#!/usr/bin/env python3
"""
Ultra AWS Transfer Family Cleanup Manager
Comprehensive Transfer Family cleanup across multiple AWS accounts and regions
- Deletes Transfer Servers (SFTP/FTPS/FTP/AS2)
- Deletes Users
- Deletes Workflows
- Deletes Connectors
- Deletes Certificates
- Deletes Profiles
- Deletes Agreements
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


class UltraCleanupTransferFamilyManager:
    """Manager for comprehensive AWS Transfer Family cleanup operations"""

    def __init__(self):
        """Initialize the Transfer Family cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'transfer_family')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'transfer_family_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_servers': [],
            'deleted_users': [],
            'deleted_workflows': [],
            'deleted_connectors': [],
            'deleted_certificates': [],
            'deleted_profiles': [],
            'deleted_agreements': [],
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

    def delete_server_user(self, transfer_client, server_id, username, region, account_key):
        """Delete a user from a Transfer server"""
        try:
            self.print_colored(Colors.CYAN, f"   [USER] Deleting user: {username}")
            
            transfer_client.delete_user(
                ServerId=server_id,
                UserName=username
            )
            
            self.print_colored(Colors.GREEN, f"   [OK] Deleted user: {username}")
            self.log_action(f"Deleted user {username} from server {server_id} in {region}")
            
            self.cleanup_results['deleted_users'].append({
                'username': username,
                'server_id': server_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            self.log_action(f"Failed to delete user {username}: {e}", "ERROR")
            return False

    def delete_server(self, transfer_client, server_id, region, account_key):
        """Delete a Transfer Family server"""
        try:
            # Get server details
            server_response = transfer_client.describe_server(ServerId=server_id)
            server = server_response['Server']
            protocol = server.get('Protocols', ['UNKNOWN'])[0]
            state = server.get('State', 'UNKNOWN')
            
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting server: {server_id} (Protocol: {protocol}, State: {state})")
            
            # Skip if already offline/stopping
            if state in ['STOPPING', 'OFFLINE']:
                self.print_colored(Colors.YELLOW, f"[SKIP] Server already {state}: {server_id}")
                return True
            
            # Delete all users first
            try:
                users_response = transfer_client.list_users(ServerId=server_id)
                users = users_response.get('Users', [])
                
                if users:
                    self.print_colored(Colors.YELLOW, f"   [SCAN] Found {len(users)} users")
                    for user in users:
                        self.delete_server_user(
                            transfer_client,
                            server_id,
                            user['UserName'],
                            region,
                            account_key
                        )
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing users for server {server_id}: {e}", "ERROR")
            
            # Stop server if online
            if state == 'ONLINE':
                self.print_colored(Colors.YELLOW, f"   [STOP] Stopping server...")
                transfer_client.stop_server(ServerId=server_id)
                time.sleep(5)
            
            # Delete the server
            transfer_client.delete_server(ServerId=server_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted server: {server_id}")
            self.log_action(f"Deleted Transfer server: {server_id} in {region}")
            
            self.cleanup_results['deleted_servers'].append({
                'server_id': server_id,
                'protocol': protocol,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete server {server_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'TransferServer',
                'name': server_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_workflow(self, transfer_client, workflow_id, region, account_key):
        """Delete a Transfer workflow"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting workflow: {workflow_id}")
            
            transfer_client.delete_workflow(WorkflowId=workflow_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted workflow: {workflow_id}")
            self.log_action(f"Deleted workflow: {workflow_id} in {region}")
            
            self.cleanup_results['deleted_workflows'].append({
                'workflow_id': workflow_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete workflow {workflow_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Workflow',
                'name': workflow_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_connector(self, transfer_client, connector_id, region, account_key):
        """Delete an AS2 connector"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting connector: {connector_id}")
            
            transfer_client.delete_connector(ConnectorId=connector_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted connector: {connector_id}")
            self.log_action(f"Deleted connector: {connector_id} in {region}")
            
            self.cleanup_results['deleted_connectors'].append({
                'connector_id': connector_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete connector {connector_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Connector',
                'name': connector_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_certificate(self, transfer_client, certificate_id, region, account_key):
        """Delete a certificate"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting certificate: {certificate_id}")
            
            transfer_client.delete_certificate(CertificateId=certificate_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted certificate: {certificate_id}")
            self.log_action(f"Deleted certificate: {certificate_id} in {region}")
            
            self.cleanup_results['deleted_certificates'].append({
                'certificate_id': certificate_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete certificate {certificate_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Certificate',
                'name': certificate_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_profile(self, transfer_client, profile_id, region, account_key):
        """Delete an AS2 profile"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting profile: {profile_id}")
            
            transfer_client.delete_profile(ProfileId=profile_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted profile: {profile_id}")
            self.log_action(f"Deleted profile: {profile_id} in {region}")
            
            self.cleanup_results['deleted_profiles'].append({
                'profile_id': profile_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete profile {profile_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Profile',
                'name': profile_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_agreement(self, transfer_client, agreement_id, server_id, region, account_key):
        """Delete an AS2 agreement"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting agreement: {agreement_id}")
            
            transfer_client.delete_agreement(
                AgreementId=agreement_id,
                ServerId=server_id
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted agreement: {agreement_id}")
            self.log_action(f"Deleted agreement: {agreement_id} in {region}")
            
            self.cleanup_results['deleted_agreements'].append({
                'agreement_id': agreement_id,
                'server_id': server_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete agreement {agreement_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def cleanup_region_transfer(self, account_name, credentials, region):
        """Cleanup all Transfer Family resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            transfer_client = boto3.client(
                'transfer',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Agreements (before servers)
            try:
                servers_response = transfer_client.list_servers()
                servers = servers_response.get('Servers', [])
                
                for server in servers:
                    server_id = server['ServerId']
                    try:
                        agreements_response = transfer_client.list_agreements(ServerId=server_id)
                        agreements = agreements_response.get('Agreements', [])
                        
                        if agreements:
                            self.print_colored(Colors.YELLOW, f"   [AGREE] Found {len(agreements)} agreements for server {server_id}")
                            for agreement in agreements:
                                self.delete_agreement(
                                    transfer_client,
                                    agreement['AgreementId'],
                                    server_id,
                                    region,
                                    account_name
                                )
                                time.sleep(0.5)
                    except ClientError:
                        pass
            except ClientError as e:
                self.log_action(f"Error listing servers/agreements in {region}: {e}", "ERROR")
            
            # Delete Connectors
            try:
                connectors_response = transfer_client.list_connectors()
                connectors = connectors_response.get('Connectors', [])
                
                if connectors:
                    self.print_colored(Colors.CYAN, f"[CONNECTOR] Found {len(connectors)} connectors")
                    for connector in connectors:
                        self.delete_connector(
                            transfer_client,
                            connector['ConnectorId'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing connectors in {region}: {e}", "ERROR")
            
            # Delete Workflows
            try:
                workflows_response = transfer_client.list_workflows()
                workflows = workflows_response.get('Workflows', [])
                
                if workflows:
                    self.print_colored(Colors.CYAN, f"[WORKFLOW] Found {len(workflows)} workflows")
                    for workflow in workflows:
                        self.delete_workflow(
                            transfer_client,
                            workflow['WorkflowId'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing workflows in {region}: {e}", "ERROR")
            
            # Delete Servers (and their users)
            try:
                servers_response = transfer_client.list_servers()
                servers = servers_response.get('Servers', [])
                
                if servers:
                    self.print_colored(Colors.CYAN, f"[SERVER] Found {len(servers)} servers")
                    for server in servers:
                        self.delete_server(
                            transfer_client,
                            server['ServerId'],
                            region,
                            account_name
                        )
                        time.sleep(2)
            except ClientError as e:
                self.log_action(f"Error listing servers in {region}: {e}", "ERROR")
            
            # Delete Profiles
            try:
                profiles_response = transfer_client.list_profiles()
                profiles = profiles_response.get('Profiles', [])
                
                if profiles:
                    self.print_colored(Colors.CYAN, f"[PROFILE] Found {len(profiles)} profiles")
                    for profile in profiles:
                        self.delete_profile(
                            transfer_client,
                            profile['ProfileId'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing profiles in {region}: {e}", "ERROR")
            
            # Delete Certificates
            try:
                certificates_response = transfer_client.list_certificates()
                certificates = certificates_response.get('Certificates', [])
                
                if certificates:
                    self.print_colored(Colors.CYAN, f"[CERT] Found {len(certificates)} certificates")
                    for certificate in certificates:
                        self.delete_certificate(
                            transfer_client,
                            certificate['CertificateId'],
                            region,
                            account_name
                        )
                        time.sleep(1)
            except ClientError as e:
                self.log_action(f"Error listing certificates in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_transfer(self, account_name, credentials):
        """Cleanup all Transfer Family resources in an account across all regions"""
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
                self.cleanup_region_transfer(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"transfer_family_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_servers_deleted': len(self.cleanup_results['deleted_servers']),
                    'total_users_deleted': len(self.cleanup_results['deleted_users']),
                    'total_workflows_deleted': len(self.cleanup_results['deleted_workflows']),
                    'total_connectors_deleted': len(self.cleanup_results['deleted_connectors']),
                    'total_certificates_deleted': len(self.cleanup_results['deleted_certificates']),
                    'total_profiles_deleted': len(self.cleanup_results['deleted_profiles']),
                    'total_agreements_deleted': len(self.cleanup_results['deleted_agreements']),
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
            self.print_colored(Colors.GREEN, f"[OK] Servers Deleted: {summary['summary']['total_servers_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Users Deleted: {summary['summary']['total_users_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Workflows Deleted: {summary['summary']['total_workflows_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Connectors Deleted: {summary['summary']['total_connectors_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Certificates Deleted: {summary['summary']['total_certificates_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Profiles Deleted: {summary['summary']['total_profiles_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Agreements Deleted: {summary['summary']['total_agreements_deleted']}")

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
                (self.cleanup_results['deleted_servers'], 'servers'),
                (self.cleanup_results['deleted_users'], 'users'),
                (self.cleanup_results['deleted_workflows'], 'workflows'),
                (self.cleanup_results['deleted_connectors'], 'connectors'),
                (self.cleanup_results['deleted_certificates'], 'certificates'),
                (self.cleanup_results['deleted_profiles'], 'profiles'),
                (self.cleanup_results['deleted_agreements'], 'agreements')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'servers': 0,
                            'users': 0,
                            'workflows': 0,
                            'connectors': 0,
                            'certificates': 0,
                            'profiles': 0,
                            'agreements': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Servers: {stats['servers']}")
                self.print_colored(Colors.GREEN, f"  [OK] Users: {stats['users']}")
                self.print_colored(Colors.GREEN, f"  [OK] Workflows: {stats['workflows']}")
                self.print_colored(Colors.GREEN, f"  [OK] Connectors: {stats['connectors']}")
                self.print_colored(Colors.GREEN, f"  [OK] Certificates: {stats['certificates']}")
                self.print_colored(Colors.GREEN, f"  [OK] Profiles: {stats['profiles']}")
                self.print_colored(Colors.GREEN, f"  [OK] Agreements: {stats['agreements']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for Transfer Family cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA AWS TRANSFER FAMILY CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Transfer Family Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all Transfer Family resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Includes: Servers (SFTP/FTPS/FTP/AS2), Users, Workflows, Connectors, Certificates")
            self.print_colored(Colors.YELLOW, f"[INFO] Cost savings: ~$216/month per server (~$0.30/hour)")
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

                self.cleanup_account_transfer(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Transfer Family cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupTransferFamilyManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
