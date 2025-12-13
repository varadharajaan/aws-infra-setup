#!/usr/bin/env python3

"""
Ultra SNS Cleanup Manager

Tool to perform comprehensive cleanup of SNS resources across AWS accounts.

Manages deletion of:
- SNS Topics
- SNS Subscriptions
- Platform Applications
- SMS Sandbox phone numbers

PROTECTIONS:
- None (all SNS resources can be recreated)

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
from text_symbols import Symbols


class UltraCleanupSNSManager:
    """
    Tool to perform comprehensive cleanup of SNS resources across AWS accounts.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the SNS Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.sns_dir = os.path.join(self.config_dir, "aws", "sns")
        self.reports_dir = os.path.join(self.sns_dir, "reports")

        self.setup_detailed_logging()
        self.user_regions = self._get_user_regions()

        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_topics': [],
            'deleted_subscriptions': [],
            'deleted_platform_apps': [],
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
            self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  Warning: Could not load user regions: {e}")
        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.sns_dir, exist_ok=True)
            self.log_filename = f"{self.sns_dir}/ultra_sns_cleanup_log_{self.execution_timestamp}.log"
            
            self.operation_logger = logging.getLogger('ultra_sns_cleanup')
            self.operation_logger.setLevel(logging.INFO)
            
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s | %(levelname)8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            file_handler.setFormatter(formatter)
            self.operation_logger.addHandler(file_handler)
            
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"{Symbols.ALERT} ULTRA SNS CLEANUP SESSION STARTED {Symbols.ALERT}")
            self.operation_logger.info("=" * 100)
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Simple logging operation"""
        if self.operation_logger:
            getattr(self.operation_logger, level.lower(), self.operation_logger.info)(message)
        else:
            print(f"[{level.upper()}] {message}")

    def create_sns_client(self, access_key, secret_key, region):
        """Create SNS client"""
        try:
            client = boto3.client('sns', aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
            # Test client connectivity
            client.list_topics()
            return client
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create SNS client for {region}: {e}")
            raise

    def delete_topics(self, sns_client, region, account_name):
        """Delete all SNS topics"""
        try:
            deleted_count = 0
            paginator = sns_client.get_paginator('list_topics')
            
            for page in paginator.paginate():
                for topic in page.get('Topics', []):
                    topic_arn = topic['TopicArn']
                    try:
                        self.log_operation('INFO', f"{Symbols.DELETE}  Deleting topic: {topic_arn}")
                        sns_client.delete_topic(TopicArn=topic_arn)
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_topics'].append({
                            'topic_arn': topic_arn,
                            'region': region,
                            'account_name': account_name,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete topic {topic_arn}: {e}")
                        self.cleanup_results['failed_deletions'].append({
                            'resource_type': 'topic',
                            'resource_id': topic_arn,
                            'region': region,
                            'account_name': account_name,
                            'error': str(e)
                        })
            
            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Deleted {deleted_count} topics")
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete topics: {e}")
            return False

    def delete_platform_applications(self, sns_client, region, account_name):
        """Delete platform applications"""
        try:
            deleted_count = 0
            paginator = sns_client.get_paginator('list_platform_applications')
            
            for page in paginator.paginate():
                for app in page.get('PlatformApplications', []):
                    app_arn = app['PlatformApplicationArn']
                    try:
                        sns_client.delete_platform_application(PlatformApplicationArn=app_arn)
                        deleted_count += 1
                        
                        self.cleanup_results['deleted_platform_apps'].append({
                            'app_arn': app_arn,
                            'region': region,
                            'account_name': account_name,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to delete app {app_arn}: {e}")
            
            if deleted_count > 0:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Deleted {deleted_count} platform apps")
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete platform apps: {e}")
            return False

    def cleanup_account_region(self, account_info: dict, region: str) -> bool:
        """Clean up all SNS resources in a specific account and region"""
        try:
            account_name = account_info.get('name', 'Unknown')
            access_key = account_info.get('access_key')
            secret_key = account_info.get('secret_key')
        
            self.print_colored(Colors.CYAN, f"\n{Symbols.CLEANUP} Starting cleanup for {account_name} in {region}")
        
            try:
                sns_client = self.create_sns_client(access_key, secret_key, region)
            except Exception as e:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Could not create SNS client: {e}")
                return False
        
            self.delete_topics(sns_client, region, account_name)
            self.delete_platform_applications(sns_client, region, account_name)
        
            self.cleanup_results['regions_processed'].append({'account_name': account_name, 'region': region})
            
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account_name': account_name})
        
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cleanup completed")
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error: {e}")
            return False

    def save_cleanup_report(self):
        """Save cleanup report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_sns_cleanup_report_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_SNS_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "execution_timestamp": self.execution_timestamp
                },
                "summary": {
                    "total_topics_deleted": len(self.cleanup_results['deleted_topics']),
                    "total_platform_apps_deleted": len(self.cleanup_results['deleted_platform_apps'])
                },
                "detailed_results": self.cleanup_results
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            return report_filename
        except Exception as e:
            self.log_operation('ERROR', f"Failed to save report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.print_colored(Colors.CYAN, "\n" + "[ALERT]" * 30)
            self.print_colored(Colors.BLUE, "[START] ULTRA SNS CLEANUP MANAGER")
            self.print_colored(Colors.CYAN, "[ALERT]" * 30)
            
            selected_accounts = self.cred_manager.select_root_accounts_interactive()
            if not selected_accounts:
                return
            
            selected_regions = self.cred_manager.select_regions_interactive()
            if not selected_regions:
                return
            
            self.print_colored(Colors.YELLOW, f"\n{Symbols.WARN}  Type 'yes' to confirm:")
            if input("   → ").strip().lower() != 'yes':
                self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Cleanup cancelled")
                return
            
            start_time = time.time()
            
            for account_info in selected_accounts:
                for region in selected_regions:
                    self.cleanup_account_region(account_info, region)
            
            total_time = int(time.time() - start_time)
            
            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Cleanup completed successfully!")
            self.print_colored(Colors.WHITE, f"📧 Topics: {len(self.cleanup_results['deleted_topics'])}")
            self.print_colored(Colors.WHITE, f"[MOBILE] Platform Apps: {len(self.cleanup_results['deleted_platform_apps'])}")
            
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Report: {report_file}")
            
        except Exception as e:
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} ERROR: {e}")

    def select_regions_interactive(self, available_regions: List[str]) -> List[str]:
        """Interactive region selection with modern formatting"""
        self.print_colored(Colors.CYAN, "\n" + "="*100)
        self.print_colored(Colors.WHITE, "AVAILABLE REGIONS")
        self.print_colored(Colors.CYAN, "="*100)
        
        for idx, region in enumerate(available_regions, 1):
            self.print_colored(Colors.WHITE, f"  {idx}. {region}")
        
        self.print_colored(Colors.CYAN, "="*100)
        self.print_colored(Colors.WHITE, "\nRegion Selection Options:")
        self.print_colored(Colors.WHITE, "  • Single regions: 1,3,5")
        self.print_colored(Colors.WHITE, "  • Ranges: 1-3")
        self.print_colored(Colors.WHITE, "  • Mixed: 1-2,4")
        self.print_colored(Colors.WHITE, "  • All regions: 'all' or press Enter")
        self.print_colored(Colors.WHITE, "  • Cancel: 'cancel' or 'quit'")
        self.print_colored(Colors.CYAN, "="*100)
        
        selection = input("\n[#] Select regions to process: ").strip().lower()
        
        if selection in ['cancel', 'quit']:
            return []
        
        if not selection or selection == 'all':
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected all {len(available_regions)} regions")
            return available_regions
        
        try:
            indices = self.cred_manager._parse_selection(selection, len(available_regions))
            selected_regions = [available_regions[i] for i in indices]
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
            return selected_regions
        except ValueError as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Invalid selection: {e}")
            return []

def main():
    try:
        manager = UltraCleanupSNSManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
