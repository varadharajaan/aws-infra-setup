#!/usr/bin/env python3
"""
Ultra Secrets Manager Cleanup Manager
Comprehensive AWS Secrets Manager cleanup across multiple AWS accounts and regions
- Deletes Secrets (with recovery window or force delete)
- Removes Resource Policies
- Cancels Rotation Configurations
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


class UltraCleanupSecretsManagerManager:
    """Manager for comprehensive Secrets Manager cleanup operations"""

    def __init__(self):
        """Initialize the Secrets Manager cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'secrets_manager')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'secrets_manager_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_secrets': [],
            'force_deleted_secrets': [],
            'failed_deletions': [],
            'errors': []
        }
        
        # Force delete flag (set during interactive prompt)
        self.force_delete = False

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_secret(self, sm_client, secret_arn, secret_name, region, account_key):
        """Delete a secret from Secrets Manager"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting secret: {secret_name}")
            
            # Cancel rotation if enabled
            try:
                sm_client.cancel_rotate_secret(SecretId=secret_arn)
                self.print_colored(Colors.YELLOW, f"   [CANCEL] Cancelled rotation for: {secret_name}")
            except ClientError:
                pass  # Secret may not have rotation enabled
            
            # Delete resource policy if exists
            try:
                sm_client.delete_resource_policy(SecretId=secret_arn)
                self.print_colored(Colors.YELLOW, f"   [POLICY] Removed resource policy for: {secret_name}")
            except ClientError:
                pass  # Secret may not have resource policy
            
            # Delete the secret
            if self.force_delete:
                # Force delete without recovery window
                sm_client.delete_secret(
                    SecretId=secret_arn,
                    ForceDeleteWithoutRecovery=True
                )
                self.print_colored(Colors.GREEN, f"[OK] Force deleted secret: {secret_name}")
                self.log_action(f"Force deleted secret: {secret_name} in {region}")
                
                self.cleanup_results['force_deleted_secrets'].append({
                    'secret_arn': secret_arn,
                    'secret_name': secret_name,
                    'region': region,
                    'account_key': account_key
                })
            else:
                # Delete with 7-day recovery window
                sm_client.delete_secret(
                    SecretId=secret_arn,
                    RecoveryWindowInDays=7
                )
                self.print_colored(Colors.GREEN, f"[OK] Deleted secret (7-day recovery): {secret_name}")
                self.log_action(f"Deleted secret with recovery window: {secret_name} in {region}")
                
                self.cleanup_results['deleted_secrets'].append({
                    'secret_arn': secret_arn,
                    'secret_name': secret_name,
                    'region': region,
                    'account_key': account_key
                })
            
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete secret {secret_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Secret',
                'name': secret_name,
                'arn': secret_arn,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_secrets(self, account_name, credentials, region):
        """Cleanup all Secrets Manager resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            sm_client = boto3.client(
                'secretsmanager',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # List all secrets (including scheduled for deletion)
            try:
                paginator = sm_client.get_paginator('list_secrets')
                secrets = []
                
                for page in paginator.paginate():
                    secrets.extend(page.get('SecretList', []))
                
                if secrets:
                    # Filter out secrets already scheduled for deletion (unless force delete)
                    active_secrets = []
                    for secret in secrets:
                        if 'DeletedDate' in secret and not self.force_delete:
                            self.print_colored(Colors.YELLOW, f"[SKIP] Secret already scheduled for deletion: {secret['Name']}")
                            continue
                        active_secrets.append(secret)
                    
                    if active_secrets:
                        self.print_colored(Colors.CYAN, f"[SECRET] Found {len(active_secrets)} active secrets")
                        for secret in active_secrets:
                            self.delete_secret(
                                sm_client,
                                secret['ARN'],
                                secret['Name'],
                                region,
                                account_name
                            )
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing secrets in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_secrets(self, account_name, credentials):
        """Cleanup all Secrets Manager resources in an account across all regions"""
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
                self.cleanup_region_secrets(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"secrets_manager_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'force_delete_mode': self.force_delete,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_secrets_deleted': len(self.cleanup_results['deleted_secrets']),
                    'total_secrets_force_deleted': len(self.cleanup_results['force_deleted_secrets']),
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
            
            if self.force_delete:
                self.print_colored(Colors.GREEN, f"[OK] Secrets Force Deleted: {summary['summary']['total_secrets_force_deleted']}")
            else:
                self.print_colored(Colors.GREEN, f"[OK] Secrets Deleted (7-day recovery): {summary['summary']['total_secrets_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            all_secrets = self.cleanup_results['deleted_secrets'] + self.cleanup_results['force_deleted_secrets']
            
            for secret in all_secrets:
                account = secret.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {'secrets': 0, 'regions': set()}
                account_summary[account]['secrets'] += 1
                account_summary[account]['regions'].add(secret.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Secrets Deleted: {stats['secrets']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for Secrets Manager cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA SECRETS MANAGER CLEANUP")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Secrets Manager Cleanup:")
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

            # Ask about force delete
            self.print_colored(Colors.YELLOW, "\n[OPTION] Delete Mode:")
            print("   1. Standard (7-day recovery window) - Secrets can be recovered within 7 days")
            print("   2. Force Delete (immediate, no recovery) - Secrets deleted permanently")
            delete_mode = input("\nSelect delete mode (1 or 2, default: 1): ").strip()
            
            if delete_mode == '2':
                self.force_delete = True
                self.print_colored(Colors.RED, "\n[WARN] WARNING: FORCE DELETE MODE - Secrets will be deleted PERMANENTLY!")
            else:
                self.force_delete = False
                self.print_colored(Colors.YELLOW, "\n[INFO] Standard mode: Secrets will have 7-day recovery window")

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all Secrets Manager secrets!")
            confirm = input(f"\nType 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_secrets(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Secrets Manager cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupSecretsManagerManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
