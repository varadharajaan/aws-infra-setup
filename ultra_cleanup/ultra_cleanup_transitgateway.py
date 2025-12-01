#!/usr/bin/env python3
"""
Ultra Transit Gateway Cleanup Manager
Comprehensive AWS Transit Gateway cleanup across multiple AWS accounts and regions
- Deletes Transit Gateway VPC Attachments
- Deletes Transit Gateway VPN Attachments
- Deletes Transit Gateway Peering Attachments
- Deletes Transit Gateway Route Tables
- Deletes Transit Gateway Connect Attachments
- Deletes Transit Gateways
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


class UltraCleanupTransitGatewayManager:
    """Manager for comprehensive Transit Gateway cleanup operations"""

    def __init__(self):
        """Initialize the Transit Gateway cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'transitgateway')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'transitgateway_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_vpc_attachments': [],
            'deleted_vpn_attachments': [],
            'deleted_peering_attachments': [],
            'deleted_connect_attachments': [],
            'deleted_route_tables': [],
            'deleted_transit_gateways': [],
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

    def wait_for_attachment_deletion(self, ec2_client, attachment_id, timeout=300):
        """Wait for a transit gateway attachment to be deleted"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = ec2_client.describe_transit_gateway_attachments(
                    TransitGatewayAttachmentIds=[attachment_id]
                )
                
                if not response.get('TransitGatewayAttachments'):
                    return True
                
                attachment = response['TransitGatewayAttachments'][0]
                state = attachment.get('State', '')
                
                if state == 'deleted':
                    return True
                
                time.sleep(5)
                
            except ClientError as e:
                if 'InvalidTransitGatewayAttachmentID.NotFound' in str(e):
                    return True
                time.sleep(5)
        
        return False

    def delete_transit_gateway_vpc_attachment(self, ec2_client, attachment_id, region, account_key):
        """Delete a Transit Gateway VPC attachment"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting VPC attachment: {attachment_id}")
            
            ec2_client.delete_transit_gateway_vpc_attachment(
                TransitGatewayAttachmentId=attachment_id
            )
            
            # Wait for deletion to complete
            if self.wait_for_attachment_deletion(ec2_client, attachment_id):
                self.print_colored(Colors.GREEN, f"[OK] Deleted VPC attachment: {attachment_id}")
                self.log_action(f"Deleted VPC attachment: {attachment_id} in {region}")
                
                self.cleanup_results['deleted_vpc_attachments'].append({
                    'id': attachment_id,
                    'region': region,
                    'account_key': account_key
                })
                return True
            else:
                self.print_colored(Colors.YELLOW, f"[WARN] VPC attachment deletion timeout: {attachment_id}")
                return False
            
        except ClientError as e:
            error_msg = f"Failed to delete VPC attachment {attachment_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'VPCAttachment',
                'id': attachment_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_transit_gateway_vpn_attachment(self, ec2_client, attachment_id, region, account_key):
        """Delete a Transit Gateway VPN attachment"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting VPN attachment: {attachment_id}")
            
            # Get the VPN connection ID from the attachment
            response = ec2_client.describe_transit_gateway_attachments(
                TransitGatewayAttachmentIds=[attachment_id]
            )
            
            if response.get('TransitGatewayAttachments'):
                attachment = response['TransitGatewayAttachments'][0]
                vpn_conn_id = attachment.get('ResourceId')
                
                if vpn_conn_id:
                    # Delete the VPN connection (this will delete the attachment)
                    ec2_client.delete_vpn_connection(VpnConnectionId=vpn_conn_id)
                    
                    if self.wait_for_attachment_deletion(ec2_client, attachment_id):
                        self.print_colored(Colors.GREEN, f"[OK] Deleted VPN attachment: {attachment_id}")
                        self.log_action(f"Deleted VPN attachment: {attachment_id} in {region}")
                        
                        self.cleanup_results['deleted_vpn_attachments'].append({
                            'id': attachment_id,
                            'vpn_connection_id': vpn_conn_id,
                            'region': region,
                            'account_key': account_key
                        })
                        return True
            
            return False
            
        except ClientError as e:
            error_msg = f"Failed to delete VPN attachment {attachment_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'VPNAttachment',
                'id': attachment_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_transit_gateway_peering_attachment(self, ec2_client, attachment_id, region, account_key):
        """Delete a Transit Gateway peering attachment"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting peering attachment: {attachment_id}")
            
            ec2_client.delete_transit_gateway_peering_attachment(
                TransitGatewayAttachmentId=attachment_id
            )
            
            if self.wait_for_attachment_deletion(ec2_client, attachment_id):
                self.print_colored(Colors.GREEN, f"[OK] Deleted peering attachment: {attachment_id}")
                self.log_action(f"Deleted peering attachment: {attachment_id} in {region}")
                
                self.cleanup_results['deleted_peering_attachments'].append({
                    'id': attachment_id,
                    'region': region,
                    'account_key': account_key
                })
                return True
            
            return False
            
        except ClientError as e:
            error_msg = f"Failed to delete peering attachment {attachment_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'PeeringAttachment',
                'id': attachment_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_transit_gateway_connect_attachment(self, ec2_client, attachment_id, region, account_key):
        """Delete a Transit Gateway Connect attachment"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting Connect attachment: {attachment_id}")
            
            ec2_client.delete_transit_gateway_connect(
                TransitGatewayAttachmentId=attachment_id
            )
            
            if self.wait_for_attachment_deletion(ec2_client, attachment_id):
                self.print_colored(Colors.GREEN, f"[OK] Deleted Connect attachment: {attachment_id}")
                self.log_action(f"Deleted Connect attachment: {attachment_id} in {region}")
                
                self.cleanup_results['deleted_connect_attachments'].append({
                    'id': attachment_id,
                    'region': region,
                    'account_key': account_key
                })
                return True
            
            return False
            
        except ClientError as e:
            error_msg = f"Failed to delete Connect attachment {attachment_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'ConnectAttachment',
                'id': attachment_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_transit_gateway_route_table(self, ec2_client, route_table_id, region, account_key):
        """Delete a Transit Gateway route table"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting route table: {route_table_id}")
            
            ec2_client.delete_transit_gateway_route_table(
                TransitGatewayRouteTableId=route_table_id
            )
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted route table: {route_table_id}")
            self.log_action(f"Deleted route table: {route_table_id} in {region}")
            
            self.cleanup_results['deleted_route_tables'].append({
                'id': route_table_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete route table {route_table_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'RouteTable',
                'id': route_table_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_transit_gateway(self, ec2_client, tgw_id, region, account_key):
        """Delete a Transit Gateway"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting Transit Gateway: {tgw_id}")
            
            ec2_client.delete_transit_gateway(TransitGatewayId=tgw_id)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted Transit Gateway: {tgw_id}")
            self.log_action(f"Deleted Transit Gateway: {tgw_id} in {region}")
            
            self.cleanup_results['deleted_transit_gateways'].append({
                'id': tgw_id,
                'region': region,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete Transit Gateway {tgw_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'TransitGateway',
                'id': tgw_id,
                'region': region,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_region_transitgateway(self, account_name, credentials, region):
        """Cleanup all Transit Gateway resources in a specific region"""
        try:
            self.print_colored(Colors.YELLOW, f"\n[SCAN] Scanning region: {region}")
            
            ec2_client = boto3.client(
                'ec2',
                region_name=region,
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Get all Transit Gateways in this region
            try:
                tgws_response = ec2_client.describe_transit_gateways()
                transit_gateways = tgws_response.get('TransitGateways', [])
                
                if not transit_gateways:
                    return
                
                self.print_colored(Colors.CYAN, f"[TGW] Found {len(transit_gateways)} Transit Gateways")
                
                for tgw in transit_gateways:
                    tgw_id = tgw['TransitGatewayId']
                    tgw_state = tgw.get('State', '')
                    
                    if tgw_state in ['deleting', 'deleted']:
                        continue
                    
                    # Delete all attachments for this TGW
                    try:
                        attachments_response = ec2_client.describe_transit_gateway_attachments(
                            Filters=[{'Name': 'transit-gateway-id', 'Values': [tgw_id]}]
                        )
                        
                        attachments = attachments_response.get('TransitGatewayAttachments', [])
                        
                        if attachments:
                            self.print_colored(Colors.CYAN, f"[ATTACH] Found {len(attachments)} attachments for {tgw_id}")
                            
                            for attachment in attachments:
                                attachment_id = attachment['TransitGatewayAttachmentId']
                                attachment_type = attachment.get('ResourceType', '')
                                attachment_state = attachment.get('State', '')
                                
                                if attachment_state in ['deleting', 'deleted']:
                                    continue
                                
                                if attachment_type == 'vpc':
                                    self.delete_transit_gateway_vpc_attachment(ec2_client, attachment_id, region, account_name)
                                elif attachment_type == 'vpn':
                                    self.delete_transit_gateway_vpn_attachment(ec2_client, attachment_id, region, account_name)
                                elif attachment_type == 'peering':
                                    self.delete_transit_gateway_peering_attachment(ec2_client, attachment_id, region, account_name)
                                elif attachment_type == 'connect':
                                    self.delete_transit_gateway_connect_attachment(ec2_client, attachment_id, region, account_name)
                                
                                time.sleep(1)
                    
                    except ClientError as e:
                        self.log_action(f"Error listing attachments for {tgw_id} in {region}: {e}", "ERROR")
                    
                    # Delete route tables for this TGW
                    try:
                        route_tables_response = ec2_client.describe_transit_gateway_route_tables(
                            Filters=[{'Name': 'transit-gateway-id', 'Values': [tgw_id]}]
                        )
                        
                        route_tables = route_tables_response.get('TransitGatewayRouteTables', [])
                        
                        if route_tables:
                            self.print_colored(Colors.CYAN, f"[RTB] Found {len(route_tables)} route tables for {tgw_id}")
                            
                            for rt in route_tables:
                                rt_id = rt['TransitGatewayRouteTableId']
                                rt_state = rt.get('State', '')
                                is_default = rt.get('DefaultAssociationRouteTable', False)
                                
                                if rt_state in ['deleting', 'deleted']:
                                    continue
                                
                                # Delete non-default route tables
                                if not is_default:
                                    self.delete_transit_gateway_route_table(ec2_client, rt_id, region, account_name)
                                    time.sleep(1)
                    
                    except ClientError as e:
                        self.log_action(f"Error listing route tables for {tgw_id} in {region}: {e}", "ERROR")
                    
                    # Finally, delete the Transit Gateway itself
                    time.sleep(5)  # Give time for attachments and route tables to delete
                    self.delete_transit_gateway(ec2_client, tgw_id, region, account_name)
                    time.sleep(2)
            
            except ClientError as e:
                self.log_action(f"Error listing Transit Gateways in {region}: {e}", "ERROR")
            
        except Exception as e:
            error_msg = f"Error processing region {region}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def cleanup_account_transitgateway(self, account_name, credentials):
        """Cleanup all Transit Gateway resources in an account across all regions"""
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
                self.cleanup_region_transitgateway(account_name, credentials, region)
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"transitgateway_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_vpc_attachments_deleted': len(self.cleanup_results['deleted_vpc_attachments']),
                    'total_vpn_attachments_deleted': len(self.cleanup_results['deleted_vpn_attachments']),
                    'total_peering_attachments_deleted': len(self.cleanup_results['deleted_peering_attachments']),
                    'total_connect_attachments_deleted': len(self.cleanup_results['deleted_connect_attachments']),
                    'total_route_tables_deleted': len(self.cleanup_results['deleted_route_tables']),
                    'total_transit_gateways_deleted': len(self.cleanup_results['deleted_transit_gateways']),
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
            self.print_colored(Colors.GREEN, f"[OK] VPC Attachments Deleted: {summary['summary']['total_vpc_attachments_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] VPN Attachments Deleted: {summary['summary']['total_vpn_attachments_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Peering Attachments Deleted: {summary['summary']['total_peering_attachments_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Connect Attachments Deleted: {summary['summary']['total_connect_attachments_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Route Tables Deleted: {summary['summary']['total_route_tables_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Transit Gateways Deleted: {summary['summary']['total_transit_gateways_deleted']}")

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
                (self.cleanup_results['deleted_vpc_attachments'], 'vpc_attachments'),
                (self.cleanup_results['deleted_vpn_attachments'], 'vpn_attachments'),
                (self.cleanup_results['deleted_peering_attachments'], 'peering_attachments'),
                (self.cleanup_results['deleted_connect_attachments'], 'connect_attachments'),
                (self.cleanup_results['deleted_route_tables'], 'route_tables'),
                (self.cleanup_results['deleted_transit_gateways'], 'transit_gateways')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'vpc_attachments': 0, 'vpn_attachments': 0, 'peering_attachments': 0,
                            'connect_attachments': 0, 'route_tables': 0, 'transit_gateways': 0,
                            'regions': set()
                        }
                    account_summary[account][key_name] += 1
                    account_summary[account]['regions'].add(item.get('region', 'unknown'))

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Transit Gateways: {stats['transit_gateways']}")
                self.print_colored(Colors.GREEN, f"  [OK] VPC Attachments: {stats['vpc_attachments']}")
                self.print_colored(Colors.GREEN, f"  [OK] VPN Attachments: {stats['vpn_attachments']}")
                self.print_colored(Colors.GREEN, f"  [OK] Peering Attachments: {stats['peering_attachments']}")
                self.print_colored(Colors.GREEN, f"  [OK] Connect Attachments: {stats['connect_attachments']}")
                self.print_colored(Colors.GREEN, f"  [OK] Route Tables: {stats['route_tables']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for Transit Gateway cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA TRANSIT GATEWAY CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Transit Gateway Cleanup:")
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

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all Transit Gateway resources!")
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

                self.cleanup_account_transitgateway(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Transit Gateway cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupTransitGatewayManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
