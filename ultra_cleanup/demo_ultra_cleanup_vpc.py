#!/usr/bin/env python3

"""
Demo script to show the Ultra VPC Cleanup Manager interactive interface
"""

import sys
import os
import tempfile
import json
from unittest.mock import patch

# Add the main directory to the path
sys.path.append('/home/runner/work/aws-infra-setup/aws-infra-setup')

def create_demo_config():
    """Create a demo configuration file"""
    demo_config = {
        "accounts": {
            "production-account": {
                "account_id": "123456789012",
                "email": "prod@example.com",
                "access_key": "AKIAEXAMPLE1234567890",
                "secret_key": "example-secret-key-1234567890abcdef",
                "users_per_account": 3
            },
            "staging-account": {
                "account_id": "123456789013", 
                "email": "staging@example.com",
                "access_key": "AKIAEXAMPLE1234567891",
                "secret_key": "example-secret-key-1234567890abcdef2",
                "users_per_account": 2
            },
            "development-account": {
                "account_id": "123456789014",
                "email": "dev@example.com", 
                "access_key": "AKIAEXAMPLE1234567892",
                "secret_key": "example-secret-key-1234567890abcdef3",
                "users_per_account": 1
            }
        },
        "user_settings": {
            "user_regions": ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1"]
        }
    }
    
    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(demo_config, f, indent=2)
        return f.name

def simulate_interactive_demo():
    """Simulate running the interactive demo"""
    config_file = create_demo_config()
    
    try:
        from ultra_cleanup_vpc import UltraVPCCleanupManager
        
        print("[TARGET] ULTRA VPC CLEANUP MANAGER - DEMO")
        print("=" * 80)
        print("This demo shows the Enhanced Ultra VPC Cleanup Manager interface")
        print("without actually connecting to AWS or making any changes.")
        print("=" * 80)
        
        # Initialize the manager
        manager = UltraVPCCleanupManager(config_file)
        
        print(f"\n{Symbols.OK} Successfully initialized VPC Cleanup Manager")
        print(f"{Symbols.FOLDER} Loaded configuration with {len(manager.config_data['accounts'])} accounts")
        print(f"{Symbols.REGION} Will work across {len(manager.regions)} regions")
        
        print(f"\n🏢 Available accounts:")
        for account_name, account_data in manager.config_data['accounts'].items():
            account_id = account_data.get('account_id', 'Unknown')
            email = account_data.get('email', 'Unknown')
            print(f"   • {account_name}: {account_id} ({email})")
        
        print(f"\n{Symbols.REGION} Available regions: {', '.join(manager.regions)}")
        
        print(f"\n{Symbols.DELETE} VPC Resource Types that will be handled:")
        for i, resource_type in enumerate(manager.cleanup_order, 1):
            display_name = resource_type.replace('_', ' ').title()
            print(f"   {i:2}. {display_name}")
        
        print(f"\n{Symbols.PROTECTED} Safety Features:")
        print(f"   {Symbols.OK} Default VPC resources are COMPLETELY PROTECTED")
        print(f"   {Symbols.OK} Only custom VPC resources will be processed")
        print(f"   {Symbols.OK} Dry-run mode available for safe analysis")
        print(f"   {Symbols.OK} Dependency-aware cleanup order")
        print(f"   {Symbols.OK} Comprehensive logging and reporting")
        print(f"   {Symbols.OK} Interactive account and region selection")
        
        print(f"\n{Symbols.STATS} Resource Protection Examples:")
        # Test protection logic
        test_cases = [
            ("Default VPC", {'IsDefault': True}, manager.is_default_vpc),
            ("Default Security Group", {'GroupName': 'default'}, manager.is_default_security_group),
            ("Main Route Table", {'Associations': [{'Main': True}]}, manager.is_main_route_table),
            ("Default Network ACL", {'IsDefault': True}, manager.is_default_network_acl)
        ]
        
        for name, test_resource, test_func in test_cases:
            is_protected = test_func(test_resource)
            status = f"{Symbols.PROTECTED} PROTECTED" if is_protected else f"{Symbols.DELETE} Would be deleted"
            print(f"   • {name}: {status}")
        
        print(f"\n{Symbols.TARGET} Usage Flow:")
        print(f"   1. Select operation mode (Dry Run or Actual Cleanup)")
        print(f"   2. Choose accounts to process")
        print(f"   3. Select regions to process")
        print(f"   4. Confirm the operation")
        print(f"   5. Process resources in dependency order")
        print(f"   6. Generate comprehensive reports")
        
        print(f"\n📄 Output Files:")
        print(f"   • Detailed logs: aws/vpc/logs/ultra_vpc_cleanup_TIMESTAMP.log")
        print(f"   • JSON reports: aws/vpc/logs/vpc_cleanup_report_TIMESTAMP.json")
        
        print(f"\n" + "=" * 80)
        print(f"[PARTY] Demo completed successfully!")
        print(f"The Ultra VPC Cleanup Manager is ready for use.")
        print(f"Run 'python3 ultra_cleanup_vpc.py' to start the interactive interface.")
        print(f"=" * 80)
        
    except Exception as e:
        print(f"{Symbols.ERROR} Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Clean up demo config file
        try:
            os.unlink(config_file)
        except:
            pass
    
    return True

if __name__ == "__main__":
    simulate_interactive_demo()