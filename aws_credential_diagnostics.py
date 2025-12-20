#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime

class AWSCredentialDiagnostics:
    def __init__(self, config_file='aws_accounts_config.json'):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    def load_configuration(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            print(f"[OK] Configuration loaded from: {self.config_file}")
            
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
                    print(f"[WARN]  Skipping incomplete account: {account_name}")
            
            self.config_data['accounts'] = valid_accounts
            
            print(f"[STATS] Valid accounts found: {len(valid_accounts)}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Error loading configuration: {e}")
            return False

    def test_default_aws_credentials(self):
        """Test default AWS credentials (AWS CLI profile)"""
        print(f"\n{'='*60}")
        print("[SCAN] TESTING DEFAULT AWS CREDENTIALS")
        print(f"{'='*60}")
        
        try:
            # Test default session
            session = boto3.Session()
            sts_client = session.client('sts')
            identity = sts_client.get_caller_identity()
            
            print(f"[OK] Default AWS credentials work!")
            print(f"   👤 User: {identity.get('Arn', 'Unknown')}")
            print(f"   [BANK] Account: {identity.get('Account', 'Unknown')}")
            print(f"   [LIST] User ID: {identity.get('UserId', 'Unknown')}")
            
            # Test EC2 access
            ec2_client = session.client('ec2', region_name='us-east-1')
            regions = ec2_client.describe_regions()
            print(f"   [REGION] EC2 access: [OK] (Found {len(regions['Regions'])} regions)")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Default AWS credentials failed: {e}")
            return False

    def test_account_credentials(self, account_name, account_data, test_regions=['us-east-1', 'us-west-1']):
        """Test specific account credentials"""
        print(f"\n{'='*60}")
        print(f"[SCAN] TESTING ACCOUNT: {account_name}")
        print(f"{'='*60}")
        
        access_key = account_data['access_key']
        secret_key = account_data['secret_key']
        account_id = account_data['account_id']
        
        print(f"   [FILE] Config Account ID: {account_id}")
        print(f"   [KEY] Access Key: {access_key[:10]}...{access_key[-4:]}")
        print(f"   [LOCKED] Secret Key: {secret_key[:10]}...****")
        
        results = {
            'account_name': account_name,
            'config_account_id': account_id,
            'credentials_valid': False,
            'identity_info': {},
            'regions_tested': {},
            'errors': []
        }
        
        try:
            # Test STS (identity)
            print(f"\n   [SCAN] Testing STS (Identity)...")
            sts_client = boto3.client(
                'sts',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            
            identity = sts_client.get_caller_identity()
            actual_account_id = identity.get('Account')
            user_arn = identity.get('Arn', 'Unknown')
            user_id = identity.get('UserId', 'Unknown')
            
            print(f"   [OK] STS Identity successful!")
            print(f"      👤 User ARN: {user_arn}")
            print(f"      [BANK] Actual Account: {actual_account_id}")
            print(f"      [LIST] User ID: {user_id}")
            
            results['credentials_valid'] = True
            results['identity_info'] = {
                'arn': user_arn,
                'account': actual_account_id,
                'user_id': user_id
            }
            
            # Check if account IDs match
            if actual_account_id != account_id:
                error_msg = f"Account ID mismatch! Config: {account_id}, Actual: {actual_account_id}"
                print(f"   [WARN]  {error_msg}")
                results['errors'].append(error_msg)
            else:
                print(f"   [OK] Account ID matches config")
            
            # Test EC2 in different regions
            print(f"\n   [SCAN] Testing EC2 access in regions...")
            for region in test_regions:
                try:
                    print(f"      Testing {region}...")
                    ec2_client = boto3.client(
                        'ec2',
                        aws_access_key_id=access_key,
                        aws_secret_access_key=secret_key,
                        region_name=region
                    )
                    
                    # Test describe_regions (same as cleanup script)
                    regions_response = ec2_client.describe_regions(RegionNames=[region])
                    print(f"      [OK] {region}: describe_regions successful")
                    
                    # Test describe_instances
                    instances_response = ec2_client.describe_instances()
                    instance_count = sum(len(r['Instances']) for r in instances_response['Reservations'])
                    print(f"      [OK] {region}: Found {instance_count} instances")
                    
                    # Test describe_security_groups
                    sgs_response = ec2_client.describe_security_groups()
                    sg_count = len(sgs_response['SecurityGroups'])
                    print(f"      [OK] {region}: Found {sg_count} security groups")
                    
                    results['regions_tested'][region] = {
                        'success': True,
                        'instances': instance_count,
                        'security_groups': sg_count
                    }
                    
                except Exception as e:
                    error_msg = f"EC2 access failed in {region}: {e}"
                    print(f"      [ERROR] {region}: {e}")
                    results['errors'].append(error_msg)
                    results['regions_tested'][region] = {
                        'success': False,
                        'error': str(e)
                    }
            
        except Exception as e:
            error_msg = f"STS/Identity test failed: {e}"
            print(f"   [ERROR] {error_msg}")
            results['errors'].append(error_msg)
        
        return results

    def compare_credential_sources(self):
        """Compare different credential sources"""
        print(f"\n{'='*60}")
        print("[SCAN] COMPARING CREDENTIAL SOURCES")
        print(f"{'='*60}")
        
        # Check environment variables
        env_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE']
        print(f"\n[PIN] Environment Variables:")
        for var in env_vars:
            value = os.environ.get(var)
            if value:
                display_value = f"{value[:10]}...{value[-4:]}" if len(value) > 14 else value
                print(f"   {var}: {display_value}")
            else:
                print(f"   {var}: Not set")
        
        # Check AWS config files
        print(f"\n[PIN] AWS Configuration Files:")
        aws_config_dir = os.path.expanduser('~/.aws')
        for file in ['credentials', 'config']:
            file_path = os.path.join(aws_config_dir, file)
            if os.path.exists(file_path):
                print(f"   [OK] {file_path} exists")
            else:
                print(f"   [ERROR] {file_path} not found")

    def run_diagnostics(self):
        """Run comprehensive diagnostics"""
        print("[ALERT]" * 30)
        print("[SCAN] AWS CREDENTIAL DIAGNOSTICS")
        print("[ALERT]" * 30)
        print(f"[DATE] Execution Time: {self.current_time} UTC")
        print(f"[FILE] Config File: {self.config_file}")
        
        # Load configuration
        if not self.load_configuration():
            sys.exit(1)
        
        # Compare credential sources
        self.compare_credential_sources()
        
        # Test default credentials
        default_works = self.test_default_aws_credentials()
        
        # Test each account from JSON
        all_results = []
        accounts = self.config_data['accounts']
        
        for account_name, account_data in accounts.items():
            result = self.test_account_credentials(account_name, account_data)
            all_results.append(result)
        
        # Summary
        print(f"\n{'='*60}")
        print("[STATS] DIAGNOSTIC SUMMARY")
        print(f"{'='*60}")
        
        print(f"[CONFIG] Default AWS credentials: {'[OK] Working' if default_works else '[ERROR] Failed'}")
        
        for result in all_results:
            status = "[OK] Working" if result['credentials_valid'] and not result['errors'] else "[ERROR] Issues"
            print(f"[BANK] {result['account_name']}: {status}")
            
            if result['errors']:
                for error in result['errors']:
                    print(f"   [WARN]  {error}")
        
        # Recommendations
        print(f"\n{'='*60}")
        print("[TIP] RECOMMENDATIONS")
        print(f"{'='*60}")
        
        failed_accounts = [r for r in all_results if not r['credentials_valid'] or r['errors']]
        
        if failed_accounts:
            print("[CONFIG] Issues found with JSON config accounts:")
            for result in failed_accounts:
                print(f"\n[BANK] {result['account_name']}:")
                if not result['credentials_valid']:
                    print("   • Credentials are invalid or expired")
                    print("   • Check if access key and secret key are correct")
                    print("   • Verify the account is active")
                
                for error in result['errors']:
                    if "Account ID mismatch" in error:
                        print("   • Account ID in config doesn't match actual account")
                    elif "AuthFailure" in error:
                        print("   • Authentication failed - check credentials")
                    elif "AccessDenied" in error:
                        print("   • Permission denied - check IAM permissions")
        
        if default_works and failed_accounts:
            print(f"\n[TIP] Your default AWS credentials work but JSON config has issues.")
            print(f"   Consider updating your JSON config with working credentials.")
        
        print(f"\n[TARGET] Next steps:")
        print(f"   1. Fix any credential issues identified above")
        print(f"   2. Ensure all accounts have necessary EC2 permissions")
        print(f"   3. Re-run the cleanup script")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AWS Credential Diagnostics')
    parser.add_argument('--config', '-c', default='aws_accounts_config.json',
                       help='Path to AWS accounts configuration file')
    args = parser.parse_args()
    
    try:
        diagnostics = AWSCredentialDiagnostics(args.config)
        diagnostics.run_diagnostics()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Diagnostics interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()