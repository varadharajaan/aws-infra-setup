#!/usr/bin/env python3
"""
EKS Cluster NodeGroup Scaling Lambda Function
Handles scheduled scaling of EKS nodegroups based on EventBridge events
Supports both single and multiple nodegroup scaling operations
"""

import boto3
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for EKS nodegroup scaling
    
    Event structure expected:
    {
        "action": "scale_up" or "scale_down",
        "ist_time": "8:30 AM IST",  # For logging purposes
        "nodegroups": [
            {
                "name": "nodegroup-name",
                "desired_size": 1,
                "min_size": 1,
                "max_size": 3
            },
            {
                "name": "another-nodegroup",
                "desired_size": 1,
                "min_size": 1,
                "max_size": 3
            }
        ]
    }
    """
    try:
        cluster_name = '{cluster_name}'
        region = '{region}'
        
        # Create EKS client
        eks_client = boto3.client('eks', region_name=region)
        
        # Process the event
        action = event.get('action', 'unknown')
        ist_time = event.get('ist_time', 'unknown time')
        nodegroups_config = event.get('nodegroups', [])
        
        # Validate the input
        if not nodegroups_config:
            error_msg = "No nodegroups specified in the event"
            logger.error(error_msg)
            return {
                'statusCode': 400,
                'body': json.dumps({'error': error_msg})
            }
        
        # Log the operation
        logger.info(f"Starting {action} operation for cluster {cluster_name} at {ist_time} with {len(nodegroups_config)} nodegroups")
        
        # Track operation results
        results = []
        success_count = 0
        
        # Process each nodegroup
        for ng_config in nodegroups_config:
            nodegroup_name = ng_config.get('name')
            if not nodegroup_name:
                logger.warning("Skipping nodegroup with missing name")
                continue
                
            # Get scaling parameters with defaults
            desired_size = ng_config.get('desired_size', 1)
            min_size = ng_config.get('min_size', 0)
            max_size = ng_config.get('max_size', 3)
            
            try:
                # Get current nodegroup configuration
                current_ng = eks_client.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name
                )
                
                # Extract current scaling configuration
                current_scaling = current_ng['nodegroup'].get('scalingConfig', {})
                current_desired = current_scaling.get('desiredSize', 0)
                current_min = current_scaling.get('minSize', 0)
                current_max = current_scaling.get('maxSize', 0)
                
                # Log current and target values
                logger.info(f"Nodegroup {nodegroup_name}:")
                logger.info(f"  Current: min={current_min}, desired={current_desired}, max={current_max}")
                logger.info(f"  Target: min={min_size}, desired={desired_size}, max={max_size}")
                
                # Skip update if configuration is unchanged
                if current_min == min_size and current_desired == desired_size and current_max == max_size:
                    logger.info(f"Skipping update for {nodegroup_name} - scaling configuration unchanged")
                    
                    results.append({
                        'nodegroup': nodegroup_name,
                        'status': 'skipped',
                        'message': 'Configuration unchanged',
                        'current': {
                            'min': current_min,
                            'desired': current_desired,
                            'max': current_max
                        }
                    })
                    
                    # Count as success since there was no error
                    success_count += 1
                    continue
                
                # Update the nodegroup scaling configuration
                response = eks_client.update_nodegroup_config(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name,
                    scalingConfig={
                        'minSize': min_size,
                        'maxSize': max_size,
                        'desiredSize': desired_size
                    }
                )
                
                # Record successful result
                results.append({
                    'nodegroup': nodegroup_name,
                    'status': 'success',
                    'update_id': response['update']['id'],
                    'previous': {
                        'min': current_min,
                        'desired': current_desired,
                        'max': current_max
                    },
                    'new': {
                        'min': min_size,
                        'desired': desired_size,
                        'max': max_size
                    }
                })
                
                success_count += 1
                logger.info(f"Successfully initiated scaling for {nodegroup_name}")
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error scaling nodegroup {nodegroup_name}: {error_msg}")
                
                # Record error result
                results.append({
                    'nodegroup': nodegroup_name,
                    'status': 'error',
                    'error': error_msg,
                    'target': {
                        'min': min_size,
                        'desired': desired_size,
                        'max': max_size
                    }
                })
        
        # Prepare the summary response
        summary = {
            'timestamp': datetime.now().isoformat(),
            'cluster': cluster_name,
            'region': region,
            'action': action,
            'ist_time': ist_time,
            'total_nodegroups': len(nodegroups_config),
            'successful_operations': success_count,
            'results': results
        }
        
        logger.info(f"Scaling operation summary: {success_count}/{len(nodegroups_config)} nodegroups processed successfully")
        
        # Return the response
        return {
            'statusCode': 200 if success_count > 0 else 500,
            'body': json.dumps(summary, default=str)
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Unexpected error during scaling operation: {error_msg}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': error_msg,
                'cluster': '{cluster_name}',
                'region': '{region}'
            })
        }

## For local testing
# if __name__ == "__main__":
#     # Test event simulating a scale-up operation
#     scale_up_event = {
#         "action": "scale_up",
#         "ist_time": "8:30 AM IST",
#         "nodegroups": [
#             {
#                 "name": "test-nodegroup-1",
#                 "desired_size": 2,
#                 "min_size": 1,
#                 "max_size": 3
#             },
#             {
#                 "name": "test-nodegroup-2",
#                 "desired_size": 1,
#                 "min_size": 1,
#                 "max_size": 3
#             }
#         ]
#     }
    
#     scale_down_event = {
#         "action": "scale_down",
#         "ist_time": "6:30 PM IST",
#         "nodegroups": [
#             {
#                 "name": "test-nodegroup-1",
#                 "desired_size": 0,
#                 "min_size": 0,
#                 "max_size": 3
#             },
#             {
#                 "name": "test-nodegroup-2",
#                 "desired_size": 0,
#                 "min_size": 0,
#                 "max_size": 3
#             }
#         ]
#     }
    
#         # Set placeholders for local testing
#     cluster_name = "eks-test-cluster"
#     region = "us-east-1"
    
#     # Override the placeholders in the function
#     globals()['lambda_handler'] = lambda event, context: lambda_handler.__globals__['lambda_handler'](event, context)
#     lambda_handler.__globals__['cluster_name'] = cluster_name
#     lambda_handler.__globals__['region'] = region
    
#     print("=== Testing SCALE UP operation ===")
#     print(f"Cluster: {cluster_name}")
#     print(f"Region: {region}")
    
#     # Simulate lambda invocation for scale up
#     print("\nRunning scale-up test:")
#     result = lambda_handler(scale_up_event, None)
#     print(json.dumps(result, indent=2))
    
#     print("\n\n=== Testing SCALE DOWN operation ===")
#     print(f"Cluster: {cluster_name}")
#     print(f"Region: {region}")
    
#     # Simulate lambda invocation for scale down
#     print("\nRunning scale-down test:")
#     result = lambda_handler(scale_down_event, None)
#     print(json.dumps(result, indent=2))

