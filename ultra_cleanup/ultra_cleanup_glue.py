#!/usr/bin/env python3
"""
Ultra Glue Cleanup Manager
Comprehensive AWS Glue cleanup across multiple AWS accounts and regions
- Deletes Glue Databases and Tables
- Deletes Glue Crawlers
- Deletes Glue Jobs
- Deletes Glue Triggers
- Deletes Glue Dev Endpoints
- Deletes Glue ML Transforms
- Deletes Glue Workflows
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


class UltraCleanupGlueManager:
    """Manager for comprehensive Glue cleanup operations"""

    def __init__(self):
        """Initialize the Glue cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'glue')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'glue_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_databases': [],
            'deleted_tables': [],
            'deleted_crawlers': [],
            'deleted_jobs': [],
            'deleted_triggers': [],
            'deleted_dev_endpoints': [],
            'deleted_ml_transforms': [],
            'deleted_workflows': [],
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

    def delete_glue_table(self, glue_client, database_name, table_name, region, account_key):
        """Delete a Glue table"""
        try:
            glue_client.delete_table(
                DatabaseName=database_name,
                Name=table_name
            )
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted table: {table_name}")
            self.log_action(f"Deleted Glue table: {table_name} from database {database_name} in {region}")
            
            self.cleanup_results['deleted_tables'].append({
                'database': database_name,
                'table': table_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete table {table_name}: {e}"
            self.print_colored(Colors.RED, f"   [ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def delete_glue_database(self, glue_client, database_name, region, account_key):
        """Delete a Glue database and all its tables"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting database: {database_name}")
            
            # Get all tables in the database
            try:
                paginator = glue_client.get_paginator('get_tables')
                for page in paginator.paginate(DatabaseName=database_name):
                    tables = page.get('TableList', [])
                    if tables:
                        self.print_colored(Colors.YELLOW, f"   [SCAN] Found {len(tables)} tables in database")
                        for table in tables:
                            self.delete_glue_table(glue_client, database_name, table['Name'], region, account_key)
            except ClientError:
                pass
            
            # Delete the database
            glue_client.delete_database(Name=database_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted database: {database_name}")
            self.log_action(f"Deleted Glue database: {database_name} in {region}")
            
            self.cleanup_results['deleted_databases'].append({
                'database': database_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete database {database_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Database',
                'name': database_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_glue_crawler(self, glue_client, crawler_name, region, account_key):
        """Delete a Glue crawler"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting crawler: {crawler_name}")
            
            glue_client.delete_crawler(Name=crawler_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted crawler: {crawler_name}")
            self.log_action(f"Deleted Glue crawler: {crawler_name} in {region}")
            
            self.cleanup_results['deleted_crawlers'].append({
                'crawler': crawler_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete crawler {crawler_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Crawler',
                'name': crawler_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_glue_job(self, glue_client, job_name, region, account_key):
        """Delete a Glue job"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting job: {job_name}")
            
            glue_client.delete_job(JobName=job_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted job: {job_name}")
            self.log_action(f"Deleted Glue job: {job_name} in {region}")
            
            self.cleanup_results['deleted_jobs'].append({
                'job': job_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete job {job_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Job',
                'name': job_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_glue_trigger(self, glue_client, trigger_name, region, account_key):
        """Delete a Glue trigger"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting trigger: {trigger_name}")
            
            glue_client.delete_trigger(Name=trigger_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted trigger: {trigger_name}")
            self.log_action(f"Deleted Glue trigger: {trigger_name} in {region}")
            
            self.cleanup_results['deleted_triggers'].append({
                'trigger': trigger_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete trigger {trigger_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Trigger',
                'name': trigger_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_glue_dev_endpoint(self, glue_client, endpoint_name, region, account_key):
        """Delete a Glue dev endpoint"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting dev endpoint: {endpoint_name}")
            
            glue_client.delete_dev_endpoint(EndpointName=endpoint_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted dev endpoint: {endpoint_name}")
            self.log_action(f"Deleted Glue dev endpoint: {endpoint_name} in {region}")
            
            self.cleanup_results['deleted_dev_endpoints'].append({
                'endpoint': endpoint_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete dev endpoint {endpoint_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'DevEndpoint',
                'name': endpoint_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_glue_ml_transform(self, glue_client, transform_id, region, account_key):
        """Delete a Glue ML transform"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting ML transform: {transform_id}")
            
            glue_client.delete_ml_transform(TransformId=transform_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted ML transform: {transform_id}")
            self.log_action(f"Deleted Glue ML transform: {transform_id} in {region}")
            
            self.cleanup_results['deleted_ml_transforms'].append({
                'transform_id': transform_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete ML transform {transform_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'MLTransform',
                'name': transform_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_glue_workflow(self, glue_client, workflow_name, region, account_key):
        """Delete a Glue workflow"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting workflow: {workflow_name}")
            
            glue_client.delete_workflow(Name=workflow_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted workflow: {workflow_name}")
            self.log_action(f"Deleted Glue workflow: {workflow_name} in {region}")
            
            self.cleanup_results['deleted_workflows'].append({
                'workflow': workflow_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete workflow {workflow_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Workflow',
                'name': workflow_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_glue(self, account_name, credentials, region):
        """Cleanup all Glue resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            glue_client = boto3.client(
                'glue',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Workflows
            try:
                workflows_response = glue_client.list_workflows()
                workflows = workflows_response.get('Workflows', [])
                
                if workflows:
                    self.print_colored(Colors.CYAN, f"[WORKFLOW] Found {len(workflows)} Glue workflows")
                    for workflow_name in workflows:
                        self.delete_glue_workflow(glue_client, workflow_name, region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue workflows in {region}: {e}", "ERROR")
            
            # Delete Triggers
            try:
                triggers_response = glue_client.get_triggers()
                triggers = triggers_response.get('Triggers', [])
                
                if triggers:
                    self.print_colored(Colors.CYAN, f"[TRIGGER] Found {len(triggers)} Glue triggers")
                    for trigger in triggers:
                        self.delete_glue_trigger(glue_client, trigger['Name'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue triggers in {region}: {e}", "ERROR")
            
            # Delete Jobs
            try:
                jobs_response = glue_client.get_jobs()
                jobs = jobs_response.get('Jobs', [])
                
                if jobs:
                    self.print_colored(Colors.CYAN, f"[JOB] Found {len(jobs)} Glue jobs")
                    for job in jobs:
                        self.delete_glue_job(glue_client, job['Name'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue jobs in {region}: {e}", "ERROR")
            
            # Delete Crawlers
            try:
                crawlers_response = glue_client.get_crawlers()
                crawlers = crawlers_response.get('Crawlers', [])
                
                if crawlers:
                    self.print_colored(Colors.CYAN, f"[CRAWLER] Found {len(crawlers)} Glue crawlers")
                    for crawler in crawlers:
                        self.delete_glue_crawler(glue_client, crawler['Name'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue crawlers in {region}: {e}", "ERROR")
            
            # Delete Dev Endpoints
            try:
                endpoints_response = glue_client.get_dev_endpoints()
                endpoints = endpoints_response.get('DevEndpoints', [])
                
                if endpoints:
                    self.print_colored(Colors.CYAN, f"[ENDPOINT] Found {len(endpoints)} Glue dev endpoints")
                    for endpoint in endpoints:
                        self.delete_glue_dev_endpoint(glue_client, endpoint['EndpointName'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue dev endpoints in {region}: {e}", "ERROR")
            
            # Delete ML Transforms
            try:
                transforms_response = glue_client.get_ml_transforms()
                transforms = transforms_response.get('Transforms', [])
                
                if transforms:
                    self.print_colored(Colors.CYAN, f"[ML] Found {len(transforms)} Glue ML transforms")
                    for transform in transforms:
                        self.delete_glue_ml_transform(glue_client, transform['TransformId'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue ML transforms in {region}: {e}", "ERROR")
            
            # Delete Databases (and their tables)
            try:
                databases_response = glue_client.get_databases()
                databases = databases_response.get('DatabaseList', [])
                
                if databases:
                    self.print_colored(Colors.CYAN, f"[DATABASE] Found {len(databases)} Glue databases")
                    for database in databases:
                        self.delete_glue_database(glue_client, database['Name'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing Glue databases in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_glue(self, account_name, credentials):
        """Cleanup all Glue resources in an account across all regions"""
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
                self.cleanup_region_glue(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"glue_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_databases_deleted': len(self.cleanup_results['deleted_databases']),
                    'total_tables_deleted': len(self.cleanup_results['deleted_tables']),
                    'total_crawlers_deleted': len(self.cleanup_results['deleted_crawlers']),
                    'total_jobs_deleted': len(self.cleanup_results['deleted_jobs']),
                    'total_triggers_deleted': len(self.cleanup_results['deleted_triggers']),
                    'total_dev_endpoints_deleted': len(self.cleanup_results['deleted_dev_endpoints']),
                    'total_ml_transforms_deleted': len(self.cleanup_results['deleted_ml_transforms']),
                    'total_workflows_deleted': len(self.cleanup_results['deleted_workflows']),
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
            self.print_colored(Colors.GREEN, f"[OK] Databases Deleted: {summary['summary']['total_databases_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Tables Deleted: {summary['summary']['total_tables_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Crawlers Deleted: {summary['summary']['total_crawlers_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Jobs Deleted: {summary['summary']['total_jobs_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Triggers Deleted: {summary['summary']['total_triggers_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Dev Endpoints Deleted: {summary['summary']['total_dev_endpoints_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] ML Transforms Deleted: {summary['summary']['total_ml_transforms_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Workflows Deleted: {summary['summary']['total_workflows_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for resource_list, key in [
                (self.cleanup_results['deleted_databases'], 'databases'),
                (self.cleanup_results['deleted_tables'], 'tables'),
                (self.cleanup_results['deleted_crawlers'], 'crawlers'),
                (self.cleanup_results['deleted_jobs'], 'jobs'),
                (self.cleanup_results['deleted_triggers'], 'triggers'),
                (self.cleanup_results['deleted_dev_endpoints'], 'dev_endpoints'),
                (self.cleanup_results['deleted_ml_transforms'], 'ml_transforms'),
                (self.cleanup_results['deleted_workflows'], 'workflows')
            ]:
                for resource in resource_list:
                    account = resource.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'databases': 0, 'tables': 0, 'crawlers': 0, 'jobs': 0,
                            'triggers': 0, 'dev_endpoints': 0, 'ml_transforms': 0,
                            'workflows': 0, 'regions': set()
                        }
                    account_summary[account][key] += 1
                    account_summary[account]['regions'].add(resource.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Databases: {stats['databases']}")
                self.print_colored(Colors.GREEN, f"  [OK] Tables: {stats['tables']}")
                self.print_colored(Colors.GREEN, f"  [OK] Crawlers: {stats['crawlers']}")
                self.print_colored(Colors.GREEN, f"  [OK] Jobs: {stats['jobs']}")
                self.print_colored(Colors.GREEN, f"  [OK] Triggers: {stats['triggers']}")
                self.print_colored(Colors.GREEN, f"  [OK] Dev Endpoints: {stats['dev_endpoints']}")
                self.print_colored(Colors.GREEN, f"  [OK] ML Transforms: {stats['ml_transforms']}")
                self.print_colored(Colors.GREEN, f"  [OK] Workflows: {stats['workflows']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")
            self.log_action(f"Failed to generate summary report: {e}", "ERROR")

    def interactive_cleanup(self):
        """Interactive mode for Glue cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA GLUE CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            # Load accounts
            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']

            # Display accounts
            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Glue Cleanup:")
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
            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all Glue resources!")
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

                self.cleanup_account_glue(account_name, credentials)
                time.sleep(2)

            # Generate summary
            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Glue cleanup completed!")
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
        manager = UltraCleanupGlueManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
