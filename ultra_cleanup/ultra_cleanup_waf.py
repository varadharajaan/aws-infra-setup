#!/usr/bin/env python3
"""
Ultra AWS WAF Cleanup Manager
"""
import sys,os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boto3,json,time
from datetime import datetime
from botocore.exceptions import ClientError
from root_iam_credential_manager import AWSCredentialManager

class Colors:
    RED='\033[91m';GREEN='\033[92m';YELLOW='\033[93m';BLUE='\033[94m';CYAN='\033[96m';END='\033[0m'

class UltraCleanupWAFManager:
    def __init__(self):
        self.cred_manager=AWSCredentialManager();self.execution_timestamp=datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.base_dir=os.path.join(os.getcwd(),'aws','waf');os.makedirs(os.path.join(self.base_dir,'logs'),exist_ok=True);os.makedirs(os.path.join(self.base_dir,'reports'),exist_ok=True)
        self.cleanup_results={'accounts_processed':[],'deleted_web_acls':[],'deleted_rule_groups':[],'deleted_ip_sets':[],'errors':[]}
    def print_colored(self,color,msg):print(f"{color}{msg}{Colors.END}")
    def cleanup_region_waf(self,account_name,credentials,region,scope):
        try:
            self.print_colored(Colors.YELLOW,f"\n[SCAN] {region} ({scope})")
            waf=boto3.client('wafv2',region_name=region,aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
            try:
                acls=waf.list_web_acls(Scope=scope);acl_list=acls.get('WebACLs',[])
                if acl_list:
                    self.print_colored(Colors.CYAN,f"[ACL] Found {len(acl_list)} Web ACLs")
                    for acl in acl_list:
                        try:
                            self.print_colored(Colors.CYAN,f"[DELETE] Deleting Web ACL: {acl['Name']}")
                            waf.delete_web_acl(Name=acl['Name'],Scope=scope,Id=acl['Id'],LockToken=acl['LockToken'])
                            self.cleanup_results['deleted_web_acls'].append({'name':acl['Name'],'scope':scope,'region':region,'account_key':account_name})
                            time.sleep(1)
                        except ClientError:pass
            except ClientError:pass
            try:
                rule_groups=waf.list_rule_groups(Scope=scope);rg_list=rule_groups.get('RuleGroups',[])
                if rg_list:
                    for rg in rg_list:
                        try:
                            if not rg['Name'].startswith('AWS'):
                                waf.delete_rule_group(Name=rg['Name'],Scope=scope,Id=rg['Id'],LockToken=rg['LockToken'])
                                self.cleanup_results['deleted_rule_groups'].append({'name':rg['Name'],'scope':scope,'region':region,'account_key':account_name})
                                time.sleep(1)
                        except ClientError:pass
            except ClientError:pass
            try:
                ip_sets=waf.list_ip_sets(Scope=scope);ip_list=ip_sets.get('IPSets',[])
                if ip_list:
                    for ip_set in ip_list:
                        try:
                            waf.delete_ip_set(Name=ip_set['Name'],Scope=scope,Id=ip_set['Id'],LockToken=ip_set['LockToken'])
                            self.cleanup_results['deleted_ip_sets'].append({'name':ip_set['Name'],'scope':scope,'region':region,'account_key':account_name})
                            time.sleep(1)
                        except ClientError:pass
            except ClientError:pass
        except Exception as e:self.cleanup_results['errors'].append(str(e))
    def cleanup_account(self,account_name,credentials):
        self.print_colored(Colors.BLUE,f"\n{'='*100}\n[START] Account: {account_name}\n{'='*100}")
        self.cleanup_results['accounts_processed'].append(account_name)
        ec2=boto3.client('ec2',region_name='us-east-1',aws_access_key_id=credentials['access_key'],aws_secret_access_key=credentials['secret_key'])
        regions=[r['RegionName'] for r in ec2.describe_regions()['Regions']]
        for region in regions:
            self.cleanup_region_waf(account_name,credentials,region,'REGIONAL')
        self.cleanup_region_waf(account_name,credentials,'us-east-1','CLOUDFRONT')
    def interactive_cleanup(self):
        self.print_colored(Colors.BLUE,"\n"+"="*100+"\n[START] ULTRA AWS WAF CLEANUP\n"+"="*100)
        config=self.cred_manager.load_root_accounts_config()
        if not config:return
        accounts=config['accounts'];account_list=list(accounts.keys())
        for idx,name in enumerate(account_list,1):print(f"{idx}. {name}")
        selection=input("Select accounts or 'q': ").strip()
        if selection.lower()=='q':return
        selected=account_list if selection.lower()=='all' else [account_list[int(x.strip())-1] for x in selection.split(',')]
        if input("\nType 'DELETE' to confirm: ").strip()!='DELETE':return
        for name in selected:
            self.cleanup_account(name,{'access_key':accounts[name]['access_key'],'secret_key':accounts[name]['secret_key']})
        self.print_colored(Colors.GREEN,"\n[OK] WAF cleanup completed!")

def main():
    try:UltraCleanupWAFManager().interactive_cleanup()
    except KeyboardInterrupt:print("\n[WARN] Cancelled!")
if __name__=="__main__":main()
