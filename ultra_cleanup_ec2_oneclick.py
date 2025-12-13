#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
import threading
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from concurrent.futures import ThreadPoolExecutor, as_completed
from text_symbols import Symbols

class UltraEC2CleanupManager:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize lock for thread-safe logging FIRST
        self.log_lock = threading.Lock()
        
        # Initialize log file (now safe to use log_operation)
        self.setup_detailed_logging()
        
        # Load configuration
        self.load_configuration()
        
        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_instances': [],
            'deleted_security_groups': [],
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"ultra_ec2_cleanup_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            
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
            self.operation_logger.info("🚨 ULTRA EC2 CLEANUP SESSION STARTED 🚨")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config File: {self.config_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Thread-safe logging operation"""
        with self.log_lock:
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

    def load_configuration(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            self.log_operation('INFO', f"{Symbols.OK} Configuration loaded from: {self.config_file}")
            
            # Validate accounts
            if 'accounts' not in self.config_data:
                raise ValueError("No 'accounts' section found in configuration")
            
            # Filter out incomplete accounts
            valid_accounts = {}
            for account_name, account_data in self.config_data['accounts'].items():
                if (account_data.get('access_key') and 
                    account_data.get('secret_key') and
                    account_data.get('account_id') and
                    not account_data.get('access_key').startswith('ADD_')):
                    valid_accounts[account_name] = account_data
                else:
                    self.log_operation('WARNING', f"Skipping incomplete account: {account_name}")
            
            self.config_data['accounts'] = valid_accounts
            
            self.log_operation('INFO', f"{Symbols.STATS} Valid accounts loaded: {len(valid_accounts)}")
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                self.log_operation('INFO', f"   • {account_name}: {account_id} ({email})")
            
            # Get user regions
            self.user_regions = self.config_data.get('user_settings', {}).get('user_regions', [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
            ])
            
            self.log_operation('INFO', f"{Symbols.REGION} Regions to process: {self.user_regions}")
            
        except FileNotFoundError as e:
            self.log_operation('ERROR', f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation('ERROR', f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation('ERROR', f"Error loading configuration: {e}")
            sys.exit(1)

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using root account credentials"""
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

    def get_all_instances_in_region(self, ec2_client, region, account_name):
        """Get all EC2 instances in a specific region"""
        try:
            instances = []
            
            self.log_operation('INFO', f"{Symbols.SCAN} Scanning for instances in {region} ({account_name})")
            
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
                            'account_name': account_name,
                            'security_groups': security_groups,
                            'launch_time': instance.get('LaunchTime'),
                            'vpc_id': instance.get('VpcId'),
                            'subnet_id': instance.get('SubnetId'),
                            'public_ip': instance.get('PublicIpAddress'),
                            'private_ip': instance.get('PrivateIpAddress')
                        }
                        
                        instances.append(instance_info)
            
            self.log_operation('INFO', f"[PACKAGE] Found {len(instances)} instances in {region} ({account_name})")
            
            return instances
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting instances in {region} ({account_name}): {e}")
            return []

    def get_all_security_groups_in_region(self, ec2_client, region, account_name):
        """Get all security groups in a specific region"""
        try:
            security_groups = []
            
            self.log_operation('INFO', f"{Symbols.SCAN} Scanning for security groups in {region} ({account_name})")
            
            paginator = ec2_client.get_paginator('describe_security_groups')
            
            for page in paginator.paginate():
                for sg in page['SecurityGroups']:
                    sg_id = sg['GroupId']
                    sg_name = sg['GroupName']
                    vpc_id = sg['VpcId']
                    description = sg['Description']
                    
                    # Skip default security groups
                    if sg_name == 'default':
                        continue
                    
                    sg_info = {
                        'group_id': sg_id,
                        'group_name': sg_name,
                        'description': description,
                        'vpc_id': vpc_id,
                        'region': region,
                        'account_name': account_name,
                        'is_attached': False,  # Will be updated later
                        'attached_instances': []
                    }
                    
                    security_groups.append(sg_info)
            
            self.log_operation('INFO', f"{Symbols.PROTECTED}  Found {len(security_groups)} security groups in {region} ({account_name})")
            
            return security_groups
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting security groups in {region} ({account_name}): {e}")
            return []

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
            
            self.log_operation('INFO', f"🔗 Security group correlation complete:")
            self.log_operation('INFO', f"   📎 Attached to instances: {len(attached_sgs)}")
            self.log_operation('INFO', f"   🔓 Unattached: {len(unattached_sgs)}")
            
            return attached_sgs, unattached_sgs
            
        except Exception as e:
            self.log_operation('ERROR', f"Error correlating instances and security groups: {e}")
            return [], []

    def terminate_instance(self, ec2_client, instance_info, wait_for_termination=False):
        """Terminate an EC2 instance"""
        try:
            instance_id = instance_info['instance_id']
            region = instance_info['region']
            account_name = instance_info['account_name']
            current_state = instance_info['state']
            
            if current_state in ['terminated', 'terminating']:
                self.log_operation('INFO', f"Instance {instance_id} already {current_state}")
                self.cleanup_results['skipped_resources'].append({
                    'resource_type': 'instance',
                    'resource_id': instance_id,
                    'region': region,
                    'account_name': account_name,
                    'reason': f'Already {current_state}'
                })
                return True
            
            self.log_operation('INFO', f"{Symbols.DELETE}  Terminating instance {instance_id} in {region} ({account_name})")
            
            response = ec2_client.terminate_instances(InstanceIds=[instance_id])
            
            current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
            previous_state = response['TerminatingInstances'][0]['PreviousState']['Name']
            
            self.log_operation('INFO', f"{Symbols.OK} Instance {instance_id} termination initiated: {previous_state} → {current_state}")
            
            self.cleanup_results['deleted_instances'].append({
                'instance_id': instance_id,
                'instance_name': instance_info['instance_name'],
                'instance_type': instance_info['instance_type'],
                'previous_state': previous_state,
                'current_state': current_state,
                'region': region,
                'account_name': account_name,
                'public_ip': instance_info.get('public_ip'),
                'private_ip': instance_info.get('private_ip'),
                'terminated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to terminate instance {instance_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'instance',
                'resource_id': instance_id,
                'region': region,
                'account_name': account_name,
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
            
            # [FIRE] Clear ingress rules (including cross-references)
            if ingress_rules:
                self.log_operation('INFO', f"Removing {len(ingress_rules)} ingress rules from {sg_id} ({sg_name})")
                
                # Process rules one by one to handle cross-references better
                for rule_index, rule in enumerate(ingress_rules):
                    try:
                        # Log rule details for debugging
                        protocol = rule.get('IpProtocol', 'unknown')
                        from_port = rule.get('FromPort', 'N/A')
                        to_port = rule.get('ToPort', 'N/A')
                        
                        # Check if rule references other security groups
                        sg_references = rule.get('UserIdGroupPairs', [])
                        ip_ranges = rule.get('IpRanges', [])
                        
                        if sg_references:
                            ref_groups = [ref.get('GroupId', 'unknown') for ref in sg_references]
                            self.log_operation('INFO', f"  Rule {rule_index + 1}: {protocol}:{from_port}-{to_port} references SGs: {ref_groups}")
                        else:
                            self.log_operation('INFO', f"  Rule {rule_index + 1}: {protocol}:{from_port}-{to_port} from IPs: {[ip.get('CidrIp', 'unknown') for ip in ip_ranges]}")
                        
                        # Try to remove this specific rule
                        ec2_client.revoke_security_group_ingress(
                            GroupId=sg_id,
                            IpPermissions=[rule]
                        )
                        rules_cleared += 1
                        self.log_operation('INFO', f"  {Symbols.OK} Successfully removed ingress rule {rule_index + 1}")
                        
                    except ClientError as e:
                        error_code = e.response['Error']['Code']
                        if error_code == 'InvalidGroupId.NotFound':
                            self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                            return True
                        elif error_code == 'InvalidPermission.NotFound':
                            self.log_operation('INFO', f"  Ingress rule {rule_index + 1} already removed")
                            rules_cleared += 1
                        else:
                            self.log_operation('ERROR', f"  {Symbols.ERROR} Failed to remove ingress rule {rule_index + 1}: {e}")
                            rules_failed += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"  {Symbols.ERROR} Unexpected error removing ingress rule {rule_index + 1}: {e}")
                        rules_failed += 1
            
            # [FIRE] Clear egress rules (but keep the default allow-all rule)
            if egress_rules:
                # Filter out the default egress rule (0.0.0.0/0 for all traffic)
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
                    
                    # Process egress rules one by one
                    for rule_index, rule in enumerate(non_default_egress):
                        try:
                            # Log rule details for debugging
                            protocol = rule.get('IpProtocol', 'unknown')
                            from_port = rule.get('FromPort', 'N/A')
                            to_port = rule.get('ToPort', 'N/A')
                            
                            # Check if rule references other security groups
                            sg_references = rule.get('UserIdGroupPairs', [])
                            ip_ranges = rule.get('IpRanges', [])
                            
                            if sg_references:
                                ref_groups = [ref.get('GroupId', 'unknown') for ref in sg_references]
                                self.log_operation('INFO', f"  Egress Rule {rule_index + 1}: {protocol}:{from_port}-{to_port} references SGs: {ref_groups}")
                            else:
                                self.log_operation('INFO', f"  Egress Rule {rule_index + 1}: {protocol}:{from_port}-{to_port} to IPs: {[ip.get('CidrIp', 'unknown') for ip in ip_ranges]}")
                            
                            # Try to remove this specific rule
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg_id,
                                IpPermissions=[rule]
                            )
                            rules_cleared += 1
                            self.log_operation('INFO', f"  {Symbols.OK} Successfully removed egress rule {rule_index + 1}")
                            
                        except ClientError as e:
                            error_code = e.response['Error']['Code']
                            if error_code == 'InvalidGroupId.NotFound':
                                self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                                return True
                            elif error_code == 'InvalidPermission.NotFound':
                                self.log_operation('INFO', f"  Egress rule {rule_index + 1} already removed")
                                rules_cleared += 1
                            else:
                                self.log_operation('ERROR', f"  {Symbols.ERROR} Failed to remove egress rule {rule_index + 1}: {e}")
                                rules_failed += 1
                        except Exception as e:
                            self.log_operation('ERROR', f"  {Symbols.ERROR} Unexpected error removing egress rule {rule_index + 1}: {e}")
                            rules_failed += 1
                else:
                    self.log_operation('INFO', f"No non-default egress rules to remove from {sg_id}")
            
            total_rules = len(ingress_rules) + len(egress_rules)
            if total_rules == 0:
                self.log_operation('INFO', f"No rules found in security group {sg_id}")
            else:
                self.log_operation('INFO', f"Rule clearing summary for {sg_id}: {rules_cleared} cleared, {rules_failed} failed")
            
            # Wait briefly for rule changes to propagate
            if rules_cleared > 0:
                self.log_operation('INFO', f"Waiting 10 seconds for rule changes to propagate...")
                time.sleep(10)  # Increased wait time for cross-references
            
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
            account_name = sg_info['account_name']
            
            self.log_operation('INFO', f"{Symbols.DELETE}  Deleting security group {sg_id} ({sg_name}) in {region} ({account_name})")
            
            # If it's attached to instances and force_delete is True, wait a bit
            if sg_info['is_attached'] and force_delete:
                self.log_operation('INFO', f"Security group {sg_id} is attached to instances, waiting for termination...")
                time.sleep(30)  # Wait for instance termination
            
            # Step 1: Clear all security group rules first
            self.log_operation('INFO', f"Step 1: Clearing security group rules for {sg_id}")
            rules_cleared = self.clear_security_group_rules(ec2_client, sg_id)
            
            if not rules_cleared:
                self.log_operation('WARNING', f"Some rules could not be cleared from {sg_id}, proceeding with deletion attempt")
            
            # Step 2: Delete the security group
            self.log_operation('INFO', f"Step 2: Attempting to delete security group {sg_id}")
            ec2_client.delete_security_group(GroupId=sg_id)
            
            self.log_operation('INFO', f"{Symbols.OK} Successfully deleted security group {sg_id} ({sg_name})")
            
            self.cleanup_results['deleted_security_groups'].append({
                'group_id': sg_id,
                'group_name': sg_name,
                'description': sg_info['description'],
                'vpc_id': sg_info['vpc_id'],
                'was_attached': sg_info['is_attached'],
                'attached_instances': sg_info['attached_instances'],
                'rules_cleared': rules_cleared,
                'region': region,
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidGroupId.NotFound':
                self.log_operation('INFO', f"Security group {sg_id} does not exist")
                return True
            elif error_code == 'DependencyViolation':
                self.log_operation('WARNING', f"Cannot delete security group {sg_id}: dependency violation (still in use)")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'security_group',
                    'resource_id': sg_id,
                    'region': region,
                    'account_name': account_name,
                    'error': 'Dependency violation - still in use after rule clearing'
                })
                return False
            else:
                self.log_operation('ERROR', f"Failed to delete security group {sg_id}: {e}")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'security_group',
                    'resource_id': sg_id,
                    'region': region,
                    'account_name': account_name,
                    'error': str(e)
                })
                return False
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error deleting security group {sg_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'security_group',
                'resource_id': sg_id,
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_name, account_data, region):
        """Clean up all resources in a specific account and region"""
        try:
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            account_id = account_data['account_id']
            
            self.log_operation('INFO', f"🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
            
            # Create EC2 client
            ec2_client = self.create_ec2_client(access_key, secret_key, region)
            
            # [FIRE] Initialize variables first to avoid scope issues
            instances = []
            security_groups = []
            attached_sgs = []
            unattached_sgs = []
            
            try:
                # Get all instances
                instances = self.get_all_instances_in_region(ec2_client, region, account_name)
                
                # Get all security groups
                security_groups = self.get_all_security_groups_in_region(ec2_client, region, account_name)
                
                # Correlate instances and security groups
                attached_sgs, unattached_sgs = self.correlate_instances_and_security_groups(instances, security_groups)
                
            except Exception as discovery_error:
                self.log_operation('ERROR', f"Error during resource discovery in {account_name} ({region}): {discovery_error}")
                # Continue with whatever we managed to discover
            
            region_summary = {
                'account_name': account_name,
                'account_id': account_id,
                'region': region,
                'instances_found': len(instances),
                'attached_security_groups': len(attached_sgs),
                'unattached_security_groups': len(unattached_sgs),
                'total_security_groups': len(security_groups)
            }
            
            self.cleanup_results['regions_processed'].append(region_summary)
            
            self.log_operation('INFO', f"{Symbols.STATS} {account_name} ({region}) summary:")
            self.log_operation('INFO', f"   💻 Instances: {len(instances)}")
            self.log_operation('INFO', f"   {Symbols.PROTECTED}  Total Security Groups: {len(security_groups)}")
            self.log_operation('INFO', f"   📎 Attached SGs: {len(attached_sgs)}")
            self.log_operation('INFO', f"   🔓 Unattached SGs: {len(unattached_sgs)}")
            
            if not instances and not security_groups:
                self.log_operation('INFO', f"No resources found in {account_name} ({region})")
                return True
            
            # Step 1: Terminate all instances
            if instances:
                self.log_operation('INFO', f"{Symbols.DELETE}  Terminating {len(instances)} instances in {account_name} ({region})")
                
                for instance in instances:
                    try:
                        self.terminate_instance(ec2_client, instance)
                    except Exception as e:
                        self.log_operation('ERROR', f"Error terminating instance {instance['instance_id']}: {e}")
                
                # Wait for instances to start terminating
                if attached_sgs:
                    self.log_operation('INFO', f"⏳ Waiting 60 seconds for instances to start terminating...")
                    time.sleep(60)
            
            # Step 2: Delete unattached security groups first
            if unattached_sgs:
                self.log_operation('INFO', f"{Symbols.DELETE}  Deleting {len(unattached_sgs)} unattached security groups in {account_name} ({region})")
                
                for sg in unattached_sgs:
                    try:
                        self.delete_security_group(ec2_client, sg)
                    except Exception as e:
                        self.log_operation('ERROR', f"Error deleting unattached security group {sg['group_id']}: {e}")
            
            # Step 3: [FIRE] ENHANCED - Delete attached security groups with multiple passes for cross-references
            if attached_sgs:
                self.log_operation('INFO', f"{Symbols.DELETE}  Deleting {len(attached_sgs)} attached security groups in {account_name} ({region})")
                
                max_retries = 5  # Increased retries for cross-references
                retry_delay = 30  # Reduced delay between retries
                
                remaining_sgs = attached_sgs.copy()
                
                for retry in range(max_retries):
                    self.log_operation('INFO', f"{Symbols.SCAN} Security group deletion attempt {retry + 1}/{max_retries}")
                    
                    # Track progress in this iteration
                    sgs_deleted_this_round = 0
                    still_remaining = []
                    
                    for sg in remaining_sgs:
                        try:
                            success = self.delete_security_group(ec2_client, sg, force_delete=True)
                            if success:
                                sgs_deleted_this_round += 1
                                self.log_operation('INFO', f"{Symbols.OK} Deleted {sg['group_id']} in attempt {retry + 1}")
                            else:
                                still_remaining.append(sg)
                                self.log_operation('WARNING', f"⏳ {sg['group_id']} still has dependencies, will retry")
                        except Exception as e:
                            self.log_operation('ERROR', f"Error deleting attached security group {sg['group_id']}: {e}")
                            still_remaining.append(sg)
                    
                    self.log_operation('INFO', f"Attempt {retry + 1} results: {sgs_deleted_this_round} deleted, {len(still_remaining)} remaining")
                    
                    # Update remaining list
                    remaining_sgs = still_remaining
                    
                    if not remaining_sgs:
                        self.log_operation('INFO', f"{Symbols.OK} All attached security groups deleted in {account_name} ({region})")
                        break
                    
                    # If no progress was made and we have remaining groups, try clearing rules again
                    if sgs_deleted_this_round == 0 and remaining_sgs and retry < max_retries - 1:
                        self.log_operation('INFO', f"🧹 No progress made, re-clearing rules for remaining {len(remaining_sgs)} security groups")
                        for sg in remaining_sgs:
                            try:
                                self.clear_security_group_rules(ec2_client, sg['group_id'])
                            except Exception as e:
                                self.log_operation('ERROR', f"Error re-clearing rules for {sg['group_id']}: {e}")
                    
                    if retry < max_retries - 1:
                        self.log_operation('INFO', f"⏳ Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                        time.sleep(retry_delay)
                
                if remaining_sgs:
                    self.log_operation('WARNING', f"{Symbols.WARN}  {len(remaining_sgs)} security groups could not be deleted after {max_retries} retries")
                    self.log_operation('WARNING', f"Remaining security groups: {[sg['group_id'] for sg in remaining_sgs]}")
                    
                    # Log detailed information about remaining security groups
                    for sg in remaining_sgs:
                        try:
                            response = ec2_client.describe_security_groups(GroupIds=[sg['group_id']])
                            sg_details = response['SecurityGroups'][0]
                            ingress_count = len(sg_details.get('IpPermissions', []))
                            egress_count = len(sg_details.get('IpPermissionsEgress', []))
                            self.log_operation('WARNING', f"  {sg['group_id']} still has {ingress_count} ingress, {egress_count} egress rules")
                        except Exception as e:
                            self.log_operation('ERROR', f"  Could not get details for {sg['group_id']}: {e}")
            
            self.log_operation('INFO', f"{Symbols.OK} Cleanup completed for {account_name} ({region})")
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Error cleaning up {account_name} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return False

    def run_parallel_cleanup(self, max_workers=5):
        """Run cleanup across all accounts and regions in parallel"""
        try:
            accounts = self.config_data['accounts']
            regions = self.user_regions
            
            # Create list of (account_name, account_data, region) tuples
            tasks = []
            for account_name, account_data in accounts.items():
                for region in regions:
                    tasks.append((account_name, account_data, region))
            
            self.log_operation('INFO', f"{Symbols.START} Starting parallel cleanup across {len(accounts)} accounts and {len(regions)} regions")
            self.log_operation('INFO', f"{Symbols.LIST} Total tasks: {len(tasks)} (max workers: {max_workers})")
            
            successful_tasks = 0
            failed_tasks = 0
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_task = {
                    executor.submit(self.cleanup_account_region, account_name, account_data, region): (account_name, region)
                    for account_name, account_data, region in tasks
                }
                
                # Process completed tasks
                for future in as_completed(future_to_task):
                    account_name, region = future_to_task[future]
                    try:
                        success = future.result()
                        if success:
                            successful_tasks += 1
                        else:
                            failed_tasks += 1
                    except Exception as e:
                        self.log_operation('ERROR', f"Task failed for {account_name} ({region}): {e}")
                        failed_tasks += 1
            
            self.log_operation('INFO', f"{Symbols.TARGET} Parallel cleanup completed:")
            self.log_operation('INFO', f"   {Symbols.OK} Successful tasks: {successful_tasks}")
            self.log_operation('INFO', f"   {Symbols.ERROR} Failed tasks: {failed_tasks}")
            
            return successful_tasks, failed_tasks
            
        except Exception as e:
            self.log_operation('ERROR', f"Error in parallel cleanup: {e}")
            return 0, len(tasks)

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_filename = f"ultra_ec2_cleanup_report_{self.execution_timestamp}.json"
            
            # Calculate statistics
            total_instances_deleted = len(self.cleanup_results['deleted_instances'])
            total_sgs_deleted = len(self.cleanup_results['deleted_security_groups'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])
            
            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for instance in self.cleanup_results['deleted_instances']:
                account = instance['account_name']
                region = instance['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'instances': 0, 'security_groups': 0}
                deletions_by_account[account]['instances'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'instances': 0, 'security_groups': 0}
                deletions_by_region[region]['instances'] += 1
            
            for sg in self.cleanup_results['deleted_security_groups']:
                account = sg['account_name']
                region = sg['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'instances': 0, 'security_groups': 0}
                deletions_by_account[account]['security_groups'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'instances': 0, 'security_groups': 0}
                deletions_by_region[region]['security_groups'] += 1
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_file": self.config_file,
                    "log_file": self.log_filename,
                    "accounts_in_config": list(self.config_data['accounts'].keys()),
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(set(rp['account_name'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_instances_deleted": total_instances_deleted,
                    "total_security_groups_deleted": total_sgs_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_instances": self.cleanup_results['deleted_instances'],
                    "deleted_security_groups": self.cleanup_results['deleted_security_groups'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"{Symbols.OK} Ultra cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to save ultra cleanup report: {e}")
            return None

    def display_configuration_summary(self):
        """Display configuration summary before cleanup"""
        accounts = self.config_data['accounts']
        regions = self.user_regions
        
        print(f"\n{Symbols.TARGET} ULTRA CLEANUP CONFIGURATION")
        print("=" * 80)
        print(f"📄 Config file: {self.config_file}")
        print(f"{Symbols.ACCOUNT} Accounts to process: {len(accounts)}")
        print(f"{Symbols.REGION} Regions per account: {len(regions)}")
        print(f"{Symbols.LIST} Total operations: {len(accounts) * len(regions)}")
        print("=" * 80)
        
        print(f"\n{Symbols.ACCOUNT} AWS Accounts:")
        for account_name, account_data in accounts.items():
            account_id = account_data.get('account_id', 'Unknown')
            email = account_data.get('email', 'Unknown')
            print(f"   • {account_name}: {account_id} ({email})")
        
        print(f"\n{Symbols.REGION} Regions:")
        for i, region in enumerate(regions, 1):
            print(f"   {i}. {region}")
        
        print("=" * 80)

    def run(self):
        """Main execution method with account selection"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA EC2 CLEANUP SESSION 🚨")
        
            print("🚨" * 30)
            print("💥 ULTRA EC2 CLEANUP - WITH ACCOUNT SELECTION 💥")
            print("🚨" * 30)
            print(f"{Symbols.DATE} Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"{Symbols.LIST} Log File: {self.log_filename}")
        
            # Display available accounts first
            accounts = self.config_data['accounts']
            regions = self.user_regions
        
            print(f"\n{Symbols.ACCOUNT} AVAILABLE AWS ACCOUNTS:")
            print("=" * 80)
        
            account_list = []
        
            for i, (account_name, account_data) in enumerate(accounts.items(), 1):
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
            
                account_list.append({
                    'name': account_name,
                    'account_id': account_id,
                    'email': email,
                    'data': account_data
                })
            
                print(f"  {i}. {account_name}: {account_id} ({email})")
        
            # Selection prompt
            print("\nAccount Selection Options:")
            print("  • Single accounts: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-2,4")
            print("  • All accounts: 'all' or press Enter")
            print("  • Cancel: 'cancel' or 'quit'")
        
            selection = input("\n[#] Select accounts to process: ").strip().lower()
        
            if selection in ['cancel', 'quit']:
                self.log_operation('INFO', "EC2 cleanup cancelled by user")
                print(f"{Symbols.ERROR} Cleanup cancelled")
                return
            
            # Process selection
            selected_accounts = {}
            if not selection or selection == 'all':
                selected_accounts = accounts
                self.log_operation('INFO', f"All accounts selected: {len(accounts)}")
                print(f"{Symbols.OK} Selected all {len(accounts)} accounts")
            else:
                try:
                    # Parse selection
                    parts = []
                    for part in selection.split(','):
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            if start < 1 or end > len(account_list):
                                raise ValueError(f"Range {part} out of bounds (1-{len(account_list)})")
                            parts.extend(range(start, end + 1))
                        else:
                            num = int(part)
                            if num < 1 or num > len(account_list):
                                raise ValueError(f"Selection {part} out of bounds (1-{len(account_list)})")
                            parts.append(num)
                
                    # Get selected account data
                    for idx in parts:
                        account = account_list[idx-1]
                        selected_accounts[account['name']] = account['data']
                
                    if not selected_accounts:
                        raise ValueError("No valid accounts selected")
                
                    self.log_operation('INFO', f"Selected accounts: {list(selected_accounts.keys())}")
                    print(f"{Symbols.OK} Selected {len(selected_accounts)} accounts: {', '.join(selected_accounts.keys())}")
                
                except ValueError as e:
                    self.log_operation('ERROR', f"Invalid account selection: {e}")
                    print(f"{Symbols.ERROR} Invalid selection: {e}")
                    return
        
            # Update the config_data with only selected accounts
            self.config_data['accounts'] = selected_accounts
        
            # Display configuration summary with selected accounts
            self.display_configuration_summary()
        
            # Calculate totals for summary
            account_count = len(selected_accounts)
            region_count = len(regions)
            total_operations = account_count * region_count
        
            # Simplified confirmation process
            print(f"\n{Symbols.WARN}  WARNING: This will delete ALL EC2 instances and security groups")
            print(f"    across {account_count} accounts in {region_count} regions ({total_operations} operations)")
            print(f"    This action CANNOT be undone!")
        
            # First confirmation
            confirm1 = input(f"\nContinue with cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")
        
            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra cleanup cancelled by user")
                print(f"{Symbols.ERROR} Cleanup cancelled")
                return
        
            # Second confirmation - final check
            confirm2 = input(f"Are you absolutely sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")
        
            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra cleanup cancelled at final confirmation")
                print(f"{Symbols.ERROR} Cleanup cancelled")
                return
        
            # Start the cleanup
            print(f"\n💥 STARTING CLEANUP...")
            self.log_operation('INFO', f"🚨 CLEANUP INITIATED - {account_count} accounts, {region_count} regions")
        
            start_time = time.time()
        
            # Run parallel cleanup (this uses the updated self.config_data with selected accounts)
            successful_tasks, failed_tasks = self.run_parallel_cleanup(max_workers=10)
        
            end_time = time.time()
            total_time = int(end_time - start_time)
        
            # Display final results
            print(f"\n💥" + "="*25 + " CLEANUP COMPLETE " + "="*25)
            print(f"{Symbols.TIMER}  Total execution time: {total_time} seconds")
            print(f"{Symbols.OK} Successful operations: {successful_tasks}")
            print(f"{Symbols.ERROR} Failed operations: {failed_tasks}")
            print(f"💻 Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            print(f"{Symbols.PROTECTED}  Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            print(f"⏭️  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            print(f"{Symbols.ERROR} Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
        
            self.log_operation('INFO', f"CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            self.log_operation('INFO', f"Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
        
            # Show account summary
            if self.cleanup_results['deleted_instances'] or self.cleanup_results['deleted_security_groups']:
                print(f"\n{Symbols.STATS} Deletion Summary by Account:")
            
                # Group by account
                account_summary = {}
                for instance in self.cleanup_results['deleted_instances']:
                    account = instance['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'security_groups': 0, 'regions': set()}
                    account_summary[account]['instances'] += 1
                    account_summary[account]['regions'].add(instance['region'])
            
                for sg in self.cleanup_results['deleted_security_groups']:
                    account = sg['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'instances': 0, 'security_groups': 0, 'regions': set()}
                    account_summary[account]['security_groups'] += 1
                    account_summary[account]['regions'].add(sg['region'])
            
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    print(f"   {Symbols.ACCOUNT} {account}:")
                    print(f"      💻 Instances: {summary['instances']}")
                    print(f"      {Symbols.PROTECTED}  Security Groups: {summary['security_groups']}")
                    print(f"      {Symbols.REGION} Regions: {regions_list}")
        
            # Show failures if any
            if self.cleanup_results['failed_deletions']:
                print(f"\n{Symbols.ERROR} Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    print(f"   • {failure['resource_type']} {failure['resource_id']} in {failure['account_name']} ({failure['region']})")
                    print(f"     Error: {failure['error']}")
            
                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    print(f"   ... and {remaining} more failures (see detailed report)")
        
            # Save comprehensive report
            print(f"\n📄 Saving cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                print(f"{Symbols.OK} Cleanup report saved to: {report_file}")
        
            print(f"{Symbols.OK} Session log saved to: {self.log_filename}")
        
            print(f"\n💥 CLEANUP COMPLETE! 💥")
            print("🚨" * 50)
        
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            traceback.print_exc()
            raise
def main():
    """Main function"""
    try:
        manager = UltraEC2CleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"{Symbols.ERROR} Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()