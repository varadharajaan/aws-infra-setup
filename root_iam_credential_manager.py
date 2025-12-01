import json
import os
import glob
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import re


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


class AWSCredentialManager:
    """
    Pure credential management class.

    Handles loading, parsing, and selecting AWS credentials from various sources.
    Does not make AWS API calls or decisions about which credentials to use.

    Author: varadharajaan
    Created: 2025-06-25
    """

    def __init__(self, config_dir: str = None):
        """Initialize the credential manager."""
        if config_dir is None:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                if os.access(script_dir, os.R_OK):
                    config_dir = script_dir
                else:
                    config_dir = os.getcwd()
            except Exception:
                config_dir = os.getcwd()

        self.config_dir = config_dir
        self.print_colored(Colors.CYAN, f"[FOLDER] Using config directory: {self.config_dir}")

        # Check directory permissions
        if not os.access(self.config_dir, os.R_OK):
            raise PermissionError(f"Cannot read from directory: {self.config_dir}")

        # Set up file paths
        self.aws_accounts_config_file = os.path.join(config_dir, "aws_accounts_config.json")
        self.iam_dir = os.path.join(config_dir, "aws", "iam")
        self.iam_users_pattern = os.path.join(self.iam_dir, "iam_users_credentials_*.json")

        # Check if required files exist
        self._check_config_files()

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def _check_config_files(self):
        """Check if configuration files exist and are accessible."""
        self.print_colored(Colors.CYAN, "[SCAN] Checking configuration files...")

        # Check aws_accounts_config.json
        if not os.path.exists(self.aws_accounts_config_file):
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: aws_accounts_config.json not found in {self.config_dir}")
        elif not os.access(self.aws_accounts_config_file, os.R_OK):
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: Cannot read aws_accounts_config.json")
        else:
            self.print_colored(Colors.GREEN, f"[OK] Found aws_accounts_config.json")

        # Check aws/iam directory
        if not os.path.exists(self.iam_dir):
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: aws/iam directory not found in {self.config_dir}")
        elif not os.access(self.iam_dir, os.R_OK):
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: Cannot read aws/iam directory")
        else:
            self.print_colored(Colors.GREEN, f"[OK] Found aws/iam directory")
            iam_files = glob.glob(self.iam_users_pattern)
            if not iam_files:
                self.print_colored(Colors.YELLOW, f"[WARN]  Warning: No iam_users_credentials_*.json files found")
            else:
                self.print_colored(Colors.GREEN, f"[OK] Found {len(iam_files)} IAM credential files")

    # === ROOT ACCOUNT METHODS ===

    def load_root_accounts_config(self) -> Optional[Dict]:
        """Load AWS root accounts configuration from aws_accounts_config.json."""
        try:
            if not os.path.exists(self.aws_accounts_config_file):
                self.print_colored(Colors.RED, f"[ERROR] AWS accounts config file not found: {self.aws_accounts_config_file}")
                return None

            if not os.access(self.aws_accounts_config_file, os.R_OK):
                self.print_colored(Colors.RED, f"[ERROR] Cannot read AWS accounts config file")
                return None

            self.print_colored(Colors.CYAN, f"📖 Loading root accounts config...")
            with open(self.aws_accounts_config_file, 'r') as f:
                config = json.load(f)

            if 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] Invalid config file: missing 'accounts' section")
                return None

            accounts_count = len(config['accounts'])
            self.print_colored(Colors.GREEN, f"[OK] Loaded {accounts_count} root accounts")
            return config

        except json.JSONDecodeError as e:
            self.print_colored(Colors.RED, f"[ERROR] Error parsing root accounts config: {e}")
            return None
        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Error loading root accounts config: {e}")
            return None

    def get_root_account_by_key(self, account_key: str) -> Optional[Dict[str, Any]]:
        """Get root account credentials by account key."""
        config = self.load_root_accounts_config()
        if not config:
            return None

        accounts = config.get('accounts', {})
        if account_key not in accounts:
            self.print_colored(Colors.RED, f"[ERROR] Root account '{account_key}' not found")
            return None

        account_data = accounts[account_key]
        default_regions = config.get('user_settings', {}).get('user_regions', ['us-east-1'])

        return {
            'account_key': account_key,
            'account_id': account_data['account_id'],
            'email': account_data['email'],
            'access_key': account_data['access_key'],
            'secret_key': account_data['secret_key'],
            'region': default_regions[0],
            'source_type': 'root',
            'users_per_account': account_data.get('users_per_account', 0)
        }

    def get_root_account_by_id(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get root account credentials by account ID."""
        config = self.load_root_accounts_config()
        if not config:
            return None

        accounts = config.get('accounts', {})
        for account_key, account_data in accounts.items():
            if account_data['account_id'] == account_id:
                default_regions = config.get('user_settings', {}).get('user_regions', ['us-east-1'])

                return {
                    'account_key': account_key,
                    'account_id': account_data['account_id'],
                    'email': account_data['email'],
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key'],
                    'region': default_regions[0],
                    'source_type': 'root',
                    'users_per_account': account_data.get('users_per_account', 0)
                }

        self.print_colored(Colors.RED, f"[ERROR] No root account found for ID: {account_id}")
        return None

    def get_all_root_accounts(self) -> List[Dict[str, Any]]:
        """Get all root account credentials."""
        config = self.load_root_accounts_config()
        if not config:
            return []

        accounts = config.get('accounts', {})
        default_regions = config.get('user_settings', {}).get('user_regions', ['us-east-1'])

        root_accounts = []
        for account_key, account_data in accounts.items():
            root_accounts.append({
                'account_key': account_key,
                'account_id': account_data['account_id'],
                'email': account_data['email'],
                'access_key': account_data['access_key'],
                'secret_key': account_data['secret_key'],
                'region': default_regions[0],
                'source_type': 'root',
                'users_per_account': account_data.get('users_per_account', 0)
            })

        return root_accounts

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n[REGION] Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(f"Select regions (1-{len(self.user_regions)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all" or not choice:
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {len(self.user_regions)} regions")
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(choice, len(self.user_regions))
                if not selected_indices:
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
                return selected_regions

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def get_user_regions(self) -> List[str]:
        """Get user regions from root accounts config."""
        try:
            config = self.load_root_accounts_config()
            if config:
                return config.get('user_settings', {}).get('user_regions', [
                    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
                ])
        except Exception as e:
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def select_root_accounts_interactive(self, allow_multiple: bool = True) -> Optional[List[Dict[str, Any]]]:
        """Interactive root account selection."""
        config = self.load_root_accounts_config()
        if not config:
            return None

        accounts = config.get('accounts', {})
        if not accounts:
            self.print_colored(Colors.RED, "[ERROR] No root accounts found!")
            return None

        self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
        self.print_colored(Colors.YELLOW, "=" * 100)

        account_keys = list(accounts.keys())
        for i, account_key in enumerate(account_keys, 1):
            account = accounts[account_key]
            email = account['email'][:40] + '...' if len(account['email']) > 43 else account['email']

            self.print_colored(Colors.CYAN, f"   {i}. {account_key} (ID: {account['account_id']})")
            self.print_colored(Colors.WHITE, f"      Email: {email}, Users: {account.get('users_per_account', 0)}")

        self.print_colored(Colors.YELLOW, "=" * 100)

        if allow_multiple:
            self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
            self.print_colored(Colors.WHITE, "   • Single: 1")
            self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
            self.print_colored(Colors.WHITE, "   • Range: 1-5")
            self.print_colored(Colors.WHITE, "   • All: all")
            self.print_colored(Colors.YELLOW, "=" * 100)

        while True:
            try:
                if allow_multiple:
                    choice = input(
                        f"Select accounts (1-{len(account_keys)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()
                else:
                    choice = input(f"Select account (1-{len(account_keys)}) or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if allow_multiple:
                    if choice.lower() == "all":
                        selected_keys = account_keys
                    else:
                        selected_indices = self._parse_selection(choice, len(account_keys))
                        if not selected_indices:
                            self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                            continue
                        selected_keys = [account_keys[i - 1] for i in selected_indices]
                else:
                    choice_num = int(choice)
                    if 1 <= choice_num <= len(account_keys):
                        selected_keys = [account_keys[choice_num - 1]]
                    else:
                        self.print_colored(Colors.RED, f"[ERROR] Invalid choice. Please enter 1-{len(account_keys)}")
                        continue

                # Build result list
                selected_accounts = []
                default_regions = config.get('user_settings', {}).get('user_regions', ['us-east-1'])

                for account_key in selected_keys:
                    account_data = accounts[account_key]
                    selected_accounts.append({
                        'account_key': account_key,
                        'account_id': account_data['account_id'],
                        'email': account_data['email'],
                        'access_key': account_data['access_key'],
                        'secret_key': account_data['secret_key'],
                        'region': default_regions[0],
                        'source_type': 'root',
                        'users_per_account': account_data.get('users_per_account', 0)
                    })

                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_accounts)} account(s)")
                return selected_accounts

            except ValueError:
                self.print_colored(Colors.RED, "[ERROR] Invalid input. Please enter a number")

    # === IAM USER METHODS ===

    def scan_iam_credentials_files(self) -> List[Dict[str, Any]]:
        """Scan aws/iam/ directory for IAM user credentials files."""
        try:
            self.print_colored(Colors.CYAN, "[SCAN] Scanning for IAM user credentials files...")

            files = glob.glob(self.iam_users_pattern)
            if not files:
                self.print_colored(Colors.RED, "[ERROR] No IAM credentials files found in aws/iam/")
                return []

            credentials_files = []
            for file_path in files:
                try:
                    filename = os.path.basename(file_path)
                    timestamp_info = self._parse_timestamp_from_filename(filename)
                    if not timestamp_info:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        timestamp_info = {
                            'formatted_timestamp': mod_time.strftime('%Y-%m-%d %H:%M:%S'),
                            'sort_key': mod_time.strftime('%Y%m%d%H%M%S')
                        }

                    with open(file_path, 'r') as f:
                        cred_data = json.load(f)

                    credentials_files.append({
                        'file_path': file_path,
                        'filename': filename,
                        'timestamp': timestamp_info['formatted_timestamp'],
                        'sort_key': timestamp_info['sort_key'],
                        'created_date': cred_data.get('created_date', 'Unknown'),
                        'created_time': cred_data.get('created_time', 'Unknown'),
                        'created_by': cred_data.get('created_by', 'Unknown'),
                        'total_users': cred_data.get('total_users', 0),
                        'data': cred_data
                    })

                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   [WARN]  Error parsing {file_path}: {str(e)}")

            credentials_files.sort(key=lambda x: x['sort_key'], reverse=True)
            self.print_colored(Colors.GREEN, f"[OK] Found {len(credentials_files)} IAM credentials files")
            return credentials_files

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Error scanning IAM credentials files: {str(e)}")
            return []

    def load_iam_users_from_file(self, file_path: str) -> Optional[Dict]:
        """Load IAM users credentials from specified file."""
        try:
            if not os.access(file_path, os.R_OK):
                self.print_colored(Colors.RED, f"[ERROR] Cannot read IAM users file: {file_path}")
                return None

            self.print_colored(Colors.CYAN, f"📖 Loading IAM users from: {os.path.basename(file_path)}")
            with open(file_path, 'r') as f:
                data = json.load(f)

            if 'accounts' not in data:
                self.print_colored(Colors.RED, "[ERROR] Invalid IAM users file: missing 'accounts' section")
                return None

            total_users = sum(len(account_data.get('users', [])) for account_data in data['accounts'].values())
            accounts_count = len(data['accounts'])

            self.print_colored(Colors.GREEN, f"[OK] Loaded {total_users} users from {accounts_count} accounts")
            return data

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Error loading IAM users file: {e}")
            return None

    def get_all_iam_users_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Get all IAM users from a specific file as a flat list."""
        data = self.load_iam_users_from_file(file_path)
        if not data:
            return []

        all_users = []
        for account_key, account_data in data['accounts'].items():
            account_id = account_data['account_id']
            users = account_data.get('users', [])

            for user in users:
                all_users.append({
                    'account_key': account_key,
                    'account_id': account_id,
                    'account_email': account_data.get('account_email', 'Unknown'),
                    'username': user['username'],
                    'region': user['region'],
                    'access_key': user['access_key_id'],
                    'secret_key': user['secret_access_key'],
                    'real_name': user.get('real_user', {}).get('full_name', 'Unknown'),
                    'email': user.get('real_user', {}).get('email', 'Unknown'),
                    'console_password': user.get('console_password', ''),
                    'console_url': user.get('console_url', ''),
                    'source_type': 'iam'
                })

        return all_users

    def select_iam_credentials_file_interactive(self) -> Optional[str]:
        """Interactive IAM credentials file selection."""
        iam_files = self.scan_iam_credentials_files()
        if not iam_files:
            return None

        self.print_colored(Colors.YELLOW, f"\n[OPENFOLDER] Available IAM credentials files (sorted by timestamp):")
        self.print_colored(Colors.YELLOW, f"=" * 100)

        for i, file_info in enumerate(iam_files, 1):
            timestamp = file_info['timestamp']
            created_by = file_info['created_by']
            total_users = file_info['total_users']
            filename = file_info['filename']
            default_marker = " (LATEST - DEFAULT)" if i == 1 else ""

            self.print_colored(Colors.CYAN, f"   {i}. {timestamp} - {filename}")
            self.print_colored(Colors.WHITE,
                               f"      Created by: {created_by}, Total users: {total_users}{default_marker}")

        self.print_colored(Colors.YELLOW, f"=" * 100)

        while True:
            try:
                choice = input(
                    f"Select IAM credentials file (1-{len(iam_files)}) [default: 1 (latest)] or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if not choice:
                    choice = "1"

                choice_num = int(choice)
                if 1 <= choice_num <= len(iam_files):
                    selected_file = iam_files[choice_num - 1]
                    self.print_colored(Colors.GREEN, f"[OK] Selected: {selected_file['filename']}")
                    return selected_file['file_path']
                else:
                    self.print_colored(Colors.RED, f"[ERROR] Invalid choice. Please enter 1-{len(iam_files)}")

            except ValueError:
                self.print_colored(Colors.RED, "[ERROR] Invalid input. Please enter a number")

    def select_iam_users_interactive(self, file_path: str) -> Optional[List[Dict[str, Any]]]:
        """Interactive IAM user selection from a specific file."""
        all_users = self.get_all_iam_users_from_file(file_path)
        if not all_users:
            return None

        self.print_colored(Colors.YELLOW, "\n👤 Available IAM Users:")
        self.print_colored(Colors.YELLOW, "=" * 120)

        # Group by account for display
        current_account = None
        for i, user in enumerate(all_users, 1):
            if user['account_key'] != current_account:
                current_account = user['account_key']
                self.print_colored(Colors.PURPLE, f"\n[LIST] Account: {current_account} (ID: {user['account_id']})")

            real_name_display = user['real_name'][:25] + '...' if len(user['real_name']) > 28 else user['real_name']
            email_display = user['email'][:35] + '...' if len(user['email']) > 38 else user['email']

            self.print_colored(Colors.CYAN, f"   {i}. {user['username']} ({user['region']})")
            self.print_colored(Colors.WHITE, f"      Name: {real_name_display}, Email: {email_display}")

        self.print_colored(Colors.YELLOW, "=" * 120)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 120)

        while True:
            try:
                choice = input(
                    f"Select users (1-{len(all_users)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None
                elif choice.lower() == "all":
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {len(all_users)} users")
                    return all_users
                else:
                    selected_indices = self._parse_selection(choice, len(all_users))
                    if selected_indices:
                        selected_users = [all_users[i - 1] for i in selected_indices]
                        self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_users)} users")
                        return selected_users
                    else:
                        self.print_colored(Colors.RED, "[ERROR] Invalid selection format. Examples: 1, 1,3,5, 1-5, all")

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {e}")

    # === UTILITY METHODS ===

    def _parse_timestamp_from_filename(self, filename: str) -> Optional[Dict[str, str]]:
        """Parse timestamp from various filename patterns."""

        # Pattern 1: iam_users_credentials_YYYYMMDD_HHMMSS.json
        timestamp_match = re.search(r'_(\d{8})_(\d{6})\.json$', filename)
        if timestamp_match:
            date_str = timestamp_match.group(1)
            time_str = timestamp_match.group(2)
            formatted_timestamp = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
            sort_key = f"{date_str}{time_str}"
            return {'formatted_timestamp': formatted_timestamp, 'sort_key': sort_key}

        # Pattern 2: iam_users_credentials_YYYY-MM-DD_HH-MM-SS.json
        timestamp_match = re.search(r'_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.json$', filename)
        if timestamp_match:
            date_str = timestamp_match.group(1)
            time_str = timestamp_match.group(2)
            formatted_timestamp = f"{date_str} {time_str.replace('-', ':')}"
            sort_key = date_str.replace('-', '') + time_str.replace('-', '')
            return {'formatted_timestamp': formatted_timestamp, 'sort_key': sort_key}

        # Pattern 3: Unix timestamp
        timestamp_match = re.search(r'_(\d{10})\.json$', filename)
        if timestamp_match:
            unix_timestamp = int(timestamp_match.group(1))
            dt = datetime.fromtimestamp(unix_timestamp)
            return {
                'formatted_timestamp': dt.strftime('%Y-%m-%d %H:%M:%S'),
                'sort_key': dt.strftime('%Y%m%d%H%M%S')
            }

        return None

    def _parse_selection(self, selection: str, max_count: int) -> Optional[List[int]]:
        """Parse user selection string into list of indices."""
        try:
            indices = []
            parts = [part.strip() for part in selection.split(',')]

            for part in parts:
                if '-' in part:
                    range_parts = part.split('-', 1)
                    if len(range_parts) != 2:
                        return None

                    start, end = range_parts
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())

                    if 1 <= start_idx <= max_count and 1 <= end_idx <= max_count and start_idx <= end_idx:
                        indices.extend(range(start_idx, end_idx + 1))
                    else:
                        return None
                else:
                    idx = int(part)
                    if 1 <= idx <= max_count:
                        indices.append(idx)
                    else:
                        return None

            return sorted(list(set(indices)))

        except ValueError:
            return None