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
from botocore.exceptions import ClientError, BotoCoreError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Set, Optional, Tuple

class LiveCostCalculator:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now()
        self.current_time_str = self.current_time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = os.environ.get('USER', 'unknown')
        
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
            end_time = datetime.utcnow()
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
                        
                        self.logger.info(f"Calculated cost for instance {instance_id} ({instance_type}): ${estimated_cost} for {round(uptime_hours, 2)} hours")
                
            except Exception as e:
                self.logger.error(f"Error getting EC2 instances in {region}: {e}")
            
            # Update region and total results
            results["regions"][region] = region_results
            results["total_cost"] += region_results["total_cost"]
            results["instance_count"] += region_results["instance_count"]
        
        # Save results to file
        output_file = f"{self.ec2_output_dir}/ec2_cost_{account_selection}_{self.execution_timestamp}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        self.logger.info(f"EC2 cost calculation saved to: {output_file}")
        self.logger.info(f"Total EC2 cost: ${results['total_cost']:.2f} for {results['instance_count']} instances")
        
        return results

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
        """Calculate costs for EKS clusters"""
        self.logger.info(f"Calculating EKS costs for account {account_selection} in regions: {region_selection}")
        
        results = {
            "account_id": account_selection,
            "account_name": self.account_id_to_name.get(account_selection, "Unknown"),
            "regions": {},
            "total_cost": 0.0,
            "currency": "USD",
            "calculated_at": self.current_time_str,
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
        
        # Process each region
        for region in region_selection:
            self.logger.info(f"Processing region: {region}")
            
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
                clusters = []
                
                if eks_selection and eks_selection != 'all':
                    # Get specific clusters
                    cluster_names = eks_selection if isinstance(eks_selection, list) else [eks_selection]
                    for cluster_name in cluster_names:
                        try:
                            cluster_info = eks_client.describe_cluster(name=cluster_name)
                            clusters.append(cluster_info['cluster'])
                        except Exception as e:
                            self.logger.error(f"Error getting cluster {cluster_name}: {e}")
                else:
                    # Get all clusters
                    response = eks_client.list_clusters()
                    for cluster_name in response.get('clusters', []):
                        try:
                            cluster_info = eks_client.describe_cluster(name=cluster_name)
                            clusters.append(cluster_info['cluster'])
                        except Exception as e:
                            self.logger.error(f"Error getting cluster {cluster_name}: {e}")
                
                # Process each cluster
                for cluster in clusters:
                    cluster_name = cluster['name']
                    cluster_arn = cluster['arn']
                    created_at = cluster['createdAt']
                    status = cluster['status']
                    version = cluster['version']
                    
                    self.logger.info(f"Processing EKS cluster: {cluster_name} ({status})")
                    
                    # Skip clusters that aren't active
                    if status != 'ACTIVE':
                        self.logger.info(f"Skipping cluster {cluster_name} with status: {status}")
                        continue
                    
                    # Calculate control plane uptime
                    uptime_hours = (self.current_time - created_at.replace(tzinfo=None)).total_seconds() / 3600
                    
                    # Calculate control plane cost
                    control_plane_cost = round(uptime_hours * control_plane_hourly, 2)
                    
                    # Initialize cluster costs
                    cluster_cost = {
                        "cluster_name": cluster_name,
                        "status": status,
                        "version": version,
                        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "uptime_hours": round(uptime_hours, 2),
                        "control_plane": {
                            "hourly_rate": control_plane_hourly,
                            "cost": control_plane_cost
                        },
                        "nodegroups": [],
                        "total_cost": control_plane_cost
                    }
                    
                    # Get nodegroups
                    try:
                        nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                        
                        for nodegroup_name in nodegroups_response.get('nodegroups', []):
                            try:
                                nodegroup_info = eks_client.describe_nodegroup(
                                    clusterName=cluster_name,
                                    nodegroupName=nodegroup_name
                                )['nodegroup']
                                
                                # Get nodegroup details
                                ng_status = nodegroup_info['status']
                                ng_created_at = nodegroup_info['createdAt']
                                ng_instance_types = nodegroup_info.get('instanceTypes', [])
                                ng_desired_size = nodegroup_info['scalingConfig']['desiredSize']
                                
                                # Calculate nodegroup uptime
                                ng_uptime_hours = (self.current_time - ng_created_at.replace(tzinfo=None)).total_seconds() / 3600
                                
                                # Find EC2 instances for this nodegroup
                                instance_ids = []
                                
                                # Try to find instances using the EKS API
                                if 'resources' in nodegroup_info and 'autoScalingGroups' in nodegroup_info['resources']:
                                    for asg in nodegroup_info['resources']['autoScalingGroups']:
                                        asg_name = asg.get('name')
                                        if asg_name:
                                            # Get ASG details to find instances
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
                                                    instance_ids.append(instance['InstanceId'])
                                
                                # If no instances found through ASGs, try with EC2 tags
                                if not instance_ids:
                                    # Describe EC2 instances with EKS cluster and nodegroup tags
                                    ec2_response = ec2_client.describe_instances(
                                        Filters=[
                                            {
                                                'Name': 'tag:eks:cluster-name',
                                                'Values': [cluster_name]
                                            },
                                            {
                                                'Name': 'tag:eks:nodegroup-name',
                                                'Values': [nodegroup_name]
                                            }
                                        ]
                                    )
                                    
                                    for reservation in ec2_response.get('Reservations', []):
                                        for instance in reservation.get('Instances', []):
                                            if instance['State']['Name'] == 'running':
                                                instance_ids.append(instance['InstanceId'])
                                
                                # Get detailed instance information
                                nodes_info = self.get_eks_node_info(ec2_client, instance_ids) if instance_ids else {}
                                
                                # Calculate nodegroup cost
                                nodegroup_cost = 0.0
                                node_details = []
                                
                                if nodes_info:
                                    for instance_id, node_info in nodes_info.items():
                                        instance_type = node_info['instance_type']
                                        uptime = node_info['uptime_hours']
                                        hourly_rate = ec2_pricing.get(instance_type, 0.0)
                                        cost = round(uptime * hourly_rate, 2)
                                        
                                        nodegroup_cost += cost
                                        
                                        node_details.append({
                                            "instance_id": instance_id,
                                            "instance_type": instance_type,
                                            "node_name": node_info['node_name'],
                                            "uptime_hours": uptime,
                                            "hourly_rate": hourly_rate,
                                            "cost": cost
                                        })
                                else:
                                    # Estimate cost based on desired size and instance types
                                    for instance_type in ng_instance_types:
                                        hourly_rate = ec2_pricing.get(instance_type, 0.0)
                                        estimated_cost = round(ng_uptime_hours * hourly_rate * ng_desired_size / len(ng_instance_types), 2)
                                        
                                        nodegroup_cost += estimated_cost
                                        
                                        node_details.append({
                                            "instance_type": instance_type,
                                            "count": f"{ng_desired_size}/{len(ng_instance_types)} (estimated)",
                                            "uptime_hours": ng_uptime_hours,
                                            "hourly_rate": hourly_rate,
                                            "estimated_cost": estimated_cost
                                        })
                                
                                # Add nodegroup to cluster cost
                                nodegroup_entry = {
                                    "nodegroup_name": nodegroup_name,
                                    "status": ng_status,
                                    "created_at": ng_created_at.strftime("%Y-%m-%d %H:%M:%S"),
                                    "instance_types": ng_instance_types,
                                    "desired_size": ng_desired_size,
                                    "nodes": node_details,
                                    "cost": nodegroup_cost
                                }
                                
                                cluster_cost["nodegroups"].append(nodegroup_entry)
                                cluster_cost["total_cost"] += nodegroup_cost
                                
                            except Exception as e:
                                self.logger.error(f"Error processing nodegroup {nodegroup_name}: {e}")
                    except Exception as e:
                        self.logger.error(f"Error listing nodegroups for cluster {cluster_name}: {e}")
                    
                    # Add cluster to region results
                    region_results["clusters"].append(cluster_cost)
                    region_results["total_cost"] += cluster_cost["total_cost"]
                    region_results["cluster_count"] += 1
            except Exception as e:
                self.logger.error(f"Error listing EKS clusters in {region}: {e}")
            
            # Update region and total results
            results["regions"][region] = region_results
            results["total_cost"] += region_results["total_cost"]
            results["cluster_count"] += region_results["cluster_count"]
        
        # Save results to file
        output_file = f"{self.eks_output_dir}/eks_cost_{account_selection}_{self.execution_timestamp}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        self.logger.info(f"EKS cost calculation saved to: {output_file}")
        self.logger.info(f"Total EKS cost: ${results['total_cost']:.2f} for {results['cluster_count']} clusters")
        
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
        """Display active EC2 instances and EKS clusters"""
    
        print("\n" + "=" * 80)
        print(f"🔍 ACTIVE RESOURCES IN ACCOUNT: {account_id} ({account_name})")
        print("=" * 80)
    
        has_active_resources = False
    
        # Display EC2 instances
        all_instances = []
        for region in regions:
            instances = self.list_active_ec2_instances(access_key, secret_key, region)
            if instances:
                for instance in instances:
                    instance['region'] = region
                all_instances.extend(instances)
    
        if all_instances:
            has_active_resources = True
            print("\n🖥️  ACTIVE EC2 INSTANCES:")
            print(f"   {'Instance ID':<20} {'Name':<30} {'Type':<15} {'Region':<12} {'Launch Time'}")
            print("   " + "-" * 90)
        
            for instance in all_instances:
                print(f"   {instance['instance_id']:<20} {instance['instance_name'][:28]:<30} "
                      f"{instance['instance_type']:<15} {instance['region']:<12} {instance['launch_time']}")
        
            print(f"\n   Total: {len(all_instances)} active EC2 instances")
        else:
            print("\n🖥️  No active EC2 instances found in selected regions.")
    
        # Display EKS clusters
        all_clusters = []
        for region in regions:
            clusters = self.list_active_eks_clusters(access_key, secret_key, region)
            if clusters:
                for cluster in clusters:
                    cluster['region'] = region
                all_clusters.extend(clusters)
    
        if all_clusters:
            has_active_resources = True
            print("\n🚢 ACTIVE EKS CLUSTERS:")
            print(f"   {'Cluster Name':<30} {'Version':<10} {'Region':<12} {'Nodegroups':<10} {'Created At'}")
            print("   " + "-" * 90)
        
            for cluster in all_clusters:
                print(f"   {cluster['cluster_name'][:28]:<30} {cluster['version']:<10} "
                      f"{cluster['region']:<12} {cluster['nodegroups_count']:<10} {cluster['created_at']}")
        
            print(f"\n   Total: {len(all_clusters)} active EKS clusters")
        else:
            print("\n🚢 No active EKS clusters found in selected regions.")
    
        if not has_active_resources:
            print("\n⚠️  No active EC2 instances or EKS clusters found in selected regions.")
    
        print("\n" + "=" * 80)
    
        # Return summary for further use
        return {
            "ec2_instances": all_instances,
            "eks_clusters": all_clusters
        }

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
                selected_account_ids = [accounts[i-1][0] for i in account_indices]
            
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
    
        # Step 4: Calculate costs and display results for each account
        print("\n🧮 CALCULATING COSTS...")
    
        # Containers to store results for all accounts
        all_ec2_results = {}
        all_eks_results = {}
    
        # Calculate for each selected account
        for account_id in selected_account_ids:
            account_name = self.account_id_to_name.get(account_id, "Unknown")
            print(f"\n📊 Processing account: {account_name} ({account_id})")
        
            if calculate_ec2:
                print(f"  Calculating EC2 costs...")
                ec2_results = self.calculate_ec2_costs(account_id, selected_regions, ec2_selection)
                all_ec2_results[account_id] = ec2_results
        
            if calculate_eks:
                print(f"  Calculating EKS costs...")
                eks_results = self.calculate_eks_costs(account_id, selected_regions, eks_selection)
                all_eks_results[account_id] = eks_results
    
        # Step 5: Aggregate and display final summary
        print("\n" + "=" * 80)
        print("💵 AGGREGATED COST SUMMARY")
        print("=" * 80)
    
        # Calculate totals
        total_ec2_cost = sum(result['total_cost'] for result in all_ec2_results.values()) if all_ec2_results else 0
        total_ec2_instances = sum(result['instance_count'] for result in all_ec2_results.values()) if all_ec2_results else 0
    
        total_eks_cost = sum(result['total_cost'] for result in all_eks_results.values()) if all_eks_results else 0
        total_eks_clusters = sum(result['cluster_count'] for result in all_eks_results.values()) if all_eks_results else 0
    
        total_cost = total_ec2_cost + total_eks_cost
    
        print(f"📈 TOTAL ESTIMATED COST ACROSS ALL ACCOUNTS: ${total_cost:.2f} USD")
        print(f"  • Total accounts processed: {len(selected_account_ids)}")
    
        if calculate_ec2:
            print(f"  • EC2: ${total_ec2_cost:.2f} ({total_ec2_instances} instances)")
    
        if calculate_eks:
            print(f"  • EKS: ${total_eks_cost:.2f} ({total_eks_clusters} clusters)")
    
        # Per-account breakdown
        print("\n📊 COST BREAKDOWN BY ACCOUNT:")
    
        for account_id in selected_account_ids:
            account_name = self.account_id_to_name.get(account_id, "Unknown")
            account_ec2_cost = all_ec2_results.get(account_id, {}).get('total_cost', 0)
            account_eks_cost = all_eks_results.get(account_id, {}).get('total_cost', 0)
            account_total = account_ec2_cost + account_eks_cost
        
            print(f"  • {account_name} ({account_id}): ${account_total:.2f}")
            if calculate_ec2 and account_id in all_ec2_results:
                instances = all_ec2_results[account_id]['instance_count']
                print(f"      EC2: ${account_ec2_cost:.2f} ({instances} instances)")
        
            if calculate_eks and account_id in all_eks_results:
                clusters = all_eks_results[account_id]['cluster_count']
                print(f"      EKS: ${account_eks_cost:.2f} ({clusters} clusters)")
    
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
            } if calculate_eks else {}
        }
    
        # Save aggregated results
        aggregated_output_file = f"aws/live-cost/cost_summary_{self.execution_timestamp}.json"
        os.makedirs("aws/live-cost", exist_ok=True)
        with open(aggregated_output_file, 'w') as f:
            json.dump(aggregated_results, f, indent=2, default=str)
    
        # Output file locations
        print("\n📄 OUTPUT FILES:")
        print(f"   Aggregated Cost Report: {aggregated_output_file}")
    
        # Show individual file locations
        for account_id in selected_account_ids:
            if calculate_ec2 and account_id in all_ec2_results:
                print(f"   EC2 Cost Report ({account_id}): {self.ec2_output_dir}/ec2_cost_{account_id}_{self.execution_timestamp}.json")
        
            if calculate_eks and account_id in all_eks_results:
                print(f"   EKS Cost Report ({account_id}): {self.eks_output_dir}/eks_cost_{account_id}_{self.execution_timestamp}.json")
    
        print(f"   Log File: {self.log_filename}")
    
        print("\n✅ Cost calculation complete!\n") 

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