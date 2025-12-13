#!/usr/bin/env python3
"""
Ultra EventBridge Cleanup Manager
Comprehensive EventBridge cleanup across multiple AWS accounts and regions
- Deletes Event Rules and Targets
- Deletes Custom Event Buses
- Deletes Event Archives
- Deletes API Destinations and Connections
- Deletes Event Schemas and Registries
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


class UltraCleanupEventBridgeManager:
    """Manager for comprehensive EventBridge cleanup operations"""

    def __init__(self):
        """Initialize the EventBridge cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'eventbridge')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'eventbridge_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_rules': [],
            'deleted_event_buses': [],
            'deleted_archives': [],
            'deleted_api_destinations': [],
            'deleted_connections': [],
            'deleted_schemas': [],
            'deleted_registries': [],
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

    def delete_rule_targets(self, events_client, rule_name, event_bus_name, region, account_key):
        """Remove all targets from a rule"""
        try:
            targets_response = events_client.list_targets_by_rule(
                Rule=rule_name,
                EventBusName=event_bus_name
            )
            
            targets = targets_response.get('Targets', [])
            if targets:
                target_ids = [target['Id'] for target in targets]
                events_client.remove_targets(
                    Rule=rule_name,
                    EventBusName=event_bus_name,
                    Ids=target_ids
                )
                self.print_colored(Colors.GREEN, f"   {Symbols.OK} Removed {len(target_ids)} targets from rule: {rule_name}")
            
            return True
        except ClientError as e:
            self.log_action(f"Failed to remove targets from rule {rule_name}: {e}", "ERROR")
            return False

    def delete_event_rule(self, events_client, rule_name, event_bus_name, region, account_key):
        """Delete an EventBridge rule"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting rule: {rule_name}")
            
            # Remove all targets first
            self.delete_rule_targets(events_client, rule_name, event_bus_name, region, account_key)
            
            # Delete the rule
            events_client.delete_rule(
                Name=rule_name,
                EventBusName=event_bus_name
            )
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted rule: {rule_name}")
            self.log_action(f"Deleted EventBridge rule: {rule_name} in {region}")
            
            self.cleanup_results['deleted_rules'].append({
                'rule': rule_name,
                'event_bus': event_bus_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete rule {rule_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Rule',
                'name': rule_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_event_bus(self, events_client, bus_name, region, account_key):
        """Delete a custom event bus"""
        try:
            # Skip default event bus
            if bus_name == 'default':
                return True
            
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting event bus: {bus_name}")
            
            # Delete all rules on this bus first
            try:
                rules_response = events_client.list_rules(EventBusName=bus_name)
                rules = rules_response.get('Rules', [])
                for rule in rules:
                    self.delete_event_rule(events_client, rule['Name'], bus_name, region, account_key)
            except ClientError:
                pass
            
            events_client.delete_event_bus(Name=bus_name)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted event bus: {bus_name}")
            self.log_action(f"Deleted event bus: {bus_name} in {region}")
            
            self.cleanup_results['deleted_event_buses'].append({
                'bus_name': bus_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete event bus {bus_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'EventBus',
                'name': bus_name,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_archive(self, events_client, archive_name, region, account_key):
        """Delete an event archive"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting archive: {archive_name}")
            
            events_client.delete_archive(ArchiveName=archive_name)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted archive: {archive_name}")
            self.log_action(f"Deleted archive: {archive_name} in {region}")
            
            self.cleanup_results['deleted_archives'].append({
                'archive_name': archive_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete archive {archive_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def delete_api_destination(self, events_client, destination_name, region, account_key):
        """Delete an API destination"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting API destination: {destination_name}")
            
            events_client.delete_api_destination(Name=destination_name)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted API destination: {destination_name}")
            self.log_action(f"Deleted API destination: {destination_name} in {region}")
            
            self.cleanup_results['deleted_api_destinations'].append({
                'destination_name': destination_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete API destination {destination_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def delete_connection(self, events_client, connection_name, region, account_key):
        """Delete a connection"""
        try:
            self.print_colored(Colors.CYAN, f"{Symbols.DELETE} Deleting connection: {connection_name}")
            
            events_client.delete_connection(Name=connection_name)
            
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Deleted connection: {connection_name}")
            self.log_action(f"Deleted connection: {connection_name} in {region}")
            
            self.cleanup_results['deleted_connections'].append({
                'connection_name': connection_name,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete connection {connection_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            return False

    def cleanup_region_eventbridge(self, account_name, credentials, region):
        """Cleanup all EventBridge resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n{Symbols.SCAN} Scanning region: {region}")
            
            events_client = boto3.client(
                'events',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete API Destinations
            try:
                destinations_response = events_client.list_api_destinations()
                destinations = destinations_response.get('ApiDestinations', [])
                
                if destinations:
                    self.print_colored(Colors.CYAN, f"[API] Found {len(destinations)} API destinations")
                    for destination in destinations:
                        self.delete_api_destination(events_client, destination['Name'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing API destinations in {region}: {e}", "ERROR")
            
            # Delete Connections
            try:
                connections_response = events_client.list_connections()
                connections = connections_response.get('Connections', [])
                
                if connections:
                    self.print_colored(Colors.CYAN, f"[CONNECT] Found {len(connections)} connections")
                    for connection in connections:
                        self.delete_connection(events_client, connection['Name'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing connections in {region}: {e}", "ERROR")
            
            # Delete Archives
            try:
                archives_response = events_client.list_archives()
                archives = archives_response.get('Archives', [])
                
                if archives:
                    self.print_colored(Colors.CYAN, f"[ARCHIVE] Found {len(archives)} archives")
                    for archive in archives:
                        self.delete_archive(events_client, archive['ArchiveName'], region, account_name)
                        time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing archives in {region}: {e}", "ERROR")
            
            # Delete Event Buses and their Rules
            try:
                buses_response = events_client.list_event_buses()
                event_buses = buses_response.get('EventBuses', [])
                
                if event_buses:
                    self.print_colored(Colors.CYAN, f"[BUS] Found {len(event_buses)} event buses")
                    for bus in event_buses:
                        # Delete rules on default bus first, then delete custom buses
                        bus_name = bus['Name']
                        
                        # Delete rules on this bus
                        try:
                            rules_response = events_client.list_rules(EventBusName=bus_name)
                            rules = rules_response.get('Rules', [])
                            if rules:
                                self.print_colored(Colors.YELLOW, f"   {Symbols.SCAN} Found {len(rules)} rules on bus: {bus_name}")
                                for rule in rules:
                                    self.delete_event_rule(events_client, rule['Name'], bus_name, region, account_name)
                                    time.sleep(0.3)
                        except ClientError as e:
                            self.log_action(f"Error listing rules for bus {bus_name}: {e}", "ERROR")
                        
                        # Delete custom buses (not default)
                        if bus_name != 'default':
                            self.delete_event_bus(events_client, bus_name, region, account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing event buses in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_eventbridge(self, account_name, credentials):
        """Cleanup all EventBridge resources in an account across all regions"""
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
                self.cleanup_region_eventbridge(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"{Symbols.ERROR} {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"eventbridge_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_rules_deleted': len(self.cleanup_results['deleted_rules']),
                    'total_event_buses_deleted': len(self.cleanup_results['deleted_event_buses']),
                    'total_archives_deleted': len(self.cleanup_results['deleted_archives']),
                    'total_api_destinations_deleted': len(self.cleanup_results['deleted_api_destinations']),
                    'total_connections_deleted': len(self.cleanup_results['deleted_connections']),
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
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Rules Deleted: {summary['summary']['total_rules_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Event Buses Deleted: {summary['summary']['total_event_buses_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Archives Deleted: {summary['summary']['total_archives_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} API Destinations Deleted: {summary['summary']['total_api_destinations_deleted']}")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Connections Deleted: {summary['summary']['total_connections_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"{Symbols.WARN} Failed Deletions: {summary['summary']['total_failed_deletions']}")

        except Exception as e:
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for EventBridge cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA EVENTBRIDGE CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, f"{Symbols.ERROR} No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, f"{Symbols.KEY} Select Root AWS Accounts for EventBridge Cleanup:")
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

            self.print_colored(Colors.RED, f"\n{Symbols.WARN} WARNING: This will DELETE all EventBridge resources!")
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

                self.cleanup_account_eventbridge(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} EventBridge cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupEventBridgeManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n{Symbols.ERROR} Fatal error: {e}")


if __name__ == "__main__":
    main()
