#!/usr/bin/env python3
"""
Launch Template Manager - Lists and deletes launch templates across multiple AWS accounts and regions
"""

import boto3
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
import time
from concurrent.futures import ThreadPoolExecutor
from botocore.exceptions import ClientError

REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-west-2", "eu-west-3", "eu-north-1", "eu-south-1", "eu-central-1",
    "ap-south-1", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3", "ap-southeast-1", "ap-southeast-2",
    "ca-central-1", "sa-east-1", "af-south-1", "me-south-1"
]

# Launch templates with these prefixes won't be deleted
PROTECTED_PREFIXES = ['prod-', 'prod_', 'production-', 'protected-']

class LaunchTemplateManager:
    def __init__(self, accounts_file="aws_accounts_config.json"):
        self.accounts_file = accounts_file
        self.accounts = self.load_accounts()
        self.now = datetime.now()
        self.results = {
            "lt_found": 0,
            "lt_deleted": 0,
            "regions_scanned": 0,
            "accounts_scanned": 0,
            "errors": []
        }

    def load_accounts(self) -> Dict:
        """Load AWS account configurations"""
        try:
            if not os.path.exists(self.accounts_file):
                print(f"[ERROR] Accounts file '{self.accounts_file}' not found")
                sys.exit(1)
            
            with open(self.accounts_file, 'r') as f:
                config = json.load(f)
            
            print(f"[OK] Loaded {len(config['accounts'])} accounts from: {self.accounts_file}")
            return config["accounts"]
        
        except Exception as e:
            print(f"[ERROR] Error loading accounts: {e}")
            sys.exit(1)
    
    def select_accounts(self) -> List[str]:
        """Prompt user to select accounts to process"""
        account_names = list(self.accounts.keys())
        
        print("\n" + "="*80)
        print("[LIST] Available AWS Accounts:")
        print("="*80)
        
        for i, acc_name in enumerate(account_names, 1):
            acc = self.accounts[acc_name]
            print(f"{i:2d}. {acc_name} (ID: {acc['account_id']}, Email: {acc['email']})")
        
        print(f"{len(account_names)+1:2d}. ALL accounts")
        
        while True:
            try:
                selection = input("\nSelect accounts to process (comma-separated numbers, range with '-', or 'all'): ").strip().lower()
                
                if selection == 'all' or selection == str(len(account_names) + 1):
                    return account_names
                
                selected_indices = set()
                parts = selection.split(',')
                
                for part in parts:
                    part = part.strip()
                    if '-' in part:
                        try:
                            start, end = map(int, part.split('-'))
                            if 1 <= start <= end <= len(account_names):
                                selected_indices.update(range(start, end + 1))
                            else:
                                print(f"[WARN] Invalid range: {part}")
                        except ValueError:
                            print(f"[WARN] Invalid range format: {part}")
                    else:
                        try:
                            idx = int(part)
                            if 1 <= idx <= len(account_names):
                                selected_indices.add(idx)
                            else:
                                print(f"[WARN] Invalid index: {idx}")
                        except ValueError:
                            print(f"[WARN] Invalid input: {part}")
                
                if selected_indices:
                    return [account_names[i-1] for i in selected_indices]
                else:
                    print("[ERROR] No valid selections made")
            
            except Exception as e:
                print(f"[ERROR] Error during account selection: {e}")
    
    def select_regions(self) -> List[str]:
        """Prompt user to select regions to process"""
        print("\n" + "="*80)
        print("🌎 AWS Regions:")
        print("="*80)
        
        for i, region in enumerate(REGIONS, 1):
            print(f"{i:2d}. {region}")
        
        print(f"{len(REGIONS)+1:2d}. ALL regions")
        
        while True:
            try:
                selection = input("\nSelect regions to process (comma-separated numbers, range with '-', or 'all'): ").strip().lower()
                
                if selection == 'all' or selection == str(len(REGIONS) + 1):
                    return REGIONS
                
                selected_indices = set()
                parts = selection.split(',')
                
                for part in parts:
                    part = part.strip()
                    if '-' in part:
                        try:
                            start, end = map(int, part.split('-'))
                            if 1 <= start <= end <= len(REGIONS):
                                selected_indices.update(range(start, end + 1))
                            else:
                                print(f"[WARN] Invalid range: {part}")
                        except ValueError:
                            print(f"[WARN] Invalid range format: {part}")
                    else:
                        try:
                            idx = int(part)
                            if 1 <= idx <= len(REGIONS):
                                selected_indices.add(idx)
                            else:
                                print(f"[WARN] Invalid index: {idx}")
                        except ValueError:
                            print(f"[WARN] Invalid input: {part}")
                
                if selected_indices:
                    return [REGIONS[i-1] for i in selected_indices]
                else:
                    print("[ERROR] No valid selections made")
            
            except Exception as e:
                print(f"[ERROR] Error during region selection: {e}")

    def process_accounts(self, selected_accounts: List[str], selected_regions: List[str], age_days: int) -> Dict:
        """Process selected accounts and regions to list and optionally delete old launch templates"""
        cutoff_date = self.now - timedelta(days=age_days)
        total_templates = 0
        total_old_templates = 0
        total_deleted = 0
        
        print(f"\n[SCAN] Searching for launch templates older than {age_days} days ({cutoff_date.strftime('%Y-%m-%d')})")
        print(f"[NETWORK] Scanning {len(selected_regions)} regions across {len(selected_accounts)} accounts")
        
        for account_name in selected_accounts:
            self.results["accounts_scanned"] += 1
            account_info = self.accounts[account_name]
            
            # Create credentials
            credentials = {
                "access_key": account_info["access_key"],
                "secret_key": account_info["secret_key"],
                "account_id": account_info["account_id"],
                "account_name": account_name,
                "email": account_info.get("email", "No email provided")
            }
            
            print(f"\n{'='*100}")
            print(f"[ACCOUNT] Processing account: {account_name} (ID: {account_info['account_id']})")
            print(f"{'='*100}")
            
            account_templates = 0
            account_old_templates = 0
            account_deleted = 0
            
            for region in selected_regions:
                self.results["regions_scanned"] += 1
                try:
                    print(f"\n🗺️  Region: {region}")
                    
                    # Get EC2 client for this account and region
                    ec2_client = boto3.client(
                        'ec2',
                        aws_access_key_id=credentials['access_key'],
                        aws_secret_access_key=credentials['secret_key'],
                        region_name=region
                    )
                    
                    # Get launch templates
                    paginator = ec2_client.get_paginator('describe_launch_templates')
                    templates = []
                    
                    for page in paginator.paginate():
                        templates.extend(page.get('LaunchTemplates', []))
                    
                    if not templates:
                        print(f"   [MAILBOX] No launch templates found in {region}")
                        continue
                    
                    # Sort templates by creation time (newest first)
                    templates.sort(key=lambda x: x.get('CreateTime', datetime.min), reverse=True)
                    
                    print(f"   [LIST] Found {len(templates)} launch templates in {region}")
                    account_templates += len(templates)
                    total_templates += len(templates)
                    self.results["lt_found"] += len(templates)
                    
                    # Display and identify old templates
                    old_templates = []
                    protected_templates = []
                    
                    print(f"\n   {'ID':<25} {'Name':<40} {'Created':<20} {'Age (days)':<10} {'Status'}")
                    print(f"   {'-'*25} {'-'*40} {'-'*20} {'-'*10} {'-'*20}")
                    
                    for tpl in templates:
                        template_id = tpl['LaunchTemplateId']
                        template_name = tpl['LaunchTemplateName']
                        create_time = tpl.get('CreateTime', datetime.min)
                        
                        # Skip if create_time is None or not a datetime
                        if not isinstance(create_time, datetime):
                            continue
                        
                        # Calculate age in days
                        age_days_actual = (self.now - create_time).days
                        
                        status = ""
                        if any(template_name.startswith(prefix) for prefix in PROTECTED_PREFIXES):
                            status = "[SECURE] PROTECTED"
                            protected_templates.append(tpl)
                        elif age_days_actual >= age_days:
                            status = "[WARN] OLD"
                            old_templates.append(tpl)
                        else:
                            status = "[OK] KEEP"
                        
                        print(f"   {template_id:<25} {template_name[:38]:<40} {create_time.strftime('%Y-%m-%d %H:%M:%S'):<20} {age_days_actual:<10} {status}")
                    
                    account_old_templates += len(old_templates)
                    total_old_templates += len(old_templates)
                    
                    # Prompt for deletion if old templates exist
                    if old_templates:
                        print(f"\n   [WARN] Found {len(old_templates)} templates older than {age_days} days")
                        
                        delete_choice = input(f"   Delete these {len(old_templates)} old templates in {region}? (y/n): ").strip().lower()
                        if delete_choice == 'y':
                            deleted_count = 0
                            for tpl in old_templates:
                                template_id = tpl['LaunchTemplateId']
                                template_name = tpl['LaunchTemplateName']
                                try:
                                    ec2_client.delete_launch_template(LaunchTemplateId=template_id)
                                    print(f"   [OK] Deleted: {template_name} ({template_id})")
                                    deleted_count += 1
                                    account_deleted += 1
                                    total_deleted += 1
                                    self.results["lt_deleted"] += 1
                                except Exception as e:
                                    error_msg = f"Failed to delete template {template_id} in {region} for {account_name}: {str(e)}"
                                    print(f"   [ERROR] {error_msg}")
                                    self.results["errors"].append(error_msg)
                            
                            print(f"   [OK] Deleted {deleted_count} templates in {region}")
                        else:
                            print(f"   ℹ️ Skipped deletion in {region}")
                    
                    if protected_templates:
                        print(f"\n   [SECURE] {len(protected_templates)} templates are protected due to name prefixes")
                
                except Exception as e:
                    error_msg = f"Error processing {region} in account {account_name}: {str(e)}"
                    print(f"   [ERROR] {error_msg}")
                    self.results["errors"].append(error_msg)
            
            print(f"\n[STATS] Account Summary for {account_name}:")
            print(f"   - Total templates: {account_templates}")
            print(f"   - Templates older than {age_days} days: {account_old_templates}")
            print(f"   - Templates deleted: {account_deleted}")
        
        # Overall summary
        print(f"\n{'='*100}")
        print(f"[STATS] FINAL SUMMARY")
        print(f"{'='*100}")
        print(f"Total accounts processed: {len(selected_accounts)}")
        print(f"Total regions scanned: {len(selected_regions)}")
        print(f"Total launch templates found: {total_templates}")
        print(f"Total templates older than {age_days} days: {total_old_templates}")
        print(f"Total templates deleted: {total_deleted}")
        
        if self.results["errors"]:
            print(f"\n[WARN] There were {len(self.results['errors'])} errors during processing")
            print("See the generated report for details.")
        
        return self.results
    
    def generate_report(self, selected_accounts: List[str], selected_regions: List[str], age_days: int) -> str:
        """Generate a report of the operation"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report = {
            "metadata": {
                "execution_date": datetime.now().strftime('%Y-%m-%d'),
                "execution_time": datetime.now().strftime('%H:%M:%S'),
                "executed_by": os.environ.get('USER', 'unknown_user'),
                "execution_timestamp": timestamp,
            },
            "parameters": {
                "selected_accounts": selected_accounts,
                "selected_regions": selected_regions,
                "age_threshold_days": age_days,
                "protected_prefixes": PROTECTED_PREFIXES
            },
            "results": self.results
        }
        
        # Create output directory
        os.makedirs("reports", exist_ok=True)
        
        # Save to JSON file
        filename = f"reports/lt_cleanup_report_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n[FILE] Report saved to: {filename}")
        return filename

def main():
    print("\n" + "="*100)
    print("[START] Launch Template Manager - List and cleanup old launch templates across AWS accounts")
    print("="*100)
    
    # Initialize manager
    manager = LaunchTemplateManager()
    
    # Select accounts
    selected_accounts = manager.select_accounts()
    if not selected_accounts:
        print("[ERROR] No accounts selected. Exiting.")
        sys.exit(1)
    
    # Select regions
    selected_regions = manager.select_regions()
    if not selected_regions:
        print("[ERROR] No regions selected. Exiting.")
        sys.exit(1)
    
    # Get age threshold
    age_days = 0
    while age_days <= 0:
        try:
            age_input = input("\nEnter age threshold in days (templates older than this will be considered for deletion): ")
            age_days = int(age_input)
            if age_days <= 0:
                print("[ERROR] Please enter a positive number of days")
        except ValueError:
            print("[ERROR] Please enter a valid number")
    
    print(f"\n[OK] Selected {len(selected_accounts)} accounts")
    print(f"[OK] Selected {len(selected_regions)} regions")
    print(f"[OK] Age threshold: {age_days} days")
    
    # Confirm before proceeding
    confirm = input("\nProceed with scanning and potential deletion? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Operation cancelled by user")
        sys.exit(0)
    
    start_time = time.time()
    
    # Process accounts
    results = manager.process_accounts(selected_accounts, selected_regions, age_days)
    
    # Generate report
    report_file = manager.generate_report(selected_accounts, selected_regions, age_days)
    
    end_time = time.time()
    duration = end_time - start_time
    minutes, seconds = divmod(duration, 60)
    
    print(f"\nOperation completed in {int(minutes)} minutes and {seconds:.2f} seconds")
    print(f"Found {results['lt_found']} launch templates, deleted {results['lt_deleted']}")
    print(f"Full report available at: {report_file}")

if __name__ == "__main__":
    main()