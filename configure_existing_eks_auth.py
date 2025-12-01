#!/usr/bin/env python3
"""
Fix EKS Cluster Authentication - Dynamic Version
Apply aws-auth ConfigMap using admin credentials
Loads cluster info from eks_clusters_created_*.json
Loads admin creds from aws_accounts_config.json  
Loads user creds from iam_users_credentials_*.json
Author: varadharajaan
Date: 2025-06-02 02:53:14 UTC
"""

import json
import os
import boto3
import yaml
import subprocess
import glob
import re
from datetime import datetime

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

def print_colored(color: str, message: str) -> None:
    """Print colored message to terminal"""
    print(f"{color}{message}{Colors.NC}")

def find_latest_file(pattern: str) -> str:
    """Find the latest file matching pattern with timestamp"""
    files = glob.glob(pattern)
    
    if not files:
        return None
    
    print_colored(Colors.BLUE, f"[SCAN] Found {len(files)} files matching {pattern}:")
    
    # Sort by timestamp in filename
    file_timestamps = []
    for file_path in files:
        # Match pattern with timestamp
        match = re.search(r'(\d{8}_\d{6})\.json', file_path)
        if match:
            timestamp_str = match.group(1)
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                file_timestamps.append((file_path, timestamp, timestamp_str))
                
                # Display file info
                file_size = os.path.getsize(file_path)
                file_size_kb = file_size / 1024
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                print(f"   [FILE] {file_path} - {formatted_time} UTC ({file_size_kb:.1f} KB)")
                
            except ValueError:
                print(f"   [WARN]  Invalid timestamp format in: {file_path}")
                continue
        else:
            print(f"   [WARN]  No timestamp found in: {file_path}")
    
    if not file_timestamps:
        print_colored(Colors.RED, f"[ERROR] No valid files found with proper timestamp format!")
        return None
    
    # Sort by timestamp (newest first)
    file_timestamps.sort(key=lambda x: x[1], reverse=True)
    latest_file = file_timestamps[0][0]
    latest_datetime = file_timestamps[0][1]
    
    print_colored(Colors.GREEN, f"[OK] Selected latest file: {latest_file}")
    print(f"   [DATE] File timestamp: {latest_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   [NEW] This is the most recent file available")
    
    return latest_file

def load_cluster_data():
    """Load cluster data from eks_clusters_created_*.json"""
    print_colored(Colors.YELLOW, "[LIST] Loading cluster data...")
    
    clusters_file = find_latest_file("eks_clusters_created_*.json")
    if not clusters_file:
        print_colored(Colors.RED, "[ERROR] No eks_clusters_created_*.json file found!")
        return None
    
    try:
        with open(clusters_file, 'r') as f:
            cluster_data = json.load(f)
        
        clusters = cluster_data.get('clusters', [])
        metadata = cluster_data.get('metadata', {})
        
        print_colored(Colors.GREEN, f"[OK] Loaded {len(clusters)} clusters from {clusters_file}")
        print(f"   [DATE] Created on: {metadata.get('created_on', 'Unknown')}")
        print(f"   👤 Created by: {metadata.get('created_by', 'Unknown')}")
        
        return cluster_data
        
    except Exception as e:
        print_colored(Colors.RED, f"[ERROR] Failed to load cluster data: {str(e)}")
        return None

def load_admin_credentials():
    """Load admin credentials from aws_accounts_config.json"""
    print_colored(Colors.YELLOW, "[KEY] Loading admin credentials...")
    
    admin_config_file = "aws_accounts_config.json"
    if not os.path.exists(admin_config_file):
        print_colored(Colors.RED, f"[ERROR] Admin config file {admin_config_file} not found!")
        return None
    
    try:
        with open(admin_config_file, 'r') as f:
            admin_config = json.load(f)
        
        accounts = admin_config.get('accounts', {})
        print_colored(Colors.GREEN, f"[OK] Loaded admin credentials for {len(accounts)} accounts")
        
        return admin_config
        
    except Exception as e:
        print_colored(Colors.RED, f"[ERROR] Failed to load admin credentials: {str(e)}")
        return None

def load_user_credentials():
    """Load user credentials from iam_users_credentials_*.json"""
    print_colored(Colors.YELLOW, "👥 Loading user credentials...")
    
    user_creds_file = find_latest_file("iam_users_credentials_*.json")
    if not user_creds_file:
        print_colored(Colors.RED, "[ERROR] No iam_users_credentials_*.json file found!")
        return None
    
    try:
        with open(user_creds_file, 'r') as f:
            user_creds = json.load(f)
        
        total_users = user_creds.get('total_users', 0)
        print_colored(Colors.GREEN, f"[OK] Loaded user credentials for {total_users} users from {user_creds_file}")
        
        return user_creds
        
    except Exception as e:
        print_colored(Colors.RED, f"[ERROR] Failed to load user credentials: {str(e)}")
        return None

def display_clusters_menu(cluster_data):
    """Display available clusters and return selection"""
    clusters = cluster_data.get('clusters', [])
    
    if not clusters:
        print_colored(Colors.YELLOW, "No clusters found in the data file!")
        return None
    
    print_colored(Colors.BLUE, f"\n🏗️  Available EKS Clusters ({len(clusters)} total):")
    print("=" * 80)
    
    for i, cluster in enumerate(clusters, 1):
        auth_status = "[OK]" if cluster.get('auth_configured', False) else "[ERROR]"
        verify_status = "[OK]" if cluster.get('access_verified', False) else "[ERROR]"
        
        print(f"  {i:2}. {cluster['cluster_name']}")
        print(f"      [BANK] Account: {cluster['account_key']} ({cluster['account_id']})")
        print(f"      👤 User: {cluster['username']}")
        print(f"      [REGION] Region: {cluster['region']}")
        print(f"      [COMPUTE] Instance: {cluster['instance_type']}")
        print(f"      [STATS] Nodes: {cluster['default_nodes']} (max: {cluster['max_nodes']})")
        print(f"      [LOCKED] Auth Configured: {auth_status}")
        print(f"      [TEST] Access Verified: {verify_status}")
        print()
    
    print("=" * 80)
    print(f"[LOG] Selection Options:")
    print(f"   • Single cluster: 1-{len(clusters)}")
    print(f"   • All clusters: 'all' or press Enter")
    print(f"   • Cancel: 'cancel' or 'quit'")
    
    while True:
        selection = input(f"\n🔢 Select cluster to fix (1-{len(clusters)}): ").strip()
        
        if not selection or selection.lower() == 'all':
            return clusters
        
        if selection.lower() in ['cancel', 'quit', 'exit']:
            return None
        
        try:
            cluster_num = int(selection)
            if 1 <= cluster_num <= len(clusters):
                return [clusters[cluster_num - 1]]
            else:
                print(f"[ERROR] Please enter a number between 1 and {len(clusters)}")
        except ValueError:
            print("[ERROR] Please enter a valid number")

def get_user_credentials(user_creds, username, account_key):
    """Get user credentials for specific username and account"""
    accounts = user_creds.get('accounts', {})
    
    if account_key not in accounts:
        print_colored(Colors.RED, f"[ERROR] Account {account_key} not found in user credentials")
        return None
    
    account_data = accounts[account_key]
    users = account_data.get('users', [])
    
    for user in users:
        if user.get('username') == username:
            return user
    
    print_colored(Colors.RED, f"[ERROR] User {username} not found in account {account_key}")
    return None

def fix_cluster_auth(cluster, admin_config, user_creds):
    """Fix authentication for a specific cluster"""
    cluster_name = cluster['cluster_name']
    region = cluster['region']
    account_key = cluster['account_key']
    username = cluster['username']
    account_id = cluster['account_id']
    
    print_colored(Colors.YELLOW, f"\n[LOCKED] Fixing authentication for cluster: {cluster_name}")
    print(f"👤 User: {username}")
    print(f"[REGION] Region: {region}")
    print(f"[BANK] Account: {account_key} ({account_id})")
    
    # Get admin credentials
    if account_key not in admin_config.get('accounts', {}):
        print_colored(Colors.RED, f"[ERROR] Admin credentials not found for account: {account_key}")
        return False
    
    admin_creds = admin_config['accounts'][account_key]
    admin_access_key = admin_creds.get('access_key')
    admin_secret_key = admin_creds.get('secret_key')
    
    if not admin_access_key or not admin_secret_key:
        print_colored(Colors.RED, f"[ERROR] Invalid admin credentials for account: {account_key}")
        return False
    
    print_colored(Colors.GREEN, f"[OK] Retrieved admin credentials for {account_key}")
    
    # Get user credentials
    user_data = get_user_credentials(user_creds, username, account_key)
    if not user_data:
        return False
    
    user_access_key = user_data.get('access_key_id')
    user_secret_key = user_data.get('secret_access_key')
    
    if not user_access_key or not user_secret_key:
        print_colored(Colors.RED, f"[ERROR] Invalid user credentials for {username}")
        return False
    
    print_colored(Colors.GREEN, f"[OK] Retrieved user credentials for {username}")
    
    # Create aws-auth ConfigMap
    user_arn = f"arn:aws:iam::{account_id}:user/{username}"
    
    aws_auth_config = {
        'apiVersion': 'v1',
        'kind': 'ConfigMap',
        'metadata': {
            'name': 'aws-auth',
            'namespace': 'kube-system'
        },
        'data': {
            'mapRoles': yaml.dump([
                {
                    'rolearn': f"arn:aws:iam::{account_id}:role/NodeInstanceRole",
                    'username': 'system:node:{{EC2PrivateDNSName}}',
                    'groups': ['system:bootstrappers', 'system:nodes']
                }
            ], default_flow_style=False),
            'mapUsers': yaml.dump([
                {
                    'userarn': user_arn,
                    'username': username,
                    'groups': ['system:masters']
                }
            ], default_flow_style=False)
        }
    }
    
    # Save ConfigMap file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    configmap_file = f"aws-auth-fix-{cluster_name}-{timestamp}.yaml"
    
    try:
        with open(configmap_file, 'w') as f:
            yaml.dump(aws_auth_config, f)
        
        print_colored(Colors.GREEN, f"[OK] Created ConfigMap file: {configmap_file}")
        
        # Apply using admin credentials
        print_colored(Colors.YELLOW, "[START] Applying ConfigMap with admin credentials...")
        
        # Set admin environment
        env = os.environ.copy()
        env['AWS_ACCESS_KEY_ID'] = admin_access_key
        env['AWS_SECRET_ACCESS_KEY'] = admin_secret_key
        env['AWS_DEFAULT_REGION'] = region
        
        # Update kubeconfig with admin credentials
        update_cmd = [
            'aws', 'eks', 'update-kubeconfig',
            '--region', region,
            '--name', cluster_name
        ]
        
        result = subprocess.run(update_cmd, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print_colored(Colors.GREEN, "[OK] Updated kubeconfig with admin credentials")
        else:
            print_colored(Colors.RED, f"[ERROR] Failed to update kubeconfig: {result.stderr}")
            return False
        
        # Apply the ConfigMap
        apply_cmd = ['kubectl', 'apply', '-f', configmap_file]
        result = subprocess.run(apply_cmd, env=env, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            print_colored(Colors.GREEN, "[OK] Successfully applied aws-auth ConfigMap!")
            print("[LIST] ConfigMap output:")
            print(result.stdout)
            
            # Verify the ConfigMap
            verify_cmd = ['kubectl', 'get', 'configmap', 'aws-auth', '-n', 'kube-system', '-o', 'yaml']
            verify_result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True, timeout=120)
            
            if verify_result.returncode == 0:
                print_colored(Colors.CYAN, "\n[STATS] ConfigMap verification successful")
                # Print just the relevant parts, not the full yaml
                lines = verify_result.stdout.split('\n')
                for line in lines:
                    if 'mapRoles:' in line or 'mapUsers:' in line or username in line:
                        print(f"   {line.strip()}")
            
            # Test user access
            success = test_user_access(cluster_name, region, username, user_access_key, user_secret_key)
            return success
            
        else:
            print_colored(Colors.RED, f"[ERROR] Failed to apply ConfigMap: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print_colored(Colors.RED, "[ERROR] Command timed out")
        return False
    except Exception as e:
        print_colored(Colors.RED, f"[ERROR] Error: {str(e)}")
        return False
    
    finally:
        # Clean up
        try:
            if os.path.exists(configmap_file):
                os.remove(configmap_file)
                print_colored(Colors.CYAN, f"[CLEANUP] Cleaned up {configmap_file}")
        except:
            pass

def test_user_access(cluster_name: str, region: str, username: str, user_access_key: str, user_secret_key: str):
    """Test user access after applying ConfigMap"""
    print_colored(Colors.YELLOW, "\n[TEST] Testing user access...")
    
    # Set user environment
    user_env = os.environ.copy()
    user_env['AWS_ACCESS_KEY_ID'] = user_access_key
    user_env['AWS_SECRET_ACCESS_KEY'] = user_secret_key
    user_env['AWS_DEFAULT_REGION'] = region
    
    try:
        # Update kubeconfig with user credentials
        update_cmd = [
            'aws', 'eks', 'update-kubeconfig',
            '--region', region,
            '--name', cluster_name
        ]
        
        result = subprocess.run(update_cmd, env=user_env, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print_colored(Colors.GREEN, "[OK] Updated kubeconfig with user credentials")
        else:
            print_colored(Colors.RED, f"[ERROR] Failed to update kubeconfig with user creds: {result.stderr}")
            return False
        
        # Test kubectl get nodes
        print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl get nodes'...")
        nodes_cmd = ['kubectl', 'get', 'nodes', '--no-headers']
        nodes_result = subprocess.run(nodes_cmd, env=user_env, capture_output=True, text=True, timeout=60)
        
        if nodes_result.returncode == 0:
            node_lines = [line.strip() for line in nodes_result.stdout.strip().split('\n') if line.strip()]
            node_count = len(node_lines)
            
            print_colored(Colors.GREEN, f"   [OK] Found {node_count} node(s)")
            for i, node_line in enumerate(node_lines, 1):
                node_parts = node_line.split()
                if len(node_parts) >= 2:
                    node_name = node_parts[0]
                    node_status = node_parts[1]
                    print_colored(Colors.CYAN, f"      {i}. {node_name} ({node_status})")
        else:
            print_colored(Colors.RED, f"   [ERROR] kubectl get nodes failed: {nodes_result.stderr}")
            return False
        
        # Test kubectl get pods
        print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl get pods --all-namespaces'...")
        pods_cmd = ['kubectl', 'get', 'pods', '--all-namespaces', '--no-headers']
        pods_result = subprocess.run(pods_cmd, env=user_env, capture_output=True, text=True, timeout=60)
        
        if pods_result.returncode == 0:
            pod_lines = [line.strip() for line in pods_result.stdout.strip().split('\n') if line.strip()]
            pod_count = len(pod_lines)
            
            print_colored(Colors.GREEN, f"   [OK] Found {pod_count} pod(s) across all namespaces")
            
            # Count pods by namespace
            namespace_counts = {}
            for pod_line in pod_lines:
                parts = pod_line.split()
                if len(parts) >= 1:
                    namespace = parts[0]
                    namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
            
            for namespace, count in namespace_counts.items():
                print_colored(Colors.CYAN, f"      {namespace}: {count} pod(s)")
        else:
            print_colored(Colors.RED, f"   [ERROR] kubectl get pods failed: {pods_result.stderr}")
            return False
        
        # Test cluster-info
        print_colored(Colors.CYAN, "   [SCAN] Testing 'kubectl cluster-info'...")
        info_cmd = ['kubectl', 'cluster-info']
        info_result = subprocess.run(info_cmd, env=user_env, capture_output=True, text=True, timeout=60)
        
        if info_result.returncode == 0:
            print_colored(Colors.GREEN, f"   [OK] Cluster info retrieved successfully")
        else:
            print_colored(Colors.YELLOW, f"   [WARN]  kubectl cluster-info failed (non-critical)")
        
        print_colored(Colors.GREEN, f"[PARTY] User access verification successful for {username}!")
        return True
            
    except subprocess.TimeoutExpired:
        print_colored(Colors.RED, "[ERROR] User access test timed out")
        return False
    except Exception as e:
        print_colored(Colors.RED, f"[ERROR] Error testing user access: {str(e)}")
        return False

def main():
    """Main execution flow"""
    print_colored(Colors.GREEN, "[CONFIG] EKS Cluster Authentication Fix Tool - Dynamic Version")
    print("=" * 70)
    from datetime import datetime
    print(f"Current Date and Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"👤 Current User: varadharajaan")
    print("=" * 70)
    
    # Load all required data
    cluster_data = load_cluster_data()
    if not cluster_data:
        return
    
    admin_config = load_admin_credentials()
    if not admin_config:
        return
    
    user_creds = load_user_credentials()
    if not user_creds:
        return
    
    # Display clusters and get selection
    selected_clusters = display_clusters_menu(cluster_data)
    if not selected_clusters:
        print_colored(Colors.YELLOW, "No clusters selected or operation cancelled")
        return
    
    print_colored(Colors.BLUE, f"\n[START] Processing {len(selected_clusters)} cluster(s)...")
    
    # Process each selected cluster
    successful_fixes = 0
    failed_fixes = 0
    
    for i, cluster in enumerate(selected_clusters, 1):
        print_colored(Colors.BLUE, f"\n[LIST] Progress: {i}/{len(selected_clusters)}")
        print("=" * 50)
        
        success = fix_cluster_auth(cluster, admin_config, user_creds)
        
        if success:
            successful_fixes += 1
            print_colored(Colors.GREEN, f"[OK] Successfully fixed authentication for {cluster['cluster_name']}")
        else:
            failed_fixes += 1
            print_colored(Colors.RED, f"[ERROR] Failed to fix authentication for {cluster['cluster_name']}")
    
    # Summary
    print("\n" + "=" * 70)
    print_colored(Colors.GREEN, f"[PARTY] Authentication Fix Summary:")
    print_colored(Colors.GREEN, f"[OK] Successful: {successful_fixes}")
    if failed_fixes > 0:
        print_colored(Colors.RED, f"[ERROR] Failed: {failed_fixes}")
    
    print(f"[STATS] Total processed: {len(selected_clusters)}")
    print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_colored(Colors.YELLOW, "\n\nOperation cancelled by user.")
    except Exception as e:
        print_colored(Colors.RED, f"\nError: {str(e)}")