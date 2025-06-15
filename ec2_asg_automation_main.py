"""
EC2 + ASG Automation Main Orchestrator
Enhanced with Root/IAM credential support and multiple ASG strategies
"""

import os
import sys
from datetime import datetime
from aws_credential_manager import AWSCredentialManager, CredentialInfo
from ec2_instance_manager import EC2InstanceManager
from auto_scaling_group_manager import AutoScalingGroupManager
from spot_instance_analyzer import SpotInstanceAnalyzer
import random
import string

class EC2ASGAutomation:
    def __init__(self):
        self.current_user = 'varadharajaan'
        self.current_time = '2025-06-13 05:13:24'
        self.credential_manager = AWSCredentialManager()
        self.ec2_manager = EC2InstanceManager()
        self.asg_manager = AutoScalingGroupManager(self.current_user, self.current_time)
        self.spot_analyzer = SpotInstanceAnalyzer()
        
        print("🚀 EC2 + ASG Automation Tool")
        print(f"👤 User: {self.current_user}")
        print(f"🕒 Time: {self.current_time}")
        print("="*60)
        
    @staticmethod
    def generate_random_suffix(length=4):
        """Generate a random alphanumeric suffix of specified length"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    
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
        
            # Step 3: Create EC2 instance or use launch template
            print("\n💻 STEP 2: EC2 INSTANCE CREATION")
            create_ec2 = input("Create new EC2 instance? (y/n): ").strip().lower()
        
            instance_details = None
            launch_template_id = None
        
            if create_ec2 == 'y':
                # Ask for instance strategy (on-demand vs spot)
                print("\n" + "="*60)
                print("🚀 EC2 INSTANCE STRATEGY SELECTION")
                print("="*60)
                print("Choose your EC2 strategy:")
                print("1. On-Demand (Reliable, Higher Cost)")
                print("2. Spot (Cost-Effective, Higher Risk)")
            
                ec2_strategy = None
                while True:
                    choice = input("Enter your choice (1-2): ").strip()
                    if choice == '1':
                        ec2_strategy = 'on-demand'
                        break
                    elif choice == '2':
                        ec2_strategy = 'spot'
                        break
                    else:
                        print("❌ Invalid choice. Please enter 1 or 2.")
            
                # Get allowed instance types for the region
                allowed_types = self.ec2_manager.get_allowed_instance_types(credentials.regions[0])
            
                # Select instance type based on strategy
                selected_type = None
            
                if ec2_strategy == 'on-demand':
                    # For on-demand, perform service quota analysis
                    print("\n" + "="*60)
                    print("💰 ON-DEMAND INSTANCE SELECTION")
                    print("="*60)
                    print("Analyzing service quotas for instance families...")
                
                    # Get quota information
                    quota_info = self.spot_analyzer.analyze_service_quotas(credentials, allowed_types)
                    
                    # Create a list with instance types and their availability for sorting
                    instance_availability = []
                    for instance_type in allowed_types:
                        family = instance_type.split('.')[0]
                        if family in quota_info:
                            quota = quota_info[family]
                            available = quota.available_capacity
                            used = f"{quota.current_usage}/{quota.quota_limit}"
                        else:
                            available = 32  # Default
                            used = "Unknown"
        
                        instance_availability.append({
                            'type': instance_type,
                            'available': available,
                            'used': used
                        })
    
                    # Sort by available capacity (highest first)
                    sorted_instances = sorted(instance_availability, key=lambda x: -x['available'])

                    # Display all instance types with quota info
                    print("\n📊 Available On-Demand Instances (Sorted by Availability):")
                    print("-" * 70)
                    print(f"{'#':<3} {'Type':<12} {'Available Quota':<15} {'Used':<10}")
                    print("-" * 70)

                    for i, instance in enumerate(sorted_instances, 1):
                        print(f"{i:<3} {instance['type']:<12} {instance['available']:<15} {instance['used']:<10}")

                    # Option to enter custom instance type
                    print("\n" + "-"*50)
                    print("Options:")
                    print("1. Select from the list")
                    print("2. Enter custom instance type")
                
                    selection_mode = input("Your choice (1-2): ").strip()
                
                    if selection_mode == '1':
                        while True:
                            try:
                                choice = int(input(f"\nSelect instance type (1-{len(allowed_types)}): ").strip())
                                if 1 <= choice <= len(allowed_types):
                                    selected_type = allowed_types[choice-1]
                                    break
                                else:
                                    print(f"❌ Please enter a number between 1 and {len(allowed_types)}")
                            except ValueError:
                                print("❌ Please enter a valid number")
                    else:
                        while True:
                            custom_type = input("\nEnter custom instance type (e.g., 't3.large'): ").strip()
                            if custom_type:
                                print(f"⚠️ Warning: Custom instance type '{custom_type}' selected. Ensure it's available in {credentials.regions[0]}.")
                                confirm = input("Confirm this selection? (y/n): ").strip().lower()
                                if confirm == 'y':
                                    selected_type = custom_type
                                    break
                            else:
                                print("❌ Please enter a valid instance type")
                
                else:  # spot strategy
                    # For spot, perform full spot analysis
                    print("\n" + "="*60)
                    print("📈 SPOT INSTANCE SELECTION")
                    print("="*60)
                    print("Analyzing spot instance availability and pricing...")
                
                    # Ask for refresh preference
                    refresh_choice = input("Use cached spot data if available? (y/n): ").strip().lower()
                    force_refresh = refresh_choice == 'n'
                
                    # Get spot analysis and quotas
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
                
                    # Display all spot options
                    print("\n" + "="*80)
                    print("📊 SPOT INSTANCE AVAILABILITY")
                    print("="*80)
                
                    print(f"{'#':<3} {'Type':<10} {'Zone':<15} {'Price':<8} {'Score':<6} {'Interrupt':<15}")
                    print("-" * 80)
                
                    # Display all sorted spot instances, not just the first 10
                    for i, analysis in enumerate(sorted_spots, 1):
                        print(f"{i:<3} {analysis.instance_type:<10} {analysis.availability_zone:<15} "
                              f"${analysis.current_price:<7.4f} {analysis.score:<6.1f} "
                              f"{analysis.interruption_rate}")
                
                    # Option to enter custom instance type
                    print("\n" + "-"*50)
                    print("Options:")
                    print("1. Select from the list")
                    print("2. Enter custom instance type")
                
                    selection_mode = input("Your choice (1-2): ").strip()
                
                    if selection_mode == '1':
                        while True:
                            try:
                                spot_choice = int(input(f"\nSelect spot instance (1-{len(sorted_spots)}): ").strip())
                                if 1 <= spot_choice <= len(sorted_spots):
                                    selected_spot = sorted_spots[spot_choice-1]
                                    selected_type = selected_spot.instance_type
                                    # Store AZ for potential use
                                    selected_az = selected_spot.availability_zone
                                    break
                                else:
                                    print(f"❌ Please enter a number between 1 and {len(sorted_spots)}")
                            except ValueError:
                                print("❌ Please enter a valid number")
                    else:
                        while True:
                            custom_type = input("\nEnter custom instance type (e.g., 't3.large'): ").strip()
                            if custom_type:
                                print(f"⚠️ Warning: Custom spot instance type '{custom_type}' selected. Ensure it's available in {credentials.regions[0]}.")
                                confirm = input("Confirm this selection? (y/n): ").strip().lower()
                                if confirm == 'y':
                                    selected_type = custom_type
                                    # For custom spot types, we don't have AZ information
                                    break
                            else:
                                print("❌ Please enter a valid instance type")
            
                # Create instance with the selected type and strategy
                instance_details = self.ec2_manager.create_ec2_instance(
                    credentials, 
                    instance_type=selected_type
                )
            
                launch_template_id = instance_details.get('launch_template_id')
                print(f"✅ EC2 instance created: {instance_details['instance_id']}")
                if ec2_strategy == 'spot':
                    print(f"   💡 Using spot pricing (strategy: {ec2_strategy})")
                
                # Invalidate service quota cache after creating an instance
                print("🔄 Updating service quota data after instance creation...")
                # Find and remove any quota cache files
                self.invalidate_quota_cache()
            else:
                # Ask for existing launch template
                launch_template_id = self.ec2_manager.select_existing_launch_template(credentials)
                if not launch_template_id:
                    # Create launch template without instance
                    from ec2_instance_manager import InstanceConfig
                
                    # Get allowed instance types
                    allowed_types = self.ec2_manager.get_allowed_instance_types(credentials.regions[0])
                
                    # Display all available instance types
                    print("\n📊 Available Instance Types:")
                    print("-" * 50)
                    for i, instance_type in enumerate(allowed_types, 1):
                        print(f"{i:<3} {instance_type}")
                
                    # Option for custom instance type
                    print("\n" + "-"*50)
                    print("Options:")
                    print("1. Select from the list")
                    print("2. Enter custom instance type")
                
                    selection_mode = input("Your choice (1-2): ").strip()
                
                    if selection_mode == '1':
                        while True:
                            try:
                                choice = int(input(f"\nSelect instance type (1-{len(allowed_types)}): ").strip())
                                if 1 <= choice <= len(allowed_types):
                                    selected_type = allowed_types[choice-1]
                                    break
                                else:
                                    print(f"❌ Please enter a number between 1 and {len(allowed_types)}")
                            except ValueError:
                                print("❌ Please enter a valid number")
                    else:
                        while True:
                            custom_type = input("\nEnter custom instance type (e.g., 't3.large'): ").strip()
                            if custom_type:
                                print(f"⚠️ Warning: Custom instance type '{custom_type}' selected. Ensure it's available in {credentials.regions[0]}.")
                                confirm = input("Confirm this selection? (y/n): ").strip().lower()
                                if confirm == 'y':
                                    selected_type = custom_type
                                    break
                            else:
                                print("❌ Please enter a valid instance type")
                
                    # Get AMI
                    ami_mapping = self.ec2_manager.ami_config.get('region_ami_mapping', {})
                    ami_id = ami_mapping.get(credentials.regions[0])
                
                    if not ami_id:
                        print(f"❌ No AMI found for region: {credentials.regions[0]}")
                        return False
                
                    enhanced_userdata = self.ec2_manager.prepare_userdata_with_aws_config(
                        self.ec2_manager.userdata_script,
                        credentials.access_key,
                        credentials.secret_key,
                        credentials.regions[0]
                    )
                    instance_config = InstanceConfig(
                        instance_type=selected_type,
                        ami_id=ami_id,
                        region=credentials.regions[0],
                        userdata_script=enhanced_userdata
                    )
                    import boto3
                    ec2_client = boto3.client(
                        'ec2',
                        aws_access_key_id=credentials.access_key,
                        aws_secret_access_key=credentials.secret_key,
                        region_name=credentials.regions[0]
                    )
                
                    launch_template_id = self.ec2_manager.create_launch_template(
                            ec2_client, credentials, instance_config, None  # Pass None for security_group_id
                    )
        
            # Step 4: Create Auto Scaling Group
            print("\n🚀 STEP 3: AUTO SCALING GROUP CREATION")
            create_asg = input("Create Auto Scaling Group? (y/n): ").strip().lower()
        
            if create_asg == 'y':
                # Select ASG strategy
                strategy = self.asg_manager.prompt_asg_strategy()
            
                # Get allowed instance types
                allowed_types = self.ec2_manager.get_allowed_instance_types(credentials.regions[0])
            
                # Modify the selection method to show all instance types and allow custom entry
                if strategy == 'on-demand':
                    # Get quota information
                    quota_info = self.spot_analyzer.analyze_service_quotas(credentials, allowed_types)
                
                    # Show all on-demand instances with quota info
                    print("\n📊 Available On-Demand Instances:")
                    print("-" * 70)
                    print(f"{'#':<3} {'Type':<12} {'Available Quota':<15} {'Used':<10}")
                    print("-" * 70)
                
                    for i, instance_type in enumerate(allowed_types, 1):
                        family = instance_type.split('.')[0]
                        if family in quota_info:
                            quota = quota_info[family]
                            available = quota.available_capacity
                            used = f"{quota.current_usage}/{quota.quota_limit}"
                        else:
                            available = "Unknown"
                            used = "Unknown"
                    
                        print(f"{i:<3} {instance_type:<12} {available:<15} {used:<10}")
                
                    # Allow custom selection
                    print("\nSelect multiple instance types (comma-separated, e.g. '1,3,5-7') or enter 'c' for custom:")
                    selection = input("> ").strip()
                
                    if selection.lower() == 'c':
                        custom_types = []
                        print("\nEnter custom instance types (one per line, empty line to finish):")
                        while True:
                            custom_type = input("> ").strip()
                            if not custom_type:
                                break
                            custom_types.append(custom_type)
                    
                        if custom_types:
                            print(f"⚠️ Warning: {len(custom_types)} custom instance types selected.")
                            confirm = input("Confirm these selections? (y/n): ").strip().lower()
                            if confirm == 'y':
                                ondemand_selection = {'on-demand': custom_types}
                            else:
                                print("❌ Custom selection cancelled.")
                                return False
                        else:
                            print("❌ No custom types entered.")
                            return False
                    else:
                        # Parse the selection
                        try:
                            selected_indices = self.asg_manager.parse_selection(selection, len(allowed_types))
                            selected_types = [allowed_types[i-1] for i in selected_indices]
                            ondemand_selection = {'on-demand': selected_types}
                        except ValueError as e:
                            print(f"❌ Error: {e}")
                            return False
            
                elif strategy == 'spot':
                    # Get spot analysis
                    refresh_choice = input("Use cached spot data if available? (y/n): ").strip().lower()
                    force_refresh = refresh_choice == 'n'
                
                    spot_analyses = self.spot_analyzer.analyze_spot_instances(credentials, allowed_types, force_refresh)
                
                    # Group and sort by instance type and best score
                    best_spots = {}
                    for analysis in spot_analyses:
                        instance_type = analysis.instance_type
                        if (instance_type not in best_spots or 
                            analysis.score > best_spots[instance_type].score):
                            best_spots[instance_type] = analysis
                
                    sorted_spots = sorted(best_spots.values(), key=lambda x: x.score, reverse=True)
                
                    # Show all spot instances
                    print("\n📊 Available Spot Instances:")
                    print("-" * 80)
                    print(f"{'#':<3} {'Type':<10} {'Zone':<15} {'Price':<8} {'Score':<6} {'Interrupt':<15}")
                    print("-" * 80)
                
                    for i, analysis in enumerate(sorted_spots, 1):
                        print(f"{i:<3} {analysis.instance_type:<10} {analysis.availability_zone:<15} "
                              f"${analysis.current_price:<7.4f} {analysis.score:<6.1f} "
                              f"{analysis.interruption_rate}")
                
                    # Allow custom selection
                    print("\nSelect multiple instance types (comma-separated, e.g. '1,3,5-7') or enter 'c' for custom:")
                    selection = input("> ").strip()
                
                    if selection.lower() == 'c':
                        custom_types = []
                        print("\nEnter custom instance types (one per line, empty line to finish):")
                        while True:
                            custom_type = input("> ").strip()
                            if not custom_type:
                                break
                            custom_types.append(custom_type)
                    
                        if custom_types:
                            print(f"⚠️ Warning: {len(custom_types)} custom instance types selected.")
                            confirm = input("Confirm these selections? (y/n): ").strip().lower()
                            if confirm == 'y':
                                spot_selection = {'spot': custom_types}
                            else:
                                print("❌ Custom selection cancelled.")
                                return False
                        else:
                            print("❌ No custom types entered.")
                            return False
                    else:
                        # Parse the selection
                        try:
                            selected_indices = self.asg_manager.parse_selection(selection, len(sorted_spots))
                            selected_types = [sorted_spots[i-1].instance_type for i in selected_indices]
                            spot_selection = {'spot': selected_types}
                        except ValueError as e:
                            print(f"❌ Error: {e}")
                            return False
            
                else:  # mixed
                    # On-demand selection
                    print("\n📊 On-Demand Instance Selection for Mixed Strategy:")
                    print("-" * 70)

                    # Get quota information
                    quota_info = self.spot_analyzer.analyze_service_quotas(credentials, allowed_types)

                    # Create a list with instance types and their availability for sorting
                    instance_availability = []
                    for instance_type in allowed_types:
                        family = instance_type.split('.')[0]
                        if family in quota_info:
                            quota = quota_info[family]
                            available = quota.available_capacity
                            used = f"{quota.current_usage}/{quota.quota_limit}"
                        else:
                            available = 32  # Default
                            used = "Unknown"

                        instance_availability.append({
                            'type': instance_type,
                            'available': available,
                            'used': used
                        })

                    # Sort by available capacity (highest first)
                    sorted_instances = sorted(instance_availability, key=lambda x: -x['available'])

                    # Display all instance types with quota info
                    print(f"{'#':<3} {'Type':<12} {'Available Quota':<15} {'Used':<10}")
                    print("-" * 70)

                    for i, instance in enumerate(sorted_instances, 1):
                        print(f"{i:<3} {instance['type']:<12} {instance['available']:<15} {instance['used']:<10}")

                    # Allow custom selection
                    print("\nSelect multiple on-demand instance types (comma-separated, e.g. '1,3,5-7') or enter 'c' for custom:")
                    selection = input("> ").strip()

                    if selection.lower() == 'c':
                        custom_ondemand_types = []
                        print("\nEnter custom on-demand instance types (one per line, empty line to finish):")
                        while True:
                            custom_type = input("> ").strip()
                            if not custom_type:
                                break
                            custom_ondemand_types.append(custom_type)
        
                        if not custom_ondemand_types:
                            print("❌ No custom on-demand types entered.")
                            return False
                        ondemand_types = custom_ondemand_types
                    else:
                        # Parse the selection
                        try:
                            selected_indices = self.asg_manager.parse_selection(selection, len(sorted_instances))
                            # Use the sorted instances list for selection, not the original allowed_types
                            ondemand_types = [sorted_instances[i-1]['type'] for i in selected_indices]
                        except ValueError as e:
                            print(f"❌ Error: {e}")
                            return False
            
                # Inside the run_automation method, after handling the mixed strategy instance type selection
                # If we're in on-demand or spot strategy, use the selections created above
                if strategy == 'on-demand':
                    instance_selections = ondemand_selection
                elif strategy == 'spot':
                    instance_selections = spot_selection
                else:  # mixed strategy
                    # Now we need spot instance types for mixed strategy
                    print("\n📊 Spot Instance Selection for Mixed Strategy:")
                    print("-" * 70)

                    # Spot analysis
                    refresh_choice = input("Use cached spot data for spot instances selection? (y/n): ").strip().lower()
                    force_refresh = refresh_choice == 'n'

                    spot_analyses = self.spot_analyzer.analyze_spot_instances(credentials, allowed_types, force_refresh)
                    best_spots = {}
                    for analysis in spot_analyses:
                        instance_type = analysis.instance_type
                        if (instance_type not in best_spots or 
                            analysis.score > best_spots[instance_type].score):
                            best_spots[instance_type] = analysis

                    sorted_spots = sorted(best_spots.values(), key=lambda x: x.score, reverse=True)

                    # Display all spot instances
                    print(f"{'#':<3} {'Type':<10} {'Zone':<15} {'Price':<8} {'Score':<6} {'Interrupt':<15}")
                    print("-" * 70)

                    for i, analysis in enumerate(sorted_spots, 1):
                        print(f"{i:<3} {analysis.instance_type:<10} {analysis.availability_zone:<15} "
                              f"${analysis.current_price:<7.4f} {analysis.score:<6.1f} "
                              f"{analysis.interruption_rate}")

                    # Allow custom selection
                    print("\nSelect multiple spot instance types (comma-separated, e.g. '1,3,5-7') or enter 'c' for custom:")
                    selection = input("> ").strip()

                    if selection.lower() == 'c':
                        custom_spot_types = []
                        print("\nEnter custom spot instance types (one per line, empty line to finish):")
                        while True:
                            custom_type = input("> ").strip()
                            if not custom_type:
                                break
                            custom_spot_types.append(custom_type)

                        if not custom_spot_types:
                            print("❌ No custom spot types entered.")
                            return False
                        spot_types = custom_spot_types
                    else:
                        # Parse the selection
                        try:
                            selected_indices = self.asg_manager.parse_selection(selection, len(sorted_spots))
                            spot_types = [sorted_spots[i-1].instance_type for i in selected_indices]
                        except ValueError as e:
                            print(f"❌ Error: {e}")
                            return False
    
                    # Get on-demand percentage for mixed strategy
                    print("\n" + "="*50)
                    print("⚖️ On-Demand vs Spot Percentage")
                    print("="*50)
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
    
                    # Now create the instance_selections dictionary for mixed strategy
                    instance_selections = {
                        'on-demand': ondemand_types,
                        'spot': spot_types,
                        'on_demand_percentage': percentage
                    }
                
                enable_scheduled_scaling = self.prompt_for_scheduled_scaling()

                if enable_scheduled_scaling:
                    print("🔄 Scheduled scaling enabled")
                    print("🔄 ASG will be created with scheduled scaling enabled")
                # Create ASG
                asg_details = self.asg_manager.create_asg_with_strategy(
                    credentials, instance_selections, launch_template_id, strategy, enable_scheduled_scaling
                )
            
                print(f"✅ Auto Scaling Group created: {asg_details['asg_name']}")
            
                # Optional: Schedule ASG
                
                #self.prompt_asg_scheduling(credentials, asg_details['asg_name'])
        
            # Step 5: Summary
            print("\n✅ AUTOMATION COMPLETED SUCCESSFULLY!")
            print("="*60)
            print("📋 SUMMARY:")
            print(f"   🔑 Credential Type: {credentials.credential_type.upper()}")
            print(f"   🏢 Account: {credentials.account_name}")
            print(f"   🆔 Email: {credentials.email}")
            print(f"   🌍 Region: {credentials.regions[0]}")
        
            if instance_details:
                print(f"   💻 EC2 Instance: {instance_details['instance_id']}")
                print(f"   📋 Launch Template: {instance_details['launch_template_id']}")
                if create_ec2 == 'y' and 'ec2_strategy' in locals():
                    print(f"   💲 EC2 Pricing: {ec2_strategy.upper()}")
        
            if create_asg == 'y':
                print(f"   🚀 ASG Name: {asg_details['asg_name']}")
                print(f"   📊 ASG Strategy: {asg_details['strategy'].upper()}")
        
            print(f"   📁 Output saved to: aws/ec2/{credentials.account_name}/")

            print("="*60)

            # Invalidate service quota cache after creating an instance
            print("🔄 Updating service quota data after instance creation...")
            # Find and remove any quota cache files
            self.invalidate_quota_cache()
        
            return True
        
        except KeyboardInterrupt:
            print("\n\n⏹️ Automation interrupted by user")
            return False
        except Exception as e:
            print(f"\n❌ Automation failed: {e}")
            return False

    def invalidate_quota_cache(self):
        """Invalidate service quota cache files to force refresh after instance changes"""
        try:
            cache_dir = self.spot_analyzer.cache_dir
            for file in os.listdir(cache_dir):
                if file.startswith('quotas_') or file.startswith('usage_'):
                    cache_file = os.path.join(cache_dir, file)
                    os.remove(cache_file)
                    print(f"   ♻️ Removed cache file: {file}")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not invalidate cache: {e}")


    def prompt_asg_scheduling(self, credentials: CredentialInfo, asg_name: str):
        """Optional ASG scheduling (9 AM - 6 PM IST)"""
        print("\n" + "="*60)
        print("⏰ OPTIONAL: ASG SCHEDULING")
        print("="*60)
        print("Schedule ASG to run only during business hours (9 AM - 6 PM IST)?")
        
        schedule_choice = input("Enable scheduling? (y/n): ").strip().lower()
        
        if schedule_choice == 'y':
            print("🚧 ASG Scheduling feature will be implemented in Phase 2")
            print("For now, ASG will run 24/7")
            
            # TODO: Implement ASG scheduling
            # - Create CloudWatch Events/EventBridge rules
            # - Create Lambda functions for scale up/down
            # - Schedule based on IST timezone
            pass
    
    def display_cache_options(self):
        """Display options for cache management"""
        print("\n" + "="*50)
        print("💾 CACHE MANAGEMENT OPTIONS")
        print("="*50)
        print("1. Use cached data (if available)")
        print("2. Force refresh all data")
        print("3. Clear cache and refresh")
        
        while True:
            choice = input("Select option (1-3): ").strip()
            if choice == '1':
                return False  # Don't force refresh
            elif choice == '2':
                return True   # Force refresh
            elif choice == '3':
                # Clear cache
                if os.path.exists(self.spot_analyzer.cache_file):
                    os.remove(self.spot_analyzer.cache_file)
                    print("🗑️ Cache cleared")
                return True   # Force refresh
            else:
                print("❌ Invalid choice. Please enter 1, 2, or 3.")

    def setup_unicode_support_bk(self):
        """Setup Unicode support for Windows terminals"""
        if sys.platform.startswith('win'):
            try:
                # Try to enable UTF-8 mode
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            except (AttributeError, UnicodeError):
                try:
                    import codecs
                    # Use UTF-8 codec with error handling
                    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
                    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')
                except Exception:
                    try:
                        # Last resort: use Windows console encoding
                        import locale
                        encoding = locale.getpreferredencoding()
                        sys.stdout = codecs.getwriter(encoding)(sys.stdout.buffer, 'replace')
                        sys.stderr = codecs.getwriter(encoding)(sys.stderr.buffer, 'replace')
                    except Exception:
                        # Final fallback
                        os.environ['PYTHONIOENCODING'] = 'utf-8:replace'
                        print("Warning: Using fallback encoding method")
        else:
            # For non-Windows systems, ensure UTF-8
            try:
                if sys.stdout.encoding.lower() != 'utf-8':
                    import codecs
                    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
                    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')
            except Exception:
                os.environ['PYTHONIOENCODING'] = 'utf-8:replace'

    def setup_unicode_support(self):
        """Setup Unicode support for Windows terminals"""
        if sys.platform.startswith('win'):
            try:
                # Method 1: Reconfigure stdout/stderr
                import codecs
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            except (AttributeError, UnicodeError):
                try:
                    # Method 2: Use codecs wrapper
                    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
                    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
                except:
                    # Method 3: Set environment variable
                    os.environ['PYTHONIOENCODING'] = 'utf-8'
                    print("Warning: Using fallback encoding method")

    def prompt_for_scheduled_scaling(self) -> bool:
            """Prompt user if they want to enable scheduled scaling"""
            print("\n" + "="*60)
            print("⏰ SCHEDULED SCALING CONFIGURATION")
            print("="*60)
            print("Do you want to enable scheduled scaling?")
            print("This will automatically scale your ASG up during business hours (9 AM IST)")
            print("and down after hours (7 PM IST) on weekdays (Monday-Friday)")
            print("-" * 60)
    
            while True:
                choice = input("Enable scheduled scaling? (y/n): ").strip().lower()
                if choice in ['y', 'yes']:
                    return True
                elif choice in ['n', 'no']:
                    return False
                else:
                    print("❌ Invalid choice. Please enter 'y' or 'n'.")

def main():
    
    """Main entry point"""
    automation = EC2ASGAutomation()
    automation.setup_unicode_support()
    
    try:
        success = automation.run_automation()
        if success:
            print("\n🎉 All operations completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Automation failed or was interrupted")
            sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()