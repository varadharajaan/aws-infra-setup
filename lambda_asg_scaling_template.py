import json
import boto3

def lambda_handler(event, context):
    asg_client = boto3.client('autoscaling')
    asg_name = '${ASG_NAME}'
    
    try:
        # Get current ASG configuration
        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        
        if not response['AutoScalingGroups']:
            return {
                'statusCode': 404,
                'body': json.dumps(f'ASG {asg_name} not found')
            }
        
        asg = response['AutoScalingGroups'][0]
        
        if '${DIRECTION}' == 'up':
            # Scale up to desired capacity (or at least min size)
            new_desired = max(asg['MinSize'], 1)
            action = 'scaled up'
        else:
            # Scale down to 0
            new_desired = 0
            action = 'scaled down'
        
        # Update desired capacity
        asg_client.set_desired_capacity(
            AutoScalingGroupName=asg_name,
            DesiredCapacity=new_desired,
            HonorCooldown=False
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps(f'ASG {asg_name} {action} to {new_desired} instances')
        }
        
    except Exception as e:
        print(f'Error: {str(e)}')
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error scaling ASG: {str(e)}')
        }