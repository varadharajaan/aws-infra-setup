#!/usr/bin/env python3
"""
Lambda Node Protection Monitor with integrated credential management
"""

import json
import os
import sys
import boto3
from datetime import datetime
import logging

# Import the credential management from continue_cluster_setup
from continue_cluster_setup import EKSClusterContinuationFromErrors


class LambdaNodeProtectionMonitor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.continuation_helper = EKSClusterContinuationFromErrors()

    def run_local_test(self, cluster_name: str):
        """
        Run local test using automatic credential detection from cluster name

        Args:
            cluster_name: EKS cluster name (e.g., 'eks-cluster-account01_clouduser01-us-east-1-igku')
        """
        try:
            print(f"🚀 Running Local Test for Cluster: {cluster_name}")
            print("=" * 60)

            # Extract region from cluster name
            region = self.continuation_helper._extract_region_from_cluster_name(cluster_name)
            if not region:
                print("⚠️ Could not extract region from cluster name")
                region = input("Enter AWS region: ").strip()
                if not region:
                    raise ValueError("Region is required")

            print(f"🌍 Detected region: {region}")

            # Get credentials automatically based on cluster name pattern
            print("🔐 Retrieving credentials...")

            try:
                # Try IAM credentials first
                access_key, secret_key, account_id = self.continuation_helper.get_iam_credentials_from_cluster(
                    cluster_name, region
                )
                credential_type = "IAM"
                print(f"✅ Found IAM credentials")

            except Exception as e:
                print(f"⚠️ IAM credentials failed: {str(e)}")
                print("🔄 Trying root credentials...")

                try:
                    # Fallback to root credentials
                    access_key, secret_key, account_id = self.continuation_helper.get_root_credentials(
                        cluster_name, region
                    )
                    credential_type = "Root"
                    print(f"✅ Found root credentials")

                except Exception as e2:
                    raise ValueError(f"Could not get any credentials. IAM: {str(e)}, Root: {str(e2)}")

            # Display credential info
            print(f"📋 Credential Details:")
            print(f"   • Type: {credential_type}")
            print(f"   • Account ID: {account_id}")
            print(f"   • Region: {region}")
            print(f"   • Access Key: {access_key[:8]}...")

            # Verify cluster access
            print("\n🔍 Verifying cluster access...")
            if not self.continuation_helper.verify_cluster_exists(cluster_name, region, access_key, secret_key):
                raise ValueError(f"Cannot access cluster {cluster_name}")

            print(f"✅ Cluster {cluster_name} is accessible")

            # Run your actual Lambda protection monitoring logic here
            result = self.run_protection_monitor_logic(cluster_name, region, access_key, secret_key, account_id)

            print(f"\n🎉 Local test completed successfully!")
            return result

        except Exception as e:
            print(f"❌ Local test failed: {str(e)}")
            raise

    def run_protection_monitor_logic(self, cluster_name: str, region: str, access_key: str,
                                     secret_key: str, account_id: str):
        """
        Your actual Lambda protection monitoring logic
        """
        print("\n🛡️ Running Protection Monitor Logic...")

        # Create AWS session
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )

        eks_client = session.client('eks')
        ec2_client = session.client('ec2')

        # Example: Check node protection status
        try:
            # Get nodegroups
            nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
            nodegroups = nodegroups_response.get('nodegroups', [])

            print(f"📦 Found {len(nodegroups)} nodegroups:")

            for ng_name in nodegroups:
                print(f"   • {ng_name}")

                # Get nodegroup details
                ng_response = eks_client.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=ng_name
                )

                nodegroup = ng_response['nodegroup']
                print(f"     Status: {nodegroup['status']}")
                print(f"     Capacity: {nodegroup.get('capacityType', 'ON_DEMAND')}")

                # Check if nodes have NO_DELETE protection
                # Add your specific protection monitoring logic here

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Protection monitor completed for {cluster_name}',
                    'cluster_name': cluster_name,
                    'region': region,
                    'nodegroups_checked': len(nodegroups),
                    'timestamp': datetime.now().isoformat()
                })
            }

        except Exception as e:
            print(f"❌ Protection monitor logic failed: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': str(e),
                    'cluster_name': cluster_name,
                    'timestamp': datetime.now().isoformat()
                })
            }


def main():
    """Main function for local testing"""
    if len(sys.argv) != 2:
        print("Usage: python lambda_note_protection_monitor.py <cluster_name>")
        print("Example: python lambda_note_protection_monitor.py eks-cluster-account01_clouduser01-us-east-1-igku")
        sys.exit(1)

    cluster_name = sys.argv[1]

    monitor = LambdaNodeProtectionMonitor()
    try:
        result = monitor.run_local_test(cluster_name)
        print(f"\n📊 Result: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"\n💥 Test failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()