#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError
from logger import setup_logger
from excel_helper import ExcelCredentialsExporter

class IAMUserManager:
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.logger = setup_logger("iam_user_manager", "user_creation")
        self.load_configuration()
        self.load_user_mapping()
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
    def load_configuration(self):
        """Load AWS account configurations from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.aws_accounts = config['accounts']
            self.user_settings = config['user_settings']
            
            self.logger.info(f"Configuration loaded from: {self.config_file}")
            self.logger.info(f"Found {len(self.aws_accounts)} AWS accounts")
            
        except FileNotFoundError as e:
            self.logger.error(f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)

    def load_user_mapping(self):
        """Load user mapping from JSON file"""
        try:
            if not os.path.exists(self.mapping_file):
                self.logger.warning(f"User mapping file '{self.mapping_file}' not found")
                self.user_mappings = {}
                return
            
            with open(self.mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            self.user_mappings = mapping_data['user_mappings']
            self.logger.info(f"User mapping loaded from: {self.mapping_file}")
            self.logger.info(f"Found mappings for {len(self.user_mappings)} users")
            
            # Log account coverage
            self.analyze_account_coverage()
            
        except Exception as e:
            self.logger.warning(f"Error loading user mapping: {e}")
            self.user_mappings = {}

    def analyze_account_coverage(self):
        """Analyze which accounts have user mappings and which don't"""
        accounts_with_mappings = set()
        accounts_without_mappings = set(self.aws_accounts.keys())
        
        for username in self.user_mappings.keys():
            # Extract account name from username (e.g., account01_clouduser01 -> account01)
            account_name = '_'.join(username.split('_')[:-1])
            if account_name in self.aws_accounts:
                accounts_with_mappings.add(account_name)
                accounts_without_mappings.discard(account_name)
        
        self.accounts_with_mappings = accounts_with_mappings
        self.accounts_without_mappings = accounts_without_mappings
        
        self.logger.info(f"Accounts with user mappings: {sorted(accounts_with_mappings)}")
        if accounts_without_mappings:
            self.logger.warning(f"Accounts without user mappings: {sorted(accounts_without_mappings)}")

    def get_user_info(self, username):
        """Get real user information for a username"""
        if username in self.user_mappings:
            mapping = self.user_mappings[username]
            return {
                'first_name': mapping['first_name'],
                'last_name': mapping['last_name'],
                'email': mapping['email'],
                'full_name': f"{mapping['first_name']} {mapping['last_name']}"
            }
        else:
            self.logger.error(f"No mapping found for user: {username}")
            return None

    def create_iam_client(self, account_name):
        """Create IAM client using specific account credentials"""
        if account_name not in self.aws_accounts:
            raise ValueError(f"Account {account_name} not found in configurations")
        
        account_config = self.aws_accounts[account_name]
        
        try:
            iam_client = boto3.client(
                'iam',
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name='us-east-1'
            )
            
            # Test the connection
            iam_client.get_user()
            self.logger.log_account_action(account_name, "CONNECT", "SUCCESS", f"Account ID: {account_config['account_id']}")
            return iam_client, account_config
            
        except ClientError as e:
            error_msg = f"Access denied: {e}"
            self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            raise
        except Exception as e:
            error_msg = f"Connection failed: {e}"
            self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            raise

    def check_user_exists(self, iam_client, username):
        """Check if IAM user already exists"""
        try:
            iam_client.get_user(UserName=username)
            self.logger.log_user_action(username, "CHECK_EXISTS", "EXISTS")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                self.logger.log_user_action(username, "CHECK_EXISTS", "NOT_EXISTS")
                return False
            else:
                self.logger.error(f"Error checking user existence: {e}")
                raise e

    def get_users_for_account(self, account_name):
        """Get user-region mapping for specific account based on actual user mappings"""
        users_regions = {}
        regions = self.user_settings['user_regions']
        region_index = 0
        
        # Find all users mapped to this account
        for username, user_info in self.user_mappings.items():
            # Extract account name from username (e.g., account01_clouduser01 -> account01)
            user_account = '_'.join(username.split('_')[:-1])
            
            if user_account == account_name:
                # Assign region in round-robin fashion
                region = regions[region_index % len(regions)]
                users_regions[username] = region
                region_index += 1
                
        return users_regions

    def create_or_get_group(self, iam_client, account_name):
        """Create or get an IAM group for the account and attach required policies"""
        group_name = f"{account_name}-group"
    
        try:
            # Check if group exists
            try:
                iam_client.get_group(GroupName=group_name)
                self.logger.info(f"Group {group_name} already exists")
                group_exists = True
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    self.logger.info(f"Group {group_name} does not exist, creating...")
                    iam_client.create_group(GroupName=group_name)
                    self.logger.log_account_action(account_name, "CREATE_GROUP", "SUCCESS", f"Created group {group_name}")
                    group_exists = False
                else:
                    self.logger.error(f"Error checking group {group_name}: {e}")
                    raise e
        
            # Check and attach AdministratorAccess policy if needed
            admin_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
            if not self.check_group_has_policy(iam_client, group_name, admin_policy_arn):
                iam_client.attach_group_policy(
                    GroupName=group_name,
                    PolicyArn=admin_policy_arn
                )
                self.logger.log_account_action(account_name, "ATTACH_POLICY", "SUCCESS", 
                                              f"Attached AdministratorAccess policy to group {group_name}")
        
            return group_name
        
        except Exception as e:
            self.logger.error(f"Failed to create or get group for {account_name}: {e}")
            raise
        
    def check_group_has_policy(self, iam_client, group_name, policy_arn):
        """Check if a group has a specific policy attached"""
        try:
            paginator = iam_client.get_paginator('list_attached_group_policies')
        
            for page in paginator.paginate(GroupName=group_name):
                for policy in page['AttachedPolicies']:
                    if policy['PolicyArn'] == policy_arn:
                        self.logger.debug(f"Group {group_name} already has policy {policy_arn}")
                        return True
        
            self.logger.debug(f"Group {group_name} does not have policy {policy_arn}")
            return False
        
        except Exception as e:
            self.logger.error(f"Error checking policies for group {group_name}: {e}")
            raise

    def create_restriction_policy_for_user(self, region):
        """Create a policy that restricts access to a specific region for a user,
        always including us-east-1 as allowed."""

        # Always include 'us-east-1' as allowed
        allowed_regions = set()

        if isinstance(region, str):
            allowed_regions.add(region)
        elif isinstance(region, list):
            allowed_regions.update(region)

        # allowed_regions.add("us-east-1")  # Ensure us-east-1 is always allowed

        # Convert to sorted list for consistency
        allowed_regions = sorted(allowed_regions)

        policy = {
            "Version": "2012-10-17",
            "Statement": []
        }

        # Deny if requested region is not one of the allowed
        policy["Statement"].append({
            "Sid": "DenyIfNotInRegion",
            "Effect": "Deny",
            "Action": [
                "ec2:*",
                "eks:*",
                "lambda:*",
                "rds:*",
                "dynamodb:*",
                "sagemaker:*",
                "elasticloadbalancing:*",
                "autoscaling:*",
                "events:*",
                "sns:*",
                "sqs:*",
                "athena:*",
                "glue:*",
                "redshift:*",
                "elasticmapreduce:*",
                "elasticbeanstalk:*",
                "apprunner:*",
                "cloudwatch:PutMetricAlarm",
                "budgets:*",
                "ce:*"
            ],
            "Resource": "*",
            "Condition": {
                "StringNotEquals": {
                    "aws:RequestedRegion": allowed_regions
                }
            }
        })

        # Allow launch template creation and usage
        policy["Statement"].append({
            "Sid": "AllowLaunchTemplateOperations",
            "Effect": "Allow",
            "Action": [
                "ec2:CreateLaunchTemplate",
                "ec2:CreateLaunchTemplateVersion",
                "ec2:DescribeLaunchTemplates",
                "ec2:DescribeLaunchTemplateVersions",
                "ec2:GetLaunchTemplateData"
            ],
            "Resource": "*"
        })

        # Allow IAM PassRole for Auto Scaling and EC2
        policy["Statement"].append({
            "Sid": "AllowPassRoleForAutoScaling",
            "Effect": "Allow",
            "Action": [
                "iam:PassRole"
            ],
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "iam:PassedToService": [
                        "ec2.amazonaws.com",
                        "autoscaling.amazonaws.com"
                    ]
                }
            }
        })

        # Allow essential IAM read operations (needed for role validation)
        policy["Statement"].append({
            "Sid": "AllowIAMReadOperations",
            "Effect": "Allow",
            "Action": [
                "iam:GetRole",
                "iam:ListInstanceProfiles",
                "iam:GetInstanceProfile"
            ],
            "Resource": "*"
        })

        # Allow essential EC2 describe operations (needed for Auto Scaling)
        policy["Statement"].append({
            "Sid": "AllowEC2DescribeOperations",
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeImages",
                "ec2:DescribeKeyPairs",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeSubnets",
                "ec2:DescribeVpcs",
                "ec2:DescribeAvailabilityZones",
                "ec2:DescribeInstanceTypes",
                "ec2:DescribeInstanceAttribute",
                "ec2:DescribeInstances"
            ],
            "Resource": "*"
        })

        # Deny disallowed instance types
        policy["Statement"].append({
            "Sid": "DenyIfDisallowedInstanceType",
            "Effect": "Deny",
            "Action": [
                "ec2:RunInstances"
            ],
            "Resource": "arn:aws:ec2:*:*:instance/*",
            "Condition": {
                "StringNotEquals": {
                    "ec2:InstanceType": self.user_settings['allowed_instance_types']
                }
            }
        })

        return policy

    def create_single_user(self, iam_client, username, region, account_config, group_name):
        """Create a single IAM user and add to group, with user-specific region restriction"""
        try:
            # 1. Create IAM User
            self.logger.debug(f"Creating IAM user: {username}")
            iam_client.create_user(UserName=username)
            self.logger.log_user_action(username, "CREATE_USER", "SUCCESS")
        
            # 2. Enable Console Access
            self.logger.debug(f"Setting up console access for: {username}")
            iam_client.create_login_profile(
                UserName=username,
                Password=self.user_settings['password'],
                PasswordResetRequired=False
            )
            self.logger.log_user_action(username, "CREATE_LOGIN_PROFILE", "SUCCESS")
        
            # 3. Add user to the group
            self.logger.debug(f"Adding user {username} to group {group_name}")
            iam_client.add_user_to_group(
                UserName=username,
                GroupName=group_name
            )
            self.logger.log_user_action(username, "ADD_TO_GROUP", "SUCCESS", f"Added to group {group_name}")
        
            # 4. Create user-specific Restriction Policy to limit access to mapped region
            # This ensures each user is restricted to their specific region
            self.logger.debug(f"Creating region restriction policy for: {username}")
            restriction_policy = self.create_restriction_policy_for_user(region)
        
            iam_client.put_user_policy(
                UserName=username,
                PolicyName="Restrict-Region-And-EC2-Managed-Types",
                PolicyDocument=json.dumps(restriction_policy)
            )
            self.logger.log_user_action(username, "CREATE_RESTRICTION_POLICY", "SUCCESS", f"Region: {region}")
        
            # 5. Create Access Key
            self.logger.debug(f"Creating access keys for: {username}")
            response = iam_client.create_access_key(UserName=username)
            access_key = response['AccessKey']['AccessKeyId']
            secret_key = response['AccessKey']['SecretAccessKey']
            self.logger.log_user_action(username, "CREATE_ACCESS_KEY", "SUCCESS", f"Key ID: {access_key}")
        
            # 6. Verify user has correct permissions
            self.verify_user_permissions(iam_client, username, region)
        
            return {
                'username': username,
                'region': region,
                'access_key': access_key,
                'secret_key': secret_key,
                'console_url': f"https://{account_config['account_id']}.signin.aws.amazon.com/console"
            }
        
        except Exception as e:
            self.logger.log_user_action(username, "CREATE_USER", "FAILED", str(e))
            raise

    def verify_user_permissions(self, iam_client, username, region):
        """Verify the user has the correct permissions through group membership"""
        try:
            # Check which groups user belongs to
            groups_response = iam_client.list_groups_for_user(UserName=username)
            self.logger.debug(f"User {username} belongs to {len(groups_response['Groups'])} groups")
        
            for group in groups_response['Groups']:
                self.logger.debug(f"User {username} is member of group: {group['GroupName']}")
            
            # Check user's inline policies to verify region restriction
            try:
                policy_response = iam_client.get_user_policy(
                    UserName=username,
                    PolicyName="Restrict-Region-And-EC2-Managed-Types"
                )
                self.logger.debug(f"User {username} has region restriction policy")
            
                # Parse and verify the policy content
                policy_doc = policy_response['PolicyDocument']
                if isinstance(policy_doc, str):
                    policy_doc = json.loads(policy_doc)
                
                # Check if the policy restricts to the correct region
                for statement in policy_doc.get('Statement', []):
                    if statement.get('Sid') == 'DenyIfNotInRegion':
                        policy_region = statement.get('Condition', {}).get('StringNotEquals', {}).get(
                            'aws:RequestedRegion')

                        # Handle case where policy_region might be a list or string
                        if isinstance(policy_region, list):
                            # If it's a list, check if the region is in the list
                            if region in policy_region:
                                self.logger.debug(f"User {username} has correct region restriction: {region}")
                            else:
                                self.logger.warning(
                                    f"User {username} has incorrect region restriction: {policy_region}, should include {region}")
                        elif isinstance(policy_region, str):
                            # If it's a string, do direct comparison
                            if policy_region == region:
                                self.logger.debug(f"User {username} has correct region restriction: {region}")
                            else:
                                self.logger.warning(
                                    f"User {username} has incorrect region restriction: {policy_region}, should be {region}")
                        elif policy_region is None:
                            self.logger.warning(f"User {username} has no region restriction policy found")
                        else:
                            self.logger.warning(
                                f"User {username} has unexpected region restriction format: {policy_region}, expected string or list")

            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    self.logger.warning(f"User {username} does not have a region restriction policy")
                else:
                    self.logger.error(f"Error checking region policy for {username}: {e}")
                
            self.logger.log_user_action(username, "VERIFY_PERMISSIONS", "SUCCESS", f"User has expected group memberships for region {region}")
        
        except Exception as e:
            self.logger.error(f"Error verifying permissions for user {username}: {e}")
            # Don't raise here, just log the error

    def ensure_user_in_group(self, iam_client, username, group_name, account_name):
        """Ensure an existing user is added to the specified group"""
        try:
            # Check if user is already in the group
            groups_response = iam_client.list_groups_for_user(UserName=username)
            is_in_group = any(g['GroupName'] == group_name for g in groups_response['Groups'])
        
            if not is_in_group:
                self.logger.info(f"Adding existing user {username} to group {group_name}")
                iam_client.add_user_to_group(
                    GroupName=group_name,
                    UserName=username
                )
                self.logger.log_user_action(username, "ADD_TO_GROUP", "SUCCESS", 
                                           f"Added existing user to group {group_name}")
            else:
                self.logger.debug(f"User {username} is already in group {group_name}")
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to add user {username} to group {group_name}: {e}")
            raise

    def create_users_in_account(self, account_name):
        """Create users in a specific AWS account"""
        self.logger.info(f"Processing account: {account_name.upper()}")
    
        # Check if account has any user mappings
        users_regions = self.get_users_for_account(account_name)
    
        if not users_regions:
            self.logger.warning(f"No user mappings found for account: {account_name}")
            return [], [], []
    
        self.logger.info(f"Found {len(users_regions)} mapped users for account {account_name}")
    
        try:
            # Initialize IAM client for this account
            iam_client, account_config = self.create_iam_client(account_name)
        
            # Create or get group for this account
            group_name = self.create_or_get_group(iam_client, account_name)
            self.logger.info(f"Using group {group_name} for account {account_name}")
        
        except Exception as e:
            self.logger.error(f"Failed to connect to {account_name} or create group: {e}")
            return [], [], []
    
        created_users = []
        skipped_users = []
        failed_users = []
    
        # Check existing users first
        self.logger.info(f"Checking for existing users in {account_name}...")
        for username, region in users_regions.items():
            user_info = self.get_user_info(username)
            if user_info is None:
                self.logger.error(f"User info not found for {username}, skipping...")
                failed_users.append(username)
                continue
            
            try:
                if self.check_user_exists(iam_client, username):
                    self.logger.log_user_action(username, "SKIP", "ALREADY_EXISTS", user_info['full_name'])
                
                    # Try to add existing user to group if they're not already a member
                    try:
                        self.ensure_user_in_group(iam_client, username, group_name, account_name)
                    except Exception as e:
                        self.logger.warning(f"Failed to add existing user {username} to group: {e}")
                
                    skipped_users.append({
                        'username': username,
                        'region': region,
                        'reason': 'Already exists',
                        'user_info': user_info
                    })
                    continue
            except Exception as e:
                self.logger.log_user_action(username, "CHECK", "FAILED", str(e))
                failed_users.append(username)
                continue
    
        # Create new users
        users_to_create = {k: v for k, v in users_regions.items() 
                          if k not in [u['username'] for u in skipped_users] 
                          and k not in failed_users}
    
        if not users_to_create:
            self.logger.warning(f"No new users to create in {account_name}")
            return created_users, skipped_users, failed_users
    
        self.logger.info(f"Creating {len(users_to_create)} new users in {account_name}")
    
        for username, region in users_to_create.items():
            user_info = self.get_user_info(username)
            if user_info is None:
                self.logger.error(f"User info not found for {username}, skipping...")
                failed_users.append(username)
                continue
            
            self.logger.info(f"Creating user: {username} → {user_info['full_name']} (Region: {region})")
        
            try:
                user_data = self.create_single_user(iam_client, username, region, account_config, group_name)
            
                # Add account and real user information
                user_data.update({
                    'account_name': account_name,
                    'account_id': account_config['account_id'],
                    'account_email': account_config['email'],
                    'user_info': user_info
                })
            
                created_users.append(user_data)
                self.logger.log_user_action(username, "COMPLETE", "SUCCESS", 
                                          f"All resources created for {user_info['full_name']}")
            
            except Exception as e:
                self.logger.log_user_action(username, "CREATE", "FAILED", str(e))
                failed_users.append(username)
                continue
    
        return created_users, skipped_users, failed_users

    def display_account_menu(self):
        """Display account selection menu with mapping information"""
        print("\n[LIST] Available AWS Accounts:")

        # Show accounts with mappings
        accounts_with_mappings = []
        accounts_without_mappings = []

        for i, (account_name, config) in enumerate(self.aws_accounts.items(), 1):
            user_count = len(self.get_users_for_account(account_name))
            if user_count > 0:
                print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']} [{user_count} users mapped]")
                accounts_with_mappings.append(account_name)
            else:
                print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']} [[WARN]  NO USERS MAPPED]")
                accounts_without_mappings.append(account_name)

        print(f"  {len(self.aws_accounts) + 1}. All accounts with mappings ({len(accounts_with_mappings)} accounts)")
        print(f"  {len(self.aws_accounts) + 2}. All accounts (including unmapped)")

        if accounts_without_mappings:
            print(f"\n[WARN]  Warning: {len(accounts_without_mappings)} accounts have no user mappings:")
            for account in accounts_without_mappings:
                print(f"     - {account}")
            print("   These accounts will be skipped unless you explicitly select them.")

        print(f"\n[TIP] Selection Options:")
        print(f"   • Single account: 1")
        print(f"   • Multiple accounts: 1,3,5")
        print(f"   • Range: 1-3")
        print(f"   • Mixed: 1,3-5,7")
        print(f"   • All with mappings: {len(self.aws_accounts) + 1}")
        print(f"   • All accounts: {len(self.aws_accounts) + 2}")

        while True:
            try:
                choice = input(f"\n🔢 Select account(s) to process: ").strip()

                # Handle special cases first
                if choice == str(len(self.aws_accounts) + 1):
                    # All accounts with mappings
                    return accounts_with_mappings
                elif choice == str(len(self.aws_accounts) + 2):
                    # All accounts
                    if accounts_without_mappings:
                        confirm = input(
                            f"[WARN]  This includes {len(accounts_without_mappings)} accounts with no mappings. Continue? (y/N): ").lower().strip()
                        if confirm != 'y':
                            continue
                    return list(self.aws_accounts.keys())

                # Parse the selection
                selected_accounts = self.parse_account_selection(choice)

                if not selected_accounts:
                    print(f"[ERROR] Invalid selection. Please try again.")
                    continue

                # Validate all selections are within range
                account_names = list(self.aws_accounts.keys())
                invalid_selections = [num for num in selected_accounts if num < 1 or num > len(self.aws_accounts)]

                if invalid_selections:
                    print(
                        f"[ERROR] Invalid account numbers: {invalid_selections}. Please enter numbers between 1 and {len(self.aws_accounts)}")
                    continue

                # Convert numbers to account names
                selected_account_names = [account_names[num - 1] for num in selected_accounts]

                # Remove duplicates while preserving order
                selected_account_names = list(dict.fromkeys(selected_account_names))

                # Warn about unmapped accounts in selection
                unmapped_in_selection = [acc for acc in selected_account_names if acc in accounts_without_mappings]
                if unmapped_in_selection:
                    print(
                        f"[WARN]  Selected accounts include {len(unmapped_in_selection)} with no mappings: {unmapped_in_selection}")
                    confirm = input(f"Continue? (y/N): ").lower().strip()
                    if confirm != 'y':
                        continue

                print(f"[OK] Selected accounts: {selected_account_names}")
                return selected_account_names

            except ValueError as e:
                print(f"[ERROR] Invalid input format: {e}")
                continue

    def parse_account_selection(self, selection):
        """Parse account selection string supporting single, comma-separated, ranges, and mixed formats"""
        try:
            selected_numbers = []

            # Split by comma first
            parts = [part.strip() for part in selection.split(',')]

            for part in parts:
                if '-' in part:
                    # Handle range like "1-3"
                    try:
                        start, end = part.split('-')
                        start_num = int(start.strip())
                        end_num = int(end.strip())

                        if start_num > end_num:
                            raise ValueError(f"Invalid range: {part} (start > end)")

                        # Add all numbers in range
                        selected_numbers.extend(range(start_num, end_num + 1))

                    except ValueError as e:
                        if "Invalid range" in str(e):
                            raise e
                        else:
                            raise ValueError(f"Invalid range format: {part}")
                else:
                    # Handle single number
                    try:
                        num = int(part)
                        selected_numbers.append(num)
                    except ValueError:
                        raise ValueError(f"Invalid number: {part}")

            return selected_numbers

        except Exception as e:
            print(f"[ERROR] Error parsing selection: {e}")
            return []

    def save_credentials_to_file(self, all_created_users):
        """Save user credentials to a JSON file and create Excel with correct column order"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Save in the aws/iam directory
            os.makedirs("aws/iam", exist_ok=True)
            filename = f"aws/iam/iam_users_credentials_{timestamp}.json"
            
            credentials_data = {
                "created_date": self.current_time.split()[0],
                "created_time": self.current_time.split()[1] + " UTC",
                "created_by": self.current_user,
                "total_users": len(all_created_users),
                "accounts": {}
            }
            
            # Group users by account
            for user in all_created_users:
                account_name = user['account_name']
                if account_name not in credentials_data["accounts"]:
                    credentials_data["accounts"][account_name] = {
                        "account_id": user['account_id'],
                        "account_email": user['account_email'],
                        "users": []
                    }
                
                credentials_data["accounts"][account_name]["users"].append({
                    "username": user['username'],
                    "real_user": {
                        "first_name": user['user_info']['first_name'],
                        "last_name": user['user_info']['last_name'],
                        "full_name": user['user_info']['full_name'],
                        "email": user['user_info']['email']
                    },
                    "region": user['region'],
                    "access_key_id": user['access_key'],
                    "secret_access_key": user['secret_key'],
                    "console_password": self.user_settings['password'],
                    "console_url": user['console_url']
                })
            
            with open(filename, 'w') as f:
                json.dump(credentials_data, f, indent=2)
            
            self.logger.log_credentials_saved(filename, len(all_created_users))
            
            # Create Excel file with correct column order
            try:
                exporter = ExcelCredentialsExporter()
                excel_path = exporter.export_from_json(filename)
                self.logger.info(f"Excel file created with correct column order: {excel_path}")
                print(f"[STATS] Excel file created: {excel_path}")
                print(f"[LIST] Columns: firstname, lastname, mail id, username, password, loginurl, homeregion, accesskey, secretkey")
                
                # Optionally create summary Excel with multiple sheets
                summary_path = exporter.create_summary_sheet(filename)
                self.logger.info(f"Summary Excel created: {summary_path}")
                print(f"📈 Summary Excel created: {summary_path}")
                
            except Exception as e:
                self.logger.error(f"Failed to create Excel files: {e}")
                print(f"[ERROR] Failed to create Excel files: {e}")
            
            return filename
            
        except Exception as e:
            self.logger.error(f"Failed to save credentials to file: {e}")
            return None

    def run(self):
        """Main execution method"""
        self.logger.info("Starting AWS IAM User Creation with Real User Mapping")
        self.logger.info(f"Execution time: {self.current_time} UTC")
        self.logger.info(f"Executed by: {self.current_user}")
        
        # Display mapping analysis
        print(f"\n[STATS] User Mapping Analysis:")
        print(f"   Total AWS accounts: {len(self.aws_accounts)}")
        print(f"   Accounts with mappings: {len(self.accounts_with_mappings)}")
        print(f"   Accounts without mappings: {len(self.accounts_without_mappings)}")
        print(f"   Total mapped users: {len(self.user_mappings)}")
        
        # Select accounts to process
        accounts_to_process = self.display_account_menu()
        self.logger.info(f"Selected accounts for processing: {accounts_to_process}")
        
        all_created_users = []
        all_skipped_users = []
        all_failed_users = []
        
        # Process selected accounts
        for account_name in accounts_to_process:
            created_users, skipped_users, failed_users = self.create_users_in_account(account_name)
            all_created_users.extend(created_users)
            all_skipped_users.extend(skipped_users)
            all_failed_users.extend(failed_users)
        
        # Log final summary
        total_processed = len(all_created_users) + len(all_skipped_users) + len(all_failed_users)
        self.logger.log_summary(total_processed, len(all_created_users), len(all_failed_users), len(all_skipped_users))
        
        # Display summary
        print(f"\n📈 Execution Summary:")
        print(f"   Users created: {len(all_created_users)}")
        print(f"   Users skipped: {len(all_skipped_users)}")
        print(f"   Users failed: {len(all_failed_users)}")
        
        # Save credentials if any users were created
        if all_created_users:
            #save_to_file = input("\n[INSTANCE] Save credentials to file? (y/N): ").lower().strip()
            save_to_file = 'y'  # Automatically save to file for demonstration purposes
            if save_to_file == 'y':
                saved_file = self.save_credentials_to_file(all_created_users)
                if saved_file:
                    print(f"[OK] Credentials saved to: {saved_file}")
                    print("[STATS] Excel files also generated in output/ directory")
        else:
            print("\n[WARN]  No users were created. Nothing to save.")

def main():
    """Main function"""
    try:
        # Create necessary directory structure
        os.makedirs("aws/iam/create", exist_ok=True)
        manager = IAMUserManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()