#!/usr/bin/env python3
"""
EKS Cluster Automation - Phase 2
Enhanced with Root/IAM credential support and multiple nodegroup strategies
Supports on-demand, spot, and mixed instance type selection with quota analysis
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set
import boto3

# Import credential manager for Root/IAM support
from aws_credential_manager import AWSCredentialManager, CredentialInfo

# Import spot analyzer for instance analysis
from spot_instance_analyzer import SpotInstanceAnalyzer, SpotAnalysis

# Import EKS manager for cluster operations
from eks_cluster_manager import EKSClusterManager

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    WHITE = '\033[1;37m'
    NC = '\033[0m'  # No Color

class EKSAutomation:
    def __init__(self):
        """Initialize the EKS Automation tool"""
        self.current_user = 'varadharajaan'
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.credential_manager = AWSCredentialManager()
        self.spot_analyzer = SpotInstanceAnalyzer()
        
        # EKS Manager will be initialized after credentials are selected
        self.eks_manager = None
        self.config_file = "ec2-region-ami-mapping.json"
        self.ami_config = self.load_ami_configuration()
        
        # Create output directory
        os.makedirs("aws/eks", exist_ok=True)
        
        # Print welcome message
        print("🚀 EKS Cluster & Nodegroup Automation - Phase 2")
        print(f"👤 User: {self.current_user}")
        print(f"🕒 Time: {self.current_time}")
        print("="*60)
        
    def load_ami_configuration(self) -> Dict:
        """Load EC2-AMI-Region mapping configuration"""
        try:
            if not os.path.exists(self.config_file):
                print(f"⚠️  Configuration file {self.config_file} not found, using defaults")
                return {
                    "eks_config": {
                        "default_version": "1.27",
                        "ami_type": "AL2_x86_64"
                    }
                }
            
            with open(self.config_file, 'r') as f:
                ami_config = json.load(f)
                
            print(f"✅ Configuration loaded from: {self.config_file}")
            return ami_config
        
        except Exception as e:
            print(f"⚠️  Error loading configuration: {e}, using defaults")
            return {
                "eks_config": {
                    "default_version": "1.27",
                    "ami_type": "AL2_x86_64"
                }
            }

    def get_eks_config(self) -> Dict:
        """Get EKS configuration from the loaded configuration"""
        # Get EKS config or use defaults
        return self.ami_config.get('eks_config', {
            "default_version": "1.27",
            "ami_type": "AL2_x86_64"
        })

    def run_automation(self):
        """Main automation flow with enhanced account and user selection"""
        try:
            # Step 1: Get credentials (Root or IAM)
            print("\n🔑 STEP 1: CREDENTIAL TYPE SELECTION")
        
            # Ask user to choose between Root or IAM credentials
            print("\n👤 USER TYPE SELECTION")
            print("=" * 60)
            print("1. Root Credentials - Use AWS account root credentials")
            print("2. IAM Credentials - Use IAM user credentials")
        
            while True:
                user_type_choice = input("\nSelect credential type (1/2): ").strip()
                if user_type_choice == '1':
                    user_type = 'root'
                    print(f"✅ Using Root credentials for cluster creation")
                    break
                elif user_type_choice == '2':
                    user_type = 'iam'
                    print(f"✅ Using IAM user credentials for cluster creation")
                    break
                else:
                    print(f"❌ Invalid choice. Please enter 1 or 2.")

            # Step 2: Process based on credential type choice
            all_selected_users = []
        
            if user_type == 'root':
                # ROOT CREDENTIALS: Get from aws_accounts_config.json
                print("\n🔑 ROOT CREDENTIALS COLLECTION FROM CONFIG")
                print("-" * 60)
            
                # Load aws_accounts_config.json
                if not os.path.exists('aws_accounts_config.json'):
                    print("❌ aws_accounts_config.json not found. Cannot proceed with root credentials.")
                    return False
            
                try:
                    with open('aws_accounts_config.json', 'r') as f:
                        root_config = json.load(f)
                        root_accounts = root_config.get('accounts', {})
                        # Get available regions from user_settings
                        available_regions = root_config.get('user_settings', {}).get('user_regions', ["us-east-1"])
                    
                    if not root_accounts:
                        print("❌ No accounts found in aws_accounts_config.json")
                        return False
                    
                    print(f"✅ Found {len(root_accounts)} accounts in config file")
                
                    # Display available accounts
                    print("\n🏦 AVAILABLE ROOT ACCOUNTS:")
                    print("-" * 60)
                    for i, (account_name, account_info) in enumerate(root_accounts.items(), 1):
                        print(f"{i}. {account_name} ({account_info.get('account_id', 'Unknown ID')})")
                        print(f"   📧 Email: {account_info.get('email', 'Not specified')}")
                        print(f"   🔑 Credentials: {'✅ Available' if 'access_key' in account_info and 'secret_key' in account_info else '❌ Missing'}")
                        print()
                
                    # Account selection options
                    print("\nAccount Selection:")
                    print("  • Single account: Enter the number (e.g., 1)")
                    print("  • Multiple accounts: Comma-separated numbers (e.g., 1,3)")
                    print("  • All accounts: 'all' or press Enter")
                    print("  • Cancel: 'cancel' or 'quit'")
                
                    # Get user's account selection
                    selection = input("\n🔢 Select accounts: ").strip().lower()
                
                    if selection in ['cancel', 'quit']:
                        print("❌ Operation cancelled")
                        return False
                
                    # Process account selection
                    selected_accounts = []
                    if not selection or selection == 'all':
                        selected_accounts = [(acct_name, acct_info) for acct_name, acct_info in root_accounts.items() 
                                             if 'access_key' in acct_info and 'secret_key' in acct_info]
                        print(f"✅ Selected all accounts with credentials: {len(selected_accounts)}")
                    else:
                        try:
                            # Handle comma-separated values
                            if ',' in selection:
                                indices = [int(idx.strip()) for idx in selection.split(',') if idx.strip()]
                            # Handle single number
                            else:
                                indices = [int(selection)]
                        
                            # Get the selected accounts
                            account_items = list(root_accounts.items())
                            for idx in indices:
                                if 1 <= idx <= len(account_items):
                                    acct_name, acct_info = account_items[idx-1]
                                    if 'access_key' in acct_info and 'secret_key' in acct_info:
                                        selected_accounts.append((acct_name, acct_info))
                                    else:
                                        print(f"⚠️ Account {acct_name} skipped - no credentials")
                                else:
                                    print(f"⚠️ Invalid index: {idx} - skipped")
                        
                            if not selected_accounts:
                                print("❌ No valid accounts selected with credentials")
                                return False
                        
                            print(f"✅ Selected {len(selected_accounts)} accounts: " + 
                                  ", ".join([acct[0] for acct in selected_accounts]))
                        except ValueError:
                            print(f"❌ Invalid selection format. Please use numbers separated by commas.")
                            return False
                
                    # Display available regions for selection
                    print("\n🌍 AVAILABLE REGIONS:")
                    print("-" * 60)
                    for i, region in enumerate(available_regions, 1):
                        print(f"{i}. {region}")
                
                    # Set default region
                    default_region = "us-east-1"
                    if default_region in available_regions:
                        default_idx = available_regions.index(default_region) + 1
                        print(f"\nDefault region: {default_region} (option {default_idx})")
                
                    # Ask user to select a region
                    region_selection = input(f"\n🔢 Select region (1-{len(available_regions)}) [default: {default_region}]: ").strip()
                
                    selected_region = default_region
                    if region_selection:
                        try:
                            region_idx = int(region_selection) - 1
                            if 0 <= region_idx < len(available_regions):
                                selected_region = available_regions[region_idx]
                            else:
                                print(f"❌ Invalid selection. Using default region: {default_region}")
                        except ValueError:
                            print(f"❌ Invalid input. Using default region: {default_region}")
                
                    print(f"✅ Using region: {selected_region}")
                    
                    # Build root user objects from selected accounts
                    print("\n⏳ Loading root user information...")
                    for acct_name, acct_info in selected_accounts:
                        # Create a user object for the root account with selected region
                        root_user = {
                            'username': f"root-{acct_name}",
                            'full_name': f"Root User ({acct_name})",
                            'role': 'root',
                            'location': 'N/A',
                            'email': acct_info.get('email', f"root@{acct_name}"),
                            'region': selected_region,  # Use the selected region
                            'access_key': acct_info['access_key'],
                            'secret_key': acct_info['secret_key'],
                            'account_id': acct_info.get('account_id', ''),
                            'account_name': acct_name
                        }
                    
                        all_selected_users.append(root_user)
                        print(f"✅ Root credentials added for {acct_name} in region {selected_region}")
                
                except Exception as e:
                    print(f"❌ Error processing root credentials: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            
            else:
                # IAM CREDENTIALS: List and select from aws/iam/iam_users_credentials_{timestamp}.json files
                print("\n🔑 IAM CREDENTIALS SELECTION")
                print("-" * 60)
            
                try:
                    # Find all IAM credential files
                    iam_cred_files = []
                    iam_dir = 'aws/iam'
                
                    if not os.path.exists(iam_dir):
                        print(f"❌ Directory {iam_dir} not found. Cannot find IAM credential files.")
                        return False
                
                    # Find all iam_users_credentials_{timestamp}.json files
                    for file in os.listdir(iam_dir):
                        if file.startswith('iam_users_credentials_') and file.endswith('.json'):
                            file_path = os.path.join(iam_dir, file)
                            timestamp_str = file.replace('iam_users_credentials_', '').replace('.json', '')
                            try:
                                # Try to parse the timestamp from the filename
                                timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                                file_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                            except:
                                # If parsing fails, use file modification time
                                file_time = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
                        
                            iam_cred_files.append({
                                'path': file_path,
                                'name': file,
                                'timestamp_str': timestamp_str,
                                'time': file_time,
                                'mtime': os.path.getmtime(file_path)
                            })
                
                    if not iam_cred_files:
                        print(f"❌ No IAM credential files found in {iam_dir}")
                        print("Run create_iam_users_logging.py first to generate credentials.")
                        return False
                
                    # Sort files by modification time (newest first)
                    iam_cred_files.sort(key=lambda x: x['mtime'], reverse=True)
                
                    # Display files
                    print("\n📂 AVAILABLE IAM CREDENTIAL FILES:")
                    print("-" * 60)
                    for i, file_info in enumerate(iam_cred_files, 1):
                        print(f"{i}. {file_info['name']}")
                        print(f"   ⏰ Created: {file_info['time']}")
                        print()
                
                    # Latest file is selected by default
                    default_file = iam_cred_files[0]
                    print(f"Latest file (default): {default_file['name']} ({default_file['time']})")
                
                    # Ask user to select a file
                    file_choice = input("\nSelect file (press Enter for latest): ").strip()
                
                    selected_file_info = None
                    if not file_choice:
                        selected_file_info = default_file
                        print(f"✅ Using default latest file: {selected_file_info['name']}")
                    else:
                        try:
                            file_idx = int(file_choice) - 1
                            if 0 <= file_idx < len(iam_cred_files):
                                selected_file_info = iam_cred_files[file_idx]
                                print(f"✅ Selected file: {selected_file_info['name']}")
                            else:
                                print(f"❌ Invalid selection. Using default latest file: {default_file['name']}")
                                selected_file_info = default_file
                        except ValueError:
                            print(f"❌ Invalid input. Using default latest file: {default_file['name']}")
                            selected_file_info = default_file
                
                    # Load selected credential file
                    with open(selected_file_info['path'], 'r') as f:
                        iam_cred_data = json.load(f)
                
                    # Display accounts in the file
                    account_data = iam_cred_data.get('accounts', {})
                    if not account_data:
                        print("❌ No account data found in the selected file")
                        return False
                
                    print(f"\n🏦 ACCOUNTS IN CREDENTIAL FILE:")
                    print("-" * 60)
                
                    for i, (acct_name, acct_info) in enumerate(account_data.items(), 1):
                        users_count = len(acct_info.get('users', []))
                        print(f"{i}. {acct_name} ({acct_info.get('account_id', 'Unknown')})")
                        print(f"   👥 Users: {users_count}")
                        print()
                
                    # Account selection options
                    print("\nAccount Selection:")
                    print("  • Single account: Enter the number (e.g., 1)")
                    print("  • Multiple accounts: Comma-separated numbers (e.g., 1,3)")
                    print("  • All accounts: 'all' or press Enter")
                    print("  • Cancel: 'cancel' or 'quit'")
                
                    # Get user's account selection
                    selection = input("\n🔢 Select accounts: ").strip().lower()
                
                    if selection in ['cancel', 'quit']:
                        print("❌ Operation cancelled")
                        return False
                
                    # Process account selection
                    selected_accounts = []
                    if not selection or selection == 'all':
                        selected_accounts = list(account_data.items())
                        print(f"✅ Selected all accounts: {len(selected_accounts)}")
                    else:
                        try:
                            # Handle comma-separated values
                            if ',' in selection:
                                indices = [int(idx.strip()) for idx in selection.split(',') if idx.strip()]
                            # Handle single number
                            else:
                                indices = [int(selection)]
                        
                            # Get the selected accounts
                            account_items = list(account_data.items())
                            for idx in indices:
                                if 1 <= idx <= len(account_items):
                                    selected_accounts.append(account_items[idx-1])
                                else:
                                    print(f"⚠️ Invalid index: {idx} - skipped")
                        
                            if not selected_accounts:
                                print("❌ No valid accounts selected")
                                return False
                        
                            print(f"✅ Selected {len(selected_accounts)} accounts: " + 
                                  ", ".join([acct[0] for acct in selected_accounts]))
                        except ValueError:
                            print(f"❌ Invalid selection format. Please use numbers separated by commas.")
                            return False
                
                    # Process each selected account - get users
                    for acct_name, acct_info in selected_accounts:
                        users = acct_info.get('users', [])
                        if not users:
                            print(f"⚠️ No users found for account: {acct_name}")
                            continue
                    
                        print(f"\n👥 USERS IN {acct_name.upper()}:")
                        print("-" * 60)
                        for i, user in enumerate(users, 1):
                            username = user.get('username', 'Unknown')
                            real_user = user.get('real_user', {})
                            full_name = real_user.get('full_name', 'Unknown User')
                            region = user.get('region', 'us-east-1')
                            print(f"{i}. {username} - {full_name} - Region: {region}")
                    
                        # User selection options
                        print("\nUser Selection Options:")
                        print("  • Single user: Enter the number (e.g., 1)")
                        print("  • Multiple users: Comma-separated numbers (e.g., 1,3,5)")
                        print("  • All users: 'all' or press Enter")
                        print("  • Skip this account: 'skip'")
                    
                        # Get user selection
                        user_selection = input(f"\n🔢 Select users from {acct_name}: ").strip().lower()
                    
                        if user_selection == 'skip':
                            print(f"⏭️ Skipping {acct_name}")
                            continue
                    
                        # Process user selection
                        selected_users = []
                        if not user_selection or user_selection == 'all':
                            selected_users = users
                            print(f"✅ Selected all {len(users)} users from {acct_name}")
                        else:
                            try:
                                # Handle comma-separated values
                                if ',' in user_selection:
                                    indices = [int(idx.strip()) for idx in user_selection.split(',') if idx.strip()]
                                # Handle single number
                                else:
                                    indices = [int(user_selection)]
                            
                                for idx in indices:
                                    if 1 <= idx <= len(users):
                                        selected_users.append(users[idx-1])
                                    else:
                                        print(f"⚠️ Invalid index: {idx} - skipped")
                            
                                if not selected_users:
                                    print(f"⚠️ No valid users selected from {acct_name}")
                                    continue
                            
                                print(f"✅ Selected {len(selected_users)} users from {acct_name}")
                            except ValueError:
                                print(f"⚠️ Invalid selection format for {acct_name} - skipped")
                                continue
                    
                        # Add selected users to master list with account information
                        for user in selected_users:
                            user_obj = {
                                'username': user.get('username', 'unknown'),
                                'full_name': user.get('real_user', {}).get('full_name', 'Unknown User'),
                                'role': 'iam',
                                'location': 'N/A',
                                'email': user.get('real_user', {}).get('email', ''),
                                'region': user.get('region', 'us-east-1'),
                                'access_key': user.get('access_key_id', ''),
                                'secret_key': user.get('secret_access_key', ''),
                                'account_id': acct_info.get('account_id', ''),
                                'account_name': acct_name
                            }
                            all_selected_users.append(user_obj)
                            print(f"✅ Added user: {user_obj['username']} - {user_obj['full_name']}")
                
                except Exception as e:
                    print(f"❌ Error processing IAM credentials: {e}")
                    import traceback
                    traceback.print_exc()
                    return False

            # Final check - make sure we have users selected
            if not all_selected_users:
                print("❌ No users selected from any account. Exiting...")
                return False
        
            print(f"\n✅ Selected {len(all_selected_users)} users across accounts")

            # Initialize EKS Manager with validated credentials and user type
            self.eks_manager = EKSClusterManager(config_file=None)
        
            # Store the user_type in the EKS manager
            self.eks_manager.user_type = user_type
        
            # Step 3: Nodegroup Configuration Prompts
            # Convert first user to CredentialInfo for configuration methods
            first_user = all_selected_users[0]
            credential_info = CredentialInfo(
                account_name=first_user['account_name'],
                account_id=first_user['account_id'],
                email=first_user['email'],
                access_key=first_user['access_key'],
                secret_key=first_user['secret_key'],
                credential_type=user_type,
                regions=[first_user['region']],
                username=first_user['username']
            )
        
            # Configure nodegroups interactively
            nodegroup_configs = self.configure_multiple_nodegroups(credential_info)
        
            # Display configuration summary
            self.display_common_nodegroup_summary(nodegroup_configs)
        
            # Confirmation
            confirmation = input("\nProceed with cluster creation using these configurations? (Y/n): ").strip().lower()
            if confirmation == 'n':
                print("❌ Operation cancelled by user")
                return False
            
            # Step 4: Get EKS configuration
            eks_config = self.get_eks_config()
            eks_version = eks_config.get('default_version', '1.28')
            ami_type = eks_config.get('ami_type', 'AL2_x86_64')
        
            # Display overall creation summary
            self.display_cluster_creation_summary(credential_info, eks_version, ami_type, nodegroup_configs)
            
            # Apply this configuration to all user selections
            for user in all_selected_users:
                user['nodegroup_configs'] = nodegroup_configs
            print("Nodegroup configs assigned to all selected users:", all_selected_users[0]['nodegroup_configs'])
    
            # Call process_multiple_user_selection with all selected users and nodegroup configs
            result = self.eks_manager.process_multiple_user_selection(all_selected_users)
    
            if result:
                print("\n✅ EKS Clusters created successfully!")
                return True
            else:
                print("\n⚠️ Some EKS Cluster creations may have failed")
                return False
    
        except Exception as e:
            print(f"\n❌ Error during automation: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def display_common_nodegroup_summary(self, nodegroup_configs: List[Dict]):
        """Display a summary of the common nodegroup configuration"""
        print("\nCommon Nodegroup Configurations:")
        print("-" * 60)
    
        for i, config in enumerate(nodegroup_configs, 1):
            print(f"{i}. {config['name']} ({config['strategy'].upper()})")
            print(f"   Scaling: Min={config['min_nodes']}, Desired={config['desired_nodes']}, Max={config['max_nodes']}")
            print(f"   Instance Types: {self.format_instance_types_summary(config['instance_selections'])}")
            print(f"   Subnet Preference: {config['subnet_preference']}")
            if i < len(nodegroup_configs):
                print()

    def configure_multiple_nodegroups(self, credentials: CredentialInfo) -> List[Dict]:
        """Configure multiple nodegroups with individual settings"""
        print("\n🏗️  NODEGROUP CONFIGURATION")
        print("=" * 60)
    
        # Ask for number of nodegroups
        while True:
            try:
                num_nodegroups = input("How many nodegroups do you want to create? (1-5) [default: 2]: ").strip()
                if not num_nodegroups:
                    num_nodegroups = 2
                else:
                    num_nodegroups = int(num_nodegroups)
            
                if 1 <= num_nodegroups <= 5:
                    break
                else:
                    print("❌ Please enter a number between 1 and 5")
            except ValueError:
                print("❌ Please enter a valid number")
    
        print(f"\n✅ Creating {num_nodegroups} nodegroup(s)")
    
        # Get allowed instance types
        allowed_instance_types = self.ami_config.get('allowed_instance_types', 
                                                     ["t3.medium", "t3.large", "m5.large", "c5.large", "c6a.large"])
    
        nodegroup_configs = []
    
        # Configure each nodegroup individually
        for i in range(num_nodegroups):
            nodegroup_num = i + 1
            print(f"\n" + "="*60)
            print(f"🔧 CONFIGURING NODEGROUP {nodegroup_num} of {num_nodegroups}")
            print("="*60)
        
            # Get nodegroup name
            default_name = f"nodegroup-{nodegroup_num}"
            nodegroup_name = input(f"Enter name for nodegroup {nodegroup_num} [default: {default_name}]: ").strip()
            if not nodegroup_name:
                nodegroup_name = default_name
        
            # Strategy selection for this nodegroup
            print(f"\n📊 Strategy Selection for {nodegroup_name}:")
            print("1. On-Demand Only (Reliable, Higher Cost)")
            print("2. Spot Only (Cost-Effective, Higher Risk)")
            print("3. Mixed Strategy (On-Demand + Spot)")
        
            while True:
                strategy_choice = input("Select strategy (1-3): ").strip()
            
                if strategy_choice == '1':
                    strategy = "on-demand"
                    break
                elif strategy_choice == '2':
                    strategy = "spot"
                    break
                elif strategy_choice == '3':
                    strategy = "mixed"
                    break
                else:
                    print("❌ Invalid choice. Please select 1, 2, or 3")
        
            print(f"✅ Strategy: {strategy.upper()}")
        
            # Instance type selection based on strategy
            instance_selections = {}
        
            if strategy == "on-demand":
                instance_selections = self.select_ondemand_instance_types_for_nodegroup(
                    credentials, allowed_instance_types, nodegroup_name
                )
            elif strategy == "spot":
                instance_selections = self.select_spot_instance_types_for_nodegroup(
                    credentials, allowed_instance_types, nodegroup_name
                )
            else:  # mixed
                instance_selections = self.select_mixed_instance_types_for_nodegroup(
                    credentials, allowed_instance_types, nodegroup_name
                )
        
            # Scaling configuration for this nodegroup
            min_nodes, desired_nodes, max_nodes = self.prompt_nodegroup_scaling_individual(
                nodegroup_name, strategy
            )
        
            # Subnet selection for this nodegroup (optional)
            subnet_preference = self.select_subnet_preference(nodegroup_name)
        
            # Add to configurations
            nodegroup_config = {
                'name': nodegroup_name,
                'strategy': strategy,
                'instance_selections': instance_selections,
                'min_nodes': min_nodes,
                'desired_nodes': desired_nodes,
                'max_nodes': max_nodes,
                'subnet_preference': subnet_preference,
                'nodegroup_number': nodegroup_num
            }
        
            nodegroup_configs.append(nodegroup_config)
        
            print(f"\n✅ Nodegroup {nodegroup_num} ({nodegroup_name}) configured successfully!")
            print(f"   Strategy: {strategy.upper()}")
            print(f"   Scaling: Min={min_nodes}, Desired={desired_nodes}, Max={max_nodes}")
            print(f"   Instance Types: {self.format_instance_types_summary(instance_selections)}")
    
        return nodegroup_configs

    def select_subnet_preference(self, nodegroup_name: str) -> str:
        """Select subnet preference for nodegroup"""
        print(f"\n🌐 SUBNET PREFERENCE for {nodegroup_name}")
        print("-" * 50)
        print("1. Auto (Use all available subnets)")
        print("2. Public subnets only")
        print("3. Private subnets only")
    
        while True:
            choice = input("Select subnet preference (1-3) [default: 1]: ").strip()
            if not choice:
                choice = '1'
        
            if choice == '1':
                return "auto"
            elif choice == '2':
                return "public"
            elif choice == '3':
                return "private"
            else:
                print("❌ Invalid choice. Please select 1, 2, or 3")

    def format_instance_types_summary(self, instance_selections: Dict) -> str:
        """Format instance types for summary display"""
        summary_parts = []
    
        if 'on-demand' in instance_selections and instance_selections['on-demand']:
            summary_parts.append(f"OnDemand: {', '.join(instance_selections['on-demand'])}")
    
        if 'spot' in instance_selections and instance_selections['spot']:
            summary_parts.append(f"Spot: {', '.join(instance_selections['spot'])}")
    
        if 'on_demand_percentage' in instance_selections:
            summary_parts.append(f"({instance_selections['on_demand_percentage']}% OnDemand)")
    
        return " | ".join(summary_parts) if summary_parts else "None"

    def display_cluster_creation_summary(self, credentials, eks_version: str, ami_type: str, nodegroup_configs: List[Dict]):
        """Display comprehensive cluster creation summary"""
        print("\n" + "="*80)
        print("📋 CLUSTER CREATION SUMMARY")
        print("="*80)
    
        print(f"Account: {credentials.account_name} ({credentials.account_id})")
        print(f"Region: {credentials.regions[0]}")
        print(f"EKS Version: {eks_version}")
        print(f"AMI Type: {ami_type}")
        print(f"Total Nodegroups: {len(nodegroup_configs)}")
    
        print("\nNodegroup Details:")
        print("-" * 60)
    
        for i, config in enumerate(nodegroup_configs, 1):
            print(f"{i}. {config['name']} ({config['strategy'].upper()})")
            print(f"   Scaling: Min={config['min_nodes']}, Desired={config['desired_nodes']}, Max={config['max_nodes']}")
            print(f"   Instance Types: {self.format_instance_types_summary(config['instance_selections'])}")
            print(f"   Subnet Preference: {config['subnet_preference']}")
            if i < len(nodegroup_configs):
                print()
    
        print("="*80)

    def select_mixed_instance_types_for_nodegroup(self, credentials: CredentialInfo, allowed_types: List[str], nodegroup_name: str) -> Dict[str, List[str]]:
        """Select instance types for specific Mixed nodegroup"""
        print(f"\n🔄 MIXED STRATEGY SELECTION for {nodegroup_name}")
        print("-" * 60)
    
        # Get On-Demand types
        print("Step 1: Select On-Demand instance types")
        ondemand_selection = self.select_ondemand_instance_types_for_nodegroup(
            credentials, allowed_types, f"{nodegroup_name}-OnDemand"
        )
    
        # Get Spot types
        print("\nStep 2: Select Spot instance types")
        spot_selection = self.select_spot_instance_types_for_nodegroup(
            credentials, allowed_types, f"{nodegroup_name}-Spot"
        )
    
        # Get On-Demand percentage
        print(f"\n⚖️ On-Demand vs Spot Percentage for {nodegroup_name}")
        print("-" * 50)
        print("Default: 50% On-Demand, 50% Spot")
    
        while True:
            try:
                percentage = input("Enter On-Demand percentage (0-100, default 50): ").strip()
                if not percentage:
                    percentage = 50
                else:
                    percentage = int(percentage)
            
                if 0 <= percentage <= 100:
                    break
                else:
                    print("❌ Please enter a value between 0 and 100")
            except ValueError:
                print("❌ Please enter a valid number")
    
        return {
            'on-demand': ondemand_selection['on-demand'],
            'spot': spot_selection['spot'],
            'on_demand_percentage': percentage
        }
    
    def select_ondemand_instance_types_for_nodegroup(self, credentials: CredentialInfo, allowed_types: List[str], nodegroup_name: str) -> Dict[str, List[str]]:
        """Select instance types for specific On-Demand nodegroup"""
        print(f"\n💰 ON-DEMAND INSTANCE SELECTION for {nodegroup_name}")
        print("-" * 60)
    
        # Ask for cache preference
        refresh_choice = input("Use cached on-demand quota data if available? (y/n): ").strip().lower()
        force_refresh = refresh_choice == 'n'
    
        if force_refresh:
            print("🔄 Invalidating cache and fetching fresh data...")
            self.invalidate_quota_cache()
    
        print("Analyzing service quotas for On-Demand instances...")
    
        # Get quota information with cache control
        quota_info = self.analyze_service_quotas_with_cache(credentials, allowed_types, force_refresh)
    
        # Display quota information
        print(f"\n📊 Service Quota Analysis for {nodegroup_name}:")
        print("-" * 50)
    
        # Sort instance types by available quota
        instance_data = []
    
        for instance_type in allowed_types:
            family = instance_type.split('.')[0]
            if family in quota_info:
                quota = quota_info[family]
                available = quota.get('available_capacity', quota.get('quota_limit', 0) - quota.get('current_usage', 0))
                used = f"{quota.get('current_usage', 0)}/{quota.get('quota_limit', 'Unknown')}"
                status = "✅ Available" if available > 0 else "❌ Limited"
            else:
                available = 0
                used = "Unknown/Unknown"
                status = "⚠️ Unknown"
        
            instance_data.append({
                'type': instance_type,
                'available': available if isinstance(available, int) else 0,
                'used': used,
                'status': status
            })
    
        # Sort by available capacity (highest first)
        sorted_instances = sorted(instance_data, key=lambda x: -x['available'])
    
        # Display all instance types with quota info
        print(f"{'#':<3} {'Type':<12} {'Available':<10} {'Used':<15} {'Status':<15}")
        print("-" * 60)
    
        for i, instance in enumerate(sorted_instances, 1):
            print(f"{i:<3} {instance['type']:<12} {instance['available']:<10} {instance['used']:<15} {instance['status']:<15}")
    
        # Choose instance types
        selected_types = self.multi_select_instance_types(
            [instance['type'] for instance in sorted_instances],
            f"On-Demand ({nodegroup_name})"
        )
    
        return {'on-demand': selected_types}

    def select_spot_instance_types_for_nodegroup(self, credentials: CredentialInfo, allowed_types: List[str], nodegroup_name: str) -> Dict[str, List[str]]:
        """Select instance types for specific Spot nodegroup"""
        print(f"\n📈 SPOT INSTANCE SELECTION for {nodegroup_name}")
        print("-" * 60)
    
        # Ask for refresh preference
        refresh_choice = input("Use cached spot data if available? (y/n): ").strip().lower()
        force_refresh = refresh_choice == 'n'
    
        if force_refresh:
            print("🔄 Invalidating spot cache and fetching fresh data...")
            self.spot_analyzer.invalidate_cache()
    
        print("Analyzing spot instances and service quotas...")
    
        # Get spot analysis
        spot_analyses = self.spot_analyzer.analyze_spot_instances(credentials, allowed_types, force_refresh)
    
        # Group by instance type and choose best AZ for each
        best_spots = {}
        for analysis in spot_analyses:
            instance_type = analysis.instance_type
            if (instance_type not in best_spots or 
                analysis.score > best_spots[instance_type].score):
                best_spots[instance_type] = analysis
    
        # Sort by score (descending)
        sorted_spots = sorted(best_spots.values(), key=lambda x: x.score, reverse=True)
    
        # Display spot analysis results
        print(f"\n📊 SPOT ANALYSIS RESULTS for {nodegroup_name}")
        print("-" * 80)
    
        print(f"{'#':<3} {'Type':<10} {'Zone':<15} {'Price':<8} {'Score':<6} {'Interrupt':<15}")
        print("-" * 80)
    
        for i, analysis in enumerate(sorted_spots, 1):
            print(f"{i:<3} {analysis.instance_type:<10} {analysis.availability_zone:<15} "
                  f"${analysis.current_price:<7.4f} {analysis.score:<6.1f} "
                  f"{analysis.interruption_rate}")
    
        # Choose instance types
        selected_types = self.multi_select_instance_types(
            [analysis.instance_type for analysis in sorted_spots],
            f"Spot ({nodegroup_name})"
        )
    
        return {'spot': selected_types}

    def select_mixed_instance_types_for_nodegroup(self, credentials: CredentialInfo, allowed_types: List[str], nodegroup_name: str) -> Dict[str, List[str]]:
        """Select instance types for specific Mixed nodegroup"""
        print(f"\n🔄 MIXED STRATEGY SELECTION for {nodegroup_name}")
        print("-" * 60)
    
        # Get On-Demand types
        print("Step 1: Select On-Demand instance types")
        ondemand_selection = self.select_ondemand_instance_types_for_nodegroup(
            credentials, allowed_types, f"{nodegroup_name}-OnDemand"
        )
    
        # Get Spot types
        print("\nStep 2: Select Spot instance types")
        spot_selection = self.select_spot_instance_types_for_nodegroup(
            credentials, allowed_types, f"{nodegroup_name}-Spot"
        )
    
        # Get On-Demand percentage
        print(f"\n⚖️ On-Demand vs Spot Percentage for {nodegroup_name}")
        print("-" * 50)
        print("Default: 50% On-Demand, 50% Spot")
    
        while True:
            try:
                percentage = input("Enter On-Demand percentage (0-100, default 50): ").strip()
                if not percentage:
                    percentage = 50
                else:
                    percentage = int(percentage)
            
                if 0 <= percentage <= 100:
                    break
                else:
                    print("❌ Please enter a value between 0 and 100")
            except ValueError:
                print("❌ Please enter a valid number")
    
        return {
            'on-demand': ondemand_selection['on-demand'],
            'spot': spot_selection['spot'],
            'on_demand_percentage': percentage
        }

    def prompt_nodegroup_scaling_individual(self, nodegroup_name: str, strategy: str) -> Tuple[int, int, int]:
        """Prompt user for individual nodegroup scaling configuration"""
        print(f"\n📊 SCALING CONFIGURATION for {nodegroup_name}")
        print("-" * 60)
    
        # Default values based on strategy
        if strategy == "spot":
            default_min = 1
            default_desired = 2
            default_max = 5
        else:
            default_min = 1
            default_desired = 2
            default_max = 4
    
        print(f"Default scaling for {strategy.upper()} strategy:")
        print(f"  Min: {default_min}")
        print(f"  Desired: {default_desired}")
        print(f"  Max: {default_max}")
    
        use_defaults = input(f"\nUse default scaling values for {nodegroup_name}? (y/n): ").strip().lower()
        if use_defaults == 'y':
            return default_min, default_desired, default_max
    
        # Custom scaling values
        while True:
            try:
                min_nodes = int(input(f"Minimum nodes for {nodegroup_name} (default {default_min}): ").strip() or default_min)
                if min_nodes < 0:
                    print("❌ Minimum nodes must be >= 0")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
    
        while True:
            try:
                desired_nodes = int(input(f"Desired nodes for {nodegroup_name} (default {default_desired}): ").strip() or default_desired)
                if desired_nodes < min_nodes:
                    print(f"❌ Desired nodes must be >= minimum nodes ({min_nodes})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
    
        while True:
            try:
                max_nodes = int(input(f"Maximum nodes for {nodegroup_name} (default {default_max}): ").strip() or default_max)
                if max_nodes < desired_nodes:
                    print(f"❌ Maximum nodes must be >= desired nodes ({desired_nodes})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
    
        return min_nodes, desired_nodes, max_nodes

    def select_ondemand_instance_types(self, credentials: CredentialInfo, allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for On-Demand nodegroup with caching support"""
        region = credentials.regions[0]
    
        print("\n💰 ON-DEMAND INSTANCE TYPE SELECTION")
        print("-" * 60)
    
        # Ask for cache preference
        refresh_choice = input("Use cached on-demand quota data if available? (y/n): ").strip().lower()
        force_refresh = refresh_choice == 'n'
    
        if force_refresh:
            print("🔄 Invalidating cache and fetching fresh data...")
            self.invalidate_quota_cache()
    
        print("Analyzing service quotas for On-Demand instances...")
    
        # Get quota information with cache control
        quota_info = self.analyze_service_quotas_with_cache(credentials, allowed_types, force_refresh)
    
        # Display quota information
        print("\n📊 Service Quota Analysis:")
        print("-" * 50)
    
        # Sort instance types by available quota
        instance_data = []
    
        for instance_type in allowed_types:
            family = instance_type.split('.')[0]
            if family in quota_info:
                quota = quota_info[family]
                available = quota.get('available_capacity', quota.get('quota_limit', 0) - quota.get('current_usage', 0))
                used = f"{quota.get('current_usage', 0)}/{quota.get('quota_limit', 'Unknown')}"
                status = "✅ Available" if available > 0 else "❌ Limited"
            else:
                available = 0
                used = "Unknown/Unknown"
                status = "⚠️ Unknown"
        
            instance_data.append({
                'type': instance_type,
                'available': available if isinstance(available, int) else 0,
                'used': used,
                'status': status
            })
    
        # Sort by available capacity (highest first)
        sorted_instances = sorted(instance_data, key=lambda x: -x['available'])
    
        # Display all instance types with quota info
        print(f"{'#':<3} {'Type':<12} {'Available':<10} {'Used':<15} {'Status':<15}")
        print("-" * 60)
    
        for i, instance in enumerate(sorted_instances, 1):
            print(f"{i:<3} {instance['type']:<12} {instance['available']:<10} {instance['used']:<15} {instance['status']:<15}")
    
        # Choose instance types
        selected_types = self.multi_select_instance_types(
            [instance['type'] for instance in sorted_instances],
            "On-Demand"
        )
    
        return {'on-demand': selected_types}

    def analyze_service_quotas_with_cache(self, credentials: CredentialInfo, instance_types: List[str], force_refresh: bool = False) -> Dict:
        """Analyze service quotas with caching support"""
        import pickle
        import os
        from datetime import datetime, timedelta
    
        region = credentials.regions[0]
        cache_file = f"quota_cache_{region}_{credentials.account_id}.pkl"
        cache_duration = timedelta(hours=1)  # Cache for 1 hour
    
        # Check if cache exists and is valid
        if not force_refresh and os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
            
                cache_time = cache_data.get('timestamp')
                if cache_time and datetime.now() - cache_time < cache_duration:
                    print(f"📁 Using cached quota data from {cache_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    return cache_data.get('quota_info', {})
            except Exception as e:
                print(f"⚠️ Cache read error: {e}")
    
        # Fetch fresh data
        print("🔍 Fetching fresh service quota data...")
        quota_info = self.fetch_service_quotas(credentials, instance_types)
        # NEW: Run diagnostic to see all running instances
        print("\n🔍 Running instance diagnostic to verify detection...")
        # Ensure analyzer has credentials and session before running diagnostic
        self.spot_analyzer.set_credentials(credentials)
        self.spot_analyzer.diagnose_running_instances()

        # Save to cache
        try:
            cache_data = {
                'timestamp': datetime.now(),
                'quota_info': quota_info
            }
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            print(f"💾 Quota data cached for future use")
        except Exception as e:
            print(f"⚠️ Cache write error: {e}")
    
        return quota_info

    def fetch_service_quotas(self, credentials: CredentialInfo, instance_types: List[str]) -> Dict:
        """Fetch EC2 service quotas with proper error handling and retry logic"""
        quotas = {}
        region = credentials.regions[0]
    
        # Create AWS session with provided credentials
        session = boto3.Session(
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            region_name=region
        )
    
        client = session.client('service-quotas')
        ec2_client = session.client('ec2')
    
        # Define correct service code
        service_code = 'ec2'
    
        # Define quota code mappings for instance families
        quota_code_mappings = {
            'standard': 'L-1216C47A',     # Standard (A, C, D, H, I, M, R, T, Z) instances
            'f': 'L-74FC7D96',            # F instances
            'g': 'L-DB2E81BA',            # G instances
            'p': 'L-417A185B',            # P instances
            'x': 'L-7295265B',            # X instances
            'inf': 'L-1F1C9089',          # Inf instances
            'high-memory': 'L-44C546A5'   # High Memory instances
        }
    
        # Dictionary to track current usage by family
        usage = {}
    
        # Get current usage
        try:
            print("🔍 Analyzing current instance usage...")
            instances = []
        
            # Use paginator to handle larger number of instances
            paginator = ec2_client.get_paginator('describe_instances')
            for page in paginator.paginate(
                Filters=[{'Name': 'instance-state-name', 'Values': ['pending', 'running']}]
            ):
                for reservation in page['Reservations']:
                    instances.extend(reservation['Instances'])
        
            # Calculate vCPU usage by instance family
            family_usage = {'standard': 0}
        
            # vCPU mapping for common instance types
            vcpu_mapping = {
                'c6a.large': 2, 'c6i.large': 2, 'm6a.large': 2, 'm6i.large': 2, 'c5.large': 2, 'm5.large': 2,
                't2.micro': 2, 't2.small': 2, 't2.medium': 2, 't2.large': 2,
                't3.micro': 2, 't3.small': 2, 't3.medium': 2, 't3.large': 2,
                't3a.micro': 2, 't3a.small': 2, 't3a.medium': 2, 't3a.large': 2,
                't4g.micro': 2, 't4g.small': 2, 't4g.medium': 2, 't4g.large': 2
            }
        
            # Count instances by family
            for instance in instances:
                instance_type = instance['InstanceType']
                family = instance_type.split('.')[0]
            
                # Get vCPU count (default to 2 if unknown)
                vcpu_count = vcpu_mapping.get(instance_type, 2)
            
                # Add to specific family or standard bucket
                if family in ['f', 'g', 'p', 'x', 'inf']:
                    family_usage[family] = family_usage.get(family, 0) + vcpu_count
                else:
                    # Most instance types fall under 'standard'
                    family_usage['standard'] = family_usage.get('standard', 0) + vcpu_count
        
            # Store usage info
            usage = family_usage
            print(f"📊 Current vCPU usage: {usage}")
        
        except Exception as e:
            print(f"⚠️ Error analyzing instance usage: {str(e)}")
            usage = {'standard': 0}  # Default to zero usage if we can't fetch it
    
        # Fetch quotas for each family
        quota_results = {}
        for instance_family, quota_code in quota_code_mappings.items():
            try:
                print(f"🔍 Fetching quota for {instance_family} family...")
                response = client.get_service_quota(
                    ServiceCode=service_code,
                    QuotaCode=quota_code
                )
            
                quota_limit = response['Quota']['Value']
                current_usage = usage.get(instance_family, 0)
                available_capacity = quota_limit - current_usage
            
                quota_results[instance_family] = {
                    'quota_limit': quota_limit,
                    'current_usage': current_usage,
                    'available_capacity': available_capacity
                }
            
                print(f"✅ {instance_family}: Limit={quota_limit}, Used={current_usage}, Available={available_capacity}")
            
            except client.exceptions.NoSuchResourceException:
                print(f"⚠️ No quota found for {instance_family} with code {quota_code}")
                # Use a default value as fallback (66 vCPUs is common default)
                DEFAULT_QUOTA = 66.0
                quota_results[instance_family] = {
                    'quota_limit': DEFAULT_QUOTA,
                    'current_usage': usage.get(instance_family, 0),
                    'available_capacity': DEFAULT_QUOTA - usage.get(instance_family, 0)
                }
            
            except Exception as e:
                print(f"⚠️ Error fetching quota for {instance_family}: {str(e)}")
                # Use a default value as fallback (66 vCPUs is common default)
                DEFAULT_QUOTA = 66.0
                quota_results[instance_family] = {
                    'quota_limit': DEFAULT_QUOTA,
                    'current_usage': usage.get(instance_family, 0),
                    'available_capacity': DEFAULT_QUOTA - usage.get(instance_family, 0)
                }
    
        # Debug: Print all quota results
        print("\n✅ Quota information fetched for all families:")
        for family, values in quota_results.items():
            print(f"   {family}: Limit={values['quota_limit']}, Used={values['current_usage']}, Available={values['available_capacity']}")
    
        # Map specific instance types to their families
        instance_quotas = {}
        for instance_type in instance_types:
            family = instance_type.split('.')[0]
        
            # Map instance family to quota category
            if family in ['t2', 't3', 't3a', 't4g', 'm5', 'm6a', 'm6i', 'c5', 'c6a', 'c6i', 'r5', 'r6a', 'r6i']:
                quota_family = 'standard'
            elif family.startswith('f'):
                quota_family = 'f'
            elif family.startswith('g'):
                quota_family = 'g'
            elif family.startswith('p'):
                quota_family = 'p'
            elif family.startswith('x'):
                quota_family = 'x'
            elif family.startswith('inf'):
                quota_family = 'inf'
            else:
                quota_family = 'standard'  # Default to standard for unknown types
        
            instance_quotas[family] = quota_results.get(quota_family, {
                'quota_limit': 66.0,  # Default quota (common AWS default)
                'current_usage': 0,
                'available_capacity': 66.0
            })

            # FIX: Make sure available_capacity is properly calculated and never negative
            instance_quotas[family]['available_capacity'] = max(0, instance_quotas[family]['quota_limit'] - instance_quotas[family]['current_usage'])
    
        return instance_quotas   
    def get_ondemand_instance_quotas(self):
        """Get on-demand instance quotas with correct quota codes"""
        # These are the correct quota codes for vCPU limits by instance family
        quota_code_mappings = {
            'standard': 'L-1216C47A',     # Standard (A, C, D, H, I, M, R, T, Z) instances
            'f': 'L-74FC7D96',            # F instances
            'g': 'L-DB2E81BA',            # G instances
            'p': 'L-417A185B',            # P instances
            'x': 'L-7295265B',            # X instances
            'inf': 'L-1F1C9089',          # Inf instances
            'high-memory': 'L-44C546A5'   # High Memory instances
        }
    
        try:
            # Use the proper function to fetch quotas
            quotas = self.fetch_service_quotas(quota_code_mappings)
        
            # Most instance types fall under 'standard' category
            standard_types = ['c6a', 'c6i', 'm6a', 'm6i', 't3', 't3a']
            for instance_type in standard_types:
                if instance_type not in quotas:
                    quotas[instance_type] = quotas.get('standard', 5.0)
        
            return quotas
    
        except Exception as e:
            self.log_operation('ERROR', f"Error getting on-demand quotas: {str(e)}")
            return {'standard': 5.0}  # Default fallback

    def calculate_actual_usage(self):
        """Calculate actual instance usage across all EC2 instances"""
        try:
            ec2_client = self.session.client('ec2')
            instances = []
        
            # Use paginator to handle large number of instances
            paginator = ec2_client.get_paginator('describe_instances')
            for page in paginator.paginate(
                Filters=[{'Name': 'instance-state-name', 'Values': ['pending', 'running']}]
            ):
                for reservation in page['Reservations']:
                    instances.extend(reservation['Instances'])
        
            # Calculate vCPU usage by instance family
            usage = {family: 0 for family in ['c6a', 'c6i', 'm6a', 'm6i', 't3', 't3a', 'standard']}
        
            # Instance type to vCPU mapping
            vcpu_mapping = {
                'c6a.large': 2,
                'c6i.large': 2,
                'm6a.large': 2,
                'm6i.large': 2,
                't3.micro': 2,
                't3.small': 2,
                't3.medium': 2,
                't3.large': 2,
                't3a.micro': 2,
                't3a.small': 2,
                't3a.medium': 2,
                't3a.large': 2
                # Add more mappings as needed
            }
        
            for instance in instances:
                instance_type = instance['InstanceType']
                instance_family = instance_type.split('.')[0]
            
                # Get vCPU count for this instance type
                vcpu_count = vcpu_mapping.get(instance_type, 2)
            
                # Add to specific family count
                if instance_family in usage:
                    usage[instance_family] += vcpu_count
                else:
                    # If not a specific tracked family, add to standard
                    usage['standard'] += vcpu_count
        
            self.log_operation('INFO', f"Current instance usage (vCPUs): {usage}")
            return usage
        
        except Exception as e:
            self.log_operation('ERROR', f"Error calculating instance usage: {str(e)}")
            return {family: 0 for family in ['c6a', 'c6i', 'm6a', 'm6i', 't3', 't3a', 'standard']}

    def invalidate_quota_cache(self):
        """Invalidate all quota cache files"""
        import glob
        import os
    
        cache_files = glob.glob("quota_cache_*.pkl")
        for cache_file in cache_files:
            try:
                os.remove(cache_file)
                print(f"🗑️ Removed cache file: {cache_file}")
            except Exception as e:
                print(f"⚠️ Error removing cache file {cache_file}: {e}")    

    def select_spot_instance_types(self, credentials: CredentialInfo, allowed_types: List[str]) -> Dict[str, List[str]]:
            """Select instance types for Spot nodegroup with analysis"""
            print("\n📈 SPOT INSTANCE TYPE SELECTION")
            print("-" * 60)
        
            # Ask for refresh preference
            refresh_choice = input("Use cached spot data if available? (y/n): ").strip().lower()
            force_refresh = refresh_choice == 'n'
        
            print("Analyzing spot instances and service quotas...")
        
            # Get spot analysis
            spot_analyses = self.spot_analyzer.analyze_spot_instances(credentials, allowed_types, force_refresh)
        
            # Group by instance type and choose best AZ for each
            best_spots = {}
            for analysis in spot_analyses:
                instance_type = analysis.instance_type
                if (instance_type not in best_spots or 
                    analysis.score > best_spots[instance_type].score):
                    best_spots[instance_type] = analysis
        
            # Sort by score (descending)
            sorted_spots = sorted(best_spots.values(), key=lambda x: x.score, reverse=True)
        
            # Display spot analysis results
            print("\n📊 SPOT INSTANCE ANALYSIS RESULTS")
            print("-" * 80)
        
            print(f"{'#':<3} {'Type':<10} {'Zone':<15} {'Price':<8} {'Score':<6} {'Interrupt':<15}")
            print("-" * 80)
        
            for i, analysis in enumerate(sorted_spots, 1):
                print(f"{i:<3} {analysis.instance_type:<10} {analysis.availability_zone:<15} "
                        f"${analysis.current_price:<7.4f} {analysis.score:<6.1f} "
                        f"{analysis.interruption_rate}")
        
            # Choose instance types
            selected_types = self.multi_select_instance_types(
                [analysis.instance_type for analysis in sorted_spots],
                "Spot"
            )
        
            return {'spot': selected_types}
    
    def select_mixed_instance_types(self, credentials: CredentialInfo, allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for Mixed nodegroup strategy"""
        print("\n🔄 MIXED STRATEGY INSTANCE TYPE SELECTION")
        print("-" * 60)
        
        # Get On-Demand types
        print("Step 1: Select On-Demand instance types")
        ondemand_selection = self.select_ondemand_instance_types(credentials, allowed_types)
        
        # Get Spot types
        print("\nStep 2: Select Spot instance types")
        spot_selection = self.select_spot_instance_types(credentials, allowed_types)
        
        # Get On-Demand percentage
        print("\n⚖️ On-Demand vs Spot Percentage")
        print("-" * 50)
        print("Default: 50% On-Demand, 50% Spot")
        
        while True:
            try:
                percentage = input("Enter On-Demand percentage (0-100, default 50): ").strip()
                if not percentage:
                    percentage = 50
                else:
                    percentage = int(percentage)
                
                if 0 <= percentage <= 100:
                    break
                else:
                    print("❌ Please enter a value between 0 and 100")
            except ValueError:
                print("❌ Please enter a valid number")
        
        return {
            'on-demand': ondemand_selection['on-demand'],
            'spot': spot_selection['spot'],
            'on_demand_percentage': percentage
        }
    
    def multi_select_instance_types(self, available_types: List[str], strategy_name: str) -> List[str]:
        """Allow user to select multiple instance types"""
        if not available_types:
            print(f"⚠️ No {strategy_name} instance types available")
            return []
            
        print(f"\n📝 Select {strategy_name} Instance Types:")
        print("You can select multiple types for better availability")
        print("-" * 50)
        
        for i, instance_type in enumerate(available_types, 1):
            print(f"  {i:2}. {instance_type}")
        
        print("\nSelection format:")
        print("  Single: 1")
        print("  Multiple: 1,3,5")
        print("  Range: 1-4")
        print("  Combined: 1,3,5-8")
        print("  All: 'all'")
        
        while True:
            try:
                selection = input(f"Select {strategy_name} instance types: ").strip()
                
                if selection.lower() == 'all':
                    selected_types = available_types
                    print(f"✅ Selected all {len(selected_types)} {strategy_name} types")
                    return selected_types
                    
                selected_indices = self.parse_selection(selection, len(available_types))
                
                if selected_indices:
                    selected_types = [available_types[i-1] for i in selected_indices]
                    print(f"✅ Selected {strategy_name} types: {', '.join(selected_types)}")
                    return selected_types
                else:
                    print("❌ No valid selection made")
            except ValueError as e:
                print(f"❌ {e}")
    
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
    
    def prompt_nodegroup_scaling(self, strategy: str) -> Tuple[int, int, int]:
        """Prompt user for nodegroup scaling configuration"""
        print("\n📊 NODEGROUP SCALING CONFIGURATION")
        print("-" * 60)
        
        # Default values based on strategy
        if strategy == "spot":
            default_min = 2
            default_desired = 2
            default_max = 6
        else:
            default_min = 2
            default_desired = 2
            default_max = 6
        
        print(f"Default scaling for {strategy.upper()} strategy:")
        print(f"  Min: {default_min}")
        print(f"  Desired: {default_desired}")
        print(f"  Max: {default_max}")
        
        use_defaults = input("\nUse default scaling values? (y/n): ").strip().lower()
        if use_defaults == 'y':
            return default_min, default_desired, default_max
        
        # Custom scaling values
        while True:
            try:
                min_nodes = int(input(f"Minimum nodes (default {default_min}): ").strip() or default_min)
                if min_nodes < 0:
                    print("❌ Minimum nodes must be >= 0")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        while True:
            try:
                desired_nodes = int(input(f"Desired nodes (default {default_desired}): ").strip() or default_desired)
                if desired_nodes < min_nodes:
                    print(f"❌ Desired nodes must be >= minimum nodes ({min_nodes})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        while True:
            try:
                max_nodes = int(input(f"Maximum nodes (default {default_max}): ").strip() or default_max)
                if max_nodes < desired_nodes:
                    print(f"❌ Maximum nodes must be >= desired nodes ({desired_nodes})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        return min_nodes, desired_nodes, max_nodes

    def log_operation(self, level: str, message: str):
        """Basic logger for EKSClusterManager"""
        print(f"[{level}] {message}")

    def print_colored(self, color: str, message: str) -> None:
        """Print colored message to terminal"""
        print(f"{color}{message}{Colors.NC}")

def main():
    """Main entry point"""
    automation = EKSAutomation()
    
    try:
        success = automation.run_automation()
        if success:
            print("\n🎉 EKS Cluster creation completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ EKS Cluster creation failed or was interrupted")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⏹️ Automation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()