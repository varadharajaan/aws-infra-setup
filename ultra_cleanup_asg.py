#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError
from typing import List, Dict, Any, Set, Tuple

class UltraASGCleanupManager:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize log file
        self.setup_detailed_logging()
        
        # Load configuration
        self.load_configuration()
        
        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_asgs': [],
            'failed_deletions': [],
            'skipped_asgs': [],
            'errors': []
        }
        
        # Store discovered ASGs
        self.all_asgs = []

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/ec2/asg"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/ec2/asg directory
            self.log_filename = f"{log_dir}/ultra_asg_cleanup_log_{self.execution_timestamp}.log"
            
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
            self.operation_logger.info(f"Config File: {self.config_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Simple logging operation (no thread safety needed)"""
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

    def load_configuration(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            self.log_operation('INFO', f"✅ Configuration loaded from: {self.config_file}")
            
            # Validate accounts
            if 'accounts' not in self.config_data:
                raise ValueError("No 'accounts' section found in configuration")
            
            # Filter out incomplete accounts
            valid_accounts = {}
            for account_name, account_data in self.config_data['accounts'].items():
                if (account_data.get('access_key') and 
                    account_data.get('secret_key') and
                    account_data.get('account_id') and
                    not account_data.get('access_key').startswith('ADD_')):
                    valid_accounts[account_name] = account_data
                else:
                    self.log_operation('WARNING', f"Skipping incomplete account: {account_name}")
            
            self.config_data['accounts'] = valid_accounts
            
            self.log_operation('INFO', f"📊 Valid accounts loaded: {len(valid_accounts)}")
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                self.log_operation('INFO', f"   • {account_name}: {account_id} ({email})")
            
            # Get user regions
            self.user_regions = self.config_data.get('user_settings', {}).get('user_regions', [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
            ])
            
            self.log_operation('INFO', f"🌍 Regions to process: {self.user_regions}")
            
        except FileNotFoundError as e:
            self.log_operation('ERROR', f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation('ERROR', f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation('ERROR', f"Error loading configuration: {e}")
            sys.exit(1)

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

    def get_all_asgs_in_region(self, asg_client, region, account_name):
        """Get all Auto Scaling Groups in a specific region"""
        try:
            asgs = []
            
            self.log_operation('INFO', f"🔍 Scanning for ASGs in {region} ({account_name})")
            
            paginator = asg_client.get_paginator('describe_auto_scaling_groups')
            
            for page in paginator.paginate():
                for asg in page['AutoScalingGroups']:
                    asg_name = asg['AutoScalingGroupName']
                    min_size = asg['MinSize']
                    max_size = asg['MaxSize']
                    desired_capacity = asg['DesiredCapacity']
                    
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
                        elif tag['Key'] == 'CreatedAt':  # Added for compatibility with ASG creation script
                            created_time = tag['Value']
                        elif tag['Key'] == 'CreatedBy':  # Added for compatibility with ASG creation script
                            creator = tag['Value']
                    
                    # Get launch template info
                    launch_template_id = None
                    launch_template_name = None
                    
                    if 'LaunchTemplate' in asg:
                        launch_template_id = asg['LaunchTemplate'].get('LaunchTemplateId')
                        launch_template_name = asg['LaunchTemplate'].get('LaunchTemplateName')
                    
                    # Format instance count
                    instance_count = len(asg.get('Instances', []))
                    
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
                        'account_name': account_name,
                        'asg_obj': asg  # Store full ASG object for later use
                    }
                    
                    asgs.append(asg_info)
            
            self.log_operation('INFO', f"📦 Found {len(asgs)} ASGs in {region} ({account_name})")
            print(f"   📦 Found {len(asgs)} ASGs in {region} ({account_name})")
            
            return asgs
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting ASGs in {region} ({account_name}): {e}")
            print(f"   ❌ Error scanning {region} ({account_name}): {e}")
            return []

    def delete_asg(self, asg_info):
        """Delete an Auto Scaling Group without threading"""
        try:
            asg_name = asg_info['asg_name']
            region = asg_info['region']
            account_name = asg_info['account_name']
        
            self.log_operation('INFO', f"🗑️  Deleting ASG {asg_name} in {region} ({account_name})")
            print(f"🗑️  Deleting ASG {asg_name} in {region} ({account_name})...")
        
            # Get account credentials
            account_data = self.config_data['accounts'][account_name]
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
        
            # Create ASG client
            asg_client = self.create_asg_client(access_key, secret_key, region)
        
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
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'instance_count': asg_info['instance_count'],
                'launch_template_id': asg_info['launch_template_id'],
                'launch_template_name': asg_info['launch_template_name']
            })
        
            return True
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete ASG {asg_name}: {e}")
            print(f"   ❌ Failed to delete ASG {asg_name}: {e}")
            
            # Update cleanup results
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'asg',
                'resource_id': asg_name,
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            
            return False

    def discover_asgs_for_account_region(self, account_name, account_data, region):
        """Discover ASGs in a specific account and region"""
        try:
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            account_id = account_data.get('account_id', 'Unknown')
            
            self.log_operation('INFO', f"🔍 Discovering ASGs in {account_name} ({account_id}) - {region}")
            
            # Create ASG client
            asg_client = self.create_asg_client(access_key, secret_key, region)
            
            # Get all ASGs
            asgs = self.get_all_asgs_in_region(asg_client, region, account_name)
            
            # Add region summary to results
            region_summary = {
                'account_name': account_name,
                'account_id': account_id,
                'region': region,
                'asgs_found': len(asgs)
            }
            
            self.cleanup_results['regions_processed'].append(region_summary)
            
            # Add account to processed accounts if not already there
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({
                    'account_name': account_name,
                    'account_id': account_id
                })
            
            return asgs
            
        except Exception as e:
            self.log_operation('ERROR', f"Error discovering ASGs in {account_name} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return []

    def discover_all_asgs(self, selected_accounts):
        """Discover all ASGs across selected accounts and regions - without threading"""
        try:
            regions = self.user_regions
            
            all_asgs = []
            
            print(f"\n🔍 Discovering ASGs across {len(selected_accounts)} accounts in {len(regions)} regions...")
            self.log_operation('INFO', f"Starting ASG discovery across {len(selected_accounts)} accounts and {len(regions)} regions")
            
            # Process each account and region sequentially
            for account_name, account_data in selected_accounts.items():
                print(f"\n⚙️  Processing account: {account_name}")
                for region in regions:
                    try:
                        print(f"   🌍 Scanning region: {region}")
                        asgs = self.discover_asgs_for_account_region(account_name, account_data, region)
                        if asgs:
                            all_asgs.extend(asgs)
                    except Exception as e:
                        self.log_operation('ERROR', f"Error processing {account_name} ({region}): {e}")
                        print(f"   ❌ Error processing {account_name} ({region}): {e}")
            
            # Sort ASGs by account and region for better display
            all_asgs.sort(key=lambda x: (x['account_name'], x['region'], x['asg_name']))
            
            self.log_operation('INFO', f"📊 Discovery complete: Found {len(all_asgs)} ASGs across all accounts")
            print(f"\n📊 Discovery complete: Found {len(all_asgs)} ASGs across selected accounts")
            
            return all_asgs
            
        except Exception as e:
            self.log_operation('ERROR', f"Error in ASG discovery: {e}")
            print(f"❌ Error in ASG discovery: {e}")
            return []

    def parse_selection(self, selection: str, max_count: int) -> List[int]:
        """Parse user selection string into list of indices"""
        selected_indices = set()
        
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_count:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_count})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                # Handle single number
                try:
                    num = int(part)
                    if num < 1 or num > max_count:
                        raise ValueError(f"Selection {num} is out of bounds (1-{max_count})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid selection: {part}")
        
        return sorted(list(selected_indices))

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_dir = "aws/ec2/asg/reports"
            os.makedirs(report_dir, exist_ok=True)
            report_filename = f"{report_dir}/ultra_asg_cleanup_report_{self.execution_timestamp}.json"
            
            # Calculate statistics
            total_asgs_deleted = len(self.cleanup_results['deleted_asgs'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_asgs'])
            
            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for asg in self.cleanup_results['deleted_asgs']:
                account = asg['account_name']
                region = asg['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = 0
                deletions_by_account[account] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = 0
                deletions_by_region[region] += 1
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_ASG_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_file": self.config_file,
                    "log_file": self.log_filename,
                    "accounts_in_config": list(self.config_data['accounts'].keys()),
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(self.cleanup_results['accounts_processed']),
                    "total_regions_processed": len(self.cleanup_results['regions_processed']),
                    "total_asgs_deleted": total_asgs_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_asgs": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results['accounts_processed'],
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
        """Main execution method - sequential (without threading)"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA ASG CLEANUP SESSION 🚨")
        
            print("🧹" * 30)
            print("💥 ULTRA AUTO SCALING GROUP CLEANUP 💥")
            print("🧹" * 30)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📋 Log File: {self.log_filename}")
            
            # STEP 1: Display available accounts and select accounts to process
            accounts = self.config_data['accounts']
            
            print(f"\n🏦 AVAILABLE AWS ACCOUNTS:")
            print("=" * 80)
            
            account_list = []
            
            for i, (account_name, account_data) in enumerate(accounts.items(), 1):
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                
                account_list.append({
                    'name': account_name,
                    'account_id': account_id,
                    'email': email,
                    'data': account_data
                })
                
                print(f"  {i}. {account_name}: {account_id} ({email})")
            
            # Selection prompt
            print("\nAccount Selection Options:")
            print("  • Single accounts: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-2,4")
            print("  • All accounts: 'all' or press Enter")
            print("  • Cancel: 'cancel' or 'quit'")
            
            selection = input("\n🔢 Select accounts to process: ").strip().lower()
            
            if selection in ['cancel', 'quit']:
                self.log_operation('INFO', "ASG cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Process account selection
            selected_accounts = {}
            if not selection or selection == 'all':
                selected_accounts = accounts
                self.log_operation('INFO', f"All accounts selected: {len(accounts)}")
                print(f"✅ Selected all {len(accounts)} accounts")
            else:
                try:
                    # Parse selection
                    parts = []
                    for part in selection.split(','):
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            if start < 1 or end > len(account_list):
                                raise ValueError(f"Range {part} out of bounds (1-{len(account_list)})")
                            parts.extend(range(start, end + 1))
                        else:
                            num = int(part)
                            if num < 1 or num > len(account_list):
                                raise ValueError(f"Selection {part} out of bounds (1-{len(account_list)})")
                            parts.append(num)
                    
                    # Get selected account data
                    for idx in parts:
                        account = account_list[idx-1]
                        selected_accounts[account['name']] = account['data']
                    
                    if not selected_accounts:
                        raise ValueError("No valid accounts selected")
                    
                    self.log_operation('INFO', f"Selected accounts: {list(selected_accounts.keys())}")
                    print(f"✅ Selected {len(selected_accounts)} accounts: {', '.join(selected_accounts.keys())}")
                    
                except ValueError as e:
                    self.log_operation('ERROR', f"Invalid account selection: {e}")
                    print(f"❌ Invalid selection: {e}")
                    return
        
            # STEP 2: Discover all ASGs across selected accounts and regions
            all_asgs = self.discover_all_asgs(selected_accounts)
            self.all_asgs = all_asgs
        
            if not all_asgs:
                print("\n❌ No Auto Scaling Groups found. Nothing to clean up.")
                return
        
            # STEP 3: Display all ASGs for selection
            print("\n" + "="*80)
            print("📋 ALL AUTO SCALING GROUPS ACROSS ACCOUNTS")
            print("="*80)
        
            # Display ASGs with more informative headers
            print(f"{'#':<4} {'ASG Name':<40} {'Size':<15} {'Instances':<10} {'Account':<15} {'Region'}")
            print("-" * 100)
        
            for i, asg in enumerate(all_asgs, 1):
                asg_name = asg['asg_name']
                min_size = asg['min_size']
                max_size = asg['max_size']
                desired = asg['desired_capacity']
                instances = asg['instance_count']
                account_name = asg['account_name']
                region = asg['region']
            
                size_info = f"{min_size}/{desired}/{max_size}"
                print(f"{i:<4} {asg_name:<40} {size_info:<15} {instances:<10} {account_name:<15} {region}")
        
            # STEP 4: Prompt user for ASG selection
            print("\nASG Selection Options:")
            print("  • Single ASGs: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-3,5,7-9")
            print("  • All ASGs: 'all' or press Enter")
            print("  • Cancel: 'cancel' or 'quit'")
        
            selection = input("\n🔢 Select ASGs to delete: ").strip().lower()
        
            if selection in ['cancel', 'quit']:
                self.log_operation('INFO', "ASG cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # STEP 5: Parse ASG selection
            selected_asgs = []
        
            if not selection or selection == 'all':
                selected_asgs = all_asgs.copy()
                self.log_operation('INFO', f"All ASGs selected: {len(all_asgs)}")
                print(f"✅ Selected all {len(all_asgs)} Auto Scaling Groups")
            else:
                try:
                    indices = self.parse_selection(selection, len(all_asgs))
                    selected_asgs = [all_asgs[i-1] for i in indices]
                    self.log_operation('INFO', f"Selected {len(selected_asgs)} ASGs")
                    print(f"✅ Selected {len(selected_asgs)} Auto Scaling Groups")
                except ValueError as e:
                    self.log_operation('ERROR', f"Invalid selection: {e}")
                    print(f"❌ Invalid selection: {e}")
                    return
        
            # STEP 6: Confirm deletion
            print("\n⚠️  WARNING: This will delete the selected Auto Scaling Groups")
            print(f"    and terminate any EC2 instances within them. ({len(selected_asgs)} total)")
            print(f"    This action CANNOT be undone!")
        
            confirm = input("\nType 'yes' to confirm deletion: ").strip().lower()
            self.log_operation('INFO', f"Deletion confirmation: '{confirm}'")
        
            if confirm != 'yes':
                self.log_operation('INFO', "ASG cleanup cancelled at confirmation")
                print("❌ Cleanup cancelled")
                return
        
            # STEP 7: Delete selected ASGs - sequentially (no threading)
            print(f"\n🗑️  Deleting {len(selected_asgs)} Auto Scaling Groups sequentially...")
        
            start_time = time.time()
            successful = 0
            failed = 0
        
            # Process each ASG sequentially
            for i, asg in enumerate(selected_asgs, 1):
                asg_name = asg['asg_name']
                account_name = asg['account_name']
                region = asg['region']
                
                print(f"\n[{i}/{len(selected_asgs)}] Processing ASG: {asg_name} in {account_name} ({region})")
                
                try:
                    result = self.delete_asg(asg)
                    if result:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    self.log_operation('ERROR', f"Error deleting ASG {asg_name}: {e}")
                    print(f"❌ Error deleting ASG {asg_name}: {e}")
        
            end_time = time.time()
            total_time = int(end_time - start_time)
        
            # STEP 8: Display results
            print("\n" + "="*80)
            print("🧹 AUTO SCALING GROUP CLEANUP RESULTS")
            print("="*80)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"✅ Successfully deleted: {successful}")
            print(f"❌ Failed to delete: {failed}")
        
            # Display results by account
            print("\n📊 Results by Account:")
        
            # Group deletions by account
            account_summary = {}
            for asg in self.cleanup_results['deleted_asgs']:
                account = asg['account_name']
                if account not in account_summary:
                    account_summary[account] = {'asgs': 0, 'regions': set()}
                account_summary[account]['asgs'] += 1
                account_summary[account]['regions'].add(asg['region'])
        
            for account, summary in account_summary.items():
                regions_list = ', '.join(sorted(summary['regions']))
                print(f"   • {account}:")
                print(f"     - ASGs deleted: {summary['asgs']}")
                print(f"     - Regions: {regions_list}")
        
            # Save cleanup report
            report_file = self.save_cleanup_report()
        
            if report_file:
                print(f"\n📄 Cleanup report saved to: {report_file}")
        
            print(f"📋 Detailed log saved to: {self.log_filename}")
        
            print("\n🧹 ASG CLEANUP COMPLETE! 🧹")
        
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraASGCleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()