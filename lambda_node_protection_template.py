#!/usr/bin/env python3
"""
EKS Cluster Node Protection Lambda Function
Ensures at least one node in each nodegroup has NO_DELETE protection label
Runs every 5 minutes via EventBridge scheduled rule
"""

import boto3
import json
import logging
import os
import subprocess
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Lambda handler for EKS node protection monitoring
    """
    try:
        cluster_name = '{{cluster_name}}'
        region = '{{region}}'
        access_key = '{{access_key}}'
        secret_key = '{{secret_key}}'
        
        # Calculate current IST time (UTC + 5:30)
        ist_timezone = timezone(timedelta(hours=5, minutes=30))
        current_ist = datetime.now(ist_timezone)
        ist_time = current_ist.strftime('%I:%M %p IST')
        
        logger.info(f"Starting node protection check for cluster {cluster_name} at {ist_time}")
        
        # Create AWS session with credentials
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        eks_client = session.client('eks')
        
        # Set environment variables for kubectl
        env = os.environ.copy()
        env['AWS_ACCESS_KEY_ID'] = access_key
        env['AWS_SECRET_ACCESS_KEY'] = secret_key
        env['AWS_DEFAULT_REGION'] = region
        
        # Update kubeconfig
        logger.info("Updating kubeconfig...")
        subprocess.run([
            'aws', 'eks', 'update-kubeconfig',
            '--region', region,
            '--name', cluster_name
        ], check=True, capture_output=True, env=env)
        
        # Get all nodegroups
        response = eks_client.list_nodegroups(clusterName=cluster_name)
        all_nodegroups = response.get('nodegroups', [])
        
        # Filter nodegroups with priority patterns
        primary_pattern = re.compile(r'^nodegroup-[0-9]-ondemand$')
        matching_nodegroups = [ng for ng in all_nodegroups if primary_pattern.match(ng)]
        
        if not matching_nodegroups:
            secondary_pattern = re.compile(r'^nodegroup-[0-9]-.*$')
            matching_nodegroups = [ng for ng in all_nodegroups if secondary_pattern.match(ng)]
        
        if not matching_nodegroups:
            fallback_pattern = re.compile(r'^nodegroup-.*$')
            matching_nodegroups = [ng for ng in all_nodegroups if fallback_pattern.match(ng)]
            if len(matching_nodegroups) > 1:
                matching_nodegroups = [matching_nodegroups[0]]
        
        logger.info(f"Found {len(matching_nodegroups)} matching nodegroups: {matching_nodegroups}")
        
        if not matching_nodegroups:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No matching nodegroups found',
                    'cluster': cluster_name,
                    'timestamp': ist_time
                })
            }
        
        # Check each nodegroup for protected nodes
        results = []
        actions_taken = 0
        
        for nodegroup in matching_nodegroups:
            logger.info(f"Checking nodegroup: {nodegroup}")
            
            # Check if nodegroup has any nodes with NO_DELETE=true
            check_cmd = [
                'kubectl', 'get', 'nodes',
                '-l', f'eks.amazonaws.com/nodegroup={nodegroup},NO_DELETE=true',
                '--no-headers'
            ]
            
            check_result = subprocess.run(check_cmd, env=env, capture_output=True, text=True)
            
            protected_nodes = []
            if check_result.returncode == 0 and check_result.stdout.strip():
                protected_nodes = [line.split()[0] for line in check_result.stdout.strip().split('\n') if line.strip()]
            
            nodegroup_result = {
                'nodegroup': nodegroup,
                'protected_nodes_found': len(protected_nodes),
                'protected_nodes': protected_nodes,
                'action_taken': False,
                'new_protected_node': None
            }
            
            if len(protected_nodes) == 0:
                logger.info(f"No protected nodes found in {nodegroup}. Applying protection...")
                
                # Apply protection to nodes in this nodegroup
                protection_result = apply_node_protection(
                    cluster_name, region, access_key, secret_key, 
                    nodegroup, env
                )
                
                if protection_result['success']:
                    nodegroup_result['action_taken'] = True
                    nodegroup_result['new_protected_node'] = protection_result.get('protected_node')
                    actions_taken += 1
                    logger.info(f"Successfully protected node in {nodegroup}")
                else:
                    nodegroup_result['error'] = protection_result.get('error', 'Unknown error')
                    logger.error(f"Failed to protect nodes in {nodegroup}: {nodegroup_result['error']}")
            else:
                logger.info(f"Found {len(protected_nodes)} protected nodes in {nodegroup}. No action needed.")
            
            results.append(nodegroup_result)
        
        # Prepare response
        summary = {
            'timestamp': datetime.now().isoformat(),
            'ist_time': ist_time,
            'cluster': cluster_name,
            'region': region,
            'total_nodegroups_checked': len(matching_nodegroups),
            'actions_taken': actions_taken,
            'nodegroup_results': results
        }
        
        logger.info(f"Node protection check completed. Actions taken: {actions_taken}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(summary, default=str)
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Unexpected error during node protection check: {error_msg}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': error_msg,
                'cluster': '{{cluster_name}}',
                'region': '{{region}}',
                'timestamp': datetime.now().isoformat()
            })
        }

def apply_node_protection(cluster_name, region, access_key, secret_key, nodegroup, env):
    """
    Apply NO_DELETE protection to nodes in the specified nodegroup
    Modified version of apply_no_delete_to_matching_nodegroups for single nodegroup
    """
    try:
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_user = 'lambda-automation'
        
        logger.info(f"Applying protection to nodegroup: {nodegroup}")
        
        # Get all nodes in this specific nodegroup
        result = subprocess.run([
            'kubectl', 'get', 'nodes',
            '-l', f'eks.amazonaws.com/nodegroup={nodegroup}',
            '-o', 'json'
        ], capture_output=True, text=True, check=True, env=env)
        
        nodes_data = json.loads(result.stdout)
        
        if not nodes_data.get('items'):
            return {
                'success': False,
                'error': f'No nodes found in nodegroup {nodegroup}'
            }
        
        # Find a node that doesn't have NO_DELETE=true
        target_node = None
        for node in nodes_data['items']:
            node_name = node['metadata']['name']
            node_labels = node['metadata'].get('labels', {})
            current_no_delete = node_labels.get('NO_DELETE')
            
            if current_no_delete != 'true':
                target_node = node_name
                break
        
        if not target_node:
            return {
                'success': True,
                'message': 'All nodes already protected',
                'protected_node': None
            }
        
        # Apply protection labels to the target node
        raw_datetime = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        label_safe_timestamp = raw_datetime.replace(' ', 'T').replace(':', '-')
        
        protection_labels = {
            'NO_DELETE': 'true',
            'protection-level': 'high',
            'protected-by': current_user,
            'protection-date': datetime.utcnow().strftime('%Y-%m-%d'),
            'protection-time': datetime.utcnow().strftime('%H-%M-%S'),
            'protection-timestamp': label_safe_timestamp,
            'managed-by': 'lambda-automation',
            'nodegroup-protected': nodegroup
        }
        
        # Apply each label
        for label_key, label_value in protection_labels.items():
            subprocess.run([
                'kubectl', 'label', 'node', target_node,
                f'{label_key}={label_value}', '--overwrite'
            ], check=True, capture_output=True, env=env)
        
        # Also apply scale-down protection annotation
        subprocess.run([
            'kubectl', 'annotate', 'node', target_node,
            'cluster-autoscaler.kubernetes.io/scale-down-disabled=true',
            '--overwrite'
        ], check=True, capture_output=True, env=env)
        
        logger.info(f"Successfully protected node {target_node} in nodegroup {nodegroup}")
        
        return {
            'success': True,
            'protected_node': target_node,
            'labels_applied': list(protection_labels.keys())
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed: {e}"
        if e.stderr:
            error_msg += f" - {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}"
        return {
            'success': False,
            'error': error_msg
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

## For local testing
# if __name__ == "__main__":
#     test_event = {
#         "source": "aws.events",
#         "detail-type": "Scheduled Event",
#         "detail": {}
#     }
    
#     # Set test credentials (replace with actual values for testing)
#     os.environ['AWS_ACCESS_KEY_ID'] = 'your-access-key'
#     os.environ['AWS_SECRET_ACCESS_KEY'] = 'your-secret-key'
    
#     print("=== Testing Node Protection Lambda ===")
#     result = lambda_handler(test_event, None)
#     print(json.dumps(result, indent=2))