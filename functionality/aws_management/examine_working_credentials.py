#!/usr/bin/env python3

import json
import boto3

def examine_credentials_structure():
    """Examine the structure of the working credentials file"""
    
    print("🔍 EXAMINING WORKING CREDENTIALS FILE STRUCTURE")
    print("=" * 60)
    
    try:
        with open('iam_users_credentials_20250605_224146.json', 'r') as f:
            working_creds = json.load(f)
        
        print("✅ File loaded successfully")
        print(f"📊 File type: {type(working_creds)}")
        
        if isinstance(working_creds, dict):
            print(f"📋 Top-level keys: {list(working_creds.keys())}")
            
            # Look for any structure that might contain account02 credentials
            for key, value in working_creds.items():
                print(f"\n🔍 Examining key: '{key}'")
                print(f"   Type: {type(value)}")
                
                if isinstance(value, dict):
                    print(f"   Sub-keys: {list(value.keys())}")
                    
                    # Look for account02 or similar
                    for sub_key, sub_value in value.items():
                        if 'account02' in sub_key.lower() or 'account02' in str(sub_value).lower():
                            print(f"   🎯 Found account02 reference in: {sub_key}")
                            print(f"      Value: {sub_value}")
                        
                        # Look for access keys
                        if isinstance(sub_value, dict) and 'access_key' in sub_value:
                            access_key = sub_value['access_key']
                            print(f"   🔑 Found access_key in {sub_key}: {access_key[:10]}...{access_key[-4:]}")
                        
                        # If this sub_value contains access_key directly
                        if isinstance(sub_value, str) and sub_value.startswith('AKIA'):
                            print(f"   🔑 Found potential access_key: {sub_key} = {sub_value[:10]}...{sub_value[-4:]}")
                
                elif isinstance(value, list):
                    print(f"   List length: {len(value)}")
                    if value:
                        print(f"   First item type: {type(value[0])}")
                        if isinstance(value[0], dict):
                            print(f"   First item keys: {list(value[0].keys())}")
        
        elif isinstance(working_creds, list):
            print(f"📋 List length: {len(working_creds)}")
            if working_creds:
                print(f"📋 First item type: {type(working_creds[0])}")
                if isinstance(working_creds[0], dict):
                    print(f"📋 First item keys: {list(working_creds[0].keys())}")
        
        # Now let's try to find the specific credentials that worked
        print(f"\n" + "="*60)
        print("🔍 SEARCHING FOR ACCOUNT02 CREDENTIALS")
        print("="*60)
        
        def search_for_account02(data, path=""):
            """Recursively search for account02 credentials"""
            if isinstance(data, dict):
                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key
                    
                    # Check if this looks like account02
                    if 'account02' in key.lower():
                        print(f"🎯 Found account02 match at: {current_path}")
                        print(f"   Value: {value}")
                    
                    # Check if this contains access_key that matches the pattern we saw in logs
                    if isinstance(value, dict) and 'access_key' in value:
                        access_key = value['access_key']
                        if 'AKIA6P6R7F' in access_key:
                            print(f"🎯 Found matching access_key at: {current_path}")
                            print(f"   Access Key: {access_key[:10]}...{access_key[-4:]}")
                            return current_path, value
                    
                    # Recurse into nested structures
                    result = search_for_account02(value, current_path)
                    if result:
                        return result
            
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    current_path = f"{path}[{i}]" if path else f"[{i}]"
                    result = search_for_account02(item, current_path)
                    if result:
                        return result
            
            return None
        
        found = search_for_account02(working_creds)
        if found:
            path, creds = found
            print(f"\n✅ FOUND WORKING CREDENTIALS!")
            print(f"📍 Location: {path}")
            print(f"🔑 Access Key: {creds['access_key'][:10]}...{creds['access_key'][-4:]}")
            
            # Test these credentials
            print(f"\n🧪 TESTING FOUND CREDENTIALS...")
            test_credentials(creds['access_key'], creds['secret_key'])
        else:
            print(f"\n❌ Could not find account02 credentials with matching access key pattern")
            
    except Exception as e:
        print(f"❌ Error examining file: {e}")

def test_credentials(access_key, secret_key):
    """Test the found credentials"""
    try:
        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='us-east-1'
        )
        
        # Test describe_regions
        regions_response = ec2_client.describe_regions(RegionNames=['us-east-1'])
        print(f"✅ describe_regions: SUCCESS")
        
        # Test describe_instances
        instances_response = ec2_client.describe_instances()
        instance_count = sum(len(r['Instances']) for r in instances_response['Reservations'])
        print(f"✅ describe_instances: Found {instance_count} instances")
        
        return True
        
    except Exception as e:
        print(f"❌ Credential test failed: {e}")
        return False

if __name__ == "__main__":
    examine_credentials_structure()