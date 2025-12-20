#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWS Account Resource Manager - EC2 + EKS Creator for Root Users
Creates EC2 instances and EKS clusters for selected AWS accounts using root user credentials
Author: varadharajaan
Date: 2025-06-02 04:11:48 UTC
"""

import boto3
import json
import sys
import os
import time
import glob
import re
import random
import string
from datetime import datetime
from botocore.exceptions import ClientError
from logger import setup_logger

# UTF-8 Encoding Support
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    NC = '\033[0m'

class AWSAccountResourceManager:
    def __init__(self, 
                 credentials_file=None,
                 ami_mapping_file='ec2-region-ami-mapping.json',
                 userdata_file='userdata.sh',
                 eks_config_file='eks-cluster-config.json'):
        
        self.ami_mapping_file = ami_mapping_file
        self.userdata_file = userdata_file
        self.eks_config_file = eks_config_file
        self.default_region = 'eu-north-1'  # Default region as specified
        self.logger = setup_logger("aws_resource_manager", "aws_resource_creation")
        
        # Find credentials file
        self.credentials_file = credentials_file or self.find_latest_credentials_file()
        
        # Load configurations
        self.load_configurations()
        
        # Set current user and time (using provided values)
        self.current_time = "2025-06-02 04:11:48"
        self.current_user = "varadharajaan"
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Load user data script
        self.user_data_script = self.load_user_data_script()
        
        # Setup logging
        self.setup_detailed_logging()
        
    def print_colored(self, color: str, message: str) -> None:
        """Print colored message with encoding safety"""
        try:
            print(f"{color}{message}{Colors.NC}")
        except UnicodeEncodeError:
            ascii_message = message.encode('ascii', 'replace').decode('ascii')
            print(f"{color}{ascii_message}{Colors.NC}")
        except Exception:
            print(f"[MESSAGE] {str(message)}")

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"aws_resource_creation_log_{self.execution_timestamp}.log"
            
            import logging
            
            self.operation_logger = logging.getLogger('aws_resource_operations')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
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
            self.operation_logger.info("AWS Account Resource Creation Session Started")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Default Region: {self.default_region}")
            self.operation_logger.info(f"Credentials File: {self.credentials_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 80)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Log operation to both console and file"""
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
            print(f"[{level.upper()}] {message}")

    def find_latest_credentials_file(self):
        """Find the latest iam_users_credentials file based on timestamp"""
        try:
            pattern = "iam_users_credentials_*.json"
            matching_files = glob.glob(pattern)
            
            if not matching_files:
                raise FileNotFoundError(f"No IAM credentials files found matching pattern: {pattern}")
            
            file_timestamps = []
            for file_path in matching_files:
                match = re.search(r'iam_users_credentials_(\d{8}_\d{6})\.json', file_path)
                if match:
                    timestamp_str = match.group(1)
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        file_timestamps.append((file_path, timestamp, timestamp_str))
                    except ValueError:
                        continue
            
            if not file_timestamps:
                raise ValueError("No valid credential files with proper timestamp format found")
            
            file_timestamps.sort(key=lambda x: x[1], reverse=True)
            latest_file = file_timestamps[0][0]
            
            self.print_colored(Colors.GREEN, f"[SUCCESS] Using latest credentials file: {latest_file}")
            return latest_file
            
        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Error finding credentials file: {e}")
            raise

    def load_configurations(self):
        """Load all configuration files"""
        try:
            # Load IAM credentials
            if not os.path.exists(self.credentials_file):
                raise FileNotFoundError(f"Credentials file '{self.credentials_file}' not found")
            
            with open(self.credentials_file, 'r', encoding='utf-8') as f:
                self.credentials_data = json.load(f)
            
            # Count actual accounts in the file
            actual_account_count = len(self.credentials_data.get('accounts', {}))
            
            self.print_colored(Colors.GREEN, f"[SUCCESS] Credentials loaded from: {self.credentials_file}")
            self.print_colored(Colors.CYAN, f"[INFO] Found {actual_account_count} accounts in credentials file")
            
            # Load AMI mappings
            if not os.path.exists(self.ami_mapping_file):
                raise FileNotFoundError(f"AMI mapping file '{self.ami_mapping_file}' not found")
            
            with open(self.ami_mapping_file, 'r', encoding='utf-8') as f:
                self.ami_config = json.load(f)
            
            self.print_colored(Colors.GREEN, f"[SUCCESS] AMI mappings loaded from: {self.ami_mapping_file}")
            
            # Load EKS configuration (optional)
            if os.path.exists(self.eks_config_file):
                with open(self.eks_config_file, 'r', encoding='utf-8') as f:
                    self.eks_config = json.load(f)
                self.print_colored(Colors.GREEN, f"[SUCCESS] EKS config loaded from: {self.eks_config_file}")
            else:
                # Default EKS configuration
                self.eks_config = {
                    "default_kubernetes_version": "1.28",
                    "default_node_instance_type": "t3.medium",
                    "default_node_count": 2,
                    "default_node_disk_size": 20
                }
                self.print_colored(Colors.YELLOW, f"[WARNING] Using default EKS configuration")
            
        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Error loading configuration: {e}")
            sys.exit(1)

    def load_user_data_script(self):
        """Load the user data script content"""
        try:
            if not os.path.exists(self.userdata_file):
                self.print_colored(Colors.YELLOW, f"[WARNING] User data script not found: {self.userdata_file}")
                return self.get_default_userdata()
            
            with open(self.userdata_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.print_colored(Colors.GREEN, f"[SUCCESS] User data script loaded from: {self.userdata_file}")
            return content
            
        except Exception as e:
            self.print_colored(Colors.YELLOW, f"[WARNING] Error loading user data script: {e}")
            return self.get_default_userdata()

    def get_default_userdata(self):
        """Return default user data script"""
        return """#!/bin/bash
yum update -y
yum install -y git vim htop aws-cli

# Configure AWS CLI
echo "Configuring AWS CLI..."
mkdir -p /home/ec2-user/.aws
mkdir -p /root/.aws

# Configure for ec2-user
sudo -u ec2-user aws configure set aws_access_key_id "${AWS_ACCESS_KEY_ID}"
sudo -u ec2-user aws configure set aws_secret_access_key "${AWS_SECRET_ACCESS_KEY}"
sudo -u ec2-user aws configure set default.region "${AWS_DEFAULT_REGION}"
sudo -u ec2-user aws configure set default.output json

# Set proper permissions
chown -R ec2-user:ec2-user /home/ec2-user/.aws
chmod 600 /home/ec2-user/.aws/credentials /home/ec2-user/.aws/config

# Test configuration
sudo -u ec2-user aws sts get-caller-identity

echo "AWS CLI configured successfully!"
"""

    def get_account_region(self, account_data):
        """Extract region from account data, fallback to default"""
        # Check multiple possible region field names
        region_fields = ['region', 'aws_region', 'default_region', 'Region']
        
        for field in region_fields:
            if field in account_data and account_data[field]:
                region = account_data[field].strip()
                if region:
                    self.log_operation('INFO', f"Found region in account data: {region}")
                    return region
        
        # Check root user data for region
        root_user = self.get_root_user_from_account(account_data)
        if root_user:
            for field in region_fields:
                if field in root_user and root_user[field]:
                    region = root_user[field].strip()
                    if region:
                        self.log_operation('INFO', f"Found region in root user data: {region}")
                        return region
        
        # Use default region
        self.log_operation('INFO', f"No region found in account data, using default: {self.default_region}")
        return self.default_region

    def get_root_user_from_account(self, account_data):
        """Extract root user credentials from account data"""
        # For root user credentials, look for account-level credentials or designated root user
        
        # Method 1: Check if account has direct root credentials
        if all(key in account_data for key in ['access_key_id', 'secret_access_key']):
            self.log_operation('INFO', "Found account-level root credentials")
            return {
                'username': 'root',
                'access_key_id': account_data['access_key_id'],
                'secret_access_key': account_data['secret_access_key'],
                'is_root': True,
                'account_type': 'root'
            }
        
        # Method 2: Check if account has root_credentials section
        if 'root_credentials' in account_data:
            root_creds = account_data['root_credentials']
            if all(key in root_creds for key in ['access_key_id', 'secret_access_key']):
                self.log_operation('INFO', "Found root_credentials section")
                return {
                    'username': 'root',
                    'access_key_id': root_creds['access_key_id'],
                    'secret_access_key': root_creds['secret_access_key'],
                    'is_root': True,
                    'account_type': 'root'
                }
        
        # Method 3: Look for users marked as root or admin
        if 'users' in account_data:
            for user in account_data['users']:
                username = user.get('username', '').lower()
                user_type = user.get('user_type', '').lower()
                is_root = user.get('is_root', False)
                
                if (is_root or 
                    'root' in username or 
                    'admin' in username or 
                    user_type in ['root', 'admin', 'administrator']):
                    
                    if all(key in user for key in ['access_key_id', 'secret_access_key']):
                        self.log_operation('INFO', f"Found root-like user: {user.get('username', 'unknown')}")
                        return user
        
        # Method 4: If no explicit root user, use first user with admin/full permissions
        if 'users' in account_data and account_data['users']:
            first_user = account_data['users'][0]
            if all(key in first_user for key in ['access_key_id', 'secret_access_key']):
                self.log_operation('WARNING', "No explicit root user found, using first available user")
                return first_user
        
        return None

    def display_accounts_menu(self):
        """Display available accounts and return account selection"""
        if 'accounts' not in self.credentials_data:
            self.print_colored(Colors.RED, "[ERROR] No accounts found in credentials data")
            return []
        
        accounts = list(self.credentials_data['accounts'].items())
        actual_count = len(accounts)
        
        self.print_colored(Colors.CYAN, f"\n[INFO] Available AWS Accounts ({actual_count} total):")
        print("=" * 90)
        
        for i, (account_name, account_data) in enumerate(accounts, 1):
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            # Get region for this account
            region = self.get_account_region(account_data)
            
            # Check if account has root user credentials
            root_user = self.get_root_user_from_account(account_data)
            root_status = "[SUCCESS] Root credentials found" if root_user else "[ERROR] No root credentials"
            
            print(f"  {i:2}. {account_name}")
            print(f"      [ACCOUNT] Email: {account_email}")
            print(f"      [ACCOUNT] Account ID: {account_id}")
            print(f"      [REGION] {region}")
            print(f"      [CREDENTIALS] {root_status}")
            if root_user:
                username = root_user.get('username', 'Unknown')
                access_key_preview = root_user.get('access_key_id', '')[:10] + '...' if root_user.get('access_key_id') else 'N/A'
                print(f"      [ROOT USER] {username} (Key: {access_key_preview})")
            print()
        
        print("=" * 90)
        
        self.print_colored(Colors.YELLOW, f"[INFO] Selection Options:")
        print(f"   • Single accounts: 1,3,5")
        print(f"   • Ranges: 1-{actual_count} (accounts 1 through {actual_count})")
        print(f"   • Mixed: 1-2,4 (accounts 1, 2, and 4)")
        print(f"   • All accounts: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n[INPUT] Select accounts to process: ").strip()
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all accounts")
                return list(range(1, actual_count + 1))
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled account selection")
                return []
            
            try:
                selected_indices = self.parse_selection(selection, actual_count)
                if selected_indices:
                    # Show confirmation
                    selected_accounts = []
                    for idx in selected_indices:
                        account_name, account_data = accounts[idx - 1]
                        region = self.get_account_region(account_data)
                        selected_accounts.append(f"{account_name} ({region})")
                    
                    self.print_colored(Colors.GREEN, f"[SUCCESS] Selected {len(selected_indices)} out of {actual_count} accounts:")
                    for acc in selected_accounts:
                        print(f"  • {acc}")
                    
                    confirm = input(f"\n[INPUT] Proceed with these {len(selected_indices)} accounts? (y/N): ").lower().strip()
                    if confirm == 'y':
                        return selected_indices
                    else:
                        self.print_colored(Colors.YELLOW, "[INFO] Selection cancelled, please choose again.")
                        continue
                else:
                    self.print_colored(Colors.RED, "[ERROR] No valid accounts selected. Please try again.")
            except ValueError as e:
                self.print_colored(Colors.RED, f"[ERROR] Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")

    def parse_selection(self, selection, max_items):
        """Parse selection string and return list of indices"""
        selected_indices = set()
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                start_str, end_str = part.split('-', 1)
                start = int(start_str.strip())
                end = int(end_str.strip())
                
                if start < 1 or end > max_items:
                    raise ValueError(f"Range {part} is out of bounds (1-{max_items})")
                
                if start > end:
                    raise ValueError(f"Invalid range {part}: start must be <= end")
                
                selected_indices.update(range(start, end + 1))
            else:
                num = int(part)
                if num < 1 or num > max_items:
                    raise ValueError(f"Number {num} is out of bounds (1-{max_items})")
                selected_indices.add(num)
        
        return sorted(list(selected_indices))

    def display_resource_menu(self):
        """Display resource creation options - separate EC2 and EKS options"""
        self.print_colored(Colors.CYAN, f"\n[INFO] Resource Creation Options:")
        print("=" * 60)
        print("  1. Create EC2 Instance only")
        print("  2. Create EKS Cluster only")  
        print("  3. Create EC2 Instance first, then EKS Cluster")
        print("  4. Create EKS Cluster first, then EC2 Instance")
        print("  5. Create both EC2 and EKS simultaneously")
        print("  6. Cancel operation")
        print("=" * 60)
        
        while True:
            choice = input(f"\n[INPUT] Select resource creation option (1-6): ").strip()
            
            if choice == '1':
                return 'ec2_only'
            elif choice == '2':
                return 'eks_only'
            elif choice == '3':
                return 'ec2_then_eks'
            elif choice == '4':
                return 'eks_then_ec2'
            elif choice == '5':
                return 'both_simultaneous'
            elif choice == '6':
                return 'cancel'
            else:
                self.print_colored(Colors.RED, "[ERROR] Invalid choice. Please enter 1, 2, 3, 4, 5, or 6.")

    def create_ec2_instance(self, account_name, account_data, root_user, region):
        """Create EC2 instance for root user"""
        try:
            self.print_colored(Colors.YELLOW, f"[PROCESSING] Creating EC2 instance for account: {account_name} in {region}")
            
            # Extract credentials
            access_key = root_user.get('access_key_id', '')
            secret_key = root_user.get('secret_access_key', '')
            username = root_user.get('username', 'root')
            
            if not access_key or not secret_key:
                raise ValueError("Missing AWS root user credentials")
            
            # Create EC2 client
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test connection
            try:
                ec2_client.describe_regions(RegionNames=[region])
                self.log_operation('INFO', f"Successfully connected to EC2 in {region}")
            except Exception as e:
                raise ValueError(f"Failed to connect to EC2 in {region}: {str(e)}")
            
            # Get AMI for region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            # Get default VPC and subnet
            vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
            if not vpcs['Vpcs']:
                raise ValueError(f"No default VPC found in region {region}")
            
            vpc_id = vpcs['Vpcs'][0]['VpcId']
            
            subnets = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'default-for-az', 'Values': ['true']}
                ]
            )
            
            if not subnets['Subnets']:
                raise ValueError(f"No default subnets found in VPC {vpc_id}")
            
            subnet_id = subnets['Subnets'][0]['SubnetId']
            
            # Create or get security group
            random_suffix = self.generate_random_suffix()
            sg_name = f"{account_name}-root-sg-{random_suffix}"
            
            try:
                sg_response = ec2_client.create_security_group(
                    GroupName=sg_name,
                    Description=f'Security group for {account_name} root user instance',
                    VpcId=vpc_id
                )
                sg_id = sg_response['GroupId']
                
                # Add security group rules
                ec2_client.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[{
                        'IpProtocol': '-1',
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow all traffic'}]
                    }]
                )
                
                self.log_operation('INFO', f"Created new security group: {sg_id}")
                
            except ClientError as e:
                if 'InvalidGroup.Duplicate' in str(e):
                    # Generate new name and try again
                    random_suffix = self.generate_random_suffix()
                    sg_name = f"{account_name}-root-sg-{random_suffix}"
                    sg_response = ec2_client.create_security_group(
                        GroupName=sg_name,
                        Description=f'Security group for {account_name} root user instance',
                        VpcId=vpc_id
                    )
                    sg_id = sg_response['GroupId']
                    
                    ec2_client.authorize_security_group_ingress(
                        GroupId=sg_id,
                        IpPermissions=[{
                            'IpProtocol': '-1',
                            'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow all traffic'}]
                        }]
                    )
                    self.log_operation('INFO', f"Created new security group with updated name: {sg_id}")
                else:
                    raise
            
            # Prepare user data with AWS configuration
            enhanced_userdata = self.user_data_script.replace('${AWS_ACCESS_KEY_ID}', access_key)
            enhanced_userdata = enhanced_userdata.replace('${AWS_SECRET_ACCESS_KEY}', secret_key)
            enhanced_userdata = enhanced_userdata.replace('${AWS_DEFAULT_REGION}', region)
            
            # Create instance
            instance_name = f"{account_name}-root-instance-{random_suffix}"
            
            response = ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=self.ami_config.get('default_instance_type', 't3.micro'),
                SecurityGroupIds=[sg_id],
                SubnetId=subnet_id,
                UserData=enhanced_userdata,
                TagSpecifications=[{
                    'ResourceType': 'instance',
                    'Tags': [
                        {'Key': 'Name', 'Value': instance_name},
                        {'Key': 'Account', 'Value': account_name},
                        {'Key': 'Owner', 'Value': username},
                        {'Key': 'Purpose', 'Value': 'Root-User-Instance'},
                        {'Key': 'CreatedBy', 'Value': self.current_user},
                        {'Key': 'CreatedAt', 'Value': self.current_time},
                        {'Key': 'Region', 'Value': region},
                        {'Key': 'RandomSuffix', 'Value': random_suffix},
                        {'Key': 'AccountID', 'Value': account_data.get('account_id', 'Unknown')}
                    ]
                }]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            instance_type = response['Instances'][0]['InstanceType']
            
            self.print_colored(Colors.GREEN, f"[SUCCESS] EC2 instance created: {instance_id}")
            self.log_operation('INFO', f"EC2 instance created successfully: {instance_id} in {region}")
            
            return {
                'status': 'created',
                'instance_id': instance_id,
                'instance_name': instance_name,
                'instance_type': instance_type,
                'region': region,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'ami_id': ami_id,
                'random_suffix': random_suffix,
                'created_at': self.current_time
            }
            
        except Exception as e:
            error_msg = str(e)
            self.print_colored(Colors.RED, f"[ERROR] Failed to create EC2 instance: {error_msg}")
            self.log_operation('ERROR', f"EC2 instance creation failed: {error_msg}")
            return {'status': 'failed', 'error': error_msg}

    def create_eks_cluster(self, account_name, account_data, root_user, region):
        """Create EKS cluster for root user"""
        try:
            self.print_colored(Colors.YELLOW, f"[PROCESSING] Creating EKS cluster for account: {account_name} in {region}")
            
            # Extract credentials
            access_key = root_user.get('access_key_id', '')
            secret_key = root_user.get('secret_access_key', '')
            
            if not access_key or not secret_key:
                raise ValueError("Missing AWS root user credentials")
            
            # Create EKS client
            eks_client = boto3.client(
                'eks',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test connection
            try:
                eks_client.list_clusters()
                self.log_operation('INFO', f"Successfully connected to EKS in {region}")
            except Exception as e:
                raise ValueError(f"Failed to connect to EKS in {region}: {str(e)}")
            
            random_suffix = self.generate_random_suffix()
            cluster_name = f"{account_name}-root-cluster-{random_suffix}"
            
            # Note: Full EKS cluster creation requires:
            # 1. IAM service role for EKS
            # 2. VPC and subnets configuration
            # 3. Security groups
            # 4. Node groups (for worker nodes)
            
            self.print_colored(Colors.YELLOW, f"[INFO] EKS cluster name planned: {cluster_name}")
            self.print_colored(Colors.YELLOW, f"[INFO] EKS creation requires additional IAM roles and VPC setup")
            self.print_colored(Colors.YELLOW, f"[INFO] This is a simplified implementation - extend as needed")
            
            # For demonstration, we'll create a placeholder response
            # In a full implementation, you would:
            # 1. Create/verify IAM service role
            # 2. Create EKS cluster
            # 3. Create node group
            # 4. Configure kubectl access
            
            self.log_operation('INFO', f"EKS cluster planned: {cluster_name} in {region}")
            
            return {
                'status': 'planned',
                'cluster_name': cluster_name,
                'region': region,
                'kubernetes_version': self.eks_config.get('default_kubernetes_version', '1.28'),
                'node_instance_type': self.eks_config.get('default_node_instance_type', 't3.medium'),
                'node_count': self.eks_config.get('default_node_count', 2),
                'random_suffix': random_suffix,
                'created_at': self.current_time,
                'note': 'EKS cluster planned - requires IAM roles and VPC configuration for full implementation'
            }
            
        except Exception as e:
            error_msg = str(e)
            self.print_colored(Colors.RED, f"[ERROR] Failed to create EKS cluster: {error_msg}")
            self.log_operation('ERROR', f"EKS cluster creation failed: {error_msg}")
            return {'status': 'failed', 'error': error_msg}

    def generate_random_suffix(self, length=4):
        """Generate random alphanumeric suffix"""
        characters = string.ascii_lowercase + string.digits
        return ''.join(random.choice(characters) for _ in range(length))

    def save_results(self, results):
        """Save creation results to JSON file"""
        try:
            results_filename = f"aws_resource_creation_results_{self.execution_timestamp}.json"
            
            results_data = {
                "metadata": {
                    "creation_date": self.current_time.split()[0],
                    "creation_time": self.current_time.split()[1],
                    "created_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "default_region": self.default_region,
                    "total_accounts_available": len(self.credentials_data.get('accounts', {})),
                    "total_accounts_processed": len(results),
                    "credentials_source": self.credentials_file,
                    "ami_mapping_file": self.ami_mapping_file,
                    "userdata_file": self.userdata_file,
                    "eks_config_file": self.eks_config_file
                },
                "results": results
            }
            
            with open(results_filename, 'w', encoding='utf-8') as f:
                json.dump(results_data, f, indent=2, default=str)
            
            self.print_colored(Colors.GREEN, f"[SUCCESS] Results saved to: {results_filename}")
            return results_filename
            
        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to save results: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            # Get actual account count for display
            actual_account_count = len(self.credentials_data.get('accounts', {}))
            
            self.print_colored(Colors.BOLD, "AWS Account Resource Manager for Root Users")
            print("=" * 90)
            print(f"[INFO] Execution Date/Time: {self.current_time} UTC")
            print(f"[INFO] Executed by: {self.current_user}")
            print(f"[INFO] Default Region: {self.default_region}")
            print(f"[INFO] Accounts Available: {actual_account_count}")
            print(f"[INFO] Credentials Source: {self.credentials_file}")
            print(f"[INFO] Log File: {self.log_filename}")
            print("=" * 90)
            
            # Step 1: Select accounts
            selected_account_indices = self.display_accounts_menu()
            if not selected_account_indices:
                self.print_colored(Colors.YELLOW, "[INFO] Operation cancelled")
                return
            
            # Step 2: Select resource type with separate options
            resource_type = self.display_resource_menu()
            if resource_type == 'cancel':
                self.print_colored(Colors.YELLOW, "[INFO] Operation cancelled")
                return
            
            # Step 3: Process selected accounts
            accounts = list(self.credentials_data['accounts'].items())
            results = []
            
            selected_count = len(selected_account_indices)
            self.print_colored(Colors.CYAN, f"\n[INFO] Processing {selected_count} out of {actual_account_count} accounts with option: {resource_type}")
            
            for i, idx in enumerate(selected_account_indices, 1):
                account_name, account_data = accounts[idx - 1]
                region = self.get_account_region(account_data)
                
                self.print_colored(Colors.YELLOW, f"\n[PROCESSING] Account {i}/{selected_count}: {account_name} ({region})")
                
                # Get root user
                root_user = self.get_root_user_from_account(account_data)
                if not root_user:
                    self.print_colored(Colors.RED, f"[ERROR] No root user credentials found for account: {account_name}")
                    results.append({
                        'account_name': account_name,
                        'account_id': account_data.get('account_id', 'Unknown'),
                        'region': region,
                        'status': 'failed',
                        'error': 'No root user credentials found'
                    })
                    continue
                
                account_result = {
                    'account_name': account_name,
                    'account_id': account_data.get('account_id', 'Unknown'),
                    'region': region,
                    'root_user': root_user.get('username', 'root'),
                    'access_key_preview': root_user.get('access_key_id', '')[:10] + '...' if root_user.get('access_key_id') else 'N/A',
                    'resources_created': {},
                    'execution_order': resource_type
                }
                
                # Execute based on selected option
                if resource_type == 'ec2_only':
                    ec2_result = self.create_ec2_instance(account_name, account_data, root_user, region)
                    account_result['resources_created']['ec2'] = ec2_result
                    
                elif resource_type == 'eks_only':
                    eks_result = self.create_eks_cluster(account_name, account_data, root_user, region)
                    account_result['resources_created']['eks'] = eks_result
                    
                elif resource_type == 'ec2_then_eks':
                    # Create EC2 first, then EKS
                    ec2_result = self.create_ec2_instance(account_name, account_data, root_user, region)
                    account_result['resources_created']['ec2'] = ec2_result
                    
                    if ec2_result.get('status') == 'created':
                        self.print_colored(Colors.YELLOW, f"[INFO] EC2 created successfully, now creating EKS...")
                        time.sleep(3)  # Brief pause
                        eks_result = self.create_eks_cluster(account_name, account_data, root_user, region)
                        account_result['resources_created']['eks'] = eks_result
                    else:
                        self.print_colored(Colors.RED, f"[WARNING] Skipping EKS creation due to EC2 failure")
                        
                elif resource_type == 'eks_then_ec2':
                    # Create EKS first, then EC2
                    eks_result = self.create_eks_cluster(account_name, account_data, root_user, region)
                    account_result['resources_created']['eks'] = eks_result
                    
                    if eks_result.get('status') in ['created', 'planned']:
                        self.print_colored(Colors.YELLOW, f"[INFO] EKS planned successfully, now creating EC2...")
                        time.sleep(3)  # Brief pause
                        ec2_result = self.create_ec2_instance(account_name, account_data, root_user, region)
                        account_result['resources_created']['ec2'] = ec2_result
                    else:
                        self.print_colored(Colors.RED, f"[WARNING] Skipping EC2 creation due to EKS failure")
                        
                elif resource_type == 'both_simultaneous':
                    # Create both simultaneously (in practice, one after the other quickly)
                    ec2_result = self.create_ec2_instance(account_name, account_data, root_user, region)
                    account_result['resources_created']['ec2'] = ec2_result
                    
                    time.sleep(2)  # Brief pause
                    
                    eks_result = self.create_eks_cluster(account_name, account_data, root_user, region)
                    account_result['resources_created']['eks'] = eks_result
                
                results.append(account_result)
                
                # Brief pause between accounts
                if i < selected_count:
                    time.sleep(5)
            
            # Step 4: Display summary and save results
            self.display_summary(results, resource_type, actual_account_count)
            self.save_results(results)
            
            self.print_colored(Colors.GREEN, f"\n[SUCCESS] Resource creation completed!")
            self.log_operation('INFO', "Resource creation session completed successfully")
            
        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Fatal error: {str(e)}")
            self.log_operation('ERROR', f"Fatal error in main execution: {str(e)}")
            raise

    def display_summary(self, results, resource_type, total_available_accounts):
        """Display creation summary"""
        self.print_colored(Colors.CYAN, f"\n[INFO] Creation Summary - {resource_type}")
        print("=" * 80)
        
        total_processed = len(results)
        successful_ec2 = 0
        successful_eks = 0
        failed_accounts = 0
        
        for result in results:
            account_name = result['account_name']
            region = result['region']
            resources = result.get('resources_created', {})
            
            print(f"\n[ACCOUNT] {account_name} ({region})")
            
            # Display EC2 results
            if 'ec2' in resources:
                ec2_status = resources['ec2'].get('status', 'unknown')
                if ec2_status == 'created':
                    successful_ec2 += 1
                    instance_id = resources['ec2'].get('instance_id', 'N/A')
                    instance_type = resources['ec2'].get('instance_type', 'N/A')
                    print(f"  [EC2] [SUCCESS] Instance: {instance_id} ({instance_type})")
                else:
                    print(f"  [EC2] [FAILED] {resources['ec2'].get('error', 'Unknown error')}")
            
            # Display EKS results
            if 'eks' in resources:
                eks_status = resources['eks'].get('status', 'unknown')
                if eks_status in ['created', 'planned']:
                    successful_eks += 1
                    cluster_name = resources['eks'].get('cluster_name', 'N/A')
                    k8s_version = resources['eks'].get('kubernetes_version', 'N/A')
                    status_text = "PLANNED" if eks_status == 'planned' else "CREATED"
                    print(f"  [EKS] [SUCCESS/{status_text}] Cluster: {cluster_name} (K8s: {k8s_version})")
                else:
                    print(f"  [EKS] [FAILED] {resources['eks'].get('error', 'Unknown error')}")
            
            # Count failed accounts
            if (('ec2' in resources and resources['ec2'].get('status') == 'failed') or
                ('eks' in resources and resources['eks'].get('status') == 'failed') or
                result.get('status') == 'failed'):
                failed_accounts += 1
        
        print("=" * 80)
        print(f"[SUMMARY] Total accounts available: {total_available_accounts}")
        print(f"[SUMMARY] Total accounts processed: {total_processed}")
        print(f"[SUMMARY] Execution method: {resource_type}")
        
        if 'ec2' in resource_type or resource_type in ['both_simultaneous']:
            print(f"[SUMMARY] Successful EC2 instances: {successful_ec2}")
        if 'eks' in resource_type or resource_type in ['both_simultaneous']:
            print(f"[SUMMARY] Successful EKS clusters: {successful_eks}")
        
        print(f"[SUMMARY] Failed accounts: {failed_accounts}")
        
        if total_processed > 0:
            success_rate = ((successful_ec2 + successful_eks) / (total_processed * 2)) * 100 if resource_type in ['both_simultaneous', 'ec2_then_eks', 'eks_then_ec2'] else ((successful_ec2 + successful_eks) / total_processed) * 100
            print(f"[SUMMARY] Overall success rate: {success_rate:.1f}%")

def main():
    """Main function"""
    try:
        manager = AWSAccountResourceManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[INFO] Operation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()