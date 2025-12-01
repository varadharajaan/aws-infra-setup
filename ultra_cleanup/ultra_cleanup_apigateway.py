#!/usr/bin/env python3
"""Ultra API Gateway Cleanup Manager - Deletes REST APIs, HTTP APIs, WebSocket APIs"""

import os, json, boto3, time    
from datetime import datetime
from typing import List 
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors

class UltraCleanupAPIGatewayManager:
    def __init__(self, config_dir: str = None):
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.apigw_dir = os.path.join(self.config_dir, "aws", "apigateway")
        self.reports_dir = os.path.join(self.apigw_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_rest_apis': [],
            'deleted_http_apis': [],
            'deleted_websocket_apis': [],
            'failed_deletions': []
        }

    def print_colored(self, color: str, message: str):
        print(f"{color}{message}{Colors.END}")

    def _get_regions(self):
        try:
            config = self.cred_manager.load_root_accounts_config()
            return config.get('user_settings', {}).get('user_regions', ['us-east-1'])
        except:
            return ['us-east-1', 'us-west-2']

    def delete_rest_apis(self, client, region, account):
        deleted = 0
        for api in client.get_rest_apis().get('items', []):
            try:
                client.delete_rest_api(restApiId=api['id'])
                deleted += 1
                self.cleanup_results['deleted_rest_apis'].append({
                    'api_id': api['id'], 'name': api.get('name'), 'region': region, 'account': account
                })
            except Exception as e:
                self.cleanup_results['failed_deletions'].append({'api_id': api['id'], 'error': str(e)})
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} REST APIs")

    def delete_http_apis(self, client, region, account):
        deleted = 0
        for api in client.get_apis().get('Items', []):
            try:
                client.delete_api(ApiId=api['ApiId'])
                deleted += 1
                self.cleanup_results['deleted_http_apis'].append({
                    'api_id': api['ApiId'], 'name': api.get('Name'), 'region': region, 'account': account
                })
            except Exception as e:
                self.cleanup_results['failed_deletions'].append({'api_id': api['ApiId'], 'error': str(e)})
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} HTTP APIs")

    def cleanup_account_region(self, account_info: dict, region: str):
        try:
            account_name = account_info.get('name')
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] {account_name} - {region}")
            
            # REST APIs
            rest_client = boto3.client('apigateway', 
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            self.delete_rest_apis(rest_client, region, account_name)
            
            # HTTP/WebSocket APIs
            v2_client = boto3.client('apigatewayv2',
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            self.delete_http_apis(v2_client, region, account_name)
            
            if account_name not in [a['account'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account': account_name})
            
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   [ERROR] {e}")
            return False

    def save_report(self):
        report_file = f"{self.reports_dir}/ultra_apigateway_cleanup_{self.execution_timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump({"summary": {
                "rest_apis": len(self.cleanup_results['deleted_rest_apis']),
                "http_apis": len(self.cleanup_results['deleted_http_apis'])
            }, "details": self.cleanup_results}, f, indent=2)
        return report_file

    def run(self):
        self.print_colored(Colors.BLUE, "\n[START] ULTRA API GATEWAY CLEANUP MANAGER")
        
        accounts = self.cred_manager.select_root_accounts_interactive()
        if not accounts:
            return
        
        regions = self._get_regions()
        
        if input("\nType 'DELETE': ").strip().upper() != 'DELETE':
            return
        
        for acc in accounts:
            for reg in regions:
                self.cleanup_account_region(acc, reg)
        
        total = len(self.cleanup_results['deleted_rest_apis']) + len(self.cleanup_results['deleted_http_apis'])
        self.print_colored(Colors.WHITE, f"\n[STATS] APIs deleted: {total}")
        self.print_colored(Colors.GREEN, f"[OK] Report: {self.save_report()}")

def main():
    try:
        UltraCleanupAPIGatewayManager().run()
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
