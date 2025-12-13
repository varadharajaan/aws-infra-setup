#!/usr/bin/env python3
"""
Ultra EFS Cleanup Manager
Comprehensive AWS EFS (Elastic File System) cleanup across multiple AWS accounts and regions
- Deletes EFS Mount Targets (dependencies first)
- Deletes EFS Access Points
- Deletes EFS File Systems
- Deletes EFS Replication Configurations
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


class UltraCleanupEFSManager:
    """Manager for comprehensive EFS cleanup operations"""

    def __init__(self):
        """Initialize the EFS cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'efs')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'efs_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_mount_targets': [],
            'deleted_access_points': [],
            'deleted_file_systems': [],
            'deleted_replications': [],
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

    def delete_mount_target(self, efs_client, mount_target_id, region, account_key):
        """Delete an EFS mount target"""
        try:
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting mount target: {mount_target_id}")
            
            efs_client.delete_mount_target(MountTargetId=mount_target_id)
            
            # Wait for mount target to be deleted
            max_wait = 60
            wait_time = 0
            while wait_time < max_wait:
                try:
                    efs_client.describe_mount_targets(MountTargetId=mount_target_id)
                    time.sleep(5)
                    wait_time += 5
                except ClientError as e:
                    if 'MountTargetNotFound' in str(e):
                        break
                    raise
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted mount target: {mount_target_id}")
            self.log_action(f"Deleted mount target: {mount_target_id} in {region}")
            
            self.cleanup_results['deleted_mount_targets'].append({
                'mount_target_id': mount_target_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete mount target {mount_target_id}: {e}"
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def delete_access_point(self, efs_client, access_point_id, region, account_key):
        """Delete an EFS access point"""
        try:
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting access point: {access_point_id}")
            
            efs_client.delete_access_point(AccessPointId=access_point_id)
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted access point: {access_point_id}")
            self.log_action(f"Deleted access point: {access_point_id} in {region}")
            
            self.cleanup_results['deleted_access_points'].append({
                'access_point_id': access_point_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete access point {access_point_id}: {e}"
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def delete_replication_configuration(self, efs_client, file_system_id, region, account_key):
        """Delete EFS replication configuration"""
        try:
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting replication config for: {file_system_id}")
            
            efs_client.delete_replication_configuration(SourceFileSystemId=file_system_id)
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted replication config: {file_system_id}")
            self.log_action(f"Deleted replication config for: {file_system_id} in {region}")
            
            self.cleanup_results['deleted_replications'].append({
                'file_system_id': file_system_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            if 'ReplicationNotFound' in str(e):
                return True
            error_msg = f"Failed to delete replication config {file_system_id}: {e}"
            self.print_colored(Colors.YELLOW, f"   [WARN] {error_msg}")
            self.log_action(error_msg, "WARNING")
            return False

    def delete_file_system(self, efs_client, file_system_id, region, account_key):
        """Delete an EFS file system after removing dependencies"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Processing file system: {file_system_id}")
            
            # Step 1: Delete replication configuration first
            self.delete_replication_configuration(efs_client, file_system_id, region, account_key)
            time.sleep(2)
            
            # Step 2: Delete all access points
            try:
                access_points_response = efs_client.describe_access_points(FileSystemId=file_system_id)
                access_points = access_points_response.get('AccessPoints', [])
                
                if access_points:
                    self.print_colored(Colors.YELLOW, f"   [SCAN] Found {len(access_points)} access points")
                    for ap in access_points:
                        self.delete_access_point(efs_client, ap['AccessPointId'], region, account_key)
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing access points for {file_system_id}: {e}", "ERROR")
            
            # Step 3: Delete all mount targets
            try:
                mount_targets_response = efs_client.describe_mount_targets(FileSystemId=file_system_id)
                mount_targets = mount_targets_response.get('MountTargets', [])
                
                if mount_targets:
                    self.print_colored(Colors.YELLOW, f"   [SCAN] Found {len(mount_targets)} mount targets")
                    for mt in mount_targets:
                        self.delete_mount_target(efs_client, mt['MountTargetId'], region, account_key)
                        time.sleep(2)
                    
                    # Wait for all mount targets to be fully deleted
                    self.print_colored(Colors.YELLOW, f"   [WAIT] Waiting for mount targets to be deleted...")
                    time.sleep(10)
            except ClientError as e:
                self.log_action(f"Error listing mount targets for {file_system_id}: {e}", "ERROR")
            
            # Step 4: Delete the file system
            efs_client.delete_file_system(FileSystemId=file_system_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted file system: {file_system_id}")
            self.log_action(f"Deleted file system: {file_system_id} in {region}")
            
            self.cleanup_results['deleted_file_systems'].append({
                'file_system_id': file_system_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete file system {file_system_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'FileSystem',
                'id': file_system_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_efs(self, account_name, credentials, region):
        """Cleanup all EFS resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            efs_client = boto3.client(
                'efs',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Get all file systems
            try:
                file_systems_response = efs_client.describe_file_systems()
                file_systems = file_systems_response.get('FileSystems', [])
                
                if file_systems:
                    self.print_colored(Colors.CYAN, f"[EFS] Found {len(file_systems)} file systems")
                    for fs in file_systems:
                        self.delete_file_system(efs_client, fs['FileSystemId'], region, account_name)
                        time.sleep(2)
            except ClientError as e:
                self.log_action(f"Error listing file systems in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_efs(self, account_name, credentials):
        """Cleanup all EFS resources in an account across all regions"""
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
                self.cleanup_region_efs(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"efs_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_file_systems_deleted': len(self.cleanup_results['deleted_file_systems']),
                    'total_mount_targets_deleted': len(self.cleanup_results['deleted_mount_targets']),
                    'total_access_points_deleted': len(self.cleanup_results['deleted_access_points']),
                    'total_replications_deleted': len(self.cleanup_results['deleted_replications']),
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
            self.print_colored(Colors.GREEN, f"[OK] File Systems Deleted: {summary['summary']['total_file_systems_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Mount Targets Deleted: {summary['summary']['total_mount_targets_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Access Points Deleted: {summary['summary']['total_access_points_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Replication Configs Deleted: {summary['summary']['total_replications_deleted']}")

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
                (self.cleanup_results['deleted_file_systems'], 'file_systems'),
                (self.cleanup_results['deleted_mount_targets'], 'mount_targets'),
                (self.cleanup_results['deleted_access_points'], 'access_points'),
                (self.cleanup_results['deleted_replications'], 'replications')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'file_systems': 0, 'mount_targets': 0,
                            'access_points': 0, 'replications': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] File Systems: {stats['file_systems']}")
                self.print_colored(Colors.GREEN, f"  [OK] Mount Targets: {stats['mount_targets']}")
                self.print_colored(Colors.GREEN, f"  [OK] Access Points: {stats['access_points']}")
                self.print_colored(Colors.GREEN, f"  [OK] Replication Configs: {stats['replications']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for EFS cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA EFS CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for EFS Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all EFS resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: File Systems, Mount Targets, Access Points, Replication Configs")
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

                self.cleanup_account_efs(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] EFS cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupEFSManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
