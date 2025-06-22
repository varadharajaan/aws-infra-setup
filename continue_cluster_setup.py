#!/usr/bin/env python3
"""
EKS Cluster Continuation Setup Script
Allows users to continue configuration of an existing EKS cluster when initial creation had partial failures.
Provides menu-driven interface for selecting and installing cluster components.
"""

import json
import os
import sys
import time
import boto3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import argparse

# Import required classes from existing modules
from aws_credential_manager import AWSCredentialManager, CredentialInfo
from eks_cluster_manager import EKSClusterManager, Colors
from spot_instance_analyzer import SpotInstanceAnalyzer


class EKSClusterContinuation:
    def __init__(self):
        """Initialize the EKS Cluster Continuation Setup"""
        self.cluster_name = None
        self.credentials = None
        self.region = None
        self.eks_manager = None
        self.cluster_info = {}
        
    def print_colored(self, color: str, message: str) -> None:
        """Print colored message to terminal"""
        print(f"{color}{message}{Colors.NC}")
    
    def display_banner(self):
        """Display welcome banner"""
        print("\n" + "="*80)
        self.print_colored(Colors.CYAN, "🚀 EKS Cluster Continuation Setup")
        self.print_colored(Colors.YELLOW, "   Continue configuration of partially configured EKS clusters")
        print("="*80 + "\n")
    
    def get_cluster_credentials(self) -> bool:
        """Get cluster name and admin credentials from user input"""
        try:
            print("📝 Enter cluster details:")
            
            # Get cluster name
            self.cluster_name = input("   Cluster name: ").strip()
            if not self.cluster_name:
                self.print_colored(Colors.RED, "❌ Cluster name is required")
                return False
            
            # Get admin credentials
            admin_access_key = input("   Admin Access Key: ").strip()
            if not admin_access_key:
                self.print_colored(Colors.RED, "❌ Admin Access Key is required")
                return False
                
            admin_secret_key = input("   Admin Secret Key: ").strip()
            if not admin_secret_key:
                self.print_colored(Colors.RED, "❌ Admin Secret Key is required")
                return False
            
            # Auto-detect region from cluster
            self.print_colored(Colors.YELLOW, "🔍 Auto-detecting cluster region...")
            
            # Try common regions to find the cluster
            common_regions = ['us-east-1', 'us-west-2', 'eu-west-1', 'eu-central-1', 'ap-south-1']
            cluster_found = False
            
            for region in common_regions:
                try:
                    session = boto3.Session(
                        aws_access_key_id=admin_access_key,
                        aws_secret_access_key=admin_secret_key,
                        region_name=region
                    )
                    eks_client = session.client('eks')
                    
                    # Try to describe the cluster in this region
                    response = eks_client.describe_cluster(name=self.cluster_name)
                    if response['cluster']:
                        self.region = region
                        cluster_found = True
                        self.print_colored(Colors.GREEN, f"✅ Found cluster in region: {region}")
                        break
                except:
                    continue
            
            if not cluster_found:
                self.print_colored(Colors.YELLOW, "⚠️  Could not auto-detect region")
                self.region = input("   Enter cluster region (e.g., us-west-2): ").strip()
                if not self.region:
                    self.print_colored(Colors.RED, "❌ Region is required")
                    return False
            
            # Create CredentialInfo object
            self.credentials = CredentialInfo(
                account_name="admin-account",
                account_id="",  # Will be populated later
                email="admin@example.com",
                access_key=admin_access_key,
                secret_key=admin_secret_key,
                credential_type="admin",
                regions=[self.region],
                username="admin"
            )
            
            return True
            
        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n⚠️  Setup cancelled by user")
            return False
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error getting credentials: {str(e)}")
            return False
    
    def verify_cluster_status(self) -> bool:
        """Verify that the cluster exists and get its current status"""
        try:
            self.print_colored(Colors.YELLOW, f"🔍 Verifying cluster status for '{self.cluster_name}'...")
            
            # Create AWS session
            session = boto3.Session(
                aws_access_key_id=self.credentials.access_key,
                aws_secret_access_key=self.credentials.secret_key,
                region_name=self.region
            )
            
            eks_client = session.client('eks')
            sts_client = session.client('sts')
            
            # Get account ID
            try:
                account_response = sts_client.get_caller_identity()
                self.credentials.account_id = account_response['Account']
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"⚠️  Could not get account ID: {str(e)}")
            
            # Describe cluster
            cluster_response = eks_client.describe_cluster(name=self.cluster_name)
            cluster = cluster_response['cluster']
            
            self.cluster_info = {
                'name': cluster['name'],
                'status': cluster['status'],
                'version': cluster.get('version', 'Unknown'),
                'endpoint': cluster.get('endpoint', ''),
                'created_at': cluster.get('createdAt', ''),
                'platform_version': cluster.get('platformVersion', ''),
                'vpc_config': cluster.get('resourcesVpcConfig', {}),
                'logging': cluster.get('logging', {}),
                'addons': [],
                'nodegroups': []
            }
            
            # Get nodegroups
            try:
                nodegroups_response = eks_client.list_nodegroups(clusterName=self.cluster_name)
                for ng_name in nodegroups_response.get('nodegroups', []):
                    ng_response = eks_client.describe_nodegroup(
                        clusterName=self.cluster_name,
                        nodegroupName=ng_name
                    )
                    self.cluster_info['nodegroups'].append({
                        'name': ng_name,
                        'status': ng_response['nodegroup']['status'],
                        'capacity_type': ng_response['nodegroup'].get('capacityType', 'ON_DEMAND'),
                        'instance_types': ng_response['nodegroup'].get('instanceTypes', []),
                        'scaling_config': ng_response['nodegroup'].get('scalingConfig', {})
                    })
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"⚠️  Could not get nodegroups: {str(e)}")
            
            # Get add-ons
            try:
                addons_response = eks_client.list_addons(clusterName=self.cluster_name)
                for addon_name in addons_response.get('addons', []):
                    addon_response = eks_client.describe_addon(
                        clusterName=self.cluster_name,
                        addonName=addon_name
                    )
                    self.cluster_info['addons'].append({
                        'name': addon_name,
                        'status': addon_response['addon']['status'],
                        'version': addon_response['addon'].get('addonVersion', 'Unknown')
                    })
            except Exception as e:
                self.print_colored(Colors.YELLOW, f"⚠️  Could not get add-ons: {str(e)}")
            
            # Display cluster status
            self.display_cluster_status()
            
            if self.cluster_info['status'] != 'ACTIVE':
                self.print_colored(Colors.RED, f"❌ Cluster status is '{self.cluster_info['status']}', expected 'ACTIVE'")
                return False
            
            return True
            
        except eks_client.exceptions.ResourceNotFoundException:
            self.print_colored(Colors.RED, f"❌ Cluster '{self.cluster_name}' not found in region '{self.region}'")
            return False
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error verifying cluster: {str(e)}")
            return False
    
    def display_cluster_status(self):
        """Display current cluster status and components"""
        print("\n" + "="*60)
        self.print_colored(Colors.CYAN, "📋 CLUSTER STATUS")
        print("="*60)
        
        print(f"Name: {self.cluster_info['name']}")
        print(f"Status: {self.cluster_info['status']}")
        print(f"Version: {self.cluster_info['version']}")
        print(f"Region: {self.region}")
        if self.credentials.account_id:
            print(f"Account: {self.credentials.account_id}")
        
        # Nodegroups
        print(f"\n📊 Nodegroups ({len(self.cluster_info['nodegroups'])}):")
        if self.cluster_info['nodegroups']:
            for ng in self.cluster_info['nodegroups']:
                status_color = Colors.GREEN if ng['status'] == 'ACTIVE' else Colors.YELLOW
                print(f"   {status_color}• {ng['name']}{Colors.NC} - {ng['status']} ({ng['capacity_type']})")
                if ng['instance_types']:
                    print(f"     Instance Types: {', '.join(ng['instance_types'])}")
        else:
            self.print_colored(Colors.YELLOW, "   No nodegroups found")
        
        # Add-ons
        print(f"\n🔧 Add-ons ({len(self.cluster_info['addons'])}):")
        if self.cluster_info['addons']:
            for addon in self.cluster_info['addons']:
                status_color = Colors.GREEN if addon['status'] == 'ACTIVE' else Colors.YELLOW
                print(f"   {status_color}• {addon['name']}{Colors.NC} - {addon['status']} (v{addon['version']})")
        else:
            self.print_colored(Colors.YELLOW, "   No add-ons found")
        
        print("="*60)
    
    def display_main_menu(self) -> int:
        """Display main component selection menu and get user choice"""
        print("\n" + "="*60)
        self.print_colored(Colors.CYAN, "🛠️  COMPONENT CONFIGURATION MENU")
        print("="*60)
        
        menu_options = [
            "🔸 Nodegroups Management",
            "🔧 Essential Add-ons (EBS CSI, EFS CSI, VPC CNI)",
            "📊 Container Insights",
            "🔄 Cluster Autoscaler",
            "⏰ Scheduled Scaling",
            "📈 CloudWatch Monitoring & Alarms",
            "💰 Cost Monitoring Alarms",
            "🔍 Comprehensive Health Check",
            "💵 Cost Estimation",
            "📋 Generate User Instructions",
            "❌ Exit"
        ]
        
        for i, option in enumerate(menu_options, 1):
            print(f"   {i}. {option}")
        
        print("="*60)
        
        try:
            choice = input("Select option (1-11): ").strip()
            return int(choice) if choice.isdigit() else 0
        except (ValueError, KeyboardInterrupt):
            return 0
    
    def initialize_eks_manager(self):
        """Initialize the EKS manager for component operations"""
        if not self.eks_manager:
            self.eks_manager = EKSClusterManager(current_user=self.credentials.username)
    
    def handle_nodegroups_management(self):
        """Handle nodegroup creation and management"""
        self.print_colored(Colors.CYAN, "\n🔸 Nodegroups Management")
        print("-" * 40)
        
        # Display current nodegroups
        if self.cluster_info['nodegroups']:
            print("Current nodegroups:")
            for ng in self.cluster_info['nodegroups']:
                print(f"   • {ng['name']} - {ng['status']} ({ng['capacity_type']})")
        
        print("\nNodegroup options:")
        print("   1. Add On-Demand Nodegroup")
        print("   2. Add Spot Nodegroup")
        print("   3. Add Mixed Nodegroup")
        print("   4. Back to main menu")
        
        try:
            choice = input("Select option (1-4): ").strip()
            
            if choice == "1":
                self.create_nodegroup("on-demand")
            elif choice == "2":
                self.create_nodegroup("spot")
            elif choice == "3":
                self.create_nodegroup("mixed")
            elif choice == "4":
                return
            else:
                self.print_colored(Colors.YELLOW, "⚠️  Invalid choice")
                
        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n⚠️  Operation cancelled")
    
    def get_cluster_vpc_config(self):
        """Get VPC configuration from existing cluster"""
        try:
            vpc_config = self.cluster_info.get('vpc_config', {})
            subnet_ids = vpc_config.get('subnetIds', [])
            security_group_ids = vpc_config.get('securityGroupIds', [])
            
            if not subnet_ids:
                self.print_colored(Colors.YELLOW, "⚠️  No subnet IDs found in cluster VPC config")
                return [], ""
            
            # Use the first security group if available, otherwise will be created by EKS
            security_group_id = security_group_ids[0] if security_group_ids else ""
            
            return subnet_ids, security_group_id
            
        except Exception as e:
            self.print_colored(Colors.YELLOW, f"⚠️  Error getting VPC config: {str(e)}")
            return [], ""
    
    def create_nodegroup(self, strategy: str):
        """Create a new nodegroup with the specified strategy"""
        self.print_colored(Colors.YELLOW, f"🚀 Creating {strategy} nodegroup...")
        
        # Generate nodegroup name
        self.initialize_eks_manager()
        nodegroup_name = self.eks_manager.generate_nodegroup_name(self.cluster_name, strategy)
        
        # Get basic configuration
        print(f"\nNodegroup name: {nodegroup_name}")
        
        try:
            min_nodes = int(input("Minimum nodes (default: 1): ").strip() or "1")
            desired_nodes = int(input("Desired nodes (default: 1): ").strip() or "1")
            max_nodes = int(input("Maximum nodes (default: 3): ").strip() or "3")
            
            if min_nodes < 0 or desired_nodes < min_nodes or max_nodes < desired_nodes:
                self.print_colored(Colors.RED, "❌ Invalid node configuration")
                return
            
            # Get instance types from user or use defaults
            print(f"\nInstance type selection:")
            use_defaults = input("Use default instance types? (Y/n): ").strip().lower() != 'n'
            
            if use_defaults:
                default_instances = {
                    'on-demand': ['t3.medium'],
                    'spot': ['t3.medium', 't3.large'],
                    'mixed': ['t3.medium', 't3.large']
                }
                instance_types = default_instances.get(strategy, ['t3.medium'])
            else:
                instance_input = input("Enter instance types (comma-separated, e.g., t3.medium,t3.large): ").strip()
                if instance_input:
                    instance_types = [t.strip() for t in instance_input.split(',')]
                else:
                    instance_types = ['t3.medium']
            
            self.print_colored(Colors.YELLOW, f"Using instance types: {', '.join(instance_types)}")
            
            # Get VPC configuration from existing cluster
            subnet_ids, security_group_id = self.get_cluster_vpc_config()
            
            if not subnet_ids:
                self.print_colored(Colors.RED, "❌ Could not get subnet information from cluster")
                return
            
            # Create AWS session and EKS client
            session = boto3.Session(
                aws_access_key_id=self.credentials.access_key,
                aws_secret_access_key=self.credentials.secret_key,
                region_name=self.region
            )
            eks_client = session.client('eks')
            
            # Create the nodegroup based on strategy
            success = False
            try:
                if strategy == "on-demand":
                    success = self.eks_manager.create_ondemand_nodegroup(
                        eks_client, self.cluster_name, nodegroup_name,
                        instance_types, min_nodes, desired_nodes, max_nodes,
                        subnet_ids, security_group_id
                    )
                elif strategy == "spot":
                    success = self.eks_manager.create_spot_nodegroup(
                        eks_client, self.cluster_name, nodegroup_name,
                        instance_types, min_nodes, desired_nodes, max_nodes,
                        subnet_ids, security_group_id
                    )
                elif strategy == "mixed":
                    success = self.eks_manager.create_mixed_nodegroup(
                        eks_client, self.cluster_name, nodegroup_name,
                        instance_types, instance_types, min_nodes, desired_nodes, max_nodes,
                        subnet_ids, security_group_id, 50  # 50% on-demand
                    )
                
                if success:
                    self.print_colored(Colors.GREEN, f"✅ Nodegroup '{nodegroup_name}' creation initiated")
                    self.print_colored(Colors.YELLOW, "⏳ Nodegroup creation may take 5-10 minutes to complete")
                    
                    # Ask if user wants to wait and refresh status
                    wait_for_completion = input("Wait for nodegroup to become ACTIVE? (y/N): ").strip().lower() == 'y'
                    if wait_for_completion:
                        self.print_colored(Colors.YELLOW, "⏳ Waiting for nodegroup to become ACTIVE...")
                        self.wait_for_nodegroup_active(nodegroup_name)
                    
                    # Refresh cluster info
                    self.verify_cluster_status()
                else:
                    self.print_colored(Colors.RED, f"❌ Failed to create nodegroup '{nodegroup_name}'")
                    
            except Exception as nodegroup_error:
                self.print_colored(Colors.RED, f"❌ Error during nodegroup creation: {str(nodegroup_error)}")
                
        except ValueError:
            self.print_colored(Colors.RED, "❌ Invalid number format")
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error creating nodegroup: {str(e)}")
    
    def wait_for_nodegroup_active(self, nodegroup_name: str, timeout_minutes: int = 15):
        """Wait for nodegroup to become ACTIVE"""
        try:
            session = boto3.Session(
                aws_access_key_id=self.credentials.access_key,
                aws_secret_access_key=self.credentials.secret_key,
                region_name=self.region
            )
            eks_client = session.client('eks')
            
            start_time = time.time()
            timeout_seconds = timeout_minutes * 60
            
            while time.time() - start_time < timeout_seconds:
                try:
                    response = eks_client.describe_nodegroup(
                        clusterName=self.cluster_name,
                        nodegroupName=nodegroup_name
                    )
                    status = response['nodegroup']['status']
                    
                    if status == 'ACTIVE':
                        self.print_colored(Colors.GREEN, f"✅ Nodegroup '{nodegroup_name}' is now ACTIVE")
                        return True
                    elif status in ['CREATE_FAILED', 'DELETE_FAILED']:
                        self.print_colored(Colors.RED, f"❌ Nodegroup '{nodegroup_name}' failed: {status}")
                        return False
                    else:
                        print(f"   Status: {status} - waiting...")
                        time.sleep(30)  # Wait 30 seconds before checking again
                        
                except Exception as e:
                    self.print_colored(Colors.YELLOW, f"⚠️  Error checking nodegroup status: {str(e)}")
                    time.sleep(30)
            
            self.print_colored(Colors.YELLOW, f"⚠️  Timeout waiting for nodegroup to become ACTIVE")
            return False
            
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error waiting for nodegroup: {str(e)}")
            return False
    
    def handle_essential_addons(self):
        """Handle installation of essential add-ons"""
        self.print_colored(Colors.CYAN, "\n🔧 Essential Add-ons Installation")
        print("-" * 40)
        
        # Check current add-ons
        current_addons = [addon['name'] for addon in self.cluster_info['addons']]
        essential_addons = ['vpc-cni', 'kube-proxy', 'coredns', 'aws-ebs-csi-driver', 'aws-efs-csi-driver']
        
        print("Current add-ons:")
        for addon in current_addons:
            print(f"   ✅ {addon}")
        
        missing_addons = [addon for addon in essential_addons if addon not in current_addons]
        
        if missing_addons:
            print(f"\nMissing essential add-ons:")
            for addon in missing_addons:
                print(f"   ❌ {addon}")
            
            install = input(f"\nInstall missing add-ons? (Y/n): ").strip().lower()
            if install != 'n':
                self.initialize_eks_manager()
                
                session = boto3.Session(
                    aws_access_key_id=self.credentials.access_key,
                    aws_secret_access_key=self.credentials.secret_key,
                    region_name=self.region
                )
                eks_client = session.client('eks')
                
                success = self.eks_manager.install_essential_addons(
                    eks_client, self.cluster_name, self.region,
                    self.credentials.access_key, self.credentials.secret_key,
                    self.credentials.account_id
                )
                
                if success:
                    self.print_colored(Colors.GREEN, "✅ Essential add-ons installation completed")
                    self.verify_cluster_status()  # Refresh cluster info
                else:
                    self.print_colored(Colors.RED, "❌ Some add-ons may have failed to install")
        else:
            self.print_colored(Colors.GREEN, "✅ All essential add-ons are already installed")
    
    def handle_container_insights(self):
        """Handle Container Insights setup"""
        self.print_colored(Colors.CYAN, "\n📊 Container Insights Setup")
        print("-" * 40)
        
        # Check if already enabled
        self.initialize_eks_manager()
        
        try:
            enabled = self.eks_manager._verify_container_insights(
                self.cluster_name, self.region,
                self.credentials.access_key, self.credentials.secret_key
            )
            
            if enabled:
                self.print_colored(Colors.GREEN, "✅ Container Insights is already enabled")
            else:
                enable = input("Enable Container Insights? (Y/n): ").strip().lower()
                if enable != 'n':
                    success = self.eks_manager.enable_container_insights(
                        self.cluster_name, self.region,
                        self.credentials.access_key, self.credentials.secret_key
                    )
                    
                    if success:
                        self.print_colored(Colors.GREEN, "✅ Container Insights enabled successfully")
                    else:
                        self.print_colored(Colors.RED, "❌ Failed to enable Container Insights")
                        
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error checking Container Insights: {str(e)}")
    
    def handle_cluster_autoscaler(self):
        """Handle Cluster Autoscaler setup"""
        self.print_colored(Colors.CYAN, "\n🔄 Cluster Autoscaler Setup")
        print("-" * 40)
        
        # Check if already installed
        self.initialize_eks_manager()
        
        try:
            enabled = self.eks_manager._verify_cluster_autoscaler(
                self.cluster_name, self.region,
                self.credentials.access_key, self.credentials.secret_key
            )
            
            if enabled:
                self.print_colored(Colors.GREEN, "✅ Cluster Autoscaler is already installed")
            else:
                install = input("Install Cluster Autoscaler? (Y/n): ").strip().lower()
                if install != 'n':
                    session = boto3.Session(
                        aws_access_key_id=self.credentials.access_key,
                        aws_secret_access_key=self.credentials.secret_key,
                        region_name=self.region
                    )
                    
                    success = self.eks_manager._setup_autoscaler_iam_permissions(
                        session, self.cluster_name, self.credentials.account_id
                    )
                    
                    if success:
                        self.print_colored(Colors.GREEN, "✅ Cluster Autoscaler setup completed")
                    else:
                        self.print_colored(Colors.RED, "❌ Failed to setup Cluster Autoscaler")
                        
        except Exception as e:
            self.print_colored(Colors.RED, f"❌ Error setting up Cluster Autoscaler: {str(e)}")
    
    def handle_scheduled_scaling(self):
        """Handle Scheduled Scaling setup"""
        self.print_colored(Colors.CYAN, "\n⏰ Scheduled Scaling Setup")
        print("-" * 40)
        
        if not self.cluster_info['nodegroups']:
            self.print_colored(Colors.YELLOW, "⚠️  No nodegroups found. Create nodegroups first.")
            return
        
        nodegroup_names = [ng['name'] for ng in self.cluster_info['nodegroups']]
        print(f"Available nodegroups: {', '.join(nodegroup_names)}")
        
        setup = input("Setup scheduled scaling for all nodegroups? (Y/n): ").strip().lower()
        if setup != 'n':
            self.initialize_eks_manager()
            
            success = self.eks_manager.setup_scheduled_scaling_multi_nodegroup(
                self.cluster_name, self.region,
                self.credentials.access_key, self.credentials.secret_key,
                nodegroup_names
            )
            
            if success:
                self.print_colored(Colors.GREEN, "✅ Scheduled scaling setup completed")
            else:
                self.print_colored(Colors.RED, "❌ Failed to setup scheduled scaling")
    
    def handle_cloudwatch_monitoring(self):
        """Handle CloudWatch monitoring and alarms setup"""
        self.print_colored(Colors.CYAN, "\n📈 CloudWatch Monitoring & Alarms Setup")
        print("-" * 40)
        
        if not self.cluster_info['nodegroups']:
            self.print_colored(Colors.YELLOW, "⚠️  No nodegroups found. Create nodegroups first.")
            return
        
        setup = input("Setup CloudWatch monitoring and alarms? (Y/n): ").strip().lower()
        if setup != 'n':
            self.initialize_eks_manager()
            
            session = boto3.Session(
                aws_access_key_id=self.credentials.access_key,
                aws_secret_access_key=self.credentials.secret_key,
                region_name=self.region
            )
            cloudwatch_client = session.client('cloudwatch')
            
            # Setup CloudWatch agent
            self.print_colored(Colors.YELLOW, "🔧 Setting up CloudWatch agent...")
            agent_success = self.eks_manager.deploy_cloudwatch_agent_fixed(
                self.cluster_name, self.region,
                self.credentials.access_key, self.credentials.secret_key,
                self.credentials.account_id
            )
            
            # Setup alarms for all nodegroups
            alarm_success = True
            nodegroup_names = [ng['name'] for ng in self.cluster_info['nodegroups']]
            
            self.print_colored(Colors.YELLOW, "🚨 Setting up CloudWatch alarms...")
            for ng_name in nodegroup_names:
                ng_alarm_success = self.eks_manager.setup_cloudwatch_alarms(
                    self.cluster_name, self.region, cloudwatch_client,
                    ng_name, self.credentials.account_id
                )
                alarm_success = alarm_success and ng_alarm_success
            
            if agent_success and alarm_success:
                self.print_colored(Colors.GREEN, "✅ CloudWatch monitoring setup completed")
            else:
                self.print_colored(Colors.YELLOW, "⚠️  CloudWatch monitoring setup completed with some issues")
    
    def handle_cost_monitoring(self):
        """Handle cost monitoring alarms setup"""
        self.print_colored(Colors.CYAN, "\n💰 Cost Monitoring Alarms Setup")
        print("-" * 40)
        
        setup = input("Setup cost monitoring alarms? (Y/n): ").strip().lower()
        if setup != 'n':
            self.initialize_eks_manager()
            
            session = boto3.Session(
                aws_access_key_id=self.credentials.access_key,
                aws_secret_access_key=self.credentials.secret_key,
                region_name=self.region
            )
            cloudwatch_client = session.client('cloudwatch')
            
            success = self.eks_manager.setup_cost_alarms(
                self.cluster_name, self.region, cloudwatch_client,
                self.credentials.account_id
            )
            
            if success:
                self.print_colored(Colors.GREEN, "✅ Cost monitoring alarms setup completed")
            else:
                self.print_colored(Colors.RED, "❌ Failed to setup cost monitoring alarms")
    
    def handle_health_check(self):
        """Perform comprehensive cluster health check"""
        self.print_colored(Colors.CYAN, "\n🔍 Comprehensive Health Check")
        print("-" * 40)
        
        self.initialize_eks_manager()
        
        health_results = self.eks_manager.health_check_cluster(
            self.cluster_name, self.region,
            self.credentials.access_key, self.credentials.secret_key
        )
        
        if health_results.get('overall_healthy', False):
            self.print_colored(Colors.GREEN, "✅ Cluster health check passed")
        else:
            self.print_colored(Colors.YELLOW, "⚠️  Cluster health check found issues")
        
        # Display summary
        summary = health_results.get('summary', {})
        if summary:
            print(f"\nHealth Score: {summary.get('health_score', 'Unknown')}/100")
    
    def estimate_costs(self):
        """Provide cost estimation for new components"""
        self.print_colored(Colors.CYAN, "\n💰 Cost Estimation")
        print("-" * 40)
        
        # Basic cost estimates (these would be fetched from pricing APIs in production)
        cost_estimates = {
            'eks_cluster': {'description': 'EKS Control Plane', 'cost_per_hour': 0.10, 'monthly': 73.00},
            'nodegroup_ondemand': {'description': 'On-Demand Nodes (t3.medium)', 'cost_per_hour': 0.0416, 'monthly': 30.37},
            'nodegroup_spot': {'description': 'Spot Nodes (t3.medium)', 'cost_per_hour': 0.0125, 'monthly': 9.13},
            'ebs_storage': {'description': 'EBS Storage (gp3)', 'cost_per_gb_month': 0.08},
            'cloudwatch_logs': {'description': 'CloudWatch Logs', 'cost_per_gb': 0.50},
            'cloudwatch_metrics': {'description': 'CloudWatch Custom Metrics', 'cost_per_metric': 0.30}
        }
        
        print("💵 Current EKS pricing estimates (US East):")
        print(f"   • EKS Control Plane: ${cost_estimates['eks_cluster']['monthly']:.2f}/month")
        
        # Estimate based on current nodegroups
        total_monthly_estimate = cost_estimates['eks_cluster']['monthly']
        
        if self.cluster_info['nodegroups']:
            print("\n📊 Current Nodegroups:")
            for ng in self.cluster_info['nodegroups']:
                scaling = ng.get('scaling_config', {})
                desired = scaling.get('desiredSize', scaling.get('desired_size', 1))
                capacity_type = ng.get('capacity_type', 'ON_DEMAND')
                
                if capacity_type == 'SPOT':
                    node_cost = cost_estimates['nodegroup_spot']['monthly'] * desired
                    print(f"   • {ng['name']} (Spot): ${node_cost:.2f}/month ({desired} nodes)")
                else:
                    node_cost = cost_estimates['nodegroup_ondemand']['monthly'] * desired
                    print(f"   • {ng['name']} (On-Demand): ${node_cost:.2f}/month ({desired} nodes)")
                
                total_monthly_estimate += node_cost
        
        # Additional services estimates
        additional_costs = 0
        if self.cluster_info['addons']:
            additional_costs += 5.00  # CloudWatch logs and metrics
            print(f"\n🔧 Add-ons & Monitoring: ~$5.00/month")
        
        total_monthly_estimate += additional_costs
        
        print(f"\n💰 Estimated Total Monthly Cost: ${total_monthly_estimate:.2f}")
        print("   (Estimates based on US East pricing, actual costs may vary)")
        
        # Cost optimization suggestions
        print(f"\n💡 Cost Optimization Tips:")
        print("   • Use Spot instances for non-critical workloads (60-90% savings)")
        print("   • Enable Cluster Autoscaler to scale down unused nodes")
        print("   • Use Reserved Instances for predictable workloads")
        print("   • Monitor CloudWatch costs and set up billing alarms")
        
        return total_monthly_estimate
    
    def handle_user_instructions(self):
        """Generate and display user access instructions"""
        self.print_colored(Colors.CYAN, "\n📋 User Instructions Generation")
        print("-" * 40)
        
        self.initialize_eks_manager()
        
        # Generate instructions for the admin user
        self.eks_manager.generate_user_instructions_enhanced(
            self.credentials, self.cluster_name, self.region,
            self.credentials.username, {}  # Empty nodegroup configs for now
        )
        
        self.print_colored(Colors.GREEN, "✅ User instructions generated and saved")
    
    def run(self):
        """Main execution flow"""
        try:
            self.display_banner()
            
            # Get cluster credentials
            if not self.get_cluster_credentials():
                return False
            
            # Verify cluster status
            if not self.verify_cluster_status():
                return False
            
            # Main menu loop
            while True:
                choice = self.display_main_menu()
                
                if choice == 1:
                    self.handle_nodegroups_management()
                elif choice == 2:
                    self.handle_essential_addons()
                elif choice == 3:
                    self.handle_container_insights()
                elif choice == 4:
                    self.handle_cluster_autoscaler()
                elif choice == 5:
                    self.handle_scheduled_scaling()
                elif choice == 6:
                    self.handle_cloudwatch_monitoring()
                elif choice == 7:
                    self.handle_cost_monitoring()
                elif choice == 8:
                    self.handle_health_check()
                elif choice == 9:
                    self.estimate_costs()
                elif choice == 10:
                    self.handle_user_instructions()
                elif choice == 11:
                    self.print_colored(Colors.GREEN, "👋 Goodbye!")
                    break
                else:
                    self.print_colored(Colors.YELLOW, "⚠️  Invalid choice. Please try again.")
                
                # Pause before showing menu again
                input("\nPress Enter to continue...")
            
            return True
            
        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n\n⚠️  Setup interrupted by user")
            return False
        except Exception as e:
            self.print_colored(Colors.RED, f"\n❌ Unexpected error: {str(e)}")
            return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Continue EKS cluster configuration')
    parser.add_argument('--cluster-name', help='EKS cluster name')
    parser.add_argument('--access-key', help='Admin access key')
    parser.add_argument('--secret-key', help='Admin secret key')
    parser.add_argument('--region', help='AWS region')
    
    args = parser.parse_args()
    
    continuation = EKSClusterContinuation()
    
    # Pre-populate if arguments provided
    if args.cluster_name:
        continuation.cluster_name = args.cluster_name
    if args.access_key and args.secret_key:
        continuation.credentials = CredentialInfo(
            account_name="admin-account",
            account_id="",
            email="admin@example.com",
            access_key=args.access_key,
            secret_key=args.secret_key,
            credential_type="admin",
            regions=[args.region or 'us-west-2'],
            username="admin"
        )
        continuation.region = args.region or 'us-west-2'
    
    success = continuation.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()