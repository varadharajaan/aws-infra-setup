#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from text_symbols import Symbols

class IAMUserManager:
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.load_configuration()
        self.load_user_mapping()
        self.current_time = "2025-06-01 16:56:27"
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
                print("User creation will continue without real user mapping")
                self.user_mappings = {}
                return
            
            with open(self.mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            self.user_mappings = mapping_data['user_mappings']
            
            print(f"{Symbols.OK} User mapping loaded from: {self.mapping_file}")
            print(f"👥 Found mappings for {len(self.user_mappings)} users")
            
        except json.JSONDecodeError as e:
            print(f"{Symbols.ERROR} Invalid JSON in user mapping file: {e}")
            self.user_mappings = {}
        except Exception as e:
            print(f"{Symbols.WARN}  Warning: Error loading user mapping: {e}")
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
                'email': 'unknown@bakerhughes.com',
                'full_name': 'Unknown User'
            }

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

    def check_user_exists(self, iam_client, username):
        """Check if IAM user already exists"""
        try:
            iam_client.get_user(UserName=username)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                return False
            else:
                # Re-raise other errors
                raise e

    def get_users_for_account(self, account_name):
        """Get user-region mapping for specific account"""
        regions = self.user_settings['user_regions']
        users_count = self.user_settings['users_per_account']
        
        users_regions = {}
        for i in range(1, users_count + 1):
            username = f"{account_name}_clouduser{i:02d}"
            region = regions[(i-1) % len(regions)]  # Cycle through regions
            users_regions[username] = region
            
        return users_regions

    def create_restriction_policy(self, region):
        """Create IAM policy for region and instance type restrictions"""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyIfNotInRegion",
                    "Effect": "Deny",
                    "Action": "*",
                    "Resource": "*",
                    "Condition": {
                        "StringNotEquals": {
                            "aws:RequestedRegion": region
                        }
                    }
                },
                {
                    "Sid": "DenyIfDisallowedInstanceType",
                    "Effect": "Deny",
                    "Action": [
                        "ec2:RunInstances",
                        "ec2:CreateFleet",
                        "ec2:CreateLaunchTemplate",
                        "ec2:CreateLaunchTemplateVersion"
                    ],
                    "Resource": "*",
                    "Condition": {
                        "StringNotEqualsIfExists": {
                            "ec2:InstanceType": self.user_settings['allowed_instance_types']
                        }
                    }
                }
            ]
        }


    def create_single_user(self, iam_client, username, region, account_config):
        """Create a single IAM user with all necessary configurations"""
        try:
            # 1. Create IAM User
            print("  [LOG] Creating IAM user...")
            iam_client.create_user(UserName=username)
            print(f"  {Symbols.OK} User {username} created successfully")
            
            # 2. Enable Console Access
            print("  🔐 Setting up console access...")
            iam_client.create_login_profile(
                UserName=username,
                Password=self.user_settings['password'],
                PasswordResetRequired=False
            )
            print(f"  {Symbols.OK} Console access configured")
            
            # 3. Attach AdministratorAccess Policy
            print(f"  {Symbols.KEY} Attaching AdministratorAccess policy...")
            iam_client.attach_user_policy(
                UserName=username,
                PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess"
            )
            print(f"  {Symbols.OK} AdministratorAccess policy attached")
            
            # 4. Create Restriction Policy
            print("  🚫 Creating region and instance type restriction policy...")
            restriction_policy = self.create_restriction_policy(region)
            
            iam_client.put_user_policy(
                UserName=username,
                PolicyName="Restrict-Region-And-EC2Types",
                PolicyDocument=json.dumps(restriction_policy)
            )
            print(f"  {Symbols.OK} Restriction policy applied")
            
            # 5. Create Access Key
            print(f"  {Symbols.KEY} Creating access keys...")
            response = iam_client.create_access_key(UserName=username)
            access_key = response['AccessKey']['AccessKeyId']
            secret_key = response['AccessKey']['SecretAccessKey']
            print(f"  {Symbols.OK} Access keys created")
            
            return {
                'username': username,
                'region': region,
                'access_key': access_key,
                'secret_key': secret_key,
                'console_url': f"https://{account_config['account_id']}.signin.aws.amazon.com/console"
            }
            
        except Exception as e:
            print(f"  {Symbols.ERROR} Error creating user {username}: {e}")
            raise

    def create_users_in_account(self, account_name):
        """Create users in a specific AWS account"""
        print(f"\n{Symbols.ACCOUNT} Working on Account: {account_name.upper()}")
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
        users_regions = self.get_users_for_account(account_name)
        
        created_users = []
        skipped_users = []
        failed_users = []
        
        # Check existing users first
        print(f"\n{Symbols.SCAN} Checking for existing users...")
        for username, region in users_regions.items():
            try:
                if self.check_user_exists(iam_client, username):
                    user_info = self.get_user_info(username)
                    print(f"  {Symbols.WARN}  User {username} ({user_info['full_name']}) already exists - SKIPPING")
                    skipped_users.append({
                        'username': username,
                        'region': region,
                        'reason': 'Already exists',
                        'user_info': user_info
                    })
                    continue
                else:
                    user_info = self.get_user_info(username)
                    print(f"  {Symbols.OK} User {username} ({user_info['full_name']}) does not exist - will create")
            except Exception as e:
                print(f"  {Symbols.ERROR} Error checking user {username}: {e}")
                failed_users.append(username)
                continue
        
        # Create new users
        users_to_create = {k: v for k, v in users_regions.items() 
                          if k not in [u['username'] for u in skipped_users] 
                          and k not in failed_users}
        
        if not users_to_create:
            print(f"\n{Symbols.WARN}  No new users to create in {account_name}")
            return created_users, skipped_users, failed_users
        
        print(f"\n🔨 Creating {len(users_to_create)} new users...")
        
        for username, region in users_to_create.items():
            user_info = self.get_user_info(username)
            print(f"\n🔧 Creating user: {username}")
            print(f"   👤 Real User: {user_info['full_name']} ({user_info['email']})")
            print(f"   {Symbols.REGION} Restricted to Region: {region}")
            
            try:
                user_data = self.create_single_user(iam_client, username, region, account_config)
                
                # Add account and real user information
                user_data.update({
                    'account_name': account_name,
                    'account_id': account_config['account_id'],
                    'account_email': account_config['email'],
                    'user_info': user_info
                })
                
                created_users.append(user_data)
                
                # Print credentials with real user info
                print("\n" + "[PARTY]" * 30)
                print(f"{Symbols.OK} User Created Successfully: {username}")
                print(f"👤 Real User: {user_info['full_name']}")
                print(f"📧 Real Email: {user_info['email']}")
                print(f"{Symbols.ACCOUNT} AWS Account: {account_name} ({account_config['account_id']})")
                print(f"📧 Account Email: {account_config['email']}")
                print(f"{Symbols.KEY} Access Key ID:     {user_data['access_key']}")
                print(f"🔐 Secret Access Key: {user_data['secret_key']}")
                print(f"🌐 Console Login URL: {user_data['console_url']}")
                print(f"🗝️  Password: {self.user_settings['password']}")
                print(f"🚫 Restricted to Region: {region}")
                print(f"🖥️  Allowed Instance Types: {', '.join(self.user_settings['allowed_instance_types'])}")
                print("=" * 60)
                
            except Exception as e:
                print(f"{Symbols.ERROR} Failed to create user {username}: {e}")
                failed_users.append(username)
                continue
        
        return created_users, skipped_users, failed_users

    def display_account_menu(self):
        """Display account selection menu"""
        print("\n[LIST] Available AWS Accounts:")
        for i, (account_name, config) in enumerate(self.aws_accounts.items(), 1):
            print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']}")
        
        print(f"  {len(self.aws_accounts) + 1}. All accounts")
        
        while True:
            try:
                choice = input(f"\n[#] Select account(s) to process (1-{len(self.aws_accounts) + 1}) or range (e.g., 1-3): ").strip()
                
                # Handle range input like "1-2"
                if '-' in choice:
                    try:
                        start, end = choice.split('-')
                        start_num = int(start.strip())
                        end_num = int(end.strip())
                        
                        if start_num < 1 or end_num > len(self.aws_accounts) or start_num > end_num:
                            print(f"{Symbols.ERROR} Invalid range. Please enter a range between 1 and {len(self.aws_accounts)}")
                            continue
                        
                        # Return list of account names for the range
                        account_names = list(self.aws_accounts.keys())
                        return account_names[start_num-1:end_num]
                        
                    except ValueError:
                        print("[ERROR] Invalid range format. Use format like '1-3'")
                        continue
                
                # Handle single number input
                choice_num = int(choice)
                
                if choice_num == len(self.aws_accounts) + 1:
                    return list(self.aws_accounts.keys())
                elif 1 <= choice_num <= len(self.aws_accounts):
                    return [list(self.aws_accounts.keys())[choice_num - 1]]
                else:
                    print(f"{Symbols.ERROR} Invalid choice. Please enter a number between 1 and {len(self.aws_accounts) + 1}")
            except ValueError:
                print("[ERROR] Invalid input. Please enter a number or range (e.g., 1-3).") 
                  
    def save_credentials_to_file(self, all_created_users):
        """Save user credentials to a JSON file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"iam_users_credentials.json"
            
            credentials_data = {
                "created_date": self.current_time.split()[0],
                "created_time": self.current_time.split()[1] + " UTC",
                "created_by": self.current_user,
                "total_users": len(all_created_users),
                "accounts": {}
            }
            
            # Group users by account
            for user in all_created_users:
                account_name = user['account_name']
                if account_name not in credentials_data["accounts"]:
                    credentials_data["accounts"][account_name] = {
                        "account_id": user['account_id'],
                        "account_email": user['account_email'],
                        "users": []
                    }
                
                credentials_data["accounts"][account_name]["users"].append({
                    "username": user['username'],
                    "real_user": {
                        "first_name": user['user_info']['first_name'],
                        "last_name": user['user_info']['last_name'],
                        "full_name": user['user_info']['full_name'],
                        "email": user['user_info']['email']
                    },
                    "region": user['region'],
                    "access_key_id": user['access_key'],
                    "secret_access_key": user['secret_key'],
                    "console_password": self.user_settings['password'],
                    "console_url": user['console_url']
                })
            
            with open(filename, 'w') as f:
                json.dump(credentials_data, f, indent=2)
            
            print(f"{Symbols.INSTANCE} Credentials saved to: {filename}")
            print("[WARN]  SECURITY WARNING: This file contains sensitive information. Store it securely!")
            print("[SECURE] Consider encrypting this file and deleting it after use.")
            
        except Exception as e:
            print(f"{Symbols.ERROR} Failed to save credentials to file: {e}")

    def run(self):
        """Main execution method"""
        print("[START] AWS IAM User Creation Script with Real User Mapping")
        print("=" * 70)
        print(f"{Symbols.DATE} Execution Date/Time: {self.current_time} UTC")
        print(f"👤 Executed by: {self.current_user}")
        print("=" * 70)
        
        # Select accounts to process
        accounts_to_process = self.display_account_menu()
        
        all_created_users = []
        all_skipped_users = []
        all_failed_users = []
        
        # Process selected accounts
        for account_name in accounts_to_process:
            created_users, skipped_users, failed_users = self.create_users_in_account(account_name)
            all_created_users.extend(created_users)
            all_skipped_users.extend(skipped_users)
            all_failed_users.extend(failed_users)
        
        # Overall Summary
        print("\n" + "[TARGET]" * 20 + " OVERALL SUMMARY " + "[TARGET]" * 20)
        print("=" * 80)
        print(f"{Symbols.OK} Total users successfully created: {len(all_created_users)}")
        print(f"{Symbols.WARN}  Total users skipped (already exist): {len(all_skipped_users)}")
        print(f"{Symbols.ERROR} Total users failed: {len(all_failed_users)}")
        
        if all_created_users:
            print("\n[LIST] Successfully Created Users:")
            current_account = None
            for user in all_created_users:
                if current_account != user['account_name']:
                    current_account = user['account_name']
                    print(f"\n  {Symbols.ACCOUNT} {user['account_name']} ({user['account_id']}):")
                print(f"    • {user['username']} → {user['user_info']['full_name']} ({user['user_info']['email']}) [Region: {user['region']}]")
        
        if all_skipped_users:
            print("\n[WARN]  Skipped Users (Already Exist):")
            current_account = None
            for user in all_skipped_users:
                account_name = user['username'].split('_')[0]
                if current_account != account_name:
                    current_account = account_name
                    print(f"\n  {Symbols.ACCOUNT} {account_name}:")
                print(f"    • {user['username']} → {user['user_info']['full_name']} ({user['user_info']['email']}) [Region: {user['region']}]")
        
        if all_failed_users:
            print("\n[ERROR] Failed Users:")
            for username in all_failed_users:
                print(f"  • {username}")
        
        print("\n[PARTY] Script execution completed!")
        
        # Optional: Save credentials to file
        if all_created_users:
            save_to_file = input("\n[INSTANCE] Save credentials to file? (y/N): ").lower().strip()
            if save_to_file == 'y':
                self.save_credentials_to_file(all_created_users)

def main():
    """Main function"""
    try:
        manager = IAMUserManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"{Symbols.ERROR} Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()