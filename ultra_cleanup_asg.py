#!/usr/bin/env python3

import os
import json
import boto3
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from botocore.exceptions import ClientError, BotoCoreError
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupASGManager:
    """
    Tool to perform comprehensive cleanup of Auto Scaling Group resources across AWS accounts.

    Manages deletion of:
    - Auto Scaling Groups (ASGs)
    - Launch Templates associated with ASGs
    - Scaling Policies
    - Scheduled Actions

    Author: varadharajaan
    Created: 2025-07-05
    """

    def __init__(self, config_dir: str = None):
        """Initialize the ASG Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.asg_dir = os.path.join(self.config_dir, "aws", "asg")
        self.reports_dir = os.path.join(self.asg_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_asgs': [],
            'failed_deletions': [],
            'skipped_asgs': [],
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
            self.print_colored(Colors.YELLOW, f"⚠️  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.asg_dir, exist_ok=True)

            # Save log file in the aws/asg directory
            self.log_filename = f"{self.asg_dir}/ultra_asg_cleanup_log_{self.execution_timestamp}.log"

            # Create a file handler for detailed logging
            import logging

            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_asg_cleanup')
            self.operation_logger.setLevel(logging.INFO)

            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)

            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)

            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)

            # Log initial information
            self.operation_logger.info("=" * 100)
            self.operation_logger.info("🚨 ULTRA ASG CLEANUP SESSION STARTED 🚨")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config Dir: {self.config_dir}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)

        except Exception as e:
            self.print_colored(Colors.YELLOW, f"Warning: Could not setup detailed logging: {e}")
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

    def create_asg_client(self, access_key, secret_key, region):
        """Create ASG client using account credentials"""
        try:
            asg_client = boto3.client(
                'autoscaling',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            # Test the connection
            asg_client.describe_auto_scaling_groups(MaxRecords=1)
            return asg_client

        except Exception as e:
            self.log_operation('ERROR', f"Failed to create ASG client for {region}: {e}")
            raise

    def get_all_asgs_in_region(self, asg_client, region, account_info):
        """Get all Auto Scaling Groups in a specific region"""
        try:
            asgs = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"🔍 Scanning for ASGs in {region} ({account_name})")
            print(f"   🔍 Scanning for ASGs in {region} ({account_name})...")

            paginator = asg_client.get_paginator('describe_auto_scaling_groups')

            for page in paginator.paginate():
                for asg in page['AutoScalingGroups']:
                    asg_name = asg['AutoScalingGroupName']
                    min_size = asg['MinSize']
                    max_size = asg['MaxSize']
                    desired_capacity = asg['DesiredCapacity']
                    instance_count = len(asg.get('Instances', []))

                    # Get ASG name from tags
                    asg_name_tag = asg_name
                    created_time = "Unknown"
                    creator = "Unknown"

                    for tag in asg.get('Tags', []):
                        if tag['Key'] == 'Name':
                            asg_name_tag = tag['Value']
                        elif tag['Key'] == 'CreatedTime':
                            created_time = tag['Value']
                        elif tag['Key'] == 'Creator':
                            creator = tag['Value']
                        elif tag['Key'] == 'CreatedAt':
                            created_time = tag['Value']
                        elif tag['Key'] == 'CreatedBy':
                            creator = tag['Value']

                    # Get launch template info
                    launch_template_id = None
                    launch_template_name = None

                    if 'LaunchTemplate' in asg:
                        launch_template_id = asg['LaunchTemplate'].get('LaunchTemplateId')
                        launch_template_name = asg['LaunchTemplate'].get('LaunchTemplateName')

                    asg_info = {
                        'asg_name': asg_name,
                        'asg_name_tag': asg_name_tag,
                        'min_size': min_size,
                        'max_size': max_size,
                        'desired_capacity': desired_capacity,
                        'instance_count': instance_count,
                        'created_time': created_time,
                        'creator': creator,
                        'launch_template_id': launch_template_id,
                        'launch_template_name': launch_template_name,
                        'region': region,
                        'account_info': account_info
                    }

                    asgs.append(asg_info)

            self.log_operation('INFO', f"📦 Found {len(asgs)} ASGs in {region} ({account_name})")
            print(f"   📦 Found {len(asgs)} ASGs in {region} ({account_name})")

            return asgs

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting ASGs in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting ASGs in {region}: {e}")
            return []

    def delete_asg(self, asg_client, asg_info):
        """Delete an Auto Scaling Group"""
        try:
            asg_name = asg_info['asg_name']
            region = asg_info['region']
            account_name = asg_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"🗑️  Deleting ASG {asg_name} in {region} ({account_name})")
            print(f"   🗑️  Deleting ASG {asg_name}...")

            # Step 1: Delete scheduled actions (if any)
            try:
                self.log_operation('INFO', f"🕒 Checking for scheduled actions...")
                print(f"   🕒 Checking for scheduled actions...")

                actions_response = asg_client.describe_scheduled_actions(
                    AutoScalingGroupName=asg_name
                )
                actions = actions_response.get('ScheduledUpdateGroupActions', [])

                if actions:
                    self.log_operation('INFO', f"⏰ Found {len(actions)} scheduled action(s)")
                    print(f"   ⏰ Found {len(actions)} scheduled action(s)")

                    for action in actions:
                        action_name = action['ScheduledActionName']
                        self.log_operation('INFO', f"🗑️ Deleting scheduled action: {action_name}")
                        print(f"   🗑️ Deleting scheduled action: {action_name}")

                        asg_client.delete_scheduled_action(
                            AutoScalingGroupName=asg_name,
                            ScheduledActionName=action_name
                        )
            except Exception as e:
                self.log_operation('WARNING', f"⚠️ Warning: Failed to clean up scheduled actions: {e}")
                print(f"   ⚠️ Warning: Failed to clean up scheduled actions: {e}")

            # Step 2: Check and delete any scaling policies
            try:
                self.log_operation('INFO', f"📊 Checking for scaling policies...")
                print(f"   📊 Checking for scaling policies...")

                policies_response = asg_client.describe_policies(
                    AutoScalingGroupName=asg_name
                )
                policies = policies_response.get('ScalingPolicies', [])

                if policies:
                    self.log_operation('INFO', f"📈 Found {len(policies)} scaling policy(s)")
                    print(f"   📈 Found {len(policies)} scaling policy(s)")

                    for policy in policies:
                        policy_name = policy['PolicyName']
                        self.log_operation('INFO', f"🗑️ Deleting scaling policy: {policy_name}")
                        print(f"   🗑️ Deleting scaling policy: {policy_name}")

                        asg_client.delete_policy(
                            AutoScalingGroupName=asg_name,
                            PolicyName=policy_name
                        )
            except Exception as e:
                self.log_operation('WARNING', f"⚠️ Warning: Failed to clean up scaling policies: {e}")
                print(f"   ⚠️ Warning: Failed to clean up scaling policies: {e}")

            # Step 3: Delete the ASG with ForceDelete to terminate instances
            self.log_operation('INFO', f"💥 Deleting Auto Scaling Group with Force option")
            print(f"   💥 Deleting Auto Scaling Group with Force option...")

            asg_client.delete_auto_scaling_group(
                AutoScalingGroupName=asg_name,
                ForceDelete=True
            )

            self.log_operation('INFO', f"✅ Successfully deleted ASG: {asg_name}")
            print(f"   ✅ Successfully deleted ASG: {asg_name}")

            # Update cleanup results
            self.cleanup_results['deleted_asgs'].append({
                'asg_name': asg_name,
                'region': region,
                'account_info': asg_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'instance_count': asg_info['instance_count'],
                'launch_template_id': asg_info['launch_template_id'],
                'launch_template_name': asg_info['launch_template_name']
            })

            return True

        except Exception as e:
            account_name = asg_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to delete ASG {asg_name}: {e}")
            print(f"   ❌ Failed to delete ASG {asg_name}: {e}")

            # Update cleanup results
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'asg',
                'resource_id': asg_name,
                'region': region,
                'account_info': asg_info['account_info'],
                'error': str(e)
            })

            return False

    def cleanup_account_region(self, account_info, region):
        """Clean up ASG resources in a specific account and region"""
        try:
            access_key = account_info['access_key']
            secret_key = account_info['secret_key']
            account_id = account_info['account_id']
            account_key = account_info['account_key']

            self.log_operation('INFO', f"🧹 Starting ASG cleanup for {account_key} ({account_id}) in {region}")
            print(f"\n🧹 Starting ASG cleanup for {account_key} ({account_id}) in {region}")

            # Create ASG client
            asg_client = self.create_asg_client(access_key, secret_key, region)

            # Get all ASGs in the region
            asgs = self.get_all_asgs_in_region(asg_client, region, account_info)

            # Add region summary to results
            region_summary = {
                'account_key': account_key,
                'account_id': account_id,
                'region': region,
                'asgs_found': len(asgs)
            }

            self.cleanup_results['regions_processed'].append(region_summary)

            self.log_operation('INFO', f"📊 {account_key} ({region}) ASG resources summary:")
            self.log_operation('INFO', f"   📦 Auto Scaling Groups: {len(asgs)}")

            print(f"   📊 ASG resources found: {len(asgs)} ASGs")

            if not asgs:
                self.log_operation('INFO', f"No ASG resources found in {account_key} ({region})")
                print(f"   ✅ No ASG resources to clean up in {region}")
                return True

            # Delete ASGs sequentially
            if asgs:
                self.log_operation('INFO', f"🗑️  Deleting {len(asgs)} ASGs in {account_key} ({region}) sequentially")
                print(f"\n   🗑️  Deleting {len(asgs)} ASGs sequentially...")

                deleted_count = 0
                failed_count = 0

                for i, asg in enumerate(asgs, 1):
                    asg_name = asg['asg_name']
                    print(f"   [{i}/{len(asgs)}] Processing ASG {asg_name}...")

                    try:
                        success = self.delete_asg(asg_client, asg)
                        if success:
                            deleted_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log_operation('ERROR', f"Error deleting ASG {asg_name}: {e}")
                        print(f"   ❌ Error deleting ASG {asg_name}: {e}")

                print(f"   ✅ Deleted {deleted_count} ASGs, ❌ Failed: {failed_count}")

                # Wait for ASGs to be deleted
                if deleted_count > 0:
                    self.log_operation('INFO', f"⏳ Waiting 30 seconds for {deleted_count} ASGs to be deleted...")
                    print(f"   ⏳ Waiting 30 seconds for ASGs to be deleted...")
                    time.sleep(30)

            self.log_operation('INFO', f"✅ ASG cleanup completed for {account_key} ({region})")
            print(f"\n   ✅ ASG cleanup completed for {account_key} ({region})")
            return True

        except Exception as e:
            account_key = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error cleaning up ASG resources in {account_key} ({region}): {e}")
            print(f"   ❌ Error cleaning up ASG resources in {account_key} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_info': account_info,
                'region': region,
                'error': str(e)
            })
            return False

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n🌍 Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "💡 Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(f"Select regions (1-{len(self.user_regions)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all" or not choice:
                    self.print_colored(Colors.GREEN, f"✅ Selected all {len(self.user_regions)} regions")
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(choice, len(self.user_regions))
                if not selected_indices:
                    self.print_colored(Colors.RED, "❌ Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"✅ Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
                return selected_regions

            except Exception as e:
                self.print_colored(Colors.RED, f"❌ Error processing selection: {str(e)}")

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_asg_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_asgs_deleted = len(self.cleanup_results['deleted_asgs'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_asgs'])

            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}

            for asg in self.cleanup_results['deleted_asgs']:
                account = asg['account_info'].get('account_key', 'Unknown')
                region = asg['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {'asgs': 0, 'regions': set()}
                deletions_by_account[account]['asgs'] += 1
                deletions_by_account[account]['regions'].add(region)

                if region not in deletions_by_region:
                    deletions_by_region[region] = {'asgs': 0}
                deletions_by_region[region]['asgs'] += 1

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_ASG_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(
                        set(rp['account_key'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(
                        set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_asgs_deleted": total_asgs_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_asgs": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_asgs": self.cleanup_results['deleted_asgs'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_asgs": self.cleanup_results['skipped_asgs'],
                    "errors": self.cleanup_results['errors']
                }
            }

            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation('INFO', f"✅ Ultra ASG cleanup report saved to: {report_filename}")
            return report_filename

        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save ultra ASG cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA ASG CLEANUP SESSION 🚨")

            self.print_colored(Colors.YELLOW, "🚨" * 30)
            self.print_colored(Colors.RED, "💥 ULTRA ASG CLEANUP - SEQUENTIAL 💥")
            self.print_colored(Colors.YELLOW, "🚨" * 30)
            self.print_colored(Colors.WHITE, f"📅 Execution Date/Time: {self.current_time} UTC")
            self.print_colored(Colors.WHITE, f"👤 Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"📋 Log File: {self.log_filename}")

            # STEP 1: Select root accounts
            self.print_colored(Colors.YELLOW, "\n🔑 Select Root AWS Accounts for ASG Cleanup:")

            root_accounts = self.cred_manager.select_root_accounts_interactive(allow_multiple=True)
            if not root_accounts:
                self.print_colored(Colors.RED, "❌ No root accounts selected, exiting...")
                return
            selected_accounts = root_accounts

            # STEP 2: Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.RED, "❌ No regions selected, exiting...")
                return

            # STEP 3: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(selected_regions)

            self.print_colored(Colors.YELLOW, f"\n🎯 ASG CLEANUP CONFIGURATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"🔑 Credential source: ROOT ACCOUNTS")
            self.print_colored(Colors.WHITE, f"🏦 Selected accounts: {len(selected_accounts)}")
            self.print_colored(Colors.WHITE, f"🌍 Regions per account: {len(selected_regions)}")
            self.print_colored(Colors.WHITE, f"📋 Total operations: {total_operations}")
            self.print_colored(Colors.YELLOW, "=" * 80)

            # Show what will be cleaned up
            self.print_colored(Colors.RED, f"\n⚠️  WARNING: This will delete ALL of the following ASG resources:")
            self.print_colored(Colors.WHITE, f"    • Auto Scaling Groups (ASGs)")
            self.print_colored(Colors.WHITE, f"    • EC2 Instances within ASGs")
            self.print_colored(Colors.WHITE, f"    • Scaling Policies")
            self.print_colored(Colors.WHITE, f"    • Scheduled Actions")
            self.print_colored(Colors.WHITE, f"    across {len(selected_accounts)} accounts in {len(selected_regions)} regions ({total_operations} operations)")
            self.print_colored(Colors.RED, f"    This action CANNOT be undone!")

            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with ASG cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")

            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra ASG cleanup cancelled by user")
                self.print_colored(Colors.RED, "❌ Cleanup cancelled")
                return

            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")

            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra ASG cleanup cancelled at final confirmation")
                self.print_colored(Colors.RED, "❌ Cleanup cancelled")
                return

            # STEP 4: Start the cleanup sequentially
            self.print_colored(Colors.RED, f"\n💥 STARTING ASG CLEANUP...")
            self.log_operation('INFO', f"🚨 ASG CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(selected_regions)} regions")

            start_time = time.time()

            successful_tasks = 0
            failed_tasks = 0

            # Create tasks list
            tasks = []
            for account_info in selected_accounts:
                for region in selected_regions:
                    tasks.append((account_info, region))

            # Process each task sequentially
            for i, (account_info, region) in enumerate(tasks, 1):
                account_key = account_info.get('account_key', 'Unknown')
                self.print_colored(Colors.CYAN, f"\n[{i}/{len(tasks)}] Processing {account_key} in {region}...")

                try:
                    success = self.cleanup_account_region(account_info, region)
                    if success:
                        successful_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    self.log_operation('ERROR', f"Task failed for {account_key} ({region}): {e}")
                    self.print_colored(Colors.RED, f"❌ Task failed for {account_key} ({region}): {e}")

            end_time = time.time()
            total_time = int(end_time - start_time)

            # STEP 5: Display final results
            self.print_colored(Colors.YELLOW, f"\n💥" + "="*25 + " ASG CLEANUP COMPLETE " + "="*25)
            self.print_colored(Colors.WHITE, f"⏱️  Total execution time: {total_time} seconds")
            self.print_colored(Colors.GREEN, f"✅ Successful operations: {successful_tasks}")
            self.print_colored(Colors.RED, f"❌ Failed operations: {failed_tasks}")
            self.print_colored(Colors.WHITE, f"📦 Auto Scaling Groups deleted: {len(self.cleanup_results['deleted_asgs'])}")
            self.print_colored(Colors.RED, f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}")

            self.log_operation('INFO', f"ASG CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Auto Scaling Groups deleted: {len(self.cleanup_results['deleted_asgs'])}")

            # STEP 6: Show account summary
            if self.cleanup_results['deleted_asgs']:
                self.print_colored(Colors.YELLOW, f"\n📊 Deletion Summary by Account:")

                # Group by account
                account_summary = {}

                for asg in self.cleanup_results['deleted_asgs']:
                    account = asg['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'asgs': 0, 'regions': set()}
                    account_summary[account]['asgs'] += 1
                    account_summary[account]['regions'].add(asg['region'])

                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.PURPLE, f"   🏦 {account}:")
                    self.print_colored(Colors.WHITE, f"      📦 Auto Scaling Groups: {summary['asgs']}")
                    self.print_colored(Colors.WHITE, f"      🌍 Regions: {regions_list}")

            # STEP 7: Show failures if any
            if self.cleanup_results['failed_deletions']:
                self.print_colored(Colors.RED, f"\n❌ Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    account_key = failure['account_info'].get('account_key', 'Unknown')
                    self.print_colored(Colors.WHITE, f"   • {failure['resource_type']} {failure['resource_id']} in {account_key} ({failure['region']})")
                    self.print_colored(Colors.WHITE, f"     Error: {failure['error']}")

                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    self.print_colored(Colors.WHITE, f"   ... and {remaining} more failures (see detailed report)")

            # Save comprehensive report
            self.print_colored(Colors.CYAN, f"\n📄 Saving ASG cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"✅ ASG cleanup report saved to: {report_file}")

            self.print_colored(Colors.GREEN, f"✅ Session log saved to: {self.log_filename}")

            self.print_colored(Colors.RED, f"\n💥 ASG CLEANUP COMPLETE! 💥")
            self.print_colored(Colors.YELLOW, "🚨" * 30)

        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in ASG cleanup execution: {str(e)}")
            self.print_colored(Colors.RED, f"\n❌ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraCleanupASGManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ ASG cleanup interrupted by user")
        exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()