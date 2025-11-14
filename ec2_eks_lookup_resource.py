# Databricks notebook source
#!/usr/bin/env python3
"""
AWS Resource Manager - FIXED VERSION
Manages EKS clusters and EC2 instances state files and provides APIs to check resource status
"""

import json
import os
import re
import boto3
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from botocore.exceptions import ClientError
import glob
from collections import defaultdict

# Set UTF-8 encoding for console output
if sys.platform.startswith('win'):
    os.system('chcp 65001 >nul')  # Set Windows console to UTF-8
    
# Force UTF-8 encoding
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

class AWSCostCalculator:
    """Class to handle cost calculations for AWS resources"""
    
    # AWS pricing (approximate USD per hour)
    EC2_PRICING = {
        't2.micro': 0.0116,
        't2.small': 0.023,
        't2.medium': 0.0464,
        't2.large': 0.0928,
        't3.micro': 0.0104,
        't3.small': 0.0208,
        't3.medium': 0.0416,
        't3.large': 0.0832,
        't3.xlarge': 0.1664,
        'c6a.large': 0.0864,
        'c6a.xlarge': 0.1728,
        'm5.large': 0.096,
        'm5.xlarge': 0.192,
    }
    
    # EKS cluster base cost - FIXED: Changed from 0.10 to 0.65
    EKS_CLUSTER_HOURLY_COST = 0.65  # $0.65 per hour per cluster
    
    # Storage costs (per GB per month)
    EBS_GP3_COST_PER_GB_MONTH = 0.08
    
    def __init__(self):
        pass
    
    def get_current_time(self) -> datetime:
        """Get current UTC time (timezone-aware)"""
        return datetime.now(timezone.utc)
    
    def calculate_live_ec2_cost(self, instance_data: Dict, live_instance_data: Dict = None) -> Dict:
        """Calculate EC2 instance cost based on LIVE AWS data"""
        instance_type = instance_data.get('instance_type', 'unknown')
        instance_id = instance_data.get('instance_id', 'unknown')
        
        # Use live launch time if available, otherwise fall back to created_at
        launch_time = None
        if live_instance_data and 'LaunchTime' in live_instance_data:
            launch_time = live_instance_data['LaunchTime']
            if hasattr(launch_time, 'replace'):
                launch_time = launch_time.replace(tzinfo=timezone.utc)
        
        if not launch_time:
            # Fall back to created_at from JSON
            created_at = instance_data.get('created_at', '')
            if created_at:
                try:
                    launch_time = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                except:
                    launch_time = None
        
        # Calculate actual running hours
        current_time = self.get_current_time()
        if launch_time:
            running_hours = (current_time - launch_time).total_seconds() / 3600
            running_hours = max(0.01, running_hours)  # At least 0.01 hours
        else:
            running_hours = 24  # Default fallback
        
        # Get current state
        current_state = 'unknown'
        if live_instance_data:
            current_state = live_instance_data.get('State', {}).get('Name', 'unknown')
        
        hourly_rate = self.EC2_PRICING.get(instance_type, 0.05)  # Default fallback
        
        # Calculate compute cost (only for running time)
        compute_cost = hourly_rate * running_hours
        
        # Calculate storage cost (EBS - charged even when stopped)
        disk_size_gb = instance_data.get('disk_size', 20)  # Default 20GB
        if isinstance(disk_size_gb, str):
            disk_size_gb = int(disk_size_gb) if disk_size_gb.isdigit() else 20
        
        storage_cost_monthly = disk_size_gb * self.EBS_GP3_COST_PER_GB_MONTH
        storage_cost = storage_cost_monthly * (running_hours / 24 / 30)  # Prorated
        
        total_cost = compute_cost + storage_cost
        
        return {
            'instance_id': instance_id,
            'instance_type': instance_type,
            'hours_running': running_hours,
            'hourly_rate': hourly_rate,
            'compute_cost': compute_cost,
            'storage_cost': storage_cost,
            'total_cost': total_cost,
            'disk_size_gb': disk_size_gb,
            'current_state': current_state,
            'launch_time': launch_time,
            'calculation_time': current_time
        }
    
    def parse_and_convert_to_utc(self, time_string):
        """Helper to parse time strings and convert to UTC"""
        if not time_string or time_string in ['Unknown', '']:
            return datetime.now(timezone.utc)
        
        # IST timezone offset
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        
        try:
            # Common formats to try
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',      # With microseconds
                '%Y-%m-%d %H:%M:%S',         # Standard format
                '%Y-%m-%dT%H:%M:%S.%fZ',     # ISO format with Z
                '%Y-%m-%dT%H:%M:%SZ',        # ISO format without microseconds
                '%Y-%m-%dT%H:%M:%S.%f%z',    # ISO with timezone
                '%Y-%m-%dT%H:%M:%S%z',       # ISO with timezone no microseconds
            ]
            
            for fmt in formats:
                try:
                    if 'Z' in time_string:
                        # Remove Z and treat as UTC
                        clean_time = time_string.replace('Z', '')
                        parsed_time = datetime.strptime(clean_time, fmt.replace('Z', ''))
                        return parsed_time.replace(tzinfo=timezone.utc)
                    elif '+' in time_string or time_string.endswith('IST'):
                        # Has timezone info
                        if time_string.endswith('IST'):
                            # Remove IST and treat as IST timezone
                            clean_time = time_string.replace(' IST', '')
                            parsed_time = datetime.strptime(clean_time, fmt.replace('%z', ''))
                            return parsed_time.replace(tzinfo=ist_tz).astimezone(timezone.utc)
                        else:
                            # Has +/- timezone offset
                            parsed_time = datetime.strptime(time_string, fmt)
                            return parsed_time.astimezone(timezone.utc)
                    else:
                        # No timezone info - assume UTC
                        parsed_time = datetime.strptime(time_string, fmt)
                        return parsed_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
            
            # If no format matches, try to parse ISO format manually
            if 'T' in time_string:
                # ISO format
                return datetime.fromisoformat(time_string.replace('Z', '+00:00')).astimezone(timezone.utc)
            
            # Last resort - assume it's a simple date string in UTC
            parsed_time = datetime.strptime(time_string, '%Y-%m-%d %H:%M:%S')
            return parsed_time.replace(tzinfo=timezone.utc)
        
        except Exception as e:
            print(f"⚠️ Warning: Could not parse time '{time_string}': {e}")
            print(f"   Using current time as fallback")
            return datetime.now(timezone.utc)
    
    def get_ebs_hourly_rate(self, volume_type='gp3', region='us-east-1'):
        """Get EBS storage hourly rate per GB"""
        # EBS pricing per GB per month, converted to hourly
        monthly_rates = {
            'gp3': 0.08,    # $0.08 per GB per month
            'gp2': 0.10,    # $0.10 per GB per month
            'io1': 0.125,   # $0.125 per GB per month
            'io2': 0.125,   # $0.125 per GB per month
        }
        
        monthly_rate = monthly_rates.get(volume_type, 0.08)
        
        # Convert monthly to hourly (assuming 730 hours per month)
        hourly_rate = monthly_rate / 730
        
        # Regional pricing multipliers
        regional_multipliers = {
            'us-east-1': 1.0,
            'us-west-1': 1.0,
            'us-west-2': 1.0,
            'eu-west-1': 1.0,
            'ap-southeast-1': 1.0,
        }
        
        multiplier = regional_multipliers.get(region, 1.0)
        return hourly_rate * multiplier
    
    def get_ec2_hourly_rate(self, instance_type, region='us-east-1'):
        """Get EC2 instance hourly rate"""
        # Your existing EC2 pricing logic
        base_rates = {
        't3.micro': 0.0104,
        't3.small': 0.0208,
        't3.medium': 0.0416,
        't3.large': 0.0832,
        't3.xlarge': 0.1664,
        't3.2xlarge': 0.3328,
        'm5.large': 0.0960,
        'm5.xlarge': 0.1920,
        'm5.2xlarge': 0.3840,
        'm5.4xlarge': 0.7680,
        'c5.large': 0.0850,
        'c5.xlarge': 0.1700,
        'c5.2xlarge': 0.3400,
        'c5.4xlarge': 0.6800,
        'c5.9xlarge': 1.6200
        }
        
        base_rate = base_rates.get(instance_type, 0.0416)  # Default to t3.medium
        
        # Regional pricing multipliers (simplified)
        regional_multipliers = {
            'us-east-1': 1.0,
            'us-west-1': 1.05,
            'us-west-2': 1.05,
            'eu-west-1': 1.1,
            'ap-southeast-1': 1.15,
        }
        
        multiplier = regional_multipliers.get(region, 1.0)
        return base_rate * multiplier
    
    def format_creation_time_readable(self, timestamp_str):
        """Format creation timestamp to show only hours and minutes"""
        try:
            # Parse the timestamp (handles both string and datetime objects)
            if isinstance(timestamp_str, str):
                # Handle different formats
                if '+05:30' in timestamp_str or 'IST' in timestamp_str:
                    # Remove timezone info for parsing
                    clean_time = timestamp_str.replace('+05:30', '').replace(' IST', '').strip()
                    dt = datetime.fromisoformat(clean_time)
                    # Add IST timezone
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    dt = dt.replace(tzinfo=ist_tz)
                else:
                    dt = datetime.fromisoformat(timestamp_str)
            else:
                dt = timestamp_str
            
            # Convert to IST if needed
            if dt.tzinfo != timezone(timedelta(hours=5, minutes=30)):
                ist_tz = timezone(timedelta(hours=5, minutes=30))
                dt = dt.astimezone(ist_tz)
            
            # Format options:
            
            # Option 1: 12:01 PM IST (12-hour format)
            return dt.strftime('%I:%M %p IST')
            
            # Option 2: 12:01 IST (12-hour without AM/PM)
            # return dt.strftime('%I:%M IST')
            
            # Option 3: 12:01 (24-hour format, no timezone)
            # return dt.strftime('%H:%M')
            
            # Option 4: 12:01 PM (12-hour, no timezone)
            # return dt.strftime('%I:%M %p')
            
        except Exception as e:
            return "Unknown time"
        
    def calculate_live_eks_cost(self, cluster_data, live_cluster_data=None):
        """Calculate EKS cost with proper timezone handling and live AWS data"""
        
        # Get current time in UTC (consistent reference)
        current_time_utc = datetime.now(timezone.utc)
        
        # Handle creation time with proper timezone conversion
        if live_cluster_data and 'createdAt' in live_cluster_data:
            # AWS API returns createdAt in UTC
            created_at = live_cluster_data['createdAt']
            
            # Ensure it's timezone-aware UTC
            if hasattr(created_at, 'tzinfo'):
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                elif created_at.tzinfo != timezone.utc:
                    created_at = created_at.astimezone(timezone.utc)
            else:
                # If it's a string, parse it
                created_at = self.parse_and_convert_to_utc(str(created_at))
        else:
            # Fallback to stored data - need to convert if it's in IST
            created_str = cluster_data.get('created_time', '')
            if not created_str:
                # Try alternative field names
                created_str = cluster_data.get('creation_time', cluster_data.get('created_on', ''))
            
            created_at = self.parse_and_convert_to_utc(created_str)
        
        # Calculate running time in UTC (both times in same timezone)
        running_time = current_time_utc - created_at
        hours_running = max(0, running_time.total_seconds() / 3600)  # Ensure non-negative
        
        # Get cluster configuration
        instance_type = cluster_data.get('instance_type', 't3.medium')
        disk_size_gb = int(cluster_data.get('disk_size', 20))
        
        # Get actual node count from live data if available
        if live_cluster_data and 'nodegroups' in live_cluster_data:
            actual_nodes = sum([
                ng.get('scalingConfig', {}).get('desiredSize', 0) 
                for ng in live_cluster_data['nodegroups']
            ])
            current_status = live_cluster_data.get('status', 'UNKNOWN')
        else:
            # Fallback to stored data
            actual_nodes = int(cluster_data.get('default_nodes', cluster_data.get('min_nodes', 1)))
            current_status = 'UNKNOWN (from stored data)'
        
        # Cost calculations
        # 1. EKS Control Plane cost
        control_plane_cost = hours_running * self.EKS_CLUSTER_HOURLY_COST
        
        # 2. Node compute cost
        hourly_rate = self.get_ec2_hourly_rate(instance_type, cluster_data.get('region', 'us-east-1'))
        node_compute_cost = hours_running * hourly_rate * actual_nodes
        
        # 3. EBS storage cost (if any)
        storage_hourly_rate = self.get_ebs_hourly_rate('gp3', cluster_data.get('region', 'us-east-1'))
        node_storage_cost = hours_running * storage_hourly_rate * disk_size_gb * actual_nodes
        
        # Total cost
        total_cost = control_plane_cost + node_compute_cost + node_storage_cost
        
        return {
            'total_cost': total_cost,
            'control_plane_cost': control_plane_cost,
            'node_compute_cost': node_compute_cost,
            'node_storage_cost': node_storage_cost,
            'hours_running': hours_running,
            'calculation_time': current_time_utc,
            'cluster_created_at_utc': created_at,
            'current_status': current_status,
            'actual_nodes': actual_nodes,
            'instance_type': instance_type,
            'disk_size_gb': disk_size_gb,
            'hourly_rate': hourly_rate,
            'control_plane_hourly_rate': self.EKS_CLUSTER_HOURLY_COST,
            'node_storage_hourly_rate': storage_hourly_rate,
            'cost_breakdown': {
                'control_plane': {
                    'hours': hours_running,
                    'rate_per_hour': self.EKS_CLUSTER_HOURLY_COST,
                    'total': control_plane_cost
                },
                'compute': {
                    'hours': hours_running,
                    'rate_per_hour': hourly_rate,
                    'nodes': actual_nodes,
                    'total': node_compute_cost
                },
                'storage': {
                    'hours': hours_running,
                    'rate_per_gb_hour': storage_hourly_rate,
                    'total_gb': disk_size_gb * actual_nodes,
                    'total': node_storage_cost
                }
            }
        }

    def calculate_ec2_cost(self, instance_data: Dict, hours: int = 24) -> Dict:
        """Calculate EC2 instance cost (legacy method for JSON-only data)"""
        instance_type = instance_data.get('instance_type', 'unknown')
        created_at = instance_data.get('created_at', '')
        
        # Calculate hours since creation if possible
        if created_at:
            try:
                created_time = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                current_time = self.get_current_time()
                actual_hours = (current_time - created_time).total_seconds() / 3600
                hours = max(1, int(actual_hours))  # At least 1 hour
            except:
                pass
        
        hourly_rate = self.EC2_PRICING.get(instance_type, 0.05)  # Default fallback
        
        # Calculate compute cost
        compute_cost = hourly_rate * hours
        
        # Calculate storage cost (EBS)
        disk_size_gb = instance_data.get('disk_size', 20)  # Default 20GB
        if isinstance(disk_size_gb, str):
            disk_size_gb = int(disk_size_gb) if disk_size_gb.isdigit() else 20
        
        storage_cost_monthly = disk_size_gb * self.EBS_GP3_COST_PER_GB_MONTH
        storage_cost = storage_cost_monthly * (hours / 24 / 30)  # Prorated
        
        total_cost = compute_cost + storage_cost
        
        return {
            'instance_id': instance_data.get('instance_id', 'unknown'),
            'instance_type': instance_type,
            'hours_running': hours,
            'hourly_rate': hourly_rate,
            'compute_cost': compute_cost,
            'storage_cost': storage_cost,
            'total_cost': total_cost,
            'disk_size_gb': disk_size_gb
        }
    
    def calculate_eks_cost(self, cluster_data: Dict, hours: int = 24) -> Dict:
        """Calculate EKS cluster cost (legacy method for JSON-only data) - FIXED pricing"""
        cluster_name = cluster_data.get('cluster_name', 'unknown')
        created_timestamp = cluster_data.get('created_timestamp', '')
        
        # Calculate hours since creation if possible
        if created_timestamp:
            try:
                # Parse timestamp format like "20250603_121046"
                created_time = datetime.strptime(created_timestamp, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
                current_time = self.get_current_time()
                actual_hours = (current_time - created_time).total_seconds() / 3600
                hours = max(1, int(actual_hours))  # At least 1 hour
            except:
                pass
        
        # EKS Control Plane cost - FIXED: Using correct price
        control_plane_cost = self.EKS_CLUSTER_HOURLY_COST * hours
        
        # Node Group costs (estimated)
        instance_type = cluster_data.get('instance_type', 't3.micro')
        max_nodes = cluster_data.get('max_nodes', 1)
        default_nodes = cluster_data.get('default_nodes', 1)
        
        # Use default_nodes for cost calculation
        node_hourly_rate = self.EC2_PRICING.get(instance_type, 0.05)
        node_compute_cost = node_hourly_rate * default_nodes * hours
        
        # Node storage cost
        disk_size_gb = cluster_data.get('disk_size', 20)
        if isinstance(disk_size_gb, str):
            disk_size_gb = int(disk_size_gb) if str(disk_size_gb).isdigit() else 20
        
        storage_cost_monthly = disk_size_gb * default_nodes * self.EBS_GP3_COST_PER_GB_MONTH
        node_storage_cost = storage_cost_monthly * (hours / 24 / 30)  # Prorated
        
        total_cost = control_plane_cost + node_compute_cost + node_storage_cost
        
        return {
            'cluster_name': cluster_name,
            'instance_type': instance_type,
            'hours_running': hours,
            'control_plane_cost': control_plane_cost,
            'node_compute_cost': node_compute_cost,
            'node_storage_cost': node_storage_cost,
            'total_cost': total_cost,
            'default_nodes': default_nodes,
            'disk_size_gb': disk_size_gb
        }

class AWSResourceManager:
    def __init__(self, config_file: str = "aws_accounts_config.json"):
        """Initialize the AWS Resource Manager"""
        self.config_file = config_file
        self.aws_config = self.load_aws_config()
        self.cost_calculator = AWSCostCalculator()
        self.execution_reports = []  # Store reports for consolidated saving
        
    def get_current_time_formatted(self) -> str:
        """Get current IST time in formatted string"""
        return datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M:%S')
    
    def utc_to_ist(self, utc_time_str: str) -> str:
        """Convert UTC timestamp to IST"""
        try:
            if isinstance(utc_time_str, str):
                # Try different UTC formats
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%fZ']:
                    try:
                        utc_dt = datetime.strptime(utc_time_str, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    return utc_time_str  # Return original if no format matches
            elif hasattr(utc_time_str, 'replace'):
                # It's already a datetime object
                utc_dt = utc_time_str.replace(tzinfo=timezone.utc) if utc_time_str.tzinfo is None else utc_time_str
            else:
                return str(utc_time_str)
            
            # Convert to IST
            ist_dt = utc_dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
            return ist_dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return str(utc_time_str)
        
    def load_aws_config(self) -> Dict:
        """Load AWS account configuration"""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ AWS config file '{self.config_file}' not found!")
            return {}
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON in '{self.config_file}'!")
            return {}

    def detect_resource_type(self, resource_id: str) -> str:
        """Detect if resource_id is an EKS cluster name or EC2 instance ID"""
        # EC2 instance IDs start with 'i-' followed by alphanumeric characters
        if re.match(r'^i-[a-f0-9]+$', resource_id):
            return 'ec2'
        # Assume everything else is an EKS cluster name
        else:
            return 'eks'
        
        
    def format_timestamp_to_ist_readable(self, timestamp_str: str) -> str:
        """Convert timestamp from YYYYMMDD_HHMMSS to readable IST format"""
        try:
            # Parse the timestamp (e.g., "20250603_121046")
            dt = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
            
            # Since the timestamp is already in IST, just format it nicely
            return dt.strftime('%B %d, %Y at %I:%M:%S %p IST')
            # This will output like: "June 03, 2025 at 12:10:46 PM IST"
        except:
            return f"{timestamp_str} (Invalid format)"

    def find_state_files(self, patterns: List[str]) -> List[Tuple[str, str]]:
        """Find all state files matching the patterns and return sorted by timestamp"""
        files = []
        for pattern in patterns:
            files.extend(glob.glob(pattern))
        
        file_timestamps = []
        
        for file in files:
            # Extract timestamp from filename
            timestamp_match = re.search(r'(\d{8}_\d{6})', file)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                file_timestamps.append((file, timestamp))
        
        # Sort by timestamp (latest first)
        file_timestamps.sort(key=lambda x: x[1], reverse=True)
        return file_timestamps
    
    def group_files_by_date(self, file_timestamps: List[Tuple[str, str]]) -> Dict[str, List[str]]:
        """Group files by date (YYYYMMDD) and return in reverse chronological order"""
        date_groups = defaultdict(list)
        
        for file, timestamp in file_timestamps:
            # Extract date from timestamp (YYYYMMDD_HHMMSS -> YYYYMMDD)
            date_part = timestamp.split('_')[0]
            date_groups[date_part].append((file, timestamp))  # Store both file and timestamp
        
        # Sort dates in reverse order (newest first)
        sorted_dates = sorted(date_groups.keys(), reverse=True)
        
        return {date: date_groups[date] for date in sorted_dates}

    def format_date_display(self, date_str: str) -> str:
        """Format YYYYMMDD to readable date"""
        try:
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.strftime('%B %d, %Y')  # e.g., "June 03, 2025"
        except:
            return date_str

    def select_files(self, file_type: str) -> List[str]:
        """Interactive file selection with date-based confirmation and readable timestamps"""
        if file_type.lower() == 'eks':
            patterns = [
                "eks_cluster_created_*.json",
                "eks_clusters_created_*.json"
            ]
        else:
            patterns = [
                "ec2_instance_report_*.json",
                "ec2_instances_report_*.json",
                "ec2_report_*.json"
            ]
        
        json_files = self.find_state_files(patterns)
        
        if not json_files:
            print(f"❌ No {file_type} state files found!")
            print(f"   Looking for patterns: {', '.join(patterns)}")
            return []
        
        # Group files by date
        date_groups = self.group_files_by_date(json_files)
        
        print(f"\n📁 Found {len(json_files)} {file_type.upper()} state file(s) across {len(date_groups)} date(s):")
        print("-" * 70)
        
        selected_files = []
        
        # Ask for each date group, starting from newest
        for date_str, file_timestamp_pairs in date_groups.items():
            readable_date = self.format_date_display(date_str)
            print(f"\n📅 {readable_date} ({date_str}): {len(file_timestamp_pairs)} file(s)")
            
            # Sort files within the date by timestamp (latest first)
            file_timestamp_pairs.sort(key=lambda x: x[1], reverse=True)
            
            for i, (file, timestamp) in enumerate(file_timestamp_pairs, 1):
                file_size = os.path.getsize(file) if os.path.exists(file) else 0
                readable_timestamp = self.format_timestamp_to_ist_readable(timestamp)
                print(f"   {i}. {file}")
                print(f"      📅 Created: {readable_timestamp}")
                print(f"      📦 Size: {file_size:,} bytes")
            
            # Ask user confirmation for this date
            while True:
                response = input(f"\n🤔 Process {readable_date} files? (yes/no): ").strip().lower()
                if response in ['yes', 'y']:
                    # Add just the file names to selected_files
                    selected_files.extend([file for file, _ in file_timestamp_pairs])
                    print(f"✅ Added {len(file_timestamp_pairs)} file(s) from {readable_date}")
                    break
                elif response in ['no', 'n']:
                    print(f"⏭️ Skipping {readable_date} and all older files")
                    # If user says no to this date, stop asking for older dates
                    if selected_files:
                        print(f"\n📋 Final selection: {len(selected_files)} file(s) from newer dates")
                        return selected_files
                    else:
                        print(f"\n❌ No files selected")
                        return []
                else:
                    print("❌ Please enter 'yes' or 'no'")
        
        if selected_files:
            print(f"\n📋 Final selection: {len(selected_files)} file(s) from all selected dates")
        else:
            print(f"\n❌ No files selected")
        
        return selected_files

    def parse_selection_input(self, user_input: str, max_items: int) -> List[int]:
        """Parse user selection input supporting ranges, multiple values, and 'all'"""
        user_input = user_input.strip().lower()
        
        if not user_input or user_input == 'all':
            return list(range(1, max_items + 1))
        
        selected_items = []
        
        # Split by comma and process each part
        parts = [part.strip() for part in user_input.split(',')]
        
        for part in parts:
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start, end = map(int, part.split('-'))
                    selected_items.extend(range(start, end + 1))
                except ValueError:
                    print(f"⚠️ Invalid range format: {part}")
                    continue
            else:
                # Handle single number
                try:
                    num = int(part)
                    if 1 <= num <= max_items:
                        selected_items.append(num)
                    else:
                        print(f"⚠️ Number {num} is out of range (1-{max_items})")
                except ValueError:
                    print(f"⚠️ Invalid number: {part}")
                    continue
        
        # Remove duplicates and sort
        return sorted(list(set(selected_items)))

    def get_aws_client(self, service: str, region: str, account_key: str):
        """Get AWS client with ROOT credentials from config"""
        if account_key not in self.aws_config.get('accounts', {}):
            raise ValueError(f"Account key '{account_key}' not found in configuration")
        
        account_info = self.aws_config['accounts'][account_key]
        
        print(f"🔑 Using ROOT credentials for account '{account_key}': {account_info.get('email', 'Unknown')}")
        
        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=account_info['access_key'],
            aws_secret_access_key=account_info['secret_key']
        )

    def parse_eks_json_file(self, file_path: str) -> Dict:
        """Parse EKS JSON state file"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error parsing {file_path}: {e}")
            return {}

    def parse_ec2_file(self, file_path: str) -> Dict:
        """Parse EC2 JSON state file"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error parsing {file_path}: {e}")
            return {}

    def check_eks_cluster_status(self, cluster_name: str, region: str, account_key: str) -> Dict:
        """Check the current status of an EKS cluster using AWS API"""
        check_time = self.get_current_time_formatted()
        print(f"🔗 Making live AWS API call to check EKS cluster status...")
        print(f"⏰ Check time (UTC): {check_time}")
        
        try:
            eks_client = self.get_aws_client('eks', region, account_key)
            
            cluster_response = eks_client.describe_cluster(name=cluster_name)
            cluster = cluster_response['cluster']
            
            nodegroups_response = eks_client.list_nodegroups(clusterName=cluster_name)
            nodegroup_details = []
            
            for ng_name in nodegroups_response.get('nodegroups', []):
                ng_detail = eks_client.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=ng_name
                )
                nodegroup_details.append(ng_detail['nodegroup'])
            
            return {
                "cluster": cluster,
                "nodegroups": nodegroup_details,
                "status": "success",
                "check_time": check_time
            }
            
        except ClientError as e:
            return {
                "error": str(e),
                "status": "error",
                "check_time": check_time
            }
        except Exception as e:
            return {
                "error": f"Unexpected error: {str(e)}",
                "status": "error",
                "check_time": check_time
            }

    def check_ec2_instance_status(self, instance_id: str, region: str, account_key: str) -> Dict:
        """Check the current status of an EC2 instance using AWS API"""
        check_time = self.get_current_time_formatted()
        print(f"🔗 Making live AWS API call to check EC2 instance status...")
        print(f"⏰ Check time (UTC): {check_time}")
        
        try:
            ec2_client = self.get_aws_client('ec2', region, account_key)
            
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            
            if not response['Reservations']:
                return {
                    "error": f"Instance {instance_id} not found",
                    "status": "not_found",
                    "check_time": check_time
                }
            
            instance = response['Reservations'][0]['Instances'][0]
            
            try:
                cloudwatch_client = self.get_aws_client('cloudwatch', region, account_key)
                print(f"📊 Fetching CloudWatch metrics...")
                cpu_response = cloudwatch_client.get_metric_statistics(
                    Namespace='AWS/EC2',
                    MetricName='CPUUtilization',
                    Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                    StartTime=datetime.now(timezone.utc) - timedelta(minutes=5),
                    EndTime=datetime.now(timezone.utc),
                    Period=300,
                    Statistics=['Average']
                )
                cpu_utilization = cpu_response.get('Datapoints', [])
            except Exception as e:
                print(f"⚠️ Could not fetch CloudWatch metrics: {e}")
                cpu_utilization = []
            
            return {
                "instance": instance,
                "cpu_metrics": cpu_utilization,
                "status": "success",
                "check_time": check_time
            }
            
        except ClientError as e:
            return {
                "error": str(e),
                "status": "error",
                "check_time": check_time
            }
        except Exception as e:
            return {
                "error": f"Unexpected error: {str(e)}",
                "status": "error",
                "check_time": check_time
            }

    def format_creation_time_readable(self, timestamp_str):
        """Format creation timestamp from YYYYMMDD_HHMMSS to readable date and time"""
        try:
            if not timestamp_str or timestamp_str == 'Unknown':
                return "Unknown time"
            
            # Handle YYYYMMDD_HHMMSS format (like "20250602_153150")
            if '_' in timestamp_str and len(timestamp_str) == 15:
                # Parse YYYYMMDD_HHMMSS format
                date_part = timestamp_str[:8]    # "20250602"
                time_part = timestamp_str[9:]    # "153150"
                
                # Extract components
                year = int(date_part[:4])        # 2025
                month = int(date_part[4:6])      # 06
                day = int(date_part[6:8])        # 02
                
                hour = int(time_part[:2])        # 15
                minute = int(time_part[2:4])     # 31
                second = int(time_part[4:6])     # 50
                
                # Create datetime object (assuming IST timezone)
                ist_tz = timezone(timedelta(hours=5, minutes=30))
                dt = datetime(year, month, day, hour, minute, second, tzinfo=ist_tz)
                
                # Format options with date and time:
                
                # Option 1: Jun 02, 2025 at 03:31 PM IST (Recommended - most readable)
                return dt.strftime('%b %d, %Y at %I:%M %p IST')
                
                # Option 2: 2025-06-02 15:31 IST (24-hour format)
                # return dt.strftime('%Y-%m-%d %H:%M IST')
                
                # Option 3: 02/06/2025 03:31 PM IST (DD/MM/YYYY format)
                # return dt.strftime('%d/%m/%Y %I:%M %p IST')
                
                # Option 4: June 2, 2025 03:31 PM IST (Full month name)
                # return dt.strftime('%B %d, %Y %I:%M %p IST')
            
            # Handle other formats (existing logic for ISO timestamps)
            elif isinstance(timestamp_str, str):
                if '+05:30' in timestamp_str or 'IST' in timestamp_str:
                    clean_time = timestamp_str.replace('+05:30', '').replace(' IST', '').strip()
                    dt = datetime.fromisoformat(clean_time)
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    dt = dt.replace(tzinfo=ist_tz)
                else:
                    dt = datetime.fromisoformat(timestamp_str)
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    dt = dt.astimezone(ist_tz)
                
                return dt.strftime('%b %d, %Y at %I:%M %p IST')
            
        except Exception as e:
            print(f"⚠️ Warning: Could not parse timestamp '{timestamp_str}': {e}")
        return "Unknown time"
        
    def display_eks_summary(self, data: Dict, file_path: str = "", show_cost: bool = False, start_number: int = 1) -> List[Tuple]:
        """Display EKS cluster summary from JSON file with continuous numbering"""
        print("\n" + "="*80)
        print("🚀 EKS CLUSTER STATE SUMMARY (FROM JSON FILE)")
        print("="*80)
        
        if file_path:
            print(f"📁 Source file: {file_path}")
        
        metadata = data.get('metadata', {})
        print(f"📅 Created: {metadata.get('created_on', 'Unknown')}")
        print(f"👤 Created by: {metadata.get('created_by', 'Unknown')}")
        print(f"📊 Total clusters: {metadata.get('total_clusters', 0)}")
        
        clusters = data.get('clusters', [])
        cluster_list = []
        total_cost = 0
        
        # Use continuous numbering starting from start_number
        for idx, cluster in enumerate(clusters):
            global_number = start_number + idx  # Global continuous number
            cluster_name = cluster.get('cluster_name', 'Unknown')
            account_key = cluster.get('account_key', 'Unknown')
            region = cluster.get('region', 'Unknown')
            
            creation_time = cluster.get('created_timestamp', 'Unknown')
            formatted_time = self.format_creation_time_readable(creation_time)
            
            print(f"\n🏷️  Cluster {global_number}: {cluster_name}")
            print(f"   🌍 Region: {region}")
            print(f"   🏢 Account: {account_key} ({cluster.get('account_id', 'Unknown')})")
            print(f"   📏 Instance Type: {cluster.get('instance_type', 'Unknown')}")
            print(f"   📈 Max Nodes: {cluster.get('max_nodes', 'Unknown')}")
            print(f"   🔢 Default Nodes: {cluster.get('default_nodes', 'Unknown')}")
            print(f"   💾 Disk Size: {cluster.get('disk_size', 'Unknown')} GB")
            print(f"   📅 Created: {formatted_time}")  # Shows: 12:01 PM IST
            
            if show_cost:
                cost_data = self.cost_calculator.calculate_eks_cost(cluster)
                print(f"   💰 Estimated Cost: ${cost_data['total_cost']:.2f} (for {cost_data['hours_running']:.1f} hours)")
                print(f"      └─ Control Plane: ${cost_data['control_plane_cost']:.2f}")
                print(f"      └─ Node Compute: ${cost_data['node_compute_cost']:.2f}")
                print(f"      └─ Node Storage: ${cost_data['node_storage_cost']:.2f}")
                total_cost += cost_data['total_cost']
            
            # Use global_number in the tuple for proper selection
            cluster_list.append((global_number, cluster_name, account_key, region, cluster))
        
        if show_cost:
            print(f"\n💰 TOTAL EKS COST: ${total_cost:.2f}")
            print(f"⏰ Cost calculated at (UTC): {self.get_current_time_formatted()}")
        
        return cluster_list

    def display_ec2_summary(self, data: Dict, file_path: str = "", show_cost: bool = False, start_number: int = 1) -> List[Tuple]:
        """Display EC2 instance summary from JSON file with continuous numbering"""
        print("\n" + "="*80)
        print("💻 EC2 INSTANCE STATE SUMMARY (FROM JSON FILE)")
        print("="*80)
        
        if file_path:
            print(f"📁 Source file: {file_path}")
        
        metadata = data.get('metadata', {})
        print(f"📅 Created: {metadata.get('creation_date', 'Unknown')} {metadata.get('creation_time', '')}")
        print(f"👤 Created by: {metadata.get('created_by', 'Unknown')}")
        
        summary = data.get('summary', {})
        print(f"📊 Total processed: {summary.get('total_processed', 0)}")
        print(f"✅ Total created: {summary.get('total_created', 0)}")
        
        instances = data.get('created_instances', [])
        instance_list = []
        total_cost = 0
        
        print(f"\n📋 Instance Details ({len(instances)} instances):")
        
        # Use continuous numbering starting from start_number
        for idx, instance in enumerate(instances):
            global_number = start_number + idx  # Global continuous number
            instance_id = instance.get('instance_id', 'Unknown')
            account_name = instance.get('account_name', 'Unknown')
            region = instance.get('region', 'Unknown')
            
            print(f"\n{global_number}. 🖥️  {instance_id}")
            print(f"   🏷️  Type: {instance.get('instance_type', 'Unknown')}")
            print(f"   🌍 Region: {region}")
            print(f"   🏢 Account: {account_name} ({instance.get('account_id', 'Unknown')})")
            print(f"   🌐 Public IP: {instance.get('public_ip', 'None')}")
            print(f"   📊 State: {instance.get('state', 'Unknown')}")
            
            if show_cost:
                cost_data = self.cost_calculator.calculate_ec2_cost(instance)
                print(f"   💰 Estimated Cost: ${cost_data['total_cost']:.2f} (for {cost_data['hours_running']:.1f} hours)")
                print(f"      └─ Compute: ${cost_data['compute_cost']:.2f} ({cost_data['hourly_rate']:.4f}/hr)")
                print(f"      └─ Storage: ${cost_data['storage_cost']:.2f} ({cost_data['disk_size_gb']}GB)")
                total_cost += cost_data['total_cost']
            
            # Use global_number in the tuple for proper selection
            instance_list.append((global_number, instance_id, account_name, region, instance))
        
        if show_cost:
            print(f"\n💰 TOTAL EC2 COST: ${total_cost:.2f}")
            print(f"⏰ Cost calculated at (UTC): {self.get_current_time_formatted()}")
        
        return instance_list

    def interactive_live_lookup(self, resource_type: str):
        """Interactive selection and live lookup of EKS/EC2 resources with continuous numbering"""
        files = self.select_files(resource_type)
        if not files:
            return
            
        all_resources = []
        current_number = 1  # Track continuous numbering across files
        
        # Parse and collect all resources from selected files with continuous numbering
        for file in files:
            if resource_type == 'eks':
                data = self.parse_eks_json_file(file)
                if data:
                    # Pass current_number and get back resources with global numbers
                    resources = self.display_eks_summary(data, file, show_cost=False, start_number=current_number)
                    all_resources.extend(resources)
                    # Update current_number for next file
                    current_number += len(data.get('clusters', []))
            else:
                data = self.parse_ec2_file(file)
                if data:
                    # Pass current_number and get back resources with global numbers
                    resources = self.display_ec2_summary(data, file, show_cost=False, start_number=current_number)
                    all_resources.extend(resources)
                    # Update current_number for next file
                    current_number += len(data.get('created_instances', []))
        
        if not all_resources:
            print(f"❌ No {resource_type} resources found in selected files")
            return
        
        # Show summary of all resources with their global numbers
        print(f"\n📊 SUMMARY: Found {len(all_resources)} {resource_type.upper()} resources across {len(files)} file(s)")
        print("="*80)
        
        # Interactive selection
        print(f"\n🔍 Select {resource_type.upper()} resource(s) for LIVE lookup:")
        print("💡 Options: single number (5), range (1-3), multiple (1,3,5), or 'all' (default)")
        print(f"💡 Available numbers: 1-{len(all_resources)}")
        print("-" * 70)
        
        selection_input = input(f"Select {resource_type.upper()} for live lookup (default=all): ").strip()
        selected_indices = self.parse_selection_input(selection_input, len(all_resources))
        
        if not selected_indices:
            print("❌ No valid selections made")
            return
        
        current_time = self.get_current_time_formatted()
        print(f"\n🔍 LIVE LOOKUP FOR {len(selected_indices)} {resource_type.upper()} RESOURCE(S)")
        print(f"⏰ Lookup time (IST): {current_time}")
        print("="*80)
        
        # Track results for summary
        successful_lookups = 0
        failed_lookups = 0
        not_found_resources = []
        
        # Process each selected resource using global numbers
        for global_num in selected_indices:
            # Find the resource by its global number
            selected_resource = None
            for resource in all_resources:
                if resource[0] == global_num:  # resource[0] is the global number
                    selected_resource = resource
                    break
            
            if not selected_resource:
                print(f"❌ Resource number {global_num} not found")
                continue
            
            try:
                if resource_type == 'eks':
                    global_number, cluster_name, account_key, region, cluster_data = selected_resource
                    
                    print(f"\n🚀 EKS Cluster {global_number}: {cluster_name}")
                    print(f"🏢 Account: {account_key} | 🌍 Region: {region}")
                    
                    # Perform live lookup
                    status_data = self.check_eks_cluster_status(cluster_name, region, account_key)
                    
                    if status_data['status'] == 'error':
                        print(f"❌ LIVE LOOKUP FAILED")
                        print(f"   Error: {status_data['error']}")
                        print(f"   📝 Reason: Cluster found in JSON but not found in live AWS")
                        failed_lookups += 1
                        not_found_resources.append({
                            'type': 'EKS Cluster',
                            'id': cluster_name,
                            'account': account_key,
                            'region': region,
                            'number': global_number
                        })
                    else:
                        print(f"✅ LIVE LOOKUP SUCCESSFUL")
                        cluster = status_data['cluster']
                        print(f"   📊 Status: {cluster['status']}")
                        print(f"   🎯 Version: {cluster['version']}")
                        print(f"   📅 Created: {self.utc_to_ist(str(cluster['createdAt']))} IST")
                        
                        nodegroups = status_data.get('nodegroups', [])
                        if nodegroups:
                            total_nodes = sum([ng.get('scalingConfig', {}).get('desiredSize', 0) for ng in nodegroups])
                            print(f"   🔗 Node Groups: {len(nodegroups)} active with {total_nodes} total nodes")
                        successful_lookups += 1
                    
                    # Add to execution reports
                    self.execution_reports.append({
                        'type': 'eks_status',
                        'resource_id': cluster_name,
                        'global_number': global_number,
                        'status': 'success' if status_data['status'] != 'error' else 'error',
                        'data': status_data,
                        'timestamp': current_time,
                        'total_nodes': sum([ng.get('scalingConfig', {}).get('desiredSize', 0) for ng in status_data.get('nodegroups', [])]) if status_data['status'] != 'error' else 0
                    })
                    
                else:  # EC2
                    global_number, instance_id, account_name, region, instance_data = selected_resource
                    
                    print(f"\n💻 EC2 Instance {global_number}: {instance_id}")
                    print(f"🏢 Account: {account_name} | 🌍 Region: {region}")
                    
                    # Perform live lookup
                    status_data = self.check_ec2_instance_status(instance_id, region, account_name)
                    
                    if status_data['status'] in ['error', 'not_found']:
                        print(f"❌ LIVE LOOKUP FAILED")
                        print(f"   Error: {status_data['error']}")
                        print(f"   📝 Reason: Instance found in JSON but not found in live AWS")
                        failed_lookups += 1
                        not_found_resources.append({
                            'type': 'EC2 Instance',
                            'id': instance_id,
                            'account': account_name,
                            'region': region,
                            'number': global_number
                        })
                    else:
                        print(f"✅ LIVE LOOKUP SUCCESSFUL")
                        instance = status_data['instance']
                        print(f"   🏷️ Type: {instance['InstanceType']}")
                        print(f"   📊 State: {instance['State']['Name']}")
                        print(f"   🌐 Public IP: {instance.get('PublicIpAddress', 'None')}")
                        print(f"   📅 Launch Time: {self.utc_to_ist(str(instance['LaunchTime']))} IST")
                        
                        cpu_metrics = status_data.get('cpu_metrics', [])
                        if cpu_metrics:
                            latest_cpu = cpu_metrics[-1]['Average']
                            print(f"   💹 CPU Utilization: {latest_cpu:.2f}%")
                        successful_lookups += 1
                    
                    # Add to execution reports
                    self.execution_reports.append({
                        'type': 'ec2_status',
                        'resource_id': instance_id,
                        'global_number': global_number,
                        'status': 'success' if status_data['status'] not in ['error', 'not_found'] else 'error',
                        'data': status_data,
                        'timestamp': current_time
                    })
                    
            except Exception as e:
                print(f"❌ UNEXPECTED ERROR during lookup of resource {global_num}")
                print(f"   Error: {str(e)}")
                print(f"   📝 Continuing with next resource...")
                failed_lookups += 1
                continue
        
        # Final summary
        print(f"\n" + "="*80)
        print(f"📊 LIVE LOOKUP SUMMARY")
        print(f"⏰ Completed at (IST): {current_time}")
        print(f"✅ Successful lookups: {successful_lookups}")
        print(f"❌ Failed lookups: {failed_lookups}")
        print(f"📊 Total processed: {len(selected_indices)}")
        
        # Show resources not found in live AWS with their numbers
        if not_found_resources:
            print(f"\n⚠️ RESOURCES NOT FOUND IN LIVE AWS:")
            print("-" * 50)
            for resource in not_found_resources:
                print(f"📝 #{resource['number']} {resource['type']}: {resource['id']} (Account: {resource['account']}, Region: {resource['region']})")
        else:
            print(f"\n✅ All resources successfully found in live AWS")
        
        # Save consolidated report
        saved_file = self.save_consolidated_execution_report('live_lookup', resource_type)
        if saved_file:
            print(f"📄 Consolidated execution report saved to: {saved_file}")
        
        print("="*80)


    def display_live_eks_status(self, cluster_name: str, region: str, account_key: str):
        """Display live EKS cluster status using AWS API calls - IMPROVED with node details"""
        print(f"\n🔍 LIVE EKS CLUSTER STATUS (AWS API)")
        print(f"🎯 Cluster: {cluster_name}")
        print(f"🌍 Region: {region}")
        print(f"🏢 Account: {account_key}")
        print("-" * 60)
        
        current_time = self.get_current_time_formatted()
        status_data = self.check_eks_cluster_status(cluster_name, region, account_key)
        
        if status_data['status'] == 'error':
            print(f"❌ Error: {status_data['error']}")
            print(f"⏰ Check completed at (IST): {status_data['check_time']}")
            
            # Add to execution reports for consolidated saving
            self.execution_reports.append({
                'type': 'eks_status',
                'resource_id': cluster_name,
                'status': 'error',
                'data': status_data,
                'timestamp': current_time
            })
            return
        
        cluster = status_data['cluster']
        print(f"✅ Successfully retrieved live cluster data!")
        print(f"⏰ Data retrieved at (IST): {status_data['check_time']}")
        print(f"🏷️  Cluster Name: {cluster['name']}")
        print(f"📊 Status: {cluster['status']}")
        print(f"🎯 Version: {cluster['version']}")
        print(f"🔗 Endpoint: {cluster['endpoint']}")
        print(f"📅 Created: {self.utc_to_ist(str(cluster['createdAt']))} IST")
        
        nodegroups = status_data.get('nodegroups', [])
        if nodegroups:
            total_nodes = 0
            print(f"\n📋 Node Groups ({len(nodegroups)}):")
            for ng in nodegroups:
                scaling = ng.get('scalingConfig', {})
                desired_nodes = scaling.get('desiredSize', 0)
                total_nodes += desired_nodes
                
                print(f"  • {ng['nodegroupName']}: {ng['status']}")
                print(f"    - Instance Types: {', '.join(ng.get('instanceTypes', []))}")
                print(f"    - Scaling: Min={scaling.get('minSize', 0)}, "
                    f"Max={scaling.get('maxSize', 0)}, "
                    f"Desired={desired_nodes}")
                if 'createdAt' in ng:
                    print(f"    - Created: {self.utc_to_ist(str(ng['createdAt']))} IST")
            
            print(f"\n🔢 Total Active Nodes: {total_nodes}")
        else:
            print(f"\n📋 No node groups found")
        
        # Add to execution reports for consolidated saving
        self.execution_reports.append({
            'type': 'eks_status',
            'resource_id': cluster_name,
            'status': 'success',
            'data': status_data,
            'timestamp': current_time,
            'total_nodes': total_nodes if nodegroups else 0
        })

    def display_live_ec2_status(self, instance_id: str, region: str, account_key: str):
        """Display live EC2 instance status using AWS API calls"""
        print(f"\n🔍 LIVE EC2 INSTANCE STATUS (AWS API)")
        print(f"🎯 Instance: {instance_id}")
        print(f"🌍 Region: {region}")
        print(f"🏢 Account: {account_key}")
        print("-" * 60)
        
        current_time = self.get_current_time_formatted()
        status_data = self.check_ec2_instance_status(instance_id, region, account_key)
        
        if status_data['status'] in ['error', 'not_found']:
            print(f"❌ Error: {status_data['error']}")
            print(f"⏰ Check completed at (IST): {status_data['check_time']}")
            
            # Add to execution reports for consolidated saving
            self.execution_reports.append({
                'type': 'ec2_status',
                'resource_id': instance_id,
                'status': 'error',
                'data': status_data,
                'timestamp': current_time
            })
            return
        
        instance = status_data['instance']
        print(f"✅ Successfully retrieved live instance data!")
        print(f"⏰ Data retrieved at (IST): {status_data['check_time']}")
        print(f"🖥️  Instance ID: {instance['InstanceId']}")
        print(f"🏷️  Instance Type: {instance['InstanceType']}")
        print(f"📊 State: {instance['State']['Name']} (CURRENT)")
        print(f"🌐 Public IP: {instance.get('PublicIpAddress', 'None')}")
        print(f"🔒 Private IP: {instance.get('PrivateIpAddress', 'None')}")
        print(f"📅 Launch Time: {self.utc_to_ist(str(instance['LaunchTime']))} IST")
        
        cpu_metrics = status_data.get('cpu_metrics', [])
        if cpu_metrics:
            latest_cpu = cpu_metrics[-1]['Average']
            print(f"💹 Latest CPU Utilization: {latest_cpu:.2f}%")
        
        # Add to execution reports for consolidated saving
        self.execution_reports.append({
            'type': 'ec2_status',
            'resource_id': instance_id,
            'status': 'success',
            'data': status_data,
            'timestamp': current_time
        })
    
    def find_resource_in_files(self, resource_id: str, resource_type: str) -> Optional[Tuple[str, str, str]]:
        """Find a resource in state files and return account_key and region"""
        if resource_type.lower() == 'eks':
            patterns = [
                "eks_cluster_created_*.json",
                "eks_clusters_created_*.json"
            ]
        else:
            patterns = [
                "ec2_instance_report_*.json",
                "ec2_instances_report_*.json",
                "ec2_report_*.json"
            ]
        
        json_files = self.find_state_files(patterns)
        for file_path, _ in json_files:
            if resource_type.lower() == 'eks':
                data = self.parse_eks_json_file(file_path)
                for cluster in data.get('clusters', []):
                    if cluster.get('cluster_name') == resource_id:
                        return cluster.get('account_key'), cluster.get('region'), file_path
            else:
                data = self.parse_ec2_file(file_path)
                for instance in data.get('created_instances', []):
                    if instance.get('instance_id') == resource_id:
                        return instance.get('account_name'), instance.get('region'), file_path
        
        return None

    def direct_resource_lookup(self, resource_id: str):
        """Perform direct lookup for a resource with LIVE AWS API calls"""
        resource_type = self.detect_resource_type(resource_id)
        
        print(f"🔍 Detected resource type: {resource_type.upper()}")
        print(f"🎯 Looking up resource: {resource_id}")
        
        result = self.find_resource_in_files(resource_id, resource_type)
        
        if result:
            account_key, region, file_path = result
            print(f"✅ Found {resource_type} resource in: {file_path}")
            
            if resource_type == 'eks':
                self.display_live_eks_status(resource_id, region, account_key)
            else:
                self.display_live_ec2_status(resource_id, region, account_key)
            
            # Save consolidated report
            self.save_consolidated_execution_report('direct_lookup', resource_type)
        else:
            print(f"❌ {resource_type.upper()} resource '{resource_id}' not found in state files")
            
    def create_output_folders(self, folder_type: str) -> str:
        """Create folder structure for saving files"""
        try:
            # Get current date in YYYYMMDD format
            current_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%Y%m%d')
            
            # Create folder path: livecost/20250603 or livestatus/20250603
            folder_path = os.path.join(folder_type, current_date)
            
            # Create folders if they don't exist
            os.makedirs(folder_path, exist_ok=True)
            
            return folder_path
            
        except Exception as e:
            print(f"⚠️ Warning: Could not create folder structure: {e}")
            print(f"📁 Files will be saved in current directory")
            return "."

    def save_consolidated_execution_report(self, operation_type: str, resource_type: str):
        """Save consolidated report for entire execution - IMPROVED"""
        if not self.execution_reports:
            print("⚠️ No reports to save")
            return
        
        try:
            # Create appropriate folder structure
            if operation_type in ['live_cost', 'cost_calculation']:
                folder_path = self.create_output_folders("livecost")
            else:
                folder_path = self.create_output_folders("livestatus")
            
            # Generate filename with timestamp
            timestamp = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%Y%m%d_%H%M%S')
            filename = f"{resource_type}_{operation_type}_execution_report_{timestamp}.txt"
            full_path = os.path.join(folder_path, filename)
            
            current_time = self.get_current_time_formatted()
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(f"AWS {resource_type.upper()} {operation_type.upper()} EXECUTION REPORT\n")
                f.write("="*70 + "\n")
                f.write(f"Generated at (IST): {current_time}\n")
                f.write(f"Operation Type: {operation_type.upper()}\n")
                f.write(f"Resource Type: {resource_type.upper()}\n")
                f.write(f"User: varadharajaan\n")
                f.write(f"Total Resources Processed: {len(self.execution_reports)}\n\n")
                
                # Summary statistics
                successful_count = len([r for r in self.execution_reports if r['status'] == 'success'])
                error_count = len([r for r in self.execution_reports if r['status'] == 'error'])
                
                f.write("EXECUTION SUMMARY:\n")
                f.write("-"*30 + "\n")
                f.write(f"✅ Successful: {successful_count}\n")
                f.write(f"❌ Errors/Not Found: {error_count}\n")
                f.write(f"📊 Total: {len(self.execution_reports)}\n\n")
                
                # Detailed results
                f.write("DETAILED RESULTS:\n")
                f.write("="*50 + "\n")
                
                for i, report in enumerate(self.execution_reports, 1):
                    f.write(f"\n{i}. Resource: {report['resource_id']}\n")
                    f.write(f"   Status: {'✅ SUCCESS' if report['status'] == 'success' else '❌ ERROR'}\n")
                    f.write(f"   Timestamp: {report['timestamp']}\n")
                    
                    if report['status'] == 'success':
                        if report['type'] == 'eks_status':
                            f.write(f"   Total Nodes: {report.get('total_nodes', 'Unknown')}\n")
                        elif report['type'] == 'eks_cost':
                            cost_data = report.get('cost_data', {})
                            f.write(f"   Total Cost: ${cost_data.get('total_cost', 0):.2f}\n")
                            f.write(f"   Running Hours: {cost_data.get('hours_running', 0):.2f}\n")
                        elif report['type'] == 'ec2_cost':
                            cost_data = report.get('cost_data', {})
                            f.write(f"   Total Cost: ${cost_data.get('total_cost', 0):.2f}\n")
                            f.write(f"   Running Hours: {cost_data.get('hours_running', 0):.2f}\n")
                    else:
                        error_msg = report.get('data', {}).get('error', 'Unknown error')
                        f.write(f"   Error: {error_msg}\n")
                    
                    f.write("-"*40 + "\n")
                
                # Cost summary if applicable
                if operation_type in ['live_cost', 'cost_calculation']:
                    total_cost = sum([r.get('cost_data', {}).get('total_cost', 0) for r in self.execution_reports if r['status'] == 'success'])
                    f.write(f"\nGRAND TOTAL COST: ${total_cost:.2f}\n")
                
                f.write(f"\nReport generated at (IST): {current_time}\n")
            
            print(f"\n💾 Consolidated execution report saved to: {full_path}")
            
            # Clear reports for next execution
            self.execution_reports = []
            
            return full_path
            
        except Exception as e:
            print(f"❌ Error saving consolidated report: {e}")
            return None
        
    def calculate_resource_costs(self, resource_type: str):
        """Calculate and display LIVE costs for selected resources with continuous numbering"""
        files = self.select_files(resource_type)
        if not files:
            return
            
        all_resources = []
        current_number = 1  # Track continuous numbering across files
        
        # Parse and collect all resources from selected files with continuous numbering
        for file in files:
            if resource_type == 'eks':
                data = self.parse_eks_json_file(file)
                if data:
                    # Pass current_number and get back resources with global numbers
                    resources = self.display_eks_summary(data, file, show_cost=False, start_number=current_number)
                    all_resources.extend(resources)
                    # Update current_number for next file
                    current_number += len(data.get('clusters', []))
            else:
                data = self.parse_ec2_file(file)
                if data:
                    # Pass current_number and get back resources with global numbers
                    resources = self.display_ec2_summary(data, file, show_cost=False, start_number=current_number)
                    all_resources.extend(resources)
                    # Update current_number for next file
                    current_number += len(data.get('created_instances', []))
        
        if not all_resources:
            return
        
        # Show summary of all resources with their global numbers
        print(f"\n📊 SUMMARY: Found {len(all_resources)} {resource_type.upper()} resources across {len(files)} file(s)")
        print("="*80)
        
        print(f"\n💰 Select {resource_type.upper()} resource(s) for LIVE COST calculation:")
        print("💡 Options: single number (5), range (1-3), multiple (1,3,5), or 'all' (default)")
        print("📊 This will fetch LIVE AWS data for accurate cost calculation")
        print(f"💡 Available numbers: 1-{len(all_resources)}")
        print("-" * 70)
        
        selection_input = input(f"Select {resource_type.upper()} for live cost calculation (default=all): ").strip()
        selected_indices = self.parse_selection_input(selection_input, len(all_resources))
        
        if not selected_indices:
            print("❌ No valid selections made")
            return
        
        current_time = self.get_current_time_formatted()
        print(f"\n💰 LIVE COST CALCULATION FOR {len(selected_indices)} {resource_type.upper()} RESOURCE(S)")
        print(f"⏰ Calculation time (IST): {current_time}")
        print("="*80)
        
        # Group resources by account using global numbers
        account_groups = {}
        account_costs = {}
        total_cost = 0
        skipped_resources = 0
        successful_resources = 0
        
        # Find selected resources by global numbers and group by account
        for global_num in selected_indices:
            # Find the resource by its global number
            selected_resource = None
            for resource in all_resources:
                if resource[0] == global_num:  # resource[0] is the global number
                    selected_resource = resource
                    break
            
            if not selected_resource:
                print(f"❌ Resource number {global_num} not found")
                continue
            
            if resource_type == 'eks':
                global_number, cluster_name, account_key, region, cluster_data = selected_resource
                account_name = account_key
            else:
                global_number, instance_id, account_name, region, instance_data = selected_resource
            
            if account_name not in account_groups:
                account_groups[account_name] = {
                    'resources': [],
                    'total_cost': 0,
                    'count': 0
                }
                account_costs[account_name] = 0
            
            account_groups[account_name]['resources'].append(selected_resource)
            account_groups[account_name]['count'] += 1
        
        # Process each account group
        for account_name, group_data in account_groups.items():
            print(f"\n🏢 ACCOUNT: {account_name}")
            print("="*60)
            account_cost = 0
            account_successful = 0
            account_skipped = 0
            
            for selected_resource in group_data['resources']:
                if resource_type == 'eks':
                    global_number, cluster_name, account_key, region, cluster_data = selected_resource
                    
                    try:
                        # Get live cluster data
                        print(f"\n🔍 Fetching live data for EKS cluster: {cluster_name}")
                        live_status = self.check_eks_cluster_status(cluster_name, region, account_key)
                        
                        if live_status['status'] == 'error':
                            print(f"⚠️ SKIPPED - EKS Cluster {global_number}: {cluster_name}")
                            print(f"   ❌ Error: {live_status['error']}")
                            print(f"   📝 Reason: Cluster not found in live AWS or access denied")
                            skipped_resources += 1
                            account_skipped += 1
                            
                            # Add to execution reports for skipped resources
                            self.execution_reports.append({
                                'type': 'eks_cost',
                                'resource_id': cluster_name,
                                'global_number': global_number,
                                'status': 'error',
                                'data': live_status,
                                'timestamp': current_time,
                                'cost_data': {'total_cost': 0}
                            })
                            continue
                        
                        live_cluster_data = None
                        if live_status['status'] == 'success':
                            live_cluster_data = live_status['cluster']
                            live_cluster_data['nodegroups'] = live_status.get('nodegroups', [])
                        
                        cost_data = self.cost_calculator.calculate_live_eks_cost(cluster_data, live_cluster_data)
                        
                        # Calculate total nodes for display
                        total_nodes = cost_data['actual_nodes']
                        
                        print(f"\n🚀 EKS Cluster {global_number}: {cluster_name}")
                        print(f"   🌍 Region: {region}")
                        print(f"   📊 Status: {cost_data.get('current_status', 'unknown')}")
                        print(f"   📅 Created: {self.utc_to_ist(str(live_cluster_data.get('createdAt', 'Unknown') if live_cluster_data else 'Unknown'))} IST")
                        print(f"   ⏰ Running Hours: {cost_data['hours_running']:.2f}")
                        print(f"   🔢 Total Nodes: {total_nodes}")
                        print(f"   🎛️ Control Plane: ${cost_data['control_plane_cost']:.2f} (${self.cost_calculator.EKS_CLUSTER_HOURLY_COST:.2f}/hr)")
                        print(f"   🖥️ Node Compute: ${cost_data['node_compute_cost']:.2f} ({total_nodes} × {cost_data['instance_type']})")
                        print(f"   💾 Node Storage: ${cost_data['node_storage_cost']:.2f} ({cost_data['disk_size_gb']}GB per node)")
                        print(f"   💰 Total Cost: ${cost_data['total_cost']:.2f}")
                        print(f"   ⏰ Calculated at: {cost_data['calculation_time'].astimezone(timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M:%S')} IST")
                        
                        account_cost += cost_data['total_cost']
                        successful_resources += 1
                        account_successful += 1
                        
                        # Add to execution reports for successful resources
                        self.execution_reports.append({
                            'type': 'eks_cost',
                            'resource_id': cluster_name,
                            'global_number': global_number,
                            'status': 'success',
                            'data': live_status,
                            'timestamp': current_time,
                            'cost_data': cost_data,
                            'total_nodes': total_nodes
                        })
                        
                    except Exception as e:
                        print(f"⚠️ SKIPPED - EKS Cluster {global_number}: {cluster_name}")
                        print(f"   ❌ Unexpected error: {str(e)}")
                        print(f"   📝 Continuing with next resource...")
                        skipped_resources += 1
                        account_skipped += 1
                        
                        # Add to execution reports for error resources
                        self.execution_reports.append({
                            'type': 'eks_cost',
                            'resource_id': cluster_name,
                            'global_number': global_number,
                            'status': 'error',
                            'data': {'error': str(e)},
                            'timestamp': current_time,
                            'cost_data': {'total_cost': 0}
                        })
                        continue
                    
                else:  # EC2
                    global_number, instance_id, account_name_inner, region, instance_data = selected_resource
                    
                    try:
                        # Get live instance data
                        print(f"\n🔍 Fetching live data for EC2 instance: {instance_id}")
                        live_status = self.check_ec2_instance_status(instance_id, region, account_name_inner)
                        
                        if live_status['status'] in ['error', 'not_found']:
                            print(f"⚠️ SKIPPED - EC2 Instance {global_number}: {instance_id}")
                            print(f"   ❌ Error: {live_status['error']}")
                            print(f"   📝 Reason: Instance not found in live AWS or access denied")
                            skipped_resources += 1
                            account_skipped += 1
                            
                            # Add to execution reports for skipped resources
                            self.execution_reports.append({
                                'type': 'ec2_cost',
                                'resource_id': instance_id,
                                'global_number': global_number,
                                'status': 'error',
                                'data': live_status,
                                'timestamp': current_time,
                                'cost_data': {'total_cost': 0}
                            })
                            continue
                        
                        live_instance_data = None
                        if live_status['status'] == 'success':
                            live_instance_data = live_status['instance']
                        
                        cost_data = self.cost_calculator.calculate_live_ec2_cost(instance_data, live_instance_data)
                        
                        print(f"\n💻 EC2 Instance {global_number}: {instance_id}")
                        print(f"   🌍 Region: {region}")
                        print(f"   🏷️ Type: {cost_data['instance_type']} | 📊 State: {cost_data.get('current_state', 'unknown')}")
                        print(f"   📅 Launch Time: {self.utc_to_ist(str(live_instance_data.get('LaunchTime', 'Unknown') if live_instance_data else 'Unknown'))} IST")
                        print(f"   ⏰ Running Hours: {cost_data['hours_running']:.2f}")
                        print(f"   🖥️ Compute: ${cost_data['compute_cost']:.2f} (${cost_data['hourly_rate']:.4f}/hr)")
                        print(f"   💾 Storage: ${cost_data['storage_cost']:.2f} ({cost_data['disk_size_gb']}GB)")
                        print(f"   💰 Total Cost: ${cost_data['total_cost']:.2f}")
                        print(f"   ⏰ Calculated at: {cost_data['calculation_time'].astimezone(timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M:%S')} IST")
                        
                        account_cost += cost_data['total_cost']
                        successful_resources += 1
                        account_successful += 1
                        
                        # Add to execution reports for successful resources
                        self.execution_reports.append({
                            'type': 'ec2_cost',
                            'resource_id': instance_id,
                            'global_number': global_number,
                            'status': 'success',
                            'data': live_status,
                            'timestamp': current_time,
                            'cost_data': cost_data
                        })
                        
                    except Exception as e:
                        print(f"⚠️ SKIPPED - EC2 Instance {global_number}: {instance_id}")
                        print(f"   ❌ Unexpected error: {str(e)}")
                        print(f"   📝 Continuing with next resource...")
                        skipped_resources += 1
                        account_skipped += 1
                        
                        # Add to execution reports for error resources
                        self.execution_reports.append({
                            'type': 'ec2_cost',
                            'resource_id': instance_id,
                            'global_number': global_number,
                            'status': 'error',
                            'data': {'error': str(e)},
                            'timestamp': current_time,
                            'cost_data': {'total_cost': 0}
                        })
                        continue
            
            # Store the actual calculated cost
            account_costs[account_name] = account_cost
            
            # Account summary with success/skip counts
            print(f"\n💰 ACCOUNT {account_name} TOTAL: ${account_cost:.2f}")
            print(f"📊 Resources in this account: {group_data['count']} {resource_type.upper()} (✅ {account_successful} successful, ⚠️ {account_skipped} skipped)")
            print("-"*60)
            
            total_cost += account_cost
        
        # Grand total summary with error statistics
        print(f"\n" + "="*80)
        print(f"💰 GRAND TOTAL COST (ALL ACCOUNTS): ${total_cost:.2f}")
        print(f"🏢 Number of accounts: {len(account_groups)}")
        print(f"📊 Total {resource_type.upper()} resources: {len(selected_indices)}")
        print(f"✅ Successfully processed: {successful_resources}")
        print(f"⚠️ Skipped (not found/error): {skipped_resources}")
        print(f"⏰ Calculation completed at (IST): {current_time}")
        
        # Account breakdown summary using actual calculated costs
        print(f"\n📋 COST BREAKDOWN BY ACCOUNT:")
        for account_name in account_groups.keys():
            account_total = account_costs[account_name]  # Use stored actual costs
            percentage = (account_total / total_cost * 100) if total_cost > 0 else 0
            print(f"   🏢 {account_name}: ${account_total:.2f} ({percentage:.1f}%) - {account_groups[account_name]['count']} resources")
        
        # Save consolidated execution report instead of individual files            
        if self.execution_reports:
            saved_file = self.save_consolidated_execution_report('live_cost', resource_type)
            if saved_file:
                print(f"\n📄 Consolidated cost calculation report saved to: {saved_file}")
            else:
                print("\n⚠️ No cost calculation report saved")
        
        print("="*80)
        
    def ask_resource_type(self):
        """Main interactive menu"""
        print(f"\n🚀 AWS Resource Manager")
        print(f"Current Date and Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"👤 Current User: varadharajaan")
        print("=" * 60)
        
        while True:
            print("\n📋 Select operation:")
            print("1. 🚀 EKS Clusters (metadata + optional live lookup)")
            print("2. 💻 EC2 Instances (metadata + optional live lookup)")
            print("3. 💰 EKS Live Cost Calculator (fetches current AWS data)")
            print("4. 💰 EC2 Live Cost Calculator (fetches current AWS data)")
            print("5. 🔍 Direct live lookup (provide resource ID)")
            print("6. 🚪 Exit")
            
            choice = input("\nSelect option (1-6): ").strip()
            
            if choice == '1':
                print("\n🚀 Processing EKS state files...")
                self.interactive_live_lookup('eks')
                break
                        
            elif choice == '2':
                print("\n💻 Processing EC2 state files...")
                self.interactive_live_lookup('ec2')
                break
            
            elif choice == '3':
                print("\n💰 EKS Live Cost Calculator...")
                print("📊 This will fetch live AWS data for accurate cost calculation")
                self.calculate_resource_costs('eks')
                break
                
            elif choice == '4':
                print("\n💰 EC2 Live Cost Calculator...")
                print("📊 This will fetch live AWS data for accurate cost calculation")
                self.calculate_resource_costs('ec2')
                break
            
            elif choice == '5':
                resource_id = input("\nEnter resource ID (cluster name or instance ID): ").strip()
                if resource_id:
                    self.direct_resource_lookup(resource_id)
                else:
                    print("❌ No resource ID provided")
                break
                        
            elif choice == '6':
                print("👋 Goodbye!")
                sys.exit(0)
            else:
                print("❌ Invalid option, please try again")

def main():
    parser = argparse.ArgumentParser(
        description='AWS Resource Manager with Live Cost Calculator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
python ec2_eks_lookup_resource.py i-0ea27a17f321529f1    # Direct EC2 lookup
python ec2_eks_lookup_resource.py eks-cluster-name       # Direct EKS lookup  
python ec2_eks_lookup_resource.py                        # Interactive mode
        """
    )
    
    parser.add_argument('resource_id', nargs='?', help='Resource ID for direct lookup')
    parser.add_argument('--config', default='aws_accounts_config.json', 
                    help='AWS configuration file path')
    
    args = parser.parse_args()
    
    manager = AWSResourceManager(args.config)
    
    if args.resource_id:
        manager.direct_resource_lookup(args.resource_id)
    else:
        manager.ask_resource_type()

if __name__ == "__main__":
    main()
# Example usage:

# EKS Flow:
# 📄 Read EKS JSON → Extract cluster_name, region, account_key
# 🔑 Look up account_key in aws_accounts_config.json → Get ROOT credentials
# 🔗 Connect to AWS using ROOT creds → Make live API calls
# EC2 Flow:
# 📄 Read EC2 JSON → Extract instance_id, region, account_name
# 🔑 Look up account_name in aws_accounts_config.json → Get ROOT credentials
# 🔗 Connect to AWS using ROOT creds → Make live API calls
    
# Direct EC2 instance lookup
# python ec2_eks_lookup_resource.py i-0ea27a17f321529f1

# Direct EKS cluster lookup  
# python ec2_eks_lookup_resource.py eks-cluster-account05_clouduser03-us-west-1-zdxr

# Interactive mode (no arguments)
# python ec2_eks_lookup_resource.py

# Using custom config file with direct lookup
# python ec2_eks_lookup_resource.py i-0ea27a17f321529f1 --config my_aws_config.json

# Interactive mode with custom config
# python ec2_eks_lookup_resource.py --config my_aws_config.json