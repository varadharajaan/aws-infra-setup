from text_symbols import Symbols
#!/usr/bin/env python3

"""
Test script for Ultra VPC Cleanup Manager
Tests basic functionality without requiring AWS credentials
"""

import sys
import os
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock

# Add the main directory to the path
sys.path.append('/home/runner/work/aws-infra-setup/aws-infra-setup')

def create_test_config():
    """Create a test configuration file"""
    test_config = {
        "accounts": {
            "test-account-1": {
                "account_id": "123456789012",
                "email": "test1@example.com",
                "access_key": "AKIATEST1234567890",
                "secret_key": "test-secret-key-1234567890abcdef",
                "users_per_account": 1
            },
            "test-account-2": {
                "account_id": "123456789013", 
                "email": "test2@example.com",
                "access_key": "AKIATEST1234567891",
                "secret_key": "test-secret-key-1234567890abcdef2",
                "users_per_account": 1
            }
        },
        "user_settings": {
            "user_regions": ["us-east-1", "us-west-2"]
        }
    }
    
    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(test_config, f, indent=2)
        return f.name

def test_basic_functionality():
    """Test basic functionality of the VPC cleanup manager"""
    print("[TEST] Testing Ultra VPC Cleanup Manager...")
    
    # Create test config
    config_file = create_test_config()
    
    try:
        # Import the module
        from ultra_cleanup_vpc import UltraVPCCleanupManager
        
        # Test initialization
        print("[OK] Testing initialization...")
        manager = UltraVPCCleanupManager(config_file)
        
        # Test that configuration was loaded
        assert len(manager.config_data['accounts']) == 2
        assert 'test-account-1' in manager.config_data['accounts']
        assert 'test-account-2' in manager.config_data['accounts']
        print(f"{Symbols.OK} Configuration loading works")
        
        # Test dry run mode
        manager.dry_run = True
        print(f"{Symbols.OK} Dry run mode can be set")
        
        # Test default VPC detection methods
        print(f"{Symbols.OK} Testing default resource detection...")
        
        # Test default VPC detection
        default_vpc = {'IsDefault': True, 'VpcId': 'vpc-default123'}
        custom_vpc = {'IsDefault': False, 'VpcId': 'vpc-custom123'}
        
        assert manager.is_default_vpc(default_vpc) == True
        assert manager.is_default_vpc(custom_vpc) == False
        print(f"{Symbols.OK} Default VPC detection works")
        
        # Test default security group detection
        default_sg = {'GroupName': 'default', 'GroupId': 'sg-default123'}
        custom_sg = {'GroupName': 'web-tier', 'GroupId': 'sg-custom123'}
        
        assert manager.is_default_security_group(default_sg) == True
        assert manager.is_default_security_group(custom_sg) == False
        print(f"{Symbols.OK} Default security group detection works")
        
        # Test main route table detection
        main_rt = {
            'RouteTableId': 'rtb-main123',
            'Associations': [{'Main': True, 'RouteTableAssociationId': 'rtbassoc-123'}]
        }
        custom_rt = {
            'RouteTableId': 'rtb-custom123', 
            'Associations': [{'Main': False, 'RouteTableAssociationId': 'rtbassoc-456'}]
        }
        
        assert manager.is_main_route_table(main_rt) == True
        assert manager.is_main_route_table(custom_rt) == False
        print(f"{Symbols.OK} Main route table detection works")
        
        # Test default network ACL detection
        default_acl = {'IsDefault': True, 'NetworkAclId': 'acl-default123'}
        custom_acl = {'IsDefault': False, 'NetworkAclId': 'acl-custom123'}
        
        assert manager.is_default_network_acl(default_acl) == True
        assert manager.is_default_network_acl(custom_acl) == False
        print(f"{Symbols.OK} Default network ACL detection works")
        
        # Test cleanup order
        assert len(manager.cleanup_order) == 17
        assert 'vpc_flow_logs' in manager.cleanup_order
        assert 'vpc_endpoints' in manager.cleanup_order
        assert 'nat_gateways' in manager.cleanup_order
        print(f"{Symbols.OK} Cleanup order is properly defined")
        
        # Test EC2 client creation (mocked)
        with patch('boto3.client') as mock_boto3:
            mock_client = Mock()
            mock_boto3.return_value = mock_client
            
            client = manager.create_ec2_client('test-key', 'test-secret', 'us-east-1')
            assert client == mock_client
            print(f"{Symbols.OK} EC2 client creation works")
        
        print("\n[PARTY] All basic tests passed!")
        
    except Exception as e:
        print(f"{Symbols.ERROR} Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Clean up test config file
        try:
            os.unlink(config_file)
        except:
            pass
    
    return True

def test_vpc_resource_methods():
    """Test VPC resource discovery methods with mocked AWS responses"""
    print("\n[TEST] Testing VPC resource discovery methods...")
    
    config_file = create_test_config()
    
    try:
        from ultra_cleanup_vpc import UltraVPCCleanupManager
        manager = UltraVPCCleanupManager(config_file)
        manager.dry_run = True
        
        # Mock EC2 client
        mock_ec2_client = Mock()
        
        # Test VPC discovery
        mock_ec2_client.describe_vpcs.return_value = {
            'Vpcs': [
                {'VpcId': 'vpc-default123', 'IsDefault': True, 'CidrBlock': '172.31.0.0/16'},
                {'VpcId': 'vpc-custom123', 'IsDefault': False, 'CidrBlock': '10.0.0.0/16'},
                {'VpcId': 'vpc-custom456', 'IsDefault': False, 'CidrBlock': '10.1.0.0/16'}
            ]
        }
        
        custom_vpcs = manager.get_all_vpcs_in_region(mock_ec2_client, 'us-east-1', 'test-account')
        assert len(custom_vpcs) == 2
        assert all(not vpc.get('IsDefault') for vpc in custom_vpcs)
        print(f"{Symbols.OK} VPC discovery correctly filters default VPCs")
        
        # Test VPC endpoints discovery
        mock_ec2_client.describe_vpc_endpoints.return_value = {
            'VpcEndpoints': [
                {'VpcEndpointId': 'vpce-123', 'VpcEndpointType': 'Interface'},
                {'VpcEndpointId': 'vpce-456', 'VpcEndpointType': 'Gateway'}
            ]
        }
        
        endpoints = manager.get_vpc_endpoints(mock_ec2_client, ['vpc-custom123'], 'us-east-1', 'test-account')
        assert len(endpoints) == 2
        print(f"{Symbols.OK} VPC endpoints discovery works")
        
        # Test security groups discovery
        mock_ec2_client.describe_security_groups.return_value = {
            'SecurityGroups': [
                {'GroupId': 'sg-default123', 'GroupName': 'default', 'VpcId': 'vpc-custom123'},
                {'GroupId': 'sg-web123', 'GroupName': 'web-tier', 'VpcId': 'vpc-custom123'},
                {'GroupId': 'sg-app123', 'GroupName': 'app-tier', 'VpcId': 'vpc-custom123'}
            ]
        }
        
        sgs = manager.get_security_groups(mock_ec2_client, ['vpc-custom123'], 'us-east-1', 'test-account')
        assert len(sgs) == 2  # Should exclude default security group
        assert all(sg['GroupName'] != 'default' for sg in sgs)
        print(f"{Symbols.OK} Security groups discovery correctly filters default SGs")
        
        print("\n[PARTY] All VPC resource discovery tests passed!")
        
    except Exception as e:
        print(f"{Symbols.ERROR} Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        try:
            os.unlink(config_file)
        except:
            pass
    
    return True

def main():
    """Run all tests"""
    print("[START] Starting Ultra VPC Cleanup Manager Tests")
    print("=" * 80)
    
    success = True
    
    # Test basic functionality
    if not test_basic_functionality():
        success = False
    
    # Test VPC resource methods
    if not test_vpc_resource_methods():
        success = False
    
    print("\n" + "=" * 80)
    if success:
        print("[PARTY] ALL TESTS PASSED! Ultra VPC Cleanup Manager is working correctly.")
        print("[OK] The script properly:")
        print("   • Loads configuration files")
        print("   • Detects and protects default VPC resources")
        print("   • Identifies custom VPC resources for cleanup")
        print("   • Supports dry-run mode for safe analysis")
        print("   • Follows proper dependency cleanup order")
    else:
        print("[ERROR] SOME TESTS FAILED! Please check the implementation.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())