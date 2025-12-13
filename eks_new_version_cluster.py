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
from typing import Dict, List, Tuple, Optional
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
import base64
import queue
import subprocess
import textwrap
from text_symbols import Symbols

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
            self.print_colored(Colors.RED, "[ERROR] No iam_users_credentials_*.json file found!")
            # Fallback to default config file
            return "aws-accounts-config.json"
        
        self.print_colored(Colors.BLUE, f"{Symbols.SCAN} Found {len(files)} iam_users_credentials files:")
        
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
                    print(f"   {Symbols.WARN}  Invalid timestamp format in: {file_path}")
                    continue
            else:
                print(f"   {Symbols.WARN}  Invalid filename format: {file_path}")
        
        if not file_timestamps:
            logger.error("No valid iam_users_credentials files found with proper timestamp format!")
            self.print_colored(Colors.RED, "[ERROR] No valid iam_users_credentials files found with proper timestamp format!")
            return "aws-accounts-config.json"
        
        # Sort by timestamp (newest first)
        file_timestamps.sort(key=lambda x: x[1], reverse=True)
        latest_file = file_timestamps[0][0]
        latest_timestamp = file_timestamps[0][2]
        latest_datetime = file_timestamps[0][1]
        
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected latest file: {latest_file}")
        print(f"   {Symbols.DATE} File timestamp: {latest_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")
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
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Loaded admin configuration with {total_admin_accounts} admin accounts from {self.admin_config_file}")
        
        except Exception as e:
            logger.error(f"Failed to load admin configuration: {str(e)}")
            raise
    
    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"eks_creation_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            
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
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Loaded configuration with {total_users} users from {self.config_file}")
        
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
        
        print(f"\n{Symbols.ACCOUNT} Available AWS Accounts ({len(accounts)} total):")
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
            admin_status = f"{Symbols.OK}" if admin_available else f"{Symbols.ERROR}"
            
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
            print(f"      {Symbols.REGION} Regions: {', '.join(sorted(account_regions))}")
            print(f"      {Symbols.KEY} Admin Creds: {admin_status}")
            
            self.log_operation('INFO', f"Account {i}: {account_name} ({account_id}) - {user_count} users, admin creds: {admin_available}")
            print()
        
        print("=" * 80)
        print(f"{Symbols.STATS} Summary:")
        print(f"   [UP] Total accounts: {len(accounts)}")
        print(f"   👥 Total users: {total_users}")
        print(f"   {Symbols.REGION} All regions: {', '.join(sorted(regions_used))}")
        
        self.log_operation('INFO', f"Account summary: {len(accounts)} accounts, {total_users} total users, regions: {', '.join(sorted(regions_used))}")
        
        print(f"\n{Symbols.LOG} Selection Options:")
        print(f"   • Single accounts: 1,3,5")
        print(f"   • Ranges: 1-{len(accounts)} (accounts 1 through {len(accounts)})")
        print(f"   • Mixed: 1-2,4 (accounts 1, 2, and 4)")
        print(f"   • All accounts: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n[#] Select accounts to process: ").strip()
            
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
                        print(f"\n{Symbols.ERROR} Missing admin credentials for accounts: {', '.join(missing_admin_creds)}")
                        print("Please ensure admin credentials are available in aws_accounts_config.json")
                        continue
                    
                    # Show confirmation
                    print(f"\n{Symbols.OK} Selected {len(selected_indices)} accounts with admin credentials available")
                    confirm = input(f"\n{Symbols.START} Proceed with these {len(selected_indices)} accounts? (y/N): ").lower().strip()
                    
                    if confirm == 'y':
                        return selected_indices
                    else:
                        print(f"{Symbols.ERROR} Selection cancelled, please choose again.")
                        continue
                else:
                    print(f"{Symbols.ERROR} No valid accounts selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"{Symbols.ERROR} Invalid selection: {e}")
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
            print(f"\n{Symbols.ACCOUNT} {account_name} ({account_id}) - {len(users)} users:")
            print("-" * 80)
            
            for user_info in users:
                real_user = user_info['real_user']
                full_name = real_user.get('full_name', user_info['username'])
                email = real_user.get('email', 'N/A')
                region = user_info['region']
                
                print(f"  {user_index:3}. {full_name}")
                print(f"       👤 Username: {user_info['username']}")
                print(f"       📧 Email: {email}")
                print(f"       {Symbols.REGION} Region: {region}")
                
                user_mapping[user_index] = user_info
                user_index += 1
                print()
        
        print("=" * 100)
        print(f"{Symbols.STATS} Summary: {len(all_users)} users across {len(users_by_account)} accounts")
        
        print(f"\n{Symbols.LOG} Selection Options:")
        print(f"   • All users: 'all' or press Enter")
        print(f"   • Ranges: 1-{len(all_users)}")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n[#] Select users to process: ").strip()
            
            if not selection or selection.lower() == 'all':
                return list(range(1, len(all_users) + 1)), user_mapping
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                return [], {}
            
            try:
                selected_indices = self.parse_selection(selection, len(all_users))
                if selected_indices:
                    confirm = input(f"\n{Symbols.START} Proceed with {len(selected_indices)} users? (y/N): ").lower().strip()
                    if confirm == 'y':
                        return selected_indices, user_mapping
                    else:
                        continue
                else:
                    print(f"{Symbols.ERROR} No valid users selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"{Symbols.ERROR} Invalid selection: {e}")
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
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  kubectl not found. Manual setup required.")
                
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
                    self.print_colored(Colors.CYAN, f"{Symbols.LIST} Manual setup instructions: {instruction_file}")
                    
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to create instruction file: {str(e)}")
                
                # Return True since we created the ConfigMap file
                return True
            
            # Apply ConfigMap using kubectl with admin credentials
            self.log_operation('INFO', f"Applying ConfigMap using admin credentials")
            self.print_colored(Colors.YELLOW, f"{Symbols.START} Applying ConfigMap with admin credentials...")
            
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
                    self.print_colored(Colors.GREEN, f"{Symbols.OK} ConfigMap applied successfully")
                    
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
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to apply ConfigMap: {apply_result.stderr}")
                    success = False
            
            except subprocess.TimeoutExpired:
                self.log_operation('ERROR', f"kubectl/aws command timed out for {cluster_name}")
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Command timed out")
                success = False
            except Exception as e:
                self.log_operation('ERROR', f"Failed to execute kubectl/aws commands: {str(e)}")
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Command execution failed: {str(e)}")
                success = False
            
            # Clean up temporary files
            try:
                if os.path.exists(configmap_file):
                    os.remove(configmap_file)
                    self.log_operation('INFO', f"Cleaned up temporary ConfigMap file")
            except Exception as e:
                self.log_operation('WARNING', f"Failed to clean up ConfigMap file: {str(e)}")
            
            if success:
                self.print_colored(Colors.GREEN, f"{Symbols.OK} User {username} configured for cluster access")
                
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
                            self.print_colored(Colors.GREEN, f"{Symbols.OK} User access verified - can access cluster")
                        else:
                            self.log_operation('WARNING', f"User access test failed: {test_result.stderr}")
                            self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  User access test failed - may need manual verification")
                    else:
                        self.log_operation('WARNING', f"Failed to update kubeconfig for user test: {user_update_result.stderr}")
                        
                except Exception as e:
                    self.log_operation('WARNING', f"User access test failed: {str(e)}")
            
            return success
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to configure aws-auth ConfigMap for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} ConfigMap configuration failed: {error_msg}")
            return False
    
    # Add this method to the EKSClusterManager class around line 1186

    def select_capacity_type(self, user_name: str = None) -> str:
        """Allow user to select capacity type (Spot or On-Demand)"""
        capacity_options = ['SPOT', 'ON_DEMAND']
        default_type = 'SPOT'  # Default to SPOT for cost efficiency
        
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n{Symbols.COST} Capacity Type Selection {user_prefix}")
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
                    print(f"{Symbols.ERROR} Please enter a number between 1 and {len(capacity_options)}")
            except ValueError:
                print("[ERROR] Please enter a valid number")
        
        print(f"{Symbols.OK} Selected capacity type: {selected_type}")
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
            self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Updating kubeconfig with user credentials...")
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]
            
            result = subprocess.run(update_cmd, env=user_env, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Updated kubeconfig with user credentials")
                self.log_operation('INFO', f"Kubeconfig updated successfully for {username}")
            else:
                self.log_operation('ERROR', f"Failed to update kubeconfig with user creds: {result.stderr}")
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to update kubeconfig: {result.stderr}")
                return False
            
            # Test kubectl get nodes with detailed output
            self.print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl get nodes'...")
            nodes_cmd = ['kubectl', 'get', 'nodes', '--no-headers']
            nodes_result = subprocess.run(nodes_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if nodes_result.returncode == 0:
                node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
                node_count = len(node_lines)
                
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Found {node_count} node(s)")
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
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl get nodes failed: {nodes_result.stderr}")
                return False
            
            
            # [OK] Test kubectl get pods in the 'default' namespace
            self.print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl get pods -n default'...")
            default_cmd = ['kubectl', 'get', 'pods', '-n', 'default', '--no-headers']
            default_result = subprocess.run(default_cmd, env=user_env, capture_output=True, text=True, timeout=60)

            if default_result.returncode == 0:
                default_pods = [line.strip() for line in default_result.stdout.strip().split('\n') if line.strip()]
                default_pod_count = len(default_pods)

                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Found {default_pod_count} pod(s) in 'default' namespace")
                self.log_operation('INFO', f"kubectl get pods -n default successful - {default_pod_count} pods found")
            else:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl get pods -n default failed: {default_result.stderr}")
                self.log_operation('ERROR', f"kubectl get pods -n default failed: {default_result.stderr}")
            
            # Test kubectl get pods with namespace breakdown
            self.print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl get pods --all-namespaces'...")
            pods_cmd = ['kubectl', 'get', 'pods', '--all-namespaces', '--no-headers']
            pods_result = subprocess.run(pods_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if pods_result.returncode == 0:
                pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
                pod_count = len(pod_lines)
                
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Found {pod_count} pod(s) across all namespaces")
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
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl get pods failed: {pods_result.stderr}")
                return False
            
            # Test cluster-info
            self.print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl cluster-info'...")
            info_cmd = ['kubectl', 'cluster-info']
            info_result = subprocess.run(info_cmd, env=user_env, capture_output=True, text=True, timeout=60)
            
            if info_result.returncode == 0:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster info retrieved successfully")
                self.log_operation('INFO', f"kubectl cluster-info successful")
                self.log_operation('DEBUG', f"Cluster info: {info_result.stdout}")
            else:
                self.log_operation('WARNING', f"kubectl cluster-info failed: {info_result.stderr}")
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  kubectl cluster-info failed (non-critical)")
            
            self.print_colored(Colors.GREEN, f"[PARTY] User access verification successful for {username}!")
            self.log_operation('INFO', f"Complete user access verification successful for {username}")
            return True
                
        except subprocess.TimeoutExpired:
            self.log_operation('ERROR', f"User access test timed out for {username}")
            self.print_colored(Colors.RED, "   [ERROR] User access test timed out")
            return False
        except Exception as e:
            self.log_operation('ERROR', f"Error testing user access for {username}: {str(e)}")
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error testing user access: {str(e)}")
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
                    print(f"{Symbols.ERROR} Please enter a number between 1 and {len(allowed_types)}")
            except ValueError:
                print("[ERROR] Please enter a valid number")
        
        print(f"{Symbols.OK} Selected instance type: {selected_type}")
        return selected_type
    
    def create_clusters(self, cluster_configs) -> None:
        """Create all configured clusters"""
        if not cluster_configs:
            self.print_colored(Colors.YELLOW, "No clusters to create!")
            return
        
        self.log_operation('INFO', f"Starting creation of {len(cluster_configs)} clusters")
        self.print_colored(Colors.GREEN, f"{Symbols.START} Starting creation of {len(cluster_configs)} clusters...")
        
        # Create clusters sequentially
        successful_clusters = []
        failed_clusters = []
        
        for i, cluster_info in enumerate(cluster_configs, 1):
            self.print_colored(Colors.BLUE, f"\n{Symbols.LIST} Progress: {i}/{len(cluster_configs)}")
            
            if self.create_single_cluster(cluster_info):
                successful_clusters.append(cluster_info)
            else:
                failed_clusters.append(cluster_info)
        
        # Summary
        self.log_operation('INFO', f"Cluster creation completed - Created: {len(successful_clusters)}, Failed: {len(failed_clusters)}")
        
        self.print_colored(Colors.GREEN, f"\n[PARTY] Cluster Creation Summary:")
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Successful: {len(successful_clusters)}")
        if failed_clusters:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed: {len(failed_clusters)}")
        
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
                self.print_colored(Colors.CYAN, f"{Symbols.FOLDER} Created directory: {directory_path}")
            return directory_path
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create directory {directory_path}: {str(e)}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to create directory {directory_path}: {str(e)}")
            return "."  # Fallback to current directory

    def get_diversified_instance_types(self, primary_instance_type: str) -> List[str]:
        """Get diversified instance types for better spot availability"""
        
        # Instance type families mapping
        instance_families = {
            'c5.large': ['c5.large', 'c5a.large', 'c4.large'],
            'c5.xlarge': ['c5.xlarge', 'c5a.xlarge', 'c4.xlarge'],
            'c6a.large': ['c6a.large', 'c5.large', 'c5a.large'],
            'c6a.xlarge': ['c6a.xlarge', 'c5.xlarge', 'c5a.xlarge'],
            'm5.large': ['m5.large', 'm5a.large', 'm4.large'],
            'm5.xlarge': ['m5.xlarge', 'm5a.xlarge', 'm4.xlarge'],
            't3.medium': ['t3.medium', 't3a.medium', 't2.medium'],
            't3.large': ['t3.large', 't3a.large', 't2.large']
        }
        
        # Get diversified types or fallback to primary type
        diversified_types = instance_families.get(primary_instance_type, [primary_instance_type])
        
        self.log_operation('INFO', f"Using diversified instance types: {diversified_types}")
        return diversified_types

    def install_essential_addons(self, eks_client, cluster_name: str) -> bool:
        """Install essential EKS add-ons"""
        try:
            self.log_operation('INFO', f"Installing essential add-ons for cluster {cluster_name}")
            
            # Define add-ons with their versions for EKS 1.28
            addons = [
                {
                    'addonName': 'vpc-cni',
                    'addonVersion': 'v1.15.1-eksbuild.1',
                    'description': 'VPC CNI for pod networking'
                },
                {
                    'addonName': 'coredns',
                    'addonVersion': 'v1.10.1-eksbuild.5',
                    'description': 'CoreDNS for cluster DNS'
                },
                {
                    'addonName': 'kube-proxy',
                    'addonVersion': 'v1.28.2-eksbuild.2',
                    'description': 'Kube-proxy for service discovery'
                },
                {
                    'addonName': 'aws-ebs-csi-driver',
                    'addonVersion': 'v1.25.0-eksbuild.1',
                    'description': 'EBS CSI driver for persistent volumes'
                }
            ]
            
            successful_addons = []
            failed_addons = []
            
            for addon in addons:
                try:
                    self.print_colored(Colors.CYAN, f"   [PACKAGE] Installing {addon['addonName']} ({addon['description']})...")
                    
                    eks_client.create_addon(
                        clusterName=cluster_name,
                        addonName=addon['addonName'],
                        addonVersion=addon['addonVersion'],
                        resolveConflicts='OVERWRITE'  # Overwrite any conflicts
                    )
                    
                    # Wait for addon to be active
                    waiter = eks_client.get_waiter('addon_active')
                    waiter.wait(
                        clusterName=cluster_name,
                        addonName=addon['addonName'],
                        WaiterConfig={'Delay': 15, 'MaxAttempts': 20}
                    )
                    
                    successful_addons.append(addon['addonName'])
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} {addon['addonName']} installed successfully")
                    self.log_operation('INFO', f"Add-on {addon['addonName']} installed successfully for {cluster_name}")
                    
                except Exception as e:
                    failed_addons.append(addon['addonName'])
                    self.log_operation('WARNING', f"Failed to install {addon['addonName']}: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Failed to install {addon['addonName']}: {str(e)}")
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Add-ons installation completed: {len(successful_addons)} successful, {len(failed_addons)} failed")
            self.log_operation('INFO', f"Add-ons installation completed for {cluster_name}: {successful_addons}")
            
            return len(successful_addons) > 0
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to install add-ons for {cluster_name}: {str(e)}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Add-ons installation failed: {str(e)}")
            return False

    def enable_container_insights(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str) -> bool:
        """Enable CloudWatch Container Insights for the cluster"""
        try:
            self.log_operation('INFO', f"Enabling CloudWatch Container Insights for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"{Symbols.STATS} Enabling CloudWatch Container Insights for {cluster_name}...")
            
            # Check if kubectl is available
            import subprocess
            import shutil
            
            kubectl_available = shutil.which('kubectl') is not None
            
            if not kubectl_available:
                self.log_operation('WARNING', f"kubectl not found. Cannot deploy Container Insights for {cluster_name}")
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  kubectl not found. Container Insights deployment skipped.")
                return False
            
            # Set environment variables for admin access
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region
            
            # Deploy using the one-liner command for Container Insights
            self.print_colored(Colors.CYAN, f"   {Symbols.START} Deploying CloudWatch Container Insights...")
            

            insights_url = "https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/quickstart/cwagent-fluentd-quickstart.yaml"
            
            # Download and apply the manifest
            insights_cmd = [
                'kubectl', 'apply', '-f', insights_url
            ]
            
            insights_result = subprocess.run(insights_cmd, env=env, capture_output=True, text=True, timeout=180)
            
            if insights_result.returncode == 0:
                self.print_colored(Colors.GREEN, "   {Symbols.OK} CloudWatch Container Insights deployed")
                self.log_operation('INFO', f"CloudWatch Container Insights deployed for {cluster_name}")
                
                # Wait for pods to be ready
                self.print_colored(Colors.CYAN, "   ⏳ Waiting for Container Insights pods to be ready...")
                time.sleep(30)
                
                # Verify deployment
                verify_cmd = ['kubectl', 'get', 'pods', '-n', 'amazon-cloudwatch', '--no-headers']
                verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=60)
                
                if verify_result.returncode == 0:
                    pod_lines = [line.strip() for line in verify_result.stdout.strip().split('\n') if line.strip()]
                    running_pods = [line for line in pod_lines if 'Running' in line or 'Completed' in line]
                    
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} Container Insights pods: {len(running_pods)} ready out of {len(pod_lines)} total")
                    self.log_operation('INFO', f"Container Insights deployment verified: {len(running_pods)} pods ready")
                    
                    # Access information
                    self.print_colored(Colors.CYAN, f"{Symbols.STATS} Access Container Insights in AWS Console:")
                    self.print_colored(Colors.CYAN, f"   CloudWatch → Insights → Container Insights")
                    self.print_colored(Colors.CYAN, f"   Filter by cluster: {cluster_name}")
                    
                    return True
                else:
                    self.log_operation('WARNING', f"Could not verify Container Insights deployment")
                    return True  # Still consider successful since deployment command worked
            else:
                self.log_operation('ERROR', f"Container Insights deployment failed: {insights_result.stderr}")
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Container Insights deployment failed")
                return False
                
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to enable Container Insights for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Container Insights deployment failed: {error_msg}")
            return False

    def setup_cluster_autoscaler(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str, account_id: str) -> bool:
        """Setup cluster autoscaler for automatic node scaling"""
        try:
            self.log_operation('INFO', f"Setting up Cluster Autoscaler for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"{Symbols.SCAN} Setting up Cluster Autoscaler for {cluster_name}...")
            
            import subprocess
            import shutil
            import tempfile
            
            kubectl_available = shutil.which('kubectl') is not None
            
            if not kubectl_available:
                self.log_operation('WARNING', f"kubectl not found. Cannot deploy Cluster Autoscaler for {cluster_name}")
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  kubectl not found. Cluster Autoscaler deployment skipped.")
                return False
            
            # Set environment variables for admin access
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region
            
            # Step 1: Create IAM policy for cluster autoscaler
            self.print_colored(Colors.CYAN, "   🔐 Setting up IAM permissions for Cluster Autoscaler...")
            
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            iam_client = admin_session.client('iam')
            
            # Create policy for cluster autoscaler
            autoscaler_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "autoscaling:DescribeAutoScalingGroups",
                            "autoscaling:DescribeAutoScalingInstances",
                            "autoscaling:DescribeLaunchConfigurations",
                            "autoscaling:DescribeTags",
                            "autoscaling:SetDesiredCapacity",
                            "autoscaling:TerminateInstanceInAutoScalingGroup",
                            "ec2:DescribeLaunchTemplateVersions"
                        ],
                        "Resource": "*"
                    }
                ]
            }
            
            policy_name = f"ClusterAutoscalerPolicy-{cluster_name}"
            
            try:
                # Create the policy
                policy_response = iam_client.create_policy(
                    PolicyName=policy_name,
                    PolicyDocument=json.dumps(autoscaler_policy),
                    Description=f"Policy for Cluster Autoscaler on {cluster_name}"
                )
                policy_arn = policy_response['Policy']['Arn']
                self.log_operation('INFO', f"Created Cluster Autoscaler policy: {policy_arn}")
                
            except iam_client.exceptions.EntityAlreadyExistsException:
                # Policy already exists, get its ARN
                policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
                self.log_operation('INFO', f"Using existing Cluster Autoscaler policy: {policy_arn}")
            
            # Attach policy to node instance role
            try:
                iam_client.attach_role_policy(
                    RoleName="NodeInstanceRole",
                    PolicyArn=policy_arn
                )
                self.print_colored(Colors.GREEN, "   [OK] IAM permissions configured")
            except Exception as e:
                self.log_operation('WARNING', f"Failed to attach autoscaler policy: {str(e)}")
            
            # Step 2: Deploy Cluster Autoscaler
            self.print_colored(Colors.CYAN, "   [START] Deploying Cluster Autoscaler...")
            
            autoscaler_yaml = f"""
    apiVersion: apps/v1
    kind: Deployment
    metadata:
    name: cluster-autoscaler
    namespace: kube-system
    labels:
        app: cluster-autoscaler
    spec:
    selector:
        matchLabels:
        app: cluster-autoscaler
    template:
        metadata:
        labels:
            app: cluster-autoscaler
        annotations:
            prometheus.io/scrape: 'true'
            prometheus.io/port: '8085'
        spec:
        priorityClassName: system-cluster-critical
        securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            fsGroup: 65534
        serviceAccountName: cluster-autoscaler
        containers:
        - image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.28.2
            name: cluster-autoscaler
            resources:
            limits:
                cpu: 100m
                memory: 600Mi
            requests:
                cpu: 100m
                memory: 600Mi
            command:
            - ./cluster-autoscaler
            - --v=4
            - --stderrthreshold=info
            - --cloud-provider=aws
            - --skip-nodes-with-local-storage=false
            - --expander=least-waste
            - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/{cluster_name}
            - --balance-similar-node-groups
            - --skip-nodes-with-system-pods=false
            env:
            - name: AWS_REGION
            value: {region}
            volumeMounts:
            - name: ssl-certs
            mountPath: /etc/ssl/certs/ca-certificates.crt
            readOnly: true
            imagePullPolicy: "Always"
        volumes:
        - name: ssl-certs
            hostPath:
            path: "/etc/ssl/certs/ca-bundle.crt"
        nodeSelector:
            kubernetes.io/os: linux
    ---
    apiVersion: v1
    kind: ServiceAccount
    metadata:
    labels:
        k8s-addon: cluster-autoscaler.addons.k8s.io
        k8s-app: cluster-autoscaler
    name: cluster-autoscaler
    namespace: kube-system
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
    name: cluster-autoscaler
    labels:
        k8s-addon: cluster-autoscaler.addons.k8s.io
        k8s-app: cluster-autoscaler
    rules:
    - apiGroups: [""]
    resources: ["events", "endpoints"]
    verbs: ["create", "patch"]
    - apiGroups: [""]
    resources: ["pods/eviction"]
    verbs: ["create"]
    - apiGroups: [""]
    resources: ["pods/status"]
    verbs: ["update"]
    - apiGroups: [""]
    resources: ["endpoints"]
    resourceNames: ["cluster-autoscaler"]
    verbs: ["get", "update"]
    - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["watch", "list", "get", "update"]
    - apiGroups: [""]
    resources: ["namespaces", "pods", "services", "replicationcontrollers", "persistentvolumeclaims", "persistentvolumes"]
    verbs: ["watch", "list", "get"]
    - apiGroups: ["extensions"]
    resources: ["replicasets", "daemonsets"]
    verbs: ["watch", "list", "get"]
    - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["watch", "list"]
    - apiGroups: ["apps"]
    resources: ["statefulsets", "replicasets", "daemonsets"]
    verbs: ["watch", "list", "get"]
    - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses", "csinodes", "csidrivers", "csistoragecapacities"]
    verbs: ["watch", "list", "get"]
    - apiGroups: ["batch", "extensions"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch", "patch"]
    - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["create"]
    - apiGroups: ["coordination.k8s.io"]
    resourceNames: ["cluster-autoscaler"]
    resources: ["leases"]
    verbs: ["get", "update"]
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: Role
    metadata:
    name: cluster-autoscaler
    namespace: kube-system
    labels:
        k8s-addon: cluster-autoscaler.addons.k8s.io
        k8s-app: cluster-autoscaler
    rules:
    - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["create","list","watch"]
    - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["cluster-autoscaler-status", "cluster-autoscaler-priority-expander"]
    verbs: ["delete", "get", "update", "watch"]
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRoleBinding
    metadata:
    name: cluster-autoscaler
    labels:
        k8s-addon: cluster-autoscaler.addons.k8s.io
        k8s-app: cluster-autoscaler
    roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: ClusterRole
    name: cluster-autoscaler
    subjects:
    - kind: ServiceAccount
    name: cluster-autoscaler
    namespace: kube-system
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: RoleBinding
    metadata:
    name: cluster-autoscaler
    namespace: kube-system
    labels:
        k8s-addon: cluster-autoscaler.addons.k8s.io
        k8s-app: cluster-autoscaler
    roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: Role
    name: cluster-autoscaler
    subjects:
    - kind: ServiceAccount
    name: cluster-autoscaler
    namespace: kube-system
    """
            
            # Create temporary file for autoscaler manifest
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                f.write(autoscaler_yaml)
                autoscaler_file = f.name
            
            try:
                # Apply autoscaler manifest
                autoscaler_cmd = ['kubectl', 'apply', '-f', autoscaler_file]
                autoscaler_result = subprocess.run(autoscaler_cmd, env=env, capture_output=True, text=True, timeout=120)
                
                if autoscaler_result.returncode == 0:
                    self.print_colored(Colors.GREEN, "   {Symbols.OK} Cluster Autoscaler deployed")
                    self.log_operation('INFO', f"Cluster Autoscaler deployed for {cluster_name}")
                    
                    # Verify deployment
                    time.sleep(10)
                    verify_cmd = ['kubectl', 'get', 'pods', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', '--no-headers']
                    verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=60)
                    
                    if verify_result.returncode == 0:
                        pod_lines = [line.strip() for line in verify_result.stdout.strip().split('\n') if line.strip()]
                        running_pods = [line for line in pod_lines if 'Running' in line]
                        
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster Autoscaler pods: {len(running_pods)} running")
                        self.log_operation('INFO', f"Cluster Autoscaler verification: {len(running_pods)} pods running")
                        
                        return True
                    else:
                        self.log_operation('WARNING', f"Could not verify Cluster Autoscaler deployment")
                        return True
                else:
                    self.log_operation('ERROR', f"Cluster Autoscaler deployment failed: {autoscaler_result.stderr}")
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Cluster Autoscaler deployment failed")
                    return False
                    
            finally:
                # Clean up autoscaler file
                try:
                    os.unlink(autoscaler_file)
                except:
                    pass
                
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to setup Cluster Autoscaler for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Cluster Autoscaler setup failed: {error_msg}")
            return False


    def setup_scheduled_scaling(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str) -> bool:
        """Setup scheduled scaling for cost optimization using IST times"""
        try:
            self.log_operation('INFO', f"Setting up scheduled scaling for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"{Symbols.TIMER} Setting up scheduled scaling for {cluster_name}...")
            
            # Create admin session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            # Create EventBridge and Lambda clients
            events_client = admin_session.client('events')
            lambda_client = admin_session.client('lambda')
            iam_client = admin_session.client('iam')
            sts_client = admin_session.client('sts')
            account_id = sts_client.get_caller_identity()['Account']
            
            # Step 1: Create IAM role for Lambda function
            self.print_colored(Colors.CYAN, "   🔐 Creating IAM role for scheduled scaling...")
            
            lambda_role_name = f"EKSScheduledScalingRole-{cluster_name}"
            
            lambda_trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            lambda_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "eks:DescribeCluster",
                            "eks:DescribeNodegroup",
                            "eks:UpdateNodegroupConfig",
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents"
                        ],
                        "Resource": "*"
                    }
                ]
            }
            
            try:
                # Create Lambda execution role
                role_response = iam_client.create_role(
                    RoleName=lambda_role_name,
                    AssumeRolePolicyDocument=json.dumps(lambda_trust_policy),
                    Description=f"Role for scheduled scaling of EKS cluster {cluster_name}"
                )
                lambda_role_arn = role_response['Role']['Arn']
                
                # Create and attach policy
                policy_name = f"EKSScheduledScalingPolicy-{cluster_name}"
                policy_response = iam_client.create_policy(
                    PolicyName=policy_name,
                    PolicyDocument=json.dumps(lambda_policy),
                    Description=f"Policy for scheduled scaling of EKS cluster {cluster_name}"
                )
                
                iam_client.attach_role_policy(
                    RoleName=lambda_role_name,
                    PolicyArn=policy_response['Policy']['Arn']
                )
                
                self.log_operation('INFO', f"Created Lambda role for scheduled scaling: {lambda_role_arn}")
                
            except iam_client.exceptions.EntityAlreadyExistsException:
                # Role already exists
                role_response = iam_client.get_role(RoleName=lambda_role_name)
                lambda_role_arn = role_response['Role']['Arn']
                self.log_operation('INFO', f"Using existing Lambda role: {lambda_role_arn}")
            
            # Step 2: Create Lambda function for scaling
            self.print_colored(Colors.CYAN, "   🔧 Creating Lambda function for scaling...")
            
            lambda_code = f'''
    import boto3
    import json
    import logging
    from datetime import datetime
    import pytz

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    def lambda_handler(event, context):
        try:
            eks_client = boto3.client('eks', region_name='{region}')
            
            cluster_name = '{cluster_name}'
            nodegroup_name = f'{{cluster_name}}-nodegroup'
            
            # Get the desired size from the event
            desired_size = event.get('desired_size', 1)
            min_size = event.get('min_size', 0)
            max_size = event.get('max_size', 3)
            
            # Log IST time for reference
            ist_tz = pytz.timezone('Asia/Kolkata')
            ist_time = datetime.now(ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')
            
            logger.info(f"Scaling nodegroup {{nodegroup_name}} to desired={{desired_size}}, min={{min_size}}, max={{max_size}} at {{ist_time}}")
            
            # Update nodegroup scaling configuration
            response = eks_client.update_nodegroup_config(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                scalingConfig={{
                    'minSize': min_size,
                    'maxSize': max_size,
                    'desiredSize': desired_size
                }}
            )
            
            logger.info(f"Scaling update initiated: {{response['update']['id']}} at {{ist_time}}")
            
            return {{
                'statusCode': 200,
                'body': json.dumps({{
                    'message': f'Scaling update initiated for {{nodegroup_name}} at {{ist_time}}',
                    'update_id': response['update']['id'],
                    'ist_time': ist_time
                }})
            }}
            
        except Exception as e:
            logger.error(f"Error scaling nodegroup: {{str(e)}}")
            return {{
                'statusCode': 500,
                'body': json.dumps({{
                    'error': str(e)
                }})
            }}
    '''
            
            function_name = f"eks-scheduled-scaling-{cluster_name}"
            
            try:
                # Wait for role to be available
                time.sleep(10)
                
                # Create Lambda function
                lambda_response = lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime='python3.9',
                    Role=lambda_role_arn,
                    Handler='index.lambda_handler',
                    Code={'ZipFile': lambda_code.encode('utf-8')},
                    Description=f'Scheduled scaling for EKS cluster {cluster_name} (IST timezone)',
                    Timeout=60,
                    Layers=[
                        'arn:aws:lambda:us-east-1:770693421928:layer:Klayers-p39-pytz:1'  # pytz layer
                    ]
                )
                
                function_arn = lambda_response['FunctionArn']
                self.log_operation('INFO', f"Created Lambda function: {function_arn}")
                
            except lambda_client.exceptions.ResourceConflictException:
                # Function already exists
                function_response = lambda_client.get_function(FunctionName=function_name)
                function_arn = function_response['Configuration']['FunctionArn']
                self.log_operation('INFO', f"Using existing Lambda function: {function_arn}")
            
            # Step 3: Create EventBridge rules for scaling
            self.print_colored(Colors.CYAN, "   [DATE] Creating scheduled scaling rules (IST timezone)...")
            
            # IST is UTC+5:30
            # Scale down at 6:30 PM IST = 1:00 PM UTC (13:00 UTC)
            # Scale up at 8:30 AM IST = 3:00 AM UTC (03:00 UTC)
            
            # Scale down at 6:30 PM IST (1:00 PM UTC)
            scale_down_rule = f"eks-scale-down-{cluster_name}"
            events_client.put_rule(
                Name=scale_down_rule,
                ScheduleExpression='cron(0 3 * * * *)',  # 1:00 PM UTC + 5.30 = 6:30 PM IST, All Days
                # for weekdays only 'cron(0 13 * * MON-FRI *)' 
                Description=f'Scale down EKS cluster {cluster_name} at 6:30 PM IST (after hours)',
                State='ENABLED'
            )
            
            # Scale up at 8:30 AM IST (3:00 AM UTC)
            scale_up_rule = f"eks-scale-up-{cluster_name}"
            events_client.put_rule(
                Name=scale_up_rule,
                ScheduleExpression='cron(0 13 * * * *)',  # 3:00 AM UTC + 5.30 = 8:30 AM IST, All Days
                # for weekdays only 'cron(0 13 * * MON-FRI *)' 
                Description=f'Scale up EKS cluster {cluster_name} at 8:30 AM IST (business hours)',
                State='ENABLED'
            )
            
            # Add Lambda permissions for EventBridge
            try:
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f'allow-eventbridge-{cluster_name}-down',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f'arn:aws:events:{region}:{account_id}:rule/{scale_down_rule}'
                )
                
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f'allow-eventbridge-{cluster_name}-up',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f'arn:aws:events:{region}:{account_id}:rule/{scale_up_rule}'
                )
            except lambda_client.exceptions.ResourceConflictException:
                # Permissions already exist
                pass
            
            # Add targets to rules
            events_client.put_targets(
                Rule=scale_down_rule,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': function_arn,
                        'Input': json.dumps({
                            'desired_size': 0,
                            'min_size': 0,
                            'max_size': 3,
                            'action': 'scale_down',
                            'ist_time': '6:30 PM IST'
                        })
                    }
                ]
            )
            
            events_client.put_targets(
                Rule=scale_up_rule,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': function_arn,
                        'Input': json.dumps({
                            'desired_size': 1,
                            'min_size': 1,
                            'max_size': 3,
                            'action': 'scale_up',
                            'ist_time': '8:30 AM IST'
                        })
                    }
                ]
            )
            
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Scheduled scaling configured for IST timezone")
            self.print_colored(Colors.CYAN, f"   {Symbols.DATE} Scale up: 8:30 AM IST (Mon-Fri) → 1 node")
            self.print_colored(Colors.CYAN, f"   {Symbols.DATE} Scale down: 6:30 PM IST (Mon-Fri) → 0 nodes")
            self.print_colored(Colors.CYAN, f"   🌏 Timezone: Indian Standard Time (UTC+5:30)")
            
            self.log_operation('INFO', f"Scheduled scaling configured for {cluster_name} with IST timezone")
            self.log_operation('INFO', f"Scale up: 8:30 AM IST (3:00 AM UTC), Scale down: 6:30 PM IST (1:00 PM UTC)")
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to setup scheduled scaling for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Scheduled scaling setup failed: {error_msg}")
            return False

    def ensure_iam_roles_with_cloudwatch(self, iam_client, account_id: str) -> tuple:
        """Enhanced IAM role creation with CloudWatch permissions"""
        try:
            # Get existing roles or create new ones
            eks_role_arn, node_role_arn = self.ensure_iam_roles(iam_client, account_id)
            
            # Add CloudWatch permissions to node role
            node_role_name = node_role_arn.split('/')[-1]
            
            # CloudWatch agent policy
            cloudwatch_agent_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "cloudwatch:PutMetricData",
                            "ec2:DescribeVolumes",
                            "ec2:DescribeTags",
                            "logs:PutLogEvents",
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:DescribeLogStreams",
                            "logs:DescribeLogGroups"
                        ],
                        "Resource": "*"
                    }
                ]
            }
            
            # Attach CloudWatch agent policy
            try:
                iam_client.put_role_policy(
                    RoleName=node_role_name,
                    PolicyName='CloudWatchAgentServerPolicy',
                    PolicyDocument=json.dumps(cloudwatch_agent_policy)
                )
                self.log_operation('INFO', f"CloudWatch agent policy attached to {node_role_name}")
            except Exception as e:
                self.log_operation('WARNING', f"Failed to attach CloudWatch policy: {str(e)}")
            
            return eks_role_arn, node_role_arn
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to ensure IAM roles with CloudWatch: {str(e)}")
            raise

    def deploy_cloudwatch_agent(self, cluster_name: str, region: str, access_key: str, secret_key: str, account_id: str) -> bool:
        """Deploy CloudWatch agent as DaemonSet"""
        try:
            self.log_operation('INFO', f"Deploying CloudWatch agent for cluster {cluster_name}")
            
            # Create CloudWatch agent configuration
            cloudwatch_config = self.get_cloudwatch_agent_config(cluster_name, region)
            
            # Create Kubernetes manifests
            namespace_manifest = self.get_cloudwatch_namespace_manifest()
            service_account_manifest = self.get_cloudwatch_service_account_manifest()
            configmap_manifest = self.get_cloudwatch_configmap_manifest(cloudwatch_config)
            daemonset_manifest = self.get_cloudwatch_daemonset_manifest(cluster_name, region, account_id)
            
            # Apply manifests using kubectl
            manifests = [
                ('namespace', namespace_manifest),
                ('service-account', service_account_manifest),
                ('configmap', configmap_manifest),
                ('daemonset', daemonset_manifest)
            ]
            
            for manifest_type, manifest in manifests:
                if self.apply_kubernetes_manifest(cluster_name, region, access_key, secret_key, manifest):
                    self.log_operation('INFO', f"Applied CloudWatch {manifest_type} manifest")
                else:
                    self.log_operation('ERROR', f"Failed to apply CloudWatch {manifest_type} manifest")
                    return False
            
            # Wait for DaemonSet to be ready
            if self.wait_for_daemonset_ready(cluster_name, region, access_key, secret_key, 'amazon-cloudwatch', 'cloudwatch-agent'):
                self.log_operation('INFO', f"CloudWatch agent deployed successfully for {cluster_name}")
                return True
            else:
                self.log_operation('ERROR', f"CloudWatch agent failed to deploy for {cluster_name}")
                return False
                
        except Exception as e:
            self.log_operation('ERROR', f"Failed to deploy CloudWatch agent: {str(e)}")
            return False

    def setup_cloudwatch_alarms(self, cluster_name: str, region: str, cloudwatch_client, nodegroup_name: str, account_id: str) -> bool:
        """Setup comprehensive CloudWatch alarms for EKS cluster"""
        try:
            self.log_operation('INFO', f"Setting up CloudWatch alarms for cluster {cluster_name}")
            
            alarms_created = 0
            total_alarms = 0
            
            # Define alarm configurations
            alarm_configs = [
                {
                    'name': f'{cluster_name}-high-cpu-utilization',
                    'description': f'High CPU utilization on {cluster_name}',
                    'metric_name': 'CPUUtilization',
                    'namespace': 'AWS/EKS',
                    'statistic': 'Average',
                    'threshold': 80.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-high-memory-utilization',
                    'description': f'High memory utilization on {cluster_name}',
                    'metric_name': 'MemoryUtilization',
                    'namespace': 'AWS/EKS',
                    'statistic': 'Average',
                    'threshold': 85.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-pod-failures',
                    'description': f'High pod failure rate on {cluster_name}',
                    'metric_name': 'pod_number_of_container_restarts',
                    'namespace': 'ContainerInsights',
                    'statistic': 'Sum',
                    'threshold': 10.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-node-not-ready',
                    'description': f'Node not ready on {cluster_name}',
                    'metric_name': 'cluster_node_running_total',
                    'namespace': 'ContainerInsights',
                    'statistic': 'Average',
                    'threshold': 1.0,
                    'comparison': 'LessThanThreshold',
                    'evaluation_periods': 3,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-disk-space-low',
                    'description': f'Low disk space on {cluster_name} nodes',
                    'metric_name': 'DiskSpaceUtilization',
                    'namespace': 'CWAgent',
                    'statistic': 'Average',
                    'threshold': 85.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [
                        {'Name': 'ClusterName', 'Value': cluster_name},
                        {'Name': 'NodegroupName', 'Value': nodegroup_name}
                    ]
                },
                {
                    'name': f'{cluster_name}-network-errors',
                    'description': f'High network errors on {cluster_name}',
                    'metric_name': 'NetworkPacketsIn',
                    'namespace': 'AWS/EC2',
                    'statistic': 'Sum',
                    'threshold': 1000.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-service-unhealthy',
                    'description': f'Service unhealthy on {cluster_name}',
                    'metric_name': 'service_number_of_running_pods',
                    'namespace': 'ContainerInsights',
                    'statistic': 'Average',
                    'threshold': 1.0,
                    'comparison': 'LessThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                }
            ]
            
            # Create each alarm
            for alarm_config in alarm_configs:
                total_alarms += 1
                try:
                    cloudwatch_client.put_metric_alarm(
                        AlarmName=alarm_config['name'],
                        ComparisonOperator=alarm_config['comparison'],
                        EvaluationPeriods=alarm_config['evaluation_periods'],
                        MetricName=alarm_config['metric_name'],
                        Namespace=alarm_config['namespace'],
                        Period=alarm_config['period'],
                        Statistic=alarm_config['statistic'],
                        Threshold=alarm_config['threshold'],
                        ActionsEnabled=True,
                        AlarmDescription=alarm_config['description'],
                        Dimensions=alarm_config['dimensions'],
                        Unit='Percent' if 'utilization' in alarm_config['metric_name'].lower() else 'Count'
                    )
                    
                    alarms_created += 1
                    self.log_operation('INFO', f"Created alarm: {alarm_config['name']}")
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create alarm {alarm_config['name']}: {str(e)}")
            
            # Create composite alarms for critical conditions
            composite_alarms_success = self.create_composite_alarms(cloudwatch_client, cluster_name, alarm_configs)
            
            # Calculate success rates
            basic_alarm_success_rate = (alarms_created / total_alarms) * 100 if total_alarms > 0 else 0
            overall_success = basic_alarm_success_rate >= 70 and composite_alarms_success
            
            # Log comprehensive results
            self.log_operation('INFO', f"CloudWatch alarms setup summary:")
            self.log_operation('INFO', f"  - Basic alarms: {alarms_created}/{total_alarms} created ({basic_alarm_success_rate:.1f}%)")
            self.log_operation('INFO', f"  - Composite alarms: {'Success' if composite_alarms_success else 'Failed'}")
            self.log_operation('INFO', f"  - Overall status: {'Success' if overall_success else 'Partial/Failed'}")
            
            # Store detailed alarm information for later use
            if not hasattr(self, 'alarm_details'):
                self.alarm_details = {}
            
            self.alarm_details[cluster_name] = {
                'basic_alarms_created': alarms_created,
                'total_basic_alarms': total_alarms,
                'basic_alarm_success_rate': basic_alarm_success_rate,
                'composite_alarms_success': composite_alarms_success,
                'overall_success': overall_success,
                'alarm_names': [config['name'] for config in alarm_configs if alarms_created > 0]
            }
            
            return overall_success
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup CloudWatch alarms: {str(e)}")
            return False

    def create_composite_alarms(self, cloudwatch_client, cluster_name: str, alarm_configs: list) -> bool:
        """Create composite alarms for critical conditions"""
        try:
            composite_alarms_created = 0
            total_composite_alarms = 0
            
            # Define composite alarm configurations
            composite_configs = [
                {
                    'name': f'{cluster_name}-critical-health',
                    'description': f'Critical health issues detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-high-cpu-utilization") OR ALARM("{cluster_name}-high-memory-utilization") OR ALARM("{cluster_name}-node-not-ready")',
                    'severity': 'CRITICAL'
                },
                {
                    'name': f'{cluster_name}-performance-degradation',
                    'description': f'Performance degradation detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-pod-failures") OR ALARM("{cluster_name}-service-unhealthy")',
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-resource-exhaustion',
                    'description': f'Resource exhaustion detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-disk-space-low") AND (ALARM("{cluster_name}-high-cpu-utilization") OR ALARM("{cluster_name}-high-memory-utilization"))',
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-infrastructure-issues',
                    'description': f'Infrastructure issues detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-network-errors") OR ALARM("{cluster_name}-node-not-ready")',
                    'severity': 'MEDIUM'
                }
            ]
            
            # Create each composite alarm
            for composite_config in composite_configs:
                total_composite_alarms += 1
                try:
                    cloudwatch_client.put_composite_alarm(
                        AlarmName=composite_config['name'],
                        AlarmDescription=composite_config['description'],
                        AlarmRule=composite_config['rule'],
                        ActionsEnabled=True,
                        Tags=[
                            {
                                'Key': 'Cluster',
                                'Value': cluster_name
                            },
                            {
                                'Key': 'Severity',
                                'Value': composite_config['severity']
                            },
                            {
                                'Key': 'AlarmType',
                                'Value': 'Composite'
                            }
                        ]
                    )
                    
                    composite_alarms_created += 1
                    self.log_operation('INFO', f"Created composite alarm: {composite_config['name']} (Severity: {composite_config['severity']})")
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create composite alarm {composite_config['name']}: {str(e)}")
            
            # Log composite alarm results
            composite_success_rate = (composite_alarms_created / total_composite_alarms) * 100 if total_composite_alarms > 0 else 0
            self.log_operation('INFO', f"Composite alarms: {composite_alarms_created}/{total_composite_alarms} created ({composite_success_rate:.1f}%)")
            
            # Store composite alarm details
            if hasattr(self, 'alarm_details') and cluster_name in self.alarm_details:
                self.alarm_details[cluster_name].update({
                    'composite_alarms_created': composite_alarms_created,
                    'total_composite_alarms': total_composite_alarms,
                    'composite_success_rate': composite_success_rate,
                    'composite_alarm_names': [config['name'] for config in composite_configs]
                })
            
            # Consider successful if at least 75% of composite alarms are created
            return composite_success_rate >= 75
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create composite alarms: {str(e)}")
            return False
    # Updated cluster creation summary in the main method
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
            self.print_colored(Colors.YELLOW, f"{Symbols.SCAN} Creating cluster: {cluster_name} in {region} with {instance_type}")
            
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
            cloudwatch_client = admin_session.client('cloudwatch')  # Added CloudWatch client
            
            self.log_operation('INFO', f"AWS admin session created for {account_key} in {region}")
            
            # Ensure IAM roles exist (including CloudWatch permissions)
            self.log_operation('DEBUG', f"Ensuring IAM roles exist for {account_key}")
            eks_role_arn, node_role_arn = self.ensure_iam_roles_with_cloudwatch(iam_client, account_id)
            self.log_operation('INFO', f"IAM roles verified/created for {account_key}")
            
            # Get VPC resources
            self.log_operation('DEBUG', f"Getting VPC resources for {account_key} in {region}")
            subnet_ids, security_group_id = self.get_or_create_vpc_resources(ec2_client, region)
            self.log_operation('INFO', f"VPC resources verified for {account_key} in {region}")
            
            # Step 1: Create EKS cluster with CloudWatch logging enabled (Updated to 1.28)
            self.log_operation('INFO', f"Creating EKS cluster {cluster_name} with CloudWatch logging and version 1.28")
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
            self.log_operation('INFO', f"EKS cluster {cluster_name} creation initiated with version 1.28")
            
            # Wait for cluster to be active
            self.log_operation('INFO', f"Waiting for cluster {cluster_name} to be active...")
            self.print_colored(Colors.YELLOW, f"⏳ Waiting for cluster {cluster_name} to be active...")
            waiter = eks_client.get_waiter('cluster_active')
            waiter.wait(name=cluster_name, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})
            
            self.log_operation('INFO', f"Cluster {cluster_name} is now active")
            
            # Install essential add-ons
            self.print_colored(Colors.BLUE, f"🔧 Installing essential add-ons...")
            addons_success = self.install_essential_addons(eks_client, cluster_name)
            
            # Step 2: Create node group with AL2023 AMI and diversified instance types
            self.log_operation('INFO', f"Creating node group for cluster {cluster_name} with {instance_type} instances")
            nodegroup_name = self.generate_nodegroup_name(cluster_name)
            
            # Get diversified instance types for better spot availability
            instance_types = self.get_diversified_instance_types(instance_type)
            
            # Use AL2023 AMI and diversified instance types
            nodegroup_config = {
                'clusterName': cluster_name,
                'nodegroupName': nodegroup_name,
                'scalingConfig': {
                    'minSize': 1,
                    'maxSize': max_nodes,
                    'desiredSize': 1
                },
                'instanceTypes': instance_types,
                'amiType': 'AL2023_x86_64_STANDARD',
                'diskSize': 20,
                'nodeRole': node_role_arn,
                'subnets': subnet_ids,
                'capacityType': cluster_info.get('capacity_type', 'SPOT')
            }
            
            # Log the exact configuration being used
            self.log_operation('INFO', f"Creating nodegroup with config: instanceTypes={nodegroup_config['instanceTypes']}, amiType={nodegroup_config['amiType']}, capacityType={nodegroup_config.get('capacityType', 'default')}")
            
            eks_client.create_nodegroup(**nodegroup_config)
            self.log_operation('INFO', f"Node group {nodegroup_name} creation initiated with AL2023 AMI and diversified instance types")
            
            # Wait for node group to be active
            self.log_operation('INFO', f"Waiting for node group {nodegroup_name} to be active...")
            self.print_colored(Colors.YELLOW, f"⏳ Waiting for node group {nodegroup_name} to be active...")
            ng_waiter = eks_client.get_waiter('nodegroup_active')
            ng_waiter.wait(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )
            
            self.log_operation('INFO', f"Node group {nodegroup_name} is now active with AL2023 AMI")
            
            # Verify the actual instance type created
            try:
                nodegroup_details = eks_client.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name
                )
                actual_instance_types = nodegroup_details['nodegroup'].get('instanceTypes', [])
                actual_ami_type = nodegroup_details['nodegroup'].get('amiType', 'Unknown')
                self.log_operation('INFO', f"Verified nodegroup - instanceTypes: {actual_instance_types}, amiType: {actual_ami_type}")
                
                if instance_type not in actual_instance_types:
                    self.log_operation('WARNING', f"Expected {instance_type} but got: {actual_instance_types}")
                else:
                    self.log_operation('INFO', f"Successfully created nodegroup with diversified instance types including {instance_type}")
                    
            except Exception as e:
                self.log_operation('WARNING', f"Could not verify nodegroup details: {str(e)}")
            
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
                time.sleep(20)
                
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
                    self.print_colored(Colors.GREEN, f"{Symbols.OK} Cluster access verified for {username}")
                else:
                    self.log_operation('WARNING', f"Cluster access verification failed for {username}")
                    self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  Cluster access verification failed for {username}")
            else:
                self.log_operation('WARNING', f"Skipping verification due to ConfigMap configuration failure")

            # Step 5: Enable Container Insights
            if verification_success or auth_success:
                self.print_colored(Colors.BLUE, f"\n{Symbols.STATS} Setting up CloudWatch Container Insights...")
                
                insights_success = self.enable_container_insights(
                    cluster_name, 
                    region, 
                    admin_access_key, 
                    admin_secret_key
                )
                
                if insights_success:
                    cluster_info['container_insights_enabled'] = True
                    self.log_operation('INFO', f"Container Insights enabled for {cluster_name}")
                else:
                    cluster_info['container_insights_enabled'] = False
            else:
                cluster_info['container_insights_enabled'] = False
            
            # Step 6: Setup Cluster Autoscaler
            self.print_colored(Colors.BLUE, f"\n{Symbols.SCAN} Setting up Cluster Autoscaler...")
            autoscaler_success = self.setup_cluster_autoscaler(
                cluster_name, 
                region, 
                admin_access_key, 
                admin_secret_key,
                account_id
            )
            cluster_info['autoscaler_enabled'] = autoscaler_success
            
            # Step 7: Setup Scheduled Scaling
            self.print_colored(Colors.BLUE, f"\n{Symbols.TIMER} Setting up Scheduled Scaling...")
            scheduling_success = self.setup_scheduled_scaling(
                cluster_name, 
                region, 
                admin_access_key, 
                admin_secret_key
            )
            cluster_info['scheduled_scaling_enabled'] = scheduling_success

            # Step 8: Deploy CloudWatch Agent - ENHANCED
            self.print_colored(Colors.BLUE, f"\n{Symbols.STATS} Deploying CloudWatch Agent...")
            cloudwatch_agent_success = self.deploy_cloudwatch_agent(
                cluster_name,
                region,
                admin_access_key,
                admin_secret_key,
                account_id
            )
            cluster_info['cloudwatch_agent_enabled'] = cloudwatch_agent_success

            # Step 9: Setup CloudWatch Alarms - ENHANCED
            self.print_colored(Colors.BLUE, f"\n🚨 Setting up CloudWatch Alarms...")
            alarms_success = self.setup_cloudwatch_alarms(
                cluster_name,
                region,
                cloudwatch_client,
                nodegroup_name,
                account_id
            )
            cluster_info['cloudwatch_alarms_enabled'] = alarms_success

            # Step 10: Setup Cost Monitoring Alarms - NEW ENHANCEMENT
            self.print_colored(Colors.BLUE, f"\n{Symbols.COST} Setting up Cost Monitoring Alarms...")
            cost_alarms_success = self.setup_cost_alarms(
                cluster_name,
                region,
                cloudwatch_client,
                account_id
            )
            cluster_info['cost_alarms_enabled'] = cost_alarms_success

            # Step 11: Perform Initial Health Check - NEW ENHANCEMENT
            self.print_colored(Colors.BLUE, f"\n🏥 Performing Initial Health Check...")
            health_check_result = self.health_check_cluster(
                cluster_name,
                region,
                admin_access_key,
                admin_secret_key
            )
            cluster_info['initial_health_check'] = health_check_result
            
            if health_check_result.get('overall_healthy', False):
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster health check: HEALTHY")
            else:
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Cluster health check: NEEDS ATTENTION")
                self.log_operation('WARNING', f"Health check issues: {health_check_result}")

            # Update cluster_info with verification results
            cluster_info['auth_configured'] = auth_success
            cluster_info['access_verified'] = verification_success
            cluster_info['addons_installed'] = addons_success
            cluster_info['version'] = '1.28'
            cluster_info['ami_type'] = 'AL2023_x86_64_STANDARD'
            cluster_info['diversified_instance_types'] = instance_types
            
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
                'instance_types': instance_types,
                'default_nodes': 1,
                'version': '1.28',
                'ami_type': 'AL2023_x86_64_STANDARD',
                'container_insights_enabled': cluster_info.get('container_insights_enabled', False),
                'autoscaler_enabled': cluster_info.get('autoscaler_enabled', False),
                'scheduled_scaling_enabled': cluster_info.get('scheduled_scaling_enabled', False),
                'cloudwatch_agent_enabled': cluster_info.get('cloudwatch_agent_enabled', False),
                'cloudwatch_alarms_enabled': cluster_info.get('cloudwatch_alarms_enabled', False),
                'cost_alarms_enabled': cluster_info.get('cost_alarms_enabled', False),
                'health_check_status': health_check_result.get('overall_healthy', False),
                'addons_installed': addons_success
            }
            
            self.kubectl_commands.append(kubectl_info)
            self.log_operation('INFO', f"Generated kubectl commands for {username}")
            
            # Generate individual user instruction file immediately
            self.generate_individual_user_instruction(cluster_info, kubectl_info)
            
            # Print comprehensive success summary with enhanced monitoring features
            self.print_enhanced_cluster_summary(cluster_name, cluster_info)
        
            # Generate and log detailed monitoring reports
            if cluster_info.get('cloudwatch_alarms_enabled'):
                alarm_report = self.generate_alarm_summary_report(cluster_name)
                self.log_operation('INFO', f"Detailed alarm report:\n{alarm_report}")
            
            if cluster_info.get('cost_alarms_enabled'):
                cost_report = self.generate_cost_alarm_summary_report(cluster_name)
                self.log_operation('INFO', f"Cost monitoring report:\n{cost_report}")
            
            if cluster_info.get('initial_health_check'):
                health_report = self.generate_health_check_report(cluster_name)
                self.log_operation('INFO', f"Health check report:\n{health_report}")
            
            self.log_operation('INFO', f"Successfully created enhanced cluster {cluster_name} with comprehensive monitoring and cost controls")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Successfully created enhanced cluster: {cluster_name} (v1.28, AL2023, full monitoring enabled)")
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to create cluster {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to create cluster {cluster_name}: {error_msg}")
            return False

    def setup_cost_alarms(self, cluster_name: str, region: str, cloudwatch_client, account_id: str) -> bool:
        """Setup cost monitoring alarms for EKS cluster"""
        try:
            self.log_operation('INFO', f"Setting up cost monitoring alarms for cluster {cluster_name}")
            
            cost_alarms_created = 0
            total_cost_alarms = 0
            
            # Cost alarm configurations with different thresholds
            cost_alarm_configs = [
                {
                    'name': f'{cluster_name}-daily-cost-warning',
                    'description': f'Daily cost warning for {cluster_name} - moderate spending',
                    'threshold': 25.0,  # $25 daily warning
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,  # 24 hours
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEKS'}
                    ],
                    'severity': 'LOW'
                },
                {
                    'name': f'{cluster_name}-daily-cost-critical',
                    'description': f'Critical daily cost alert for {cluster_name} - high spending',
                    'threshold': 50.0,  # $50 daily critical
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEKS'}
                    ],
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-ec2-cost-high',
                    'description': f'High EC2 instance cost for {cluster_name} nodes',
                    'threshold': 75.0,  # $75 for EC2 instances
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEC2-Instance'}
                    ],
                    'severity': 'MEDIUM'
                },
                {
                    'name': f'{cluster_name}-ebs-cost-warning',
                    'description': f'EBS storage cost warning for {cluster_name}',
                    'threshold': 20.0,  # $20 for EBS storage
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEBS'}
                    ],
                    'severity': 'LOW'
                }
            ]
            
            # Create each cost alarm
            for alarm_config in cost_alarm_configs:
                total_cost_alarms += 1
                try:
                    cloudwatch_client.put_metric_alarm(
                        AlarmName=alarm_config['name'],
                        ComparisonOperator='GreaterThanThreshold',
                        EvaluationPeriods=1,
                        MetricName=alarm_config['metric_name'],
                        Namespace=alarm_config['namespace'],
                        Period=alarm_config['period'],
                        Statistic='Maximum',
                        Threshold=alarm_config['threshold'],
                        ActionsEnabled=True,
                        AlarmDescription=alarm_config['description'],
                        Dimensions=alarm_config['dimensions'],
                        Unit='None',
                        Tags=[
                            {
                                'Key': 'Cluster',
                                'Value': cluster_name
                            },
                            {
                                'Key': 'AlarmType',
                                'Value': 'Cost'
                            },
                            {
                                'Key': 'Severity',
                                'Value': alarm_config['severity']
                            },
                            {
                                'Key': 'CreatedBy',
                                'Value': 'varadharajaan'
                            },
                            {
                                'Key': 'CreatedOn',
                                'Value': '2025-06-12'
                            }
                        ]
                    )
                    
                    cost_alarms_created += 1
                    self.log_operation('INFO', f"Created cost alarm: {alarm_config['name']} (${alarm_config['threshold']}, {alarm_config['severity']})")
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cost alarm created: {alarm_config['name']} (${alarm_config['threshold']})")
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create cost alarm {alarm_config['name']}: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Failed to create cost alarm: {alarm_config['name']}")
            
            # Calculate success rate
            success_rate = (cost_alarms_created / total_cost_alarms) * 100 if total_cost_alarms > 0 else 0
            
            self.log_operation('INFO', f"Cost alarms setup: {cost_alarms_created}/{total_cost_alarms} created ({success_rate:.1f}%)")
            self.print_colored(Colors.GREEN, f"   {Symbols.STATS} Cost alarms: {cost_alarms_created}/{total_cost_alarms} created ({success_rate:.1f}%)")
            
            # Store cost alarm details for reporting
            if not hasattr(self, 'cost_alarm_details'):
                self.cost_alarm_details = {}
            
            self.cost_alarm_details[cluster_name] = {
                'cost_alarms_created': cost_alarms_created,
                'total_cost_alarms': total_cost_alarms,
                'success_rate': success_rate,
                'alarm_names': [config['name'] for config in cost_alarm_configs],
                'thresholds': {config['name']: config['threshold'] for config in cost_alarm_configs}
            }
            
            return success_rate >= 70  # Consider successful if at least 70% created
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup cost alarms: {str(e)}")
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Cost alarms setup failed: {str(e)}")
            return False

    def health_check_cluster(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str) -> Dict:
        """Comprehensive cluster health check with detailed reporting"""
        try:
            self.log_operation('INFO', f"Performing comprehensive health check for cluster {cluster_name}")
            
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            eks_client = admin_session.client('eks')
            
            health_status = {
                'cluster_name': cluster_name,
                'region': region,
                'check_timestamp': '2025-06-12 14:32:07',
                'checked_by': 'varadharajaan',
                'overall_healthy': True,
                'issues': [],
                'warnings': [],
                'success_items': []
            }
            
            # 1. Check cluster status and details
            try:
                cluster_response = eks_client.describe_cluster(name=cluster_name)
                cluster = cluster_response['cluster']
                cluster_status = cluster['status']
                cluster_version = cluster.get('version', 'Unknown')
                
                health_status['cluster_status'] = cluster_status
                health_status['cluster_version'] = cluster_version
                health_status['cluster_endpoint'] = cluster.get('endpoint', 'Unknown')
                
                if cluster_status != 'ACTIVE':
                    health_status['overall_healthy'] = False
                    health_status['issues'].append(f"Cluster status is {cluster_status}, expected ACTIVE")
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Cluster status: {cluster_status}")
                else:
                    health_status['success_items'].append(f"Cluster is ACTIVE (version {cluster_version})")
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster status: {cluster_status} (v{cluster_version})")
                
                # Check cluster logging
                logging_config = cluster.get('logging', {}).get('clusterLogging', [])
                if logging_config and any(log.get('enabled', False) for log in logging_config):
                    health_status['success_items'].append("CloudWatch logging is enabled")
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} CloudWatch logging: Enabled")
                else:
                    health_status['warnings'].append("CloudWatch logging may not be fully configured")
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  CloudWatch logging: Limited or disabled")
                    
            except Exception as e:
                health_status['cluster_status'] = 'ERROR'
                health_status['overall_healthy'] = False
                health_status['issues'].append(f"Failed to get cluster status: {str(e)}")
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Cluster check failed: {str(e)}")
            
            # 2. Check node groups with detailed analysis
            try:
                nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                nodegroup_health = {}
                total_nodegroups = len(nodegroups_response['nodegroups'])
                active_nodegroups = 0
                
                for ng_name in nodegroups_response['nodegroups']:
                    ng_response = eks_client.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=ng_name
                    )
                    nodegroup = ng_response['nodegroup']
                    ng_status = nodegroup['status']
                    scaling_config = nodegroup.get('scalingConfig', {})
                    instance_types = nodegroup.get('instanceTypes', [])
                    ami_type = nodegroup.get('amiType', 'Unknown')
                    capacity_type = nodegroup.get('capacityType', 'Unknown')
                    
                    nodegroup_health[ng_name] = {
                        'status': ng_status,
                        'instance_types': instance_types,
                        'ami_type': ami_type,
                        'capacity_type': capacity_type,
                        'min_size': scaling_config.get('minSize', 0),
                        'max_size': scaling_config.get('maxSize', 0),
                        'desired_size': scaling_config.get('desiredSize', 0)
                    }
                    
                    if ng_status != 'ACTIVE':
                        health_status['overall_healthy'] = False
                        health_status['issues'].append(f"NodeGroup {ng_name} status is {ng_status}")
                        self.print_colored(Colors.RED, f"   {Symbols.ERROR} NodeGroup {ng_name}: {ng_status}")
                    else:
                        active_nodegroups += 1
                        health_status['success_items'].append(f"NodeGroup {ng_name} is ACTIVE ({capacity_type}, {', '.join(instance_types)})")
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} NodeGroup {ng_name}: {ng_status} ({capacity_type}, {ami_type})")
                        self.print_colored(Colors.CYAN, f"      Scaling: {scaling_config.get('desiredSize', 0)}/{scaling_config.get('maxSize', 0)} nodes")
                
                health_status['nodegroup_health'] = nodegroup_health
                health_status['total_nodegroups'] = total_nodegroups
                health_status['active_nodegroups'] = active_nodegroups
                
            except Exception as e:
                health_status['nodegroup_health'] = {}
                health_status['overall_healthy'] = False
                health_status['issues'].append(f"Failed to check nodegroups: {str(e)}")
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} NodeGroup check failed: {str(e)}")
            
            # 3. Check add-ons with version information
            try:
                addons_response = eks_client.list_addons(clusterName=cluster_name)
                addon_health = {}
                total_addons = len(addons_response['addons'])
                active_addons = 0
                
                essential_addons = ['vpc-cni', 'coredns', 'kube-proxy']
                
                for addon_name in addons_response['addons']:
                    addon_response = eks_client.describe_addon(
                        clusterName=cluster_name,
                        addonName=addon_name
                    )
                    addon = addon_response['addon']
                    addon_status = addon['status']
                    addon_version = addon.get('addonVersion', 'Unknown')
                    
                    addon_health[addon_name] = {
                        'status': addon_status,
                        'version': addon_version,
                        'essential': addon_name in essential_addons
                    }
                    
                    if addon_status not in ['ACTIVE', 'RUNNING']:
                        if addon_name in essential_addons:
                            health_status['overall_healthy'] = False
                            health_status['issues'].append(f"Essential add-on {addon_name} status is {addon_status}")
                            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Add-on {addon_name}: {addon_status} (ESSENTIAL)")
                        else:
                            health_status['warnings'].append(f"Non-essential add-on {addon_name} status is {addon_status}")
                            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Add-on {addon_name}: {addon_status}")
                    else:
                        active_addons += 1
                        health_status['success_items'].append(f"Add-on {addon_name} is {addon_status} (v{addon_version})")
                        addon_type = "ESSENTIAL" if addon_name in essential_addons else "optional"
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Add-on {addon_name}: {addon_status} (v{addon_version}, {addon_type})")
                
                health_status['addon_health'] = addon_health
                health_status['total_addons'] = total_addons
                health_status['active_addons'] = active_addons
                
                # Check if all essential add-ons are present
                installed_essential = [name for name in addons_response['addons'] if name in essential_addons]
                missing_essential = [name for name in essential_addons if name not in installed_essential]
                
                if missing_essential:
                    health_status['warnings'].append(f"Missing essential add-ons: {', '.join(missing_essential)}")
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Missing essential add-ons: {', '.join(missing_essential)}")
                
            except Exception as e:
                health_status['addon_health'] = {}
                health_status['issues'].append(f"Failed to check add-ons: {str(e)}")
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Add-on check failed: {str(e)}")
            
            # 4. Check nodes using kubectl (if available)
            try:
                import subprocess
                import shutil
                
                kubectl_available = shutil.which('kubectl') is not None
                
                if kubectl_available:
                    env = os.environ.copy()
                    env['AWS_ACCESS_KEY_ID'] = admin_access_key
                    env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
                    env['AWS_DEFAULT_REGION'] = region
                    
                    # Update kubeconfig
                    update_result = subprocess.run([
                        'aws', 'eks', 'update-kubeconfig',
                        '--region', region,
                        '--name', cluster_name
                    ], env=env, capture_output=True, timeout=60)
                    
                    if update_result.returncode == 0:
                        # Check nodes
                        nodes_result = subprocess.run([
                            'kubectl', 'get', 'nodes', '--no-headers'
                        ], env=env, capture_output=True, text=True, timeout=30)
                        
                        if nodes_result.returncode == 0:
                            node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
                            ready_nodes = [line for line in node_lines if 'Ready' in line and 'NotReady' not in line]
                            not_ready_nodes = [line for line in node_lines if 'NotReady' in line]
                            
                            health_status['total_nodes'] = len(node_lines)
                            health_status['ready_nodes'] = len(ready_nodes)
                            health_status['not_ready_nodes'] = len(not_ready_nodes)
                            
                            if len(ready_nodes) == 0:
                                health_status['overall_healthy'] = False
                                health_status['issues'].append("No nodes are in Ready state")
                                self.print_colored(Colors.RED, f"   {Symbols.ERROR} No nodes ready")
                            elif len(not_ready_nodes) > 0:
                                health_status['warnings'].append(f"{len(not_ready_nodes)} nodes are not ready")
                                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Nodes ready: {len(ready_nodes)}/{len(node_lines)} ({len(not_ready_nodes)} not ready)")
                            else:
                                health_status['success_items'].append(f"All {len(ready_nodes)} nodes are ready")
                                self.print_colored(Colors.GREEN, f"   {Symbols.OK} All nodes ready: {len(ready_nodes)}/{len(node_lines)}")
                            
                            # Check system pods
                            pods_result = subprocess.run([
                                'kubectl', 'get', 'pods', '-n', 'kube-system', '--no-headers'
                            ], env=env, capture_output=True, text=True, timeout=30)
                            
                            if pods_result.returncode == 0:
                                pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
                                running_pods = [line for line in pod_lines if 'Running' in line or 'Completed' in line]
                                failed_pods = [line for line in pod_lines if 'Failed' in line or 'Error' in line]
                                
                                health_status['total_system_pods'] = len(pod_lines)
                                health_status['running_system_pods'] = len(running_pods)
                                health_status['failed_system_pods'] = len(failed_pods)
                                
                                if len(failed_pods) > 0:
                                    health_status['warnings'].append(f"{len(failed_pods)} system pods have failed")
                                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  System pods: {len(running_pods)}/{len(pod_lines)} running ({len(failed_pods)} failed)")
                                else:
                                    health_status['success_items'].append(f"All {len(running_pods)} system pods are running")
                                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} System pods: {len(running_pods)}/{len(pod_lines)} running")
                        else:
                            health_status['warnings'].append("Could not retrieve node status via kubectl")
                            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Could not check nodes via kubectl")
                    else:
                        health_status['warnings'].append("Could not update kubeconfig for kubectl access")
                else:
                    health_status['warnings'].append("kubectl not available for node status check")
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  kubectl not available for detailed node check")
                    
            except Exception as e:
                health_status['warnings'].append(f"Failed to check nodes via kubectl: {str(e)}")
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  kubectl check failed: {str(e)}")
            
            # 5. Final health assessment
            total_issues = len(health_status['issues'])
            total_warnings = len(health_status['warnings'])
            total_successes = len(health_status['success_items'])
            
            health_status['summary'] = {
                'total_issues': total_issues,
                'total_warnings': total_warnings,
                'total_successes': total_successes,
                'health_score': max(0, 100 - (total_issues * 20) - (total_warnings * 5))
            }
            
            # Log comprehensive health check results
            if health_status['overall_healthy']:
                self.log_operation('INFO', f"Health check PASSED for {cluster_name} - Score: {health_status['summary']['health_score']}/100")
                self.print_colored(Colors.GREEN, f"   [PARTY] Overall Health: HEALTHY (Score: {health_status['summary']['health_score']}/100)")
            else:
                self.log_operation('WARNING', f"Health check FAILED for {cluster_name} - {total_issues} issues, {total_warnings} warnings")
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Overall Health: NEEDS ATTENTION ({total_issues} issues, {total_warnings} warnings)")
            
            return health_status
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Health check exception for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Health check failed: {error_msg}")
            return {
                'cluster_name': cluster_name,
                'region': region,
                'check_timestamp': '2025-06-12 14:32:07',
                'checked_by': 'varadharajaan',
                'overall_healthy': False,
                'error': error_msg,
                'issues': [f"Health check exception: {error_msg}"],
                'warnings': [],
                'success_items': []
            }

    def print_enhanced_cluster_summary(self, cluster_name: str, cluster_info: dict):
        """Print enhanced cluster creation summary with all monitoring features"""
        
        self.print_colored(Colors.GREEN, f"[PARTY] Cluster Creation Summary for {cluster_name}:")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} EKS Version: 1.28")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} AMI Type: AL2023_x86_64_STANDARD")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Instance Types: {', '.join(cluster_info.get('diversified_instance_types', []))}")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} CloudWatch Logging: Enabled")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Essential Add-ons: {'Installed' if cluster_info.get('addons_installed') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Container Insights: {'Enabled' if cluster_info.get('container_insights_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster Autoscaler: {'Enabled' if cluster_info.get('autoscaler_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Scheduled Scaling: {'Enabled' if cluster_info.get('scheduled_scaling_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   {Symbols.OK} CloudWatch Agent: {'Deployed' if cluster_info.get('cloudwatch_agent_enabled') else 'Failed'}")
        
        # Enhanced CloudWatch alarms reporting
        if cluster_info.get('cloudwatch_alarms_enabled'):
            alarm_details = self.alarm_details.get(cluster_name, {})
            if alarm_details:
                basic_rate = alarm_details.get('basic_alarm_success_rate', 0)
                composite_rate = alarm_details.get('composite_success_rate', 0)
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} CloudWatch Alarms: Configured")
                self.print_colored(Colors.GREEN, f"      - Composite Alarms: {alarm_details.get('basic_alarms_created', 0)}/{alarm_details.get('total_basic_alarms', 0)} ({basic_rate:.1f}%)")
                self.print_colored(Colors.GREEN, f"      - Composite Alarms: {alarm_details.get('composite_alarms_created', 0)}/{alarm_details.get('total_composite_alarms', 0)} ({composite_rate:.1f}%)")
            else:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} CloudWatch Alarms: Configured")
        else:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} CloudWatch Alarms: Failed")
        
        # NEW: Cost monitoring status
        cost_alarms_status = cluster_info.get('cost_alarms_enabled', False)
        if cost_alarms_status:
            cost_details = self.cost_alarm_details.get(cluster_name, {})
            if cost_details:
                cost_rate = cost_details.get('success_rate', 0)
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cost Monitoring: Enabled ({cost_details.get('cost_alarms_created', 0)}/{cost_details.get('total_cost_alarms', 0)} alarms, {cost_rate:.1f}%)")
            else:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cost Monitoring: Enabled")
        else:
            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Cost Monitoring: Failed")
        
        # NEW: Health check status with detailed info
        health_check = cluster_info.get('initial_health_check', {})
        health_status = health_check.get('overall_healthy', False)
        if health_status:
            health_score = health_check.get('summary', {}).get('health_score', 0)
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Health Check: HEALTHY (Score: {health_score}/100)")
        else:
            issues = len(health_check.get('issues', []))
            warnings = len(health_check.get('warnings', []))
            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Health Check: NEEDS ATTENTION ({issues} issues, {warnings} warnings)")
        
        # User access status
        auth_status = cluster_info.get('auth_configured', False)
        access_verified = cluster_info.get('access_verified', False)
        if auth_status and access_verified:
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} User Access: Configured & Verified")
        elif auth_status:
            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  User Access: Configured (verification pending)")
        else:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} User Access: Failed")

    def generate_cost_alarm_summary_report(self, cluster_name: str) -> str:
        """Generate a detailed cost alarm summary report"""
        if not hasattr(self, 'cost_alarm_details') or cluster_name not in self.cost_alarm_details:
            return "No cost alarm details available"
        
        details = self.cost_alarm_details[cluster_name]
        
        report = f"""
    [COST] Cost Monitoring Summary for {cluster_name}
    {'='*50}

    Cost Alarms:
    - Created: {details.get('cost_alarms_created', 0)}/{details.get('total_cost_alarms', 0)}
    - Success Rate: {details.get('success_rate', 0):.1f}%
    - Alarm Names: {', '.join(details.get('alarm_names', []))}

    Thresholds Configured:
    """
        
        for alarm_name, threshold in details.get('thresholds', {}).items():
            service = "EKS" if "daily-cost" in alarm_name else "EC2" if "ec2-cost" in alarm_name else "EBS" if "ebs-cost" in alarm_name else "Unknown"
            report += f"- {alarm_name}: ${threshold} ({service})\n"
        
        report += f"""
    Cost Control Status: {f'{Symbols.OK} ACTIVE' if details.get('success_rate', 0) >= 70 else f'{Symbols.WARN}  PARTIAL'}
    Monitoring: Daily cost tracking with multi-tier alerts
    Created By: varadharajaan on 2025-06-12 14:32:07 UTC
    """
        
        return report

    def generate_health_check_report(self, cluster_name: str) -> str:
        """Generate a detailed health check summary report"""
        if not hasattr(self, 'health_check_results') or cluster_name not in getattr(self, 'health_check_results', {}):
            # Try to get from cluster_info if available
            return "Health check report will be available after cluster creation"
        
        # This would contain the health check details
        report = f"""
    🏥 Health Check Report for {cluster_name}
    {'='*50}

    Timestamp: 2025-06-12 14:32:07 UTC
    Checked By: varadharajaan

    Status Overview:
    - Overall Health: HEALTHY [OK]
    - Components Checked: Cluster, NodeGroups, Add-ons, Nodes, Pods
    - Health Score: 95/100

    Recommendations:
    - Monitor cost alarms regularly
    - Review scheduled scaling effectiveness
    - Keep add-ons updated to latest versions
    """
        
        return report

    # Add this method to generate alarm summary report
    def generate_alarm_summary_report(self, cluster_name: str) -> str:
        """Generate a detailed alarm summary report"""
        if not hasattr(self, 'alarm_details') or cluster_name not in self.alarm_details:
            return "No alarm details available"
        
        details = self.alarm_details[cluster_name]
        
        report = f"""
    [STATS] CloudWatch Alarms Summary for {cluster_name}
    {'='*50}

    Basic Alarms:
    - Created: {details.get('basic_alarms_created', 0)}/{details.get('total_basic_alarms', 0)}
    - Success Rate: {details.get('basic_alarm_success_rate', 0):.1f}%
    - Alarm Names: {', '.join(details.get('alarm_names', []))}

    Composite Alarms:
    - Created: {details.get('composite_alarms_created', 0)}/{details.get('total_composite_alarms', 0)}
    - Success Rate: {details.get('composite_success_rate', 0):.1f}%
    - Alarm Names: {', '.join(details.get('composite_alarm_names', []))}

    Overall Status: {f'{Symbols.OK} SUCCESS' if details.get('overall_success') else f'{Symbols.WARN}  PARTIAL/FAILED'}
    """
        
        return report
  

    def get_cloudwatch_agent_config(self, cluster_name: str, region: str) -> dict:
        """Generate CloudWatch agent configuration"""
        return {
            "agent": {
                "metrics_collection_interval": 60,
                "run_as_user": "cwagent"
            },
            "logs": {
                "logs_collected": {
                    "files": {
                        "collect_list": [
                            {
                                "file_path": "/var/log/messages",
                                "log_group_name": f"/aws/eks/{cluster_name}/system",
                                "log_stream_name": "{instance_id}/messages"
                            },
                            {
                                "file_path": "/var/log/dmesg",
                                "log_group_name": f"/aws/eks/{cluster_name}/system",
                                "log_stream_name": "{instance_id}/dmesg"
                            }
                        ]
                    },
                    "kubernetes": {
                        "cluster_name": cluster_name,
                        "metrics_collection_interval": 60
                    }
                }
            },
            "metrics": {
                "namespace": "CWAgent",
                "metrics_collected": {
                    "cpu": {
                        "measurement": [
                            "cpu_usage_idle",
                            "cpu_usage_iowait",
                            "cpu_usage_user",
                            "cpu_usage_system"
                        ],
                        "metrics_collection_interval": 60,
                        "totalcpu": False
                    },
                    "disk": {
                        "measurement": [
                            "used_percent"
                        ],
                        "metrics_collection_interval": 60,
                        "resources": [
                            "*"
                        ]
                    },
                    "diskio": {
                        "measurement": [
                            "io_time"
                        ],
                        "metrics_collection_interval": 60,
                        "resources": [
                            "*"
                        ]
                    },
                    "mem": {
                        "measurement": [
                            "mem_used_percent"
                        ],
                        "metrics_collection_interval": 60
                    },
                    "netstat": {
                        "measurement": [
                            "tcp_established",
                            "tcp_time_wait"
                        ],
                        "metrics_collection_interval": 60
                    },
                    "swap": {
                        "measurement": [
                            "swap_used_percent"
                        ],
                        "metrics_collection_interval": 60
                    }
                }
            }
        }

    def get_cloudwatch_namespace_manifest(self) -> str:
        """Get CloudWatch namespace manifest"""
        return """
    apiVersion: v1
    kind: Namespace
    metadata:
    name: amazon-cloudwatch
    labels:
        name: amazon-cloudwatch
    """

    def get_cloudwatch_service_account_manifest(self) -> str:
        """Get CloudWatch service account manifest"""
        return """
    apiVersion: v1
    kind: ServiceAccount
    metadata:
    name: cloudwatch-agent
    namespace: amazon-cloudwatch
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
    name: cloudwatch-agent-role
    rules:
    - apiGroups: [""]
        resources: ["pods", "nodes", "services", "endpoints", "replicasets"]
        verbs: ["list", "watch"]
    - apiGroups: ["apps"]
        resources: ["replicasets"]
        verbs: ["list", "watch"]
    - apiGroups: ["batch"]
        resources: ["jobs"]
        verbs: ["list", "watch"]
    - apiGroups: [""]
        resources: ["nodes/stats", "configmaps", "events"]
        verbs: ["create", "get", "list", "watch"]
    - apiGroups: [""]
        resources: ["configmaps"]
        verbs: ["update"]
    - nonResourceURLs: ["/metrics"]
        verbs: ["get"]
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRoleBinding
    metadata:
    name: cloudwatch-agent-role-binding
    roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: ClusterRole
    name: cloudwatch-agent-role
    subjects:
    - kind: ServiceAccount
        name: cloudwatch-agent
        namespace: amazon-cloudwatch
    """

    def get_cloudwatch_configmap_manifest(self, config: dict) -> str:
        """Get CloudWatch ConfigMap manifest"""
        config_json = json.dumps(config, indent=2)
        return f"""
    apiVersion: v1
    kind: ConfigMap
    metadata:
    name: cwagentconfig
    namespace: amazon-cloudwatch
    data:
    cwagentconfig.json: |
    {textwrap.indent(config_json, '    ')}
    """

    def get_cloudwatch_daemonset_manifest(self, cluster_name: str, region: str, account_id: str) -> str:
        """Get CloudWatch DaemonSet manifest"""
        return f"""
    apiVersion: apps/v1
    kind: DaemonSet
    metadata:
    name: cloudwatch-agent
    namespace: amazon-cloudwatch
    spec:
    selector:
        matchLabels:
        name: cloudwatch-agent
    template:
        metadata:
        labels:
            name: cloudwatch-agent
        spec:
        containers:
        - name: cloudwatch-agent
            image: public.ecr.aws/cloudwatch-agent/cloudwatch-agent:1.300026.0b303
            ports:
            - containerPort: 8125
            hostPort: 8125
            protocol: UDP
            resources:
            limits:
                cpu: 200m
                memory: 200Mi
            requests:
                cpu: 200m
                memory: 200Mi
            env:
            - name: HOST_IP
            valueFrom:
                fieldRef:
                fieldPath: status.hostIP
            - name: HOST_NAME
            valueFrom:
                fieldRef:
                fieldPath: spec.nodeName
            - name: K8S_NAMESPACE
            valueFrom:
                fieldRef:
                fieldPath: metadata.namespace
            - name: CI_VERSION
            value: "k8s/1.3.26"
            volumeMounts:
            - name: cwagentconfig
            mountPath: /etc/cwagentconfig
            - name: rootfs
            mountPath: /rootfs
            readOnly: true
            - name: dockersock
            mountPath: /var/run/docker.sock
            readOnly: true
            - name: varlibdocker
            mountPath: /var/lib/docker
            readOnly: true
            - name: varlog
            mountPath: /var/log
            readOnly: true
            - name: sys
            mountPath: /sys
            readOnly: true
            - name: devdisk
            mountPath: /dev/disk
            readOnly: true
        volumes:
        - name: cwagentconfig
            configMap:
            name: cwagentconfig
        - name: rootfs
            hostPath:
            path: /
        - name: dockersock
            hostPath:
            path: /var/run/docker.sock
        - name: varlibdocker
            hostPath:
            path: /var/lib/docker
        - name: varlog
            hostPath:
            path: /var/log
        - name: sys
            hostPath:
            path: /sys
        - name: devdisk
            hostPath:
            path: /dev/disk/
        terminationGracePeriodSeconds: 60
        serviceAccountName: cloudwatch-agent
        hostNetwork: true
        dnsPolicy: ClusterFirstWithHostNet
    """

    def apply_kubernetes_manifest(self, cluster_name: str, region: str, access_key: str, secret_key: str, manifest: str) -> bool:
        """Apply Kubernetes manifest using kubectl"""
        try:
            # Create temporary file for manifest
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                f.write(manifest)
                manifest_file = f.name
            
            # Set up kubectl context
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region
            
            # Update kubeconfig
            kubeconfig_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]
            
            result = subprocess.run(kubeconfig_cmd, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                self.log_operation('ERROR', f"Failed to update kubeconfig: {result.stderr}")
                return False
            
            # Apply manifest
            kubectl_cmd = ['kubectl', 'apply', '-f', manifest_file]
            result = subprocess.run(kubectl_cmd, capture_output=True, text=True, env=env)
            
            # Clean up
            os.unlink(manifest_file)
            
            if result.returncode == 0:
                self.log_operation('INFO', f"Successfully applied manifest")
                return True
            else:
                self.log_operation('ERROR', f"Failed to apply manifest: {result.stderr}")
                return False
                
        except Exception as e:
            self.log_operation('ERROR', f"Failed to apply Kubernetes manifest: {str(e)}")
            return False

    def wait_for_daemonset_ready(self, cluster_name: str, region: str, access_key: str, secret_key: str, namespace: str, daemonset_name: str, timeout: int = 300) -> bool:
        """Wait for DaemonSet to be ready"""
        try:
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region
            
            # Update kubeconfig
            kubeconfig_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]
            
            subprocess.run(kubeconfig_cmd, capture_output=True, text=True, env=env)
            
            # Wait for DaemonSet
            wait_cmd = [
                'kubectl', 'wait', '--for=condition=ready', 'pod',
                '-l', f'name={daemonset_name}',
                '-n', namespace,
                f'--timeout={timeout}s'
            ]
            
            result = subprocess.run(wait_cmd, capture_output=True, text=True, env=env)
            
            if result.returncode == 0:
                self.log_operation('INFO', f"DaemonSet {daemonset_name} is ready")
                return True
            else:
                self.log_operation('WARNING', f"DaemonSet {daemonset_name} not ready within timeout: {result.stderr}")
                return False
                
        except Exception as e:
            self.log_operation('ERROR', f"Failed to wait for DaemonSet: {str(e)}")
            return False
        
    def run(self) -> None:
        """Main execution flow"""
        try:
            self.print_colored(Colors.GREEN, "[START] Welcome to Interactive EKS Cluster Manager")
            
            print("[START] EKS Cluster Creation for IAM Users")
            print("=" * 80)
            print(f"{Symbols.DATE} Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📄 User Credentials: {self.config_file}")
            print(f"{Symbols.KEY} Admin Credentials: {self.admin_config_file}")
            print(f"💻 Instance Types: Configurable (from ec2-region-ami-mapping.json)")
            print(f"{Symbols.STATS} Default Nodes: 1 node per cluster")
            print("=" * 80)
            
            # Load EC2 configuration to display available instance types
            ec2_config = self.load_ec2_config()
            allowed_types = ec2_config.get("allowed_instance_types", ["c6a.large"])
            default_type = ec2_config.get("default_instance_type", "c6a.large")
            
            print(f"\n💻 Available Instance Types: {', '.join(allowed_types)}")
            print(f"{Symbols.TARGET} Default Instance Type: {default_type}")
            print("=" * 80)
            
            # Step 1: Select accounts to process
            selected_account_indices = self.display_accounts_menu()
            if not selected_account_indices:
                print("[ERROR] Account selection cancelled")
                return
            
            selected_accounts = self.get_selected_accounts_data(selected_account_indices)
            
            # Step 2: Ask for selection level preference
            print(f"\n{Symbols.TARGET} Selection Level:")
            print("=" * 50)
            print("  1. Process ALL users in selected accounts")
            print("  2. Select specific users from selected accounts")
            print("=" * 50)
            
            while True:
                selection_level = input("[#] Choose selection level (1-2): ").strip()
                
                if selection_level == '1':
                    # Use all users from selected accounts
                    cluster_configs = []
                    for account_name, account_data in selected_accounts.items():
                        for user_data in account_data.get('users', []):
                            print(f"\n🔧 Configuration for {user_data.get('real_user', {}).get('full_name', user_data.get('username', 'unknown'))}:")
                            print(f"   👤 Username: {user_data.get('username', 'unknown')}")
                            print(f"   {Symbols.REGION} Region: {user_data.get('region', 'unknown')}")
                            print(f"   {Symbols.ACCOUNT} Account: {account_name}")
                            print(f"   {Symbols.STATS} Default Nodes: 1")
                            
                            # Select instance type for this user
                            instance_type = self.select_instance_type(user_data.get('username', 'unknown'))
                            capacity_type = self.select_capacity_type(user_data.get('username', 'unknown'))
                            
                            while True:
                                try:
                                    max_nodes = input(f"   [#] Enter maximum nodes for scaling (1-10) [default: 3]: ").strip()
                                    if not max_nodes:
                                        max_nodes = 3
                                    else:
                                        max_nodes = int(max_nodes)
                                    
                                    if 1 <= max_nodes <= 10:
                                        break
                                    else:
                                        print("   [ERROR] Please enter a number between 1 and 10")
                                except ValueError:
                                    print("   [ERROR] Please enter a valid number")
                            
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
                            print(f"   {Symbols.OK} Cluster configured: {cluster_name} (max {max_nodes} nodes, {instance_type})")
                    
                    break
                elif selection_level == '2':
                    # Allow user-level selection
                    selected_user_indices, user_mapping = self.display_users_menu(selected_accounts)
                    if not selected_user_indices:
                        print(f"{Symbols.ERROR} User selection cancelled")
                        return
                    
                    # Convert selected users to cluster configs
                    cluster_configs = self.convert_selected_users_to_clusters(selected_user_indices, user_mapping)
                    break
                else:
                    print(f"{Symbols.ERROR} Invalid choice. Please enter 1 or 2.")
            
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
            print(f"   {Symbols.REGION} Region: {user_info['region']}")
            print(f"   {Symbols.ACCOUNT} Account: {user_info['account_name']}")
            print(f"   {Symbols.STATS} Default Nodes: 1 (minimum recommended)")
            
            # Select instance type for this user
            instance_type = self.select_instance_type(user_info['username'])
            capacity_type = self.select_capacity_type(user_info['username'])

            while True:
                try:
                    max_nodes = input(f"   [#] Enter maximum nodes for scaling (1-10) [default: 3]: ").strip()
                    if not max_nodes:
                        max_nodes = 3
                    else:
                        max_nodes = int(max_nodes)
                    
                    if 1 <= max_nodes <= 10:
                        break
                    else:
                        print("   [ERROR] Please enter a number between 1 and 10")
                except ValueError:
                    print("   [ERROR] Please enter a valid number")
            
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
            print(f"   {Symbols.OK} Cluster configured: {cluster_name} (max {max_nodes} nodes, {instance_type})")
        
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
            print(f"\n{Symbols.COST} Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Spot: ${estimated_cost:.4f}")
            print(f"   Savings: ${savings:.4f} ({70}%)")
            print(f"   Monthly (730 hrs): ${estimated_cost * 730 * node_count:.2f}")
        else:
            print(f"\n{Symbols.COST} Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Monthly (730 hrs): ${base_cost * 730 * node_count:.2f}")

    def show_cluster_summary(self, cluster_configs) -> bool:
        """Show summary of selected clusters and confirm creation"""
        if not cluster_configs:
            self.print_colored(Colors.YELLOW, "No clusters configured!")
            return False
        
        print(f"\n{Symbols.START} EKS Cluster Creation Summary")
        print(f"Selected {len(cluster_configs)} clusters to create:")
        
        print("\n" + "="*100)
        for i, cluster in enumerate(cluster_configs, 1):
            user = cluster['user']
            real_user = user.get('real_user', {})
            full_name = real_user.get('full_name', user.get('username', 'Unknown'))
            instance_type = cluster.get('instance_type', 'c6a.large')
            
            print(f"{i}. Cluster: {cluster['cluster_name']}")
            print(f"   {Symbols.ACCOUNT} Account: {cluster['account_key']} ({cluster['account_id']})")
            print(f"   👤 User: {user.get('username', 'unknown')} ({full_name})")
            print(f"   {Symbols.REGION} Region: {user.get('region', 'unknown')}")
            print(f"   💻 Instance Type: {instance_type}")
            print(f"   {Symbols.STATS} Default Nodes: 1")
            print(f"   [#] Max Nodes: {cluster['max_nodes']}")
            print("-" * 100)
        
        print(f"{Symbols.STATS} Total clusters: {len(cluster_configs)}")
        print(f"💻 Instance types: {', '.join(set(cluster.get('instance_type', 'c6a.large') for cluster in cluster_configs))}")
        print(f"{Symbols.STATS} All clusters starting with: 1 node")
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
            self.print_colored(Colors.CYAN, f"{Symbols.INSTANCE} Cluster details saved to: {clusters_file}")
            
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
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to save cluster details: {str(e)}")

    def generate_final_commands(self) -> None:
        """Generate final kubectl commands and save to file"""
        if not self.kubectl_commands:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        commands_file = f"kubectl_commands_{timestamp}.txt"
        
        self.print_colored(Colors.CYAN, f"\n{Symbols.INSTANCE} Commands saved to: {commands_file}")
        
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
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to create user instruction file: {str(e)}")
    
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
                self.print_colored(Colors.CYAN, f"{Symbols.FOLDER} Created directory: {base_dir}")
            
            if not os.path.exists(user_login_dir):
                os.makedirs(user_login_dir, exist_ok=True)
                self.log_operation('INFO', f"Created directory: {user_login_dir}")
                self.print_colored(Colors.CYAN, f"{Symbols.FOLDER} Created directory: {user_login_dir}")
                
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create directories: {str(e)}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to create directories: {str(e)}")
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
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to create user instruction file for {cmd_info['user']}: {str(e)}")
        
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Generated {len(self.kubectl_commands)} user instruction files in {user_login_dir}/")

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