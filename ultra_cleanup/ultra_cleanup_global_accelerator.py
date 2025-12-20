#!/usr/bin/env python3
"""
Ultra AWS Global Accelerator Cleanup Manager
"""
import sys,os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boto3
import time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager

class Colors:
    RED='\033[91m';GREEN='\033[92m';YELLOW='\033[93m';BLUE='\033[94m';CYAN='\033[96m';END='\033[0m'

class UltraCleanupGlobalAcceleratorManager:
    def __init__(self):
        self.cred_manager=AWSCredentialManager();self.execution_timestamp=datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.base_dir=os.path.join(os.getcwd(),'aws','global_accelerator');os.makedirs(os.path.join(self.base_dir,'logs'),exist_ok=True);os.makedirs(os.path.join(self.base_dir,'reports'),exist_ok=True)
        self.cleanup_results={'accounts_processed':[],'deleted_accelerators':[],'errors':[]}
    def print_colored(self,color,msg):print(f"{color}{msg}{Colors.END}")
    def cleanup_global_accelerator(self,account_name,credentials):
        try:
            self.print_colored(Colors.YELLOW,f"\n[SCAN] Global Accelerator (us-west-2 only)")
            ga=boto3.client('globalaccelerator',region_name='us-west-2',aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
            try:
                accelerators=ga.list_accelerators();acc_list=accelerators.get('Accelerators',[])
                if acc_list:
                    self.print_colored(Colors.CYAN,f"[ACC] Found {len(acc_list)} accelerators")
                    for acc in acc_list:
                        try:
                            if acc['Status']=='DEPLOYED':
                                self.print_colored(Colors.YELLOW,f"[DISABLE] Disabling: {acc['Name']}")
                                ga.update_accelerator(AcceleratorArn=acc['AcceleratorArn'],Enabled=False)
                                time.sleep(30)
                            self.print_colored(Colors.CYAN,f"[DELETE] Deleting: {acc['Name']}")
                            ga.delete_accelerator(AcceleratorArn=acc['AcceleratorArn'])
                            self.cleanup_results['deleted_accelerators'].append({'name':acc['Name'],'arn':acc['AcceleratorArn'],'account_key':account_name})
                            time.sleep(2)
                        except ClientError:pass
            except ClientError as e:pass
        except Exception as e:self.cleanup_results['errors'].append(str(e))
    def cleanup_account(self,account_name,credentials):
        self.print_colored(Colors.BLUE,f"\n{'='*100}\n[START] Account: {account_name}\n{'='*100}")
        self.cleanup_results['accounts_processed'].append(account_name)
        self.cleanup_global_accelerator(account_name,credentials)
    def interactive_cleanup(self):
        self.print_colored(Colors.BLUE,"\n"+"="*100+"\n[START] ULTRA AWS GLOBAL ACCELERATOR CLEANUP\n"+"="*100)
        config=self.cred_manager.load_root_accounts_config()
        if not config:return
        accounts=config['accounts'];account_list=list(accounts.keys())
        for idx,name in enumerate(account_list,1):print(f"{idx}. {name}")
        selection=input("Select accounts or 'q': ").strip()
        if selection.lower()=='q':return
        selected=account_list if selection.lower()=='all' else [account_list[int(x.strip())-1] for x in selection.split(',')]
        if input("\nType 'yes' to confirm: ").strip().lower()!='yes':return
        for name in selected:
            self.cleanup_account(name,{'access_key':accounts[name]['access_key'],'secret_key':accounts[name]['secret_key']})
        self.print_colored(Colors.GREEN,"\n[OK] Global Accelerator cleanup completed!")

def main():
    try:UltraCleanupGlobalAcceleratorManager().interactive_cleanup()
    except KeyboardInterrupt:print("\n[WARN] Cancelled!")
if __name__=="__main__":main()
