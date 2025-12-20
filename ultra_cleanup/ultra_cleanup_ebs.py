#!/usr/bin/env python3

import os
import json
import boto3
import time
from datetime import datetime
from typing import List, Optional
from botocore.exceptions import ClientError
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupEBSManager:
    """
    Tool to perform comprehensive cleanup of Elastic Beanstalk resources across AWS accounts.

    Manages deletion of:
    - Elastic Beanstalk Applications
    - Elastic Beanstalk Environments
    - Application Versions
    - Associated AWS resources (EC2, ALB, ASG, etc.)

    Author: varadharajaan
    Created: 2025-07-05
    """

    def __init__(self, config_dir: str = None):
        """Initialize the EBS Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.ebs_dir = os.path.join(self.config_dir, "aws", "elasticbeanstalk")
        self.reports_dir = os.path.join(self.ebs_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Get user regions from config
        self.user_regions = self._get_user_regions()

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
            self.print_colored(Colors.YELLOW, f"[WARN]  Warning: Could not load user regions: {e}")

        return ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'ap-south-1']

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.ebs_dir, exist_ok=True)

            # Save log file in the aws/elasticbeanstalk directory
            self.log_filename = f"{self.ebs_dir}/ultra_ebs_cleanup_log_{self.execution_timestamp}.log"

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
            self.operation_logger.info("[ALERT] ULTRA ELASTIC BEANSTALK CLEANUP SESSION STARTED [ALERT]")
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

    def get_all_beanstalk_apps(self, ebs_client, region, account_info):
        """Get all Elastic Beanstalk applications in a specific region"""
        try:
            applications = []
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"[SCAN] Scanning for Elastic Beanstalk applications in {region} ({account_name})")
            print(f"   [SCAN] Scanning for Elastic Beanstalk applications in {region} ({account_name})...")

            # Get all applications
            response = ebs_client.describe_applications()
            apps = response.get('Applications', [])

            if not apps:
                self.log_operation('INFO', f"No Elastic Beanstalk applications found in {region} ({account_name})")
                print(f"   [PACKAGE] No Elastic Beanstalk applications found in {region}")
                return []

            # Process each application
            for app in apps:
                app_name = app.get('ApplicationName')
                description = app.get('Description', 'No description')
                created_time = app.get('DateCreated', 'Unknown')
                updated_time = app.get('DateUpdated', 'Unknown')

                # Get all environments for this application
                environments = self.get_environments_for_app(ebs_client, app_name, region, account_info)

                app_info = {
                    'application_name': app_name,
                    'description': description,
                    'created_time': created_time,
                    'updated_time': updated_time,
                    'region': region,
                    'account_info': account_info,
                    'environments': environments
                }

                applications.append(app_info)

            self.log_operation('INFO', f"[PACKAGE] Found {len(applications)} Elastic Beanstalk applications in {region} ({account_name})")
            print(f"   [PACKAGE] Found {len(applications)} Elastic Beanstalk applications in {region} ({account_name})")

            # Count environments for output
            total_envs = sum(len(app['environments']) for app in applications)
            print(f"   [NETWORK] Found {total_envs} environments across all applications")

            return applications

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error getting Elastic Beanstalk applications in {region} ({account_name}): {e}")
            print(f"   [ERROR] Error getting applications in {region}: {e}")
            return []

    def get_environments_for_app(self, ebs_client, app_name, region, account_info):
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
                resources = self.get_environment_resources(ebs_client, env_name, region, account_info)

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

    def get_environment_resources(self, ebs_client, env_name, region, account_info):
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

    def terminate_environment(self, ebs_client, env_info, app_name, region, account_info):
        """Terminate an Elastic Beanstalk environment"""
        try:
            env_name = env_info['environment_name']
            env_id = env_info['environment_id']
            account_name = account_info.get('account_key', 'Unknown')

            self.log_operation('INFO', f"[DELETE]  Terminating environment {env_name} ({env_id}) in app {app_name} ({region}, {account_name})")
            print(f"      [DELETE]  Terminating environment {env_name} ({env_id})...")

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
                    'account_info': account_info,
                    'reason': f"Already {env_info['status']}"
                })

                return True

            # Terminate environment
            ebs_client.terminate_environment(
                EnvironmentName=env_name,
                TerminateResources=True
            )

            # Wait for environment termination to complete
            print(f"      [WAIT] Waiting for environment {env_name} termination to complete...")
            self.log_operation('INFO', f"[WAIT] Waiting for environment {env_name} termination to complete...")

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
                        self.log_operation('INFO', f"[OK] Environment {env_name} terminated successfully")
                        print(f"      [OK] Environment {env_name} terminated successfully")
                        break

                    status = response['Environments'][0]['Status']

                    if status == 'Terminated':
                        waiter = False
                        self.log_operation('INFO', f"[OK] Environment {env_name} terminated successfully")
                        print(f"      [OK] Environment {env_name} terminated successfully")
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
                        self.log_operation('INFO', f"[OK] Environment {env_name} terminated successfully")
                        print(f"      [OK] Environment {env_name} terminated successfully")
                        break
                    else:
                        self.log_operation('ERROR', f"Error checking environment status: {e}")
                        raise
                except Exception as e:
                    self.log_operation('ERROR', f"Unexpected error checking environment status: {e}")
                    raise

            if retry_count >= max_retries:
                self.log_operation('WARNING', f"Timed out waiting for environment {env_name} termination")
                print(f"      [WARN] Timed out waiting for environment {env_name} termination")

            # Record the deletion
            self.cleanup_results['deleted_environments'].append({
                'environment_name': env_name,
                'environment_id': env_id,
                'application_name': app_name,
                'region': region,
                'account_info': account_info,
                'resources': env_info.get('resources', {}),
                'platform': env_info.get('platform', 'Unknown'),
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            account_name = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to terminate environment {env_info['environment_name']}: {e}")
            print(f"      [ERROR] Failed to terminate environment {env_info['environment_name']}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'environment',
                'resource_id': env_info['environment_name'],
                'environment_id': env_info['environment_id'],
                'application_name': app_name,
                'region': region,
                'account_info': account_info,
                'error': str(e)
            })
            return False

    def delete_application(self, ebs_client, app_info):
        """Delete an Elastic Beanstalk application with all its environments"""
        try:
            app_name = app_info['application_name']
            region = app_info['region']
            account_name = app_info['account_info'].get('account_key', 'Unknown')
            environments = app_info['environments']

            self.log_operation('INFO', f"[DELETE]  Deleting Elastic Beanstalk application {app_name} in {region} ({account_name})")
            print(f"\n   [DELETE]  Deleting Elastic Beanstalk application {app_name} in {region} ({account_name})...")

            # Step 1: Terminate all environments first
            if environments:
                env_count = len(environments)
                self.log_operation('INFO', f"Found {env_count} environments to terminate in application {app_name}")
                print(f"      Found {env_count} environments to terminate in application {app_name}")

                for env in environments:
                    self.terminate_environment(ebs_client, env, app_name, region, app_info['account_info'])
            else:
                self.log_operation('INFO', f"No environments found in application {app_name}")
                print(f"      No environments found in application {app_name}")

            # Step 2: Wait a bit to ensure all resources are terminated
            print(f"   [WAIT] Waiting 30 seconds to ensure all resources are released...")
            time.sleep(30)

            # Step 3: Delete application versions
            print(f"   [DELETE]  Deleting application versions for {app_name}...")
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
                            print(f"      [OK] Deleted application version {version_label}")
                        except Exception as version_error:
                            self.log_operation('WARNING', f"Could not delete version {version_label}: {str(version_error)}")
                            print(f"      [WARN] Could not delete version {version_label}: {str(version_error)}")
                else:
                    self.log_operation('INFO', f"No application versions found for {app_name}")
                    print(f"      No application versions found for {app_name}")
            except Exception as versions_error:
                self.log_operation('WARNING', f"Error deleting application versions: {str(versions_error)}")
                print(f"      [WARN] Error deleting application versions: {str(versions_error)}")

            # Step 4: Delete the application
            self.log_operation('INFO', f"Deleting the application {app_name}...")
            print(f"   [DELETE]  Deleting the application {app_name}...")

            ebs_client.delete_application(
                ApplicationName=app_name,
                TerminateEnvByForce=True
            )

            self.log_operation('INFO', f"[OK] Successfully deleted application {app_name}")
            print(f"   [OK] Successfully deleted application {app_name}")

            self.cleanup_results['deleted_applications'].append({
                'application_name': app_name,
                'description': app_info['description'],
                'created_time': app_info['created_time'],
                'updated_time': app_info['updated_time'],
                'region': region,
                'account_info': app_info['account_info'],
                'environment_count': len(environments),
                'deleted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            return True

        except Exception as e:
            account_name = app_info['account_info'].get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Failed to delete application {app_info['application_name']}: {e}")
            print(f"   [ERROR] Failed to delete application {app_info['application_name']}: {e}")

            self.cleanup_results['failed_deletions'].append({
                'resource_type': 'application',
                'resource_id': app_info['application_name'],
                'region': region,
                'account_info': app_info['account_info'],
                'error': str(e)
            })
            return False

    def cleanup_account_region(self, account_info, region):
        """Clean up all Elastic Beanstalk resources in a specific account and region"""
        try:
            access_key = account_info['access_key']
            secret_key = account_info['secret_key']
            account_id = account_info['account_id']
            account_key = account_info['account_key']

            self.log_operation('INFO', f"[CLEANUP] Starting EBS cleanup for {account_key} ({account_id}) in {region}")
            print(f"\n[CLEANUP] Starting EBS cleanup for {account_key} ({account_id}) in {region}")

            # Create Elastic Beanstalk client
            try:
                ebs_client = self.create_client('elasticbeanstalk', access_key, secret_key, region)
            except Exception as client_error:
                self.log_operation('ERROR', f"Could not create Elastic Beanstalk client for {region}: {client_error}")
                print(f"   [ERROR] Could not create Elastic Beanstalk client for {region}: {client_error}")
                return False

            # Get all Elastic Beanstalk applications
            applications = self.get_all_beanstalk_apps(ebs_client, region, account_info)

            if not applications:
                self.log_operation('INFO', f"No Elastic Beanstalk applications found in {account_key} ({region})")
                print(f"   ✓ No Elastic Beanstalk applications found in {account_key} ({region})")
                return True

            # Record region summary
            region_summary = {
                'account_key': account_key,
                'account_id': account_id,
                'region': region,
                'applications_found': len(applications),
                'environments_found': sum(len(app.get('environments', [])) for app in applications)
            }
            self.cleanup_results['regions_processed'].append(region_summary)

            self.log_operation('INFO', f"[STATS] {account_key} ({region}) EBS resources summary:")
            self.log_operation('INFO', f"   [NETWORK] Applications: {len(applications)}")
            self.log_operation('INFO', f"   🌱 Environments: {region_summary['environments_found']}")

            print(f"   [STATS] EBS resources found: {len(applications)} applications, {region_summary['environments_found']} environments")

            # Delete each application and its environments
            deleted_count = 0
            failed_count = 0

            for i, app in enumerate(applications, 1):
                app_name = app['application_name']
                print(f"   [{i}/{len(applications)}] Processing application {app_name}...")

                try:
                    if self.delete_application(ebs_client, app):
                        deleted_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    self.log_operation('ERROR', f"Error deleting application {app_name}: {e}")
                    print(f"   [ERROR] Error deleting application {app_name}: {e}")

            print(f"   [OK] Deleted {deleted_count} applications, [ERROR] Failed: {failed_count}")

            self.log_operation('INFO', f"[OK] EBS cleanup completed for {account_key} ({region})")
            print(f"\n   [OK] EBS cleanup completed for {account_key} ({region})")
            return True

        except Exception as e:
            account_key = account_info.get('account_key', 'Unknown')
            self.log_operation('ERROR', f"Error cleaning up EBS resources in {account_key} ({region}): {e}")
            print(f"   [ERROR] Error cleaning up EBS resources in {account_key} ({region}): {e}")
            self.cleanup_results['errors'].append({
                'account_info': account_info,
                'region': region,
                'error': str(e)
            })
            return False

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n[REGION] Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "[TIP] Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(f"Select regions (1-{len(self.user_regions)}, comma-separated, range, or 'all') or 'q' to quit: ").strip()

                if choice.lower() == 'q':
                    return None

                if choice.lower() == "all" or not choice:
                    self.print_colored(Colors.GREEN, f"[OK] Selected all {len(self.user_regions)} regions")
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(choice, len(self.user_regions))
                if not selected_indices:
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(Colors.GREEN, f"[OK] Selected {len(selected_regions)} regions: {', '.join(selected_regions)}")
                return selected_regions

            except Exception as e:
                self.print_colored(Colors.RED, f"[ERROR] Error processing selection: {str(e)}")

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_ebs_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_apps_deleted = len(self.cleanup_results['deleted_applications'])
            total_envs_deleted = len(self.cleanup_results['deleted_environments'])
            total_failed = len(self.cleanup_results['failed_deletions'])
            total_skipped = len(self.cleanup_results['skipped_resources'])

            # Group deletions by account and region
            deletions_by_account = {}
            deletions_by_region = {}

            for app in self.cleanup_results['deleted_applications']:
                account = app['account_info'].get('account_key', 'Unknown')
                region = app['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {'applications': 0, 'environments': 0, 'regions': set()}
                deletions_by_account[account]['applications'] += 1
                deletions_by_account[account]['regions'].add(region)

                if region not in deletions_by_region:
                    deletions_by_region[region] = {'applications': 0, 'environments': 0}
                deletions_by_region[region]['applications'] += 1

            for env in self.cleanup_results['deleted_environments']:
                account = env['account_info'].get('account_key', 'Unknown')
                region = env['region']

                if account not in deletions_by_account:
                    deletions_by_account[account] = {'applications': 0, 'environments': 0, 'regions': set()}
                deletions_by_account[account]['environments'] += 1
                deletions_by_account[account]['regions'].add(region)

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
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                    "regions_processed": self.user_regions
                },
                "summary": {
                    "total_accounts_processed": len(
                        set(rp['account_key'] for rp in self.cleanup_results['regions_processed'])),
                    "total_regions_processed": len(
                        set(rp['region'] for rp in self.cleanup_results['regions_processed'])),
                    "total_applications_deleted": total_apps_deleted,
                    "total_environments_deleted": total_envs_deleted,
                    "total_failed_deletions": total_failed,
                    "total_skipped_resources": total_skipped,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region
                },
                "detailed_results": {
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

            self.log_operation('INFO', f"[OK] Ultra EBS cleanup report saved to: {report_filename}")
            return report_filename

        except Exception as e:
            self.log_operation('ERROR', f"[ERROR] Failed to save ultra EBS cleanup report: {e}")
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation('INFO', "[ALERT] STARTING ULTRA ELASTIC BEANSTALK CLEANUP SESSION [ALERT]")

            self.print_colored(Colors.YELLOW, "[ALERT]" * 30)
            self.print_colored(Colors.BLUE, "[START] ULTRA ELASTIC BEANSTALK CLEANUP MANAGER")
            self.print_colored(Colors.YELLOW, "[ALERT]" * 30)
            self.print_colored(Colors.WHITE, f"[DATE] Execution Date/Time: {self.current_time} UTC")
            self.print_colored(Colors.WHITE, f"[USER] Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"[LIST] Log File: {self.log_filename}")

            # STEP 1: Select root accounts
            self.print_colored(Colors.YELLOW, "\n[KEY] Select Root AWS Accounts for Elastic Beanstalk Cleanup:")

            root_accounts = self.cred_manager.select_root_accounts_interactive(allow_multiple=True)
            if not root_accounts:
                self.print_colored(Colors.RED, "[ERROR] No root accounts selected, exiting...")
                return
            selected_accounts = root_accounts

            # STEP 2: Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.RED, "[ERROR] No regions selected, exiting...")
                return

            # STEP 3: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(selected_regions)

            self.print_colored(Colors.YELLOW, f"\n[TARGET] ELASTIC BEANSTALK CLEANUP CONFIGURATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"[KEY] Credential source: ROOT ACCOUNTS")
            self.print_colored(Colors.WHITE, f"[BANK] Selected accounts: {len(selected_accounts)}")
            self.print_colored(Colors.WHITE, f"[REGION] Regions per account: {len(selected_regions)}")
            self.print_colored(Colors.WHITE, f"[LIST] Total operations: {total_operations}")
            self.print_colored(Colors.YELLOW, "=" * 80)

            # Show what will be cleaned up
            self.print_colored(Colors.RED, f"\n[WARN]  WARNING: This will delete ALL of the following Elastic Beanstalk resources:")
            self.print_colored(Colors.WHITE, f"    • Elastic Beanstalk Applications")
            self.print_colored(Colors.WHITE, f"    • Elastic Beanstalk Environments")
            self.print_colored(Colors.WHITE, f"    • Application Versions")
            self.print_colored(Colors.WHITE, f"    • Associated AWS resources (EC2, ALB, ASG, etc.)")
            self.print_colored(Colors.WHITE, f"    across {len(selected_accounts)} accounts in {len(selected_regions)} regions ({total_operations} operations)")
            self.print_colored(Colors.RED, f"    This action CANNOT be undone!")

            # First confirmation - simple y/n
            confirm1 = input(f"\nContinue with Elastic Beanstalk cleanup? (y/n): ").strip().lower()
            self.log_operation('INFO', f"First confirmation: '{confirm1}'")

            if confirm1 not in ['y', 'yes']:
                self.log_operation('INFO', "Ultra EBS cleanup cancelled by user")
                self.print_colored(Colors.RED, "[ERROR] Cleanup cancelled")
                return

            # Second confirmation - final check
            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation('INFO', f"Final confirmation: '{confirm2}'")

            if confirm2 != 'yes':
                self.log_operation('INFO', "Ultra EBS cleanup cancelled at final confirmation")
                self.print_colored(Colors.RED, "[ERROR] Cleanup cancelled")
                return

            # STEP 4: Start the cleanup sequentially
            self.print_colored(Colors.CYAN, f"\n[START] Starting Elastic Beanstalk cleanup...")
            self.log_operation('INFO', f"[ALERT] EBS CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(selected_regions)} regions")

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
                    self.print_colored(Colors.RED, f"[ERROR] Task failed for {account_key} ({region}): {e}")

            end_time = time.time()
            total_time = int(end_time - start_time)

            # STEP 5: Display final results
            self.print_colored(Colors.GREEN, f"\n" + "=" * 100)
            self.print_colored(Colors.GREEN, "[OK] ELASTIC BEANSTALK CLEANUP COMPLETE")
            self.print_colored(Colors.GREEN, "=" * 100)
            self.print_colored(Colors.WHITE, f"[TIMER]  Total execution time: {total_time} seconds")
            self.print_colored(Colors.GREEN, f"[OK] Successful operations: {successful_tasks}")
            self.print_colored(Colors.RED, f"[ERROR] Failed operations: {failed_tasks}")
            self.print_colored(Colors.WHITE, f"[NETWORK] Applications deleted: {len(self.cleanup_results['deleted_applications'])}")
            self.print_colored(Colors.WHITE, f"🌱 Environments deleted: {len(self.cleanup_results['deleted_environments'])}")
            self.print_colored(Colors.WHITE, f"[SKIP]  Resources skipped: {len(self.cleanup_results['skipped_resources'])}")
            self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(self.cleanup_results['failed_deletions'])}")

            self.log_operation('INFO', f"EBS CLEANUP COMPLETED")
            self.log_operation('INFO', f"Execution time: {total_time} seconds")
            self.log_operation('INFO', f"Applications deleted: {len(self.cleanup_results['deleted_applications'])}")
            self.log_operation('INFO', f"Environments deleted: {len(self.cleanup_results['deleted_environments'])}")

            # STEP 6: Show account summary
            if self.cleanup_results['deleted_applications'] or self.cleanup_results['deleted_environments']:
                self.print_colored(Colors.YELLOW, f"\n[STATS] Deletion Summary by Account:")

                # Group by account
                account_summary = {}
                for app in self.cleanup_results['deleted_applications']:
                    account = app['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'applications': 0, 'environments': 0, 'regions': set()}
                    account_summary[account]['applications'] += 1
                    account_summary[account]['regions'].add(app['region'])

                for env in self.cleanup_results['deleted_environments']:
                    account = env['account_info'].get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {'applications': 0, 'environments': 0, 'regions': set()}
                    account_summary[account]['environments'] += 1
                    account_summary[account]['regions'].add(env['region'])

                for account, summary in account_summary.items():
                    regions_list = ', '.join(sorted(summary['regions']))
                    self.print_colored(Colors.PURPLE, f"   [BANK] {account}:")
                    self.print_colored(Colors.WHITE, f"      [NETWORK] Applications: {summary['applications']}")
                    self.print_colored(Colors.WHITE, f"      🌱 Environments: {summary['environments']}")
                    self.print_colored(Colors.WHITE, f"      [REGION] Regions: {regions_list}")

            # STEP 7: Show failures if any
            if self.cleanup_results['failed_deletions']:
                self.print_colored(Colors.RED, f"\n[ERROR] Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions'][:10]:  # Show first 10
                    account_key = failure['account_info'].get('account_key', 'Unknown')
                    self.print_colored(Colors.WHITE, f"   • {failure['resource_type']} {failure['resource_id']} in {account_key} ({failure['region']})")
                    self.print_colored(Colors.WHITE, f"     Error: {failure['error']}")

                if len(self.cleanup_results['failed_deletions']) > 10:
                    remaining = len(self.cleanup_results['failed_deletions']) - 10
                    self.print_colored(Colors.WHITE, f"   ... and {remaining} more failures (see detailed report)")

            # Save comprehensive report
            self.print_colored(Colors.CYAN, f"\n[FILE] Saving Elastic Beanstalk cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(Colors.GREEN, f"[OK] Elastic Beanstalk cleanup report saved to: {report_file}")

            self.print_colored(Colors.GREEN, f"[OK] Session log saved to: {self.log_filename}")

            self.print_colored(Colors.GREEN, f"\n[OK] Elastic Beanstalk cleanup completed successfully!")
            self.print_colored(Colors.YELLOW, "[ALERT]" * 30)

        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in EBS cleanup execution: {str(e)}")
            self.print_colored(Colors.RED, f"\n[ERROR] FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraCleanupEBSManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Elastic Beanstalk cleanup interrupted by user")
        exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()