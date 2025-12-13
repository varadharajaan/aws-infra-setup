#!/usr/bin/env python3
"""
Ultra AWS SageMaker Cleanup Manager
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

class UltraCleanupSageMakerManager:
    def __init__(self):
        self.cred_manager=AWSCredentialManager();self.execution_timestamp=datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')
        self.base_dir=os.path.join(os.getcwd(),'aws','sagemaker');os.makedirs(os.path.join(self.base_dir,'logs'),exist_ok=True);os.makedirs(os.path.join(self.base_dir,'reports'),exist_ok=True)
        self.cleanup_results={'accounts_processed':[],'deleted_endpoints':[],'deleted_notebook_instances':[],'deleted_models':[],'errors':[]}
    def print_colored(self,color,msg):print(f"{color}{msg}{Colors.END}")
    def cleanup_region(self,account_name,credentials,region):
        try:
            self.print_colored(Colors.YELLOW,f"\n{Symbols.SCAN} Region: {region}")
            sm=boto3.client('sagemaker',region_name=region,aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
            try:
                endpoints=sm.list_endpoints();ep_list=endpoints.get('Endpoints',[])
                if ep_list:
                    self.print_colored(Colors.CYAN,f"[ENDPOINT] Found {len(ep_list)} endpoints")
                    for ep in ep_list:
                        try:
                            self.print_colored(Colors.CYAN,f"{Symbols.DELETE} Deleting endpoint: {ep['EndpointName']}")
                            sm.delete_endpoint(EndpointName=ep['EndpointName'])
                            self.cleanup_results['deleted_endpoints'].append({'name':ep['EndpointName'],'region':region,'account_key':account_name})
                            time.sleep(1)
                        except ClientError:pass
            except ClientError:pass
            try:
                notebooks=sm.list_notebook_instances();nb_list=notebooks.get('NotebookInstances',[])
                if nb_list:
                    self.print_colored(Colors.CYAN,f"[NOTEBOOK] Found {len(nb_list)} notebook instances")
                    for nb in nb_list:
                        try:
                            if nb['NotebookInstanceStatus']!='Deleting':
                                if nb['NotebookInstanceStatus']=='InService':
                                    sm.stop_notebook_instance(NotebookInstanceName=nb['NotebookInstanceName'])
                                    time.sleep(10)
                                self.print_colored(Colors.CYAN,f"{Symbols.DELETE} Deleting notebook: {nb['NotebookInstanceName']}")
                                sm.delete_notebook_instance(NotebookInstanceName=nb['NotebookInstanceName'])
                                self.cleanup_results['deleted_notebook_instances'].append({'name':nb['NotebookInstanceName'],'region':region,'account_key':account_name})
                                time.sleep(2)
                        except ClientError:pass
            except ClientError:pass
            try:
                models=sm.list_models();model_list=models.get('Models',[])
                if model_list:
                    for model in model_list:
                        try:
                            sm.delete_model(ModelName=model['ModelName'])
                            self.cleanup_results['deleted_models'].append({'name':model['ModelName'],'region':region,'account_key':account_name})
                            time.sleep(1)
                        except ClientError:pass
            except ClientError:pass
        except Exception as e:self.cleanup_results['errors'].append(str(e))
    def cleanup_account(self,account_name,credentials):
        self.print_colored(Colors.BLUE,f"\n{'='*100}\n{Symbols.START} Account: {account_name}\n{'='*100}")
        self.cleanup_results['accounts_processed'].append(account_name)
        ec2=boto3.client('ec2',region_name='us-east-1',aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
        regions=[r['RegionName'] for r in ec2.describe_regions()['Regions']]
        for region in regions:self.cleanup_region(account_name,credentials,region)
    def interactive_cleanup(self):
        self.print_colored(Colors.BLUE,"\n"+"="*100+f"\n{Symbols.START} ULTRA AWS SAGEMAKER CLEANUP\n"+"="*100)
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
        self.print_colored(Colors.GREEN,f"\n{Symbols.OK} SageMaker cleanup completed!")

def main():
    try:UltraCleanupSageMakerManager().interactive_cleanup()
    except KeyboardInterrupt:print(f"\n{Symbols.WARN} Cancelled!")
if __name__=="__main__":main()
