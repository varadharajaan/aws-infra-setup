#!/usr/bin/env python3
"""Ultra ECR Cleanup Manager - Deletes ECR repositories and images"""

import os, json, boto3, time
from datetime import datetime
from typing import List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors

class UltraCleanupECRManager:
    def __init__(self, config_dir: str = None):
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.ecr_dir = os.path.join(self.config_dir, "aws", "ecr")
        self.reports_dir = os.path.join(self.ecr_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_repositories': [],
            'failed_deletions': []
        }

    def print_colored(self, color: str, message: str):
        print(f"{color}{message}{Colors.END}")

    def _get_regions(self):
        try:
            config = self.cred_manager.load_root_accounts_config()
            return config.get('user_settings', {}).get('user_regions', ['us-east-1'])
        except:
            return ['us-east-1', 'us-west-2']

    def delete_repositories(self, client, region, account):
        deleted = 0
        paginator = client.get_paginator('describe_repositories')
        
        for page in paginator.paginate():
            for repo in page.get('repositories', []):
                repo_name = repo['repositoryName']
                try:
                    # Delete repository with all images
                    client.delete_repository(
                        repositoryName=repo_name,
                        force=True  # Delete even if contains images
                    )
                    deleted += 1
                    self.cleanup_results['deleted_repositories'].append({
                        'repository_name': repo_name,
                        'uri': repo['repositoryUri'],
                        'region': region,
                        'account': account,
                        'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'repository': repo_name, 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} repositories")

    def cleanup_account_region(self, account_info: dict, region: str):
        try:
            account_name = account_info.get('name')
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] {account_name} - {region}")
            
            client = boto3.client('ecr',
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            
            self.delete_repositories(client, region, account_name)
            
            if account_name not in [a['account'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account': account_name})
            
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   [ERROR] {e}")
            return False

    def save_report(self):
        report_file = f"{self.reports_dir}/ultra_ecr_cleanup_{self.execution_timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump({"summary": {
                "repositories": len(self.cleanup_results['deleted_repositories'])
            }, "details": self.cleanup_results}, f, indent=2)
        return report_file

    def run(self):
        self.print_colored(Colors.BLUE, "\n[START] ULTRA ECR CLEANUP MANAGER")
        
        accounts = self.cred_manager.select_root_accounts_interactive()
        if not accounts:
            return
        
        regions = self._get_regions()
        
        if input("\nType 'DELETE': ").strip().upper() != 'DELETE':
            return
        
        for acc in accounts:
            for reg in regions:
                self.cleanup_account_region(acc, reg)
        
        self.print_colored(Colors.WHITE, f"\n[STATS] Repositories: {len(self.cleanup_results['deleted_repositories'])}")
        self.print_colored(Colors.GREEN, f"[OK] Report: {self.save_report()}")

def main():
    try:
        UltraCleanupECRManager().run()
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
