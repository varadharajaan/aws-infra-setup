#!/usr/bin/env python3
"""
Ultra Kinesis Cleanup Manager
Comprehensive Kinesis cleanup across multiple AWS accounts and regions
- Deletes Kinesis Data Streams
- Deletes Kinesis Firehose Delivery Streams
- Deletes Kinesis Data Analytics Applications (v1 and v2)
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


class UltraCleanupKinesisManager:
    """Manager for comprehensive Kinesis cleanup operations"""

    def __init__(self):
        """Initialize the Kinesis cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'kinesis')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'kinesis_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_data_streams': [],
            'deleted_firehose_streams': [],
            'deleted_analytics_apps_v1': [],
            'deleted_analytics_apps_v2': [],
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

    def delete_kinesis_data_stream(self, kinesis_client, stream_name, region, account_key):
        """Delete a Kinesis Data Stream"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting data stream: {stream_name}")
            
            kinesis_client.delete_stream(
                StreamName=stream_name,
                EnforceConsumerDeletion=True
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted data stream: {stream_name}")
            self.log_action(f"Deleted Kinesis data stream: {stream_name} in {region}")
            
            self.cleanup_results['deleted_data_streams'].append({
                'stream_name': stream_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete data stream {stream_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'DataStream',
                'name': stream_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_firehose_stream(self, firehose_client, stream_name, region, account_key):
        """Delete a Kinesis Firehose Delivery Stream"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting firehose stream: {stream_name}")
            
            firehose_client.delete_delivery_stream(
                DeliveryStreamName=stream_name,
                AllowForceDelete=True
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted firehose stream: {stream_name}")
            self.log_action(f"Deleted Firehose stream: {stream_name} in {region}")
            
            self.cleanup_results['deleted_firehose_streams'].append({
                'stream_name': stream_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete firehose stream {stream_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'FirehoseStream',
                'name': stream_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_analytics_app_v1(self, analytics_client, app_name, region, account_key):
        """Delete a Kinesis Data Analytics Application (v1 - SQL)"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting analytics app (v1): {app_name}")
            
            # Get application details to find creation timestamp
            response = analytics_client.describe_application(ApplicationName=app_name)
            create_timestamp = response['ApplicationDetail']['CreateTimestamp']
            
            analytics_client.delete_application(
                ApplicationName=app_name,
                CreateTimestamp=create_timestamp
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted analytics app (v1): {app_name}")
            self.log_action(f"Deleted Kinesis Analytics app (v1): {app_name} in {region}")
            
            self.cleanup_results['deleted_analytics_apps_v1'].append({
                'app_name': app_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete analytics app (v1) {app_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'AnalyticsAppV1',
                'name': app_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_analytics_app_v2(self, analyticsv2_client, app_name, region, account_key):
        """Delete a Kinesis Data Analytics Application (v2 - Flink/Java)"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting analytics app (v2): {app_name}")
            
            # Get application details
            response = analyticsv2_client.describe_application(ApplicationName=app_name)
            create_timestamp = response['ApplicationDetail']['CreateTimestamp']
            
            analyticsv2_client.delete_application(
                ApplicationName=app_name,
                CreateTimestamp=create_timestamp
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted analytics app (v2): {app_name}")
            self.log_action(f"Deleted Kinesis Analytics app (v2): {app_name} in {region}")
            
            self.cleanup_results['deleted_analytics_apps_v2'].append({
                'app_name': app_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete analytics app (v2) {app_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'AnalyticsAppV2',
                'name': app_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_kinesis(self, account_name, credentials, region):
        """Cleanup all Kinesis resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            # Create clients for the region
            kinesis_client = boto3.client(
                'kinesis',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            firehose_client = boto3.client(
                'firehose',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            analytics_client = boto3.client(
                'kinesisanalytics',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            analyticsv2_client = boto3.client(
                'kinesisanalyticsv2',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Kinesis Data Streams
            try:
                streams_response = kinesis_client.list_streams()
                data_streams = streams_response.get('StreamNames', [])
                
                if data_streams:
                    self.print_colored(Colors.CYAN, f"[STREAM] Found {len(data_streams)} Kinesis data streams")
                    for stream_name in data_streams:
                        self.delete_kinesis_data_stream(kinesis_client, stream_name, region, account_name)
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing Kinesis data streams in {region}: {e}", "ERROR")
            
            # Delete Firehose Delivery Streams
            try:
                firehose_response = firehose_client.list_delivery_streams()
                firehose_streams = firehose_response.get('DeliveryStreamNames', [])
                
                if firehose_streams:
                    self.print_colored(Colors.CYAN, f"[STREAM] Found {len(firehose_streams)} Firehose streams")
                    for stream_name in firehose_streams:
                        self.delete_firehose_stream(firehose_client, stream_name, region, account_name)
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing Firehose streams in {region}: {e}", "ERROR")
            
            # Delete Analytics Applications (v1)
            try:
                analytics_response = analytics_client.list_applications()
                analytics_apps = analytics_response.get('ApplicationSummaries', [])
                
                if analytics_apps:
                    self.print_colored(Colors.CYAN, f"[APP] Found {len(analytics_apps)} Analytics apps (v1)")
                    for app in analytics_apps:
                        self.delete_analytics_app_v1(analytics_client, app['ApplicationName'], region, account_name)
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing Analytics apps (v1) in {region}: {e}", "ERROR")
            
            # Delete Analytics Applications (v2)
            try:
                analyticsv2_response = analyticsv2_client.list_applications()
                analyticsv2_apps = analyticsv2_response.get('ApplicationSummaries', [])
                
                if analyticsv2_apps:
                    self.print_colored(Colors.CYAN, f"[APP] Found {len(analyticsv2_apps)} Analytics apps (v2)")
                    for app in analyticsv2_apps:
                        self.delete_analytics_app_v2(analyticsv2_client, app['ApplicationName'], region, account_name)
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing Analytics apps (v2) in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_kinesis(self, account_name, credentials):
        """Cleanup all Kinesis resources in an account across all regions"""
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
                self.cleanup_region_kinesis(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"kinesis_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_data_streams_deleted': len(self.cleanup_results['deleted_data_streams']),
                    'total_firehose_streams_deleted': len(self.cleanup_results['deleted_firehose_streams']),
                    'total_analytics_apps_v1_deleted': len(self.cleanup_results['deleted_analytics_apps_v1']),
                    'total_analytics_apps_v2_deleted': len(self.cleanup_results['deleted_analytics_apps_v2']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n[STATS] Summary report saved: {report_path}")
            self.log_action(f"Summary report saved: {report_path}")

            # Print summary to console
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            self.print_colored(Colors.GREEN, f"[OK] Data Streams Deleted: {summary['summary']['total_data_streams_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Firehose Streams Deleted: {summary['summary']['total_firehose_streams_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Analytics Apps (v1) Deleted: {summary['summary']['total_analytics_apps_v1_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Analytics Apps (v2) Deleted: {summary['summary']['total_analytics_apps_v2_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for stream in self.cleanup_results['deleted_data_streams']:
                account = stream.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'data_streams': 0,
                        'firehose_streams': 0,
                        'analytics_apps_v1': 0,
                        'analytics_apps_v2': 0,
                        'regions': set()
                    }
                account_summary[account]['data_streams'] += 1
                account_summary[account]['regions'].add(stream.get('region', 'unknown'))

            for stream in self.cleanup_results['deleted_firehose_streams']:
                account = stream.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'data_streams': 0,
                        'firehose_streams': 0,
                        'analytics_apps_v1': 0,
                        'analytics_apps_v2': 0,
                        'regions': set()
                    }
                account_summary[account]['firehose_streams'] += 1
                account_summary[account]['regions'].add(stream.get('region', 'unknown'))

            for app in self.cleanup_results['deleted_analytics_apps_v1']:
                account = app.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'data_streams': 0,
                        'firehose_streams': 0,
                        'analytics_apps_v1': 0,
                        'analytics_apps_v2': 0,
                        'regions': set()
                    }
                account_summary[account]['analytics_apps_v1'] += 1
                account_summary[account]['regions'].add(app.get('region', 'unknown'))

            for app in self.cleanup_results['deleted_analytics_apps_v2']:
                account = app.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'data_streams': 0,
                        'firehose_streams': 0,
                        'analytics_apps_v1': 0,
                        'analytics_apps_v2': 0,
                        'regions': set()
                    }
                account_summary[account]['analytics_apps_v2'] += 1
                account_summary[account]['regions'].add(app.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Data Streams: {stats['data_streams']}")
                self.print_colored(Colors.GREEN, f"  [OK] Firehose Streams: {stats['firehose_streams']}")
                self.print_colored(Colors.GREEN, f"  [OK] Analytics Apps (v1): {stats['analytics_apps_v1']}")
                self.print_colored(Colors.GREEN, f"  [OK] Analytics Apps (v2): {stats['analytics_apps_v2']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")
            self.log_action(f"Failed to generate summary report: {e}", "ERROR")

    def interactive_cleanup(self):
        """Interactive mode for Kinesis cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA KINESIS CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            # Load accounts
            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']

            # Display accounts
            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Kinesis Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"[OK] Loaded {len(accounts)} root accounts")
            
            self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
            print("=" * 100)
            
            account_list = list(accounts.keys())
            for idx, account_name in enumerate(account_list, 1):
                account_data = accounts[account_name]
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'N/A')
                
                user_count = 0
                if 'users' in account_data and isinstance(account_data['users'], list):
                    user_count = len(account_data['users'])
                
                print(f"   {idx}. {account_name} (ID: {account_id})")
                print(f"      Email: {email}, Users: {user_count}")
            
            print("=" * 100)
            self.print_colored(Colors.BLUE, "[TIP] Selection options:")
            print("   - Single: 1")
            print("   - Multiple: 1,3,5")
            print("   - Range: 1-5")
            print("   - All: all")
            print("=" * 100)

            selection = input(f"Select accounts (1-{len(account_list)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

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

            # Confirm deletion
            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all Kinesis resources!")
            self.print_colored(Colors.YELLOW, f"[INFO] Accounts: {len(selected_accounts)}")
            
            confirm = input(f"\nType 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            # Process selected accounts
            self.log_action(f"Starting cleanup for accounts: {selected_accounts}")

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_kinesis(account_name, credentials)
                time.sleep(2)

            # Generate summary
            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Kinesis cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
            self.log_action("Cleanup interrupted by user", "WARNING")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")
            self.log_action(f"Error during cleanup: {e}", "ERROR")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupKinesisManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
