#!/usr/bin/env python3
"""
Ultra AWS Lightsail Cleanup Manager
Comprehensive Lightsail cleanup across multiple AWS accounts and regions
- Deletes Instances
- Deletes Databases
- Deletes Load Balancers
- Deletes Container Services
- Deletes Distributions (CDN)
- Releases Static IPs
- Deletes Disks
- Deletes Snapshots
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


class UltraCleanupLightsailManager:
    def __init__(self):
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'lightsail')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.log_file = os.path.join(self.logs_dir, f'lightsail_cleanup_log_{self.execution_timestamp}.log')
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_instances': [],
            'deleted_databases': [],
            'deleted_load_balancers': [],
            'deleted_container_services': [],
            'deleted_distributions': [],
            'released_static_ips': [],
            'deleted_disks': [],
            'deleted_snapshots': [],
            'failed_deletions': [],
            'errors': []
        }

    def print_colored(self, color, message):
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.log_file, 'a') as f:
            f.write(f"{timestamp} | {level:8} | {message}\n")

    def cleanup_region_lightsail(self, account_name, credentials, region):
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            lightsail_client = boto3.client(
                'lightsail',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Container Services
            try:
                containers = lightsail_client.get_container_services()
                container_services = containers.get('containerServices', [])
                
                if container_services:
                    self.print_colored(Colors.CYAN, f"[CONTAINER] Found {len(container_services)} container services")
                    for container in container_services:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting container service: {container['containerServiceName']}")
                            lightsail_client.delete_container_service(serviceName=container['containerServiceName'])
                            self.cleanup_results['deleted_container_services'].append({
                                'service_name': container['containerServiceName'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(2)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing container services in {region}: {e}", "ERROR")
            
            # Delete Distributions (CDN)
            try:
                distributions = lightsail_client.get_distributions()
                dist_list = distributions.get('distributions', [])
                
                if dist_list:
                    self.print_colored(Colors.CYAN, f"[CDN] Found {len(dist_list)} distributions")
                    for dist in dist_list:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting distribution: {dist['name']}")
                            lightsail_client.delete_distribution(distributionName=dist['name'])
                            self.cleanup_results['deleted_distributions'].append({
                                'distribution_name': dist['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(2)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing distributions in {region}: {e}", "ERROR")
            
            # Delete Load Balancers
            try:
                lbs = lightsail_client.get_load_balancers()
                load_balancers = lbs.get('loadBalancers', [])
                
                if load_balancers:
                    self.print_colored(Colors.CYAN, f"[LB] Found {len(load_balancers)} load balancers")
                    for lb in load_balancers:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting load balancer: {lb['name']}")
                            lightsail_client.delete_load_balancer(loadBalancerName=lb['name'])
                            self.cleanup_results['deleted_load_balancers'].append({
                                'lb_name': lb['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(2)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing load balancers in {region}: {e}", "ERROR")
            
            # Delete Databases
            try:
                dbs = lightsail_client.get_relational_databases()
                databases = dbs.get('relationalDatabases', [])
                
                if databases:
                    self.print_colored(Colors.CYAN, f"[DB] Found {len(databases)} databases")
                    for db in databases:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting database: {db['name']}")
                            lightsail_client.delete_relational_database(
                                relationalDatabaseName=db['name'],
                                skipFinalSnapshot=True
                            )
                            self.cleanup_results['deleted_databases'].append({
                                'db_name': db['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(2)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing databases in {region}: {e}", "ERROR")
            
            # Delete Instances
            try:
                instances = lightsail_client.get_instances()
                instance_list = instances.get('instances', [])
                
                if instance_list:
                    self.print_colored(Colors.CYAN, f"[INSTANCE] Found {len(instance_list)} instances")
                    for instance in instance_list:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting instance: {instance['name']}")
                            lightsail_client.delete_instance(instanceName=instance['name'])
                            self.cleanup_results['deleted_instances'].append({
                                'instance_name': instance['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(1)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing instances in {region}: {e}", "ERROR")
            
            # Wait for resources to delete
            time.sleep(10)
            
            # Release Static IPs
            try:
                ips = lightsail_client.get_static_ips()
                static_ips = ips.get('staticIps', [])
                
                if static_ips:
                    self.print_colored(Colors.CYAN, f"[IP] Found {len(static_ips)} static IPs")
                    for ip in static_ips:
                        try:
                            self.print_colored(Colors.CYAN, f"[RELEASE] Releasing static IP: {ip['name']}")
                            lightsail_client.release_static_ip(staticIpName=ip['name'])
                            self.cleanup_results['released_static_ips'].append({
                                'ip_name': ip['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(1)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing static IPs in {region}: {e}", "ERROR")
            
            # Delete Disks
            try:
                disks = lightsail_client.get_disks()
                disk_list = disks.get('disks', [])
                
                if disk_list:
                    self.print_colored(Colors.CYAN, f"[DISK] Found {len(disk_list)} disks")
                    for disk in disk_list:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting disk: {disk['name']}")
                            lightsail_client.delete_disk(diskName=disk['name'])
                            self.cleanup_results['deleted_disks'].append({
                                'disk_name': disk['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(1)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing disks in {region}: {e}", "ERROR")
            
            # Delete Snapshots
            try:
                snapshots = lightsail_client.get_instance_snapshots()
                snapshot_list = snapshots.get('instanceSnapshots', [])
                
                if snapshot_list:
                    self.print_colored(Colors.CYAN, f"[SNAPSHOT] Found {len(snapshot_list)} snapshots")
                    for snapshot in snapshot_list:
                        try:
                            self.print_colored(Colors.CYAN, f"[DELETE] Deleting snapshot: {snapshot['name']}")
                            lightsail_client.delete_instance_snapshot(instanceSnapshotName=snapshot['name'])
                            self.cleanup_results['deleted_snapshots'].append({
                                'snapshot_name': snapshot['name'],
                                'region': region,
                                'account_key': account_name
                            })
                            time.sleep(1)
                        except ClientError:
                            pass
            except ClientError as e:
                self.log_action(f"Error listing snapshots in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_lightsail(self, account_name, credentials):
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
                self.cleanup_region_lightsail(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        try:
            report_filename = f"lightsail_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_instances_deleted': len(self.cleanup_results['deleted_instances']),
                    'total_databases_deleted': len(self.cleanup_results['deleted_databases']),
                    'total_load_balancers_deleted': len(self.cleanup_results['deleted_load_balancers']),
                    'total_container_services_deleted': len(self.cleanup_results['deleted_container_services']),
                    'total_distributions_deleted': len(self.cleanup_results['deleted_distributions']),
                    'total_static_ips_released': len(self.cleanup_results['released_static_ips']),
                    'total_disks_deleted': len(self.cleanup_results['deleted_disks']),
                    'total_snapshots_deleted': len(self.cleanup_results['deleted_snapshots']),
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
            self.print_colored(Colors.GREEN, f"[OK] Instances Deleted: {summary['summary']['total_instances_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Databases Deleted: {summary['summary']['total_databases_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Load Balancers Deleted: {summary['summary']['total_load_balancers_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Container Services Deleted: {summary['summary']['total_container_services_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Distributions Deleted: {summary['summary']['total_distributions_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Static IPs Released: {summary['summary']['total_static_ips_released']}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS LIGHTSAIL CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Lightsail Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all Lightsail resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: Instances, Databases, Load Balancers, Container Services, Distributions, Static IPs")
            confirm = input(f"\nType 'DELETE' to confirm: ").strip()
            if confirm != 'DELETE':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_lightsail(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Lightsail cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    try:
        manager = UltraCleanupLightsailManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
