"""
EC2 + ASG Automation Main Orchestrator
Enhanced with Safety Features, Logging, and Rollback Capabilities
"""

import os
import sys
import json
import logging
from datetime import datetime
from enhanced_aws_credential_manager import EnhancedAWSCredentialManager, MultiUserCredentials, CredentialInfo
from ec2_instance_manager import EC2InstanceManager
from auto_scaling_group_manager import AutoScalingGroupManager
from spot_instance_analyzer import SpotInstanceAnalyzer
import random
import string
import concurrent.futures
import time
import boto3
import threading
import argparse

class SafetyLogger:
    def __init__(self, log_dir='logs'):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        # Create timestamped log file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = os.path.join(log_dir, f'ec2_automation_{timestamp}.log')

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def log_action(self, level, message, resource_id=None, account=None):
        """Log actions with context"""
        context = f"[{account}:{resource_id}]" if account and resource_id else f"[{account}]" if account else ""
        full_message = f"{context} {message}"

        if level.upper() == 'INFO':
            self.logger.info(full_message)
        elif level.upper() == 'WARNING':
            self.logger.warning(full_message)
        elif level.upper() == 'ERROR':
            self.logger.error(full_message)
        elif level.upper() == 'CRITICAL':
            self.logger.critical(full_message)

class EC2ASGAutomation:
    keypair_lock = threading.Lock()

    def __init__(self, dry_run=False, max_resources=50):
        self.dry_run = dry_run
        self.max_resources_per_session = max_resources
        self.current_user = 'varadharajaan'
        self.current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.generate_random_suffix()}"

        # Initialize safety logger
        self.safety_logger = SafetyLogger()
        self.created_resources = []

        # Initialize managers
        self.credential_manager = EnhancedAWSCredentialManager()
        self.ec2_manager = EC2InstanceManager()
        self.asg_manager = AutoScalingGroupManager(self.current_user, self.current_time)
        self.spot_analyzer = SpotInstanceAnalyzer()
        self.keypair_name = 'k8s_demo_key'

        # Log session start
        self.safety_logger.log_action('INFO', f"Starting automation session {self.session_id}")
        if self.dry_run:
            self.safety_logger.log_action('INFO', "Running in DRY-RUN mode")

        print("🚀 EC2 + ASG Multi-User Automation Tool")
        print(f"👤 User: {self.current_user}")
        print(f"🕒 Time: {self.current_time}")
        print(f"🔑 Session ID: {self.session_id}")
        if self.dry_run:
            print("🧪 DRY-RUN MODE: No actual resources will be created")
        print("="*60)

    @staticmethod
    def generate_random_suffix(length=4):
        """Generate a random alphanumeric suffix of specified length"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def track_created_resource(self, resource_id, resource_type, credential, region, metadata=None):
        """Track created resources for potential rollback"""
        resource_info = {
            'resource_id': resource_id,
            'resource_type': resource_type,
            'account': credential.account_name,
            'account_id': credential.account_id,
            'region': region,
            'created_at': datetime.now(),
            'session_id': self.session_id,
            'access_key': credential.access_key,
            'secret_key': credential.secret_key,
            'metadata': metadata or {}
        }
        self.created_resources.append(resource_info)

        # Save to persistent file
        self.save_session_state()

        # Log creation
        self.safety_logger.log_action('INFO',
            f"Created {resource_type}: {resource_id}",
            resource_id=resource_id,
            account=credential.account_name)

    def save_session_state(self):
        """Save session state to file for rollback capability"""
        session_file = f"session_{self.session_id}.json"
        try:
            with open(session_file, 'w') as f:
                json.dump({
                    'session_id': self.session_id,
                    'created_at': datetime.now().isoformat(),
                    'user': self.current_user,
                    'dry_run': self.dry_run,
                    'created_resources': [{
                        'resource_id': r['resource_id'],
                        'resource_type': r['resource_type'],
                        'account': r['account'],
                        'account_id': r['account_id'],
                        'region': r['region'],
                        'created_at': r['created_at'].isoformat(),
                        'session_id': r['session_id'],
                        'access_key': r['access_key'],
                        'secret_key': r['secret_key'],
                        'metadata': r['metadata']
                    } for r in self.created_resources]
                }, f, indent=2)
        except Exception as e:
            self.safety_logger.log_action('ERROR', f"Failed to save session state: {e}")

    def is_production_environment(self, account_name):
        """Check if account appears to be production"""
        prod_indicators = ['prod', 'production', 'live', 'main', 'master']
        return any(indicator in account_name.lower() for indicator in prod_indicators)

    def has_critical_resources(self, credential):
        """Check for critical resources that shouldn't be modified"""
        try:
            ec2 = boto3.client(
                'ec2',
                aws_access_key_id=credential.access_key,
                aws_secret_access_key=credential.secret_key,
                region_name=credential.regions[0]
            )

            # Check for running instances with critical tags
            instances = ec2.describe_instances()
            for reservation in instances['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] == 'running':
                        for tag in instance.get('Tags', []):
                            if tag['Key'].lower() in ['critical', 'production'] and tag['Value'].lower() == 'true':
                                return True
            return False
        except Exception:
            return True  # Err on side of caution

    def perform_safety_checks(self, credentials, global_config):
        """Perform safety checks before execution"""
        safety_issues = []

        # Check for production indicators
        for cred in credentials:
            if self.is_production_environment(cred.account_name):
                safety_issues.append(f"🚨 PRODUCTION account detected: {cred.account_name}")

        # Check for existing critical resources
        for cred in credentials:
            if self.has_critical_resources(cred):
                safety_issues.append(f"⚠️ Critical resources found in {cred.account_name}")

        # Check resource limits
        total_expected = self.calculate_expected_resources(credentials, global_config)
        if total_expected > self.max_resources_per_session:
            safety_issues.append(f"📊 Too many resources ({total_expected}) exceeds limit ({self.max_resources_per_session})")

        if safety_issues:
            print("\n🚨 SAFETY WARNINGS:")
            for issue in safety_issues:
                print(f"   {issue}")
                self.safety_logger.log_action('WARNING', issue)

            if not self.dry_run:
                proceed = input("\nContinue despite warnings? (type 'YES' to confirm): ")
                if proceed != 'YES':
                    raise Exception("Execution cancelled due to safety concerns")

    def calculate_expected_resources(self, credentials, global_config):
        """Calculate total expected resources to be created"""
        total = 0
        per_user = 0

        if global_config.get('create_ec2'):
            per_user += 1

        if global_config.get('create_asg'):
            per_user += 2  # ASG + Launch Template

        total = len(credentials) * per_user
        return total

    def tag_created_resources(self, resource_id, resource_type, credential, ec2_client=None):
        """Tag resources with protection and metadata"""
        try:
            if not ec2_client:
                ec2_client = boto3.client(
                    'ec2',
                    aws_access_key_id=credential.access_key,
                    aws_secret_access_key=credential.secret_key,
                    region_name=credential.regions[0]
                )

            protection_tags = [
                {'Key': 'CreatedBy', 'Value': 'EC2ASGAutomation'},
                {'Key': 'CreatedAt', 'Value': datetime.now().isoformat()},
                {'Key': 'CreatedByUser', 'Value': self.current_user},
                {'Key': 'AutomationSession', 'Value': self.session_id},
                {'Key': 'Environment', 'Value': 'Development'},
                {'Key': 'ManagedBy', 'Value': 'Automation'}
            ]

            if resource_type in ['instance', 'launch-template']:
                ec2_client.create_tags(Resources=[resource_id], Tags=protection_tags)

            self.safety_logger.log_action('INFO',
                f"Tagged {resource_type} {resource_id} with protection tags",
                resource_id=resource_id,
                account=credential.account_name)

        except Exception as e:
            self.safety_logger.log_action('WARNING',
                f"Failed to tag {resource_type} {resource_id}: {e}",
                resource_id=resource_id,
                account=credential.account_name)

    def ensure_key_pair(self, region, credential=None):
        import botocore

        key_name = self.keypair_name
        key_file = f"{key_name}.pem"
        public_key_file = f"{key_name}.pub"

        # Use credential if provided, else default
        if credential:
            ec2 = boto3.client(
                'ec2',
                aws_access_key_id=credential.access_key,
                aws_secret_access_key=credential.secret_key,
                region_name=region
            )
        else:
            ec2 = boto3.client('ec2', region_name=region)

        with self.keypair_lock:
            try:
                ec2.describe_key_pairs(KeyNames=[key_name])
                self.safety_logger.log_action('INFO', f"Key pair '{key_name}' already exists in region {region}")
                print(f"🔑 Key pair '{key_name}' already exists in region {region}")
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'InvalidKeyPair.NotFound':
                    if self.dry_run:
                        print(f"🧪 DRY-RUN: Would import key pair '{key_name}' in region {region}")
                        self.safety_logger.log_action('INFO', f"DRY-RUN: Would import key pair '{key_name}' in region {region}")
                    else:
                        print(f"🔑 Key pair '{key_name}' not found in region {region}. Importing public key...")
                        if not os.path.exists(public_key_file):
                            raise FileNotFoundError(f"Public key file '{public_key_file}' not found.")
                        with open(public_key_file, 'r') as pubf:
                            public_key_material = pubf.read()
                        ec2.import_key_pair(KeyName=key_name, PublicKeyMaterial=public_key_material)
                        print(f"✅ Imported public key as key pair '{key_name}' in region {region}")
                        self.safety_logger.log_action('INFO', f"Imported key pair '{key_name}' in region {region}")
                else:
                    raise

            if not os.path.exists(key_file) and not self.dry_run:
                raise FileNotFoundError(f"Private key file '{key_file}' not found locally. Please provide it.")

            if not self.dry_run:
                print(f"🔑 Using local private key file: {key_file}")

        return key_name

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
        print("Or enter 'cus' to specify custom instance types:")

        while True:
            try:
                user_input = input("Selection: ").strip()

                if user_input.lower() == 'all':
                    selected_indices = list(range(len(sorted_instances)))
                    break
                elif user_input.lower() == 'cus' or user_input.lower() == 'custom':
                    print("\nEnter custom instance types (comma-separated):")
                    print("Example: t3.micro,t3.small,m5.large")
                    custom_input = input("Custom types: ").strip()

                    if custom_input:
                        custom_types = [t.strip() for t in custom_input.split(',')]
                        print(f"\n✅ Selected {len(custom_types)} custom instances:")
                        for i, instance_type in enumerate(custom_types, 1):
                            print(f"   {i}. {instance_type}")
                        return {'on-demand': custom_types}
                    else:
                        print("❌ Please enter valid instance types")
                        continue
                elif user_input.lower() in ['quit', 'exit', 'q']:
                    print("❌ Selection cancelled.")
                    return {'on-demand': []}
                else:
                    # Parse comma-separated numbers
                    selected_numbers = [int(x.strip()) for x in user_input.split(',')]

                    # Validate selection
                    if all(1 <= num <= len(sorted_instances) for num in selected_numbers):
                        selected_indices = [num - 1 for num in selected_numbers]
                        break
                    else:
                        print(f"❌ Please enter numbers between 1 and {len(sorted_instances)}")
                        continue

            except ValueError:
                print("❌ Invalid input. Please enter comma-separated numbers, 'all', or 'custom'")
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
                        selected_indices = [num - 1 for num in selected_numbers]
                        break
                    else:
                        print(f"❌ Please enter numbers between 1 and {len(sorted_spots)}")
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

            self.safety_logger.log_action('INFO',
                f"Starting processing for user {user_index}/{total_users}: {username}",
                account=account_name)

            region = credential.regions[0]
            key_name = self.ensure_key_pair(region, credential)

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
                    self.safety_logger.log_action('INFO',
                        f"Creating EC2 instance for {username}",
                        account=account_name)

                    if self.dry_run:
                        print(f"🧪 DRY-RUN: Would create {global_config['instance_type']} instance")
                        result['ec2_instance'] = {
                            'instance_id': f'dry-run-i-{self.generate_random_suffix()}',
                            'instance_type': global_config['instance_type'],
                            'dry_run': True
                        }
                    else:
                        instance_details = self.ec2_manager.create_ec2_instance(
                            credential, global_config['instance_type']
                        )

                        # Track and tag the resource
                        self.track_created_resource(
                            instance_details['instance_id'],
                            'instance',
                            credential,
                            region,
                            {'instance_type': global_config['instance_type']}
                        )

                        self.tag_created_resources(
                            instance_details['instance_id'],
                            'instance',
                            credential
                        )

                        result['ec2_instance'] = instance_details

                    print(f"   ✅ EC2 instance created successfully")

                except Exception as e:
                    error_msg = f"EC2 creation failed: {e}"
                    print(f"   ❌ {error_msg}")
                    result['errors'].append(error_msg)
                    self.safety_logger.log_action('ERROR', error_msg, account=account_name)

            # ASG Creation
            if global_config.get('create_asg', False):
                try:
                    self.safety_logger.log_action('INFO',
                        f"Creating ASG for {username}",
                        account=account_name)

                    if self.dry_run:
                        print(f"🧪 DRY-RUN: Would create ASG with {global_config['asg_strategy']} strategy")
                        result['asg'] = {
                            'asg_name': f'dry-run-asg-{self.generate_random_suffix()}',
                            'launch_template_id': f'dry-run-lt-{self.generate_random_suffix()}',
                            'strategy': global_config['asg_strategy'],
                            'dry_run': True
                        }
                    else:
                        # Create launch template first
                        launch_template_id = self.create_launch_template_for_user(
                            credential, global_config, key_name
                        )

                        # Track launch template
                        self.track_created_resource(
                            launch_template_id,
                            'launch-template',
                            credential,
                            region,
                            {'strategy': global_config['asg_strategy']}
                        )

                        self.tag_created_resources(
                            launch_template_id,
                            'launch-template',
                            credential
                        )

                        # Create ASG
                        asg_details = self.asg_manager.create_auto_scaling_group(
                            credential,
                            launch_template_id,
                            global_config['asg_strategy'],
                            global_config.get('asg_instance_selections', {}),
                            global_config.get('enable_scheduled_scaling', False)
                        )

                        # Track ASG
                        self.track_created_resource(
                            asg_details['asg_name'],
                            'auto-scaling-group',
                            credential,
                            region,
                            {
                                'launch_template_id': launch_template_id,
                                'strategy': global_config['asg_strategy']
                            }
                        )

                        result['asg'] = asg_details

                    print(f"   ✅ ASG created successfully")

                except Exception as e:
                    error_msg = f"ASG creation failed: {e}"
                    print(f"   ❌ {error_msg}")
                    result['errors'].append(error_msg)
                    self.safety_logger.log_action('ERROR', error_msg, account=account_name)

            if result['errors']:
                result['status'] = 'partial'

            self.safety_logger.log_action('INFO',
                f"Completed processing for {username} with status: {result['status']}",
                account=account_name)

            return result

        except Exception as e:
            error_msg = f"Error processing {username}: {e}"
            print(f"❌ {error_msg}")
            self.safety_logger.log_action('ERROR', error_msg, account=account_name)
            return {
                'user_index': user_index,
                'account': account_name,
                'username': username,
                'status': 'failed',
                'error': str(e)
            }

    def create_launch_template_for_user(self, credential: CredentialInfo, global_config: dict, key_name: str) -> str:
        """Create a launch template for the ASG"""
        from ec2_instance_manager import InstanceConfig

        # Get AMI for region
        ami_mapping = self.ec2_manager.ami_config.get('region_ami_mapping', {})
        ami_id = ami_mapping.get(credential.regions[0])
        if not ami_id:
            raise ValueError(f"No AMI found for region: {credential.regions[0]}")

        # Prepare userdata
        enhanced_userdata = self.ec2_manager.prepare_userdata_with_aws_config(
            self.ec2_manager.userdata_script,
            credential.access_key,
            credential.secret_key,
            credential.regions[0]
        )

        # Use first selected instance type from on-demand or spot for the launch template
        instance_types = []
        if 'asg_instance_selections' in global_config:
            selections = global_config['asg_instance_selections']
            if selections.get('on-demand'):
                instance_types = selections['on-demand']
            elif selections.get('spot'):
                instance_types = selections['spot']
        launch_template_instance_type = instance_types[0] if instance_types else global_config.get('instance_type', 't3.micro')

        instance_config = InstanceConfig(
            instance_type=launch_template_instance_type,
            ami_id=ami_id,
            region=credential.regions[0],
            userdata_script=enhanced_userdata,
            key_name=key_name
        )

        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=credential.access_key,
            aws_secret_access_key=credential.secret_key,
            region_name=credential.regions[0]
        )

        # Create the launch template
        launch_template_id = self.ec2_manager.create_launch_template(
            ec2_client, credential, instance_config
        )

        return launch_template_id

    def offer_rollback_on_failure(self):
        """Offer to rollback created resources on failure"""
        if self.created_resources and not self.dry_run:
            print(f"\n🔄 {len(self.created_resources)} resources were created in this session")
            print("Resources created:")
            for resource in self.created_resources:
                print(f"   • {resource['resource_type']}: {resource['resource_id']} ({resource['account']})")

            rollback = input("\nWould you like to rollback (delete) these resources? (y/n): ").strip().lower()

            if rollback == 'y':
                self.rollback_session_resources()

    def rollback_session_resources(self):
        """Rollback all resources created in this session"""
        print(f"\n🔄 Rolling back {len(self.created_resources)} resources...")
        self.safety_logger.log_action('INFO', f"Starting rollback of {len(self.created_resources)} resources")

        success_count = 0
        failure_count = 0

        for resource in reversed(self.created_resources):  # Delete in reverse order
            try:
                self.delete_resource_safely(resource)
                success_count += 1
                self.safety_logger.log_action('INFO',
                    f"Rolled back {resource['resource_type']} {resource['resource_id']}",
                    resource_id=resource['resource_id'],
                    account=resource['account'])
            except Exception as e:
                failure_count += 1
                self.safety_logger.log_action('ERROR',
                    f"Failed to rollback {resource['resource_type']} {resource['resource_id']}: {e}",
                    resource_id=resource['resource_id'],
                    account=resource['account'])

        print(f"\n📊 Rollback Results:")
        print(f"   ✅ Successfully deleted: {success_count}")
        print(f"   ❌ Failed to delete: {failure_count}")

    def delete_resource_safely(self, resource):
        """Safely delete a resource"""
        resource_type = resource['resource_type']
        resource_id = resource['resource_id']

        # Create client for the resource's account and region
        if resource_type == 'instance':
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=resource['access_key'],
                aws_secret_access_key=resource['secret_key'],
                region_name=resource['region']
            )

            print(f"   🗑️ Terminating instance {resource_id}...")
            ec2_client.terminate_instances(InstanceIds=[resource_id])

        elif resource_type == 'auto-scaling-group':
            asg_client = boto3.client(
                'autoscaling',
                aws_access_key_id=resource['access_key'],
                aws_secret_access_key=resource['secret_key'],
                region_name=resource['region']
            )

            print(f"   🗑️ Deleting ASG {resource_id}...")
            # First, set desired capacity to 0
            asg_client.update_auto_scaling_group(
                AutoScalingGroupName=resource_id,
                DesiredCapacity=0,
                MinSize=0
            )
            # Then delete the ASG
            asg_client.delete_auto_scaling_group(
                AutoScalingGroupName=resource_id,
                ForceDelete=True
            )

        elif resource_type == 'launch-template':
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=resource['access_key'],
                aws_secret_access_key=resource['secret_key'],
                region_name=resource['region']
            )

            print(f"   🗑️ Deleting launch template {resource_id}...")
            ec2_client.delete_launch_template(LaunchTemplateId=resource_id)

    def run_automation(self):
        """Main automation flow with safety features"""
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

            # STEP 3: SAFETY CHECKS
            print("\n🛡️ STEP 2.5: PERFORMING SAFETY CHECKS")
            self.perform_safety_checks(validated_credentials.users, global_config)

            # STEP 4: Show summary and confirmation
            self.display_automation_summary(validated_credentials, global_config)

            if not self.dry_run:
                proceed = input("\n🚀 Proceed with automation for all users? (Y/n): ").strip().lower()
                if proceed not in ['', 'y', 'yes']:
                    print("❌ Automation cancelled by user")
                    return False
            else:
                print("\n🧪 DRY-RUN: Proceeding with simulation...")

            # STEP 5: Process all users
            print(f"\n🔄 STEP 3: PROCESSING {validated_credentials.total_users} USER(S)")

            # Ask for processing mode
            if validated_credentials.total_users > 1 and not self.dry_run:
                processing_mode = input("Process users in parallel? (y/n, default: n): ").strip().lower()
                use_parallel = processing_mode == 'y'
            else:
                use_parallel = False

            # Process users
            if use_parallel:
                results = self.process_users_parallel(validated_credentials.users, global_config)
            else:
                results = self.process_users_sequential(validated_credentials.users, global_config)

            # STEP 6: Display final results
            self.display_final_results(results, global_config)

            # Save final session state
            self.save_session_state()

            return True

        except KeyboardInterrupt:
            print("\n\n⏹️ Automation interrupted by user")
            self.safety_logger.log_action('WARNING', "Automation interrupted by user")
            self.offer_rollback_on_failure()
            return False
        except Exception as e:
            print(f"\n❌ Automation failed: {e}")
            self.safety_logger.log_action('ERROR', f"Automation failed: {e}")
            self.offer_rollback_on_failure()
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
                except Exception as e:
                    cred = future_to_credential[future]
                    self.safety_logger.log_action('ERROR', f"Parallel processing failed for {cred.account_name}: {e}")
                    results.append({
                        'account': cred.account_name,
                        'username': cred.username or 'ROOT',
                        'status': 'failed',
                        'error': str(e)
                    })

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
        if self.dry_run:
            print("🧪 Mode: DRY-RUN (Simulation only)")

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

        # Calculate expected resources
        expected_resources = self.calculate_expected_resources(validated_credentials.users, global_config)
        print(f"\n📊 Expected Resources: {expected_resources}")
        print(f"📋 Session ID: {self.session_id}")

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

        if self.dry_run:
            print(f"   🧪 DRY-RUN: No actual resources were created")
        else:
            print(f"   🗂️ Created Resources: {len(self.created_resources)}")
            print(f"   📄 Session File: session_{self.session_id}.json")
            print(f"   📋 Log File: {self.safety_logger.log_file}")

        if successful:
            print(f"\n✅ FULLY SUCCESSFUL DEPLOYMENTS:")
            print("-" * 60)
            for result in successful:
                print(f"🏢 {result['account']} - {result['username']}")
                print(f"   🌍 Region: {result['region']}")

                if result.get('ec2_instance'):
                    ec2_info = result['ec2_instance']
                    if ec2_info.get('dry_run'):
                        print(f"   💻 EC2: {ec2_info['instance_id']} (DRY-RUN)")
                    else:
                        print(f"   💻 EC2: {ec2_info['instance_id']} ({ec2_info.get('instance_type', 'Unknown')})")

                if result.get('asg'):
                    asg_info = result['asg']
                    if asg_info.get('dry_run'):
                        print(f"   🚀 ASG: {asg_info['asg_name']} (DRY-RUN)")
                    else:
                        print(f"   🚀 ASG: {asg_info['asg_name']} ({asg_info.get('strategy', 'Unknown')})")
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

    def setup_unicode_support(self):
        """Setup Unicode support for Windows terminals"""
        if sys.platform.startswith('win'):
            try:
                import codecs
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            except (AttributeError, UnicodeError):
                try:
                    import locale
                    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
                except:
                    pass

def main():
    """Enhanced main with safety options"""
    parser = argparse.ArgumentParser(description='EC2 ASG Automation with Safety Features')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode (simulation only)')
    parser.add_argument('--max-resources', type=int, default=50, help='Maximum resources per session')

    args = parser.parse_args()

    if args.dry_run:
        print("🧪 Running in DRY-RUN mode - no actual resources will be created")

    automation = EC2ASGAutomation(dry_run=args.dry_run, max_resources=args.max_resources)
    automation.setup_unicode_support()

    try:
        success = automation.run_automation()
        if success:
            print("\n🎉 All operations completed successfully!")
            if not automation.dry_run:
                print(f"📋 Session logs saved to: {automation.safety_logger.log_file}")
                print(f"🗂️ Session state saved to: session_{automation.session_id}.json")
            sys.exit(0)
        else:
            print("\n❌ Automation failed or was interrupted")
            sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        automation.safety_logger.log_action('CRITICAL', f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()