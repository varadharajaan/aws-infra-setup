#!/usr/bin/env python3
"""
Ultra AWS DocumentDB Cleanup Manager
Comprehensive DocumentDB (MongoDB-compatible) cleanup across multiple AWS accounts and regions
- Deletes DB Clusters
- Deletes DB Instances
- Deletes DB Cluster Snapshots
- Deletes DB Subnet Groups
- Deletes DB Cluster Parameter Groups
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import json
import time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager


class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    END = '\033[0m'


class UltraCleanupDocumentDBManager:
    def __init__(self):
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'documentdb')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.log_file = os.path.join(self.logs_dir, f'documentdb_cleanup_log_{self.execution_timestamp}.log')
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_instances': [],
            'deleted_clusters': [],
            'deleted_snapshots': [],
            'deleted_subnet_groups': [],
            'deleted_cluster_parameter_groups': [],
            'failed_deletions': [],
            'errors': []
        }
        
        self.create_final_snapshot = False

    def print_colored(self, color, message):
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.log_file, 'a') as f:
            f.write(f"{timestamp} | {level:8} | {message}\n")

    def delete_db_instance(self, docdb_client, instance_id, region, account_key):
        try:
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting instance: {instance_id}")
            docdb_client.delete_db_instance(DBInstanceIdentifier=instance_id)
            self.print_colored(Colors.GREEN, f"   [OK] Deleted instance: {instance_id}")
            self.log_action(f"Deleted DocumentDB instance: {instance_id} in {region}")
            
            self.cleanup_results['deleted_instances'].append({
                'instance_id': instance_id,
                'region': region,
                'account_key': account_key
            })
            return True
        except ClientError as e:
            self.log_action(f"Failed to delete instance {instance_id}: {e}", "ERROR")
            return False

    def delete_db_cluster(self, docdb_client, cluster_id, region, account_key):
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting cluster: {cluster_id}")
            
            # Delete instances first
            try:
                instances_response = docdb_client.describe_db_instances(
                    Filters=[{'Name': 'db-cluster-id', 'Values': [cluster_id]}]
                )
                instances = instances_response.get('DBInstances', [])
                
                if instances:
                    self.print_colored(Colors.YELLOW, f"   [SCAN] Found {len(instances)} instances")
                    for instance in instances:
                        self.delete_db_instance(docdb_client, instance['DBInstanceIdentifier'], region, account_key)
                        time.sleep(2)
                    self.print_colored(Colors.YELLOW, f"   [WAIT] Waiting for instances to delete...")
                    time.sleep(15)
            except ClientError as e:
                self.log_action(f"Error listing instances for cluster {cluster_id}: {e}", "ERROR")
            
            # Delete cluster
            delete_params = {
                'DBClusterIdentifier': cluster_id,
                'SkipFinalSnapshot': not self.create_final_snapshot
            }
            
            if self.create_final_snapshot:
                snapshot_id = f"{cluster_id}-final-{self.execution_timestamp}"
                delete_params['FinalDBSnapshotIdentifier'] = snapshot_id
                self.print_colored(Colors.YELLOW, f"   [SNAPSHOT] Creating final snapshot: {snapshot_id}")
            
            docdb_client.delete_db_cluster(**delete_params)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted cluster: {cluster_id}")
            self.log_action(f"Deleted DocumentDB cluster: {cluster_id} in {region}")
            
            self.cleanup_results['deleted_clusters'].append({
                'cluster_id': cluster_id,
                'region': region,
                'account_key': account_key
            })
            return True
        except ClientError as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to delete cluster {cluster_id}: {e}")
            self.log_action(f"Failed to delete cluster {cluster_id}: {e}", "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'DocumentDBCluster',
                'name': cluster_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_documentdb(self, account_name, credentials, region):
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            docdb_client = boto3.client(
                'docdb',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Clusters
            try:
                clusters_response = docdb_client.describe_db_clusters()
                clusters = clusters_response.get('DBClusters', [])
                
                if clusters:
                    self.print_colored(Colors.CYAN, f"[CLUSTER] Found {len(clusters)} clusters")
                    for cluster in clusters:
                        self.delete_db_cluster(docdb_client, cluster['DBClusterIdentifier'], region, account_name)
                        time.sleep(3)
                    
                    if clusters:
                        self.print_colored(Colors.YELLOW, f"   [WAIT] Waiting for clusters to delete...")
                        time.sleep(15)
            except ClientError as e:
                self.log_action(f"Error listing clusters in {region}: {e}", "ERROR")
            
            # Delete Snapshots
            try:
                snapshots_response = docdb_client.describe_db_cluster_snapshots()
                snapshots = snapshots_response.get('DBClusterSnapshots', [])
                manual_snapshots = [s for s in snapshots if s.get('SnapshotType') == 'manual']
                
                if manual_snapshots:
                    self.print_colored(Colors.CYAN, f"[SNAPSHOT] Found {len(manual_snapshots)} manual snapshots")
                    for snapshot in manual_snapshots:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting snapshot: {snapshot['DBClusterSnapshotIdentifier']}")
                            docdb_client.delete_db_cluster_snapshot(
                                DBClusterSnapshotIdentifier=snapshot['DBClusterSnapshotIdentifier']
                            )
                            self.cleanup_results['deleted_snapshots'].append({
                                'snapshot_id': snapshot['DBClusterSnapshotIdentifier'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(1)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing snapshots in {region}: {e}", "ERROR")
            
            # Delete Subnet Groups
            try:
                subnet_groups_response = docdb_client.describe_db_subnet_groups()
                subnet_groups = subnet_groups_response.get('DBSubnetGroups', [])
                
                if subnet_groups:
                    self.print_colored(Colors.CYAN, f"[SUBNET] Found {len(subnet_groups)} subnet groups")
                    for group in subnet_groups:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting subnet group: {group['DBSubnetGroupName']}")
                            docdb_client.delete_db_subnet_group(DBSubnetGroupName=group['DBSubnetGroupName'])
                            self.cleanup_results['deleted_subnet_groups'].append({
                                'group_name': group['DBSubnetGroupName'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(1)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing subnet groups in {region}: {e}", "ERROR")
            
            # Delete Cluster Parameter Groups
            try:
                param_groups_response = docdb_client.describe_db_cluster_parameter_groups()
                param_groups = param_groups_response.get('DBClusterParameterGroups', [])
                
                if param_groups:
                    self.print_colored(Colors.CYAN, f"[PARAM] Found {len(param_groups)} cluster parameter groups")
                    for group in param_groups:
                        if not group['DBClusterParameterGroupName'].startswith('default.'):
                            try:
                                self.print_colored(Colors.CYAN, f"[DELETE] Deleting parameter group: {group['DBClusterParameterGroupName']}")
                                docdb_client.delete_db_cluster_parameter_group(
                                    DBClusterParameterGroupName=group['DBClusterParameterGroupName']
                                )
                                self.cleanup_results['deleted_cluster_parameter_groups'].append({
                                    'group_name': group['DBClusterParameterGroupName'],
                                    'region': region,
                                    'account_key': account_name
                                })
                                time.sleep(1)
                            except ClientError:
                                pass
            except ClientError as e:
                self.log_action(f"Error listing parameter groups in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_documentdb(self, account_name, credentials):
        try:
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, f"[START] Processing Account: {account_name}")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            
            self.cleanup_results['accounts_processed'].append(account_name)
            
            ec2_client = boto3.client(
                'ec2',
                region_name='us-east-1',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            regions_response = ec2_client.describe_regions()
            regions = [region['RegionName'] for region in regions_response['Regions']]
            
            self.print_colored(Colors.CYAN, f"[SCAN] Processing {len(regions)} regions")
            
            for region in regions:
                self.cleanup_region_documentdb(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        try:
            report_filename = f"documentdb_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_clusters_deleted': len(self.cleanup_results['deleted_clusters']),
                    'total_instances_deleted': len(self.cleanup_results['deleted_instances']),
                    'total_snapshots_deleted': len(self.cleanup_results['deleted_snapshots']),
                    'total_subnet_groups_deleted': len(self.cleanup_results['deleted_subnet_groups']),
                    'total_cluster_parameter_groups_deleted': len(self.cleanup_results['deleted_cluster_parameter_groups']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n[STATS] Summary report saved: {report_path}")
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            self.print_colored(Colors.GREEN, f"[OK] Clusters Deleted: {summary['summary']['total_clusters_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Instances Deleted: {summary['summary']['total_instances_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Snapshots Deleted: {summary['summary']['total_snapshots_deleted']}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS DOCUMENTDB CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for DocumentDB Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"[OK] Loaded {len(accounts)} root accounts")
            
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
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection!")
                    return

            if not selected_accounts:
                self.print_colored(Colors.RED, "[ERROR] No accounts selected!")
                return

            self.print_colored(Colors.YELLOW, "\n[KEY] Final Snapshot Options:")
            snapshot_choice = input("Create final snapshots before deleting clusters? (yes/no) [default: no]: ").strip().lower()
            self.create_final_snapshot = snapshot_choice == 'yes'

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all DocumentDB resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: Clusters, Instances, Snapshots, Subnet Groups, Parameter Groups")
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

                self.cleanup_account_documentdb(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] DocumentDB cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    try:
        manager = UltraCleanupDocumentDBManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
