#!/usr/bin/env python3

"""
Ultra SQS Cleanup Manager

Tool to perform comprehensive cleanup of SQS resources across AWS accounts.

Manages deletion of:
- SQS Queues (Standard and FIFO)
- Dead Letter Queues

PROTECTIONS:
- None (all SQS queues can be recreated)

Author: varadharajaan
Created: 2025-11-24
"""

import os
import json
import boto3
from datetime import datetime
from typing import List
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupSQSManager:
    def __init__(self, config_dir: str = None):
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.sqs_dir = os.path.join(self.config_dir, "aws", "sqs")
        self.reports_dir = os.path.join(self.sqs_dir, "reports")

        self.setup_logging()
        self.user_regions = self._get_user_regions()

        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_queues': [],
            'failed_deletions': [],
        }

    def print_colored(self, color: str, message: str):
        print(f"{color}{message}{Colors.END}")

    def _get_user_regions(self) -> List[str]:
        try:
            config = self.cred_manager.load_root_accounts_config()
            if config:
                return config.get('user_settings', {}).get('user_regions', ['us-east-1'])
        except:
            pass
        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']

    def setup_logging(self):
        try:
            os.makedirs(self.sqs_dir, exist_ok=True)
            self.log_filename = f"{self.sqs_dir}/ultra_sqs_cleanup_{self.execution_timestamp}.log"
            
            import logging
            self.logger = logging.getLogger('sqs_cleanup')
            self.logger.setLevel(logging.INFO)
            handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
            self.logger.addHandler(handler)
        except:
            self.logger = None

    def log(self, msg):
        if self.logger:
            self.logger.info(msg)

    def create_sqs_client(self, access_key, secret_key, region):
        return boto3.client('sqs', aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)

    def delete_queues(self, sqs_client, region, account_name):
        try:
            deleted = 0
            response = sqs_client.list_queues()
            
            for queue_url in response.get('QueueUrls', []):
                try:
                    self.log(f"Deleting queue: {queue_url}")
                    sqs_client.delete_queue(QueueUrl=queue_url)
                    deleted += 1
                    
                    self.cleanup_results['deleted_queues'].append({
                        'queue_url': queue_url,
                        'region': region,
                        'account_name': account_name,
                        'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception as e:
                    self.log(f"Failed to delete {queue_url}: {e}")
                    self.cleanup_results['failed_deletions'].append({
                        'queue_url': queue_url,
                        'error': str(e)
                    })
            
            if deleted > 0:
                self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} queues")
            return True
        except:
            return False

    def cleanup_account_region(self, account_info: dict, region: str) -> bool:
        try:
            account_name = account_info.get('name')
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] Cleanup: {account_name} - {region}")
            
            sqs_client = self.create_sqs_client(
                account_info.get('access_key'),
                account_info.get('secret_key'),
                region
            )
            
            self.delete_queues(sqs_client, region, account_name)
            
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account_name': account_name})
            
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   [ERROR] Error: {e}")
            return False

    def save_report(self):
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_file = f"{self.reports_dir}/ultra_sqs_cleanup_{self.execution_timestamp}.json"
            
            with open(report_file, 'w') as f:
                json.dump({
                    "metadata": {"cleanup_type": "SQS", "timestamp": self.execution_timestamp},
                    "summary": {"queues_deleted": len(self.cleanup_results['deleted_queues'])},
                    "details": self.cleanup_results
                }, f, indent=2)
            
            return report_file
        except:
            return None

    def run(self):
        self.print_colored(Colors.BLUE, "\n[START] ULTRA SQS CLEANUP MANAGER")
        
        accounts = self.cred_manager.select_root_accounts_interactive()
        if not accounts:
            return
        
        regions = self.select_regions()
        if not regions:
            return
        
        if input("\nType 'DELETE': ").strip().upper() != 'DELETE':
            return
        
        for acc in accounts:
            for reg in regions:
                self.cleanup_account_region(acc, reg)
        
        self.print_colored(Colors.WHITE, f"\n[STATS] Queues deleted: {len(self.cleanup_results['deleted_queues'])}")
        
        report = self.save_report()
        if report:
            self.print_colored(Colors.GREEN, f"[OK] Report: {report}")

    def select_regions(self):
        print("\nRegions: 1-all, 2-us-east-1, 3-custom")
        choice = input("→ ").strip()
        if choice == '1' or not choice:
            return self.user_regions
        elif choice == '2':
            return ['us-east-1']
        return []

def main():
    try:
        UltraCleanupSQSManager().run()
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
