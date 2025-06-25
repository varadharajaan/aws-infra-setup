"""
Auto Scaling Group Manager - Enhanced with Multiple Strategies
Handles ASG creation with On-Demand, Spot, and Mixed strategies
"""

import json
import os
import re
import stat
from turtle import st
import boto3
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from botocore import regions
from aws_credential_manager import CredentialInfo
from spot_instance_analyzer import SpotInstanceAnalyzer, SpotAnalysis, ServiceQuotaInfo
import random
import string

@dataclass
class ASGConfig:
    name: str
    launch_template_id: str
    launch_template_version: str
    min_size: int
    max_size: int
    desired_capacity: int
    availability_zones: List[str]
    region: str
    strategy: str  # 'on-demand', 'spot', 'mixed'
    instance_types: List[str]
    spot_allocation_strategy: Optional[str] = None
    on_demand_percentage: Optional[int] = None

class AutoScalingGroupManager:
    def __init__(self, current_user='varadharajaan', current_time='2025-06-13 05:13:24'):
        self.current_user = current_user
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_time = current_timestamp
        self.spot_analyzer = SpotInstanceAnalyzer()

    @staticmethod
    def generate_random_suffix(length=4):
        """Generate a random alphanumeric suffix of specified length"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def generate_asg_report(self, cred_info, asg_details, instance_selections, execution_timestamp=None):
        """
        Generate a comprehensive report for ASG creation
        """
        if execution_timestamp is None:
            execution_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
        creation_date = datetime.now().strftime('%Y-%m-%d')
        creation_time = datetime.now().strftime('%H:%M:%S')
    
        # Extract details from the ASG creation process
        asg_name = asg_details.get('asg_name', 'Unknown')
        strategy = asg_details.get('strategy', 'Unknown')
        region = asg_details.get('region', 'Unknown')
        instance_types = asg_details.get('instance_types', [])
        launch_template_id = asg_details.get('launch_template_id', 'Unknown')
        min_size = asg_details.get('min_size', 0)
        max_size = asg_details.get('max_size', 0)
        desired_capacity = asg_details.get('desired_capacity', 0)
        spot_allocation_strategy = asg_details.get('spot_allocation_strategy', None)
        on_demand_percentage = asg_details.get('on_demand_percentage', None)
    
        # Get account details
        account_name = cred_info.account_name
        account_id = cred_info.account_id
        email = cred_info.email
    
        # Structure the report
        report = {
            "metadata": {
                "creation_date": creation_date,
                "creation_time": creation_time,
                "created_by": self.current_user,
                "execution_timestamp": execution_timestamp,
                "strategy": strategy,
                "launch_template_id": launch_template_id
            },
            "summary": {
                "total_created": 1,
                "total_failed": 0,
                "success_rate": "100.0%",
                "accounts_processed": 1,
                "regions_used": [region]
            },
            "created_asgs": [
                {
                    "asg_name": asg_name,
                    "region": region,
                    "strategy": strategy,
                    "instance_types": instance_types,
                    "launch_template_id": launch_template_id,
                    "min_size": min_size,
                    "max_size": max_size,
                    "desired_capacity": desired_capacity,
                    "account_name": account_name,
                    "account_id": account_id,
                    "account_email": email,
                    "created_at": self.current_time,
                    "spot_allocation_strategy": spot_allocation_strategy,
                    "on_demand_percentage": on_demand_percentage,
                    "vpc_id": asg_details.get('vpc_id', 'To be populated'),
                    "subnets": asg_details.get('subnets', 'To be populated')
                }
            ],
            "failed_asgs": [],
            "statistics": {
                "by_region": {
                    region: 1
                },
                "by_account": {
                    account_name: 1
                },
                "by_strategy": {
                    strategy: 1
                },
                "by_instance_types": {
                    instance_type: 1 for instance_type in instance_types
                }
            }
        }
    
        # Create output directory
        output_dir = f"aws/asg/{cred_info.account_name}"
        os.makedirs(output_dir, exist_ok=True)
    
        # Save to JSON file
        filename = f"{output_dir}/asg_report_{execution_timestamp}.json"
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
    
        print(f"📊 ASG report saved to: {filename}")
        return report

    def create_asg_scaling_policies(self, asg_name, cred_info):
        """
        Creates and attaches scaling policies and alarms to an Auto Scaling Group.
        """
        autoscaling_client = boto3.client(
            'autoscaling',
            aws_access_key_id=cred_info.access_key,
            aws_secret_access_key=cred_info.secret_key,
            region_name=cred_info.regions[0]
        )
        cloudwatch_client = boto3.client(
            'cloudwatch',
            aws_access_key_id=cred_info.access_key,
            aws_secret_access_key=cred_info.secret_key,
            region_name=cred_info.regions[0]
        )
        try:
            # Scale Up Policy
            scale_up_response = autoscaling_client.put_scaling_policy(
                AutoScalingGroupName=asg_name,
                PolicyName=f'{asg_name}-scale-up-policy',
                PolicyType='SimpleScaling',
                AdjustmentType='ChangeInCapacity',
                ScalingAdjustment=1,
                Cooldown=120
            )
            scale_up_policy_arn = scale_up_response['PolicyARN']

            # Scale Down Policy
            scale_down_response = autoscaling_client.put_scaling_policy(
                AutoScalingGroupName=asg_name,
                PolicyName=f'{asg_name}-scale-down-policy',
                PolicyType='SimpleScaling',
                AdjustmentType='ChangeInCapacity',
                ScalingAdjustment=-1,
                Cooldown=120
            )
            scale_down_policy_arn = scale_down_response['PolicyARN']

            # High CPU Alarm
            cloudwatch_client.put_metric_alarm(
                AlarmName=f'{asg_name}-high-cpu-alarm',
                ComparisonOperator='GreaterThanThreshold',
                EvaluationPeriods=2,
                MetricName='CPUUtilization',
                Namespace='AWS/EC2',
                Period=60,
                Statistic='Average',
                Threshold=70.0,
                ActionsEnabled=True,
                AlarmActions=[scale_up_policy_arn],
                AlarmDescription='Alarm when server CPU exceeds 70%',
                Dimensions=[{'Name': 'AutoScalingGroupName', 'Value': asg_name}],
                Unit='Percent'
            )

            # Low CPU Alarm
            cloudwatch_client.put_metric_alarm(
                AlarmName=f'{asg_name}-low-cpu-alarm',
                ComparisonOperator='LessThanThreshold',
                EvaluationPeriods=2,
                MetricName='CPUUtilization',
                Namespace='AWS/EC2',
                Period=60,
                Statistic='Average',
                Threshold=20.0,
                ActionsEnabled=True,
                AlarmActions=[scale_down_policy_arn],
                AlarmDescription='Alarm when server CPU is below 20%',
                Dimensions=[{'Name': 'AutoScalingGroupName', 'Value': asg_name}],
                Unit='Percent'
            )

            self.log_operation('INFO', f"Scaling policies and alarms created for ASG: {asg_name}")
            return {
                'scale_up_policy_arn': scale_up_policy_arn,
                'scale_down_policy_arn': scale_down_policy_arn,
                'high_cpu_alarm': f'{asg_name}-high-cpu-alarm',
                'low_cpu_alarm': f'{asg_name}-low-cpu-alarm',
                'status': 'success'
            }
        except Exception as e:
            self.log_operation('ERROR', f"Error creating scaling policies: {str(e)}")
            return {'status': 'error', 'error_message': str(e)}

    def create_ondemand_asg(self, asg_client, asg_config: ASGConfig, cred_info: CredentialInfo, schedule_scaling: bool = True) -> Dict:
        """Create On-Demand ASG"""
        try:
            print(f"🏗️ Creating On-Demand Auto Scaling Group...")
            
            # Get subnets for availability zones
            subnets = self._get_subnets_for_azs(asg_config.availability_zones, asg_config.region, cred_info)
            
            # Create ASG with On-Demand instances only
            response = asg_client.create_auto_scaling_group(
                AutoScalingGroupName=asg_config.name,
                LaunchTemplate={
                    'LaunchTemplateId': asg_config.launch_template_id,
                    'Version': asg_config.launch_template_version
                },
                MinSize=asg_config.min_size,
                MaxSize=asg_config.max_size,
                DesiredCapacity=asg_config.desired_capacity,
                VPCZoneIdentifier=','.join(subnets),
                HealthCheckType='EC2',
                HealthCheckGracePeriod=300,
                DefaultCooldown=300,
                Tags=[
                    {
                        'Key': 'Name',
                        'Value': asg_config.name,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'Strategy',
                        'Value': 'OnDemand',
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'CreatedBy',
                        'Value': self.current_user,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'CreatedAt',
                        'Value': self.current_time,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    }
                ]
            )
            
            print(f"✅ On-Demand ASG created successfully")
            # Attach scheduled scaling actions if requested
            if schedule_scaling:
                self.attach_scheduled_actions(asg_client, asg_config.name, asg_config.region)
                print(f"✅ On-Demand ASG created successfully with scheduled scaling")
            return response
            
        except Exception as e:
            print(f"❌ Error creating On-Demand ASG: {e}")
            raise
    
    def create_spot_asg(self, asg_client, asg_config: ASGConfig, cred_info: CredentialInfo, schedule_scaling: bool = True) -> Dict:
        """Create Spot ASG"""
        try:
            print(f"📈 Creating Spot Auto Scaling Group...")
            
            # Get subnets for availability zones
            subnets = self._get_subnets_for_azs(asg_config.availability_zones, asg_config.region, cred_info)
                        # Determine the spot allocation strategy
            spot_allocation_strategy = asg_config.spot_allocation_strategy or 'capacity-optimized'

            # Build InstancesDistribution dict step by step
            instances_distribution = {
                'OnDemandPercentageAboveBaseCapacity': 0,  # 100% Spot
                'OnDemandAllocationStrategy': 'prioritized',
                'SpotAllocationStrategy': spot_allocation_strategy,
                'SpotMaxPrice': ''  # Use current spot price
            }
            # Only add SpotInstancePools if using 'lowest-price'
            if spot_allocation_strategy == 'lowest-price':
                instances_distribution['SpotInstancePools'] = min(len(asg_config.instance_types), 20)

            # Now use instances_distribution in your policy:
            mixed_instances_policy = {
                'LaunchTemplate': {
                    'LaunchTemplateSpecification': {
                        'LaunchTemplateId': asg_config.launch_template_id,
                        'Version': asg_config.launch_template_version
                    },
                    'Overrides': [
                        {
                            'InstanceType': instance_type,
                            'WeightedCapacity': '1'
                        } for instance_type in asg_config.instance_types
                    ]
                },
                'InstancesDistribution': instances_distribution
            }

            # Create ASG with Spot instances
            response = asg_client.create_auto_scaling_group(
                AutoScalingGroupName=asg_config.name,
                MixedInstancesPolicy=mixed_instances_policy,
                MinSize=asg_config.min_size,
                MaxSize=asg_config.max_size,
                DesiredCapacity=asg_config.desired_capacity,
                VPCZoneIdentifier=','.join(subnets),
                HealthCheckType='EC2',
                HealthCheckGracePeriod=300,
                DefaultCooldown=300,
                Tags=[
                    {
                        'Key': 'Name',
                        'Value': asg_config.name,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'Strategy',
                        'Value': 'Spot',
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'SpotAllocationStrategy',
                        'Value': asg_config.spot_allocation_strategy or 'diversified',
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'CreatedBy',
                        'Value': self.current_user,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'CreatedAt',
                        'Value': self.current_time,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    }
                ]
            )
            
            print(f"✅ Spot ASG created successfully")
            # Attach scheduled scaling actions if requested
            schedule_scaling = True  # This should be passed as a parameter or class attribute
            if schedule_scaling:
                self.attach_scheduled_actions(asg_client, asg_config.name, asg_config.region)
                print(f"✅ Spot ASG created successfully with scheduled scaling")
            return response
            
        except Exception as e:
            print(f"❌ Error creating Spot ASG: {e}")
            raise
    
    def create_mixed_asg(self, asg_client, asg_config: ASGConfig, instance_selections: Dict, cred_info: CredentialInfo, schedule_scaling: bool = True) -> Dict:
        """Create Mixed ASG with configurable On-Demand/Spot ratio"""
        try:
            on_demand_percentage = instance_selections.get('on_demand_percentage', 50)
            print(f"🔄 Creating Mixed ASG ({on_demand_percentage}% On-Demand, {100-on_demand_percentage}% Spot)...")
            
            # Get subnets for availability zones
            subnets = self._get_subnets_for_azs(asg_config.availability_zones, asg_config.region, cred_info)
            
            # Combine all instance types from both on-demand and spot selections
            all_instance_types = []
            if 'on-demand' in instance_selections:
                all_instance_types.extend(instance_selections['on-demand'])
            if 'spot' in instance_selections:
                all_instance_types.extend(instance_selections['spot'])
            
            # Remove duplicates while preserving order (on-demand types first for priority)
            unique_instance_types = []
            seen = set()
            for instance_type in all_instance_types:
                if instance_type not in seen:
                    unique_instance_types.append(instance_type)
                    seen.add(instance_type)

            # Determine spot allocation strategy
            spot_allocation_strategy = asg_config.spot_allocation_strategy or 'capacity-optimized'

            # Build instances distribution
            instances_distribution = {
                'OnDemandPercentageAboveBaseCapacity': on_demand_percentage,
                'OnDemandAllocationStrategy': 'prioritized',
                'SpotAllocationStrategy': spot_allocation_strategy,
                'SpotMaxPrice': ''
            }

            # Only add SpotInstancePools if using lowest-price
            if spot_allocation_strategy == 'lowest-price':
                instances_distribution['SpotInstancePools'] = min(len(unique_instance_types), 20)
            
            # Create mixed instances policy
            mixed_instances_policy = {
                'LaunchTemplate': {
                    'LaunchTemplateSpecification': {
                        'LaunchTemplateId': asg_config.launch_template_id,
                        'Version': asg_config.launch_template_version
                    },
                    'Overrides': [
                        {
                            'InstanceType': instance_type,
                            'WeightedCapacity': '1'
                        } for instance_type in unique_instance_types
                    ]
                },
                'InstancesDistribution': instances_distribution
            }
            
            # Create ASG with Mixed instances
            response = asg_client.create_auto_scaling_group(
                AutoScalingGroupName=asg_config.name,
                MixedInstancesPolicy=mixed_instances_policy,
                MinSize=asg_config.min_size,
                MaxSize=asg_config.max_size,
                DesiredCapacity=asg_config.desired_capacity,
                VPCZoneIdentifier=','.join(subnets),
                HealthCheckType='EC2',
                HealthCheckGracePeriod=300,
                DefaultCooldown=300,
                Tags=[
                    {
                        'Key': 'Name',
                        'Value': asg_config.name,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'Strategy',
                        'Value': 'Mixed',
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'OnDemandPercentage',
                        'Value': str(on_demand_percentage),
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'SpotPercentage',
                        'Value': str(100 - on_demand_percentage),
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'CreatedBy',
                        'Value': self.current_user,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    },
                    {
                        'Key': 'CreatedAt',
                        'Value': self.current_time,
                        'PropagateAtLaunch': True,
                        'ResourceId': asg_config.name,
                        'ResourceType': 'auto-scaling-group'
                    }
                ]
            )
            
            print(f"✅ Mixed ASG created successfully")
            # Attach scheduled scaling actions if requested
            schedule_scaling = True  # This should be passed as a parameter or class attribute
            if schedule_scaling:
                self.attach_scheduled_actions(asg_client, asg_config.name, asg_config.region)
            print(f"✅ Mixed ASG created successfully with scheduled scaling")
            return response
            
        except Exception as e:
            print(f"❌ Error creating Mixed ASG: {e}")
            raise
    
    def _get_subnets_for_azs(self, availability_zones: List[str], region: str, cred_info: CredentialInfo) -> List[str]:
        """Get default subnet IDs for the given availability zones, filtering out unsupported AZs"""
        try:
            # Use the credentials from the current context
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )  # Will use default credentials

            # Get current region from the client
            region = ec2_client.meta.region_name

            # Filter out unsupported AZs
            unsupported_azs = self._get_unsupported_azs(region)
            supported_azs = [az for az in availability_zones if az not in unsupported_azs]
            if not supported_azs:
                print("⚠️ No supported availability zones after filtering unsupported AZs.")
                return []

            # Get default VPC
            vpcs_response = ec2_client.describe_vpcs(
                Filters=[{'Name': 'is-default', 'Values': ['true']}]
            )

            if not vpcs_response['Vpcs']:
                raise ValueError("No default VPC found")

            default_vpc_id = vpcs_response['Vpcs'][0]['VpcId']

            # Get subnets in the default VPC for supported AZs
            subnets_response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [default_vpc_id]},
                    {'Name': 'availability-zone', 'Values': supported_azs}
                ]
            )

            subnet_ids = [subnet['SubnetId'] for subnet in subnets_response['Subnets']]

            if not subnet_ids:
                # If no subnets found in specified AZs, get all subnets in default VPC
                all_subnets = ec2_client.describe_subnets(
                    Filters=[{'Name': 'vpc-id', 'Values': [default_vpc_id]}]
                )
                subnet_ids = [subnet['SubnetId'] for subnet in all_subnets['Subnets']]

            print(f"   🌐 Using subnets: {', '.join(subnet_ids)}")
            print(f"DEBUG: availability_zones: {availability_zones}")
            print(f"DEBUG: supported_azs: {supported_azs}")
            print(f"DEBUG: default_vpc_id: {default_vpc_id}")
            return subnet_ids

        except Exception as e:
            print(f"⚠️ Error getting subnets: {e}")
            # Return empty list - ASG creation will use default subnets
            return []
    
    def prompt_asg_strategy(self) -> str:
        """Prompt user to select ASG strategy"""
        print("\n" + "="*70)
        print("🚀 AUTO SCALING GROUP STRATEGY SELECTION")
        print("="*70)
        print("Choose your ASG strategy:")
        print("1. On-Demand Only (Reliable, Higher Cost)")
        print("2. Spot Only (Cost-Effective, Higher Risk)")
        print("3. Mixed Strategy (50/50 default, Balanced)")
        print("="*70)
        
        while True:
            choice = input("Enter your choice (1-3): ").strip()
            if choice == '1':
                return 'on-demand'
            elif choice == '2':
                return 'spot'
            elif choice == '3':
                return 'mixed'
            else:
                print("❌ Invalid choice. Please enter 1, 2, or 3.")
    
    def select_instance_types_for_strategy(self, cred_info: CredentialInfo, 
                                         strategy: str, allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types based on strategy"""
        if strategy == 'on-demand':
            return self.select_ondemand_instance_types(cred_info, allowed_types)
        elif strategy == 'spot':
            return self.select_spot_instance_types(cred_info, allowed_types)
        else:  # mixed
            return self.select_mixed_instance_types(cred_info, allowed_types)
    
    def select_ondemand_instance_types(self, cred_info: CredentialInfo, 
                                 allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for On-Demand strategy"""
        print("\n" + "="*60)
        print("💰 ON-DEMAND INSTANCE TYPE SELECTION")
        print("="*60)
        print("Analyzing service quotas for On-Demand instances...")
    
        # Use the spot_analyzer that's already initialized in the class
        quota_info = self.spot_analyzer.analyze_service_quotas(cred_info, allowed_types)
    
        # Display quota information
        print("\n📊 Service Quota Analysis:")
        print("-" * 50)
    
        # Create a list of available types with their quota info for sorting
        available_instance_data = []
    
        for instance_type in allowed_types:
            family = instance_type.split('.')[0]
            if family in quota_info:
                quota = quota_info[family]
                available_capacity = quota.available_capacity
                current_usage = quota.current_usage
                quota_limit = quota.quota_value
            
                # Store instance data for sorting
                available_instance_data.append({
                    'instance_type': instance_type,
                    'available_capacity': available_capacity,
                    'current_usage': current_usage,
                    'quota_limit': quota_limit
                })
            
                # Display in the current format
                if available_capacity > 0:
                    print(f"✅ {instance_type:15} | Available: {available_capacity:3} | Used: {current_usage:3}/{quota_limit}")
                else:
                    print(f"❌ {instance_type:15} | No capacity available ({current_usage}/{quota_limit})")
            else:
                # Include with default values if no quota info
                available_instance_data.append({
                    'instance_type': instance_type,
                    'available_capacity': 32,  # Default value
                    'current_usage': 0,
                    'quota_limit': 32
                })
                print(f"⚠️  {instance_type:15} | Quota info unavailable (using default 32)")
    
        # Sort by available capacity (highest first)
        sorted_instances = sorted(available_instance_data, key=lambda x: -x['available_capacity'])
    
        # Extract just the instance types for display and selection
        available_types = [item['instance_type'] for item in sorted_instances]
    
        if not available_types:
            print("❌ No instance types available due to quota limits!")
            raise ValueError("No available instance types")
    
        # Let user select multiple instance types
        selected_types = self.multi_select_instance_types(available_types, "On-Demand")
    
        return {'on-demand': selected_types}
    
    def select_spot_instance_types(self, cred_info: CredentialInfo, 
                     allowed_types: List[str], force_refresh: bool = False) -> Dict[str, List[str]]:
        """Select instance types for Spot strategy with analysis"""
        print("\n" + "="*60)
        print("📈 SPOT INSTANCE TYPE SELECTION")
        print("="*60)

        # Check if we should force refresh
        if not force_refresh:
            refresh_choice = input("Use cached spot data if available? (y/n): ").strip().lower()
            force_refresh = refresh_choice == 'n'

        print("Analyzing spot instances and service quotas...")

        # Analyze spot instances and quotas for ALL allowed types
        spot_analyses = self.spot_analyzer.analyze_spot_instances(cred_info, allowed_types, force_refresh)
        quota_info = self.spot_analyzer.analyze_service_quotas(cred_info, allowed_types, force_refresh)

        # Combine spot analysis with quota information
        enhanced_analyses = self.enhance_spot_analysis_with_quotas(spot_analyses, quota_info)

        # Display analysis results - sorted by score and quota
        self.display_spot_analysis_results(enhanced_analyses)

        # Let user review and select
        if enhanced_analyses:
            print("\n" + "="*60)
            review_choice = input("Review detailed JSON summary? (y/n): ").strip().lower()
            if review_choice == 'y':
                self.save_and_display_spot_summary(enhanced_analyses, cred_info)

        # Create a map of instance types to analyses for direct lookup
        # This ensures all instance types are included, even if some didn't get analyzed
        analyses_by_type = {}
        for analysis in enhanced_analyses:
            if analysis.instance_type not in analyses_by_type:
                analyses_by_type[analysis.instance_type] = []
            analyses_by_type[analysis.instance_type].append(analysis)
    
        # Create a list of all instance types, prioritizing those with analyses
        available_spot_types = []
        seen = set()
    
        # First add analyzed instance types, sorted by score and quota
        sorted_analyses = sorted(enhanced_analyses, key=lambda x: (x.score, x.quota_available), reverse=True)
        for analysis in sorted_analyses:
            if analysis.instance_type not in seen:
                available_spot_types.append(analysis.instance_type)
                seen.add(analysis.instance_type)
    
        # Then add any remaining instance types from allowed_types that weren't analyzed
        for instance_type in allowed_types:
            if instance_type not in seen:
                available_spot_types.append(instance_type)
                seen.add(instance_type)
            
        # Let user select from the list
        selected_types = self.multi_select_instance_types(available_spot_types, "Spot")
    
        return {'spot': selected_types}
    
    def select_mixed_instance_types(self, cred_info: CredentialInfo, 
                                  allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for Mixed strategy"""
        print("\n" + "="*60)
        print("🔄 MIXED STRATEGY INSTANCE TYPE SELECTION")
        print("="*60)
        
        # Get On-Demand types
        print("Step 1: Select On-Demand instance types")
        ondemand_selection = self.select_ondemand_instance_types(cred_info, allowed_types)
        
        # Get Spot types
        print("\nStep 2: Select Spot instance types")
        spot_selection = self.select_spot_instance_types(cred_info, allowed_types)
        
        # Get On-Demand percentage
        print("\n" + "="*50)
        print("⚖️ On-Demand vs Spot Percentage")
        print("="*50)
        print("Default: 50% On-Demand, 50% Spot")
        
        while True:
            try:
                percentage = input("Enter On-Demand percentage (0-100, default 50): ").strip()
                if not percentage:
                    percentage = 50
                else:
                    percentage = int(percentage)
                
                if 0 <= percentage <= 100:
                    break
                else:
                    print("❌ Please enter a value between 0 and 100")
            except ValueError:
                print("❌ Please enter a valid number")
        
        return {
            'on-demand': ondemand_selection['on-demand'],
            'spot': spot_selection['spot'],
            'on_demand_percentage': percentage
        }
    
    def multi_select_instance_types(self, available_types: List[str], strategy_name: str) -> List[str]:
        """Allow user to select multiple instance types"""
        print(f"\n📝 Select {strategy_name} Instance Types:")
        print("You can select multiple types for better availability")
        print("-" * 50)
        
        for i, instance_type in enumerate(available_types, 1):
            print(f"  {i:2}. {instance_type}")
        
        print("\nSelection format:")
        print("  Single: 1")
        print("  Multiple: 1,3,5")
        print("  Range: 1-4")
        print("  Combined: 1,3,5-8")
        
        while True:
            try:
                selection = input(f"Select {strategy_name} instance types: ").strip()
                selected_indices = self.parse_selection(selection, len(available_types))
                
                if selected_indices:
                    selected_types = [available_types[i-1] for i in selected_indices]
                    print(f"✅ Selected {strategy_name} types: {', '.join(selected_types)}")
                    return selected_types
                else:
                    print("❌ No valid selection made")
            except ValueError as e:
                print(f"❌ {e}")
    
    def parse_selection(self, selection: str, max_count: int) -> List[int]:
        """Parse user selection string into list of indices"""
        selected_indices = set()
        
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_count:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_count})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                # Handle single number
                try:
                    num = int(part)
                    if num < 1 or num > max_count:
                        raise ValueError(f"Selection {num} is out of bounds (1-{max_count})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid selection: {part}")
        
        return sorted(list(selected_indices))
    
    def enhance_spot_analysis_with_quotas(self, spot_analyses: List[SpotAnalysis], 
                                        quota_info: Dict[str, ServiceQuotaInfo]) -> List[SpotAnalysis]:
        """Enhance spot analysis with quota information"""
        enhanced = []
        
        for analysis in spot_analyses:
            family = analysis.instance_type.split('.')[0]
            if family in quota_info:
                # Update quota available in analysis
                analysis.quota_available = quota_info[family].available_capacity
                # Recalculate score with quota consideration
                quota_score = min(100, (analysis.quota_available / 10) * 10)  # Scale quota to score
                analysis.score = (analysis.score + quota_score) / 2
            
            enhanced.append(analysis)
        
        return enhanced
    
    def display_spot_analysis_results(self, analyses: List[SpotAnalysis]):
        """Display spot analysis results in a formatted table"""
        if not analyses:
            print("❌ No spot analysis results available")
            return

        # Sort by both score and quota_available (gives higher priority to score, then quota)
        sorted_analyses = sorted(analyses, key=lambda x: (x.score, x.quota_available), reverse=True)

        print("\n" + "="*100)
        print("📊 SPOT INSTANCE ANALYSIS RESULTS")
        print("="*100)

        print(f"{'Type':<12} {'Zone':<15} {'Price':<8} {'Avg':<8} {'Interrupt':<10} {'Quota':<6} {'Score':<6}")
        print("-" * 100)

        # Show top 15 results
        for analysis in sorted_analyses[:15]:
            print(f"{analysis.instance_type:<12} {analysis.availability_zone:<15} "
                  f"${analysis.current_price:<7.4f} ${analysis.price_history_avg:<7.4f} "
                  f"{analysis.interruption_rate:<10} {analysis.quota_available:<6} {analysis.score:<6.1f}")

    def save_and_display_spot_summary(self, analyses: List[SpotAnalysis], cred_info: CredentialInfo):
        """Save and display detailed spot analysis summary"""
        try:
            # Create output directory
            output_dir = f"aws/asg/{cred_info.account_name}"
            os.makedirs(output_dir, exist_ok=True)
            
            # Prepare summary
            summary = {
                'timestamp': datetime.now().isoformat(),
                'account_info': {
                    'account_name': cred_info.account_name,
                    'region': cred_info.regions[0],
                    'credential_type': cred_info.credential_type
                },
                'analysis_summary': {
                    'total_analyzed': len(analyses),
                    'high_score_count': len([a for a in analyses if a.score > 70]),
                    'medium_score_count': len([a for a in analyses if 40 <= a.score <= 70]),
                    'low_score_count': len([a for a in analyses if a.score < 40])
                },
                'detailed_results': [asdict(analysis) for analysis in analyses]
            }
            
            # Save to JSON file
            filename = f"{output_dir}/spot_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(summary, f, indent=2)
            
            print(f"📁 Spot analysis saved to: {filename}")
            
            # Display summary
            print("\n" + "="*60)
            print("📋 SPOT ANALYSIS SUMMARY")
            print("="*60)
            print(f"Total instances analyzed: {summary['analysis_summary']['total_analyzed']}")
            print(f"High score (>70): {summary['analysis_summary']['high_score_count']}")
            print(f"Medium score (40-70): {summary['analysis_summary']['medium_score_count']}")
            print(f"Low score (<40): {summary['analysis_summary']['low_score_count']}")
            
        except Exception as e:
            print(f"⚠️ Warning: Could not save spot analysis summary: {e}")
    
    def create_asg_with_strategy(self, cred_info: CredentialInfo, instance_selections: Dict[str, List[str]], 
                           launch_template_id: str, strategy: str, enable_scheduled_scaling: bool = True) -> Dict:
        """Create Auto Scaling Group with specified strategy"""
        region = cred_info.regions[0]
        execution_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
        try:
            # Create ASG client
            asg_client = boto3.client(
                'autoscaling',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )
        
            # Create ASG configuration
            asg_config = self.build_asg_config(cred_info, instance_selections, launch_template_id, strategy, enable_scheduled_scaling)
        
            print(f"\n🚀 Creating Auto Scaling Group: {asg_config.name}")
            print(f"   📍 Region: {region}")
            print(f"   📊 Strategy: {strategy.upper()}")
            print(f"   💻 Instance Types: {', '.join(asg_config.instance_types)}")
            print(f"   📈 Capacity: Min={asg_config.min_size}, Desired={asg_config.desired_capacity}, Max={asg_config.max_size}")
        
            # Get subnet information for reporting
            subnets = self._get_subnets_for_azs(asg_config.availability_zones, asg_config.region, cred_info)
        
            # Create the ASG based on strategy
            if strategy == 'on-demand':
                asg_response = self.create_ondemand_asg(asg_client, asg_config, cred_info, enable_scheduled_scaling)
            elif strategy == 'spot':
                asg_response = self.create_spot_asg(asg_client, asg_config, cred_info, enable_scheduled_scaling)
            else:  # mixed
                asg_response = self.create_mixed_asg(asg_client, asg_config, instance_selections, cred_info, enable_scheduled_scaling)
        
            print(f"✅ Auto Scaling Group created successfully!")

            # After ASG creation, add scaling policies and alarms
            scaling_policy_result = self.create_asg_scaling_policies(asg_config.name, cred_info)
            if scaling_policy_result['status'] == 'success':
                print(f"✅ Scaling policies and alarms attached to ASG: {asg_config.name}")
            else:
                print(f"⚠️ Failed to attach scaling policies: {scaling_policy_result['error_message']}")

            # Save ASG details
            self.save_asg_details(cred_info, asg_config, asg_response, scaling_policy_result)
        
            # Create detailed result dictionary for the report
            result = {
                'asg_name': asg_config.name,
                'strategy': strategy,
                'instance_types': asg_config.instance_types,
                'region': region,
                'launch_template_id': launch_template_id,
                'min_size': asg_config.min_size,
                'max_size': asg_config.max_size,
                'desired_capacity': asg_config.desired_capacity,
                'spot_allocation_strategy': asg_config.spot_allocation_strategy,
                'on_demand_percentage': asg_config.on_demand_percentage,
                'subnets': subnets,
                'created_at': self.current_time,
                'enabled_scheduled_scaling': enable_scheduled_scaling,
                # Get VPC ID from the first subnet
                'vpc_id': self._get_vpc_from_subnet(subnets[0], region, cred_info) if subnets else 'Unknown'
            }
        
            # Generate and save the comprehensive report
            self.generate_asg_report(cred_info, result, instance_selections, execution_timestamp)
        
            # Print summary with email
            print("\n" + "="*50)
            print("📋 SUMMARY:")
            print(f"   🔑 Credential Type: {cred_info.credential_type}")
            print(f"   🏢 Account: {cred_info.account_name}")
            print(f"   📧 Email: {cred_info.email}")
            print(f"   🌍 Region: {region}")
            print(f"   🚀 ASG Name: {asg_config.name}")
            print(f"   📊 ASG Strategy: {strategy.upper()}")
            print(f"   📁 Output saved to: aws/asg/{cred_info.account_name}/")
            print(f"   📊 Report: aws/asg/{cred_info.account_name}/asg_report_{execution_timestamp}.json")
            print("="*50)
        
            return result
        
        except Exception as e:
            # Handle failures and generate report with failed information
            print(f"❌ Error creating Auto Scaling Group: {e}")
        
            # Create failed result dictionary
            failed_result = {
                "metadata": {
                    "creation_date": datetime.now().strftime('%Y-%m-%d'),
                    "creation_time": datetime.now().strftime('%H:%M:%S'),
                    "created_by": self.current_user,
                    "execution_timestamp": execution_timestamp,
                    "strategy": strategy
                },
                "summary": {
                    "total_created": 0,
                    "total_failed": 1,
                    "success_rate": "0.0%",
                    "accounts_processed": 1,
                    "regions_used": [region]
                },
                "created_asgs": [],
                "failed_asgs": [{
                    "region": region,
                    "strategy": strategy,
                    "instance_types": instance_selections.get('on-demand', []) + instance_selections.get('spot', []),
                    "launch_template_id": launch_template_id,
                    "account_name": cred_info.account_name,
                    "account_id": cred_info.account_id,
                    "account_email": cred_info.email,
                    "attempted_at": self.current_time,
                    "error": str(e)
                }]
            }
        
            # Create output directory
            output_dir = f"aws/asg/{cred_info.account_name}"
            os.makedirs(output_dir, exist_ok=True)
        
            # Save failed report to JSON file
            failed_filename = f"{output_dir}/asg_report_failed_{execution_timestamp}.json"
            with open(failed_filename, 'w') as f:
                json.dump(failed_result, f, indent=2)
        
            print(f"📊 Failed ASG report saved to: {failed_filename}")
            raise

    def _get_vpc_from_subnet(self, subnet_id: str, region: str, cred_info: CredentialInfo) -> str:
        """Get VPC ID for a subnet"""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )
            subnet_response = ec2_client.describe_subnets(SubnetIds=[subnet_id])
            if subnet_response and 'Subnets' in subnet_response and subnet_response['Subnets']:
                return subnet_response['Subnets'][0].get('VpcId', 'Unknown')
            return 'Unknown'
        except Exception as e:
            print(f"⚠️ Warning: Could not get VPC ID for subnet {subnet_id}: {e}")
            return 'Unknown'

    def build_asg_config(self, cred_info: CredentialInfo, instance_selections: Dict[str, List[str]], 
            launch_template_id: str, strategy: str, enable_scheduled_scaling: bool = True) -> ASGConfig:
        """Build ASG configuration based on selections"""
        region = cred_info.regions[0]
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')

        # Use the static method properly
        suffix = self.generate_random_suffix()  # Using class method

        # Only include the instance types explicitly selected by the user
        all_instance_types = []
    
        # Get the appropriate instance types based on the strategy
        if strategy == 'on-demand' and 'on-demand' in instance_selections:
            # For on-demand strategy, only use the on-demand instance types
            all_instance_types = instance_selections['on-demand']
            print(f"DEBUG: Selected on-demand instance types: {all_instance_types}")
        
        elif strategy == 'spot' and 'spot' in instance_selections:
            # For spot strategy, only use the spot instance types
            all_instance_types = instance_selections['spot']
            print(f"DEBUG: Selected spot instance types: {all_instance_types}")
        
        elif strategy == 'mixed':
            # For mixed strategy, include both on-demand and spot types
            mixed_instance_types = []
        
            # Add on-demand types first (they get priority in the ASG)
            if 'on-demand' in instance_selections:
                mixed_instance_types.extend(instance_selections['on-demand'])
            
            # Then add spot types
            if 'spot' in instance_selections:
                # Add any spot types that aren't already in the list
                for spot_type in instance_selections['spot']:
                    if spot_type not in mixed_instance_types:
                        mixed_instance_types.append(spot_type)
                    
            all_instance_types = mixed_instance_types
            print(f"DEBUG: Mixed strategy instance types: {all_instance_types}")

        # Get availability zones
        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=cred_info.access_key,
            aws_secret_access_key=cred_info.secret_key,
            region_name=region
        )

        azs_response = ec2_client.describe_availability_zones()
        availability_zones = [az['ZoneName'] for az in azs_response['AvailabilityZones']]

        # Prompt for capacity settings
        #declare default value
        min_size, desired_capacity, max_size = (1, 1, 3)
       # min_size, desired_capacity, max_size = self.prompt_capacity_settings()

        # Update ASG naming format to include random 4-character suffix
        asg_name = f"asg-{cred_info.account_name}-{strategy}-{suffix}"

        # Verify that we have instance types before continuing
        if not all_instance_types:
            error_msg = f"No instance types selected for {strategy} strategy!"
            print(f"❌ {error_msg}")
            raise ValueError(error_msg)

        return ASGConfig(
            name=asg_name,
            launch_template_id=launch_template_id,
            launch_template_version='$Latest',
            min_size=min_size,
            max_size=max_size,
            desired_capacity=desired_capacity,
            availability_zones=availability_zones,
            region=region,
            strategy=strategy,
            instance_types=all_instance_types,
            spot_allocation_strategy='capacity-optimized' if strategy in ['spot', 'mixed'] else None,
            on_demand_percentage=instance_selections.get('on_demand_percentage', 50) if strategy == 'mixed' else None
        )
    def prompt_capacity_settings(self) -> Tuple[int, int, int]:
        """Prompt user for ASG capacity settings"""
        print("\n" + "="*50)
        print("📊 AUTO SCALING GROUP CAPACITY SETTINGS")
        print("="*50)
        
        while True:
            try:
                min_size = int(input("Minimum capacity (default 1): ").strip() or "1")
                if min_size < 0:
                    print("❌ Minimum capacity must be >= 0")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        while True:
            try:
                desired_capacity = int(input(f"Desired capacity (default {max(1, min_size)}): ").strip() or str(max(1, min_size)))
                if desired_capacity < min_size:
                    print(f"❌ Desired capacity must be >= minimum capacity ({min_size})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        while True:
            try:
                max_size = int(input(f"Maximum capacity (default {max(desired_capacity, 5)}): ").strip() or str(max(desired_capacity, 5)))
                if max_size < desired_capacity:
                    print(f"❌ Maximum capacity must be >= desired capacity ({desired_capacity})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        return min_size, desired_capacity, max_size

    def save_asg_details(self, cred_info, asg_config, asg_response, scaling_policy_result=None):
        """Save ASG details to output folder"""
        try:
            # Create output directory
            output_dir = f"aws/asg/{cred_info.account_name}"
            os.makedirs(output_dir, exist_ok=True)
            
            # Prepare ASG details
            details = {
                'timestamp': datetime.now().isoformat(),
                'created_by': self.current_user,
                'account_info': {
                    'account_name': cred_info.account_name,
                    'account_id': cred_info.account_id,
                    'credential_type': cred_info.credential_type,
                    'region': cred_info.regions[0]
                },
                'asg_configuration': asdict(asg_config),
                'aws_response': asg_response,
                'scaling_policy_result': scaling_policy_result
            }
            
            # Save to JSON file
            filename = f"{output_dir}/asg_{asg_config.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(details, f, indent=2)
            
            print(f"📁 ASG details saved to: {filename}")
            
        except Exception as e:
            print(f"⚠️ Warning: Could not save ASG details: {e}")

    def _get_unsupported_azs(self, region: str) -> Set[str]:
        """Load unsupported AZs from ec2-region-ami-mapping.json file"""
        try:
            # Adjust the path to your mapping file
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
            
            if not os.path.exists(mapping_file_path):
                self.log_operation('WARNING', f"Mapping file not found: {mapping_file_path}")
                return set()
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            # Get unsupported AZs for the specified region
            unsupported_azs = set()
            
            if 'eks_unsupported_azs' in mapping_data and region in mapping_data['eks_unsupported_azs']:
                unsupported_azs = set(mapping_data['eks_unsupported_azs'][region])
                self.log_operation('DEBUG', f"Loaded {len(unsupported_azs)} unsupported AZs for {region} from mapping file")
            else:
                self.log_operation('DEBUG', f"No unsupported AZs found for region {region} in mapping file")
            
            return unsupported_azs
            
        except Exception as e:
            self.log_operation('WARNING', f"Failed to load unsupported AZs from mapping file: {str(e)}")


    def attach_scheduled_actions(self, asg_client, asg_name: str, region: str) -> bool:
        """Attach scheduled scaling actions directly to the ASG with conflict handling"""
        try:
            self.log_operation('INFO', f"Attaching scheduled scaling actions to ASG {asg_name}")
            print(f"🕒 Attaching scheduled scaling actions to ASG {asg_name}...")
        
            # First, check for existing scheduled actions
            try:
                response = asg_client.describe_scheduled_actions(
                    AutoScalingGroupName=asg_name
                )
                existing_actions = response.get('ScheduledUpdateGroupActions', [])
            
                if existing_actions:
                    action_names = [action['ScheduledActionName'] for action in existing_actions]
                    print(f"⚠️ Found {len(existing_actions)} existing scheduled actions: {', '.join(action_names)}")
                    print("ℹ️ These actions will be used for scheduled scaling")
                    return True
            except Exception as e:
                print(f"⚠️ Warning: Could not check for existing scheduled actions: {str(e)}")
        
            # Generate unique timestamp for start time
            tomorrow = datetime.now() + timedelta(days=1)
            # Add a random offset in seconds to ensure uniqueness (0-899 seconds = 0-15 minutes)
            offset_seconds = random.randint(0, 899)
            unique_start_time = tomorrow.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(seconds=offset_seconds)
        
            # Business hours (8 AM IST = 2:30 AM UTC)
            scale_up_name = f"{asg_name}-scale-up"
            asg_client.put_scheduled_update_group_action(
                AutoScalingGroupName=asg_name,
                ScheduledActionName=scale_up_name,
                StartTime=unique_start_time,
                Recurrence="30 2 * * 1-5",  # 2:30 AM UTC (8 AM IST), Monday-Friday
                MinSize=1,
                MaxSize=3,
                DesiredCapacity=1
            )
            print(f"✅ Created scale-up action: {scale_up_name} (starts at 8:00 AM IST on weekdays)")
        
            # After business hours (7 PM IST = 1:30 PM UTC)
            scale_down_name = f"{asg_name}-scale-down"
            asg_client.put_scheduled_update_group_action(
                AutoScalingGroupName=asg_name,
                ScheduledActionName=scale_down_name,
                StartTime=unique_start_time + timedelta(minutes=1),  # Ensure different start time
                Recurrence="30 13 * * 1-5",  # 1:30 PM UTC (7 PM IST), Monday-Friday
                MinSize=0,
                MaxSize=3,
                DesiredCapacity=0
            )
            print(f"✅ Created scale-down action: {scale_down_name} (starts at 7:00 PM IST on weekdays)")
            print(f"🗓️ Scaling actions will begin tomorrow and repeat on weekdays thereafter")
        
            print(f"✅ Scheduled scaling actions attached to ASG {asg_name}")
            self.log_operation('INFO', f"Successfully attached scheduled scaling actions to ASG {asg_name}")
            return True
    
        except Exception as e:
            self.log_operation('ERROR', f"Failed to attach scheduled scaling actions to ASG {asg_name}: {str(e)}")
            print(f"❌ Failed to attach scheduled scaling actions: {str(e)}")
            return False

    def log_operation(self, level, message):
        """Log operations for ASG manager"""
        if hasattr(self, 'logger') and self.logger:
            if level.upper() == 'INFO':
                self.logger.info(message)
            elif level.upper() == 'WARNING':
                self.logger.warning(message)
            elif level.upper() == 'ERROR':
                self.logger.error(message)
            elif level.upper() == 'DEBUG':
                self.logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")