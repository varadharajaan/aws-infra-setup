import os
import glob
import json
import boto3
from datetime import datetime
import re
from typing import Dict, List, Optional, Any
from root_iam_credential_manager import AWSCredentialManager, Colors


class EKSLambdaScaler:
    """
    Tool to scale EKS clusters via Lambda functions.

    Manages the process of discovering EKS cluster files, selecting clusters,
    and triggering Lambda scale up/down events.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the EKS Lambda Scaler."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir

        # Set up directory paths
        self.eks_dir = os.path.join(self.config_dir, "aws", "eks")

        # Lambda event templates
        self.lambda_scale_up_file = os.path.join(self.config_dir, "lambda_scale_up_event.json")
        self.lambda_scale_down_file = os.path.join(self.config_dir, "lambda_scale_down_event.json")

        self._check_required_files()

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def select_iam_credentials_file(self) -> Optional[str]:
        """Interactive IAM credentials file selection with timestamp sorting."""
        iam_files = self.cred_manager.scan_iam_credentials_files()

        if not iam_files:
            self.print_colored(Colors.RED, "[ERROR] No IAM credential files found")
            return None

        if len(iam_files) == 1:
            self.print_colored(Colors.GREEN, f"[OK] Using single IAM credentials file: {iam_files[0]['filename']}")
            return iam_files[0]['file_path']

        # Sort by timestamp (newest first)
        # Handle both string and datetime timestamp formats
        def get_sort_key(file_info):
            timestamp = file_info['timestamp']
            if isinstance(timestamp, str):
                try:
                    # Try to parse string timestamp
                    return datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    try:
                        return datetime.strptime(timestamp, '%Y%m%d_%H%M%S')
                    except ValueError:
                        # If parsing fails, use file modification time
                        return datetime.fromtimestamp(os.path.getmtime(file_info['file_path']))
            return timestamp

        sorted_files = sorted(iam_files, key=get_sort_key, reverse=True)

        self.print_colored(Colors.YELLOW, f"\n[FOLDER] Found {len(sorted_files)} IAM credential files:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, file_info in enumerate(sorted_files, 1):
            timestamp = file_info['timestamp']

            # Format timestamp for display
            if isinstance(timestamp, str):
                timestamp_str = timestamp  # Use as-is if it's already a string
            else:
                timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')

            filename = file_info['filename']

            # Mark the latest (first) file as default
            if i == 1:
                self.print_colored(Colors.GREEN, f"   {i}. [{timestamp_str}] {filename} (DEFAULT)")
            else:
                self.print_colored(Colors.CYAN, f"   {i}. [{timestamp_str}] {filename}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[TIP] Press Enter to use default (latest file) or select by number")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(
                    f"Select IAM credentials file (1-{len(sorted_files)}, Enter for default) or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                # Use default (latest file)
                if choice == '':
                    selected_file = sorted_files[0]
                    self.print_colored(Colors.GREEN, f"[OK] Using default: {selected_file['filename']}")
                    return selected_file['file_path']

                # Parse selection
                selection = int(choice)
                if 1 <= selection <= len(sorted_files):
                    selected_file = sorted_files[selection - 1]
                    self.print_colored(Colors.GREEN, f"[OK] Selected: {selected_file['filename']}")
                    return selected_file['file_path']
                else:
                    self.print_colored(Colors.RED, f"[ERROR] Invalid selection. Please enter 1-{len(sorted_files)}")

            except ValueError:
                self.print_colored(Colors.RED, "[ERROR] Invalid input. Please enter a number")
            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def _check_required_files(self):
        """Check if required files exist."""
        if not os.path.exists(self.eks_dir):
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: AWS EKS directory not found: {self.eks_dir}")

        if not os.path.exists(self.lambda_scale_up_file):
            self.print_colored(Colors.YELLOW,
                               f"[WARN]  Warning: Lambda scale up event file not found: {self.lambda_scale_up_file}")

        if not os.path.exists(self.lambda_scale_down_file):
            self.print_colored(Colors.YELLOW,
                               f"[WARN]  Warning: Lambda scale down event file not found: {self.lambda_scale_down_file}")

    def scan_eks_files(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scan for EKS cluster files and organize them by date.

        Returns:
            Dict mapping dates to lists of file information
        """
        self.print_colored(Colors.CYAN, f"[SCAN] Scanning for EKS cluster files...")

        # Look for all eks cluster files under all account directories
        eks_pattern = os.path.join(self.eks_dir, "*", "eks_cluster_*-*-*.json")
        all_files = glob.glob(eks_pattern)

        if not all_files:
            self.print_colored(Colors.RED, f"[ERROR] No EKS cluster files found")
            return {}

        # Group files by date (day)
        files_by_date = {}
        for file_path in all_files:
            try:
                # Extract timestamp from filename
                filename = os.path.basename(file_path)
                match = re.search(r'(\d{4}-\d{2}-\d{2})(?:_\d{2}-\d{2}-\d{2})?\.json$', filename)

                if match:
                    date_key = match.group(1)  # YYYY-MM-DD
                else:
                    # Use file modification date if pattern not found
                    mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    date_key = mod_time.strftime('%Y-%m-%d')

                # Extract account and cluster info from filename
                account_match = re.search(r'eks_cluster_(.*?)(?:_clouduser|\.json|-us)', filename)
                account_info = account_match.group(1) if account_match else "unknown"

                file_info = {
                    'file_path': file_path,
                    'filename': filename,
                    'account_info': account_info,
                    'date': date_key
                }

                if date_key not in files_by_date:
                    files_by_date[date_key] = []

                files_by_date[date_key].append(file_info)

            except Exception as e:
                self.print_colored(Colors.YELLOW, f"[WARN]  Error processing {file_path}: {str(e)}")

        # Sort dates in reverse order (newest first)
        sorted_files_by_date = {
            date: files
            for date, files in sorted(files_by_date.items(), key=lambda x: x[0], reverse=True)
        }

        total_files = sum(len(files) for files in sorted_files_by_date.values())
        self.print_colored(Colors.GREEN,
                           f"[OK] Found {total_files} EKS cluster files across {len(sorted_files_by_date)} dates")

        return sorted_files_by_date

    def select_dates_interactive(self, files_by_date: Dict[str, List[Dict[str, Any]]]) -> Optional[List[str]]:
        """Interactive date selection for EKS files."""
        if not files_by_date:
            self.print_colored(Colors.RED, "[ERROR] No EKS dates available")
            return None

        dates = list(files_by_date.keys())

        self.print_colored(Colors.YELLOW, "\n[DATE] Available EKS Cluster File Dates:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, date in enumerate(dates, 1):
            file_count = len(files_by_date[date])
            self.print_colored(Colors.CYAN, f"   {i}. {date}")
            self.print_colored(Colors.WHITE, f"      Files: {file_count}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(
                    f"Select dates (1-{len(dates)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all":
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {len(dates)} dates")
                    return dates

                selected_indices = self.cred_manager._parse_selection(choice, len(dates))
                if not selected_indices:
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                    continue

                selected_dates = [dates[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_dates)} dates")
                return selected_dates

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def load_clusters_from_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Load EKS cluster information from files.

        Args:
            files: List of file information dictionaries

        Returns:
            List of cluster information dictionaries
        """
        clusters = []

        for file_info in files:
            file_path = file_info['file_path']

            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Extract account details from the path
                account_dir = os.path.basename(os.path.dirname(file_path))

                # Check if this is the new JSON structure (with cluster_info)
                if 'cluster_info' in data:
                    # Get account info
                    account_info = data.get('account_info', {})
                    account_id = account_info.get('account_id', account_dir)

                    # Get cluster details
                    cluster_info = data.get('cluster_info', {})

                    # Create a cluster entry
                    clusters.append({
                        'account_id': account_id,
                        'account_key': account_info.get('account_name', account_dir),
                        'region': account_info.get('region', 'unknown'),
                        'name': cluster_info.get('cluster_name', 'unknown'),
                        'status': 'ACTIVE',  # Default status since it's not in the JSON
                        'created_at': data.get('timestamp', 'unknown'),
                        'file_path': file_path,
                        'cluster': cluster_info,
                        'source_file': file_info,
                        # Additional useful information from the JSON file
                        'eks_version': cluster_info.get('eks_version', 'unknown'),
                        'nodegroups': cluster_info.get('nodegroups_created', []),
                        'features': data.get('features_status', {})
                    })
                # Try the old format with clusters array
                elif 'clusters' in data:
                    for cluster in data['clusters']:
                        # Store both file info and cluster info (old format)
                        clusters.append({
                            'account_id': data.get('account_id', account_dir),
                            'account_key': data.get('account_key', account_dir),
                            'region': cluster.get('region', 'unknown'),
                            'name': cluster.get('name', 'unknown'),
                            'status': cluster.get('status', 'unknown'),
                            'created_at': cluster.get('created_at', 'unknown'),
                            'file_path': file_path,
                            'cluster': cluster,
                            'source_file': file_info
                        })

            except Exception as e:
                self.print_colored(Colors.YELLOW, f"[WARN]  Error loading clusters from {file_path}: {str(e)}")

        return clusters

    def select_clusters_interactive(self, clusters: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Interactive cluster selection."""
        if not clusters:
            self.print_colored(Colors.RED, "[ERROR] No clusters found")
            return None

        self.print_colored(Colors.YELLOW, "\n[START] Available EKS Clusters:")
        self.print_colored(Colors.YELLOW, "=" * 100)

        # Create a flat list for proper indexing while still grouping for display
        clusters_by_account = {}
        for cluster in clusters:
            account_key = f"{cluster['account_key']} ({cluster['account_id']})"
            if account_key not in clusters_by_account:
                clusters_by_account[account_key] = []
            clusters_by_account[account_key].append(cluster)

        # Display clusters grouped by account but maintain correct indexing
        for account, account_clusters in clusters_by_account.items():
            self.print_colored(Colors.PURPLE, f"\n[LIST] Account: {account}")

            for cluster in account_clusters:
                # Find the correct index in the original clusters list
                cluster_index = clusters.index(cluster) + 1
                self.print_colored(Colors.CYAN, f"   {cluster_index}. {cluster['name']} ({cluster['region']})")
                self.print_colored(Colors.WHITE, f"      Status: {cluster['status']}, Created: {cluster['created_at']}")

        total_clusters = len(clusters)
        self.print_colored(Colors.YELLOW, "=" * 100)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 100)

        while True:
            try:
                choice = input(
                    f"Select clusters (1-{total_clusters}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all":
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {total_clusters} clusters")
                    return clusters

                selected_indices = self.cred_manager._parse_selection(choice, total_clusters)
                if not selected_indices:
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                    continue

                selected_clusters = [clusters[i - 1] for i in selected_indices]

                # Show what was actually selected for confirmation
                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_clusters)} clusters:")
                for cluster in selected_clusters:
                    self.print_colored(Colors.WHITE, f"   • {cluster['name']} ({cluster['account_key']})")

                return selected_clusters

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def get_lambda_event_template(self, action: str) -> Optional[Dict[str, Any]]:
        """Get the Lambda event template for the specified action."""
        template_file = self.lambda_scale_up_file if action == "up" else self.lambda_scale_down_file

        try:
            if not os.path.exists(template_file):
                self.print_colored(Colors.RED, f"[ERROR] Lambda {action} event template not found: {template_file}")
                return None

            with open(template_file, 'r') as f:
                data = json.load(f)

            return data

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Error loading Lambda event template: {str(e)}")
            return None

    def get_lambda_function_name(self, cluster_name: str) -> str:
        """Derive Lambda function name from cluster name."""
        # Extract the 4-character suffix if it exists
        match = re.search(r'([a-zA-Z0-9]{4})$', cluster_name)
        suffix = match.group(1) if match else "main"

        return f"eks-scale-{suffix}"

    def invoke_lambda(self, cluster_info: Dict[str, Any], action: str, aws_creds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invoke Lambda function to scale the cluster.

        Args:
            cluster_info: Cluster information
            action: "up" or "down"
            aws_creds: AWS credentials

        Returns:
            Dictionary with result information
        """
        try:
            # Get Lambda event template
            event_template = self.get_lambda_event_template(action)
            if not event_template:
                return {'success': False, 'error': 'Event template not found'}

            # Customize event for this cluster
            event = event_template.copy()
            # Add any necessary customization here based on the cluster

            # Get Lambda function name
            function_name = self.get_lambda_function_name(cluster_info['name'])

            # Create Lambda client
            lambda_client = boto3.client(
                'lambda',
                region_name=cluster_info['region'],
                aws_access_key_id=aws_creds['access_key'],
                aws_secret_access_key=aws_creds['secret_key']
            )

            # Invoke Lambda
            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(event)
            )

            # Read and parse response
            payload = json.loads(response['Payload'].read().decode('utf-8'))

            return {
                'success': response['StatusCode'] == 200,
                'function_name': function_name,
                'response': payload,
                'status_code': response['StatusCode']
            }

        except Exception as e:
            return {
                'success': False,
                'function_name': self.get_lambda_function_name(cluster_info['name']),
                'error': str(e)
            }

    def get_credentials_for_cluster(self, cluster_info: Dict[str, Any], selected_iam_file: str = None) -> Optional[
        Dict[str, Any]]:
        """Get AWS credentials for the cluster's account."""
        account_id = cluster_info['account_id']
        account_key = cluster_info['account_key']
        cluster_name = cluster_info['name']

        # Determine if this is a root or IAM user cluster
        is_root_cluster = cluster_name.startswith('root-')

        if is_root_cluster:
            return self.cred_manager.get_root_account_by_id(account_id) or self.cred_manager.get_root_account_by_key(
                account_key)
        else:
            # Extract username from cluster name (if format is account_clouduser)
            user_match = re.search(r'_clouduser(\d+)', cluster_name)

            # Use selected IAM file if provided
            if selected_iam_file:
                all_users = self.cred_manager.get_all_iam_users_from_file(selected_iam_file)
                for user in all_users:
                    if user['account_id'] == account_id:
                        # If we have a specific username match, prioritize that user
                        if user_match and f"clouduser{user_match.group(1)}" == user['username']:
                            return user

                # If we didn't find a specific match but have users for this account, return the first one
                for user in all_users:
                    if user['account_id'] == account_id:
                        return user

            # Fall back to root credentials
            return self.cred_manager.get_root_account_by_id(account_id) or self.cred_manager.get_root_account_by_key(
                account_key)

    def run(self):
        """Main execution flow for the EKS Lambda scaler."""
        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[START] EKS Lambda Cluster Scaling Tool")
        self.print_colored(Colors.YELLOW, "=" * 80)

        # Scan and select dates
        selected_iam_file = self.select_iam_credentials_file()
        if not selected_iam_file:
            self.print_colored(Colors.RED, "[ERROR] No IAM credentials file selected, exiting...")
            return

        files_by_date = self.scan_eks_files()
        if not files_by_date:
            return

        selected_dates = self.select_dates_interactive(files_by_date)
        if not selected_dates:
            self.print_colored(Colors.RED, "[ERROR] No dates selected, exiting...")
            return

        # Collect all files from selected dates
        selected_files = []
        for date in selected_dates:
            selected_files.extend(files_by_date[date])

        # Load clusters from files
        all_clusters = self.load_clusters_from_files(selected_files)
        if not all_clusters:
            self.print_colored(Colors.RED, "[ERROR] No clusters found in selected files")
            return

        # Select clusters
        selected_clusters = self.select_clusters_interactive(all_clusters)
        if not selected_clusters:
            self.print_colored(Colors.RED, "[ERROR] No clusters selected, exiting...")
            return

        # Choose scale action
        self.print_colored(Colors.YELLOW, "\n[CONFIG] Select Scaling Action:")
        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.CYAN, "   1. Scale Up")
        self.print_colored(Colors.CYAN, "   2. Scale Down")
        self.print_colored(Colors.YELLOW, "=" * 80)

        action = None
        while action is None:
            choice = input("Select action (1 for Scale Up, 2 for Scale Down) or 'q' to quit: ").strip()

            if choice.lower() == 'q':
                return

            if choice == '1':
                action = 'up'
            elif choice == '2':
                action = 'down'
            else:
                self.print_colored(Colors.RED, "[ERROR] Invalid choice. Please enter 1 or 2")

        action_display = "Scale Up" if action == "up" else "Scale Down"

        # Confirm before proceeding
        self.print_colored(Colors.YELLOW, f"\n[WARN]  You are about to {action_display} {len(selected_clusters)} clusters:")
        for cluster in selected_clusters[:5]:
            self.print_colored(Colors.WHITE, f"   • {cluster['name']} ({cluster['account_key']})")

        if len(selected_clusters) > 5:
            self.print_colored(Colors.WHITE, f"   • ... and {len(selected_clusters) - 5} more")

        confirmation = input(f"\nConfirm {action_display} for all selected clusters? (y/n): ").strip().lower()
        if confirmation != 'y':
            self.print_colored(Colors.RED, "[ERROR] Operation canceled")
            return

        # Process clusters
        self.print_colored(Colors.YELLOW, f"\n[START] Executing {action_display} on {len(selected_clusters)} clusters...")

        results = {
            'success': [],
            'failed': []
        }

        for i, cluster in enumerate(selected_clusters, 1):
            self.print_colored(Colors.CYAN,
                               f"[{i}/{len(selected_clusters)}] Processing: {cluster['name']} ({cluster['account_key']})")

            # Get credentials for this cluster
            creds = self.get_credentials_for_cluster(cluster)
            if not creds:
                self.print_colored(Colors.RED, f"   [ERROR] Failed to get credentials for account {cluster['account_id']}")
                results['failed'].append({
                    'cluster': cluster,
                    'error': 'No credentials found'
                })
                continue

            # Invoke Lambda
            result = self.invoke_lambda(cluster, action, creds)

            if result['success']:
                function_name = result.get('function_name', 'unknown')
                self.print_colored(Colors.GREEN, f"   [OK] Successfully invoked Lambda: {function_name}")
                results['success'].append({
                    'cluster': cluster,
                    'result': result
                })
            else:
                error = result.get('error', 'unknown error')
                function_name = result.get('function_name', 'unknown')
                self.print_colored(Colors.RED, f"   [ERROR] Failed to invoke Lambda {function_name}: {error}")
                results['failed'].append({
                    'cluster': cluster,
                    'error': error
                })

        # Summary
        self.print_colored(Colors.YELLOW, "\n[STATS] Summary:")
        self.print_colored(Colors.GREEN,
                           f"   [OK] Successfully executed {action_display} on {len(results['success'])} clusters")

        if results['failed']:
            self.print_colored(Colors.RED,
                               f"   [ERROR] Failed to execute {action_display} on {len(results['failed'])} clusters")

if __name__ == "__main__":
    scaler = EKSLambdaScaler()
    scaler.run()