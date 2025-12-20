#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError

# Import the credential manager
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager

class UltraCleanupCustomVPCManager:
    def __init__(self):
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize credential manager
        self.credential_manager = AWSCredentialManager()
        
        # Initialize log file
        self.setup_detailed_logging()
        
        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_vpcs': [],
            'deleted_dependencies': {
                'subnets': [],
                'internet_gateways': [],
                'nat_gateways': [],
                'route_tables': [],
                'network_acls': [],
                'security_groups': [],
                'vpc_endpoints': [],
                'elastic_ips': [],
                'network_interfaces': []
            },
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/vpc"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/vpc directory
            self.log_filename = f"{log_dir}/ultra_vpc_cleanup_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_vpc_cleanup')
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
            self.operation_logger.info("[ALERT] ULTRA CUSTOM VPC CLEANUP SESSION STARTED [ALERT]")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
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

    def create_vpc_client(self, credentials, region):
        """Create VPC client using account credentials"""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key'],
                region_name=region
            )
            
            # Test the connection
            ec2_client.describe_regions(RegionNames=[region])
            return ec2_client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create VPC client for {region}: {e}")
            raise

    def get_custom_vpcs(self, ec2_client, region, account_name):
        """Get all custom VPCs (non-default) in a region"""
        try:
            vpcs = []
            
            self.log_operation('INFO', f"[SCAN] Scanning for custom VPCs in {region} ({account_name})")
            print(f"   [SCAN] Scanning for custom VPCs in {region} ({account_name})...")
            
            response = ec2_client.describe_vpcs()
            
            for vpc in response['Vpcs']:
                vpc_id = vpc['VpcId']
                is_default = vpc.get('IsDefault', False)
                state = vpc.get('State', 'unknown')
                cidr_block = vpc.get('CidrBlock', 'unknown')
                
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
                    'vpc_name': vpc_name,
                    'state': state,
                    'cidr_block': cidr_block,
                    'is_default': is_default,
                    'region': region,
                    'account_name': account_name,
                    'tags': vpc.get('Tags', [])
                }
                
                vpcs.append(vpc_info)
            
            self.log_operation('INFO', f"🏗️  Found {len(vpcs)} custom VPCs in {region} ({account_name})")
            print(f"   🏗️  Found {len(vpcs)} custom VPCs in {region} ({account_name})")
            
            return vpcs
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting custom VPCs in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting custom VPCs in {region}: {e}")
            return []

    def get_vpc_dependencies(self, ec2_client, vpc_id):
        """Get all dependencies for a VPC"""
        dependencies = {
            'subnets': [],
            'internet_gateways': [],
            'nat_gateways': [],
            'route_tables': [],
            'network_acls': [],
            'security_groups': [],
            'vpc_endpoints': [],
            'network_interfaces': [],
            'elastic_ips': []
        }
        
        try:
            # Get subnets
            subnet_response = ec2_client.describe_subnets(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            dependencies['subnets'] = subnet_response['Subnets']
            
            # Get internet gateways
            igw_response = ec2_client.describe_internet_gateways(
                Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
            )
            dependencies['internet_gateways'] = igw_response['InternetGateways']
            
            # Get NAT gateways
            nat_response = ec2_client.describe_nat_gateways(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            dependencies['nat_gateways'] = nat_response['NatGateways']
            
            # Get route tables (excluding main route table)
            rt_response = ec2_client.describe_route_tables(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            # Filter out main route table
            dependencies['route_tables'] = [
                rt for rt in rt_response['RouteTables']
                if not any(assoc.get('Main', False) for assoc in rt.get('Associations', []))
            ]
            
            # Get network ACLs (excluding default)
            nacl_response = ec2_client.describe_network_acls(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            # Filter out default ACL
            dependencies['network_acls'] = [
                nacl for nacl in nacl_response['NetworkAcls']
                if not nacl.get('IsDefault', False)
            ]
            
            # Get security groups (excluding default)
            sg_response = ec2_client.describe_security_groups(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            dependencies['security_groups'] = [
                sg for sg in sg_response['SecurityGroups']
                if sg['GroupName'] != 'default'
            ]
            
            # Get VPC endpoints
            try:
                endpoint_response = ec2_client.describe_vpc_endpoints(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )
                dependencies['vpc_endpoints'] = endpoint_response['VpcEndpoints']
            except Exception as e:
                self.log_operation('WARNING', f"Could not get VPC endpoints: {e}")
            
            # Get network interfaces
            eni_response = ec2_client.describe_network_interfaces(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            # Filter out interfaces attached to instances (they'll be deleted with instances)
            dependencies['network_interfaces'] = [
                eni for eni in eni_response['NetworkInterfaces']
                if not eni.get('Attachment', {}).get('InstanceId')
            ]
            
            # Get elastic IPs associated with VPC
            eip_response = ec2_client.describe_addresses(
                Filters=[{'Name': 'domain', 'Values': ['vpc']}]
            )
            # Filter for this VPC's EIPs
            vpc_eips = []
            for eip in eip_response['Addresses']:
                if eip.get('NetworkInterfaceId'):
                    # Check if the network interface belongs to this VPC
                    for eni in eni_response['NetworkInterfaces']:
                        if eni['NetworkInterfaceId'] == eip['NetworkInterfaceId']:
                            vpc_eips.append(eip)
                            break
            dependencies['elastic_ips'] = vpc_eips
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting VPC dependencies for {vpc_id}: {e}")
        
        return dependencies

    def cleanup_vpc_dependencies(self, ec2_client, vpc_id, vpc_name):
        """Clean up all VPC dependencies in the correct order"""
        self.log_operation('INFO', f"[CLEANUP] Cleaning VPC dependencies for {vpc_id} ({vpc_name})")
        print(f"   [CLEANUP] Cleaning VPC dependencies for {vpc_id} ({vpc_name})...")
        
        dependencies = self.get_vpc_dependencies(ec2_client, vpc_id)
        cleanup_success = True
        
        # Step 1: Delete VPC endpoints
        for endpoint in dependencies['vpc_endpoints']:
            try:
                endpoint_id = endpoint['VpcEndpointId']
                self.log_operation('INFO', f"   Deleting VPC endpoint {endpoint_id}")
                ec2_client.delete_vpc_endpoint(VpcEndpointId=endpoint_id)
                self.cleanup_results['deleted_dependencies']['vpc_endpoints'].append({
                    'endpoint_id': endpoint_id,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete VPC endpoint {endpoint_id}: {e}")
                cleanup_success = False
        
        # Step 2: Release elastic IPs
        for eip in dependencies['elastic_ips']:
            try:
                allocation_id = eip.get('AllocationId')
                public_ip = eip.get('PublicIp')
                if allocation_id:
                    self.log_operation('INFO', f"   Releasing elastic IP {public_ip} ({allocation_id})")
                    ec2_client.release_address(AllocationId=allocation_id)
                    self.cleanup_results['deleted_dependencies']['elastic_ips'].append({
                        'allocation_id': allocation_id,
                        'public_ip': public_ip,
                        'vpc_id': vpc_id,
                        'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to release elastic IP {public_ip}: {e}")
                cleanup_success = False
        
        # Step 3: Delete network interfaces
        for eni in dependencies['network_interfaces']:
            try:
                eni_id = eni['NetworkInterfaceId']
                # Detach if attached
                if eni.get('Attachment'):
                    attachment_id = eni['Attachment'].get('AttachmentId')
                    if attachment_id:
                        self.log_operation('INFO', f"   Detaching network interface {eni_id}")
                        ec2_client.detach_network_interface(AttachmentId=attachment_id, Force=True)
                        time.sleep(5)
                
                self.log_operation('INFO', f"   Deleting network interface {eni_id}")
                ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
                self.cleanup_results['deleted_dependencies']['network_interfaces'].append({
                    'interface_id': eni_id,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete network interface {eni_id}: {e}")
                cleanup_success = False
        
        # Step 4: Delete NAT gateways and wait for deletion
        nat_gateway_ids = []
        for nat in dependencies['nat_gateways']:
            try:
                nat_id = nat['NatGatewayId']
                state = nat.get('State', 'unknown')
                
                if state not in ['deleted', 'deleting']:
                    self.log_operation('INFO', f"   Deleting NAT gateway {nat_id}")
                    ec2_client.delete_nat_gateway(NatGatewayId=nat_id)
                    nat_gateway_ids.append(nat_id)
                    self.cleanup_results['deleted_dependencies']['nat_gateways'].append({
                        'nat_gateway_id': nat_id,
                        'vpc_id': vpc_id,
                        'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete NAT gateway {nat_id}: {e}")
                cleanup_success = False
        
        # Wait for NAT gateways to be deleted
        if nat_gateway_ids:
            self.log_operation('INFO', f"   Waiting for {len(nat_gateway_ids)} NAT gateways to be deleted...")
            self.wait_for_nat_gateways_deletion(ec2_client, nat_gateway_ids)
        
        # Step 5: Delete subnets
        for subnet in dependencies['subnets']:
            try:
                subnet_id = subnet['SubnetId']
                self.log_operation('INFO', f"   Deleting subnet {subnet_id}")
                ec2_client.delete_subnet(SubnetId=subnet_id)
                self.cleanup_results['deleted_dependencies']['subnets'].append({
                    'subnet_id': subnet_id,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete subnet {subnet_id}: {e}")
                cleanup_success = False
        
        # Step 6: Delete security groups (clear rules first)
        for sg in dependencies['security_groups']:
            try:
                sg_id = sg['GroupId']
                sg_name = sg['GroupName']
                
                # Clear security group rules first
                self.clear_security_group_rules(ec2_client, sg_id)
                
                self.log_operation('INFO', f"   Deleting security group {sg_id} ({sg_name})")
                ec2_client.delete_security_group(GroupId=sg_id)
                self.cleanup_results['deleted_dependencies']['security_groups'].append({
                    'group_id': sg_id,
                    'group_name': sg_name,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete security group {sg_id}: {e}")
                cleanup_success = False
        
        # Step 7: Delete route tables
        for rt in dependencies['route_tables']:
            try:
                rt_id = rt['RouteTableId']
                self.log_operation('INFO', f"   Deleting route table {rt_id}")
                ec2_client.delete_route_table(RouteTableId=rt_id)
                self.cleanup_results['deleted_dependencies']['route_tables'].append({
                    'route_table_id': rt_id,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete route table {rt_id}: {e}")
                cleanup_success = False
        
        # Step 8: Delete network ACLs
        for nacl in dependencies['network_acls']:
            try:
                nacl_id = nacl['NetworkAclId']
                self.log_operation('INFO', f"   Deleting network ACL {nacl_id}")
                ec2_client.delete_network_acl(NetworkAclId=nacl_id)
                self.cleanup_results['deleted_dependencies']['network_acls'].append({
                    'network_acl_id': nacl_id,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete network ACL {nacl_id}: {e}")
                cleanup_success = False
        
        # Step 9: Detach and delete internet gateways
        for igw in dependencies['internet_gateways']:
            try:
                igw_id = igw['InternetGatewayId']
                
                # Detach from VPC first
                self.log_operation('INFO', f"   Detaching internet gateway {igw_id} from VPC {vpc_id}")
                ec2_client.detach_internet_gateway(
                    InternetGatewayId=igw_id,
                    VpcId=vpc_id
                )
                time.sleep(5)
                
                # Delete the internet gateway
                self.log_operation('INFO', f"   Deleting internet gateway {igw_id}")
                ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
                self.cleanup_results['deleted_dependencies']['internet_gateways'].append({
                    'internet_gateway_id': igw_id,
                    'vpc_id': vpc_id,
                    'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                time.sleep(2)
            except Exception as e:
                self.log_operation('WARNING', f"   Failed to delete internet gateway {igw_id}: {e}")
                cleanup_success = False
        
        total_dependencies = sum(len(deps) for deps in dependencies.values())
        self.log_operation('INFO', f"   Deleted {total_dependencies} dependencies, waiting 30 seconds for cleanup...")
        if total_dependencies > 0:
            time.sleep(30)
        
        return cleanup_success

    def wait_for_nat_gateways_deletion(self, ec2_client, nat_gateway_ids, max_wait_time=300):
        """Wait for NAT gateways to be deleted"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                response = ec2_client.describe_nat_gateways(NatGatewayIds=nat_gateway_ids)
                
                active_gateways = [
                    gw for gw in response['NatGateways']
                    if gw['State'] not in ['deleted', 'deleting']
                ]
                
                if not active_gateways:
                    self.log_operation('INFO', f"   All NAT gateways deleted successfully")
                    return True
                
                self.log_operation('INFO', f"   Waiting for {len(active_gateways)} NAT gateways to be deleted...")
                time.sleep(15)
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidNatGatewayID.NotFound':
                    # All gateways are deleted
                    return True
                else:
                    self.log_operation('WARNING', f"Error checking NAT gateway status: {e}")
                    break
            except Exception as e:
                self.log_operation('WARNING', f"Error waiting for NAT gateways: {e}")
                break
        
        self.log_operation('WARNING', f"Timeout waiting for NAT gateways to be deleted")
        return False

    def clear_security_group_rules(self, ec2_client, sg_id):
        """Clear all security group rules"""
        try:
            response = ec2_client.describe_security_groups(GroupIds=[sg_id])
            sg_info = response['SecurityGroups'][0]
            
            # Clear ingress rules
            ingress_rules = sg_info.get('IpPermissions', [])
            if ingress_rules:
                ec2_client.revoke_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=ingress_rules
                )
            
            # Clear egress rules (but keep default allow-all if needed)
            egress_rules = sg_info.get('IpPermissionsEgress', [])
            non_default_egress = []
            for rule in egress_rules:
                # Keep default egress rule (all traffic to 0.0.0.0/0)
                is_default = (
                    rule.get('IpProtocol') == '-1' and
                    len(rule.get('IpRanges', [])) == 1 and
                    rule.get('IpRanges', [{}])[0].get('CidrIp') == '0.0.0.0/0'
                )
                if not is_default:
                    non_default_egress.append(rule)
            
            if non_default_egress:
                ec2_client.revoke_security_group_egress(
                    GroupId=sg_id,
                    IpPermissions=non_default_egress
                )
            
            return True
        except Exception as e:
            self.log_operation('WARNING', f"Failed to clear rules for security group {sg_id}: {e}")
            return False

    def delete_vpc(self, ec2_client, vpc_info, force_delete=True):
        """Delete a VPC after cleaning dependencies"""
        try:
            vpc_id = vpc_info['vpc_id']
            vpc_name = vpc_info['vpc_name']
            region = vpc_info['region']
            account_name = vpc_info['account_name']
            
            self.log_operation('INFO', f"[DELETE]  Deleting custom VPC {vpc_id} ({vpc_name}) in {region} ({account_name})")
            print(f"   [DELETE]  Deleting custom VPC {vpc_id} ({vpc_name})...")
            
            # Clean dependencies first
            if force_delete:
                dependencies_cleaned = self.cleanup_vpc_dependencies(ec2_client, vpc_id, vpc_name)
                if not dependencies_cleaned:
                    self.log_operation('WARNING', f"Some dependencies could not be cleaned for VPC {vpc_id}")
            
            # Attempt to delete the VPC
            self.log_operation('INFO', f"Attempting to delete VPC {vpc_id}")
            ec2_client.delete_vpc(VpcId=vpc_id)
            
            self.log_operation('INFO', f"[OK] Successfully deleted VPC {vpc_id} ({vpc_name})")
            print(f"   [OK] Successfully deleted VPC {vpc_id}")
            
            self.cleanup_results['deleted_vpcs'].append({
                'vpc_id': vpc_id,
                'vpc_name': vpc_name,
                'cidr_block': vpc_info['cidr_block'],
                'region': region,
                'account_name': account_name,
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidVpcID.NotFound':
                self.log_operation('INFO', f"VPC {vpc_id} does not exist")
                return True
            elif error_code == 'DependencyViolation':
                self.log_operation('WARNING', f"Cannot delete VPC {vpc_id}: dependency violation")
                print(f"   [WARN] Cannot delete VPC {vpc_id}: still has dependencies")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'vpc',
                    'resource_id': vpc_id,
                    'region': region,
                    'account_name': account_name,
                    'error': 'Dependency violation - still has dependencies'
                })
                return False
            else:
                self.log_operation('ERROR', f"Failed to delete VPC {vpc_id}: {e}")
                print(f"   [ERROR] Failed to delete VPC {vpc_id}: {e}")
                self.cleanup_results['failed_deletions'].append({
                    'resource_type': 'vpc',
                    'resource_id': vpc_id,
                    'region': region,
                    'account_name': account_name,
                    'error': str(e)
                })
                return False
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error deleting VPC {vpc_id}: {e}")
            print(f"   [ERROR] Unexpected error deleting VPC {vpc_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'vpc',
                'resource_id': vpc_id,
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_info, region):
        """Clean up custom VPCs in a specific account and region"""
        try:
            account_name = account_info['name']
            credentials = account_info['credentials']
            
            self.log_operation('INFO', f"[CLEANUP] Starting VPC cleanup for {account_name} in {region}")
            print(f"\n[CLEANUP] Starting VPC cleanup for {account_name} in {region}")
            
            # Create VPC client
            ec2_client = self.create_vpc_client(credentials, region)
            
            # Get custom VPCs
            vpcs = self.get_custom_vpcs(ec2_client, region, account_name)
            
            region_summary = {
                'account_name': account_name,
                'region': region,
                'vpcs_found': len(vpcs)
            }
            
            self.cleanup_results['regions_processed'].append(region_summary)
            
            self.log_operation('INFO', f"[STATS] {account_name} ({region}) summary:")
            self.log_operation('INFO', f"   🏗️  Custom VPCs: {len(vpcs)}")
            
            print(f"   [STATS] Resources found: {len(vpcs)} custom VPCs")
            
            if not vpcs:
                self.log_operation('INFO', f"No custom VPCs found in {account_name} ({region})")
                print(f"   [OK] No custom VPCs to clean up in {region}")
                return True
            
            # Delete VPCs with retries for dependency issues
            self.log_operation('INFO', f"[DELETE]  Deleting {len(vpcs)} custom VPCs in {account_name} ({region})")
            print(f"\n   [DELETE]  Deleting {len(vpcs)} custom VPCs...")
            
            max_retries = 4
            retry_delay = 30
            
            remaining_vpcs = vpcs.copy()
            
            for retry in range(max_retries):
                self.log_operation('INFO', f"🔄 VPC deletion attempt {retry + 1}/{max_retries}")
                print(f"   🔄 VPC deletion attempt {retry + 1}/{max_retries}")
                
                vpcs_deleted_this_round = 0
                still_remaining = []
                
                for i, vpc in enumerate(remaining_vpcs, 1):
                    vpc_id = vpc['vpc_id']
                    print(f"   [{i}/{len(remaining_vpcs)}] Trying to delete VPC {vpc_id}...")
                    
                    try:
                        success = self.delete_vpc(ec2_client, vpc, force_delete=True)
                        if success:
                            vpcs_deleted_this_round += 1
                            self.log_operation('INFO', f"[OK] Deleted {vpc_id} in attempt {retry + 1}")
                        else:
                            still_remaining.append(vpc)
                            self.log_operation('WARNING', f"[WAIT] {vpc_id} still has dependencies, will retry")
                    except Exception as e:
                        self.log_operation('ERROR', f"Error deleting VPC {vpc_id}: {e}")
                        print(f"   [ERROR] Error deleting VPC {vpc_id}: {e}")
                        still_remaining.append(vpc)
                
                self.log_operation('INFO', f"Attempt {retry + 1} results: {vpcs_deleted_this_round} deleted, {len(still_remaining)} remaining")
                print(f"   [OK] Deleted {vpcs_deleted_this_round} VPCs in attempt {retry + 1}, {len(still_remaining)} remaining")
                
                remaining_vpcs = still_remaining
                
                if not remaining_vpcs:
                    self.log_operation('INFO', f"[OK] All custom VPCs deleted in {account_name} ({region})")
                    print(f"   [OK] All custom VPCs deleted successfully!")
                    break
                
                if retry < max_retries - 1 and remaining_vpcs:
                    self.log_operation('INFO', f"[WAIT] Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                    print(f"   [WAIT] Waiting {retry_delay}s before next retry...")
                    time.sleep(retry_delay)
                    retry_delay += 15  # Increase delay for subsequent retries
            
            if remaining_vpcs:
                self.log_operation('WARNING', f"[WARN]  {len(remaining_vpcs)} VPCs could not be deleted after {max_retries} retries")
                print(f"   [WARN]  {len(remaining_vpcs)} VPCs could not be deleted after {max_retries} retries")
                self.log_operation('WARNING', f"Remaining VPCs: {[vpc['vpc_id'] for vpc in remaining_vpcs]}")
            
            self.log_operation('INFO', f"[OK] VPC cleanup completed for {account_name} ({region})")
            print(f"\n   [OK] VPC cleanup completed for {account_name} ({region})")
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Error cleaning up VPCs in {account_name} ({region}): {e}")
            print(f"   [ERROR] Error cleaning up VPCs in {account_name} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_dir = "aws/vpc/reports"
            os.makedirs(report_dir, exist_ok=True)
            report_filename = f"{report_dir}/ultra_vpc_cleanup_report_{self.execution_timestamp}.json"
            
            # Calculate statistics
            total_vpcs_deleted = len(self.cleanup_results['deleted_vpcs'])
            total_dependencies_deleted = sum(
                len(deps) for deps in self.cleanup_results['deleted_dependencies'].values()
            )
            total_failed = len(self.cleanup_results['failed_deletions'])
            
            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for vpc in self.cleanup_results['deleted_vpcs']:
                account = vpc['account_name']
                region = vpc['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = 0
                deletions_by_account[account] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = 0
                deletions_by_region[region] += 1
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_VPC_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "log_file": self.log_filename
                },
                "summary": {
                    "total_accounts_processed": len(set(rp['account_name'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_vpcs_deleted": total_vpcs_deleted,
                    "total_dependencies_deleted": total_dependencies_deleted,
                    "total_failed_deletions": total_failed,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region,
                    "dependency_breakdown": {
                        dep_type: len(deps) for dep_type, deps in self.cleanup_results['deleted_dependencies'].items()
                    }
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_vpcs": self.cleanup_results['deleted_vpcs'],
                    "deleted_dependencies": self.cleanup_results['deleted_dependencies'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"[OK] VPC cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"[ERROR] Failed to save VPC cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.log_operation('INFO', "[ALERT] STARTING ULTRA CUSTOM VPC CLEANUP SESSION [ALERT]")
            
            print("[ALERT]" * 30)
            print("[BOOM] ULTRA CUSTOM VPC CLEANUP [BOOM]")
            print("[ALERT]" * 30)
            print(f"[DATE] Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"[LIST] Log File: {self.log_filename}")
            
            # Get account credentials using the credential manager
            print(f"\n[LOCKED] Loading AWS account credentials...")
            accounts = self.credential_manager.get_interactive_accounts_selection()
            
            if not accounts:
                self.log_operation('INFO', "No accounts selected for cleanup")
                print("[ERROR] No accounts selected")
                return
            
            # Get regions (using common AWS regions)
            regions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']
            
            # Calculate total operations
            total_operations = len(accounts) * len(regions)
            
            print(f"\n[TARGET] CLEANUP CONFIGURATION")
            print("=" * 80)
            print(f"[BANK] Selected accounts: {len(accounts)}")
            for account in accounts:
                print(f"   • {account['name']}")
            print(f"[REGION] Regions per account: {len(regions)}")
            print(f"[LIST] Total operations: {total_operations}")
            print("=" * 80)
            
            # Confirmation
            print(f"\n[WARN]  WARNING: This will delete ALL custom VPCs and their dependencies")
            print(f"    across {len(accounts)} accounts in {len(regions)} regions")
            print(f"    This includes subnets, route tables, internet gateways, NAT gateways, etc.")
            print(f"    This action CANNOT be undone!")
            
            confirm1 = input(f"\nContinue with VPC cleanup? (y/n): ").strip().lower()
            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "VPC cleanup cancelled by user")
                print("[ERROR] Cleanup cancelled")
                return
            
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            if confirm2 != 'yes':
                self.log_operation('INFO', "VPC cleanup cancelled at final confirmation")
                print("[ERROR] Cleanup cancelled")
                return
            
            # Start cleanup
            print(f"\n[BOOM] STARTING VPC CLEANUP...")
            self.log_operation('INFO', f"[ALERT] VPC CLEANUP INITIATED - {len(accounts)} accounts, {len(regions)} regions")
            
            start_time = time.time()
            successful_tasks = 0
            failed_tasks = 0
            
            # Process each account and region
            task_count = 0
            total_tasks = len(accounts) * len(regions)
            
            for account in accounts:
                for region in regions:
                    task_count += 1
                    print(f"\n[{task_count}/{total_tasks}] Processing {account['name']} in {region}...")
                    
                    try:
                        success = self.cleanup_account_region(account, region)
                        if success:
                            successful_tasks += 1
                        else:
                            failed_tasks += 1
                    except Exception as e:
                        failed_tasks += 1
                        self.log_operation('ERROR', f"Task failed for {account['name']} ({region}): {e}")
                        print(f"[ERROR] Task failed for {account['name']} ({region}): {e}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # Display final results
            print(f"\n[BOOM]" + "="*25 + " CLEANUP COMPLETE " + "="*25)
            print(f"[TIMER]  Total execution time: {total_time} seconds")
            print(f"[OK] Successful operations: {successful_tasks}")
            print(f"[ERROR] Failed operations: {failed_tasks}")
            print(f"🏗️  Custom VPCs deleted: {len(self.cleanup_results['deleted_vpcs'])}")
            
            # Show dependency breakdown
            total_dependencies = sum(len(deps) for deps in self.cleanup_results['deleted_dependencies'].values())
            print(f"[CLEANUP] Total dependencies deleted: {total_dependencies}")
            for dep_type, deps in self.cleanup_results['deleted_dependencies'].items():
                if deps:
                    print(f"   • {dep_type.replace('_', ' ').title()}: {len(deps)}")
            
            print(f"[ERROR] Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            # Show account summary
            if self.cleanup_results['deleted_vpcs']:
                print(f"\n[STATS] VPC Deletion Summary by Account:")
                account_summary = {}
                for vpc in self.cleanup_results['deleted_vpcs']:
                    account = vpc['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'vpcs': 0, 'regions': set()}
                    account_summary[account]['vpcs'] += 1
                    account_summary[account]['regions'].add(vpc['region'])
                
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    print(f"   [BANK] {account}: {summary['vpcs']} VPCs in {regions_list}")
            
            # Show failures if any
            if self.cleanup_results['failed_deletions']:
                print(f"\n[ERROR] Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:
                    print(f"   • {failure['resource_type']} {failure['resource_id']} in {failure['account_name']} ({failure['region']})")
                    print(f"     Error: {failure['error']}")
                
                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    print(f"   ... and {remaining} more failures (see detailed report)")
            
            # Save report
            print(f"\n[FILE] Saving VPC cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                print(f"[OK] VPC cleanup report saved to: {report_file}")
            
            print(f"[OK] Session log saved to: {self.log_filename}")
            print(f"\n[BOOM] VPC CLEANUP COMPLETE! [BOOM]")
            print("[ALERT]" * 30)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in VPC cleanup execution: {str(e)}")
            print(f"\n[ERROR] FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise

def main():
    """Main function"""
    try:
        manager = UltraCleanupCustomVPCManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] VPC cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()