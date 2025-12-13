#!/usr/bin/env python3
"""
Enhanced Interactive Cluster Management Tool
Handles batch operations on EKS clusters with smart credential detection and selection
"""

import json
import os
import sys
import time
import boto3
import glob
import re
import yaml
import subprocess
import shutil
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set
import tempfile
import logging
from text_symbols import Symbols



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


class EnhancedInteractiveClusterManager:
    """Enhanced interactive cluster management tool for EKS clusters with smart credential handling"""

    def __init__(self):
        """Initialize the Enhanced Interactive Cluster Manager"""
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_time = current_timestamp
        self.current_user = "varadharajaan"
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Setup logging
        self.setup_logging()

        self.log_operation('INFO',
                           f"Enhanced Interactive Cluster Manager initialized - Session ID: {self.execution_timestamp}")
        self.log_operation('INFO', f"Current Date and Time (UTC): {self.current_time}")
        self.log_operation('INFO', f"Current User: {self.current_user}")

    def setup_logging(self):
        """Set up logging for the interactive cluster manager"""
        log_dir = "logs/enhanced_cluster_mgmt"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        self.logger = logging.getLogger("enhanced_cluster_manager")
        self.logger.setLevel(logging.DEBUG)

        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        log_file = os.path.join(log_dir, f"enhanced_cluster_management_{self.execution_timestamp}.log")

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def log_operation(self, level: str, message: str):
        """Log operation with specified level"""
        if level == 'DEBUG':
            self.logger.debug(message)
        elif level == 'INFO':
            self.logger.info(message)
        elif level == 'WARNING':
            self.logger.warning(message)
        elif level == 'ERROR':
            self.logger.error(message)
        elif level == 'CRITICAL':
            self.logger.critical(message)
        else:
            self.logger.info(message)

    def print_colored(self, color: str, message: str) -> None:
        """Print colored message to terminal"""
        print(f"{color}{message}{Colors.NC}")

    def enhanced_interactive_cluster_management(self) -> bool:
        """
        Enhanced main interactive method for cluster management operations with smart credential handling
        """
        try:
            self.print_colored(Colors.YELLOW, f"\n🎛️  Enhanced EKS Cluster Management Tool")
            self.print_colored(Colors.YELLOW, f"Current Date and Time (UTC): {self.current_time}")
            self.print_colored(Colors.YELLOW, f"Current User: {self.current_user}")

            # Scan for cluster files
            cluster_files = self.scan_cluster_files()

            if not cluster_files:
                self.print_colored(Colors.RED, "[ERROR] No cluster files found")
                return False

            # Group clusters by date
            clusters_by_date = self.group_clusters_by_date(cluster_files)

            # Let user select date
            selected_date = self.select_date_interactive(clusters_by_date)
            if not selected_date:
                return False

            # Get clusters for selected date
            date_clusters = clusters_by_date[selected_date]

            # Let user select specific clusters
            selected_clusters = self.select_clusters_interactive(date_clusters, selected_date)
            if not selected_clusters:
                return False

            # Analyze cluster types and determine credential requirements
            credential_requirements = self.analyze_cluster_credential_requirements(selected_clusters)

            # Select appropriate credentials
            selected_credentials = self.select_credentials_interactive(credential_requirements)
            if not selected_credentials:
                return False

            # Let user choose operation
            operation = self.select_operation_interactive()
            if not operation:
                return False

            # Execute selected operation with appropriate credentials
            if operation == "delete_autoscaler":
                return self.delete_autoscalers_with_smart_credentials(selected_clusters, selected_credentials)
            elif operation == "configure_auth":
                return self.configure_auth_with_smart_credentials(selected_clusters, selected_credentials)
            else:
                self.print_colored(Colors.RED, "[ERROR] Unknown operation selected")
                return False

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Enhanced interactive cluster management failed: {str(e)}")
            self.log_operation('ERROR', f"Enhanced interactive cluster management failed: {str(e)}")
            return False

    def analyze_cluster_credential_requirements(self, selected_clusters: List[Dict]) -> Dict:
        """
        Analyze selected clusters to determine credential requirements

        Args:
            selected_clusters: List of selected cluster information

        Returns:
            Dict: Analysis of credential requirements
        """
        try:
            self.print_colored(Colors.CYAN, "\n[SCAN] Analyzing cluster credential requirements...")

            root_clusters = []
            iam_clusters = []

            for cluster in selected_clusters:
                cluster_name = cluster['cluster_name']

                # Detect cluster type based on naming pattern
                if self.is_root_created_cluster(cluster_name):
                    root_clusters.append(cluster)
                else:
                    iam_clusters.append(cluster)

            self.print_colored(Colors.CYAN, f"   {Symbols.STATS} Root user clusters: {len(root_clusters)}")
            self.print_colored(Colors.CYAN, f"   {Symbols.STATS} IAM user clusters: {len(iam_clusters)}")

            if root_clusters:
                self.print_colored(Colors.YELLOW, f"   [CROWN] Root clusters found:")
                for cluster in root_clusters:
                    self.print_colored(Colors.WHITE, f"      - {cluster['cluster_name']}")

            if iam_clusters:
                self.print_colored(Colors.YELLOW, f"   👤 IAM clusters found:")
                for cluster in iam_clusters:
                    self.print_colored(Colors.WHITE, f"      - {cluster['cluster_name']}")

            return {
                'root_clusters': root_clusters,
                'iam_clusters': iam_clusters,
                'needs_root_creds': len(root_clusters) > 0,
                'needs_iam_creds': len(iam_clusters) > 0
            }

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error analyzing credential requirements: {str(e)}")
            return {'root_clusters': [], 'iam_clusters': [], 'needs_root_creds': False, 'needs_iam_creds': False}

    def is_root_created_cluster(self, cluster_name: str) -> bool:
        """
        Determine if cluster was created by root user based on naming pattern

        Args:
            cluster_name: EKS cluster name

        Returns:
            bool: True if cluster was created by root user
        """
        # Root pattern: eks-cluster-root-account03-us-east-1-diox
        # IAM pattern: eks-cluster-account03_clouduser01-us-east-1-diox
        return '-root-' in cluster_name

    def extract_account_from_cluster_name(self, cluster_name: str) -> str:
        """
        Extract account identifier from cluster name

        Args:
            cluster_name: EKS cluster name

        Returns:
            str: Account identifier (e.g., account03) or empty string if not found
        """
        try:
            # Root pattern: eks-cluster-root-account03-us-east-1-diox
            # IAM pattern: eks-cluster-account03_clouduser01-us-east-1-diox

            if '-root-' in cluster_name:
                # Extract from root pattern
                match = re.search(r'-root-(account\d+)-', cluster_name)
                if match:
                    return match.group(1)
            else:
                # Extract from IAM pattern
                match = re.search(r'-(account\d+)_', cluster_name)
                if match:
                    return match.group(1)

            return ""

        except Exception as e:
            self.log_operation('ERROR', f"Error extracting account from cluster name {cluster_name}: {str(e)}")
            return ""

    def extract_iam_user_from_cluster_name(self, cluster_name: str) -> str:
        """
        Extract IAM username from cluster name

        Args:
            cluster_name: EKS cluster name

        Returns:
            str: IAM username (e.g., account03_clouduser01) or empty string if not found
        """
        try:
            # IAM pattern: eks-cluster-account03_clouduser01-us-east-1-diox
            if '_clouduser' in cluster_name:
                match = re.search(r'-(account\d+_clouduser\d+)-', cluster_name)
                if match:
                    return match.group(1)

            return ""

        except Exception as e:
            self.log_operation('ERROR', f"Error extracting IAM user from cluster name {cluster_name}: {str(e)}")
            return ""

    def scan_iam_credentials_files(self) -> List[Dict]:
        """
        Scan aws/iam/ directory for IAM user credentials files

        Returns:
            List[Dict]: List of IAM credentials file information sorted by timestamp
        """
        try:
            self.print_colored(Colors.CYAN, "[SCAN] Scanning for IAM user credentials files...")

            # Find all IAM credentials files
            pattern = "aws/iam/iam_users_credentials_*.json"
            files = glob.glob(pattern)

            if not files:
                self.print_colored(Colors.RED, "[ERROR] No IAM credentials files found in aws/iam/")
                return []

            credentials_files = []

            for file_path in files:
                try:
                    # Extract timestamp from filename
                    filename = os.path.basename(file_path)
                    # Pattern: iam_users_credentials_YYYYMMDD_HHMMSS.json
                    timestamp_match = re.search(r'_(\d{8})_(\d{6})\.json$', filename)

                    if timestamp_match:
                        date_str = timestamp_match.group(1)  # YYYYMMDD
                        time_str = timestamp_match.group(2)  # HHMMSS

                        # Format timestamp for display
                        formatted_timestamp = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"

                        # Load file to get creation info
                        with open(file_path, 'r') as f:
                            cred_data = json.load(f)

                        credentials_files.append({
                            'file_path': file_path,
                            'filename': filename,
                            'timestamp': formatted_timestamp,
                            'date_str': date_str,
                            'time_str': time_str,
                            'created_date': cred_data.get('created_date', 'Unknown'),
                            'created_time': cred_data.get('created_time', 'Unknown'),
                            'created_by': cred_data.get('created_by', 'Unknown'),
                            'total_users': cred_data.get('total_users', 0),
                            'data': cred_data
                        })

                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Error parsing {file_path}: {str(e)}")

            # Sort by timestamp (newest first)
            credentials_files.sort(key=lambda x: f"{x['date_str']}{x['time_str']}", reverse=True)

            self.print_colored(Colors.GREEN, f"{Symbols.OK} Found {len(credentials_files)} IAM credentials files")
            return credentials_files

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error scanning IAM credentials files: {str(e)}")
            return []

    def select_credentials_interactive(self, credential_requirements: Dict) -> Dict:
        """
        Interactive credential selection

        Args:
            credential_requirements: Analysis of credential requirements

        Returns:
            Dict: Selected credentials or None if cancelled
        """
        try:
            credentials = {}

            # Handle root credentials if needed
            if credential_requirements['needs_root_creds']:
                self.print_colored(Colors.YELLOW, f"\n[CROWN] Root user credentials required for root-created clusters")

                try:
                    with open('aws_accounts_config.json', 'r') as f:
                        aws_config = json.load(f)

                    credentials['root_accounts'] = aws_config.get('accounts', {})
                    self.print_colored(Colors.GREEN, f"{Symbols.OK} Loaded root account credentials from aws_accounts_config.json")

                except Exception as e:
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to load root credentials: {str(e)}")
                    return None

            # Handle IAM credentials if needed
            if credential_requirements['needs_iam_creds']:
                self.print_colored(Colors.YELLOW, f"\n👤 IAM user credentials required for IAM-created clusters")

                # Scan and select IAM credentials file
                iam_files = self.scan_iam_credentials_files()

                if not iam_files:
                    self.print_colored(Colors.RED, "[ERROR] No IAM credentials files found")
                    return None

                selected_iam_file = self.select_iam_credentials_file_interactive(iam_files)
                if not selected_iam_file:
                    return None

                credentials['iam_users'] = selected_iam_file['data']
                credentials['iam_file_info'] = selected_iam_file

            return credentials

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error in credential selection: {str(e)}")
            return None

    def select_iam_credentials_file_interactive(self, iam_files: List[Dict]) -> Dict:
        """
        Interactive IAM credentials file selection

        Args:
            iam_files: List of IAM credentials files

        Returns:
            Dict: Selected IAM credentials file or None if cancelled
        """
        try:
            self.print_colored(Colors.YELLOW, f"\n[OPENFOLDER] Available IAM credentials files (sorted by timestamp):")
            self.print_colored(Colors.YELLOW, f"=" * 80)

            for i, file_info in enumerate(iam_files, 1):
                timestamp = file_info['timestamp']
                created_by = file_info['created_by']
                total_users = file_info['total_users']
                filename = file_info['filename']

                # Mark latest as default
                default_marker = " (LATEST - DEFAULT)" if i == 1 else ""

                self.print_colored(Colors.CYAN, f"   {i}. {timestamp} - {filename}")
                self.print_colored(Colors.WHITE,
                                   f"      Created by: {created_by}, Total users: {total_users}{default_marker}")

            self.print_colored(Colors.YELLOW, f"=" * 80)

            while True:
                try:
                    choice = input(
                        f"Select IAM credentials file (1-{len(iam_files)}) [default: 1 (latest)] or 'q' to quit: ").strip()

                    if choice.lower() == 'q':
                        self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Operation cancelled by user")
                        return None

                    if not choice:
                        choice = "1"  # Default to latest

                    choice_num = int(choice)
                    if 1 <= choice_num <= len(iam_files):
                        selected_file = iam_files[choice_num - 1]
                        self.print_colored(Colors.GREEN,
                                           f"{Symbols.OK} Selected: {selected_file['filename']} ({selected_file['timestamp']})")
                        return selected_file
                    else:
                        self.print_colored(Colors.RED, f"{Symbols.ERROR} Invalid choice. Please enter 1-{len(iam_files)}")

                except ValueError:
                    self.print_colored(Colors.RED, "[ERROR] Invalid input. Please enter a number")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error in IAM file selection: {str(e)}")
            return None

    def get_credentials_for_cluster(self, cluster_info: Dict, credentials: Dict) -> Tuple[str, str, str]:
        """
        Get appropriate credentials for a specific cluster

        Args:
            cluster_info: Cluster information
            credentials: Available credentials

        Returns:
            Tuple[str, str, str]: (access_key, secret_key, account_id) or (None, None, None) if not found
        """
        try:
            cluster_name = cluster_info['cluster_name']
            account_name = self.extract_account_from_cluster_name(cluster_name)

            if not account_name:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Could not extract account from cluster name: {cluster_name}")
                return None, None, None

            if self.is_root_created_cluster(cluster_name):
                # Use root credentials
                if 'root_accounts' not in credentials:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Root credentials not available for {cluster_name}")
                    return None, None, None

                account_config = credentials['root_accounts'].get(account_name)
                if not account_config:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Root account {account_name} not found")
                    return None, None, None

                return (
                    account_config.get('access_key'),
                    account_config.get('secret_key'),
                    account_config.get('account_id')
                )

            else:
                # Use IAM user credentials
                if 'iam_users' not in credentials:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} IAM credentials not available for {cluster_name}")
                    return None, None, None

                # Extract IAM username from cluster name
                iam_username = self.extract_iam_user_from_cluster_name(cluster_name)
                if not iam_username:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Could not extract IAM username from: {cluster_name}")
                    return None, None, None

                # Find user in IAM credentials
                iam_data = credentials['iam_users']
                accounts = iam_data.get('accounts', {})

                for account_id, account_info in accounts.items():
                    users = account_info.get('users', [])
                    for user in users:
                        if user.get('username') == iam_username:
                            return (
                                user.get('access_key_id'),
                                user.get('secret_access_key'),
                                account_info.get('account_id')
                            )

                self.print_colored(Colors.RED, f"   {Symbols.ERROR} IAM user {iam_username} not found in credentials")
                return None, None, None

        except Exception as e:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error getting credentials for cluster: {str(e)}")
            return None, None, None

    def delete_autoscalers_with_smart_credentials(self, selected_clusters: List[Dict], credentials: Dict) -> bool:
        """
        Delete autoscalers from selected clusters using smart credential selection

        Args:
            selected_clusters: List of selected cluster information
            credentials: Available credentials

        Returns:
            bool: True if all operations completed
        """
        try:
            self.print_colored(Colors.YELLOW,
                               f"\n{Symbols.DELETE}  Starting smart autoscaler deletion for {len(selected_clusters)} clusters")

            # Final confirmation
            confirm = input(
                f"\nConfirm deletion of autoscaler from {len(selected_clusters)} clusters? (y/N): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Operation cancelled by user")
                return False

            # Process each selected cluster
            successful_deletions = []
            failed_deletions = []

            for i, cluster_info in enumerate(selected_clusters, 1):
                cluster_name = cluster_info['cluster_name']
                region = cluster_info['region']

                self.print_colored(Colors.YELLOW, f"\n[{i}/{len(selected_clusters)}] Processing: {cluster_name}")

                # Determine cluster type
                is_root = self.is_root_created_cluster(cluster_name)
                cluster_type = "Root User" if is_root else "IAM User"
                self.print_colored(Colors.CYAN, f"   [ROUNDPIN] Type: {cluster_type}, Region: {region}")

                try:
                    # Get appropriate credentials
                    access_key, secret_key, account_id = self.get_credentials_for_cluster(cluster_info, credentials)

                    if not access_key or not secret_key:
                        self.print_colored(Colors.RED, f"   {Symbols.ERROR} Missing credentials for {cluster_name}")
                        failed_deletions.append(cluster_name)
                        continue

                    # Delete cluster autoscaler
                    success = self.delete_cluster_autoscaler(cluster_name, region, access_key, secret_key)

                    if success:
                        successful_deletions.append(cluster_name)
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Successfully deleted autoscaler from {cluster_name}")
                    else:
                        failed_deletions.append(cluster_name)
                        self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to delete autoscaler from {cluster_name}")

                except Exception as e:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error processing {cluster_name}: {str(e)}")
                    failed_deletions.append(cluster_name)

            # Print final summary
            self.print_summary("SMART AUTOSCALER DELETION", successful_deletions, failed_deletions,
                               len(selected_clusters))

            return len(successful_deletions) > 0

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error during smart autoscaler deletion: {str(e)}")
            return False

    def configure_auth_with_smart_credentials(self, selected_clusters: List[Dict], credentials: Dict) -> bool:
        """
        Configure user authentication for selected clusters using smart credential selection - SIMPLIFIED
        """
        try:
            self.print_colored(Colors.YELLOW,
                               f"\n{Symbols.KEY} Starting ConfigMap-only authentication configuration for {len(selected_clusters)} clusters")
            self.print_colored(Colors.YELLOW, f"Mode: ConfigMap updates only (no access entries)")

            # Final confirmation
            confirm = input(
                f"\nConfirm user authentication configuration for {len(selected_clusters)} clusters? (y/N): ").strip().lower()
            if confirm not in ['y', 'yes']:
                self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Operation cancelled by user")
                return False

            # Process each selected cluster
            successful_configs = []
            failed_configs = []

            for i, cluster_info in enumerate(selected_clusters, 1):
                cluster_name = cluster_info['cluster_name']
                region = cluster_info['region']
                cluster_data = cluster_info['cluster_data']

                self.print_colored(Colors.YELLOW, f"\n[{i}/{len(selected_clusters)}] Processing: {cluster_name}")

                # Determine cluster type
                is_root = self.is_root_created_cluster(cluster_name)
                cluster_type = "Root User" if is_root else "IAM User"
                self.print_colored(Colors.CYAN, f"   [ROUNDPIN] Type: {cluster_type}, Region: {region}")

                try:
                    # Get appropriate credentials
                    access_key, secret_key, account_id = self.get_credentials_for_cluster(cluster_info, credentials)

                    if not access_key or not secret_key or not account_id:
                        self.print_colored(Colors.RED, f"   {Symbols.ERROR} Missing credentials for {cluster_name}")
                        failed_configs.append(cluster_name)
                        continue

                    # Extract user data from cluster data
                    user_data = self.extract_user_data_from_cluster(cluster_data, cluster_name)

                    # Configure auth for cluster - SIMPLIFIED VERSION
                    success = self.configure_aws_auth_configmap_simplified(
                        cluster_name, region, account_id, user_data, access_key, secret_key, is_root
                    )

                    if success:
                        successful_configs.append(cluster_name)
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Successfully configured auth for {cluster_name}")
                    else:
                        failed_configs.append(cluster_name)
                        self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to configure auth for {cluster_name}")

                except Exception as e:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error processing {cluster_name}: {str(e)}")
                    failed_configs.append(cluster_name)

            # Print final summary
            self.print_summary("CONFIGMAP-ONLY USER AUTHENTICATION", successful_configs, failed_configs,
                               len(selected_clusters))

            return len(successful_configs) > 0

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error during ConfigMap-only auth configuration: {str(e)}")
            return False

    def extract_user_data_from_cluster(self, cluster_data: Dict, cluster_name: str) -> Dict:
        """
        Extract user data from cluster information with enhanced detection

        Args:
            cluster_data: Cluster data from JSON file
            cluster_name: Cluster name for additional extraction

        Returns:
            Dict: User data for auth configuration
        """
        try:
            account_info = cluster_data.get('account_info', {})

            # Try to extract username from cluster name if not in data
            username = account_info.get('user_name', 'unknown')

            if username == 'unknown' and not self.is_root_created_cluster(cluster_name):
                # Extract from IAM cluster name
                extracted_username = self.extract_iam_user_from_cluster_name(cluster_name)
                if extracted_username:
                    username = extracted_username

            return {
                'username': username,
                'email': account_info.get('email', ''),
                'access_key_id': '',  # Not stored in cluster files for security
                'secret_access_key': ''  # Not stored in cluster files for security
            }

        except Exception as e:
            self.log_operation('ERROR', f"Error extracting user data: {str(e)}")
            return {
                'username': 'unknown',
                'email': '',
                'access_key_id': '',
                'secret_access_key': ''
            }

    def configure_aws_auth_configmap_simplified(self, cluster_name: str, region: str, account_id: str, user_data: Dict,
                                                admin_access_key: str, admin_secret_key: str,
                                                is_root_cluster: bool) -> bool:
        """
        Simplified configure aws-auth ConfigMap - ONLY ConfigMap updates, no access entries
        """
        try:
            self.log_operation('INFO', f"Configuring aws-auth ConfigMap for cluster {cluster_name}")
            self.print_colored(Colors.CYAN, f"   [LOCKED] Configuring aws-auth ConfigMap (ConfigMap only)...")

            # Prepare user entries based on cluster creator type (from naming pattern)
            users_to_add = []

            if is_root_cluster:
                # If created by root user, only add root user access
                root_arn = f"arn:aws:iam::{account_id}:root"
                users_to_add.append({
                    'userarn': root_arn,
                    'username': 'root-user',
                    'groups': ['system:masters']
                })

                self.print_colored(Colors.CYAN, f"   [CROWN] Root-created cluster - configuring root access only")

            else:
                # If created by IAM user, add both IAM user and root user access
                username = user_data.get('username', 'unknown')
                user_arn = f"arn:aws:iam::{account_id}:user/{username}"
                root_arn = f"arn:aws:iam::{account_id}:root"

                users_to_add.extend([
                    {
                        'userarn': user_arn,
                        'username': username,
                        'groups': ['system:masters']
                    },
                    {
                        'userarn': root_arn,
                        'username': 'root-user',
                        'groups': ['system:masters']
                    }
                ])

                self.print_colored(Colors.CYAN,
                                   f"   👤 IAM-created cluster: {username} - configuring IAM user + root access")

            # Apply ConfigMap directly
            return self.apply_configmap_only(cluster_name, region, account_id, users_to_add, admin_access_key,
                                             admin_secret_key, is_root_cluster, user_data)

        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to configure aws-auth ConfigMap for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} ConfigMap configuration failed: {error_msg}")
            return False

    def apply_configmap_only(self, cluster_name: str, region: str, account_id: str, users_to_add: List[Dict],
                             admin_access_key: str, admin_secret_key: str, is_root_cluster: bool,
                             user_data: Dict) -> bool:
        """
        Apply ONLY ConfigMap using kubectl - IMPROVED VERIFICATION
        """
        try:
            self.print_colored(Colors.CYAN, "   [LIST] Creating/updating aws-auth ConfigMap (ConfigMap only mode)...")

            # Check if kubectl is available
            kubectl_available = shutil.which('kubectl') is not None

            if not kubectl_available:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl not found. ConfigMap setup failed.")
                return False

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
                    'mapUsers': yaml.dump(users_to_add, default_flow_style=False)
                }
            }

            # Save ConfigMap YAML
            temp_dir = tempfile.gettempdir()
            configmap_file = os.path.join(temp_dir, f"aws-auth-{cluster_name}-{self.execution_timestamp}.yaml")

            try:
                with open(configmap_file, 'w') as f:
                    yaml.dump(aws_auth_config, f)
                self.log_operation('INFO', f"Created ConfigMap file: {configmap_file}")
            except Exception as e:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to create ConfigMap file: {str(e)}")
                return False

            # Apply ConfigMap with kubectl
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region

            try:
                # Update kubeconfig (fixed - no invalid flags)
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]

                self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Updating kubeconfig...")
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)

                if update_result.returncode != 0:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to update kubeconfig: {update_result.stderr}")
                    return False

                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Kubeconfig updated successfully")

                # Apply ConfigMap with multiple strategies
                success = False
                applied_method = ""

                # Strategy 1: Standard apply
                self.print_colored(Colors.CYAN, f"   {Symbols.LIST} Applying ConfigMap (standard apply)...")
                apply_cmd = ['kubectl', 'apply', '-f', configmap_file, '--validate=false']
                apply_result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=300)

                if apply_result.returncode == 0:
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap applied successfully")
                    success = True
                    applied_method = "standard apply"
                else:
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Standard apply failed: {apply_result.stderr.strip()}")

                    # Strategy 2: Force replace
                    self.print_colored(Colors.CYAN, f"   {Symbols.LIST} Trying force replace...")
                    replace_cmd = ['kubectl', 'replace', '-f', configmap_file, '--validate=false', '--force']
                    replace_result = subprocess.run(replace_cmd, env=env, capture_output=True, text=True, timeout=300)

                    if replace_result.returncode == 0:
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap replaced successfully")
                        success = True
                        applied_method = "force replace"
                    else:
                        self.print_colored(Colors.YELLOW,
                                           f"   {Symbols.WARN}  Force replace failed: {replace_result.stderr.strip()}")

                        # Strategy 3: Delete and recreate
                        self.print_colored(Colors.CYAN, f"   {Symbols.LIST} Trying delete and recreate...")

                        # Delete existing ConfigMap
                        delete_cmd = ['kubectl', 'delete', 'configmap', 'aws-auth', '-n', 'kube-system',
                                      '--ignore-not-found']
                        delete_result = subprocess.run(delete_cmd, env=env, capture_output=True, text=True, timeout=90)

                        if delete_result.returncode == 0:
                            self.print_colored(Colors.CYAN, f"   {Symbols.DELETE}  Existing ConfigMap deleted")

                        # Wait for deletion to complete
                        time.sleep(3)

                        # Create new ConfigMap
                        create_cmd = ['kubectl', 'create', '-f', configmap_file, '--validate=false']
                        create_result = subprocess.run(create_cmd, env=env, capture_output=True, text=True, timeout=300)

                        if create_result.returncode == 0:
                            self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap recreated successfully")
                            success = True
                            applied_method = "delete and recreate"
                        else:
                            self.print_colored(Colors.RED,
                                               f"   {Symbols.ERROR} All ConfigMap strategies failed: {create_result.stderr}")

                # IMPROVED VERIFICATION with multiple methods
                if success:
                    self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Verifying ConfigMap (applied via {applied_method})...")
                    verification_passed = False

                    # Method 1: Simple existence check
                    try:
                        verify_cmd1 = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system']
                        verify_result1 = subprocess.run(verify_cmd1, env=env, capture_output=True, text=True,
                                                        timeout=30)

                        if verify_result1.returncode == 0:
                            self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap exists and is accessible")
                            verification_passed = True
                        else:
                            self.log_operation('DEBUG', f"Method 1 verification failed: {verify_result1.stderr}")
                    except Exception as e1:
                        self.log_operation('DEBUG', f"Method 1 verification error: {str(e1)}")

                    # Method 2: List all configmaps and check
                    if not verification_passed:
                        try:
                            verify_cmd2 = ['kubectl', 'get', 'configmaps', '-n', 'kube-system', '--no-headers']
                            verify_result2 = subprocess.run(verify_cmd2, env=env, capture_output=True, text=True,
                                                            timeout=30)

                            if verify_result2.returncode == 0 and 'aws-auth' in verify_result2.stdout:
                                self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap found in namespace listing")
                                verification_passed = True
                            else:
                                self.log_operation('DEBUG', f"Method 2 verification failed or aws-auth not found")
                        except Exception as e2:
                            self.log_operation('DEBUG', f"Method 2 verification error: {str(e2)}")

                    # Method 3: Check ConfigMap content
                    if verification_passed:
                        try:
                            content_cmd = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system', '-o',
                                           'jsonpath={.data.mapUsers}']
                            content_result = subprocess.run(content_cmd, env=env, capture_output=True, text=True,
                                                            timeout=30)

                            if content_result.returncode == 0 and content_result.stdout.strip():
                                users_yaml = content_result.stdout.strip()
                                try:
                                    users_list = yaml.safe_load(users_yaml)
                                    user_count = len(users_list) if isinstance(users_list, list) else 0
                                    self.print_colored(Colors.GREEN,
                                                       f"   {Symbols.OK} ConfigMap contains {user_count} user mappings")

                                    # Show the users for confirmation
                                    self.print_colored(Colors.CYAN, f"   {Symbols.LIST} Configured user mappings:")
                                    for user in users_list[:3]:  # Show first 3 users
                                        username = user.get('username', 'unknown')
                                        userarn = user.get('userarn', 'unknown')
                                        # Truncate long ARNs for readability
                                        if len(userarn) > 60:
                                            userarn = userarn[:30] + "..." + userarn[-30:]
                                        self.print_colored(Colors.WHITE, f"      - {username}")

                                    if len(users_list) > 3:
                                        self.print_colored(Colors.WHITE,
                                                           f"      ... and {len(users_list) - 3} more users")

                                except Exception as parse_e:
                                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap contains user mappings")
                                    self.log_operation('DEBUG', f"User mapping parse error: {str(parse_e)}")
                            else:
                                self.print_colored(Colors.YELLOW,
                                                   f"   {Symbols.WARN}  ConfigMap exists but content verification failed")

                        except Exception as content_e:
                            self.print_colored(Colors.YELLOW,
                                               f"   {Symbols.WARN}  Could not verify ConfigMap content: {str(content_e)}")

                    # Final verification status
                    if verification_passed:
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap verification completed successfully")
                    else:
                        self.print_colored(Colors.YELLOW,
                                           f"   {Symbols.WARN}  ConfigMap was applied but verification had issues (this is often normal)")
                        self.print_colored(Colors.CYAN,
                                           f"   {Symbols.TIP} You can manually verify with: kubectl get configmap aws-auth -n kube-system")

                    # Success message
                    if is_root_cluster:
                        self.print_colored(Colors.GREEN,
                                           f"   {Symbols.OK} Root user configured for cluster access (ConfigMap only)")
                    else:
                        username = user_data.get('username', 'unknown')
                        self.print_colored(Colors.GREEN,
                                           f"   {Symbols.OK} User [{username}] and root user configured for cluster access (ConfigMap only)")

                    # Show useful commands
                    self.print_colored(Colors.CYAN, f"   {Symbols.TIP} Test access with:")
                    self.print_colored(Colors.WHITE, f"      kubectl get nodes")
                    self.print_colored(Colors.WHITE, f"      kubectl get pods --all-namespaces")

                    return True
                else:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} All ConfigMap application strategies failed")
                    return False

            except subprocess.TimeoutExpired:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl/aws command timed out")
                return False
            except Exception as e:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Command execution failed: {str(e)}")
                return False

            finally:
                # Clean up temporary files
                try:
                    if os.path.exists(configmap_file):
                        os.remove(configmap_file)
                        self.log_operation('INFO', f"Cleaned up temporary ConfigMap file")
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to clean up ConfigMap file: {str(e)}")

        except Exception as e:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} ConfigMap application failed: {str(e)}")
            return False

    def configure_aws_auth_configmap_enhanced(self, cluster_name: str, region: str, account_id: str, user_data: Dict,
                                              admin_access_key: str, admin_secret_key: str,
                                              is_root_cluster: bool) -> bool:
        """
        Enhanced configure aws-auth ConfigMap with better root/IAM detection
        """
        try:
            self.log_operation('INFO', f"Configuring aws-auth ConfigMap for cluster {cluster_name}")
            self.print_colored(Colors.CYAN, f"   [LOCKED] Configuring aws-auth ConfigMap...")

            # Create admin session for configuring the cluster
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            eks_client = admin_session.client('eks')

            # Get cluster details
            cluster_info = eks_client.describe_cluster(name=cluster_name)

            # Prepare user entries based on cluster creator type (from naming pattern)
            users_to_add = []
            principals_to_add = []

            if is_root_cluster:
                # If created by root user, only add root user access
                root_arn = f"arn:aws:iam::{account_id}:root"
                users_to_add.append({
                    'userarn': root_arn,
                    'username': 'root-user',
                    'groups': ['system:masters']
                })
                principals_to_add.append(root_arn)

                self.print_colored(Colors.CYAN, f"   [CROWN] Root-created cluster - configuring root access only")

            else:
                # If created by IAM user, add both IAM user and root user access
                username = user_data.get('username', 'unknown')
                user_arn = f"arn:aws:iam::{account_id}:user/{username}"
                root_arn = f"arn:aws:iam::{account_id}:root"

                users_to_add.extend([
                    {
                        'userarn': user_arn,
                        'username': username,
                        'groups': ['system:masters']
                    },
                    {
                        'userarn': root_arn,
                        'username': 'root-user',
                        'groups': ['system:masters']
                    }
                ])
                principals_to_add.extend([user_arn, root_arn])

                self.print_colored(Colors.CYAN,
                                   f"   👤 IAM-created cluster: {username} - configuring IAM user + root access")

            # Check cluster authentication mode
            access_config = cluster_info['cluster'].get('accessConfig', {})
            auth_mode = access_config.get('authenticationMode', 'CONFIG_MAP')

            self.print_colored(Colors.CYAN, f"   {Symbols.LIST} Cluster authentication mode: {auth_mode}")

            # If cluster supports API mode, create access entries
            if auth_mode in ['API', 'API_AND_CONFIG_MAP']:
                self.print_colored(Colors.CYAN, f"   {Symbols.KEY} Creating access entries for API-based authentication...")

                success_count = 0
                for principal_arn in principals_to_add:
                    try:
                        # Determine principal type for logging
                        principal_type = "root user" if "root" in principal_arn else f"IAM user ({user_data.get('username', 'unknown')})"

                        # Create access entry
                        eks_client.create_access_entry(
                            clusterName=cluster_name,
                            principalArn=principal_arn,
                            type='STANDARD'
                        )

                        # Associate admin policy
                        eks_client.associate_access_policy(
                            clusterName=cluster_name,
                            principalArn=principal_arn,
                            policyArn='arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy',
                            accessScope={'type': 'cluster'}
                        )

                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Created access entry for {principal_type}")
                        success_count += 1

                    except Exception as e:
                        if "already exists" in str(e).lower():
                            self.print_colored(Colors.CYAN, f"   {Symbols.INFO}  Access entry already exists for {principal_type}")
                            success_count += 1
                        else:
                            self.print_colored(Colors.YELLOW,
                                               f"   {Symbols.WARN}  Failed to create access entry for {principal_type}: {str(e)}")

                # If API mode worked, we don't need ConfigMap
                if success_count > 0:
                    if is_root_cluster:
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Root user configured for cluster access via API")
                    else:
                        username = user_data.get('username', 'unknown')
                        self.print_colored(Colors.GREEN,
                                           f"   {Symbols.OK} User [{username}] and root user configured for cluster access via API")

                    return True

            # If cluster uses CONFIG_MAP mode or API mode failed, create/update aws-auth ConfigMap
            if auth_mode in ['CONFIG_MAP', 'API_AND_CONFIG_MAP']:
                return self.apply_configmap_with_kubectl(cluster_name, region, account_id, users_to_add,
                                                         admin_access_key, admin_secret_key, is_root_cluster, user_data)
            else:
                return True  # If only API mode, access entries are sufficient

        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to configure aws-auth ConfigMap for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} ConfigMap configuration failed: {error_msg}")
            return False

    def apply_configmap_with_kubectl(self, cluster_name: str, region: str, account_id: str, users_to_add: List[Dict],
                                     admin_access_key: str, admin_secret_key: str, is_root_cluster: bool,
                                     user_data: Dict) -> bool:
        """
        Apply ConfigMap using kubectl with enhanced error handling - FIXED VERSION
        """
        try:
            self.print_colored(Colors.CYAN, "   [LIST] Creating/updating aws-auth ConfigMap...")

            # Check if kubectl is available
            kubectl_available = shutil.which('kubectl') is not None

            if not kubectl_available:
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  kubectl not found. ConfigMap setup skipped.")
                return True

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
                    'mapUsers': yaml.dump(users_to_add, default_flow_style=False)
                }
            }

            # Save ConfigMap YAML
            temp_dir = tempfile.gettempdir()
            configmap_file = os.path.join(temp_dir, f"aws-auth-{cluster_name}-{self.execution_timestamp}.yaml")

            try:
                with open(configmap_file, 'w') as f:
                    yaml.dump(aws_auth_config, f)
                self.log_operation('INFO', f"Created ConfigMap file: {configmap_file}")
            except Exception as e:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to create ConfigMap file: {str(e)}")
                return False

            # Apply ConfigMap with enhanced error handling
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region

            try:
                # Update kubeconfig - FIXED: Removed invalid --overwrite-existing flag
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]

                self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Updating kubeconfig...")
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)

                if update_result.returncode != 0:
                    self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to update kubeconfig: {update_result.stderr}")
                    return False

                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Kubeconfig updated successfully")

                # Test cluster connectivity before applying ConfigMap
                self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Testing cluster connectivity...")
                test_cmd = ['kubectl', 'get', 'namespaces', '--timeout=30s']
                test_result = subprocess.run(test_cmd, env=env, capture_output=True, text=True, timeout=60)

                if test_result.returncode != 0:
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Cluster connectivity test failed: {test_result.stderr}")
                    self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Attempting to authenticate with current credentials...")

                    # Try to create a temporary access entry for the current admin user
                    try:
                        admin_session = boto3.Session(
                            aws_access_key_id=admin_access_key,
                            aws_secret_access_key=admin_secret_key,
                            region_name=region
                        )

                        sts_client = admin_session.client('sts')
                        eks_client = admin_session.client('eks')

                        # Get current user identity
                        caller_identity = sts_client.get_caller_identity()
                        caller_arn = caller_identity.get('Arn', '')

                        if caller_arn:
                            self.print_colored(Colors.CYAN,
                                               f"   [LOCKED] Creating temporary access entry for admin: {caller_arn}")

                            # Create access entry for admin
                            try:
                                eks_client.create_access_entry(
                                    clusterName=cluster_name,
                                    principalArn=caller_arn,
                                    type='STANDARD'
                                )

                                eks_client.associate_access_policy(
                                    clusterName=cluster_name,
                                    principalArn=caller_arn,
                                    policyArn='arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy',
                                    accessScope={'type': 'cluster'}
                                )

                                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Temporary admin access entry created")

                                # Wait for access to propagate
                                time.sleep(10)

                                # Test connectivity again
                                test_result2 = subprocess.run(test_cmd, env=env, capture_output=True, text=True,
                                                              timeout=60)
                                if test_result2.returncode == 0:
                                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster connectivity established")
                                else:
                                    self.print_colored(Colors.YELLOW,
                                                       f"   {Symbols.WARN}  Still having connectivity issues, proceeding anyway...")

                            except Exception as access_e:
                                if "already exists" in str(access_e).lower():
                                    self.print_colored(Colors.CYAN, f"   {Symbols.INFO}  Admin access entry already exists")
                                else:
                                    self.print_colored(Colors.YELLOW,
                                                       f"   {Symbols.WARN}  Could not create admin access entry: {str(access_e)}")

                    except Exception as auth_e:
                        self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Authentication setup failed: {str(auth_e)}")
                else:
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} Cluster connectivity confirmed")

                # Apply ConfigMap with multiple fallback strategies
                apply_strategies = [
                    {
                        'name': 'Standard Apply',
                        'cmd': ['kubectl', 'apply', '-f', configmap_file, '--validate=false']
                    },
                    {
                        'name': 'Force Replace',
                        'cmd': ['kubectl', 'replace', '-f', configmap_file, '--validate=false', '--force']
                    },
                    {
                        'name': 'Create (ignore conflicts)',
                        'cmd': ['kubectl', 'create', '-f', configmap_file, '--validate=false', '--save-config']
                    }
                ]

                success = False
                for i, strategy in enumerate(apply_strategies, 1):
                    self.print_colored(Colors.CYAN,
                                       f"   {Symbols.LIST} Applying ConfigMap using strategy {i}: {strategy['name']}...")

                    result = subprocess.run(strategy['cmd'], env=env, capture_output=True, text=True, timeout=300)

                    if result.returncode == 0:
                        self.print_colored(Colors.GREEN,
                                           f"   {Symbols.OK} ConfigMap applied successfully using {strategy['name']}")
                        success = True
                        break
                    else:
                        self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  {strategy['name']} failed: {result.stderr.strip()}")
                        # Continue to next strategy

                # If all standard strategies failed, try delete and recreate
                if not success:
                    self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Trying delete and recreate strategy...")

                    try:
                        # Delete existing ConfigMap (ignore errors)
                        delete_cmd = ['kubectl', 'delete', 'configmap', 'aws-auth', '-n', 'kube-system',
                                      '--ignore-not-found', '--timeout=60s']
                        delete_result = subprocess.run(delete_cmd, env=env, capture_output=True, text=True, timeout=90)

                        if delete_result.returncode == 0:
                            self.print_colored(Colors.CYAN, f"   {Symbols.DELETE}  Existing ConfigMap deleted")
                        else:
                            self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Delete result: {delete_result.stderr}")

                        # Wait a moment for deletion to complete
                        time.sleep(5)

                        # Create new ConfigMap
                        create_cmd = ['kubectl', 'create', '-f', configmap_file, '--validate=false']
                        create_result = subprocess.run(create_cmd, env=env, capture_output=True, text=True, timeout=300)

                        if create_result.returncode == 0:
                            self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap recreated successfully")
                            success = True
                        else:
                            self.print_colored(Colors.RED, f"   {Symbols.ERROR} ConfigMap recreation failed: {create_result.stderr}")

                            # Last resort: try server-side apply (kubectl 1.18+)
                            self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Trying server-side apply as last resort...")

                            server_side_cmd = ['kubectl', 'apply', '-f', configmap_file, '--server-side',
                                               '--validate=false', '--force-conflicts']
                            server_side_result = subprocess.run(server_side_cmd, env=env, capture_output=True,
                                                                text=True, timeout=300)

                            if server_side_result.returncode == 0:
                                self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap applied using server-side apply")
                                success = True
                            else:
                                self.print_colored(Colors.RED,
                                                   f"   {Symbols.ERROR} Server-side apply also failed: {server_side_result.stderr}")

                    except Exception as recreate_e:
                        self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error during recreate strategy: {str(recreate_e)}")

                # Verify ConfigMap was applied (but don't fail if verification fails)
                if success:
                    try:
                        self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Verifying ConfigMap...")
                        verify_cmd = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system', '-o', 'name',
                                      '--timeout=30s']
                        verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=60)

                        if verify_result.returncode == 0 and 'aws-auth' in verify_result.stdout:
                            self.print_colored(Colors.GREEN, f"   {Symbols.OK} ConfigMap verification successful")

                            # Show ConfigMap content summary
                            content_cmd = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system', '-o', 'yaml']
                            content_result = subprocess.run(content_cmd, env=env, capture_output=True, text=True,
                                                            timeout=60)

                            if content_result.returncode == 0:
                                # Count users in ConfigMap
                                try:
                                    import yaml as yaml_parser
                                    configmap_content = yaml_parser.safe_load(content_result.stdout)
                                    map_users = configmap_content.get('data', {}).get('mapUsers', '')
                                    if map_users:
                                        users_list = yaml_parser.safe_load(map_users)
                                        user_count = len(users_list) if isinstance(users_list, list) else 0
                                        self.print_colored(Colors.GREEN,
                                                           f"   {Symbols.OK} ConfigMap contains {user_count} user mappings")
                                    else:
                                        self.print_colored(Colors.YELLOW,
                                                           f"   {Symbols.WARN}  ConfigMap exists but no user mappings found")
                                except Exception as parse_e:
                                    self.print_colored(Colors.YELLOW,
                                                       f"   {Symbols.WARN}  Could not parse ConfigMap content: {str(parse_e)}")

                        else:
                            self.print_colored(Colors.YELLOW,
                                               f"   {Symbols.WARN}  ConfigMap verification failed, but apply reported success")

                    except Exception as verify_e:
                        self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  ConfigMap verification error: {str(verify_e)}")

                if success:
                    if is_root_cluster:
                        self.print_colored(Colors.GREEN, f"   {Symbols.OK} Root user configured for cluster access")
                    else:
                        username = user_data.get('username', 'unknown')
                        self.print_colored(Colors.GREEN,
                                           f"   {Symbols.OK} User [{username}] and root user configured for cluster access")

                return success

            except subprocess.TimeoutExpired:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl/aws command timed out")
                return False
            except Exception as e:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Command execution failed: {str(e)}")
                return False

            finally:
                # Clean up temporary files
                try:
                    if os.path.exists(configmap_file):
                        os.remove(configmap_file)
                        self.log_operation('INFO', f"Cleaned up temporary ConfigMap file")
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to clean up ConfigMap file: {str(e)}")

        except Exception as e:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} ConfigMap application failed: {str(e)}")
            return False

    # Include all the other methods from the previous class (scan_cluster_files, group_clusters_by_date, etc.)
    # ... (keeping the existing methods for brevity)

    def scan_cluster_files(self) -> List[Dict]:
        """Scan aws/eks/ directories for cluster files"""
        try:
            cluster_files = []
            base_dirs = ["aws/eks/account01", "aws/eks/account02", "aws/eks/account03",
                         "aws/eks/account04", "aws/eks/account05", "aws/eks/account06"]

            self.print_colored(Colors.CYAN, "[SCAN] Scanning for cluster files...")

            for base_dir in base_dirs:
                if not os.path.exists(base_dir):
                    continue

                account_id = base_dir.split('/')[-1]
                pattern = os.path.join(base_dir, "eks_cluster_eks-cluster-*.json")
                files = glob.glob(pattern)

                self.print_colored(Colors.CYAN, f"   {Symbols.FOLDER} {account_id}: Found {len(files)} cluster files")

                for file_path in files:
                    try:
                        file_info = self.parse_cluster_file_info(file_path, account_id)
                        if file_info:
                            cluster_files.append(file_info)
                    except Exception as e:
                        self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  Error parsing {file_path}: {str(e)}")

            self.print_colored(Colors.GREEN, f"{Symbols.OK} Total cluster files found: {len(cluster_files)}")
            return cluster_files

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error scanning cluster files: {str(e)}")
            return []

    def parse_cluster_file_info(self, file_path: str, account_id: str) -> Dict:
        """Parse cluster file to extract relevant information"""
        try:
            filename = os.path.basename(file_path)
            date_match = re.search(r'_(\d{8})_\d{6}\.json$', filename)
            if not date_match:
                return None

            date_str = date_match.group(1)
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

            with open(file_path, 'r') as f:
                cluster_data = json.load(f)

            cluster_name = cluster_data.get('cluster_info', {}).get('cluster_name', 'Unknown')
            region = cluster_data.get('account_info', {}).get('region', 'us-east-1')
            created_by = cluster_data.get('created_by', 'Unknown')
            timestamp = cluster_data.get('timestamp', 'Unknown')
            account_name = cluster_data.get('account_info', {}).get('account_name', account_id)

            return {
                'file_path': file_path,
                'filename': filename,
                'account_id': account_id,
                'account_name': account_name,
                'cluster_name': cluster_name,
                'region': region,
                'date': formatted_date,
                'date_raw': date_str,
                'created_by': created_by,
                'timestamp': timestamp,
                'cluster_data': cluster_data
            }

        except Exception as e:
            self.log_operation('ERROR', f"Error parsing cluster file {file_path}: {str(e)}")
            return None

    def group_clusters_by_date(self, cluster_files: List[Dict]) -> Dict:
        """Group cluster files by creation date"""
        try:
            clusters_by_date = {}

            for cluster_file in cluster_files:
                date = cluster_file['date']
                if date not in clusters_by_date:
                    clusters_by_date[date] = []
                clusters_by_date[date].append(cluster_file)

            sorted_dates = sorted(clusters_by_date.keys(), reverse=True)
            sorted_clusters = {date: clusters_by_date[date] for date in sorted_dates}

            return sorted_clusters

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error grouping clusters by date: {str(e)}")
            return {}

    def select_date_interactive(self, clusters_by_date: Dict) -> str:
        """Interactive date selection"""
        try:
            self.print_colored(Colors.YELLOW, f"\n{Symbols.DATE} Available dates with clusters:")
            self.print_colored(Colors.YELLOW, f"=" * 50)

            dates = list(clusters_by_date.keys())

            for i, date in enumerate(dates, 1):
                cluster_count = len(clusters_by_date[date])
                accounts = set(cluster['account_id'] for cluster in clusters_by_date[date])
                account_summary = ', '.join(sorted(accounts))

                self.print_colored(Colors.CYAN, f"   {i}. {date} - {cluster_count} clusters ({account_summary})")

            self.print_colored(Colors.YELLOW, f"=" * 50)

            while True:
                try:
                    choice = input(f"Select date (1-{len(dates)}) or 'q' to quit: ").strip()

                    if choice.lower() == 'q':
                        self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Operation cancelled by user")
                        return None

                    choice_num = int(choice)
                    if 1 <= choice_num <= len(dates):
                        selected_date = dates[choice_num - 1]
                        self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected date: {selected_date}")
                        return selected_date
                    else:
                        self.print_colored(Colors.RED, f"{Symbols.ERROR} Invalid choice. Please enter 1-{len(dates)}")

                except ValueError:
                    self.print_colored(Colors.RED, "[ERROR] Invalid input. Please enter a number")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error in date selection: {str(e)}")
            return None

    def select_clusters_interactive(self, date_clusters: List[Dict], selected_date: str) -> List[Dict]:
        """Interactive cluster selection for a specific date"""
        try:
            self.print_colored(Colors.YELLOW, f"\n{Symbols.TARGET} Clusters available for {selected_date}:")
            self.print_colored(Colors.YELLOW, f"=" * 80)

            for i, cluster in enumerate(date_clusters, 1):
                cluster_name = cluster['cluster_name']
                account_id = cluster['account_id']
                region = cluster['region']
                created_by = cluster['created_by']

                # Detect cluster type
                cluster_type = "[CROWN] Root" if self.is_root_created_cluster(cluster_name) else "👤 IAM"

                self.print_colored(Colors.CYAN, f"   {i:2d}. {cluster_name} {cluster_type}")
                self.print_colored(Colors.WHITE,
                                   f"       Account: {account_id}, Region: {region}, Created by: {created_by}")

            self.print_colored(Colors.YELLOW, f"=" * 80)
            self.print_colored(Colors.YELLOW, f"Selection options:")
            self.print_colored(Colors.WHITE, f"   • Single: 1")
            self.print_colored(Colors.WHITE, f"   • Range: 1-5")
            self.print_colored(Colors.WHITE, f"   • Multiple: 1,3,5")
            self.print_colored(Colors.WHITE, f"   • All: all")
            self.print_colored(Colors.WHITE, f"   • Quit: q")

            while True:
                try:
                    selection = input(f"\nSelect clusters: ").strip()

                    if selection.lower() == 'q':
                        self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Operation cancelled by user")
                        return None

                    if selection.lower() == 'all':
                        selected_clusters = date_clusters.copy()
                        self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected all {len(selected_clusters)} clusters")
                        return selected_clusters

                    selected_indices = self.parse_cluster_selection(selection, len(date_clusters))

                    if not selected_indices:
                        self.print_colored(Colors.RED, "[ERROR] Invalid selection. Please try again.")
                        continue

                    selected_clusters = [date_clusters[i - 1] for i in selected_indices]

                    self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected {len(selected_clusters)} clusters:")
                    for cluster in selected_clusters:
                        cluster_type = "[CROWN] Root" if self.is_root_created_cluster(cluster['cluster_name']) else "👤 IAM"
                        self.print_colored(Colors.GREEN,
                                           f"   - {cluster['cluster_name']} {cluster_type} ({cluster['account_id']})")

                    return selected_clusters

                except Exception as e:
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Error processing selection: {str(e)}")
                    continue

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error in cluster selection: {str(e)}")
            return None

    def parse_cluster_selection(self, selection: str, max_count: int) -> List[int]:
        """Parse user selection string into list of indices"""
        try:
            selected_indices = []
            parts = [part.strip() for part in selection.split(',')]

            for part in parts:
                if '-' in part:
                    try:
                        start, end = part.split('-', 1)
                        start_idx = int(start.strip())
                        end_idx = int(end.strip())

                        if 1 <= start_idx <= max_count and 1 <= end_idx <= max_count and start_idx <= end_idx:
                            selected_indices.extend(range(start_idx, end_idx + 1))
                        else:
                            return None
                    except ValueError:
                        return None
                else:
                    try:
                        idx = int(part)
                        if 1 <= idx <= max_count:
                            selected_indices.append(idx)
                        else:
                            return None
                    except ValueError:
                        return None

            selected_indices = sorted(list(set(selected_indices)))
            return selected_indices

        except Exception as e:
            self.log_operation('ERROR', f"Error parsing selection '{selection}': {str(e)}")
            return None

    def select_operation_interactive(self) -> str:
        """Interactive operation selection"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SETTINGS]  Select Operation:")
            self.print_colored(Colors.YELLOW, f"=" * 50)
            self.print_colored(Colors.CYAN, f"   1. Delete Cluster Autoscaler")
            self.print_colored(Colors.CYAN, f"   2. Configure User Authentication")
            self.print_colored(Colors.YELLOW, f"=" * 50)

            while True:
                try:
                    choice = input(f"Select operation (1-2) or 'q' to quit: ").strip()

                    if choice.lower() == 'q':
                        self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} Operation cancelled by user")
                        return None

                    if choice == "1":
                        self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected: Delete Cluster Autoscaler")
                        return "delete_autoscaler"
                    elif choice == "2":
                        self.print_colored(Colors.GREEN, f"{Symbols.OK} Selected: Configure User Authentication")
                        return "configure_auth"
                    else:
                        self.print_colored(Colors.RED, f"{Symbols.ERROR} Invalid choice. Please enter 1 or 2")

                except ValueError:
                    self.print_colored(Colors.RED, "[ERROR] Invalid input. Please enter a number")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Error in operation selection: {str(e)}")
            return None

    def delete_cluster_autoscaler(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Delete cluster autoscaler deployment from a specific cluster"""
        try:
            self.log_operation('INFO', f"Deleting cluster autoscaler from {cluster_name}")

            kubectl_available = shutil.which('kubectl') is not None

            if not kubectl_available:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} kubectl not found. Cannot delete autoscaler")
                return False

            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region

            self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Updating kubeconfig for {cluster_name}...")
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]

            update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)

            if update_result.returncode != 0:
                self.print_colored(Colors.RED, f"   {Symbols.ERROR} Failed to update kubeconfig: {update_result.stderr}")
                return False

            self.print_colored(Colors.CYAN, f"   {Symbols.DELETE}  Deleting cluster autoscaler components...")

            delete_commands = [
                ['kubectl', 'delete', 'deployment', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found'],
                ['kubectl', 'delete', 'serviceaccount', 'cluster-autoscaler', '-n', 'kube-system',
                 '--ignore-not-found'],
                ['kubectl', 'delete', 'clusterrole', 'cluster-autoscaler', '--ignore-not-found'],
                ['kubectl', 'delete', 'clusterrolebinding', 'cluster-autoscaler', '--ignore-not-found'],
                ['kubectl', 'delete', 'role', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found'],
                ['kubectl', 'delete', 'rolebinding', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found'],
                ['kubectl', 'delete', 'secret', 'cluster-autoscaler-aws-credentials', '-n', 'kube-system',
                 '--ignore-not-found']
            ]

            deletion_results = []

            for delete_cmd in delete_commands:
                try:
                    result = subprocess.run(delete_cmd, env=env, capture_output=True, text=True, timeout=60)
                    component = delete_cmd[2]

                    if result.returncode == 0:
                        if "deleted" in result.stdout or "not found" in result.stdout:
                            deletion_results.append(f"   {Symbols.OK} {component}")
                        else:
                            deletion_results.append(f"   {Symbols.OK} {component} (already deleted)")
                    else:
                        deletion_results.append(f"   {Symbols.WARN}  {component}: {result.stderr.strip()}")

                except subprocess.TimeoutExpired:
                    deletion_results.append(f"   {Symbols.ERROR} {component}: Timeout")
                except Exception as e:
                    deletion_results.append(f"   {Symbols.ERROR} {component}: {str(e)}")

            success_count = len([r for r in deletion_results if "[OK]" in r])
            total_count = len(deletion_results)

            if success_count == total_count:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} All {total_count} components deleted successfully")
            else:
                self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  {success_count}/{total_count} components deleted")

            self.print_colored(Colors.CYAN, f"   {Symbols.SCAN} Verifying autoscaler deletion...")

            verify_cmd = ['kubectl', 'get', 'pods', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', '--no-headers']
            verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=60)

            if verify_result.returncode == 0:
                remaining_pods = [line.strip() for line in verify_result.stdout.strip().split('\n') if line.strip()]

                if not remaining_pods:
                    self.print_colored(Colors.GREEN, f"   {Symbols.OK} No autoscaler pods found - deletion successful")
                    return True
                else:
                    self.print_colored(Colors.YELLOW, f"   {Symbols.WARN}  {len(remaining_pods)} autoscaler pods still found")
                    return False
            else:
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Deletion commands completed (verification skipped)")
                return True

        except Exception as e:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} Error deleting autoscaler: {str(e)}")
            self.log_operation('ERROR', f"Failed to delete cluster autoscaler from {cluster_name}: {str(e)}")
            return False

    def print_summary(self, operation_name: str, successful: List[str], failed: List[str], total: int):
        """Print operation summary"""
        self.print_colored(Colors.YELLOW, f"\n{Symbols.STATS} {operation_name} SUMMARY")
        self.print_colored(Colors.YELLOW, f"=" * 60)
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Successful: {len(successful)}/{total}")
        self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed: {len(failed)}/{total}")

        if successful:
            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Successfully processed clusters:")
            for cluster in successful:
                self.print_colored(Colors.GREEN, f"   - {cluster}")

        if failed:
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} Failed clusters:")
            for cluster in failed:
                self.print_colored(Colors.RED, f"   - {cluster}")

        self.log_operation('INFO', json.dumps({
            "event": f"enhanced_{operation_name.lower().replace(' ', '_')}_summary",
            "total_clusters": total,
            "successful": len(successful),
            "failed": len(failed),
            "successful_clusters": successful,
            "failed_clusters": failed
        }))


def main():
    """Main method for enhanced interactive cluster management"""

    # Initialize Enhanced Interactive Cluster Manager
    cluster_manager = EnhancedInteractiveClusterManager()

    # Run enhanced interactive management process
    success = cluster_manager.enhanced_interactive_cluster_management()

    if success:
        print("\n[PARTY] Enhanced interactive cluster management completed successfully")
    else:
        print("\n[ERROR] Enhanced interactive cluster management failed or was cancelled")


if __name__ == "__main__":
    main()