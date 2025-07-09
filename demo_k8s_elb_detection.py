#!/usr/bin/env python3

"""
Demonstration script for Enhanced Kubernetes ELB Detection
Shows the new functionality without requiring AWS credentials
"""

import sys
import os
from unittest.mock import Mock
from datetime import datetime
import pytz

# Add the main directory to the path
sys.path.append('/home/runner/work/aws-infra-setup/aws-infra-setup')

def demo_kubernetes_detection():
    """Demonstrate the Kubernetes ELB detection capabilities"""
    print("🚀 Enhanced Kubernetes ELB Detection Demo")
    print("=" * 60)
    
    try:
        from ultra_cleanup_elb import UltraCleanupELBManager
        
        # Mock a minimal manager for demonstration
        manager = UltraCleanupELBManager.__new__(UltraCleanupELBManager)
        manager.log_operation = lambda level, msg: print(f"[{level}] {msg}")
        
        print("\n🔍 1. Kubernetes Tag Detection Examples")
        print("-" * 40)
        
        # Example 1: Kubernetes cluster tag
        k8s_tags = {
            'kubernetes.io/cluster/prod-cluster': 'owned',
            'kubernetes.io/service-name': 'api-gateway',
            'Name': 'k8s-api-elb'
        }
        
        result = manager.check_kubernetes_tags(k8s_tags, 'a1b2c3d4e5f6g7h8-123456789')
        print(f"📋 Tags: {k8s_tags}")
        print(f"✅ Kubernetes detected: {result['is_kubernetes']}")
        print(f"🏷️  Cluster: {result['cluster_name']}")
        print(f"🔗 Service: {result['service_name']}")
        print(f"📝 Reasons: {result['reasons']}")
        
        print("\n🏷️  2. Naming Pattern Detection Examples")
        print("-" * 40)
        
        # AWS-generated name
        aws_name = "a1b2c3d4e5f6g7h8-123456789"
        result = manager.check_kubernetes_naming_patterns(aws_name)
        print(f"📛 ELB Name: {aws_name}")
        print(f"✅ Kubernetes pattern: {result['is_kubernetes_pattern']}")
        print(f"🔍 Pattern type: {result['pattern_type']}")
        print(f"📝 Reasons: {result['reasons']}")
        
        # Kubernetes keyword in name
        k8s_name = "prod-k8s-cluster-elb"
        result = manager.check_kubernetes_naming_patterns(k8s_name)
        print(f"\n📛 ELB Name: {k8s_name}")
        print(f"✅ Kubernetes pattern: {result['is_kubernetes_pattern']}")
        print(f"🔍 Pattern type: {result['pattern_type']}")
        print(f"📝 Reasons: {result['reasons']}")
        
        print("\n🧩 3. Integrated Detection Example")
        print("-" * 40)
        
        # Mock ELB info for integrated detection
        k8s_elb_info = {
            'name': 'a1b2c3d4e5f6g7h8-123456789',
            'type': 'classic',
            'dns_name': 'a1b2c3d4e5f6g7h8-123456789.us-east-1.elb.amazonaws.com',
            'vpc_id': 'vpc-12345678',
            'region': 'us-east-1'
        }
        
        # Mock the helper methods for demonstration
        manager.get_elb_tags = Mock(return_value=k8s_tags)
        manager.is_orphaned_kubernetes_elb = Mock(return_value={
            'is_orphaned': False,
            'confidence': 'low',
            'reasons': []
        })
        
        result = manager.is_kubernetes_load_balancer(
            Mock(), Mock(), Mock(), k8s_elb_info
        )
        
        print(f"📛 ELB: {k8s_elb_info['name']}")
        print(f"✅ Is Kubernetes: {result['is_kubernetes']}")
        print(f"🎯 Confidence: {result['confidence']}")
        print(f"🔬 Detection methods: {result['detection_methods']}")
        print(f"🏷️  Cluster: {result['cluster_name']}")
        print(f"🔗 Service: {result['service_name']}")
        print(f"🧹 Is orphaned: {result['is_orphaned']}")
        
        print("\n📊 4. Enhanced Reporting Breakdown")
        print("-" * 40)
        
        # Example load balancer data
        sample_lbs = [
            {
                'name': 'a1b2c3d4e5f6g7h8-123456789',
                'type': 'classic',
                'kubernetes': {
                    'is_kubernetes': True,
                    'cluster_name': 'prod-cluster',
                    'service_name': 'api-gateway',
                    'is_orphaned': False,
                    'confidence': 'high'
                }
            },
            {
                'name': 'a9f8e7d6c5b4a3b2-987654321',
                'type': 'classic',
                'kubernetes': {
                    'is_kubernetes': True,
                    'cluster_name': 'staging-cluster',
                    'service_name': 'web-service',
                    'is_orphaned': True,
                    'confidence': 'high'
                }
            },
            {
                'name': 'production-api-elb',
                'type': 'application',
                'kubernetes': {
                    'is_kubernetes': False,
                    'confidence': 'low'
                }
            }
        ]
        
        k8s_count = sum(1 for lb in sample_lbs if lb['kubernetes']['is_kubernetes'])
        non_k8s_count = len(sample_lbs) - k8s_count
        orphaned_count = sum(1 for lb in sample_lbs if lb['kubernetes'].get('is_orphaned', False))
        
        print(f"📈 Total ELBs discovered: {len(sample_lbs)}")
        print(f"🚢 Kubernetes ELBs: {k8s_count}")
        print(f"🏢 Non-Kubernetes ELBs: {non_k8s_count}")
        print(f"🧹 Orphaned Kubernetes ELBs: {orphaned_count}")
        
        print("\n🚢 Kubernetes ELB Details:")
        for lb in sample_lbs:
            if lb['kubernetes']['is_kubernetes']:
                k8s_info = lb['kubernetes']
                cluster_info = f" (cluster: {k8s_info['cluster_name']})" if k8s_info.get('cluster_name') else ""
                service_info = f" (service: {k8s_info['service_name']})" if k8s_info.get('service_name') else ""
                orphan_info = " [ORPHANED]" if k8s_info.get('is_orphaned') else ""
                
                print(f"    • {lb['name']} ({lb['type']}) - confidence: {k8s_info['confidence']}{cluster_info}{service_info}{orphan_info}")
        
        print("\n✅ Enhanced Kubernetes ELB Detection Features:")
        print("   🏷️  Tag-based detection (kubernetes.io/cluster, service-name, etc.)")
        print("   📛 AWS-generated name pattern detection")
        print("   🔍 Keyword detection in names and DNS")
        print("   🧹 Orphaned resource detection")
        print("   📊 Enhanced categorization and reporting")
        print("   🛡️  Improved error handling with Kubernetes context")
        print("   📝 Detailed logging and confidence scoring")
        
        print(f"\n🎉 Demo completed successfully!")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    demo_kubernetes_detection()