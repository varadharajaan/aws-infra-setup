import boto3
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        eks_client = boto3.client('eks', region_name='{region}')
        
        cluster_name = '{cluster_name}'
        
        # Get nodegroup name from cluster
        nodegroups = eks_client.list_nodegroups(clusterName=cluster_name)['nodegroups']
        if not nodegroups:
            logger.error(f"No nodegroups found for cluster {cluster_name}")
            return {{'statusCode': 500, 'body': 'No nodegroups found'}}
        
        # Use the first nodegroup found
        nodegroup_name = nodegroups[0]
        
        # Get the desired size from the event
        desired_size = event.get('desired_size', 1)
        min_size = event.get('min_size', 0)
        max_size = event.get('max_size', 3)
        
        # Log current time
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        logger.info(f"Scaling nodegroup {{nodegroup_name}} to desired={{desired_size}}, min={{min_size}}, max={{max_size}} at {{current_time}}")
        
        # Update nodegroup scaling configuration
        response = eks_client.update_nodegroup_config(
            clusterName=cluster_name,
            nodegroupName=nodegroup_name,
            scalingConfig={{
                'minSize': min_size,
                'maxSize': max_size,
                'desiredSize': desired_size
            }}
        )
        
        logger.info(f"Scaling update initiated: {{response['update']['id']}} at {{current_time}}")
        
        return {{
            'statusCode': 200,
            'body': json.dumps({{
                'message': f'Scaling update initiated for {{nodegroup_name}} at {{current_time}}',
                'update_id': response['update']['id'],
                'timestamp': current_time
            }})
        }}
        
    except Exception as e:
        logger.error(f"Error scaling nodegroup: {{str(e)}}")
        return {{
            'statusCode': 500,
            'body': json.dumps({{
                'error': str(e)
            }})
        }}