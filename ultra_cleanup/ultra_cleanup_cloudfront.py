#!/usr/bin/env python3
"""
Ultra CloudFront Cleanup Manager
Comprehensive AWS CloudFront cleanup across multiple AWS accounts
- Deletes CloudFront Distributions (disables first, then deletes)
- Deletes Origin Access Identities (OAI)
- Deletes Origin Access Controls (OAC)
- Deletes Cache Policies
- Deletes Origin Request Policies
- Deletes Response Headers Policies
- Deletes Field-Level Encryption Configs
"""

import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import json
import time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager


class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    END = '\033[0m'


class UltraCleanupCloudFrontManager:
    """Manager for comprehensive CloudFront cleanup operations"""

    def __init__(self):
        """Initialize the CloudFront cleanup manager"""
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
        self.execution_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Create directories for logs and reports
        self.base_dir = os.path.join(os.getcwd(), 'aws', 'cloudfront')
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.reports_dir = os.path.join(self.base_dir, 'reports')
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Setup logging
        self.log_file = os.path.join(
            self.logs_dir, 
            f'cloudfront_cleanup_log_{self.execution_timestamp}.log'
        )
        
        # Cleanup results tracking
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_distributions': [],
            'deleted_oais': [],
            'deleted_oacs': [],
            'deleted_cache_policies': [],
            'deleted_origin_request_policies': [],
            'deleted_response_headers_policies': [],
            'deleted_field_level_encryption_configs': [],
            'failed_deletions': [],
            'errors': []
        }

    def print_colored(self, color, message):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def log_action(self, message, level="INFO"):
        """Log action to file"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {level:8} | {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)

    def wait_for_distribution_deployed(self, cf_client, distribution_id, timeout=1200):
        """Wait for a CloudFront distribution to be fully deployed"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = cf_client.get_distribution(Id=distribution_id)
                status = response['Distribution']['Status']
                
                if status == 'Deployed':
                    return True
                
                self.print_colored(Colors.YELLOW, f"   [WAIT] Distribution status: {status}, waiting...")
                time.sleep(30)
                
            except ClientError as e:
                if 'NoSuchDistribution' in str(e):
                    return True
                time.sleep(10)
        
        return False

    def disable_and_delete_distribution(self, cf_client, distribution_id, account_key):
        """Disable and delete a CloudFront distribution"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Processing distribution: {distribution_id}")
            
            # Get current distribution config
            response = cf_client.get_distribution_config(Id=distribution_id)
            config = response['DistributionConfig']
            etag = response['ETag']
            
            # Check if already disabled
            if not config.get('Enabled', True):
                self.print_colored(Colors.YELLOW, f"   [SKIP] Distribution already disabled")
            else:
                # Disable the distribution
                self.print_colored(Colors.CYAN, f"   [DISABLE] Disabling distribution...")
                config['Enabled'] = False
                
                cf_client.update_distribution(
                    Id=distribution_id,
                    DistributionConfig=config,
                    IfMatch=etag
                )
                
                self.print_colored(Colors.YELLOW, f"   [WAIT] Waiting for distribution to deploy...")
                if not self.wait_for_distribution_deployed(cf_client, distribution_id):
                    self.print_colored(Colors.RED, f"   [ERROR] Timeout waiting for distribution deployment")
                    return False
            
            # Get updated config with new ETag
            response = cf_client.get_distribution_config(Id=distribution_id)
            etag = response['ETag']
            
            # Delete the distribution
            self.print_colored(Colors.CYAN, f"   [DELETE] Deleting distribution...")
            cf_client.delete_distribution(Id=distribution_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted distribution: {distribution_id}")
            self.log_action(f"Deleted distribution: {distribution_id}")
            
            self.cleanup_results['deleted_distributions'].append({
                'id': distribution_id,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete distribution {distribution_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'Distribution',
                'id': distribution_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_origin_access_identity(self, cf_client, oai_id, account_key):
        """Delete a CloudFront Origin Access Identity"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting OAI: {oai_id}")
            
            # Get current OAI config
            response = cf_client.get_cloud_front_origin_access_identity(Id=oai_id)
            etag = response['ETag']
            
            cf_client.delete_cloud_front_origin_access_identity(Id=oai_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted OAI: {oai_id}")
            self.log_action(f"Deleted OAI: {oai_id}")
            
            self.cleanup_results['deleted_oais'].append({
                'id': oai_id,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete OAI {oai_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'OAI',
                'id': oai_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_origin_access_control(self, cf_client, oac_id, account_key):
        """Delete a CloudFront Origin Access Control"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting OAC: {oac_id}")
            
            # Get current OAC config
            response = cf_client.get_origin_access_control(Id=oac_id)
            etag = response['ETag']
            
            cf_client.delete_origin_access_control(Id=oac_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted OAC: {oac_id}")
            self.log_action(f"Deleted OAC: {oac_id}")
            
            self.cleanup_results['deleted_oacs'].append({
                'id': oac_id,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete OAC {oac_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'OAC',
                'id': oac_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_cache_policy(self, cf_client, policy_id, policy_name, account_key):
        """Delete a CloudFront cache policy"""
        try:
            # Skip AWS managed policies
            if policy_name and policy_name.startswith('Managed-'):
                self.print_colored(Colors.YELLOW, f"[SKIP] Skipping managed cache policy: {policy_name}")
                return True
            
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting cache policy: {policy_id}")
            
            # Get current policy config
            response = cf_client.get_cache_policy(Id=policy_id)
            etag = response['ETag']
            
            cf_client.delete_cache_policy(Id=policy_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted cache policy: {policy_id}")
            self.log_action(f"Deleted cache policy: {policy_id}")
            
            self.cleanup_results['deleted_cache_policies'].append({
                'id': policy_id,
                'name': policy_name,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            if 'IllegalDelete' in str(e) or 'CachePolicyInUse' in str(e):
                self.print_colored(Colors.YELLOW, f"[SKIP] Cache policy in use or managed: {policy_id}")
                return True
            
            error_msg = f"Failed to delete cache policy {policy_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'CachePolicy',
                'id': policy_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_origin_request_policy(self, cf_client, policy_id, policy_name, account_key):
        """Delete a CloudFront origin request policy"""
        try:
            # Skip AWS managed policies
            if policy_name and policy_name.startswith('Managed-'):
                self.print_colored(Colors.YELLOW, f"[SKIP] Skipping managed origin request policy: {policy_name}")
                return True
            
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting origin request policy: {policy_id}")
            
            # Get current policy config
            response = cf_client.get_origin_request_policy(Id=policy_id)
            etag = response['ETag']
            
            cf_client.delete_origin_request_policy(Id=policy_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted origin request policy: {policy_id}")
            self.log_action(f"Deleted origin request policy: {policy_id}")
            
            self.cleanup_results['deleted_origin_request_policies'].append({
                'id': policy_id,
                'name': policy_name,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            if 'IllegalDelete' in str(e) or 'OriginRequestPolicyInUse' in str(e):
                self.print_colored(Colors.YELLOW, f"[SKIP] Origin request policy in use or managed: {policy_id}")
                return True
            
            error_msg = f"Failed to delete origin request policy {policy_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'OriginRequestPolicy',
                'id': policy_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_response_headers_policy(self, cf_client, policy_id, policy_name, account_key):
        """Delete a CloudFront response headers policy"""
        try:
            # Skip AWS managed policies
            if policy_name and policy_name.startswith('Managed-'):
                self.print_colored(Colors.YELLOW, f"[SKIP] Skipping managed response headers policy: {policy_name}")
                return True
            
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting response headers policy: {policy_id}")
            
            # Get current policy config
            response = cf_client.get_response_headers_policy(Id=policy_id)
            etag = response['ETag']
            
            cf_client.delete_response_headers_policy(Id=policy_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted response headers policy: {policy_id}")
            self.log_action(f"Deleted response headers policy: {policy_id}")
            
            self.cleanup_results['deleted_response_headers_policies'].append({
                'id': policy_id,
                'name': policy_name,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            if 'IllegalDelete' in str(e) or 'ResponseHeadersPolicyInUse' in str(e):
                self.print_colored(Colors.YELLOW, f"[SKIP] Response headers policy in use or managed: {policy_id}")
                return True
            
            error_msg = f"Failed to delete response headers policy {policy_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'ResponseHeadersPolicy',
                'id': policy_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def delete_field_level_encryption_config(self, cf_client, config_id, account_key):
        """Delete a CloudFront field-level encryption config"""
        try:
            self.print_colored(Colors.CYAN, f"[DELETE] Deleting field-level encryption config: {config_id}")
            
            # Get current config
            response = cf_client.get_field_level_encryption_config(Id=config_id)
            etag = response['ETag']
            
            cf_client.delete_field_level_encryption_config(Id=config_id, IfMatch=etag)
            
            self.print_colored(Colors.GREEN, f"[OK] Deleted field-level encryption config: {config_id}")
            self.log_action(f"Deleted field-level encryption config: {config_id}")
            
            self.cleanup_results['deleted_field_level_encryption_configs'].append({
                'id': config_id,
                'account_key': account_key
            })
            return True
            
        except ClientError as e:
            error_msg = f"Failed to delete field-level encryption config {config_id}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['failed_deletions'].append({
                'type': 'FieldLevelEncryptionConfig',
                'id': config_id,
                'error': str(e),
                'account_key': account_key
            })
            return False

    def cleanup_account_cloudfront(self, account_name, credentials):
        """Cleanup all CloudFront resources in an account"""
        try:
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, f"[START] Processing Account: {account_name}")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            
            self.cleanup_results['accounts_processed'].append(account_name)
            
            # CloudFront is a global service (no region needed)
            cf_client = boto3.client(
                'cloudfront',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key']
            )
            
            # Delete Distributions
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning CloudFront distributions...")
                distributions_response = cf_client.list_distributions()
                
                if 'DistributionList' in distributions_response and 'Items' in distributions_response['DistributionList']:
                    distributions = distributions_response['DistributionList']['Items']
                    
                    if distributions:
                        self.print_colored(Colors.CYAN, f"[DIST] Found {len(distributions)} distributions")
                        for dist in distributions:
                            self.disable_and_delete_distribution(cf_client, dist['Id'], account_name)
                            time.sleep(2)
            except ClientError as e:
                self.log_action(f"Error listing distributions: {e}", "ERROR")
            
            # Delete Origin Access Identities
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning Origin Access Identities...")
                oais_response = cf_client.list_cloud_front_origin_access_identities()
                
                if 'CloudFrontOriginAccessIdentityList' in oais_response and 'Items' in oais_response['CloudFrontOriginAccessIdentityList']:
                    oais = oais_response['CloudFrontOriginAccessIdentityList']['Items']
                    
                    if oais:
                        self.print_colored(Colors.CYAN, f"[OAI] Found {len(oais)} OAIs")
                        for oai in oais:
                            self.delete_origin_access_identity(cf_client, oai['Id'], account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing OAIs: {e}", "ERROR")
            
            # Delete Origin Access Controls
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning Origin Access Controls...")
                oacs_response = cf_client.list_origin_access_controls()
                
                if 'OriginAccessControlList' in oacs_response and 'Items' in oacs_response['OriginAccessControlList']:
                    oacs = oacs_response['OriginAccessControlList']['Items']
                    
                    if oacs:
                        self.print_colored(Colors.CYAN, f"[OAC] Found {len(oacs)} OACs")
                        for oac in oacs:
                            self.delete_origin_access_control(cf_client, oac['Id'], account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing OACs: {e}", "ERROR")
            
            # Delete Cache Policies
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning Cache Policies...")
                policies_response = cf_client.list_cache_policies(Type='custom')
                
                if 'CachePolicyList' in policies_response and 'Items' in policies_response['CachePolicyList']:
                    policies = policies_response['CachePolicyList']['Items']
                    
                    if policies:
                        self.print_colored(Colors.CYAN, f"[POLICY] Found {len(policies)} custom cache policies")
                        for policy in policies:
                            policy_name = policy['CachePolicy'].get('CachePolicyConfig', {}).get('Name', '')
                            self.delete_cache_policy(cf_client, policy['CachePolicy']['Id'], policy_name, account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing cache policies: {e}", "ERROR")
            
            # Delete Origin Request Policies
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning Origin Request Policies...")
                policies_response = cf_client.list_origin_request_policies(Type='custom')
                
                if 'OriginRequestPolicyList' in policies_response and 'Items' in policies_response['OriginRequestPolicyList']:
                    policies = policies_response['OriginRequestPolicyList']['Items']
                    
                    if policies:
                        self.print_colored(Colors.CYAN, f"[POLICY] Found {len(policies)} custom origin request policies")
                        for policy in policies:
                            policy_name = policy['OriginRequestPolicy'].get('OriginRequestPolicyConfig', {}).get('Name', '')
                            self.delete_origin_request_policy(cf_client, policy['OriginRequestPolicy']['Id'], policy_name, account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing origin request policies: {e}", "ERROR")
            
            # Delete Response Headers Policies
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning Response Headers Policies...")
                policies_response = cf_client.list_response_headers_policies(Type='custom')
                
                if 'ResponseHeadersPolicyList' in policies_response and 'Items' in policies_response['ResponseHeadersPolicyList']:
                    policies = policies_response['ResponseHeadersPolicyList']['Items']
                    
                    if policies:
                        self.print_colored(Colors.CYAN, f"[POLICY] Found {len(policies)} custom response headers policies")
                        for policy in policies:
                            policy_name = policy['ResponseHeadersPolicy'].get('ResponseHeadersPolicyConfig', {}).get('Name', '')
                            self.delete_response_headers_policy(cf_client, policy['ResponseHeadersPolicy']['Id'], policy_name, account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing response headers policies: {e}", "ERROR")
            
            # Delete Field-Level Encryption Configs
            try:
                self.print_colored(Colors.YELLOW, "\n[SCAN] Scanning Field-Level Encryption Configs...")
                configs_response = cf_client.list_field_level_encryption_configs()
                
                if 'FieldLevelEncryptionList' in configs_response and 'Items' in configs_response['FieldLevelEncryptionList']:
                    configs = configs_response['FieldLevelEncryptionList']['Items']
                    
                    if configs:
                        self.print_colored(Colors.CYAN, f"[ENCRYPT] Found {len(configs)} field-level encryption configs")
                        for config in configs:
                            self.delete_field_level_encryption_config(cf_client, config['Id'], account_name)
                            time.sleep(0.5)
            except ClientError as e:
                self.log_action(f"Error listing field-level encryption configs: {e}", "ERROR")
            
            self.print_colored(Colors.GREEN, f"\n[OK] Account {account_name} cleanup completed!")
            
        except Exception as e:
            error_msg = f"Error processing account {account_name}: {e}"
            self.print_colored(Colors.RED, f"[ERROR] {error_msg}")
            self.log_action(error_msg, "ERROR")
            self.cleanup_results['errors'].append(error_msg)

    def generate_summary_report(self):
        """Generate a summary report of the cleanup operation"""
        try:
            report_filename = f"cloudfront_cleanup_summary_{self.execution_timestamp}.json"
            report_path = os.path.join(self.reports_dir, report_filename)

            summary = {
                'execution_timestamp': self.execution_timestamp,
                'execution_time': self.current_time,
                'user': self.current_user,
                'accounts_processed': self.cleanup_results['accounts_processed'],
                'summary': {
                    'total_distributions_deleted': len(self.cleanup_results['deleted_distributions']),
                    'total_oais_deleted': len(self.cleanup_results['deleted_oais']),
                    'total_oacs_deleted': len(self.cleanup_results['deleted_oacs']),
                    'total_cache_policies_deleted': len(self.cleanup_results['deleted_cache_policies']),
                    'total_origin_request_policies_deleted': len(self.cleanup_results['deleted_origin_request_policies']),
                    'total_response_headers_policies_deleted': len(self.cleanup_results['deleted_response_headers_policies']),
                    'total_field_level_encryption_configs_deleted': len(self.cleanup_results['deleted_field_level_encryption_configs']),
                    'total_failed_deletions': len(self.cleanup_results['failed_deletions']),
                    'total_errors': len(self.cleanup_results['errors'])
                },
                'details': self.cleanup_results
            }

            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=2)

            self.print_colored(Colors.GREEN, f"\n[STATS] Summary report saved: {report_path}")

            # Print summary to console
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] CLEANUP SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")
            self.print_colored(Colors.GREEN, f"[OK] Distributions Deleted: {summary['summary']['total_distributions_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Origin Access Identities Deleted: {summary['summary']['total_oais_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Origin Access Controls Deleted: {summary['summary']['total_oacs_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Cache Policies Deleted: {summary['summary']['total_cache_policies_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Origin Request Policies Deleted: {summary['summary']['total_origin_request_policies_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Response Headers Policies Deleted: {summary['summary']['total_response_headers_policies_deleted']}")
            self.print_colored(Colors.GREEN, f"[OK] Field-Level Encryption Configs Deleted: {summary['summary']['total_field_level_encryption_configs_deleted']}")

            if summary['summary']['total_failed_deletions'] > 0:
                self.print_colored(Colors.YELLOW, f"[WARN] Failed Deletions: {summary['summary']['total_failed_deletions']}")

            if summary['summary']['total_errors'] > 0:
                self.print_colored(Colors.RED, f"[ERROR] Errors: {summary['summary']['total_errors']}")

            # Display Account Summary
            self.print_colored(Colors.BLUE, f"\n{'='*100}")
            self.print_colored(Colors.BLUE, "[STATS] ACCOUNT-WISE SUMMARY")
            self.print_colored(Colors.BLUE, f"{'='*100}")

            account_summary = {}

            # Aggregate all deleted resources
            for item_list, key_name in [
                (self.cleanup_results['deleted_distributions'], 'distributions'),
                (self.cleanup_results['deleted_oais'], 'oais'),
                (self.cleanup_results['deleted_oacs'], 'oacs'),
                (self.cleanup_results['deleted_cache_policies'], 'cache_policies'),
                (self.cleanup_results['deleted_origin_request_policies'], 'origin_request_policies'),
                (self.cleanup_results['deleted_response_headers_policies'], 'response_headers_policies'),
                (self.cleanup_results['deleted_field_level_encryption_configs'], 'field_level_encryption_configs')
            ]:
                for item in item_list:
                    account = item.get('account_key', 'Unknown')
                    if account not in account_summary:
                        account_summary[account] = {
                            'distributions': 0, 'oais': 0, 'oacs': 0,
                            'cache_policies': 0, 'origin_request_policies': 0,
                            'response_headers_policies': 0, 'field_level_encryption_configs': 0
                        }
                    account_summary[account][key_name] += 1

            for account, stats in account_summary.items():
                self.print_colored(Colors.CYAN, f"\n[LIST] Account: {account}")
                self.print_colored(Colors.GREEN, f"  [OK] Distributions: {stats['distributions']}")
                self.print_colored(Colors.GREEN, f"  [OK] Origin Access Identities: {stats['oais']}")
                self.print_colored(Colors.GREEN, f"  [OK] Origin Access Controls: {stats['oacs']}")
                self.print_colored(Colors.GREEN, f"  [OK] Cache Policies: {stats['cache_policies']}")
                self.print_colored(Colors.GREEN, f"  [OK] Origin Request Policies: {stats['origin_request_policies']}")
                self.print_colored(Colors.GREEN, f"  [OK] Response Headers Policies: {stats['response_headers_policies']}")
                self.print_colored(Colors.GREEN, f"  [OK] Field-Level Encryption Configs: {stats['field_level_encryption_configs']}")

        except Exception as e:
            self.print_colored(Colors.RED, f"[ERROR] Failed to generate summary report: {e}")

    def interactive_cleanup(self):
        """Interactive mode for CloudFront cleanup"""
        try:
            self.print_colored(Colors.BLUE, "\n" + "="*100)
            self.print_colored(Colors.BLUE, "[START] ULTRA CLOUDFRONT CLEANUP MANAGER")
            self.print_colored(Colors.BLUE, "="*100)

            config = self.cred_manager.load_root_accounts_config()
            if not config or 'accounts' not in config:
                self.print_colored(Colors.RED, "[ERROR] No accounts configuration found!")
                return

            accounts = config['accounts']
            account_list = list(accounts.keys())

            self.print_colored(Colors.CYAN, "[KEY] Select Root AWS Accounts for CloudFront Cleanup:")
            print(f"{Colors.CYAN}[BOOK] Loading root accounts config...{Colors.END}")
            self.print_colored(Colors.GREEN, f"[OK] Loaded {len(accounts)} root accounts")
            
            self.print_colored(Colors.YELLOW, "\n[KEY] Available Root AWS Accounts:")
            print("=" * 100)
            
            for idx, account_name in enumerate(account_list, 1):
                account_data = accounts[account_name]
                account_id = account_data.get('account_id', 'Unknown')
                email = account_data.get('email', 'N/A')
                user_count = len(account_data.get('users', []))
                
                print(f"   {idx}. {account_name} (ID: {account_id})")
                print(f"      Email: {email}, Users: {user_count}")
            
            print("=" * 100)
            self.print_colored(Colors.BLUE, "[TIP] Selection options:")
            print("   - Single: 1")
            print("   - Multiple: 1,3,5")
            print("   - All: all")
            print("=" * 100)

            selection = input(f"Select accounts (1-{len(account_list)}, comma-separated, or 'all') or 'q' to quit: ").strip()

            if selection.lower() == 'q':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            selected_accounts = []
            if selection.lower() == 'all':
                selected_accounts = account_list
            else:
                try:
                    indices = [int(x.strip()) for x in selection.split(',')]
                    selected_accounts = [account_list[i-1] for i in indices if 0 < i <= len(account_list)]
                except (ValueError, IndexError):
                    self.print_colored(Colors.RED, "[ERROR] Invalid selection!")
                    return

            if not selected_accounts:
                self.print_colored(Colors.RED, "[ERROR] No accounts selected!")
                return

            self.print_colored(Colors.RED, "\n[WARN] WARNING: This will DELETE all CloudFront resources!")
            self.print_colored(Colors.YELLOW, "[WARN] Note: Distributions will be disabled first, then deleted (may take time)")
            confirm = input(f"\nType 'DELETE' to confirm: ").strip()
            if confirm != 'DELETE':
                self.print_colored(Colors.YELLOW, "[EXIT] Cleanup cancelled!")
                return

            for account_name in selected_accounts:
                account_data = accounts[account_name]
                credentials = {
                    'access_key': account_data['access_key'],
                    'secret_key': account_data['secret_key']
                }

                self.cleanup_account_cloudfront(account_name, credentials)
                time.sleep(2)

            self.generate_summary_report()

            self.print_colored(Colors.GREEN, f"\n[OK] CloudFront cleanup completed!")
            self.print_colored(Colors.CYAN, f"[FILE] Log file: {self.log_file}")

        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n[WARN] Cleanup interrupted by user!")
        except Exception as e:
            self.print_colored(Colors.RED, f"\n[ERROR] Error during cleanup: {e}")


def main():
    """Main entry point"""
    try:
        manager = UltraCleanupCloudFrontManager()
        manager.interactive_cleanup()
    except KeyboardInterrupt:
        print("\n\n[WARN] Operation cancelled by user!")
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")


if __name__ == "__main__":
    main()
