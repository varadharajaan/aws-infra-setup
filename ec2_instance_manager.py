"""
EC2 Instance Manager - Enhanced with ASG support
Handles EC2 instance creation with automatic ASG attachment
"""

import json
import os

import boto3
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from datetime import datetime
from aws_credential_manager import CredentialInfo
import sys
import random
import string
import threading


@dataclass
class InstanceConfig:
    instance_type: str
    ami_id: str
    region: str
    launch_template_id: Optional[str] = None
    userdata_script: Optional[str] = None
    key_name: Optional[str] = None

class EC2InstanceManager:
    keypair_lock = threading.Lock()  # Add this at class level
    def __init__(self, ami_mapping_file='ec2-region-ami-mapping.json', userdata_file='userdata_allsupport.sh', current_user='varadharajaan'):
        self.ami_mapping_file = ami_mapping_file
        self.userdata_file = userdata_file
        self.ami_config = None
        self.current_user = current_user  # Add this line to define the current_user attribute
        self.load_ami_configuration()
        self.userdata_script = self.load_userdata_script()
        self.keypair_name = 'k8s_demo_key'

    
    def generate_random_suffix(self,length=4):
        """Generate a random alphanumeric suffix of specified length"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def load_ami_configuration(self):
        """Load AMI mapping configuration"""
        try:
            if not os.path.exists(self.ami_mapping_file):
                raise FileNotFoundError(f"AMI mapping file '{self.ami_mapping_file}' not found")
            
            with open(self.ami_mapping_file, 'r') as f:
                self.ami_config = json.load(f)
            
            print(f"✅ AMI configuration loaded from: {self.ami_mapping_file}")
            
        except Exception as e:
            print(f"❌ Error loading AMI configuration: {e}")
            raise

    def prepare_userdata_with_aws_config_enchanced(self, base_userdata, access_key, secret_key, region, account_name=None):
        """Add AWS credentials to userdata script for both default and custom profiles"""

        # Create custom profile name based on user type
        if account_name:
            if self.current_user == "root":
                custom_profile = f"root-{account_name.lower()}"
            else:
                custom_profile = self.current_user
        else:
            custom_profile = self.current_user

        # Replace placeholder variables if they exist
        enhanced_userdata = base_userdata.replace('${AWS_ACCESS_KEY_ID}', access_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_SECRET_ACCESS_KEY}', secret_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_DEFAULT_REGION}', region)

        # Create AWS config block for both default and custom profiles
        aws_config_commands = f"""
    # Configure AWS CLI with both default and custom profiles
    echo "Configuring AWS CLI for ec2-user..."
    sudo -u ec2-user bash <<EOF
    # Configure default profile
    aws configure set aws_access_key_id "{access_key}"
    aws configure set aws_secret_access_key "{secret_key}"
    aws configure set default.region "{region}"
    aws configure set default.output "json"

    # Configure custom profile ({custom_profile})
    aws configure set aws_access_key_id "{access_key}" --profile {custom_profile}
    aws configure set aws_secret_access_key "{secret_key}" --profile {custom_profile}
    aws configure set region "{region}" --profile {custom_profile}
    aws configure set output "json" --profile {custom_profile}
    EOF

    echo "✅ AWS CLI configured with profiles: default and {custom_profile}"

    # Test the credentials
    sudo -u ec2-user bash <<EOF
    echo "Testing AWS credentials for default profile:"
    aws sts get-caller-identity || echo "⚠️ Default profile credentials may be invalid"

    echo "Testing AWS credentials for {custom_profile} profile:"
    aws sts get-caller-identity --profile {custom_profile} || echo "⚠️ {custom_profile} profile credentials may be invalid"
    EOF
    """

        # Check if we can find the AWS CLI configuration section in userdata
        if "Configure AWS CLI" in enhanced_userdata and "aws configure set" in enhanced_userdata:
            # Look for the section after "Configuring AWS CLI for ec2-user..."
            parts = enhanced_userdata.split('echo "Configuring AWS CLI for ec2-user..."', 1)
            if len(parts) == 2:
                # Split at the end of existing config section
                before_config = parts[0] + 'echo "Configuring AWS CLI for ec2-user..."'
                after_config = parts[1]

                # Find where the configuration section ends
                if "echo \"✅ AWS CLI configured" in after_config:
                    end_marker = "echo \"✅ AWS CLI configured"
                    config_parts = after_config.split(end_marker, 1)
                    if len(config_parts) == 2:
                        # Replace the entire configuration section
                        enhanced_userdata = before_config + aws_config_commands
                        return enhanced_userdata

        # If we couldn't find the right section to replace, let's check if the file
        # has aws configure commands and replace that entire section
        if "aws configure set aws_access_key_id" in enhanced_userdata:
            # Find the sudo -u ec2-user bash part
            start_marker = "sudo -u ec2-user bash <<EOF"
            end_marker = "EOF"

            # Split at start marker
            parts = enhanced_userdata.split(start_marker, 1)
            if len(parts) == 2:
                before_block = parts[0]
                after_start = parts[1]

                # Split at end marker
                config_parts = after_start.split(end_marker, 1)
                if len(config_parts) == 2:
                    # Replace the entire block
                    enhanced_userdata = before_block + aws_config_commands + config_parts[1]
                    return enhanced_userdata

        # If we couldn't find a good place to replace, just add it after AWS CLI installation
        if "awscli" in enhanced_userdata:
            enhanced_userdata = enhanced_userdata.replace(
                "sudo dnf install -y git vim htop awscli python3-pip",
                "sudo dnf install -y git vim htop awscli python3-pip\n" + aws_config_commands
            )
        else:
            # Just append at the end if we can't find a good insertion point
            enhanced_userdata += "\n\n" + aws_config_commands

        return enhanced_userdata

    def prepare_userdata_with_aws_config(self, base_userdata, access_key, secret_key, region):
        """Add AWS credentials to userdata script"""
        
        # Replace placeholder variables in userdata
        enhanced_userdata = base_userdata.replace('${AWS_ACCESS_KEY_ID}', access_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_SECRET_ACCESS_KEY}', secret_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_DEFAULT_REGION}', region)
        
        return enhanced_userdata
    
    def load_userdata_script(self):
        """Load the user data script content from external file with proper encoding handling"""
        try:
            if not os.path.exists(self.userdata_file):
                raise FileNotFoundError(f"User data script file '{self.userdata_file}' not found")
            
            # Try different encodings in order of preference
            encodings_to_try = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            user_data_content = None
            encoding_used = None
            
            for encoding in encodings_to_try:
                try:
                    with open(self.userdata_file, 'r', encoding=encoding) as f:
                        user_data_content = f.read()
                    encoding_used = encoding
                    print(f"✅ Successfully read user data script using {encoding} encoding")
                    break
                except UnicodeDecodeError as e:
                    print(f"Failed to read with {encoding} encoding: {e}")
                    continue
                except Exception as e:
                    print(f"Error reading with {encoding} encoding: {e}")
                    continue
            
            if user_data_content is None:
                raise ValueError(f"Could not read {self.userdata_file} with any supported encoding")
            
            print(f"📜 User data script loaded from: {self.userdata_file}")
            print(f"🔤 Encoding used: {encoding_used}")
            print(f"📏 User data script size: {len(user_data_content)} characters")
            
            # Clean up any problematic characters
            user_data_content = user_data_content.replace('\r\n', '\n')  # Normalize line endings
            user_data_content = user_data_content.replace('\r', '\n')    # Handle old Mac line endings
            
            # Validate that it's a bash script
            lines = user_data_content.strip().split('\n')
            if lines and not lines[0].startswith('#!'):
                self.logger.warning("User data script doesn't start with a shebang (#!)")
                # Add shebang if missing
                user_data_content = '#!/bin/bash\n\n' + user_data_content
                self.logger.info("Added #!/bin/bash shebang to user data script")
            
            # Remove any non-ASCII characters that might cause issues
            user_data_content = ''.join(char for char in user_data_content if ord(char) < 128 or char.isspace())
            
            return user_data_content
            
        except FileNotFoundError as e:
            print(f"User data script file error: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error loading user data script: {e}")
            sys.exit(1)

    def load_userdata_script_bk(self):
        """Load userdata script from file"""
        try:
            userdata_file = 'userdata_allsupport.sh'
            if os.path.exists(userdata_file):
                with open(userdata_file, 'r') as f:
                    self.userdata_script = f.read()
                print(f"✅ Userdata script loaded from: {userdata_file}")
            else:
                print(f"⚠️ Userdata script not found: {userdata_file}")
                self.userdata_script = "#!/bin/bash\necho 'Default userdata script'"
        except Exception as e:
            print(f"❌ Error loading userdata script: {e}")
            self.userdata_script = "#!/bin/bash\necho 'Default userdata script'"
    
    def get_allowed_instance_types(self, region: str = None) -> List[str]:
        """Get allowed instance types for region"""
        # First check region-specific types
        if region and region in self.ami_config.get('region_instance_types', {}):
            return self.ami_config['region_instance_types'][region]
        
        # Fall back to global allowed types
        return self.ami_config.get('allowed_instance_types', ['t3.micro'])
    
    def get_default_instance_types(self) -> List[str]:
        """Get default instance types for user selection"""
        defaults = ['t3.micro', 'c6a.large', 'c6i.large', 't3.medium', 't3a.medium']
        allowed = self.ami_config.get('allowed_instance_types', [])
        
        # Return intersection of defaults and allowed
        return [instance_type for instance_type in defaults if instance_type in allowed]
    
    def select_instance_type(self, region: str) -> str:
        """Prompt user to select instance type with sorting by quota availability"""
        from spot_instance_analyzer import SpotInstanceAnalyzer
    
        allowed_types = self.get_allowed_instance_types(region)
        default_types = self.get_default_instance_types()
    
        # Get quota information for instance types using SpotInstanceAnalyzer
        try:
            # Create temporary credential info for quota analysis
            class SimpleCredInfo:
                def __init__(self, region):
                    self.regions = [region]
                    self.access_key = None
                    self.secret_key = None
                    self.username = "system"
                    self.account_name = "current"
                
            # Initialize spot analyzer with AWS credentials
            spot_analyzer = SpotInstanceAnalyzer(region=region)
        
            # Create simple credential object
            cred_info = SimpleCredInfo(region)
        
            # If we have AWS credentials from self.credentials, use them
            if hasattr(self, 'credentials') and self.credentials:
                cred_info.access_key = self.credentials.get('access_key')
                cred_info.secret_key = self.credentials.get('secret_key')
            
            spot_analyzer.set_credentials(cred_info)
        
            # Get quota information
            quota_info = spot_analyzer.analyze_service_quotas(cred_info, allowed_types)
        
            # Sort instance types by available capacity
            instance_types_with_quota = []
            for instance_type in allowed_types:
                family = instance_type.split('.')[0]
                is_default = instance_type in default_types
                available_capacity = 32  # Default value
            
                if family in quota_info:
                    available_capacity = quota_info[family].available_capacity
                
                instance_types_with_quota.append({
                    'instance_type': instance_type,
                    'available_capacity': available_capacity,
                    'is_default': is_default
                })
        
            # Sort first by whether it's a default type, then by available capacity (high to low)
            sorted_instances = sorted(
                instance_types_with_quota, 
                key=lambda x: (-x['is_default'], -x['available_capacity'])
            )
        
            # Build display list
            display_types = []
            for item in sorted_instances:
                instance_type = item['instance_type']
                quota = item['available_capacity']
                label = f"{instance_type} - {quota} available"
            
                if item['is_default']:
                    label += " (recommended)"
                
                display_types.append(label)

            print("\n" + "="*60)
            print("💻 SELECT INSTANCE TYPE")
            print("="*60)
        
            for i, display_text in enumerate(display_types, 1):
                print(f"  {i:2}. {display_text}")
        
            while True:
                try:
                    choice = input(f"Select instance type (1-{len(display_types)}): ").strip()
                    type_index = int(choice) - 1
                
                    if 0 <= type_index < len(display_types):
                        # Extract just the instance type from the display text
                        selected = sorted_instances[type_index]['instance_type']
                        return selected
                    else:
                        print(f"❌ Invalid choice. Please enter a number between 1 and {len(display_types)}")
                except ValueError:
                    print("❌ Please enter a valid number")
    
        except Exception as e:
            print(f"⚠️ Warning: Could not analyze service quotas: {e}")
            # Fall back to original method
            display_types = []
            for instance_type in default_types:
                if instance_type in allowed_types:
                    display_types.append(f"{instance_type} (recommended)")
                    allowed_types.remove(instance_type)
        
            # Add remaining types
            display_types.extend(allowed_types)

            print("\n" + "="*60)
            print("💻 SELECT INSTANCE TYPE")
            print("="*60)
        
            for i, instance_type in enumerate(display_types, 1):
                print(f"  {i:2}. {instance_type}")
        
            while True:
                try:
                    choice = input(f"Select instance type (1-{len(display_types)}): ").strip()
                    type_index = int(choice) - 1
                
                    if 0 <= type_index < len(display_types):
                        selected = display_types[type_index].split(' ')[0]  # Remove "(recommended)"
                        return selected
                    else:
                        print(f"❌ Invalid choice. Please enter a number between 1 and {len(display_types)}")
                except ValueError:
                    print("❌ Please enter a valid number")

    def create_launch_template(self, ec2_client, cred_info: CredentialInfo, instance_config: InstanceConfig, security_group_id=None) -> str:
        """Create launch template with userdata"""

        suffix = self.generate_random_suffix()

        # Create security group for this launch template ONLY IF ONE WASN'T PROVIDED
        if security_group_id is None:
            security_group_id = self.create_security_group(ec2_client, cred_info, suffix)

    
        template_name = f"lt-{cred_info.account_name}-{instance_config.region}-{suffix}"
    
        try:
            print(f"📋 Creating launch template: {template_name}")

            # Ensure user data is not None
            user_data = instance_config.userdata_script
            if not user_data:
                print("⚠️ Warning: User data script is empty, using default script.")
                user_data = "#!/bin/bash\necho 'Default userdata script'"

            import base64
            userdata_b64 = base64.b64encode(user_data.encode()).decode()

            response = ec2_client.create_launch_template(
                LaunchTemplateName=template_name,
                LaunchTemplateData={
                    'ImageId': instance_config.ami_id,
                    'InstanceType': instance_config.instance_type,
                    'UserData': userdata_b64,
                    'SecurityGroupIds': [security_group_id],
                    'KeyName': instance_config.key_name,  # Use provided key name
                    'TagSpecifications': [
                        {
                            'ResourceType': 'instance',
                            'Tags': [
                                {'Key': 'Name', 'Value': f'EC2-{cred_info.account_name}-{instance_config.region}-{suffix}'},
                                {'Key': 'CreatedBy', 'Value': 'EC2-ASG-Automation'},
                                {'Key': 'Account', 'Value': cred_info.account_name},
                                {'Key': 'Region', 'Value': instance_config.region}
                            ]
                        }
                    ]
                }
            )

            template_id = response['LaunchTemplate']['LaunchTemplateId']
            print(f"✅ Launch template created: {template_id}")
            return template_id

        except Exception as e:
                print(f"❌ Error creating launch template: {e}")
                raise
    
    def get_supported_subnets(self, ec2_client, region: str) -> List[Dict]:
        """
        Return a list of subnets in the default VPC that are in supported AZs for the given region.
        """
        unsupported_azs = self._get_unsupported_azs(region)
        # Get default VPC
        vpcs_response = ec2_client.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
        if not vpcs_response['Vpcs']:
            raise ValueError("No default VPC found")
        default_vpc_id = vpcs_response['Vpcs'][0]['VpcId']

        # Get all subnets in default VPC
        subnets_response = ec2_client.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [default_vpc_id]}])
        # Filter subnets to only those in supported AZs
        supported_subnets = [
            subnet for subnet in subnets_response['Subnets']
            if subnet['AvailabilityZone'] not in unsupported_azs
        ]
        return supported_subnets

        
    def create_security_group(self, ec2_client, cred_info: CredentialInfo, suffix=None) -> str:
        """Create a security group with all traffic allowed for inbound and outbound"""    
        if suffix is None:
            suffix = self.generate_random_suffix()
    
        sg_name = f"{self.current_user}_sg_{suffix}"
    
        try:
            print(f"🔒 Creating security group: {sg_name}")
        
            # Get default VPC ID
            vpcs_response = ec2_client.describe_vpcs(
                Filters=[{'Name': 'is-default', 'Values': ['true']}]
            )
        
            if not vpcs_response['Vpcs']:
                raise ValueError("No default VPC found")
            
            vpc_id = vpcs_response['Vpcs'][0]['VpcId']
        
            # Create security group
            sg_response = ec2_client.create_security_group(
                GroupName=sg_name,
                Description=f"Security group created by {self.current_user} with EC2-ASG-Automation",
                VpcId=vpc_id
            )
        
            sg_id = sg_response['GroupId']
        
            # Add inbound rule - allow all traffic
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',  # All protocols
                        'FromPort': -1,      # All ports
                        'ToPort': -1,        # All ports
                        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]  # All IPs
                    }
                ]
            )
        
            # Add outbound rule - allow all traffic (already default but explicitly setting)
            # ec2_client.authorize_security_group_egress(
            #     GroupId=sg_id,
            #     IpPermissions=[
            #         {
            #             'IpProtocol': '-1',  # All protocols
            #             'FromPort': -1,      # All ports
            #             'ToPort': -1,        # All ports
            #             'IpRanges': [{'CidrIp': '0.0.0.0/0'}]  # All IPs
            #         }
            #     ]
            # )
        
            print(f"✅ Security group created: {sg_id}")
            return sg_id
        
        except Exception as e:
            print(f"❌ Error creating security group: {e}")
            raise


    def ensure_key_pair(self, region, credential=None):
        """
        Ensure the EC2 key pair exists by importing the existing public key.
        If it doesn't exist, import the public key material from local file.
        Returns the key name.
        """
        import botocore

        key_name = self.keypair_name
        key_dir = "."  # Current directory

        # Use credential if provided, else default
        if credential:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=credential.access_key,
                aws_secret_access_key=credential.secret_key,
                region_name=region
            )
        else:
            ec2_client = boto3.client('ec2', region_name=region)

        with self.keypair_lock:
            try:
                # Check if key exists in AWS
                response = ec2_client.describe_key_pairs(KeyNames=[key_name])
                self.log_operation('INFO', f"EC2 key pair '{key_name}' already exists in AWS.")
                print(f"🔑 Key pair '{key_name}' already exists in region {region}")
                return key_name
            except botocore.exceptions.ClientError as e:
                if "InvalidKeyPair.NotFound" in str(e):
                    self.log_operation('INFO', f"Key pair '{key_name}' not found in AWS, importing from local file...")
                    print(f"🔑 Key pair '{key_name}' not found in region {region}. Importing public key...")

                    # Look for public key file
                    public_key_path = os.path.join(key_dir, f"{key_name}.pub")

                    try:
                        # Check if public key file exists
                        if not os.path.exists(public_key_path):
                            self.log_operation('ERROR', f"Public key file not found: {public_key_path}")
                            raise FileNotFoundError(f"Public key file not found: {public_key_path}")

                        # Read the public key file
                        with open(public_key_path, 'r') as f:
                            public_key_material = f.read().strip()

                        # Validate public key format
                        if not public_key_material.startswith(('ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-')):
                            raise ValueError("Invalid public key format")

                        # Import the public key to AWS
                        ec2_client.import_key_pair(
                            KeyName=key_name,
                            PublicKeyMaterial=public_key_material
                        )

                        self.log_operation('INFO',
                                           f"Successfully imported public key '{public_key_path}' as EC2 key pair '{key_name}'")
                        print(f"✅ Imported public key as EC2 key pair '{key_name}' in region {region}")
                        return key_name

                    except FileNotFoundError:
                        self.log_operation('ERROR', f"Public key file not found: {public_key_path}")
                        print(f"❌ Public key file not found: {public_key_path}")
                        raise
                    except ValueError as ve:
                        self.log_operation('ERROR', f"Invalid public key format: {str(ve)}")
                        print(f"❌ Invalid public key format in {public_key_path}")
                        raise
                    except Exception as upload_error:
                        self.log_operation('ERROR', f"Error importing public key: {str(upload_error)}")
                        print(f"❌ Error importing public key: {str(upload_error)}")
                        raise
                else:
                    self.log_operation('ERROR', f"Error checking key pair: {str(e)}")
                    raise

            # Check if private key file exists locally (for verification)
            private_key_file = f"{key_name}.pem"
            if not os.path.exists(private_key_file):
                self.log_operation('WARNING', f"Private key file '{private_key_file}' not found locally.")
                print(f"⚠️ Warning: Private key file '{private_key_file}' not found locally.")
            else:
                print(f"🔑 Using local private key file: {private_key_file}")

            return key_name

    def create_ec2_instance(self, cred_info: CredentialInfo, instance_type: str = None) -> Dict:
        """Create EC2 instance with specified configuration, avoiding unsupported AZs"""
        try:
            # Import generate_random_suffix function
            suffix = self.generate_random_suffix()
        
            # Setup EC2 client
            region = cred_info.regions[0]
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=cred_info.access_key,
                aws_secret_access_key=cred_info.secret_key,
                region_name=region
            )

            # Create security group
            security_group_id = self.create_security_group(ec2_client, cred_info, suffix)
            key_name = self.ensure_key_pair(region,credential=cred_info)

            # Get AMI for region
            ami_mapping = self.ami_config.get('region_ami_mapping', {})
            ami_id = ami_mapping.get(region)
            if not ami_id:
                raise ValueError(f"No AMI found for region: {region}")

            # Select instance type
            if not instance_type:
                instance_type = self.select_instance_type(region)

            # Get supported subnets
            supported_subnets = self.get_supported_subnets(ec2_client, region)
            if not supported_subnets:
                raise ValueError("No supported subnets found in default VPC after filtering unsupported AZs")
            subnet_id = supported_subnets[0]['SubnetId']

            enhanced_userdata = self.prepare_userdata_with_aws_config(
                self.userdata_script,
                cred_info.access_key,
                cred_info.secret_key,
                region
            )

            # Create instance configuration
            instance_config = InstanceConfig(
                instance_type=instance_type,
                ami_id=ami_id,
                region=region,
                userdata_script=enhanced_userdata,
                key_name=key_name  # Use provided key name
            )

            # Create launch template
            template_id = self.create_launch_template(ec2_client, cred_info, instance_config, security_group_id)
            instance_config.launch_template_id = template_id

            print(f"\n🚀 Launching EC2 instance...")
            print(f"   📍 Region: {region}")
            print(f"   💻 Instance Type: {instance_type}")
            print(f"   📀 AMI ID: {ami_id}")
            print(f"   🌐 Subnet: {subnet_id}")

            # Launch instance in supported subnet
            response = ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                UserData=enhanced_userdata,
                SubnetId=subnet_id,
                SecurityGroupIds=[security_group_id],
                KeyName=key_name,  # Use provided key name
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': [
                            {'Key': 'Name', 'Value': f'EC2-{cred_info.account_name}-{region}-{suffix}'},
                            {'Key': 'CreatedBy', 'Value': 'EC2-ASG-Automation'},
                            {'Key': 'Account', 'Value': cred_info.account_name},
                            {'Key': 'Region', 'Value': region}
                        ]
                    }
                ]
            )

            instance_id = response['Instances'][0]['InstanceId']
            print(f"✅ EC2 instance launched: {instance_id}")

            # Save instance details
            self.save_instance_details(cred_info, instance_config, instance_id, template_id)

            return {
                'instance_id': instance_id,
                'instance_type': instance_type,
                'ami_id': ami_id,
                'region': region,
                'launch_template_id': template_id,
                'account_name': cred_info.account_name
            }

        except Exception as e:
            print(f"❌ Error creating EC2 instance: {e}")
            raise
    
    def save_instance_details(self, cred_info: CredentialInfo, instance_config: InstanceConfig, 
                            instance_id: str, template_id: str):
        """Save instance details to output folder"""
        try:
            # Create output directory
            output_dir = f"aws/ec2/{cred_info.account_name}"
            os.makedirs(output_dir, exist_ok=True)

            if cred_info.credential_type == 'root':
                cred_info.username = f"root-{cred_info.account_name}"

            
            # Prepare instance details
            details = {
                'timestamp': datetime.now().isoformat(),
                'account_info': {
                    'account_name': cred_info.account_name,
                    'account_id': cred_info.account_id,
                    'email': cred_info.email,
                    'credential_type': cred_info.credential_type,
                    'username': cred_info.username,
                },
                'instance_details': {
                    'instance_id': instance_id,
                    'instance_type': instance_config.instance_type,
                    'ami_id': instance_config.ami_id,
                    'region': instance_config.region,
                    'launch_template_id': template_id
                }
            }
            
            # Save to JSON file
            filename = f"{output_dir}/ec2_instance_{instance_id}_{cred_info.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(details, f, indent=2)
            
            print(f"📁 Instance details saved to: {filename}")
            
        except Exception as e:
            print(f"⚠️ Warning: Could not save instance details: {e}")

    def _get_unsupported_azs(self, region: str) -> Set[str]:
        """Load unsupported AZs from ec2-region-ami-mapping.json file"""
        try:
            # Adjust the path to your mapping file
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
            
            if not os.path.exists(mapping_file_path):
                self.log_operation('WARNING', f"Mapping file not found: {mapping_file_path}")
                return set()
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            # Get unsupported AZs for the specified region
            unsupported_azs = set()
            
            if 'eks_unsupported_azs' in mapping_data and region in mapping_data['eks_unsupported_azs']:
                unsupported_azs = set(mapping_data['eks_unsupported_azs'][region])
                self.log_operation('DEBUG', f"Loaded {len(unsupported_azs)} unsupported AZs for {region} from mapping file")
            else:
                self.log_operation('DEBUG', f"No unsupported AZs found for region {region} in mapping file")
            
            return unsupported_azs
            
        except Exception as e:
            self.log_operation('WARNING', f"Failed to load unsupported AZs from mapping file: {str(e)}")
    
    def select_existing_launch_template(self, cred_info: CredentialInfo) -> Optional[str]:
        """
        List available launch templates and prompt user to select one.
        Returns the selected Launch Template ID or None.
        """
        import boto3
        from datetime import datetime

        region = cred_info.regions[0]
        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=cred_info.access_key,
            aws_secret_access_key=cred_info.secret_key,
            region_name=region
        )

        try:
            response = ec2_client.describe_launch_templates()
            templates = response.get('LaunchTemplates', [])
            if not templates:
                print("No launch templates found in this region.")
                return None

            print("\nAvailable Launch Templates:")
            print("=" * 60)
                        # Sort templates by CreateTime descending (most recent first)
            templates = sorted(
                templates,
                key=lambda tpl: tpl.get('CreateTime', datetime.min),
                reverse=True
            )

            for idx, tpl in enumerate(templates, 1):
                created = tpl.get('CreateTime')
                if isinstance(created, datetime):
                    created_str = created.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    created_str = str(created)
                print(f"{idx:2}. {tpl['LaunchTemplateName']} | ID: {tpl['LaunchTemplateId']} | Created: {created_str}")

            while True:
                choice = input(f"Select a launch template (1-{len(templates)}) (or press Enter to create new): ").strip()
                if not choice:
                    return None
                if choice.isdigit() and 1 <= int(choice) <= len(templates):
                    return templates[int(choice) - 1]['LaunchTemplateId']
                print("❌ Invalid choice. Please enter a valid number or press Enter to cancel.")
        except Exception as e:
            print(f"❌ Error listing launch templates: {e}")
            return None

    def log_operation(self, level: str, message: str):
            """Basic logger for EC2InstanceManager"""
            print(f"[{level}] {message}")