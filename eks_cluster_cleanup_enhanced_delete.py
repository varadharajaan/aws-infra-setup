#!/usr/bin/env python3
"""
Enhanced EKS Cluster Cleanup Script
This script reads EKS cluster reference files, groups them by creation date,
allows user selection, and deletes the selected clusters with comprehensive cleanup
including Prometheus scrapers and Lambda functions for node scheduling.
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
log_dir = "aws/eks"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/eks_cleanup_{timestamp}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EKSClusterManager:
    def __init__(self, base_path: str = "files/eks"):
        self.base_path = base_path
        self.aws_accounts_config = self.load_json_file("aws_accounts_config.json")
        self.users_mapping = self.load_json_file("user_mapping.json")
        self.cluster_files = []
        
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
    
    def scan_cluster_files(self) -> List[Dict]:
        """Scan all EKS cluster files in the directory structure"""
        cluster_files = []
        
        if not os.path.exists(self.base_path):
            logger.error(f"Base path does not exist: {self.base_path}")
            return cluster_files
        
        # Enhanced pattern to match both file formats
        patterns = [
            re.compile(r'eks_cluster_eks-cluster-.*_(\d{8}T\d{6}\.\d+)\.json$'),
            re.compile(r'eks_cluser.*\.json$')  # For typo in filename
        ]
        
        for account_dir in os.listdir(self.base_path):
            account_path = os.path.join(self.base_path, account_dir)
            if not os.path.isdir(account_path):
                continue
                
            eks_path = account_path
            
            if not os.path.exists(eks_path):
                continue
                
            for file_name in os.listdir(eks_path):
                matched = False
                timestamp_from_filename = None
                
                for pattern in patterns:
                    match = pattern.match(file_name)
                    if match:
                        matched = True
                        if match.groups():
                            timestamp_from_filename = match.group(1)
                        break
                
                if matched or file_name.startswith('eks_cluster') or file_name.startswith('eks_cluser'):
                    file_path = os.path.join(eks_path, file_name)
                    cluster_data = self.load_json_file(file_path)
                    
                    if cluster_data:
                        cluster_data['file_path'] = file_path
                        cluster_data['file_name'] = file_name
                        if timestamp_from_filename:
                            cluster_data['timestamp_from_filename'] = timestamp_from_filename
                        cluster_files.append(cluster_data)
        
        logger.info(f"Found {len(cluster_files)} cluster files")
        return cluster_files
    
    def group_clusters_by_day(self, cluster_files: List[Dict]) -> Dict[str, List[Dict]]:
        """Group cluster files by creation day"""
        grouped = defaultdict(list)
        
        for cluster in cluster_files:
            try:
                # Try to get timestamp from cluster data first, then from filename
                timestamp = cluster.get('timestamp') or cluster.get('timestamp_from_filename', '')
                
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
                
                grouped[day_key].append(cluster)
                
            except Exception as e:
                logger.warning(f"Error processing timestamp for {cluster.get('file_name', 'unknown')}: {e}")
                grouped["unknown"].append(cluster)
        
        return dict(grouped)
    
    def display_day_options(self, grouped_clusters: Dict[str, List[Dict]]) -> None:
        """Display available day options to user"""
        print("\n" + "="*60)
        print("AVAILABLE CLUSTER CREATION DAYS")
        print("="*60)
        
        sorted_days = sorted([day for day in grouped_clusters.keys() if day != "unknown"])
        if "unknown" in grouped_clusters:
            sorted_days.append("unknown")
        
        for i, day in enumerate(sorted_days, 1):
            count = len(grouped_clusters[day])
            print(f"Day-{i}: {day} ({count} clusters)")
        
        print(f"\nTotal days available: {len(sorted_days)}")
        print("="*60)
    
    def get_user_day_selection(self, grouped_clusters: Dict[str, List[Dict]]) -> List[str]:
        """Get user selection for days"""
        sorted_days = sorted([day for day in grouped_clusters.keys() if day != "unknown"])
        if "unknown" in grouped_clusters:
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
    
    def display_clusters_for_selection(self, clusters: List[Dict]) -> None:
        """Display clusters for user selection"""
        print("\n" + "="*80)
        print("AVAILABLE CLUSTERS FOR DELETION")
        print("="*80)
        
        for i, cluster in enumerate(clusters, 1):
            account_info = cluster.get('account_info', {})
            cluster_info = cluster.get('cluster_info', {})
            
            print(f"\nCluster-{i}:")
            print(f"  File: {cluster.get('file_name', 'N/A')}")
            print(f"  Cluster Name: {cluster_info.get('cluster_name', 'N/A')}")
            print(f"  Account: {account_info.get('account_name', 'N/A')}")
            print(f"  Region: {account_info.get('region', 'N/A')}")
            print(f"  Created By: {cluster.get('created_by', 'N/A')}")
            print(f"  Timestamp: {cluster.get('timestamp', 'N/A')}")
        
        print("="*80)

    def get_user_cluster_selection(self, clusters: List[Dict]) -> List[Dict]:
        """Get user selection for clusters to delete"""
        while True:
            print("\nCluster Selection Options:")
            print("1. Single cluster (e.g., 'cluster-1' or '1')")
            print("2. Multiple clusters (e.g., 'cluster-1,cluster-3' or '1,3')")
            print("3. Range of clusters (e.g., 'cluster-1-cluster-3' or '1-3')")
            print("4. All clusters ('all')")

            selection = input("\nEnter your selection: ").strip().lower()

            if selection == 'all':
                return clusters

            try:
                selected_clusters = []

                # Handle range (e.g., "1-3" or "cluster-1-cluster-3")
                if '-' in selection and not selection.startswith('cluster-'):
                    # Handle simple number range like "1-3"
                    parts = selection.split('-')
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        start_idx = int(parts[0]) - 1
                        end_idx = int(parts[1]) - 1
                        if 0 <= start_idx < len(clusters) and 0 <= end_idx < len(clusters):
                            selected_clusters = clusters[start_idx:end_idx + 1]
                elif 'cluster-' in selection and '-cluster-' in selection:
                    # Handle "cluster-1-cluster-3" format
                    match = re.match(r'cluster-(\d+)-cluster-(\d+)', selection)
                    if match:
                        start_idx = int(match.group(1)) - 1
                        end_idx = int(match.group(2)) - 1
                        if 0 <= start_idx < len(clusters) and 0 <= end_idx < len(clusters):
                            selected_clusters = clusters[start_idx:end_idx + 1]

                # Handle comma-separated values
                elif ',' in selection:
                    indices = []
                    valid_selection = True
                    for item in selection.split(','):
                        item = item.strip()
                        if item.startswith('cluster-'):
                            try:
                                idx = int(item.replace('cluster-', '')) - 1
                            except ValueError:
                                valid_selection = False
                                break
                        elif item.isdigit():
                            idx = int(item) - 1
                        else:
                            valid_selection = False
                            break

                        if 0 <= idx < len(clusters):
                            indices.append(idx)
                        else:
                            valid_selection = False
                            break

                    if valid_selection and indices:
                        selected_clusters = [clusters[idx] for idx in indices]

                # Handle single selection
                else:
                    if selection.startswith('cluster-'):
                        try:
                            idx = int(selection.replace('cluster-', '')) - 1
                        except ValueError:
                            print("Invalid format. Please try again.")
                            continue
                    elif selection.isdigit():
                        idx = int(selection) - 1
                    else:
                        print("Invalid format. Please try again.")
                        continue

                    if 0 <= idx < len(clusters):
                        selected_clusters = [clusters[idx]]
                    else:
                        print(f"Invalid selection. Please enter a number between 1 and {len(clusters)}.")
                        continue

                if selected_clusters:
                    return selected_clusters
                else:
                    print(
                        f"Invalid selection. Please enter a number between 1 and {len(clusters)}, or use the formats shown above.")

            except (ValueError, IndexError) as e:
                print(f"Invalid format. Please try again. Error: {e}")

    # Example usage based on your output:
    # If you want clusters 1-5: enter "1-5" or "cluster-1-cluster-5"
    # If you want clusters 1,3,5: enter "1,3,5" or "cluster-1,cluster-3,cluster-5"
    # If you want cluster 10: enter "10" or "cluster-10"
    # If you want all: enter "all"

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
    
    def cleanup_prometheus_scrapers(self, session: boto3.Session, cluster_name: str, region: str) -> bool:
        """Clean up Prometheus scrapers and related resources"""
        try:
            logger.info(f"Cleaning up Prometheus scrapers for cluster: {cluster_name}")
            
            # Clean up ECS services and tasks (if Prometheus is running on ECS)
            ecs_client = session.client('ecs', region_name=region)
            try:
                # List clusters
                clusters_response = ecs_client.list_clusters()
                for cluster_arn in clusters_response.get('clusterArns', []):
                    cluster_name_ecs = cluster_arn.split('/')[-1]
                    if cluster_name in cluster_name_ecs or 'prometheus' in cluster_name_ecs.lower():
                        
                        # List services in the cluster
                        services_response = ecs_client.list_services(cluster=cluster_arn)
                        for service_arn in services_response.get('serviceArns', []):
                            service_name = service_arn.split('/')[-1]
                            if cluster_name in service_name or 'prometheus' in service_name.lower():
                                logger.info(f"Deleting ECS service: {service_name}")
                                try:
                                    # Scale down to 0 first
                                    ecs_client.update_service(
                                        cluster=cluster_arn,
                                        service=service_arn,
                                        desiredCount=0
                                    )
                                    time.sleep(30)  # Wait for tasks to stop
                                    
                                    # Delete service
                                    ecs_client.delete_service(
                                        cluster=cluster_arn,
                                        service=service_arn
                                    )
                                except ClientError as e:
                                    logger.warning(f"Error deleting ECS service {service_name}: {e}")
                        
                        # Delete the cluster if it's empty
                        try:
                            ecs_client.delete_cluster(cluster=cluster_arn)
                            logger.info(f"Deleted ECS cluster: {cluster_name_ecs}")
                        except ClientError as e:
                            logger.warning(f"Error deleting ECS cluster {cluster_name_ecs}: {e}")
                            
            except ClientError as e:
                logger.warning(f"Error cleaning up ECS resources: {e}")
            
            # Clean up EC2 instances tagged with Prometheus and cluster name
            ec2_client = session.client('ec2', region_name=region)
            try:
                instances_response = ec2_client.describe_instances(
                    Filters=[
                        {
                            'Name': 'tag:Purpose',
                            'Values': ['prometheus', 'monitoring']
                        },
                        {
                            'Name': 'tag:Cluster',
                            'Values': [cluster_name]
                        },
                        {
                            'Name': 'instance-state-name',
                            'Values': ['running', 'stopped', 'stopping']
                        }
                    ]
                )
                
                instance_ids = []
                for reservation in instances_response['Reservations']:
                    for instance in reservation['Instances']:
                        instance_ids.append(instance['InstanceId'])
                
                if instance_ids:
                    logger.info(f"Terminating Prometheus EC2 instances: {instance_ids}")
                    ec2_client.terminate_instances(InstanceIds=instance_ids)
                    
            except ClientError as e:
                logger.warning(f"Error cleaning up EC2 instances: {e}")
            
            # Clean up Application Load Balancers
            elbv2_client = session.client('elbv2', region_name=region)
            try:
                albs_response = elbv2_client.describe_load_balancers()
                for alb in albs_response.get('LoadBalancers', []):
                    alb_name = alb['LoadBalancerName']
                    if cluster_name in alb_name or 'prometheus' in alb_name.lower():
                        logger.info(f"Deleting ALB: {alb_name}")
                        try:
                            elbv2_client.delete_load_balancer(LoadBalancerArn=alb['LoadBalancerArn'])
                        except ClientError as e:
                            logger.warning(f"Error deleting ALB {alb_name}: {e}")
                            
            except ClientError as e:
                logger.warning(f"Error cleaning up ALBs: {e}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up Prometheus scrapers: {e}")
            return False

    def cleanup_lambda_functions(self, session: boto3.Session, cluster_name: str, region: str) -> bool:
        """Clean up Lambda functions associated with node scheduling"""
        try:
            logger.info(f"Cleaning up Lambda functions for cluster: {cluster_name}")
            print(f"   🔍 Searching for Lambda functions related to cluster {cluster_name}...")

            # Extract cluster suffix for matching
            cluster_parts = cluster_name.split('-')
            if len(cluster_parts) >= 2:
                cluster_suffix = cluster_parts[-1]
            else:
                cluster_suffix = cluster_name

            logger.info(f"Using cluster suffix for matching: {cluster_suffix}")

            lambda_client = session.client('lambda', region_name=region)

            # List all Lambda functions (use paginator to handle large numbers)
            paginator = lambda_client.get_paginator('list_functions')

            deleted_functions = []
            for page in paginator.paginate():
                for function in page.get('Functions', []):
                    function_name = function['FunctionName']
                    function_arn = function['FunctionArn']

                    # Check if function is related to the cluster using suffix pattern
                    if (f"eks-scale-{cluster_suffix}" in function_name or
                            f"eks-down-{cluster_suffix}" in function_name or
                            f"eks-up-{cluster_suffix}" in function_name or
                            cluster_name in function_name or
                            cluster_suffix in function_name):

                        logger.info(f"Found potential matching Lambda function: {function_name}")

                        # Get function tags to confirm association when possible
                        try:
                            tags_response = lambda_client.list_tags(Resource=function_arn)
                            tags = tags_response.get('Tags', {})

                            # Additional confirmation via tags when available
                            tag_match = (tags.get('Cluster') == cluster_name or
                                         tags.get('cluster') == cluster_name or
                                         tags.get('ClusterSuffix') == cluster_suffix or
                                         cluster_name in tags.get('Purpose', '') or
                                         cluster_suffix in tags.get('Purpose', ''))

                            # Delete if name pattern matches or tags confirm association
                            if f"eks-scale-{cluster_suffix}" in function_name or tag_match:
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
                logger.info(f"Successfully deleted {len(deleted_functions)} Lambda functions: {deleted_functions}")
                print(f"   ✅ Deleted {len(deleted_functions)} Lambda functions related to cluster {cluster_name}")
            else:
                logger.info(f"No Lambda functions found for deletion related to cluster {cluster_name}")
                print(f"   ℹ️ No Lambda functions found related to cluster {cluster_name}")

            # Clean up CloudWatch Events/EventBridge rules with the same pattern
            events_client = session.client('events', region_name=region)
            try:
                # Try matching with cluster suffix patterns
                rule_prefixes = [
                    f"eks-scale-{cluster_suffix}",
                    f"eks-up-{cluster_suffix}",
                    f"eks-down-{cluster_suffix}",
                    cluster_name
                ]

                deleted_rules = []

                # Check for each potential rule prefix
                for prefix in rule_prefixes:
                    try:
                        rules_response = events_client.list_rules(NamePrefix=prefix)
                        for rule in rules_response.get('Rules', []):
                            rule_name = rule['Name']
                            logger.info(f"Found EventBridge rule: {rule_name}")

                            try:
                                # Remove targets first
                                targets_response = events_client.list_targets_by_rule(Rule=rule_name)
                                if targets_response.get('Targets'):
                                    target_ids = [target['Id'] for target in targets_response['Targets']]
                                    events_client.remove_targets(Rule=rule_name, Ids=target_ids)
                                    logger.info(f"Removed {len(target_ids)} targets from rule {rule_name}")

                                # Delete the rule
                                events_client.delete_rule(Name=rule_name)
                                deleted_rules.append(rule_name)
                                logger.info(f"Deleted EventBridge rule: {rule_name}")
                            except ClientError as e:
                                logger.warning(f"Error deleting EventBridge rule {rule_name}: {e}")
                    except ClientError as e:
                        logger.debug(f"No matching rules found for prefix {prefix}: {e}")

                if deleted_rules:
                    logger.info(f"Successfully deleted {len(deleted_rules)} EventBridge rules")
                    print(f"   ✅ Deleted {len(deleted_rules)} EventBridge rules related to cluster {cluster_name}")
                else:
                    logger.info("No relevant EventBridge rules found for deletion")

            except ClientError as e:
                logger.warning(f"Error cleaning up EventBridge rules: {e}")

            return True

        except Exception as e:
            logger.error(f"Error cleaning up Lambda functions: {e}")
            print(f"   ❌ Failed to clean up Lambda functions: {e}")
            return False


    def delete_all_event_rules(self, session, cluster_name, region):
        """
        Delete all EventBridge (CloudWatch Events) rules associated with the cluster.
        Particularly targeting rules matching the cluster suffix pattern.
        """
        try:
            # Create EventBridge client from session
            events_client = session.client('events', region_name=region)

            # Get cluster suffix for matching
            cluster_suffix = cluster_name.split('-')[-1]

            logger.info(f"Searching for EventBridge rules related to cluster {cluster_name} in region {region}")
            print(f"   🔍 Searching for EventBridge rules with suffix '{cluster_suffix}'...")

            # List all EventBridge rules
            paginator = events_client.get_paginator('list_rules')

            deleted_rules = []
            skipped_rules = []

            for page in paginator.paginate():
                for rule in page.get('Rules', []):
                    rule_name = rule['Name']
                    rule_arn = rule['Arn']

                    # Skip common/shared rules
                    if any(pattern in rule_name.lower() for pattern in [
                        'common-', 'shared-', 'global-', 'admin-', 'monitoring-',
                        'all-', 'master-', 'centrallogging', 'security'
                    ]):
                        logger.info(f"Skipping shared EventBridge rule: {rule_name}")
                        skipped_rules.append(rule_name)
                        continue

                    # Check if rule is related to this EKS cluster
                    is_cluster_related = False

                    # Method 1: Direct cluster name match
                    if cluster_name.lower() in rule_name.lower():
                        is_cluster_related = True

                    # Method 2: Check if rule has specific cluster suffix (eks-down-diox, eks-up-diox)
                    elif len(cluster_suffix) >= 3:
                        if (f"-{cluster_suffix}" in rule_name or
                                rule_name.lower().endswith(f"-{cluster_suffix}")):
                            is_cluster_related = True

                    # Method 3: Check rule tags
                    if not is_cluster_related:
                        try:
                            tags_response = events_client.list_tags_for_resource(ResourceARN=rule_arn)
                            tags = tags_response.get('Tags', [])

                            # Fix: Check if tags is a list or dict and handle accordingly
                            if isinstance(tags, list):
                                # Handle case where tags is a list of key-value dictionaries
                                for tag in tags:
                                    if isinstance(tag, dict):
                                        key = tag.get('Key', '').lower()
                                        value = tag.get('Value', '').lower()
                                        if ((key in ['cluster', 'clustername', 'eks-cluster'] and
                                             value == cluster_name.lower()) or
                                                key == f'kubernetes.io/cluster/{cluster_name.lower()}'):
                                            is_cluster_related = True
                                            break
                            elif isinstance(tags, dict):
                                # Handle case where tags is a dictionary
                                for key, value in tags.items():
                                    if ((key.lower() in ['cluster', 'clustername', 'eks-cluster'] and
                                         value.lower() == cluster_name.lower()) or
                                            key.lower() == f'kubernetes.io/cluster/{cluster_name.lower()}'):
                                        is_cluster_related = True
                                        break
                        except Exception as tag_error:
                            logger.warning(f"Could not check tags for EventBridge rule {rule_name}: {tag_error}")

                    if is_cluster_related:
                        logger.info(f"Deleting EventBridge rule {rule_name} related to cluster {cluster_name}")

                        try:
                            # First, remove any targets from the rule
                            targets_response = events_client.list_targets_by_rule(Rule=rule_name)
                            targets = targets_response.get('Targets', [])

                            if targets:
                                target_ids = [t['Id'] for t in targets]
                                events_client.remove_targets(Rule=rule_name, Ids=target_ids)
                                logger.info(f"Removed {len(target_ids)} targets from rule {rule_name}")

                            # Now delete the rule
                            events_client.delete_rule(Name=rule_name)
                            deleted_rules.append(rule_name)
                            logger.info(f"Successfully deleted EventBridge rule {rule_name}")
                        except Exception as delete_error:
                            logger.error(f"Failed to delete EventBridge rule {rule_name}: {delete_error}")

            if deleted_rules:
                logger.info(
                    f"Deleted {len(deleted_rules)} EventBridge rules for cluster {cluster_name}")
                print(
                    f"   ✅ Deleted {len(deleted_rules)} EventBridge rules for cluster {cluster_name}")
            else:
                logger.info(
                    f"No EventBridge rules found related to cluster {cluster_name}.")
                print(f"   ℹ️ No EventBridge rules found related to cluster {cluster_name}")

            return True

        except Exception as e:
            logger.error(f"Failed to delete EventBridge rules for cluster {cluster_name}: {e}")
            print(f"   ❌ Failed to delete EventBridge rules: {e}")
            return False


    def delete_node_groups(self, eks_client, cluster_name: str) -> bool:
        """Delete all node groups in the cluster"""
        try:
            # List node groups
            response = eks_client.list_nodegroups(clusterName=cluster_name)
            nodegroups = response.get('nodegroups', [])
            
            if not nodegroups:
                logger.info(f"No node groups found for cluster {cluster_name}")
                return True
            
            # Delete each node group
            for nodegroup in nodegroups:
                logger.info(f"Deleting node group: {nodegroup}")
                try:
                    eks_client.delete_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup
                    )
                    logger.info(f"Node group {nodegroup} deletion initiated")
                except ClientError as e:
                    logger.error(f"Error deleting node group {nodegroup}: {e}")
                    return False
            
            # Wait for node groups to be deleted
            logger.info("Waiting for node groups to be deleted...")
            for nodegroup in nodegroups:
                waiter = eks_client.get_waiter('nodegroup_deleted')
                try:
                    waiter.wait(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup,
                        WaiterConfig={
                            'Delay': 30,
                            'MaxAttempts': 60
                        }
                    )
                    logger.info(f"Node group {nodegroup} deleted successfully")
                except Exception as e:
                    logger.error(f"Error waiting for node group {nodegroup} deletion: {e}")
                    return False
            
            return True
            
        except ClientError as e:
            logger.error(f"Error managing node groups for cluster {cluster_name}: {e}")
            return False
    
    def delete_cluster_addons(self, eks_client, cluster_name: str) -> bool:
        """Delete all addons from the cluster"""
        try:
            # List addons
            response = eks_client.list_addons(clusterName=cluster_name)
            addons = response.get('addons', [])
            
            if not addons:
                logger.info(f"No addons found for cluster {cluster_name}")
                return True
            
            # Delete each addon
            for addon in addons:
                logger.info(f"Deleting addon: {addon}")
                try:
                    eks_client.delete_addon(
                        clusterName=cluster_name,
                        addonName=addon
                    )
                    logger.info(f"Addon {addon} deletion initiated")
                except ClientError as e:
                    logger.error(f"Error deleting addon {addon}: {e}")
                    # Continue with other addons
            
            # Wait a bit for addons to be deleted
            time.sleep(30)
            return True
            
        except ClientError as e:
            logger.error(f"Error managing addons for cluster {cluster_name}: {e}")
            return False
    
    def cleanup_associated_resources(self, session: boto3.Session, cluster_name: str, region: str) -> None:
        """Clean up resources associated with the cluster"""
        try:
            # Clean up CloudWatch log groups
            logs_client = session.client('logs', region_name=region)
            try:
                log_groups = logs_client.describe_log_groups(
                    logGroupNamePrefix=f'/aws/eks/{cluster_name}'
                )
                
                for log_group in log_groups.get('logGroups', []):
                    log_group_name = log_group['logGroupName']
                    logger.info(f"Deleting log group: {log_group_name}")
                    logs_client.delete_log_group(logGroupName=log_group_name)
                
                # Also check for Prometheus and Lambda log groups
                prometheus_log_groups = logs_client.describe_log_groups(
                    logGroupNamePrefix=f'/aws/lambda/{cluster_name}'
                )
                for log_group in prometheus_log_groups.get('logGroups', []):
                    log_group_name = log_group['logGroupName']
                    logger.info(f"Deleting Lambda log group: {log_group_name}")
                    logs_client.delete_log_group(logGroupName=log_group_name)
                    
            except ClientError as e:
                logger.warning(f"Error cleaning up log groups: {e}")
            
            # Clean up security groups (if they have cluster name in tags)
            ec2_client = session.client('ec2', region_name=region)
            try:
                security_groups = ec2_client.describe_security_groups(
                    Filters=[
                        {
                            'Name': 'tag:kubernetes.io/cluster/' + cluster_name,
                            'Values': ['owned']
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
            
            # Clean up CloudWatch alarms
            cloudwatch_client = session.client('cloudwatch', region_name=region)
            try:
                alarms = cloudwatch_client.describe_alarms(
                    AlarmNamePrefix=cluster_name
                )
                
                for alarm in alarms.get('MetricAlarms', []):
                    alarm_name = alarm['AlarmName']
                    logger.info(f"Deleting CloudWatch alarm: {alarm_name}")
                    cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                    
            except ClientError as e:
                logger.warning(f"Error cleaning up CloudWatch alarms: {e}")
                
        except Exception as e:
            logger.error(f"Error during resource cleanup: {e}")
    
    def delete_cluster(self, cluster_data: Dict) -> bool:
        """Delete a single EKS cluster with comprehensive cleanup"""
        try:
            account_info = cluster_data.get('account_info', {})
            cluster_info = cluster_data.get('cluster_info', {})
            
            account_name = account_info.get('account_name')
            cluster_name = cluster_info.get('cluster_name')
            region = account_info.get('region')
            
            if not all([account_name, cluster_name, region]):
                logger.error(f"Missing required information in cluster data: {cluster_data.get('file_name')}")
                return False
            
            logger.info(f"Starting comprehensive deletion of cluster: {cluster_name}")
            
            # Get AWS credentials
            access_key, secret_key = self.get_aws_credentials(account_name)
            if not access_key or not secret_key:
                return False
            
            # Create boto3 session
            session = self.create_boto3_session(access_key, secret_key, region)
            eks_client = session.client('eks', region_name=region)
            
            # Check if cluster exists
            try:
                cluster_response = eks_client.describe_cluster(name=cluster_name)
                cluster_status = cluster_response['cluster']['status']
                logger.info(f"Cluster {cluster_name} status: {cluster_status}")
                
                if cluster_status in ['DELETING', 'FAILED']:
                    logger.warning(f"Cluster {cluster_name} is already in {cluster_status} state")
                    # Still run cleanup for associated resources
                    self.cleanup_prometheus_scrapers(session, cluster_name, region)
                    self.cleanup_lambda_functions(session, cluster_name, region)
                    self.delete_all_event_rules(session, cluster_name, region)
                    return True

            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.info(f"Cluster {cluster_name} not found, cleaning up associated resources")
                    # Still run cleanup for associated resources
                    self.cleanup_prometheus_scrapers(session, cluster_name, region)
                    self.cleanup_lambda_functions(session, cluster_name, region)
                    self.delete_all_event_rules(session, cluster_name, region)
                    return True
                else:
                    logger.error(f"Error checking cluster status: {e}")
                    return False
            
            # Step 1: Clean up Prometheus scrapers
            logger.info("Step 1: Cleaning up Prometheus scrapers...")
            if not self.cleanup_prometheus_scrapers(session, cluster_name, region):
                logger.warning("Some Prometheus resources may not have been cleaned up properly")

            logger.info("Step 2: Cleaning up EventBridge rules...")
            if not self.delete_all_event_rules(session, cluster_name, region):
                logger.warning("Some EventBridge rules may not have been cleaned up properly")

            # Step 2: Clean up Lambda functions for node scheduling
            logger.info("Step 3: Cleaning up Lambda functions...")
            if not self.cleanup_lambda_functions(session, cluster_name, region):
                logger.warning("Some Lambda functions may not have been cleaned up properly")
            
            # Step 3: Delete addons
            logger.info("Step 4: Deleting cluster addons...")
            if not self.delete_cluster_addons(eks_client, cluster_name):
                logger.warning("Some addons may not have been deleted properly")
            
            # Step 4: Delete node groups
            logger.info("Step 5: Deleting node groups...")
            if not self.delete_node_groups(eks_client, cluster_name):
                logger.error("Failed to delete node groups")
                return False
            
            # Step 5: Delete the cluster
            logger.info(f"Step 6: Deleting EKS cluster: {cluster_name}")
            eks_client.delete_cluster(name=cluster_name)
            
            # Step 6: Wait for cluster deletion
            logger.info("Step 7: Waiting for cluster deletion to complete...")
            waiter = eks_client.get_waiter('cluster_deleted')
            try:
                waiter.wait(
                    name=cluster_name,
                    WaiterConfig={
                        'Delay': 30,
                        'MaxAttempts': 60
                    }
                )
                logger.info(f"Cluster {cluster_name} deleted successfully")
                
                # Step 7: Clean up associated resources
                logger.info("Step 8: Cleaning up remaining associated resources...")
                self.cleanup_associated_resources(session, cluster_name, region)
                
                return True
                
            except Exception as e:
                logger.error(f"Error waiting for cluster deletion: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting cluster: {e}")
            return False
    
    def delete_cluster_reference_file(self, file_path: str) -> bool:
        """Delete the cluster reference file after successful cluster deletion"""
        try:
            if os.path.exists(file_path):
                # Create backup before deletion
                backup_path = file_path + '.deleted.' + str(int(time.time()))
                os.rename(file_path, backup_path)
                logger.info(f"Cluster reference file moved to: {backup_path}")
                return True
            else:
                logger.warning(f"Reference file not found: {file_path}")
                return False
        except Exception as e:
            logger.error(f"Error handling reference file {file_path}: {e}")
            return False
    
    def run_cleanup(self) -> None:
        """Main method to run the cleanup process"""
        logger.info("Starting Enhanced EKS Cluster Cleanup Process")
        
        # Scan for cluster files
        cluster_files = self.scan_cluster_files()
        if not cluster_files:
            logger.info("No cluster files found")
            return
        
        # Group by day
        grouped_clusters = self.group_clusters_by_day(cluster_files)
        
        # Display day options
        self.display_day_options(grouped_clusters)
        
        # Get user day selection
        selected_days = self.get_user_day_selection(grouped_clusters)
        
        # Collect clusters from selected days
        selected_clusters = []
        for day in selected_days:
            selected_clusters.extend(grouped_clusters[day])
        
        if not selected_clusters:
            logger.info("No clusters selected")
            return
        
        # Display cluster options
        self.display_clusters_for_selection(selected_clusters)
        
        # Get user cluster selection
        clusters_to_delete = self.get_user_cluster_selection(selected_clusters)
        
        # Confirm deletion
        print(f"\nYou have selected {len(clusters_to_delete)} cluster(s) for deletion:")
        for cluster in clusters_to_delete:
            cluster_name = cluster.get('cluster_info', {}).get('cluster_name', 'N/A')
            account_name = cluster.get('account_info', {}).get('account_name', 'N/A')
            print(f"  - {cluster_name} (Account: {account_name})")
        
        print("\nThis will also delete:")
        print("  - Prometheus scrapers and monitoring resources")
        print("  - Lambda functions for node scheduling")
        print("  - Associated CloudWatch resources")
        print("  - Security groups and networking components")

        confirm = input("\nAre you sure you want to delete these clusters and all associated resources? (yes/no): ").strip().lower()
        if confirm != 'yes':
            logger.info("Deletion cancelled by user")
            return
        
        # Delete clusters
        successful_deletions = 0
        failed_deletions = 0
        
        for i, cluster in enumerate(clusters_to_delete, 1):
            cluster_name = cluster.get('cluster_info', {}).get('cluster_name', 'Unknown')
            logger.info(f"Processing cluster {i}/{len(clusters_to_delete)}: {cluster_name}")
            
            if self.delete_cluster(cluster):
                successful_deletions += 1
                # Delete reference file
                self.delete_cluster_reference_file(cluster.get('file_path', ''))
            else:
                failed_deletions += 1
            
            # Add delay between deletions
            if i < len(clusters_to_delete):
                logger.info("Waiting before next deletion...")
                time.sleep(10)
        
        # Summary
        logger.info("="*60)
        logger.info("ENHANCED CLEANUP SUMMARY")
        logger.info("="*60)
        logger.info(f"Total clusters processed: {len(clusters_to_delete)}")
        logger.info(f"Successfully deleted: {successful_deletions}")
        logger.info(f"Failed deletions: {failed_deletions}")
        logger.info("Resources cleaned up per cluster:")
        logger.info("  - EKS cluster and node groups")
        logger.info("  - Prometheus scrapers and monitoring")
        logger.info("  - Lambda functions for scheduling")
        logger.info("  - CloudWatch logs and alarms")
        logger.info("  - Security groups and networking")
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
        manager = EKSClusterManager()
        manager.run_cleanup()
        
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()