#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
import threading
import requests
import logging
from datetime import datetime, timedelta

class LiveCostCalculator:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now()
        self.current_time_str = self.current_time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = os.environ.get('USER', 'varadharajaan')
        
        # EC2 Pricing API URL
        self.ec2_pricing_api_url = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/index.json"
        self.eks_pricing_api_url = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEKS/current/index.json"
        
        # Cache for pricing data (will be loaded on first use)
        self.ec2_pricing_cache = {}
        self.eks_pricing_cache = {}
        self.pricing_cache_timestamp = None
        self.pricing_cache_valid_hours = 24  # Pricing cache valid for 24 hours
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize directories
        self.setup_output_directories()
        
        # Initialize logging
        self.setup_logging()
        
        # Load AWS account configuration
        self.load_aws_accounts_config()

    def setup_output_directories(self):
        """Setup output directories for log files and results"""
        # EC2 directory
        self.ec2_output_dir = "aws/ec2/live-host"
        os.makedirs(self.ec2_output_dir, exist_ok=True)
        
        # EKS directory
        self.eks_output_dir = "aws/eks/live-host"
        os.makedirs(self.eks_output_dir, exist_ok=True)
        
        # Log directory
        self.log_dir = "aws/logs"
        os.makedirs(self.log_dir, exist_ok=True)

    def setup_logging(self):
        """Setup logging configuration"""
        self.log_filename = f"{self.log_dir}/live_cost_calculator_{self.execution_timestamp}.log"
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)8s | %(message)s',
            handlers=[
                logging.FileHandler(self.log_filename, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger('live_cost_calculator')
        self.logger.info("=" * 80)
        self.logger.info("💲 LIVE COST CALCULATOR & HEALTH METADATA SESSION STARTED")
        self.logger.info("=" * 80)
        self.logger.info(f"Execution Time: {self.current_time_str}")
        self.logger.info(f"Executed By: {self.current_user}")
        self.logger.info(f"Config File: {self.config_file}")
        self.logger.info(f"EC2 Output Directory: {self.ec2_output_dir}")
        self.logger.info(f"EKS Output Directory: {self.eks_output_dir}")
        self.logger.info(f"Log File: {self.log_filename}")
        self.logger.info("=" * 80)

    def load_aws_accounts_config(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                self.logger.error(f"Configuration file '{self.config_file}' not found")
                sys.exit(1)
                
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.aws_config = json.load(f)
            
            self.logger.info(f"✅ AWS accounts configuration loaded from: {self.config_file}")
            
            # Validate accounts
            if 'accounts' not in self.aws_config:
                self.logger.error("No 'accounts' section found in configuration")
                sys.exit(1)
            
            # Filter out accounts without valid credentials
            valid_accounts = {}
            for account_name, account_data in self.aws_config['accounts'].items():
                if (account_data.get('access_key') and 
                    account_data.get('secret_key') and
                    not account_data.get('access_key').startswith('ADD_')):
                    valid_accounts[account_name] = account_data
                else:
                    self.logger.warning(f"Skipping account with invalid credentials: {account_name}")
            
            self.aws_config['accounts'] = valid_accounts
            
            # Map account IDs to account names for easier lookup
            self.account_id_to_name = {}
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id')
                if account_id:
                    self.account_id_to_name[account_id] = account_name
            
            self.logger.info(f"📊 Valid accounts loaded: {len(valid_accounts)}")
            
            # Get default regions
            self.default_regions = self.aws_config.get('user_settings', {}).get('user_regions', 
                ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'])
            
            self.logger.info(f"📍 Default regions: {self.default_regions}")
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client for specified region"""
        try:
            return boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        except Exception as e:
            self.logger.error(f"Failed to create EC2 client for region {region}: {e}")
            return None

    def create_eks_client(self, access_key, secret_key, region):
        """Create EKS client for specified region"""
        try:
            return boto3.client(
                'eks',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        except Exception as e:
            self.logger.error(f"Failed to create EKS client for region {region}: {e}")
            return None
    
    def create_cloudwatch_client(self, access_key, secret_key, region):
        """Create CloudWatch client for specified region"""
        try:
            return boto3.client(
                'cloudwatch',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        except Exception as e:
            self.logger.error(f"Failed to create CloudWatch client for region {region}: {e}")
            return None


    def load_ec2_pricing_data(self, region_code):
        """Load EC2 pricing data for a specific region"""
        # Check if we already have cached pricing data
        if self.pricing_cache_timestamp and (datetime.now() - self.pricing_cache_timestamp).total_seconds() < (self.pricing_cache_valid_hours * 3600):
            if region_code in self.ec2_pricing_cache:
                self.logger.info(f"Using cached EC2 pricing data for {region_code}")
                return self.ec2_pricing_cache[region_code]
        
        # Map region codes to pricing API region descriptions
        region_map = {
            'us-east-1': 'US East (N. Virginia)',
            'us-east-2': 'US East (Ohio)',
            'us-west-1': 'US West (N. California)',
            'us-west-2': 'US West (Oregon)',
            'ap-south-1': 'Asia Pacific (Mumbai)',
            'ap-northeast-1': 'Asia Pacific (Tokyo)',
            'ap-northeast-2': 'Asia Pacific (Seoul)',
            'ap-northeast-3': 'Asia Pacific (Osaka)',
            'ap-southeast-1': 'Asia Pacific (Singapore)',
            'ap-southeast-2': 'Asia Pacific (Sydney)',
            'ca-central-1': 'Canada (Central)',
            'eu-central-1': 'EU (Frankfurt)',
            'eu-west-1': 'EU (Ireland)',
            'eu-west-2': 'EU (London)',
            'eu-west-3': 'EU (Paris)',
            'eu-north-1': 'EU (Stockholm)',
            'sa-east-1': 'South America (Sao Paulo)'
        }
        
        # Use the AWS Price List API instead of downloading the index file
        self.logger.info(f"Fetching EC2 pricing data for region {region_code}...")
        
        try:
               # Get credentials for the selected account
            account_name = next(iter(self.account_id_to_name.values()), None)
            if not account_name:
                self.logger.error("No valid account found for pricing API")
                return {}
            
            account_data = self.aws_config['accounts'].get(account_name)
            if not account_data:
                self.logger.error(f"Account {account_name} not found in configuration")
                return {}
            
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
        
            # Create pricing client with credentials
            pricing_client = boto3.client(
                'pricing',
                region_name= 'us-east-1',  # pricing API is only available in us-east-1
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            
            # Get EC2 pricing for Linux on-demand instances
            region_name = region_map.get(region_code, region_code)
            
            # Initialize pricing map
            pricing_map = {}
            
            # Get pricing for Linux On-Demand instances
            paginator = pricing_client.get_paginator('get_products')
            
            # Service code for EC2
            service_code = 'AmazonEC2'
            
            # Set up the filter
            filters = [
                {'Type': 'TERM_MATCH', 'Field': 'ServiceCode', 'Value': service_code},
                {'Type': 'TERM_MATCH', 'Field': 'regionCode', 'Value': region_code},
                {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
                {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                {'Type': 'TERM_MATCH', 'Field': 'capacitystatus', 'Value': 'Used'}
            ]
            
            # Get products
            page_iterator = paginator.paginate(
                ServiceCode=service_code,
                Filters=filters
            )
            
            # Process each page
            for page in page_iterator:
                for price_item in page['PriceList']:
                    price_data = json.loads(price_item)
                    
                    # Extract SKU and product attributes
                    product = price_data.get('product', {})
                    attributes = product.get('attributes', {})
                    instance_type = attributes.get('instanceType')
                    
                    # If not an instance type we're interested in, skip
                    if not instance_type:
                        continue
                    
                    # Extract price
                    terms = price_data.get('terms', {})
                    on_demand = terms.get('OnDemand', {})
                    
                    if on_demand:
                        # Get the first price dimension
                        sku_id = list(on_demand.keys())[0]
                        price_dimensions = on_demand[sku_id].get('priceDimensions', {})
                        
                        if price_dimensions:
                            dimension_id = list(price_dimensions.keys())[0]
                            price_per_unit = float(price_dimensions[dimension_id].get('pricePerUnit', {}).get('USD', '0'))
                            
                            # Store pricing information
                            if instance_type not in pricing_map or price_per_unit > 0:
                                pricing_map[instance_type] = price_per_unit
            
            # Cache the data
            if not self.pricing_cache_timestamp:
                self.pricing_cache_timestamp = datetime.now()
            
            self.ec2_pricing_cache[region_code] = pricing_map
            
            self.logger.info(f"Cached EC2 pricing data for {region_code} ({len(pricing_map)} instance types)")
            return pricing_map
            
        except Exception as e:
            self.logger.error(f"Error loading EC2 pricing data: {e}")
            
            # Try loading from a local file as fallback
            pricing_file = f"ec2_pricing_{region_code}.json"
            if os.path.exists(pricing_file):
                with open(pricing_file, 'r') as f:
                    pricing_map = json.load(f)
                self.logger.info(f"Loaded EC2 pricing from local file: {pricing_file}")
                return pricing_map
            
            # Return an empty map as last resort
            return {}

    def load_eks_pricing_data(self):
        """Load EKS pricing data"""
        # Check if we already have cached pricing data
        if self.pricing_cache_timestamp and (datetime.now() - self.pricing_cache_timestamp).total_seconds() < (self.pricing_cache_valid_hours * 3600):
            if self.eks_pricing_cache:
                self.logger.info("Using cached EKS pricing data")
                return self.eks_pricing_cache
        
        self.logger.info("Fetching EKS pricing data...")
        
        try:
                # Get credentials for the selected account
            account_name = next(iter(self.account_id_to_name.values()), None)
            if not account_name:
                self.logger.error("No valid account found for pricing API")
                return {}
            
            account_data = self.aws_config['accounts'].get(account_name)
            if not account_data:
                self.logger.error(f"Account {account_name} not found in configuration")
                return {}
            
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
        
            # Create pricing client with credentials
            pricing_client = boto3.client(
                'pricing',
                region_name='us-east-1',  # pricing API is only available in us-east-1
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            
            # Get EKS pricing
            paginator = pricing_client.get_paginator('get_products')
            
            # Service code for EKS
            service_code = 'AmazonEKS'
            
            # Set up the filter
            filters = [
                {'Type': 'TERM_MATCH', 'Field': 'ServiceCode', 'Value': service_code}
            ]
            
            # Get products
            page_iterator = paginator.paginate(
                ServiceCode=service_code,
                Filters=filters
            )
            
            # Initialize pricing map by region
            pricing_map = {}
            
            # Process each page
            for page in page_iterator:
                for price_item in page['PriceList']:
                    price_data = json.loads(price_item)
                    
                    # Extract SKU and product attributes
                    product = price_data.get('product', {})
                    attributes = product.get('attributes', {})
                    region = attributes.get('regionCode')
                    
                    if not region:
                        continue
                    
                    # Initialize region in pricing map if not exists
                    if region not in pricing_map:
                        pricing_map[region] = {}
                    
                    # Extract price
                    terms = price_data.get('terms', {})
                    on_demand = terms.get('OnDemand', {})
                    
                    if on_demand:
                        # Get the first price dimension
                        sku_id = list(on_demand.keys())[0]
                        price_dimensions = on_demand[sku_id].get('priceDimensions', {})
                        
                        if price_dimensions:
                            dimension_id = list(price_dimensions.keys())[0]
                            price_per_unit = float(price_dimensions[dimension_id].get('pricePerUnit', {}).get('USD', '0'))
                            
                            # Get control plane price (per hour)
                            if 'Cluster' in attributes.get('usagetype', ''):
                                pricing_map[region]['control_plane'] = price_per_unit
            
            # Cache the data
            if not self.pricing_cache_timestamp:
                self.pricing_cache_timestamp = datetime.now()
            
            self.eks_pricing_cache = pricing_map
            
            self.logger.info(f"Cached EKS pricing data for {len(pricing_map)} regions")
            return pricing_map
            
        except Exception as e:
            self.logger.error(f"Error loading EKS pricing data: {e}")
            
            # Try loading from a local file as fallback
            pricing_file = "eks_pricing.json"
            if os.path.exists(pricing_file):
                with open(pricing_file, 'r') as f:
                    pricing_map = json.load(f)
                self.logger.info(f"Loaded EKS pricing from local file: {pricing_file}")
                return pricing_map
            
            # Return an empty map as last resort
            return {}

    def get_ec2_instance_health(self, ec2_client, cloudwatch_client, instance_id):
        """Get EC2 instance health metadata"""
        health_data = {
            "status": "Unknown",
            "status_checks": {
                "system": "Unknown",
                "instance": "Unknown"
            },
            "cpu_utilization": None,
            "memory_utilization": None,
            "last_checked": self.current_time_str
        }
        
        try:
            # Get instance status
            response = ec2_client.describe_instance_status(InstanceIds=[instance_id])
            
            if response['InstanceStatuses']:
                status_info = response['InstanceStatuses'][0]
                
                # Overall status
                health_data["status"] = status_info['InstanceState']['Name']
                
                # Status checks
                if 'SystemStatus' in status_info:
                    health_data["status_checks"]["system"] = status_info['SystemStatus']['Status']
                
                if 'InstanceStatus' in status_info:
                    health_data["status_checks"]["instance"] = status_info['InstanceStatus']['Status']
            
            # Get CloudWatch metrics for the instance
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=1)
            
            # Get CPU utilization
            try:
                cpu_response = cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/EC2',
                    MetricName='CPUUtilization',
                    Dimensions=[
                        {
                            'Name': 'InstanceId',
                            'Value': instance_id
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=300,  # 5-minute intervals
                    Statistics=['Average']
                )
                
                if cpu_response['Datapoints']:
                    # Get the latest datapoint
                    latest_datapoint = max(cpu_response['Datapoints'], key=lambda x: x['Timestamp'])
                    health_data["cpu_utilization"] = round(latest_datapoint['Average'], 2)
            except Exception as e:
                self.logger.warning(f"Could not get CPU utilization for instance {instance_id}: {e}")
            
            # Try to get memory utilization if available
            try:
                memory_response = cloudwatch_client.get_metric_statistics(
                    Namespace='CWAgent',
                    MetricName='mem_used_percent',
                    Dimensions=[
                        {
                            'Name': 'InstanceId',
                            'Value': instance_id
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=300,  # 5-minute intervals
                    Statistics=['Average']
                )
                
                if memory_response['Datapoints']:
                    # Get the latest datapoint
                    latest_datapoint = max(memory_response['Datapoints'], key=lambda x: x['Timestamp'])
                    health_data["memory_utilization"] = round(latest_datapoint['Average'], 2)
            except Exception:
                # Memory metrics might not be available if CloudWatch agent isn't installed
                pass
            
        except Exception as e:
            self.logger.warning(f"Error getting health data for instance {instance_id}: {e}")
            health_data["status"] = "Error"
        
        return health_data

    def calculate_ec2_costs(self, account_selection, region_selection, ec2_selection=None):
        """Calculate costs for EC2 instances"""
        self.logger.info(f"Calculating EC2 costs for account {account_selection} in regions: {region_selection}")

        results = {
            "account_id": account_selection,
            "account_name": self.account_id_to_name.get(account_selection, "Unknown"),
            "regions": {},
            "total_cost": 0.0,
            "currency": "USD",
            "calculated_at": self.current_time_str,
            "instance_count": 0
        }

        # Get account credentials
        account_name = self.account_id_to_name.get(account_selection)
        if not account_name:
            self.logger.error(f"Account ID {account_selection} not found in configuration")
            return results

        account_data = self.aws_config['accounts'].get(account_name)
        if not account_data:
            self.logger.error(f"Account {account_name} not found in configuration")
            return results

        access_key = account_data['access_key']
        secret_key = account_data['secret_key']

        # Process each region
        for region in region_selection:
            self.logger.info(f"Processing region: {region}")

            region_results = {
                "instances": [],
                "total_cost": 0.0,
                "instance_count": 0
            }

            # Create clients
            ec2_client = self.create_ec2_client(access_key, secret_key, region)
            if not ec2_client:
                self.logger.error(f"Could not create EC2 client for region {region}")
                continue

            cloudwatch_client = self.create_cloudwatch_client(access_key, secret_key, region)
            if not cloudwatch_client:
                self.logger.warning(f"Could not create CloudWatch client for region {region}")

            # Load pricing data
            pricing_data = self.load_ec2_pricing_data(region)

            # Get instances
            try:
                if ec2_selection and ec2_selection != 'all':
                    # Get specific instances
                    instance_ids = ec2_selection if isinstance(ec2_selection, list) else [ec2_selection]
                    response = ec2_client.describe_instances(InstanceIds=instance_ids)
                else:
                    # Get all instances
                    response = ec2_client.describe_instances()

                # Process each reservation and instance
                for reservation in response.get('Reservations', []):
                    for instance in reservation.get('Instances', []):
                        instance_id = instance['InstanceId']
                        instance_type = instance['InstanceType']
                        state = instance['State']['Name']

                        # Only calculate costs for running instances
                        if state != 'running':
                            self.logger.info(f"Skipping instance {instance_id} with state: {state}")
                            continue

                        # Get instance name from tags
                        instance_name = 'Unnamed'
                        for tag in instance.get('Tags', []):
                            if tag['Key'] == 'Name':
                                instance_name = tag['Value']
                                break

                        # Calculate uptime based on launch time
                        launch_time = instance['LaunchTime']
                        uptime_hours = (self.current_time - launch_time.replace(tzinfo=None)).total_seconds() / 3600

                        # Get hourly rate from pricing data
                        hourly_rate = pricing_data.get(instance_type, 0.0)

                        # Calculate cost
                        estimated_cost = round(uptime_hours * hourly_rate, 2)

                        # Get instance health
                        health_data = self.get_ec2_instance_health(ec2_client, cloudwatch_client, instance_id)

                        # Add instance to results
                        instance_info = {
                            "instance_id": instance_id,
                            "instance_name": instance_name,
                            "instance_type": instance_type,
                            "state": state,
                            "launch_time": launch_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "uptime_hours": round(uptime_hours, 2),
                            "hourly_rate": hourly_rate,
                            "estimated_cost": estimated_cost,
                            "health": health_data
                        }

                        region_results["instances"].append(instance_info)
                        region_results["total_cost"] += estimated_cost
                        region_results["instance_count"] += 1

                        self.logger.info(
                            f"Calculated cost for instance {instance_id} ({instance_type}): ${estimated_cost} for {round(uptime_hours, 2)} hours")

            except Exception as e:
                self.logger.error(f"Error getting EC2 instances in {region}: {e}")

            # Update region and total results
            results["regions"][region] = region_results
            results["total_cost"] += region_results["total_cost"]
            results["instance_count"] += region_results["instance_count"]

        # Save results to file with proper directory creation
        account_save_name = self.account_id_to_name.get(account_selection, "Unknown")
        account_output_dir = f"{self.ec2_output_dir}/{account_save_name}"

        # Create directory if it doesn't exist
        try:
            os.makedirs(account_output_dir, exist_ok=True)
            self.logger.info(f"Created/verified directory: {account_output_dir}")
        except Exception as e:
            self.logger.error(f"Failed to create directory {account_output_dir}: {e}")
            # Fallback to parent directory
            account_output_dir = self.ec2_output_dir
            os.makedirs(account_output_dir, exist_ok=True)

        output_file = f"{account_output_dir}/ec2_cost_{account_save_name}_{self.execution_timestamp}.json"

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, default=str)
            self.logger.info(f"EC2 cost calculation saved to: {output_file}")
        except Exception as e:
            self.logger.error(f"Failed to save EC2 results to {output_file}: {e}")

        self.logger.info(f"Total EC2 cost: ${results['total_cost']:.2f} for {results['instance_count']} instances")

        return results

    def calculate_historical_costs(self, account_selection, region_selection, hours_back=9):
        """Calculate costs for the last N hours"""
        self.logger.info(f"Calculating historical costs for last {hours_back} hours")

        historical_results = {
            "account_id": account_selection,
            "account_name": self.account_id_to_name.get(account_selection, "Unknown"),
            "analysis_period": f"Last {hours_back} hours",
            "start_time": (self.current_time - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": self.current_time_str,
            "regions": {},
            "total_historical_cost": 0.0,
            "hourly_breakdown": []
        }

        # Get account credentials
        account_name = self.account_id_to_name.get(account_selection)
        if not account_name:
            return historical_results

        account_data = self.aws_config['accounts'].get(account_name)
        if not account_data:
            return historical_results

        access_key = account_data['access_key']
        secret_key = account_data['secret_key']

        # Process each region
        for region in region_selection:
            self.logger.info(f"Analyzing historical costs for region: {region}")

            region_results = {
                "ec2_instances": [],
                "eks_clusters": [],
                "total_cost": 0.0,
                "hourly_costs": []
            }

            # Create clients
            ec2_client = self.create_ec2_client(access_key, secret_key, region)
            eks_client = self.create_eks_client(access_key, secret_key, region)
            cloudwatch_client = self.create_cloudwatch_client(access_key, secret_key, region)

            if not ec2_client or not cloudwatch_client:
                continue

            # Load pricing data
            ec2_pricing = self.load_ec2_pricing_data(region)
            eks_pricing = self.load_eks_pricing_data().get(region, {})

            # Analyze EC2 historical costs
            ec2_historical = self.analyze_ec2_historical_costs(
                ec2_client, cloudwatch_client, ec2_pricing, hours_back
            )
            region_results["ec2_instances"] = ec2_historical["instances"]
            region_results["total_cost"] += ec2_historical["total_cost"]

            # Analyze EKS historical costs
            if eks_client:
                eks_historical = self.analyze_eks_historical_costs(
                    eks_client, ec2_client, cloudwatch_client, ec2_pricing, eks_pricing, hours_back
                )
                region_results["eks_clusters"] = eks_historical["clusters"]
                region_results["total_cost"] += eks_historical["total_cost"]

            # Generate hourly breakdown for this region
            region_results["hourly_costs"] = self.generate_hourly_breakdown(
                region_results["ec2_instances"], region_results["eks_clusters"], hours_back
            )

            historical_results["regions"][region] = region_results
            historical_results["total_historical_cost"] += region_results["total_cost"]

        # Generate overall hourly breakdown
        historical_results["hourly_breakdown"] = self.generate_overall_hourly_breakdown(
            historical_results["regions"], hours_back
        )

        return historical_results

    def calculate_forecast_costs(self, account_selection, region_selection, hours_ahead=9):
        """Calculate forecasted costs for the next N hours"""
        self.logger.info(f"Calculating cost forecast for next {hours_ahead} hours")

        forecast_results = {
            "account_id": account_selection,
            "account_name": self.account_id_to_name.get(account_selection, "Unknown"),
            "forecast_period": f"Next {hours_ahead} hours",
            "start_time": self.current_time_str,
            "end_time": (self.current_time + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d %H:%M:%S"),
            "regions": {},
            "total_forecast_cost": 0.0,
            "hourly_forecast": [],
            "confidence_level": "85%",
            "forecast_method": "Linear projection based on current usage"
        }

        # Get account credentials
        account_name = self.account_id_to_name.get(account_selection)
        if not account_name:
            return forecast_results

        account_data = self.aws_config['accounts'].get(account_name)
        if not account_data:
            return forecast_results

        access_key = account_data['access_key']
        secret_key = account_data['secret_key']

        # Process each region
        for region in region_selection:
            self.logger.info(f"Generating cost forecast for region: {region}")

            region_results = {
                "ec2_forecast": [],
                "eks_forecast": [],
                "total_forecast_cost": 0.0,
                "hourly_forecast": []
            }

            # Create clients
            ec2_client = self.create_ec2_client(access_key, secret_key, region)
            eks_client = self.create_eks_client(access_key, secret_key, region)
            cloudwatch_client = self.create_cloudwatch_client(access_key, secret_key, region)

            if not ec2_client:
                continue

            # Load pricing data
            ec2_pricing = self.load_ec2_pricing_data(region)
            eks_pricing = self.load_eks_pricing_data().get(region, {})

            # Generate EC2 forecast
            ec2_forecast = self.generate_ec2_forecast(
                ec2_client, cloudwatch_client, ec2_pricing, hours_ahead
            )
            region_results["ec2_forecast"] = ec2_forecast["instances"]
            region_results["total_forecast_cost"] += ec2_forecast["total_cost"]

            # Generate EKS forecast
            if eks_client:
                eks_forecast = self.generate_eks_forecast(
                    eks_client, ec2_client, ec2_pricing, eks_pricing, hours_ahead
                )
                region_results["eks_forecast"] = eks_forecast["clusters"]
                region_results["total_forecast_cost"] += eks_forecast["total_cost"]

            # Generate hourly forecast for this region
            region_results["hourly_forecast"] = self.generate_hourly_forecast(
                region_results["ec2_forecast"], region_results["eks_forecast"], hours_ahead
            )

            forecast_results["regions"][region] = region_results
            forecast_results["total_forecast_cost"] += region_results["total_forecast_cost"]

        # Generate overall hourly forecast
        forecast_results["hourly_forecast"] = self.generate_overall_hourly_forecast(
            forecast_results["regions"], hours_ahead
        )

        return forecast_results

    def analyze_nodegroup_historical_cost(self, eks_client, ec2_client, cluster_name, nodegroup_name, ec2_pricing,
                                          start_time, end_time):
        """Analyze historical cost for a specific nodegroup"""
        try:
            # Get nodegroup details
            nodegroup_info = eks_client.describe_nodegroup(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name
            )['nodegroup']

            ng_status = nodegroup_info['status']
            ng_created_at = nodegroup_info['createdAt'].replace(tzinfo=None)
            ng_instance_types = nodegroup_info.get('instanceTypes', [])
            ng_scaling_config = nodegroup_info.get('scalingConfig', {})

            # Calculate analysis period for this nodegroup
            analysis_start = max(start_time, ng_created_at)
            analysis_end = end_time

            if analysis_start >= analysis_end:
                return {
                    "nodegroup_name": nodegroup_name,
                    "status": ng_status,
                    "cost": 0.0,
                    "running_hours": 0.0,
                    "instances": [],
                    "reason": "Nodegroup was not active during analysis period"
                }

            running_hours = (analysis_end - analysis_start).total_seconds() / 3600

            # Find instances belonging to this nodegroup
            instance_costs = []
            total_cost = 0.0

            # Try to find instances using Auto Scaling Groups
            if 'resources' in nodegroup_info and 'autoScalingGroups' in nodegroup_info['resources']:
                for asg in nodegroup_info['resources']['autoScalingGroups']:
                    asg_name = asg.get('name')
                    if asg_name:
                        try:
                            # Create autoscaling client
                            access_key = None
                            secret_key = None
                            region = ec2_client.meta.region_name

                            # Get credentials from the first account (you may need to pass these properly)
                            account_name = next(iter(self.aws_config['accounts'].keys()))
                            account_data = self.aws_config['accounts'][account_name]
                            access_key = account_data['access_key']
                            secret_key = account_data['secret_key']

                            autoscaling_client = boto3.client(
                                'autoscaling',
                                aws_access_key_id=access_key,
                                aws_secret_access_key=secret_key,
                                region_name=region
                            )

                            asg_response = autoscaling_client.describe_auto_scaling_groups(
                                AutoScalingGroupNames=[asg_name]
                            )

                            for asg_detail in asg_response.get('AutoScalingGroups', []):
                                for instance in asg_detail.get('Instances', []):
                                    instance_id = instance['InstanceId']

                                    # Get instance details
                                    try:
                                        ec2_response = ec2_client.describe_instances(InstanceIds=[instance_id])
                                        for reservation in ec2_response.get('Reservations', []):
                                            for ec2_instance in reservation.get('Instances', []):
                                                instance_type = ec2_instance['InstanceType']
                                                hourly_rate = ec2_pricing.get(instance_type, 0.0)
                                                instance_cost = running_hours * hourly_rate

                                                instance_costs.append({
                                                    "instance_id": instance_id,
                                                    "instance_type": instance_type,
                                                    "hourly_rate": hourly_rate,
                                                    "running_hours": round(running_hours, 2),
                                                    "cost": round(instance_cost, 2)
                                                })

                                                total_cost += instance_cost
                                    except Exception as e:
                                        self.logger.warning(f"Could not get details for instance {instance_id}: {e}")
                        except Exception as e:
                            self.logger.warning(f"Could not get ASG details for {asg_name}: {e}")

            # If no instances found via ASG, estimate based on desired capacity and instance types
            if not instance_costs:
                desired_size = ng_scaling_config.get('desiredSize', 0)
                if desired_size > 0 and ng_instance_types:
                    # Use the first instance type for estimation
                    primary_instance_type = ng_instance_types[0]
                    hourly_rate = ec2_pricing.get(primary_instance_type, 0.096)  # Default to m5.large rate
                    estimated_cost = desired_size * hourly_rate * running_hours

                    instance_costs.append({
                        "estimated": True,
                        "instance_type": primary_instance_type,
                        "count": desired_size,
                        "hourly_rate": hourly_rate,
                        "running_hours": round(running_hours, 2),
                        "cost": round(estimated_cost, 2)
                    })

                    total_cost = estimated_cost

            return {
                "nodegroup_name": nodegroup_name,
                "status": ng_status,
                "cost": round(total_cost, 2),
                "running_hours": round(running_hours, 2),
                "instances": instance_costs,
                "instance_types": ng_instance_types,
                "scaling_config": ng_scaling_config,
                "created_at": ng_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "analysis_period": f"{analysis_start.strftime('%H:%M')} - {analysis_end.strftime('%H:%M')}"
            }

        except Exception as e:
            self.logger.error(f"Error analyzing nodegroup {nodegroup_name}: {e}")
            return {
                "nodegroup_name": nodegroup_name,
                "status": "ERROR",
                "cost": 0.0,
                "running_hours": 0.0,
                "instances": [],
                "error": str(e)
            }

    def forecast_nodegroup_cost(self, eks_client, ec2_client, cluster_name, nodegroup_name, ec2_pricing, hours_ahead):
        """Forecast cost for a specific nodegroup"""
        try:
            # Get nodegroup details
            nodegroup_info = eks_client.describe_nodegroup(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name
            )['nodegroup']

            ng_status = nodegroup_info['status']
            ng_instance_types = nodegroup_info.get('instanceTypes', [])
            ng_scaling_config = nodegroup_info.get('scalingConfig', {})

            if ng_status != 'ACTIVE':
                return {
                    "nodegroup_name": nodegroup_name,
                    "status": ng_status,
                    "cost": 0.0,
                    "forecast_hours": hours_ahead,
                    "instances": [],
                    "assumption": f"Nodegroup is {ng_status}, not forecasting"
                }

            # Get current instance count
            desired_size = ng_scaling_config.get('desiredSize', 0)

            forecast_instances = []
            total_forecast_cost = 0.0

            # Forecast based on current configuration
            if desired_size > 0 and ng_instance_types:
                for instance_type in ng_instance_types:
                    hourly_rate = ec2_pricing.get(instance_type, 0.096)

                    # Assume equal distribution across instance types
                    instances_of_this_type = max(1, desired_size // len(ng_instance_types))
                    if ng_instance_types.index(instance_type) < (desired_size % len(ng_instance_types)):
                        instances_of_this_type += 1

                    type_forecast_cost = instances_of_this_type * hourly_rate * hours_ahead

                    forecast_instances.append({
                        "instance_type": instance_type,
                        "count": instances_of_this_type,
                        "hourly_rate": hourly_rate,
                        "forecast_hours": hours_ahead,
                        "forecast_cost": round(type_forecast_cost, 2)
                    })

                    total_forecast_cost += type_forecast_cost

            return {
                "nodegroup_name": nodegroup_name,
                "status": ng_status,
                "cost": round(total_forecast_cost, 2),
                "forecast_hours": hours_ahead,
                "instances": forecast_instances,
                "instance_types": ng_instance_types,
                "scaling_config": ng_scaling_config,
                "assumption": "Current configuration maintained",
                "confidence": "85%"
            }

        except Exception as e:
            self.logger.error(f"Error forecasting nodegroup {nodegroup_name}: {e}")
            return {
                "nodegroup_name": nodegroup_name,
                "status": "ERROR",
                "cost": 0.0,
                "forecast_hours": hours_ahead,
                "instances": [],
                "error": str(e)
            }

    def get_recent_cpu_trend(self, cloudwatch_client, instance_id):
        """Get recent CPU utilization trend for forecast confidence calculation"""
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=3)  # Last 3 hours

            response = cloudwatch_client.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=900,  # 15-minute intervals
                Statistics=['Average']
            )

            if response['Datapoints']:
                datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
                values = [dp['Average'] for dp in datapoints]

                return {
                    "values": values,
                    "average": round(sum(values) / len(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                    "trend": "stable" if max(values) - min(values) < 20 else "variable"
                }
        except Exception as e:
            self.logger.warning(f"Could not get CPU trend for {instance_id}: {e}")

        return {
            "values": [],
            "average": 0,
            "min": 0,
            "max": 0,
            "trend": "unknown"
        }

    def calculate_forecast_confidence(self, cpu_trend):
        """Calculate forecast confidence based on CPU trend stability"""
        if not cpu_trend or not cpu_trend.get('values'):
            return "60%"  # Low confidence if no data

        trend_type = cpu_trend.get('trend', 'unknown')
        average_cpu = cpu_trend.get('average', 0)

        if trend_type == "stable" and 10 <= average_cpu <= 80:
            return "90%"  # High confidence for stable, normal utilization
        elif trend_type == "stable":
            return "85%"  # Good confidence for stable utilization
        elif trend_type == "variable" and average_cpu < 90:
            return "75%"  # Medium confidence for variable but not overloaded
        else:
            return "65%"  # Lower confidence for highly variable or overloaded instances

    def generate_overall_hourly_breakdown(self, regions_data, hours):
        """Generate overall hourly breakdown across all regions"""
        hourly_breakdown = []

        for hour in range(hours):
            hour_start = self.current_time - timedelta(hours=hours - hour)

            hour_data = {
                "hour": hour_start.strftime("%H:00"),
                "timestamp": hour_start.strftime("%Y-%m-%d %H:%M:%S"),
                "total_cost": 0.0,
                "ec2_cost": 0.0,
                "eks_cost": 0.0,
                "regions": {}
            }

            # Aggregate costs from all regions
            for region, region_data in regions_data.items():
                region_cost = {
                    "ec2": 0.0,
                    "eks": 0.0,
                    "total": 0.0
                }

                # Add EC2 costs for this hour
                for instance in region_data.get("ec2_instances", []):
                    if instance.get("running_hours", 0) > hour:
                        instance_hourly = instance.get("hourly_rate", 0)
                        region_cost["ec2"] += instance_hourly
                        hour_data["ec2_cost"] += instance_hourly

                # Add EKS costs for this hour
                for cluster in region_data.get("eks_clusters", []):
                    if cluster.get("running_hours", 0) > hour:
                        # Control plane cost (constant per hour)
                        control_plane_hourly = 0.10  # $0.10 per hour
                        region_cost["eks"] += control_plane_hourly
                        hour_data["eks_cost"] += control_plane_hourly

                        # Worker nodes cost
                        worker_cost = cluster.get("nodegroups_cost", 0)
                        if cluster.get("running_hours", 0) > 0:
                            worker_hourly = worker_cost / cluster.get("running_hours", 1)
                            region_cost["eks"] += worker_hourly
                            hour_data["eks_cost"] += worker_hourly

                region_cost["total"] = region_cost["ec2"] + region_cost["eks"]
                hour_data["regions"][region] = region_cost

            hour_data["total_cost"] = hour_data["ec2_cost"] + hour_data["eks_cost"]
            hourly_breakdown.append(hour_data)

        return hourly_breakdown

    def generate_overall_hourly_forecast(self, regions_data, hours):
        """Generate overall hourly forecast across all regions"""
        hourly_forecast = []

        for hour in range(hours):
            hour_start = self.current_time + timedelta(hours=hour)

            hour_data = {
                "hour": hour_start.strftime("%H:00"),
                "timestamp": hour_start.strftime("%Y-%m-%d %H:%M:%S"),
                "total_cost": 0.0,
                "ec2_cost": 0.0,
                "eks_cost": 0.0,
                "regions": {}
            }

            # Aggregate forecast costs from all regions
            for region, region_data in regions_data.items():
                region_cost = {
                    "ec2": 0.0,
                    "eks": 0.0,
                    "total": 0.0
                }

                # Add EC2 forecast costs for this hour
                for instance in region_data.get("ec2_forecast", []):
                    instance_hourly = instance.get("hourly_rate", 0)
                    region_cost["ec2"] += instance_hourly
                    hour_data["ec2_cost"] += instance_hourly

                # Add EKS forecast costs for this hour
                for cluster in region_data.get("eks_forecast", []):
                    # Control plane cost (constant per hour)
                    control_plane_hourly = 0.10  # $0.10 per hour
                    region_cost["eks"] += control_plane_hourly
                    hour_data["eks_cost"] += control_plane_hourly

                    # Worker nodes forecast cost
                    worker_forecast = cluster.get("nodegroups_forecast", 0)
                    if cluster.get("forecast_hours", 0) > 0:
                        worker_hourly = worker_forecast / cluster.get("forecast_hours", 1)
                        region_cost["eks"] += worker_hourly
                        hour_data["eks_cost"] += worker_hourly

                region_cost["total"] = region_cost["ec2"] + region_cost["eks"]
                hour_data["regions"][region] = region_cost

            hour_data["total_cost"] = hour_data["ec2_cost"] + hour_data["eks_cost"]
            hourly_forecast.append(hour_data)

        return hourly_forecast

    def generate_hourly_forecast(self, ec2_forecast, eks_forecast, hours):
        """Generate hourly forecast for a specific region"""
        hourly_forecast = []

        for hour in range(hours):
            hour_start = self.current_time + timedelta(hours=hour)

            hour_data = {
                "hour": hour_start.strftime("%H:00"),
                "timestamp": hour_start.strftime("%Y-%m-%d %H:%M:%S"),
                "ec2_cost": 0.0,
                "eks_cost": 0.0,
                "total_cost": 0.0
            }

            # Calculate EC2 cost for this hour
            for instance in ec2_forecast:
                hour_data["ec2_cost"] += instance.get("hourly_rate", 0)

            # Calculate EKS cost for this hour
            for cluster in eks_forecast:
                # Control plane: $0.10/hour
                hour_data["eks_cost"] += 0.10

                # Worker nodes
                if cluster.get("forecast_hours", 0) > 0:
                    worker_hourly = cluster.get("nodegroups_forecast", 0) / cluster.get("forecast_hours", 1)
                    hour_data["eks_cost"] += worker_hourly

            hour_data["total_cost"] = hour_data["ec2_cost"] + hour_data["eks_cost"]
            hourly_forecast.append(hour_data)

        return hourly_forecast


    def analyze_ec2_historical_costs(self, ec2_client, cloudwatch_client, ec2_pricing, hours_back):
        """Analyze EC2 historical costs"""
        results = {"instances": [], "total_cost": 0.0}

        try:
            # Get all running instances
            response = ec2_client.describe_instances(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
            )

            end_time = self.current_time
            start_time = end_time - timedelta(hours=hours_back)

            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_id = instance['InstanceId']
                    instance_type = instance['InstanceType']
                    launch_time = instance['LaunchTime'].replace(tzinfo=None)

                    # Calculate the actual running time in the analysis period
                    analysis_start = max(start_time, launch_time)
                    analysis_end = end_time

                    if analysis_start >= analysis_end:
                        continue  # Instance was not running during analysis period

                    running_hours = (analysis_end - analysis_start).total_seconds() / 3600
                    hourly_rate = ec2_pricing.get(instance_type, 0.0)
                    historical_cost = running_hours * hourly_rate

                    # Get instance name
                    instance_name = 'Unnamed'
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            instance_name = tag['Value']
                            break

                    # Get CPU utilization trend
                    cpu_trend = self.get_cpu_utilization_trend(
                        cloudwatch_client, instance_id, start_time, end_time
                    )

                    instance_data = {
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "running_hours": round(running_hours, 2),
                        "hourly_rate": hourly_rate,
                        "historical_cost": round(historical_cost, 2),
                        "cpu_trend": cpu_trend,
                        "launch_time": launch_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "analysis_period": f"{analysis_start.strftime('%H:%M')} - {analysis_end.strftime('%H:%M')}"
                    }

                    results["instances"].append(instance_data)
                    results["total_cost"] += historical_cost

        except Exception as e:
            self.logger.error(f"Error analyzing EC2 historical costs: {e}")

        return results

    def analyze_eks_historical_costs(self, eks_client, ec2_client, cloudwatch_client, ec2_pricing, eks_pricing,
                                     hours_back):
        """Analyze EKS historical costs"""
        results = {"clusters": [], "total_cost": 0.0}

        try:
            # Get all active clusters
            clusters_response = eks_client.list_clusters()

            end_time = self.current_time
            start_time = end_time - timedelta(hours=hours_back)
            control_plane_hourly = eks_pricing.get('control_plane', 0.10)

            for cluster_name in clusters_response.get('clusters', []):
                try:
                    cluster_info = eks_client.describe_cluster(name=cluster_name)['cluster']

                    if cluster_info['status'] != 'ACTIVE':
                        continue

                    created_at = cluster_info['createdAt'].replace(tzinfo=None)

                    # Calculate control plane cost for the analysis period
                    analysis_start = max(start_time, created_at)
                    analysis_end = end_time

                    if analysis_start >= analysis_end:
                        continue

                    running_hours = (analysis_end - analysis_start).total_seconds() / 3600
                    control_plane_cost = running_hours * control_plane_hourly

                    # Analyze nodegroups
                    nodegroups_cost = 0.0
                    nodegroups_data = []

                    nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)

                    for nodegroup_name in nodegroups_response.get('nodegroups', []):
                        ng_cost = self.analyze_nodegroup_historical_cost(
                            eks_client, ec2_client, cluster_name, nodegroup_name,
                            ec2_pricing, start_time, end_time
                        )
                        nodegroups_cost += ng_cost["cost"]
                        nodegroups_data.append(ng_cost)

                    total_cluster_cost = control_plane_cost + nodegroups_cost

                    cluster_data = {
                        "cluster_name": cluster_name,
                        "version": cluster_info['version'],
                        "running_hours": round(running_hours, 2),
                        "control_plane_cost": round(control_plane_cost, 2),
                        "nodegroups_cost": round(nodegroups_cost, 2),
                        "total_cost": round(total_cluster_cost, 2),
                        "nodegroups": nodegroups_data,
                        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "analysis_period": f"{analysis_start.strftime('%H:%M')} - {analysis_end.strftime('%H:%M')}"
                    }

                    results["clusters"].append(cluster_data)
                    results["total_cost"] += total_cluster_cost

                except Exception as e:
                    self.logger.error(f"Error analyzing cluster {cluster_name}: {e}")

        except Exception as e:
            self.logger.error(f"Error analyzing EKS historical costs: {e}")

        return results

    def generate_ec2_forecast(self, ec2_client, cloudwatch_client, ec2_pricing, hours_ahead):
        """Generate EC2 cost forecast"""
        results = {"instances": [], "total_cost": 0.0}

        try:
            # Get all running instances
            response = ec2_client.describe_instances(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
            )

            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_id = instance['InstanceId']
                    instance_type = instance['InstanceType']
                    hourly_rate = ec2_pricing.get(instance_type, 0.0)

                    # Simple forecast: assume instance continues running
                    forecast_cost = hours_ahead * hourly_rate

                    # Get instance name
                    instance_name = 'Unnamed'
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            instance_name = tag['Value']
                            break

                    # Get recent CPU trend for confidence level
                    cpu_trend = self.get_recent_cpu_trend(cloudwatch_client, instance_id)
                    confidence = self.calculate_forecast_confidence(cpu_trend)

                    instance_forecast = {
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "forecast_hours": hours_ahead,
                        "hourly_rate": hourly_rate,
                        "forecast_cost": round(forecast_cost, 2),
                        "confidence": confidence,
                        "assumption": "Continues running at current rate"
                    }

                    results["instances"].append(instance_forecast)
                    results["total_cost"] += forecast_cost

        except Exception as e:
            self.logger.error(f"Error generating EC2 forecast: {e}")

        return results

    def generate_eks_forecast(self, eks_client, ec2_client, ec2_pricing, eks_pricing, hours_ahead):
        """Generate EKS cost forecast"""
        results = {"clusters": [], "total_cost": 0.0}

        try:
            # Get all active clusters
            clusters_response = eks_client.list_clusters()
            control_plane_hourly = eks_pricing.get('control_plane', 0.10)

            for cluster_name in clusters_response.get('clusters', []):
                try:
                    cluster_info = eks_client.describe_cluster(name=cluster_name)['cluster']

                    if cluster_info['status'] != 'ACTIVE':
                        continue

                    # Control plane forecast
                    control_plane_forecast = hours_ahead * control_plane_hourly

                    # Nodegroups forecast
                    nodegroups_forecast = 0.0
                    nodegroups_data = []

                    nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)

                    for nodegroup_name in nodegroups_response.get('nodegroups', []):
                        ng_forecast = self.forecast_nodegroup_cost(
                            eks_client, ec2_client, cluster_name, nodegroup_name,
                            ec2_pricing, hours_ahead
                        )
                        nodegroups_forecast += ng_forecast["cost"]
                        nodegroups_data.append(ng_forecast)

                    total_forecast = control_plane_forecast + nodegroups_forecast

                    cluster_forecast = {
                        "cluster_name": cluster_name,
                        "version": cluster_info['version'],
                        "forecast_hours": hours_ahead,
                        "control_plane_forecast": round(control_plane_forecast, 2),
                        "nodegroups_forecast": round(nodegroups_forecast, 2),
                        "total_forecast": round(total_forecast, 2),
                        "nodegroups": nodegroups_data,
                        "confidence": "85%",
                        "assumption": "Current configuration maintained"
                    }

                    results["clusters"].append(cluster_forecast)
                    results["total_cost"] += total_forecast

                except Exception as e:
                    self.logger.error(f"Error forecasting cluster {cluster_name}: {e}")

        except Exception as e:
            self.logger.error(f"Error generating EKS forecast: {e}")

        return results

    def get_cpu_utilization_trend(self, cloudwatch_client, instance_id, start_time, end_time):
        """Get CPU utilization trend for an instance"""
        try:
            response = cloudwatch_client.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,  # 1-hour periods
                Statistics=['Average']
            )

            if response['Datapoints']:
                datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
                trend = [round(dp['Average'], 2) for dp in datapoints]
                return {
                    "values": trend,
                    "average": round(sum(trend) / len(trend), 2),
                    "min": min(trend),
                    "max": max(trend)
                }
        except Exception as e:
            self.logger.warning(f"Could not get CPU trend for {instance_id}: {e}")

        return {"values": [], "average": 0, "min": 0, "max": 0}

    def generate_hourly_breakdown(self, ec2_instances, eks_clusters, hours):
        """Generate hourly cost breakdown"""
        hourly_breakdown = []

        for hour in range(hours):
            hour_start = self.current_time - timedelta(hours=hours - hour)
            hour_end = hour_start + timedelta(hours=1)

            hour_data = {
                "hour": hour_start.strftime("%H:00"),
                "timestamp": hour_start.strftime("%Y-%m-%d %H:%M:%S"),
                "ec2_cost": 0.0,
                "eks_cost": 0.0,
                "total_cost": 0.0
            }

            # Calculate EC2 cost for this hour
            for instance in ec2_instances:
                if instance["running_hours"] > hour:
                    hour_data["ec2_cost"] += instance["hourly_rate"]

            # Calculate EKS cost for this hour
            for cluster in eks_clusters:
                if cluster["running_hours"] > hour:
                    hour_data["eks_cost"] += (cluster["control_plane_cost"] + cluster["nodegroups_cost"]) / cluster[
                        "running_hours"]

            hour_data["total_cost"] = hour_data["ec2_cost"] + hour_data["eks_cost"]
            hourly_breakdown.append(hour_data)

        return hourly_breakdown

    def get_eks_node_info(self, ec2_client, instance_ids):
        """Get information about EC2 instances used as EKS nodes"""
        node_info = {}
        
        try:
            # Get instance details
            response = ec2_client.describe_instances(InstanceIds=instance_ids)
            
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_id = instance['InstanceId']
                    instance_type = instance['InstanceType']
                    launch_time = instance['LaunchTime']
                    state = instance['State']['Name']
                    
                    # Calculate uptime
                    uptime_hours = (self.current_time - launch_time.replace(tzinfo=None)).total_seconds() / 3600
                    
                    # Get node name from tags
                    node_name = None
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name' or tag['Key'] == 'kubernetes.io/hostname':
                            node_name = tag['Value']
                            break
                    
                    node_info[instance_id] = {
                        "instance_id": instance_id,
                        "instance_type": instance_type,
                        "state": state,
                        "node_name": node_name,
                        "launch_time": launch_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "uptime_hours": round(uptime_hours, 2)
                    }
            
            return node_info
            
        except Exception as e:
            self.logger.error(f"Error getting EKS node info: {e}")
            return {}

    def calculate_eks_costs(self, account_selection, region_selection, eks_selection=None):
        """Calculate costs for EKS clusters with proper timezone handling"""
        current_timestamp_utc = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_user = "varadharajaan"

        self.logger.info(f"Calculating EKS costs for account {account_selection} in regions: {region_selection}")

        results = {
            "account_id": account_selection,
            "account_name": self.account_id_to_name.get(account_selection, "Unknown"),
            "regions": {},
            "total_cost": 0.0,
            "currency": "USD",
            "calculated_at": current_timestamp_utc,
            "calculated_by": current_user,
            "cluster_count": 0
        }

        # Get account credentials
        account_name = self.account_id_to_name.get(account_selection)
        if not account_name:
            self.logger.error(f"Account ID {account_selection} not found in configuration")
            return results

        account_data = self.aws_config['accounts'].get(account_name)
        if not account_data:
            self.logger.error(f"Account {account_name} not found in configuration")
            return results

        access_key = account_data['access_key']
        secret_key = account_data['secret_key']

        # Load EKS pricing data
        eks_pricing = self.load_eks_pricing_data()

        # Current time for calculations (UTC)
        current_time = datetime.strptime(current_timestamp_utc, "%Y-%m-%d %H:%M:%S")

        # Process each region
        for region in region_selection:
            self.logger.info(f"Processing EKS in region: {region}")

            region_results = {
                "clusters": [],
                "total_cost": 0.0,
                "cluster_count": 0
            }

            # Create clients
            eks_client = self.create_eks_client(access_key, secret_key, region)
            if not eks_client:
                self.logger.error(f"Could not create EKS client for region {region}")
                continue

            ec2_client = self.create_ec2_client(access_key, secret_key, region)
            if not ec2_client:
                self.logger.error(f"Could not create EC2 client for region {region}")
                continue

            # Load EC2 pricing for this region (for worker nodes)
            ec2_pricing = self.load_ec2_pricing_data(region)

            # Get EKS control plane hourly price for this region
            control_plane_hourly = eks_pricing.get(region, {}).get('control_plane', 0.10)  # Default to $0.10/hour

            # Get clusters
            try:
                clusters_to_process = []

                if eks_selection and eks_selection != 'all':
                    # Get specific clusters
                    cluster_names = eks_selection if isinstance(eks_selection, list) else [eks_selection]
                    for cluster_name in cluster_names:
                        try:
                            cluster_info = eks_client.describe_cluster(name=cluster_name)
                            clusters_to_process.append(cluster_info['cluster'])
                            self.logger.info(f"Found specific cluster: {cluster_name}")
                        except Exception as e:
                            self.logger.error(f"Error getting cluster {cluster_name}: {e}")
                else:
                    # Get all clusters
                    try:
                        list_response = eks_client.list_clusters()
                        cluster_names = list_response.get('clusters', [])
                        self.logger.info(f"Found {len(cluster_names)} clusters in region {region}: {cluster_names}")

                        for cluster_name in cluster_names:
                            try:
                                cluster_info = eks_client.describe_cluster(name=cluster_name)
                                clusters_to_process.append(cluster_info['cluster'])
                                self.logger.info(f"Successfully described cluster: {cluster_name}")
                            except Exception as e:
                                self.logger.error(f"Error describing cluster {cluster_name}: {e}")
                    except Exception as e:
                        self.logger.error(f"Error listing clusters in region {region}: {e}")

                self.logger.info(f"Processing {len(clusters_to_process)} clusters in region {region}")

                # Process each cluster
                for cluster in clusters_to_process:
                    cluster_name = cluster['name']
                    cluster_status = cluster['status']
                    cluster_version = cluster['version']
                    cluster_created_at = cluster['createdAt']

                    # Handle timezone-aware datetime
                    if hasattr(cluster_created_at, 'tzinfo') and cluster_created_at.tzinfo:
                        cluster_created_at = cluster_created_at.replace(tzinfo=None)

                    self.logger.info(
                        f"Processing cluster: {cluster_name}, Status: {cluster_status}, Created: {cluster_created_at}")

                    # Only calculate costs for ACTIVE clusters
                    if cluster_status != 'ACTIVE':
                        self.logger.warning(f"Skipping cluster {cluster_name} with status: {cluster_status}")
                        continue

                    # Calculate uptime (handle future timestamps correctly)
                    if cluster_created_at <= current_time:
                        uptime_hours = (current_time - cluster_created_at).total_seconds() / 3600
                    else:
                        # If cluster was "created in the future", it's likely a timezone issue
                        # Assume it was just created
                        uptime_hours = 0.1  # Minimum 6 minutes
                        self.logger.warning(f"Cluster {cluster_name} has future creation time, using minimum uptime")

                    uptime_hours = max(0.1, uptime_hours)  # Ensure minimum uptime

                    # Calculate control plane cost
                    control_plane_cost = uptime_hours * control_plane_hourly

                    # Get nodegroups
                    try:
                        nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                        nodegroup_names = nodegroups_response.get('nodegroups', [])

                        nodegroups_info = []
                        total_nodegroups_cost = 0.0

                        for ng_name in nodegroup_names:
                            try:
                                ng_response = eks_client.describe_nodegroup(
                                    clusterName=cluster_name,
                                    nodegroupName=ng_name
                                )
                                ng_info = ng_response['nodegroup']

                                # Calculate nodegroup cost
                                ng_scaling_config = ng_info.get('scalingConfig', {})
                                ng_instance_types = ng_info.get('instanceTypes', ['m5.large'])
                                ng_desired_size = ng_scaling_config.get('desiredSize', 1)

                                # Calculate worker node costs
                                ng_cost = 0.0
                                for instance_type in ng_instance_types:
                                    instance_hourly_rate = ec2_pricing.get(instance_type, 0.096)
                                    # Distribute instances across types
                                    instances_of_type = max(1, ng_desired_size // len(ng_instance_types))
                                    ng_cost += instances_of_type * instance_hourly_rate * uptime_hours

                                nodegroup_info = {
                                    "nodegroup_name": ng_name,
                                    "status": ng_info.get('status', 'UNKNOWN'),
                                    "instance_types": ng_instance_types,
                                    "desired_size": ng_desired_size,
                                    "cost": round(ng_cost, 2)
                                }

                                nodegroups_info.append(nodegroup_info)
                                total_nodegroups_cost += ng_cost

                            except Exception as e:
                                self.logger.error(f"Error processing nodegroup {ng_name}: {e}")

                    except Exception as e:
                        self.logger.error(f"Error listing nodegroups for cluster {cluster_name}: {e}")
                        nodegroups_info = []
                        total_nodegroups_cost = 0.0

                    # Calculate total cluster cost
                    total_cluster_cost = control_plane_cost + total_nodegroups_cost

                    # Add cluster to results
                    cluster_info = {
                        "cluster_name": cluster_name,
                        "status": cluster_status,
                        "version": cluster_version,
                        "created_at": cluster_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "uptime_hours": round(uptime_hours, 2),
                        "control_plane": {
                            "hourly_rate": control_plane_hourly,
                            "cost": round(control_plane_cost, 2)
                        },
                        "nodegroups": nodegroups_info,
                        "nodegroups_count": len(nodegroups_info),
                        "nodegroups_cost": round(total_nodegroups_cost, 2),
                        "total_cost": round(total_cluster_cost, 2)
                    }

                    region_results["clusters"].append(cluster_info)
                    region_results["total_cost"] += total_cluster_cost
                    region_results["cluster_count"] += 1

                    self.logger.info(
                        f"Calculated cost for cluster {cluster_name}: ${total_cluster_cost:.2f} (Control: ${control_plane_cost:.2f}, Workers: ${total_nodegroups_cost:.2f})")

            except Exception as e:
                self.logger.error(f"Error processing EKS clusters in {region}: {e}")

            # Update region and total results
            results["regions"][region] = region_results
            results["total_cost"] += region_results["total_cost"]
            results["cluster_count"] += region_results["cluster_count"]

            self.logger.info(
                f"Region {region} summary: {region_results['cluster_count']} clusters, ${region_results['total_cost']:.2f}")

        # Save results to file with proper directory creation
        account_save_name = self.account_id_to_name.get(account_selection, "Unknown")
        account_output_dir = f"{self.eks_output_dir}/{account_save_name}"

        # Create directory if it doesn't exist
        try:
            os.makedirs(account_output_dir, exist_ok=True)
            self.logger.info(f"Created/verified EKS directory: {account_output_dir}")
        except Exception as e:
            self.logger.error(f"Failed to create EKS directory {account_output_dir}: {e}")
            # Fallback to parent directory
            account_output_dir = self.eks_output_dir
            os.makedirs(account_output_dir, exist_ok=True)

        # EKS ONLY saved here - separate file
        output_file = f"{account_output_dir}/eks_cost_{account_save_name}_{self.execution_timestamp}.json"

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, default=str)
            self.logger.info(f"EKS cost calculation saved to: {output_file}")
            print(f"✅ EKS results saved: {results['cluster_count']} clusters, ${results['total_cost']:.2f}")
        except Exception as e:
            self.logger.error(f"Failed to save EKS results to {output_file}: {e}")

        self.logger.info(
            f"Total EKS cost for account {account_selection}: ${results['total_cost']:.2f} for {results['cluster_count']} clusters")

        return results

    def display_ec2_cost_summary(self, cost_data):
        """Display EC2 cost summary to console"""
        print("\n" + "=" * 80)
        print(f"💰 EC2 COST SUMMARY FOR ACCOUNT: {cost_data['account_id']} ({cost_data['account_name']})")
        print("=" * 80)
        
        # Display total
        print(f"📊 TOTAL EC2 COST: ${cost_data['total_cost']:.2f}")
        print(f"📊 TOTAL INSTANCES: {cost_data['instance_count']}")
        print(f"📊 CALCULATED AT: {cost_data['calculated_at']}")
        
        # Display by region
        for region, region_data in cost_data['regions'].items():
            if region_data['instance_count'] > 0:
                print(f"\n🌍 REGION: {region}")
                print(f"   Cost: ${region_data['total_cost']:.2f}")
                print(f"   Instances: {region_data['instance_count']}")
                
                # Display top instances by cost
                instances = sorted(region_data['instances'], key=lambda x: x['estimated_cost'], reverse=True)
                
                print("\n   Top instances by cost:")
                print(f"   {'Instance ID':<20} {'Name':<30} {'Type':<15} {'Hours':<10} {'Cost':<10} {'CPU %':<10}")
                print("   " + "-" * 90)
                
                # Display top 5 instances or fewer if less than 5
                for instance in instances[:5]:
                    cpu_util = instance['health'].get('cpu_utilization', 'N/A')
                    cpu_str = f"{cpu_util}%" if cpu_util is not None else "N/A"
                    
                    print(f"   {instance['instance_id']:<20} {instance['instance_name'][:28]:<30} "
                          f"{instance['instance_type']:<15} {instance['uptime_hours']:<10.2f} "
                          f"${instance['estimated_cost']:<9.2f} {cpu_str:<10}")
                
                if len(instances) > 5:
                    print(f"   ... and {len(instances) - 5} more instances")
        
        print("\n" + "=" * 80)

    def display_eks_cost_summary(self, cost_data):
        """Display EKS cost summary to console"""
        print("\n" + "=" * 80)
        print(f"💰 EKS COST SUMMARY FOR ACCOUNT: {cost_data['account_id']} ({cost_data['account_name']})")
        print("=" * 80)
        
        # Display total
        print(f"📊 TOTAL EKS COST: ${cost_data['total_cost']:.2f}")
        print(f"📊 TOTAL CLUSTERS: {cost_data['cluster_count']}")
        print(f"📊 CALCULATED AT: {cost_data['calculated_at']}")
        
        # Display by region
        for region, region_data in cost_data['regions'].items():
            if region_data['cluster_count'] > 0:
                print(f"\n🌍 REGION: {region}")
                print(f"   Cost: ${region_data['total_cost']:.2f}")
                print(f"   Clusters: {region_data['cluster_count']}")
                
                # Display clusters
                clusters = sorted(region_data['clusters'], key=lambda x: x['total_cost'], reverse=True)
                
                for cluster in clusters:
                    print(f"\n   📦 CLUSTER: {cluster['cluster_name']} (v{cluster['version']})")
                    print(f"      Status: {cluster['status']}")
                    print(f"      Uptime: {cluster['uptime_hours']:.2f} hours")
                    print(f"      Control Plane Cost: ${cluster['control_plane']['cost']:.2f}")
                    
                    # Display nodegroups
                    if cluster['nodegroups']:
                        print("\n      Nodegroups:")
                        for ng in cluster['nodegroups']:
                            print(f"         - {ng['nodegroup_name']}: ${ng['cost']:.2f}")
                            
                            # Display node details if available
                            if ng['nodes']:
                                print("            Nodes:")
                                for node in ng['nodes']:
                                    if 'instance_id' in node:
                                        print(f"               {node['instance_id']} ({node['instance_type']}): ${node['cost']:.2f}")
                                    else:
                                        print(f"               {node['instance_type']} x {node['count']}: ${node['estimated_cost']:.2f}")
                    
                    print(f"      Total Cluster Cost: ${cluster['total_cost']:.2f}")
        
        print("\n" + "=" * 80)

    def list_active_ec2_instances(self, access_key, secret_key, region):
        """List active EC2 instances in a region"""
        active_instances = []
    
        try:
            # Create EC2 client
            ec2_client = self.create_ec2_client(access_key, secret_key, region)
            if not ec2_client:
                self.logger.error(f"Could not create EC2 client for region {region}")
                return active_instances
            
            # Get all instances
            response = ec2_client.describe_instances(
                Filters=[
                    {
                        'Name': 'instance-state-name', 
                        'Values': ['running']
                    }
                ]
            )
        
            # Process each reservation and instance
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_id = instance['InstanceId']
                    instance_type = instance['InstanceType']
                
                    # Get instance name from tags
                    instance_name = 'Unnamed'
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            instance_name = tag['Value']
                            break
                
                    # Get launch time
                    launch_time = instance['LaunchTime'].strftime("%Y-%m-%d %H:%M:%S")
                
                    # Add instance to result
                    active_instances.append({
                        'instance_id': instance_id,
                        'instance_name': instance_name,
                        'instance_type': instance_type,
                        'launch_time': launch_time
                    })
                
            return active_instances
        
        except Exception as e:
            self.logger.error(f"Error listing EC2 instances in {region}: {e}")
            return active_instances

    def list_active_eks_clusters(self, access_key, secret_key, region):
        """List active EKS clusters in a region"""
        active_clusters = []

        try:
            # Create EKS client
            eks_client = self.create_eks_client(access_key, secret_key, region)
            if not eks_client:
                self.logger.error(f"Could not create EKS client for region {region}")
                return active_clusters

            # Get all clusters
            response = eks_client.list_clusters()

            # For each cluster, get details
            for cluster_name in response.get('clusters', []):
                try:
                    cluster_info = eks_client.describe_cluster(name=cluster_name)
                    cluster = cluster_info['cluster']

                    # Only add active clusters
                    if cluster['status'] == 'ACTIVE':
                        active_clusters.append({
                            'cluster_name': cluster['name'],
                            'status': cluster['status'],
                            'version': cluster['version'],
                            'created_at': cluster['createdAt'].strftime("%Y-%m-%d %H:%M:%S")
                        })

                        # Get nodegroups count for this cluster
                        try:
                            nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                            active_clusters[-1]['nodegroups_count'] = len(nodegroups_response.get('nodegroups', []))
                        except Exception:
                            active_clusters[-1]['nodegroups_count'] = 0

                except Exception as e:
                    self.logger.error(f"Error getting details for cluster {cluster_name}: {e}")

            return active_clusters

        except Exception as e:
            self.logger.error(f"Error listing EKS clusters in {region}: {e}")
            return active_clusters

    def display_active_resources(self, account_id, account_name, regions, access_key, secret_key):
        """Display active EC2 instances and EKS clusters with enhanced details"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        print("\n" + "=" * 80)
        print(f"🔍 ACTIVE RESOURCES IN ACCOUNT: {account_id} ({account_name})")
        print("=" * 80)
        print(f"📅 Scan Time: {now_str}")
        print(f"👤 Scanned by: varadharajaan")
        print(f"🌍 Regions: {', '.join(regions)}")
        print("=" * 80)

        has_active_resources = False
        total_estimated_hourly_cost = 0.0
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        scan_summary = {
            "account_id": account_id,
            "account_name": account_name,
            "scan_time": current_timestamp,
            "scanned_by": "varadharajaan",
            "regions_scanned": regions,
            "ec2_instances": [],
            "eks_clusters": [],
            "total_resources": 0,
            "estimated_hourly_cost": 0.0
        }

        # Display EC2 instances
        all_instances = []
        ec2_regions_with_instances = []  # Correctly defined here

        print("\n🖥️  SCANNING EC2 INSTANCES...")
        for region in regions:
            print(f"   🔍 Scanning {region}...", end=" ")
            instances = self.list_active_ec2_instances(access_key, secret_key, region)
            if instances:
                ec2_regions_with_instances.append(region)  # Add region if instances found
                for instance in instances:
                    instance['region'] = region

                    # Calculate uptime
                    try:
                        # current_stamp is already a datetime object, no need to convert it
                        current_time = datetime.now()
                        launch_time = datetime.strptime(instance['launch_time'], "%Y-%m-%d %H:%M:%S")
                        uptime_hours = ((current_time - launch_time).total_seconds() / 3600) - 5.30
                        instance['uptime_hours'] = round(uptime_hours, 1)

                        # Estimate hourly cost (simplified - you may want to load actual pricing)
                        instance_type_costs = {
                            't2.micro': 0.0116, 't2.small': 0.023, 't2.medium': 0.0464,
                            't3.micro': 0.0104, 't3.small': 0.0208, 't3.medium': 0.0416,
                            't3.large': 0.0832, 't3.xlarge': 0.1664, 't3.2xlarge': 0.3328,
                            'm5.large': 0.096, 'm5.xlarge': 0.192, 'm5.2xlarge': 0.384,
                            'm5.4xlarge': 0.768, 'm5.8xlarge': 1.536, 'm5.12xlarge': 2.304,
                            'c5.large': 0.085, 'c5.xlarge': 0.17, 'c5.2xlarge': 0.34,
                            'c5.4xlarge': 0.68, 'c5.9xlarge': 1.53, 'c5.18xlarge': 3.06,
                            'r5.large': 0.126, 'r5.xlarge': 0.252, 'r5.2xlarge': 0.504,
                            'r5.4xlarge': 1.008, 'r5.8xlarge': 2.016, 'r5.12xlarge': 3.024
                        }

                        instance['estimated_hourly_cost'] = instance_type_costs.get(instance['instance_type'], 0.05)
                        total_estimated_hourly_cost += instance['estimated_hourly_cost']

                    except Exception as e:
                        instance['uptime_hours'] = 0
                        instance['estimated_hourly_cost'] = 0.05
                        total_estimated_hourly_cost += 0.05

                all_instances.extend(instances)
                print(f"✅ Found {len(instances)} instances")
            else:
                print("📭 No instances")

        if all_instances:
            has_active_resources = True
            print(f"\n🖥️  ACTIVE EC2 INSTANCES ({len(all_instances)} total):")
            print("-" * 120)
            print(
                f"   {'Instance ID':<20} {'Name':<25} {'Type':<15} {'Region':<12} {'Uptime':<10} {'Est.Cost/hr':<12} {'Launch Time'}")
            print("-" * 120)

            # Sort instances by estimated cost (highest first)
            sorted_instances = sorted(all_instances, key=lambda x: x.get('estimated_hourly_cost', 0), reverse=True)

            for instance in sorted_instances:
                uptime_str = f"{instance.get('uptime_hours', 0):.1f}h"
                cost_str = f"${instance.get('estimated_hourly_cost', 0):.4f}"
                print(f"   {instance['instance_id']:<20} {instance['instance_name'][:23]:<25} "
                      f"{instance['instance_type']:<15} {instance['region']:<12} {uptime_str:<10} "
                      f"{cost_str:<12} {instance['launch_time']}")

            print("-" * 120)
            print(f"   📊 Summary: {len(all_instances)} instances across {len(ec2_regions_with_instances)} regions")
            print(
                f"   💰 Estimated Total Hourly Cost: ${sum(i.get('estimated_hourly_cost', 0) for i in all_instances):.4f}")
            print(f"   🌍 Regions with instances: {', '.join(ec2_regions_with_instances)}")

            # Show top cost instances
            if len(all_instances) > 3:
                top_instances = sorted_instances[:3]
                print(f"   🔥 Top 3 Most Expensive:")
                for i, instance in enumerate(top_instances, 1):
                    print(
                        f"      {i}. {instance['instance_id']} ({instance['instance_type']}) - ${instance.get('estimated_hourly_cost', 0):.4f}/hr")

            scan_summary["ec2_instances"] = all_instances
        else:
            print("\n🖥️  No active EC2 instances found in selected regions.")

        # Display EKS clusters
        all_clusters = []
        eks_regions_with_clusters = []  # Correctly defined here
        total_eks_hourly_cost = 0.0

        print(f"\n🚢 SCANNING EKS CLUSTERS...")
        for region in regions:
            print(f"   🔍 Scanning {region}...", end=" ")
            clusters = self.list_active_eks_clusters(access_key, secret_key, region)
            if clusters:
                eks_regions_with_clusters.append(region)  # Add region if clusters found
                for cluster in clusters:
                    cluster['region'] = region

                    # Calculate uptime and costs
                    try:
                        # Current stamp is already a datetime object
                        current_time = datetime.now()
                        created_time = datetime.strptime(cluster['created_at'], "%Y-%m-%d %H:%M:%S")
                        uptime_hours = (current_time - created_time).total_seconds() / 3600 - 5.30
                        cluster['uptime_hours'] = round(uptime_hours, 1)

                        # EKS control plane cost is $0.10 per hour
                        cluster['control_plane_hourly_cost'] = 0.10

                        # Estimate worker node costs based on nodegroup count (simplified)
                        nodegroup_count = cluster.get('nodegroups_count', 0)
                        estimated_worker_cost = nodegroup_count * 0.096  # Assume m5.large equivalent
                        cluster['estimated_worker_hourly_cost'] = estimated_worker_cost
                        cluster['total_estimated_hourly_cost'] = 0.10 + estimated_worker_cost

                        total_eks_hourly_cost += cluster['total_estimated_hourly_cost']

                    except Exception as e:
                        cluster['uptime_hours'] = 0
                        cluster['control_plane_hourly_cost'] = 0.10
                        cluster['estimated_worker_hourly_cost'] = 0
                        cluster['total_estimated_hourly_cost'] = 0.10
                        total_eks_hourly_cost += 0.10

                all_clusters.extend(clusters)
                print(f"✅ Found {len(clusters)} clusters")
            else:
                print("📭 No clusters")

        if all_clusters:
            has_active_resources = True
            print(f"\n🚢 ACTIVE EKS CLUSTERS ({len(all_clusters)} total):")
            print("-" * 130)
            print(
                f"   {'Cluster Name':<25} {'Version':<10} {'Region':<12} {'Nodegroups':<10} {'Uptime':<10} {'Est.Cost/hr':<12} {'Created At'}")
            print("-" * 130)

            # Sort clusters by estimated cost (highest first)
            sorted_clusters = sorted(all_clusters, key=lambda x: x.get('total_estimated_hourly_cost', 0), reverse=True)

            for cluster in sorted_clusters:
                uptime_str = f"{cluster.get('uptime_hours', 0):.1f}h"
                cost_str = f"${cluster.get('total_estimated_hourly_cost', 0):.4f}"
                print(f"   {cluster['cluster_name'][:23]:<25} {cluster['version']:<10} "
                      f"{cluster['region']:<12} {cluster['nodegroups_count']:<10} {uptime_str:<10} "
                      f"{cost_str:<12} {cluster['created_at']}")

            print("-" * 130)
            print(f"   📊 Summary: {len(all_clusters)} clusters across {len(eks_regions_with_clusters)} regions")
            print(f"   💰 Estimated Total Hourly Cost: ${total_eks_hourly_cost:.4f}")
            print(f"   🌍 Regions with clusters: {', '.join(eks_regions_with_clusters)}")

            # Show cluster breakdown
            total_control_plane_cost = len(all_clusters) * 0.10
            total_worker_cost = sum(c.get('estimated_worker_hourly_cost', 0) for c in all_clusters)
            print(f"   🎛️  Control Plane Cost: ${total_control_plane_cost:.2f}/hr ({len(all_clusters)} × $0.10)")
            print(f"   👷 Worker Nodes Cost: ${total_worker_cost:.4f}/hr (estimated)")

            scan_summary["eks_clusters"] = all_clusters
        else:
            print("\n🚢 No active EKS clusters found in selected regions.")

        # Overall summary
        total_resources = len(all_instances) + len(all_clusters)
        total_hourly_cost = total_estimated_hourly_cost + total_eks_hourly_cost

        print(f"\n📊 RESOURCE SUMMARY:")
        print("=" * 80)

        if has_active_resources:
            print(f"✅ Total Active Resources: {total_resources}")
            print(f"   🖥️  EC2 Instances: {len(all_instances)}")
            print(f"   🚢 EKS Clusters: {len(all_clusters)}")
            print(f"   🌍 Regions with resources: {len(set(ec2_regions_with_instances + eks_regions_with_clusters))}")
            print(f"   💰 Estimated Total Hourly Cost: ${total_hourly_cost:.4f}")
            print(f"   📅 Estimated Daily Cost: ${total_hourly_cost * 24:.2f}")
            print(f"   📆 Estimated Monthly Cost: ${total_hourly_cost * 24 * 30:.2f}")

            # Cost breakdown
            if total_hourly_cost > 0:
                ec2_percentage = (total_estimated_hourly_cost / total_hourly_cost) * 100
                eks_percentage = (total_eks_hourly_cost / total_hourly_cost) * 100
                print(f"\n💹 Cost Breakdown:")
                print(f"   🖥️  EC2: ${total_estimated_hourly_cost:.4f}/hr ({ec2_percentage:.1f}%)")
                print(f"   🚢 EKS: ${total_eks_hourly_cost:.4f}/hr ({eks_percentage:.1f}%)")

            # Alerts and recommendations
            print(f"\n💡 INSIGHTS & RECOMMENDATIONS:")
            if total_hourly_cost > 5.0:
                print(f"   ⚠️  High hourly cost detected (>${total_hourly_cost:.2f}/hr)")
                print(f"   💡 Consider reviewing resource utilization and right-sizing")

            if len(all_instances) > 10:
                print(f"   📈 Large number of EC2 instances ({len(all_instances)})")
                print(f"   💡 Consider using auto-scaling or spot instances for cost optimization")

            if len(all_clusters) > 3:
                print(f"   🚢 Multiple EKS clusters detected ({len(all_clusters)})")
                print(f"   💡 Consider cluster consolidation if workloads allow")

            # Security and compliance
            print(f"\n🔒 SECURITY NOTES:")
            print(f"   📝 Review instance security groups and access policies")
            print(f"   🔐 Ensure proper IAM roles and policies are applied")
            print(f"   📊 Monitor resource utilization for optimization opportunities")

        else:
            print("⚠️  No active EC2 instances or EKS clusters found in selected regions.")
            print("💡 This could indicate:")
            print("   • Resources are in different regions")
            print("   • Instances are stopped/terminated")
            print("   • Access permissions may be limited")

        # Update scan summary
        scan_summary.update({
            "total_resources": total_resources,
            "estimated_hourly_cost": total_hourly_cost,
            "cost_breakdown": {
                "ec2_hourly": total_estimated_hourly_cost,
                "eks_hourly": total_eks_hourly_cost,
                "daily_estimate": total_hourly_cost * 24,
                "monthly_estimate": total_hourly_cost * 24 * 30
            },
            "regions_with_resources": list(set(ec2_regions_with_instances + eks_regions_with_clusters))
        })

        print("\n" + "=" * 80)

        # Save scan results to file
        try:
            scan_file = f"aws/live-cost/{account_name}/resource_scan_{account_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            os.makedirs(os.path.dirname(scan_file), exist_ok=True)

            with open(scan_file, 'w', encoding='utf-8') as f:
                json.dump(scan_summary, f, indent=2, default=str)

            print(f"📄 Scan results saved to: {scan_file}")

        except Exception as e:
            self.logger.warning(f"Could not save scan results: {e}")

        # Return enhanced summary for further use
        return scan_summary

    def run(self):
        """Main execution method"""
        print("\n" + "=" * 80)
        print("💲 LIVE COST CALCULATOR & HEALTH METADATA")
        print("=" * 80)

        # Step 1: Account selection with multiple account support
        print("\n🏦 ACCOUNT SELECTION")
        print("-" * 80)

        accounts = []

        # Display account list
        print("Available AWS Accounts:")
        for i, (account_name, account_data) in enumerate(self.aws_config['accounts'].items(), 1):
            account_id = account_data.get('account_id', 'Unknown')
            accounts.append((account_id, account_name))
            print(f"  {i}. {account_name} ({account_id})")

        # Enhanced account selection for multiple accounts
        print("\nSelection Options:")
        print("  • Single accounts: 1,3,5")
        print("  • Ranges: 1-3")
        print("  • All accounts: 'all' or press Enter")

        account_input = input("\nEnter account ID or number(s): ").strip().lower()

        selected_account_ids = []

        if not account_input or account_input == 'all':
            # Select all accounts
            selected_account_ids = [account[0] for account in accounts]
            print(f"Selected all {len(selected_account_ids)} accounts")
        else:
            # Parse account selection similar to region selection
            try:
                account_indices = []
                parts = [part.strip() for part in account_input.split(',')]

                for part in parts:
                    if '-' in part:
                        # Process range
                        start, end = map(int, part.split('-'))
                        if start < 1 or end > len(accounts) or start > end:
                            raise ValueError(f"Invalid range: {part}")
                        account_indices.extend(range(start, end + 1))
                    else:
                        # Check if it's a number or account ID
                        try:
                            index = int(part)
                            if index < 1 or index > len(accounts):
                                raise ValueError(f"Invalid account number: {index}")
                            account_indices.append(index)
                        except ValueError:
                            # Might be an account ID directly
                            found = False
                            for i, (account_id, _) in enumerate(accounts, 1):
                                if account_id == part:
                                    account_indices.append(i)
                                    found = True
                                    break
                            if not found:
                                print(f"Warning: Account ID '{part}' not found, skipping.")

                # Convert indices to account IDs
                selected_account_ids = [accounts[i - 1][0] for i in account_indices]

                if not selected_account_ids:
                    print("No valid accounts selected. Please try again.")
                    return

                print(f"Selected {len(selected_account_ids)} accounts")

            except ValueError as e:
                print(f"Error parsing account selection: {e}")
                return

        # Step 2: Region selection
        print("\n🌍 REGION SELECTION")
        print("-" * 80)

        print("Available Regions:")
        for i, region in enumerate(self.default_regions, 1):
            print(f"  {i}. {region}")

        print("\nSelection Options:")
        print("  • Single regions: 1,3,5")
        print("  • Ranges: 1-3")
        print("  • All regions: 'all' or press Enter")

        region_input = input("\nSelect regions: ").strip().lower()

        selected_regions = []

        if not region_input or region_input == 'all':
            selected_regions = self.default_regions
        else:
            # Parse region selection
            try:
                region_indices = []
                parts = [part.strip() for part in region_input.split(',')]

                for part in parts:
                    if '-' in part:
                        # Process range
                        start, end = map(int, part.split('-'))
                        if start < 1 or end > len(self.default_regions) or start > end:
                            raise ValueError(f"Invalid range: {part}")
                        region_indices.extend(range(start, end + 1))
                    else:
                        # Process single number
                        index = int(part)
                        if index < 1 or index > len(self.default_regions):
                            raise ValueError(f"Invalid region number: {index}")
                        region_indices.append(index)

                # Convert indices to region codes
                selected_regions = [self.default_regions[i - 1] for i in region_indices]

            except ValueError as e:
                print(f"Error parsing region selection: {e}")
                return

        print(f"Selected regions: {', '.join(selected_regions)}")

        # List active resources for each selected account
        account_resources = {}
        for account_id in selected_account_ids:
            account_name = self.account_id_to_name.get(account_id, "Unknown")
            print(f"\nListing active resources for account: {account_name} ({account_id})...")

            # Get account credentials
            account_data = self.aws_config['accounts'].get(account_name)
            if not account_data:
                self.logger.error(f"Account {account_name} not found in configuration")
                continue

            access_key = account_data['access_key']
            secret_key = account_data['secret_key']

            # Display active resources
            resources = self.display_active_resources(account_id, account_name, selected_regions,
                                                      access_key, secret_key)
            account_resources[account_id] = resources

        # Step 3: Service scope selection
        print("\n🔍 SERVICE SCOPE SELECTION")
        print("-" * 80)

        print("Available Service Scopes:")
        print("  1. EC2 Only")
        print("  2. EKS Only")
        print("  3. Both EC2 and EKS")

        scope_input = input("\nSelect service scope (1-3): ").strip()

        calculate_ec2 = False
        calculate_eks = False

        if scope_input == '1':
            calculate_ec2 = True
        elif scope_input == '2':
            calculate_eks = True
        elif scope_input == '3' or not scope_input:
            calculate_ec2 = True
            calculate_eks = True
        else:
            print("Invalid selection. Please enter 1, 2, or 3.")
            return

        # EC2 instance selection (if applicable)
        ec2_selection = 'all'
        if calculate_ec2:
            print("\n💻 EC2 INSTANCE SELECTION")
            print("-" * 80)

            print("EC2 Selection Options:")
            print("  1. All listed EC2 instances")
            print("  2. Selected EC2 instances")

            ec2_option = input("\nSelect EC2 option (1-2): ").strip()

            if ec2_option == '2':
                ec2_ids = input("\nEnter EC2 instance IDs (comma-separated): ").strip()
                if ec2_ids:
                    ec2_selection = [id.strip() for id in ec2_ids.split(',')]

        # EKS cluster selection (if applicable)
        eks_selection = 'all'
        if calculate_eks:
            print("\n🚢 EKS CLUSTER SELECTION")
            print("-" * 80)

            print("EKS Selection Options:")
            print("  1. All listed EKS clusters")
            print("  2. Selected EKS clusters")

            eks_option = input("\nSelect EKS option (1-2): ").strip()

            if eks_option == '2':
                eks_names = input("\nEnter EKS cluster names (comma-separated): ").strip()
                if eks_names:
                    eks_selection = [name.strip() for name in eks_names.split(',')]

        # Step 4: Calculate costs, historical analysis, and forecasts
        print("\n🧮 CALCULATING COSTS AND ANALYSIS...")

        # Containers to store results for all accounts
        all_ec2_results = {}
        all_eks_results = {}
        all_historical_results = {}
        all_forecast_results = {}

        # Calculate for each selected account
        for account_id in selected_account_ids:
            account_name = self.account_id_to_name.get(account_id, "Unknown")
            print(f"\n📊 Processing account: {account_name} ({account_id})")

            if calculate_ec2:
                print(f"  💻 Calculating EC2 costs...")
                ec2_results = self.calculate_ec2_costs(account_id, selected_regions, ec2_selection)
                all_ec2_results[account_id] = ec2_results

            if calculate_eks:
                print(f"  🚢 Calculating EKS costs...")
                eks_results = self.calculate_eks_costs(account_id, selected_regions, eks_selection)
                all_eks_results[account_id] = eks_results

            # Historical analysis (last 9 hours)
            print(f"  📈 Analyzing last 9 hours...")
            historical_results = self.calculate_historical_costs(account_id, selected_regions, 9)
            all_historical_results[account_id] = historical_results

            # Forecast analysis (next 9 hours)
            print(f"  🔮 Forecasting next 9 hours...")
            forecast_results = self.calculate_forecast_costs(account_id, selected_regions, 9)
            all_forecast_results[account_id] = forecast_results

        # Step 5: Aggregate and display final summary
        print("\n" + "=" * 80)
        print("💵 AGGREGATED COST SUMMARY")
        print("=" * 80)

        # Calculate totals
        total_ec2_cost = sum(result['total_cost'] for result in all_ec2_results.values()) if all_ec2_results else 0
        total_ec2_instances = sum(
            result['instance_count'] for result in all_ec2_results.values()) if all_ec2_results else 0

        total_eks_cost = sum(result['total_cost'] for result in all_eks_results.values()) if all_eks_results else 0
        total_eks_clusters = sum(
            result['cluster_count'] for result in all_eks_results.values()) if all_eks_results else 0

        total_historical_cost = sum(result['total_historical_cost'] for result in
                                    all_historical_results.values()) if all_historical_results else 0
        total_forecast_cost = sum(
            result['total_forecast_cost'] for result in all_forecast_results.values()) if all_forecast_results else 0

        total_cost = total_ec2_cost + total_eks_cost

        print(f"📈 TOTAL ESTIMATED COST ACROSS ALL ACCOUNTS: ${total_cost:.2f} USD")
        print(f"  • Total accounts processed: {len(selected_account_ids)}")

        if calculate_ec2:
            print(f"  • EC2: ${total_ec2_cost:.2f} ({total_ec2_instances} instances)")

        if calculate_eks:
            print(f"  • EKS: ${total_eks_cost:.2f} ({total_eks_clusters} clusters)")

        print(f"\n📊 HISTORICAL & FORECAST ANALYSIS:")
        print(f"  • Last 9 hours cost: ${total_historical_cost:.2f}")
        print(f"  • Next 9 hours forecast: ${total_forecast_cost:.2f}")

        # Per-account breakdown
        print("\n📊 COST BREAKDOWN BY ACCOUNT:")

        for account_id in selected_account_ids:
            account_name = self.account_id_to_name.get(account_id, "Unknown")
            account_ec2_cost = all_ec2_results.get(account_id, {}).get('total_cost', 0)
            account_eks_cost = all_eks_results.get(account_id, {}).get('total_cost', 0)
            account_historical = all_historical_results.get(account_id, {}).get('total_historical_cost', 0)
            account_forecast = all_forecast_results.get(account_id, {}).get('total_forecast_cost', 0)
            account_total = account_ec2_cost + account_eks_cost

            print(f"  • {account_name} ({account_id}): ${account_total:.2f}")
            if calculate_ec2 and account_id in all_ec2_results:
                instances = all_ec2_results[account_id]['instance_count']
                print(f"      EC2: ${account_ec2_cost:.2f} ({instances} instances)")

            if calculate_eks and account_id in all_eks_results:
                clusters = all_eks_results[account_id]['cluster_count']
                print(f"      EKS: ${account_eks_cost:.2f} ({clusters} clusters)")

            print(f"      Historical (9hrs): ${account_historical:.2f}")
            print(f"      Forecast (9hrs): ${account_forecast:.2f}")

        print("\n" + "=" * 80)

        # Output aggregated results to a single file
        aggregated_results = {
            "execution_timestamp": self.execution_timestamp,
            "calculated_at": self.current_time_str,
            "accounts_processed": len(selected_account_ids),
            "regions_processed": selected_regions,
            "total_cost": total_cost,
            "currency": "USD",
            "ec2": {
                "total_cost": total_ec2_cost,
                "instance_count": total_ec2_instances,
                "accounts": all_ec2_results
            } if calculate_ec2 else {},
            "eks": {
                "total_cost": total_eks_cost,
                "cluster_count": total_eks_clusters,
                "accounts": all_eks_results
            } if calculate_eks else {},
            "historical_analysis": {
                "period": "Last 9 hours",
                "total_historical_cost": total_historical_cost,
                "accounts": all_historical_results
            },
            "forecast_analysis": {
                "period": "Next 9 hours",
                "total_forecast_cost": total_forecast_cost,
                "confidence_level": "85%",
                "accounts": all_forecast_results
            }
        }

        # Save aggregated results
        aggregated_output_file = f"aws/live-cost/cost_summary_{self.execution_timestamp}.json"
        os.makedirs("aws/live-cost", exist_ok=True)
        with open(aggregated_output_file, 'w') as f:
            json.dump(aggregated_results, f, indent=2, default=str)

        # Generate HTML Report
        print("\n📊 Generating comprehensive HTML report...")
        html_filename = self.generate_html_report(aggregated_results, all_ec2_results, all_eks_results,
                                                  all_historical_results, all_forecast_results)

        # Output file locations
        print("\n📄 OUTPUT FILES:")
        print(f"   📊 HTML Report: {html_filename}")
        print(f"   📋 Aggregated Cost Report: {aggregated_output_file}")

        # Show individual file locations with updated paths
        for account_id in selected_account_ids:
            account_save_name = self.account_id_to_name.get(account_id, "Unknown")
            if calculate_ec2 and account_id in all_ec2_results:
                print(
                    f"   💻 EC2 Cost Report ({account_id}): {self.ec2_output_dir}/{account_save_name}/ec2_cost_{account_save_name}_{self.execution_timestamp}.json")

            if calculate_eks and account_id in all_eks_results:
                print(
                    f"   🚢 EKS Cost Report ({account_id}): {self.eks_output_dir}/{account_save_name}/eks_cost_{account_save_name}_{self.execution_timestamp}.json")

        print(f"   📝 Log File: {self.log_filename}")

        print("\n✅ Cost calculation and analysis complete!\n")

    def generate_data_tables_html(self, aggregated_results):
        """Generate HTML for data tables"""
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_user = "varadharajaan"

        html = '<div class="data-tables">'

        # EC2 Summary Table
        if aggregated_results.get('ec2', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">🖥️ EC2 Instances Summary - Generated: {current_timestamp} by {current_user}</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Region</th>
                            <th>Instance ID</th>
                            <th>Instance Name</th>
                            <th>Type</th>
                            <th>State</th>
                            <th>Launch Time</th>
                            <th>Uptime (hrs)</th>
                            <th>Hourly Rate</th>
                            <th>Estimated Cost</th>
                            <th>CPU Utilization</th>
                            <th>Health Status</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, ec2_data in aggregated_results['ec2']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")
                for region, region_data in ec2_data.get('regions', {}).items():
                    for instance in region_data.get('instances', []):
                        cpu_util = instance['health'].get('cpu_utilization')
                        cpu_display = f"{cpu_util}%" if cpu_util is not None else "N/A"
                        status = instance['health'].get('status', 'Unknown')

                        # Determine status class
                        if status.lower() == 'running':
                            status_class = 'status-active'
                        elif status.lower() in ['pending', 'stopping', 'starting']:
                            status_class = 'status-warning'
                        else:
                            status_class = 'status-error'

                        # Determine CPU class
                        cpu_class = ''
                        if cpu_util is not None:
                            if cpu_util > 80:
                                cpu_class = 'status-error'
                            elif cpu_util > 60:
                                cpu_class = 'status-warning'
                            else:
                                cpu_class = 'status-active'

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td><code>{instance['instance_id']}</code></td>
                            <td>{instance['instance_name']}</td>
                            <td><strong>{instance['instance_type']}</strong></td>
                            <td><span class="{status_class}">{status}</span></td>
                            <td>{instance['launch_time']}</td>
                            <td>{instance['uptime_hours']:.2f}</td>
                            <td>${instance['hourly_rate']:.4f}</td>
                            <td class="cost-highlight">${instance['estimated_cost']:.2f}</td>
                            <td class="{cpu_class}">{cpu_display}</td>
                            <td class="{status_class}">{status}</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>💡 <strong>Health Status:</strong> Data collected from CloudWatch metrics. CPU utilization shows average over last hour.</small>
                </div>
            </div>
            '''

        # EKS Summary Table
        if aggregated_results.get('eks', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">🚢 EKS Clusters Summary - Generated: {current_timestamp} by {current_user}</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Region</th>
                            <th>Cluster Name</th>
                            <th>Version</th>
                            <th>Status</th>
                            <th>Created At</th>
                            <th>Uptime (hrs)</th>
                            <th>Control Plane Cost</th>
                            <th>Worker Nodes Cost</th>
                            <th>Total Cost</th>
                            <th>Nodegroups</th>
                            <th>Efficiency</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, eks_data in aggregated_results['eks']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")
                for region, region_data in eks_data.get('regions', {}).items():
                    for cluster in region_data.get('clusters', []):
                        worker_cost = cluster['total_cost'] - cluster['control_plane']['cost']
                        nodegroup_count = len(cluster.get('nodegroups', []))

                        # Calculate efficiency score (simplified)
                        efficiency_score = "High" if worker_cost > 0 else "Low"
                        efficiency_class = "status-active" if efficiency_score == "High" else "status-warning"

                        # Version status
                        version = cluster['version']
                        version_class = "status-active" if version >= "1.25" else "status-warning"

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td><strong>{cluster['cluster_name']}</strong></td>
                            <td class="{version_class}">v{version}</td>
                            <td class="status-active">{cluster['status']}</td>
                            <td>{cluster['created_at']}</td>
                            <td>{cluster['uptime_hours']:.2f}</td>
                            <td class="cost-highlight">${cluster['control_plane']['cost']:.2f}</td>
                            <td class="cost-highlight">${worker_cost:.2f}</td>
                            <td class="cost-highlight"><strong>${cluster['total_cost']:.2f}</strong></td>
                            <td>{nodegroup_count}</td>
                            <td class="{efficiency_class}">{efficiency_score}</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>💡 <strong>Cost Breakdown:</strong> Control Plane = $0.10/hour per cluster. Worker Nodes = EC2 instance costs in nodegroups.</small>
                </div>
            </div>
            '''

        # Historical Analysis Table
        if aggregated_results.get('historical_analysis', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">📈 Historical Cost Analysis (Last 9 Hours) - Generated: {current_timestamp} by {current_user}</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Service</th>
                            <th>Region</th>
                            <th>Resource Count</th>
                            <th>Analysis Period</th>
                            <th>Total Running Hours</th>
                            <th>Historical Cost</th>
                            <th>Avg Hourly Rate</th>
                            <th>Trend</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, historical_data in aggregated_results['historical_analysis']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")

                # EC2 Historical Data
                for region, region_data in historical_data.get('regions', {}).items():
                    ec2_instances = region_data.get('ec2_instances', [])
                    if ec2_instances:
                        total_hours = sum(i.get('running_hours', 0) for i in ec2_instances)
                        total_cost = sum(i.get('historical_cost', 0) for i in ec2_instances)
                        avg_hourly = total_cost / total_hours if total_hours > 0 else 0

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🖥️ EC2</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(ec2_instances)}</td>
                            <td>{historical_data.get('start_time', 'N/A')} - {historical_data.get('end_time', 'N/A')}</td>
                            <td>{total_hours:.1f}</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td>${avg_hourly:.4f}</td>
                            <td class="status-active">Stable</td>
                        </tr>
                        '''

                    # EKS Historical Data
                    eks_clusters = region_data.get('eks_clusters', [])
                    if eks_clusters:
                        total_hours = sum(c.get('running_hours', 0) for c in eks_clusters)
                        total_cost = sum(c.get('total_cost', 0) for c in eks_clusters)
                        avg_hourly = total_cost / total_hours if total_hours > 0 else 0

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🚢 EKS</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(eks_clusters)}</td>
                            <td>{historical_data.get('start_time', 'N/A')} - {historical_data.get('end_time', 'N/A')}</td>
                            <td>{total_hours:.1f}</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td>${avg_hourly:.4f}</td>
                            <td class="status-active">Stable</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>📊 <strong>Historical Analysis:</strong> Costs calculated based on actual running time during the last 9 hours.</small>
                </div>
            </div>
            '''

        # Forecast Analysis Table
        if aggregated_results.get('forecast_analysis', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">🔮 Cost Forecast Analysis (Next 9 Hours) - Generated: {current_timestamp} by {current_user}</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Service</th>
                            <th>Region</th>
                            <th>Resource Count</th>
                            <th>Forecast Period</th>
                            <th>Forecast Hours</th>
                            <th>Forecast Cost</th>
                            <th>Confidence Level</th>
                            <th>Assumptions</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, forecast_data in aggregated_results['forecast_analysis']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")

                # EC2 Forecast Data
                for region, region_data in forecast_data.get('regions', {}).items():
                    ec2_forecast = region_data.get('ec2_forecast', [])
                    if ec2_forecast:
                        total_cost = sum(i.get('forecast_cost', 0) for i in ec2_forecast)

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🖥️ EC2</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(ec2_forecast)}</td>
                            <td>{forecast_data.get('start_time', 'N/A')} - {forecast_data.get('end_time', 'N/A')}</td>
                            <td>9.0</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td class="status-active">85%</td>
                            <td>Current configuration maintained</td>
                        </tr>
                        '''

                    # EKS Forecast Data
                    eks_forecast = region_data.get('eks_forecast', [])
                    if eks_forecast:
                        total_cost = sum(c.get('total_forecast', 0) for c in eks_forecast)

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🚢 EKS</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(eks_forecast)}</td>
                            <td>{forecast_data.get('start_time', 'N/A')} - {forecast_data.get('end_time', 'N/A')}</td>
                            <td>9.0</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td class="status-active">85%</td>
                            <td>Current scaling maintained</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>🔮 <strong>Forecast Assumptions:</strong> Based on current resource configuration and historical usage patterns. Confidence levels may vary based on workload stability.</small>
                </div>
            </div>
            '''

        # Cost Optimization Recommendations Table
        html += f'''
        <div class="table-container">
            <div class="table-header">💡 Cost Optimization Recommendations - Generated: {current_timestamp} by {current_user}</div>
            <table>
                <thead>
                    <tr>
                        <th>Priority</th>
                        <th>Resource Type</th>
                        <th>Recommendation</th>
                        <th>Potential Savings</th>
                        <th>Effort</th>
                        <th>Impact</th>
                        <th>Implementation</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><span class="status-error">🔴 High</span></td>
                        <td>🖥️ EC2</td>
                        <td>Review underutilized instances (CPU < 20%)</td>
                        <td class="cost-highlight">$50-200/month</td>
                        <td>Low</td>
                        <td>High</td>
                        <td>Right-size or terminate unused instances</td>
                    </tr>
                    <tr>
                        <td><span class="status-warning">🟡 Medium</span></td>
                        <td>🚢 EKS</td>
                        <td>Implement cluster autoscaling</td>
                        <td class="cost-highlight">$30-100/month</td>
                        <td>Medium</td>
                        <td>Medium</td>
                        <td>Configure HPA and VPA</td>
                    </tr>
                    <tr>
                        <td><span class="status-active">🟢 Low</span></td>
                        <td>🌍 Multi-Region</td>
                        <td>Consider Reserved Instances for consistent workloads</td>
                        <td class="cost-highlight">$100-500/month</td>
                        <td>Low</td>
                        <td>High</td>
                        <td>Purchase 1-year or 3-year RIs</td>
                    </tr>
                    <tr>
                        <td><span class="status-warning">🟡 Medium</span></td>
                        <td>💾 Storage</td>
                        <td>Review EBS volumes and snapshots</td>
                        <td class="cost-highlight">$20-80/month</td>
                        <td>Low</td>
                        <td>Medium</td>
                        <td>Delete unused volumes and old snapshots</td>
                    </tr>
                </tbody>
            </table>
            <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                <small>💡 <strong>Optimization Tips:</strong> Regularly review your cost reports and implement cost optimization strategies. Consider using AWS Cost Explorer and Trusted Advisor for additional insights.</small>
            </div>
        </div>
        '''

        html += '</div>'
        return html

    def generate_html_report(self, aggregated_results, all_ec2_results, all_eks_results, all_historical_results=None,
                             all_forecast_results=None):
        """Generate a modern HTML report with visualizations"""
        import base64
        from datetime import datetime

        # Create the HTML report directory
        html_dir = "aws/live-cost"
        try:
            os.makedirs(html_dir, exist_ok=True)
            self.logger.info(f"Created/verified directory: {html_dir}")
        except Exception as e:
            self.logger.error(f"Failed to create directory {html_dir}: {e}")
            # Fallback to current directory
            html_dir = "."

        # Generate filename with timestamp - updated naming convention
        timestamp = self.execution_timestamp
        html_filename = f"{html_dir}/aws_cost_report_{timestamp}.html"

        # Prepare data for charts including historical and forecast
        chart_data = self.prepare_chart_data(aggregated_results, all_ec2_results, all_eks_results)

        # Generate the HTML content
        html_content = self.generate_html_content(aggregated_results, chart_data, timestamp, all_historical_results,
                                                  all_forecast_results)

        # Write HTML file
        try:
            with open(html_filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"HTML report generated: {html_filename}")
            print(f"   📊 HTML Report: {html_filename}")
        except Exception as e:
            self.logger.error(f"Failed to save HTML report to {html_filename}: {e}")
            print(f"   ❌ Failed to save HTML report: {e}")
            return None

        return html_filename

    def prepare_chart_data(self, aggregated_results, all_ec2_results, all_eks_results):
        """Prepare data for charts and visualizations"""
        chart_data = {
            'account_costs': [],
            'service_breakdown': [],
            'regional_distribution': {},
            'instance_types': {},
            'cluster_versions': {},
            'timeline_data': []
        }

        # Account costs data
        for account_id, ec2_data in all_ec2_results.items():
            account_name = self.account_id_to_name.get(account_id, "Unknown")
            ec2_cost = ec2_data.get('total_cost', 0)
            eks_cost = all_eks_results.get(account_id, {}).get('total_cost', 0)

            chart_data['account_costs'].append({
                'account': f"{account_name} ({account_id})",
                'ec2_cost': ec2_cost,
                'eks_cost': eks_cost,
                'total_cost': ec2_cost + eks_cost
            })

        # Service breakdown
        total_ec2 = aggregated_results.get('ec2', {}).get('total_cost', 0)
        total_eks = aggregated_results.get('eks', {}).get('total_cost', 0)

        if total_ec2 > 0:
            chart_data['service_breakdown'].append({'service': 'EC2', 'cost': total_ec2})
        if total_eks > 0:
            chart_data['service_breakdown'].append({'service': 'EKS', 'cost': total_eks})

        # Regional distribution
        for account_id, ec2_data in all_ec2_results.items():
            for region, region_data in ec2_data.get('regions', {}).items():
                if region not in chart_data['regional_distribution']:
                    chart_data['regional_distribution'][region] = {'ec2': 0, 'eks': 0}
                chart_data['regional_distribution'][region]['ec2'] += region_data.get('total_cost', 0)

        for account_id, eks_data in all_eks_results.items():
            for region, region_data in eks_data.get('regions', {}).items():
                if region not in chart_data['regional_distribution']:
                    chart_data['regional_distribution'][region] = {'ec2': 0, 'eks': 0}
                chart_data['regional_distribution'][region]['eks'] += region_data.get('total_cost', 0)

        # Instance types distribution
        for account_id, ec2_data in all_ec2_results.items():
            for region, region_data in ec2_data.get('regions', {}).items():
                for instance in region_data.get('instances', []):
                    instance_type = instance['instance_type']
                    if instance_type not in chart_data['instance_types']:
                        chart_data['instance_types'][instance_type] = {'count': 0, 'cost': 0}
                    chart_data['instance_types'][instance_type]['count'] += 1
                    chart_data['instance_types'][instance_type]['cost'] += instance['estimated_cost']

        # EKS cluster versions
        for account_id, eks_data in all_eks_results.items():
            for region, region_data in eks_data.get('regions', {}).items():
                for cluster in region_data.get('clusters', []):
                    version = cluster['version']
                    if version not in chart_data['cluster_versions']:
                        chart_data['cluster_versions'][version] = {'count': 0, 'cost': 0}
                    chart_data['cluster_versions'][version]['count'] += 1
                    chart_data['cluster_versions'][version]['cost'] += cluster['total_cost']

        return chart_data

    def generate_html_content(self, aggregated_results, chart_data, timestamp, historical_results=None,
                              forecast_results=None):
        """Generate the complete HTML content with proper error handling"""

        # Current timestamp and user
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_user = "varadharajaan"
        formatted_timestamp = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")

        # Safely calculate additional metrics with error handling
        try:
            total_historical = 0
            if historical_results and isinstance(historical_results, dict):
                for account_data in historical_results.values():
                    if isinstance(account_data, dict):
                        total_historical += account_data.get('total_historical_cost', 0)
        except Exception as e:
            self.logger.warning(f"Error calculating historical total: {e}")
            total_historical = 0

        try:
            total_forecast = 0
            if forecast_results and isinstance(forecast_results, dict):
                for account_data in forecast_results.values():
                    if isinstance(account_data, dict):
                        total_forecast += account_data.get('total_forecast_cost', 0)
        except Exception as e:
            self.logger.warning(f"Error calculating forecast total: {e}")
            total_forecast = 0

        try:
            current_total = aggregated_results.get('total_cost', 0) if isinstance(aggregated_results, dict) else 0
        except Exception as e:
            self.logger.warning(f"Error getting current total: {e}")
            current_total = 0

        # Calculate trends safely
        historical_trend = 0
        forecast_trend = 0

        try:
            if total_historical > 0 and current_total > 0:
                historical_trend = ((current_total - total_historical) / total_historical) * 100
        except Exception as e:
            self.logger.warning(f"Error calculating historical trend: {e}")
            historical_trend = 0

        try:
            if current_total > 0 and total_forecast > 0:
                forecast_trend = ((total_forecast - current_total) / current_total) * 100
        except Exception as e:
            self.logger.warning(f"Error calculating forecast trend: {e}")
            forecast_trend = 0

        # Generate data tables HTML safely
        try:
            data_tables_html = self.generate_data_tables_html_inline(aggregated_results, current_timestamp,
                                                                     current_user)
        except Exception as e:
            self.logger.error(f"Error generating data tables: {e}")
            data_tables_html = '<div class="data-tables"><p>Error generating data tables.</p></div>'

        # Safely get aggregated data
        try:
            accounts_processed = aggregated_results.get('accounts_processed', 0) if isinstance(aggregated_results,
                                                                                               dict) else 0
            ec2_data = aggregated_results.get('ec2', {}) if isinstance(aggregated_results, dict) else {}
            eks_data = aggregated_results.get('eks', {}) if isinstance(aggregated_results, dict) else {}
            ec2_instance_count = ec2_data.get('instance_count', 0) if isinstance(ec2_data, dict) else 0
            eks_cluster_count = eks_data.get('cluster_count', 0) if isinstance(eks_data, dict) else 0
        except Exception as e:
            self.logger.warning(f"Error extracting aggregated data: {e}")
            accounts_processed = 0
            ec2_instance_count = 0
            eks_cluster_count = 0

        html_content = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AWS Cost Report - {formatted_timestamp}</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
        <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }}

            .container {{
                max-width: 1400px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                overflow: hidden;
            }}

            .header {{
                background: linear-gradient(135deg, #2196F3 0%, #21CBF3 100%);
                color: white;
                padding: 30px;
                text-align: center;
                position: relative;
            }}

            .header h1 {{
                font-size: 2.5em;
                margin-bottom: 10px;
                font-weight: 300;
            }}

            .header .subtitle {{
                font-size: 1.2em;
                opacity: 0.9;
            }}

            .header .timestamp {{
                position: absolute;
                top: 20px;
                right: 30px;
                background: rgba(255,255,255,0.2);
                padding: 10px 15px;
                border-radius: 20px;
                font-size: 0.9em;
            }}

            .controls {{
                padding: 20px 30px;
                background: #f8f9fa;
                border-bottom: 1px solid #e9ecef;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}

            .btn {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 25px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 500;
                transition: all 0.3s ease;
                text-decoration: none;
                display: inline-block;
                margin-right: 10px;
            }}

            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 20px rgba(0,0,0,0.2);
            }}

            .btn-pdf {{
                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            }}

            .summary-cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                padding: 30px;
                background: #f8f9fa;
            }}

            .card {{
                background: white;
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                text-align: center;
                transition: transform 0.3s ease;
                position: relative;
            }}

            .card:hover {{
                transform: translateY(-5px);
            }}

            .card-icon {{
                font-size: 2.5em;
                margin-bottom: 15px;
            }}

            .card-title {{
                font-size: 1.1em;
                color: #666;
                margin-bottom: 10px;
            }}

            .card-value {{
                font-size: 2em;
                font-weight: bold;
                color: #333;
            }}

            .card-trend {{
                position: absolute;
                top: 10px;
                right: 15px;
                font-size: 0.8em;
                padding: 4px 8px;
                border-radius: 12px;
                font-weight: bold;
            }}

            .trend-up {{
                background: #e8f5e8;
                color: #28a745;
            }}

            .trend-down {{
                background: #fdeaea;
                color: #dc3545;
            }}

            .trend-neutral {{
                background: #e2e3e5;
                color: #6c757d;
            }}

            .charts-container {{
                padding: 30px;
            }}

            .chart-row {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 30px;
                margin-bottom: 30px;
            }}

            .chart-single {{
                display: grid;
                grid-template-columns: 1fr;
                gap: 30px;
                margin-bottom: 30px;
            }}

            .chart-box {{
                background: white;
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }}

            .chart-title {{
                font-size: 1.3em;
                font-weight: 600;
                color: #333;
                margin-bottom: 20px;
                text-align: center;
            }}

            .chart-canvas {{
                max-height: 400px;
            }}

            .data-tables {{
                padding: 30px;
                background: #f8f9fa;
            }}

            .table-container {{
                background: white;
                border-radius: 15px;
                overflow: hidden;
                margin-bottom: 30px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }}

            .table-header {{
                background: linear-gradient(135deg, #2196F3 0%, #21CBF3 100%);
                color: white;
                padding: 20px;
                font-size: 1.2em;
                font-weight: 600;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
            }}

            th, td {{
                padding: 15px;
                text-align: left;
                border-bottom: 1px solid #e9ecef;
                vertical-align: top;
            }}

            th {{
                background: #f8f9fa;
                font-weight: 600;
                color: #333;
                position: sticky;
                top: 0;
                z-index: 10;
            }}

            tr:hover {{
                background: #f8f9fa;
            }}

            .cost-highlight {{
                font-weight: bold;
                color: #2196F3;
            }}

            .status-active {{
                color: #28a745;
                font-weight: bold;
            }}

            .status-warning {{
                color: #ffc107;
                font-weight: bold;
            }}

            .status-error {{
                color: #dc3545;
                font-weight: bold;
            }}

            .footer {{
                padding: 30px;
                text-align: center;
                background: #333;
                color: white;
            }}

            .insights-section {{
                padding: 30px;
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            }}

            .insight-card {{
                background: white;
                border-radius: 15px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                border-left: 5px solid #2196F3;
            }}

            .insight-title {{
                font-size: 1.2em;
                font-weight: 600;
                color: #333;
                margin-bottom: 10px;
            }}

            .insight-text {{
                color: #666;
                line-height: 1.6;
            }}

            .metric-badge {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8em;
                margin-left: 10px;
            }}

            .progress-bar {{
                width: 100%;
                height: 6px;
                background: #e9ecef;
                border-radius: 3px;
                overflow: hidden;
                margin-top: 10px;
            }}

            .progress-fill {{
                height: 100%;
                background: linear-gradient(135deg, #2196F3 0%, #21CBF3 100%);
                transition: width 0.3s ease;
            }}

            .timeline-section {{
                background: white;
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 30px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }}

            code {{
                background: #f8f9fa;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 0.9em;
            }}

            small {{
                color: #666;
                font-size: 0.85em;
            }}

            @media (max-width: 768px) {{
                .chart-row {{
                    grid-template-columns: 1fr;
                }}

                .summary-cards {{
                    grid-template-columns: 1fr;
                }}

                .header h1 {{
                    font-size: 2em;
                }}

                .header .timestamp {{
                    position: static;
                    margin-top: 15px;
                    display: inline-block;
                }}

                .controls {{
                    flex-direction: column;
                    gap: 15px;
                }}

                table {{
                    font-size: 0.9em;
                }}

                th, td {{
                    padding: 10px 8px;
                }}
            }}

            .loading {{
                text-align: center;
                padding: 20px;
                color: #666;
            }}

            @media print {{
                body {{
                    background: white;
                }}

                .controls {{
                    display: none;
                }}

                .container {{
                    box-shadow: none;
                    border-radius: 0;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container" id="reportContent">
            <div class="header">
                <div class="timestamp">Generated: {current_timestamp} UTC</div>
                <h1>💰 AWS Cost Analysis Report</h1>
                <div class="subtitle">Live Cost Calculator & Health Metadata • Historical Analysis & Forecasting</div>
            </div>

            <div class="controls">
                <div>
                    <button class="btn" onclick="window.print()">🖨️ Print Report</button>
                    <button class="btn btn-pdf" onclick="downloadPDF()">📄 Download PDF</button>
                    <button class="btn" onclick="location.reload()">🔄 Refresh Data</button>
                </div>
                <div style="color: #666;">
                    Report ID: {timestamp} • Generated by: {current_user} • {current_timestamp} UTC
                </div>
            </div>

            <div class="summary-cards">
                <div class="card">
                    <div class="card-trend {'trend-up' if forecast_trend > 5 else 'trend-down' if forecast_trend < -5 else 'trend-neutral'}">
                        {'+' if forecast_trend > 0 else ''}{forecast_trend:.1f}%
                    </div>
                    <div class="card-icon">💵</div>
                    <div class="card-title">Current Total Cost</div>
                    <div class="card-value">${current_total:.2f}</div>
                </div>
                <div class="card">
                    <div class="card-icon">📈</div>
                    <div class="card-title">Historical (9hrs)</div>
                    <div class="card-value">${total_historical:.2f}</div>
                </div>
                <div class="card">
                    <div class="card-icon">🔮</div>
                    <div class="card-title">Forecast (9hrs)</div>
                    <div class="card-value">${total_forecast:.2f}</div>
                </div>
                <div class="card">
                    <div class="card-icon">🏦</div>
                    <div class="card-title">Accounts</div>
                    <div class="card-value">{accounts_processed}</div>
                </div>
                <div class="card">
                    <div class="card-icon">🖥️</div>
                    <div class="card-title">EC2 Instances</div>
                    <div class="card-value">{ec2_instance_count}</div>
                </div>
                <div class="card">
                    <div class="card-icon">🚢</div>
                    <div class="card-title">EKS Clusters</div>
                    <div class="card-value">{eks_cluster_count}</div>
                </div>
            </div>

            <div class="insights-section">
                <h2 style="text-align: center; margin-bottom: 30px; color: #333;">💡 Cost Insights & Analysis</h2>

                <div class="insight-card">
                    <div class="insight-title">📊 Cost Trend Analysis</div>
                    <div class="insight-text">
                        {'Your costs are trending upward' if forecast_trend > 5 else 'Your costs are trending downward' if forecast_trend < -5 else 'Your costs are relatively stable'} 
                        with a {forecast_trend:.1f}% change projected over the next 9 hours.
                        Historical analysis shows ${total_historical:.2f} spent in the last 9 hours.
                    </div>
                </div>

                <div class="insight-card">
                    <div class="insight-title">🎯 Optimization Opportunities</div>
                    <div class="insight-text">
                        Based on your current usage patterns, consider reviewing instances with low CPU utilization 
                        and evaluating right-sizing opportunities for cost optimization. Monitor your forecasted costs regularly.
                    </div>
                </div>

                <div class="insight-card">
                    <div class="insight-title">⚡ Real-time Monitoring</div>
                    <div class="insight-text">
                        This report includes real-time health metrics and utilization data to help you make 
                        informed decisions about your AWS infrastructure spending. Data collected at {current_timestamp} UTC by {current_user}.
                    </div>
                </div>
            </div>

            <div class="charts-container">
                <div class="timeline-section">
                    <div class="chart-title">📈 Cost Timeline: Historical → Current → Forecast</div>
                    <canvas id="timelineChart" class="chart-canvas"></canvas>
                </div>

                <div class="chart-row">
                    <div class="chart-box">
                        <div class="chart-title">💹 Service Cost Breakdown</div>
                        <canvas id="serviceChart" class="chart-canvas"></canvas>
                    </div>
                    <div class="chart-box">
                        <div class="chart-title">🏦 Cost Distribution by Account</div>
                        <canvas id="accountChart" class="chart-canvas"></canvas>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-box">
                        <div class="chart-title">🌍 Regional Cost Distribution</div>
                        <canvas id="regionChart" class="chart-canvas"></canvas>
                    </div>
                    <div class="chart-box">
                        <div class="chart-title">⚙️ Top Instance Types by Cost</div>
                        <canvas id="instanceChart" class="chart-canvas"></canvas>
                    </div>
                </div>
            </div>

            {data_tables_html}

            <div class="footer">
                <p>🚀 AWS Cost Report Generated by Live Cost Calculator</p>
                <p>📅 Report Generated: {current_timestamp} UTC • 🆔 Report ID: {timestamp}</p>
                <p>👤 Generated by: {current_user} • 🌐 Execution Time: {formatted_timestamp}</p>
                <p>💻 System: AWS Live Cost Calculator v2.1 • 📊 Data Source: Real-time AWS APIs</p>
            </div>
        </div>

        <script>
            // Chart.js default configuration
            Chart.defaults.responsive = true;
            Chart.defaults.maintainAspectRatio = false;
            Chart.defaults.plugins.legend.labels.usePointStyle = true;

            // Chart data - safely handle chart_data
            let chartData;
            try {{
                chartData = {chart_data};
            }} catch(e) {{
                console.warn('Error loading chart data:', e);
                chartData = {{
                    service_breakdown: [],
                    account_costs: [],
                    regional_distribution: {{}},
                    instance_types: {{}}
                }};
            }}

            // Timeline Chart (Historical + Current + Forecast)
            const timelineCtx = document.getElementById('timelineChart').getContext('2d');
            const timelineLabels = ['-9h', '-6h', '-3h', 'Now', '+3h', '+6h', '+9h'];
            const timelineData = [
                {total_historical * 0.6:.2f},
                {total_historical * 0.8:.2f},
                {total_historical:.2f},
                {current_total:.2f},
                {total_forecast * 0.4:.2f},
                {total_forecast * 0.7:.2f},
                {total_forecast:.2f}
            ];

            new Chart(timelineCtx, {{
                type: 'line',
                data: {{
                    labels: timelineLabels,
                    datasets: [{{
                        label: 'Cost Trend ($)',
                        data: timelineData,
                        borderColor: '#FF6384',
                        backgroundColor: 'rgba(255, 99, 132, 0.1)',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4,
                        pointBackgroundColor: ['#36A2EB', '#36A2EB', '#36A2EB', '#FF6384', '#FFCE56', '#FFCE56', '#FFCE56'],
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        pointRadius: 6
                    }}]
                }},
                options: {{
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const phase = context.dataIndex < 3 ? 'Historical' : 
                                                context.dataIndex === 3 ? 'Current' : 'Forecast';
                                    return phase + ': $' + context.parsed.y.toFixed(2);
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            ticks: {{
                                callback: function(value) {{
                                    return '$' + value.toFixed(2);
                                }}
                            }}
                        }},
                        x: {{
                            grid: {{
                                color: function(context) {{
                                    return context.tick.value === 3 ? '#FF6384' : '#e9ecef';
                                }},
                                lineWidth: function(context) {{
                                    return context.tick.value === 3 ? 3 : 1;
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            // Service Breakdown Chart
            const serviceCtx = document.getElementById('serviceChart').getContext('2d');
            const serviceData = chartData.service_breakdown || [];
            new Chart(serviceCtx, {{
                type: 'doughnut',
                data: {{
                    labels: serviceData.map(item => item.service || 'Unknown'),
                    datasets: [{{
                        data: serviceData.map(item => item.cost || 0),
                        backgroundColor: [
                            '#FF6384',
                            '#36A2EB',
                            '#FFCE56',
                            '#4BC0C0',
                            '#9966FF',
                            '#FF9F40'
                        ],
                        borderWidth: 3,
                        borderColor: '#fff',
                        hoverBorderWidth: 5
                    }}]
                }},
                options: {{
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20,
                                font: {{
                                    size: 12
                                }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = total > 0 ? ((context.parsed / total) * 100).toFixed(1) : '0';
                                    return context.label + ': $' + context.parsed.toFixed(2) + ' (' + percentage + '%)';
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            // Account Chart
            const accountCtx = document.getElementById('accountChart').getContext('2d');
            const accountData = chartData.account_costs || [];
            new Chart(accountCtx, {{
                type: 'bar',
                data: {{
                    labels: accountData.map(item => (item.account || 'Unknown').split('(')[0].trim()),
                    datasets: [
                        {{
                            label: 'EC2 Cost',
                            data: accountData.map(item => item.ec2_cost || 0),
                            backgroundColor: '#36A2EB',
                            borderColor: '#36A2EB',
                            borderWidth: 1,
                            borderRadius: 5
                        }},
                        {{
                            label: 'EKS Cost',
                            data: accountData.map(item => item.eks_cost || 0),
                            backgroundColor: '#FF6384',
                            borderColor: '#FF6384',
                            borderWidth: 1,
                            borderRadius: 5
                        }}
                    ]
                }},
                options: {{
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    return context.dataset.label + ': $' + context.parsed.y.toFixed(2);
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            ticks: {{
                                callback: function(value) {{
                                    return '$' + value.toFixed(2);
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            // Regional Distribution Chart
            const regionCtx = document.getElementById('regionChart').getContext('2d');
            const regionalData = chartData.regional_distribution || {{}};
            const regionLabels = Object.keys(regionalData);
            const regionEC2Data = regionLabels.map(region => (regionalData[region] || {{}}).ec2 || 0);
            const regionEKSData = regionLabels.map(region => (regionalData[region] || {{}}).eks || 0);

            new Chart(regionCtx, {{
                type: 'bar',
                data: {{
                    labels: regionLabels,
                    datasets: [
                        {{
                            label: 'EC2 Cost',
                            data: regionEC2Data,
                            backgroundColor: '#4BC0C0',
                            borderColor: '#4BC0C0',
                            borderWidth: 1,
                            borderRadius: 5
                        }},
                        {{
                            label: 'EKS Cost',
                            data: regionEKSData,
                            backgroundColor: '#FFCE56',
                            borderColor: '#FFCE56',
                            borderWidth: 1,
                            borderRadius: 5
                        }}
                    ]
                }},
                options: {{
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    return context.dataset.label + ': $' + context.parsed.y.toFixed(2);
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            ticks: {{
                                callback: function(value) {{
                                    return '$' + value.toFixed(2);
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            // Instance Types Chart
            const instanceCtx = document.getElementById('instanceChart').getContext('2d');
            const instanceData = chartData.instance_types || {{}};
            const instanceLabels = Object.keys(instanceData).slice(0, 10); // Top 10
            const instanceCosts = instanceLabels.map(type => (instanceData[type] || {{}}).cost || 0);

            new Chart(instanceCtx, {{
                type: 'bar',
                data: {{
                    labels: instanceLabels,
                    datasets: [{{
                        label: 'Cost ($)',
                        data: instanceCosts,
                        backgroundColor: '#FF9F40',
                        borderColor: '#FF9F40',
                        borderWidth: 1,
                        borderRadius: 5
                    }}]
                }},
                options: {{
                    indexAxis: 'y',
                    plugins: {{
                        legend: {{
                            display: false
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const type = context.label;
                                    const cost = context.parsed.x;
                                    const count = ((instanceData[type] || {{}}).count || 0);
                                    return `${{cost.toFixed(2)}} ({{count}} instances)`;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            beginAtZero: true,
                            ticks: {{
                                callback: function(value) {{
                                    return '$' + value.toFixed(2);
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            // PDF Download Function
            async function downloadPDF() {{
                const {{ jsPDF }} = window.jspdf;
                const element = document.getElementById('reportContent');

                // Show loading
                const button = event.target;
                const originalText = button.textContent;
                button.textContent = '📄 Generating PDF...';
                button.disabled = true;

                try {{
                    const canvas = await html2canvas(element, {{
                        scale: 1.5,
                        useCORS: true,
                        logging: false,
                        height: element.scrollHeight,
                        width: element.scrollWidth,
                        backgroundColor: '#ffffff'
                    }});

                    const imgData = canvas.toDataURL('image/png');
                    const pdf = new jsPDF({{
                        orientation: 'portrait',
                        unit: 'mm',
                        format: 'a4'
                    }});

                    const imgWidth = 210;
                    const pageHeight = 295;
                    const imgHeight = (canvas.height * imgWidth) / canvas.width;
                    let heightLeft = imgHeight;
                    let position = 0;

                    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
                    heightLeft -= pageHeight;

                    while (heightLeft >= 0) {{
                        position = heightLeft - imgHeight;
                        pdf.addPage();
                        pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
                        heightLeft -= pageHeight;
                    }}

                    pdf.save(`aws-cost-report-{timestamp}.pdf`);
                }} catch (error) {{
                    console.error('Error generating PDF:', error);
                    alert('Error generating PDF. Please try the print option instead.');
                }} finally {{
                    button.textContent = originalText;
                    button.disabled = false;
                }}
            }}

            // Auto-refresh every 30 minutes
            setTimeout(function() {{
                if (confirm('Data is 30 minutes old. Would you like to refresh the report?')) {{
                    location.reload();
                }}
            }}, 30 * 60 * 1000);

            // Print styles
            window.addEventListener('beforeprint', function() {{
                document.body.style.background = 'white';
            }});

            window.addEventListener('afterprint', function() {{
                document.body.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
            }});

            // Add loading animation
            document.addEventListener('DOMContentLoaded', function() {{
                const cards = document.querySelectorAll('.card');
                cards.forEach((card, index) => {{
                    setTimeout(() => {{
                        card.style.opacity = '0';
                        card.style.transform = 'translateY(20px)';
                        card.style.transition = 'all 0.5s ease';
                        setTimeout(() => {{
                            card.style.opacity = '1';
                            card.style.transform = 'translateY(0)';
                        }}, 100);
                    }}, index * 100);
                }});
            }});

            // Update timestamp every second
            setInterval(function() {{
                const now = new Date();
                const timeStr = now.toISOString().slice(0, 19).replace('T', ' ');
                // Update any dynamic timestamps if needed
            }}, 1000);
        </script>
    </body>
    </html>
        '''

        return html_content

    def generate_data_tables_html_inline(self, aggregated_results, current_timestamp, current_user):
        """Generate HTML for data tables inline with EKS table included"""
        html = '<div class="data-tables">'

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # EC2 Summary Table
        if aggregated_results.get('ec2', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">🖥️ EC2 Instances Summary - Generated: {now_str} by varadharajaan</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Region</th>
                            <th>Instance ID</th>
                            <th>Instance Name</th>
                            <th>Type</th>
                            <th>State</th>
                            <th>Launch Time</th>
                            <th>Uptime (hrs)</th>
                            <th>Hourly Rate</th>
                            <th>Estimated Cost</th>
                            <th>CPU Utilization</th>
                            <th>Health Status</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, ec2_data in aggregated_results['ec2']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")
                for region, region_data in ec2_data.get('regions', {}).items():
                    for instance in region_data.get('instances', []):
                        cpu_util = instance['health'].get('cpu_utilization')
                        cpu_display = f"{cpu_util}%" if cpu_util is not None else "N/A"
                        status = instance['health'].get('status', 'Unknown')

                        # Determine status class
                        if status.lower() == 'running':
                            status_class = 'status-active'
                        elif status.lower() in ['pending', 'stopping', 'starting']:
                            status_class = 'status-warning'
                        else:
                            status_class = 'status-error'

                        # Determine CPU class
                        cpu_class = ''
                        if cpu_util is not None:
                            if cpu_util > 80:
                                cpu_class = 'status-error'
                            elif cpu_util > 60:
                                cpu_class = 'status-warning'
                            else:
                                cpu_class = 'status-active'

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td><code>{instance['instance_id']}</code></td>
                            <td>{instance['instance_name']}</td>
                            <td><strong>{instance['instance_type']}</strong></td>
                            <td><span class="{status_class}">{status}</span></td>
                            <td>{instance['launch_time']}</td>
                            <td>{instance['uptime_hours']:.2f}</td>
                            <td>${instance['hourly_rate']:.4f}</td>
                            <td class="cost-highlight">${instance['estimated_cost']:.2f}</td>
                            <td class="{cpu_class}">{cpu_display}</td>
                            <td class="{status_class}">{status}</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>💡 <strong>Health Status:</strong> Data collected from CloudWatch metrics. CPU utilization shows average over last hour.</small>
                </div>
            </div>
            '''

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # EKS Summary Table - THIS WAS MISSING!
        if aggregated_results.get('eks', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">🚢 EKS Clusters Summary - Generated: {now_str} by varadharajaan</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Region</th>
                            <th>Cluster Name</th>
                            <th>Version</th>
                            <th>Status</th>
                            <th>Created At</th>
                            <th>Uptime (hrs)</th>
                            <th>Control Plane Cost</th>
                            <th>Worker Nodes Cost</th>
                            <th>Total Cost</th>
                            <th>Nodegroups</th>
                            <th>Efficiency</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, eks_data in aggregated_results['eks']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")
                for region, region_data in eks_data.get('regions', {}).items():
                    for cluster in region_data.get('clusters', []):
                        worker_cost = cluster['total_cost'] - cluster['control_plane']['cost']
                        nodegroup_count = len(cluster.get('nodegroups', []))

                        # Calculate efficiency score (simplified)
                        efficiency_score = "High" if worker_cost > 0 else "Low"
                        efficiency_class = "status-active" if efficiency_score == "High" else "status-warning"

                        # Version status
                        version = cluster['version']
                        version_class = "status-active" if version >= "1.25" else "status-warning"

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td><strong>{cluster['cluster_name']}</strong></td>
                            <td class="{version_class}">v{version}</td>
                            <td class="status-active">{cluster['status']}</td>
                            <td>{cluster['created_at']}</td>
                            <td>{cluster['uptime_hours']:.2f}</td>
                            <td class="cost-highlight">${cluster['control_plane']['cost']:.2f}</td>
                            <td class="cost-highlight">${worker_cost:.2f}</td>
                            <td class="cost-highlight"><strong>${cluster['total_cost']:.2f}</strong></td>
                            <td>{nodegroup_count}</td>
                            <td class="{efficiency_class}">{efficiency_score}</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>💡 <strong>Cost Breakdown:</strong> Control Plane = $0.10/hour per cluster. Worker Nodes = EC2 instance costs in nodegroups.</small>
                </div>
            </div>
            '''
        else:
            # Add message if no EKS clusters found
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

            html += f'''
            <div class="table-container">
                <div class="table-header">🚢 EKS Clusters Summary - Generated: {now_str} by varadharajaan</div>
                <div style="padding: 30px; text-align: center; color: #666;">
                    <div style="font-size: 3em; margin-bottom: 15px;">🚢</div>
                    <h3>No EKS Clusters Found</h3>
                    <p>No active EKS clusters were detected in the selected accounts and regions.</p>
                    <small>This could be because:</small>
                    <ul style="text-align: left; display: inline-block; margin-top: 10px;">
                        <li>No EKS clusters exist in the selected regions</li>
                        <li>Clusters are in different regions than scanned</li>
                        <li>Access permissions may be limited</li>
                        <li>Clusters are not in ACTIVE status</li>
                    </ul>
                </div>
            </div>
            '''

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Historical Analysis Table
        if aggregated_results.get('historical_analysis', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">📈 Historical Cost Analysis (Last 9 Hours) - Generated: {now_str} by varadharajaan</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Service</th>
                            <th>Region</th>
                            <th>Resource Count</th>
                            <th>Analysis Period</th>
                            <th>Total Running Hours</th>
                            <th>Historical Cost</th>
                            <th>Avg Hourly Rate</th>
                            <th>Trend</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, historical_data in aggregated_results['historical_analysis']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")

                # EC2 Historical Data
                for region, region_data in historical_data.get('regions', {}).items():
                    ec2_instances = region_data.get('ec2_instances', [])
                    if ec2_instances:
                        total_hours = sum(i.get('running_hours', 0) for i in ec2_instances)
                        total_cost = sum(i.get('historical_cost', 0) for i in ec2_instances)
                        avg_hourly = total_cost / total_hours if total_hours > 0 else 0

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🖥️ EC2</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(ec2_instances)}</td>
                            <td>{historical_data.get('start_time', 'N/A')} - {historical_data.get('end_time', 'N/A')}</td>
                            <td>{total_hours:.1f}</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td>${avg_hourly:.4f}</td>
                            <td class="status-active">Stable</td>
                        </tr>
                        '''

                    # EKS Historical Data
                    eks_clusters = region_data.get('eks_clusters', [])
                    if eks_clusters:
                        total_hours = sum(c.get('running_hours', 0) for c in eks_clusters)
                        total_cost = sum(c.get('total_cost', 0) for c in eks_clusters)
                        avg_hourly = total_cost / total_hours if total_hours > 0 else 0

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🚢 EKS</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(eks_clusters)}</td>
                            <td>{historical_data.get('start_time', 'N/A')} - {historical_data.get('end_time', 'N/A')}</td>
                            <td>{total_hours:.1f}</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td>${avg_hourly:.4f}</td>
                            <td class="status-active">Stable</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>📊 <strong>Historical Analysis:</strong> Costs calculated based on actual running time during the last 9 hours.</small>
                </div>
            </div>
            '''

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Forecast Analysis Table
        if aggregated_results.get('forecast_analysis', {}).get('accounts'):
            html += f'''
            <div class="table-container">
                <div class="table-header">🔮 Cost Forecast Analysis (Next 9 Hours) - Generated: {now_str} by varadharajaan</div>
                <table>
                    <thead>
                        <tr>
                            <th>Account</th>
                            <th>Service</th>
                            <th>Region</th>
                            <th>Resource Count</th>
                            <th>Forecast Period</th>
                            <th>Forecast Hours</th>
                            <th>Forecast Cost</th>
                            <th>Confidence Level</th>
                            <th>Assumptions</th>
                        </tr>
                    </thead>
                    <tbody>
            '''

            for account_id, forecast_data in aggregated_results['forecast_analysis']['accounts'].items():
                account_name = self.account_id_to_name.get(account_id, "Unknown")

                # EC2 Forecast Data
                for region, region_data in forecast_data.get('regions', {}).items():
                    ec2_forecast = region_data.get('ec2_forecast', [])
                    if ec2_forecast:
                        total_cost = sum(i.get('forecast_cost', 0) for i in ec2_forecast)

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🖥️ EC2</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(ec2_forecast)}</td>
                            <td>{forecast_data.get('start_time', 'N/A')} - {forecast_data.get('end_time', 'N/A')}</td>
                            <td>9.0</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td class="status-active">85%</td>
                            <td>Current configuration maintained</td>
                        </tr>
                        '''

                    # EKS Forecast Data
                    eks_forecast = region_data.get('eks_forecast', [])
                    if eks_forecast:
                        total_cost = sum(c.get('total_forecast', 0) for c in eks_forecast)

                        html += f'''
                        <tr>
                            <td><strong>{account_name}</strong><br><small>{account_id}</small></td>
                            <td>🚢 EKS</td>
                            <td><span class="metric-badge">{region}</span></td>
                            <td>{len(eks_forecast)}</td>
                            <td>{forecast_data.get('start_time', 'N/A')} - {forecast_data.get('end_time', 'N/A')}</td>
                            <td>9.0</td>
                            <td class="cost-highlight">${total_cost:.2f}</td>
                            <td class="status-active">85%</td>
                            <td>Current scaling maintained</td>
                        </tr>
                        '''

            html += '''
                    </tbody>
                </table>
                <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                    <small>🔮 <strong>Forecast Assumptions:</strong> Based on current resource configuration and historical usage patterns. Confidence levels may vary based on workload stability.</small>
                </div>
            </div>
            '''

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Cost Optimization Recommendations Table
        html += f'''
        <div class="table-container">
            <div class="table-header">💡 Cost Optimization Recommendations - Generated: {now_str} by varadharajaan</div>
            <table>
                <thead>
                    <tr>
                        <th>Priority</th>
                        <th>Resource Type</th>
                        <th>Recommendation</th>
                        <th>Potential Savings</th>
                        <th>Effort</th>
                        <th>Impact</th>
                        <th>Implementation</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><span class="status-error">🔴 High</span></td>
                        <td>🖥️ EC2</td>
                        <td>Review underutilized instances (CPU < 20%)</td>
                        <td class="cost-highlight">$50-200/month</td>
                        <td>Low</td>
                        <td>High</td>
                        <td>Right-size or terminate unused instances</td>
                    </tr>
                    <tr>
                        <td><span class="status-warning">🟡 Medium</span></td>
                        <td>🚢 EKS</td>
                        <td>Implement cluster autoscaling</td>
                        <td class="cost-highlight">$30-100/month</td>
                        <td>Medium</td>
                        <td>Medium</td>
                        <td>Configure HPA and VPA</td>
                    </tr>
                    <tr>
                        <td><span class="status-active">🟢 Low</span></td>
                        <td>🌍 Multi-Region</td>
                        <td>Consider Reserved Instances for consistent workloads</td>
                        <td class="cost-highlight">$100-500/month</td>
                        <td>Low</td>
                        <td>High</td>
                        <td>Purchase 1-year or 3-year RIs</td>
                    </tr>
                    <tr>
                        <td><span class="status-warning">🟡 Medium</span></td>
                        <td>💾 Storage</td>
                        <td>Review EBS volumes and snapshots</td>
                        <td class="cost-highlight">$20-80/month</td>
                        <td>Low</td>
                        <td>Medium</td>
                        <td>Delete unused volumes and old snapshots</td>
                    </tr>
                </tbody>
            </table>
            <div style="padding: 15px; background: #f8f9fa; border-top: 1px solid #e9ecef;">
                <small>💡 <strong>Optimization Tips:</strong> Regularly review your cost reports and implement cost optimization strategies. Consider using AWS Cost Explorer and Trusted Advisor for additional insights.</small>
            </div>
        </div>
        '''

        html += '</div>'
        return html


def main():
    """Main entry point"""
    try:
        calculator = LiveCostCalculator()
        calculator.run()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()