#!/usr/bin/env python3
"""
EC2 to EKS Cluster Connection Automation System with Smart Username Mapping
Automates the process of connecting EC2 instances to EKS clusters
"""

import json
import os
import sys
import paramiko
import boto3
import logging
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Configure logging
# Ensure log directory exists first
log_dir = "aws/ssh-reports"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'eks_connector.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class EKSConnector:
    def __init__(self):
        self.config_file = "aws_accounts_config.json"
        self.asg_base_path = "aws/asg"
        self.ec2_base_path = "aws/ec2"
        self.reports_path = "aws/ssh-reports"
        self.ssh_username = "demouser"
        self.ssh_password = "demouser@123"
        self.accounts_config = {}
        self.selected_accounts = []
        self.selected_asg_files = []
        self.selected_ec2_files = []
        self.selected_asgs = []
        self.selected_ec2_instances = []
        self.user_instruction_files = {}
        self.direct_mode = False
        self.direct_instances = []
        self.direct_account = None
        self.instance_source = None

        # Smart mapping storage
        self.asg_username_mapping = {}  # {asg_name: extracted_username}
        self.ec2_username_mapping = {}  # {instance_id: extracted_username}
        self.instruction_username_mapping = {}  # {file_path: extracted_username}
        self.final_mapping = {}  # Final mapping for processing

        # UPDATED: Current timestamp
        self.current_time = "2025-06-26 16:53:37"
        self.current_user = "varadharajaan"

        # Ensure reports directory exists
        Path(self.reports_path).mkdir(parents=True, exist_ok=True)

    def load_accounts_config(self):
        """Load AWS accounts configuration"""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                self.accounts_config = config.get('accounts', {})
                logger.info(f"Loaded {len(self.accounts_config)} accounts from config")
                return True
        except FileNotFoundError:
            logger.error(f"Configuration file {self.config_file} not found")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            return False

    def parse_command_line_args(self):
        """Parse command line arguments for direct instance processing"""
        parser = argparse.ArgumentParser(
            description='EC2 to EKS Cluster Connection Automation',
            epilog='''
Examples:
  python eks_connector.py                          # Interactive mode (multi-account support)
  python eks_connector.py i-123456789 account01   # Single instance, single account
  python eks_connector.py i-123,i-456 account01   # Multiple instances, single account
            ''',
            formatter_class=argparse.RawDescriptionHelpFormatter
        )

        parser.add_argument('instances', nargs='?', help='Comma-separated instance IDs (e.g., i-123,i-456)')
        parser.add_argument('account', nargs='?', help='Account name to process (single account only in direct mode)')

        args = parser.parse_args()

        # Check if direct mode arguments are provided
        if args.instances and args.account:
            self.direct_mode = True
            self.direct_instances = [inst.strip() for inst in args.instances.split(',')]
            self.direct_account = args.account
            self.selected_accounts = [args.account]

            # Validate account exists
            if not self.load_accounts_config():
                return False

            if args.account not in self.accounts_config:
                print(f"Error: Account '{args.account}' not found in configuration")
                print(f"Available accounts: {', '.join(self.accounts_config.keys())}")
                return False

            print(f"Direct mode: Processing instances {', '.join(self.direct_instances)} in account {args.account}")
            print("Note: Direct mode supports single account only. Use interactive mode for multi-account processing.")
            return True
        elif args.instances or args.account:
            print("Error: Both instance IDs and account name are required for direct mode")
            print("Usage: python eks_connector.py <instance_ids> <account_name>")
            print("Example: python eks_connector.py i-123456789,i-987654321 account01")
            print("\nFor multi-account processing, use interactive mode (no arguments)")
            return False
        else:
            # Interactive mode - supports multi-account
            print("Interactive mode: Multi-account processing supported")
            return True

    def extract_username_from_cluster_name(cluster_name):
        """
        Extracts username from EKS cluster name based on common patterns.

        Args:
            cluster_name (str): EKS cluster name like 'eks-cluster-account01_clouduser05-ap-south-1-tnkg'

        Returns:
            str: Extracted username or None if pattern doesn't match
        """
        try:
            # Pattern 1: eks-cluster-account01_clouduser05-ap-south-1-tnkg
            if '_' in cluster_name:
                # Split by '-' to get segments
                segments = cluster_name.split('-')
                # Find the segment containing the username (with '_')
                for segment in segments:
                    if '_' in segment:
                        return segment

            # Pattern 2: eks-cluster-root-account01-ap-south-1-tnkg
            else:
                # Match pattern for root user
                parts = cluster_name.split('-')
                if len(parts) >= 4 and parts[2] == 'root':
                    return f"root-{parts[3]}"

            return None
        except Exception as e:
            print(f"Error extracting username: {str(e)}")
            return None

    def extract_username_from_cluster(self, cluster_name):
        """
        Extract username from cluster name:
        - For root: eks-cluster-root-account01-... -> root-account01
        - For IAM: {username}_eks-cluster-{username}-... -> {username}
        """
        try:
            if not cluster_name:
                return 'unknown-user'
            if cluster_name.startswith('eks-cluster-root-'):
                # root user: username is 'root-accountXX'
                parts = cluster_name.split('-')
                if len(parts) >= 4:
                    return f"root-{parts[3]}"
                return 'root-user'
            if '_eks-cluster-' in cluster_name:
                # IAM user: username is before '_eks-cluster-'
                return cluster_name.split('_eks-cluster-')[0]
            if 'eks-cluster-' in cluster_name:
                # Fallback for other patterns
                parts = cluster_name.split('-')
                if len(parts) >= 3:
                    return parts[2]
            return 'unknown-user'
        except Exception:
            return 'unknown-user'


    def extract_username_from_instruction_filename(self, filename):
        """Extract username from instruction filename: user_mini_instructions_{account}_{username}_{cluster}_{timestamp}.txt"""
        try:
            # Pattern: user_mini_instructions_{account}_{username}_{cluster}_{timestamp}.txt
            # We want to extract account_username as the combined username
            match = re.search(r'user_mini_instructions_([^_]+)_([^_]+)_.*?_\d{8}_\d{6}\.txt$', filename)
            if match:
                account = match.group(1)  # account03
                username = match.group(2)  # clouduser05
                combined_username = f"{account}_{username}"  # account03_clouduser05
                return combined_username
            return 'unknown-user'
        except Exception:
            return 'unknown-user'

    def get_instance_details_direct(self, instance_ids, account):
        """Get instance details directly from AWS API"""
        try:
            account_config = self.accounts_config[account]

            # Try to get region from user instructions files first
            region = 'us-east-1'  # default
            instruction_files = self.discover_user_instruction_files()
            if account in instruction_files and instruction_files[account]:
                # Try to extract region from instruction file content
                try:
                    with open(instruction_files[account][0]['path'], 'r') as f:
                        content = f.read()
                        region_match = re.search(r'--region\s+([a-z0-9-]+)', content)
                        if region_match:
                            region = region_match.group(1)
                except:
                    pass

            # Configure AWS client
            session = boto3.Session(
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name=region
            )

            ec2 = session.client('ec2')

            # Get instance details
            try:
                instances_response = ec2.describe_instances(InstanceIds=instance_ids)
            except Exception as e:
                if "InvalidInstanceID.NotFound" in str(e):
                    logger.error(f"One or more instances not found in region {region}")
                    # Try other common regions
                    common_regions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1', 'eu-central-1', 'eu-west-1']
                    for try_region in common_regions:
                        if try_region != region:
                            try:
                                logger.info(f"Trying region {try_region}")
                                session = boto3.Session(
                                    aws_access_key_id=account_config['access_key'],
                                    aws_secret_access_key=account_config['secret_key'],
                                    region_name=try_region
                                )
                                ec2 = session.client('ec2')
                                instances_response = ec2.describe_instances(InstanceIds=instance_ids)
                                region = try_region
                                logger.info(f"Found instances in region {region}")
                                break
                            except:
                                continue
                    else:
                        raise e
                else:
                    raise e

            instances = []

            for reservation in instances_response['Reservations']:
                for instance in reservation['Instances']:
                    instances.append({
                        'instance_id': instance['InstanceId'],
                        'public_ip': instance.get('PublicIpAddress'),
                        'private_ip': instance.get('PrivateIpAddress'),
                        'state': instance['State']['Name'],
                        'account': account,
                        'region': region
                    })

            # Filter only running instances
            running_instances = [inst for inst in instances if inst['state'] == 'running']

            if len(running_instances) < len(instance_ids):
                not_running = [inst for inst in instances if inst['state'] != 'running']
                for inst in not_running:
                    logger.warning(f"Instance {inst['instance_id']} is in state '{inst['state']}', skipping")

            return running_instances

        except Exception as e:
            logger.error(f"Error getting instance details: {e}")
            return []

    def extract_username_from_cluster_name_in_instruction(self, cluster_name):
        """
        Extract username from cluster name in instruction file:
        - For root: eks-cluster-root-account01-...
          -> username: root-account01
        - For IAM: eks-cluster-account01_clouduser01-...
          -> username: account01_clouduser01
        """
        try:
            if not cluster_name:
                return 'unknown-user'
            if cluster_name.startswith('eks-cluster-root-'):
                # root user: username is 'root-accountXX'
                parts = cluster_name.split('-')
                if len(parts) >= 4:
                    return f"root-{parts[3]}"
                return 'root-user'
            elif '_eks-cluster-' in cluster_name:
                # IAM user: username is before '-'
                parts = cluster_name.split('_eks-cluster-')
                if len(parts) >= 2:
                    after_cluster = parts[1]
                    username = after_cluster.split('-')[0]
                    return username
            return 'unknown-user'
        except Exception:
            return 'unknown-user'

    def discover_user_instruction_files(self):
        """Discover and group user instruction files by account"""
        print("\n=== Discovering User Mini-Instruction Files ===")

        # Look for user_mini_instructions_*.txt files
        all_instruction_files = list(Path('.').glob('user_mini_instructions_*.txt'))
        print(f"Found {len(all_instruction_files)} user mini-instruction files in current directory:")

        for file_path in all_instruction_files:
            print(f"  - {file_path.name}")

        if not all_instruction_files:
            print("No user mini-instruction files found in current directory.")
            print("Expected pattern: user_mini_instructions_{account}_{username}_{cluster}_TIMESTAMP.txt")
            return {}

        # Parse files and group by account
        instruction_files = defaultdict(list)

        print(f"\nParsing user mini-instruction files:")

        for file_path in all_instruction_files:
            # Extract account from the beginning of filename after prefix
            filename = file_path.name
            if filename.startswith('user_mini_instructions_'):
                # Remove prefix
                remaining = filename[len('user_mini_instructions_'):]
                # Split by underscore and take first part as account
                parts = remaining.split('_')
                if len(parts) >= 2:
                    account_name = parts[0]  # First part is account
                    username = parts[1]  # Second part is username

                    # Extract timestamp from end of filename
                    timestamp_match = re.search(r'(\d{8}_\d{6})\.txt$', filename)
                    timestamp = timestamp_match.group(1) if timestamp_match else 'unknown'

                    # Extract cluster name from filename
                    cluster_match = re.search(
                        f'user_mini_instructions_{account_name}_{username}_(.+)_{timestamp}\\.txt$', filename)
                    cluster_name = cluster_match.group(1) if cluster_match else 'unknown'

                    # NEW: Extract username from cluster name (the proper way)
                    extracted_username = self.extract_username_from_cluster_name_in_instruction(cluster_name)
                    if 'root-account' in cluster_name:
                        extracted_username = username

                    print(f"  ✓ Parsed: {file_path.name}")
                    print(
                        f"    -> Account: {account_name}, User: {username}, Cluster: {cluster_name}, Time: {timestamp}")
                    print(f"    -> Extracted Username from Cluster: {extracted_username}")

                    file_info = {
                        'path': file_path,
                        'account_name': account_name,
                        'username': username,
                        'cluster_name': cluster_name,
                        'timestamp': timestamp,
                        'extracted_username': extracted_username  # This is now account03_clouduser05
                    }

                    instruction_files[account_name].append(file_info)

                    # Store in mapping for smart matching
                    self.instruction_username_mapping[str(file_path)] = extracted_username

                else:
                    print(f"  ✗ Could not parse: {file_path.name} (insufficient parts)")
            else:
                print(f"  ✗ Could not parse: {file_path.name} (doesn't match expected pattern)")

        print(f"\nGrouped user mini-instruction files by account:")
        for account, files in instruction_files.items():
            print(f"  [FOLDER] {account}: {len(files)} files")
            for file_info in files:
                print(
                    f"    - {file_info['username']} @ {file_info['cluster_name']} -> {file_info['extracted_username']}")

        return dict(instruction_files)

    def extract_username_from_asg_filename(self, filename):
        """Extract username from ASG filename: asg_{asg_name}_{username}_{timestamp}.json"""
        try:
            # Pattern: asg_{asg_name}_{username}_{timestamp}.json
            match = re.search(r'asg_.*?_([^_]+)_\d{8}_\d{6}\.json$', filename)
            if match:
                base_username = match.group(1)  # This gives us clouduser05

                # Now we need to get the account name from the ASG info to create account_username
                # We'll do this in the build_smart_mapping method where we have access to account info
                return base_username
            return 'unknown-user'
        except Exception:
            return 'unknown-user'


    def build_smart_mapping(self):
        """Build smart mapping between ASG/EC2 instances and instruction files based on usernames"""
        print("\n" + "=" * 80)
        print("🤖 SMART USERNAME MAPPING ANALYSIS")
        print("=" * 80)

        # Get all instruction files grouped by account
        all_instruction_files = self.discover_user_instruction_files()

        if self.instance_source == 'asg':
            print(f"\n[STATS] ASG Username Analysis:")
            print(f"{'ASG Name':<30} {'Account':<15} {'Extracted Username':<20} {'Full Username':<25}")
            print("-" * 100)

            for asg_info in self.selected_asgs:
                filename = asg_info['file_path'].name
                base_username = self.extract_username_from_asg_filename(filename)
                # Create full username: account_username
                full_username = f"{asg_info['account']}_{base_username}"
                if 'root-account' in base_username:
                    full_username = base_username

                self.asg_username_mapping[asg_info['name']] = full_username
                print(f"{asg_info['name']:<30} {asg_info['account']:<15} {base_username:<20} {full_username:<25}")

        else:  # ec2
            print(f"\n[STATS] EC2 Instance Username Analysis:")
            print(f"{'Instance ID':<20} {'Account':<15} {'Extracted Username':<20} {'Full Username':<25}")
            print("-" * 90)

            for instance_info in self.selected_ec2_instances:
                filename = instance_info['file_path'].name
                base_username = self.extract_username_from_ec2_filename(filename)
                # Create full username: account_username (same logic as ASG)
                full_username = f"{instance_info['account']}_{base_username}"
                if 'root-account' in base_username:
                    full_username = base_username
                self.ec2_username_mapping[instance_info['instance_id']] = full_username
                print(
                    f"{instance_info['instance_id']:<20} {instance_info['account']:<15} {base_username:<20} {full_username:<25}")

        print(f"\n[LIST] Available Instruction Files by Username:")
        print(f"{'Account':<15} {'Username':<25} {'Cluster Name':<40}")
        print("-" * 90)

        available_instructions = {}
        for account, files in all_instruction_files.items():
            available_instructions[account] = {}
            for file_info in files:
                username = file_info['extracted_username']  # This is account03_clouduser05 from cluster name
                available_instructions[account][username] = file_info
                print(f"{account:<15} {username:<25} {file_info['cluster_name']:<40}")

        # Attempt automatic mapping
        print(f"\n🔄 Attempting Automatic Mapping...")
        auto_mapping = {}
        unmapped_items = []

        if self.instance_source == 'asg':
            for asg_name, full_username in self.asg_username_mapping.items():
                # Find ASG account
                asg_account = None
                for asg_info in self.selected_asgs:
                    if asg_info['name'] == asg_name:
                        asg_account = asg_info['account']
                        break

                if asg_account and asg_account in available_instructions:
                    if full_username in available_instructions[asg_account]:
                        auto_mapping[asg_name] = available_instructions[asg_account][full_username]
                        print(f"  ✓ {asg_name} -> {full_username} (auto-matched)")
                    else:
                        unmapped_items.append((asg_name, full_username, asg_account))
                        print(f"  ✗ {asg_name} -> {full_username} (no matching instruction file)")
                else:
                    unmapped_items.append((asg_name, full_username, asg_account))
                    print(f"  ✗ {asg_name} -> {full_username} (account not found)")

        else:  # ec2 - FIXED: Same logic as ASG now
            for instance_id, full_username in self.ec2_username_mapping.items():
                # Find instance account
                instance_account = None
                for instance_info in self.selected_ec2_instances:
                    if instance_info['instance_id'] == instance_id:
                        instance_account = instance_info['account']
                        break

                if instance_account and instance_account in available_instructions:
                    if full_username in available_instructions[instance_account]:
                        auto_mapping[instance_id] = available_instructions[instance_account][full_username]
                        print(f"  ✓ {instance_id} -> {full_username} (auto-matched)")
                    else:
                        unmapped_items.append((instance_id, full_username, instance_account))
                        print(f"  ✗ {instance_id} -> {full_username} (no matching instruction file)")
                else:
                    unmapped_items.append((instance_id, full_username, instance_account))
                    print(f"  ✗ {instance_id} -> {full_username} (account not found)")

        print(f"\n📈 Mapping Results:")
        print(f"  [OK] Auto-mapped: {len(auto_mapping)}")
        print(f"  [ERROR] Unmapped: {len(unmapped_items)}")

        # Ask user to approve automatic mapping
        if auto_mapping:
            print(f"\n🤔 Do you want to use the automatic mapping above?")
            choice = input("Enter 'yes' or 'y' to accept, 'no' to manually map: ").strip().lower()

            if choice == 'y'or choice == 'yes':
                self.final_mapping = auto_mapping
                print(f"[OK] Using automatic mapping for {len(auto_mapping)} items")

                # Handle unmapped items
                if unmapped_items:
                    print(f"\n[WARN]  Manual mapping required for {len(unmapped_items)} unmapped items:")
                    self.handle_manual_mapping(unmapped_items, available_instructions)

                return True
            else:
                print(f"[CONFIG] Proceeding with manual mapping...")
                return self.handle_full_manual_mapping(available_instructions)
        else:
            print(f"\n[CONFIG] No automatic mapping possible. Proceeding with manual mapping...")
            return self.handle_full_manual_mapping(available_instructions)

    def handle_manual_mapping(self, unmapped_items, available_instructions):
        """Handle manual mapping for unmapped items"""
        print(f"\n[CONFIG] Manual Mapping for Unmapped Items")
        print("=" * 50)

        for item_name, username, account in unmapped_items:
            print(f"\n[PIN] Mapping for: {item_name} (extracted username: {username}, account: {account})")

            if account in available_instructions:
                files = list(available_instructions[account].values())
                print(f"\nAvailable instruction files for account {account}:")
                for i, file_info in enumerate(files, 1):
                    print(f"  {i}. {file_info['extracted_username']} -> {file_info['cluster_name']}")

                while True:
                    try:
                        selection = input(
                            f"Select instruction file for {item_name} (1-{len(files)}, or 's' to skip): ").strip()

                        if selection.lower() == 's':
                            print(f"  [SKIP]  Skipped {item_name}")
                            break

                        idx = int(selection) - 1
                        if 0 <= idx < len(files):
                            self.final_mapping[item_name] = files[idx]
                            print(f"  [OK] Mapped {item_name} -> {files[idx]['extracted_username']}")
                            break
                        else:
                            print(f"Invalid selection. Please choose 1-{len(files)} or 's' to skip.")
                    except ValueError:
                        print(f"Invalid input. Please enter a number 1-{len(files)} or 's' to skip.")
            else:
                print(f"  [ERROR] No instruction files available for account {account}")

    def handle_full_manual_mapping(self, available_instructions):
        """Handle full manual mapping when automatic mapping is rejected"""
        print(f"\n[CONFIG] Full Manual Mapping")
        print("=" * 50)

        items_to_map = []

        if self.instance_source == 'asg':
            for asg_info in self.selected_asgs:
                asg_name = asg_info['name']
                username = self.asg_username_mapping.get(asg_name, 'unknown')
                items_to_map.append((asg_name, username, asg_info['account']))
        else:  # ec2
            for instance_info in self.selected_ec2_instances:
                instance_id = instance_info['instance_id']
                username = self.ec2_username_mapping.get(instance_id, 'unknown')
                items_to_map.append((instance_id, username, instance_info['account']))

        for item_name, username, account in items_to_map:
            print(f"\n[PIN] Mapping for: {item_name} (extracted username: {username}, account: {account})")

            if account in available_instructions:
                files = list(available_instructions[account].values())
                print(f"\nAvailable instruction files for account {account}:")
                for i, file_info in enumerate(files, 1):
                    print(f"  {i}. {file_info['extracted_username']} -> {file_info['cluster_name']}")

                while True:
                    try:
                        selection = input(
                            f"Select instruction file for {item_name} (1-{len(files)}, or 's' to skip): ").strip()

                        if selection.lower() == 's':
                            print(f"  [SKIP]  Skipped {item_name}")
                            break

                        idx = int(selection) - 1
                        if 0 <= idx < len(files):
                            self.final_mapping[item_name] = files[idx]
                            print(f"  [OK] Mapped {item_name} -> {files[idx]['extracted_username']}")
                            break
                        else:
                            print(f"Invalid selection. Please choose 1-{len(files)} or 's' to skip.")
                    except ValueError:
                        print(f"Invalid input. Please enter a number 1-{len(files)} or 's' to skip.")
            else:
                print(f"  [ERROR] No instruction files available for account {account}")

        print(f"\n[OK] Manual mapping completed. {len(self.final_mapping)} items mapped.")
        return len(self.final_mapping) > 0

    def display_accounts(self):
        """Display available accounts with enhanced multi-account messaging"""
        print("\n=== Available AWS Accounts ===")
        print("You can select multiple accounts using:")
        print("  - Single: 1")
        print("  - Comma-separated: 1,3,4")
        print("  - Range: 1-3")
        print("  - All: all or", len(self.accounts_config) + 1)
        print()

        for i, (account_name, account_info) in enumerate(self.accounts_config.items(), 1):
            print(f"{i}. {account_name} (ID: {account_info['account_id']})")
        print(f"{len(self.accounts_config) + 1}. All accounts")

    def select_accounts(self):
        """Interactive account selection"""
        self.display_accounts()

        while True:
            selection = input(f"\nSelect accounts (single/comma-separated/range/all): ").strip()

            if selection.lower() in ['all', str(len(self.accounts_config) + 1)]:
                self.selected_accounts = list(self.accounts_config.keys())
                print(f"Selected ALL {len(self.selected_accounts)} accounts")
                break

            try:
                # Parse selection
                account_names = []
                parts = selection.split(',')

                for part in parts:
                    part = part.strip()
                    if '-' in part and not part.startswith('-'):
                        # Range selection
                        start, end = map(int, part.split('-'))
                        account_list = list(self.accounts_config.keys())
                        for i in range(start - 1, min(end, len(account_list))):
                            if i >= 0:
                                account_names.append(account_list[i])
                    else:
                        # Single selection
                        if part.isdigit():
                            idx = int(part) - 1
                            account_list = list(self.accounts_config.keys())
                            if 0 <= idx < len(account_list):
                                account_names.append(account_list[idx])
                        else:
                            # Direct account name
                            if part in self.accounts_config:
                                account_names.append(part)

                if account_names:
                    self.selected_accounts = list(set(account_names))  # Remove duplicates
                    print(f"Selected {len(self.selected_accounts)} accounts")
                    break
                else:
                    print("Invalid selection. Please try again.")

            except (ValueError, IndexError):
                print("Invalid selection format. Please try again.")
                print("Examples: 1, 1,3, 1-3, all")

        print(f"\nSelected accounts: {', '.join(self.selected_accounts)}")

        # Show summary
        print(f"\nAccount Selection Summary:")
        for i, account in enumerate(self.selected_accounts, 1):
            account_id = self.accounts_config[account]['account_id']
            print(f"  {i}. {account} (ID: {account_id})")

    def select_instance_source(self):
        """Select between ASG or direct EC2 instances"""
        print("\n=== Instance Source Selection ===")
        print("Choose how to discover EC2 instances:")
        print("1. ASG (Auto Scaling Groups) - Get instances from ASG files")
        print("2. EC2 (Direct EC2 Instances) - Get instances from EC2 instance files")

        while True:
            choice = input("\nSelect instance source (1=ASG, 2=EC2): ").strip()

            if choice == '1':
                self.instance_source = 'asg'
                print("✓ Selected: ASG (Auto Scaling Groups)")
                break
            elif choice == '2':
                self.instance_source = 'ec2'
                print("✓ Selected: EC2 (Direct EC2 Instances)")
                break
            else:
                print("Invalid choice. Please enter 1 for ASG or 2 for EC2.")

        return True

    def discover_asg_files(self):
        """Discover ASG files grouped by day"""
        asg_files_by_day = defaultdict(list)

        print(f"\n=== Discovering ASG Files for {len(self.selected_accounts)} Accounts ===")

        for account in self.selected_accounts:
            asg_path = Path(self.asg_base_path) / account
            print(f"Checking ASG files for account: {account}")

            if asg_path.exists():
                files_found = 0
                for file_path in asg_path.glob("asg_asg-*.json"):
                    # Extract timestamp from filename properly
                    match = re.search(r'_(\d{8})_(\d{6})\.json$', file_path.name)
                    if match:
                        date_str = match.group(1)
                        time_str = match.group(2)
                        try:
                            # Parse date and time separately
                            date_obj = datetime.strptime(date_str, '%Y%m%d')
                            # Parse time and add to date
                            hour = int(time_str[:2])
                            minute = int(time_str[2:4])
                            second = int(time_str[4:6])
                            full_datetime = date_obj.replace(hour=hour, minute=minute, second=second)

                            day_key = date_obj.strftime('%Y-%m-%d')
                            asg_files_by_day[day_key].append({
                                'path': file_path,
                                'account': account,
                                'timestamp': full_datetime
                            })
                            files_found += 1
                        except ValueError as e:
                            logger.warning(f"Could not parse timestamp from {file_path.name}: {e}")
                            continue
                print(f"  Found {files_found} ASG files in {asg_path}")
            else:
                print(f"  ASG directory not found: {asg_path}")

        # Sort files within each day by timestamp
        for day in asg_files_by_day:
            asg_files_by_day[day].sort(key=lambda x: x['timestamp'])

        total_files = sum(len(files) for files in asg_files_by_day.values())
        print(f"\nTotal ASG files found: {total_files} files across {len(asg_files_by_day)} days")

        return dict(asg_files_by_day)

    def extract_username_from_ec2_filename(self, filename):
        """
        Extract username from EC2 filename:
        - ec2_instance_{instance_id}_{account}_{username}_{timestamp}.json
        - ec2_instance_{instance_id}_root-account01_{timestamp}.json
        """
        try:
            # Pattern 1: account + username
            match = re.match(r'ec2_instance_[^_]+_[^_]+_([^_]+)_\d{8}_\d{6}\.json$', filename)
            if match:
                return match.group(1)
            # Pattern 2: root-accountXX
            match_root = re.match(r'ec2_instance_[^_]+_(root-account\d+)_\d{8}_\d{6}\.json$', filename)
            if match_root:
                return match_root.group(1)
            return 'unknown-user'
        except Exception:
            return 'unknown-user'

    def discover_ec2_files(self):
        """Discover EC2 instance files grouped by day"""
        ec2_files_by_day = defaultdict(list)

        print(f"\n=== Discovering EC2 Instance Files for {len(self.selected_accounts)} Accounts ===")

        for account in self.selected_accounts:
            ec2_path = Path(self.ec2_base_path) / account
            print(f"Checking EC2 instance files for account: {account}")

            if ec2_path.exists():
                files_found = 0
                for file_path in ec2_path.glob("ec2_instance_*.json"):
                    # Match both: ec2_instance_{instance_id}_{account}_{username}_{timestamp}.json
                    # and ec2_instance_{instance_id}_root-account01_{timestamp}.json
                    match = re.match(
                        r'ec2_instance_([^_]+)_((?:root-account\d+|[^_]+))_(?:([^_]+)_)?(\d{8})_(\d{6})\.json$',
                        file_path.name
                    )
                    if match:
                        instance_id = match.group(1)
                        account_or_root = match.group(2)
                        username = match.group(3) if match.group(3) else account_or_root
                        date_str = match.group(4)
                        time_str = match.group(5)
                        try:
                            date_obj = datetime.strptime(date_str, '%Y%m%d')
                            hour = int(time_str[:2])
                            minute = int(time_str[2:4])
                            second = int(time_str[4:6])
                            full_datetime = date_obj.replace(hour=hour, minute=minute, second=second)

                            day_key = date_obj.strftime('%Y-%m-%d')
                            ec2_files_by_day[day_key].append({
                                'path': file_path,
                                'account': account,
                                'instance_id': instance_id,
                                'username': username,
                                'timestamp': full_datetime
                            })
                            files_found += 1
                            print(f"    ✓ Found: {file_path.name} -> Instance: {instance_id}, User: {username}")
                        except ValueError as e:
                            logger.warning(f"Could not parse timestamp from {file_path.name}: {e}")
                            continue
                    else:
                        print(f"    ✗ Skipped: {file_path.name} (doesn't match expected pattern)")
                print(f"  Found {files_found} EC2 instance files in {ec2_path}")
            else:
                print(f"  EC2 directory not found: {ec2_path}")

        # Sort files within each day by timestamp
        for day in ec2_files_by_day:
            ec2_files_by_day[day].sort(key=lambda x: x['timestamp'])

        total_files = sum(len(files) for files in ec2_files_by_day.values())
        print(f"\nTotal EC2 instance files found: {total_files} files across {len(ec2_files_by_day)} days")

        return dict(ec2_files_by_day)

    def display_asg_files_by_day(self, files_by_day):
        """Display ASG files grouped by day"""
        print("\n=== ASG Files by Day (Multi-Account) ===")
        sorted_days = sorted(files_by_day.keys(), reverse=True)  # CHANGED: Added reverse=True

        for i, day in enumerate(sorted_days, 1):
            # Group files by account for this day
            accounts_this_day = defaultdict(int)
            for file_info in files_by_day[day]:
                accounts_this_day[file_info['account']] += 1

            account_summary = ", ".join([f"{acc}({count})" for acc, count in accounts_this_day.items()])
            print(f"\n{i}. {day} ({len(files_by_day[day])} files) - Accounts: {account_summary}")

            for file_info in files_by_day[day]:
                timestamp_str = file_info['timestamp'].strftime('%H:%M:%S')
                print(f"   {timestamp_str} - {file_info['path'].name} ({file_info['account']})")

        print(f"\n{len(sorted_days) + 1}. All days")
        return sorted_days

    def display_ec2_files_by_day(self, files_by_day):
        """Display EC2 instance files grouped by day"""
        print("\n=== EC2 Instance Files by Day (Multi-Account) ===")
        sorted_days = sorted(files_by_day.keys(), reverse=True)  # CHANGED: Added reverse=True

        for i, day in enumerate(sorted_days, 1):
            # Group files by account for this day
            accounts_this_day = defaultdict(int)
            for file_info in files_by_day[day]:
                accounts_this_day[file_info['account']] += 1

            account_summary = ", ".join([f"{acc}({count})" for acc, count in accounts_this_day.items()])
            print(f"\n{i}. {day} ({len(files_by_day[day])} files) - Accounts: {account_summary}")

            for file_info in files_by_day[day]:
                timestamp_str = file_info['timestamp'].strftime('%H:%M:%S')
                print(
                    f"   {timestamp_str} - {file_info['instance_id']} - {file_info['path'].name} ({file_info['account']})")

        print(f"\n{len(sorted_days) + 1}. All days")
        return sorted_days

    def select_asg_files(self):
        """Select ASG files by day"""
        files_by_day = self.discover_asg_files()

        if not files_by_day:
            logger.error("No ASG files found for selected accounts")
            return False

        sorted_days = self.display_asg_files_by_day(files_by_day)

        while True:
            selection = input("\nSelect days (single/comma-separated/range/all): ").strip()

            if selection.lower() in ['all', str(len(sorted_days) + 1)]:
                selected_days = sorted_days
                break

            try:
                selected_days = []
                parts = selection.split(',')

                for part in parts:
                    part = part.strip()
                    if '-' in part and not part.startswith('-'):
                        start, end = map(int, part.split('-'))
                        for i in range(start - 1, min(end, len(sorted_days))):
                            if i >= 0:
                                selected_days.append(sorted_days[i])
                    else:
                        if part.isdigit():
                            idx = int(part) - 1
                            if 0 <= idx < len(sorted_days):
                                selected_days.append(sorted_days[idx])

                if selected_days:
                    break
                else:
                    print("Invalid selection. Please try again.")

            except (ValueError, IndexError):
                print("Invalid selection format. Please try again.")

        # Collect all files from selected days
        self.selected_asg_files = []
        for day in selected_days:
            self.selected_asg_files.extend(files_by_day[day])

        # Show summary by account
        account_file_count = defaultdict(int)
        for file_info in self.selected_asg_files:
            account_file_count[file_info['account']] += 1

        print(f"\nSelected {len(self.selected_asg_files)} ASG files from {len(selected_days)} days:")
        for account, count in account_file_count.items():
            print(f"  - {account}: {count} files")

        return True

    def select_ec2_files(self):
        """Select EC2 instance files by day"""
        files_by_day = self.discover_ec2_files()

        if not files_by_day:
            logger.error("No EC2 instance files found for selected accounts")
            return False

        sorted_days = self.display_ec2_files_by_day(files_by_day)

        while True:
            selection = input("\nSelect days (single/comma-separated/range/all): ").strip()

            if selection.lower() in ['all', str(len(sorted_days) + 1)]:
                selected_days = sorted_days
                break

            try:
                selected_days = []
                parts = selection.split(',')

                for part in parts:
                    part = part.strip()
                    if '-' in part and not part.startswith('-'):
                        start, end = map(int, part.split('-'))
                        for i in range(start - 1, min(end, len(sorted_days))):
                            if i >= 0:
                                selected_days.append(sorted_days[i])
                    else:
                        if part.isdigit():
                            idx = int(part) - 1
                            if 0 <= idx < len(sorted_days):
                                selected_days.append(sorted_days[idx])

                if selected_days:
                    break
                else:
                    print("Invalid selection. Please try again.")

            except (ValueError, IndexError):
                print("Invalid selection format. Please try again.")

        # Collect all files from selected days
        self.selected_ec2_files = []
        for day in selected_days:
            self.selected_ec2_files.extend(files_by_day[day])

        # Show summary by account
        account_file_count = defaultdict(int)
        for file_info in self.selected_ec2_files:
            account_file_count[file_info['account']] += 1

        print(f"\nSelected {len(self.selected_ec2_files)} EC2 instance files from {len(selected_days)} days:")
        for account, count in account_file_count.items():
            print(f"  - {account}: {count} files")

        return True

    def extract_asgs_from_files(self):
        """Extract ASG information from selected files"""
        asgs = []

        print(f"\n=== Extracting ASG Information ===")

        for file_info in self.selected_asg_files:
            file_path = file_info['path']

            try:
                # Ensure file exists and is readable
                if not file_path.exists():
                    logger.error(f"File does not exist: {file_path}")
                    continue

                # Convert to string path for Windows compatibility
                file_path_str = str(file_path)

                # Add small delay to prevent file handle conflicts
                time.sleep(0.01)

                # Read file with explicit error handling
                with open(file_path_str, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parse JSON separately
                asg_data = json.loads(content)

                asg_config = asg_data.get('asg_configuration', {})
                asg_name = asg_config.get('name', 'Unknown')

                asgs.append({
                    'name': asg_name,
                    'account': file_info['account'],
                    'file_path': file_info['path'],
                    'config': asg_config
                })

            except PermissionError as e:
                logger.error(f"Permission denied reading ASG file {file_path}: {e}")
                continue
            except OSError as e:
                logger.error(f"OS error reading ASG file {file_path}: {e}")
                continue
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in ASG file {file_path}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error reading ASG file {file_path}: {e}")
                continue

        # Show summary by account
        account_asg_count = defaultdict(int)
        for asg in asgs:
            account_asg_count[asg['account']] += 1

        print(f"Extracted {len(asgs)} ASGs from files:")
        for account, count in account_asg_count.items():
            print(f"  - {account}: {count} ASGs")

        return asgs

    def extract_ec2_instances_from_files(self):
        """Extract EC2 instance information from selected files"""
        instances = []

        print(f"\n=== Extracting EC2 Instance Information ===")

        for file_info in self.selected_ec2_files:
            try:
                with open(file_info['path'], 'r') as f:
                    ec2_data = json.load(f)

                    instance_details = ec2_data.get('instance_details', {})
                    account_info = ec2_data.get('account_info', {})

                    instances.append({
                        'instance_id': instance_details.get('instance_id', 'Unknown'),
                        'instance_type': instance_details.get('instance_type', 'Unknown'),
                        'region': instance_details.get('region', 'us-east-1'),
                        'ami_id': instance_details.get('ami_id', 'Unknown'),
                        'account': account_info.get('account_name', file_info['account']),
                        'file_path': file_info['path']
                    })

            except (json.JSONDecodeError, FileNotFoundError) as e:
                logger.error(f"Error reading EC2 instance file {file_info['path']}: {e}")
                continue

        # Show summary by account
        account_instance_count = defaultdict(int)
        for instance in instances:
            account_instance_count[instance['account']] += 1

        print(f"Extracted {len(instances)} EC2 instances from files:")
        for account, count in account_instance_count.items():
            print(f"  - {account}: {count} instances")

        return instances

    def display_asgs(self, asgs):
        """Display available ASGs"""
        print("\n=== Available ASGs (Multi-Account) ===")

        # Group by account
        asgs_by_account = defaultdict(list)
        for asg in asgs:
            asgs_by_account[asg['account']].append(asg)

        for i, asg in enumerate(asgs, 1):
            print(f"{i}. {asg['name']} ({asg['account']})")

        print(f"\nSummary by Account:")
        for account, account_asgs in asgs_by_account.items():
            asg_names = [asg['name'] for asg in account_asgs]
            print(f"  - {account}: {len(account_asgs)} ASGs - {', '.join(asg_names)}")

        print(f"\n{len(asgs) + 1}. All ASGs")

    def display_ec2_instances(self, instances):
        """Display available EC2 instances"""
        print("\n=== Available EC2 Instances (Multi-Account) ===")

        # Group by account
        instances_by_account = defaultdict(list)
        for instance in instances:
            instances_by_account[instance['account']].append(instance)

        for i, instance in enumerate(instances, 1):
            print(
                f"{i}. {instance['instance_id']} ({instance['instance_type']}) - {instance['region']} ({instance['account']})")

        print(f"\nSummary by Account:")
        for account, account_instances in instances_by_account.items():
            instance_ids = [inst['instance_id'] for inst in account_instances]
            print(f"  - {account}: {len(account_instances)} instances - {', '.join(instance_ids)}")

        print(f"\n{len(instances) + 1}. All Instances")

    def select_asgs(self):
        """Select ASGs for processing"""
        available_asgs = self.extract_asgs_from_files()

        if not available_asgs:
            logger.error("No ASGs found in selected files")
            return False

        self.display_asgs(available_asgs)

        while True:
            selection = input("\nSelect ASGs (single/comma-separated/range/all): ").strip()

            if selection.lower() in ['all', str(len(available_asgs) + 1)]:
                self.selected_asgs = available_asgs
                break

            try:
                selected_asgs = []
                parts = selection.split(',')

                for part in parts:
                    part = part.strip()
                    if '-' in part and not part.startswith('-'):
                        start, end = map(int, part.split('-'))
                        for i in range(start - 1, min(end, len(available_asgs))):
                            if i >= 0:
                                selected_asgs.append(available_asgs[i])
                    else:
                        if part.isdigit():
                            idx = int(part) - 1
                            if 0 <= idx < len(available_asgs):
                                selected_asgs.append(available_asgs[idx])

                if selected_asgs:
                    self.selected_asgs = selected_asgs
                    break
                else:
                    print("Invalid selection. Please try again.")

            except (ValueError, IndexError):
                print("Invalid selection format. Please try again.")

        # Show final selection summary
        account_selected_count = defaultdict(int)
        for asg in self.selected_asgs:
            account_selected_count[asg['account']] += 1

        print(f"\nSelected {len(self.selected_asgs)} ASGs:")
        for account, count in account_selected_count.items():
            asg_names = [asg['name'] for asg in self.selected_asgs if asg['account'] == account]
            print(f"  - {account}: {count} ASGs - {', '.join(asg_names)}")

        return True

    def select_ec2_instances(self):
        """Select EC2 instances for processing"""
        available_instances = self.extract_ec2_instances_from_files()

        if not available_instances:
            logger.error("No EC2 instances found in selected files")
            return False

        self.display_ec2_instances(available_instances)

        while True:
            selection = input("\nSelect EC2 instances (single/comma-separated/range/all): ").strip()

            if selection.lower() in ['all', str(len(available_instances) + 1)]:
                self.selected_ec2_instances = available_instances
                break

            try:
                selected_instances = []
                parts = selection.split(',')

                for part in parts:
                    part = part.strip()
                    if '-' in part and not part.startswith('-'):
                        start, end = map(int, part.split('-'))
                        for i in range(start - 1, min(end, len(available_instances))):
                            if i >= 0:
                                selected_instances.append(available_instances[i])
                    else:
                        if part.isdigit():
                            idx = int(part) - 1
                            if 0 <= idx < len(available_instances):
                                selected_instances.append(available_instances[idx])

                if selected_instances:
                    self.selected_ec2_instances = selected_instances
                    break
                else:
                    print("Invalid selection. Please try again.")

            except (ValueError, IndexError):
                print("Invalid selection format. Please try again.")

        # Show final selection summary
        account_selected_count = defaultdict(int)
        for instance in self.selected_ec2_instances:
            account_selected_count[instance['account']] += 1

        print(f"\nSelected {len(self.selected_ec2_instances)} EC2 instances:")
        for account, count in account_selected_count.items():
            instance_ids = [inst['instance_id'] for inst in self.selected_ec2_instances if inst['account'] == account]
            print(f"  - {account}: {count} instances - {', '.join(instance_ids)}")

        return True

    def get_ec2_instances_from_asg(self, asg_info):
        """Get EC2 instances from ASG using AWS API"""
        try:
            account_config = self.accounts_config[asg_info['account']]

            # Configure AWS client
            session = boto3.Session(
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name=asg_info['config'].get('region', 'us-east-1')
            )

            autoscaling = session.client('autoscaling')
            ec2 = session.client('ec2')

            # Get ASG instances
            response = autoscaling.describe_auto_scaling_groups(
                AutoScalingGroupNames=[asg_info['name']]
            )

            if not response['AutoScalingGroups']:
                logger.warning(f"ASG {asg_info['name']} not found")
                return []

            asg = response['AutoScalingGroups'][0]
            instance_ids = [instance['InstanceId'] for instance in asg['Instances']
                            if instance['LifecycleState'] == 'InService']

            if not instance_ids:
                logger.warning(f"No running instances in ASG {asg_info['name']}")
                return []

            # Get instance details
            instances_response = ec2.describe_instances(InstanceIds=instance_ids)
            instances = []

            for reservation in instances_response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] == 'running':
                        instances.append({
                            'instance_id': instance['InstanceId'],
                            'public_ip': instance.get('PublicIpAddress'),
                            'private_ip': instance.get('PrivateIpAddress'),
                            'asg_name': asg_info['name'],
                            'account': asg_info['account']
                        })

            return instances

        except Exception as e:
            logger.error(f"Error getting instances from ASG {asg_info['name']}: {e}")
            return []

    def get_ec2_instance_details_from_aws(self, instance_info):
        """Get EC2 instance details from AWS API using instance_id and region"""
        try:
            account_config = self.accounts_config[instance_info['account']]

            # Configure AWS client
            session = boto3.Session(
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name=instance_info['region']
            )

            ec2 = session.client('ec2')

            # Get instance details
            instances_response = ec2.describe_instances(InstanceIds=[instance_info['instance_id']])

            for reservation in instances_response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] == 'running':
                        return {
                            'instance_id': instance['InstanceId'],
                            'public_ip': instance.get('PublicIpAddress'),
                            'private_ip': instance.get('PrivateIpAddress'),
                            'state': instance['State']['Name'],
                            'account': instance_info['account'],
                            'region': instance_info['region']
                        }
                    else:
                        logger.warning(
                            f"Instance {instance['InstanceId']} is in state '{instance['State']['Name']}', skipping")
                        return None

            return None

        except Exception as e:
            logger.error(f"Error getting instance details for {instance_info['instance_id']}: {e}")
            return None

    def test_ssh_connection(self, instance):
        """Test SSH connection to an instance, supporting key-based auth for ec2-user."""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            ip = instance['public_ip'] or instance['private_ip']
            if not ip:
                return False, "No IP address available", None

            if self.ssh_username == "ec2-user":
                key_path = "./k8s_demo_key.pem"  # Update this path as needed
                if not os.path.exists(key_path):
                    return False, f"Key file not found: {key_path}", None
                pkey = paramiko.RSAKey.from_private_key_file(key_path)
                ssh.connect(
                    hostname=ip,
                    username="ec2-user",
                    pkey=pkey,
                    timeout=10
                )
            else:
                ssh.connect(
                    hostname=ip,
                    username=self.ssh_username,
                    password=self.ssh_password,
                    timeout=10
                )

            stdin, stdout, stderr = ssh.exec_command('echo "SSH connection successful"')
            output = stdout.read().decode().strip()
            ssh.close()

            if "SSH connection successful" in output:
                ssh_command = f"ssh {self.ssh_username}@{ip}"
                if self.ssh_username == "ec2-user":
                    ssh_command += f" -i k8s_demo_key.pem"
                logger.info(f"SSH connection successful to {instance['instance_id']} ({ip})")
                print(
                    f"✓ SSH SUCCESS: {instance['instance_id']} - To connect manually: {ssh_command}")
                return True, "SSH connection successful", ssh_command
            else:
                return False, "SSH command failed", None

        except Exception as e:
            logger.error(f"SSH connection failed to {instance['instance_id']}: {e}")
            return False, str(e), None

    def parse_user_instructions(self, file_path):
        """Parse user mini-instruction file and extract commands"""
        try:
            print(f"\nReading commands from: {file_path.name}")

            with open(file_path, 'r') as f:
                lines = f.readlines()

            # Read each line, strip whitespace, skip empty lines
            commands = []
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                # Skip empty lines
                if line:
                    commands.append(line)
                    print(f"  {len(commands)}. {line}")

            print(f"\nExtracted {len(commands)} commands from file")
            return commands

        except Exception as e:
            logger.error(f"Error reading instruction file {file_path}: {e}")
            return None

    def execute_command_on_instance(self, instance, command, timeout=30):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ip = instance['public_ip'] or instance['private_ip']

            if self.ssh_username == "ec2-user":
                key_path = "./k8s_demo_key.pem"
                if not os.path.exists(key_path):
                    return {'success': False, 'output': '', 'error': f'Key file not found: {key_path}', 'exit_code': -1}
                pkey = paramiko.RSAKey.from_private_key_file(key_path)
                ssh.connect(hostname=ip, username="ec2-user", pkey=pkey, timeout=10)
            else:
                ssh.connect(hostname=ip, username=self.ssh_username, password=self.ssh_password, timeout=10)

            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            output = stdout.read().decode()
            error = stderr.read().decode()
            exit_code = stdout.channel.recv_exit_status()
            ssh.close()
            return {'success': exit_code == 0, 'output': output, 'error': error, 'exit_code': exit_code}
        except Exception as e:
            return {'success': False, 'output': '', 'error': str(e), 'exit_code': -1}

    def log_command_output(log_file, username, command, output, error, success, command_number):
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"User: {username}\n")
            f.write(f"Command #{command_number}: {command}\n")
            f.write(f"Success: {'YES' if success else 'NO'}\n")
            f.write(f"Output:\n{output}\n")
            if error:
                f.write(f"Error:\n{error}\n")
            f.write("-" * 50 + "\n")

    def process_instance(self, instance, instruction_file_info):
        """Process a single instance with user instructions for both demouser and ec2-user"""
        logger.info(f"Processing instance {instance['instance_id']} in ASG {instance['asg_name']} for account {instance['account']}")

        # Prepare output file path
        account = instance['account']
        instance_id = instance['instance_id']
        cluster_name = instruction_file_info.get('cluster_name', 'unknown-cluster')
        extracted_username = self.extract_username_from_cluster(cluster_name)
        account_dir = Path(self.reports_path) / account / 'instances'
        account_dir.mkdir(parents=True, exist_ok=True)
        output_file = account_dir / f"{instance_id}_{account}_{extracted_username}_command_output.txt"

        # --- 1. Run as demouser ---
        self.ssh_username = "demouser"
        self.ssh_password = "demouser@123"
        ssh_success, ssh_message, ssh_command = self.test_ssh_connection(instance)

        if not ssh_success:
            logger.error(f"SSH connection failed for {instance_id}: {ssh_message}")
            return {
                'instance_id': instance_id,
                'account': account,
                'instance_ip': instance['public_ip'] or instance['private_ip'],
                'ssh_command': f"ssh {self.ssh_username}@{instance['public_ip'] or instance['private_ip']}",
                'ssh_success': False,
                'ssh_message': ssh_message,
                'username': instruction_file_info.get('username', 'unknown'),
                'cluster_name': cluster_name,
                'commands_executed': 0,
                'commands_successful': 0,
                'command_results': [],
                'asg_name': instance.get('asg_name', 'N/A')
            }

        commands = self.parse_user_instructions(instruction_file_info['path'])
        if not commands:
            return {
                'instance_id': instance_id,
                'account': account,
                'instance_ip': instance['public_ip'] or instance['private_ip'],
                'ssh_command': ssh_command,
                'ssh_success': True,
                'ssh_message': "SSH successful",
                'username': instruction_file_info.get('username', 'unknown'),
                'cluster_name': cluster_name,
                'commands_executed': 0,
                'commands_successful': 0,
                'command_results': [],
                'asg_name': instance.get('asg_name', 'N/A'),
                'error': "Failed to parse instruction file"
            }

        results = []
        successful_commands = 0
        total_commands = len(commands)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"=== demouser OUTPUT ===\n")

        for i, command in enumerate(commands, 1):
            result = self.execute_command_on_instance(instance, command)
            result['command'] = command
            result['command_number'] = i
            results.append(result)
            if result['success']:
                successful_commands += 1

            # Append to output file
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(f"Command #{i}: {command}\n")
                f.write(f"Success: {'YES' if result['success'] else 'NO'}\n")
                f.write(f"Output:\n{result['output']}\n")
                if result['error']:
                    f.write(f"Error:\n{result['error']}\n")
                f.write("-" * 50 + "\n")

            time.sleep(1)

        #self.log_command_output(output_file, self.ssh_username, command, result['output'], result['error'], result['success'], i)

        # --- 2. Run as ec2-user, skipping setup commands ---
        skip_cmds = [
            "sudo mkdir -p /home/ec2-user/.aws",
            "sudo cp -r /home/demouser/.aws/* /home/ec2-user/.aws/",
            "sudo chown -R ec2-user:ec2-user /home/ec2-user/.aws",
            "sudo mkdir -p /home/ec2-user/.kube",
            "sudo cp -r /home/demouser/.kube/* /home/ec2-user/.kube/",
            "sudo chown -R ec2-user:ec2-user /home/ec2-user/.kube"
        ]
        self.ssh_username = "ec2-user"
        self.ssh_password = None  # Use key-based auth if needed

        # Try SSH as ec2-user
        ssh_success_ec2, ssh_message_ec2, ssh_command_ec2 = self.test_ssh_connection(instance)
        ec2_results = []
        ec2_successful = 0

        filtered_commands = [
            cmd for cmd in commands
            if not any(cmd.strip().startswith(skip) for skip in skip_cmds)
        ]

        with open(output_file, 'a', encoding='utf-8') as f:
            f.write("\n =============ec2-user OUTPUT =============\n")

        if ssh_success_ec2:
            for i, command in enumerate(filtered_commands, 1):
                result = self.execute_command_on_instance(instance, command)
                result['command'] = command
                result['command_number'] = i
                ec2_results.append(result)
                if result['success']:
                    ec2_successful += 1

                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(f"Command #{i}: {command}\n")
                    f.write(f"Success: {'YES' if result['success'] else 'NO'}\n")
                    f.write(f"Output:\n{result['output']}\n")
                    if result['error']:
                        f.write(f"Error:\n{result['error']}\n")
                    f.write("-" * 50 + "\n")
                time.sleep(1)
        else:
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(f"ec2-user SSH failed: {ssh_message_ec2}\n")

        #self.log_command_output(output_file, self.ssh_username, command, result['output'], result['error'], result['success'], i)
        # Return combined result (demouser + ec2-user)
        return {
            'instance_id': instance_id,
            'account': account,
            'instance_ip': instance['public_ip'] or instance['private_ip'],
            'ssh_command': ssh_command,
            'username': instruction_file_info['username'],
            'cluster_name': cluster_name,
            'ssh_success': True,
            'ssh_message': "SSH successful (demouser)",
            'commands_executed': total_commands,
            'commands_successful': successful_commands,
            'command_results': results,
            'ec2_user_ssh_success': ssh_success_ec2,
            'ec2_user_ssh_message': ssh_message_ec2,
            'ec2_user_commands_executed': len(filtered_commands),
            'ec2_user_commands_successful': ec2_successful,
            'ec2_user_command_results': ec2_results,
            'asg_name': instance.get('asg_name', 'N/A')
        }

    def save_instance_report(self, instance_result):
        """Save individual instance report with extracted username in filename, showing both demouser and ec2-user results"""
        account = instance_result['account']
        instance_id = instance_result['instance_id']
        cluster_name = instance_result.get('cluster_name', 'unknown-cluster')
        extracted_username = self.extract_username_from_cluster(cluster_name)
        account_dir = Path(self.reports_path) / account / 'instances'
        account_dir.mkdir(parents=True, exist_ok=True)
        report_file = account_dir / f"{instance_id}_{account}_{extracted_username}_report.json"

        # Save JSON report (optional, as before)
        # with open(report_file, 'w', encoding='utf-8') as f:
        #     json.dump(instance_result, f, indent=2)

        output_file = account_dir / f"{instance_id}_{account}_{extracted_username}_command_output.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"Command Outputs for Instance: {instance_id}\n")
            f.write(f"Account: {account}\n")
            f.write(f"Username: {account}_{extracted_username}\n")
            f.write(f"Cluster: {instance_result.get('cluster_name', 'N/A')}\n")
            f.write(f"ASG Name: {instance_result.get('asg_name', 'N/A')}\n")
            f.write(f"Instance Source: {self.instance_source}\n")
            f.write(f"Instance IP: {instance_result.get('instance_ip', 'N/A')}\n")
            f.write(f"SSH Command: {instance_result.get('ssh_command', 'N/A')}\n")
            f.write(f"Report Generated: {self.current_time} IST\n")
            f.write(f"Generated By: {self.current_user}\n")
            f.write("=" * 80 + "\n\n")

            # demouser summary
            f.write(
                f"demouser: {instance_result['commands_successful']}/{instance_result['commands_executed']} commands successful\n")
            # ec2-user summary
            f.write(
                f"ec2-user: {instance_result.get('ec2_user_commands_successful', 0)}/{instance_result.get('ec2_user_commands_executed', 0)} commands successful\n\n")

            # demouser output
            f.write("=== demouser OUTPUT ===\n")
            for result in instance_result['command_results']:
                f.write(f"[{result['command_number']}] {result['command']}\n")
                f.write(
                    f"    Status: {'SUCCESS' if result['success'] else 'FAILED'} (exit code: {result['exit_code']})\n")
                if result['output'].strip():
                    f.write("    Output:\n")
                    for line in result['output'].strip().split('\n'):
                        f.write(f"      {line}\n")
                if result['error'].strip():
                    f.write("    Error:\n")
                    for line in result['error'].strip().split('\n'):
                        f.write(f"      {line}\n")
                f.write("\n")

            # ec2-user output
            f.write("\n =============ec2-user OUTPUT =============\n")
            for result in instance_result.get('ec2_user_command_results', []):
                f.write(f"[{result['command_number']}] {result['command']}\n")
                f.write(
                    f"    Status: {'SUCCESS' if result['success'] else 'FAILED'} (exit code: {result['exit_code']})\n")
                if result['output'].strip():
                    f.write("    Output:\n")
                    for line in result['output'].strip().split('\n'):
                        f.write(f"      {line}\n")
                if result['error'].strip():
                    f.write("    Error:\n")
                    for line in result['error'].strip().split('\n'):
                        f.write(f"      {line}\n")
                f.write("\n")

        logger.info(f"Command outputs saved: {output_file}")

    def save_asg_report(self, asg_name, username, instance_results):
        """Save ASG-level report in account/asg/ directory, showing both demouser and ec2-user results"""
        if not instance_results:
            return

        account = instance_results[0]['account']
        cluster_name = instance_results[0].get('cluster_name', 'unknown-cluster')
        extracted_username = self.extract_username_from_cluster(cluster_name)
        asg_dir = Path(self.reports_path) / account / 'asg'
        asg_dir.mkdir(parents=True, exist_ok=True)
        json_file = asg_dir / f"{asg_name}_{account}_{extracted_username}.json"
        txt_file = asg_dir / f"{asg_name}_{account}_{extracted_username}_output.txt"

        total_instances = len(instance_results)
        ssh_successful = sum(1 for r in instance_results if r['ssh_success'])
        # Per-user stats
        demouser_total = sum(r['commands_executed'] for r in instance_results)
        demouser_success = sum(r['commands_successful'] for r in instance_results)
        ec2user_total = sum(r.get('ec2_user_commands_executed', 0) for r in instance_results)
        ec2user_success = sum(r.get('ec2_user_commands_successful', 0) for r in instance_results)

        final_username = f"{account}_{extracted_username}"
        if 'root' in extracted_username:
            final_username = extracted_username


        # Save text output report
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(f"ASG SSH Connection Report\n")
            f.write(f"=" * 50 + "\n")
            f.write(f"ASG Name: {asg_name}\n")
            f.write(f"Username: {final_username}\n")
            f.write(f"Account: {account}\n")
            f.write(f"Instance Source: {self.instance_source}\n")
            f.write(f"Report Generated: {self.current_time} IST\n")
            f.write(f"Generated By: {self.current_user}\n")
            f.write(f"\nSummary Statistics:\n")
            f.write(f"- Total Instances: {total_instances}\n")
            f.write(
                f"- SSH Successful: {ssh_successful}/{total_instances} ({(ssh_successful / max(total_instances, 1) * 100):.1f}%)\n")
            f.write(f"- demouser: {demouser_success}/{demouser_total} commands successful\n")
            f.write(f"- ec2-user: {ec2user_success}/{ec2user_total} commands successful\n")
            f.write(f"\n" + "=" * 80 + "\n")
            f.write(f"INSTANCE DETAILS\n")
            f.write(f"=" * 80 + "\n\n")

            for result in instance_results:
                f.write(f"Instance ID: {result['instance_id']}\n")
                f.write(f"Instance IP: {result.get('instance_ip', 'N/A')}\n")
                f.write(f"SSH Success: {'SUCCESS' if result['ssh_success'] else 'FAILED'}\n")
                f.write(f"SSH Command: {result.get('ssh_command', 'N/A')}\n")
                f.write(f"Cluster: {result.get('cluster_name', 'N/A')}\n")
                f.write(
                    f"Commands (demouser): {result['commands_successful']}/{result['commands_executed']} successful\n")
                f.write(
                    f"Commands (ec2-user): {result.get('ec2_user_commands_successful', 0)}/{result.get('ec2_user_commands_executed', 0)} successful\n")

                if not result['ssh_success']:
                    f.write(f"SSH Error: {result['ssh_message']}\n")

                # demouser output
                f.write(f"\n=== demouser OUTPUT ===\n")
                for cmd_result in result['command_results']:
                    status = "SUCCESS" if cmd_result['success'] else "FAILED"
                    f.write(f"[{cmd_result['command_number']}] {cmd_result['command']}\n")
                    f.write(f"    Status: {status} (exit code: {cmd_result['exit_code']})\n")
                    if cmd_result['output'].strip():
                        f.write(f"    Output:\n")
                        for line in cmd_result['output'].strip().split('\n'):
                            f.write(f"      {line}\n")
                    if cmd_result['error'].strip():
                        f.write(f"    Error:\n")
                        for line in cmd_result['error'].strip().split('\n'):
                            f.write(f"      {line}\n")
                    f.write(f"\n")

                # ec2-user output
                f.write("\n =============ec2-user OUTPUT =============\n")
                for cmd_result in result.get('ec2_user_command_results', []):
                    status = "SUCCESS" if cmd_result['success'] else "FAILED"
                    f.write(f"[{cmd_result['command_number']}] {cmd_result['command']}\n")
                    f.write(f"    Status: {status} (exit code: {cmd_result['exit_code']})\n")
                    if cmd_result['output'].strip():
                        f.write(f"    Output:\n")
                        for line in cmd_result['output'].strip().split('\n'):
                            f.write(f"      {line}\n")
                    if cmd_result['error'].strip():
                        f.write(f"    Error:\n")
                        for line in cmd_result['error'].strip().split('\n'):
                            f.write(f"      {line}\n")
                    f.write(f"\n")

                f.write(f"=" * 80 + "\n\n")

        logger.info(f"ASG text report saved: {txt_file}")
        return json_file, txt_file


    def save_account_summary(self, account, instance_results):
        """Save account-level summary report"""
        account_dir = Path(self.reports_path) / account
        account_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_file = account_dir / f'summary_report_{timestamp}.json'

        total_instances = len(instance_results)
        ssh_successful = sum(1 for r in instance_results if r['ssh_success'])
        total_commands = sum(r['commands_executed'] for r in instance_results)
        successful_commands = sum(r['commands_successful'] for r in instance_results)

        summary_data = {
            'report_generated': self.current_time,
            'generated_by': self.current_user,
            'account': account,
            'processing_mode': 'direct' if self.direct_mode else 'interactive',
            'instance_source': self.instance_source,
            'total_instances': total_instances,
            'ssh_successful_instances': ssh_successful,
            'ssh_success_rate': (ssh_successful / max(total_instances, 1)) * 100,
            'total_commands_executed': total_commands,
            'total_commands_successful': successful_commands,
            'command_success_rate': (successful_commands / max(total_commands, 1)) * 100,
            'instance_summaries': [
                {
                    'instance_id': r['instance_id'],
                    'username': r.get('username', 'N/A'),
                    'cluster_name': r.get('cluster_name', 'N/A'),
                    'instance_ip': r.get('instance_ip', 'N/A'),
                    'ssh_command': r.get('ssh_command', 'N/A'),
                    'ssh_success': r['ssh_success'],
                    'commands_executed': r['commands_executed'],
                    'commands_successful': r['commands_successful'],
                    'asg_name': r.get('asg_name', 'N/A')
                }
                for r in instance_results
            ]
        }

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2)

        logger.info(f"Account summary saved: {summary_file}")

    def save_instance_html_report(self, instance_result):
        """
        Save a styled HTML report for an instance, showing SSH details and command outputs
        for both demouser (password) and ec2-user (key).
        """
        from html import escape

        account = instance_result['account']
        instance_id = instance_result['instance_id']
        cluster_name = instance_result.get('cluster_name', 'unknown-cluster')
        extracted_username = self.extract_username_from_cluster(cluster_name)
        account_dir = Path(self.reports_path) / account / 'instances'
        account_dir.mkdir(parents=True, exist_ok=True)
        # Save in account directory (existing location)
        html_file = account_dir / f"{instance_id}_{account}_{extracted_username}_report.html"

        # Also save in current directory where ec2_ssh_connector.py is located
        current_dir_html_file = Path(f"{account}_{extracted_username}_report.html")

        demouser_ssh = f"ssh demouser@{instance_result.get('instance_ip', 'N/A')} (password: demouser@123)"
        ec2user_ssh = f"ssh -i k8s_demo_key.pem ec2-user@{instance_result.get('instance_ip', 'N/A')}"

        final_username = f"{account}_{extracted_username}"
        if 'root' in extracted_username:
            final_username = extracted_username

        def render_commands(title, results):
            html = f'<details><summary><b>{escape(title)}</b></summary><div style="margin-left:1em">'

            # First, show essential commands (like nodegroup listing) that should be visible
            essential_commands = ['aws eks list-nodegroups', 'kubectl get nodes', 'kubectl get pods']

            # Show essential commands first (expanded)
            for result in results:
                if any(cmd in result['command'] for cmd in essential_commands):
                    html += f"<div style='margin-bottom:1em; border-left: 3px solid #28a745; padding-left: 10px;'>"
                    html += f"<b>Command #{result['command_number']}:</b> <code>{escape(result['command'])}</code><br>"
                    html += f"<b>Status:</b> {'<span style=\"color:green\">SUCCESS</span>' if result['success'] else '<span style=\"color:red\">FAILED</span>'} (exit code: {result['exit_code']})<br>"
                    if result['output'].strip():
                        html += f"<b>Output:</b><pre>{escape(result['output'][:500])}{('...' if len(result['output']) > 500 else '')}</pre>"
                    html += "</div>"

            # Then show all other commands collapsed
            html += '<details style="margin-top: 1em;"><summary><b>Show All Commands</b></summary><div style="margin-left:1em">'
            for result in results:
                html += f"<div style='margin-bottom:1em;'><b>Command #{result['command_number']}:</b> <code>{escape(result['command'])}</code><br>"
                html += f"<b>Status:</b> {'<span style=\"color:green\">SUCCESS</span>' if result['success'] else '<span style=\"color:red\">FAILED</span>'} (exit code: {result['exit_code']})<br>"
                if result['output'].strip():
                    html += f"<b>Output:</b><pre>{escape(result['output'])}</pre>"
                if result['error'].strip():
                    html += f"<b>Error:</b><pre style='color:red'>{escape(result['error'])}</pre>"
                html += "</div>"
            html += "</div></details>"

            html += "</div></details>"
            return html

        html_content = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Instance Report: {instance_id}</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #f9f9f9; color: #222; }}
            h1 {{ color: #2c3e50; }}
            .section {{ background: #fff; border-radius: 8px; box-shadow: 0 2px 8px #ccc; margin: 2em 0; padding: 1.5em; }}
            pre {{ background: #f4f4f4; border-radius: 4px; padding: 0.5em; overflow-x: auto; }}
            code {{ background: #f4f4f4; border-radius: 3px; padding: 2px 4px; }}
            details {{ margin-bottom: 1em; }}
            summary {{ cursor: pointer; font-size: 1.1em; }}
        </style>
    </head>
    <body>
        <h1>EC2/EKS Instance Report</h1>
        <div class="section">
            <b>Instance ID:</b> {escape(instance_id)}<br>
            <b>Account:</b> {escape(account)}<br>
            <b>Cluster:</b> {escape(cluster_name)}<br>
            <b>Username:</b> {escape(final_username)}<br>
            <b>ASG Name:</b> {escape(instance_result.get('asg_name', 'N/A'))}<br>
            <b>Instance IP:</b> {escape(instance_result.get('instance_ip', 'N/A'))}<br>
            <b>Report Generated:</b> {escape(self.current_time)} IST<br>
            <b>Generated By:</b> {escape(self.current_user)}<br>
        </div>
        <div class="section">
            <h2>SSH Access Instructions</h2>
            <ul>
                <li><b>demouser (password):</b> <code>{escape(demouser_ssh)}</code></li>
                <li><b>ec2-user (key):</b> <code>{escape(ec2user_ssh)}</code></li>
            </ul>
            <p><b>Key file:</b> <code>k8s_demo_key.pem</code> (contact admin if you need this)</p>
        </div>
        <div class="section">
            <h2>Command Outputs</h2>
            {render_commands("demouser Output", instance_result['command_results'])}
            {render_commands("ec2-user Output", instance_result.get('ec2_user_command_results', []))}
        </div>
    </body>
    </html>
    """

        # Write to account directory
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Write to current directory as well
        with open(current_dir_html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"HTML report saved to account directory: {html_file}")
        logger.info(f"HTML report saved to current directory: {current_dir_html_file}")

    def run_automation(self):
        """Main automation workflow with smart mapping"""
        print("=== EC2 to EKS Cluster Connection Automation (Interactive Mode) ===")
        print(f"Current Date/Time: {self.current_time} UTC")
        print(f"Current User: {self.current_user}")
        print("Processing Mode: Interactive Multi-Account Processing with Smart Mapping\n")

        # Step 1: Load configuration
        if not self.load_accounts_config():
            return False

        # Step 2: Select accounts (MULTI-ACCOUNT)
        self.select_accounts()

        # Step 3: Select instance source (ASG or EC2)
        if not self.select_instance_source():
            return False

        # Step 4: Select files based on instance source
        if self.instance_source == 'asg':
            if not self.select_asg_files():
                return False
            if not self.select_asgs():
                return False
        else:  # ec2
            if not self.select_ec2_files():
                return False
            if not self.select_ec2_instances():
                return False

        # Step 5: NEW - Smart mapping between ASG/EC2 and instruction files
        if not self.build_smart_mapping():
            print("[ERROR] Smart mapping failed. Cannot proceed without instruction file mappings.")
            return False

        # Step 6: Get instances and process them based on source with smart mapping
        print(f"\n=== Processing Instances from {self.instance_source.upper()} Source with Smart Mapping ===")

        all_instances = []

        if self.instance_source == 'asg':
            # Get instances from selected ASGs
            for asg_info in self.selected_asgs:
                if asg_info['name'] in self.final_mapping:
                    instances = self.get_ec2_instances_from_asg(asg_info)
                    all_instances.extend(instances)
                else:
                    print(f"[SKIP]  Skipping ASG {asg_info['name']} (no instruction file mapping)")
        else:  # ec2
            # Get instances from selected EC2 files
            for instance_info in self.selected_ec2_instances:
                if instance_info['instance_id'] in self.final_mapping:
                    instance_details = self.get_ec2_instance_details_from_aws(instance_info)
                    if instance_details:
                        all_instances.append(instance_details)
                else:
                    print(f"[SKIP]  Skipping instance {instance_info['instance_id']} (no instruction file mapping)")

        logger.info(f"Found {len(all_instances)} instances to process with mappings")

        if not all_instances:
            logger.error("No instances found with valid mappings")
            return False

        # Process instances with smart mappings
        all_results = []

        # Group instances by their mapping
        instances_by_mapping = defaultdict(list)

        if self.instance_source == 'asg':
            for instance in all_instances:
                asg_name = instance.get('asg_name')
                if asg_name and asg_name in self.final_mapping:
                    instances_by_mapping[asg_name].append(instance)
        else:  # ec2
            for instance in all_instances:
                instance_id = instance.get('instance_id')
                if instance_id and instance_id in self.final_mapping:
                    instances_by_mapping[instance_id].append(instance)

        print(f"\nInstance distribution by mapping:")
        for mapping_key, instances in instances_by_mapping.items():
            instruction_info = self.final_mapping[mapping_key]
            print(f"  - {mapping_key} -> {instruction_info['extracted_username']} ({len(instances)} instances)")

        # Process each mapping group
        for mapping_key, instances in instances_by_mapping.items():
            instruction_file = self.final_mapping[mapping_key]
            logger.info(f"Processing {len(instances)} instances for mapping {mapping_key}")
            print(
                f"\nUsing instruction file: {instruction_file['extracted_username']} @ {instruction_file['cluster_name']}")

            mapping_results = []

            # Process instances in parallel (limited concurrency)
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_instance = {
                    executor.submit(self.process_instance, instance, instruction_file): instance
                    for instance in instances
                }

                for future in as_completed(future_to_instance):
                    instance = future_to_instance[future]
                    try:
                        result = future.result()
                        mapping_results.append(result)
                        all_results.append(result)

                        # Save individual instance report
                        self.save_instance_html_report(result)
                        self.save_instance_report(result)

                    except Exception as e:
                        logger.error(f"Error processing instance {instance['instance_id']}: {e}")

            # Generate ASG reports if using ASG source
            if self.instance_source == 'asg' and mapping_results:
                print(f"\n=== Generating ASG Report for {mapping_key} ===")

                try:
                    extracted_username = instruction_file['extracted_username']
                    json_file, txt_file = self.save_asg_report(mapping_key, instruction_file['username'],
                                                               mapping_results)
                    print(f"✓ ASG report saved: {mapping_key} -> {json_file.name}, {txt_file.name}")
                except Exception as e:
                    logger.error(f"Error generating ASG report for {mapping_key}: {e}")

        # Save account summaries
        account_results = defaultdict(list)
        for result in all_results:
            account_results[result['account']].append(result)

        for account, results in account_results.items():
            if results:
                self.save_account_summary(account, results)

        # Print final summary
        self.print_final_summary(all_results)

        return True

    def print_final_summary(self, results):
        """Print final summary to console"""
        print("\n" + "=" * 80)
        print("FINAL EXECUTION SUMMARY (SMART MAPPING)")
        print("=" * 80)
        print(f"Report Generated: {self.current_time} IST")
        print(f"Generated By: {self.current_user}")
        print(f"Processing Mode: Interactive Smart Mapping ({self.instance_source.upper()} Source)")
        print("-" * 80)

        total_instances = len(results)
        ssh_successful = sum(1 for r in results if r['ssh_success'])
        total_commands = sum(r['commands_executed'] for r in results)
        successful_commands = sum(r['commands_successful'] for r in results)

        print(f"Total Instances Processed: {total_instances}")
        print(
            f"SSH Successful: {ssh_successful}/{total_instances} ({(ssh_successful / max(total_instances, 1) * 100):.1f}%)")
        print(f"Total Commands Executed: {total_commands}")
        print(
            f"Commands Successful: {successful_commands}/{total_commands} ({(successful_commands / max(total_commands, 1) * 100):.1f}%)")

        print(f"\n{'=' * 20} SSH CONNECTION DETAILS BY ACCOUNT {'=' * 20}")

        by_account = defaultdict(list)
        for r in results:
            by_account[r['account']].append(r)

        for account, account_results in by_account.items():
            ssh_ok = sum(1 for r in account_results if r['ssh_success'])
            print(f"\nAccount: {account} - {ssh_ok}/{len(account_results)} instances SSH successful")

            for result in account_results:
                status_symbol = "SUCCESS" if result['ssh_success'] else "FAILED"
                username = result.get('username', 'N/A')
                cluster = result.get('cluster_name', 'N/A')
                asg_name = result.get('asg_name', 'N/A')
                cmd_status = f"{result['commands_successful']}/{result['commands_executed']}"
                ip = result.get('instance_ip', 'N/A')
                ssh_cmd = result.get('ssh_command', f"ssh {self.ssh_username}@{ip}")

                # Extract username from cluster
                extracted_username = self.extract_username_from_cluster(cluster)

                print(
                    f"  {status_symbol} {result['instance_id']} | User: {username} | Extracted: {extracted_username} | ASG: {asg_name}")
                print(f"    IP: {ip} | Commands: {cmd_status} | Cluster: {cluster}")
                if result['ssh_success']:
                    print(f"    SSH: {ssh_cmd} (password: {self.ssh_password})")
                else:
                    print(f"    SSH Failed: {result['ssh_message']}")
                print()

        print(f"{'=' * 30} REPORTS SAVED BY ACCOUNT {'=' * 30}")
        print(f"Detailed reports saved in: {self.reports_path}/")
        print("Files generated by account:")

        for account in by_account.keys():
            print(f"\n  Account: {account}")
            #print(f"    [STATS] Account Summary: {self.reports_path}/{account}/summary_report.json")

            # Instance reports
            account_results = by_account[account]
            for result in account_results:
                cluster_name = result.get('cluster_name', 'unknown-cluster')
                extracted_username = self.extract_username_from_cluster(cluster_name)
                # print(
                #     f"    [LIST] Instance: {self.reports_path}/{account}/instances/{result['instance_id']}_{extracted_username}_report.json")
                print(
                    f"    [FILE] Commands: {self.reports_path}/{account}/instances/{result['instance_id']}_{extracted_username}_command_output.txt")

            # ASG reports
            if self.instance_source == 'asg':
                asg_names = set(r.get('asg_name') for r in account_results if r.get('asg_name', 'N/A') != 'N/A')
                for asg_name in asg_names:
                    # Get extracted username from one of the results
                    for result in account_results:
                        if result.get('asg_name') == asg_name:
                            cluster_name = result.get('cluster_name', 'unknown-cluster')
                            extracted_username = self.extract_username_from_cluster(cluster_name)
                            # print(
                            #     f"    🏗️  ASG JSON: {self.asg_base_path}/{account}/{asg_name}_{extracted_username}.json")
                            print(
                                f"    [LOG] ASG Text: {self.asg_base_path}/{account}/{asg_name}_{extracted_username}_output.txt")
                            break

        print(f"\nTotal accounts processed: {len(by_account)}")
        print(f"Instance source used: {self.instance_source.upper()} with Smart Username Mapping")
        print(f"Smart mappings applied: {len(self.final_mapping)}")
        print("\n" + "=" * 80)


def main():
    """Main entry point"""
    connector = EKSConnector()

    # UPDATED: Current timestamp from your input
    connector.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connector.current_user = "varadharajaan"

    try:
        # Parse command line arguments
        if not connector.parse_command_line_args():
            return 1

        # Run in appropriate mode
        if connector.direct_mode:
            # For direct mode, we still need basic instruction file selection
            if not connector.discover_user_instruction_files():
                return 1
            success = connector.run_direct_mode()
        else:
            success = connector.run_automation()

        if success:
            print("\nAutomation completed successfully!")
            return 0
        else:
            print("\nAutomation failed!")
            return 1
    except KeyboardInterrupt:
        print("\nAutomation interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1



if __name__ == "__main__":
    sys.exit(main())
