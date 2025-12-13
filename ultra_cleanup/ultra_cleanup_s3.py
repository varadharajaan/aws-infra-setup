#!/usr/bin/env python3
"""
Ultra S3 Cleanup Manager
Comprehensive S3 bucket cleanup across multiple AWS accounts
- Disables versioning
- Deletes all object versions
- Removes bucket policies, notifications, lifecycle rules, CORS, website config
- Deletes all buckets (with exclusion list support)
"""

import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import json
import time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager
from text_symbols import Symbols


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    END = '\033[0m'


class UltraCleanupS3Manager:
    """Manager for comprehensive S3 bucket cleanup operations"""

    def __init__(self):
        """Initialize the S3 cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 's3')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f's3_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Excluded buckets (to be skipped during cleanup)
        self.excluded_buckets = []
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_buckets': [],
            'excluded_buckets': [],
            'versioning_disabled': [],
            'objects_deleted': [],
            'policies_removed': [],
            'notifications_removed': [],
            'lifecycle_removed': [],
            'cors_removed': [],
            'website_removed': [],
            'encryption_removed': [],
            'logging_removed': [],
            'accelerate_removed': [],
            'replication_removed': [],
            'tagging_removed': [],
            'failed_deletions': [],
            'errors': []
        }

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_all_objects(self, s3_client, bucket_name, region):
        """Delete all objects and versions from a bucket"""
        try:
            self.print_colored(Colors.CYAN, f"   {Symbols.DELETE} Deleting all objects and versions...")
            
            # List and delete all object versions
            paginator = s3_client.get_paginator('list_object_versions')
            delete_count = 0
            
            for page in paginator.paginate(Bucket=bucket_name):
                objects_to_delete = []
                
                # Add all versions
                if 'Versions' in page:
                    for version in page['Versions']:
                        objects_to_delete.append({
                            'Key': version['Key'],
                            'VersionId': version['VersionId']
                        })
                
                # Add all delete markers
                if 'DeleteMarkers' in page:
                    for marker in page['DeleteMarkers']:
                        objects_to_delete.append({
                            'Key': marker['Key'],
                            'VersionId': marker['VersionId']
                        })
                
                # Delete in batches of 1000 (AWS limit)
                if objects_to_delete:
                    s3_client.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': objects_to_delete, 'Quiet': True}
                    )
                    delete_count += len(objects_to_delete)
            
            if delete_count > 0:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Deleted {delete_count} objects/versions")
                self.log_action(f"Deleted {delete_count} objects/versions from {bucket_name}")
                self.cleanup_results['objects_deleted'].append({
                    'bucket': bucket_name,
                    'region': region,
                    'count': delete_count
                })
            else:
                self.print_colored(Colors.YELLOW, f"   {Symbols.SKIP} No objects found")
                
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete objects from {bucket_name}: {e}"
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def disable_versioning(self, s3_client, bucket_name, region):
        """Disable versioning on a bucket"""
        try:
            s3_client.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={'Status': 'Suspended'}
            )
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Versioning disabled")
            self.log_action(f"Disabled versioning for {bucket_name}")
            self.cleanup_results['versioning_disabled'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchBucketVersioning':
                error_msg = f"Failed to disable versioning for {bucket_name}: {e}"
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} {error_msg}")
                self.log_action(error_msg, "WARNING")
            return False

    def remove_bucket_policy(self, s3_client, bucket_name, region):
        """Remove bucket policy"""
        try:
            s3_client.delete_bucket_policy(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Bucket policy removed")
            self.log_action(f"Removed bucket policy from {bucket_name}")
            self.cleanup_results['policies_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchBucketPolicy':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove policy: {e.response['Error']['Code']}")
            return False

    def remove_bucket_notifications(self, s3_client, bucket_name, region):
        """Remove all bucket notifications"""
        try:
            s3_client.put_bucket_notification_configuration(
                Bucket=bucket_name,
                NotificationConfiguration={}
            )
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Notifications removed")
            self.log_action(f"Removed notifications from {bucket_name}")
            self.cleanup_results['notifications_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove notifications: {e.response['Error']['Code']}")
            return False

    def remove_bucket_lifecycle(self, s3_client, bucket_name, region):
        """Remove lifecycle configuration"""
        try:
            s3_client.delete_bucket_lifecycle(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Lifecycle rules removed")
            self.log_action(f"Removed lifecycle rules from {bucket_name}")
            self.cleanup_results['lifecycle_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchLifecycleConfiguration':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove lifecycle: {e.response['Error']['Code']}")
            return False

    def remove_bucket_cors(self, s3_client, bucket_name, region):
        """Remove CORS configuration"""
        try:
            s3_client.delete_bucket_cors(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} CORS configuration removed")
            self.log_action(f"Removed CORS from {bucket_name}")
            self.cleanup_results['cors_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchCORSConfiguration':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove CORS: {e.response['Error']['Code']}")
            return False

    def remove_bucket_website(self, s3_client, bucket_name, region):
        """Remove website configuration"""
        try:
            s3_client.delete_bucket_website(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Website configuration removed")
            self.log_action(f"Removed website config from {bucket_name}")
            self.cleanup_results['website_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchWebsiteConfiguration':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove website: {e.response['Error']['Code']}")
            return False

    def remove_bucket_encryption(self, s3_client, bucket_name, region):
        """Remove encryption configuration"""
        try:
            s3_client.delete_bucket_encryption(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Encryption configuration removed")
            self.log_action(f"Removed encryption from {bucket_name}")
            self.cleanup_results['encryption_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'ServerSideEncryptionConfigurationNotFoundError':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove encryption: {e.response['Error']['Code']}")
            return False

    def remove_bucket_logging(self, s3_client, bucket_name, region):
        """Remove logging configuration"""
        try:
            s3_client.put_bucket_logging(
                Bucket=bucket_name,
                BucketLoggingStatus={}
            )
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Logging configuration removed")
            self.log_action(f"Removed logging from {bucket_name}")
            self.cleanup_results['logging_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove logging: {e.response['Error']['Code']}")
            return False

    def remove_bucket_accelerate(self, s3_client, bucket_name, region):
        """Remove transfer acceleration configuration"""
        try:
            s3_client.put_bucket_accelerate_configuration(
                Bucket=bucket_name,
                AccelerateConfiguration={'Status': 'Suspended'}
            )
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Transfer acceleration disabled")
            self.log_action(f"Disabled acceleration for {bucket_name}")
            self.cleanup_results['accelerate_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to disable acceleration: {e.response['Error']['Code']}")
            return False

    def remove_bucket_replication(self, s3_client, bucket_name, region):
        """Remove replication configuration"""
        try:
            s3_client.delete_bucket_replication(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Replication configuration removed")
            self.log_action(f"Removed replication from {bucket_name}")
            self.cleanup_results['replication_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'ReplicationConfigurationNotFoundError':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove replication: {e.response['Error']['Code']}")
            return False

    def remove_bucket_tagging(self, s3_client, bucket_name, region):
        """Remove bucket tagging"""
        try:
            s3_client.delete_bucket_tagging(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Bucket tagging removed")
            self.log_action(f"Removed tagging from {bucket_name}")
            self.cleanup_results['tagging_removed'].append({
                'bucket': bucket_name,
                'region': region
            })
            return True
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchTagSet':
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN} Failed to remove tagging: {e.response['Error']['Code']}")
            return False

    def cleanup_bucket(self, s3_client, bucket_name, region, account_key):
        """Complete cleanup of a single bucket"""
        try:
            self.print_colored(Colors.CYAN, f"\n{Symbols.SCAN} Processing bucket: {bucket_name} (Region: {region})")
            
            # Check if bucket is in exclusion list
            if bucket_name in self.excluded_buckets:
                self.print_colored(Colors.YELLOW, f"   {Symbols.SKIP} Bucket is in exclusion list")
                self.log_action(f"Skipped excluded bucket: {bucket_name}")
                self.cleanup_results['excluded_buckets'].append({
                    'bucket': bucket_name,
                    'region': region,
                    'account_key': account_key
                })
                return
            
            # Step 1: Remove replication configuration FIRST (required before disabling versioning)
            self.remove_bucket_replication(s3_client, bucket_name, region)
            
            # Step 2: Disable versioning (now possible after replication is removed)
            self.disable_versioning(s3_client, bucket_name, region)
            
            # Step 3: Remove other bucket configurations
            self.remove_bucket_policy(s3_client, bucket_name, region)
            self.remove_bucket_notifications(s3_client, bucket_name, region)
            self.remove_bucket_lifecycle(s3_client, bucket_name, region)
            self.remove_bucket_cors(s3_client, bucket_name, region)
            self.remove_bucket_website(s3_client, bucket_name, region)
            self.remove_bucket_encryption(s3_client, bucket_name, region)
            self.remove_bucket_logging(s3_client, bucket_name, region)
            self.remove_bucket_accelerate(s3_client, bucket_name, region)
            self.remove_bucket_tagging(s3_client, bucket_name, region)
            
            # Step 3: Delete all objects and versions
            if not self.delete_all_objects(s3_client, bucket_name, region):
                self.cleanup_results['failed_deletions'].append({
                    'bucket': bucket_name,
                    'region': region,
                    'reason': 'Failed to delete objects',
                    'account_key': account_key
                })
                return
            
            # Step 4: Delete the bucket
            s3_client.delete_bucket(Bucket=bucket_name)
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted bucket: {bucket_name}")
            self.log_action(f"Deleted bucket: {bucket_name} in region {region}")
            
            self.cleanup_results['deleted_buckets'].append({
                'bucket': bucket_name,
                'region': region,
                'account_key': account_key
            })
            
        except ClientError as e:
            error_msg = f"Failed to delete bucket {bucket_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'bucket': bucket_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })

    def cleanup_account_s3_buckets(self, account_name, credentials):
        """Cleanup all S3 buckets in an account"""
        try:
            self.print_colored(Colors.BLUE, f"\n{'='*80}")
            self.print_colored(Colors.BLUE, f"{Symbols.START} Processing Account: {account_name}")
            self.print_colored(Colors.BLUE, f"{'='*80}")
            
            self.cleanup_results['accounts_processed'].append(account_name)
            
            # Create S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # List all buckets
            response = s3_client.list_buckets()
            buckets = response.get('Buckets', [])
            
            if not buckets:
                self.print_colored(Colors.YELLOW, f"{Symbols.SKIP} No buckets found in account")
                return
            
            self.print_colored(Colors.CYAN, f"{Symbols.SCAN} Found {len(buckets)} buckets")
            
            # Process each bucket
            for bucket in buckets:
                bucket_name = bucket['Name']
                
                try:
                    # Get bucket region
                    location = s3_client.get_bucket_location(Bucket=bucket_name)
                    region = location.get('LocationConstraint') or 'us-east-1'
                    
                    # Create regional client
                    regional_s3_client = boto3.client(
                        's3',
                        region_name=region,
                        aws_access_key_id=credentials['access_key'],
                        aws_secret_access_key=credentials['secret_key']
                    )
                    
                    self.cleanup_bucket(regional_s3_client, bucket_name, region, account_name)
                    
                except Exception as e:
                    error_msg = f"Error processing bucket {bucket_name}: {e}"
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
                    self.log_action(error_msg, "ERROR")
                    self.cleanup_results['errors'].append(error_msg)
            
            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"s3_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'excluded_buckets_list': self.excluded_buckets,
                'summary': {
                    'total_buckets_deleted': len(self.cleanup_results['deleted_buckets']),
                    'total_buckets_excluded': len(self.cleanup_results['excluded_buckets']),
                    'total_objects_deleted': sum(obj['count'] for obj in self.cleanup_results['objects_deleted']),
                    'total_versioning_disabled': len(self.cleanup_results['versioning_disabled']),
                    'total_policies_removed': len(self.cleanup_results['policies_removed']),
                    'total_notifications_removed': len(self.cleanup_results['notifications_removed']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n{Symbols.STATS} Summary report saved: {report_path}")
            self.log_action(f"Summary report saved: {report_path}")

            # Print summary to console
            self.print_colored(Colors.BLUE, f"\n{'='*80}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*80}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Buckets Deleted: {summary['summary']['total_buckets_deleted']}")
            self.print_colored(Colors.YELLOW, f"{Symbols.SKIP} Buckets Excluded: {summary['summary']['total_buckets_excluded']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Objects Deleted: {summary['summary']['total_objects_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Versioning Disabled: {summary['summary']['total_versioning_disabled']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Policies Removed: {summary['summary']['total_policies_removed']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Notifications Removed: {summary['summary']['total_notifications_removed']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN} Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*80}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*80}")

            account_summary = {}

            # Aggregate deleted buckets by account
            for bucket in self.cleanup_results['deleted_buckets']:
                account = bucket.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'buckets_deleted': 0,
                        'buckets_excluded': 0,
                        'regions': set()
                    }
                account_summary[account]['buckets_deleted'] += 1
                account_summary[account]['regions'].add(bucket.get('region', 'unknown'))

            # Aggregate excluded buckets by account
            for bucket in self.cleanup_results['excluded_buckets']:
                account = bucket.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'buckets_deleted': 0,
                        'buckets_excluded': 0,
                        'regions': set()
                    }
                account_summary[account]['buckets_excluded'] += 1
                account_summary[account]['regions'].add(bucket.get('region', 'unknown'))

            # Display account summary
            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n{Symbols.LIST} Account: {account}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Buckets Deleted: {stats['buckets_deleted']}")
                self.print_colored(Colors.YELLOW, f"  {Symbols.SKIP} Buckets Excluded: {stats['buckets_excluded']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  {Symbols.SCAN} Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to generate summary report: {e}")
            self.log_action(f"Failed to generate summary report: {e}", "ERROR")

    def interactive_cleanup(self):
        """Interactive mode for S3 cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*80)
            self.print_colored(Colors.BLUE, "[START] ULTRA S3 CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*80)

            # Load accounts
            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} No accounts configuration found!")
                return

            accounts = config['accounts']

            # Display accounts with detailed info
            self.print_colored(Colors.CYAN, f"{Symbols.KEY} Select Root AWS Accounts for S3 Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Loaded {len(accounts)} root accounts")
            
            self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
            print("=" * 100)
            
            account_list = list(accounts.keys())
            for idx, account_name in enumerate(account_list, 1):
                account_data = accounts[account_name]
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'N/A')
                
                # Count users in this account
                user_count = 0
                if 'users' in account_data and isinstance(account_data['users'], list):
                    user_count = len(account_data['users'])
                
                print(f"   {idx}. {account_name} (ID: {account_id})")
                print(f"      Email: {email}, Users: {user_count}")
            
            print("=" * 100)
            self.print_colored(Colors.BLUE, "[TIP] Selection options:")
            print("   - Single: 1")
            print("   - Multiple: 1,3,5")
            print("   - Range: 1-5")
            print("   - All: all")
            print("=" * 100)

            # Account selection
            selection = input(f"Select accounts (1-{len(account_list)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

            if selection.lower() == 'q':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            selected_accounts = []
            if selection.lower() == 'all':
                selected_accounts = account_list
            else:
                try:
                    indices = [int(x.strip()) for x in selection.split(',')]
                    selected_accounts = [account_list[i-1] for i in indices if 0 < i <= len(account_list)]
                except (ValueError, IndexError):
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Invalid selection!")
                    return

            if not selected_accounts:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} No accounts selected!")
                return

            # Bucket exclusion list
            self.print_colored(Colors.YELLOW, "\n[CONFIG] Bucket Exclusion List:")
            self.print_colored(Colors.CYAN, "Enter bucket names to exclude (comma-separated), or press Enter to skip:")
            exclusion_input = input(f"{Colors.GREEN}Excluded buckets: {Colors.END}").strip()
            
            if exclusion_input:
                self.excluded_buckets = [b.strip() for b in exclusion_input.split(',') if b.strip()]
                self.print_colored(Colors.YELLOW, f"[CONFIG] Excluding {len(self.excluded_buckets)} buckets: {', '.join(self.excluded_buckets)}")
            else:
                self.print_colored(Colors.CYAN, "[CONFIG] No buckets excluded")

            # Confirm deletion
            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all S3 buckets and their contents!")
            self.print_colored(Colors.RED, "[WARN] This action is IRREVERSIBLE!")
            self.print_colored(Colors.YELLOW, f"{Symbols.INFO} Accounts: {len(selected_accounts)}")
            self.print_colored(Colors.YELLOW, f"{Symbols.INFO} Excluded buckets: {len(self.excluded_buckets)}")
            
            confirm = input(f"\nType 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            # Process selected accounts
            self.log_action(f"Starting cleanup for accounts: {selected_accounts}")
            self.log_action(f"Excluded buckets: {self.excluded_buckets}")

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_s3_buckets(account_name, credentials)
                time.sleep(2)  # Delay between accounts

            # Generate summary
            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} S3 cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
            self.log_action("Cleanup interrupted by user", "WARNING")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} Error during cleanup: {e}")
            self.log_action(f"Error during cleanup: {e}", "ERROR")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupS3Manager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n{Symbols.ERROR} Fatal error: {e}")


if __name__ == "__main__":
    main()
