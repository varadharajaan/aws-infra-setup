#!/usr/bin/env python3

"""
Ultra Athena Cleanup Manager

Tool to perform comprehensive cleanup of Athena resources across AWS accounts.

Manages deletion of:
- Athena Workgroups (custom)
- Named Queries
- Prepared Statements
- Data Catalogs (custom)
- Query Execution History

PROTECTIONS:
- Primary workgroup is PRESERVED
- Default data catalog is PRESERVED

Author: varadharajaan
Created: 2025-11-24
"""

import os
import json
import boto3
import time
from datetime import datetime
from typing import List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupAthenaManager:
    """
    Tool to perform comprehensive cleanup of Athena resources across AWS accounts.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the Athena Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.athena_dir = os.path.join(self.config_dir, "aws", "athena")
        self.reports_dir = os.path.join(self.athena_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_workgroups': [],
            'deleted_queries': [],
            'deleted_catalogs': [],
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
            os.makedirs(self.athena_dir, exist_ok=True)

            self.log_filename = f"{self.athena_dir}/ultra_athena_cleanup_log_{self.execution_timestamp}.log"
            
            import logging
            
            self.operation_logger = logging.getLogger('ultra_athena_cleanup')
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
            self.operation_logger.info("[ALERT] ULTRA ATHENA CLEANUP SESSION STARTED [ALERT]")
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

    def create_athena_client(self, access_key, secret_key, region):
        """Create Athena client"""
        try:
            client = boto3.client(
                'athena',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            client.list_work_groups(MaxResults=1)
            return client
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create Athena client for {region}: {e}")
            raise

    def delete_workgroups(self, athena_client, region, account_name):
        """Delete custom Athena workgroups"""
        try:
            deleted_count = 0
            
            paginator = athena_client.get_paginator('list_work_groups')
            for page in paginator.paginate():
                for wg in page.get('WorkGroups', []):
                    wg_name = wg['Name']
                    
                    # PROTECTION: Skip primary workgroup
                    if wg_name.lower() == 'primary':
                        self.log_operation('INFO', f"[PROTECTED]  PROTECTED: {wg_name} (primary workgroup)")
                        continue
                    
                    try:
                        self.log_operation('INFO', f"[DELETE]  Deleting workgroup: {wg_name}")
                        athena_client.delete_work_group(
                            WorkGroup=wg_name,
                            RecursiveDeleteOption=True
                        )
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_workgroups'].append({
                            'workgroup_name': wg_name,
                            'state': wg.get('State', 'UNKNOWN'),
                            'region': region,
                            'account_name': account_name,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete workgroup {wg_name}: {e}")
                        self.cleanup_results['failed_deletions'].append({
                            'resource_type': 'workgroup',
                            'resource_id': wg_name,
                            'region': region,
                            'account_name': account_name,
                            'error': str(e)
                        })
            
            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} workgroups")
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete workgroups: {e}")
            return False

    def delete_named_queries(self, athena_client, region, account_name):
        """Delete named queries"""
        try:
            deleted_count = 0
            
            paginator = athena_client.get_paginator('list_named_queries')
            for page in paginator.paginate():
                for query_id in page.get('NamedQueryIds', []):
                    try:
                        athena_client.delete_named_query(NamedQueryId=query_id)
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_queries'].append({
                            'query_id': query_id,
                            'region': region,
                            'account_name': account_name,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete query {query_id}: {e}")
            
            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted_count} named queries")
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete named queries: {e}")
            return False

    def cleanup_account_region(self, account_info: dict, region: str) -> bool:
        """Clean up all Athena resources in a specific account and region"""
        try:
            account_name = account_info.get('name', 'Unknown')
            account_id = account_info.get('account_id', 'Unknown')
            access_key = account_info.get('access_key')
            secret_key = account_info.get('secret_key')
        
            self.log_operation('INFO', f"[CLEANUP] Starting cleanup for {account_name} ({account_id}) in {region}")
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] Starting cleanup for {account_name} ({account_id}) in {region}")
        
            try:
                athena_client = self.create_athena_client(access_key, secret_key, region)
            except Exception as client_error:
                error_msg = f"Could not create Athena client for {region}: {client_error}"
                self.log_operation('ERROR', error_msg)
                self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
                return False
        
            # Delete resources
            self.delete_workgroups(athena_client, region, account_name)
            self.delete_named_queries(athena_client, region, account_name)
        
            # Record region summary
            self.cleanup_results['regions_processed'].append({
                'account_name': account_name,
                'account_id': account_id,
                'region': region
            })
        
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({
                    'account_name': account_name,
                    'account_id': account_id
                })
        
            self.log_operation('INFO', f"[OK] Cleanup completed for {account_name} ({region})")
            self.print_colored(Colors.GREEN, f"   [OK] Cleanup completed for {account_name} ({region})")
            return True
        
        except Exception as e:
            error_msg = f"Error cleaning up {account_name} ({region}): {e}"
            self.log_operation('ERROR', error_msg)
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_athena_cleanup_report_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_ATHENA_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename
                },
                "summary": {
                    "total_workgroups_deleted": len(self.cleanup_results['deleted_workgroups']),
                    "total_queries_deleted": len(self.cleanup_results['deleted_queries']),
                    "total_failed_deletions": len(self.cleanup_results['failed_deletions'])
                },
                "detailed_results": self.cleanup_results
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"[OK] Report saved to: {report_filename}")
            return report_filename
        except Exception as e:
            self.log_operation('ERROR', f"Failed to save report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.print_colored(Colors.CYAN, "\n" + "[ALERT]" * 30)
            self.print_colored(Colors.BLUE, "[START] ULTRA ATHENA CLEANUP MANAGER")
            self.print_colored(Colors.CYAN, "[ALERT]" * 30)
            
            selected_accounts = self.cred_manager.select_root_accounts_interactive()
            if not selected_accounts:
                self.print_colored(Colors.YELLOW, "[ERROR] No accounts selected. Exiting.")
                return
            
            self.user_regions = self._get_user_regions()
            selected_regions = self.select_regions_interactive(self.user_regions)
            
            if not selected_regions:
                self.print_colored(Colors.YELLOW, "[ERROR] No regions selected. Exiting.")
                return
            
            self.print_colored(Colors.RED, f"\n[WARN]  WARNING: This will delete Athena workgroups, queries, and catalogs!")
            self.print_colored(Colors.YELLOW, f"\n[WARN]  Type 'DELETE' to confirm:")
            confirm = input("   → ").strip()
            
            if confirm.upper() != 'DELETE':
                self.print_colored(Colors.YELLOW, "[ERROR] Cleanup cancelled")
                return
            
            self.print_colored(Colors.CYAN, f"\n[START] Starting cleanup...")
            start_time = time.time()
            
            for account_info in selected_accounts:
                for region in selected_regions:
                    self.cleanup_account_region(account_info, region)
            
            total_time = int(time.time() - start_time)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Cleanup completed successfully!")
            self.print_colored(Colors.WHITE, f"[TIMER]  Time: {total_time}s")
            self.print_colored(Colors.WHITE, f"[DELETE]  Workgroups: {len(self.cleanup_results['deleted_workgroups'])}")
            self.print_colored(Colors.WHITE, f"[LOG] Queries: {len(self.cleanup_results['deleted_queries'])}")
            
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"\n[OK] Report: {report_file}")
            
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()

    def select_regions_interactive(self, available_regions: List[str]) -> List[str]:
        """Interactive region selection"""
        self.print_colored(Colors.CYAN, f"\n[REGION] AVAILABLE REGIONS:")
        for i, region in enumerate(available_regions, 1):
            self.print_colored(Colors.WHITE, f"  {i}. {region}")
        
        selection = input("\n🔢 Select regions (1-5, 'all', or 'q'): ").strip().lower()
        
        if selection in ['cancel', 'quit', 'q']:
            return []
        
        if not selection or selection == 'all':
            return available_regions
        
        try:
            indices = self.cred_manager._parse_selection(selection, len(available_regions))
            return [available_regions[i] for i in indices]
        except ValueError as e:
            self.print_colored(Colors.RED, f"[ERROR] Invalid selection: {e}")
            return []

def main():
    """Main function"""
    try:
        manager = UltraCleanupAthenaManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Cleanup interrupted by user")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")

if __name__ == "__main__":
    main()
