#!/usr/bin/env python3
"""Ultra Lambda Cleanup Manager - Deletes Lambda functions, layers, and event source mappings"""

import os
import json
import boto3
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors

class UltraCleanupLambdaManager:
    def __init__(self, config_dir: str = None):
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.lambda_dir = os.path.join(self.config_dir, "aws", "lambda")
        self.reports_dir = os.path.join(self.lambda_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_functions': [],
            'deleted_layers': [],
            'deleted_event_mappings': [],
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

    def delete_functions(self, client, region, account):
        deleted = 0
        paginator = client.get_paginator('list_functions')
        
        for page in paginator.paginate():
            for func in page.get('Functions', []):
                try:
                    client.delete_function(FunctionName=func['FunctionName'])
                    deleted += 1
                    self.cleanup_results['deleted_functions'].append({
                        'function_name': func['FunctionName'],
                        'runtime': func.get('Runtime'),
                        'region': region,
                        'account': account
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'function': func['FunctionName'], 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} functions")

    def delete_layers(self, client, region, account):
        deleted = 0
        paginator = client.get_paginator('list_layers')
        
        for page in paginator.paginate():
            for layer in page.get('Layers', []):
                layer_name = layer['LayerName']
                try:
                    # Delete all versions
                    versions = client.list_layer_versions(LayerName=layer_name)
                    for version in versions.get('LayerVersions', []):
                        client.delete_layer_version(
                            LayerName=layer_name,
                            VersionNumber=version['Version']
                        )
                    deleted += 1
                    self.cleanup_results['deleted_layers'].append({
                        'layer_name': layer_name, 'region': region, 'account': account
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'layer': layer_name, 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} layers")

    def delete_event_source_mappings(self, client, region, account):
        deleted = 0
        paginator = client.get_paginator('list_event_source_mappings')
        
        for page in paginator.paginate():
            for mapping in page.get('EventSourceMappings', []):
                try:
                    client.delete_event_source_mapping(UUID=mapping['UUID'])
                    deleted += 1
                    self.cleanup_results['deleted_event_mappings'].append({
                        'uuid': mapping['UUID'], 'region': region, 'account': account
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'mapping': mapping['UUID'], 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} event mappings")

    def cleanup_account_region(self, account_info: dict, region: str):
        try:
            account_name = account_info.get('name')
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] {account_name} - {region}")
            
            client = boto3.client('lambda',
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            
            self.delete_event_source_mappings(client, region, account_name)
            self.delete_functions(client, region, account_name)
            self.delete_layers(client, region, account_name)
            
            if account_name not in [a['account'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account': account_name})
            
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   [ERROR] {e}")
            return False

    def save_report(self):
        report_file = f"{self.reports_dir}/ultra_lambda_cleanup_{self.execution_timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump({"summary": {
                "functions": len(self.cleanup_results['deleted_functions']),
                "layers": len(self.cleanup_results['deleted_layers']),
                "event_mappings": len(self.cleanup_results['deleted_event_mappings'])
            }, "details": self.cleanup_results}, f, indent=2)
        return report_file

    def run(self):
        self.print_colored(Colors.BLUE, "\n[START] ULTRA LAMBDA CLEANUP MANAGER")
        
        accounts = self.cred_manager.select_root_accounts_interactive()
        if not accounts:
            return
        
        regions = self._get_regions()
        
        if input("\nType 'DELETE': ").strip().upper() != 'DELETE':
            return
        
        for acc in accounts:
            for reg in regions:
                self.cleanup_account_region(acc, reg)
        
        total = len(self.cleanup_results['deleted_functions'])
        self.print_colored(Colors.WHITE, f"\n[STATS] Functions deleted: {total}")
        self.print_colored(Colors.GREEN, f"[OK] Report: {self.save_report()}")

def main():
    try:
        UltraCleanupLambdaManager().run()
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
