#!/usr/bin/env python3
"""
EKS Cluster Continuation Script with Error File Selection
Allows continuation of EKS cluster setup from failed cluster creation logs
"""

import json
import os
import sys
import time
import boto3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import glob
from collections import defaultdict
from eks_cluster_manager import EKSClusterManager
from complete_autoscaler_deployment import CompleteAutoscalerDeployer
import textwrap

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'

class EKSClusterContinuationFromErrors:
    """
    Class for continuing EKS cluster setup by reading from cluster creation error files
    """

    def __init__(self):
        """Initialize the EKS Cluster Continuation manager"""
        self.current_user = 'varadharajaan'
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Setup logging
        self.setup_logging()

        # Initialize EKS manager for reusing existing methods
        self.eks_manager = EKSClusterManager()

        # Cluster state tracking
        self.cluster_info = {}
        self.existing_components = {}

        # Load AWS accounts configuration
        self.aws_accounts_config = self.load_aws_accounts_config()

        # Failed clusters data
        self.failed_clusters_data = {}

    def setup_logging(self):
        """Set up logging for the continuation script"""
        log_dir = "logs/eks_continuation"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_file = os.path.join(log_dir, f"cluster_continuation_{self.execution_timestamp}.log")

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"EKS Cluster Continuation from Error Files initialized - Session ID: {self.execution_timestamp}")

    def print_colored(self, color: str, message: str, indent=0) -> None:
        """Print colored message to terminal"""
        colors = {
            'RED': '\033[0;31m',
            'GREEN': '\033[0;32m',
            'YELLOW': '\033[1;33m',
            'BLUE': '\033[0;34m',
            'PURPLE': '\033[0;35m',
            'CYAN': '\033[0;36m',
            'WHITE': '\033[1;37m',
            'NC': '\033[0m'  # No Color
        }

        color_code = colors.get(color, colors['WHITE'])
        print(f"{color_code}{message}{colors['NC']}")

    def load_aws_accounts_config(self) -> dict:
        """Load AWS accounts configuration from aws_accounts_config.json"""
        try:
            config_file = "aws_accounts_config.json"
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                self.logger.info(f"Loaded AWS accounts configuration from {config_file}")
                return config
            else:
                self.logger.warning(f"AWS accounts config file not found: {config_file}")
                return {}
        except Exception as e:
            self.logger.error(f"Failed to load AWS accounts config: {str(e)}")
            return {}

    def find_error_files(self) -> List[Tuple[str, dict]]:
        """Find all cluster creation error files and parse them"""
        error_files = []

        try:
            # Look for error files in aws/eks/ directory
            error_pattern = "aws/eks/cluster_creation_errors_*.json"
            file_paths = glob.glob(error_pattern)

            if not file_paths:
                self.print_colored('YELLOW', f"⚠️  No error files found matching pattern: {error_pattern}")
                return []

            self.logger.info(f"Found {len(file_paths)} error files")

            for file_path in file_paths:
                try:
                    with open(file_path, 'r') as f:
                        error_data = json.load(f)

                    # Extract timestamp from filename for sorting
                    filename = os.path.basename(file_path)
                    timestamp_part = filename.replace('cluster_creation_errors_', '').replace('.json', '')

                    error_files.append((file_path, error_data, timestamp_part))
                    self.logger.info(f"Loaded error file: {file_path}")

                except Exception as e:
                    self.logger.error(f"Failed to parse error file {file_path}: {str(e)}")
                    continue

            # Sort by timestamp (newest first)
            error_files.sort(key=lambda x: x[2], reverse=True)

            return [(path, data) for path, data, _ in error_files]

        except Exception as e:
            self.logger.error(f"Error finding error files: {str(e)}")
            return []

    def group_clusters_by_date(self, error_files: List[Tuple[str, dict]]) -> Dict[str, List[Dict]]:
        """Group failed clusters by date"""
        clusters_by_date = defaultdict(list)

        for file_path, error_data in error_files:
            try:
                # Parse the timestamp from the error data
                timestamp_str = error_data.get('timestamp', '')
                if timestamp_str:
                    # Parse ISO format timestamp
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    date_key = timestamp.strftime('%Y-%m-%d')
                else:
                    # Fallback to extracting from filename
                    filename = os.path.basename(file_path)
                    timestamp_part = filename.replace('cluster_creation_errors_', '').replace('.json', '')
                    try:
                        timestamp = datetime.strptime(timestamp_part, '%Y%m%d_%H%M%S')
                        date_key = timestamp.strftime('%Y-%m-%d')
                    except:
                        date_key = 'Unknown Date'

                # Extract failed clusters from this file
                failed_clusters = error_data.get('errors', {})
                total_clusters = error_data.get('total_clusters', len(failed_clusters))
                failed_count = error_data.get('failed_clusters', len(failed_clusters))

                for cluster_name, error_msg in failed_clusters.items():
                    cluster_info = {
                        'cluster_name': cluster_name,
                        'error_message': error_msg,
                        'file_path': file_path,
                        'timestamp': timestamp_str,
                        'total_clusters_in_batch': total_clusters,
                        'failed_clusters_in_batch': failed_count
                    }
                    clusters_by_date[date_key].append(cluster_info)

            except Exception as e:
                self.logger.error(f"Error processing error file {file_path}: {str(e)}")
                continue

        return dict(clusters_by_date)

    def display_clusters_by_date(self, clusters_by_date: Dict[str, List[Dict]]) -> None:
        """Display clusters grouped by date"""
        print("\n" + "=" * 80)
        print("📅 FAILED CLUSTERS BY DATE")
        print("=" * 80)

        for date_key in sorted(clusters_by_date.keys(), reverse=True):
            clusters = clusters_by_date[date_key]
            print(f"\n📅 {date_key} ({len(clusters)} failed clusters)")
            print("-" * 60)

            for i, cluster_info in enumerate(clusters, 1):
                cluster_name = cluster_info['cluster_name']
                error_msg = cluster_info['error_message']

                # Extract region from cluster name if possible
                parts = cluster_name.split('-')
                region = 'unknown'
                if len(parts) >= 4:
                    for part in parts:
                        if part.startswith('us-') or part.startswith('eu-') or part.startswith(
                                'ap-') or part.startswith('ca-') or part.startswith('sa-'):
                            region = part
                            break

                print(f"  {i}. {cluster_name}")
                print(f"     Region: {region}")
                print(f"     Error: {error_msg}")
                print(f"     File: {os.path.basename(cluster_info['file_path'])}")
                print()

    def select_date_and_clusters(self, clusters_by_date: Dict[str, List[Dict]]) -> List[Dict]:
        """Allow user to select date and clusters to continue"""
        if not clusters_by_date:
            self.print_colored('RED', "❌ No failed clusters found in error files")
            return []

        # Step 1: Select date
        dates = sorted(clusters_by_date.keys(), reverse=True)

        print("\n" + "=" * 60)
        print("📅 SELECT DATE")
        print("=" * 60)

        for i, date_key in enumerate(dates, 1):
            cluster_count = len(clusters_by_date[date_key])
            print(f"{i}. {date_key} ({cluster_count} failed clusters)")

        print("=" * 60)

        while True:
            try:
                choice = input(f"Select date (1-{len(dates)}): ").strip()
                choice_num = int(choice)
                if 1 <= choice_num <= len(dates):
                    selected_date = dates[choice_num - 1]
                    selected_clusters_pool = clusters_by_date[selected_date]
                    break
                else:
                    self.print_colored('RED', f"❌ Please enter a number between 1 and {len(dates)}")
            except ValueError:
                self.print_colored('RED', "❌ Please enter a valid number")

        self.print_colored('GREEN', f"✅ Selected date: {selected_date} ({len(selected_clusters_pool)} clusters)")

        # Step 2: Select clusters from the chosen date
        print(f"\n" + "=" * 60)
        print(f"🚀 SELECT CLUSTERS FROM {selected_date}")
        print("=" * 60)

        for i, cluster_info in enumerate(selected_clusters_pool, 1):
            cluster_name = cluster_info['cluster_name']
            error_msg = cluster_info['error_message']

            # Extract region from cluster name
            parts = cluster_name.split('-')
            region = 'unknown'
            if len(parts) >= 4:
                for part in parts:
                    if part.startswith('us-') or part.startswith('eu-') or part.startswith('ap-') or part.startswith(
                            'ca-') or part.startswith('sa-'):
                        region = part
                        break

            print(f"{i}. {cluster_name} (Region: {region})")
            print(f"   Error: {error_msg}")

        print("=" * 60)
        print("Selection options:")
        print("• Enter cluster numbers: 1,3,5")
        print("• Enter range: 1-3")
        print("• Enter 'all' for all clusters")
        print("• Combine: 1,3-5,7")
        print("=" * 60)

        while True:
            selection = input("Select clusters: ").strip().lower()

            if not selection:
                self.print_colored('RED', "❌ Please enter a selection")
                continue

            try:
                selected_indices = self.parse_selection(selection, len(selected_clusters_pool))
                if selected_indices:
                    selected_clusters = [selected_clusters_pool[i - 1] for i in selected_indices]

                    # Display selection summary
                    self.print_colored('GREEN', f"\n✅ Selected {len(selected_clusters)} clusters:")
                    for cluster_info in selected_clusters:
                        print(f"   - {cluster_info['cluster_name']}")

                    confirm = input(
                        f"\nConfirm selection of {len(selected_clusters)} clusters? (Y/n): ").strip().lower()
                    if confirm != 'n':
                        return selected_clusters
                else:
                    self.print_colored('RED', "❌ Invalid selection")

            except Exception as e:
                self.print_colored('RED', f"❌ Error parsing selection: {str(e)}")

    def parse_selection(self, selection: str, max_count: int) -> List[int]:
        """Parse user selection string into list of indices"""
        if selection == 'all':
            return list(range(1, max_count + 1))

        indices = set()
        parts = selection.split(',')

        for part in parts:
            part = part.strip()
            if '-' in part:
                # Handle range like "1-3"
                try:
                    start, end = part.split('-')
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())

                    if 1 <= start_idx <= max_count and 1 <= end_idx <= max_count and start_idx <= end_idx:
                        indices.update(range(start_idx, end_idx + 1))
                    else:
                        raise ValueError(f"Invalid range: {part}")
                except ValueError:
                    raise ValueError(f"Invalid range format: {part}")
            else:
                # Handle single number
                try:
                    idx = int(part)
                    if 1 <= idx <= max_count:
                        indices.add(idx)
                    else:
                        raise ValueError(f"Index {idx} out of range (1-{max_count})")
                except ValueError:
                    raise ValueError(f"Invalid number: {part}")

        return sorted(list(indices))

    def extract_cluster_details(self, cluster_info: Dict) -> Tuple[str, str]:
        """
        Extract cluster name and region from cluster info
        Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): 2025-06-25 05:50:39
        Current User's Login: varadharajaan
        """
        import re
        cluster_name = cluster_info['cluster_name']

        # Try to extract region from cluster name using regex pattern
        # Look for AWS region pattern: us-east-1, us-west-1, eu-west-1, ap-south-1, etc.
        region_pattern = r'(us|eu|ap|ca|sa|me|af)-(east|west|north|south|central|northeast|northwest|southeast|southwest)-\d+'

        region_match = re.search(region_pattern, cluster_name)

        if region_match:
            region = region_match.group(0)
            self.print_colored('YELLOW', f"Extracted region '{region}' from cluster name '{cluster_name}'")
        else:
            # Fallback: try to get from cluster_info if available
            region = cluster_info.get('region', 'us-east-1')
            self.print_colored('YELLOW',
                               f"Could not extract region from cluster name '{cluster_name}', using fallback: {region}")

        return cluster_name, region

    def get_credentials_for_cluster(self, cluster_name: str, region: str) -> Tuple[str, str]:
        """Get AWS credentials for the cluster based on cluster name pattern"""
        print(f"\n" + "=" * 60)
        print(f"🔐 CREDENTIALS FOR CLUSTER: {cluster_name}")
        print("=" * 60)

        # Try to determine account type from cluster name
        if 'root-account' in cluster_name.lower() or 'root_account' in cluster_name.lower():
            account_type = 'root'
            self.print_colored('CYAN', "📋 Detected: Root Account (from cluster name)")
        else:
            account_type = 'iam'
            self.print_colored('CYAN', "📋 Detected: IAM User (from cluster name)")

        # Ask user to confirm or override
        print(f"\nAccount type detected: {account_type.upper()}")
        override = input("Override account type? (r for Root, i for IAM, Enter to keep detected): ").strip().lower()

        self.show_account_summary()

        if override == 'r':
            account_type = 'root'
        elif override == 'i':
            account_type = 'iam'

        if account_type == 'root':
            return self.get_root_credentials_from_cluster_legacy(cluster_name=cluster_name)
        else:
            return self.get_iam_credentials_from_cluster_legacy(cluster_name, region)

    def show_account_summary(self):
        """Show summary of all available root accounts"""
        try:
            config = self._load_root_accounts_config()
            accounts = config.get('accounts', {})
            user_settings = config.get('user_settings', {})

            self.print_colored(Colors.BOLD, "=" * 80)
            self.print_colored(Colors.BOLD, "    AWS ROOT ACCOUNTS SUMMARY")
            self.print_colored(Colors.BOLD, "=" * 80)

            total_users = sum(acc.get('users_per_account', 0) for acc in accounts.values())

            self.print_colored(Colors.CYAN, f"📊 Overview:")
            self.print_colored(Colors.WHITE, f"   • Total Accounts: {len(accounts)}", 1)
            self.print_colored(Colors.WHITE, f"   • Total Users: {total_users}", 1)

            if user_settings:
                default_password = user_settings.get('password', 'N/A')
                allowed_instances = user_settings.get('allowed_instance_types', [])
                self.print_colored(Colors.WHITE, f"   • Default Password: {default_password}", 1)
                self.print_colored(Colors.WHITE, f"   • Allowed Instances: {len(allowed_instances)} types", 1)

            self.print_colored(Colors.CYAN, f"\n📋 Accounts:")
            for account_name, account_data in accounts.items():
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                users = account_data.get('users_per_account', 0)

                self.print_colored(Colors.YELLOW, f"• {account_name}")
                self.print_colored(Colors.WHITE, f"  ID: {account_id} | Email: {email} | Users: {users}", 1)

            self.print_colored(Colors.BOLD, "=" * 80)

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Failed to show account summary: {str(e)}")

    def get_iam_credentials(self, username: str = None, account_id: str = None, cluster_name: str = None) -> Tuple[
        str, str, str]:
        """
        Find IAM credentials by username, account ID, or cluster name

        Current Date and Time (UTC): 2025-06-24 15:48:52
        Current User's Login: varadharajaan

        Args:
            username: IAM username to search for (optional)
            account_id: AWS Account ID to filter by (optional) - should be actual account ID, not region
            cluster_name: Cluster name to extract username from (optional)

        Returns:
            Tuple[access_key, secret_key, account_id]: AWS credentials and account ID
        """
        import glob
        import re
        import os
        from datetime import datetime

        try:
            # If cluster_name provided, extract username from it
            if cluster_name and not username:
                username = self._extract_username_from_cluster_name(cluster_name)
                if not username:
                    raise ValueError(f"Could not extract username from cluster name: {cluster_name}")
                self.print_colored(Colors.GREEN, f"🎯 Extracted username from cluster: {username}")

            # If no username provided, show available users and prompt
            if not username:
                print(f"\n🔍 No username provided. Let's find your credentials...")
                self._show_available_users()
                username = input("\n📝 Enter your username: ").strip()

                if not username:
                    raise ValueError("Username is required")

            # Validate account_id is not a region
            if account_id and any(region_part in account_id for region_part in ['us-', 'eu-', 'ap-', 'sa-', 'ca-']):
                self.print_colored(Colors.YELLOW, f"⚠️ Account ID looks like a region ({account_id}), ignoring filter")
                account_id = None

            # Find credential files
            iam_dir = "aws/iam"
            if not os.path.exists(iam_dir):
                raise ValueError(f"IAM directory '{iam_dir}' not found")

            pattern = f"{iam_dir}/iam_users_credentials_*.json"
            credential_files = glob.glob(pattern)

            if not credential_files:
                raise ValueError(f"No IAM credential files found in {iam_dir} matching pattern: {pattern}")

            # Parse and sort files by timestamp
            parsed_files = []
            for file_path in credential_files:
                timestamp_str = self._extract_timestamp_from_filename(file_path)
                if timestamp_str:
                    try:
                        # Parse timestamp from filename (format: YYYYMMDD_HHMMSS)
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        parsed_files.append((file_path, timestamp, timestamp_str))
                    except ValueError:
                        # If timestamp parsing fails, use file modification time
                        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        parsed_files.append((file_path, mod_time, "unknown"))
                else:
                    # Fallback to file modification time
                    mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    parsed_files.append((file_path, mod_time, "unknown"))

            # Sort by timestamp (newest first)
            parsed_files.sort(key=lambda x: x[1], reverse=True)

            # Select credential file
            selected_file = self._select_credential_file(parsed_files, username)

            # Search the selected file
            return self._search_credentials_in_file(selected_file, username, account_id, cluster_name)

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error loading IAM credentials: {str(e)}")
            raise ValueError(f"Error accessing credentials: {str(e)}")

    def _extract_timestamp_from_filename(self, file_path: str) -> str:
        """Extract timestamp from filename like iam_users_credentials_20250619_180944.json"""
        try:
            import re
            import os

            filename = os.path.basename(file_path)
            # Pattern: iam_users_credentials_YYYYMMDD_HHMMSS.json
            match = re.search(r'(\d{8}_\d{6})', filename)
            if match:
                return match.group(1)
            return None
        except Exception:
            return None

    def _select_credential_file(self, parsed_files: list, username: str) -> str:
        """Interactive file selection with timestamp display"""
        try:
            if len(parsed_files) == 1:
                file_path, timestamp, timestamp_str = parsed_files[0]
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                self.print_colored(Colors.GREEN,
                                   f"✅ Using credential file: {os.path.basename(file_path)} ({formatted_time})")
                return file_path

            # Multiple files - show selection
            self.print_colored(Colors.CYAN, f"\n📁 Found {len(parsed_files)} IAM credential files:")
            self.print_colored(Colors.CYAN, "=" * 80)

            for i, (file_path, timestamp, timestamp_str) in enumerate(parsed_files, 1):
                filename = os.path.basename(file_path)
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")

                # Highlight the latest (default) file
                if i == 1:
                    self.print_colored(Colors.YELLOW, f"{i}. {formatted_time} - {filename} [LATEST - DEFAULT]")
                else:
                    self.print_colored(Colors.WHITE, f"{i}. {formatted_time} - {filename}")

            self.print_colored(Colors.CYAN, "=" * 80)

            # Get user selection
            while True:
                try:
                    choice = input(f"📁 Select credential file (1-{len(parsed_files)}, Enter for latest): ").strip()

                    # Default to latest (first in list)
                    if not choice:
                        choice = "1"

                    choice_num = int(choice)

                    if 1 <= choice_num <= len(parsed_files):
                        selected_file = parsed_files[choice_num - 1][0]
                        selected_timestamp = parsed_files[choice_num - 1][1].strftime("%Y-%m-%d %H:%M:%S")

                        self.print_colored(Colors.GREEN,
                                           f"✅ Selected: {os.path.basename(selected_file)} ({selected_timestamp})")
                        return selected_file
                    else:
                        self.print_colored(Colors.RED, f"❌ Please enter a number between 1 and {len(parsed_files)}")

                except ValueError:
                    self.print_colored(Colors.RED, "❌ Please enter a valid number or press Enter for default")
                except KeyboardInterrupt:
                    self.print_colored(Colors.RED, "\n❌ Selection cancelled by user")
                    # Default to latest file
                    return parsed_files[0][0]

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ File selection failed: {str(e)}")
            # Fallback to latest file
            return parsed_files[0][0]

    def _search_credentials_in_file(self, file_path: str, username: str, account_id: str = None,
                                    cluster_name: str = None) -> Tuple[str, str, str]:
        """Search for credentials in a specific file"""
        try:
            import os

            self.print_colored(Colors.BLUE, f"📁 Checking file: {os.path.basename(file_path)}")

            with open(file_path, 'r', encoding='utf-8') as f:
                credential_data = json.load(f)

            # Look for users within each account
            accounts = credential_data.get('accounts', {})

            for account_name, account_data in accounts.items():
                current_account_id = account_data.get('account_id', '')

                # Check account ID filter if specified (and valid)
                if account_id and current_account_id != account_id:
                    continue

                # Search for matching username in this account's users
                users = account_data.get('users', [])

                for user in users:
                    user_username = user.get('username', '')

                    # Case-insensitive username matching
                    if user_username.lower() == username.lower():
                        # Found the user!
                        access_key = user.get('access_key_id', '').strip()
                        secret_key = user.get('secret_access_key', '').strip()
                        region = user.get('region', 'us-east-1')
                        real_user = user.get('real_user', {})

                        if not access_key or not secret_key:
                            raise ValueError(f"Incomplete credentials for user {username} in account {account_name}")

                        # Success! Print detailed info
                        self.print_colored(Colors.GREEN, "✅ IAM CREDENTIALS FOUND!")
                        self.print_colored(Colors.WHITE, f"📋 User Details:")
                        self.print_colored(Colors.WHITE, f"   • Username: {user_username}", 1)
                        self.print_colored(Colors.WHITE, f"   • Account: {account_name} ({current_account_id})", 1)
                        self.print_colored(Colors.WHITE, f"   • Region: {region}", 1)
                        self.print_colored(Colors.WHITE, f"   • File: {os.path.basename(file_path)}", 1)

                        if cluster_name:
                            self.print_colored(Colors.WHITE, f"   • Cluster: {cluster_name}", 1)

                        if real_user:
                            self.print_colored(Colors.WHITE, f"   • Real User: {real_user.get('full_name', 'N/A')}", 1)
                            self.print_colored(Colors.WHITE, f"   • Email: {real_user.get('email', 'N/A')}", 1)

                        self.print_colored(Colors.WHITE, f"   • Access Key: {access_key[:8]}...", 1)
                        self.print_colored(Colors.WHITE, f"   • Secret Key: {secret_key[:8]}...", 1)
                        self.print_colored(Colors.CYAN, f"   • Console URL: {user.get('console_url', 'N/A')}", 1)

                        return access_key, secret_key, current_account_id

            # If we get here, user was not found in this file
            error_msg = f"User '{username}' not found in file {os.path.basename(file_path)}"
            if account_id:
                error_msg += f" for account ID {account_id}"

            raise ValueError(error_msg)

        except json.JSONDecodeError as e:
            self.print_colored(Colors.RED, f"❌ Error reading {file_path}: Invalid JSON - {str(e)}")
            raise ValueError(f"Invalid JSON in credential file: {str(e)}")
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error processing {file_path}: {str(e)}")
            raise

    def _show_available_users(self):
        """Show available users from credential files to help user choose"""
        try:
            import glob
            import os
            from datetime import datetime

            iam_dir = "aws/iam"
            pattern = f"{iam_dir}/iam_users_credentials_*.json"
            credential_files = glob.glob(pattern)

            if not credential_files:
                self.print_colored(Colors.RED, f"No credential files found in {iam_dir}")
                return

            # Parse and sort files by timestamp (newest first)
            parsed_files = []
            for file_path in credential_files:
                timestamp_str = self._extract_timestamp_from_filename(file_path)
                if timestamp_str:
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        parsed_files.append((file_path, timestamp))
                    except ValueError:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        parsed_files.append((file_path, mod_time))
                else:
                    mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    parsed_files.append((file_path, mod_time))

            # Sort by timestamp (newest first)
            parsed_files.sort(key=lambda x: x[1], reverse=True)

            self.print_colored(Colors.CYAN, "\n📋 Available IAM Users (from latest file):")
            self.print_colored(Colors.CYAN, "=" * 60)

            # Show users from the latest file only
            latest_file = parsed_files[0][0]
            latest_timestamp = parsed_files[0][1].strftime("%Y-%m-%d %H:%M:%S")

            self.print_colored(Colors.BLUE, f"📁 File: {os.path.basename(latest_file)} ({latest_timestamp})")

            user_count = 0
            try:
                with open(latest_file, 'r', encoding='utf-8') as f:
                    credential_data = json.load(f)

                accounts = credential_data.get('accounts', {})

                for account_name, account_data in accounts.items():
                    account_id = account_data.get('account_id', '')
                    users = account_data.get('users', [])

                    if users:
                        self.print_colored(Colors.YELLOW, f"\n🏢 {account_name} ({account_id}):")

                        for user in users:
                            username = user.get('username', '')
                            real_user = user.get('real_user', {})
                            region = user.get('region', '')

                            real_name = real_user.get('full_name', 'N/A')

                            self.print_colored(Colors.WHITE, f"   • {username} ({real_name}) - {region}", 1)
                            user_count += 1

            except Exception as e:
                self.print_colored(Colors.RED, f"Error reading {latest_file}: {str(e)}")

            self.print_colored(Colors.CYAN, "=" * 60)
            self.print_colored(Colors.CYAN, f"Total users shown: {user_count}")

            if len(parsed_files) > 1:
                self.print_colored(Colors.YELLOW,
                                   f"💡 Note: {len(parsed_files)} credential files available - latest shown above")

        except Exception as e:
            self.print_colored(Colors.RED, f"Error showing available users: {str(e)}")

    def show_all_credential_files(self):
        """Show all available credential files with timestamps"""
        try:
            import glob
            import os
            from datetime import datetime

            iam_dir = "aws/iam"
            pattern = f"{iam_dir}/iam_users_credentials_*.json"
            credential_files = glob.glob(pattern)

            if not credential_files:
                self.print_colored(Colors.RED, f"No credential files found in {iam_dir}")
                return

            # Parse and sort files by timestamp
            parsed_files = []
            for file_path in credential_files:
                timestamp_str = self._extract_timestamp_from_filename(file_path)
                if timestamp_str:
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        parsed_files.append((file_path, timestamp, timestamp_str))
                    except ValueError:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        parsed_files.append((file_path, mod_time, "modified"))
                else:
                    mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    parsed_files.append((file_path, mod_time, "modified"))

            # Sort by timestamp (newest first)
            parsed_files.sort(key=lambda x: x[1], reverse=True)
            current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.print_colored(Colors.BOLD, "=" * 80)
            self.print_colored(Colors.BOLD, "    IAM CREDENTIAL FILES SUMMARY")
            self.print_colored(Colors.BOLD, "=" * 80)
            self.print_colored(Colors.CYAN, f"    Current Date: {current_timestamp}")
            self.print_colored(Colors.CYAN, f"    Current User: varadharajaan")
            self.print_colored(Colors.BOLD, "=" * 80)

            for i, (file_path, timestamp, timestamp_type) in enumerate(parsed_files, 1):
                filename = os.path.basename(file_path)
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                file_size = os.path.getsize(file_path)

                if i == 1:
                    self.print_colored(Colors.GREEN, f"{formatted_time} - {filename} [LATEST] ({file_size} bytes)")
                else:
                    self.print_colored(Colors.WHITE, f"{formatted_time} - {filename} ({file_size} bytes)")

            self.print_colored(Colors.BOLD, "=" * 80)
            self.print_colored(Colors.CYAN, f"📊 Total files: {len(parsed_files)}")

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error showing credential files: {str(e)}")

    def get_iam_credentials_from_cluster(self, cluster_name: str, region: str = None) -> Tuple[str, str, str]:
        """
        Extract username from cluster name and get IAM credentials

        Current Date and Time (UTC): 2025-06-24 15:37:19
        Current User's Login: varadharajaan

        Args:
            cluster_name: EKS cluster name with embedded username (e.g., eks-cluster-account03_clouduser01-us-east-1-diox)
            region: AWS region (optional)

        Returns:
            Tuple[access_key, secret_key, account_id]: AWS credentials and account ID
        """
        try:
            # Extract username from cluster name
            username = self._extract_username_from_cluster_name(cluster_name)

            if not username:
                raise ValueError(f"Could not extract username from cluster name: {cluster_name}")

            self.print_colored(Colors.GREEN, f"🎯 Extracted username from cluster: {username}")

            # If region not provided, try to extract from cluster name
            if not region:
                region = self._extract_region_from_cluster_name(cluster_name)
                if region:
                    self.print_colored(Colors.GREEN, f"🌍 Extracted region from cluster: {region}")

            # Get credentials using the extracted username (NO account_id filter)
            return self.get_iam_credentials(username=username, account_id=None, cluster_name=cluster_name)

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error extracting credentials from cluster '{cluster_name}': {str(e)}")
            raise ValueError(f"Error extracting credentials from cluster '{cluster_name}': {str(e)}")

    # Alternative method that returns only 2 values for backward compatibility
    def get_iam_credentials_legacy(self, username: str = None, account_id: str = None, cluster_name: str = None) -> \
    Tuple[str, str]:
        """
        Legacy method that returns only access_key and secret_key (for backward compatibility)

        Returns:
            Tuple[access_key, secret_key]: AWS credentials (without account_id)
        """
        try:
            access_key, secret_key, account_id = self.get_iam_credentials(username, account_id, cluster_name)
            return access_key, secret_key
        except Exception as e:
            raise e

    def get_iam_credentials_from_cluster_legacy(self, cluster_name: str, region: str = None) -> Tuple[str, str]:
        """
        Legacy method that returns only access_key and secret_key (for backward compatibility)

        Returns:
            Tuple[access_key, secret_key]: AWS credentials (without account_id)
        """
        try:
            access_key, secret_key, account_id = self.get_iam_credentials_from_cluster(cluster_name, region)
            return access_key, secret_key
        except Exception as e:
            raise e

    def get_root_credentials_from_cluster_legacy(self, cluster_name: str = None, region: str = None, account_id: str = None) -> Tuple[
        str, str]:
        """
        Legacy method that returns only access_key and secret_key (for backward compatibility)

        Returns:
            Tuple[access_key, secret_key]: Root AWS credentials (without account_id)
        """
        try:
            access_key, secret_key, _ = self.get_root_credentials(cluster_name, region, account_id)
            return access_key, secret_key
        except Exception as e:
            raise e

    def get_root_credentials(self, cluster_name: str = None, region: str = None, account_id: str = None) -> Tuple[
        str, str, str]:
        """
        Get root account credentials from accounts config JSON

        Current Date and Time (UTC): 2025-06-24 15:27:01
        Current User's Login: varadharajaan

        Args:
            cluster_name: EKS cluster name (optional - used for auto-detection)
            region: AWS region (optional)
            account_id: Specific account ID to filter by (optional)

        Returns:
            Tuple[access_key, secret_key, account_id]: Root AWS credentials and account ID
        """
        try:
            # Load root credentials from file if not already loaded
            if not hasattr(self, 'aws_accounts_config') or not self.aws_accounts_config:
                self.aws_accounts_config = self._load_root_accounts_config()

            if not self.aws_accounts_config or not self.aws_accounts_config.get("accounts"):
                raise ValueError("No AWS root accounts configuration found or invalid format")

            # Get accounts dictionary
            accounts = self.aws_accounts_config.get("accounts", {})
            if not accounts:
                raise ValueError("No accounts found in AWS root accounts configuration")

            self.print_colored(Colors.CYAN, f"🔍 Found {len(accounts)} root accounts in configuration")

            # Strategy 1: Filter by specific account ID if provided
            if account_id:
                matching_accounts = []
                for account_name, account_data in accounts.items():
                    if account_data.get('account_id') == account_id:
                        matching_accounts.append((account_name, account_data))

                if not matching_accounts:
                    raise ValueError(f"No account found with ID: {account_id}")

                self.print_colored(Colors.GREEN, f"✅ Found account by ID: {account_id}")

            # Strategy 2: Try to extract account name from cluster name
            elif cluster_name:
                account_name_from_cluster = self._extract_account_from_cluster_name(cluster_name)
                matching_accounts = []

                if account_name_from_cluster and account_name_from_cluster in accounts:
                    matching_accounts.append((account_name_from_cluster, accounts[account_name_from_cluster]))
                    self.print_colored(Colors.GREEN,
                                       f"🎯 Detected account from cluster name: {account_name_from_cluster}")
                else:
                    # Include all accounts if no match
                    matching_accounts = list(accounts.items())
                    self.print_colored(Colors.YELLOW, f"⚠️ Could not detect account from cluster name: {cluster_name}")

            # Strategy 3: Show all accounts
            else:
                matching_accounts = list(accounts.items())
                self.print_colored(Colors.BLUE, "📋 No filters provided, showing all accounts")

            # Auto-select if only one account matches
            if len(matching_accounts) == 1:
                account_name, account_data = matching_accounts[0]
                account_id = account_data.get('account_id', 'unknown')
                self.print_colored(Colors.GREEN, f"✅ Auto-selected account: {account_name} (ID: {account_id})")

            # Let user choose from multiple accounts
            else:
                account_name, account_data = self._interactive_account_selection(matching_accounts)

            # Extract and validate credentials
            access_key = account_data.get('access_key', '').strip()
            secret_key = account_data.get('secret_key', '').strip()
            account_id = account_data.get('account_id', '').strip()
            account_email = account_data.get('email', 'N/A')
            users_count = account_data.get('users_per_account', 0)

            # Validate credentials
            if not access_key or not secret_key or not account_id:
                raise ValueError(f"Incomplete root credentials for account {account_name}")

            if not isinstance(access_key, str) or not isinstance(secret_key, str):
                raise ValueError(f"Invalid credential format for account {account_name}")

            # Success! Print detailed info
            self.print_colored(Colors.GREEN, "✅ ROOT CREDENTIALS LOADED!")
            self.print_colored(Colors.WHITE, f"📋 Account Details:")
            self.print_colored(Colors.WHITE, f"   • Account Name: {account_name}", 1)
            self.print_colored(Colors.WHITE, f"   • Account ID: {account_id}", 1)
            self.print_colored(Colors.WHITE, f"   • Email: {account_email}", 1)
            self.print_colored(Colors.WHITE, f"   • Users: {users_count}", 1)
            self.print_colored(Colors.WHITE, f"   • Access Key: {access_key[:8]}...", 1)
            self.print_colored(Colors.WHITE, f"   • Secret Key: {secret_key[:8]}...", 1)

            if region:
                self.print_colored(Colors.WHITE, f"   • Region: {region}", 1)

            return access_key, secret_key, account_id

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error loading root credentials: {str(e)}")
            raise ValueError(f"Error accessing root credentials: {str(e)}")

    def _load_root_accounts_config(self) -> dict:
        """Load root accounts configuration from JSON file"""
        try:
            import glob

            # Look for root credentials files
            root_dir = "."
            patterns = [
                f"{root_dir}/root_accounts_*.json",
                f"{root_dir}/aws_accounts_*.json",
                "aws/root_accounts.json",
                "aws_accounts.json",
                "root_accounts.json",
                "aws_accounts_config.json"
            ]

            credential_files = []
            for pattern in patterns:
                credential_files.extend(glob.glob(pattern))

            # Remove duplicates and sort by newest
            credential_files = sorted(list(set(credential_files)), reverse=True)

            if not credential_files:
                raise ValueError(f"No root account files found. Searched patterns: {patterns}")

            # Try to load the first (newest) file
            for file_path in credential_files:
                try:
                    self.print_colored(Colors.BLUE, f"📁 Loading root accounts from: {file_path}")

                    with open(file_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)

                    # Validate structure
                    if not config.get('accounts'):
                        continue

                    self.print_colored(Colors.GREEN, f"✅ Successfully loaded root accounts configuration")
                    return config

                except json.JSONDecodeError as e:
                    self.print_colored(Colors.RED, f"❌ Invalid JSON in {file_path}: {str(e)}")
                    continue
                except Exception as e:
                    self.print_colored(Colors.RED, f"❌ Error reading {file_path}: {str(e)}")
                    continue

            raise ValueError("No valid root account configuration files found")

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Failed to load root accounts config: {str(e)}")
            raise

    def _extract_username_from_cluster_name(self, cluster_name: str) -> str:
        """
        Extract username from cluster name patterns.

        - Root: eks-cluster-root-account01-us-east-1-xxxx → root-account01
        - IAM:  eks-cluster-account01_clouduser01-us-east-1-xxxx → account01_clouduser01
        """
        try:
            if not cluster_name:
                return None

            self.print_colored(Colors.BLUE, f"🔍 Parsing cluster name: {cluster_name}")

            # Root user pattern
            if cluster_name.startswith("eks-cluster-root-account"):
                # Example: eks-cluster-root-account01-us-east-1-xxxx
                parts = cluster_name.split('-')
                if len(parts) >= 4:
                    username = f"{parts[2]}-{parts[3]}"  # root-account01
                    self.print_colored(Colors.GREEN, f"✅ Detected root user: {username}")
                    return username
                else:
                    self.print_colored(Colors.RED, f"❌ Invalid root cluster name format: {cluster_name}")
                    return None

            # IAM user pattern
            if cluster_name.startswith("eks-cluster-"):
                parts = cluster_name.split('-')
                if len(parts) >= 3:
                    username = parts[2]
                    if '_' in username:
                        self.print_colored(Colors.GREEN, f"✅ Detected IAM user: {username}")
                        return username
                    else:
                        self.print_colored(Colors.YELLOW,
                                           f"⚠️ Username does not match expected IAM pattern: {username}")
                        return username

            self.print_colored(Colors.RED, f"❌ Unrecognized cluster name format: {cluster_name}")
            return None

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error parsing cluster name: {str(e)}")
            return None

    def _extract_account_from_cluster_name(self, cluster_name: str) -> str:
        """
        Extract account name from EKS cluster name.
        - Root: eks-cluster-root-account01-us-east-1-xxxx → account01
        - IAM:  eks-cluster-account01_clouduser01-us-east-1-xxxx → account01
        """
        try:
            if not cluster_name:
                return None

            parts = cluster_name.split('-')
            # Root pattern: eks-cluster-root-account01-us-east-1-xxxx
            if len(parts) >= 4 and parts[2] == 'root':
                return parts[3] if parts[3].startswith('account') else None

            # IAM pattern: eks-cluster-account01_clouduser01-us-east-1-xxxx
            if len(parts) >= 3 and parts[2].startswith('account'):
                return parts[2].split('_')[0]

            # Fallback: regex search
            import re
            match = re.search(r'account\d+', cluster_name)
            if match:
                return match.group(0)

            return None
        except Exception:
            return None

    def _extract_region_from_cluster_name(self, cluster_name: str) -> str:
        """
        Extract AWS region from cluster name

        Examples:
        - eks-cluster-account03_clouduser01-us-east-1-diox → us-east-1
        - eks-cluster-account02_clouduser05-ap-south-1-xyz → ap-south-1
        """
        try:
            if not cluster_name:
                return None

            # Common AWS regions pattern
            import re

            # Pattern for AWS regions: us-east-1, us-west-2, ap-south-1, eu-west-1, etc.
            region_pattern = r'(us|eu|ap|sa|ca|me|af)-(north|south|east|west|central|southeast|northeast)-[1-9]'

            match = re.search(region_pattern, cluster_name)
            if match:
                region = match.group()
                self.print_colored(Colors.GREEN, f"🌍 Extracted region: {region}")
                return region

            # Fallback: try to find region-like patterns in cluster name parts
            parts = cluster_name.split('-')
            for i in range(len(parts) - 1):
                # Look for patterns like us-east, us-west, ap-south
                if i + 1 < len(parts):
                    potential_region = f"{parts[i]}-{parts[i + 1]}"
                    if any(potential_region.startswith(prefix) for prefix in ['us-', 'eu-', 'ap-', 'sa-', 'ca-']):
                        # Check if next part looks like a number
                        if i + 2 < len(parts) and parts[i + 2].isdigit():
                            region = f"{potential_region}-{parts[i + 2]}"
                            self.print_colored(Colors.GREEN, f"🌍 Extracted region (fallback): {region}")
                            return region

            self.print_colored(Colors.YELLOW, f"⚠️ Could not extract region from cluster name: {cluster_name}")
            return None

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error extracting region: {str(e)}")
            return None

    def _interactive_account_selection(self, matching_accounts: list) -> Tuple[str, dict]:
        """Interactive account selection with enhanced display"""
        try:
            self.print_colored(Colors.CYAN, "\n📋 Available Root Accounts:")
            self.print_colored(Colors.CYAN, "=" * 80)

            # Display accounts in a nice format
            for i, (account_name, account_data) in enumerate(matching_accounts, 1):
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                users_count = account_data.get('users_per_account', 0)
                access_key = account_data.get('access_key', '')

                self.print_colored(Colors.YELLOW, f"{i}. {account_name}")
                self.print_colored(Colors.WHITE, f"   • Account ID: {account_id}", 1)
                self.print_colored(Colors.WHITE, f"   • Email: {email}", 1)
                self.print_colored(Colors.WHITE, f"   • Users: {users_count}", 1)
                self.print_colored(Colors.WHITE,
                                   f"   • Access Key: {access_key[:8]}..." if access_key else "   • Access Key: Not available",
                                   1)
                print()

            self.print_colored(Colors.CYAN, "=" * 80)

            # Get user selection
            while True:
                try:
                    choice = input(f"🔑 Select root account (1-{len(matching_accounts)}): ").strip()
                    choice_num = int(choice)

                    if 1 <= choice_num <= len(matching_accounts):
                        selected_account = matching_accounts[choice_num - 1]
                        account_name, account_data = selected_account

                        self.print_colored(Colors.GREEN, f"✅ Selected: {account_name}")
                        return selected_account
                    else:
                        self.print_colored(Colors.RED,
                                           f"❌ Please enter a number between 1 and {len(matching_accounts)}")

                except ValueError:
                    self.print_colored(Colors.RED, "❌ Please enter a valid number")
                except KeyboardInterrupt:
                    self.print_colored(Colors.RED, "\n❌ Selection cancelled by user")
                    raise ValueError("Account selection cancelled")

        except Exception as e:
            raise ValueError(f"Account selection failed: {str(e)}")


    def _suggest_username_from_context(self) -> str:
        """Enhanced version that can extract from cluster names"""
        try:
            # This method can be called from the original get_iam_credentials
            # when no username is provided - you can enhance this based on your needs

            # For now, we could check if there are any recent cluster operations
            # or stored cluster names that we can extract from

            return None  # Will be enhanced based on your specific needs

        except Exception:
            return None


    def verify_cluster_exists(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Verify that the cluster exists and is accessible"""
        try:
            self.print_colored('YELLOW', f"🔍 Verifying cluster {cluster_name} in {region}...")

            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            eks_client = session.client('eks')

            # Try to describe the cluster
            response = eks_client.describe_cluster(name=cluster_name)
            cluster = response['cluster']

            self.cluster_info = {
                'name': cluster['name'],
                'status': cluster['status'],
                'version': cluster['version'],
                'endpoint': cluster['endpoint'],
                'arn': cluster['arn'],
                'created_at': cluster['createdAt'].strftime('%Y-%m-%d %H:%M:%S'),
                'region': region,
                'account_id': cluster['arn'].split(':')[4],
                'username': self._extract_username_from_cluster_name(cluster_name)
            }

            if cluster['status'] != 'ACTIVE':
                self.print_colored('RED', f"❌ Cluster is in {cluster['status']} state, not ACTIVE")
                return False

            self.print_colored('GREEN', f"✅ Cluster {cluster_name} is ACTIVE")
            self.print_colored('CYAN', f"   Version: {cluster['version']}")
            self.print_colored('CYAN', f"   Created: {self.cluster_info['created_at']}")
            self.print_colored('CYAN', f"   Account: {self.cluster_info['account_id']}")
            self.print_colored('CYAN', f"   ARN: {self.cluster_info['region']}")

            return True

        except Exception as e:
            self.print_colored('RED', f"❌ Failed to verify cluster: {str(e)}")
            return False

    def analyze_existing_components(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> Dict:
        """Analyze what components are already installed on the cluster"""
        self.print_colored('YELLOW', f"🔍 Analyzing existing cluster components...")

        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )

        eks_client = session.client('eks')

        components = {
            'nodegroups': [],
            'addons': [],
            'container_insights': False,
            'cluster_autoscaler': False,
            'scheduled_scaling': False,
            'cloudwatch_alarms': False,
            'cost_alarms': False
        }

        try:
            # Check nodegroups
            nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
            nodegroups = nodegroups_response.get('nodegroups', [])

            for ng_name in nodegroups:
                ng_response = eks_client.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=ng_name
                )
                nodegroup = ng_response['nodegroup']

                components['nodegroups'].append({
                    'name': ng_name,
                    'status': nodegroup['status'],
                    'capacity_type': nodegroup.get('capacityType', 'ON_DEMAND'),
                    'instance_types': nodegroup.get('instanceTypes', []),
                    'scaling_config': nodegroup.get('scalingConfig', {}),
                    'ami_type': nodegroup.get('amiType', 'Unknown')
                })

            # Check add-ons
            addons_response = eks_client.list_addons(clusterName=cluster_name)
            addons = addons_response.get('addons', [])

            for addon_name in addons:
                addon_response = eks_client.describe_addon(
                    clusterName=cluster_name,
                    addonName=addon_name
                )
                addon = addon_response['addon']

                components['addons'].append({
                    'name': addon_name,
                    'status': addon['status'],
                    'version': addon.get('addonVersion', 'Unknown')
                })

            # Check for Container Insights, Cluster Autoscaler, etc. using existing methods
            components['container_insights'] = self.eks_manager._verify_container_insights(
                cluster_name, region, access_key, secret_key
            )

            components['cluster_autoscaler'] = self.eks_manager._verify_cluster_autoscaler(
                cluster_name, region, access_key, secret_key
            )

            # Check scheduled scaling
            components['scheduled_scaling'] = self.check_scheduled_scaling(
                cluster_name, region, access_key, secret_key
            )

            # Check CloudWatch alarms
            components['cloudwatch_alarms'] = self.check_cloudwatch_alarms(
                cluster_name, region, access_key, secret_key
            )

            # Check cost alarms
            components['cost_alarms'] = self.check_cost_alarms(
                cluster_name, region, access_key, secret_key
            )

        except Exception as e:
            self.logger.error(f"Error analyzing components: {str(e)}")

        self.existing_components = components
        return components

    def check_scheduled_scaling(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Check if scheduled scaling is configured"""
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            lambda_client = session.client('lambda')

            short_cluster_suffix = cluster_name.split('-')[-1]
            function_name = f"eks-scale-{short_cluster_suffix}"

            # Check if Lambda function exists
            try:
                lambda_client.get_function(FunctionName=function_name)
                return True
            except lambda_client.exceptions.ResourceNotFoundException:
                return False

        except Exception:
            return False

    def check_cloudwatch_alarms(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Check if CloudWatch alarms are configured"""
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            cloudwatch_client = session.client('cloudwatch')

            # Check for alarms with cluster name prefix
            alarm_prefix = f"{cluster_name}-"
            response = cloudwatch_client.describe_alarms(AlarmNamePrefix=alarm_prefix)

            return len(response.get('MetricAlarms', [])) > 0

        except Exception:
            return False

    def check_cost_alarms(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Check if cost monitoring alarms are configured"""
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            cloudwatch_client = session.client('cloudwatch')

            # Check for cost alarms
            cost_patterns = [f"{cluster_name}-daily-cost", f"{cluster_name}-ec2-cost"]

            for pattern in cost_patterns:
                response = cloudwatch_client.describe_alarms(AlarmNamePrefix=pattern)
                if response.get('MetricAlarms', []):
                    return True

            return False

        except Exception:
            return False

    def display_cluster_status(self) -> None:
        """Display current cluster status and components"""
        print("\n" + "=" * 60)
        print("📊 CURRENT CLUSTER STATUS")
        print("=" * 60)

        # Cluster info
        print(f"Cluster Name: {self.cluster_info['name']}")
        print(f"Status: {self.cluster_info['status']}")
        print(f"Version: {self.cluster_info['version']}")
        print(f"Region: {self.cluster_info['region']}")
        print(f"Account: {self.cluster_info['account_id']}")

        # Nodegroups
        nodegroups = self.existing_components.get('nodegroups', [])
        print(f"\n📦 Nodegroups ({len(nodegroups)} found):")
        if nodegroups:
            for ng in nodegroups:
                scaling = ng['scaling_config']
                status_color = 'GREEN' if ng['status'] == 'ACTIVE' else 'YELLOW'
                self.print_colored(status_color, f"  ✓ {ng['name']} ({ng['capacity_type']}) - {ng['status']}")
                print(f"    Instance Types: {', '.join(ng['instance_types'])}")
                print(f"    Scaling: {scaling.get('desiredSize', 0)}/{scaling.get('maxSize', 0)} nodes")
        else:
            self.print_colored('YELLOW', "  ⚠️  No nodegroups found")

        # Add-ons
        addons = self.existing_components.get('addons', [])
        print(f"\n🧩 Add-ons ({len(addons)} found):")
        if addons:
            for addon in addons:
                status_color = 'GREEN' if addon['status'] == 'ACTIVE' else 'YELLOW'
                self.print_colored(status_color, f"  ✓ {addon['name']} (v{addon['version']}) - {addon['status']}")
        else:
            self.print_colored('YELLOW', "  ⚠️  No add-ons found")

        # Other components
        print(f"\n🔧 Other Components:")
        components_status = [
            ('Container Insights', self.existing_components.get('container_insights', False)),
            ('Cluster Autoscaler', self.existing_components.get('cluster_autoscaler', False)),
            ('Scheduled Scaling', self.existing_components.get('scheduled_scaling', False)),
            ('CloudWatch Alarms', self.existing_components.get('cloudwatch_alarms', False)),
            ('Cost Alarms', self.existing_components.get('cost_alarms', False))
        ]

        for component, status in components_status:
            status_color = 'GREEN' if status else 'YELLOW'
            status_text = 'Configured' if status else 'Not configured'
            icon = '✓' if status else '⚠️'
            self.print_colored(status_color, f"  {icon} {component}: {status_text}")

    def show_main_menu(self) -> int:
        """Show main menu and get user choice"""
        print("\n" + "=" * 60)
        print("🔧 CLUSTER CONFIGURATION MENU")
        print("=" * 60)
        print("1. Create/Modify Nodegroups")
        print("2. Install/Update Add-ons")
        print("3. Configure Container Insights")
        print("4. Setup Cluster Autoscaler")
        print("5. Configure Scheduled Scaling")
        print("6. Setup CloudWatch Monitoring")
        print("7. Configure Cost Monitoring")
        print("8. Generate User Instructions")
        print("9. Run Health Check")
        print("10. configure user auth configmap")
        print("11. add NO_DELETE protected labels to nodes")
        print("12. add custom cloudwatch agent")
        print("0. Exit")
        print("=" * 60)

        choice = input("Enter your choices (0-12): ").strip()
        return int(choice)

    def continue_cluster_setup_from_errors(self) -> bool:
        """Main method to continue cluster setup from error files"""
        try:
            # Find and parse error files
            error_files = self.find_error_files()
            if not error_files:
                self.print_colored('RED', "❌ No cluster creation error files found")
                return False

            # Group clusters by date
            clusters_by_date = self.group_clusters_by_date(error_files)
            if not clusters_by_date:
                self.print_colored('RED', "❌ No failed clusters found in error files")
                return False

            # Display clusters by date
            self.display_clusters_by_date(clusters_by_date)

            # Let user select date and clusters
            selected_clusters = self.select_date_and_clusters(clusters_by_date)
            if not selected_clusters:
                self.print_colored('YELLOW', "⚠️  No clusters selected")
                return False

            # Process each selected cluster
            successful_continuations = 0

            for i, cluster_info in enumerate(selected_clusters, 1):
                cluster_name, region = self.extract_cluster_details(cluster_info)

                print(f"\n{'=' * 80}")
                print(f"🚀 CONTINUING CLUSTER {i}/{len(selected_clusters)}: {cluster_name}")
                print(f"{'=' * 80}")

                try:
                    # Get credentials for this cluster
                    admin_access_key, admin_secret_key = self.get_credentials_for_cluster(cluster_name, region)

                    # Verify cluster exists
                    if not self.verify_cluster_exists(cluster_name, region, admin_access_key, admin_secret_key):
                        self.print_colored('RED', f"❌ Cluster {cluster_name} verification failed")
                        continue

                    # Analyze existing components
                    #self.analyze_existing_components(cluster_name, region, admin_access_key, admin_secret_key)

                    # Main configuration loop for this cluster
                    print(f"\n🔧 Starting configuration for {cluster_name}...")
                    cluster_success = self.configure_single_cluster(cluster_name, region, admin_access_key,
                                                                    admin_secret_key)

                    if cluster_success:
                        successful_continuations += 1
                        self.print_colored('GREEN', f"✅ Successfully configured cluster {cluster_name}")
                    else:
                        self.print_colored('YELLOW', f"⚠️  Partial configuration for cluster {cluster_name}")

                except Exception as e:
                    self.logger.error(f"Error configuring cluster {cluster_name}: {str(e)}")
                    self.print_colored('RED', f"❌ Error configuring cluster {cluster_name}: {str(e)}")
                    continue

            # Final summary
            print(f"\n{'=' * 80}")
            print("📋 CONTINUATION SUMMARY")
            print(f"{'=' * 80}")
            print(f"Total clusters processed: {len(selected_clusters)}")
            print(f"Successfully configured: {successful_continuations}")
            print(f"Failed/Partial: {len(selected_clusters) - successful_continuations}")

            return successful_continuations > 0

        except KeyboardInterrupt:
            self.print_colored('YELLOW', "\n⚠️  Configuration interrupted by user")
            return False
        except Exception as e:
            self.logger.error(f"Error in cluster continuation: {str(e)}")
            self.print_colored('RED', f"❌ Error: {str(e)}")
            return False

    def configure_single_cluster(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure a single cluster interactively"""
        try:
            # Show status once at the start
            self.display_cluster_status()

            while True:
                changed = False
                choice_num = self.show_main_menu()

                if choice_num == 0:
                    self.print_colored(Colors.YELLOW, "Exiting cluster configuration")
                    return True
                elif choice_num == 1:
                    changed = self.configure_nodegroups(cluster_name, region, access_key, secret_key)
                elif choice_num == 2:
                    changed = self.configure_addons(cluster_name, region, access_key, secret_key)
                elif choice_num == 3:
                    changed = self.configure_container_insights(cluster_name, region, access_key, secret_key)
                elif choice_num == 4:
                    changed = self.configure_cluster_autoscaler(cluster_name, region, access_key, secret_key)
                elif choice_num == 5:
                    changed = self.configure_scheduled_scaling(cluster_name, region, access_key, secret_key)
                elif choice_num == 6:
                    changed = self.configure_cloudwatch_monitoring(cluster_name, region, access_key, secret_key)
                elif choice_num == 7:
                    changed = self.configure_cost_monitoring(cluster_name, region, access_key, secret_key)
                elif choice_num == 8:
                    changed = self.generate_user_instructions(cluster_name, region, access_key, secret_key)
                elif choice_num == 9:
                    changed = self.run_health_check(cluster_name, region, access_key, secret_key)
                elif choice_num == 10:
                    account_id = self._extract_account_from_cluster_name(cluster_name)
                    user_data = {
                        'username': self._extract_username_from_cluster_name(cluster_name),
                        'email': '',
                        'access_key_id': access_key,
                        'secret_access_key': secret_key
                    }
                    is_root = 'root' in cluster_name
                    changed = self.configure_aws_auth_configmap_enhanced(
                        cluster_name, region, account_id, user_data, access_key, secret_key, is_root
                    )
                elif choice_num == 11:
                    self.print_colored(Colors.CYAN, "\n🔒 Setting up node protection with NO_DELETE labels...")

                    self.eks_manager.protect_nodes_with_no_delete_label(cluster_name, region, access_key, secret_key)



                    # Apply initial node protection
                    protection_result = self.eks_manager.apply_no_delete_to_matching_nodegroups(
                        cluster_name, region, access_key, secret_key
                    )

                    nodegroup_names = protection_result.get('all_nodegroups', [])

                    if protection_result.get('success'):
                        self.print_colored(Colors.GREEN, f"✅ Initial node protection applied")

                        # Setup automated monitoring
                        self.print_colored(Colors.YELLOW, f"\n⏰ Setting up automated node protection monitoring...")
                        monitoring_setup = self.eks_manager.setup_node_protection_monitoring(
                            cluster_name, region, access_key, secret_key, nodegroup_names
                        )

                        if monitoring_setup:
                            self.print_colored(Colors.GREEN, f"✅ Automated node protection monitoring enabled")
                            self.print_colored(Colors.CYAN,
                                               f"   📋 Lambda will run every time a ec2 is terminated to ensure node protection")
                        else:
                            self.print_colored(Colors.YELLOW,
                                               f"⚠️ Automated monitoring setup failed - manual monitoring required")

                elif choice_num == 12:
                    self.print_colored(Colors.CYAN, "\n🔒 Configuring custom cloudwatch agent...")
                    if False:
                        from custom_cloudwatch_agent_deployer import CustomCloudWatchAgentDeployer
                        agent_deployer = CustomCloudWatchAgentDeployer()
                        changed = agent_deployer.deploy_custom_cloudwatch_agent(
                            cluster_name, region, access_key, secret_key
                        )
                else:
                    self.print_colored(Colors.RED, f"❌ Invalid choice: {choice_num}")

                # # Only re-analyze and show status if something changed
                # if changed:
                #     self.analyze_existing_components(cluster_name, region, access_key, secret_key)
                #     self.display_cluster_status()

                continue_choice = input("\nContinue configuring this cluster? (Y/n): ").strip().lower()
                if continue_choice == 'n':
                    break

            return True

        except Exception as e:
            self.logger.error(f"Error configuring cluster: {str(e)}")
            self.print_colored('RED', f"❌ Error configuring cluster: {str(e)}")
            return False


    def configure_aws_auth_configmap_enhanced(self, cluster_name: str, region: str, account_id: str, user_data: Dict,
                                              admin_access_key: str, admin_secret_key: str,
                                              is_root_cluster: bool) -> bool:
        """
        Enhanced configure aws-auth ConfigMap with better root/IAM detection
        """
        try:
            self.logger.info(f"Configuring aws-auth ConfigMap for cluster {cluster_name}")
            self.print_colored('CYAN', f"   🔐 Configuring aws-auth ConfigMap...")

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
                self.print_colored('CYAN', f"   👑 Root-created cluster - configuring root access only")
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
                self.print_colored('CYAN', f"   👤 IAM-created cluster: {username} - configuring IAM user + root access")

            # Check cluster authentication mode
            access_config = cluster_info['cluster'].get('accessConfig', {})
            auth_mode = access_config.get('authenticationMode', 'CONFIG_MAP')

            self.print_colored('CYAN', f"   📋 Cluster authentication mode: {auth_mode}")

            # If cluster uses CONFIG_MAP mode or API mode failed, create/update aws-auth ConfigMap
            if auth_mode in ['CONFIG_MAP', 'API_AND_CONFIG_MAP']:
                return self.apply_configmap_with_kubectl(cluster_name, region, account_id, users_to_add,
                                                         admin_access_key, admin_secret_key, is_root_cluster, user_data)
            else:
                return True  # If only API mode, access entries are sufficient

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Failed to configure aws-auth ConfigMap for {cluster_name}: {error_msg}")
            self.print_colored('RED', f"   ❌ ConfigMap configuration failed: {error_msg}")
            return False

    def apply_configmap_with_kubectl(self, cluster_name: str, region: str, account_id: str, users_to_add: List[Dict],
                                     admin_access_key: str, admin_secret_key: str, is_root_cluster: bool,
                                     user_data: Dict) -> bool:
        """
        Apply ConfigMap using kubectl with enhanced error handling
        """
        try:
            self.print_colored('CYAN', "   📋 Creating/updating aws-auth ConfigMap...")
            import yaml
            import tempfile
            import subprocess
            import shutil

            # Check if kubectl is available
            kubectl_available = shutil.which('kubectl') is not None

            if not kubectl_available:
                self.print_colored('YELLOW', f"   ⚠️  kubectl not found. ConfigMap setup skipped.")
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
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            configmap_file = os.path.join(temp_dir, f"aws-auth-{cluster_name}-{timestamp}.yaml")

            try:
                with open(configmap_file, 'w') as f:
                    yaml.dump(aws_auth_config, f)
                self.logger.info(f"Created ConfigMap file: {configmap_file}")
            except Exception as e:
                self.print_colored('RED', f"   ❌ Failed to create ConfigMap file: {str(e)}")
                return False

            # Apply ConfigMap with enhanced error handling
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region

            try:
                # Update kubeconfig
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name,
                    '--overwrite-existing'
                ]

                self.print_colored('CYAN', f"   🔄 Updating kubeconfig...")
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)

                if update_result.returncode != 0:
                    self.print_colored('RED', f"   ❌ Failed to update kubeconfig: {update_result.stderr}")
                    return False

                # Apply ConfigMap with multiple fallback strategies
                apply_strategies = [
                    # Strategy 1: Standard apply with validation disabled
                    ['kubectl', 'apply', '-f', configmap_file, '--validate=false'],
                    # Strategy 2: Replace with force
                    ['kubectl', 'replace', '-f', configmap_file, '--validate=false', '--force'],
                    # Strategy 3: Delete and create
                    ['kubectl', 'delete', 'configmap', 'aws-auth', '-n', 'kube-system', '--ignore-not-found']
                ]

                success = False
                for i, strategy in enumerate(apply_strategies[:2], 1):  # Try first 2 strategies
                    self.print_colored('CYAN', f"   📋 Applying ConfigMap (strategy {i})...")

                    result = subprocess.run(strategy, env=env, capture_output=True, text=True, timeout=300)

                    if result.returncode == 0:
                        self.print_colored('GREEN', f"   ✅ ConfigMap applied successfully (strategy {i})")
                        success = True
                        break
                    else:
                        self.print_colored('YELLOW', f"   ⚠️  Strategy {i} failed: {result.stderr}")

                # If standard strategies failed, try delete and recreate
                if not success:
                    self.print_colored('CYAN', f"   🔄 Trying delete and recreate strategy...")

                    # Delete existing ConfigMap
                    delete_cmd = ['kubectl', 'delete', 'configmap', 'aws-auth', '-n', 'kube-system',
                                  '--ignore-not-found']
                    subprocess.run(delete_cmd, env=env, capture_output=True, text=True, timeout=60)

                    # Wait a moment
                    time.sleep(5)

                    # Apply new ConfigMap
                    create_result = subprocess.run(
                        ['kubectl', 'apply', '-f', configmap_file, '--validate=false'],
                        env=env, capture_output=True, text=True, timeout=300
                    )

                    if create_result.returncode == 0:
                        self.print_colored('GREEN', f"   ✅ ConfigMap recreated successfully")
                        success = True
                    else:
                        self.print_colored('RED', f"   ❌ All strategies failed: {create_result.stderr}")

                if success:
                    if is_root_cluster:
                        self.print_colored('GREEN', f"   ✅ Root user configured for cluster access")
                    else:
                        username = user_data.get('username', 'unknown')
                        self.print_colored('GREEN',
                                           f"   ✅ User [{username}] and root user configured for cluster access")

                return success

            except Exception as e:
                self.print_colored('RED', f"   ❌ Command execution failed: {str(e)}")
                return False

            finally:
                # Clean up temporary files
                try:
                    if os.path.exists(configmap_file):
                        os.remove(configmap_file)
                        self.logger.info(f"Cleaned up temporary ConfigMap file")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up ConfigMap file: {str(e)}")

        except Exception as e:
            self.print_colored('RED', f"   ❌ ConfigMap application failed: {str(e)}")
            return False

    # Include all the configuration methods from the original continuation class
    def configure_nodegroups(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure nodegroups for the cluster"""
        self.print_colored('YELLOW', "\n🚀 Nodegroup Configuration")

        existing_nodegroups = self.existing_components.get('nodegroups', [])

        if existing_nodegroups:
            print(f"\nFound {len(existing_nodegroups)} existing nodegroups:")
            for ng in existing_nodegroups:
                print(f"  - {ng['name']} ({ng['capacity_type']}) - {ng['status']}")

            choice = input("\nDo you want to create additional nodegroups? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                return True

        # Get nodegroup configuration from user
        nodegroup_config = self.get_nodegroup_configuration(cluster_name)

        if not nodegroup_config:
            return False

        # Create the nodegroup using existing EKS manager methods
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            eks_client = session.client('eks')
            ec2_client = session.client('ec2')
            iam_client = session.client('iam')

            account_id = self.cluster_info['account_id']

            # Ensure IAM roles exist
            eks_role_arn, node_role_arn = self.eks_manager.ensure_iam_roles(iam_client, account_id)

            # Get VPC resources
            subnet_ids, security_group_id = self.eks_manager.get_or_create_vpc_resources(ec2_client, region)

            # Select subnets based on preference
            selected_subnets = self.eks_manager.select_subnets_for_nodegroup(
                subnet_ids, nodegroup_config['subnet_preference'], ec2_client
            )

            # Create nodegroup based on strategy
            success = False
            strategy = nodegroup_config['strategy']
            key_name = "k8s_demo_key"
            ec2_key_name = self.ensure_ec2_key_pair(ec2_client, key_name)

            if strategy == 'on-demand':
                success = self.eks_manager.create_ondemand_nodegroup(
                    eks_client, cluster_name, nodegroup_config['name'], node_role_arn,
                    selected_subnets, nodegroup_config['ami_type'],
                    nodegroup_config['instance_selections']['on-demand'],
                    nodegroup_config['min_size'], nodegroup_config['desired_size'], nodegroup_config['max_size'],
                    ec2_key_name
                )
            elif strategy == 'spot':
                success = self.eks_manager.create_spot_nodegroup(
                    eks_client, cluster_name, nodegroup_config['name'], node_role_arn,
                    selected_subnets, nodegroup_config['ami_type'],
                    nodegroup_config['instance_selections']['spot'],
                    nodegroup_config['min_size'], nodegroup_config['desired_size'], nodegroup_config['max_size'],
                    ec2_key_name
                )
            elif strategy == 'mixed':
                success = self.eks_manager.create_mixed_nodegroup(
                    eks_client, cluster_name, nodegroup_config['name'], node_role_arn,
                    selected_subnets, nodegroup_config['ami_type'],
                    nodegroup_config['instance_selections'],
                    nodegroup_config['min_size'], nodegroup_config['desired_size'], nodegroup_config['max_size'],
                    ec2_key_name
                )

            if success:
                self.print_colored('GREEN', f"✅ Successfully created nodegroup: {nodegroup_config['name']}")
                return True
            else:
                self.print_colored('RED', f"❌ Failed to create nodegroup: {nodegroup_config['name']}")
                return False

        except Exception as e:
            self.logger.error(f"Error creating nodegroup: {str(e)}")
            self.print_colored('RED', f"❌ Error creating nodegroup: {str(e)}")
            return False

    def get_nodegroup_configuration(self, cluster_name: str) -> Optional[Dict]:
        """Get nodegroup configuration from user"""
        print("\n📝 Nodegroup Configuration")

        # Strategy selection
        print("\n🔄 Select nodegroup strategy:")
        print("1. On-Demand (reliable, consistent performance, higher cost)")
        print("2. Spot (cheaper, but can be terminated, best for non-critical workloads)")
        print("3. Mixed (combination of on-demand and spot for balance)")

        while True:
            strategy_choice = input("Select strategy (1-3): ").strip()
            if strategy_choice == "1":
                strategy = "on-demand"
                break
            elif strategy_choice == "2":
                strategy = "spot"
                break
            elif strategy_choice == "3":
                strategy = "mixed"
                break
            else:
                print("❌ Invalid choice. Please enter 1, 2, or 3.")

        # Instance type selection
        instance_type = self.eks_manager.select_instance_type()

        # Sizing configuration
        print("\n🔢 Nodegroup sizing:")
        try:
            min_size = int(input("Minimum nodes [default: 1]: ").strip() or "1")
            desired_size = int(input("Desired nodes [default: 1]: ").strip() or "1")
            max_size = int(input("Maximum nodes [default: 3]: ").strip() or "3")

            # Validate values
            if min_size < 0 or desired_size < 0 or max_size < 0:
                print("❌ Negative values are not allowed. Using defaults.")
                min_size, desired_size, max_size = 1, 1, 3

            if min_size > desired_size or desired_size > max_size:
                print("❌ Invalid values (should be min ≤ desired ≤ max). Adjusting...")
                max_size = max(max_size, desired_size, min_size)
                min_size = min(min_size, desired_size)
                desired_size = max(min_size, min(desired_size, max_size))

        except ValueError:
            print("❌ Invalid number format. Using defaults.")
            min_size, desired_size, max_size = 1, 1, 3

        # Instance selections based on strategy
        instance_selections = {}

        if strategy == 'mixed':
            print("\n📊 Mixed strategy configuration:")
            try:
                on_demand_percentage = int(
                    input("Percentage of On-Demand capacity (0-100) [default: 30%]: ").strip() or "30")
                if on_demand_percentage < 0 or on_demand_percentage > 100:
                    on_demand_percentage = 30
            except ValueError:
                on_demand_percentage = 30

            instance_selections = {
                'on-demand': [instance_type],
                'spot': self.eks_manager.get_diversified_instance_types(instance_type),
                'on_demand_percentage': on_demand_percentage
            }
        elif strategy == 'spot':
            instance_selections = {
                'spot': self.eks_manager.get_diversified_instance_types(instance_type)
            }
        else:  # on-demand
            instance_selections = {
                'on-demand': [instance_type]
            }

        # Subnet preference
        print("\n🌐 Subnet preference:")
        print("1. Auto (use all available subnets)")
        print("2. Public (prefer public subnets)")
        print("3. Private (prefer private subnets)")

        subnet_choice = input("Select subnet preference (1-3) [default: 1]: ").strip()
        subnet_preference = {
            "1": "auto",
            "2": "public",
            "3": "private"
        }.get(subnet_choice, "auto")

        # Generate nodegroup name
        nodegroup_name = self.eks_manager.generate_nodegroup_name(cluster_name, strategy)

        return {
            'name': nodegroup_name,
            'strategy': strategy,
            'min_size': min_size,
            'desired_size': desired_size,
            'max_size': max_size,
            'instance_selections': instance_selections,
            'subnet_preference': subnet_preference,
            'ami_type': 'AL2_x86_64'
        }

    def configure_addons(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure essential add-ons"""
        self.print_colored('YELLOW', "\n📦 Add-ons Configuration")

        existing_addons = [addon['name'] for addon in self.existing_components.get('addons', [])]

        if existing_addons:
            print(f"\nFound existing add-ons: {', '.join(existing_addons)}")

        essential_addons = ['vpc-cni', 'coredns', 'kube-proxy', 'aws-ebs-csi-driver', 'aws-efs-csi-driver']
        missing_addons = [addon for addon in essential_addons if addon not in existing_addons]

        if not missing_addons:
            self.print_colored('GREEN', "✅ All essential add-ons are already installed")
            return True

        print(f"\nMissing essential add-ons: {', '.join(missing_addons)}")
        choice = input("Install missing add-ons? (Y/n): ").strip().lower()

        if choice == 'n':
            return True

        # Install missing add-ons using existing method
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            eks_client = session.client('eks')
            account_id = self.cluster_info['account_id']

            success = self.eks_manager.install_essential_addons(
                eks_client, cluster_name, region, access_key, secret_key, account_id
            )

            if success:
                self.print_colored('GREEN', "✅ Add-ons installation completed")
            else:
                self.print_colored('YELLOW', "⚠️  Add-ons installation had some issues")

            return success

        except Exception as e:
            self.logger.error(f"Error installing add-ons: {str(e)}")
            self.print_colored('RED', f"❌ Error installing add-ons: {str(e)}")
            return False

    def configure_container_insights(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure Container Insights"""
        self.print_colored('YELLOW', "\n📊 Container Insights Configuration")

        if self.existing_components.get('container_insights', False):
            self.print_colored('GREEN', "✅ Container Insights is already configured")
            choice = input("Reconfigure Container Insights? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                return True

        choice = input("Enable Container Insights? (Y/n): ").strip().lower()
        if choice == 'n':
            return True

        try:
            success = self.eks_manager.enable_container_insights(
                cluster_name, region, access_key, secret_key
            )

            if success:
                self.print_colored('GREEN', "✅ Container Insights configured successfully")
            else:
                self.print_colored('YELLOW', "⚠️  Container Insights configuration had issues")

            return success

        except Exception as e:
            self.logger.error(f"Error configuring Container Insights: {str(e)}")
            self.print_colored('RED', f"❌ Error configuring Container Insights: {str(e)}")
            return False

    def configure_cluster_autoscaler(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure Cluster Autoscaler"""
        self.print_colored('YELLOW', "\n🔄 Cluster Autoscaler Configuration")

        if self.existing_components.get('cluster_autoscaler', False):
            self.print_colored('GREEN', "✅ Cluster Autoscaler is already configured")
            choice = input("Reconfigure Cluster Autoscaler? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                return True

        choice = input("Configure Cluster Autoscaler? (Y/n): ").strip().lower()
        if choice == 'n':
            return True

        try:
            account_id = self.cluster_info['account_id']
            deployer = CompleteAutoscalerDeployer()

            success = deployer.deploy_complete_autoscaler(
                cluster_name, region, access_key, secret_key, account_id
            )

            if success:
                self.print_colored('GREEN', "✅ Cluster Autoscaler configured successfully")
            else:
                self.print_colored('YELLOW', "⚠️  Cluster Autoscaler configuration had issues")

            return success

        except Exception as e:
            self.logger.error(f"Error configuring Cluster Autoscaler: {str(e)}")
            self.print_colored('RED', f"❌ Error configuring Cluster Autoscaler: {str(e)}")
            return False

    def configure_scheduled_scaling(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure scheduled scaling"""
        self.print_colored('YELLOW', "\n⏰ Scheduled Scaling Configuration")

        if self.existing_components.get('scheduled_scaling', False):
            self.print_colored('GREEN', "✅ Scheduled Scaling is already configured")
            choice = input("Reconfigure Scheduled Scaling? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                return True

        choice = input("Configure Scheduled Scaling? (Y/n): ").strip().lower()
        if choice == 'n':
            return True

        try:
            # Get nodegroup names
            nodegroup_names = [ng['name'] for ng in self.existing_components.get('nodegroups', [])]

            if not nodegroup_names:
                self.print_colored('YELLOW', "⚠️  No nodegroups found for scheduled scaling")
                return False

            success = self.eks_manager.setup_scheduled_scaling_multi_nodegroup(
                cluster_name, region, access_key, secret_key, nodegroup_names
            )

            if success:
                self.print_colored('GREEN', "✅ Scheduled Scaling configured successfully")
            else:
                self.print_colored('YELLOW', "⚠️  Scheduled Scaling configuration had issues")

            return success

        except Exception as e:
            self.logger.error(f"Error configuring Scheduled Scaling: {str(e)}")
            self.print_colored('RED', f"❌ Error configuring Scheduled Scaling: {str(e)}")
            return False

    def configure_cloudwatch_monitoring(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure CloudWatch monitoring"""
        self.print_colored('YELLOW', "\n🚨 CloudWatch Monitoring Configuration")

        if self.existing_components.get('cloudwatch_alarms', False):
            self.print_colored('GREEN', "✅ CloudWatch Alarms are already configured")
            choice = input("Reconfigure CloudWatch Alarms? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                return True

        choice = input("Configure CloudWatch Monitoring? (Y/n): ").strip().lower()
        if choice == 'n':
            return True

        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            cloudwatch_client = session.client('cloudwatch')
            account_id = self.cluster_info['account_id']
            nodegroup_names = [ng['name'] for ng in self.existing_components.get('nodegroups', [])]

            success = self.eks_manager.setup_cloudwatch_alarms_multi_nodegroup(
                cluster_name, region, cloudwatch_client, nodegroup_names, account_id
            )

            if success:
                self.print_colored('GREEN', "✅ CloudWatch Monitoring configured successfully")
            else:
                self.print_colored('YELLOW', "⚠️  CloudWatch Monitoring configuration had issues")

            return success

        except Exception as e:
            self.logger.error(f"Error configuring CloudWatch Monitoring: {str(e)}")
            self.print_colored('RED', f"❌ Error configuring CloudWatch Monitoring: {str(e)}")
            return False

    def configure_cost_monitoring(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Configure cost monitoring"""
        self.print_colored('YELLOW', "\n💰 Cost Monitoring Configuration")

        if self.existing_components.get('cost_alarms', False):
            self.print_colored('GREEN', "✅ Cost Monitoring is already configured")
            choice = input("Reconfigure Cost Monitoring? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                return True

        choice = input("Configure Cost Monitoring? (Y/n): ").strip().lower()
        if choice == 'n':
            return True

        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            cloudwatch_client = session.client('cloudwatch')
            account_id = self.cluster_info['account_id']

            success = self.eks_manager.setup_cost_alarms(
                cluster_name, region, cloudwatch_client, account_id
            )

            if success:
                self.print_colored('GREEN', "✅ Cost Monitoring configured successfully")
            else:
                self.print_colored('YELLOW', "⚠️  Cost Monitoring configuration had issues")

            return success

        except Exception as e:
            self.logger.error(f"Error configuring Cost Monitoring: {str(e)}")
            self.print_colored('RED', f"❌ Error configuring Cost Monitoring: {str(e)}")
            return False

    def generate_user_instructions(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Generate user instructions"""
        self.print_colored('YELLOW', "\n📋 Generating User Instructions")

        try:
            # Create mock credential info for instruction generation
            from aws_credential_manager import CredentialInfo

            username = self.extract_username_from_cluster_name(cluster_name)

            credential_info = CredentialInfo(
                account_name=f"account-{self.cluster_info['account_id']}",
                account_id=self.cluster_info['account_id'],
                email='user@example.com',
                access_key=access_key,
                secret_key=secret_key,
                credential_type='iam',
                regions=[region],
                username=username
            )

            # Convert nodegroup info to config format
            nodegroup_configs = []
            for ng in self.existing_components.get('nodegroups', []):
                scaling = ng['scaling_config']
                nodegroup_configs.append({
                    'name': ng['name'],
                    'strategy': ng['capacity_type'].lower().replace('_', '-'),
                    'min_nodes': scaling.get('minSize', 0),
                    'desired_nodes': scaling.get('desiredSize', 0),
                    'max_nodes': scaling.get('maxSize', 0),
                    'instance_selections': {'types': ng['instance_types']},
                    'subnet_preference': 'auto'
                })

            self.eks_manager.generate_user_instructions_enhanced(
                credential_info, cluster_name, region, credential_info.username, nodegroup_configs
            )

            self.generate_mini_instructions(credential_info, cluster_name, region, credential_info.username)

            self.print_colored('GREEN', "✅ User instructions generated successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error generating user instructions: {str(e)}")
            self.print_colored('RED', f"❌ Error generating user instructions: {str(e)}")
            return False

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

    def run_health_check(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Run comprehensive health check"""
        self.print_colored('YELLOW', "\n🏥 Running Health Check")

        try:
            health_check = self.eks_manager.health_check_cluster(
                cluster_name, region, access_key, secret_key
            )

            if health_check.get('overall_healthy', False):
                self.print_colored('GREEN', "✅ Cluster health check passed")
            else:
                self.print_colored('YELLOW', "⚠️  Cluster health check found issues")

            # Display health summary
            summary = health_check.get('summary', {})
            print(f"\nHealth Score: {summary.get('health_score', 0)}/100")
            print(f"Issues: {summary.get('total_issues', 0)}")
            print(f"Warnings: {summary.get('total_warnings', 0)}")
            print(f"Successes: {summary.get('total_successes', 0)}")

            return True

        except Exception as e:
            self.logger.error(f"Error running health check: {str(e)}")
            self.print_colored('RED', f"❌ Error running health check: {str(e)}")
            return False

    def reconfigure_cluster(self, cluster_names: List[str]) -> bool:
        """
        Reconfigure existing clusters by cluster name without requiring error files

        Args:
            cluster_names: List of cluster names to reconfigure

        Returns:
            bool: True if all clusters were successfully reconfigured, False otherwise
        """
        try:
            self.print_colored(Colors.CYAN, "\n🔄 RECONFIGURING EXISTING CLUSTERS")
            self.print_colored(Colors.CYAN, "=" * 80)

            if not cluster_names:
                self.print_colored(Colors.RED, "❌ No cluster names provided")
                return False

            self.print_colored(Colors.BLUE, f"📋 Found {len(cluster_names)} clusters to reconfigure")

            # Process each cluster
            successful_reconfigures = 0

            for i, cluster_name in enumerate(cluster_names, 1):
                self.print_colored(Colors.CYAN, "\n" + "=" * 80)
                self.print_colored(Colors.CYAN, f"🚀 PROCESSING CLUSTER {i}/{len(cluster_names)}: {cluster_name}")
                self.print_colored(Colors.CYAN, "=" * 80)

                try:
                    # Extract region from cluster name
                    cluster_name = cluster_name.strip()
                    region = self._extract_region_from_cluster_name(cluster_name)

                    if not region:
                        self.print_colored(Colors.YELLOW,
                                           f"⚠️ Could not extract region from cluster name. Please enter it manually:")
                        region = input("Enter AWS region for this cluster: ").strip()
                        if not region:
                            self.print_colored(Colors.RED, f"❌ No region provided, skipping cluster {cluster_name}")
                            continue

                    self.print_colored(Colors.BLUE, f"🌐 Using region: {region}")

                    # Get credentials for cluster
                    self.print_colored(Colors.BLUE, f"🔐 Retrieving credentials for cluster {cluster_name}...")

                    try:
                        access_key, secret_key, account_id = self.get_iam_credentials_from_cluster(cluster_name, region)
                        is_iam = True
                        self.print_colored(Colors.GREEN, f"✅ Found IAM credentials for cluster {cluster_name}")
                    except Exception as e1:
                        self.print_colored(Colors.YELLOW, f"⚠️ Could not get IAM credentials: {str(e1)}")
                        self.print_colored(Colors.YELLOW, f"⚠️ Attempting to use root credentials...")
                        try:
                            access_key, secret_key, account_id = self.get_root_credentials(cluster_name, region)
                            is_iam = False
                            self.print_colored(Colors.GREEN, f"✅ Found root credentials for cluster {cluster_name}")
                        except Exception as e2:
                            self.print_colored(Colors.RED,
                                               f"❌ Failed to get any credentials for cluster {cluster_name}")
                            self.print_colored(Colors.RED, f"❌ IAM Error: {str(e1)}")
                            self.print_colored(Colors.RED, f"❌ Root Error: {str(e2)}")
                            continue

                    # Verify cluster exists and is accessible
                    if not self.verify_cluster_exists(cluster_name, region, access_key, secret_key):
                        self.print_colored(Colors.RED, f"❌ Could not access cluster {cluster_name}, skipping")
                        continue

                    # Analyze existing components
                    self.analyze_existing_components(cluster_name, region, access_key, secret_key)

                    # Configure the cluster
                    success = self.configure_single_cluster(cluster_name, region, access_key, secret_key)

                    if success:
                        successful_reconfigures += 1
                        self.print_colored(Colors.GREEN, f"✅ Successfully reconfigured cluster {cluster_name}")
                    else:
                        self.print_colored(Colors.YELLOW, f"⚠️ Partial configuration for cluster {cluster_name}")

                except Exception as e:
                    self.logger.error(f"Error reconfiguring cluster {cluster_name}: {str(e)}")
                    self.print_colored(Colors.RED, f"❌ Error reconfiguring cluster {cluster_name}: {str(e)}")
                    continue

            # Final summary
            print(f"\n{'=' * 80}")
            print("📋 RECONFIGURATION SUMMARY")
            print(f"{'=' * 80}")
            print(f"Total clusters processed: {len(cluster_names)}")
            print(f"Successfully reconfigured: {successful_reconfigures}")
            print(f"Failed/Partial: {len(cluster_names) - successful_reconfigures}")

            return successful_reconfigures > 0

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n⚠️ Reconfiguration interrupted by user")
            return False
        except Exception as e:
            self.logger.error(f"Error in cluster reconfiguration: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Error: {str(e)}")
            return False

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

    def select_clusters_from_eks_accounts(self, base_dir='aws/eks'):
        import os
        import glob

        # Step 1: List account folders
        unused_accounts = {'live-host', 'reports'}
        accounts = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d)) and d not in unused_accounts]
        if not accounts:
            print("No account folders found in aws/eks")
            return []

        print("\nAvailable accounts:")
        for idx, acc in enumerate(accounts, 1):
            print(f"{idx}. {acc}")
        print("Enter account numbers (comma, range, or 'all'): ", end='')
        acc_input = input().strip().lower()

        # Step 2: Parse account selection
        def parse_selection(selection, max_count):
            if selection == 'all':
                return list(range(1, max_count + 1))
            indices = set()
            for part in selection.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    indices.update(range(start, end + 1))
                else:
                    indices.add(int(part))
            return sorted(indices)

        try:
            acc_indices = parse_selection(acc_input, len(accounts))
            selected_accounts = [accounts[i - 1] for i in acc_indices]
        except Exception:
            print("Invalid account selection.")
            return []

        # Step 3: For each account, list cluster files and prompt for selection
        selected_clusters = []
        for acc in selected_accounts:
            acc_dir = os.path.join(base_dir, acc)
            cluster_files = glob.glob(os.path.join(acc_dir, "eks_cluster_*"))
            if not cluster_files:
                print(f"No cluster files found in {acc_dir}")
                continue

            print(f"\nAccount: {acc}")
            for idx, f in enumerate(cluster_files, 1):
                print(f"{idx}. {os.path.basename(f)}")
            print("Enter cluster numbers (comma, range, or 'all') for this account: ", end='')
            cl_input = input().strip().lower()
            try:
                cl_indices = parse_selection(cl_input, len(cluster_files))
                for i in cl_indices:
                    fname = os.path.basename(cluster_files[i - 1])
                    # Remove extension if present
                    fname = fname.rsplit('.', 1)[0]
                    parts = fname.split('_')
                    # Join all parts from index 2 to -2 for full cluster name
                    if len(parts) >= 4:
                        cluster_name = '_'.join(parts[2:-2])
                        selected_clusters.append(cluster_name)
            except Exception:
                print("Invalid cluster selection for account", acc)
                continue

        print("\nSelected clusters:")
        for c in selected_clusters:
            print(" -", c)
        confirm = input("Proceed with these clusters? (Y/n): ").strip().lower()
        if confirm == 'n':
            return []

        return selected_clusters

def main():
    """Main function to run the cluster continuation script with interactive input"""
    print("🚀 EKS Cluster Continuation Script with Interactive Input")
    print("=" * 60)

    try:
        cluster_names= ['eks-cluster-account01_clouduser01-us-east-1-wxie']
        continuation = EKSClusterContinuationFromErrors()
        #cluster_names = continuation.select_clusters_from_eks_accounts()
        #success = continuation.continue_cluster_setup_from_errors()
        success = continuation.reconfigure_cluster(cluster_names)

        if success:
            print("\n✅ Cluster continuation completed successfully!")
        else:
            print("\n❌ Cluster continuation failed or was cancelled")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()