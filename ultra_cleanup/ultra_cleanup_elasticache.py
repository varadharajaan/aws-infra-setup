#!/usr/bin/env python3
"""Ultra ElastiCache Cleanup Manager - Deletes Redis and Memcached clusters"""

import os, json, boto3, time
from datetime import datetime
from typing import List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors
from text_symbols import Symbols

class UltraCleanupElastiCacheManager:
    def __init__(self, config_dir: str = None):
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.cache_dir = os.path.join(self.config_dir, "aws", "elasticache")
        self.reports_dir = os.path.join(self.cache_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_cache_clusters': [],
            'deleted_replication_groups': [],
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

    def delete_replication_groups(self, client, region, account):
        deleted = 0
        paginator = client.get_paginator('describe_replication_groups')
        
        for page in paginator.paginate():
            for rg in page.get('ReplicationGroups', []):
                rg_id = rg['ReplicationGroupId']
                try:
                    client.delete_replication_group(
                        ReplicationGroupId=rg_id,
                        RetainPrimaryCluster=False
                    )
                    deleted += 1
                    self.cleanup_results['deleted_replication_groups'].append({
                        'replication_group_id': rg_id,
                        'status': rg.get('Status'),
                        'region': region,
                        'account': account
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'replication_group': rg_id, 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Deleted {deleted} replication groups")

    def delete_cache_clusters(self, client, region, account):
        deleted = 0
        paginator = client.get_paginator('describe_cache_clusters')
        
        for page in paginator.paginate():
            for cluster in page.get('CacheClusters', []):
                cluster_id = cluster['CacheClusterId']
                
                # Skip if part of replication group (will be deleted with group)
                if cluster.get('ReplicationGroupId'):
                    continue
                
                try:
                    client.delete_cache_cluster(CacheClusterId=cluster_id)
                    deleted += 1
                    self.cleanup_results['deleted_cache_clusters'].append({
                        'cluster_id': cluster_id,
                        'engine': cluster.get('Engine'),
                        'region': region,
                        'account': account
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'cluster': cluster_id, 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   {Symbols.OK} Deleted {deleted} cache clusters")

    def cleanup_account_region(self, account_info: dict, region: str):
        try:
            account_name = account_info.get('name')
            self.print_colored(Colors.CYAN, f"\n{Symbols.CLEANUP} {account_name} - {region}")
            
            client = boto3.client('elasticache',
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            
            self.delete_replication_groups(client, region, account_name)
            self.delete_cache_clusters(client, region, account_name)
            
            if account_name not in [a['account'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account': account_name})
            
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   {Symbols.ERROR} {e}")
            return False

    def save_report(self):
        report_file = f"{self.reports_dir}/ultra_elasticache_cleanup_{self.execution_timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump({"summary": {
                "clusters": len(self.cleanup_results['deleted_cache_clusters']),
                "replication_groups": len(self.cleanup_results['deleted_replication_groups'])
            }, "details": self.cleanup_results}, f, indent=2)
        return report_file

    def run(self):
        self.print_colored(Colors.BLUE, f"\n{Symbols.START} ULTRA ELASTICACHE CLEANUP MANAGER")
        
        accounts = self.cred_manager.select_root_accounts_interactive()
        if not accounts:
            return
        
        regions = self.cred_manager.select_regions_interactive()
        if not regions:
            self.print_colored(Colors.YELLOW, f"{Symbols.ERROR} No regions selected. Exiting.")
            return
        
        if input("\nType 'yes': ").strip().lower() != 'yes':
            return
        
        for acc in accounts:
            for reg in regions:
                self.cleanup_account_region(acc, reg)
        
        self.print_colored(Colors.WHITE, f"\n{Symbols.STATS} Clusters: {len(self.cleanup_results['deleted_cache_clusters'])}")
        self.print_colored(Colors.WHITE, f"{Symbols.STATS} Replication Groups: {len(self.cleanup_results['deleted_replication_groups'])}")
        self.print_colored(Colors.GREEN, f"{Symbols.OK} Report: {self.save_report()}")

def main():
    try:
        UltraCleanupElastiCacheManager().run()
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
