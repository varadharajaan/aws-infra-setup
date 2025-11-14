#!/usr/bin/env python3

import json
import os
import time
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraCleanupIAMManager:
    """
    Tool to perform comprehensive cleanup of IAM resources across AWS accounts.

    Manages deletion of:
    - IAM Users
    - IAM Groups
    - Access Keys
    - Policies (attached and inline)
    - MFA Devices
    - Service-specific credentials

    Author: varadharajaan
    Created: 2025-07-05
    """

    def __init__(self, config_dir: str = None):
        """Initialize the IAM Cleanup Manager."""
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Set up directory paths
        self.iam_dir = os.path.join(self.config_dir, "aws", "iam")
        self.reports_dir = os.path.join(self.iam_dir, "reports")

        # Initialize log file
        self.setup_detailed_logging()

        # Storage for cleanup results
        self.cleanup_results = {
            "accounts_processed": [],
            "users_deleted": [],
            "groups_deleted": [],
            "policies_detached": [],
            "access_keys_deleted": [],
            "failed_operations": [],
            "errors": [],
        }

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            os.makedirs(self.iam_dir, exist_ok=True)

            # Save log file in the aws/iam directory
            self.log_filename = (
                f"{self.iam_dir}/ultra_iam_cleanup_log_{self.execution_timestamp}.log"
            )

            # Create a file handler for detailed logging
            import logging

            # Create logger for detailed operations
            self.operation_logger = logging.getLogger("ultra_iam_cleanup")
            self.operation_logger.setLevel(logging.INFO)

            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)

            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding="utf-8")
            file_handler.setLevel(logging.INFO)

            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # Formatter
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)

            # Log initial information
            self.operation_logger.info("=" * 100)
            self.operation_logger.info("🚨 ULTRA IAM CLEANUP SESSION STARTED 🚨")
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config Dir: {self.config_dir}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)

        except Exception as e:
            self.print_colored(
                Colors.YELLOW, f"Warning: Could not setup detailed logging: {e}"
            )
            self.operation_logger = None

    def log_operation(self, level, message):
        """Simple logging operation"""
        if self.operation_logger:
            if level.upper() == "INFO":
                self.operation_logger.info(message)
            elif level.upper() == "WARNING":
                self.operation_logger.warning(message)
            elif level.upper() == "ERROR":
                self.operation_logger.error(message)
            elif level.upper() == "DEBUG":
                self.operation_logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")

    def create_iam_client(self, access_key, secret_key):
        """Create IAM client using account credentials"""
        try:
            iam_client = boto3.client(
                "iam", aws_access_key_id=access_key, aws_secret_access_key=secret_key
            )

            # Test the connection
            iam_client.get_account_summary()
            return iam_client

        except Exception as e:
            self.log_operation("ERROR", f"Failed to create IAM client: {e}")
            raise

    def get_all_iam_users(self, iam_client, account_info):
        """Get all IAM users in an account"""
        try:
            users = []
            account_name = account_info.get("account_key", "Unknown")

            self.log_operation("INFO", f"🔍 Scanning for IAM users in {account_name}")
            print(f"   🔍 Scanning for IAM users in {account_name}...")

            paginator = iam_client.get_paginator("list_users")

            for page in paginator.paginate():
                for user in page["Users"]:
                    username = user["UserName"]
                    user_id = user["UserId"]
                    created_date = user["CreateDate"]

                    # Get user's groups
                    try:
                        groups_response = iam_client.list_groups_for_user(
                            UserName=username
                        )
                        groups = [
                            group["GroupName"] for group in groups_response["Groups"]
                        ]
                    except Exception:
                        groups = []

                    # Get user's access keys
                    try:
                        keys_response = iam_client.list_access_keys(UserName=username)
                        access_keys = [
                            key["AccessKeyId"]
                            for key in keys_response["AccessKeyMetadata"]
                        ]
                    except Exception:
                        access_keys = []

                    # Get user's attached policies
                    try:
                        policies_response = iam_client.list_attached_user_policies(
                            UserName=username
                        )
                        attached_policies = [
                            policy["PolicyName"]
                            for policy in policies_response["AttachedPolicies"]
                        ]
                    except Exception:
                        attached_policies = []

                    # Get inline policies
                    try:
                        inline_policies_response = iam_client.list_user_policies(
                            UserName=username
                        )
                        inline_policies = inline_policies_response["PolicyNames"]
                    except Exception:
                        inline_policies = []

                    user_info = {
                        "username": username,
                        "user_id": user_id,
                        "arn": user["Arn"],
                        "created_date": created_date,
                        "account_info": account_info,
                        "groups": groups,
                        "access_keys": access_keys,
                        "attached_policies": attached_policies,
                        "inline_policies": inline_policies,
                    }

                    users.append(user_info)

            self.log_operation(
                "INFO", f"👤 Found {len(users)} IAM users in {account_name}"
            )
            print(f"   👤 Found {len(users)} IAM users in {account_name}")

            return users

        except Exception as e:
            account_name = account_info.get("account_key", "Unknown")
            self.log_operation(
                "ERROR", f"Error getting IAM users in {account_name}: {e}"
            )
            print(f"   ❌ Error getting IAM users in {account_name}: {e}")
            return []

    def get_all_iam_groups(self, iam_client, account_info):
        """Get all IAM groups in an account"""
        try:
            groups = []
            account_name = account_info.get("account_key", "Unknown")

            self.log_operation("INFO", f"🔍 Scanning for IAM groups in {account_name}")
            print(f"   🔍 Scanning for IAM groups in {account_name}...")

            paginator = iam_client.get_paginator("list_groups")

            for page in paginator.paginate():
                for group in page["Groups"]:
                    group_name = group["GroupName"]
                    group_id = group["GroupId"]
                    created_date = group["CreateDate"]

                    # Get group's attached policies
                    try:
                        policies_response = iam_client.list_attached_group_policies(
                            GroupName=group_name
                        )
                        attached_policies = [
                            policy["PolicyName"]
                            for policy in policies_response["AttachedPolicies"]
                        ]
                    except Exception:
                        attached_policies = []

                    # Get inline policies
                    try:
                        inline_policies_response = iam_client.list_group_policies(
                            GroupName=group_name
                        )
                        inline_policies = inline_policies_response["PolicyNames"]
                    except Exception:
                        inline_policies = []

                    # Get users in group
                    try:
                        users_response = iam_client.get_group(GroupName=group_name)
                        users_in_group = [
                            user["UserName"] for user in users_response["Users"]
                        ]
                    except Exception:
                        users_in_group = []

                    group_info = {
                        "group_name": group_name,
                        "group_id": group_id,
                        "arn": group["Arn"],
                        "created_date": created_date,
                        "account_info": account_info,
                        "attached_policies": attached_policies,
                        "inline_policies": inline_policies,
                        "users": users_in_group,
                    }

                    groups.append(group_info)

            self.log_operation(
                "INFO", f"👥 Found {len(groups)} IAM groups in {account_name}"
            )
            print(f"   👥 Found {len(groups)} IAM groups in {account_name}")

            return groups

        except Exception as e:
            account_name = account_info.get("account_key", "Unknown")
            self.log_operation(
                "ERROR", f"Error getting IAM groups in {account_name}: {e}"
            )
            print(f"   ❌ Error getting IAM groups in {account_name}: {e}")
            return []

    def delete_iam_user(self, iam_client, user_info):
        """Delete an IAM user (first removing all dependencies)"""
        try:
            username = user_info["username"]
            account_name = user_info["account_info"].get("account_key", "Unknown")

            self.log_operation(
                "INFO", f"🗑️  Deleting IAM user: {username} in {account_name}"
            )
            print(f"   🗑️  Deleting IAM user: {username}...")

            # Step 1: Delete user's access keys
            for key_id in user_info["access_keys"]:
                try:
                    self.log_operation(
                        "INFO", f"Deleting access key: {key_id} for user {username}"
                    )
                    iam_client.delete_access_key(UserName=username, AccessKeyId=key_id)

                    self.cleanup_results["access_keys_deleted"].append(
                        {
                            "access_key_id": key_id,
                            "username": username,
                            "account_info": user_info["account_info"],
                        }
                    )
                except Exception as e:
                    self.log_operation(
                        "WARNING",
                        f"Failed to delete access key {key_id} for user {username}: {e}",
                    )

            # Step 2: Detach user's managed policies
            try:
                attached_policies_response = iam_client.list_attached_user_policies(
                    UserName=username
                )

                for policy in attached_policies_response.get("AttachedPolicies", []):
                    policy_name = policy["PolicyName"]
                    policy_arn = policy["PolicyArn"]

                    try:
                        self.log_operation(
                            "INFO",
                            f"Detaching policy: {policy_name} from user {username}",
                        )
                        iam_client.detach_user_policy(
                            UserName=username, PolicyArn=policy_arn
                        )

                        self.cleanup_results["policies_detached"].append(
                            {
                                "policy_name": policy_name,
                                "policy_arn": policy_arn,
                                "username": username,
                                "type": "user",
                                "account_info": user_info["account_info"],
                            }
                        )
                    except Exception as e:
                        self.log_operation(
                            "WARNING",
                            f"Failed to detach policy {policy_name} from user {username}: {e}",
                        )
            except Exception as e:
                self.log_operation(
                    "ERROR",
                    f"Error listing or detaching policies for user {username}: {e}",
                )

            # Step 3: Delete user's inline policies
            for policy_name in user_info["inline_policies"]:
                try:
                    self.log_operation(
                        "INFO",
                        f"Deleting inline policy: {policy_name} from user {username}",
                    )
                    iam_client.delete_user_policy(
                        UserName=username, PolicyName=policy_name
                    )
                except Exception as e:
                    self.log_operation(
                        "WARNING",
                        f"Failed to delete inline policy {policy_name} for user {username}: {e}",
                    )

            # Step 4: Remove user from groups
            for group_name in user_info["groups"]:
                try:
                    self.log_operation(
                        "INFO", f"Removing user {username} from group {group_name}"
                    )
                    iam_client.remove_user_from_group(
                        UserName=username, GroupName=group_name
                    )
                except Exception as e:
                    self.log_operation(
                        "WARNING",
                        f"Failed to remove user {username} from group {group_name}: {e}",
                    )

            # Step 5: Delete login profile (if exists)
            try:
                iam_client.get_login_profile(UserName=username)
                self.log_operation(
                    "INFO", f"Deleting login profile for user {username}"
                )
                iam_client.delete_login_profile(UserName=username)
            except ClientError as e:
                if "NoSuchEntity" not in str(e):
                    self.log_operation(
                        "WARNING",
                        f"Error checking/deleting login profile for {username}: {e}",
                    )

            # Step 6: Delete MFA devices
            try:
                mfa_devices_response = iam_client.list_mfa_devices(UserName=username)
                for device in mfa_devices_response["MFADevices"]:
                    self.log_operation(
                        "INFO",
                        f"Deactivating MFA device: {device['SerialNumber']} for user {username}",
                    )
                    iam_client.deactivate_mfa_device(
                        UserName=username, SerialNumber=device["SerialNumber"]
                    )
            except Exception as e:
                self.log_operation(
                    "WARNING", f"Error handling MFA devices for user {username}: {e}"
                )

            # Step 7: Delete service-specific credentials
            try:
                service_creds_response = iam_client.list_service_specific_credentials(
                    UserName=username
                )
                for cred in service_creds_response.get(
                    "ServiceSpecificCredentials", []
                ):
                    self.log_operation(
                        "INFO",
                        f"Deleting service credential ID: {cred['ServiceSpecificCredentialId']} for user {username}",
                    )
                    iam_client.delete_service_specific_credential(
                        UserName=username,
                        ServiceSpecificCredentialId=cred["ServiceSpecificCredentialId"],
                    )
            except Exception as e:
                self.log_operation(
                    "WARNING",
                    f"Error handling service credentials for user {username}: {e}",
                )

            # Step 8: Delete signing certificates
            try:
                cert_response = iam_client.list_signing_certificates(UserName=username)
                for cert in cert_response.get("Certificates", []):
                    self.log_operation(
                        "INFO",
                        f"Deleting signing certificate ID: {cert['CertificateId']} for user {username}",
                    )
                    iam_client.delete_signing_certificate(
                        UserName=username, CertificateId=cert["CertificateId"]
                    )
            except Exception as e:
                self.log_operation(
                    "WARNING",
                    f"Error handling signing certificates for user {username}: {e}",
                )

            # Step 9: Finally delete the user
            self.log_operation("INFO", f"Deleting IAM user: {username}")
            iam_client.delete_user(UserName=username)

            self.cleanup_results["users_deleted"].append(
                {
                    "username": username,
                    "user_id": user_info["user_id"],
                    "account_info": user_info["account_info"],
                    "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

            self.log_operation("INFO", f"✅ Successfully deleted IAM user: {username}")
            print(f"   ✅ Successfully deleted IAM user: {username}")
            return True

        except Exception as e:
            account_name = user_info["account_info"].get("account_key", "Unknown")
            self.log_operation("ERROR", f"Failed to delete IAM user {username}: {e}")
            print(f"   ❌ Failed to delete IAM user {username}: {e}")

            self.cleanup_results["failed_operations"].append(
                {
                    "operation_type": "delete_user",
                    "resource_name": username,
                    "account_info": user_info["account_info"],
                    "error": str(e),
                }
            )

            return False

    def delete_iam_group(self, iam_client, group_info):
        """Delete an IAM group (first removing all dependencies)"""
        try:
            group_name = group_info["group_name"]
            account_name = group_info["account_info"].get("account_key", "Unknown")

            self.log_operation(
                "INFO", f"🗑️  Deleting IAM group: {group_name} in {account_name}"
            )
            print(f"   🗑️  Deleting IAM group: {group_name}...")

            # Step 1: Remove all users from the group
            already_deleted_users = [
                user["username"]
                for user in self.cleanup_results["users_deleted"]
                if user["account_info"].get("account_key") == account_name
            ]

            for username in group_info["users"]:
                try:
                    if username in already_deleted_users:
                        self.log_operation(
                            "INFO",
                            f"Skipping removal of already deleted user {username} from group {group_name}",
                        )
                        continue

                    self.log_operation(
                        "INFO", f"Removing user {username} from group {group_name}"
                    )
                    iam_client.remove_user_from_group(
                        UserName=username, GroupName=group_name
                    )
                except Exception as e:
                    self.log_operation(
                        "WARNING",
                        f"Failed to remove user {username} from group {group_name}: {e}",
                    )

            # Step 2: Detach managed policies from the group
            try:
                attached_policies = iam_client.list_attached_group_policies(
                    GroupName=group_name
                )

                for policy in attached_policies.get("AttachedPolicies", []):
                    policy_name = policy["PolicyName"]
                    policy_arn = policy["PolicyArn"]

                    try:
                        self.log_operation(
                            "INFO",
                            f"Detaching policy: {policy_name} from group {group_name}",
                        )
                        iam_client.detach_group_policy(
                            GroupName=group_name, PolicyArn=policy_arn
                        )

                        self.cleanup_results["policies_detached"].append(
                            {
                                "policy_name": policy_name,
                                "policy_arn": policy_arn,
                                "group_name": group_name,
                                "type": "group",
                                "account_info": group_info["account_info"],
                            }
                        )
                    except Exception as e:
                        self.log_operation(
                            "WARNING",
                            f"Failed to detach policy {policy_name} from group {group_name}: {e}",
                        )
            except Exception as e:
                self.log_operation(
                    "ERROR",
                    f"Error listing or detaching policies for group {group_name}: {e}",
                )

            # Step 3: Delete inline policies
            try:
                inline_policies = iam_client.list_group_policies(
                    GroupName=group_name
                ).get("PolicyNames", [])
                for policy_name in inline_policies:
                    try:
                        self.log_operation(
                            "INFO",
                            f"Deleting inline policy: {policy_name} from group {group_name}",
                        )
                        iam_client.delete_group_policy(
                            GroupName=group_name, PolicyName=policy_name
                        )
                    except Exception as e:
                        self.log_operation(
                            "WARNING",
                            f"Failed to delete inline policy {policy_name} for group {group_name}: {e}",
                        )
            except Exception as e:
                self.log_operation(
                    "WARNING",
                    f"Error listing inline policies for group {group_name}: {e}",
                )

            # Step 4: Add a short delay to ensure AWS has processed all detachments
            time.sleep(1)

            # Step 5: Delete the group
            try:
                self.log_operation("INFO", f"Deleting IAM group: {group_name}")
                iam_client.delete_group(GroupName=group_name)

                self.cleanup_results["groups_deleted"].append(
                    {
                        "group_name": group_name,
                        "group_id": group_info["group_id"],
                        "account_info": group_info["account_info"],
                        "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

                self.log_operation(
                    "INFO", f"✅ Successfully deleted IAM group: {group_name}"
                )
                print(f"   ✅ Successfully deleted IAM group: {group_name}")
                return True
            except Exception as e:
                self.log_operation("ERROR", f"Failed to delete group {group_name}: {e}")
                return False

        except Exception as e:
            account_name = group_info["account_info"].get("account_key", "Unknown")
            self.log_operation("ERROR", f"Failed to delete IAM group {group_name}: {e}")
            print(f"   ❌ Failed to delete IAM group {group_name}: {e}")

            self.cleanup_results["failed_operations"].append(
                {
                    "operation_type": "delete_group",
                    "resource_name": group_name,
                    "account_info": group_info["account_info"],
                    "error": str(e),
                }
            )

            return False

    def cleanup_account_iam(
        self,
        account_info,
        selected_users=None,
        selected_groups=None,
        exclude_root_account=True,
    ):
        """Clean up IAM resources in a specific account"""
        try:
            access_key = account_info["access_key"]
            secret_key = account_info["secret_key"]
            account_id = account_info["account_id"]
            account_key = account_info["account_key"]

            self.log_operation(
                "INFO", f"🧹 Starting IAM cleanup for {account_key} ({account_id})"
            )
            print(f"\n🧹 Starting IAM cleanup for {account_key} ({account_id})")

            # Create IAM client
            iam_client = self.create_iam_client(access_key, secret_key)

            # Get all IAM resources
            users = self.get_all_iam_users(iam_client, account_info)
            groups = self.get_all_iam_groups(iam_client, account_info)

            # Add account summary to results
            self.cleanup_results["accounts_processed"].append(
                {
                    "account_key": account_key,
                    "account_id": account_id,
                    "users_found": len(users),
                    "groups_found": len(groups),
                }
            )

            self.log_operation("INFO", f"📊 {account_key} IAM resources summary:")
            self.log_operation("INFO", f"   👤 IAM Users: {len(users)}")
            self.log_operation("INFO", f"   👥 IAM Groups: {len(groups)}")

            print(
                f"   📊 IAM resources found: {len(users)} users, {len(groups)} groups"
            )

            if not users and not groups:
                self.log_operation("INFO", f"No IAM resources found in {account_key}")
                print(f"   ✅ No IAM resources to clean up")
                return True

            success_count = 0
            failed_count = 0

            # Process selected users
            if selected_users:
                filtered_users = [
                    u
                    for u in users
                    if u["username"] in [su["username"] for su in selected_users]
                ]

                self.log_operation(
                    "INFO",
                    f"🗑️  Deleting {len(filtered_users)} IAM users in {account_key}",
                )
                print(f"\n   🗑️  Deleting {len(filtered_users)} IAM users...")

                for i, user_info in enumerate(filtered_users, 1):
                    username = user_info["username"]

                    # Skip root account user if flag is set
                    if exclude_root_account and "root" in username.lower():
                        self.log_operation(
                            "WARNING", f"Skipping root account user: {username}"
                        )
                        print(f"   ⚠️  Skipping root account user: {username}")
                        continue

                    print(
                        f"   [{i}/{len(filtered_users)}] Processing user {username}..."
                    )

                    try:
                        if self.delete_iam_user(iam_client, user_info):
                            success_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log_operation(
                            "ERROR", f"Error deleting user {username}: {e}"
                        )
                        print(f"   ❌ Error deleting user {username}: {e}")

            # Process selected groups
            if selected_groups:
                filtered_groups = [
                    g
                    for g in groups
                    if g["group_name"] in [sg["group_name"] for sg in selected_groups]
                ]

                self.log_operation(
                    "INFO",
                    f"🗑️  Deleting {len(filtered_groups)} IAM groups in {account_key}",
                )
                print(f"\n   🗑️  Deleting {len(filtered_groups)} IAM groups...")

                for i, group_info in enumerate(filtered_groups, 1):
                    group_name = group_info["group_name"]
                    print(
                        f"   [{i}/{len(filtered_groups)}] Processing group {group_name}..."
                    )

                    try:
                        if self.delete_iam_group(iam_client, group_info):
                            success_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log_operation(
                            "ERROR", f"Error deleting group {group_name}: {e}"
                        )
                        print(f"   ❌ Error deleting group {group_name}: {e}")

            print(f"   ✅ Completed: {success_count} successful, {failed_count} failed")

            self.log_operation("INFO", f"✅ IAM cleanup completed for {account_key}")
            print(f"\n   ✅ IAM cleanup completed for {account_key}")
            return True

        except Exception as e:
            account_key = account_info.get("account_key", "Unknown")
            self.log_operation(
                "ERROR", f"Error cleaning up IAM resources in {account_key}: {e}"
            )
            print(f"   ❌ Error cleaning up IAM resources in {account_key}: {e}")
            self.cleanup_results["errors"].append(
                {"account_info": account_info, "error": str(e)}
            )
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            report_filename = f"{self.reports_dir}/ultra_iam_cleanup_report_{self.execution_timestamp}.json"

            # Calculate statistics
            total_users_deleted = len(self.cleanup_results["users_deleted"])
            total_groups_deleted = len(self.cleanup_results["groups_deleted"])
            total_failed = len(self.cleanup_results["failed_operations"])

            # Group deletions by account
            deletions_by_account = {}

            for user in self.cleanup_results["users_deleted"]:
                account = user["account_info"].get("account_key", "Unknown")
                if account not in deletions_by_account:
                    deletions_by_account[account] = {
                        "users": 0,
                        "groups": 0,
                        "regions": set(),
                    }
                deletions_by_account[account]["users"] += 1

            for group in self.cleanup_results["groups_deleted"]:
                account = group["account_info"].get("account_key", "Unknown")
                if account not in deletions_by_account:
                    deletions_by_account[account] = {
                        "users": 0,
                        "groups": 0,
                        "regions": set(),
                    }
                deletions_by_account[account]["groups"] += 1

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_IAM_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_dir": self.config_dir,
                    "log_file": self.log_filename,
                },
                "summary": {
                    "total_accounts_processed": len(
                        self.cleanup_results["accounts_processed"]
                    ),
                    "total_users_deleted": total_users_deleted,
                    "total_groups_deleted": total_groups_deleted,
                    "total_failed_operations": total_failed,
                    "total_access_keys_deleted": len(
                        self.cleanup_results["access_keys_deleted"]
                    ),
                    "total_policies_detached": len(
                        self.cleanup_results["policies_detached"]
                    ),
                    "deletions_by_account": deletions_by_account,
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results["accounts_processed"],
                    "users_deleted": self.cleanup_results["users_deleted"],
                    "groups_deleted": self.cleanup_results["groups_deleted"],
                    "policies_detached": self.cleanup_results["policies_detached"],
                    "access_keys_deleted": self.cleanup_results["access_keys_deleted"],
                    "failed_operations": self.cleanup_results["failed_operations"],
                    "errors": self.cleanup_results["errors"],
                },
            }

            with open(report_filename, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation(
                "INFO", f"✅ Ultra IAM cleanup report saved to: {report_filename}"
            )
            return report_filename

        except Exception as e:
            self.log_operation(
                "ERROR", f"❌ Failed to save ultra IAM cleanup report: {e}"
            )
            return None

    def run(self):
        """Main execution method - sequential (no threading)"""
        try:
            self.log_operation("INFO", "🚨 STARTING ULTRA IAM CLEANUP SESSION 🚨")

            self.print_colored(Colors.YELLOW, "🚨" * 30)
            self.print_colored(Colors.RED, "💥 ULTRA IAM CLEANUP - SEQUENTIAL 💥")
            self.print_colored(Colors.YELLOW, "🚨" * 30)
            self.print_colored(
                Colors.WHITE, f"📅 Execution Date/Time: {self.current_time} UTC"
            )
            self.print_colored(Colors.WHITE, f"👤 Executed by: {self.current_user}")
            self.print_colored(Colors.WHITE, f"📋 Log File: {self.log_filename}")

            # STEP 1: Select root accounts
            self.print_colored(
                Colors.YELLOW, "\n🔑 Select Root AWS Accounts for IAM Cleanup:"
            )

            root_accounts = self.cred_manager.select_root_accounts_interactive(
                allow_multiple=True
            )
            if not root_accounts:
                self.print_colored(
                    Colors.RED, "❌ No root accounts selected, exiting..."
                )
                return
            selected_accounts = root_accounts

            # STEP 2: Calculate total operations and get IAM resources
            self.print_colored(Colors.YELLOW, f"\n🎯 IAM CLEANUP CONFIGURATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"🔑 Credential source: ROOT ACCOUNTS")
            self.print_colored(
                Colors.WHITE, f"🏦 Selected accounts: {len(selected_accounts)}"
            )
            self.print_colored(Colors.YELLOW, "=" * 80)

            # STEP 3: Discover IAM resources across all selected accounts
            self.print_colored(
                Colors.CYAN,
                f"\n🔍 Scanning {len(selected_accounts)} accounts for IAM resources...",
            )

            all_users = []
            all_groups = []
            account_resources = {}

            for account_info in selected_accounts:
                try:
                    account_key = account_info.get("account_key", "Unknown")
                    print(f"   🔍 Scanning account: {account_key}...")

                    access_key = account_info["access_key"]
                    secret_key = account_info["secret_key"]

                    # Create IAM client
                    iam_client = self.create_iam_client(access_key, secret_key)

                    # Get IAM resources
                    users = self.get_all_iam_users(iam_client, account_info)
                    groups = self.get_all_iam_groups(iam_client, account_info)

                    account_resources[account_key] = {
                        "account_info": account_info,
                        "users": users,
                        "groups": groups,
                    }

                    all_users.extend(users)
                    all_groups.extend(groups)

                    print(
                        f"   ✅ Found {len(users)} users, {len(groups)} groups in {account_key}"
                    )

                except Exception as e:
                    print(f"   ❌ Error scanning account {account_key}: {e}")

            if not account_resources:
                self.print_colored(
                    Colors.RED,
                    "\n❌ No accounts were successfully processed. Nothing to clean up.",
                )
                return

            # STEP 4: Display summary and get user selections
            self.print_colored(Colors.YELLOW, f"\n📊 IAM RESOURCES FOUND:")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"👤 Total Users: {len(all_users)}")
            self.print_colored(Colors.WHITE, f"👥 Total Groups: {len(all_groups)}")
            self.print_colored(Colors.YELLOW, "=" * 80)

            # Ask what to clean up
            self.print_colored(Colors.YELLOW, "\nCleanup Options:")
            self.print_colored(Colors.WHITE, "1. Delete Users")
            self.print_colored(Colors.WHITE, "2. Delete Groups")
            self.print_colored(Colors.WHITE, "3. Delete Both Users and Groups")
            self.print_colored(Colors.WHITE, "4. Cancel Cleanup")

            cleanup_option = input("\nSelect cleanup option (1-4): ").strip()

            if cleanup_option == "4" or not cleanup_option:
                self.print_colored(Colors.RED, "❌ Cleanup cancelled")
                return

            # Process cleanup option
            cleanup_users = cleanup_option in ["1", "3"]
            cleanup_groups = cleanup_option in ["2", "3"]

            users_to_delete = []
            groups_to_delete = []

            # Option to exclude root accounts
            exclude_root = True
            if exclude_root:
                self.print_colored(
                    Colors.GREEN, "✅ Root account users will be excluded from deletion"
                )

            # USERS Selection
            if cleanup_users and all_users:
                self.print_colored(Colors.YELLOW, "\n" + "=" * 80)
                self.print_colored(Colors.YELLOW, "👤 IAM USERS SELECTION")
                self.print_colored(Colors.YELLOW, "=" * 80)

                # Show all users
                print(
                    f"\n{'#':<4} {'Username':<30} {'Account':<15} {'ID':<24} {'Groups'}"
                )
                print("-" * 90)

                for i, user in enumerate(all_users, 1):
                    username = user["username"]
                    account_name = user["account_info"].get("account_key", "Unknown")
                    user_id = user["user_id"]
                    groups = ",".join(user["groups"]) if user["groups"] else "None"

                    # Highlight root users
                    if "root" in username.lower():
                        print(
                            f"{i:<4} {username:<30} {account_name:<15} {user_id:<24} {groups} ⚠️ ROOT USER"
                        )
                    else:
                        print(
                            f"{i:<4} {username:<30} {account_name:<15} {user_id:<24} {groups}"
                        )

                # Ask for user selection
                self.print_colored(Colors.YELLOW, "\nUser Selection Options:")
                self.print_colored(Colors.WHITE, "  • Single users: 1,3,5")
                self.print_colored(Colors.WHITE, "  • Ranges: 1-3")
                self.print_colored(Colors.WHITE, "  • Mixed: 1-3,5,7-9")
                self.print_colored(Colors.WHITE, "  • All users: 'all' or press Enter")
                self.print_colored(Colors.WHITE, "  • Skip users: 'skip'")

                user_selection = input("\n🔢 Select users to delete: ").strip().lower()

                if user_selection != "skip":
                    if not user_selection or user_selection == "all":
                        users_to_delete = all_users
                        self.print_colored(
                            Colors.GREEN, f"✅ Selected all {len(all_users)} IAM users"
                        )
                    else:
                        try:
                            indices = self.cred_manager._parse_selection(
                                user_selection, len(all_users)
                            )
                            users_to_delete = [all_users[i - 1] for i in indices]
                            self.print_colored(
                                Colors.GREEN,
                                f"✅ Selected {len(users_to_delete)} IAM users",
                            )
                        except ValueError as e:
                            self.print_colored(Colors.RED, f"❌ Invalid selection: {e}")
                            return

            # GROUPS Selection
            if cleanup_groups and all_groups:
                self.print_colored(Colors.YELLOW, "\n" + "=" * 80)
                self.print_colored(Colors.YELLOW, "👥 IAM GROUPS SELECTION")
                self.print_colored(Colors.YELLOW, "=" * 80)

                # Show all groups
                print(
                    f"\n{'#':<4} {'Group Name':<30} {'Account':<15} {'ID':<24} {'Users Count'}"
                )
                print("-" * 90)

                for i, group in enumerate(all_groups, 1):
                    group_name = group["group_name"]
                    account_name = group["account_info"].get("account_key", "Unknown")
                    group_id = group["group_id"]
                    user_count = len(group["users"])

                    print(
                        f"{i:<4} {group_name:<30} {account_name:<15} {group_id:<24} {user_count}"
                    )

                # Ask for group selection
                self.print_colored(Colors.YELLOW, "\nGroup Selection Options:")
                self.print_colored(Colors.WHITE, "  • Single groups: 1,3,5")
                self.print_colored(Colors.WHITE, "  • Ranges: 1-3")
                self.print_colored(Colors.WHITE, "  • Mixed: 1-3,5,7-9")
                self.print_colored(Colors.WHITE, "  • All groups: 'all' or press Enter")
                self.print_colored(Colors.WHITE, "  • Skip groups: 'skip'")

                group_selection = (
                    input("\n🔢 Select groups to delete: ").strip().lower()
                )

                if group_selection != "skip":
                    if not group_selection or group_selection == "all":
                        groups_to_delete = all_groups
                        self.print_colored(
                            Colors.GREEN,
                            f"✅ Selected all {len(all_groups)} IAM groups",
                        )
                    else:
                        try:
                            indices = self.cred_manager._parse_selection(
                                group_selection, len(all_groups)
                            )
                            groups_to_delete = [all_groups[i - 1] for i in indices]
                            self.print_colored(
                                Colors.GREEN,
                                f"✅ Selected {len(groups_to_delete)} IAM groups",
                            )
                        except ValueError as e:
                            self.print_colored(Colors.RED, f"❌ Invalid selection: {e}")
                            return

            # STEP 5: Final confirmation
            if not users_to_delete and not groups_to_delete:
                self.print_colored(
                    Colors.RED,
                    "\n❌ No IAM resources selected for deletion. Nothing to clean up.",
                )
                return

            self.print_colored(Colors.YELLOW, f"\n🎯 FINAL CONFIRMATION")
            self.print_colored(Colors.YELLOW, "=" * 80)
            self.print_colored(Colors.WHITE, f"You are about to delete:")
            self.print_colored(Colors.WHITE, f"  • {len(users_to_delete)} IAM users")
            self.print_colored(Colors.WHITE, f"  • {len(groups_to_delete)} IAM groups")
            self.print_colored(Colors.RED, f"This action CANNOT be undone!")

            confirm = input("\nType 'yes' to confirm deletion: ").strip().lower()

            if confirm != "yes":
                self.print_colored(Colors.RED, "❌ Deletion cancelled.")
                return

            # STEP 6: Execute deletion
            self.print_colored(Colors.RED, f"\n💥 STARTING IAM CLEANUP...")
            self.log_operation(
                "INFO", f"🚨 IAM CLEANUP INITIATED - {len(selected_accounts)} accounts"
            )

            start_time = time.time()

            # Organize users and groups by account for efficient processing
            users_by_account = {}
            groups_by_account = {}

            for user in users_to_delete:
                account = user["account_info"].get("account_key", "Unknown")
                if account not in users_by_account:
                    users_by_account[account] = []
                users_by_account[account].append(user)

            for group in groups_to_delete:
                account = group["account_info"].get("account_key", "Unknown")
                if account not in groups_by_account:
                    groups_by_account[account] = []
                groups_by_account[account].append(group)

            # Process each account
            for account_key, resources in account_resources.items():
                account_users = users_by_account.get(account_key, [])
                account_groups = groups_by_account.get(account_key, [])

                if account_users or account_groups:
                    self.print_colored(
                        Colors.CYAN, f"\n🏦 Processing account: {account_key}"
                    )
                    print(
                        f"  • Deleting {len(account_users)} users and {len(account_groups)} groups"
                    )

                    self.cleanup_account_iam(
                        resources["account_info"],
                        account_users,
                        account_groups,
                        exclude_root_account=exclude_root,
                    )

            end_time = time.time()
            total_time = int(end_time - start_time)

            # STEP 7: Display final results
            self.print_colored(
                Colors.YELLOW, f"\n💥" + "=" * 25 + " IAM CLEANUP COMPLETE " + "=" * 25
            )
            self.print_colored(
                Colors.WHITE, f"⏱️  Total execution time: {total_time} seconds"
            )
            self.print_colored(
                Colors.WHITE,
                f"👤 Users deleted: {len(self.cleanup_results['users_deleted'])}",
            )
            self.print_colored(
                Colors.WHITE,
                f"👥 Groups deleted: {len(self.cleanup_results['groups_deleted'])}",
            )
            self.print_colored(
                Colors.WHITE,
                f"🔑 Access keys deleted: {len(self.cleanup_results['access_keys_deleted'])}",
            )
            self.print_colored(
                Colors.WHITE,
                f"📝 Policies detached: {len(self.cleanup_results['policies_detached'])}",
            )
            self.print_colored(
                Colors.RED,
                f"❌ Failed operations: {len(self.cleanup_results['failed_operations'])}",
            )

            self.log_operation("INFO", f"IAM CLEANUP COMPLETED")
            self.log_operation("INFO", f"Execution time: {total_time} seconds")
            self.log_operation(
                "INFO", f"Users deleted: {len(self.cleanup_results['users_deleted'])}"
            )
            self.log_operation(
                "INFO", f"Groups deleted: {len(self.cleanup_results['groups_deleted'])}"
            )

            # STEP 8: Show account summary
            if (
                self.cleanup_results["users_deleted"]
                or self.cleanup_results["groups_deleted"]
            ):
                self.print_colored(Colors.YELLOW, f"\n📊 Deletion Summary by Account:")

                # Group by account
                account_summary = {}
                for user in self.cleanup_results["users_deleted"]:
                    account = user["account_info"].get("account_key", "Unknown")
                    if account not in account_summary:
                        account_summary[account] = {"users": 0, "groups": 0}
                    account_summary[account]["users"] += 1

                for group in self.cleanup_results["groups_deleted"]:
                    account = group["account_info"].get("account_key", "Unknown")
                    if account not in account_summary:
                        account_summary[account] = {"users": 0, "groups": 0}
                    account_summary[account]["groups"] += 1

                for account, summary in account_summary.items():
                    self.print_colored(Colors.PURPLE, f"   🏦 {account}:")
                    self.print_colored(
                        Colors.WHITE, f"      👤 Users: {summary['users']}"
                    )
                    self.print_colored(
                        Colors.WHITE, f"      👥 Groups: {summary['groups']}"
                    )

            # STEP 9: Show failures if any
            if self.cleanup_results["failed_operations"]:
                self.print_colored(Colors.RED, f"\n❌ Failed Operations:")
                for failure in self.cleanup_results["failed_operations"][
                    :10
                ]:  # Show first 10
                    account_key = failure["account_info"].get("account_key", "Unknown")
                    self.print_colored(
                        Colors.WHITE,
                        f"   • {failure['operation_type']} {failure['resource_name']} in {account_key}",
                    )
                    self.print_colored(Colors.WHITE, f"     Error: {failure['error']}")

                if len(self.cleanup_results["failed_operations"]) > 10:
                    remaining = len(self.cleanup_results["failed_operations"]) - 10
                    self.print_colored(
                        Colors.WHITE,
                        f"   ... and {remaining} more failures (see detailed report)",
                    )

            # Save comprehensive report
            self.print_colored(Colors.CYAN, f"\n📄 Saving IAM cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                self.print_colored(
                    Colors.GREEN, f"✅ IAM cleanup report saved to: {report_file}"
                )

            self.print_colored(
                Colors.GREEN, f"✅ Session log saved to: {self.log_filename}"
            )

            self.print_colored(Colors.RED, f"\n💥 IAM CLEANUP COMPLETE! 💥")
            self.print_colored(Colors.YELLOW, "🚨" * 30)

        except Exception as e:
            self.log_operation(
                "ERROR", f"FATAL ERROR in IAM cleanup execution: {str(e)}"
            )
            self.print_colored(Colors.RED, f"\n❌ FATAL ERROR: {e}")
            import traceback

            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraCleanupIAMManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ IAM cleanup interrupted by user")
        exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
