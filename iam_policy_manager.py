import boto3
import logging
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Optional, Dict, Any
import time
from datetime import datetime
from root_iam_credential_manager import Colors
from text_symbols import Symbols


class IAMPolicyManager:
    """
    Pure IAM operations manager.

    Handles all AWS IAM API calls for policies and roles.
    Does not handle credential selection - receives credentials from caller.

    Author: varadharajaan
    Created: 2025-06-25
    """

    def __init__(self):
        """Initialize the IAM Policy Manager."""
        self._setup_logging()
        self.iam_client = None
        self.sts_client = None
        self.account_id = None
        self.current_credentials = None

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def _setup_logging(self):
        """Configure logging for the class."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    def initialize_with_credentials(self, credentials: Dict[str, str]) -> bool:
        """
        Initialize AWS clients with provided credentials.

        Args:
            credentials (Dict): Credentials dictionary with access_key, secret_key, region

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.iam_client = boto3.client(
                'iam',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key'],
                region_name=credentials['region']
            )

            self.sts_client = boto3.client(
                'sts',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key'],
                region_name=credentials['region']
            )

            self.account_id = self.sts_client.get_caller_identity()['Account']
            self.current_credentials = credentials

            self.logger.info(f"Initialized clients for account: {self.account_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize AWS clients: {str(e)}")
            return False

    # === POLICY OPERATIONS ===

    def delete_custom_policies_from_role(self, role_name: str, dry_run: bool = False) -> Dict[str, Any]:
        """Delete all custom policies attached to a specific IAM role."""
        if not self.iam_client:
            return {'operation': 'delete_custom_policies_from_role', 'errors': ['IAM client not initialized']}

        results = {
            'operation': 'delete_custom_policies_from_role',
            'timestamp': datetime.now(datetime.UTC).isoformat(),
            'role_name': role_name,
            'account_id': self.account_id,
            'custom_policies_found': [],
            'aws_managed_policies_found': [],
            'deleted_policies': [],
            'failed_deletions': [],
            'errors': [],
            'dry_run': dry_run
        }

        try:
            self.logger.info(f"{'DRY RUN - ' if dry_run else ''}Processing role: {role_name}")

            if not self._role_exists(role_name):
                error_msg = f"Role '{role_name}' does not exist"
                results['errors'].append(error_msg)
                self.logger.error(error_msg)
                return results

            attached_policies = self._get_attached_role_policies(role_name)

            for policy in attached_policies:
                policy_arn = policy['PolicyArn']
                policy_name = policy['PolicyName']

                if self._is_custom_policy(policy_arn):
                    results['custom_policies_found'].append({'name': policy_name, 'arn': policy_arn})
                    self.logger.info(f"Found custom policy: {policy_name}")

                    if not dry_run:
                        delete_result = self._detach_and_delete_custom_policy(role_name, policy_arn, policy_name)
                        if delete_result['success']:
                            results['deleted_policies'].append(policy_name)
                        else:
                            results['failed_deletions'].append({
                                'policy_name': policy_name,
                                'reason': delete_result['error']
                            })
                else:
                    results['aws_managed_policies_found'].append({'name': policy_name, 'arn': policy_arn})

        except Exception as e:
            error_msg = f"Unexpected error processing role {role_name}: {str(e)}"
            results['errors'].append(error_msg)
            self.logger.error(error_msg)

        return results

    def delete_all_custom_policies_in_account(self, dry_run: bool = False,
                                              exclude_policies: Optional[List[str]] = None) -> Dict[str, Any]:
        """Delete ALL custom policies in the AWS account."""
        if not self.iam_client:
            return {'operation': 'delete_all_custom_policies_in_account', 'errors': ['IAM client not initialized']}

        if exclude_policies is None:
            exclude_policies = []

        results = {
            'operation': 'delete_all_custom_policies_in_account',
            'timestamp': datetime.now(datetime.UTC).isoformat(),
            'account_id': self.account_id,
            'total_custom_policies_found': 0,
            'policies_to_process': [],
            'deleted_policies': [],
            'failed_deletions': [],
            'excluded_policies': [],
            'errors': [],
            'dry_run': dry_run
        }

        try:
            self.logger.info(f"{'DRY RUN - ' if dry_run else ''}Starting account-wide policy deletion")

            custom_policies = self._get_all_custom_policies()

            for policy in custom_policies:
                policy_name = policy['PolicyName']
                policy_arn = policy['Arn']

                results['total_custom_policies_found'] += 1

                if policy_name in exclude_policies:
                    results['excluded_policies'].append(policy_name)
                    continue

                results['policies_to_process'].append({
                    'name': policy_name,
                    'arn': policy_arn,
                    'create_date': policy['CreateDate'].isoformat() if 'CreateDate' in policy else 'Unknown'
                })

                if not dry_run:
                    delete_result = self._detach_and_delete_policy_completely(policy_arn, policy_name)
                    if delete_result['success']:
                        results['deleted_policies'].append(policy_name)
                    else:
                        results['failed_deletions'].append({
                            'policy_name': policy_name,
                            'reason': delete_result['error']
                        })
                    time.sleep(0.1)

        except Exception as e:
            error_msg = f"Unexpected error in account policy cleanup: {str(e)}"
            results['errors'].append(error_msg)
            self.logger.error(error_msg)

        return results

    # === ROLE OPERATIONS ===

    def delete_custom_roles(self, role_names: Optional[List[str]] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Delete custom IAM roles."""
        if not self.iam_client:
            return {'operation': 'delete_custom_roles', 'errors': ['IAM client not initialized']}

        results = {
            'operation': 'delete_custom_roles',
            'timestamp': datetime.now(datetime.UTC).isoformat(),
            'account_id': self.account_id,
            'roles_found': [],
            'roles_to_delete': [],
            'deleted_roles': [],
            'failed_deletions': [],
            'aws_service_roles_found': [],
            'errors': [],
            'dry_run': dry_run
        }

        try:
            if role_names:
                # Use specific role names
                for role_name in role_names:
                    if self._role_exists(role_name):
                        role_info = self._get_role_info(role_name)
                        if role_info:
                            results['roles_found'].append(role_info)
                            if self._is_custom_role(role_info):
                                results['roles_to_delete'].append(role_info)
                            else:
                                results['aws_service_roles_found'].append(role_info)
                    else:
                        results['errors'].append(f"Role '{role_name}' does not exist")
            else:
                # Get all roles and let user select
                all_roles = self._get_all_roles()
                custom_roles = [role for role in all_roles if self._is_custom_role(role)]

                if not custom_roles:
                    results['errors'].append("No custom roles found in the account")
                    return results

                results['roles_found'] = custom_roles
                results['roles_to_delete'] = custom_roles  # For now, select all custom roles

            # Process deletion
            for role_info in results['roles_to_delete']:
                role_name = role_info['role_name']

                if not dry_run:
                    delete_result = self._delete_role_completely(role_name)
                    if delete_result['success']:
                        results['deleted_roles'].append(role_name)
                    else:
                        results['failed_deletions'].append({
                            'role_name': role_name,
                            'reason': delete_result['error']
                        })

        except Exception as e:
            error_msg = f"Unexpected error in role deletion: {str(e)}"
            results['errors'].append(error_msg)
            self.logger.error(error_msg)

        return results

    def get_role_policy_summary(self, role_name: str) -> Dict[str, Any]:
        """Get a summary of all policies attached to a role."""
        if not self.iam_client:
            return {'errors': ['IAM client not initialized']}

        summary = {
            'role_name': role_name,
            'account_id': self.account_id,
            'timestamp': datetime.now(datetime.UTC).isoformat(),
            'custom_policies': [],
            'aws_managed_policies': [],
            'inline_policies': [],
            'total_policies': 0,
            'errors': []
        }

        try:
            if not self._role_exists(role_name):
                summary['errors'].append(f"Role '{role_name}' does not exist")
                return summary

            # Get attached policies
            attached_policies = self._get_attached_role_policies(role_name)
            for policy in attached_policies:
                policy_info = {'name': policy['PolicyName'], 'arn': policy['PolicyArn']}
                if self._is_custom_policy(policy['PolicyArn']):
                    summary['custom_policies'].append(policy_info)
                else:
                    summary['aws_managed_policies'].append(policy_info)

            # Get inline policies
            try:
                response = self.iam_client.list_role_policies(RoleName=role_name)
                for policy_name in response.get('PolicyNames', []):
                    summary['inline_policies'].append({'name': policy_name})
            except ClientError:
                pass

            summary['total_policies'] = (
                    len(summary['custom_policies']) +
                    len(summary['aws_managed_policies']) +
                    len(summary['inline_policies'])
            )

        except Exception as e:
            summary['errors'].append(f"Error getting role summary: {str(e)}")

        return summary

    # === HELPER METHODS ===

    def _role_exists(self, role_name: str) -> bool:
        """Check if a role exists."""
        try:
            self.iam_client.get_role(RoleName=role_name)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                return False
            raise

    def _is_custom_policy(self, policy_arn: str) -> bool:
        """Check if a policy is customer-managed."""
        return f"::{self.account_id}:policy/" in policy_arn

    def _get_attached_role_policies(self, role_name: str) -> List[Dict[str, str]]:
        """Get all attached policies for a role."""
        policies = []
        paginator = self.iam_client.get_paginator('list_attached_role_policies')
        for page in paginator.paginate(RoleName=role_name):
            policies.extend(page['AttachedPolicies'])
        return policies

    def _get_all_custom_policies(self) -> List[Dict[str, Any]]:
        """Get all customer-managed policies."""
        policies = []
        paginator = self.iam_client.get_paginator('list_policies')
        for page in paginator.paginate(Scope='Local'):
            policies.extend(page['Policies'])
        return policies

    def _get_all_roles(self) -> List[Dict[str, Any]]:
        """Get all IAM roles."""
        roles = []
        try:
            paginator = self.iam_client.get_paginator('list_roles')
            for page in paginator.paginate():
                for role in page['Roles']:
                    role_info = {
                        'role_name': role['RoleName'],
                        'arn': role['Arn'],
                        'path': role['Path'],
                        'create_date': role['CreateDate'],
                        'assume_role_policy': role.get('AssumeRolePolicyDocument', {}),
                        'description': role.get('Description', ''),
                        'max_session_duration': role.get('MaxSessionDuration', 3600)
                    }
                    roles.append(role_info)
        except Exception as e:
            self.logger.error(f"Error getting roles: {e}")
        return roles

    def _get_role_info(self, role_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific role."""
        try:
            response = self.iam_client.get_role(RoleName=role_name)
            role = response['Role']
            return {
                'role_name': role['RoleName'],
                'arn': role['Arn'],
                'path': role['Path'],
                'create_date': role['CreateDate'],
                'assume_role_policy': role.get('AssumeRolePolicyDocument', {}),
                'description': role.get('Description', ''),
                'max_session_duration': role.get('MaxSessionDuration', 3600)
            }
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                return None
            raise

    def _is_custom_role(self, role_info: Dict[str, Any]) -> bool:
        """Determine if a role is custom vs AWS service role."""
        role_name = role_info['role_name']
        path = role_info['path']

        # AWS service role patterns
        aws_service_patterns = [
            'AWSServiceRole', 'aws-service-role', 'service-role',
            'OrganizationAccountAccessRole', 'CloudFormation-',
            'AWS-CodeBuild-', 'AWS-CodeDeploy-', 'lambda-',
            'rds-', 'ec2-', 'eks-', 'EMR_', 'DataPipelineDefaultRole',
            'ecsTaskExecutionRole', 'ecs-'
        ]

        # Check path
        if '/aws-service-role/' in path or '/service-role/' in path:
            return False

        # Check role name patterns
        for pattern in aws_service_patterns:
            if pattern in role_name:
                return False

        return True

    def _detach_and_delete_custom_policy(self, role_name: str, policy_arn: str, policy_name: str) -> Dict[str, Any]:
        """Detach and delete a custom policy."""
        try:
            # Detach from role
            self.iam_client.detach_role_policy(RoleName=role_name, PolicyArn=policy_arn)

            # Check if attached to other entities
            try:
                entities = self.iam_client.list_entities_for_policy(PolicyArn=policy_arn)
                if (entities.get('PolicyUsers') or entities.get('PolicyGroups') or entities.get('PolicyRoles')):
                    detach_result = self._detach_policy_from_all_entities(policy_arn, policy_name)
                    if not detach_result['success']:
                        return {'success': False, 'error': f"Failed to detach from all entities"}
            except ClientError:
                pass

            # Delete policy versions
            self._delete_policy_versions(policy_arn, policy_name)

            # Delete policy
            self.iam_client.delete_policy(PolicyArn=policy_arn)
            return {'success': True}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _detach_and_delete_policy_completely(self, policy_arn: str, policy_name: str) -> Dict[str, Any]:
        """Completely detach and delete a policy."""
        try:
            # Detach from all entities
            detach_result = self._detach_policy_from_all_entities(policy_arn, policy_name)
            if not detach_result['success']:
                return {'success': False, 'error': "Failed to detach from all entities"}

            # Delete versions
            self._delete_policy_versions(policy_arn, policy_name)

            # Delete policy
            self.iam_client.delete_policy(PolicyArn=policy_arn)
            return {'success': True}

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                return {'success': True}
            return {'success': False, 'error': str(e)}

    def _detach_policy_from_all_entities(self, policy_arn: str, policy_name: str) -> Dict[str, Any]:
        """Detach policy from all users, groups, and roles."""
        try:
            response = self.iam_client.list_entities_for_policy(PolicyArn=policy_arn)

            # Detach from users
            for user in response.get('PolicyUsers', []):
                try:
                    self.iam_client.detach_user_policy(UserName=user['UserName'], PolicyArn=policy_arn)
                except ClientError:
                    pass

            # Detach from groups
            for group in response.get('PolicyGroups', []):
                try:
                    self.iam_client.detach_group_policy(GroupName=group['GroupName'], PolicyArn=policy_arn)
                except ClientError:
                    pass

            # Detach from roles
            for role in response.get('PolicyRoles', []):
                try:
                    self.iam_client.detach_role_policy(RoleName=role['RoleName'], PolicyArn=policy_arn)
                except ClientError:
                    pass

            return {'success': True}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _delete_policy_versions(self, policy_arn: str, policy_name: str) -> Dict[str, Any]:
        """Delete all non-default versions of a policy."""
        try:
            response = self.iam_client.list_policy_versions(PolicyArn=policy_arn)

            for version in response.get('Versions', []):
                if not version['IsDefaultVersion']:
                    try:
                        self.iam_client.delete_policy_version(PolicyArn=policy_arn, VersionId=version['VersionId'])
                    except ClientError:
                        pass

            return {'success': True}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _delete_role_completely(self, role_name: str) -> Dict[str, Any]:
        """Completely delete a role."""
        try:
            # Detach managed policies
            self._detach_all_managed_policies_from_role(role_name)

            # Delete inline policies
            self._delete_all_inline_policies_from_role(role_name)

            # Remove from instance profiles
            self._remove_role_from_instance_profiles(role_name)

            # Delete role
            self.iam_client.delete_role(RoleName=role_name)
            return {'success': True}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _detach_all_managed_policies_from_role(self, role_name: str):
        """Detach all managed policies from role."""
        try:
            paginator = self.iam_client.get_paginator('list_attached_role_policies')
            for page in paginator.paginate(RoleName=role_name):
                for policy in page['AttachedPolicies']:
                    try:
                        self.iam_client.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
                    except ClientError:
                        pass
        except ClientError:
            pass

    def _delete_all_inline_policies_from_role(self, role_name: str):
        """Delete all inline policies from role."""
        try:
            paginator = self.iam_client.get_paginator('list_role_policies')
            for page in paginator.paginate(RoleName=role_name):
                for policy_name in page['PolicyNames']:
                    try:
                        self.iam_client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                    except ClientError:
                        pass
        except ClientError:
            pass

    def _remove_role_from_instance_profiles(self, role_name: str):
        """Remove role from all instance profiles."""
        try:
            paginator = self.iam_client.get_paginator('list_instance_profiles_for_role')
            for page in paginator.paginate(RoleName=role_name):
                for instance_profile in page['InstanceProfiles']:
                    try:
                        self.iam_client.remove_role_from_instance_profile(
                            InstanceProfileName=instance_profile['InstanceProfileName'],
                            RoleName=role_name
                        )
                    except ClientError:
                        pass
        except ClientError:
            pass