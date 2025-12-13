from text_symbols import Symbols
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

class IAMLogFileCleanupManager:
    def __init__(self, config_file='aws_accounts_config.json', creds_base_dir='aws/iam', 
                 file_pattern='iam_users_credentials'):
        self.config_file = config_file
        self.creds_base_dir = creds_base_dir
        self.file_pattern = file_pattern  # Pattern to filter IAM credential files
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
        
        # Initialize storage for IAM data
        self.creds_by_file = {}  # Map filename to credentials data
        self.creds_by_age = {}   # Group credentials by age in days
        self.users_list = []     # List of all users found
        self.groups_list = []    # List of all groups found
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'files_processed': [],
            'users_found': [],
            'groups_found': [],
            'users_deleted': [],
            'groups_deleted': [],
            'failed_deletions': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/iam/logs"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/iam/logs directory
            self.log_filename = f"{log_dir}/iam_log_cleanup_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            
            # Create logger
            self.logger = logging.getLogger('iam_log_cleanup')
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
            self.logger.info(f"{Symbols.CLEANUP} IAM LOG FILE CLEANUP SESSION STARTED (Pattern: {self.file_pattern})")
            self.logger.info("=" * 100)
            self.logger.info(f"Execution Time: {self.current_time_str}")
            self.logger.info(f"Executed By: {self.current_user}")
            self.logger.info(f"Config File: {self.config_file}")
            self.logger.info(f"Credentials Base Directory: {self.creds_base_dir}")
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
            
            self.log_operation('INFO', f"{Symbols.OK} AWS accounts configuration loaded from: {self.config_file}")
            
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
            
            self.log_operation('INFO', f"{Symbols.STATS} Valid accounts loaded: {len(valid_accounts)}")
            
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
        """Extract date from IAM log filename"""
        # Pattern: iam_users_credentials_YYYYMMDD_HHMMSS.json
        pattern = r'{}(?:_(\d{{8}})_(\d{{6}}))\.json'.format(self.file_pattern)
        match = re.search(pattern, filename)
        if match:
            date_str = match.group(1)
            time_str = match.group(2)
            try:
                return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            except:
                pass
        
        # If unable to extract date from filename, use file modified time as fallback
        return None

    def find_iam_credential_files(self):
        """Find and parse all IAM credential files in the directory"""
        self.log_operation('INFO', f"{Symbols.SCAN} Scanning for IAM credential files matching '{self.file_pattern}' in {self.creds_base_dir}")
        
        if not os.path.exists(self.creds_base_dir):
            # Try to create the directory
            try:
                os.makedirs(self.creds_base_dir, exist_ok=True)
                self.log_operation('INFO', f"Created directory: {self.creds_base_dir}")
            except Exception as e:
                self.log_operation('ERROR', f"Could not create IAM credentials directory: {e}")
            
            self.log_operation('WARNING', f"No IAM credential files found as directory was just created: {self.creds_base_dir}")
            return []
        
        cred_files = []
        total_files = 0
        valid_files = 0
        
        # Walk through the directory structure
        for root, dirs, files in os.walk(self.creds_base_dir):
            for filename in files:
                if self.file_pattern in filename and filename.endswith(".json"):
                    total_files += 1
                    file_path = os.path.join(root, filename)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            try:
                                cred_data = json.load(f)
                                valid_files += 1
                                
                                # Extract date from filename or get file modification time
                                file_date = self.extract_date_from_filename(filename)
                                if file_date is None:
                                    file_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                                
                                # Calculate file age in days
                                file_age_days = (self.current_time - file_date).days
                                
                                # Extract relevant info
                                cred_info = {
                                    'file_path': file_path,
                                    'file_name': filename,
                                    'file_date': file_date,
                                    'file_age_days': file_age_days,
                                    'created_date': cred_data.get('created_date'),
                                    'created_time': cred_data.get('created_time'),
                                    'created_by': cred_data.get('created_by', 'Unknown'),
                                    'total_users': cred_data.get('total_users', 0),
                                    'accounts': cred_data.get('accounts', {}),
                                    'raw_data': cred_data  # Store the complete data for reference
                                }
                                
                                # Add to list of credential files
                                cred_files.append(cred_info)
                                
                            except json.JSONDecodeError:
                                self.log_operation('WARNING', f"Invalid JSON in file: {file_path}")
                    except Exception as e:
                        self.log_operation('ERROR', f"Error processing file {file_path}: {e}")
        
        self.log_operation('INFO', f"{Symbols.STATS} Found {valid_files} valid IAM credential files out of {total_files} total files")
        
        # Sort credential files by date (newest first)
        cred_files.sort(key=lambda x: x['file_date'], reverse=True)
        
        return cred_files

    def group_credentials_by_age(self, cred_files):
        """Group IAM credential files by age in days"""
        creds_by_age = {}
        
        for cred_info in cred_files:
            age_days = cred_info['file_age_days']
            
            if age_days not in creds_by_age:
                creds_by_age[age_days] = []
            
            creds_by_age[age_days].append(cred_info)
        
        return creds_by_age

    def extract_users_from_credentials(self, cred_files):
        """Extract IAM users from credential files"""
        users_by_name = {}  # Group by user name and account
        
        for cred_info in cred_files:
            accounts_data = cred_info['accounts']
            file_date = cred_info['file_date']
            
            for account_name, account_data in accounts_data.items():
                account_id = account_data.get('account_id', 'Unknown')
                account_email = account_data.get('account_email', 'Unknown')
                
                for user in account_data.get('users', []):
                    username = user.get('username')
                    if not username:
                        continue
                    
                    # Create user key to avoid duplicates across accounts
                    user_key = f"{account_name}|{username}"
                    
                    # If this is the first time we've seen this user or it's newer than what we have
                    if user_key not in users_by_name or file_date > users_by_name[user_key]['file_date']:
                        # Add extra metadata for better display and processing
                        user_info = {
                            'username': username,
                            'account_name': account_name,
                            'account_id': account_id,
                            'account_email': account_email,
                            'access_key_id': user.get('access_key_id'),
                            'region': user.get('region', 'us-east-1'),
                            'file_date': file_date,
                            'file_age_days': cred_info['file_age_days'],
                            'file_path': cred_info['file_path'],
                            'real_user': user.get('real_user', {})
                        }
                        
                        users_by_name[user_key] = user_info
        
        # Convert dictionary to list of unique users
        unique_users = list(users_by_name.values())
        
        # Sort by account name and username for consistent display
        unique_users.sort(key=lambda x: (x['account_name'], x['username']))
        
        return unique_users

    def extract_groups_from_credentials(self, cred_files):
        """Extract IAM groups from credential files (if present)"""
        # In the provided sample, groups aren't explicitly included,
        # but we'll create a mechanism to handle them if they are added later
        groups_by_name = {}
        
        for cred_info in cred_files:
            accounts_data = cred_info['accounts']
            file_date = cred_info['file_date']
            
            for account_name, account_data in accounts_data.items():
                account_id = account_data.get('account_id', 'Unknown')
                
                # Check if 'groups' is in the data structure
                for group in account_data.get('groups', []):
                    group_name = group.get('group_name')
                    if not group_name:
                        continue
                    
                    # Create group key to avoid duplicates across accounts
                    group_key = f"{account_name}|{group_name}"
                    
                    # If this is the first time we've seen this group or it's newer than what we have
                    if group_key not in groups_by_name or file_date > groups_by_name[group_key]['file_date']:
                        group_info = {
                            'group_name': group_name,
                            'account_name': account_name,
                            'account_id': account_id,
                            'members': group.get('members', []),
                            'file_date': file_date,
                            'file_age_days': cred_info['file_age_days'],
                            'file_path': cred_info['file_path'],
                        }
                        
                        groups_by_name[group_key] = group_info
        
        # Convert dictionary to list of unique groups
        unique_groups = list(groups_by_name.values())
        
        # Sort by account name and group name for consistent display
        unique_groups.sort(key=lambda x: (x['account_name'], x['group_name']))
        
        return unique_groups

    def create_iam_client(self, account_name):
        """Create IAM client for given account"""
        try:
            account_data = self.aws_config['accounts'].get(account_name)
            if not account_data:
                self.log_operation('ERROR', f"Account {account_name} not found in configuration")
                return None
            
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            
            client = boto3.client(
                'iam',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            
            return client
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create IAM client for {account_name}: {e}")
            return None

    def delete_user_access_keys(self, iam_client, username):
        """Delete all access keys for a user"""
        try:
            # List access keys
            response = iam_client.list_access_keys(UserName=username)
            
            # Delete each access key
            for key in response.get('AccessKeyMetadata', []):
                key_id = key['AccessKeyId']
                self.log_operation('INFO', f"Deleting access key {key_id} for user {username}")
                iam_client.delete_access_key(
                    UserName=username,
                    AccessKeyId=key_id
                )
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting access keys for user {username}: {e}")
            return False

    def delete_login_profile(self, iam_client, username):
        """Delete user's login profile if it exists"""
        try:
            # Check if login profile exists
            try:
                iam_client.get_login_profile(UserName=username)
                # If it exists, delete it
                self.log_operation('INFO', f"Deleting login profile for user {username}")
                iam_client.delete_login_profile(UserName=username)
            except ClientError as e:
                # If profile doesn't exist, that's fine
                if 'NoSuchEntity' in str(e):
                    return True
                else:
                    raise
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting login profile for user {username}: {e}")
            return False

    def remove_user_from_groups(self, iam_client, username):
        """Remove user from all groups"""
        try:
            # List groups for user
            response = iam_client.list_groups_for_user(UserName=username)
            
            # Remove user from each group
            for group in response.get('Groups', []):
                group_name = group['GroupName']
                self.log_operation('INFO', f"Removing user {username} from group {group_name}")
                iam_client.remove_user_from_group(
                    UserName=username,
                    GroupName=group_name
                )
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error removing user {username} from groups: {e}")
            return False

    def detach_user_policies(self, iam_client, username):
        """Detach all managed policies from a user"""
        try:
            # List attached policies with their complete ARNs
            response = iam_client.list_attached_user_policies(UserName=username)
        
            # Detach each policy using its exact ARN from the response
            for policy in response.get('AttachedPolicies', []):
                policy_name = policy['PolicyName']
                policy_arn = policy['PolicyArn']
            
                self.log_operation('INFO', f"Detaching policy {policy_name} (ARN: {policy_arn}) from user {username}")
                try:
                    iam_client.detach_user_policy(
                        UserName=username,
                        PolicyArn=policy_arn
                    )
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to detach policy {policy_name} ({policy_arn}) from user {username}: {e}")
                    # Continue with other policies even if one fails
        
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error detaching policies from user {username}: {e}")
            return False

    def delete_user_inline_policies(self, iam_client, username):
        """Delete all inline policies for a user"""
        try:
            # List inline policies
            response = iam_client.list_user_policies(UserName=username)
            
            # Delete each inline policy
            for policy_name in response.get('PolicyNames', []):
                self.log_operation('INFO', f"Deleting inline policy {policy_name} for user {username}")
                iam_client.delete_user_policy(
                    UserName=username,
                    PolicyName=policy_name
                )
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting inline policies for user {username}: {e}")
            return False

    def delete_iam_user(self, user_info):
        """Delete an IAM user with all its dependencies"""
        try:
            username = user_info['username']
            account_name = user_info['account_name']
            
            self.log_operation('INFO', f"{Symbols.DELETE} Deleting IAM user: {username} in {account_name}")
            
            # Create IAM client
            iam_client = self.create_iam_client(account_name)
            if not iam_client:
                self.log_operation('ERROR', f"Cannot delete user {username}: Failed to create IAM client")
                return False
            
            # Step 1: Delete all access keys
            self.delete_user_access_keys(iam_client, username)
            
            # Step 2: Delete login profile (console access)
            self.delete_login_profile(iam_client, username)
            
            # Step 3: Remove from all groups
            self.remove_user_from_groups(iam_client, username)
            
            # Step 4: Detach all managed policies
            self.detach_user_policies(iam_client, username)
            
            # Step 5: Delete all inline policies
            self.delete_user_inline_policies(iam_client, username)
            
            # Step 6: Delete MFA devices
            try:
                response = iam_client.list_mfa_devices(UserName=username)
                for mfa in response.get('MFADevices', []):
                    self.log_operation('INFO', f"Deactivating MFA device {mfa['SerialNumber']} for {username}")
                    iam_client.deactivate_mfa_device(
                        UserName=username,
                        SerialNumber=mfa['SerialNumber']
                    )
            except Exception as e:
                self.log_operation('WARNING', f"Error handling MFA devices for {username}: {e}")
            
            # Step 7: Finally delete the user
            self.log_operation('INFO', f"Finally deleting user {username}")
            iam_client.delete_user(UserName=username)
            
            self.log_operation('INFO', f"{Symbols.OK} Successfully deleted IAM user: {username} in {account_name}")
            
            # Record successful deletion
            self.cleanup_results['users_deleted'].append({
                'username': username,
                'account_name': account_name,
                'account_id': user_info['account_id'],
                'file_path': user_info['file_path'],
                'file_date': user_info['file_date'].strftime("%Y-%m-%d %H:%M:%S"),
                'file_age_days': user_info['file_age_days'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'real_user': user_info.get('real_user', {})
            })
            
            return True
            
        except ClientError as e:
            if 'NoSuchEntity' in str(e):
                self.log_operation('INFO', f"User {username} does not exist in account {account_name}")
                return True
            else:
                self.log_operation('ERROR', f"Error deleting IAM user {username} in {account_name}: {e}")
                
                # Record failed deletion
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'user',
                    'resource_name': username,
                    'account_name': account_name,
                    'file_path': user_info['file_path'],
                    'error': str(e)
                })
                
                return False
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error deleting IAM user {username} in {account_name}: {e}")
            
            # Record failed deletion
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'user',
                'resource_name': username,
                'account_name': account_name,
                'file_path': user_info['file_path'],
                'error': str(e)
            })
            
            return False

    def detach_group_policies(self, iam_client, group_name):
        """Detach all managed policies from a group"""
        try:
            # List attached policies
            response = iam_client.list_attached_group_policies(GroupName=group_name)
            
            # Detach each policy
            for policy in response.get('AttachedPolicies', []):
                policy_arn = policy['PolicyArn']
                self.log_operation('INFO', f"Detaching policy {policy['PolicyName']} from group {group_name}")
                iam_client.detach_group_policy(
                    GroupName=group_name,
                    PolicyArn=policy_arn
                )
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error detaching policies from group {group_name}: {e}")
            return False

    def delete_group_inline_policies(self, iam_client, group_name):
        """Delete all inline policies for a group"""
        try:
            # List inline policies
            response = iam_client.list_group_policies(GroupName=group_name)
            
            # Delete each inline policy
            for policy_name in response.get('PolicyNames', []):
                self.log_operation('INFO', f"Deleting inline policy {policy_name} for group {group_name}")
                iam_client.delete_group_policy(
                    GroupName=group_name,
                    PolicyName=policy_name
                )
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error deleting inline policies for group {group_name}: {e}")
            return False

    def remove_all_users_from_group(self, iam_client, group_name):
        """Remove all users from a group"""
        try:
            # Get users in the group
            response = iam_client.get_group(GroupName=group_name)
            
            # Remove each user from the group
            for user in response.get('Users', []):
                username = user['UserName']
                self.log_operation('INFO', f"Removing user {username} from group {group_name}")
                iam_client.remove_user_from_group(
                    UserName=username,
                    GroupName=group_name
                )
            
            return True
        except Exception as e:
            self.log_operation('ERROR', f"Error removing users from group {group_name}: {e}")
            return False

    def delete_iam_group(self, group_info):
        """Delete an IAM group with all its dependencies"""
        try:
            group_name = group_info['group_name']
            account_name = group_info['account_name']
            
            self.log_operation('INFO', f"{Symbols.DELETE} Deleting IAM group: {group_name} in {account_name}")
            
            # Create IAM client
            iam_client = self.create_iam_client(account_name)
            if not iam_client:
                self.log_operation('ERROR', f"Cannot delete group {group_name}: Failed to create IAM client")
                return False
            
            # Step 1: Remove all users from the group
            self.remove_all_users_from_group(iam_client, group_name)
            
            # Step 2: Detach all managed policies
            self.detach_group_policies(iam_client, group_name)
            
            # Step 3: Delete all inline policies
            self.delete_group_inline_policies(iam_client, group_name)
            
            # Step 4: Finally delete the group
            self.log_operation('INFO', f"Finally deleting group {group_name}")
            iam_client.delete_group(GroupName=group_name)
            
            self.log_operation('INFO', f"{Symbols.OK} Successfully deleted IAM group: {group_name} in {account_name}")
            
            # Record successful deletion
            self.cleanup_results['groups_deleted'].append({
                'group_name': group_name,
                'account_name': account_name,
                'account_id': group_info['account_id'],
                'file_path': group_info['file_path'],
                'file_date': group_info['file_date'].strftime("%Y-%m-%d %H:%M:%S"),
                'file_age_days': group_info['file_age_days'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except ClientError as e:
            if 'NoSuchEntity' in str(e):
                self.log_operation('INFO', f"Group {group_name} does not exist in account {account_name}")
                return True
            else:
                self.log_operation('ERROR', f"Error deleting IAM group {group_name} in {account_name}: {e}")
                
                # Record failed deletion
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'group',
                    'resource_name': group_name,
                    'account_name': account_name,
                    'file_path': group_info['file_path'],
                    'error': str(e)
                })
                
                return False
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error deleting IAM group {group_name} in {account_name}: {e}")
            
            # Record failed deletion
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'group',
                'resource_name': group_name,
                'account_name': account_name,
                'file_path': group_info['file_path'],
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
            report_dir = "aws/iam/reports"
            os.makedirs(report_dir, exist_ok=True)
            
            report_filename = f"{report_dir}/iam_cleanup_report_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "execution_date": self.current_time_str,
                    "executed_by": self.current_user,
                    "file_pattern": self.file_pattern,
                    "config_file": self.config_file,
                    "creds_base_dir": self.creds_base_dir,
                    "log_file": self.log_filename
                },
                "summary": {
                    "users_found": len(self.users_list),
                    "groups_found": len(self.groups_list),
                    "users_deleted": len(self.cleanup_results['users_deleted']),
                    "groups_deleted": len(self.cleanup_results['groups_deleted']),
                    "failed_deletions": len(self.cleanup_results['failed_deletions'])
                },
                "details": {
                    "users_deleted": self.cleanup_results['users_deleted'],
                    "groups_deleted": self.cleanup_results['groups_deleted'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"{Symbols.OK} Cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to save cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            print("\n" + "="*80)
            print(f"{Symbols.CLEANUP} IAM CREDENTIAL FILE CLEANUP UTILITY")
            print("="*80)
            print(f"Execution Date/Time: {self.current_time_str}")
            print(f"Searching for IAM credential files in: {self.creds_base_dir}")
            
            # Step 1: Find and parse all IAM credential files
            self.log_operation('INFO', f"Starting IAM credential file discovery for pattern: {self.file_pattern}")
            cred_files = self.find_iam_credential_files()
            
            if not cred_files:
                print(f"\n{Symbols.ERROR} No IAM credential files found matching pattern '{self.file_pattern}'. Nothing to clean up.")
                return
            
            # Step 2: Extract IAM users from credential files
            all_users = self.extract_users_from_credentials(cred_files)
            self.users_list = all_users
            
            # Step 3: Extract IAM groups from credential files (if present)
            all_groups = self.extract_groups_from_credentials(cred_files)
            self.groups_list = all_groups
            
            # Step 4: Group credential files by age
            self.creds_by_age = self.group_credentials_by_age(cred_files)
            age_groups = sorted(self.creds_by_age.keys())
            
            # Step 5: Display age groups and ask user which to process
            print(f"\n{Symbols.STATS} Found {len(all_users)} IAM users across {len(cred_files)} credential files")
            if all_groups:
                print(f"{Symbols.STATS} Found {len(all_groups)} IAM groups across {len(cred_files)} credential files")
            
            print(f"\nCredential files grouped by age:")
            for age in age_groups:
                count = len(self.creds_by_age[age])
                age_label = "today" if age == 0 else f"{age} day{'s' if age != 1 else ''} old"
                print(f"  • {age_label}: {count} file{'s' if count != 1 else ''}")
            
            # Process credential files by age
            max_age_to_process = -1
            users_to_delete = []
            groups_to_delete = []
            
            print("\n" + "="*80)
            print("[SCAN] CREDENTIAL FILE SELECTION BY AGE")
            print("="*80)
            
            for age in sorted(age_groups):
                # If max_age_to_process is set and we've gone beyond it, stop
                if max_age_to_process >= 0 and age > max_age_to_process:
                    self.log_operation('INFO', f"Stopping at age {age} days (limit was {max_age_to_process} days)")
                    break
                
                creds_in_age_group = self.creds_by_age[age]
                count = len(creds_in_age_group)
                
                age_label = "today" if age == 0 else f"{age} day{'s' if age != 1 else ''} old"
                print(f"\n{Symbols.DATE} Credential files that are {age_label} ({count} found):")
                
                # Show credential files in this age group
                print(f"{'#':<4} {'Filename':<40} {'Created By':<15} {'Total Users'}")
                print("-" * 80)
                
                for i, cred in enumerate(creds_in_age_group, 1):
                    filename = os.path.basename(cred['file_path'])
                    created_by = cred['created_by']
                    total_users = cred['total_users']
                    print(f"{i:<4} {filename:<40} {created_by:<15} {total_users}")
                
                # If age is at least 1 day, ask if user wants to process this age group
                if age >= 1:
                    process_age = input(f"\nProcess credentials that are {age_label}? (y/n/all): ").strip().lower()
                    
                    if process_age == 'n':
                        continue
                    elif process_age == 'all':
                        # Process all remaining age groups
                        max_age_to_process = 999
                    elif process_age != 'y':
                        print("Invalid choice. Enter 'y', 'n', or 'all'.")
                        continue
                
                # Extract users from credential files in this age group
                age_users = [user for user in all_users if user['file_age_days'] == age]
                age_groups = [group for group in all_groups if group['file_age_days'] == age]
                
                # Display users in this age group
                if age_users:
                    print("\n" + "="*80)
                    print(f"👤 IAM USERS FROM {age_label.upper()} CREDENTIALS")
                    print("="*80)
                    print(f"{'#':<4} {'Username':<30} {'Account':<15} {'Real Name':<25} {'Email'}")
                    print("-" * 90)
                    
                    for i, user in enumerate(age_users, 1):
                        username = user['username']
                        account_name = user['account_name']
                        real_name = user.get('real_user', {}).get('full_name', 'Unknown')
                        email = user.get('real_user', {}).get('email', 'Unknown')
                        print(f"{i:<4} {username:<30} {account_name:<15} {real_name:<25} {email}")
                    
                    # Ask which users to delete
                    print("\nUser Selection Options:")
                    print("  • Single users: 1,3,5")
                    print("  • Ranges: 1-3")
                    print("  • Mixed: 1-3,5,7-9")
                    print("  • All users: 'all' or press Enter")
                    print("  • Skip users: 'skip'")
                    
                    user_selection = input("\n[#] Select users to delete: ").strip().lower()
                    
                    if user_selection != 'skip':
                        selected_users = []
                        if not user_selection or user_selection == 'all':
                            selected_users = age_users
                            print(f"{Symbols.OK} Selected all {len(age_users)} users from this age group")
                        else:
                            try:
                                indices = self.parse_selection(user_selection, len(age_users))
                                selected_users = [age_users[i-1] for i in indices]
                                print(f"{Symbols.OK} Selected {len(selected_users)} users from this age group")
                            except ValueError as e:
                                print(f"{Symbols.ERROR} Invalid selection: {e}")
                                continue
                        
                        # Add selected users to the delete list
                        users_to_delete.extend(selected_users)
                
                # Display groups in this age group
                if age_groups:
                    print("\n" + "="*80)
                    print(f"👥 IAM GROUPS FROM {age_label.upper()} CREDENTIALS")
                    print("="*80)
                    print(f"{'#':<4} {'Group Name':<30} {'Account':<15} {'Members Count'}")
                    print("-" * 80)
                    
                    for i, group in enumerate(age_groups, 1):
                        group_name = group['group_name']
                        account_name = group['account_name']
                        members_count = len(group.get('members', []))
                        print(f"{i:<4} {group_name:<30} {account_name:<15} {members_count}")
                    
                    # Ask which groups to delete
                    print("\nGroup Selection Options:")
                    print("  • Single groups: 1,3,5")
                    print("  • Ranges: 1-3")
                    print("  • Mixed: 1-3,5,7-9")
                    print("  • All groups: 'all' or press Enter")
                    print("  • Skip groups: 'skip'")
                    
                    group_selection = input("\n[#] Select groups to delete: ").strip().lower()
                    
                    if group_selection != 'skip':
                        selected_groups = []
                        if not group_selection or group_selection == 'all':
                            selected_groups = age_groups
                            print(f"{Symbols.OK} Selected all {len(age_groups)} groups from this age group")
                        else:
                            try:
                                indices = self.parse_selection(group_selection, len(age_groups))
                                selected_groups = [age_groups[i-1] for i in indices]
                                print(f"{Symbols.OK} Selected {len(selected_groups)} groups from this age group")
                            except ValueError as e:
                                print(f"{Symbols.ERROR} Invalid selection: {e}")
                                continue
                        
                        # Add selected groups to the delete list
                        groups_to_delete.extend(selected_groups)
            
            # Final deletion step
            if not users_to_delete and not groups_to_delete:
                print("\n[ERROR] No IAM resources selected for deletion. Nothing to clean up.")
                return
            
            # Show summary and confirm deletion
            print("\n" + "="*80)
            print("[LIST] DELETION SUMMARY")
            print("="*80)
            print(f"You have selected:")
            print(f"  • {len(users_to_delete)} IAM users for deletion")
            print(f"  • {len(groups_to_delete)} IAM groups for deletion")
            
            # Display selected users
            if users_to_delete:
                print("\nSelected users to delete:")
                print(f"{'#':<4} {'Username':<30} {'Account':<15} {'Real Name':<25}")
                print("-" * 80)
                
                for i, user in enumerate(users_to_delete, 1):
                    username = user['username']
                    account_name = user['account_name']
                    real_name = user.get('real_user', {}).get('full_name', 'Unknown')
                    print(f"{i:<4} {username:<30} {account_name:<15} {real_name:<25}")
            
            # Display selected groups
            if groups_to_delete:
                print("\nSelected groups to delete:")
                print(f"{'#':<4} {'Group Name':<30} {'Account':<15}")
                print("-" * 60)
                
                for i, group in enumerate(groups_to_delete, 1):
                    group_name = group['group_name']
                    account_name = group['account_name']
                    print(f"{i:<4} {group_name:<30} {account_name:<15}")
            
            # Final confirmation
            print("\n[WARN]  WARNING: This will delete the selected IAM users and groups!")
            print(f"    User access keys, policies, and group memberships will also be deleted.")
            print(f"    This action CANNOT be undone!")
            
            confirm = input("\nType 'yes' to confirm deletion: ").strip().lower()
            
            if confirm != 'yes':
                print(f"{Symbols.ERROR} Deletion cancelled.")
                return
            
            # Execute deletion
            print(f"\n{Symbols.DELETE}  Deleting IAM resources...")
            
            start_time = time.time()
            
            # Delete groups first
            if groups_to_delete:
                print(f"\n{Symbols.DELETE} Deleting {len(groups_to_delete)} IAM groups...")
                
                successful_groups = 0
                failed_groups = 0
                
                for group in groups_to_delete:
                    try:
                        if self.delete_iam_group(group):
                            successful_groups += 1
                            print(f"{Symbols.OK} Deleted group: {group['group_name']} in account {group['account_name']}")
                        else:
                            failed_groups += 1
                            print(f"{Symbols.ERROR} Failed to delete group: {group['group_name']} in account {group['account_name']}")
                    except Exception as e:
                        self.log_operation('ERROR', f"Error deleting group {group['group_name']}: {e}")
                        failed_groups += 1
                        print(f"{Symbols.ERROR} Error deleting group {group['group_name']}: {e}")
            
            # Then delete users
            if users_to_delete:
                print(f"\n{Symbols.DELETE} Deleting {len(users_to_delete)} IAM users...")
                
                successful_users = 0
                failed_users = 0
                
                for user in users_to_delete:
                    try:
                        if self.delete_iam_user(user):
                            successful_users += 1
                            print(f"{Symbols.OK} Deleted user: {user['username']} in account {user['account_name']}")
                        else:
                            failed_users += 1
                            print(f"{Symbols.ERROR} Failed to delete user: {user['username']} in account {user['account_name']}")
                    except Exception as e:
                        self.log_operation('ERROR', f"Error deleting user {user['username']}: {e}")
                        failed_users += 1
                        print(f"{Symbols.ERROR} Error deleting user {user['username']}: {e}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # Display results
            print("\n" + "="*80)
            print("[OK] CLEANUP COMPLETE")
            print("="*80)
            print(f"{Symbols.TIMER}  Total execution time: {total_time} seconds")
            print(f"{Symbols.OK} Successfully deleted: {len(self.cleanup_results['users_deleted'])} users")
            print(f"{Symbols.OK} Successfully deleted: {len(self.cleanup_results['groups_deleted'])} groups")
            print(f"{Symbols.ERROR} Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            # Save report
            report_file = self.save_cleanup_report()
            
            if report_file:
                print(f"\n[FILE] Cleanup report saved to: {report_file}")
            
            print(f"{Symbols.LIST} Log file: {self.log_filename}")
            
        except KeyboardInterrupt:
            print("\n\n[ERROR] Cleanup interrupted by user")
        except Exception as e:
            self.log_operation('ERROR', f"Error in IAM cleanup: {e}")
            traceback.print_exc()
            print(f"\n{Symbols.ERROR} Error: {e}")

def main():
    """Main entry point"""
    print("\n[CLEANUP] IAM CREDENTIAL FILE CLEANUP UTILITY [CLEANUP]")
    print("This utility finds IAM users and groups from credential files and deletes them from AWS")
    
    # Default paths and pattern
    default_config = "aws_accounts_config.json"
    default_creds_dir = "aws/iam"
    default_pattern = "iam_users_credentials"
    
    # Get configuration file
    config_file = input(f"AWS config file path (default: {default_config}): ").strip()
    if not config_file:
        config_file = default_config
    
    # Get credentials base directory
    creds_dir = input(f"IAM credentials directory path (default: {default_creds_dir}): ").strip()
    if not creds_dir:
        creds_dir = default_creds_dir
    
    # Get file pattern
    pattern = input(f"Credential file pattern (default: {default_pattern}): ").strip()
    if not pattern:
        pattern = default_pattern
    
    # Create and run the cleanup manager
    try:
        cleanup_manager = IAMLogFileCleanupManager(
            config_file=config_file, 
            creds_base_dir=creds_dir,
            file_pattern=pattern
        )
        cleanup_manager.run()
    except Exception as e:
        print(f"\n{Symbols.ERROR} Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()