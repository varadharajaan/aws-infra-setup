#!/usr/bin/env python3
"""
EKS Cluster Deletion Manager with Parallel Threading
Author: varadharajaan
Date: 2025-06-02
Description: Interactive tool to delete EKS clusters using admin credentials across multiple regions with parallel processing
"""

import sys
import os

# Fix Windows terminal encoding for Unicode characters
def setup_unicode_support():
    """Setup Unicode support for Windows terminals"""
    if sys.platform.startswith('win'):
        try:
            # Method 1: Reconfigure stdout/stderr
            import codecs
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except (AttributeError, UnicodeError):
            try:
                # Method 2: Use codecs wrapper
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
            except:
                # Method 3: Set environment variable
                os.environ['PYTHONIOENCODING'] = 'utf-8'
                print("Warning: Using fallback encoding method")

# Call this before any Unicode print statements
setup_unicode_support()

import json
import time
import boto3
import glob
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import your existing logging module
try:
    from logger import setup_logger
    logger = setup_logger('eks_delete_manager', 'cluster_deletion')
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('eks_delete_manager')

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

class ThreadSafePrinter:
    """Thread-safe printer for parallel operations"""
    def __init__(self):
        self._lock = threading.Lock()
    
    def print_colored(self, color: str, message: str, thread_id: str = None):
        """Thread-safe colored print"""
        with self._lock:
            prefix = f"[Thread-{thread_id}] " if thread_id else ""
            print(f"{color}{prefix}{message}{Colors.NC}")
    
    def print_normal(self, message: str, thread_id: str = None):
        """Thread-safe normal print"""
        with self._lock:
            prefix = f"[Thread-{thread_id}] " if thread_id else ""
            print(f"{prefix}{message}")

class EKSClusterDeleteManager:
    """Main class for deleting EKS clusters across multiple AWS accounts and regions with parallel processing"""
    
    def __init__(self, admin_config_file: str = "aws_accounts_config.json"):
        """
        Initialize the EKS Cluster Delete Manager
        
        Args:
            admin_config_file (str): Path to the admin AWS accounts configuration file
        """
        self.admin_config_file = admin_config_file
        self.admin_config_data = None
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Define the 5 regions to scan
        self.scan_regions = self.get_regions_from_config()
        
        self.discovered_clusters = {}  # account -> region -> clusters
        self.deletion_summary = []
        
        # Thread safety
        self.printer = ThreadSafePrinter()
        self.deletion_lock = threading.Lock()
        self.summary_lock = threading.Lock()
        
        # Parallel execution settings
        self.max_parallel_deletions = 3  # Maximum parallel cluster deletions
        
        logger.info(f"Initializing EKS Cluster Delete Manager with parallel processing")
        self.load_admin_configuration()
        self.setup_detailed_logging()
    
    def load_admin_configuration(self) -> None:
        """Load admin AWS accounts configuration from JSON file"""
        try:
            if not os.path.exists(self.admin_config_file):
                logger.error(f"Admin configuration file {self.admin_config_file} not found!")
                raise FileNotFoundError(f"Admin configuration file {self.admin_config_file} not found!")
            
            with open(self.admin_config_file, 'r') as file:
                self.admin_config_data = json.load(file)
            
            total_admin_accounts = len(self.admin_config_data.get('accounts', {}))
            logger.info(f"Successfully loaded admin configuration with {total_admin_accounts} admin accounts")
            self.printer.print_colored(Colors.GREEN, f"✅ Loaded admin configuration with {total_admin_accounts} admin accounts from {self.admin_config_file}")
        
        except Exception as e:
            logger.error(f"Failed to load admin configuration: {str(e)}")
            raise
    
    def setup_detailed_logging(self):
        """Setup detailed logging to file with thread safety"""
        try:
            self.log_filename = f"eks_deletion_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('eks_delete_operations')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler with thread-safe formatter
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler (reduced verbosity)
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)  # Only show warnings and errors on console
            
            # Thread-safe formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(thread)d | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)
            
            # Log initial information
            self.operation_logger.info("=" * 80)
            self.operation_logger.info("EKS Cluster Deletion Session Started (Parallel Processing)")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Admin Config File: {self.admin_config_file}")
            self.operation_logger.info(f"Scan Regions: {', '.join(self.scan_regions)}")
            self.operation_logger.info(f"Max Parallel Deletions: {self.max_parallel_deletions}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 80)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message, thread_id: str = None):
        """Thread-safe log operation"""
        thread_info = f"[T-{thread_id}] " if thread_id else ""
        full_message = f"{thread_info}{message}"
        
        if self.operation_logger:
            if level.upper() == 'INFO':
                self.operation_logger.info(full_message)
            elif level.upper() == 'WARNING':
                self.operation_logger.warning(full_message)
            elif level.upper() == 'ERROR':
                self.operation_logger.error(full_message)
            elif level.upper() == 'DEBUG':
                self.operation_logger.debug(full_message)
        else:
            # Only print errors and warnings to console
            if level.upper() in ['ERROR', 'WARNING']:
                self.printer.print_normal(f"[{level.upper()}] {full_message}")
    
    def print_colored(self, color: str, message: str) -> None:
        """Print colored message to terminal"""
        self.printer.print_colored(color, message)
    
    def get_admin_credentials_for_account(self, account_key: str) -> Tuple[str, str]:
        """Get admin credentials for a specific account"""
        if account_key not in self.admin_config_data['accounts']:
            raise ValueError(f"Admin credentials not found for account: {account_key}")
        
        admin_account = self.admin_config_data['accounts'][account_key]
        access_key = admin_account.get('access_key')
        secret_key = admin_account.get('secret_key')
        
        if not access_key or not secret_key:
            raise ValueError(f"Invalid admin credentials for account: {account_key}")
        
        return access_key, secret_key
    
    def scan_eks_clusters_in_region(self, account_key: str, region: str) -> List[Dict]:
        """Scan EKS clusters in a specific account and region"""
        try:
            thread_id = threading.current_thread().ident
            self.log_operation('INFO', f"Scanning EKS clusters in {account_key} - {region}", str(thread_id))
            
            # Get admin credentials
            admin_access_key, admin_secret_key = self.get_admin_credentials_for_account(account_key)
            
            # Create AWS session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            eks_client = admin_session.client('eks')
            
            # List all clusters
            clusters_response = eks_client.list_clusters()
            cluster_names = clusters_response.get('clusters', [])
            
            clusters_info = []
            
            if cluster_names:
                self.log_operation('INFO', f"Found {len(cluster_names)} clusters in {account_key} - {region}", str(thread_id))
                
                for cluster_name in cluster_names:
                    try:
                        # Get cluster details
                        cluster_details = eks_client.describe_cluster(name=cluster_name)
                        cluster_info = cluster_details['cluster']
                        
                        # Get nodegroups
                        nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
                        nodegroups = nodegroups_response.get('nodegroups', [])
                        
                        # Get nodegroup details
                        nodegroup_details = []
                        total_nodes = 0
                        
                        for ng_name in nodegroups:
                            try:
                                ng_details = eks_client.describe_nodegroup(
                                    clusterName=cluster_name,
                                    nodegroupName=ng_name
                                )
                                ng_info = ng_details['nodegroup']
                                
                                # Calculate node count
                                scaling_config = ng_info.get('scalingConfig', {})
                                desired_size = scaling_config.get('desiredSize', 0)
                                total_nodes += desired_size
                                
                                nodegroup_details.append({
                                    'name': ng_name,
                                    'status': ng_info.get('status', 'UNKNOWN'),
                                    'instance_types': ng_info.get('instanceTypes', []),
                                    'desired_size': desired_size,
                                    'min_size': scaling_config.get('minSize', 0),
                                    'max_size': scaling_config.get('maxSize', 0),
                                    'created_at': ng_info.get('createdAt', 'Unknown')
                                })
                                
                            except Exception as e:
                                self.log_operation('WARNING', f"Failed to get nodegroup {ng_name} details: {str(e)}", str(thread_id))
                                nodegroup_details.append({
                                    'name': ng_name,
                                    'status': 'ERROR',
                                    'error': str(e)
                                })
                        
                        cluster_data = {
                            'name': cluster_name,
                            'status': cluster_info.get('status', 'UNKNOWN'),
                            'version': cluster_info.get('version', 'Unknown'),
                            'created_at': cluster_info.get('createdAt', 'Unknown'),
                            'endpoint': cluster_info.get('endpoint', 'Unknown'),
                            'nodegroups': nodegroup_details,
                            'nodegroup_count': len(nodegroups),
                            'total_nodes': total_nodes,
                            'account_key': account_key,
                            'region': region
                        }
                        
                        clusters_info.append(cluster_data)
                        self.log_operation('INFO', f"Cluster {cluster_name}: {len(nodegroups)} nodegroups, {total_nodes} total nodes", str(thread_id))
                        
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to get details for cluster {cluster_name}: {str(e)}", str(thread_id))
                        clusters_info.append({
                            'name': cluster_name,
                            'status': 'ERROR',
                            'error': str(e),
                            'account_key': account_key,
                            'region': region
                        })
            else:
                self.log_operation('INFO', f"No clusters found in {account_key} - {region}", str(thread_id))
            
            return clusters_info
            
        except Exception as e:
            thread_id = threading.current_thread().ident
            self.log_operation('ERROR', f"Failed to scan clusters in {account_key} - {region}: {str(e)}", str(thread_id))
            return []
    
    def scan_all_accounts_and_regions(self, selected_accounts: List[str]) -> None:
        """Scan all selected accounts across all regions using parallel processing"""
        self.print_colored(Colors.BLUE, f"\n🔍 Scanning {len(selected_accounts)} accounts across {len(self.scan_regions)} regions using parallel processing...")
        
        total_scans = len(selected_accounts) * len(self.scan_regions)
        completed_scans = 0
        scan_lock = threading.Lock()
        
        def update_progress():
            nonlocal completed_scans
            with scan_lock:
                completed_scans += 1
                return completed_scans
        
        # Prepare scan tasks
        scan_tasks = []
        for account_key in selected_accounts:
            for region in self.scan_regions:
                scan_tasks.append((account_key, region))
        
        # Initialize cluster storage
        for account_key in selected_accounts:
            self.discovered_clusters[account_key] = {}
            for region in self.scan_regions:
                self.discovered_clusters[account_key][region] = []
        
        # Execute scans in parallel
        max_scan_workers = min(10, len(scan_tasks))  # Limit concurrent scans
        
        with ThreadPoolExecutor(max_workers=max_scan_workers, thread_name_prefix="ScanWorker") as executor:
            # Submit all scan tasks
            future_to_task = {
                executor.submit(self.scan_eks_clusters_in_region, account_key, region): (account_key, region)
                for account_key, region in scan_tasks
            }
            
            # Process completed scans
            for future in as_completed(future_to_task):
                account_key, region = future_to_task[future]
                current_scan = update_progress()
                
                try:
                    clusters = future.result()
                    self.discovered_clusters[account_key][region] = clusters
                    
                    status_msg = f"✅ Found {len(clusters)} cluster(s)" if clusters else "🔍 No clusters found"
                    self.printer.print_normal(f"[{current_scan:2}/{total_scans}] {account_key} - {region}: {status_msg}")
                    
                    if clusters:
                        for cluster in clusters:
                            if 'error' not in cluster:
                                self.printer.print_normal(f"      📋 {cluster['name']} ({cluster['status']}) - {cluster['nodegroup_count']} nodegroups, {cluster['total_nodes']} nodes")
                            else:
                                self.printer.print_normal(f"      ❌ {cluster['name']} (ERROR)")
                                
                except Exception as e:
                    self.discovered_clusters[account_key][region] = []
                    self.printer.print_colored(Colors.RED, f"[{current_scan:2}/{total_scans}] {account_key} - {region}: ❌ Error: {str(e)}")
        
        self.print_colored(Colors.GREEN, f"✅ Completed scanning {total_scans} account-region combinations")
    
    def display_discovered_clusters(self) -> bool:
        """Display all discovered clusters and return True if any exist"""
        total_clusters = 0
        total_nodegroups = 0
        total_nodes = 0
        
        # Count totals
        for account_key, regions in self.discovered_clusters.items():
            for region, clusters in regions.items():
                total_clusters += len(clusters)
                for cluster in clusters:
                    if 'error' not in cluster:
                        total_nodegroups += cluster.get('nodegroup_count', 0)
                        total_nodes += cluster.get('total_nodes', 0)
        
        if total_clusters == 0:
            self.print_colored(Colors.YELLOW, "\n🎉 No EKS clusters found in any of the scanned accounts and regions!")
            return False
        
        print(f"\n📊 EKS Cluster Discovery Summary")
        print("=" * 100)
        print(f"🎯 Total Clusters Found: {total_clusters}")
        print(f"📦 Total Nodegroups: {total_nodegroups}")
        print(f"💻 Total Nodes: {total_nodes}")
        print("=" * 100)
        
        cluster_index = 1
        cluster_mapping = {}
        
        for account_key, regions in self.discovered_clusters.items():
            account_data = self.admin_config_data['accounts'][account_key]
            account_id = account_data.get('account_id', 'Unknown')
            
            account_has_clusters = any(len(clusters) > 0 for clusters in regions.values())
            
            if account_has_clusters:
                print(f"\n🏦 Account: {account_key} ({account_id})")
                print("-" * 80)
                
                for region, clusters in regions.items():
                    if clusters:
                        print(f"\n   🌍 Region: {region}")
                        
                        for cluster in clusters:
                            if 'error' not in cluster:
                                created_time = cluster.get('created_at', 'Unknown')
                                if isinstance(created_time, datetime):
                                    created_str = created_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                                else:
                                    created_str = str(created_time)
                                
                                print(f"      {cluster_index:3}. {cluster['name']}")
                                print(f"           📊 Status: {cluster['status']}")
                                print(f"           🔢 Version: {cluster['version']}")
                                print(f"           📅 Created: {created_str}")
                                print(f"           📦 Nodegroups: {cluster['nodegroup_count']}")
                                print(f"           💻 Total Nodes: {cluster['total_nodes']}")
                                
                                # Show nodegroup details
                                if cluster.get('nodegroups'):
                                    print(f"           🔧 Nodegroup Details:")
                                    for ng in cluster['nodegroups']:
                                        if 'error' not in ng:
                                            print(f"              • {ng['name']} ({ng['status']}) - {ng['desired_size']} nodes ({', '.join(ng['instance_types'])})")
                                        else:
                                            print(f"              • {ng['name']} (ERROR)")
                                
                                cluster_mapping[cluster_index] = {
                                    'account_key': account_key,
                                    'region': region,
                                    'cluster': cluster
                                }
                                cluster_index += 1
                            else:
                                print(f"      ❌ {cluster['name']} - ERROR: {cluster.get('error', 'Unknown error')}")
                            print()
        
        self.cluster_mapping = cluster_mapping
        return True
    
    def select_clusters_to_delete(self) -> List[Dict]:
        """Allow user to select which clusters to delete"""
        if not hasattr(self, 'cluster_mapping') or not self.cluster_mapping:
            return []
        
        total_clusters = len(self.cluster_mapping)
        
        print(f"\n🗑️  Cluster Deletion Selection")
        print("=" * 60)
        print(f"📝 Selection Options:")
        print(f"   • Single clusters: 1,3,5")
        print(f"   • Ranges: 1-{total_clusters}")
        print(f"   • Mixed: 1-3,5,7-9")
        print(f"   • All clusters: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select clusters to DELETE (1-{total_clusters}): ").strip()
            
            self.log_operation('INFO', f"User input for cluster deletion selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all clusters for deletion")
                return list(self.cluster_mapping.values())
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled cluster deletion selection")
                return []
            
            try:
                selected_indices = self.parse_selection(selection, total_clusters)
                if selected_indices:
                    selected_clusters = [self.cluster_mapping[idx] for idx in selected_indices]
                    
                    # Show confirmation
                    print(f"\n⚠️  DELETION CONFIRMATION")
                    print("🚨 The following clusters will be PERMANENTLY DELETED:")
                    print("-" * 60)
                    
                    for i, cluster_info in enumerate(selected_clusters, 1):
                        cluster = cluster_info['cluster']
                        print(f"   {i}. {cluster['name']} ({cluster_info['account_key']} - {cluster_info['region']})")
                        print(f"      📦 {cluster['nodegroup_count']} nodegroups, {cluster['total_nodes']} nodes")
                    
                    print("-" * 60)
                    print(f"🔥 Total: {len(selected_clusters)} clusters will be deleted")
                    print(f"🚀 Parallel Processing: Up to {self.max_parallel_deletions} clusters will be deleted simultaneously")
                    print("⚠️  This action CANNOT be undone!")
                    
                    confirm1 = input(f"\n❓ Are you sure you want to delete these {len(selected_clusters)} clusters? (yes/no): ").lower().strip()
                    
                    if confirm1 == 'yes':
                        confirm2 = input(f"❓ Type 'DELETE' to confirm permanent deletion: ").strip()
                        if confirm2 == 'DELETE':
                            self.log_operation('INFO', f"User confirmed deletion of {len(selected_clusters)} clusters")
                            return selected_clusters
                        else:
                            print("❌ Deletion cancelled - incorrect confirmation")
                    else:
                        print("❌ Deletion cancelled")
                    continue
                else:
                    print("❌ No valid clusters selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                continue
    
    def parse_selection(self, selection, max_items):
        """Parse selection string and return list of indices"""
        selected_indices = set()
        
        # Split by comma and process each part
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_items:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_items})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                # Handle single number
                try:
                    num = int(part)
                    if num < 1 or num > max_items:
                        raise ValueError(f"Cluster number {num} is out of bounds (1-{max_items})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid cluster number: {part}")
        
        return sorted(list(selected_indices))
    
    def delete_cluster_nodegroups(self, cluster_info: Dict, thread_id: str) -> bool:
        """Delete all nodegroups in a cluster"""
        try:
            account_key = cluster_info['account_key']
            region = cluster_info['region']
            cluster = cluster_info['cluster']
            cluster_name = cluster['name']
            
            self.log_operation('INFO', f"Deleting nodegroups for cluster {cluster_name} in {account_key} - {region}", thread_id)
            
            # Get admin credentials
            admin_access_key, admin_secret_key = self.get_admin_credentials_for_account(account_key)
            
            # Create AWS session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            eks_client = admin_session.client('eks')
            
            # Get current nodegroups
            nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
            nodegroups = nodegroups_response.get('nodegroups', [])
            
            if not nodegroups:
                self.log_operation('INFO', f"No nodegroups found in cluster {cluster_name}", thread_id)
                return True
            
            self.log_operation('INFO', f"Found {len(nodegroups)} nodegroups to delete in {cluster_name}", thread_id)
            
            # Delete all nodegroups
            for nodegroup_name in nodegroups:
                try:
                    self.log_operation('INFO', f"Deleting nodegroup {nodegroup_name} from cluster {cluster_name}", thread_id)
                    
                    eks_client.delete_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup_name
                    )
                    
                    self.log_operation('INFO', f"Nodegroup {nodegroup_name} deletion initiated", thread_id)
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to delete nodegroup {nodegroup_name}: {str(e)}", thread_id)
                    return False
            
            # Wait for all nodegroups to be deleted
            self.log_operation('INFO', f"Waiting for {len(nodegroups)} nodegroups to be deleted...", thread_id)
            
            for nodegroup_name in nodegroups:
                try:
                    # Wait for nodegroup deletion
                    waiter = eks_client.get_waiter('nodegroup_deleted')
                    waiter.wait(
                        clusterName=cluster_name,
                        nodegroupName=nodegroup_name,
                        WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                    )
                    
                    self.log_operation('INFO', f"Nodegroup {nodegroup_name} successfully deleted", thread_id)
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Failed to wait for nodegroup {nodegroup_name} deletion: {str(e)}", thread_id)
                    return False
            
            self.log_operation('INFO', f"All nodegroups deleted successfully from cluster {cluster_name}", thread_id)
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete nodegroups: {str(e)}", thread_id)
            return False
        
    def delete_cluster_scrappers(self, cluster_info: Dict, thread_id: str) -> bool:
        """Delete all scrappers associated with a cluster"""
        try:
            account_key = cluster_info['account_key']
            region = cluster_info['region']
            cluster = cluster_info['cluster']
            cluster_name = cluster['name']
            
            self.log_operation('INFO', f"Deleting scrappers for cluster {cluster_name} in {account_key} - {region}", thread_id)
            
            # Get admin credentials
            admin_access_key, admin_secret_key = self.get_admin_credentials_for_account(account_key)
            
            # Create AWS session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            # Delete scrappers from different AWS services
            deleted_scrappers = []
            
            # 1. Delete CloudWatch Scrappers
            try:
                cloudwatch_client = admin_session.client('cloudwatch')
                
                # List and delete custom metrics/alarms related to the cluster
                paginator = cloudwatch_client.get_paginator('list_metrics')
                for page in paginator.paginate():
                    for metric in page['Metrics']:
                        if cluster_name in str(metric.get('Dimensions', [])):
                            try:
                                # Delete related alarms
                                alarms_response = cloudwatch_client.describe_alarms_for_metric(
                                    MetricName=metric['MetricName'],
                                    Namespace=metric['Namespace'],
                                    Dimensions=metric.get('Dimensions', [])
                                )
                                
                                for alarm in alarms_response.get('MetricAlarms', []):
                                    cloudwatch_client.delete_alarms(AlarmNames=[alarm['AlarmName']])
                                    deleted_scrappers.append(f"CloudWatch Alarm: {alarm['AlarmName']}")
                                    self.log_operation('INFO', f"Deleted CloudWatch alarm: {alarm['AlarmName']}", thread_id)
                            except Exception as e:
                                self.log_operation('WARNING', f"Failed to delete CloudWatch alarm: {str(e)}", thread_id)
                                
            except Exception as e:
                self.log_operation('WARNING', f"Failed to process CloudWatch scrappers: {str(e)}", thread_id)
            
            # 2. Delete Prometheus/Grafana related resources
            try:
                # Look for AMP (Amazon Managed Prometheus) workspaces
                amp_client = admin_session.client('amp')
                
                workspaces_response = amp_client.list_workspaces()
                for workspace in workspaces_response.get('workspaces', []):
                    workspace_id = workspace['workspaceId']
                    workspace_alias = workspace.get('alias', '')
                    
                    # Check if workspace is related to our cluster
                    if cluster_name in workspace_alias or cluster_name in workspace.get('tags', {}).values():
                        try:
                            # List and delete scrape configurations
                            scrape_configs = amp_client.list_scrapers(
                                filters={'name': f'*{cluster_name}*'}
                            )
                            
                            for scraper in scrape_configs.get('scrapers', []):
                                amp_client.delete_scraper(scraperId=scraper['scraperId'])
                                deleted_scrappers.append(f"AMP Scraper: {scraper['scraperId']}")
                                self.log_operation('INFO', f"Deleted AMP scraper: {scraper['scraperId']}", thread_id)
                                
                        except Exception as e:
                            self.log_operation('WARNING', f"Failed to delete AMP scrapers: {str(e)}", thread_id)
                            
            except Exception as e:
                self.log_operation('WARNING', f"Failed to process AMP scrappers: {str(e)}", thread_id)
            
            # 3. Delete EKS-specific monitoring resources
            try:
                eks_client = admin_session.client('eks')
                
                # Check for EKS add-ons that might include monitoring
                addons_response = eks_client.list_addons(clusterName=cluster_name)
                monitoring_addons = ['aws-for-fluent-bit', 'adot', 'amazon-cloudwatch-observability']
                
                for addon_name in addons_response.get('addons', []):
                    if any(monitoring in addon_name.lower() for monitoring in monitoring_addons):
                        try:
                            eks_client.delete_addon(
                                clusterName=cluster_name,
                                addonName=addon_name
                            )
                            deleted_scrappers.append(f"EKS Addon: {addon_name}")
                            self.log_operation('INFO', f"Deleted EKS monitoring addon: {addon_name}", thread_id)
                        except Exception as e:
                            self.log_operation('WARNING', f"Failed to delete EKS addon {addon_name}: {str(e)}", thread_id)
                            
            except Exception as e:
                self.log_operation('WARNING', f"Failed to process EKS monitoring addons: {str(e)}", thread_id)
            
            # 4. Delete EC2-based scrappers (instances with scrapper tags)
            try:
                ec2_client = admin_session.client('ec2')
                
                # Find EC2 instances tagged as scrappers for this cluster
                response = ec2_client.describe_instances(
                    Filters=[
                        {'Name': 'tag:Purpose', 'Values': ['scrapper', 'monitoring', 'prometheus', 'grafana']},
                        {'Name': 'tag:Cluster', 'Values': [cluster_name]},
                        {'Name': 'instance-state-name', 'Values': ['running', 'stopped']}
                    ]
                )
                
                instance_ids = []
                for reservation in response['Reservations']:
                    for instance in reservation['Instances']:
                        instance_ids.append(instance['InstanceId'])
                
                if instance_ids:
                    ec2_client.terminate_instances(InstanceIds=instance_ids)
                    deleted_scrappers.extend([f"EC2 Scrapper Instance: {iid}" for iid in instance_ids])
                    self.log_operation('INFO', f"Terminated {len(instance_ids)} scrapper EC2 instances", thread_id)
                    
            except Exception as e:
                self.log_operation('WARNING', f"Failed to delete EC2 scrapper instances: {str(e)}", thread_id)
            
            if deleted_scrappers:
                self.log_operation('INFO', f"Successfully deleted {len(deleted_scrappers)} scrappers for cluster {cluster_name}", thread_id)
                for scrapper in deleted_scrappers:
                    self.log_operation('INFO', f"  - {scrapper}", thread_id)
            else:
                self.log_operation('INFO', f"No scrappers found for cluster {cluster_name}", thread_id)
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to delete scrappers: {str(e)}", thread_id)
            return False
    
    def delete_single_cluster(self, cluster_info: Dict, thread_id: str = None) -> bool:
        """Delete a single EKS cluster (scrappers first, then nodegroups, then cluster) - Thread-safe"""
        if thread_id is None:
            thread_id = str(threading.current_thread().ident)
        
        try:
            account_key = cluster_info['account_key']
            region = cluster_info['region']
            cluster = cluster_info['cluster']
            cluster_name = cluster['name']
            
            self.log_operation('INFO', f"Starting deletion of cluster {cluster_name} in {account_key} - {region}", thread_id)
            self.printer.print_colored(Colors.YELLOW, f"🗑️  Deleting cluster: {cluster_name} ({account_key} - {region})", thread_id)
            
            # Get admin credentials
            admin_access_key, admin_secret_key = self.get_admin_credentials_for_account(account_key)
            
            # Create AWS session
            admin_session = boto3.Session(
                aws_access_key_id=admin_access_key,
                aws_secret_access_key=admin_secret_key,
                region_name=region
            )
            
            eks_client = admin_session.client('eks')
            
            # Step 1: Delete all scrappers first
            self.printer.print_normal(f"   🔍 Step 1: Deleting scrappers...", thread_id)
            scrappers_deleted = self.delete_cluster_scrappers(cluster_info, thread_id)
            
            if not scrappers_deleted:
                self.log_operation('WARNING', f"Some scrappers may not have been deleted for cluster {cluster_name}", thread_id)
                self.printer.print_colored(Colors.YELLOW, f"   ⚠️  Some scrappers may still exist (check logs)", thread_id)
            else:
                self.printer.print_normal(f"   ✅ All scrappers processed successfully", thread_id)
            
            # Step 2: Delete all nodegroups
            self.printer.print_normal(f"   📦 Step 2: Deleting nodegroups...", thread_id)
            nodegroups_deleted = self.delete_cluster_nodegroups(cluster_info, thread_id)
            
            if not nodegroups_deleted:
                self.log_operation('ERROR', f"Failed to delete nodegroups for cluster {cluster_name}", thread_id)
                self.printer.print_colored(Colors.RED, f"   ❌ Failed to delete nodegroups", thread_id)
                return False
            
            self.printer.print_normal(f"   ✅ All nodegroups deleted successfully", thread_id)
            
            # Step 3: Delete the EKS cluster
            self.printer.print_normal(f"   🎯 Step 3: Deleting EKS cluster...", thread_id)
            self.log_operation('INFO', f"Deleting EKS cluster {cluster_name}", thread_id)
            
            eks_client.delete_cluster(name=cluster_name)
            self.log_operation('INFO', f"EKS cluster {cluster_name} deletion initiated", thread_id)
            
            # Step 4: Wait for cluster deletion
            self.printer.print_normal(f"   ⏳ Step 4: Waiting for cluster deletion to complete...", thread_id)
            self.log_operation('INFO', f"Waiting for cluster {cluster_name} to be deleted...", thread_id)
            
            waiter = eks_client.get_waiter('cluster_deleted')
            waiter.wait(
                name=cluster_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )
            
            self.log_operation('INFO', f"Cluster {cluster_name} successfully deleted", thread_id)
            self.printer.print_colored(Colors.GREEN, f"   ✅ Cluster {cluster_name} deleted successfully", thread_id)
            
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to delete cluster {cluster_name}: {error_msg}", thread_id)
            self.printer.print_colored(Colors.RED, f"   ❌ Failed to delete cluster {cluster_name}: {error_msg}", thread_id)
        return False
    
    def get_regions_from_config(self) -> List[str]:
        """Extract regions from user_settings.user_regions in the config"""
        if not self.admin_config_data:
            return ['us-east-1','us-east-2','us-west-1','us-west-2','ap-south-1']  # Fallback
        
        # Try to get regions from user_settings.user_regions
        user_settings = self.admin_config_data.get('user_settings', {})
        user_regions = user_settings.get('user_regions', [])
        
        if user_regions and isinstance(user_regions, list):
            region_list = sorted(user_regions)
            logger.info(f"Extracted regions from config user_settings: {region_list}")
            return region_list
        
        # Fallback: try to get from individual accounts
        regions = set()
        for account_key, account_data in self.admin_config_data.get('accounts', {}).items():
            account_regions = account_data.get('regions', [])
            if isinstance(account_regions, list):
                regions.update(account_regions)
            elif isinstance(account_regions, str):
                regions.add(account_regions)
        
        region_list = sorted(list(regions)) if regions else ['us-east-1','us-east-2','us-west-1','us-west-2','ap-south-1']
        logger.info(f"Extracted regions from accounts (fallback): {region_list}")
        
        return region_list
    
    def update_deletion_summary(self, deletion_record: Dict):
        """Thread-safe update of deletion summary"""
        with self.summary_lock:
            self.deletion_summary.append(deletion_record)
    
    def delete_selected_clusters(self, selected_clusters: List[Dict]) -> None:
        """Delete all selected clusters using parallel processing"""
        if not selected_clusters:
            self.print_colored(Colors.YELLOW, "No clusters selected for deletion!")
            return
        
        self.log_operation('INFO', f"Starting parallel deletion of {len(selected_clusters)} clusters")
        self.print_colored(Colors.RED, f"\n🚨 Starting parallel deletion of {len(selected_clusters)} clusters...")
        self.print_colored(Colors.CYAN, f"🚀 Maximum parallel deletions: {self.max_parallel_deletions}")
        
        successful_deletions = []
        failed_deletions = []
        completion_times = {}
        
        # Progress tracking
        completed_deletions = 0
        progress_lock = threading.Lock()
        
        def update_progress(cluster_name: str, success: bool, deletion_record: Dict):
            nonlocal completed_deletions
            with progress_lock:
                completed_deletions += 1
                if success:
                    successful_deletions.append(deletion_record)
                else:
                    failed_deletions.append(deletion_record)
                
                progress_msg = f"📊 Progress: {completed_deletions}/{len(selected_clusters)} completed"
                if successful_deletions:
                    progress_msg += f" (✅ {len(successful_deletions)} successful"
                if failed_deletions:
                    progress_msg += f", ❌ {len(failed_deletions)} failed"
                if successful_deletions or failed_deletions:
                    progress_msg += ")"
                
                self.printer.print_colored(Colors.BLUE, progress_msg)
                return completed_deletions
        
        def delete_cluster_worker(cluster_info: Dict) -> Dict:
            """Worker function for parallel cluster deletion"""
            thread_id = str(threading.current_thread().ident)
            cluster_name = cluster_info['cluster']['name']
            account_key = cluster_info['account_key']
            region = cluster_info['region']
            
            start_time = time.time()
            
            try:
                success = self.delete_single_cluster(cluster_info, thread_id)
                end_time = time.time()
                duration = end_time - start_time
                
                deletion_record = {
                    'cluster_name': cluster_name,
                    'account_key': account_key,
                    'region': region,
                    'status': 'SUCCESS' if success else 'FAILED',
                    'duration_seconds': round(duration, 2),
                    'thread_id': thread_id,
                    'start_time': datetime.fromtimestamp(start_time).strftime('%H:%M:%S'),
                    'end_time': datetime.fromtimestamp(end_time).strftime('%H:%M:%S')
                }
                
                if success:
                    deletion_record.update({
                        'nodegroups_deleted': len(cluster_info['cluster'].get('nodegroups', [])),
                        'nodes_removed': cluster_info['cluster'].get('total_nodes', 0)
                    })
                
                # Update summary thread-safely
                self.update_deletion_summary(deletion_record)
                
                # Update progress
                update_progress(cluster_name, success, deletion_record)
                
                return deletion_record
                
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                
                deletion_record = {
                    'cluster_name': cluster_name,
                    'account_key': account_key,
                    'region': region,
                    'status': 'FAILED',
                    'duration_seconds': round(duration, 2),
                    'thread_id': thread_id,
                    'error': str(e),
                    'start_time': datetime.fromtimestamp(start_time).strftime('%H:%M:%S'),
                    'end_time': datetime.fromtimestamp(end_time).strftime('%H:%M:%S')
                }
                
                self.update_deletion_summary(deletion_record)
                update_progress(cluster_name, False, deletion_record)
                
                return deletion_record
        
        # Execute parallel deletions
        self.print_colored(Colors.YELLOW, f"🚀 Starting parallel execution...")
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_parallel_deletions, thread_name_prefix="DeleteWorker") as executor:
            # Submit all deletion tasks
            future_to_cluster = {
                executor.submit(delete_cluster_worker, cluster_info): cluster_info
                for cluster_info in selected_clusters
            }
            
            # Process completed deletions
            for future in as_completed(future_to_cluster):
                cluster_info = future_to_cluster[future]
                cluster_name = cluster_info['cluster']['name']
                
                try:
                    deletion_record = future.result()
                    # Results already processed in worker function
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Unexpected error in deletion worker for {cluster_name}: {str(e)}")
        
        total_time = time.time() - start_time
        
        # Final summary
        self.log_operation('INFO', f"Parallel cluster deletion completed - Deleted: {len(successful_deletions)}, Failed: {len(failed_deletions)}, Total Time: {total_time:.2f}s")
        
        print("\n" + "=" * 80)
        self.print_colored(Colors.GREEN, f"🎉 Parallel Cluster Deletion Summary:")
        self.print_colored(Colors.GREEN, f"✅ Successfully Deleted: {len(successful_deletions)}")
        if failed_deletions:
            self.print_colored(Colors.RED, f"❌ Failed: {len(failed_deletions)}")
        
        self.print_colored(Colors.CYAN, f"⏱️  Total Execution Time: {total_time:.2f} seconds")
        self.print_colored(Colors.CYAN, f"🚀 Parallel Workers Used: {self.max_parallel_deletions}")
        
        if successful_deletions:
            avg_time = sum(r['duration_seconds'] for r in successful_deletions) / len(successful_deletions)
            self.print_colored(Colors.CYAN, f"📊 Average Deletion Time: {avg_time:.2f} seconds per cluster")
        
        print("=" * 80)
        
        # Generate deletion report
        self.generate_deletion_report()
    
    def generate_deletion_report(self) -> None:
        """Generate detailed deletion report file with parallel execution details"""
        if not self.deletion_summary:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"eks_deletion_report_parallel_{timestamp}.txt"
        
        self.print_colored(Colors.CYAN, f"\n💾 Deletion report saved to: {report_file}")
        
        with open(report_file, 'w') as f:
            f.write(f"# EKS Cluster Parallel Deletion Report\n")
            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"# Executed by: {self.current_user}\n")
            f.write(f"# Total clusters processed: {len(self.deletion_summary)}\n")
            f.write(f"# Max parallel workers: {self.max_parallel_deletions}\n\n")
            
            successful = [r for r in self.deletion_summary if r['status'] == 'SUCCESS']
            failed = [r for r in self.deletion_summary if r['status'] == 'FAILED']
            
            f.write(f"## Summary\n")
            f.write(f"✅ Successfully deleted: {len(successful)}\n")
            f.write(f"❌ Failed deletions: {len(failed)}\n")
            f.write(f"🚀 Parallel execution enabled: {self.max_parallel_deletions} max workers\n\n")
            
            if successful:
                f.write(f"## Successful Deletions\n")
                f.write(f"{'Cluster Name':<30} {'Account':<15} {'Region':<15} {'Duration':<10} {'Start':<10} {'End':<10} {'Thread':<12} {'Nodegroups':<12} {'Nodes':<8}\n")
                f.write(f"{'-'*120}\n")
                
                total_duration = 0
                total_nodegroups = 0
                total_nodes = 0
                
                for record in successful:
                    f.write(f"{record['cluster_name']:<30} {record['account_key']:<15} {record['region']:<15} "
                           f"{record['duration_seconds']:<10} {record.get('start_time', 'N/A'):<10} {record.get('end_time', 'N/A'):<10} "
                           f"{record.get('thread_id', 'N/A'):<12} {record.get('nodegroups_deleted', 0):<12} {record.get('nodes_removed', 0):<8}\n")
                    total_duration += record['duration_seconds']
                    total_nodegroups += record.get('nodegroups_deleted', 0)
                    total_nodes += record.get('nodes_removed', 0)
                
                f.write(f"{'-'*120}\n")
                f.write(f"{'TOTALS':<30} {'':<15} {'':<15} {total_duration:<10} {'':<10} {'':<10} {'':<12} {total_nodegroups:<12} {total_nodes:<8}\n")
                
                avg_duration = total_duration / len(successful)
                f.write(f"{'AVERAGE':<30} {'':<15} {'':<15} {avg_duration:<10.2f}\n\n")
            
            if failed:
                f.write(f"## Failed Deletions\n")
                f.write(f"{'Cluster Name':<30} {'Account':<15} {'Region':<15} {'Duration':<10} {'Thread':<12} {'Error':<50}\n")
                f.write(f"{'-'*130}\n")
                
                for record in failed:
                    error_msg = record.get('error', 'Unknown error')[:47] + '...' if len(record.get('error', '')) > 50 else record.get('error', 'Unknown error')
                    f.write(f"{record['cluster_name']:<30} {record['account_key']:<15} {record['region']:<15} "
                           f"{record['duration_seconds']:<10} {record.get('thread_id', 'N/A'):<12} {error_msg:<50}\n")
                f.write("\n")
            
            f.write(f"## Parallel Execution Statistics\n")
            f.write(f"Maximum parallel workers: {self.max_parallel_deletions}\n")
            f.write(f"Thread utilization: {len(set(r.get('thread_id', 'N/A') for r in self.deletion_summary if r.get('thread_id')))} unique threads used\n")
            
            if successful:
                execution_times = [r['duration_seconds'] for r in successful]
                f.write(f"Fastest deletion: {min(execution_times):.2f} seconds\n")
                f.write(f"Slowest deletion: {max(execution_times):.2f} seconds\n")
                f.write(f"Average deletion time: {sum(execution_times)/len(execution_times):.2f} seconds\n")
            
            f.write(f"\n## Detailed Log\n")
            f.write(f"For detailed operation logs, see: {self.log_filename}\n")
    
    def display_accounts_menu(self) -> List[str]:
        """Display available admin accounts and return selection"""
        accounts = list(self.admin_config_data['accounts'].keys())
        
        print(f"\n🏦 Available Admin Accounts ({len(accounts)} total):")
        print("=" * 60)
        
        for i, account_key in enumerate(accounts, 1):
            account_data = self.admin_config_data['accounts'][account_key]
            account_id = account_data.get('account_id', 'Unknown')
            email = account_data.get('email', 'Unknown')
            
            print(f"  {i:2}. {account_key}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      📧 Email: {email}")
            print()
        
        print("=" * 60)
        print(f"🌍 Scan Regions: {', '.join(self.scan_regions)}")
        print(f"📊 Total scan operations: {len(accounts)} accounts × {len(self.scan_regions)} regions = {len(accounts) * len(self.scan_regions)} scans")
        print(f"🚀 Parallel processing: Max {self.max_parallel_deletions} simultaneous deletions")
        
        print(f"\n📝 Selection Options:")
        print(f"   • Single accounts: 1,3,5")
        print(f"   • Ranges: 1-{len(accounts)}")
        print(f"   • All accounts: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select accounts to scan: ").strip()
            
            if not selection or selection.lower() == 'all':
                return accounts
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                return []
            
            try:
                selected_indices = self.parse_selection(selection, len(accounts))
                if selected_indices:
                    selected_accounts = [accounts[idx - 1] for idx in selected_indices]
                    
                    print(f"\n✅ Selected {len(selected_accounts)} accounts:")
                    for account_key in selected_accounts:
                        account_data = self.admin_config_data['accounts'][account_key]
                        print(f"   • {account_key} ({account_data.get('account_id', 'Unknown')})")
                    
                    total_scans = len(selected_accounts) * len(self.scan_regions)
                    print(f"\n📊 Total scan operations: {total_scans}")
                    
                    confirm = input(f"\n🚀 Proceed with scanning these {len(selected_accounts)} accounts? (y/N): ").lower().strip()
                    
                    if confirm == 'y':
                        return selected_accounts
                    else:
                        continue
                else:
                    print("❌ No valid accounts selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                continue
    
    def run(self) -> None:
        """Main execution flow with parallel processing"""
        try:
            self.print_colored(Colors.RED, "🗑️  Welcome to EKS Cluster Deletion Manager (Parallel Edition)")
            
            print("🗑️  EKS Cluster Deletion Tool (Parallel Processing)")
            print("=" * 80)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"🔑 Admin Config: {self.admin_config_file}")
            print(f"🌍 Scan Regions: {', '.join(self.scan_regions)}")
            print(f"🚀 Max Parallel Deletions: {self.max_parallel_deletions}")
            print(f"📋 Log File: {self.log_filename}")
            print("=" * 80)
            
            print("⚠️  WARNING: This tool will permanently delete EKS clusters!")
            print("🚨 Deleted clusters cannot be recovered!")
            print("🚀 Parallel processing will speed up deletions but use more resources!")
            
            # Step 1: Select accounts to scan
            selected_accounts = self.display_accounts_menu()
            if not selected_accounts:
                print("❌ Account selection cancelled")
                return
            
            # Step 2: Scan all accounts and regions (parallel)
            self.scan_all_accounts_and_regions(selected_accounts)
            
            # Step 3: Display discovered clusters
            clusters_found = self.display_discovered_clusters()
            if not clusters_found:
                return
            
            # Step 4: Select clusters to delete
            clusters_to_delete = self.select_clusters_to_delete()
            if not clusters_to_delete:
                self.print_colored(Colors.YELLOW, "No clusters selected for deletion.")
                return
            
            # Step 5: Delete selected clusters (parallel)
            self.delete_selected_clusters(clusters_to_delete)
            
        except KeyboardInterrupt:
            self.print_colored(Colors.YELLOW, "\n\nOperation cancelled by user.")
        except Exception as e:
            error_msg = str(e)
            self.print_colored(Colors.RED, f"Error: {error_msg}")
            sys.exit(1)

def main():
    """Main entry point"""
    try:
        # Run the EKS deletion manager with parallel processing
        manager = EKSClusterDeleteManager()
        manager.run()
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()