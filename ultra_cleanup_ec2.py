#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError

class UltraEC2CleanupManager:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize log file
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
            log_dir = "aws/ec2"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/ec2 directory
            self.log_filename = f"{log_dir}/ultra_ec2_cleanup_log_{self.execution_timestamp}.log"
            
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
        """Simple logging operation (no thread-safety)"""
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
            
            self.log_operation('INFO', f"✅ Configuration loaded from: {self.config_file}")
            
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
            
            self.log_operation('INFO', f"📊 Valid accounts loaded: {len(valid_accounts)}")
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                self.log_operation('INFO', f"   • {account_name}: {account_id} ({email})")
            
            # Get user regions
            self.user_regions = self.config_data.get('user_settings', {}).get('user_regions', [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
            ])
            
            self.log_operation('INFO', f"🌍 Regions to process: {self.user_regions}")
            
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

    def get_all_instances_in_region(self, ec2_client, region, account_name):
        """Get all EC2 instances in a specific region"""
        try:
            instances = []
            
            self.log_operation('INFO', f"🔍 Scanning for instances in {region} ({account_name})")
            print(f"   🔍 Scanning for instances in {region} ({account_name})...")
            
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
            
            self.log_operation('INFO', f"📦 Found {len(instances)} instances in {region} ({account_name})")
            print(f"   📦 Found {len(instances)} instances in {region} ({account_name})")
            
            return instances
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting instances in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting instances in {region}: {e}")
            return []

    def get_all_security_groups_in_region(self, ec2_client, region, account_name):
        """Get all security groups in a specific region"""
        try:
            security_groups = []
            
            self.log_operation('INFO', f"🔍 Scanning for security groups in {region} ({account_name})")
            print(f"   🔍 Scanning for security groups in {region} ({account_name})...")
            
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
            
            self.log_operation('INFO', f"🛡️  Found {len(security_groups)} security groups in {region} ({account_name})")
            print(f"   🛡️  Found {len(security_groups)} security groups in {region} ({account_name})")
            
            return security_groups
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting security groups in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting security groups in {region}: {e}")
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

    def terminate_instance(self, ec2_client, instance_info):
        """Terminate an EC2 instance - now sequential (no thread-safety needed)"""
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
        
            self.log_operation('INFO', f"🗑️  Terminating instance {instance_id} in {region} ({account_name})")
            print(f"   🗑️  Terminating instance {instance_id} in {region} ({account_name})...")
        
            response = ec2_client.terminate_instances(InstanceIds=[instance_id])
        
            current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
            previous_state = response['TerminatingInstances'][0]['PreviousState']['Name']
        
            self.log_operation('INFO', f"✅ Instance {instance_id} termination initiated: {previous_state} → {current_state}")
            print(f"   ✅ Instance {instance_id} termination initiated: {previous_state} → {current_state}")
            
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
            print(f"   ❌ Failed to terminate instance {instance_id}: {e}")
            
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
            
            # Clear ingress rules (including cross-references)
            if ingress_rules:
                self.log_operation('INFO', f"Removing {len(ingress_rules)} ingress rules from {sg_id} ({sg_name})")
                print(f"   Removing {len(ingress_rules)} ingress rules from {sg_id} ({sg_name})...")
                
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
                    print(f"   Removing {len(non_default_egress)} non-default egress rules from {sg_id}...")
                    
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
                            self.log_operation('ERROR', f"  ❌ Unexpected error removing egress rule {rule_index + 1}: {e}")
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
            
            self.log_operation('INFO', f"🗑️  Deleting security group {sg_id} ({sg_name}) in {region} ({account_name})")
            print(f"   🗑️  Deleting security group {sg_id} ({sg_name})...")
            
            # If it's attached to instances and force_delete is True, wait a bit
            if sg_info['is_attached'] and force_delete:
                self.log_operation('INFO', f"Security group {sg_id} is attached to instances, waiting for termination...")
                print(f"   ⏳ Security group {sg_id} is attached to instances, waiting for termination...")
                time.sleep(30)  # Wait for instance termination
            
            # Step 1: Clear all security group rules first
            self.log_operation('INFO', f"Step 1: Clearing security group rules for {sg_id}")
            rules_cleared = self.clear_security_group_rules(ec2_client, sg_id)
            
            if not rules_cleared:
                self.log_operation('WARNING', f"Some rules could not be cleared from {sg_id}, proceeding with deletion attempt")
            
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
                print(f"   ⚠️ Cannot delete security group {sg_id}: still in use")
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
                print(f"   ❌ Failed to delete security group {sg_id}: {e}")
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
            print(f"   ❌ Unexpected error deleting security group {sg_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'security_group',
                'resource_id': sg_id,
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_name, account_data, region):
        """Clean up all resources in a specific account and region - sequential (no threading)"""
        try:
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            account_id = account_data['account_id']
        
            self.log_operation('INFO', f"🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
            print(f"\n🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
        
            # Create EC2 client
            ec2_client = self.create_ec2_client(access_key, secret_key, region)
        
            # Initialize variables
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
                print(f"   ❌ Error during resource discovery: {discovery_error}")
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
        
            self.log_operation('INFO', f"📊 {account_name} ({region}) summary:")
            self.log_operation('INFO', f"   💻 Instances: {len(instances)}")
            self.log_operation('INFO', f"   🛡️  Total Security Groups: {len(security_groups)}")
            self.log_operation('INFO', f"   📎 Attached SGs: {len(attached_sgs)}")
            self.log_operation('INFO', f"   🔓 Unattached SGs: {len(unattached_sgs)}")
            
            print(f"   📊 Resources found: {len(instances)} instances, {len(security_groups)} security groups")
            print(f"   📎 Attached SGs: {len(attached_sgs)}, 🔓 Unattached SGs: {len(unattached_sgs)}")
        
            if not instances and not security_groups:
                self.log_operation('INFO', f"No resources found in {account_name} ({region})")
                print(f"   ✅ No resources to clean up in {region}")
                return True
        
            # Step 1: Terminate all instances sequentially
            if instances:
                self.log_operation('INFO', f"🗑️  Terminating {len(instances)} instances in {account_name} ({region}) sequentially")
                print(f"\n   🗑️  Terminating {len(instances)} instances sequentially...")
                
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
                        print(f"   ❌ Error terminating instance {instance_id}: {e}")
                
                print(f"   ✅ Terminated {terminated_count} instances, ❌ Failed: {failed_count}")
                
                # Wait for instances to start terminating
                if attached_sgs and terminated_count > 0:
                    self.log_operation('INFO', f"⏳ Waiting 60 seconds for {terminated_count} instances to start terminating...")
                    print(f"   ⏳ Waiting 60 seconds for instances to start terminating...")
                    time.sleep(60)
        
            # Step 2: Delete unattached security groups first
            if unattached_sgs:
                self.log_operation('INFO', f"🗑️  Deleting {len(unattached_sgs)} unattached security groups in {account_name} ({region})")
                print(f"\n   🗑️  Deleting {len(unattached_sgs)} unattached security groups...")
                
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
                        print(f"   ❌ Error deleting security group {sg_id}: {e}")
                
                print(f"   ✅ Deleted {sg_success} unattached security groups, ❌ Failed: {sg_failed}")
        
            # Step 3: Delete attached security groups with multiple passes for cross-references
            if attached_sgs:
                self.log_operation('INFO', f"🗑️  Deleting {len(attached_sgs)} attached security groups in {account_name} ({region})")
                print(f"\n   🗑️  Deleting {len(attached_sgs)} attached security groups...")
                
                max_retries = 5  # Increased retries for cross-references
                retry_delay = 30  # Reduced delay between retries
                
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
                                self.log_operation('INFO', f"✅ Deleted {sg_id} in attempt {retry + 1}")
                            else:
                                still_remaining.append(sg)
                                self.log_operation('WARNING', f"⏳ {sg_id} still has dependencies, will retry")
                        except Exception as e:
                            self.log_operation('ERROR', f"Error deleting attached security group {sg_id}: {e}")
                            print(f"   ❌ Error deleting security group {sg_id}: {e}")
                            still_remaining.append(sg)
                    
                    self.log_operation('INFO', f"Attempt {retry + 1} results: {sgs_deleted_this_round} deleted, {len(still_remaining)} remaining")
                    print(f"   ✅ Deleted {sgs_deleted_this_round} security groups in attempt {retry + 1}, {len(still_remaining)} remaining")
                    
                    # Update remaining list
                    remaining_sgs = still_remaining
                    
                    if not remaining_sgs:
                        self.log_operation('INFO', f"✅ All attached security groups deleted in {account_name} ({region})")
                        print(f"   ✅ All attached security groups deleted successfully!")
                        break
                    
                    # If no progress was made and we have remaining groups, try clearing rules again
                    if sgs_deleted_this_round == 0 and remaining_sgs and retry < max_retries - 1:
                        self.log_operation('INFO', f"🧹 No progress made, re-clearing rules for remaining {len(remaining_sgs)} security groups")
                        print(f"   🧹 No progress made, re-clearing rules for remaining security groups...")
                        
                        for sg in remaining_sgs:
                            try:
                                self.clear_security_group_rules(ec2_client, sg['group_id'])
                            except Exception as e:
                                self.log_operation('ERROR', f"Error re-clearing rules for {sg['group_id']}: {e}")
                    
                    if retry < max_retries - 1 and remaining_sgs:
                        self.log_operation('INFO', f"⏳ Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                        print(f"   ⏳ Waiting {retry_delay}s before next retry...")
                        time.sleep(retry_delay)
                
                if remaining_sgs:
                    self.log_operation('WARNING', f"⚠️  {len(remaining_sgs)} security groups could not be deleted after {max_retries} retries")
                    print(f"   ⚠️  {len(remaining_sgs)} security groups could not be deleted after {max_retries} retries")
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
            
            self.log_operation('INFO', f"✅ Cleanup completed for {account_name} ({region})")
            print(f"\n   ✅ Cleanup completed for {account_name} ({region})")
            return True
        
        except Exception as e:
            self.log_operation('ERROR', f"Error cleaning up {account_name} ({region}): {e}")
            print(f"   ❌ Error cleaning up {account_name} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return False

    def parse_selection(self, selection: str, max_count: int) -> list:
        """Parse user selection string into list of indices"""
        selected_indices = set()
        
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_count:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_count})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                # Handle single number
                try:
                    num = int(part)
                    if num < 1 or num > max_count:
                        raise ValueError(f"Selection {num} is out of bounds (1-{max_count})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid selection: {part}")
        
        return sorted(list(selected_indices))

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_dir = "aws/ec2/reports"
            os.makedirs(report_dir, exist_ok=True)
            report_filename = f"{report_dir}/ultra_ec2_cleanup_report_{self.execution_timestamp}.json"
            
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
            
            self.log_operation('INFO', f"✅ Ultra cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save ultra cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA EC2 CLEANUP SESSION 🚨")
            
            print("🚨" * 30)
            print("💥 ULTRA EC2 CLEANUP - SEQUENTIAL 💥")
            print("🚨" * 30)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📋 Log File: {self.log_filename}")
            
            # STEP 1: Display available accounts and select accounts to process
            accounts = self.config_data['accounts']
            
            print(f"\n🏦 AVAILABLE AWS ACCOUNTS:")
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
            
            selection = input("\n🔢 Select accounts to process: ").strip().lower()
            
            if selection in ['cancel', 'quit']:
                self.log_operation('INFO', "EC2 cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Process account selection
            selected_accounts = {}
            if not selection or selection == 'all':
                selected_accounts = accounts
                self.log_operation('INFO', f"All accounts selected: {len(accounts)}")
                print(f"✅ Selected all {len(accounts)} accounts")
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
                    print(f"✅ Selected {len(selected_accounts)} accounts: {', '.join(selected_accounts.keys())}")
                    
                except ValueError as e:
                    self.log_operation('ERROR', f"Invalid account selection: {e}")
                    print(f"❌ Invalid selection: {e}")
                    return
            
            regions = self.user_regions
            
            # STEP 2: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(regions)
            
            print(f"\n🎯 CLEANUP CONFIGURATION")
            print("=" * 80)
            print(f"🏦 Selected accounts: {len(selected_accounts)}")
            print(f"🌍 Regions per account: {len(regions)}")
            print(f"📋 Total operations: {total_operations}")
            print("=" * 80)
            
            # Simplified confirmation process
            print(f"\n⚠️  WARNING: This will delete ALL EC2 instances and security groups")
            print(f"    across {len(selected_accounts)} accounts in {len(regions)} regions ({total_operations} operations)")
            print(f"    This action CANNOT be undone!")
            
            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")
            
            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")
            
            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra cleanup cancelled at final confirmation")
                print("❌ Cleanup cancelled")
                return
            
            # STEP 3: Start the cleanup sequentially
            print(f"\n💥 STARTING CLEANUP...")
            self.log_operation('INFO', f"🚨 CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(regions)} regions")
            
            start_time = time.time()
            
            successful_tasks = 0
            failed_tasks = 0
            
            # Create tasks list
            tasks = []
            for account_name, account_data in selected_accounts.items():
                for region in regions:
                    tasks.append((account_name, account_data, region))
            
            # Process each task sequentially
            for i, (account_name, account_data, region) in enumerate(tasks, 1):
                print(f"\n[{i}/{len(tasks)}] Processing {account_name} in {region}...")
                
                try:
                    success = self.cleanup_account_region(account_name, account_data, region)
                    if success:
                        successful_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    self.log_operation('ERROR', f"Task failed for {account_name} ({region}): {e}")
                    print(f"❌ Task failed for {account_name} ({region}): {e}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # STEP 4: Display final results
            print(f"\n💥" + "="*25 + " CLEANUP COMPLETE " + "="*25)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"✅ Successful operations: {successful_tasks}")
            print(f"❌ Failed operations: {failed_tasks}")
            print(f"💻 Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            print(f"🛡️  Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            print(f"⏭️  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            print(f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            self.log_operation('INFO', f"CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            self.log_operation('INFO', f"Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            
            # STEP 5: Show account summary
            if self.cleanup_results['deleted_instances'] or self.cleanup_results['deleted_security_groups']:
                print(f"\n📊 Deletion Summary by Account:")
                
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
                    print(f"   🏦 {account}:")
                    print(f"      💻 Instances: {summary['instances']}")
                    print(f"      🛡️  Security Groups: {summary['security_groups']}")
                    print(f"      🌍 Regions: {regions_list}")
            
            # STEP 6: Show failures if any
            if self.cleanup_results['failed_deletions']:
                print(f"\n❌ Failed Deletions:")
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
                print(f"✅ Cleanup report saved to: {report_file}")
            
            print(f"✅ Session log saved to: {self.log_filename}")
            
            print(f"\n💥 CLEANUP COMPLETE! 💥")
            print("🚨" * 30)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            print(f"\n❌ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise

def main():
    """Main function"""
    try:
        manager = UltraEC2CleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()