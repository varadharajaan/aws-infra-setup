#!/usr/bin/env python3
"""
Ultra AWS Redshift Cleanup Manager
Comprehensive Redshift cleanup across multiple AWS accounts and regions
- Deletes Redshift Clusters
- Deletes Manual Snapshots
- Deletes Cluster Subnet Groups
- Deletes Cluster Parameter Groups
- Deletes Event Subscriptions
- Deletes HSM Configurations
- Deletes Endpoint Access
"""

import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import json
import time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager
from text_symbols import Symbols


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    END = '\033[0m'


class UltraCleanupRedshiftManager:
    """Manager for comprehensive Redshift cleanup operations"""

    def __init__(self):
        """Initialize the Redshift cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'redshift')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'redshift_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_clusters': [],
            'deleted_snapshots': [],
            'deleted_subnet_groups': [],
            'deleted_parameter_groups': [],
            'deleted_event_subscriptions': [],
            'deleted_endpoint_access': [],
            'failed_deletions': [],
            'errors': []
        }
        
        # Prompt user for snapshot creation
        self.create_final_snapshot = False

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_cluster(self, redshift_client, cluster_id, region, account_key):
        """Delete a Redshift cluster"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting cluster: {cluster_id}")
            
            # Get cluster info
            try:
                cluster_response = redshift_client.describe_clusters(ClusterIdentifier=cluster_id)
                cluster = cluster_response['Clusters'][0]
                cluster_status = cluster.get('ClusterStatus', 'unknown')
                
                # Skip if already deleting
                if cluster_status == 'deleting':
                    self.print_colored(Colors.YELLOW, f"{Symbols.SKIP} Cluster already deleting: {cluster_id}")
                    return True
            except ClientError:
                pass
            
            # Delete cluster
            delete_params = {
                'ClusterIdentifier': cluster_id,
                'SkipFinalClusterSnapshot': not self.create_final_snapshot
            }
            
            if self.create_final_snapshot:
                snapshot_id = f"{cluster_id}-final-{self.execution_timestamp}"
                delete_params['FinalClusterSnapshotIdentifier'] = snapshot_id
                self.print_colored(Colors.YELLOW, f"   [SNAPSHOT] Creating final snapshot: {snapshot_id}")
            
            redshift_client.delete_cluster(**delete_params)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted cluster: {cluster_id}")
            self.log_action(f"Deleted cluster: {cluster_id} in {region}")
            
            self.cleanup_results['deleted_clusters'].append({
                'cluster_id': cluster_id,
                'region': region,
                'account_key': account_key,
                'final_snapshot_created': self.create_final_snapshot
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete cluster {cluster_id}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'RedshiftCluster',
                'name': cluster_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_snapshot(self, redshift_client, snapshot_id, region, account_key):
        """Delete a manual Redshift snapshot"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting snapshot: {snapshot_id}")
            
            redshift_client.delete_cluster_snapshot(
                SnapshotIdentifier=snapshot_id
            )
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted snapshot: {snapshot_id}")
            self.log_action(f"Deleted snapshot: {snapshot_id} in {region}")
            
            self.cleanup_results['deleted_snapshots'].append({
                'snapshot_id': snapshot_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete snapshot {snapshot_id}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'RedshiftSnapshot',
                'name': snapshot_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_subnet_group(self, redshift_client, group_name, region, account_key):
        """Delete a cluster subnet group"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting subnet group: {group_name}")
            
            redshift_client.delete_cluster_subnet_group(
                ClusterSubnetGroupName=group_name
            )
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted subnet group: {group_name}")
            self.log_action(f"Deleted subnet group: {group_name} in {region}")
            
            self.cleanup_results['deleted_subnet_groups'].append({
                'group_name': group_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete subnet group {group_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'SubnetGroup',
                'name': group_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_parameter_group(self, redshift_client, group_name, region, account_key):
        """Delete a cluster parameter group"""
        try:
            # Skip default parameter groups
            if group_name.startswith('default.'):
                self.print_colored(Colors.YELLOW, f"{Symbols.SKIP} Skipping default parameter group: {group_name}")
                return True
            
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting parameter group: {group_name}")
            
            redshift_client.delete_cluster_parameter_group(
                ParameterGroupName=group_name
            )
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted parameter group: {group_name}")
            self.log_action(f"Deleted parameter group: {group_name} in {region}")
            
            self.cleanup_results['deleted_parameter_groups'].append({
                'group_name': group_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete parameter group {group_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'ParameterGroup',
                'name': group_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_event_subscription(self, redshift_client, subscription_name, region, account_key):
        """Delete an event subscription"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting event subscription: {subscription_name}")
            
            redshift_client.delete_event_subscription(
                SubscriptionName=subscription_name
            )
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted event subscription: {subscription_name}")
            self.log_action(f"Deleted event subscription: {subscription_name} in {region}")
            
            self.cleanup_results['deleted_event_subscriptions'].append({
                'subscription_name': subscription_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete event subscription {subscription_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'EventSubscription',
                'name': subscription_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_endpoint_access(self, redshift_client, endpoint_name, region, account_key):
        """Delete a Redshift-managed VPC endpoint"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting endpoint access: {endpoint_name}")
            
            redshift_client.delete_endpoint_access(
                EndpointName=endpoint_name
            )
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted endpoint access: {endpoint_name}")
            self.log_action(f"Deleted endpoint access: {endpoint_name} in {region}")
            
            self.cleanup_results['deleted_endpoint_access'].append({
                'endpoint_name': endpoint_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete endpoint access {endpoint_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'EndpointAccess',
                'name': endpoint_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_redshift(self, account_name, credentials, region):
        """Cleanup all Redshift resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n{Symbols.SCAN} Scanning region: {region}")
            
            redshift_client = boto3.client(
                'redshift',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Endpoint Access first
            try:
                endpoints_response = redshift_client.describe_endpoint_access()
                endpoints = endpoints_response.get('EndpointAccessList', [])
                
                if endpoints:
                    self.print_colored(Colors.CYAN, f"[ENDPOINT] Found {len(endpoints)} endpoint accesses")
                    for endpoint in endpoints:
                        self.delete_endpoint_access(
                            redshift_client,
                            endpoint['EndpointName'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing endpoint accesses in {region}: {e}", "ERROR")
            
            # Delete Clusters
            try:
                clusters_response = redshift_client.describe_clusters()
                clusters = clusters_response.get('Clusters', [])
                
                if clusters:
                    self.print_colored(Colors.CYAN, f"{Symbols.CLUSTER} Found {len(clusters)} clusters")
                    for cluster in clusters:
                        self.delete_cluster(
                            redshift_client,
                            cluster['ClusterIdentifier'],
                            region,
                            account_name
                        )
                        time.sleep(2)
                    
                    # Wait for clusters to start deleting
                    if clusters:
                        self.print_colored(Colors.YELLOW, f"   [WAIT] Waiting for clusters to start deleting...")
                        time.sleep(10)
            except ClientError as e:
                self.log_action(f"Error listing clusters in {region}: {e}", "ERROR")
            
            # Delete Manual Snapshots
            try:
                snapshots_response = redshift_client.describe_cluster_snapshots(
                    SnapshotType='manual'
                )
                snapshots = snapshots_response.get('Snapshots', [])
                
                if snapshots:
                    self.print_colored(Colors.CYAN, f"[SNAPSHOT] Found {len(snapshots)} manual snapshots")
                    for snapshot in snapshots:
                        self.delete_snapshot(
                            redshift_client,
                            snapshot['SnapshotIdentifier'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing snapshots in {region}: {e}", "ERROR")
            
            # Delete Event Subscriptions
            try:
                subscriptions_response = redshift_client.describe_event_subscriptions()
                subscriptions = subscriptions_response.get('EventSubscriptionsList', [])
                
                if subscriptions:
                    self.print_colored(Colors.CYAN, f"[EVENT] Found {len(subscriptions)} event subscriptions")
                    for subscription in subscriptions:
                        self.delete_event_subscription(
                            redshift_client,
                            subscription['CustSubscriptionId'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing event subscriptions in {region}: {e}", "ERROR")
            
            # Delete Subnet Groups
            try:
                subnet_groups_response = redshift_client.describe_cluster_subnet_groups()
                subnet_groups = subnet_groups_response.get('ClusterSubnetGroups', [])
                
                if subnet_groups:
                    self.print_colored(Colors.CYAN, f"[SUBNET] Found {len(subnet_groups)} subnet groups")
                    for group in subnet_groups:
                        self.delete_subnet_group(
                            redshift_client,
                            group['ClusterSubnetGroupName'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing subnet groups in {region}: {e}", "ERROR")
            
            # Delete Parameter Groups
            try:
                param_groups_response = redshift_client.describe_cluster_parameter_groups()
                param_groups = param_groups_response.get('ParameterGroups', [])
                
                if param_groups:
                    self.print_colored(Colors.CYAN, f"[PARAM] Found {len(param_groups)} parameter groups")
                    for group in param_groups:
                        self.delete_parameter_group(
                            redshift_client,
                            group['ParameterGroupName'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing parameter groups in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_redshift(self, account_name, credentials):
        """Cleanup all Redshift resources in an account across all regions"""
        try:
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, f"{Symbols.START} Processing Account: {account_name}")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            
            self.cleanup_results['accounts_processed'].append(account_name)
            
            # Get all regions
            ec2_client = boto3.client(
                'ec2',
                region_name='us-east-1',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            regions_response = ec2_client.describe_regions()
            regions = [region['RegionName'] for region in regions_response['Regions']]
            
            self.print_colored(Colors.CYAN, f"{Symbols.SCAN} Processing {len(regions)} regions")
            
            # Process each region
            for region in regions:
                self.cleanup_region_redshift(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"redshift_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_clusters_deleted': len(self.cleanup_results['deleted_clusters']),
                    'total_snapshots_deleted': len(self.cleanup_results['deleted_snapshots']),
                    'total_subnet_groups_deleted': len(self.cleanup_results['deleted_subnet_groups']),
                    'total_parameter_groups_deleted': len(self.cleanup_results['deleted_parameter_groups']),
                    'total_event_subscriptions_deleted': len(self.cleanup_results['deleted_event_subscriptions']),
                    'total_endpoint_access_deleted': len(self.cleanup_results['deleted_endpoint_access']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n{Symbols.STATS} Summary report saved: {report_path}")

            # Print summary to console
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Clusters Deleted: {summary['summary']['total_clusters_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Snapshots Deleted: {summary['summary']['total_snapshots_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Subnet Groups Deleted: {summary['summary']['total_subnet_groups_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Parameter Groups Deleted: {summary['summary']['total_parameter_groups_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Event Subscriptions Deleted: {summary['summary']['total_event_subscriptions_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Endpoint Access Deleted: {summary['summary']['total_endpoint_access_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN} Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for item_list, key_name in [
                (self.cleanup_results['deleted_clusters'], 'clusters'),
                (self.cleanup_results['deleted_snapshots'], 'snapshots'),
                (self.cleanup_results['deleted_subnet_groups'], 'subnet_groups'),
                (self.cleanup_results['deleted_parameter_groups'], 'parameter_groups'),
                (self.cleanup_results['deleted_event_subscriptions'], 'event_subscriptions'),
                (self.cleanup_results['deleted_endpoint_access'], 'endpoint_access')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'clusters': 0,
                            'snapshots': 0,
                            'subnet_groups': 0,
                            'parameter_groups': 0,
                            'event_subscriptions': 0,
                            'endpoint_access': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n{Symbols.LIST} Account: {account}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Clusters: {stats['clusters']}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Snapshots: {stats['snapshots']}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Subnet Groups: {stats['subnet_groups']}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Parameter Groups: {stats['parameter_groups']}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Event Subscriptions: {stats['event_subscriptions']}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Endpoint Access: {stats['endpoint_access']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  {Symbols.SCAN} Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for Redshift cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS REDSHIFT CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, f"{Symbols.KEY} Select Root AWS Accounts for Redshift Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Loaded {len(accounts)} root accounts")
            
            self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
            print("=" * 100)
            
            for idx, account_name in enumerate(account_list, 1):
                account_data = accounts[account_name]
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'N/A')
                user_count = len(account_data.get('users', []))
                
                print(f"   {idx}. {account_name} (ID: {account_id})")
                print(f"      Email: {email}, Users: {user_count}")
            
            print("=" * 100)
            self.print_colored(Colors.BLUE, "[TIP] Selection options:")
            print("   - Single: 1")
            print("   - Multiple: 1,3,5")
            print("   - All: all")
            print("=" * 100)

            selection = input(f"Select accounts (1-{len(account_list)}, comma-separated, or 'all') or 'q' to quit: ").strip()

            if selection.lower() == 'q':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            selected_accounts = []
            if selection.lower() == 'all':
                selected_accounts = account_list
            else:
                try:
                    indices = [int(x.strip()) for x in selection.split(',')]
                    selected_accounts = [account_list[i-1] for i in indices if 0 < i <= len(account_list)]
                except (ValueError, IndexError):
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Invalid selection!")
                    return

            if not selected_accounts:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} No accounts selected!")
                return

            # Ask about final snapshots
            self.print_colored(Colors.YELLOW, f"\n{Symbols.KEY} Final Snapshot Options:")
            snapshot_choice = input("Create final snapshots before deleting clusters? (yes/no) [default: no]: ").strip().lower()
            self.create_final_snapshot = snapshot_choice == 'yes'
            
            if self.create_final_snapshot:
                self.print_colored(Colors.GREEN, f"{Symbols.INFO} Final snapshots will be created before cluster deletion")
            else:
                self.print_colored(Colors.YELLOW, f"{Symbols.INFO} Clusters will be deleted without final snapshots")

            self.print_colored(Colors.RED, f"\n{Symbols.WARN} WARNING: This will DELETE all Redshift resources!")
            self.print_colored(Colors.YELLOW, f"{Symbols.WARN} Includes: Clusters, Snapshots, Subnet Groups, Parameter Groups, Event Subscriptions")
            self.print_colored(Colors.YELLOW, f"{Symbols.INFO} Default parameter groups will be skipped")
            confirm = input(f"\nType 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_redshift(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Redshift cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupRedshiftManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n{Symbols.ERROR} Fatal error: {e}")


if __name__ == "__main__":
    main()
