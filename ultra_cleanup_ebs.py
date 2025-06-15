#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError

class UltraEBSCleanupManager:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize log file
        self.setup_detailed_logging()
        
        # Load configuration
        self.load_configuration()
        
        # Storage for cleanup results
        self.cleanup_results = {
            'accounts_processed': [],
            'regions_processed': [],
            'deleted_applications': [],
            'deleted_environments': [],
            'failed_deletions': [],
            'skipped_resources': [],
            'errors': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/elasticbeanstalk"
            os.makedirs(log_dir, exist_ok=True)
        
            # Save log file in the aws/elasticbeanstalk directory
            self.log_filename = f"{log_dir}/ultra_ebs_cleanup_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ultra_ebs_cleanup')
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
            self.operation_logger.info("🚨 ULTRA ELASTIC BEANSTALK CLEANUP SESSION STARTED 🚨")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config File: {self.config_file}")
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

    def load_configuration(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            self.log_operation('INFO', f"✅ Configuration loaded from: {self.config_file}")
            
            # Validate accounts
            if 'accounts' not in self.config_data:
                raise ValueError("No 'accounts' section found in configuration")
            
            # Filter out incomplete accounts
            valid_accounts = {}
            for account_name, account_data in self.config_data['accounts'].items():
                if (account_data.get('access_key') and 
                    account_data.get('secret_key') and
                    account_data.get('account_id') and
                    not account_data.get('access_key').startswith('ADD_')):
                    valid_accounts[account_name] = account_data
                else:
                    self.log_operation('WARNING', f"Skipping incomplete account: {account_name}")
            
            self.config_data['accounts'] = valid_accounts
            
            self.log_operation('INFO', f"📊 Valid accounts loaded: {len(valid_accounts)}")
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                self.log_operation('INFO', f"   • {account_name}: {account_id} ({email})")
            
            # Get user regions
            self.user_regions = self.config_data.get('user_settings', {}).get('user_regions', [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1'
            ])
            
            self.log_operation('INFO', f"🌍 Regions to process: {self.user_regions}")
            
        except FileNotFoundError as e:
            self.log_operation('ERROR', f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation('ERROR', f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation('ERROR', f"Error loading configuration: {e}")
            sys.exit(1)

    def create_client(self, service, access_key, secret_key, region):
        """Create AWS service client using account credentials"""
        try:
            client = boto3.client(
                service,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            if service == 'elasticbeanstalk':
                # Test the connection
                client.describe_applications()
            
            return client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create {service} client for {region}: {e}")
            raise

    def get_all_beanstalk_apps(self, ebs_client, region, account_name):
        """Get all Elastic Beanstalk applications in a specific region"""
        try:
            applications = []
            
            self.log_operation('INFO', f"🔍 Scanning for Elastic Beanstalk applications in {region} ({account_name})")
            print(f"   🔍 Scanning for Elastic Beanstalk applications in {region} ({account_name})...")
            
            # Get all applications
            response = ebs_client.describe_applications()
            apps = response.get('Applications', [])
            
            if not apps:
                self.log_operation('INFO', f"No Elastic Beanstalk applications found in {region} ({account_name})")
                print(f"   📦 No Elastic Beanstalk applications found in {region}")
                return []
            
            # Process each application
            for app in apps:
                app_name = app.get('ApplicationName')
                description = app.get('Description', 'No description')
                created_time = app.get('DateCreated', 'Unknown')
                updated_time = app.get('DateUpdated', 'Unknown')
                
                # Get all environments for this application
                environments = self.get_environments_for_app(ebs_client, app_name, region, account_name)
                
                app_info = {
                    'application_name': app_name,
                    'description': description,
                    'created_time': created_time,
                    'updated_time': updated_time,
                    'region': region,
                    'account_name': account_name,
                    'environments': environments
                }
                
                applications.append(app_info)
            
            self.log_operation('INFO', f"📦 Found {len(applications)} Elastic Beanstalk applications in {region} ({account_name})")
            print(f"   📦 Found {len(applications)} Elastic Beanstalk applications in {region} ({account_name})")
            
            # Count environments for output
            total_envs = sum(len(app['environments']) for app in applications)
            print(f"   🌐 Found {total_envs} environments across all applications")
            
            return applications
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting Elastic Beanstalk applications in {region} ({account_name}): {e}")
            print(f"   ❌ Error getting applications in {region}: {e}")
            return []

    def get_environments_for_app(self, ebs_client, app_name, region, account_name):
        """Get all environments for a specific application"""
        try:
            environments = []
            
            # Get environments for this application
            response = ebs_client.describe_environments(
                ApplicationName=app_name,
                IncludeDeleted=False
            )
            
            envs = response.get('Environments', [])
            
            for env in envs:
                env_name = env.get('EnvironmentName')
                env_id = env.get('EnvironmentId')
                status = env.get('Status')
                health = env.get('Health')
                tier = env.get('Tier', {}).get('Name', 'Unknown')
                platform = env.get('PlatformArn', 'Unknown')
                
                # Extract platform details
                platform_parts = platform.split('/')
                platform_name = platform_parts[-2] if len(platform_parts) > 1 else platform
                platform_version = platform_parts[-1] if len(platform_parts) > 1 else 'Unknown'
                
                # Get resource details
                resources = self.get_environment_resources(ebs_client, env_name, region, account_name)
                
                env_info = {
                    'environment_name': env_name,
                    'environment_id': env_id,
                    'status': status,
                    'health': health,
                    'tier': tier,
                    'platform': platform_name,
                    'version': platform_version,
                    'resources': resources
                }
                
                environments.append(env_info)
            
            return environments
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting environments for app {app_name} in {region}: {e}")
            return []

    def get_environment_resources(self, ebs_client, env_name, region, account_name):
        """Get resources for a specific environment"""
        try:
            resources = {}
            
            # Describe environment resources
            response = ebs_client.describe_environment_resources(
                EnvironmentName=env_name
            )
            
            # Extract key resources
            env_resources = response.get('EnvironmentResources', {})
            
            # Auto Scaling Groups
            resources['auto_scaling_groups'] = [
                asg.get('Name') for asg in env_resources.get('AutoScalingGroups', [])
            ]
            
            # Load Balancers
            resources['load_balancers'] = [
                lb.get('Name') for lb in env_resources.get('LoadBalancers', [])
            ]
            
            # Instances
            resources['instances'] = [
                instance.get('Id') for instance in env_resources.get('Instances', [])
            ]
            
            # Launch Configurations
            resources['launch_configurations'] = [
                lc.get('Name') for lc in env_resources.get('LaunchConfigurations', [])
            ]
            
            # Launch Templates
            resources['launch_templates'] = [
                lt.get('Id') for lt in env_resources.get('LaunchTemplates', [])
            ]
            
            return resources
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting resources for environment {env_name} in {region}: {e}")
            return {}

    def terminate_environment(self, ebs_client, env_info, app_name, region, account_name):
        """Terminate an Elastic Beanstalk environment"""
        try:
            env_name = env_info['environment_name']
            env_id = env_info['environment_id']
            
            self.log_operation('INFO', f"🗑️  Terminating environment {env_name} ({env_id}) in app {app_name} ({region}, {account_name})")
            print(f"      🗑️  Terminating environment {env_name} ({env_id})...")
            
            # Check if environment is already being terminated
            if env_info['status'] in ['Terminating', 'Terminated']:
                self.log_operation('INFO', f"Environment {env_name} is already {env_info['status']}")
                print(f"      ✓ Environment {env_name} is already {env_info['status']}")
                
                self.cleanup_results['skipped_resources'].append({
                    'resource_type': 'environment',
                    'resource_id': env_name,
                    'environment_id': env_id,
                    'application_name': app_name,
                    'region': region,
                    'account_name': account_name,
                    'reason': f"Already {env_info['status']}"
                })
                
                return True
            
            # Terminate environment
            ebs_client.terminate_environment(
                EnvironmentName=env_name,
                TerminateResources=True
            )
            
            # Wait for environment termination to complete
            print(f"      ⏳ Waiting for environment {env_name} termination to complete...")
            self.log_operation('INFO', f"⏳ Waiting for environment {env_name} termination to complete...")
            
            waiter = True
            retry_count = 0
            max_retries = 80  # 40 minutes (80 * 30 seconds)
            
            while waiter and retry_count < max_retries:
                try:
                    response = ebs_client.describe_environments(
                        EnvironmentNames=[env_name],
                        IncludeDeleted=False
                    )
                    
                    if not response['Environments']:
                        # Environment is gone
                        waiter = False
                        self.log_operation('INFO', f"✅ Environment {env_name} terminated successfully")
                        print(f"      ✅ Environment {env_name} terminated successfully")
                        break
                    
                    status = response['Environments'][0]['Status']
                    
                    if status == 'Terminated':
                        waiter = False
                        self.log_operation('INFO', f"✅ Environment {env_name} terminated successfully")
                        print(f"      ✅ Environment {env_name} terminated successfully")
                        break
                    elif status == 'Terminating':
                        if retry_count % 6 == 0:  # Log every 3 minutes
                            self.log_operation('INFO', f"Environment {env_name} status: {status} (Waiting...)")
                            print(f"      ⌛ Environment {env_name} status: {status} (Still terminating...)")
                        time.sleep(30)  # Check every 30 seconds
                        retry_count += 1
                    else:
                        self.log_operation('WARNING', f"Unexpected environment status: {status}")
                        time.sleep(30)
                        retry_count += 1
                except ClientError as e:
                    if 'No Environment found' in str(e):
                        waiter = False
                        self.log_operation('INFO', f"✅ Environment {env_name} terminated successfully")
                        print(f"      ✅ Environment {env_name} terminated successfully")
                        break
                    else:
                        self.log_operation('ERROR', f"Error checking environment status: {e}")
                        raise
                except Exception as e:
                    self.log_operation('ERROR', f"Unexpected error checking environment status: {e}")
                    raise
            
            if retry_count >= max_retries:
                self.log_operation('WARNING', f"Timed out waiting for environment {env_name} termination")
                print(f"      ⚠️ Timed out waiting for environment {env_name} termination")
            
            # Record the deletion
            self.cleanup_results['deleted_environments'].append({
                'environment_name': env_name,
                'environment_id': env_id,
                'application_name': app_name,
                'region': region,
                'account_name': account_name,
                'resources': env_info.get('resources', {}),
                'platform': env_info.get('platform', 'Unknown'),
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to terminate environment {env_info['environment_name']}: {e}")
            print(f"      ❌ Failed to terminate environment {env_info['environment_name']}: {e}")
            
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'environment',
                'resource_id': env_info['environment_name'],
                'environment_id': env_info['environment_id'],
                'application_name': app_name,
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def delete_application(self, ebs_client, app_info):
        """Delete an Elastic Beanstalk application with all its environments"""
        try:
            app_name = app_info['application_name']
            region = app_info['region']
            account_name = app_info['account_name']
            environments = app_info['environments']
            
            self.log_operation('INFO', f"🗑️  Deleting Elastic Beanstalk application {app_name} in {region} ({account_name})")
            print(f"\n   🗑️  Deleting Elastic Beanstalk application {app_name} in {region} ({account_name})...")
            
            # Step 1: Terminate all environments first
            if environments:
                env_count = len(environments)
                self.log_operation('INFO', f"Found {env_count} environments to terminate in application {app_name}")
                print(f"      Found {env_count} environments to terminate in application {app_name}")
                
                for env in environments:
                    self.terminate_environment(ebs_client, env, app_name, region, account_name)
            else:
                self.log_operation('INFO', f"No environments found in application {app_name}")
                print(f"      No environments found in application {app_name}")
            
            # Step 2: Wait a bit to ensure all resources are terminated
            print(f"   ⏳ Waiting 30 seconds to ensure all resources are released...")
            time.sleep(30)
            
            # Step 3: Delete application versions
            print(f"   🗑️  Deleting application versions for {app_name}...")
            self.log_operation('INFO', f"Deleting application versions for {app_name}")
            
            try:
                # Get application versions
                versions_response = ebs_client.describe_application_versions(
                    ApplicationName=app_name
                )
                
                versions = versions_response.get('ApplicationVersions', [])
                
                if versions:
                    self.log_operation('INFO', f"Found {len(versions)} application versions to delete")
                    print(f"      Found {len(versions)} application versions to delete")
                    
                    # Delete each version
                    for version in versions:
                        version_label = version.get('VersionLabel')
                        
                        try:
                            ebs_client.delete_application_version(
                                ApplicationName=app_name,
                                VersionLabel=version_label,
                                DeleteSourceBundle=True
                            )
                            self.log_operation('INFO', f"Deleted application version {version_label}")
                            print(f"      ✅ Deleted application version {version_label}")
                        except Exception as version_error:
                            self.log_operation('WARNING', f"Could not delete version {version_label}: {str(version_error)}")
                            print(f"      ⚠️ Could not delete version {version_label}: {str(version_error)}")
                else:
                    self.log_operation('INFO', f"No application versions found for {app_name}")
                    print(f"      No application versions found for {app_name}")
            except Exception as versions_error:
                self.log_operation('WARNING', f"Error deleting application versions: {str(versions_error)}")
                print(f"      ⚠️ Error deleting application versions: {str(versions_error)}")
            
            # Step 4: Delete the application
            self.log_operation('INFO', f"Deleting the application {app_name}...")
            print(f"   🗑️  Deleting the application {app_name}...")
            
            ebs_client.delete_application(
                ApplicationName=app_name,
                TerminateEnvByForce=True
            )
            
            self.log_operation('INFO', f"✅ Successfully deleted application {app_name}")
            print(f"   ✅ Successfully deleted application {app_name}")
            
            self.cleanup_results['deleted_applications'].append({
                'application_name': app_name,
                'description': app_info['description'],
                'created_time': app_info['created_time'],
                'updated_time': app_info['updated_time'],
                'region': region,
                'account_name': account_name,
                'environment_count': len(environments),
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete application {app_info['application_name']}: {e}")
            print(f"   ❌ Failed to delete application {app_info['application_name']}: {e}")
            
            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'application',
                'resource_id': app_info['application_name'],
                'region': region,
                'account_name': account_name,
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_name, account_data, region):
        """Clean up all Elastic Beanstalk resources in a specific account and region"""
        try:
            access_key = account_data['access_key']
            secret_key = account_data['secret_key']
            account_id = account_data['account_id']
        
            self.log_operation('INFO', f"🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
            print(f"\n🧹 Starting cleanup for {account_name} ({account_id}) in {region}")
        
            # Create Elastic Beanstalk client
            try:
                ebs_client = self.create_client('elasticbeanstalk', access_key, secret_key, region)
            except Exception as client_error:
                self.log_operation('ERROR', f"Could not create Elastic Beanstalk client for {region}: {client_error}")
                print(f"   ❌ Could not create Elastic Beanstalk client for {region}: {client_error}")
                return False
        
            # Get all Elastic Beanstalk applications
            applications = self.get_all_beanstalk_apps(ebs_client, region, account_name)
        
            if not applications:
                self.log_operation('INFO', f"No Elastic Beanstalk applications found in {account_name} ({region})")
                print(f"   ✓ No Elastic Beanstalk applications found in {account_name} ({region})")
                return True
        
            # Record region summary
            region_summary = {
                'account_name': account_name,
                'account_id': account_id,
                'region': region,
                'applications_found': len(applications),
                'environments_found': sum(len(app.get('environments', [])) for app in applications)
            }
            self.cleanup_results['regions_processed'].append(region_summary)
        
            # Add account to processed accounts if not already there
            if account_name not in [a['account_name'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({
                    'account_name': account_name,
                    'account_id': account_id
                })
            
            # Delete each application and its environments
            for app in applications:
                self.delete_application(ebs_client, app)
        
            self.log_operation('INFO', f"✅ Cleanup completed for {account_name} ({region})")
            print(f"   ✅ Cleanup completed for {account_name} ({region})")
            return True
        
        except Exception as e:
            self.log_operation('ERROR', f"Error cleaning up {account_name} ({region}): {e}")
            print(f"   ❌ Error cleaning up {account_name} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_name': account_name,
                'region': region,
                'error': str(e)
            })
            return False

    def parse_selection(self, selection: str, max_count: int) -> list:
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

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_dir = "aws/elasticbeanstalk/reports"
            os.makedirs(report_dir, exist_ok=True)
            report_filename = f"{report_dir}/ultra_ebs_cleanup_report_{self.execution_timestamp}.json"
            
            # Calculate statistics
            total_apps_deleted = len(self.cleanup_results['deleted_applications'])
            total_envs_deleted = len(self.cleanup_results['deleted_environments'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])
            
            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}
            
            for app in self.cleanup_results['deleted_applications']:
                account = app['account_name']
                region = app['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'applications': 0, 'environments': 0}
                deletions_by_account[account]['applications'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'applications': 0, 'environments': 0}
                deletions_by_region[region]['applications'] += 1
            
            for env in self.cleanup_results['deleted_environments']:
                account = env['account_name']
                region = env['region']
                
                if account not in deletions_by_account:
                    deletions_by_account[account] = {'applications': 0, 'environments': 0}
                deletions_by_account[account]['environments'] += 1
                
                if region not in deletions_by_region:
                    deletions_by_region[region] = {'applications': 0, 'environments': 0}
                deletions_by_region[region]['environments'] += 1
            
            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_EBS_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_file": self.config_file,
                    "log_file": self.log_filename,
                    "accounts_in_config": list(self.config_data['accounts'].keys()),
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(self.cleanup_results['accounts_processed']),
                    "total_regions_processed": len(self.cleanup_results['regions_processed']),
                    "total_applications_deleted": total_apps_deleted,
                    "total_environments_deleted": total_envs_deleted, 
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results['accounts_processed'],
                    "regions_processed": self.cleanup_results['regions_processed'],
                    "deleted_applications": self.cleanup_results['deleted_applications'],
                    "deleted_environments": self.cleanup_results['deleted_environments'],
                    "failed_deletions": self.cleanup_results['failed_deletions'],
                    "skipped_resources": self.cleanup_results['skipped_resources'],
                    "errors": self.cleanup_results['errors']
                }
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"✅ Ultra cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save ultra cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "🚨 STARTING ULTRA ELASTIC BEANSTALK CLEANUP SESSION 🚨")
            
            print("🚨" * 30)
            print("💥 ULTRA ELASTIC BEANSTALK CLEANUP - SEQUENTIAL 💥")
            print("🚨" * 30)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📋 Log File: {self.log_filename}")
            
            # STEP 1: Display available accounts and select accounts to process
            accounts = self.config_data['accounts']
            
            print(f"\n🏦 AVAILABLE AWS ACCOUNTS:")
            print("=" * 80)
            
            account_list = []
            
            for i, (account_name, account_data) in enumerate(accounts.items(), 1):
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'Unknown')
                
                account_list.append({
                    'name': account_name,
                    'account_id': account_id,
                    'email': email,
                    'data': account_data
                })
                
                print(f"  {i}. {account_name}: {account_id} ({email})")
            
            # Selection prompt
            print("\nAccount Selection Options:")
            print("  • Single accounts: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-2,4")
            print("  • All accounts: 'all' or press Enter")
            print("  • Cancel: 'cancel' or 'quit'")
            
            selection = input("\n🔢 Select accounts to process: ").strip().lower()
            
            if selection in ['cancel', 'quit']:
                self.log_operation('INFO', "Elastic Beanstalk cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Process account selection
            selected_accounts = {}
            if not selection or selection == 'all':
                selected_accounts = accounts
                self.log_operation('INFO', f"All accounts selected: {len(accounts)}")
                print(f"✅ Selected all {len(accounts)} accounts")
            else:
                try:
                    # Parse selection
                    parts = []
                    for part in selection.split(','):
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            if start < 1 or end > len(account_list):
                                raise ValueError(f"Range {part} out of bounds (1-{len(account_list)})")
                            parts.extend(range(start, end + 1))
                        else:
                            num = int(part)
                            if num < 1 or num > len(account_list):
                                raise ValueError(f"Selection {part} out of bounds (1-{len(account_list)})")
                            parts.append(num)
                    
                    # Get selected account data
                    for idx in parts:
                        account = account_list[idx-1]
                        selected_accounts[account['name']] = account['data']
                    
                    if not selected_accounts:
                        raise ValueError("No valid accounts selected")
                    
                    self.log_operation('INFO', f"Selected accounts: {list(selected_accounts.keys())}")
                    print(f"✅ Selected {len(selected_accounts)} accounts: {', '.join(selected_accounts.keys())}")
                    
                except ValueError as e:
                    self.log_operation('ERROR', f"Invalid account selection: {e}")
                    print(f"❌ Invalid selection: {e}")
                    return
            
            regions = self.user_regions
            
            # STEP 2: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(regions)
            
            print(f"\n🎯 CLEANUP CONFIGURATION")
            print("=" * 80)
            print(f"🏦 Selected accounts: {len(selected_accounts)}")
            print(f"🌍 Regions per account: {len(regions)}")
            print(f"📋 Total operations: {total_operations}")
            print("=" * 80)
            
            # Simplified confirmation process
            print(f"\n⚠️  WARNING: This will delete ALL Elastic Beanstalk applications and environments")
            print(f"    across {len(selected_accounts)} accounts in {len(regions)} regions ({total_operations} operations)")
            print(f"    This action CANNOT be undone!")
            
            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")
            
            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return
            
            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")
            
            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra cleanup cancelled at final confirmation")
                print("❌ Cleanup cancelled")
                return
            
            # STEP 3: Start the cleanup sequentially
            print(f"\n💥 STARTING CLEANUP...")
            self.log_operation('INFO', f"🚨 CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(regions)} regions")
            
            start_time = time.time()
            
            successful_tasks = 0
            failed_tasks = 0
            
            # Create tasks list
            tasks = []
            for account_name, account_data in selected_accounts.items():
                for region in regions:
                    tasks.append((account_name, account_data, region))
            
            # Process each task sequentially
            for i, (account_name, account_data, region) in enumerate(tasks, 1):
                print(f"\n[{i}/{len(tasks)}] Processing {account_name} in {region}...")
                
                try:
                    success = self.cleanup_account_region(account_name, account_data, region)
                    if success:
                        successful_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    self.log_operation('ERROR', f"Task failed for {account_name} ({region}): {e}")
                    print(f"❌ Task failed for {account_name} ({region}): {e}")
            
            end_time = time.time()
            total_time = int(end_time - start_time)
            
            # STEP 4: Display final results
            print(f"\n💥" + "="*25 + " CLEANUP COMPLETE " + "="*25)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"✅ Successful operations: {successful_tasks}")
            print(f"❌ Failed operations: {failed_tasks}")
            print(f"🌐 Applications deleted: {len(self.cleanup_results['deleted_applications'])}")
            print(f"🌱 Environments deleted: {len(self.cleanup_results['deleted_environments'])}")
            print(f"⏭️  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            print(f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            self.log_operation('INFO', f"CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Applications deleted: {len(self.cleanup_results['deleted_applications'])}")
            self.log_operation('INFO', f"Environments deleted: {len(self.cleanup_results['deleted_environments'])}")
            
            # STEP 5: Show account summary
            if self.cleanup_results['deleted_applications'] or self.cleanup_results['deleted_environments']:
                print(f"\n📊 Deletion Summary by Account:")
                
                # Group by account
                account_summary = {}
                for app in self.cleanup_results['deleted_applications']:
                    account = app['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'applications': 0, 'environments': 0, 'regions': set()}
                    account_summary[account]['applications'] += 1
                    account_summary[account]['regions'].add(app['region'])
                
                for env in self.cleanup_results['deleted_environments']:
                    account = env['account_name']
                    if account not in account_summary:
                        account_summary[account] = {'applications': 0, 'environments': 0, 'regions': set()}
                    account_summary[account]['environments'] += 1
                    account_summary[account]['regions'].add(env['region'])
                
                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    print(f"   🏦 {account}:")
                    print(f"      🌐 Applications: {summary['applications']}")
                    print(f"      🌱 Environments: {summary['environments']}")
                    print(f"      🌍 Regions: {regions_list}")
            
            # STEP 6: Show failures if any
            if self.cleanup_results['failed_deletions']:
                print(f"\n❌ Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    print(f"   • {failure['resource_type']} {failure['resource_id']} in {failure['account_name']} ({failure['region']})")
                    print(f"     Error: {failure['error']}")
                
                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    print(f"   ... and {remaining} more failures (see detailed report)")
            
            # Save comprehensive report
            print(f"\n📄 Saving cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                print(f"✅ Cleanup report saved to: {report_file}")
            
            print(f"✅ Session log saved to: {self.log_filename}")
            
            print(f"\n💥 CLEANUP COMPLETE! 💥")
            print("🚨" * 30)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            print(f"\n❌ FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise

def main():
    """Main function"""
    try:
        manager = UltraEBSCleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
            