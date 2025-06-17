#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
import botocore

# Add this class at the top of the file, before the UltraEKSCleanupManager class
class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class UltraEKSCleanupManager:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize log file
        self.setup_detailed_logging()
        
        # Load configuration
        self.load_configuration()
        
        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_clusters': [],
            'deleted_nodegroups': [],
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/eks"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/eks directory
            self.log_filename = f"{log_dir}/ultra_eks_cleanup_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_eks_cleanup')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)
            
            # Log initial information
            self.operation_logger.info("=" * 100)
            self.operation_logger.info("🚨 ULTRA EKS CLEANUP SESSION STARTED 🚨")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config File: {self.config_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Simple logging operation"""
        if self.operation_logger:
            if level.upper() == 'INFO':
                self.operation_logger.info(message)
            elif level.upper() == 'WARNING':
                self.operation_logger.warning(message)
            elif level.upper() == 'ERROR':
                self.operation_logger.error(message)
            elif level.upper() == 'DEBUG':
                self.operation_logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")

    def delete_all_lambda_functions(self, access_key, secret_key, region, cluster_name):
        """Delete all Lambda functions that might be related to the EKS cluster."""
        try:
            lambda_client = boto3.client(
                'lambda',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Get all Lambda functions
            paginator = lambda_client.get_paginator('list_functions')
            
            deleted_functions = []
            
            # Extract meaningful parts from cluster name for better matching
            cluster_parts = self.extract_cluster_identifiers(cluster_name)
            
            for page in paginator.paginate():
                for function in page['Functions']:
                    function_name = function['FunctionName']
                    
                    # Check if function is related to EKS cluster
                    is_cluster_related = False
                    
                    # Method 1: Direct cluster name match (original logic)
                    if cluster_name.lower() in function_name.lower():
                        is_cluster_related = True
                    
                    # Method 2: Check if function name parts match cluster parts
                    if not is_cluster_related:
                        is_cluster_related = self.check_name_similarity(function_name, cluster_parts)
                    
                    # Method 3: Check for common EKS patterns
                    if not is_cluster_related:
                        eks_patterns = ['eks-scale', 'eks-autoscale', 'eks-node', 'eks-pod', 'eks-function']
                        for pattern in eks_patterns:
                            if pattern in function_name.lower():
                                # If it's an EKS-related function, check for shared identifiers
                                if any(part in function_name.lower() for part in cluster_parts if len(part) >= 4):
                                    is_cluster_related = True
                                    break
                    
                    # Method 4: Check function tags (existing logic)
                    if not is_cluster_related:
                        try:
                            tags_response = lambda_client.list_tags(Resource=function['FunctionArn'])
                            tags = tags_response.get('Tags', {})
                            
                            # Check for EKS-related tags
                            for key, value in tags.items():
                                if (cluster_name.lower() in str(value).lower() or 
                                    any(part in str(value).lower() for part in cluster_parts if len(part) >= 4) or
                                    'eks' in key.lower() or 
                                    key.lower() in ['kubernetes.io/cluster', 'alpha.eksctl.io/cluster-name']):
                                    is_cluster_related = True
                                    break
                        except Exception as tag_error:
                            self.log_operation('WARNING', f"Could not check tags for Lambda function {function_name}: {tag_error}")
                    
                    if is_cluster_related:
                        try:
                            self.log_operation('INFO', f"🗑️  Deleting Lambda function {function_name} related to cluster {cluster_name}")
                            lambda_client.delete_function(FunctionName=function_name)
                            deleted_functions.append(function_name)
                            self.log_operation('INFO', f"✅ Deleted Lambda function {function_name}")
                        except Exception as delete_error:
                            self.log_operation('ERROR', f"Failed to delete Lambda function {function_name}: {delete_error}")
            
            if deleted_functions:
                self.log_operation('INFO', f"Deleted {len(deleted_functions)} Lambda functions for cluster {cluster_name}")
            else:
                self.log_operation('INFO', f"No Lambda functions found related to cluster {cluster_name}")
                
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete Lambda functions for cluster {cluster_name}: {e}")
            return False

    def extract_cluster_identifiers(self, cluster_name):
        """Extract meaningful identifiers from cluster name for matching."""
        # Split by common separators and filter out common words
        import re
        
        # Split by hyphens, underscores, and dots
        parts = re.split(r'[-_.]', cluster_name.lower())
        
        # Filter out very common/generic parts
        generic_parts = {'eks', 'cluster', 'root', 'us', 'west', 'east', 'south', 'north', '1', '2', '3', '4', '5'}
        meaningful_parts = [part for part in parts if part not in generic_parts and len(part) >= 3]
        
        return meaningful_parts

    def check_name_similarity(self, function_name, cluster_parts):
        """Check if function name shares meaningful parts with cluster."""
        function_lower = function_name.lower()
        
        # Count how many cluster parts are found in the function name
        matching_parts = 0
        for part in cluster_parts:
            if part in function_lower:
                matching_parts += 1
        
        # If at least 1 meaningful part matches and it's an EKS function, consider it related
        if matching_parts >= 1 and 'eks' in function_lower:
            return True
        
        # If multiple parts match (even without 'eks' in name), it's likely related
        if matching_parts >= 2:
            return True
        
        return False

    def delete_all_iam_roles_policies(self, access_key, secret_key, region, cluster_name):
        """Delete IAM roles and policies related to the EKS cluster."""
        try:
            iam_client = boto3.client(
                'iam',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            deleted_roles = []
            deleted_policies = []
            
            # Get all IAM roles
            paginator = iam_client.get_paginator('list_roles')
            
            for page in paginator.paginate():
                for role in page['Roles']:
                    role_name = role['RoleName']
                    
                    # Check if role is related to EKS cluster
                    is_cluster_related = False
                    
                    if (cluster_name.lower() in role_name.lower() or 
                        'eks' in role_name.lower() or
                        'nodegroup' in role_name.lower()):
                        is_cluster_related = True
                    
                    # Also check role tags
                    try:
                        tags_response = iam_client.list_role_tags(RoleName=role_name)
                        tags = tags_response.get('Tags', [])
                        
                        for tag in tags:
                            if (cluster_name.lower() in str(tag.get('Value', '')).lower() or
                                tag.get('Key', '').lower() in ['kubernetes.io/cluster', 'alpha.eksctl.io/cluster-name']):
                                is_cluster_related = True
                                break
                    except Exception as tag_error:
                        self.log_operation('WARNING', f"Could not check tags for IAM role {role_name}: {tag_error}")
                    
                    if is_cluster_related:
                        try:
                            # Detach managed policies first
                            attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
                            for policy in attached_policies['AttachedPolicies']:
                                iam_client.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
                            
                            # Delete inline policies
                            inline_policies = iam_client.list_role_policies(RoleName=role_name)
                            for policy_name in inline_policies['PolicyNames']:
                                iam_client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                            
                            # Delete the role
                            self.log_operation('INFO', f"🗑️  Deleting IAM role {role_name} related to cluster {cluster_name}")
                            iam_client.delete_role(RoleName=role_name)
                            deleted_roles.append(role_name)
                            self.log_operation('INFO', f"✅ Deleted IAM role {role_name}")
                            
                        except Exception as delete_error:
                            self.log_operation('ERROR', f"Failed to delete IAM role {role_name}: {delete_error}")
            
            # Delete customer-managed policies related to the cluster
            policy_paginator = iam_client.get_paginator('list_policies')
            
            for page in policy_paginator.paginate(Scope='Local'):  # Only customer-managed policies
                for policy in page['Policies']:
                    policy_name = policy['PolicyName']
                    policy_arn = policy['Arn']
                    
                    if (cluster_name.lower() in policy_name.lower() or 
                        'eks' in policy_name.lower()):
                        try:
                            # Get all policy versions and delete non-default versions first
                            versions = iam_client.list_policy_versions(PolicyArn=policy_arn)['Versions']
                            for version in versions:
                                if not version['IsDefaultVersion']:
                                    iam_client.delete_policy_version(
                                        PolicyArn=policy_arn, 
                                        VersionId=version['VersionId']
                                    )
                            
                            # Delete the policy
                            self.log_operation('INFO', f"🗑️  Deleting IAM policy {policy_name} related to cluster {cluster_name}")
                            iam_client.delete_policy(PolicyArn=policy_arn)
                            deleted_policies.append(policy_name)
                            self.log_operation('INFO', f"✅ Deleted IAM policy {policy_name}")
                            
                        except Exception as delete_error:
                            self.log_operation('ERROR', f"Failed to delete IAM policy {policy_name}: {delete_error}")
            
            if deleted_roles or deleted_policies:
                self.log_operation('INFO', f"Deleted {len(deleted_roles)} IAM roles and {len(deleted_policies)} policies for cluster {cluster_name}")
            else:
                self.log_operation('INFO', f"No IAM roles/policies found related to cluster {cluster_name}")
                
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete IAM resources for cluster {cluster_name}: {e}")
            return False

    def delete_all_security_groups(self, access_key, secret_key, region, cluster_name, vpc_id):
        """Delete security groups related to the EKS cluster."""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            deleted_sgs = []
            
            # Get all security groups in the VPC
            response = ec2_client.describe_security_groups(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]}
                ]
            )
            
            for sg in response['SecurityGroups']:
                sg_id = sg['GroupId']
                sg_name = sg['GroupName']
                
                # Skip default security group
                if sg_name == 'default':
                    continue
                
                # Check if security group is related to EKS cluster
                is_cluster_related = False
                
                # Check security group name and description
                if (cluster_name.lower() in sg_name.lower() or
                    cluster_name.lower() in sg.get('Description', '').lower() or
                    'eks' in sg_name.lower() or
                    'eks' in sg.get('Description', '').lower()):
                    is_cluster_related = True
                
                # Check security group tags
                for tag in sg.get('Tags', []):
                    if (cluster_name.lower() in str(tag.get('Value', '')).lower() or
                        tag.get('Key', '').lower() in ['kubernetes.io/cluster', 'alpha.eksctl.io/cluster-name']):
                        is_cluster_related = True
                        break
                
                if is_cluster_related:
                    try:
                        self.log_operation('INFO', f"🗑️  Deleting security group {sg_id} ({sg_name}) related to cluster {cluster_name}")
                        ec2_client.delete_security_group(GroupId=sg_id)
                        deleted_sgs.append(sg_name)
                        self.log_operation('INFO', f"✅ Deleted security group {sg_id} ({sg_name})")
                        
                    except Exception as delete_error:
                        self.log_operation('ERROR', f"Failed to delete security group {sg_id}: {delete_error}")
            
            if deleted_sgs:
                self.log_operation('INFO', f"Deleted {len(deleted_sgs)} security groups for cluster {cluster_name}")
            else:
                self.log_operation('INFO', f"No security groups found related to cluster {cluster_name}")
                
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete security groups for cluster {cluster_name}: {e}")
            return False
    
    def delete_all_eks_addons(self, eks_client, cluster_name):
        """Delete all EKS add-ons attached to the cluster."""
        try:
            addons = eks_client.list_addons(clusterName=cluster_name).get('addons', [])
            for addon in addons:
                try:
                    eks_client.delete_addon(clusterName=cluster_name, addonName=addon)
                    self.log_operation('INFO', f"Deleting EKS add-on {addon} for {cluster_name}")
                    # Wait for deletion
                    for _ in range(30):
                        status = eks_client.describe_addon(clusterName=cluster_name, addonName=addon).get('addon',
                                                                                                          {}).get(
                            'status', '')
                        if status == 'DELETING':
                            time.sleep(10)
                        else:
                            break
                except botocore.exceptions.ClientError as e:
                    if 'ResourceNotFoundException' in str(e):
                        continue
                    self.log_operation('ERROR', f"Failed to delete add-on {addon} for {cluster_name}: {e}")
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete add-ons for {cluster_name}: {e}")
            return False

    def load_configuration(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            self.log_operation('INFO', f"✅ Configuration loaded from: {self.config_file}")
            
            # Validate accounts
            if 'accounts' not in self.config_data:
                raise ValueError("No 'accounts' section found in configuration")
            
            # Filter out incomplete accounts
            valid_accounts = {}
            for account_name, account_data in self.config_data['accounts'].items():
                if (account_data.get('access_key') and 
                    account_data.get('secret_key') and
                    account_data.get('account_id') and
                    not account_data.get('access_key').startswith('ADD_')):
                    valid_accounts[account_name] = account_data
                else:
                    self.log_operation('WARNING', f"Skipping incomplete account: {account_name}")
            
            self.config_data['accounts'] = valid_accounts
            
            self.log_operation('INFO', f"📊 Valid accounts loaded: {len(valid_accounts)}")
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                self.log_operation('INFO', f"   • {account_name}: {account_id} ({email})")
            
            # Get user regions
            self.user_regions = self.config_data.get('user_settings', {}).get('user_regions', [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
            ])
            
            self.log_operation('INFO', f"🌍 Regions to process: {self.user_regions}")
            
        except FileNotFoundError as e:
            self.log_operation('ERROR', f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation('ERROR', f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation('ERROR', f"Error loading configuration: {e}")
            sys.exit(1)

    def create_eks_client(self, access_key, secret_key, region):
        """Create EKS client using account credentials"""
        try:
            eks_client = boto3.client(
                'eks',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the connection
            eks_client.list_clusters()
            return eks_client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create EKS client for {region}: {e}")
            raise

    def get_all_clusters_in_region(self, eks_client, region, account_name):
        """Get all EKS clusters in a specific region"""
        try:
            clusters = []
            
            self.log_operation('INFO', f"🔍 Scanning for EKS clusters in {region} ({account_name})")
            print(f"   🔍 Scanning for EKS clusters in {region} ({account_name})...")
            
            cluster_names = eks_client.list_clusters()['clusters']
            
            if not cluster_names:
                self.log_operation('INFO', f"No EKS clusters found in {region} ({account_name})")
                print(f"   📦 No EKS clusters found in {region}")
                return []
                
            for cluster_name in cluster_names:
                try:
                    cluster_info = eks_client.describe_cluster(name=cluster_name)['cluster']
                    
                    # Extract relevant details
                    cluster_status = cluster_info.get('status', 'UNKNOWN')
                    created_at = cluster_info.get('createdAt', 'Unknown')
                    version = cluster_info.get('version', 'Unknown')
                    vpc_id = cluster_info.get('resourcesVpcConfig', {}).get('vpcId', 'Unknown')
                    
                    # Get node groups for this cluster
                    nodegroups = []
                    try:
                        nodegroup_names = eks_client.list_nodegroups(clusterName=cluster_name).get('nodegroups', [])
                        
                        for ng_name in nodegroup_names:
                            try:
                                ng_details = eks_client.describe_nodegroup(
                                    clusterName=cluster_name, 
                                    nodegroupName=ng_name
                                ).get('nodegroup', {})
                                
                                nodegroups.append({
                                    'name': ng_name,
                                    'status': ng_details.get('status', 'UNKNOWN'),
                                    'instance_types': ng_details.get('instanceTypes', []),
                                    'ami_type': ng_details.get('amiType', 'Unknown'),
                                    'created_at': ng_details.get('createdAt', 'Unknown'),
                                    'min_size': ng_details.get('scalingConfig', {}).get('minSize', 0),
                                    'max_size': ng_details.get('scalingConfig', {}).get('maxSize', 0),
                                    'desired_size': ng_details.get('scalingConfig', {}).get('desiredSize', 0),
                                })
                            except Exception as ng_error:
                                self.log_operation('WARNING', f"Could not get details for nodegroup {ng_name}: {str(ng_error)}")
                    except Exception as ng_list_error:
                        self.log_operation('WARNING', f"Could not list nodegroups for cluster {cluster_name}: {str(ng_list_error)}")
                    
                    cluster_data = {
                        'cluster_name': cluster_name,
                        'status': cluster_status,
                        'created_at': created_at,
                        'version': version,
                        'vpc_id': vpc_id,
                        'region': region,
                        'account_name': account_name,
                        'nodegroups': nodegroups
                    }
                    
                    clusters.append(cluster_data)
                    
                except Exception as cluster_error:
                    self.log_operation('ERROR', f"Error getting details for cluster {cluster_name}: {str(cluster_error)}")
            
            self.log_operation('INFO', f"📦 Found {len(clusters)} EKS clusters in {region} ({account_name})")
            print(f"   📦 Found {len(clusters)} EKS clusters in {region} ({account_name})")
            
            return clusters
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting EKS clusters in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting clusters in {region}: {e}")
            return []

    def delete_nodegroup(self, eks_client, cluster_name, nodegroup_name, region, account_name):
        """Delete an EKS nodegroup"""
        try:
            self.log_operation('INFO', f"🗑️  Deleting nodegroup {nodegroup_name} in cluster {cluster_name} ({region}, {account_name})")
            print(f"      🗑️  Deleting nodegroup {nodegroup_name} in cluster {cluster_name}...")
            
            # Delete the nodegroup
            eks_client.delete_nodegroup(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name
            )
            
            # Wait for nodegroup deletion to complete
            print(f"      ⏳ Waiting for nodegroup {nodegroup_name} deletion to complete...")
            self.log_operation('INFO', f"⏳ Waiting for nodegroup {nodegroup_name} deletion to complete...")
            
            waiter = True
            retry_count = 0
            max_retries = 60  # 30 minutes (30 * 60 seconds)
            
            while waiter and retry_count < max_retries:
                try:
                    response = eks_client.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup_name
                    )
                    status = response['nodegroup']['status']
                    
                    if status == 'DELETING':
                        self.log_operation('INFO', f"Nodegroup {nodegroup_name} status: {status} (Waiting...)")
                        time.sleep(30)  # Check every 30 seconds
                        retry_count += 1
                    else:
                        self.log_operation('WARNING', f"Unexpected nodegroup status: {status}")
                        break
                except ClientError as e:
                    if 'ResourceNotFoundException' in str(e):
                        self.log_operation('INFO', f"✅ Nodegroup {nodegroup_name} deleted successfully")
                        print(f"      ✅ Nodegroup {nodegroup_name} deleted successfully")
                        waiter = False
                    else:
                        self.log_operation('ERROR', f"Error checking nodegroup status: {e}")
                        raise
            
            if retry_count >= max_retries:
                self.log_operation('WARNING', f"Timed out waiting for nodegroup {nodegroup_name} deletion")
                print(f"      ⚠️ Timed out waiting for nodegroup {nodegroup_name} deletion")
            
            self.cleanup_results['deleted_nodegroups'].append({
                'nodegroup_name': nodegroup_name,
                'cluster_name': cluster_name,
                'region': region,
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete nodegroup {nodegroup_name}: {e}")
            print(f"      ❌ Failed to delete nodegroup {nodegroup_name}: {e}")
            
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'nodegroup',
                'resource_id': nodegroup_name,
                'cluster_name': cluster_name,
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def delete_cluster(self, eks_client, cluster_info):
        """Delete an EKS cluster with all its nodegroups"""
        try:
            cluster_name = cluster_info['cluster_name']
            region = cluster_info['region']
            account_name = cluster_info['account_name']
            nodegroups = cluster_info.get('nodegroups', [])
            
            self.log_operation('INFO', f"🗑️  Deleting EKS cluster {cluster_name} in {region} ({account_name})")
            print(f"   🗑️  Deleting EKS cluster {cluster_name} in {region} ({account_name})...")
            
            # Step 1: Delete all nodegroups first
            if nodegroups:
                self.log_operation('INFO', f"Found {len(nodegroups)} nodegroups to delete in cluster {cluster_name}")
                print(f"      Found {len(nodegroups)} nodegroups to delete in cluster {cluster_name}")
                
                for nodegroup in nodegroups:
                    nodegroup_name = nodegroup['name']
                    self.delete_nodegroup(eks_client, cluster_name, nodegroup_name, region, account_name)
            else:
                self.log_operation('INFO', f"No nodegroups found in cluster {cluster_name}")
                print(f"      No nodegroups found in cluster {cluster_name}")
            
            # Get account credentials from account data
            account_data = self.config_data['accounts'].get(account_name, {})
            access_key = account_data.get('access_key')
            secret_key = account_data.get('secret_key')

            
            # STEP 3: Delete all monitoring scrapers for this cluster
            self.delete_eks_scrapers(
                access_key,
                secret_key,
                region,
                cluster_name
            )
        
           #STEP 2: Delete all CloudWatch alarms for this cluster
            self.delete_all_cloudwatch_alarms(
                access_key,
                secret_key,
                region,
                cluster_name
            )

            # STEP 3: Delete Lambda functions related to this cluster
            self.delete_all_lambda_functions(
                access_key,
                .secret_key,
                region,
                cluster_name
            )

            # STEP 4: Delete IAM roles and policies related to this cluster
            self.delete_all_iam_roles_policies(
                access_key,
                secret_key,
                region,
                cluster_name
            )

            # STEP 5: Delete security groups related to this cluster
            if cluster_info.get('vpc_id') and cluster_info['vpc_id'] != 'Unknown':
                self.delete_all_security_groups(
                    access_key,
                    secret_key,
                    region,
                    cluster_name,
                    cluster_info['vpc_id']
                )

            # STEP 6: Delete all EKS add-ons for this cluster
            self.delete_all_eks_addons(eks_client, cluster_name)


            # Step 7: Delete the cluster itself
            self.log_operation('INFO', f"Deleting the cluster {cluster_name}...")
            print(f"   🗑️  Deleting the cluster {cluster_name}...")
            
            eks_client.delete_cluster(name=cluster_name)
            
            # Wait for cluster deletion to complete
            self.log_operation('INFO', f"⏳ Waiting for cluster {cluster_name} deletion to complete...")
            print(f"   ⏳ Waiting for cluster {cluster_name} deletion to complete...")
            
            waiter = True
            retry_count = 0
            max_retries = 120  # 60 minutes (120 * 30 seconds)
            
            while waiter and retry_count < max_retries:
                try:
                    response = eks_client.describe_cluster(name=cluster_name)
                    status = response['cluster']['status']
                    
                    if status == 'DELETING':
                        if retry_count % 10 == 0:  # Log every 5 minutes
                            self.log_operation('INFO', f"Cluster {cluster_name} status: {status} (Waiting...)")
                            print(f"   ⌛ Cluster {cluster_name} status: {status} (Still deleting...)")
                        time.sleep(30)  # Check every 30 seconds
                        retry_count += 1
                    else:
                        self.log_operation('WARNING', f"Unexpected cluster status: {status}")
                        break
                except ClientError as e:
                    if 'ResourceNotFoundException' in str(e) or 'ResourceNotFound' in str(e):
                        self.log_operation('INFO', f"✅ Cluster {cluster_name} deleted successfully")
                        print(f"   ✅ Cluster {cluster_name} deleted successfully")
                        waiter = False
                    else:
                        self.log_operation('ERROR', f"Error checking cluster status: {e}")
                        raise
            
            if retry_count >= max_retries:
                self.log_operation('WARNING', f"Timed out waiting for cluster {cluster_name} deletion")
                print(f"   ⚠️ Timed out waiting for cluster {cluster_name} deletion")
            
            self.cleanup_results['deleted_clusters'].append({
                'cluster_name': cluster_name,
                'version': cluster_info['version'],
                'vpc_id': cluster_info['vpc_id'],
                'region': region,
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete cluster {cluster_info['cluster_name']}: {e}")
            print(f"   ❌ Failed to delete cluster {cluster_info['cluster_name']}: {e}")
            
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'cluster',
                'resource_id': cluster_info['cluster_name'],
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False
###
    def delete_all_cloudwatch_alarms(self, access_key: str, secret_key: str, region: str, cluster_name: str) -> bool:
        """
        Delete all CloudWatch alarms associated with an EKS cluster
        This includes basic alarms, composite alarms, and cost alarms
        """
        try:
            self.log_operation('INFO', f"Starting deletion of all CloudWatch alarms for cluster {cluster_name}")
            print(f"🗑️  Deleting all CloudWatch alarms for cluster {cluster_name}...")
        
            # Create CloudWatch client
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        
            cloudwatch_client = session.client('cloudwatch')
        
            # Track deletion statistics
            total_deleted = 0
            failed_deletions = 0
        
            # Step 1: Find and delete composite alarms first (they depend on basic alarms)
            print(f"   🔍 Finding composite alarms for cluster {cluster_name}...")
            composite_deleted = self.delete_composite_alarms_for_cluster(cloudwatch_client, cluster_name)
            total_deleted += composite_deleted
        
            # Step 2: Find and delete basic metric alarms
            print(f"   🔍 Finding basic metric alarms for cluster {cluster_name}...")
            basic_deleted = self.delete_basic_alarms_for_cluster(cloudwatch_client, cluster_name)
            total_deleted += basic_deleted
        
            # Step 3: Find and delete cost alarms
            print(f"   🔍 Finding cost monitoring alarms for cluster {cluster_name}...")
            cost_deleted = self.delete_cost_alarms_for_cluster(cloudwatch_client, cluster_name)
            total_deleted += cost_deleted
        
            # Step 4: Find and delete any remaining alarms with cluster tags
            print(f"   🔍 Finding tagged alarms for cluster {cluster_name}...")
            tagged_deleted = self.delete_tagged_alarms_for_cluster(cloudwatch_client, cluster_name)
            total_deleted += tagged_deleted
        
            # Summary
            if total_deleted > 0:
                self.print_colored(Colors.GREEN, f"   ✅ Successfully deleted {total_deleted} CloudWatch alarms for {cluster_name}")
                self.log_operation('INFO', f"Successfully deleted {total_deleted} CloudWatch alarms for cluster {cluster_name}")
            else:
                self.print_colored(Colors.YELLOW, f"   ⚠️  No CloudWatch alarms found for cluster {cluster_name}")
                self.log_operation('INFO', f"No CloudWatch alarms found for cluster {cluster_name}")
        
            if failed_deletions > 0:
                self.print_colored(Colors.YELLOW, f"   ⚠️  {failed_deletions} alarms failed to delete")
                self.log_operation('WARNING', f"{failed_deletions} alarms failed to delete for cluster {cluster_name}")
        
            return failed_deletions == 0
        
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to delete CloudWatch alarms for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"   ❌ Failed to delete CloudWatch alarms: {error_msg}")
            return False
    def delete_composite_alarms_for_cluster(self, cloudwatch_client, cluster_name: str) -> int:
        """Delete composite alarms associated with the cluster"""
        try:
            deleted_count = 0
        
            # List all composite alarms (CloudWatch doesn't have direct filtering, so we get all and filter)
            paginator = cloudwatch_client.get_paginator('describe_alarms')
        
            # Get composite alarms
            for page in paginator.paginate(AlarmTypes=['CompositeAlarm']):
                composite_alarms = page.get('CompositeAlarms', [])
            
                cluster_composite_alarms = []
            
                for alarm in composite_alarms:
                    alarm_name = alarm['AlarmName']
                
                    # Check if alarm name contains cluster name or follows our naming convention
                    if self.is_cluster_related_alarm(alarm_name, cluster_name):
                        cluster_composite_alarms.append(alarm_name)
                        continue
                
                    # Check alarm description for cluster reference
                    alarm_description = alarm.get('AlarmDescription', '')
                    if cluster_name in alarm_description:
                        cluster_composite_alarms.append(alarm_name)
                        continue
            
                # Delete found composite alarms
                if cluster_composite_alarms:
                    print(f"      🗑️  Deleting {len(cluster_composite_alarms)} composite alarms...")
                
                    for alarm_name in cluster_composite_alarms:
                        try:
                            cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                            print(f"         ✅ Deleted composite alarm: {alarm_name}")
                            self.log_operation('INFO', f"Deleted composite alarm: {alarm_name}")
                            deleted_count += 1
                        
                            # Small delay to avoid throttling
                            time.sleep(0.1)
                        
                        except Exception as e:
                            print(f"         ❌ Failed to delete composite alarm {alarm_name}: {str(e)}")
                            self.log_operation('ERROR', f"Failed to delete composite alarm {alarm_name}: {str(e)}")
        
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting composite alarms: {str(e)}")
            return 0
    def delete_basic_alarms_for_cluster(self, cloudwatch_client, cluster_name: str) -> int:
        """Delete basic metric alarms associated with the cluster"""
        try:
            deleted_count = 0
        
            # List all metric alarms
            paginator = cloudwatch_client.get_paginator('describe_alarms')
        
            # Get metric alarms
            for page in paginator.paginate(AlarmTypes=['MetricAlarm']):
                metric_alarms = page.get('MetricAlarms', [])
            
                cluster_metric_alarms = []
            
                for alarm in metric_alarms:
                    alarm_name = alarm['AlarmName']
                
                    # Check if alarm name contains cluster name or follows our naming convention
                    if self.is_cluster_related_alarm(alarm_name, cluster_name):
                        cluster_metric_alarms.append(alarm_name)
                        continue
                
                    # Check alarm description for cluster reference
                    alarm_description = alarm.get('AlarmDescription', '')
                    if cluster_name in alarm_description:
                        cluster_metric_alarms.append(alarm_name)
                        continue
                
                    # Check dimensions for cluster name
                    dimensions = alarm.get('Dimensions', [])
                    for dimension in dimensions:
                        if dimension.get('Name') == 'ClusterName' and dimension.get('Value') == cluster_name:
                            cluster_metric_alarms.append(alarm_name)
                            break
                        elif dimension.get('Name') == 'NodegroupName' and cluster_name in dimension.get('Value', ''):
                            cluster_metric_alarms.append(alarm_name)
                            break
            
                # Delete found metric alarms in batches (CloudWatch allows up to 100 per call)
                if cluster_metric_alarms:
                    print(f"      🗑️  Deleting {len(cluster_metric_alarms)} metric alarms...")
                
                    # Delete in batches of 100
                    for i in range(0, len(cluster_metric_alarms), 100):
                        batch = cluster_metric_alarms[i:i+100]
                    
                        try:
                            cloudwatch_client.delete_alarms(AlarmNames=batch)
                        
                            for alarm_name in batch:
                                print(f"         ✅ Deleted metric alarm: {alarm_name}")
                                self.log_operation('INFO', f"Deleted metric alarm: {alarm_name}")
                                deleted_count += 1
                        
                            # Small delay between batches to avoid throttling
                            time.sleep(0.5)
                        
                        except Exception as e:
                            print(f"         ❌ Failed to delete batch of metric alarms: {str(e)}")
                            self.log_operation('ERROR', f"Failed to delete batch of metric alarms: {str(e)}")
                        
                            # Try individual deletion for this batch
                            for alarm_name in batch:
                                try:
                                    cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                                    print(f"         ✅ Deleted metric alarm (individual): {alarm_name}")
                                    self.log_operation('INFO', f"Deleted metric alarm (individual): {alarm_name}")
                                    deleted_count += 1
                                except Exception as individual_error:
                                    print(f"         ❌ Failed to delete metric alarm {alarm_name}: {str(individual_error)}")
                                    self.log_operation('ERROR', f"Failed to delete metric alarm {alarm_name}: {str(individual_error)}")
        
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting metric alarms: {str(e)}")
            return 0
    def delete_cost_alarms_for_cluster(self, cloudwatch_client, cluster_name: str) -> int:
        """Delete cost monitoring alarms associated with the cluster"""
        try:
            deleted_count = 0
        
            # List all metric alarms
            paginator = cloudwatch_client.get_paginator('describe_alarms')
        
            # Get metric alarms
            for page in paginator.paginate(AlarmTypes=['MetricAlarm']):
                metric_alarms = page.get('MetricAlarms', [])
            
                cost_alarms = []
            
                for alarm in metric_alarms:
                    alarm_name = alarm['AlarmName']
                
                    # Check for cost-related alarm names
                    if self.is_cost_alarm_for_cluster(alarm_name, cluster_name):
                        cost_alarms.append(alarm_name)
                        continue
                
                    # Check if it's a billing alarm with cluster reference
                    namespace = alarm.get('Namespace', '')
                    metric_name = alarm.get('MetricName', '')
                
                    if namespace == 'AWS/Billing' and metric_name == 'EstimatedCharges':
                        alarm_description = alarm.get('AlarmDescription', '')
                        if cluster_name in alarm_description:
                            cost_alarms.append(alarm_name)
            
                # Delete found cost alarms
                if cost_alarms:
                    print(f"      🗑️  Deleting {len(cost_alarms)} cost monitoring alarms...")
                
                    for alarm_name in cost_alarms:
                        try:
                            cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                            print(f"         ✅ Deleted cost alarm: {alarm_name}")
                            self.log_operation('INFO', f"Deleted cost alarm: {alarm_name}")
                            deleted_count += 1
                        
                            # Small delay to avoid throttling
                            time.sleep(0.1)
                        
                        except Exception as e:
                            print(f"         ❌ Failed to delete cost alarm {alarm_name}: {str(e)}")
                            self.log_operation('ERROR', f"Failed to delete cost alarm {alarm_name}: {str(e)}")
        
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting cost alarms: {str(e)}")
            return 0
    def is_cluster_related_alarm(self, alarm_name: str, cluster_name: str) -> bool:
        """Check if an alarm name is related to the specified cluster"""
        # Direct cluster name match
        if cluster_name in alarm_name:
            return True
    
        # Common alarm naming patterns
        alarm_patterns = [
            f"{cluster_name}-",
            f"-{cluster_name}-",
            f"-{cluster_name}",
            cluster_name.replace("-", "_"),
            cluster_name.replace("_", "-")
        ]
    
        for pattern in alarm_patterns:
            if pattern in alarm_name:
                return True
    
        # Check for cluster suffix patterns (last part of cluster name)
        cluster_suffix = cluster_name.split('-')[-1]
        if len(cluster_suffix) >= 4:  # Only check suffixes that are meaningful
            suffix_patterns = [
                f"-{cluster_suffix}-",
                f"-{cluster_suffix}",
                f"{cluster_suffix}-"
            ]
        
            for pattern in suffix_patterns:
                if pattern in alarm_name:
                    return True
    
        return False
    def is_cost_alarm_for_cluster(self, alarm_name: str, cluster_name: str) -> bool:
        """Check if an alarm is a cost alarm for the specified cluster"""
        # Cost alarm naming patterns
        cost_patterns = [
            f"{cluster_name}-daily-cost",
            f"{cluster_name}-cost",
            f"{cluster_name}-ec2-cost",
            f"{cluster_name}-ebs-cost",
            f"cost-{cluster_name}",
            f"billing-{cluster_name}"
        ]
    
        alarm_name_lower = alarm_name.lower()
    
        for pattern in cost_patterns:
            if pattern.lower() in alarm_name_lower:
                return True
    
        # Check for cluster suffix in cost alarms
        cluster_suffix = cluster_name.split('-')[-1]
        if len(cluster_suffix) >= 4:
            suffix_cost_patterns = [
                f"{cluster_suffix}-daily-cost",
                f"{cluster_suffix}-cost",
                f"cost-{cluster_suffix}"
            ]
        
            for pattern in suffix_cost_patterns:
                if pattern.lower() in alarm_name_lower:
                    return True
    
        return False
    def print_colored(self, color, message):
        """Print a message with color"""
        try:
            print(f"{color}{message}{Colors.END}")
        except Exception:
            # Fallback if color codes aren't supported
            print(message)

# Fix the delete_tagged_alarms_for_cluster method
    def delete_tagged_alarms_for_cluster(self, cloudwatch_client, cluster_name: str) -> int:
        """Delete alarms that are tagged with the cluster name"""
        try:
            deleted_count = 0
        
            # Get all alarms (both metric and composite)
            all_alarms = []
        
            # Get metric alarms
            paginator = cloudwatch_client.get_paginator('describe_alarms')
            for page in paginator.paginate(AlarmTypes=['MetricAlarm']):
                metric_alarms = page.get('MetricAlarms', [])
                all_alarms.extend([alarm['AlarmArn'] for alarm in metric_alarms])
        
            # Get composite alarms
            for page in paginator.paginate(AlarmTypes=['CompositeAlarm']):
                composite_alarms = page.get('CompositeAlarms', [])
                all_alarms.extend([alarm['AlarmArn'] for alarm in composite_alarms])
        
            if not all_alarms:
                return 0
        
            # Check tags for each alarm individually (corrected approach)
            tagged_alarms = []
        
            for resource_arn in all_alarms:
                try:
                    # Use the correct parameter name: ResourceARN (not ResourceARNList)
                    response = cloudwatch_client.list_tags_for_resource(
                        ResourceARN=resource_arn
                    )
                
                    tags = response.get('Tags', [])
                
                    # Check if any tag references the cluster
                    for tag in tags:
                        tag_key = tag.get('Key', '')
                        tag_value = tag.get('Value', '')
                    
                        if (tag_key == 'Cluster' and tag_value == cluster_name) or \
                           (cluster_name in tag_value) or \
                           (tag_key == 'ClusterName' and tag_value == cluster_name):
                        
                            # Extract alarm name from ARN
                            alarm_name = resource_arn.split(':')[-1]
                            tagged_alarms.append(alarm_name)
                            break
                
                    # Small delay between tag requests
                    time.sleep(0.05)
                
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to check tags for alarm {resource_arn.split(':')[-1]}: {str(e)}")
        
            # Delete tagged alarms
            if tagged_alarms:
                print(f"      🗑️  Deleting {len(tagged_alarms)} tagged alarms...")
            
                for alarm_name in tagged_alarms:
                    try:
                        cloudwatch_client.delete_alarms(AlarmNames=[alarm_name])
                        print(f"         ✅ Deleted tagged alarm: {alarm_name}")
                        self.log_operation('INFO', f"Deleted tagged alarm: {alarm_name}")
                        deleted_count += 1
                    
                        # Small delay to avoid throttling
                        time.sleep(0.1)
                    
                    except Exception as e:
                        print(f"         ❌ Failed to delete tagged alarm {alarm_name}: {str(e)}")
                        self.log_operation('ERROR', f"Failed to delete tagged alarm {alarm_name}: {str(e)}")
        
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting tagged alarms: {str(e)}")
            return 0

    def delete_eks_scrapers(self, access_key, secret_key, region, cluster_name):
        """
        Delete all monitoring scrapers/collectors attached to the EKS cluster
        This includes Prometheus scrapers, CloudWatch agents, and custom monitoring solutions
        """
        try:
            self.log_operation('INFO', f"🔍 Identifying monitoring scrapers for cluster {cluster_name}")
            print(f"   🔍 Identifying monitoring scrapers for cluster {cluster_name}...")
        
            # Create session with the provided credentials
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        
            # Check and delete CloudWatch Container Insights
            deleted_count = self.delete_cloudwatch_container_insights(session, cluster_name, region)
        
            # Check and delete Prometheus scrapers
            prometheus_count = self.delete_prometheus_scrapers(session, cluster_name, region)
            deleted_count += prometheus_count
        
            # Check and delete other common monitoring solutions
            other_count = self.delete_other_monitoring_solutions(session, cluster_name, region)
            deleted_count += other_count
        
            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   ✅ Successfully removed {deleted_count} monitoring scrapers for {cluster_name}")
                self.log_operation('INFO', f"Successfully removed {deleted_count} monitoring scrapers for cluster {cluster_name}")
            else:
                self.print_colored(Colors.YELLOW, f"   ℹ️ No active monitoring scrapers found for cluster {cluster_name}")
                self.log_operation('INFO', f"No active monitoring scrapers found for cluster {cluster_name}")
            
            return True
    
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to remove monitoring scrapers for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"   ❌ Failed to remove monitoring scrapers: {error_msg}")
            return False

    def delete_cloudwatch_container_insights(self, session, cluster_name, region):
        """Delete AWS CloudWatch Container Insights for the specified cluster"""
        deleted_count = 0
        try:
            # Check if Container Insights is enabled for this cluster
            cloudwatch = session.client('cloudwatch')
            logs_client = session.client('logs')
        
            # Look for Container Insights log groups
            log_group_prefixes = [
                f"/aws/containerinsights/{cluster_name}/",
                f"/aws/eks/{cluster_name}/",
                f"/aws/eks/containerinsights/{cluster_name}/"
            ]
        
            for prefix in log_group_prefixes:
                try:
                    response = logs_client.describe_log_groups(
                        logGroupNamePrefix=prefix,
                        limit=50
                    )
                
                    for log_group in response.get('logGroups', []):
                        log_group_name = log_group.get('logGroupName')
                        try:
                            logs_client.delete_log_group(logGroupName=log_group_name)
                            print(f"      ✅ Deleted Container Insights log group: {log_group_name}")
                            self.log_operation('INFO', f"Deleted Container Insights log group: {log_group_name}")
                            deleted_count += 1
                        except Exception as e:
                            print(f"      ❌ Failed to delete log group {log_group_name}: {str(e)}")
                            self.log_operation('ERROR', f"Failed to delete log group {log_group_name}: {str(e)}")
                except Exception as e:
                    self.log_operation('WARNING', f"Error checking log groups with prefix {prefix}: {str(e)}")
        
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting Container Insights: {str(e)}")
            return deleted_count

    def delete_prometheus_scrapers(self, session, cluster_name, region):
        """Delete AWS Managed Prometheus scrapers for the specified cluster"""
        deleted_count = 0
        try:
            # Check if AMP (Amazon Managed Prometheus) is being used
            try:
                amp_client = session.client('amp')  # Amazon Managed Prometheus
            
                # List workspaces
                workspaces = amp_client.list_workspaces().get('workspaces', [])
            
                for workspace in workspaces:
                    # Check if this workspace is used for the cluster
                    workspace_id = workspace.get('workspaceId')
                    workspace_arn = workspace.get('arn')
                
                    # Check workspace tags for the cluster name
                    try:
                        tags = amp_client.list_tags_for_resource(resourceArn=workspace_arn).get('tags', {})
                    
                        if any(cluster_name.lower() in str(tag).lower() for tag in tags.values()):
                            # This workspace is likely monitoring our cluster
                            try:
                                amp_client.delete_workspace(workspaceId=workspace_id)
                                print(f"      ✅ Deleted Prometheus workspace: {workspace_id}")
                                self.log_operation('INFO', f"Deleted Prometheus workspace: {workspace_id}")
                                deleted_count += 1
                            except Exception as del_err:
                                print(f"      ❌ Failed to delete Prometheus workspace {workspace_id}: {str(del_err)}")
                                self.log_operation('ERROR', f"Failed to delete Prometheus workspace {workspace_id}: {str(del_err)}")
                    except Exception as tag_err:
                        self.log_operation('WARNING', f"Failed to check tags for workspace {workspace_id}: {str(tag_err)}")
        
            except Exception as amp_err:
                # AMP might not be available in this region
                self.log_operation('DEBUG', f"AMP check failed (might not be available): {str(amp_err)}")
        
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting Prometheus scrapers: {str(e)}")
            return deleted_count

    def delete_other_monitoring_solutions(self, session, cluster_name, region):
        """Delete other common monitoring solutions that might be attached to the cluster"""
        deleted_count = 0
        try:
            # Check and delete related EventBridge rules
            events_client = session.client('events')
        
            try:
                # List rules that might be related to cluster monitoring
                rules = events_client.list_rules().get('Rules', [])
            
                for rule in rules:
                    rule_name = rule.get('Name')
                
                    # Check if the rule name contains the cluster name
                    if cluster_name.lower() in rule_name.lower():
                        # This rule is likely related to our cluster
                        try:
                            # First, remove targets
                            targets = events_client.list_targets_by_rule(Rule=rule_name).get('Targets', [])
                            if targets:
                                target_ids = [t.get('Id') for t in targets]
                                events_client.remove_targets(Rule=rule_name, Ids=target_ids)
                        
                            # Then delete the rule
                            events_client.delete_rule(Name=rule_name)
                            print(f"      ✅ Deleted EventBridge rule: {rule_name}")
                            self.log_operation('INFO', f"Deleted EventBridge rule: {rule_name}")
                            deleted_count += 1
                        except Exception as rule_err:
                            print(f"      ❌ Failed to delete EventBridge rule {rule_name}: {str(rule_err)}")
                            self.log_operation('ERROR', f"Failed to delete EventBridge rule {rule_name}: {str(rule_err)}")
            except Exception as events_err:
                self.log_operation('WARNING', f"Failed to check EventBridge rules: {str(events_err)}")
            
            return deleted_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting other monitoring solutions: {str(e)}")
            return deleted_count

###
    def cleanup_account_region(self, account_name, account_data, region):
        """Clean up all EKS resources in a specific account and region"""
        try:
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            account_id = account_data['account_id']
        
            self.log_operation('INFO', f"🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
            print(f"\n🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
        
            # Create EKS client
            try:
                eks_client = self.create_eks_client(access_key, secret_key, region)
            except Exception as client_error:
                self.log_operation('ERROR', f"Could not create EKS client for {region}: {client_error}")
                print(f"   ❌ Could not create EKS client for {region}: {client_error}")
                return False
        
            # Get all EKS clusters
            clusters = self.get_all_clusters_in_region(eks_client, region, account_name)
        
            if not clusters:
                self.log_operation('INFO', f"No EKS clusters found in {account_name} ({region})")
                print(f"   ✓ No EKS clusters found in {account_name} ({region})")
                return True
        
            # Record region summary
            region_summary = {
                'account_name': account_name,
                'account_id': account_id,
                'region': region,
                'clusters_found': len(clusters),
                'nodegroups_found': sum(len(cluster.get('nodegroups', [])) for cluster in clusters)
            }
            self.cleanup_results['regions_processed'].append(region_summary)
        
            # Add account to processed accounts if not already there
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({
                    'account_name': account_name,
                    'account_id': account_id
                })
        
            # Delete each cluster
            for cluster in clusters:
                self.delete_cluster(eks_client, cluster)
        
            self.log_operation('INFO', f"✅ Cleanup completed for {account_name} ({region})")
            print(f"   ✅ Cleanup completed for {account_name} ({region})")
            return True
        
        except Exception as e:
            self.log_operation('ERROR', f"Error cleaning up {account_name} ({region}): {e}")
            print(f"   ❌ Error cleaning up {account_name} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return False

    def parse_selection(self, selection: str, max_count: int) -> list:
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

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_dir = "aws/eks/reports"
            os.makedirs(report_dir, exist_ok=True)
            report_filename = f"{report_dir}/ultra_eks_cleanup_report_{self.execution_timestamp}.json"
            
            # Calculate statistics
            total_clusters_deleted = len(self.cleanup_results['deleted_clusters'])
            total_nodegroups_deleted = len(self.cleanup_results['deleted_nodegroups'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])
            
            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for cluster in self.cleanup_results['deleted_clusters']:
                account = cluster['account_name']
                region = cluster['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'clusters': 0, 'nodegroups': 0}
                deletions_by_account[account]['clusters'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'clusters': 0, 'nodegroups': 0}
                deletions_by_region[region]['clusters'] += 1
            
            for nodegroup in self.cleanup_results['deleted_nodegroups']:
                account = nodegroup['account_name']
                region = nodegroup['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'clusters': 0, 'nodegroups': 0}
                deletions_by_account[account]['nodegroups'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'clusters': 0, 'nodegroups': 0}
                deletions_by_region[region]['nodegroups'] += 1
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_EKS_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_file": self.config_file,
                    "log_file": self.log_filename,
                    "accounts_in_config": list(self.config_data['accounts'].keys()),
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(self.cleanup_results['accounts_processed']),
                    "total_regions_processed": len(self.cleanup_results['regions_processed']),
                    "total_clusters_deleted": total_clusters_deleted,
                    "total_nodegroups_deleted": total_nodegroups_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results['accounts_processed'],
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_clusters": self.cleanup_results['deleted_clusters'],
                    "deleted_nodegroups": self.cleanup_results['deleted_nodegroups'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"✅ Ultra cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save ultra cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA EKS CLEANUP SESSION 🚨")
            
            print("🚨" * 30)
            print("💥 ULTRA EKS CLEANUP - SEQUENTIAL 💥")
            print("🚨" * 30)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📋 Log File: {self.log_filename}")
            
            # STEP 1: Display available accounts and select accounts to process
            accounts = self.config_data['accounts']
            
            print(f"\n🏦 AVAILABLE AWS ACCOUNTS:")
            print("=" * 80)
            
            account_list = []
            
            for i, (account_name, account_data) in enumerate(accounts.items(), 1):
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                
                account_list.append({
                    'name': account_name,
                    'account_id': account_id,
                    'email': email,
                    'data': account_data
                })
                
                print(f"  {i}. {account_name}: {account_id} ({email})")
            
            # Selection prompt
            print("\nAccount Selection Options:")
            print("  • Single accounts: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-2,4")
            print("  • All accounts: 'all' or press Enter")
            print("  • Cancel: 'cancel' or 'quit'")
            
            selection = input("\n🔢 Select accounts to process: ").strip().lower()
            
            if selection in ['cancel', 'quit']:
                self.log_operation('INFO', "EKS cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Process account selection
            selected_accounts = {}
            if not selection or selection == 'all':
                selected_accounts = accounts
                self.log_operation('INFO', f"All accounts selected: {len(accounts)}")
                print(f"✅ Selected all {len(accounts)} accounts")
            else:
                try:
                    # Parse selection
                    parts = []
                    for part in selection.split(','):
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            if start < 1 or end > len(account_list):
                                raise ValueError(f"Range {part} out of bounds (1-{len(account_list)})")
                            parts.extend(range(start, end + 1))
                        else:
                            num = int(part)
                            if num < 1 or num > len(account_list):
                                raise ValueError(f"Selection {part} out of bounds (1-{len(account_list)})")
                            parts.append(num)
                    
                    # Get selected account data
                    for idx in parts:
                        account = account_list[idx-1]
                        selected_accounts[account['name']] = account['data']
                    
                    if not selected_accounts:
                        raise ValueError("No valid accounts selected")
                    
                    self.log_operation('INFO', f"Selected accounts: {list(selected_accounts.keys())}")
                    print(f"✅ Selected {len(selected_accounts)} accounts: {', '.join(selected_accounts.keys())}")
                    
                except ValueError as e:
                    self.log_operation('ERROR', f"Invalid account selection: {e}")
                    print(f"❌ Invalid selection: {e}")
                    return
            
            regions = self.user_regions
            
            # STEP 2: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(regions)
            
            print(f"\n🎯 CLEANUP CONFIGURATION")
            print("=" * 80)
            print(f"🏦 Selected accounts: {len(selected_accounts)}")
            print(f"🌍 Regions per account: {len(regions)}")
            print(f"📋 Total operations: {total_operations}")
            print("=" * 80)
            
            # Simplified confirmation process
            print(f"\n⚠️  WARNING: This will delete ALL EKS clusters and nodegroups")
            print(f"    across {len(selected_accounts)} accounts in {len(regions)} regions ({total_operations} operations)")
            print(f"    This action CANNOT be undone!")
            
            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")
            
            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")
            
            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra cleanup cancelled at final confirmation")
                print("❌ Cleanup cancelled")
                return
            
            # STEP 3: Start the cleanup sequentially
            print(f"\n💥 STARTING CLEANUP...")
            self.log_operation('INFO', f"🚨 CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(regions)} regions")
            
            start_time = time.time()
            
            successful_tasks = 0
            failed_tasks = 0
            
            # Create tasks list
            tasks = []
            for account_name, account_data in selected_accounts.items():
                for region in regions:
                    tasks.append((account_name, account_data, region))
            
            # Process each task sequentially
            for i, (account_name, account_data, region) in enumerate(tasks, 1):
                print(f"\n[{i}/{len(tasks)}] Processing {account_name} in {region}...")
                
                try:
                    success = self.cleanup_account_region(account_name, account_data, region)
                    if success:
                        successful_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    self.log_operation('ERROR', f"Task failed for {account_name} ({region}): {e}")
                    print(f"❌ Task failed for {account_name} ({region}): {e}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # STEP 4: Display final results
            print(f"\n💥" + "="*25 + " CLEANUP COMPLETE " + "="*25)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"✅ Successful operations: {successful_tasks}")
            print(f"❌ Failed operations: {failed_tasks}")
            print(f"🧠 Clusters deleted: {len(self.cleanup_results['deleted_clusters'])}")
            print(f"🔄 Nodegroups deleted: {len(self.cleanup_results['deleted_nodegroups'])}")
            print(f"⏭️  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            print(f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            self.log_operation('INFO', f"CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Clusters deleted: {len(self.cleanup_results['deleted_clusters'])}")
            self.log_operation('INFO', f"Nodegroups deleted: {len(self.cleanup_results['deleted_nodegroups'])}")
            
            # STEP 5: Show account summary
            if self.cleanup_results['deleted_clusters'] or self.cleanup_results['deleted_nodegroups']:
                print(f"\n📊 Deletion Summary by Account:")
                
                # Group by account
                account_summary = {}
                for cluster in self.cleanup_results['deleted_clusters']:
                    account = cluster['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'clusters': 0, 'nodegroups': 0, 'regions': set()}
                    account_summary[account]['clusters'] += 1
                    account_summary[account]['regions'].add(cluster['region'])
                
                for nodegroup in self.cleanup_results['deleted_nodegroups']:
                    account = nodegroup['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'clusters': 0, 'nodegroups': 0, 'regions': set()}
                    account_summary[account]['nodegroups'] += 1
                    account_summary[account]['regions'].add(nodegroup['region'])
                
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    print(f"   🏦 {account}:")
                    print(f"      🧠 Clusters: {summary['clusters']}")
                    print(f"      🔄 Nodegroups: {summary['nodegroups']}")
                    print(f"      🌍 Regions: {regions_list}")
            
            # STEP 6: Show failures if any
            if self.cleanup_results['failed_deletions']:
                print(f"\n❌ Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    print(f"   • {failure['resource_type']} {failure['resource_id']} in {failure['account_name']} ({failure['region']})")
                    print(f"     Error: {failure['error']}")
                
                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    print(f"   ... and {remaining} more failures (see detailed report)")
            
            # Save comprehensive report
            print(f"\n📄 Saving cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                print(f"✅ Cleanup report saved to: {report_file}")
            
            print(f"✅ Session log saved to: {self.log_filename}")
            
            print(f"\n💥 CLEANUP COMPLETE! 💥")
            print("🚨" * 30)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            print(f"\n❌ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise

def main():
    """Main function"""
    try:
        manager = UltraEKSCleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()