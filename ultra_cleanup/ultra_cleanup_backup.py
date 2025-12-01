#!/usr/bin/env python3
"""
Ultra AWS Backup Cleanup Manager
Comprehensive AWS Backup cleanup across multiple AWS accounts and regions
- Deletes Recovery Points
- Deletes Backup Plans
- Deletes Backup Vaults (after recovery points are deleted)
- Removes Backup Vault Access Policies
- Removes Backup Vault Notifications
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


class UltraCleanupBackupManager:
    """Manager for comprehensive AWS Backup cleanup operations"""

    def __init__(self):
        """Initialize the AWS Backup cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'backup')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'backup_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_recovery_points': [],
            'deleted_backup_plans': [],
            'deleted_backup_vaults': [],
            'failed_deletions': [],
            'errors': []
        }

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_recovery_point(self, backup_client, vault_name, recovery_point_arn, region, account_key):
        """Delete a recovery point from a backup vault"""
        try:
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting recovery point: {recovery_point_arn.split('/')[-1]}")
            
            backup_client.delete_recovery_point(
                BackupVaultName=vault_name,
                RecoveryPointArn=recovery_point_arn
            )
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted recovery point")
            self.log_action(f"Deleted recovery point: {recovery_point_arn} from vault {vault_name} in {region}")
            
            self.cleanup_results['deleted_recovery_points'].append({
                'recovery_point_arn': recovery_point_arn,
                'vault_name': vault_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete recovery point {recovery_point_arn}: {e}"
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def delete_backup_plan(self, backup_client, plan_id, plan_name, region, account_key):
        """Delete a backup plan"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting backup plan: {plan_name}")
            
            # Delete all backup selections first
            try:
                selections_response = backup_client.list_backup_selections(BackupPlanId=plan_id)
                selections = selections_response.get('BackupSelectionsList', [])
                
                for selection in selections:
                    try:
                        backup_client.delete_backup_selection(
                            BackupPlanId=plan_id,
                            SelectionId=selection['SelectionId']
                        )
                        self.print_colored(Colors.YELLOW, f"   [DELETE] Deleted backup selection: {selection['SelectionName']}")
                    except ClientError:
                        pass
            except ClientError:
                pass
            
            # Delete the backup plan
            backup_client.delete_backup_plan(BackupPlanId=plan_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted backup plan: {plan_name}")
            self.log_action(f"Deleted backup plan: {plan_name} ({plan_id}) in {region}")
            
            self.cleanup_results['deleted_backup_plans'].append({
                'plan_id': plan_id,
                'plan_name': plan_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete backup plan {plan_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'BackupPlan',
                'name': plan_name,
                'id': plan_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_backup_vault(self, backup_client, vault_name, region, account_key):
        """Delete a backup vault after removing all recovery points"""
        try:
            # Skip default vault
            if vault_name == 'Default':
                self.print_colored(Colors.YELLOW, f"[SKIP] Skipping default vault: {vault_name}")
                return True
            
            self.print_colored(Colors.CYAN, f"[DELETE] Processing backup vault: {vault_name}")
            
            # Step 1: Delete all recovery points in the vault
            try:
                paginator = backup_client.get_paginator('list_recovery_points_by_backup_vault')
                recovery_points = []
                
                for page in paginator.paginate(BackupVaultName=vault_name):
                    recovery_points.extend(page.get('RecoveryPoints', []))
                
                if recovery_points:
                    self.print_colored(Colors.YELLOW, f"   [SCAN] Found {len(recovery_points)} recovery points")
                    for rp in recovery_points:
                        self.delete_recovery_point(
                            backup_client,
                            vault_name,
                            rp['RecoveryPointArn'],
                            region,
                            account_key
                        )
                        time.sleep(1)
                    
                    # Wait for recovery points to be fully deleted
                    self.print_colored(Colors.YELLOW, f"   [WAIT] Waiting for recovery points to be deleted...")
                    time.sleep(10)
            except ClientError as e:
                self.log_action(f"Error listing recovery points for vault {vault_name}: {e}", "ERROR")
            
            # Step 2: Remove vault access policy
            try:
                backup_client.delete_backup_vault_access_policy(BackupVaultName=vault_name)
                self.print_colored(Colors.YELLOW, f"   [POLICY] Removed access policy")
            except ClientError:
                pass  # Vault may not have access policy
            
            # Step 3: Remove vault notifications
            try:
                backup_client.delete_backup_vault_notifications(BackupVaultName=vault_name)
                self.print_colored(Colors.YELLOW, f"   [NOTIFY] Removed notifications")
            except ClientError:
                pass  # Vault may not have notifications
            
            # Step 4: Delete the vault
            backup_client.delete_backup_vault(BackupVaultName=vault_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted backup vault: {vault_name}")
            self.log_action(f"Deleted backup vault: {vault_name} in {region}")
            
            self.cleanup_results['deleted_backup_vaults'].append({
                'vault_name': vault_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete backup vault {vault_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'BackupVault',
                'name': vault_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_backup(self, account_name, credentials, region):
        """Cleanup all AWS Backup resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            backup_client = boto3.client(
                'backup',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Backup Plans
            try:
                plans_response = backup_client.list_backup_plans()
                plans = plans_response.get('BackupPlansList', [])
                
                if plans:
                    self.print_colored(Colors.CYAN, f"[PLAN] Found {len(plans)} backup plans")
                    for plan in plans:
                        self.delete_backup_plan(
                            backup_client,
                            plan['BackupPlanId'],
                            plan['BackupPlanName'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing backup plans in {region}: {e}", "ERROR")
            
            # Delete Backup Vaults (and their recovery points)
            try:
                vaults_response = backup_client.list_backup_vaults()
                vaults = vaults_response.get('BackupVaultList', [])
                
                if vaults:
                    self.print_colored(Colors.CYAN, f"[VAULT] Found {len(vaults)} backup vaults")
                    for vault in vaults:
                        self.delete_backup_vault(
                            backup_client,
                            vault['BackupVaultName'],
                            region,
                            account_name
                        )
                        time.sleep(2)
            except ClientError as e:
                self.log_action(f"Error listing backup vaults in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_backup(self, account_name, credentials):
        """Cleanup all AWS Backup resources in an account across all regions"""
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
                self.cleanup_region_backup(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"backup_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_recovery_points_deleted': len(self.cleanup_results['deleted_recovery_points']),
                    'total_backup_plans_deleted': len(self.cleanup_results['deleted_backup_plans']),
                    'total_backup_vaults_deleted': len(self.cleanup_results['deleted_backup_vaults']),
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
            self.print_colored(Colors.GREEN, f"[OK] Recovery Points Deleted: {summary['summary']['total_recovery_points_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Backup Plans Deleted: {summary['summary']['total_backup_plans_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Backup Vaults Deleted: {summary['summary']['total_backup_vaults_deleted']}")

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
                (self.cleanup_results['deleted_recovery_points'], 'recovery_points'),
                (self.cleanup_results['deleted_backup_plans'], 'backup_plans'),
                (self.cleanup_results['deleted_backup_vaults'], 'backup_vaults')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'recovery_points': 0,
                            'backup_plans': 0,
                            'backup_vaults': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Recovery Points: {stats['recovery_points']}")
                self.print_colored(Colors.GREEN, f"  [OK] Backup Plans: {stats['backup_plans']}")
                self.print_colored(Colors.GREEN, f"  [OK] Backup Vaults: {stats['backup_vaults']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for AWS Backup cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS BACKUP CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for AWS Backup Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all AWS Backup resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: Recovery Points, Backup Plans, Backup Vaults")
            self.print_colored(Colors.YELLOW, "[INFO] Default vault will be skipped")
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

                self.cleanup_account_backup(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] AWS Backup cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupBackupManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
