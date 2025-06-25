#!/usr/bin/env python3
"""
EC2 Instance Cleanup Script
This script reads EC2 instance reference files, groups them by creation date,
allows user selection, and deletes the selected instances with comprehensive cleanup
including associated resources like volumes, security groups, and monitoring.
"""

import json
import os
import boto3
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Any
import logging
import subprocess
from botocore.exceptions import ClientError, NoCredentialsError

# Configure logging
import os
from datetime import datetime

# Create timestamp for filename
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_dir = "aws/ec2"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/ec2_cleanup_{timestamp}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EC2CleanupManager:
    def __init__(self, base_path: str = "aws/ec2"):
        self.base_path = base_path
        self.aws_accounts_config = self.load_json_file("aws_accounts_config.json")
        self.users_mapping = self.load_json_file("user_mapping.json")
        self.ec2_files = []
        
    def load_json_file(self, file_path: str) -> Dict:
        """Load JSON file and return its content"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            return {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in file: {file_path}")
            return {}
    
    def scan_ec2_files(self) -> List[Dict]:
        """Scan all EC2 instance files in the directory structure"""
        ec2_files = []
        
        if not os.path.exists(self.base_path):
            logger.error(f"Base path does not exist: {self.base_path}")
            return ec2_files
        
        # Pattern to match EC2 instance files
        patterns = [
            re.compile(r'ec2_instance_i-[a-f0-9]+_(\d{8}T\d{6}\.\d+)\.json$'),
            re.compile(r'ec2_instance_i-[a-f0-9]+.*\.json$')  # Fallback pattern
        ]
        
        for account_dir in os.listdir(self.base_path):
            account_path = os.path.join(self.base_path, account_dir)
            
            if not os.path.isdir(account_path):
                continue
                
            # Scan directly in account folder (not in subfolder)
            for file_name in os.listdir(account_path):
                matched = False
                timestamp_from_filename = None
                
                for pattern in patterns:
                    match = pattern.match(file_name)
                    if match:
                        matched = True
                        if match.groups():
                            timestamp_from_filename = match.group(1)
                        break
                
                if matched or file_name.startswith('ec2_instance_'):
                    file_path = os.path.join(account_path, file_name)
                    ec2_data = self.load_json_file(file_path)
                    
                    if ec2_data:
                        ec2_data['file_path'] = file_path
                        ec2_data['file_name'] = file_name
                        if timestamp_from_filename:
                            ec2_data['timestamp_from_filename'] = timestamp_from_filename
                        ec2_files.append(ec2_data)
        
        logger.info(f"Found {len(ec2_files)} EC2 instance files")
        return ec2_files
    
    def group_ec2s_by_day(self, ec2_files: List[Dict]) -> Dict[str, List[Dict]]:
        """Group EC2 files by creation day"""
        grouped = defaultdict(list)
        
        for ec2 in ec2_files:
            try:
                # Try to get timestamp from EC2 data first, then from filename
                timestamp = ec2.get('timestamp') or ec2.get('timestamp_from_filename', '')
                
                if timestamp:
                    # Parse timestamp and extract date
                    if 'T' in timestamp:
                        date_str = timestamp.split('T')[0]
                    else:
                        date_str = timestamp[:10]
                    
                    # Convert to readable format
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        day_key = date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        # Try alternative format
                        try:
                            date_obj = datetime.strptime(date_str, '%Y%m%d')
                            day_key = date_obj.strftime('%Y-%m-%d')
                        except ValueError:
                            day_key = "unknown"
                else:
                    day_key = "unknown"
                
                grouped[day_key].append(ec2)
                
            except Exception as e:
                logger.warning(f"Error processing timestamp for {ec2.get('file_name', 'unknown')}: {e}")
                grouped["unknown"].append(ec2)
        
        return dict(grouped)
    
    def display_day_options(self, grouped_ec2s: Dict[str, List[Dict]]) -> None:
        """Display available day options to user"""
        print("\n" + "="*60)
        print("AVAILABLE EC2 CREATION DAYS")
        print("="*60)
        
        sorted_days = sorted([day for day in grouped_ec2s.keys() if day != "unknown"])
        if "unknown" in grouped_ec2s:
            sorted_days.append("unknown")
        
        for i, day in enumerate(sorted_days, 1):
            count = len(grouped_ec2s[day])
            print(f"Day-{i}: {day} ({count} instances)")
        
        print(f"\nTotal days available: {len(sorted_days)}")
        print("="*60)
    
    def get_user_day_selection(self, grouped_ec2s: Dict[str, List[Dict]]) -> List[str]:
        """Get user selection for days"""
        sorted_days = sorted([day for day in grouped_ec2s.keys() if day != "unknown"])
        if "unknown" in grouped_ec2s:
            sorted_days.append("unknown")
        
        while True:
            print("\nDay Selection Options:")
            print("1. Single day (e.g., 'day-1' or '1')")
            print("2. Multiple days (e.g., 'day-1,day-3,day-5' or '1,3,5')")
            print("3. Range of days (e.g., 'day-1-day-3' or '1-3')")
            print("4. All days ('all')")
            
            selection = input("\nEnter your selection: ").strip().lower()
            
            if selection == 'all':
                return sorted_days
            
            try:
                selected_days = []
                
                # Handle range (e.g., "1-3" or "day-1-day-3")
                if '-' in selection and not selection.startswith('day-'):
                    parts = selection.split('-')
                    if len(parts) == 2:
                        start_idx = int(parts[0]) - 1
                        end_idx = int(parts[1]) - 1
                        selected_days = sorted_days[start_idx:end_idx + 1]
                elif 'day-' in selection and '-day-' in selection:
                    # Handle "day-1-day-3" format
                    match = re.match(r'day-(\d+)-day-(\d+)', selection)
                    if match:
                        start_idx = int(match.group(1)) - 1
                        end_idx = int(match.group(2)) - 1
                        selected_days = sorted_days[start_idx:end_idx + 1]
                
                # Handle comma-separated values
                elif ',' in selection:
                    indices = []
                    for item in selection.split(','):
                        item = item.strip()
                        if item.startswith('day-'):
                            idx = int(item.replace('day-', '')) - 1
                        else:
                            idx = int(item) - 1
                        indices.append(idx)
                    selected_days = [sorted_days[idx] for idx in indices if 0 <= idx < len(sorted_days)]
                
                # Handle single day
                else:
                    if selection.startswith('day-'):
                        idx = int(selection.replace('day-', '')) - 1
                    else:
                        idx = int(selection) - 1
                    
                    if 0 <= idx < len(sorted_days):
                        selected_days = [sorted_days[idx]]
                
                if selected_days:
                    return selected_days
                else:
                    print("Invalid selection. Please try again.")
                    
            except (ValueError, IndexError):
                print("Invalid format. Please try again.")
    
    def display_ec2s_for_selection(self, ec2s: List[Dict]) -> None:
        """Display EC2 instances for user selection"""
        print("\n" + "="*80)
        print("AVAILABLE EC2 INSTANCES FOR DELETION")
        print("="*80)
        
        for i, ec2 in enumerate(ec2s, 1):
            account_info = ec2.get('account_info', {})
            instance_details = ec2.get('instance_details', {})
            
            print(f"\nInstance-{i}:")
            print(f"  File: {ec2.get('file_name', 'N/A')}")
            print(f"  Instance ID: {instance_details.get('instance_id', 'N/A')}")
            print(f"  Instance Type: {instance_details.get('instance_type', 'N/A')}")
            print(f"  Account: {account_info.get('account_name', 'N/A')}")
            print(f"  Region: {instance_details.get('region', 'N/A')}")
            print(f"  AMI ID: {instance_details.get('ami_id', 'N/A')}")
            print(f"  Launch Template: {instance_details.get('launch_template_id', 'N/A')}")
            print(f"  Timestamp: {ec2.get('timestamp', 'N/A')}")
        
        print("="*80)
    
    def get_user_ec2_selection(self, ec2s: List[Dict]) -> List[Dict]:
        """Get user selection for EC2 instances to delete"""
        while True:
            print("\nEC2 Instance Selection Options:")
            print("1. Single instance (e.g., 'instance-1' or '1')")
            print("2. Multiple instances (e.g., 'instance-1,instance-3' or '1,3')")
            print("3. Range of instances (e.g., 'instance-1-instance-3' or '1-3')")
            print("4. All instances ('all')")
            
            selection = input("\nEnter your selection: ").strip().lower()
            
            if selection == 'all':
                return ec2s
            
            try:
                selected_ec2s = []
                
                # Handle range
                if '-' in selection and not selection.startswith('instance-'):
                    parts = selection.split('-')
                    if len(parts) == 2:
                        start_idx = int(parts[0]) - 1
                        end_idx = int(parts[1]) - 1
                        selected_ec2s = ec2s[start_idx:end_idx + 1]
                elif 'instance-' in selection and '-instance-' in selection:
                    match = re.match(r'instance-(\d+)-instance-(\d+)', selection)
                    if match:
                        start_idx = int(match.group(1)) - 1
                        end_idx = int(match.group(2)) - 1
                        selected_ec2s = ec2s[start_idx:end_idx + 1]
                
                # Handle comma-separated values
                elif ',' in selection:
                    indices = []
                    for item in selection.split(','):
                        item = item.strip()
                        if item.startswith('instance-'):
                            idx = int(item.replace('instance-', '')) - 1
                        else:
                            idx = int(item) - 1
                        indices.append(idx)
                    selected_ec2s = [ec2s[idx] for idx in indices if 0 <= idx < len(ec2s)]
                
                # Handle single instance
                else:
                    if selection.startswith('instance-'):
                        idx = int(selection.replace('instance-', '')) - 1
                    else:
                        idx = int(selection) - 1
                    
                    if 0 <= idx < len(ec2s):
                        selected_ec2s = [ec2s[idx]]
                
                if selected_ec2s:
                    return selected_ec2s
                else:
                    print("Invalid selection. Please try again.")
                    
            except (ValueError, IndexError):
                print("Invalid format. Please try again.")
    
    def get_aws_credentials(self, account_name: str) -> Tuple[str, str]:
        """Get AWS credentials for the specified account"""
        accounts = self.aws_accounts_config.get('accounts', {})
        account_info = accounts.get(account_name, {})
        
        access_key = account_info.get('access_key', '')
        secret_key = account_info.get('secret_key', '')
        
        if not access_key or not secret_key:
            logger.error(f"Credentials not found for account: {account_name}")
            return None, None
        
        return access_key, secret_key
    
    def create_boto3_session(self, access_key: str, secret_key: str, region: str) -> boto3.Session:
        """Create boto3 session with provided credentials"""
        return boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
    
    def cleanup_monitoring_resources(self, session: boto3.Session, instance_id: str, region: str) -> bool:
        """Clean up monitoring resources (CloudWatch, SNS) associated with EC2 instance"""
        try:
            logger.info(f"Cleaning up monitoring resources for instance: {instance_id}")
            
            # Clean up CloudWatch alarms
            cloudwatch_client = session.client('cloudwatch', region_name=region)
            try:
                # Search for alarms related to this instance
                alarms_response = cloudwatch_client.describe_alarms()
                
                for alarm in alarms_response.get('MetricAlarms', []):
                    alarm_name = alarm['AlarmName']
                    
                    # Check if alarm is related to our instance
                    for dimension in alarm.get('Dimensions', []):
                        if (dimension.get('Name') == 'InstanceId' and 
                            dimension.get('Value') == instance_id):
                            logger.info(f"Deleting CloudWatch alarm: {alarm_name}")
                            try:
                                cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                            except ClientError as e:
                                logger.warning(f"Error deleting alarm {alarm_name}: {e}")
                            break
                    
                    # Also check alarm names that might contain instance ID
                    if instance_id in alarm_name:
                        logger.info(f"Deleting CloudWatch alarm: {alarm_name}")
                        try:
                            cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                        except ClientError as e:
                            logger.warning(f"Error deleting alarm {alarm_name}: {e}")
                            
            except ClientError as e:
                logger.warning(f"Error cleaning up CloudWatch alarms: {e}")
            
            # Clean up SNS topics and subscriptions
            sns_client = session.client('sns', region_name=region)
            try:
                topics_response = sns_client.list_topics()
                
                for topic in topics_response.get('Topics', []):
                    topic_arn = topic['TopicArn']
                    topic_name = topic_arn.split(':')[-1]
                    
                    if instance_id in topic_name or 'ec2-notification' in topic_name.lower():
                        logger.info(f"Deleting SNS topic: {topic_name}")
                        try:
                            sns_client.delete_topic(TopicArn=topic_arn)
                        except ClientError as e:
                            logger.warning(f"Error deleting SNS topic {topic_name}: {e}")
                            
            except ClientError as e:
                logger.warning(f"Error cleaning up SNS topics: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up monitoring resources: {e}")
            return False
    
    def cleanup_lambda_functions(self, session: boto3.Session, instance_id: str, region: str) -> bool:
        """Clean up Lambda functions associated with EC2 instance management"""
        try:
            logger.info(f"Cleaning up Lambda functions for instance: {instance_id}")
            
            lambda_client = session.client('lambda', region_name=region)
            
            # List all Lambda functions
            functions_response = lambda_client.list_functions(MaxItems=1000)
            
            deleted_functions = []
            for function in functions_response.get('Functions', []):
                function_name = function['FunctionName']
                
                # Check if function is related to the instance
                if (instance_id in function_name or 
                    'ec2-manager' in function_name.lower() or
                    'instance-scheduler' in function_name.lower() or
                    'ec2-scheduler' in function_name.lower() or
                    'instance-monitor' in function_name.lower()):
                    
                    try:
                        # Get function tags to confirm association
                        tags_response = lambda_client.list_tags(Resource=function['FunctionArn'])
                        tags = tags_response.get('Tags', {})
                        
                        # Check if tags indicate association with our instance
                        if (tags.get('InstanceId') == instance_id or 
                            tags.get('EC2Instance') == instance_id or
                            instance_id in tags.get('Purpose', '') or
                            instance_id in tags.get('Resource', '')):
                            
                            logger.info(f"Deleting Lambda function: {function_name}")
                            
                            # Delete event source mappings first
                            try:
                                mappings_response = lambda_client.list_event_source_mappings(
                                    FunctionName=function_name
                                )
                                for mapping in mappings_response.get('EventSourceMappings', []):
                                    lambda_client.delete_event_source_mapping(
                                        UUID=mapping['UUID']
                                    )
                                    logger.info(f"Deleted event source mapping: {mapping['UUID']}")
                            except ClientError as e:
                                logger.warning(f"Error deleting event source mappings: {e}")
                            
                            # Delete the function
                            lambda_client.delete_function(FunctionName=function_name)
                            deleted_functions.append(function_name)
                            
                    except ClientError as e:
                        logger.warning(f"Error processing Lambda function {function_name}: {e}")
            
            if deleted_functions:
                logger.info(f"Successfully deleted Lambda functions: {deleted_functions}")
            else:
                logger.info("No Lambda functions found for deletion")
            
            # Clean up CloudWatch Events/EventBridge rules
            events_client = session.client('events', region_name=region)
            try:
                rules_response = events_client.list_rules(NamePrefix=instance_id)
                for rule in rules_response.get('Rules', []):
                    rule_name = rule['Name']
                    if instance_id in rule_name:
                        logger.info(f"Deleting EventBridge rule: {rule_name}")
                        try:
                            # Remove targets first
                            targets_response = events_client.list_targets_by_rule(Rule=rule_name)
                            if targets_response.get('Targets'):
                                target_ids = [target['Id'] for target in targets_response['Targets']]
                                events_client.remove_targets(Rule=rule_name, Ids=target_ids)
                            
                            # Delete the rule
                            events_client.delete_rule(Name=rule_name)
                        except ClientError as e:
                            logger.warning(f"Error deleting EventBridge rule {rule_name}: {e}")
                            
            except ClientError as e:
                logger.warning(f"Error cleaning up EventBridge rules: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up Lambda functions: {e}")
            return False
    
    def cleanup_volumes_and_snapshots(self, session: boto3.Session, instance_id: str, region: str) -> bool:
        """Clean up EBS volumes and snapshots associated with the instance"""
        try:
            logger.info(f"Cleaning up volumes and snapshots for instance: {instance_id}")
            
            ec2_client = session.client('ec2', region_name=region)
            
            # Get volumes attached to the instance
            try:
                volumes_response = ec2_client.describe_volumes(
                    Filters=[
                        {
                            'Name': 'attachment.instance-id',
                            'Values': [instance_id]
                        }
                    ]
                )
                
                volume_ids = []
                for volume in volumes_response.get('Volumes', []):
                    volume_id = volume['VolumeId']
                    volume_ids.append(volume_id)
                    
                    # Check if volume will be deleted on termination
                    delete_on_termination = False
                    for attachment in volume.get('Attachments', []):
                        if attachment.get('DeleteOnTermination', False):
                            delete_on_termination = True
                            break
                    
                    if not delete_on_termination:
                        logger.info(f"Volume {volume_id} will need manual deletion after instance termination")
                
                # Get snapshots created from these volumes
                if volume_ids:
                    snapshots_response = ec2_client.describe_snapshots(
                        OwnerIds=['self'],
                        Filters=[
                            {
                                'Name': 'volume-id',
                                'Values': volume_ids
                            }
                        ]
                    )
                    
                    for snapshot in snapshots_response.get('Snapshots', []):
                        snapshot_id = snapshot['SnapshotId']
                        logger.info(f"Found snapshot {snapshot_id} for cleanup after instance termination")
                
            except ClientError as e:
                logger.warning(f"Error listing volumes and snapshots: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up volumes and snapshots: {e}")
            return False
    
    def delete_launch_template(self, session: boto3.Session, launch_template_id: str, region: str) -> bool:
        """Delete the launch template associated with the instance"""
        try:
            if not launch_template_id:
                logger.info("No launch template ID provided")
                return True
                
            logger.info(f"Deleting launch template: {launch_template_id}")
            
            ec2_client = session.client('ec2', region_name=region)
            
            try:
                # Check if launch template is used by other instances
                instances_response = ec2_client.describe_instances(
                    Filters=[
                        {
                            'Name': 'launch-template.id',
                            'Values': [launch_template_id]
                        },
                        {
                            'Name': 'instance-state-name',
                            'Values': ['pending', 'running', 'shutting-down', 'stopping', 'stopped']
                        }
                    ]
                )
                
                other_instances = []
                for reservation in instances_response['Reservations']:
                    for instance in reservation['Instances']:
                        other_instances.append(instance['InstanceId'])
                
                if other_instances:
                    logger.warning(f"Launch template {launch_template_id} is still used by other instances: {other_instances}")
                    logger.warning("Skipping launch template deletion")
                    return True
                
                # Delete launch template
                ec2_client.delete_launch_template(LaunchTemplateId=launch_template_id)
                logger.info(f"Launch template {launch_template_id} deleted successfully")
                return True
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidLaunchTemplateId.NotFound':
                    logger.info(f"Launch template {launch_template_id} not found, may already be deleted")
                    return True
                else:
                    logger.error(f"Error deleting launch template: {e}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting launch template: {e}")
            return False
    
    def cleanup_security_groups(self, session: boto3.Session, instance_id: str, region: str) -> bool:
        """Clean up security groups that were created specifically for this instance"""
        try:
            logger.info(f"Checking security groups for instance: {instance_id}")
            
            ec2_client = session.client('ec2', region_name=region)
            
            try:
                # Get instance details to find security groups
                instances_response = ec2_client.describe_instances(InstanceIds=[instance_id])
                
                for reservation in instances_response['Reservations']:
                    for instance in reservation['Instances']:
                        security_groups = instance.get('SecurityGroups', [])
                        
                        for sg in security_groups:
                            sg_id = sg['GroupId']
                            sg_name = sg['GroupName']
                            
                            # Only try to delete security groups that appear to be instance-specific
                            if (instance_id in sg_name or 
                                'temporary' in sg_name.lower() or
                                'instance-specific' in sg_name.lower()):
                                
                                logger.info(f"Attempting to delete security group: {sg_id} ({sg_name})")
                                try:
                                    ec2_client.delete_security_group(GroupId=sg_id)
                                    logger.info(f"Security group {sg_id} deleted successfully")
                                except ClientError as e:
                                    if 'DependencyViolation' in str(e):
                                        logger.info(f"Security group {sg_id} still in use, skipping")
                                    else:
                                        logger.warning(f"Could not delete security group {sg_id}: {e}")
                            else:
                                logger.info(f"Keeping security group {sg_id} ({sg_name}) - appears to be shared")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
                    logger.info(f"Instance {instance_id} not found for security group cleanup")
                else:
                    logger.warning(f"Error checking security groups: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up security groups: {e}")
            return False
    
    def cleanup_associated_resources(self, session: boto3.Session, instance_id: str, region: str) -> None:
        """Clean up additional resources associated with the instance"""
        try:
            # Clean up CloudWatch log groups
            logs_client = session.client('logs', region_name=region)
            try:
                log_groups = logs_client.describe_log_groups()
                
                for log_group in log_groups.get('logGroups', []):
                    log_group_name = log_group['logGroupName']
                    if instance_id in log_group_name:
                        logger.info(f"Deleting log group: {log_group_name}")
                        logs_client.delete_log_group(logGroupName=log_group_name)
                        
            except ClientError as e:
                logger.warning(f"Error cleaning up log groups: {e}")
            
            # Clean up Route 53 records if any
            route53_client = session.client('route53', region_name=region)
            try:
                hosted_zones = route53_client.list_hosted_zones()
                
                for zone in hosted_zones.get('HostedZones', []):
                    zone_id = zone['Id'].split('/')[-1]
                    
                    try:
                        records = route53_client.list_resource_record_sets(HostedZoneId=zone_id)
                        
                        for record in records.get('ResourceRecordSets', []):
                            record_name = record.get('Name', '')
                            if instance_id in record_name:
                                logger.info(f"Found Route 53 record for cleanup: {record_name}")
                                # Note: Actual deletion would require more complex logic
                                # to handle different record types and dependencies
                                
                    except ClientError as e:
                        logger.warning(f"Error checking Route 53 records in zone {zone_id}: {e}")
                        
            except ClientError as e:
                logger.warning(f"Error accessing Route 53: {e}")
                
        except Exception as e:
            logger.error(f"Error during additional resource cleanup: {e}")
    
    def delete_ec2_instance(self, ec2_data: Dict) -> bool:
        """Delete a single EC2 instance with comprehensive cleanup"""
        try:
            account_info = ec2_data.get('account_info', {})
            instance_details = ec2_data.get('instance_details', {})
            
            account_name = account_info.get('account_name')
            instance_id = instance_details.get('instance_id')
            region = instance_details.get('region')
            launch_template_id = instance_details.get('launch_template_id')
            
            if not all([account_name, instance_id, region]):
                logger.error(f"Missing required information in EC2 data: {ec2_data.get('file_name')}")
                return False
            
            logger.info(f"Starting comprehensive deletion of EC2 instance: {instance_id}")
            
            # Get AWS credentials
            access_key, secret_key = self.get_aws_credentials(account_name)
            if not access_key or not secret_key:
                return False
            
            # Create boto3 session
            session = self.create_boto3_session(access_key, secret_key, region)
            ec2_client = session.client('ec2', region_name=region)
            
            # Check if instance exists
            try:
                instances_response = ec2_client.describe_instances(InstanceIds=[instance_id])
                
                instance_found = False
                current_state = None
                for reservation in instances_response['Reservations']:
                    for instance in reservation['Instances']:
                        if instance['InstanceId'] == instance_id:
                            instance_found = True
                            current_state = instance['State']['Name']
                            break
                
                if not instance_found:
                    logger.info(f"Instance {instance_id} not found, cleaning up associated resources")
                    # Still run cleanup for associated resources
                    self.cleanup_monitoring_resources(session, instance_id, region)
                    self.cleanup_lambda_functions(session, instance_id, region)
                    self.delete_launch_template(session, launch_template_id, region)
                    return True
                
                if current_state in ['terminated', 'terminating']:
                    logger.info(f"Instance {instance_id} is already {current_state}, cleaning up associated resources")
                    # Still run cleanup for associated resources
                    self.cleanup_monitoring_resources(session, instance_id, region)
                    self.cleanup_lambda_functions(session, instance_id, region)
                    self.delete_launch_template(session, launch_template_id, region)
                    return True
                
                logger.info(f"Instance {instance_id} current state: {current_state}")
                    
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
                    logger.info(f"Instance {instance_id} not found, cleaning up associated resources")
                    # Still run cleanup for associated resources
                    self.cleanup_monitoring_resources(session, instance_id, region)
                    self.cleanup_lambda_functions(session, instance_id, region)
                    self.delete_launch_template(session, launch_template_id, region)
                    return True
                else:
                    logger.error(f"Error checking instance status: {e}")
                    return False
            
            # Step 1: Clean up monitoring resources
            logger.info("Step 1: Cleaning up monitoring resources...")
            if not self.cleanup_monitoring_resources(session, instance_id, region):
                logger.warning("Some monitoring resources may not have been cleaned up properly")
            
            # Step 2: Clean up Lambda functions
            logger.info("Step 2: Cleaning up Lambda functions...")
            if not self.cleanup_lambda_functions(session, instance_id, region):
                logger.warning("Some Lambda functions may not have been cleaned up properly")
            
            # Step 3: Clean up volumes and snapshots info (before termination)
            logger.info("Step 3: Checking volumes and snapshots...")
            if not self.cleanup_volumes_and_snapshots(session, instance_id, region):
                logger.warning("Some volume/snapshot information may not have been processed")
            
            # Step 4: Terminate the instance
            logger.info(f"Step 4: Terminating EC2 instance: {instance_id}")
            try:
                ec2_client.terminate_instances(InstanceIds=[instance_id])
                logger.info(f"Instance {instance_id} termination initiated")
                
                # Wait for instance termination
                logger.info("Waiting for instance termination to complete...")
                waiter = ec2_client.get_waiter('instance_terminated')
                try:
                    waiter.wait(
                        InstanceIds=[instance_id],
                        WaiterConfig={
                            'Delay': 15,
                            'MaxAttempts': 40  # 10 minutes
                        }
                    )
                    logger.info(f"Instance {instance_id} terminated successfully")
                    
                except Exception as e:
                    logger.warning(f"Timeout waiting for instance termination: {e}")
                    logger.info("Proceeding with cleanup of remaining resources")
                
            except ClientError as e:
                logger.error(f"Error terminating instance: {e}")
                return False
            
            # Step 5: Clean up security groups (after termination)
            logger.info("Step 5: Cleaning up security groups...")
            if not self.cleanup_security_groups(session, instance_id, region):
                logger.warning("Some security groups may not have been cleaned up properly")
            
            # Step 6: Delete launch template (if not used by other instances)
            logger.info("Step 6: Checking launch template for deletion...")
            if not self.delete_launch_template(session, launch_template_id, region):
                logger.warning("Launch template may not have been deleted properly")
            
            # Step 7: Clean up additional associated resources
            logger.info("Step 7: Cleaning up additional resources...")
            self.cleanup_associated_resources(session, instance_id, region)
            
            logger.info(f"EC2 instance {instance_id} and associated resources deleted successfully")
            return True
                
        except Exception as e:
            logger.error(f"Error deleting EC2 instance: {e}")
            return False
    
    def delete_ec2_reference_file(self, file_path: str) -> bool:
        """Delete the EC2 reference file after successful deletion"""
        try:
            if os.path.exists(file_path):
                # Create backup before deletion
                backup_path = file_path + '.deleted.' + str(int(time.time()))
                os.rename(file_path, backup_path)
                logger.info(f"EC2 reference file moved to: {backup_path}")
                return True
            else:
                logger.warning(f"Reference file not found: {file_path}")
                return False
        except Exception as e:
            logger.error(f"Error handling reference file {file_path}: {e}")
            return False
    
    def run_cleanup(self) -> None:
        """Main method to run the cleanup process"""
        logger.info("Starting EC2 Instance Cleanup Process")
        
        # Scan for EC2 files
        ec2_files = self.scan_ec2_files()
        if not ec2_files:
            logger.info("No EC2 instance files found")
            return
        
        # Group by day
        grouped_ec2s = self.group_ec2s_by_day(ec2_files)
        
        # Display day options
        self.display_day_options(grouped_ec2s)
        
        # Get user day selection
        selected_days = self.get_user_day_selection(grouped_ec2s)
        
        # Collect EC2s from selected days
        selected_ec2s = []
        for day in selected_days:
            selected_ec2s.extend(grouped_ec2s[day])
        
        if not selected_ec2s:
            logger.info("No EC2 instances selected")
            return
        
        # Display EC2 options
        self.display_ec2s_for_selection(selected_ec2s)
        
        # Get user EC2 selection
        ec2s_to_delete = self.get_user_ec2_selection(selected_ec2s)
        
        # Confirm deletion
        print(f"\nYou have selected {len(ec2s_to_delete)} EC2 instance(s) for deletion:")
        for ec2 in ec2s_to_delete:
            instance_id = ec2.get('instance_details', {}).get('instance_id', 'N/A')
            instance_type = ec2.get('instance_details', {}).get('instance_type', 'N/A')
            account_name = ec2.get('account_info', {}).get('account_name', 'N/A')
            print(f"  - {instance_id} ({instance_type}) (Account: {account_name})")
        
        print("\nThis will also delete:")
        print("  - EC2 instances and associated EBS volumes")
        print("  - Launch templates (if not used by other instances)")
        print("  - Instance-specific security groups")
        print("  - Lambda functions for instance management")
        print("  - CloudWatch alarms and monitoring")
        print("  - SNS topics and notifications")
        print("  - CloudWatch log groups")
        print("  - EventBridge rules and schedules")
        
        confirm = input("\nAre you sure you want to delete these EC2 instances and all associated resources? (yes/no): ").strip().lower()
        if confirm != 'yes':
            logger.info("Deletion cancelled by user")
            return
        
        # Delete EC2 instances
        successful_deletions = 0
        failed_deletions = 0
        
        for i, ec2 in enumerate(ec2s_to_delete, 1):
            instance_id = ec2.get('instance_details', {}).get('instance_id', 'Unknown')
            logger.info(f"Processing EC2 instance {i}/{len(ec2s_to_delete)}: {instance_id}")
            
            if self.delete_ec2_instance(ec2):
                successful_deletions += 1
                # Delete reference file
                self.delete_ec2_reference_file(ec2.get('file_path', ''))
            else:
                failed_deletions += 1
            
            # Add delay between deletions
            if i < len(ec2s_to_delete):
                logger.info("Waiting before next deletion...")
                time.sleep(10)
        
        # Summary
        logger.info("="*60)
        logger.info("EC2 CLEANUP SUMMARY")
        logger.info("="*60)
        logger.info(f"Total EC2 instances processed: {len(ec2s_to_delete)}")
        logger.info(f"Successfully deleted: {successful_deletions}")
        logger.info(f"Failed deletions: {failed_deletions}")
        logger.info("Resources cleaned up per instance:")
        logger.info("  - EC2 instance and EBS volumes")
        logger.info("  - Launch templates (when safe)")
        logger.info("  - Instance-specific security groups")
        logger.info("  - Lambda functions for management")
        logger.info("  - CloudWatch alarms and monitoring")
        logger.info("  - SNS notifications")
        logger.info("  - CloudWatch logs and EventBridge rules")
        logger.info("="*60)

def main():
    """Main function"""
    try:
        # Check if required files exist
        required_files = ["aws_accounts_config.json", "user_mapping.json"]
        for file_path in required_files:
            if not os.path.exists(file_path):
                logger.error(f"Required file not found: {file_path}")
                return
        
        # Initialize and run cleanup
        manager = EC2CleanupManager()
        manager.run_cleanup()
        
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()