#!/usr/bin/env python3
"""
Interactive EKS Cluster Manager
Author: varadharajaan
Date: 2025-06-01
Description: Interactive tool to create EKS clusters for multiple AWS accounts and users
"""

import json
import os
import sys
import boto3
import glob
from datetime import datetime
from typing import Dict, List, Tuple

# Import your existing logging module
try:
    from logger import setup_logger
    logger = setup_logger('eks_manager', 'cluster_management')
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('eks_manager')

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    WHITE = '\033[1;37m'
    NC = '\033[0m'  # No Color

class EKSClusterManager:
    """Main class for managing EKS clusters across multiple AWS accounts"""
    
    def __init__(self, config_file: str = None):
        """
        Initialize the EKS Cluster Manager
        
        Args:
            config_file (str): Path to the AWS accounts configuration file (optional)
        """
        self.config_file = config_file or self.find_latest_credentials_file()
        self.config_data = None
        self.selected_clusters = []
        self.kubectl_commands = []
        
        logger.info(f"Initializing EKS Cluster Manager with config: {self.config_file}")
        self.load_configuration()
    
    def find_latest_credentials_file(self) -> str:
        """Find the latest iam_users_credentials_timestamp file"""
        pattern = "iam_users_credentials_*.json"
        files = glob.glob(pattern)
        
        if not files:
            logger.error("No iam_users_credentials_*.json file found!")
            # Fallback to default config file
            return "aws-accounts-config.json"
        
        # Sort by timestamp in filename
        files.sort(reverse=True)
        latest_file = files[0]
        
        logger.info(f"Found {len(files)} credential files, using latest: {latest_file}")
        return latest_file
    
    def print_colored(self, color: str, message: str) -> None:
        """Print colored message to terminal"""
        print(f"{color}{message}{Colors.NC}")
    
    def load_configuration(self) -> None:
        """Load AWS accounts configuration from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                logger.error(f"Configuration file {self.config_file} not found!")
                raise FileNotFoundError(f"Configuration file {self.config_file} not found!")
            
            with open(self.config_file, 'r') as file:
                self.config_data = json.load(file)
            
            total_users = self.config_data.get('total_users', 0)
            if total_users == 0:
                # Try to count users from accounts
                total_users = sum(len(account['users']) for account in self.config_data.get('accounts', {}).values())
            
            logger.info(f"Successfully loaded configuration with {total_users} users")
            self.print_colored(Colors.GREEN, f"✅ Loaded configuration with {total_users} users from {self.config_file}")
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            raise
    
    def get_accounts(self) -> List[str]:
        """Get list of account keys"""
        return list(self.config_data['accounts'].keys())
    
    def get_account_info(self, account_key: str) -> Dict:
        """Get account information"""
        account = self.config_data['accounts'][account_key]
        return {
            'key': account_key,
            'id': account['account_id'],
            'email': account['account_email'],
            'users_count': len(account['users'])
        }
    
    def get_users_for_account(self, account_key: str) -> List[Dict]:
        """Get users for a specific account"""
        return self.config_data['accounts'][account_key]['users']
    
    def generate_cluster_name(self, username: str, region: str) -> str:
        """Generate EKS cluster name"""
        return f"eks-cluster-{username}-{region}"
    
    def generate_nodegroup_name(self, cluster_name: str) -> str:
        """Generate node group name"""
        return f"{cluster_name}-nodegroup"
    
    def show_menu(self, title: str, options: List[str]) -> None:
        """Display menu with options"""
        self.print_colored(Colors.BLUE, f"\n=== {title} ===")
        for i, option in enumerate(options, 1):
            print(f"{i}. {option}")
        print("0. Exit/Back")
        print("-" * 50)
    
    def get_user_input(self, prompt: str, max_option: int) -> int:
        """Get and validate user input"""
        while True:
            try:
                choice = int(input(f"{prompt} (0-{max_option}): "))
                if 0 <= choice <= max_option:
                    return choice
                else:
                    self.print_colored(Colors.RED, f"Invalid input. Please enter a number between 0 and {max_option}.")
            except ValueError:
                self.print_colored(Colors.RED, "Invalid input. Please enter a valid number.")
            except KeyboardInterrupt:
                print("\n")
                logger.info("User interrupted input")
                return 0
    
    def select_accounts_and_users(self) -> None:
        """Interactive selection of accounts and users"""
        accounts = self.get_accounts()
        
        while True:
            os.system('clear' if os.name == 'posix' else 'cls')
            self.print_colored(Colors.GREEN, "🚀 EKS Cluster Manager - Account Selection")
            logger.info("Starting account selection interface")
            
            # Show accounts
            account_options = []
            for account in accounts:
                info = self.get_account_info(account)
                account_options.append(f"{info['key']} (ID: {info['id']}, Users: {info['users_count']})")
            
            self.show_menu("Select AWS Account", account_options)
            account_choice = self.get_user_input("Choose account", len(account_options))
            
            if account_choice == 0:
                logger.info("User exited account selection")
                break
            
            selected_account = accounts[account_choice - 1]
            logger.info(f"User selected account: {selected_account}")
            self.select_users_for_account(selected_account)
    
    def select_users_for_account(self, account_key: str) -> None:
        """Select users for a specific account"""
        account_info = self.get_account_info(account_key)
        users = self.get_users_for_account(account_key)
        
        logger.info(f"Entering user selection for account: {account_key}")
        
        while True:
            os.system('clear' if os.name == 'posix' else 'cls')
            self.print_colored(Colors.GREEN, f"🚀 EKS Cluster Manager - User Selection")
            self.print_colored(Colors.BLUE, f"Account: {account_info['key']} (ID: {account_info['id']})")
            
            # Show users
            user_options = []
            for user in users:
                user_options.append(f"{user['username']} - {user['real_user']['full_name']} - {user['region']}")
            
            self.show_menu("Select User", user_options)
            user_choice = self.get_user_input("Choose user", len(user_options))
            
            if user_choice == 0:
                logger.info(f"User exited user selection for account: {account_key}")
                break
            
            selected_user = users[user_choice - 1]
            logger.log_user_action(selected_user['username'], "SELECTED", "SUCCESS", f"Selected for EKS cluster in {selected_user['region']}")
            
            # Get max scaling preference
            self.print_colored(Colors.YELLOW, "\nEnter maximum number of nodes for scaling:")
            max_nodes = self.get_user_input("Max nodes (2-10)", 10)
            if max_nodes < 2:
                max_nodes = 2
            
            # Add to selected clusters
            cluster_info = {
                'account_key': account_key,
                'account_id': account_info['id'],
                'user': selected_user,
                'max_nodes': max_nodes,
                'cluster_name': self.generate_cluster_name(selected_user['username'], selected_user['region'])
            }
            
            self.selected_clusters.append(cluster_info)
            
            logger.log_user_action(
                selected_user['username'], 
                "CLUSTER_QUEUED", 
                "SUCCESS", 
                f"Cluster {cluster_info['cluster_name']} queued for creation with max nodes: {max_nodes}"
            )
            self.print_colored(Colors.GREEN, f"✅ Added cluster for {selected_user['username']} in {selected_user['region']} (max nodes: {max_nodes})")
            
            input("\nPress Enter to continue...")
    
    def show_cluster_summary(self) -> bool:
        """Show summary of selected clusters and confirm creation"""
        if not self.selected_clusters:
            self.print_colored(Colors.YELLOW, "No clusters selected!")
            logger.warning("No clusters selected for creation")
            return False
        
        os.system('clear' if os.name == 'posix' else 'cls')
        self.print_colored(Colors.GREEN, "🚀 Cluster Creation Summary")
        self.print_colored(Colors.BLUE, f"Selected {len(self.selected_clusters)} clusters to create:")
        
        logger.info(f"Displaying summary for {len(self.selected_clusters)} selected clusters")
        
        print("\n" + "="*80)
        for i, cluster in enumerate(self.selected_clusters, 1):
            user = cluster['user']
            print(f"{i}. Cluster: {cluster['cluster_name']}")
            print(f"   Account: {cluster['account_key']} ({cluster['account_id']})")
            print(f"   User: {user['username']} ({user['real_user']['full_name']})")
            print(f"   Region: {user['region']}")
            print(f"   Max Nodes: {cluster['max_nodes']}")
            print("-" * 80)
        
        confirm = input("\nDo you want to proceed with cluster creation? (y/N): ").lower().strip()
        confirmed = confirm in ['y', 'yes']
        
        if confirmed:
            logger.info("User confirmed cluster creation")
        else:
            logger.info("User cancelled cluster creation")
            
        return confirmed
    
    def get_or_create_vpc_resources(self, ec2_client, region: str) -> Tuple[List[str], str]:
        """Get or create VPC resources (subnets, security group)"""
        try:
            logger.debug(f"Getting VPC resources for region: {region}")
            
            # Get default VPC
            vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
            
            if not vpcs['Vpcs']:
                logger.error(f"No default VPC found in {region}")
                raise Exception(f"No default VPC found in {region}")
            
            vpc_id = vpcs['Vpcs'][0]['VpcId']
            logger.debug(f"Using VPC {vpc_id} in region {region}")
            
            # Get subnets
            subnets = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'state', 'Values': ['available']}
                ]
            )
            
            subnet_ids = [subnet['SubnetId'] for subnet in subnets['Subnets'][:2]]  # Take first 2 subnets
            
            if len(subnet_ids) < 2:
                logger.error(f"Need at least 2 subnets, found {len(subnet_ids)} in {region}")
                raise Exception(f"Need at least 2 subnets, found {len(subnet_ids)} in {region}")
            
            logger.debug(f"Found {len(subnet_ids)} subnets: {subnet_ids}")
            
            # Get or create security group
            try:
                security_groups = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': ['eks-cluster-sg']},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                
                if security_groups['SecurityGroups']:
                    sg_id = security_groups['SecurityGroups'][0]['GroupId']
                    logger.debug(f"Using existing security group: {sg_id}")
                else:
                    # Create security group
                    sg_response = ec2_client.create_security_group(
                        GroupName='eks-cluster-sg',
                        Description='Security group for EKS cluster',
                        VpcId=vpc_id
                    )
                    sg_id = sg_response['GroupId']
                    logger.info(f"Created security group {sg_id}")
                    
            except Exception as e:
                logger.warning(f"Using default security group due to: {str(e)}")
                default_sg = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': ['default']},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                sg_id = default_sg['SecurityGroups'][0]['GroupId']
            
            return subnet_ids, sg_id
            
        except Exception as e:
            logger.error(f"Failed to get VPC resources in {region}: {str(e)}")
            raise
    
    def ensure_iam_roles(self, iam_client, account_id: str) -> Tuple[str, str]:
        """Ensure required IAM roles exist"""
        eks_role_name = "eks-service-role"
        node_role_name = "NodeInstanceRole"
        
        eks_role_arn = f"arn:aws:iam::{account_id}:role/{eks_role_name}"
        node_role_arn = f"arn:aws:iam::{account_id}:role/{node_role_name}"
        
        logger.debug(f"Checking IAM roles for account {account_id}")
        
        # Check if roles exist, create if they don't
        try:
            iam_client.get_role(RoleName=eks_role_name)
            logger.debug(f"EKS service role {eks_role_name} already exists")
        except iam_client.exceptions.NoSuchEntityException:
            logger.info(f"Creating EKS service role {eks_role_name}")
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "eks.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            iam_client.create_role(
                RoleName=eks_role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="IAM role for EKS service"
            )
            
            # Attach required policies
            policies = ["arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"]
            for policy in policies:
                iam_client.attach_role_policy(RoleName=eks_role_name, PolicyArn=policy)
        
        try:
            iam_client.get_role(RoleName=node_role_name)
            logger.debug(f"Node instance role {node_role_name} already exists")
        except iam_client.exceptions.NoSuchEntityException:
            logger.info(f"Creating node instance role {node_role_name}")
            node_trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ec2.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            iam_client.create_role(
                RoleName=node_role_name,
                AssumeRolePolicyDocument=json.dumps(node_trust_policy),
                Description="IAM role for EKS worker nodes"
            )
            
            # Attach required policies for worker nodes
            node_policies = [
                "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
                "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
            ]
            
            for policy in node_policies:
                iam_client.attach_role_policy(RoleName=node_role_name, PolicyArn=policy)
        
        return eks_role_arn, node_role_arn
    
    def create_single_cluster(self, cluster_info: Dict) -> bool:
        """Create a single EKS cluster"""
        user = cluster_info['user']
        cluster_name = cluster_info['cluster_name']
        region = user['region']
        account_id = cluster_info['account_id']
        max_nodes = cluster_info['max_nodes']
        username = user['username']
        
        try:
            logger.log_user_action(username, "CLUSTER_CREATE_START", "IN_PROGRESS", f"Starting cluster creation: {cluster_name}")
            self.print_colored(Colors.YELLOW, f"🔄 Creating cluster: {cluster_name} in {region}")
            
            # Create AWS clients
            session = boto3.Session(
                aws_access_key_id=user['access_key_id'],
                aws_secret_access_key=user['secret_access_key'],
                region_name=region
            )
            
            eks_client = session.client('eks')
            ec2_client = session.client('ec2')
            iam_client = session.client('iam')
            
            logger.log_user_action(username, "AWS_SESSION_CREATE", "SUCCESS", f"AWS session created for region {region}")
            
            # Ensure IAM roles exist
            logger.debug(f"Ensuring IAM roles exist for {username}")
            eks_role_arn, node_role_arn = self.ensure_iam_roles(iam_client, account_id)
            logger.log_user_action(username, "IAM_ROLES_CHECK", "SUCCESS", "IAM roles verified/created")
            
            # Get VPC resources
            logger.debug(f"Getting VPC resources for {username} in {region}")
            subnet_ids, security_group_id = self.get_or_create_vpc_resources(ec2_client, region)
            logger.log_user_action(username, "VPC_RESOURCES_CHECK", "SUCCESS", f"VPC resources verified in {region}")
            
            # Step 1: Create EKS cluster (without node group)
            logger.info(f"Creating EKS cluster {cluster_name} for user {username}")
            cluster_config = {
                'name': cluster_name,
                'version': '1.27',
                'roleArn': eks_role_arn,
                'resourcesVpcConfig': {
                    'subnetIds': subnet_ids,
                    'securityGroupIds': [security_group_id]
                }
            }
            
            eks_client.create_cluster(**cluster_config)
            logger.log_user_action(username, "EKS_CLUSTER_CREATE", "SUCCESS", f"Cluster {cluster_name} creation initiated")
            
            # Wait for cluster to be active
            logger.info(f"Waiting for cluster {cluster_name} to be active...")
            self.print_colored(Colors.YELLOW, f"⏳ Waiting for cluster {cluster_name} to be active...")
            waiter = eks_client.get_waiter('cluster_active')
            waiter.wait(name=cluster_name, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})
            
            logger.log_user_action(username, "EKS_CLUSTER_ACTIVE", "SUCCESS", f"Cluster {cluster_name} is now active")
            
            # Step 2: Create node group
            logger.info(f"Creating node group for cluster {cluster_name}")
            nodegroup_name = self.generate_nodegroup_name(cluster_name)
            
            nodegroup_config = {
                'clusterName': cluster_name,
                'nodegroupName': nodegroup_name,
                'scalingConfig': {
                    'minSize': 1,
                    'maxSize': max_nodes,
                    'desiredSize': 1
                },
                'instanceTypes': ['m5.large'],
                'amiType': 'AL2_x86_64',
                'nodeRole': node_role_arn,
                'subnets': subnet_ids
            }
            
            eks_client.create_nodegroup(**nodegroup_config)
            logger.log_user_action(username, "NODEGROUP_CREATE", "SUCCESS", f"Node group {nodegroup_name} creation initiated")
            
            # Wait for node group to be active
            logger.info(f"Waiting for node group {nodegroup_name} to be active...")
            self.print_colored(Colors.YELLOW, f"⏳ Waiting for node group {nodegroup_name} to be active...")
            ng_waiter = eks_client.get_waiter('nodegroup_active')
            ng_waiter.wait(
                clusterName=cluster_name,
                nodegroupName=nodegroup_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )
            
            logger.log_user_action(username, "NODEGROUP_ACTIVE", "SUCCESS", f"Node group {nodegroup_name} is now active")
            
            # Generate kubectl command
            kubectl_cmd = f"aws eks update-kubeconfig --region {region} --name {cluster_name}"
            self.kubectl_commands.append({
                'cluster_name': cluster_name,
                'region': region,
                'command': kubectl_cmd,
                'user': username,
                'account': cluster_info['account_key'],
                'max_nodes': max_nodes
            })
            
            logger.log_user_action(username, "CLUSTER_CREATE_COMPLETE", "SUCCESS", f"Cluster {cluster_name} fully created and configured")
            self.print_colored(Colors.GREEN, f"✅ Successfully created cluster: {cluster_name}")
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.log_user_action(username, "CLUSTER_CREATE_FAILED", "ERROR", f"Cluster {cluster_name} creation failed: {error_msg}")
            self.print_colored(Colors.RED, f"❌ Failed to create cluster {cluster_name}: {error_msg}")
            return False
    
    def create_clusters(self) -> None:
        """Create all selected clusters"""
        if not self.selected_clusters:
            self.print_colored(Colors.YELLOW, "No clusters to create!")
            logger.warning("No clusters to create")
            return
        
        logger.info(f"Starting creation of {len(self.selected_clusters)} clusters")
        self.print_colored(Colors.GREEN, f"🚀 Starting creation of {len(self.selected_clusters)} clusters...")
        
        # Create clusters sequentially for now (can be made parallel if needed)
        successful_clusters = []
        failed_clusters = []
        
        for i, cluster_info in enumerate(self.selected_clusters, 1):
            self.print_colored(Colors.BLUE, f"\n📋 Progress: {i}/{len(self.selected_clusters)}")
            
            if self.create_single_cluster(cluster_info):
                successful_clusters.append(cluster_info)
            else:
                failed_clusters.append(cluster_info)
        
        # Summary
        logger.log_summary(
            total_processed=len(self.selected_clusters),
            successful=len(successful_clusters),
            failed=len(failed_clusters)
        )
        
        self.print_colored(Colors.GREEN, f"\n🎉 Cluster Creation Summary:")
        self.print_colored(Colors.GREEN, f"✅ Successful: {len(successful_clusters)}")
        if failed_clusters:
            self.print_colored(Colors.RED, f"❌ Failed: {len(failed_clusters)}")
        
        # Generate final commands
        self.generate_final_commands()
    
    def generate_final_commands(self) -> None:
        """Generate final kubectl commands and save to file"""
        if not self.kubectl_commands:
            logger.warning("No kubectl commands to generate")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        commands_file = f"kubectl_commands_{timestamp}.txt"
        
        logger.info(f"Generating kubectl commands file: {commands_file}")
        self.print_colored(Colors.GREEN, f"\n📝 Generated kubectl commands:")
        
        with open(commands_file, 'w') as f:
            f.write(f"# EKS Cluster kubectl Commands\n")
            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"# Total clusters: {len(self.kubectl_commands)}\n\n")
            
            for i, cmd_info in enumerate(self.kubectl_commands, 1):
                command_block = f"""
# Cluster {i}: {cmd_info['cluster_name']}
# Account: {cmd_info['account']}
# User: {cmd_info['user']}
# Region: {cmd_info['region']}
# Max Nodes: {cmd_info['max_nodes']}

# Update kubeconfig
{cmd_info['command']}

# Test cluster access
kubectl get nodes
kubectl get pods --all-namespaces

# Optional: Set context name for easier management
kubectl config rename-context arn:aws:eks:{cmd_info['region']}:*:cluster/{cmd_info['cluster_name']} {cmd_info['cluster_name']}

# Scale the node group (example)
aws eks update-nodegroup-config --cluster-name {cmd_info['cluster_name']} --nodegroup-name {cmd_info['cluster_name']}-nodegroup --scaling-config minSize=1,maxSize={cmd_info['max_nodes']},desiredSize=2 --region {cmd_info['region']}

{'-'*80}
"""
                f.write(command_block)
                print(f"{i}. {cmd_info['command']}")
        
        logger.log_credentials_saved(commands_file, len(self.kubectl_commands))
        self.print_colored(Colors.CYAN, f"\n💾 All commands saved to: {commands_file}")
        
        # Show example usage
        self.print_colored(Colors.YELLOW, f"\n🚀 To access your clusters, run:")
        print(f"1. Ensure AWS CLI is configured with appropriate credentials")
        print(f"2. Run the update-kubeconfig commands from {commands_file}")
        print(f"3. Test with: kubectl get nodes")
        print(f"4. Scale node groups as needed using the provided commands")
    
    def run(self) -> None:
        """Main execution flow"""
        try:
            self.print_colored(Colors.GREEN, "🚀 Welcome to Interactive EKS Cluster Manager")
            self.print_colored(Colors.BLUE, f"Loaded configuration for {len(self.get_accounts())} accounts")
            
            logger.info("Starting EKS Cluster Manager")
            logger.log_account_action("SYSTEM", "MANAGER_START", "SUCCESS", f"Loaded {len(self.get_accounts())} accounts from {self.config_file}")
            
            # Interactive selection
            self.select_accounts_and_users()
            
            # Show summary and confirm
            if self.show_cluster_summary():
                # Create clusters
                self.create_clusters()
            else:
                self.print_colored(Colors.YELLOW, "Cluster creation cancelled.")
                logger.info("Cluster creation cancelled by user")
            
        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n\nOperation cancelled by user.")
            logger.info("Operation cancelled by user")
        except Exception as e:
            error_msg = str(e)
            self.print_colored(Colors.RED, f"Error: {error_msg}")
            logger.error(f"Unexpected error: {error_msg}")
            sys.exit(1)

def main():
    """Main entry point"""
    try:
        # Run the EKS manager
        manager = EKSClusterManager()
        manager.run()
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()