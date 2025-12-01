"""
Enhanced Spot Instance Analyzer with Dynamic Quota Fetching
Refactored for maintainability, reduced hardcoding, and improved caching/logging.
"""

import os
import json
import hashlib
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import boto3
import statistics
import requests
import re

from aws_credential_manager import CredentialInfo

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
@dataclass
class SpotAnalysis:
    instance_type: str
    region: str
    availability_zone: str
    current_price: float
    price_history_avg: float
    interruption_rate: str
    quota_available: int
    score: float
    last_updated: str

@dataclass
class ServiceQuotaInfo:
    instance_family: str
    quota_name: str
    quota_value: int
    quota_limit: int
    current_usage: int
    available_capacity: int
    unit: str
    region: str

class SpotInstanceAnalyzer:
    def __init__(self, region='us-east-1', cache_dir='cache', cache_ttl_hours=24):
        self.region = region
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_ttl_hours = cache_ttl_hours
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        self.credentials = None

    def set_credentials(self, credentials: CredentialInfo):
        """Set AWS credentials and create a boto3 session"""
        self.credentials = credentials
        self.region = credentials.regions[0]
    
        # Create boto3 session
        self.session = boto3.Session(
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            region_name=self.region
        )
    
        logger.info(f"Credentials set for region: {self.region}")

    def _get_current_ist_time(self):
        return datetime.now(self.ist_tz)

    def _get_instance_types_hash(self, instance_types: List[str]) -> str:
        return hashlib.md5('_'.join(sorted(instance_types)).encode()).hexdigest()[:8]

    def _get_cache_filename(self, data_type: str, instance_types_hash: str) -> Path:
        return self.cache_dir / f"{data_type}_{self.region}_{instance_types_hash}.json"

    def _is_cache_valid(self, cache_file: Path) -> bool:
        if not cache_file.exists():
            return False
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            cache_time = datetime.fromisoformat(cache_data.get('timestamp', ''))
            if cache_time.tzinfo:
                cache_time_ist = cache_time.astimezone(self.ist_tz)
            else:
                cache_time_ist = self.ist_tz.localize(cache_time)
            current_time_ist = self._get_current_ist_time()
            return current_time_ist - cache_time_ist < timedelta(hours=self.cache_ttl_hours)
        except Exception as e:
            logger.warning(f"Cache validation error: {e}")
            return False

    def _save_to_cache(self, data, cache_file: Path, created_by="system"):
        cache_data = {
            'timestamp': self._get_current_ist_time().isoformat(),
            'created_by': created_by,
            'region': self.region,
            'timezone': 'Asia/Kolkata',
            'data': data
        }
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        logger.info(f"Data cached to {cache_file}")

    def _load_from_cache(self, cache_file: Path):
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        return cache_data['data']

    def invalidate_cache(self):
        """Invalidate cache files"""
        import glob
        import os
    
        cache_files = glob.glob("*_cache_*.pkl")
        for cache_file in cache_files:
            try:
                os.remove(cache_file)
                print(f"[DELETE] Removed cache file: {cache_file}")
            except Exception as e:
                print(f"[WARN] Error removing cache file {cache_file}: {e}")

    def get_service_quotas(self, instance_types: List[str], created_by="system") -> Dict[str, Dict]:
        instance_types_hash = self._get_instance_types_hash(instance_types)
        cache_file = self._get_cache_filename('quotas', instance_types_hash)
        if self._is_cache_valid(cache_file):
            logger.info("Loading service quotas from cache")
            return self._load_from_cache(cache_file)

        logger.info("Fetching service quotas from AWS API")
        service_quotas = boto3.client(
            'service-quotas',
            region_name=self.region,
            aws_access_key_id=getattr(self.credentials, 'access_key', None),
            aws_secret_access_key=getattr(self.credentials, 'secret_key', None)
        )

        instance_families = set([itype.split('.')[0] for itype in instance_types])
        quotas_by_family = {}

        try:
            response = service_quotas.list_service_quotas(ServiceCode='ec2')
        except Exception as e:
            logger.error(f"Error fetching service quotas: {e}")
            return {"error": str(e)}

        for quota in response.get('Quotas', []):
            name = quota['QuotaName'].lower()
            for family in instance_families:
                if family in name and 'spot' in name:
                    quotas_by_family[family] = {
                        'QuotaName': quota['QuotaName'],
                        'QuotaValue': int(quota['Value']),
                        'Unit': quota.get('Unit', 'None')
                    }

        # Use default quota of 32 for families not found
        for family in instance_families:
            if family not in quotas_by_family:
                quotas_by_family[family] = {
                    'QuotaName': f"Default {family.upper()} Spot Instance Requests",
                    'QuotaValue': 32,  # Changed from 10 to 32
                    'Unit': 'None'
                }

        self._save_to_cache(quotas_by_family, cache_file, created_by)
        return quotas_by_family

    def get_current_usage(self, instance_types: List[str], created_by="system") -> Dict[str, int]:
        instance_types_hash = self._get_instance_types_hash(instance_types)
        cache_file = self._get_cache_filename('usage', instance_types_hash)
        if self._is_cache_valid(cache_file):
            logger.info("Loading current usage from cache")
            return self._load_from_cache(cache_file)

        logger.info("Fetching current instance usage from AWS")
        ec2_client = boto3.client(
            'ec2',
            region_name=self.region,
            aws_access_key_id=getattr(self.credentials, 'access_key', None),
            aws_secret_access_key=getattr(self.credentials, 'secret_key', None)
        )

        instance_families = set([itype.split('.')[0] for itype in instance_types])
        usage_by_family = {family: 0 for family in instance_families}

        try:
            response = ec2_client.describe_instances(
                Filters=[
                    {'Name': 'instance-state-name', 'Values': ['running', 'pending', 'stopping']}
                ]
            )
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    instance_type = instance.get('InstanceType', '')
                    family = instance_type.split('.')[0]
                    if family in usage_by_family:
                        usage_by_family[family] += 1
            for family, count in usage_by_family.items():
                logger.info(f"{family}: {count} instances currently running")
        except Exception as e:
            logger.warning(f"Error fetching current usage: {e}")
            return usage_by_family

        self._save_to_cache(usage_by_family, cache_file, created_by)
        return usage_by_family

    def analyze_service_quotas(self, cred_info: CredentialInfo, instance_types: List[str], force_refresh: bool = False) -> Dict[str, ServiceQuotaInfo]:
        self.set_credentials(cred_info)
        instance_types_hash = self._get_instance_types_hash(instance_types)
        quota_cache_file = self._get_cache_filename('quotas', instance_types_hash)
        usage_cache_file = self._get_cache_filename('usage', instance_types_hash)

        if force_refresh:
            if quota_cache_file.exists():
                quota_cache_file.unlink()
            if usage_cache_file.exists():
                usage_cache_file.unlink()

        quotas_by_family = self.get_service_quotas(instance_types, getattr(cred_info, 'username', 'system'))
        usage_by_family = self.get_current_usage(instance_types, getattr(cred_info, 'username', 'system'))

        quota_info = {}
        for family, quota_data in quotas_by_family.items():
            current_usage = usage_by_family.get(family, 0)
            quota_value = quota_data.get('QuotaValue', 32)  # Changed default from 10 to 32
            available_capacity = max(0, quota_value - current_usage)
            quota_info[family] = ServiceQuotaInfo(
                instance_family=family,
                quota_name=quota_data.get('QuotaName', f'Default {family} quota'),
                quota_value=quota_value,
                quota_limit=quota_value,
                current_usage=current_usage,
                available_capacity=available_capacity,
                unit=quota_data.get('Unit', 'None'),
                region=self.region
            )
            logger.info(f"{family}: {current_usage}/{quota_value} used, {available_capacity} available")
        return quota_info

    def get_current_spot_price(self, ec2_client, instance_type: str, availability_zone: str) -> float:
        try:
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                AvailabilityZone=availability_zone,
                ProductDescriptions=['Linux/UNIX'],
                MaxResults=1
            )
            if response['SpotPriceHistory']:
                return float(response['SpotPriceHistory'][0]['SpotPrice'])
            else:
                return 0.0
        except Exception as e:
            logger.warning(f"Error getting spot price for {instance_type} in {availability_zone}: {e}")
            return 0.0

    def get_price_history_average(self, ec2_client, instance_type: str, availability_zone: str, days: int = 7) -> float:
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                AvailabilityZone=availability_zone,
                ProductDescriptions=['Linux/UNIX'],
                StartTime=start_time,
                EndTime=end_time,
                MaxResults=100
            )
            if response['SpotPriceHistory']:
                prices = [float(price['SpotPrice']) for price in response['SpotPriceHistory']]
                return sum(prices) / len(prices)
            else:
                return 0.0
        except Exception as e:
            logger.warning(f"Error getting price history for {instance_type} in {availability_zone}: {e}")
            return 0.0

    def analyze_single_spot_instance(self, ec2_client, instance_type: str, region: str, availability_zone: str) -> Optional[SpotAnalysis]:
        try:
            current_price = self.get_current_spot_price(ec2_client, instance_type, availability_zone)
            price_history_avg = self.get_price_history_average(ec2_client, instance_type, availability_zone)
            interruption_rate = self.estimate_interruption_rate(current_price, price_history_avg)
            score = self.calculate_spot_score(current_price, price_history_avg, interruption_rate)
            return SpotAnalysis(
                instance_type=instance_type,
                region=region,
                availability_zone=availability_zone,
                current_price=current_price,
                price_history_avg=price_history_avg,
                interruption_rate=interruption_rate,
                quota_available=100,  # Will be updated with actual quota
                score=score,
                last_updated=self._get_current_ist_time().isoformat()
            )
        except Exception as e:
            logger.warning(f"Error analyzing {instance_type} in {availability_zone}: {e}")
            return None

    def analyze_spot_instances(self, cred_info: CredentialInfo, instance_types: List[str], force_refresh: bool = False) -> List[SpotAnalysis]:
        """Analyze spot instances with enhanced real-time data"""
        self.set_credentials(cred_info)
        instance_types_hash = self._get_instance_types_hash(instance_types)
        cache_file = self._get_cache_filename('spot', instance_types_hash)
    
        if not force_refresh and cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                if 'timestamp' in cache_data:
                    cache_time = datetime.fromisoformat(cache_data['timestamp'])
                    current_time = datetime.now()
                
                    # Calculate cache age in hours
                    if hasattr(cache_time, 'tzinfo') and cache_time.tzinfo:
                        cache_time = cache_time.replace(tzinfo=None)
                    cache_age_hours = (current_time - cache_time).total_seconds() / 3600
                
                    # If cache is older than 1 hour, show warning
                    if cache_age_hours > 1:
                        print(f"\n[WARN] WARNING: Cached spot data is {cache_age_hours:.1f} hours old.")
                        print("Spot prices and availability can change frequently.")
                        use_cache = input("Do you want to use this cached data? (y/n): ").strip().lower()
                        if use_cache == 'y':
                            logger.info("Using cached spot analysis data")
                            spot_analyses = [SpotAnalysis(**item) for item in cache_data.get('data', [])]
                            return self._sort_spot_analyses(spot_analyses)
                        else:
                            force_refresh = True
                    else:
                        # Cache is fresh (less than 1 hour)
                        logger.info("Using fresh cached spot analysis data")
                        spot_analyses = [SpotAnalysis(**item) for item in cache_data.get('data', [])]
                        return self._sort_spot_analyses(spot_analyses)
            except Exception as e:
                logger.warning(f"Error reading spot cache: {e}")
    
        # Continue with fetch if cache is invalid or force_refresh is True
        logger.info(f"Analyzing spot instances in {self.region} with enhanced data... This may take a few moments...")
    
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=getattr(cred_info, 'access_key', None),
                aws_secret_access_key=getattr(cred_info, 'secret_key', None),
                region_name=self.region
            )
        
            service_quotas_client = boto3.client(
                'service-quotas',
                aws_access_key_id=getattr(cred_info, 'access_key', None),
                aws_secret_access_key=getattr(cred_info, 'secret_key', None),
                region_name=self.region
            )
        
            # Get real-time service quotas
            quotas_by_family = self.get_real_time_service_quotas(ec2_client, service_quotas_client, instance_types)
        
            # Get spot placement scores for better AZ selection
            placement_scores = self.get_spot_placement_scores(ec2_client, instance_types, self.region)
        
            spot_analyses = []
            azs_response = ec2_client.describe_availability_zones()
            all_azs = [az['ZoneName'] for az in azs_response['AvailabilityZones']]
            unsupported_azs = self._get_unsupported_azs(self.region)
            availability_zones = [az for az in all_azs if az not in unsupported_azs]
        
            print(f"Analyzing {len(instance_types)} instance types across {len(availability_zones)} availability zones...")
        
            # Create progress bar for better UX
            total_analyses = len(instance_types) * len(availability_zones)
            completed = 0
        
            for instance_type in instance_types:
                family = instance_type.split('.')[0]
                quota_info = quotas_by_family.get(family, {})
                quota_available = quota_info.get('AvailableCapacity', 32)  # Changed default from 10 to 32
            
                for az in availability_zones:
                    # Get enhanced price history with interruption analysis
                    price_history = self.get_spot_price_history_with_interruption(
                        ec2_client, instance_type, az, days=10
                    )
                
                    # Get placement score for this AZ
                    az_placement_score = placement_scores.get(az, {}).get('PlacementScore', 50)
                
                    analysis = SpotAnalysis(
                        instance_type=instance_type,
                        region=self.region,
                        availability_zone=az,
                        current_price=price_history['current_price'],
                        price_history_avg=price_history['avg_price'],
                        interruption_rate=price_history['estimated_interruption_rate'],
                        quota_available=quota_available,
                        score=self.calculate_enhanced_spot_score(
                            price_history['current_price'], 
                            price_history['avg_price'],
                            price_history['estimated_interruption_rate'],
                            quota_available,
                            az_placement_score
                        ),
                        last_updated=self._get_current_ist_time().isoformat()
                    )
                
                    spot_analyses.append(analysis)
                
                    # Update progress
                    completed += 1
                    if completed % 5 == 0 or completed == total_analyses:
                        progress = completed / total_analyses * 100
                        print(f"Progress: {progress:.1f}% ({completed}/{total_analyses})", end='\r')
        
            print("\nAnalysis complete!")
        
            # Sort by interruption rate, score, and quota availability
            spot_analyses = self._sort_spot_analyses(spot_analyses)
        
            # Save to cache
            self._save_to_cache([asdict(analysis) for analysis in spot_analyses], cache_file, 
                               getattr(cred_info, 'username', 'system'))
        
            return spot_analyses
        
        except Exception as e:
            logger.error(f"Error analyzing spot instances: {e}")
            return []

    def _sort_spot_analyses(self, spot_analyses: List[SpotAnalysis]) -> List[SpotAnalysis]:
        """Sort spot analyses by interruption rate (low first), score (high first), and quota (high first)"""
        interruption_rate_map = {
            "Low (<5%)": 1,
            "Medium (5-10%)": 2,
            "High (10-20%)": 3,
            "Very High (>20%)": 4,
            "Unknown": 5
        }
        
        return sorted(spot_analyses, key=lambda x: (
            interruption_rate_map.get(x.interruption_rate, 5),  # First by interruption rate (low to high)
            -x.score,                                          # Then by score (high to low)
            -x.quota_available                                 # Then by quota (high to low)
        ))

    def calculate_enhanced_spot_score(self, current_price: float, avg_price: float, 
                                    interruption_rate: str, quota_available: int, 
                                    placement_score: int) -> float:
        """Calculate an enhanced spot instance score based on multiple factors"""
        if avg_price == 0:
            return 0.0
    
        # Price score component (30% weight)
        price_ratio = current_price / avg_price if avg_price > 0 else 1.0
        price_score = max(0, 100 - (price_ratio * 100))
    
        # Interruption rate score component (40% weight)
        interrupt_penalty = {
            "Low (<5%)": 0,
            "Medium (5-10%)": 20,
            "High (10-20%)": 40,
            "Very High (>20%)": 60,
            "Unknown": 30
        }.get(interruption_rate, 30)
    
        interruption_score = max(0, 100 - interrupt_penalty)
    
        # Quota availability score component (15% weight)
        quota_score = min(100, (quota_available / 5) * 100)
    
        # Placement score component (15% weight)
        # AWS placement score is already 0-100
    
        # Weighted score calculation
        final_score = (
            (0.30 * price_score) +
            (0.40 * interruption_score) +
            (0.15 * quota_score) +
            (0.15 * placement_score)
        )
    
        return round(final_score, 1)

    def estimate_interruption_rate(self, current_price: float, avg_price: float) -> str:
        if avg_price == 0:
            return "Unknown"
        price_ratio = current_price / avg_price
        if price_ratio <= 0.3:
            return "Very High"
        elif price_ratio <= 0.5:
            return "High"
        elif price_ratio <= 0.8:
            return "Medium"
        else:
            return "Low"

    def calculate_spot_score(self, current_price: float, avg_price: float, interruption_rate: str) -> float:
        if avg_price == 0:
            return 0.0
        price_score = max(0, 100 - (current_price / avg_price * 100))
        interruption_penalty = {
            "Low": 0,
            "Medium": 20,
            "High": 40,
            "Very High": 60,
            "Unknown": 30
        }.get(interruption_rate, 50)
        return max(0, price_score - interruption_penalty)

    def _get_unsupported_azs(self, region: str) -> Set[str]:
        """Load unsupported AZs from ec2-region-ami-mapping.json file"""
        try:
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
            if not os.path.exists(mapping_file_path):
                logger.warning(f"Mapping file not found: {mapping_file_path}")
                return set()
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            unsupported_azs = set()
            if 'eks_unsupported_azs' in mapping_data and region in mapping_data['eks_unsupported_azs']:
                unsupported_azs = set(mapping_data['eks_unsupported_azs'][region])
                logger.debug(f"Loaded {len(unsupported_azs)} unsupported AZs for {region} from mapping file")
            else:
                logger.debug(f"No unsupported AZs found for region {region} in mapping file")
            return unsupported_azs
        except Exception as e:
            logger.warning(f"Failed to load unsupported AZs from mapping file: {str(e)}")
            return set()

    
    def get_spot_price_history_with_interruption(self, ec2_client, instance_type: str, availability_zone: str, days: int = 7) -> Dict:
        """Get spot price history and calculate interruption statistics"""
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)
    
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                AvailabilityZone=availability_zone,
                ProductDescriptions=['Linux/UNIX'],
                StartTime=start_time,
                EndTime=end_time,
                MaxResults=1000  # Get more data for better analysis
            )
    
            # Process spot price history to identify potential interruptions
            price_history = sorted([(datetime.fromisoformat(price['Timestamp'].isoformat()), 
                                    float(price['SpotPrice'])) 
                                  for price in response['SpotPriceHistory']],
                                 key=lambda x: x[0])
    
            if not price_history:
                return {
                    'current_price': 0.0,
                    'avg_price': 0.0,
                    'max_price': 0.0,
                    'min_price': 0.0,
                    'price_volatility': 0.0,
                    'estimated_interruption_rate': "Unknown"
                }
        
            # Calculate price statistics
            prices = [price for _, price in price_history]
            current_price = prices[0] if prices else 0.0
            avg_price = sum(prices) / len(prices) if prices else 0.0
            max_price = max(prices) if prices else 0.0
            min_price = min(prices) if prices else 0.0
    
            # Calculate price volatility (standard deviation as percentage of mean)
            if len(prices) > 1 and avg_price > 0:
                std_dev = statistics.stdev(prices)
                volatility = (std_dev / avg_price) * 100
            else:
                volatility = 0.0
        
            # Estimate interruption rate based on volatility and recent price trends
            if volatility < 5:
                interruption_rate = "Low (<5%)"
            elif volatility < 10:
                interruption_rate = "Medium (5-10%)"
            elif volatility < 20:
                interruption_rate = "High (10-20%)"
            else:
                interruption_rate = "Very High (>20%)"
        
            return {
                'current_price': current_price,
                'avg_price': avg_price,
                'max_price': max_price,
                'min_price': min_price,
                'price_volatility': volatility,
                'estimated_interruption_rate': interruption_rate
            }
        except Exception as e:
            self.log_operation('WARNING', f"Error analyzing spot price history: {e}")
            return {
                'current_price': 0.0,
                'avg_price': 0.0,
                'max_price': 0.0,
                'min_price': 0.0,
                'price_volatility': 0.0,
                'estimated_interruption_rate': "Unknown",  # Make sure this is always included
                'error': str(e)
            }

    def get_real_time_service_quotas(self, ec2_client, service_quotas_client, instance_types: List[str]) -> Dict[str, Dict]:
        """Fetch real-time service quotas and current usage for instance families"""
        # Extract instance families
        instance_families = set([itype.split('.')[0] for itype in instance_types])
        quotas_by_family = {}
    
        # Track current usage
        try:
            # Get running instances
            paginator = ec2_client.get_paginator('describe_instances')
            instance_counts = {}
        
            for page in paginator.paginate(
                Filters=[{'Name': 'instance-state-name', 'Values': ['pending', 'running']}]
            ):
                for reservation in page['Reservations']:
                    for instance in reservation['Instances']:
                        instance_type = instance['InstanceType']
                        family = instance_type.split('.')[0]
                        if family in instance_families:
                            instance_counts[family] = instance_counts.get(family, 0) + 1
        
            # Get quotas
            response = service_quotas_client.list_service_quotas(ServiceCode='ec2')
        
            for quota in response.get('Quotas', []):
                quota_name = quota['QuotaName'].lower()
            
                for family in instance_families:
                    if family in quota_name and ('running' in quota_name or 'spot' in quota_name):
                        quota_value = int(quota['Value'])
                        usage = instance_counts.get(family, 0)
                    
                        quotas_by_family[family] = {
                            'QuotaName': quota['QuotaName'],
                            'QuotaValue': quota_value,
                            'CurrentUsage': usage, 
                            'AvailableCapacity': max(0, quota_value - usage),
                            'Unit': quota.get('Unit', 'Count'),
                            'UtilizationPercentage': (usage / quota_value * 100) if quota_value > 0 else 0
                        }
        
            # For any families without quotas, use default value of 32 and actual usage
            for family in instance_families:
                if family not in quotas_by_family:
                    usage = instance_counts.get(family, 0)
                    default_quota = 32  # Changed from 10 to 32
                
                    quotas_by_family[family] = {
                        'QuotaName': f"Default {family.upper()} Instance Limit",
                        'QuotaValue': default_quota,
                        'CurrentUsage': usage,
                        'AvailableCapacity': max(0, default_quota - usage),
                        'Unit': 'Count',
                        'UtilizationPercentage': (usage / default_quota * 100) if default_quota > 0 else 0,
                        'IsDefault': True
                    }
    
        except Exception as e:
            self.log_operation('ERROR', f"Error fetching service quotas: {e}")
            # Provide default values (32) in case of error
            for family in instance_families:
                quotas_by_family[family] = {
                    'QuotaName': f"Default {family.upper()} Instance Limit",
                    'QuotaValue': 32,  # Changed from 10 to 32
                    'CurrentUsage': 0,
                    'AvailableCapacity': 32,  # Changed from 10 to 32
                    'Unit': 'Count',
                    'Error': str(e)
                }
    
        return quotas_by_family

    def get_spot_placement_scores(self, ec2_client, instance_types: List[str], region: str) -> Dict[str, Dict]:
        """Get AWS Spot Placement Scores for better instance selection"""
        try:
            response = ec2_client.get_spot_placement_scores(
                InstanceTypes=instance_types,
                TargetCapacity=1,
                SingleAvailabilityZone=True,
                RegionNames=[region]
            )
        
            placement_scores = {}
        
            for score_set in response.get('SpotPlacementScores', []):
                for az_score in score_set.get('AvailabilityZoneScores', []):
                    az = az_score['AvailabilityZone']
                    if az not in placement_scores:
                        placement_scores[az] = {}
                
                    score = az_score['Score']
                    placement_scores[az]['PlacementScore'] = score
        
            return placement_scores
        
        except Exception as e:
            self.log_operation('WARNING', f"Error fetching spot placement scores: {e}")
            return {}

    def log_operation(self, level: str, message: str):
            """Basic logger for SpotInstanceAnalyzer"""
            print(f"[{level}] {message}")

    def diagnose_running_instances(self):
        """Diagnostic function to list all running instances with details"""
        try:
            # Check if session is initialized
            if not hasattr(self, 'session') or self.session is None:
                if hasattr(self, 'credentials') and self.credentials is not None:
                    # Create session from credentials
                    self.session = boto3.Session(
                        aws_access_key_id=self.credentials.access_key,
                        aws_secret_access_key=self.credentials.secret_key,
                        region_name=self.region
                    )
                    print(f"Created new session for region: {self.region}")
                else:
                    print("[WARN]  No credentials or session available. Creating default session.")
                    self.session = boto3.Session(region_name=self.region)

            ec2_client = self.session.client('ec2')
            instances = []
    
            # Use paginator to handle large number of instances
            print("Fetching instances (this may take a moment)...")
            paginator = ec2_client.get_paginator('describe_instances')
            for page in paginator.paginate(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'pending']}]
            ):
                for reservation in page['Reservations']:
                    instances.extend(reservation['Instances'])
    
            # Print diagnostic info
            print(f"\n[SCAN] Found {len(instances)} running/pending instances")
            print("=" * 80)
    
            for i, instance in enumerate(instances, 1):
                instance_id = instance['InstanceId']
                instance_type = instance['InstanceType']
                az = instance.get('Placement', {}).get('AvailabilityZone', 'N/A')
                state = instance.get('State', {}).get('Name', 'unknown')
        
                # Get instance name from tags
                name = "No Name"
                if 'Tags' in instance:
                    for tag in instance['Tags']:
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break
        
                print(f"{i}. {instance_id} | {instance_type} | {name} | {az} | {state}")
    
            print("=" * 80)
    
            # Summarize by instance type
            instance_types = {}
            for instance in instances:
                instance_type = instance['InstanceType']
                instance_types[instance_type] = instance_types.get(instance_type, 0) + 1
        
            print("\nInstance Type Summary:")
            for instance_type, count in sorted(instance_types.items()):
                print(f"  {instance_type}: {count} instances")
        
            # Calculate vCPU usage by instance family
            print("\nvCPU Usage by Instance Family:")
            # Define vCPU mapping for common instance types
            vcpu_mapping = {
                'c6a.large': 2, 'c6i.large': 2, 'm6a.large': 2, 'm6i.large': 2,
                't3.micro': 2, 't3.small': 2, 't3.medium': 2, 't3.large': 2,
                't3a.micro': 2, 't3a.small': 2, 't3a.medium': 2, 't3a.large': 2
            }
        
            vcpu_usage = {}
            for instance in instances:
                instance_type = instance['InstanceType']
                family = instance_type.split('.')[0]
            
                # Get vCPU count for this instance type
                vcpu_count = vcpu_mapping.get(instance_type, 2)  # Default to 2 if not known
            
                if family not in vcpu_usage:
                    vcpu_usage[family] = 0
                vcpu_usage[family] += vcpu_count
        
            for family, vcpus in sorted(vcpu_usage.items()):
                print(f"  {family}: {vcpus} vCPUs")
            
            return instances
    
        except Exception as e:
            print(f"[ERROR] Error in diagnostic function: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def log_operation(self, level: str, message: str):
            """Basic logger for EKSClusterManager"""
            print(f"[{level}] {message}")

    def print_colored(self, color: str, message: str) -> None:
            """Print colored message to terminal"""
            print(f"{color}{message}{Colors.NC}")

    def set_session(self, session):
        """Set boto3 session for API calls"""
        self.session = session
        self.region = session.region_name
        logger.info(f"Session set with region: {self.region}")