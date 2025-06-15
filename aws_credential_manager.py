"""
AWS Credential Manager - Enhanced for Root/IAM Selection
Handles credential selection flow for EC2 and EKS automation
"""

import json
import os
import boto3
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import re

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

class AWSCredentialManager:
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.config_data = None
        self.user_mappings = {}
        self.load_configuration()
        self.load_user_mapping()
    
    def load_configuration(self):
        """Load AWS account configurations from JSON file - reuse existing method"""
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
        """Load user mapping from JSON file - reuse existing method"""
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
        """Get real user information for a username - reuse existing method"""
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
                'email': 'unknown@bakerhughes.com',
                'full_name': 'Unknown User'
            }

    def get_users_for_account(self, account_name):
        """Get user-region mapping for specific account - reuse existing method"""
        regions = self.user_settings['user_regions']
        users_count = self.user_settings['users_per_account']
        
        users_regions = {}
        for i in range(1, users_count + 1):
            username = f"{account_name}_clouduser{i:02d}"
            region = regions[(i-1) % len(regions)]  # Cycle through regions
            users_regions[username] = region
            
        return users_regions
    
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
    
    def display_root_accounts(self) -> List[Dict]:
        """Display available Root accounts"""
        accounts = self.aws_accounts
        root_accounts = []
        
        print("\n" + "="*80)
        print("🏢 AVAILABLE ROOT ACCOUNTS")
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
            
            root_accounts.append({
                'index': i,
                'account_name': account_name,
                'account_data': account_data
            })
        
        return root_accounts

    def display_iam_accounts_with_users(self) -> List[Dict]:
        """Display available accounts with their IAM users"""
        accounts = self.aws_accounts
        iam_accounts = []
        
        print("\n" + "="*90)
        print("👥 AVAILABLE IAM USERS BY ACCOUNT")
        print("="*90)
        
        for i, (account_name, account_data) in enumerate(accounts.items(), 1):
            account_id = account_data.get('account_id', 'Unknown')
            email = account_data.get('email', 'Unknown')
            
            # Get users for this account
            users_regions = self.get_users_for_account(account_name)
            
            print(f"  {i:2}. {account_name}")
            print(f"      📧 Email: {email}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      👥 Available Users:")
            
            for j, (username, region) in enumerate(users_regions.items(), 1):
                user_info = self.get_user_info(username)
                print(f"         {j}. {username} ({user_info['full_name']}) - Region: {region}")
            print()
            
            iam_accounts.append({
                'index': i,
                'account_name': account_name,
                'account_data': account_data,
                'users_regions': users_regions
            })
        
        return iam_accounts
    
    def select_root_account(self) -> CredentialInfo:
        """Handle Root account selection"""
        root_accounts = self.display_root_accounts()
        
        while True:
            try:
                choice = input(f"Select account (1-{len(root_accounts)}): ").strip()
                account_index = int(choice) - 1
                
                if 0 <= account_index < len(root_accounts):
                    selected = root_accounts[account_index]
                    account_data = selected['account_data']
                    
                    # Select region from available regions
                    regions = self.user_settings.get('user_regions', [])
                    selected_region = self.select_region(regions)
                    
                    return CredentialInfo(
                        account_name=selected['account_name'],
                        account_id=account_data.get('account_id'),
                        email=account_data.get('email'),
                        access_key=account_data.get('access_key'),
                        secret_key=account_data.get('secret_key'),
                        credential_type='root',
                        regions=[selected_region]
                    )
                else:
                    print(f"❌ Invalid choice. Please enter a number between 1 and {len(root_accounts)}")
            except ValueError:
                print("❌ Please enter a valid number")

    def select_iam_credentials(self) -> CredentialInfo:
            """Handle IAM user selection with proper IAM credential files"""
            iam_accounts = self.display_iam_accounts_with_users()
    
            # Step 1: Select account
            while True:
                try:
                    choice = input(f"Select account (1-{len(iam_accounts)}): ").strip()
                    account_index = int(choice) - 1
            
                    if 0 <= account_index < len(iam_accounts):
                        selected_account = iam_accounts[account_index]
                        break
                    else:
                        print(f"❌ Invalid choice. Please enter a number between 1 and {len(iam_accounts)}")
                except ValueError:
                    print("❌ Please enter a valid number")
    
            # Step 2: Select user from the account
            users_regions = selected_account['users_regions']
            user_list = list(users_regions.items())
    
            print(f"\n👤 Select user from {selected_account['account_name']}:")
            for i, (username, region) in enumerate(user_list, 1):
                user_info = self.get_user_info(username)
                print(f"  {i}. {username} ({user_info['full_name']}) - Region: {region}")
    
            while True:
                try:
                    choice = input(f"Select user (1-{len(user_list)}): ").strip()
                    user_index = int(choice) - 1
            
                    if 0 <= user_index < len(user_list):
                        selected_username, selected_region = user_list[user_index]
                        break
                    else:
                        print(f"❌ Invalid choice. Please enter a number between 1 and {len(user_list)}")
                except ValueError:
                    print("❌ Please enter a valid number")
    
            # Step 3: Find IAM credential files for this user
            try:
                # Look for IAM credential files with pattern "iam_users_credentials_YYYYMMDD_HHMMSS"
                iam_cred_files = []
                for filename in os.listdir('./aws/iam/'):
                    if filename.startswith('iam_users_credentials_') and filename.endswith('.json'):
                        file_path = os.path.join('./aws/iam/', filename)
                        iam_cred_files.append({
                            'path': file_path,
                            'filename': filename,
                            'timestamp': os.path.getmtime(file_path)
                        })
        
                if not iam_cred_files:
                    print(f"❌ No IAM credential files found")
                    print("Please run the IAM user creation script first")
                    raise ValueError("No IAM credential files found")
        
                # Sort files by timestamp (newest first)
                sorted_files = sorted(iam_cred_files, key=lambda x: x['timestamp'], reverse=True)
        
                # Display options for credential files
                print("\n📂 IAM Credential Files Available (sorted by timestamp, newest first):")
                for i, file_info in enumerate(sorted_files, 1):
                    timestamp = datetime.fromtimestamp(file_info['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  {i}. {file_info['filename']} ({timestamp})")
        
                print("\nOptions:")
                print("  1. Use latest file (recommended)")
                print("  2. Select from list")
        
                file_choice = input("Enter choice (1-2): ").strip()
        
                selected_file = None
                if file_choice == '1' or not file_choice:
                    # Use the latest file
                    selected_file = sorted_files[0]['path']
                    print(f"✅ Using latest file: {sorted_files[0]['filename']}")
                else:
                    # Let user select file
                    while True:
                        try:
                            file_index = int(input(f"Select file (1-{len(sorted_files)}): ").strip()) - 1
                            if 0 <= file_index < len(sorted_files):
                                selected_file = sorted_files[file_index]['path']
                                print(f"✅ Selected file: {sorted_files[file_index]['filename']}")
                                break
                            else:
                                print(f"❌ Invalid choice. Please enter a number between 1 and {len(sorted_files)}")
                        except ValueError:
                            print("❌ Please enter a valid number")
        
                # Load selected IAM credential file
                with open(selected_file, 'r') as f:
                    iam_creds_data = json.load(f)
        
                # Find the credentials for the selected user
                # The structure is: {'accounts': {'account01': {'users': [{'username': '...', ...}]}}}
                account_name = selected_account['account_name']
                user_creds = None
        
                # Debug information to help trace the issue
                if 'accounts' not in iam_creds_data:
                    print(f"⚠️ 'accounts' key not found in credentials file")
                    print(f"Keys found: {list(iam_creds_data.keys())}")
                elif account_name not in iam_creds_data['accounts']:
                    print(f"⚠️ Account '{account_name}' not found in credentials file")
                    print(f"Available accounts: {list(iam_creds_data['accounts'].keys())}")
                elif 'users' not in iam_creds_data['accounts'][account_name]:
                    print(f"⚠️ 'users' not found for account '{account_name}'")
                else:
                    # Correct access pattern: accounts -> account_name -> users -> [user_list]
                    users = iam_creds_data['accounts'][account_name]['users']
                    for user in users:
                        if user['username'] == selected_username:
                            user_creds = user
                            break
        
                if not user_creds:
                    print(f"❌ Credentials for user {selected_username} not found in the selected file")
                    raise ValueError(f"Credentials for {selected_username} not found")
        
                print(f"✅ Credentials found for user {selected_username}")
        
                # Return user-specific credentials
                return CredentialInfo(
                    account_name=selected_account['account_name'],
                    account_id=selected_account['account_data'].get('account_id'),
                    email=user_creds.get('real_user', {}).get('email', selected_account['account_data'].get('email')),
                    access_key=user_creds.get('access_key_id'),  # Using actual IAM user credentials
                    secret_key=user_creds.get('secret_access_key'),  # Using actual IAM user credentials
                    credential_type='iam',
                    regions=[selected_region],
                    username=selected_username
                )
        
            except Exception as e:
                print(f"❌ Error accessing user credentials: {e}")
                raise
  
    def select_region(self, available_regions: List[str]) -> str:
        """Select region from available regions"""
        if len(available_regions) == 1:
            print(f"🌍 Using region: {available_regions[0]}")
            return available_regions[0]
        
        print("\n" + "="*50)
        print("🌍 SELECT REGION")
        print("="*50)
        
        for i, region in enumerate(available_regions, 1):
            print(f"  {i}. {region}")
        
        while True:
            try:
                choice = input(f"Select region (1-{len(available_regions)}): ").strip()
                region_index = int(choice) - 1
                
                if 0 <= region_index < len(available_regions):
                    print(available_regions[region_index])
                    return available_regions[region_index]
                else:
                    print(f"❌ Invalid choice. Please enter a number between 1 and {len(available_regions)}")
            except ValueError:
                print("❌ Please enter a valid number")
    
    def get_credentials(self) -> CredentialInfo:
        """Main method to get credentials based on user choice"""
        credential_type = self.prompt_credential_type()
        
        if credential_type == 'root':
            return self.select_root_account()
        else:
            return self.select_iam_credentials()
    
    def validate_credentials(self, cred_info: CredentialInfo) -> bool:
        """Validate credentials by making a test AWS call"""
        try:
            print(f"\n🔍 Validating {cred_info.credential_type} credentials...")

            sts_client = boto3.client(
                'sts',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=cred_info.regions[0]
            )

            identity = sts_client.get_caller_identity()
            actual_account_id = identity.get('Account')

            if actual_account_id == cred_info.account_id:
                print(f"✅ Credentials validated successfully")
                print(f"   👤 User ARN: {identity.get('Arn', 'Unknown')}")
                if cred_info.username:
                    print(f"   👥 Selected IAM User: {cred_info.username}")
                return True
            else:
                print(f"❌ Account ID mismatch!")
                print(f"   Expected: {cred_info.account_id}")
                print(f"   Actual: {actual_account_id}")
                return False

        except Exception as e:
            print(f"❌ Credential validation failed: {e}")
            return False