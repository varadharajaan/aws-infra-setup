#!/usr/bin/env python3
"""
Lambda Node Protection Monitor with integrated credential management
Ensures only ONE instance across ALL nodegroups has NO_DELETE protection
Template version with injectable parameters
Generated on: {{current_date}} {{current_time}} UTC
Created by: {{current_user}}
"""

import json
import os
import sys
import boto3
from datetime import datetime
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


class LambdaNodeProtectionMonitor:
    def __init__(self):
        self.logger = logger

    def extract_region_from_cluster_name(self, cluster_name):
        """Extract region from cluster name pattern"""
        try:
            # Pattern: eks-cluster-account01_clouduser01-us-east-1-wxie
            parts = cluster_name.split('-')
            if len(parts) >= 6:
                # Look for region pattern (us-east-1, us-west-2, etc.)
                for i in range(len(parts) - 2):
                    if i + 2 < len(parts):
                        potential_region = f"{parts[i]}-{parts[i + 1]}-{parts[i + 2]}"
                        if potential_region.startswith(('us-', 'eu-', 'ap-', 'ca-', 'sa-', 'af-', 'me-')):
                            return potential_region
            return None
        except Exception as e:
            self.logger.error(f"Error extracting region: {str(e)}")
            return None

    def run_protection_monitor_logic(self, cluster_name: str, region: str, access_key: str = None,
                                     secret_key: str = None):
        """
        Lambda protection monitoring logic - applies NO_DELETE protection to only ONE instance across ALL nodegroups
        """
        self.logger.info(f"🛡️ Running Protection Monitor for cluster: {cluster_name} in region: {region}")

        try:
            # Create AWS clients using provided credentials or Lambda's execution role
            if access_key and secret_key:
                self.logger.info("Using provided AWS credentials")
                session = boto3.Session(
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name=region
                )
                eks_client = session.client('eks')
                ec2_client = session.client('ec2')
                autoscaling_client = session.client('autoscaling')
            else:
                self.logger.info("Using Lambda execution role credentials")
                eks_client = boto3.client('eks', region_name=region)
                ec2_client = boto3.client('ec2', region_name=region)
                autoscaling_client = boto3.client('autoscaling', region_name=region)

            results = {}
            all_protected_instances = []
            all_unprotected_instances = []

            # Get nodegroups
            self.logger.info(f"Getting nodegroups for cluster: {cluster_name}")
            nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
            nodegroups = nodegroups_response.get('nodegroups', [])

            self.logger.info(f"📦 Found {len(nodegroups)} nodegroups: {nodegroups}")

            # PHASE 1: Collect all instances and check current protection status
            for ng_name in nodegroups:
                self.logger.info(f"🔍 Scanning nodegroup: {ng_name}")

                try:
                    # Get nodegroup details
                    ng_response = eks_client.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=ng_name
                    )

                    nodegroup = ng_response['nodegroup']
                    self.logger.info(f"   Status: {nodegroup['status']}")
                    self.logger.info(f"   Capacity: {nodegroup.get('capacityType', 'ON_DEMAND')}")

                    # Get Auto Scaling Group details
                    asg_name = None
                    if 'resources' in nodegroup and 'autoScalingGroups' in nodegroup['resources']:
                        asg_list = nodegroup['resources']['autoScalingGroups']
                        if asg_list:
                            asg_name = asg_list[0]['name']

                    if not asg_name:
                        self.logger.warning(f"   ⚠️ No ASG found for {ng_name}")
                        results[ng_name] = {'status': 'warning', 'message': 'No ASG found'}
                        continue

                    self.logger.info(f"   ASG: {asg_name}")

                    # Get instances in ASG
                    asg_response = autoscaling_client.describe_auto_scaling_groups(
                        AutoScalingGroupNames=[asg_name]
                    )

                    if not asg_response['AutoScalingGroups']:
                        self.logger.warning(f"   ⚠️ ASG {asg_name} not found")
                        results[ng_name] = {'status': 'warning', 'message': f'ASG {asg_name} not found'}
                        continue

                    asg = asg_response['AutoScalingGroups'][0]
                    instances = [i for i in asg.get('Instances', []) if i['LifecycleState'] == 'InService']

                    if not instances:
                        self.logger.warning(f"   ⚠️ No instances in service for {ng_name}")
                        results[ng_name] = {'status': 'warning', 'message': 'No instances in service'}
                        continue

                    self.logger.info(f"   📊 Found {len(instances)} instances in service")

                    # Check protection status for each instance
                    ng_protected_instances = []
                    ng_unprotected_instances = []

                    for instance in instances:
                        instance_id = instance['InstanceId']

                        try:
                            instance_response = ec2_client.describe_instances(InstanceIds=[instance_id])
                            if not instance_response['Reservations']:
                                continue

                            instance_data = instance_response['Reservations'][0]['Instances'][0]
                            tags = instance_data.get('Tags', [])

                            # Check for NO_DELETE protection tag
                            has_protection = any(
                                tag['Key'] == 'kubernetes.io/cluster-autoscaler/node-template/label/protection'
                                and tag['Value'] == 'NO_DELETE'
                                for tag in tags
                            )

                            instance_info = {
                                'instance_id': instance_id,
                                'nodegroup': ng_name,
                                'asg': asg_name
                            }

                            if has_protection:
                                ng_protected_instances.append(instance_id)
                                all_protected_instances.append(instance_info)
                                self.logger.info(f"   ✅ {instance_id}: Protected")
                            else:
                                ng_unprotected_instances.append(instance_id)
                                all_unprotected_instances.append(instance_info)
                                self.logger.info(f"   🔓 {instance_id}: Not protected")

                        except Exception as e:
                            self.logger.error(f"   ❌ Error checking {instance_id}: {str(e)}")

                    # Store nodegroup results (for now, just scanning)
                    results[ng_name] = {
                        'status': 'scanned',
                        'total_instances': len(instances),
                        'protected_instances': ng_protected_instances,
                        'unprotected_instances': ng_unprotected_instances
                    }

                except Exception as e:
                    self.logger.error(f"   ❌ Error processing {ng_name}: {str(e)}")
                    results[ng_name] = {
                        'status': 'error',
                        'message': f'Failed to process: {str(e)}'
                    }

            # PHASE 2: Apply protection logic across ALL nodegroups
            self.logger.info(f"📊 CLUSTER SUMMARY:")
            self.logger.info(f"   Total protected instances across all nodegroups: {len(all_protected_instances)}")
            self.logger.info(f"   Total unprotected instances across all nodegroups: {len(all_unprotected_instances)}")

            if len(all_protected_instances) == 0 and len(all_unprotected_instances) > 0:
                # No protection exists, apply to first available instance
                target_instance = all_unprotected_instances[0]
                instance_id = target_instance['instance_id']
                target_ng = target_instance['nodegroup']

                self.logger.info(f"🛡️ APPLYING NO_DELETE protection to {instance_id} in nodegroup {target_ng}")

                try:
                    ec2_client.create_tags(
                        Resources=[instance_id],
                        Tags=[
                            {
                                'Key': 'kubernetes.io/cluster-autoscaler/node-template/label/protection',
                                'Value': 'NO_DELETE'
                            }
                        ]
                    )
                    self.logger.info(f"✅ Protection applied successfully to {instance_id}")

                    # Update results
                    results[target_ng]['status'] = 'success'
                    results[target_ng]['message'] = f'Applied protection to {instance_id}'
                    results[target_ng]['action_taken'] = 'protection_applied'
                    results[target_ng]['protected_instance'] = instance_id

                except Exception as e:
                    self.logger.error(f"❌ Failed to apply protection: {str(e)}")
                    results[target_ng]['status'] = 'error'
                    results[target_ng]['message'] = f'Failed to apply protection: {str(e)}'

            elif len(all_protected_instances) == 1:
                # Exactly one instance is protected - perfect!
                protected_instance = all_protected_instances[0]
                target_ng = protected_instance['nodegroup']

                self.logger.info(
                    f"✅ PERFECT: Exactly one instance {protected_instance['instance_id']} is protected in nodegroup {target_ng}")
                results[target_ng]['status'] = 'success'
                results[target_ng]['message'] = f'Exactly one instance protected: {protected_instance["instance_id"]}'
                results[target_ng]['action_taken'] = 'no_action_needed'

            elif len(all_protected_instances) > 1:
                # Multiple instances are protected - remove protection from all but one
                keep_instance = all_protected_instances[0]  # Keep the first one
                remove_instances = all_protected_instances[1:]  # Remove protection from the rest

                self.logger.info(
                    f"⚠️ TOO MANY protected instances ({len(all_protected_instances)}). Keeping {keep_instance['instance_id']}, removing protection from {len(remove_instances)} others")

                for instance_info in remove_instances:
                    instance_id = instance_info['instance_id']
                    ng_name = instance_info['nodegroup']

                    try:
                        # Remove the protection tag
                        ec2_client.delete_tags(
                            Resources=[instance_id],
                            Tags=[
                                {
                                    'Key': 'kubernetes.io/cluster-autoscaler/node-template/label/protection',
                                    'Value': 'NO_DELETE'
                                }
                            ]
                        )
                        self.logger.info(f"🔓 Removed protection from {instance_id} in nodegroup {ng_name}")

                        results[ng_name]['status'] = 'success'
                        results[ng_name]['message'] = f'Removed excess protection from {instance_id}'
                        results[ng_name]['action_taken'] = 'protection_removed'

                    except Exception as e:
                        self.logger.error(f"❌ Failed to remove protection from {instance_id}: {str(e)}")
                        results[ng_name]['status'] = 'error'
                        results[ng_name]['message'] = f'Failed to remove protection: {str(e)}'

                # Update the kept instance's nodegroup
                keep_ng = keep_instance['nodegroup']
                if results[keep_ng]['status'] != 'error':  # Don't overwrite error status
                    results[keep_ng]['status'] = 'success'
                    results[keep_ng]['message'] = f'Kept protection on {keep_instance["instance_id"]}'
                    results[keep_ng]['action_taken'] = 'protection_kept'

            else:
                # No instances available
                self.logger.warning("⚠️ No instances available for protection")

            # Update final status for nodegroups that were only scanned
            for ng_name, result in results.items():
                if result.get('status') == 'scanned':
                    result['status'] = 'success'
                    result['action_taken'] = 'no_action_needed'
                    result['message'] = f"No action needed for this nodegroup"

            # Final summary
            successful = sum(1 for r in results.values() if r['status'] == 'success')
            total = len(results)
            protection_applied = sum(1 for r in results.values() if r.get('action_taken') == 'protection_applied')
            protection_removed = sum(1 for r in results.values() if r.get('action_taken') == 'protection_removed')

            self.logger.info(f"🎉 FINAL SUMMARY:")
            self.logger.info(f"   Nodegroups processed: {successful}/{total}")
            self.logger.info(f"   Protection applied: {protection_applied}")
            self.logger.info(f"   Protection removed: {protection_removed}")
            self.logger.info(
                f"   Total protected instances in cluster: {1 if protection_applied > 0 or (len(all_protected_instances) > 0 and protection_removed == 0) else 0}")

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'message': f'Protection monitor completed for {cluster_name} - ensuring only ONE instance protected across ALL nodegroups',
                    'cluster_name': cluster_name,
                    'region': region,
                    'nodegroups_checked': total,
                    'successful_operations': successful,
                    'protection_actions': {
                        'applied': protection_applied,
                        'removed': protection_removed,
                        'final_protected_count': 1 if (protection_applied > 0 or (
                                    len(all_protected_instances) > 0 and protection_removed < len(
                                all_protected_instances))) else 0
                    },
                    'results': results,
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'processed_by': 'lambda-node-protection-monitor',
                    'processed_by_user': '{{current_user}}',
                    'generated_on': '{{current_date}} {{current_time}} UTC'
                }, indent=2)
            }

        except Exception as e:
            self.logger.error(f"❌ Protection monitor logic failed: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'error': str(e),
                    'cluster_name': cluster_name,
                    'region': region,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }, indent=2)
            }


# Create global instance
monitor = LambdaNodeProtectionMonitor()


def lambda_handler(event, context):
    """
    AWS Lambda entry point - this is the function Lambda expects to find

    Template variables that will be injected:
    - {{cluster_name}}: EKS cluster name
    - {{region}}: AWS region
    - {{access_key}}: AWS access key (optional)
    - {{secret_key}}: AWS secret key (optional)
    - {{current_user}}: User who generated this function
    - {{current_date}}: Date when function was generated
    - {{current_time}}: Time when function was generated

    Expected event format (if not using injected values):
    {
        "cluster_name": "eks-cluster-name",
        "region": "us-east-1",
        "access_key": "optional-access-key",
        "secret_key": "optional-secret-key"
    }
    """
    try:
        logger.info(f"🚀 Lambda invoked by {context.invoked_function_arn}")
        logger.info(f"📅 Generated on: {{current_date}} {{current_time}} UTC")
        logger.info(f"👤 Generated by user: {{current_user}}")
        logger.info(f"📥 Event received: {json.dumps(event, indent=2)}")

        # Get configuration from template injection or event
        cluster_name = '{{cluster_name}}' if '{{cluster_name}}' != '{{cluster_name}}' else event.get(
            'cluster_name') or os.environ.get('CLUSTER_NAME')
        region = '{{region}}' if '{{region}}' != '{{region}}' else event.get('region') or os.environ.get('AWS_REGION')
        access_key = '{{access_key}}' if '{{access_key}}' != '{{access_key}}' else event.get(
            'access_key') or os.environ.get('NEW_AWS_ACCESS_KEY_ID')
        secret_key = '{{secret_key}}' if '{{secret_key}}' != '{{secret_key}}' else event.get(
            'secret_key') or os.environ.get('NEW_AWS_SECRET_ACCESS_KEY')

        # Log current execution role if using Lambda role
        if not access_key or not secret_key:
            sts_client = boto3.client('sts')
            identity = sts_client.get_caller_identity()
            logger.info(f"🔐 Executing as: {identity.get('Arn')}")
        else:
            logger.info(f"🔐 Using injected AWS credentials")

        # Validate required parameters
        if not cluster_name:
            error_msg = 'cluster_name is required in template injection, event payload, or CLUSTER_NAME environment variable'
            logger.error(f"❌ {error_msg}")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': error_msg,
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'example_event': {
                        'cluster_name': 'eks-cluster-account01_clouduser01-us-east-1-wxie',
                        'region': 'us-east-1',
                        'access_key': 'optional-access-key',
                        'secret_key': 'optional-secret-key'
                    }
                })
            }

        if not region:
            # Try to extract region from cluster name
            region = monitor.extract_region_from_cluster_name(cluster_name)

        if not region:
            error_msg = 'region is required in template injection, event, environment variable, or extractable from cluster name'
            logger.error(f"❌ {error_msg}")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': error_msg,
                    'cluster_name': cluster_name,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }

        logger.info(f"🎯 Processing cluster: {cluster_name} in region: {region}")

        # Run the protection monitoring logic
        result = monitor.run_protection_monitor_logic(cluster_name, region, access_key, secret_key)

        logger.info(f"🎉 Lambda execution completed with status: {result['statusCode']}")
        return result

    except Exception as e:
        logger.error(f"💥 Lambda handler failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': f'Lambda execution failed: {str(e)}',
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        }


def main():
    """
    Local testing function - simulates Lambda execution with template values
    """
    print("🧪 Running local test simulation...")
    print(f"📅 Generated on: {{current_date}} {{current_time}} UTC")
    print(f"👤 Generated by: {{current_user}}")

    # Test event - these would be overridden by template injection
    test_event = {
        'cluster_name': '{{cluster_name}}',
        'region': '{{region}}',
        'access_key': '{{access_key}}',
        'secret_key': '{{secret_key}}'
    }

    # Mock Lambda context
    class MockContext:
        def __init__(self):
            self.function_name = 'lambda-node-protection-monitor'
            self.function_version = '$LATEST'
            self.invoked_function_arn = 'arn:aws:lambda:{{region}}:123456789012:function:node-protection-monitor'
            self.memory_limit_in_mb = '128'
            self.remaining_time_in_millis = 30000
            self.log_group_name = '/aws/lambda/node-protection-monitor'
            self.log_stream_name = '{{current_date}}/[$LATEST]test'

    context = MockContext()

    try:
        print(f"📤 Invoking with template values...")
        result = lambda_handler(test_event, context)

        print(f"\n📊 Result:")
        print(f"Status Code: {result['statusCode']}")
        if result.get('body'):
            body = json.loads(result['body'])
            print(json.dumps(body, indent=2))

        return result

    except Exception as e:
        print(f"💥 Local test failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()