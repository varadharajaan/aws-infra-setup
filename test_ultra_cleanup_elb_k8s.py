#!/usr/bin/env python3

"""
Test script for Enhanced Kubernetes ELB Detection in Ultra ELB Cleanup Manager
Tests the new Kubernetes detection functionality without requiring AWS credentials
"""

import sys
import os
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import pytz

# Add the main directory to the path
sys.path.append('/home/runner/work/aws-infra-setup/aws-infra-setup')

def create_test_config():
    """Create a test configuration file"""
    test_config = {
        "accounts": {
            "test-k8s-account": {
                "account_id": "123456789012",
                "email": "test-k8s@example.com",
                "access_key": "AKIATEST1234567890",
                "secret_key": "test-secret-key-1234567890abcdef",
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

def test_kubernetes_tag_detection():
    """Test Kubernetes tag detection functionality"""
    print("🧪 Testing Kubernetes tag detection...")
    
    config_file = create_test_config()
    
    try:
        from ultra_cleanup_elb import UltraCleanupELBManager
        manager = UltraCleanupELBManager(config_file)
        
        # Test Case 1: kubernetes.io/cluster tag
        k8s_cluster_tags = {
            'kubernetes.io/cluster/my-eks-cluster': 'owned',
            'kubernetes.io/service-name': 'my-service',
            'Name': 'k8s-elb-test'
        }
        
        result = manager.check_kubernetes_tags(k8s_cluster_tags, 'test-elb')
        assert result['is_kubernetes'] == True
        assert result['cluster_name'] == 'my-eks-cluster'
        assert result['service_name'] == 'my-service'
        assert len(result['reasons']) >= 2
        print("  ✅ kubernetes.io/cluster tag detection works")
        
        # Test Case 2: KubernetesCluster tag
        k8s_cluster_simple_tags = {
            'KubernetesCluster': 'prod-cluster',
            'Environment': 'production'
        }
        
        result = manager.check_kubernetes_tags(k8s_cluster_simple_tags, 'test-elb')
        assert result['is_kubernetes'] == True
        assert result['cluster_name'] == 'prod-cluster'
        print("  ✅ KubernetesCluster tag detection works")
        
        # Test Case 3: No Kubernetes tags
        non_k8s_tags = {
            'Name': 'regular-elb',
            'Environment': 'production',
            'Owner': 'team-a'
        }
        
        result = manager.check_kubernetes_tags(non_k8s_tags, 'test-elb')
        assert result['is_kubernetes'] == False
        assert result['cluster_name'] is None
        print("  ✅ Non-Kubernetes tags correctly ignored")
        
        # Test Case 4: EKS in tag value
        eks_value_tags = {
            'Description': 'Load balancer for EKS cluster',
            'Team': 'kubernetes-team'
        }
        
        result = manager.check_kubernetes_tags(eks_value_tags, 'test-elb')
        assert result['is_kubernetes'] == True
        assert len(result['reasons']) >= 1
        print("  ✅ EKS/Kubernetes in tag values detected")
        
        print("✅ All Kubernetes tag detection tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        try:
            os.unlink(config_file)
        except:
            pass
    
    return True

def test_kubernetes_naming_patterns():
    """Test Kubernetes naming pattern detection"""
    print("\n🧪 Testing Kubernetes naming pattern detection...")
    
    config_file = create_test_config()
    
    try:
        from ultra_cleanup_elb import UltraCleanupELBManager
        manager = UltraCleanupELBManager(config_file)
        
        # Test Case 1: AWS-generated ELB name (starts with 'a')
        aws_generated_name = "a1b2c3d4e5f6g7h8-123456789"
        result = manager.check_kubernetes_naming_patterns(aws_generated_name)
        assert result['is_kubernetes_pattern'] == True
        assert result['pattern_type'] == 'aws_generated'
        print("  ✅ AWS-generated ELB name pattern detected")
        
        # Test Case 2: Name with kubernetes keyword
        k8s_name = "my-k8s-cluster-elb"
        result = manager.check_kubernetes_naming_patterns(k8s_name)
        assert result['is_kubernetes_pattern'] == True
        assert result['pattern_type'] == 'named_pattern'
        print("  ✅ Kubernetes keyword in name detected")
        
        # Test Case 3: EKS in name
        eks_name = "prod-eks-loadbalancer"
        result = manager.check_kubernetes_naming_patterns(eks_name)
        assert result['is_kubernetes_pattern'] == True
        assert result['pattern_type'] == 'named_pattern'
        print("  ✅ EKS keyword in name detected")
        
        # Test Case 4: DNS with kubernetes keyword
        regular_name = "prod-api-elb"
        k8s_dns = "k8s-api-server-123.us-east-1.elb.amazonaws.com"
        result = manager.check_kubernetes_naming_patterns(regular_name, k8s_dns)
        assert result['is_kubernetes_pattern'] == True
        assert result['pattern_type'] == 'dns_pattern'
        print("  ✅ Kubernetes keyword in DNS detected")
        
        # Test Case 5: Regular ELB name (should not match)
        regular_name = "production-api-load-balancer"
        result = manager.check_kubernetes_naming_patterns(regular_name)
        assert result['is_kubernetes_pattern'] == False
        print("  ✅ Regular ELB name correctly ignored")
        
        print("✅ All Kubernetes naming pattern tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        try:
            os.unlink(config_file)
        except:
            pass
    
    return True

def test_kubernetes_elb_detection_integration():
    """Test the integrated Kubernetes ELB detection"""
    print("\n🧪 Testing integrated Kubernetes ELB detection...")
    
    config_file = create_test_config()
    
    try:
        from ultra_cleanup_elb import UltraCleanupELBManager
        manager = UltraCleanupELBManager(config_file)
        
        # Mock AWS clients
        mock_elb_client = Mock()
        mock_elbv2_client = Mock()
        mock_ec2_client = Mock()
        
        # Test Case 1: Kubernetes ELB with cluster tag
        k8s_lb_info = {
            'name': 'a1b2c3d4e5f6g7h8-123456789',
            'type': 'classic',
            'dns_name': 'a1b2c3d4e5f6g7h8-123456789.us-east-1.elb.amazonaws.com',
            'vpc_id': 'vpc-12345678',
            'region': 'us-east-1'
        }
        
        # Mock the get_elb_tags method response
        with patch.object(manager, 'get_elb_tags') as mock_get_tags:
            mock_get_tags.return_value = {
                'kubernetes.io/cluster/prod-cluster': 'owned',
                'kubernetes.io/service-name': 'api-service'
            }
            
            # Mock the orphan check
            with patch.object(manager, 'is_orphaned_kubernetes_elb') as mock_orphan_check:
                mock_orphan_check.return_value = {
                    'is_orphaned': False,
                    'confidence': 'low',
                    'reasons': []
                }
                
                result = manager.is_kubernetes_load_balancer(
                    mock_elb_client, mock_elbv2_client, mock_ec2_client, k8s_lb_info
                )
                
                assert result['is_kubernetes'] == True
                assert result['confidence'] == 'high'
                assert 'tags' in result['detection_methods']
                assert 'naming_pattern' in result['detection_methods']
                assert result['cluster_name'] == 'prod-cluster'
                assert result['service_name'] == 'api-service'
                assert result['is_orphaned'] == False
                
                print("  ✅ Kubernetes ELB with tags and AWS-generated name detected")
        
        # Test Case 2: Non-Kubernetes ELB
        regular_lb_info = {
            'name': 'production-api-elb',
            'type': 'application',
            'dns_name': 'production-api-elb-123456789.us-east-1.elb.amazonaws.com',
            'vpc_id': 'vpc-87654321',
            'region': 'us-east-1',
            'arn': 'arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/production-api-elb/1234567890123456'
        }
        
        with patch.object(manager, 'get_elb_tags') as mock_get_tags:
            mock_get_tags.return_value = {
                'Name': 'production-api-elb',
                'Environment': 'production',
                'Team': 'backend'
            }
            
            result = manager.is_kubernetes_load_balancer(
                mock_elb_client, mock_elbv2_client, mock_ec2_client, regular_lb_info
            )
            
            assert result['is_kubernetes'] == False
            assert result['confidence'] == 'low'
            assert result['cluster_name'] is None
            assert result['service_name'] is None
            
            print("  ✅ Non-Kubernetes ELB correctly identified")
        
        print("✅ All integrated Kubernetes ELB detection tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        try:
            os.unlink(config_file)
        except:
            pass
    
    return True

def test_enhanced_load_balancer_discovery():
    """Test the enhanced load balancer discovery with Kubernetes detection"""
    print("\n🧪 Testing enhanced load balancer discovery...")
    
    config_file = create_test_config()
    
    try:
        from ultra_cleanup_elb import UltraCleanupELBManager
        manager = UltraCleanupELBManager(config_file)
        
        # Mock AWS clients
        mock_elb_client = Mock()
        mock_elbv2_client = Mock()
        
        account_info = {
            'account_key': 'test-k8s-account',
            'access_key': 'test-key',
            'secret_key': 'test-secret'
        }
        
        # Mock Classic ELB response
        mock_elb_client.get_paginator.return_value.paginate.return_value = [
            {
                'LoadBalancerDescriptions': [
                    {
                        'LoadBalancerName': 'a1b2c3d4e5f6g7h8-123456789',
                        'DNSName': 'a1b2c3d4e5f6g7h8-123456789.us-east-1.elb.amazonaws.com',
                        'Scheme': 'internet-facing',
                        'VpcId': 'vpc-12345678',
                        'SecurityGroups': ['sg-12345678'],
                        'Subnets': ['subnet-12345678'],
                        'AvailabilityZones': [{'ZoneName': 'us-east-1a'}],
                        'CreatedTime': datetime.now(pytz.UTC)
                    }
                ]
            }
        ]
        
        # Mock ALB/NLB response
        mock_elbv2_client.get_paginator.return_value.paginate.return_value = [
            {
                'LoadBalancers': [
                    {
                        'LoadBalancerArn': 'arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/production-api/1234567890123456',
                        'LoadBalancerName': 'production-api',
                        'Type': 'application',
                        'DNSName': 'production-api-123456789.us-east-1.elb.amazonaws.com',
                        'Scheme': 'internet-facing',
                        'VpcId': 'vpc-87654321',
                        'SecurityGroups': ['sg-87654321'],
                        'AvailabilityZones': [{'SubnetId': 'subnet-87654321', 'ZoneName': 'us-east-1a'}],
                        'CreatedTime': datetime.now(pytz.UTC)
                    }
                ]
            }
        ]
        
        # Mock the create_aws_clients method
        with patch.object(manager, 'create_aws_clients') as mock_create_clients:
            mock_ec2_client = Mock()
            mock_create_clients.return_value = (mock_ec2_client, mock_elb_client, mock_elbv2_client)
            
            # Mock the Kubernetes detection
            with patch.object(manager, 'is_kubernetes_load_balancer') as mock_k8s_detection:
                # First call (Classic ELB) - Kubernetes
                # Second call (ALB) - Non-Kubernetes
                mock_k8s_detection.side_effect = [
                    {
                        'is_kubernetes': True,
                        'confidence': 'high',
                        'cluster_name': 'prod-cluster',
                        'service_name': 'api-service',
                        'is_orphaned': False,
                        'detection_methods': ['tags', 'naming_pattern'],
                        'reasons': ['AWS-generated ELB name pattern', 'Found kubernetes.io/cluster tag']
                    },
                    {
                        'is_kubernetes': False,
                        'confidence': 'low',
                        'cluster_name': None,
                        'service_name': None,
                        'is_orphaned': False,
                        'detection_methods': [],
                        'reasons': []
                    }
                ]
                
                load_balancers = manager.get_all_load_balancers_in_region(
                    mock_elb_client, mock_elbv2_client, 'us-east-1', account_info
                )
                
                # Verify results
                assert len(load_balancers) == 2
                
                # Check Kubernetes ELB
                k8s_elb = load_balancers[0]
                assert k8s_elb['name'] == 'a1b2c3d4e5f6g7h8-123456789'
                assert k8s_elb['kubernetes']['is_kubernetes'] == True
                assert k8s_elb['kubernetes']['cluster_name'] == 'prod-cluster'
                
                # Check non-Kubernetes ELB
                regular_elb = load_balancers[1]
                assert regular_elb['name'] == 'production-api'
                assert regular_elb['kubernetes']['is_kubernetes'] == False
                
                print("  ✅ Enhanced load balancer discovery correctly categorizes K8s and non-K8s ELBs")
        
        print("✅ All enhanced load balancer discovery tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
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
    """Run all Kubernetes ELB detection tests"""
    print("🚀 Starting Enhanced Kubernetes ELB Detection Tests")
    print("=" * 80)
    
    success = True
    
    # Test Kubernetes tag detection
    if not test_kubernetes_tag_detection():
        success = False
    
    # Test Kubernetes naming patterns
    if not test_kubernetes_naming_patterns():
        success = False
    
    # Test integrated Kubernetes ELB detection
    if not test_kubernetes_elb_detection_integration():
        success = False
    
    # Test enhanced load balancer discovery
    if not test_enhanced_load_balancer_discovery():
        success = False
    
    print("\n" + "=" * 80)
    if success:
        print("🎉 ALL KUBERNETES ELB DETECTION TESTS PASSED!")
        print("✅ Enhanced functionality working correctly:")
        print("   • Kubernetes tag detection (kubernetes.io/cluster, service-name, etc.)")
        print("   • AWS-generated name pattern detection (starts with 'a')")
        print("   • Kubernetes keyword detection in names and DNS")
        print("   • Integrated ELB classification (K8s vs non-K8s)")
        print("   • Enhanced load balancer discovery with categorization")
        print("   • Improved logging and reporting")
    else:
        print("❌ SOME KUBERNETES ELB DETECTION TESTS FAILED!")
        print("Please check the implementation.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())