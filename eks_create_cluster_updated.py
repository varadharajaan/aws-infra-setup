# Databricks notebook source
#!/usr/bin/env python3
"""
Interactive EKS Cluster Manager - Updated Version
Author: varadharajaan
Date: 2025-06-02
Description: Interactive tool to create EKS clusters using admin credentials and configure user access
"""

import json
import os
import sys
import time
import boto3
import glob
import re
from datetime import datetime
from typing import Dict, List, Tuple
import yaml
import subprocess
import json
import os
from typing import List, Tuple, Set

# Import your existing logging module
try:
    from logger import setup_logger
    logger = setup_logger('eks_manager', 'cluster_management')
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('eks_manager')

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

class EKSClusterManager:
    """Main class for managing EKS clusters across multiple AWS accounts"""
    
    def __init__(self, config_file: str = None):
        """
        Initialize the EKS Cluster Manager
        
        Args:
            config_file (str): Path to the AWS accounts configuration file (optional)
        """
        self.config_file = config_file or self.find_latest_credentials_file()
        self.admin_config_file = "aws_accounts_config.json"
        self.config_data = None
        self.admin_config_data = None
        self.selected_clusters = []
        self.kubectl_commands = []
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"Initializing EKS Cluster Manager with config: {self.config_file}")
        self.load_configuration()
        self.load_admin_configuration()
        self.setup_detailed_logging()
    
    def find_latest_credentials_file(self) -> str:
        """Find the latest iam_users_credentials_timestamp file"""
        pattern = "iam_users_credentials_*.json"
        files = glob.glob(pattern)
        
        if not files:
            logger.error("No iam_users_credentials_*.json file found!")
            self.print_colored(Colors.RED, "❌ No iam_users_credentials_*.json file found!")
            # Fallback to default config file
            return "aws-accounts-config.json"
        
        self.print_colored(Colors.BLUE, f"🔍 Found {len(files)} iam_users_credentials files:")
        
        # Sort by timestamp in filename
        file_timestamps = []
        for file_path in files:
            # Match pattern: iam_users_credentials_YYYYMMDD_HHMMSS.json
            match = re.search(r'iam_users_credentials_(\d{8}_\d{6})\.json', file_path)
            if match:
                timestamp_str = match.group(1)
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    file_timestamps.append((file_path, timestamp, timestamp_str))
                    
                    # Display file info
                    file_size = os.path.getsize(file_path)
                    file_size_mb = file_size / (1024 * 1024)
                    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    print(f"   📄 {file_path} - {formatted_time} UTC ({file_size_mb:.2f} MB)")
                    
                except ValueError:
                    print(f"   ⚠️  Invalid timestamp format in: {file_path}")
                    continue
            else:
                print(f"   ⚠️  Invalid filename format: {file_path}")
        
        if not file_timestamps:
            logger.error("No valid iam_users_credentials files found with proper timestamp format!")
            self.print_colored(Colors.RED, "❌ No valid iam_users_credentials files found with proper timestamp format!")
            return "aws-accounts-config.json"
        
        # Sort by timestamp (newest first)
        file_timestamps.sort(key=lambda x: x[1], reverse=True)
        latest_file = file_timestamps[0][0]
        latest_timestamp = file_timestamps[0][2]
        latest_datetime = file_timestamps[0][1]
        
        self.print_colored(Colors.GREEN, f"✅ Selected latest file: {latest_file}")
        print(f"   📅 File timestamp: {latest_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   🆕 This is the most recent credentials file available")
        
        logger.info(f"Selected latest credentials file: {latest_file} (timestamp: {latest_timestamp})")
        return latest_file
    
    def load_admin_configuration(self) -> None:
        """Load admin AWS accounts configuration from JSON file"""
        try:
            if not os.path.exists(self.admin_config_file):
                logger.error(f"Admin configuration file {self.admin_config_file} not found!")
                raise FileNotFoundError(f"Admin configuration file {self.admin_config_file} not found!")
            
            with open(self.admin_config_file, 'r') as file:
                self.admin_config_data = json.load(file)
            
            total_admin_accounts = len(self.admin_config_data.get('accounts', {}))
            logger.info(f"Successfully loaded admin configuration with {total_admin_accounts} admin accounts")
            self.print_colored(Colors.GREEN, f"✅ Loaded admin configuration with {total_admin_accounts} admin accounts from {self.admin_config_file}")
        
        except Exception as e:
            logger.error(f"Failed to load admin configuration: {str(e)}")
            raise
    
    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"eks_creation_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('eks_operations')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler (reduced verbosity)
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)  # Only show warnings and errors on console
            
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
            self.operation_logger.info("=" * 80)
            self.operation_logger.info("EKS Cluster Creation Session Started")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Credentials File: {self.config_file}")
            self.operation_logger.info(f"Admin Config File: {self.admin_config_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 80)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Log operation to file only (reduced console output)"""
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
            # Only print errors and warnings to console
            if level.upper() in ['ERROR', 'WARNING']:
                print(f"[{level.upper()}] {message}")
    
    def print_colored(self, color: str, message: str) -> None:
        """Print colored message to terminal"""
        print(f"{color}{message}{Colors.NC}")
    
    def load_configuration(self) -> None:
        """Load AWS accounts configuration from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                logger.error(f"Configuration file {self.config_file} not found!")
                raise FileNotFoundError(f"Configuration file {self.config_file} not found!")
            
            with open(self.config_file, 'r') as file:
                self.config_data = json.load(file)
            
            total_users = self.config_data.get('total_users', 0)
            if total_users == 0:
                # Try to count users from accounts
                total_users = sum(len(account['users']) for account in self.config_data.get('accounts', {}).values())
            
            logger.info(f"Successfully loaded configuration with {total_users} users")
            self.print_colored(Colors.GREEN, f"✅ Loaded configuration with {total_users} users from {self.config_file}")
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            raise
    
    def get_admin_credentials_for_account(self, account_key: str) -> Tuple[str, str]:
        """Get admin credentials for a specific account"""
        if account_key not in self.admin_config_data['accounts']:
            raise ValueError(f"Admin credentials not found for account: {account_key}")
        
        admin_account = self.admin_config_data['accounts'][account_key]
        access_key = admin_account.get('access_key')
        secret_key = admin_account.get('secret_key')
        
        if not access_key or not secret_key:
            raise ValueError(f"Invalid admin credentials for account: {account_key}")
        
        self.log_operation('INFO', f"Retrieved admin credentials for account: {account_key}")
        return access_key, secret_key
    
    def generate_cluster_name(self, username: str, region: str) -> str:
        """Generate EKS cluster name with random 4-letter suffix"""
        import random
        import string
        
        # Generate 4 random lowercase letters
        random_suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
        
        return f"eks-cluster-{username}-{region}-{random_suffix}"
    
    def generate_nodegroup_name(self, cluster_name: str) -> str:
        """Generate node group name"""
        return f"{cluster_name}-nodegroup"
    
    def display_accounts_menu(self):
        """Display available accounts and return account selection"""
        if 'accounts' not in self.config_data:
            logger.error("No accounts found in credentials data")
            return []
        
        accounts = list(self.config_data['accounts'].items())
        
        self.log_operation('INFO', f"Displaying {len(accounts)} available accounts for selection")
        
        print(f"\n🏦 Available AWS Accounts ({len(accounts)} total):")
        print("=" * 80)
        
        total_users = 0
        regions_used = set()
        
        for i, (account_name, account_data) in enumerate(accounts, 1):
            user_count = len(account_data.get('users', []))
            total_users += user_count
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            # Check if admin credentials exist for this account
            admin_available = account_name in self.admin_config_data.get('accounts', {})
            admin_status = "✅" if admin_available else "❌"
            
            # Collect regions used in this account
            account_regions = set()
            for user in account_data.get('users', []):
                region = user.get('region', 'unknown')
                account_regions.add(region)
                regions_used.add(region)
            
            print(f"  {i:2}. {account_name}")
            print(f"      📧 Email: {account_email}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      👥 Users: {user_count}")
            print(f"      🌍 Regions: {', '.join(sorted(account_regions))}")
            print(f"      🔑 Admin Creds: {admin_status}")
            
            self.log_operation('INFO', f"Account {i}: {account_name} ({account_id}) - {user_count} users, admin creds: {admin_available}")
            print()
        
        print("=" * 80)
        print(f"📊 Summary:")
        print(f"   📈 Total accounts: {len(accounts)}")
        print(f"   👥 Total users: {total_users}")
        print(f"   🌍 All regions: {', '.join(sorted(regions_used))}")
        
        self.log_operation('INFO', f"Account summary: {len(accounts)} accounts, {total_users} total users, regions: {', '.join(sorted(regions_used))}")
        
        print(f"\n📝 Selection Options:")
        print(f"   • Single accounts: 1,3,5")
        print(f"   • Ranges: 1-{len(accounts)} (accounts 1 through {len(accounts)})")
        print(f"   • Mixed: 1-2,4 (accounts 1, 2, and 4)")
        print(f"   • All accounts: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select accounts to process: ").strip()
            
            self.log_operation('INFO', f"User input for account selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all accounts")
                return list(range(1, len(accounts) + 1))
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled account selection")
                return []
            
            try:
                selected_indices = self.parse_selection(selection, len(accounts))
                if selected_indices:
                    # Validate admin credentials for selected accounts
                    selected_accounts = []
                    missing_admin_creds = []
                    
                    for idx in selected_indices:
                        account_name, account_data = accounts[idx - 1]
                        if account_name not in self.admin_config_data.get('accounts', {}):
                            missing_admin_creds.append(account_name)
                        else:
                            selected_accounts.append((account_name, account_data))
                    
                    if missing_admin_creds:
                        print(f"\n❌ Missing admin credentials for accounts: {', '.join(missing_admin_creds)}")
                        print("Please ensure admin credentials are available in aws_accounts_config.json")
                        continue
                    
                    # Show confirmation
                    print(f"\n✅ Selected {len(selected_indices)} accounts with admin credentials available")
                    confirm = input(f"\n🚀 Proceed with these {len(selected_indices)} accounts? (y/N): ").lower().strip()
                    
                    if confirm == 'y':
                        return selected_indices
                    else:
                        print("❌ Selection cancelled, please choose again.")
                        continue
                else:
                    print("❌ No valid accounts selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                continue

    def parse_selection(self, selection, max_items):
        """Parse selection string and return list of indices"""
        selected_indices = set()
        
        # Split by comma and process each part
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
                    
                    if start < 1 or end > max_items:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_items})")
                    
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
                    if num < 1 or num > max_items:
                        raise ValueError(f"Item number {num} is out of bounds (1-{max_items})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid item number: {part}")
        
        return sorted(list(selected_indices))

    def get_selected_accounts_data(self, selected_indices):
        """Get account data for selected indices"""
        accounts = list(self.config_data['accounts'].items())
        selected_accounts = {}
        
        for idx in selected_indices:
            account_name, account_data = accounts[idx - 1]
            selected_accounts[account_name] = account_data
        
        return selected_accounts

    def display_users_menu(self, selected_accounts):
        """Display available users and return user selection"""
        # Collect all users from selected accounts
        all_users = []
        for account_name, account_data in selected_accounts.items():
            for user_data in account_data.get('users', []):
                user_info = {
                    'account_name': account_name,
                    'account_id': account_data.get('account_id', 'Unknown'),
                    'account_email': account_data.get('account_email', 'Unknown'),
                    'user_data': user_data,
                    'username': user_data.get('username', 'unknown'),
                    'region': user_data.get('region', 'us-east-1'),
                    'real_user': user_data.get('real_user', {}),
                    'access_key': user_data.get('access_key_id', ''),
                    'secret_key': user_data.get('secret_access_key', '')
                }
                all_users.append(user_info)
        
        if not all_users:
            self.log_operation('ERROR', "No users found in selected accounts")
            return [], {}
        
        self.log_operation('INFO', f"Displaying {len(all_users)} available users for selection")
        
        print(f"\n👥 Available Users ({len(all_users)} total):")
        print("=" * 100)
        
        # Group users by account for better display
        users_by_account = {}
        for user_info in all_users:
            account_name = user_info['account_name']
            if account_name not in users_by_account:
                users_by_account[account_name] = []
            users_by_account[account_name].append(user_info)
        
        user_index = 1
        user_mapping = {}  # Map display index to user info
        
        for account_name, users in users_by_account.items():
            account_id = users[0]['account_id']
            print(f"\n🏦 {account_name} ({account_id}) - {len(users)} users:")
            print("-" * 80)
            
            for user_info in users:
                real_user = user_info['real_user']
                full_name = real_user.get('full_name', user_info['username'])
                email = real_user.get('email', 'N/A')
                region = user_info['region']
                
                print(f"  {user_index:3}. {full_name}")
                print(f"       👤 Username: {user_info['username']}")
                print(f"       📧 Email: {email}")
                print(f"       🌍 Region: {region}")
                
                user_mapping[user_index] = user_info
                user_index += 1
                print()
        
        print("=" * 100)
        print(f"📊 Summary: {len(all_users)} users across {len(users_by_account)} accounts")
        
        print(f"\n📝 Selection Options:")
        print(f"   • All users: 'all' or press Enter")
        print(f"   • Ranges: 1-{len(all_users)}")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select users to process: ").strip()
            
            if not selection or selection.lower() == 'all':
                return list(range(1, len(all_users) + 1)), user_mapping
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                return [], {}
            
            try:
                selected_indices = self.parse_selection(selection, len(all_users))
                if selected_indices:
                    confirm = input(f"\n🚀 Proceed with {len(selected_indices)} users? (y/N): ").lower().strip()
                    if confirm == 'y':
                        return selected_indices, user_mapping
                    else:
                        continue
                else:
                    print("❌ No valid users selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                continue

    

    

    def get_or_create_vpc_resources(self, ec2_client, region: str) -> Tuple[List[str], str]:
        """Get or create VPC resources (subnets, security group) filtering out unsupported AZs"""
        try:
            self.log_operation('DEBUG', f"Getting VPC resources for region: {region}")
            
            # Load unsupported AZs from mapping file
            unsupported_azs = self._get_unsupported_azs(region)
            if unsupported_azs:
                self.log_operation('DEBUG', f"Unsupported AZs in {region}: {unsupported_azs}")
            
            # Get default VPC
            vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
            
            if not vpcs['Vpcs']:
                self.log_operation('ERROR', f"No default VPC found in {region}")
                raise Exception(f"No default VPC found in {region}")
            
            vpc_id = vpcs['Vpcs'][0]['VpcId']
            self.log_operation('DEBUG', f"Using VPC {vpc_id} in region {region}")
            
            # Get subnets
            subnets = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'state', 'Values': ['available']}
                ]
            )
            
            # Filter out subnets in unsupported AZs
            supported_subnets = []
            for subnet in subnets['Subnets']:
                az = subnet['AvailabilityZone']
                if az not in unsupported_azs:
                    supported_subnets.append(subnet)
                else:
                    self.log_operation('DEBUG', f"Skipping subnet {subnet['SubnetId']} in unsupported AZ: {az}")
            
            # Take first 2 supported subnets
            subnet_ids = [subnet['SubnetId'] for subnet in supported_subnets[:2]]
            
            if len(subnet_ids) < 2:
                # Check minimum requirements from config
                min_subnets = self._get_min_subnets_required()
                self.log_operation('WARNING', f"Only found {len(subnet_ids)} supported subnets in {region}, minimum required: {min_subnets}")
                
                if len(supported_subnets) > 0:
                    # If we have at least one supported subnet, use what we have
                    subnet_ids = [subnet['SubnetId'] for subnet in supported_subnets]
                    self.log_operation('INFO', f"Using {len(subnet_ids)} available supported subnets")
                    
                    if len(subnet_ids) < min_subnets:
                        self.log_operation('ERROR', f"Insufficient supported subnets: found {len(subnet_ids)}, need {min_subnets}")
                        raise Exception(f"Insufficient supported subnets in {region}: found {len(subnet_ids)}, need at least {min_subnets}")
                else:
                    self.log_operation('ERROR', f"No supported subnets found in {region}")
                    raise Exception(f"No supported subnets found in {region}")
            
            self.log_operation('DEBUG', f"Found {len(subnet_ids)} supported subnets: {subnet_ids}")
            
            # Get or create security group
            try:
                security_groups = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': ['eks-cluster-sg']},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                
                if security_groups['SecurityGroups']:
                    sg_id = security_groups['SecurityGroups'][0]['GroupId']
                    self.log_operation('DEBUG', f"Using existing security group: {sg_id}")
                else:
                    # Create security group
                    sg_response = ec2_client.create_security_group(
                        GroupName='eks-cluster-sg',
                        Description='Security group for EKS cluster',
                        VpcId=vpc_id
                    )
                    sg_id = sg_response['GroupId']
                    self.log_operation('INFO', f"Created security group {sg_id}")
                    
            except Exception as e:
                self.log_operation('WARNING', f"Using default security group due to: {str(e)}")
                default_sg = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': ['default']},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                sg_id = default_sg['SecurityGroups'][0]['GroupId']
            return subnet_ids, sg_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to get VPC resources in {region}: {str(e)}")
            raise

    def _get_unsupported_azs(self, region: str) -> Set[str]:
        """Load unsupported AZs from ec2-region-ami-mapping.json file"""
        try:
            # Adjust the path to your mapping file
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
            
            if not os.path.exists(mapping_file_path):
                self.log_operation('WARNING', f"Mapping file not found: {mapping_file_path}")
                return set()
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            # Get unsupported AZs for the specified region
            unsupported_azs = set()
            
            if 'eks_unsupported_azs' in mapping_data and region in mapping_data['eks_unsupported_azs']:
                unsupported_azs = set(mapping_data['eks_unsupported_azs'][region])
                self.log_operation('DEBUG', f"Loaded {len(unsupported_azs)} unsupported AZs for {region} from mapping file")
            else:
                self.log_operation('DEBUG', f"No unsupported AZs found for region {region} in mapping file")
            
            return unsupported_azs
            
        except Exception as e:
            self.log_operation('WARNING', f"Failed to load unsupported AZs from mapping file: {str(e)}")
        
    def _get_min_subnets_required(self) -> int:
        """Get minimum subnets required from config file"""
        try:
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
            
            if not os.path.exists(mapping_file_path):
                return 2  # Default fallback
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            if 'eks_config' in mapping_data and 'min_subnets_required' in mapping_data['eks_config']:
                return mapping_data['eks_config']['min_subnets_required']
            
            return 2  # Default fallback
            
        except Exception:
            return 2  # Default fallback



    def ensure_iam_roles(self, iam_client, account_id: str) -> Tuple[str, str]:
        """Ensure required IAM roles exist"""
        eks_role_name = "eks-service-role"
        node_role_name = "NodeInstanceRole"
        
        eks_role_arn = f"arn:aws:iam::{account_id}:role/{eks_role_name}"
        node_role_arn = f"arn:aws:iam::{account_id}:role/{node_role_name}"
        
        self.log_operation('DEBUG', f"Checking IAM roles for account {account_id}")
        
        # Check if roles exist, create if they don't
        try:
            iam_client.get_role(RoleName=eks_role_name)
            self.log_operation('DEBUG', f"EKS service role {eks_role_name} already exists")
        except iam_client.exceptions.NoSuchEntityException:
            self.log_operation('INFO', f"Creating EKS service role {eks_role_name}")
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "eks.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            iam_client.create_role(
                RoleName=eks_role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="IAM role for EKS service"
            )
            
            # Attach required policies
            policies = ["arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"]
            for policy in policies:
                iam_client.attach_role_policy(RoleName=eks_role_name, PolicyArn=policy)
                
            # Wait for role to be available
            time.sleep(10)
        
        try:
            iam_client.get_role(RoleName=node_role_name)
            self.log_operation('DEBUG', f"Node instance role {node_role_name} already exists")
        except iam_client.exceptions.NoSuchEntityException:
            self.log_operation('INFO', f"Creating node instance role {node_role_name}")
            node_trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ec2.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            iam_client.create_role(
                RoleName=node_role_name,
                AssumeRolePolicyDocument=json.dumps(node_trust_policy),
                Description="IAM role for EKS worker nodes"
            )
            
            # Attach required policies for worker nodes
            node_policies = [
                "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
                "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
            ]
            
            for policy in node_policies:
                iam_client.attach_role_policy(RoleName=node_role_name, PolicyArn=policy)
                
            # Wait for role to be available
            time.sleep(10)
        
        return eks_role_arn, node_role_arn
    
    def configure_aws_auth_configmap(self, cluster_name: str, region: str, account_id: str, user_data: Dict, admin_access_key: str, admin_secret_key: str) -> bool:
        """Configure aws-auth ConfigMap to add user access to the cluster using admin credentials"""
        try:
            self.log_operation('INFO', f"Configuring aws-auth ConfigMap for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔐 Configuring aws-auth ConfigMap for cluster {cluster_name}")
            
            # Create admin session for configuring the cluster
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            eks_client = admin_session.client('eks')
            
            # Get cluster details
            cluster_info = eks_client.describe_cluster(name=cluster_name)
            cluster_endpoint = cluster_info['cluster']['endpoint']
            cluster_ca = cluster_info['cluster']['certificateAuthority']['data']
            
            # Create temporary directory if it doesn't exist
            temp_dir = "/tmp"
            if not os.path.exists(temp_dir):
                temp_dir = os.getcwd()  # Use current directory as fallback
            
            # Get user's IAM ARN
            username = user_data.get('username', 'unknown')
            user_arn = f"arn:aws:iam::{account_id}:user/{username}"
            
            self.log_operation('INFO', f"Configuring access for user: {username} with ARN: {user_arn}")
            
            # Create aws-auth ConfigMap YAML
            aws_auth_config = {
                'apiVersion': 'v1',
                'kind': 'ConfigMap',
                'metadata': {
                    'name': 'aws-auth',
                    'namespace': 'kube-system'
                },
                'data': {
                    'mapRoles': yaml.dump([
                        {
                            'rolearn': f"arn:aws:iam::{account_id}:role/NodeInstanceRole",
                            'username': 'system:node:{{EC2PrivateDNSName}}',
                            'groups': ['system:bootstrappers', 'system:nodes']
                        }
                    ], default_flow_style=False),
                    'mapUsers': yaml.dump([
                        {
                            'userarn': user_arn,
                            'username': username,
                            'groups': ['system:masters']
                        }
                    ], default_flow_style=False)
                }
            }
            
            # Save ConfigMap YAML with error handling
            configmap_file = os.path.join(temp_dir, f"aws-auth-{cluster_name}-{self.execution_timestamp}.yaml")
            try:
                with open(configmap_file, 'w') as f:
                    yaml.dump(aws_auth_config, f)
                self.log_operation('INFO', f"Created ConfigMap file: {configmap_file}")
            except Exception as e:
                self.log_operation('ERROR', f"Failed to create ConfigMap file: {str(e)}")
                return False
            
            # Check if kubectl is available
            import subprocess
            import shutil
            
            kubectl_available = shutil.which('kubectl') is not None
            
            if not kubectl_available:
                self.log_operation('WARNING', f"kubectl not found. ConfigMap file created but not applied: {configmap_file}")
                self.print_colored(Colors.YELLOW, f"⚠️  kubectl not found. Manual setup required.")
                
                # Create manual instruction file
                instruction_file = os.path.join(temp_dir, f"manual-auth-setup-{cluster_name}-{self.execution_timestamp}.txt")
                try:
                    with open(instruction_file, 'w') as f:
                        f.write(f"# Manual aws-auth ConfigMap Setup for {cluster_name}\n")
                        f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                        f.write(f"# Cluster: {cluster_name}\n")
                        f.write(f"# Region: {region}\n")
                        f.write(f"# User: {username}\n\n")
                        
                        f.write("## Prerequisites\n")
                        f.write("# Install kubectl\n")
                        f.write("curl -LO \"https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl\"\n")
                        f.write("chmod +x kubectl\n")
                        f.write("sudo mv kubectl /usr/local/bin/\n\n")
                        
                        f.write("## Apply ConfigMap with Admin Credentials\n")
                        f.write(f"# Set AWS admin credentials\n")
                        f.write(f"export AWS_ACCESS_KEY_ID={admin_access_key}\n")
                        f.write(f"export AWS_SECRET_ACCESS_KEY={admin_secret_key}\n")
                        f.write(f"export AWS_DEFAULT_REGION={region}\n\n")
                        
                        f.write(f"# Update kubeconfig with admin credentials\n")
                        f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name}\n\n")
                        
                        f.write(f"# Apply the ConfigMap\n")
                        f.write(f"kubectl apply -f {configmap_file}\n\n")
                        
                        f.write(f"# Verify ConfigMap\n")
                        f.write(f"kubectl get configmap aws-auth -n kube-system -o yaml\n\n")
                        
                        f.write(f"## Test User Access\n")
                        f.write(f"# Set user credentials\n")
                        f.write(f"export AWS_ACCESS_KEY_ID={user_data.get('access_key_id', 'USER_ACCESS_KEY')}\n")
                        f.write(f"export AWS_SECRET_ACCESS_KEY={user_data.get('secret_access_key', 'USER_SECRET_KEY')}\n")
                        f.write(f"# Update kubeconfig with user profile\n")
                        f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name} --profile {username}\n")
                        f.write(f"# Test access\n")
                        f.write(f"kubectl get nodes\n")
                        f.write(f"kubectl get pods\n")
                    
                    self.log_operation('INFO', f"Manual setup instructions saved to: {instruction_file}")
                    self.print_colored(Colors.CYAN, f"📋 Manual setup instructions: {instruction_file}")
                    
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to create instruction file: {str(e)}")
                
                # Return True since we created the ConfigMap file
                return True
            
            # Apply ConfigMap using kubectl with admin credentials
            self.log_operation('INFO', f"Applying ConfigMap using admin credentials")
            self.print_colored(Colors.YELLOW, f"🚀 Applying ConfigMap with admin credentials...")
            
            # Set environment variables for admin access
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region
            
            try:
                # Update kubeconfig with admin credentials first
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]
                
                self.log_operation('INFO', f"Updating kubeconfig with admin credentials")
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
                
                if update_result.returncode == 0:
                    self.log_operation('INFO', f"Successfully updated kubeconfig with admin credentials")
                else:
                    self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                    return False
                
                # Apply the ConfigMap
                apply_cmd = ['kubectl', 'apply', '-f', configmap_file]
                self.log_operation('INFO', f"Applying ConfigMap: {' '.join(apply_cmd)}")
                
                apply_result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=300)
                
                if apply_result.returncode == 0:
                    self.log_operation('INFO', f"Successfully applied aws-auth ConfigMap for {cluster_name}")
                    self.print_colored(Colors.GREEN, f"✅ ConfigMap applied successfully")
                    
                    # Verify the ConfigMap was applied
                    verify_cmd = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system', '-o', 'yaml']
                    verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=120)
                    
                    if verify_result.returncode == 0:
                        self.log_operation('INFO', f"ConfigMap verification successful")
                        self.log_operation('DEBUG', f"ConfigMap content: {verify_result.stdout}")
                    else:
                        self.log_operation('WARNING', f"ConfigMap verification failed: {verify_result.stderr}")
                    
                    success = True
                else:
                    self.log_operation('ERROR', f"Failed to apply aws-auth ConfigMap: {apply_result.stderr}")
                    self.print_colored(Colors.RED, f"❌ Failed to apply ConfigMap: {apply_result.stderr}")
                    success = False
            
            except subprocess.TimeoutExpired:
                self.log_operation('ERROR', f"kubectl/aws command timed out for {cluster_name}")
                self.print_colored(Colors.RED, f"❌ Command timed out")
                success = False
            except Exception as e:
                self.log_operation('ERROR', f"Failed to execute kubectl/aws commands: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Command execution failed: {str(e)}")
                success = False
            
            # Clean up temporary files
            try:
                if os.path.exists(configmap_file):
                    os.remove(configmap_file)
                    self.log_operation('INFO', f"Cleaned up temporary ConfigMap file")
            except Exception as e:
                self.log_operation('WARNING', f"Failed to clean up ConfigMap file: {str(e)}")
            
            if success:
                self.print_colored(Colors.GREEN, f"✅ User {username} configured for cluster access")
                
                # Test user access after a brief delay
                try:
                    import time
                    time.sleep(10)  # Wait for ConfigMap to propagate
                    
                    self.log_operation('INFO', f"Testing user access for {username}")
                    self.print_colored(Colors.YELLOW, f"🧪 Testing user access...")
                    
                    # Set user environment
                    user_env = os.environ.copy()
                    user_env['AWS_ACCESS_KEY_ID'] = user_data.get('access_key_id', '')
                    user_env['AWS_SECRET_ACCESS_KEY'] = user_data.get('secret_access_key', '')
                    user_env['AWS_DEFAULT_REGION'] = region
                    
                    # Update kubeconfig with user credentials
                    user_update_cmd = [
                        'aws', 'eks', 'update-kubeconfig',
                        '--region', region,
                        '--name', cluster_name
                        #'--profile', username
                    ]
                    
                    user_update_result = subprocess.run(user_update_cmd, env=user_env, capture_output=True, text=True, timeout=120)
                    
                    if user_update_result.returncode == 0:
                        # Test kubectl access
                        test_cmd = ['kubectl', 'get', 'nodes']
                        test_result = subprocess.run(test_cmd, env=user_env, capture_output=True, text=True, timeout=60)
                        
                        if test_result.returncode == 0:
                            self.log_operation('INFO', f"User access test successful for {username}")
                            self.print_colored(Colors.GREEN, f"✅ User access verified - can access cluster")
                        else:
                            self.log_operation('WARNING', f"User access test failed: {test_result.stderr}")
                            self.print_colored(Colors.YELLOW, f"⚠️  User access test failed - may need manual verification")
                    else:
                        self.log_operation('WARNING', f"Failed to update kubeconfig for user test: {user_update_result.stderr}")
                        
                except Exception as e:
                    self.log_operation('WARNING', f"User access test failed: {str(e)}")
            
            return success
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to configure aws-auth ConfigMap for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"❌ ConfigMap configuration failed: {error_msg}")
            return False
    
    # Add this method to the EKSClusterManager class around line 1186

    def select_capacity_type(self, user_name: str = None) -> str:
        """Allow user to select capacity type (Spot or On-Demand)"""
        capacity_options = ['SPOT', 'ON_DEMAND']
        default_type = 'SPOT'  # Default to SPOT for cost efficiency
        
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n💰 Capacity Type Selection {user_prefix}")
        print("=" * 60)
        print("Available capacity types:")
        
        for i, capacity_type in enumerate(capacity_options, 1):
            is_default = " (default)" if capacity_type == default_type else ""
            cost_info = " - Lower cost, may be interrupted" if capacity_type == 'SPOT' else " - Higher cost, stable"
            print(f"  {i}. {capacity_type}{is_default}{cost_info}")
        
        print("=" * 60)
        
        while True:
            try:
                choice = input(f"Select capacity type (1-{len(capacity_options)}) [default: {default_type}]: ").strip()
                
                if not choice:
                    selected_type = default_type
                    break
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(capacity_options):
                    selected_type = capacity_options[choice_num - 1]
                    break
                else:
                    print(f"❌ Please enter a number between 1 and {len(capacity_options)}")
            except ValueError:
                print("❌ Please enter a valid number")
        
        print(f"✅ Selected capacity type: {selected_type}")
        return selected_type
    
    def test_user_access_enhanced(self, cluster_name: str, region: str, username: str, user_access_key: str, user_secret_key: str) -> bool:
        """Enhanced user access testing with detailed feedback"""
        self.log_operation('INFO', f"Testing user access for {username} on cluster {cluster_name}")
        self.print_colored(Colors.YELLOW, f"🧪 Testing user access for {username}...")
        
        # Set user environment
        user_env = os.environ.copy()
        user_env['AWS_ACCESS_KEY_ID'] = user_access_key
        user_env['AWS_SECRET_ACCESS_KEY'] = user_secret_key
        user_env['AWS_DEFAULT_REGION'] = region
        
        try:
            # Update kubeconfig with user credentials
            self.print_colored(Colors.CYAN, f"   🔄 Updating kubeconfig with user credentials...")
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]
            
            result = subprocess.run(update_cmd, env=user_env, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                self.print_colored(Colors.GREEN, "   ✅ Updated kubeconfig with user credentials")
                self.log_operation('INFO', f"Kubeconfig updated successfully for {username}")
            else:
                self.log_operation('ERROR', f"Failed to update kubeconfig with user creds: {result.stderr}")
                self.print_colored(Colors.RED, f"   ❌ Failed to update kubeconfig: {result.stderr}")
                return False
            
            # Test kubectl get nodes with detailed output
            self.print_colored(Colors.CYAN, "   🔍 Testing 'kubectl get nodes'...")
            nodes_cmd = ['kubectl', 'get', 'nodes', '--no-headers']
            nodes_result = subprocess.run(nodes_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if nodes_result.returncode == 0:
                node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
                node_count = len(node_lines)
                
                self.print_colored(Colors.GREEN, f"   ✅ Found {node_count} node(s)")
                self.log_operation('INFO', f"kubectl get nodes successful - {node_count} nodes found")
                
                # Show detailed node information
                for i, node_line in enumerate(node_lines, 1):
                    node_parts = node_line.split()
                    if len(node_parts) >= 2:
                        node_name = node_parts[0]
                        node_status = node_parts[1]
                        self.print_colored(Colors.CYAN, f"      {i}. {node_name} ({node_status})")
                        self.log_operation('DEBUG', f"Node {i}: {node_line}")
            else:
                self.log_operation('ERROR', f"kubectl get nodes failed: {nodes_result.stderr}")
                self.print_colored(Colors.RED, f"   ❌ kubectl get nodes failed: {nodes_result.stderr}")
                return False
            
            
            # ✅ Test kubectl get pods in the 'default' namespace
            self.print_colored(Colors.CYAN, "   🔍 Testing 'kubectl get pods -n default'...")
            default_cmd = ['kubectl', 'get', 'pods', '-n', 'default', '--no-headers']
            default_result = subprocess.run(default_cmd, env=user_env, capture_output=True, text=True, timeout=60)

            if default_result.returncode == 0:
                default_pods = [line.strip() for line in default_result.stdout.strip().split('\n') if line.strip()]
                default_pod_count = len(default_pods)

                self.print_colored(Colors.GREEN, f"   ✅ Found {default_pod_count} pod(s) in 'default' namespace")
                self.log_operation('INFO', f"kubectl get pods -n default successful - {default_pod_count} pods found")
            else:
                self.print_colored(Colors.RED, f"   ❌ kubectl get pods -n default failed: {default_result.stderr}")
                self.log_operation('ERROR', f"kubectl get pods -n default failed: {default_result.stderr}")
            
            # Test kubectl get pods with namespace breakdown
            self.print_colored(Colors.CYAN, "   🔍 Testing 'kubectl get pods --all-namespaces'...")
            pods_cmd = ['kubectl', 'get', 'pods', '--all-namespaces', '--no-headers']
            pods_result = subprocess.run(pods_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if pods_result.returncode == 0:
                pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
                pod_count = len(pod_lines)
                
                self.print_colored(Colors.GREEN, f"   ✅ Found {pod_count} pod(s) across all namespaces")
                self.log_operation('INFO', f"kubectl get pods successful - {pod_count} pods found")
                
                # Count pods by namespace
                namespace_counts = {}
                for pod_line in pod_lines:
                    parts = pod_line.split()
                    if len(parts) >= 1:
                        namespace = parts[0]
                        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
                
                for namespace, count in namespace_counts.items():
                    self.print_colored(Colors.CYAN, f"      {namespace}: {count} pod(s)")
                    self.log_operation('DEBUG', f"Namespace {namespace}: {count} pods")
            else:
                self.log_operation('ERROR', f"kubectl get pods failed: {pods_result.stderr}")
                self.print_colored(Colors.RED, f"   ❌ kubectl get pods failed: {pods_result.stderr}")
                return False
            
            # Test cluster-info
            self.print_colored(Colors.CYAN, "   🔍 Testing 'kubectl cluster-info'...")
            info_cmd = ['kubectl', 'cluster-info']
            info_result = subprocess.run(info_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if info_result.returncode == 0:
                self.print_colored(Colors.GREEN, f"   ✅ Cluster info retrieved successfully")
                self.log_operation('INFO', f"kubectl cluster-info successful")
                self.log_operation('DEBUG', f"Cluster info: {info_result.stdout}")
            else:
                self.log_operation('WARNING', f"kubectl cluster-info failed: {info_result.stderr}")
                self.print_colored(Colors.YELLOW, f"   ⚠️  kubectl cluster-info failed (non-critical)")
            
            self.print_colored(Colors.GREEN, f"🎉 User access verification successful for {username}!")
            self.log_operation('INFO', f"Complete user access verification successful for {username}")
            return True
                
        except subprocess.TimeoutExpired:
            self.log_operation('ERROR', f"User access test timed out for {username}")
            self.print_colored(Colors.RED, "   ❌ User access test timed out")
            return False
        except Exception as e:
            self.log_operation('ERROR', f"Error testing user access for {username}: {str(e)}")
            self.print_colored(Colors.RED, f"   ❌ Error testing user access: {str(e)}")
            return False

    def load_ec2_config(self) -> Dict:
        """Load EC2 configuration from JSON file"""
        config_file = "ec2-region-ami-mapping.json"
        try:
            if not os.path.exists(config_file):
                self.log_operation('WARNING', f"Config file {config_file} not found, using defaults")
                # Fallback configuration
                return {
                    "allowed_instance_types": ["t3.micro", "t2.micro", "c6a.large"],
                    "default_instance_type": "c6a.large"
                }
            
            with open(config_file, 'r') as f:
                config = json.load(f)
                self.log_operation('INFO', f"Loaded EC2 configuration from {config_file}")
                return config
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load {config_file}: {str(e)}")
            # Return fallback configuration
            return {
                "allowed_instance_types": ["t3.micro", "t2.micro", "c6a.large"],
                "default_instance_type": "c6a.large"
            }

    def select_instance_type(self, user_name: str = None) -> str:
        """Allow user to select instance type from allowed types"""
        ec2_config = self.load_ec2_config()
        allowed_types = ec2_config.get("allowed_instance_types", ["c6a.large"])
        default_type = ec2_config.get("default_instance_type", "c6a.large")
        
        # Ensure default is in allowed types
        if default_type not in allowed_types:
            default_type = allowed_types[0] if allowed_types else "c6a.large"
        
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n💻 Instance Type Selection {user_prefix}")
        print("=" * 60)
        print("Available instance types:")
        
        for i, instance_type in enumerate(allowed_types, 1):
            is_default = " (default)" if instance_type == default_type else ""
            print(f"  {i}. {instance_type}{is_default}")
        
        print("=" * 60)
        
        while True:
            try:
                choice = input(f"Select instance type (1-{len(allowed_types)}) [default: {default_type}]: ").strip()
                
                if not choice:
                    selected_type = default_type
                    break
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(allowed_types):
                    selected_type = allowed_types[choice_num - 1]
                    break
                else:
                    print(f"❌ Please enter a number between 1 and {len(allowed_types)}")
            except ValueError:
                print("❌ Please enter a valid number")
        
        print(f"✅ Selected instance type: {selected_type}")
        return selected_type
    
    def create_clusters(self, cluster_configs) -> None:
        """Create all configured clusters"""
        if not cluster_configs:
            self.print_colored(Colors.YELLOW, "No clusters to create!")
            return
        
        self.log_operation('INFO', f"Starting creation of {len(cluster_configs)} clusters")
        self.print_colored(Colors.GREEN, f"🚀 Starting creation of {len(cluster_configs)} clusters...")
        
        # Create clusters sequentially
        successful_clusters = []
        failed_clusters = []
        
        for i, cluster_info in enumerate(cluster_configs, 1):
            self.print_colored(Colors.BLUE, f"\n📋 Progress: {i}/{len(cluster_configs)}")
            
            if self.create_single_cluster(cluster_info):
                successful_clusters.append(cluster_info)
            else:
                failed_clusters.append(cluster_info)
        
        # Summary
        self.log_operation('INFO', f"Cluster creation completed - Created: {len(successful_clusters)}, Failed: {len(failed_clusters)}")
        
        self.print_colored(Colors.GREEN, f"\n🎉 Cluster Creation Summary:")
        self.print_colored(Colors.GREEN, f"✅ Successful: {len(successful_clusters)}")
        if failed_clusters:
            self.print_colored(Colors.RED, f"❌ Failed: {len(failed_clusters)}")
        
        # Generate final commands and instructions (silently)
        # Save created clusters to JSON file
        if successful_clusters:
            self.save_created_clusters(successful_clusters)

        # Generate final commands and instructions (silently)
        self.generate_final_commands()
        self.generate_user_instructions()

    def ensure_directory_exists(self, directory_path: str) -> str:
        """Ensure directory exists, create if it doesn't"""
        try:
            if not os.path.exists(directory_path):
                os.makedirs(directory_path, exist_ok=True)
                self.log_operation('INFO', f"Created directory: {directory_path}")
                self.print_colored(Colors.CYAN, f"📁 Created directory: {directory_path}")
            return directory_path
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create directory {directory_path}: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Failed to create directory {directory_path}: {str(e)}")
            return "."  # Fallback to current directory

    def create_single_cluster(self, cluster_info: Dict) -> bool:
        """Create a single EKS cluster using admin credentials with user-selected instance type and 1 default node"""
        user = cluster_info['user']
        cluster_name = cluster_info['cluster_name']
        region = user['region']
        account_id = cluster_info['account_id']
        account_key = cluster_info['account_key']
        max_nodes = cluster_info['max_nodes']
        username = user['username']
        instance_type = cluster_info.get('instance_type', 'c6a.large')
        
        try:
            self.log_operation('INFO', f"Starting cluster creation: {cluster_name} in {region} with {instance_type}")
            self.print_colored(Colors.YELLOW, f"🔄 Creating cluster: {cluster_name} in {region} with {instance_type}")
            
            # Get admin credentials for this account
            admin_access_key, admin_secret_key = self.get_admin_credentials_for_account(account_key)
            
            # Create AWS clients using admin credentials
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            eks_client = admin_session.client('eks')
            ec2_client = admin_session.client('ec2')
            iam_client = admin_session.client('iam')
            
            self.log_operation('INFO', f"AWS admin session created for {account_key} in {region}")
            
            # Ensure IAM roles exist
            self.log_operation('DEBUG', f"Ensuring IAM roles exist for {account_key}")
            eks_role_arn, node_role_arn = self.ensure_iam_roles(iam_client, account_id)
            self.log_operation('INFO', f"IAM roles verified/created for {account_key}")
            
            # Get VPC resources
            self.log_operation('DEBUG', f"Getting VPC resources for {account_key} in {region}")
            subnet_ids, security_group_id = self.get_or_create_vpc_resources(ec2_client, region)
            self.log_operation('INFO', f"VPC resources verified for {account_key} in {region}")
            
            # Step 1: Create EKS cluster
            self.log_operation('INFO', f"Creating EKS cluster {cluster_name} with CloudWatch logging")
            cluster_config = {
                'name': cluster_name,
                'version': '1.28',
                'roleArn': eks_role_arn,
                'resourcesVpcConfig': {
                    'subnetIds': subnet_ids,
                    'securityGroupIds': [security_group_id]
                },
                'logging': {
                    'clusterLogging': [
                        {
                            'types': ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
                            'enabled': True
                        }
                    ]
                }
            }
            
            eks_client.create_cluster(**cluster_config)
            self.log_operation('INFO', f"EKS cluster {cluster_name} creation initiated")
            
            # Wait for cluster to be active
            self.log_operation('INFO', f"Waiting for cluster {cluster_name} to be active...")
            self.print_colored(Colors.YELLOW, f"⏳ Waiting for cluster {cluster_name} to be active...")
            waiter = eks_client.get_waiter('cluster_active')
            waiter.wait(name=cluster_name, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})
            
            self.log_operation('INFO', f"Cluster {cluster_name} is now active")
            
            # Step 2: Create node group with selected instance type and 1 default node
            self.log_operation('INFO', f"Creating node group for cluster {cluster_name} with {instance_type} instances")
            nodegroup_name = self.generate_nodegroup_name(cluster_name)
            
            # Use the selected instance type
            nodegroup_config = {
                'clusterName': cluster_name,
                'nodegroupName': nodegroup_name,
                'scalingConfig': {
                    'minSize': 1,
                    'maxSize': max_nodes,
                    'desiredSize': 1
                },
                'instanceTypes': [instance_type],
                'amiType': 'AL2023_x86_64_STANDARD',#"AL2_x86_64"
                'diskSize': 20,
                'nodeRole': node_role_arn,
                'subnets': subnet_ids,
                'capacityType': cluster_info.get('capacity_type', 'SPOT')
            }
            
            # Log the exact configuration being used
            self.log_operation('INFO', f"Creating nodegroup with config: instanceTypes={nodegroup_config['instanceTypes']}, capacityType={nodegroup_config.get('capacityType', 'default')}")
            
            eks_client.create_nodegroup(**nodegroup_config)
            self.log_operation('INFO', f"Node group {nodegroup_name} creation initiated with {instance_type} instances")
            
            # Wait for node group to be active
            self.log_operation('INFO', f"Waiting for node group {nodegroup_name} to be active...")
            self.print_colored(Colors.YELLOW, f"⏳ Waiting for node group {nodegroup_name} to be active...")
            ng_waiter = eks_client.get_waiter('nodegroup_active')
            ng_waiter.wait(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )
            
            self.log_operation('INFO', f"Node group {nodegroup_name} is now active with 1 {instance_type} node")
            
            # Verify the actual instance type created
            try:
                nodegroup_details = eks_client.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name
                )
                actual_instance_types = nodegroup_details['nodegroup'].get('instanceTypes', [])
                self.log_operation('INFO', f"Verified nodegroup instance types: {actual_instance_types}")
                
                if instance_type not in actual_instance_types:
                    self.log_operation('WARNING', f"Expected {instance_type} but got: {actual_instance_types}")
                else:
                    self.log_operation('INFO', f"Successfully created nodegroup with {instance_type} instances")
                    
            except Exception as e:
                self.log_operation('WARNING', f"Could not verify nodegroup instance types: {str(e)}")
            
            # Step 3: Configure aws-auth ConfigMap for user access
            self.log_operation('INFO', f"Configuring user access for {username}")
            self.print_colored(Colors.YELLOW, f"🔐 Configuring user access for {username}...")

            auth_success = self.configure_aws_auth_configmap(
                cluster_name, region, account_id, user, admin_access_key, admin_secret_key
            )

            if auth_success:
                self.log_operation('INFO', f"User access configured for {username}")
            else:
                self.log_operation('WARNING', f"Failed to configure user access for {username}")

            # Step 4: Verify cluster access using user credentials
            verification_success = False
            if auth_success:
                self.log_operation('INFO', f"Verifying cluster access for {username}")
                
                # Wait a bit more for ConfigMap to fully propagate
                time.sleep(15)
                
                user_credentials = {
                    'access_key_id': user.get('access_key_id', ''),
                    'secret_access_key': user.get('secret_access_key', '')
                }
                
                verification_success = self.test_user_access_enhanced(
                    cluster_name, 
                    region, 
                    username, 
                    user_credentials['access_key_id'], 
                    user_credentials['secret_access_key']
                )
                if verification_success:
                    self.log_operation('INFO', f"Cluster access verification successful for {username}")
                    self.print_colored(Colors.GREEN, f"✅ Cluster access verified for {username}")
                else:
                    self.log_operation('WARNING', f"Cluster access verification failed for {username}")
                    self.print_colored(Colors.YELLOW, f"⚠️  Cluster access verification failed for {username}")
            else:
                self.log_operation('WARNING', f"Skipping verification due to ConfigMap configuration failure")

            # Update cluster_info with verification results
            cluster_info['auth_configured'] = auth_success
            cluster_info['access_verified'] = verification_success
            
            # Generate kubectl commands for the user
            user_kubectl_cmd = f"aws eks update-kubeconfig --region {region} --name {cluster_name} --profile {username}"
            admin_kubectl_cmd = f"aws eks update-kubeconfig --region {region} --name {cluster_name}"
            
            kubectl_info = {
                'cluster_name': cluster_name,
                'region': region,
                'user_command': user_kubectl_cmd,
                'admin_command': admin_kubectl_cmd,
                'user': username,
                'account': account_key,
                'max_nodes': max_nodes,
                'auth_configured': auth_success,
                'access_verified': verification_success,
                'user_access_key': user.get('access_key_id', ''),
                'user_secret_key': user.get('secret_access_key', ''),
                'instance_type': instance_type,
                'default_nodes': 1
            }
            
            self.kubectl_commands.append(kubectl_info)
            self.log_operation('INFO', f"Generated kubectl commands for {username}")
            
            # *** NEW: Generate individual user instruction file immediately ***
            self.generate_individual_user_instruction(cluster_info, kubectl_info)
            
            self.log_operation('INFO', f"Successfully created cluster {cluster_name} with {instance_type} instances")
            self.print_colored(Colors.GREEN, f"✅ Successfully created cluster: {cluster_name} ({instance_type}, 1 node)")
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to create cluster {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"❌ Failed to create cluster {cluster_name}: {error_msg}")
            return False
    def run(self) -> None:
        """Main execution flow"""
        try:
            self.print_colored(Colors.GREEN, "🚀 Welcome to Interactive EKS Cluster Manager")
            
            print("🚀 EKS Cluster Creation for IAM Users")
            print("=" * 80)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📄 User Credentials: {self.config_file}")
            print(f"🔑 Admin Credentials: {self.admin_config_file}")
            print(f"💻 Instance Types: Configurable (from ec2-region-ami-mapping.json)")
            print(f"📊 Default Nodes: 1 node per cluster")
            print("=" * 80)
            
            # Load EC2 configuration to display available instance types
            ec2_config = self.load_ec2_config()
            allowed_types = ec2_config.get("allowed_instance_types", ["c6a.large"])
            default_type = ec2_config.get("default_instance_type", "c6a.large")
            
            print(f"\n💻 Available Instance Types: {', '.join(allowed_types)}")
            print(f"🎯 Default Instance Type: {default_type}")
            print("=" * 80)
            
            # Step 1: Select accounts to process
            selected_account_indices = self.display_accounts_menu()
            if not selected_account_indices:
                print("❌ Account selection cancelled")
                return
            
            selected_accounts = self.get_selected_accounts_data(selected_account_indices)
            
            # Step 2: Ask for selection level preference
            print(f"\n🎯 Selection Level:")
            print("=" * 50)
            print("  1. Process ALL users in selected accounts")
            print("  2. Select specific users from selected accounts")
            print("=" * 50)
            
            while True:
                selection_level = input("🔢 Choose selection level (1-2): ").strip()
                
                if selection_level == '1':
                    # Use all users from selected accounts
                    cluster_configs = []
                    for account_name, account_data in selected_accounts.items():
                        for user_data in account_data.get('users', []):
                            print(f"\n🔧 Configuration for {user_data.get('real_user', {}).get('full_name', user_data.get('username', 'unknown'))}:")
                            print(f"   👤 Username: {user_data.get('username', 'unknown')}")
                            print(f"   🌍 Region: {user_data.get('region', 'unknown')}")
                            print(f"   🏦 Account: {account_name}")
                            print(f"   📊 Default Nodes: 1")
                            
                            # Select instance type for this user
                            instance_type = self.select_instance_type(user_data.get('username', 'unknown'))
                            capacity_type = self.select_capacity_type(user_data.get('username', 'unknown'))
                            
                            while True:
                                try:
                                    max_nodes = input(f"   🔢 Enter maximum nodes for scaling (1-10) [default: 3]: ").strip()
                                    if not max_nodes:
                                        max_nodes = 3
                                    else:
                                        max_nodes = int(max_nodes)
                                    
                                    if 1 <= max_nodes <= 10:
                                        break
                                    else:
                                        print("   ❌ Please enter a number between 1 and 10")
                                except ValueError:
                                    print("   ❌ Please enter a valid number")
                            
                            cluster_name = self.generate_cluster_name(user_data.get('username', 'unknown'), user_data.get('region', 'us-east-1'))
                            
                            self.display_cost_estimation(instance_type, capacity_type, max_nodes)

                            cluster_config = {
                                'account_key': account_name,
                                'account_id': account_data.get('account_id', 'Unknown'),
                                'user': user_data,
                                'max_nodes': max_nodes,
                                'cluster_name': cluster_name,
                                'instance_type': instance_type,  # Add selected instance type
                                'capacity_type': capacity_type  # Add selected capacity type
                            }
                            
                            cluster_configs.append(cluster_config)
                            print(f"   ✅ Cluster configured: {cluster_name} (max {max_nodes} nodes, {instance_type})")
                    
                    break
                elif selection_level == '2':
                    # Allow user-level selection
                    selected_user_indices, user_mapping = self.display_users_menu(selected_accounts)
                    if not selected_user_indices:
                        print("❌ User selection cancelled")
                        return
                    
                    # Convert selected users to cluster configs
                    cluster_configs = self.convert_selected_users_to_clusters(selected_user_indices, user_mapping)
                    break
                else:
                    print("❌ Invalid choice. Please enter 1 or 2.")
            
            # Show summary and confirm
            if self.show_cluster_summary(cluster_configs):
                # Create clusters
                self.create_clusters(cluster_configs)
            else:
                self.print_colored(Colors.YELLOW, "Cluster creation cancelled.")
            
        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n\nOperation cancelled by user.")
        except Exception as e:
            error_msg = str(e)
            self.print_colored(Colors.RED, f"Error: {error_msg}")
            sys.exit(1)

    def convert_selected_users_to_clusters(self, selected_user_indices, user_mapping):
        """Convert selected user indices to cluster configuration with max nodes and instance type selection"""
        cluster_configs = []
        
        for user_index in selected_user_indices:
            user_info = user_mapping[user_index]
            
            # Get max scaling preference and instance type for this user
            print(f"\n🔧 Configuration for {user_info['real_user'].get('full_name', user_info['username'])}:")
            print(f"   👤 Username: {user_info['username']}")
            print(f"   🌍 Region: {user_info['region']}")
            print(f"   🏦 Account: {user_info['account_name']}")
            print(f"   📊 Default Nodes: 1 (minimum recommended)")
            
            # Select instance type for this user
            instance_type = self.select_instance_type(user_info['username'])
            capacity_type = self.select_capacity_type(user_info['username'])

            while True:
                try:
                    max_nodes = input(f"   🔢 Enter maximum nodes for scaling (1-10) [default: 3]: ").strip()
                    if not max_nodes:
                        max_nodes = 3
                    else:
                        max_nodes = int(max_nodes)
                    
                    if 1 <= max_nodes <= 10:
                        break
                    else:
                        print("   ❌ Please enter a number between 1 and 10")
                except ValueError:
                    print("   ❌ Please enter a valid number")
            
            cluster_name = self.generate_cluster_name(user_info['username'], user_info['region'])
            
            cluster_config = {
                'account_key': user_info['account_name'],
                'account_id': user_info['account_id'],
                'user': user_info['user_data'],
                'max_nodes': max_nodes,
                'cluster_name': cluster_name,
                'instance_type': instance_type,  # Add selected instance type
                'capacity_type': capacity_type  # Add selected capacity type
            }
            
            cluster_configs.append(cluster_config)
            print(f"   ✅ Cluster configured: {cluster_name} (max {max_nodes} nodes, {instance_type})")
        
        return cluster_configs
    
    # Add cost estimation display for both scripts:

    def display_cost_estimation(self, instance_type: str, capacity_type: str, node_count: int = 1):
        """Display estimated cost information"""
        # This is a simplified estimation - you'd want to use actual AWS pricing API
        base_costs = {
            't3.micro': 0.0104,
            't3.small': 0.0208,
            't3.medium': 0.0416,
            'c6a.large': 0.0864,
            'c6a.xlarge': 0.1728
        }
        
        base_cost = base_costs.get(instance_type, 0.05)  # Default fallback
        
        if capacity_type.lower() in ['spot', 'SPOT']:
            estimated_cost = base_cost * 0.3  # Spot instances are typically 70% cheaper
            savings = base_cost * 0.7
            print(f"\n💰 Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Spot: ${estimated_cost:.4f}")
            print(f"   Savings: ${savings:.4f} ({70}%)")
            print(f"   Monthly (730 hrs): ${estimated_cost * 730 * node_count:.2f}")
        else:
            print(f"\n💰 Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Monthly (730 hrs): ${base_cost * 730 * node_count:.2f}")

    def show_cluster_summary(self, cluster_configs) -> bool:
        """Show summary of selected clusters and confirm creation"""
        if not cluster_configs:
            self.print_colored(Colors.YELLOW, "No clusters configured!")
            return False
        
        print(f"\n🚀 EKS Cluster Creation Summary")
        print(f"Selected {len(cluster_configs)} clusters to create:")
        
        print("\n" + "="*100)
        for i, cluster in enumerate(cluster_configs, 1):
            user = cluster['user']
            real_user = user.get('real_user', {})
            full_name = real_user.get('full_name', user.get('username', 'Unknown'))
            instance_type = cluster.get('instance_type', 'c6a.large')
            
            print(f"{i}. Cluster: {cluster['cluster_name']}")
            print(f"   🏦 Account: {cluster['account_key']} ({cluster['account_id']})")
            print(f"   👤 User: {user.get('username', 'unknown')} ({full_name})")
            print(f"   🌍 Region: {user.get('region', 'unknown')}")
            print(f"   💻 Instance Type: {instance_type}")
            print(f"   📊 Default Nodes: 1")
            print(f"   🔢 Max Nodes: {cluster['max_nodes']}")
            print("-" * 100)
        
        print(f"📊 Total clusters: {len(cluster_configs)}")
        print(f"💻 Instance types: {', '.join(set(cluster.get('instance_type', 'c6a.large') for cluster in cluster_configs))}")
        print(f"📊 All clusters starting with: 1 node")
        print("=" * 100)
        
        confirm = input("\nDo you want to proceed with cluster creation? (y/N): ").lower().strip()
        return confirm in ['y', 'yes']

    def save_created_clusters(self, successful_clusters: List[Dict]) -> None:
        """Save created cluster details to JSON file"""
        if not successful_clusters:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clusters_file = f"eks_clusters_created_{timestamp}.json"
        
        clusters_data = {
            "metadata": {
                "created_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "created_by": self.current_user,
                "total_clusters": len(successful_clusters),
                "execution_timestamp": self.execution_timestamp
            },
            "clusters": []
        }
        
        for cluster_info in successful_clusters:
            user = cluster_info['user']
            instance_type = cluster_info.get('instance_type', 'c6a.large')
            capacity_type = cluster_info.get('capacity_type', 'SPOT')
            
            cluster_data = {
                "cluster_name": cluster_info['cluster_name'],
                "region": user['region'],
                "account_key": cluster_info['account_key'],
                "username": user['username'],
                "account_id": cluster_info['account_id'],
                "max_nodes": cluster_info['max_nodes'],
                "instance_type": instance_type,  # Use selected instance type
                "default_nodes": 1,
                "ami_type": "AL2023_x86_64_STANDARD", #"AL2_x86_64"
                "disk_size": 20,
                "capacity_type": capacity_type.upper(),  # Use selected capacity type
                "user_credentials": {
                    "access_key_id": user.get('access_key_id', ''),
                    "secret_access_key": user.get('secret_access_key', ''),
                    "profile_name": user['username']
                },
                "real_user_info": user.get('real_user', {}),
                "created_timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "kubectl_commands": {
                    "update_kubeconfig": f"aws eks update-kubeconfig --region {user['region']} --name {cluster_info['cluster_name']} --profile {user['username']}",
                    "test_access": [
                        "kubectl get nodes",
                        "kubectl get pods --all-namespaces",
                        "kubectl cluster-info"
                    ]
                }
            }
            
            clusters_data["clusters"].append(cluster_data)
        
        try:
            with open(clusters_file, 'w') as f:
                json.dump(clusters_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"Created clusters data saved to: {clusters_file}")
            self.print_colored(Colors.CYAN, f"💾 Cluster details saved to: {clusters_file}")
            
            # Also create a simple list format for easy reference
            simple_file = f"eks_clusters_simple_{timestamp}.txt"
            with open(simple_file, 'w') as f:
                f.write(f"# EKS Clusters Created on {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"# Created by: {self.current_user}\n")
                f.write(f"# Total clusters: {len(successful_clusters)}\n\n")
                
                for i, cluster_info in enumerate(successful_clusters, 1):
                    user = cluster_info['user']
                    instance_type = cluster_info.get('instance_type', 'c6a.large')
                    f.write(f"{i}. {cluster_info['cluster_name']}\n")
                    f.write(f"   Account: {cluster_info['account_key']} ({cluster_info['account_id']})\n")
                    f.write(f"   User: {user['username']}\n")
                    f.write(f"   Region: {user['region']}\n")
                    f.write(f"   Max Nodes: {cluster_info['max_nodes']}\n")
                    f.write(f"   Instance Type: {instance_type}\n")
                    f.write(f"   Access: aws eks update-kubeconfig --region {user['region']} --name {cluster_info['cluster_name']} --profile {user['username']}\n")
                    f.write("\n")
            
            self.print_colored(Colors.CYAN, f"📄 Simple cluster list saved to: {simple_file}")
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to save cluster details: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Failed to save cluster details: {str(e)}")

    def generate_final_commands(self) -> None:
        """Generate final kubectl commands and save to file"""
        if not self.kubectl_commands:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        commands_file = f"kubectl_commands_{timestamp}.txt"
        
        self.print_colored(Colors.CYAN, f"\n💾 Commands saved to: {commands_file}")
        
        with open(commands_file, 'w') as f:
            f.write(f"# EKS Cluster kubectl Commands\n")
            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"# Total clusters: {len(self.kubectl_commands)}\n")
            f.write(f"# Instance Types: Configurable per cluster\n")
            f.write(f"# Default Nodes: 1\n\n")
            
            for i, cmd_info in enumerate(self.kubectl_commands, 1):
                command_block = f"""
    # Cluster {i}: {cmd_info['cluster_name']}
    # Account: {cmd_info['account']}
    # User: {cmd_info['user']}
    # Region: {cmd_info['region']}
    # Instance Type: {cmd_info['instance_type']}
    # Default Nodes: {cmd_info['default_nodes']}
    # Max Nodes: {cmd_info['max_nodes']}
    # User Access Configured: {cmd_info['auth_configured']}
    # Access Verified: {cmd_info.get('access_verified', 'Unknown')}
    # Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}


    # Admin access (using admin credentials)
    {cmd_info['admin_command']}

    # User access (configure AWS profile first)
    # aws configure set aws_access_key_id {cmd_info['user_access_key']} --profile {cmd_info['user']}
    # aws configure set aws_secret_access_key {cmd_info['user_secret_key']} --profile {cmd_info['user']}
    # aws configure set region {cmd_info['region']} --profile {cmd_info['user']}
    {cmd_info['user_command']}

    # Test cluster access
    kubectl get nodes
    kubectl get pods --all-namespaces

    # Scale the node group (example - {cmd_info['instance_type']} instances)
    aws eks update-nodegroup-config --cluster-name {cmd_info['cluster_name']} --nodegroup-name {cmd_info['cluster_name']}-nodegroup --scaling-config minSize=1,maxSize={cmd_info['max_nodes']},desiredSize=2 --region {cmd_info['region']}

    {'-'*80}
    """
                f.write(command_block)

    def verify_cluster_access(self, cluster_info: Dict, user_credentials: Dict) -> bool:
        """Verify cluster access using IAM user credentials"""
        try:
            cluster_name = cluster_info['cluster_name']
            region = cluster_info['user']['region']
            username = cluster_info['user']['username']
            
            self.log_operation('INFO', f"Verifying cluster access for {username} on {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🧪 Verifying cluster access for {username}...")
            
            # Set up user environment
            user_env = os.environ.copy()
            user_env['AWS_ACCESS_KEY_ID'] = user_credentials['access_key_id']
            user_env['AWS_SECRET_ACCESS_KEY'] = user_credentials['secret_access_key']
            user_env['AWS_DEFAULT_REGION'] = region
            
            import subprocess
            
            # Step 1: Update kubeconfig with user credentials
            self.print_colored(Colors.CYAN, f"   🔄 Updating kubeconfig with user credentials...")
            
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]
            
            update_result = subprocess.run(update_cmd, env=user_env, capture_output=True, text=True, timeout=120)
            
            if update_result.returncode != 0:
                self.log_operation('ERROR', f"Failed to update kubeconfig for {username}: {update_result.stderr}")
                self.print_colored(Colors.RED, f"   ❌ Failed to update kubeconfig")
                return False
            
            self.print_colored(Colors.GREEN, f"   ✅ Kubeconfig updated successfully")
            
            # Step 2: Test kubectl get nodes
            self.print_colored(Colors.CYAN, f"   🔍 Testing 'kubectl get nodes'...")
            
            nodes_cmd = ['kubectl', 'get', 'nodes', '--no-headers']
            nodes_result = subprocess.run(nodes_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if nodes_result.returncode == 0:
                node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
                node_count = len(node_lines)
                
                self.print_colored(Colors.GREEN, f"   ✅ Found {node_count} node(s)")
                self.log_operation('INFO', f"kubectl get nodes successful - {node_count} nodes found")
                
                # Log node details
                for i, node_line in enumerate(node_lines, 1):
                    node_parts = node_line.split()
                    if len(node_parts) >= 2:
                        node_name = node_parts[0]
                        node_status = node_parts[1]
                        self.print_colored(Colors.CYAN, f"      {i}. {node_name} ({node_status})")
                        self.log_operation('DEBUG', f"Node {i}: {node_line}")
            else:
                self.log_operation('ERROR', f"kubectl get nodes failed for {username}: {nodes_result.stderr}")
                self.print_colored(Colors.RED, f"   ❌ kubectl get nodes failed")
                return False
            
            # Step 3: Test kubectl get pods
            self.print_colored(Colors.CYAN, f"   🔍 Testing 'kubectl get pods --all-namespaces'...")
            
            pods_cmd = ['kubectl', 'get', 'pods', '--all-namespaces', '--no-headers']
            pods_result = subprocess.run(pods_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if pods_result.returncode == 0:
                pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
                pod_count = len(pod_lines)
                
                self.print_colored(Colors.GREEN, f"   ✅ Found {pod_count} pod(s) across all namespaces")
                self.log_operation('INFO', f"kubectl get pods successful - {pod_count} pods found")
                
                # Count pods by namespace
                namespace_counts = {}
                for pod_line in pod_lines:
                    parts = pod_line.split()
                    if len(parts) >= 1:
                        namespace = parts[0]
                        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
                
                for namespace, count in namespace_counts.items():
                    self.print_colored(Colors.CYAN, f"      {namespace}: {count} pod(s)")
            else:
                self.log_operation('ERROR', f"kubectl get pods failed for {username}: {pods_result.stderr}")
                self.print_colored(Colors.RED, f"   ❌ kubectl get pods failed")
                return False
            
            # Step 4: Test cluster-info
            self.print_colored(Colors.CYAN, f"   🔍 Testing 'kubectl cluster-info'...")
            
            info_cmd = ['kubectl', 'cluster-info']
            info_result = subprocess.run(info_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if info_result.returncode == 0:
                self.print_colored(Colors.GREEN, f"   ✅ Cluster info retrieved successfully")
                self.log_operation('INFO', f"kubectl cluster-info successful")
                self.log_operation('DEBUG', f"Cluster info: {info_result.stdout}")
            else:
                self.log_operation('WARNING', f"kubectl cluster-info failed for {username}: {info_result.stderr}")
                self.print_colored(Colors.YELLOW, f"   ⚠️  kubectl cluster-info failed (non-critical)")
            
            self.print_colored(Colors.GREEN, f"✅ Cluster access verification successful for {username}")
            self.log_operation('INFO', f"Cluster access verification completed successfully for {username}")
            
            return True
            
        except subprocess.TimeoutExpired:
            self.log_operation('ERROR', f"Cluster verification timed out for {username}")
            self.print_colored(Colors.RED, f"   ❌ Verification timed out")
            return False
        except Exception as e:
            self.log_operation('ERROR', f"Cluster verification failed for {username}: {str(e)}")
            self.print_colored(Colors.RED, f"   ❌ Verification failed: {str(e)}")
            return False
    
    def generate_individual_user_instruction(self, cluster_info: Dict, kubectl_info: Dict) -> None:
        """Generate user-specific instruction file immediately after cluster creation"""
        try:
            user = cluster_info['user']
            username = user['username']
            cluster_name = cluster_info['cluster_name']
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            user_file = f"user_instructions_{username}_{cluster_name}_{timestamp}.txt"
            
            with open(user_file, 'w') as f:
                f.write(f"# EKS Cluster Access Instructions for {username}\n")
                f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"# Cluster: {cluster_name}\n")
                f.write(f"# Region: {kubectl_info['region']}\n")
                f.write(f"# Instance Type: {kubectl_info['instance_type']}\n")
                f.write(f"# Default Nodes: {kubectl_info['default_nodes']}\n")
                f.write(f"# Max Nodes: {kubectl_info['max_nodes']}\n")
                f.write(f"# Account: {kubectl_info['account']}\n")
                f.write(f"# Auth Configured: {kubectl_info['auth_configured']}\n")
                f.write(f"# Access Verified: {kubectl_info['access_verified']}\n\n")
                
                f.write("## Prerequisites\n")
                f.write("1. Install AWS CLI: https://aws.amazon.com/cli/\n")
                f.write("2. Install kubectl: https://kubernetes.io/docs/tasks/tools/\n\n")
                
                f.write("## AWS Configuration\n")
                f.write(f"aws configure set aws_access_key_id {kubectl_info['user_access_key']} --profile {username}\n")
                f.write(f"aws configure set aws_secret_access_key {kubectl_info['user_secret_key']} --profile {username}\n")
                f.write(f"aws configure set region {kubectl_info['region']} --profile {username}\n\n")
                
                f.write("## Cluster Access\n")
                f.write(f"{kubectl_info['user_command']}\n\n")
                
                f.write("## Test Commands\n")
                f.write("kubectl get nodes\n")
                f.write("kubectl get pods --all-namespaces\n")
                f.write("kubectl cluster-info\n\n")
                
                f.write("## Cluster Details\n")
                f.write(f"- Instance Type: {kubectl_info['instance_type']} (selected during creation)\n")
                f.write(f"- Default Nodes: {kubectl_info['default_nodes']}\n")
                f.write(f"- Maximum Scalable Nodes: {kubectl_info['max_nodes']}\n")
                f.write(f"- Capacity Type: {cluster_info.get('capacity_type', 'SPOT')}\n\n")
                
                f.write("## Scaling Example\n")
                f.write(f"# Scale up the node group\n")
                f.write(f"aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name {cluster_name}-nodegroup --scaling-config minSize=1,maxSize={kubectl_info['max_nodes']},desiredSize=2 --region {kubectl_info['region']}\n\n")
                
                f.write("## Troubleshooting\n")
                f.write("# If you get authentication errors:\n")
                f.write("# 1. Verify your AWS credentials are correct\n")
                f.write("# 2. Ensure your user has been granted access to the cluster\n")
                f.write("# 3. Try updating the kubeconfig again\n")
                f.write(f"# 4. Contact administrator if issues persist\n\n")
                
                f.write("## Additional Resources\n")
                f.write("- EKS User Guide: https://docs.aws.amazon.com/eks/latest/userguide/\n")
                f.write("- kubectl Cheat Sheet: https://kubernetes.io/docs/reference/kubectl/cheatsheet/\n")
            
            self.log_operation('INFO', f"Individual user instruction file created: {user_file}")
            self.print_colored(Colors.CYAN, f"📄 User instructions saved: {user_file}")
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create user instruction file for {username}: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Failed to create user instruction file: {str(e)}")
    
    def generate_user_instructions(self) -> None:
        """Generate user-specific instruction files in eks/user_login directory"""
        if not self.kubectl_commands:
            return
        
        # Create directory structure if it doesn't exist
        base_dir = "eks"
        user_login_dir = os.path.join(base_dir, "user_login")
        
        try:
            if not os.path.exists(base_dir):
                os.makedirs(base_dir, exist_ok=True)
                self.log_operation('INFO', f"Created directory: {base_dir}")
                self.print_colored(Colors.CYAN, f"📁 Created directory: {base_dir}")
            
            if not os.path.exists(user_login_dir):
                os.makedirs(user_login_dir, exist_ok=True)
                self.log_operation('INFO', f"Created directory: {user_login_dir}")
                self.print_colored(Colors.CYAN, f"📁 Created directory: {user_login_dir}")
                
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create directories: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Failed to create directories: {str(e)}")
            # Fallback to current directory
            user_login_dir = "."
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create individual instruction files for each user
        for cmd_info in self.kubectl_commands:
            user_file = os.path.join(user_login_dir, f"user_instructions_{cmd_info['user']}_{timestamp}.txt")
            
            try:
                with open(user_file, 'w') as f:
                    f.write(f"# EKS Cluster Access Instructions for {cmd_info['user']}\n")
                    f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                    f.write(f"# Generated by: varadharajaan\n")
                    f.write(f"# Cluster: {cmd_info['cluster_name']}\n")
                    f.write(f"# Region: {cmd_info['region']}\n")
                    f.write(f"# Instance Type: {cmd_info['instance_type']}\n")
                    f.write(f"# Default Nodes: {cmd_info['default_nodes']}\n")
                    f.write(f"# Max Nodes: {cmd_info['max_nodes']}\n\n")
                    
                    f.write("## Prerequisites\n")
                    f.write("1. Install AWS CLI: https://aws.amazon.com/cli/\n")
                    f.write("2. Install kubectl: https://kubernetes.io/docs/tasks/tools/\n\n")
                    
                    f.write("## AWS Configuration\n")
                    f.write(f"aws configure set aws_access_key_id {cmd_info['user_access_key']} --profile {cmd_info['user']}\n")
                    f.write(f"aws configure set aws_secret_access_key {cmd_info['user_secret_key']} --profile {cmd_info['user']}\n")
                    f.write(f"aws configure set region {cmd_info['region']} --profile {cmd_info['user']}\n\n")
                    
                    f.write("## Cluster Access\n")
                    f.write(f"{cmd_info['user_command']}\n\n")
                    
                    f.write("## Test Commands\n")
                    f.write("kubectl get nodes\n")
                    f.write("kubectl get pods --all-namespaces\n")
                    f.write("kubectl cluster-info\n\n")
                    
                    f.write("## Cluster Details\n")
                    f.write(f"- Instance Type: {cmd_info['instance_type']} (compute optimized)\n")
                    f.write(f"- Default Nodes: {cmd_info['default_nodes']}\n")
                    f.write(f"- Maximum Scalable Nodes: {cmd_info['max_nodes']}\n\n")
                    
                    f.write("## Scaling Example\n")
                    f.write(f"aws eks update-nodegroup-config --cluster-name {cmd_info['cluster_name']} --nodegroup-name {cmd_info['cluster_name']}-nodegroup --scaling-config minSize=1,maxSize={cmd_info['max_nodes']},desiredSize=2 --region {cmd_info['region']} --profile {cmd_info['user']}\n\n")
                    
                    f.write("## Troubleshooting\n")
                    f.write("# If you get authentication errors:\n")
                    f.write("# 1. Verify your AWS credentials are correct\n")
                    f.write("# 2. Ensure your user has been granted access to the cluster\n")
                    f.write("# 3. Try updating the kubeconfig again\n")
                    f.write("# 4. Contact administrator if issues persist\n\n")
                    
                    f.write("## Additional Resources\n")
                    f.write("- EKS User Guide: https://docs.aws.amazon.com/eks/latest/userguide/\n")
                    f.write("- kubectl Cheat Sheet: https://kubernetes.io/docs/reference/kubectl/cheatsheet/\n")
                
                self.log_operation('INFO', f"User instruction file created: {user_file}")
                self.print_colored(Colors.CYAN, f"📄 User instructions saved: {user_file}")
                
            except Exception as e:
                self.log_operation('ERROR', f"Failed to create user instruction file for {cmd_info['user']}: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Failed to create user instruction file for {cmd_info['user']}: {str(e)}")
        
        self.print_colored(Colors.GREEN, f"✅ Generated {len(self.kubectl_commands)} user instruction files in {user_login_dir}/")

def main():
    """Main entry point"""
    try:
        # Run the EKS manager
        manager = EKSClusterManager()
        manager.run()
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()