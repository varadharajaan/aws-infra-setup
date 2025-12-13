#!/usr/bin/env python3
"""
Ultra AWS Storage Gateway Cleanup Manager
"""
import sys,os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boto3,json,time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager
from text_symbols import Symbols

class Colors:
    RED='\033[91m';GREEN='\033[92m';YELLOW='\033[93m';BLUE='\033[94m';CYAN='\033[96m';END='\033[0m'

class UltraCleanupStorageGatewayManager:
    def __init__(self):
        self.cred_manager=AWSCredentialManager();self.execution_timestamp=datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        self.base_dir=os.path.join(os.getcwd(),'aws','storage_gateway');os.makedirs(os.path.join(self.base_dir,'logs'),exist_ok=True);os.makedirs(os.path.join(self.base_dir,'reports'),exist_ok=True)
        self.cleanup_results={'accounts_processed':[],'deleted_gateways':[],'errors':[]}
    def print_colored(self,color,msg):print(f"{color}{msg}{Colors.END}")
    def cleanup_region(self,account_name,credentials,region):
        try:
            self.print_colored(Colors.YELLOW,f"\n{Symbols.SCAN} Region: {region}")
            sgw=boto3.client('storagegateway',region_name=region,aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
            try:
                gateways=sgw.list_gateways();gw_list=gateways.get('Gateways',[])
                if gw_list:
                    self.print_colored(Colors.CYAN,f"[GATEWAY] Found {len(gw_list)} gateways")
                    for gw in gw_list:
                        try:
                            self.print_colored(Colors.CYAN,f"{Symbols.DELETE} Deleting gateway: {gw['GatewayARN']}")
                            sgw.delete_gateway(GatewayARN=gw['GatewayARN'])
                            self.cleanup_results['deleted_gateways'].append({'arn':gw['GatewayARN'],'region':region,'account_key':account_name})
                            time.sleep(2)
                        except ClientError:pass
            except ClientError as e:pass
        except Exception as e:self.cleanup_results['errors'].append(str(e))
    def cleanup_account(self,account_name,credentials):
        self.print_colored(Colors.BLUE,f"\n{'='*100}\n{Symbols.START} Account: {account_name}\n{'='*100}")
        self.cleanup_results['accounts_processed'].append(account_name)
        ec2=boto3.client('ec2',region_name='us-east-1',aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
        regions=[r['RegionName'] for r in ec2.describe_regions()['Regions']]
        for region in regions:self.cleanup_region(account_name,credentials,region)
    def interactive_cleanup(self):
        self.print_colored(Colors.BLUE,"\n"+"="*100+f"\n{Symbols.START} ULTRA AWS STORAGE GATEWAY CLEANUP\n"+"="*100)
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
        self.print_colored(Colors.GREEN,f"\n{Symbols.OK} Storage Gateway cleanup completed!")

def main():
    try:UltraCleanupStorageGatewayManager().interactive_cleanup()
    except KeyboardInterrupt:print(f"\n{Symbols.WARN} Cancelled!")
if __name__=="__main__":main()
