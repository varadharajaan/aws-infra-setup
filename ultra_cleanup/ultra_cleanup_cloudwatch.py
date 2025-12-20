#!/usr/bin/env python3
"""Ultra CloudWatch Cleanup Manager - Deletes alarms, log groups, dashboards, and metrics"""

import os
import json
import boto3
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors

class UltraCleanupCloudWatchManager:
    def __init__(self, config_dir: str = None):
        self.cred_manager = AWSCredentialManager(config_dir)
        self.config_dir = self.cred_manager.config_dir
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.cw_dir = os.path.join(self.config_dir, "aws", "cloudwatch")
        self.reports_dir = os.path.join(self.cw_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        
        self.cleanup_results = {
            'accounts_processed': [],
            'deleted_alarms': [],
            'deleted_log_groups': [],
            'deleted_dashboards': [],
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

    def delete_alarms(self, cw_client, region, account):
        deleted = 0
        paginator = cw_client.get_paginator('describe_alarms')
        
        alarm_names = []
        for page in paginator.paginate():
            for alarm in page.get('MetricAlarms', []):
                alarm_names.append(alarm['AlarmName'])
            for alarm in page.get('CompositeAlarms', []):
                alarm_names.append(alarm['AlarmName'])
        
        # Delete in batches of 100
        for i in range(0, len(alarm_names), 100):
            batch = alarm_names[i:i+100]
            try:
                cw_client.delete_alarms(AlarmNames=batch)
                deleted += len(batch)
                for alarm_name in batch:
                    self.cleanup_results['deleted_alarms'].append({
                        'alarm_name': alarm_name, 'region': region, 'account': account
                    })
            except Exception as e:
                self.cleanup_results['failed_deletions'].append({
                    'alarms': batch, 'error': str(e)
                })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} alarms")

    def delete_log_groups(self, logs_client, region, account):
        deleted = 0
        paginator = logs_client.get_paginator('describe_log_groups')
        
        for page in paginator.paginate():
            for lg in page.get('logGroups', []):
                lg_name = lg['logGroupName']
                try:
                    logs_client.delete_log_group(logGroupName=lg_name)
                    deleted += 1
                    self.cleanup_results['deleted_log_groups'].append({
                        'log_group_name': lg_name, 'region': region, 'account': account
                    })
                except Exception as e:
                    self.cleanup_results['failed_deletions'].append({
                        'log_group': lg_name, 'error': str(e)
                    })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} log groups")

    def delete_dashboards(self, cw_client, region, account):
        deleted = 0
        paginator = cw_client.get_paginator('list_dashboards')
        
        dashboard_names = []
        for page in paginator.paginate():
            for db in page.get('DashboardEntries', []):
                dashboard_names.append(db['DashboardName'])
        
        if dashboard_names:
            try:
                cw_client.delete_dashboards(DashboardNames=dashboard_names)
                deleted = len(dashboard_names)
                for db_name in dashboard_names:
                    self.cleanup_results['deleted_dashboards'].append({
                        'dashboard_name': db_name, 'region': region, 'account': account
                    })
            except Exception as e:
                self.cleanup_results['failed_deletions'].append({
                    'dashboards': dashboard_names, 'error': str(e)
                })
        
        if deleted > 0:
            self.print_colored(Colors.GREEN, f"   [OK] Deleted {deleted} dashboards")

    def cleanup_account_region(self, account_info: dict, region: str):
        try:
            account_name = account_info.get('name')
            self.print_colored(Colors.CYAN, f"\n[CLEANUP] {account_name} - {region}")
            
            cw_client = boto3.client('cloudwatch',
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            
            logs_client = boto3.client('logs',
                aws_access_key_id=account_info.get('access_key'),
                aws_secret_access_key=account_info.get('secret_key'),
                region_name=region)
            
            self.delete_alarms(cw_client, region, account_name)
            self.delete_dashboards(cw_client, region, account_name)
            self.delete_log_groups(logs_client, region, account_name)
            
            if account_name not in [a['account'] for a in self.cleanup_results['accounts_processed']]:
                self.cleanup_results['accounts_processed'].append({'account': account_name})
            
            return True
        except Exception as e:
            self.print_colored(Colors.RED, f"   [ERROR] {e}")
            return False

    def save_report(self):
        report_file = f"{self.reports_dir}/ultra_cloudwatch_cleanup_{self.execution_timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump({"summary": {
                "alarms": len(self.cleanup_results['deleted_alarms']),
                "log_groups": len(self.cleanup_results['deleted_log_groups']),
                "dashboards": len(self.cleanup_results['deleted_dashboards'])
            }, "details": self.cleanup_results}, f, indent=2)
        return report_file

    def run(self):
        self.print_colored(Colors.BLUE, "\n[START] ULTRA CLOUDWATCH CLEANUP MANAGER")
        
        accounts = self.cred_manager.select_root_accounts_interactive()
        if not accounts:
            return
        
        regions = self._get_regions()
        
        self.print_colored(Colors.RED, "\n[WARN]  WARNING: This deletes ALL CloudWatch resources!")
        if input("\nType 'DELETE': ").strip().upper() != 'DELETE':
            return
        
        for acc in accounts:
            for reg in regions:
                self.cleanup_account_region(acc, reg)
        
        self.print_colored(Colors.WHITE, f"\n[STATS] Alarms: {len(self.cleanup_results['deleted_alarms'])}")
        self.print_colored(Colors.WHITE, f"[STATS] Log Groups: {len(self.cleanup_results['deleted_log_groups'])}")
        self.print_colored(Colors.WHITE, f"[STATS] Dashboards: {len(self.cleanup_results['deleted_dashboards'])}")
        self.print_colored(Colors.GREEN, f"[OK] Report: {self.save_report()}")

def main():
    try:
        UltraCleanupCloudWatchManager().run()
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted")

if __name__ == "__main__":
    main()
