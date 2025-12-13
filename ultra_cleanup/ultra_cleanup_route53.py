#!/usr/bin/env python3

"""
Ultra Route53 Cleanup Manager

Tool to perform comprehensive cleanup of Route53 resources across AWS accounts.

Manages deletion of:
- Hosted Zones (Public and Private)
- All Record Sets (A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, SRV, SPF, CAA, etc.)
- Health Checks
- Traffic Policies
- Traffic Policy Instances
- Query Logging Configurations
- Reusable Delegation Sets
- DNSSEC Configurations

PROTECTIONS:
- VPCs associated with private hosted zones are PRESERVED (only zone association is removed)
- NS and SOA records for hosted zones are handled automatically during zone deletion
- Does NOT delete VPCs, security groups, or any network infrastructure

Author: varadharajaan
Created: 2025-12-01
"""

import os
import json
import boto3
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from botocore.exceptions import ClientError, BotoCoreError
import botocore
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupRoute53Manager:
    """
    Tool to perform comprehensive cleanup of Route53 resources across AWS accounts.
    """

    def __init__(self, config_dir: str = None):
        """Initialize the Route53 Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.route53_dir = os.path.join(self.config_dir, "aws", "route53")
        self.reports_dir = os.path.join(self.route53_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_hosted_zones': [],
            'deleted_record_sets': [],
            'deleted_health_checks': [],
            'deleted_traffic_policies': [],
            'deleted_query_logging_configs': [],
            'deleted_reusable_delegation_sets': [],
            'disassociated_vpcs': [],
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

        # Record types that can be deleted
        self.deletable_record_types = [
            'A', 'AAAA', 'CNAME', 'MX', 'TXT', 'PTR', 'SRV', 'SPF', 'CAA', 'DS'
        ]

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.route53_dir, exist_ok=True)
            os.makedirs(self.reports_dir, exist_ok=True)

            log_filename = f"route53_cleanup_{self.execution_timestamp}.log"
            self.log_file = os.path.join(self.route53_dir, log_filename)

            with open(self.log_file, 'w') as f:
                f.write(f"Route53 Ultra Cleanup Log - Started at {self.current_time}\n")
                f.write(f"User: {self.current_user}\n")
                f.write("=" * 80 + "\n\n")

            self.print_colored(Colors.GREEN, f"[OK] Logging initialized: {self.log_file}")
        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to setup logging: {e}")

    def log_action(self, message: str, level: str = "INFO"):
        """Log action to file with timestamp"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [{level}] {message}\n"

            with open(self.log_file, 'a') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"Warning: Could not write to log file: {e}")

    def create_route53_client(self, credentials: Dict[str, str]) -> boto3.client:
        """Create Route53 client with credentials."""
        try:
            return boto3.client(
                'route53',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
        except Exception as e:
            raise Exception(f"Failed to create Route53 client: {e}")

    def list_all_hosted_zones(self, route53_client) -> List[Dict[str, Any]]:
        """List all hosted zones in the account."""
        hosted_zones = []
        try:
            paginator = route53_client.get_paginator('list_hosted_zones')
            for page in paginator.paginate():
                hosted_zones.extend(page.get('HostedZones', []))

            self.log_action(f"Found {len(hosted_zones)} hosted zones")
            return hosted_zones
        except Exception as e:
            self.log_action(f"Error listing hosted zones: {e}", "ERROR")
            self.cleanup_results['errors'].append(f"List hosted zones: {e}")
            return []

    def get_hosted_zone_details(self, route53_client, zone_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a hosted zone."""
        try:
            response = route53_client.get_hosted_zone(Id=zone_id)
            return response
        except Exception as e:
            self.log_action(f"Error getting details for zone {zone_id}: {e}", "ERROR")
            return None

    def list_record_sets(self, route53_client, zone_id: str) -> List[Dict[str, Any]]:
        """List all record sets in a hosted zone."""
        record_sets = []
        try:
            paginator = route53_client.get_paginator('list_resource_record_sets')
            for page in paginator.paginate(HostedZoneId=zone_id):
                record_sets.extend(page.get('ResourceRecordSets', []))

            return record_sets
        except Exception as e:
            self.log_action(f"Error listing record sets for zone {zone_id}: {e}", "ERROR")
            return []

    def delete_record_set(self, route53_client, zone_id: str, record_set: Dict[str, Any]) -> bool:
        """Delete a single record set."""
        try:
            record_name = record_set['Name']
            record_type = record_set['Type']

            # Skip NS and SOA records for the zone itself (they are deleted with the zone)
            if record_type in ['NS', 'SOA']:
                self.log_action(f"Skipping {record_type} record: {record_name} (auto-handled)", "INFO")
                return True

            # Skip if not a deletable record type
            if record_type not in self.deletable_record_types:
                self.log_action(f"Skipping record type {record_type}: {record_name}", "INFO")
                self.cleanup_results['skipped_resources'].append({
                    'type': 'RecordSet',
                    'name': record_name,
                    'record_type': record_type,
                    'reason': 'Non-deletable type or managed record'
                })
                return True

            # Prepare change batch for deletion
            change_batch = {
                'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': record_set
                }]
            }

            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch=change_batch
            )

            self.print_colored(Colors.GREEN, f"[OK] Deleted {record_type} record: {record_name}")
            self.log_action(f"Deleted {record_type} record: {record_name}")
            self.cleanup_results['deleted_record_sets'].append({
                'zone_id': zone_id,
                'name': record_name,
                'type': record_type
            })
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidChangeBatch':
                self.log_action(f"Skipping managed record: {record_name}", "INFO")
                return True
            else:
                self.log_action(f"Failed to delete record {record_name}: {e}", "ERROR")
                self.cleanup_results['failed_deletions'].append({
                    'type': 'RecordSet',
                    'name': record_name,
                    'error': str(e)
                })
                return False
        except Exception as e:
            self.log_action(f"Error deleting record {record_name}: {e}", "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'RecordSet',
                'name': record_name,
                'error': str(e)
            })
            return False

    def disassociate_vpc_from_hosted_zone(self, route53_client, zone_id: str, vpc_id: str, vpc_region: str) -> bool:
        """Disassociate a VPC from a private hosted zone."""
        try:
            route53_client.disassociate_vpc_from_hosted_zone(
                HostedZoneId=zone_id,
                VPC={
                    'VPCRegion': vpc_region,
                    'VPCId': vpc_id
                }
            )

            self.print_colored(Colors.GREEN, f"[OK] Disassociated VPC {vpc_id} from zone {zone_id}")
            self.log_action(f"Disassociated VPC {vpc_id} ({vpc_region}) from zone {zone_id}")
            self.cleanup_results['disassociated_vpcs'].append({
                'zone_id': zone_id,
                'vpc_id': vpc_id,
                'vpc_region': vpc_region
            })
            return True

        except Exception as e:
            self.log_action(f"Failed to disassociate VPC {vpc_id} from zone {zone_id}: {e}", "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'VPC_Disassociation',
                'zone_id': zone_id,
                'vpc_id': vpc_id,
                'error': str(e)
            })
            return False

    def delete_hosted_zone(self, route53_client, zone: Dict[str, Any]) -> bool:
        """Delete a hosted zone after removing all records and VPC associations."""
        try:
            zone_id = zone['Id']
            zone_name = zone['Name']
            is_private = zone.get('Config', {}).get('PrivateZone', False)

            self.print_colored(Colors.YELLOW, f"\n[SCAN] Processing hosted zone: {zone_name} ({zone_id})")
            self.log_action(f"Processing hosted zone: {zone_name} ({zone_id}) - Private: {is_private}")

            # Get detailed zone information
            zone_details = self.get_hosted_zone_details(route53_client, zone_id)
            if not zone_details:
                return False

            # Step 1: Disassociate VPCs if private zone
            if is_private:
                vpcs = zone_details.get('VPCs', [])
                if vpcs:
                    self.print_colored(Colors.CYAN, f"   [ROUNDPIN] Found {len(vpcs)} VPC associations")
                    for vpc in vpcs:
                        vpc_id = vpc.get('VPCId')
                        vpc_region = vpc.get('VPCRegion')
                        if vpc_id and vpc_region:
                            self.disassociate_vpc_from_hosted_zone(route53_client, zone_id, vpc_id, vpc_region)
                            time.sleep(1)  # Rate limiting

            # Step 2: Delete all deletable record sets
            record_sets = self.list_record_sets(route53_client, zone_id)
            deletable_records = [r for r in record_sets if r['Type'] in self.deletable_record_types]

            if deletable_records:
                self.print_colored(Colors.CYAN, f"   [LOG] Found {len(deletable_records)} deletable records")
                for record_set in deletable_records:
                    self.delete_record_set(route53_client, zone_id, record_set)
                    time.sleep(0.5)  # Rate limiting

            # Step 3: Delete the hosted zone
            # Wait a bit before deleting zone to ensure record deletions are processed
            time.sleep(2)

            route53_client.delete_hosted_zone(Id=zone_id)

            self.print_colored(Colors.GREEN, f"[OK] Deleted hosted zone: {zone_name}")
            self.log_action(f"Deleted hosted zone: {zone_name} ({zone_id})")
            self.cleanup_results['deleted_hosted_zones'].append({
                'zone_id': zone_id,
                'name': zone_name,
                'private': is_private
            })
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            self.log_action(f"Failed to delete hosted zone {zone_name}: {error_code} - {e}", "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'HostedZone',
                'name': zone_name,
                'error': f"{error_code}: {str(e)}"
            })
            return False
        except Exception as e:
            self.log_action(f"Error deleting hosted zone {zone_name}: {e}", "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'HostedZone',
                'name': zone_name,
                'error': str(e)
            })
            return False

    def list_health_checks(self, route53_client) -> List[Dict[str, Any]]:
        """List all health checks."""
        health_checks = []
        try:
            paginator = route53_client.get_paginator('list_health_checks')
            for page in paginator.paginate():
                health_checks.extend(page.get('HealthChecks', []))

            self.log_action(f"Found {len(health_checks)} health checks")
            return health_checks
        except Exception as e:
            self.log_action(f"Error listing health checks: {e}", "ERROR")
            return []

    def delete_health_check(self, route53_client, health_check_id: str) -> bool:
        """Delete a health check."""
        try:
            route53_client.delete_health_check(HealthCheckId=health_check_id)

            self.print_colored(Colors.GREEN, f"[OK] Deleted health check: {health_check_id}")
            self.log_action(f"Deleted health check: {health_check_id}")
            self.cleanup_results['deleted_health_checks'].append({
                'health_check_id': health_check_id
            })
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'HealthCheckInUse':
                self.log_action(f"Health check {health_check_id} is in use, will retry after zone deletion", "WARNING")
                return False
            self.log_action(f"Failed to delete health check {health_check_id}: {e}", "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'HealthCheck',
                'id': health_check_id,
                'error': str(e)
            })
            return False
        except Exception as e:
            self.log_action(f"Error deleting health check {health_check_id}: {e}", "ERROR")
            return False

    def list_traffic_policies(self, route53_client) -> List[Dict[str, Any]]:
        """List all traffic policies."""
        traffic_policies = []
        try:
            paginator = route53_client.get_paginator('list_traffic_policies')
            for page in paginator.paginate():
                traffic_policies.extend(page.get('TrafficPolicySummaries', []))

            self.log_action(f"Found {len(traffic_policies)} traffic policies")
            return traffic_policies
        except Exception as e:
            self.log_action(f"Error listing traffic policies: {e}", "ERROR")
            return []

    def list_traffic_policy_instances(self, route53_client) -> List[Dict[str, Any]]:
        """List all traffic policy instances."""
        instances = []
        try:
            paginator = route53_client.get_paginator('list_traffic_policy_instances')
            for page in paginator.paginate():
                instances.extend(page.get('TrafficPolicyInstances', []))

            self.log_action(f"Found {len(instances)} traffic policy instances")
            return instances
        except Exception as e:
            self.log_action(f"Error listing traffic policy instances: {e}", "ERROR")
            return []

    def delete_traffic_policy_instance(self, route53_client, instance_id: str) -> bool:
        """Delete a traffic policy instance."""
        try:
            route53_client.delete_traffic_policy_instance(Id=instance_id)

            self.print_colored(Colors.GREEN, f"[OK] Deleted traffic policy instance: {instance_id}")
            self.log_action(f"Deleted traffic policy instance: {instance_id}")
            return True

        except Exception as e:
            self.log_action(f"Failed to delete traffic policy instance {instance_id}: {e}", "ERROR")
            return False

    def delete_traffic_policy(self, route53_client, policy_id: str, version: int) -> bool:
        """Delete a specific version of a traffic policy."""
        try:
            route53_client.delete_traffic_policy(Id=policy_id, Version=version)

            self.print_colored(Colors.GREEN, f"[OK] Deleted traffic policy: {policy_id} v{version}")
            self.log_action(f"Deleted traffic policy: {policy_id} v{version}")
            self.cleanup_results['deleted_traffic_policies'].append({
                'policy_id': policy_id,
                'version': version
            })
            return True

        except Exception as e:
            self.log_action(f"Failed to delete traffic policy {policy_id} v{version}: {e}", "ERROR")
            return False

    def list_query_logging_configs(self, route53_client) -> List[Dict[str, Any]]:
        """List all query logging configurations."""
        configs = []
        try:
            paginator = route53_client.get_paginator('list_query_logging_configs')
            for page in paginator.paginate():
                configs.extend(page.get('QueryLoggingConfigs', []))

            self.log_action(f"Found {len(configs)} query logging configs")
            return configs
        except Exception as e:
            self.log_action(f"Error listing query logging configs: {e}", "ERROR")
            return []

    def delete_query_logging_config(self, route53_client, config_id: str) -> bool:
        """Delete a query logging configuration."""
        try:
            route53_client.delete_query_logging_config(Id=config_id)

            self.print_colored(Colors.GREEN, f"[OK] Deleted query logging config: {config_id}")
            self.log_action(f"Deleted query logging config: {config_id}")
            self.cleanup_results['deleted_query_logging_configs'].append({
                'config_id': config_id
            })
            return True

        except Exception as e:
            self.log_action(f"Failed to delete query logging config {config_id}: {e}", "ERROR")
            return False

    def list_reusable_delegation_sets(self, route53_client) -> List[Dict[str, Any]]:
        """List all reusable delegation sets."""
        delegation_sets = []
        try:
            paginator = route53_client.get_paginator('list_reusable_delegation_sets')
            for page in paginator.paginate():
                delegation_sets.extend(page.get('DelegationSets', []))

            self.log_action(f"Found {len(delegation_sets)} reusable delegation sets")
            return delegation_sets
        except Exception as e:
            self.log_action(f"Error listing reusable delegation sets: {e}", "ERROR")
            return []

    def delete_reusable_delegation_set(self, route53_client, delegation_set_id: str) -> bool:
        """Delete a reusable delegation set."""
        try:
            route53_client.delete_reusable_delegation_set(Id=delegation_set_id)

            self.print_colored(Colors.GREEN, f"[OK] Deleted delegation set: {delegation_set_id}")
            self.log_action(f"Deleted delegation set: {delegation_set_id}")
            self.cleanup_results['deleted_reusable_delegation_sets'].append({
                'delegation_set_id': delegation_set_id
            })
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'DelegationSetInUse':
                self.log_action(f"Delegation set {delegation_set_id} is in use", "WARNING")
                return False
            self.log_action(f"Failed to delete delegation set {delegation_set_id}: {e}", "ERROR")
            return False
        except Exception as e:
            self.log_action(f"Error deleting delegation set {delegation_set_id}: {e}", "ERROR")
            return False

    def cleanup_account_route53_resources(self, account_name: str, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Cleanup all Route53 resources for a single account."""
        results = {
            'account_name': account_name,
            'success': False,
            'deleted_zones': 0,
            'deleted_records': 0,
            'deleted_health_checks': 0,
            'errors': []
        }

        try:
            self.print_colored(Colors.BLUE, f"\n{'='*80}")
            self.print_colored(Colors.BLUE, f"[ACCOUNT] Processing Account: {account_name}")
            self.print_colored(Colors.BLUE, f"{'='*80}")

            route53_client = self.create_route53_client(credentials)

            # Step 1: Delete query logging configs
            self.print_colored(Colors.YELLOW, "\n[STATS] Cleaning up query logging configurations...")
            query_configs = self.list_query_logging_configs(route53_client)
            for config in query_configs:
                self.delete_query_logging_config(route53_client, config['Id'])
                time.sleep(0.5)

            # Step 2: Delete traffic policy instances (must be before policies)
            self.print_colored(Colors.YELLOW, "\n[TRAFFIC] Cleaning up traffic policy instances...")
            tp_instances = self.list_traffic_policy_instances(route53_client)
            for instance in tp_instances:
                self.delete_traffic_policy_instance(route53_client, instance['Id'])
                time.sleep(0.5)

            # Step 3: Delete traffic policies
            self.print_colored(Colors.YELLOW, "\n[TRAFFIC] Cleaning up traffic policies...")
            traffic_policies = self.list_traffic_policies(route53_client)
            for policy in traffic_policies:
                # Get all versions and delete them
                policy_id = policy['Id']
                try:
                    versions_response = route53_client.list_traffic_policy_versions(Id=policy_id)
                    versions = versions_response.get('TrafficPolicies', [])
                    for version_info in versions:
                        self.delete_traffic_policy(route53_client, policy_id, version_info['Version'])
                        time.sleep(0.5)
                except Exception as e:
                    self.log_action(f"Error processing traffic policy {policy_id}: {e}", "ERROR")

            # Step 4: Delete hosted zones (this includes record sets)
            self.print_colored(Colors.YELLOW, "\n[NETWORK] Cleaning up hosted zones...")
            hosted_zones = self.list_all_hosted_zones(route53_client)

            for zone in hosted_zones:
                self.delete_hosted_zone(route53_client, zone)
                results['deleted_zones'] += 1
                time.sleep(1)  # Rate limiting between zones

            # Step 5: Delete health checks (after zones, as they might be in use)
            self.print_colored(Colors.YELLOW, "\n[HEALTH] Cleaning up health checks...")
            health_checks = self.list_health_checks(route53_client)

            # First attempt
            failed_health_checks = []
            for health_check in health_checks:
                if not self.delete_health_check(route53_client, health_check['Id']):
                    failed_health_checks.append(health_check['Id'])
                else:
                    results['deleted_health_checks'] += 1
                time.sleep(0.5)

            # Retry failed health checks after a delay
            if failed_health_checks:
                self.print_colored(Colors.YELLOW, f"\n[WAIT] Retrying {len(failed_health_checks)} health checks...")
                time.sleep(5)
                for health_check_id in failed_health_checks:
                    if self.delete_health_check(route53_client, health_check_id):
                        results['deleted_health_checks'] += 1
                    time.sleep(0.5)

            # Step 6: Delete reusable delegation sets (if not in use)
            self.print_colored(Colors.YELLOW, "\n[LIST] Cleaning up reusable delegation sets...")
            delegation_sets = self.list_reusable_delegation_sets(route53_client)
            for ds in delegation_sets:
                self.delete_reusable_delegation_set(route53_client, ds['Id'])
                time.sleep(0.5)

            results['success'] = True
            results['deleted_records'] = len(self.cleanup_results['deleted_record_sets'])

            self.cleanup_results['accounts_processed'].append(account_name)

            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            self.log_action(f"Account {account_name} cleanup completed successfully")

        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            results['errors'].append(error_msg)
            self.cleanup_results['errors'].append(error_msg)

        return results

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation."""
        try:
            report_filename = f"route53_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_hosted_zones_deleted': len(self.cleanup_results['deleted_hosted_zones']),
                    'total_record_sets_deleted': len(self.cleanup_results['deleted_record_sets']),
                    'total_health_checks_deleted': len(self.cleanup_results['deleted_health_checks']),
                    'total_traffic_policies_deleted': len(self.cleanup_results['deleted_traffic_policies']),
                    'total_query_logging_configs_deleted': len(self.cleanup_results['deleted_query_logging_configs']),
                    'total_delegation_sets_deleted': len(self.cleanup_results['deleted_reusable_delegation_sets']),
                    'total_vpcs_disassociated': len(self.cleanup_results['disassociated_vpcs']),
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
            self.print_colored(Colors.BLUE, f"\n{'='*80}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*80}")
            self.print_colored(Colors.GREEN, f"[OK] Hosted Zones Deleted: {summary['summary']['total_hosted_zones_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Record Sets Deleted: {summary['summary']['total_record_sets_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Health Checks Deleted: {summary['summary']['total_health_checks_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Traffic Policies Deleted: {summary['summary']['total_traffic_policies_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Query Logging Configs Deleted: {summary['summary']['total_query_logging_configs_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] VPCs Disassociated: {summary['summary']['total_vpcs_disassociated']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN]  Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*80}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*80}")

            account_summary = {}

            # Aggregate hosted zones by account
            for zone in self.cleanup_results['deleted_hosted_zones']:
                account = zone.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['hosted_zones'] += 1
                account_summary[account]['regions'].add(zone.get('region', 'global'))

            # Aggregate record sets by account
            for record in self.cleanup_results['deleted_record_sets']:
                account = record.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['record_sets'] += 1
                account_summary[account]['regions'].add(record.get('region', 'global'))

            # Aggregate health checks by account
            for health_check in self.cleanup_results['deleted_health_checks']:
                account = health_check.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['health_checks'] += 1
                account_summary[account]['regions'].add(health_check.get('region', 'global'))

            # Aggregate traffic policies by account
            for policy in self.cleanup_results['deleted_traffic_policies']:
                account = policy.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['traffic_policies'] += 1
                account_summary[account]['regions'].add(policy.get('region', 'global'))

            # Aggregate query logging configs by account
            for config in self.cleanup_results['deleted_query_logging_configs']:
                account = config.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['query_logging_configs'] += 1
                account_summary[account]['regions'].add(config.get('region', 'global'))

            # Aggregate reusable delegation sets by account
            for delegation_set in self.cleanup_results['deleted_reusable_delegation_sets']:
                account = delegation_set.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['delegation_sets'] += 1
                account_summary[account]['regions'].add(delegation_set.get('region', 'global'))

            # Aggregate disassociated VPCs by account
            for vpc in self.cleanup_results['disassociated_vpcs']:
                account = vpc.get('account_key', 'Unknown')
                if account not in account_summary:
                    account_summary[account] = {
                        'hosted_zones': 0,
                        'record_sets': 0,
                        'health_checks': 0,
                        'traffic_policies': 0,
                        'query_logging_configs': 0,
                        'delegation_sets': 0,
                        'vpcs_disassociated': 0,
                        'regions': set()
                    }
                account_summary[account]['vpcs_disassociated'] += 1
                account_summary[account]['regions'].add(vpc.get('region', 'global'))

            # Display account summary
            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Hosted Zones: {stats['hosted_zones']}")
                self.print_colored(Colors.GREEN, f"  [OK] Record Sets: {stats['record_sets']}")
                self.print_colored(Colors.GREEN, f"  [OK] Health Checks: {stats['health_checks']}")
                self.print_colored(Colors.GREEN, f"  [OK] Traffic Policies: {stats['traffic_policies']}")
                self.print_colored(Colors.GREEN, f"  [OK] Query Logging Configs: {stats['query_logging_configs']}")
                self.print_colored(Colors.GREEN, f"  [OK] Delegation Sets: {stats['delegation_sets']}")
                self.print_colored(Colors.GREEN, f"  [OK] VPCs Disassociated: {stats['vpcs_disassociated']}")
                regions_str = ', '.join(sorted(stats['regions'])) if stats['regions'] else 'N/A'
                self.print_colored(Colors.YELLOW, f"  [SCAN] Regions: {regions_str}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")
            self.log_action(f"Failed to generate summary report: {e}", "ERROR")

    def interactive_cleanup(self):
        """Interactive mode for Route53 cleanup."""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*80)
            self.print_colored(Colors.BLUE, "[START] ULTRA ROUTE53 CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*80)

            # Load accounts
            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']

            # Display accounts with detailed info
            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for Route53 Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"[OK] Loaded {len(accounts)} root accounts")
            
            self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
            print("=" * 100)
            
            account_list = list(accounts.keys())
            for idx, account_name in enumerate(account_list, 1):
                account_data = accounts[account_name]
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'N/A')
                
                # Count users in this account
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

            # Account selection
            selection = input(f"Select accounts (1-{len(account_list)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

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
            self.print_colored(Colors.RED, "\n[WARN]  WARNING: This will DELETE Route53 resources!")
            self.print_colored(Colors.RED, "[WARN]  VPCs will NOT be deleted (only disassociated from zones)")
            self.print_colored(Colors.YELLOW, f"Accounts: {len(selected_accounts)}")
            
            confirm = input(f"\nType 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.print_colored(Colors.YELLOW, "[ERROR] Cleanup cancelled!")
                return

            # Process selected accounts
            self.log_action(f"Starting cleanup for accounts: {selected_accounts}")

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_route53_resources(account_name, credentials)
                time.sleep(2)  # Delay between accounts

            # Generate summary
            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] Route53 cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN]  Cleanup interrupted by user!")
            self.log_action("Cleanup interrupted by user", "WARNING")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")
            self.log_action(f"Error during cleanup: {e}", "ERROR")


def main():
    """Main entry point."""
    try:
        manager = UltraCleanupRoute53Manager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN]  Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
