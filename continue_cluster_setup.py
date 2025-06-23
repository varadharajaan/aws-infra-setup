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
from eks_cluster_manager import EKSClusterManager, Colors
from complete_autoscaler_deployment import CompleteAutoscalerDeployer


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

    def print_colored(self, color: str, message: str) -> None:
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
        """Extract cluster name and region from cluster info"""
        cluster_name = cluster_info['cluster_name']

        # Try to extract region from cluster name
        parts = cluster_name.split('-')
        region = 'us-east-1'  # Default region

        for part in parts:
            if part.startswith('us-') or part.startswith('eu-') or part.startswith('ap-') or part.startswith(
                    'ca-') or part.startswith('sa-'):
                region = part
                break

        return cluster_name, region

    def get_credentials_for_cluster(self, cluster_name: str, region: str) -> Tuple[str, str]:
        """Get AWS credentials for the cluster based on cluster name pattern"""
        print(f"\n" + "=" * 60)
        print(f"🔐 CREDENTIALS FOR CLUSTER: {cluster_name}")
        print("=" * 60)

        # Try to determine account type from cluster name
        if 'root-account' in cluster_name.lower():
            account_type = 'root'
            self.print_colored('CYAN', "📋 Detected: Root Account (from cluster name)")
        else:
            account_type = 'iam'
            self.print_colored('CYAN', "📋 Detected: IAM User (from cluster name)")

        # Ask user to confirm or override
        print(f"\nAccount type detected: {account_type.upper()}")
        override = input("Override account type? (r for Root, i for IAM, Enter to keep detected): ").strip().lower()

        if override == 'r':
            account_type = 'root'
        elif override == 'i':
            account_type = 'iam'

        if account_type == 'root':
            return self.get_root_credentials(cluster_name, region)
        else:
            return self.get_iam_credentials(cluster_name, region)

    def get_root_credentials(self, cluster_name: str, region: str) -> Tuple[str, str]:
        """Get root account credentials"""
        if not self.aws_accounts_config:
            raise ValueError("No AWS accounts configuration found")

        # Try to match by region first
        matching_accounts = []
        for account_name, account_data in self.aws_accounts_config.items():
            if account_data.get('region') == region:
                matching_accounts.append((account_name, account_data))

        if not matching_accounts:
            # If no region match, show all accounts
            matching_accounts = list(self.aws_accounts_config.items())

        if len(matching_accounts) == 1:
            # Auto-select if only one account
            account_name, account_data = matching_accounts[0]
            self.print_colored('GREEN',
                               f"✅ Auto-selected account: {account_name} (Region: {account_data.get('region', 'unknown')})")
        else:
            # Let user choose
            print(f"\nAvailable accounts for region {region}:")
            for i, (account_name, account_data) in enumerate(matching_accounts, 1):
                account_id = account_data.get('account_id', 'Unknown')
                account_region = account_data.get('region', 'Unknown')
                print(f"{i}. {account_name} (ID: {account_id}, Region: {account_region})")

            while True:
                try:
                    choice = input(f"Select account (1-{len(matching_accounts)}): ").strip()
                    choice_num = int(choice)
                    if 1 <= choice_num <= len(matching_accounts):
                        account_name, account_data = matching_accounts[choice_num - 1]
                        break
                    else:
                        self.print_colored('RED', f"❌ Please enter a number between 1 and {len(matching_accounts)}")
                except ValueError:
                    self.print_colored('RED', "❌ Please enter a valid number")

        admin_access_key = account_data.get('access_key', '')
        admin_secret_key = account_data.get('secret_key', '')

        if not admin_access_key or not admin_secret_key:
            raise ValueError(f"Incomplete credentials for account {account_name}")

        return admin_access_key, admin_secret_key

    def get_iam_credentials(self, cluster_name: str, region: str) -> Tuple[str, str]:
        """Get IAM user credentials"""
        # Try to extract username from cluster name
        suggested_username = None

        # Look for common patterns in cluster names
        parts = cluster_name.split('-')
        for i, part in enumerate(parts):
            if part in ['cluster', 'eks'] and i > 0:
                # Username might be before 'cluster' or 'eks'
                suggested_username = parts[i - 1]
                break

        if suggested_username:
            print(f"\nSuggested username from cluster name: {suggested_username}")
            use_suggested = input(f"Use '{suggested_username}' as username? (Y/n): ").strip().lower()
            if use_suggested != 'n':
                username = suggested_username
            else:
                username = input("Enter IAM username: ").strip()
        else:
            username = input("Enter IAM username: ").strip()

        if not username:
            raise ValueError("Username cannot be empty")

        # Load IAM credentials
        user_data = self.get_iam_credentials_file(username)
        if not user_data:
            raise ValueError(f"No credentials found for user {username}")

        admin_access_key = user_data.get('access_key', '')
        admin_secret_key = user_data.get('secret_key', '')

        if not admin_access_key or not admin_secret_key:
            raise ValueError(f"Incomplete credentials for user {username}")

        return admin_access_key, admin_secret_key

    def get_iam_credentials_file(self, username: str) -> Optional[dict]:
        """Get IAM credentials file for the specified username"""
        try:
            # Look for IAM credentials files
            iam_dir = "aws/iam"
            if not os.path.exists(iam_dir):
                self.print_colored('RED', f"❌ IAM directory not found: {iam_dir}")
                return None

            # Find credential files for this user
            pattern = f"{iam_dir}/iam_users_credentials_*.json"
            credential_files = glob.glob(pattern)

            if not credential_files:
                self.print_colored('RED', f"❌ No IAM credential files found in {iam_dir}")
                return None

            # Sort files by timestamp (newest first)
            credential_files.sort(reverse=True)

            # Try to find the user in the latest file first
            for file_path in credential_files:
                try:
                    with open(file_path, 'r') as f:
                        all_users = json.load(f)

                    # Find the specific user
                    for user in all_users:
                        if user.get('username', '').lower() == username.lower():
                            filename = os.path.basename(file_path)
                            timestamp_part = filename.replace('iam_users_credentials_', '').replace('.json', '')
                            try:
                                timestamp_obj = datetime.strptime(timestamp_part, '%Y%m%d_%H%M%S')
                                formatted_timestamp = timestamp_obj.strftime('%Y-%m-%d %H:%M:%S')
                            except:
                                formatted_timestamp = timestamp_part

                            self.print_colored('GREEN',
                                               f"✅ Found credentials for {username} in file: {filename} ({formatted_timestamp})")
                            return user

                except Exception as e:
                    self.logger.error(f"Error reading IAM file {file_path}: {str(e)}")
                    continue

            self.print_colored('RED', f"❌ User '{username}' not found in any credential files")
            return None

        except Exception as e:
            self.logger.error(f"Error loading IAM credentials: {str(e)}")
            self.print_colored('RED', f"❌ Error loading IAM credentials: {str(e)}")
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
                'account_id': cluster['arn'].split(':')[4]
            }

            if cluster['status'] != 'ACTIVE':
                self.print_colored('RED', f"❌ Cluster is in {cluster['status']} state, not ACTIVE")
                return False

            self.print_colored('GREEN', f"✅ Cluster {cluster_name} is ACTIVE")
            self.print_colored('CYAN', f"   Version: {cluster['version']}")
            self.print_colored('CYAN', f"   Created: {self.cluster_info['created_at']}")
            self.print_colored('CYAN', f"   Account: {self.cluster_info['account_id']}")

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

    def show_main_menu(self) -> str:
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
        print("0. Exit")
        print("=" * 60)

        choice = input("Enter your choice (0-9): ").strip()
        return choice

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
                    self.analyze_existing_components(cluster_name, region, admin_access_key, admin_secret_key)

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
            while True:
                # Display current status
                self.display_cluster_status()

                # Show menu and get choice
                choice = self.show_main_menu()

                if choice == '0':
                    self.print_colored('GREEN', f"✅ Configuration completed for {cluster_name}")
                    break
                elif choice == '1':
                    self.configure_nodegroups(cluster_name, region, access_key, secret_key)
                elif choice == '2':
                    self.configure_addons(cluster_name, region, access_key, secret_key)
                elif choice == '3':
                    self.configure_container_insights(cluster_name, region, access_key, secret_key)
                elif choice == '4':
                    self.configure_cluster_autoscaler(cluster_name, region, access_key, secret_key)
                elif choice == '5':
                    self.configure_scheduled_scaling(cluster_name, region, access_key, secret_key)
                elif choice == '6':
                    self.configure_cloudwatch_monitoring(cluster_name, region, access_key, secret_key)
                elif choice == '7':
                    self.configure_cost_monitoring(cluster_name, region, access_key, secret_key)
                elif choice == '8':
                    self.generate_user_instructions(cluster_name, region, access_key, secret_key)
                elif choice == '9':
                    self.run_health_check(cluster_name, region, access_key, secret_key)
                else:
                    self.print_colored('YELLOW', "⚠️  Invalid choice. Please try again.")

                # Re-analyze components after each action
                self.analyze_existing_components(cluster_name, region, access_key, secret_key)

                input("\nPress Enter to continue...")

            return True

        except Exception as e:
            self.logger.error(f"Error configuring cluster {cluster_name}: {str(e)}")
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

            if strategy == 'on-demand':
                success = self.eks_manager.create_ondemand_nodegroup(
                    eks_client, cluster_name, nodegroup_config['name'], node_role_arn,
                    selected_subnets, nodegroup_config['ami_type'],
                    nodegroup_config['instance_selections']['on-demand'],
                    nodegroup_config['min_size'], nodegroup_config['desired_size'], nodegroup_config['max_size']
                )
            elif strategy == 'spot':
                success = self.eks_manager.create_spot_nodegroup(
                    eks_client, cluster_name, nodegroup_config['name'], node_role_arn,
                    selected_subnets, nodegroup_config['ami_type'],
                    nodegroup_config['instance_selections']['spot'],
                    nodegroup_config['min_size'], nodegroup_config['desired_size'], nodegroup_config['max_size']
                )
            elif strategy == 'mixed':
                success = self.eks_manager.create_mixed_nodegroup(
                    eks_client, cluster_name, nodegroup_config['name'], node_role_arn,
                    selected_subnets, nodegroup_config['ami_type'],
                    nodegroup_config['instance_selections'],
                    nodegroup_config['min_size'], nodegroup_config['desired_size'], nodegroup_config['max_size']
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

            credential_info = CredentialInfo(
                account_name=f"account-{self.cluster_info['account_id']}",
                account_id=self.cluster_info['account_id'],
                email='user@example.com',
                access_key=access_key,
                secret_key=secret_key,
                credential_type='iam',
                regions=[region],
                username='cluster-user'
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
                credential_info, cluster_name, region, 'cluster-user', nodegroup_configs
            )

            self.print_colored('GREEN', "✅ User instructions generated successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error generating user instructions: {str(e)}")
            self.print_colored('RED', f"❌ Error generating user instructions: {str(e)}")
            return False

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


def main():
    """Main function to run the cluster continuation script with interactive input"""
    print("🚀 EKS Cluster Continuation Script with Interactive Input")
    print("=" * 60)

    try:
        continuation = EKSClusterContinuationFromErrors()
        success = continuation.continue_cluster_setup_from_errors()

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