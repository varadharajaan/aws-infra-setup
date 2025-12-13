#!/usr/bin/env python3
"""
Ultra AWS MSK (Managed Kafka) Cleanup Manager
Comprehensive MSK cleanup across multiple AWS accounts and regions
- Deletes MSK Clusters
- Deletes Configurations
- Deletes Cluster Policies
- Very expensive service - ~$150/month per broker ($0.21/hour)
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


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    END = '\033[0m'


class UltraCleanupMSKManager:
    """Manager for comprehensive MSK cleanup operations"""

    def __init__(self):
        """Initialize the MSK cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'msk')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'msk_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_clusters': [],
            'deleted_configurations': [],
            'failed_deletions': [],
            'errors': []
        }

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_cluster(self, kafka_client, cluster_arn, cluster_name, region, account_key):
        """Delete an MSK cluster"""
        try:
            # Get cluster info
            cluster_response = kafka_client.describe_cluster(ClusterArn=cluster_arn)
            cluster = cluster_response['ClusterInfo']
            state = cluster.get('State', 'UNKNOWN')
            broker_count = cluster.get('NumberOfBrokerNodes', 0)
            
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting MSK cluster: {cluster_name}")
            self.print_colored(Colors.YELLOW, f"   [INFO] State: {state}, Brokers: {broker_count}")
            self.print_colored(Colors.YELLOW, f"   [COST] Estimated savings: ~${broker_count * 150}/month")
            
            # Skip if already deleting
            if state == 'DELETING':
                self.print_colored(Colors.YELLOW, f"[SKIP] Cluster already deleting: {cluster_name}")
                return True
            
            # Delete the cluster
            kafka_client.delete_cluster(ClusterArn=cluster_arn)
            
            self.print_colored(Colors.GREEN, f"[OK] Initiated deletion for cluster: {cluster_name}")
            self.log_action(f"Deleted MSK cluster: {cluster_name} ({cluster_arn}) in {region}")
            
            self.cleanup_results['deleted_clusters'].append({
                'cluster_arn': cluster_arn,
                'cluster_name': cluster_name,
                'broker_count': broker_count,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete cluster {cluster_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'MSKCluster',
                'name': cluster_name,
                'arn': cluster_arn,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_configuration(self, kafka_client, config_arn, config_name, region, account_key):
        """Delete an MSK configuration"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting configuration: {config_name}")
            
            kafka_client.delete_configuration(Arn=config_arn)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted configuration: {config_name}")
            self.log_action(f"Deleted configuration: {config_name} ({config_arn}) in {region}")
            
            self.cleanup_results['deleted_configurations'].append({
                'config_arn': config_arn,
                'config_name': config_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete configuration {config_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'MSKConfiguration',
                'name': config_name,
                'arn': config_arn,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_msk(self, account_name, credentials, region):
        """Cleanup all MSK resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            kafka_client = boto3.client(
                'kafka',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete MSK Clusters
            try:
                clusters_response = kafka_client.list_clusters()
                clusters = clusters_response.get('ClusterInfoList', [])
                
                if clusters:
                    self.print_colored(Colors.CYAN, f"[CLUSTER] Found {len(clusters)} MSK clusters")
                    for cluster in clusters:
                        self.delete_cluster(
                            kafka_client,
                            cluster['ClusterArn'],
                            cluster['ClusterName'],
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
            
            # Delete Configurations
            try:
                configs_response = kafka_client.list_configurations()
                configs = configs_response.get('Configurations', [])
                
                if configs:
                    self.print_colored(Colors.CYAN, f"[CONFIG] Found {len(configs)} configurations")
                    for config in configs:
                        self.delete_configuration(
                            kafka_client,
                            config['Arn'],
                            config['Name'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing configurations in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_msk(self, account_name, credentials):
        """Cleanup all MSK resources in an account across all regions"""
        try:
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, f"[START] Processing Account: {account_name}")
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
            
            self.print_colored(Colors.CYAN, f"[SCAN] Processing {len(regions)} regions")
            
            # Process each region
            for region in regions:
                self.cleanup_region_msk(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"msk_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            # Calculate total cost savings
            total_brokers = sum(c.get('broker_count', 0) for c in self.cleanup_results['deleted_clusters'])
            estimated_savings = total_brokers * 150

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_clusters_deleted': len(self.cleanup_results['deleted_clusters']),
                    'total_brokers': total_brokers,
                    'estimated_monthly_savings_usd': estimated_savings,
                    'total_configurations_deleted': len(self.cleanup_results['deleted_configurations']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n[STATS] Summary report saved: {report_path}")

            # Print summary to console
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            self.print_colored(Colors.GREEN, f"[OK] MSK Clusters Deleted: {summary['summary']['total_clusters_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Total Brokers: {total_brokers}")
            self.print_colored(Colors.CYAN, f"[COST] Estimated Monthly Savings: ${estimated_savings}")
            self.print_colored(Colors.GREEN, f"[OK] Configurations Deleted: {summary['summary']['total_configurations_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for cluster in self.cleanup_results['deleted_clusters']:
                account = cluster.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'clusters': 0,
                        'brokers': 0,
                        'configurations': 0,
                        'regions': set()
                    }
                account_summary[account]['clusters'] += 1
                account_summary[account]['brokers'] += cluster.get('broker_count', 0)
                account_summary[account]['regions'].add(cluster.get('region', 'unknown'))

            for config in self.cleanup_results['deleted_configurations']:
                account = config.get('account_key', 'Unknown')
                if account in account_summary:
                    account_summary[account]['configurations'] += 1

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Clusters: {stats['clusters']}")
                self.print_colored(Colors.GREEN, f"  [OK] Brokers: {stats['brokers']}")
                self.print_colored(Colors.CYAN, f"  [COST] Est. Savings: ~${stats['brokers'] * 150}/month")
                self.print_colored(Colors.GREEN, f"  [OK] Configurations: {stats['configurations']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for MSK cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS MSK (MANAGED KAFKA) CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for MSK Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all MSK resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: Kafka Clusters, Configurations")
            self.print_colored(Colors.CYAN, "[INFO] Cost: ~$150/month per broker (~$0.21/hour)")
            self.print_colored(Colors.CYAN, "[INFO] Potential for significant cost savings!")
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

                self.cleanup_account_msk(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] MSK cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupMSKManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
