#!/usr/bin/env python3
"""
EKS Cluster Manager - Enhanced for Phase 2
Handles EKS cluster creation with on-demand, spot, and mixed nodegroup strategies
"""

import json
import os
import time
from os import environ
import re
import textwrap

import boto3

from datetime import datetime
from typing import Dict, Optional

import yaml

import subprocess
import random
import string
from typing import List, Tuple, Set
from aws_credential_manager import CredentialInfo

import tempfile
import requests
from jinja2 import Environment, FileSystemLoader
import logging
from logging.handlers import RotatingFileHandler
from complete_autoscaler_deployment import CompleteAutoscalerDeployer


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    WHITE = '\033[1;37m'
    NC = '\033[0m'  # No Color

class EKSClusterManager:
    def __init__(self, config_file=None, current_user='varadharajaan'):
            """Initialize the EKS Cluster Manager"""
            self.config_file = config_file
            self.current_user = current_user
            self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.eks_ssh_keypair_name = "k8s_demo_key"
        
            # Setup logging
            self.setup_logging()
        
            self.load_configuration()
    
    def setup_logging(self):
        """Set up proper logging with file and console handlers, capturing all output"""
        # Create logs directory if it doesn't exist
        log_dir = "logs/eks"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
    
        # Configure the main logger
        self.logger = logging.getLogger("eks_cluster_manager")
        self.logger.setLevel(logging.DEBUG)
    
        # Clear any existing handlers
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
    
        # Generate timestamp and create log filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.execution_timestamp = timestamp
        log_file = os.path.join(log_dir, f"eks_cluster_creation_{timestamp}.log")
    
        # Create file handler which logs all messages
        file_handler = RotatingFileHandler(log_file, maxBytes=10485760, backupCount=5)  # 10MB max size
        file_handler.setLevel(logging.DEBUG)
    
        # Create console handler with a higher log level
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
    
        # Create formatters and add them to the handlers
        detailed_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(detailed_formatter)
    
        simple_formatter = logging.Formatter('[%(levelname)s] %(message)s')
        console_handler.setFormatter(simple_formatter)
    
        # Add handlers to the logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
        # Create stdout capture handler for capturing print statements
        import sys
    
        class PrintCaptureHandler(logging.StreamHandler):
            def __init__(self, log_file):
                super().__init__()
                self.log_file = log_file
                self.terminal = sys.stdout
            
            def emit(self, record):
                msg = self.format(record)
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(msg + '\n')
            
            def write(self, message):
                self.terminal.write(message)
                if message.strip():  # Skip empty lines
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        f.write(f"{timestamp} - CONSOLE - {message}\n")
                
            def flush(self):
                self.terminal.flush()
    
        # Replace sys.stdout with our capturing handler
        sys.stdout = PrintCaptureHandler(log_file)
    
        self.logger.info(f"EKS Cluster Manager initialized - Session ID: {self.execution_timestamp}")
        self.logger.info(f"Log file created: {log_file}")

    def load_configuration(self):
        """Load configuration from JSON file"""
        try:
            if self.config_file and os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config_data = json.load(f)
                print(f"✅ Configuration loaded from: {self.config_file}")
            else:
                self.config_data = {}
                print("📝 Using default configuration")
        except Exception as e:
            print(f"⚠️  Error loading configuration: {e}")
            self.config_data = {}

    def log_operation(self, level: str, message: str):
        """Enhanced logger that writes to both console and log file with proper levels"""
        if level == 'DEBUG':
            self.logger.debug(message)
        elif level == 'INFO':
            self.logger.info(message)
        elif level == 'WARNING':
            self.logger.warning(message)
        elif level == 'ERROR':
            self.logger.error(message)
        elif level == 'CRITICAL':
            self.logger.critical(message)
        else:
            self.logger.info(message)

    def render_fluentbit_configmap(self, cluster_name, region_name, http_server_toggle, http_server_port, read_from_head, read_from_tail):
        """
        Render the Fluent Bit ConfigMap YAML from a Jinja2 template.
        """
        template_dir = os.path.join(os.path.dirname(__file__), "k8s_manifests")
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template("fluent-bit-cluster-info.yaml.j2")
    
        # Convert boolean and numeric values to strings
        http_server_port = str(http_server_port)  # Convert to string
        read_from_head = str(read_from_head)  # Convert to string
        read_from_tail = str(read_from_tail)  # Convert to string
    
        rendered_yaml = template.render(
            cluster_name=cluster_name,
            region_name=region_name,
            http_server_toggle=http_server_toggle,
            http_server_port=http_server_port,
            read_from_head=read_from_head,
            read_from_tail=read_from_tail
        )
        return rendered_yaml

    def load_yaml_file(self, filename: str) -> str:
        """Load a YAML manifest from the k8s_manifests directory."""
        manifest_dir = os.path.join(os.path.dirname(__file__), "k8s_manifests")
        file_path = os.path.join(manifest_dir, filename)
        with open(file_path, "r") as f:
            return f.read()

    def get_cloudwatch_namespace_manifest_fixed(self) -> str:
        return self.load_yaml_file("cloudwatch-namespace.yaml")

    def get_cloudwatch_service_account_manifest_fixed(self) -> str:
        return self.load_yaml_file("cloudwatch-service-account.yaml")

    def get_cloudwatch_daemonset_manifest_fixed(self, cluster_name: str, region: str, account_id: str) -> str:
        """Load and prepare the cloudwatch-daemonset.yaml manifest with proper annotations"""
        # Load the template
        manifest = self.load_yaml_file("cloudwatch-daemonset.yaml")
    
        # Process the manifest to ensure the annotation is properly set
        import yaml
        try:
            # Parse YAML
            daemonset_yaml = yaml.safe_load(manifest)
        
            # Ensure annotations exist and add the required one
            if 'metadata' in daemonset_yaml:
                if 'annotations' not in daemonset_yaml['metadata']:
                    daemonset_yaml['metadata']['annotations'] = {}
                
                # Add or update the kubectl.kubernetes.io/last-applied-configuration annotation
                # This is required by kubectl apply
                daemonset_yaml['metadata']['annotations']['kubectl.kubernetes.io/last-applied-configuration'] = "{}"
            
                # Add a timestamp to make each deployment unique
                from datetime import datetime
                daemonset_yaml['metadata']['annotations']['deployment-timestamp'] = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # Convert back to YAML string
            updated_manifest = yaml.dump(daemonset_yaml)
            return updated_manifest
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to process DaemonSet manifest: {str(e)}")
            # Return original manifest if processing failed
            return manifest

    def generate_cluster_name(self, username: str, region: str) -> str:
        """Generate EKS cluster name with random 4-letter suffix"""
        # Generate 4 random lowercase letters
        random_suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
        return f"eks-cluster-{username}-{region}-{random_suffix}"
    
    def generate_nodegroup_name(self, cluster_name: str, strategy: str) -> str:
        """Generate nodegroup name based on strategy"""
        return f"{cluster_name}-ng-{strategy}"
   
    def get_application_signals_operator_manifest(self, cluster_name: str, region: str, account_id: str) -> str:
        """Load Application Signals operator manifest from YAML file"""
        try:
            manifest = self.load_yaml_file("application-signals-operator.yaml")
        
            # Replace placeholders
            manifest = manifest.replace("${CLUSTER_NAME}", cluster_name)
            manifest = manifest.replace("${AWS_REGION}", region)
            manifest = manifest.replace("${ACCOUNT_ID}", account_id)
        
            return manifest
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load Application Signals operator manifest: {str(e)}")
            return ""

    def get_adot_collector_manifest(self, cluster_name: str, region: str, account_id: str) -> str:
        """Load ADOT Collector manifest from YAML file"""
        try:
            manifest = self.load_yaml_file("adot-collector.yaml")
        
            # Replace placeholders
            manifest = manifest.replace("${CLUSTER_NAME}", cluster_name)
            manifest = manifest.replace("${AWS_REGION}", region)
            manifest = manifest.replace("${ACCOUNT_ID}", account_id)
        
            return manifest
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load ADOT Collector manifest: {str(e)}")
            return ""

    def get_auto_instrumentation_manifest(self, cluster_name: str, region: str) -> str:
        """Load auto-instrumentation manifest from YAML file"""
        try:
            manifest = self.load_yaml_file("auto-instrumentation.yaml")
        
            # Replace placeholders
            manifest = manifest.replace("${CLUSTER_NAME}", cluster_name)
            manifest = manifest.replace("${AWS_REGION}", region)
        
            return manifest
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load auto-instrumentation manifest: {str(e)}")
            return ""

    def enable_application_signals(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str, account_id: str) -> bool:
        """Enable CloudWatch Application Signals for comprehensive observability"""
        try:
            self.log_operation('INFO', f"Enabling CloudWatch Application Signals for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"📊 Enabling CloudWatch Application Signals for {cluster_name}...")
        
            # Check if kubectl is available
            import subprocess
            import shutil
        
            kubectl_available = shutil.which('kubectl') is not None
        
            if not kubectl_available:
                self.log_operation('WARNING', f"kubectl not found. Cannot deploy Application Signals for {cluster_name}")
                self.print_colored(Colors.YELLOW, f"⚠️  kubectl not found. Application Signals deployment skipped.")
                return False
        
            # Set environment variables for admin access
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = admin_access_key
            env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
            env['AWS_DEFAULT_REGION'] = region
        
            # Update kubeconfig first
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]
        
            self.print_colored(Colors.CYAN, "   🔄 Updating kubeconfig for Application Signals...")
            update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
        
            if update_result.returncode != 0:
                self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                self.print_colored(Colors.RED, f"❌ Failed to update kubeconfig: {update_result.stderr}")
                return False
        
            # Step 1: Create IAM role first
            self.print_colored(Colors.CYAN, "   🔐 Setting up IAM role for Application Signals...")
        
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            iam_client = admin_session.client('iam')
        
            role_arn = self.create_application_signals_iam_role(iam_client, account_id)
            if not role_arn:
                self.print_colored(Colors.YELLOW, "   ⚠️  IAM role creation failed, continuing with deployment...")
        
            # Step 2: Enable Application Signals service
            self.print_colored(Colors.CYAN, "   📡 Enabling Application Signals service...")
        
            try:
                enable_cmd = [
                    'aws', 'application-signals', 'start-discovery',
                    '--region', region
                ]
            
                enable_result = subprocess.run(enable_cmd, env=env, capture_output=True, text=True, timeout=120)
            
                if enable_result.returncode == 0:
                    self.print_colored(Colors.GREEN, "   ✅ Application Signals service enabled")
                    self.log_operation('INFO', f"Application Signals service enabled for {cluster_name}")
                else:
                    self.log_operation('WARNING', f"Application Signals service enablement failed: {enable_result.stderr}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️  Application Signals service enablement failed, continuing...")
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"   ⚠️  Could not enable Application Signals service: {str(e)}")
        
            # Step 3: Deploy Application Signals operator
            self.print_colored(Colors.CYAN, "   🚀 Deploying Application Signals operator...")
        
            operator_manifest = self.get_application_signals_operator_manifest(cluster_name, region, account_id)
            if not operator_manifest:
                self.print_colored(Colors.RED, "   ❌ Failed to load operator manifest")
                return False
        
            if self.apply_kubernetes_manifest_fixed(cluster_name, region, admin_access_key, admin_secret_key, operator_manifest):
                self.print_colored(Colors.GREEN, "   ✅ Application Signals operator deployed")
                self.log_operation('INFO', f"Application Signals operator deployed for {cluster_name}")
            else:
                self.print_colored(Colors.YELLOW, "   ⚠️  Application Signals operator deployment failed")
                return False
        
            # Wait for operator to be ready
            time.sleep(30)
        
            # Step 4: Deploy ADOT Collector
            self.print_colored(Colors.CYAN, "   📊 Deploying ADOT Collector for Application Signals...")
        
            adot_manifest = self.get_adot_collector_manifest(cluster_name, region, account_id)
            if not adot_manifest:
                self.print_colored(Colors.RED, "   ❌ Failed to load ADOT Collector manifest")
                return False
        
            if self.apply_kubernetes_manifest_fixed(cluster_name, region, admin_access_key, admin_secret_key, adot_manifest):
                self.print_colored(Colors.GREEN, "   ✅ ADOT Collector deployed")
                self.log_operation('INFO', f"ADOT Collector deployed for {cluster_name}")
            else:
                self.print_colored(Colors.YELLOW, "   ⚠️  ADOT Collector deployment failed")
                return False
        
            # Step 5: Deploy auto-instrumentation
            self.print_colored(Colors.CYAN, "   🔍 Deploying auto-instrumentation for all supported languages...")
        
            auto_instrumentation_manifest = self.get_auto_instrumentation_manifest(cluster_name, region)
            if not auto_instrumentation_manifest:
                self.print_colored(Colors.RED, "   ❌ Failed to load auto-instrumentation manifest")
                return False
        
            if self.apply_kubernetes_manifest_fixed(cluster_name, region, admin_access_key, admin_secret_key, auto_instrumentation_manifest):
                self.print_colored(Colors.GREEN, "   ✅ Auto-instrumentation deployed")
                self.log_operation('INFO', f"Auto-instrumentation deployed for {cluster_name}")
            else:
                self.print_colored(Colors.YELLOW, "   ⚠️  Auto-instrumentation deployment failed")
                return False
        
            # Step 6: Verify deployment
            self.print_colored(Colors.CYAN, "   ⏳ Verifying Application Signals deployment...")
            time.sleep(30)
        
            verify_cmd = ['kubectl', 'get', 'pods', '-n', 'aws-application-signals-system', '--no-headers']
            verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=60)
        
            if verify_result.returncode == 0:
                pod_lines = [line.strip() for line in verify_result.stdout.strip().split('\n') if line.strip()]
                running_pods = [line for line in pod_lines if 'Running' in line or 'Completed' in line]
            
                self.print_colored(Colors.GREEN, f"   ✅ Application Signals pods: {len(running_pods)} ready out of {len(pod_lines)} total")
                self.log_operation('INFO', f"Application Signals deployment verified: {len(running_pods)} pods ready")
            
                # Access information
                self.print_colored(Colors.CYAN, f"📊 Access Application Signals in AWS Console:")
                self.print_colored(Colors.CYAN, f"   CloudWatch → Application Signals → Services")
                self.print_colored(Colors.CYAN, f"   Filter by cluster: {cluster_name}")
                self.print_colored(Colors.CYAN, f"   Supported languages: Java, Python, .NET, Node.js, Go")
                self.print_colored(Colors.CYAN, f"")
                self.print_colored(Colors.CYAN, f"📋 To auto-instrument your applications, add this annotation:")
                self.print_colored(Colors.CYAN, f"   instrumentation.opentelemetry.io/inject-java: 'aws-application-signals-system/application-signals-instrumentation'")
                self.print_colored(Colors.CYAN, f"   (Replace 'java' with: python, nodejs, dotnet, or go as needed)")
            
                return True
            else:
                self.log_operation('WARNING', f"Could not verify Application Signals deployment")
                return True  # Still consider successful since deployment commands worked
        
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to enable Application Signals for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"❌ Application Signals deployment failed: {error_msg}")
            return False

    def create_application_signals_iam_role(self, iam_client, account_id: str) -> str:
        """Create IAM role for Application Signals using your existing pattern"""
        try:
            role_name = "ApplicationSignalsRole"
        
            # Trust policy for Application Signals
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "application-signals.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
        
            # Policy for Application Signals
            policy_document = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "application-signals:*",
                            "cloudwatch:PutMetricData",
                            "cloudwatch:GetMetricStatistics",
                            "cloudwatch:ListMetrics",
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                            "logs:DescribeLogGroups",
                            "logs:DescribeLogStreams",
                            "xray:PutTraceSegments",
                            "xray:PutTelemetryRecords",
                            "xray:GetSamplingRules",
                            "xray:GetSamplingTargets",
                            "xray:GetTraceGraph",
                            "xray:GetTraceSummaries"
                        ],
                        "Resource": "*"
                    }
                ]
            }
        
            try:
                # Create role
                role_response = iam_client.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="Role for AWS Application Signals"
                )
            
                # Create and attach policy
                policy_response = iam_client.create_policy(
                    PolicyName="ApplicationSignalsPolicy",
                    PolicyDocument=json.dumps(policy_document),
                    Description="Policy for AWS Application Signals"
                )
            
                iam_client.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy_response['Policy']['Arn']
                )
            
                self.log_operation('INFO', f"Created Application Signals IAM role: {role_response['Role']['Arn']}")
                return role_response['Role']['Arn']
            
            except iam_client.exceptions.EntityAlreadyExistsException:
                # Role already exists
                role_response = iam_client.get_role(RoleName=role_name)
                self.log_operation('INFO', f"Using existing Application Signals IAM role: {role_response['Role']['Arn']}")
                return role_response['Role']['Arn']
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create Application Signals IAM role: {str(e)}")
            return None

    #####
    def ensure_addon_service_roles(self, eks_client, cluster_name: str, account_id: str) -> None:
        """
        Ensure that the EBS CSI Driver, EFS CSI Driver, and VPC CNI add-ons
        have the NodeInstanceRole as their service account role if not already set.
        """
        addon_names = ['aws-ebs-csi-driver', 'aws-efs-csi-driver', 'vpc-cni']
        node_role_arn = f"arn:aws:iam::{account_id}:role/NodeInstanceRole"

        for addon_name in addon_names:
            try:
                addon = eks_client.describe_addon(clusterName=cluster_name, addonName=addon_name)['addon']
                current_role = addon.get('serviceAccountRoleArn')
                if current_role and not current_role == None:
                    self.log_operation('INFO', f"{addon_name}: serviceAccountRoleArn already set ({current_role}), skipping.")
                    continue

                self.log_operation('INFO', f"{addon_name}: serviceAccountRoleArn not set, applying NodeInstanceRole.")
                eks_client.update_addon(
                    clusterName=cluster_name,
                    addonName=addon_name,
                    serviceAccountRoleArn=node_role_arn,
                    resolveConflicts='OVERWRITE'
                )
                self.print_colored(Colors.GREEN, f"✅ Applied NodeInstanceRole to {addon_name}")
            except eks_client.exceptions.ResourceNotFoundException:
                self.log_operation('WARNING', f"{addon_name} not found on cluster {cluster_name}, skipping.")
            except Exception as e:
                self.log_operation('ERROR', f"Failed to update {addon_name}: {str(e)}")

                self.print_colored(Colors.RED, f"❌ Failed to update {addon_name}: {str(e)}")

    def format_instance_types_summary(self, instance_selections: Dict) -> str:
        """Format instance types for summary display"""
        summary_parts = []
    
        if 'on-demand' in instance_selections and instance_selections['on-demand']:
            summary_parts.append(f"OnDemand: {', '.join(instance_selections['on-demand'])}")
    
        if 'spot' in instance_selections and instance_selections['spot']:
            summary_parts.append(f"Spot: {', '.join(instance_selections['spot'])}")
    
        if 'on_demand_percentage' in instance_selections:
            summary_parts.append(f"({instance_selections['on_demand_percentage']}% OnDemand)")
    
        return " | ".join(summary_parts) if summary_parts else "None"

    def select_subnets_for_nodegroup(self, all_subnet_ids: List[str], preference: str, ec2_client) -> List[str]:
        """Select subnets based on nodegroup preference"""
        if preference == "auto":
            return all_subnet_ids
    
        try:
            # Get subnet details to determine public/private
            subnets_response = ec2_client.describe_subnets(SubnetIds=all_subnet_ids)
        
            public_subnets = []
            private_subnets = []
        
            for subnet in subnets_response['Subnets']:
                subnet_id = subnet['SubnetId']
            
                # Check if subnet has a route to internet gateway (simplified check)
                route_tables = ec2_client.describe_route_tables(
                    Filters=[
                        {'Name': 'association.subnet-id', 'Values': [subnet_id]}
                    ]
                )
            
                is_public = False
                for rt in route_tables['RouteTables']:
                    for route in rt['Routes']:
                        if route.get('GatewayId', '').startswith('igw-'):
                            is_public = True
                            break
                    if is_public:
                        break
            
                if is_public:
                    public_subnets.append(subnet_id)
                else:
                    private_subnets.append(subnet_id)
        
            if preference == "public":
                return public_subnets if public_subnets else all_subnet_ids
            elif preference == "private":
                return private_subnets if private_subnets else all_subnet_ids
    
        except Exception as e:
            self.log_operation('WARNING', f"Could not determine subnet types: {str(e)}")
    
        # Fallback to all subnets
        return all_subnet_ids
###
    def _setup_autoscaler_iam_permissions(self, admin_session, cluster_name: str, account_id: str) -> bool:
        """Setup IAM permissions for cluster autoscaler"""
        try:
            iam_client = admin_session.client('iam')
        
            # Enhanced policy for cluster autoscaler
            autoscaler_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "autoscaling:DescribeAutoScalingGroups",
                            "autoscaling:DescribeAutoScalingInstances",
                            "autoscaling:DescribeLaunchConfigurations",
                            "autoscaling:DescribeTags",
                            "autoscaling:SetDesiredCapacity",
                            "autoscaling:TerminateInstanceInAutoScalingGroup",
                            "autoscaling:UpdateAutoScalingGroup",
                            "ec2:DescribeLaunchTemplateVersions",
                            "ec2:DescribeImages",
                            "ec2:DescribeInstances",
                            "ec2:DescribeSecurityGroups",
                            "ec2:DescribeSubnets",
                            "ec2:DescribeVpcs",
                            "eks:DescribeNodegroup",
                            "eks:ListNodegroups"
                        ],
                        "Resource": "*"
                    }
                ]
            }

            policy_name = f"EnhancedClusterAutoscaler-{cluster_name.split('-')[-1]}"

            try:
                # Create the policy
                policy_response = iam_client.create_policy(
                    PolicyName=policy_name,
                    PolicyDocument=json.dumps(autoscaler_policy),
                    Description=f"Enhanced policy for Cluster Autoscaler on {cluster_name}"
                )
                policy_arn = policy_response['Policy']['Arn']
                self.log_operation('INFO', f"Created Enhanced Cluster Autoscaler policy: {policy_arn}")

            except iam_client.exceptions.EntityAlreadyExistsException:
                # Policy already exists, get its ARN
                policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
                self.log_operation('INFO', f"Using existing Enhanced Cluster Autoscaler policy: {policy_arn}")

            # Try to attach to common node roles
            node_role_names = [
                "NodeInstanceRole",
                f"EKS-{cluster_name.split('-')[-1]}-NodeRole",
                f"eks-node-group-role-{cluster_name.split('-')[-1]}"
            ]

            attached_to_role = False
            for role_name in node_role_names:
                try:
                    iam_client.attach_role_policy(
                        RoleName=role_name,
                        PolicyArn=policy_arn
                    )
                    self.print_colored(Colors.GREEN, f"   ✅ IAM policy attached to role: {role_name}")
                    attached_to_role = True
                    break
                except Exception as e:
                    self.log_operation('DEBUG', f"Could not attach policy to role {role_name}: {str(e)}")

            if not attached_to_role:
                self.print_colored(Colors.YELLOW, f"   ⚠️ Could not attach IAM policy to any node role")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup IAM permissions: {str(e)}")
            return False

    def debug_cluster_autoscaler(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> dict:
        """Debug cluster autoscaler deployment and return detailed status"""
        try:
            import subprocess
            import shutil
        
            kubectl_available = shutil.which('kubectl') is not None
            if not kubectl_available:
                return {"error": "kubectl not available"}
        
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region
        
            debug_info = {}
        
            # Check deployment
            cmd = ['kubectl', 'get', 'deployment', 'cluster-autoscaler', '-n', 'kube-system', '-o', 'json']
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            print(f"Deployment error:\n{result.stderr}")
            if result.returncode == 0:
                debug_info['deployment_exists'] = True
            else:
                debug_info['deployment_exists'] = False
                debug_info['deployment_error'] = result.stderr
        
            # Check pods
            cmd = ['kubectl', 'get', 'pods', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', '-o', 'wide']
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            print(f"Pods output:\n{result.stdout}")
            print(f"Pods error:\n{result.stderr}")
            debug_info['pods_output'] = result.stdout
        
            # Check logs if pods exist
            cmd = ['kubectl', 'logs', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', '--tail=50']
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            print(f"Logs output:\n{result.stdout}")
            print(f"Logs error:\n{result.stderr}")
            debug_info['logs'] = result.stdout
        
            # Check events
            cmd = ['kubectl', 'get', 'events', '-n', 'kube-system', '--sort-by=.lastTimestamp']
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            print(f"Events error:\n{result.stderr}")
            debug_info['events'] = result.stdout
        
            return debug_info
        
        except Exception as e:
            return {"error": str(e)}

    def _print_usage_instructions_fixed(self, cluster_name: str, region: str):
        """
        FIXED: Print comprehensive usage instructions
        Current time: 2025-06-19 06:59:56 UTC
        User: varadharajaan
        """
        self.print_colored(Colors.BLUE, "\n" + "="*70)
        self.print_colored(Colors.BLUE, "    🎉 CLUSTER AUTOSCALER DEPLOYMENT SUCCESSFUL!")
        self.print_colored(Colors.BLUE, "="*70)
    
        self.print_colored(Colors.GREEN, f"\n📋 Cluster Information:")
        self.print_colored(Colors.GREEN, f"   • Cluster Name: {cluster_name}")
        self.print_colored(Colors.GREEN, f"   • Region: {region}")
        self.print_colored(Colors.GREEN, f"   • Deployment Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    
        self.print_colored(Colors.CYAN, f"\n🔍 Monitoring Commands:")
        self.print_colored(Colors.CYAN, f"   • Monitor autoscaler logs:")
        self.print_colored(Colors.WHITE, f"     kubectl logs -n kube-system -l app=cluster-autoscaler -f")
    
        self.print_colored(Colors.CYAN, f"   • Check autoscaler pod status:")
        self.print_colored(Colors.WHITE, f"     kubectl get pods -n kube-system -l app=cluster-autoscaler")
    
        self.print_colored(Colors.CYAN, f"   • Monitor nodes:")
        self.print_colored(Colors.WHITE, f"     watch kubectl get nodes")
    
        self.print_colored(Colors.YELLOW, f"\n🧪 Testing Commands:")
        self.print_colored(Colors.YELLOW, f"   • Scale up test (trigger node addition):")
        self.print_colored(Colors.WHITE, f"     kubectl scale deployment stress-test --replicas=8")
    
        self.print_colored(Colors.YELLOW, f"   • Scale down test (trigger node removal):")
        self.print_colored(Colors.WHITE, f"     kubectl scale deployment stress-test --replicas=1")
    
        self.print_colored(Colors.YELLOW, f"   • Monitor test pods:")
        self.print_colored(Colors.WHITE, f"     kubectl get pods -l app=stress-test")
    
        self.print_colored(Colors.GREEN, f"\n✅ Expected Behavior:")
        self.print_colored(Colors.GREEN, f"   • Scale Up: New nodes added when pods are pending (2-5 minutes)")
        self.print_colored(Colors.GREEN, f"   • Scale Down: Unused nodes removed after 10+ minutes")
        self.print_colored(Colors.GREEN, f"   • Auto-discovery: ASGs tagged for autoscaler discovery")
    
        self.print_colored(Colors.BLUE, "\n" + "="*70)
###
    def check_container_insights_enabled(self):
        """Check if Container Insights is already enabled"""
        try:
            # Check if amazon-cloudwatch namespace exists
            result = subprocess.run(
                ["kubectl", "get", "namespace", "amazon-cloudwatch"],
                capture_output=True, text=True
            )
        
            if result.returncode == 0:
                # Check if cloudwatch-agent daemonset exists
                result = subprocess.run(
                    ["kubectl", "get", "daemonset", "cloudwatch-agent", "-n", "amazon-cloudwatch"],
                    capture_output=True, text=True
                )
                return result.returncode == 0
            return False
        except Exception:
            return False

    def should_deploy_cloudwatch_agent(self):
        """Determine if we should deploy our custom CloudWatch agent"""
        if self.check_container_insights_enabled():
            self.log_operation('INFO', 'Container Insights already enabled - skipping custom CloudWatch agent deployment')
            return False
        return True


    def ensure_ec2_key_pair(self, ec2_client, key_name: str, save_dir: str = ".") -> str:
        """
        Ensure the EC2 key pair exists. If not, create it and save the private key.
        Returns the key name.
        """
        try:
            # Check if key exists
            response = ec2_client.describe_key_pairs(KeyNames=[key_name])
            self.log_operation('INFO', f"EC2 key pair '{key_name}' already exists.")
            return key_name
        except ec2_client.exceptions.ClientError as e:
            if "InvalidKeyPair.NotFound" in str(e):
                # Create the key pair
                key_pair = ec2_client.create_key_pair(KeyName=key_name)
                private_key = key_pair['KeyMaterial']
                key_path = os.path.join(save_dir, f"{key_name}.pem")
                with open(key_path, "w") as f:
                    f.write(private_key)
                os.chmod(key_path, 0o400)
                self.log_operation('INFO', f"Created EC2 key pair '{key_name}' and saved private key to {key_path}")
                return key_name
            else:
                self.log_operation('ERROR', f"Error checking/creating key pair: {str(e)}")
                raise

    def setup_cloudwatch_alarms_multi_nodegroup(self, cluster_name: str, region: str, cloudwatch_client, nodegroup_names: List[str], account_id: str) -> bool:
        """Setup CloudWatch alarms for multiple nodegroups"""
        if not nodegroup_names:
            self.log_operation('WARNING', f"No nodegroups to configure alarms for")
            return False
    
        # Create alarms for each nodegroup
        all_success = True
        for nodegroup_name in nodegroup_names:
            success = self.setup_cloudwatch_alarms(cluster_name, region, cloudwatch_client, nodegroup_name, account_id)
            if not success:
                all_success = False
    
        return all_success

    def save_cluster_details_enhanced(self, credential_info, cluster_name, region, eks_version, ami_type, nodegroup_configs, features_status):
        """Save enhanced cluster details with nodegroup information"""
        try:
            # Create output directory
            output_dir = f"aws/eks/{credential_info.account_name}"
            os.makedirs(output_dir, exist_ok=True)
        
            # Prepare enhanced cluster details
            details = {
                'timestamp': datetime.now().isoformat(),
                'created_by': self.current_user,
                'account_info': {
                    'account_name': credential_info.account_name,
                    'user_name': credential_info.username,
                    'account_id': credential_info.account_id,
                    'credential_type': credential_info.credential_type,
                    'email': credential_info.email,
                    'region': region
                },
                'cluster_info': {
                    'cluster_name': cluster_name,
                    'eks_version': eks_version,
                    'ami_type': ami_type,
                    'total_nodegroups': len(nodegroup_configs),
                    'nodegroups_created': features_status.get('nodegroups_created', [])
                },
                'nodegroup_configurations': [
                    {
                        'name': config['name'],
                        'strategy': config['strategy'],
                        'min_nodes': config['min_nodes'],
                        'desired_nodes': config['desired_nodes'],
                        'max_nodes': config['max_nodes'],
                        'instance_selections': config['instance_selections'],
                        'subnet_preference': config['subnet_preference']
                    }
                    for config in nodegroup_configs
                ],
                'features_status': features_status,
                'kubectl_commands': {
                    'update_kubeconfig': f"aws eks update-kubeconfig --region {region} --name {cluster_name}",
                    'get_nodes': "kubectl get nodes",
                    'get_pods': "kubectl get pods --all-namespaces",
                    'cluster_info': "kubectl cluster-info"
                }
            }
        
            # Save to JSON file
            filename = f"{output_dir}/eks_cluster_{cluster_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(details, f, indent=2)
        
            print(f"📁 Enhanced cluster details saved to: {filename}")
        
        except Exception as e:
            print(f"⚠️  Warning: Could not save enhanced cluster details: {e}")

    def generate_mini_instructions(self, credential_info, cluster_name, region, username):
        """Generate minimal instruction file with just the essential commands"""
        try:
            # Create output directory
            account_name = credential_info.account_name
            output_dir = f"aws/eks/{account_name}/user_login"
            os.makedirs(output_dir, exist_ok=True)

            # Format timestamp as YYYYMMDD_HHMMSS for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Filenames
            filename = f"user_mini_instructions_{account_name}_{username}_{cluster_name}_{timestamp}.txt"
            instruction_mini_file = os.path.join(output_dir, filename)
            instruction_copy_file = os.path.join(os.getcwd(), filename)

            # Shared content to write
            content_lines = [
                f"aws configure set aws_access_key_id {credential_info.access_key} --profile {username}\n\n",
                f"aws configure set aws_secret_access_key {credential_info.secret_key} --profile {username}\n\n",
                f"aws configure set region {region} --profile {username}\n\n",
                f"aws eks update-kubeconfig --region {region} --name {cluster_name} --profile {username}\n\n",
                'kubectl auth can-i "*" "*"\n\n',
                "kubectl get nodes\n\n",
                "kubectl get pods --all-namespaces\n\n",
                "kubectl cluster-info\n\n",
                "kubectl get nodes --show-labels\n\n",
                f"aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username}\n\n",
                "sudo mkdir -p /home/ec2-user/.aws\n\n",
                "sudo cp -r /home/demouser/.aws/* /home/ec2-user/.aws/\n\n",
                "sudo chown -R ec2-user:ec2-user /home/ec2-user/.aws\n\n",
                "sudo mkdir -p /home/ec2-user/.kube\n\n",
                "sudo cp -r /home/demouser/.kube/* /home/ec2-user/.kube/\n\n",
                "sudo chown -R ec2-user:ec2-user /home/ec2-user/.kube\n\n"
            ]

            # Write to both files
            for filepath in [instruction_mini_file, instruction_copy_file]:
                with open(filepath, 'w') as f:
                    f.writelines(content_lines)

            self.log_operation('INFO', f"Mini instruction file generated: {instruction_mini_file}")
            self.print_colored(Colors.GREEN,
                               f"✅ Mini instruction files generated:\n→ {instruction_mini_file}\n→ {instruction_copy_file}")
            return instruction_mini_file

        except Exception as e:
            self.log_operation('ERROR', f"Failed to generate mini instruction file: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Failed to generate mini instruction file: {str(e)}")
            return None

    def generate_user_instructions_enhanced(self, credential_info, cluster_name, region, username, nodegroup_configs):
        """Generate enhanced user instructions with nodegroup information"""
        try:
            # Create output directory
            account_name = credential_info.account_name
            output_dir = f"aws/eks/{account_name}/user_login"
            os.makedirs(output_dir, exist_ok=True)

            # Format timestamp as YYYYMMDD_HHMMSS for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Generate enhanced instruction file
            instruction_file = f"{output_dir}/user_instructions_{account_name}_{username}_{cluster_name}_{timestamp}.txt"

            with open(instruction_file, 'w') as f:
                f.write(f"# Enhanced EKS Cluster Access Instructions for {username}\n")
                f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"# Account: {account_name}\n")
                f.write(f"# Cluster: {cluster_name}\n")
                f.write(f"# Region: {region}\n")
                f.write(f"# Total Nodegroups: {len(nodegroup_configs)}\n\n")
    
                f.write("## Cluster Overview\n")
                f.write(f"Cluster Name: {cluster_name}\n")
                f.write(f"Region: {region}\n")
                f.write(f"Total Nodegroups: {len(nodegroup_configs)}\n\n")
    
                f.write("## Nodegroup Details\n")
                for i, config in enumerate(nodegroup_configs, 1):
                    f.write(f"{i}. {config['name']} ({config['strategy'].upper()})\n")
                    f.write(f"   Scaling: Min={config['min_nodes']}, Desired={config['desired_nodes']}, Max={config['max_nodes']}\n")
                    f.write(f"   Subnet Preference: {config['subnet_preference']}\n")
    
                f.write("\n## Prerequisites\n")
                f.write("1. Install AWS CLI: https://aws.amazon.com/cli/\n")
                f.write("2. Install kubectl: https://kubernetes.io/docs/tasks/tools/\n\n")
    
                f.write("## AWS Configuration\n")
                f.write(f"aws configure set aws_access_key_id {credential_info.access_key} --profile {username}\n")
                f.write(f"aws configure set aws_secret_access_key {credential_info.secret_key} --profile {username}\n")
                f.write(f"aws configure set region {region} --profile {username}\n\n")
    
                f.write("## Cluster Access\n")
                f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name} --profile {username}\n\n")
    
                f.write("## Test Commands\n")
                f.write('kubectl auth can-i "*" "*"\n')
                f.write("kubectl get nodes\n")
                f.write("kubectl get pods --all-namespaces\n")
                f.write("kubectl cluster-info\n")
                f.write("kubectl get nodes --show-labels\n")
                f.write(f"aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username}\n\n")
    
                f.write("## Nodegroup Management Commands\n\n")
            
                f.write("### Current Nodegroup Scaling\n")
                for config in nodegroup_configs:
                    f.write(f"# Scale {config['name']} (current: min={config['min_nodes']}, desired={config['desired_nodes']}, max={config['max_nodes']})\n")
                    f.write(f"# Scale up to 2 nodes:\n")
                    f.write(f"aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name {config['name']} --scaling-config minSize=1,maxSize={config['max_nodes']},desiredSize=2 --region {region} --profile {username}\n\n")
                    f.write(f"# Scale down to 1 node:\n")
                    f.write(f"aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name {config['name']} --scaling-config minSize=1,maxSize={config['max_nodes']},desiredSize=1 --region {region} --profile {username}\n\n")
                    f.write(f"# Scale to zero (for cost savings):\n")
                    f.write(f"aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name {config['name']} --scaling-config minSize=0,maxSize={config['max_nodes']},desiredSize=0 --region {region} --profile {username}\n\n")
            
                f.write("### Create New Nodegroup (Default: min=1, desired=1, max=3)\n")
                f.write("# Replace <NEW_NODEGROUP_NAME> with your desired nodegroup name\n")
                f.write("# Replace <NODE_ROLE_ARN> with your EKS node instance role ARN\n")
                f.write("# Replace <SUBNET_IDS> with comma-separated subnet IDs\n\n")
                f.write(" -----------------------------------------------------------------------------\n")
                f.write("*************** EXAMPLE COMMANDS NOT TO RUN DIRECTLY ***************\n")
                f.write(" -----------------------------------------------------------------------------\n")
                # Get subnet information from existing nodegroups for reference
                if nodegroup_configs:
                    f.write("# Example using similar configuration as existing nodegroups:\n")
            
                f.write(f"""aws eks create-nodegroup \\
        --cluster-name {cluster_name} \\
        --nodegroup-name <NEW_NODEGROUP_NAME> \\
        --scaling-config minSize=1,maxSize=3,desiredSize=1 \\
        --instance-types t3.medium \\
        --ami-type AL2023_x86_64_STANDARD \\
        --node-role <NODE_ROLE_ARN> \\
        --subnets <SUBNET_IDS> \\
        --capacity-type ON_DEMAND \\
        --region {region} \\
        --profile {username}

    """)
            
                f.write("# Quick nodegroup creation template (update the values):\n")
                f.write(f"""# Get existing node role ARN:
    aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name {nodegroup_configs[0]['name'] if nodegroup_configs else 'nodegroup-1'} --region {region} --profile {username} --query 'nodegroup.nodeRole' --output text

    # Get existing subnets:
    aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name {nodegroup_configs[0]['name'] if nodegroup_configs else 'nodegroup-1'} --region {region} --profile {username} --query 'nodegroup.subnets' --output text

    # Example with common values:
    aws eks create-nodegroup \\
        --cluster-name {cluster_name} \\
        --nodegroup-name new-nodegroup-$(date +%s) \\
        --scaling-config minSize=1,maxSize=3,desiredSize=1 \\
        --instance-types t3.medium \\
        --ami-type AL2_x86_64 \\
        --node-role arn:aws:iam::534739421744:role/EKS-{cluster_name.split('-')[-1]}-NodeRole \\
        --subnets subnet-12345678,subnet-87654321 \\
        --capacity-type ON_DEMAND \\
        --region {region} \\
        --profile {username}

    """)
            
                f.write("### Update Existing Nodegroups by Name\n")
                f.write("# Generic template - replace <NODEGROUP_NAME> with actual nodegroup name\n\n")
            
                # Scaling templates
                f.write("# Scale any nodegroup by name:\n")
                f.write(f"aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name <NODEGROUP_NAME> --scaling-config minSize=1,maxSize=5,desiredSize=2 --region {region} --profile {username}\n\n")
            
                f.write("# Update instance types (requires new nodegroup):\n")
                f.write(f"# Note: Cannot change instance types of existing nodegroup. Create new one and migrate workloads.\n\n")
            
                f.write("# Update AMI version:\n")
                f.write(f"aws eks update-nodegroup-version --cluster-name {cluster_name} --nodegroup-name <NODEGROUP_NAME> --region {region} --profile {username}\n\n")
            
                f.write("### Nodegroup Information Commands\n")
                f.write(f"# List all nodegroups:\n")
                f.write(f"aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username}\n\n")
            
                f.write(f"# Describe specific nodegroup:\n")
                f.write(f"aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name <NODEGROUP_NAME> --region {region} --profile {username}\n\n")
            
                f.write(f"# Get nodegroup scaling configuration:\n")
                f.write(f"aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name <NODEGROUP_NAME> --region {region} --profile {username} --query 'nodegroup.scalingConfig'\n\n")
            
                f.write(f"# Get nodegroup status:\n")
                f.write(f"aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name <NODEGROUP_NAME> --region {region} --profile {username} --query 'nodegroup.status' --output text\n\n")
            
                f.write("### Delete Nodegroup\n")
                f.write("# WARNING: This will terminate all nodes in the nodegroup\n")
                f.write(f"aws eks delete-nodegroup --cluster-name {cluster_name} --nodegroup-name <NODEGROUP_NAME> --region {region} --profile {username}\n\n")
            
                f.write("## Advanced Nodegroup Operations\n\n")
            
                f.write("### Batch Operations on All Nodegroups\n")
                f.write("# Scale all nodegroups to 2 nodes:\n")
                f.write(f"""for ng in $(aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username} --query 'nodegroups[]' --output text); do
        echo "Scaling $ng to 2 nodes..."
        aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name $ng --scaling-config minSize=1,maxSize=5,desiredSize=2 --region {region} --profile {username}
        sleep 10
    done

    """)
            
                f.write("# Scale all nodegroups to 0 (cost savings):\n")
                f.write(f"""for ng in $(aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username} --query 'nodegroups[]' --output text); do
        echo "Scaling $ng to 0 nodes..."
        aws eks update-nodegroup-config --cluster-name {cluster_name} --nodegroup-name $ng --scaling-config minSize=0,maxSize=5,desiredSize=0 --region {region} --profile {username}
        sleep 10
    done

    """)
            
                f.write("### Monitor Nodegroup Operations\n")
                f.write("# Watch nodegroup scaling in real-time:\n")
                f.write(f"""watch -n 30 "aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username} --output table && echo && kubectl get nodes"

    """)
            
                f.write("# Check all nodegroup configurations:\n")
                f.write(f"""aws eks list-nodegroups --cluster-name {cluster_name} --region {region} --profile {username} --query 'nodegroups[]' --output text | while read ng; do
        echo "=== $ng ==="
        aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name $ng --region {region} --profile {username} --query 'nodegroup.{{Name:nodegroupName,Status:status,Scaling:scalingConfig,Instances:instanceTypes}}'
        echo
    done

    """)

                f.write("## Troubleshooting\n")
                f.write("# If you get authentication errors:\n")
                f.write("# 1. Verify your AWS credentials are correct\n")
                f.write("# 2. Ensure your user has been granted access to the cluster\n")
                f.write("# 3. Try updating the kubeconfig again\n")
                f.write("# 4. Contact administrator if issues persist\n\n")
            
                f.write("# If nodegroup creation fails:\n")
                f.write("# 1. Check IAM role permissions\n")
                f.write("# 2. Verify subnet IDs are correct and have available capacity\n")
                f.write("# 3. Ensure instance type is available in the selected subnets\n")
                f.write("# 4. Check service quotas for EC2 instances\n\n")
            
                f.write("# If scaling operations are slow:\n")
                f.write("# 1. Scaling operations typically take 3-5 minutes\n")
                f.write("# 2. Check CloudTrail logs for detailed operation status\n")
                f.write("# 3. Monitor EC2 Auto Scaling Groups for underlying changes\n\n")
    
                f.write("## Current Time Reference\n")
                f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# User: varadharajaan\n\n")
            
                f.write("## Additional Resources\n")
                f.write("- EKS User Guide: https://docs.aws.amazon.com/eks/latest/userguide/\n")
                f.write("- kubectl Cheat Sheet: https://kubernetes.io/docs/reference/kubectl/cheatsheet/\n")
                f.write("- EKS Nodegroup Management: https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html\n")
                f.write("- AWS CLI EKS Reference: https://docs.aws.amazon.com/cli/latest/reference/eks/\n")

            self.log_operation('INFO', f"Enhanced user instructions saved to: {instruction_file}")
            self.print_colored(Colors.GREEN, f"📄 Enhanced user instructions saved to: {instruction_file}")
            
            # Also generate a copy in the current directory for immediate access
            current_dir_file = f"user_instructions_{account_name}_{username}_{cluster_name}_{timestamp}.txt"
            import shutil
            shutil.copy(instruction_file, current_dir_file)
            print(f"📄 User instructions also available at: {current_dir_file}")

        except Exception as e:
            error_msg = f"Could not create enhanced user instruction file: {e}"
            self.log_operation('WARNING', error_msg)
            self.print_colored(Colors.YELLOW, f"⚠️  Warning: {error_msg}")

    def print_enhanced_cluster_summary_multi_nodegroup(self, cluster_name: str, cluster_info: dict):
        """Print enhanced cluster creation summary with multi-nodegroup support"""
    
        nodegroup_configs = cluster_info.get('nodegroup_configs', [])
        nodegroups_created = cluster_info.get('nodegroups_created', [])
    
        self.print_colored(Colors.GREEN, f"🎉 Enhanced Cluster Summary for {cluster_name}:")
        self.print_colored(Colors.GREEN, f"   ✅ EKS Version: {cluster_info.get('eks_version', 'Unknown')}")
        self.print_colored(Colors.GREEN, f"   ✅ AMI Type: {cluster_info.get('ami_type', 'Unknown')}")
        self.print_colored(Colors.GREEN, f"   ✅ Total Nodegroups: {len(nodegroups_created)}/{len(nodegroup_configs)}")
    
        # Display nodegroup details
        for config in nodegroup_configs:
            if config['strategy'] == 'mixed':
                # For mixed strategy, check if both on-demand and spot nodegroups were created
                ondemand_name = f"{config['name']}-ondemand"
                spot_name = f"{config['name']}-spot"
                both_created = ondemand_name in nodegroups_created and spot_name in nodegroups_created
                status = "✅" if both_created else "⚠️" if (
                            ondemand_name in nodegroups_created or spot_name in nodegroups_created) else "❌"
                suffix_info = f" → {ondemand_name}, {spot_name}"
            else:
                # For non-mixed strategies, check for exact match
                status = "✅" if config['name'] in nodegroups_created else "❌"
                suffix_info = ""

            instance_summary = self.format_instance_types_summary(config['instance_selections'])
            self.print_colored(
                Colors.GREEN if status == "✅" else Colors.YELLOW if status == "⚠️" else Colors.RED,
                f"   {status} {config['name']}{suffix_info}: {config['strategy'].upper()} "
                f"({config['min_nodes']}-{config['desired_nodes']}-{config['max_nodes']}) "
                f"[{instance_summary}]"
            )
    
        self.print_colored(Colors.GREEN, f"   ✅ CloudWatch Logging: Enabled")
        self.print_colored(Colors.GREEN, f"   ✅ Essential Add-ons: {'Installed' if cluster_info.get('addons_installed') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   ✅ Container Insights: {'Enabled' if cluster_info.get('container_insights_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   ✅ Cluster Autoscaler: {'Enabled' if cluster_info.get('autoscaler_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   ✅ Scheduled Scaling: {'Enabled' if cluster_info.get('scheduled_scaling_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   ✅ CloudWatch Agent: {'Deployed' if cluster_info.get('cloudwatch_agent_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   ✅ CloudWatch Alarms: {'Configured' if cluster_info.get('cloudwatch_alarms_enabled') else 'Failed'}")
        self.print_colored(Colors.GREEN, f"   ✅ Cost Monitoring: {'Enabled' if cluster_info.get('cost_alarms_enabled') else 'Failed'}")
    
        # Health check status
        health_check = cluster_info.get('initial_health_check', {})
        health_status = health_check.get('overall_healthy', False)
        if health_status:
            health_score = health_check.get('summary', {}).get('health_score', 0)
            self.print_colored(Colors.GREEN, f"   ✅ Health Check: HEALTHY (Score: {health_score}/100)")
        else:
            issues = len(health_check.get('issues', []))
            warnings = len(health_check.get('warnings', []))
            self.print_colored(Colors.YELLOW, f"   ⚠️  Health Check: NEEDS ATTENTION ({issues} issues, {warnings} warnings)")
    
        # User access status
        auth_status = cluster_info.get('auth_configured', False)
        access_verified = cluster_info.get('access_verified', False)
        if auth_status and access_verified:
            self.print_colored(Colors.GREEN, f"   ✅ User Access: Configured & Verified")
        elif auth_status:
            self.print_colored(Colors.YELLOW, f"   ⚠️  User Access: Configured (verification pending)")
        else:
            self.print_colored(Colors.RED, f"   ❌ User Access: Failed")

    ######

    def create_eks_control_plane(self, eks_client, cluster_name: str, eks_version: str, eks_role_arn: str, subnet_ids: List[str], security_group_id: str) -> bool:
        """Create EKS control plane with CloudWatch logging enabled"""
        try:
            supported_versions = ["1.26", "1.27", "1.28", "1.29", "1.30", "1.31", "1.32"]
            if not any(eks_version.startswith(v) for v in supported_versions):
                print(f"⚠️ Warning: EKS version {eks_version} may not be fully supported")
                proceed = input(f"Proceed with version {eks_version}? (y/N): ").strip().lower()
                if proceed not in ['y', 'yes']:
                    print("❌ EKS creation canceled due to unsupported version")
                    return False

            print(f"Creating EKS cluster {cluster_name} with version {eks_version}")
            
            cluster_config = {
                'name': cluster_name,
                'version': eks_version,
                'roleArn': eks_role_arn,
                'resourcesVpcConfig': {
                    'subnetIds': subnet_ids,
                    'securityGroupIds': [security_group_id]
                },
                'logging': {
                    'clusterLogging': [
                        {
                            'types': ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
                            'enabled': True
                        }
                    ]
                }
            }
            
            # Create EKS cluster
            eks_client.create_cluster(**cluster_config)
            print(f"EKS cluster {cluster_name} creation initiated")
            
            # Wait for cluster to be active
            print(f"⏳ Waiting for cluster {cluster_name} to be active...")
            waiter = eks_client.get_waiter('cluster_active')
            waiter.wait(name=cluster_name, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})
            
            print(f"✅ Cluster {cluster_name} is now active")
            return True
            
        except Exception as e:
            print(f"❌ Error creating EKS control plane: {e}")
            return False

    @staticmethod
    def sanitize_label_value(value: str) -> str:
        # Replace any invalid character with '-'
        import re
        value = re.sub(r'[^A-Za-z0-9\-_.]', '-', value)
        # Truncate to 63 chars (K8s label max)
        return value[:63]

    def _get_multi_nodegroup_lambda_template(self):
        """
        Returns the embedded Lambda template for multi-nodegroup EKS scaling
        Uses {{cluster_name}} and {{region}} as placeholders for replacement
        """
        return '''#!/usr/bin/env python3
    """
    EKS Cluster NodeGroup Scaling Lambda Function
    Handles scheduled scaling of EKS nodegroups based on EventBridge events
    Supports both single and multiple nodegroup scaling operations
    """

    import boto3
    import json
    import logging
    import os
    from datetime import datetime, timedelta, timezone
    from typing import Dict, List, Any, Optional

    # Configure logging
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    def lambda_handler(event, context):
        """
        Lambda handler for EKS nodegroup scaling
        """
        try:
            cluster_name = '{{cluster_name}}'
            region = '{{region}}'
        
            # Create EKS client
            eks_client = boto3.client('eks', region_name=region)
        
            # Process the event
            action = event.get('action', 'unknown')
        
            # Get IST time - if not provided, calculate current IST time
            ist_time = event.get('ist_time')
            if not ist_time or ist_time == 'unknown time':
                # Calculate current IST time (UTC + 5:30)
                ist_timezone = timezone(timedelta(hours=5, minutes=30))
            
                # Get current time in IST
                current_ist = datetime.now(ist_timezone)
                ist_time = current_ist.strftime('%I:%M %p IST')
                logger.info(f"IST time not provided in event, using current IST time: {ist_time}")
        
            nodegroups_config = event.get('nodegroups', [])
        
            # Validate the input
            if not nodegroups_config:
                error_msg = "No nodegroups specified in the event"
                logger.error(error_msg)
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': error_msg})
                }
        
            # Log the operation
            logger.info(f"Starting {action} operation for cluster {cluster_name} at {ist_time} with {len(nodegroups_config)} nodegroups")
        
            # Track operation results
            results = []
            success_count = 0
        
            # Process each nodegroup
            for ng_config in nodegroups_config:
                nodegroup_name = ng_config.get('name')
                if not nodegroup_name:
                    logger.warning("Skipping nodegroup with missing name")
                    continue
                
                # Get scaling parameters with defaults
                desired_size = ng_config.get('desired_size', 1)
                min_size = ng_config.get('min_size', 0)
                max_size = ng_config.get('max_size', 3)
            
                try:
                    # Get current nodegroup configuration
                    current_ng = eks_client.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup_name
                    )
                
                    # Extract current scaling configuration
                    current_scaling = current_ng['nodegroup'].get('scalingConfig', {})
                    current_desired = current_scaling.get('desiredSize', 0)
                    current_min = current_scaling.get('minSize', 0)
                    current_max = current_scaling.get('maxSize', 0)
                
                    # Log current and target values
                    logger.info(f"Nodegroup {nodegroup_name}:")
                    logger.info(f"  Current: min={current_min}, desired={current_desired}, max={current_max}")
                    logger.info(f"  Target: min={min_size}, desired={desired_size}, max={max_size}")
                
                    # Skip update if configuration is unchanged
                    if current_min == min_size and current_desired == desired_size and current_max == max_size:
                        logger.info(f"Skipping update for {nodegroup_name} - scaling configuration unchanged")
                    
                        results.append({
                            'nodegroup': nodegroup_name,
                            'status': 'skipped',
                            'message': 'Configuration unchanged',
                            'current': {
                                'min': current_min,
                                'desired': current_desired,
                                'max': current_max
                            }
                        })
                    
                        # Count as success since there was no error
                        success_count += 1
                        continue
                
                    # Update the nodegroup scaling configuration
                    response = eks_client.update_nodegroup_config(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup_name,
                        scalingConfig={
                            'minSize': min_size,
                            'maxSize': max_size,
                            'desiredSize': desired_size
                        }
                    )
                
                    # Record successful result
                    results.append({
                        'nodegroup': nodegroup_name,
                        'status': 'success',
                        'update_id': response['update']['id'],
                        'previous': {
                            'min': current_min,
                            'desired': current_desired,
                            'max': current_max
                        },
                        'new': {
                            'min': min_size,
                            'desired': desired_size,
                            'max': max_size
                        }
                    })
                
                    success_count += 1
                    logger.info(f"Successfully initiated scaling for {nodegroup_name}")
                
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error scaling nodegroup {nodegroup_name}: {error_msg}")
                
                    # Record error result
                    results.append({
                        'nodegroup': nodegroup_name,
                        'status': 'error',
                        'error': error_msg,
                        'target': {
                            'min': min_size,
                            'desired': desired_size,
                            'max': max_size
                        }
                    })
        
            # Prepare the summary response
            summary = {
                'timestamp': datetime.now().isoformat(),
                'cluster': cluster_name,
                'region': region,
                'action': action,
                'ist_time': ist_time,
                'total_nodegroups': len(nodegroups_config),
                'successful_operations': success_count,
                'results': results
            }
        
            logger.info(f"Scaling operation summary: {success_count}/{len(nodegroups_config)} nodegroups processed successfully")
        
            # Return the response
            return {
                'statusCode': 200 if success_count > 0 else 500,
                'body': json.dumps(summary, default=str)
            }
        
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected error during scaling operation: {error_msg}")
        
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': error_msg,
                    'cluster': '{{cluster_name}}',
                    'region': '{{region}}'
                })
            }
    '''

    # python
    def short_cluster_name(self, cluster_name: str) -> str:
        # Example: eks-cluster-account01_clouduser03-us-west-1-ffkd -> eks-acc1-user03-uws1
        parts = cluster_name.split('-')
        acc = parts[2].replace('account', 'acc') if len(parts) > 2 else ''
        user = parts[3].replace('clouduser', 'user') if len(parts) > 3 else ''
        region = parts[4].replace('us', 'u').replace('west', 'w').replace('east', 'e') if len(parts) > 4 else ''
        return f"eks-{acc}-{user}-{region}"

    def short_nodegroup_name(self, nodegroup: str) -> str:
        # nodegroup-1-ondemand -> ng1o, nodegroup-1-spot -> ng1s, nodegrup-2 -> ng2
        if 'ondemand' in nodegroup:
            return f"ng{nodegroup.split('-')[1]}o"
        if 'spot' in nodegroup:
            return f"ng{nodegroup.split('-')[1]}s"
        # fallback for other patterns
        nums = ''.join(filter(str.isdigit, nodegroup))
        return f"ng{nums}"

    def generate_short_name(self, cluster_name: str, nodegroup: str) -> str:
        return f"{self.short_cluster_name(cluster_name)}-{self.short_nodegroup_name(nodegroup)}"

    def create_mixed_nodegroup(self, eks_client, cluster_name: str, nodegroup_name: str,
                           node_role_arn: str, subnet_ids: List[str], ami_type: str,
                           instance_selections: Dict, min_size: int, desired_size: int, max_size: int, ec2_key_name: str) -> bool:
        """Create mixed strategy using two separate nodegroups with proper validation"""
        try:
            # Validate required instance selections are provided
            on_demand_percentage = instance_selections.get('on_demand_percentage', 50)
            on_demand_types = instance_selections.get('on-demand', ["t3.medium"])
            spot_types = instance_selections.get('spot', ["t3.medium"])
        
            # Validation checks
            if on_demand_percentage is None:
                self.log_operation('ERROR', f"No on_demand_percentage specified for mixed nodegroup {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create mixed nodegroup: on_demand_percentage not specified")
                return False
            
            if not on_demand_types:
                self.log_operation('ERROR', f"No on-demand instance types provided for mixed nodegroup {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create mixed nodegroup: on-demand instance types not provided")
                return False
            
            if not spot_types:
                self.log_operation('ERROR', f"No spot instance types provided for mixed nodegroup {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create mixed nodegroup: spot instance types not provided")
                return False

            # Make sure both instance type lists are properly formatted as lists, not comma-separated strings
            if isinstance(on_demand_types, str):
                on_demand_types = [t.strip() for t in on_demand_types.split(',')]
        
            if isinstance(spot_types, str):
                spot_types = [t.strip() for t in spot_types.split(',')]
        
            # Validate lists aren't empty after processing
            if not on_demand_types:
                self.log_operation('ERROR', f"Empty on-demand instance types list after processing for {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create mixed nodegroup: Empty on-demand instance types")
                return False
            
            if not spot_types:
                self.log_operation('ERROR', f"Empty spot instance types list after processing for {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create mixed nodegroup: Empty spot instance types")
                return False

            self.print_colored(Colors.CYAN, f"Creating mixed strategy with {on_demand_percentage}% On-Demand, {100-on_demand_percentage}% Spot")

            # Calculate node distribution
            total_desired = desired_size
            total_min = min_size
            total_max = max_size

            # Calculate On-Demand nodes (ensure at least 1 if percentage > 0)
            if on_demand_percentage > 0:
                ondemand_desired = max(1, int(total_desired * on_demand_percentage / 100))
                ondemand_min = max(0, int(total_min * on_demand_percentage / 100))
                ondemand_max = max(1, int(total_max * on_demand_percentage / 100))
            else:
                ondemand_desired = ondemand_min = ondemand_max = 0

            # Calculate Spot nodes (remainder)
            spot_desired = total_desired - ondemand_desired
            spot_min = total_min - ondemand_min
            spot_max = total_max - ondemand_max

            # Ensure spot values are valid
            spot_desired = max(0, spot_desired)
            spot_min = max(0, spot_min)
            spot_max = max(0, spot_max)

            self.print_colored(Colors.CYAN, f"📊 Node Distribution:")
            self.print_colored(Colors.CYAN, f"   On-Demand: Min={ondemand_min}, Desired={ondemand_desired}, Max={ondemand_max}")
            self.print_colored(Colors.CYAN, f"   Spot: Min={spot_min}, Desired={spot_desired}, Max={spot_max}")

            success_count = 0
            created_nodegroups = []

            # Create On-Demand nodegroup if we have on-demand allocation
            if on_demand_types and ondemand_max > 0:
                ondemand_ng_name = f"{nodegroup_name}-ondemand"
                self.print_colored(Colors.CYAN, f"\n🏗️ Creating On-Demand nodegroup: {ondemand_ng_name}")
                self.print_colored(Colors.CYAN, f"   Instance Types: {', '.join(on_demand_types)}")
                self.print_colored(Colors.CYAN, f"   Scaling: Min={ondemand_min}, Desired={ondemand_desired}, Max={ondemand_max}")
            
                # Generate comprehensive tags for On-Demand instances
                ondemand_instance_tags = self.generate_instance_tags(cluster_name, ondemand_ng_name, 'Mixed-OnDemand')
                ondemand_instance_tags['ParentNodegroup'] = nodegroup_name
                ondemand_instance_tags['OnDemandPercentage'] = str(on_demand_percentage)
                if ondemand_instance_tags['Name'] == None or ondemand_instance_tags['Name'] == '':
                    ondemand_instance_tags['Name'] = f"{ondemand_ng_name}-instance"
        
                try:
                    eks_client.create_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=ondemand_ng_name,
                        scalingConfig={
                            'minSize': ondemand_min,
                            'maxSize': ondemand_max,
                            'desiredSize': ondemand_desired
                        },
                        instanceTypes=on_demand_types,  # Now properly a list of strings
                        amiType=ami_type,
                        nodeRole=node_role_arn,
                        subnets=subnet_ids,
                        diskSize=20,
                        capacityType='ON_DEMAND',
                        remoteAccess={
                            'ec2SshKey': ec2_key_name
                        },
                        tags=ondemand_instance_tags,
                        labels={
                            'nodegroup-name': ondemand_ng_name,
                            'instance-type': self.sanitize_label_value('-'.join(on_demand_types))[:63],
                            'capacity-type': 'on-demand',
                            'parent-nodegroup': nodegroup_name
                        }
                    )
            
                    self.print_colored(Colors.CYAN, f"⏳ Waiting for On-Demand nodegroup {ondemand_ng_name} to be active...")
                    waiter = eks_client.get_waiter('nodegroup_active')
                    waiter.wait(
                        clusterName=cluster_name,
                        nodegroupName=ondemand_ng_name,
                        WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                    )
                    self.print_colored(Colors.GREEN, f"✅ On-Demand nodegroup {ondemand_ng_name} is now active")
                    success_count += 1
                    created_nodegroups.append(ondemand_ng_name)
            
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create On-Demand nodegroup: {str(e)}")
                    self.print_colored(Colors.RED, f"❌ Failed to create On-Demand nodegroup: {str(e)}")

            # Create Spot nodegroup if we have spot allocation
            if spot_types and spot_max > 0:
                spot_ng_name = f"{nodegroup_name}-spot"
                self.print_colored(Colors.CYAN, f"\n🏗️ Creating Spot nodegroup: {spot_ng_name}")
                self.print_colored(Colors.CYAN, f"   Instance Types: {', '.join(spot_types)}")
                self.print_colored(Colors.CYAN, f"   Scaling: Min={spot_min}, Desired={spot_desired}, Max={spot_max}")
            
                # Generate comprehensive tags for Spot instances
                spot_instance_tags = self.generate_instance_tags(cluster_name, spot_ng_name, 'Mixed-Spot')
                spot_instance_tags['ParentNodegroup'] = nodegroup_name
                spot_instance_tags['OnDemandPercentage'] = str(on_demand_percentage)

                try:
                    eks_client.create_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=spot_ng_name,
                        scalingConfig={
                            'minSize': spot_min,
                            'maxSize': spot_max,
                            'desiredSize': spot_desired
                        },
                        instanceTypes=spot_types,  # Now properly a list of strings
                        amiType=ami_type,
                        nodeRole=node_role_arn,
                        subnets=subnet_ids,
                        diskSize=20,
                        capacityType='SPOT',
                        tags=spot_instance_tags,
                        labels={
                            'nodegroup-name': spot_ng_name,
                            'instance-type': self.sanitize_label_value('-'.join(spot_types))[:63],
                            'capacity-type': 'spot',
                            'parent-nodegroup': nodegroup_name
                        }
                    )
            
                    self.print_colored(Colors.CYAN, f"⏳ Waiting for Spot nodegroup {spot_ng_name} to be active...")
                    waiter = eks_client.get_waiter('nodegroup_active')
                    waiter.wait(
                        clusterName=cluster_name,
                        nodegroupName=spot_ng_name,
                        WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                    )
                    self.print_colored(Colors.GREEN, f"✅ Spot nodegroup {spot_ng_name} is now active")
                    success_count += 1
                    created_nodegroups.append(spot_ng_name)
            
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create Spot nodegroup: {str(e)}")
                    self.print_colored(Colors.RED, f"❌ Failed to create Spot nodegroup: {str(e)}")

            # Final result
            if success_count > 0:
                self.print_colored(Colors.GREEN, f"\n🎉 Mixed strategy implemented successfully!")
                self.print_colored(Colors.GREEN, f"   ✅ Created {success_count} nodegroups: {', '.join(created_nodegroups)}")
                self.print_colored(Colors.GREEN, f"   📊 Distribution: {on_demand_percentage}% On-Demand, {100-on_demand_percentage}% Spot")
                return True
            else:
                self.print_colored(Colors.RED, f"\n❌ Failed to create any nodegroups for mixed strategy")
                return False

        except Exception as e:
            self.log_operation('ERROR', f"Error creating mixed nodegroups: {e}")
            self.print_colored(Colors.RED, f"❌ Error creating mixed nodegroups: {e}")
            import traceback
            self.log_operation('ERROR', f"Stack trace: {traceback.format_exc()}")
            return False

    def create_spot_nodegroup(self, eks_client, cluster_name: str, nodegroup_name: str,
                              node_role_arn: str, subnet_ids: List[str], ami_type: str,
                              instance_types: List[str], min_size: int, desired_size: int, max_size: int,
                              ec2_key_name: str) -> bool:
        """Create Spot nodegroup with strict instance type validation"""
        try:
        
            # Make sure instance_types is a list of individual strings, not a comma-separated string
            if isinstance(instance_types, str):
                instance_types = [t.strip() for t in instance_types.split(',')]
        
            # Validate we have at least one instance type after processing
            if not instance_types:
                self.log_operation('ERROR', f"Empty instance types list after processing for spot nodegroup {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create spot nodegroup: Empty instance types list")
                return False

            self.print_colored(Colors.CYAN, f"Creating spot nodegroup {nodegroup_name}")
            self.print_colored(Colors.CYAN, f"Instance types: {' '.join(instance_types)}")
            self.print_colored(Colors.CYAN, f"AMI type: {ami_type}")
            self.print_colored(Colors.CYAN, f"Scaling: Min={min_size}, Desired={desired_size}, Max={max_size}")

            # Generate comprehensive tags for instances
            instance_tags = self.generate_instance_tags(cluster_name, nodegroup_name, 'Spot')

            # Create Spot nodegroup
            eks_client.create_nodegroup(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                scalingConfig={
                    'minSize': min_size,
                    'maxSize': max_size,
                    'desiredSize': desired_size
                },
                instanceTypes=instance_types,  # This is now a list of strings
                amiType=ami_type,
                nodeRole=node_role_arn,
                remoteAccess={
                    'ec2SshKey': ec2_key_name
                },
                subnets=subnet_ids,
                diskSize=20,  # Default disk size in GB
                capacityType='SPOT',
                tags=instance_tags,
                labels={
                    'nodegroup-name': nodegroup_name,
                    'instance-type': self.sanitize_label_value('-'.join(instance_types))[:63],
                    'capacity-type': 'spot'
                }
            )

            # Wait for nodegroup to be active
            self.print_colored(Colors.CYAN, f"⏳ Waiting for nodegroup {nodegroup_name} to be active...")
            waiter = eks_client.get_waiter('nodegroup_active')
            waiter.wait(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )

            self.print_colored(Colors.GREEN, f"✅ Nodegroup {nodegroup_name} is now active")
            return True

        except Exception as e:
            self.log_operation('ERROR', f"Error creating spot nodegroup: {e}")
            self.print_colored(Colors.RED, f"❌ Error creating spot nodegroup: {e}")
            return False

    def create_ondemand_nodegroup(self, eks_client, cluster_name: str, nodegroup_name: str,
                        node_role_arn: str, subnet_ids: List[str], ami_type: str,
                        instance_types: List[str], min_size: int, desired_size: int, max_size: int, ec2_key_name: str) -> bool:
        """Create On-Demand nodegroup with strict instance type validation"""
        try:
            # Validate that instance types are provided
            if not instance_types:
                self.log_operation('ERROR', f"No instance types provided for on-demand nodegroup {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create nodegroup: No instance types provided")
                return False
        
            # Make sure instance_types is a list of individual strings, not a comma-separated string
            if isinstance(instance_types, str):
                instance_types = [t.strip() for t in instance_types.split(',')]
        
            # Validate we have at least one instance type after processing
            if not instance_types:
                self.log_operation('ERROR', f"Empty instance types list after processing for nodegroup {nodegroup_name}")
                self.print_colored(Colors.RED, f"❌ Failed to create nodegroup: Empty instance types list")
                return False

            self.print_colored(Colors.CYAN, f"Creating on-demand nodegroup {nodegroup_name}")
            self.print_colored(Colors.CYAN, f"Instance types: {', '.join(instance_types)}")
            self.print_colored(Colors.CYAN, f"AMI type: {ami_type}")
            self.print_colored(Colors.CYAN, f"Scaling: Min={min_size}, Desired={desired_size}, Max={max_size}")

            # Generate comprehensive tags for instances
            instance_tags = self.generate_instance_tags(cluster_name, nodegroup_name, 'On-Demand')

            # Create On-Demand nodegroup
            eks_client.create_nodegroup(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                scalingConfig={
                    'minSize': min_size,
                    'maxSize': max_size,
                    'desiredSize': desired_size
                },
                instanceTypes=instance_types,  # This is now a list of strings
                amiType=ami_type,
                nodeRole=node_role_arn,
                remoteAccess={
                    'ec2SshKey': ec2_key_name
                },
                subnets=subnet_ids,
                diskSize=20,  # Default disk size in GB
                capacityType='ON_DEMAND',
                tags=instance_tags,
                labels={
                    'nodegroup-name': nodegroup_name,
                    'instance-type': self.sanitize_label_value('-'.join(instance_types))[:63],
                    'capacity-type': 'on-demand'
                }
            )

            # Wait for nodegroup to be active
            self.print_colored(Colors.CYAN, f"⏳ Waiting for nodegroup {nodegroup_name} to be active...")
            waiter = eks_client.get_waiter('nodegroup_active')
            waiter.wait(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )

            self.print_colored(Colors.GREEN, f"✅ Nodegroup {nodegroup_name} is now active")
            return True

        except Exception as e:
            self.log_operation('ERROR', f"Error creating on-demand nodegroup: {e}")
            self.print_colored(Colors.RED, f"❌ Error creating on-demand nodegroup: {e}")
            return False
    
    def ensure_iam_roles(self, iam_client, account_id: str) -> Tuple[str, str]:
            """Ensure required IAM roles exist"""
            eks_role_name = "eks-service-role"
            node_role_name = "NodeInstanceRole"
    
            eks_role_arn = f"arn:aws:iam::{account_id}:role/{eks_role_name}"
            node_role_arn = f"arn:aws:iam::{account_id}:role/{node_role_name}"
    
            self.log_operation('DEBUG', f"Checking IAM roles for account {account_id}")
    
            # Check if roles exist, create if they don't
            try:
                iam_client.get_role(RoleName=eks_role_name)
                self.log_operation('DEBUG', f"EKS service role {eks_role_name} already exists")
            except iam_client.exceptions.NoSuchEntityException:
                self.log_operation('INFO', f"Creating EKS service role {eks_role_name}")
                trust_policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "eks.amazonaws.com"},
                            "Action": "sts:AssumeRole"
                        }
                    ]
                }
        
                iam_client.create_role(
                    RoleName=eks_role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="IAM role for EKS service"
                )
        
                # Attach required policies
                policies = ["arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"]
                for policy in policies:
                    iam_client.attach_role_policy(RoleName=eks_role_name, PolicyArn=policy)
            
                # Wait for role to be available
                time.sleep(10)
    
            try:
                iam_client.get_role(RoleName=node_role_name)
                self.log_operation('DEBUG', f"Node instance role {node_role_name} already exists")
            except iam_client.exceptions.NoSuchEntityException:
                self.log_operation('INFO', f"Creating node instance role {node_role_name}")
                node_trust_policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                            "Action": "sts:AssumeRole"
                        }
                    ]
                }
        
                iam_client.create_role(
                    RoleName=node_role_name,
                    AssumeRolePolicyDocument=json.dumps(node_trust_policy),
                    Description="IAM role for EKS worker nodes"
                )
        
                # Attach required policies for worker nodes
                node_policies = [
                    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
                    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
                ]
        
                for policy in node_policies:
                    iam_client.attach_role_policy(RoleName=node_role_name, PolicyArn=policy)
            
                # Wait for role to be available
                time.sleep(10)
    
            # Create and attach the AWS CSI Policy
            self.log_operation('INFO', f"Checking and attaching AWS CSI policy for EBS driver")
            csi_policy_name = "AWSEBSCSIDriverPolicy"
            csi_policy_arn = f"arn:aws:iam::{account_id}:policy/{csi_policy_name}"
    
            # Check if policy exists, create if not
            try:
                iam_client.get_policy(PolicyArn=csi_policy_arn)
                self.log_operation('DEBUG', f"AWS CSI policy {csi_policy_name} already exists")
            except iam_client.exceptions.NoSuchEntityException:
                self.log_operation('INFO', f"Creating AWS CSI policy {csi_policy_name}")
        
                # Check if file exists, read its contents
                if os.path.exists('aws_csi_policy.json'):
                    with open('aws_csi_policy.json', 'r') as file:
                        csi_policy_document = file.read()
                    self.log_operation('DEBUG', f"Loaded CSI policy from aws_csi_policy.json")
                else:
                    # Create default CSI policy document if file doesn't exist
                    self.log_operation('WARNING', f"aws_csi_policy.json not found, using default policy")
                    csi_policy_document = json.dumps({
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": [
                                    "ec2:AttachVolume",
                                    "ec2:CreateSnapshot",
                                    "ec2:CreateTags",
                                    "ec2:CreateVolume",
                                    "ec2:DeleteSnapshot",
                                    "ec2:DeleteTags",
                                    "ec2:DeleteVolume",
                                    "ec2:DescribeInstances",
                                    "ec2:DescribeSnapshots",
                                    "ec2:DescribeTags",
                                    "ec2:DescribeVolumes",
                                    "ec2:DetachVolume",
                                    "ec2:ModifyVolume"
                                ],
                                "Resource": "*"
                            },
                            {
                                "Effect": "Allow",
                                "Action": [
                                    "kms:CreateGrant",
                                    "kms:ListGrants",
                                    "kms:RevokeGrant"
                                ],
                                "Resource": "*",
                                "Condition": {
                                    "Bool": {
                                        "kms:GrantIsForAWSResource": "true"
                                    }
                                }
                            },
                            {
                                "Effect": "Allow",
                                "Action": [
                                    "kms:Decrypt",
                                    "kms:DescribeKey",
                                    "kms:Encrypt",
                                    "kms:GenerateDataKey*",
                                    "kms:ReEncrypt*"
                                ],
                                "Resource": "*"
                            }
                        ]
                    })
        
                # Create policy
                policy = iam_client.create_policy(
                    PolicyName=csi_policy_name,
                    PolicyDocument=csi_policy_document,
                    Description="Policy for AWS EBS CSI Driver"
                )
                csi_policy_arn = policy['Policy']['Arn']
                self.log_operation('INFO', f"Created AWS CSI policy: {csi_policy_arn}")
        
                # Wait for policy to be available
                time.sleep(5)
    
            # Attach CSI policy to the node role
            try:
                iam_client.attach_role_policy(
                    RoleName=node_role_name,
                    PolicyArn=csi_policy_arn
                )
                self.log_operation('INFO', f"Attached AWS CSI policy to {node_role_name}")
                print(f"✅ AWS CSI policy attached to {node_role_name}")
            except Exception as e:
                self.log_operation('ERROR', f"Failed to attach CSI policy: {str(e)}")
                print(f"❌ Failed to attach CSI policy: {str(e)}")
    
            return eks_role_arn, node_role_arn

    def get_or_create_vpc_resources(self, ec2_client, region: str) -> Tuple[List[str], str]:
            """Get or create VPC resources (subnets, security group) filtering out unsupported AZs"""
            try:
                self.log_operation('DEBUG', f"Getting VPC resources for region: {region}")
            
                # Load unsupported AZs from mapping file
                unsupported_azs = self._get_unsupported_azs(region)
                if unsupported_azs:
                    self.log_operation('DEBUG', f"Unsupported AZs in {region}: {unsupported_azs}")
            
                # Get default VPC
                vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
            
                if not vpcs['Vpcs']:
                    self.log_operation('ERROR', f"No default VPC found in {region}")
                    raise Exception(f"No default VPC found in {region}")
            
                vpc_id = vpcs['Vpcs'][0]['VpcId']
                self.log_operation('DEBUG', f"Using VPC {vpc_id} in region {region}")
            
                # Get subnets
                subnets = ec2_client.describe_subnets(
                    Filters=[
                        {'Name': 'vpc-id', 'Values': [vpc_id]},
                        {'Name': 'state', 'Values': ['available']}
                    ]
                )
            
                # Filter out subnets in unsupported AZs
                supported_subnets = []
                for subnet in subnets['Subnets']:
                    az = subnet['AvailabilityZone']
                    if az not in unsupported_azs:
                        supported_subnets.append(subnet)
                    else:
                        self.log_operation('DEBUG', f"Skipping subnet {subnet['SubnetId']} in unsupported AZ: {az}")
            
                # Take first 2 supported subnets
                subnet_ids = [subnet['SubnetId'] for subnet in supported_subnets[:2]]
            
                if len(subnet_ids) < 2:
                    # Check minimum requirements from config
                    min_subnets = self._get_min_subnets_required()
                    self.log_operation('WARNING', f"Only found {len(subnet_ids)} supported subnets in {region}, minimum required: {min_subnets}")
                
                    if len(supported_subnets) > 0:
                        # If we have at least one supported subnet, use what we have
                        subnet_ids = [subnet['SubnetId'] for subnet in supported_subnets]
                        self.log_operation('INFO', f"Using {len(subnet_ids)} available supported subnets")
                    
                        if len(subnet_ids) < min_subnets:
                            self.log_operation('ERROR', f"Insufficient supported subnets: found {len(subnet_ids)}, need {min_subnets}")
                            raise Exception(f"Insufficient supported subnets in {region}: found {len(subnet_ids)}, need at least {min_subnets}")
                    else:
                        self.log_operation('ERROR', f"No supported subnets found in {region}")
                        raise Exception(f"No supported subnets found in {region}")

                self.log_operation('DEBUG', f"Found {len(subnet_ids)} supported subnets: {subnet_ids}")
            
                # Get or create security group
                try:
                    security_groups = ec2_client.describe_security_groups(
                        Filters=[
                            {'Name': 'group-name', 'Values': ['eks-cluster-sg']},  # Wildcard to match any suffix
                            {'Name': 'vpc-id', 'Values': [vpc_id]}
                        ]
                    )

                    if security_groups['SecurityGroups']:
                        # Use the first security group found
                        sg_id = security_groups['SecurityGroups'][0]['GroupId']
                        self.log_operation('DEBUG', f"Using security group: {sg_id}")

                        # Get VPC CIDR block
                        vpc_response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
                        vpc_cidr = vpc_response['Vpcs'][0]['CidrBlock']
                        self.log_operation('DEBUG', f"VPC {vpc_id} has CIDR block: {vpc_cidr}")

                        # Check if the security group has the required rule
                        sg_rules = ec2_client.describe_security_group_rules(
                            Filters=[{'Name': 'group-id', 'Values': [sg_id]}]
                        )

                        # Check if the VPC CIDR rule exists
                        has_vpc_rule = any(
                            rule.get('IsEgress') == False and
                            rule.get('CidrIpv4') == vpc_cidr and
                            rule.get('IpProtocol') == '-1'
                            for rule in sg_rules['SecurityGroupRules']
                        )

                        if not has_vpc_rule:
                            self.log_operation('INFO',
                                               f"Adding VPC access rule for CIDR {vpc_cidr} to security group {sg_id}")
                            ec2_client.authorize_security_group_ingress(
                                GroupId=sg_id,
                                IpPermissions=[
                                    {
                                        'IpProtocol': '-1',  # All protocols
                                        'FromPort': -1,  # All ports
                                        'ToPort': -1,  # All ports
                                        'IpRanges': [
                                            {
                                                'CidrIp': vpc_cidr,
                                                'Description': 'Allow traffic within VPC for private cluster access'
                                            }
                                        ]
                                    }
                                ]
                            )
                    else:
                        # No existing security groups, create a new one
                        sg_response = ec2_client.create_security_group(
                            GroupName='eks-cluster-sg',
                            Description='Security group for EKS cluster',
                            VpcId=vpc_id
                        )
                        sg_id = sg_response['GroupId']
                        self.log_operation('INFO', f"Created new security group {sg_id}")

                        # Add creation time tag
                        ec2_client.create_tags(
                            Resources=[sg_id],
                            Tags=[
                                {
                                    'Key': 'CreationTime',
                                    'Value': datetime.now().isoformat()
                                },
                                {
                                    'Key': 'Name',
                                    'Value': 'eks-cluster-sg'
                                }
                            ]
                        )

                        # Get VPC CIDR block
                        vpc_response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
                        vpc_cidr = vpc_response['Vpcs'][0]['CidrBlock']
                        self.log_operation('INFO', f"VPC {vpc_id} has CIDR block: {vpc_cidr}")

                        # Add the VPC access rule
                        self.log_operation('INFO', f"Adding VPC access rule to new security group {sg_id}")
                        ec2_client.authorize_security_group_ingress(
                            GroupId=sg_id,
                            IpPermissions=[
                                {
                                    'IpProtocol': '-1',  # All protocols
                                    'FromPort': -1,  # All ports
                                    'ToPort': -1,  # All ports
                                    'IpRanges': [
                                        {
                                            'CidrIp': vpc_cidr,
                                            'Description': 'Allow traffic within VPC for private cluster access'
                                        }
                                    ]
                                }
                            ]
                        )

                except Exception as e:
                    self.log_operation('WARNING', f"Using default security group due to: {str(e)}")
                    default_sg = ec2_client.describe_security_groups(
                        Filters=[
                            {'Name': 'group-name', 'Values': ['default']},
                            {'Name': 'vpc-id', 'Values': [vpc_id]}
                        ]
                    )
                    sg_id = default_sg['SecurityGroups'][0]['GroupId']
                return subnet_ids, sg_id
            
            except Exception as e:
                self.log_operation('ERROR', f"Failed to get VPC resources in {region}: {str(e)}")
                raise

    def enable_cluster_access_modes(self, cluster_name: str, region: str, account_id: str, user_data: Dict,
                                    admin_access_key: str, admin_secret_key: str) -> bool:
        """Enable both ConfigMap and API access modes for the cluster"""
        try:
            self.log_operation('INFO', f"Enabling both ConfigMap and API access for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔐 Configuring dual access (ConfigMap + API) for cluster {cluster_name}")

            # Create admin session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            eks_client = admin_session.client('eks')
            sts_client = admin_session.client('sts')

            # Get caller identity to determine user type
            caller_identity = sts_client.get_caller_identity()
            creator_arn = caller_identity['Arn']
            creator_type = 'root' if ':root' in creator_arn else 'user'

            # Determine user ARN for access configuration
            username = user_data.get('username', 'unknown')
            if creator_type == 'root':
                user_arn = f"arn:aws:iam::{account_id}:root"
            else:
                user_arn = f"arn:aws:iam::{account_id}:user/{username}"

            self.log_operation('INFO', f"Configuring access for {creator_type}: {user_arn}")

            # Step 1: Configure ConfigMap access (existing functionality)
            configmap_success = self.configure_aws_auth_configmap(
                cluster_name, region, account_id, user_data, admin_access_key, admin_secret_key
            )

            # Step 2: Enable API access
            api_success = self._enable_api_access(eks_client, cluster_name, user_arn, username)

            # Return success if at least one method worked
            if configmap_success and api_success:
                self.print_colored(Colors.GREEN, f"✅ Both ConfigMap and API access enabled successfully")
                return True
            elif configmap_success:
                self.print_colored(Colors.YELLOW, f"⚠️ ConfigMap access enabled, API access failed")
                return True
            elif api_success:
                self.print_colored(Colors.YELLOW, f"⚠️ API access enabled, ConfigMap access failed")
                return True
            else:
                self.print_colored(Colors.RED, f"❌ Both access methods failed")
                return False

        except Exception as e:
            self.log_operation('ERROR', f"Error enabling cluster access modes: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Error enabling cluster access modes: {str(e)}")
            return False

    def _enable_api_access(self, eks_client, cluster_name: str, user_arn: str, username: str) -> bool:
        """Enable API access for the user"""
        try:
            self.log_operation('INFO', f"Enabling API access for user {username}")
            self.print_colored(Colors.CYAN, f"🔑 Enabling API access for user {username}")

            # Create access entry for the user
            try:
                eks_client.create_access_entry(
                    clusterName=cluster_name,
                    principalArn=user_arn,
                    type='STANDARD'
                )
                self.log_operation('INFO', f"Created access entry for {user_arn}")

            except eks_client.exceptions.ResourceInUseException:
                self.log_operation('INFO', f"Access entry already exists for {user_arn}")
                self.print_colored(Colors.YELLOW, f"⚠️ Access entry already exists for {username}")

            # Associate admin policy with the access entry
            try:
                eks_client.associate_access_policy(
                    clusterName=cluster_name,
                    principalArn=user_arn,
                    policyArn='arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy',
                    accessScope={
                        'type': 'cluster'
                    }
                )
                self.log_operation('INFO', f"Associated admin policy with access entry for {user_arn}")
                self.print_colored(Colors.GREEN, f"✅ API access enabled for user {username}")
                return True

            except eks_client.exceptions.ResourceInUseException:
                self.log_operation('INFO', f"Access policy already associated for {user_arn}")
                self.print_colored(Colors.YELLOW, f"⚠️ Access policy already associated for {username}")
                return True

        except Exception as e:
            self.log_operation('WARNING', f"Failed to enable API access for {username}: {str(e)}")
            self.print_colored(Colors.YELLOW, f"⚠️ API access setup failed for {username}: {str(e)}")
            return False

    def configure_aws_auth_configmap(self, cluster_name: str, region: str, account_id: str, user_data: Dict, admin_access_key: str, admin_secret_key: str) -> bool:
        """Configure aws-auth ConfigMap to add appropriate user access based on creator type (root or IAM user)"""
        try:
            self.log_operation('INFO', f"Configuring aws-auth ConfigMap for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔐 Configuring aws-auth ConfigMap for cluster {cluster_name}")

            # Create admin session for configuring the cluster
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            eks_client = admin_session.client('eks')
            sts_client = admin_session.client('sts')

            # Determine if the creator is root user or IAM user
            try:
                caller_identity = sts_client.get_caller_identity()
                caller_arn = caller_identity.get('Arn', '')
                caller_user_id = caller_identity.get('UserId', '')

                # Check if this is a root user
                is_root_user = (
                        caller_arn == f"arn:aws:iam::{account_id}:root" or
                        caller_user_id == account_id or
                        'root' in caller_arn.lower()
                )

                self.log_operation('INFO', f"Caller identity: {caller_arn}")
                self.log_operation('INFO', f"Is root user: {is_root_user}")

            except Exception as e:
                self.log_operation('WARNING', f"Could not determine caller identity: {str(e)}")
                # Default to treating as IAM user if we can't determine
                is_root_user = False

            # Get cluster details
            cluster_info = eks_client.describe_cluster(name=cluster_name)
            cluster_endpoint = cluster_info['cluster']['endpoint']
            cluster_ca = cluster_info['cluster']['certificateAuthority']['data']

            # Create temporary directory if it doesn't exist
            temp_dir = "/tmp"
            if not os.path.exists(temp_dir):
                temp_dir = os.getcwd()  # Use current directory as fallback

            # Prepare user entries based on creator type
            users_to_add = []
            principals_to_add = []

            if is_root_user:
                # If created by root user, only add root user access
                root_arn = f"arn:aws:iam::{account_id}:root"
                users_to_add.append({
                    'userarn': root_arn,
                    'username': 'root-user',
                    'groups': ['system:masters']
                })
                principals_to_add.append(root_arn)

                self.log_operation('INFO', f"Configuring access for root user: {root_arn}")
                self.print_colored(Colors.CYAN, f"   👑 Creator is root user - configuring root access only")

            else:
                # If created by IAM user, add both IAM user and root user access
                username = user_data.get('username', 'unknown')
                user_arn = f"arn:aws:iam::{account_id}:user/{username}"
                root_arn = f"arn:aws:iam::{account_id}:root"

                users_to_add.extend([
                    {
                        'userarn': user_arn,
                        'username': username,
                        'groups': ['system:masters']
                    },
                    {
                        'userarn': root_arn,
                        'username': 'root-user',
                        'groups': ['system:masters']
                    }
                ])
                principals_to_add.extend([user_arn, root_arn])

                self.log_operation('INFO', f"Configuring access for IAM user: {username} ({user_arn})")
                self.log_operation('INFO', f"Configuring access for root user: {root_arn}")
                self.print_colored(Colors.CYAN,
                                   f"   👤 Creator is IAM user: {username} - configuring IAM user + root access")

            # Check cluster authentication mode
            access_config = cluster_info['cluster'].get('accessConfig', {})
            auth_mode = access_config.get('authenticationMode', 'CONFIG_MAP')

            self.print_colored(Colors.CYAN, f"   📋 Cluster authentication mode: {auth_mode}")

            # If cluster uses CONFIG_MAP mode, create/update aws-auth ConfigMap
            if auth_mode in ['CONFIG_MAP', 'API_AND_CONFIG_MAP']:
                self.print_colored(Colors.CYAN, "   📋 Creating/updating aws-auth ConfigMap...")

                # Create aws-auth ConfigMap YAML with appropriate users
                aws_auth_config = {
                    'apiVersion': 'v1',
                    'kind': 'ConfigMap',
                    'metadata': {
                        'name': 'aws-auth',
                        'namespace': 'kube-system'
                    },
                    'data': {
                        'mapRoles': yaml.dump([
                            {
                                'rolearn': f"arn:aws:iam::{account_id}:role/NodeInstanceRole",
                                'username': 'system:node:{{EC2PrivateDNSName}}',
                                'groups': ['system:bootstrappers', 'system:nodes']
                            }
                        ], default_flow_style=False),
                        'mapUsers': yaml.dump(users_to_add, default_flow_style=False)
                    }
                }

                # Save ConfigMap YAML with error handling
                configmap_file = os.path.join(temp_dir, f"aws-auth-{cluster_name}-{self.execution_timestamp}.yaml")
                try:
                    with open(configmap_file, 'w') as f:
                        yaml.dump(aws_auth_config, f)
                    self.log_operation('INFO', f"Created ConfigMap file: {configmap_file}")
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create ConfigMap file: {str(e)}")
                    return False

                # Check if kubectl is available
                import subprocess
                import shutil

                kubectl_available = shutil.which('kubectl') is not None

                if not kubectl_available:
                    self.log_operation('WARNING',
                                       f"kubectl not found. ConfigMap file created but not applied: {configmap_file}")
                    self.print_colored(Colors.YELLOW, f"⚠️  kubectl not found. Manual setup required.")

                    # Create manual instruction file
                    instruction_file = os.path.join(temp_dir,
                                                    f"manual-auth-setup-{cluster_name}-{self.execution_timestamp}.txt")
                    try:
                        with open(instruction_file, 'w') as f:
                            f.write(f"# Manual aws-auth ConfigMap Setup for {cluster_name}\n")
                            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                            f.write(f"# Cluster: {cluster_name}\n")
                            f.write(f"# Region: {region}\n")
                            f.write(f"# Creator type: {'Root User' if is_root_user else 'IAM User'}\n\n")

                            f.write("## Prerequisites\n")
                            f.write("# Install kubectl\n")
                            f.write(
                                "curl -LO \"https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl\"\n")
                            f.write("chmod +x kubectl\n")
                            f.write("sudo mv kubectl /usr/local/bin/\n\n")

                            f.write("## Apply ConfigMap with Admin Credentials\n")
                            f.write(f"# Set AWS admin credentials\n")
                            f.write(f"export AWS_ACCESS_KEY_ID={admin_access_key}\n")
                            f.write(f"export AWS_SECRET_ACCESS_KEY={admin_secret_key}\n")
                            f.write(f"export AWS_DEFAULT_REGION={region}\n\n")
                            f.write(f"# export profil= {username}\n")

                            f.write(f"# Update kubeconfig with admin credentials\n")
                            f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name}\n\n")

                            f.write(f"# Apply the ConfigMap\n")
                            f.write(f"kubectl apply -f {configmap_file}\n\n")

                            f.write(f"# Verify ConfigMap\n")
                            f.write(f"kubectl get configmap aws-auth -n kube-system -o yaml\n\n")

                            if is_root_user:
                                f.write(f"## Test Root Access\n")
                                f.write(f"# Use root credentials to test access\n")
                                f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name}\n")
                                f.write(f"kubectl get nodes\n")
                                f.write(f"kubectl get pods\n")
                            else:
                                f.write(f"## Test IAM User Access\n")
                                f.write(f"# Set user credentials\n")
                                f.write(
                                    f"export AWS_ACCESS_KEY_ID={user_data.get('access_key_id', 'USER_ACCESS_KEY')}\n")
                                f.write(
                                    f"export AWS_SECRET_ACCESS_KEY={user_data.get('secret_access_key', 'USER_SECRET_KEY')}\n")
                                f.write(f"# Update kubeconfig with user profile\n")
                                f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name}\n")
                                f.write(f"# Test access\n")
                                f.write(f"kubectl get nodes\n")
                                f.write(f"kubectl get pods\n")

                                f.write(f"\n## Test Root Access\n")
                                f.write(f"# Set root credentials (replace with actual root credentials)\n")
                                f.write(f"export AWS_ACCESS_KEY_ID=ROOT_ACCESS_KEY\n")
                                f.write(f"export AWS_SECRET_ACCESS_KEY=ROOT_SECRET_KEY\n")
                                f.write(f"# Update kubeconfig with root credentials\n")
                                f.write(f"aws eks update-kubeconfig --region {region} --name {cluster_name}\n")
                                f.write(f"# Test root access\n")
                                f.write(f"kubectl get nodes\n")
                                f.write(f"kubectl get pods\n")

                        self.log_operation('INFO', f"Manual setup instructions saved to: {instruction_file}")
                        self.print_colored(Colors.CYAN, f"📋 Manual setup instructions: {instruction_file}")

                    except Exception as e:
                        self.log_operation('WARNING', f"Failed to create instruction file: {str(e)}")

                    # Return True since we created the ConfigMap file
                    return True

                # Apply ConfigMap using kubectl with admin credentials
                self.log_operation('INFO', f"Applying ConfigMap using admin credentials")
                self.print_colored(Colors.YELLOW, f"🚀 Applying ConfigMap with admin credentials...")

                # Set environment variables for admin access
                myenv = os.environ.copy()
                myenv['AWS_ACCESS_KEY_ID'] = admin_access_key
                myenv['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
                myenv['AWS_DEFAULT_REGION'] = region

                try:
                    # Update kubeconfig with admin credentials first
                    update_cmd = [
                        'aws', 'eks', 'update-kubeconfig',
                        '--region', region,
                        '--name', cluster_name
                    ]

                    self.log_operation('INFO', f"Updating kubeconfig with admin credentials")
                    update_result = subprocess.run(update_cmd, env=myenv, capture_output=True, text=True, timeout=120)

                    if update_result.returncode == 0:
                        self.log_operation('INFO', f"Successfully updated kubeconfig with admin credentials")
                    else:
                        self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                        return False

                    # Apply the ConfigMap
                    apply_cmd = ['kubectl', 'apply', '-f', configmap_file]
                    self.log_operation('INFO', f"Applying ConfigMap: {' '.join(apply_cmd)}")

                    apply_result = subprocess.run(apply_cmd, env=myenv, capture_output=True, text=True, timeout=300)

                    if apply_result.returncode == 0:
                        self.log_operation('INFO', f"Successfully applied aws-auth ConfigMap for {cluster_name}")
                        self.print_colored(Colors.GREEN, f"✅ ConfigMap applied successfully")

                        # Verify the ConfigMap was applied
                        verify_cmd = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system', '-o', 'yaml']
                        verify_result = subprocess.run(verify_cmd, env=myenv, capture_output=True, text=True, timeout=120)

                        if verify_result.returncode == 0:
                            self.log_operation('INFO', f"ConfigMap verification successful")
                            self.log_operation('DEBUG', f"ConfigMap content: {verify_result.stdout}")
                        else:
                            self.log_operation('WARNING', f"ConfigMap verification failed: {verify_result.stderr}")

                        success = True
                    else:
                        self.log_operation('ERROR', f"Failed to apply aws-auth ConfigMap: {apply_result.stderr}")
                        self.print_colored(Colors.RED, f"❌ Failed to apply ConfigMap: {apply_result.stderr}")
                        success = False

                except subprocess.TimeoutExpired:
                    self.log_operation('ERROR', f"kubectl/aws command timed out for {cluster_name}")
                    self.print_colored(Colors.RED, f"❌ Command timed out")
                    success = False
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to execute kubectl/aws commands: {str(e)}")
                    self.print_colored(Colors.RED, f"❌ Command execution failed: {str(e)}")
                    success = False

                # Clean up temporary files
                try:
                    if os.path.exists(configmap_file):
                        os.remove(configmap_file)
                        self.log_operation('INFO', f"Cleaned up temporary ConfigMap file")
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to clean up ConfigMap file: {str(e)}")
            else:
                success = True  # If only API mode, access entries are sufficient

            if success:
                if is_root_user:
                    self.print_colored(Colors.GREEN, f"✅ Root user configured for cluster access")
                else:
                    username = user_data.get('username', 'unknown')
                    self.print_colored(Colors.GREEN, f"✅ User [{username}] and root user configured for cluster access")

                # Test access after a brief delay (only for IAM user, not root)
                if not is_root_user:
                    try:
                        import time
                        time.sleep(10)  # Wait for ConfigMap to propagate

                        username = user_data.get('username', 'unknown')
                        self.log_operation('INFO', f"Testing user access for {username}")
                        self.print_colored(Colors.YELLOW, f"🧪 Testing user access...")

                        # Set user environment
                        user_env = os.environ.copy()
                        user_env['AWS_ACCESS_KEY_ID'] = user_data.get('access_key', '')
                        user_env['AWS_SECRET_ACCESS_KEY'] = user_data.get('secret_key', '')
                        user_env['AWS_DEFAULT_REGION'] = region
                        user_env['AWS_PROFILE'] = user_data.get('username', username)


                        # Update kubeconfig with user credentials
                        user_update_cmd = [
                            'aws', 'eks', 'update-kubeconfig',
                            '--region', region,
                            '--name', cluster_name
                        ]

                        user_update_result = subprocess.run(user_update_cmd, env=user_env, capture_output=True,
                                                            text=True, timeout=120)

                        if user_update_result.returncode == 0:
                            # Test kubectl access
                            test_cmd = ['kubectl', 'get', 'nodes']
                            test_result = subprocess.run(test_cmd, env=user_env, capture_output=True, text=True,
                                                         timeout=60)

                            if test_result.returncode == 0:
                                self.log_operation('INFO', f"User access test successful for {username}")
                                self.print_colored(Colors.GREEN, f"✅ User access verified - can access cluster")
                            else:
                                self.log_operation('WARNING', f"User access test failed: {test_result.stderr}")
                                self.print_colored(Colors.YELLOW,
                                                   f"⚠️  User access test failed - may need manual verification")
                        else:
                            self.log_operation('WARNING',
                                               f"Failed to update kubeconfig for user test: {user_update_result.stderr}")

                    except Exception as e:
                        self.log_operation('WARNING', f"User access test failed: {str(e)}")

            return success

        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to configure aws-auth ConfigMap for {cluster_name}: {error_msg}")
            self.print_colored(Colors.RED, f"❌ ConfigMap configuration failed: {error_msg}")
            return False

    def health_check_cluster(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str) -> Dict:
            """Comprehensive cluster health check with detailed reporting"""
            try:
                self.log_operation('INFO', f"Performing comprehensive health check for cluster {cluster_name}")
            
                admin_session = boto3.Session(
                    aws_access_key_id=admin_access_key,
                    aws_secret_access_key=admin_secret_key,
                    region_name=region
                )
            
                eks_client = admin_session.client('eks')
                from datetime import datetime
                current_timestamp = int(datetime.utcnow().timestamp())
                health_status = {
                    'cluster_name': cluster_name,
                    'region': region,
                    'check_timestamp': current_timestamp,
                    'checked_by': 'varadharajaan',
                    'overall_healthy': True,
                    'issues': [],
                    'warnings': [],
                    'success_items': []
                }
            
                # 1. Check cluster status and details
                try:
                    cluster_response = eks_client.describe_cluster(name=cluster_name)
                    cluster = cluster_response['cluster']
                    cluster_status = cluster['status']
                    cluster_version = cluster.get('version', 'Unknown')
                
                    health_status['cluster_status'] = cluster_status
                    health_status['cluster_version'] = cluster_version
                    health_status['cluster_endpoint'] = cluster.get('endpoint', 'Unknown')
                
                    if cluster_status != 'ACTIVE':
                        health_status['overall_healthy'] = False
                        health_status['issues'].append(f"Cluster status is {cluster_status}, expected ACTIVE")
                        self.print_colored(Colors.RED, f"   ❌ Cluster status: {cluster_status}")
                    else:
                        health_status['success_items'].append(f"Cluster is ACTIVE (version {cluster_version})")
                        self.print_colored(Colors.GREEN, f"   ✅ Cluster status: {cluster_status} (v{cluster_version})")
                
                    # Check cluster logging
                    logging_config = cluster.get('logging', {}).get('clusterLogging', [])
                    if logging_config and any(log.get('enabled', False) for log in logging_config):
                        health_status['success_items'].append("CloudWatch logging is enabled")
                        self.print_colored(Colors.GREEN, f"   ✅ CloudWatch logging: Enabled")
                    else:
                        health_status['warnings'].append("CloudWatch logging may not be fully configured")
                        self.print_colored(Colors.YELLOW, f"   ⚠️  CloudWatch logging: Limited or disabled")
                    
                except Exception as e:
                    health_status['cluster_status'] = 'ERROR'
                    health_status['overall_healthy'] = False
                    health_status['issues'].append(f"Failed to get cluster status: {str(e)}")
                    self.print_colored(Colors.RED, f"   ❌ Cluster check failed: {str(e)}")
            
                # 2. Check node groups with detailed analysis
                try:
                    nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                    nodegroup_health = {}
                    total_nodegroups = len(nodegroups_response['nodegroups'])
                    active_nodegroups = 0
                
                    for ng_name in nodegroups_response['nodegroups']:
                        ng_response = eks_client.describe_nodegroup(
                            clusterName=cluster_name,
                            nodegroupName=ng_name
                        )
                        nodegroup = ng_response['nodegroup']
                        ng_status = nodegroup['status']
                        scaling_config = nodegroup.get('scalingConfig', {})
                        instance_types = nodegroup.get('instanceTypes', [])
                        ami_type = nodegroup.get('amiType', 'Unknown')
                        capacity_type = nodegroup.get('capacityType', 'Unknown')
                    
                        nodegroup_health[ng_name] = {
                            'status': ng_status,
                            'instance_types': instance_types,
                            'ami_type': ami_type,
                            'capacity_type': capacity_type,
                            'min_size': scaling_config.get('minSize', 0),
                            'max_size': scaling_config.get('maxSize', 0),
                            'desired_size': scaling_config.get('desiredSize', 0)
                        }
                    
                        if ng_status != 'ACTIVE':
                            health_status['overall_healthy'] = False
                            health_status['issues'].append(f"NodeGroup {ng_name} status is {ng_status}")
                            self.print_colored(Colors.RED, f"   ❌ NodeGroup {ng_name}: {ng_status}")
                        else:
                            active_nodegroups += 1
                            health_status['success_items'].append(f"NodeGroup {ng_name} is ACTIVE ({capacity_type}, {', '.join(instance_types)})")
                            self.print_colored(Colors.GREEN, f"   ✅ NodeGroup {ng_name}: {ng_status} ({capacity_type}, {ami_type})")
                            self.print_colored(Colors.CYAN, f"      Scaling: {scaling_config.get('desiredSize', 0)}/{scaling_config.get('maxSize', 0)} nodes")
                
                    health_status['nodegroup_health'] = nodegroup_health
                    health_status['total_nodegroups'] = total_nodegroups
                    health_status['active_nodegroups'] = active_nodegroups
                
                except Exception as e:
                    health_status['nodegroup_health'] = {}
                    health_status['overall_healthy'] = False
                    health_status['issues'].append(f"Failed to check nodegroups: {str(e)}")
                    self.print_colored(Colors.RED, f"   ❌ NodeGroup check failed: {str(e)}")
            
                # 3. Check add-ons with version information
                try:
                    addons_response = eks_client.list_addons(clusterName=cluster_name)
                    addon_health = {}
                    total_addons = len(addons_response['addons'])
                    active_addons = 0
                
                    essential_addons = ['vpc-cni', 'coredns', 'kube-proxy']
                
                    for addon_name in addons_response['addons']:
                        addon_response = eks_client.describe_addon(
                            clusterName=cluster_name,
                            addonName=addon_name
                        )
                        addon = addon_response['addon']
                        addon_status = addon['status']
                        addon_version = addon.get('addonVersion', 'Unknown')
                    
                        addon_health[addon_name] = {
                            'status': addon_status,
                            'version': addon_version,
                            'essential': addon_name in essential_addons
                        }
                    
                        if addon_status not in ['ACTIVE', 'RUNNING']:
                            if addon_name in essential_addons:
                                health_status['overall_healthy'] = False
                                health_status['issues'].append(f"Essential add-on {addon_name} status is {addon_status}")
                                self.print_colored(Colors.RED, f"   ❌ Add-on {addon_name}: {addon_status} (ESSENTIAL)")
                            else:
                                health_status['warnings'].append(f"Non-essential add-on {addon_name} status is {addon_status}")
                                self.print_colored(Colors.YELLOW, f"   ⚠️  Add-on {addon_name}: {addon_status}")
                        else:
                            active_addons += 1
                            health_status['success_items'].append(f"Add-on {addon_name} is {addon_status} (v{addon_version})")
                            addon_type = "ESSENTIAL" if addon_name in essential_addons else "optional"
                            self.print_colored(Colors.GREEN, f"   ✅ Add-on {addon_name}: {addon_status} (v{addon_version}, {addon_type})")
                
                    health_status['addon_health'] = addon_health
                    health_status['total_addons'] = total_addons
                    health_status['active_addons'] = active_addons
                
                    # Check if all essential add-ons are present
                    installed_essential = [name for name in addons_response['addons'] if name in essential_addons]
                    missing_essential = [name for name in essential_addons if name not in installed_essential]
                
                    if missing_essential:
                        health_status['warnings'].append(f"Missing essential add-ons: {', '.join(missing_essential)}")
                        self.print_colored(Colors.YELLOW, f"   ⚠️  Missing essential add-ons: {', '.join(missing_essential)}")
                
                except Exception as e:
                    health_status['addon_health'] = {}
                    health_status['issues'].append(f"Failed to check add-ons: {str(e)}")
                    self.print_colored(Colors.RED, f"   ❌ Add-on check failed: {str(e)}")
            
                # 4. Check nodes using kubectl (if available)
                try:
                    import subprocess
                    import shutil
                
                    kubectl_available = shutil.which('kubectl') is not None
                
                    if kubectl_available:
                        env = os.environ.copy()
                        env['AWS_ACCESS_KEY_ID'] = admin_access_key
                        env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
                        env['AWS_DEFAULT_REGION'] = region
                    
                        # Update kubeconfig
                        update_result = subprocess.run([
                            'aws', 'eks', 'update-kubeconfig',
                            '--region', region,
                            '--name', cluster_name
                        ], env=env, capture_output=True, timeout=60)
                    
                        if update_result.returncode == 0:
                            # Check nodes
                            nodes_result = subprocess.run([
                                'kubectl', 'get', 'nodes', '--no-headers'
                            ], env=env, capture_output=True, text=True, timeout=30)
                        
                            if nodes_result.returncode == 0:
                                node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
                                ready_nodes = [line for line in node_lines if 'Ready' in line and 'NotReady' not in line]
                                not_ready_nodes = [line for line in node_lines if 'NotReady' in line]
                            
                                health_status['total_nodes'] = len(node_lines)
                                health_status['ready_nodes'] = len(ready_nodes)
                                health_status['not_ready_nodes'] = len(not_ready_nodes)
                            
                                if len(ready_nodes) == 0:
                                    health_status['overall_healthy'] = False
                                    health_status['issues'].append("No nodes are in Ready state")
                                    self.print_colored(Colors.RED, f"   ❌ No nodes ready")
                                elif len(not_ready_nodes) > 0:
                                    health_status['warnings'].append(f"{len(not_ready_nodes)} nodes are not ready")
                                    self.print_colored(Colors.YELLOW, f"   ⚠️  Nodes ready: {len(ready_nodes)}/{len(node_lines)} ({len(not_ready_nodes)} not ready)")
                                else:
                                    health_status['success_items'].append(f"All {len(ready_nodes)} nodes are ready")
                                    self.print_colored(Colors.GREEN, f"   ✅ All nodes ready: {len(ready_nodes)}/{len(node_lines)}")
                            
                                # Check system pods
                                pods_result = subprocess.run([
                                    'kubectl', 'get', 'pods', '-n', 'kube-system', '--no-headers'
                                ], env=env, capture_output=True, text=True, timeout=30)
                            
                                if pods_result.returncode == 0:
                                    pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
                                    running_pods = [line for line in pod_lines if 'Running' in line or 'Completed' in line]
                                    failed_pods = [line for line in pod_lines if 'Failed' in line or 'Error' in line]
                                
                                    health_status['total_system_pods'] = len(pod_lines)
                                    health_status['running_system_pods'] = len(running_pods)
                                    health_status['failed_system_pods'] = len(failed_pods)
                                
                                    if len(failed_pods) > 0:
                                        health_status['warnings'].append(f"{len(failed_pods)} system pods have failed")
                                        self.print_colored(Colors.YELLOW, f"   ⚠️  System pods: {len(running_pods)}/{len(pod_lines)} running ({len(failed_pods)} failed)")
                                    else:
                                        health_status['success_items'].append(f"All {len(running_pods)} system pods are running")
                                        self.print_colored(Colors.GREEN, f"   ✅ System pods: {len(running_pods)}/{len(pod_lines)} running")
                            else:
                                health_status['warnings'].append("Could not retrieve node status via kubectl")
                                self.print_colored(Colors.YELLOW, f"   ⚠️  Could not check nodes via kubectl")
                        else:
                            health_status['warnings'].append("Could not update kubeconfig for kubectl access")
                    else:
                        health_status['warnings'].append("kubectl not available for node status check")
                        self.print_colored(Colors.YELLOW, f"   ⚠️  kubectl not available for detailed node check")
                    
                except Exception as e:
                    health_status['warnings'].append(f"Failed to check nodes via kubectl: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️  kubectl check failed: {str(e)}")
            
                # 5. Final health assessment
                total_issues = len(health_status['issues'])
                total_warnings = len(health_status['warnings'])
                total_successes = len(health_status['success_items'])
            
                health_status['summary'] = {
                    'total_issues': total_issues,
                    'total_warnings': total_warnings,
                    'total_successes': total_successes,
                    'health_score': max(0, 100 - (total_issues * 20) - (total_warnings * 5))
                }
            
                # Log comprehensive health check results
                if health_status['overall_healthy']:
                    self.log_operation('INFO', f"Health check PASSED for {cluster_name} - Score: {health_status['summary']['health_score']}/100")
                    self.print_colored(Colors.GREEN, f"   🎉 Overall Health: HEALTHY (Score: {health_status['summary']['health_score']}/100)")
                else:
                    self.log_operation('WARNING', f"Health check FAILED for {cluster_name} - {total_issues} issues, {total_warnings} warnings")
                    self.print_colored(Colors.YELLOW, f"   ⚠️  Overall Health: NEEDS ATTENTION ({total_issues} issues, {total_warnings} warnings)")
            
                return health_status
            
            except Exception as e:
                from datetime import datetime
                current_timestamp = int(datetime.utcnow().timestamp())

                error_msg = str(e)
                self.log_operation('ERROR', f"Health check exception for {cluster_name}: {error_msg}")
                self.print_colored(Colors.RED, f"   ❌ Health check failed: {error_msg}")
                return {
                    'cluster_name': cluster_name,
                    'region': region,
                    'check_timestamp': current_timestamp,
                    'checked_by': 'varadharajaan',
                    'overall_healthy': False,
                    'error': error_msg,
                    'issues': [f"Health check exception: {error_msg}"],
                    'warnings': [],
                    'success_items': []
                }

    def create_kubectl_awscli_layer(self, lambda_client, layer_name: str = "kubectl-layer") -> Optional[str]:
        """
        Create a Lambda layer with kubectl only (removed AWS CLI)
        """
        try:
            self.print_colored(Colors.CYAN, "   📦 Creating kubectl Lambda layer...")

            import tempfile
            import zipfile
            import urllib.request
            import os
            import stat

            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                layer_dir = os.path.join(temp_dir, "layer")
                bin_dir = os.path.join(layer_dir, "bin")
                os.makedirs(bin_dir, exist_ok=True)

                # Download kubectl
                self.print_colored(Colors.BLUE, "   📥 Downloading kubectl...")
                kubectl_url = "https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl"
                kubectl_path = os.path.join(bin_dir, "kubectl")

                urllib.request.urlretrieve(kubectl_url, kubectl_path)

                # Make kubectl executable
                os.chmod(kubectl_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                self.print_colored(Colors.GREEN, "   [OK] kubectl downloaded and made executable")

                # Create zip file
                zip_path = os.path.join(temp_dir, "kubectl-layer.zip")

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Add kubectl
                    zipf.write(kubectl_path, "bin/kubectl")

                    # Add a simple bootstrap script
                    bootstrap_script = """#!/bin/bash
    export PATH="/opt/bin:$PATH"
    """
                    bootstrap_path = os.path.join(temp_dir, "bootstrap")
                    with open(bootstrap_path, 'w') as f:
                        f.write(bootstrap_script)
                    os.chmod(bootstrap_path, 0o755)
                    zipf.write(bootstrap_path, "bootstrap")

                # Read zip file
                with open(zip_path, 'rb') as f:
                    zip_content = f.read()

                # Check if layer already exists
                try:
                    existing_layers = lambda_client.list_layers()
                    layer_exists = any(layer['LayerName'] == layer_name for layer in existing_layers.get('Layers', []))

                    if layer_exists:
                        self.print_colored(Colors.YELLOW,
                                           f"   ⚠️  Layer {layer_name} already exists, using existing version")
                        # Get the latest version
                        layer_versions = lambda_client.list_layer_versions(LayerName=layer_name)
                        if layer_versions.get('LayerVersions'):
                            latest_version = layer_versions['LayerVersions'][0]
                            return latest_version['LayerVersionArn']

                    # Create new layer
                    self.print_colored(Colors.BLUE, f"   📦 Publishing kubectl layer...")

                    response = lambda_client.publish_layer_version(
                        LayerName=layer_name,
                        Description="kubectl binary for EKS operations",
                        Content={'ZipFile': zip_content},
                        CompatibleRuntimes=['python3.9', 'python3.10', 'python3.11'],
                        CompatibleArchitectures=['x86_64']
                    )

                    layer_arn = response['LayerVersionArn']
                    self.print_colored(Colors.GREEN, f"   ✅ kubectl layer created: {layer_arn}")

                    return layer_arn

                except Exception as e:
                    self.print_colored(Colors.RED, f"   ❌ Failed to create kubectl layer: {str(e)}")
                    return None

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to create kubectl layer: {str(e)}")
            return None

    def create_minimal_kubectl_layer(self, region: str, admin_access_key: str, admin_secret_key: str) -> str:
        """
        Alternative: Create a minimal layer with just kubectl (much smaller and more reliable).
        """
        try:
            self.print_colored(Colors.YELLOW, f"🔧 Creating minimal kubectl layer...")

            # Create AWS session
            import boto3
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            lambda_client = admin_session.client('lambda')
            layer_name = "kubectl-minimal-layer"

            # Check if layer already exists
            try:
                response = lambda_client.list_layer_versions(LayerName=layer_name, MaxItems=1)
                if response.get('LayerVersions'):
                    latest_version = response['LayerVersions'][0]
                    layer_arn = latest_version['LayerVersionArn']
                    self.print_colored(Colors.CYAN, f"   📦 Using existing minimal layer: {layer_arn}")
                    return layer_arn
            except lambda_client.exceptions.ResourceNotFoundException:
                pass

            import tempfile
            import os
            import zipfile
            import urllib.request
            import shutil

            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            layer_dir = os.path.join(temp_dir, 'layer')
            bin_dir = os.path.join(layer_dir, 'bin')
            os.makedirs(bin_dir, exist_ok=True)

            try:
                # Download only kubectl
                self.print_colored(Colors.CYAN, f"   ⬇️  Downloading kubectl...")
                kubectl_url = "https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl"
                kubectl_path = os.path.join(bin_dir, 'kubectl')

                urllib.request.urlretrieve(kubectl_url, kubectl_path)
                os.chmod(kubectl_path, 0o755)

                kubectl_size_mb = os.path.getsize(kubectl_path) / 1024 / 1024
                self.print_colored(Colors.GREEN, f"   ✅ kubectl downloaded ({kubectl_size_mb:.1f} MB)")

                # Create zip
                temp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
                temp_zip_path = temp_zip.name
                temp_zip.close()

                with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zip_file:
                    for root, dirs, files in os.walk(layer_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, layer_dir)
                            zip_file.write(file_path, arcname)

                layer_size_mb = os.path.getsize(temp_zip_path) / 1024 / 1024
                self.print_colored(Colors.CYAN, f"   📏 Layer size: {layer_size_mb:.1f} MB")

                # Upload
                self.print_colored(Colors.CYAN, f"   ⬆️  Uploading minimal layer...")

                with open(temp_zip_path, 'rb') as zip_data:
                    response = lambda_client.publish_layer_version(
                        LayerName=layer_name,
                        Description='Minimal Lambda layer with kubectl only',
                        Content={'ZipFile': zip_data.read()},
                        CompatibleRuntimes=['python3.9', 'python3.8', 'python3.10', 'python3.11'],
                        CompatibleArchitectures=['x86_64']
                    )

                    layer_arn = response['LayerVersionArn']
                    self.print_colored(Colors.GREEN, f"   ✅ Minimal layer created: {layer_arn}")
                    return layer_arn

            finally:
                try:
                    shutil.rmtree(temp_dir)
                    os.unlink(temp_zip_path)
                except OSError:
                    pass

        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Minimal layer creation failed: {str(e)}")
            return None

    def setup_node_protection_monitoring(self, cluster_name: str, region: str, admin_access_key: str,
                                                   admin_secret_key: str, nodegroup_names: list) -> bool:
        """
        Setup optimized node protection monitoring with kubectl-only layer (no AWS CLI)
        """
        try:
            # Extract suffix from cluster name
            cluster_suffix = cluster_name.split('-')[-1] if '-' in cluster_name else cluster_name

            # Get current datetime dynamically
            current_datetime = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

            self.log_operation('INFO',
                               f"Setting up optimized node protection monitoring for cluster {cluster_name} (suffix: {cluster_suffix})")

            # Create Lambda client
            lambda_client = boto3.client('lambda', region_name=region,
                                         aws_access_key_id=admin_access_key,
                                         aws_secret_access_key=admin_secret_key)

            # Create IAM client for role management
            iam_client = boto3.client('iam', region_name=region,
                                      aws_access_key_id=admin_access_key,
                                      aws_secret_access_key=admin_secret_key)

            # Get account ID
            sts_client = boto3.client('sts', region_name=region,
                                      aws_access_key_id=admin_access_key,
                                      aws_secret_access_key=admin_secret_key)
            account_id = sts_client.get_caller_identity()['Account']

            # Step 1: Create only kubectl layer (much smaller, ~15MB)
            self.print_colored(Colors.CYAN, "   📦 Creating kubectl layer (optimized)...")

            kubectl_layer_arn = self.create_kubectl_only_layer(lambda_client)

            if not kubectl_layer_arn:
                self.print_colored(Colors.RED, "   ❌ Failed to create kubectl layer")
                return False

            self.print_colored(Colors.GREEN, f"   ✅ kubectl layer created: {kubectl_layer_arn}")

            # Step 2: Create IAM role with new naming convention
            role_name = f"NodeProtectionMonitorRole-{cluster_suffix}"
            self.print_colored(Colors.CYAN, f"   🔑 Creating IAM role: {role_name}")

            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }

            try:
                iam_client.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description=f"Role for optimized Lambda node protection monitoring - {cluster_name} (suffix: {cluster_suffix})"
                )
                self.print_colored(Colors.GREEN, f"   ✅ Created IAM role: {role_name}")
            except iam_client.exceptions.EntityAlreadyExistsException:
                self.print_colored(Colors.YELLOW, f"   ⚠️  IAM role already exists: {role_name}")

            # Attach policies
            policies = [
                "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                "arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess",
                "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
                "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
            ]

            for policy_arn in policies:
                try:
                    iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
                    self.print_colored(Colors.GREEN, f"   ✅ Attached policy: {policy_arn}")
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️  Policy may already be attached: {policy_arn}")

            # Enhanced inline policy for EKS and EC2 access
            inline_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:CreateTags",
                            "ec2:DeleteTags",
                            "ec2:DescribeInstances",
                            "ec2:DescribeTags",
                            "autoscaling:DescribeAutoScalingGroups",
                            "autoscaling:DescribeAutoScalingInstances",
                            "eks:DescribeCluster",
                            "eks:DescribeNodegroup",
                            "eks:ListNodegroups",
                            "sts:GetCallerIdentity",
                            "sts:GeneratePresignedUrl"
                        ],
                        "Resource": "*"
                    }
                ]
            }

            try:
                iam_client.put_role_policy(
                    RoleName=role_name,
                    PolicyName="OptimizedNodeProtectionPolicy",
                    PolicyDocument=json.dumps(inline_policy)
                )
                self.print_colored(Colors.GREEN, f"   ✅ Created optimized inline policy")
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"   ⚠️  Inline policy may already exist: {str(e)}")

            role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

            # Wait for role to be ready
            self.print_colored(Colors.CYAN, f"   ⏱️  Waiting for IAM role to be ready...")
            time.sleep(10)

            # Step 3: Create optimized Lambda function with template replacement
            function_name = f"node-protection-monitor-eks-{cluster_suffix}"
            self.print_colored(Colors.CYAN, f"   🚀 Creating optimized Lambda function: {function_name}")

            # Read Lambda template and replace variables with proper encoding
            try:
                # Read template file with explicit UTF-8 encoding
                with open('lambda_node_protection_template.py', 'r', encoding='utf-8') as f:
                    lambda_template = f.read()

                self.print_colored(Colors.GREEN, f"   ✅ Lambda template loaded successfully with UTF-8 encoding")

                # Replace template variables with actual values
                lambda_code = lambda_template.replace('{{CLUSTER_NAME}}', cluster_name)
                lambda_code = lambda_code.replace('{{REGION}}', region)
                lambda_code = lambda_code.replace('{{ACCESS_KEY}}', admin_access_key)
                lambda_code = lambda_code.replace('{{SECRET_KEY}}', admin_secret_key)
                lambda_code = lambda_code.replace('{{CURRENT_DATETIME}}', current_datetime)
                lambda_code = lambda_code.replace('{{CURRENT_USER}}', self.current_user)

                self.print_colored(Colors.GREEN, f"   ✅ Template variables replaced successfully")
                self.print_colored(Colors.CYAN, f"   📅 Generated: {current_datetime} UTC by {self.current_user}")

            except FileNotFoundError:
                self.print_colored(Colors.RED,
                                   f"   ❌ Lambda template file 'lambda_node_protection_template.py' not found")
                return False
            except UnicodeDecodeError as e:
                self.print_colored(Colors.RED, f"   ❌ Unicode decode error reading template file: {str(e)}")
                self.print_colored(Colors.YELLOW,
                                   f"   ⚠️  Template file may have encoding issues. Please save it as UTF-8.")
                return False
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Failed to read Lambda template: {str(e)}")
                return False

            # Create proper Lambda deployment package as ZIP
            import tempfile
            import zipfile
            import os

            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Create the lambda function file
                    lambda_file_path = os.path.join(temp_dir, 'lambda_function.py')
                    with open(lambda_file_path, 'w', encoding='utf-8') as f:
                        f.write(lambda_code)

                    # Create ZIP file for Lambda
                    zip_path = os.path.join(temp_dir, 'lambda_function.zip')
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        zip_file.write(lambda_file_path, 'lambda_function.py')

                    # Read the ZIP file as bytes
                    with open(zip_path, 'rb') as zip_file:
                        lambda_zip_content = zip_file.read()

                    self.print_colored(Colors.GREEN,
                                       f"   ✅ Lambda deployment package created: {len(lambda_zip_content)} bytes")

            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Failed to create Lambda deployment package: {str(e)}")
                return False

            # Check if function exists
            function_exists = False
            try:
                lambda_client.get_function(FunctionName=function_name)
                function_exists = True
                self.print_colored(Colors.YELLOW, f"   ⚠️  Lambda function already exists: {function_name}")
            except lambda_client.exceptions.ResourceNotFoundException:
                self.print_colored(Colors.CYAN, f"   📝 Creating new optimized Lambda function...")

            if not function_exists:
                try:
                    lambda_client.create_function(
                        FunctionName=function_name,
                        Runtime='python3.9',
                        Role=role_arn,
                        Handler='lambda_function.lambda_handler',
                        Code={'ZipFile': lambda_zip_content},
                        Description=f'Optimized node protection monitoring for EKS cluster {cluster_name} (suffix: {cluster_suffix}) - No AWS CLI dependency',
                        Timeout=180,
                        MemorySize=256,
                        Layers=[kubectl_layer_arn],
                        Environment={
                            'Variables': {
                                'CLUSTER_NAME': cluster_name,
                                'REGION': region,
                                'NEW_AWS_ACCESS_KEY_ID': admin_access_key,
                                'NEW_AWS_SECRET_ACCESS_KEY': admin_secret_key
                            }
                        }
                    )
                    self.print_colored(Colors.GREEN, f"   ✅ Created optimized Lambda function: {function_name}")
                except Exception as e:
                    self.print_colored(Colors.RED, f"   ❌ Failed to create Lambda function: {str(e)}")
                    return False
            else:
                # Update existing function
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # Update function code with proper ZIP package
                        lambda_client.update_function_code(
                            FunctionName=function_name,
                            ZipFile=lambda_zip_content
                        )

                        # Wait for update to complete
                        time.sleep(5)

                        # Update function configuration
                        lambda_client.update_function_configuration(
                            FunctionName=function_name,
                            Role=role_arn,
                            Handler='lambda_function.lambda_handler',
                            Description=f'Optimized node protection monitoring for EKS cluster {cluster_name} (suffix: {cluster_suffix}) - Updated at {current_datetime}',
                            Timeout=180,
                            MemorySize=256,
                            Layers=[kubectl_layer_arn],
                            Environment={
                                'Variables': {
                                    'CLUSTER_NAME': cluster_name,
                                    'REGION': region,
                                    'NEW_AWS_ACCESS_KEY_ID': admin_access_key,
                                    'NEW_AWS_SECRET_ACCESS_KEY': admin_secret_key
                                }
                            }
                        )

                        self.print_colored(Colors.GREEN, f"   ✅ Updated optimized Lambda function: {function_name}")
                        break

                    except lambda_client.exceptions.ResourceConflictException:
                        if attempt < max_retries - 1:
                            self.print_colored(Colors.YELLOW,
                                               f"   ⚠️  Function update in progress, retrying in {10 * (attempt + 1)} seconds...")
                            time.sleep(10 * (attempt + 1))
                        else:
                            self.print_colored(Colors.RED,
                                               f"   ❌ Failed to update Lambda function after {max_retries} attempts")
                            return False
                    except Exception as e:
                        self.print_colored(Colors.RED, f"   ❌ Failed to update Lambda function: {str(e)}")
                        return False

            # Step 4: Create EventBridge rule with new naming convention
            events_client = boto3.client('events', region_name=region,
                                         aws_access_key_id=admin_access_key,
                                         aws_secret_access_key=admin_secret_key)

            rule_name = f"node-protection-monitor-eks-{cluster_suffix}-rule"
            self.print_colored(Colors.CYAN, f"   📅 Creating EventBridge rule: {rule_name}")

            # Create event pattern for EC2 instance state changes
            event_pattern = {
                "source": ["aws.ec2"],
                "detail-type": ["EC2 Instance State-change Notification"],
                "detail": {
                    "state": ["terminated", "running"]
                }
            }

            try:
                events_client.put_rule(
                    Name=rule_name,
                    EventPattern=json.dumps(event_pattern),
                    State='ENABLED',
                    Description=f'Optimized node protection monitoring for EKS cluster {cluster_name} (suffix: {cluster_suffix})'
                )
                self.print_colored(Colors.GREEN, f"   ✅ Created EventBridge rule: {rule_name}")
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"   ⚠️  EventBridge rule may already exist: {str(e)}")

            # Step 5: Add Lambda permission for EventBridge
            self.print_colored(Colors.CYAN, f"   🔒 Adding Lambda permission for EventBridge...")

            try:
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f"AllowEventBridge-{cluster_suffix}",
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f"arn:aws:events:{region}:{account_id}:rule/{rule_name}"
                )
                self.print_colored(Colors.GREEN, f"   ✅ Added Lambda permission for EventBridge")
            except lambda_client.exceptions.ResourceConflictException:
                self.print_colored(Colors.YELLOW, f"   ⚠️  Lambda permission already exists")
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Failed to add Lambda permission: {str(e)}")

            # Step 6: Create EventBridge target
            self.print_colored(Colors.CYAN, f"   🎯 Creating EventBridge target...")

            try:
                events_client.put_targets(
                    Rule=rule_name,
                    Targets=[
                        {
                            'Id': '1',
                            'Arn': f"arn:aws:lambda:{region}:{account_id}:function:{function_name}",
                            'InputTransformer': {
                                'InputPathsMap': {
                                    'instance_id': '$.detail.instance-id',
                                    'state': '$.detail.state'
                                },
                                'InputTemplate': json.dumps({
                                    'cluster_name': cluster_name,
                                    'region': region,
                                    'instance_id': '<instance_id>',
                                    'state': '<state>',
                                    'nodegroup_names': nodegroup_names
                                })
                            }
                        }
                    ]
                )
                self.print_colored(Colors.GREEN, f"   ✅ Created EventBridge target")
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Failed to create EventBridge target: {str(e)}")
                return False

            # Step 7: Test the Lambda function
            self.print_colored(Colors.CYAN, f"   🧪 Testing optimized Lambda function...")

            test_event = {
                'cluster_name': cluster_name,
                'region': region,
                'test_mode': True
            }

            # sleep for 1 mins
            time.sleep(60)

            try:
                response = lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType='RequestResponse',
                    Payload=json.dumps(test_event)
                )

                response_payload = json.loads(response['Payload'].read())

                if response.get('StatusCode') == 200:
                    self.print_colored(Colors.GREEN, f"   ✅ Lambda function test successful")
                    self.print_colored(Colors.CYAN,
                                       f"   📊 Test result: {response_payload.get('statusCode', 'Unknown')}")
                else:
                    self.print_colored(Colors.YELLOW, f"   ⚠️  Lambda function test returned non-200 status")

            except Exception as e:
                self.print_colored(Colors.YELLOW,
                                   f"   ⚠️  Lambda function test failed (this is often normal): {str(e)}")

            # # Step 8: Create scheduled trigger for regular monitoring
            # self.print_colored(Colors.CYAN, f"   ⏰ Creating scheduled monitoring rule...")
            #
            # schedule_rule_name = f"node-protection-monitor-eks-{cluster_suffix}-schedule"
            #
            # try:
            #     events_client.put_rule(
            #         Name=schedule_rule_name,
            #         ScheduleExpression='rate(5 minutes)',
            #         State='ENABLED',
            #         Description=f'Scheduled optimized node protection monitoring for EKS cluster {cluster_name} (suffix: {cluster_suffix})'
            #     )
            #
            #     # Add permission for scheduled rule
            #     lambda_client.add_permission(
            #         FunctionName=function_name,
            #         StatementId=f"AllowScheduledEventBridge-{cluster_suffix}",
            #         Action='lambda:InvokeFunction',
            #         Principal='events.amazonaws.com',
            #         SourceArn=f"arn:aws:events:{region}:{account_id}:rule/{schedule_rule_name}"
            #     )
            #
            #     # Create target for scheduled rule
            #     events_client.put_targets(
            #         Rule=schedule_rule_name,
            #         Targets=[
            #             {
            #                 'Id': '1',
            #                 'Arn': f"arn:aws:lambda:{region}:{account_id}:function:{function_name}",
            #                 'Input': json.dumps({
            #                     'cluster_name': cluster_name,
            #                     'region': region,
            #                     'scheduled_check': True,
            #                     'nodegroup_names': nodegroup_names
            #                 })
            #             }
            #         ]
            #     )
            #
            #     self.print_colored(Colors.GREEN, f"   ✅ Created scheduled monitoring rule (5-minute interval)")

            except lambda_client.exceptions.ResourceConflictException:
                self.print_colored(Colors.YELLOW, f"   ⚠️  Scheduled monitoring rule already exists")
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"   ⚠️  Failed to create scheduled monitoring: {str(e)}")

            self.print_colored(Colors.GREEN, f"✅ Optimized node protection monitoring setup completed!")
            self.print_colored(Colors.CYAN, f"   📋 Function: {function_name}")
            self.print_colored(Colors.CYAN, f"   🔑 Role: {role_name}")
            self.print_colored(Colors.CYAN, f"   📦 Layer: kubectl only (~15MB vs 70MB)")
            self.print_colored(Colors.CYAN, f"   🔧 Method: Boto3 kubeconfig generation")
            self.print_colored(Colors.CYAN, f"   ⏱️  Timeout: 180s (optimized)")
            self.print_colored(Colors.CYAN, f"   💾 Memory: 256MB (optimized)")
            self.print_colored(Colors.CYAN, f"   🎯 Monitoring: {len(nodegroup_names)} nodegroups")
            self.print_colored(Colors.CYAN, f"   🏷️  Cluster Suffix: {cluster_suffix}")
            self.print_colored(Colors.CYAN, f"   📅 Generated: {current_datetime} UTC by {self.current_user}")
            self.print_colored(Colors.CYAN, f"   📝 Encoding: UTF-8 (prevents charmap errors)")
            self.print_colored(Colors.CYAN, f"   📦 Package: Proper ZIP format (prevents unzip errors)")

            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup optimized node protection monitoring: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Optimized node protection monitoring setup failed: {str(e)}")
            return False

    def create_kubectl_only_layer(self, lambda_client):
        """
        Create a kubectl-only layer (much smaller than combined layer)
        """
        try:
            self.print_colored(Colors.CYAN, "   📦 Creating kubectl-only layer...")

            # Create minimal kubectl layer
            import tempfile
            import zipfile
            import os

            with tempfile.TemporaryDirectory() as temp_dir:
                # Create layer structure
                layer_dir = os.path.join(temp_dir, 'kubectl-layer')
                bin_dir = os.path.join(layer_dir, 'bin')
                os.makedirs(bin_dir, exist_ok=True)

                # Download kubectl binary
                kubectl_url = "https://dl.k8s.io/release/v1.28.2/bin/linux/amd64/kubectl"
                kubectl_path = os.path.join(bin_dir, 'kubectl')

                self.print_colored(Colors.CYAN, f"   📥 Downloading kubectl from {kubectl_url}")

                import urllib.request
                urllib.request.urlretrieve(kubectl_url, kubectl_path)
                os.chmod(kubectl_path, 0o755)

                # Create zip file
                zip_path = os.path.join(temp_dir, 'kubectl-layer.zip')
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for root, dirs, files in os.walk(layer_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_path = os.path.relpath(file_path, layer_dir)
                            zip_file.write(file_path, arc_path)

                # Upload layer
                with open(zip_path, 'rb') as zip_file:
                    layer_response = lambda_client.publish_layer_version(
                        LayerName='kubectl-only-layer',
                        Description='kubectl binary for EKS operations (optimized)',
                        Content={'ZipFile': zip_file.read()},
                        CompatibleRuntimes=['python3.9', 'python3.8'],
                        CompatibleArchitectures=['x86_64']
                    )

                layer_arn = layer_response['LayerVersionArn']
                self.print_colored(Colors.GREEN, f"   ✅ kubectl-only layer created: {layer_arn}")

                return layer_arn

        except Exception as e:
            self.print_colored(Colors.RED, f"   ❌ Failed to create kubectl-only layer: {str(e)}")
            return None

    def create_kubectl_pyyaml_layer(self, lambda_client):
        """
        Create a kubectl + PyYAML layer (still much smaller than AWS CLI)
        """
        try:
            self.print_colored(Colors.CYAN, "   📦 Creating kubectl + PyYAML layer...")

            import tempfile
            import zipfile
            import os
            import subprocess

            with tempfile.TemporaryDirectory() as temp_dir:
                # Create layer structure
                layer_dir = os.path.join(temp_dir, 'kubectl-pyyaml-layer')
                bin_dir = os.path.join(layer_dir, 'bin')
                python_dir = os.path.join(layer_dir, 'python')
                os.makedirs(bin_dir, exist_ok=True)
                os.makedirs(python_dir, exist_ok=True)

                # Download kubectl binary
                kubectl_url = "https://dl.k8s.io/release/v1.28.2/bin/linux/amd64/kubectl"
                kubectl_path = os.path.join(bin_dir, 'kubectl')

                self.print_colored(Colors.CYAN, f"   📥 Downloading kubectl from {kubectl_url}")

                import urllib.request
                urllib.request.urlretrieve(kubectl_url, kubectl_path)
                os.chmod(kubectl_path, 0o755)

                # Install PyYAML using pip
                self.print_colored(Colors.CYAN, f"   📦 Installing PyYAML...")

                try:
                    subprocess.run([
                        'pip', 'install', 'pyyaml>=6.0.0',
                        '--target', python_dir,
                        '--no-deps',
                        '--platform', 'linux_x86_64',
                        '--implementation', 'cp',
                        '--python-version', '3.9',
                        '--only-binary=:all:'
                    ], check=True, capture_output=True)

                    self.print_colored(Colors.GREEN, f"   ✅ PyYAML installed successfully")

                except subprocess.CalledProcessError as e:
                    self.print_colored(Colors.RED, f"   ❌ Failed to install PyYAML: {e.stderr.decode()}")
                    return None

                # Create zip file
                zip_path = os.path.join(temp_dir, 'kubectl-pyyaml-layer.zip')
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for root, dirs, files in os.walk(layer_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_path = os.path.relpath(file_path, layer_dir)
                            zip_file.write(file_path, arc_path)

                # Check layer size
                layer_size = os.path.getsize(zip_path)
                layer_size_mb = layer_size / (1024 * 1024)
                self.print_colored(Colors.CYAN, f"   📊 Layer size: {layer_size_mb:.2f} MB")

                # Upload layer
                with open(zip_path, 'rb') as zip_file:
                    layer_response = lambda_client.publish_layer_version(
                        LayerName='kubectl-pyyaml-layer',
                        Description='kubectl binary + PyYAML for EKS operations (optimized)',
                        Content={'ZipFile': zip_file.read()},
                        CompatibleRuntimes=['python3.9', 'python3.8'],
                        CompatibleArchitectures=['x86_64']
                    )

                layer_arn = layer_response['LayerVersionArn']
                self.print_colored(Colors.GREEN, f"   ✅ kubectl + PyYAML layer created: {layer_arn}")

                return layer_arn

        except Exception as e:
            self.print_colored(Colors.RED, f"   ❌ Failed to create kubectl + PyYAML layer: {str(e)}")
            return None

    def create_node_termination_eventbridge_rule(self, region: str, account_id: str, lambda_arn: str,
                                                 nodegroup_names: List[str], admin_access_key, admin_secret_key) -> bool:
        """Create EventBridge rule to trigger Lambda when EC2 instances in nodegroups are terminated"""
        try:
            # Extract cluster suffix for naming
            cluster_suffix = lambda_arn.split('-')[-1]
            rule_name = f"node-termination-monitor-{cluster_suffix}"

            # Use the same session context for both services
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            events_client = admin_session.client('events', region_name=region)
            lambda_client = admin_session.client('lambda', region_name=region)

            # Verify account context
            sts_client = admin_session.client('sts')
            current_account = sts_client.get_caller_identity()['Account']

            if current_account != account_id:
                self.print_colored(Colors.RED, f"❌ Account mismatch: Current={current_account}, Expected={account_id}")
                return False

            # Create event pattern
            event_pattern = {
                "source": ["aws.ec2"],
                "detail-type": ["EC2 Instance State-change Notification"],
                "detail": {
                    "state": ["running", "terminated"]
                }
            }

            # Log the event pattern
            self.logger.info("Event pattern updated to trigger on EC2 instance creation and deletion events:")
            self.logger.info(json.dumps(event_pattern, indent=2))

            # Create the rule
            try:
                events_client.put_rule(
                    Name=rule_name,
                    EventPattern=json.dumps(event_pattern),
                    State='ENABLED',
                    Description=f'Monitor EC2 terminations for EKS nodegroups: {", ".join(nodegroup_names)}'
                )
                self.print_colored(Colors.GREEN, f"   ✅ EventBridge rule {rule_name} created")
            except Exception as e:
                if "already exists" in str(e):
                    self.print_colored(Colors.CYAN, f"   📝 EventBridge rule {rule_name} already exists")
                else:
                    raise e

            # Construct proper ARNs
            rule_arn = f"arn:aws:events:{region}:{current_account}:rule/{rule_name}"
            statement_id = f"AllowEventBridge-{cluster_suffix}"

            # Add Lambda permission - try with different approaches
            try:
                # Method 1: Standard permission
                lambda_client.add_permission(
                    FunctionName=lambda_arn,
                    StatementId=statement_id,
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=rule_arn
                )
                self.print_colored(Colors.GREEN, f"   ✅ Lambda permission added for EventBridge")
            except lambda_client.exceptions.ResourceConflictException:
                self.print_colored(Colors.CYAN, f"   📝 Lambda permission already exists")
            except Exception as e:
                if "Cross-account access" in str(e):
                    # Method 2: Remove and re-add permission
                    try:
                        lambda_client.remove_permission(
                            FunctionName=lambda_arn,
                            StatementId=statement_id
                        )
                        time.sleep(2)
                        lambda_client.add_permission(
                            FunctionName=lambda_arn,
                            StatementId=statement_id,
                            Action='lambda:InvokeFunction',
                            Principal='events.amazonaws.com',
                            SourceArn=rule_arn
                        )
                        self.print_colored(Colors.GREEN, f"   ✅ Lambda permission recreated successfully")
                    except Exception as e2:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Permission issue: {str(e2)}")
                        # Continue anyway - the rule might still work
                else:
                    raise e

            # Add Lambda as target
            events_client.put_targets(
                Rule=rule_name,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': lambda_arn,
                        'InputTransformer': {
                            'InputPathsMap': {
                                'instance_id': '$.detail.instance-id',
                                'state': '$.detail.state',
                                'region': '$.region',
                                'account': '$.account'
                            },
                            'InputTemplate': json.dumps({
                                'instance_id': '<instance_id>',
                                'state': '<state>',
                                'region': '<region>',
                                'account': '<account>',
                                'nodegroup_names': nodegroup_names,
                                'source': 'eventbridge-termination'
                            })
                        }
                    }
                ]
            )

            self.print_colored(Colors.GREEN, f"   ✅ Lambda target added to EventBridge rule")
            return True

        except Exception as e:
            self.log_operation('ERROR', f"Failed to create EventBridge rule: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Failed to create EventBridge rule: {str(e)}")
            return False

    def apply_no_delete_to_matching_nodegroups(self, cluster_name, region, access_key, secret_key):
        """Apply NO_DELETE labels to all nodes in nodegroups matching nodegroup-*-ondemand pattern"""

        import boto3
        import subprocess
        import json
        import re
        import os
        from datetime import datetime

        # Set current user and datetime
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_user = 'varadharajaan'
        current_datetime = current_timestamp

        print("=" * 80)
        print("🚀 STARTING NO_DELETE LABEL APPLICATION")
        print("=" * 80)
        print(f"📅 Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {current_datetime}")
        print(f"👤 Current User's Login: {current_user}")
        print(f"🏷️  Cluster Name: {cluster_name}")
        print(f"🌍 Region: {region}")
        print(f"🎯 Target Pattern: nodegroup-*-ondemand (where * is 0-9) if not found then Target Pattern: nodegroup-*-")
        print("=" * 80)

        try:
            # Create AWS session with credentials
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            eks_client = session.client('eks')
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region

            # Step 1: Update kubeconfig
            print(f"🔧 Updating kubeconfig for cluster: {cluster_name} in region: {region}")
            subprocess.run([
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ], check=True, capture_output=True, env=env)
            print("✅ Kubeconfig updated successfully")

            # Step 2: Get all nodegroups and filter matching ones
            print("📋 Fetching all nodegroups from EKS...")
            response = eks_client.list_nodegroups(clusterName=cluster_name)
            all_nodegroups = response.get('nodegroups', [])

            # Pattern: nodegroup-[0-9]-ondemand
            # First try to match nodegroup-[0-9]-ondemand pattern
            primary_pattern = re.compile(r'^nodegroup-[0-9]-ondemand$')
            matching_nodegroups = [ng for ng in all_nodegroups if primary_pattern.match(ng)]

            # If none found, try more flexible pattern nodegroup-[0-9]-*
            if not matching_nodegroups:
                secondary_pattern = re.compile(r'^nodegroup-[0-9]-.*$')
                matching_nodegroups = [ng for ng in all_nodegroups if secondary_pattern.match(ng)]

            # If still none found, try the most flexible pattern nodegroup-*
            if not matching_nodegroups:
                fallback_pattern = re.compile(r'^nodegroup-.*$')
                matching_nodegroups = [ng for ng in all_nodegroups if fallback_pattern.match(ng)]
                # If multiple found with the fallback pattern, just take the first one
                if len(matching_nodegroups) > 1:
                    print(
                        f"⚠️ Multiple nodegroups found with pattern 'nodegroup-*'. Selecting the first one: {matching_nodegroups[0]}")
                    matching_nodegroups = [matching_nodegroups[0]]

            print(f"📊 Total nodegroups found: {len(all_nodegroups)}")
            print(f"🎯 Matching nodegroups found: {len(matching_nodegroups)}")

            if matching_nodegroups:
                for ng in matching_nodegroups:
                    print(f"   ✓ {ng}")
            else:
                print("⚠️ No nodegroups found matching any 'nodegroup-*' pattern")
                return {
                    'success': False,
                    'message': 'No matching nodegroups found',
                    'nodegroups_processed': 0,
                    'nodes_labeled': 0
                }

            # Update kubeconfig before running kubectl
            subprocess.run([
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ], check=True, capture_output=True, env=env)
            print("✅ Kubeconfig updated successfully")

            # Step 3: Get all nodes and process matching ones
            print("🔍 Getting all nodes and processing...")
            # Now run kubectl
            result = subprocess.run([
                'kubectl', 'get', 'nodes', '-o', 'json'
            ], capture_output=True, text=True, check=True, env=env)

            nodes_data = json.loads(result.stdout)

            # Initialize counters
            results = {
                'total_processed': 0,
                'newly_labeled': 0,
                'already_labeled': 0,
                'skipped': 0,
                'errors': 0,
                'nodes_to_verify': []  # Track nodes we labeled for verification
            }

            print(f"📋 Found {len(nodes_data['items'])} total nodes in cluster")

            # Process each node
            count = 0
            for node in nodes_data['items']:
                if count >= 1:
                    break
                node_name = node['metadata']['name']
                node_labels = node['metadata'].get('labels', {})

                # Get the nodegroup this node belongs to
                nodegroup_label = node_labels.get('eks.amazonaws.com/nodegroup')

                if nodegroup_label and nodegroup_label in matching_nodegroups:
                    print(f"\n🎯 Processing node: {node_name} (nodegroup: {nodegroup_label})")
                    results['total_processed'] += 1

                    # Check if NO_DELETE label already exists
                    current_no_delete = node_labels.get('NO_DELETE')

                    if current_no_delete == 'true':
                        print(f"✅ Node {node_name} already has NO_DELETE=true")
                        results['already_labeled'] += 1
                    else:
                        # Apply NO_DELETE and related labels
                        raw_datetime = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                        label_safe_timestamp = raw_datetime.replace(' ', 'T').replace(':', '-')

                        protection_labels = {
                            'NO_DELETE': 'true',
                            'protection-level': 'high',
                            'protected-by': current_user,
                            'protection-date': datetime.utcnow().strftime('%Y-%m-%d'),
                            'protection-time': datetime.utcnow().strftime('%H-%M-%S'),
                            'protection-timestamp': label_safe_timestamp,
                            'managed-by': 'automation',
                            'nodegroup-protected': nodegroup_label
                        }

                        try:
                            # Apply each label
                            for label_key, label_value in protection_labels.items():
                                subprocess.run([
                                    'kubectl', 'label', 'node', node_name,
                                    f'{label_key}={label_value}', '--overwrite'
                                ], check=True, capture_output=True, env=env)

                            print(f"✅ Successfully applied NO_DELETE protection to node: {node_name}")
                            print(f"   📋 Labels applied: {list(protection_labels.keys())}")
                            results['newly_labeled'] += 1
                            results['nodes_to_verify'].append({
                                'node_name': node_name,
                                'nodegroup': nodegroup_label,
                                'labels_applied': protection_labels
                            })
                            count = count +1
                        except subprocess.CalledProcessError as e:
                            print(f"❌ Failed to apply labels to node {node_name}: {e}")
                            # print e.stderr.decode()
                            if e.stderr:
                                error_msg = e.stderr.decode().strip() if isinstance(e.stderr, bytes) else e.stderr.strip()
                                print(f"   Error details when applying NO_DELETE Protection Label: {error_msg}")

                            results['errors'] += 1
                        except Exception as e:
                            print(f"❌ Unexpected error applying labels to {node_name}: {e}")
                            results['errors'] += 1
                else:
                    results['skipped'] += 1

            # Step 4: COMPREHENSIVE VERIFICATION OF APPLIED LABELS
            print("\n" + "=" * 80)
            print("🔍 VERIFICATION: Checking Applied Labels")
            print("=" * 80)

            verification_results = {
                'verified_successfully': 0,
                'verification_failed': 0,
                'missing_labels': 0
            }

            if results['nodes_to_verify']:
                print(f"🔍 Verifying {len(results['nodes_to_verify'])} newly labeled nodes...")

                for node_info in results['nodes_to_verify']:
                    node_name = node_info['node_name']
                    nodegroup = node_info['nodegroup']
                    expected_labels = node_info['labels_applied']

                    print(f"\n📋 Verifying node: {node_name} (nodegroup: {nodegroup})")

                    try:
                        # Get current node labels
                        verify_result = subprocess.run([
                            'kubectl', 'get', 'node', node_name, '-o', 'json'
                        ], capture_output=True, text=True, check=True, env=env)

                        node_data = json.loads(verify_result.stdout)
                        current_labels = node_data['metadata'].get('labels', {})

                        # Check each expected label
                        all_labels_present = True
                        missing_labels = []

                        for label_key, expected_value in expected_labels.items():
                            actual_value = current_labels.get(label_key)

                            if actual_value == expected_value:
                                print(f"   ✅ {label_key}={actual_value}")
                            else:
                                print(f"   ❌ {label_key}: expected='{expected_value}', actual='{actual_value}'")
                                all_labels_present = False
                                missing_labels.append(label_key)

                        if all_labels_present:
                            print(f"   🎯 All labels verified successfully on {node_name}")
                            verification_results['verified_successfully'] += 1
                        else:
                            print(f"   ⚠️ Some labels missing on {node_name}: {missing_labels}")
                            verification_results['verification_failed'] += 1
                            verification_results['missing_labels'] += len(missing_labels)

                    except Exception as e:
                        print(f"   ❌ Error verifying node {node_name}: {e}")
                        verification_results['verification_failed'] += 1

            # Step 5: Verify all nodes in matching nodegroups
            print(f"\n🔍 VERIFICATION: All Nodes in Matching Nodegroups")
            print("-" * 60)

            for nodegroup in matching_nodegroups:
                print(f"\n📋 Nodegroup: {nodegroup}")

                try:
                    # Get nodes with their labels for this nodegroup
                    verify_result = subprocess.run([
                        'kubectl', 'get', 'nodes',
                        '-l', f'eks.amazonaws.com/nodegroup={nodegroup}',
                        '-o',
                        'custom-columns=NAME:.metadata.name,NO_DELETE:.metadata.labels.NO_DELETE,PROTECTED_BY:.metadata.labels.protected-by,PROTECTION_DATE:.metadata.labels.protection-date,PROTECTION_TIME:.metadata.labels.protection-time'
                    ], capture_output=True, text=True, check=True, env=env)

                    print("Final Verification Results:")
                    for line in verify_result.stdout.strip().split('\n'):
                        if 'NAME' in line:
                            print(f"   {line}")  # Header
                        else:
                            # Check if NO_DELETE is true
                            parts = line.split()
                            if len(parts) >= 2:
                                node_name = parts[0]
                                no_delete_value = parts[1] if len(parts) > 1 else '<none>'
                                if no_delete_value == 'true':
                                    print(f"   ✅ {line}")
                                else:
                                    print(f"   ⚠️ {line}")
                            else:
                                print(f"   {line}")

                    # Count nodes with NO_DELETE=true in this nodegroup
                    count_result = subprocess.run([
                        'kubectl', 'get', 'nodes',
                        '-l', f'eks.amazonaws.com/nodegroup={nodegroup},NO_DELETE=true',
                        '--no-headers'
                    ], capture_output=True, text=True, check=True, env=env)

                    protected_count = len([line for line in count_result.stdout.strip().split('\n') if line.strip()])
                    print(f"   📊 Nodes with NO_DELETE=true: {protected_count}")

                except Exception as e:
                    print(f"   ❌ Error verifying nodegroup {nodegroup}: {e}")

            # Step 6: Final Summary
            print("\n" + "=" * 80)
            print("📊 FINAL OPERATION SUMMARY")
            print("=" * 80)
            print(f"👤 Applied by: {current_user}")
            print(f"📅 Completed at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
            print(f"🎯 Nodegroups targeted: {len(matching_nodegroups)}")
            print(f"   • {', '.join(matching_nodegroups)}")
            print(f"📋 Nodes processed: {results['total_processed']}")
            print(f"🏷️  Nodes newly labeled: {results['newly_labeled']}")
            print(f"✅ Nodes already labeled: {results['already_labeled']}")
            print(f"⏭️ Nodes skipped: {results['skipped']}")
            print(f"❌ Errors encountered: {results['errors']}")
            print("\n🔍 VERIFICATION SUMMARY:")
            print(f"✅ Nodes verified successfully: {verification_results['verified_successfully']}")
            print(f"❌ Nodes with verification issues: {verification_results['verification_failed']}")
            print(f"⚠️ Missing labels found: {verification_results['missing_labels']}")
            print("=" * 80)

            # Step 7: Quick command to verify all protected nodes
            print(f"\n🔍 QUICK VERIFICATION COMMAND:")
            print(f"To quickly check all protected nodes, run:")
            print(
                f"kubectl get nodes -l NO_DELETE=true -o custom-columns=NAME:.metadata.name,NODEGROUP:.metadata.labels.eks\\.amazonaws\\.com/nodegroup,NO_DELETE:.metadata.labels.NO_DELETE,PROTECTED_BY:.metadata.labels.protected-by")

            # Return results
            return {
                'success': True,
                'message': 'NO_DELETE labels applied and verified successfully',
                'all_nodegroups': all_nodegroups,
                'nodegroups_processed': len(matching_nodegroups),
                'nodes_labeled': results['newly_labeled'],
                'nodes_already_labeled': results['already_labeled'],
                'total_nodes_processed': results['total_processed'],
                'matching_nodegroups': matching_nodegroups,
                'timestamp': current_datetime,
                'applied_by': current_user,
                'errors': results['errors'],
                'verification': {
                    'verified_successfully': verification_results['verified_successfully'],
                    'verification_failed': verification_results['verification_failed'],
                    'missing_labels': verification_results['missing_labels']
                }
            }

        except subprocess.CalledProcessError as e:
            error_msg = f"Command failed: {e}"
            print(f"❌ {error_msg}")
            return {
                'success': False,
                'message': error_msg,
                'nodegroups_processed': 0,
                'nodes_labeled': 0
            }

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(f"❌ CRITICAL ERROR: {error_msg}")
            return {
                'success': False,
                'message': error_msg,
                'nodegroups_processed': 0,
                'nodes_labeled': 0
            }

    def protect_nodes_with_no_delete_label(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """
        Protect nodes with NO_DELETE label from cluster autoscaler scale-down
        by adding the cluster-autoscaler.kubernetes.io/scale-down-disabled annotation
        """
        try:
            self.log_operation('INFO', f"Prot"
                                       f"ecting nodes with NO_DELETE label in cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔒 Protecting nodes with NO_DELETE label...")

            # Check if kubectl is available
            import subprocess
            import shutil

            kubectl_available = shutil.which('kubectl') is not None
            if not kubectl_available:
                self.log_operation('WARNING', f"kubectl not found. Cannot protect nodes")
                self.print_colored(Colors.YELLOW, f"kubectl not found. Manual node protection required.")
                return False

            # Set environment variables for access
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region

            # Update kubeconfig
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]

            update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
            if update_result.returncode != 0:
                self.print_colored(Colors.RED, f"Failed to update kubeconfig: {update_result.stderr}")
                return False

            # Get nodes with NO_DELETE label
            get_nodes_cmd = ['kubectl', 'get', 'nodes', '-l', 'NO_DELETE', '--no-headers']
            nodes_result = subprocess.run(get_nodes_cmd, env=env, capture_output=True, text=True, timeout=60)

            if nodes_result.returncode != 0:
                self.print_colored(Colors.YELLOW, f"No nodes found with NO_DELETE label or kubectl error")
                return True  # Not an error, just no nodes to protect

            if not nodes_result.stdout.strip():
                self.print_colored(Colors.CYAN, f"No nodes found with NO_DELETE label")
                return True

            # Process each node with NO_DELETE label
            node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
            protected_nodes = 0

            count = 0
            for line in node_lines:
                if count >=2:
                    break
                node_name = line.split()[0] if line.split() else ""
                if not node_name:
                    continue

                # Check if annotation already exists
                check_annotation_cmd = [
                    'kubectl', 'get', 'node', node_name,
                    '-o', 'jsonpath={.metadata.annotations.cluster-autoscaler\\.kubernetes\\.io/scale-down-disabled}'
                ]

                check_result = subprocess.run(check_annotation_cmd, env=env, capture_output=True, text=True, timeout=30)

                if check_result.returncode == 0 and check_result.stdout.strip() == "true":
                    self.print_colored(Colors.CYAN, f" Node {node_name} already protected")
                    protected_nodes += 1
                    continue

                # Add the annotation to prevent scale-down
                annotate_cmd = [
                    'kubectl', 'annotate', 'node', node_name,
                    'cluster-autoscaler.kubernetes.io/scale-down-disabled=true',
                    '--overwrite'
                ]

                annotate_result = subprocess.run(annotate_cmd, env=env, capture_output=True, text=True, timeout=30)
                count = count +1

                if annotate_result.returncode == 0:
                    self.print_colored(Colors.GREEN, f"Protected node {node_name} from autoscaler scale-down")
                    protected_nodes += 1
                else:
                    self.print_colored(Colors.RED, f"Failed to protect node {node_name}: {annotate_result.stderr}")

            if protected_nodes > 0:
                self.print_colored(Colors.GREEN,
                                   f"Protected {protected_nodes} nodes with NO_DELETE label from autoscaler scale-down")
                self.log_operation('INFO', f"Protected {protected_nodes} nodes from autoscaler scale-down")
            else:
                self.print_colored(Colors.YELLOW, f"No nodes were protected")

            return protected_nodes > 0

        except Exception as e:
            self.log_operation('ERROR', f"Failed to protect nodes: {str(e)}")
            self.print_colored(Colors.RED, f"Node protection failed: {str(e)}")
            return False

    def generate_cost_alarm_summary_report(self, cluster_name: str) -> str:
            """Generate a detailed cost alarm summary report"""
            if not hasattr(self, 'cost_alarm_details') or cluster_name not in self.cost_alarm_details:
                return "No cost alarm details available"
    
            details = self.cost_alarm_details[cluster_name]
    
            report = f"""
        💰 Cost Monitoring Summary for {cluster_name}
        {'='*50}

        Cost Alarms:
        - Created: {details.get('cost_alarms_created', 0)}/{details.get('total_cost_alarms', 0)}
        - Success Rate: {details.get('success_rate', 0):.1f}%
        - Alarm Names: {', '.join(details.get('alarm_names', []))}

        Thresholds Configured:
        """
    
            for alarm_name, threshold in details.get('thresholds', {}).items():
                service = "EKS" if "daily-cost" in alarm_name else "EC2" if "ec2-cost" in alarm_name else "EBS" if "ebs-cost" in alarm_name else "Unknown"
                report += f"- {alarm_name}: ${threshold} ({service})\n"
    
            report += f"""
        Cost Control Status: {'✅ ACTIVE' if details.get('success_rate', 0) >= 70 else '⚠️  PARTIAL'}
        Monitoring: Daily cost tracking with multi-tier alerts
        Created By: {self.current_user} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
        """
    
            return report

    def generate_health_check_report(self, cluster_name: str) -> str:
            """Generate a detailed health check summary report"""
            if not hasattr(self, 'health_check_results') or cluster_name not in getattr(self, 'health_check_results', {}):
                # Try to get from cluster_info if available
                return "Health check report will be available after cluster creation"
    
            health_check = self.health_check_results.get(cluster_name, {})
            health_score = health_check.get('summary', {}).get('health_score', 95)
            timestamp = health_check.get('check_timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
            report = f"""
        🏥 Health Check Report for {cluster_name}
        {'='*50}

        Timestamp: {timestamp} UTC
        Checked By: {self.current_user}

        Status Overview:
        - Overall Health: {'HEALTHY ✅' if health_check.get('overall_healthy', True) else 'NEEDS ATTENTION ⚠️'}
        - Components Checked: Cluster, NodeGroups, Add-ons, Nodes, Pods
        - Health Score: {health_score}/100

        Recommendations:
        - Monitor cost alarms regularly
        - Review scheduled scaling effectiveness
        - Keep add-ons updated to latest versions
        """
    
            return report

    def generate_alarm_summary_report(self, cluster_name: str) -> str:
        """Generate a detailed alarm summary report"""
        if not hasattr(self, 'alarm_details') or cluster_name not in self.alarm_details:
            return "No alarm details available"
    
        details = self.alarm_details[cluster_name]
    
        report = f"""
    📊 CloudWatch Alarms Summary for {cluster_name}
    {'='*50}

    Basic Alarms:
    - Created: {details.get('basic_alarms_created', 0)}/{details.get('total_basic_alarms', 0)}
    - Success Rate: {details.get('basic_alarm_success_rate', 0):.1f}%
    - Alarm Names: {', '.join(details.get('alarm_names', []))}

    Composite Alarms:
    - Created: {details.get('composite_alarms_created', 0)}/{details.get('total_composite_alarms', 0)}
    - Success Rate: {details.get('composite_success_rate', 0):.1f}%
    - Alarm Names: {', '.join(details.get('composite_alarm_names', []))}

    Overall Status: {'✅ SUCCESS' if details.get('overall_success') else '⚠️  PARTIAL/FAILED'}
    """
    
        return report

    def get_cloudwatch_agent_config(self, cluster_name: str, region: str) -> dict:
        """Generate CloudWatch agent configuration"""
        return {
            "agent": {
                "metrics_collection_interval": 60,
                "run_as_user": "cwagent"
            },
            "logs": {
                "logs_collected": {
                    "files": {
                        "collect_list": [
                            {
                                "file_path": "/var/log/messages",
                                "log_group_name": f"/aws/eks/{cluster_name}/system",
                                "log_stream_name": "{instance_id}/messages"
                            },
                            {
                                "file_path": "/var/log/dmesg",
                                "log_group_name": f"/aws/eks/{cluster_name}/system",
                                "log_stream_name": "{instance_id}/dmesg"
                            }
                        ]
                    },
                    "kubernetes": {
                        "cluster_name": cluster_name,
                        "metrics_collection_interval": 60
                    }
                }
            },
            "metrics": {
                "namespace": "CWAgent",
                "metrics_collected": {
                    "cpu": {
                        "measurement": [
                            "cpu_usage_idle",
                            "cpu_usage_iowait",
                            "cpu_usage_user",
                            "cpu_usage_system"
                        ],
                        "metrics_collection_interval": 60,
                        "totalcpu": False
                    },
                    "disk": {
                        "measurement": [
                            "used_percent"
                        ],
                        "metrics_collection_interval": 60,
                        "resources": [
                            "*"
                        ]
                    },
                    "diskio": {
                        "measurement": [
                            "io_time"
                        ],
                        "metrics_collection_interval": 60,
                        "resources": [
                            "*"
                        ]
                    },
                    "mem": {
                        "measurement": [
                            "mem_used_percent"
                        ],
                        "metrics_collection_interval": 60
                    },
                    "netstat": {
                        "measurement": [
                            "tcp_established",
                            "tcp_time_wait"
                        ],
                        "metrics_collection_interval": 60
                    },
                    "swap": {
                        "measurement": [
                            "swap_used_percent"
                        ],
                        "metrics_collection_interval": 60
                    }
                }
            }
        }

    def display_cost_estimation(self, instance_type: str, capacity_type: str, node_count: int = 1):
        """Display estimated cost information"""
        # This is a simplified estimation - you'd want to use actual AWS pricing API
        base_costs = {
            't3.micro': 0.0104,
            't3.small': 0.0208,
            't3.medium': 0.0416,
            'c6a.large': 0.0864,
            'c6a.xlarge': 0.1728
        }
    
        base_cost = base_costs.get(instance_type, 0.05)  # Default fallback
    
        if capacity_type.lower() in ['spot', 'SPOT']:
            estimated_cost = base_cost * 0.3  # Spot instances are typically 70% cheaper
            savings = base_cost * 0.7
            print(f"\n💰 Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Spot: ${estimated_cost:.4f}")
            print(f"   Savings: ${savings:.4f} ({70}%)")
            print(f"   Monthly (730 hrs): ${estimated_cost * 730 * node_count:.2f}")
        else:
            print(f"\n💰 Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Monthly (730 hrs): ${base_cost * 730 * node_count:.2f}")

    def show_cluster_summary(self, cluster_configs) -> bool:
        """Show summary of selected clusters and confirm creation"""
        if not cluster_configs:
            self.print_colored(Colors.YELLOW, "No clusters configured!")
            return False
    
        print(f"\n🚀 EKS Cluster Creation Summary")
        print(f"Selected {len(cluster_configs)} clusters to create:")
    
        print("\n" + "="*100)
        for i, cluster in enumerate(cluster_configs, 1):
            user = cluster['user']
            real_user = user.get('real_user', {})
            full_name = real_user.get('full_name', user.get('username', 'Unknown'))
            instance_type = cluster.get('instance_type', 'c6a.large')
        
            print(f"{i}. Cluster: {cluster['cluster_name']}")
            print(f"   🏦 Account: {cluster['account_key']} ({cluster['account_id']})")
            print(f"   👤 User: {user.get('username', 'unknown')} ({full_name})")
            print(f"   🌍 Region: {user.get('region', 'unknown')}")
            print(f"   💻 Instance Type: {instance_type}")
            print(f"   📊 Default Nodes: 1")
            print(f"   🔢 Max Nodes: {cluster['max_nodes']}")
            print("-" * 100)
    
        print(f"📊 Total clusters: {len(cluster_configs)}")
        print(f"💻 Instance types: {', '.join(set(cluster.get('instance_type', 'c6a.large') for cluster in cluster_configs))}")
        print(f"📊 All clusters starting with: 1 node")
        print("=" * 100)
    
        confirm = input("\nDo you want to proceed with cluster creation? (y/N): ").lower().strip()
        return confirm in ['y', 'yes']

    def setup_cost_alarms(self, cluster_name: str, region: str, cloudwatch_client, account_id: str) -> bool:
        """Setup cost monitoring alarms with proper service names and realistic expectations"""
        try:
            self.log_operation('INFO', f"Setting up cost monitoring alarms for cluster {cluster_name}")

            cost_alarms_created = 0
            total_cost_alarms = 0

            # Fixed cost alarm configurations with correct service names
            cost_alarm_configs = [
                {
                    'name': f'{cluster_name}-ec2-cost-high',
                    'description': f'High EC2 cost for {cluster_name} nodes',
                    'threshold': 50.0,  # $50 daily
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,  # 24 hours
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'Amazon Elastic Compute Cloud - Compute'}  # Fixed service name
                    ],
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-ebs-cost-warning',
                    'description': f'EBS storage cost warning for {cluster_name}',
                    'threshold': 20.0,  # $20 daily
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'Amazon Elastic Block Store'}  # Fixed service name
                    ],
                    'severity': 'MEDIUM'
                },
                {
                    'name': f'{cluster_name}-total-cost-critical',
                    'description': f'Total AWS cost critical threshold',
                    'threshold': 100.0,  # $100 daily
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'}
                        # No ServiceName dimension = total account cost
                    ],
                    'severity': 'CRITICAL'
                }
            ]

            # Create each cost alarm
            for alarm_config in cost_alarm_configs:
                total_cost_alarms += 1
                try:
                    cloudwatch_client.put_metric_alarm(
                        AlarmName=alarm_config['name'],
                        ComparisonOperator='GreaterThanThreshold',
                        EvaluationPeriods=1,  # Only 1 period since billing updates daily
                        MetricName=alarm_config['metric_name'],
                        Namespace=alarm_config['namespace'],
                        Period=alarm_config['period'],
                        Statistic='Maximum',
                        Threshold=alarm_config['threshold'],
                        ActionsEnabled=False,  # Set to False since no actions configured
                        AlarmDescription=alarm_config['description'],
                        Dimensions=alarm_config['dimensions'],
                        Unit='None',
                        TreatMissingData='notBreaching',  # Important: Don't alarm if no data yet
                        Tags=[
                            {'Key': 'Cluster', 'Value': cluster_name},
                            {'Key': 'AlarmType', 'Value': 'Cost'},
                            {'Key': 'Severity', 'Value': alarm_config['severity']},
                            {'Key': 'CreatedBy', 'Value': self.current_user}
                        ]
                    )

                    cost_alarms_created += 1
                    self.log_operation('INFO',
                                       f"Created cost alarm: {alarm_config['name']} (${alarm_config['threshold']}, {alarm_config['severity']})")
                    self.print_colored(Colors.GREEN,
                                       f"   ✅ Cost alarm: {alarm_config['name']} (${alarm_config['threshold']})")

                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create cost alarm {alarm_config['name']}: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Failed cost alarm: {alarm_config['name']}")

            # Print important note about cost alarm delays
            if cost_alarms_created > 0:
                self.print_colored(Colors.CYAN, "   ℹ️  Note: Cost alarms may show 'Insufficient Data' for 24-48 hours")
                self.print_colored(Colors.CYAN, "      This is normal as AWS billing metrics update daily")

            success_rate = (cost_alarms_created / total_cost_alarms) * 100 if total_cost_alarms > 0 else 0
            self.log_operation('INFO',
                               f"Cost alarms setup: {cost_alarms_created}/{total_cost_alarms} created ({success_rate:.1f}%)")

            return success_rate >= 70

        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup cost alarms: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Cost alarms setup failed: {str(e)}")
            return False

    def setup_cost_alarms_v1(self, cluster_name: str, region: str, cloudwatch_client, account_id: str) -> bool:
        """Setup cost monitoring alarms for EKS cluster"""
        try:
            self.log_operation('INFO', f"Setting up cost monitoring alarms for cluster {cluster_name}")
        
            cost_alarms_created = 0
            total_cost_alarms = 0
        
            # Cost alarm configurations with different thresholds
            cost_alarm_configs = [
                {
                    'name': f'{cluster_name}-daily-cost-warning',
                    'description': f'Daily cost warning for {cluster_name} - moderate spending',
                    'threshold': 25.0,  # $25 daily warning
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,  # 24 hours
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEKS'}
                    ],
                    'severity': 'LOW'
                },
                {
                    'name': f'{cluster_name}-daily-cost-critical',
                    'description': f'Critical daily cost alert for {cluster_name} - high spending',
                    'threshold': 50.0,  # $50 daily critical
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEKS'}
                    ],
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-ec2-cost-high',
                    'description': f'High EC2 instance cost for {cluster_name} nodes',
                    'threshold': 75.0,  # $75 for EC2 instances
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEC2-Instance'}
                    ],
                    'severity': 'MEDIUM'
                },
                {
                    'name': f'{cluster_name}-ebs-cost-warning',
                    'description': f'EBS storage cost warning for {cluster_name}',
                    'threshold': 20.0,  # $20 for EBS storage
                    'metric_name': 'EstimatedCharges',
                    'namespace': 'AWS/Billing',
                    'period': 86400,
                    'dimensions': [
                        {'Name': 'Currency', 'Value': 'USD'},
                        {'Name': 'ServiceName', 'Value': 'AmazonEBS'}
                    ],
                    'severity': 'LOW'
                }
            ]
        
            # Create each cost alarm
            for alarm_config in cost_alarm_configs:
                total_cost_alarms += 1
                try:
                    cloudwatch_client.put_metric_alarm(
                        AlarmName=alarm_config['name'],
                        ComparisonOperator='GreaterThanThreshold',
                        EvaluationPeriods=1,
                        MetricName=alarm_config['metric_name'],
                        Namespace=alarm_config['namespace'],
                        Period=alarm_config['period'],
                        Statistic='Maximum',
                        Threshold=alarm_config['threshold'],
                        ActionsEnabled=True,
                        AlarmDescription=alarm_config['description'],
                        Dimensions=alarm_config['dimensions'],
                        Unit='None',
                        Tags=[
                            {
                                'Key': 'Cluster',
                                'Value': cluster_name
                            },
                            {
                                'Key': 'AlarmType',
                                'Value': 'Cost'
                            },
                            {
                                'Key': 'Severity',
                                'Value': alarm_config['severity']
                            },
                            {
                                'Key': 'CreatedBy',
                                'Value': self.current_user
                            },
                            {
                                'Key': 'CreatedOn',
                                'Value': datetime.now().strftime('%Y-%m-%d')
                            }
                        ]
                    )
                
                    cost_alarms_created += 1
                    self.log_operation('INFO', f"Created cost alarm: {alarm_config['name']} (${alarm_config['threshold']}, {alarm_config['severity']})")
                    self.print_colored(Colors.GREEN, f"   ✅ Cost alarm created: {alarm_config['name']} (${alarm_config['threshold']})")
                
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create cost alarm {alarm_config['name']}: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️  Failed to create cost alarm: {alarm_config['name']}")
        
            # Calculate success rate
            success_rate = (cost_alarms_created / total_cost_alarms) * 100 if total_cost_alarms > 0 else 0
        
            self.log_operation('INFO', f"Cost alarms setup: {cost_alarms_created}/{total_cost_alarms} created ({success_rate:.1f}%)")
            self.print_colored(Colors.GREEN, f"   📊 Cost alarms: {cost_alarms_created}/{total_cost_alarms} created ({success_rate:.1f}%)")
        
            # Store cost alarm details for reporting
            if not hasattr(self, 'cost_alarm_details'):
                self.cost_alarm_details = {}
        
            self.cost_alarm_details[cluster_name] = {
                'cost_alarms_created': cost_alarms_created,
                'total_cost_alarms': total_cost_alarms,
                'success_rate': success_rate,
                'alarm_names': [config['name'] for config in cost_alarm_configs],
                'thresholds': {config['name']: config['threshold'] for config in cost_alarm_configs}
            }
        
            return success_rate >= 70  # Consider successful if at least 70% created
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup cost alarms: {str(e)}")
            self.print_colored(Colors.RED, f"   ❌ Cost alarms setup failed: {str(e)}")
            return False

    def _get_unsupported_azs(self, region: str) -> Set[str]:
        """Load unsupported AZs from ec2-region-ami-mapping.json file"""
        try:
            # Adjust the path to your mapping file
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
        
            if not os.path.exists(mapping_file_path):
                self.log_operation('WARNING', f"Mapping file not found: {mapping_file_path}")
                return set()
        
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
        
            # Get unsupported AZs for the specified region
            unsupported_azs = set()
        
            if 'eks_unsupported_azs' in mapping_data and region in mapping_data['eks_unsupported_azs']:
                unsupported_azs = set(mapping_data['eks_unsupported_azs'][region])
                self.log_operation('DEBUG', f"Loaded {len(unsupported_azs)} unsupported AZs for {region} from mapping file")
            else:
                self.log_operation('DEBUG', f"No unsupported AZs found for region {region} in mapping file")
        
            return unsupported_azs
        
        except Exception as e:
            self.log_operation('WARNING', f"Failed to load unsupported AZs from mapping file: {str(e)}")
            return set()
    
    def _get_min_subnets_required(self) -> int:
        """Get minimum subnets required from config file"""
        try:
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
        
            if not os.path.exists(mapping_file_path):
                return 2  # Default fallback
        
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
        
            if 'eks_config' in mapping_data and 'min_subnets_required' in mapping_data['eks_config']:
                return mapping_data['eks_config']['min_subnets_required']
        
            return 2  # Default fallback
        
        except Exception:
            return 2  # Default fallback
        
    ####
    def install_essential_addons(self, eks_client, cluster_name: str, region:str, admin_access_key: str, admin_secret_key: str, account_id:str ) -> bool:
        """Install essential EKS add-ons including EFS CSI driver with proper credentials"""
        try:
            self.log_operation('INFO', f"Installing essential add-ons for cluster {cluster_name}")

            # Get the EKS version and cluster info
            try:
                cluster_info = eks_client.describe_cluster(name=cluster_name)
                eks_version = cluster_info['cluster']['version']
                cluster_arn = cluster_info['cluster']['arn']
                account_id = cluster_arn.split(':')[4]
                region = cluster_arn.split(':')[3]
            
                self.log_operation('INFO', f"Detected EKS version: {eks_version}")
            except Exception as e:
                eks_version = "1.28"
                self.log_operation('WARNING', f"Could not detect EKS version, using default {eks_version}: {str(e)}")

            # Always create a session with explicit credentials
            session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            iam_client = session.client('iam')
        
            # Attach CSI policies to NodeInstanceRole
            self.attach_csi_policies_to_node_role(iam_client, account_id)

            # Define add-ons including EFS CSI driver
            if eks_version.startswith('1.32'):
                addons = [
                    {
                        'addonName': 'vpc-cni',
                        'addonVersion': 'v1.16.2-eksbuild.1',
                        'description': 'VPC CNI for pod networking'
                    },
                    {
                        'addonName': 'coredns',
                        'addonVersion': 'v1.11.1-eksbuild.4',
                        'description': 'CoreDNS for cluster DNS'
                    },
                    {
                        'addonName': 'kube-proxy',
                        'addonVersion': 'v1.32.0-eksbuild.1',
                        'description': 'Kube-proxy for service discovery'
                    },
                    {
                        'addonName': 'aws-ebs-csi-driver',
                        'addonVersion': 'v1.28.0-eksbuild.1',
                        'description': 'EBS CSI driver for persistent volumes'
                    },
                    {
                        'addonName': 'aws-efs-csi-driver',
                        'addonVersion': 'v1.7.0-eksbuild.1',
                        'description': 'EFS CSI driver for shared persistent volumes'
                    }
                ]
            elif eks_version.startswith('1.27'):
                addons = [
                    {
                        'addonName': 'vpc-cni',
                        'addonVersion': 'v1.14.0-eksbuild.3',
                        'description': 'VPC CNI for pod networking'
                    },
                    {
                        'addonName': 'coredns',
                        'addonVersion': 'v1.10.1-eksbuild.2',
                        'description': 'CoreDNS for cluster DNS'
                    },
                    {
                        'addonName': 'kube-proxy',
                        'addonVersion': 'v1.27.4-eksbuild.2',
                        'description': 'Kube-proxy for service discovery'
                    },
                    {
                        'addonName': 'aws-ebs-csi-driver',
                        'addonVersion': 'v1.24.0-eksbuild.1',
                        'description': 'EBS CSI driver for persistent volumes'
                    },
                    {
                        'addonName': 'aws-efs-csi-driver',
                        'addonVersion': 'v1.6.0-eksbuild.1',
                        'description': 'EFS CSI driver for shared persistent volumes'
                    }
                ]
            else:
                addons = [
                    {
                        'addonName': 'vpc-cni',
                        'addonVersion': 'latest',
                        'description': 'VPC CNI for pod networking'
                    },
                    {
                        'addonName': 'coredns',
                        'addonVersion': 'latest',
                        'description': 'CoreDNS for cluster DNS'
                    },
                    {
                        'addonName': 'kube-proxy',
                        'addonVersion': 'latest',
                        'description': 'Kube-proxy for service discovery'
                    },
                    {
                        'addonName': 'aws-ebs-csi-driver',
                        'addonVersion': 'latest',
                        'description': 'EBS CSI driver for persistent volumes'
                    },
                    {
                        'addonName': 'aws-efs-csi-driver',
                        'addonVersion': 'latest',
                        'description': 'EFS CSI driver for shared persistent volumes'
                    }
                ]

            successful_addons = []
            failed_addons = []

            for addon in addons:
                try:
                    self.print_colored(Colors.CYAN, f"   📦 Installing {addon['addonName']} ({addon['description']})...")
                
                    # Build creation parameters
                    create_params = {
                        'clusterName': cluster_name,
                        'addonName': addon['addonName'],
                        'resolveConflicts': 'OVERWRITE'
                    }
                
                    # Add version if specific version is provided
                    if addon['addonVersion'] != 'latest':
                        create_params['addonVersion'] = addon['addonVersion']
                
                    # Create the add-on
                    eks_client.create_addon(**create_params)
                
                    # Wait for addon to be active
                    waiter = eks_client.get_waiter('addon_active')
                    try:
                        waiter.wait(
                            clusterName=cluster_name,
                            addonName=addon['addonName'],
                            WaiterConfig={'Delay': 15, 'MaxAttempts': 20}
                        )
                
                        successful_addons.append(addon['addonName'])
                        self.print_colored(Colors.GREEN, f"   ✅ {addon['addonName']} installed successfully")
                        self.log_operation('INFO', f"Add-on {addon['addonName']} installed successfully for {cluster_name}")
                    except Exception as waiter_error:
                        # Check addon status
                        try:
                            addon_info = eks_client.describe_addon(
                                clusterName=cluster_name, 
                                addonName=addon['addonName']
                            )
                    
                            status = addon_info['addon']['status']
                            if status in ['DEGRADED', 'UPDATE_FAILED'] and 'csi-driver' in addon['addonName']:
                                self.print_colored(Colors.YELLOW, f"   ⚠️ {addon['addonName']} installed but status is {status} (may work normally)")
                                self.log_operation('WARNING', f"Add-on {addon['addonName']} installed with status {status}")
                                successful_addons.append(addon['addonName'])
                            else:
                                failed_addons.append(addon['addonName'])
                                self.print_colored(Colors.YELLOW, f"   ⚠️ {addon['addonName']} installation completed but status is {status}")
                                self.log_operation('WARNING', f"Add-on {addon['addonName']} status: {status}")
                        except Exception as describe_error:
                            failed_addons.append(addon['addonName'])
                            self.log_operation('WARNING', f"Failed to verify {addon['addonName']} status: {str(describe_error)}")
                            self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to verify {addon['addonName']} status: {str(describe_error)}")
                
                except Exception as e:
                    failed_addons.append(addon['addonName'])
                    self.log_operation('WARNING', f"Failed to install {addon['addonName']}: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to install {addon['addonName']}: {str(e)}")

            self.print_colored(Colors.GREEN, f"✅ Add-ons installation completed: {len(successful_addons)} successful, {len(failed_addons)} failed")
            self.log_operation('INFO', f"Add-ons installation completed for {cluster_name}: {successful_addons}")

            return len(successful_addons) > 0

        except Exception as e:
            self.log_operation('ERROR', f"Failed to install add-ons for {cluster_name}: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Add-ons installation failed: {str(e)}")

            return False
    def attach_csi_policies_to_node_role(self, iam_client, account_id: str) -> bool:
        """Attach all required CSI policies including custom aws_csi_policy.json to NodeInstanceRole"""
        try:
            node_role_name = "NodeInstanceRole"
        
            # Step 1: Create and attach custom CSI policy from aws_csi_policy.json
           # custom_policy_attached = self.create_and_attach_custom_csi_policy(iam_client, account_id, node_role_name)
            custom_policy_attached = False
            # Step 2: Attach AWS managed policies
            aws_managed_policies = [
                "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy",
                "arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy",
                "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"  # For VPC CNI
            ]
        
            managed_policies_attached = 0
            for policy_arn in aws_managed_policies:
                try:
                    iam_client.attach_role_policy(
                        RoleName=node_role_name,
                        PolicyArn=policy_arn
                    )
                    policy_name = policy_arn.split('/')[-1]
                    self.log_operation('INFO', f"Attached AWS managed policy {policy_name} to {node_role_name}")
                    self.print_colored(Colors.GREEN, f"   ✅ Attached {policy_name} to NodeInstanceRole")
                    managed_policies_attached += 1
                
                except Exception as e:
                    # Check if policy is already attached
                    if "attached" in str(e).lower() or "already" in str(e).lower():
                        policy_name = policy_arn.split('/')[-1]
                        self.log_operation('INFO', f"AWS managed policy {policy_name} already attached to {node_role_name}")
                        self.print_colored(Colors.CYAN, f"   ℹ️  {policy_name} already attached to NodeInstanceRole")
                        managed_policies_attached += 1
                    else:
                        policy_name = policy_arn.split('/')[-1]
                        self.log_operation('WARNING', f"Failed to attach {policy_name}: {str(e)}")
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to attach {policy_name}: {str(e)}")
        
            # Summary
            total_policies = len(aws_managed_policies) + (1 if custom_policy_attached else 0)
            attached_policies = managed_policies_attached + (1 if custom_policy_attached else 0)
        
            self.print_colored(Colors.GREEN, f"   📊 Policy attachment summary: {attached_policies}/{total_policies} policies attached")
            self.log_operation('INFO', f"CSI policies attachment completed: {attached_policies}/{total_policies} successful")
        
            return attached_policies > 0
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to attach CSI policies: {str(e)}")
            return False

    def create_and_attach_custom_csi_policy(self, iam_client, account_id: str, node_role_name: str) -> bool:
        """Create custom CSI policy from aws_csi_policy.json and attach to NodeInstanceRole"""
        try:
            custom_policy_name = "CustomAWSCSIDriverPolicy"
            custom_policy_arn = f"arn:aws:iam::{account_id}:policy/{custom_policy_name}"
        
            # Step 1: Load custom policy from aws_csi_policy.json
            policy_document = self.load_custom_csi_policy()
            if not policy_document:
                return False
        
            # Step 2: Check if custom policy already exists
            try:
                iam_client.get_policy(PolicyArn=custom_policy_arn)
                self.log_operation('INFO', f"Custom CSI policy {custom_policy_name} already exists")
                self.print_colored(Colors.CYAN, f"   ℹ️  Custom CSI policy {custom_policy_name} already exists")
            
            except iam_client.exceptions.NoSuchEntityException:
                # Step 3: Create the custom policy if it doesn't exist
                self.log_operation('INFO', f"Creating custom CSI policy {custom_policy_name}")
                self.print_colored(Colors.CYAN, f"   🔧 Creating custom CSI policy {custom_policy_name}")
            
                try:
                    policy_response = iam_client.create_policy(
                        PolicyName=custom_policy_name,
                        PolicyDocument=policy_document,
                        Description="Custom AWS CSI Driver Policy from aws_csi_policy.json"
                    )
                    custom_policy_arn = policy_response['Policy']['Arn']
                    self.log_operation('INFO', f"Created custom CSI policy: {custom_policy_arn}")
                    self.print_colored(Colors.GREEN, f"   ✅ Created custom CSI policy: {custom_policy_name}")
                
                    # Wait for policy to be available
                    time.sleep(5)
                
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create custom CSI policy: {str(e)}")
                    self.print_colored(Colors.RED, f"   ❌ Failed to create custom CSI policy: {str(e)}")
                    return False
        
            # Step 4: Attach the custom policy to NodeInstanceRole
            try:
                iam_client.attach_role_policy(
                    RoleName=node_role_name,
                    PolicyArn=custom_policy_arn
                )
                self.log_operation('INFO', f"Attached custom CSI policy {custom_policy_name} to {node_role_name}")
                self.print_colored(Colors.GREEN, f"   ✅ Attached custom CSI policy {custom_policy_name} to NodeInstanceRole")
                return True
            
            except Exception as e:
                # Check if policy is already attached
                if "attached" in str(e).lower() or "already" in str(e).lower():
                    self.log_operation('INFO', f"Custom CSI policy {custom_policy_name} already attached to {node_role_name}")
                    self.print_colored(Colors.CYAN, f"   ℹ️  Custom CSI policy {custom_policy_name} already attached to NodeInstanceRole")
                    return True
                else:
                    self.log_operation('ERROR', f"Failed to attach custom CSI policy to {node_role_name}: {str(e)}")
                    self.print_colored(Colors.RED, f"   ❌ Failed to attach custom CSI policy: {str(e)}")
                    return False
                
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create and attach custom CSI policy: {str(e)}")
            self.print_colored(Colors.RED, f"   ❌ Custom CSI policy setup failed: {str(e)}")
            return False

    def load_custom_csi_policy(self) -> str:
        """Load custom CSI policy from aws_csi_policy.json file"""
        try:
            policy_file = 'aws_csi_policy.json'
        
            # Check if file exists
            if not os.path.exists(policy_file):
                self.log_operation('ERROR', f"Custom CSI policy file not found: {policy_file}")
                self.print_colored(Colors.RED, f"   ❌ Custom CSI policy file not found: {policy_file}")
                return None
        
            # Load and validate JSON
            with open(policy_file, 'r') as f:
                policy_content = f.read().strip()
            
            # Validate JSON format
            try:
                json.loads(policy_content)  # Validate JSON syntax
            except json.JSONDecodeError as e:
                self.log_operation('ERROR', f"Invalid JSON in {policy_file}: {str(e)}")
                self.print_colored(Colors.RED, f"   ❌ Invalid JSON in {policy_file}: {str(e)}")
                return None
        
            self.log_operation('INFO', f"Successfully loaded custom CSI policy from {policy_file}")
            self.print_colored(Colors.GREEN, f"   ✅ Loaded custom CSI policy from {policy_file}")
        
            return policy_content
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load custom CSI policy from {policy_file}: {str(e)}")
            self.print_colored(Colors.RED, f"   ❌ Failed to load custom CSI policy: {str(e)}")
            return None
####
    def verify_user_access(self, cluster_name: str, region: str, username: str, access_key: str,
                           secret_key: str) -> bool:
        """Verify user access to the cluster and check cluster endpoint configuration"""
        try:
            # Colorful output for just this method
            BLUE = '\033[94m'
            GREEN = '\033[92m'
            RED = '\033[91m'
            YELLOW = '\033[93m'
            CYAN = '\033[96m'
            RESET = '\033[0m'

            print(f"{BLUE}[INFO] Verifying user access...{RESET}")
            print(f"{BLUE}[INFO] Verifying user access for {username} to cluster {cluster_name}{RESET}")
            print(f"{YELLOW}[SECURITY] Verifying user access to cluster {cluster_name}...{RESET}")

            # Create user session
            user_session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            eks_client = user_session.client('eks')

            # Step 1: Check if user can describe the cluster
            try:
                cluster_info = eks_client.describe_cluster(name=cluster_name)
                print(f"{GREEN}   [OK] User {username} can access cluster information{RESET}")
                print(f"{BLUE}[INFO] User {username} can access cluster {cluster_name}{RESET}")

                # Check cluster endpoint access configuration
                endpoint_access = cluster_info['cluster'].get('resourcesVpcConfig', {})
                endpoint_public_access = endpoint_access.get('endpointPublicAccess', False)
                endpoint_private_access = endpoint_access.get('endpointPrivateAccess', False)
                public_access_cidrs = endpoint_access.get('publicAccessCidrs', ['0.0.0.0/0'])

                print(f"{CYAN}   [STATS] Cluster Endpoint Configuration:{RESET}")
                print(f"{CYAN}      - Public Access: {'Enabled' if endpoint_public_access else 'Disabled'}{RESET}")
                print(f"{CYAN}      - Private Access: {'Enabled' if endpoint_private_access else 'Disabled'}{RESET}")
                print(f"{CYAN}      - Public Access CIDRs: {', '.join(public_access_cidrs)}{RESET}")

                # Log endpoint configuration
                print(
                    f"{BLUE}[INFO] Cluster endpoint config - Public: {endpoint_public_access}, Private: {endpoint_private_access}{RESET}")

            except Exception as e:
                print(f"{RED}   [ERROR] User {username} cannot access cluster information: {str(e)}{RESET}")
                return False

            # Step 2: Update kubeconfig and test kubectl access
            import subprocess
            import shutil

            kubectl_available = shutil.which('kubectl') is not None

            if kubectl_available:
                print(f"{CYAN}   🧪 Testing kubectl access...{RESET}")

                # Set environment variables for user access
                my_env = os.environ.copy()
                my_env['AWS_ACCESS_KEY_ID'] = access_key
                my_env['AWS_SECRET_ACCESS_KEY'] = secret_key
                my_env['AWS_DEFAULT_REGION'] = region

                # Update kubeconfig for user
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]

                update_result = subprocess.run(update_cmd, env=my_env, capture_output=True, text=True, timeout=120)

                if update_result.returncode != 0:
                    print(f"{RED}   [ERROR] Failed to update kubeconfig: {update_result.stderr}{RESET}")
                    return False

                # Test kubectl access - get nodes
                print(f"{CYAN}   🧪 Testing kubectl get nodes...{RESET}")
                nodes_cmd = ['kubectl', 'get', 'nodes']
                nodes_result = subprocess.run(nodes_cmd, env=my_env, capture_output=True, text=True, timeout=60)

                if nodes_result.returncode == 0:
                    node_count = len([line for line in nodes_result.stdout.strip().split('\n') if line.strip()]) - 1
                    print(f"{GREEN}   [OK] kubectl access successful - {node_count} nodes found{RESET}")
                    print(f"{BLUE}[INFO] User {username} has kubectl access to cluster {cluster_name}{RESET}")
                else:
                    print(f"{RED}   [ERROR] kubectl access failed: {nodes_result.stderr}{RESET}")
                    return False

                # Test kubectl access - get pods
                print(f"{CYAN}   🧪 Testing kubectl get pods...{RESET}")
                pods_cmd = ['kubectl', 'get', 'pods', '--all-namespaces']
                pods_result = subprocess.run(pods_cmd, env=my_env, capture_output=True, text=True, timeout=60)

                if pods_result.returncode == 0:
                    pod_count = len([line for line in pods_result.stdout.strip().split('\n') if line.strip()]) - 1
                    print(f"{GREEN}   [OK] kubectl pod access successful - {pod_count} pods found{RESET}")
                    print(f"{BLUE}[INFO] User {username} can access pods in cluster {cluster_name}{RESET}")

                    # Display kubectl access command for user
                    print(f"{CYAN}📋 Kubectl access command:{RESET}")
                    print(f"{CYAN}   aws eks update-kubeconfig --region {region} --name {cluster_name}{RESET}")

                    return True
                else:
                    print(f"{RED}   [ERROR] kubectl pod access failed: {pods_result.stderr}{RESET}")
                    return False
            else:
                print(f"{YELLOW}   ⚠️ kubectl not available. Skipping kubectl access verification.{RESET}")
                # Return True since we could at least access the cluster API
                return True

        except Exception as e:
            print(f"{RED}   [ERROR] User access verification failed: {str(e)}{RESET}")
            return False

    def setup_cloudwatch_alarms(self, cluster_name: str, region: str, cloudwatch_client, nodegroup_name: str,
                                account_id: str) -> bool:
        """Setup comprehensive CloudWatch alarms for EKS cluster with proper metric validation"""
        try:
            self.log_operation('INFO', f"Setting up CloudWatch alarms for cluster {cluster_name}")

            alarms_created = 0
            total_alarms = 0

            # Step 1: Verify what metrics are actually available
            available_metrics = self._discover_available_metrics(cloudwatch_client, cluster_name, nodegroup_name)

            # Step 2: Create EC2-based alarms (these will have data)
            ec2_alarms_created = self._create_ec2_based_alarms(
                cloudwatch_client, cluster_name, nodegroup_name, available_metrics
            )
            alarms_created += ec2_alarms_created[0]
            total_alarms += ec2_alarms_created[1]

            # Step 3: Create Container Insights alarms only if metrics exist
            if available_metrics.get('container_insights', False):
                ci_alarms_created = self._create_container_insights_alarms(
                    cloudwatch_client, cluster_name, available_metrics
                )
                alarms_created += ci_alarms_created[0]
                total_alarms += ci_alarms_created[1]
            else:
                self.print_colored(Colors.YELLOW,
                                   "   ⚠️ Container Insights metrics not available, skipping related alarms")

            # Step 4: Create composite alarms
            composite_success = self.create_composite_alarms(cloudwatch_client, cluster_name, alarms_created)

            # Calculate success rates
            basic_alarm_success_rate = (alarms_created / total_alarms) * 100 if total_alarms > 0 else 0
            overall_success = basic_alarm_success_rate >= 70 and composite_success

            self.log_operation('INFO',
                               f"CloudWatch alarms setup: {alarms_created}/{total_alarms} created ({basic_alarm_success_rate:.1f}%)")
            self.print_colored(Colors.GREEN,
                               f"   📊 CloudWatch alarms: {alarms_created}/{total_alarms} created ({basic_alarm_success_rate:.1f}%)")

            return overall_success

        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup CloudWatch alarms: {str(e)}")
            self.print_colored(Colors.RED, f"❌ CloudWatch alarms setup failed: {str(e)}")
            return False

    def setup_cloudwatch_alarms_v1(self, cluster_name: str, region: str, cloudwatch_client, nodegroup_name: str, account_id: str) -> bool:
        """Setup comprehensive CloudWatch alarms for EKS cluster"""
        try:
            self.log_operation('INFO', f"Setting up CloudWatch alarms for cluster {cluster_name}")
        
            alarms_created = 0
            total_alarms = 0
        
            # Define alarm configurations
            alarm_configs = [
                {
                    'name': f'{cluster_name}-high-cpu-utilization',
                    'description': f'High CPU utilization on {cluster_name}',
                    'metric_name': 'CPUUtilization',
                    'namespace': 'AWS/EKS',
                    'statistic': 'Average',
                    'threshold': 80.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-high-memory-utilization',
                    'description': f'High memory utilization on {cluster_name}',
                    'metric_name': 'MemoryUtilization',
                    'namespace': 'AWS/EKS',
                    'statistic': 'Average',
                    'threshold': 85.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-pod-failures',
                    'description': f'High pod failure rate on {cluster_name}',
                    'metric_name': 'pod_number_of_container_restarts',
                    'namespace': 'ContainerInsights',
                    'statistic': 'Sum',
                    'threshold': 10.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-node-not-ready',
                    'description': f'Node not ready on {cluster_name}',
                    'metric_name': 'cluster_node_running_total',
                    'namespace': 'ContainerInsights',
                    'statistic': 'Average',
                    'threshold': 1.0,
                    'comparison': 'LessThanThreshold',
                    'evaluation_periods': 3,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-disk-space-low',
                    'description': f'Low disk space on {cluster_name} nodes',
                    'metric_name': 'DiskSpaceUtilization',
                    'namespace': 'CWAgent',
                    'statistic': 'Average',
                    'threshold': 85.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [
                        {'Name': 'ClusterName', 'Value': cluster_name},
                        {'Name': 'NodegroupName', 'Value': nodegroup_name}
                    ]
                },
                {
                    'name': f'{cluster_name}-network-errors',
                    'description': f'High network errors on {cluster_name}',
                    'metric_name': 'NetworkPacketsIn',
                    'namespace': 'AWS/EC2',
                    'statistic': 'Sum',
                    'threshold': 1000.0,
                    'comparison': 'GreaterThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                },
                {
                    'name': f'{cluster_name}-service-unhealthy',
                    'description': f'Service unhealthy on {cluster_name}',
                    'metric_name': 'service_number_of_running_pods',
                    'namespace': 'ContainerInsights',
                    'statistic': 'Average',
                    'threshold': 1.0,
                    'comparison': 'LessThanThreshold',
                    'evaluation_periods': 2,
                    'period': 300,
                    'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
                }
            ]
        
            # Create each alarm
            for alarm_config in alarm_configs:
                total_alarms += 1
                try:
                    cloudwatch_client.put_metric_alarm(
                        AlarmName=alarm_config['name'],
                        ComparisonOperator=alarm_config['comparison'],
                        EvaluationPeriods=alarm_config['evaluation_periods'],
                        MetricName=alarm_config['metric_name'],
                        Namespace=alarm_config['namespace'],
                        Period=alarm_config['period'],
                        Statistic=alarm_config['statistic'],
                        Threshold=alarm_config['threshold'],
                        ActionsEnabled=True,
                        AlarmDescription=alarm_config['description'],
                        Dimensions=alarm_config['dimensions'],
                        Unit='Percent' if 'utilization' in alarm_config['metric_name'].lower() else 'Count'
                    )
                
                    alarms_created += 1
                    self.log_operation('INFO', f"Created alarm: {alarm_config['name']}")
                
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create alarm {alarm_config['name']}: {str(e)}")
        
            # Create composite alarms for critical conditions
            composite_alarms_success = self.create_composite_alarms(cloudwatch_client, cluster_name, alarm_configs)
        
            # Calculate success rates
            basic_alarm_success_rate = (alarms_created / total_alarms) * 100 if total_alarms > 0 else 0
            overall_success = basic_alarm_success_rate >= 70 and composite_alarms_success
        
            # Log comprehensive results
            self.log_operation('INFO', f"CloudWatch alarms setup summary:")
            self.log_operation('INFO', f"  - Basic alarms: {alarms_created}/{total_alarms} created ({basic_alarm_success_rate:.1f}%)")
            self.log_operation('INFO', f"  - Composite alarms: {'Success' if composite_alarms_success else 'Failed'}")
            self.log_operation('INFO', f"  - Overall status: {'Success' if overall_success else 'Partial/Failed'}")
        
            # Store detailed alarm information for later use
            if not hasattr(self, 'alarm_details'):
                self.alarm_details = {}
        
            self.alarm_details[cluster_name] = {
                'basic_alarms_created': alarms_created,
                'total_basic_alarms': total_alarms,
                'basic_alarm_success_rate': basic_alarm_success_rate,
                'composite_alarms_success': composite_alarms_success,
                'overall_success': overall_success,
                'alarm_names': [config['name'] for config in alarm_configs if alarms_created > 0]
            }
        
            return overall_success
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to setup CloudWatch alarms: {str(e)}")
            return False

    def _create_container_insights_alarms(self, cloudwatch_client, cluster_name: str, available_metrics: dict) -> tuple:
        """Create Container Insights alarms only if the metrics actually exist"""
        created = 0
        total = 0

        if not available_metrics.get('container_insights'):
            return (0, 0)

        # Container Insights alarm configurations
        ci_alarm_configs = [
            {
                'name': f'{cluster_name}-node-not-ready',
                'description': f'Node not ready in {cluster_name}',
                'metric_name': 'cluster_node_running_total',
                'namespace': 'ContainerInsights',
                'statistic': 'Average',
                'threshold': 1.0,
                'comparison': 'LessThanThreshold',
                'evaluation_periods': 3,
                'period': 300,
                'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
            },
            {
                'name': f'{cluster_name}-pod-failures',
                'description': f'High pod restart rate in {cluster_name}',
                'metric_name': 'pod_number_of_container_restarts',
                'namespace': 'ContainerInsights',
                'statistic': 'Sum',
                'threshold': 10.0,
                'comparison': 'GreaterThanThreshold',
                'evaluation_periods': 2,
                'period': 300,
                'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
            },
            {
                'name': f'{cluster_name}-service-unhealthy',
                'description': f'Service unhealthy in {cluster_name}',
                'metric_name': 'service_number_of_running_pods',
                'namespace': 'ContainerInsights',
                'statistic': 'Average',
                'threshold': 1.0,
                'comparison': 'LessThanThreshold',
                'evaluation_periods': 2,
                'period': 300,
                'dimensions': [{'Name': 'ClusterName', 'Value': cluster_name}]
            }
        ]

        # Create each Container Insights alarm
        for alarm_config in ci_alarm_configs:
            total += 1
            try:
                # First verify the specific metric exists
                if self._verify_metric_exists(cloudwatch_client, alarm_config['namespace'],
                                              alarm_config['metric_name'], alarm_config['dimensions']):

                    cloudwatch_client.put_metric_alarm(
                        AlarmName=alarm_config['name'],
                        ComparisonOperator=alarm_config['comparison'],
                        EvaluationPeriods=alarm_config['evaluation_periods'],
                        MetricName=alarm_config['metric_name'],
                        Namespace=alarm_config['namespace'],
                        Period=alarm_config['period'],
                        Statistic=alarm_config['statistic'],
                        Threshold=alarm_config['threshold'],
                        ActionsEnabled=True,
                        AlarmDescription=alarm_config['description'],
                        Dimensions=alarm_config['dimensions'],
                        Unit='Count',
                        Tags=[
                            {'Key': 'Cluster', 'Value': cluster_name},
                            {'Key': 'AlarmType', 'Value': 'ContainerInsights'},
                            {'Key': 'CreatedBy', 'Value': self.current_user}
                        ]
                    )

                    created += 1
                    self.log_operation('INFO', f"Created Container Insights alarm: {alarm_config['name']}")
                    self.print_colored(Colors.GREEN, f"   ✅ Created CI alarm: {alarm_config['name']}")
                else:
                    self.log_operation('WARNING',
                                       f"Metric {alarm_config['metric_name']} not found, skipping alarm {alarm_config['name']}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Metric not found, skipped: {alarm_config['name']}")

            except Exception as e:
                self.log_operation('ERROR',
                                   f"Failed to create Container Insights alarm {alarm_config['name']}: {str(e)}")
                self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to create CI alarm: {alarm_config['name']}")

        return (created, total)

    def _create_ec2_based_alarms(self, cloudwatch_client, cluster_name: str, nodegroup_name: str,
                                 available_metrics: dict) -> tuple:
        """Create alarms based on EC2 metrics that actually exist"""
        created = 0
        total = 0

        if not available_metrics.get('ec2') or not available_metrics.get('asg_names'):
            self.log_operation('WARNING', f"No EC2 metrics available for cluster {cluster_name}")
            return (0, 0)

        # Use the first ASG name found (or you could create alarms for all ASGs)
        asg_name = available_metrics['asg_names'][0]

        # Define EC2-based alarm configurations that will actually have data
        ec2_alarm_configs = [
            {
                'name': f'{cluster_name}-high-cpu-utilization',
                'description': f'High CPU utilization on nodes in {cluster_name}',
                'metric_name': 'CPUUtilization',
                'namespace': 'AWS/EC2',
                'statistic': 'Average',
                'threshold': 80.0,
                'comparison': 'GreaterThanThreshold',
                'evaluation_periods': 2,
                'period': 300,
                'dimensions': [{'Name': 'AutoScalingGroupName', 'Value': asg_name}]
            },
            {
                'name': f'{cluster_name}-high-network-in',
                'description': f'High network input on nodes in {cluster_name}',
                'metric_name': 'NetworkIn',
                'namespace': 'AWS/EC2',
                'statistic': 'Average',
                'threshold': 100000000,  # 100MB in bytes
                'comparison': 'GreaterThanThreshold',
                'evaluation_periods': 2,
                'period': 300,
                'dimensions': [{'Name': 'AutoScalingGroupName', 'Value': asg_name}]
            },
            {
                'name': f'{cluster_name}-high-network-out',
                'description': f'High network output on nodes in {cluster_name}',
                'metric_name': 'NetworkOut',
                'namespace': 'AWS/EC2',
                'statistic': 'Average',
                'threshold': 100000000,  # 100MB in bytes
                'comparison': 'GreaterThanThreshold',
                'evaluation_periods': 2,
                'period': 300,
                'dimensions': [{'Name': 'AutoScalingGroupName', 'Value': asg_name}]
            }
        ]

        # Create Auto Scaling Group specific alarms
        asg_alarm_configs = [
            {
                'name': f'{cluster_name}-low-instance-count',
                'description': f'Low instance count in ASG for {cluster_name}',
                'metric_name': 'GroupTotalInstances',
                'namespace': 'AWS/AutoScaling',
                'statistic': 'Average',
                'threshold': 1.0,
                'comparison': 'LessThanThreshold',
                'evaluation_periods': 2,
                'period': 300,
                'dimensions': [{'Name': 'AutoScalingGroupName', 'Value': asg_name}]
            },
            {
                'name': f'{cluster_name}-unhealthy-instances',
                'description': f'Unhealthy instances in ASG for {cluster_name}',
                'metric_name': 'GroupTotalInstances',
                'namespace': 'AWS/AutoScaling',
                'statistic': 'Average',
                'threshold': 0.0,
                'comparison': 'GreaterThanThreshold',
                'evaluation_periods': 1,
                'period': 300,
                'dimensions': [{'Name': 'AutoScalingGroupName', 'Value': asg_name}]
            }
        ]

        # Combine all EC2-based alarms
        all_ec2_alarms = ec2_alarm_configs + asg_alarm_configs

        # Create each alarm
        for alarm_config in all_ec2_alarms:
            total += 1
            try:
                cloudwatch_client.put_metric_alarm(
                    AlarmName=alarm_config['name'],
                    ComparisonOperator=alarm_config['comparison'],
                    EvaluationPeriods=alarm_config['evaluation_periods'],
                    MetricName=alarm_config['metric_name'],
                    Namespace=alarm_config['namespace'],
                    Period=alarm_config['period'],
                    Statistic=alarm_config['statistic'],
                    Threshold=alarm_config['threshold'],
                    ActionsEnabled=True,
                    AlarmDescription=alarm_config['description'],
                    Dimensions=alarm_config['dimensions'],
                    Unit='Percent' if 'utilization' in alarm_config['metric_name'].lower() else 'Count',
                    Tags=[
                        {'Key': 'Cluster', 'Value': cluster_name},
                        {'Key': 'AlarmType', 'Value': 'EC2'},
                        {'Key': 'CreatedBy', 'Value': self.current_user}
                    ]
                )

                created += 1
                self.log_operation('INFO', f"Created EC2 alarm: {alarm_config['name']}")
                self.print_colored(Colors.GREEN, f"   ✅ Created alarm: {alarm_config['name']}")

            except Exception as e:
                self.log_operation('ERROR', f"Failed to create EC2 alarm {alarm_config['name']}: {str(e)}")
                self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to create alarm: {alarm_config['name']}")

        return (created, total)

    def _discover_available_metrics(self, cloudwatch_client, cluster_name: str, nodegroup_name: str) -> dict:
        """Discover what metrics are actually available for this cluster"""
        try:
            available_metrics = {
                'ec2': False,
                'container_insights': False,
                'cwagent': False,
                'asg_names': []
            }

            # Check for EC2 metrics by looking for Auto Scaling Groups
            try:
                ec2_metrics = cloudwatch_client.list_metrics(
                    Namespace='AWS/EC2',
                    MetricName='CPUUtilization'
                )

                # Find ASGs related to this cluster
                for metric in ec2_metrics.get('Metrics', []):
                    for dimension in metric.get('Dimensions', []):
                        if dimension['Name'] == 'AutoScalingGroupName':
                            asg_name = dimension['Value']
                            # Check if this ASG belongs to our cluster
                            if cluster_name.split('-')[-1] in asg_name or nodegroup_name in asg_name:
                                available_metrics['asg_names'].append(asg_name)
                                available_metrics['ec2'] = True

                self.log_operation('INFO',
                                   f"Found {len(available_metrics['asg_names'])} Auto Scaling Groups for cluster")

            except Exception as e:
                self.log_operation('WARNING', f"Failed to discover EC2 metrics: {str(e)}")

            # Check for Container Insights metrics
            try:
                ci_metrics = cloudwatch_client.list_metrics(
                    Namespace='ContainerInsights',
                    MetricName='cluster_node_running_total',
                    Dimensions=[
                        {'Name': 'ClusterName', 'Value': cluster_name}
                    ]
                )

                if ci_metrics.get('Metrics'):
                    available_metrics['container_insights'] = True
                    self.log_operation('INFO', f"Container Insights metrics available for cluster {cluster_name}")
                else:
                    self.log_operation('INFO', f"Container Insights metrics not available for cluster {cluster_name}")

            except Exception as e:
                self.log_operation('WARNING', f"Failed to check Container Insights metrics: {str(e)}")

            # Check for CloudWatch Agent metrics
            try:
                cwa_metrics = cloudwatch_client.list_metrics(
                    Namespace='CWAgent',
                    MetricName='cpu_usage_active'
                )

                if cwa_metrics.get('Metrics'):
                    available_metrics['cwagent'] = True
                    self.log_operation('INFO', f"CloudWatch Agent metrics available")

            except Exception as e:
                self.log_operation('WARNING', f"Failed to check CloudWatch Agent metrics: {str(e)}")

            return available_metrics

        except Exception as e:
            self.log_operation('ERROR', f"Failed to discover available metrics: {str(e)}")
            return {'ec2': False, 'container_insights': False, 'cwagent': False, 'asg_names': []}


    def _verify_metric_exists(self, cloudwatch_client, namespace: str, metric_name: str, dimensions: list) -> bool:
        """Verify a metric exists before creating alarm"""
        try:
            response = cloudwatch_client.list_metrics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions
            )

            metrics_found = len(response.get('Metrics', []))
            if metrics_found > 0:
                self.log_operation('DEBUG', f"Metric {namespace}/{metric_name} exists ({metrics_found} instances)")
                return True
            else:
                self.log_operation('DEBUG', f"Metric {namespace}/{metric_name} not found")
                return False

        except Exception as e:
            self.log_operation('WARNING', f"Failed to verify metric {namespace}/{metric_name}: {str(e)}")
            return False

    def create_composite_alarms(self, cloudwatch_client, cluster_name: str, basic_alarms_created: int) -> bool:
        """Create composite alarms only if we have basic alarms to reference"""
        try:
            if basic_alarms_created == 0:
                self.log_operation('WARNING', f"No basic alarms created, skipping composite alarms")
                return True  # Not a failure, just nothing to composite

            composite_alarms_created = 0
            total_composite_alarms = 0

            # Define composite alarm configurations - only reference alarms that likely exist
            composite_configs = [
                {
                    'name': f'{cluster_name}-infrastructure-issues',
                    'description': f'Infrastructure issues detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-high-cpu-utilization") OR ALARM("{cluster_name}-low-instance-count")',
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-performance-degradation',
                    'description': f'Performance degradation detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-high-network-in") OR ALARM("{cluster_name}-high-network-out")',
                    'severity': 'MEDIUM'
                },
                {
                    'name': f'{cluster_name}-critical-health',
                    'description': f'Critical health issues detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-unhealthy-instances") OR ALARM("{cluster_name}-low-instance-count")',
                    'severity': 'CRITICAL'
                }
            ]

            # Create composite alarms
            for composite_config in composite_configs:
                total_composite_alarms += 1
                try:
                    cloudwatch_client.put_composite_alarm(
                        AlarmName=composite_config['name'],
                        AlarmDescription=composite_config['description'],
                        AlarmRule=composite_config['rule'],
                        ActionsEnabled=False,  # Set to False since no actions configured
                        Tags=[
                            {'Key': 'Cluster', 'Value': cluster_name},
                            {'Key': 'Severity', 'Value': composite_config['severity']},
                            {'Key': 'AlarmType', 'Value': 'Composite'},
                            {'Key': 'CreatedBy', 'Value': self.current_user}
                        ]
                    )

                    composite_alarms_created += 1
                    self.log_operation('INFO', f"Created composite alarm: {composite_config['name']}")
                    self.print_colored(Colors.GREEN, f"   ✅ Composite alarm: {composite_config['name']}")

                except Exception as e:
                    # This is expected if referenced alarms don't exist
                    self.log_operation('WARNING',
                                       f"Failed to create composite alarm {composite_config['name']}: {str(e)}")
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Composite alarm skipped: {composite_config['name']}")

            success_rate = (
                                       composite_alarms_created / total_composite_alarms) * 100 if total_composite_alarms > 0 else 100
            self.log_operation('INFO',
                               f"Composite alarms: {composite_alarms_created}/{total_composite_alarms} created ({success_rate:.1f}%)")

            return success_rate >= 50  # More lenient for composite alarms

        except Exception as e:
            self.log_operation('ERROR', f"Failed to create composite alarms: {str(e)}")
            return False


    def create_composite_alarms_v1(self, cloudwatch_client, cluster_name: str, alarm_configs: list) -> bool:
        """Create composite alarms for critical conditions"""
        try:
            composite_alarms_created = 0
            total_composite_alarms = 0
        
            # Define composite alarm configurations
            composite_configs = [
                {
                    'name': f'{cluster_name}-critical-health',
                    'description': f'Critical health issues detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-high-cpu-utilization") OR ALARM("{cluster_name}-high-memory-utilization") OR ALARM("{cluster_name}-node-not-ready")',
                    'severity': 'CRITICAL'
                },
                {
                    'name': f'{cluster_name}-performance-degradation',
                    'description': f'Performance degradation detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-pod-failures") OR ALARM("{cluster_name}-service-unhealthy")',
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-resource-exhaustion',
                    'description': f'Resource exhaustion detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-disk-space-low") AND (ALARM("{cluster_name}-high-cpu-utilization") OR ALARM("{cluster_name}-high-memory-utilization"))',
                    'severity': 'HIGH'
                },
                {
                    'name': f'{cluster_name}-infrastructure-issues',
                    'description': f'Infrastructure issues detected in {cluster_name}',
                    'rule': f'ALARM("{cluster_name}-network-errors") OR ALARM("{cluster_name}-node-not-ready")',
                    'severity': 'MEDIUM'
                }
            ]
        
            # Create each composite alarm
            for composite_config in composite_configs:
                total_composite_alarms += 1
                try:
                    cloudwatch_client.put_composite_alarm(
                        AlarmName=composite_config['name'],
                        AlarmDescription=composite_config['description'],
                        AlarmRule=composite_config['rule'],
                        ActionsEnabled=True,
                        Tags=[
                            {
                                'Key': 'Cluster',
                                'Value': cluster_name
                            },
                            {
                                'Key': 'Severity',
                                'Value': composite_config['severity']
                            },
                            {
                                'Key': 'AlarmType',
                                'Value': 'Composite'
                            }
                        ]
                    )
                
                    composite_alarms_created += 1
                    self.log_operation('INFO', f"Created composite alarm: {composite_config['name']} (Severity: {composite_config['severity']})")
                
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to create composite alarm {composite_config['name']}: {str(e)}")
        
            # Log composite alarm results
            composite_success_rate = (composite_alarms_created / total_composite_alarms) * 100 if total_composite_alarms > 0 else 0
            self.log_operation('INFO', f"Composite alarms: {composite_alarms_created}/{total_composite_alarms} created ({composite_success_rate:.1f}%)")
        
            # Store composite alarm details
            if hasattr(self, 'alarm_details') and cluster_name in self.alarm_details:
                self.alarm_details[cluster_name].update({
                    'composite_alarms_created': composite_alarms_created,
                    'total_composite_alarms': total_composite_alarms,
                    'composite_success_rate': composite_success_rate,
                    'composite_alarm_names': [config['name'] for config in composite_configs]
                })
        
            # Consider successful if at least 75% of composite alarms are created
            return composite_success_rate >= 75
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create composite alarms: {str(e)}")
            return False

    def select_instance_type(self, user_name: str = None) -> str:
        """Allow user to select instance type from allowed types"""
        ec2_config = self.load_ec2_config()
        allowed_types = ec2_config.get("allowed_instance_types", ["c6a.large"])
        default_type = ec2_config.get("default_instance_type", "c6a.large")
    
        # Ensure default is in allowed types
        if default_type not in allowed_types:
            default_type = allowed_types[0] if allowed_types else "c6a.large"
    
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n💻 Instance Type Selection {user_prefix}")
        print("=" * 60)
        print("Available instance types:")
    
        for i, instance_type in enumerate(allowed_types, 1):
            is_default = " (default)" if instance_type == default_type else ""
            print(f"  {i}. {instance_type}{is_default}")
    
        print("=" * 60)
    
        while True:
            try:
                choice = input(f"Select instance type (1-{len(allowed_types)}) [default: {default_type}]: ").strip()
            
                if not choice:
                    selected_type = default_type
                    break
            
                choice_num = int(choice)
                if 1 <= choice_num <= len(allowed_types):
                    selected_type = allowed_types[choice_num - 1]
                    break
                else:
                    print(f"❌ Please enter a number between 1 and {len(allowed_types)}")
            except ValueError:
                print("❌ Please enter a valid number")
    
        print(f"✅ Selected instance type: {selected_type}")
        return selected_type

    def select_capacity_type(self, user_name: str = None) -> str:
        """Allow user to select capacity type: on-demand, spot, or mixed"""
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n🔄 Capacity Type Selection {user_prefix}")
        print("=" * 60)
        print("Available capacity types:")
        print("  1. On-Demand (reliable, consistent performance, higher cost)")
        print("  2. Spot (cheaper, but can be terminated, best for non-critical workloads)")
        print("  3. Mixed (combination of on-demand and spot for balance)")
        print("=" * 60)
    
        default_type = "spot"  # Default to spot for cost efficiency
    
        while True:
            try:
                choice = input(f"Select capacity type (1-3) [default: Spot]: ").strip().lower()
            
                if not choice:
                    selected_type = default_type
                    break
            
                if choice in ['1', 'on-demand',]:
                    selected_type = "on-demand"
                    break
                elif choice in ['2', 'spot']:
                    selected_type = "spot"
                    break
                elif choice in ['3', 'mixed']:
                    selected_type = "mixed"
                    break
                else:
                    print("❌ Please enter a valid choice (1-3)")
            except ValueError:
                print("❌ Please enter a valid choice")
    
        print(f"✅ Selected capacity type: {selected_type.upper()}")

        return selected_type

    def load_ec2_config(self) -> Dict:
        """Load EC2 configuration from JSON file"""
        config_file = "ec2-region-ami-mapping.json"
        try:
            if not os.path.exists(config_file):
                self.log_operation('WARNING', f"Config file {config_file} not found, using defaults")
                # Fallback configuration
                return {
                    "allowed_instance_types": ["t3.micro", "t2.micro", "c6a.large"],
                    "default_instance_type": "c6a.large"
                }
        
            with open(config_file, 'r') as f:
                config = json.load(f)
                self.log_operation('INFO', f"Loaded EC2 configuration from {config_file}")
                return config
        except Exception as e:
            self.log_operation('ERROR', f"Failed to load {config_file}: {str(e)}")
            # Return fallback configuration
            return {
                "allowed_instance_types": ["t3.micro", "t2.micro", "c6a.large"],
                "default_instance_type": "c6a.large"
            }

    def get_diversified_instance_types(self, primary_instance_type: str) -> List[str]:
        """Get diversified instance types for better spot availability"""
    
        # Instance type families mapping
        instance_families = {
            'c5.large': ['c5.large', 'c5a.large', 'c4.large'],
            'c5.xlarge': ['c5.xlarge', 'c5a.xlarge', 'c4.xlarge'],
            'c6a.large': ['c6a.large', 'c5.large', 'c5a.large'],
            'c6a.xlarge': ['c6a.xlarge', 'c5.xlarge', 'c5a.xlarge'],
            'm5.large': ['m5.large', 'm5a.large', 'm4.large'],
            'm5.xlarge': ['m5.xlarge', 'm5a.xlarge', 'm4.xlarge'],
            't3.medium': ['t3.medium', 't3a.medium', 't2.medium'],
            't3.large': ['t3.large', 't3a.large', 't2.large']
        }
    
        # Get diversified types or fallback to primary type
        diversified_types = instance_families.get(primary_instance_type, [primary_instance_type])
    
        self.log_operation('INFO', f"Using diversified instance types: {diversified_types}")
        return diversified_types

    def log_operation(self, level: str, message: str):
        """Basic logger for EKSClusterManager"""
        print(f"[{level}] {message}")

    def print_colored(self, color: str, message: str, indent: int = 0) -> None:
        """
        Print colored message to terminal with proper Unicode handling for Windows.

        Args:
            color: Color name (RED, GREEN, etc.)
            message: The message to print
            indent: Optional indentation level (number of 2-space indents)
        """
        if not hasattr(self, 'colors'):
            self.colors = {
                'RED': '\033[0;31m',
                'GREEN': '\033[0;32m',
                'YELLOW': '\033[1;33m',
                'BLUE': '\033[0;34m',
                'PURPLE': '\033[0;35m',
                'CYAN': '\033[0;36m',
                'WHITE': '\033[1;37m',
                'NC': '\033[0m'  # No Color
            }

        # Get color code or default to WHITE
        color_code = self.colors.get(color, self.colors['WHITE'])
        no_color = self.colors['NC']

        # Apply indentation
        prefix = "  " * indent

        # Handle potential Unicode issues on Windows
        try:
            # Replace Unicode characters that might cause issues on Windows
            safe_message = message
            # Replace common Unicode symbols with ASCII alternatives
            replacements = {
                '✅': '[OK]',
                '❌': '[X]',
                '⚠️': '[WARNING]',
                '🔍': '[INFO]',
                '📊': '[STATS]',
                '🚀': '[LAUNCH]',
                '💰': '[COST]',
                '🛠️': '[TOOLS]',
                '📈': '[GRAPH]',
                '🏥': '[HEALTH]',
                '🔄': '[SYNC]',
                '🔐': '[SECURITY]',
                '📄': '[DOC]',
                '💻': '[SYSTEM]'
            }

            for emoji, replacement in replacements.items():
                if emoji in safe_message:
                    safe_message = safe_message.replace(emoji, replacement)

            print(f"{color_code}{prefix}{safe_message}{no_color}")
        except UnicodeEncodeError:
            # Fall back to ASCII only if terminal can't handle Unicode
            ascii_message = message.encode('ascii', errors='replace').decode('ascii')
            print(f"{color_code}{prefix}{ascii_message}{no_color}")

    def debug_nodegroup_configs(self, stage: str, nodegroup_configs) -> None:
        """Debug function to print the nodegroup_configs at various points"""
        if nodegroup_configs is None:
            self.print_colored('YELLOW', f"[DEBUG {stage}] nodegroup_configs is None")
        else:
            self.print_colored('GREEN', f"[DEBUG {stage}] nodegroup_configs is set: {len(nodegroup_configs)} configs")
            for i, config in enumerate(nodegroup_configs):
                self.print_colored('CYAN', f"  Config {i+1}: {config.get('name')}, strategy: {config.get('strategy')}")
    
 ########

    def get_cloudwatch_configmap_manifest_fixed(self, config: dict, cluster_name: str, region: str) -> str:
            """Get CloudWatch ConfigMap manifest with safely quoted JSON"""
            # Create JSON string and escape it properly for YAML
            config_json = json.dumps(config, indent=2)
    
            # Create the manifest using YAML-safe approach
            manifest = {
                'apiVersion': 'v1',
                'kind': 'ConfigMap',
                'metadata': {
                    'name': 'cwagentconfig',
                    'namespace': 'amazon-cloudwatch'
                },
                'data': {
                    'cwagentconfig.json': config_json
                }
            }
    
            import yaml
            return yaml.dump(manifest, default_flow_style=False)

    def apply_kubernetes_manifest_fixed(self, cluster_name: str, region: str, access_key: str, secret_key: str, manifest: str) -> bool:
            """Apply Kubernetes manifest using kubectl with proper error handling and YAML validation"""
            try:
                import tempfile
                import subprocess
                import yaml

                # Validate YAML syntax before writing to file
                try:
                    # This will raise yaml.YAMLError if the manifest is invalid
                    yaml.safe_load_all(manifest)
                except yaml.YAMLError as e:
                    print("\n[ERROR] Invalid YAML syntax detected. Manifest will not be applied.")
                    print("[YAML ERROR]:", e)
                    print("[DEBUG] Manifest contents:\n" + "-"*60)
                    print(manifest)
                    print("-"*60)
                    return False

                # Create temporary file for manifest
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    f.write(manifest)
                    manifest_file = f.name

                # Set up kubectl context
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = access_key
                env['AWS_SECRET_ACCESS_KEY'] = secret_key
                env['AWS_DEFAULT_REGION'] = region

                try:
                    # Apply manifest
                    kubectl_cmd = ['kubectl', 'apply', '-f', manifest_file]
                    result = subprocess.run(kubectl_cmd, capture_output=True, text=True, env=env, timeout=120)

                    if result.returncode == 0:
                        self.log_operation('INFO', f"Successfully applied manifest")
                        return True
                    else:
                        self.log_operation('ERROR', f"Failed to apply manifest: {result.stderr}")
                        print(f"[ERROR] Failed to apply manifest: error parsing")
                        print(f"\n[DEBUG] manifest file failed: {manifest_file}")
                        print("[DEBUG] Manifest contents:\n" + "-"*60)
                        with open(manifest_file, 'r') as debug_f:
                            print(debug_f.read())
                        print("-"*60)
                        return False
                finally:
                    # Clean up
                    try:
                        os.unlink(manifest_file)
                    except:
                        pass

            except Exception as e:
                self.log_operation('ERROR', f"Failed to apply Kubernetes manifest: {str(e)}")

            return False
    def wait_for_daemonset_ready_fixed(self, cluster_name: str, region: str, access_key: str, secret_key: str, namespace: str, daemonset_name: str, timeout: int = 300) -> bool:
            """Wait for DaemonSet to be ready with improved error handling"""
            try:
                import subprocess
        
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = access_key
                env['AWS_SECRET_ACCESS_KEY'] = secret_key
                env['AWS_DEFAULT_REGION'] = region
    
                # Wait for DaemonSet pods to be ready
                wait_cmd = [
                    'kubectl', 'wait', '--for=condition=ready', 'pod',
                    '-l', f'name={daemonset_name}',
                    '-n', namespace,
                    f'--timeout={timeout}s'
                ]
    
                result = subprocess.run(wait_cmd, capture_output=True, text=True, env=env, timeout=timeout+30)
    
                if result.returncode == 0:
                    self.log_operation('INFO', f"DaemonSet {daemonset_name} is ready")
                    return True
                else:
                    self.log_operation('WARNING', f"DaemonSet {daemonset_name} not ready within timeout: {result.stderr}")
                    # Still return True as it might work eventually
                    return True
        
            except Exception as e:
                self.log_operation('ERROR', f"Failed to wait for DaemonSet: {str(e)}")
                return False

    def deploy_cloudwatch_agent_fixed_bk(self, cluster_name: str, region: str, access_key: str, secret_key: str, account_id: str) -> bool:
            """Deploy CloudWatch agent as DaemonSet with proper handling of existing resources"""
            try:
                self.log_operation('INFO', f"Deploying CloudWatch agent for cluster {cluster_name}")
        
                # Check if kubectl is available
                import subprocess
                import shutil
        
                kubectl_available = shutil.which('kubectl') is not None
        
                if not kubectl_available:
                    self.log_operation('WARNING', f"kubectl not found. Cannot deploy CloudWatch agent for {cluster_name}")
                    self.print_colored(Colors.YELLOW, f"⚠️  kubectl not found. CloudWatch agent deployment skipped.")
                    return False
        
                # Set environment variables for admin access
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = access_key
                env['AWS_SECRET_ACCESS_KEY'] = secret_key
                env['AWS_DEFAULT_REGION'] = region
        
                # Update kubeconfig first
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]
        
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
        
                if update_result.returncode != 0:
                    self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                    return False
        
                # Create CloudWatch agent configuration
                cloudwatch_config = self.get_cloudwatch_agent_config(cluster_name, region)
        
                # Create Kubernetes manifests
                namespace_manifest = self.get_cloudwatch_namespace_manifest_fixed()
                service_account_manifest = self.get_cloudwatch_service_account_manifest_fixed()
                configmap_manifest = self.get_cloudwatch_configmap_manifest_fixed(cloudwatch_config, cluster_name, region)
                daemonset_manifest = self.get_cloudwatch_daemonset_manifest_fixed(cluster_name, region, account_id)
        
                # Apply manifests using kubectl
                try:
                    # 1. Create namespace if it doesn't exist
                    self.apply_kubernetes_manifest_fixed(cluster_name, region, access_key, secret_key, namespace_manifest)
                    self.log_operation('INFO', f"Applied CloudWatch namespace manifest")
            
                    # 2. Apply service account
                    self.apply_kubernetes_manifest_fixed(cluster_name, region, access_key, secret_key, service_account_manifest)
                    self.log_operation('INFO', f"Applied CloudWatch service account manifest")
            
                    # 3. Apply configmap 
                    self.apply_kubernetes_manifest_fixed(cluster_name, region, access_key, secret_key, configmap_manifest)
                    self.log_operation('INFO', f"Applied CloudWatch configmap manifest")
            
                    # 4. Check for existing DaemonSet and delete it if it exists
                    delete_cmd = ['kubectl', 'delete', 'daemonset', 'cloudwatch-agent', '-n', 'amazon-cloudwatch', '--ignore-not-found']
                    subprocess.run(delete_cmd, env=env, capture_output=True, text=True, timeout=60)
                    self.log_operation('INFO', f"Removed existing CloudWatch DaemonSet if present")
            
                    # 5. Apply DaemonSet manifest
                    self.apply_kubernetes_manifest_fixed(cluster_name, region, access_key, secret_key, daemonset_manifest)
                    self.log_operation('INFO', f"Applied CloudWatch daemonset manifest")
            
                    # 6. Also apply Fluent Bit components for log collection
                    fluentbit_yaml = self.render_fluentbit_configmap(
                        cluster_name=cluster_name,
                        region_name=region,
                        http_server_toggle="On",
                        http_server_port="2020",
                        read_from_head="false",  # Use strings instead of booleans
                        read_from_tail="true"    # Use strings instead of booleans
                    )
            
                    self.apply_kubernetes_manifest_fixed(cluster_name, region, access_key, secret_key, fluentbit_yaml)
                    self.log_operation('INFO', f"Applied Fluent Bit cluster info configmap")
            
                    return True
            
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to apply CloudWatch manifests: {str(e)}")
                    return False
            
            except Exception as e:
                self.log_operation('ERROR', f"Failed to deploy CloudWatch agent: {str(e)}")
                return False
    def deploy_cloudwatch_agent_fixed(self, cluster_name: str, region: str, access_key: str, secret_key: str, account_id: str) -> bool:
            """Deploy CloudWatch agent as DaemonSet with proper handling of existing resources"""
            try:
                self.log_operation('INFO', f"Deploying CloudWatch agent for cluster {cluster_name}")
                self.print_colored(Colors.YELLOW, f"🔧 Deploying CloudWatch agent for {cluster_name}...")
    
                # Check if kubectl is available
                import subprocess
                import shutil
    
                kubectl_available = shutil.which('kubectl') is not None
    
                if not kubectl_available:
                    self.log_operation('WARNING', f"kubectl not found. Cannot deploy CloudWatch agent for {cluster_name}")
                    self.print_colored(Colors.YELLOW, f"⚠️  kubectl not found. CloudWatch agent deployment skipped.")
                    return False
    
                # Set environment variables for admin access
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = access_key
                env['AWS_SECRET_ACCESS_KEY'] = secret_key
                env['AWS_DEFAULT_REGION'] = region
    
                # Update kubeconfig first
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]
    
                self.print_colored(Colors.CYAN, "   🔄 Updating kubeconfig...")
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
    
                if update_result.returncode != 0:
                    self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                    self.print_colored(Colors.RED, f"❌ Failed to update kubeconfig: {update_result.stderr}")
                    return False
    
                # Create CloudWatch agent configuration
                cloudwatch_config = self.get_cloudwatch_agent_config(cluster_name, region)
    
                # Create Kubernetes manifests
                namespace_manifest = self.get_cloudwatch_namespace_manifest_fixed()
                service_account_manifest = self.get_cloudwatch_service_account_manifest_fixed()
                configmap_manifest = self.get_cloudwatch_configmap_manifest_fixed(cloudwatch_config, cluster_name, region)
                daemonset_manifest = self.get_cloudwatch_daemonset_manifest_fixed(cluster_name, region, account_id)
    
                # Apply manifests using kubectl with proper cleanup first
                try:
                    # 1. Create namespace if it doesn't exist
                    self.print_colored(Colors.CYAN, "   📦 Creating CloudWatch namespace...")
                    namespace_success = self.apply_kubernetes_manifest_fixed(
                        cluster_name, region, access_key, secret_key, namespace_manifest
                    )
                    if not namespace_success:
                        self.print_colored(Colors.YELLOW, "   ⚠️ Could not create namespace, but continuing...")
        
                    # 2. Apply service account
                    self.print_colored(Colors.CYAN, "   📦 Creating CloudWatch service account...")
                    self.apply_kubernetes_manifest_fixed(
                        cluster_name, region, access_key, secret_key, service_account_manifest
                    )
        
                    # 3. Apply configmap 
                    self.print_colored(Colors.CYAN, "   📦 Creating CloudWatch config map...")
                    configmap_success = self.apply_kubernetes_manifest_fixed(
                        cluster_name, region, access_key, secret_key, configmap_manifest
                    )
                    if not configmap_success:
                        self.print_colored(Colors.RED, "   ❌ Failed to create ConfigMap, cannot proceed")
                        return False
        
                    # 4. Completely remove existing DaemonSet to avoid selector conflicts
                    self.print_colored(Colors.CYAN, "   🗑️ Completely removing existing CloudWatch agent DaemonSet...")
            
                    # First check if the DaemonSet exists
                    check_cmd = ['kubectl', 'get', 'daemonset', 'cloudwatch-agent', 
                                 '-n', 'amazon-cloudwatch', '--no-headers']
                    check_result = subprocess.run(check_cmd, env=env, capture_output=True, text=True, timeout=30)
            
                    if check_result.returncode == 0 and check_result.stdout.strip():
                        # DaemonSet exists, so delete with more force
                        delete_cmd = ['kubectl', 'delete', 'daemonset', 'cloudwatch-agent', 
                                     '-n', 'amazon-cloudwatch', '--force', '--grace-period=0']
                
                        delete_result = subprocess.run(delete_cmd, env=env, capture_output=True, text=True, timeout=60)
                        self.print_colored(Colors.CYAN, f"   🗑️ Forcefully deleted existing DaemonSet")
                
                        # Wait for deletion to complete
                        import time
                        time.sleep(10)  # Increased wait time for proper deletion
                
                        # Verify deletion has completed
                        verify_cmd = ['kubectl', 'get', 'daemonset', 'cloudwatch-agent', 
                                     '-n', 'amazon-cloudwatch', '--no-headers']
                        verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=30)
                
                        if verify_result.returncode == 0 and verify_result.stdout.strip():
                            self.print_colored(Colors.YELLOW, "   ⚠️ DaemonSet still exists, waiting longer...")
                            time.sleep(10)  # Wait more if it still exists
                    else:
                        self.print_colored(Colors.CYAN, "   ✅ No existing DaemonSet found, proceeding with creation")
        
                    # 5. Apply DaemonSet manifest with retry
                    max_retries = 2
                    for attempt in range(max_retries):
                        self.print_colored(Colors.CYAN, f"   📦 Creating CloudWatch DaemonSet (attempt {attempt+1}/{max_retries})...")
                        daemonset_success = self.apply_kubernetes_manifest_fixed(
                            cluster_name, region, access_key, secret_key, daemonset_manifest
                        )
                
                        if daemonset_success:
                            self.print_colored(Colors.GREEN, "   ✅ CloudWatch agent DaemonSet deployed successfully")
                            break
                        elif attempt < max_retries - 1:
                            self.print_colored(Colors.YELLOW, f"   ⚠️ Deployment failed, retrying in 5 seconds...")
                            time.sleep(5)
                        else:
                            self.print_colored(Colors.RED, "   ❌ Failed to deploy CloudWatch agent DaemonSet after retries")
                            return False
        
                    # 6. Wait for DaemonSet to be ready
                    self.print_colored(Colors.CYAN, "   ⏳ Waiting for CloudWatch agent DaemonSet to be ready...")
                    ready_success = self.wait_for_daemonset_ready_fixed(
                        cluster_name, region, access_key, secret_key, 'amazon-cloudwatch', 'cloudwatch-agent'
                    )
        
                    if ready_success:
                        self.print_colored(Colors.GREEN, "   ✅ CloudWatch agent DaemonSet is ready")
                    else:
                        self.print_colored(Colors.YELLOW, "   ⚠️ CloudWatch agent DaemonSet readiness check timed out")
        
                    # Apply Fluent Bit for log collection
                    self.print_colored(Colors.CYAN, "   📦 Setting up Fluent Bit for log collection...")
                    fluentbit_yaml = self.render_fluentbit_configmap(
                        cluster_name=cluster_name,
                        region_name=region,
                        http_server_toggle="On",
                        http_server_port="2020",
                        read_from_head="false",  # String value, not boolean
                        read_from_tail="true"    # String value, not boolean
                    )
        
                    fluentbit_result = self.apply_kubernetes_manifest_fixed(
                        cluster_name, region, access_key, secret_key, fluentbit_yaml
                    )
        
                    if fluentbit_result:
                        self.print_colored(Colors.GREEN, "   ✅ Fluent Bit configuration applied")
                    else:
                        self.print_colored(Colors.YELLOW, "   ⚠️ Could not apply Fluent Bit configuration")
        
                    self.print_colored(Colors.GREEN, "✅ CloudWatch monitoring deployment completed")
                    return True
        
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to apply CloudWatch manifests: {str(e)}")
                    self.print_colored(Colors.RED, f"❌ Failed to apply CloudWatch manifests: {str(e)}")
                    return False
        
            except Exception as e:
                self.log_operation('ERROR', f"Failed to deploy CloudWatch agent: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Failed to deploy CloudWatch agent: {str(e)}")
                return False
    def get_cloudwatch_daemonset_manifest_fixed_chatgpt(self, cluster_name: str, region: str, account_id: str) -> str:
        """Load and prepare the cloudwatch-daemonset.yaml manifest with proper annotations"""
        # Load the template
        manifest = self.load_yaml_file("cloudwatch-daemonset.yaml")
    
        # Process the manifest to ensure the annotation is properly set
        import yaml
        try:
            # Parse YAML
            daemonset_yaml = yaml.safe_load(manifest)
        
            # Ensure annotations exist and add the required one
            if 'metadata' in daemonset_yaml:
                if 'annotations' not in daemonset_yaml['metadata']:
                    daemonset_yaml['metadata']['annotations'] = {}
                
                # Add a timestamp to make each deployment unique
                from datetime import datetime
                daemonset_yaml['metadata']['annotations']['deployment-timestamp'] = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # Convert back to YAML string with better formatting
            updated_manifest = yaml.dump(daemonset_yaml, default_flow_style=False, indent=2)
            return updated_manifest
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to process DaemonSet manifest: {str(e)}")
            # Return original manifest if processing failed
            return manifest

    ########
    def setup_scheduled_scaling_multi_nodegroup_bk(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str, nodegroup_names: List[str]) -> bool:
        """Setup scheduled scaling for multiple nodegroups using a single Lambda function with default parameters"""
        try:
            if not nodegroup_names:
                self.log_operation('WARNING', f"No nodegroups to configure scheduled scaling for")
                return False

            self.log_operation('INFO',
                               f"Setting up scheduled scaling for {len(nodegroup_names)} nodegroups: {', '.join(nodegroup_names)}")
            self.print_colored(Colors.YELLOW,
                               f"⏰ Setting up scheduled scaling for {len(nodegroup_names)} nodegroups...")

            # Create admin session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            # Create clients
            eks_client = admin_session.client('eks')
            events_client = admin_session.client('events')
            lambda_client = admin_session.client('lambda')
            iam_client = admin_session.client('iam')
            sts_client = admin_session.client('sts')
            account_id = sts_client.get_caller_identity()['Account']

            # Get current nodegroup configurations (for logging only)
            nodegroup_configs = {}
            for ng_name in nodegroup_names:
                try:
                    ng_info = eks_client.describe_nodegroup(clusterName=cluster_name, nodegroupName=ng_name)
                    scaling_config = ng_info['nodegroup'].get('scalingConfig', {})
                    nodegroup_configs[ng_name] = {
                        'current_min': scaling_config.get('minSize', 0),
                        'current_desired': scaling_config.get('desiredSize', 0),
                        'current_max': scaling_config.get('maxSize', 0)
                    }
                    self.print_colored(Colors.CYAN,
                                       f"   ℹ️  Current {ng_name} scaling: min={scaling_config.get('minSize', 0)}, desired={scaling_config.get('desiredSize', 0)}, max={scaling_config.get('maxSize', 0)}")
                except Exception as e:
                    self.log_operation('WARNING', f"Could not get current scaling config for {ng_name}: {str(e)}")
                    nodegroup_configs[ng_name] = {'current_min': 0, 'current_desired': 0, 'current_max': 0}

            # ASK USER FOR SCALING TIMES OR USE DEFAULTS
            self.print_colored(Colors.CYAN, "\n   🕒 Set scheduled scaling times (IST timezone):")
            self.print_colored(Colors.CYAN, "   Default scale-up: 11:00 AM IST (5:30 AM UTC)")
            self.print_colored(Colors.CYAN, "   Default scale-down: 9:00 PM IST (3:30 PM UTC)")
            #change_times = input("   Change default scaling times? (y/N): ").strip().lower()
            change_times = 'n'

            if change_times == 'y':
                # Get custom times from user
                scale_up_time_input = input("   Enter scale-up time (HH:MM AM/PM IST): ").strip()
                scale_down_time_input = input("   Enter scale-down time (HH:MM AM/PM IST): ").strip()

                # Convert to cron expressions (simplified - you may want to add proper parsing)
                scale_up_time = scale_up_time_input
                scale_down_time = scale_down_time_input

                # For simplicity, you'd need to add proper time parsing here
                # This is a simplified version - use defaults for now
                scale_up_cron = "30 5 * * ? *"  # 5:30 AM UTC = 11:00 AM IST
                scale_down_cron = "30 15 * * ? *"  # 3:30 PM UTC = 9:00 PM IST
            else:
                scale_up_time = "11:00 AM IST"
                scale_up_cron = "30 5 * * ? *"  # 5:30 AM UTC = 11:00 AM IST
                scale_down_time = "9:00 PM IST"
                scale_down_cron = "30 15 * * ? *"  # 3:30 PM UTC = 9:00 PM IST

            # ASK USER FOR SCALING SIZES OR USE DEFAULTS
            self.print_colored(Colors.CYAN, "\n   [SYSTEM] Set node scaling parameters:")
            self.print_colored(Colors.CYAN, "   Default scale-up: min=1, desired=1, max=3")
            self.print_colored(Colors.CYAN, "   Default scale-down: min=0, desired=0, max=3")

            change_sizes = 'n'
            #change_sizes = input("   Change default scaling sizes? (y/N): ").strip().lower()

            if change_sizes == 'y':
                # Get custom scaling sizes from user
                try:
                    print("   Scale-up configuration:")
                    scale_up_min = int(input("     Min nodes for scale-up: "))
                    scale_up_desired = int(input("     Desired nodes for scale-up: "))
                    scale_up_max = int(input("     Max nodes for scale-up: "))

                    print("   Scale-down configuration:")
                    scale_down_min = int(input("     Min nodes for scale-down: "))
                    scale_down_desired = int(input("     Desired nodes for scale-down: "))
                    scale_down_max = int(input("     Max nodes for scale-down: "))

                except ValueError:
                    self.print_colored(Colors.RED, "   ❌ Invalid input. Using default values.")
                    # Use default values
                    scale_up_min, scale_up_desired, scale_up_max = 1, 1, 3
                    scale_down_min, scale_down_desired, scale_down_max = 0, 0, 3
            else:
                # Use the values you actually want as defaults
                scale_up_min, scale_up_desired, scale_up_max = 1, 1, 3
                scale_down_min, scale_down_desired, scale_down_max = 0, 0, 3

            # Check if current nodes exceed scale-down configuration
            max_current_desired = max([config['current_desired'] for config in nodegroup_configs.values()])
            if max_current_desired > scale_down_desired:
                self.print_colored(Colors.YELLOW,
                                   f"\n   [WARNING]  Warning: Some nodegroups currently have more nodes than the scale-down size.")
                self.print_colored(Colors.YELLOW,
                                   f"      This will cause nodes to be terminated during scale-down.")
                continue_with_settings = input("   Continue with these settings? (y/N): ").strip().lower()
                if continue_with_settings != 'y':
                    self.print_colored(Colors.YELLOW, "   Operation cancelled by user.")
                    return False

            self.print_colored(Colors.CYAN, f"\n   🕒 Using scheduled scaling times (IST timezone):")
            self.print_colored(Colors.CYAN, f"      - Scale up: {scale_up_time} (cron: {scale_up_cron})")
            self.print_colored(Colors.CYAN, f"      - Scale down: {scale_down_time} (cron: {scale_down_cron})")

            self.print_colored(Colors.CYAN, f"\n   💻 Using node scaling parameters:")
            self.print_colored(Colors.CYAN,
                               f"      - Scale up: min={scale_up_min}, desired={scale_up_desired}, max={scale_up_max}")
            self.print_colored(Colors.CYAN,
                               f"      - Scale down: min={scale_down_min}, desired={scale_down_desired}, max={scale_down_max}")

            # Create IAM role for Lambda function - with shorter name
            self.print_colored(Colors.CYAN, "   [SECURITY] Creating IAM role for scheduled scaling...")

            # Use a shorter name - EKS-{cluster_suffix}-ScaleRole
            short_cluster_suffix = cluster_name.split('-')[-1]  # Just take the random suffix
            lambda_role_name = f"EKS-{short_cluster_suffix}-ScaleRole"

            lambda_trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }

            lambda_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "eks:DescribeCluster",
                            "eks:DescribeNodegroup",
                            "eks:ListNodegroups",
                            "eks:UpdateNodegroupConfig",
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents"
                        ],
                        "Resource": "*"
                    }
                ]
            }

            try:
                # Create Lambda execution role
                role_response = iam_client.create_role(
                    RoleName=lambda_role_name,
                    AssumeRolePolicyDocument=json.dumps(lambda_trust_policy),
                    Description=f"Role for scheduled scaling of EKS cluster {cluster_name}"
                )
                lambda_role_arn = role_response['Role']['Arn']

                # Create and attach policy - also with shorter name
                policy_name = f"EKS-{short_cluster_suffix}-ScalePolicy"
                policy_response = iam_client.create_policy(
                    PolicyName=policy_name,
                    PolicyDocument=json.dumps(lambda_policy),
                    Description=f"Policy for scheduled scaling of EKS cluster {cluster_name}"
                )

                iam_client.attach_role_policy(
                    RoleName=lambda_role_name,
                    PolicyArn=policy_response['Policy']['Arn']
                )

                self.log_operation('INFO', f"Created Lambda role for scheduled scaling: {lambda_role_arn}")

            except iam_client.exceptions.EntityAlreadyExistsException:
                # Role already exists
                role_response = iam_client.get_role(RoleName=lambda_role_name)
                lambda_role_arn = role_response['Role']['Arn']
                self.log_operation('INFO', f"Using existing Lambda role: {lambda_role_arn}")

            # Create a multi-nodegroup Lambda function
            self.print_colored(Colors.CYAN, "   🔧 Creating Lambda function for multi-nodegroup scaling...")

            # Load lambda code from template file if it exists, otherwise use embedded template
            try:
                template_file = os.path.join(os.path.dirname(__file__), 'lambda_eks_scaling_template.py')

                # If template file doesn't exist in same directory, try current directory
                if not os.path.exists(template_file):
                    template_file = 'lambda_eks_scaling_template.py'

                # If still not found, create it
                if not os.path.exists(template_file):
                    self.log_operation('INFO', f"Creating lambda template file: {template_file}")
                    with open(template_file, 'w') as f:
                        f.write(self._get_multi_nodegroup_lambda_template())

                # Read the template
                with open(template_file, 'r', encoding='utf-8') as f:
                    lambda_template = f.read()

                # Replace placeholders
                lambda_code = lambda_template.format(
                    region=region,
                    cluster_name=cluster_name
                )

                self.log_operation('INFO', f"Loaded Lambda template from file: {template_file}")

            except Exception as e:
                self.log_operation('WARNING',
                                   f"Failed to load lambda template file: {str(e)}. Using embedded template.")
                # Fall back to embedded template
                lambda_code = self._get_multi_nodegroup_lambda_template().format(
                    region=region,
                    cluster_name=cluster_name
                )

            function_name = f"eks-scale-{short_cluster_suffix}"

            # Create a zip file with the lambda code
            import io
            import zipfile

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr('index.py', lambda_code)

            zip_buffer.seek(0)

            try:
                # Wait for role to be available
                time.sleep(10)

                # Create Lambda function
                lambda_response = lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime='python3.9',
                    Role=lambda_role_arn,
                    Handler='index.lambda_handler',
                    Code={'ZipFile': zip_buffer.read()},
                    Description=f'Scheduled scaling for EKS cluster {cluster_name} nodegroups',
                    Timeout=60
                )

                function_arn = lambda_response['FunctionArn']
                self.log_operation('INFO', f"Created Lambda function: {function_arn}")

            except lambda_client.exceptions.ResourceConflictException:
                # Function already exists - update the code
                lambda_client.update_function_code(
                    FunctionName=function_name,
                    ZipFile=zip_buffer.read()
                )
                function_response = lambda_client.get_function(FunctionName=function_name)
                function_arn = function_response['Configuration']['FunctionArn']
                self.log_operation('INFO', f"Updated existing Lambda function: {function_arn}")

            # Create EventBridge rules for scaling
            self.print_colored(Colors.CYAN, f"   📅 Creating scheduled scaling rules (IST timezone):")
            self.print_colored(Colors.CYAN, f"      - Scale up: {scale_up_time} → {scale_up_desired} node(s)")
            self.print_colored(Colors.CYAN, f"      - Scale down: {scale_down_time} → {scale_down_desired} node(s)")

            # Scale down rule
            scale_down_rule = f"eks-down-{short_cluster_suffix}"
            events_client.put_rule(
                Name=scale_down_rule,
                ScheduleExpression=f'cron({scale_down_cron})',
                Description=f'Scale down EKS cluster {cluster_name} at {scale_down_time} (after hours)',
                State='ENABLED'
            )

            # Scale up rule
            scale_up_rule = f"eks-up-{short_cluster_suffix}"
            events_client.put_rule(
                Name=scale_up_rule,
                ScheduleExpression=f'cron({scale_up_cron})',
                Description=f'Scale up EKS cluster {cluster_name} at {scale_up_time} (business hours)',
                State='ENABLED'
            )

            # Add Lambda permissions for EventBridge
            try:
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f'allow-eventbridge-down-{short_cluster_suffix}',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f'arn:aws:events:{region}:{account_id}:rule/{scale_down_rule}'
                )

                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f'allow-eventbridge-up-{short_cluster_suffix}',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f'arn:aws:events:{region}:{account_id}:rule/{scale_up_rule}'
                )
            except lambda_client.exceptions.ResourceConflictException:
                # Permissions already exist
                pass

            # Add targets to rules with nodegroup-aware configuration
            # Scale down configuration includes all nodegroups to scale to configured size
            events_client.put_targets(
                Rule=scale_down_rule,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': function_arn,
                        'Input': json.dumps({
                            'action': 'scale_down',
                            'ist_time': scale_down_time,
                            'nodegroups': [
                                {
                                    'name': nodegroup,
                                    'desired_size': scale_down_desired,
                                    'min_size': scale_down_min,
                                    'max_size': scale_down_max
                                } for nodegroup in nodegroup_names
                            ]
                        })
                    }
                ]
            )

            # Scale up configuration includes all nodegroups to scale to configured size
            events_client.put_targets(
                Rule=scale_up_rule,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': function_arn,
                        'Input': json.dumps({
                            'action': 'scale_up',
                            'ist_time': scale_up_time,
                            'nodegroups': [
                                {
                                    'name': nodegroup,
                                    'desired_size': scale_up_desired,
                                    'min_size': scale_up_min,
                                    'max_size': scale_up_max
                                } for nodegroup in nodegroup_names
                            ]
                        })
                    }
                ]
            )

            self.print_colored(Colors.GREEN, "   [OK] Scheduled scaling configured")
            self.print_colored(Colors.CYAN,
                               f"   📅 Scale up: {scale_up_time} → {scale_up_desired} node(s) per nodegroup")
            self.print_colored(Colors.CYAN,
                               f"   📅 Scale down: {scale_down_time} → {scale_down_desired} node(s) per nodegroup")
            self.print_colored(Colors.CYAN, f"   🌏 Timezone: Indian Standard Time (UTC+5:30)")

            return True

        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to setup multi-nodegroup scheduled scaling: {error_msg}")
            self.print_colored(Colors.RED, f"❌ Scheduled scaling setup failed: {error_msg}")
            return False

    def setup_scheduled_scaling_multi_nodegroup(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str, nodegroup_names: List[str]) -> bool:
        """Setup scheduled scaling for multiple nodegroups using a single Lambda function with user-defined parameters"""
        try:
            if not nodegroup_names:
                self.log_operation('WARNING', f"No nodegroups to configure scheduled scaling for")
                return False

            self.log_operation('INFO', f"Setting up scheduled scaling for {len(nodegroup_names)} nodegroups: {', '.join(nodegroup_names)}")
            self.print_colored(Colors.YELLOW, f"⏰ Setting up scheduled scaling for {len(nodegroup_names)} nodegroups...")

            # Create admin session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )

            # Create clients
            eks_client = admin_session.client('eks')
            events_client = admin_session.client('events')
            lambda_client = admin_session.client('lambda')
            iam_client = admin_session.client('iam')
            sts_client = admin_session.client('sts')
            account_id = sts_client.get_caller_identity()['Account']

            # Get current nodegroup configurations
            nodegroup_configs = {}
            for ng_name in nodegroup_names:
                try:
                    ng_info = eks_client.describe_nodegroup(clusterName=cluster_name, nodegroupName=ng_name)
                    scaling_config = ng_info['nodegroup'].get('scalingConfig', {})
                    nodegroup_configs[ng_name] = {
                        'current_min': scaling_config.get('minSize', 0),
                        'current_desired': scaling_config.get('desiredSize', 0),
                        'current_max': scaling_config.get('maxSize', 0)
                    }
                    self.print_colored(Colors.CYAN, f"   ℹ️  Current {ng_name} scaling: min={scaling_config.get('minSize', 0)}, desired={scaling_config.get('desiredSize', 0)}, max={scaling_config.get('maxSize', 0)}")
                except Exception as e:
                    self.log_operation('WARNING', f"Could not get current scaling config for {ng_name}: {str(e)}")
                    nodegroup_configs[ng_name] = {'current_min': 0, 'current_desired': 0, 'current_max': 0}

            # Step 1: Get user input for scale up/down times
            self.print_colored(Colors.CYAN, "\n   🕒 Set scheduled scaling times (IST timezone):")
            print("   Default scale-up: 11:00 AM IST (5:30 AM UTC)")
            print("   Default scale-down: 9:00 PM IST (3:30 PM UTC)")

            change_times = False
            #change_times = input("   Change default scaling times? (y/N): ").strip().lower() in ['y', 'yes']

            if change_times:
                while True:
                    scale_up_time = input("   Enter scale-up time (format: HH:MM AM/PM IST): ").strip()
                    if not scale_up_time:
                        scale_up_time = "11:00 AM IST"
                        scale_up_cron = "30 5 * * ? *"  # 5:30 AM UTC = 11:00 AM IST (weekdays only)
                        break
        
                    try:
                        # Parse user input and convert to UTC
                        time_format = "%I:%M %p IST"
                        time_obj = datetime.strptime(scale_up_time, time_format)
                        # IST is UTC+5:30, subtract to get UTC
                        utc_hour = (time_obj.hour - 5) % 24
                        utc_minute = (time_obj.minute - 30) % 60
                        if time_obj.minute < 30:  # Handle minute underflow
                            utc_hour = (utc_hour - 1) % 24
            
                        scale_up_cron = f"{utc_minute} {utc_hour} * * ? *"
                        break
                    except ValueError:
                        self.print_colored(Colors.YELLOW, "   ⚠️  Invalid time format. Please use format like '8:30 AM IST'")
    
                while True:
                    scale_down_time = input("   Enter scale-down time (format: HH:MM AM/PM IST): ").strip()
                    if not scale_down_time:
                        scale_down_time = "9:00 PM IST"
                        scale_down_cron = "30 15 * * ? *"  # 3:30 PM UTC = 9:00 PM IST
                        break
        
                    try:
                        # Parse user input and convert to UTC
                        time_format = "%I:%M %p IST"
                        time_obj = datetime.strptime(scale_down_time, time_format)
                        # IST is UTC+5:30, subtract to get UTC
                        utc_hour = (time_obj.hour - 5) % 24
                        utc_minute = (time_obj.minute - 30) % 60
                        if time_obj.minute < 30:  # Handle minute underflow
                            utc_hour = (utc_hour - 1) % 24
            
                        scale_down_cron = f"{utc_minute} {utc_hour} * * ? *"
                        break
                    except ValueError:
                        self.print_colored(Colors.YELLOW, "   ⚠️  Invalid time format. Please use format like '6:30 PM IST'")
            else:
                # scale_up_time = "11:00 AM IST"
                # scale_up_cron = "30 5 * * ? *"  # 5:30 AM UTC = 11:00 AM IST
                # scale_down_time = "9:00 PM IST"
                # scale_down_cron = "30 15 * * ? *"  # 3:30 PM UTC = 9:00 PM IST

                scale_up_time = "11:00 AM IST"
                scale_up_cron = "30 5 * * ? *"  # 6:30 AM UTC = 11:00 AM IST
                scale_down_time = "9:00 PM IST"
                scale_down_cron = "30 15 * * ? *"  # 3:30 PM UTC = 9:00 PM IST

            # Step 2: Get user input for scaling sizes
            self.print_colored(Colors.CYAN, "\n   💻 Set node scaling parameters:")
            print("   Default scale-up: min=1, desired=1, max=3")
            print("   Default scale-down: min=0, desired=0, max=3")

            change_sizes = False
            #change_sizes = input("   Change default scaling sizes? (y/N): ").strip().lower() in ['y', 'yes']

            if change_sizes:
                try:
                    scale_up_min = int(input("   Scale-up minimum nodes (default: 1): ").strip() or "1")
                    scale_up_desired = int(input("   Scale-up desired nodes (default: 1): ").strip() or "1")
                    scale_up_max = int(input("   Scale-up maximum nodes (default: 3): ").strip() or "3")
        
                    scale_down_min = int(input("   Scale-down minimum nodes (default: 0): ").strip() or "0")
                    scale_down_desired = int(input("   Scale-down desired nodes (default: 0): ").strip() or "0")
                    scale_down_max = int(input("   Scale-down maximum nodes (default: 3): ").strip() or "3")
        
                    # Validate input
                    if scale_up_min < 0 or scale_up_desired < 0 or scale_up_max < 0 or scale_down_min < 0 or scale_down_desired < 0 or scale_down_max < 0:
                        self.print_colored(Colors.YELLOW, "   ⚠️  Negative values not allowed, using defaults.")
                        scale_up_min, scale_up_desired, scale_up_max = 1, 1, 3
                        scale_down_min, scale_down_desired, scale_down_max = 0, 0, 3
        
                    if scale_up_min > scale_up_desired or scale_up_desired > scale_up_max:
                        self.print_colored(Colors.YELLOW, "   ⚠️  Invalid scale-up values (should be min ≤ desired ≤ max), adjusting...")
                        scale_up_max = max(scale_up_max, scale_up_desired, scale_up_min)
                        scale_up_min = min(scale_up_min, scale_up_desired)
                        scale_up_desired = max(scale_up_min, min(scale_up_desired, scale_up_max))
        
                    if scale_down_min > scale_down_desired or scale_down_desired > scale_down_max:
                        self.print_colored(Colors.YELLOW, "   ⚠️  Invalid scale-down values (should be min ≤ desired ≤ max), adjusting...")
                        scale_down_max = max(scale_down_max, scale_down_desired, scale_down_min)
                        scale_down_min = min(scale_down_min, scale_down_desired)
                        scale_down_desired = max(scale_down_min, min(scale_down_desired, scale_down_max))
        
                except ValueError:
                    self.print_colored(Colors.YELLOW, "   ⚠️  Invalid number format, using defaults.")
                    scale_up_min, scale_up_desired, scale_up_max = 1, 1, 3
                    scale_down_min, scale_down_desired, scale_down_max = 0, 0, 3
            else:
                scale_up_min, scale_up_desired, scale_up_max = 1, 1, 3
                scale_down_min, scale_down_desired, scale_down_max = 0, 0, 3

            # Check if any nodegroup current size is greater than new scale down size
            size_reduction_detected = False
            for ng_name, config in nodegroup_configs.items():
                if config['current_desired'] > scale_down_desired:
                    size_reduction_detected = True
                    break

            if size_reduction_detected:
                self.print_colored(Colors.YELLOW, "\n   ⚠️  Warning: Some nodegroups currently have more nodes than the scale-down size.")
                self.print_colored(Colors.YELLOW, "      This will cause nodes to be terminated during scale-down.")
                confirm = 'yes'
                #confirm = input("   Continue with these settings? (y/N): ").strip().lower()
                if confirm not in ['y', 'yes']:
                    self.print_colored(Colors.YELLOW, "   ⚠️  Scheduled scaling setup canceled.")
                    return False

            # Step 3: Create IAM role for Lambda function - with shorter name
            self.print_colored(Colors.CYAN, "   🔐 Creating IAM role for scheduled scaling...")

            # Use a shorter name - EKS-{cluster_suffix}-ScaleRole
            short_cluster_suffix = cluster_name.split('-')[-1]  # Just take the random suffix
            lambda_role_name = f"EKS-{short_cluster_suffix}-ScaleRole"

            lambda_trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }

            lambda_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "eks:DescribeCluster",
                            "eks:DescribeNodegroup",
                            "eks:ListNodegroups",
                            "eks:UpdateNodegroupConfig",
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents"
                        ],
                        "Resource": "*"
                    }
                ]
            }

            try:
                # Create Lambda execution role
                role_response = iam_client.create_role(
                    RoleName=lambda_role_name,
                    AssumeRolePolicyDocument=json.dumps(lambda_trust_policy),
                    Description=f"Role for scheduled scaling of EKS cluster {cluster_name}"
                )
                lambda_role_arn = role_response['Role']['Arn']
    
                # Create and attach policy - also with shorter name
                policy_name = f"EKS-{short_cluster_suffix}-ScalePolicy"
                policy_response = iam_client.create_policy(
                    PolicyName=policy_name,
                    PolicyDocument=json.dumps(lambda_policy),
                    Description=f"Policy for scheduled scaling of EKS cluster {cluster_name}"
                )
    
                iam_client.attach_role_policy(
                    RoleName=lambda_role_name,
                    PolicyArn=policy_response['Policy']['Arn']
                )
    
                self.log_operation('INFO', f"Created Lambda role for scheduled scaling: {lambda_role_arn}")
    
            except iam_client.exceptions.EntityAlreadyExistsException:
                # Role already exists
                role_response = iam_client.get_role(RoleName=lambda_role_name)
                lambda_role_arn = role_response['Role']['Arn']
                self.log_operation('INFO', f"Using existing Lambda role: {lambda_role_arn}")

            # Step 4: Create a multi-nodegroup Lambda function
            self.print_colored(Colors.CYAN, "   🔧 Creating Lambda function for multi-nodegroup scaling...")

            # Load lambda code from template file if it exists, otherwise use embedded template
            try:
                template_file = os.path.join(os.path.dirname(__file__), 'lambda_eks_scaling_template.py')
    
                # If template file doesn't exist in same directory, try current directory
                if not os.path.exists(template_file):
                    template_file = 'lambda_eks_scaling_template.py'
    
                # If still not found, create it
                if not os.path.exists(template_file):
                    self.log_operation('INFO', f"Creating lambda template file: {template_file}")
                    with open(template_file, 'w', encoding='utf-8') as f:
                        f.write(self._get_multi_nodegroup_lambda_template())
    
                # Read the template
                with open(template_file, 'r', encoding='utf-8') as f:
                    lambda_template = f.read()
    
                # Replace placeholders using replace() method instead of format()
                lambda_code = lambda_template.replace('{{cluster_name}}', cluster_name).replace('{{region}}', region)
    
                self.log_operation('INFO', f"Loaded Lambda template from file: {template_file}")
    
            except Exception as e:
                self.log_operation('WARNING', f"Failed to load lambda template file: {str(e)}. Using embedded template.")
                # Fall back to embedded template using replace() method instead of format()
                lambda_code = self._get_multi_nodegroup_lambda_template().replace('{{cluster_name}}', cluster_name).replace('{{region}}', region)

            function_name = f"eks-scale-{short_cluster_suffix}"

            # Create a zip file with the lambda code
            import io
            import zipfile
            import time

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr('index.py', lambda_code)
    
            zip_buffer.seek(0)

            try:
                # Wait for role to be available
                time.sleep(10)
    
                # Create Lambda function
                lambda_response = lambda_client.create_function(
                    FunctionName=function_name,
                    Runtime='python3.9',
                    Role=lambda_role_arn,
                    Handler='index.lambda_handler',
                    Code={'ZipFile': zip_buffer.read()},
                    Description=f'Scheduled scaling for EKS cluster {cluster_name} nodegroups',
                    Timeout=60
                )
    
                function_arn = lambda_response['FunctionArn']
                self.log_operation('INFO', f"Created Lambda function: {function_arn}")
    
            except lambda_client.exceptions.ResourceConflictException:
                # Function already exists - update the code
                zip_buffer.seek(0)  # Reset buffer position
                lambda_client.update_function_code(
                    FunctionName=function_name,
                    ZipFile=zip_buffer.read()
                )
                function_response = lambda_client.get_function(FunctionName=function_name)
                function_arn = function_response['Configuration']['FunctionArn']
                self.log_operation('INFO', f"Updated existing Lambda function: {function_arn}")

            # Step 5: Create EventBridge rules for scaling
            self.print_colored(Colors.CYAN, f"   📅 Creating scheduled scaling rules (IST timezone):")
            self.print_colored(Colors.CYAN, f"      - Scale up: {scale_up_time} → {scale_up_desired} node(s)")
            self.print_colored(Colors.CYAN, f"      - Scale down: {scale_down_time} → {scale_down_desired} node(s)")

            # Scale down rule
            scale_down_rule = f"eks-down-{short_cluster_suffix}"
            events_client.put_rule(
                Name=scale_down_rule,
                ScheduleExpression=f'cron({scale_down_cron})',
                Description=f'Scale down EKS cluster {cluster_name} at {scale_down_time} (after hours)',
                State='ENABLED'
            )

            # Scale up rule
            scale_up_rule = f"eks-up-{short_cluster_suffix}"
            events_client.put_rule(
                Name=scale_up_rule,
                ScheduleExpression=f'cron({scale_up_cron})',
                Description=f'Scale up EKS cluster {cluster_name} at {scale_up_time} (business hours)',
                State='ENABLED'
            )

            # Add Lambda permissions for EventBridge
            try:
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f'allow-eventbridge-down-{short_cluster_suffix}',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f'arn:aws:events:{region}:{account_id}:rule/{scale_down_rule}'
                )
    
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=f'allow-eventbridge-up-{short_cluster_suffix}',
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=f'arn:aws:events:{region}:{account_id}:rule/{scale_up_rule}'
                )
            except lambda_client.exceptions.ResourceConflictException:
                # Permissions already exist
                pass

            # Add targets to rules with nodegroup-aware configuration
            # Scale down configuration includes all nodegroups to scale to configured size
            events_client.put_targets(
                Rule=scale_down_rule,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': function_arn,
                        'Input': json.dumps({
                            'action': 'scale_down',
                            'ist_time': scale_down_time,
                            'nodegroups': [
                                {
                                    'name': nodegroup,
                                    'desired_size': scale_down_desired,
                                    'min_size': scale_down_min,
                                    'max_size': scale_down_max
                                } for nodegroup in nodegroup_names
                            ]
                        })
                    }
                ]
            )

            # Scale up configuration includes all nodegroups to scale to configured size
            events_client.put_targets(
                Rule=scale_up_rule,
                Targets=[
                    {
                        'Id': '1',
                        'Arn': function_arn,
                        'Input': json.dumps({
                            'action': 'scale_up',
                            'ist_time': scale_up_time,
                            'nodegroups': [
                                {
                                    'name': nodegroup,
                                    'desired_size': scale_up_desired,
                                    'min_size': scale_up_min,
                                    'max_size': scale_up_max
                                } for nodegroup in nodegroup_names
                            ]
                        })
                    }
                ]
            )

            self.print_colored(Colors.GREEN, "   ✅ Scheduled scaling configured")
            self.print_colored(Colors.CYAN, f"   📅 Scale up: {scale_up_time} → {scale_up_desired} node(s) per nodegroup")
            self.print_colored(Colors.CYAN, f"   📅 Scale down: {scale_down_time} → {scale_down_desired} node(s) per nodegroup")
            self.print_colored(Colors.CYAN, f"   🌏 Timezone: Indian Standard Time (UTC+5:30)")

            return True

        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to setup multi-nodegroup scheduled scaling: {error_msg}")
            self.print_colored(Colors.RED, f"❌ Scheduled scaling setup failed: {error_msg}")
            return False

    # Correct IST to UTC conversion for EventBridge
    def convert_ist_to_utc_cron(ist_hour, ist_minute):
        """Convert IST time to UTC cron expression"""
        #convert_ist_to_utc_cron(12, 0)   # 12:00 PM IST
        utc_hour = (ist_hour - 5) % 24  # IST is UTC+5:30, simplified to +5
        utc_minute = ist_minute - 30 if ist_minute >= 30 else ist_minute + 30
        if ist_minute < 30:
            utc_hour = (utc_hour - 1) % 24

        return f"cron({utc_minute} {utc_hour} * * ? *)"

    def get_lambda_scaling_template(self) -> str:
        """Get the Lambda function template code as a string"""
        return '''
    import boto3
    import json
    import logging
    from datetime import datetime

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    def lambda_handler(event, context):
        try:
            eks_client = boto3.client('eks', region_name='{region}')
        
            cluster_name = '{cluster_name}'
        
            # Get nodegroup name from cluster
            nodegroups = eks_client.list_nodegroups(clusterName=cluster_name)['nodegroups']
            if not nodegroups:
                logger.error(f"No nodegroups found for cluster {{cluster_name}}")
                return {{'statusCode': 500, 'body': 'No nodegroups found'}}
        
            # Use the first nodegroup found
            nodegroup_name = nodegroups[0]
        
            # Get the desired size from the event
            desired_size = event.get('desired_size', 1)
            min_size = event.get('min_size', 0)
            max_size = event.get('max_size', 3)
        
            # Log current time
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
            logger.info(f"Scaling nodegroup {{nodegroup_name}} to desired={{desired_size}}, min={{min_size}}, max={{max_size}} at {{current_time}}")
        
            # Update nodegroup scaling configuration
            response = eks_client.update_nodegroup_config(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                scalingConfig={{
                    'minSize': min_size,
                    'maxSize': max_size,
                    'desiredSize': desired_size
                }}
            )
        
            logger.info(f"Scaling update initiated: {{response['update']['id']}} at {{current_time}}")
        
            return {{
                'statusCode': 200,
                'body': json.dumps({{
                    'message': f'Scaling update initiated for {{nodegroup_name}} at {{current_time}}',
                    'update_id': response['update']['id'],
                    'timestamp': current_time
                }})
            }}
        
        except Exception as e:
            logger.error(f"Error scaling nodegroup: {{str(e)}}")
            return {{
                'statusCode': 500,
                'body': json.dumps({{
                    'error': str(e)
                }})
            }}
    '''

    def cleanup_temp_file(self, file_path: str) -> None:
            """
            Deletes the temporary file at the given path if it exists.
            """
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.log_operation('INFO', f"Cleaned up temporary file: {file_path}")
                else:
                    self.log_operation('WARNING', f"Temporary file not found during cleanup: {file_path}")
            except Exception as e:
                self.log_operation('ERROR', f"Error during cleanup of temp file {file_path}: {str(e)}")

    def install_enhanced_addons(self, eks_client, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str, account_id: str) -> dict:
        """Install enhanced add-ons (EFS CSI Driver, Node monitoring agent, EKS Pod Identity)"""
        results = {
            'efs_csi_driver': False,
            'node_monitoring_agent': False,
            'eks_pod_identity_agent': False
        }
    
        try:
            self.log_operation('INFO', f"Installing enhanced add-ons for cluster {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔧 Installing enhanced add-ons for {cluster_name}...")
        
            # Get the EKS version to determine compatible add-on versions
            try:
                cluster_info = eks_client.describe_cluster(name=cluster_name)
                eks_version = cluster_info['cluster']['version']
                self.log_operation('INFO', f"Detected EKS version: {eks_version}")
            except Exception as e:
                eks_version = "1.28"  # Default to latest version if we can't detect
                self.log_operation('WARNING', f"Could not detect EKS version, using default {eks_version}: {str(e)}")
        
            # 1. Install Amazon EFS CSI Driver
            try:
                self.print_colored(Colors.CYAN, f"   📦 Installing Amazon EFS CSI Driver...")
            
                # Get appropriate addon version based on EKS version
                if eks_version.startswith('1.32'):
                    addon_version = 'v1.8.0-eksbuild.1'
                if eks_version.startswith('1.28'):
                    addon_version = 'v1.7.0-eksbuild.1'
                elif eks_version.startswith('1.27'):
                    addon_version = 'v1.6.0-eksbuild.1'
                else:
                    addon_version = 'latest'
                
                # Create the IAM role for EFS CSI Driver
                session = boto3.Session(
                    aws_access_key_id=admin_access_key,
                    aws_secret_access_key=admin_secret_key,
                    region_name=region
                )
            
                iam_client = session.client('iam')
            
                # Create EFS CSI Driver policy if needed
                efs_policy_name = "AmazonEFS_CSI_DriverPolicy"
                efs_policy_arn = f"arn:aws:iam::{account_id}:policy/{efs_policy_name}"
            
                efs_policy_document = json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "elasticfilesystem:DescribeAccessPoints",
                                "elasticfilesystem:DescribeFileSystems",
                                "elasticfilesystem:DescribeMountTargets",
                                "elasticfilesystem:CreateAccessPoint",
                                "elasticfilesystem:DeleteAccessPoint",
                                "elasticfilesystem:TagResource"
                            ],
                            "Resource": "*"
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "ec2:DescribeAvailabilityZones"
                            ],
                            "Resource": "*"
                        }
                    ]
                })
            
                try:
                    iam_client.get_policy(PolicyArn=efs_policy_arn)
                    self.log_operation('INFO', f"EFS CSI Driver policy already exists: {efs_policy_arn}")
                except iam_client.exceptions.NoSuchEntityException:
                    policy = iam_client.create_policy(
                        PolicyName=efs_policy_name,
                        PolicyDocument=efs_policy_document,
                        Description="Policy for EFS CSI Driver"
                    )
                    efs_policy_arn = policy['Policy']['Arn']
                    self.log_operation('INFO', f"Created EFS CSI Driver policy: {efs_policy_arn}")
                
                # Attach policy to node role
                try:
                    iam_client.attach_role_policy(
                        RoleName="NodeInstanceRole",
                        PolicyArn=efs_policy_arn
                    )
                    self.log_operation('INFO', f"Attached EFS CSI Driver policy to NodeInstanceRole")
                except Exception as e:
                    self.log_operation('WARNING', f"Failed to attach EFS CSI Driver policy: {str(e)}")
            
                # Create addon
                try:
                    eks_client.create_addon(
                        clusterName=cluster_name,
                        addonName='aws-efs-csi-driver',
                        addonVersion=addon_version if addon_version != 'latest' else None,
                        resolveConflicts='OVERWRITE'
                    )
                
                    # Wait for addon to be active
                    waiter = eks_client.get_waiter('addon_active')
                    waiter.wait(
                        clusterName=cluster_name,
                        addonName='aws-efs-csi-driver',
                        WaiterConfig={'Delay': 15, 'MaxAttempts': 20}
                    )
                
                    self.print_colored(Colors.GREEN, f"   ✅ Amazon EFS CSI Driver installed successfully")
                    self.log_operation('INFO', f"Amazon EFS CSI Driver installed successfully for {cluster_name}")
                    results['efs_csi_driver'] = True
                
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to install Amazon EFS CSI Driver: {str(e)}")
                    self.log_operation('WARNING', f"Failed to install Amazon EFS CSI Driver: {str(e)}")
                
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ EFS CSI Driver installation error: {str(e)}")
                self.log_operation('ERROR', f"EFS CSI Driver installation error: {str(e)}")
            
            # 2. Install Node monitoring agent (CloudWatch agent with Node metrics)
            try:
                self.print_colored(Colors.CYAN, f"   📦 Installing Node monitoring agent...")
            
                # Use kubectl to deploy Node monitoring agent
                import subprocess
                import shutil
            
                kubectl_available = shutil.which('kubectl') is not None
                if not kubectl_available:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ kubectl not found. Node monitoring agent installation skipped.")
                    self.log_operation('WARNING', f"kubectl not found. Node monitoring agent installation skipped.")
                else:
                    # Setup environment
                    env = os.environ.copy()
                    env['AWS_ACCESS_KEY_ID'] = admin_access_key
                    env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
                    env['AWS_DEFAULT_REGION'] = region
                
                    # Create ConfigMap with node monitoring configuration
                    node_monitoring_config = {
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "metadata": {
                            "name": "node-monitoring-config",
                            "namespace": "amazon-cloudwatch"
                        },
                        "data": {
                            "node-metrics.json": json.dumps({
                                "agent": {
                                    "metrics_collection_interval": 60
                                },
                                "metrics": {
                                    "namespace": "NodeMonitoring",
                                    "metrics_collected": {
                                        "cpu": {
                                            "resources": ["*"],
                                            "measurement": ["usage_active", "usage_system", "usage_user"],
                                            "metrics_collection_interval": 60
                                        },
                                        "memory": {
                                            "measurement": ["used_percent", "used", "available"],
                                            "metrics_collection_interval": 60
                                        },
                                        "disk": {
                                            "resources": ["/", "/tmp"],
                                            "measurement": ["used_percent", "inodes_free"],
                                            "metrics_collection_interval": 60
                                        },
                                        "diskio": {
                                            "resources": ["*"],
                                            "measurement": ["io_time", "write_bytes", "read_bytes"],
                                            "metrics_collection_interval": 60
                                        },
                                        "netstat": {
                                            "measurement": ["tcp_established", "tcp_time_wait"],
                                            "metrics_collection_interval": 60
                                        },
                                        "swap": {
                                            "measurement": ["used_percent", "free"],
                                            "metrics_collection_interval": 60
                                        }
                                    }
                                }
                            })
                        }
                    }
                
                    # Create yaml file
                    import tempfile
                    import yaml
                
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                        yaml.dump(node_monitoring_config, f)
                        config_file = f.name
                
                    try:
                        # Create namespace if it doesn't exist
                        namespace_cmd = ['kubectl', 'create', 'namespace', 'amazon-cloudwatch']
                        try:
                            subprocess.run(namespace_cmd, env=env, capture_output=True, text=True, timeout=60)
                        except Exception as e:
                            # Namespace might already exist, continue anyway
                            pass
                    
                        # Apply config
                        apply_cmd = ['kubectl', 'apply', '-f', config_file]
                        apply_result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=120)
                    
                        if apply_result.returncode == 0:
                            self.print_colored(Colors.GREEN, f"   ✅ Node monitoring agent configured successfully")
                            self.log_operation('INFO', f"Node monitoring agent configured for {cluster_name}")
                            results['node_monitoring_agent'] = True
                        else:
                            self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to configure Node monitoring agent: {apply_result.stderr}")
                            self.log_operation('WARNING', f"Failed to configure Node monitoring agent: {apply_result.stderr}")
                        
                    finally:
                        # Clean up
                        try:
                            os.unlink(config_file)
                        except:
                            pass
                
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Node monitoring agent installation error: {str(e)}")
                self.log_operation('ERROR', f"Node monitoring agent installation error: {str(e)}")
            
            # 3. Install Amazon EKS Pod Identity Agent
            try:
                self.print_colored(Colors.CYAN, f"   📦 Installing Amazon EKS Pod Identity Agent...")
            
                # Get appropriate addon version based on EKS version
                if eks_version.startswith('1.32'):
                    identity_version = 'v1.2.0-eksbuild.1'
                if eks_version.startswith('1.28'):
                    identity_version = 'v1.1.0-eksbuild.1'
                else:
                    identity_version = 'latest'
                
                # Create addon
                try:
                    eks_client.create_addon(
                        clusterName=cluster_name,
                        addonName='eks-pod-identity-agent',
                        addonVersion=identity_version if identity_version != 'latest' else None,
                        resolveConflicts='OVERWRITE'
                    )
                
                    # Wait for addon to be active
                    waiter = eks_client.get_waiter('addon_active')
                    waiter.wait(
                        clusterName=cluster_name,
                        addonName='eks-pod-identity-agent',
                        WaiterConfig={'Delay': 15, 'MaxAttempts': 20}
                    )
                
                    self.print_colored(Colors.GREEN, f"   ✅ Amazon EKS Pod Identity Agent installed successfully")
                    self.log_operation('INFO', f"Amazon EKS Pod Identity Agent installed successfully for {cluster_name}")
                    results['eks_pod_identity_agent'] = True
                
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Failed to install Amazon EKS Pod Identity Agent: {str(e)}")
                    self.log_operation('WARNING', f"Failed to install Amazon EKS Pod Identity Agent: {str(e)}")
                
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ EKS Pod Identity Agent installation error: {str(e)}")
                self.log_operation('ERROR', f"EKS Pod Identity Agent installation error: {str(e)}")
            
            # Summary of enhanced addons installation
            successful = sum(1 for value in results.values() if value)
            total = len(results)
        
            self.print_colored(Colors.GREEN, f"✅ Enhanced add-ons installation completed: {successful}/{total} successful")
            self.log_operation('INFO', f"Enhanced add-ons installation completed for {cluster_name}: {successful}/{total} successful")
        
            return results
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to install enhanced add-ons for {cluster_name}: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Enhanced add-ons installation failed: {str(e)}")
            return results

    def verify_scheduled_scaling(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str) -> bool:
        """Verify if scheduled scaling has been properly configured"""
        try:
            self.print_colored(Colors.YELLOW, f"🔍 Verifying scheduled scaling for {cluster_name}...")
        
            # Create admin session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
        
            # Create EventBridge client
            events_client = admin_session.client('events')
            lambda_client = admin_session.client('lambda')
        
            # Get the short cluster suffix used in rule names
            short_cluster_suffix = cluster_name.split('-')[-1]
            scale_up_rule = f"eks-up-{short_cluster_suffix}"
            scale_down_rule = f"eks-down-{short_cluster_suffix}"
            function_name = f"eks-scale-{short_cluster_suffix}"
        
            verification_results = {
                'lambda_exists': False,
                'scale_up_rule_exists': False,
                'scale_down_rule_exists': False
            }
        
            # 1. Verify the Lambda function exists
            try:
                lambda_response = lambda_client.get_function(FunctionName=function_name)
            
                if lambda_response and 'Configuration' in lambda_response:
                    verification_results['lambda_exists'] = True
                    self.print_colored(Colors.GREEN, f"   ✅ Lambda function verified: {function_name}")
                
                    # Show additional Lambda info
                    last_modified = lambda_response['Configuration'].get('LastModified', 'Unknown')
                    runtime = lambda_response['Configuration'].get('Runtime', 'Unknown')
                    memory = lambda_response['Configuration'].get('MemorySize', 'Unknown')
                    timeout = lambda_response['Configuration'].get('Timeout', 'Unknown')
                
                    self.print_colored(Colors.CYAN, f"      - Last Modified: {last_modified}")
                    self.print_colored(Colors.CYAN, f"      - Runtime: {runtime}")
                    self.print_colored(Colors.CYAN, f"      - Memory: {memory}MB, Timeout: {timeout}s")
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Lambda function verification failed: {str(e)}")
            
            # 2. Verify EventBridge rules exist
            try:
                # Check scale up rule
                up_rule_response = events_client.describe_rule(Name=scale_up_rule)
                if up_rule_response:
                    verification_results['scale_up_rule_exists'] = True
                    self.print_colored(Colors.GREEN, f"   ✅ Scale-up rule verified: {scale_up_rule}")
                
                    # Show schedule and state
                    schedule = up_rule_response.get('ScheduleExpression', 'Unknown')
                    state = up_rule_response.get('State', 'Unknown')
                    self.print_colored(Colors.CYAN, f"      - Schedule: {schedule} ({state})")
                
                    # Get targets for the rule
                    targets = events_client.list_targets_by_rule(Rule=scale_up_rule)
                    if 'Targets' in targets:
                        first_target = targets['Targets'][0] if targets['Targets'] else {}
                        if 'Input' in first_target:
                            input_json = json.loads(first_target['Input'])
                            desired = input_json.get('desired_size', 'Unknown')
                            min_size = input_json.get('min_size', 'Unknown')
                            max_size = input_json.get('max_size', 'Unknown')
                            ist_time = input_json.get('ist_time', 'Unknown')
                            self.print_colored(Colors.CYAN, f"      - Action: Scale to {desired} nodes at {ist_time}")
                            self.print_colored(Colors.CYAN, f"      - Min/Max: {min_size}/{max_size}")
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Scale-up rule verification failed: {str(e)}")
            
            try:
                # Check scale down rule
                down_rule_response = events_client.describe_rule(Name=scale_down_rule)
                if down_rule_response:
                    verification_results['scale_down_rule_exists'] = True
                    self.print_colored(Colors.GREEN, f"   ✅ Scale-down rule verified: {scale_down_rule}")
                
                    # Show schedule and state
                    schedule = down_rule_response.get('ScheduleExpression', 'Unknown')
                    state = down_rule_response.get('State', 'Unknown')
                    self.print_colored(Colors.CYAN, f"      - Schedule: {schedule} ({state})")
                
                    # Get targets for the rule
                    targets = events_client.list_targets_by_rule(Rule=scale_down_rule)
                    if 'Targets' in targets:
                        first_target = targets['Targets'][0] if targets['Targets'] else {}
                        if 'Input' in first_target:
                            input_json = json.loads(first_target['Input'])
                            desired = input_json.get('desired_size', 'Unknown')
                            min_size = input_json.get('min_size', 'Unknown')
                            max_size = input_json.get('max_size', 'Unknown')
                            ist_time = input_json.get('ist_time', 'Unknown')
                            self.print_colored(Colors.CYAN, f"      - Action: Scale to {desired} nodes at {ist_time}")
                            self.print_colored(Colors.CYAN, f"      - Min/Max: {min_size}/{max_size}")
            except Exception as e:
                self.print_colored(Colors.RED, f"   ❌ Scale-down rule verification failed: {str(e)}")
        
            # 3. Overall verification status
            all_verified = all(verification_results.values())
        
            if all_verified:
                self.print_colored(Colors.GREEN, f"✅ Scheduled scaling verification successful")
                self.print_colored(Colors.GREEN, f"   All components verified: Lambda function, scale-up rule, scale-down rule")
            else:
                self.print_colored(Colors.YELLOW, f"⚠️ Scheduled scaling verification incomplete")
                self.print_colored(Colors.YELLOW, f"   Some components could not be verified")
            
            return all_verified
        
        except Exception as e:
            self.log_operation('ERROR', f"Failed to verify scheduled scaling: {str(e)}")
            self.print_colored(Colors.RED, f"❌ Scheduled scaling verification failed: {str(e)}")
            return False

    def download_and_patch_fluentbit_config(self, manifest_url: str, cluster_name: str) -> str:
        """
        Downloads the fluent-bit-configmap.yaml file, replaces {cluster_name} placeholder,
        and writes it to a temporary file. Returns the path to the modified file.
        """
        try:
            self.log_operation('INFO', f"Downloading and patching manifest from: {manifest_url}")
            response = requests.get(manifest_url)
            if response.status_code != 200:
                raise Exception(f"Failed to download manifest: HTTP {response.status_code}")

            # Replace placeholder with actual cluster name
            patched_yaml = response.text.replace("{cluster_name}", cluster_name)

            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml", mode='w') as temp_file:
                temp_file.write(patched_yaml)
                self.log_operation('INFO', f"Patched manifest written to: {temp_file.name}")
                return temp_file.name
        except Exception as e:
            self.log_operation('ERROR', f"Error patching fluent-bit configmap: {str(e)}")
            raise

    #######

    def verify_enhanced_cluster_components(self, cluster_name: str, region: str, access_key: str, secret_key: str, account_id: str) -> dict:
            """
            Verify all enhanced components installed on the cluster before health check
            Returns a dictionary with verification status of each component
            """
            self.log_operation('INFO', f"Verifying enhanced cluster components for {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔍 Verifying enhanced cluster components for {cluster_name}...")

            # Initialize results dictionary
            verification_results = {
                'container_insights': False,
                'cluster_autoscaler': False,
                'scheduled_scaling': False,
                'cloudwatch_agent': False,
                'cloudwatch_alarms': False,
                'cost_alarms': False,
                'addons': {
                    'core_addons': False,
                    'efs_csi_driver': False,
                    'eks_pod_identity': False
                },
                'overall': False
            }
    
            # Create session for AWS clients
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            eks_client = session.client('eks')
            cloudwatch_client = session.client('cloudwatch')
            events_client = session.client('events')
            lambda_client = session.client('lambda')
    
            try:
                # 1. Verify Container Insights
                self.print_colored(Colors.CYAN, "📊 Verifying CloudWatch Container Insights...")
                container_insights_verified = self._verify_container_insights(cluster_name, region, access_key, secret_key)
                verification_results['container_insights'] = container_insights_verified
        
                # 2. Verify Cluster Autoscaler
                self.print_colored(Colors.CYAN, "🔄 Verifying Cluster Autoscaler...")
                autoscaler_verified = self._verify_cluster_autoscaler(cluster_name, region, access_key, secret_key)
                verification_results['cluster_autoscaler'] = autoscaler_verified
        
                # 3. Verify Scheduled Scaling
                self.print_colored(Colors.CYAN, "⏰ Verifying Scheduled Scaling...")
                short_cluster_suffix = cluster_name.split('-')[-1]
                function_name = f"eks-scale-{short_cluster_suffix}"
                scale_up_rule = f"eks-up-{short_cluster_suffix}"
                scale_down_rule = f"eks-down-{short_cluster_suffix}"
        
                # Check if Lambda function exists
                lambda_exists = False
                try:
                    lambda_response = lambda_client.get_function(FunctionName=function_name)
                    lambda_exists = 'Configuration' in lambda_response
                    if lambda_exists:
                        self.print_colored(Colors.GREEN, f"   ✅ Lambda function verified: {function_name}")
                except Exception:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Lambda function not found: {function_name}")
        
                # Check if EventBridge rules exist
                rules_exist = False
                try:
                    up_rule = events_client.describe_rule(Name=scale_up_rule)
                    down_rule = events_client.describe_rule(Name=scale_down_rule)
                    rules_exist = True
                    self.print_colored(Colors.GREEN, f"   ✅ Scheduling rules verified: {scale_up_rule}, {scale_down_rule}")
                except Exception:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Scheduling rules not found")
            
                verification_results['scheduled_scaling'] = lambda_exists and rules_exist
        
                # 4. Verify CloudWatch Agent
                self.print_colored(Colors.CYAN, "🔍 Verifying CloudWatch Agent...")
        
                # Check if CloudWatch agent deployment exists using kubectl
                import subprocess
                import shutil
        
                kubectl_available = shutil.which('kubectl') is not None
                cloudwatch_agent_verified = False
        
                if kubectl_available:
                    env = os.environ.copy()
                    env['AWS_ACCESS_KEY_ID'] = access_key
                    env['AWS_SECRET_ACCESS_KEY'] = secret_key
                    env['AWS_DEFAULT_REGION'] = region
            
                    # Update kubeconfig
                    try:
                        update_cmd = [
                            'aws', 'eks', 'update-kubeconfig',
                            '--region', region,
                            '--name', cluster_name
                        ]
                        subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
                
                        # Check for CloudWatch agent pods
                        agent_cmd = ['kubectl', 'get', 'pods', '-n', 'amazon-cloudwatch', '-l', 'name=cloudwatch-agent', '--no-headers']
                        agent_result = subprocess.run(agent_cmd, env=env, capture_output=True, text=True, timeout=60)
                
                        if agent_result.returncode == 0:
                            pod_lines = [line.strip() for line in agent_result.stdout.strip().split('\n') if line.strip()]
                            running_pods = [line for line in pod_lines if 'Running' in line]
                    
                            if running_pods:
                                cloudwatch_agent_verified = True
                                self.print_colored(Colors.GREEN, f"   ✅ CloudWatch agent pods: {len(running_pods)} running")
                            else:
                                self.print_colored(Colors.YELLOW, f"   ⚠️ No running CloudWatch agent pods found")
                        else:
                            self.print_colored(Colors.YELLOW, f"   ⚠️ Could not check CloudWatch agent pods: {agent_result.stderr}")
                    except Exception as e:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking CloudWatch agent: {str(e)}")
                else:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ kubectl not available, skipping CloudWatch agent check")
            
                verification_results['cloudwatch_agent'] = cloudwatch_agent_verified
        
                # 5. Verify CloudWatch Alarms
                self.print_colored(Colors.CYAN, "🚨 Verifying CloudWatch Alarms...")
        
                # Check for basic alarms
                alarm_prefix = f"{cluster_name}-"
                try:
                    alarms_response = cloudwatch_client.describe_alarms(
                        AlarmNamePrefix=alarm_prefix,
                        AlarmTypes=['MetricAlarm']
                    )
                    metric_alarms = alarms_response.get('MetricAlarms', [])
            
                    # Check for composite alarms
                    composite_response = cloudwatch_client.describe_alarms(
                        AlarmNamePrefix=alarm_prefix,
                        AlarmTypes=['CompositeAlarm']
                    )
                    composite_alarms = composite_response.get('CompositeAlarms', [])
            
                    if len(metric_alarms) > 0:
                        self.print_colored(Colors.GREEN, f"   ✅ CloudWatch metric alarms: {len(metric_alarms)} found")
                        verification_results['cloudwatch_alarms'] = True
                    else:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ No CloudWatch metric alarms found with prefix {alarm_prefix}")
                
                    if len(composite_alarms) > 0:
                        self.print_colored(Colors.GREEN, f"   ✅ CloudWatch composite alarms: {len(composite_alarms)} found")
                    else:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ No CloudWatch composite alarms found with prefix {alarm_prefix}")
        
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking CloudWatch alarms: {str(e)}")
            
                # 6. Verify Cost Alarms
                self.print_colored(Colors.CYAN, "💰 Verifying Cost Monitoring Alarms...")
        
                try:
                    cost_alarm_patterns = [f"{cluster_name}-daily-cost", f"{cluster_name}-ec2-cost", f"{cluster_name}-ebs-cost"]
                    cost_alarms_found = 0
            
                    for pattern in cost_alarm_patterns:
                        try:
                            cost_response = cloudwatch_client.describe_alarms(
                                AlarmNamePrefix=pattern,
                                AlarmTypes=['MetricAlarm']
                            )
                            pattern_alarms = cost_response.get('MetricAlarms', [])
                            cost_alarms_found += len(pattern_alarms)
                    
                            if pattern_alarms:
                                self.print_colored(Colors.GREEN, f"   ✅ Cost alarms for {pattern}: {len(pattern_alarms)} found")
                        except Exception:
                            continue
                    
                    verification_results['cost_alarms'] = cost_alarms_found > 0
            
                    if cost_alarms_found == 0:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ No cost monitoring alarms found")
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking cost alarms: {str(e)}")
            
                # 7. Verify Core Add-ons
                self.print_colored(Colors.CYAN, "🧩 Verifying Core Add-ons...")
        
                try:
                    addons_response = eks_client.list_addons(clusterName=cluster_name)
                    addons = addons_response.get('addons', [])
            
                    essential_addons = ['vpc-cni', 'coredns', 'kube-proxy']
                    found_essential = [addon for addon in addons if addon in essential_addons]
            
                    # Check EFS CSI driver
                    efs_addon = 'aws-efs-csi-driver' in addons
                    verification_results['addons']['efs_csi_driver'] = efs_addon
            
                    # Check EKS Pod Identity
                    pod_identity = 'eks-pod-identity-agent' in addons
                    verification_results['addons']['eks_pod_identity'] = pod_identity
            
                    # Check core addons
                    core_addons_complete = len(found_essential) == len(essential_addons)
                    verification_results['addons']['core_addons'] = core_addons_complete
            
                    self.print_colored(Colors.GREEN, f"   ✅ Essential add-ons: {len(found_essential)}/{len(essential_addons)} found")
            
                    if efs_addon:
                        self.print_colored(Colors.GREEN, f"   ✅ Amazon EFS CSI Driver: Installed")
                    else:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Amazon EFS CSI Driver: Not installed")
                
                    if pod_identity:
                        self.print_colored(Colors.GREEN, f"   ✅ Amazon EKS Pod Identity Agent: Installed")
                    else:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Amazon EKS Pod Identity Agent: Not installed")
                
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking add-ons: {str(e)}")
        
                # Calculate overall verification status
                # Consider core functionality (we can be lenient with enhanced features)
                core_components = [
                    verification_results['container_insights'],
                    verification_results['cluster_autoscaler'],
                    verification_results['cloudwatch_alarms'],
                    verification_results['addons']['core_addons']
                ]
        
                verification_results['overall'] = all(core_components)
        
                # Print summary
                success_count = sum(1 for key, value in verification_results.items() 
                                  if key != 'addons' and key != 'overall' and value)
                addon_success = sum(1 for _, value in verification_results['addons'].items() if value)
                total_items = len([key for key in verification_results if key != 'addons' and key != 'overall'])
                total_addons = len(verification_results['addons'])
        
                self.print_colored(Colors.GREEN, f"\n📋 Verification Summary:")
                self.print_colored(Colors.GREEN if verification_results['overall'] else Colors.YELLOW, 
                                  f"   ✓ Core functionality: {verification_results['overall']}")
                self.print_colored(Colors.CYAN, f"   ✓ Components verified: {success_count}/{total_items}")
                self.print_colored(Colors.CYAN, f"   ✓ Add-ons verified: {addon_success}/{total_addons}")
        
                return verification_results
        
            except Exception as e:
                self.log_operation('ERROR', f"Error during component verification: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Component verification failed: {str(e)}")
                return verification_results

    def setup_and_verify_all_components(self, cluster_name: str, region: str, access_key: str, secret_key: str,
                                        account_id: str, nodegroups_created: list,
                                        enable_container_insights: bool) -> dict:
        """
        Setup and verify all components, including:
        - Container Insights
        - Cluster Autoscaler
        - Scheduled Scaling
        - CloudWatch Agent
        - CloudWatch Alarms
        - Cost Alarms
        - Node Protection Verification (NEW)

        Returns a dictionary with status of all components
        """
        self.log_operation('INFO', f"Setting up and verifying all components for {cluster_name}")
        self.print_colored(Colors.YELLOW, f"\n🔧 Setting up and verifying all components for {cluster_name}...")

        components_status = {
            'container_insights': False,
            'cluster_autoscaler': False,
            'scheduled_scaling': False,
            'cloudwatch_agent': False,
            'cloudwatch_alarms': False,
            'cost_alarms': False,
            'user_access': False,
            'node_protection': {
                'enabled': False,
                'monitoring_setup': False,
                'protected_nodegroups': [],
                'protected_nodes_count': 0,
                'verification_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

        # Create session clients
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )

        cloudwatch_client = session.client('cloudwatch')

        # 1. Setup Container Insights
        if enable_container_insights:
            print("\n📊 Step 1: Setting up CloudWatch Container Insights...")
            insights_success = self.enable_container_insights(
                cluster_name, region, access_key, secret_key
            )
            components_status['container_insights'] = insights_success
        else:
            print("\n📊 Step 1: Skipping CloudWatch Container Insights setup as per user preference.")
            components_status['container_insights'] = False

        # 2. Setup Cluster Autoscaler
        print("\n🔄 Step 2: Setting up Cluster Autoscaler for all nodegroups...")
        deployer = CompleteAutoscalerDeployer()
        autoscaler_success = deployer.deploy_complete_autoscaler(
            cluster_name, region, access_key, secret_key, account_id
        )
        components_status['cluster_autoscaler'] = autoscaler_success

        if True:
            # 3. Setup Scheduled Scaling
            print("\n⏰ Step 3: Setting up Scheduled Scaling for all nodegroups...")
            scheduling_success = self.setup_scheduled_scaling_multi_nodegroup(
                cluster_name, region, access_key, secret_key, nodegroups_created
            )
            components_status['scheduled_scaling'] = scheduling_success

        # 4. Deploy CloudWatch agent
        # if self.should_deploy_cloudwatch_agent():
        if False:  # Always skip for now
            print("\n🔍 Step 4: Deploying CloudWatch agent...")
            from custom_cloudwatch_agent_deployer import CustomCloudWatchAgentDeployer
            agent_deployer = CustomCloudWatchAgentDeployer()
            cloudwatch_agent_success = agent_deployer.deploy_custom_cloudwatch_agent(
                cluster_name, region, access_key, secret_key
            )
            components_status['cloudwatch_agent'] = cloudwatch_agent_success
        else:
            print("\n🔍 Step 4: Skipping CloudWatch agent deployment as per user preference.")
            components_status['cloudwatch_agent'] = False

        # 5. Setup CloudWatch alarms
        print("\n🚨 Step 5: Setting up CloudWatch alarms...")
        cloudwatch_alarms_success = self.setup_cloudwatch_alarms_multi_nodegroup(
            cluster_name, region, cloudwatch_client, nodegroups_created, account_id
        )
        components_status['cloudwatch_alarms'] = cloudwatch_alarms_success

        # 6. Setup cost monitoring alarms
        print("\n💰 Step 6: Setting up cost monitoring alarms...")
        cost_alarms_success = self.setup_cost_alarms(
            cluster_name, region, cloudwatch_client, account_id
        )
        components_status['cost_alarms'] = cost_alarms_success

        # 7. NEW: Verify Node Protection Status
        print("\n🛡️ Step 7: Verifying node protection status...")
        try:
            protection_status = self.verify_node_protection_status(cluster_name, region, access_key, secret_key)

            if protection_status:
                components_status['node_protection']['enabled'] = protection_status.get('protected_nodes', 0) > 0
                components_status['node_protection']['protected_nodegroups'] = protection_status.get(
                    'protected_nodegroups', [])
                components_status['node_protection']['protected_nodes_count'] = protection_status.get('protected_nodes',
                                                                                                      0)

                # Display node protection status
                if components_status['node_protection']['enabled']:
                    self.print_colored(Colors.GREEN,
                                       f"   ✅ Node protection enabled: {protection_status.get('protected_nodes', 0)} nodes protected")
                    for ng in protection_status.get('protected_nodegroups', []):
                        self.print_colored(Colors.CYAN, f"      - Protected nodegroup: {ng}")
                else:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ No node protection found")
            else:
                self.print_colored(Colors.YELLOW, f"   ⚠️ Could not verify node protection status")

        except Exception as e:
            self.log_operation('WARNING', f"Could not verify node protection: {str(e)}")
            self.print_colored(Colors.YELLOW, f"   ⚠️ Node protection verification failed: {str(e)}")

        # 8. NEW: Check for Node Protection Monitoring Lambda
        print("\n🔍 Step 8: Checking node protection monitoring setup...")
        try:
            lambda_client = session.client('lambda')

            # Check for various possible Lambda function names
            possible_function_names = [
                f"node-protection-monitor-{cluster_name}",
                f"node-protection-{cluster_name}",
                f"eks-node-monitor-{cluster_name.split('-')[-1]}",  # Using cluster suffix
                f"node-monitor-{cluster_name.split('-')[-1]}",
                f"node-protection-monitor-{cluster_name.split('-')[-1]}",
            ]

            monitoring_found = False
            for function_name in possible_function_names:
                try:
                    lambda_response = lambda_client.get_function(FunctionName=function_name)
                    monitoring_found = True
                    components_status['node_protection']['monitoring_setup'] = True
                    self.print_colored(Colors.GREEN, f"   ✅ Node protection monitoring Lambda found: {function_name}")

                    # Log additional details about the Lambda function
                    last_modified = lambda_response['Configuration'].get('LastModified', 'Unknown')
                    runtime = lambda_response['Configuration'].get('Runtime', 'Unknown')
                    self.print_colored(Colors.CYAN, f"      - Last Modified: {last_modified}")
                    self.print_colored(Colors.CYAN, f"      - Runtime: {runtime}")
                    break

                except lambda_client.exceptions.ResourceNotFoundException:
                    continue

            if not monitoring_found:
                components_status['node_protection']['monitoring_setup'] = False
                self.print_colored(Colors.YELLOW, f"   ⚠️ No node protection monitoring Lambda found")
                self.print_colored(Colors.CYAN, f"      - Searched for: {', '.join(possible_function_names)}")

        except Exception as e:
            self.log_operation('WARNING', f"Could not check node protection monitoring: {str(e)}")
            self.print_colored(Colors.YELLOW, f"   ⚠️ Node protection monitoring check failed: {str(e)}")

        # 9. Verify all other components (existing functionality)
        print("\n🔍 Step 9: Verifying all components...")
        verification_results = self.verify_enhanced_cluster_components(
            cluster_name, region, access_key, secret_key, account_id
        )

        # Update components status with verification results
        for key in components_status:
            if key != 'node_protection' and key in verification_results and verification_results[key]:
                # If verification confirms it's working, keep it as is
                # If verification says it's not working but setup reported success,
                # we'll trust the verification (more reliable)
                if not verification_results[key]:
                    components_status[key] = False

        # 10. Final Node Protection Summary
        print("\n🛡️ Final Node Protection Summary:")
        node_protection = components_status['node_protection']
        if node_protection['enabled']:
            self.print_colored(Colors.GREEN, f"   ✅ Protection Status: ENABLED")
            self.print_colored(Colors.GREEN, f"   ✅ Protected Nodes: {node_protection['protected_nodes_count']}")
            self.print_colored(Colors.GREEN,
                               f"   ✅ Protected Nodegroups: {len(node_protection['protected_nodegroups'])}")
            if node_protection['monitoring_setup']:
                self.print_colored(Colors.GREEN, f"   ✅ Monitoring Lambda: ACTIVE")
            else:
                self.print_colored(Colors.YELLOW, f"   ⚠️ Monitoring Lambda: NOT FOUND")
        else:
            self.print_colored(Colors.YELLOW, f"   ⚠️ Protection Status: NOT ENABLED")
            self.print_colored(Colors.YELLOW, f"   ⚠️ Consider enabling node protection for critical workloads")

        return components_status

    def verify_node_protection_status(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> dict:
        """
        Verify the current node protection status

        Returns:
            dict: Contains protection status, protected nodes count, and protected nodegroups
        """
        try:
            import subprocess
            import shutil
            import json
            import re

            # Check if kubectl is available
            kubectl_available = shutil.which('kubectl') is not None
            if not kubectl_available:
                self.log_operation('WARNING', f"kubectl not found. Cannot verify node protection")
                return {}

            # Set environment variables for access
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region

            # Update kubeconfig
            update_cmd = [
                'aws', 'eks', 'update-kubeconfig',
                '--region', region,
                '--name', cluster_name
            ]

            update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
            if update_result.returncode != 0:
                self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                return {}

            # Get all nodes with NO_DELETE label
            nodes_cmd = ['kubectl', 'get', 'nodes', '-l', 'NO_DELETE=true', '-o', 'json']
            nodes_result = subprocess.run(nodes_cmd, env=env, capture_output=True, text=True, timeout=60)

            if nodes_result.returncode != 0:
                self.log_operation('WARNING', f"Could not get protected nodes: {nodes_result.stderr}")
                return {
                    'protected_nodes': 0,
                    'protected_nodegroups': [],
                    'verification_status': 'failed'
                }

            # Parse the JSON response
            try:
                nodes_data = json.loads(nodes_result.stdout)
                protected_nodes = nodes_data.get('items', [])

                # Extract nodegroups from protected nodes
                protected_nodegroups = set()
                for node in protected_nodes:
                    labels = node.get('metadata', {}).get('labels', {})
                    nodegroup = labels.get('eks.amazonaws.com/nodegroup')
                    if nodegroup:
                        protected_nodegroups.add(nodegroup)

                return {
                    'protected_nodes': len(protected_nodes),
                    'protected_nodegroups': list(protected_nodegroups),
                    'verification_status': 'success',
                    'verification_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

            except json.JSONDecodeError as e:
                self.log_operation('ERROR', f"Failed to parse kubectl JSON output: {str(e)}")
                return {}

        except Exception as e:
            self.log_operation('ERROR', f"Failed to verify node protection status: {str(e)}")
            return {}
    #######

    def verify_cloudwatch_insights(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
            """Verify if CloudWatch Container Insights is working - FIXED"""
            try:
                self.log_operation('INFO', f"Verifying CloudWatch Container Insights for cluster {cluster_name}")
                self.print_colored(Colors.YELLOW, f"🔍 Verifying CloudWatch Container Insights...")
    
                import subprocess
                import shutil
    
                kubectl_available = shutil.which('kubectl') is not None
                if not kubectl_available:
                    self.log_operation('WARNING', f"kubectl not found. Cannot verify Container Insights")
                    self.print_colored(Colors.YELLOW, f"⚠️ kubectl not found. Manual verification required.")
                    return False
        
                # Set environment variables for access
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = access_key
                env['AWS_SECRET_ACCESS_KEY'] = secret_key
                env['AWS_DEFAULT_REGION'] = region
    
                # Ensure kubeconfig is updated
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]
    
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
                if update_result.returncode != 0:
                    self.print_colored(Colors.RED, f"❌ Failed to update kubeconfig: {update_result.stderr}")
                    return False
        
                # FIXED: Check multiple possible namespaces and pod patterns for Container Insights
                namespaces_to_check = ['amazon-cloudwatch', 'kube-system']
                pod_patterns = [
                    'cloudwatch-agent',
                    'fluent-bit',
                    'aws-cloudwatch',
                    'container-insights'
                ]
        
                total_running_pods = 0
                found_insights_pods = False
        
                for namespace in namespaces_to_check:
                    try:
                        # Check all pods in the namespace
                        verify_cmd = ['kubectl', 'get', 'pods', '-n', namespace, '--no-headers']
                        verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=60)
            
                        if verify_result.returncode == 0 and verify_result.stdout.strip():
                            pod_lines = [line.strip() for line in verify_result.stdout.strip().split('\n') if line.strip()]
                    
                            # Filter for Container Insights related pods
                            insights_pods = []
                            for line in pod_lines:
                                pod_name = line.split()[0] if line.split() else ""
                                for pattern in pod_patterns:
                                    if pattern in pod_name.lower():
                                        insights_pods.append(line)
                                        break
                    
                            if insights_pods:
                                found_insights_pods = True
                                running_pods = [line for line in insights_pods if 'Running' in line or 'Completed' in line]
                                total_running_pods += len(running_pods)
                        
                                self.print_colored(Colors.GREEN, f"   ✅ Found Container Insights pods in namespace '{namespace}': {len(running_pods)}/{len(insights_pods)} running")
                        
                                # Display specific pod details
                                for pod in insights_pods[:3]:  # Show first 3 pods
                                    pod_parts = pod.split()
                                    if len(pod_parts) >= 3:
                                        pod_name = pod_parts[0]
                                        pod_status = pod_parts[2]
                                        status_color = Colors.GREEN if pod_status == "Running" else Colors.YELLOW
                                        self.print_colored(status_color, f"      - {pod_name}: {pod_status}")
                            else:
                                self.print_colored(Colors.CYAN, f"   📍 No Container Insights pods found in namespace '{namespace}'")
                        
                    except Exception as e:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking namespace '{namespace}': {str(e)}")
        
                if found_insights_pods and total_running_pods > 0:
                    self.print_colored(Colors.GREEN, f"✅ CloudWatch Container Insights: {total_running_pods} total pods running")
            
                    # Display CloudWatch Console link
                    self.print_colored(Colors.CYAN, "📊 View in AWS Console:")
                    self.print_colored(Colors.CYAN, f"   - CloudWatch → Insights → Container Insights → {cluster_name}")
                    self.print_colored(Colors.CYAN, f"   - CloudWatch → Logs → Log groups → /aws/containerinsights/{cluster_name}")
            
                    return True
                else:
                    self.print_colored(Colors.YELLOW, f"⚠️ CloudWatch Container Insights: No running pods found")
                    self.print_colored(Colors.YELLOW, f"   - Container Insights may still be starting, check again in a few minutes")
                    return False
        
            except Exception as e:
                self.log_operation('ERROR', f"Failed to verify Container Insights: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Container Insights verification failed: {str(e)}")
                return False

    def _verify_container_insights(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
            """Helper method to verify Container Insights deployment - FIXED"""
            try:
                import subprocess
                import shutil
    
                kubectl_available = shutil.which('kubectl') is not None
                if not kubectl_available:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ kubectl not found, skipping Container Insights check")
                    return False
        
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = access_key
                env['AWS_SECRET_ACCESS_KEY'] = secret_key
                env['AWS_DEFAULT_REGION'] = region
    
                # Update kubeconfig
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]
                subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
    
                # FIXED: Check for CloudWatch Container Insights pods in multiple namespaces
                namespaces_to_check = ['amazon-cloudwatch', 'kube-system']
                total_running_pods = 0
        
                for namespace in namespaces_to_check:
                    try:
                        pods_cmd = ['kubectl', 'get', 'pods', '-n', namespace, '--no-headers']
                        pods_result = subprocess.run(pods_cmd, env=env, capture_output=True, text=True, timeout=60)
            
                        if pods_result.returncode == 0 and pods_result.stdout.strip():
                            pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
                    
                            # Filter for Container Insights related pods
                            insights_patterns = ['cloudwatch-agent', 'fluent-bit', 'aws-cloudwatch', 'container-insights']
                            insights_pods = []
                    
                            for line in pod_lines:
                                pod_name = line.split()[0] if line.split() else ""
                                for pattern in insights_patterns:
                                    if pattern in pod_name.lower():
                                        insights_pods.append(line)
                                        break
                    
                            if insights_pods:
                                running_pods = [line for line in insights_pods if 'Running' in line]
                                total_running_pods += len(running_pods)
                        
                                if running_pods:
                                    self.print_colored(Colors.GREEN, f"   ✅ Container Insights pods in '{namespace}': {len(running_pods)}/{len(insights_pods)} running")
                            
                    except Exception as e:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking namespace '{namespace}': {str(e)}")
        
                if total_running_pods > 0:
                    return True
                else:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ No running Container Insights pods found")
                    return False
        
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking Container Insights: {str(e)}")
                return False

    def _verify_cluster_autoscaler(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Helper method to verify Cluster Autoscaler deployment - FIXED"""
        try:
            # First debug the cluster autoscaler and print detailed debug info
            self.print_colored(Colors.CYAN, "   🔍 Running cluster autoscaler diagnostics...")
            debug_info = self.debug_cluster_autoscaler(cluster_name, region, access_key, secret_key)
        
            # Print the debug info with proper formatting
            self.print_colored(Colors.CYAN, "   📋 Cluster Autoscaler Debug Information:")
        
            if 'error' in debug_info:
                self.print_colored(Colors.RED, f"      ❌ Error: {debug_info['error']}")
            else:
                # Print deployment status
                if debug_info.get('deployment_exists', False):
                    self.print_colored(Colors.GREEN, f"      ✅ Autoscaler deployment exists")
                else:
                    self.print_colored(Colors.YELLOW, f"      ⚠️ Autoscaler deployment not found")
                    if 'deployment_error' in debug_info:
                        self.print_colored(Colors.YELLOW, f"         Error: {debug_info['deployment_error']}")
            
                # Print pod status information
                if debug_info.get('pods_output'):
                    pod_lines = debug_info['pods_output'].strip().split('\n')
                    if len(pod_lines) > 1:  # If there are pods (more than just the header)
                        self.print_colored(Colors.GREEN, f"      ✅ Found {len(pod_lines) - 1} autoscaler pods:")
                        for i, line in enumerate(pod_lines[:4]):  # Show first 4 lines max
                            if i > 0:  # Skip header
                                self.print_colored(Colors.CYAN, f"         {line}")
                        if len(pod_lines) > 5:
                            self.print_colored(Colors.CYAN, f"         ...(and {len(pod_lines) - 5} more)")
                    else:
                        self.print_colored(Colors.YELLOW, f"      ⚠️ No autoscaler pods found")
            
                # Print log sample if available
                if debug_info.get('logs'):
                    log_lines = debug_info['logs'].strip().split('\n')
                    if log_lines and log_lines[0].strip():
                        self.print_colored(Colors.GREEN, f"      ✅ Autoscaler logs available:")
                        for i, line in enumerate(log_lines[:3]):  # Show first 3 log lines
                            if line.strip():
                                self.print_colored(Colors.CYAN, f"         {line[:100]}...")
                        if len(log_lines) > 3:
                            self.print_colored(Colors.CYAN, f"         ...(and {len(log_lines) - 3} more lines)")
                    else:
                        self.print_colored(Colors.YELLOW, f"      ⚠️ No autoscaler logs found")
            
                # Print recent events if available
                if debug_info.get('events'):
                    event_lines = debug_info['events'].strip().split('\n')
                    if len(event_lines) > 1:  # More than just header
                        self.print_colored(Colors.GREEN, f"      ✅ Recent cluster events:")
                        for i, line in enumerate(event_lines[:3]):  # Show first 3 events
                            if i > 0:  # Skip header
                                self.print_colored(Colors.CYAN, f"         {line}")
                        if len(event_lines) > 4:
                            self.print_colored(Colors.CYAN, f"         ...(and {len(event_lines) - 4} more events)")

            # Continue with the original verification code
            import subprocess
            import shutil

            kubectl_available = shutil.which('kubectl') is not None
            if not kubectl_available:
                self.print_colored(Colors.YELLOW, f"   ⚠️ kubectl not found, skipping Cluster Autoscaler check")
                return False
    
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = access_key
            env['AWS_SECRET_ACCESS_KEY'] = secret_key
            env['AWS_DEFAULT_REGION'] = region

            # FIXED: Try multiple label selectors for Cluster Autoscaler
            autoscaler_selectors = [
                'app=cluster-autoscaler',
                'k8s-app=cluster-autoscaler',
                'name=cluster-autoscaler'
            ]
    
            found_autoscaler = False
    
            for selector in autoscaler_selectors:
                try:
                    autoscaler_cmd = ['kubectl', 'get', 'pods', '-n', 'kube-system', '-l', selector, '--no-headers']
                    autoscaler_result = subprocess.run(autoscaler_cmd, env=env, capture_output=True, text=True, timeout=60)
        
                    if autoscaler_result.returncode == 0 and autoscaler_result.stdout.strip():
                        pod_lines = [line.strip() for line in autoscaler_result.stdout.strip().split('\n') if line.strip()]
                        running_pods = [line for line in pod_lines if 'Running' in line]
            
                        if running_pods:
                            found_autoscaler = True
                            self.print_colored(Colors.GREEN, f"   ✅ Cluster Autoscaler pods (selector: {selector}): {len(running_pods)} running")
                    
                            # Show pod details
                            for pod in running_pods[:2]:  # Show first 2 pods
                                pod_parts = pod.split()
                                if len(pod_parts) >= 3:
                                    pod_name = pod_parts[0]
                                    pod_status = pod_parts[2]
                                    self.print_colored(Colors.GREEN, f"      - {pod_name}: {pod_status}")
                            break
                    
                except Exception as e:
                    continue
    
            if not found_autoscaler:
                # FIXED: Try searching by pod name pattern as fallback
                try:
                    all_pods_cmd = ['kubectl', 'get', 'pods', '-n', 'kube-system', '--no-headers']
                    all_pods_result = subprocess.run(all_pods_cmd, env=env, capture_output=True, text=True, timeout=60)
            
                    if all_pods_result.returncode == 0:
                        pod_lines = [line.strip() for line in all_pods_result.stdout.strip().split('\n') if line.strip()]
                        autoscaler_pods = [line for line in pod_lines if 'autoscaler' in line.lower()]
                
                        if autoscaler_pods:
                            running_pods = [line for line in autoscaler_pods if 'Running' in line]
                            if running_pods:
                                found_autoscaler = True
                                self.print_colored(Colors.GREEN, f"   ✅ Cluster Autoscaler pods (by name): {len(running_pods)} running")
                        
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Error searching for autoscaler pods: {str(e)}")
    
            if found_autoscaler:
                # FIXED: Check Cluster Autoscaler service account with better error handling
                try:
                    sa_cmd = ['kubectl', 'get', 'serviceaccount', '-n', 'kube-system', 'cluster-autoscaler', '--no-headers']
                    sa_result = subprocess.run(sa_cmd, env=env, capture_output=True, text=True, timeout=30)
        
                    if sa_result.returncode == 0 and sa_result.stdout.strip():
                        self.print_colored(Colors.GREEN, f"   ✅ Cluster Autoscaler service account verified")
                    else:
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Cluster Autoscaler service account not found (but pods are running)")
                
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Could not verify service account: {str(e)}")
            
                return True
            else:
                self.print_colored(Colors.YELLOW, f"   ⚠️ No running Cluster Autoscaler pods found")
                return False
    
        except Exception as e:
            self.print_colored(Colors.YELLOW, f"   ⚠️ Error checking Cluster Autoscaler: {str(e)}")
            return False

    def enable_container_insights(self, cluster_name: str, region: str, admin_access_key: str, admin_secret_key: str) -> bool:
            """Enable CloudWatch Container Insights for the cluster with FIXED deployment"""
            try:
                self.log_operation('INFO', f"Enabling CloudWatch Container Insights for cluster {cluster_name}")
                self.print_colored(Colors.YELLOW, f"📊 Enabling CloudWatch Container Insights for {cluster_name}...")
    
                # Check if kubectl is available
                import subprocess
                import shutil
    
                kubectl_available = shutil.which('kubectl') is not None
    
                if not kubectl_available:
                    self.log_operation('WARNING', f"kubectl not found. Cannot deploy Container Insights for {cluster_name}")
                    self.print_colored(Colors.YELLOW, f"⚠️  kubectl not found. Container Insights deployment skipped.")
                    return False
    
                # Set environment variables for admin access
                env = os.environ.copy()
                env['AWS_ACCESS_KEY_ID'] = admin_access_key
                env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
                env['AWS_DEFAULT_REGION'] = region
    
                # Update kubeconfig first
                update_cmd = [
                    'aws', 'eks', 'update-kubeconfig',
                    '--region', region,
                    '--name', cluster_name
                ]
    
                self.print_colored(Colors.CYAN, "   🔄 Updating kubeconfig...")
                update_result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
    
                if update_result.returncode != 0:
                    self.log_operation('ERROR', f"Failed to update kubeconfig: {update_result.stderr}")
                    self.print_colored(Colors.RED, f"❌ Failed to update kubeconfig: {update_result.stderr}")
                    return False
    
                # FIXED: Apply Container Insights using the official AWS deployment method
                try:
                    # Create namespace first
                    self.print_colored(Colors.CYAN, "   📦 Creating amazon-cloudwatch namespace...")
                    namespace_cmd = ['kubectl', 'create', 'namespace', 'amazon-cloudwatch']
                    subprocess.run(namespace_cmd, env=env, capture_output=True, text=True, timeout=60)
                    self.log_operation('INFO', f"Created amazon-cloudwatch namespace")
                except:
                    # Namespace might already exist
                    self.log_operation('INFO', f"amazon-cloudwatch namespace already exists or failed to create")
    
                # FIXED: Apply Container Insights using direct AWS command
                self.print_colored(Colors.CYAN, "   🚀 Deploying Container Insights...")
        
                try:
                    # Use AWS CLI to deploy Container Insights (more reliable)
                    insights_cmd = [
                        'aws', 'eks', 'create-addon',
                        '--cluster-name', cluster_name,
                        '--addon-name', 'amazon-cloudwatch-observability',
                        '--region', region,
                        '--resolve-conflicts', 'OVERWRITE'
                    ]
            
                    insights_result = subprocess.run(insights_cmd, env=env, capture_output=True, text=True, timeout=300)
            
                    if insights_result.returncode == 0:
                        self.print_colored(Colors.GREEN, "   ✅ Container Insights add-on deployed via AWS CLI")
                        self.log_operation('INFO', f"Container Insights add-on deployed for {cluster_name}")
                
                        # Wait for addon to be active
                        self.print_colored(Colors.CYAN, "   ⏳ Waiting for Container Insights add-on to be active...")
                        time.sleep(30)
                
                        return True
                    else:
                        # Fallback to manual deployment if add-on fails
                        self.print_colored(Colors.YELLOW, f"   ⚠️ Add-on deployment failed, trying manual deployment...")
                        return self._deploy_container_insights_manual(cluster_name, region, env)
                
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Add-on deployment error: {str(e)}, trying manual deployment...")
                    return self._deploy_container_insights_manual(cluster_name, region, env)
    
            except Exception as e:
                error_msg = str(e)
                self.log_operation('ERROR', f"Failed to enable Container Insights for {cluster_name}: {error_msg}")
                self.print_colored(Colors.RED, f"❌ Container Insights deployment failed: {error_msg}")
                return False

    def _deploy_container_insights_manual(self, cluster_name: str, region: str, env: dict) -> bool:
            """Manual deployment of Container Insights using kubectl - FIXED"""
            try:
                import subprocess
        
                self.print_colored(Colors.CYAN, "   📋 Applying Container Insights manifests manually...")
        
                # FIXED: Use the correct Container Insights manifests
                manifests = [
                    f"https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/cloudwatch-namespace.yaml",
                    f"https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/fluent-bit/fluent-bit-cluster-info-configmap.yaml",
                    f"https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/fluent-bit/fluent-bit-configmap.yaml",
                    f"https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/fluent-bit/fluent-bit.yaml"
                ]
        
                success_count = 0
        
                for i, manifest_url in enumerate(manifests, 1):
                    try:
                        self.print_colored(Colors.CYAN, f"   📦 Applying manifest {i}/{len(manifests)}...")
                
                        if 'fluent-bit-cluster-info-configmap.yaml' in manifest_url:
                            # FIXED: Download and patch cluster info configmap
                            import requests
                            import tempfile
                    
                            response = requests.get(manifest_url, timeout=30)
                            if response.status_code == 200:
                                # Replace placeholders
                                patched_manifest = response.text.replace("{{cluster_name}}", cluster_name)
                                patched_manifest = patched_manifest.replace("{{region_name}}", region)
                                patched_manifest = patched_manifest.replace("{{http_server_toggle}}", "On")
                                patched_manifest = patched_manifest.replace("{{http_server_port}}", "2020")
                                patched_manifest = patched_manifest.replace("{{read_from_head}}", "Off")
                                patched_manifest = patched_manifest.replace("{{read_from_tail}}", "On")
                        
                                # Save to temp file and apply
                                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                                    f.write(patched_manifest)
                                    temp_file = f.name
                        
                                try:
                                    apply_cmd = ['kubectl', 'apply', '-f', temp_file]
                                    apply_result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=120)
                                finally:
                                    os.unlink(temp_file)
                            else:
                                continue
                        
                        elif 'fluent-bit-configmap.yaml' in manifest_url:
                            # FIXED: Download and patch fluent-bit configmap
                            patched_path = self.download_and_patch_fluentbit_config(manifest_url, cluster_name)
                            apply_cmd = ['kubectl', 'apply', '-f', patched_path]
                            apply_result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=120)
                            self.cleanup_temp_file(patched_path)
                        else:
                            # Apply manifest directly
                            apply_cmd = ['kubectl', 'apply', '-f', manifest_url]
                            apply_result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=120)
                
                        if apply_result.returncode == 0:
                            success_count += 1
                            self.log_operation('INFO', f"Applied manifest: {manifest_url}")
                        else:
                            self.log_operation('WARNING', f"Failed to apply manifest {manifest_url}: {apply_result.stderr}")
                    
                    except Exception as e:
                        self.log_operation('WARNING', f"Failed to apply manifest {manifest_url}: {str(e)}")
        
                # FIXED: Wait longer for pods to be created and check status
                self.print_colored(Colors.CYAN, "   ⏳ Waiting for Container Insights pods to start...")
                time.sleep(45)  # Increased wait time
        
                if success_count >= 2:  # At least 2 manifests applied successfully
                    self.print_colored(Colors.GREEN, f"   ✅ Container Insights deployed manually ({success_count}/{len(manifests)} manifests applied)")
            
                    # Verify deployment
                    verify_result = self.verify_cloudwatch_insights(cluster_name, region, env.get('AWS_ACCESS_KEY_ID', ''), env.get('AWS_SECRET_ACCESS_KEY', ''))
            
                    if verify_result:
                        self.print_colored(Colors.CYAN, f"📊 Access Container Insights in AWS Console:")
                        self.print_colored(Colors.CYAN, f"   CloudWatch → Insights → Container Insights")
                        self.print_colored(Colors.CYAN, f"   Filter by cluster: {cluster_name}")
            
                    return True
                else:
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Container Insights deployment incomplete ({success_count}/{len(manifests)} manifests applied)")
                    return False
            
            except Exception as e:
                self.log_operation('ERROR', f"Manual Container Insights deployment failed: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Manual deployment failed: {str(e)}")
                return False
    
    def generate_instance_tags(self, cluster_name: str, nodegroup_name: str, strategy: str) -> Dict:
        """Generate comprehensive tags for EC2 instances in nodegroup"""
        short_name = self.generate_short_name(cluster_name, nodegroup_name)
        self.log_operation('DEBUG', f"Generating instance tags for {short_name} in cluster {cluster_name} with strategy {strategy}")
        if not short_name or not short_name.strip():
            short_name = f"eks-{nodegroup_name}-instance"

        return {
            'Name': short_name,
            'kubernetes.io/cluster/' + cluster_name: 'owned',
            'k8s.io/cluster-autoscaler/enabled': 'true',
            'k8s.io/cluster-autoscaler/' + cluster_name: 'owned',
            'ClusterName': cluster_name,
            'NodegroupName': nodegroup_name,
            'Strategy': strategy,
            'CreatedBy': self.current_user,
            'CreatedAt': self.current_time,
            'Environment': 'EKS',
            'AutoScaling': 'enabled',
            'Project': 'EKS-Infrastructure'
        }

    def log_operation(self, level: str, message: str):
        """Basic logger for EKSClusterManager"""
        print(f"[{level}] {message}")


########

    def create_cluster(self, config: Dict) -> bool:
        """
        Create EKS cluster with nodegroups based on provided configuration.
        Prompts for add-ons, Container Insights, and nodegroup strategies before cluster creation.

        Args:
            config: Dictionary containing cluster configuration

        Returns:
            bool: True if cluster creation was successful, False otherwise
        """
        try:
            # Extract configuration parameters
            nodegroup_configs = config.get('nodegroup_configs', None)
            self.debug_nodegroup_configs("create_cluster input", nodegroup_configs)
            cluster_name = config.get('cluster_name')
            region = config.get('region', 'us-east-1')
            access_key = config.get('access_key', '')
            secret_key = config.get('secret_key', '')
            account_id = config.get('account_id', '')
            account_name = config.get('account_name', '')
            username = config.get('username', 'unknown')

            # Log cluster creation start
            self.log_operation('INFO', f"Starting creation of cluster {cluster_name} in {region}")
            self.print_colored(Colors.YELLOW, f"\n🚀 Creating EKS cluster: {cluster_name}")
            self.print_colored(Colors.YELLOW, f"   Region: {region}")
            self.print_colored(Colors.YELLOW, f"   Account: {account_name} ({account_id})")
            self.print_colored(Colors.YELLOW, f"   User: {username}")

            # Check if nodegroup configuration is already provided
            nodegroup_configs = config.get('nodegroup_configs', None)
            self.log_operation('DEBUG', f"Received nodegroup_configs in create_cluster: {nodegroup_configs}")

            # Skip interactive configuration if nodegroup_configs are already provided
            if not nodegroup_configs:
                # Step 1: Interactive configuration prompts
                print("\n" + "="*60)
                print("💻 CLUSTER CONFIGURATION")
                print("="*60)
    
                # 1.1 Ask for nodegroup strategy
                print("\n🔄 Nodegroup Strategy Selection:")
                print("1. On-demand (reliable, consistent performance, higher cost)")
                print("2. Spot (cheaper, but can be terminated, best for non-critical workloads)")
                print("3. Mixed (combination of on-demand and spot for balance)")
    
                default_strategy = config.get('strategy', 'on-demand')
                default_choice = "1" if default_strategy == "on-demand" else "2" if default_strategy == "spot" else "3"
    
                while True:
                    strategy_choice = input(f"Select nodegroup strategy (1-3) [default: {default_choice}]: ").strip()
                    if not strategy_choice:
                        strategy_choice = default_choice
        
                    if strategy_choice == "1":
                        strategy = "on-demand"
                        break
                    elif strategy_choice == "2":
                        strategy = "spot"
                        break
                    elif strategy_choice == "3":
                        strategy = "mixed"
                        break
                    else:
                        print("❌ Invalid choice. Please enter 1, 2, or 3.")
    
                self.print_colored(Colors.GREEN, f"✅ Selected nodegroup strategy: {strategy.upper()}")
    
                # 1.2 Select instance type
                instance_type = self.select_instance_type(username)
    
                # 1.3 Configure nodegroup sizing
                print("\n🔢 Nodegroup Sizing:")
                default_min = config.get('min_size', 1)
                default_desired = config.get('desired_size', 1)
                default_max = config.get('max_size', 3)
    
                try:
                    min_size = int(input(f"Minimum nodes [default: {default_min}]: ").strip() or default_min)
                    desired_size = int(input(f"Desired nodes [default: {default_desired}]: ").strip() or default_desired)
                    max_size = int(input(f"Maximum nodes [default: {default_max}]: ").strip() or default_max)
        
                    # Validate values
                    if min_size < 0 or desired_size < 0 or max_size < 0:
                        print("❌ Negative values are not allowed. Using defaults.")
                        min_size, desired_size, max_size = default_min, default_desired, default_max
        
                    if min_size > desired_size or desired_size > max_size:
                        print("❌ Invalid values (should be min ≤ desired ≤ max). Adjusting...")
                        max_size = max(max_size, desired_size, min_size)
                        min_size = min(min_size, desired_size)
                        desired_size = max(min_size, min(desired_size, max_size))
        
                except ValueError:
                    print("❌ Invalid number format. Using defaults.")
                    min_size, desired_size, max_size = default_min, default_desired, default_max
    
                self.print_colored(Colors.GREEN, f"✅ Nodegroup sizing: Min={min_size}, Desired={desired_size}, Max={max_size}")
    
                # 1.4 For mixed strategy, ask for on-demand percentage
                instance_selections = {}
                if strategy == 'mixed':
                    print("\n📊 Mixed Strategy Configuration:")
                    default_percentage = 30
                    try:
                        on_demand_percentage = int(input(f"Percentage of On-Demand capacity (0-100) [default: {default_percentage}%]: ").strip() or default_percentage)
                        if on_demand_percentage < 0 or on_demand_percentage > 100:
                            print("❌ Percentage must be between 0 and 100. Using default.")
                            on_demand_percentage = default_percentage
                    except ValueError:
                        print("❌ Invalid number format. Using default percentage.")
                        on_demand_percentage = default_percentage
        
                    # Create instance selections for mixed strategy
                    instance_selections = {
                        'on-demand': [instance_type],
                        'spot': self.get_diversified_instance_types(instance_type),
                        'on_demand_percentage': on_demand_percentage
                    }
        
                    self.print_colored(Colors.GREEN, f"✅ Mixed strategy: {on_demand_percentage}% On-Demand, {100-on_demand_percentage}% Spot")
        
                elif strategy == 'spot':
                    # Use diversified instance types for better spot availability
                    instance_selections = {
                        'spot': self.get_diversified_instance_types(instance_type)
                    }
                    spot_types = ', '.join(instance_selections['spot'])
                    self.print_colored(Colors.GREEN, f"✅ Spot instance types: {spot_types}")
        
                elif strategy == 'on-demand':
                    print("\n💻 On-Demand Instance Configuration:", instance_type)
                    instance_selections = {
                        'on-demand': [instance_type]
                    }

    
                # 1.5 Subnet preference
                print("\n🌐 Subnet Preference:")
                print("1. Auto (use all available subnets)")
                print("2. Public (prefer public subnets)")
                print("3. Private (prefer private subnets)")
    
                default_subnet = "1"
                subnet_choice = input(f"Select subnet preference (1-3) [default: {default_subnet}]: ").strip()
                if not subnet_choice:
                    subnet_choice = default_subnet
        
                if subnet_choice == "1":
                    subnet_preference = "auto"
                elif subnet_choice == "2":
                    subnet_preference = "public"
                elif subnet_choice == "3":
                    subnet_preference = "private"
                else:
                    subnet_preference = "auto"
        
                self.print_colored(Colors.GREEN, f"✅ Subnet preference: {subnet_preference.upper()}")
    
                # Create a single nodegroup config
                nodegroup_name = self.generate_nodegroup_name(cluster_name, strategy)
                nodegroup_configs = [{
                    'name': nodegroup_name,
                    'strategy': strategy,
                    'min_nodes': min_size,
                    'desired_nodes': desired_size,
                    'max_nodes': max_size,
                    'instance_selections': instance_selections,
                    'subnet_preference': subnet_preference
                }]
    
                # Update config with the created nodegroup config
                config['nodegroup_configs'] = nodegroup_configs
                self.log_operation('DEBUG', f"Generated nodegroup_configs: {nodegroup_configs}")
    
                # 1.6 Ask for add-ons and Container Insights
                if not hasattr(self, 'setup_addons') or not hasattr(self, 'setup_container_insights'):
                    # Ask once and store for all future cluster creations
                    print("\n" + "="*60)
                    print("📦 CLUSTER ADD-ONS CONFIGURATION")
                    print("="*60)
                    self.setup_addons = config.get('install_addons', True)
                    self.setup_container_insights = config.get('enable_container_insights', True)
        
                    if self.setup_addons:
                        self.print_colored(Colors.GREEN, "✅ Essential add-ons will be installed")
                    else:
                        self.print_colored(Colors.YELLOW, "⚠️ Essential add-ons will NOT be installed")
            
                    if self.setup_container_insights:
                        self.print_colored(Colors.GREEN, "✅ CloudWatch Container Insights will be enabled")
                    else:
                        self.print_colored(Colors.YELLOW, "⚠️ CloudWatch Container Insights will NOT be enabled")
    
                # Display cost estimation based on selected configuration
                for ng_config in nodegroup_configs:
                    # Get primary instance type
                    if ng_config['strategy'] == 'on-demand':
                        primary_instance = ng_config['instance_selections'].get('on-demand', [instance_type])[0]
                    elif ng_config['strategy'] == 'spot':
                        primary_instance = ng_config['instance_selections'].get('spot', [instance_type])[0]
                    else:
                        primary_instance = ng_config['instance_selections'].get('on-demand', [instance_type])[0]
        
                    self.display_cost_estimation(primary_instance, ng_config['strategy'], ng_config['desired_nodes'])
            else:
                # We already have nodegroup configs (likely from multi-nodegroup workflow)
                # Just extract the key data we need for further processing
                self.log_operation('INFO', f"Using existing nodegroup_configs: {nodegroup_configs}")
                strategy = nodegroup_configs[0]['strategy']  # Use the strategy from the first nodegroup

            # Final confirmation
            print("\n" + "="*60)
            print("🚀 CLUSTER CREATION SUMMARY")
            print("="*60)
            print(f"Cluster Name: {cluster_name}")
            print(f"Region: {region}")

            # Display each nodegroup configuration
            for i, ng_config in enumerate(nodegroup_configs, 1):
                print(f"\nNodegroup {i}: {ng_config['name']}")
                print(f"Strategy: {ng_config['strategy'].upper()}")
                print(f"Scaling: Min={ng_config['min_nodes']}, Desired={ng_config['desired_nodes']}, Max={ng_config['max_nodes']}")
    
                # Display instance type information
                if ng_config['strategy'] == 'mixed':
                    on_demand_types = ng_config['instance_selections'].get('on-demand', ['Not specified'])
                    spot_types = ng_config['instance_selections'].get('spot', ['Not specified'])
                    on_demand_percentage = ng_config['instance_selections'].get('on_demand_percentage', 50)
                    print(f"Mixed Strategy: {on_demand_percentage}% On-Demand, {100-on_demand_percentage}% Spot")
                    print(f"Instance Types: On-Demand: {', '.join(on_demand_types)}, Spot: {', '.join(spot_types)}")
                elif ng_config['strategy'] == 'spot':
                    spot_types = ng_config['instance_selections'].get('spot', ['Not specified'])
                    print(f"Spot Instance Types: {', '.join(spot_types)}")
                else:
                    on_demand_types = ng_config['instance_selections'].get('on-demand', ['Not specified'])
                    print(f"On-Demand Instance Types: {', '.join(on_demand_types)}")
    
                print(f"Subnet Preference: {ng_config['subnet_preference'].upper()}")

            confirmation = 'Y'  # Default to 'Y' for confirmation
            #confirmation = input("\nConfirm cluster creation with these settings? (Y/n): ").strip().lower()
            if confirmation == 'n':
                self.print_colored(Colors.YELLOW, "❌ Cluster creation cancelled by user")
                return False

            # Step 2: Create AWS session and clients
            self.log_operation('INFO', f"Creating AWS session for region {region}")
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            eks_client = session.client('eks')
            ec2_client = session.client('ec2')
            iam_client = session.client('iam')
            sts_client = session.client('sts')

            # Verify account ID if not provided
            if not account_id:
                account_id = sts_client.get_caller_identity()['Account']
                self.log_operation('INFO', f"Detected Account ID: {account_id}")

            # Step 3: Ensure IAM roles exist
            self.print_colored(Colors.CYAN, "   🔐 Setting up IAM roles...")
            eks_role_arn, node_role_arn = self.ensure_iam_roles(iam_client, account_id)

            # Step 4: Get or create VPC resources
            self.print_colored(Colors.CYAN, "   🌐 Setting up networking resources...")
            subnet_ids, security_group_id = self.get_or_create_vpc_resources(ec2_client, region)

            # Step 5: Create EKS control plane
            self.print_colored(Colors.CYAN, f"   🚀 Creating EKS control plane {cluster_name}...")

            # Set default EKS version - adjust based on your requirements
            eks_version = config.get('eks_version', '1.28')

            # Create control plane with proper error handling and logging
            try:
                # Check if cluster already exists
                try:
                    eks_client.describe_cluster(name=cluster_name)
                    cluster_exists = True
                    self.log_operation('INFO', f"Cluster {cluster_name} already exists")
                    self.print_colored(Colors.YELLOW, f"   ⚠️ Cluster {cluster_name} already exists, skipping creation")
                except eks_client.exceptions.ResourceNotFoundException:
                    cluster_exists = False
    
                if not cluster_exists:
                    # Create the EKS cluster control plane
                    self.log_operation('INFO', f"Creating EKS control plane {cluster_name} with version {eks_version}")
        
                    eks_client.create_cluster(
                        name=cluster_name,
                        version=eks_version,
                        roleArn=eks_role_arn,
                        resourcesVpcConfig={
                            'subnetIds': subnet_ids,
                            'securityGroupIds': [security_group_id],
                            'endpointPublicAccess': True,
                            'endpointPrivateAccess': True,
                            'publicAccessCidrs': ['0.0.0.0/0']
                        },
                        logging={
                            'clusterLogging': [
                                {
                                    'types': ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
                                    'enabled': True
                                }
                            ]
                        },
                        tags=self.generate_instance_tags(cluster_name, "control-plane", "managed")
                    )
        
                    # Wait for cluster to be active
                    self.print_colored(Colors.CYAN, f"   ⏳ Waiting for cluster {cluster_name} to be active...")
                    waiter = eks_client.get_waiter('cluster_active')
                    waiter.wait(
                        name=cluster_name,
                        WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                    )
        
                    self.print_colored(Colors.GREEN, f"   ✅ EKS control plane {cluster_name} is now active")
                    self.log_operation('INFO', f"EKS control plane {cluster_name} created successfully")

            except Exception as e:
                self.log_operation('ERROR', f"Failed to create EKS control plane {cluster_name}: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Failed to create EKS control plane: {str(e)}")
                return False

            # Step 6: Configure Auth ConfigMap for user access
            self.print_colored(Colors.CYAN, "   🔑 Configuring user access...")
            auth_configured = self.configure_aws_auth_configmap(
                cluster_name, region, account_id, config, access_key, secret_key
            )

            # auth_configured = self.enable_cluster_access_modes(cluster_name, region, account_id, config,
            #                                                    admin_access_key, admin_secret_key)

            # Step 7: Create nodegroups based on strategy
            self.print_colored(Colors.CYAN, f"   🚀 Creating nodegroups with {strategy} strategy...")

            # Generate nodegroup name
            ami_type = config.get('ami_type', 'AL2_x86_64')  # Amazon Linux 2 x86_64
            key_name = self.eks_ssh_keypair_name
            ec2_key_name = self.ensure_ec2_key_pair(ec2_client, key_name)

            # Create nodegroup(s) based on strategy
            nodegroups_created = []
            try:
                for ng_config in nodegroup_configs:
                    self.log_operation('INFO', f"Creating nodegroup with config: {ng_config}")
            
                    strategy = ng_config['strategy']
                    nodegroup_name = ng_config['name']
                    min_size = ng_config['min_nodes']
                    desired_size = ng_config['desired_nodes']
                    max_size = ng_config['max_nodes']
                    instance_selections = ng_config['instance_selections']
            
                    # Select subnet IDs based on preference
                    subnet_preference = ng_config.get('subnet_preference', 'auto')
                    selected_subnets = self.select_subnets_for_nodegroup(subnet_ids, subnet_preference, ec2_client)
            
                    self.log_operation('INFO', f"Creating nodegroup {nodegroup_name} with strategy {strategy}")
            
                    if strategy == 'on-demand':
                        success = self.create_ondemand_nodegroup(
                            eks_client, cluster_name, nodegroup_name, node_role_arn, selected_subnets,
                            ami_type, instance_selections.get('on-demand', ["c6a.large"]), min_size, desired_size, max_size, ec2_key_name
                        )
                        if success:
                            nodegroups_created.append(nodegroup_name)
                
                    elif strategy == 'spot':
                        # print in red color big log
                        success = self.create_spot_nodegroup(
                            eks_client, cluster_name, nodegroup_name, node_role_arn, selected_subnets,
                            ami_type, instance_selections.get('spot', ["c6a.large"]), 
                            min_size, desired_size, max_size, ec2_key_name
                        )
                        if success:
                            nodegroups_created.append(nodegroup_name)
                
                    elif strategy == 'mixed':
                        success = self.create_mixed_nodegroup(
                            eks_client, cluster_name, nodegroup_name, node_role_arn, selected_subnets,
                            ami_type, instance_selections, min_size, desired_size, max_size, ec2_key_name
                        )
                        if success:
                            # For mixed strategy, we'll have two nodegroups
                            nodegroups_created.append(f"{nodegroup_name}-ondemand")
                            nodegroups_created.append(f"{nodegroup_name}-spot")
        
                if not nodegroups_created:
                    self.log_operation('ERROR', f"Failed to create nodegroups for cluster {cluster_name}")
                    self.print_colored(Colors.RED, f"❌ Nodegroup creation failed")
                    return False
        
                self.log_operation('INFO', f"Successfully created nodegroups: {', '.join(nodegroups_created)}")
    
            except Exception as e:
                self.log_operation('ERROR', f"Failed to create nodegroups: {str(e)}")
                self.print_colored(Colors.RED, f"❌ Failed to create nodegroups: {str(e)}")
                return False

            # Step 8: Verify user access to the cluster
            print("\n🔒 Step 8: Verify user access...")
            self.print_colored(Colors.CYAN, "   🔍 Verifying user access...")
            access_verified = self.verify_user_access(
                cluster_name, region, username, access_key, secret_key
            )

            # Step 9: Ensure only one node per nodegroup always NO_DELETE label using lambda function
            print("\n🔒 Step 9: Ensure only one node per nodegroup always NO_DELETE label using lambda function...")

            # Apply initial node protection
            self.print_colored(Colors.YELLOW, f"\n🔒 Setting up initial node protection...")
            protection_result = self.apply_no_delete_to_matching_nodegroups(
                cluster_name, region, access_key, secret_key
            )

            self.print_colored(Colors.CYAN, f"   📋 Ensuring only one node per nodegroup has NO_DELETE label...")
            self.protect_nodes_with_no_delete_label(cluster_name, region, access_key, secret_key)

            nodegroup_names = nodegroups_created

            if protection_result.get('success'):
                self.print_colored(Colors.GREEN, f"✅ Initial node protection applied")

                # Setup automated monitoring
                self.print_colored(Colors.YELLOW, f"\n⏰ Setting up automated node protection monitoring...")
                monitoring_setup = self.setup_node_protection_monitoring(
                    cluster_name, region, access_key, secret_key, nodegroup_names
                )

                if monitoring_setup:
                    self.print_colored(Colors.GREEN, f"✅ Automated node protection monitoring enabled")
                    self.print_colored(Colors.CYAN, f"   📋 Lambda will run every time a ec2 is terminated to ensure node protection")
                else:
                    self.print_colored(Colors.YELLOW,
                                       f"⚠️ Automated monitoring setup failed - manual monitoring required")

            # Step 10: Install essential add-ons if confirmed by user
            print("\n🔒 Step 10: Setting up add ons...")
            if self.setup_addons:
                self.print_colored(Colors.CYAN, "   📦 Installing essential add-ons...")
                addons_installed = self.install_essential_addons(
                    eks_client, cluster_name, region, access_key, secret_key, account_id
                )
                self.log_operation('INFO', f"Essential add-ons installation {'successful' if addons_installed else 'failed'}")
            else:
                addons_installed = False
                self.log_operation('INFO', "Essential add-ons installation skipped by user")

            # Step 11: Set up and verify all components
            print("\n🔒 Step 11: Setting up and Verify all components...")
            components_status = self.setup_and_verify_all_components(
                cluster_name, region, access_key, secret_key, account_id, nodegroups_created,self.setup_container_insights
            )

            # print("\n🔒 Step 12: disable public access to eks control plane and use only private access...")
            # # Disable public access - using the same eks_client
            # self.log_operation('INFO', "Disabling public access for the EKS control plane...")
            # if self.disable_public_access(eks_client, cluster_name):
            #     self.log_operation('SUCCESS', "Successfully disabled public access for EKS control plane")


            # Step 13: Perform health check
            print("\n🔒 Step 13: Peform cluster health check...")
            self.print_colored(Colors.CYAN, "   🏥 Running health check...")
            initial_health_check = self.health_check_cluster(
                cluster_name, region, access_key, secret_key
            )

            # Save cluster details for future use
            features_status = {
                'eks_version': eks_version,
                'ami_type': ami_type,
                'nodegroups_created': nodegroups_created,
                'nodegroup_configs': nodegroup_configs,  # Store full nodegroup configs
                'addons_installed': addons_installed,
                'container_insights_enabled': components_status.get('container_insights', False),
                'autoscaler_enabled': components_status.get('cluster_autoscaler', False),
                'scheduled_scaling_enabled': components_status.get('scheduled_scaling', False),
                'cloudwatch_agent_enabled': components_status.get('cloudwatch_agent', False),
                'cloudwatch_alarms_enabled': components_status.get('cloudwatch_alarms', False),
                'cost_alarms_enabled': components_status.get('cost_alarms', False),
                'auth_configured': auth_configured,
                'access_verified': access_verified,
                'initial_health_check': initial_health_check,
                'no_delete_label_applied': components_status['node_protection']['enabled'],
                'no_delete_lamba_monitoring': components_status['node_protection']['monitoring_setup']
            }

            # Create credential info for saving cluster details
            credential_info = CredentialInfo(
                account_name=account_name,
                account_id=account_id,
                email=config.get('email', 'unknown'),
                access_key=access_key,
                secret_key=secret_key,
                credential_type='unknown',
                regions=[region],
                username=username
            )

            # Save cluster details to file
            self.save_cluster_details_enhanced(
                credential_info, cluster_name, region, eks_version, ami_type, nodegroup_configs, features_status
            )

            # Generate user instructions
            self.generate_user_instructions_enhanced(
                credential_info, cluster_name, region, username, nodegroup_configs
            )

            # Generate mini instructions for quick reference
            self.generate_mini_instructions(credential_info, cluster_name, region, username)

            # Print enhanced cluster summary
            self.print_enhanced_cluster_summary_multi_nodegroup(cluster_name, features_status)

            # Log successful cluster creation
            self.log_operation('INFO', f"Successfully created and configured cluster {cluster_name}")
            return True

        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to create cluster {config.get('cluster_name', 'unknown')}: {error_msg}")
            self.print_colored(Colors.RED, f"❌ Cluster creation failed: {error_msg}")

            # Get full stack trace for debugging
            import traceback
            self.log_operation('ERROR', f"Stack trace: {traceback.format_exc()}")
            return False

    def ensure_single_no_delete_per_nodegroup(cluster_name, region, access_key, secret_key):
        """
        Ensures only one node per selected nodegroup has the NO_DELETE label.
        Only nodegroups matching the specified patterns are considered.
        """
        env = os.environ.copy()
        env['AWS_ACCESS_KEY_ID'] = access_key
        env['AWS_SECRET_ACCESS_KEY'] = secret_key
        env['AWS_DEFAULT_REGION'] = region

        # 1. List all nodegroups
        result = subprocess.run([
            'aws', 'eks', 'list-nodegroups',
            '--cluster-name', cluster_name,
            '--region', region
        ], capture_output=True, text=True, check=True, env=env)
        all_nodegroups = json.loads(result.stdout).get('nodegroups', [])

        # 2. Pattern matching logic
        primary_pattern = re.compile(r'^nodegroup-[0-9]-ondemand$')
        matching_nodegroups = [ng for ng in all_nodegroups if primary_pattern.match(ng)]

        if not matching_nodegroups:
            secondary_pattern = re.compile(r'^nodegroup-[0-9]-.*$')
            matching_nodegroups = [ng for ng in all_nodegroups if secondary_pattern.match(ng)]

        if not matching_nodegroups:
            fallback_pattern = re.compile(r'^nodegroup-.*$')
            matching_nodegroups = [ng for ng in all_nodegroups if fallback_pattern.match(ng)]
            if len(matching_nodegroups) > 1:
                print(
                    f"⚠️ Multiple nodegroups found with pattern 'nodegroup-*'. Selecting the first one: {matching_nodegroups[0]}")
                matching_nodegroups = [matching_nodegroups[0]]

        if not matching_nodegroups:
            print("No matching nodegroups found.")
            return

        # 3. Update kubeconfig
        subprocess.run([
            'aws', 'eks', 'update-kubeconfig',
            '--region', region,
            '--name', cluster_name
        ], check=True, capture_output=True, env=env)

        # 4. Get all nodes and their labels
        result = subprocess.run([
            'kubectl', 'get', 'nodes', '-o', 'json'
        ], capture_output=True, text=True, check=True, env=env)
        nodes = json.loads(result.stdout)['items']

        # 5. Group nodes by nodegroup, but only for matching nodegroups
        nodegroups = {}
        for node in nodes:
            node_name = node['metadata']['name']
            labels = node['metadata'].get('labels', {})
            nodegroup = labels.get('eks.amazonaws.com/nodegroup')
            if not nodegroup or nodegroup not in matching_nodegroups:
                continue
            nodegroups.setdefault(nodegroup, []).append({
                'name': node_name,
                'has_no_delete': labels.get('NO_DELETE') == 'true'
            })

        # 6. For each matching nodegroup, ensure only one node has NO_DELETE
        for ng, nodes in nodegroups.items():
            nodes_with_label = [n for n in nodes if n['has_no_delete']]
            nodes_without_label = [n for n in nodes if not n['has_no_delete']]

            # Remove label from extra nodes if more than one has it
            if len(nodes_with_label) > 1:
                for n in nodes_with_label[1:]:
                    subprocess.run([
                        'kubectl', 'label', 'node', n['name'], 'NO_DELETE-', '--overwrite'
                    ], check=True, env=env)
            # Add label if none has it
            if len(nodes_with_label) == 0 and nodes_without_label:
                n = nodes_without_label[0]
                subprocess.run([
                    'kubectl', 'label', 'node', n['name'], 'NO_DELETE=true', '--overwrite'
                ], check=True, env=env)

    def create_multiple_clusters(self, cluster_configs: List[Dict]) -> bool:
        """Create multiple clusters with shared configuration and enhanced error handling"""
        if not cluster_configs:
            self.logger.warning("No clusters configured to create")
            return False
    
        # Initialize tracking structures
        created_clusters = []
        failed_clusters = []
        error_details = {}  # Store detailed error info for each failed cluster
    
        # Get shared configuration once
        self.logger.info(f"Starting batch creation of {len(cluster_configs)} clusters")
    
        # Show summary before proceeding
        self.logger.info("Cluster creation summary:")
        for i, config in enumerate(cluster_configs, 1):
            cluster_name = config.get('cluster_name', 'unnamed')
            username = config.get('username', 'unknown')
            region = config.get('region', 'unknown')
            self.logger.info(f"  {i}. {cluster_name} - Region: {region}, User: {username}")
    
        # Create all clusters with shared configuration
        total_clusters = len(cluster_configs)
        print(f"\n🚀 Starting creation of {total_clusters} clusters...")
    
        for i, config in enumerate(cluster_configs, 1):
            cluster_name = config.get('cluster_name', 'unnamed')
            username = config.get('username', 'unknown')
            region = config.get('region', 'unknown')
        
            self.logger.info(f"[{i}/{total_clusters}] Creating cluster {cluster_name} for {username} in {region}")
            print(f"\n[{i}/{total_clusters}] 🚀 Creating cluster {cluster_name} for {username}...")
        
            try:
                # Create structured log entry for start of cluster creation
                self.logger.info(json.dumps({
                    "event": "cluster_creation_start", 
                    "cluster_name": cluster_name,
                    "username": username,
                    "region": region,
                    "strategy": config.get('strategy', 'unknown'),
                    "min_size": config.get('min_size', 0),
                    "desired_size": config.get('desired_size', 0),
                    "max_size": config.get('max_size', 0)
                }))
            
                # Call existing create_cluster method
                result = self.create_cluster(config)
            
                if result:
                    created_clusters.append(cluster_name)
                    self.logger.info(json.dumps({
                        "event": "cluster_creation_success", 
                        "cluster_name": cluster_name,
                        "username": username
                    }))
                else:
                    failed_clusters.append(cluster_name)
                    error_message = "Create cluster method returned False"
                    error_details[cluster_name] = error_message
                    self.logger.error(json.dumps({
                        "event": "cluster_creation_failure", 
                        "cluster_name": cluster_name,
                        "username": username,
                        "error": error_message
                    }))
                
            except Exception as e:
                failed_clusters.append(cluster_name)
                error_msg = str(e)
                error_details[cluster_name] = error_msg
            
                # Log the full stack trace for debugging
                import traceback
                stack_trace = traceback.format_exc()
                self.logger.error(json.dumps({
                    "event": "cluster_creation_exception", 
                    "cluster_name": cluster_name,
                    "username": username,
                    "error": error_msg,
                    "stack_trace": stack_trace
                }))
            
                self.print_colored(Colors.RED, f"❌ Error creating cluster {cluster_name}: {error_msg}")
            
                # Ask if user wants to continue with remaining clusters
                if i < total_clusters:
                    continue_choice = input(f"\n⚠️ Failed to create cluster {cluster_name}. Continue with remaining {total_clusters - i} clusters? (y/N): ").strip().lower()
                    if continue_choice not in ['y', 'yes']:
                        self.logger.warning(f"Batch creation aborted by user after failure of {cluster_name}")
                        break
    
        # Generate and log final summary
        success_rate = len(created_clusters) / total_clusters * 100 if total_clusters > 0 else 0
    
        summary = {
            "event": "batch_creation_summary",
            "total_clusters": total_clusters,
            "successful": len(created_clusters),
            "failed": len(failed_clusters),
            "success_rate_percent": round(success_rate, 2),
            "created_clusters": created_clusters,
            "failed_clusters": {cluster: error_details.get(cluster, "Unknown error") for cluster in failed_clusters}
        }
    
        self.logger.info(json.dumps(summary))
    
        # Print final summary
        print("\n" + "=" * 60)
        print("📋 BATCH CREATION SUMMARY")
        print("=" * 60)
        print(f"Total clusters: {total_clusters}")
        print(f"Successfully created: {len(created_clusters)} ({success_rate:.1f}%)")
        print(f"Failed: {len(failed_clusters)} ({100-success_rate:.1f}%)")
    
        if created_clusters:
            self.print_colored(Colors.GREEN, "\n✅ Successfully created clusters:")
            for cluster in created_clusters:
                print(f"   - {cluster}")
    
        if failed_clusters:
            self.print_colored(Colors.RED, "\n❌ Failed clusters:")
            for cluster in failed_clusters:
                error = error_details.get(cluster, "Unknown error")
                print(f"   - {cluster}: {error}")
    
        # Save error details to a report file
        if failed_clusters:
            try:
                log_dir = "aws/eks"
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                report_file = os.path.join(log_dir, f"cluster_creation_errors_{self.execution_timestamp}.json")
                error_report = {
                    "timestamp": datetime.now().isoformat(),
                    "total_clusters": total_clusters,
                    "failed_clusters": len(failed_clusters),
                    "errors": {cluster: error_details.get(cluster, "Unknown error") for cluster in failed_clusters}
                }
            
                with open(report_file, 'w') as f:
                    json.dump(error_report, f, indent=2)
                
                self.print_colored(Colors.YELLOW, f"\n📝 Error details saved to: {report_file}")
                self.logger.info(f"Error report written to {report_file}")
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"\n⚠️ Could not save error report: {str(e)}")
                self.logger.error(f"Failed to write error report: {str(e)}")
    
        return len(created_clusters) > 0

    def process_single_user(self, user_data: Dict) -> bool:
        """
        Process a single IAM user for cluster creation
    
        Args:
            user_data: Dictionary containing the user data including username, credentials, and preferences
        
        Returns:
            bool: True if cluster creation was successful, False otherwise
        """
        try:
            self.logger.info(f"Processing single user: {user_data.get('username', 'unknown')}")
        
            username = user_data.get('username', 'unknown')
            region = user_data.get('region', 'us-east-1')
            account_id = user_data.get('account_id', '')
            account_name = user_data.get('account_name', '')
        
            # Generate cluster name if not provided
            cluster_name = user_data.get('cluster_name', self.generate_cluster_name(username, region))
        
            # Create structured log entry for start of cluster creation
            self.logger.info(json.dumps({
                "event": "cluster_creation_start", 
                "cluster_name": cluster_name,
                "username": username,
                "region": region,
                "strategy": user_data.get('strategy', 'unknown'),
                "account_id": account_id,
                "account_name": account_name
            }))

            
            # Explicitly check and log if nodegroup_configs exists in user_data
            if 'nodegroup_configs' in user_data and user_data['nodegroup_configs']:
                self.logger.info(f"Found nodegroup_configs in user_data: {user_data['nodegroup_configs']}")
            else:
                self.logger.warning(f"No nodegroup_configs found in user_data for {username}")
        
            # Call existing create_cluster method
            config = {
                'cluster_name': cluster_name,
                'username': username,
                'region': region,
                'account_id': account_id,
                'account_name': account_name,
                'access_key': user_data.get('access_key', ''),
                'secret_key': user_data.get('secret_key', ''),
                # Add any other required configuration parameters
                'strategy': user_data.get('strategy', 'on-demand'),
                'min_size': user_data.get('min_size', 1),
                'desired_size': user_data.get('desired_size', 1),
                'max_size': user_data.get('max_size', 3),
                'instance_selections': user_data.get('instance_selections', {}),
                'subnet_preference': user_data.get('subnet_preference', 'auto')
            }

                # Explicitly add nodegroup_configs if it exists
            if 'nodegroup_configs' in user_data:
                config['nodegroup_configs'] = user_data['nodegroup_configs']
    
        
            # Add additional configs from user_data if they exist
            for key, value in user_data.items():
                if key not in config:
                    config[key] = value
        
            result = self.create_cluster(config)
        
            if result:
                self.logger.info(json.dumps({
                    "event": "cluster_creation_success",
                    "cluster_name": cluster_name,
                    "username": username,
                    "region": region
                }))
                self.print_colored(Colors.GREEN, f"✅ Successfully created cluster {cluster_name} for {username}")
            else:
                self.logger.error(json.dumps({
                    "event": "cluster_creation_failure",
                    "cluster_name": cluster_name,
                    "username": username,
                    "region": region,
                    "error": "create_cluster method returned False"
                }))
                self.print_colored(Colors.RED, f"❌ Failed to create cluster {cluster_name} for {username}")
        
            return result
        
        except Exception as e:
            error_msg = str(e)
        
            # Get the stack trace for detailed logging
            import traceback
            stack_trace = traceback.format_exc()
        
            self.logger.error(json.dumps({
                "event": "cluster_creation_exception",
                "username": user_data.get('username', 'unknown'),
                "error": error_msg,
                "stack_trace": stack_trace
            }))
        
            self.print_colored(Colors.RED, f"❌ Error creating cluster for {user_data.get('username', 'unknown')}: {error_msg}")
            return False

    def process_multiple_user_selection_bk(self, selected_users: List[Dict],automation_options) -> bool:
        """
        Process the selection of multiple IAM users for cluster creation
    
        Args:
            selected_users: List of dictionaries containing user data
        
        Returns:
            bool: True if at least one cluster was created successfully, False otherwise
        """
        if not selected_users or len(selected_users) == 0:
            self.logger.error("No users selected for cluster creation")
            return False

    
        # If only one user is selected, use the standard workflow
        if len(selected_users) == 1:
            self.logger.info("Single user selected, using standard workflow")
            return self.process_single_user(selected_users[0])
    
        # Multiple users selected - create cluster configurations
        cluster_configs = []
    
        self.logger.info(f"Selected {len(selected_users)} users for cluster creation")
        print(f"\n👥 Selected {len(selected_users)} users for cluster creation")
    
        # Generate cluster config for each selected user
        for user in selected_users:
            user_config = {
                'username': user.get('username', 'unknown'),
                'cluster_name': self.generate_cluster_name(
                    user.get('username', 'unknown'), 
                    user.get('region', 'us-east-1')
                ),
                'region': user.get('region', 'us-east-1'),
                'account_id': user.get('account_id', ''),
                'account_name': user.get('account_name', ''),
                'access_key': user.get('access_key', ''),
                'secret_key': user.get('secret_key', ''),
                # Add common configuration settings
                'strategy': user.get('strategy', 'on-demand'),
                'instance_selections': user.get('instance_selections', {}),
                'min_size': user.get('min_size', 1),
                'desired_size': user.get('desired_size', 1),
                'max_size': user.get('max_size', 3),
                'subnet_preference': user.get('subnet_preference', 'auto'),
                'install_addons': automation_options.get("install_addons", False),
                'enable_container_insights': automation_options.get("enable_container_insights", False),
                'ami_type': automation_options.get('ami_type', 'AL2_x86_64'),  # Default to Amazon Linux 2 x86_64',
                'eks_version': automation_options.get('eks_version', '1.28')  # Default EKS version'
            }
        
            # Explicitly add nodegroup_configs if it exists and is not None
            if 'nodegroup_configs' in user and user['nodegroup_configs'] is not None:
                user_config['nodegroup_configs'] = user['nodegroup_configs']
                self.logger.info(f"Added nodegroup_configs for user {user['username']}: {user['nodegroup_configs']}")
            else:
                self.logger.warning(f"No nodegroup_configs for user {user['username']}")
    
            # Add any additional config parameters
            for key, value in user.items():
                if key not in user_config:
                    user_config[key] = value
        
            cluster_configs.append(user_config)

            
        # Log the final cluster_configs to verify nodegroup_configs are preserved
        for i, config in enumerate(cluster_configs):
            has_nodegroup_configs = 'nodegroup_configs' in config and config['nodegroup_configs'] is not None
            self.logger.info(f"Cluster config {i+1} has nodegroup_configs: {has_nodegroup_configs}")
    
        # Create clusters with shared configuration
        return self.create_multiple_clusters(cluster_configs)

    def process_multiple_user_selection(self, selected_users: List[Dict], automation_options: Dict) -> bool:
        """
        Process the selection of multiple users for cluster creation with enhanced logging and error handling
    
        Args:
            selected_users: List of dictionaries containing user data including nodegroup configs
            automation_options: Dictionary containing automation settings like add-ons and EKS version
    
        Returns:
            bool: True if at least one cluster was created successfully, False otherwise
        """
        if not selected_users or len(selected_users) == 0:
            self.logger.error("No users selected for cluster creation")
            self.print_colored(Colors.RED, "❌ No users selected for cluster creation")
            return False

        # Initialize tracking structures
        created_clusters = []
        failed_clusters = []
        error_details = {}  # Store detailed error info for each failed cluster
    
        # Log the automation options
        self.logger.info(json.dumps({
            "event": "multi_user_selection_start",
            "users_count": len(selected_users),
            "automation_options": automation_options
        }))
    
        # Show summary before proceeding
        self.logger.info("User selection summary:")
        for i, user in enumerate(selected_users, 1):
            username = user.get('username', 'unknown')
            region = user.get('region', 'us-east-1')
            account_name = user.get('account_name', 'unknown')
            self.logger.info(f"  {i}. {username} - Region: {region}, Account: {account_name}")
    
        # Check for selected add-ons and features
        self.setup_addons = automation_options.get('install_addons', True)
        self.setup_container_insights = automation_options.get('enable_container_insights', True)
    
        # Set up default EKS version and AMI type from automation options
        eks_version = automation_options.get('eks_version', '1.28')
        ami_type = automation_options.get('ami_type', 'AL2_x86_64')
    
        self.print_colored(Colors.YELLOW, f"\n👥 Creating clusters for {len(selected_users)} users")
    
        # Process each selected user
        total_users = len(selected_users)
        for i, user in enumerate(selected_users, 1):
            username = user.get('username', 'unknown')
            region = user.get('region', 'us-east-1')
            account_id = user.get('account_id', '')
            account_name = user.get('account_name', '')
        
            # Create a unique cluster name for this user
            cluster_name = self.generate_cluster_name(username, region)
        
            self.logger.info(f"[{i}/{total_users}] Processing user {username} for cluster {cluster_name}")
            print(f"\n[{i}/{total_users}] 🚀 Creating cluster {cluster_name} for {username}...")
        
            try:
                # Create structured log entry for start of cluster creation
                self.logger.info(json.dumps({
                    "event": "user_cluster_creation_start", 
                    "cluster_name": cluster_name,
                    "username": username,
                    "region": region,
                    "account_name": account_name,
                    "account_id": account_id,
                    "eks_version": eks_version,
                    "ami_type": ami_type,
                    "install_addons": self.setup_addons,
                    "enable_container_insights": self.setup_container_insights,
                    "has_nodegroup_configs": 'nodegroup_configs' in user and bool(user['nodegroup_configs'])
                }))
            
                # Create configuration for this cluster
                cluster_config = {
                    'cluster_name': cluster_name,
                    'username': username,
                    'region': region,
                    'account_id': account_id,
                    'account_name': account_name,
                    'access_key': user.get('access_key', ''),
                    'secret_key': user.get('secret_key', ''),
                    'email': user.get('email', ''),
                    'install_addons': self.setup_addons,
                    'enable_container_insights': self.setup_container_insights,
                    'eks_version': eks_version,
                    'ami_type': ami_type
                }
            
                # Very important: Add nodegroup configurations if they exist
                if 'nodegroup_configs' in user and user['nodegroup_configs']:
                    nodegroup_count = len(user['nodegroup_configs'])
                    self.logger.info(f"Using nodegroup configurations from user: {nodegroup_count} nodegroups")
                    cluster_config['nodegroup_configs'] = user['nodegroup_configs']
                
                    # Log details of each nodegroup config
                    for j, ng_config in enumerate(user['nodegroup_configs'], 1):
                        self.logger.info(json.dumps({
                            "event": "nodegroup_config_details",
                            "cluster_name": cluster_name,
                            "nodegroup_index": j,
                            "nodegroup_name": ng_config.get('name', 'unknown'),
                            "strategy": ng_config.get('strategy', 'unknown'),
                            "min_nodes": ng_config.get('min_nodes', 0),
                            "desired_nodes": ng_config.get('desired_nodes', 0),
                            "max_nodes": ng_config.get('max_nodes', 0)
                        }))
                else:
                    self.logger.warning(f"No nodegroup configurations found for user {username}")
            
                # Create the cluster with this configuration
                result = self.create_cluster(cluster_config)
            
                if result:
                    created_clusters.append(cluster_name)
                    self.logger.info(json.dumps({
                        "event": "user_cluster_creation_success", 
                        "cluster_name": cluster_name,
                        "username": username
                    }))
                    self.print_colored(Colors.GREEN, f"✅ Successfully created cluster {cluster_name}")
                else:
                    failed_clusters.append(cluster_name)
                    error_message = "Create cluster method returned False"
                    error_details[cluster_name] = error_message
                    self.logger.error(json.dumps({
                        "event": "user_cluster_creation_failure", 
                        "cluster_name": cluster_name,
                        "username": username,
                        "error": error_message
                    }))
                    self.print_colored(Colors.RED, f"❌ Failed to create cluster {cluster_name}")
                
                    # Ask if user wants to continue with remaining users
                    if i < total_users:
                        continue_choice = input(f"\n⚠️ Failed to create cluster for {username}. Continue with remaining {total_users - i} users? (y/N): ").strip().lower()
                        if continue_choice not in ['y', 'yes']:
                            self.logger.warning(f"Multi-user cluster creation aborted by user after failure of {cluster_name}")
                            break
                    
            except Exception as e:
                error_msg = str(e)
                failed_clusters.append(cluster_name)
                error_details[cluster_name] = error_msg
            
                # Log the full stack trace for debugging
                import traceback
                stack_trace = traceback.format_exc()
                self.logger.error(json.dumps({
                    "event": "user_cluster_creation_exception", 
                    "cluster_name": cluster_name,
                    "username": username,
                    "error": error_msg,
                    "stack_trace": stack_trace
                }))
            
                self.print_colored(Colors.RED, f"❌ Error creating cluster {cluster_name}: {error_msg}")
            
                # Ask if user wants to continue with remaining users
                if i < total_users:
                    continue_choice = input(f"\n⚠️ Error creating cluster for {username}. Continue with remaining {total_users - i} users? (y/N): ").strip().lower()
                    if continue_choice not in ['y', 'yes']:
                        self.logger.warning(f"Multi-user cluster creation aborted by user after exception for {cluster_name}")
                        break

        # Generate and log final summary
        success_rate = len(created_clusters) / total_users * 100 if total_users > 0 else 0
    
        summary = {
            "event": "multi_user_creation_summary",
            "total_users": total_users,
            "successful_clusters": len(created_clusters),
            "failed_clusters": len(failed_clusters),
            "success_rate_percent": round(success_rate, 2),
            "created_clusters": created_clusters,
            "failed_clusters": {cluster: error_details.get(cluster, "Unknown error") for cluster in failed_clusters}
        }
    
        self.logger.info(json.dumps(summary))
    
        # Print final summary
        print("\n" + "=" * 60)
        print("📋 CLUSTER CREATION SUMMARY")
        print("=" * 60)
        print(f"Total users: {total_users}")
        print(f"Successfully created: {len(created_clusters)} clusters ({success_rate:.1f}%)")
        print(f"Failed: {len(failed_clusters)} clusters ({100-success_rate:.1f}%)")
    
        if created_clusters:
            self.print_colored(Colors.GREEN, "\n✅ Successfully created clusters:")
            for cluster in created_clusters:
                print(f"   - {cluster}")
    
        if failed_clusters:
            self.print_colored(Colors.RED, "\n❌ Failed clusters:")
            for cluster in failed_clusters:
                error = error_details.get(cluster, "Unknown error")
                print(f"   - {cluster}: {error}")
    
        # Save error details to a report file
        if failed_clusters:
            try:
                log_dir = "aws/eks"
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                report_file = os.path.join(log_dir, f"cluster_creation_errors_{self.execution_timestamp}.json")
                error_report = {
                    "timestamp": datetime.now().isoformat(),
                    "total_users": total_users,
                    "failed_clusters": len(failed_clusters),
                    "errors": {cluster: error_details.get(cluster, "Unknown error") for cluster in failed_clusters}
                }
            
                with open(report_file, 'w') as f:
                    json.dump(error_report, f, indent=2)
                
                self.print_colored(Colors.YELLOW, f"\n📝 Error details saved to: {report_file}")
                self.logger.info(f"Error report written to {report_file}")
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"\n⚠️ Could not save error report: {str(e)}")
                self.logger.error(f"Failed to write error report: {str(e)}")
    
        return len(created_clusters) > 0

    def disable_public_access(self, eks_client, cluster_name: str) -> bool:
        """
        Disable public access for an EKS cluster while maintaining private access.
        Assumes the cluster already has public access enabled.

        Args:
            eks_client: Boto3 EKS client
            cluster_name: Name of the EKS cluster

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.log_operation('INFO', f"Disabling public access for EKS cluster {cluster_name}...")

            # Update the cluster to disable public access while ensuring private access is enabled
            update_response = eks_client.update_cluster_config(
                name=cluster_name,
                resourcesVpcConfig={
                    'endpointPrivateAccess': True,
                    'endpointPublicAccess': False
                }
            )

            # Wait for the update to complete
            waiter = eks_client.get_waiter('cluster_active')
            waiter.wait(name=cluster_name)

            self.log_operation('SUCCESS', f"Successfully disabled public access for EKS cluster {cluster_name}")
            return True

        except Exception as e:
            self.log_operation('ERROR', f"Error disabling public access for cluster {cluster_name}: {str(e)}")
            return False
#####