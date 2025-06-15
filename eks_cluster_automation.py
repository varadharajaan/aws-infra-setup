#!/usr/bin/env python3
"""
EKS Cluster Automation - Phase 2
Enhanced with Root/IAM credential support and multiple nodegroup strategies
Supports on-demand, spot, and mixed instance type selection with quota analysis
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set
import boto3

# Import credential manager for Root/IAM support
from aws_credential_manager import AWSCredentialManager, CredentialInfo

# Import spot analyzer for instance analysis
from spot_instance_analyzer import SpotInstanceAnalyzer, SpotAnalysis

# Import EKS manager for cluster operations
from eks_cluster_manager import EKSClusterManager

class EKSAutomation:
    def __init__(self):
        """Initialize the EKS Automation tool"""
        self.current_user = 'varadharajaan'
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.credential_manager = AWSCredentialManager()
        self.spot_analyzer = SpotInstanceAnalyzer()
        
        # EKS Manager will be initialized after credentials are selected
        self.eks_manager = None
        self.config_file = "ec2-region-ami-mapping.json"
        self.ami_config = self.load_ami_configuration()
        
        # Create output directory
        os.makedirs("aws/eks", exist_ok=True)
        
        # Print welcome message
        print("🚀 EKS Cluster & Nodegroup Automation - Phase 2")
        print(f"👤 User: {self.current_user}")
        print(f"🕒 Time: {self.current_time}")
        print("="*60)
        
    def load_ami_configuration(self) -> Dict:
        """Load EC2-AMI-Region mapping configuration"""
        try:
            if not os.path.exists(self.config_file):
                print(f"⚠️  Configuration file {self.config_file} not found, using defaults")
                return {
                    "eks_config": {
                        "default_version": "1.27",
                        "ami_type": "AL2_x86_64"
                    }
                }
            
            with open(self.config_file, 'r') as f:
                ami_config = json.load(f)
                
            print(f"✅ Configuration loaded from: {self.config_file}")
            return ami_config
        
        except Exception as e:
            print(f"⚠️  Error loading configuration: {e}, using defaults")
            return {
                "eks_config": {
                    "default_version": "1.27",
                    "ami_type": "AL2_x86_64"
                }
            }

    def get_eks_config(self) -> Dict:
        """Get EKS configuration from the loaded configuration"""
        # Get EKS config or use defaults
        return self.ami_config.get('eks_config', {
            "default_version": "1.27",
            "ami_type": "AL2_x86_64"
        })
    
    def run_automation(self):
        """Main automation flow"""
        try:
            # Step 1: Get credentials (Root or IAM)
            print("\n🔑 STEP 1: CREDENTIAL SELECTION")
            credentials = self.credential_manager.get_credentials()
        
            # Step 2: Validate credentials
            if not self.credential_manager.validate_credentials(credentials):
                print("❌ Credential validation failed. Exiting...")
                return False
            
            # Initialize EKS Manager with validated credentials
            self.eks_manager = EKSClusterManager(config_file=None)
            
            # Step 3: Configure EKS Cluster Settings
            print("\n🔧 STEP 2: EKS CLUSTER CONFIGURATION")
            
            # Get EKS configuration from mapping file
            eks_config = self.get_eks_config()
            default_version = eks_config.get("default_version", "1.27")
            ami_type = eks_config.get("ami_type", "AL2_x86_64")
            
            print(f"📋 EKS Default Settings:")
            print(f"   🔸 Default Version: {default_version}")
            print(f"   🔸 Default AMI Type: {ami_type}")
            
            # Ask for EKS version
            print("\nEKS Version Selection:")
            print("1. Use default version: " + default_version)
            print("2. Use latest version (1.28)")
            print("3. Specify custom version")
            
            while True:
                version_choice = input("Select option (1-3): ").strip()
                
                if version_choice == '1':
                    eks_version = default_version
                    break
                elif version_choice == '2':
                    eks_version = "1.28"
                    break
                elif version_choice == '3':
                    custom_version = input("Enter EKS version (e.g., 1.28): ").strip()
                    if custom_version:
                        eks_version = custom_version
                        break
                    else:
                        print("❌ Please enter a valid version")
                else:
                    print("❌ Invalid choice. Please select 1, 2, or 3")
            
            # Ask for AMI type
            print("\nAMI Type Selection:")
            print("1. Use default AMI type: " + ami_type)
            print("2. Use AL2023_x86_64_STANDARD (newer)")
            print("3. Specify custom AMI type")
            
            while True:
                ami_choice = input("Select option (1-3): ").strip()
                
                if ami_choice == '1':
                    selected_ami_type = ami_type
                    break
                elif ami_choice == '2':
                    selected_ami_type = "AL2023_x86_64_STANDARD"
                    break
                elif ami_choice == '3':
                    custom_ami = input("Enter AMI type: ").strip()
                    if custom_ami:
                        selected_ami_type = custom_ami
                        break
                    else:
                        print("❌ Please enter a valid AMI type")
                else:
                    print("❌ Invalid choice. Please select 1, 2, or 3")
            
            print(f"\n✅ Selected EKS Version: {eks_version}")
            print(f"✅ Selected AMI Type: {selected_ami_type}")
            
            # Step 4: Configure Nodegroup Settings
            print("\n🔧 STEP 3: NODEGROUP CONFIGURATION")
            
            # Get allowed instance types
            allowed_instance_types = self.ami_config.get('allowed_instance_types', 
                                                       ["t3.medium", "t3.large", "m5.large", "c5.large", "c6a.large"])
            
            # Nodegroup strategy selection
            print("\nNodegroup Strategy Selection:")
            print("1. On-Demand Only (Reliable, Higher Cost)")
            print("2. Spot Only (Cost-Effective, Higher Risk)")
            print("3. Mixed Strategy (50/50 Default, Balanced)")
            
            while True:
                ng_strategy_choice = input("Select nodegroup strategy (1-3): ").strip()
                
                if ng_strategy_choice == '1':
                    ng_strategy = "on-demand"
                    break
                elif ng_strategy_choice == '2':
                    ng_strategy = "spot"
                    break
                elif ng_strategy_choice == '3':
                    ng_strategy = "mixed"
                    break
                else:
                    print("❌ Invalid choice. Please select 1, 2, or 3")
            
            print(f"✅ Selected Nodegroup Strategy: {ng_strategy.upper()}")
            
            # Select instance types based on strategy
            instance_selections = {}
            
            if ng_strategy == "on-demand":
                instance_selections = self.select_ondemand_instance_types(credentials, allowed_instance_types)
            elif ng_strategy == "spot":
                instance_selections = self.select_spot_instance_types(credentials, allowed_instance_types)
            else:  # mixed
                instance_selections = self.select_mixed_instance_types(credentials, allowed_instance_types)
            
            # Configure cluster scaling
            min_nodes, desired_nodes, max_nodes = self.prompt_nodegroup_scaling(ng_strategy)
            
            # Step 5: Create EKS Cluster
            print("\n🚀 STEP 4: EKS CLUSTER CREATION")
            
            # Set up cluster configuration
            cluster_config = {
                'credential_info': credentials,
                'eks_version': eks_version,
                'ami_type': selected_ami_type,
                'nodegroup_strategy': ng_strategy,
                'instance_selections': instance_selections,
                'min_nodes': min_nodes,
                'desired_nodes': desired_nodes,
                'max_nodes': max_nodes
            }
            
            # Confirm before proceeding
            print("\n📋 Cluster Creation Summary:")
            print(f"   Account: {credentials.account_name} ({credentials.account_id})")
            print(f"   Region: {credentials.regions[0]}")
            print(f"   EKS Version: {eks_version}")
            print(f"   AMI Type: {selected_ami_type}")
            print(f"   Nodegroup Strategy: {ng_strategy.upper()}")
            
            if ng_strategy == "on-demand":
                print(f"   On-Demand Instance Types: {', '.join(instance_selections.get('on-demand', []))}")
            elif ng_strategy == "spot":
                print(f"   Spot Instance Types: {', '.join(instance_selections.get('spot', []))}")
            else:
                print(f"   On-Demand Instance Types: {', '.join(instance_selections.get('on-demand', []))}")
                print(f"   Spot Instance Types: {', '.join(instance_selections.get('spot', []))}")
                print(f"   On-Demand Percentage: {instance_selections.get('on_demand_percentage', 50)}%")
            
            print(f"   Nodegroup Scaling: Min={min_nodes}, Desired={desired_nodes}, Max={max_nodes}")
            
            # Ask for confirmation
            confirm = input("\nDo you want to proceed with cluster creation? (y/n): ").strip().lower()
            if confirm != 'y':
                print("❌ Cluster creation cancelled")
                return False
            
            # Create EKS cluster with nodegroups
            result = self.eks_manager.create_cluster(cluster_config)
            
            if result:
                print("\n✅ EKS Cluster created successfully!")
                return True
            else:
                print("\n❌ EKS Cluster creation failed")
                return False
            
        except Exception as e:
            print(f"\n❌ Error during automation: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def select_ondemand_instance_types(self, credentials: CredentialInfo, allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for On-Demand nodegroup"""
        region = credentials.regions[0]
        
        print("\n💰 ON-DEMAND INSTANCE TYPE SELECTION")
        print("-" * 60)
        print("Analyzing service quotas for On-Demand instances...")
        
        # Get quota information
        quota_info = self.spot_analyzer.analyze_service_quotas(credentials, allowed_types)
        
        # Display quota information
        print("\n📊 Service Quota Analysis:")
        print("-" * 50)
        
        # Sort instance types by available quota
        instance_data = []
        
        for instance_type in allowed_types:
            family = instance_type.split('.')[0]
            if family in quota_info:
                quota = quota_info[family]
                available = quota.available_capacity
                used = f"{quota.current_usage}/{quota.quota_limit}"
            else:
                available = "Unknown"
                used = "Unknown"
            
            instance_data.append({
                'type': instance_type,
                'available': available if isinstance(available, int) else 0,
                'used': used
            })
        
        # Sort by available capacity (highest first)
        sorted_instances = sorted(instance_data, key=lambda x: -x['available'])
        
        # Display all instance types with quota info
        print(f"{'#':<3} {'Type':<12} {'Available Quota':<15} {'Used':<10}")
        print("-" * 50)
        
        for i, instance in enumerate(sorted_instances, 1):
            print(f"{i:<3} {instance['type']:<12} {instance['available']:<15} {instance['used']:<10}")
        
        # Choose instance types
        selected_types = self.multi_select_instance_types(
            [instance['type'] for instance in sorted_instances],
            "On-Demand"
        )
        
        return {'on-demand': selected_types}
    
    def select_spot_instance_types(self, credentials: CredentialInfo, allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for Spot nodegroup with analysis"""
        print("\n📈 SPOT INSTANCE TYPE SELECTION")
        print("-" * 60)
        
        # Ask for refresh preference
        refresh_choice = input("Use cached spot data if available? (y/n): ").strip().lower()
        force_refresh = refresh_choice == 'n'
        
        print("Analyzing spot instances and service quotas...")
        
        # Get spot analysis
        spot_analyses = self.spot_analyzer.analyze_spot_instances(credentials, allowed_types, force_refresh)
        
        # Group by instance type and choose best AZ for each
        best_spots = {}
        for analysis in spot_analyses:
            instance_type = analysis.instance_type
            if (instance_type not in best_spots or 
                analysis.score > best_spots[instance_type].score):
                best_spots[instance_type] = analysis
        
        # Sort by score (descending)
        sorted_spots = sorted(best_spots.values(), key=lambda x: x.score, reverse=True)
        
        # Display spot analysis results
        print("\n📊 SPOT INSTANCE ANALYSIS RESULTS")
        print("-" * 80)
        
        print(f"{'#':<3} {'Type':<10} {'Zone':<15} {'Price':<8} {'Score':<6} {'Interrupt':<15}")
        print("-" * 80)
        
        for i, analysis in enumerate(sorted_spots, 1):
            print(f"{i:<3} {analysis.instance_type:<10} {analysis.availability_zone:<15} "
                  f"${analysis.current_price:<7.4f} {analysis.score:<6.1f} "
                  f"{analysis.interruption_rate}")
        
        # Choose instance types
        selected_types = self.multi_select_instance_types(
            [analysis.instance_type for analysis in sorted_spots],
            "Spot"
        )
        
        return {'spot': selected_types}
    
    def select_mixed_instance_types(self, credentials: CredentialInfo, allowed_types: List[str]) -> Dict[str, List[str]]:
        """Select instance types for Mixed nodegroup strategy"""
        print("\n🔄 MIXED STRATEGY INSTANCE TYPE SELECTION")
        print("-" * 60)
        
        # Get On-Demand types
        print("Step 1: Select On-Demand instance types")
        ondemand_selection = self.select_ondemand_instance_types(credentials, allowed_types)
        
        # Get Spot types
        print("\nStep 2: Select Spot instance types")
        spot_selection = self.select_spot_instance_types(credentials, allowed_types)
        
        # Get On-Demand percentage
        print("\n⚖️ On-Demand vs Spot Percentage")
        print("-" * 50)
        print("Default: 50% On-Demand, 50% Spot")
        
        while True:
            try:
                percentage = input("Enter On-Demand percentage (0-100, default 50): ").strip()
                if not percentage:
                    percentage = 50
                else:
                    percentage = int(percentage)
                
                if 0 <= percentage <= 100:
                    break
                else:
                    print("❌ Please enter a value between 0 and 100")
            except ValueError:
                print("❌ Please enter a valid number")
        
        return {
            'on-demand': ondemand_selection['on-demand'],
            'spot': spot_selection['spot'],
            'on_demand_percentage': percentage
        }
    
    def multi_select_instance_types(self, available_types: List[str], strategy_name: str) -> List[str]:
        """Allow user to select multiple instance types"""
        if not available_types:
            print(f"⚠️ No {strategy_name} instance types available")
            return []
            
        print(f"\n📝 Select {strategy_name} Instance Types:")
        print("You can select multiple types for better availability")
        print("-" * 50)
        
        for i, instance_type in enumerate(available_types, 1):
            print(f"  {i:2}. {instance_type}")
        
        print("\nSelection format:")
        print("  Single: 1")
        print("  Multiple: 1,3,5")
        print("  Range: 1-4")
        print("  Combined: 1,3,5-8")
        print("  All: 'all'")
        
        while True:
            try:
                selection = input(f"Select {strategy_name} instance types: ").strip()
                
                if selection.lower() == 'all':
                    selected_types = available_types
                    print(f"✅ Selected all {len(selected_types)} {strategy_name} types")
                    return selected_types
                    
                selected_indices = self.parse_selection(selection, len(available_types))
                
                if selected_indices:
                    selected_types = [available_types[i-1] for i in selected_indices]
                    print(f"✅ Selected {strategy_name} types: {', '.join(selected_types)}")
                    return selected_types
                else:
                    print("❌ No valid selection made")
            except ValueError as e:
                print(f"❌ {e}")
    
    def parse_selection(self, selection: str, max_count: int) -> List[int]:
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
    
    def prompt_nodegroup_scaling(self, strategy: str) -> Tuple[int, int, int]:
        """Prompt user for nodegroup scaling configuration"""
        print("\n📊 NODEGROUP SCALING CONFIGURATION")
        print("-" * 60)
        
        # Default values based on strategy
        if strategy == "spot":
            default_min = 2
            default_desired = 2
            default_max = 6
        else:
            default_min = 2
            default_desired = 2
            default_max = 6
        
        print(f"Default scaling for {strategy.upper()} strategy:")
        print(f"  Min: {default_min}")
        print(f"  Desired: {default_desired}")
        print(f"  Max: {default_max}")
        
        use_defaults = input("\nUse default scaling values? (y/n): ").strip().lower()
        if use_defaults == 'y':
            return default_min, default_desired, default_max
        
        # Custom scaling values
        while True:
            try:
                min_nodes = int(input(f"Minimum nodes (default {default_min}): ").strip() or default_min)
                if min_nodes < 0:
                    print("❌ Minimum nodes must be >= 0")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        while True:
            try:
                desired_nodes = int(input(f"Desired nodes (default {default_desired}): ").strip() or default_desired)
                if desired_nodes < min_nodes:
                    print(f"❌ Desired nodes must be >= minimum nodes ({min_nodes})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        while True:
            try:
                max_nodes = int(input(f"Maximum nodes (default {default_max}): ").strip() or default_max)
                if max_nodes < desired_nodes:
                    print(f"❌ Maximum nodes must be >= desired nodes ({desired_nodes})")
                    continue
                break
            except ValueError:
                print("❌ Please enter a valid number")
        
        return min_nodes, desired_nodes, max_nodes

def main():
    """Main entry point"""
    automation = EKSAutomation()
    
    try:
        success = automation.run_automation()
        if success:
            print("\n🎉 EKS Cluster creation completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ EKS Cluster creation failed or was interrupted")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⏹️ Automation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()