#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from text_symbols import Symbols

class IAMUserCleanup:
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.load_configuration()
        self.load_user_mapping()
        self.current_time = "2025-06-01 17:01:53"
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
            
            print(f"{Symbols.OK} Configuration loaded from: {self.config_file}")
            print(f"{Symbols.STATS} Found {len(self.aws_accounts)} AWS accounts")
            
        except FileNotFoundError as e:
            print(f"{Symbols.ERROR} {e}")
            print("Please ensure the configuration file exists in the same directory.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"{Symbols.ERROR} Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Symbols.ERROR} Error loading configuration: {e}")
            sys.exit(1)

    def load_user_mapping(self):
        """Load user mapping from JSON file"""
        try:
            if not os.path.exists(self.mapping_file):
                print(f"{Symbols.WARN}  User mapping file '{self.mapping_file}' not found")
                self.user_mappings = {}
                return
            
            with open(self.mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            self.user_mappings = mapping_data['user_mappings']
            print(f"{Symbols.OK} User mapping loaded from: {self.mapping_file}")
            
        except Exception as e:
            print(f"{Symbols.WARN}  Warning: Error loading user mapping: {e}")
            self.user_mappings = {}

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
            return iam_client, account_config
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                print(f"{Symbols.ERROR} Access denied for {account_name}. Please check credentials.")
            else:
                print(f"{Symbols.ERROR} AWS Error for {account_name}: {e}")
            raise
        except Exception as e:
            print(f"{Symbols.ERROR} Failed to create IAM client for {account_name}: {e}")
            raise

    def get_users_for_account(self, account_name):
        """Get user list for specific account"""
        users_count = self.user_settings['users_per_account']
        users = []
        for i in range(1, users_count + 1):
            username = f"{account_name}_clouduser{i:02d}"
            users.append(username)
        return users

    def check_user_exists(self, iam_client, username):
        """Check if IAM user exists and return user details"""
        try:
            response = iam_client.get_user(UserName=username)
            return True, response['User']
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                return False, None
            else:
                raise e

    def cleanup_user_step_by_step(self, iam_client, username, dry_run=False):
        """Clean up user following the exact sequence: login profile → access keys → policies → user"""
        actions_taken = []
        
        try:
            # STEP 1: DELETE LOGIN PROFILE FIRST
            print("    🔐 Step 1: Deleting login profile...")
            try:
                iam_client.get_login_profile(UserName=username)
                if not dry_run:
                    iam_client.delete_login_profile(UserName=username)
                actions_taken.append("[OK] Deleted login profile")
                print("      [OK] Login profile deleted")
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    print(f"      {Symbols.INFO}  No login profile found")
                else:
                    print(f"      {Symbols.ERROR} Error deleting login profile: {e}")
            
            # STEP 2: PROCESS ACCESS KEYS (deactivate then delete)
            print("    [KEY] Step 2: Processing access keys...")
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
                                print(f"      {Symbols.OK} Deactivated access key: {access_key_id}")
                                actions_taken.append(f"{Symbols.OK} Deactivated access key: {access_key_id}")
                            except ClientError as e:
                                print(f"      {Symbols.WARN}  Warning deactivating access key {access_key_id}: {e}")
                        
                        # Then delete
                        try:
                            if not dry_run:
                                iam_client.delete_access_key(
                                    UserName=username,
                                    AccessKeyId=access_key_id
                                )
                            print(f"      {Symbols.OK} Deleted access key: {access_key_id}")
                            actions_taken.append(f"{Symbols.OK} Deleted access key: {access_key_id}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error deleting access key {access_key_id}: {e}")
                else:
                    print("      [INFO]  No access keys found")
                    
            except ClientError as e:
                print(f"      {Symbols.ERROR} Error listing access keys: {e}")
            
            # STEP 3: DETACH MANAGED POLICIES
            print("    [LIST] Step 3: Detaching managed policies...")
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
                            print(f"      {Symbols.OK} Detached policy: {policy['PolicyName']}")
                            actions_taken.append(f"{Symbols.OK} Detached policy: {policy['PolicyName']}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error detaching policy {policy['PolicyName']}: {e}")
                else:
                    print("      [INFO]  No attached policies found")
                    
            except ClientError as e:
                print(f"      {Symbols.ERROR} Error listing attached policies: {e}")
            
            # STEP 4: DELETE INLINE POLICIES
            print("    📄 Step 4: Deleting inline policies...")
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
                            print(f"      {Symbols.OK} Deleted inline policy: {policy_name}")
                            actions_taken.append(f"{Symbols.OK} Deleted inline policy: {policy_name}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error deleting inline policy {policy_name}: {e}")
                else:
                    print("      [INFO]  No inline policies found")
                    
            except ClientError as e:
                print(f"      {Symbols.ERROR} Error listing inline policies: {e}")
            
            # STEP 5: REMOVE FROM GROUPS
            print("    👥 Step 5: Removing from groups...")
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
                            print(f"      {Symbols.OK} Removed from group: {group['GroupName']}")
                            actions_taken.append(f"{Symbols.OK} Removed from group: {group['GroupName']}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error removing from group {group['GroupName']}: {e}")
                else:
                    print("      [INFO]  No group memberships found")
                    
            except ClientError as e:
                if e.response['Error']['Code'] != 'NoSuchEntity':
                    print(f"      {Symbols.ERROR} Error listing groups: {e}")
                else:
                    print("      [INFO]  No group memberships found")
            
            # STEP 6: DELETE MFA DEVICES (if any)
            print("    🔐 Step 6: Removing MFA devices...")
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
                            print(f"      {Symbols.OK} Removed MFA device: {mfa_device['SerialNumber']}")
                            actions_taken.append(f"{Symbols.OK} Removed MFA device: {mfa_device['SerialNumber']}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error removing MFA device: {e}")
                else:
                    print("      [INFO]  No MFA devices found")
                    
            except ClientError as e:
                print(f"      {Symbols.ERROR} Error listing MFA devices: {e}")
            
            # STEP 7: DELETE SIGNING CERTIFICATES (if any)
            print("    📜 Step 7: Removing signing certificates...")
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
                            print(f"      {Symbols.OK} Deleted certificate: {cert['CertificateId']}")
                            actions_taken.append(f"{Symbols.OK} Deleted certificate: {cert['CertificateId']}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error deleting certificate: {e}")
                else:
                    print("      [INFO]  No signing certificates found")
                    
            except ClientError as e:
                print(f"      {Symbols.ERROR} Error listing signing certificates: {e}")
            
            # STEP 8: DELETE SSH PUBLIC KEYS (if any)
            print("    🔧 Step 8: Removing SSH public keys...")
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
                            print(f"      {Symbols.OK} Deleted SSH key: {ssh_key['SSHPublicKeyId']}")
                            actions_taken.append(f"{Symbols.OK} Deleted SSH key: {ssh_key['SSHPublicKeyId']}")
                        except ClientError as e:
                            print(f"      {Symbols.ERROR} Error deleting SSH key: {e}")
                else:
                    print("      [INFO]  No SSH public keys found")
                    
            except ClientError as e:
                print(f"      {Symbols.ERROR} Error listing SSH public keys: {e}")
                
        except Exception as e:
            print(f"  {Symbols.ERROR} Error in cleanup process for {username}: {e}")
            raise
        
        return actions_taken

    def delete_user(self, iam_client, username, dry_run=False):
        """Delete the IAM user after all resources are cleaned up"""
        try:
            print("    [DELETE]  Step 9: Deleting user...")
            if not dry_run:
                iam_client.delete_user(UserName=username)
                print(f"      {Symbols.OK} User {username} deleted successfully")
            else:
                print(f"      🧪 Would delete user: {username}")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            print(f"      {Symbols.ERROR} Cannot delete user {username}: {error_message}")
            
            if error_code == 'DeleteConflict':
                print(f"      {Symbols.TIP} There are still resources attached. Let me check what's remaining...")
                
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
                        print(f"      {Symbols.LIST} Remaining resources: {', '.join(remaining_resources)}")
                    else:
                        print(f"      🤔 No obvious remaining resources found")
                        
                except Exception as check_e:
                    print(f"      {Symbols.WARN}  Could not check remaining resources: {check_e}")
            
            return False
                
        except Exception as e:
            print(f"      {Symbols.ERROR} Unexpected error deleting user {username}: {e}")
            return False

    def cleanup_users_in_account(self, account_name, dry_run=False):
        """Cleanup users in a specific AWS account"""
        action_prefix = "🧪 [DRY RUN]" if dry_run else "[DELETE]  [DELETING]"
        print(f"\n{Symbols.ACCOUNT} {action_prefix} Working on Account: {account_name.upper()}")
        print("=" * 60)
        
        try:
            # Initialize IAM client for this account
            iam_client, account_config = self.create_iam_client(account_name)
            print(f"{Symbols.OK} Connected to AWS Account: {account_config['account_id']}")
            print(f"📧 Email: {account_config['email']}")
            
        except Exception as e:
            print(f"{Symbols.ERROR} Failed to connect to {account_name}: {e}")
            return [], [], []
        
        # Get users for this account
        users_to_check = self.get_users_for_account(account_name)
        
        deleted_users = []
        not_found_users = []
        failed_users = []
        
        print(f"\n{Symbols.SCAN} Checking for users to cleanup...")
        
        for username in users_to_check:
            try:
                exists, user_details = self.check_user_exists(iam_client, username)
                
                if not exists:
                    print(f"  {Symbols.INFO}  User {username} does not exist - SKIPPING")
                    not_found_users.append(username)
                    continue
                
                user_info = self.get_user_info(username)
                print(f"\n{action_prefix} Processing user: {username}")
                print(f"   👤 Real User: {user_info}")
                
                # Clean up all resources step by step
                print("  🧹 Cleaning up user resources step by step...")
                actions = self.cleanup_user_step_by_step(iam_client, username, dry_run)
                
                # Then delete user
                if self.delete_user(iam_client, username, dry_run):
                    deleted_users.append({
                        'username': username,
                        'user_info': user_info,
                        'actions_taken': len(actions) + 1,
                        'created_date': user_details['CreateDate'].strftime('%Y-%m-%d %H:%M:%S') if user_details else 'Unknown'
                    })
                else:
                    failed_users.append(username)
                
                print("-" * 50)
                
            except Exception as e:
                print(f"{Symbols.ERROR} Error processing user {username}: {e}")
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
        """Select which accounts to process"""
        print("\n[LIST] Available AWS Accounts:")
        for i, (account_name, config) in enumerate(self.aws_accounts.items(), 1):
            print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']}")
        
        print(f"  {len(self.aws_accounts) + 1}. All accounts")
        
        while True:
            try:
                choice = input(f"\n[#] Select account(s) to process (1-{len(self.aws_accounts) + 1}): ").strip()
                choice_num = int(choice)
                
                if choice_num == len(self.aws_accounts) + 1:
                    return list(self.aws_accounts.keys())
                elif 1 <= choice_num <= len(self.aws_accounts):
                    return [list(self.aws_accounts.keys())[choice_num - 1]]
                else:
                    print(f"{Symbols.ERROR} Invalid choice. Please enter a number between 1 and {len(self.aws_accounts) + 1}")
            except ValueError:
                print("[ERROR] Invalid input. Please enter a number.")

    def run(self):
        """Main execution method"""
        print("[DELETE]  AWS IAM User Cleanup Script (FINAL FIX)")
        print("=" * 60)
        print(f"{Symbols.DATE} Execution Date/Time: {self.current_time} UTC")
        print(f"👤 Executed by: {self.current_user}")
        print("[WARN]  WARNING: This script will DELETE IAM users and all associated resources!")
        print("=" * 60)
        
        # Get cleanup option
        cleanup_option = self.display_cleanup_options()
        
        dry_run = (cleanup_option == 3)
        
        if cleanup_option in [1, 3]:
            accounts_to_process = list(self.aws_accounts.keys())
        else:
            accounts_to_process = self.select_accounts()
        
        if not dry_run:
            # Final confirmation
            print(f"\n{Symbols.WARN}  FINAL WARNING: You are about to DELETE IAM users in {len(accounts_to_process)} account(s)!")
            print("This action CANNOT be undone!")
            confirm = input("\nType 'DELETE' to confirm: ").strip()
            
            if confirm != 'DELETE':
                print(f"{Symbols.ERROR} Cleanup cancelled")
                return
        
        all_deleted_users = []
        all_not_found_users = []
        all_failed_users = []
        
        # Process selected accounts
        for account_name in accounts_to_process:
            deleted_users, not_found_users, failed_users = self.cleanup_users_in_account(account_name, dry_run)
            all_deleted_users.extend(deleted_users)
            all_not_found_users.extend(not_found_users)
            all_failed_users.extend(failed_users)
        
        # Overall Summary
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
        
        if dry_run:
            print(f"\n🧪 This was a DRY RUN - no actual changes were made")
            print("Run the script again without dry run option to perform actual cleanup")

        else:
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
    main()  # Run the script