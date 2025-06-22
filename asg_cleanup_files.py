#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
import threading
import re
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Set, Optional

class ASGLogFileCleanupManager:
    def __init__(self, config_file='aws_accounts_config.json', aws_base_dir='aws/ec2', target_pattern='asg-account02-mixed'):
        self.config_file = config_file
        self.aws_base_dir = aws_base_dir
        self.target_pattern = target_pattern  # Pattern to filter ASGs
        self.current_time = datetime.now()
        self.current_time_str = self.current_time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize lock for thread-safe logging
        self.log_lock = threading.Lock()
        
        # Initialize log file
        self.setup_detailed_logging()
        
        # Load AWS accounts configuration
        self.load_aws_accounts_config()
        
        # Initialize storage for ASG data
        self.asgs_by_file = {}  # Map filename to ASG data
        self.asgs_by_age = {}   # Group ASGs by age in days
        self.asgs_list = []     # List of all ASGs found
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'files_processed': [],
            'asgs_found': [],
            'asgs_deleted': [],
            'failed_deletions': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/ec2/asg"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/ec2/asg directory
            self.log_filename = f"{log_dir}/asg_log_cleanup_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger
            self.logger = logging.getLogger('asg_log_cleanup')
            self.logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.logger.handlers[:]:
                self.logger.removeHandler(handler)
            
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
            
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
            
            # Log initial information
            self.logger.info("=" * 100)
            self.logger.info(f"🧹 ASG LOG FILE CLEANUP SESSION STARTED (Pattern: {self.target_pattern})")
            self.logger.info("=" * 100)
            self.logger.info(f"Execution Time: {self.current_time_str}")
            self.logger.info(f"Executed By: {self.current_user}")
            self.logger.info(f"Config File: {self.config_file}")
            self.logger.info(f"AWS Base Directory: {self.aws_base_dir}")
            self.logger.info(f"Log File: {self.log_filename}")
            self.logger.info("=" * 100)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.logger = None

    def log_operation(self, level, message):
        """Thread-safe logging operation"""
        with self.log_lock:
            if self.logger:
                if level.upper() == 'INFO':
                    self.logger.info(message)
                elif level.upper() == 'WARNING':
                    self.logger.warning(message)
                elif level.upper() == 'ERROR':
                    self.logger.error(message)
                elif level.upper() == 'DEBUG':
                    self.logger.debug(message)
            else:
                print(f"[{level.upper()}] {message}")

    def load_aws_accounts_config(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.aws_config = json.load(f)
            
            self.log_operation('INFO', f"✅ AWS accounts configuration loaded from: {self.config_file}")
            
            # Validate accounts
            if 'accounts' not in self.aws_config:
                raise ValueError("No 'accounts' section found in configuration")
            
            # Filter out accounts without valid credentials
            valid_accounts = {}
            for account_name, account_data in self.aws_config['accounts'].items():
                if (account_data.get('access_key') and 
                    account_data.get('secret_key') and
                    not account_data.get('access_key').startswith('ADD_')):
                    valid_accounts[account_name] = account_data
                else:
                    self.log_operation('WARNING', f"Skipping account with invalid credentials: {account_name}")
            
            self.aws_config['accounts'] = valid_accounts
            
            self.log_operation('INFO', f"📊 Valid accounts loaded: {len(valid_accounts)}")
            
            # Map account IDs to account names for easier lookup
            self.account_id_to_name = {}
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id')
                if account_id:
                    self.account_id_to_name[account_id] = account_name
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load AWS accounts configuration: {e}")
            raise

    def extract_date_from_filename(self, filename):
        """Extract date from ASG log filename"""
        # Try different patterns
        # Pattern 1: asg_report_YYYYMMDD_HHMMSS.json
        report_pattern = r'asg_report_(\d{8})_(\d{6})\.json'
        match = re.search(report_pattern, filename)
        if match:
            date_str = match.group(1)
            time_str = match.group(2)
            try:
                return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            except:
                pass
        
        # Pattern 2: asg_NAME_YYYYMMDD_HHMMSS.json
        asg_pattern = r'asg_.*?_(\d{8})_(\d{6})\.json'
        match = re.search(asg_pattern, filename)
        if match:
            date_str = match.group(1)
            time_str = match.group(2)
            try:
                return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            except:
                pass
        
        # If unable to extract date from filename, use file modified time as fallback
        return None

    def find_asg_log_files(self):
        """Find and parse all ASG log files in the AWS directory with target pattern"""
        self.log_operation('INFO', f"🔍 Scanning for ASG log files matching '{self.target_pattern}' in {self.aws_base_dir}")
        
        if not os.path.exists(self.aws_base_dir):
            self.log_operation('ERROR', f"AWS base directory does not exist: {self.aws_base_dir}")
            return []
        
        asg_files = []
        total_files = 0
        valid_files = 0
        matching_pattern_files = 0
        
        # Walk through the AWS directory structure
        for root, dirs, files in os.walk(self.aws_base_dir):
            for filename in files:
                if filename.startswith("asg_") and filename.endswith(".json"):
                    total_files += 1
                    file_path = os.path.join(root, filename)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            try:
                                asg_data = json.load(f)
                                valid_files += 1
                                
                                # Extract ASG name from configuration
                                asg_name = None
                                if 'asg_configuration' in asg_data and 'name' in asg_data['asg_configuration']:
                                    asg_name = asg_data['asg_configuration']['name']
                                elif 'name' in asg_data:
                                    asg_name = asg_data['name']
                                else:
                                    # Try to extract from filename
                                    name_match = re.search(r'asg_(.*?)_\d{8}_\d{6}\.json', filename)
                                    if name_match:
                                        asg_name = name_match.group(1)
                                
                                # Skip if ASG name doesn't match the target pattern
                                if not asg_name or self.target_pattern not in asg_name:
                                    continue
                                
                                matching_pattern_files += 1
                                
                                # Extract date from filename or get file modification time
                                file_date = self.extract_date_from_filename(filename)
                                if file_date is None:
                                    file_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                                
                                # Calculate file age in days
                                file_age_days = (self.current_time - file_date).days
                                
                                # Extract relevant info
                                asg_info = {
                                    'file_path': file_path,
                                    'file_name': filename,
                                    'file_date': file_date,
                                    'file_age_days': file_age_days,
                                    'asg_name': asg_name
                                }
                                
                                # Get region info
                                if 'asg_configuration' in asg_data and 'region' in asg_data['asg_configuration']:
                                    asg_info['region'] = asg_data['asg_configuration']['region']
                                    asg_info['launch_template_id'] = asg_data['asg_configuration'].get('launch_template_id')
                                elif 'region' in asg_data:
                                    asg_info['region'] = asg_data['region']
                                    asg_info['launch_template_id'] = asg_data.get('launch_template_id')
                                
                                # Get account info
                                if 'account_info' in asg_data:
                                    account_data = asg_data['account_info']
                                    asg_info['account_name'] = account_data.get('account_name')
                                    asg_info['account_id'] = account_data.get('account_id')
                                    if not asg_info.get('region'):
                                        asg_info['region'] = account_data.get('region')

                                else:
                                    # Try to get account from directory structure
                                    path_parts = file_path.split(os.path.sep)
                                    for i, part in enumerate(path_parts):
                                        if part == 'ec2' and i + 1 < len(path_parts):
                                            asg_info['account_name'] = path_parts[i + 1]
                                            break

                                # Get additional metadata
                                asg_info['created_by'] = asg_data.get('created_by', 'Unknown')

                                # NEW: Get creation_date and creation_time from metadata, fallback to Unknown
                                if "metadata" in asg_data:
                                    asg_info['creation_date'] = asg_data["metadata"].get("creation_date", "Unknown")
                                    asg_info['creation_time'] = asg_data["metadata"].get("creation_time", "Unknown")
                                else:
                                    asg_info['creation_date'] = "Unknown"
                                    asg_info['creation_time'] = "Unknown"

                                # Store raw ASG data for reference
                                asg_info['raw_data'] = asg_data
                                
                                # Add to list of ASG files
                                asg_files.append(asg_info)
                                
                            except json.JSONDecodeError:
                                self.log_operation('WARNING', f"Invalid JSON in file: {file_path}")
                    except Exception as e:
                        self.log_operation('ERROR', f"Error processing file {file_path}: {e}")
        
        self.log_operation('INFO', f"📊 Found {matching_pattern_files} ASG files matching pattern '{self.target_pattern}' out of {valid_files} valid files")
        
        # Sort ASG files by date (newest first)
        asg_files.sort(key=lambda x: x['file_date'], reverse=True)
        
        return asg_files

    def group_asgs_by_age(self, asg_files):
        """Group ASGs by age in days"""
        asgs_by_age = {}
        
        for asg_info in asg_files:
            age_days = asg_info['file_age_days']
            
            if age_days not in asgs_by_age:
                asgs_by_age[age_days] = []
            
            asgs_by_age[age_days].append(asg_info)
        
        return asgs_by_age

    def extract_unique_asgs(self, asg_files):
        """Extract unique ASGs from log files (latest version of each)"""
        asgs_by_name = {}  # Group by ASG name
        
        for asg_info in asg_files:
            asg_name = asg_info['asg_name']
            
            # If this is the first time we've seen this ASG or it's newer than what we have
            if asg_name not in asgs_by_name or asg_info['file_date'] > asgs_by_name[asg_name]['file_date']:
                asgs_by_name[asg_name] = asg_info
        
        # Convert dictionary to list of unique ASGs
        unique_asgs = list(asgs_by_name.values())
        
        # Sort by account name and ASG name for consistent display
        unique_asgs.sort(key=lambda x: (x.get('account_name', ''), x['asg_name']))
        
        return unique_asgs

    def create_asg_client(self, account_name, region):
        """Create boto3 ASG client for given account and region"""
        try:
            account_data = self.aws_config['accounts'].get(account_name)
            if not account_data:
                self.log_operation('ERROR', f"Account {account_name} not found in configuration")
                return None
            
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            
            client = boto3.client(
                'autoscaling',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            return client
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create ASG client for {account_name} in {region}: {e}")
            return None

    def delete_asg(self, asg_info):
        """Delete an Auto Scaling Group"""
        try:
            asg_name = asg_info['asg_name']
            account_name = asg_info['account_name']
            region = asg_info['region']
            
            self.log_operation('INFO', f"🗑️ Deleting ASG: {asg_name} in {account_name} ({region})")
            
            # Verify we have the minimum required information
            if not all([asg_name, account_name, region]):
                missing = []
                if not asg_name: missing.append("ASG name")
                if not account_name: missing.append("account name")
                if not region: missing.append("region")
                
                self.log_operation('ERROR', f"Cannot delete ASG: Missing {', '.join(missing)}")
                return False
            
            # Create ASG client
            asg_client = self.create_asg_client(account_name, region)
            if not asg_client:
                return False
            
            # 1. Check if ASG exists
            try:
                response = asg_client.describe_auto_scaling_groups(
                    AutoScalingGroupNames=[asg_name],
                    MaxRecords=1
                )
                
                if not response['AutoScalingGroups']:
                    self.log_operation('INFO', f"ASG {asg_name} does not exist in {account_name} ({region})")
                    return False
            except ClientError as e:
                if 'ValidationError' in str(e) and 'not found' in str(e):
                    self.log_operation('INFO', f"ASG {asg_name} does not exist in {account_name} ({region})")
                    return False
                else:
                    raise
            
            # 2. Delete scheduled actions
            try:
                self.log_operation('INFO', f"Checking for scheduled actions on {asg_name}")
                actions_response = asg_client.describe_scheduled_actions(
                    AutoScalingGroupName=asg_name
                )
                
                for action in actions_response.get('ScheduledUpdateGroupActions', []):
                    action_name = action['ScheduledActionName']
                    self.log_operation('INFO', f"Deleting scheduled action: {action_name}")
                    asg_client.delete_scheduled_action(
                        AutoScalingGroupName=asg_name,
                        ScheduledActionName=action_name
                    )
            except Exception as e:
                self.log_operation('WARNING', f"Error handling scheduled actions: {e}")
            
            # 3. Delete scaling policies
            try:
                self.log_operation('INFO', f"Checking for scaling policies on {asg_name}")
                policies_response = asg_client.describe_policies(
                    AutoScalingGroupName=asg_name
                )
                
                for policy in policies_response.get('ScalingPolicies', []):
                    policy_name = policy['PolicyName']
                    self.log_operation('INFO', f"Deleting scaling policy: {policy_name}")
                    asg_client.delete_policy(
                        AutoScalingGroupName=asg_name,
                        PolicyName=policy_name
                    )
            except Exception as e:
                self.log_operation('WARNING', f"Error handling scaling policies: {e}")
            
            # 4. Delete the ASG with ForceDelete to terminate instances
            self.log_operation('INFO', f"Deleting Auto Scaling Group with Force option")
            asg_client.delete_auto_scaling_group(
                AutoScalingGroupName=asg_name,
                ForceDelete=True
            )
            
            self.log_operation('INFO', f"✅ Successfully deleted ASG: {asg_name}")
            
            # Record successful deletion
            self.cleanup_results['asgs_deleted'].append({
                'asg_name': asg_name,
                'account_name': account_name,
                'region': region,
                'file_path': asg_info['file_path'],
                'file_date': asg_info['file_date'].strftime("%Y-%m-%d %H:%M:%S"),
                'file_age_days': asg_info['file_age_days'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete ASG {asg_info['asg_name']}: {e}")
            
            # Record failed deletion
            self.cleanup_results['failed_deletions'].append({
                'asg_name': asg_info['asg_name'],
                'account_name': asg_info.get('account_name', 'Unknown'),
                'region': asg_info.get('region', 'Unknown'),
                'file_path': asg_info['file_path'],
                'error': str(e)
            })
            
            return False

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
        """Save cleanup results to JSON report"""
        try:
            report_filename = f"asg_cleanup_report_{self.target_pattern}_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "execution_date": self.current_time_str,
                    "executed_by": self.current_user,
                    "target_pattern": self.target_pattern,
                    "config_file": self.config_file,
                    "aws_base_dir": self.aws_base_dir,
                    "log_file": self.log_filename
                },
                "summary": {
                    "asgs_found": len(self.asgs_list),
                    "asgs_deleted": len(self.cleanup_results['asgs_deleted']),
                    "failed_deletions": len(self.cleanup_results['failed_deletions'])
                },
                "details": {
                    "deleted_asgs": self.cleanup_results['asgs_deleted'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"✅ Cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to save cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            print("\n" + "="*80)
            print(f"🧹 AUTO SCALING GROUP CLEANUP UTILITY - PATTERN: {self.target_pattern}")
            print("="*80)
            print(f"Execution Date/Time: {self.current_time_str}")
            print(f"Searching for ASG logs in: {self.aws_base_dir}")
            
            # Step 1: Find and parse all ASG log files matching the target pattern
            self.log_operation('INFO', f"Starting ASG log file discovery for pattern: {self.target_pattern}")
            asg_files = self.find_asg_log_files()
            
            if not asg_files:
                print(f"\n❌ No ASG log files found matching pattern '{self.target_pattern}'. Nothing to clean up.")
                return
            
            # Step 2: Extract unique ASGs (taking the latest version of each)
            unique_asgs = self.extract_unique_asgs(asg_files)
            self.asgs_list = unique_asgs
            
            # Step 3: Group ASGs by age
            self.asgs_by_age = self.group_asgs_by_age(asg_files)
            age_groups = sorted(self.asgs_by_age.keys())
            
            # Step 4: Display age groups and ask user which to process
            print(f"\n📊 Found {len(unique_asgs)} unique ASGs matching '{self.target_pattern}' across {len(asg_files)} log files")
            print(f"\nASGs grouped by age:")
            for age in age_groups:
                count = len(self.asgs_by_age[age])
                age_label = "today" if age == 0 else f"{age} day{'s' if age != 1 else ''} old"
                print(f"  • {age_label}: {count} ASG{'s' if count != 1 else ''}")
            
            # Process all ASGs together in a single list
            asgs_to_delete = []
            
            print("\n" + "="*80)
            print(f"🔍 ASG SELECTION - PATTERN: {self.target_pattern}")
            print("="*80)
            
            # List all ASGs together sorted by age (newest first)
            all_asgs = sorted(unique_asgs, key=lambda x: x['file_age_days'])
            
            print(f"\n📋 Available ASGs matching pattern '{self.target_pattern}':")
            print(f"{'#':<4} {'ASG Name':<40} {'Account':<15} {'Age':<8} {'Region':<12}")
            print("-" * 90)
            
            for i, asg in enumerate(all_asgs, 1):
                asg_name = asg['asg_name']
                account_name = asg.get('account_name', 'Unknown')
                region = asg.get('region', 'Unknown')
                age = asg['file_age_days']
                age_str = "Today" if age == 0 else f"{age} day{'s' if age != 1 else ''}"
                print(f"{i:<4} {asg_name:<40} {account_name:<15} {age_str:<8} {region:<12}")
            
            # Ask which ASGs to delete
            print("\nASG Selection Options:")
            print("  • Single ASGs: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-3,5,7-9")
            print("  • All ASGs: 'all' or press Enter")
            print("  • Cancel: 'cancel'")
            
            selection = input("\n🔢 Select ASGs to delete: ").strip().lower()
            
            if selection == 'cancel':
                print("❌ Operation cancelled.")
                return
            
            if not selection or selection == 'all':
                asgs_to_delete = all_asgs
                print(f"✅ Selected all {len(all_asgs)} ASGs")
            else:
                try:
                    indices = self.parse_selection(selection, len(all_asgs))
                    asgs_to_delete = [all_asgs[i-1] for i in indices]
                    print(f"✅ Selected {len(asgs_to_delete)} ASGs")
                except ValueError as e:
                    print(f"❌ Invalid selection: {e}")
                    return
            
            # Show summary and confirm deletion
            if not asgs_to_delete:
                print("\n❌ No ASGs selected for deletion. Nothing to clean up.")
                return
                
            print("\n" + "="*80)
            print(f"📋 SELECTED {len(asgs_to_delete)} ASGs FOR DELETION:")
            print("="*80)
            print(f"{'#':<4} {'ASG Name':<40} {'Account':<15} {'Age':<8} {'Region':<12}")
            print("-" * 90)
            
            for i, asg in enumerate(asgs_to_delete, 1):
                asg_name = asg['asg_name']
                account_name = asg.get('account_name', 'Unknown')
                region = asg.get('region', 'Unknown')
                age = asg['file_age_days']
                age_str = "Today" if age == 0 else f"{age} day{'s' if age != 1 else ''}"
                print(f"{i:<4} {asg_name:<40} {account_name:<15} {age_str:<8} {region:<12}")
            
            # Final confirmation
            print("\n⚠️  WARNING: This will delete the selected Auto Scaling Groups")
            print(f"    and terminate all EC2 instances within them.")
            print(f"    This action CANNOT be undone!")
            
            confirm = input("\nType 'yes' to confirm deletion: ").strip().lower()
            
            if confirm != 'yes':
                print("❌ Deletion cancelled.")
                return
            
            # Execute deletion
            print(f"\n🗑️  Deleting {len(asgs_to_delete)} Auto Scaling Groups...")
            
            start_time = time.time()
            
            successful = 0
            failed = 0
            
            for asg in asgs_to_delete:
                try:
                    if self.delete_asg(asg):
                        successful += 1
                        print(f"✅ Deleted ASG: {asg['asg_name']}")
                    else:
                        failed += 1
                        print(f"❌ Failed to delete ASG: {asg['asg_name']}")
                except Exception as e:
                    self.log_operation('ERROR', f"Error deleting ASG {asg['asg_name']}: {e}")
                    failed += 1
                    print(f"❌ Error deleting ASG {asg['asg_name']}: {e}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # Display results
            print("\n" + "="*80)
            print("✅ CLEANUP COMPLETE")
            print("="*80)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"✅ Successfully deleted: {successful} ASGs")
            print(f"❌ Failed to delete: {failed} ASGs")
            
            # Save report
            report_file = self.save_cleanup_report()
            
            if report_file:
                print(f"\n📄 Cleanup report saved to: {report_file}")
            
            print(f"📋 Log file: {self.log_filename}")
            
        except KeyboardInterrupt:
            print("\n\n❌ Cleanup interrupted by user")
        except Exception as e:
            self.log_operation('ERROR', f"Error in ASG cleanup: {e}")
            import traceback
            traceback.print_exc()
            print(f"\n❌ Error: {e}")

def main():
    """Main entry point"""
    print("\n🧹 ASG PATTERN-BASED CLEANUP UTILITY 🧹")
    print("This utility finds specific ASG patterns from log files and deletes them from AWS")
    
    # Default paths and pattern
    default_config = "aws_accounts_config.json"
    default_aws_dir = "aws/ec2"
    default_pattern = "asg-account"
    
    # Get configuration file
    config_file = input(f"AWS config file path (default: {default_config}): ").strip()
    if not config_file:
        config_file = default_config
    
    # Get AWS base directory
    aws_dir = input(f"AWS logs base directory path (default: {default_aws_dir}): ").strip()
    if not aws_dir:
        aws_dir = default_aws_dir
    
    # Get target pattern
    pattern = input(f"ASG name pattern to target (default: {default_pattern}): ").strip()
    if not pattern:
        pattern = default_pattern
        
    # Create and run the cleanup manager
    try:
        cleanup_manager = ASGLogFileCleanupManager(
            config_file=config_file, 
            aws_base_dir=aws_dir,
            target_pattern=pattern
        )
        cleanup_manager.run()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()