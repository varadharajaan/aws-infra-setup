#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed

class AWSDefaultVPCChecker:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        self.load_configuration()
        
        # Regional subnet rules
        self.regional_rules = {
            'us-east-1': {'min_subnets': 2, 'max_subnets': 6},  # 6 AZs available
            'default': {'min_subnets': 2, 'max_subnets': 3}     # Other regions
        }
        
    def load_configuration(self):
        """Load AWS account configurations from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.aws_accounts = config['accounts']
            self.user_settings = config.get('user_settings', {})
            self.check_regions = self.user_settings.get('user_regions', [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
            ])
            
            print(f"[OK] Configuration loaded from: {self.config_file}")
            print(f"[STATS] Found {len(self.aws_accounts)} AWS accounts: {list(self.aws_accounts.keys())}")
            print(f"[REGION] Will check {len(self.check_regions)} regions: {self.check_regions}")
            
        except FileNotFoundError as e:
            print(f"[ERROR] Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Error loading configuration: {e}")
            sys.exit(1)

    def get_regional_rules(self, region):
        """Get subnet rules for a specific region"""
        return self.regional_rules.get(region, self.regional_rules['default'])

    def create_clients(self, account_name, region):
        """Create AWS clients for a specific account and region"""
        if account_name not in self.aws_accounts:
            raise ValueError(f"Account {account_name} not found in configurations")
        
        account_config = self.aws_accounts[account_name]
        
        try:
            session = boto3.Session(
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name=region
            )
            
            ec2_client = session.client('ec2')
            
            # Test the connection
            ec2_client.describe_vpcs(MaxResults=5)
            
            return ec2_client, account_config
            
        except ClientError as e:
            error_msg = f"AWS Error in {region}: {e}"
            return None, error_msg
        except Exception as e:
            error_msg = f"Connection failed in {region}: {e}"
            return None, error_msg

    def check_default_vpc_exists(self, ec2_client):
        """Check if default VPC exists and get its details"""
        try:
            response = ec2_client.describe_vpcs(
                Filters=[
                    {'Name': 'isDefault', 'Values': ['true']}
                ]
            )
            
            if response['Vpcs']:
                vpc = response['Vpcs'][0]
                return True, vpc
            else:
                return False, None
                
        except Exception as e:
            return False, f"Error checking VPC: {e}"

    def check_default_subnets(self, ec2_client, vpc_id):
        """Check default subnets in the VPC"""
        try:
            response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'defaultForAz', 'Values': ['true']}
                ]
            )
            
            subnets = response['Subnets']
            subnet_details = []
            
            for subnet in subnets:
                subnet_info = {
                    'subnet_id': subnet['SubnetId'],
                    'availability_zone': subnet['AvailabilityZone'],
                    'cidr_block': subnet['CidrBlock'],
                    'auto_assign_public_ip': subnet.get('MapPublicIpOnLaunch', False),
                    'state': subnet['State']
                }
                subnet_details.append(subnet_info)
            
            return len(subnets), subnet_details
            
        except Exception as e:
            return 0, f"Error checking subnets: {e}"

    def check_internet_gateway(self, ec2_client, vpc_id):
        """Check if VPC has an Internet Gateway attached"""
        try:
            response = ec2_client.describe_internet_gateways(
                Filters=[
                    {'Name': 'attachment.vpc-id', 'Values': [vpc_id]}
                ]
            )
            
            if response['InternetGateways']:
                igw = response['InternetGateways'][0]
                return True, {
                    'igw_id': igw['InternetGatewayId'],
                    'state': igw['Attachments'][0]['State'] if igw['Attachments'] else 'unknown'
                }
            else:
                return False, None
                
        except Exception as e:
            return False, f"Error checking IGW: {e}"

    def check_route_tables_and_routes(self, ec2_client, vpc_id, subnet_ids):
        """Check route tables and internet routes for subnets"""
        try:
            # Get all route tables in the VPC
            response = ec2_client.describe_route_tables(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]}
                ]
            )
            
            route_tables = response['RouteTables']
            route_analysis = []
            
            for rt in route_tables:
                rt_info = {
                    'route_table_id': rt['RouteTableId'],
                    'is_main': False,
                    'associated_subnets': [],
                    'has_internet_route': False,
                    'internet_route_target': None,
                    'routes': []
                }
                
                # Check if it's the main route table
                for assoc in rt.get('Associations', []):
                    if assoc.get('Main', False):
                        rt_info['is_main'] = True
                    elif 'SubnetId' in assoc:
                        rt_info['associated_subnets'].append(assoc['SubnetId'])
                
                # Check routes
                for route in rt.get('Routes', []):
                    route_info = {
                        'destination': route.get('DestinationCidrBlock', route.get('DestinationIpv6CidrBlock', 'N/A')),
                        'target': route.get('GatewayId', route.get('InstanceId', route.get('NetworkInterfaceId', 'local'))),
                        'state': route.get('State', 'unknown')
                    }
                    rt_info['routes'].append(route_info)
                    
                    # Check for internet route (0.0.0.0/0)
                    if route.get('DestinationCidrBlock') == '0.0.0.0/0':
                        rt_info['has_internet_route'] = True
                        rt_info['internet_route_target'] = route.get('GatewayId', 'unknown')
                
                route_analysis.append(rt_info)
            
            # Check which subnets have internet access
            subnet_internet_access = {}
            
            for subnet_id in subnet_ids:
                has_internet = False
                route_table_used = None
                
                # Find which route table this subnet uses
                for rt in route_analysis:
                    if subnet_id in rt['associated_subnets']:
                        # Subnet has explicit association
                        has_internet = rt['has_internet_route']
                        route_table_used = rt['route_table_id']
                        break
                
                # If no explicit association, it uses the main route table
                if route_table_used is None:
                    for rt in route_analysis:
                        if rt['is_main']:
                            has_internet = rt['has_internet_route']
                            route_table_used = rt['route_table_id']
                            break
                
                subnet_internet_access[subnet_id] = {
                    'has_internet_access': has_internet,
                    'route_table_id': route_table_used
                }
            
            return route_analysis, subnet_internet_access
            
        except Exception as e:
            return [], f"Error checking route tables: {e}"

    def validate_subnet_distribution(self, subnet_details, region):
        """Validate subnet distribution against regional rules"""
        if not isinstance(subnet_details, list):
            return False, "Invalid subnet details"
        
        rules = self.get_regional_rules(region)
        subnet_count = len(subnet_details)
        
        # Check count limits
        if subnet_count < rules['min_subnets']:
            return False, f"Insufficient subnets: {subnet_count} < {rules['min_subnets']} (minimum)"
        
        if subnet_count > rules['max_subnets']:
            return True, f"Excess subnets: {subnet_count} > {rules['max_subnets']} (maximum)"
        
        # Check AZ distribution (must be in different AZs)
        azs = [subnet['availability_zone'] for subnet in subnet_details]
        unique_azs = set(azs)
        
        if len(unique_azs) != len(azs):
            return False, f"Subnets not in different AZs: {len(unique_azs)} unique AZs for {len(azs)} subnets"
        
        return True, f"Valid distribution: {subnet_count} subnets in {len(unique_azs)} different AZs"

    def cleanup_excess_subnets(self, ec2_client, vpc_id, region):
        """Clean up excess subnets beyond regional limits"""
        try:
            rules = self.get_regional_rules(region)
            
            # Get current default subnets
            response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'defaultForAz', 'Values': ['true']}
                ]
            )
            
            subnets = response['Subnets']
            
            if len(subnets) <= rules['max_subnets']:
                return True, f"No cleanup needed: {len(subnets)} subnets within limit of {rules['max_subnets']}"
            
            # Sort subnets by AZ to maintain distribution
            subnets.sort(key=lambda x: x['AvailabilityZone'])
            
            # Identify subnets to delete (keep first max_subnets)
            subnets_to_keep = subnets[:rules['max_subnets']]
            subnets_to_delete = subnets[rules['max_subnets']:]
            
            cleanup_actions = []
            
            for subnet in subnets_to_delete:
                subnet_id = subnet['SubnetId']
                az = subnet['AvailabilityZone']
                
                try:
                    # 1. First, disassociate from route tables
                    rt_response = ec2_client.describe_route_tables(
                        Filters=[
                            {'Name': 'association.subnet-id', 'Values': [subnet_id]}
                        ]
                    )
                    
                    for rt in rt_response['RouteTables']:
                        for association in rt.get('Associations', []):
                            if association.get('SubnetId') == subnet_id:
                                assoc_id = association['RouteTableAssociationId']
                                ec2_client.disassociate_route_table(AssociationId=assoc_id)
                                cleanup_actions.append(f"Disassociated {subnet_id} from route table {rt['RouteTableId']}")
                    
                    # 2. Delete the subnet
                    ec2_client.delete_subnet(SubnetId=subnet_id)
                    cleanup_actions.append(f"Deleted excess subnet {subnet_id} in {az}")
                    
                except ClientError as e:
                    if 'DependencyViolation' in str(e):
                        cleanup_actions.append(f"Cannot delete {subnet_id}: has dependencies (instances/ENIs)")
                    else:
                        cleanup_actions.append(f"Failed to delete {subnet_id}: {e}")
            
            return True, cleanup_actions
            
        except Exception as e:
            return False, f"Error during cleanup: {e}"

    def check_account_region(self, account_name, region):
        """Check default VPC configuration for one account in one region"""
        try:
            # Create clients
            ec2_client, account_config = self.create_clients(account_name, region)
            
            if ec2_client is None:
                return {
                    'account': account_name,
                    'region': region,
                    'status': 'FAILED',
                    'error': account_config,  # This contains the error message
                    'checks': {}
                }
            
            result = {
                'account': account_name,
                'account_id': account_config['account_id'],
                'region': region,
                'status': 'SUCCESS',
                'checks': {}
            }
            
            # 1. Check Default VPC
            vpc_exists, vpc_details = self.check_default_vpc_exists(ec2_client)
            result['checks']['default_vpc'] = {
                'exists': vpc_exists,
                'details': vpc_details if vpc_exists else None
            }
            
            if not vpc_exists:
                result['status'] = 'NO_DEFAULT_VPC'
                return result
            
            vpc_id = vpc_details['VpcId']
            
            # 2. Check Default Subnets with regional validation
            subnet_count, subnet_details = self.check_default_subnets(ec2_client, vpc_id)
            is_valid_distribution, distribution_msg = self.validate_subnet_distribution(subnet_details, region)
            
            rules = self.get_regional_rules(region)
            result['checks']['default_subnets'] = {
                'count': subnet_count,
                'expected_min': rules['min_subnets'],
                'expected_max': rules['max_subnets'],
                'meets_requirement': subnet_count >= rules['min_subnets'],
                'within_limits': subnet_count <= rules['max_subnets'],
                'valid_distribution': is_valid_distribution,
                'distribution_message': distribution_msg,
                'details': subnet_details
            }
            
            # Extract subnet IDs for route checking
            subnet_ids = [subnet['subnet_id'] for subnet in subnet_details] if isinstance(subnet_details, list) else []
            
            # 3. Check Internet Gateway
            igw_exists, igw_details = self.check_internet_gateway(ec2_client, vpc_id)
            result['checks']['internet_gateway'] = {
                'exists': igw_exists,
                'details': igw_details if igw_exists else None
            }
            
            # 4. Check Route Tables and Internet Access
            route_analysis, subnet_internet_access = self.check_route_tables_and_routes(ec2_client, vpc_id, subnet_ids)
            result['checks']['routing'] = {
                'route_tables': route_analysis,
                'subnet_internet_access': subnet_internet_access
            }
            
            # 5. Overall Assessment with regional rules
            all_subnets_have_internet = all(
                access_info['has_internet_access'] 
                for access_info in subnet_internet_access.values()
            ) if subnet_internet_access else False
            
            all_subnets_auto_assign_ip = all(
                subnet['auto_assign_public_ip'] 
                for subnet in subnet_details if isinstance(subnet_details, list)
            ) if isinstance(subnet_details, list) else False
            
            result['checks']['overall_assessment'] = {
                'has_default_vpc': vpc_exists,
                'has_sufficient_subnets': subnet_count >= rules['min_subnets'],
                'within_subnet_limits': subnet_count <= rules['max_subnets'],
                'valid_subnet_distribution': is_valid_distribution,
                'has_internet_gateway': igw_exists,
                'all_subnets_have_internet_access': all_subnets_have_internet,
                'all_subnets_auto_assign_public_ip': all_subnets_auto_assign_ip,
                'fully_compliant': (
                    vpc_exists and 
                    subnet_count >= rules['min_subnets'] and
                    subnet_count <= rules['max_subnets'] and
                    is_valid_distribution and
                    igw_exists and 
                    all_subnets_have_internet and 
                    all_subnets_auto_assign_ip
                )
            }
            
            return result
            
        except Exception as e:
            return {
                'account': account_name,
                'region': region,
                'status': 'ERROR',
                'error': str(e),
                'checks': {}
            }

    def fix_missing_default_vpcs(self, results):
        """Create missing default VPCs and fix compliance issues"""
        print(f"\n[CONFIG] VPC REMEDIATION OPTIONS:")
        print(f"  1. Create missing default VPCs only")
        print(f"  2. Fix all compliance issues (VPCs + subnets + routing)")
        print(f"  3. Cancel")
        
        while True:
            try:
                choice = input(f"\n🔢 Select remediation option (1-3): ").strip()
                choice_num = int(choice)
                if 1 <= choice_num <= 3:
                    break
                else:
                    print("[ERROR] Invalid choice. Please enter 1, 2, or 3")
            except ValueError:
                print("[ERROR] Invalid input. Please enter a number.")
        
        if choice_num == 3:
            print("[ERROR] Remediation cancelled")
            return
        
        # Find issues to fix
        missing_vpcs = []
        compliance_issues = []
        
        for result in results:
            if result['status'] == 'NO_DEFAULT_VPC':
                missing_vpcs.append(result)
            elif result['status'] == 'SUCCESS':
                assessment = result['checks'].get('overall_assessment', {})
                if not assessment.get('fully_compliant', False):
                    compliance_issues.append(result)
        
        if choice_num == 1:
            issues_to_fix = missing_vpcs
            print(f"\n[TARGET] Will create {len(missing_vpcs)} missing default VPCs")
        else:
            issues_to_fix = missing_vpcs + compliance_issues
            print(f"\n[TARGET] Will fix {len(missing_vpcs)} missing VPCs and {len(compliance_issues)} compliance issues")
        
        if not issues_to_fix:
            print("[OK] No issues found to fix!")
            return
        
        # Show what will be fixed
        print(f"\n🔄 Starting remediation...")
        fixed_count = 0
        failed_count = 0

        for issue in issues_to_fix:
            try:
                account = issue['account']
                region = issue['region']
                
                print(f"   [CONFIG] Fixing {account} | {region}...")
                
                if issue['status'] == 'NO_DEFAULT_VPC':
                    success = self.create_default_vpc(account, region)
                else:
                    success = self.fix_vpc_compliance(account, region, issue)
                
                if success:
                    # Verify the fix
                    if self.verify_fixes(account, region):
                        fixed_count += 1
                        print(f"   [OK] {account} | {region} - Fixed and verified")
                    else:
                        failed_count += 1
                        print(f"   [WARN]  {account} | {region} - Partially fixed")
                else:
                    failed_count += 1
                    print(f"   [ERROR] {account} | {region} - Failed")
                    
            except Exception as e:
                failed_count += 1
                print(f"   [ERROR] {account} | {region} - Error: {e}")
        
        # Summary of remediation    
        print(f"\n[STATS] Remediation Summary:")
        print(f"   [OK] Fixed: {fixed_count}")
        print(f"   [ERROR] Failed: {failed_count}")

    def create_default_vpc(self, account_name, region):
        """Create default VPC in specified account and region"""
        try:
            ec2_client, _ = self.create_clients(account_name, region)
            if not ec2_client:
                return False
            
            response = ec2_client.create_default_vpc()
            vpc_id = response['Vpc']['VpcId']
            print(f"      🏗️  Created default VPC: {vpc_id}")
            return True
            
        except ClientError as e:
            if 'DefaultVpcAlreadyExists' in str(e):
                print(f"      [WARN]  Default VPC already exists")
                return True
            else:
                print(f"      [ERROR] AWS Error: {e}")
                return False
        except Exception as e:
            print(f"      [ERROR] Error: {e}")
            return False

    def fix_vpc_compliance(self, account_name, region, issue_result):
        """Fix VPC compliance issues with regional rules"""
        try:
            ec2_client, _ = self.create_clients(account_name, region)
            if not ec2_client:
                return False
            
            checks = issue_result['checks']
            vpc_id = checks['default_vpc']['details']['VpcId']
            fixed_items = []
            rules = self.get_regional_rules(region)
            
            # 1. Handle subnet count and distribution FIRST
            subnet_check = checks.get('default_subnets', {})
            current_count = subnet_check.get('count', 0)
            
            # Check if we need to clean up excess subnets
            if current_count > rules['max_subnets']:
                print(f"      [CLEANUP] Cleaning up excess subnets: {current_count} > {rules['max_subnets']}")
                cleanup_success, cleanup_result = self.cleanup_excess_subnets(ec2_client, vpc_id, region)
                
                if cleanup_success:
                    if isinstance(cleanup_result, list):
                        fixed_items.extend(cleanup_result)
                    else:
                        fixed_items.append(cleanup_result)
                else:
                    print(f"      [ERROR] Cleanup failed: {cleanup_result}")
                    return False
            
            # Re-check subnet count after cleanup
            updated_count, updated_details = self.check_default_subnets(ec2_client, vpc_id)
            
            # Skip creating new subnets if we have adequate coverage
            if updated_count >= rules['min_subnets']:
                # Validate AZ distribution
                is_valid, msg = self.validate_subnet_distribution(updated_details, region)
                if is_valid:
                    fixed_items.append(f"Adequate subnet coverage: {updated_count} subnets in different AZs")
                else:
                    fixed_items.append(f"Subnet distribution issue: {msg}")
            else:
                # Need to create more subnets
                needed_subnets = rules['min_subnets'] - updated_count
                fixed_items.append(f"Need to create {needed_subnets} additional subnets")
            
            # 2. Handle Internet Gateway
            igw_check = checks.get('internet_gateway', {})
            if igw_check.get('exists', False):
                igw_id = igw_check['details']['igw_id']
                igw_created = False
                fixed_items.append(f"Using existing Internet Gateway: {igw_id}")
            else:
                # Create NEW IGW since none exists
                igw_response = ec2_client.create_internet_gateway()
                igw_id = igw_response['InternetGateway']['InternetGatewayId']
                ec2_client.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                igw_created = True
                fixed_items.append(f"Created and attached NEW Internet Gateway: {igw_id}")
            
            # 3. Get the main route table
            route_tables_response = ec2_client.describe_route_tables(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            
            main_route_table = None
            main_route_table_id = None
            for rt in route_tables_response['RouteTables']:
                is_main = any(assoc.get('Main', False) for assoc in rt.get('Associations', []))
                if is_main:
                    main_route_table = rt
                    main_route_table_id = rt['RouteTableId']
                    break
            
            if not main_route_table_id:
                print(f"      [ERROR] Could not find main route table for VPC {vpc_id}")
                return False
            
            # 4. Fix routing only if needed
            if main_route_table:
                rt_id = main_route_table['RouteTableId']
                
                # Check existing routes for 0.0.0.0/0
                existing_internet_route = None
                for route in main_route_table.get('Routes', []):
                    if route.get('DestinationCidrBlock') == '0.0.0.0/0':
                        existing_internet_route = route
                        break
                
                if existing_internet_route:
                    current_target = existing_internet_route.get('GatewayId', 'unknown')
                    
                    if igw_created or current_target != igw_id:
                        try:
                            ec2_client.delete_route(
                                RouteTableId=rt_id,
                                DestinationCidrBlock='0.0.0.0/0'
                            )
                            
                            ec2_client.create_route(
                                RouteTableId=rt_id,
                                DestinationCidrBlock='0.0.0.0/0',
                                GatewayId=igw_id
                            )
                            fixed_items.append(f"Updated internet route: {rt_id} -> {igw_id}")
                            
                        except ClientError as e:
                            print(f"      [WARN]  Could not fix internet route: {e}")
                            return False
                    else:
                        fixed_items.append(f"Internet route already correct: {rt_id} -> {igw_id}")
                else:
                    try:
                        ec2_client.create_route(
                            RouteTableId=rt_id,
                            DestinationCidrBlock='0.0.0.0/0',
                            GatewayId=igw_id
                        )
                        fixed_items.append(f"Added internet route: {rt_id} -> {igw_id}")
                    except ClientError as e:
                        print(f"      [WARN]  Could not add internet route: {e}")
                        return False
            
            # 5. Create subnets only if needed (not if we have adequate coverage)
            if updated_count < rules['min_subnets']:
                # Get available AZs
                azs_response = ec2_client.describe_availability_zones(
                    Filters=[{'Name': 'state', 'Values': ['available']}]
                )
                available_azs = [az['ZoneName'] for az in azs_response['AvailabilityZones']]
                
                # Get currently used AZs
                used_azs = set()
                if isinstance(updated_details, list):
                    used_azs = {subnet['availability_zone'] for subnet in updated_details}
                
                # Create needed subnets in unused AZs
                subnets_needed = rules['min_subnets'] - updated_count
                unused_azs = [az for az in available_azs if az not in used_azs]
                
                for i, az in enumerate(unused_azs[:subnets_needed]):
                    # Calculate CIDR to avoid conflicts
                    base_third_octet = (len(used_azs) + i) * 16
                    subnet_cidr = f"172.31.{base_third_octet}.0/20"
                    
                    try:
                        subnet_response = ec2_client.create_subnet(
                            VpcId=vpc_id,
                            CidrBlock=subnet_cidr,
                            AvailabilityZone=az
                        )
                        subnet_id = subnet_response['Subnet']['SubnetId']
                        
                        # Enable auto-assign public IP
                        ec2_client.modify_subnet_attribute(
                            SubnetId=subnet_id,
                            MapPublicIpOnLaunch={'Value': True}
                        )
                        
                        # Add explicit route table association
                        try:
                            association_response = ec2_client.associate_route_table(
                                RouteTableId=main_route_table_id,
                                SubnetId=subnet_id
                            )
                            association_id = association_response['AssociationId']
                            fixed_items.append(f"Created subnet: {subnet_id} ({subnet_cidr}) in {az}")
                        except ClientError as assoc_error:
                            fixed_items.append(f"Created subnet: {subnet_id} ({subnet_cidr}) in {az} (implicit association)")
                            
                    except ClientError as e:
                        if 'InvalidSubnet.Conflict' in str(e):
                            # Try different CIDR ranges
                            for retry_octet in range(32, 240, 16):
                                try:
                                    retry_cidr = f"172.31.{retry_octet}.0/20"
                                    subnet_response = ec2_client.create_subnet(
                                        VpcId=vpc_id,
                                        CidrBlock=retry_cidr,
                                        AvailabilityZone=az
                                    )
                                    subnet_id = subnet_response['Subnet']['SubnetId']
                                    
                                    ec2_client.modify_subnet_attribute(
                                        SubnetId=subnet_id,
                                        MapPublicIpOnLaunch={'Value': True}
                                    )
                                    
                                    fixed_items.append(f"Created subnet: {subnet_id} ({retry_cidr}) in {az}")
                                    break
                                except ClientError:
                                    continue
                            else:
                                print(f"      [WARN]  Could not create subnet in {az}")
                        else:
                            print(f"      [WARN]  Could not create subnet in {az}: {e}")
            
            # 6. Fix existing subnets' auto-assign IP settings
            current_subnets_response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'defaultForAz', 'Values': ['true']}
                ]
            )
            
            for subnet in current_subnets_response['Subnets']:
                subnet_id = subnet['SubnetId']
                
                # Ensure auto-assign public IP is enabled
                if not subnet.get('MapPublicIpOnLaunch', False):
                    try:
                        ec2_client.modify_subnet_attribute(
                            SubnetId=subnet_id,
                            MapPublicIpOnLaunch={'Value': True}
                        )
                        fixed_items.append(f"Enabled auto-assign public IP: {subnet_id}")
                    except ClientError as e:
                        print(f"      [WARN]  Could not enable auto-assign public IP for {subnet_id}: {e}")
            
            # Show what was fixed
            for item in fixed_items:
                print(f"      [CONFIG] {item}")
            
            return True
            
        except Exception as e:
            print(f"      [ERROR] Error fixing compliance: {e}")
            return False

    def verify_fixes(self, account_name, region):
        """Verify that fixes were applied correctly"""
        try:
            print(f"      [SCAN] Verifying fixes for {account_name} | {region}...")
            
            # Re-run the check to verify
            verification_result = self.check_account_region(account_name, region)
            
            if verification_result['status'] != 'SUCCESS':
                print(f"      [ERROR] Verification failed: {verification_result.get('error', 'Unknown error')}")
                return False
            
            assessment = verification_result['checks'].get('overall_assessment', {})
            
            # Check compliance
            is_compliant = assessment.get('fully_compliant', False)
            
            if is_compliant:
                print(f"      [OK] Verification passed: All requirements met")
                return True
            else:
                # Show what's still missing
                issues = []
                if not assessment.get('has_default_vpc', False):
                    issues.append("Missing default VPC")
                if not assessment.get('has_sufficient_subnets', False):
                    issues.append("Insufficient subnets")
                if not assessment.get('within_subnet_limits', False):
                    issues.append("Excess subnets")
                if not assessment.get('valid_subnet_distribution', False):
                    issues.append("Invalid subnet distribution")
                if not assessment.get('has_internet_gateway', False):
                    issues.append("Missing internet gateway")
                if not assessment.get('all_subnets_have_internet_access', False):
                    issues.append("Subnets lack internet access")
                if not assessment.get('all_subnets_auto_assign_public_ip', False):
                    issues.append("Subnets don't auto-assign public IPs")
                
                print(f"      [WARN]  Verification incomplete: {', '.join(issues)}")
                return False
                
        except Exception as e:
            print(f"      [ERROR] Verification error: {e}")
            return False

    def display_detailed_results(self, results):
        """Display detailed results for all accounts and regions"""
        print(f"\n{'='*100}")
        print(f"[SCAN] DETAILED AWS DEFAULT VPC ANALYSIS REPORT")
        print(f"{'='*100}")
        print(f"[DATE] Generated: {self.current_time} UTC")
        print(f"👤 Generated by: {self.current_user}")
        print(f"[REGION] Regions checked: {', '.join(self.check_regions)}")
        print(f"[BANK] Accounts checked: {len(self.aws_accounts)}")
        
        # Group results by account
        accounts_summary = {}
        for result in results:
            account = result['account']
            if account not in accounts_summary:
                accounts_summary[account] = {
                    'total_regions': 0,
                    'compliant_regions': 0,
                    'failed_regions': 0,
                    'no_vpc_regions': 0,
                    'regions': {}
                }
            
            accounts_summary[account]['total_regions'] += 1
            accounts_summary[account]['regions'][result['region']] = result
            
            if result['status'] == 'SUCCESS':
                if result['checks'].get('overall_assessment', {}).get('fully_compliant', False):
                    accounts_summary[account]['compliant_regions'] += 1
                else:
                    accounts_summary[account]['failed_regions'] += 1
            elif result['status'] == 'NO_DEFAULT_VPC':
                accounts_summary[account]['no_vpc_regions'] += 1
            else:
                accounts_summary[account]['failed_regions'] += 1
        
        # Display account-by-account results
        for account_name, summary in accounts_summary.items():
            account_id = self.aws_accounts[account_name]['account_id']
            
            print(f"\n[BANK] ACCOUNT: {account_name.upper()} ({account_id})")
            print(f"{'─'*80}")
            print(f"   [STATS] Summary: {summary['compliant_regions']}/{summary['total_regions']} regions fully compliant")
            
            if summary['no_vpc_regions'] > 0:
                print(f"   [WARN]  {summary['no_vpc_regions']} regions missing default VPC")
            if summary['failed_regions'] > 0:
                print(f"   [ERROR] {summary['failed_regions']} regions with issues")
            
            # Show region details
            for region, result in summary['regions'].items():
                rules = self.get_regional_rules(region)
                
                if result['status'] == 'SUCCESS':
                    assessment = result['checks'].get('overall_assessment', {})
                    
                    if assessment.get('fully_compliant', False):
                        status_icon = "[OK]"
                        status_text = "FULLY COMPLIANT"
                    else:
                        status_icon = "[WARN] "
                        status_text = "HAS ISSUES"
                    
                    print(f"\n   [REGION] {region}: {status_icon} {status_text}")
                    print(f"      [MEASURE] Regional rules: {rules['min_subnets']}-{rules['max_subnets']} subnets")
                    
                    # VPC Details
                    vpc_check = result['checks'].get('default_vpc', {})
                    if vpc_check.get('exists'):
                        vpc_id = vpc_check['details']['VpcId']
                        vpc_cidr = vpc_check['details']['CidrBlock']
                        print(f"      🏗️  Default VPC: {vpc_id} ({vpc_cidr})")
                    
                    # Subnet Details with regional validation
                    subnet_check = result['checks'].get('default_subnets', {})
                    subnet_count = subnet_check.get('count', 0)
                    meets_min = subnet_check.get('meets_requirement', False)
                    within_max = subnet_check.get('within_limits', False)
                    valid_dist = subnet_check.get('valid_distribution', False)
                    
                    subnet_icon = "[OK]" if meets_min and within_max and valid_dist else "[ERROR]"
                    print(f"      [NETWORK] Subnets: {subnet_icon} {subnet_count} subnets ({rules['min_subnets']}-{rules['max_subnets']} required)")
                    
                    if not valid_dist:
                        dist_msg = subnet_check.get('distribution_message', 'Invalid distribution')
                        print(f"         [WARN]  {dist_msg}")
                    
                    if isinstance(subnet_check.get('details'), list):
                        for subnet in subnet_check['details']:
                            auto_ip_icon = "[OK]" if subnet['auto_assign_public_ip'] else "[ERROR]"
                            print(f"         • {subnet['subnet_id']} ({subnet['availability_zone']}) - Auto IP: {auto_ip_icon}")
                    
                    # Internet Gateway
                    igw_check = result['checks'].get('internet_gateway', {})
                    igw_icon = "[OK]" if igw_check.get('exists') else "[ERROR]"
                    if igw_check.get('exists'):
                        igw_id = igw_check['details']['igw_id']
                        print(f"      [NETWORK] Internet Gateway: {igw_icon} {igw_id}")
                    else:
                        print(f"      [NETWORK] Internet Gateway: {igw_icon} NOT FOUND")
                    
                    # Internet Access
                    routing = result['checks'].get('routing', {})
                    subnet_access = routing.get('subnet_internet_access', {})
                    
                    all_have_access = assessment.get('all_subnets_have_internet_access', False)
                    access_icon = "[OK]" if all_have_access else "[ERROR]"
                    print(f"      [LINK] Internet Access: {access_icon} All subnets routed to internet")
                    
                    if not all_have_access:
                        for subnet_id, access_info in subnet_access.items():
                            access_status = "[OK]" if access_info['has_internet_access'] else "[ERROR]"
                            rt_id = access_info['route_table_id']
                            print(f"         • {subnet_id}: {access_status} (Route Table: {rt_id})")
                
                elif result['status'] == 'NO_DEFAULT_VPC':
                    print(f"\n   [REGION] {region}: [ERROR] NO DEFAULT VPC")
                    print(f"      [TIP] Run: aws ec2 create-default-vpc --region {region}")
                
                else:
                    print(f"\n   [REGION] {region}: [ERROR] ERROR")
                    print(f"      🐛 {result.get('error', 'Unknown error')}")
        
        # Overall Summary
        total_regions = len(results)
        compliant_regions = sum(1 for r in results if r.get('checks', {}).get('overall_assessment', {}).get('fully_compliant', False))
        no_vpc_regions = sum(1 for r in results if r['status'] == 'NO_DEFAULT_VPC')
        error_regions = sum(1 for r in results if r['status'] in ['ERROR', 'FAILED'])
        
        print(f"\n{'='*100}")
        print(f"📈 OVERALL SUMMARY")
        print(f"{'='*100}")
        print(f"[OK] Fully Compliant: {compliant_regions}/{total_regions} regions ({compliant_regions/total_regions*100:.1f}%)")
        print(f"[ERROR] Missing Default VPC: {no_vpc_regions} regions")
        print(f"[WARN]  Has Issues: {total_regions - compliant_regions - no_vpc_regions - error_regions} regions")
        print(f"🐛 Errors: {error_regions} regions")
        
        # Regional Rules Summary
        print(f"\n[MEASURE] Regional Rules Applied:")
        for region in set(r['region'] for r in results):
            rules = self.get_regional_rules(region)
            print(f"   {region}: {rules['min_subnets']}-{rules['max_subnets']} subnets")

    def save_results_to_file(self, results):
        """Save results to JSON file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = "aws/vpc"
            os.makedirs(log_dir, exist_ok=True)
            filename = f"{log_dir}/aws_default_vpc_check_report_{timestamp}.json"
            
            report_data = {
                "report_date": self.current_time.split()[0],
                "report_time": self.current_time.split()[1] + " UTC",
                "generated_by": self.current_user,
                "regions_checked": self.check_regions,
                "accounts_checked": list(self.aws_accounts.keys()),
                "regional_rules": self.regional_rules,
                "total_checks": len(results),
                "results": results
            }
            
            with open(filename, 'w') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            print(f"\n[INSTANCE] Detailed report saved to: {filename}")
            return filename
            
        except Exception as e:
            print(f"[ERROR] Failed to save report: {e}")
            return None

    def parse_number_input(self, input_str, max_value):
        """Parse user input for numbers, supporting ranges and comma-separated values"""
        try:
            numbers = set()
            
            # Split by commas first
            parts = input_str.strip().split(',')
            
            for part in parts:
                part = part.strip()
                
                if '-' in part:
                    # Handle range like "1-3"
                    try:
                        start, end = part.split('-', 1)
                        start_num = int(start.strip())
                        end_num = int(end.strip())
                        
                        if start_num > end_num:
                            start_num, end_num = end_num, start_num
                        
                        for i in range(start_num, end_num + 1):
                            if 1 <= i <= max_value:
                                numbers.add(i)
                    except ValueError:
                        return None, f"Invalid range format: '{part}'"
                else:
                    # Handle single number
                    try:
                        num = int(part)
                        if 1 <= num <= max_value:
                            numbers.add(num)
                        else:
                            return None, f"Number {num} is out of range (1-{max_value})"
                    except ValueError:
                        return None, f"Invalid number: '{part}'"
            
            return sorted(list(numbers)), None
            
        except Exception as e:
            return None, f"Error parsing input: {e}"

    def select_accounts_and_regions(self):
        """Allow user to select accounts and regions to check"""
        print(f"\n[LIST] Account Selection:")
        print(f"  1. Check all accounts ({len(self.aws_accounts)} accounts)")
        print(f"  2. Select specific accounts")
        
        while True:
            try:
                choice = input(f"\n🔢 Select option (1-2): ").strip()
                choice_num = int(choice)
                
                if choice_num == 1:
                    selected_accounts = list(self.aws_accounts.keys())
                    break
                elif choice_num == 2:
                    print(f"\n[LIST] Available Accounts:")
                    account_names = list(self.aws_accounts.keys())
                    for i, account_name in enumerate(account_names, 1):
                        config = self.aws_accounts[account_name]
                        print(f"  {i}. {account_name} ({config['account_id']})")
                    
                    while True:
                        account_input = input(f"\n🔢 Enter account numbers (e.g., 1,3,5 or 1-3 or 2): ").strip()
                        account_numbers, error = self.parse_number_input(account_input, len(account_names))
                        
                        if error:
                            print(f"[ERROR] {error}. Please try again.")
                            continue
                        
                        if not account_numbers:
                            print(f"[ERROR] No valid account numbers entered. Please try again.")
                            continue
                        
                        selected_accounts = [account_names[i-1] for i in account_numbers]
                        print(f"[OK] Selected accounts: {', '.join(selected_accounts)}")
                        break
                    break
                else:
                    print("[ERROR] Invalid choice. Please enter 1 or 2")
            except ValueError:
                print("[ERROR] Invalid input. Please enter 1 or 2")
        
        print(f"\n[REGION] Region Selection:")
        print(f"  1. Check all configured regions ({len(self.check_regions)} regions)")
        print(f"  2. Select specific regions")
        
        while True:
            try:
                choice = input(f"\n🔢 Select option (1-2): ").strip()
                choice_num = int(choice)
                
                if choice_num == 1:
                    selected_regions = self.check_regions
                    break
                elif choice_num == 2:
                    print(f"\n[REGION] Available Regions:")
                    for i, region in enumerate(self.check_regions, 1):
                        print(f"  {i}. {region}")
                    
                    while True:
                        region_input = input(f"\n🔢 Enter region numbers (e.g., 1,3,5 or 1-3 or 2): ").strip()
                        region_numbers, error = self.parse_number_input(region_input, len(self.check_regions))
                        
                        if error:
                            print(f"[ERROR] {error}. Please try again.")
                            continue
                        
                        if not region_numbers:
                            print(f"[ERROR] No valid region numbers entered. Please try again.")
                            continue
                        
                        selected_regions = [self.check_regions[i-1] for i in region_numbers]
                        print(f"[OK] Selected regions: {', '.join(selected_regions)}")
                        break
                    break
                else:
                    print("[ERROR] Invalid choice. Please enter 1 or 2")
            except ValueError:
                print("[ERROR] Invalid input. Please enter 1 or 2")
        
        return selected_accounts, selected_regions

    def run(self):
        """Main execution method"""
        print(f"[START] AWS Default VPC Configuration Checker")
        print(f"[ALARM] Started at: {self.current_time} UTC")
        print(f"👤 User: {self.current_user}")
        
        # Select accounts and regions
        selected_accounts, selected_regions = self.select_accounts_and_regions()
        
        print(f"\n[STATS] Check Summary:")
        print(f"   [BANK] Accounts: {len(selected_accounts)} ({', '.join(selected_accounts)})")
        print(f"   [REGION] Regions: {len(selected_regions)} ({', '.join(selected_regions)})")
        print(f"   [SCAN] Total checks: {len(selected_accounts) * len(selected_regions)}")
        
        # Show regional rules
        print(f"\n[MEASURE] Regional Rules:")
        for region in selected_regions:
            rules = self.get_regional_rules(region)
            print(f"   {region}: {rules['min_subnets']}-{rules['max_subnets']} subnets")
        
        confirm = input(f"\n[OK] Proceed with the check? (y/N): ").lower().strip()
        if confirm != 'y':
            print("[ERROR] Check cancelled")
            return
        
        # Prepare tasks for concurrent execution
        tasks = []
        for account in selected_accounts:
            for region in selected_regions:
                tasks.append((account, region))
        
        print(f"\n🔄 Running checks...")
        results = []
        
        # Use ThreadPoolExecutor for concurrent checks
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(self.check_account_region, account, region): (account, region)
                for account, region in tasks
            }
            
            # Collect results as they complete
            completed = 0
            for future in as_completed(future_to_task):
                account, region = future_to_task[future]
                try:
                    result = future.result()
                    results.append(result)
                    completed += 1
                    
                    # Show progress
                    status = "[OK]" if result.get('checks', {}).get('overall_assessment', {}).get('fully_compliant', False) else "[WARN]"
                    print(f"   {status} {account} | {region} ({completed}/{len(tasks)})")
                    
                except Exception as e:
                    print(f"   [ERROR] {account} | {region} - Error: {e}")
                    results.append({
                        'account': account,
                        'region': region,
                        'status': 'ERROR',
                        'error': str(e),
                        'checks': {}
                    })
        
        # Display results
        self.display_detailed_results(results)
        
        # Offer to save results
        save_report = input(f"\n[INSTANCE] Save detailed report to JSON file? (y/N): ").lower().strip()
        if save_report == 'y':
            self.save_results_to_file(results)
        
        # Check for issues and offer remediation
        issues_found = any(
            r['status'] in ['NO_DEFAULT_VPC'] or 
            not r.get('checks', {}).get('overall_assessment', {}).get('fully_compliant', False)
            for r in results if r['status'] != 'ERROR'
        )

        if issues_found:
            fix_issues = input(f"\n[CONFIG] Fix detected issues automatically? (y/N): ").lower().strip()
            if fix_issues == 'y':
                self.fix_missing_default_vpcs(results)
        
        print(f"\n[PARTY] Check completed!")

def main():
    """Main function"""
    try:
        checker = AWSDefaultVPCChecker()
        checker.run()
    except KeyboardInterrupt:
        print(f"\n\n[ERROR] Check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()