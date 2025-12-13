#!/usr/bin/env python3
"""
Ultra Step Functions Cleanup Manager
Comprehensive AWS Step Functions cleanup across multiple AWS accounts and regions
- Deletes State Machines (Standard and Express)
- Deletes Activities
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


class UltraCleanupStepFunctionsManager:
    """Manager for comprehensive Step Functions cleanup operations"""

    def __init__(self):
        """Initialize the Step Functions cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'stepfunctions')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'stepfunctions_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_state_machines': [],
            'deleted_activities': [],
            'failed_deletions': [],
            'errors': []
        }

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def delete_state_machine(self, sfn_client, state_machine_arn, region, account_key):
        """Delete a Step Functions state machine"""
        try:
            # Extract state machine name from ARN
            state_machine_name = state_machine_arn.split(':')[-1]
            
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting state machine: {state_machine_name}")
            
            # Stop all running executions first
            try:
                executions_response = sfn_client.list_executions(
                    stateMachineArn=state_machine_arn,
                    statusFilter='RUNNING'
                )
                
                running_executions = executions_response.get('executions', [])
                if running_executions:
                    self.print_colored(Colors.YELLOW, f"   {Symbols.STOP} Stopping {len(running_executions)} running executions")
                    for execution in running_executions:
                        try:
                            sfn_client.stop_execution(executionArn=execution['executionArn'])
                        except ClientError:
                            pass
                    time.sleep(2)  # Wait for executions to stop
            except ClientError:
                pass
            
            # Delete the state machine
            sfn_client.delete_state_machine(stateMachineArn=state_machine_arn)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted state machine: {state_machine_name}")
            self.log_action(f"Deleted state machine: {state_machine_name} in {region}")
            
            self.cleanup_results['deleted_state_machines'].append({
                'name': state_machine_name,
                'arn': state_machine_arn,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete state machine {state_machine_arn}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'StateMachine',
                'arn': state_machine_arn,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_activity(self, sfn_client, activity_arn, region, account_key):
        """Delete a Step Functions activity"""
        try:
            # Extract activity name from ARN
            activity_name = activity_arn.split(':')[-1]
            
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting activity: {activity_name}")
            
            sfn_client.delete_activity(activityArn=activity_arn)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted activity: {activity_name}")
            self.log_action(f"Deleted activity: {activity_name} in {region}")
            
            self.cleanup_results['deleted_activities'].append({
                'name': activity_name,
                'arn': activity_arn,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete activity {activity_arn}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Activity',
                'arn': activity_arn,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_stepfunctions(self, account_name, credentials, region):
        """Cleanup all Step Functions resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n{Symbols.SCAN} Scanning region: {region}")
            
            sfn_client = boto3.client(
                'stepfunctions',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete State Machines
            try:
                state_machines_response = sfn_client.list_state_machines()
                state_machines = state_machines_response.get('stateMachines', [])
                
                if state_machines:
                    self.print_colored(Colors.CYAN, f"[STATE] Found {len(state_machines)} state machines")
                    for sm in state_machines:
                        self.delete_state_machine(sfn_client, sm['stateMachineArn'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing state machines in {region}: {e}", "ERROR")
            
            # Delete Activities
            try:
                activities_response = sfn_client.list_activities()
                activities = activities_response.get('activities', [])
                
                if activities:
                    self.print_colored(Colors.CYAN, f"[ACTIVITY] Found {len(activities)} activities")
                    for activity in activities:
                        self.delete_activity(sfn_client, activity['activityArn'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing activities in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_stepfunctions(self, account_name, credentials):
        """Cleanup all Step Functions resources in an account across all regions"""
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
                self.cleanup_region_stepfunctions(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"stepfunctions_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_state_machines_deleted': len(self.cleanup_results['deleted_state_machines']),
                    'total_activities_deleted': len(self.cleanup_results['deleted_activities']),
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
            self.print_colored(Colors.GREEN, f"{Symbols.OK} State Machines Deleted: {summary['summary']['total_state_machines_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Activities Deleted: {summary['summary']['total_activities_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN} Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            for sm in self.cleanup_results['deleted_state_machines']:
                account = sm.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {'state_machines': 0, 'activities': 0, 'regions': set()}
                account_summary[account]['state_machines'] += 1
                account_summary[account]['regions'].add(sm.get('region', 'unknown'))

            for activity in self.cleanup_results['deleted_activities']:
                account = activity.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {'state_machines': 0, 'activities': 0, 'regions': set()}
                account_summary[account]['activities'] += 1
                account_summary[account]['regions'].add(activity.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n{Symbols.LIST} Account: {account}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} State Machines: {stats['state_machines']}")
                self.print_colored(Colors.GREEN, f"  {Symbols.OK} Activities: {stats['activities']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  {Symbols.SCAN} Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for Step Functions cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA STEP FUNCTIONS CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, f"{Symbols.KEY} Select Root AWS Accounts for Step Functions Cleanup:")
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

            self.print_colored(Colors.RED, f"\n{Symbols.WARN} WARNING: This will DELETE all Step Functions resources!")
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

                self.cleanup_account_stepfunctions(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Step Functions cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupStepFunctionsManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n{Symbols.ERROR} Fatal error: {e}")


if __name__ == "__main__":
    main()
