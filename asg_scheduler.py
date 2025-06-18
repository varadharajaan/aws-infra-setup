"""
ASG Scheduler - 9 AM to 6 PM IST Business Hours
Uses EventBridge Rules and Lambda functions for scheduling
"""

import json
import os
import boto3
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
import pytz
from aws_credential_manager import CredentialInfo

class ASGScheduler:
    def __init__(self, current_user='varadharajaan'):
        self.current_user = current_user
        self.ist_timezone = pytz.timezone('Asia/Kolkata')
        
    def create_asg_schedule(self, cred_info: CredentialInfo, asg_name: str, 
                          scale_up_time: str = "09:00", scale_down_time: str = "18:00") -> Dict:
        """Create schedule for ASG to scale up at 9 AM and down at 6 PM IST"""
        try:
            print(f"\n⏰ Creating ASG Schedule for {asg_name}")
            print(f"   📅 Scale Up: {scale_up_time} IST")
            print(f"   📅 Scale Down: {scale_down_time} IST")
            
            region = cred_info.regions[0]
            
            # Create clients
            events_client = boto3.client(
                'events',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )
            
            lambda_client = boto3.client(
                'lambda',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )
            
            iam_client = boto3.client(
                'iam',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )
            
            # Step 1: Create IAM role for Lambda
            lambda_role_arn = self._create_lambda_execution_role(iam_client, asg_name)
            
            # Step 2: Create Lambda functions
            scale_up_function_arn = self._create_scale_lambda_function(
                lambda_client, asg_name, 'up', lambda_role_arn, region
            )
            
            scale_down_function_arn = self._create_scale_lambda_function(
                lambda_client, asg_name, 'down', lambda_role_arn, region
            )
            
            # Step 3: Create EventBridge rules
            scale_up_rule = self._create_eventbridge_rule(
                events_client, asg_name, 'up', scale_up_time
            )
            
            scale_down_rule = self._create_eventbridge_rule(
                events_client, asg_name, 'down', scale_down_time
            )
            
            # Step 4: Connect rules to Lambda functions
            self._connect_rule_to_lambda(
                events_client, lambda_client, scale_up_rule['RuleArn'], 
                scale_up_function_arn, f"{asg_name}-scale-up"
            )
            
            self._connect_rule_to_lambda(
                events_client, lambda_client, scale_down_rule['RuleArn'], 
                scale_down_function_arn, f"{asg_name}-scale-down"
            )
            
            # Save scheduling details
            schedule_details = {
                'asg_name': asg_name,
                'scale_up_time': scale_up_time,
                'scale_down_time': scale_down_time,
                'timezone': 'Asia/Kolkata',
                'lambda_functions': {
                    'scale_up': scale_up_function_arn,
                    'scale_down': scale_down_function_arn
                },
                'eventbridge_rules': {
                    'scale_up': scale_up_rule['RuleName'],
                    'scale_down': scale_down_rule['RuleName']
                },
                'lambda_role': lambda_role_arn
            }
            
            self._save_schedule_details(cred_info, schedule_details)
            
            print(f"✅ ASG Schedule created successfully!")
            print(f"   🔼 Scale up function: {scale_up_function_arn.split(':')[-1]}")
            print(f"   🔽 Scale down function: {scale_down_function_arn.split(':')[-1]}")
            
            return schedule_details
            
        except Exception as e:
            print(f"❌ Error creating ASG schedule: {e}")
            raise
    
    def _create_lambda_execution_role(self, iam_client, asg_name: str) -> str:
        """Create IAM role for Lambda execution"""
        role_name = f"asg-scheduler-role-{asg_name}"
        
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        
        # Check if role already exists
        try:
            response = iam_client.get_role(RoleName=role_name)
            print(f"   📋 Using existing IAM role: {role_name}")
            return response['Role']['Arn']
        except iam_client.exceptions.NoSuchEntityException:
            pass
        
        try:
            # Create role
            role_response = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=f"Role for ASG scheduler Lambda functions - {asg_name}"
            )
            
            # Attach basic Lambda execution policy
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
            )
            
            # Create and attach custom policy for ASG operations
            asg_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "autoscaling:UpdateAutoScalingGroup",
                            "autoscaling:DescribeAutoScalingGroups",
                            "autoscaling:SetDesiredCapacity"
                        ],
                        "Resource": "*"
                    }
                ]
            }
            
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"ASGSchedulerPolicy-{asg_name}",
                PolicyDocument=json.dumps(asg_policy)
            )
            
            print(f"   ✅ Created IAM role: {role_name}")
            return role_response['Role']['Arn']
            
        except Exception as e:
            print(f"   ❌ Error creating IAM role: {e}")
            raise
    
    def _create_scale_lambda_function_fixed(self, lambda_client, asg_name: str, 
                                    direction: str, role_arn: str, region: str) -> str:
        """Create Lambda function for scaling ASG up or down"""
        function_name = f"asg-scheduler-{asg_name}-scale-{direction}"
        
        # Lambda function code
        lambda_code = f'''
import json
import boto3

def lambda_handler(event, context):
    asg_client = boto3.client('autoscaling')
    asg_name = '{asg_name}'
    
    try:
        # Get current ASG configuration
        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        
        if not response['AutoScalingGroups']:
            return {{
                'statusCode': 404,
                'body': json.dumps(f'ASG {{asg_name}} not found')
            }}
        
        asg = response['AutoScalingGroups'][0]
        
        if '{direction}' == 'up':
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
        
        return {{
            'statusCode': 200,
            'body': json.dumps(f'ASG {{asg_name}} {{action}} to {{new_desired}} instances')
        }}
        
    except Exception as e:
        print(f'Error: {{str(e)}}')
        return {{
            'statusCode': 500,
            'body': json.dumps(f'Error scaling ASG: {{str(e)}}')
        }}
'''
        
        # Check if function already exists
        try:
            response = lambda_client.get_function(FunctionName=function_name)
            print(f"   📋 Using existing Lambda function: {function_name}")
            return response['Configuration']['FunctionArn']
        except lambda_client.exceptions.ResourceNotFoundException:
            pass
        
        try:
            # Create Lambda function
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.9',
                Role=role_arn,
                Handler='index.lambda_handler',
                Code={
                    'ZipFile': lambda_code.encode('utf-8')
                },
                Description=f'ASG Scheduler - Scale {direction} for {asg_name}',
                Timeout=60,
                Tags={
                    'ASGName': asg_name,
                    'Direction': direction,
                    'CreatedBy': self.current_user,
                    'Service': 'ASGScheduler'
                }
            )
            
            print(f"   ✅ Created Lambda function: {function_name}")
            return response['FunctionArn']
            
        except Exception as e:
            print(f"   ❌ Error creating Lambda function: {e}")
            raise
    
    #if this method not works then switch to _fixed above method. 
    def _create_scale_lambda_function(self, lambda_client, asg_name: str, 
                                    direction: str, role_arn: str, region: str) -> str:
        """Create Lambda function for scaling ASG up or down"""
        function_name = f"asg-scheduler-{asg_name}-scale-{direction}"
    
        try:
            # Check if function already exists
            try:
                response = lambda_client.get_function(FunctionName=function_name)
                print(f"   📋 Using existing Lambda function: {function_name}")
                return response['Configuration']['FunctionArn']
            except lambda_client.exceptions.ResourceNotFoundException:
                pass
        
            # Load the lambda template file
            lambda_code = self._get_lambda_template_code(asg_name, direction)
        
            # Create Lambda function
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.9',
                Role=role_arn,
                Handler='index.lambda_handler',
                Code={
                    'ZipFile': lambda_code.encode('utf-8')
                },
                Description=f'ASG Scheduler - Scale {direction} for {asg_name}',
                Timeout=60,
                Tags={
                    'ASGName': asg_name,
                    'Direction': direction,
                    'CreatedBy': self.current_user,
                    'Service': 'ASGScheduler'
                }
            )
        
            print(f"   ✅ Created Lambda function: {function_name}")
            return response['FunctionArn']
        
        except Exception as e:
            print(f"   ❌ Error creating Lambda function: {e}")
            raise

    def _get_lambda_template_code(self, asg_name: str, direction: str) -> str:
        """Get the Lambda code from template file with proper variable substitution"""
        try:
            # Try to load the template file
            template_path = "lambda_asg_scaling_template.py"
            with open(template_path, "r") as file:
                template_content = file.read()
        
            # Replace placeholders with actual values
            lambda_code = template_content.replace('${ASG_NAME}', asg_name)
            lambda_code = lambda_code.replace('${DIRECTION}', direction)
        
            return lambda_code
        except FileNotFoundError:
            # Fallback to embedded code if template file doesn't exist
            print(f"   ⚠️ Template file not found. Using embedded code.")
            return self._get_embedded_lambda_code(asg_name, direction)

    def _get_embedded_lambda_code(self, asg_name: str, direction: str) -> str:
        """Generate embedded lambda code as fallback"""
        return f'''
    import json
    import boto3

    def lambda_handler(event, context):
        asg_client = boto3.client('autoscaling')
        asg_name = '{asg_name}'
    
        try:
            # Get current ASG configuration
            response = asg_client.describe_auto_scaling_groups(
                AutoScalingGroupNames=[asg_name]
            )
        
            if not response['AutoScalingGroups']:
                return {{
                    'statusCode': 404,
                    'body': json.dumps(f'ASG {{asg_name}} not found')
                }}
        
            asg = response['AutoScalingGroups'][0]
        
            if '{direction}' == 'up':
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
        
            return {{
                'statusCode': 200,
                'body': json.dumps(f'ASG {{asg_name}} {{action}} to {{new_desired}} instances')
            }}
        
        except Exception as e:
            print(f'Error: {{str(e)}}')
            return {{
                'statusCode': 500,
                'body': json.dumps(f'Error scaling ASG: {{str(e)}}')
            }}
    '''

    def _create_eventbridge_rule(self, events_client, asg_name: str, 
                               direction: str, time: str) -> Dict:
        """Create EventBridge rule for scheduling"""
        rule_name = f"asg-scheduler-{asg_name}-{direction}"
        
        # Convert IST time to UTC cron expression
        ist_hour, ist_minute = map(int, time.split(':'))
        
        # IST is UTC+5:30
        utc_time = datetime.now(self.ist_timezone).replace(
            hour=ist_hour, minute=ist_minute, second=0, microsecond=0
        ).astimezone(timezone.utc)
        
        utc_hour = utc_time.hour
        utc_minute = utc_time.minute
        
        # Cron expression for daily execution (Monday to Friday)
        cron_expression = f"cron({utc_minute} {utc_hour} ? * MON-FRI *)"
        
        try:
            # Create EventBridge rule
            response = events_client.put_rule(
                Name=rule_name,
                ScheduleExpression=cron_expression,
                Description=f'ASG Scheduler - Scale {direction} {asg_name} at {time} IST daily (Mon-Fri)',
                State='ENABLED',
                Tags=[
                    {
                        'Key': 'ASGName',
                        'Value': asg_name
                    },
                    {
                        'Key': 'Direction',
                        'Value': direction
                    },
                    {
                        'Key': 'CreatedBy',
                        'Value': self.current_user
                    },
                    {
                        'Key': 'Service',
                        'Value': 'ASGScheduler'
                    }
                ]
            )
            
            print(f"   ✅ Created EventBridge rule: {rule_name}")
            print(f"      ⏰ Schedule: {cron_expression} (Daily Mon-Fri)")
            
            return {
                'RuleName': rule_name,
                'RuleArn': response['RuleArn'],
                'CronExpression': cron_expression
            }
            
        except Exception as e:
            print(f"   ❌ Error creating EventBridge rule: {e}")
            raise
    
    def _connect_rule_to_lambda(self, events_client, lambda_client, 
                              rule_arn: str, function_arn: str, target_id: str):
        """Connect EventBridge rule to Lambda function"""
        try:
            rule_name = rule_arn.split('/')[-1]
            
            # Add Lambda function as target to the rule
            events_client.put_targets(
                Rule=rule_name,
                Targets=[
                    {
                        'Id': target_id,
                        'Arn': function_arn
                    }
                ]
            )
            
            # Add permission for EventBridge to invoke Lambda
            try:
                lambda_client.add_permission(
                    FunctionName=function_arn,
                    StatementId=f"allow-eventbridge-{target_id}",
                    Action='lambda:InvokeFunction',
                    Principal='events.amazonaws.com',
                    SourceArn=rule_arn
                )
            except lambda_client.exceptions.ResourceConflictException:
                # Permission already exists
                pass
            
            print(f"   🔗 Connected rule to Lambda function")
            
        except Exception as e:
            print(f"   ❌ Error connecting rule to Lambda: {e}")
            raise
    
    def _save_schedule_details(self, cred_info: CredentialInfo, schedule_details: Dict):
        """Save schedule details to output folder"""
        try:
            # Create output directory
            output_dir = f"aws/ec2/{cred_info.account_name}"
            os.makedirs(output_dir, exist_ok=True)
            
            # Prepare schedule details with metadata
            details = {
                'timestamp': datetime.now().isoformat(),
                'created_by': self.current_user,
                'account_info': {
                    'account_name': cred_info.account_name,
                    'account_id': cred_info.account_id,
                    'region': cred_info.regions[0]
                },
                'schedule_configuration': schedule_details
            }
            
            # Save to JSON file
            filename = f"{output_dir}/asg_schedule_{schedule_details['asg_name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(details, f, indent=2)
            
            print(f"   📁 Schedule details saved to: {filename}")
            
        except Exception as e:
            print(f"   ⚠️ Warning: Could not save schedule details: {e}")
    
    def prompt_schedule_creation(self, cred_info: CredentialInfo, asg_name: str) -> Optional[Dict]:
        """Prompt user for schedule creation with custom times"""
        print("\n" + "="*60)
        print("⏰ ASG SCHEDULING CONFIGURATION")
        print("="*60)
        print("Schedule ASG to automatically scale up/down during business hours")
        print("Default: Scale UP at 9:00 AM IST, Scale DOWN at 6:00 PM IST")
        print("Frequency: Monday to Friday (weekdays only)")
        print("-" * 60)
        
        enable_schedule = input("Enable ASG scheduling? (y/n, default: n): ").strip().lower()
        
        if enable_schedule != 'y':
            print("⏭️ Skipping ASG scheduling")
            return None
        
        # Get custom times
        print("\n📅 Schedule Configuration:")
        scale_up_time = input("Scale UP time (HH:MM, default: 09:00): ").strip()
        if not scale_up_time:
            scale_up_time = "09:00"
        
        scale_down_time = input("Scale DOWN time (HH:MM, default: 18:00): ").strip()
        if not scale_down_time:
            scale_down_time = "18:00"
        
        # Validate time format
        try:
            datetime.strptime(scale_up_time, "%H:%M")
            datetime.strptime(scale_down_time, "%H:%M")
        except ValueError:
            print("❌ Invalid time format. Using defaults: 09:00 and 18:00")
            scale_up_time = "09:00"
            scale_down_time = "18:00"
        
        print(f"\n✅ Creating schedule:")
        print(f"   🔼 Scale UP: {scale_up_time} IST (Monday-Friday)")
        print(f"   🔽 Scale DOWN: {scale_down_time} IST (Monday-Friday)")
        
        confirm = input("\nConfirm schedule creation? (y/n): ").strip().lower()
        
        if confirm == 'y':
            return self.create_asg_schedule(cred_info, asg_name, scale_up_time, scale_down_time)
        else:
            print("⏭️ ASG scheduling cancelled")
            return None