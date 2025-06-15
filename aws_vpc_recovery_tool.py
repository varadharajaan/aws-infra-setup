#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class AWSVPCRecoveryTool:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        self.recovery_actions = []  # Track all recovery actions
        self.load_configuration()
        
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
            
            print(f"✅ Configuration loaded from: {self.config_file}")
            print(f"📊 Found {len(self.aws_accounts)} AWS accounts: {list(self.aws_accounts.keys())}")
            print(f"🌍 Available {len(self.check_regions)} regions: {self.check_regions}")
            
        except FileNotFoundError as e:
            print(f"❌ Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error loading configuration: {e}")
            sys.exit(1)

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
        """Allow user to select accounts and regions for recovery"""
        print(f"\n📋 Account Selection:")
        print(f"  1. Recover ALL accounts ({len(self.aws_accounts)} accounts)")
        print(f"  2. Select specific accounts")
        
        while True:
            try:
                choice = input(f"\n🔢 Select option (1-2): ").strip()
                choice_num = int(choice)
                
                if choice_num == 1:
                    selected_accounts = list(self.aws_accounts.keys())
                    break
                elif choice_num == 2:
                    print(f"\n📋 Available Accounts:")
                    account_names = list(self.aws_accounts.keys())
                    for i, account_name in enumerate(account_names, 1):
                        config = self.aws_accounts[account_name]
                        print(f"  {i}. {account_name} ({config['account_id']})")
                    
                    while True:
                        account_input = input(f"\n🔢 Enter account numbers (e.g., 1,3,5 or 1-3 or 2): ").strip()
                        account_numbers, error = self.parse_number_input(account_input, len(account_names))
                        
                        if error:
                            print(f"❌ {error}. Please try again.")
                            continue
                        
                        if not account_numbers:
                            print(f"❌ No valid account numbers entered. Please try again.")
                            continue
                        
                        selected_accounts = [account_names[i-1] for i in account_numbers]
                        print(f"✅ Selected accounts: {', '.join(selected_accounts)}")
                        break
                    break
                else:
                    print("❌ Invalid choice. Please enter 1 or 2")
            except ValueError:
                print("❌ Invalid input. Please enter 1 or 2")
        
        print(f"\n🌍 Region Selection:")
        print(f"  1. Recover ALL configured regions ({len(self.check_regions)} regions)")
        print(f"  2. Select specific regions")
        
        while True:
            try:
                choice = input(f"\n🔢 Select option (1-2): ").strip()
                choice_num = int(choice)
                
                if choice_num == 1:
                    selected_regions = self.check_regions
                    break
                elif choice_num == 2:
                    print(f"\n🌍 Available Regions:")
                    for i, region in enumerate(self.check_regions, 1):
                        print(f"  {i}. {region}")
                    
                    while True:
                        region_input = input(f"\n🔢 Enter region numbers (e.g., 1,3,5 or 1-3 or 2): ").strip()
                        region_numbers, error = self.parse_number_input(region_input, len(self.check_regions))
                        
                        if error:
                            print(f"❌ {error}. Please try again.")
                            continue
                        
                        if not region_numbers:
                            print(f"❌ No valid region numbers entered. Please try again.")
                            continue
                        
                        selected_regions = [self.check_regions[i-1] for i in region_numbers]
                        print(f"✅ Selected regions: {', '.join(selected_regions)}")
                        break
                    break
                else:
                    print("❌ Invalid choice. Please enter 1 or 2")
            except ValueError:
                print("❌ Invalid input. Please enter 1 or 2")
        
        return selected_accounts, selected_regions

    def create_clients(self, account_name, region):
        """Create AWS clients for a specific account and region"""
        if account_name not in self.aws_accounts:
            raise ValueError(f"Account {account_name} not found")
        
        account_config = self.aws_accounts[account_name]
        
        try:
            session = boto3.Session(
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name=region
            )
            
            ec2_client = session.client('ec2')
            ec2_client.describe_vpcs(MaxResults=5)  # Test connection
            
            return ec2_client, account_config
            
        except Exception as e:
            return None, f"Connection failed: {e}"

    def get_next_available_cidr(self, existing_cidrs, base_cidr="172.31.0.0/16", subnet_size=20):
        """Generate next available CIDR block that doesn't conflict with existing ones"""
        import ipaddress
        
        try:
            # Parse the base VPC CIDR
            vpc_network = ipaddress.IPv4Network(base_cidr, strict=False)
            
            # Calculate subnet size
            subnet_prefix_len = subnet_size
            subnet_increment = 2 ** (32 - subnet_prefix_len)  # Number of IPs in each subnet
            
            # Convert existing CIDRs to network objects for comparison
            existing_networks = []
            for cidr in existing_cidrs:
                try:
                    existing_networks.append(ipaddress.IPv4Network(cidr, strict=False))
                except:
                    continue
            
            # Start from the beginning of the VPC range
            current_ip = vpc_network.network_address
            
            while current_ip < vpc_network.broadcast_address:
                try:
                    # Create candidate subnet
                    candidate_subnet = ipaddress.IPv4Network(f"{current_ip}/{subnet_prefix_len}", strict=False)
                    
                    # Check if this subnet fits within the VPC
                    if not vpc_network.supernet_of(candidate_subnet):
                        break
                    
                    # Check for conflicts with existing subnets
                    conflict_found = False
                    for existing_net in existing_networks:
                        if candidate_subnet.overlaps(existing_net):
                            conflict_found = True
                            break
                    
                    if not conflict_found:
                        return str(candidate_subnet)
                    
                    # Move to next possible subnet start
                    current_ip += subnet_increment
                    
                except Exception:
                    current_ip += subnet_increment
                    continue
            
            return None  # No available CIDR found
            
        except Exception as e:
            print(f"Error in CIDR calculation: {e}")
            return None

    def analyze_vpc_state(self, ec2_client, account_name, region):
        """Analyze current VPC state and determine what needs recovery"""
        try:
            # Check for default VPC
            vpc_response = ec2_client.describe_vpcs(
                Filters=[{'Name': 'isDefault', 'Values': ['true']}]
            )
            
            if not vpc_response['Vpcs']:
                return {
                    'has_default_vpc': False,
                    'needs_vpc_creation': True,
                    'recovery_needed': True
                }
            
            vpc = vpc_response['Vpcs'][0]
            vpc_id = vpc['VpcId']
            
            # Get all available AZs in the region
            azs_response = ec2_client.describe_availability_zones(
                Filters=[{'Name': 'state', 'Values': ['available']}]
            )
            available_azs = [az['ZoneName'] for az in azs_response['AvailabilityZones']]
            
            # Check subnets
            subnets_response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'defaultForAz', 'Values': ['true']}
                ]
            )
            
            subnets = subnets_response['Subnets']
            public_subnets = [s for s in subnets if s.get('MapPublicIpOnLaunch', False)]
            
            # Check AZ coverage - we want at least 2 AZs covered
            covered_azs = set(subnet['AvailabilityZone'] for subnet in subnets)
            min_required_azs = min(2, len(available_azs))  # At least 2 AZs or all available AZs if less than 2
            
            # Check route tables
            rt_response = ec2_client.describe_route_tables(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            
            main_rt = None
            for rt in rt_response['RouteTables']:
                if any(assoc.get('Main', False) for assoc in rt.get('Associations', [])):
                    main_rt = rt
                    break
            
            # Check internet gateway
            igw_response = ec2_client.describe_internet_gateways(
                Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
            )
            
            has_igw = len(igw_response['InternetGateways']) > 0
            igw_id = igw_response['InternetGateways'][0]['InternetGatewayId'] if has_igw else None
            
            # Check if main route table has internet route
            has_internet_route = False
            if main_rt and has_igw:
                for route in main_rt.get('Routes', []):
                    if (route.get('DestinationCidrBlock') == '0.0.0.0/0' and 
                        route.get('GatewayId') == igw_id and 
                        route.get('State') == 'active'):
                        has_internet_route = True
                        break
            
            # Determine if subnets need to be created
            needs_subnets = (len(covered_azs) < min_required_azs) or (len(subnets) < min_required_azs)
            
            analysis = {
                'has_default_vpc': True,
                'vpc_id': vpc_id,
                'subnet_count': len(subnets),
                'public_subnet_count': len(public_subnets),
                'covered_azs': list(covered_azs),
                'available_azs': available_azs,
                'min_required_azs': min_required_azs,
                'needs_subnets': needs_subnets,
                'has_main_route_table': main_rt is not None,
                'main_route_table_id': main_rt['RouteTableId'] if main_rt else None,
                'has_internet_gateway': has_igw,
                'internet_gateway_id': igw_id,
                'has_internet_route': has_internet_route,
                'recovery_needed': (needs_subnets or not main_rt or not has_igw or not has_internet_route),
                'subnets': subnets,
                'route_tables': rt_response['RouteTables']
            }
            
            return analysis
            
        except Exception as e:
            return {'error': str(e), 'recovery_needed': True}

    def recover_vpc_resources(self, account_name, region):
        """Comprehensive VPC recovery following the exact order specified"""
        print(f"\n   🏦 {account_name.upper()} | {region}")
        
        try:
            ec2_client, account_config = self.create_clients(account_name, region)
            if not ec2_client:
                print(f"      ❌ Connection failed: {account_config}")
                return False
            
            print(f"      🔍 Analyzing current state...")
            analysis = self.analyze_vpc_state(ec2_client, account_name, region)
            
            if 'error' in analysis:
                print(f"      ❌ Analysis failed: {analysis['error']}")
                return False
            
            if not analysis['recovery_needed']:
                print(f"      ✅ VPC already compliant - no recovery needed")
                return True
            
            # Step 1: Create default VPC if missing
            if not analysis['has_default_vpc']:
                print(f"      🔧 Creating default VPC...")
                try:
                    vpc_response = ec2_client.create_default_vpc()
                    vpc_id = vpc_response['Vpc']['VpcId']
                    print(f"         ✅ Created default VPC: {vpc_id}")
                    self.log_action(account_name, region, 'CREATE_DEFAULT_VPC', vpc_id)
                    
                    # Re-analyze after VPC creation
                    analysis = self.analyze_vpc_state(ec2_client, account_name, region)
                    
                except ClientError as e:
                    if 'DefaultVpcAlreadyExists' in str(e):
                        print(f"      ✅ Default VPC already exists")
                    else:
                        print(f"      ❌ Failed to create default VPC: {e}")
                        return False
            
            vpc_id = analysis['vpc_id']
            
            # Step 2: Create/verify Internet Gateway FIRST (needed for routing)
            if not analysis['has_internet_gateway']:
                print(f"      🔧 Creating Internet Gateway...")
                try:
                    igw_response = ec2_client.create_internet_gateway()
                    igw_id = igw_response['InternetGateway']['InternetGatewayId']
                    
                    ec2_client.attach_internet_gateway(
                        InternetGatewayId=igw_id,
                        VpcId=vpc_id
                    )
                    
                    print(f"         ✅ Created and attached IGW: {igw_id}")
                    self.log_action(account_name, region, 'CREATE_IGW', igw_id)
                    analysis['internet_gateway_id'] = igw_id
                    analysis['has_internet_gateway'] = True
                    
                except ClientError as e:
                    print(f"      ❌ Failed to create IGW: {e}")
                    return False
            else:
                igw_id = analysis['internet_gateway_id']
                print(f"      ✅ Using existing IGW: {igw_id}")
            
            # Step 3: Verify/Create Main Route Table
            if not analysis['has_main_route_table']:
                print(f"      🔧 Creating main route table...")
                try:
                    rt_response = ec2_client.create_route_table(VpcId=vpc_id)
                    rt_id = rt_response['RouteTable']['RouteTableId']
                    
                    print(f"         ✅ Created main route table: {rt_id}")
                    self.log_action(account_name, region, 'CREATE_MAIN_RT', rt_id)
                    analysis['main_route_table_id'] = rt_id
                    
                except ClientError as e:
                    print(f"      ❌ Failed to create main route table: {e}")
                    return False
            else:
                rt_id = analysis['main_route_table_id']
                print(f"      ✅ Using existing main route table: {rt_id}")
            
            # Step 4: Create missing subnets - IMPROVED LOGIC
            if analysis['needs_subnets']:
                current_subnet_count = analysis['subnet_count']
                covered_azs = set(analysis['covered_azs'])
                available_azs = analysis['available_azs']
                min_required_azs = analysis['min_required_azs']
                
                # Determine how many subnets we need and in which AZs
                uncovered_azs = [az for az in available_azs if az not in covered_azs]
                target_azs = uncovered_azs[:min_required_azs - len(covered_azs)]
                
                if not target_azs and current_subnet_count < min_required_azs:
                    # If all AZs are covered but we need more subnets, add to existing AZs
                    target_azs = available_azs[:min_required_azs - current_subnet_count]
                
                print(f"      🔧 Creating subnets for better AZ coverage...")
                print(f"         Current: {current_subnet_count} subnets in {len(covered_azs)} AZs: {list(covered_azs)}")
                print(f"         Target: {len(target_azs)} additional subnets in AZs: {target_azs}")
                
                # Get existing subnet CIDRs to avoid conflicts
                existing_cidrs = set()
                for subnet in analysis.get('subnets', []):
                    existing_cidrs.add(subnet['CidrBlock'])
                
                subnets_created = []
                for az in target_azs:
                    # Generate non-conflicting CIDR using improved method
                    subnet_cidr = self.get_next_available_cidr(existing_cidrs)
                    
                    if not subnet_cidr:
                        print(f"         ⚠️ No available CIDR blocks for AZ {az}")
                        continue
                    
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
                        
                        subnets_created.append({
                            'subnet_id': subnet_id,
                            'cidr': subnet_cidr,
                            'az': az
                        })
                        
                        print(f"         • Created subnet {subnet_id} in {az} ({subnet_cidr})")
                        self.log_action(account_name, region, 'CREATE_SUBNET', f"{subnet_id}:{subnet_cidr}:{az}")
                        existing_cidrs.add(subnet_cidr)
                        
                    except ClientError as e:
                        print(f"         ⚠️  Failed to create subnet in {az}: {e}")
                        continue
                
                if len(subnets_created) == 0:
                    print(f"      ❌ Failed to create any subnets")
                    return False
                
                print(f"         ✅ Created {len(subnets_created)} subnets successfully")
            else:
                print(f"      ✅ Subnet configuration already adequate ({analysis['subnet_count']} subnets in {len(analysis['covered_azs'])} AZs)")
            
            # Step 5: Create explicit subnet-to-route-table associations
            print(f"      🔧 Creating explicit route table associations...")
            
            # Get all subnets in the VPC (existing + newly created)
            all_subnets_response = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'defaultForAz', 'Values': ['true']}
                ]
            )
            
            # Get current explicit associations
            rt_response = ec2_client.describe_route_tables(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )
            
            explicitly_associated = set()
            for rt in rt_response['RouteTables']:
                for assoc in rt.get('Associations', []):
                    if 'SubnetId' in assoc and not assoc.get('Main', False):
                        explicitly_associated.add(assoc['SubnetId'])
            
            associations_created = 0
            for subnet in all_subnets_response['Subnets']:
                subnet_id = subnet['SubnetId']
                
                if subnet_id not in explicitly_associated:
                    try:
                        assoc_response = ec2_client.associate_route_table(
                            RouteTableId=rt_id,
                            SubnetId=subnet_id
                        )
                        assoc_id = assoc_response['AssociationId']
                        
                        print(f"         • Associated {subnet_id} -> {rt_id} ({assoc_id})")
                        self.log_action(account_name, region, 'CREATE_ASSOCIATION', f"{subnet_id}:{rt_id}:{assoc_id}")
                        associations_created += 1
                        
                    except ClientError as e:
                        print(f"         ⚠️  Failed to associate {subnet_id}: {e}")
            
            if associations_created > 0:
                print(f"         ✅ Created {associations_created} explicit associations")
            else:
                print(f"         ✅ All subnets already properly associated")
            
            # Step 6: Add internet route (0.0.0.0/0 -> IGW)
            if not analysis['has_internet_route']:
                print(f"      🔧 Adding internet route...")
                try:
                    # First, check if a conflicting route exists
                    rt_detail = ec2_client.describe_route_tables(RouteTableIds=[rt_id])
                    existing_internet_route = None
                    
                    for route in rt_detail['RouteTables'][0].get('Routes', []):
                        if route.get('DestinationCidrBlock') == '0.0.0.0/0':
                            existing_internet_route = route
                            break
                    
                    if existing_internet_route:
                        current_target = existing_internet_route.get('GatewayId', 'unknown')
                        if current_target != igw_id:
                            # Delete conflicting route
                            ec2_client.delete_route(
                                RouteTableId=rt_id,
                                DestinationCidrBlock='0.0.0.0/0'
                            )
                            print(f"         • Deleted conflicting route (was: {current_target})")
                    
                    # Add correct internet route
                    ec2_client.create_route(
                        RouteTableId=rt_id,
                        DestinationCidrBlock='0.0.0.0/0',
                        GatewayId=igw_id
                    )
                    
                    print(f"         ✅ Added internet route: 0.0.0.0/0 -> {igw_id}")
                    self.log_action(account_name, region, 'CREATE_INTERNET_ROUTE', f"{rt_id}:{igw_id}")
                    
                except ClientError as e:
                    if 'RouteAlreadyExists' not in str(e):
                        print(f"         ⚠️  Failed to add internet route: {e}")
                    else:
                        print(f"         ✅ Internet route already exists")
            else:
                print(f"      ✅ Internet route already configured")
            
            # Step 7: Final verification
            print(f"      🔍 Verifying recovery...")
            final_analysis = self.analyze_vpc_state(ec2_client, account_name, region)
            
            if not final_analysis.get('recovery_needed', True):
                print(f"      ✅ Recovery completed successfully")
                self.log_action(account_name, region, 'RECOVERY_SUCCESS', 'All resources operational')
                return True
            else:
                print(f"      ⚠️  Recovery partially completed")
                self.log_action(account_name, region, 'RECOVERY_PARTIAL', 'Some issues remain')
                return False
                
        except Exception as e:
            print(f"      ❌ Recovery failed: {e}")
            self.log_action(account_name, region, 'RECOVERY_FAILED', str(e))
            return False

    def log_action(self, account, region, action, details):
        """Log recovery actions for reporting"""
        self.recovery_actions.append({
            'timestamp': datetime.now().isoformat(),
            'account': account,
            'region': region,
            'action': action,
            'details': details
        })

    def save_recovery_report(self, results, selected_accounts, selected_regions):
        """Save detailed recovery report to JSON file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = "aws/vpc"
            os.makedirs(log_dir, exist_ok=True)
            filename = f"{log_dir}/vpc_recovery_report_{timestamp}.json"
            
            # Calculate statistics
            total_recoveries = len(results)
            successful_recoveries = sum(1 for r in results if r['success'])
            failed_recoveries = total_recoveries - successful_recoveries
            
            report_data = {
                "report_metadata": {
                    "generated_at": self.current_time,
                    "generated_by": self.current_user,
                    "tool_version": "AWS VPC Recovery Tool v2.1 - Fixed",
                    "total_accounts_available": list(self.aws_accounts.keys()),
                    "total_regions_available": self.check_regions,
                    "selected_accounts": selected_accounts,
                    "selected_regions": selected_regions
                },
                "recovery_summary": {
                    "total_recoveries_attempted": total_recoveries,
                    "successful_recoveries": successful_recoveries,
                    "failed_recoveries": failed_recoveries,
                    "success_rate": f"{(successful_recoveries/total_recoveries*100):.1f}%" if total_recoveries > 0 else "0%"
                },
                "recovery_results": results,
                "detailed_actions": self.recovery_actions,
                "action_statistics": {
                    "vpc_creations": len([a for a in self.recovery_actions if a['action'] == 'CREATE_DEFAULT_VPC']),
                    "igw_creations": len([a for a in self.recovery_actions if a['action'] == 'CREATE_IGW']),
                    "subnet_creations": len([a for a in self.recovery_actions if a['action'] == 'CREATE_SUBNET']),
                    "association_creations": len([a for a in self.recovery_actions if a['action'] == 'CREATE_ASSOCIATION']),
                    "route_creations": len([a for a in self.recovery_actions if a['action'] == 'CREATE_INTERNET_ROUTE'])
                }
            }
            
            with open(filename, 'w') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            print(f"\n💾 Detailed recovery report saved: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Failed to save report: {e}")
            return None

    def run_recovery(self):
        """Main recovery execution with interactive selection"""
        print(f"🚀 AWS VPC Recovery Tool v2.1 - Fixed")
        print(f"📅 Started: {self.current_time} UTC")
        print(f"👤 User: {self.current_user}")
        
        # Interactive selection
        selected_accounts, selected_regions = self.select_accounts_and_regions()
        
        print(f"\n📊 Recovery Summary:")
        print(f"   🏦 Accounts: {len(selected_accounts)} ({', '.join(selected_accounts)})")
        print(f"   🌍 Regions: {len(selected_regions)} ({', '.join(selected_regions)})")
        print(f"   🎯 Total VPCs to recover: {len(selected_accounts) * len(selected_regions)}")
        
        confirm = input(f"\n⚠️  This will recover/create VPC resources. Continue? (y/N): ").lower().strip()
        if confirm != 'y':
            print("❌ Recovery cancelled")
            return
        
        print(f"\n🔄 Starting VPC recovery...")
        
        # Prepare recovery tasks
        tasks = []
        for account in selected_accounts:
            for region in selected_regions:
                tasks.append((account, region))
        
        results = []
        
        # Execute recoveries with threading
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_task = {
                executor.submit(self.recover_vpc_resources, account, region): (account, region)
                for account, region in tasks
            }
            
            completed = 0
            for future in as_completed(future_to_task):
                account, region = future_to_task[future]
                try:
                    success = future.result()
                    results.append({
                        'account': account,
                        'region': region,
                        'success': success,
                        'timestamp': datetime.now().isoformat()
                    })
                    completed += 1
                    
                except Exception as e:
                    print(f"   ❌ {account} | {region} - Unexpected error: {e}")
                    results.append({
                        'account': account,
                        'region': region,
                        'success': False,
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    })
        
        # Show final summary
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        
        print(f"\n{'='*80}")
        print(f"📊 VPC RECOVERY SUMMARY")
        print(f"{'='*80}")
        print(f"✅ Successfully recovered: {successful}/{len(results)} VPCs ({successful/len(results)*100:.1f}%)")
        print(f"❌ Failed recoveries: {failed}/{len(results)} VPCs")
        print(f"🔧 Total actions performed: {len(self.recovery_actions)}")
        
        # Show breakdown by action type
        action_counts = {}
        for action in self.recovery_actions:
            action_type = action['action']
            action_counts[action_type] = action_counts.get(action_type, 0) + 1
        
        if action_counts:
            print(f"\n🔧 Actions Breakdown:")
            for action_type, count in action_counts.items():
                print(f"   • {action_type.replace('_', ' ').title()}: {count}")
        
        # Save detailed report
        self.save_recovery_report(results, selected_accounts, selected_regions)
        
        print(f"\n🎉 VPC recovery operation completed!")

def main():
    """Main function"""
    try:
        recovery_tool = AWSVPCRecoveryTool()
        recovery_tool.run_recovery()
    except KeyboardInterrupt:
        print(f"\n\n❌ Recovery interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()