#!/usr/bin/env python3
"""
Ultra AWS AppSync Cleanup Manager
Comprehensive AppSync cleanup across multiple AWS accounts and regions
- Deletes GraphQL APIs
- Deletes Data Sources
- Deletes Resolvers
- Deletes Functions
- Deletes API Keys
- Deletes Types
- Deletes Domain Names
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


class UltraCleanupAppSyncManager:
    """Manager for comprehensive AppSync cleanup operations"""

    def __init__(self):
        """Initialize the AppSync cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'appsync')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'appsync_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_apis': [],
            'deleted_api_keys': [],
            'deleted_domain_names': [],
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

    def delete_api(self, appsync_client, api_id, api_name, region, account_key):
        """Delete an AppSync GraphQL API (includes all data sources, resolvers, functions)"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting API: {api_name}")
            
            # Delete API (this automatically deletes data sources, resolvers, functions, types)
            appsync_client.delete_graphql_api(apiId=api_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted API: {api_name}")
            self.log_action(f"Deleted AppSync API: {api_name} ({api_id}) in {region}")
            
            self.cleanup_results['deleted_apis'].append({
                'api_id': api_id,
                'api_name': api_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete API {api_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'AppSyncAPI',
                'name': api_name,
                'id': api_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_domain_name(self, appsync_client, domain_name, region, account_key):
        """Delete a custom domain name"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting domain name: {domain_name}")
            
            # Disassociate API first if associated
            try:
                appsync_client.disassociate_api(domainName=domain_name)
                self.print_colored(Colors.YELLOW, f"   [UNLINK] Disassociated API from domain")
                time.sleep(2)
            except ClientError:
                pass  # No API associated
            
            # Delete domain name
            appsync_client.delete_domain_name(domainName=domain_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted domain name: {domain_name}")
            self.log_action(f"Deleted domain name: {domain_name} in {region}")
            
            self.cleanup_results['deleted_domain_names'].append({
                'domain_name': domain_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete domain name {domain_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'DomainName',
                'name': domain_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_appsync(self, account_name, credentials, region):
        """Cleanup all AppSync resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            appsync_client = boto3.client(
                'appsync',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Custom Domain Names (before APIs)
            try:
                domains_response = appsync_client.list_domain_names()
                domains = domains_response.get('domainNameConfigs', [])
                
                if domains:
                    self.print_colored(Colors.CYAN, f"[DOMAIN] Found {len(domains)} domain names")
                    for domain in domains:
                        self.delete_domain_name(
                            appsync_client,
                            domain['domainName'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing domain names in {region}: {e}", "ERROR")
            
            # Delete GraphQL APIs (this automatically deletes associated resources)
            try:
                apis_response = appsync_client.list_graphql_apis()
                apis = apis_response.get('graphqlApis', [])
                
                if apis:
                    self.print_colored(Colors.CYAN, f"[API] Found {len(apis)} GraphQL APIs")
                    for api in apis:
                        # Count API keys before deletion
                        try:
                            keys_response = appsync_client.list_api_keys(apiId=api['apiId'])
                            api_keys = keys_response.get('apiKeys', [])
                            
                            if api_keys:
                                self.print_colored(Colors.YELLOW, f"   [KEY] API has {len(api_keys)} API keys (will be deleted)")
                                self.cleanup_results['deleted_api_keys'].extend([
                                    {
                                        'api_id': api['apiId'],
                                        'api_name': api['name'],
                                        'key_id': key['id'],
                                        'region': region,
                                        'account_key': account_name
                                    }
                                    for key in api_keys
                                ])
                        except ClientError:
                            pass
                        
                        self.delete_api(
                            appsync_client,
                            api['apiId'],
                            api['name'],
                            region,
                            account_name
                        )
                        time.sleep(2)
            except ClientError as e:
                self.log_action(f"Error listing GraphQL APIs in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_appsync(self, account_name, credentials):
        """Cleanup all AppSync resources in an account across all regions"""
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
                self.cleanup_region_appsync(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"appsync_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_apis_deleted': len(self.cleanup_results['deleted_apis']),
                    'total_api_keys_deleted': len(self.cleanup_results['deleted_api_keys']),
                    'total_domain_names_deleted': len(self.cleanup_results['deleted_domain_names']),
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
            self.print_colored(Colors.GREEN, f"[OK] GraphQL APIs Deleted: {summary['summary']['total_apis_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] API Keys Deleted: {summary['summary']['total_api_keys_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Domain Names Deleted: {summary['summary']['total_domain_names_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for item_list, key_name in [
                (self.cleanup_results['deleted_apis'], 'apis'),
                (self.cleanup_results['deleted_api_keys'], 'api_keys'),
                (self.cleanup_results['deleted_domain_names'], 'domain_names')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'apis': 0,
                            'api_keys': 0,
                            'domain_names': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] GraphQL APIs: {stats['apis']}")
                self.print_colored(Colors.GREEN, f"  [OK] API Keys: {stats['api_keys']}")
                self.print_colored(Colors.GREEN, f"  [OK] Domain Names: {stats['domain_names']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for AppSync cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS APPSYNC CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for AppSync Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all AppSync resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: GraphQL APIs, Data Sources, Resolvers, Functions, API Keys, Domain Names")
            self.print_colored(Colors.YELLOW, "[INFO] Deleting API automatically removes all associated data sources, resolvers, and functions")
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

                self.cleanup_account_appsync(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] AppSync cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupAppSyncManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
