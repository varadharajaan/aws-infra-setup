import logging
import boto3
import botocore
import time
import os
import json
from datetime import datetime

# Define the regions
# REGIONS = [
#     "ap-south-1", "eu-north-1", "eu-west-3", "eu-west-2", "eu-west-1", "ap-northeast-3", "ap-northeast-2", "ap-northeast-1",
#     "ca-central-1", "sa-east-1", "ap-southeast-1", "ap-southeast-2", "eu-central-1", "us-east-1", "us-east-2", "us-west-1",
#     "us-west-2"
# ]

#start logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

REGIONS = ["us-east-1" , "us-east-2", "us-west-1", "us-west-2", "ap-south-1"]

def measure_time(func):
    import functools
    import time
    @functools.wraps(func)
    def wrapper_measure_time(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"Time taken for {func.__name__}: {end_time - start_time:.2f} seconds")
        return result
    return wrapper_measure_time

@measure_time
def delete_lambda_functions(exclude_list=None):
    try:
        lambda_client = boto3.client('lambda', region_name=region)
        functions = lambda_client.list_functions()['Functions']
        for function in functions:
            function_name = function['FunctionName']
            if not exclude_list or function_name not in exclude_list:
                # Delete event source mappings before deleting the function
                mappings = lambda_client.list_event_source_mappings(FunctionName=function_name)['EventSourceMappings']
                for mapping in mappings:
                    mapping_id = mapping['UUID']
                    logging.info(f'Attempting to delete event source mapping: {mapping_id} for Lambda: {function_name}')
                    try:
                        lambda_client.delete_event_source_mapping(UUID=mapping_id)
                        logging.info(f'Deleted event source mapping: {mapping_id}')
                    except Exception as e:
                        logging.error(f'Failed to delete event source mapping {mapping_id} for Lambda {function_name}: {e}')

                # Delete the lambda function after removing mappings
                logging.info(f'Attempting to delete Lambda function: {function_name}')
                try:
                    lambda_client.delete_function(FunctionName=function_name)
                    logging.info(f'Deleted Lambda function: {function_name}')
                except Exception as e:
                    logging.error(f'Failed to delete Lambda function {function_name}: {e}')
    except Exception as e:
        logging.error('Failed to retrieve Lambda functions: {e}')


@measure_time
def delete_dynamodb_tables_except(to_keep, region):
    dynamodb = boto3.client('dynamodb', region_name=region)
    tables = dynamodb.list_tables()['TableNames']
    for table_name in tables:
        if table_name not in to_keep:
            try:
                dynamodb.delete_table(TableName=table_name)
                print(f"Deleted DynamoDB table: {table_name}")
            except Exception as e:
                print(f"Failed to delete DynamoDB table {table_name}: {e}")

@measure_time
def delete_security_groups(region):
    ec2 = boto3.client('ec2', region_name=region)
    try:
        security_groups = ec2.describe_security_groups()['SecurityGroups']
        for sg in security_groups:
            if sg['GroupName'] != 'default':
                try:
                    ec2.delete_security_group(GroupId=sg['GroupId'])
                    print(f"Deleted security group: {sg['GroupName']} ({sg['GroupId']})")
                except Exception as e:
                    if "has a dependent object" in str(e):
                        print(f"Cannot delete {sg['GroupName']} ({sg['GroupId']}): It has a dependent object.")
                        # Optional: Add logic here to handle dependent objects
                    else:
                        print(f"Failed to delete security group {sg['GroupName']} ({sg['GroupId']}): {e}")
    except Exception as e:
        print(f"Error retrieving security groups: {e}")


@measure_time
def delete_key_pairs(region):
    ec2 = boto3.client('ec2', region_name=region)
    try:
        key_pairs = ec2.describe_key_pairs()['KeyPairs']
        for key_pair in key_pairs:
            ec2.delete_key_pair(KeyName=key_pair['KeyName'])
            print(f"Deleted key pair: {key_pair['KeyName']}")
    except Exception as e:
        print(f"Error deleting key pairs: {e}")


@measure_time
def release_elastic_ips(region):
    ec2 = boto3.client('ec2', region_name=region)
    addresses = ec2.describe_addresses()
    for address in addresses['Addresses']:
        if 'InstanceId' not in address:
            ec2.release_address(AllocationId=address['AllocationId'])
            print(f"Released Elastic IP: {address['PublicIp']}")

@measure_time
def delete_key_pairs(region):
    ec2 = boto3.client('ec2', region_name=region)
    key_pairs = ec2.describe_key_pairs()
    for key_pair in key_pairs['KeyPairs']:
        ec2.delete_key_pair(KeyName=key_pair['KeyName'])
        print(f"Deleted Key Pair: {key_pair['KeyName']}")

@measure_time
def terminate_vpn_connections(region):
    ec2 = boto3.client('ec2', region_name=region)
    vpns = ec2.describe_vpn_connections()
    for vpn in vpns['VpnConnections']:
        if vpn['State'] != 'deleted':
            ec2.delete_vpn_connection(VpnConnectionId=vpn['VpnConnectionId'])
            print(f"Terminated VPN Connection: {vpn['VpnConnectionId']}")

@measure_time
def delete_vpc_peering_connections(region):
    ec2 = boto3.client('ec2', region_name=region)
    peerings = ec2.describe_vpc_peering_connections()
    for peering in peerings['VpcPeeringConnections']:
        if peering['Status']['Code'] != 'deleted':
            ec2.delete_vpc_peering_connection(VpcPeeringConnectionId=peering['VpcPeeringConnectionId'])
            print(f"Deleted VPC Peering Connection: {peering['VpcPeeringConnectionId']}")

@measure_time
def remove_vpc_endpoints(region):
    ec2 = boto3.client('ec2', region_name=region)
    endpoints = ec2.describe_vpc_endpoints()
    for endpoint in endpoints['VpcEndpoints']:
        ec2.delete_vpc_endpoint(VpcEndpointId=endpoint['VpcEndpointId'])
        print(f"Removed VPC Endpoint: {endpoint['VpcEndpointId']}")

@measure_time
def delete_cloudformation_stacks(region):
    cf = boto3.client('cloudformation', region_name=region)
    stacks = cf.list_stacks(StackStatusFilter=['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'])
    for stack in stacks['StackSummaries']:
        cf.delete_stack(StackName=stack['StackName'])
        print(f"Deleting CloudFormation Stack: {stack['StackName']}")
        waiter = cf.get_waiter('stack_delete_complete')
        waiter.wait(StackName=stack['StackName'])
        print(f"Deleted CloudFormation Stack: {stack['StackName']}")

@measure_time
def delete_datasync_resources(region):
    client = boto3.client('datasync', region_name=region)
    # Delete tasks
    tasks = client.list_tasks()
    for task in tasks.get('Tasks', []):
        client.delete_task(TaskArn=task['TaskArn'])
        print(f"Deleted DataSync Task: {task['TaskArn']}")

    # Delete locations
    locations = client.list_locations()
    for location in locations.get('Locations', []):
        client.delete_location(LocationArn=location['LocationArn'])
        print(f"Deleted DataSync Location: {location['LocationArn']}")

    # Delete agents
    agents = client.list_agents()
    for agent in agents.get('Agents', []):
        client.delete_agent(AgentArn=agent['AgentArn'])
        print(f"Deleted DataSync Agent: {agent['AgentArn']}")


@measure_time
def delete_efs_resources(region):
    client = boto3.client('efs', region_name=region)

    # Retrieve all file systems
    file_systems = client.describe_file_systems()['FileSystems']

    for fs in file_systems:
        file_system_id = fs['FileSystemId']
        print(f"Working on file system: {file_system_id}")

        # Retrieve and delete all mount targets for each file system
        mount_targets = client.describe_mount_targets(FileSystemId=file_system_id)['MountTargets']
        for mt in mount_targets:
            mount_target_id = mt['MountTargetId']
            try:
                print(f"Deleting mount target: {mount_target_id}")
                client.delete_mount_target(MountTargetId=mount_target_id)
                # Wait until mount target is deleted
                waiter = client.get_waiter('mount_target_deleted')
                waiter.wait(FileSystemId=file_system_id)
                print(f"Deleted mount target: {mount_target_id}")
            except Exception as e:
                print(f"Failed to delete mount target {mount_target_id}: {e}")

        # After deleting mount targets, try to delete the file system
        try:
            if not client.describe_mount_targets(FileSystemId=file_system_id)['MountTargets']:
                print(f"Deleting file system: {file_system_id}")
                client.delete_file_system(FileSystemId=file_system_id)
                print(f"Deleted file system: {file_system_id}")
        except Exception as e:
            print(f"Failed to delete file system {file_system_id}: {e}")


    # Ensure all mount targets are deleted before deleting the file systems
    for fs in file_systems:
        try:
            # You might need to wait or check if all mount targets are really deleted
            client.delete_file_system(FileSystemId=fs['FileSystemId'])
            print(f"Deleted file system: {fs['FileSystemId']}")
        except Exception as e:
            print(f"Failed to delete file system: {fs['FileSystemId']}. Error: {str(e)}")

@measure_time
def delete_storage_gateway_resources(region):
    client = boto3.client('storagegateway', region_name=region)
    # Delete gateways (and implicitly deletes volumes)
    for gateway in client.list_gateways()['Gateways']:
        client.delete_gateway(GatewayARN=gateway['GatewayARN'])

@measure_time
def delete_aws_backup_resources(region):
    client = boto3.client('backup', region_name=region)
    try:
        vaults = client.list_backup_vaults()['BackupVaultList']
        for vault in vaults:
            recovery_points = client.list_recovery_points_by_backup_vault(BackupVaultName=vault['BackupVaultName'])['RecoveryPoints']
            for point in recovery_points:
                client.delete_recovery_point(BackupVaultName=vault['BackupVaultName'], RecoveryPointArn=point['RecoveryPointArn'])
                print(f"Deleted Recovery Point: {point['RecoveryPointArn']} in vault: {vault['BackupVaultName']}")
            
            # Ensure there are no recovery points before deleting the vault
            client.delete_backup_vault(BackupVaultName=vault['BackupVaultName'])
            print(f"Deleted Backup Vault: {vault['BackupVaultName']}")
    except Exception as e:
        print(f"Failed to delete AWS Backup resources: {str(e)}")


@measure_time
def delete_transfer_family_resources(region):
    client = boto3.client('transfer', region_name=region)
    # Delete servers
    for server in client.list_servers()['Servers']:
        client.delete_server(ServerId=server['ServerId'])

@measure_time
def delete_cloudfront_distributions(region):
    client = boto3.client('cloudfront', region_name=region)

    # Get a list of all distributions
    response = client.list_distributions()
    if 'DistributionList' in response and 'Items' in response['DistributionList']:
        for distribution in response['DistributionList']['Items']:
            dist_id = distribution['Id']
            dist_enabled = distribution['Enabled']
            
            # If the distribution is enabled, update it to be disabled
            if dist_enabled:
                print(f"Disabling distribution: {dist_id}")
                etag = client.get_distribution_config(Id=dist_id)['ETag']
                config = client.get_distribution_config(Id=dist_id)['DistributionConfig']
                config['Enabled'] = False
                # Update the distribution to disable it
                client.update_distribution(DistributionConfig=config, Id=dist_id, IfMatch=etag)
                
                # Wait for the distribution to be disabled
                waiter = client.get_waiter('distribution_deployed')
                waiter.wait(Id=dist_id)
                print(f"Distribution {dist_id} is now disabled.")
            
            # Now delete the distribution
            etag = client.get_distribution_config(Id=dist_id)['ETag']
            client.delete_distribution(Id=dist_id, IfMatch=etag)
            print(f"Deleted distribution: {dist_id}")

@measure_time
@measure_time
def delete_iam_roles(region):
    iam = boto3.client('iam', region_name=region)
    roles = iam.list_roles()['Roles']
    for role in roles:
        role_name = role['RoleName']
        
        # Check if the role is a service-linked role
        if 'aws-service-role' in role['Path']:
            print(f"Skipping service-linked role: {role_name}")
            continue
        
        try:
            # 1. Detach all managed policies
            policies = iam.list_attached_role_policies(RoleName=role_name)['AttachedPolicies']
            for policy in policies:
                try:
                    iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
                    print(f"Detached managed policy {policy['PolicyArn']} from role {role_name}")
                except Exception as e:
                    print(f"Failed to detach managed policy {policy['PolicyArn']} from role {role_name}: {e}")

            # 2. Delete all inline policies
            inline_policies = iam.list_role_policies(RoleName=role_name)['PolicyNames']
            for policy_name in inline_policies:
                try:
                    iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                    print(f"Deleted inline policy {policy_name} from role {role_name}")
                except Exception as e:
                    print(f"Failed to delete inline policy {policy_name} from role {role_name}: {e}")

            # 3. Remove role from instance profiles
            try:
                instance_profiles = iam.list_instance_profiles_for_role(RoleName=role_name)['InstanceProfiles']
                for profile in instance_profiles:
                    try:
                        iam.remove_role_from_instance_profile(
                            InstanceProfileName=profile['InstanceProfileName'],
                            RoleName=role_name
                        )
                        print(f"Removed role {role_name} from instance profile {profile['InstanceProfileName']}")
                    except Exception as e:
                        print(f"Failed to remove role {role_name} from instance profile {profile['InstanceProfileName']}: {e}")
            except Exception as e:
                print(f"Failed to list instance profiles for role {role_name}: {e}")

            # 4. Delete the role
            try:
                iam.delete_role(RoleName=role_name)
                print(f"Deleted IAM role: {role_name}")
            except Exception as e:
                print(f"Failed to delete IAM role {role_name}: {e}")
                
        except Exception as e:
            print(f"Error processing role {role_name}: {e}")

@measure_time
def delete_multipart_uploads(region):
    s3 = boto3.client('s3', region_name=region)
    # List all S3 buckets
    buckets = s3.list_buckets()['Buckets']
    
    for bucket in buckets:
        bucket_name = bucket['Name']
        print(f"Checking bucket: {bucket_name}")

        # List multipart uploads
        paginator = s3.get_paginator('list_multipart_uploads')
        page_iterator = paginator.paginate(Bucket=bucket_name)
        
        for page in page_iterator:
            if 'Uploads' in page:
                for upload in page['Uploads']:
                    # Abort incomplete multipart uploads
                    print(f"Aborting multipart upload with ID: {upload['UploadId']} for key: {upload['Key']}")
                    s3.abort_multipart_upload(Bucket=bucket_name, Key=upload['Key'], UploadId=upload['UploadId'])

        print(f"All incomplete multipart uploads aborted for bucket: {bucket_name}")

@measure_time
def delete_ecr_repositories(region):
    ecr_client = boto3.client('ecr', region_name=region)
    
    try:
        # List all ECR repositories
        response = ecr_client.describe_repositories()
        repositories = response.get('repositories', [])
        
        if not repositories:
            print(f"No ECR repositories found in {region}")
            return
        
        print(f"Found {len(repositories)} ECR repositories in {region}")
        
        for repo in repositories:
            repo_name = repo['repositoryName']
            repo_uri = repo['repositoryUri']
            registry_id = repo['registryId']
            
            print(f"\n{'='*80}")
            print(f"Processing ECR repository: {repo_name}")
            print(f"Repository URI: {repo_uri}")
            print(f"Registry ID: {registry_id}")
            print(f"{'='*80}")
            
            try:
                # Get all images in the repository
                images_response = ecr_client.list_images(repositoryName=repo_name)
                image_ids = images_response.get('imageIds', [])
                
                if image_ids:
                    print(f"Found {len(image_ids)} images in repository {repo_name}")
                    
                    # Show image details
                    for image in image_ids:
                        image_tag = image.get('imageTag', 'untagged')
                        image_digest = image.get('imageDigest', 'unknown')
                        print(f"  - Tag: {image_tag}, Digest: {image_digest[:12]}...")
                    
                    # Delete all images in batches (ECR allows up to 100 images per batch)
                    batch_size = 100
                    total_deleted = 0
                    
                    for i in range(0, len(image_ids), batch_size):
                        batch = image_ids[i:i+batch_size]
                        
                        try:
                            print(f"Deleting batch of {len(batch)} images...")
                            delete_response = ecr_client.batch_delete_image(
                                repositoryName=repo_name,
                                imageIds=batch
                            )
                            
                            deleted_images = delete_response.get('imageIds', [])
                            failed_images = delete_response.get('failures', [])
                            
                            total_deleted += len(deleted_images)
                            
                            for deleted_image in deleted_images:
                                tag = deleted_image.get('imageTag', 'untagged')
                                print(f"✅ Deleted image: {tag}")
                            
                            for failed_image in failed_images:
                                tag = failed_image.get('imageId', {}).get('imageTag', 'untagged')
                                reason = failed_image.get('failureReason', 'Unknown')
                                print(f"❌ Failed to delete image {tag}: {reason}")
                            
                        except Exception as e:
                            print(f"❌ Failed to delete batch of images: {e}")
                    
                    print(f"✅ Total images deleted: {total_deleted}")
                    
                    # Wait a moment for deletions to propagate
                    time.sleep(5)
                else:
                    print(f"No images found in repository {repo_name}")
                
                # Delete lifecycle policy if it exists
                try:
                    ecr_client.get_lifecycle_policy(repositoryName=repo_name)
                    print(f"Deleting lifecycle policy for {repo_name}")
                    ecr_client.delete_lifecycle_policy(repositoryName=repo_name)
                    print(f"✅ Deleted lifecycle policy for {repo_name}")
                except ecr_client.exceptions.LifecyclePolicyNotFoundException:
                    print(f"No lifecycle policy found for {repo_name}")
                except Exception as e:
                    print(f"❌ Failed to delete lifecycle policy for {repo_name}: {e}")
                
                # Delete repository policy if it exists
                try:
                    ecr_client.get_repository_policy(repositoryName=repo_name)
                    print(f"Deleting repository policy for {repo_name}")
                    ecr_client.delete_repository_policy(repositoryName=repo_name)
                    print(f"✅ Deleted repository policy for {repo_name}")
                except ecr_client.exceptions.RepositoryPolicyNotFoundException:
                    print(f"No repository policy found for {repo_name}")
                except Exception as e:
                    print(f"❌ Failed to delete repository policy for {repo_name}: {e}")
                
                # Delete scanning configuration
                try:
                    print(f"Deleting scanning configuration for {repo_name}")
                    ecr_client.put_image_scanning_configuration(
                        repositoryName=repo_name,
                        imageScanningConfiguration={'scanOnPush': False}
                    )
                    print(f"✅ Disabled scanning for {repo_name}")
                except Exception as e:
                    print(f"Warning: Could not modify scanning configuration for {repo_name}: {e}")
                
                # Delete the repository
                try:
                    print(f"Deleting ECR repository: {repo_name}")
                    ecr_client.delete_repository(
                        repositoryName=repo_name,
                        force=True  # Force delete even if images remain
                    )
                    print(f"✅ Deleted ECR repository: {repo_name}")
                except Exception as e:
                    print(f"❌ Failed to delete ECR repository {repo_name}: {e}")
                    
                    # Try alternative deletion method
                    try:
                        print(f"Attempting alternative deletion method for {repo_name}")
                        # First ensure all images are really gone
                        remaining_images = ecr_client.list_images(repositoryName=repo_name)
                        if remaining_images.get('imageIds'):
                            print(f"Force deleting remaining images...")
                            ecr_client.batch_delete_image(
                                repositoryName=repo_name,
                                imageIds=remaining_images['imageIds']
                            )
                            time.sleep(10)
                        
                        # Try deletion again
                        ecr_client.delete_repository(repositoryName=repo_name, force=True)
                        print(f"✅ Deleted ECR repository: {repo_name} (alternative method)")
                    except Exception as e2:
                        print(f"❌ Alternative deletion also failed for {repo_name}: {e2}")
                
            except Exception as e:
                print(f"❌ Failed to process ECR repository {repo_name}: {e}")
        
        # Clean up ECR registry settings (if any)
        try:
            print("Checking for registry-wide policies...")
            
            # Delete registry policy if it exists
            try:
                ecr_client.get_registry_policy()
                print("Deleting registry policy...")
                ecr_client.delete_registry_policy()
                print("✅ Deleted registry policy")
            except ecr_client.exceptions.RegistryPolicyNotFoundException:
                print("No registry policy found")
            except Exception as e:
                print(f"❌ Failed to delete registry policy: {e}")
            
            # Reset registry scanning configuration
            try:
                print("Resetting registry scanning configuration...")
                ecr_client.put_registry_scanning_configuration(
                    scanType='BASIC',
                    rules=[]
                )
                print("✅ Reset registry scanning configuration")
            except Exception as e:
                print(f"Warning: Could not reset registry scanning: {e}")
                
        except Exception as e:
            print(f"Warning: Could not process registry settings: {e}")
        
        print(f"✅ Completed ECR repository cleanup in {region}")
        
    except Exception as e:
        print(f"❌ Error processing ECR repositories in {region}: {e}")

@measure_time
def delete_eks_clusters(region):
    eks_client = boto3.client('eks', region_name=region)
    ec2_client = boto3.client('ec2', region_name=region)
    iam_client = boto3.client('iam')
    autoscaling_client = boto3.client('autoscaling', region_name=region)
    
    try:
        # List all EKS clusters
        response = eks_client.list_clusters()
        cluster_names = response.get('clusters', [])
        
        if not cluster_names:
            print(f"No EKS clusters found in {region}")
            return
        
        print(f"Found {len(cluster_names)} EKS clusters in {region}")
        
        for cluster_name in cluster_names:
            print(f"\n{'='*80}")
            print(f"Processing EKS cluster: {cluster_name}")
            print(f"{'='*80}")
            
            try:
                # Get cluster details
                cluster_response = eks_client.describe_cluster(name=cluster_name)
                cluster = cluster_response['cluster']
                cluster_status = cluster['status']
                cluster_arn = cluster['arn']
                
                print(f"Cluster status: {cluster_status}")
                print(f"Cluster ARN: {cluster_arn}")
                
                # 1. Delete all Fargate profiles
                try:
                    fargate_response = eks_client.list_fargate_profiles(clusterName=cluster_name)
                    fargate_profiles = fargate_response.get('fargateProfileNames', [])
                    
                    if fargate_profiles:
                        print(f"Found {len(fargate_profiles)} Fargate profiles")
                        for profile_name in fargate_profiles:
                            try:
                                print(f"Deleting Fargate profile: {profile_name}")
                                eks_client.delete_fargate_profile(
                                    clusterName=cluster_name,
                                    fargateProfileName=profile_name
                                )
                                print(f"✅ Fargate profile {profile_name} deletion initiated")
                            except Exception as e:
                                print(f"❌ Failed to delete Fargate profile {profile_name}: {e}")
                        
                        # Wait for Fargate profiles to be deleted
                        print("Waiting for Fargate profiles to be deleted...")
                        for profile_name in fargate_profiles:
                            try:
                                waiter = eks_client.get_waiter('fargate_profile_deleted')
                                waiter.wait(
                                    clusterName=cluster_name,
                                    fargateProfileName=profile_name,
                                    WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                                )
                                print(f"✅ Fargate profile {profile_name} deleted")
                            except Exception as e:
                                print(f"⚠️ Timeout or error waiting for Fargate profile {profile_name}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process Fargate profiles: {e}")
                
                # 2. Delete all node groups
                try:
                    nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                    nodegroup_names = nodegroups_response.get('nodegroups', [])
                    
                    if nodegroup_names:
                        print(f"Found {len(nodegroup_names)} node groups")
                        
                        # Get detailed info about node groups and their ASGs
                        for nodegroup_name in nodegroup_names:
                            try:
                                nodegroup_detail = eks_client.describe_nodegroup(
                                    clusterName=cluster_name,
                                    nodegroupName=nodegroup_name
                                )
                                
                                nodegroup = nodegroup_detail['nodegroup']
                                nodegroup_status = nodegroup['status']
                                
                                print(f"Processing node group: {nodegroup_name} (Status: {nodegroup_status})")
                                
                                # Get Auto Scaling Group info
                                asg_name = nodegroup.get('resources', {}).get('autoScalingGroups', [])
                                if asg_name:
                                    for asg in asg_name:
                                        asg_name_str = asg.get('name')
                                        if asg_name_str:
                                            print(f"Found associated ASG: {asg_name_str}")
                                
                                # Delete the node group
                                print(f"Deleting node group: {nodegroup_name}")
                                eks_client.delete_nodegroup(
                                    clusterName=cluster_name,
                                    nodegroupName=nodegroup_name
                                )
                                print(f"✅ Node group {nodegroup_name} deletion initiated")
                                
                            except Exception as e:
                                print(f"❌ Failed to delete node group {nodegroup_name}: {e}")
                        
                        # Wait for all node groups to be deleted
                        print("Waiting for all node groups to be deleted...")
                        for nodegroup_name in nodegroup_names:
                            try:
                                waiter = eks_client.get_waiter('nodegroup_deleted')
                                waiter.wait(
                                    clusterName=cluster_name,
                                    nodegroupName=nodegroup_name,
                                    WaiterConfig={'Delay': 30, 'MaxAttempts': 60}
                                )
                                print(f"✅ Node group {nodegroup_name} deleted")
                            except Exception as e:
                                print(f"⚠️ Timeout or error waiting for node group {nodegroup_name}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process node groups: {e}")
                
                # 3. Delete associated AWS Load Balancer Controller resources
                try:
                    # Find and delete load balancers created by the cluster
                    elb_client = boto3.client('elbv2', region_name=region)
                    classic_elb_client = boto3.client('elb', region_name=region)
                    
                    # Delete Application/Network Load Balancers
                    try:
                        albs = elb_client.describe_load_balancers()
                        for alb in albs.get('LoadBalancers', []):
                            alb_tags = elb_client.describe_tags(ResourceArns=[alb['LoadBalancerArn']])
                            for tag_desc in alb_tags.get('TagDescriptions', []):
                                for tag in tag_desc.get('Tags', []):
                                    if (tag['Key'] == 'kubernetes.io/cluster/' + cluster_name or 
                                        tag['Key'] == 'elbv2.k8s.aws/cluster' and cluster_name in tag['Value']):
                                        try:
                                            print(f"Deleting ALB/NLB: {alb['LoadBalancerName']}")
                                            elb_client.delete_load_balancer(LoadBalancerArn=alb['LoadBalancerArn'])
                                            print(f"✅ Deleted ALB/NLB: {alb['LoadBalancerName']}")
                                        except Exception as e:
                                            print(f"❌ Failed to delete ALB/NLB {alb['LoadBalancerName']}: {e}")
                                        break
                    except Exception as e:
                        print(f"Warning: Could not process ALBs/NLBs: {e}")
                    
                    # Delete Classic Load Balancers
                    try:
                        clbs = classic_elb_client.describe_load_balancers()
                        for clb in clbs.get('LoadBalancerDescriptions', []):
                            clb_tags = classic_elb_client.describe_tags(LoadBalancerNames=[clb['LoadBalancerName']])
                            for tag_desc in clb_tags.get('TagDescriptions', []):
                                for tag in tag_desc.get('Tags', []):
                                    if tag['Key'] == 'kubernetes.io/cluster/' + cluster_name:
                                        try:
                                            print(f"Deleting Classic LB: {clb['LoadBalancerName']}")
                                            classic_elb_client.delete_load_balancer(LoadBalancerName=clb['LoadBalancerName'])
                                            print(f"✅ Deleted Classic LB: {clb['LoadBalancerName']}")
                                        except Exception as e:
                                            print(f"❌ Failed to delete Classic LB {clb['LoadBalancerName']}: {e}")
                                        break
                    except Exception as e:
                        print(f"Warning: Could not process Classic LBs: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process load balancers: {e}")
                
                # 4. Delete cluster security groups (but not VPC default ones)
                try:
                    cluster_sg_id = cluster.get('resourcesVpcConfig', {}).get('clusterSecurityGroupId')
                    additional_sgs = cluster.get('resourcesVpcConfig', {}).get('securityGroupIds', [])
                    
                    all_sgs = []
                    if cluster_sg_id:
                        all_sgs.append(cluster_sg_id)
                    all_sgs.extend(additional_sgs)
                    
                    for sg_id in all_sgs:
                        try:
                            # Get security group details
                            sg_response = ec2_client.describe_security_groups(GroupIds=[sg_id])
                            sg = sg_response['SecurityGroups'][0]
                            sg_name = sg['GroupName']
                            
                            # Don't delete default VPC security group
                            if sg_name != 'default':
                                print(f"Will delete security group: {sg_name} ({sg_id}) after cluster deletion")
                            else:
                                print(f"Skipping default security group: {sg_name} ({sg_id})")
                        except Exception as e:
                            print(f"Warning: Could not describe security group {sg_id}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process security groups: {e}")
                
                # 5. Delete add-ons
                try:
                    addons_response = eks_client.list_addons(clusterName=cluster_name)
                    addons = addons_response.get('addons', [])
                    
                    if addons:
                        print(f"Found {len(addons)} add-ons")
                        for addon_name in addons:
                            try:
                                print(f"Deleting add-on: {addon_name}")
                                eks_client.delete_addon(
                                    clusterName=cluster_name,
                                    addonName=addon_name,
                                    preserve=False
                                )
                                print(f"✅ Add-on {addon_name} deletion initiated")
                            except Exception as e:
                                print(f"❌ Failed to delete add-on {addon_name}: {e}")
                        
                        # Wait for add-ons to be deleted
                        print("Waiting for add-ons to be deleted...")
                        for addon_name in addons:
                            try:
                                waiter = eks_client.get_waiter('addon_deleted')
                                waiter.wait(
                                    clusterName=cluster_name,
                                    addonName=addon_name,
                                    WaiterConfig={'Delay': 15, 'MaxAttempts': 40}
                                )
                                print(f"✅ Add-on {addon_name} deleted")
                            except Exception as e:
                                print(f"⚠️ Timeout or error waiting for add-on {addon_name}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process add-ons: {e}")
                
                # 6. Delete the EKS cluster
                print(f"Deleting EKS cluster: {cluster_name}")
                eks_client.delete_cluster(name=cluster_name)
                print(f"✅ EKS cluster {cluster_name} deletion initiated")
                
                # Wait for cluster to be deleted
                print(f"Waiting for cluster {cluster_name} to be deleted...")
                try:
                    waiter = eks_client.get_waiter('cluster_deleted')
                    waiter.wait(
                        name=cluster_name,
                        WaiterConfig={'Delay': 30, 'MaxAttempts': 80}  # 40 minutes max
                    )
                    print(f"✅ EKS cluster {cluster_name} deleted")
                except Exception as e:
                    print(f"⚠️ Timeout or error waiting for cluster deletion: {e}")
                
                # 7. Clean up remaining security groups after cluster deletion
                try:
                    if 'all_sgs' in locals():
                        for sg_id in all_sgs:
                            try:
                                sg_response = ec2_client.describe_security_groups(GroupIds=[sg_id])
                                sg = sg_response['SecurityGroups'][0]
                                sg_name = sg['GroupName']
                                
                                if sg_name != 'default':
                                    print(f"Deleting security group: {sg_name} ({sg_id})")
                                    ec2_client.delete_security_group(GroupId=sg_id)
                                    print(f"✅ Deleted security group: {sg_name}")
                            except Exception as e:
                                print(f"❌ Failed to delete security group {sg_id}: {e}")
                except Exception as e:
                    print(f"Warning: Could not clean up security groups: {e}")
                
            except Exception as e:
                print(f"❌ Failed to process EKS cluster {cluster_name}: {e}")
        
        print(f"✅ Completed EKS cluster cleanup in {region}")
        
    except Exception as e:
        print(f"❌ Error processing EKS clusters in {region}: {e}")

@measure_time
def delete_codecommit_repositories(region):
    codecommit_client = boto3.client('codecommit', region_name=region)
    repositories = codecommit_client.list_repositories()['repositories']
    for repo in repositories:
        repo_name = repo['repositoryName']
        try:
            codecommit_client.delete_repository(repositoryName=repo_name)
            print(f"CodeCommit repository {repo_name} deleted successfully")
        except Exception as e:
            print(f"Failed to delete CodeCommit repository {repo_name}: {e}")

@measure_time
def delete_codedeploy_applications(region):
    codedeploy_client = boto3.client('codedeploy', region_name=region)
    applications = codedeploy_client.list_applications()['applications']
    for app in applications:
        deployment_groups = codedeploy_client.list_deployment_groups(applicationName=app)['deploymentGroups']
        for group in deployment_groups:
            codedeploy_client.delete_deployment_group(applicationName=app, deploymentGroupName=group)
            print(f"Deployment group {group} deleted from application {app}")
        try:
            codedeploy_client.delete_application(applicationName=app)
            print(f"CodeDeploy application {app} deleted successfully")
        except Exception as e:
            print(f"Failed to delete CodeDeploy application {app}: {e}")


@measure_time
@measure_time
def delete_elastic_beanstalk_applications(region):
    eb_client = boto3.client('elasticbeanstalk', region_name=region)

    # List all Elastic Beanstalk applications
    try:
        applications = eb_client.describe_applications()['Applications']
        print(f"Found {len(applications)} Elastic Beanstalk applications in {region}")
    except Exception as e:
        print(f"Failed to list Elastic Beanstalk applications: {e}")
        return
    
    for app in applications:
        app_name = app['ApplicationName']
        print(f"Processing Elastic Beanstalk application: {app_name}")

        try:
            # List ALL environments for the application (don't filter by status)
            environments_response = eb_client.describe_environments(ApplicationName=app_name)
            environments = environments_response['Environments']
            
            print(f"Found {len(environments)} environments for application {app_name}")
            
            # Terminate all environments regardless of current status
            for env in environments:
                env_name = env['EnvironmentName']
                env_id = env['EnvironmentId']
                env_status = env['Status']
                
                print(f"Environment: {env_name} (ID: {env_id}, Status: {env_status})")
                
                # Only terminate if not already terminated/terminating
                if env_status not in ['Terminated', 'Terminating']:
                    print(f"Terminating environment: {env_name} (ID: {env_id})")
                    try:
                        eb_client.terminate_environment(
                            EnvironmentId=env_id, 
                            TerminateResources=True,
                            ForceTerminate=True  # Add force terminate
                        )
                        print(f"✅ Environment {env_name} termination initiated")
                    except Exception as e:
                        print(f"❌ Failed to terminate environment {env_name}: {e}")
                        # Try alternative termination method
                        try:
                            eb_client.terminate_environment(
                                EnvironmentName=env_name,
                                TerminateResources=True,
                                ForceTerminate=True
                            )
                            print(f"✅ Environment {env_name} termination initiated (alternative method)")
                        except Exception as e2:
                            print(f"❌ Failed alternative termination for {env_name}: {e2}")
                else:
                    print(f"Environment {env_name} is already {env_status}")

            # Wait for ALL environments to be terminated
            if environments:
                print(f"Waiting for all environments to be terminated for application {app_name}...")
                max_wait_time = 1800  # 30 minutes max wait
                wait_time = 0
                check_interval = 30
                
                while wait_time < max_wait_time:
                    try:
                        current_environments = eb_client.describe_environments(ApplicationName=app_name)['Environments']
                        
                        # Filter out terminated environments
                        active_environments = [env for env in current_environments if env['Status'] != 'Terminated']
                        
                        if not active_environments:
                            print(f"✅ All environments terminated for application {app_name}")
                            break
                        
                        print(f"Still waiting... {len(active_environments)} environments remaining:")
                        for env in active_environments:
                            print(f"  - {env['EnvironmentName']}: {env['Status']}")
                        
                        time.sleep(check_interval)
                        wait_time += check_interval
                        
                    except Exception as e:
                        print(f"Error checking environment status: {e}")
                        break
                
                if wait_time >= max_wait_time:
                    print(f"⚠️ Timeout waiting for environments to terminate for {app_name}")

        except Exception as e:
            print(f"❌ Failed to process environments for application {app_name}: {e}")

        # Delete the application
        try:
            print(f"Deleting application: {app_name}")
            eb_client.delete_application(
                ApplicationName=app_name, 
                TerminateEnvByForce=True
            )
            print(f"✅ Application {app_name} deleted successfully")
        except Exception as e:
            print(f"❌ Failed to delete application {app_name}: {e}")
            # Try to force delete application versions first
            try:
                print(f"Attempting to delete application versions for {app_name}")
                versions = eb_client.describe_application_versions(ApplicationName=app_name)['ApplicationVersions']
                for version in versions:
                    if not version.get('SourceBundle'):  # Don't delete if it has source bundle
                        try:
                            eb_client.delete_application_version(
                                ApplicationName=app_name,
                                VersionLabel=version['VersionLabel'],
                                DeleteSourceBundle=True
                            )
                            print(f"Deleted version: {version['VersionLabel']}")
                        except:
                            pass
                
                # Retry application deletion
                eb_client.delete_application(ApplicationName=app_name, TerminateEnvByForce=True)
                print(f"✅ Application {app_name} deleted successfully (retry)")
            except Exception as e2:
                print(f"❌ Final attempt failed for application {app_name}: {e2}")

    print(f"✅ Completed processing Elastic Beanstalk applications in {region}")

@measure_time
def delete_all_sns_subscriptions(region):
    sns_client = boto3.client('sns', region_name=region)

    # List and delete all subscriptions in the account
    while True:
        subscriptions = sns_client.list_subscriptions()['Subscriptions']
        if not subscriptions:
            break
        
        valid_subscriptions = []
        for subscription in subscriptions:
            subscription_arn = subscription['SubscriptionArn']
            
            # Skip subscriptions that are in PendingConfirmation state
            if subscription_arn == 'PendingConfirmation':
                print(f"Skipping pending confirmation subscription for topic: {subscription.get('TopicArn', 'Unknown')}")
                continue
            
            # Skip invalid ARNs (must have at least 6 elements separated by colons)
            if len(subscription_arn.split(':')) < 6:
                print(f"Skipping invalid subscription ARN: {subscription_arn}")
                continue
                
            valid_subscriptions.append(subscription)
        
        if not valid_subscriptions:
            print("No valid subscriptions to delete")
            break
            
        for subscription in valid_subscriptions:
            subscription_arn = subscription['SubscriptionArn']
            try:
                print(f"Deleting subscription {subscription_arn}")
                sns_client.unsubscribe(SubscriptionArn=subscription_arn)
                print(f"✅ Deleted subscription: {subscription_arn}")
            except Exception as e:
                print(f"❌ Failed to delete subscription {subscription_arn}: {e}")
        
        print("Waiting for subscriptions to be deleted...")
        time.sleep(5)  # Reduced wait time since we're being more selective
    
@measure_time
def delete_all_ecs_clusters(region):
    ecs_client = boto3.client('ecs', region_name=region)
    ec2_client = boto3.client('ec2', region_name=region)
    
    try:
        # List all ECS clusters
        response = ecs_client.list_clusters()
        cluster_arns = response.get('clusterArns', [])
        
        if not cluster_arns:
            print(f"No ECS clusters found in {region}")
            return
        
        # Get detailed cluster information
        clusters_response = ecs_client.describe_clusters(clusters=cluster_arns)
        clusters = clusters_response.get('clusters', [])
        
        print(f"Found {len(clusters)} ECS clusters in {region}")
        
        for cluster in clusters:
            cluster_name = cluster['clusterName']
            cluster_arn = cluster['clusterArn']
            cluster_status = cluster['status']
            
            print(f"\n{'='*80}")
            print(f"Processing ECS cluster: {cluster_name} (Status: {cluster_status})")
            print(f"{'='*80}")
            
            try:
                # 1. Stop and delete all services in the cluster
                services_response = ecs_client.list_services(cluster=cluster_arn)
                service_arns = services_response.get('serviceArns', [])
                
                if service_arns:
                    print(f"Found {len(service_arns)} services in cluster {cluster_name}")
                    
                    # Get service details
                    services_detail = ecs_client.describe_services(
                        cluster=cluster_arn,
                        services=service_arns
                    )
                    
                    for service in services_detail.get('services', []):
                        service_name = service['serviceName']
                        service_status = service['status']
                        desired_count = service['desiredCount']
                        
                        print(f"Processing service: {service_name} (Status: {service_status}, Desired: {desired_count})")
                        
                        try:
                            # Scale down to 0 first
                            if desired_count > 0:
                                print(f"Scaling down service {service_name} to 0")
                                ecs_client.update_service(
                                    cluster=cluster_arn,
                                    service=service_name,
                                    desiredCount=0
                                )
                                
                                # Wait for service to scale down
                                print(f"Waiting for service {service_name} to scale down...")
                                waiter = ecs_client.get_waiter('services_stable')
                                waiter.wait(
                                    cluster=cluster_arn,
                                    services=[service_name],
                                    WaiterConfig={'Delay': 15, 'MaxAttempts': 40}
                                )
                            
                            # Delete the service
                            print(f"Deleting service: {service_name}")
                            ecs_client.delete_service(
                                cluster=cluster_arn,
                                service=service_name,
                                force=True
                            )
                            print(f"✅ Deleted service: {service_name}")
                            
                        except Exception as e:
                            print(f"❌ Failed to delete service {service_name}: {e}")
                
                # 2. Stop all running tasks
                tasks_response = ecs_client.list_tasks(cluster=cluster_arn)
                task_arns = tasks_response.get('taskArns', [])
                
                if task_arns:
                    print(f"Found {len(task_arns)} tasks in cluster {cluster_name}")
                    for task_arn in task_arns:
                        try:
                            print(f"Stopping task: {task_arn}")
                            ecs_client.stop_task(
                                cluster=cluster_arn,
                                task=task_arn,
                                reason='Cluster cleanup by varadharajaan at 2025-06-11 09:11:02 UTC'
                            )
                            print(f"✅ Stopped task: {task_arn}")
                        except Exception as e:
                            print(f"❌ Failed to stop task {task_arn}: {e}")
                
                # 3. Deregister container instances
                instances_response = ecs_client.list_container_instances(cluster=cluster_arn)
                instance_arns = instances_response.get('containerInstanceArns', [])
                
                if instance_arns:
                    print(f"Found {len(instance_arns)} container instances in cluster {cluster_name}")
                    
                    # Get instance details
                    instances_detail = ecs_client.describe_container_instances(
                        cluster=cluster_arn,
                        containerInstances=instance_arns
                    )
                    
                    for instance in instances_detail.get('containerInstances', []):
                        instance_arn = instance['containerInstanceArn']
                        ec2_instance_id = instance.get('ec2InstanceId')
                        
                        try:
                            print(f"Deregistering container instance: {instance_arn}")
                            ecs_client.deregister_container_instance(
                                cluster=cluster_arn,
                                containerInstance=instance_arn,
                                force=True
                            )
                            print(f"✅ Deregistered container instance: {instance_arn}")
                            
                            # Terminate the underlying EC2 instance if it exists
                            if ec2_instance_id:
                                try:
                                    print(f"Terminating EC2 instance: {ec2_instance_id}")
                                    ec2_client.terminate_instances(InstanceIds=[ec2_instance_id])
                                    print(f"✅ Terminated EC2 instance: {ec2_instance_id}")
                                except Exception as e:
                                    print(f"❌ Failed to terminate EC2 instance {ec2_instance_id}: {e}")
                            
                        except Exception as e:
                            print(f"❌ Failed to deregister container instance {instance_arn}: {e}")
                
                # 4. Delete capacity providers associated with the cluster
                try:
                    cluster_detail = ecs_client.describe_clusters(
                        clusters=[cluster_arn],
                        include=['CAPACITY_PROVIDERS']
                    )
                    
                    if cluster_detail.get('clusters'):
                        capacity_providers = cluster_detail['clusters'][0].get('capacityProviders', [])
                        if capacity_providers:
                            print(f"Found capacity providers: {capacity_providers}")
                            # Note: Capacity providers are usually shared, so we just disassociate
                            try:
                                ecs_client.put_cluster_capacity_providers(
                                    cluster=cluster_arn,
                                    capacityProviders=[],
                                    defaultCapacityProviderStrategy=[]
                                )
                                print(f"✅ Disassociated capacity providers from cluster")
                            except Exception as e:
                                print(f"❌ Failed to disassociate capacity providers: {e}")
                except Exception as e:
                    print(f"Warning: Could not check capacity providers: {e}")
                
                # 5. Wait for all services to be deleted
                if service_arns:
                    print(f"Waiting for all services to be completely deleted...")
                    max_wait = 600  # 10 minutes
                    wait_time = 0
                    while wait_time < max_wait:
                        try:
                            current_services = ecs_client.list_services(cluster=cluster_arn)
                            if not current_services.get('serviceArns'):
                                print(f"✅ All services deleted from cluster {cluster_name}")
                                break
                            print(f"Still waiting for services to be deleted... ({len(current_services.get('serviceArns', []))} remaining)")
                            time.sleep(30)
                            wait_time += 30
                        except:
                            break
                
                # 6. Delete the cluster
                print(f"Deleting ECS cluster: {cluster_name}")
                ecs_client.delete_cluster(cluster=cluster_arn)
                print(f"✅ Deleted ECS cluster: {cluster_name}")
                
            except Exception as e:
                print(f"❌ Failed to process ECS cluster {cluster_name}: {e}")
        
        print(f"✅ Completed ECS cluster cleanup in {region}")
        
    except Exception as e:
        print(f"❌ Error processing ECS clusters in {region}: {e}")

@measure_time
def stop_codebuild_builds(region):
    codebuild_client = boto3.client('codebuild', region_name=region)
    
    try:
        # Get all builds (not just IDs)
        response = codebuild_client.list_builds()
        build_ids = response.get('ids', [])
        
        if not build_ids:
            print(f"No CodeBuild builds found in {region}")
            return
            
        print(f"Found {len(build_ids)} CodeBuild builds in {region}")
        
        # Get detailed build information
        builds_response = codebuild_client.batch_get_builds(ids=build_ids)
        builds = builds_response.get('builds', [])
        
        for build in builds:
            build_id = build['id']
            build_status = build['buildStatus']
            project_name = build.get('projectName', 'Unknown')
            
            print(f"Build: {build_id}, Project: {project_name}, Status: {build_status}")
            
            if build_status in ['IN_PROGRESS', 'QUEUED', 'SUBMITTED', 'PROVISIONING', 'DOWNLOAD_SOURCE', 'INSTALL', 'PRE_BUILD', 'BUILD', 'POST_BUILD', 'UPLOAD_ARTIFACTS', 'FINALIZING']:
                try:
                    print(f"Stopping CodeBuild build: {build_id} (Status: {build_status})")
                    codebuild_client.stop_build(id=build_id)
                    print(f"✅ Stopped build: {build_id}")
                except Exception as e:
                    print(f"❌ Failed to stop build {build_id}: {e}")
            else:
                print(f"Build {build_id} is already {build_status}, no need to stop")
                
    except Exception as e:
        print(f"❌ Error processing CodeBuild builds in {region}: {e}")

@measure_time
def delete_codebuild_projects(region):
    codebuild_client = boto3.client('codebuild', region_name=region)
    
    try:
        # List all projects
        response = codebuild_client.list_projects()
        projects = response.get('projects', [])
        
        if not projects:
            print(f"No CodeBuild projects found in {region}")
            return
            
        print(f"Found {len(projects)} CodeBuild projects in {region}")

        for project in projects:
            try:
                # First, get project details to check for running builds
                project_details = codebuild_client.batch_get_projects(names=[project])
                if project_details['projects']:
                    print(f"Processing CodeBuild project: {project}")
                    
                    # List builds for this project
                    builds_for_project = codebuild_client.list_builds_for_project(projectName=project)
                    build_ids = builds_for_project.get('ids', [])
                    
                    if build_ids:
                        # Get build statuses
                        builds_info = codebuild_client.batch_get_builds(ids=build_ids)
                        for build in builds_info.get('builds', []):
                            if build['buildStatus'] in ['IN_PROGRESS', 'QUEUED', 'SUBMITTED']:
                                try:
                                    print(f"Stopping active build {build['id']} before deleting project")
                                    codebuild_client.stop_build(id=build['id'])
                                    time.sleep(5)  # Wait a bit for build to stop
                                except Exception as e:
                                    print(f"Warning: Could not stop build {build['id']}: {e}")
                    
                    # Delete the project
                    print(f"Deleting CodeBuild project: {project}")
                    codebuild_client.delete_project(name=project)
                    print(f"✅ Deleted CodeBuild project: {project}")
                    
            except Exception as e:
                print(f"❌ Failed to delete CodeBuild project {project}: {e}")
                
    except Exception as e:
        print(f"❌ Error processing CodeBuild projects in {region}: {e}")
        
@measure_time
def stop_codepipeline_executions(region):
    codepipeline_client = boto3.client('codepipeline', region_name=region)
    
    try:
        response = codepipeline_client.list_pipelines()
        pipelines = response.get('pipelines', [])
        
        if not pipelines:
            print(f"No CodePipeline pipelines found in {region}")
            return
            
        print(f"Found {len(pipelines)} CodePipeline pipelines in {region}")

        for pipeline in pipelines:
            pipeline_name = pipeline['name']
            try:
                print(f"Checking executions for pipeline: {pipeline_name}")
                
                # Get pipeline executions
                executions_response = codepipeline_client.list_pipeline_executions(pipelineName=pipeline_name)
                executions = executions_response.get('pipelineExecutionSummaries', [])
                
                for execution in executions:
                    execution_id = execution['pipelineExecutionId']
                    status = execution['status']
                    
                    print(f"Execution: {execution_id}, Status: {status}")
                    
                    if status in ['InProgress', 'Stopping', 'Queued']:
                        try:
                            print(f"Stopping CodePipeline execution: {execution_id} for pipeline: {pipeline_name}")
                            codepipeline_client.stop_pipeline_execution(
                                pipelineName=pipeline_name, 
                                pipelineExecutionId=execution_id,
                                abandon=True  # Force stop
                            )
                            print(f"✅ Stopped execution: {execution_id}")
                        except Exception as e:
                            print(f"❌ Failed to stop execution {execution_id}: {e}")
                    else:
                        print(f"Execution {execution_id} is {status}, no action needed")
                        
            except Exception as e:
                print(f"❌ Failed to process pipeline {pipeline_name}: {e}")
                
    except Exception as e:
        print(f"❌ Error processing CodePipeline executions in {region}: {e}")

@measure_time
def delete_codepipelines(region):
    codepipeline_client = boto3.client('codepipeline', region_name=region)
    
    try:
        response = codepipeline_client.list_pipelines()
        pipelines = response.get('pipelines', [])
        
        if not pipelines:
            print(f"No CodePipeline pipelines found in {region}")
            return
            
        print(f"Found {len(pipelines)} CodePipeline pipelines to delete in {region}")

        for pipeline in pipelines:
            pipeline_name = pipeline['name']
            try:
                print(f"Deleting CodePipeline: {pipeline_name}")
                
                # First, ensure all executions are stopped
                try:
                    executions = codepipeline_client.list_pipeline_executions(pipelineName=pipeline_name)
                    for execution in executions.get('pipelineExecutionSummaries', []):
                        if execution['status'] in ['InProgress', 'Stopping', 'Queued']:
                            try:
                                codepipeline_client.stop_pipeline_execution(
                                    pipelineName=pipeline_name,
                                    pipelineExecutionId=execution['pipelineExecutionId'],
                                    abandon=True
                                )
                                print(f"Stopped execution {execution['pipelineExecutionId']} before deletion")
                            except:
                                pass  # Continue even if stopping fails
                except:
                    pass  # Continue even if listing executions fails
                
                # Wait a moment for executions to stop
                time.sleep(3)
                
                # Delete the pipeline
                codepipeline_client.delete_pipeline(name=pipeline_name)
                print(f"✅ Deleted CodePipeline: {pipeline_name}")
                
            except Exception as e:
                print(f"❌ Failed to delete CodePipeline {pipeline_name}: {e}")
                
    except Exception as e:
        print(f"❌ Error processing CodePipeline deletion in {region}: {e}")


@measure_time
def delete_route53_hosted_zones(region):
    route53_client = boto3.client('route53')  # Route53 is global, no region needed
    
    try:
        # List all hosted zones
        response = route53_client.list_hosted_zones()
        hosted_zones = response.get('HostedZones', [])
        
        if not hosted_zones:
            print(f"No Route53 hosted zones found")
            return
            
        print(f"Found {len(hosted_zones)} Route53 hosted zones")
        
        zones_to_process = []
        
        # Filter zones if region-specific logic is needed
        for zone in hosted_zones:
            zone_id = zone['Id'].replace('/hostedzone/', '')
            zone_name = zone['Name']
            zone_type = "Private" if zone.get('Config', {}).get('PrivateZone', False) else "Public"
            
            print(f"Processing {zone_type} hosted zone: {zone_name} (ID: {zone_id})")
            
            # For private zones, check if they're associated with VPCs in the target region
            if zone.get('Config', {}).get('PrivateZone', False):
                try:
                    # Get VPC associations for private zones
                    vpc_response = route53_client.list_vpc_association_authorizations(HostedZoneId=zone_id)
                    vpcs = vpc_response.get('VPCs', [])
                    
                    # Also get direct VPC associations
                    zone_details = route53_client.get_hosted_zone(Id=zone_id)
                    zone_vpcs = zone_details.get('VPCs', [])
                    
                    region_match = False
                    for vpc in vpcs + zone_vpcs:
                        if vpc.get('VPCRegion') == region:
                            region_match = True
                            break
                    
                    if region_match:
                        zones_to_process.append(zone)
                        print(f"Private zone {zone_name} has VPCs in {region}, will process")
                    else:
                        print(f"Private zone {zone_name} has no VPCs in {region}, skipping")
                        
                except Exception as e:
                    print(f"Warning: Could not check VPC associations for {zone_name}: {e}")
                    # Process anyway if we can't determine VPC associations
                    zones_to_process.append(zone)
            else:
                # Process all public zones (they're global anyway)
                zones_to_process.append(zone)
        
        print(f"Will process {len(zones_to_process)} hosted zones")
        
        for zone in zones_to_process:
            zone_id = zone['Id'].replace('/hostedzone/', '')
            zone_name = zone['Name']
            zone_type = "Private" if zone.get('Config', {}).get('PrivateZone', False) else "Public"
            
            try:
                print(f"\n{'='*80}")
                print(f"Processing {zone_type} hosted zone: {zone_name} (ID: {zone_id})")
                print(f"{'='*80}")
                
                # Get all resource record sets
                paginator = route53_client.get_paginator('list_resource_record_sets')
                page_iterator = paginator.paginate(HostedZoneId=zone_id)
                
                records_to_delete = []
                
                for page in page_iterator:
                    for record in page['ResourceRecordSets']:
                        record_name = record['Name']
                        record_type = record['Type']
                        
                        # Skip NS and SOA records for the zone apex (these are managed by AWS)
                        if record_type in ['NS', 'SOA'] and record_name.rstrip('.') == zone_name.rstrip('.'):
                            print(f"Skipping managed record: {record_name} ({record_type})")
                            continue
                        
                        records_to_delete.append(record)
                        print(f"Found record to delete: {record_name} ({record_type})")
                
                # Delete records in batches
                if records_to_delete:
                    print(f"Deleting {len(records_to_delete)} records from {zone_name}...")
                    
                    # Process records in batches of 100 (Route53 limit)
                    batch_size = 100
                    for i in range(0, len(records_to_delete), batch_size):
                        batch = records_to_delete[i:i+batch_size]
                        
                        changes = []
                        for record in batch:
                            changes.append({
                                'Action': 'DELETE',
                                'ResourceRecordSet': record
                            })
                        
                        try:
                            change_batch = {
                                'Comment': f'Batch deletion by varadharajaan at 2025-06-11 09:09:36 UTC',
                                'Changes': changes
                            }
                            
                            change_response = route53_client.change_resource_record_sets(
                                HostedZoneId=zone_id,
                                ChangeBatch=change_batch
                            )
                            
                            change_id = change_response['ChangeInfo']['Id']
                            print(f"✅ Submitted batch deletion (Change ID: {change_id})")
                            
                            # Wait for change to propagate
                            print(f"Waiting for change {change_id} to complete...")
                            waiter = route53_client.get_waiter('resource_record_sets_changed')
                            waiter.wait(Id=change_id, WaiterConfig={'Delay': 10, 'MaxAttempts': 60})
                            print(f"✅ Change {change_id} completed")
                            
                        except Exception as e:
                            print(f"❌ Failed to delete batch of records: {e}")
                            # Try deleting records individually
                            for record in batch:
                                try:
                                    individual_change = {
                                        'Comment': f'Individual deletion by varadharajaan',
                                        'Changes': [{
                                            'Action': 'DELETE',
                                            'ResourceRecordSet': record
                                        }]
                                    }
                                    
                                    route53_client.change_resource_record_sets(
                                        HostedZoneId=zone_id,
                                        ChangeBatch=individual_change
                                    )
                                    print(f"✅ Deleted record: {record['Name']} ({record['Type']})")
                                    time.sleep(1)  # Rate limiting
                                    
                                except Exception as individual_error:
                                    print(f"❌ Failed to delete record {record['Name']} ({record['Type']}): {individual_error}")
                else:
                    print(f"No user-created records to delete in {zone_name}")
                
                # Disassociate VPCs from private hosted zones before deletion
                if zone.get('Config', {}).get('PrivateZone', False):
                    try:
                        zone_details = route53_client.get_hosted_zone(Id=zone_id)
                        vpcs = zone_details.get('VPCs', [])
                        
                        for vpc in vpcs:
                            vpc_id = vpc['VPCId']
                            vpc_region = vpc['VPCRegion']
                            try:
                                print(f"Disassociating VPC {vpc_id} ({vpc_region}) from private zone {zone_name}")
                                route53_client.disassociate_vpc_from_hosted_zone(
                                    HostedZoneId=zone_id,
                                    VPC={
                                        'VPCRegion': vpc_region,
                                        'VPCId': vpc_id
                                    }
                                )
                                print(f"✅ Disassociated VPC {vpc_id}")
                            except Exception as e:
                                print(f"❌ Failed to disassociate VPC {vpc_id}: {e}")
                                
                    except Exception as e:
                        print(f"Warning: Could not get VPC associations for {zone_name}: {e}")
                
                # Delete the hosted zone
                print(f"Deleting hosted zone: {zone_name}")
                route53_client.delete_hosted_zone(Id=zone_id)
                print(f"✅ Deleted hosted zone: {zone_name}")
                
            except Exception as e:
                print(f"❌ Failed to process hosted zone {zone_name}: {e}")
                
        print(f"✅ Completed Route53 hosted zone cleanup")
        
    except Exception as e:
        print(f"❌ Error processing Route53 hosted zones: {e}")
        

@measure_time
def purge_and_delete_sqs_queues(region):
    sqs_client = boto3.client('sqs', region_name=region)
    queues = sqs_client.list_queues().get('QueueUrls', [])

    for queue in queues:
        print(f"Purging SQS queue: {queue} in {region}")
        sqs_client.purge_queue(QueueUrl=queue)
        print(f"Deleting SQS queue: {queue} in {region}")
        sqs_client.delete_queue(QueueUrl=queue)

@measure_time
@measure_time
def delete_sns_topics(region):
    sns_client = boto3.client('sns', region_name=region)
    topics = sns_client.list_topics()['Topics']

    for topic in topics:
        topic_arn = topic['TopicArn']
        try:
            subscriptions = sns_client.list_subscriptions_by_topic(TopicArn=topic_arn)['Subscriptions']
            
            for subscription in subscriptions:
                subscription_arn = subscription['SubscriptionArn']
                
                # Skip pending confirmations and invalid ARNs
                if subscription_arn == 'PendingConfirmation':
                    print(f"Skipping pending confirmation subscription for topic: {topic_arn}")
                    continue
                    
                if len(subscription_arn.split(':')) < 6:
                    print(f"Skipping invalid subscription ARN: {subscription_arn}")
                    continue
                
                try:
                    print(f"Unsubscribing: {subscription_arn} from topic: {topic_arn} in {region}")
                    sns_client.unsubscribe(SubscriptionArn=subscription_arn)
                except Exception as e:
                    print(f"❌ Failed to unsubscribe {subscription_arn}: {e}")

            print(f"Deleting SNS topic: {topic_arn} in {region}")
            sns_client.delete_topic(TopicArn=topic_arn)
            print(f"✅ Deleted SNS topic: {topic_arn}")
            
        except Exception as e:
            print(f"❌ Failed to process topic {topic_arn}: {e}")

@measure_time
def delete_rds_instances(region):
    rds_client = boto3.client('rds', region_name=region)
    
    print(f"Starting comprehensive RDS cleanup in {region}")
    print(f"Processing by: varadharajaan at 2025-06-11 18:55:43 UTC")
    
    try:
        # ========================================
        # 1. DELETE RDS INSTANCES
        # ========================================
        print(f"\n{'='*80}")
        print("PROCESSING RDS INSTANCES")
        print(f"{'='*80}")
        
        # Get all RDS instances
        paginator = rds_client.get_paginator('describe_db_instances')
        page_iterator = paginator.paginate()
        
        all_instances = []
        for page in page_iterator:
            all_instances.extend(page.get('DBInstances', []))
        
        if not all_instances:
            print("No RDS instances found")
        else:
            print(f"Found {len(all_instances)} RDS instances")
            
            for instance in all_instances:
                instance_id = instance['DBInstanceIdentifier']
                instance_class = instance['DBInstanceClass']
                engine = instance['Engine']
                engine_version = instance['EngineVersion']
                status = instance['DBInstanceStatus']
                multi_az = instance.get('MultiAZ', False)
                backup_retention = instance.get('BackupRetentionPeriod', 0)
                deletion_protection = instance.get('DeletionProtection', False)
                
                print(f"\n--- Processing RDS Instance ---")
                print(f"ID: {instance_id}")
                print(f"Class: {instance_class}")
                print(f"Engine: {engine} {engine_version}")
                print(f"Status: {status}")
                print(f"Multi-AZ: {multi_az}")
                print(f"Backup Retention: {backup_retention} days")
                print(f"Deletion Protection: {deletion_protection}")
                
                try:
                    # Skip if instance is already being deleted
                    if status in ['deleting', 'deleted']:
                        print(f"Instance {instance_id} is already {status}, skipping")
                        continue
                    
                    # Disable deletion protection if enabled
                    if deletion_protection:
                        print(f"Disabling deletion protection for {instance_id}")
                        try:
                            rds_client.modify_db_instance(
                                DBInstanceIdentifier=instance_id,
                                DeletionProtection=False,
                                ApplyImmediately=True
                            )
                            print(f"✅ Disabled deletion protection for {instance_id}")
                            
                            # Wait for modification to complete
                            print(f"Waiting for modification to complete...")
                            waiter = rds_client.get_waiter('db_instance_available')
                            waiter.wait(
                                DBInstanceIdentifier=instance_id,
                                WaiterConfig={'Delay': 30, 'MaxAttempts': 20}
                            )
                            print(f"✅ Modification completed for {instance_id}")
                        except Exception as e:
                            print(f"❌ Failed to disable deletion protection for {instance_id}: {e}")
                    
                    # Stop the instance if it's running (to save costs before deletion)
                    if status == 'available':
                        print(f"Stopping RDS instance {instance_id} before deletion")
                        try:
                            rds_client.stop_db_instance(DBInstanceIdentifier=instance_id)
                            print(f"✅ Stop initiated for {instance_id}")
                            
                            # Wait for instance to stop
                            print(f"Waiting for {instance_id} to stop...")
                            waiter = rds_client.get_waiter('db_instance_stopped')
                            waiter.wait(
                                DBInstanceIdentifier=instance_id,
                                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                            )
                            print(f"✅ {instance_id} stopped successfully")
                        except Exception as e:
                            print(f"Warning: Could not stop {instance_id}: {e}")
                    
                    # Delete the RDS instance
                    print(f"Deleting RDS instance: {instance_id}")
                    delete_params = {
                        'DBInstanceIdentifier': instance_id,
                        'SkipFinalSnapshot': True,  # Skip final snapshot
                        'DeleteAutomatedBackups': True  # Delete automated backups
                    }
                    
                    # For read replicas, we don't need final snapshot options
                    if instance.get('ReadReplicaSourceDBInstanceIdentifier'):
                        print(f"Deleting read replica: {instance_id}")
                        del delete_params['SkipFinalSnapshot']
                    
                    rds_client.delete_db_instance(**delete_params)
                    print(f"✅ Deletion initiated for RDS instance: {instance_id}")
                    
                except Exception as e:
                    print(f"❌ Failed to process RDS instance {instance_id}: {e}")
        
        # Wait for all instances to be deleted
        if all_instances:
            print(f"\nWaiting for all RDS instances to be deleted...")
            max_wait = 1800  # 30 minutes
            wait_time = 0
            check_interval = 60
            
            while wait_time < max_wait:
                try:
                    current_instances = rds_client.describe_db_instances()['DBInstances']
                    active_instances = [
                        inst for inst in current_instances 
                        if inst['DBInstanceStatus'] not in ['deleted', 'deleting']
                    ]
                    
                    if not active_instances:
                        print(f"✅ All RDS instances deleted")
                        break
                    
                    print(f"Still waiting... {len(active_instances)} instances remaining")
                    for inst in active_instances:
                        print(f"  - {inst['DBInstanceIdentifier']}: {inst['DBInstanceStatus']}")
                    
                    time.sleep(check_interval)
                    wait_time += check_interval
                    
                except Exception as e:
                    print(f"Error checking instance status: {e}")
                    break
            
            if wait_time >= max_wait:
                print(f"⚠️ Timeout waiting for RDS instances to be deleted")
        
        # ========================================
        # 2. DELETE RDS CLUSTERS (Aurora)
        # ========================================
        print(f"\n{'='*80}")
        print("PROCESSING RDS CLUSTERS (Aurora)")
        print(f"{'='*80}")
        
        # Get all RDS clusters
        try:
            clusters_response = rds_client.describe_db_clusters()
            clusters = clusters_response.get('DBClusters', [])
            
            if not clusters:
                print("No RDS clusters found")
            else:
                print(f"Found {len(clusters)} RDS clusters")
                
                for cluster in clusters:
                    cluster_id = cluster['DBClusterIdentifier']
                    engine = cluster['Engine']
                    engine_version = cluster['EngineVersion']
                    status = cluster['Status']
                    cluster_members = cluster.get('DBClusterMembers', [])
                    deletion_protection = cluster.get('DeletionProtection', False)
                    
                    print(f"\n--- Processing RDS Cluster ---")
                    print(f"ID: {cluster_id}")
                    print(f"Engine: {engine} {engine_version}")
                    print(f"Status: {status}")
                    print(f"Members: {len(cluster_members)}")
                    print(f"Deletion Protection: {deletion_protection}")
                    
                    try:
                        # Skip if cluster is already being deleted
                        if status in ['deleting', 'deleted']:
                            print(f"Cluster {cluster_id} is already {status}, skipping")
                            continue
                        
                        # Delete all cluster members first
                        if cluster_members:
                            print(f"Deleting {len(cluster_members)} cluster members...")
                            for member in cluster_members:
                                member_id = member['DBInstanceIdentifier']
                                is_writer = member['IsClusterWriter']
                                
                                print(f"Deleting cluster member: {member_id} (Writer: {is_writer})")
                                try:
                                    # Disable deletion protection for member if needed
                                    member_details = rds_client.describe_db_instances(
                                        DBInstanceIdentifier=member_id
                                    )['DBInstances'][0]
                                    
                                    if member_details.get('DeletionProtection', False):
                                        rds_client.modify_db_instance(
                                            DBInstanceIdentifier=member_id,
                                            DeletionProtection=False,
                                            ApplyImmediately=True
                                        )
                                        print(f"Disabled deletion protection for {member_id}")
                                        time.sleep(30)
                                    
                                    rds_client.delete_db_instance(
                                        DBInstanceIdentifier=member_id,
                                        SkipFinalSnapshot=True,
                                        DeleteAutomatedBackups=True
                                    )
                                    print(f"✅ Deletion initiated for cluster member: {member_id}")
                                except Exception as e:
                                    print(f"❌ Failed to delete cluster member {member_id}: {e}")
                            
                            # Wait for cluster members to be deleted
                            print(f"Waiting for cluster members to be deleted...")
                            max_member_wait = 900  # 15 minutes
                            member_wait_time = 0
                            
                            while member_wait_time < max_member_wait:
                                try:
                                    current_cluster = rds_client.describe_db_clusters(
                                        DBClusterIdentifier=cluster_id
                                    )['DBClusters'][0]
                                    
                                    remaining_members = current_cluster.get('DBClusterMembers', [])
                                    if not remaining_members:
                                        print(f"✅ All cluster members deleted")
                                        break
                                    
                                    print(f"Still waiting... {len(remaining_members)} members remaining")
                                    time.sleep(30)
                                    member_wait_time += 30
                                    
                                except Exception as e:
                                    print(f"Error checking cluster members: {e}")
                                    break
                        
                        # Disable deletion protection for cluster if enabled
                        if deletion_protection:
                            print(f"Disabling deletion protection for cluster {cluster_id}")
                            try:
                                rds_client.modify_db_cluster(
                                    DBClusterIdentifier=cluster_id,
                                    DeletionProtection=False,
                                    ApplyImmediately=True
                                )
                                print(f"✅ Disabled deletion protection for cluster {cluster_id}")
                                time.sleep(30)
                            except Exception as e:
                                print(f"❌ Failed to disable deletion protection for cluster {cluster_id}: {e}")
                        
                        # Delete the cluster
                        print(f"Deleting RDS cluster: {cluster_id}")
                        rds_client.delete_db_cluster(
                            DBClusterIdentifier=cluster_id,
                            SkipFinalSnapshot=True,
                            DeleteAutomatedBackups=True
                        )
                        print(f"✅ Deletion initiated for RDS cluster: {cluster_id}")
                        
                    except Exception as e:
                        print(f"❌ Failed to process RDS cluster {cluster_id}: {e}")
        
        except Exception as e:
            print(f"Warning: Could not process RDS clusters: {e}")
        
        # ========================================
        # 3. DELETE MANUAL SNAPSHOTS
        # ========================================
        print(f"\n{'='*80}")
        print("PROCESSING MANUAL SNAPSHOTS")
        print(f"{'='*80}")
        
        try:
            # Delete DB snapshots
            snapshots_response = rds_client.describe_db_snapshots(SnapshotType='manual')
            snapshots = snapshots_response.get('DBSnapshots', [])
            
            if snapshots:
                print(f"Found {len(snapshots)} manual DB snapshots")
                for snapshot in snapshots:
                    snapshot_id = snapshot['DBSnapshotIdentifier']
                    db_instance_id = snapshot.get('DBInstanceIdentifier', 'Unknown')
                    status = snapshot['Status']
                    created = snapshot.get('SnapshotCreateTime', 'Unknown')
                    
                    print(f"Deleting DB snapshot: {snapshot_id} (Instance: {db_instance_id}, Status: {status})")
                    try:
                        rds_client.delete_db_snapshot(DBSnapshotIdentifier=snapshot_id)
                        print(f"✅ Deleted DB snapshot: {snapshot_id}")
                    except Exception as e:
                        print(f"❌ Failed to delete DB snapshot {snapshot_id}: {e}")
            else:
                print("No manual DB snapshots found")
            
            # Delete cluster snapshots
            cluster_snapshots_response = rds_client.describe_db_cluster_snapshots(SnapshotType='manual')
            cluster_snapshots = cluster_snapshots_response.get('DBClusterSnapshots', [])
            
            if cluster_snapshots:
                print(f"Found {len(cluster_snapshots)} manual cluster snapshots")
                for snapshot in cluster_snapshots:
                    snapshot_id = snapshot['DBClusterSnapshotIdentifier']
                    cluster_id = snapshot.get('DBClusterIdentifier', 'Unknown')
                    status = snapshot['Status']
                    
                    print(f"Deleting cluster snapshot: {snapshot_id} (Cluster: {cluster_id}, Status: {status})")
                    try:
                        rds_client.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier=snapshot_id)
                        print(f"✅ Deleted cluster snapshot: {snapshot_id}")
                    except Exception as e:
                        print(f"❌ Failed to delete cluster snapshot {snapshot_id}: {e}")
            else:
                print("No manual cluster snapshots found")
                
        except Exception as e:
            print(f"Warning: Could not process manual snapshots: {e}")
        
        # ========================================
        # 4. DELETE DB SUBNET GROUPS
        # ========================================
        print(f"\n{'='*80}")
        print("PROCESSING DB SUBNET GROUPS")
        print(f"{'='*80}")
        
        try:
            subnet_groups_response = rds_client.describe_db_subnet_groups()
            subnet_groups = subnet_groups_response.get('DBSubnetGroups', [])
            
            if subnet_groups:
                print(f"Found {len(subnet_groups)} DB subnet groups")
                for subnet_group in subnet_groups:
                    group_name = subnet_group['DBSubnetGroupName']
                    vpc_id = subnet_group['VpcId']
                    subnets = subnet_group.get('Subnets', [])
                    
                    # Skip default subnet group
                    if group_name == 'default':
                        print(f"Skipping default subnet group: {group_name}")
                        continue
                    
                    print(f"Deleting DB subnet group: {group_name} (VPC: {vpc_id}, Subnets: {len(subnets)})")
                    try:
                        rds_client.delete_db_subnet_group(DBSubnetGroupName=group_name)
                        print(f"✅ Deleted DB subnet group: {group_name}")
                    except Exception as e:
                        print(f"❌ Failed to delete DB subnet group {group_name}: {e}")
            else:
                print("No custom DB subnet groups found")
                
        except Exception as e:
            print(f"Warning: Could not process DB subnet groups: {e}")
        
        # ========================================
        # 5. DELETE DB PARAMETER GROUPS
        # ========================================
        print(f"\n{'='*80}")
        print("PROCESSING DB PARAMETER GROUPS")
        print(f"{'='*80}")
        
        try:
            # Delete DB parameter groups
            param_groups_response = rds_client.describe_db_parameter_groups()
            param_groups = param_groups_response.get('DBParameterGroups', [])
            
            if param_groups:
                print(f"Found {len(param_groups)} DB parameter groups")
                for param_group in param_groups:
                    group_name = param_group['DBParameterGroupName']
                    family = param_group['DBParameterGroupFamily']
                    
                    # Skip default parameter groups
                    if group_name.startswith('default.'):
                        print(f"Skipping default parameter group: {group_name}")
                        continue
                    
                    print(f"Deleting DB parameter group: {group_name} (Family: {family})")
                    try:
                        rds_client.delete_db_parameter_group(DBParameterGroupName=group_name)
                        print(f"✅ Deleted DB parameter group: {group_name}")
                    except Exception as e:
                        print(f"❌ Failed to delete DB parameter group {group_name}: {e}")
            else:
                print("No custom DB parameter groups found")
            
            # Delete cluster parameter groups
            cluster_param_groups_response = rds_client.describe_db_cluster_parameter_groups()
            cluster_param_groups = cluster_param_groups_response.get('DBClusterParameterGroups', [])
            
            if cluster_param_groups:
                print(f"Found {len(cluster_param_groups)} cluster parameter groups")
                for param_group in cluster_param_groups:
                    group_name = param_group['DBClusterParameterGroupName']
                    family = param_group['DBParameterGroupFamily']
                    
                    # Skip default parameter groups
                    if group_name.startswith('default.'):
                        print(f"Skipping default cluster parameter group: {group_name}")
                        continue
                    
                    print(f"Deleting cluster parameter group: {group_name} (Family: {family})")
                    try:
                        rds_client.delete_db_cluster_parameter_group(DBClusterParameterGroupName=group_name)
                        print(f"✅ Deleted cluster parameter group: {group_name}")
                    except Exception as e:
                        print(f"❌ Failed to delete cluster parameter group {group_name}: {e}")
            else:
                print("No custom cluster parameter groups found")
                
        except Exception as e:
            print(f"Warning: Could not process parameter groups: {e}")
        
        # ========================================
        # 6. DELETE OPTION GROUPS
        # ========================================
        print(f"\n{'='*80}")
        print("PROCESSING OPTION GROUPS")
        print(f"{'='*80}")
        
        try:
            option_groups_response = rds_client.describe_option_groups()
            option_groups = option_groups_response.get('OptionGroupsList', [])
            
            if option_groups:
                print(f"Found {len(option_groups)} option groups")
                for option_group in option_groups:
                    group_name = option_group['OptionGroupName']
                    engine_name = option_group['EngineName']
                    
                    # Skip default option groups
                    if group_name.startswith('default:'):
                        print(f"Skipping default option group: {group_name}")
                        continue
                    
                    print(f"Deleting option group: {group_name} (Engine: {engine_name})")
                    try:
                        rds_client.delete_option_group(OptionGroupName=group_name)
                        print(f"✅ Deleted option group: {group_name}")
                    except Exception as e:
                        print(f"❌ Failed to delete option group {group_name}: {e}")
            else:
                print("No custom option groups found")
                
        except Exception as e:
            print(f"Warning: Could not process option groups: {e}")
        
        print(f"\n✅ Completed comprehensive RDS cleanup in {region}")
        
    except Exception as e:
        print(f"❌ Error during RDS cleanup in {region}: {e}")

@measure_time
def delete_all_objects(bucket_name, region):
    """
    Delete all objects in the specified S3 bucket.
    """
    s3 = boto3.resource('s3', region_name=region)
    bucket = s3.Bucket(bucket_name)
    deleted_objects = []
    for obj in bucket.objects.all():
        obj.delete()
        deleted_objects.append(obj.key)
    return deleted_objects

@measure_time
def delete_bucket_policy(bucket_name, region):
    """
    Delete the bucket policy if it exists.
    """
    s3 = boto3.client('s3', region_name=region)
    try:
        s3.delete_bucket_policy(Bucket=bucket_name)
        print(f"Deleted policy for bucket: {bucket_name}")
    except s3.exceptions.NoSuchBucketPolicy:
        print(f"No policy found for bucket: {bucket_name}")

@measure_time
def delete_s3_buckets(buckets_to_keep, region):
    """
    Delete all S3 buckets in the specified region except those specified to keep.
    """
    s3 = boto3.client('s3', region_name=region)

    # List all buckets
    response = s3.list_buckets()
    all_bucket_names = [bucket['Name'] for bucket in response['Buckets']]

    print(f"\nDeleting S3 buckets in region {region} except the ones specified to keep:")

    for bucket_name in all_bucket_names:
        if bucket_name not in buckets_to_keep:
            print(f"\nDeleting bucket: {bucket_name}")
            # Delete all objects in the bucket
            deleted_objects = delete_all_objects(bucket_name, region)
            print(f"Deleted objects in bucket {bucket_name}:")
            for obj_key in deleted_objects:
                print(obj_key)
            
            # Delete the bucket policy if exists
            delete_bucket_policy(bucket_name, region)
            
            # Try to delete the bucket
            try:
                s3.delete_bucket(Bucket=bucket_name)
                print(f"Bucket {bucket_name} deleted.")
            except Exception as e:
                print(f"Error deleting bucket {bucket_name}: {e}")

@measure_time
def delete_dynamodb_tables(tables_to_keep, region):
    """
    Delete all DynamoDB tables in the specified region except those specified to keep.
    """
    # Initialize the DynamoDB client
    dynamodb = boto3.client('dynamodb', region_name=region)

    # List all tables
    response = dynamodb.list_tables()

    # Get the names of all tables
    all_table_names = response['TableNames']

    print(f"\nDeleting DynamoDB tables in region {region} except the ones specified to keep:")

    # Delete tables except the ones specified to keep
    for table_name in all_table_names:
        if table_name not in tables_to_keep:
            print(f"\nDeleting table: {table_name}")
            # Try to delete the table
            try:
                dynamodb.delete_table(TableName=table_name)
                print(f"Table {table_name} deleted.")
            except Exception as e:
                print(f"Error deleting table {table_name}: {e}")

@measure_time
def delete_ec2_instances(region):
    """
    Terminate all EC2 instances in the specified region.
    """
    # Initialize the EC2 client
    ec2 = boto3.client('ec2', region_name=region)

    # Describe all instances
    response = ec2.describe_instances()

    print(f"\nTerminating EC2 instances in region {region}:")

    # Terminate all instances
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            print(f"\nTerminating instance: {instance_id}")
            # Try to terminate the instance
            try:
                ec2.terminate_instances(InstanceIds=[instance_id])
                print(f"Instance {instance_id} terminated.")
            except Exception as e:
                print(f"Error terminating instance {instance_id}: {e}")


@measure_time
def delete_auto_scaling_groups(region):
    autoscaling_client = boto3.client('autoscaling', region_name=region)
    ec2_client = boto3.client('ec2', region_name=region)
    
    try:
        # List all Auto Scaling Groups
        paginator = autoscaling_client.get_paginator('describe_auto_scaling_groups')
        page_iterator = paginator.paginate()
        
        all_asgs = []
        for page in page_iterator:
            all_asgs.extend(page.get('AutoScalingGroups', []))
        
        if not all_asgs:
            print(f"No Auto Scaling Groups found in {region}")
            return
        
        print(f"Found {len(all_asgs)} Auto Scaling Groups in {region}")
        
        for asg in all_asgs:
            asg_name = asg['AutoScalingGroupName']
            desired_capacity = asg['DesiredCapacity']
            min_size = asg['MinSize']
            max_size = asg['MaxSize']
            instances = asg.get('Instances', [])
            launch_template = asg.get('LaunchTemplate', {})
            launch_config = asg.get('LaunchConfigurationName')
            
            print(f"\n{'='*80}")
            print(f"Processing Auto Scaling Group: {asg_name}")
            print(f"Desired: {desired_capacity}, Min: {min_size}, Max: {max_size}")
            print(f"Current instances: {len(instances)}")
            if launch_template:
                print(f"Launch Template: {launch_template.get('LaunchTemplateName')} (v{launch_template.get('Version')})")
            if launch_config:
                print(f"Launch Configuration: {launch_config}")
            print(f"Processed by: varadharajaan at 2025-06-11 09:13:05 UTC")
            print(f"{'='*80}")
            
            try:
                # 1. Suspend all scaling processes
                print(f"Suspending all scaling processes for {asg_name}")
                try:
                    autoscaling_client.suspend_processes(AutoScalingGroupName=asg_name)
                    print(f"✅ Suspended scaling processes for {asg_name}")
                except Exception as e:
                    print(f"❌ Failed to suspend processes for {asg_name}: {e}")
                
                # 2. Detach and terminate all instances
                if instances:
                    print(f"Found {len(instances)} instances in ASG {asg_name}")
                    
                    instance_ids = [instance['InstanceId'] for instance in instances]
                    
                    # Show instance details
                    for instance in instances:
                        instance_id = instance['InstanceId']
                        lifecycle_state = instance['LifecycleState']
                        health_status = instance['HealthStatus']
                        print(f"  - Instance: {instance_id} (State: {lifecycle_state}, Health: {health_status})")
                    
                    # Terminate instances with decrement
                    print(f"Terminating instances in {asg_name}...")
                    for instance_id in instance_ids:
                        try:
                            autoscaling_client.terminate_instance_in_auto_scaling_group(
                                InstanceId=instance_id,
                                ShouldDecrementDesiredCapacity=True
                            )
                            print(f"✅ Terminated instance: {instance_id}")
                        except Exception as e:
                            print(f"❌ Failed to terminate instance {instance_id}: {e}")
                    
                    # Wait for instances to terminate
                    print(f"Waiting for instances to terminate...")
                    max_wait = 600  # 10 minutes
                    wait_time = 0
                    check_interval = 30
                    
                    while wait_time < max_wait:
                        try:
                            current_asg = autoscaling_client.describe_auto_scaling_groups(
                                AutoScalingGroupNames=[asg_name]
                            )
                            
                            if current_asg['AutoScalingGroups']:
                                current_instances = current_asg['AutoScalingGroups'][0].get('Instances', [])
                                if not current_instances:
                                    print(f"✅ All instances terminated in {asg_name}")
                                    break
                                print(f"Still waiting... {len(current_instances)} instances remaining")
                            else:
                                break
                            
                            time.sleep(check_interval)
                            wait_time += check_interval
                            
                        except Exception as e:
                            print(f"Error checking ASG status: {e}")
                            break
                    
                    if wait_time >= max_wait:
                        print(f"⚠️ Timeout waiting for instances to terminate in {asg_name}")
                
                # 3. Update ASG to zero capacity
                print(f"Setting ASG {asg_name} capacity to zero")
                try:
                    autoscaling_client.update_auto_scaling_group(
                        AutoScalingGroupName=asg_name,
                        MinSize=0,
                        MaxSize=0,
                        DesiredCapacity=0
                    )
                    print(f"✅ Set {asg_name} capacity to zero")
                except Exception as e:
                    print(f"❌ Failed to update ASG capacity for {asg_name}: {e}")
                
                # 4. Detach load balancers
                target_group_arns = asg.get('TargetGroupARNs', [])
                load_balancer_names = asg.get('LoadBalancerNames', [])
                
                if target_group_arns:
                    print(f"Detaching {len(target_group_arns)} target groups from {asg_name}")
                    try:
                        autoscaling_client.detach_load_balancer_target_groups(
                            AutoScalingGroupName=asg_name,
                            TargetGroupARNs=target_group_arns
                        )
                        print(f"✅ Detached target groups from {asg_name}")
                    except Exception as e:
                        print(f"❌ Failed to detach target groups from {asg_name}: {e}")
                
                if load_balancer_names:
                    print(f"Detaching {len(load_balancer_names)} classic load balancers from {asg_name}")
                    try:
                        autoscaling_client.detach_load_balancers(
                            AutoScalingGroupName=asg_name,
                            LoadBalancerNames=load_balancer_names
                        )
                        print(f"✅ Detached classic load balancers from {asg_name}")
                    except Exception as e:
                        print(f"❌ Failed to detach classic load balancers from {asg_name}: {e}")
                
                # 5. Delete scaling policies
                try:
                    policies_response = autoscaling_client.describe_policies(
                        AutoScalingGroupName=asg_name
                    )
                    policies = policies_response.get('ScalingPolicies', [])
                    
                    if policies:
                        print(f"Found {len(policies)} scaling policies for {asg_name}")
                        for policy in policies:
                            policy_name = policy['PolicyName']
                            try:
                                print(f"Deleting scaling policy: {policy_name}")
                                autoscaling_client.delete_policy(
                                    AutoScalingGroupName=asg_name,
                                    PolicyName=policy_name
                                )
                                print(f"✅ Deleted scaling policy: {policy_name}")
                            except Exception as e:
                                print(f"❌ Failed to delete scaling policy {policy_name}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process scaling policies for {asg_name}: {e}")
                
                # 6. Delete scheduled actions
                try:
                    scheduled_actions = autoscaling_client.describe_scheduled_actions(
                        AutoScalingGroupName=asg_name
                    )
                    actions = scheduled_actions.get('ScheduledUpdateGroupActions', [])
                    
                    if actions:
                        print(f"Found {len(actions)} scheduled actions for {asg_name}")
                        for action in actions:
                            action_name = action['ScheduledActionName']
                            try:
                                print(f"Deleting scheduled action: {action_name}")
                                autoscaling_client.delete_scheduled_action(
                                    AutoScalingGroupName=asg_name,
                                    ScheduledActionName=action_name
                                )
                                print(f"✅ Deleted scheduled action: {action_name}")
                            except Exception as e:
                                print(f"❌ Failed to delete scheduled action {action_name}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process scheduled actions for {asg_name}: {e}")
                
                # 7. Delete lifecycle hooks
                try:
                    hooks_response = autoscaling_client.describe_lifecycle_hooks(
                        AutoScalingGroupName=asg_name
                    )
                    hooks = hooks_response.get('LifecycleHooks', [])
                    
                    if hooks:
                        print(f"Found {len(hooks)} lifecycle hooks for {asg_name}")
                        for hook in hooks:
                            hook_name = hook['LifecycleHookName']
                            try:
                                print(f"Deleting lifecycle hook: {hook_name}")
                                autoscaling_client.delete_lifecycle_hook(
                                    AutoScalingGroupName=asg_name,
                                    LifecycleHookName=hook_name
                                )
                                print(f"✅ Deleted lifecycle hook: {hook_name}")
                            except Exception as e:
                                print(f"❌ Failed to delete lifecycle hook {hook_name}: {e}")
                
                except Exception as e:
                    print(f"Warning: Could not process lifecycle hooks for {asg_name}: {e}")
                
                # 8. Delete the Auto Scaling Group
                print(f"Deleting Auto Scaling Group: {asg_name}")
                try:
                    autoscaling_client.delete_auto_scaling_group(
                        AutoScalingGroupName=asg_name,
                        ForceDelete=True  # Force delete even if instances exist
                    )
                    print(f"✅ Deleted Auto Scaling Group: {asg_name}")
                except Exception as e:
                    print(f"❌ Failed to delete ASG {asg_name}: {e}")
                
                # 9. Clean up associated Launch Configuration (if not shared)
                if launch_config:
                    try:
                        print(f"Checking if launch configuration {launch_config} can be deleted...")
                        
                        # Check if other ASGs use this launch config
                        all_asgs_check = autoscaling_client.describe_auto_scaling_groups()
                        other_users = [
                            asg_check['AutoScalingGroupName'] 
                            for asg_check in all_asgs_check['AutoScalingGroups']
                            if asg_check.get('LaunchConfigurationName') == launch_config
                            and asg_check['AutoScalingGroupName'] != asg_name
                        ]
                        
                        if not other_users:
                            print(f"Deleting unused launch configuration: {launch_config}")
                            autoscaling_client.delete_launch_configuration(
                                LaunchConfigurationName=launch_config
                            )
                            print(f"✅ Deleted launch configuration: {launch_config}")
                        else:
                            print(f"Launch configuration {launch_config} is used by other ASGs: {other_users}")
                            
                    except Exception as e:
                        print(f"❌ Failed to delete launch configuration {launch_config}: {e}")
                
            except Exception as e:
                print(f"❌ Failed to process Auto Scaling Group {asg_name}: {e}")
        
        print(f"✅ Completed Auto Scaling Group cleanup in {region}")
        
    except Exception as e:
        print(f"❌ Error processing Auto Scaling Groups in {region}: {e}")

@measure_time
def delete_load_balancers_and_target_groups(region):
    # Initialize clients
    elbv2_client = boto3.client('elbv2', region_name=region)  # Application/Network Load Balancers
    elb_client = boto3.client('elb', region_name=region)      # Classic Load Balancers
    ec2_client = boto3.client('ec2', region_name=region)
    
    print(f"Starting comprehensive load balancer cleanup in {region}")
    print(f"Processing by: varadharajaan at 2025-06-11 09:14:24 UTC")
    
    # ========================================
    # 1. DELETE APPLICATION/NETWORK LOAD BALANCERS
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("PROCESSING APPLICATION/NETWORK LOAD BALANCERS")
        print(f"{'='*80}")
        
        # Get all ALBs/NLBs
        paginator = elbv2_client.get_paginator('describe_load_balancers')
        page_iterator = paginator.paginate()
        
        all_load_balancers = []
        for page in page_iterator:
            all_load_balancers.extend(page.get('LoadBalancers', []))
        
        if not all_load_balancers:
            print("No Application/Network Load Balancers found")
        else:
            print(f"Found {len(all_load_balancers)} Application/Network Load Balancers")
            
            for lb in all_load_balancers:
                lb_arn = lb['LoadBalancerArn']
                lb_name = lb['LoadBalancerName']
                lb_type = lb['Type']  # application, network, or gateway
                lb_scheme = lb['Scheme']  # internet-facing or internal
                lb_state = lb['State']['Code']
                
                print(f"\n--- Processing {lb_type.upper()} Load Balancer ---")
                print(f"Name: {lb_name}")
                print(f"Type: {lb_type}")
                print(f"Scheme: {lb_scheme}")
                print(f"State: {lb_state}")
                print(f"ARN: {lb_arn}")
                
                try:
                    # Delete all listeners first
                    print(f"Checking listeners for {lb_name}...")
                    try:
                        listeners_response = elbv2_client.describe_listeners(LoadBalancerArn=lb_arn)
                        listeners = listeners_response.get('Listeners', [])
                        
                        if listeners:
                            print(f"Found {len(listeners)} listeners")
                            for listener in listeners:
                                listener_arn = listener['ListenerArn']
                                listener_port = listener['Port']
                                listener_protocol = listener['Protocol']
                                
                                print(f"Deleting listener: {listener_protocol}:{listener_port} ({listener_arn})")
                                try:
                                    elbv2_client.delete_listener(ListenerArn=listener_arn)
                                    print(f"✅ Deleted listener: {listener_protocol}:{listener_port}")
                                except Exception as e:
                                    print(f"❌ Failed to delete listener {listener_arn}: {e}")
                        else:
                            print("No listeners found")
                    except Exception as e:
                        print(f"Warning: Could not check listeners for {lb_name}: {e}")
                    
                    # Wait a moment for listeners to be deleted
                    if listeners:
                        print("Waiting for listeners to be deleted...")
                        time.sleep(10)
                    
                    # Delete the load balancer
                    print(f"Deleting {lb_type} load balancer: {lb_name}")
                    elbv2_client.delete_load_balancer(LoadBalancerArn=lb_arn)
                    print(f"✅ Deletion initiated for {lb_name}")
                    
                    # Wait for deletion to complete
                    print(f"Waiting for {lb_name} to be deleted...")
                    max_wait = 300  # 5 minutes
                    wait_time = 0
                    check_interval = 15
                    
                    while wait_time < max_wait:
                        try:
                            elbv2_client.describe_load_balancers(LoadBalancerArns=[lb_arn])
                            print(f"Still deleting {lb_name}...")
                            time.sleep(check_interval)
                            wait_time += check_interval
                        except elbv2_client.exceptions.LoadBalancerNotFoundException:
                            print(f"✅ {lb_name} deleted successfully")
                            break
                        except Exception as e:
                            print(f"Error checking deletion status: {e}")
                            break
                    
                    if wait_time >= max_wait:
                        print(f"⚠️ Timeout waiting for {lb_name} deletion")
                    
                except Exception as e:
                    print(f"❌ Failed to process load balancer {lb_name}: {e}")
    
    except Exception as e:
        print(f"❌ Error processing Application/Network Load Balancers: {e}")
    
    # ========================================
    # 2. DELETE CLASSIC LOAD BALANCERS
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("PROCESSING CLASSIC LOAD BALANCERS")
        print(f"{'='*80}")
        
        # Get all Classic Load Balancers
        paginator = elb_client.get_paginator('describe_load_balancers')
        page_iterator = paginator.paginate()
        
        all_classic_lbs = []
        for page in page_iterator:
            all_classic_lbs.extend(page.get('LoadBalancerDescriptions', []))
        
        if not all_classic_lbs:
            print("No Classic Load Balancers found")
        else:
            print(f"Found {len(all_classic_lbs)} Classic Load Balancers")
            
            for clb in all_classic_lbs:
                clb_name = clb['LoadBalancerName']
                clb_scheme = clb['Scheme']
                instances = clb.get('Instances', [])
                
                print(f"\n--- Processing Classic Load Balancer ---")
                print(f"Name: {clb_name}")
                print(f"Scheme: {clb_scheme}")
                print(f"Attached instances: {len(instances)}")
                
                try:
                    # Deregister all instances first
                    if instances:
                        instance_ids = [instance['InstanceId'] for instance in instances]
                        print(f"Deregistering {len(instance_ids)} instances from {clb_name}")
                        
                        try:
                            elb_client.deregister_instances_from_load_balancer(
                                LoadBalancerName=clb_name,
                                Instances=[{'InstanceId': iid} for iid in instance_ids]
                            )
                            print(f"✅ Deregistered instances from {clb_name}")
                            time.sleep(5)  # Wait for deregistration
                        except Exception as e:
                            print(f"❌ Failed to deregister instances from {clb_name}: {e}")
                    
                    # Delete the Classic Load Balancer
                    print(f"Deleting Classic Load Balancer: {clb_name}")
                    elb_client.delete_load_balancer(LoadBalancerName=clb_name)
                    print(f"✅ Deleted Classic Load Balancer: {clb_name}")
                    
                except Exception as e:
                    print(f"❌ Failed to process Classic Load Balancer {clb_name}: {e}")
    
    except Exception as e:
        print(f"❌ Error processing Classic Load Balancers: {e}")
    
    # ========================================
    # 3. DELETE TARGET GROUPS
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("PROCESSING TARGET GROUPS")
        print(f"{'='*80}")
        
        # Get all target groups
        paginator = elbv2_client.get_paginator('describe_target_groups')
        page_iterator = paginator.paginate()
        
        all_target_groups = []
        for page in page_iterator:
            all_target_groups.extend(page.get('TargetGroups', []))
        
        if not all_target_groups:
            print("No Target Groups found")
        else:
            print(f"Found {len(all_target_groups)} Target Groups")
            
            for tg in all_target_groups:
                tg_arn = tg['TargetGroupArn']
                tg_name = tg['TargetGroupName']
                tg_type = tg['TargetType']
                tg_protocol = tg['Protocol']
                tg_port = tg['Port']
                
                print(f"\n--- Processing Target Group ---")
                print(f"Name: {tg_name}")
                print(f"Type: {tg_type}")
                print(f"Protocol: {tg_protocol}")
                print(f"Port: {tg_port}")
                print(f"ARN: {tg_arn}")
                
                try:
                    # Get and deregister all targets
                    print(f"Checking targets for {tg_name}...")
                    try:
                        targets_response = elbv2_client.describe_target_health(TargetGroupArn=tg_arn)
                        target_health_descriptions = targets_response.get('TargetHealthDescriptions', [])
                        
                        if target_health_descriptions:
                            targets_to_deregister = []
                            for target_health in target_health_descriptions:
                                target = target_health['Target']
                                target_id = target['Id']
                                target_port = target.get('Port', tg_port)
                                health_state = target_health['TargetHealth']['State']
                                
                                print(f"Found target: {target_id}:{target_port} (State: {health_state})")
                                targets_to_deregister.append(target)
                            
                            if targets_to_deregister:
                                print(f"Deregistering {len(targets_to_deregister)} targets from {tg_name}")
                                elbv2_client.deregister_targets(
                                    TargetGroupArn=tg_arn,
                                    Targets=targets_to_deregister
                                )
                                print(f"✅ Deregistered targets from {tg_name}")
                                
                                # Wait for targets to be deregistered
                                print(f"Waiting for targets to be deregistered from {tg_name}...")
                                max_wait = 120  # 2 minutes
                                wait_time = 0
                                check_interval = 10
                                
                                while wait_time < max_wait:
                                    try:
                                        current_targets = elbv2_client.describe_target_health(TargetGroupArn=tg_arn)
                                        healthy_targets = [
                                            t for t in current_targets.get('TargetHealthDescriptions', [])
                                            if t['TargetHealth']['State'] not in ['unused', 'draining']
                                        ]
                                        
                                        if not healthy_targets:
                                            print(f"✅ All targets deregistered from {tg_name}")
                                            break
                                        
                                        print(f"Still waiting... {len(healthy_targets)} targets remaining")
                                        time.sleep(check_interval)
                                        wait_time += check_interval
                                        
                                    except Exception as e:
                                        print(f"Error checking target health: {e}")
                                        break
                                
                                if wait_time >= max_wait:
                                    print(f"⚠️ Timeout waiting for targets to deregister from {tg_name}")
                        else:
                            print(f"No targets found in {tg_name}")
                            
                    except Exception as e:
                        print(f"Warning: Could not check targets for {tg_name}: {e}")
                    
                    # Delete the target group
                    print(f"Deleting Target Group: {tg_name}")
                    elbv2_client.delete_target_group(TargetGroupArn=tg_arn)
                    print(f"✅ Deleted Target Group: {tg_name}")
                    
                except Exception as e:
                    print(f"❌ Failed to process Target Group {tg_name}: {e}")
    
    except Exception as e:
        print(f"❌ Error processing Target Groups: {e}")
    
    # ========================================
    # 4. CLEANUP SECURITY GROUPS (Load Balancer related)
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("CLEANING UP LOAD BALANCER SECURITY GROUPS")
        print(f"{'='*80}")
        
        # Find security groups that might be related to deleted load balancers
        security_groups = ec2_client.describe_security_groups()['SecurityGroups']
        lb_security_groups = []
        
        for sg in security_groups:
            sg_name = sg['GroupName']
            sg_id = sg['GroupId']
            sg_description = sg.get('Description', '')
            
            # Look for load balancer related security groups
            if any(keyword in sg_name.lower() for keyword in ['elb', 'loadbalancer', 'lb-']):
                lb_security_groups.append(sg)
            elif any(keyword in sg_description.lower() for keyword in ['load balancer', 'elb', 'created by aws']):
                lb_security_groups.append(sg)
        
        if lb_security_groups:
            print(f"Found {len(lb_security_groups)} potential load balancer security groups")
            
            for sg in lb_security_groups:
                sg_id = sg['GroupId']
                sg_name = sg['GroupName']
                
                # Skip default security groups
                if sg_name == 'default':
                    print(f"Skipping default security group: {sg_id}")
                    continue
                
                try:
                    print(f"Checking if security group {sg_name} ({sg_id}) can be deleted...")
                    
                    # Check if any network interfaces are using this security group
                    enis = ec2_client.describe_network_interfaces(
                        Filters=[
                            {'Name': 'group-id', 'Values': [sg_id]}
                        ]
                    )['NetworkInterfaces']
                    
                    if not enis:
                        print(f"Deleting unused security group: {sg_name} ({sg_id})")
                        ec2_client.delete_security_group(GroupId=sg_id)
                        print(f"✅ Deleted security group: {sg_name}")
                    else:
                        print(f"Security group {sg_name} is still in use by {len(enis)} network interfaces")
                        
                except Exception as e:
                    print(f"❌ Failed to delete security group {sg_name} ({sg_id}): {e}")
        else:
            print("No load balancer security groups found for cleanup")
    
    except Exception as e:
        print(f"Warning: Could not clean up security groups: {e}")
    
    print(f"\n✅ Completed comprehensive load balancer and target group cleanup in {region}")

@measure_time
def delete_launch_templates(region):
    ec2_client = boto3.client('ec2', region_name=region)

    # List all launch templates
    launch_templates = ec2_client.describe_launch_templates()['LaunchTemplates']
    
    for lt in launch_templates:
        lt_id = lt['LaunchTemplateId']
        lt_name = lt['LaunchTemplateName']
        print(f"Deleting launch template: {lt_name} (ID: {lt_id})")
        try:
            ec2_client.delete_launch_template(LaunchTemplateId=lt_id)
            print(f"Launch template {lt_name} deleted successfully")
        except ec2_client.exceptions.ClientException as e:
            print(f"Failed to delete launch template {lt_name}: {e}")
            
@measure_time
def delete_ebs_snapshots(region):
    """
    Delete all EBS snapshots in the specified region.
    """
    # Initialize the EC2 client
    ec2 = boto3.client('ec2', region_name=region)

    # Describe all snapshots
    response = ec2.describe_snapshots(OwnerIds=['self'])

    print(f"\nDeleting EBS snapshots in region {region}:")

    # Delete all snapshots
    for snapshot in response['Snapshots']:
        snapshot_id = snapshot['SnapshotId']
        print(f"\nDeleting snapshot: {snapshot_id}")
        # Try to delete the snapshot
        try:
            ec2.delete_snapshot(SnapshotId=snapshot_id)
            print(f"EBS snapshot {snapshot_id} deleted.")
        except Exception as e:
            print(f"Error deleting EBS snapshot {snapshot_id}: {e}")
            ami_ids = find_amis_for_snapshot(snapshot_id, region)
            for ami_id in ami_ids:
                try:
                    print(f"Deregistering AMI: {ami_id} associated with snapshot {snapshot_id}")
                    ec2.deregister_image(ImageId=ami_id)
                    print(f"AMI {ami_id} deregistered.")
                except Exception as ami_e:
                    print(f"Error deregistering AMI {ami_id}: {ami_e}")
            # Retry snapshot deletion
            try:
                ec2.delete_snapshot(SnapshotId=snapshot_id)
                print(f"EBS snapshot {snapshot_id} deleted after deregistering AMIs.")
            except Exception as retry_e:
                print(f"Error deleting EBS snapshot {snapshot_id} after deregistering AMIs: {retry_e}")

@measure_time
def find_amis_for_snapshot(snapshot_id, region):
    """
    Find all AMIs that use the specified snapshot.
    """
    ec2 = boto3.client('ec2', region_name=region)
    response = ec2.describe_images(Owners=['self'])
    ami_ids = []
    for image in response['Images']:
        for mapping in image['BlockDeviceMappings']:
            if 'Ebs' in mapping and 'SnapshotId' in mapping['Ebs'] and mapping['Ebs']['SnapshotId'] == snapshot_id:
                ami_ids.append(image['ImageId'])
    return ami_ids

@measure_time
def delete_amis(region):
    """
    Deregister all AMIs in the specified region.
    """
    # Initialize the EC2 client
    ec2 = boto3.client('ec2', region_name=region)

    # Describe all AMIs
    response = ec2.describe_images(Owners=['self'])

    print(f"\nDeregistering AMIs in region {region}:")

    # Deregister all AMIs
    for image in response['Images']:
        image_id = image['ImageId']
        print(f"\nDeregistering AMI: {image_id}")
        # Try to deregister the AMI
        try:
            ec2.deregister_image(ImageId=image_id)
            print(f"AMI {image_id} deregistered.")
        except Exception as e:
            print(f"Error deregistering AMI {image_id}: {e}")

@measure_time
def delete_ebs_volumes(region):
    """
    Delete all EBS volumes in the specified region.
    """
    ec2 = boto3.client('ec2', region_name=region)
    response = ec2.describe_volumes(Filters=[{'Name': 'status', 'Values': ['in-use', 'available']}])
    
    for volume in response['Volumes']:
        volume_id = volume['VolumeId']
        if volume['State'] == 'in-use':
            # Attempt to detach the volume first if it's in use
            try:
                print(f"Volume {volume_id} is in use. Attempting to detach...")
                for attachment in volume['Attachments']:
                    ec2.detach_volume(VolumeId=volume_id, InstanceId=attachment['InstanceId'], Device=attachment['Device'], Force=True)
                print(f"Volume {volume_id} detached successfully.")
            except Exception as e:
                print(f"Error detaching volume {volume_id}: {e}")
                continue

        # Proceed with deleting the volume
        try:
            ec2.delete_volume(VolumeId=volume_id)
            print(f"Volume {volume_id} deleted successfully.")
        except botocore.exceptions.ClientError as e:
            print(f"Error deleting volume {volume_id}: {e}")

@measure_time
def delete_lambda_functions(region):
    """
    Delete all Lambda functions in the specified region.
    """
    # Initialize the Lambda client
    lambda_client = boto3.client('lambda', region_name=region)

    # List all Lambda functions
    response = lambda_client.list_functions()

    print(f"\nDeleting Lambda functions in region {region}:")

    # Delete all Lambda functions
    for function in response['Functions']:
        function_name = function['FunctionName']
        print(f"\nDeleting Lambda function: {function_name}")
        # Try to delete the function
        try:
            lambda_client.delete_function(FunctionName=function_name)
            print(f"Lambda function {function_name} deleted.")
        except Exception as e:
            print(f"Error deleting Lambda function {function_name}: {e}")
            
@measure_time
def delete_custom_vpcs(region):
    ec2_client = boto3.client('ec2', region_name=region)
    vpcs = ec2_client.describe_vpcs()['Vpcs']

    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        is_default = vpc['IsDefault']
        
        if not is_default:
            print(f"Deleting custom VPC: {vpc_id} in {region}")

            # Detach and delete Internet Gateways
            igws = ec2_client.describe_internet_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}])['InternetGateways']
            for igw in igws:
                print(f"Detaching and deleting Internet Gateway: {igw['InternetGatewayId']} from VPC: {vpc_id}")
                ec2_client.detach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc_id)
                ec2_client.delete_internet_gateway(InternetGatewayId=igw['InternetGatewayId'])

            # Delete NAT Gateways
            nat_gateways = ec2_client.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['NatGateways']
            for nat_gateway in nat_gateways:
                print(f"Deleting NAT Gateway: {nat_gateway['NatGatewayId']} in VPC: {vpc_id}")
                ec2_client.delete_nat_gateway(NatGatewayId=nat_gateway['NatGatewayId'])
                while True:
                    status = ec2_client.describe_nat_gateways(NatGatewayIds=[nat_gateway['NatGatewayId']])['NatGateways'][0]['State']
                    if status == 'deleted':
                        break
                    print(f"Waiting for NAT Gateway {nat_gateway['NatGatewayId']} to be deleted...")
                    time.sleep(10)

            # Delete VPC Peering Connections
            peering_connections_requester = ec2_client.describe_vpc_peering_connections(Filters=[{'Name': 'requester-vpc-info.vpc-id', 'Values': [vpc_id]}])['VpcPeeringConnections']
            peering_connections_accepter = ec2_client.describe_vpc_peering_connections(Filters=[{'Name': 'accepter-vpc-info.vpc-id', 'Values': [vpc_id]}])['VpcPeeringConnections']

            peering_connections = peering_connections_requester + peering_connections_accepter
            for peering_connection in peering_connections:
                print(f"Deleting VPC Peering Connection: {peering_connection['VpcPeeringConnectionId']} in VPC: {vpc_id}")
                ec2_client.delete_vpc_peering_connection(VpcPeeringConnectionId=peering_connection['VpcPeeringConnectionId'])

            # Delete PrivateLink endpoints
            endpoints = ec2_client.describe_vpc_endpoints(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['VpcEndpoints']
            for endpoint in endpoints:
                print(f"Deleting VPC Endpoint: {endpoint['VpcEndpointId']} in VPC: {vpc_id}")
                ec2_client.delete_vpc_endpoints(VpcEndpointIds=[endpoint['VpcEndpointId']])

            # Delete PrivateLink endpoint services
            endpoint_services = ec2_client.describe_vpc_endpoint_service_configurations()['ServiceConfigurations']
            for service in endpoint_services:
                print(f"Deregistering VPC Endpoint Service: {service['ServiceId']} in VPC: {vpc_id}")
                ec2_client.deregister_vpc_endpoint_service(VpcEndpointServiceId=service['ServiceId'])

            # Delete route tables (excluding the main route table)
            route_tables = ec2_client.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['RouteTables']
            for route_table in route_tables:
                is_main = False
                for association in route_table['Associations']:
                    if association['Main']:
                        is_main = True
                        break
                if not is_main:
                    print(f"Deleting Route Table: {route_table['RouteTableId']} in VPC: {vpc_id}")
                    ec2_client.delete_route_table(RouteTableId=route_table['RouteTableId'])

            # Delete network ACLs (excluding the default ACL)
            acls = ec2_client.describe_network_acls(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['NetworkAcls']
            for acl in acls:
                if not acl['IsDefault']:
                    print(f"Deleting Network ACL: {acl['NetworkAclId']} in VPC: {vpc_id}")
                    ec2_client.delete_network_acl(NetworkAclId=acl['NetworkAclId'])

            # Delete security groups (excluding the default security group)
            security_groups = ec2_client.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['SecurityGroups']
            for sg in security_groups:
                if sg['GroupName'] != 'default':
                    print(f"Deleting Security Group: {sg['GroupId']} in VPC: {vpc_id}")
                    ec2_client.delete_security_group(GroupId=sg['GroupId'])

            # Delete subnets
            subnets = ec2_client.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['Subnets']
            for subnet in subnets:
                print(f"Deleting Subnet: {subnet['SubnetId']} in VPC: {vpc_id}")
                ec2_client.delete_subnet(SubnetId=subnet['SubnetId'])

           # Finally, delete the VPC
            print(f"Deleting VPC: {vpc_id} in {region}")
            try:
                ec2_client.delete_vpc(VpcId=vpc_id)
                print(f"VPC {vpc_id} deleted successfully")
            except ec2_client.exceptions.ClientError as e:
                print(f"Error deleting VPC {vpc_id}: {e}")

@measure_time
def delete_elastic_cache_clusters(clusters_to_keep, region):
    """
    Delete all ElastiCache clusters in the specified region except those specified to keep.
    """
    # Initialize the ElastiCache client
    elasti_cache = boto3.client('elasticache', region_name=region)
    
    # Get the names of all clusters
    all_cluster_ids = [cluster['CacheClusterId'] for cluster in elasti_cache.describe_cache_clusters()['CacheClusters']]
    
    print(f"\nDeleting ElastiCache clusters in region {region} except the ones specified to keep:")
    
    # Delete clusters except the ones specified to keep
    for cluster_id in all_cluster_ids:
        if cluster_id not in clusters_to_keep:
            print(f"\nDeleting cluster: {cluster_id}")
            # Try to delete the cluster
            try:
                elasti_cache.delete_cache_cluster(CacheClusterId=cluster_id)
                print(f"Cluster {cluster_id} deleted.")
            except Exception as e:
                print(f"Error deleting cluster {cluster_id}: {e}")

@measure_time
def delete_lambda_functions_except(to_keep, region='us-east-1'):
    lambda_client = boto3.client('lambda', region_name=region)
    functions = lambda_client.list_functions()['Functions']
    for function in functions:
        function_name = function['FunctionName']
        if function_name not in to_keep:
            try:
                lambda_client.delete_function(FunctionName=function_name)
                print(f"Deleted Lambda function: {function_name}")
            except Exception as e:
                print(f"Failed to delete Lambda function {function_name}: {e}")

@measure_time
def delete_cloudwatch_alarms(region='us-east-1'):
    cloudwatch_client = boto3.client('cloudwatch', region_name=region)
    alarms = cloudwatch_client.describe_alarms()['MetricAlarms']
    alarm_names = [alarm['AlarmName'] for alarm in alarms]  # Collect all alarm names

    try:
        if alarm_names:  # Check if there are alarms to delete
            cloudwatch_client.delete_alarms(AlarmNames=alarm_names)  # Use delete_alarms for a list of names
            for alarm_name in alarm_names:
                print(f"Deleted CloudWatch alarm: {alarm_name}")
    except Exception as e:
        print(f"Failed to delete CloudWatch alarms: {e}")

@measure_time
def delete_api_gateway_rest_apis(apis_to_keep, region):
    # Initialize clients for all API Gateway types
    apigateway_client = boto3.client('apigateway', region_name=region)  # REST APIs
    apigatewayv2_client = boto3.client('apigatewayv2', region_name=region)  # HTTP/WebSocket APIs
    
    print(f"Starting comprehensive API Gateway cleanup in {region}")
    print(f"Processing by: varadharajaan at 2025-06-11 09:15:25 UTC")
    print(f"APIs to keep: {apis_to_keep}")
    
    # ========================================
    # 1. DELETE REST APIs (API Gateway v1)
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("PROCESSING REST APIs (API Gateway v1)")
        print(f"{'='*80}")
        
        # Get all REST APIs
        paginator = apigateway_client.get_paginator('get_rest_apis')
        page_iterator = paginator.paginate()
        
        all_rest_apis = []
        for page in page_iterator:
            all_rest_apis.extend(page.get('items', []))
        
        if not all_rest_apis:
            print("No REST APIs found")
        else:
            print(f"Found {len(all_rest_apis)} REST APIs")
            
            for api in all_rest_apis:
                api_id = api['id']
                api_name = api['name']
                api_description = api.get('description', 'No description')
                api_created = api.get('createdDate', 'Unknown')
                api_version = api.get('version', 'No version')
                endpoint_config = api.get('endpointConfiguration', {})
                endpoint_types = endpoint_config.get('types', [])
                
                print(f"\n--- Processing REST API ---")
                print(f"ID: {api_id}")
                print(f"Name: {api_name}")
                print(f"Description: {api_description}")
                print(f"Version: {api_version}")
                print(f"Created: {api_created}")
                print(f"Endpoint Types: {endpoint_types}")
                
                # Check if API should be kept
                if api_name in apis_to_keep or api_id in apis_to_keep:
                    print(f"🔒 Keeping REST API: {api_name} (in keep list)")
                    continue
                
                try:
                    # 1. Delete all deployments
                    print(f"Checking deployments for REST API {api_name}...")
                    try:
                        deployments_response = apigateway_client.get_deployments(restApiId=api_id)
                        deployments = deployments_response.get('items', [])
                        
                        if deployments:
                            print(f"Found {len(deployments)} deployments")
                            for deployment in deployments:
                                deployment_id = deployment['id']
                                deployment_desc = deployment.get('description', 'No description')
                                created_date = deployment.get('createdDate', 'Unknown')
                                
                                print(f"Deleting deployment: {deployment_id} ({deployment_desc}) - Created: {created_date}")
                                try:
                                    apigateway_client.delete_deployment(
                                        restApiId=api_id,
                                        deploymentId=deployment_id
                                    )
                                    print(f"✅ Deleted deployment: {deployment_id}")
                                except Exception as e:
                                    print(f"❌ Failed to delete deployment {deployment_id}: {e}")
                        else:
                            print("No deployments found")
                    except Exception as e:
                        print(f"Warning: Could not check deployments for {api_name}: {e}")
                    
                    # 2. Delete all stages
                    print(f"Checking stages for REST API {api_name}...")
                    try:
                        stages_response = apigateway_client.get_stages(restApiId=api_id)
                        stages = stages_response.get('item', [])
                        
                        if stages:
                            print(f"Found {len(stages)} stages")
                            for stage in stages:
                                stage_name = stage['stageName']
                                deployment_id = stage.get('deploymentId', 'No deployment')
                                last_updated = stage.get('lastUpdatedDate', 'Unknown')
                                
                                print(f"Deleting stage: {stage_name} (Deployment: {deployment_id}) - Updated: {last_updated}")
                                try:
                                    apigateway_client.delete_stage(
                                        restApiId=api_id,
                                        stageName=stage_name
                                    )
                                    print(f"✅ Deleted stage: {stage_name}")
                                except Exception as e:
                                    print(f"❌ Failed to delete stage {stage_name}: {e}")
                        else:
                            print("No stages found")
                    except Exception as e:
                        print(f"Warning: Could not check stages for {api_name}: {e}")
                    
                    # 3. Delete API keys associated with this API
                    print(f"Checking API keys for REST API {api_name}...")
                    try:
                        api_keys_response = apigateway_client.get_api_keys()
                        api_keys = api_keys_response.get('items', [])
                        
                        for api_key in api_keys:
                            api_key_id = api_key['id']
                            api_key_name = api_key.get('name', 'Unnamed')
                            
                            # Check usage plans to see if this key is associated with our API
                            try:
                                usage_plans = apigateway_client.get_usage_plans()['items']
                                for usage_plan in usage_plans:
                                    usage_plan_id = usage_plan['id']
                                    usage_plan_name = usage_plan.get('name', 'Unnamed')
                                    
                                    # Check if usage plan includes our API
                                    api_stages = usage_plan.get('apiStages', [])
                                    if any(stage.get('apiId') == api_id for stage in api_stages):
                                        print(f"Found API key {api_key_name} linked to usage plan {usage_plan_name}")
                                        
                                        # Remove API key from usage plan
                                        try:
                                            apigateway_client.delete_usage_plan_key(
                                                usagePlanId=usage_plan_id,
                                                keyId=api_key_id
                                            )
                                            print(f"✅ Removed API key from usage plan")
                                        except Exception as e:
                                            print(f"Warning: Could not remove API key from usage plan: {e}")
                            except Exception as e:
                                print(f"Warning: Could not check usage plans for API key: {e}")
                    except Exception as e:
                        print(f"Warning: Could not check API keys for {api_name}: {e}")
                    
                    # 4. Delete usage plans associated with this API
                    print(f"Checking usage plans for REST API {api_name}...")
                    try:
                        usage_plans_response = apigateway_client.get_usage_plans()
                        usage_plans = usage_plans_response.get('items', [])
                        
                        for usage_plan in usage_plans:
                            usage_plan_id = usage_plan['id']
                            usage_plan_name = usage_plan.get('name', 'Unnamed')
                            api_stages = usage_plan.get('apiStages', [])
                            
                            # Check if this usage plan is associated with our API
                            if any(stage.get('apiId') == api_id for stage in api_stages):
                                print(f"Deleting usage plan: {usage_plan_name} ({usage_plan_id})")
                                try:
                                    apigateway_client.delete_usage_plan(usagePlanId=usage_plan_id)
                                    print(f"✅ Deleted usage plan: {usage_plan_name}")
                                except Exception as e:
                                    print(f"❌ Failed to delete usage plan {usage_plan_name}: {e}")
                    except Exception as e:
                        print(f"Warning: Could not check usage plans for {api_name}: {e}")
                    
                    # 5. Delete domain name mappings
                    print(f"Checking domain name mappings for REST API {api_name}...")
                    try:
                        domain_names_response = apigateway_client.get_domain_names()
                        domain_names = domain_names_response.get('items', [])
                        
                        for domain in domain_names:
                            domain_name = domain['domainName']
                            
                            # Check base path mappings
                            try:
                                mappings_response = apigateway_client.get_base_path_mappings(domainName=domain_name)
                                mappings = mappings_response.get('items', [])
                                
                                for mapping in mappings:
                                    if mapping.get('restApiId') == api_id:
                                        base_path = mapping.get('basePath', '(none)')
                                        print(f"Deleting base path mapping: {base_path} for domain {domain_name}")
                                        try:
                                            apigateway_client.delete_base_path_mapping(
                                                domainName=domain_name,
                                                basePath=mapping.get('basePath', '')
                                            )
                                            print(f"✅ Deleted base path mapping: {base_path}")
                                        except Exception as e:
                                            print(f"❌ Failed to delete base path mapping: {e}")
                            except Exception as e:
                                print(f"Warning: Could not check mappings for domain {domain_name}: {e}")
                    except Exception as e:
                        print(f"Warning: Could not check domain names for {api_name}: {e}")
                    
                    # 6. Delete the REST API
                    print(f"Deleting REST API: {api_name} ({api_id})")
                    apigateway_client.delete_rest_api(restApiId=api_id)
                    print(f"✅ Deleted REST API: {api_name}")
                    
                    # Wait a moment between deletions to avoid rate limiting
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"❌ Failed to process REST API {api_name}: {e}")
    
    except Exception as e:
        print(f"❌ Error processing REST APIs: {e}")
    
    # ========================================
    # 2. DELETE HTTP APIs (API Gateway v2)
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("PROCESSING HTTP APIs (API Gateway v2)")
        print(f"{'='*80}")
        
        # Get all HTTP APIs
        paginator = apigatewayv2_client.get_paginator('get_apis')
        page_iterator = paginator.paginate()
        
        all_http_apis = []
        for page in page_iterator:
            all_http_apis.extend(page.get('Items', []))
        
        # Filter for HTTP APIs only (not WebSocket)
        http_apis = [api for api in all_http_apis if api.get('ProtocolType') == 'HTTP']
        
        if not http_apis:
            print("No HTTP APIs found")
        else:
            print(f"Found {len(http_apis)} HTTP APIs")
            
            for api in http_apis:
                api_id = api['ApiId']
                api_name = api['Name']
                protocol_type = api['ProtocolType']
                api_endpoint = api.get('ApiEndpoint', 'No endpoint')
                created_date = api.get('CreatedDate', 'Unknown')
                description = api.get('Description', 'No description')
                
                print(f"\n--- Processing HTTP API ---")
                print(f"ID: {api_id}")
                print(f"Name: {api_name}")
                print(f"Protocol: {protocol_type}")
                print(f"Endpoint: {api_endpoint}")
                print(f"Created: {created_date}")
                print(f"Description: {description}")
                
                # Check if API should be kept
                if api_name in apis_to_keep or api_id in apis_to_keep:
                    print(f"🔒 Keeping HTTP API: {api_name} (in keep list)")
                    continue
                
                try:
                    # 1. Delete all stages
                    print(f"Checking stages for HTTP API {api_name}...")
                    try:
                        stages_response = apigatewayv2_client.get_stages(ApiId=api_id)
                        stages = stages_response.get('Items', [])
                        
                        if stages:
                            print(f"Found {len(stages)} stages")
                            for stage in stages:
                                stage_name = stage['StageName']
                                auto_deploy = stage.get('AutoDeploy', False)
                                last_updated = stage.get('LastUpdatedDate', 'Unknown')
                                
                                print(f"Deleting stage: {stage_name} (AutoDeploy: {auto_deploy}) - Updated: {last_updated}")
                                try:
                                    apigatewayv2_client.delete_stage(
                                        ApiId=api_id,
                                        StageName=stage_name
                                    )
                                    print(f"✅ Deleted stage: {stage_name}")
                                except Exception as e:
                                    print(f"❌ Failed to delete stage {stage_name}: {e}")
                        else:
                            print("No stages found")
                    except Exception as e:
                        print(f"Warning: Could not check stages for {api_name}: {e}")
                    
                    # 2. Delete all routes
                    print(f"Checking routes for HTTP API {api_name}...")
                    try:
                        routes_response = apigatewayv2_client.get_routes(ApiId=api_id)
                        routes = routes_response.get('Items', [])
                        
                        if routes:
                            print(f"Found {len(routes)} routes")
                            for route in routes:
                                route_id = route['RouteId']
                                route_key = route.get('RouteKey', 'No key')
                                target = route.get('Target', 'No target')
                                
                                print(f"Deleting route: {route_key} (ID: {route_id}) - Target: {target}")
                                try:
                                    apigatewayv2_client.delete_route(
                                        ApiId=api_id,
                                        RouteId=route_id
                                    )
                                    print(f"✅ Deleted route: {route_key}")
                                except Exception as e:
                                    print(f"❌ Failed to delete route {route_id}: {e}")
                        else:
                            print("No routes found")
                    except Exception as e:
                        print(f"Warning: Could not check routes for {api_name}: {e}")
                    
                    # 3. Delete all integrations
                    print(f"Checking integrations for HTTP API {api_name}...")
                    try:
                        integrations_response = apigatewayv2_client.get_integrations(ApiId=api_id)
                        integrations = integrations_response.get('Items', [])
                        
                        if integrations:
                            print(f"Found {len(integrations)} integrations")
                            for integration in integrations:
                                integration_id = integration['IntegrationId']
                                integration_type = integration.get('IntegrationType', 'Unknown')
                                integration_uri = integration.get('IntegrationUri', 'No URI')
                                
                                print(f"Deleting integration: {integration_id} (Type: {integration_type}) - URI: {integration_uri}")
                                try:
                                    apigatewayv2_client.delete_integration(
                                        ApiId=api_id,
                                        IntegrationId=integration_id
                                    )
                                    print(f"✅ Deleted integration: {integration_id}")
                                except Exception as e:
                                    print(f"❌ Failed to delete integration {integration_id}: {e}")
                        else:
                            print("No integrations found")
                    except Exception as e:
                        print(f"Warning: Could not check integrations for {api_name}: {e}")
                    
                    # 4. Delete domain name mappings (v2)
                    print(f"Checking domain name mappings for HTTP API {api_name}...")
                    try:
                        domain_names_response = apigatewayv2_client.get_domain_names()
                        domain_names = domain_names_response.get('Items', [])
                        
                        for domain in domain_names:
                            domain_name = domain['DomainName']
                            
                            # Check API mappings
                            try:
                                mappings_response = apigatewayv2_client.get_api_mappings(DomainName=domain_name)
                                mappings = mappings_response.get('Items', [])
                                
                                for mapping in mappings:
                                    if mapping.get('ApiId') == api_id:
                                        mapping_id = mapping['ApiMappingId']
                                        api_mapping_key = mapping.get('ApiMappingKey', '(none)')
                                        stage = mapping.get('Stage', 'Unknown')
                                        
                                        print(f"Deleting API mapping: {api_mapping_key} (Stage: {stage}) for domain {domain_name}")
                                        try:
                                            apigatewayv2_client.delete_api_mapping(
                                                ApiMappingId=mapping_id,
                                                DomainName=domain_name
                                            )
                                            print(f"✅ Deleted API mapping: {api_mapping_key}")
                                        except Exception as e:
                                            print(f"❌ Failed to delete API mapping: {e}")
                            except Exception as e:
                                print(f"Warning: Could not check mappings for domain {domain_name}: {e}")
                    except Exception as e:
                        print(f"Warning: Could not check domain names for {api_name}: {e}")
                    
                    # 5. Delete the HTTP API
                    print(f"Deleting HTTP API: {api_name} ({api_id})")
                    apigatewayv2_client.delete_api(ApiId=api_id)
                    print(f"✅ Deleted HTTP API: {api_name}")
                    
                    # Wait a moment between deletions
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"❌ Failed to process HTTP API {api_name}: {e}")
    
    except Exception as e:
        print(f"❌ Error processing HTTP APIs: {e}")
    
    # ========================================
    # 3. DELETE WEBSOCKET APIs (API Gateway v2)
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("PROCESSING WEBSOCKET APIs (API Gateway v2)")
        print(f"{'='*80}")
        
        # Filter for WebSocket APIs
        websocket_apis = [api for api in all_http_apis if api.get('ProtocolType') == 'WEBSOCKET']
        
        if not websocket_apis:
            print("No WebSocket APIs found")
        else:
            print(f"Found {len(websocket_apis)} WebSocket APIs")
            
            for api in websocket_apis:
                api_id = api['ApiId']
                api_name = api['Name']
                protocol_type = api['ProtocolType']
                api_endpoint = api.get('ApiEndpoint', 'No endpoint')
                
                print(f"\n--- Processing WebSocket API ---")
                print(f"ID: {api_id}")
                print(f"Name: {api_name}")
                print(f"Protocol: {protocol_type}")
                print(f"Endpoint: {api_endpoint}")
                
                # Check if API should be kept
                if api_name in apis_to_keep or api_id in apis_to_keep:
                    print(f"🔒 Keeping WebSocket API: {api_name} (in keep list)")
                    continue
                
                try:
                    # Similar cleanup process as HTTP APIs
                    # Delete stages, routes, integrations, then the API itself
                    print(f"Deleting WebSocket API: {api_name} ({api_id})")
                    apigatewayv2_client.delete_api(ApiId=api_id)
                    print(f"✅ Deleted WebSocket API: {api_name}")
                    
                except Exception as e:
                    print(f"❌ Failed to process WebSocket API {api_name}: {e}")
    
    except Exception as e:
        print(f"❌ Error processing WebSocket APIs: {e}")
    
    # ========================================
    # 4. CLEANUP REMAINING RESOURCES
    # ========================================
    try:
        print(f"\n{'='*80}")
        print("CLEANING UP REMAINING API GATEWAY RESOURCES")
        print(f"{'='*80}")
        
        # Clean up unused domain names
        print("Checking for unused domain names...")
        try:
            # v1 domain names
            v1_domains = apigateway_client.get_domain_names().get('items', [])
            for domain in v1_domains:
                domain_name = domain['domainName']
                try:
                    mappings = apigateway_client.get_base_path_mappings(domainName=domain_name).get('items', [])
                    if not mappings:
                        print(f"Deleting unused v1 domain: {domain_name}")
                        apigateway_client.delete_domain_name(domainName=domain_name)
                        print(f"✅ Deleted v1 domain: {domain_name}")
                except Exception as e:
                    print(f"Warning: Could not delete v1 domain {domain_name}: {e}")
            
            # v2 domain names
            v2_domains = apigatewayv2_client.get_domain_names().get('Items', [])
            for domain in v2_domains:
                domain_name = domain['DomainName']
                try:
                    mappings = apigatewayv2_client.get_api_mappings(DomainName=domain_name).get('Items', [])
                    if not mappings:
                        print(f"Deleting unused v2 domain: {domain_name}")
                        apigatewayv2_client.delete_domain_name(DomainName=domain_name)
                        print(f"✅ Deleted v2 domain: {domain_name}")
                except Exception as e:
                    print(f"Warning: Could not delete v2 domain {domain_name}: {e}")
                    
        except Exception as e:
            print(f"Warning: Could not clean up domain names: {e}")
        
        # Clean up unused API keys
        print("Checking for unused API keys...")
        try:
            api_keys = apigateway_client.get_api_keys().get('items', [])
            for api_key in api_keys:
                api_key_id = api_key['id']
                api_key_name = api_key.get('name', 'Unnamed')
                
                # Check if API key is associated with any usage plans
                usage_plans = apigateway_client.get_usage_plans().get('items', [])
                key_in_use = False
                
                for usage_plan in usage_plans:
                    try:
                        keys_in_plan = apigateway_client.get_usage_plan_keys(
                            usagePlanId=usage_plan['id']
                        ).get('items', [])
                        if any(key.get('id') == api_key_id for key in keys_in_plan):
                            key_in_use = True
                            break
                    except:
                        pass
                
                if not key_in_use:
                    print(f"Deleting unused API key: {api_key_name}")
                    try:
                        apigateway_client.delete_api_key(apiKey=api_key_id)
                        print(f"✅ Deleted API key: {api_key_name}")
                    except Exception as e:
                        print(f"❌ Failed to delete API key {api_key_name}: {e}")
                        
        except Exception as e:
            print(f"Warning: Could not clean up API keys: {e}")
    
    except Exception as e:
        print(f"Warning: Could not perform final cleanup: {e}")
    
    print(f"\n✅ Completed comprehensive API Gateway cleanup in {region}")

@measure_time
def delete_kms_keys(keys_to_keep, region):
    """
    Delete all KMS keys in the specified region except those specified to keep.
    """
    print(f"Region passed to delete_kms_keys: {region}")  # Debugging statement

    # Ensure the region is a string and not a list or other type
    if not isinstance(region, str):
        raise ValueError("Region name must be a string")
    
    # Initialize the KMS client for the specified AWS region
    kms_client = boto3.client('kms', region_name=region)

    # Get the names of all keys
    all_key_ids = [key['KeyId'] for key in kms_client.list_keys()['Keys']]

    print(f"\nDeleting KMS keys in region {region} except the ones specified to keep:")

    # Delete keys except the ones specified to keep
    for key_id in all_key_ids:
        if key_id not in keys_to_keep:
            print(f"\nDeleting key: {key_id}")
            # Try to delete the key
            try:
                kms_client.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=7)
                print(f"Key {key_id} scheduled for deletion.")
            except Exception as e:
                print(f"Error deleting key {key_id}: {e}")

@measure_time
def delete_internet_gateways(region):
    """
    Delete all internet gateways in the specified region, except those attached to the default VPC.
    """
    ec2 = boto3.client('ec2', region_name=region)
    
    # Describe all internet gateways
    response = ec2.describe_internet_gateways()
    for gateway in response['InternetGateways']:
        gateway_id = gateway['InternetGatewayId']
        # Skip default VPC gateways
        if any(attachment['VpcId'].endswith('default') for attachment in gateway['Attachments']):
            print(f"Skipping default internet gateway: {gateway_id}")
            continue
        
        # Detach from all VPCs
        for attachment in gateway['Attachments']:
            vpc_id = attachment['VpcId']
            try:
                print(f"Detaching internet gateway {gateway_id} from VPC {vpc_id}")
                ec2.detach_internet_gateway(InternetGatewayId=gateway_id, VpcId=vpc_id)
            except Exception as e:
                print(f"Failed to detach internet gateway {gateway_id} from VPC {vpc_id}: {e}")
                continue
        
        # Attempt to delete the internet gateway
        try:
            print(f"Deleting internet gateway: {gateway_id}")
            ec2.delete_internet_gateway(InternetGatewayId=gateway_id)
            print(f"Deleted internet gateway: {gateway_id}")
        except Exception as e:
            print(f"Failed to delete internet gateway {gateway_id}: {e}")

@measure_time
def delete_custom_vpcs(region):
    """
    Delete all custom VPCs in the specified region.
    """
    ec2 = boto3.client('ec2', region_name=region)
    
    vpcs = ec2.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['false']}])
    for vpc in vpcs['Vpcs']:
        vpc_id = vpc['VpcId']
        print(f"Deleting custom VPC: {vpc_id}")
        ec2.delete_vpc(VpcId=vpc_id)
        print(f"Deleted custom VPC: {vpc_id}")
        waiter = ec2.get_waiter('vpc_deleted')
        waiter.wait(VpcIds=[vpc_id])
        print(f"Deleted custom VPC: {vpc_id} (waited for deletion)")
        # Delete subnets
        subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
        for subnet in subnets['Subnets']:
            subnet_id = subnet['SubnetId']
            print(f"Deleting subnet: {subnet_id}")
            ec2.delete_subnet(SubnetId=subnet_id)
            print(f"Deleted subnet: {subnet_id}")
            waiter = ec2.get_waiter('subnet_deleted')
            waiter.wait(SubnetIds=[subnet_id])
            print(f"Deleted subnet: {subnet_id} (waited for deletion)")
            # Delete route tables
            route_tables = ec2.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
            for route_table in route_tables['RouteTables']:
                route_table_id = route_table['RouteTableId']
                print(f"Deleting route table: {route_table_id}")
                ec2.delete_route_table(RouteTableId=route_table_id)
                print(f"Deleted route table: {route_table_id}")
                waiter = ec2.get_waiter('route_table_deleted')
                waiter.wait(RouteTableIds=[route_table_id])
                print(f"Deleted route table: {route_table_id} (waited for deletion)")
                # Delete VPC endpoints
                endpoints = ec2.describe_vpc_endpoints(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                for endpoint in endpoints['VpcEndpoints']:
                    endpoint_id = endpoint['VpcEndpointId']
                    print(f"Deleting VPC endpoint: {endpoint_id}")
                    ec2.delete_vpc_endpoint(VpcEndpointId=endpoint_id)
                    print(f"Deleted VPC endpoint: {endpoint_id}")
                    waiter = ec2.get_waiter('vpc_endpoint_deleted')
                    waiter.wait(VpcEndpointIds=[endpoint_id])
                    print(f"Deleted VPC endpoint: {endpoint_id} (waited for deletion)")
                    # Delete VPC peering connections
                    peering_connections = ec2.describe_vpc_peering_connections(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                    for connection in peering_connections['VpcPeeringConnections']:
                        peer_vpc_id = connection['PeerVpcId']
                        print(f"Deleting VPC peering connection: {peer_vpc_id}")
                        ec2.delete_vpc_peering_connection(VpcPeeringConnectionId=connection['VpcPeeringConnectionId'])
                        print(f"Deleted VPC peering connection: {peer_vpc_id}")
                        waiter = ec2.get_waiter('vpc_peering_connection_deleted')
                        waiter.wait(VpcPeeringConnectionIds=[connection['VpcPeeringConnectionId']])
                        print(f"Deleted VPC peering connection: {peer_vpc_id} (waited for deletion)")
                        # Delete VPC security groups
                        security_groups = ec2.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                        for security_group in security_groups['SecurityGroups']:
                            security_group_id = security_group['GroupId']
                            print(f"Deleting security group: {security_group_id}")
                            ec2.delete_security_group(GroupId=security_group_id)
                            print(f"Deleted security group: {security_group_id}")
                            waiter = ec2.get_waiter('security_group_deleted')
                            waiter.wait(GroupIds=[security_group_id])
                            print(f"Deleted security group: {security_group_id} (waited for deletion)")
                            # Delete VPC flow logs
                            flow_logs = ec2.describe_flow_logs(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                            for log in flow_logs['FlowLogs']:
                                log_id = log['FlowLogId']
                                print(f"Deleting VPC flow log: {log_id}")
                                ec2.delete_flow_logs(FlowLogIds=[log_id])
                                print(f"Deleted VPC flow log: {log_id}")
                                waiter = ec2.get_waiter('flow_log_deleted')
                                waiter.wait(FlowLogIds=[log_id])
                                print(f"Deleted VPC flow log: {log_id} (waited for deletion)")
                                # Delete VPC DHCPOptions
                                dhcp_options = ec2.describe_dhcp_options(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                                for dhcp_option in dhcp_options['DhcpOptions']:
                                    dhcp_option_id = dhcp_option['DhcpOptionsId']
                                    print(f"Deleting VPC DHCPOptions: {dhcp_option_id}")
                                    ec2.delete_dhcp_options(DhcpOptionsId=dhcp_option_id)
                                    print(f"Deleted VPC DHCPOptions: {dhcp_option_id}")
                                    waiter = ec2.get_waiter('dhcp_options_deleted')
                                    waiter.wait(DhcpOptionsIds=[dhcp_option_id])
                                    print(f"Deleted VPC DHCPOptions: {dhcp_option_id} (waited for deletion)")
                                # Delete VPC transit gateways
                                transit_gateways = ec2.describe_transit_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                                for transit_gateway in transit_gateways['TransitGateways']:
                                    transit_gateway_id = transit_gateway['TransitGatewayId']
                                    print(f"Deleting transit gateway: {transit_gateway_id}")
                                    ec2.delete_transit_gateway(TransitGatewayId=transit_gateway_id)
                                    print(f"Deleted transit gateway: {transit_gateway_id}")
                                    waiter = ec2.get_waiter('transit_gateway_deleted')
                                    waiter.wait(TransitGatewayIds=[transit_gateway_id])
                                    print(f"Deleted transit gateway: {transit_gateway_id} (waited for deletion)")

                                    # Delete VPC network ACLs
                                    network_acls = ec2.describe_network_acls(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                                    for network_acl in network_acls['NetworkAcls']:
                                        network_acl_id = network_acl['NetworkAclId']
                                        print(f"Deleting network ACL: {network_acl_id}")
                                        ec2.delete_network_acl(NetworkAclId=network_acl_id)
                                        print(f"Deleted network ACL: {network_acl_id}")
                                        waiter = ec2.get_waiter('network_acl_deleted')
                                        waiter.wait(NetworkAclIds=[network_acl_id])
                                        print(f"Deleted network ACL: {network_acl_id} (waited for deletion)")
                                        # Delete VPC customer gateways
                                        customer_gateways = ec2.describe_customer_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                                        for customer_gateway in customer_gateways['CustomerGateways']:
                                            customer_gateway_id = customer_gateway['CustomerGatewayId']
                                            print(f"Deleting customer gateway: {customer_gateway_id}")
                                            ec2.delete_customer_gateway(CustomerGatewayId=customer_gateway_id)
                                            print(f"Deleted customer gateway: {customer_gateway_id}")
                                            waiter = ec2.get_waiter('customer_gateway_deleted')
                                            waiter.wait(CustomerGatewayIds=[customer_gateway_id])
                                            print(f"Deleted customer gateway: {customer_gateway_id} (waited for deletion)")
                                        # Delete VPC DynamoDB tables
                                        dynamodb_tables = ec2.describe_table(TableName=f'MyTable-{vpc_id}')
                                        if 'Table' in dynamodb_tables:
                                             dynamodb_table_name = dynamodb_tables['Table']['TableName']
                                             print(f"Deleting DynamoDB table: {dynamodb_table_name}")
                                             ec2.delete_table(TableName=dynamodb_table_name)
                                             print(f"Deleted DynamoDB table: {dynamodb_table_name}")
                                             waiter = ec2.get_waiter('table_not_exists')
                                             waiter.wait(TableName=dynamodb_table_name)
                                             print(f"Deleted DynamoDB table: {dynamodb_table_name} (waited for deletion)")
                            # Delete VPC NAT gateways
                            nat_gateways = ec2.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                            for nat_gateway in nat_gateways['NatGateways']:
                                nat_gateway_id = nat_gateway['NatGatewayId']
                                print(f"Deleting NAT gateway: {nat_gateway_id}")
                                ec2.delete_nat_gateway(NatGatewayId=nat_gateway_id)
                                print(f"Deleted NAT gateway: {nat_gateway_id}")
                                waiter = ec2.get_waiter('nat_gateway_deleted')
                                waiter.wait(NatGatewayIds=[nat_gateway_id])
                                print(f"Deleted NAT gateway: {nat_gateway_id} (waited for deletion)")
                            # Delete VPC internet gateways
                            internet_gateways = ec2.describe_internet_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                            for internet_gateway in internet_gateways['InternetGateways']:
                                internet_gateway_id = internet_gateway['InternetGatewayId']
                                print(f"Deleting internet gateway: {internet_gateway_id}")
                                ec2.delete_internet_gateway(InternetGatewayId=internet_gateway_id)
                                print(f"Deleted internet gateway: {internet_gateway_id}")
                                waiter = ec2.get_waiter('internet_gateway_deleted')
                                waiter.wait(InternetGatewayIds=[internet_gateway_id])
                                print(f"Deleted internet gateway: {internet_gateway_id} (waited for deletion)")

@measure_time
def delete_ec2_snapshots(region):
    ec2 = boto3.resource('ec2', region_name=region)
    snapshots = ec2.snapshots.filter(OwnerIds=['self'])  # Ensure to operate only on owned snapshots
    
    for snapshot in snapshots:
        try:
            print(f"Attempting to delete snapshot: {snapshot.id}")
            snapshot.delete()
            print(f"Snapshot deletion initiated: {snapshot.id}")

            # Custom polling to check if the snapshot is deleted
            while True:
                try:
                    snapshot.reload()
                except Exception as e:
                    if 'InvalidSnapshot.NotFound' in str(e):
                        print(f"Snapshot {snapshot.id} has been successfully deleted.")
                        break
                    else:
                        raise e
                print(f"Waiting for snapshot {snapshot.id} to be deleted...")
                time.sleep(5)

        except Exception as e:
            if hasattr(e, 'response') and e.response['Error']['Code'] == 'InvalidSnapshot.NotFound':
                print(f"Snapshot {snapshot.id} does not exist or is already deleted.")
            else:
                print(f"An error occurred: {str(e)}")

@measure_time
def set_aws_profile(profile_name, access_key, secret_key, region="us-east-1"):
    """Set AWS credentials in environment variables and create AWS CLI profile"""
    import subprocess
    
    # Set environment variables (primary method)
    os.environ['AWS_ACCESS_KEY_ID'] = access_key
    os.environ['AWS_SECRET_ACCESS_KEY'] = secret_key
    os.environ['AWS_DEFAULT_REGION'] = region
    os.environ['AWS_PROFILE'] = profile_name
    
    # Also create AWS CLI profile as backup
    try:
        subprocess.run([
            "aws", "configure", "set", "aws_access_key_id",
            access_key, "--profile", profile_name
        ], check=True, capture_output=True)
        
        subprocess.run([
            "aws", "configure", "set", "aws_secret_access_key",
            secret_key, "--profile", profile_name
        ], check=True, capture_output=True)
        
        subprocess.run([
            "aws", "configure", "set", "region",
            region, "--profile", profile_name
        ], check=True, capture_output=True)
        
        print(f"✅ Set AWS profile: {profile_name}")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Warning: Could not create AWS CLI profile {profile_name}, using environment variables only")

@measure_time
@measure_time
def delete_all_iam_roles(region):
    """
    Delete all IAM roles in the specified region, except service-linked roles.
    """
    iam = boto3.client('iam', region_name=region)
    
    try:
        # List all IAM roles
        roles = iam.list_roles()
        for role in roles['Roles']:
            role_name = role['RoleName']
            
            # Skip deleting service-linked roles
            if role['Path'].startswith('/aws-service-role/'):
                print(f"Skipping service-linked role: {role_name}")
                continue
            
            try:
                # 1. Detach all managed policies
                try:
                    policies = iam.list_attached_role_policies(RoleName=role_name)['AttachedPolicies']
                    for policy in policies:
                        iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
                        print(f"Detached managed policy {policy['PolicyArn']} from role {role_name}")
                except Exception as e:
                    print(f"Failed to detach managed policies from {role_name}: {e}")

                # 2. Delete all inline policies
                try:
                    inline_policies = iam.list_role_policies(RoleName=role_name)['PolicyNames']
                    for policy_name in inline_policies:
                        iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                        print(f"Deleted inline policy {policy_name} from role {role_name}")
                except Exception as e:
                    print(f"Failed to delete inline policies from {role_name}: {e}")

                # 3. Remove role from instance profiles
                try:
                    instance_profiles = iam.list_instance_profiles_for_role(RoleName=role_name)['InstanceProfiles']
                    for profile in instance_profiles:
                        try:
                            iam.remove_role_from_instance_profile(
                                InstanceProfileName=profile['InstanceProfileName'],
                                RoleName=role_name
                            )
                            print(f"Removed role {role_name} from instance profile {profile['InstanceProfileName']}")
                        except Exception as e:
                            print(f"Failed to remove role {role_name} from instance profile {profile['InstanceProfileName']}: {e}")
                except Exception as e:
                    print(f"Failed to list instance profiles for role {role_name}: {e}")
                
                # 4. Delete the role
                iam.delete_role(RoleName=role_name)
                print(f"Deleted IAM role: {role_name}")
                
            except Exception as e:
                print(f"Failed to delete IAM role {role_name}: {e}")
                
    except Exception as e:
        print(f"Failed to retrieve roles: {e}")

def setup_aws_profiles(accounts):
    """Setup AWS profiles using AWS CLI"""
    import subprocess
    print("🔧 Setting up AWS profiles...")
    
    for profile_name, account_info in accounts.items():
        try:
            subprocess.run([
                "aws", "configure", "set", "aws_access_key_id",
                account_info["access_key"], "--profile", profile_name
            ], check=True, capture_output=True)
            
            subprocess.run([
                "aws", "configure", "set", "aws_secret_access_key",
                account_info["secret_key"], "--profile", profile_name
            ], check=True, capture_output=True)
            
            subprocess.run([
                "aws", "configure", "set", "region",
                "us-east-1", "--profile", profile_name
            ], check=True, capture_output=True)
            
            print(f"✅ Profile '{profile_name}' configured successfully")
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to configure profile '{profile_name}': {e}")

def delete_aws_profiles(profiles):
    """Delete AWS profiles"""
    import subprocess
    from pathlib import Path
    
    print("🗑️ Deleting AWS profiles...")
    for profile in profiles:
        try:
            # Remove profile sections by setting empty values
            subprocess.run([
                "aws", "configure", "set", "aws_access_key_id", "", 
                "--profile", profile
            ], capture_output=True)
            
            subprocess.run([
                "aws", "configure", "set", "aws_secret_access_key", "", 
                "--profile", profile
            ], capture_output=True)
            
            subprocess.run([
                "aws", "configure", "set", "region", "", 
                "--profile", profile
            ], capture_output=True)
            
            print(f"✅ Deleted profile: {profile}")
            
        except Exception as e:
            print(f"❌ Failed to delete profile {profile}: {e}")

def set_current_profile(profile_name):
    """Set the current AWS profile via environment variable"""
    os.environ['AWS_PROFILE'] = profile_name
    print(f"🔄 Switched to profile: {profile_name}")

if __name__ == "__main__":
    # Load AWS accounts configuration
    CONFIG_FILE = "aws_accounts_config.json"
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        accounts = config["accounts"]
        print(f"✅ Loaded configuration from {CONFIG_FILE}")
    except FileNotFoundError:
        print(f"❌ Configuration file {CONFIG_FILE} not found!")
        exit(1)
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in {CONFIG_FILE}")
        exit(1)

    # Setup AWS profiles for ALL accounts first
    setup_aws_profiles(accounts)

    # Display available accounts and get selection
    account_list = list(accounts.keys())
    print(f"\n{'='*80}")
    print("📋 Available AWS Accounts:")
    print(f"{'='*80}")
    for i, acc in enumerate(account_list, 1):
        acc_info = accounts[acc]
        print(f"{i:2d}. {acc} (ID: {acc_info['account_id']}, Email: {acc_info['email']})")
    print(f"{len(account_list)+1:2d}. ALL")

    # Get user selection for accounts
    selected = input(f"\nSelect accounts to process (comma-separated numbers, range with -, or 'all'): ").strip()
    
    if selected.lower() == "all" or selected == str(len(account_list) + 1):
        selected_accounts = account_list
    else:
        selected_accounts = []
        parts = selected.split(',')
        for part in parts:
            part = part.strip()
            if '-' in part and not part.startswith('-'):
                try:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        if 1 <= i <= len(account_list):
                            selected_accounts.append(account_list[i-1])
                except ValueError:
                    print(f"⚠️ Invalid range: {part}")
            else:
                try:
                    num = int(part)
                    if 1 <= num <= len(account_list):
                        selected_accounts.append(account_list[num-1])
                except ValueError:
                    print(f"⚠️ Invalid number: {part}")
        selected_accounts = list(set(selected_accounts))

    if not selected_accounts:
        print("❌ No accounts selected. Exiting.")
        exit(1)

    print(f"\n✅ Selected accounts: {', '.join(selected_accounts)}")

    # Configuration constants
    BUCKETS_TO_KEEP = ["vm-import-export-bucket-01", "vd-employee-app"]
    TABLES_TO_KEEP = ["Table1", "Table2"]
    LAMBDA_FUNCTIONS_TO_KEEP = ["function1", "function2"]

    # Start overall timing
    overall_start_time = time.time()
    start_time = datetime.utcnow()
    successful_accounts = 0
    failed_accounts = []

    # Process each selected account
    for acc_idx, acc in enumerate(selected_accounts, 1):
        acc_info = accounts[acc]
        print(f"\n{'='*100}")
        print(f"🏢 Processing account {acc_idx}/{len(selected_accounts)}: {acc}")
        print(f"{'='*100}")
        print(f"🆔 Account ID: {acc_info['account_id']}")
        print(f"📧 Email: {acc_info['email']}")
        print(f"⏰ Started at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{'='*100}")
        
        try:
            # Switch to the current account profile
            set_current_profile(acc)
            
            # Process all regions for this account
            for region in REGIONS:
                print(f"\n🌍 Working on region: {region}")
                
                # 1. First, disable resource protections
            stop_codebuild_builds(region)               # Stop running builds
            stop_codepipeline_executions(region)        # (Add this function to stop pipeline executions)

            # 2. Applications and services that generate other resources
            delete_elastic_beanstalk_applications(region)  # These create many dependent resources
            delete_eks_clusters(region)                    # These create many dependent resources
            delete_all_ecs_clusters(region)                # These require networking resources

            # 3. API Gateway and Lambda resources
            delete_api_gateway_rest_apis([], region)       # APIs often connect to Lambda
            delete_lambda_functions_except(LAMBDA_FUNCTIONS_TO_KEEP, region)
            delete_lambda_functions(region)                # Remove duplicate call - use only one Lambda delete

            # 4. Message and queue services
            delete_sns_topics(region)                      # SNS topics may trigger other resources
            delete_all_sns_subscriptions(region)           # Delete subscriptions before topics
            purge_and_delete_sqs_queues(region)            # SQS queues may be triggered by other services

            # 5. Database and storage resources
            delete_rds_instances(region)                   # RDS may have dependencies
            delete_elastic_cache_clusters([], region)      # ElastiCache clusters may have dependencies
            delete_multipart_uploads(region)               # Clean up S3 multipart uploads before buckets
            delete_s3_buckets(BUCKETS_TO_KEEP, region)     # S3 buckets may store deployment artifacts
            delete_dynamodb_tables_except(TABLES_TO_KEEP, region)

            # 6. Compute resources
            delete_auto_scaling_groups(region)             # Delete ASGs before their EC2 instances
            delete_launch_templates(region)                # Launch templates used by ASGs
            delete_ec2_instances(region)                   # Delete standalone EC2 instances
            delete_amis(region)                            # Delete AMIs before snapshots
            delete_ebs_snapshots(region)                   # Delete snapshots before volumes
            delete_ebs_volumes(region)                     # Delete volumes last in the compute section
            delete_ecr_repositories(region)                # Container repositories

            # 7. Load balancing and networking
            delete_load_balancers_and_target_groups(region)  # Load balancers may have dependencies
            release_elastic_ips(region)                      # Release IPs before deleting VPCs
            delete_cloudformation_stacks(region)             # CloudFormation stacks create multiple resources

            # 8. Network dependencies (order matters here)
            remove_vpc_endpoints(region)                     # VPC endpoints must be deleted before VPCs
            delete_vpc_peering_connections(region)           # VPC peering must be deleted before VPCs
            terminate_vpn_connections(region)                # VPN connections must be deleted before VPCs
            delete_security_groups(region)                   # Security groups might have cross-references
            delete_custom_vpcs(region)                       # VPCs should be deleted after all their resources

            # 9. Development and deployment resources
            delete_codebuild_projects(region)
            delete_codepipelines(region)
            delete_codecommit_repositories(region)
            delete_codedeploy_applications(region)
            delete_key_pairs(region)

            # 10. Storage and backup services
            delete_datasync_resources(region)
            delete_efs_resources(region)
            delete_storage_gateway_resources(region)
            delete_aws_backup_resources(region)
            delete_transfer_family_resources(region)

            # 11. Monitoring and IAM resources (do these last)
            delete_cloudwatch_alarms(region)                  # Delete alarms that might monitor services
            delete_route53_hosted_zones(region)               # DNS should be deleted last to prevent failures
            delete_kms_keys([], region)                       # KMS keys might be used by other resources
            delete_all_iam_roles(region)                      # IAM roles might be used by other resources
            delete_iam_roles(region)                          # Remove duplicate call - use only one IAM role delete
            
            successful_accounts += 1
            print(f"\n✅ Completed account: {acc}")
            
        except Exception as e:
            failed_accounts.append(acc)
            print(f"\n❌ Failed to process account {acc}: {e}")
            
        # Pause between accounts if not the last one
        if acc_idx < len(selected_accounts):
            print(f"\n⏸️ Pausing before next account...")
            time.sleep(2)

    # Calculate total time and show summary
    overall_end_time = time.time()
    end_time = datetime.utcnow()
    total_time = overall_end_time - overall_start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Final summary
    print(f"\n{'='*100}")
    print("📊 FINAL EXECUTION SUMMARY")
    print(f"{'='*100}")
    print(f"⏰ Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"⏰ End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"⏱️ Total Duration: {int(hours)} hours {int(minutes)} minutes {seconds:.2f} seconds")
    print(f"👤 User: varadharajaan")
    print(f"📁 Config File: {CONFIG_FILE}")
    print(f"🏢 Total accounts: {len(selected_accounts)}")
    print(f"✅ Successful executions: {successful_accounts}")
    print(f"❌ Failed executions: {len(selected_accounts) - successful_accounts}")
    
    if failed_accounts:
        print(f"\n❌ Failed accounts: {', '.join(failed_accounts)}")
    
    print(f"{'='*100}")
    print("\n🎉 All selected accounts processed!")

    # Ask user if they want to delete profiles
    delete_profiles_confirm = input("\n🗑️ Do you want to delete the AWS profiles that were created? (yes/no): ").strip().lower()
    if delete_profiles_confirm == "yes":
        delete_aws_profiles(selected_accounts)
        print("✅ AWS profiles have been deleted")
    else:
        print("ℹ️ AWS profiles retained")