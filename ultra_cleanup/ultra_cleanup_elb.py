#!/usr/bin/env python3

import os
import json
import boto3
import time
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from botocore.exceptions import ClientError, BotoCoreError
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors
from text_symbols import Symbols


class UltraCleanupELBManager:
    """
    Tool to perform comprehensive cleanup of ELB resources across AWS accounts.

    Manages deletion of:
    - Classic Load Balancers (ELB) - including Kubernetes-managed ones
    - Application Load Balancers (ALB)
    - Network Load Balancers (NLB)
    - Target Groups
    - Security Groups attached to Load Balancers only

    Author: varadharajaan
    Created: 2025-01-20
    Updated: 2025-07-09 - Enhanced Kubernetes ELB detection, simplified scope
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

        # Storage for cleanup results - simplified scope
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_load_balancers': [],
            'deleted_target_groups': [],
            'deleted_security_groups': [],
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
            self.print_colored(Colors.YELLOW, f"{Symbols.WARN}  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.elb_dir, exist_ok=True)

            # Save log file in the aws/elb directory
            self.log_filename = f"{self.elb_dir}/ultra_elb_cleanup_log_{self.execution_timestamp}.log"

            # Create a file handler for detailed logging

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
            self.operation_logger.info(f"{Symbols.ALERT} ULTRA ELB CLEANUP SESSION STARTED {Symbols.ALERT}")
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

    def is_kubernetes_managed_elb(self, lb_name: str, lb_tags: List[Dict], lb_description: str = "") -> Dict[str, Any]:
        """
        Enhanced detection for Kubernetes-managed load balancers
        Returns a dict with detection details
        """
        detection_info = {
            'is_kubernetes': False,
            'detection_method': None,
            'cluster_name': None,
            'service_name': None,
            'namespace': None,
            'confidence': 'low'
        }

        # Method 1: Check for Kubernetes tags
        for tag in lb_tags:
            tag_key = tag.get('Key', '')
            tag_value = tag.get('Value', '')

            # Kubernetes cluster tag
            if tag_key.startswith('kubernetes.io/cluster/'):
                detection_info['is_kubernetes'] = True
                detection_info['detection_method'] = 'cluster_tag'
                detection_info['cluster_name'] = tag_key.replace('kubernetes.io/cluster/', '')
                detection_info['confidence'] = 'high'

            # Kubernetes service name tag
            elif tag_key == 'kubernetes.io/service-name':
                detection_info['is_kubernetes'] = True
                detection_info['detection_method'] = 'service_tag'
                detection_info['service_name'] = tag_value
                detection_info['confidence'] = 'high'

            # Kubernetes namespace tag
            elif tag_key == 'kubernetes.io/namespace':
                detection_info['namespace'] = tag_value

            # Other Kubernetes-related tags
            elif tag_key in ['KubernetesCluster', 'kubernetes.io/created-for/pvc/name',
                             'kubernetes.io/created-for/pv/name']:
                detection_info['is_kubernetes'] = True
                detection_info['detection_method'] = 'k8s_tag'
                detection_info['confidence'] = 'medium'

        # Method 2: Check AWS-generated naming pattern for Kubernetes ELBs
        # AWS generates names like: a1234567890abcdef1234567890abcdef
        if not detection_info['is_kubernetes']:
            # Pattern: starts with 'a' followed by 32 hex characters
            aws_generated_pattern = re.match(r'^a[0-9a-f]{32}$', lb_name)
            if aws_generated_pattern:
                detection_info['is_kubernetes'] = True
                detection_info['detection_method'] = 'aws_generated_name'
                detection_info['confidence'] = 'medium'

        # Method 3: Check for other common Kubernetes naming patterns
        if not detection_info['is_kubernetes']:
            k8s_patterns = [
                r'.*-k8s-.*',  # Contains k8s
                r'k8s-.*',  # Starts with k8s
                r'.*-kubernetes-.*',  # Contains kubernetes
                r'kube-.*',  # Starts with kube
            ]

            for pattern in k8s_patterns:
                if re.match(pattern, lb_name, re.IGNORECASE):
                    detection_info['is_kubernetes'] = True
                    detection_info['detection_method'] = 'name_pattern'
                    detection_info['confidence'] = 'low'
                    break

        # Method 4: Check description for Kubernetes indicators
        if not detection_info['is_kubernetes'] and lb_description:
            k8s_desc_indicators = ['kubernetes', 'k8s', 'kube-system', 'cluster']
            for indicator in k8s_desc_indicators:
                if indicator.lower() in lb_description.lower():
                    detection_info['is_kubernetes'] = True
                    detection_info['detection_method'] = 'description'
                    detection_info['confidence'] = 'low'
                    break

        return detection_info

    def get_load_balancer_tags(self, elb_client, lb_name: str, lb_type: str) -> List[Dict]:
        """Get tags for a load balancer"""
        try:
            if lb_type == 'classic':
                response = elb_client.describe_tags(LoadBalancerNames=[lb_name])
                tag_descriptions = response.get('TagDescriptions', [])
                if tag_descriptions:
                    return tag_descriptions[0].get('Tags', [])
            return []
        except Exception as e:
            self.log_operation('WARNING', f"Could not get tags for {lb_type} LB {lb_name}: {e}")
            return []

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
        """Get all load balancers (Classic, Application, Network) in a specific region with enhanced Kubernetes detection"""
        try:
            load_balancers = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"{Symbols.SCAN} Scanning for load balancers in {region} ({account_name})")
            print(f"   {Symbols.SCAN} Scanning for load balancers in {region} ({account_name})...")

            # Counters for different types
            classic_count = 0
            alb_count = 0
            nlb_count = 0
            kubernetes_count = 0

            # Get Classic Load Balancers with enhanced Kubernetes detection
            try:
                paginator = elb_client.get_paginator('describe_load_balancers')
                for page in paginator.paginate():
                    for lb in page['LoadBalancerDescriptions']:
                        lb_name = lb['LoadBalancerName']
                        lb_dns = lb['DNSName']
                        vpc_id = lb.get('VpcId', 'EC2-Classic')
                        scheme = lb['Scheme']

                        # Get tags for this load balancer
                        lb_tags = self.get_load_balancer_tags(elb_client, lb_name, 'classic')

                        # Get description if available
                        lb_description = lb.get('LoadBalancerDescription', '')

                        # Check if this is Kubernetes-managed
                        k8s_info = self.is_kubernetes_managed_elb(lb_name, lb_tags, lb_description)

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
                            'created_time': lb.get('CreatedTime'),
                            'tags': lb_tags,
                            'kubernetes_info': k8s_info
                        }

                        load_balancers.append(lb_info)
                        classic_count += 1

                        if k8s_info['is_kubernetes']:
                            kubernetes_count += 1
                            self.log_operation('INFO',
                                               f"{Symbols.TARGET} Kubernetes Classic ELB detected: {lb_name} "
                                               f"(method: {k8s_info['detection_method']}, "
                                               f"confidence: {k8s_info['confidence']})")
                            if k8s_info['cluster_name']:
                                self.log_operation('INFO', f"   Cluster: {k8s_info['cluster_name']}")
                            if k8s_info['service_name']:
                                self.log_operation('INFO', f"   Service: {k8s_info['service_name']}")

            except Exception as e:
                self.log_operation('WARNING', f"Error getting Classic Load Balancers: {e}")

            # Get Application and Network Load Balancers (ELBv2) with Kubernetes detection
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

                        # Get tags for ALB/NLB
                        lb_tags = []
                        try:
                            tags_response = elbv2_client.describe_tags(ResourceArns=[lb_arn])
                            tag_descriptions = tags_response.get('TagDescriptions', [])
                            if tag_descriptions:
                                lb_tags = tag_descriptions[0].get('Tags', [])
                        except Exception as e:
                            self.log_operation('WARNING', f"Could not get tags for {lb_type} LB {lb_name}: {e}")

                        # Check if this is Kubernetes-managed
                        k8s_info = self.is_kubernetes_managed_elb(lb_name, lb_tags)

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
                            'created_time': lb.get('CreatedTime'),
                            'tags': lb_tags,
                            'kubernetes_info': k8s_info
                        }

                        load_balancers.append(lb_info)

                        if lb_type == 'application':
                            alb_count += 1
                        elif lb_type == 'network':
                            nlb_count += 1

                        if k8s_info['is_kubernetes']:
                            kubernetes_count += 1
                            self.log_operation('INFO',
                                               f"{Symbols.TARGET} Kubernetes {lb_type.upper()} detected: {lb_name} "
                                               f"(method: {k8s_info['detection_method']}, "
                                               f"confidence: {k8s_info['confidence']})")

            except Exception as e:
                self.log_operation('WARNING', f"Error getting ALB/NLB Load Balancers: {e}")

            # Enhanced logging with breakdown
            self.log_operation('INFO',
                               f"[BALANCE]  Found {len(load_balancers)} total load balancers in {region} ({account_name})")
            self.log_operation('INFO', f"   {Symbols.STATS} Classic ELBs: {classic_count}")
            self.log_operation('INFO', f"   {Symbols.STATS} Application LBs: {alb_count}")
            self.log_operation('INFO', f"   {Symbols.STATS} Network LBs: {nlb_count}")
            self.log_operation('INFO', f"   {Symbols.TARGET} Kubernetes-managed: {kubernetes_count}")

            print(f"   [BALANCE]  Found {len(load_balancers)} load balancers ({classic_count} Classic, "
                  f"{alb_count} ALB, {nlb_count} NLB, {kubernetes_count} Kubernetes-managed)")

            return load_balancers

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting load balancers in {region} ({account_name}): {e}")
            print(f"   {Symbols.ERROR} Error getting load balancers in {region}: {e}")
            return []

    def get_all_target_groups_in_region(self, elbv2_client, region, account_info):
        """Get all target groups in a specific region"""
        try:
            target_groups = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"{Symbols.SCAN} Scanning for target groups in {region} ({account_name})")
            print(f"   {Symbols.SCAN} Scanning for target groups in {region} ({account_name})...")

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

            self.log_operation('INFO', f"{Symbols.TARGET} Found {len(target_groups)} target groups in {region} ({account_name})")
            print(f"   {Symbols.TARGET} Found {len(target_groups)} target groups in {region} ({account_name})")

            return target_groups

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting target groups in {region} ({account_name}): {e}")
            print(f"   {Symbols.ERROR} Error getting target groups in {region}: {e}")
            return []

    def get_elb_security_groups_in_region(self, ec2_client, load_balancers, region, account_info):
        """Get ONLY security groups attached to load balancers (excluding default)"""
        try:
            elb_security_groups = []
            processed_sg_ids = set()
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"{Symbols.SCAN} Scanning for ELB security groups in {region} ({account_name})")
            print(f"   {Symbols.SCAN} Scanning for ELB security groups in {region} ({account_name})...")

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
                               f"{Symbols.PROTECTED}  Found {len(elb_security_groups)} ELB security groups in {region} ({account_name})")
            print(f"   {Symbols.PROTECTED}  Found {len(elb_security_groups)} ELB security groups in {region} ({account_name})")

            return elb_security_groups

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting ELB security groups in {region} ({account_name}): {e}")
            print(f"   {Symbols.ERROR} Error getting ELB security groups in {region}: {e}")
            return []

    def delete_load_balancer(self, elb_client, elbv2_client, lb_info):
        """Delete a load balancer (Classic, Application, or Network) with enhanced Kubernetes handling"""
        try:
            lb_name = lb_info['name']
            lb_type = lb_info['type']
            region = lb_info['region']
            account_name = lb_info['account_info'].get('account_key', 'Unknown')
            k8s_info = lb_info.get('kubernetes_info', {})

            # Enhanced logging for Kubernetes load balancers
            if k8s_info.get('is_kubernetes'):
                self.log_operation('INFO',
                                   f"{Symbols.DELETE}  Deleting Kubernetes-managed {lb_type} load balancer {lb_name} in {region} ({account_name})")
                self.log_operation('INFO',
                                   f"   Detection method: {k8s_info.get('detection_method')}, "
                                   f"confidence: {k8s_info.get('confidence')}")
                if k8s_info.get('cluster_name'):
                    self.log_operation('INFO', f"   Cluster: {k8s_info['cluster_name']}")
                if k8s_info.get('service_name'):
                    self.log_operation('INFO', f"   Service: {k8s_info['service_name']}")
                print(f"   {Symbols.DELETE}  Deleting Kubernetes {lb_type} load balancer {lb_name}...")
            else:
                self.log_operation('INFO',
                                   f"{Symbols.DELETE}  Deleting {lb_type} load balancer {lb_name} in {region} ({account_name})")
                print(f"   {Symbols.DELETE}  Deleting {lb_type} load balancer {lb_name}...")

            # Add retry logic for Kubernetes load balancers that might be in transitional states
            max_retries = 3 if k8s_info.get('is_kubernetes') else 1
            retry_delay = 10

            for attempt in range(max_retries):
                try:
                    if lb_type == 'classic':
                        # Delete Classic Load Balancer
                        elb_client.delete_load_balancer(LoadBalancerName=lb_name)
                    else:
                        # Delete Application/Network Load Balancer
                        elbv2_client.delete_load_balancer(LoadBalancerArn=lb_info['arn'])

                    self.log_operation('INFO', f"{Symbols.OK} Successfully deleted {lb_type} load balancer {lb_name}")
                    print(f"   {Symbols.OK} Successfully deleted {lb_type} load balancer {lb_name}")

                    # Enhanced cleanup results tracking
                    deletion_record = {
                        'name': lb_name,
                        'type': lb_type,
                        'dns_name': lb_info['dns_name'],
                        'vpc_id': lb_info['vpc_id'],
                        'security_groups': lb_info['security_groups'],
                        'scheme': lb_info['scheme'],
                        'region': region,
                        'account_info': lb_info['account_info'],
                        'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'is_kubernetes': k8s_info.get('is_kubernetes', False),
                        'kubernetes_info': k8s_info
                    }

                    self.cleanup_results['deleted_load_balancers'].append(deletion_record)
                    return True

                except ClientError as e:
                    error_code = e.response['Error']['Code']

                    if error_code == 'LoadBalancerNotFound':
                        self.log_operation('INFO', f"Load balancer {lb_name} already deleted")
                        return True
                    elif error_code in ['InvalidLoadBalancerName', 'ValidationError'] and attempt < max_retries - 1:
                        self.log_operation('WARNING',
                                           f"Load balancer {lb_name} in transitional state, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise

                except Exception as e:
                    if attempt < max_retries - 1:
                        self.log_operation('WARNING',
                                           f"Error deleting {lb_name}, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries}): {e}")
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise

        except Exception as e:
            account_name = lb_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to delete load balancer {lb_name}: {e}")
            print(f"   {Symbols.ERROR} Failed to delete load balancer {lb_name}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'load_balancer',
                'resource_id': lb_name,
                'region': region,
                'account_info': lb_info['account_info'],
                'error': str(e),
                'is_kubernetes': k8s_info.get('is_kubernetes', False),
                'kubernetes_info': k8s_info
            })
            return False

    def delete_target_group(self, elbv2_client, tg_info):
        """Delete a target group"""
        try:
            tg_name = tg_info['name']
            tg_arn = tg_info['arn']
            region = tg_info['region']
            account_name = tg_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"{Symbols.DELETE}  Deleting target group {tg_name} in {region} ({account_name})")
            print(f"   {Symbols.DELETE}  Deleting target group {tg_name}...")

            elbv2_client.delete_target_group(TargetGroupArn=tg_arn)

            self.log_operation('INFO', f"{Symbols.OK} Successfully deleted target group {tg_name}")
            print(f"   {Symbols.OK} Successfully deleted target group {tg_name}")

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
            print(f"   {Symbols.ERROR} Failed to delete target group {tg_name}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'target_group',
                'resource_id': tg_name,
                'region': region,
                'account_info': tg_info['account_info'],
                'error': str(e)
            })
            return False

    def clear_security_group_rules(self, ec2_client, sg_id):
        """Clear all ingress and egress rules from a security group"""
        try:
            self.log_operation('INFO', f"{Symbols.CLEANUP} Clearing rules for security group {sg_id}")

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

            # Clear ingress rules
            if ingress_rules:
                self.log_operation('INFO', f"Removing {len(ingress_rules)} ingress rules from {sg_id} ({sg_name})")

                for rule_index, rule in enumerate(ingress_rules):
                    try:
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

            # Clear non-default egress rules
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
                            self.log_operation('INFO', f"  {Symbols.OK} Successfully removed egress rule {rule_index + 1}")

                        except ClientError as e:
                            error_code = e.response['Error']['Code']
                            if error_code == 'InvalidGroupId.NotFound':
                                self.log_operation('INFO', f"  Security group {sg_id} no longer exists")
                                return True
                            elif error_code == 'InvalidPermission.NotFound':
                                self.log_operation('INFO', f"  Egress rule {rule_index + 1} already removed")
                                rules_cleared += 1

            # Wait briefly for rule changes to propagate
            if rules_cleared > 0:
                self.log_operation('INFO', f"Waiting 5 seconds for rule changes to propagate...")
                time.sleep(5)

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Error clearing rules for security group {sg_id}: {e}")
            return False

    def delete_security_group(self, ec2_client, sg_info):
        """Delete a security group after clearing its rules"""
        try:
            sg_id = sg_info['group_id']
            sg_name = sg_info['group_name']
            region = sg_info['region']
            account_name = sg_info['account_info'].get('account_key', 'Unknown')

            self.log_operation('INFO', f"{Symbols.DELETE}  Deleting security group {sg_id} ({sg_name}) in {region} ({account_name})")
            print(f"   {Symbols.DELETE}  Deleting security group {sg_id} ({sg_name})...")

            # Step 1: Clear all security group rules first
            self.log_operation('INFO', f"Step 1: Clearing security group rules for {sg_id}")
            self.clear_security_group_rules(ec2_client, sg_id)

            # Step 2: Delete the security group
            self.log_operation('INFO', f"Step 2: Attempting to delete security group {sg_id}")
            ec2_client.delete_security_group(GroupId=sg_id)

            self.log_operation('INFO', f"{Symbols.OK} Successfully deleted security group {sg_id} ({sg_name})")
            print(f"   {Symbols.OK} Successfully deleted security group {sg_id}")

            self.cleanup_results['deleted_security_groups'].append({
                'group_id': sg_id,
                'group_name': sg_name,
                'description': sg_info['description'],
                'vpc_id': sg_info['vpc_id'],
                'was_attached': sg_info['is_attached'],
                'attached_load_balancers': sg_info.get('attached_load_balancers', []),
                'region': region,
                'account_info': sg_info['account_info'],
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidGroupId.NotFound':
                self.log_operation('INFO', f"Security group {sg_id} does not exist")
                return True
            elif error_code == 'DependencyViolation':
                self.log_operation('WARNING',
                                   f"Cannot delete security group {sg_id}: dependency violation (still in use)")
                print(f"   {Symbols.WARN} Cannot delete security group {sg_id}: still in use")
                return False
            else:
                self.log_operation('ERROR', f"Failed to delete security group {sg_id}: {e}")
                print(f"   {Symbols.ERROR} Failed to delete security group {sg_id}: {e}")
                return False
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error deleting security group {sg_id}: {e}")
            print(f"   {Symbols.ERROR} Unexpected error deleting security group {sg_id}: {e}")
            return False

    def cleanup_account_region(self, account_info, region):
        """Clean up ONLY ELB-related resources in a specific account and region"""
        try:
            access_key = account_info['access_key']
            secret_key = account_info['secret_key']
            account_id = account_info['account_id']
            account_key = account_info['account_key']

            self.log_operation('INFO', f"{Symbols.CLEANUP} Starting ELB cleanup for {account_key} ({account_id}) in {region}")
            print(f"\n{Symbols.CLEANUP} Starting ELB cleanup for {account_key} ({account_id}) in {region}")

            # Create AWS clients
            ec2_client, elb_client, elbv2_client = self.create_aws_clients(access_key, secret_key, region)

            # Initialize variables
            load_balancers = []
            target_groups = []
            elb_security_groups = []

            try:
                # Get all load balancers
                load_balancers = self.get_all_load_balancers_in_region(elb_client, elbv2_client, region, account_info)

                # Get all target groups
                target_groups = self.get_all_target_groups_in_region(elbv2_client, region, account_info)

                # Get ONLY security groups attached to load balancers
                elb_security_groups = self.get_elb_security_groups_in_region(ec2_client, load_balancers, region,
                                                                             account_info)

            except Exception as discovery_error:
                self.log_operation('ERROR',
                                   f"Error during resource discovery in {account_key} ({region}): {discovery_error}")
                print(f"   {Symbols.ERROR} Error during resource discovery: {discovery_error}")
                # Continue with whatever we managed to discover

            # Count Kubernetes-managed load balancers
            kubernetes_lbs = [lb for lb in load_balancers if lb.get('kubernetes_info', {}).get('is_kubernetes', False)]

            region_summary = {
                'account_key': account_key,
                'account_id': account_id,
                'region': region,
                'load_balancers_found': len(load_balancers),
                'kubernetes_load_balancers_found': len(kubernetes_lbs),
                'target_groups_found': len(target_groups),
                'elb_security_groups_found': len(elb_security_groups)
            }

            self.cleanup_results['regions_processed'].append(region_summary)

            self.log_operation('INFO', f"{Symbols.STATS} {account_key} ({region}) ELB resources summary:")
            self.log_operation('INFO', f"   [BALANCE]  Load Balancers: {len(load_balancers)}")
            self.log_operation('INFO', f"   {Symbols.TARGET} Kubernetes LBs: {len(kubernetes_lbs)}")
            self.log_operation('INFO', f"   {Symbols.TARGET} Target Groups: {len(target_groups)}")
            self.log_operation('INFO', f"   {Symbols.PROTECTED}  ELB Security Groups: {len(elb_security_groups)}")

            print(
                f"   {Symbols.STATS} ELB resources found: {len(load_balancers)} LBs ({len(kubernetes_lbs)} K8s), "
                f"{len(target_groups)} TGs, {len(elb_security_groups)} SGs")

            if not load_balancers and not target_groups and not elb_security_groups:
                self.log_operation('INFO', f"No ELB resources found in {account_key} ({region})")
                print(f"   {Symbols.OK} No ELB resources to clean up in {region}")
                return True

            # Step 1: Delete Load Balancers sequentially
            if load_balancers:
                self.log_operation('INFO',
                                   f"{Symbols.DELETE}  Deleting {len(load_balancers)} load balancers in {account_key} ({region})")
                print(f"\n   {Symbols.DELETE}  Deleting {len(load_balancers)} load balancers...")

                deleted_count = 0
                failed_count = 0

                for i, lb in enumerate(load_balancers, 1):
                    lb_name = lb['name']
                    k8s_info = lb.get('kubernetes_info', {})

                    if k8s_info.get('is_kubernetes'):
                        print(f"   [{i}/{len(load_balancers)}] Processing Kubernetes load balancer {lb_name}...")
                    else:
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
                        print(f"   {Symbols.ERROR} Error deleting load balancer {lb_name}: {e}")

                print(f"   {Symbols.OK} Deleted {deleted_count} load balancers, {Symbols.ERROR} Failed: {failed_count}")

                # Wait for load balancers to be deleted
                if deleted_count > 0:
                    self.log_operation('INFO', f"[WAIT] Waiting 30 seconds for load balancers to be deleted...")
                    print(f"   [WAIT] Waiting 30 seconds for load balancers to be deleted...")
                    time.sleep(30)

            # Step 2: Delete Target Groups sequentially
            if target_groups:
                self.log_operation('INFO',
                                   f"{Symbols.DELETE}  Deleting {len(target_groups)} target groups in {account_key} ({region})")
                print(f"\n   {Symbols.DELETE}  Deleting {len(target_groups)} target groups...")

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
                        print(f"   {Symbols.ERROR} Error deleting target group {tg_name}: {e}")

                print(f"   {Symbols.OK} Deleted {deleted_count} target groups, {Symbols.ERROR} Failed: {failed_count}")

            # Step 3: Delete ONLY security groups that were attached to load balancers
            if elb_security_groups:
                self.log_operation('INFO',
                                   f"{Symbols.DELETE}  Deleting {len(elb_security_groups)} ELB security groups in {account_key} ({region})")
                print(f"\n   {Symbols.DELETE}  Deleting {len(elb_security_groups)} ELB security groups...")

                max_retries = 3
                retry_delay = 15

                remaining_sgs = elb_security_groups.copy()

                for retry in range(max_retries):
                    self.log_operation('INFO', f"{Symbols.SCAN} Security group deletion attempt {retry + 1}/{max_retries}")
                    print(f"   {Symbols.SCAN} Security group deletion attempt {retry + 1}/{max_retries}")

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
                                                   f"{Symbols.OK} Deleted ELB security group {sg_id} in attempt {retry + 1}")
                            else:
                                still_remaining.append(sg)
                                self.log_operation('WARNING',
                                                   f"[WAIT] ELB security group {sg_id} still has dependencies, will retry")
                        except Exception as e:
                            self.log_operation('ERROR', f"Error deleting ELB security group {sg_id}: {e}")
                            print(f"   {Symbols.ERROR} Error deleting ELB security group {sg_id}: {e}")
                            still_remaining.append(sg)

                    print(
                        f"   {Symbols.OK} Deleted {sgs_deleted_this_round} ELB security groups in attempt {retry + 1}, {len(still_remaining)} remaining")

                    remaining_sgs = still_remaining

                    if not remaining_sgs:
                        self.log_operation('INFO', f"{Symbols.OK} All ELB security groups deleted in {account_key} ({region})")
                        print(f"   {Symbols.OK} All ELB security groups deleted successfully!")
                        break

                    if retry < max_retries - 1 and remaining_sgs:
                        self.log_operation('INFO', f"[WAIT] Waiting {retry_delay}s before retry {retry + 2}/{max_retries}")
                        print(f"   [WAIT] Waiting {retry_delay}s before next retry...")
                        time.sleep(retry_delay)

                if remaining_sgs:
                    self.log_operation('WARNING',
                                       f"{Symbols.WARN}  {len(remaining_sgs)} ELB security groups could not be deleted after {max_retries} retries")
                    print(
                        f"   {Symbols.WARN}  {len(remaining_sgs)} ELB security groups could not be deleted after {max_retries} retries")

            self.log_operation('INFO', f"{Symbols.OK} ELB cleanup completed for {account_key} ({region})")
            print(f"\n   {Symbols.OK} ELB cleanup completed for {account_key} ({region})")
            return True

        except Exception as e:
            account_key = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error cleaning up ELB resources in {account_key} ({region}): {e}")
            print(f"   {Symbols.ERROR} Error cleaning up ELB resources in {account_key} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_info': account_info,
                'region': region,
                'error': str(e)
            })
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_elb_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_lbs_deleted = len(self.cleanup_results['deleted_load_balancers'])
            total_k8s_lbs_deleted = len([lb for lb in self.cleanup_results['deleted_load_balancers']
                                         if lb.get('is_kubernetes', False)])
            total_tgs_deleted = len(self.cleanup_results['deleted_target_groups'])
            total_sgs_deleted = len(self.cleanup_results['deleted_security_groups'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_ELB_CLEANUP_SIMPLIFIED",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                    "regions_processed": self.user_regions,
                    "kubernetes_enhanced": True,
                    "scope": "load_balancers_target_groups_security_groups_only"
                },
                "summary": {
                    "total_accounts_processed": len(
                        set(rp['account_key'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(
                        set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_load_balancers_deleted": total_lbs_deleted,
                    "total_kubernetes_load_balancers_deleted": total_k8s_lbs_deleted,
                    "total_target_groups_deleted": total_tgs_deleted,
                    "total_security_groups_deleted": total_sgs_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped
                },
                "detailed_results": {
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_load_balancers": self.cleanup_results['deleted_load_balancers'],
                    "deleted_target_groups": self.cleanup_results['deleted_target_groups'],
                    "deleted_security_groups": self.cleanup_results['deleted_security_groups'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }

            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation('INFO', f"{Symbols.OK} Ultra ELB cleanup report saved to: {report_filename}")
            return report_filename

        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to save ultra ELB cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - simplified scope"""
        try:
            self.log_operation('INFO', f"{Symbols.ALERT} STARTING SIMPLIFIED ELB CLEANUP SESSION {Symbols.ALERT}")

            self.print_colored(Colors.YELLOW, f"{Symbols.ALERT}" * 30)
            self.print_colored(Colors.BLUE, f"{Symbols.START} SIMPLIFIED ELB CLEANUP - KUBERNETES ENHANCED")
            self.print_colored(Colors.YELLOW, f"{Symbols.ALERT}" * 30)
            self.print_colored(Colors.WHITE, f"{Symbols.DATE} Execution Date/Time: {self.current_time} UTC")
            self.print_colored(Colors.WHITE, f"[USER] Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"{Symbols.LIST} Log File: {self.log_filename}")
            self.print_colored(Colors.GREEN, f"{Symbols.TARGET} Enhanced Kubernetes ELB Detection: ENABLED")
            self.print_colored(Colors.CYAN, f"{Symbols.TARGET} Simplified Scope: Load Balancers + Target Groups + Security Groups ONLY")

            # STEP 1: Select root accounts
            self.print_colored(Colors.YELLOW, "\n[KEY] Select Root AWS Accounts for ELB Cleanup:")

            root_accounts = self.cred_manager.select_root_accounts_interactive(allow_multiple=True)
            if not root_accounts:
                self.print_colored(Colors.RED, "[ERROR] No root accounts selected, exiting...")
                return
            selected_accounts = root_accounts

            # STEP 2: Select regions
            selected_regions = self.cred_manager.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.RED, "[ERROR] No regions selected, exiting...")
                return

            # STEP 3: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(selected_regions)

            self.print_colored(Colors.YELLOW, f"\n{Symbols.TARGET} SIMPLIFIED ELB CLEANUP CONFIGURATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"{Symbols.KEY} Credential source: ROOT ACCOUNTS")
            self.print_colored(Colors.WHITE, f"{Symbols.ACCOUNT} Selected accounts: {len(selected_accounts)}")
            self.print_colored(Colors.WHITE, f"{Symbols.REGION} Regions per account: {len(selected_regions)}")
            self.print_colored(Colors.WHITE, f"{Symbols.LIST} Total operations: {total_operations}")
            self.print_colored(Colors.GREEN, f"{Symbols.TARGET} Kubernetes ELB Detection: ENHANCED")
            self.print_colored(Colors.CYAN, f"{Symbols.TARGET} Scope: SIMPLIFIED - LBs + TGs + SGs ONLY")
            self.print_colored(Colors.YELLOW, "=" * 80)

            # Show what will be cleaned up
            self.print_colored(Colors.RED, f"\n{Symbols.WARN}  WARNING: This will delete the following ELB resources ONLY:")
            self.print_colored(Colors.WHITE, f"    • Classic Load Balancers (ELB) - INCLUDING Kubernetes-managed")
            self.print_colored(Colors.WHITE, f"    • Application Load Balancers (ALB)")
            self.print_colored(Colors.WHITE, f"    • Network Load Balancers (NLB)")
            self.print_colored(Colors.WHITE, f"    • Target Groups")
            self.print_colored(Colors.WHITE, f"    • Security Groups attached to Load Balancers ONLY")
            self.print_colored(Colors.GREEN, f"    {Symbols.OK} VPCs, subnets, and other resources will be LEFT ALONE")
            self.print_colored(Colors.GREEN, f"    {Symbols.TARGET} Enhanced detection for Kubernetes-managed load balancers")
            self.print_colored(Colors.WHITE,
                               f"    across {len(selected_accounts)} accounts in {len(selected_regions)} regions ({total_operations} operations)")
            self.print_colored(Colors.RED, f"    This action CANNOT be undone!")

            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with simplified ELB cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")

            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Simplified ELB cleanup cancelled by user")
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Cleanup cancelled")
                return

            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")

            if confirm2 != 'yes':
                self.log_operation('INFO', "Simplified ELB cleanup cancelled at final confirmation")
                self.print_colored(Colors.RED, f"{Symbols.ERROR} Cleanup cancelled")
                return

            # STEP 4: Start the cleanup sequentially
            self.print_colored(Colors.CYAN, f"\n{Symbols.START} Starting simplified Kubernetes-enhanced ELB cleanup...")
            self.log_operation('INFO',
                               f"{Symbols.ALERT} SIMPLIFIED ELB CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(selected_regions)} regions")

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
                    self.print_colored(Colors.RED, f"{Symbols.ERROR} Task failed for {account_key} ({region}): {e}")

            end_time = time.time()
            total_time = int(end_time - start_time)

            # Calculate Kubernetes-specific statistics
            total_k8s_lbs = len([lb for lb in self.cleanup_results['deleted_load_balancers']
                                 if lb.get('is_kubernetes', False)])

            # STEP 5: Display final results
            self.print_colored(Colors.GREEN, f"\n" + "=" * 100)
            self.print_colored(Colors.GREEN, "[OK] SIMPLIFIED ELB CLEANUP COMPLETE")
            self.print_colored(Colors.GREEN, "=" * 100)
            self.print_colored(Colors.WHITE, f"{Symbols.TIMER}  Total execution time: {total_time} seconds")
            self.print_colored(Colors.GREEN, f"{Symbols.OK} Successful operations: {successful_tasks}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed operations: {failed_tasks}")
            self.print_colored(Colors.WHITE,
                               f"[BALANCE]  Load balancers deleted: {len(self.cleanup_results['deleted_load_balancers'])}")
            self.print_colored(Colors.GREEN, f"{Symbols.TARGET} Kubernetes LBs deleted: {total_k8s_lbs}")
            self.print_colored(Colors.WHITE,
                               f"{Symbols.TARGET} Target groups deleted: {len(self.cleanup_results['deleted_target_groups'])}")
            self.print_colored(Colors.WHITE,
                               f"{Symbols.PROTECTED}  Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            self.print_colored(Colors.RED, f"{Symbols.ERROR} Failed deletions: {len(self.cleanup_results['failed_deletions'])}")

            self.log_operation('INFO', f"SIMPLIFIED ELB CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Load balancers deleted: {len(self.cleanup_results['deleted_load_balancers'])}")
            self.log_operation('INFO', f"Kubernetes load balancers deleted: {total_k8s_lbs}")
            self.log_operation('INFO', f"Target groups deleted: {len(self.cleanup_results['deleted_target_groups'])}")
            self.log_operation('INFO', f"Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")

            # STEP 6: Show account summary
            if (self.cleanup_results['deleted_load_balancers'] or
                    self.cleanup_results['deleted_target_groups'] or
                    self.cleanup_results['deleted_security_groups']):

                self.print_colored(Colors.YELLOW, f"\n{Symbols.STATS} Deletion Summary by Account:")

                # Group by account
                account_summary = {}

                for lb in self.cleanup_results['deleted_load_balancers']:
                    account = lb['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'kubernetes_lbs': 0, 'target_groups': 0,
                            'security_groups': 0, 'regions': set()
                        }
                    account_summary[account]['load_balancers'] += 1
                    if lb.get('is_kubernetes', False):
                        account_summary[account]['kubernetes_lbs'] += 1
                    account_summary[account]['regions'].add(lb['region'])

                for tg in self.cleanup_results['deleted_target_groups']:
                    account = tg['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'kubernetes_lbs': 0, 'target_groups': 0,
                            'security_groups': 0, 'regions': set()
                        }
                    account_summary[account]['target_groups'] += 1
                    account_summary[account]['regions'].add(tg['region'])

                for sg in self.cleanup_results['deleted_security_groups']:
                    account = sg['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'load_balancers': 0, 'kubernetes_lbs': 0, 'target_groups': 0,
                            'security_groups': 0, 'regions': set()
                        }
                    account_summary[account]['security_groups'] += 1
                    account_summary[account]['regions'].add(sg['region'])

                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.PURPLE, f"   {Symbols.ACCOUNT} {account}:")
                    self.print_colored(Colors.WHITE, f"      [BALANCE]  Load Balancers: {summary['load_balancers']}")
                    if summary['kubernetes_lbs'] > 0:
                        self.print_colored(Colors.GREEN, f"      {Symbols.TARGET} Kubernetes LBs: {summary['kubernetes_lbs']}")
                    self.print_colored(Colors.WHITE, f"      {Symbols.TARGET} Target Groups: {summary['target_groups']}")
                    self.print_colored(Colors.WHITE, f"      {Symbols.PROTECTED}  Security Groups: {summary['security_groups']}")
                    self.print_colored(Colors.WHITE, f"      {Symbols.REGION} Regions: {regions_list}")

            # STEP 7: Show failures if any
            if self.cleanup_results['failed_deletions']:
                self.print_colored(Colors.RED, f"\n{Symbols.ERROR} Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    account_key = failure['account_info'].get('account_key', 'Unknown')
                    self.print_colored(Colors.WHITE,
                                       f"   • {failure['resource_type']} {failure['resource_id']} in {account_key} ({failure['region']})")
                    self.print_colored(Colors.WHITE, f"     Error: {failure['error']}")

                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    self.print_colored(Colors.WHITE, f"   ... and {remaining} more failures (see detailed report)")

            # Save comprehensive report
            self.print_colored(Colors.CYAN, f"\n[FILE] Saving simplified ELB cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"{Symbols.OK} ELB cleanup report saved to: {report_file}")

            self.print_colored(Colors.GREEN, f"{Symbols.OK} Session log saved to: {self.log_filename}")

            self.print_colored(Colors.GREEN, f"\n{Symbols.OK} Simplified Kubernetes-enhanced ELB cleanup completed successfully!")
            self.print_colored(Colors.YELLOW, "[ALERT]" * 30)

        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in simplified ELB cleanup execution: {str(e)}")
            self.print_colored(Colors.RED, f"\n{Symbols.ERROR} FATAL ERROR: {e}")
            traceback.print_exc()
            raise

def main():
    """Main function"""
    try:
        manager = UltraCleanupELBManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] ELB cleanup interrupted by user")
        exit(1)
    except Exception as e:
        print(f"{Symbols.ERROR} Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()

