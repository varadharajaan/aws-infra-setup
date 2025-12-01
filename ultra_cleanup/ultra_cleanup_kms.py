#!/usr/bin/env python3
"""
Ultra KMS Cleanup Manager
Comprehensive AWS KMS (Key Management Service) cleanup across multiple AWS accounts and regions
- Schedules Customer Managed Keys (CMKs) for deletion
- Deletes Key Aliases
- Cancels Key Deletion (optional recovery mode)
- Skips AWS Managed Keys
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


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    END = '\033[0m'


class UltraCleanupKMSManager:
    """Manager for comprehensive KMS cleanup operations"""

    def __init__(self):
        """Initialize the KMS cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'kms')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'kms_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'scheduled_for_deletion': [],
            'deleted_aliases': [],
            'skipped_aws_managed': [],
            'failed_deletions': [],
            'errors': []
        }
        
        # Deletion waiting period (days)
        self.pending_window_days = 30  # Default 30 days (AWS minimum is 7, max is 30)

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_key_alias(self, kms_client, alias_name, region, account_key):
        """Delete a KMS key alias"""
        try:
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting alias: {alias_name}")
            
            kms_client.delete_alias(AliasName=alias_name)
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted alias: {alias_name}")
            self.log_action(f"Deleted alias: {alias_name} in {region}")
            
            self.cleanup_results['deleted_aliases'].append({
                'alias_name': alias_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete alias {alias_name}: {e}"
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def schedule_key_deletion(self, kms_client, key_id, key_metadata, region, account_key):
        """Schedule a KMS key for deletion"""
        try:
            key_manager = key_metadata.get('KeyManager', 'CUSTOMER')
            key_state = key_metadata.get('KeyState', '')
            
            # Skip AWS managed keys
            if key_manager == 'AWS':
                self.print_colored(Colors.YELLOW, f"[SKIP] AWS managed key: {key_id}")
                self.cleanup_results['skipped_aws_managed'].append({
                    'key_id': key_id,
                    'region': region,
                    'account_key': account_key
                })
                return True
            
            # Skip keys already pending deletion
            if key_state == 'PendingDeletion':
                self.print_colored(Colors.YELLOW, f"[SKIP] Key already pending deletion: {key_id}")
                return True
            
            # Skip keys that are not enabled or disabled
            if key_state not in ['Enabled', 'Disabled']:
                self.print_colored(Colors.YELLOW, f"[SKIP] Key in state {key_state}: {key_id}")
                return True
            
            self.print_colored(Colors.CYAN, f"[DELETE] Scheduling key for deletion: {key_id}")
            
            # Delete all aliases for this key first
            try:
                aliases_response = kms_client.list_aliases(KeyId=key_id)
                aliases = aliases_response.get('Aliases', [])
                
                for alias in aliases:
                    alias_name = alias.get('AliasName', '')
                    if alias_name and not alias_name.startswith('alias/aws/'):
                        self.delete_key_alias(kms_client, alias_name, region, account_key)
                        time.sleep(0.3)
            except ClientError:
                pass  # Key may not have aliases
            
            # Disable key if enabled
            if key_state == 'Enabled':
                try:
                    kms_client.disable_key(KeyId=key_id)
                    self.print_colored(Colors.YELLOW, f"   [DISABLE] Disabled key: {key_id}")
                except ClientError:
                    pass
            
            # Schedule key deletion
            response = kms_client.schedule_key_deletion(
                KeyId=key_id,
                PendingWindowInDays=self.pending_window_days
            )
            
            deletion_date = response.get('DeletionDate', 'Unknown')
            
            self.print_colored(Colors.GREEN, f"[OK] Scheduled for deletion ({self.pending_window_days} days): {key_id}")
            self.print_colored(Colors.YELLOW, f"   [DATE] Deletion date: {deletion_date}")
            self.log_action(f"Scheduled key deletion: {key_id} in {region}, deletion date: {deletion_date}")
            
            self.cleanup_results['scheduled_for_deletion'].append({
                'key_id': key_id,
                'deletion_date': str(deletion_date),
                'pending_days': self.pending_window_days,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to schedule key deletion {key_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Key',
                'key_id': key_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_kms(self, account_name, credentials, region):
        """Cleanup all KMS resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            kms_client = boto3.client(
                'kms',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # List all keys
            try:
                paginator = kms_client.get_paginator('list_keys')
                keys = []
                
                for page in paginator.paginate():
                    keys.extend(page.get('Keys', []))
                
                if keys:
                    # Filter customer managed keys
                    customer_keys = []
                    for key in keys:
                        try:
                            metadata = kms_client.describe_key(KeyId=key['KeyId'])
                            key_metadata = metadata.get('KeyMetadata', {})
                            
                            if key_metadata.get('KeyManager') == 'CUSTOMER':
                                customer_keys.append({
                                    'KeyId': key['KeyId'],
                                    'Metadata': key_metadata
                                })
                        except ClientError:
                            pass
                    
                    if customer_keys:
                        self.print_colored(Colors.CYAN, f"[KMS] Found {len(customer_keys)} customer managed keys")
                        for key in customer_keys:
                            self.schedule_key_deletion(
                                kms_client,
                                key['KeyId'],
                                key['Metadata'],
                                region,
                                account_name
                            )
                            time.sleep(0.5)
                    else:
                        self.print_colored(Colors.YELLOW, f"[SKIP] No customer managed keys found")
            except ClientError as e:
                self.log_action(f"Error listing keys in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_kms(self, account_name, credentials):
        """Cleanup all KMS resources in an account across all regions"""
        try:
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, f"[START] Processing Account: {account_name}")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            
            self.cleanup_results['accounts_processed'].append(account_name)
            
            # Get all regions
            ec2_client = boto3.client(
                'ec2',
                region_name='us-east-1',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            regions_response = ec2_client.describe_regions()
            regions = [region['RegionName'] for region in regions_response['Regions']]
            
            self.print_colored(Colors.CYAN, f"[SCAN] Processing {len(regions)} regions")
            
            # Process each region
            for region in regions:
                self.cleanup_region_kms(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"kms_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'pending_window_days': self.pending_window_days,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_keys_scheduled_for_deletion': len(self.cleanup_results['scheduled_for_deletion']),
                    'total_aliases_deleted': len(self.cleanup_results['deleted_aliases']),
                    'total_aws_managed_keys_skipped': len(self.cleanup_results['skipped_aws_managed']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n[STATS] Summary report saved: {report_path}")

            # Print summary to console
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            self.print_colored(Colors.GREEN, f"[OK] Keys Scheduled for Deletion: {summary['summary']['total_keys_scheduled_for_deletion']}")
            self.print_colored(Colors.GREEN, f"[OK] Key Aliases Deleted: {summary['summary']['total_aliases_deleted']}")
            self.print_colored(Colors.YELLOW, f"[SKIP] AWS Managed Keys Skipped: {summary['summary']['total_aws_managed_keys_skipped']}")
            self.print_colored(Colors.CYAN, f"[INFO] Pending Window: {self.pending_window_days} days")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for item_list, key_name in [
                (self.cleanup_results['scheduled_for_deletion'], 'keys_scheduled'),
                (self.cleanup_results['deleted_aliases'], 'aliases_deleted')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'keys_scheduled': 0,
                            'aliases_deleted': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Keys Scheduled for Deletion: {stats['keys_scheduled']}")
                self.print_colored(Colors.GREEN, f"  [OK] Aliases Deleted: {stats['aliases_deleted']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for KMS cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA KMS CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for KMS Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"[OK] Loaded {len(accounts)} root accounts")
            
            self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
            print("=" * 100)
            
            for idx, account_name in enumerate(account_list, 1):
                account_data = accounts[account_name]
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'N/A')
                user_count = len(account_data.get('users', []))
                
                print(f"   {idx}. {account_name} (ID: {account_id})")
                print(f"      Email: {email}, Users: {user_count}")
            
            print("=" * 100)
            self.print_colored(Colors.BLUE, "[TIP] Selection options:")
            print("   - Single: 1")
            print("   - Multiple: 1,3,5")
            print("   - All: all")
            print("=" * 100)

            selection = input(f"Select accounts (1-{len(account_list)}, comma-separated, or 'all') or 'q' to quit: ").strip()

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
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection!")
                    return

            if not selected_accounts:
                self.print_colored(Colors.RED, "[ERROR] No accounts selected!")
                return

            # Ask for pending window
            self.print_colored(Colors.YELLOW, "\n[OPTION] Deletion Pending Window:")
            print("   AWS allows 7-30 days before permanent deletion")
            print("   During this time, you can cancel the deletion")
            pending_input = input(f"\nEnter pending window in days (7-30, default: 30): ").strip()
            
            if pending_input:
                try:
                    pending_days = int(pending_input)
                    if 7 <= pending_days <= 30:
                        self.pending_window_days = pending_days
                    else:
                        self.print_colored(Colors.YELLOW, "[WARN] Invalid range, using default: 30 days")
                except ValueError:
                    self.print_colored(Colors.YELLOW, "[WARN] Invalid input, using default: 30 days")

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will SCHEDULE all Customer Managed KMS Keys for deletion!")
            self.print_colored(Colors.YELLOW, f"[INFO] Keys will be deleted after {self.pending_window_days} days")
            self.print_colored(Colors.YELLOW, "[INFO] AWS Managed Keys will be skipped automatically")
            confirm = input(f"\nType 'DELETE' to confirm: ").strip()
            if confirm != 'DELETE':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_kms(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] KMS cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupKMSManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
