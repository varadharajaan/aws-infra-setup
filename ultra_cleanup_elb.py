#!/usr/bin/env python3

import os
import json
import boto3
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from botocore.exceptions import ClientError, BotoCoreError
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupELBManager:
    """
    Tool to perform comprehensive cleanup of ELB resources across AWS accounts.

    Manages deletion of:
    - Classic Load Balancers (ELB)
    - Application Load Balancers (ALB)
    - Network Load Balancers (NLB)
    - Target Groups
    - Security Groups attached to Load Balancers
    - Custom VPCs and their dependencies

    Author: varadharajaan
    Created: 2025-01-20
    """

    def __init__(self, config_dir: str = None):
        """Initialize the ELB Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.elb_dir = os.path.join(self.config_dir, "aws", "elb")
        self.reports_dir = os.path.join(self.elb_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_load_balancers': [],
            'deleted_target_groups': [],
            'deleted_security_groups': [],
            'deleted_vpcs': [],
            'deleted_subnets': [],
            'deleted_internet_gateways': [],
            'deleted_route_tables': [],
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")


    def _get_user_regions(self) -> List[str]:
        """Get user regions from root accounts config."""
        try:
            config = self.cred_manager.load_root_accounts_config()
            if config:
                return config.get('user_settings', {}).get('user_regions', [
                    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
                ])
        except Exception as e:
            self.print_colored(Colors.YELLOW, f"⚠️  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.elb_dir, exist_ok=True)

            # Save log file in the aws/elb directory
            self.log_filename = f"{self.elb_dir}/ultra_elb_cleanup_log_{self.execution_timestamp}.log"

            # Create a file handler for detailed logging
            import logging

            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_elb_cleanup')
            self.operation_logger.setLevel(logging.INFO)

            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)

            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)

            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)

            # Log initial information
            self.operation_logger.info("=" * 100)
            self.operation_logger.info("🚨 ULTRA ELB CLEANUP SESSION STARTED 🚨")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config Dir: {self.config_dir}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)

        except Exception as e:
            self.print_colored(Colors.YELLOW, f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Simple logging operation"""
        if self.operation_logger:
            if level.upper() == 'INFO':
                self.operation_logger.info(message)
            elif level.upper() == 'WARNING':
                self.operation_logger.warning(message)
            elif level.upper() == 'ERROR':
                self.operation_logger.error(message)
            elif level.upper() == 'DEBUG':
                self.operation_logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")

    def create_aws_clients(self, access_key, secret_key, region):
        """Create AWS clients using account credentials"""
        try:
            # Create EC2 client
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            # Create Classic Load Balancer client
            elb_client = boto3.client(
                'elb',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            # Create Application/Network Load Balancer client (ELBv2)
            elbv2_client = boto3.client(
                'elbv2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            # Test the connections
            ec2_client.describe_regions(RegionNames=[region])
            elb_client.describe_load_balancers()
            elbv2_client.describe_load_balancers()

            return ec2_client, elb_client, elbv2_client

        except Exception as e:
            self.log_operation('ERROR', f"Failed to create AWS clients for {region}: {e}")
            raise

    def get_all_load_balancers_in_region(self, elb_client, elbv2_client, region, account_info):
        """Get all load balancers (Classic, Application, Network) in a specific region"""
        try:
            load_balancers = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"🔍 Scanning for load balancers in {region} ({account_name})")
            print(f"   🔍 Scanning for load balancers in {region} ({account_name})...")

            # Get Classic Load Balancers
            try:
                paginator = elb_client.get_paginator('describe_load_balancers')
                for page in paginator.paginate():
                    for lb in page['LoadBalancerDescriptions']:
                        lb_name = lb['LoadBalancerName']
                        lb_dns = lb['DNSName']
                        vpc_id = lb.get('VpcId', 'EC2-Classic')
                        scheme = lb['Scheme']

                        # Get security groups
                        security_groups = lb.get('SecurityGroups', [])

                        lb_info = {
                            'name': lb_name,
                            'type': 'classic',
                            'dns_name': lb_dns,
                            'vpc_id': vpc_id,
                            'scheme': scheme,
                            'security_groups': security_groups,
                            'region': region,
                            'account_info': account_info,
                            'subnets': lb.get('Subnets', []),
                            'availability_zones': [az['ZoneName'] for az in lb.get('AvailabilityZones', [])],
                            'created_time': lb.get('CreatedTime')
                        }

                        load_balancers.append(lb_info)

            except Exception as e:
                self.log_operation('WARNING', f"Error getting Classic Load Balancers: {e}")

            # Get Application and Network Load Balancers (ELBv2)
            try:
                paginator = elbv2_client.get_paginator('describe_load_balancers')
                for page in paginator.paginate():
                    for lb in page['LoadBalancers']:
                        lb_arn = lb['LoadBalancerArn']
                        lb_name = lb['LoadBalancerName']
                        lb_type = lb['Type']  # application or network
                        lb_dns = lb['DNSName']
                        vpc_id = lb.get('VpcId')
                        scheme = lb['Scheme']

                        # Get security groups (only for ALB, NLB doesn't have security groups)
                        security_groups = lb.get('SecurityGroups', [])

                        lb_info = {
                            'name': lb_name,
                            'arn': lb_arn,
                            'type': lb_type,
                            'dns_name': lb_dns,
                            'vpc_id': vpc_id,
                            'scheme': scheme,
                            'security_groups': security_groups,
                            'region': region,
                            'account_info': account_info,
                            'subnets': [subnet['SubnetId'] for subnet in lb.get('AvailabilityZones', [])],
                            'availability_zones': [az['ZoneName'] for az in lb.get('AvailabilityZones', [])],
                            'created_time': lb.get('CreatedTime')
                        }

                        load_balancers.append(lb_info)

            except Exception as e:
                self.log_operation('WARNING', f"Error getting ALB/NLB Load Balancers: {e}")

            self.log_operation('INFO', f"⚖️  Found {len(load_balancers)} load balancers in {region} ({account_name})")
            print(f"   ⚖️  Found {len(load_balancers)} load balancers in {region} ({account_name})")

            return load_balancers

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting load balancers in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting load balancers in {region}: {e}")
            return []

    def get_all_target_groups_in_region(self, elbv2_client, region, account_info):
        """Get all target groups in a specific region"""
        try:
            target_groups = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"🔍 Scanning for target groups in {region} ({account_name})")
            print(f"   🔍 Scanning for target groups in {region} ({account_name})...")

            paginator = elbv2_client.get_paginator('describe_target_groups')
            for page in paginator.paginate():
                for tg in page['TargetGroups']:
                    tg_arn = tg['TargetGroupArn']
                    tg_name = tg['TargetGroupName']
                    tg_type = tg['TargetType']
                    vpc_id = tg.get('VpcId')
                    protocol = tg['Protocol']
                    port = tg['Port']
                    health_check_path = tg.get('HealthCheckPath', 'N/A')

                    tg_info = {
                        'name': tg_name,
                        'arn': tg_arn,
                        'type': tg_type,
                        'protocol': protocol,
                        'port': port,
                        'health_check_path': health_check_path,
                        'vpc_id': vpc_id,
                        'region': region,
                        'account_info': account_info
                    }

                    target_groups.append(tg_info)

            self.log_operation('INFO', f"🎯 Found {len(target_groups)} target groups in {region} ({account_name})")
            print(f"   🎯 Found {len(target_groups)} target groups in {region} ({account_name})")

            return target_groups

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting target groups in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting target groups in {region}: {e}")
            return []

    def get_elb_security_groups_in_region(self, ec2_client, load_balancers, region, account_info):
        """Get all security groups attached to load balancers (excluding default)"""
        try:
            elb_security_groups = []
            processed_sg_ids = set()
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"🔍 Scanning for ELB security groups in {region} ({account_name})")
            print(f"   🔍 Scanning for ELB security groups in {region} ({account_name})...")

            for lb in load_balancers:
                for sg_id in lb.get('security_groups', []):
                    if sg_id in processed_sg_ids:
                        continue

                    try:
                        response = ec2_client.describe_security_groups(GroupIds=[sg_id])
                        sg = response['SecurityGroups'][0]
                        sg_name = sg['GroupName']

                        # Skip default security groups
                        if sg_name == 'default':
                            continue

                        sg_info = {
                            'group_id': sg_id,
                            'group_name': sg_name,
                            'description': sg['Description'],
                            'vpc_id': sg['VpcId'],
                            'region': region,
                            'account_info': account_info,
                            'is_attached': True,
                            'attached_load_balancers': [lb['name'] for lb in load_balancers if
                                                        sg_id in lb.get('security_groups', [])]
                        }

                        elb_security_groups.append(sg_info)
                        processed_sg_ids.add(sg_id)

                    except Exception as e:
                        self.log_operation('WARNING', f"Could not get details for security group {sg_id}: {e}")

            self.log_operation('INFO',
                               f"🛡️  Found {len(elb_security_groups)} ELB security groups in {region} ({account_name})")
            print(f"   🛡️  Found {len(elb_security_groups)} ELB security groups in {region} ({account_name})")

            return elb_security_groups

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting ELB security groups in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting ELB security groups in {region}: {e}")
            return []

    def get_custom_vpcs_in_region(self, ec2_client, region, account_info):
        """Get all custom VPCs (non-default) in a specific region"""
        try:
            custom_vpcs = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"🔍 Scanning for custom VPCs in {region} ({account_name})")
            print(f"   🔍 Scanning for custom VPCs in {region} ({account_name})...")

            paginator = ec2_client.get_paginator('describe_vpcs')
            for page in paginator.paginate():
                for vpc in page['Vpcs']:
                    vpc_id = vpc['VpcId']
                    is_default = vpc.get('IsDefault', False)
                    state = vpc['State']
                    cidr_block = vpc['CidrBlock']

                    # Skip default VPCs
                    if is_default:
                        continue

                    # Get VPC name from tags
                    vpc_name = 'Unknown'
                    for tag in vpc.get('Tags', []):
                        if tag['Key'] == 'Name':
                            vpc_name = tag['Value']
                            break

                    vpc_info = {
                        'vpc_id': vpc_id,
                        'name': vpc_name,
                        'cidr_block': cidr_block,
                        'state': state,
                        'is_default': is_default,
                        'region': region,
                        'account_info': account_info
                    }

                    custom_vpcs.append(vpc_info)

            self.log_operation('INFO', f"🏗️  Found {len(custom_vpcs)} custom VPCs in {region} ({account_name})")
            print(f"   🏗️  Found {len(custom_vpcs)} custom VPCs in {region} ({account_name})")

            return custom_vpcs

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting custom VPCs in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting custom VPCs in {region}: {e}")
            return []

    def delete_load_balancer(self, elb_client, elbv2_client, lb_info):
        """Delete a load balancer (Classic, Application, or Network)"""
        try:
            lb_name = lb_info['name']
            lb_type = lb_info['type']
            region = lb_info['region']
            account_name = lb_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"🗑️  Deleting {lb_type} load balancer {lb_name} in {region} ({account_name})")
            print(f"   🗑️  Deleting {lb_type} load balancer {lb_name}...")

            if lb_type == 'classic':
                # Delete Classic Load Balancer
                elb_client.delete_load_balancer(LoadBalancerName=lb_name)
            else:
                # Delete Application/Network Load Balancer
                elbv2_client.delete_load_balancer(LoadBalancerArn=lb_info['arn'])

            self.log_operation('INFO', f"✅ Successfully deleted {lb_type} load balancer {lb_name}")
            print(f"   ✅ Successfully deleted {lb_type} load balancer {lb_name}")

            self.cleanup_results['deleted_load_balancers'].append({
                'name': lb_name,
                'type': lb_type,
                'dns_name': lb_info['dns_name'],
                'vpc_id': lb_info['vpc_id'],
                'security_groups': lb_info['security_groups'],
                'scheme': lb_info['scheme'],
                'region': region,
                'account_info': lb_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            account_name = lb_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to delete load balancer {lb_name}: {e}")
            print(f"   ❌ Failed to delete load balancer {lb_name}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'load_balancer',
                'resource_id': lb_name,
                'region': region,
                'account_info': lb_info['account_info'],
                'error': str(e)
            })
            return False

    def delete_target_group(self, elbv2_client, tg_info):
        """Delete a target group"""
        try:
            tg_name = tg_info['name']
            tg_arn = tg_info['arn']
            region = tg_info['region']
            account_name = tg_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"🗑️  Deleting target group {tg_name} in {region} ({account_name})")
            print(f"   🗑️  Deleting target group {tg_name}...")

            elbv2_client.delete_target_group(TargetGroupArn=tg_arn)

            self.log_operation('INFO', f"✅ Successfully deleted target group {tg_name}")
            print(f"   ✅ Successfully deleted target group {tg_name}")

            self.cleanup_results['deleted_target_groups'].append({
                'name': tg_name,
                'arn': tg_arn,
                'type': tg_info['type'],
                'protocol': tg_info['protocol'],
                'port': tg_info['port'],
                'vpc_id': tg_info['vpc_id'],
                'region': region,
                'account_info': tg_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            account_name = tg_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to delete target group {tg_name}: {e}")
            print(f"   ❌ Failed to delete target group {tg_name}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'target_group',
                'resource_id': tg_name,
                'region': region,
                'account_info': tg_info['account_info'],
                'error': str(e)
            })
            return False

    def clear_security_group_rules(self, ec2_client, sg_id):
        """Clear all ingress and egress rules from a security group, handling cross-references"""
        try:
            self.log_operation('INFO', f"🧹 Clearing rules for security group {sg_id}")

            # Get security group details
            try:
                response = ec2_client.describe_security_groups(GroupIds=[sg_id])
                sg_info = response['SecurityGroups'][0]
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidGroupId.NotFound':
                    self.log_operation('INFO', f"Security group {sg_id} does not exist, skipping rule clearing")
                    return True
                else:
                    raise

            sg_name = sg_info['GroupName']
            ingress_rules = sg_info.get('IpPermissions', [])
            egress_rules = sg_info.get('IpPermissionsEgress', [])

            rules_cleared = 0
            rules_failed = 0

            # Clear ingress rules (including cross-references)
            if ingress_rules:
                self.log_operation('INFO', f"Removing {len(ingress_rules)} ingress rules from {sg_id} ({sg_name})")

                for rule_index, rule in enumerate(ingress_rules):
                    try:
                        ec2_client.revoke_security_group_ingress(
                            GroupId=sg_id,
                            IpPermissions=[rule]
                        )
                        rules_cleared += 1
                        self.log_operation('INFO', f"  ✅ Successfully removed ingress rule {rule_index + 1}")

                    except ClientError as e:
                        error_code = e.response['Error']['Code']
                        if error_code == 'InvalidGroupId.NotFound':
                            self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                            return True
                        elif error_code == 'InvalidPermission.NotFound':
                            self.log_operation('INFO', f"  Ingress rule {rule_index + 1} already removed")
                            rules_cleared += 1
                        else:
                            self.log_operation('ERROR', f"  ❌ Failed to remove ingress rule {rule_index + 1}: {e}")
                            rules_failed += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"  ❌ Unexpected error removing ingress rule {rule_index + 1}: {e}")
                        rules_failed += 1

            # Clear egress rules (but keep the default allow-all rule)
            if egress_rules:
                non_default_egress = []
                for rule in egress_rules:
                    # Default rule: protocol=-1, port=all, destination=0.0.0.0/0
                    is_default = (
                            rule.get('IpProtocol') == '-1' and
                            len(rule.get('IpRanges', [])) == 1 and
                            rule.get('IpRanges', [{}])[0].get('CidrIp') == '0.0.0.0/0' and
                            not rule.get('UserIdGroupPairs') and
                            not rule.get('PrefixListIds')
                    )

                    if not is_default:
                        non_default_egress.append(rule)

                if non_default_egress:
                    self.log_operation('INFO',
                                       f"Removing {len(non_default_egress)} non-default egress rules from {sg_id} ({sg_name})")

                    for rule_index, rule in enumerate(non_default_egress):
                        try:
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg_id,
                                IpPermissions=[rule]
                            )
                            rules_cleared += 1
                            self.log_operation('INFO', f"  ✅ Successfully removed egress rule {rule_index + 1}")

                        except ClientError as e:
                            error_code = e.response['Error']['Code']
                            if error_code == 'InvalidGroupId.NotFound':
                                self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                                return True
                            elif error_code == 'InvalidPermission.NotFound':
                                self.log_operation('INFO', f"  Egress rule {rule_index + 1} already removed")
                                rules_cleared += 1
                            else:
                                self.log_operation('ERROR', f"  ❌ Failed to remove egress rule {rule_index + 1}: {e}")
                                rules_failed += 1
                        except Exception as e:
                            self.log_operation('ERROR',
                                               f"  ❌ Unexpected error removing egress rule {rule_index + 1}: {e}")
                            rules_failed += 1

            # Wait briefly for rule changes to propagate
            if rules_cleared > 0:
                self.log_operation('INFO', f"Waiting 10 seconds for rule changes to propagate...")
                time.sleep(10)

            return rules_failed == 0

        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error clearing rules for security group {sg_id}: {e}")
            return False

    def delete_security_group(self, ec2_client, sg_info):
        """Delete a security group after clearing its rules"""
        try:
            sg_id = sg_info['group_id']
            sg_name = sg_info['group_name']
            region = sg_info['region']
            account_name = sg_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"🗑️  Deleting security group {sg_id} ({sg_name}) in {region} ({account_name})")
            print(f"   🗑️  Deleting security group {sg_id} ({sg_name})...")

            # Step 1: Clear all security group rules first
            self.log_operation('INFO', f"Step 1: Clearing security group rules for {sg_id}")
            rules_cleared = self.clear_security_group_rules(ec2_client, sg_id)

            if not rules_cleared:
                self.log_operation('WARNING',
                                   f"Some rules could not be cleared from {sg_id}, proceeding with deletion attempt")

            # Step 2: Delete the security group
            self.log_operation('INFO', f"Step 2: Attempting to delete security group {sg_id}")
            print(f"   🗑️ Attempting to delete security group {sg_id}...")
            ec2_client.delete_security_group(GroupId=sg_id)

            self.log_operation('INFO', f"✅ Successfully deleted security group {sg_id} ({sg_name})")
            print(f"   ✅ Successfully deleted security group {sg_id}")

            self.cleanup_results['deleted_security_groups'].append({
                'group_id': sg_id,
                'group_name': sg_name,
                'description': sg_info['description'],
                'vpc_id': sg_info['vpc_id'],
                'was_attached': sg_info['is_attached'],
                'attached_load_balancers': sg_info.get('attached_load_balancers', []),
                'rules_cleared': rules_cleared,
                'region': region,
                'account_info': sg_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            account_name = sg_info['account_info'].get('account_key', 'Unknown')
            if error_code == 'InvalidGroupId.NotFound':
                self.log_operation('INFO', f"Security group {sg_id} does not exist")
                return True
            elif error_code == 'DependencyViolation':
                self.log_operation('WARNING',
                                   f"Cannot delete security group {sg_id}: dependency violation (still in use)")
                print(f"   ⚠️ Cannot delete security group {sg_id}: still in use")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'security_group',
                    'resource_id': sg_id,
                    'region': region,
                    'account_info': sg_info['account_info'],
                    'error': 'Dependency violation - still in use after rule clearing'
                })
                return False
            else:
                self.log_operation('ERROR', f"Failed to delete security group {sg_id}: {e}")
                print(f"   ❌ Failed to delete security group {sg_id}: {e}")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'security_group',
                    'resource_id': sg_id,
                    'region': region,
                    'account_info': sg_info['account_info'],
                    'error': str(e)
                })
                return False
        except Exception as e:
            account_name = sg_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Unexpected error deleting security group {sg_id}: {e}")
            print(f"   ❌ Unexpected error deleting security group {sg_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'security_group',
                'resource_id': sg_id,
                'region': region,
                'account_info': sg_info['account_info'],
                'error': str(e)
            })
            return False

    def delete_vpc_dependencies(self, ec2_client, vpc_id, vpc_name, region, account_info):
        """Delete VPC dependencies (subnets, IGWs, route tables, etc.)"""
        try:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('INFO', f"🧹 Cleaning VPC dependencies for {vpc_id} ({vpc_name})")

            dependencies_deleted = {
                'subnets': 0,
                'internet_gateways': 0,
                'nat_gateways': 0,
                'route_tables': 0,
                'vpc_endpoints': 0
            }

            # Delete subnets
            try:
                subnets = ec2_client.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                for subnet in subnets['Subnets']:
                    subnet_id = subnet['SubnetId']
                    try:
                        ec2_client.delete_subnet(SubnetId=subnet_id)
                        dependencies_deleted['subnets'] += 1
                        self.log_operation('INFO', f"   Deleted subnet {subnet_id}")

                        self.cleanup_results['deleted_subnets'].append({
                            'subnet_id': subnet_id,
                            'vpc_id': vpc_id,
                            'cidr_block': subnet.get('CidrBlock'),
                            'availability_zone': subnet.get('AvailabilityZone'),
                            'region': region,
                            'account_info': account_info,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })

                    except Exception as e:
                        self.log_operation('WARNING', f"   Failed to delete subnet {subnet_id}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error listing subnets for VPC {vpc_id}: {e}")

            # Delete NAT Gateways
            try:
                nat_gateways = ec2_client.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                for nat_gw in nat_gateways['NatGateways']:
                    if nat_gw['State'] not in ['deleted', 'deleting']:
                        nat_gw_id = nat_gw['NatGatewayId']
                        try:
                            ec2_client.delete_nat_gateway(NatGatewayId=nat_gw_id)
                            dependencies_deleted['nat_gateways'] += 1
                            self.log_operation('INFO', f"   Deleted NAT gateway {nat_gw_id}")
                        except Exception as e:
                            self.log_operation('WARNING', f"   Failed to delete NAT gateway {nat_gw_id}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error listing NAT gateways for VPC {vpc_id}: {e}")

            # Delete internet gateways
            try:
                igws = ec2_client.describe_internet_gateways(
                    Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}])
                for igw in igws['InternetGateways']:
                    igw_id = igw['InternetGatewayId']
                    try:
                        ec2_client.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                        ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
                        dependencies_deleted['internet_gateways'] += 1
                        self.log_operation('INFO', f"   Deleted internet gateway {igw_id}")

                        self.cleanup_results['deleted_internet_gateways'].append({
                            'internet_gateway_id': igw_id,
                            'vpc_id': vpc_id,
                            'region': region,
                            'account_info': account_info,
                            'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })

                    except Exception as e:
                        self.log_operation('WARNING', f"   Failed to delete internet gateway {igw_id}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error listing internet gateways for VPC {vpc_id}: {e}")

            # Delete route tables (except main)
            try:
                route_tables = ec2_client.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                for rt in route_tables['RouteTables']:
                    rt_id = rt['RouteTableId']
                    # Skip main route table
                    is_main = any(assoc.get('Main', False) for assoc in rt.get('Associations', []))
                    if not is_main:
                        try:
                            ec2_client.delete_route_table(RouteTableId=rt_id)
                            dependencies_deleted['route_tables'] += 1
                            self.log_operation('INFO', f"   Deleted route table {rt_id}")

                            self.cleanup_results['deleted_route_tables'].append({
                                'route_table_id': rt_id,
                                'vpc_id': vpc_id,
                                'region': region,
                                'account_info': account_info,
                                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })

                        except Exception as e:
                            self.log_operation('WARNING', f"   Failed to delete route table {rt_id}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error listing route tables for VPC {vpc_id}: {e}")

            # Delete VPC endpoints
            try:
                vpc_endpoints = ec2_client.describe_vpc_endpoints(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                for endpoint in vpc_endpoints['VpcEndpoints']:
                    if endpoint['State'] not in ['deleted', 'deleting']:
                        endpoint_id = endpoint['VpcEndpointId']
                        try:
                            ec2_client.delete_vpc_endpoint(VpcEndpointId=endpoint_id)
                            dependencies_deleted['vpc_endpoints'] += 1
                            self.log_operation('INFO', f"   Deleted VPC endpoint {endpoint_id}")
                        except Exception as e:
                            self.log_operation('WARNING', f"   Failed to delete VPC endpoint {endpoint_id}: {e}")
            except Exception as e:
                self.log_operation('WARNING', f"Error listing VPC endpoints for VPC {vpc_id}: {e}")

            # Wait for dependencies to be deleted
            total_deps = sum(dependencies_deleted.values())
            if total_deps > 0:
                self.log_operation('INFO', f"   Deleted {total_deps} dependencies, waiting 30 seconds for cleanup...")
                time.sleep(30)

            return dependencies_deleted

        except Exception as e:
            self.log_operation('ERROR', f"Error cleaning VPC dependencies for {vpc_id}: {e}")
            return {}

    def delete_custom_vpc(self, ec2_client, vpc_info):
        """Delete a custom VPC and its dependencies"""
        try:
            vpc_id = vpc_info['vpc_id']
            vpc_name = vpc_info['name']
            region = vpc_info['region']
            account_name = vpc_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"🗑️  Deleting custom VPC {vpc_id} ({vpc_name}) in {region} ({account_name})")
            print(f"   🗑️  Deleting custom VPC {vpc_id} ({vpc_name})...")

            # Delete VPC dependencies first
            dependencies_deleted = self.delete_vpc_dependencies(ec2_client, vpc_id, vpc_name, region,
                                                                vpc_info['account_info'])

            # Finally delete the VPC
            ec2_client.delete_vpc(VpcId=vpc_id)

            self.log_operation('INFO', f"✅ Successfully deleted custom VPC {vpc_id} ({vpc_name})")
            print(f"   ✅ Successfully deleted custom VPC {vpc_id}")

            self.cleanup_results['deleted_vpcs'].append({
                'vpc_id': vpc_id,
                'name': vpc_name,
                'cidr_block': vpc_info['cidr_block'],
                'dependencies_deleted': dependencies_deleted,
                'region': region,
                'account_info': vpc_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            account_name = vpc_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to delete custom VPC {vpc_id}: {e}")
            print(f"   ❌ Failed to delete custom VPC {vpc_id}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'vpc',
                'resource_id': vpc_id,
                'region': region,
                'account_info': vpc_info['account_info'],
                'error': str(e)
            })
            return False

    def get_vpc_resources_for_load_balancers(self, ec2_client, load_balancers, region, account_info):
        """Get VPC resources (subnets, IGWs, route tables) that are specifically used by load balancers"""
        try:
            lb_vpc_resources = {
                'vpcs': {},
                'subnets': [],
                'security_groups': [],
                'route_tables': [],
                'internet_gateways': []
            }

            account_name = account_info.get('account_key', 'Unknown')

            # Get unique VPC IDs from load balancers
            lb_vpc_ids = set()
            lb_subnet_ids = set()
            lb_sg_ids = set()

            for lb in load_balancers:
                vpc_id = lb.get('vpc_id')
                if vpc_id and vpc_id != 'EC2-Classic':
                    lb_vpc_ids.add(vpc_id)

                # Get subnets used by this load balancer
                for subnet_id in lb.get('subnets', []):
                    if subnet_id:
                        lb_subnet_ids.add(subnet_id)

                # Get security groups used by this load balancer
                for sg_id in lb.get('security_groups', []):
                    if sg_id:
                        lb_sg_ids.add(sg_id)

            if not lb_vpc_ids:
                self.log_operation('INFO', f"No custom VPCs used by load balancers in {region} ({account_name})")
                return lb_vpc_resources

            self.log_operation('INFO', f"🔍 Analyzing VPC resources for {len(lb_vpc_ids)} VPCs used by load balancers")

            # Check each VPC used by load balancers
            for vpc_id in lb_vpc_ids:
                try:
                    # Get VPC details
                    vpc_response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
                    vpc = vpc_response['Vpcs'][0]

                    # Skip default VPCs
                    if vpc.get('IsDefault', False):
                        self.log_operation('INFO', f"Skipping default VPC {vpc_id}")
                        continue

                    # Get VPC name
                    vpc_name = 'Unknown'
                    for tag in vpc.get('Tags', []):
                        if tag['Key'] == 'Name':
                            vpc_name = tag['Value']
                            break

                    # Check if VPC has OTHER resources (not just our load balancer resources)
                    vpc_has_other_resources = self.vpc_has_other_resources(ec2_client, vpc_id, lb_subnet_ids, lb_sg_ids)

                    vpc_info = {
                        'vpc_id': vpc_id,
                        'name': vpc_name,
                        'cidr_block': vpc['CidrBlock'],
                        'state': vpc['State'],
                        'is_default': vpc.get('IsDefault', False),
                        'has_other_resources': vpc_has_other_resources,
                        'region': region,
                        'account_info': account_info
                    }

                    lb_vpc_resources['vpcs'][vpc_id] = vpc_info

                    # Only collect resources if VPC has NO other resources
                    if not vpc_has_other_resources:
                        self.log_operation('INFO',
                                           f"VPC {vpc_id} appears to be dedicated to load balancers, collecting its resources")

                        # Get subnets in this VPC that are used by load balancers
                        subnets_response = ec2_client.describe_subnets(
                            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                        )

                        for subnet in subnets_response['Subnets']:
                            subnet_id = subnet['SubnetId']
                            # Only include subnets that are actually used by our load balancers
                            if subnet_id in lb_subnet_ids:
                                lb_vpc_resources['subnets'].append({
                                    'subnet_id': subnet_id,
                                    'vpc_id': vpc_id,
                                    'cidr_block': subnet.get('CidrBlock'),
                                    'availability_zone': subnet.get('AvailabilityZone'),
                                    'is_default': subnet.get('DefaultForAz', False),
                                    'region': region,
                                    'account_info': account_info
                                })

                        # Get internet gateways attached to this VPC
                        igw_response = ec2_client.describe_internet_gateways(
                            Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
                        )

                        for igw in igw_response['InternetGateways']:
                            lb_vpc_resources['internet_gateways'].append({
                                'internet_gateway_id': igw['InternetGatewayId'],
                                'vpc_id': vpc_id,
                                'region': region,
                                'account_info': account_info
                            })

                        # Get custom route tables in this VPC (excluding main route table)
                        rt_response = ec2_client.describe_route_tables(
                            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                        )

                        for rt in rt_response['RouteTables']:
                            # Skip main route table
                            is_main = any(assoc.get('Main', False) for assoc in rt.get('Associations', []))
                            if not is_main:
                                lb_vpc_resources['route_tables'].append({
                                    'route_table_id': rt['RouteTableId'],
                                    'vpc_id': vpc_id,
                                    'region': region,
                                    'account_info': account_info
                                })
                    else:
                        self.log_operation('INFO',
                                           f"VPC {vpc_id} has other resources, will NOT delete VPC or its dependencies")

                except Exception as e:
                    self.log_operation('WARNING', f"Error analyzing VPC {vpc_id}: {e}")

            # Get security groups used by load balancers
            for sg_id in lb_sg_ids:
                try:
                    sg_response = ec2_client.describe_security_groups(GroupIds=[sg_id])
                    sg = sg_response['SecurityGroups'][0]

                    # Skip default security groups
                    if sg['GroupName'] == 'default':
                        continue

                    lb_vpc_resources['security_groups'].append({
                        'group_id': sg_id,
                        'group_name': sg['GroupName'],
                        'description': sg['Description'],
                        'vpc_id': sg['VpcId'],
                        'region': region,
                        'account_info': account_info,
                        'is_attached': True,
                        'attached_load_balancers': [lb['name'] for lb in load_balancers if
                                                    sg_id in lb.get('security_groups', [])]
                    })

                except Exception as e:
                    self.log_operation('WARNING', f"Error getting security group {sg_id}: {e}")

            return lb_vpc_resources

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR',
                               f"Error getting VPC resources for load balancers in {region} ({account_name}): {e}")
            return {}

    def vpc_has_other_resources(self, ec2_client, vpc_id, lb_subnet_ids, lb_sg_ids):
        """Check if VPC has resources other than those used by our load balancers"""
        try:
            # Check for EC2 instances
            instances_response = ec2_client.describe_instances(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )

            for reservation in instances_response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] not in ['terminated', 'shutting-down']:
                        self.log_operation('INFO', f"VPC {vpc_id} has active EC2 instances")
                        return True

            # Check for RDS instances
            try:
                import boto3
                rds_client = boto3.client('rds', region_name=ec2_client.meta.region_name)
                db_instances = rds_client.describe_db_instances()

                for db in db_instances['DBInstances']:
                    if db.get('DBSubnetGroup', {}).get('VpcId') == vpc_id:
                        self.log_operation('INFO', f"VPC {vpc_id} has RDS instances")
                        return True
            except Exception:
                pass  # RDS check is optional

            # Check for Lambda functions (ENIs)
            try:
                enis_response = ec2_client.describe_network_interfaces(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

                for eni in enis_response['NetworkInterfaces']:
                    # Skip ENIs that belong to load balancers
                    if eni.get('InterfaceType') == 'load_balancer':
                        continue
                    if eni.get('RequesterId') == 'amazon-elb':
                        continue

                    self.log_operation('INFO', f"VPC {vpc_id} has other network interfaces")
                    return True
            except Exception:
                pass

            # Check for NAT Gateways
            try:
                nat_response = ec2_client.describe_nat_gateways(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

                for nat in nat_response['NatGateways']:
                    if nat['State'] not in ['deleted', 'deleting']:
                        self.log_operation('INFO', f"VPC {vpc_id} has NAT gateways")
                        return True
            except Exception:
                pass

            # Check for VPC Endpoints
            try:
                endpoints_response = ec2_client.describe_vpc_endpoints(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

                if endpoints_response['VpcEndpoints']:
                    self.log_operation('INFO', f"VPC {vpc_id} has VPC endpoints")
                    return True
            except Exception:
                pass

            return False

        except Exception as e:
            self.log_operation('WARNING', f"Error checking if VPC {vpc_id} has other resources: {e}")
            return True  # Err on the side of caution

    def cleanup_account_region(self, account_info, region):
        """Clean up only ELB-related resources in a specific account and region"""
        try:
            access_key = account_info['access_key']
            secret_key = account_info['secret_key']
            account_id = account_info['account_id']
            account_key = account_info['account_key']

            self.log_operation('INFO', f"🧹 Starting ELB cleanup for {account_key} ({account_id}) in {region}")
            print(f"\n🧹 Starting ELB cleanup for {account_key} ({account_id}) in {region}")

            # Create AWS clients
            ec2_client, elb_client, elbv2_client = self.create_aws_clients(access_key, secret_key, region)

            # Initialize variables
            load_balancers = []
            target_groups = []
            lb_vpc_resources = {}

            try:
                # Get all load balancers
                load_balancers = self.get_all_load_balancers_in_region(elb_client, elbv2_client, region, account_info)

                # Get all target groups
                target_groups = self.get_all_target_groups_in_region(elbv2_client, region, account_info)

                # Get only VPC resources used by load balancers (not all custom VPCs)
                lb_vpc_resources = self.get_vpc_resources_for_load_balancers(ec2_client, load_balancers, region,
                                                                             account_info)

            except Exception as discovery_error:
                self.log_operation('ERROR',
                                   f"Error during resource discovery in {account_key} ({region}): {discovery_error}")
                print(f"   ❌ Error during resource discovery: {discovery_error}")
                # Continue with whatever we managed to discover

            # Calculate resource counts
            elb_security_groups = lb_vpc_resources.get('security_groups', [])
            lb_vpcs = lb_vpc_resources.get('vpcs', {})
            lb_subnets = lb_vpc_resources.get('subnets', [])
            vpcs_to_delete = [vpc for vpc in lb_vpcs.values() if not vpc.get('has_other_resources', True)]

            region_summary = {
                'account_key': account_key,
                'account_id': account_id,
                'region': region,
                'load_balancers_found': len(load_balancers),
                'target_groups_found': len(target_groups),
                'elb_security_groups_found': len(elb_security_groups),
                'lb_subnets_found': len(lb_subnets),
                'lb_vpcs_found': len(vpcs_to_delete)
            }

            self.cleanup_results['regions_processed'].append(region_summary)

            self.log_operation('INFO', f"📊 {account_key} ({region}) ELB resources summary:")
            self.log_operation('INFO', f"   ⚖️  Load Balancers: {len(load_balancers)}")
            self.log_operation('INFO', f"   🎯 Target Groups: {len(target_groups)}")
            self.log_operation('INFO', f"   🛡️  ELB Security Groups: {len(elb_security_groups)}")
            self.log_operation('INFO', f"   🏗️  ELB Subnets: {len(lb_subnets)}")
            self.log_operation('INFO', f"   🌐 ELB-only VPCs: {len(vpcs_to_delete)}")

            print(
                f"   📊 ELB resources found: {len(load_balancers)} LBs, {len(target_groups)} TGs, {len(elb_security_groups)} SGs, {len(vpcs_to_delete)} VPCs")

            if not load_balancers and not target_groups and not elb_security_groups and not vpcs_to_delete:
                self.log_operation('INFO', f"No ELB resources found in {account_key} ({region})")
                print(f"   ✅ No ELB resources to clean up in {region}")
                return True

            # Step 1: Delete Load Balancers sequentially
            if load_balancers:
                self.log_operation('INFO',
                                   f"🗑️  Deleting {len(load_balancers)} load balancers in {account_key} ({region}) sequentially")
                print(f"\n   🗑️  Deleting {len(load_balancers)} load balancers sequentially...")

                deleted_count = 0
                failed_count = 0

                for i, lb in enumerate(load_balancers, 1):
                    lb_name = lb['name']
                    print(f"   [{i}/{len(load_balancers)}] Processing load balancer {lb_name}...")

                    try:
                        success = self.delete_load_balancer(elb_client, elbv2_client, lb)
                        if success:
                            deleted_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log_operation('ERROR', f"Error deleting load balancer {lb_name}: {e}")
                        print(f"   ❌ Error deleting load balancer {lb_name}: {e}")

                print(f"   ✅ Deleted {deleted_count} load balancers, ❌ Failed: {failed_count}")

                # Wait for load balancers to be deleted
                if deleted_count > 0:
                    self.log_operation('INFO',
                                       f"⏳ Waiting 45 seconds for {deleted_count} load balancers to be deleted...")
                    print(f"   ⏳ Waiting 45 seconds for load balancers to be deleted...")
                    time.sleep(45)

            # Step 2: Delete Target Groups sequentially
            if target_groups:
                self.log_operation('INFO',
                                   f"🗑️  Deleting {len(target_groups)} target groups in {account_key} ({region}) sequentially")
                print(f"\n   🗑️  Deleting {len(target_groups)} target groups sequentially...")

                deleted_count = 0
                failed_count = 0

                for i, tg in enumerate(target_groups, 1):
                    tg_name = tg['name']
                    print(f"   [{i}/{len(target_groups)}] Processing target group {tg_name}...")

                    try:
                        success = self.delete_target_group(elbv2_client, tg)
                        if success:
                            deleted_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log_operation('ERROR', f"Error deleting target group {tg_name}: {e}")
                        print(f"   ❌ Error deleting target group {tg_name}: {e}")

                print(f"   ✅ Deleted {deleted_count} target groups, ❌ Failed: {failed_count}")

            # Step 3: Delete only security groups that were attached to load balancers
            if elb_security_groups:
                self.log_operation('INFO',
                                   f"🗑️  Deleting {len(elb_security_groups)} ELB security groups in {account_key} ({region})")
                print(f"\n   🗑️  Deleting {len(elb_security_groups)} ELB security groups...")

                max_retries = 3
                retry_delay = 20

                remaining_sgs = elb_security_groups.copy()

                for retry in range(max_retries):
                    self.log_operation('INFO', f"🔄 Security group deletion attempt {retry + 1}/{max_retries}")
                    print(f"   🔄 Security group deletion attempt {retry + 1}/{max_retries}")

                    # Track progress in this iteration
                    sgs_deleted_this_round = 0
                    still_remaining = []

                    for i, sg in enumerate(remaining_sgs, 1):
                        sg_id = sg['group_id']
                        print(f"   [{i}/{len(remaining_sgs)}] Trying to delete ELB security group {sg_id}...")

                        try:
                            success = self.delete_security_group(ec2_client, sg)
                            if success:
                                sgs_deleted_this_round += 1
                                self.log_operation('INFO',
                                                   f"✅ Deleted ELB security group {sg_id} in attempt {retry + 1}")
                            else:
                                still_remaining.append(sg)
                                self.log_operation('WARNING',
                                                   f"⏳ ELB security group {sg_id} still has dependencies, will retry")
                        except Exception as e:
                            self.log_operation('ERROR', f"Error deleting ELB security group {sg_id}: {e}")
                            print(f"   ❌ Error deleting ELB security group {sg_id}: {e}")
                            still_remaining.append(sg)

                    self.log_operation('INFO',
                                       f"Attempt {retry + 1} results: {sgs_deleted_this_round} deleted, {len(still_remaining)} remaining")
                    print(
                        f"   ✅ Deleted {sgs_deleted_this_round} ELB security groups in attempt {retry + 1}, {len(still_remaining)} remaining")

                    # Update remaining list
                    remaining_sgs = still_remaining

                    if not remaining_sgs:
                        self.log_operation('INFO', f"✅ All ELB security groups deleted in {account_key} ({region})")
                        print(f"   ✅ All ELB security groups deleted successfully!")
                        break

                    if retry < max_retries - 1 and remaining_sgs:
                        self.log_operation('INFO', f"⏳ Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                        print(f"   ⏳ Waiting {retry_delay}s before next retry...")
                        time.sleep(retry_delay)

                if remaining_sgs:
                    self.log_operation('WARNING',
                                       f"⚠️  {len(remaining_sgs)} ELB security groups could not be deleted after {max_retries} retries")
                    print(
                        f"   ⚠️  {len(remaining_sgs)} ELB security groups could not be deleted after {max_retries} retries")

            # Step 4: Delete ELB-related subnets (only if they're not default and not used by other resources)
            lb_subnets_to_delete = [subnet for subnet in lb_subnets if
                                    not subnet.get('is_default', True) and not subnet.get('has_other_resources', True)]

            if lb_subnets_to_delete:
                self.log_operation('INFO',
                                   f"🗑️  Deleting {len(lb_subnets_to_delete)} ELB-only subnets in {account_key} ({region})")
                print(f"\n   🗑️  Deleting {len(lb_subnets_to_delete)} ELB-only subnets...")

                deleted_count = 0
                failed_count = 0

                for i, subnet in enumerate(lb_subnets_to_delete, 1):
                    subnet_id = subnet['subnet_id']
                    print(f"   [{i}/{len(lb_subnets_to_delete)}] Deleting ELB subnet {subnet_id}...")

                    try:
                        success = self.delete_subnet(ec2_client, subnet)
                        if success:
                            deleted_count += 1
                            self.log_operation('INFO', f"✅ Deleted ELB subnet {subnet_id}")
                        else:
                            failed_count += 1
                            self.log_operation('WARNING', f"⚠️  Failed to delete ELB subnet {subnet_id}")
                    except Exception as e:
                        failed_count += 1
                        self.log_operation('ERROR', f"Error deleting ELB subnet {subnet_id}: {e}")
                        print(f"   ❌ Error deleting ELB subnet {subnet_id}: {e}")

                print(f"   ✅ Deleted {deleted_count} ELB subnets, ❌ Failed: {failed_count}")

            # Step 5: Delete only VPC resources that belong to load balancer-only VPCs
            if vpcs_to_delete:
                self.log_operation('INFO',
                                   f"🗑️  Deleting {len(vpcs_to_delete)} load balancer-only VPCs in {account_key} ({region})")
                print(f"\n   🗑️  Deleting {len(vpcs_to_delete)} load balancer-only VPCs...")

                max_retries = 4
                retry_delay = 45

                remaining_vpcs = vpcs_to_delete.copy()

                for retry in range(max_retries):
                    self.log_operation('INFO', f"🔄 ELB VPC deletion attempt {retry + 1}/{max_retries}")
                    print(f"   🔄 ELB VPC deletion attempt {retry + 1}/{max_retries}")

                    vpcs_deleted_this_round = 0
                    still_remaining = []

                    for i, vpc in enumerate(remaining_vpcs, 1):
                        vpc_id = vpc['vpc_id']
                        print(f"   [{i}/{len(remaining_vpcs)}] Trying to delete ELB VPC {vpc_id}...")

                        try:
                            # First clean up remaining VPC components for this specific VPC
                            self.cleanup_vpc_components_for_elb(ec2_client, vpc)

                            # Then try to delete the VPC itself
                            success = self.delete_vpc_for_elb(ec2_client, vpc)
                            if success:
                                vpcs_deleted_this_round += 1
                                self.log_operation('INFO', f"✅ Deleted ELB VPC {vpc_id}")
                            else:
                                still_remaining.append(vpc)
                                self.log_operation('WARNING', f"⏳ ELB VPC {vpc_id} still has dependencies, will retry")
                        except Exception as e:
                            self.log_operation('ERROR', f"Error deleting ELB VPC {vpc_id}: {e}")
                            print(f"   ❌ Error deleting ELB VPC {vpc_id}: {e}")
                            still_remaining.append(vpc)

                    self.log_operation('INFO',
                                       f"Attempt {retry + 1} results: {vpcs_deleted_this_round} deleted, {len(still_remaining)} remaining")
                    print(
                        f"   ✅ Deleted {vpcs_deleted_this_round} ELB VPCs in attempt {retry + 1}, {len(still_remaining)} remaining")

                    remaining_vpcs = still_remaining

                    if not remaining_vpcs:
                        self.log_operation('INFO', f"✅ All load balancer-only VPCs deleted in {account_key} ({region})")
                        print(f"   ✅ All load balancer-only VPCs deleted successfully!")
                        break

                    if retry < max_retries - 1 and remaining_vpcs:
                        self.log_operation('INFO', f"⏳ Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                        print(f"   ⏳ Waiting {retry_delay}s before next retry...")
                        time.sleep(retry_delay)

                if remaining_vpcs:
                    self.log_operation('WARNING',
                                       f"⚠️  {len(remaining_vpcs)} load balancer-only VPCs could not be deleted after {max_retries} retries")
                    print(
                        f"   ⚠️  {len(remaining_vpcs)} load balancer-only VPCs could not be deleted after {max_retries} retries")

            self.log_operation('INFO', f"✅ ELB cleanup completed for {account_key} ({region})")
            print(f"\n   ✅ ELB cleanup completed for {account_key} ({region})")
            return True

        except Exception as e:
            account_key = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error cleaning up ELB resources in {account_key} ({region}): {e}")
            print(f"   ❌ Error cleaning up ELB resources in {account_key} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_info': account_info,
                'region': region,
                'error': str(alle)
            })
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_elb_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_lbs_deleted = len(self.cleanup_results['deleted_load_balancers'])
            total_tgs_deleted = len(self.cleanup_results['deleted_target_groups'])
            total_sgs_deleted = len(self.cleanup_results['deleted_security_groups'])
            total_vpcs_deleted = len(self.cleanup_results['deleted_vpcs'])
            total_subnets_deleted = len(self.cleanup_results['deleted_subnets'])
            total_igws_deleted = len(self.cleanup_results['deleted_internet_gateways'])
            total_route_tables_deleted = len(self.cleanup_results['deleted_route_tables'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])

            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}

            for lb in self.cleanup_results['deleted_load_balancers']:
                account = lb['account_info'].get('account_key', 'Unknown')
                region = lb['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {
                        'load_balancers': 0, 'target_groups': 0, 'security_groups': 0, 'vpcs': 0
                    }
                deletions_by_account[account]['load_balancers'] += 1

                if region not in deletions_by_region:
                    deletions_by_region[region] = {
                        'load_balancers': 0, 'target_groups': 0, 'security_groups': 0, 'vpcs': 0
                    }
                deletions_by_region[region]['load_balancers'] += 1

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_ELB_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(
                        set(rp['account_key'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(
                        set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_load_balancers_deleted": total_lbs_deleted,
                    "total_target_groups_deleted": total_tgs_deleted,
                    "total_security_groups_deleted": total_sgs_deleted,
                    "total_vpcs_deleted": total_vpcs_deleted,
                    "total_subnets_deleted": total_subnets_deleted,
                    "total_internet_gateways_deleted": total_igws_deleted,
                    "total_route_tables_deleted": total_route_tables_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_load_balancers": self.cleanup_results['deleted_load_balancers'],
                    "deleted_target_groups": self.cleanup_results['deleted_target_groups'],
                    "deleted_security_groups": self.cleanup_results['deleted_security_groups'],
                    "deleted_vpcs": self.cleanup_results['deleted_vpcs'],
                    "deleted_subnets": self.cleanup_results['deleted_subnets'],
                    "deleted_internet_gateways": self.cleanup_results['deleted_internet_gateways'],
                                        "deleted_route_tables": self.cleanup_results['deleted_route_tables'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }

            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation('INFO', f"✅ Ultra ELB cleanup report saved to: {report_filename}")
            return report_filename

        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save ultra ELB cleanup report: {e}")
            return None

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n🌍 Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "💡 Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(f"Select regions (1-{len(self.user_regions)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all" or not choice:
                    self.print_colored(Colors.GREEN, f"✅ Selected all {len(self.user_regions)} regions")
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(choice, len(self.user_regions))
                if not selected_indices:
                    self.print_colored(Colors.RED, "❌ Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"✅ Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
                return selected_regions

            except Exception as e:
                self.print_colored(Colors.RED, f"❌ Error processing selection: {str(e)}")

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA ELB CLEANUP SESSION 🚨")

            self.print_colored(Colors.YELLOW, "🚨" * 30)
            self.print_colored(Colors.RED, "💥 ULTRA ELB CLEANUP - SEQUENTIAL 💥")
            self.print_colored(Colors.YELLOW, "🚨" * 30)
            self.print_colored(Colors.WHITE, f"📅 Execution Date/Time: {self.current_time} UTC")
            self.print_colored(Colors.WHITE, f"👤 Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"📋 Log File: {self.log_filename}")

            # # STEP 1: Select credential source (root accounts or IAM users)
            # self.print_colored(Colors.YELLOW, "\n🔑 Select Credential Source:")
            # self.print_colored(Colors.YELLOW, "=" * 80)
            # self.print_colored(Colors.CYAN, "   1. Root Account Credentials")
            # self.print_colored(Colors.CYAN, "   2. IAM User Credentials")
            # self.print_colored(Colors.YELLOW, "=" * 80)
            #
            # credential_source = None
            # while credential_source is None:
            #     choice = input("Select credential source (1 for Root, 2 for IAM) or 'q' to quit: ").strip()
            #
            #     if choice.lower() == 'q':
            #         self.print_colored(Colors.RED, "❌ Cleanup cancelled")
            #         return
            #
            #     if choice == '1':
            #         credential_source = 'root'
            #     elif choice == '2':
            #         credential_source = 'iam'
            #     else:
            #         self.print_colored(Colors.RED, "❌ Invalid choice. Please enter 1 or 2")
            #
            # # STEP 2: Get credentials based on source
            # selected_accounts = []
            #
            # if credential_source == 'root':
            #     # Use root account credentials
            #     root_accounts = self.cred_manager.select_root_accounts_interactive(allow_multiple=True)
            #     if not root_accounts:
            #         self.print_colored(Colors.RED, "❌ No root accounts selected, exiting...")
            #         return
            #     selected_accounts = root_accounts
            #
            # else:  # IAM credentials
            #     # Select IAM credentials file
            #     iam_file = self.cred_manager.select_iam_credentials_file_interactive()
            #     if not iam_file:
            #         self.print_colored(Colors.RED, "❌ No IAM credentials file selected, exiting...")
            #         return
            #
            #     # Select IAM users
            #     iam_users = self.cred_manager.select_iam_users_interactive(iam_file)
            #     if not iam_users:
            #         self.print_colored(Colors.RED, "❌ No IAM users selected, exiting...")
            #         return
            #     selected_accounts = iam_users
            #
            # # STEP 3: Select regions
            # selected_regions = self.select_regions_interactive()
            # if not selected_regions:
            #     self.print_colored(Colors.RED, "❌ No regions selected, exiting...")
            #     return
            #
            # # STEP 4: Calculate total operations and confirm
            # total_operations = len(selected_accounts) * len(selected_regions)
            #
            # self.print_colored(Colors.YELLOW, f"\n🎯 ELB CLEANUP CONFIGURATION")
            # self.print_colored(Colors.YELLOW, "=" * 80)
            # self.print_colored(Colors.WHITE, f"🔑 Credential source: {credential_source.upper()}")
            # self.print_colored(Colors.WHITE, f"🏦 Selected accounts: {len(selected_accounts)}")
            # self.print_colored(Colors.WHITE, f"🌍 Regions per account: {len(selected_regions)}")
            # self.print_colored(Colors.WHITE, f"📋 Total operations: {total_operations}")
            # self.print_colored(Colors.YELLOW, "=" * 80)

# unblock above code if u want to use select root or iam credentials functionality enabled

            # STEP 1: Select root accounts
            self.print_colored(Colors.YELLOW, "\n🔑 Select Root AWS Accounts for ELB Cleanup:")

            root_accounts = self.cred_manager.select_root_accounts_interactive(allow_multiple=True)
            if not root_accounts:
                self.print_colored(Colors.RED, "❌ No root accounts selected, exiting...")
                return
            selected_accounts = root_accounts

            # STEP 2: Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.RED, "❌ No regions selected, exiting...")
                return

            # STEP 3: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(selected_regions)

            self.print_colored(Colors.YELLOW, f"\n🎯 ELB CLEANUP CONFIGURATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"🔑 Credential source: ROOT ACCOUNTS")
            self.print_colored(Colors.WHITE, f"🏦 Selected accounts: {len(selected_accounts)}")
            self.print_colored(Colors.WHITE, f"🌍 Regions per account: {len(selected_regions)}")
            self.print_colored(Colors.WHITE, f"📋 Total operations: {total_operations}")
            self.print_colored(Colors.YELLOW, "=" * 80)

            # Show what will be cleaned up
            self.print_colored(Colors.RED, f"\n⚠️  WARNING: This will delete ALL of the following ELB resources:")
            self.print_colored(Colors.WHITE, f"    • Classic Load Balancers (ELB)")
            self.print_colored(Colors.WHITE, f"    • Application Load Balancers (ALB)")
            self.print_colored(Colors.WHITE, f"    • Network Load Balancers (NLB)")
            self.print_colored(Colors.WHITE, f"    • Target Groups")
            self.print_colored(Colors.WHITE, f"    • Security Groups attached to Load Balancers")
            self.print_colored(Colors.WHITE, f"    • Custom VPCs and their dependencies (subnets, IGWs, route tables)")
            self.print_colored(Colors.GREEN, f"    ✅ Default VPCs, subnets, and security groups will be IGNORED")
            self.print_colored(Colors.WHITE, f"    across {len(selected_accounts)} accounts in {len(selected_regions)} regions ({total_operations} operations)")
            self.print_colored(Colors.RED, f"    This action CANNOT be undone!")

            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with ELB cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")

            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra ELB cleanup cancelled by user")
                self.print_colored(Colors.RED, "❌ Cleanup cancelled")
                return

            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")

            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra ELB cleanup cancelled at final confirmation")
                self.print_colored(Colors.RED, "❌ Cleanup cancelled")
                return

            # STEP 5: Start the cleanup sequentially
            self.print_colored(Colors.RED, f"\n💥 STARTING ELB CLEANUP...")
            self.log_operation('INFO', f"🚨 ELB CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(selected_regions)} regions")

            start_time = time.time()

            successful_tasks = 0
            failed_tasks = 0

            # Create tasks list
            tasks = []
            for account_info in selected_accounts:
                for region in selected_regions:
                    tasks.append((account_info, region))

            # Process each task sequentially
            for i, (account_info, region) in enumerate(tasks, 1):
                account_key = account_info.get('account_key', 'Unknown')
                self.print_colored(Colors.CYAN, f"\n[{i}/{len(tasks)}] Processing {account_key} in {region}...")

                try:
                    success = self.cleanup_account_region(account_info, region)
                    if success:
                        successful_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    self.log_operation('ERROR', f"Task failed for {account_key} ({region}): {e}")
                    self.print_colored(Colors.RED, f"❌ Task failed for {account_key} ({region}): {e}")

            end_time = time.time()
            total_time = int(end_time - start_time)

            # STEP 6: Display final results
            self.print_colored(Colors.YELLOW, f"\n💥" + "="*25 + " ELB CLEANUP COMPLETE " + "="*25)
            self.print_colored(Colors.WHITE, f"⏱️  Total execution time: {total_time} seconds")
            self.print_colored(Colors.GREEN, f"✅ Successful operations: {successful_tasks}")
            self.print_colored(Colors.RED, f"❌ Failed operations: {failed_tasks}")
            self.print_colored(Colors.WHITE, f"⚖️  Load balancers deleted: {len(self.cleanup_results['deleted_load_balancers'])}")
            self.print_colored(Colors.WHITE, f"🎯 Target groups deleted: {len(self.cleanup_results['deleted_target_groups'])}")
            self.print_colored(Colors.WHITE, f"🛡️  Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            self.print_colored(Colors.WHITE, f"🏗️  VPCs deleted: {len(self.cleanup_results['deleted_vpcs'])}")
            self.print_colored(Colors.WHITE, f"🌐 Subnets deleted: {len(self.cleanup_results['deleted_subnets'])}")
            self.print_colored(Colors.WHITE, f"🌍 Internet gateways deleted: {len(self.cleanup_results['deleted_internet_gateways'])}")
            self.print_colored(Colors.WHITE, f"🛣️  Route tables deleted: {len(self.cleanup_results['deleted_route_tables'])}")
            self.print_colored(Colors.WHITE, f"⏭️  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            self.print_colored(Colors.RED, f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}")

            self.log_operation('INFO', f"ELB CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Load balancers deleted: {len(self.cleanup_results['deleted_load_balancers'])}")
            self.log_operation('INFO', f"Target groups deleted: {len(self.cleanup_results['deleted_target_groups'])}")
            self.log_operation('INFO', f"Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            self.log_operation('INFO', f"VPCs deleted: {len(self.cleanup_results['deleted_vpcs'])}")

            # STEP 7: Show account summary
            if (self.cleanup_results['deleted_load_balancers'] or
                self.cleanup_results['deleted_target_groups'] or
                self.cleanup_results['deleted_security_groups'] or
                self.cleanup_results['deleted_vpcs']):

                self.print_colored(Colors.YELLOW, f"\n📊 Deletion Summary by Account:")

                # Group by account
                account_summary = {}

                for lb in self.cleanup_results['deleted_load_balancers']:
                    account = lb['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'target_groups': 0, 'security_groups': 0,
                            'vpcs': 0, 'regions': set()
                        }
                    account_summary[account]['load_balancers'] += 1
                    account_summary[account]['regions'].add(lb['region'])

                for tg in self.cleanup_results['deleted_target_groups']:
                    account = tg['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'target_groups': 0, 'security_groups': 0,
                            'vpcs': 0, 'regions': set()
                        }
                    account_summary[account]['target_groups'] += 1
                    account_summary[account]['regions'].add(tg['region'])

                for sg in self.cleanup_results['deleted_security_groups']:
                    account = sg['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'target_groups': 0, 'security_groups': 0,
                            'vpcs': 0, 'regions': set()
                        }
                    account_summary[account]['security_groups'] += 1
                    account_summary[account]['regions'].add(sg['region'])

                for vpc in self.cleanup_results['deleted_vpcs']:
                    account = vpc['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'target_groups': 0, 'security_groups': 0,
                            'vpcs': 0, 'regions': set()
                        }
                    account_summary[account]['vpcs'] += 1
                    account_summary[account]['regions'].add(vpc['region'])

                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.PURPLE, f"   🏦 {account}:")
                    self.print_colored(Colors.WHITE, f"      ⚖️  Load Balancers: {summary['load_balancers']}")
                    self.print_colored(Colors.WHITE, f"      🎯 Target Groups: {summary['target_groups']}")
                    self.print_colored(Colors.WHITE, f"      🛡️  Security Groups: {summary['security_groups']}")
                    self.print_colored(Colors.WHITE, f"      🏗️  VPCs: {summary['vpcs']}")
                    self.print_colored(Colors.WHITE, f"      🌍 Regions: {regions_list}")

            # STEP 8: Show failures if any
            if self.cleanup_results['failed_deletions']:
                self.print_colored(Colors.RED, f"\n❌ Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    account_key = failure['account_info'].get('account_key', 'Unknown')
                    self.print_colored(Colors.WHITE, f"   • {failure['resource_type']} {failure['resource_id']} in {account_key} ({failure['region']})")
                    self.print_colored(Colors.WHITE, f"     Error: {failure['error']}")

                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    self.print_colored(Colors.WHITE, f"   ... and {remaining} more failures (see detailed report)")

            # Save comprehensive report
            self.print_colored(Colors.CYAN, f"\n📄 Saving ELB cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"✅ ELB cleanup report saved to: {report_file}")

            self.print_colored(Colors.GREEN, f"✅ Session log saved to: {self.log_filename}")

            self.print_colored(Colors.RED, f"\n💥 ELB CLEANUP COMPLETE! 💥")
            self.print_colored(Colors.YELLOW, "🚨" * 30)

        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in ELB cleanup execution: {str(e)}")
            self.print_colored(Colors.RED, f"\n❌ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraCleanupELBManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ ELB cleanup interrupted by user")
        exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()