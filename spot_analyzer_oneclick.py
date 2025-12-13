#!/usr/bin/env python3

import boto3
import json
import time
import statistics
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass
from botocore.exceptions import ClientError
from text_symbols import Symbols


# Import logger from your existing setup
try:
    from logger import setup_logger
except ImportError:
    # Fallback logger if logger module not available
    def setup_logger(name, log_file):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

@dataclass
class SpotAvailabilityResult:
    """Result of spot availability analysis"""
    instance_type: str
    is_available: bool
    availability_zones: List[str]
    current_price: float
    on_demand_price: float
    savings_percentage: float
    interruption_rate: float
    recommendation_score: float
    reasons: List[str]

@dataclass
class InstanceAlternative:
    """Alternative instance type recommendation"""
    instance_type: str
    family: str
    vcpus: int
    memory_gb: float
    performance_score: float
    cost_per_hour: float
    availability_score: float
    overall_score: float
    reason: str

@dataclass
class SpotInstanceAnalyzer:
    def __init__(self, region: str):
        self.region = region
        self.logger = setup_logger("spot_analyzer", "spot_analysis")
        self.ec2_client = None
        self.pricing_client = None
        
        # Enhanced instance type specifications
        self.instance_specs = {
            # T3 Family - Burstable Performance
            't3.nano': {'vcpus': 2, 'memory': 0.5, 'family': 't3', 'performance': 0.5},
            't3.micro': {'vcpus': 2, 'memory': 1, 'family': 't3', 'performance': 1},
            't3.small': {'vcpus': 2, 'memory': 2, 'family': 't3', 'performance': 2},
            't3.medium': {'vcpus': 2, 'memory': 4, 'family': 't3', 'performance': 4},
            't3.large': {'vcpus': 2, 'memory': 8, 'family': 't3', 'performance': 8},
            't3.xlarge': {'vcpus': 4, 'memory': 16, 'family': 't3', 'performance': 16},
            't3.2xlarge': {'vcpus': 8, 'memory': 32, 'family': 't3', 'performance': 32},
            
            # T4g Family - ARM-based Burstable
            't4g.nano': {'vcpus': 2, 'memory': 0.5, 'family': 't4g', 'performance': 0.6},
            't4g.micro': {'vcpus': 2, 'memory': 1, 'family': 't4g', 'performance': 1.2},
            't4g.small': {'vcpus': 2, 'memory': 2, 'family': 't4g', 'performance': 2.4},
            't4g.medium': {'vcpus': 2, 'memory': 4, 'family': 't4g', 'performance': 4.8},
            't4g.large': {'vcpus': 2, 'memory': 8, 'family': 't4g', 'performance': 9.6},
            
            # C5 Family - Compute Optimized
            'c5.large': {'vcpus': 2, 'memory': 4, 'family': 'c5', 'performance': 5},
            'c5.xlarge': {'vcpus': 4, 'memory': 8, 'family': 'c5', 'performance': 10},
            'c5.2xlarge': {'vcpus': 8, 'memory': 16, 'family': 'c5', 'performance': 20},
            'c5.4xlarge': {'vcpus': 16, 'memory': 32, 'family': 'c5', 'performance': 40},
            
            # C6a Family - Latest Compute Optimized
            'c6a.large': {'vcpus': 2, 'memory': 4, 'family': 'c6a', 'performance': 6},
            'c6a.xlarge': {'vcpus': 4, 'memory': 8, 'family': 'c6a', 'performance': 12},
            'c6a.2xlarge': {'vcpus': 8, 'memory': 16, 'family': 'c6a', 'performance': 24},
            'c6a.4xlarge': {'vcpus': 16, 'memory': 32, 'family': 'c6a', 'performance': 48},
            
            # M5 Family - General Purpose
            'm5.large': {'vcpus': 2, 'memory': 8, 'family': 'm5', 'performance': 7},
            'm5.xlarge': {'vcpus': 4, 'memory': 16, 'family': 'm5', 'performance': 14},
            'm5.2xlarge': {'vcpus': 8, 'memory': 32, 'family': 'm5', 'performance': 28},
            'm5.4xlarge': {'vcpus': 16, 'memory': 64, 'family': 'm5', 'performance': 56},
            
            # M6i Family - Latest General Purpose
            'm6i.large': {'vcpus': 2, 'memory': 8, 'family': 'm6i', 'performance': 8},
            'm6i.xlarge': {'vcpus': 4, 'memory': 16, 'family': 'm6i', 'performance': 16},
            'm6i.2xlarge': {'vcpus': 8, 'memory': 32, 'family': 'm6i', 'performance': 32},
            
            # R5 Family - Memory Optimized
            'r5.large': {'vcpus': 2, 'memory': 16, 'family': 'r5', 'performance': 9},
            'r5.xlarge': {'vcpus': 4, 'memory': 32, 'family': 'r5', 'performance': 18},
            'r5.2xlarge': {'vcpus': 8, 'memory': 64, 'family': 'r5', 'performance': 36},
        }
        
    def initialize_clients(self, access_key: str, secret_key: str) -> bool:
        """Initialize AWS clients with credentials"""
        try:
            self.ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=self.region
            )
            
            # Pricing client is always in us-east-1
            self.pricing_client = boto3.client(
                'pricing',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name='us-east-1'
            )
            
            # Test the connection
            self.ec2_client.describe_regions(RegionNames=[self.region])
            self.logger.info(f"Successfully initialized AWS clients for region {self.region}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize AWS clients: {e}")
            return False

    def get_availability_zones(self) -> List[str]:
        """Get all availability zones in the region"""
        try:
            response = self.ec2_client.describe_availability_zones(
                Filters=[
                    {'Name': 'state', 'Values': ['available']},
                    {'Name': 'region-name', 'Values': [self.region]}
                ]
            )
            
            azs = [az['ZoneName'] for az in response['AvailabilityZones']]
            self.logger.info(f"Found {len(azs)} availability zones: {azs}")
            return azs
            
        except Exception as e:
            self.logger.error(f"Error getting availability zones: {e}")
            return []

    def get_spot_price_history(self, instance_type: str, days: int = 7) -> Dict:
        """Get spot price history for analysis"""
        try:
            end_time = datetime.now(datetime.UTC)
            start_time = end_time - timedelta(days=days)
            
            response = self.ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=['Linux/UNIX'],
                StartTime=start_time,
                EndTime=end_time,
                MaxResults=1000
            )
            
            prices = response.get('SpotPriceHistory', [])
            self.logger.info(f"Retrieved {len(prices)} spot price records for {instance_type}")
            
            if not prices:
                return {'available': False, 'reason': 'No price history available'}
            
            # Analyze price data
            price_values = [float(p['SpotPrice']) for p in prices]
            availability_zones = list(set(p['AvailabilityZone'] for p in prices))
            
            analysis = {
                'available': True,
                'current_price': price_values[0] if price_values else 0,
                'avg_price': statistics.mean(price_values),
                'min_price': min(price_values),
                'max_price': max(price_values),
                'price_volatility': statistics.stdev(price_values) if len(price_values) > 1 else 0,
                'availability_zones': availability_zones,
                'data_points': len(prices)
            }
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error getting spot price history for {instance_type}: {e}")
            return {'available': False, 'reason': f'Error retrieving price data: {e}'}

    def get_on_demand_price(self, instance_type: str) -> float:
        """Get on-demand price for instance type"""
        try:
            # Try AWS Pricing API first
            response = self.pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': self._get_region_name()},
                    {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                    {'Type': 'TERM_MATCH', 'Field': 'operating-system', 'Value': 'Linux'},
                    {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'},
                    {'Type': 'TERM_MATCH', 'Field': 'capacitystatus', 'Value': 'Used'}
                ],
                MaxResults=1
            )
            
            for price_item in response['PriceList']:
                price_data = json.loads(price_item)
                terms = price_data.get('terms', {}).get('OnDemand', {})
                
                for term in terms.values():
                    price_dimensions = term.get('priceDimensions', {})
                    for dimension in price_dimensions.values():
                        price_per_hour = float(dimension['pricePerUnit']['USD'])
                        return price_per_hour
            
            # Fallback to static pricing if API fails
            return self._get_fallback_price(instance_type)
            
        except Exception as e:
            self.logger.warning(f"Error getting on-demand price for {instance_type}: {e}")
            return self._get_fallback_price(instance_type)

    def _get_fallback_price(self, instance_type: str) -> float:
        """Get fallback pricing when API is unavailable"""
        # Updated pricing as of June 2025 (these are approximate US East prices)
        fallback_prices = {
            # T3 Family
            't3.nano': 0.0052, 't3.micro': 0.0104, 't3.small': 0.0208,
            't3.medium': 0.0416, 't3.large': 0.0832, 't3.xlarge': 0.1664,
            't3.2xlarge': 0.3328,
            
            # T4g Family (ARM-based, typically 20% cheaper)
            't4g.nano': 0.0042, 't4g.micro': 0.0084, 't4g.small': 0.0168,
            't4g.medium': 0.0336, 't4g.large': 0.0672,
            
            # C5 Family
            'c5.large': 0.085, 'c5.xlarge': 0.17, 'c5.2xlarge': 0.34,
            'c5.4xlarge': 0.68,
            
            # C6a Family
            'c6a.large': 0.0864, 'c6a.xlarge': 0.1728, 'c6a.2xlarge': 0.3456,
            'c6a.4xlarge': 0.6912,
            
            # M5 Family
            'm5.large': 0.096, 'm5.xlarge': 0.192, 'm5.2xlarge': 0.384,
            'm5.4xlarge': 0.768,
            
            # M6i Family
            'm6i.large': 0.0864, 'm6i.xlarge': 0.1728, 'm6i.2xlarge': 0.3456,
            
            # R5 Family
            'r5.large': 0.126, 'r5.xlarge': 0.252, 'r5.2xlarge': 0.504
        }
        
        return fallback_prices.get(instance_type, 0.05)

    def _get_region_name(self) -> str:
        """Convert region code to region name for pricing API"""
        region_mapping = {
            'us-east-1': 'US East (N. Virginia)',
            'us-east-2': 'US East (Ohio)',
            'us-west-1': 'US West (N. California)',
            'us-west-2': 'US West (Oregon)',
            'eu-west-1': 'Europe (Ireland)',
            'eu-west-2': 'Europe (London)',
            'eu-central-1': 'Europe (Frankfurt)',
            'ap-southeast-1': 'Asia Pacific (Singapore)',
            'ap-northeast-1': 'Asia Pacific (Tokyo)',
            'ap-south-1': 'Asia Pacific (Mumbai)',
            'ca-central-1': 'Canada (Central)',
            'sa-east-1': 'South America (Sao Paulo)'
        }
        return region_mapping.get(self.region, 'US East (N. Virginia)')

    def calculate_interruption_rate(self, instance_type: str) -> float:
        """Calculate estimated historical interruption rate"""
        try:
            # Base interruption rates by instance family (based on AWS data and community feedback)
            base_rates = {
                't3': 0.05,    # 5% - Burstable instances have moderate interruption rates
                't4g': 0.04,   # 4% - ARM instances tend to have lower interruption rates
                'c5': 0.03,    # 3% - Compute optimized, stable demand
                'c6a': 0.025,  # 2.5% - Newer generation, better availability
                'm5': 0.04,    # 4% - General purpose, moderate demand
                'm6i': 0.035,  # 3.5% - Newer generation general purpose
                'r5': 0.06,    # 6% - Memory optimized, higher demand
            }
            
            family = instance_type.split('.')[0]
            base_rate = base_rates.get(family, 0.05)
            
            # Size adjustment - larger instances typically have lower interruption rates
            if '4xlarge' in instance_type or '8xlarge' in instance_type:
                base_rate *= 0.7  # 30% reduction for very large instances
            elif '2xlarge' in instance_type:
                base_rate *= 0.8  # 20% reduction for 2xlarge
            elif 'xlarge' in instance_type:
                base_rate *= 0.85  # 15% reduction for xlarge
            elif 'large' in instance_type:
                base_rate *= 0.9   # 10% reduction for large
            # nano, micro, small keep base rate or slightly higher
            elif 'nano' in instance_type or 'micro' in instance_type:
                base_rate *= 1.1   # 10% increase for very small instances
            
            self.logger.info(f"Estimated interruption rate for {instance_type}: {base_rate:.2%}")
            return base_rate
            
        except Exception as e:
            self.logger.error(f"Error calculating interruption rate for {instance_type}: {e}")
            return 0.05  # Default 5%

    def analyze_spot_availability(self, instance_type: str) -> SpotAvailabilityResult:
        """Comprehensive spot availability analysis"""
        try:
            self.logger.info(f"Starting comprehensive spot analysis for {instance_type}")
            
            reasons = []
            
            # 1. Check if instance type exists in our specs
            if instance_type not in self.instance_specs:
                reasons.append(f"Instance type {instance_type} not in supported list")
                return SpotAvailabilityResult(
                    instance_type=instance_type,
                    is_available=False,
                    availability_zones=[],
                    current_price=0,
                    on_demand_price=0,
                    savings_percentage=0,
                    interruption_rate=0,
                    recommendation_score=0,
                    reasons=reasons
                )
            
            # 2. Get availability zones
            available_azs = self.get_availability_zones()
            if not available_azs:
                reasons.append("No availability zones found")
                return SpotAvailabilityResult(
                    instance_type=instance_type,
                    is_available=False,
                    availability_zones=[],
                    current_price=0,
                    on_demand_price=0,
                    savings_percentage=0,
                    interruption_rate=0,
                    recommendation_score=0,
                    reasons=reasons
                )
            
            # 3. Get spot price history
            price_analysis = self.get_spot_price_history(instance_type)
            if not price_analysis.get('available', False):
                reasons.append(price_analysis.get('reason', 'No spot price data'))
                current_price = 0
                spot_azs = []
            else:
                current_price = price_analysis['current_price']
                spot_azs = price_analysis['availability_zones']
                reasons.append(f"Spot price data available across {len(spot_azs)} AZs")
            
            # 4. Get on-demand price
            on_demand_price = self.get_on_demand_price(instance_type)
            
            # 5. Calculate savings
            if current_price > 0 and on_demand_price > 0:
                savings_percentage = ((on_demand_price - current_price) / on_demand_price) * 100
            else:
                savings_percentage = 0
            
            # 6. Calculate interruption rate
            interruption_rate = self.calculate_interruption_rate(instance_type)
            
            # 7. Calculate recommendation score
            recommendation_score = self._calculate_recommendation_score(
                price_analysis, savings_percentage, interruption_rate, len(spot_azs)
            )
            
            # 8. Determine overall availability with enhanced logic
            min_savings_threshold = 15  # Minimum 15% savings required
            min_az_count = 1  # At least 1 AZ with spot availability
            max_interruption_rate = 0.15  # Maximum 15% interruption rate
            min_confidence_score = 0.4  # Minimum 40% confidence
            
            is_available = (
                len(spot_azs) >= min_az_count and 
                current_price > 0 and 
                savings_percentage >= min_savings_threshold and
                interruption_rate <= max_interruption_rate and
                recommendation_score >= min_confidence_score
            )
            
            # Add detailed reasoning
            if is_available:
                reasons.append(f"{Symbols.OK} RECOMMENDED: {savings_percentage:.1f}% savings, {recommendation_score:.1%} confidence")
                reasons.append(f"Available in {len(spot_azs)} AZs with {interruption_rate:.1%} interruption rate")
            else:
                if len(spot_azs) < min_az_count:
                    reasons.append(f"{Symbols.ERROR} Insufficient AZ coverage: {len(spot_azs)} < {min_az_count}")
                if current_price <= 0:
                    reasons.append("[ERROR] No current spot pricing available")
                if savings_percentage < min_savings_threshold:
                    reasons.append(f"{Symbols.ERROR} Low savings potential: {savings_percentage:.1f}% < {min_savings_threshold}%")
                if interruption_rate > max_interruption_rate:
                    reasons.append(f"{Symbols.ERROR} High interruption risk: {interruption_rate:.1%} > {max_interruption_rate:.1%}")
                if recommendation_score < min_confidence_score:
                    reasons.append(f"{Symbols.ERROR} Low confidence score: {recommendation_score:.1%} < {min_confidence_score:.1%}")
            
            result = SpotAvailabilityResult(
                instance_type=instance_type,
                is_available=is_available,
                availability_zones=spot_azs,
                current_price=current_price,
                on_demand_price=on_demand_price,
                savings_percentage=savings_percentage,
                interruption_rate=interruption_rate,
                recommendation_score=recommendation_score,
                reasons=reasons
            )
            
            self.logger.info(f"Spot analysis complete for {instance_type}: Available={is_available}, Score={recommendation_score:.1%}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error in spot availability analysis for {instance_type}: {e}")
            return SpotAvailabilityResult(
                instance_type=instance_type,
                is_available=False,
                availability_zones=[],
                current_price=0,
                on_demand_price=0,
                savings_percentage=0,
                interruption_rate=0,
                recommendation_score=0,
                reasons=[f"Analysis failed: {e}"]
            )

    def _calculate_recommendation_score(self, price_analysis: Dict, savings_percentage: float, 
                                       interruption_rate: float, az_count: int) -> float:
        """Calculate overall recommendation score (0-1)"""
        try:
            score = 0.0
            
            # Price stability score (25% weight)
            if price_analysis.get('available', False) and price_analysis.get('avg_price', 0) > 0:
                volatility = price_analysis.get('price_volatility', 0)
                avg_price = price_analysis.get('avg_price', 0)
                volatility_ratio = min(volatility / avg_price, 1.0)  # Cap at 100%
                price_stability_score = max(0, 1 - volatility_ratio)
            else:
                price_stability_score = 0
            
            score += price_stability_score * 0.25
            
            # Savings potential score (35% weight)
            # Scale: 0% savings = 0 score, 70%+ savings = 1.0 score
            savings_score = min(max(savings_percentage, 0) / 70, 1.0)
            score += savings_score * 0.35
            
            # Low interruption rate score (25% weight)
            # Scale: 0% interruption = 1.0 score, 20%+ interruption = 0 score
            interruption_score = max(0, 1 - (interruption_rate / 0.2))
            score += interruption_score * 0.25
            
            # Multi-AZ availability score (15% weight)
            # Scale: 1 AZ = 0.33 score, 3+ AZs = 1.0 score
            az_score = min(az_count / 3, 1.0)
            score += az_score * 0.15
            
            return min(score, 1.0)
            
        except Exception as e:
            self.logger.error(f"Error calculating recommendation score: {e}")
            return 0.0

    def get_alternative_instances(self, target_instance: str, max_alternatives: int = 5) -> List[InstanceAlternative]:
        """Get alternative instance types with availability analysis"""
        try:
            self.logger.info(f"Finding alternatives for {target_instance}")
            
            target_specs = self.instance_specs.get(target_instance)
            if not target_specs:
                self.logger.warning(f"No specifications found for {target_instance}")
                return []
            
            alternatives = []
            
            # 1. Same family, different sizes (highest priority)
            target_family = target_specs['family']
            same_family_types = [
                inst for inst, specs in self.instance_specs.items() 
                if specs['family'] == target_family and inst != target_instance
            ]
            
            for instance_type in same_family_types:
                alternative = self._create_instance_alternative(instance_type, "Same family alternative")
                if alternative:
                    alternatives.append(alternative)
            
            # 2. Similar performance, different families (medium priority)
            target_performance = target_specs['performance']
            performance_tolerance = max(target_performance * 0.3, 1)  # 30% tolerance, minimum 1
            
            similar_performance_types = [
                inst for inst, specs in self.instance_specs.items()
                if (abs(specs['performance'] - target_performance) <= performance_tolerance
                    and specs['family'] != target_family
                    and inst != target_instance)
            ]
            
            for instance_type in similar_performance_types:
                alternative = self._create_instance_alternative(instance_type, "Similar performance")
                if alternative:
                    alternatives.append(alternative)
            
            # 3. Cost-effective alternatives (lower priority)
            target_price = self.get_on_demand_price(target_instance)
            cost_effective_types = [
                inst for inst, specs in self.instance_specs.items()
                if (inst != target_instance 
                    and inst not in same_family_types 
                    and inst not in similar_performance_types)
            ]
            
            for instance_type in cost_effective_types[:10]:  # Limit to 10 to avoid too many API calls
                alternative = self._create_instance_alternative(instance_type, "Cost-effective option")
                if alternative and alternative.cost_per_hour <= target_price * 1.5:  # Within 150% of target price
                    alternatives.append(alternative)
            
            # 4. Sort by overall score and return top alternatives
            alternatives.sort(key=lambda x: x.overall_score, reverse=True)
            
            return alternatives[:max_alternatives]
            
        except Exception as e:
            self.logger.error(f"Error finding alternatives for {target_instance}: {e}")
            return []

    def _create_instance_alternative(self, instance_type: str, reason: str) -> Optional[InstanceAlternative]:
        """Create an InstanceAlternative object with availability analysis"""
        try:
            specs = self.instance_specs.get(instance_type)
            if not specs:
                return None
            
            # Quick spot availability check (shorter period for performance)
            price_analysis = self.get_spot_price_history(instance_type, days=2)
            availability_score = 0.5  # Default neutral score
            
            if price_analysis.get('available', False):
                az_count = len(price_analysis.get('availability_zones', []))
                current_price = price_analysis.get('current_price', 0)
                
                # Calculate availability score based on AZ coverage and price availability
                if current_price > 0:
                    availability_score = min(az_count / 3, 1.0) * 0.7 + 0.3  # 0.3 to 1.0 range
                else:
                    availability_score = min(az_count / 3, 1.0) * 0.5  # 0 to 0.5 range
            
            # Get pricing
            on_demand_price = self.get_on_demand_price(instance_type)
            
            # Calculate scores
            performance_score = specs['performance']
            cost_efficiency_score = performance_score / max(on_demand_price, 0.001)  # Performance per dollar
            
            # Overall score combines multiple factors
            overall_score = (
                performance_score * 0.3 +           # 30% performance
                cost_efficiency_score * 0.3 +       # 30% cost efficiency  
                availability_score * 100 * 0.25 +   # 25% availability (scaled to match other scores)
                (1 / max(on_demand_price, 0.001)) * 10 * 0.15  # 15% raw cost factor
            )
            
            return InstanceAlternative(
                instance_type=instance_type,
                family=specs['family'],
                vcpus=specs['vcpus'],
                memory_gb=specs['memory'],
                performance_score=performance_score,
                cost_per_hour=on_demand_price,
                availability_score=availability_score,
                overall_score=overall_score,
                reason=reason
            )
            
        except Exception as e:
            self.logger.error(f"Error creating alternative for {instance_type}: {e}")
            return None