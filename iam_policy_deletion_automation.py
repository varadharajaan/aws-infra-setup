from datetime import datetime
from typing import Dict, List
import os
from root_iam_credential_manager import AWSCredentialManager, Colors
from iam_policy_manager import IAMPolicyManager


class IAMCleanupAutomation:
    """
    Main automation class that orchestrates IAM cleanup operations.

    This class makes decisions about which credentials to use based on the operation:
    - IAM operations (policies/roles) -> Use ROOT credentials (required for IAM management)
    - Other operations -> Could use IAM user credentials

    Author: varadharajaan
    Created: 2025-06-25
    """

    def __init__(self, config_dir: str = None):
        """Initialize the cleanup automation."""
        try:
            self.credential_manager = AWSCredentialManager(config_dir)
            self.policy_manager = IAMPolicyManager()
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Error loading configuration: {e}{Colors.END}")
            raise

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def show_main_menu(self):
        """Display the main menu and handle user choices."""
        while True:
            self._display_header()
            self._display_menu_options()

            choice = input("\nSelect operation (0-6): ").strip()

            if choice == "0":
                self.print_colored(Colors.GREEN, "\n👋 Goodbye!")
                break
            elif choice == "1":
                self._handle_single_role_cleanup()
            elif choice == "2":
                self._handle_multi_account_role_cleanup()
            elif choice == "3":
                self._handle_single_account_policy_cleanup()
            elif choice == "4":
                self._handle_multi_account_policy_cleanup()
            elif choice == "5":
                self._handle_role_deletion()
            elif choice == "6":
                self._show_help()
            else:
                self.print_colored(Colors.RED, "[ERROR] Please enter a valid option (0-6)")

    def _display_header(self):
        """Display the application header."""
        self.print_colored(Colors.YELLOW, "\n" + "=" * 80)
        self.print_colored(Colors.BOLD + Colors.CYAN, "[STAR] AWS IAM Policy & Role Cleanup Manager")
        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.WHITE,
                           f"[DATE] Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        self.print_colored(Colors.WHITE, f"👤 Current User's Login: varadharajaan")
        self.print_colored(Colors.YELLOW, "=" * 80)

    def _display_menu_options(self):
        """Display menu options."""
        self.print_colored(Colors.CYAN, "[TOOLS]  Available Operations:")
        self.print_colored(Colors.WHITE, "-" * 50)
        self.print_colored(Colors.WHITE, "1. [TARGET] Delete custom policies from specific role (single account)")
        self.print_colored(Colors.WHITE, "2. [TARGET] Delete custom policies from specific role (multiple accounts)")
        self.print_colored(Colors.WHITE, "3. [REGION] Delete ALL custom policies (single account)")
        self.print_colored(Colors.WHITE, "4. [REGION] Delete ALL custom policies (multiple accounts)")
        self.print_colored(Colors.WHITE, "5. [MASK] Delete custom IAM roles")
        self.print_colored(Colors.WHITE, "6. ❓ Help")
        self.print_colored(Colors.WHITE, "0. 🚪 Exit")

    def _handle_single_role_cleanup(self):
        """Handle cleanup of policies from a specific role in a single account."""
        self.print_colored(Colors.CYAN, "\n[TARGET] Single Account - Role Policy Cleanup")
        self.print_colored(Colors.YELLOW, "=" * 60)
        self.print_colored(Colors.WHITE, "ℹ️  This operation requires ROOT user credentials")
        self.print_colored(Colors.WHITE, "ℹ️  IAM policies are account-level resources")

        # Get role name
        role_name = input("\n[LOG] Enter role name (e.g., 'nodeinstancerole'): ").strip()
        if not role_name:
            self.print_colored(Colors.RED, "[ERROR] Role name cannot be empty!")
            return

        # Get credentials (ROOT required for IAM operations)
        root_accounts = self.credential_manager.select_root_accounts_interactive(allow_multiple=False)
        if not root_accounts:
            return

        root_account = root_accounts[0]

        # Ask for dry run
        dry_run = input("[SCAN] Perform dry run first? (Y/n): ").strip().lower() != 'n'

        # Initialize and execute
        if not self.policy_manager.initialize_with_credentials(root_account):
            self.print_colored(Colors.RED, "[ERROR] Failed to initialize with credentials")
            return

        results = self.policy_manager.delete_custom_policies_from_role(role_name, dry_run)
        self._display_role_results(results)

        # If dry run and found policies, ask to proceed
        if dry_run and results['custom_policies_found'] and not results['errors']:
            proceed = input(
                f"\n[WARN]  Found {len(results['custom_policies_found'])} custom policies. Proceed with deletion? (y/N): ").strip().lower()
            if proceed == 'y':
                self.print_colored(Colors.RED, f"[DELETE]  EXECUTING: Deleting custom policies from role: {role_name}")
                real_results = self.policy_manager.delete_custom_policies_from_role(role_name, False)
                self._display_role_results(real_results)

    def _handle_multi_account_role_cleanup(self):
        """Handle cleanup of policies from a specific role across multiple accounts."""
        self.print_colored(Colors.CYAN, "\n[TARGET] Multi-Account - Role Policy Cleanup")
        self.print_colored(Colors.YELLOW, "=" * 60)
        self.print_colored(Colors.WHITE, "ℹ️  This operation requires ROOT user credentials")
        self.print_colored(Colors.WHITE, "ℹ️  Same role will be processed across all selected accounts")

        # Get multiple root accounts
        root_accounts = self.credential_manager.select_root_accounts_interactive(allow_multiple=True)
        if not root_accounts:
            return

        # Get role name once
        role_name = input(f"\n[LOG] Enter role name for ALL {len(root_accounts)} accounts: ").strip()
        if not role_name:
            self.print_colored(Colors.RED, "[ERROR] Role name cannot be empty!")
            return

        # Ask for dry run
        dry_run = input("[SCAN] Perform dry run first? (Y/n): ").strip().lower() != 'n'

        # Process each account
        all_results = []
        for i, root_account in enumerate(root_accounts, 1):
            self.print_colored(Colors.PURPLE,
                               f"\n[LIST] Processing Account {i}/{len(root_accounts)}: {root_account['account_key']}")
            self.print_colored(Colors.WHITE, f"   Account ID: {root_account['account_id']}")

            if not self.policy_manager.initialize_with_credentials(root_account):
                self.print_colored(Colors.RED, f"[ERROR] Failed to initialize account {root_account['account_key']}")
                continue

            results = self.policy_manager.delete_custom_policies_from_role(role_name, dry_run)
            results['account_key'] = root_account['account_key']
            results['account_id'] = root_account['account_id']
            all_results.append(results)

            self._display_role_results(results)

        # Summary
        self._display_multi_account_summary(all_results, "role_policy_cleanup")

    def _handle_single_account_policy_cleanup(self):
        """Handle cleanup of all custom policies in a single account."""
        self.print_colored(Colors.CYAN, "\n[REGION] Single Account - All Policies Cleanup")
        self.print_colored(Colors.YELLOW, "=" * 60)
        self.print_colored(Colors.RED, "[WARN]  WARNING: This will delete ALL custom policies in the account!")
        self.print_colored(Colors.GREEN, "[OK] AWS managed policies will NOT be affected")
        self.print_colored(Colors.WHITE, "ℹ️  This operation requires ROOT user credentials")

        proceed = input("\n🤔 Are you sure you want to continue? (y/N): ").strip().lower()
        if proceed != 'y':
            return

        # Get credentials
        root_accounts = self.credential_manager.select_root_accounts_interactive(allow_multiple=False)
        if not root_accounts:
            return

        root_account = root_accounts[0]

        # Get exclusion list
        exclude_input = input("\n[LOG] Enter policy names to exclude (comma-separated, or press Enter for none): ").strip()
        exclude_policies = [p.strip() for p in exclude_input.split(',')] if exclude_input else []

        # Ask for dry run
        dry_run = input("[SCAN] Perform dry run first? (Y/n): ").strip().lower() != 'n'

        # Initialize and execute
        if not self.policy_manager.initialize_with_credentials(root_account):
            self.print_colored(Colors.RED, "[ERROR] Failed to initialize with credentials")
            return

        results = self.policy_manager.delete_all_custom_policies_in_account(dry_run, exclude_policies)
        self._display_account_results(results)

        # If dry run and found policies, ask to proceed
        if dry_run and results['policies_to_process'] and not results['errors']:
            proceed = input(
                f"\n[WARN]  Found {len(results['policies_to_process'])} policies to delete. Proceed? (y/N): ").strip().lower()
            if proceed == 'y':
                self.print_colored(Colors.RED, "[DELETE]  EXECUTING: Deleting ALL custom policies")
                real_results = self.policy_manager.delete_all_custom_policies_in_account(False, exclude_policies)
                self._display_account_results(real_results)

    def _handle_multi_account_policy_cleanup(self):
        """Handle cleanup of all custom policies across multiple accounts."""
        self.print_colored(Colors.CYAN, "\n[REGION] Multi-Account - All Policies Cleanup")
        self.print_colored(Colors.YELLOW, "=" * 60)
        self.print_colored(Colors.RED, "[WARN]  WARNING: This will delete ALL custom policies in ALL selected accounts!")
        self.print_colored(Colors.GREEN, "[OK] AWS managed policies will NOT be affected")
        self.print_colored(Colors.WHITE, "ℹ️  This operation requires ROOT user credentials")

        proceed = input("\n🤔 Are you sure you want to continue? (y/N): ").strip().lower()
        if proceed != 'y':
            return

        # Get multiple root accounts
        root_accounts = self.credential_manager.select_root_accounts_interactive(allow_multiple=True)
        if not root_accounts:
            return

        # Get exclusion list once for all accounts
        exclude_input = input(
            f"\n[LOG] Enter policy names to exclude from ALL {len(root_accounts)} accounts (comma-separated, or press Enter for none): ").strip()
        exclude_policies = [p.strip() for p in exclude_input.split(',')] if exclude_input else []

        # Ask for dry run
        dry_run = input("[SCAN] Perform dry run first? (Y/n): ").strip().lower() != 'n'

        # Process each account
        all_results = []
        for i, root_account in enumerate(root_accounts, 1):
            self.print_colored(Colors.PURPLE,
                               f"\n[LIST] Processing Account {i}/{len(root_accounts)}: {root_account['account_key']}")
            self.print_colored(Colors.WHITE, f"   Account ID: {root_account['account_id']}")

            if not self.policy_manager.initialize_with_credentials(root_account):
                self.print_colored(Colors.RED, f"[ERROR] Failed to initialize account {root_account['account_key']}")
                continue

            results = self.policy_manager.delete_all_custom_policies_in_account(dry_run, exclude_policies)
            results['account_key'] = root_account['account_key']
            results['account_id'] = root_account['account_id']
            all_results.append(results)

            self._display_account_results(results)

        # Summary
        self._display_multi_account_summary(all_results, "account_policy_cleanup")

    def _handle_role_deletion(self):
        """Handle deletion of custom IAM roles."""
        self.print_colored(Colors.CYAN, "\n[MASK] Custom IAM Role Deletion")
        self.print_colored(Colors.YELLOW, "=" * 60)
        self.print_colored(Colors.RED, "[WARN]  WARNING: Role deletion is irreversible!")
        self.print_colored(Colors.GREEN, "[OK] AWS service roles will be identified and protected")
        self.print_colored(Colors.WHITE, "ℹ️  This operation requires ROOT user credentials")

        proceed = input("\n🤔 Continue with role deletion? (y/N): ").strip().lower()
        if proceed != 'y':
            return

        # Ask for single or multi-account
        self.print_colored(Colors.YELLOW, "\n[LIST] Role Deletion Scope:")
        self.print_colored(Colors.WHITE, "1. Single account")
        self.print_colored(Colors.WHITE, "2. Multiple accounts")

        scope_choice = input("Select scope (1-2): ").strip()

        if scope_choice == "1":
            self._handle_single_account_role_deletion()
        elif scope_choice == "2":
            self._handle_multi_account_role_deletion()
        else:
            self.print_colored(Colors.RED, "[ERROR] Invalid choice")

    def _handle_single_account_role_deletion(self):
        """Handle role deletion in a single account."""
        # Get credentials
        root_accounts = self.credential_manager.select_root_accounts_interactive(allow_multiple=False)
        if not root_accounts:
            return

        root_account = root_accounts[0]

        # Ask for specific roles or show all
        self.print_colored(Colors.YELLOW, "\n[LIST] Role Selection Options:")
        self.print_colored(Colors.WHITE, "1. Select from list of all custom roles (recommended)")
        self.print_colored(Colors.WHITE, "2. Specify role names manually")

        selection_choice = input("Choose option (1-2): ").strip()

        role_names = None
        if selection_choice == "2":
            role_input = input("\n[LOG] Enter role names (comma-separated): ").strip()
            if role_input:
                role_names = [name.strip() for name in role_input.split(',')]
            else:
                self.print_colored(Colors.RED, "[ERROR] No role names provided!")
                return

        # Ask for dry run
        dry_run = input("[SCAN] Perform dry run first? (Y/n): ").strip().lower() != 'n'

        # Initialize and execute
        if not self.policy_manager.initialize_with_credentials(root_account):
            self.print_colored(Colors.RED, "[ERROR] Failed to initialize with credentials")
            return

        results = self.policy_manager.delete_custom_roles(role_names, dry_run)
        self._display_role_deletion_results(results)

        # If dry run and found roles, ask to proceed
        if dry_run and results['roles_to_delete'] and not results['errors']:
            proceed = input(
                f"\n[WARN]  Found {len(results['roles_to_delete'])} roles to delete. Proceed? (y/N): ").strip().lower()
            if proceed == 'y':
                self.print_colored(Colors.RED, "[DELETE]  EXECUTING: Deleting selected custom roles")
                real_results = self.policy_manager.delete_custom_roles(
                    [role['role_name'] for role in results['roles_to_delete']],
                    False
                )
                self._display_role_deletion_results(real_results)

    def _handle_multi_account_role_deletion(self):
        """Handle role deletion across multiple accounts."""
        # Get multiple root accounts
        root_accounts = self.credential_manager.select_root_accounts_interactive(allow_multiple=True)
        if not root_accounts:
            return

        # Ask for dry run
        dry_run = input("[SCAN] Perform dry run first? (Y/n): ").strip().lower() != 'n'

        # Process each account
        all_results = []
        for i, root_account in enumerate(root_accounts, 1):
            self.print_colored(Colors.PURPLE,
                               f"\n[LIST] Processing Account {i}/{len(root_accounts)}: {root_account['account_key']}")
            self.print_colored(Colors.WHITE, f"   Account ID: {root_account['account_id']}")

            if not self.policy_manager.initialize_with_credentials(root_account):
                self.print_colored(Colors.RED, f"[ERROR] Failed to initialize account {root_account['account_key']}")
                continue

            results = self.policy_manager.delete_custom_roles(None, dry_run)  # None = show all for selection
            results['account_key'] = root_account['account_key']
            results['account_id'] = root_account['account_id']
            all_results.append(results)

            self._display_role_deletion_results(results)

        # Summary
        self._display_multi_account_summary(all_results, "role_deletion")

    def _show_help(self):
        """Display help information."""
        self.print_colored(Colors.CYAN, "\n❓ Help & Information")
        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.WHITE, "[LIST] This tool helps you clean up AWS IAM custom policies and roles.")

        self.print_colored(Colors.CYAN, "\n[TARGET] Role-Specific Policy Cleanup:")
        self.print_colored(Colors.WHITE, "   • Deletes custom policies attached to a specific role")
        self.print_colored(Colors.WHITE, "   • Can be done for single or multiple accounts")
        self.print_colored(Colors.WHITE, "   • Same role name applied across all selected accounts")
        self.print_colored(Colors.WHITE, "   • Requires ROOT credentials (IAM is account-level)")

        self.print_colored(Colors.CYAN, "\n[REGION] Account-Wide Policy Cleanup:")
        self.print_colored(Colors.WHITE, "   • Deletes ALL custom policies in an account")
        self.print_colored(Colors.WHITE, "   • Can exclude specific policies")
        self.print_colored(Colors.WHITE, "   • Most destructive operation - use carefully!")
        self.print_colored(Colors.WHITE, "   • Requires ROOT credentials")

        self.print_colored(Colors.CYAN, "\n[MASK] Custom Role Deletion:")
        self.print_colored(Colors.WHITE, "   • Identifies and deletes custom IAM roles")
        self.print_colored(Colors.WHITE, "   • Protects AWS service roles automatically")
        self.print_colored(Colors.WHITE, "   • Safely detaches policies and removes instance profiles")
        self.print_colored(Colors.WHITE, "   • Requires ROOT credentials")

        self.print_colored(Colors.CYAN, "\n[SECURE] Safety Features:")
        self.print_colored(Colors.WHITE, "   • Dry run mode (default) - shows what would be deleted")
        self.print_colored(Colors.WHITE, "   • Confirmation prompts before actual deletion")
        self.print_colored(Colors.WHITE, "   • AWS managed policies/roles are never touched")
        self.print_colored(Colors.WHITE, "   • Detailed logging and error reporting")
        self.print_colored(Colors.WHITE, "   • Multi-account operation summaries")

        self.print_colored(Colors.CYAN, "\n[KEY] Credential Requirements:")
        self.print_colored(Colors.WHITE, "   • IAM operations require ROOT user credentials")
        self.print_colored(Colors.WHITE, "   • IAM policies and roles are account-level resources")
        self.print_colored(Colors.WHITE, "   • IAM user credentials cannot manage account-level IAM")

        self.print_colored(Colors.CYAN, "\n[FOLDER] Required Files:")
        self.print_colored(Colors.WHITE, "   • aws_accounts_config.json - Root account credentials")
        self.print_colored(Colors.WHITE,
                           "   • aws/iam/iam_users_credentials_*.json - IAM user credentials (for reference)")

        self.print_colored(Colors.CYAN, "\n🏗️  AWS Service Role Protection:")
        self.print_colored(Colors.WHITE, "   • Roles with /aws-service-role/ or /service-role/ paths")
        self.print_colored(Colors.WHITE, "   • Names containing: AWSServiceRole, OrganizationAccountAccessRole")
        self.print_colored(Colors.WHITE, "   • CloudFormation, CodeBuild, CodeDeploy service roles")
        self.print_colored(Colors.WHITE, "   • Lambda, RDS, EKS, EMR execution roles")

        input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.END}")

    # === DISPLAY METHODS ===

    def _display_role_results(self, results: Dict):
        """Display results from role policy operations."""
        self.print_colored(Colors.CYAN, f"\n[STATS] Results for role: {results.get('role_name', 'Unknown')}")
        self.print_colored(Colors.WHITE, "-" * 50)

        if results.get('errors'):
            self.print_colored(Colors.RED, f"[ERROR] Errors: {len(results['errors'])}")
            for error in results['errors']:
                self.print_colored(Colors.WHITE, f"   • {error}")
            return

        self.print_colored(Colors.WHITE, f"[SCAN] Custom policies found: {len(results.get('custom_policies_found', []))}")
        for policy in results.get('custom_policies_found', []):
            self.print_colored(Colors.WHITE, f"   • {policy['name']}")

        self.print_colored(Colors.WHITE,
                           f"[ACCOUNT] AWS managed policies found: {len(results.get('aws_managed_policies_found', []))}")
        for policy in results.get('aws_managed_policies_found', []):
            self.print_colored(Colors.WHITE, f"   • {policy['name']}")

        if not results.get('dry_run', True):
            self.print_colored(Colors.GREEN, f"[OK] Successfully deleted: {len(results.get('deleted_policies', []))}")
            for policy in results.get('deleted_policies', []):
                self.print_colored(Colors.WHITE, f"   • {policy}")

            if results.get('failed_deletions'):
                self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(results['failed_deletions'])}")
                for failure in results['failed_deletions']:
                    self.print_colored(Colors.WHITE, f"   • {failure['policy_name']}: {failure['reason']}")

    def _display_account_results(self, results: Dict):
        """Display results from account-wide policy operations."""
        self.print_colored(Colors.CYAN, f"\n[STATS] Account-wide Results")
        account_info = f"Account: {results.get('account_key', 'Unknown')} (ID: {results.get('account_id', 'Unknown')})"
        self.print_colored(Colors.WHITE, account_info)
        self.print_colored(Colors.WHITE, "-" * len(account_info))

        if results.get('errors'):
            self.print_colored(Colors.RED, f"[ERROR] Errors: {len(results['errors'])}")
            for error in results['errors']:
                self.print_colored(Colors.WHITE, f"   • {error}")
            return

        self.print_colored(Colors.WHITE,
                           f"[SCAN] Total custom policies found: {results.get('total_custom_policies_found', 0)}")
        self.print_colored(Colors.WHITE, f"[LOG] Policies to process: {len(results.get('policies_to_process', []))}")
        self.print_colored(Colors.WHITE, f"🚫 Excluded policies: {len(results.get('excluded_policies', []))}")

        if results.get('excluded_policies'):
            self.print_colored(Colors.WHITE, "   Excluded:")
            for policy in results['excluded_policies']:
                self.print_colored(Colors.WHITE, f"     • {policy}")

        if not results.get('dry_run', True):
            self.print_colored(Colors.GREEN, f"[OK] Successfully deleted: {len(results.get('deleted_policies', []))}")
            for policy in results.get('deleted_policies', []):
                self.print_colored(Colors.WHITE, f"   • {policy}")

            if results.get('failed_deletions'):
                self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(results['failed_deletions'])}")
                for failure in results['failed_deletions']:
                    self.print_colored(Colors.WHITE, f"   • {failure['policy_name']}: {failure['reason']}")

    def _display_role_deletion_results(self, results: Dict):
        """Display results from role deletion operations."""
        self.print_colored(Colors.CYAN, f"\n[STATS] Role Deletion Results")
        account_info = f"Account: {results.get('account_key', 'Unknown')} (ID: {results.get('account_id', 'Unknown')})"
        self.print_colored(Colors.WHITE, account_info)
        self.print_colored(Colors.WHITE, "-" * len(account_info))

        if results.get('errors'):
            self.print_colored(Colors.RED, f"[ERROR] Errors: {len(results['errors'])}")
            for error in results['errors']:
                self.print_colored(Colors.WHITE, f"   • {error}")
            if not results.get('roles_found'):
                return

        self.print_colored(Colors.WHITE, f"[SCAN] Custom roles found: {len(results.get('roles_found', []))}")
        self.print_colored(Colors.WHITE, f"[TARGET] Roles selected for deletion: {len(results.get('roles_to_delete', []))}")
        self.print_colored(Colors.WHITE,
                           f"[ACCOUNT] AWS service roles found (protected): {len(results.get('aws_service_roles_found', []))}")

        if results.get('aws_service_roles_found'):
            self.print_colored(Colors.WHITE, "   AWS Service Roles (protected):")
            for role in results['aws_service_roles_found']:
                self.print_colored(Colors.WHITE, f"     • {role['role_name']}")

        if results.get('roles_to_delete'):
            self.print_colored(Colors.WHITE, "   Roles selected for deletion:")
            for role in results['roles_to_delete']:
                create_date = role['create_date'].strftime('%Y-%m-%d') if hasattr(role['create_date'],
                                                                                  'strftime') else str(
                    role['create_date'])[:10]
                self.print_colored(Colors.WHITE, f"     • {role['role_name']} (created: {create_date})")

        if not results.get('dry_run', True):
            self.print_colored(Colors.GREEN, f"[OK] Successfully deleted: {len(results.get('deleted_roles', []))}")
            for role in results.get('deleted_roles', []):
                self.print_colored(Colors.WHITE, f"   • {role}")

            if results.get('failed_deletions'):
                self.print_colored(Colors.RED, f"[ERROR] Failed deletions: {len(results['failed_deletions'])}")
                for failure in results['failed_deletions']:
                    self.print_colored(Colors.WHITE, f"   • {failure['role_name']}: {failure['reason']}")

    def _display_multi_account_summary(self, all_results: List[Dict], operation_type: str):
        """Display summary of multi-account operations."""
        self.print_colored(Colors.YELLOW, "\n[STATS] Multi-Account Operation Summary")
        self.print_colored(Colors.YELLOW, "=" * 80)

        total_accounts = len(all_results)
        successful_accounts = len([r for r in all_results if not r.get('errors')])
        failed_accounts = total_accounts - successful_accounts

        self.print_colored(Colors.WHITE, f"📈 Total Accounts Processed: {total_accounts}")
        self.print_colored(Colors.GREEN, f"[OK] Successful Operations: {successful_accounts}")
        self.print_colored(Colors.RED, f"[ERROR] Failed Operations: {failed_accounts}")

        # Operation-specific summary
        if operation_type == "role_policy_cleanup":
            total_custom_policies = sum(
                len(r.get('custom_policies_found', [])) for r in all_results if not r.get('errors'))
            total_deleted = sum(len(r.get('deleted_policies', [])) for r in all_results if not r.get('errors'))

            self.print_colored(Colors.WHITE, f"[SCAN] Total custom policies found: {total_custom_policies}")
            if not all_results[0].get('dry_run', True):
                self.print_colored(Colors.GREEN, f"[DELETE]  Total policies deleted: {total_deleted}")

        elif operation_type == "account_policy_cleanup":
            total_policies = sum(r.get('total_custom_policies_found', 0) for r in all_results if not r.get('errors'))
            total_deleted = sum(len(r.get('deleted_policies', [])) for r in all_results if not r.get('errors'))

            self.print_colored(Colors.WHITE, f"[SCAN] Total custom policies found: {total_policies}")
            if not all_results[0].get('dry_run', True):
                self.print_colored(Colors.GREEN, f"[DELETE]  Total policies deleted: {total_deleted}")

        elif operation_type == "role_deletion":
            total_roles = sum(len(r.get('roles_found', [])) for r in all_results if not r.get('errors'))
            total_deleted = sum(len(r.get('deleted_roles', [])) for r in all_results if not r.get('errors'))

            self.print_colored(Colors.WHITE, f"[SCAN] Total custom roles found: {total_roles}")
            if not all_results[0].get('dry_run', True):
                self.print_colored(Colors.GREEN, f"[DELETE]  Total roles deleted: {total_deleted}")

        # Per-account breakdown
        self.print_colored(Colors.YELLOW, "\n[LIST] Per-Account Results:")
        for result in all_results:
            account_key = result.get('account_key', 'Unknown')
            account_id = result.get('account_id', 'Unknown')

            self.print_colored(Colors.CYAN, f"\n   [LIST] {account_key} (ID: {account_id})")

            if result.get('errors'):
                self.print_colored(Colors.RED, f"      [ERROR] Errors: {', '.join(result['errors'])}")
            else:
                if operation_type == "role_policy_cleanup":
                    custom_policies = len(result.get('custom_policies_found', []))
                    self.print_colored(Colors.WHITE, f"      [SCAN] Custom policies: {custom_policies}")
                    if not result.get('dry_run', True):
                        deleted = len(result.get('deleted_policies', []))
                        self.print_colored(Colors.GREEN, f"      [OK] Deleted: {deleted}")

                elif operation_type == "account_policy_cleanup":
                    total_found = result.get('total_custom_policies_found', 0)
                    self.print_colored(Colors.WHITE, f"      [SCAN] Total policies: {total_found}")
                    if not result.get('dry_run', True):
                        deleted = len(result.get('deleted_policies', []))
                        self.print_colored(Colors.GREEN, f"      [OK] Deleted: {deleted}")

                elif operation_type == "role_deletion":
                    roles_found = len(result.get('roles_found', []))
                    self.print_colored(Colors.WHITE, f"      [SCAN] Custom roles: {roles_found}")
                    if not result.get('dry_run', True):
                        deleted = len(result.get('deleted_roles', []))
                        self.print_colored(Colors.GREEN, f"      [OK] Deleted: {deleted}")


def main():
    """
    Main function to run the IAM Cleanup Automation.
    """
    print(f"{Colors.CYAN}[START] Starting AWS IAM Policy & Role Cleanup Manager...{Colors.END}")
    print(f"{Colors.WHITE}[DATE] Current Date and Time (UTC): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    print(f"{Colors.WHITE}👤 Current User's Login: varadharajaan{Colors.END}")

    try:
        # Initialize the cleanup automation with better error handling
        config_dir = None

        # Try to determine the best config directory
        try:
            # First try the script directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if os.access(script_dir, os.R_OK):
                config_dir = script_dir
            else:
                # Fall back to current working directory
                config_dir = os.getcwd()

            print(f"{Colors.CYAN}[FOLDER] Attempting to use config directory: {config_dir}{Colors.END}")

        except Exception as e:
            print(f"{Colors.YELLOW}[WARN]  Warning: Could not determine config directory: {e}{Colors.END}")
            config_dir = None

        # Initialize the cleanup automation
        automation = IAMCleanupAutomation(config_dir)

        # Show main menu
        automation.show_main_menu()

    except PermissionError as e:
        print(f"\n{Colors.RED}[ERROR] Permission Error: {e}{Colors.END}")
        print(f"{Colors.WHITE}[TIP] Solutions:{Colors.END}")
        print(f"{Colors.WHITE}   • Run from a directory you have read permissions on{Colors.END}")
        print(f"{Colors.WHITE}   • Move the config files to your home directory{Colors.END}")
        print(f"{Colors.WHITE}   • Run with appropriate permissions{Colors.END}")

    except FileNotFoundError as e:
        print(f"\n{Colors.RED}[ERROR] File Not Found: {e}{Colors.END}")
        print(f"{Colors.WHITE}[TIP] Make sure these files exist in the config directory:{Colors.END}")
        print(f"{Colors.WHITE}   • aws_accounts_config.json{Colors.END}")
        print(f"{Colors.WHITE}   • aws/iam/iam_users_credentials_*.json{Colors.END}")

    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}[WARN]  Operation cancelled by user{Colors.END}")

    except Exception as e:
        print(f"\n{Colors.RED}[ERROR] Unexpected error: {e}{Colors.END}")
        print(f"{Colors.WHITE}[TIP] Please check your configuration files and try again{Colors.END}")
        print(f"{Colors.WHITE}   Error type: {type(e).__name__}{Colors.END}")


if __name__ == "__main__":
    main()