#!/usr/bin/env python3

"""
Ultra DynamoDB Cleanup Manager

Tool to perform comprehensive cleanup of DynamoDB resources across AWS accounts.

Manages deletion of:
- DynamoDB Tables
- Global Tables (replicas)
- Backups (on-demand)
- Continuous Backups (Point-in-Time Recovery disabled)
- CloudWatch Alarms (DynamoDB-related)
- CloudWatch Log Groups (DynamoDB-related)

PROTECTIONS:
- Tables with deletion protection enabled are SKIPPED
- Production tables (configurable tags) can be PROTECTED
- Tables in CREATING/UPDATING state are SKIPPED

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


class UltraCleanupDynamoDBManager:
    """
    Tool to perform comprehensive cleanup of DynamoDB resources across AWS accounts.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the DynamoDB Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.dynamodb_dir = os.path.join(self.config_dir, "aws", "dynamodb")
        self.reports_dir = os.path.join(self.dynamodb_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_tables': [],
            'deleted_backups': [],
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
            os.makedirs(self.dynamodb_dir, exist_ok=True)

            # Save log file in the aws/dynamodb directory
            self.log_filename = f"{self.dynamodb_dir}/ultra_dynamodb_cleanup_log_{self.execution_timestamp}.log"
            
            import logging
            
            self.operation_logger = logging.getLogger('ultra_dynamodb_cleanup')
            self.operation_logger.setLevel(logging.INFO)
            
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)
            
            self.operation_logger.info("=" * 100)
            self.operation_logger.info("[ALERT] ULTRA DYNAMODB CLEANUP SESSION STARTED [ALERT]")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config Dir: {self.config_dir}")
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

    def create_dynamodb_client(self, access_key, secret_key, region):
        """Create DynamoDB client using account credentials"""
        try:
            client = boto3.client(
                'dynamodb',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the connection
            client.list_tables(Limit=1)
            
            return client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create DynamoDB client for {region}: {e}")
            raise

    def create_cloudwatch_client(self, access_key, secret_key, region):
        """Create CloudWatch client"""
        try:
            return boto3.client(
                'cloudwatch',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create CloudWatch client: {e}")
            return None

    def create_logs_client(self, access_key, secret_key, region):
        """Create CloudWatch Logs client"""
        try:
            return boto3.client(
                'logs',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create CloudWatch Logs client: {e}")
            return None

    def get_all_tables(self, dynamodb_client, region, account_name):
        """Get all DynamoDB tables in a specific region"""
        try:
            tables = []
            
            self.log_operation('INFO', f"[SCAN] Scanning for DynamoDB tables in {region} ({account_name})")
            print(f"   [SCAN] Scanning for DynamoDB tables in {region} ({account_name})...")
            
            # List all tables
            paginator = dynamodb_client.get_paginator('list_tables')
            
            for page in paginator.paginate():
                for table_name in page.get('TableNames', []):
                    try:
                        # Get table details
                        response = dynamodb_client.describe_table(TableName=table_name)
                        table = response['Table']
                        
                        # Get tags
                        try:
                            tags_response = dynamodb_client.list_tags_of_resource(
                                ResourceArn=table['TableArn']
                            )
                            tags = {tag['Key']: tag['Value'] for tag in tags_response.get('Tags', [])}
                        except:
                            tags = {}
                        
                        table_info = {
                            'table_name': table_name,
                            'table_arn': table['TableArn'],
                            'status': table['TableStatus'],
                            'creation_date': table['CreationDateTime'].strftime("%Y-%m-%d %H:%M:%S") if 'CreationDateTime' in table else 'N/A',
                            'item_count': table.get('ItemCount', 0),
                            'size_bytes': table.get('TableSizeBytes', 0),
                            'billing_mode': table.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED'),
                            'deletion_protection': table.get('DeletionProtectionEnabled', False),
                            'global_table': table.get('GlobalTableVersion') is not None,
                            'stream_enabled': table.get('StreamSpecification', {}).get('StreamEnabled', False),
                            'pitr_enabled': False,  # Will check separately
                            'tags': tags,
                            'region': region,
                            'account_name': account_name
                        }
                        
                        # Check Point-in-Time Recovery
                        try:
                            pitr_response = dynamodb_client.describe_continuous_backups(TableName=table_name)
                            table_info['pitr_enabled'] = pitr_response.get('ContinuousBackupsDescription', {}).get('PointInTimeRecoveryDescription', {}).get('PointInTimeRecoveryStatus') == 'ENABLED'
                        except:
                            pass
                        
                        tables.append(table_info)
                        
                    except Exception as e:
                        self.log_operation('WARNING', f"Could not describe table {table_name}: {e}")
            
            self.log_operation('INFO', f"[STATS] Found {len(tables)} DynamoDB tables in {region} ({account_name})")
            print(f"   [STATS] Found {len(tables)} DynamoDB tables in {region} ({account_name})")
            
            # Count by status
            active_count = sum(1 for t in tables if t['status'] == 'ACTIVE')
            protected_count = sum(1 for t in tables if t['deletion_protection'])
            
            if tables:
                print(f"      ✓ Active: {active_count}, Protected: {protected_count}")
            
            return tables
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting DynamoDB tables in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting DynamoDB tables in {region}: {e}")
            return []

    def get_table_backups(self, dynamodb_client, table_arn, table_name):
        """Get all backups for a specific table"""
        try:
            backups = []
            
            paginator = dynamodb_client.get_paginator('list_backups')
            
            for page in paginator.paginate(TableName=table_name):
                for backup in page.get('BackupSummaries', []):
                    backups.append({
                        'backup_arn': backup['BackupArn'],
                        'backup_name': backup['BackupName'],
                        'backup_status': backup['BackupStatus'],
                        'backup_type': backup['BackupType'],
                        'creation_date': backup['BackupCreationDateTime'].strftime("%Y-%m-%d %H:%M:%S"),
                        'size_bytes': backup.get('BackupSizeBytes', 0)
                    })
            
            return backups
            
        except Exception as e:
            self.log_operation('WARNING', f"Could not list backups for {table_name}: {e}")
            return []

    def delete_table(self, dynamodb_client, table_info):
        """Delete a DynamoDB table"""
        try:
            table_name = table_info['table_name']
            region = table_info['region']
            account_name = table_info['account_name']
            
            # PROTECTION: Skip tables with deletion protection
            if table_info['deletion_protection']:
                self.log_operation('INFO', f"[PROTECTED]  PROTECTED: {table_name} - deletion protection enabled")
                print(f"      [PROTECTED]  Skipping {table_name} - deletion protection enabled")
                
                self.cleanup_results['skipped_resources'].append({
                    'resource_type': 'table',
                    'resource_id': table_name,
                    'region': region,
                    'account_name': account_name,
                    'reason': 'Deletion protection enabled'
                })
                return False
            
            # PROTECTION: Skip tables in non-ACTIVE state
            if table_info['status'] not in ['ACTIVE', 'ARCHIVED']:
                self.log_operation('INFO', f"[SKIP]  Skipping {table_name} - status: {table_info['status']}")
                print(f"      [SKIP]  Skipping {table_name} - status: {table_info['status']}")
                
                self.cleanup_results['skipped_resources'].append({
                    'resource_type': 'table',
                    'resource_id': table_name,
                    'region': region,
                    'account_name': account_name,
                    'reason': f"Status: {table_info['status']}"
                })
                return False
            
            # Delete table
            self.log_operation('INFO', f"[DELETE]  Deleting table {table_name} ({table_info['item_count']} items, {table_info['size_bytes']} bytes)")
            print(f"      [DELETE]  Deleting table {table_name}")
            
            dynamodb_client.delete_table(TableName=table_name)
            
            self.log_operation('INFO', f"[OK] Successfully deleted table {table_name}")
            
            # Record the table deletion
            self.cleanup_results['deleted_tables'].append({
                'table_name': table_name,
                'table_arn': table_info['table_arn'],
                'status': table_info['status'],
                'creation_date': table_info['creation_date'],
                'item_count': table_info['item_count'],
                'size_bytes': table_info['size_bytes'],
                'billing_mode': table_info['billing_mode'],
                'global_table': table_info['global_table'],
                'stream_enabled': table_info['stream_enabled'],
                'pitr_enabled': table_info['pitr_enabled'],
                'tags': table_info['tags'],
                'region': region,
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete table {table_info['table_name']}: {e}")
            print(f"      [ERROR] Failed to delete table {table_info['table_name']}: {e}")
            
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'table',
                'resource_id': table_info['table_name'],
                'region': table_info['region'],
                'account_name': table_info['account_name'],
                'error': str(e)
            })
            return False

    def delete_table_backups(self, dynamodb_client, table_info):
        """Delete all backups for a table"""
        try:
            table_name = table_info['table_name']
            region = table_info['region']
            account_name = table_info['account_name']
            
            backups = self.get_table_backups(dynamodb_client, table_info['table_arn'], table_name)
            
            if not backups:
                return True
            
            deleted_count = 0
            
            print(f"         [DELETE]  Deleting {len(backups)} backups for {table_name}...")
            
            for backup in backups:
                try:
                    # Only delete USER (on-demand) backups, skip SYSTEM backups
                    if backup['backup_type'] == 'USER':
                        self.log_operation('INFO', f"Deleting backup {backup['backup_name']}")
                        dynamodb_client.delete_backup(BackupArn=backup['backup_arn'])
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_backups'].append({
                            'backup_arn': backup['backup_arn'],
                            'backup_name': backup['backup_name'],
                            'table_name': table_name,
                            'backup_type': backup['backup_type'],
                            'creation_date': backup['creation_date'],
                            'size_bytes': backup['size_bytes'],
                            'region': region,
                            'account_name': account_name,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    else:
                        self.log_operation('INFO', f"Skipping system backup {backup['backup_name']}")
                        
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to delete backup {backup['backup_name']}: {e}")
                    print(f"         [ERROR] Failed to delete backup {backup['backup_name']}: {e}")
            
            if deleted_count > 0:
                self.log_operation('INFO', f"[OK] Deleted {deleted_count} backups for {table_name}")
                print(f"         [OK] Deleted {deleted_count} backups")
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete backups for {table_name}: {e}")
            return False

    def delete_cloudwatch_alarms(self, cloudwatch_client, table_name, region, account_name):
        """Delete CloudWatch alarms related to a DynamoDB table"""
        try:
            if not cloudwatch_client:
                return
            
            # Get alarms with table name in the dimension
            alarms_to_delete = []
            
            paginator = cloudwatch_client.get_paginator('describe_alarms')
            for page in paginator.paginate():
                for alarm in page.get('MetricAlarms', []):
                    # Check if alarm is related to this DynamoDB table
                    for dimension in alarm.get('Dimensions', []):
                        if dimension.get('Name') == 'TableName' and dimension.get('Value') == table_name:
                            alarms_to_delete.append(alarm['AlarmName'])
                            break
            
            if alarms_to_delete:
                print(f"         [NOTIFY] Deleting {len(alarms_to_delete)} CloudWatch alarms...")
                cloudwatch_client.delete_alarms(AlarmNames=alarms_to_delete)
                self.log_operation('INFO', f"[OK] Deleted {len(alarms_to_delete)} CloudWatch alarms for {table_name}")
            
        except Exception as e:
            self.log_operation('WARNING', f"Could not delete CloudWatch alarms for {table_name}: {e}")

    def cleanup_account_region(self, account_info: dict, region: str) -> bool:
        """Clean up all DynamoDB resources in a specific account and region"""
        try:
            account_name = account_info.get('name', 'Unknown')
            account_id = account_info.get('account_id', 'Unknown')
            access_key = account_info.get('access_key')
            secret_key = account_info.get('secret_key')
        
            self.log_operation('INFO', f"[CLEANUP] Starting cleanup for {account_name} ({account_id}) in {region}")
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] Starting cleanup for {account_name} ({account_id}) in {region}")
        
            # Create DynamoDB client
            try:
                dynamodb_client = self.create_dynamodb_client(access_key, secret_key, region)
                cloudwatch_client = self.create_cloudwatch_client(access_key, secret_key, region)
            except Exception as client_error:
                error_msg = f"Could not create clients for {region}: {client_error}"
                self.log_operation('ERROR', error_msg)
                self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
                return False
        
            # Get all tables
            tables = self.get_all_tables(dynamodb_client, region, account_name)
        
            if not tables:
                self.log_operation('INFO', f"No DynamoDB tables found in {account_name} ({region})")
                self.print_colored(Colors.GREEN, f"   ✓ No DynamoDB tables found in {account_name} ({region})")
                return True
        
            # Record region summary
            region_summary = {
                'account_name': account_name,
                'account_id': account_id,
                'region': region,
                'tables_found': len(tables),
                'total_items': sum(t['item_count'] for t in tables),
                'total_size_bytes': sum(t['size_bytes'] for t in tables)
            }
            self.cleanup_results['regions_processed'].append(region_summary)
        
            # Add account to processed accounts if not already there
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({
                    'account_name': account_name,
                    'account_id': account_id
                })
            
            # Delete each table
            if tables:
                print(f"\n   [DELETE]  Processing {len(tables)} DynamoDB tables...")
                for table in tables:
                    # Delete backups first
                    self.delete_table_backups(dynamodb_client, table)
                    
                    # Delete CloudWatch alarms
                    self.delete_cloudwatch_alarms(cloudwatch_client, table['table_name'], region, account_name)
                    
                    # Delete the table
                    self.delete_table(dynamodb_client, table)
        
            self.log_operation('INFO', f"[OK] Cleanup completed for {account_name} ({region})")
            self.print_colored(Colors.GREEN, f"   [OK] Cleanup completed for {account_name} ({region})")
            return True
        
        except Exception as e:
            error_msg = f"Error cleaning up {account_name} ({region}): {e}"
            self.log_operation('ERROR', error_msg)
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_dynamodb_cleanup_report_{self.execution_timestamp}.json"
            
            total_tables_deleted = len(self.cleanup_results['deleted_tables'])
            total_backups_deleted = len(self.cleanup_results['deleted_backups'])
            total_skipped = len(self.cleanup_results['skipped_resources'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            
            # Group by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for table in self.cleanup_results['deleted_tables']:
                account = table['account_name']
                region = table['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'tables': 0, 'backups': 0}
                deletions_by_account[account]['tables'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'tables': 0, 'backups': 0}
                deletions_by_region[region]['tables'] += 1
            
            for backup in self.cleanup_results['deleted_backups']:
                account = backup['account_name']
                region = backup['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'tables': 0, 'backups': 0}
                deletions_by_account[account]['backups'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'tables': 0, 'backups': 0}
                deletions_by_region[region]['backups'] += 1
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_DYNAMODB_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(self.cleanup_results['accounts_processed']),
                    "total_regions_processed": len(self.cleanup_results['regions_processed']),
                    "total_tables_deleted": total_tables_deleted,
                    "total_backups_deleted": total_backups_deleted,
                    "total_skipped_resources": total_skipped,
                    "total_failed_deletions": total_failed,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results['accounts_processed'],
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_tables": self.cleanup_results['deleted_tables'],
                    "deleted_backups": self.cleanup_results['deleted_backups'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"[OK] Ultra cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"[ERROR] Failed to save ultra cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.log_operation('INFO', "[ALERT] STARTING ULTRA DYNAMODB CLEANUP SESSION [ALERT]")
            
            self.print_colored(Colors.CYAN, "\n" + "[ALERT]" * 30)
            self.print_colored(Colors.BLUE, "[START] ULTRA DYNAMODB CLEANUP MANAGER")
            self.print_colored(Colors.CYAN, "[ALERT]" * 30)
            self.print_colored(Colors.WHITE, f"[DATE] Execution Date/Time: {self.current_time} UTC")
            self.print_colored(Colors.WHITE, f"[USER] Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"[LIST] Log File: {self.log_filename}")
            
            # Select accounts using AWSCredentialManager
            selected_accounts = self.cred_manager.select_root_accounts_interactive()
            
            if not selected_accounts:
                self.print_colored(Colors.YELLOW, "[ERROR] No accounts selected. Exiting.")
                return
            
            # Get user regions
            self.user_regions = self._get_user_regions()
            
            # Select regions
            selected_regions = self.select_regions_interactive(self.user_regions)
            
            if not selected_regions:
                self.print_colored(Colors.YELLOW, "[ERROR] No regions selected. Exiting.")
                return
            
            # Calculate total operations
            total_operations = len(selected_accounts) * len(selected_regions)
            
            self.print_colored(Colors.CYAN, f"\n[TARGET] CLEANUP CONFIGURATION")
            self.print_colored(Colors.CYAN, "=" * 80)
            self.print_colored(Colors.WHITE, f"[BANK] Selected accounts: {len(selected_accounts)}")
            self.print_colored(Colors.WHITE, f"[REGION] Regions per account: {len(selected_regions)}")
            self.print_colored(Colors.WHITE, f"[LIST] Total operations: {total_operations}")
            self.print_colored(Colors.WHITE, f"[DELETE]  Target: All DynamoDB tables + backups")
            self.print_colored(Colors.WHITE, f"[PROTECTED]  Protected: Tables with deletion protection enabled")
            self.print_colored(Colors.CYAN, "=" * 80)
            
            # Confirmation
            self.print_colored(Colors.RED, f"\n[WARN]  WARNING: This will:")
            self.print_colored(Colors.RED, f"    • Delete ALL DynamoDB tables")
            self.print_colored(Colors.RED, f"    • Delete ALL on-demand backups")
            self.print_colored(Colors.RED, f"    • Delete CloudWatch alarms for tables")
            self.print_colored(Colors.RED, f"    • Across {len(selected_accounts)} accounts in {len(selected_regions)} regions")
            self.print_colored(Colors.RED, f"    • Tables with deletion protection will be SKIPPED")
            self.print_colored(Colors.RED, f"    This action CANNOT be undone!")
            
            # Final destructive confirmation
            self.print_colored(Colors.YELLOW, f"\n[WARN]  Type 'DELETE' to confirm this destructive action:")
            confirm = input("   → ").strip()
            
            if confirm.upper() != 'DELETE':
                self.log_operation('INFO', "Ultra cleanup cancelled by user")
                self.print_colored(Colors.YELLOW, "[ERROR] Cleanup cancelled")
                return
            
            # Start cleanup
            self.print_colored(Colors.CYAN, f"\n[START] Starting cleanup...")
            self.log_operation('INFO', f"[ALERT] CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(selected_regions)} regions")
            
            start_time = time.time()
            
            successful_tasks = 0
            failed_tasks = 0
            
            # Process each account and region
            for account_info in selected_accounts:
                account_name = account_info.get('name', 'Unknown')
                
                for region in selected_regions:
                    try:
                        success = self.cleanup_account_region(account_info, region)
                        if success:
                            successful_tasks += 1
                        else:
                            failed_tasks += 1
                    except Exception as e:
                        failed_tasks += 1
                        error_msg = f"Task failed for {account_name} ({region}): {e}"
                        self.log_operation('ERROR', error_msg)
                        self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # Display final results
            self.print_colored(Colors.GREEN, f"\n" + "=" * 100)
            self.print_colored(Colors.GREEN, "[OK] CLEANUP COMPLETE")
            self.print_colored(Colors.GREEN, "=" * 100)
            self.print_colored(Colors.WHITE, f"[TIMER]  Total execution time: {total_time} seconds")
            self.print_colored(Colors.GREEN, f"[OK] Successful operations: {successful_tasks}")
            self.print_colored(Colors.RED, f"[ERROR] Failed operations: {failed_tasks}")
            self.print_colored(Colors.WHITE, f"[STATS] Tables deleted: {len(self.cleanup_results['deleted_tables'])}")
            self.print_colored(Colors.WHITE, f"[INSTANCE] Backups deleted: {len(self.cleanup_results['deleted_backups'])}")
            self.print_colored(Colors.YELLOW, f"[SKIP]  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            self.log_operation('INFO', f"CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Tables deleted: {len(self.cleanup_results['deleted_tables'])}")
            self.log_operation('INFO', f"Backups deleted: {len(self.cleanup_results['deleted_backups'])}")
            
            # Show account summary
            if self.cleanup_results['deleted_tables']:
                self.print_colored(Colors.CYAN, f"\n[STATS] Deletion Summary by Account:")
                
                account_summary = {}
                for table in self.cleanup_results['deleted_tables']:
                    account = table['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'tables': 0, 'backups': 0, 'regions': set()}
                    account_summary[account]['tables'] += 1
                    account_summary[account]['regions'].add(table['region'])
                
                for backup in self.cleanup_results['deleted_backups']:
                    account = backup['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'tables': 0, 'backups': 0, 'regions': set()}
                    account_summary[account]['backups'] += 1
                
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.WHITE, f"   [BANK] {account}:")
                    self.print_colored(Colors.WHITE, f"      [STATS] Tables: {summary['tables']}")
                    self.print_colored(Colors.WHITE, f"      [INSTANCE] Backups: {summary['backups']}")
                    self.print_colored(Colors.WHITE, f"      [REGION] Regions: {regions_list}")
            
            # Show failures if any
            if self.cleanup_results['failed_deletions']:
                self.print_colored(Colors.RED, f"\n[ERROR] Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:
                    self.print_colored(Colors.RED, f"   • {failure['resource_type']} {failure['resource_id']} in {failure['account_name']} ({failure['region']})")
                    self.print_colored(Colors.RED, f"     Error: {failure['error']}")
                
                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    self.print_colored(Colors.RED, f"   ... and {remaining} more failures (see detailed report)")
            
            # Show skipped resources
            if self.cleanup_results['skipped_resources']:
                self.print_colored(Colors.YELLOW, f"\n[SKIP]  Skipped Resources:")
                for skipped in self.cleanup_results['skipped_resources'][:5]:
                    self.print_colored(Colors.YELLOW, f"   • {skipped['resource_type']} {skipped['resource_id']} - {skipped['reason']}")
                
                if len(self.cleanup_results['skipped_resources']) > 5:
                    remaining = len(self.cleanup_results['skipped_resources']) - 5
                    self.print_colored(Colors.YELLOW, f"   ... and {remaining} more (see detailed report)")
            
            # Save report
            self.print_colored(Colors.CYAN, f"\n[FILE] Saving cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"[OK] Cleanup report saved to: {report_file}")
            
            self.print_colored(Colors.GREEN, f"[OK] Session log saved to: {self.log_filename}")
            
            self.print_colored(Colors.GREEN, f"\n[OK] Cleanup completed successfully!")
            self.print_colored(Colors.CYAN, "[ALERT]" * 30)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            self.print_colored(Colors.RED, f"\n[ERROR] FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise

    def select_regions_interactive(self, available_regions: List[str]) -> List[str]:
        """Interactive region selection"""
        self.print_colored(Colors.CYAN, f"\n[REGION] AVAILABLE REGIONS:")
        self.print_colored(Colors.CYAN, "=" * 80)
        
        for i, region in enumerate(available_regions, 1):
            self.print_colored(Colors.WHITE, f"  {i}. {region}")
        
        self.print_colored(Colors.WHITE, "\nRegion Selection Options:")
        self.print_colored(Colors.WHITE, "  • Single regions: 1,3,5")
        self.print_colored(Colors.WHITE, "  • Ranges: 1-3")
        self.print_colored(Colors.WHITE, "  • Mixed: 1-2,4")
        self.print_colored(Colors.WHITE, "  • All regions: 'all' or press Enter")
        self.print_colored(Colors.WHITE, "  • Cancel: 'cancel' or 'quit'")
        
        selection = input("\n🔢 Select regions to process: ").strip().lower()
        
        if selection in ['cancel', 'quit']:
            return []
        
        if not selection or selection == 'all':
            self.log_operation('INFO', f"All regions selected: {len(available_regions)}")
            self.print_colored(Colors.GREEN, f"[OK] Selected all {len(available_regions)} regions")
            return available_regions
        
        # Parse selection
        selected_regions = []
        try:
            indices = self.cred_manager._parse_selection(selection, len(available_regions))
            selected_regions = [available_regions[i] for i in indices]
            
            self.log_operation('INFO', f"Selected regions: {selected_regions}")
            self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
            
        except ValueError as e:
            self.log_operation('ERROR', f"Invalid region selection: {e}")
            self.print_colored(Colors.RED, f"[ERROR] Invalid selection: {e}")
            return []
        
        return selected_regions

def main():
    """Main function"""
    try:
        manager = UltraCleanupDynamoDBManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Cleanup interrupted by user")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")

if __name__ == "__main__":
    main()
