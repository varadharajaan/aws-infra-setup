#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from logger import setup_logger
from text_symbols import Symbols

class IAMUserCleanup:
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.logger = setup_logger("iam_user_cleanup", "user_cleanup")
        self.load_configuration()
        self.load_user_mapping()
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
    def load_configuration(self):
        """Load AWS account configurations from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.aws_accounts = config['accounts']
            self.user_settings = config['user_settings']
            
            self.logger.info(f"Configuration loaded from: {self.config_file}")
            self.logger.info(f"Found {len(self.aws_accounts)} AWS accounts")
            
        except FileNotFoundError as e:
            self.logger.error(f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)

    def load_user_mapping(self):
        """Load user mapping from JSON file"""
        try:
            if not os.path.exists(self.mapping_file):
                self.logger.warning(f"User mapping file '{self.mapping_file}' not found")
                self.user_mappings = {}
                return
            
            with open(self.mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            self.user_mappings = mapping_data['user_mappings']
            self.logger.info(f"User mapping loaded from: {self.mapping_file}")
            self.logger.info(f"Found mappings for {len(self.user_mappings)} users")
            
            # Analyze which accounts have users
            self.analyze_user_distribution()
            
        except Exception as e:
            self.logger.warning(f"Error loading user mapping: {e}")
            self.user_mappings = {}

    def analyze_user_distribution(self):
        """Analyze user distribution across accounts"""
        account_user_count = {}
        
        for username in self.user_mappings.keys():
            # Extract account name from username (e.g., account01_clouduser01 -> account01)
            account_name = '_'.join(username.split('_')[:-1])
            if account_name not in account_user_count:
                account_user_count[account_name] = 0
            account_user_count[account_name] += 1
        
        self.account_user_count = account_user_count
        self.logger.info(f"User distribution: {account_user_count}")

    def get_user_info(self, username):
        """Get real user information for a username"""
        if username in self.user_mappings:
            mapping = self.user_mappings[username]
            return f"{mapping['first_name']} {mapping['last_name']} ({mapping['email']})"
        else:
            return "Unknown User"

    def create_iam_client(self, account_name):
        """Create IAM client using specific account credentials"""
        if account_name not in self.aws_accounts:
            raise ValueError(f"Account {account_name} not found in configurations")
        
        account_config = self.aws_accounts[account_name]
        
        try:
            iam_client = boto3.client(
                'iam',
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name='us-east-1'
            )
            
            # Test the connection
            iam_client.get_user()
            self.logger.log_account_action(account_name, "CONNECT", "SUCCESS", 
                                         f"Account ID: {account_config['account_id']}")
            return iam_client, account_config
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                error_msg = f"Access denied: {e}"
                self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            else:
                error_msg = f"AWS Error: {e}"
                self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            raise
        except Exception as e:
            error_msg = f"Connection failed: {e}"
            self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            raise

    def get_users_for_account(self, account_name):
        """Get users for specific account from the user mapping file"""
        users_for_account = []
        
        for username in self.user_mappings.keys():
            # Extract account name from username (e.g., account01_clouduser01 -> account01)
            user_account = '_'.join(username.split('_')[:-1])
            if user_account == account_name:
                users_for_account.append(username)
        
        users_for_account.sort()  # Sort for consistent ordering
        return users_for_account

    def check_user_exists(self, iam_client, username):
        """Check if IAM user exists and return user details"""
        try:
            response = iam_client.get_user(UserName=username)
            self.logger.log_user_action(username, "CHECK_EXISTS", "EXISTS")
            return True, response['User']
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                self.logger.log_user_action(username, "CHECK_EXISTS", "NOT_EXISTS")
                return False, None
            else:
                self.logger.error(f"Error checking user existence: {e}")
                raise e

    def cleanup_user_step_by_step(self, iam_client, username, dry_run=False):
        """Clean up user following the exact sequence: login profile → access keys → policies → user"""
        actions_taken = []
        action_prefix = "[DRY RUN] " if dry_run else ""
        
        try:
            # STEP 1: DELETE LOGIN PROFILE FIRST
            self.logger.debug(f"{action_prefix}Step 1: Deleting login profile for {username}")
            try:
                iam_client.get_login_profile(UserName=username)
                if not dry_run:
                    iam_client.delete_login_profile(UserName=username)
                actions_taken.append("[OK] Deleted login profile")
                self.logger.log_resource_cleanup(username, "LOGIN_PROFILE", "console_access", "DELETED")
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    self.logger.debug(f"No login profile found for {username}")
                else:
                    self.logger.error(f"Error deleting login profile for {username}: {e}")
            
            # STEP 2: PROCESS ACCESS KEYS (deactivate then delete)
            self.logger.debug(f"{action_prefix}Step 2: Processing access keys for {username}")
            try:
                access_keys_response = iam_client.list_access_keys(UserName=username)
                access_keys = access_keys_response['AccessKeyMetadata']
                
                if access_keys:
                    for access_key in access_keys:
                        access_key_id = access_key['AccessKeyId']
                        
                        # Deactivate first if active
                        if access_key['Status'] == 'Active':
                            try:
                                if not dry_run:
                                    iam_client.update_access_key(
                                        UserName=username,
                                        AccessKeyId=access_key_id,
                                        Status='Inactive'
                                    )
                                self.logger.log_resource_cleanup(username, "ACCESS_KEY", access_key_id, "DEACTIVATED")
                                actions_taken.append(f"{Symbols.OK} Deactivated access key: {access_key_id}")
                            except ClientError as e:
                                self.logger.error(f"Warning deactivating access key {access_key_id}: {e}")
                        
                        # Then delete
                        try:
                            if not dry_run:
                                iam_client.delete_access_key(
                                    UserName=username,
                                    AccessKeyId=access_key_id
                                )
                            self.logger.log_resource_cleanup(username, "ACCESS_KEY", access_key_id, "DELETED")
                            actions_taken.append(f"{Symbols.OK} Deleted access key: {access_key_id}")
                        except ClientError as e:
                            self.logger.error(f"Error deleting access key {access_key_id}: {e}")
                else:
                    self.logger.debug(f"No access keys found for {username}")
                    
            except ClientError as e:
                self.logger.error(f"Error listing access keys for {username}: {e}")
            
            # STEP 3: DETACH MANAGED POLICIES
            self.logger.debug(f"{action_prefix}Step 3: Detaching managed policies for {username}")
            try:
                policies_response = iam_client.list_attached_user_policies(UserName=username)
                attached_policies = policies_response['AttachedPolicies']
                
                if attached_policies:
                    for policy in attached_policies:
                        try:
                            if not dry_run:
                                iam_client.detach_user_policy(
                                    UserName=username,
                                    PolicyArn=policy['PolicyArn']
                                )
                            self.logger.log_resource_cleanup(username, "ATTACHED_POLICY", policy['PolicyName'], "DETACHED")
                            actions_taken.append(f"{Symbols.OK} Detached policy: {policy['PolicyName']}")
                        except ClientError as e:
                            self.logger.error(f"Error detaching policy {policy['PolicyName']}: {e}")
                else:
                    self.logger.debug(f"No attached policies found for {username}")
                    
            except ClientError as e:
                self.logger.error(f"Error listing attached policies for {username}: {e}")
            
            # STEP 4: DELETE INLINE POLICIES
            self.logger.debug(f"{action_prefix}Step 4: Deleting inline policies for {username}")
            try:
                inline_policies_response = iam_client.list_user_policies(UserName=username)
                inline_policies = inline_policies_response['PolicyNames']
                
                if inline_policies:
                    for policy_name in inline_policies:
                        try:
                            if not dry_run:
                                iam_client.delete_user_policy(
                                    UserName=username,
                                    PolicyName=policy_name
                                )
                            self.logger.log_resource_cleanup(username, "INLINE_POLICY", policy_name, "DELETED")
                            actions_taken.append(f"{Symbols.OK} Deleted inline policy: {policy_name}")
                        except ClientError as e:
                            self.logger.error(f"Error deleting inline policy {policy_name}: {e}")
                else:
                    self.logger.debug(f"No inline policies found for {username}")
                    
            except ClientError as e:
                self.logger.error(f"Error listing inline policies for {username}: {e}")
            
            # STEP 5: REMOVE FROM GROUPS
            self.logger.debug(f"{action_prefix}Step 5: Removing from groups for {username}")
            try:
                groups_response = iam_client.list_groups_for_user(UserName=username)
                groups = groups_response['Groups']
                
                if groups:
                    for group in groups:
                        try:
                            if not dry_run:
                                iam_client.remove_user_from_group(
                                    GroupName=group['GroupName'],
                                    UserName=username
                                )
                            self.logger.log_resource_cleanup(username, "GROUP_MEMBERSHIP", group['GroupName'], "REMOVED")
                            actions_taken.append(f"{Symbols.OK} Removed from group: {group['GroupName']}")
                        except ClientError as e:
                            self.logger.error(f"Error removing from group {group['GroupName']}: {e}")
                else:
                    self.logger.debug(f"No group memberships found for {username}")
                    
            except ClientError as e:
                if e.response['Error']['Code'] != 'NoSuchEntity':
                    self.logger.error(f"Error listing groups for {username}: {e}")
                else:
                    self.logger.debug(f"No group memberships found for {username}")
            
            # STEP 6: DELETE MFA DEVICES (if any)
            self.logger.debug(f"{action_prefix}Step 6: Removing MFA devices for {username}")
            try:
                mfa_response = iam_client.list_mfa_devices(UserName=username)
                mfa_devices = mfa_response['MFADevices']
                
                if mfa_devices:
                    for mfa_device in mfa_devices:
                        try:
                            if not dry_run:
                                iam_client.deactivate_mfa_device(
                                    UserName=username,
                                    SerialNumber=mfa_device['SerialNumber']
                                )
                                # Delete virtual MFA if applicable
                                if 'arn:aws:iam::' in mfa_device['SerialNumber']:
                                    iam_client.delete_virtual_mfa_device(
                                        SerialNumber=mfa_device['SerialNumber']
                                    )
                            self.logger.log_resource_cleanup(username, "MFA_DEVICE", mfa_device['SerialNumber'], "REMOVED")
                            actions_taken.append(f"{Symbols.OK} Removed MFA device: {mfa_device['SerialNumber']}")
                        except ClientError as e:
                            self.logger.error(f"Error removing MFA device: {e}")
                else:
                    self.logger.debug(f"No MFA devices found for {username}")
                    
            except ClientError as e:
                self.logger.error(f"Error listing MFA devices for {username}: {e}")
            
            # STEP 7: DELETE SIGNING CERTIFICATES (if any)
            self.logger.debug(f"{action_prefix}Step 7: Removing signing certificates for {username}")
            try:
                certs_response = iam_client.list_signing_certificates(UserName=username)
                certificates = certs_response['Certificates']
                
                if certificates:
                    for cert in certificates:
                        try:
                            if not dry_run:
                                iam_client.delete_signing_certificate(
                                    UserName=username,
                                    CertificateId=cert['CertificateId']
                                )
                            self.logger.log_resource_cleanup(username, "SIGNING_CERT", cert['CertificateId'], "DELETED")
                            actions_taken.append(f"{Symbols.OK} Deleted certificate: {cert['CertificateId']}")
                        except ClientError as e:
                            self.logger.error(f"Error deleting certificate: {e}")
                else:
                    self.logger.debug(f"No signing certificates found for {username}")
                    
            except ClientError as e:
                self.logger.error(f"Error listing signing certificates for {username}: {e}")
            
            # STEP 8: DELETE SSH PUBLIC KEYS (if any)
            self.logger.debug(f"{action_prefix}Step 8: Removing SSH public keys for {username}")
            try:
                ssh_response = iam_client.list_ssh_public_keys(UserName=username)
                ssh_keys = ssh_response['SSHPublicKeys']
                
                if ssh_keys:
                    for ssh_key in ssh_keys:
                        try:
                            if not dry_run:
                                iam_client.delete_ssh_public_key(
                                    UserName=username,
                                    SSHPublicKeyId=ssh_key['SSHPublicKeyId']
                                )
                            self.logger.log_resource_cleanup(username, "SSH_KEY", ssh_key['SSHPublicKeyId'], "DELETED")
                            actions_taken.append(f"{Symbols.OK} Deleted SSH key: {ssh_key['SSHPublicKeyId']}")
                        except ClientError as e:
                            self.logger.error(f"Error deleting SSH key: {e}")
                else:
                    self.logger.debug(f"No SSH public keys found for {username}")
                    
            except ClientError as e:
                self.logger.error(f"Error listing SSH public keys for {username}: {e}")
                
        except Exception as e:
            self.logger.error(f"Error in cleanup process for {username}: {e}")
            raise
        
        return actions_taken

    def delete_user(self, iam_client, username, dry_run=False):
        """Delete the IAM user after all resources are cleaned up"""
        try:
            self.logger.debug(f"Step 9: Deleting user {username}")
            if not dry_run:
                iam_client.delete_user(UserName=username)
                self.logger.log_user_action(username, "DELETE_USER", "SUCCESS")
            else:
                self.logger.log_user_action(username, "DELETE_USER", "DRY_RUN")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            self.logger.log_user_action(username, "DELETE_USER", "FAILED", f"{error_code}: {error_message}")
            
            if error_code == 'DeleteConflict':
                self.logger.warning(f"There are still resources attached to {username}")
                
                # Quick check for remaining resources
                remaining_resources = []
                try:
                    # Check for remaining access keys
                    ak_response = iam_client.list_access_keys(UserName=username)
                    if ak_response['AccessKeyMetadata']:
                        remaining_resources.append(f"{len(ak_response['AccessKeyMetadata'])} access keys")
                    
                    # Check for remaining policies
                    pol_response = iam_client.list_attached_user_policies(UserName=username)
                    if pol_response['AttachedPolicies']:
                        remaining_resources.append(f"{len(pol_response['AttachedPolicies'])} attached policies")
                    
                    # Check for remaining inline policies
                    inline_response = iam_client.list_user_policies(UserName=username)
                    if inline_response['PolicyNames']:
                        remaining_resources.append(f"{len(inline_response['PolicyNames'])} inline policies")
                    
                    # Check for login profile
                    try:
                        iam_client.get_login_profile(UserName=username)
                        remaining_resources.append("login profile")
                    except ClientError:
                        pass
                    
                    if remaining_resources:
                        self.logger.warning(f"Remaining resources for {username}: {', '.join(remaining_resources)}")
                    else:
                        self.logger.warning(f"No obvious remaining resources found for {username}")
                        
                except Exception as check_e:
                    self.logger.error(f"Could not check remaining resources for {username}: {check_e}")
            
            return False
                
        except Exception as e:
            self.logger.error(f"Unexpected error deleting user {username}: {e}")
            return False

    def cleanup_users_in_account(self, account_name, dry_run=False):
        """Cleanup users in a specific AWS account"""
        action_prefix = "🧪 [DRY RUN]" if dry_run else "[DELETE]  [DELETING]"
        self.logger.info(f"{action_prefix} Processing account: {account_name.upper()}")
        
        # Get users for this account from mapping file
        users_for_account = self.get_users_for_account(account_name)
        
        if not users_for_account:
            self.logger.info(f"No users found in mapping for account: {account_name}")
            return [], [], []
            
        self.logger.info(f"Found {len(users_for_account)} users to cleanup in {account_name}: {users_for_account}")
        
        try:
            # Initialize IAM client for this account
            iam_client, account_config = self.create_iam_client(account_name)
            
        except Exception as e:
            self.logger.error(f"Failed to connect to {account_name}: {e}")
            return [], [], []
        
        deleted_users = []
        not_found_users = []
        failed_users = []
        
        # Process each user from the mapping file
        for username in users_for_account:
            try:
                exists, user_details = self.check_user_exists(iam_client, username)
                
                if not exists:
                    self.logger.log_user_action(username, "SKIP", "NOT_EXISTS")
                    not_found_users.append(username)
                    continue
                
                user_info = self.get_user_info(username)
                self.logger.info(f"{action_prefix} Processing user: {username} → {user_info}")
                
                # Clean up all resources step by step
                self.logger.debug(f"Starting step-by-step cleanup for {username}")
                actions = self.cleanup_user_step_by_step(iam_client, username, dry_run)
                
                # Then delete user
                if self.delete_user(iam_client, username, dry_run):
                    deleted_users.append({
                        'username': username,
                        'user_info': user_info,
                        'actions_taken': len(actions) + 1,
                        'created_date': user_details['CreateDate'].strftime('%Y-%m-%d %H:%M:%S') if user_details else 'Unknown'
                    })
                    self.logger.log_user_action(username, "CLEANUP_COMPLETE", "SUCCESS", 
                                              f"All resources cleaned and user deleted for {user_info}")
                else:
                    failed_users.append(username)
                    self.logger.log_user_action(username, "CLEANUP_COMPLETE", "FAILED", user_info)
                
            except Exception as e:
                self.logger.error(f"Error processing user {username}: {e}")
                failed_users.append(username)
                continue
        
        return deleted_users, not_found_users, failed_users

    def display_cleanup_options(self):
        """Display cleanup options menu"""
        print("\n[DELETE]  Cleanup Options:")
        print("  1. Cleanup all cloud users in all accounts")
        print("  2. Cleanup all cloud users in specific account")
        print("  3. Dry run - Show what would be deleted (recommended first)")
        
        while True:
            try:
                choice = input("\n[#] Select cleanup option (1-3): ").strip()
                choice_num = int(choice)
                
                if 1 <= choice_num <= 3:
                    return choice_num
                else:
                    print("[ERROR] Invalid choice. Please enter a number between 1 and 3")
            except ValueError:
                print("[ERROR] Invalid input. Please enter a number.")

    def select_accounts(self):
        """Select which accounts to process with user count information"""
        print("\n[LIST] Available AWS Accounts:")
        
        for i, (account_name, config) in enumerate(self.aws_accounts.items(), 1):
            user_count = self.account_user_count.get(account_name, 0)
            if user_count > 0:
                print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']} [{user_count} users mapped]")
            else:
                print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']} [{Symbols.WARN}  NO USERS MAPPED]")
        
        print(f"  {len(self.aws_accounts) + 1}. All accounts with mapped users")
        
        while True:
            try:
                choice = input(f"\n[#] Select account(s) to process (1-{len(self.aws_accounts) + 1}): ").strip()
                choice_num = int(choice)
                
                if choice_num == len(self.aws_accounts) + 1:
                    # Return only accounts that have users in the mapping
                    return [acc for acc in self.aws_accounts.keys() if self.account_user_count.get(acc, 0) > 0]
                elif 1 <= choice_num <= len(self.aws_accounts):
                    selected_account = list(self.aws_accounts.keys())[choice_num - 1]
                    user_count = self.account_user_count.get(selected_account, 0)
                    if user_count == 0:
                        print(f"{Symbols.WARN}  Warning: Account '{selected_account}' has no mapped users to delete.")
                        confirm = input("Continue anyway? (y/N): ").lower().strip()
                        if confirm != 'y':
                            continue
                    return [selected_account]
                else:
                    print(f"{Symbols.ERROR} Invalid choice. Please enter a number between 1 and {len(self.aws_accounts) + 1}")
            except ValueError:
                print("[ERROR] Invalid input. Please enter a number.")

    def save_cleanup_report(self, all_deleted_users, all_not_found_users, all_failed_users):
        """Save cleanup report to JSON file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"iam_cleanup_report_{timestamp}.json"
            
            report_data = {
                "cleanup_date": self.current_time.split()[0],
                "cleanup_time": self.current_time.split()[1] + " UTC",
                "cleaned_by": self.current_user,
                "summary": {
                    "total_deleted": len(all_deleted_users),
                    "total_not_found": len(all_not_found_users),
                    "total_failed": len(all_failed_users)
                },
                "deleted_users": all_deleted_users,
                "not_found_users": all_not_found_users,
                "failed_users": all_failed_users
            }
            
            with open(filename, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            self.logger.info(f"Cleanup report saved to: {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"Failed to save cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        self.logger.info("Starting AWS IAM User Cleanup Script with Logging")
        self.logger.info(f"Execution time: {self.current_time} UTC")
        self.logger.info(f"Executed by: {self.current_user}")
        self.logger.warning("This script will DELETE IAM users and all associated resources!")
        
        # Display mapping analysis
        print(f"\n{Symbols.STATS} User Mapping Analysis:")
        print(f"   Total mapped users: {len(self.user_mappings)}")
        print(f"   Distribution: {self.account_user_count}")
        
        # Get cleanup option
        cleanup_option = self.display_cleanup_options()
        self.logger.info(f"Selected cleanup option: {cleanup_option}")
        
        dry_run = (cleanup_option == 3)
        if dry_run:
            self.logger.info("Running in DRY RUN mode - no actual changes will be made")
        
        if cleanup_option in [1, 3]:
            # Only process accounts that have users in the mapping
            accounts_to_process = [acc for acc in self.aws_accounts.keys() if self.account_user_count.get(acc, 0) > 0]
            if not accounts_to_process:
                print("[ERROR] No accounts have mapped users to delete!")
                return
        else:
            accounts_to_process = self.select_accounts()
        
        self.logger.info(f"Selected accounts for cleanup: {accounts_to_process}")
        
        if not dry_run:
            # Final confirmation
            total_users_to_delete = sum(self.account_user_count.get(acc, 0) for acc in accounts_to_process)
            print(f"\n{Symbols.WARN}  FINAL WARNING: You are about to DELETE {total_users_to_delete} IAM users in {len(accounts_to_process)} account(s)!")
            print("This action CANNOT be undone!")
            confirm = input("\nType 'DELETE' to confirm: ").strip()
            
            if confirm != 'DELETE':
                self.logger.info("Cleanup cancelled by user")
                print(f"{Symbols.ERROR} Cleanup cancelled")
                return
            else:
                self.logger.info("User confirmed deletion - proceeding with cleanup")
        
        all_deleted_users = []
        all_not_found_users = []
        all_failed_users = []
        
        # Process selected accounts
        for account_name in accounts_to_process:
            deleted_users, not_found_users, failed_users = self.cleanup_users_in_account(account_name, dry_run)
            all_deleted_users.extend(deleted_users)
            all_not_found_users.extend(not_found_users)
            all_failed_users.extend(failed_users)
        
        # Log final summary
        total_processed = len(all_deleted_users) + len(all_not_found_users) + len(all_failed_users)
        self.logger.log_summary(total_processed, len(all_deleted_users), len(all_failed_users), len(all_not_found_users))
        
        # Display results
        action_word = "Would be deleted" if dry_run else "Deleted"
        print(f"\n{'🧪' if dry_run else '{Symbols.TARGET}'}" * 20 + " CLEANUP SUMMARY " + f"{'🧪' if dry_run else '{Symbols.TARGET}'}" * 20)
        print("=" * 80)
        print(f"{Symbols.OK} Total users {action_word.lower()}: {len(all_deleted_users)}")
        print(f"{Symbols.INFO}  Total users not found: {len(all_not_found_users)}")
        print(f"{Symbols.ERROR} Total users failed: {len(all_failed_users)}")
        
        if all_deleted_users:
            print(f"\n{'🧪' if dry_run else '{Symbols.OK}'} Users {action_word}:")
            current_account = None
            for user in all_deleted_users:
                account_name = user['username'].split('_')[0]
                if current_account != account_name:
                    current_account = account_name
                    print(f"\n  {Symbols.ACCOUNT} {account_name}:")
                print(f"    • {user['username']} → {user['user_info']} ({user['actions_taken']} actions, created: {user['created_date']})")
        
        if all_not_found_users:
            print("\n[INFO]  Users Not Found (already deleted or never existed):")
            for username in all_not_found_users:
                print(f"  • {username}")
        
        if all_failed_users:
            print("\n[ERROR] Failed to Delete:")
            for username in all_failed_users:
                print(f"  • {username}")
        
        # Save cleanup report
        if not dry_run and (all_deleted_users or all_failed_users):
            save_report = input("\n📄 Save cleanup report to file? (y/N): ").lower().strip()
            if save_report == 'y':
                report_file = self.save_cleanup_report(all_deleted_users, all_not_found_users, all_failed_users)
                if report_file:
                    print(f"{Symbols.OK} Cleanup report saved to: {report_file}")
        
        if dry_run:
            self.logger.info("DRY RUN completed - no actual changes were made")
            print(f"\n🧪 This was a DRY RUN - no actual changes were made")
            print("Run the script again without dry run option to perform actual cleanup")
        else:
            self.logger.info("Cleanup operation completed")
            print(f"\n[PARTY] Cleanup completed!")

def main():
    """Main function"""
    try:
        cleanup = IAMUserCleanup()
        cleanup.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"{Symbols.ERROR} Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()