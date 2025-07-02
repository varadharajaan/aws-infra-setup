"""
Enhanced AWS Credential Manager - Multi Account Multi User Selection
Supports comma-separated, range, single, and 'all' selection for both accounts and users
"""

import json
import os
import boto3
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import re
import glob

@dataclass
class CredentialInfo:
    account_name: str
    account_id: str
    email: str
    access_key: str
    secret_key: str
    credential_type: str  # 'root' or 'iam'
    regions: List[str]
    username: Optional[str] = None  # For IAM users

@dataclass
class MultiUserCredentials:
    """Container for multiple user credentials"""
    users: List[CredentialInfo]
    credential_type: str
    total_users: int

class EnhancedAWSCredentialManager:
    from datetime import datetime
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.config_data = None
        self.user_mappings = {}
        self.current_user = 'varadharajaan'
        self.current_time = int(datetime.utcnow().timestamp())
        self.load_configuration()
        self.load_user_mapping()
    
    def load_configuration(self):
        """Load AWS account configurations from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.aws_accounts = config['accounts']
            self.user_settings = config['user_settings']
            self.config_data = config
            
            print(f"✅ Configuration loaded from: {self.config_file}")
            print(f"📊 Found {len(self.aws_accounts)} AWS accounts")
            
        except FileNotFoundError as e:
            print(f"❌ {e}")
            print("Please ensure the configuration file exists in the same directory.")
            raise
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in configuration file: {e}")
            raise
        except Exception as e:
            print(f"❌ Error loading configuration: {e}")
            raise

    def load_user_mapping(self):
        """Load user mapping from JSON file"""
        try:
            if not os.path.exists(self.mapping_file):
                print(f"⚠️  User mapping file '{self.mapping_file}' not found")
                self.user_mappings = {}
                return
            
            with open(self.mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            self.user_mappings = mapping_data['user_mappings']
            print(f"✅ User mapping loaded from: {self.mapping_file}")
            print(f"👥 Found mappings for {len(self.user_mappings)} users")
            
        except Exception as e:
            print(f"⚠️  Warning: Error loading user mapping: {e}")
            self.user_mappings = {}

    def get_user_info(self, username):
        """Get real user information for a username"""
        if username in self.user_mappings:
            mapping = self.user_mappings[username]
            return {
                'first_name': mapping['first_name'],
                'last_name': mapping['last_name'],
                'email': mapping['email'],
                'full_name': f"{mapping['first_name']} {mapping['last_name']}"
            }
        else:
            return {
                'first_name': 'Unknown',
                'last_name': 'User',
                'email': 'unknown@company.com',
                'full_name': 'Unknown User'
            }

    def get_users_per_account_name(self, account_name: str) -> int:
        """
        Return the users_per_account for a given account, falling back to the global value if not set at the account level.
        """
        account = self.aws_accounts.get(account_name, {})
        if 'users_per_account' in account:
            return account['users_per_account']
        return self.user_settings.get('users_per_account', 1)

    def get_users_for_account(self, account_name):
        """Get user-region mapping for specific account"""
        regions = self.user_settings['user_regions']
        users_count = self.get_users_per_account_name(account_name)
        
        users_regions = {}
        for i in range(1, users_count + 1):
            username = f"{account_name}_clouduser{i:02d}"
            region = regions[(i-1) % len(regions)]  # Cycle through regions
            users_regions[username] = region
            
        return users_regions

    def parse_selection_input(self, user_input: str, max_items: int) -> List[int]:
        """Parse user selection input supporting ranges, multiple values, and 'all'"""
        user_input = user_input.strip().lower()
        
        if not user_input or user_input == 'all':
            return list(range(1, max_items + 1))
        
        selected_items = []
        
        # Split by comma and process each part
        parts = [part.strip() for part in user_input.split(',')]
        
        for part in parts:
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start, end = map(int, part.split('-'))
                    if start < 1 or end > max_items or start > end:
                        print(f"⚠️ Invalid range: {part} (valid range: 1-{max_items})")
                        continue
                    selected_items.extend(range(start, end + 1))
                except ValueError:
                    print(f"⚠️ Invalid range format: {part}")
                    continue
            else:
                # Handle single number
                try:
                    num = int(part)
                    if 1 <= num <= max_items:
                        selected_items.append(num)
                    else:
                        print(f"⚠️ Number {num} is out of range (1-{max_items})")
                except ValueError:
                    print(f"⚠️ Invalid number: {part}")
                    continue
        
        # Remove duplicates and sort
        return sorted(list(set(selected_items)))

    def prompt_credential_type(self) -> str:
        """Prompt user to select credential type"""
        print("\n" + "="*60)
        print("🔑 CREDENTIAL SELECTION")
        print("="*60)
        print("Choose your credential type:")
        print("1. Root Credentials (Full account access)")
        print("2. IAM User Credentials (User-specific access)")
        print("="*60)
        
        while True:
            choice = input("Enter your choice (1 for Root, 2 for IAM): ").strip()
            if choice == '1':
                return 'root'
            elif choice == '2':
                return 'iam'
            else:
                print("❌ Invalid choice. Please enter 1 or 2.")

    def display_accounts_for_selection(self) -> List[Dict]:
        """Display available accounts for selection"""
        accounts = self.aws_accounts
        account_list = []
        
        print("\n" + "="*80)
        print("🏢 AVAILABLE AWS ACCOUNTS")
        print("="*80)
        
        for i, (account_name, account_data) in enumerate(accounts.items(), 1):
            account_id = account_data.get('account_id', 'Unknown')
            email = account_data.get('email', 'Unknown')
            user_regions = self.user_settings.get('user_regions', [])
            
            print(f"  {i:2}. {account_name}")
            print(f"      📧 Email: {email}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      🌍 Available Regions: {', '.join(user_regions)}")
            print()
            
            account_list.append({
                'index': i,
                'account_name': account_name,
                'account_data': account_data
            })
        
        return account_list

    def select_multiple_accounts(self) -> List[Dict]:
        """Select multiple accounts with various input formats"""
        account_list = self.display_accounts_for_selection()
        
        print("Account Selection Options:")
        print("  • Single account: Enter number (e.g., 1)")
        print("  • Multiple accounts: Comma-separated (e.g., 1,3,5)")
        print("  • Range: Use dash (e.g., 1-3 or 2-5)")
        print("  • All accounts: 'all' or press Enter")
        print("  • Mixed: Combine methods (e.g., 1,3-5,7)")
        
        while True:
            try:
                selection = input(f"\n🔢 Select account(s) (1-{len(account_list)}): ").strip()
                
                if not selection:
                    selection = 'all'
                
                selected_indices = self.parse_selection_input(selection, len(account_list))
                
                if not selected_indices:
                    print("❌ No valid accounts selected. Please try again.")
                    continue
                
                selected_accounts = [account_list[i-1] for i in selected_indices]
                
                # Show selected accounts for confirmation
                print(f"\n✅ Selected {len(selected_accounts)} account(s):")
                for account in selected_accounts:
                    print(f"   • {account['account_name']} ({account['account_data'].get('account_id', 'Unknown')})")
                
                confirm = input("\nConfirm selection? (Y/n): ").strip().lower()
                if confirm in ['', 'y', 'yes']:
                    return selected_accounts
                else:
                    print("Selection cancelled. Please choose again.")
                
            except Exception as e:
                print(f"❌ Error in account selection: {e}")
                continue

    def select_multiple_root_credentials(self) -> MultiUserCredentials:
        """Handle multiple Root account selection"""
        selected_accounts = self.select_multiple_accounts()
        root_credentials = []
        
        print("\n" + "="*60)
        print("🌍 REGION SELECTION FOR ROOT ACCOUNTS")
        print("="*60)
        
        # Get available regions
        available_regions = self.user_settings.get('user_regions', ['us-east-1'])
        
        for account in selected_accounts:
            account_name = account['account_name']
            account_data = account['account_data']
            
            print(f"\n📍 Select region for {account_name}:")
            for i, region in enumerate(available_regions, 1):
                print(f"  {i}. {region}")
            
            while True:
                try:
                    choice = input(f"Select region (1-{len(available_regions)}): ").strip()
                    if not choice:
                        choice = '1'  # Default to first region
                    
                    region_index = int(choice) - 1
                    if 0 <= region_index < len(available_regions):
                        selected_region = available_regions[region_index]
                        break
                    else:
                        print(f"❌ Invalid choice. Please enter 1-{len(available_regions)}")
                except ValueError:
                    print("❌ Please enter a valid number")
            
            # Create credential info for root account
            cred_info = CredentialInfo(
                account_name=account_name,
                account_id=account_data.get('account_id'),
                email=account_data.get('email'),
                access_key=account_data.get('access_key'),
                secret_key=account_data.get('secret_key'),
                credential_type='root',
                regions=[selected_region]
            )
            
            root_credentials.append(cred_info)
            print(f"✅ Added root credentials for {account_name} in {selected_region}")
        
        return MultiUserCredentials(
            users=root_credentials,
            credential_type='root',
            total_users=len(root_credentials)
        )

    def select_iam_credential_file(self) -> Optional[str]:
        """Display all IAM credential files and let user select one"""
        try:
            # Look for IAM credential files with pattern "iam_users_credentials_*"
            pattern = './aws/iam/iam_users_credentials_*.json'
            iam_files = glob.glob(pattern)
            
            if not iam_files:
                print("❌ No IAM credential files found in ./aws/iam/")
                print("Please run the IAM user creation script first")
                return None
            
            # Sort files by modification time (newest first)
            file_info_list = []
            for file_path in iam_files:
                file_info_list.append({
                    'path': file_path,
                    'filename': os.path.basename(file_path),
                    'timestamp': os.path.getmtime(file_path)
                })
            
            # Sort by timestamp (newest first)
            sorted_files = sorted(file_info_list, key=lambda x: x['timestamp'], reverse=True)
            
            print("\n📂 Available IAM Credential Files:")
            print("="*80)
            print(f"{'#':<3} {'Filename':<35} {'Modified':<25} {'Size':<8}")
            print("-"*80)
            
            for i, file_info in enumerate(sorted_files, 1):
                # Format timestamp to human readable
                timestamp = datetime.fromtimestamp(file_info['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                
                # Get file size
                try:
                    file_size = os.path.getsize(file_info['path'])
                    if file_size < 1024:
                        size_str = f"{file_size}B"
                    elif file_size < 1024*1024:
                        size_str = f"{file_size/1024:.1f}KB"
                    else:
                        size_str = f"{file_size/(1024*1024):.1f}MB"
                except:
                    size_str = "N/A"
                
                print(f"{i:<3} {file_info['filename']:<35} {timestamp:<25} {size_str:<8}")
            
            print("-"*80)
            print(f"Total files found: {len(sorted_files)}")
            print("\nSelection Options:")
            print("  • Enter number (1-{}) to select specific file".format(len(sorted_files)))
            print("  • Press Enter to use latest file (recommended)")
            print("  • Enter 'q' to quit")
            
            while True:
                try:
                    choice = input(f"\n🔢 Select IAM credential file (1-{len(sorted_files)}, Enter for latest): ").strip()
                    
                    if choice == 'q':
                        print("❌ File selection cancelled")
                        return None
                    elif not choice:
                        # Use latest file (first in sorted list)
                        selected_file = sorted_files[0]
                        print(f"✅ Using latest file: {selected_file['filename']}")
                        print(f"   📅 Modified: {datetime.fromtimestamp(selected_file['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}")
                        return selected_file['path']
                    else:
                        file_index = int(choice) - 1
                        if 0 <= file_index < len(sorted_files):
                            selected_file = sorted_files[file_index]
                            timestamp_str = datetime.fromtimestamp(selected_file['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                            print(f"✅ Selected file: {selected_file['filename']}")
                            print(f"   📅 Modified: {timestamp_str}")
                            
                            # Show file preview
                            self.show_credential_file_preview(selected_file['path'])
                            return selected_file['path']
                        else:
                            print(f"❌ Invalid choice. Please enter a number between 1 and {len(sorted_files)}")
                            
                except ValueError:
                    print("❌ Please enter a valid number")
                except KeyboardInterrupt:
                    print("\n❌ File selection cancelled")
                    return None
                    
        except Exception as e:
            print(f"❌ Error finding IAM credential files: {e}")
            return None

    def show_credential_file_preview(self, file_path: str):
        """Show a preview of the credential file contents"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            print(f"\n📋 File Preview:")
            print("-"*40)
            print(f"Created Date: {data.get('created_date', 'Unknown')}")
            print(f"Created Time: {data.get('created_time', 'Unknown')}")
            print(f"Created By: {data.get('created_by', 'Unknown')}")
            print(f"Total Users: {data.get('total_users', 'Unknown')}")
            
            if 'accounts' in data:
                print(f"Accounts: {len(data['accounts'])}")
                for account_name, account_info in list(data['accounts'].items())[:3]:  # Show first 3 accounts
                    users_count = len(account_info.get('users', []))
                    print(f"  • {account_name}: {users_count} users")
                
                if len(data['accounts']) > 3:
                    print(f"  ... and {len(data['accounts']) - 3} more accounts")
            
        except Exception as e:
            print(f"⚠️ Could not preview file: {e}")

    def display_iam_accounts_with_users(self, iam_file_path: str) -> List[Dict]:
        """Display available accounts with their IAM users from credential file"""
        try:
            with open(iam_file_path, 'r') as f:
                iam_data = json.load(f)
            
            if 'accounts' not in iam_data:
                print("❌ Invalid IAM credential file format")
                return []
            
            iam_accounts = []
            
            print("\n" + "="*90)
            print("👥 AVAILABLE IAM USERS BY ACCOUNT")
            print("="*90)
            
            for i, (account_name, account_info) in enumerate(iam_data['accounts'].items(), 1):
                account_data = self.aws_accounts.get(account_name, {})
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                
                users = account_info.get('users', [])
                
                print(f"  {i:2}. {account_name}")
                print(f"      📧 Email: {email}")
                print(f"      🆔 Account ID: {account_id}")
                print(f"      👥 Available Users ({len(users)}):")
                
                for j, user in enumerate(users, 1):
                    username = user.get('username', 'Unknown')
                    real_user = user.get('real_user', {})
                    full_name = real_user.get('full_name', 'Unknown User')
                    region = user.get('region', 'us-east-1')
                    print(f"         {j}. {username} ({full_name}) - Region: {region}")
                print()
                
                iam_accounts.append({
                    'index': i,
                    'account_name': account_name,
                    'account_data': account_data,
                    'users': users
                })
            
            return iam_accounts
            
        except Exception as e:
            print(f"❌ Error reading IAM credential file: {e}")
            return []

    def select_multiple_iam_credentials(self) -> MultiUserCredentials:
        """Handle multiple IAM user selection with manual file selection"""
        
        # Step 1: Manual file selection instead of automatic latest
        print("\n🔑 STEP 1: IAM CREDENTIAL FILE SELECTION")
        iam_file_path = self.select_iam_credential_file()
        if not iam_file_path:
            raise ValueError("No IAM credential file selected")
        
        # Step 2: Display accounts with users
        iam_accounts = self.display_iam_accounts_with_users(iam_file_path)
        if not iam_accounts:
            raise ValueError("No accounts found in IAM credential file")
        
        # Step 3: Select multiple accounts
        print("\n🏢 STEP 2: ACCOUNT SELECTION")
        print("Account Selection Options:")
        print("  • Single account: Enter number (e.g., 1)")
        print("  • Multiple accounts: Comma-separated (e.g., 1,3,5)")
        print("  • Range: Use dash (e.g., 1-3)")
        print("  • All accounts: 'all' or press Enter")
        
        while True:
            try:
                selection = input(f"\n🔢 Select account(s) (1-{len(iam_accounts)}): ").strip()
                
                if not selection:
                    selection = 'all'
                
                selected_indices = self.parse_selection_input(selection, len(iam_accounts))
                
                if not selected_indices:
                    print("❌ No valid accounts selected. Please try again.")
                    continue
                
                selected_accounts = [iam_accounts[i-1] for i in selected_indices]
                
                # Show selected accounts for confirmation
                print(f"\n✅ Selected {len(selected_accounts)} account(s):")
                for account in selected_accounts:
                    users_count = len(account['users'])
                    print(f"   • {account['account_name']} ({users_count} users)")

                break
                
            except Exception as e:
                print(f"❌ Error in account selection: {e}")
                continue
        
        # Step 4: For each selected account, select users
        print("\n👤 STEP 3: USER SELECTION")
        all_iam_credentials = []
        
        for account in selected_accounts:
            account_name = account['account_name']
            users = account['users']
            
            print(f"\n👥 USER SELECTION FOR {account_name.upper()}:")
            print("-" * 60)
            
            for i, user in enumerate(users, 1):
                username = user.get('username', 'Unknown')
                real_user = user.get('real_user', {})
                full_name = real_user.get('full_name', 'Unknown User')
                region = user.get('region', 'us-east-1')
                print(f"  {i:2}. {username} ({full_name}) - Region: {region}")
            
            print(f"\nUser Selection Options for {account_name}:")
            print("  • Single user: Enter number (e.g., 1)")
            print("  • Multiple users: Comma-separated (e.g., 1,3,5)")
            print("  • Range: Use dash (e.g., 1-3)")
            print("  • All users: 'all' or press Enter")
            
            while True:
                try:
                    user_selection = input(f"\n🔢 Select user(s) for {account_name} (1-{len(users)}): ").strip()
                    
                    if not user_selection:
                        user_selection = 'all'
                    
                    selected_user_indices = self.parse_selection_input(user_selection, len(users))
                    
                    if not selected_user_indices:
                        print("❌ No valid users selected. Please try again.")
                        continue
                    
                    selected_users = [users[i-1] for i in selected_user_indices]
                    
                    # Show selected users for confirmation
                    print(f"\n✅ Selected {len(selected_users)} user(s) from {account_name}:")
                    for user in selected_users:
                        username = user.get('username', 'Unknown')
                        real_user = user.get('real_user', {})
                        full_name = real_user.get('full_name', 'Unknown User')
                        region = user.get('region', 'us-east-1')
                        print(f"   • {username} ({full_name}) - {region}")
                    
                    break
                    
                except Exception as e:
                    print(f"❌ Error in user selection: {e}")
                    continue
            
            # Create credential info for each selected user
            for user in selected_users:
                cred_info = CredentialInfo(
                    account_name=account_name,
                    account_id=account['account_data'].get('account_id'),
                    email=user.get('real_user', {}).get('email', account['account_data'].get('email')),
                    access_key=user.get('access_key_id'),
                    secret_key=user.get('secret_access_key'),
                    credential_type='iam',
                    regions=[user.get('region', 'us-east-1')],
                    username=user.get('username')
                )
                
                all_iam_credentials.append(cred_info)
                print(f"✅ Added IAM credentials for {user.get('username')} in {account_name}")
        
        print(f"\n🎉 Total IAM credentials configured: {len(all_iam_credentials)}")
        
        return MultiUserCredentials(
            users=all_iam_credentials,
            credential_type='iam',
            total_users=len(all_iam_credentials)
        )

    def get_multiple_credentials(self) -> MultiUserCredentials:
        """Main method to get multiple credentials based on user choice"""
        credential_type = self.prompt_credential_type()
        
        if credential_type == 'root':
            return self.select_multiple_root_credentials()
        else:
            return self.select_multiple_iam_credentials()

    def validate_credentials(self, cred_info: CredentialInfo) -> bool:
        """Validate credentials by making a test AWS call"""
        try:
            print(f"🔍 Validating {cred_info.credential_type} credentials for {cred_info.account_name}...")

            sts_client = boto3.client(
                'sts',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=cred_info.regions[0]
            )

            identity = sts_client.get_caller_identity()
            actual_account_id = identity.get('Account')

            if actual_account_id == cred_info.account_id:
                print(f"✅ Credentials validated successfully for {cred_info.account_name}")
                if cred_info.username:
                    print(f"   👥 IAM User: {cred_info.username}")
                return True
            else:
                print(f"❌ Account ID mismatch for {cred_info.account_name}!")
                print(f"   Expected: {cred_info.account_id}")
                print(f"   Actual: {actual_account_id}")
                return False

        except Exception as e:
            print(f"❌ Credential validation failed for {cred_info.account_name}: {e}")
            return False

    def validate_multiple_credentials(self, multi_creds: MultiUserCredentials) -> MultiUserCredentials:
        """Validate multiple credentials and return only valid ones"""
        print(f"\n🔍 Validating {multi_creds.total_users} credential(s)...")
        
        valid_credentials = []
        
        for cred_info in multi_creds.users:
            if self.validate_credentials(cred_info):
                valid_credentials.append(cred_info)
        
        print(f"\n📊 Validation Results:")
        print(f"   ✅ Valid: {len(valid_credentials)}")
        print(f"   ❌ Invalid: {multi_creds.total_users - len(valid_credentials)}")
        
        return MultiUserCredentials(
            users=valid_credentials,
            credential_type=multi_creds.credential_type,
            total_users=len(valid_credentials)
        )

    def get_credentials(self) -> CredentialInfo:
        """Single credential method for backwards compatibility"""
        multi_creds = self.get_multiple_credentials()
        validated_creds = self.validate_multiple_credentials(multi_creds)
        
        if validated_creds.total_users == 0:
            raise ValueError("No valid credentials found")
        
        return validated_creds.users[0]  # Return first credential for backwards compatibility

# Example usage function
def main():
    """Example usage of the enhanced credential manager"""
    try:
        # Initialize the credential manager
        cred_manager = EnhancedAWSCredentialManager()
        
        # Get multiple credentials with enhanced selection
        multi_credentials = cred_manager.get_multiple_credentials()
        
        # Validate all credentials
        validated_credentials = cred_manager.validate_multiple_credentials(multi_credentials)
        
        if validated_credentials.total_users == 0:
            print("❌ No valid credentials found. Exiting.")
            return False
        
        print(f"\n🎉 Successfully configured {validated_credentials.total_users} credential(s)!")
        print(f"   Credential Type: {validated_credentials.credential_type.upper()}")
        
        # Display final summary
        print(f"\n📋 FINAL CREDENTIAL SUMMARY:")
        print("="*60)
        for i, cred in enumerate(validated_credentials.users, 1):
            print(f"{i:2}. Account: {cred.account_name}")
            if cred.username:
                print(f"    User: {cred.username}")
            print(f"    Region: {cred.regions[0]}")
            print(f"    Type: {cred.credential_type.upper()}")
            print()
        
        return validated_credentials
        
    except Exception as e:
        print(f"❌ Error in credential selection: {e}")
        return False

if __name__ == "__main__":
    result = main()
    if result:
        print("✅ Credential selection completed successfully!")
    else:
        print("❌ Credential selection failed!")