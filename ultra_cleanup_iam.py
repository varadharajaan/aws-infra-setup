#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError
from typing import List, Dict, Any, Set, Optional

class UltraIAMCleanupManager:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now()
        self.current_time_str = self.current_time.strftime("%Y-%m-%d %H:%M:%S")
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
            'users_deleted': [],
            'groups_deleted': [],
            'policies_detached': [],
            'access_keys_deleted': [],
            'failed_operations': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/iam/logs"
            os.makedirs(log_dir, exist_ok=True)
            
            self.log_filename = f"{log_dir}/ultra_iam_cleanup_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.logger = logging.getLogger('ultra_iam_cleanup')
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
            self.logger.info("🚨 ULTRA IAM CLEANUP SESSION STARTED 🚨")
            self.logger.info("=" * 100)
            self.logger.info(f"Execution Time: {self.current_time_str}")
            self.logger.info(f"Executed By: {self.current_user}")
            self.logger.info(f"Config File: {self.config_file}")
            self.logger.info(f"Log File: {self.log_filename}")
            self.logger.info("=" * 100)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.logger = None

    def log_operation(self, level, message):
        """Simple logging operation (no thread-safety needed)"""
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
            
        except FileNotFoundError as e:
            self.log_operation('ERROR', f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation('ERROR', f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation('ERROR', f"Error loading configuration: {e}")
            sys.exit(1)

    def create_iam_client(self, access_key, secret_key):
        """Create IAM client using account credentials"""
        try:
            iam_client = boto3.client(
                'iam',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            
            # Test the connection
            iam_client.get_account_summary()
            return iam_client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create IAM client: {e}")
            raise

    def get_all_iam_users(self, iam_client, account_name):
        """Get all IAM users in an account"""
        try:
            users = []
            
            self.log_operation('INFO', f"🔍 Scanning for IAM users in {account_name}")
            
            paginator = iam_client.get_paginator('list_users')
            
            for page in paginator.paginate():
                for user in page['Users']:
                    username = user['UserName']
                    user_id = user['UserId']
                    created_date = user['CreateDate']
                    
                    # Get user's groups
                    try:
                        groups_response = iam_client.list_groups_for_user(UserName=username)
                        groups = [group['GroupName'] for group in groups_response['Groups']]
                    except Exception:
                        groups = []
                    
                    # Get user's access keys
                    try:
                        keys_response = iam_client.list_access_keys(UserName=username)
                        access_keys = [key['AccessKeyId'] for key in keys_response['AccessKeyMetadata']]
                    except Exception:
                        access_keys = []
                    
                    # Get user's attached policies
                    try:
                        policies_response = iam_client.list_attached_user_policies(UserName=username)
                        attached_policies = [policy['PolicyName'] for policy in policies_response['AttachedPolicies']]
                    except Exception:
                        attached_policies = []
                    
                    # Get inline policies
                    try:
                        inline_policies_response = iam_client.list_user_policies(UserName=username)
                        inline_policies = inline_policies_response['PolicyNames']
                    except Exception:
                        inline_policies = []
                    
                    user_info = {
                        'username': username,
                        'user_id': user_id,
                        'arn': user['Arn'],
                        'created_date': created_date,
                        'account_name': account_name,
                        'groups': groups,
                        'access_keys': access_keys,
                        'attached_policies': attached_policies,
                        'inline_policies': inline_policies
                    }
                    
                    users.append(user_info)
            
            self.log_operation('INFO', f"👤 Found {len(users)} IAM users in {account_name}")
            
            return users
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting IAM users in {account_name}: {e}")
            return []

    def get_all_iam_groups(self, iam_client, account_name):
        """Get all IAM groups in an account"""
        try:
            groups = []
            
            self.log_operation('INFO', f"🔍 Scanning for IAM groups in {account_name}")
            
            paginator = iam_client.get_paginator('list_groups')
            
            for page in paginator.paginate():
                for group in page['Groups']:
                    group_name = group['GroupName']
                    group_id = group['GroupId']
                    created_date = group['CreateDate']
                    
                    # Get group's attached policies
                    try:
                        policies_response = iam_client.list_attached_group_policies(GroupName=group_name)
                        attached_policies = [policy['PolicyName'] for policy in policies_response['AttachedPolicies']]
                    except Exception:
                        attached_policies = []
                    
                    # Get inline policies
                    try:
                        inline_policies_response = iam_client.list_group_policies(GroupName=group_name)
                        inline_policies = inline_policies_response['PolicyNames']
                    except Exception:
                        inline_policies = []
                    
                    # Get users in group
                    try:
                        users_response = iam_client.get_group(GroupName=group_name)
                        users_in_group = [user['UserName'] for user in users_response['Users']]
                    except Exception:
                        users_in_group = []
                    
                    group_info = {
                        'group_name': group_name,
                        'group_id': group_id,
                        'arn': group['Arn'],
                        'created_date': created_date,
                        'account_name': account_name,
                        'attached_policies': attached_policies,
                        'inline_policies': inline_policies,
                        'users': users_in_group
                    }
                    
                    groups.append(group_info)
            
            self.log_operation('INFO', f"👥 Found {len(groups)} IAM groups in {account_name}")
            
            return groups
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting IAM groups in {account_name}: {e}")
            return []

    def delete_iam_group(self, iam_client, group_info, account_name):
        """Delete an IAM group (first removing all dependencies) - no threading"""
        try:
            group_name = group_info['group_name']
            self.log_operation('INFO', f"🗑️ Deleting IAM group: {group_name} in {account_name}")
        
            # Step 1: Remove all users from the group
            already_deleted_users = [user['username'] for user in self.cleanup_results['users_deleted'] if user['account_name'] == account_name]

            for username in group_info['users']:
                try:
                    # Skip if user was already deleted
                    if username in already_deleted_users:
                        self.log_operation('INFO', f"Skipping removal of already deleted user {username} from group {group_name}")
                        continue

                    self.log_operation('INFO', f"Removing user {username} from group {group_name}")
                    iam_client.remove_user_from_group(
                        UserName=username,
                        GroupName=group_name
                    )
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to remove user {username} from group {group_name}: {e}")
        
            # Step 2: Detach managed policies from the group
            try:
                # Get the complete list of attached policies with full ARNs
                attached_policies = iam_client.list_attached_group_policies(GroupName=group_name)
            
                # Iterate through policies and detach each one
                for policy in attached_policies.get('AttachedPolicies', []):
                    policy_name = policy['PolicyName']
                    policy_arn = policy['PolicyArn']
                
                    try:
                        self.log_operation('INFO', f"Detaching policy: {policy_name} (ARN: {policy_arn}) from group {group_name}")
                        iam_client.detach_group_policy(
                            GroupName=group_name,
                            PolicyArn=policy_arn
                        )
                        
                        self.cleanup_results['policies_detached'].append({
                            'policy_name': policy_name,
                            'policy_arn': policy_arn,
                            'group_name': group_name,
                            'type': 'group',
                            'account_name': account_name
                        })
                    except Exception as e:
                        self.log_operation('WARNING', f"Failed to detach policy {policy_name} from group {group_name}: {e}")
            except Exception as e:
                self.log_operation('ERROR', f"Error listing or detaching policies for group {group_name}: {e}")
        
            # Step 3: Delete inline policies
            try:
                inline_policies = iam_client.list_group_policies(GroupName=group_name).get('PolicyNames', [])
                for policy_name in inline_policies:
                    try:
                        self.log_operation('INFO', f"Deleting inline policy: {policy_name} from group {group_name}")
                        iam_client.delete_group_policy(
                            GroupName=group_name,
                            PolicyName=policy_name
                        )
                    except Exception as e:
                        self.log_operation('WARNING', f"Failed to delete inline policy {policy_name} for group {group_name}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error listing inline policies for group {group_name}: {e}")
        
            # Step 4: Add a short delay to ensure AWS has processed all detachments
            time.sleep(1)
        
            # Step 5: Delete the group
            try:
                self.log_operation('INFO', f"Deleting IAM group: {group_name}")
                iam_client.delete_group(GroupName=group_name)
                
                self.cleanup_results['groups_deleted'].append({
                    'group_name': group_name,
                    'group_id': group_info['group_id'],
                    'account_name': account_name,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
                self.log_operation('INFO', f"✅ Successfully deleted IAM group: {group_name}")
                return True
            except Exception as e:
                self.log_operation('ERROR', f"Failed to delete group {group_name}, attempting force delete: {e}")
                return self.force_delete_iam_group(iam_client, group_info, account_name)
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete IAM group {group_name}: {e}")
            
            self.cleanup_results['failed_operations'].append({
                'operation_type': 'delete_group',
                'resource_name': group_name,
                'account_name': account_name,
                'error': str(e)
            })
            
            # Try force delete as a last resort
            return self.force_delete_iam_group(iam_client, group_info, account_name)

    def process_account(self, account_name, account_data):
        """Process a single account - list IAM resources"""
        try:
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            account_id = account_data['account_id']
            
            self.log_operation('INFO', f"🔍 Starting IAM cleanup for {account_name} ({account_id})")
            
            # Create IAM client
            iam_client = self.create_iam_client(access_key, secret_key)
            
            # Get all users and groups
            users = self.get_all_iam_users(iam_client, account_name)
            groups = self.get_all_iam_groups(iam_client, account_name)
            
            # Add to account summary
            self.cleanup_results['accounts_processed'].append({
                'account_name': account_name,
                'account_id': account_id,
                'users_found': len(users),
                'groups_found': len(groups)
            })
            
            # Return the resources for display and selection
            return {
                'iam_client': iam_client,
                'users': users,
                'groups': groups,
                'account_name': account_name,
                'account_id': account_id
            }
            
        except Exception as e:
            self.log_operation('ERROR', f"Error processing account {account_name}: {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'error': str(e)
            })
            return None

    def force_delete_iam_group(self, iam_client, group_info, account_name):
        """Attempt to force delete an IAM group using AWS CLI"""
        try:
            group_name = group_info['group_name']
            self.log_operation('INFO', f"🗑️ Force deleting IAM group: {group_name} in {account_name}")
        
            # Get account credentials for AWS CLI
            account_data = self.config_data['accounts'][account_name]
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
        
            # Try once more to remove dependencies
             # Track already deleted users
            already_deleted_users = [user['username'] for user in self.cleanup_results['users_deleted'] if user['account_name'] == account_name]
        
            # Remove all users from the group
            try:
                for username in group_info['users']:
                    try:
                        if username in already_deleted_users:
                            self.log_operation('INFO', f"Skipping removal of already deleted user {username} from group {group_name}")
                            continue

                        iam_client.remove_user_from_group(
                            UserName=username,
                            GroupName=group_name
                        )
                    except Exception as e:
                        self.log_operation('WARNING', f"Could not remove user {username} from group: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error removing users from group: {e}")
        
            # Try detaching policies
            try:
                policies = iam_client.list_attached_group_policies(GroupName=group_name).get('AttachedPolicies', [])
                for policy in policies:
                    try:
                        iam_client.detach_group_policy(
                            GroupName=group_name,
                            PolicyArn=policy['PolicyArn']
                        )
                    except Exception as e:
                        self.log_operation('WARNING', f"Could not detach policy {policy['PolicyName']}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error detaching policies: {e}")
        
            # Try deleting inline policies
            try:
                inline_policies = iam_client.list_group_policies(GroupName=group_name).get('PolicyNames', [])
                for policy_name in inline_policies:
                    try:
                        iam_client.delete_group_policy(
                            GroupName=group_name,
                            PolicyName=policy_name
                        )
                    except Exception as e:
                        self.log_operation('WARNING', f"Could not delete inline policy {policy_name}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error deleting inline policies: {e}")
        
            # Use subprocess to run AWS CLI
            import subprocess
            import os
        
            # Create environment with AWS credentials
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = 'us-east-1'  # Using default region for IAM
        
            # Try to delete the group using AWS CLI
            try:
                self.log_operation('INFO', f"Attempting to delete group using AWS CLI: {group_name}")
                process = subprocess.Popen(
                    ['aws', 'iam', 'delete-group', '--group-name', group_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )
                stdout, stderr = process.communicate(timeout=15)
                
                if process.returncode == 0:
                    self.cleanup_results['groups_deleted'].append({
                        'group_name': group_name,
                        'group_id': group_info['group_id'],
                        'account_name': account_name,
                        'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'method': 'force_delete'
                    })
                    self.log_operation('INFO', f"✅ Successfully force deleted IAM group: {group_name}")
                    return True
                else:
                    error = stderr.decode('utf-8')
                    self.log_operation('ERROR', f"Failed to force delete group {group_name}: {error}")
                    self.cleanup_results['failed_operations'].append({
                        'operation_type': 'force_delete_group',
                        'resource_name': group_name,
                        'account_name': account_name,
                        'error': error
                    })
                    return False
            except subprocess.TimeoutExpired:
                self.log_operation('ERROR', f"AWS CLI command timed out for group {group_name}")
                return False
        
        except Exception as e:
            self.log_operation('ERROR', f"Force delete failed for IAM group {group_name}: {e}")
            self.cleanup_results['failed_operations'].append({
                'operation_type': 'force_delete_group',
                'resource_name': group_name,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def cleanup_account(self, account_resources, selected_users=None, selected_groups=None, exclude_root_account=True):
        """Clean up selected IAM resources in an account - sequential approach"""
        try:
            if not account_resources:
                return 0, 0  # No successful or failed operations
        
            iam_client = account_resources['iam_client']
            account_name = account_resources['account_name']
        
            success_count = 0
            failed_count = 0
        
            # Process users first - sequentially
            if selected_users:
                self.log_operation('INFO', f"Processing {len(selected_users)} users in account {account_name}")
                for user_info in selected_users:
                    # Skip root account user if flag is set
                    if exclude_root_account and 'root' in user_info['username'].lower():
                        self.log_operation('WARNING', f"Skipping root account user: {user_info['username']}")
                        continue
                    
                    # Delete user
                    if self.delete_iam_user(iam_client, user_info, account_name):
                        success_count += 1
                        self.log_operation('INFO', f"✅ Successfully deleted user '{user_info['username']}' in account {account_name}")
                    else:
                        failed_count += 1
                        self.log_operation('ERROR', f"❌ Failed to delete user '{user_info['username']}' in account {account_name}")
            
            # Process groups second - sequentially
            if selected_groups:
                self.log_operation('INFO', f"Processing {len(selected_groups)} groups in account {account_name}")
                for group_info in selected_groups:
                    # Delete group
                    if self.delete_iam_group(iam_client, group_info, account_name):
                        success_count += 1
                        self.log_operation('INFO', f"✅ Successfully deleted group '{group_info['group_name']}' in account {account_name}")
                    else:
                        failed_count += 1
                        self.log_operation('ERROR', f"❌ Failed to delete group '{group_info['group_name']}' in account {account_name}")
        
            return success_count, failed_count
        
        except Exception as e:
            self.log_operation('ERROR', f"Error in account cleanup for {account_resources['account_name']}: {e}")
            return 0, 0

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
            report_dir = "aws/iam/reports"
            os.makedirs(report_dir, exist_ok=True)
        
            report_filename = f"{report_dir}/ultra_iam_cleanup_report_{self.execution_timestamp}.json"
        
            # Calculate statistics
            total_users_deleted = len(self.cleanup_results['users_deleted'])
            total_groups_deleted = len(self.cleanup_results['groups_deleted'])
            total_failed = len(self.cleanup_results['failed_operations'])
        
            # Group deletions by account
            deletions_by_account = {}
        
            for user in self.cleanup_results['users_deleted']:
                account = user['account_name']
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'users': 0, 'groups': 0}
                deletions_by_account[account]['users'] += 1
        
            for group in self.cleanup_results['groups_deleted']:
                account = group['account_name']
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'users': 0, 'groups': 0}
                deletions_by_account[account]['groups'] += 1
        
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_IAM_CLEANUP",
                    "cleanup_date": self.current_time_str.split()[0],
                    "cleanup_time": self.current_time_str.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_file": self.config_file,
                    "log_file": self.log_filename
                },
                "summary": {
                    "total_accounts_processed": len(self.cleanup_results['accounts_processed']),
                    "total_users_deleted": total_users_deleted,
                    "total_groups_deleted": total_groups_deleted,
                    "total_failed_operations": total_failed,
                    "total_access_keys_deleted": len(self.cleanup_results['access_keys_deleted']),
                    "total_policies_detached": len(self.cleanup_results['policies_detached']),
                    "deletions_by_account": deletions_by_account
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results['accounts_processed'],
                    "users_deleted": self.cleanup_results['users_deleted'],
                    "groups_deleted": self.cleanup_results['groups_deleted'],
                    "policies_detached": self.cleanup_results['policies_detached'],
                    "access_keys_deleted": self.cleanup_results['access_keys_deleted'],
                    "failed_operations": self.cleanup_results['failed_operations'],
                    "errors": self.cleanup_results['errors']
                }
            }
        
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
        
            self.log_operation('INFO', f"✅ Ultra IAM cleanup report saved to: {report_filename}")
            return report_filename
        
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save ultra IAM cleanup report: {e}")
            return None

    def delete_iam_user(self, iam_client, user_info, account_name):
        """Delete an IAM user (first removing all dependencies)"""
        try:
            username = user_info['username']
            self.log_operation('INFO', f"🗑️ Deleting IAM user: {username} in {account_name}")
    
            # Step 1: Delete user's access keys
            for key_id in user_info['access_keys']:
                try:
                    self.log_operation('INFO', f"Deleting access key: {key_id} for user {username}")
                    iam_client.delete_access_key(
                        UserName=username,
                        AccessKeyId=key_id
                    )
                    
                    self.cleanup_results['access_keys_deleted'].append({
                        'access_key_id': key_id,
                        'username': username,
                        'account_name': account_name
                    })
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to delete access key {key_id} for user {username}: {e}")
    
            # Step 2: Detach user's managed policies
            try:
                # Get the complete list of attached policies with full ARNs
                attached_policies_response = iam_client.list_attached_user_policies(UserName=username)
        
                for policy in attached_policies_response.get('AttachedPolicies', []):
                    policy_name = policy['PolicyName']
                    policy_arn = policy['PolicyArn']
            
                    try:
                        self.log_operation('INFO', f"Detaching policy: {policy_name} (ARN: {policy_arn}) from user {username}")
                        iam_client.detach_user_policy(
                            UserName=username,
                            PolicyArn=policy_arn
                        )
                
                        self.cleanup_results['policies_detached'].append({
                            'policy_name': policy_name,
                            'policy_arn': policy_arn,
                            'username': username,
                            'type': 'user',
                            'account_name': account_name
                        })
                    except Exception as e:
                        self.log_operation('WARNING', f"Failed to detach policy {policy_name} from user {username}: {e}")
            except Exception as e:
                self.log_operation('ERROR', f"Error listing or detaching policies for user {username}: {e}")
    
            # Step 3: Delete user's inline policies
            for policy_name in user_info['inline_policies']:
                try:
                    self.log_operation('INFO', f"Deleting inline policy: {policy_name} from user {username}")
                    iam_client.delete_user_policy(
                        UserName=username,
                        PolicyName=policy_name
                    )
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to delete inline policy {policy_name} for user {username}: {e}")
    
            # Step 4: Remove user from groups
            for group_name in user_info['groups']:
                try:
                    self.log_operation('INFO', f"Removing user {username} from group {group_name}")
                    iam_client.remove_user_from_group(
                        UserName=username,
                        GroupName=group_name
                    )
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to remove user {username} from group {group_name}: {e}")
    
            # Step 5: Delete login profile (if exists)
            try:
                iam_client.get_login_profile(UserName=username)
                # If we get here, the login profile exists
                self.log_operation('INFO', f"Deleting login profile for user {username}")
                iam_client.delete_login_profile(UserName=username)
            except ClientError as e:
                if 'NoSuchEntity' not in str(e):
                    self.log_operation('WARNING', f"Error checking/deleting login profile for {username}: {e}")
    
            # Step 6: Delete MFA devices
            try:
                mfa_devices_response = iam_client.list_mfa_devices(UserName=username)
                for device in mfa_devices_response['MFADevices']:
                    self.log_operation('INFO', f"Deactivating MFA device: {device['SerialNumber']} for user {username}")
                    iam_client.deactivate_mfa_device(
                        UserName=username,
                        SerialNumber=device['SerialNumber']
                    )
            except Exception as e:
                self.log_operation('WARNING', f"Error handling MFA devices for user {username}: {e}")
    
            # Step 7: Delete service-specific credentials (CodeCommit, etc.)
            try:
                service_creds_response = iam_client.list_service_specific_credentials(UserName=username)
                for cred in service_creds_response.get('ServiceSpecificCredentials', []):
                    self.log_operation('INFO', f"Deleting service credential ID: {cred['ServiceSpecificCredentialId']} for user {username}")
                    iam_client.delete_service_specific_credential(
                        UserName=username,
                        ServiceSpecificCredentialId=cred['ServiceSpecificCredentialId']
                    )
            except Exception as e:
                self.log_operation('WARNING', f"Error handling service credentials for user {username}: {e}")
    
            # Step 8: Delete signing certificates
            try:
                cert_response = iam_client.list_signing_certificates(UserName=username)
                for cert in cert_response.get('Certificates', []):
                    self.log_operation('INFO', f"Deleting signing certificate ID: {cert['CertificateId']} for user {username}")
                    iam_client.delete_signing_certificate(
                        UserName=username,
                        CertificateId=cert['CertificateId']
                    )
            except Exception as e:
                self.log_operation('WARNING', f"Error handling signing certificates for user {username}: {e}")
    
            # Step 9: Finally delete the user
            self.log_operation('INFO', f"Deleting IAM user: {username}")
            iam_client.delete_user(UserName=username)
    
            self.cleanup_results['users_deleted'].append({
                'username': username,
                'user_id': user_info['user_id'],
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        
            self.log_operation('INFO', f"✅ Successfully deleted IAM user: {username}")
            return True
    
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete IAM user {username}: {e}")
        
            self.cleanup_results['failed_operations'].append({
                'operation_type': 'delete_user',
                'resource_name': username,
                'account_name': account_name,
                'error': str(e)
            })
        
            return False

    def run(self):
        """Main execution method - sequential approach"""
        try:
            print("\n" + "="*80)
            print("💥 ULTRA IAM CLEANUP UTILITY 💥")
            print("="*80)
            print(f"📅 Execution Date/Time: {self.current_time_str}")
            print(f"👤 Executed by: {self.current_user}")
        
            # Display available accounts first
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
                self.log_operation('INFO', "IAM cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Process selection
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
        
            # Get IAM resources from all selected accounts sequentially
            account_resources = {}
            all_users = []
            all_groups = []
        
            print("\n🔍 Scanning selected accounts for IAM resources...")
        
            # Process accounts sequentially
            for account_name, account_data in selected_accounts.items():
                try:
                    print(f"  Scanning account: {account_name}...")
                    resources = self.process_account(account_name, account_data)
                    if resources:
                        account_resources[account_name] = resources
                        all_users.extend(resources['users'])
                        all_groups.extend(resources['groups'])
                        print(f"  ✅ Found {len(resources['users'])} users, {len(resources['groups'])} groups in {account_name}")
                except Exception as e:
                    print(f"  ❌ Error scanning account {account_name}: {e}")
        
            if not account_resources:
                print("\n❌ No accounts were successfully processed. Nothing to clean up.")
                return
            
            # Display summary of all IAM resources found
            print("\n📊 IAM RESOURCES FOUND:")
            print("=" * 80)
            print(f"👤 Total Users: {len(all_users)}")
            print(f"👥 Total Groups: {len(all_groups)}")
        
            # Ask user what to clean up
            print("\nCleanup Options:")
            print("1. Delete Users")
            print("2. Delete Groups")
            print("3. Delete Both Users and Groups")
            print("4. Cancel Cleanup")
        
            cleanup_option = input("\nSelect cleanup option (1-4): ").strip()
        
            if cleanup_option == '4' or not cleanup_option:
                print("❌ Cleanup cancelled")
                return
            
            # Process cleanup option
            cleanup_users = cleanup_option in ['1', '3']
            cleanup_groups = cleanup_option in ['2', '3']
        
            users_to_delete = []
            groups_to_delete = []
        
            # Option to exclude root accounts
            #exclude_root = input("\nExclude root account users from deletion? (y/n, default: y): ").strip().lower()
            exclude_root = 'y'
            exclude_root = exclude_root != 'n'
        
            if exclude_root:
                print("✅ Root account users will be excluded from deletion")
            else:
                print("⚠️ WARNING: Root account users will be included in deletion")
        
            # USERS Selection
            if cleanup_users and all_users:
                print("\n" + "="*80)
                print("👤 IAM USERS SELECTION")
                print("="*80)
            
                # Show all users
                print(f"\n{'#':<4} {'Username':<30} {'Account':<15} {'ID':<24} {'Groups'}")
                print("-" * 90)
            
                for i, user in enumerate(all_users, 1):
                    username = user['username']
                    account_name = user['account_name']
                    user_id = user['user_id']
                    groups = ",".join(user['groups']) if user['groups'] else "None"
                
                    # Highlight root users
                    if 'root' in username.lower():
                        print(f"{i:<4} {username:<30} {account_name:<15} {user_id:<24} {groups} ⚠️ ROOT USER")
                    else:
                        print(f"{i:<4} {username:<30} {account_name:<15} {user_id:<24} {groups}")
            
                # Ask for user selection
                print("\nUser Selection Options:")
                print("  • Single users: 1,3,5")
                print("  • Ranges: 1-3")
                print("  • Mixed: 1-3,5,7-9")
                print("  • All users: 'all' or press Enter")
                print("  • Skip users: 'skip'")
            
                user_selection = input("\n🔢 Select users to delete: ").strip().lower()
            
                if user_selection != 'skip':
                    if not user_selection or user_selection == 'all':
                        users_to_delete = all_users
                        print(f"✅ Selected all {len(all_users)} IAM users")
                    else:
                        try:
                            indices = self.parse_selection(user_selection, len(all_users))
                            users_to_delete = [all_users[i-1] for i in indices]
                            print(f"✅ Selected {len(users_to_delete)} IAM users")
                        except ValueError as e:
                            print(f"❌ Invalid selection: {e}")
                            return
        
            # GROUPS Selection
            if cleanup_groups and all_groups:
                print("\n" + "="*80)
                print("👥 IAM GROUPS SELECTION")
                print("="*80)
            
                # Show all groups
                print(f"\n{'#':<4} {'Group Name':<30} {'Account':<15} {'ID':<24} {'Users Count'}")
                print("-" * 90)
            
                for i, group in enumerate(all_groups, 1):
                    group_name = group['group_name']
                    account_name = group['account_name']
                    group_id = group['group_id']
                    user_count = len(group['users'])
                
                    print(f"{i:<4} {group_name:<30} {account_name:<15} {group_id:<24} {user_count}")
            
                # Ask for group selection
                print("\nGroup Selection Options:")
                print("  • Single groups: 1,3,5")
                print("  • Ranges: 1-3")
                print("  • Mixed: 1-3,5,7-9")
                print("  • All groups: 'all' or press Enter")
                print("  • Skip groups: 'skip'")
            
                group_selection = input("\n🔢 Select groups to delete: ").strip().lower()
            
                if group_selection != 'skip':
                    if not group_selection or group_selection == 'all':
                        groups_to_delete = all_groups
                        print(f"✅ Selected all {len(all_groups)} IAM groups")
                    else:
                        try:
                            indices = self.parse_selection(group_selection, len(all_groups))
                            groups_to_delete = [all_groups[i-1] for i in indices]
                            print(f"✅ Selected {len(groups_to_delete)} IAM groups")
                        except ValueError as e:
                            print(f"❌ Invalid selection: {e}")
                            return
        
            # Final confirmation
            if not users_to_delete and not groups_to_delete:
                print("\n❌ No IAM resources selected for deletion. Nothing to clean up.")
                return
            
            print("\n" + "="*80)
            print("⚠️ FINAL CONFIRMATION")
            print("="*80)
        
            print(f"\nYou are about to delete:")
            print(f"  • {len(users_to_delete)} IAM users")
            print(f"  • {len(groups_to_delete)} IAM groups")
            print(f"\nThis action CANNOT be undone!")
        
            confirm = input("\nType 'yes' to confirm deletion: ").strip().lower()
        
            if confirm != 'yes':
                print("❌ Deletion cancelled.")
                return
        
            # Execute deletion
            print(f"\n🗑️ Executing IAM cleanup...")
        
            start_time = time.time()
        
            total_success = 0
            total_failed = 0
        
            # Organize users and groups by account for efficient processing
            users_by_account = {}
            groups_by_account = {}
        
            for user in users_to_delete:
                account = user['account_name']
                if account not in users_by_account:
                    users_by_account[account] = []
                users_by_account[account].append(user)
        
            for group in groups_to_delete:
                account = group['account_name']
                if account not in groups_by_account:
                    groups_by_account[account] = []
                groups_by_account[account].append(group)
        
            # Process each account sequentially
            for account_name, resources in account_resources.items():
                account_users = users_by_account.get(account_name, [])
                account_groups = groups_by_account.get(account_name, [])
            
                if account_users or account_groups:
                    print(f"\n🏦 Processing account: {account_name}")
                    print(f"  • Deleting {len(account_users)} users and {len(account_groups)} groups")
                
                    success, failed = self.cleanup_account(
                        resources,
                        account_users,
                        account_groups,
                        exclude_root_account=exclude_root
                    )
                
                    total_success += success
                    total_failed += failed
        
            end_time = time.time()
            total_time = int(end_time - start_time)
        
            # Display results
            print("\n" + "="*80)
            print("✅ IAM CLEANUP COMPLETE")
            print("="*80)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"👤 Users deleted: {len(self.cleanup_results['users_deleted'])}")
            print(f"👥 Groups deleted: {len(self.cleanup_results['groups_deleted'])}")
            print(f"🔑 Access keys deleted: {len(self.cleanup_results['access_keys_deleted'])}")
            print(f"📝 Policies detached: {len(self.cleanup_results['policies_detached'])}")
            print(f"❌ Failed operations: {len(self.cleanup_results['failed_operations'])}")
        
            # Show results by account
            print("\n📊 Results by Account:")
        
            # Organize by account
            account_summary = {}
            for account_data in self.cleanup_results['accounts_processed']:
                account_name = account_data['account_name']
                if account_name not in account_summary:
                    account_summary[account_name] = {
                        'users_found': account_data['users_found'],
                        'groups_found': account_data['groups_found'],
                        'users_deleted': 0,
                        'groups_deleted': 0
                    }
        
            for user in self.cleanup_results['users_deleted']:
                account_name = user['account_name']
                if account_name in account_summary:
                    account_summary[account_name]['users_deleted'] += 1
        
            for group in self.cleanup_results['groups_deleted']:
                account_name = group['account_name']
                if account_name in account_summary:
                    account_summary[account_name]['groups_deleted'] += 1
        
            for account_name, summary in account_summary.items():
                print(f"\n  • {account_name}:")
                print(f"    - Users: {summary['users_deleted']}/{summary['users_found']} deleted")
                print(f"    - Groups: {summary['groups_deleted']}/{summary['groups_found']} deleted")
        
            # Save cleanup report
            report_file = self.save_cleanup_report()
        
            if report_file:
                print(f"\n📄 Full cleanup report saved to: {report_file}")
        
            print(f"📋 Log file: {self.log_filename}")
        
        except KeyboardInterrupt:
            print("\n\n❌ Cleanup interrupted by user")
        except Exception as e:
            self.log_operation('ERROR', f"Error in IAM cleanup: {e}")
            import traceback
            traceback.print_exc()
            print(f"\n❌ Error: {e}")

def main():
    """Main entry point"""
    print("\n💥 ULTRA IAM CLEANUP UTILITY 💥")
    print("This utility allows you to delete IAM users and groups across multiple AWS accounts")
    
    # Default config
    default_config = "aws_accounts_config.json"
    
    # Get configuration file
    config_file = input(f"AWS config file path (default: {default_config}): ").strip()
    if not config_file:
        config_file = default_config
    
    # Create and run the cleanup manager
    try:
        cleanup_manager = UltraIAMCleanupManager(config_file=config_file)
        cleanup_manager.run()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()