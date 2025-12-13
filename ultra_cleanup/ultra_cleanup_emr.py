#!/usr/bin/env python3
"""
Ultra AWS EMR Cleanup Manager
Comprehensive EMR cleanup across multiple AWS accounts and regions
- Terminates EMR Clusters
- Deletes Notebook Executions
- Deletes EMR Notebooks
- Deletes EMR Studios
- Deletes Security Configurations
- Deletes Instance Profiles
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


class UltraCleanupEMRManager:
    """Manager for comprehensive EMR cleanup operations"""

    def __init__(self):
        """Initialize the EMR cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'emr')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'emr_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'terminated_clusters': [],
            'deleted_notebooks': [],
            'deleted_studios': [],
            'deleted_security_configs': [],
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

    def terminate_cluster(self, emr_client, cluster_id, cluster_name, region, account_key):
        """Terminate an EMR cluster"""
        try:
            # Get cluster state
            cluster_response = emr_client.describe_cluster(ClusterId=cluster_id)
            state = cluster_response['Cluster']['Status']['State']
            
            # Skip if already terminating or terminated
            if state in ['TERMINATING', 'TERMINATED', 'TERMINATED_WITH_ERRORS']:
                self.print_colored(Colors.YELLOW, f"[SKIP] Cluster already {state}: {cluster_name}")
                return True
            
            self.print_colored(Colors.CYAN, f"[DELETE] Terminating cluster: {cluster_name} (State: {state})")
            
            # Terminate the cluster
            emr_client.terminate_job_flows(JobFlowIds=[cluster_id])
            
            self.print_colored(Colors.GREEN, f"[OK] Initiated termination for cluster: {cluster_name}")
            self.log_action(f"Terminated cluster: {cluster_name} ({cluster_id}) in {region}")
            
            self.cleanup_results['terminated_clusters'].append({
                'cluster_id': cluster_id,
                'cluster_name': cluster_name,
                'region': region,
                'account_key': account_key,
                'previous_state': state
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to terminate cluster {cluster_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'EMRCluster',
                'name': cluster_name,
                'id': cluster_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_notebook_execution(self, emr_client, execution_id, region, account_key):
        """Stop and delete a notebook execution"""
        try:
            # Get execution state
            execution_response = emr_client.describe_notebook_execution(NotebookExecutionId=execution_id)
            state = execution_response['NotebookExecution']['Status']
            
            # Stop if running
            if state in ['STARTING', 'RUNNING', 'PENDING']:
                self.print_colored(Colors.YELLOW, f"   [STOP] Stopping execution: {execution_id}")
                emr_client.stop_notebook_execution(NotebookExecutionId=execution_id)
                time.sleep(2)
            
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting execution: {execution_id}")
            
            # Note: EMR notebook executions are automatically deleted after completion/stop
            # No explicit delete API available
            
            self.print_colored(Colors.GREEN, f"   [OK] Stopped execution: {execution_id}")
            self.log_action(f"Stopped notebook execution: {execution_id} in {region}")
            return True
            
        except ClientError as e:
            self.log_action(f"Failed to stop notebook execution {execution_id}: {e}", "ERROR")
            return False

    def delete_notebook(self, emr_client, notebook_id, notebook_name, region, account_key):
        """Delete an EMR notebook"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting notebook: {notebook_name}")
            
            # Stop any running executions for this notebook
            try:
                executions_response = emr_client.list_notebook_executions(
                    EditorId=notebook_id
                )
                executions = executions_response.get('NotebookExecutions', [])
                
                for execution in executions:
                    if execution['Status'] in ['STARTING', 'RUNNING', 'PENDING']:
                        self.delete_notebook_execution(
                            emr_client,
                            execution['NotebookExecutionId'],
                            region,
                            account_key
                        )
            except ClientError:
                pass
            
            # Delete the notebook
            emr_client.delete_editor(Id=notebook_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted notebook: {notebook_name}")
            self.log_action(f"Deleted notebook: {notebook_name} ({notebook_id}) in {region}")
            
            self.cleanup_results['deleted_notebooks'].append({
                'notebook_id': notebook_id,
                'notebook_name': notebook_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete notebook {notebook_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'EMRNotebook',
                'name': notebook_name,
                'id': notebook_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_studio(self, emr_client, studio_id, studio_name, region, account_key):
        """Delete an EMR Studio"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting EMR Studio: {studio_name}")
            
            # Delete all studio session mappings first
            try:
                mappings_response = emr_client.list_studio_session_mappings(StudioId=studio_id)
                mappings = mappings_response.get('SessionMappings', [])
                
                for mapping in mappings:
                    try:
                        emr_client.delete_studio_session_mapping(
                            StudioId=studio_id,
                            IdentityType=mapping['IdentityType'],
                            IdentityId=mapping.get('IdentityId'),
                            IdentityName=mapping.get('IdentityName')
                        )
                        self.print_colored(Colors.YELLOW, f"   [DELETE] Deleted session mapping")
                    except ClientError:
                        pass
            except ClientError:
                pass
            
            # Delete the studio
            emr_client.delete_studio(StudioId=studio_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted EMR Studio: {studio_name}")
            self.log_action(f"Deleted EMR Studio: {studio_name} ({studio_id}) in {region}")
            
            self.cleanup_results['deleted_studios'].append({
                'studio_id': studio_id,
                'studio_name': studio_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete EMR Studio {studio_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'EMRStudio',
                'name': studio_name,
                'id': studio_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_security_configuration(self, emr_client, config_name, region, account_key):
        """Delete a security configuration"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting security configuration: {config_name}")
            
            emr_client.delete_security_configuration(Name=config_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted security configuration: {config_name}")
            self.log_action(f"Deleted security configuration: {config_name} in {region}")
            
            self.cleanup_results['deleted_security_configs'].append({
                'config_name': config_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete security configuration {config_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'SecurityConfiguration',
                'name': config_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_emr(self, account_name, credentials, region):
        """Cleanup all EMR resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            emr_client = boto3.client(
                'emr',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Terminate EMR Clusters
            try:
                clusters_response = emr_client.list_clusters(
                    ClusterStates=['STARTING', 'BOOTSTRAPPING', 'RUNNING', 'WAITING']
                )
                clusters = clusters_response.get('Clusters', [])
                
                if clusters:
                    self.print_colored(Colors.CYAN, f"[CLUSTER] Found {len(clusters)} active clusters")
                    for cluster in clusters:
                        self.terminate_cluster(
                            emr_client,
                            cluster['Id'],
                            cluster['Name'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing clusters in {region}: {e}", "ERROR")
            
            # Delete EMR Studios
            try:
                studios_response = emr_client.list_studios()
                studios = studios_response.get('Studios', [])
                
                if studios:
                    self.print_colored(Colors.CYAN, f"[STUDIO] Found {len(studios)} EMR Studios")
                    for studio in studios:
                        self.delete_studio(
                            emr_client,
                            studio['StudioId'],
                            studio['Name'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing EMR Studios in {region}: {e}", "ERROR")
            
            # Delete EMR Notebooks
            try:
                notebooks_response = emr_client.list_editors()
                notebooks = notebooks_response.get('Editors', [])
                
                if notebooks:
                    self.print_colored(Colors.CYAN, f"[NOTEBOOK] Found {len(notebooks)} notebooks")
                    for notebook in notebooks:
                        self.delete_notebook(
                            emr_client,
                            notebook['EditorId'],
                            notebook['Name'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing notebooks in {region}: {e}", "ERROR")
            
            # Delete Security Configurations
            try:
                configs_response = emr_client.list_security_configurations()
                configs = configs_response.get('SecurityConfigurations', [])
                
                if configs:
                    self.print_colored(Colors.CYAN, f"[CONFIG] Found {len(configs)} security configurations")
                    for config in configs:
                        self.delete_security_configuration(
                            emr_client,
                            config['Name'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing security configurations in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_emr(self, account_name, credentials):
        """Cleanup all EMR resources in an account across all regions"""
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
                self.cleanup_region_emr(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"emr_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_clusters_terminated': len(self.cleanup_results['terminated_clusters']),
                    'total_notebooks_deleted': len(self.cleanup_results['deleted_notebooks']),
                    'total_studios_deleted': len(self.cleanup_results['deleted_studios']),
                    'total_security_configs_deleted': len(self.cleanup_results['deleted_security_configs']),
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
            self.print_colored(Colors.GREEN, f"[OK] Clusters Terminated: {summary['summary']['total_clusters_terminated']}")
            self.print_colored(Colors.GREEN, f"[OK] Notebooks Deleted: {summary['summary']['total_notebooks_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Studios Deleted: {summary['summary']['total_studios_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Security Configs Deleted: {summary['summary']['total_security_configs_deleted']}")

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
                (self.cleanup_results['terminated_clusters'], 'clusters'),
                (self.cleanup_results['deleted_notebooks'], 'notebooks'),
                (self.cleanup_results['deleted_studios'], 'studios'),
                (self.cleanup_results['deleted_security_configs'], 'security_configs')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'clusters': 0,
                            'notebooks': 0,
                            'studios': 0,
                            'security_configs': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Clusters Terminated: {stats['clusters']}")
                self.print_colored(Colors.GREEN, f"  [OK] Notebooks: {stats['notebooks']}")
                self.print_colored(Colors.GREEN, f"  [OK] Studios: {stats['studios']}")
                self.print_colored(Colors.GREEN, f"  [OK] Security Configs: {stats['security_configs']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for EMR cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS EMR CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for EMR Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE/TERMINATE all EMR resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: Clusters, Notebooks, Studios, Security Configurations")
            self.print_colored(Colors.YELLOW, "[INFO] Active clusters will be terminated")
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

                self.cleanup_account_emr(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] EMR cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupEMRManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
