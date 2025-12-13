#!/usr/bin/env python3
"""
Ultra AWS FSx Cleanup Manager - File Systems (Windows, Lustre, NetApp ONTAP, OpenZFS)
"""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boto3, json, time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager
from text_symbols import Symbols

class Colors:
    RED='\033[91m';GREEN='\033[92m';YELLOW='\033[93m';BLUE='\033[94m';CYAN='\033[96m';END='\033[0m'

class UltraCleanupFSxManager:
    def __init__(self):
        self.cred_manager=AWSCredentialManager();self.execution_timestamp=datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        self.base_dir=os.path.join(os.getcwd(),'aws','fsx');self.logs_dir=os.path.join(self.base_dir,'logs');self.reports_dir=os.path.join(self.base_dir,'reports')
        os.makedirs(self.logs_dir,exist_ok=True);os.makedirs(self.reports_dir,exist_ok=True)
        self.log_file=os.path.join(self.logs_dir,f'fsx_cleanup_log_{self.execution_timestamp}.log')
        self.cleanup_results={'accounts_processed':[],'deleted_filesystems':[],'deleted_backups':[],'errors':[]}
    def print_colored(self,color,message):print(f"{color}{message}{Colors.END}")
    def log_action(self,message,level="INFO"):
        with open(self.log_file,'a') as f:f.write(f"{datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')} | {level:8} | {message}\n")
    def cleanup_region_fsx(self,account_name,credentials,region):
        try:
            self.print_colored(Colors.YELLOW,f"\n{Symbols.SCAN} Scanning region: {region}")
            fsx_client=boto3.client('fsx',region_name=region,aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
            try:
                fs_response=fsx_client.describe_file_systems();filesystems=fs_response.get('FileSystems',[])
                if filesystems:
                    self.print_colored(Colors.CYAN,f"[FS] Found {len(filesystems)} file systems")
                    for fs in filesystems:
                        try:
                            self.print_colored(Colors.CYAN,f"{Symbols.DELETE} Deleting file system: {fs['FileSystemId']} ({fs['FileSystemType']})")
                            fsx_client.delete_file_system(FileSystemId=fs['FileSystemId'])
                            self.cleanup_results['deleted_filesystems'].append({'fs_id':fs['FileSystemId'],'fs_type':fs['FileSystemType'],'region':region,'account_key':account_name})
                            time.sleep(2)
                        except ClientError:pass
            except ClientError as e:self.log_action(f"Error in {region}: {e}","ERROR")
            try:
                backups=fsx_client.describe_backups();backup_list=backups.get('Backups',[])
                if backup_list:
                    self.print_colored(Colors.CYAN,f"[BACKUP] Found {len(backup_list)} backups")
                    for backup in backup_list:
                        try:
                            fsx_client.delete_backup(BackupId=backup['BackupId'])
                            self.cleanup_results['deleted_backups'].append({'backup_id':backup['BackupId'],'region':region,'account_key':account_name})
                            time.sleep(1)
                        except ClientError:pass
            except ClientError:pass
        except Exception as e:self.cleanup_results['errors'].append(str(e))
    def cleanup_account_fsx(self,account_name,credentials):
        self.print_colored(Colors.BLUE,f"\n{'='*100}\n{Symbols.START} Processing Account: {account_name}\n{'='*100}")
        self.cleanup_results['accounts_processed'].append(account_name)
        ec2=boto3.client('ec2',region_name='us-east-1',aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
        regions=[r['RegionName'] for r in ec2.describe_regions()['Regions']]
        for region in regions:self.cleanup_region_fsx(account_name,credentials,region)
    def interactive_cleanup(self):
        self.print_colored(Colors.BLUE,"\n"+"="*100+f"\n{Symbols.START} ULTRA AWS FSX CLEANUP MANAGER\n"+"="*100)
        config=self.cred_manager.load_root_accounts_config()
        if not config or 'accounts' not in config:self.print_colored(Colors.RED,f"{Symbols.ERROR} No accounts found!");return
        accounts=config['accounts'];account_list=list(accounts.keys())
        self.print_colored(Colors.YELLOW,f"\n{Symbols.KEY} Available Accounts:");print("="*100)
        for idx,name in enumerate(account_list,1):print(f"   {idx}. {name}")
        print("="*100)
        selection=input(f"Select accounts or 'q' to quit: ").strip()
        if selection.lower()=='q':return
        selected_accounts=account_list if selection.lower()=='all' else [account_list[int(x.strip())-1] for x in selection.split(',')]
        self.print_colored(Colors.RED,f"\n{Symbols.WARN} This will DELETE all FSx file systems!")
        if input("\nType 'yes' to confirm: ").strip().lower()!='yes':return
        for account_name in selected_accounts:
            self.cleanup_account_fsx(account_name,{'access_key':accounts[account_name]['access_key'],'secret_key':accounts[account_name]['secret_key']})
        report_path=os.path.join(self.reports_dir,f"fsx_cleanup_{self.execution_timestamp}.json")
        with open(report_path,'w') as f:json.dump(self.cleanup_results,f,indent=2)
        self.print_colored(Colors.GREEN,f"\n{Symbols.OK} FSx cleanup completed! Report: {report_path}")

def main():
    try:UltraCleanupFSxManager().interactive_cleanup()
    except KeyboardInterrupt:print("\n[WARN] Cancelled!")
if __name__=="__main__":main()
