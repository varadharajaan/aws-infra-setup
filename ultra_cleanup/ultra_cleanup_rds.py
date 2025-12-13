#!/usr/bin/env python3

"""
Ultra RDS Cleanup Manager

Tool to perform comprehensive cleanup of RDS resources across AWS accounts.

Manages deletion of:
- RDS DB Instances
- RDS DB Clusters (Aurora)
- DB Snapshots (manual)
- DB Cluster Snapshots
- Automated Backups
- Snapshot Export Tasks
- Event Subscriptions
- CloudWatch Alarms (RDS-related)
- CloudWatch Log Groups (RDS-related)
- Custom Parameter Groups
- Custom Cluster Parameter Groups
- Custom Option Groups

PROTECTIONS:
- DB Subnet Groups are PRESERVED
- Default Security Groups are PRESERVED
- Default Parameter Groups are PRESERVED
- Default Option Groups are PRESERVED

Author: varadharajaan
Created: 2025-11-24
"""

import os
import json
import boto3
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from botocore.exceptions import ClientError, BotoCoreError
import botocore
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupRDSManager:
    """
    Tool to perform comprehensive cleanup of RDS resources across AWS accounts.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the RDS Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.rds_dir = os.path.join(self.config_dir, "aws", "rds")
        self.reports_dir = os.path.join(self.rds_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_instances': [],
            'deleted_clusters': [],
            'deleted_snapshots': [],
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def _get_user_regions(self) -> List[str]:
        """Get user regions from root accounts config."""
        try:
            config = self.cred_manager.load_root_accounts_config()
            if config:
                return config.get('user_settings', {}).get('user_regions', [
                    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
                ])
        except Exception as e:
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.rds_dir, exist_ok=True)

            # Save log file in the aws/rds directory
            self.log_filename = f"{self.rds_dir}/ultra_rds_cleanup_log_{self.execution_timestamp}.log"

            # Create a file handler for detailed logging
            import logging

            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_rds_cleanup')
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
            self.operation_logger.info("[ALERT] ULTRA RDS CLEANUP SESSION STARTED [ALERT]")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config Dir: {self.config_dir}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)

        except Exception as e:
            self.print_colored(Colors.YELLOW, f"Warning: Could not setup detailed logging: {e}")
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

    def _is_default_parameter_group(self, pg_name: str) -> bool:
        """Check if parameter group is a default one"""
        return pg_name.startswith('default.')

    def _is_default_option_group(self, og_name: str) -> bool:
        """Check if option group is a default one"""
        return og_name.startswith('default:')

    def create_rds_client(self, access_key, secret_key, region):
        """Create RDS client using account credentials"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            # Test the connection
            rds_client.describe_db_instances(MaxRecords=20)
            return rds_client

        except Exception as e:
            self.log_operation('ERROR', f"Failed to create RDS client for {region}: {e}")
            raise

    def get_all_db_instances_in_region(self, rds_client, region, account_info):
        """Get all RDS DB instances in a specific region"""
        try:
            instances = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"[SCAN] Scanning for RDS DB instances in {region} ({account_name})")
            print(f"   [SCAN] Scanning for RDS DB instances in {region} ({account_name})...")

            paginator = rds_client.get_paginator('describe_db_instances')
            
            for page in paginator.paginate():
                for instance in page['DBInstances']:
                    instance_id = instance['DBInstanceIdentifier']
                    
                    try:
                        instance_data = {
                            'instance_id': instance_id,
                            'engine': instance['Engine'],
                            'engine_version': instance.get('EngineVersion', 'Unknown'),
                            'instance_class': instance['DBInstanceClass'],
                            'status': instance['DBInstanceStatus'],
                            'multi_az': instance.get('MultiAZ', False),
                            'storage': instance.get('AllocatedStorage', 0),
                            'created_time': instance.get('InstanceCreateTime', 'Unknown'),
                            'region': region,
                            'account_info': account_info
                        }
                        
                        instances.append(instance_data)

                    except Exception as instance_error:
                        self.log_operation('ERROR', f"Error getting details for instance {instance_id}: {str(instance_error)}")

            self.log_operation('INFO', f"[PACKAGE] Found {len(instances)} RDS DB instances in {region} ({account_name})")
            print(f"   [PACKAGE] Found {len(instances)} RDS DB instances in {region} ({account_name})")

            return instances

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting RDS instances in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting instances in {region}: {e}")
            return []

    def get_all_db_clusters_in_region(self, rds_client, region, account_info):
        """Get all RDS DB clusters (Aurora) in a specific region"""
        try:
            clusters = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"[SCAN] Scanning for RDS DB clusters in {region} ({account_name})")
            print(f"   [SCAN] Scanning for RDS DB clusters in {region} ({account_name})...")

            paginator = rds_client.get_paginator('describe_db_clusters')
            
            for page in paginator.paginate():
                for cluster in page['DBClusters']:
                    cluster_id = cluster['DBClusterIdentifier']
                    
                    try:
                        cluster_data = {
                            'cluster_id': cluster_id,
                            'engine': cluster['Engine'],
                            'engine_version': cluster.get('EngineVersion', 'Unknown'),
                            'status': cluster['Status'],
                            'multi_az': cluster.get('MultiAZ', False),
                            'members': len(cluster.get('DBClusterMembers', [])),
                            'created_time': cluster.get('ClusterCreateTime', 'Unknown'),
                            'region': region,
                            'account_info': account_info
                        }
                        
                        clusters.append(cluster_data)

                    except Exception as cluster_error:
                        self.log_operation('ERROR', f"Error getting details for cluster {cluster_id}: {str(cluster_error)}")

            self.log_operation('INFO', f"[PACKAGE] Found {len(clusters)} RDS DB clusters in {region} ({account_name})")
            print(f"   [PACKAGE] Found {len(clusters)} RDS DB clusters in {region} ({account_name})")

            return clusters

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting RDS clusters in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting clusters in {region}: {e}")
            return []

    def delete_db_instance(self, rds_client, instance_info):
        """Delete an RDS DB instance"""
        try:
            instance_id = instance_info['instance_id']
            region = instance_info['region']
            account_name = instance_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"[DELETE]  Deleting RDS DB instance {instance_id} ({region}, {account_name})")
            print(f"      [DELETE]  Deleting DB instance {instance_id}...")

            # Delete the instance without final snapshot
            rds_client.delete_db_instance(
                DBInstanceIdentifier=instance_id,
                SkipFinalSnapshot=True,
                DeleteAutomatedBackups=True
            )

            # Wait for deletion to complete
            print(f"      [WAIT] Waiting for DB instance {instance_id} deletion to complete...")
            self.log_operation('INFO', f"[WAIT] Waiting for DB instance {instance_id} deletion to complete...")

            waiter_active = True
            retry_count = 0
            max_retries = 60  # 30 minutes

            while waiter_active and retry_count < max_retries:
                try:
                    response = rds_client.describe_db_instances(
                        DBInstanceIdentifier=instance_id
                    )
                    status = response['DBInstances'][0]['DBInstanceStatus']

                    if status == 'deleting':
                        if retry_count % 10 == 0:
                            self.log_operation('INFO', f"DB instance {instance_id} status: {status} (Waiting...)")
                        time.sleep(30)
                        retry_count += 1
                    else:
                        self.log_operation('WARNING', f"Unexpected instance status: {status}")
                        break
                except ClientError as e:
                    if 'DBInstanceNotFound' in str(e):
                        self.log_operation('INFO', f"[OK] DB instance {instance_id} deleted successfully")
                        print(f"      [OK] DB instance {instance_id} deleted successfully")
                        waiter_active = False
                    else:
                        self.log_operation('ERROR', f"Error checking instance status: {e}")
                        raise

            if retry_count >= max_retries:
                self.log_operation('WARNING', f"Timed out waiting for instance {instance_id} deletion")
                print(f"      [WARN]  Timed out waiting for instance {instance_id} deletion")

            self.cleanup_results['deleted_instances'].append({
                'instance_id': instance_id,
                'engine': instance_info['engine'],
                'region': region,
                'account_info': instance_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete DB instance {instance_info['instance_id']}: {e}")
            print(f"      [ERROR] Failed to delete DB instance {instance_info['instance_id']}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'db_instance',
                'resource_id': instance_info['instance_id'],
                'region': instance_info['region'],
                'account_info': instance_info['account_info'],
                'error': str(e)
            })
            return False

    def delete_db_cluster(self, rds_client, cluster_info):
        """Delete an RDS DB cluster (Aurora)"""
        try:
            cluster_id = cluster_info['cluster_id']
            region = cluster_info['region']
            account_name = cluster_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"[DELETE]  Deleting RDS DB cluster {cluster_id} ({region}, {account_name})")
            print(f"      [DELETE]  Deleting DB cluster {cluster_id}...")

            # Delete the cluster without final snapshot
            rds_client.delete_db_cluster(
                DBClusterIdentifier=cluster_id,
                SkipFinalSnapshot=True
            )

            # Wait for deletion to complete
            print(f"      [WAIT] Waiting for DB cluster {cluster_id} deletion to complete...")
            self.log_operation('INFO', f"[WAIT] Waiting for DB cluster {cluster_id} deletion to complete...")

            waiter_active = True
            retry_count = 0
            max_retries = 60  # 30 minutes

            while waiter_active and retry_count < max_retries:
                try:
                    response = rds_client.describe_db_clusters(
                        DBClusterIdentifier=cluster_id
                    )
                    status = response['DBClusters'][0]['Status']

                    if status == 'deleting':
                        if retry_count % 10 == 0:
                            self.log_operation('INFO', f"DB cluster {cluster_id} status: {status} (Waiting...)")
                        time.sleep(30)
                        retry_count += 1
                    else:
                        self.log_operation('WARNING', f"Unexpected cluster status: {status}")
                        break
                except ClientError as e:
                    if 'DBClusterNotFoundFault' in str(e):
                        self.log_operation('INFO', f"[OK] DB cluster {cluster_id} deleted successfully")
                        print(f"      [OK] DB cluster {cluster_id} deleted successfully")
                        waiter_active = False
                    else:
                        self.log_operation('ERROR', f"Error checking cluster status: {e}")
                        raise

            if retry_count >= max_retries:
                self.log_operation('WARNING', f"Timed out waiting for cluster {cluster_id} deletion")
                print(f"      [WARN]  Timed out waiting for cluster {cluster_id} deletion")

            self.cleanup_results['deleted_clusters'].append({
                'cluster_id': cluster_id,
                'engine': cluster_info['engine'],
                'region': region,
                'account_info': cluster_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete DB cluster {cluster_info['cluster_id']}: {e}")
            print(f"      [ERROR] Failed to delete DB cluster {cluster_info['cluster_id']}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'db_cluster',
                'resource_id': cluster_info['cluster_id'],
                'region': cluster_info['region'],
                'account_info': cluster_info['account_info'],
                'error': str(e)
            })
            return False

    def delete_all_snapshots(self, access_key, secret_key, region, account_info):
        """Delete all manual RDS snapshots"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            
            self.log_operation('INFO', f"[DELETE]  Deleting manual DB snapshots in {region}")
            print(f"   [DELETE]  Deleting manual DB snapshots in {region}...")

            # Delete DB snapshots
            paginator = rds_client.get_paginator('describe_db_snapshots')
            for page in paginator.paginate(SnapshotType='manual'):
                for snapshot in page['DBSnapshots']:
                    snapshot_id = snapshot['DBSnapshotIdentifier']
                    
                    try:
                        rds_client.delete_db_snapshot(DBSnapshotIdentifier=snapshot_id)
                        self.log_operation('INFO', f"[OK] Deleted DB snapshot: {snapshot_id}")
                        print(f"      [OK] Deleted DB snapshot: {snapshot_id}")
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_snapshots'].append({
                            'snapshot_id': snapshot_id,
                            'type': 'db_snapshot',
                            'region': region,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete snapshot {snapshot_id}: {e}")

            # Delete cluster snapshots
            cluster_paginator = rds_client.get_paginator('describe_db_cluster_snapshots')
            for page in cluster_paginator.paginate(SnapshotType='manual'):
                for snapshot in page['DBClusterSnapshots']:
                    snapshot_id = snapshot['DBClusterSnapshotIdentifier']
                    
                    try:
                        rds_client.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapshot_id)
                        self.log_operation('INFO', f"[OK] Deleted cluster snapshot: {snapshot_id}")
                        print(f"      [OK] Deleted cluster snapshot: {snapshot_id}")
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_snapshots'].append({
                            'snapshot_id': snapshot_id,
                            'type': 'cluster_snapshot',
                            'region': region,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete cluster snapshot {snapshot_id}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} snapshots")
            else:
                self.log_operation('INFO', f"No manual snapshots found in {region}")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete snapshots in {region}: {e}")
            return False

    def delete_automated_backups(self, access_key, secret_key, region):
        """Delete automated backups"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            
            self.log_operation('INFO', f"[DELETE]  Deleting automated backups in {region}")
            print(f"   [DELETE]  Deleting automated backups in {region}...")

            response = rds_client.describe_db_instance_automated_backups()
            
            for backup in response.get('DBInstanceAutomatedBackups', []):
                backup_arn = backup.get('DBInstanceAutomatedBackupsArn')
                
                if backup_arn:
                    try:
                        rds_client.delete_db_instance_automated_backup(
                            DBInstanceAutomatedBackupsArn=backup_arn
                        )
                        self.log_operation('INFO', f"[OK] Deleted automated backup: {backup_arn}")
                        deleted_count += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete automated backup: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} automated backups")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete automated backups: {e}")
            return False

    def delete_export_tasks(self, access_key, secret_key, region):
        """Delete snapshot export tasks"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            
            response = rds_client.describe_export_tasks()
            
            for export in response.get('ExportTasks', []):
                export_id = export['ExportTaskIdentifier']
                
                try:
                    rds_client.cancel_export_task(ExportTaskIdentifier=export_id)
                    self.log_operation('INFO', f"[OK] Canceled export task: {export_id}")
                    deleted_count += 1
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to cancel export {export_id}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Canceled {deleted_count} export tasks")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete export tasks: {e}")
            return False

    def delete_event_subscriptions(self, access_key, secret_key, region):
        """Delete RDS event subscriptions"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            
            paginator = rds_client.get_paginator('describe_event_subscriptions')
            
            for page in paginator.paginate():
                for subscription in page['EventSubscriptionsList']:
                    sub_name = subscription['CustSubscriptionId']
                    
                    try:
                        rds_client.delete_event_subscription(SubscriptionName=sub_name)
                        self.log_operation('INFO', f"[OK] Deleted event subscription: {sub_name}")
                        deleted_count += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete subscription {sub_name}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} event subscriptions")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete event subscriptions: {e}")
            return False

    def delete_parameter_groups(self, access_key, secret_key, region):
        """Delete custom parameter groups (preserve defaults)"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            protected_count = 0
            
            paginator = rds_client.get_paginator('describe_db_parameter_groups')
            
            for page in paginator.paginate():
                for pg in page['DBParameterGroups']:
                    pg_name = pg['DBParameterGroupName']
                    
                    # PROTECTION: Skip default parameter groups
                    if self._is_default_parameter_group(pg_name):
                        self.log_operation('INFO', f"[PROTECTED]  PROTECTED (default): {pg_name}")
                        protected_count += 1
                        self.cleanup_results['skipped_resources'].append({
                            'resource_type': 'parameter_group',
                            'resource_id': pg_name,
                            'reason': 'Default parameter group - preserved'
                        })
                        continue
                    
                    try:
                        rds_client.delete_db_parameter_group(DBParameterGroupName=pg_name)
                        self.log_operation('INFO', f"[OK] Deleted parameter group: {pg_name}")
                        deleted_count += 1
                    except ClientError as e:
                        if 'InvalidDBParameterGroupState' in str(e):
                            self.log_operation('WARNING', f"Parameter group {pg_name} in use, skipping")
                        else:
                            self.log_operation('ERROR', f"Failed to delete {pg_name}: {e}")

            # Delete cluster parameter groups
            cluster_paginator = rds_client.get_paginator('describe_db_cluster_parameter_groups')
            
            for page in cluster_paginator.paginate():
                for pg in page['DBClusterParameterGroups']:
                    pg_name = pg['DBClusterParameterGroupName']
                    
                    if self._is_default_parameter_group(pg_name):
                        self.log_operation('INFO', f"[PROTECTED]  PROTECTED (default cluster): {pg_name}")
                        protected_count += 1
                        continue
                    
                    try:
                        rds_client.delete_db_cluster_parameter_group(DBClusterParameterGroupName=pg_name)
                        self.log_operation('INFO', f"[OK] Deleted cluster parameter group: {pg_name}")
                        deleted_count += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete {pg_name}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} parameter groups, protected {protected_count}")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete parameter groups: {e}")
            return False

    def delete_option_groups(self, access_key, secret_key, region):
        """Delete custom option groups (preserve defaults)"""
        try:
            rds_client = boto3.client(
                'rds',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            protected_count = 0
            
            paginator = rds_client.get_paginator('describe_option_groups')
            
            for page in paginator.paginate():
                for og in page['OptionGroupsList']:
                    og_name = og['OptionGroupName']
                    
                    # PROTECTION: Skip default option groups
                    if self._is_default_option_group(og_name):
                        self.log_operation('INFO', f"[PROTECTED]  PROTECTED (default): {og_name}")
                        protected_count += 1
                        self.cleanup_results['skipped_resources'].append({
                            'resource_type': 'option_group',
                            'resource_id': og_name,
                            'reason': 'Default option group - preserved'
                        })
                        continue
                    
                    try:
                        rds_client.delete_option_group(OptionGroupName=og_name)
                        self.log_operation('INFO', f"[OK] Deleted option group: {og_name}")
                        deleted_count += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete {og_name}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} option groups, protected {protected_count}")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete option groups: {e}")
            return False

    def delete_cloudwatch_alarms(self, access_key, secret_key, region):
        """Delete CloudWatch alarms related to RDS"""
        try:
            cw_client = boto3.client(
                'cloudwatch',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            
            paginator = cw_client.get_paginator('describe_alarms')
            
            for page in paginator.paginate():
                for alarm in page['MetricAlarms']:
                    namespace = alarm.get('Namespace', '')
                    
                    # Only process RDS-related alarms
                    if namespace == 'AWS/RDS':
                        alarm_name = alarm['AlarmName']
                        
                        try:
                            cw_client.delete_alarms(AlarmNames=[alarm_name])
                            self.log_operation('INFO', f"[OK] Deleted CloudWatch alarm: {alarm_name}")
                            deleted_count += 1
                        except Exception as e:
                            self.log_operation('ERROR', f"Failed to delete alarm {alarm_name}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} CloudWatch alarms")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete CloudWatch alarms: {e}")
            return False

    def delete_cloudwatch_logs(self, access_key, secret_key, region):
        """Delete CloudWatch log groups related to RDS"""
        try:
            logs_client = boto3.client(
                'logs',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            deleted_count = 0
            
            paginator = logs_client.get_paginator('describe_log_groups')
            
            for page in paginator.paginate():
                for log_group in page['logGroups']:
                    log_group_name = log_group['logGroupName']
                    
                    # Only process RDS-related log groups
                    if '/aws/rds/' in log_group_name or log_group_name.startswith('RDS'):
                        try:
                            logs_client.delete_log_group(logGroupName=log_group_name)
                            self.log_operation('INFO', f"[OK] Deleted log group: {log_group_name}")
                            deleted_count += 1
                        except Exception as e:
                            self.log_operation('ERROR', f"Failed to delete log group {log_group_name}: {e}")

            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} CloudWatch log groups")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete CloudWatch logs: {e}")
            return False

    def cleanup_account_region(self, account_info, region):
        """Clean up all RDS resources in a specific account and region"""
        try:
            access_key = account_info['access_key']
            secret_key = account_info['secret_key']
            account_id = account_info['account_id']
            account_key = account_info['account_key']

            self.log_operation('INFO', f"[CLEANUP] Starting RDS cleanup for {account_key} ({account_id}) in {region}")
            print(f"\n[CLEANUP] Starting RDS cleanup for {account_key} ({account_id}) in {region}")

            # Create RDS client
            try:
                rds_client = self.create_rds_client(access_key, secret_key, region)
            except Exception as client_error:
                self.log_operation('ERROR', f"Could not create RDS client for {region}: {client_error}")
                print(f"   [ERROR] Could not create RDS client for {region}: {client_error}")
                return False

            # Get all RDS instances
            instances = self.get_all_db_instances_in_region(rds_client, region, account_info)
            
            # Get all RDS clusters
            clusters = self.get_all_db_clusters_in_region(rds_client, region, account_info)

            if not instances and not clusters:
                self.log_operation('INFO', f"No RDS resources found in {account_key} ({region})")
                print(f"   ✓ No RDS resources found in {account_key} ({region})")
            else:
                # Record region summary
                region_summary = {
                    'account_key': account_key,
                    'account_id': account_id,
                    'region': region,
                    'instances_found': len(instances),
                    'clusters_found': len(clusters)
                }
                self.cleanup_results['regions_processed'].append(region_summary)

                self.log_operation('INFO', f"[STATS] {account_key} ({region}) RDS resources summary:")
                self.log_operation('INFO', f"   [CLUSTER]  DB Instances: {len(instances)}")
                self.log_operation('INFO', f"   🔄 DB Clusters: {len(clusters)}")

                print(f"   [STATS] RDS resources found: {len(instances)} instances, {len(clusters)} clusters")

                # Delete instances
                deleted_instances = 0
                failed_instances = 0

                for i, instance in enumerate(instances, 1):
                    print(f"   [{i}/{len(instances)}] Processing instance {instance['instance_id']}...")
                    
                    try:
                        if self.delete_db_instance(rds_client, instance):
                            deleted_instances += 1
                        else:
                            failed_instances += 1
                    except Exception as e:
                        failed_instances += 1
                        self.log_operation('ERROR', f"Error deleting instance: {e}")

                # Delete clusters
                deleted_clusters = 0
                failed_clusters = 0

                for i, cluster in enumerate(clusters, 1):
                    print(f"   [{i}/{len(clusters)}] Processing cluster {cluster['cluster_id']}...")
                    
                    try:
                        if self.delete_db_cluster(rds_client, cluster):
                            deleted_clusters += 1
                        else:
                            failed_clusters += 1
                    except Exception as e:
                        failed_clusters += 1
                        self.log_operation('ERROR', f"Error deleting cluster: {e}")

                print(f"   [OK] Deleted {deleted_instances} instances, {deleted_clusters} clusters")

            # Delete snapshots
            self.delete_all_snapshots(access_key, secret_key, region, account_info)
            
            # Delete automated backups
            self.delete_automated_backups(access_key, secret_key, region)
            
            # Delete export tasks
            self.delete_export_tasks(access_key, secret_key, region)
            
            # Delete event subscriptions
            self.delete_event_subscriptions(access_key, secret_key, region)
            
            # Delete CloudWatch alarms
            self.delete_cloudwatch_alarms(access_key, secret_key, region)
            
            # Delete CloudWatch logs
            self.delete_cloudwatch_logs(access_key, secret_key, region)
            
            # Delete parameter groups (custom only)
            self.delete_parameter_groups(access_key, secret_key, region)
            
            # Delete option groups (custom only)
            self.delete_option_groups(access_key, secret_key, region)

            self.log_operation('INFO', f"[OK] RDS cleanup completed for {account_key} ({region})")
            print(f"\n   [OK] RDS cleanup completed for {account_key} ({region})")
            return True

        except Exception as e:
            account_key = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error cleaning up RDS resources in {account_key} ({region}): {e}")
            print(f"   [ERROR] Error cleaning up RDS resources in {account_key} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_info': account_info,
                'region': region,
                'error': str(e)
            })
            return False

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n[REGION] Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(f"Select regions (1-{len(self.user_regions)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all" or not choice:
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {len(self.user_regions)} regions")
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(choice, len(self.user_regions))
                if not selected_indices:
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
                return selected_regions

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_rds_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_instances_deleted = len(self.cleanup_results['deleted_instances'])
            total_clusters_deleted = len(self.cleanup_results['deleted_clusters'])
            total_snapshots_deleted = len(self.cleanup_results['deleted_snapshots'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_RDS_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(set(rp['account_key'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_instances_deleted": total_instances_deleted,
                    "total_clusters_deleted": total_clusters_deleted,
                    "total_snapshots_deleted": total_snapshots_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_instances": self.cleanup_results['deleted_instances'],
                    "deleted_clusters": self.cleanup_results['deleted_clusters'],
                    "deleted_snapshots": self.cleanup_results['deleted_snapshots'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }

            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation('INFO', f"[OK] Ultra RDS cleanup report saved to: {report_filename}")
            return report_filename

        except Exception as e:
            self.log_operation('ERROR', f"[ERROR] Failed to save ultra RDS cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.print_colored(Colors.CYAN, "\n" + "=" * 100)
            self.print_colored(Colors.CYAN, "[DELETE]  ULTRA RDS CLEANUP MANAGER")
            self.print_colored(Colors.CYAN, "=" * 100)

            # Select accounts
            accounts = self.cred_manager.select_root_accounts_interactive()
            if not accounts:
                self.print_colored(Colors.YELLOW, "No accounts selected. Exiting.")
                return

            # Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.YELLOW, "No regions selected. Exiting.")
                return

            # Confirm deletion
            self.print_colored(Colors.RED, "\n[WARN]  WARNING: This will DELETE RDS resources!")
            self.print_colored(Colors.YELLOW, f"Accounts: {len(accounts)}")
            self.print_colored(Colors.YELLOW, f"Regions: {', '.join(selected_regions)}")
            
            confirm = input("\nType 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.print_colored(Colors.YELLOW, "Cleanup cancelled.")
                return

            # Process each account and region
            for account_info in accounts:
                account_key = account_info.get('account_key', 'Unknown')
                self.cleanup_results['accounts_processed'].append(account_key)

                for region in selected_regions:
                    self.cleanup_account_region(account_info, region)

            # Save report
            report_file = self.save_cleanup_report()

            # Display summary
            self.print_colored(Colors.CYAN, "\n" + "=" * 100)
            self.print_colored(Colors.CYAN, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.CYAN, "=" * 100)
            self.print_colored(Colors.GREEN, f"[OK] DB Instances Deleted: {len(self.cleanup_results['deleted_instances'])}")
            self.print_colored(Colors.GREEN, f"[OK] DB Clusters Deleted: {len(self.cleanup_results['deleted_clusters'])}")
            self.print_colored(Colors.GREEN, f"[OK] Snapshots Deleted: {len(self.cleanup_results['deleted_snapshots'])}")
            self.print_colored(Colors.YELLOW, f"[WARN]  Resources Skipped: {len(self.cleanup_results['skipped_resources'])}")
            self.print_colored(Colors.RED, f"[ERROR] Failed Deletions: {len(self.cleanup_results['failed_deletions'])}")

            # Show deletion summary by account
            if self.cleanup_results['deleted_instances'] or self.cleanup_results['deleted_clusters']:
                self.print_colored(Colors.CYAN, f"\n[STATS] Deletion Summary by Account:")
                
                account_summary = {}
                
                # Process instances
                for instance in self.cleanup_results['deleted_instances']:
                    account = instance.get('account_name', 'Unknown')
                    region = instance.get('region', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'clusters': 0, 'snapshots': 0, 'regions': set()}
                    account_summary[account]['instances'] += 1
                    account_summary[account]['regions'].add(region)
                
                # Process clusters
                for cluster in self.cleanup_results['deleted_clusters']:
                    account = cluster.get('account_name', 'Unknown')
                    region = cluster.get('region', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'clusters': 0, 'snapshots': 0, 'regions': set()}
                    account_summary[account]['clusters'] += 1
                    account_summary[account]['regions'].add(region)
                
                # Process snapshots
                for snapshot in self.cleanup_results['deleted_snapshots']:
                    account = snapshot.get('account_name', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'clusters': 0, 'snapshots': 0, 'regions': set()}
                    account_summary[account]['snapshots'] += 1
                
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions'])) if summary['regions'] else 'N/A'
                    self.print_colored(Colors.WHITE, f"   [BANK] {account}:")
                    self.print_colored(Colors.WHITE, f"      [INSTANCE] DB Instances: {summary['instances']}")
                    self.print_colored(Colors.WHITE, f"      [CLUSTER]  DB Clusters: {summary['clusters']}")
                    self.print_colored(Colors.WHITE, f"      [SNAPSHOT] Snapshots: {summary['snapshots']}")
                    self.print_colored(Colors.WHITE, f"      [REGION] Regions: {regions_list}")

            self.print_colored(Colors.CYAN, f"\n[FILE] Report: {report_file}")
            self.print_colored(Colors.CYAN, f"[LOG] Log: {self.log_filename}")
            self.print_colored(Colors.CYAN, "=" * 100)

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n\nCleanup interrupted by user.")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupRDSManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
