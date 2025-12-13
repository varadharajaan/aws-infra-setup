#!/usr/bin/env python3
"""
Ultra CI/CD Cleanup Manager
Comprehensive AWS CI/CD cleanup across multiple AWS accounts and regions
- Deletes CodeBuild Projects
- Deletes CodePipeline Pipelines
- Deletes CodeDeploy Applications and Deployment Groups
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


class UltraCleanupCICDManager:
    """Manager for comprehensive CI/CD cleanup operations"""

    def __init__(self):
        """Initialize the CI/CD cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'cicd')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'cicd_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_codebuild_projects': [],
            'deleted_codepipeline_pipelines': [],
            'deleted_codedeploy_applications': [],
            'deleted_codedeploy_deployment_groups': [],
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

    def delete_codebuild_project(self, codebuild_client, project_name, region, account_key):
        """Delete a CodeBuild project"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting CodeBuild project: {project_name}")
            
            codebuild_client.delete_project(name=project_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted CodeBuild project: {project_name}")
            self.log_action(f"Deleted CodeBuild project: {project_name} in {region}")
            
            self.cleanup_results['deleted_codebuild_projects'].append({
                'name': project_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete CodeBuild project {project_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'CodeBuildProject',
                'name': project_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_codepipeline_pipeline(self, codepipeline_client, pipeline_name, region, account_key):
        """Delete a CodePipeline pipeline"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting CodePipeline pipeline: {pipeline_name}")
            
            codepipeline_client.delete_pipeline(name=pipeline_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted CodePipeline pipeline: {pipeline_name}")
            self.log_action(f"Deleted CodePipeline pipeline: {pipeline_name} in {region}")
            
            self.cleanup_results['deleted_codepipeline_pipelines'].append({
                'name': pipeline_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete CodePipeline pipeline {pipeline_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'CodePipelinePipeline',
                'name': pipeline_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_codedeploy_deployment_group(self, codedeploy_client, app_name, deployment_group_name, region, account_key):
        """Delete a CodeDeploy deployment group"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting deployment group: {deployment_group_name} (App: {app_name})")
            
            codedeploy_client.delete_deployment_group(
                applicationName=app_name,
                deploymentGroupName=deployment_group_name
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted deployment group: {deployment_group_name}")
            self.log_action(f"Deleted deployment group: {deployment_group_name} from app {app_name} in {region}")
            
            self.cleanup_results['deleted_codedeploy_deployment_groups'].append({
                'name': deployment_group_name,
                'application': app_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete deployment group {deployment_group_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'CodeDeployDeploymentGroup',
                'name': deployment_group_name,
                'application': app_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_codedeploy_application(self, codedeploy_client, app_name, region, account_key):
        """Delete a CodeDeploy application"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting CodeDeploy application: {app_name}")
            
            # First, delete all deployment groups
            try:
                dg_response = codedeploy_client.list_deployment_groups(applicationName=app_name)
                deployment_groups = dg_response.get('deploymentGroups', [])
                
                if deployment_groups:
                    self.print_colored(Colors.YELLOW, f"   [DG] Found {len(deployment_groups)} deployment groups, deleting...")
                    for dg_name in deployment_groups:
                        self.delete_codedeploy_deployment_group(codedeploy_client, app_name, dg_name, region, account_key)
                        time.sleep(0.5)
            except ClientError:
                pass
            
            # Delete the application
            codedeploy_client.delete_application(applicationName=app_name)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted CodeDeploy application: {app_name}")
            self.log_action(f"Deleted CodeDeploy application: {app_name} in {region}")
            
            self.cleanup_results['deleted_codedeploy_applications'].append({
                'name': app_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete CodeDeploy application {app_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'CodeDeployApplication',
                'name': app_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_cicd(self, account_name, credentials, region):
        """Cleanup all CI/CD resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            # CodeBuild Client
            codebuild_client = boto3.client(
                'codebuild',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # CodePipeline Client
            codepipeline_client = boto3.client(
                'codepipeline',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # CodeDeploy Client
            codedeploy_client = boto3.client(
                'codedeploy',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete CodeBuild Projects
            try:
                projects_response = codebuild_client.list_projects()
                projects = projects_response.get('projects', [])
                
                if projects:
                    self.print_colored(Colors.CYAN, f"[BUILD] Found {len(projects)} CodeBuild projects")
                    for project_name in projects:
                        self.delete_codebuild_project(codebuild_client, project_name, region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing CodeBuild projects in {region}: {e}", "ERROR")
            
            # Delete CodePipeline Pipelines
            try:
                pipelines_response = codepipeline_client.list_pipelines()
                pipelines = pipelines_response.get('pipelines', [])
                
                if pipelines:
                    self.print_colored(Colors.CYAN, f"[PIPELINE] Found {len(pipelines)} CodePipeline pipelines")
                    for pipeline in pipelines:
                        pipeline_name = pipeline['name']
                        self.delete_codepipeline_pipeline(codepipeline_client, pipeline_name, region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing CodePipeline pipelines in {region}: {e}", "ERROR")
            
            # Delete CodeDeploy Applications (and their deployment groups)
            try:
                applications_response = codedeploy_client.list_applications()
                applications = applications_response.get('applications', [])
                
                if applications:
                    self.print_colored(Colors.CYAN, f"[DEPLOY] Found {len(applications)} CodeDeploy applications")
                    for app_name in applications:
                        self.delete_codedeploy_application(codedeploy_client, app_name, region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing CodeDeploy applications in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_cicd(self, account_name, credentials):
        """Cleanup all CI/CD resources in an account across all regions"""
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
                self.cleanup_region_cicd(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"cicd_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_codebuild_projects_deleted': len(self.cleanup_results['deleted_codebuild_projects']),
                    'total_codepipeline_pipelines_deleted': len(self.cleanup_results['deleted_codepipeline_pipelines']),
                    'total_codedeploy_applications_deleted': len(self.cleanup_results['deleted_codedeploy_applications']),
                    'total_codedeploy_deployment_groups_deleted': len(self.cleanup_results['deleted_codedeploy_deployment_groups']),
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
            self.print_colored(Colors.GREEN, f"[OK] CodeBuild Projects Deleted: {summary['summary']['total_codebuild_projects_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] CodePipeline Pipelines Deleted: {summary['summary']['total_codepipeline_pipelines_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] CodeDeploy Applications Deleted: {summary['summary']['total_codedeploy_applications_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] CodeDeploy Deployment Groups Deleted: {summary['summary']['total_codedeploy_deployment_groups_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            # Aggregate all deleted resources
            for item_list, key_name in [
                (self.cleanup_results['deleted_codebuild_projects'], 'codebuild_projects'),
                (self.cleanup_results['deleted_codepipeline_pipelines'], 'codepipeline_pipelines'),
                (self.cleanup_results['deleted_codedeploy_applications'], 'codedeploy_applications'),
                (self.cleanup_results['deleted_codedeploy_deployment_groups'], 'codedeploy_deployment_groups')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'codebuild_projects': 0,
                            'codepipeline_pipelines': 0,
                            'codedeploy_applications': 0,
                            'codedeploy_deployment_groups': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] CodeBuild Projects: {stats['codebuild_projects']}")
                self.print_colored(Colors.GREEN, f"  [OK] CodePipeline Pipelines: {stats['codepipeline_pipelines']}")
                self.print_colored(Colors.GREEN, f"  [OK] CodeDeploy Applications: {stats['codedeploy_applications']}")
                self.print_colored(Colors.GREEN, f"  [OK] CodeDeploy Deployment Groups: {stats['codedeploy_deployment_groups']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for CI/CD cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA CI/CD CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for CI/CD Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all CI/CD resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: CodeBuild, CodePipeline, CodeDeploy")
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

                self.cleanup_account_cicd(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] CI/CD cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupCICDManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
