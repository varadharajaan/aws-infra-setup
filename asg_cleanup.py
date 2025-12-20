#!/usr/bin/env python3
"""
ASG (Auto Scaling Group) Cleanup Script
This script reads ASG reference files, groups them by creation date,
allows user selection, and deletes the selected ASGs with comprehensive cleanup
including launch templates, instances, and associated resources.
"""

import json
import os
import boto3
import re
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple
import logging
from botocore.exceptions import ClientError

# Configure logging
# Create timestamp for filename
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_dir = "aws/asg"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/asg_cleanup_{timestamp}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ASGCleanupManager:

    def __init__(self, base_path: str = "aws/asg"):
        self.base_path = base_path
        self.aws_accounts_config = self.load_json_file("aws_accounts_config.json")
        self.users_mapping = self.load_json_file("user_mapping.json")
        self.asg_files = []
        
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

    def scan_asg_files(self) -> List[Dict]:
        """Scan all ASG files in the directory structure"""
        asg_files = []

        if not os.path.exists(self.base_path):
            logger.error(f"Base path does not exist: {self.base_path}")
            return asg_files

        # Updated patterns to match only successful ASG reports and exclude failed ones
        patterns = [
            re.compile(r'^asg_report_(\d{8}_\d{6})\.json$'),  # Exact pattern: asg_report_YYYYMMDD_HHMMSS.json
            re.compile(r'^asg_report_(\d{8}T\d{6}\.\d+)\.json$')  # Alternative with T and milliseconds
        ]

        for account_dir in os.listdir(self.base_path):
            account_path = os.path.join(self.base_path, account_dir)

            if not os.path.isdir(account_path):
                continue

            for file_name in os.listdir(account_path):
                # Skip files that contain "failed" in the name
                if 'failed' in file_name.lower():
                    logger.info(f"Skipping failed ASG report: {file_name}")
                    continue

                # Skip files that don't start with "asg_report"
                if not file_name.startswith('asg_report'):
                    continue

                matched = False
                timestamp_from_filename = None

                # Check against patterns
                for pattern in patterns:
                    match = pattern.match(file_name)
                    if match:
                        matched = True
                        timestamp_from_filename = match.group(1)
                        logger.info(f"Matched ASG report file: {file_name}")
                        break

                if matched:
                    file_path = os.path.join(account_path, file_name)
                    asg_data = self.load_json_file(file_path)

                    if asg_data:
                        asg_data['file_path'] = file_path
                        asg_data['file_name'] = file_name
                        if timestamp_from_filename:
                            asg_data['timestamp_from_filename'] = timestamp_from_filename
                        asg_files.append(asg_data)
                        logger.info(f"Successfully loaded ASG file: {file_name}")
                else:
                    logger.debug(f"File {file_name} did not match expected pattern")

        logger.info(f"Found {len(asg_files)} valid ASG files (excluding failed reports)")
        return asg_files

    def group_asgs_by_day(self, asg_files: List[Dict]) -> Dict[str, List[Dict]]:
        """Group ASG files by creation day"""
        grouped = defaultdict(list)

        for asg in asg_files:
            try:
                # Try to get the date from various possible locations
                timestamp = asg.get('timestamp') or asg.get('timestamp_from_filename', '')

                # Try to get from metadata if not found
                if not timestamp and 'metadata' in asg:
                    timestamp = asg['metadata'].get('creation_date')  # e.g., '2025-06-14'
                    # Optionally, if you have creation_time too and want to combine, you can do so

                if timestamp:
                    # If it's a date only, just use it
                    if len(timestamp) == 10 and '-' in timestamp:
                        day_key = timestamp
                    # If it's a datetime string, extract date part
                    elif 'T' in timestamp:
                        day_key = timestamp.split('T')[0]
                    else:
                        # Try to parse as YYYY-MM-DD or YYYYMMDD
                        try:
                            date_obj = datetime.strptime(timestamp[:10], '%Y-%m-%d')
                            day_key = date_obj.strftime('%Y-%m-%d')
                        except ValueError:
                            try:
                                date_obj = datetime.strptime(timestamp[:8], '%Y%m%d')
                                day_key = date_obj.strftime('%Y-%m-%d')
                            except ValueError:
                                day_key = "unknown"
                else:
                    day_key = "unknown"

                grouped[day_key].append(asg)

            except Exception as e:
                logger.warning(f"Error processing timestamp for {asg.get('file_name', 'unknown')}: {e}")
                grouped["unknown"].append(asg)

        return grouped  # Add this missing return statement        """Group ASG files by creation day"""

    def display_day_options(self, grouped_asgs: Dict[str, List[Dict]]) -> None:
        """Display available day options to user"""
        print("\n" + "=" * 60)
        print("AVAILABLE ASG CREATION DAYS")
        print("=" * 60)

        # Sort days in descending order (latest first), excluding "unknown"
        sorted_days = sorted([day for day in grouped_asgs.keys() if day != "unknown"], reverse=True)
        if "unknown" in grouped_asgs:
            sorted_days.append("unknown")

        for i, day in enumerate(sorted_days, 1):
            count = len(grouped_asgs[day])
            print(f"Day-{i}: {day} ({count} ASGs)")

        print(f"\nTotal days available: {len(sorted_days)}")
        print("=" * 60)

    
    def get_user_day_selection(self, grouped_asgs: Dict[str, List[Dict]]) -> List[str]:
        """Get user selection for days"""
        sorted_days = sorted([day for day in grouped_asgs.keys() if day != "unknown"])
        if "unknown" in grouped_asgs:
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

    def display_asgs_for_selection(self, asgs: List[Dict]) -> None:
        """Display ASGs for user selection"""
        print("\n" + "=" * 80)
        print("AVAILABLE ASGs FOR DELETION")
        print("=" * 80)

        for i, asg in enumerate(asgs, 1):
            # Handle the actual file structure
            metadata = asg.get('metadata', {})
            created_asgs = asg.get('created_asgs', [])

            print(f"\nASG-{i}:")
            print(f"  File: {asg.get('file_name', 'N/A')}")
            print(f"  Created By: {metadata.get('created_by', 'N/A')}")
            print(f"  Creation Date: {metadata.get('creation_date', 'N/A')}")
            print(f"  Strategy: {metadata.get('strategy', 'N/A')}")
            print(f"  Launch Template: {metadata.get('launch_template_id', 'N/A')}")

            if created_asgs:
                for j, asg_info in enumerate(created_asgs):
                    print(f"    ASG {j + 1}:")
                    print(f"      Name: {asg_info.get('asg_name', 'N/A')}")
                    print(f"      Account: {asg_info.get('account_name', 'N/A')}")
                    print(f"      Region: {asg_info.get('region', 'N/A')}")
                    print(f"      Instance Types: {', '.join(asg_info.get('instance_types', []))}")
                    print(
                        f"      Min/Desired/Max: {asg_info.get('min_size', 'N/A')}/{asg_info.get('desired_capacity', 'N/A')}/{asg_info.get('max_size', 'N/A')}")

        print("=" * 80)

    def get_user_asg_selection(self, asgs: List[Dict]) -> List[Dict]:
        """Get user selection for ASGs to delete"""
        while True:
            print("\nASG Selection Options:")
            print("1. Single ASG (e.g., 'asg-1' or '1')")
            print("2. Multiple ASGs (e.g., 'asg-1,asg-3' or '1,3')")
            print("3. Range of ASGs (e.g., 'asg-1-asg-3' or '1-3')")
            print("4. All ASGs ('all')")
            
            selection = input("\nEnter your selection: ").strip().lower()
            
            if selection == 'all':
                return asgs
            
            try:
                selected_asgs = []
                
                # Handle range
                if '-' in selection and not selection.startswith('asg-'):
                    parts = selection.split('-')
                    if len(parts) == 2:
                        start_idx = int(parts[0]) - 1
                        end_idx = int(parts[1]) - 1
                        selected_asgs = asgs[start_idx:end_idx + 1]
                elif 'asg-' in selection and '-asg-' in selection:
                    match = re.match(r'asg-(\d+)-asg-(\d+)', selection)
                    if match:
                        start_idx = int(match.group(1)) - 1
                        end_idx = int(match.group(2)) - 1
                        selected_asgs = asgs[start_idx:end_idx + 1]
                
                # Handle comma-separated values
                elif ',' in selection:
                    indices = []
                    for item in selection.split(','):
                        item = item.strip()
                        if item.startswith('asg-'):
                            idx = int(item.replace('asg-', '')) - 1
                        else:
                            idx = int(item) - 1
                        indices.append(idx)
                    selected_asgs = [asgs[idx] for idx in indices if 0 <= idx < len(asgs)]
                
                # Handle single ASG
                else:
                    if selection.startswith('asg-'):
                        idx = int(selection.replace('asg-', '')) - 1
                    else:
                        idx = int(selection) - 1
                    
                    if 0 <= idx < len(asgs):
                        selected_asgs = [asgs[idx]]
                
                if selected_asgs:
                    return selected_asgs
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
    
    def cleanup_monitoring_resources(self, session: boto3.Session, asg_name: str, region: str) -> bool:
        """Clean up monitoring resources (CloudWatch, SNS) associated with ASG"""
        try:
            logger.info(f"Cleaning up monitoring resources for ASG: {asg_name}")
            
            # Clean up CloudWatch alarms
            cloudwatch_client = session.client('cloudwatch', region_name=region)
            try:
                # Search for alarms related to this ASG
                alarms_response = cloudwatch_client.describe_alarms()
                
                for alarm in alarms_response.get('MetricAlarms', []):
                    alarm_name = alarm['AlarmName']
                    
                    # Check if alarm is related to our ASG
                    for dimension in alarm.get('Dimensions', []):
                        if (dimension.get('Name') == 'AutoScalingGroupName' and 
                            dimension.get('Value') == asg_name):
                            logger.info(f"Deleting CloudWatch alarm: {alarm_name}")
                            try:
                                cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                            except ClientError as e:
                                logger.warning(f"Error deleting alarm {alarm_name}: {e}")
                            break
                    
                    # Also check alarm names that might contain ASG name
                    if asg_name in alarm_name:
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
                    
                    if asg_name in topic_name or 'asg-notification' in topic_name.lower():
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
    
    def cleanup_scaling_policies(self, session: boto3.Session, asg_name: str, region: str) -> bool:
        """Clean up scaling policies and scheduled actions"""
        try:
            logger.info(f"Cleaning up scaling policies for ASG: {asg_name}")
            
            autoscaling_client = session.client('autoscaling', region_name=region)
            
            # Delete scaling policies
            try:
                policies_response = autoscaling_client.describe_policies(
                    AutoScalingGroupName=asg_name
                )
                
                for policy in policies_response.get('ScalingPolicies', []):
                    policy_name = policy['PolicyName']
                    logger.info(f"Deleting scaling policy: {policy_name}")
                    try:
                        autoscaling_client.delete_policy(
                            AutoScalingGroupName=asg_name,
                            PolicyName=policy_name
                        )
                    except ClientError as e:
                        logger.warning(f"Error deleting scaling policy {policy_name}: {e}")
                        
            except ClientError as e:
                logger.warning(f"Error listing scaling policies: {e}")
            
            # Delete scheduled actions
            try:
                scheduled_response = autoscaling_client.describe_scheduled_actions(
                    AutoScalingGroupName=asg_name
                )
                
                for action in scheduled_response.get('ScheduledUpdateGroupActions', []):
                    action_name = action['ScheduledActionName']
                    logger.info(f"Deleting scheduled action: {action_name}")
                    try:
                        autoscaling_client.delete_scheduled_action(
                            AutoScalingGroupName=asg_name,
                            ScheduledActionName=action_name
                        )
                    except ClientError as e:
                        logger.warning(f"Error deleting scheduled action {action_name}: {e}")
                        
            except ClientError as e:
                logger.warning(f"Error listing scheduled actions: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up scaling policies: {e}")
            return False
    
    def cleanup_lambda_functions(self, session: boto3.Session, asg_name: str, region: str) -> bool:
        """Clean up Lambda functions associated with ASG scaling"""
        try:
            logger.info(f"Cleaning up Lambda functions for ASG: {asg_name}")
            
            lambda_client = session.client('lambda', region_name=region)
            
            # List all Lambda functions
            functions_response = lambda_client.list_functions(MaxItems=1000)
            
            deleted_functions = []
            for function in functions_response.get('Functions', []):
                function_name = function['FunctionName']
                
                # Check if function is related to the ASG
                if (asg_name in function_name or 
                    'asg-scaler' in function_name.lower() or
                    'autoscaling' in function_name.lower() or
                    'instance-scheduler' in function_name.lower()):
                    
                    try:
                        # Get function tags to confirm association
                        tags_response = lambda_client.list_tags(Resource=function['FunctionArn'])
                        tags = tags_response.get('Tags', {})
                        
                        # Check if tags indicate association with our ASG
                        if (tags.get('ASG') == asg_name or 
                            tags.get('AutoScalingGroup') == asg_name or
                            asg_name in tags.get('Purpose', '') or
                            asg_name in tags.get('Resource', '')):
                            
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
            
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up Lambda functions: {e}")
            return False
    
    def terminate_asg_instances(self, session: boto3.Session, asg_name: str, region: str) -> bool:
        """Terminate all instances in the ASG and wait for completion"""
        try:
            logger.info(f"Terminating instances in ASG: {asg_name}")
            
            autoscaling_client = session.client('autoscaling', region_name=region)
            ec2_client = session.client('ec2', region_name=region)
            
            # Get ASG details
            try:
                asg_response = autoscaling_client.describe_auto_scaling_groups(
                    AutoScalingGroupNames=[asg_name]
                )
                
                if not asg_response.get('AutoScalingGroups'):
                    logger.warning(f"ASG {asg_name} not found")
                    return True
                
                asg = asg_response['AutoScalingGroups'][0]
                instances = asg.get('Instances', [])
                
                if not instances:
                    logger.info(f"No instances found in ASG {asg_name}")
                    return True
                
                # Scale down ASG to 0
                logger.info(f"Scaling down ASG {asg_name} to 0 instances")
                autoscaling_client.update_auto_scaling_group(
                    AutoScalingGroupName=asg_name,
                    MinSize=0,
                    MaxSize=0,
                    DesiredCapacity=0
                )
                
                # Wait for instances to terminate
                instance_ids = [instance['InstanceId'] for instance in instances]
                logger.info(f"Waiting for instances to terminate: {instance_ids}")
                
                # Wait up to 10 minutes for instances to terminate
                max_wait_time = 600  # 10 minutes
                start_time = time.time()
                
                while time.time() - start_time < max_wait_time:
                    try:
                        instances_response = ec2_client.describe_instances(InstanceIds=instance_ids)
                        
                        running_instances = []
                        for reservation in instances_response['Reservations']:
                            for instance in reservation['Instances']:
                                if instance['State']['Name'] not in ['terminated', 'terminating']:
                                    running_instances.append(instance['InstanceId'])
                        
                        if not running_instances:
                            logger.info("All instances have been terminated")
                            return True
                        
                        logger.info(f"Still waiting for {len(running_instances)} instances to terminate...")
                        time.sleep(30)
                        
                    except ClientError as e:
                        if e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
                            logger.info("All instances have been terminated")
                            return True
                        else:
                            logger.warning(f"Error checking instance status: {e}")
                
                logger.warning("Timeout waiting for instances to terminate, proceeding anyway")
                return True
                
            except ClientError as e:
                logger.error(f"Error managing ASG instances: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Error terminating ASG instances: {e}")
            return False
    
    def delete_launch_template(self, session: boto3.Session, launch_template_id: str, region: str) -> bool:
        """Delete the launch template associated with the ASG"""
        try:
            if not launch_template_id:
                logger.info("No launch template ID provided")
                return True
                
            logger.info(f"Deleting launch template: {launch_template_id}")
            
            ec2_client = session.client('ec2', region_name=region)
            
            try:
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
    
    def cleanup_associated_resources(self, session: boto3.Session, asg_name: str, region: str) -> None:
        """Clean up additional resources associated with the ASG"""
        try:
            # Clean up CloudWatch log groups
            logs_client = session.client('logs', region_name=region)
            try:
                log_groups = logs_client.describe_log_groups()
                
                for log_group in log_groups.get('logGroups', []):
                    log_group_name = log_group['logGroupName']
                    if asg_name in log_group_name:
                        logger.info(f"Deleting log group: {log_group_name}")
                        logs_client.delete_log_group(logGroupName=log_group_name)
                        
            except ClientError as e:
                logger.warning(f"Error cleaning up log groups: {e}")
            
            # Clean up security groups tagged with ASG name
            ec2_client = session.client('ec2', region_name=region)
            try:
                security_groups = ec2_client.describe_security_groups(
                    Filters=[
                        {
                            'Name': 'tag:ASG',
                            'Values': [asg_name]
                        }
                    ]
                )
                
                for sg in security_groups.get('SecurityGroups', []):
                    sg_id = sg['GroupId']
                    if sg['GroupName'] != 'default':  # Don't delete default SG
                        logger.info(f"Deleting security group: {sg_id}")
                        try:
                            ec2_client.delete_security_group(GroupId=sg_id)
                        except ClientError as e:
                            logger.warning(f"Could not delete security group {sg_id}: {e}")
                            
            except ClientError as e:
                logger.warning(f"Error cleaning up security groups: {e}")
                
        except Exception as e:
            logger.error(f"Error during additional resource cleanup: {e}")

    def delete_asg(self, asg_data: Dict) -> bool:
        """Delete a single ASG with comprehensive cleanup"""
        try:
            # Handle the actual file structure
            created_asgs = asg_data.get('created_asgs', [])

            if not created_asgs:
                logger.error(f"No ASGs found in data: {asg_data.get('file_name', 'Unknown')}")
                return False

            # Process each ASG in the file (usually there's only one)
            all_success = True

            for asg_info in created_asgs:
                # Extract information from the actual structure
                account_name = asg_info.get('account_name')
                asg_name = asg_info.get('asg_name')
                region = asg_info.get('region')
                launch_template_id = asg_info.get('launch_template_id')

                if not all([account_name, asg_name, region]):
                    logger.error(f"Missing required information for ASG: {asg_info}")
                    all_success = False
                    continue

                logger.info(f"Starting comprehensive deletion of ASG: {asg_name}")
                logger.info(f"Account: {account_name}, Region: {region}")

                # Get AWS credentials
                access_key, secret_key = self.get_aws_credentials(account_name)
                if not access_key or not secret_key:
                    all_success = False
                    continue

                # Create boto3 session
                session = self.create_boto3_session(access_key, secret_key, region)
                autoscaling_client = session.client('autoscaling', region_name=region)

                # Check if ASG exists
                try:
                    asg_response = autoscaling_client.describe_auto_scaling_groups(
                        AutoScalingGroupNames=[asg_name]
                    )

                    if not asg_response.get('AutoScalingGroups'):
                        logger.info(f"ASG {asg_name} not found, cleaning up associated resources")
                        # Still run cleanup for associated resources
                        self.cleanup_monitoring_resources(session, asg_name, region)
                        self.cleanup_lambda_functions(session, asg_name, region)
                        self.delete_launch_template(session, launch_template_id, region)
                        continue

                except ClientError as e:
                    logger.error(f"Error checking ASG status: {e}")
                    all_success = False
                    continue

                # Step 1: Clean up monitoring resources
                logger.info("Step 1: Cleaning up monitoring resources...")
                if not self.cleanup_monitoring_resources(session, asg_name, region):
                    logger.warning("Some monitoring resources may not have been cleaned up properly")

                # Step 2: Clean up Lambda functions
                logger.info("Step 2: Cleaning up Lambda functions...")
                if not self.cleanup_lambda_functions(session, asg_name, region):
                    logger.warning("Some Lambda functions may not have been cleaned up properly")

                # Step 3: Clean up scaling policies and scheduled actions
                logger.info("Step 3: Cleaning up scaling policies...")
                if not self.cleanup_scaling_policies(session, asg_name, region):
                    logger.warning("Some scaling policies may not have been cleaned up properly")

                # Step 4: Terminate all instances
                logger.info("Step 4: Terminating ASG instances...")
                if not self.terminate_asg_instances(session, asg_name, region):
                    logger.error("Failed to terminate ASG instances")
                    all_success = False
                    continue

                # Step 5: Delete the ASG
                logger.info(f"Step 5: Deleting ASG: {asg_name}")
                try:
                    autoscaling_client.delete_auto_scaling_group(
                        AutoScalingGroupName=asg_name,
                        ForceDelete=True
                    )
                    logger.info(f"ASG {asg_name} deletion initiated")

                    # Wait for ASG deletion
                    logger.info("Waiting for ASG deletion to complete...")
                    max_wait_time = 300  # 5 minutes
                    start_time = time.time()

                    while time.time() - start_time < max_wait_time:
                        try:
                            asg_response = autoscaling_client.describe_auto_scaling_groups(
                                AutoScalingGroupNames=[asg_name]
                            )

                            if not asg_response.get('AutoScalingGroups'):
                                logger.info(f"ASG {asg_name} deleted successfully")
                                break

                            time.sleep(10)

                        except ClientError as e:
                            if 'does not exist' in str(e):
                                logger.info(f"ASG {asg_name} deleted successfully")
                                break
                            else:
                                logger.warning(f"Error checking ASG deletion status: {e}")

                except ClientError as e:
                    logger.error(f"Error deleting ASG: {e}")
                    all_success = False
                    continue

                # Step 6: Delete launch template
                logger.info("Step 6: Deleting launch template...")
                if not self.delete_launch_template(session, launch_template_id, region):
                    logger.warning("Launch template may not have been deleted properly")

                # Step 7: Clean up additional associated resources
                logger.info("Step 7: Cleaning up additional resources...")
                self.cleanup_associated_resources(session, asg_name, region)

                logger.info(f"ASG {asg_name} and associated resources deleted successfully")

            return all_success

        except Exception as e:
            logger.error(f"Error deleting ASG: {e}")
            return False

    def delete_asg_reference_file(self, file_path: str) -> bool:
        """Delete the ASG reference file after successful deletion"""
        try:
            if os.path.exists(file_path):
                # Create backup before deletion
                backup_path = file_path + '.deleted.' + str(int(time.time()))
                os.rename(file_path, backup_path)
                logger.info(f"ASG reference file moved to: {backup_path}")
                return True
            else:
                logger.warning(f"Reference file not found: {file_path}")
                return False
        except Exception as e:
            logger.error(f"Error handling reference file {file_path}: {e}")
            return False
    
    def run_cleanup(self) -> None:
        """Main method to run the cleanup process"""
        logger.info("Starting ASG Cleanup Process")
        
        # Scan for ASG files
        asg_files = self.scan_asg_files()
        if not asg_files:
            logger.info("No ASG files found")
            return
        
        # Group by day
        grouped_asgs = self.group_asgs_by_day(asg_files)
        
        # Display day options
        self.display_day_options(grouped_asgs)
        
        # Get user day selection
        selected_days = self.get_user_day_selection(grouped_asgs)
        
        # Collect ASGs from selected days
        selected_asgs = []
        for day in selected_days:
            selected_asgs.extend(grouped_asgs[day])
        
        if not selected_asgs:
            logger.info("No ASGs selected")
            return
        
        # Display ASG options
        self.display_asgs_for_selection(selected_asgs)
        
        # Get user ASG selection
        asgs_to_delete = self.get_user_asg_selection(selected_asgs)
        
        # Confirm deletion
        print(f"\nYou have selected {len(asgs_to_delete)} ASG(s) for deletion:")
        for asg in asgs_to_delete:
            asg_name = asg.get('asg_configuration', {}).get('name', 'N/A')
            account_name = asg.get('account_info', {}).get('account_name', 'N/A')
            print(f"  - {asg_name} (Account: {account_name})")
        
        print("\nThis will also delete:")
        print("  - All EC2 instances in the ASGs")
        print("  - Launch templates")
        print("  - Scaling policies and scheduled actions")
        print("  - Lambda functions for scaling")
        print("  - CloudWatch alarms and monitoring")
        print("  - SNS topics and notifications")
        print("  - Associated security groups and logs")
        
        confirm = input("\nAre you sure you want to delete these ASGs and all associated resources? (yes/no): ").strip().lower()
        if confirm != 'yes':
            logger.info("Deletion cancelled by user")
            return
        
        # Delete ASGs
        successful_deletions = 0
        failed_deletions = 0
        
        for i, asg in enumerate(asgs_to_delete, 1):
            asg_name = asg.get('asg_configuration', {}).get('name', 'Unknown')
            logger.info(f"Processing ASG {i}/{len(asgs_to_delete)}: {asg_name}")
            
            if self.delete_asg(asg):
                successful_deletions += 1
                # Delete reference file
                self.delete_asg_reference_file(asg.get('file_path', ''))
            else:
                failed_deletions += 1
            
            # Add delay between deletions
            if i < len(asgs_to_delete):
                logger.info("Waiting before next deletion...")
                time.sleep(10)
        
        # Summary
        logger.info("="*60)
        logger.info("ASG CLEANUP SUMMARY")
        logger.info("="*60)
        logger.info(f"Total ASGs processed: {len(asgs_to_delete)}")
        logger.info(f"Successfully deleted: {successful_deletions}")
        logger.info(f"Failed deletions: {failed_deletions}")
        logger.info("Resources cleaned up per ASG:")
        logger.info("  - Auto Scaling Group and instances")
        logger.info("  - Launch templates")
        logger.info("  - Scaling policies and scheduled actions")
        logger.info("  - Lambda functions for scaling")
        logger.info("  - CloudWatch alarms and monitoring")
        logger.info("  - SNS notifications")
        logger.info("  - Security groups and logs")
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
        manager = ASGCleanupManager()
        manager.run_cleanup()
        
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()