#!/usr/bin/env python3

import os
import json
import boto3
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from botocore.exceptions import ClientError, BotoCoreError
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupEC2Manager:
    """
    Tool to perform comprehensive cleanup of EC2 resources across AWS accounts.

    Manages deletion of:
    - EC2 Instances
    - Security Groups
    - EBS Volumes
    - Key Pairs
    - Elastic IPs

    Author: varadharajaan
    Created: 2025-07-05
    """

    def __init__(self, config_dir: str = None):
        """Initialize the EC2 Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.ec2_dir = os.path.join(self.config_dir, "aws", "ec2")
        self.reports_dir = os.path.join(self.ec2_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_instances': [],
            'deleted_security_groups': [],
            'deleted_eips': [],
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
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.ec2_dir, exist_ok=True)

            # Save log file in the aws/ec2 directory
            self.log_filename = f"{self.ec2_dir}/ultra_ec2_cleanup_log_{self.execution_timestamp}.log"

            # Create a file handler for detailed logging
            import logging

            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_ec2_cleanup')
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
            self.operation_logger.info("[ALERT] ULTRA EC2 CLEANUP SESSION STARTED [ALERT]")
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

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using account credentials"""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            # Test the connection
            ec2_client.describe_regions(RegionNames=[region])
            return ec2_client

        except Exception as e:
            self.log_operation('ERROR', f"Failed to create EC2 client for {region}: {e}")
            raise

    def get_all_instances_in_region(self, ec2_client, region, account_info):
        """Get all EC2 instances in a specific region"""
        try:
            instances = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"[SCAN] Scanning for instances in {region} ({account_name})")
            print(f"   [SCAN] Scanning for instances in {region} ({account_name})...")

            paginator = ec2_client.get_paginator('describe_instances')

            for page in paginator.paginate():
                for reservation in page['Reservations']:
                    for instance in reservation['Instances']:
                        instance_id = instance['InstanceId']
                        state = instance['State']['Name']
                        instance_type = instance['InstanceType']

                        # Get instance name from tags
                        instance_name = 'Unknown'
                        for tag in instance.get('Tags', []):
                            if tag['Key'] == 'Name':
                                instance_name = tag['Value']
                                break

                        # Get security groups
                        security_groups = []
                        for sg in instance.get('SecurityGroups', []):
                            security_groups.append({
                                'GroupId': sg['GroupId'],
                                'GroupName': sg['GroupName']
                            })

                        instance_info = {
                            'instance_id': instance_id,
                            'instance_name': instance_name,
                            'instance_type': instance_type,
                            'state': state,
                            'region': region,
                            'account_info': account_info,
                            'security_groups': security_groups,
                            'launch_time': instance.get('LaunchTime'),
                            'vpc_id': instance.get('VpcId'),
                            'subnet_id': instance.get('SubnetId'),
                            'public_ip': instance.get('PublicIpAddress'),
                            'private_ip': instance.get('PrivateIpAddress')
                        }

                        instances.append(instance_info)

            self.log_operation('INFO', f"[PACKAGE] Found {len(instances)} instances in {region} ({account_name})")
            print(f"   [PACKAGE] Found {len(instances)} instances in {region} ({account_name})")

            return instances

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting instances in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting instances in {region}: {e}")
            return []

    def get_all_security_groups_in_region(self, ec2_client, region, account_info):
        """Get all security groups in a specific region"""
        try:
            security_groups = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"[SCAN] Scanning for security groups in {region} ({account_name})")
            print(f"   [SCAN] Scanning for security groups in {region} ({account_name})...")

            paginator = ec2_client.get_paginator('describe_security_groups')

            for page in paginator.paginate():
                for sg in page['SecurityGroups']:
                    sg_id = sg['GroupId']
                    sg_name = sg['GroupName']
                    vpc_id = sg['VpcId']
                    description = sg['Description']

                    # Skip default security groups
                    if sg_name == 'default':
                        self.log_operation('DEBUG', f"Skipping default security group {sg_id} ({sg_name})")
                        continue

                    # Enhanced EKS security group protection
                    if self.is_eks_related_security_group(sg, ec2_client, region):
                        self.log_operation('WARNING',
                                           f"[PROTECTED] PROTECTED: Skipping EKS-related security group {sg_id} ({sg_name})")
                        print(f"   [PROTECTED] PROTECTED: Skipping EKS security group {sg_name}")
                        continue

                    sg_info = {
                        'group_id': sg_id,
                        'group_name': sg_name,
                        'description': description,
                        'vpc_id': vpc_id,
                        'region': region,
                        'account_info': account_info,
                        'is_attached': False,
                        'attached_instances': []
                    }

                    security_groups.append(sg_info)

            self.log_operation('INFO',
                               f"[PROTECTED]  Found {len(security_groups)} security groups in {region} ({account_name}) (after EKS filtering)")
            print(
                f"   [PROTECTED]  Found {len(security_groups)} security groups in {region} ({account_name}) (after EKS filtering)")

            return security_groups

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting security groups in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting security groups in {region}: {e}")
            return []

    def is_eks_related_security_group(self, sg, ec2_client, region):
        """Comprehensive check if security group is related to EKS"""
        sg_id = sg['GroupId']
        sg_name = sg['GroupName']
        description = sg['Description'].lower()

        try:
            # 1. Check security group name patterns
            eks_name_patterns = [
                'eks-cluster-sg',
                'eks-nodegroup-',
                'eks-cluster-',
                'eksctl-',
                'EKS',
                'eks',
                'nodegroup'
            ]

            for pattern in eks_name_patterns:
                if pattern.lower() in sg_name.lower():
                    self.log_operation('INFO', f"[TARGET] EKS pattern match in name: {sg_name} contains '{pattern}'")
                    return True

            # 2. Check security group description
            eks_description_patterns = [
                'eks',
                'nodegroup',
                'cluster',
                'kubernetes',
                'k8s',
                'worker node',
                'managed node'
            ]

            for pattern in eks_description_patterns:
                if pattern in description:
                    self.log_operation('INFO',
                                       f"[TARGET] EKS pattern match in description: {description} contains '{pattern}'")
                    return True

            # 3. Check if security group is used by Launch Templates
            if self.is_security_group_used_by_launch_template(ec2_client, sg_id):
                self.log_operation('WARNING',
                                   f"[START] Security group {sg_id} is used by Launch Template - likely EKS nodegroup")
                return True

            # 4. Check if security group is used by Auto Scaling Groups
            if self.is_security_group_used_by_asg(ec2_client, sg_id, region):
                self.log_operation('WARNING',
                                   f"📈 Security group {sg_id} is used by Auto Scaling Group - likely EKS nodegroup")
                return True

            # 5. Check tags for EKS indicators
            for tag in sg.get('Tags', []):
                tag_key = tag['Key'].lower()
                tag_value = tag['Value'].lower()

                eks_tag_patterns = [
                    'kubernetes.io/cluster/',
                    'eks:cluster-name',
                    'eks:nodegroup-name',
                    'eksctl.io/',
                    'alpha.eksctl.io/',
                    'kubernetes.io/created-for/pvc/namespace'
                ]

                for pattern in eks_tag_patterns:
                    if pattern in tag_key or pattern in tag_value:
                        self.log_operation('INFO', f"[TAG] EKS tag found: {tag_key}={tag_value}")
                        return True

            return False

        except Exception as e:
            self.log_operation('ERROR', f"Error checking if security group {sg_id} is EKS-related: {e}")
            # If we can't determine, err on the side of caution
            return True

    def is_security_group_used_by_launch_template(self, ec2_client, sg_id):
        """Check if security group is used by any Launch Template"""
        try:
            paginator = ec2_client.get_paginator('describe_launch_templates')

            for page in paginator.paginate():
                for lt in page['LaunchTemplates']:
                    lt_id = lt['LaunchTemplateId']

                    # Get launch template versions
                    try:
                        versions_response = ec2_client.describe_launch_template_versions(
                            LaunchTemplateId=lt_id
                        )

                        for version in versions_response['LaunchTemplateVersions']:
                            launch_template_data = version.get('LaunchTemplateData', {})
                            security_group_ids = launch_template_data.get('SecurityGroupIds', [])
                            security_groups = launch_template_data.get('SecurityGroups', [])

                            # Check security group IDs
                            if sg_id in security_group_ids:
                                self.log_operation('WARNING',
                                                   f"[START] Security group {sg_id} found in Launch Template {lt_id}")
                                return True

                            # Check security group names
                            for sg_name in security_groups:
                                if sg_id == sg_name:  # Sometimes names are used instead of IDs
                                    self.log_operation('WARNING',
                                                       f"[START] Security group {sg_id} found in Launch Template {lt_id}")
                                    return True

                    except Exception as version_error:
                        self.log_operation('DEBUG',
                                           f"Could not check launch template {lt_id} versions: {version_error}")
                        continue

            return False

        except Exception as e:
            self.log_operation('ERROR', f"Error checking launch templates for security group {sg_id}: {e}")
            return True  # Err on the side of caution

    def is_security_group_used_by_asg(self, ec2_client, sg_id, region):
        """Check if security group is used by any Auto Scaling Group"""
        try:
            # Create Auto Scaling client
            asg_client = boto3.client(
                'autoscaling',
                aws_access_key_id=ec2_client._request_signer._credentials.access_key,
                aws_secret_access_key=ec2_client._request_signer._credentials.secret_key,
                region_name=region
            )

            paginator = asg_client.get_paginator('describe_auto_scaling_groups')

            for page in paginator.paginate():
                for asg in page['AutoScalingGroups']:
                    asg_name = asg['AutoScalingGroupName']

                    # Check if ASG uses Launch Template
                    if 'LaunchTemplate' in asg:
                        lt_id = asg['LaunchTemplate']['LaunchTemplateId']
                        if self.is_security_group_used_by_launch_template(ec2_client, sg_id):
                            self.log_operation('WARNING',
                                               f"📈 Security group {sg_id} used by ASG {asg_name} via Launch Template {lt_id}")
                            return True

                    # Check instances in ASG for security groups
                    for instance in asg.get('Instances', []):
                        instance_id = instance['InstanceId']
                        try:
                            instance_response = ec2_client.describe_instances(InstanceIds=[instance_id])
                            for reservation in instance_response['Reservations']:
                                for inst in reservation['Instances']:
                                    for sg in inst.get('SecurityGroups', []):
                                        if sg['GroupId'] == sg_id:
                                            self.log_operation('WARNING',
                                                               f"📈 Security group {sg_id} used by ASG {asg_name} instance {instance_id}")
                                            return True
                        except Exception as inst_error:
                            self.log_operation('DEBUG', f"Could not check instance {instance_id}: {inst_error}")
                            continue

            return False

        except Exception as e:
            self.log_operation('ERROR', f"Error checking Auto Scaling Groups for security group {sg_id}: {e}")
            return True  # Err on the side of caution

    def correlate_instances_and_security_groups(self, instances, security_groups):
        """Correlate instances with their security groups"""
        try:
            # Create a mapping of security group IDs to instances
            sg_to_instances = {}

            for instance in instances:
                for sg in instance['security_groups']:
                    sg_id = sg['GroupId']
                    if sg_id not in sg_to_instances:
                        sg_to_instances[sg_id] = []
                    sg_to_instances[sg_id].append(instance['instance_id'])

            # Update security groups with attachment info
            for sg in security_groups:
                sg_id = sg['group_id']
                if sg_id in sg_to_instances:
                    sg['is_attached'] = True
                    sg['attached_instances'] = sg_to_instances[sg_id]

            attached_sgs = [sg for sg in security_groups if sg['is_attached']]
            unattached_sgs = [sg for sg in security_groups if not sg['is_attached']]

            self.log_operation('INFO', f"[LINK] Security group correlation complete:")
            self.log_operation('INFO', f"   [ATTACHED] Attached to instances: {len(attached_sgs)}")
            self.log_operation('INFO', f"   [UNLOCKED] Unattached: {len(unattached_sgs)}")

            return attached_sgs, unattached_sgs

        except Exception as e:
            self.log_operation('ERROR', f"Error correlating instances and security groups: {e}")
            return [], []

    def terminate_instance(self, ec2_client, instance_info):
        """Terminate an EC2 instance"""
        try:
            instance_id = instance_info['instance_id']
            region = instance_info['region']
            account_name = instance_info['account_info'].get('account_key', 'Unknown')
            current_state = instance_info['state']

            if current_state in ['terminated', 'terminating']:
                self.log_operation('INFO', f"Instance {instance_id} already {current_state}")
                self.cleanup_results['skipped_resources'].append({
                    'resource_type': 'instance',
                    'resource_id': instance_id,
                    'region': region,
                    'account_info': instance_info['account_info'],
                    'reason': f'Already {current_state}'
                })
                return True

            self.log_operation('INFO', f"[DELETE]  Terminating instance {instance_id} in {region} ({account_name})")
            print(f"   [DELETE]  Terminating instance {instance_id}...")

            response = ec2_client.terminate_instances(InstanceIds=[instance_id])

            current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
            previous_state = response['TerminatingInstances'][0]['PreviousState']['Name']

            self.log_operation('INFO', f"[OK] Instance {instance_id} termination initiated: {previous_state} → {current_state}")
            print(f"   [OK] Instance {instance_id} termination initiated: {previous_state} → {current_state}")

            self.cleanup_results['deleted_instances'].append({
                'instance_id': instance_id,
                'instance_name': instance_info['instance_name'],
                'instance_type': instance_info['instance_type'],
                'previous_state': previous_state,
                'current_state': current_state,
                'region': region,
                'account_info': instance_info['account_info'],
                'public_ip': instance_info.get('public_ip'),
                'private_ip': instance_info.get('private_ip'),
                'terminated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            account_name = instance_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to terminate instance {instance_id}: {e}")
            print(f"   [ERROR] Failed to terminate instance {instance_id}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'instance',
                'resource_id': instance_id,
                'region': region,
                'account_info': instance_info['account_info'],
                'error': str(e)
            })
            return False

    def clear_security_group_rules(self, ec2_client, sg_id):
        """Clear all ingress and egress rules from a security group, handling cross-references"""
        try:
            self.log_operation('INFO', f"[CLEANUP] Clearing rules for security group {sg_id}")

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
                        self.log_operation('INFO', f"  [OK] Successfully removed ingress rule {rule_index + 1}")

                    except ClientError as e:
                        error_code = e.response['Error']['Code']
                        if error_code == 'InvalidGroupId.NotFound':
                            self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                            return True
                        elif error_code == 'InvalidPermission.NotFound':
                            self.log_operation('INFO', f"  Ingress rule {rule_index + 1} already removed")
                            rules_cleared += 1
                        else:
                            self.log_operation('ERROR', f"  [ERROR] Failed to remove ingress rule {rule_index + 1}: {e}")
                            rules_failed += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"  [ERROR] Unexpected error removing ingress rule {rule_index + 1}: {e}")
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
                    self.log_operation('INFO', f"Removing {len(non_default_egress)} non-default egress rules from {sg_id} ({sg_name})")

                    for rule_index, rule in enumerate(non_default_egress):
                        try:
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg_id,
                                IpPermissions=[rule]
                            )
                            rules_cleared += 1
                            self.log_operation('INFO', f"  [OK] Successfully removed egress rule {rule_index + 1}")

                        except ClientError as e:
                            error_code = e.response['Error']['Code']
                            if error_code == 'InvalidGroupId.NotFound':
                                self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                                return True
                            elif error_code == 'InvalidPermission.NotFound':
                                self.log_operation('INFO', f"  Egress rule {rule_index + 1} already removed")
                                rules_cleared += 1
                            else:
                                self.log_operation('ERROR', f"  [ERROR] Failed to remove egress rule {rule_index + 1}: {e}")
                                rules_failed += 1
                        except Exception as e:
                            self.log_operation('ERROR', f"  [ERROR] Unexpected error removing egress rule {rule_index + 1}: {e}")
                            rules_failed += 1

            # Wait briefly for rule changes to propagate
            if rules_cleared > 0:
                self.log_operation('INFO', f"Waiting 10 seconds for rule changes to propagate...")
                time.sleep(10)

            return rules_failed == 0

        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error clearing rules for security group {sg_id}: {e}")
            return False

    def delete_security_group(self, ec2_client, sg_info, force_delete=False):
        """Delete a security group after clearing its rules"""
        try:
            sg_id = sg_info['group_id']
            sg_name = sg_info['group_name']
            region = sg_info['region']
            account_name = sg_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"[DELETE]  Deleting security group {sg_id} ({sg_name}) in {region} ({account_name})")
            print(f"   [DELETE]  Deleting security group {sg_id} ({sg_name})...")

            # If it's attached to instances and force_delete is True, wait a bit
            if sg_info['is_attached'] and force_delete:
                self.log_operation('INFO', f"Security group {sg_id} is attached to instances, waiting for termination...")
                print(f"   [WAIT] Security group {sg_id} is attached to instances, waiting for termination...")
                time.sleep(30)  # Wait for instance termination

            # Step 1: Clear all security group rules first
            self.log_operation('INFO', f"Step 1: Clearing security group rules for {sg_id}")
            rules_cleared = self.clear_security_group_rules(ec2_client, sg_id)

            if not rules_cleared:
                self.log_operation('WARNING', f"Some rules could not be cleared from {sg_id}, proceeding with deletion attempt")

            # Step 2: Delete the security group
            self.log_operation('INFO', f"Step 2: Attempting to delete security group {sg_id}")
            print(f"   [DELETE] Attempting to delete security group {sg_id}...")
            ec2_client.delete_security_group(GroupId=sg_id)

            self.log_operation('INFO', f"[OK] Successfully deleted security group {sg_id} ({sg_name})")
            print(f"   [OK] Successfully deleted security group {sg_id}")

            self.cleanup_results['deleted_security_groups'].append({
                'group_id': sg_id,
                'group_name': sg_name,
                'description': sg_info['description'],
                'vpc_id': sg_info['vpc_id'],
                'was_attached': sg_info['is_attached'],
                'attached_instances': sg_info['attached_instances'],
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
                self.log_operation('WARNING', f"Cannot delete security group {sg_id}: dependency violation (still in use)")
                print(f"   [WARN] Cannot delete security group {sg_id}: still in use")
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
                print(f"   [ERROR] Failed to delete security group {sg_id}: {e}")
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
            print(f"   [ERROR] Unexpected error deleting security group {sg_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'security_group',
                'resource_id': sg_id,
                'region': region,
                'account_info': sg_info['account_info'],
                'error': str(e)
            })
            return False

    def get_all_elastic_ips_in_region(self, ec2_client, region, account_info):
        """Get all Elastic IPs in a region"""
        elastic_ips = []
        try:
            self.log_operation('INFO', f"[SCAN] Discovering Elastic IPs in {region}...")
            print(f"   [SCAN] Discovering Elastic IPs in {region}...")
            
            response = ec2_client.describe_addresses()
            
            for eip in response.get('Addresses', []):
                eip_info = {
                    'allocation_id': eip.get('AllocationId'),
                    'public_ip': eip.get('PublicIp'),
                    'private_ip': eip.get('PrivateIpAddress'),
                    'association_id': eip.get('AssociationId'),
                    'instance_id': eip.get('InstanceId'),
                    'network_interface_id': eip.get('NetworkInterfaceId'),
                    'is_associated': eip.get('AssociationId') is not None,
                    'domain': eip.get('Domain'),
                    'tags': {tag['Key']: tag['Value'] for tag in eip.get('Tags', [])},
                    'region': region,
                    'account_info': account_info
                }
                elastic_ips.append(eip_info)
            
            associated_count = sum(1 for eip in elastic_ips if eip['is_associated'])
            unassociated_count = len(elastic_ips) - associated_count
            
            self.log_operation('INFO', f"[OK] Found {len(elastic_ips)} Elastic IP(s) in {region}")
            self.log_operation('INFO', f"   - {associated_count} associated")
            self.log_operation('INFO', f"   - {unassociated_count} unassociated")
            print(f"   [OK] Found {len(elastic_ips)} Elastic IP(s): {associated_count} associated, {unassociated_count} unassociated")
            
            return elastic_ips
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'UnauthorizedOperation':
                self.log_operation('ERROR', f"Unauthorized to describe Elastic IPs in {region}")
                print(f"   [ERROR] Unauthorized to describe Elastic IPs")
            else:
                self.log_operation('ERROR', f"Error describing Elastic IPs in {region}: {e}")
                print(f"   [ERROR] Error describing Elastic IPs: {e}")
            return []
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error getting Elastic IPs in {region}: {e}")
            print(f"   [ERROR] Unexpected error getting Elastic IPs: {e}")
            return []

    def release_elastic_ip(self, ec2_client, eip_info):
        """Release an Elastic IP address"""
        try:
            allocation_id = eip_info['allocation_id']
            public_ip = eip_info['public_ip']
            region = eip_info['region']
            account_name = eip_info['account_info'].get('account_key', 'Unknown')
            
            # Check if it's associated
            if eip_info['is_associated']:
                self.log_operation('WARNING', f"[WARN] Elastic IP {public_ip} ({allocation_id}) is still associated with {eip_info.get('instance_id', 'unknown resource')}")
                print(f"   [WARN] Elastic IP {public_ip} is still associated, skipping...")
                return False
            
            self.log_operation('INFO', f"[DELETE] Releasing Elastic IP {public_ip} ({allocation_id}) in {region} ({account_name})")
            print(f"   [DELETE] Releasing Elastic IP {public_ip}...")
            
            ec2_client.release_address(AllocationId=allocation_id)
            
            self.log_operation('INFO', f"[OK] Successfully released Elastic IP {public_ip}")
            print(f"   [OK] Successfully released Elastic IP {public_ip}")
            
            self.cleanup_results['deleted_eips'].append({
                'allocation_id': allocation_id,
                'public_ip': public_ip,
                'private_ip': eip_info.get('private_ip'),
                'domain': eip_info.get('domain'),
                'tags': eip_info.get('tags', {}),
                'region': region,
                'account_info': eip_info['account_info'],
                'released_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            account_name = eip_info['account_info'].get('account_key', 'Unknown')
            if error_code == 'InvalidAllocationID.NotFound':
                self.log_operation('INFO', f"Elastic IP {allocation_id} does not exist")
                return True
            elif error_code == 'AuthFailure':
                self.log_operation('ERROR', f"Authorization failure releasing Elastic IP {allocation_id}")
                print(f"   [ERROR] Authorization failure releasing Elastic IP {public_ip}")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'elastic_ip',
                    'resource_id': allocation_id,
                    'public_ip': public_ip,
                    'region': region,
                    'account_info': eip_info['account_info'],
                    'error': 'Authorization failure'
                })
                return False
            else:
                self.log_operation('ERROR', f"Failed to release Elastic IP {allocation_id}: {e}")
                print(f"   [ERROR] Failed to release Elastic IP {public_ip}: {e}")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'elastic_ip',
                    'resource_id': allocation_id,
                    'public_ip': public_ip,
                    'region': region,
                    'account_info': eip_info['account_info'],
                    'error': str(e)
                })
                return False
        except Exception as e:
            account_name = eip_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Unexpected error releasing Elastic IP {allocation_id}: {e}")
            print(f"   [ERROR] Unexpected error releasing Elastic IP {public_ip}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'elastic_ip',
                'resource_id': allocation_id,
                'public_ip': public_ip,
                'region': region,
                'account_info': eip_info['account_info'],
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_info, region):
        """Clean up all EC2 resources in a specific account and region"""
        try:
            access_key = account_info['access_key']
            secret_key = account_info['secret_key']
            account_id = account_info['account_id']
            account_key = account_info['account_key']

            self.log_operation('INFO', f"[CLEANUP] Starting EC2 cleanup for {account_key} ({account_id}) in {region}")
            print(f"\n[CLEANUP] Starting EC2 cleanup for {account_key} ({account_id}) in {region}")

            # Create EC2 client
            ec2_client = self.create_ec2_client(access_key, secret_key, region)

            # Initialize variables
            instances = []
            security_groups = []
            elastic_ips = []
            attached_sgs = []
            unattached_sgs = []

            try:
                # Get all instances
                instances = self.get_all_instances_in_region(ec2_client, region, account_info)

                # Get all security groups
                security_groups = self.get_all_security_groups_in_region(ec2_client, region, account_info)

                # Get all Elastic IPs
                elastic_ips = self.get_all_elastic_ips_in_region(ec2_client, region, account_info)

                # Correlate instances and security groups
                attached_sgs, unattached_sgs = self.correlate_instances_and_security_groups(instances, security_groups)

            except Exception as discovery_error:
                self.log_operation('ERROR', f"Error during resource discovery in {account_key} ({region}): {discovery_error}")
                print(f"   [ERROR] Error during resource discovery: {discovery_error}")
                # Continue with whatever we managed to discover

            region_summary = {
                'account_key': account_key,
                'account_id': account_id,
                'region': region,
                'instances_found': len(instances),
                'attached_security_groups': len(attached_sgs),
                'unattached_security_groups': len(unattached_sgs),
                'total_security_groups': len(security_groups),
                'elastic_ips_found': len(elastic_ips)
            }

            self.cleanup_results['regions_processed'].append(region_summary)

            self.log_operation('INFO', f"[STATS] {account_key} ({region}) EC2 resources summary:")
            self.log_operation('INFO', f"   [COMPUTE] Instances: {len(instances)}")
            self.log_operation('INFO', f"   [PROTECTED]  Total Security Groups: {len(security_groups)}")
            self.log_operation('INFO', f"   [ATTACHED] Attached SGs: {len(attached_sgs)}")
            self.log_operation('INFO', f"   [UNLOCKED] Unattached SGs: {len(unattached_sgs)}")
            self.log_operation('INFO', f"   [NETWORK] Elastic IPs: {len(elastic_ips)}")

            print(f"   [STATS] EC2 resources found: {len(instances)} instances, {len(security_groups)} security groups, {len(elastic_ips)} elastic IPs")
            print(f"   [ATTACHED] Attached SGs: {len(attached_sgs)}, [UNLOCKED] Unattached SGs: {len(unattached_sgs)}")

            if not instances and not security_groups and not elastic_ips:
                self.log_operation('INFO', f"No EC2 resources found in {account_key} ({region})")
                self.print_colored(Colors.GREEN, f"   [OK] No EC2 resources to clean up in {region}")
                return True

            # Step 1: Terminate all instances sequentially
            if instances:
                self.log_operation('INFO', f"[DELETE]  Terminating {len(instances)} instances in {account_key} ({region}) sequentially")
                print(f"\n   [DELETE]  Terminating {len(instances)} instances sequentially...")

                terminated_count = 0
                failed_count = 0

                for i, instance in enumerate(instances, 1):
                    instance_id = instance['instance_id']
                    print(f"   [{i}/{len(instances)}] Processing instance {instance_id}...")

                    try:
                        success = self.terminate_instance(ec2_client, instance)
                        if success:
                            terminated_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log_operation('ERROR', f"Error terminating instance {instance_id}: {e}")
                        print(f"   [ERROR] Error terminating instance {instance_id}: {e}")

                print(f"   [OK] Terminated {terminated_count} instances, [ERROR] Failed: {failed_count}")

                # Wait for instances to start terminating
                if attached_sgs and terminated_count > 0:
                    self.log_operation('INFO', f"[WAIT] Waiting 60 seconds for {terminated_count} instances to start terminating...")
                    print(f"   [WAIT] Waiting 60 seconds for instances to start terminating...")
                    time.sleep(60)

            # Step 2: Release unassociated Elastic IPs
            if elastic_ips:
                # Filter for unassociated EIPs
                unassociated_eips = [eip for eip in elastic_ips if not eip['is_associated']]
                
                if unassociated_eips:
                    self.log_operation('INFO', f"[DELETE]  Releasing {len(unassociated_eips)} unassociated Elastic IP(s) in {account_key} ({region})")
                    print(f"\n   [DELETE]  Releasing {len(unassociated_eips)} unassociated Elastic IP(s)...")
                    
                    eip_released = 0
                    eip_failed = 0
                    
                    for i, eip in enumerate(unassociated_eips, 1):
                        public_ip = eip['public_ip']
                        print(f"   [{i}/{len(unassociated_eips)}] Processing Elastic IP {public_ip}...")
                        
                        try:
                            success = self.release_elastic_ip(ec2_client, eip)
                            if success:
                                eip_released += 1
                            else:
                                eip_failed += 1
                        except Exception as e:
                            eip_failed += 1
                            self.log_operation('ERROR', f"Error releasing Elastic IP {public_ip}: {e}")
                            print(f"   [ERROR] Error releasing Elastic IP {public_ip}: {e}")
                    
                    print(f"   [OK] Released {eip_released} Elastic IP(s), [ERROR] Failed: {eip_failed}")
                else:
                    self.log_operation('INFO', f"No unassociated Elastic IPs to release in {account_key} ({region})")
                    print(f"   [OK] No unassociated Elastic IPs to release")

            # Step 3: Delete unattached security groups first
            if unattached_sgs:
                self.log_operation('INFO', f"[DELETE]  Deleting {len(unattached_sgs)} unattached security groups in {account_key} ({region})")
                print(f"\n   [DELETE]  Deleting {len(unattached_sgs)} unattached security groups...")

                sg_success = 0
                sg_failed = 0

                for i, sg in enumerate(unattached_sgs, 1):
                    sg_id = sg['group_id']
                    print(f"   [{i}/{len(unattached_sgs)}] Processing security group {sg_id}...")

                    try:
                        success = self.delete_security_group(ec2_client, sg)
                        if success:
                            sg_success += 1
                        else:
                            sg_failed += 1
                    except Exception as e:
                        sg_failed += 1
                        self.log_operation('ERROR', f"Error deleting unattached security group {sg_id}: {e}")
                        print(f"   [ERROR] Error deleting security group {sg_id}: {e}")

                print(f"   [OK] Deleted {sg_success} unattached security groups, [ERROR] Failed: {sg_failed}")

            # Step 4: Delete attached security groups with multiple passes for cross-references
            if attached_sgs:
                self.log_operation('INFO', f"[DELETE]  Deleting {len(attached_sgs)} attached security groups in {account_key} ({region})")
                print(f"\n   [DELETE]  Deleting {len(attached_sgs)} attached security groups...")

                max_retries = 5
                retry_delay = 30

                remaining_sgs = attached_sgs.copy()

                for retry in range(max_retries):
                    self.log_operation('INFO', f"🔄 Security group deletion attempt {retry + 1}/{max_retries}")
                    print(f"   🔄 Security group deletion attempt {retry + 1}/{max_retries}")

                    # Track progress in this iteration
                    sgs_deleted_this_round = 0
                    still_remaining = []

                    for i, sg in enumerate(remaining_sgs, 1):
                        sg_id = sg['group_id']
                        print(f"   [{i}/{len(remaining_sgs)}] Trying to delete {sg_id}...")

                        try:
                            success = self.delete_security_group(ec2_client, sg, force_delete=True)
                            if success:
                                sgs_deleted_this_round += 1
                                self.log_operation('INFO', f"[OK] Deleted {sg_id} in attempt {retry + 1}")
                            else:
                                still_remaining.append(sg)
                                self.log_operation('WARNING', f"[WAIT] {sg_id} still has dependencies, will retry")
                        except Exception as e:
                            self.log_operation('ERROR', f"Error deleting attached security group {sg_id}: {e}")
                            print(f"   [ERROR] Error deleting security group {sg_id}: {e}")
                            still_remaining.append(sg)

                    self.log_operation('INFO', f"Attempt {retry + 1} results: {sgs_deleted_this_round} deleted, {len(still_remaining)} remaining")
                    print(f"   [OK] Deleted {sgs_deleted_this_round} security groups in attempt {retry + 1}, {len(still_remaining)} remaining")

                    # Update remaining list
                    remaining_sgs = still_remaining

                    if not remaining_sgs:
                        self.log_operation('INFO', f"[OK] All attached security groups deleted in {account_key} ({region})")
                        print(f"   [OK] All attached security groups deleted successfully!")
                        break

                    if retry < max_retries - 1 and remaining_sgs:
                        self.log_operation('INFO', f"[WAIT] Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                        print(f"   [WAIT] Waiting {retry_delay}s before next retry...")
                        time.sleep(retry_delay)

                if remaining_sgs:
                    self.log_operation('WARNING', f"[WARN]  {len(remaining_sgs)} security groups could not be deleted after {max_retries} retries")
                    print(f"   [WARN]  {len(remaining_sgs)} security groups could not be deleted after {max_retries} retries")

            self.log_operation('INFO', f"[OK] EC2 cleanup completed for {account_key} ({region})")
            print(f"\n   [OK] EC2 cleanup completed for {account_key} ({region})")
            return True

        except Exception as e:
            account_key = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error cleaning up EC2 resources in {account_key} ({region}): {e}")
            print(f"   [ERROR] Error cleaning up EC2 resources in {account_key} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_info': account_info,
                'region': region,
                'error': str(e)
            })
            return False

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n[REGION] Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
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
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {len(self.user_regions)} regions")
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(choice, len(self.user_regions))
                if not selected_indices:
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
                return selected_regions

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_ec2_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_instances_deleted = len(self.cleanup_results['deleted_instances'])
            total_sgs_deleted = len(self.cleanup_results['deleted_security_groups'])
            total_eips_released = len(self.cleanup_results['deleted_eips'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])

            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}

            for instance in self.cleanup_results['deleted_instances']:
                account = instance['account_info'].get('account_key', 'Unknown')
                region = instance['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0, 'regions': set()}
                deletions_by_account[account]['instances'] += 1
                deletions_by_account[account]['regions'].add(region)

                if region not in deletions_by_region:
                    deletions_by_region[region] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0}
                deletions_by_region[region]['instances'] += 1

            for sg in self.cleanup_results['deleted_security_groups']:
                account = sg['account_info'].get('account_key', 'Unknown')
                region = sg['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0, 'regions': set()}
                deletions_by_account[account]['security_groups'] += 1
                deletions_by_account[account]['regions'].add(region)

                if region not in deletions_by_region:
                    deletions_by_region[region] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0}
                deletions_by_region[region]['security_groups'] += 1

            for eip in self.cleanup_results['deleted_eips']:
                account = eip['account_info'].get('account_key', 'Unknown')
                region = eip['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0, 'regions': set()}
                deletions_by_account[account]['elastic_ips'] += 1
                deletions_by_account[account]['regions'].add(region)

                if region not in deletions_by_region:
                    deletions_by_region[region] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0}
                deletions_by_region[region]['elastic_ips'] += 1

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_EC2_CLEANUP",
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
                    "total_instances_deleted": total_instances_deleted,
                    "total_security_groups_deleted": total_sgs_deleted,
                    "total_elastic_ips_released": total_eips_released,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_instances": self.cleanup_results['deleted_instances'],
                    "deleted_security_groups": self.cleanup_results['deleted_security_groups'],
                    "deleted_elastic_ips": self.cleanup_results['deleted_eips'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }

            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation('INFO', f"[OK] Ultra EC2 cleanup report saved to: {report_filename}")
            return report_filename

        except Exception as e:
            self.log_operation('ERROR', f"[ERROR] Failed to save ultra EC2 cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "[START] ULTRA EC2 CLEANUP SESSION STARTED")

            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA EC2 CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)
            self.print_colored(Colors.WHITE, f"[DATE] Execution Date/Time: {self.current_time} UTC")
            self.print_colored(Colors.WHITE, f"[USER] Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"[FILE] Log File: {self.log_filename}")

            # STEP 1: Select root accounts
            self.print_colored(Colors.YELLOW, "\n[KEY] Select Root AWS Accounts for EC2 Cleanup:")

            root_accounts = self.cred_manager.select_root_accounts_interactive(allow_multiple=True)
            if not root_accounts:
                self.print_colored(Colors.RED, "[ERROR] No root accounts selected, exiting...")
                return
            selected_accounts = root_accounts

            # STEP 2: Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.RED, "[ERROR] No regions selected, exiting...")
                return

            # STEP 3: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(selected_regions)

            self.print_colored(Colors.YELLOW, f"\n EC2 CLEANUP CONFIGURATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"[KEY] Credential source: ROOT ACCOUNTS")
            self.print_colored(Colors.WHITE, f"[BANK] Selected accounts: {len(selected_accounts)}")
            self.print_colored(Colors.WHITE, f" Regions per account: {len(selected_regions)}")
            self.print_colored(Colors.WHITE, f"[LIST] Total operations: {total_operations}")
            self.print_colored(Colors.YELLOW, "=" * 80)

            # Show what will be cleaned up
            self.print_colored(Colors.RED, f"\n[WARN]  WARNING: This will delete ALL of the following EC2 resources:")
            self.print_colored(Colors.WHITE, f"    • EC2 Instances")
            self.print_colored(Colors.WHITE, f"    • Security Groups (except default)")
            self.print_colored(Colors.WHITE, f"    • Associated EBS Volumes")
            self.print_colored(Colors.WHITE, f"    across {len(selected_accounts)} accounts in {len(selected_regions)} regions ({total_operations} operations)")
            self.print_colored(Colors.RED, f"    This action CANNOT be undone!")

            # First confirmation - simple y/n
            confirm1 = 'yes' #input(f"\nContinue with EC2 cleanup? (y/n): ").strip().lower()
            #self.log_operation('INFO', f"First confirmation: '{confirm1}'")

            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra EC2 cleanup cancelled by user")
                self.print_colored(Colors.RED, "Cleanup cancelled")
                return

            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")

            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra EC2 cleanup cancelled at final confirmation")
                self.print_colored(Colors.RED, "Cleanup cancelled")
                return

            # STEP 4: Start the cleanup sequentially
            self.print_colored(Colors.RED, f"\n STARTING EC2 CLEANUP...")
            self.log_operation('INFO', f"EC2 CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(selected_regions)} regions")

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
                    self.print_colored(Colors.RED, f"[ERROR] Task failed for {account_key} ({region}): {e}")

            end_time = time.time()
            total_time = int(end_time - start_time)

            # STEP 5: Display final results
            self.print_colored(Colors.GREEN, f"\n" + "=" * 100)
            self.print_colored(Colors.GREEN, "[OK] EC2 CLEANUP COMPLETE")
            self.print_colored(Colors.GREEN, "=" * 100)
            self.print_colored(Colors.WHITE, f"[TIMER]  Total execution time: {total_time} seconds")
            self.print_colored(Colors.GREEN, f"[OK] Successful operations: {successful_tasks}")
            self.print_colored(Colors.RED, f"[ERROR] Failed operations: {failed_tasks}")
            self.print_colored(Colors.WHITE, f"[COMPUTE] Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            self.print_colored(Colors.WHITE, f"[PROTECTED]  Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            self.print_colored(Colors.WHITE, f"[NETWORK] Elastic IPs released: {len(self.cleanup_results['deleted_eips'])}")
            self.print_colored(Colors.WHITE, f"[SKIP]  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(self.cleanup_results['failed_deletions'])}")

            self.log_operation('INFO', f"EC2 CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            self.log_operation('INFO', f"Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            self.log_operation('INFO', f"Elastic IPs released: {len(self.cleanup_results['deleted_eips'])}")

            # STEP 6: Show account summary
            if self.cleanup_results['deleted_instances'] or self.cleanup_results['deleted_security_groups'] or self.cleanup_results['deleted_eips']:
                self.print_colored(Colors.YELLOW, f"\n[STATS] Deletion Summary by Account:")

                # Group by account
                account_summary = {}
                for instance in self.cleanup_results['deleted_instances']:
                    account = instance['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0, 'regions': set()}
                    account_summary[account]['instances'] += 1
                    account_summary[account]['regions'].add(instance['region'])

                for sg in self.cleanup_results['deleted_security_groups']:
                    account = sg['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0, 'regions': set()}
                    account_summary[account]['security_groups'] += 1
                    account_summary[account]['regions'].add(sg['region'])

                for eip in self.cleanup_results['deleted_eips']:
                    account = eip['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'security_groups': 0, 'elastic_ips': 0, 'regions': set()}
                    account_summary[account]['elastic_ips'] += 1
                    account_summary[account]['regions'].add(eip['region'])

                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.PURPLE, f"   [BANK] {account}:")
                    self.print_colored(Colors.WHITE, f"      [COMPUTE] Instances: {summary['instances']}")
                    self.print_colored(Colors.WHITE, f"      [PROTECTED]  Security Groups: {summary['security_groups']}")
                    self.print_colored(Colors.WHITE, f"      [NETWORK] Elastic IPs: {summary['elastic_ips']}")
                    self.print_colored(Colors.WHITE, f"      [REGION] Regions: {regions_list}")

            # STEP 7: Show failures if any
            if self.cleanup_results['failed_deletions']:
                self.print_colored(Colors.RED, f"\n[ERROR] Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    account_key = failure['account_info'].get('account_key', 'Unknown')
                    self.print_colored(Colors.WHITE, f"   • {failure['resource_type']} {failure['resource_id']} in {account_key} ({failure['region']})")
                    self.print_colored(Colors.WHITE, f"     Error: {failure['error']}")

                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    self.print_colored(Colors.WHITE, f"   ... and {remaining} more failures (see detailed report)")

            # Save comprehensive report
            self.print_colored(Colors.CYAN, f"\n[FILE] Saving EC2 cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"[OK] EC2 cleanup report saved to: {report_file}")

            self.print_colored(Colors.GREEN, f"[OK] Session log saved to: {self.log_filename}")

            self.print_colored(Colors.GREEN, f"\n[OK] EC2 cleanup completed successfully!")
            self.print_colored(Colors.YELLOW, "[ALERT]" * 30)

        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in EC2 cleanup execution: {str(e)}")
            self.print_colored(Colors.RED, f"\n[ERROR] FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraCleanupEC2Manager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] EC2 cleanup interrupted by user")
        exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()