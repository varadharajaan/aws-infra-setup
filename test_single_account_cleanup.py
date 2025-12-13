#!/usr/bin/env python3

import boto3
import json
import sys
from botocore.exceptions import ClientError
from text_symbols import Symbols

def test_single_account():
    """Test cleanup script logic with account02 (the one that just worked)"""
    
    # Load your config
    with open('aws_accounts_config.json', 'r') as f:
        config = json.load(f)
    
    # Test account02 (the one that just created an instance)
    account_data = config['accounts']['account02']
    access_key = account_data['access_key']
    secret_key = account_data['secret_key']
    region = 'us-east-1'  # Same region where you just created the instance
    
    print(f"{Symbols.SCAN} Testing account02 in {region}")
    print(f"Access Key: {access_key[:10]}...{access_key[-4:]}")
    
    try:
        # Create EC2 client exactly like the cleanup script does
        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        
        # Test the exact same call that fails in cleanup script
        print("Testing describe_regions...")
        regions_response = ec2_client.describe_regions(RegionNames=[region])
        print(f"{Symbols.OK} describe_regions successful")
        
        # Test describe_instances (should find your newly created instance)
        print("Testing describe_instances...")
        instances_response = ec2_client.describe_instances()
        instance_count = sum(len(r['Instances']) for r in instances_response['Reservations'])
        print(f"{Symbols.OK} Found {instance_count} instances")
        
        # List instance details
        for reservation in instances_response['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                state = instance['State']['Name']
                instance_type = instance['InstanceType']
                public_ip = instance.get('PublicIpAddress', 'None')
                print(f"   Instance: {instance_id} | State: {state} | Type: {instance_type} | IP: {public_ip}")
        
        # Test describe_security_groups
        print("Testing describe_security_groups...")
        sgs_response = ec2_client.describe_security_groups()
        sg_count = len(sgs_response['SecurityGroups'])
        print(f"{Symbols.OK} Found {sg_count} security groups")
        
        print(f"\n{Symbols.OK} All tests passed! Your credentials work fine.")
        return True
        
    except Exception as e:
        print(f"{Symbols.ERROR} Error: {e}")
        return False

if __name__ == "__main__":
    test_single_account()