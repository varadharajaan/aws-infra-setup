#!/usr/bin/env python3

import json
import os
from typing import Dict, List, Optional, Tuple

class InstanceConfigManager:
    def __init__(self, config_file: str = 'instance_specs.json'):
        self.config_file = config_file
        self.config_data = None
        self.load_config()
    
    def load_config(self):
        """Load instance configuration from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Instance config file not found: {self.config_file}")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            print(f"✅ Instance configuration loaded from: {self.config_file}")
            print(f"📅 Config version: {self.config_data.get('metadata', {}).get('version', 'Unknown')}")
            print(f"🔄 Last updated: {self.config_data.get('metadata', {}).get('last_updated', 'Unknown')}")
            
        except Exception as e:
            print(f"❌ Error loading instance config: {e}")
            raise
    
    def get_instance_specs(self, instance_type: str) -> Optional[Dict]:
        """Get specifications for a specific instance type"""
        return self.config_data.get('instance_types', {}).get(instance_type)
    
    def get_all_instance_types(self) -> List[str]:
        """Get list of all available instance types"""
        return list(self.config_data.get('instance_types', {}).keys())
    
    def get_family_specs(self, family: str) -> Optional[Dict]:
        """Get specifications for an instance family"""
        return self.config_data.get('instance_families', {}).get(family)
    
    def get_size_specs(self, size: str) -> Optional[Dict]:
        """Get specifications for an instance size"""
        return self.config_data.get('instance_sizes', {}).get(size)
    
    def get_pricing_for_region(self, instance_type: str, region: str) -> float:
        """Get pricing for specific instance type and region"""
        instance_specs = self.get_instance_specs(instance_type)
        if not instance_specs:
            return 0.0
        
        # Try direct regional pricing first
        pricing_data = instance_specs.get('pricing', {})
        if region in pricing_data:
            return pricing_data[region]
        
        # Fall back to us-east-1 pricing with regional adjustment
        base_price = pricing_data.get('us-east-1', 0.0)
        if base_price == 0.0:
            return 0.0
        
        # Apply regional adjustment
        regional_adjustments = self.config_data.get('regional_adjustments', {})
        adjustment = regional_adjustments.get(region, 1.0)
        
        return base_price * adjustment
    
    def calculate_performance_score(self, instance_type: str) -> float:
        """Calculate performance score for instance type"""
        instance_specs = self.get_instance_specs(instance_type)
        if not instance_specs:
            return 0.0
        
        family = instance_specs.get('family')
        size = instance_specs.get('size')
        
        family_specs = self.get_family_specs(family)
        size_specs = self.get_size_specs(size)
        
        if not family_specs or not size_specs:
            return 0.0
        
        # Calculate base performance from vCPUs and memory
        vcpus = instance_specs.get('vcpus', 1)
        memory_gb = instance_specs.get('memory_gb', 1)
        
        # Apply family and size multipliers
        family_multiplier = family_specs.get('performance_multiplier', 1.0)
        size_multiplier = size_specs.get('size_multiplier', 1.0)
        
        # Combined performance score
        performance_score = (vcpus * 2 + memory_gb) * family_multiplier * (size_multiplier / 8)
        
        return performance_score
    
    def calculate_interruption_rate(self, instance_type: str, price_volatility: float = 0.0) -> float:
        """Calculate estimated interruption rate"""
        instance_specs = self.get_instance_specs(instance_type)
        if not instance_specs:
            return 0.05  # Default 5%
        
        family = instance_specs.get('family')
        size = instance_specs.get('size')
        
        family_specs = self.get_family_specs(family)
        size_specs = self.get_size_specs(size)
        
        if not family_specs or not size_specs:
            return 0.05
        
        # Base rate from family
        base_rate = family_specs.get('base_interruption_rate', 0.05)
        
        # Size adjustment
        size_adjustment = size_specs.get('interruption_adjustment', 1.0)
        
        # Volatility impact
        volatility_multiplier = 1 + (price_volatility * 2)
        
        # Calculate final rate
        interruption_rate = base_rate * size_adjustment * volatility_multiplier
        
        return min(interruption_rate, 0.25)  # Cap at 25%
    
    def get_analysis_thresholds(self) -> Dict:
        """Get analysis thresholds for recommendations"""
        return self.config_data.get('analysis_thresholds', {
            'min_savings_percentage': 15,
            'min_availability_zones': 2,
            'max_interruption_rate': 0.12,
            'min_confidence_score': 0.6,
            'price_volatility_threshold': 0.2,
            'min_data_points': 10
        })
    
    def get_similar_instances(self, target_instance: str, max_results: int = 5) -> List[Dict]:
        """Get similar instance types based on performance and characteristics"""
        target_specs = self.get_instance_specs(target_instance)
        if not target_specs:
            return []
        
        target_family = target_specs.get('family')
        target_vcpus = target_specs.get('vcpus')
        target_memory = target_specs.get('memory_gb')
        target_performance = self.calculate_performance_score(target_instance)
        
        similar_instances = []
        
        for instance_type, specs in self.config_data.get('instance_types', {}).items():
            if instance_type == target_instance:
                continue
            
            # Calculate similarity score
            family_match = 1.0 if specs.get('family') == target_family else 0.7
            
            vcpu_diff = abs(specs.get('vcpus', 0) - target_vcpus) / max(target_vcpus, 1)
            vcpu_similarity = max(0, 1 - vcpu_diff)
            
            memory_diff = abs(specs.get('memory_gb', 0) - target_memory) / max(target_memory, 1)
            memory_similarity = max(0, 1 - memory_diff)
            
            performance_score = self.calculate_performance_score(instance_type)
            perf_diff = abs(performance_score - target_performance) / max(target_performance, 1)
            perf_similarity = max(0, 1 - perf_diff)
            
            # Overall similarity score
            similarity_score = (
                family_match * 0.3 +
                vcpu_similarity * 0.25 +
                memory_similarity * 0.25 +
                perf_similarity * 0.2
            )
            
            similar_instances.append({
                'instance_type': instance_type,
                'similarity_score': similarity_score,
                'specs': specs,
                'performance_score': performance_score
            })
        
        # Sort by similarity and return top results
        similar_instances.sort(key=lambda x: x['similarity_score'], reverse=True)
        return similar_instances[:max_results]
    
    def get_instances_by_category(self, category: str) -> List[str]:
        """Get all instances in a specific category"""
        instances = []
        
        for instance_type, specs in self.config_data.get('instance_types', {}).items():
            family = specs.get('family')
            family_specs = self.get_family_specs(family)
            
            if family_specs and family_specs.get('category') == category:
                instances.append(instance_type)
        
        return instances
    
    def validate_instance_type(self, instance_type: str) -> Tuple[bool, str]:
        """Validate if instance type exists and get details"""
        specs = self.get_instance_specs(instance_type)
        
        if not specs:
            return False, f"Instance type '{instance_type}' not found in configuration"
        
        family = specs.get('family')
        vcpus = specs.get('vcpus')
        memory = specs.get('memory_gb')
        
        return True, f"Valid: {instance_type} - {vcpus} vCPUs, {memory}GB RAM ({family} family)"
    
    def get_cost_analysis(self, instance_type: str, region: str, hours: int = 730) -> Dict:
        """Get detailed cost analysis for instance type"""
        pricing = self.get_pricing_for_region(instance_type, region)
        
        if pricing == 0.0:
            return {"error": "Pricing not available"}
        
        return {
            "hourly_cost": pricing,
            "daily_cost": pricing * 24,
            "weekly_cost": pricing * 24 * 7,
            "monthly_cost": pricing * hours,
            "annual_cost": pricing * 24 * 365,
            "currency": "USD",
            "region": region
        }
    
    def refresh_config(self):
        """Reload configuration from file"""
        self.load_config()
        print("🔄 Configuration refreshed successfully")