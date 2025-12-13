# Databricks notebook source
#!/usr/bin/env python3
"""
ELB (Elastic Load Balancer) Cleanup Tool for Multiple AWS Accounts
Author: varadharajaan
Date: 2025-06-05
Description: Delete all ELBs (Classic, ALB, NLB) across multiple AWS accounts using regions from config
"""

import sys
import os
import json
import time
import boto3
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Fix Windows terminal encoding for Unicode characters

# Fix Windows terminal encoding for Unicode characters
def setup_unicode_support_bk():
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

def setup_unicode_support():
    """Setup Unicode support for Windows terminals"""
    if sys.platform.startswith('win'):
        try:
            # Try to enable UTF-8 mode
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except (AttributeError, UnicodeError):
            try:
                import codecs
                # Use UTF-8 codec with error handling
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')
            except Exception:
                try:
                    # Last resort: use Windows console encoding
                    import locale
                    encoding = locale.getpreferredencoding()
                    sys.stdout = codecs.getwriter(encoding)(sys.stdout.buffer, 'replace')
                    sys.stderr = codecs.getwriter(encoding)(sys.stderr.buffer, 'replace')
                except Exception:
                    # Final fallback
                    os.environ['PYTHONIOENCODING'] = 'utf-8:replace'
                    print("Warning: Using fallback encoding method")
    else:
        # For non-Windows systems, ensure UTF-8
        try:
            if sys.stdout.encoding.lower() != 'utf-8':
                import codecs
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')
        except Exception:
            os.environ['PYTHONIOENCODING'] = 'utf-8:replace'

setup_unicode_support()

# Import logging module
try:
    from logger import setup_logger
    logger = setup_logger('elb_cleanup', 'elb_deletion')
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('elb_cleanup')

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

class ELBCleanupManager:
    """Main class for deleting ELBs across multiple AWS accounts and regions"""
    
    def __init__(self, config_file: str = "aws_accounts_config.json"):
        """
        Initialize the ELB Cleanup Manager
        
        Args:
            config_file (str): Path to the AWS accounts configuration file
        """
        self.config_file = config_file
        self.config_data = None
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.discovered_elbs = {}  # account -> region -> {classic: [], alb: [], nlb: []}
        self.deletion_summary = []
        
        # Thread safety
        self.printer = ThreadSafePrinter()
        self.deletion_lock = threading.Lock()
        self.summary_lock = threading.Lock()
        
        # Parallel execution settings
        self.max_parallel_deletions = 5  # Maximum parallel ELB deletions
        
        logger.info(f"Initializing ELB Cleanup Manager with parallel processing")
        self.load_configuration()
        
        # Get regions from config after loading configuration
        self.scan_regions = self.get_regions_from_config()
        
        self.setup_detailed_logging()
    
    def get_regions_from_config(self) -> List[str]:
        """Extract regions from user_settings.user_regions in the config"""
        if not self.config_data:
            return ['us-east-1','us-east-2','us-west-1','us-west-2','ap-south-1']  # Fallback
        
        # Try to get regions from user_settings.user_regions
        user_settings = self.config_data.get('user_settings', {})
        user_regions = user_settings.get('user_regions', [])
        
        if user_regions and isinstance(user_regions, list):
            region_list = sorted(user_regions)
            logger.info(f"Extracted regions from config user_settings: {region_list}")
            return region_list
        
        # Fallback: try to get from individual accounts
        regions = set()
        for account_key, account_data in self.config_data.get('accounts', {}).items():
            account_regions = account_data.get('regions', [])
            if isinstance(account_regions, list):
                regions.update(account_regions)
            elif isinstance(account_regions, str):
                regions.add(account_regions)
        
        region_list = sorted(list(regions)) if regions else ['us-east-1','us-east-2','us-west-1','us-west-2','ap-south-1']
        logger.info(f"Extracted regions from accounts (fallback): {region_list}")
        
        return region_list
    
    def load_configuration(self) -> None:
        """Load AWS accounts configuration from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                logger.error(f"Configuration file {self.config_file} not found!")
                raise FileNotFoundError(f"Configuration file {self.config_file} not found!")
            
            with open(self.config_file, 'r') as file:
                self.config_data = json.load(file)
            
            total_accounts = len(self.config_data.get('accounts', {}))
            logger.info(f"Successfully loaded configuration with {total_accounts} accounts")
            self.printer.print_colored(Colors.GREEN, f"✅ Loaded configuration with {total_accounts} accounts from {self.config_file}")
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            raise
    
    def setup_detailed_logging(self):
        """Setup detailed logging to file with thread safety"""
        try:
            self.log_filename = f"elb_cleanup_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('elb_cleanup_operations')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler with thread-safe formatter
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler (reduced verbosity)
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            
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
            self.operation_logger.info("ELB Cleanup Session Started (Parallel Processing)")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config File: {self.config_file}")
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
            if level.upper() in ['ERROR', 'WARNING']:
                self.printer.print_normal(f"[{level.upper()}] {full_message}")
    
    def get_credentials_for_account(self, account_key: str) -> Tuple[str, str]:
        """Get credentials for a specific account"""
        if account_key not in self.config_data['accounts']:
            raise ValueError(f"Credentials not found for account: {account_key}")
        
        account = self.config_data['accounts'][account_key]
        access_key = account.get('access_key')
        secret_key = account.get('secret_key')
        
        if not access_key or not secret_key:
            raise ValueError(f"Invalid credentials for account: {account_key}")
        
        return access_key, secret_key
    
    def scan_elbs_in_region(self, account_key: str, region: str) -> Dict:
        """Scan all types of ELBs in a specific account and region"""
        try:
            thread_id = threading.current_thread().ident
            self.log_operation('INFO', f"Scanning ELBs in {account_key} - {region}", str(thread_id))
            
            # Get credentials
            access_key, secret_key = self.get_credentials_for_account(account_key)
            
            # Create AWS session
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            elb_results = {
                'classic': [],
                'alb': [],
                'nlb': []
            }
            
            # 1. Scan Classic Load Balancers
            try:
                elb_client = session.client('elb')
                classic_response = elb_client.describe_load_balancers()
                
                for elb in classic_response.get('LoadBalancerDescriptions', []):
                    # Handle AvailabilityZones - can be list of strings or list of dicts
                    availability_zones = []
                    az_data = elb.get('AvailabilityZones', [])
                    
                    for az in az_data:
                        if isinstance(az, dict):
                            # New format: [{'AvailabilityZone': 'us-east-1a'}, ...]
                            availability_zones.append(az.get('AvailabilityZone', str(az)))
                        elif isinstance(az, str):
                            # Old format: ['us-east-1a', 'us-east-1b', ...]
                            availability_zones.append(az)
                        else:
                            availability_zones.append(str(az))
                    
                    elb_info = {
                        'name': elb['LoadBalancerName'],
                        'dns_name': elb['DNSName'],
                        'scheme': elb['Scheme'],
                        'vpc_id': elb.get('VPCId', 'EC2-Classic'),
                        'created_time': elb['CreatedTime'],
                        'instances': len(elb.get('Instances', [])),
                        'availability_zones': availability_zones,
                        'account_key': account_key,
                        'region': region
                    }
                    elb_results['classic'].append(elb_info)
                    
            except Exception as e:
                self.log_operation('WARNING', f"Failed to scan Classic ELBs: {str(e)}", str(thread_id))
            
            # 2. Scan Application and Network Load Balancers (ELBv2)
            try:
                elbv2_client = session.client('elbv2')
                v2_response = elbv2_client.describe_load_balancers()
                
                for elb in v2_response.get('LoadBalancers', []):
                    elb_type = elb['Type'].upper()
                    
                    # Get target groups
                    target_groups = []
                    try:
                        tg_response = elbv2_client.describe_target_groups(LoadBalancerArn=elb['LoadBalancerArn'])
                        target_groups = [tg['TargetGroupName'] for tg in tg_response.get('TargetGroups', [])]
                    except:
                        pass
                    
                    elb_info = {
                        'name': elb['LoadBalancerName'],
                        'arn': elb['LoadBalancerArn'],
                        'dns_name': elb['DNSName'],
                        'scheme': elb['Scheme'],
                        'vpc_id': elb['VpcId'],
                        'state': elb['State']['Code'],
                        'created_time': elb['CreatedTime'],
                        'availability_zones': [az['ZoneName'] for az in elb.get('AvailabilityZones', [])],
                        'target_groups': target_groups,
                        'target_group_count': len(target_groups),
                        'account_key': account_key,
                        'region': region
                    }
                    
                    if elb_type == 'APPLICATION':
                        elb_results['alb'].append(elb_info)
                    elif elb_type == 'NETWORK':
                        elb_results['nlb'].append(elb_info)
                        
            except Exception as e:
                self.log_operation('WARNING', f"Failed to scan ALB/NLB: {str(e)}", str(thread_id))
            
            total_elbs = len(elb_results['classic']) + len(elb_results['alb']) + len(elb_results['nlb'])
            self.log_operation('INFO', f"Found {total_elbs} ELBs in {account_key} - {region} (Classic: {len(elb_results['classic'])}, ALB: {len(elb_results['alb'])}, NLB: {len(elb_results['nlb'])})", str(thread_id))
            
            return elb_results
            
        except Exception as e:
            thread_id = threading.current_thread().ident
            self.log_operation('ERROR', f"Failed to scan ELBs in {account_key} - {region}: {str(e)}", str(thread_id))
            return {'classic': [], 'alb': [], 'nlb': []}
    
    def scan_all_accounts_and_regions(self, selected_accounts: List[str]) -> None:
        """Scan all selected accounts across all regions using parallel processing"""
        self.printer.print_colored(Colors.BLUE, f"\n🔍 Scanning {len(selected_accounts)} accounts across {len(self.scan_regions)} regions for ELBs...")
        
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
        
        # Initialize ELB storage
        for account_key in selected_accounts:
            self.discovered_elbs[account_key] = {}
            for region in self.scan_regions:
                self.discovered_elbs[account_key][region] = {'classic': [], 'alb': [], 'nlb': []}
        
        # Execute scans in parallel
        max_scan_workers = min(10, len(scan_tasks))
        
        with ThreadPoolExecutor(max_workers=max_scan_workers, thread_name_prefix="ScanWorker") as executor:
            future_to_task = {
                executor.submit(self.scan_elbs_in_region, account_key, region): (account_key, region)
                for account_key, region in scan_tasks
            }
            
            for future in as_completed(future_to_task):
                account_key, region = future_to_task[future]
                current_scan = update_progress()
                
                try:
                    elbs = future.result()
                    self.discovered_elbs[account_key][region] = elbs
                    
                    total_elbs = len(elbs['classic']) + len(elbs['alb']) + len(elbs['nlb'])
                    status_msg = f"✅ Found {total_elbs} ELB(s)" if total_elbs > 0 else "🔍 No ELBs found"
                    
                    if total_elbs > 0:
                        detail_msg = f" (Classic: {len(elbs['classic'])}, ALB: {len(elbs['alb'])}, NLB: {len(elbs['nlb'])})"
                        status_msg += detail_msg
                    
                    self.printer.print_normal(f"[{current_scan:2}/{total_scans}] {account_key} - {region}: {status_msg}")
                    
                except Exception as e:
                    self.discovered_elbs[account_key][region] = {'classic': [], 'alb': [], 'nlb': []}
                    self.printer.print_colored(Colors.RED, f"[{current_scan:2}/{total_scans}] {account_key} - {region}: ❌ Error: {str(e)}")
        
        self.printer.print_colored(Colors.GREEN, f"✅ Completed scanning {total_scans} account-region combinations")
    
    def display_discovered_elbs(self) -> bool:
        """Display all discovered ELBs and return True if any exist"""
        total_classic = 0
        total_alb = 0
        total_nlb = 0
        
        # Count totals
        for account_key, regions in self.discovered_elbs.items():
            for region, elbs in regions.items():
                total_classic += len(elbs['classic'])
                total_alb += len(elbs['alb'])
                total_nlb += len(elbs['nlb'])
        
        total_elbs = total_classic + total_alb + total_nlb
        
        if total_elbs == 0:
            self.printer.print_colored(Colors.YELLOW, "\n🎉 No ELBs found in any of the scanned accounts and regions!")
            return False
        
        print(f"\n📊 ELB Discovery Summary")
        print("=" * 100)
        print(f"🎯 Total ELBs Found: {total_elbs}")
        print(f"⚖️  Classic Load Balancers: {total_classic}")
        print(f"🌐 Application Load Balancers (ALB): {total_alb}")
        print(f"🔗 Network Load Balancers (NLB): {total_nlb}")
        print("=" * 100)
        
        elb_index = 1
        elb_mapping = {}
        
        for account_key, regions in self.discovered_elbs.items():
            account_data = self.config_data['accounts'][account_key]
            account_id = account_data.get('account_id', 'Unknown')
            
            account_has_elbs = any(
                len(elbs['classic']) > 0 or len(elbs['alb']) > 0 or len(elbs['nlb']) > 0 
                for elbs in regions.values()
            )
            
            if account_has_elbs:
                print(f"\n🏦 Account: {account_key} ({account_id})")
                print("-" * 80)
                
                for region, elbs in regions.items():
                    region_total = len(elbs['classic']) + len(elbs['alb']) + len(elbs['nlb'])
                    
                    if region_total > 0:
                        print(f"\n   🌍 Region: {region} ({region_total} ELBs)")
                        
                        # Display Classic ELBs
                        if elbs['classic']:
                            print(f"      ⚖️  Classic Load Balancers ({len(elbs['classic'])}):")
                            for elb in elbs['classic']:
                                created_time = elb.get('created_time', 'Unknown')
                                if isinstance(created_time, datetime):
                                    created_str = created_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                                else:
                                    created_str = str(created_time)
                                
                                print(f"         {elb_index:3}. {elb['name']}")
                                print(f"              📊 Scheme: {elb['scheme']}")
                                print(f"              🌐 DNS: {elb['dns_name']}")
                                print(f"              🏠 VPC: {elb['vpc_id']}")
                                print(f"              💻 Instances: {elb['instances']}")
                                print(f"              📅 Created: {created_str}")
                                print(f"              🌍 AZs: {', '.join(elb['availability_zones'])}")
                                
                                elb_mapping[elb_index] = {
                                    'account_key': account_key,
                                    'region': region,
                                    'type': 'classic',
                                    'elb': elb
                                }
                                elb_index += 1
                                print()
                        
                        # Display ALBs
                        if elbs['alb']:
                            print(f"      🌐 Application Load Balancers ({len(elbs['alb'])}):")
                            for elb in elbs['alb']:
                                created_time = elb.get('created_time', 'Unknown')
                                if isinstance(created_time, datetime):
                                    created_str = created_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                                else:
                                    created_str = str(created_time)
                                
                                print(f"         {elb_index:3}. {elb['name']}")
                                print(f"              📊 State: {elb['state']}")
                                print(f"              📊 Scheme: {elb['scheme']}")
                                print(f"              🌐 DNS: {elb['dns_name']}")
                                print(f"              🏠 VPC: {elb['vpc_id']}")
                                print(f"              🎯 Target Groups: {elb['target_group_count']}")
                                print(f"              📅 Created: {created_str}")
                                print(f"              🌍 AZs: {', '.join(elb['availability_zones'])}")
                                
                                elb_mapping[elb_index] = {
                                    'account_key': account_key,
                                    'region': region,
                                    'type': 'alb',
                                    'elb': elb
                                }
                                elb_index += 1
                                print()
                        
                        # Display NLBs
                        if elbs['nlb']:
                            print(f"      🔗 Network Load Balancers ({len(elbs['nlb'])}):")
                            for elb in elbs['nlb']:
                                created_time = elb.get('created_time', 'Unknown')
                                if isinstance(created_time, datetime):
                                    created_str = created_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                                else:
                                    created_str = str(created_time)
                                
                                print(f"         {elb_index:3}. {elb['name']}")
                                print(f"              📊 State: {elb['state']}")
                                print(f"              📊 Scheme: {elb['scheme']}")
                                print(f"              🌐 DNS: {elb['dns_name']}")
                                print(f"              🏠 VPC: {elb['vpc_id']}")
                                print(f"              🎯 Target Groups: {elb['target_group_count']}")
                                print(f"              📅 Created: {created_str}")
                                print(f"              🌍 AZs: {', '.join(elb['availability_zones'])}")
                                
                                elb_mapping[elb_index] = {
                                    'account_key': account_key,
                                    'region': region,
                                    'type': 'nlb',
                                    'elb': elb
                                }
                                elb_index += 1
                                print()
        
        self.elb_mapping = elb_mapping
        return True
    
    def select_elbs_to_delete(self) -> List[Dict]:
        """Allow user to select which ELBs to delete"""
        if not hasattr(self, 'elb_mapping') or not self.elb_mapping:
            return []
        
        total_elbs = len(self.elb_mapping)
        
        print(f"\n🗑️  ELB Deletion Selection")
        print("=" * 60)
        print(f"📝 Selection Options:")
        print(f"   • Single ELBs: 1,3,5")
        print(f"   • Ranges: 1-{total_elbs}")
        print(f"   • Mixed: 1-3,5,7-9")
        print(f"   • All ELBs: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select ELBs to DELETE (1-{total_elbs}) or all : ").strip()
            
            self.log_operation('INFO', f"User input for ELB deletion selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all ELBs for deletion")
                return list(self.elb_mapping.values())
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled ELB deletion selection")
                return []
            
            try:
                selected_indices = self.parse_selection(selection, total_elbs)
                if selected_indices:
                    selected_elbs = [self.elb_mapping[idx] for idx in selected_indices]
                    
                    # Show confirmation
                    print(f"\n⚠️  DELETION CONFIRMATION")
                    print("🚨 The following ELBs will be PERMANENTLY DELETED:")
                    print("-" * 60)
                    
                    for i, elb_info in enumerate(selected_elbs, 1):
                        elb = elb_info['elb']
                        elb_type = elb_info['type'].upper()
                        print(f"   {i}. {elb['name']} ({elb_type}) ({elb_info['account_key']} - {elb_info['region']})")
                        
                        if elb_type == 'CLASSIC':
                            print(f"      💻 {elb['instances']} instances attached")
                        else:
                            print(f"      🎯 {elb['target_group_count']} target groups")
                    
                    print("-" * 60)
                    print(f"🔥 Total: {len(selected_elbs)} ELBs will be deleted")
                    print(f"🚀 Parallel Processing: Up to {self.max_parallel_deletions} ELBs will be deleted simultaneously")
                    print("⚠️  This action CANNOT be undone!")
                    
                    confirm1 = input(f"\n❓ Are you sure you want to delete these {len(selected_elbs)} ELBs? (yes/no): ").lower().strip()
                    
                    if confirm1 == 'yes':
                        confirm2 = input(f"❓ Type 'DELETE' to confirm permanent deletion: ").strip()
                        if confirm2 == 'DELETE':
                            self.log_operation('INFO', f"User confirmed deletion of {len(selected_elbs)} ELBs")
                            return selected_elbs
                        else:
                            print("❌ Deletion cancelled - incorrect confirmation")
                    else:
                        print("❌ Deletion cancelled")
                    continue
                else:
                    print("❌ No valid ELBs selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                continue
    
    def parse_selection(self, selection, max_items):
        """Parse selection string and return list of indices"""
        selected_indices = set()
        
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
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
                try:
                    num = int(part)
                    if num < 1 or num > max_items:
                        raise ValueError(f"ELB number {num} is out of bounds (1-{max_items})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid ELB number: {part}")
        
        return sorted(list(selected_indices))
    
    def delete_single_elb(self, elb_info: Dict, thread_id: str = None) -> bool:
        """Delete a single ELB - Thread-safe"""
        if thread_id is None:
            thread_id = str(threading.current_thread().ident)
        
        try:
            account_key = elb_info['account_key']
            region = elb_info['region']
            elb_type = elb_info['type']
            elb = elb_info['elb']
            elb_name = elb['name']
            
            self.log_operation('INFO', f"Starting deletion of {elb_type.upper()} ELB {elb_name} in {account_key} - {region}", thread_id)
            self.printer.print_colored(Colors.YELLOW, f"🗑️  Deleting {elb_type.upper()} ELB: {elb_name} ({account_key} - {region})", thread_id)
            
            # Get credentials
            access_key, secret_key = self.get_credentials_for_account(account_key)
            
            # Create AWS session
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            if elb_type == 'classic':
                # Delete Classic Load Balancer
                elb_client = session.client('elb')
                elb_client.delete_load_balancer(LoadBalancerName=elb_name)
                self.log_operation('INFO', f"Classic ELB {elb_name} deletion initiated", thread_id)
                
            else:
                # Delete ALB/NLB (ELBv2)
                elbv2_client = session.client('elbv2')
                
                # First delete target groups
                if elb.get('target_groups'):
                    self.printer.print_normal(f"   🎯 Deleting {len(elb['target_groups'])} target groups...", thread_id)
                    
                    for tg_name in elb['target_groups']:
                        try:
                            # Get target group ARN
                            tg_response = elbv2_client.describe_target_groups(Names=[tg_name])
                            for tg in tg_response.get('TargetGroups', []):
                                if tg['LoadBalancerArns'] and elb['arn'] in tg['LoadBalancerArns']:
                                    elbv2_client.delete_target_group(TargetGroupArn=tg['TargetGroupArn'])
                                    self.log_operation('INFO', f"Deleted target group {tg_name}", thread_id)
                        except Exception as e:
                            self.log_operation('WARNING', f"Failed to delete target group {tg_name}: {str(e)}", thread_id)
                
                # Delete the load balancer
                elbv2_client.delete_load_balancer(LoadBalancerArn=elb['arn'])
                self.log_operation('INFO', f"{elb_type.upper()} ELB {elb_name} deletion initiated", thread_id)
            
            self.log_operation('INFO', f"ELB {elb_name} successfully deleted", thread_id)
            self.printer.print_colored(Colors.GREEN, f"   ✅ ELB {elb_name} deleted successfully", thread_id)
            
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"Failed to delete ELB {elb_name}: {error_msg}", thread_id)
            self.printer.print_colored(Colors.RED, f"   ❌ Failed to delete ELB {elb_name}: {error_msg}", thread_id)
            return False
    
    def update_deletion_summary(self, deletion_record: Dict):
        """Thread-safe update of deletion summary"""
        with self.summary_lock:
            self.deletion_summary.append(deletion_record)
    
    def delete_selected_elbs(self, selected_elbs: List[Dict]) -> None:
        """Delete all selected ELBs using parallel processing"""
        if not selected_elbs:
            self.printer.print_colored(Colors.YELLOW, "No ELBs selected for deletion!")
            return
        
        self.log_operation('INFO', f"Starting parallel deletion of {len(selected_elbs)} ELBs")
        self.printer.print_colored(Colors.RED, f"\n🚨 Starting parallel deletion of {len(selected_elbs)} ELBs...")
        self.printer.print_colored(Colors.CYAN, f"🚀 Maximum parallel deletions: {self.max_parallel_deletions}")
        
        successful_deletions = []
        failed_deletions = []
        
        # Progress tracking
        completed_deletions = 0
        progress_lock = threading.Lock()
        
        def update_progress(elb_name: str, success: bool, deletion_record: Dict):
            nonlocal completed_deletions
            with progress_lock:
                completed_deletions += 1
                if success:
                    successful_deletions.append(deletion_record)
                else:
                    failed_deletions.append(deletion_record)
                
                progress_msg = f"📊 Progress: {completed_deletions}/{len(selected_elbs)} completed"
                if successful_deletions:
                    progress_msg += f" (✅ {len(successful_deletions)} successful"
                if failed_deletions:
                    progress_msg += f", ❌ {len(failed_deletions)} failed"
                if successful_deletions or failed_deletions:
                    progress_msg += ")"
                
                self.printer.print_colored(Colors.BLUE, progress_msg)
                return completed_deletions
        
        def delete_elb_worker(elb_info: Dict) -> Dict:
            """Worker function for parallel ELB deletion"""
            thread_id = str(threading.current_thread().ident)
            elb_name = elb_info['elb']['name']
            account_key = elb_info['account_key']
            region = elb_info['region']
            elb_type = elb_info['type']
            
            start_time = time.time()
            
            try:
                success = self.delete_single_elb(elb_info, thread_id)
                end_time = time.time()
                duration = end_time - start_time
                
                deletion_record = {
                    'elb_name': elb_name,
                    'elb_type': elb_type.upper(),
                    'account_key': account_key,
                    'region': region,
                    'status': 'SUCCESS' if success else 'FAILED',
                    'duration_seconds': round(duration, 2),
                    'thread_id': thread_id,
                    'start_time': datetime.fromtimestamp(start_time).strftime('%H:%M:%S'),
                    'end_time': datetime.fromtimestamp(end_time).strftime('%H:%M:%S')
                }
                
                if success and elb_type != 'classic':
                    deletion_record['target_groups_deleted'] = len(elb_info['elb'].get('target_groups', []))
                elif success and elb_type == 'classic':
                    deletion_record['instances_detached'] = elb_info['elb'].get('instances', 0)
                
                # Update summary thread-safely
                self.update_deletion_summary(deletion_record)
                
                # Update progress
                update_progress(elb_name, success, deletion_record)
                
                return deletion_record
                
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                
                deletion_record = {
                    'elb_name': elb_name,
                    'elb_type': elb_type.upper(),
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
                update_progress(elb_name, False, deletion_record)
                
                return deletion_record
        
        # Execute parallel deletions
        self.printer.print_colored(Colors.YELLOW, f"🚀 Starting parallel execution...")
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_parallel_deletions, thread_name_prefix="DeleteWorker") as executor:
            future_to_elb = {
                executor.submit(delete_elb_worker, elb_info): elb_info
                for elb_info in selected_elbs
            }
            
            for future in as_completed(future_to_elb):
                elb_info = future_to_elb[future]
                elb_name = elb_info['elb']['name']
                
                try:
                    deletion_record = future.result()
                    # Results already processed in worker function
                    
                except Exception as e:
                    self.log_operation('ERROR', f"Unexpected error in deletion worker for {elb_name}: {str(e)}")
        
        total_time = time.time() - start_time
        
        # Final summary
        self.log_operation('INFO', f"Parallel ELB deletion completed - Deleted: {len(successful_deletions)}, Failed: {len(failed_deletions)}, Total Time: {total_time:.2f}s")
        
        print("\n" + "=" * 80)
        self.printer.print_colored(Colors.GREEN, f"🎉 Parallel ELB Deletion Summary:")
        self.printer.print_colored(Colors.GREEN, f"✅ Successfully Deleted: {len(successful_deletions)}")
        if failed_deletions:
            self.printer.print_colored(Colors.RED, f"❌ Failed: {len(failed_deletions)}")
        
        self.printer.print_colored(Colors.CYAN, f"⏱️  Total Execution Time: {total_time:.2f} seconds")
        self.printer.print_colored(Colors.CYAN, f"🚀 Parallel Workers Used: {self.max_parallel_deletions}")
        
        if successful_deletions:
            avg_time = sum(r['duration_seconds'] for r in successful_deletions) / len(successful_deletions)
            self.printer.print_colored(Colors.CYAN, f"📊 Average Deletion Time: {avg_time:.2f} seconds per ELB")
        
        print("=" * 80)
        
        # Generate deletion report
        self.generate_deletion_report()
    
    def generate_deletion_report(self) -> None:
        """Generate detailed deletion report file"""
        if not self.deletion_summary:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"elb_deletion_report_{timestamp}.txt"
        
        self.printer.print_colored(Colors.CYAN, f"\n💾 Deletion report saved to: {report_file}")
        
        with open(report_file, 'w') as f:
            f.write(f"# ELB Parallel Deletion Report\n")
            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"# Executed by: {self.current_user}\n")
            f.write(f"# Total ELBs processed: {len(self.deletion_summary)}\n")
            f.write(f"# Max parallel workers: {self.max_parallel_deletions}\n")
            f.write(f"# Regions scanned: {', '.join(self.scan_regions)}\n\n")
            
            successful = [r for r in self.deletion_summary if r['status'] == 'SUCCESS']
            failed = [r for r in self.deletion_summary if r['status'] == 'FAILED']
            
            f.write(f"## Summary\n")
            f.write(f"✅ Successfully deleted: {len(successful)}\n")
            f.write(f"❌ Failed deletions: {len(failed)}\n")
            f.write(f"🚀 Parallel execution enabled: {self.max_parallel_deletions} max workers\n\n")
            
            if successful:
                f.write(f"## Successful Deletions\n")
                f.write(f"{'ELB Name':<30} {'Type':<8} {'Account':<15} {'Region':<15} {'Duration':<10} {'Start':<10} {'End':<10} {'Thread':<12}\n")
                f.write(f"{'-'*110}\n")
                
                for record in successful:
                    f.write(f"{record['elb_name']:<30} {record['elb_type']:<8} {record['account_key']:<15} {record['region']:<15} "
                           f"{record['duration_seconds']:<10} {record.get('start_time', 'N/A'):<10} {record.get('end_time', 'N/A'):<10} "
                           f"{record.get('thread_id', 'N/A'):<12}\n")
            
            if failed:
                f.write(f"\n## Failed Deletions\n")
                f.write(f"{'ELB Name':<30} {'Type':<8} {'Account':<15} {'Region':<15} {'Error':<50}\n")
                f.write(f"{'-'*120}\n")
                
                for record in failed:
                    error_msg = record.get('error', 'Unknown error')[:47] + '...' if len(record.get('error', '')) > 50 else record.get('error', 'Unknown error')
                    f.write(f"{record['elb_name']:<30} {record['elb_type']:<8} {record['account_key']:<15} {record['region']:<15} {error_msg:<50}\n")
    
    def display_accounts_menu(self) -> List[str]:
        """Display available accounts and return selection"""
        accounts = list(self.config_data['accounts'].keys())
        user_settings = self.config_data.get('user_settings', {})
        
        print(f"\n🏦 Available AWS Accounts ({len(accounts)} total):")
        print("=" * 60)
        
        for i, account_key in enumerate(accounts, 1):
            account_data = self.config_data['accounts'][account_key]
            account_id = account_data.get('account_id', 'Unknown')
            email = account_data.get('email', 'Unknown')
            
            print(f"  {i:2}. {account_key}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      📧 Email: {email}")
            print()
        
        print("=" * 60)
        print(f"🌍 Scan Regions (from user_settings): {', '.join(self.scan_regions)}")
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
                        account_data = self.config_data['accounts'][account_key]
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
        """Main execution flow"""
        try:
            self.printer.print_colored(Colors.RED, "🗑️  Welcome to ELB Cleanup Manager (Parallel Edition)")
            
            print("🗑️  ELB Cleanup Tool (Parallel Processing)")
            print("=" * 80)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"🔑 Config File: {self.config_file}")
            print(f"🌍 Scan Regions: {', '.join(self.scan_regions)}")
            print(f"🚀 Max Parallel Deletions: {self.max_parallel_deletions}")
            print(f"📋 Log File: {self.log_filename}")
            print("=" * 80)
            
            print("⚠️  WARNING: This tool will permanently delete ELBs!")
            print("🚨 Deleted ELBs cannot be recovered!")
            print("🚀 Parallel processing will speed up deletions!")
            
            # Step 1: Select accounts to scan
            selected_accounts = self.display_accounts_menu()
            if not selected_accounts:
                print("❌ Account selection cancelled")
                return
            
            # Step 2: Scan all accounts and regions
            self.scan_all_accounts_and_regions(selected_accounts)
            
            # Step 3: Display discovered ELBs
            elbs_found = self.display_discovered_elbs()
            if not elbs_found:
                return
            
            # Step 4: Select ELBs to delete
            elbs_to_delete = self.select_elbs_to_delete()
            if not elbs_to_delete:
                self.printer.print_colored(Colors.YELLOW, "No ELBs selected for deletion.")
                return
            
            # Step 5: Delete selected ELBs
            self.delete_selected_elbs(elbs_to_delete)
            
        except KeyboardInterrupt:
            self.printer.print_colored(Colors.YELLOW, "\n\nOperation cancelled by user.")
        except Exception as e:
            error_msg = str(e)
            self.printer.print_colored(Colors.RED, f"Error: {error_msg}")
            sys.exit(1)

def main():
    """Main entry point"""
    try:
        # Run the ELB cleanup manager with parallel processing
        manager = ELBCleanupManager()
        manager.run()
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()