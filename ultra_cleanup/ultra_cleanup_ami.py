#!/usr/bin/env python3

"""
Ultra AMI Cleanup Manager

Tool to perform comprehensive cleanup of AMI resources across AWS accounts.

Manages deletion of:
- Amazon Machine Images (AMIs)
- Associated EBS Snapshots
- Orphaned Snapshots

PROTECTIONS:
- AMIs in use by instances are SKIPPED
- Running/Stopped instances using AMIs are preserved

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


class UltraCleanupAMIManager:
    """
    Tool to perform comprehensive cleanup of AMI resources across AWS accounts.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the AMI Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.ami_dir = os.path.join(self.config_dir, "aws", "ami")
        self.reports_dir = os.path.join(self.ami_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_amis': [],
            'deleted_snapshots': [],
            'skipped_amis': [],
            'failed_deletions': [],
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
            os.makedirs(self.ami_dir, exist_ok=True)

            # Save log file in the aws/ami directory
            self.log_filename = f"{self.ami_dir}/ultra_ami_cleanup_log_{self.execution_timestamp}.log"
            
            import logging
            
            self.operation_logger = logging.getLogger('ultra_ami_cleanup')
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
            self.operation_logger.info("[ALERT] ULTRA AMI CLEANUP SESSION STARTED [ALERT]")
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

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using account credentials"""
        try:
            client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the connection
            client.describe_images(Owners=['self'], MaxResults=5)
            
            return client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create EC2 client for {region}: {e}")
            raise

    def get_all_amis(self, ec2_client, region, account_name, account_id):
        """Get all AMIs owned by this account in a specific region"""
        try:
            amis = []
            
            self.log_operation('INFO', f"[SCAN] Scanning for AMIs in {region} ({account_name})")
            print(f"   [SCAN] Scanning for AMIs in {region} ({account_name})...")
            
            # Get AMIs owned by this account
            response = ec2_client.describe_images(Owners=[account_id])
            
            for image in response.get('Images', []):
                ami_id = image['ImageId']
                name = image.get('Name', 'N/A')
                description = image.get('Description', 'N/A')
                state = image.get('State', 'N/A')
                creation_date = image.get('CreationDate', 'N/A')
                architecture = image.get('Architecture', 'N/A')
                platform = image.get('Platform', 'Linux/Unix')
                
                # Get snapshot IDs from block device mappings
                snapshot_ids = []
                for bdm in image.get('BlockDeviceMappings', []):
                    if 'Ebs' in bdm and 'SnapshotId' in bdm['Ebs']:
                        snapshot_ids.append(bdm['Ebs']['SnapshotId'])
                
                # Get tags
                tags = {tag['Key']: tag['Value'] for tag in image.get('Tags', [])}
                
                ami_info = {
                    'ami_id': ami_id,
                    'name': name,
                    'description': description,
                    'state': state,
                    'creation_date': creation_date,
                    'architecture': architecture,
                    'platform': platform,
                    'snapshot_ids': snapshot_ids,
                    'snapshot_count': len(snapshot_ids),
                    'tags': tags,
                    'region': region,
                    'account_name': account_name
                }
                
                amis.append(ami_info)
            
            self.log_operation('INFO', f"[SNAPSHOT] Found {len(amis)} AMIs in {region} ({account_name})")
            print(f"   [SNAPSHOT] Found {len(amis)} AMIs in {region} ({account_name})")
            
            # Count by state
            available_count = sum(1 for a in amis if a['state'] == 'available')
            other_count = len(amis) - available_count
            
            if amis:
                print(f"      ✓ Available: {available_count}, Other states: {other_count}")
            
            return amis
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting AMIs in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting AMIs in {region}: {e}")
            return []

    def check_ami_in_use(self, ec2_client, ami_id):
        """Check if AMI is currently being used by any instances"""
        try:
            # Check for running instances using this AMI
            response = ec2_client.describe_instances(
                Filters=[
                    {'Name': 'image-id', 'Values': [ami_id]},
                    {'Name': 'instance-state-name', 'Values': ['running', 'stopped', 'stopping', 'pending']}
                ]
            )
            
            instances = []
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instances.append({
                        'instance_id': instance['InstanceId'],
                        'state': instance['State']['Name']
                    })
            
            return len(instances) > 0, instances
            
        except Exception as e:
            self.log_operation('WARNING', f"Could not check if AMI {ami_id} is in use: {e}")
            return False, []

    def deregister_ami(self, ec2_client, ami_info):
        """Deregister (delete) an AMI and optionally its snapshots"""
        try:
            ami_id = ami_info['ami_id']
            region = ami_info['region']
            account_name = ami_info['account_name']
            
            # Check if AMI is in use
            in_use, instances = self.check_ami_in_use(ec2_client, ami_id)
            
            if in_use:
                instance_ids = [inst['instance_id'] for inst in instances]
                self.log_operation('INFO', f"[SKIP]  Skipping AMI {ami_id} ({ami_info['name']}) - in use by instances: {', '.join(instance_ids)}")
                print(f"      [SKIP]  Skipping {ami_id} ({ami_info['name']}) - in use by {len(instances)} instance(s)")
                
                self.cleanup_results['skipped_amis'].append({
                    'ami_id': ami_id,
                    'name': ami_info['name'],
                    'region': region,
                    'account_name': account_name,
                    'reason': f'In use by instances: {", ".join(instance_ids)}'
                })
                
                return False
            
            # Deregister AMI
            self.log_operation('INFO', f"[DELETE]  Deregistering AMI {ami_id} ({ami_info['name']}) - {ami_info['snapshot_count']} snapshots")
            print(f"      [DELETE]  Deregistering AMI {ami_id} ({ami_info['name']})")
            
            ec2_client.deregister_image(ImageId=ami_id)
            
            self.log_operation('INFO', f"[OK] Successfully deregistered AMI {ami_id}")
            
            # Delete associated snapshots
            deleted_snapshots = []
            if ami_info['snapshot_ids']:
                print(f"         [DELETE]  Deleting {len(ami_info['snapshot_ids'])} associated snapshots...")
                
                for snapshot_id in ami_info['snapshot_ids']:
                    try:
                        self.log_operation('INFO', f"Deleting snapshot {snapshot_id} for AMI {ami_id}")
                        ec2_client.delete_snapshot(SnapshotId=snapshot_id)
                        deleted_snapshots.append(snapshot_id)
                        self.log_operation('INFO', f"[OK] Deleted snapshot {snapshot_id}")
                        
                        self.cleanup_results['deleted_snapshots'].append({
                            'snapshot_id': snapshot_id,
                            'ami_id': ami_id,
                            'ami_name': ami_info['name'],
                            'region': region,
                            'account_name': account_name,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        
                    except ClientError as snap_error:
                        error_code = snap_error.response.get('Error', {}).get('Code', 'Unknown')
                        
                        if error_code == 'InvalidSnapshot.InUse':
                            self.log_operation('WARNING', f"Snapshot {snapshot_id} is in use, skipping")
                            print(f"         [WARN]  Snapshot {snapshot_id} is in use, skipping")
                        else:
                            self.log_operation('ERROR', f"Failed to delete snapshot {snapshot_id}: {snap_error}")
                            print(f"         [ERROR] Failed to delete snapshot {snapshot_id}: {snap_error}")
                        
                        self.cleanup_results['failed_deletions'].append({
                            'resource_type': 'snapshot',
                            'resource_id': snapshot_id,
                            'ami_id': ami_id,
                            'region': region,
                            'account_name': account_name,
                            'error': str(snap_error)
                        })
                    except Exception as snap_error:
                        self.log_operation('ERROR', f"Unexpected error deleting snapshot {snapshot_id}: {snap_error}")
                        print(f"         [ERROR] Error deleting snapshot {snapshot_id}: {snap_error}")
            
            # Record the AMI deletion
            self.cleanup_results['deleted_amis'].append({
                'ami_id': ami_id,
                'name': ami_info['name'],
                'description': ami_info['description'],
                'creation_date': ami_info['creation_date'],
                'architecture': ami_info['architecture'],
                'platform': ami_info['platform'],
                'snapshot_count': len(ami_info['snapshot_ids']),
                'snapshots_deleted': len(deleted_snapshots),
                'snapshot_ids': ami_info['snapshot_ids'],
                'region': region,
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to deregister AMI {ami_info['ami_id']}: {e}")
            print(f"      [ERROR] Failed to deregister AMI {ami_info['ami_id']}: {e}")
            
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'ami',
                'resource_id': ami_info['ami_id'],
                'name': ami_info['name'],
                'region': ami_info['region'],
                'account_name': ami_info['account_name'],
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_info: dict, region: str) -> bool:
        """Clean up all AMIs in a specific account and region"""
        try:
            account_name = account_info.get('name', 'Unknown')
            account_id = account_info.get('account_id', 'Unknown')
            access_key = account_info.get('access_key')
            secret_key = account_info.get('secret_key')
        
            self.log_operation('INFO', f"[CLEANUP] Starting cleanup for {account_name} ({account_id}) in {region}")
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] Starting cleanup for {account_name} ({account_id}) in {region}")
        
            # Create EC2 client
            try:
                ec2_client = self.create_ec2_client(access_key, secret_key, region)
            except Exception as client_error:
                error_msg = f"Could not create EC2 client for {region}: {client_error}"
                self.log_operation('ERROR', error_msg)
                self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
                return False
        
            # Get all AMIs
            amis = self.get_all_amis(ec2_client, region, account_name, account_id)
        
            if not amis:
                self.log_operation('INFO', f"No AMIs found in {account_name} ({region})")
                self.print_colored(Colors.GREEN, f"   ✓ No AMIs found in {account_name} ({region})")
                return True
        
            # Record region summary
            region_summary = {
                'account_name': account_name,
                'account_id': account_id,
                'region': region,
                'amis_found': len(amis),
                'total_snapshots': sum(ami['snapshot_count'] for ami in amis)
            }
            self.cleanup_results['regions_processed'].append(region_summary)
        
            # Add account to processed accounts if not already there
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({
                    'account_name': account_name,
                    'account_id': account_id
                })
            
            # Deregister each AMI
            if amis:
                print(f"\n   [DELETE]  Processing {len(amis)} AMIs...")
                for ami in amis:
                    self.deregister_ami(ec2_client, ami)
        
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
            report_filename = f"{self.reports_dir}/ultra_ami_cleanup_report_{self.execution_timestamp}.json"
            
            total_amis_deleted = len(self.cleanup_results['deleted_amis'])
            total_snapshots_deleted = len(self.cleanup_results['deleted_snapshots'])
            total_amis_skipped = len(self.cleanup_results['skipped_amis'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            
            # Group by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for ami in self.cleanup_results['deleted_amis']:
                account = ami['account_name']
                region = ami['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'amis': 0, 'snapshots': 0}
                deletions_by_account[account]['amis'] += 1
                deletions_by_account[account]['snapshots'] += ami['snapshots_deleted']
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'amis': 0, 'snapshots': 0}
                deletions_by_region[region]['amis'] += 1
                deletions_by_region[region]['snapshots'] += ami['snapshots_deleted']
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_AMI_CLEANUP",
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
                    "total_amis_deleted": total_amis_deleted,
                    "total_snapshots_deleted": total_snapshots_deleted,
                    "total_amis_skipped": total_amis_skipped,
                    "total_failed_deletions": total_failed,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results['accounts_processed'],
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_amis": self.cleanup_results['deleted_amis'],
                    "deleted_snapshots": self.cleanup_results['deleted_snapshots'],
                    "skipped_amis": self.cleanup_results['skipped_amis'],
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
            self.log_operation('INFO', "[ALERT] STARTING ULTRA AMI CLEANUP SESSION [ALERT]")
            
            self.print_colored(Colors.CYAN, "\n" + "[ALERT]" * 30)
            self.print_colored(Colors.BLUE, "[START] ULTRA AMI (Amazon Machine Image) CLEANUP MANAGER")
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
            self.print_colored(Colors.WHITE, f"[DELETE]  Target: All AMIs owned by account + Associated snapshots")
            self.print_colored(Colors.WHITE, f"[SKIP]  Skipped: AMIs in use by running/stopped instances")
            self.print_colored(Colors.CYAN, "=" * 80)
            
            # Confirmation
            self.print_colored(Colors.RED, f"\n[WARN]  WARNING: This will:")
            self.print_colored(Colors.RED, f"    • Deregister ALL AMIs owned by the account")
            self.print_colored(Colors.RED, f"    • Delete ALL snapshots associated with those AMIs")
            self.print_colored(Colors.RED, f"    • Across {len(selected_accounts)} accounts in {len(selected_regions)} regions")
            self.print_colored(Colors.RED, f"    • AMIs in use by instances will be SKIPPED")
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
            self.print_colored(Colors.WHITE, f"[SNAPSHOT] AMIs deleted: {len(self.cleanup_results['deleted_amis'])}")
            self.print_colored(Colors.WHITE, f"[INSTANCE] Snapshots deleted: {len(self.cleanup_results['deleted_snapshots'])}")
            self.print_colored(Colors.YELLOW, f"[SKIP]  AMIs skipped (in-use): {len(self.cleanup_results['skipped_amis'])}")
            self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            self.log_operation('INFO', f"CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"AMIs deleted: {len(self.cleanup_results['deleted_amis'])}")
            self.log_operation('INFO', f"Snapshots deleted: {len(self.cleanup_results['deleted_snapshots'])}")
            
            # Show account summary
            if self.cleanup_results['deleted_amis']:
                self.print_colored(Colors.CYAN, f"\n[STATS] Deletion Summary by Account:")
                
                account_summary = {}
                for ami in self.cleanup_results['deleted_amis']:
                    account = ami['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'amis': 0, 'snapshots': 0, 'regions': set()}
                    account_summary[account]['amis'] += 1
                    account_summary[account]['snapshots'] += ami['snapshots_deleted']
                    account_summary[account]['regions'].add(ami['region'])
                
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.WHITE, f"   [BANK] {account}:")
                    self.print_colored(Colors.WHITE, f"      [SNAPSHOT] AMIs: {summary['amis']}")
                    self.print_colored(Colors.WHITE, f"      [INSTANCE] Snapshots: {summary['snapshots']}")
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
            
            # Show skipped AMIs
            if self.cleanup_results['skipped_amis']:
                self.print_colored(Colors.YELLOW, f"\n[SKIP]  Skipped AMIs (in use by instances):")
                for skipped in self.cleanup_results['skipped_amis'][:5]:
                    self.print_colored(Colors.YELLOW, f"   • {skipped['ami_id']} ({skipped['name']}) - {skipped['reason']}")
                
                if len(self.cleanup_results['skipped_amis']) > 5:
                    remaining = len(self.cleanup_results['skipped_amis']) - 5
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
        manager = UltraCleanupAMIManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Cleanup interrupted by user")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")

if __name__ == "__main__":
    main()
