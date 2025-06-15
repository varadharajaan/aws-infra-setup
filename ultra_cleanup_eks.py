#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
import botocore

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

            #STEP 2: Delete all CloudWatch alarms for this cluster
            self.delete_all_cloudwatch_alarms(
                eks_client.meta.config.credentials.access_key,
                eks_client.meta.config.credentials.secret_key,
                region,
                cluster_name
            )

            # STEP 3: Delete all EKS add-ons for this cluster
            self.delete_all_eks_addons(eks_client, cluster_name)

            # Step 4: Delete the cluster itself
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