"""
EC2 + ASG Automation Main Orchestrator
Enhanced with Root/IAM credential support and multiple user processing
"""

import os
import sys
from datetime import datetime
from ..aws_management.enhanced_aws_credential_manager import EnhancedAWSCredentialManager, MultiUserCredentials, CredentialInfo
from .ec2_instance_manager import EC2InstanceManager
from ..asg.auto_scaling_group_manager import AutoScalingGroupManager
from .spot_instance_analyzer import SpotInstanceAnalyzer
import random
import string
import concurrent.futures
import time
import boto3

class EC2ASGAutomation:
    def __init__(self):
        self.current_user = 'varadharajaan'
        self.current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.credential_manager = EnhancedAWSCredentialManager()
        self.ec2_manager = EC2InstanceManager()
        self.asg_manager = AutoScalingGroupManager(self.current_user, self.current_time)
        self.spot_analyzer = SpotInstanceAnalyzer()
        self.keypair_name = 'k8s_demo_key'

        print("🚀 EC2 + ASG Multi-User Automation Tool")
        print(f"👤 User: {self.current_user}")
        print(f"🕒 Time: {self.current_time}")
        print("="*60)

    def ensure_key_pair(self, region):
        key_name = self.keypair_name
        key_file = f"{key_name}.pem"
        if not os.path.exists(key_file):
            print(f"🔑 Key file {key_file} not found. Creating new key pair...")
            ec2 = boto3.client('ec2', region_name=region)
            key_pair = ec2.create_key_pair(KeyName=key_name)
            with open(key_file, 'w') as f:
                f.write(key_pair['KeyMaterial'])
            os.chmod(key_file, 0o400)
            print(f"✅ Key pair created and saved as {key_file}")
        else:
            print(f"🔑 Using existing key file: {key_file}")
        return key_name

    @staticmethod
    def generate_random_suffix(length=4):
        """Generate a random alphanumeric suffix of specified length"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def get_global_automation_preferences(self, first_credential: CredentialInfo) -> dict:
        """Get global preferences that will apply to all users"""
        print("\n⚙️ STEP 2: GLOBAL AUTOMATION PREFERENCES")
        print("These preferences will apply to ALL selected users/accounts")
        print("="*60)

        global_config = {}

        # EC2 Creation preference
        print("\n💻 EC2 INSTANCE CONFIGURATION")
        print("-" * 40)
        create_ec2 = input("Create EC2 instances for all users? (y/n): ").strip().lower() == 'y'
        global_config['create_ec2'] = create_ec2

        if create_ec2:
            # EC2 Strategy
            print("\n🚀 EC2 INSTANCE STRATEGY (for all users)")
            print("-" * 40)
            print("Choose EC2 strategy for all users:")
            print("1. On-Demand (Reliable, Higher Cost)")
            print("2. Spot (Cost-Effective, Higher Risk)")

            while True:
                choice = input("Enter your choice (1-2): ").strip()
                if choice == '1':
                    global_config['ec2_strategy'] = 'on-demand'
                    break
                elif choice == '2':
                    global_config['ec2_strategy'] = 'spot'
                    break
                else:
                    print("❌ Invalid choice. Please enter 1 or 2.")

            # Instance Type Selection (using first user's region for analysis)
            instance_type = self.select_global_instance_type(first_credential, global_config['ec2_strategy'])
            global_config['instance_type'] = instance_type

        # ASG Creation preference
        print("\n🚀 AUTO SCALING GROUP CONFIGURATION")
        print("-" * 40)
        create_asg = input("Create Auto Scaling Groups for all users? (y/n): ").strip().lower() == 'y'
        global_config['create_asg'] = create_asg

        if create_asg:
            # ASG Strategy
            asg_strategy = self.asg_manager.prompt_asg_strategy()
            global_config['asg_strategy'] = asg_strategy

            # Instance selections for ASG
            instance_selections = self.get_global_asg_instance_selections(asg_strategy, first_credential)
            global_config['asg_instance_selections'] = instance_selections

            # Scheduled scaling
            enable_scheduled = input("Enable scheduled scaling for all ASGs? (y/n): ").strip().lower() == 'y'
            global_config['enable_scheduled_scaling'] = enable_scheduled

        return global_config

    def select_global_instance_type(self, credential: CredentialInfo, ec2_strategy: str) -> str:
        """Select instance type for EC2 creation across all users"""
        print("\n📊 GLOBAL EC2 INSTANCE TYPE SELECTION")
        print("This instance type will be used for all users")
        print("-" * 50)

        # Get allowed types from first user's region
        allowed_types = self.ec2_manager.get_allowed_instance_types(credential.regions[0])

        if ec2_strategy == 'on-demand':
            # Show quota analysis for reference
            print("📊 Analyzing service quotas for reference...")
            quota_info = self.spot_analyzer.analyze_service_quotas(credential, allowed_types)

            print("\nAvailable Instance Types (with quota info):")
            for i, instance_type in enumerate(allowed_types, 1):
                family = instance_type.split('.')[0]
                if family in quota_info:
                    quota = quota_info[family]
                    available = quota.available_capacity
                    status = "✅" if available > 0 else "❌"
                else:
                    available = "Unknown"
                    status = "⚠️"
                print(f"  {i:2}. {instance_type} {status} (Available: {available})")
        else:
            # Show spot analysis for reference
            print("📊 Analyzing spot instances for reference...")
            spot_analyses = self.spot_analyzer.analyze_spot_instances(credential, allowed_types, False)

            # Get best spots
            best_spots = {}
            for analysis in spot_analyses:
                instance_type = analysis.instance_type
                if (instance_type not in best_spots or
                    analysis.score > best_spots[instance_type].score):
                    best_spots[instance_type] = analysis

            print("\nAvailable Instance Types (with spot info):")
            for i, instance_type in enumerate(allowed_types, 1):
                if instance_type in best_spots:
                    spot_info = best_spots[instance_type]
                    print(f"  {i:2}. {instance_type} - ${spot_info.current_price:.4f} (Score: {spot_info.score:.1f})")
                else:
                    print(f"  {i:2}. {instance_type} - No spot data")

        print(f"\n{len(allowed_types) + 1:2}. Custom instance type")

        while True:
            try:
                choice = input(f"Select instance type (1-{len(allowed_types) + 1}): ").strip()
                choice_num = int(choice)

                if 1 <= choice_num <= len(allowed_types):
                    selected_type = allowed_types[choice_num - 1]
                    print(f"✅ Selected: {selected_type} for all users")
                    return selected_type
                elif choice_num == len(allowed_types) + 1:
                    custom_type = input("Enter custom instance type: ").strip()
                    if custom_type:
                        print(f"✅ Selected custom type: {custom_type} for all users")
                        return custom_type
                    else:
                        print("❌ Please enter a valid instance type")
                else:
                    print(f"❌ Please enter a number between 1 and {len(allowed_types) + 1}")
            except ValueError:
                print("❌ Please enter a valid number")

    def get_global_asg_instance_selections(self, strategy: str, credential: CredentialInfo) -> dict:
        """Get ASG instance selections that will apply to all users"""
        print(f"\n📊 GLOBAL ASG INSTANCE SELECTION ({strategy.upper()} STRATEGY)")
        print("These instance types will be used for ASG across all users")
        print("-" * 60)

        allowed_types = self.ec2_manager.get_allowed_instance_types(credential.regions[0])

        if strategy == 'on-demand':
            return self.select_global_ondemand_instances(credential, allowed_types)
        elif strategy == 'spot':
            return self.select_global_spot_instances(credential, allowed_types)
        else:  # mixed
            return self.select_global_mixed_instances(credential, allowed_types)

    def select_global_ondemand_instances(self, credential: CredentialInfo, allowed_types: list) -> dict:
        """Select on-demand instances for global use"""
        print("📊 On-Demand Instance Analysis...")
        quota_info = self.spot_analyzer.analyze_service_quotas(credential, allowed_types)

        # Sort by availability
        instance_data = []
        for instance_type in allowed_types:
            family = instance_type.split('.')[0]
            if family in quota_info:
                quota = quota_info[family]
                available = quota.available_capacity
            else:
                available = 32

            instance_data.append({
                'type': instance_type,
                'available': available
            })

        sorted_instances = sorted(instance_data, key=lambda x: -x['available'])

        # Display available instances
        print(f"{'#':<3} {'Type':<12} {'Available':<10}")
        print("-" * 30)
        for i, instance in enumerate(sorted_instances, 1):
            print(f"{i:<3} {instance['type']:<12} {instance['available']:<10}")

        # Ask user to select instances
        print(f"\nPlease select instances for global use (1-{len(sorted_instances)}):")
        print("Enter comma-separated numbers (e.g., 1,3,5) or 'all' for all instances:")

        while True:
            try:
                user_input = input("Selection: ").strip()

                if user_input.lower() == 'all':
                    selected_indices = list(range(len(sorted_instances)))
                    break
                elif user_input.lower() in ['quit', 'exit', 'q']:
                    print("❌ Selection cancelled.")
                    return {'on-demand': []}
                else:
                    # Parse comma-separated numbers
                    selected_numbers = [int(x.strip()) for x in user_input.split(',')]

                    # Validate selection
                    if all(1 <= num <= len(sorted_instances) for num in selected_numbers):
                        selected_indices = [num - 1 for num in selected_numbers]  # Convert to 0-based index
                        break
                    else:
                        print(f"❌ Invalid selection. Please enter numbers between 1 and {len(sorted_instances)}")
                        continue

            except ValueError:
                print("❌ Invalid input. Please enter comma-separated numbers or 'all'")
                continue
            except KeyboardInterrupt:
                print("\n❌ Selection cancelled.")
                return {'on-demand': []}

        # Get selected instances
        selected_types = [sorted_instances[i]['type'] for i in selected_indices]

        print(f"\n✅ Selected {len(selected_types)} instances:")
        for i, instance_type in enumerate(selected_types, 1):
            available = next(inst['available'] for inst in sorted_instances if inst['type'] == instance_type)
            print(f"   {i}. {instance_type} (Available: {available})")

        return {'on-demand': selected_types}

    def select_global_spot_instances(self, credential: CredentialInfo, allowed_types: list) -> dict:
        """Select spot instances for global use"""
        print("📊 Spot Instance Analysis...")
        spot_analyses = self.spot_analyzer.analyze_spot_instances(credential, allowed_types, False)

        # Get best spots
        best_spots = {}
        for analysis in spot_analyses:
            instance_type = analysis.instance_type
            if (instance_type not in best_spots or
                    analysis.score > best_spots[instance_type].score):
                best_spots[instance_type] = analysis

        sorted_spots = sorted(best_spots.values(), key=lambda x: x.score, reverse=True)

        # Display available spot instances
        print(f"{'#':<3} {'Type':<10} {'Score':<6} {'Price':<8}")
        print("-" * 30)
        for i, analysis in enumerate(sorted_spots, 1):
            print(f"{i:<3} {analysis.instance_type:<10} {analysis.score:<6.1f} ${analysis.current_price:<7.4f}")

        # Ask user to select spot instances
        print(f"\nPlease select spot instances for global use (1-{len(sorted_spots)}):")
        print("Enter comma-separated numbers (e.g., 1,3,5) or 'all' for all instances:")

        while True:
            try:
                user_input = input("Selection: ").strip()

                if user_input.lower() == 'all':
                    selected_indices = list(range(len(sorted_spots)))
                    break
                elif user_input.lower() in ['quit', 'exit', 'q']:
                    print("❌ Selection cancelled.")
                    return {'spot': []}
                else:
                    # Parse comma-separated numbers
                    selected_numbers = [int(x.strip()) for x in user_input.split(',')]

                    # Validate selection
                    if all(1 <= num <= len(sorted_spots) for num in selected_numbers):
                        selected_indices = [num - 1 for num in selected_numbers]  # Convert to 0-based index
                        break
                    else:
                        print(f"❌ Invalid selection. Please enter numbers between 1 and {len(sorted_spots)}")
                        continue

            except ValueError:
                print("❌ Invalid input. Please enter comma-separated numbers or 'all'")
                continue
            except KeyboardInterrupt:
                print("\n❌ Selection cancelled.")
                return {'spot': []}

        # Get selected instances
        selected_analyses = [sorted_spots[i] for i in selected_indices]
        selected_types = [analysis.instance_type for analysis in selected_analyses]

        print(f"\n✅ Selected {len(selected_types)} spot instances:")
        for i, analysis in enumerate(selected_analyses, 1):
            print(
                f"   {i}. {analysis.instance_type} (Score: {analysis.score:.1f}, Price: ${analysis.current_price:.4f})")

        return {'spot': selected_types}


    def select_global_mixed_instances(self, credential: CredentialInfo, allowed_types: list) -> dict:
        """Select mixed instances for global use"""
        print("📊 Mixed Strategy Analysis...")

        ondemand_selection = self.select_global_ondemand_instances(credential, allowed_types)
        spot_selection = self.select_global_spot_instances(credential, allowed_types)

        # Default 50-50 split
        percentage = 50
        print(f"\nUsing default 50% On-Demand, 50% Spot for all users")

        return {
            'on-demand': ondemand_selection['on-demand'][:2],
            'spot': spot_selection['spot'][:2],
            'on_demand_percentage': percentage
        }

    def process_single_user(self, credential: CredentialInfo, global_config: dict, user_index: int, total_users: int) -> dict:
        """Process EC2 and ASG creation for a single user"""
        try:
            account_name = credential.account_name
            username = credential.username if credential.username else "ROOT"

            print(f"\n🔄 Processing User {user_index}/{total_users}: {account_name} - {username}")
            print("-" * 50)
            region = credential.regions[0]
            key_name = self.ensure_key_pair(region)

            result = {
                'user_index': user_index,
                'account': account_name,
                'username': username,
                'region': credential.regions[0],
                'credential_type': credential.credential_type,
                'status': 'success',
                'ec2_instance': None,
                'asg': None,
                'errors': [],
                'created_at': self.current_time,
                'keypair_name': key_name
            }

            # EC2 Instance Creation
            if global_config.get('create_ec2', False):
                try:
                    print(f"💻 Creating EC2 instance for {username} in {account_name}")
                    instance_details = self.ec2_manager.create_ec2_instance(
                        credential,
                        instance_type=global_config['instance_type']
                    )

                    result['ec2_instance'] = {
                        'instance_id': instance_details['instance_id'],
                        'launch_template_id': instance_details.get('launch_template_id'),
                        'strategy': global_config['ec2_strategy']
                    }

                    print(f"✅ EC2 created: {instance_details['instance_id']}")

                except Exception as e:
                    error_msg = f"EC2 creation failed: {str(e)}"
                    result['errors'].append(error_msg)
                    print(f"❌ {error_msg}")

            # ASG Creation
            if global_config.get('create_asg', False):
                try:
                    print(f"🚀 Creating ASG for {username} in {account_name}")

                    # Use launch template from EC2 or create new one
                    launch_template_id = None
                    if result['ec2_instance']:
                        launch_template_id = result['ec2_instance']['launch_template_id']
                    else:
                        # Create launch template for ASG
                        launch_template_id = self.create_launch_template_for_user(credential, global_config, key_name)

                    asg_details = self.asg_manager.create_asg_with_strategy(
                        credential,
                        global_config['asg_instance_selections'],
                        launch_template_id,
                        global_config['asg_strategy'],
                        global_config.get('enable_scheduled_scaling', False)
                    )

                    result['asg'] = {
                        'asg_name': asg_details['asg_name'],
                        'strategy': asg_details['strategy']
                    }

                    print(f"✅ ASG created: {asg_details['asg_name']}")

                except Exception as e:
                    error_msg = f"ASG creation failed: {str(e)}"
                    result['errors'].append(error_msg)
                    print(f"❌ {error_msg}")

            if result['errors']:
                result['status'] = 'partial'

            return result

        except Exception as e:
            print(f"❌ Error processing {username}: {e}")
            return {
                'user_index': user_index,
                'account': account_name,
                'username': username,
                'status': 'failed',
                'error': str(e)
            }

    # In create_launch_template_for_user
    def create_launch_template_for_user(self, credential: CredentialInfo, global_config: dict, key_name: str) -> str:
        from ec2_instance_manager import InstanceConfig
        import boto3

        ami_mapping = self.ec2_manager.ami_config.get('region_ami_mapping', {})
        ami_id = ami_mapping.get(credential.regions[0])
        if not ami_id:
            raise ValueError(f"No AMI found for region: {credential.regions[0]}")

        enhanced_userdata = self.ec2_manager.prepare_userdata_with_aws_config(
            self.ec2_manager.userdata_script,
            credential.access_key,
            credential.secret_key,
            credential.regions[0]
        )

        instance_config = InstanceConfig(
            instance_type=global_config.get('instance_type', 't3.micro'),
            ami_id=ami_id,
            region=credential.regions[0],
            userdata_script=enhanced_userdata,
            key_name=key_name  # Pass the key name here
        )

        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=credential.access_key,
            aws_secret_access_key=credential.secret_key,
            region_name=credential.regions[0]
        )

        # Ensure security groups are created and fetched
        launch_template_id = self.ec2_manager.create_launch_template(
            ec2_client, credential, instance_config
        )

        return launch_template_id

    def run_automation(self):
        """Main automation flow with multi-user processing"""
        try:
            # STEP 1: ENHANCED CREDENTIAL SELECTION
            print("\n🔑 STEP 1: ENHANCED CREDENTIAL SELECTION")
            print("Choose your credential type and select accounts/users")
            print("For IAM users, you'll be able to select from available credential files")

            # Use enhanced credential manager
            multi_credentials = self.credential_manager.get_multiple_credentials()

            if multi_credentials.total_users == 0:
                print("❌ No credentials selected. Exiting...")
                return False

            # Validate all credentials
            print(f"\n🔍 VALIDATING {multi_credentials.total_users} CREDENTIAL(S)")
            validated_credentials = self.credential_manager.validate_multiple_credentials(multi_credentials)

            if validated_credentials.total_users == 0:
                print("❌ No valid credentials found. Exiting...")
                return False

            print(f"✅ {validated_credentials.total_users} valid credential(s) ready for automation")

            # STEP 2: Get global preferences using first credential for analysis
            first_credential = validated_credentials.users[0]
            global_config = self.get_global_automation_preferences(first_credential)

            # STEP 3: Show summary and confirmation
            self.display_automation_summary(validated_credentials, global_config)

            proceed = input("\n🚀 Proceed with automation for all users? (Y/n): ").strip().lower()
            if proceed not in ['', 'y', 'yes']:
                print("❌ Automation cancelled by user")
                return False

            # STEP 4: Process all users
            print(f"\n🔄 STEP 3: PROCESSING {validated_credentials.total_users} USER(S)")

            # Ask for processing mode
            if validated_credentials.total_users > 1:
                processing_mode = input("Process users in parallel? (y/n, default: n): ").strip().lower()
                use_parallel = processing_mode == 'y'
            else:
                use_parallel = False

            # Process users
            if use_parallel:
                results = self.process_users_parallel(validated_credentials.users, global_config)
            else:
                results = self.process_users_sequential(validated_credentials.users, global_config)

            # STEP 5: Display final results
            self.display_final_results(results, global_config)

            return True

        except KeyboardInterrupt:
            print("\n\n⏹️ Automation interrupted by user")
            return False
        except Exception as e:
            print(f"\n❌ Automation failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def process_users_sequential(self, credentials: list, global_config: dict) -> list:
        """Process users one by one"""
        results = []
        total = len(credentials)

        for i, credential in enumerate(credentials, 1):
            result = self.process_single_user(credential, global_config, i, total)
            results.append(result)

            # Brief pause between users
            if i < total:
                time.sleep(1)

        return results

    def process_users_parallel(self, credentials: list, global_config: dict) -> list:
        """Process users in parallel"""
        results = []
        max_workers = min(len(credentials), 5)  # Limit concurrent operations

        print(f"🔄 Processing {len(credentials)} users with {max_workers} parallel workers...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_credential = {
                executor.submit(self.process_single_user, cred, global_config, i, len(credentials)): cred
                for i, cred in enumerate(credentials, 1)
            }

            for future in concurrent.futures.as_completed(future_to_credential):
                try:
                    result = future.result()
                    results.append(result)
                    credential = future_to_credential[future]
                    username = credential.username if credential.username else "ROOT"
                    print(f"✅ Completed: {credential.account_name} - {username}")
                except Exception as e:
                    credential = future_to_credential[future]
                    username = credential.username if credential.username else "ROOT"
                    print(f"❌ Failed: {credential.account_name} - {username} - {e}")

        # Sort results by user_index
        results.sort(key=lambda x: x.get('user_index', 0))
        return results

    def display_automation_summary(self, validated_credentials: MultiUserCredentials, global_config: dict):
        """Display automation summary before execution"""
        print("\n" + "="*70)
        print("📋 AUTOMATION SUMMARY")
        print("="*70)

        print(f"🔑 Credential Type: {validated_credentials.credential_type.upper()}")
        print(f"📊 Total Users: {validated_credentials.total_users}")

        print(f"\n🏢 Selected Users:")
        for i, cred in enumerate(validated_credentials.users, 1):
            username = cred.username if cred.username else "ROOT"
            print(f"  {i:2}. {cred.account_name} - {username} ({cred.regions[0]})")

        print(f"\n⚙️ Global Configuration:")
        print(f"   💻 Create EC2: {'Yes' if global_config.get('create_ec2') else 'No'}")
        if global_config.get('create_ec2'):
            print(f"   🖥️ EC2 Strategy: {global_config.get('ec2_strategy', 'N/A').upper()}")
            print(f"   🔧 Instance Type: {global_config.get('instance_type', 'N/A')}")

        print(f"   🚀 Create ASG: {'Yes' if global_config.get('create_asg') else 'No'}")
        if global_config.get('create_asg'):
            print(f"   📊 ASG Strategy: {global_config.get('asg_strategy', 'N/A').upper()}")
            print(f"   ⏰ Scheduled: {'Yes' if global_config.get('enable_scheduled_scaling') else 'No'}")

        print("="*70)

    def display_final_results(self, results: list, global_config: dict):
        """Display final automation results"""
        print("\n" + "="*80)
        print("🎉 MULTI-USER AUTOMATION COMPLETED!")
        print("="*80)

        successful = [r for r in results if r['status'] == 'success']
        partial = [r for r in results if r['status'] == 'partial']
        failed = [r for r in results if r['status'] == 'failed']

        print(f"📊 OVERALL RESULTS:")
        print(f"   ✅ Fully Successful: {len(successful)}")
        print(f"   ⚠️ Partially Successful: {len(partial)}")
        print(f"   ❌ Failed: {len(failed)}")
        print(f"   📋 Total Processed: {len(results)}")

        if successful:
            print(f"\n✅ FULLY SUCCESSFUL DEPLOYMENTS:")
            print("-" * 60)
            for result in successful:
                print(f"🏢 {result['account']} - {result['username']}")
                print(f"   🌍 Region: {result['region']}")

                if result.get('ec2_instance'):
                    print(f"   💻 EC2: {result['ec2_instance']['instance_id']}")
                    print(f"   🖥️ Strategy: {result['ec2_instance']['strategy'].upper()}")

                if result.get('asg'):
                    print(f"   🚀 ASG: {result['asg']['asg_name']}")
                    print(f"   📊 ASG Strategy: {result['asg']['strategy'].upper()}")
                print()

        if partial:
            print(f"\n⚠️ PARTIALLY SUCCESSFUL DEPLOYMENTS:")
            print("-" * 60)
            for result in partial:
                print(f"🏢 {result['account']} - {result['username']}")
                for error in result.get('errors', []):
                    print(f"   ❌ {error}")
                print()

        if failed:
            print(f"\n❌ FAILED DEPLOYMENTS:")
            print("-" * 60)
            for result in failed:
                print(f"🏢 {result['account']} - {result['username']}")
                print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
                print()

        print("="*80)

    def invalidate_quota_cache(self):
        """Invalidate service quota cache files"""
        try:
            cache_dir = self.spot_analyzer.cache_dir
            for file in os.listdir(cache_dir):
                if file.startswith('quotas_') or file.startswith('usage_'):
                    cache_file = os.path.join(cache_dir, file)
                    os.remove(cache_file)
                    print(f"   ♻️ Removed cache file: {file}")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not invalidate cache: {e}")

    def setup_unicode_support(self):
        """Setup Unicode support for Windows terminals"""
        if sys.platform.startswith('win'):
            try:
                import codecs
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            except (AttributeError, UnicodeError):
                try:
                    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
                    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
                except:
                    os.environ['PYTHONIOENCODING'] = 'utf-8'
                    print("Warning: Using fallback encoding method")

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
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()