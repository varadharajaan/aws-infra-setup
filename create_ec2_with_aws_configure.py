# Databricks notebook source
#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
import glob
import re
import random
import string
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from logger import setup_logger
from typing import Set
from text_symbols import Symbols
from spot_instance_analyzer import SpotInstanceAnalyzer
from typing import Tuple, Optional, List, Dict
from datetime import datetime, timedelta
from instance_config_manager import InstanceConfigManager

class EC2InstanceManager:
    def __init__(self, ami_mapping_file='ec2-region-ami-mapping.json', userdata_file='userdata.sh'):
        self.ami_mapping_file = ami_mapping_file
        self.userdata_file = userdata_file
        self.logger = setup_logger("ec2_instance_manager", "ec2_creation")
        
        # Find the latest credentials file
        self.credentials_file = self.find_latest_credentials_file()
        
        self.load_configurations()
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Read the user data script from external file
        self.user_data_script = self.load_user_data_script()
        
        # Initialize log file
        self.setup_detailed_logging()
        self.spot_analyzer = None  # Will be initialized per region
        self.instance_config = InstanceConfigManager()

    def select_instance_with_smart_analysis(self) -> Tuple[str, str]:
            """Enhanced instance selection with intelligent spot analysis"""
            allowed_types = self.ami_config['allowed_instance_types']
            default_type = self.ami_config['default_instance_type']
            
            self.log_operation('INFO', "Starting intelligent instance type selection")
            
            print("\n[BRAIN] Intelligent Instance Selection with Spot Analysis")
            print("=" * 70)
            print("This will analyze spot availability and suggest optimal choices.")
            print()
            
            # Display basic options first
            print("🖥️  Available Instance Types:")
            for i, instance_type in enumerate(allowed_types, 1):
                marker = " (default)" if instance_type == default_type else ""
                print(f"  {i}. {instance_type}{marker}")
            
            print(f"  {len(allowed_types) + 1}. {Symbols.SCAN} Smart Analysis Mode (Recommended)")
            print(f"  {len(allowed_types) + 2}. Custom instance type")
            
            while True:
                try:
                    choice = input(f"\n[#] Select option (1-{len(allowed_types) + 2}) or press Enter for smart analysis: ").strip()
                    
                    if not choice:
                        # Default to smart analysis
                        return self._run_smart_analysis_mode(default_type)
                    
                    choice_num = int(choice)
                    
                    if 1 <= choice_num <= len(allowed_types):
                        # Regular selection - ask if they want analysis
                        selected_type = allowed_types[choice_num - 1]
                        
                        analyze = input(f"\n{Symbols.SCAN} Run spot analysis for {selected_type}? (Y/n): ").lower().strip()
                        if analyze != 'n':
                            return self._analyze_and_confirm_instance(selected_type)
                        else:
                            capacity_type = self.select_capacity_type_ec2()
                            return selected_type, capacity_type
                    
                    elif choice_num == len(allowed_types) + 1:
                        # Smart analysis mode
                        return self._run_smart_analysis_mode(default_type)
                    
                    elif choice_num == len(allowed_types) + 2:
                        # Custom instance type
                        return self._handle_custom_instance_type()
                    
                    else:
                        print(f"{Symbols.ERROR} Invalid choice. Please enter a number between 1 and {len(allowed_types) + 2}")
                        
                except ValueError:
                    print("[ERROR] Invalid input. Please enter a number.")

    def _run_smart_analysis_mode(self, default_type: str) -> Tuple[str, str]:
            """Run comprehensive smart analysis across multiple instance types"""
            print(f"\n[BRAIN] Smart Analysis Mode - Analyzing Multiple Instance Types")
            print("=" * 65)
            
            # Get a sample user's credentials for analysis
            sample_creds = self._get_sample_credentials()
            if not sample_creds:
                print(f"{Symbols.ERROR} No credentials available for analysis. Using default selection.")
                capacity_type = self.select_capacity_type_ec2()
                return default_type, capacity_type
            
            access_key, secret_key, region = sample_creds
            
            # Analyze top instance types
            candidate_types = self.ami_config['allowed_instance_types'][:5]  # Analyze top 5
            
            print(f"{Symbols.SCAN} Analyzing {len(candidate_types)} instance types in {region}...")
            print("This may take 30-60 seconds...\n")
            
            analysis_results = []
            
            for instance_type in candidate_types:
                print(f"   Analyzing {instance_type}...", end=" ", flush=True)
                
                # Simple analysis without external dependencies
                is_available, report = self._simple_spot_analysis(instance_type, region, access_key, secret_key)
                
                print("[OK]" if is_available else "[ERROR]")
                
                analysis_results.append({
                    'instance_type': instance_type,
                    'available': is_available,
                    'report': report
                })
            
            # Present results
            print(f"\n{Symbols.STATS} Analysis Results:")
            print("=" * 50)
            
            recommended = [r for r in analysis_results if r['available']]
            not_recommended = [r for r in analysis_results if not r['available']]
            
            if recommended:
                print(f"{Symbols.OK} Recommended for Spot ({len(recommended)} types):")
                for i, result in enumerate(recommended, 1):
                    print(f"   {i}. {result['instance_type']}")
            
            if not_recommended:
                print(f"\n{Symbols.ERROR} Not Recommended for Spot ({len(not_recommended)} types):")
                for result in not_recommended:
                    print(f"   • {result['instance_type']}")
            
            # Let user choose
            if recommended:
                print(f"\n{Symbols.TARGET} Recommendations:")
                for i, result in enumerate(recommended, 1):
                    print(f"  {i}. Use {result['instance_type']} with Spot pricing")
                
                print(f"  {len(recommended) + 1}. Use {default_type} with On-Demand pricing")
                print(f"  {len(recommended) + 2}. Manual selection")
                
                while True:
                    try:
                        choice = input(f"\n[#] Select recommendation (1-{len(recommended) + 2}): ").strip()
                        choice_num = int(choice)
                        
                        if 1 <= choice_num <= len(recommended):
                            selected_type = recommended[choice_num - 1]['instance_type']
                            return selected_type, 'spot'
                        
                        elif choice_num == len(recommended) + 1:
                            return default_type, 'on-demand'
                        
                        elif choice_num == len(recommended) + 2:
                            return self._manual_selection_with_analysis(analysis_results)
                        
                        else:
                            print(f"{Symbols.ERROR} Invalid choice. Please enter 1-{len(recommended) + 2}")
                            
                    except ValueError:
                        print("[ERROR] Invalid input. Please enter a number.")
            else:
                print(f"\n{Symbols.WARN}  No instance types recommended for Spot pricing.")
                print(f"   Using {default_type} with On-Demand pricing.")
                return default_type, 'on-demand'

    def _get_sample_credentials(self) -> Optional[Tuple[str, str, str]]:
            """Get sample credentials for analysis"""
            try:
                for account_data in self.credentials_data.get('accounts', {}).values():
                    for user_data in account_data.get('users', []):
                        access_key = user_data.get('access_key_id')
                        secret_key = user_data.get('secret_access_key')
                        region = user_data.get('region')
                        
                        if access_key and secret_key and region:
                            return access_key, secret_key, region
                
                return None
                
            except Exception as e:
                self.log_operation('ERROR', f"Error getting sample credentials: {e}")
                return None
            
    def _simple_spot_analysis(self, instance_type: str, region: str, access_key: str, secret_key: str) -> Tuple[bool, str]:
        """Enhanced spot availability analysis using dynamic configuration"""
        try:
            # Validate instance type
            is_valid, validation_msg = self.instance_config.validate_instance_type(instance_type)
            if not is_valid:
                return False, f"{Symbols.ERROR} {validation_msg}"
            
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Get spot price history
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)
            
            self.log_operation('INFO', f"Fetching spot price history for {instance_type} in {region}")
            
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=['Linux/UNIX'],
                StartTime=start_time,
                EndTime=end_time,
                MaxResults=200
            )
            
            prices = response.get('SpotPriceHistory', [])
            
            if not prices:
                return False, f"{Symbols.ERROR} No spot pricing data available for {instance_type} in {region}"
            
            # Calculate metrics using dynamic configuration
            price_values = [float(p['SpotPrice']) for p in prices]
            current_price = price_values[0]
            avg_price = sum(price_values) / len(price_values)
            min_price = min(price_values)
            max_price = max(price_values)
            price_volatility = self._calculate_price_volatility(price_values)
            
            # Get AZ data
            az_data = {}
            for p in prices[:20]:
                az = p['AvailabilityZone']
                price = float(p['SpotPrice'])
                if az not in az_data:
                    az_data[az] = []
                az_data[az].append(price)
            
            # Calculate AZ metrics
            az_metrics = {}
            for az, az_prices in az_data.items():
                az_metrics[az] = {
                    'current_price': az_prices[0],
                    'avg_price': sum(az_prices) / len(az_prices),
                    'data_points': len(az_prices)
                }
            
            # Get dynamic pricing and calculations
            on_demand_price = self.instance_config.get_pricing_for_region(instance_type, region)
            interruption_rate = self.instance_config.calculate_interruption_rate(instance_type, price_volatility)
            performance_score = self.instance_config.calculate_performance_score(instance_type)
            
            # Calculate savings
            if on_demand_price > 0:
                current_savings = ((on_demand_price - current_price) / on_demand_price) * 100
                avg_savings = ((on_demand_price - avg_price) / on_demand_price) * 100
                max_savings = ((on_demand_price - min_price) / on_demand_price) * 100
            else:
                current_savings = avg_savings = max_savings = 0
            
            # Get analysis thresholds
            thresholds = self.instance_config.get_analysis_thresholds()
            
            # Calculate availability score
            availability_score = self._calculate_availability_score(len(az_data), price_volatility, current_savings)
            
            # Determine recommendation using dynamic thresholds
            is_recommended = (
                len(az_data) >= thresholds['min_availability_zones'] and 
                current_savings >= thresholds['min_savings_percentage'] and 
                interruption_rate <= thresholds['max_interruption_rate'] and 
                availability_score >= thresholds['min_confidence_score'] and
                len(prices) >= thresholds['min_data_points']
            )
            
            # Create detailed report
            report = self._create_detailed_spot_report_dynamic(
                instance_type, region, current_price, avg_price, min_price, max_price,
                on_demand_price, current_savings, avg_savings, max_savings,
                price_volatility, interruption_rate, availability_score,
                az_metrics, len(prices), is_recommended, performance_score, thresholds
            )
            
            return is_recommended, report
            
        except Exception as e:
            error_msg = f"{Symbols.ERROR} Analysis failed for {instance_type}: {str(e)}"
            self.log_operation('ERROR', error_msg)
            return False, error_msg
            
    def _create_detailed_spot_report_dynamic(self, instance_type: str, region: str, current_price: float, 
                                            avg_price: float, min_price: float, max_price: float,
                                            on_demand_price: float, current_savings: float, avg_savings: float, 
                                            max_savings: float, price_volatility: float, interruption_rate: float,
                                            availability_score: float, az_metrics: dict, data_points: int, 
                                            is_recommended: bool, performance_score: float, thresholds: dict) -> str:
        """Create detailed spot analysis report with clean, consistent table formatting"""
        
        # Get instance specifications
        instance_specs = self.instance_config.get_instance_specs(instance_type)
        family_specs = self.instance_config.get_family_specs(instance_specs.get('family'))
        
        status = f"{Symbols.OK} RECOMMENDED" if is_recommended else f"{Symbols.ERROR} NOT RECOMMENDED"
        status_color = "🟢" if is_recommended else "🔴"
        
        # Get cost analysis
        cost_analysis = self.instance_config.get_cost_analysis(instance_type, region)
        
        report = f"""
    {status_color} DYNAMIC SPOT ANALYSIS REPORT FOR {instance_type.upper()} IN {region.upper()}
    {'='*80}

    💻 INSTANCE SPECIFICATIONS
    ┌──────────────────────┬──────────────────┬──────────────────┬──────────────────┐
    │ Specification        │ Value            │ Family Info      │ Performance      │
    ├──────────────────────┼──────────────────┼──────────────────┼──────────────────┤
    │ vCPUs                │ {instance_specs.get('vcpus', 'N/A'):<14}  │ {family_specs.get('category', 'Unknown').replace('_', ' ').title()[:14]:<14}  │ Score: {performance_score:<9.1f} │
    │ Memory (GB)          │ {str(instance_specs.get('memory_gb', 'N/A')):<14}  │ {family_specs.get('processor', 'Unknown')[:14]:<14}  │ Family: {instance_specs.get('family', 'N/A'):<8} │
    │ Network Performance  │ {instance_specs.get('network_performance', 'Unknown')[:14]:<14}  │ EBS: {str(instance_specs.get('ebs_optimized', False)):<11} │ Size: {instance_specs.get('size', 'N/A'):<10}   │
    └──────────────────────┴──────────────────┴──────────────────┴──────────────────┘

    [STATS] PRICING ANALYSIS
    ┌──────────────────────┬──────────────────┬──────────────────┬──────────────────┐
    │ Time Period          │ Spot Cost        │ On-Demand Cost   │ Savings          │
    ├──────────────────────┼──────────────────┼──────────────────┼──────────────────┤
    │ Hourly               │ ${current_price:<13.4f}  │ ${cost_analysis.get('hourly_cost', on_demand_price):<13.4f}  │ {current_savings:<13.1f}% │
    │ Daily (24hrs)        │ ${current_price * 24:<13.2f}  │ ${cost_analysis.get('daily_cost', on_demand_price * 24):<13.2f}  │ ${cost_analysis.get('daily_cost', on_demand_price * 24) - (current_price * 24):<13.2f}  │
    │ Weekly (7 days)      │ ${current_price * 24 * 7:<13.2f}  │ ${cost_analysis.get('weekly_cost', on_demand_price * 24 * 7):<13.2f}  │ ${cost_analysis.get('weekly_cost', on_demand_price * 24 * 7) - (current_price * 24 * 7):<13.2f}  │
    │ Monthly (730hrs)     │ ${current_price * 730:<13.2f}  │ ${cost_analysis.get('monthly_cost', on_demand_price * 730):<13.2f}  │ ${cost_analysis.get('monthly_cost', on_demand_price * 730) - (current_price * 730):<13.2f}  │
    │ Annual (365 days)    │ ${current_price * 24 * 365:<13.2f}  │ ${cost_analysis.get('annual_cost', on_demand_price * 24 * 365):<13.2f}  │ ${cost_analysis.get('annual_cost', on_demand_price * 24 * 365) - (current_price * 24 * 365):<13.2f}  │
    ├──────────────────────┼──────────────────┼──────────────────┼──────────────────┤
    │ 7-Day Average        │ ${avg_price:<13.4f}  │ ${cost_analysis.get('hourly_cost', on_demand_price):<13.4f}  │ {avg_savings:<13.1f}% │
    │ 7-Day Range          │ ${min_price:.4f}-{max_price:.4f}   │ Fixed Rate       │ Max: {max_savings:<8.1f}% │
    └──────────────────────┴──────────────────┴──────────────────┴──────────────────┘

    [TARGET] RISK & AVAILABILITY METRICS
    ┌──────────────────────┬──────────────────┬──────────────────┬──────────────────┐
    │ Metric               │ Current Value    │ Threshold        │ Status           │
    ├──────────────────────┼──────────────────┼──────────────────┼──────────────────┤
    │ Available AZs        │ {len(az_metrics):<14} zones │ ≥{thresholds['min_availability_zones']:<13} zones │ {self._get_threshold_status(len(az_metrics), thresholds['min_availability_zones'], True):<14} │
    │ Interruption Rate    │ {interruption_rate:<13.1%}  │ ≤{thresholds['max_interruption_rate']:<13.1%}  │ {self._get_threshold_status(interruption_rate, thresholds['max_interruption_rate'], False):<14} │
    │ Price Volatility     │ {price_volatility:<13.1%}  │ ≤{thresholds['price_volatility_threshold']:<13.1%}  │ {self._get_threshold_status(price_volatility, thresholds['price_volatility_threshold'], False):<14} │
    │ Savings Potential    │ {current_savings:<13.1f}% │ ≥{thresholds['min_savings_percentage']:<13.1f}% │ {self._get_threshold_status(current_savings, thresholds['min_savings_percentage'], True):<14} │
    │ Availability Score   │ {availability_score:<13.1%}  │ ≥{thresholds['min_confidence_score']:<13.1%}  │ {self._get_threshold_status(availability_score, thresholds['min_confidence_score'], True):<14} │
    │ Data Points          │ {data_points:<14} samples │ ≥{thresholds['min_data_points']:<13} samples │ {self._get_threshold_status(data_points, thresholds['min_data_points'], True):<14} │
    └──────────────────────┴──────────────────┴──────────────────┴──────────────────┘
    """

        # Add AZ breakdown if multiple AZs
        if len(az_metrics) > 1:
            report += f"""
    {Symbols.REGION} AVAILABILITY ZONE BREAKDOWN
    ┌─────────────────┬──────────────────┬──────────────────┬──────────────────┐
    │ Zone            │ Current Price    │ Avg Price (7d)   │ Monthly Savings  │
    ├─────────────────┼──────────────────┼──────────────────┼──────────────────┤"""
            
            for az, metrics in sorted(az_metrics.items()):
                az_savings = ((on_demand_price - metrics['current_price']) / on_demand_price) * 100 if on_demand_price > 0 else 0
                monthly_az_savings = (on_demand_price - metrics['current_price']) * 730
                report += f"""
    │ {az:<15} │ ${metrics['current_price']:<13.4f}  │ ${metrics['avg_price']:<13.4f}  │ ${monthly_az_savings:<7.2f} ({az_savings:<4.1f}%) │"""
            
            report += """
    └─────────────────┴──────────────────┴──────────────────┴──────────────────┘"""

        # Recommendation summary
        report += f"""

    {Symbols.TIP} RECOMMENDATION SUMMARY
    {status}

    {Symbols.LIST} Cost Analysis:"""
        
        if is_recommended:
            monthly_savings = cost_analysis.get('monthly_cost', on_demand_price * 730) - (current_price * 730)
            annual_savings = cost_analysis.get('annual_cost', on_demand_price * 24 * 365) - (current_price * 24 * 365)
            
            report += f"""
    {Symbols.OK} All thresholds met
    {Symbols.COST} Cost Savings:
        • Monthly: ${monthly_savings:.2f} ({current_savings:.1f}% reduction)
        • Annual: ${annual_savings:.2f}
    {Symbols.OK} Multi-AZ: {len(az_metrics)} zones available
    {Symbols.OK} Low risk: {interruption_rate:.1%} interruption rate
    {Symbols.OK} Stable: {price_volatility:.1%} price volatility
    {Symbols.OK} Confident: {availability_score:.1%} score

    {Symbols.START} RECOMMENDATION: Use SPOT instances for cost optimization!"""
        else:
            failed_checks = []
            if len(az_metrics) < thresholds['min_availability_zones']:
                failed_checks.append(f"   {Symbols.ERROR} AZ coverage: {len(az_metrics)} < {thresholds['min_availability_zones']}")
            if current_savings < thresholds['min_savings_percentage']:
                failed_checks.append(f"   {Symbols.ERROR} Savings: {current_savings:.1f}% < {thresholds['min_savings_percentage']}%")
            if interruption_rate > thresholds['max_interruption_rate']:
                failed_checks.append(f"   {Symbols.ERROR} Interruption: {interruption_rate:.1%} > {thresholds['max_interruption_rate']:.1%}")
            if availability_score < thresholds['min_confidence_score']:
                failed_checks.append(f"   {Symbols.ERROR} Confidence: {availability_score:.1%} < {thresholds['min_confidence_score']:.1%}")
            
            report += "\n".join(failed_checks)
            report += f"\n\n{Symbols.WARN}  RECOMMENDATION: Use ON-DEMAND instances for reliability."

        report += f"""

    [STATS] Analysis Info:
    • Version: {self.instance_config.config_data.get('metadata', {}).get('version', 'Unknown')}
    • Data: {data_points} samples over 7 days
    • Region: {region}
    • User: varadharajaan
    • Time: 2025-06-10 17:38:00 UTC
    """

        return report

    # Add these helper methods for enhanced analysis
    def _get_confidence_level(self, data_points: int, az_count: int) -> str:
        """Calculate confidence level based on data and AZ coverage"""
        if data_points >= 100 and az_count >= 3:
            return "Very High"
        elif data_points >= 50 and az_count >= 2:
            return "High"
        elif data_points >= 20:
            return "Medium"
        else:
            return "Low"

    def _get_confidence_status(self, data_points: int, az_count: int) -> str:
        """Get confidence status for analysis"""
        confidence = self._get_confidence_level(data_points, az_count)
        if confidence in ["Very High", "High"]:
            return "[OK] RELIABLE"
        elif confidence == "Medium":
            return "[WARN]  MODERATE"
        else:
            return "[ERROR] LIMITED"
    def _get_threshold_status(self, value: float, threshold: float, higher_is_better: bool) -> str:
        """Get threshold status indicator"""
        if higher_is_better:
            return "[OK] PASS" if value >= threshold else "[ERROR] FAIL"
        else:
            return "[OK] PASS" if value <= threshold else "[ERROR] FAIL"

    def _create_detailed_spot_report(self, instance_type: str, region: str, current_price: float, 
                                    avg_price: float, min_price: float, max_price: float,
                                    on_demand_price: float, current_savings: float, avg_savings: float, 
                                    max_savings: float, price_volatility: float, interruption_rate: float,
                                    availability_score: float, az_metrics: dict, data_points: int, 
                                    is_recommended: bool) -> str:
        """Create a detailed spot analysis report with formatted tables"""
        
        status = "[OK] RECOMMENDED" if is_recommended else "[ERROR] NOT RECOMMENDED"
        status_color = "🟢" if is_recommended else "🔴"
        
        report = f"""
    {status_color} SPOT ANALYSIS REPORT FOR {instance_type.upper()} IN {region.upper()}
    {'='*80}

    [STATS] PRICING OVERVIEW
    ┌─────────────────────────┬─────────────────┬─────────────────┬─────────────────┐
    │ Metric                  │ Current         │ Average (7d)    │ Range (7d)      │
    ├─────────────────────────┼─────────────────┼─────────────────┼─────────────────┤
    │ Spot Price              │ ${current_price:>7.4f}/hr    │ ${avg_price:>7.4f}/hr    │ ${min_price:.4f}-${max_price:.4f}   │
    │ On-Demand Price         │ ${on_demand_price:>7.4f}/hr    │ ${on_demand_price:>7.4f}/hr    │ Fixed           │
    │ Current Savings         │ {current_savings:>10.1f}%     │ {avg_savings:>10.1f}%     │ Max: {max_savings:.1f}%    │
    │ Monthly Savings (est.)  │ ${(on_demand_price - current_price) * 730:>10.2f}     │ ${(on_demand_price - avg_price) * 730:>10.2f}     │ Est. 730hrs     │
    └─────────────────────────┴─────────────────┴─────────────────┴─────────────────┘

    [TARGET] AVAILABILITY & RISK METRICS
    ┌─────────────────────────┬─────────────────┬─────────────────┬─────────────────┐
    │ Metric                  │ Value           │ Rating          │ Impact          │
    ├─────────────────────────┼─────────────────┼─────────────────┼─────────────────┤
    │ Available AZs           │ {len(az_metrics):>8} zones     │ {self._get_az_rating(len(az_metrics)):>12}    │ {self._get_az_impact(len(az_metrics)):>12}    │
    │ Interruption Rate       │ {interruption_rate:>10.1%}     │ {self._get_interruption_rating(interruption_rate):>12}    │ {self._get_interruption_impact(interruption_rate):>12}    │
    │ Price Volatility        │ {price_volatility:>10.1%}     │ {self._get_volatility_rating(price_volatility):>12}    │ {self._get_volatility_impact(price_volatility):>12}    │
    │ Availability Score      │ {availability_score:>10.1%}     │ {self._get_score_rating(availability_score):>12}    │ Overall         │
    │ Data Points             │ {data_points:>8} samples   │ {self._get_data_rating(data_points):>12}    │ Confidence      │
    └─────────────────────────┴─────────────────┴─────────────────┴─────────────────┘
    """

        # Add AZ-specific breakdown if multiple AZs available
        if len(az_metrics) > 1:
            report += f"""
    {Symbols.REGION} AVAILABILITY ZONE BREAKDOWN
    ┌─────────────────────┬─────────────────┬─────────────────┬─────────────────┐
    │ Availability Zone   │ Current Price   │ Avg Price (7d)  │ Savings vs OD   │
    ├─────────────────────┼─────────────────┼─────────────────┼─────────────────┤"""
            
            for az, metrics in sorted(az_metrics.items()):
                az_savings = ((on_demand_price - metrics['current_price']) / on_demand_price) * 100 if on_demand_price > 0 else 0
                report += f"""
    │ {az:<19} │ ${metrics['current_price']:>7.4f}/hr    │ ${metrics['avg_price']:>7.4f}/hr    │ {az_savings:>10.1f}%     │"""
            
            report += """
    └─────────────────────┴─────────────────┴─────────────────┴─────────────────┘"""

        # Add recommendation summary
        report += f"""

    {Symbols.TIP} RECOMMENDATION SUMMARY
    {status}

    {Symbols.LIST} Key Factors:
    """
        
        if is_recommended:
            report += f"""   {Symbols.OK} Excellent savings potential: {current_savings:.1f}% below on-demand
    {Symbols.OK} Available across {len(az_metrics)} availability zones
    {Symbols.OK} Low interruption risk: {interruption_rate:.1%}
    {Symbols.OK} Good price stability: {price_volatility:.1%} volatility
    {Symbols.OK} High availability score: {availability_score:.1%}

    {Symbols.START} RECOMMENDED ACTION: Use SPOT instances for significant cost savings!"""
        else:
            reasons = []
            if current_savings < 15:
                reasons.append(f"   {Symbols.ERROR} Low savings potential: {current_savings:.1f}% (minimum 15% recommended)")
            if len(az_metrics) < 2:
                reasons.append(f"   {Symbols.ERROR} Limited AZ availability: {len(az_metrics)} zone(s) (minimum 2 recommended)")
            if interruption_rate > 0.12:
                reasons.append(f"   {Symbols.ERROR} High interruption risk: {interruption_rate:.1%} (maximum 12% recommended)")
            if availability_score < 0.6:
                reasons.append(f"   {Symbols.ERROR} Low availability score: {availability_score:.1%} (minimum 60% recommended)")
            
            report += "\n".join(reasons)
            report += f"\n\n{Symbols.WARN}  RECOMMENDED ACTION: Consider ON-DEMAND instances for better reliability."

        report += f"""

    [STATS] Analysis based on {data_points} data points over 7 days in {region}
    🕒 Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
    """

        return report


    def get_alternative_instances_dynamic(self, target_instance: str, region: str) -> List[Dict]:
        """Get alternative instances using dynamic configuration"""
        try:
            # Get similar instances from config
            similar_instances = self.instance_config.get_similar_instances(target_instance, max_results=10)
            
            alternatives = []
            for similar in similar_instances:
                instance_type = similar['instance_type']
                specs = similar['specs']
                
                # Get pricing and performance data
                price = self.instance_config.get_pricing_for_region(instance_type, region)
                performance_score = similar['performance_score']
                similarity_score = similar['similarity_score']
                
                # Calculate overall recommendation score
                cost_efficiency = performance_score / max(price, 0.001)
                overall_score = (similarity_score * 0.4 + cost_efficiency * 0.1 + performance_score * 0.01) * 10
                
                alternatives.append({
                    'instance_type': instance_type,
                    'family': specs.get('family'),
                    'vcpus': specs.get('vcpus'),
                    'memory_gb': specs.get('memory_gb'),
                    'performance_score': performance_score,
                    'cost_per_hour': price,
                    'similarity_score': similarity_score,
                    'overall_score': overall_score,
                    'reason': f"Similar {specs.get('family')} family instance"
                })
            
            # Sort by overall score
            alternatives.sort(key=lambda x: x['overall_score'], reverse=True)
            return alternatives[:5]
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting dynamic alternatives: {e}")
            return []

    def display_instance_menu_dynamic(self):
        """Dynamic instance type selection menu using configuration"""
        try:
            available_types = self.instance_config.get_all_instance_types()
            
            # Group by categories
            categories = {}
            for instance_type in available_types:
                specs = self.instance_config.get_instance_specs(instance_type)
                family = specs.get('family')
                family_specs = self.instance_config.get_family_specs(family)
                category = family_specs.get('category', 'unknown') if family_specs else 'unknown'
                
                if category not in categories:
                    categories[category] = []
                categories[category].append(instance_type)
            
            self.log_operation('INFO', f"Displaying dynamic instance menu - {len(available_types)} types available")
            
            print("\n🖥️  Available Instance Types (Dynamic Configuration):")
            print("=" * 70)
            
            all_types = []
            type_index = 1
            
            for category, types in sorted(categories.items()):
                if category == 'unknown':
                    continue
                    
                print(f"\n📂 {category.replace('_', ' ').title()} ({len(types)} types):")
                print("-" * 50)
                
                for instance_type in sorted(types):
                    specs = self.instance_config.get_instance_specs(instance_type)
                    vcpus = specs.get('vcpus')
                    memory = specs.get('memory_gb')
                    family = specs.get('family')
                    
                    print(f"  {type_index:2}. {instance_type:<12} | {vcpus:2} vCPUs | {memory:>5}GB RAM | {family} family")
                    all_types.append(instance_type)
                    type_index += 1
            
            print(f"\n{'='*70}")
            print(f"{Symbols.STATS} Total: {len(all_types)} instance types from {len(categories)} categories")
            
            while True:
                try:
                    choice = input(f"\n[#] Select instance type (1-{len(all_types)}) or press Enter for smart analysis: ").strip()
                    
                    if not choice:
                        # Use first available type as default for smart analysis
                        default_type = all_types[0] if all_types else 't3.micro'
                        return default_type
                    
                    choice_num = int(choice)
                    if 1 <= choice_num <= len(all_types):
                        selected_type = all_types[choice_num - 1]
                        
                        # Show instance details
                        specs = self.instance_config.get_instance_specs(selected_type)
                        cost_analysis = self.instance_config.get_cost_analysis(selected_type, 'us-east-1')  # Default region
                        
                        print(f"\n{Symbols.OK} Selected: {selected_type}")
                        print(f"   💻 {specs.get('vcpus')} vCPUs, {specs.get('memory_gb')}GB RAM")
                        print(f"   {Symbols.COST} ~${cost_analysis.get('monthly_cost', 0):.2f}/month (us-east-1)")
                        
                        self.log_operation('INFO', f"User selected instance type: {selected_type}")
                        return selected_type
                    else:
                        print(f"{Symbols.ERROR} Invalid choice. Please enter 1-{len(all_types)}")
                        
                except ValueError:
                    print("[ERROR] Invalid input. Please enter a number.")
                    
        except Exception as e:
            self.log_operation('ERROR', f"Error in dynamic instance menu: {e}")
            # Fallback to basic selection
            return 't3.micro'
    
    def _get_on_demand_price_simple(self, instance_type: str) -> float:
        """Get simplified on-demand pricing"""
        # Enhanced pricing data with more instance types
        pricing_data = {
            # T3 Family - Burstable Performance
            't3.nano': 0.0052, 't3.micro': 0.0104, 't3.small': 0.0208,
            't3.medium': 0.0416, 't3.large': 0.0832, 't3.xlarge': 0.1664,
            't3.2xlarge': 0.3328,
            
            # T4g Family - ARM-based Burstable (typically 20% cheaper)
            't4g.nano': 0.0042, 't4g.micro': 0.0084, 't4g.small': 0.0168,
            't4g.medium': 0.0336, 't4g.large': 0.0672, 't4g.xlarge': 0.1344,
            
            # C5 Family - Compute Optimized
            'c5.large': 0.085, 'c5.xlarge': 0.17, 'c5.2xlarge': 0.34,
            'c5.4xlarge': 0.68, 'c5.9xlarge': 1.53,
            
            # C6a Family - Latest Compute Optimized
            'c6a.large': 0.0864, 'c6a.xlarge': 0.1728, 'c6a.2xlarge': 0.3456,
            'c6a.4xlarge': 0.6912, 'c6a.8xlarge': 1.3824,
            
            # M5 Family - General Purpose
            'm5.large': 0.096, 'm5.xlarge': 0.192, 'm5.2xlarge': 0.384,
            'm5.4xlarge': 0.768, 'm5.8xlarge': 1.536,
            
            # M6i Family - Latest General Purpose
            'm6i.large': 0.0864, 'm6i.xlarge': 0.1728, 'm6i.2xlarge': 0.3456,
            'm6i.4xlarge': 0.6912, 'm6i.8xlarge': 1.3824,
            
            # R5 Family - Memory Optimized
            'r5.large': 0.126, 'r5.xlarge': 0.252, 'r5.2xlarge': 0.504,
            'r5.4xlarge': 1.008, 'r5.8xlarge': 2.016
        }
        
        return pricing_data.get(instance_type, 0.05)  # Default fallback

    def _calculate_price_volatility(self, prices: list) -> float:
        """Calculate price volatility as coefficient of variation"""
        if len(prices) < 2:
            return 0.0
        
        import statistics
        mean_price = statistics.mean(prices)
        if mean_price == 0:
            return 0.0
        
        std_dev = statistics.stdev(prices)
        return (std_dev / mean_price)

    def _estimate_interruption_rate(self, instance_type: str, volatility: float) -> float:
        """Estimate interruption rate based on instance type and price volatility"""
        # Base interruption rates by instance family
        base_rates = {
            't3': 0.05, 't4g': 0.04, 'c5': 0.03, 'c6a': 0.025,
            'm5': 0.04, 'm6i': 0.035, 'r5': 0.06, 'r6i': 0.055
        }
        
        family = instance_type.split('.')[0]
        base_rate = base_rates.get(family, 0.05)
        
        # Adjust for instance size (larger = more stable)
        if '8xlarge' in instance_type or '12xlarge' in instance_type:
            base_rate *= 0.6
        elif '4xlarge' in instance_type:
            base_rate *= 0.7
        elif '2xlarge' in instance_type:
            base_rate *= 0.8
        elif 'xlarge' in instance_type:
            base_rate *= 0.85
        elif 'large' in instance_type:
            base_rate *= 0.9
        elif 'nano' in instance_type or 'micro' in instance_type:
            base_rate *= 1.1
        
        # Adjust for price volatility (higher volatility = higher interruption risk)
        volatility_multiplier = 1 + (volatility * 2)  # Double the volatility impact
        
        return min(base_rate * volatility_multiplier, 0.25)  # Cap at 25%

    def _calculate_availability_score(self, az_count: int, volatility: float, savings: float) -> float:
        """Calculate overall availability score"""
        # AZ score (0-0.4)
        az_score = min(az_count / 4, 1.0) * 0.4
        
        # Stability score (0-0.3)
        stability_score = max(0, 1 - (volatility * 5)) * 0.3
        
        # Savings score (0-0.3)
        savings_score = min(max(savings, 0) / 70, 1.0) * 0.3
        
        return az_score + stability_score + savings_score

    # Rating helper methods
    def _get_az_rating(self, az_count: int) -> str:
        if az_count >= 3: return "Excellent"
        elif az_count >= 2: return "Good"
        elif az_count >= 1: return "Fair"
        else: return "Poor"

    def _get_az_impact(self, az_count: int) -> str:
        if az_count >= 3: return "High Avail."
        elif az_count >= 2: return "Good Avail."
        else: return "Limited"

    def _get_interruption_rating(self, rate: float) -> str:
        if rate <= 0.03: return "Excellent"
        elif rate <= 0.06: return "Good"
        elif rate <= 0.12: return "Fair"
        else: return "Poor"

    def _get_interruption_impact(self, rate: float) -> str:
        if rate <= 0.03: return "Very Stable"
        elif rate <= 0.06: return "Stable"
        elif rate <= 0.12: return "Moderate"
        else: return "Unstable"

    def _get_volatility_rating(self, volatility: float) -> str:
        if volatility <= 0.05: return "Excellent"
        elif volatility <= 0.10: return "Good"
        elif volatility <= 0.20: return "Fair"
        else: return "Poor"

    def _get_volatility_impact(self, volatility: float) -> str:
        if volatility <= 0.05: return "Very Stable"
        elif volatility <= 0.10: return "Stable"
        elif volatility <= 0.20: return "Moderate"
        else: return "Volatile"

    def _get_score_rating(self, score: float) -> str:
        if score >= 0.8: return "Excellent"
        elif score >= 0.6: return "Good"
        elif score >= 0.4: return "Fair"
        else: return "Poor"

    def _get_data_rating(self, data_points: int) -> str:
        if data_points >= 100: return "High"
        elif data_points >= 50: return "Good"
        elif data_points >= 20: return "Fair"
        else: return "Low"

    def _simple_spot_analysis_bk(self, instance_type: str, region: str, access_key: str, secret_key: str) -> Tuple[bool, str]:
            """Simple spot availability analysis using basic AWS APIs"""
            try:
                ec2_client = boto3.client(
                    'ec2',
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name=region
                )
                
                # Get spot price history for last 24 hours
                end_time = datetime.now()
                start_time = end_time - timedelta(hours=24)
                
                response = ec2_client.describe_spot_price_history(
                    InstanceTypes=[instance_type],
                    ProductDescriptions=['Linux/UNIX'],
                    StartTime=start_time,
                    EndTime=end_time,
                    MaxResults=10
                )
                
                prices = response.get('SpotPriceHistory', [])
                
                if not prices:
                    return False, f"{Symbols.ERROR} No spot pricing data available for {instance_type}"
                
                current_price = float(prices[0]['SpotPrice'])
                avg_price = sum(float(p['SpotPrice']) for p in prices) / len(prices)
                available_azs = list(set(p['AvailabilityZone'] for p in prices))
                
                # Simple recommendation logic
                is_recommended = len(available_azs) >= 2 and current_price > 0
                
                report = f"""
    [STATS] Spot Analysis for {instance_type}:
    Current Price: ${current_price:.4f}/hour
    Average Price: ${avg_price:.4f}/hour
    Available AZs: {len(available_azs)} ({', '.join(available_azs[:3])})
    Status: {f'{Symbols.OK} RECOMMENDED' if is_recommended else f'{Symbols.ERROR} NOT RECOMMENDED'}
    """
                
                return is_recommended, report
                
            except Exception as e:
                return False, f"{Symbols.ERROR} Analysis failed for {instance_type}: {str(e)}"

    def _analyze_and_confirm_instance(self, instance_type: str) -> Tuple[str, str]:
            """Analyze a specific instance type and get user confirmation"""
            sample_creds = self._get_sample_credentials()
            if not sample_creds:
                print("[ERROR] No credentials available for analysis.")
                capacity_type = self.select_capacity_type_ec2()
                return instance_type, capacity_type
            
            access_key, secret_key, region = sample_creds
            
            print(f"\n{Symbols.SCAN} Analyzing {instance_type} in {region}...")
            
            is_available, report = self._simple_spot_analysis(instance_type, region, access_key, secret_key)
            
            print(report)
            
            if is_available:
                print(f"\n{Symbols.OK} {instance_type} is recommended for Spot pricing!")
                use_spot = input("[START] Use Spot pricing? (Y/n): ").lower().strip()
                if use_spot != 'n':
                    return instance_type, 'spot'
            else:
                print(f"\n{Symbols.WARN}  {instance_type} is not recommended for Spot pricing.")
            
            capacity_type = self.select_capacity_type_ec2()
            return instance_type, capacity_type

    def _handle_custom_instance_type(self) -> Tuple[str, str]:
            """Handle custom instance type input"""
            print(f"\n🔧 Custom Instance Type")
            print("=" * 30)
            
            while True:
                custom_type = input("Enter instance type (e.g., t3.medium): ").strip()
                
                if not custom_type:
                    print("[ERROR] Please enter a valid instance type.")
                    continue
                
                # Basic validation
                if '.' not in custom_type:
                    print("[ERROR] Invalid format. Use format like 't3.medium'")
                    continue
                
                print(f"\n{Symbols.SCAN} Analyze {custom_type} for spot availability? (Y/n): ", end="")
                analyze = input().lower().strip()
                
                if analyze != 'n':
                    return self._analyze_and_confirm_instance(custom_type)
                else:
                    capacity_type = self.select_capacity_type_ec2()
                    return custom_type, capacity_type

    def _manual_selection_with_analysis(self, analysis_results: List[Dict]) -> Tuple[str, str]:
            """Manual selection with analysis context"""
            print(f"\n🎛️  Manual Selection Mode")
            print("=" * 40)
            
            for i, result in enumerate(analysis_results, 1):
                status = "[OK]" if result['available'] else f"{Symbols.ERROR}"
                print(f"  {i}. {result['instance_type']} {status}")
            
            while True:
                try:
                    choice = input(f"\n[#] Select instance type (1-{len(analysis_results)}): ").strip()
                    choice_num = int(choice)
                    
                    if 1 <= choice_num <= len(analysis_results):
                        selected_result = analysis_results[choice_num - 1]
                        selected_type = selected_result['instance_type']
                        
                        if selected_result['available']:
                            print(f"\n{Symbols.OK} {selected_type} is recommended for Spot pricing.")
                            capacity_type = 'spot'
                        else:
                            print(f"\n{Symbols.WARN}  {selected_type} is not recommended for Spot pricing.")
                            capacity_type = self.select_capacity_type_ec2()
                        
                        return selected_type, capacity_type
                    
                    else:
                        print(f"{Symbols.ERROR} Invalid choice. Please enter 1-{len(analysis_results)}")
                        
                except ValueError:
                    print("[ERROR] Invalid input. Please enter a number.")

    def generate_random_suffix(self, length=4):
        """Generate random alphanumeric suffix for unique naming"""
        characters = string.ascii_lowercase + string.digits
        return ''.join(random.choice(characters) for _ in range(length))
            
    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"ec2_creation_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ec2_operations')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)
            
            # Log initial information
            self.operation_logger.info("=" * 80)
            self.operation_logger.info("EC2 Instance Creation Session Started")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Credentials File: {self.credentials_file}")
            self.operation_logger.info(f"User Data Script: {self.userdata_file}")
            self.operation_logger.info(f"AMI Mapping File: {self.ami_mapping_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 80)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Log operation to both console and file"""
        if self.operation_logger:
            if level.upper() == 'INFO':
                self.operation_logger.info(message)
            elif level.upper() == 'WARNING':
                self.operation_logger.warning(message)
            elif level.upper() == 'ERROR':
                self.operation_logger.error(message)
            elif level.upper() == 'DEBUG':
                self.operation_logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")

    def find_latest_credentials_file(self):
        """Find the latest iam_users_credentials file based on timestamp"""
        try:
            # Look for all files matching the pattern
            pattern = "iam_users_credentials_*.json"
            matching_files = glob.glob(pattern)
            
            if not matching_files:
                self.logger.error(f"No files found matching pattern: {pattern}")
                raise FileNotFoundError(f"No IAM credentials files found matching pattern: {pattern}")
            
            self.logger.info(f"Found {len(matching_files)} credential files:")
            
            # Extract timestamps and sort
            file_timestamps = []
            for file_path in matching_files:
                # Extract timestamp from filename
                # Expected format: iam_users_credentials_YYYYMMDD_HHMMSS.json
                match = re.search(r'iam_users_credentials_(\d{8}_\d{6})\.json', file_path)
                if match:
                    timestamp_str = match.group(1)
                    try:
                        # Parse timestamp to datetime for comparison
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        file_timestamps.append((file_path, timestamp, timestamp_str))
                        self.logger.info(f"  📄 {file_path} (timestamp: {timestamp_str})")
                    except ValueError as e:
                        self.logger.warning(f"  {Symbols.WARN}  {file_path} has invalid timestamp format: {e}")
                else:
                    self.logger.warning(f"  {Symbols.WARN}  {file_path} doesn't match expected timestamp pattern")
            
            if not file_timestamps:
                raise ValueError("No valid credential files with proper timestamp format found")
            
            # Sort by timestamp (newest first)
            file_timestamps.sort(key=lambda x: x[1], reverse=True)
            
            # Get the latest file
            latest_file, latest_timestamp, latest_timestamp_str = file_timestamps[0]
            
            self.logger.info(f"{Symbols.TARGET} Selected latest file: {latest_file}")
            self.logger.info(f"{Symbols.DATE} File timestamp: {latest_timestamp_str}")
            self.logger.info(f"{Symbols.DATE} Parsed timestamp: {latest_timestamp}")
            
            # Show what files were skipped
            if len(file_timestamps) > 1:
                self.logger.info("[LIST] Other files found (older):")
                for file_path, timestamp, timestamp_str in file_timestamps[1:]:
                    self.logger.info(f"  📄 {file_path} (timestamp: {timestamp_str})")
            
            return latest_file
            
        except Exception as e:
            self.logger.error(f"Error finding latest credentials file: {e}")
            raise

    def load_configurations(self):
        """Load IAM credentials and AMI mapping configurations"""
        try:
            # Load IAM credentials from the latest file
            if not os.path.exists(self.credentials_file):
                raise FileNotFoundError(f"Credentials file '{self.credentials_file}' not found")
            
            with open(self.credentials_file, 'r', encoding='utf-8') as f:
                self.credentials_data = json.load(f)
            
            self.logger.info(f"{Symbols.OK} Credentials loaded from: {self.credentials_file}")
            
            # Extract and log metadata from credentials file
            if 'created_date' in self.credentials_data:
                self.logger.info(f"{Symbols.DATE} Credentials file created: {self.credentials_data['created_date']} {self.credentials_data.get('created_time', '')}")
            if 'created_by' in self.credentials_data:
                self.logger.info(f"👤 Credentials file created by: {self.credentials_data['created_by']}")
            if 'total_users' in self.credentials_data:
                self.logger.info(f"👥 Total users in file: {self.credentials_data['total_users']}")
            
            # Load AMI mappings
            if not os.path.exists(self.ami_mapping_file):
                raise FileNotFoundError(f"AMI mapping file '{self.ami_mapping_file}' not found")
            
            with open(self.ami_mapping_file, 'r', encoding='utf-8') as f:
                self.ami_config = json.load(f)
            
            self.logger.info(f"{Symbols.OK} AMI mappings loaded from: {self.ami_mapping_file}")
            self.logger.info(f"{Symbols.REGION} Supported regions: {list(self.ami_config['region_ami_mapping'].keys())}")
            
        except FileNotFoundError as e:
            self.logger.error(f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)

    def load_user_data_script(self):
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
                    self.logger.info(f"{Symbols.OK} Successfully read user data script using {encoding} encoding")
                    break
                except UnicodeDecodeError as e:
                    self.logger.debug(f"Failed to read with {encoding} encoding: {e}")
                    continue
                except Exception as e:
                    self.logger.debug(f"Error reading with {encoding} encoding: {e}")
                    continue
            
            if user_data_content is None:
                raise ValueError(f"Could not read {self.userdata_file} with any supported encoding")
            
            self.logger.info(f"📜 User data script loaded from: {self.userdata_file}")
            self.logger.info(f"🔤 Encoding used: {encoding_used}")
            self.logger.debug(f"📏 User data script size: {len(user_data_content)} characters")
            
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
            self.logger.error(f"User data script file error: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading user data script: {e}")
            sys.exit(1)

    def display_accounts_menu(self):
        """Display available accounts and return account selection"""
        if 'accounts' not in self.credentials_data:
            self.logger.error("No accounts found in credentials data")
            return []
        
        accounts = list(self.credentials_data['accounts'].items())
        
        self.log_operation('INFO', f"Displaying {len(accounts)} available accounts for selection")
        
        print(f"\n{Symbols.ACCOUNT} Available AWS Accounts ({len(accounts)} total):")
        print("=" * 80)
        
        total_users = 0
        regions_used = set()
        
        for i, (account_name, account_data) in enumerate(accounts, 1):
            user_count = len(account_data.get('users', []))
            total_users += user_count
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            # Collect regions used in this account
            account_regions = set()
            for user in account_data.get('users', []):
                region = user.get('region', 'unknown')
                account_regions.add(region)
                regions_used.add(region)
            
            print(f"  {i:2}. {account_name}")
            print(f"      📧 Email: {account_email}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      👥 Users: {user_count}")
            print(f"      {Symbols.REGION} Regions: {', '.join(sorted(account_regions))}")
            
            # Log account details
            self.log_operation('INFO', f"Account {i}: {account_name} ({account_id}) - {user_count} users in regions: {', '.join(sorted(account_regions))}")
            
            # Show some user details
            if user_count > 0:
                print(f"      👤 Sample users:")
                for j, user in enumerate(account_data.get('users', [])[:3], 1):  # Show first 3 users
                    real_user = user.get('real_user', {})
                    full_name = real_user.get('full_name', user.get('username', 'Unknown'))
                    region = user.get('region', 'unknown')
                    print(f"         {j}. {full_name} ({region})")
                if user_count > 3:
                    print(f"         ... and {user_count - 3} more users")
            print()
        
        print("=" * 80)
        print(f"{Symbols.STATS} Summary:")
        print(f"   [UP] Total accounts: {len(accounts)}")
        print(f"   👥 Total users: {total_users}")
        print(f"   {Symbols.REGION} All regions: {', '.join(sorted(regions_used))}")
        
        self.log_operation('INFO', f"Account summary: {len(accounts)} accounts, {total_users} total users, regions: {', '.join(sorted(regions_used))}")
        
        print(f"\n{Symbols.LOG} Selection Options:")
        print(f"   • Single accounts: 1,3,5")
        print(f"   • Ranges: 1-{len(accounts)} (accounts 1 through {len(accounts)})")
        print(f"   • Mixed: 1-2,4 (accounts 1, 2, and 4)")
        print(f"   • All accounts: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n[#] Select accounts to process: ").strip()
            
            self.log_operation('INFO', f"User input for account selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all accounts")
                return list(range(1, len(accounts) + 1))
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled account selection")
                return []
            
            try:
                selected_indices = self.parse_account_selection(selection, len(accounts))
                if selected_indices:
                    # Show what was selected
                    selected_accounts = []
                    selected_users = 0
                    selected_regions = set()
                    
                    for idx in selected_indices:
                        account_name, account_data = accounts[idx - 1]
                        user_count = len(account_data.get('users', []))
                        account_id = account_data.get('account_id', 'Unknown')
                        
                        # Get regions for this account
                        account_regions = set()
                        for user in account_data.get('users', []):
                            region = user.get('region', 'unknown')
                            account_regions.add(region)
                            selected_regions.add(region)
                        
                        selected_accounts.append({
                            'name': account_name,
                            'id': account_id,
                            'users': user_count,
                            'regions': account_regions
                        })
                        selected_users += user_count
                    
                    print(f"\n{Symbols.OK} Selected {len(selected_indices)} accounts ({selected_users} total users):")
                    print("-" * 60)
                    for i, account_info in enumerate(selected_accounts, 1):
                        print(f"   {i}. {account_info['name']}")
                        print(f"      🆔 {account_info['id']}")
                        print(f"      👥 {account_info['users']} users")
                        print(f"      {Symbols.REGION} {', '.join(sorted(account_info['regions']))}")
                    
                    print("-" * 60)
                    print(f"{Symbols.STATS} Total: {len(selected_indices)} accounts, {selected_users} users, {len(selected_regions)} regions")
                    
                    # Log selection details
                    self.log_operation('INFO', f"Selected accounts: {[acc['name'] for acc in selected_accounts]}")
                    self.log_operation('INFO', f"Selection summary: {len(selected_indices)} accounts, {selected_users} users, {len(selected_regions)} regions")
                    
                    confirm = input(f"\n{Symbols.START} Proceed with these {len(selected_indices)} accounts? (y/N): ").lower().strip()
                    self.log_operation('INFO', f"User confirmation for selection: '{confirm}'")
                    
                    if confirm == 'y':
                        return selected_indices
                    else:
                        print(f"{Symbols.ERROR} Selection cancelled, please choose again.")
                        self.log_operation('INFO', "User cancelled selection, requesting new input")
                        continue
                else:
                    print(f"{Symbols.ERROR} No valid accounts selected. Please try again.")
                    self.log_operation('WARNING', "No valid accounts selected from user input")
                    continue
                    
            except ValueError as e:
                print(f"{Symbols.ERROR} Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                self.log_operation('ERROR', f"Invalid account selection format: {e}")
                continue

    def parse_account_selection(self, selection, max_accounts):
        """Parse account selection string and return list of account indices"""
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
                    
                    if start < 1 or end > max_accounts:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_accounts})")
                    
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
                    if num < 1 or num > max_accounts:
                        raise ValueError(f"Account number {num} is out of bounds (1-{max_accounts})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid account number: {part}")
        
        return sorted(list(selected_indices))

    def get_selected_accounts_data(self, selected_indices):
        """Get account data for selected indices"""
        accounts = list(self.credentials_data['accounts'].items())
        selected_accounts = {}
        
        for idx in selected_indices:
            account_name, account_data = accounts[idx - 1]
            selected_accounts[account_name] = account_data
        
        return selected_accounts

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using specific IAM user credentials"""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the connection
            ec2_client.describe_regions(RegionNames=[region])
            self.log_operation('INFO', f"Successfully connected to EC2 in {region} using access key: {access_key[:10]}...")
            return ec2_client
            
        except ClientError as e:
            error_msg = f"Failed to connect to EC2 in {region}: {e}"
            self.log_operation('ERROR', error_msg)
            raise
        except Exception as e:
            error_msg = f"Unexpected error connecting to EC2: {e}"
            self.log_operation('ERROR', error_msg)
            raise

    def get_default_vpc(self, ec2_client, region):
        """Get the default VPC for the region"""
        try:
            vpcs = ec2_client.describe_vpcs(
                Filters=[
                    {'Name': 'is-default', 'Values': ['true']}
                ]
            )
            
            if not vpcs['Vpcs']:
                self.log_operation('ERROR', f"No default VPC found in region {region}")
                return None
            
            vpc_id = vpcs['Vpcs'][0]['VpcId']
            self.log_operation('INFO', f"Found default VPC: {vpc_id} in {region}")
            return vpc_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting default VPC in {region}: {e}")
            return None

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

    def get_default_subnet(self, ec2_client, vpc_id, region):
        """Get a default public subnet from the VPC, filtering out unsupported AZs"""
        try:
            # Load unsupported AZs for this region
            unsupported_azs = self._get_unsupported_azs(region)
            if unsupported_azs:
                self.log_operation('DEBUG', f"Filtering out unsupported AZs in {region}: {unsupported_azs}")
            
            subnets = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'default-for-az', 'Values': ['true']}
                ]
            )
            
            if not subnets['Subnets']:
                self.log_operation('ERROR', f"No default subnets found in VPC {vpc_id}")
                return None
            
            # Filter out subnets in unsupported AZs
            supported_subnets = []
            for subnet in subnets['Subnets']:
                az = subnet['AvailabilityZone']
                if az not in unsupported_azs:
                    supported_subnets.append(subnet)
                else:
                    self.log_operation('DEBUG', f"Skipping default subnet {subnet['SubnetId']} in unsupported AZ: {az}")
            
            if not supported_subnets:
                self.log_operation('ERROR', f"No supported default subnets found in VPC {vpc_id} for region {region}")
                return None
            
            # Get the first available supported subnet
            subnet_id = supported_subnets[0]['SubnetId']
            availability_zone = supported_subnets[0]['AvailabilityZone']
            
            self.log_operation('INFO', f"Selected default subnet: {subnet_id} in supported AZ: {availability_zone}")
            return subnet_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting default subnet: {e}")
            return None
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            if 'eks_config' in mapping_data and 'min_subnets_required' in mapping_data['eks_config']:
                return mapping_data['eks_config']['min_subnets_required']
            
            return 2  # Default fallback
            
        except Exception:
            return 2  # Default fallback

    def create_security_group(self, ec2_client, vpc_id, group_name, region):
        """Create a security group that allows all traffic"""
        try:
            # Check if security group already exists
            try:
                existing_sgs = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': [group_name]},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                
                if existing_sgs['SecurityGroups']:
                    sg_id = existing_sgs['SecurityGroups'][0]['GroupId']
                    self.log_operation('INFO', f"Using existing security group: {sg_id} for {group_name}")
                    return sg_id
                    
            except ClientError:
                pass
            
            # Create new security group
            response = ec2_client.create_security_group(
                GroupName=group_name,
                Description='Security group allowing all traffic for IAM user instances',
                VpcId=vpc_id
            )
            
            sg_id = response['GroupId']
            self.log_operation('INFO', f"Created new security group: {sg_id} with name: {group_name}")
            
            # Add rules to allow all traffic
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',  # All protocols
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow all traffic'}]
                    }
                ]
            )
            
            self.log_operation('INFO', f"Added all-traffic ingress rules to security group: {sg_id}")
            return sg_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Error creating security group {group_name}: {e}")
            raise

    def ask_for_spot_analysis(self):
        """Ask user if they want Spot analysis or manual selection"""
        print(f"\n{Symbols.SCAN} Spot Instance Analysis")
        print("=" * 60)
        print("Would you like to analyze Spot instance availability and pricing?")
        print("")
        print("[STATS] Spot Analysis Benefits:")
        print("   • Checks current Spot prices vs On-Demand pricing")
        print("   • Analyzes interruption frequency in each region")
        print("   • Provides intelligent recommendations per region")
        print("   • Supports mixed strategy (Spot where safe, On-Demand elsewhere)")
        print("")
        print("[LIST] Options:")
        print("   1. Yes - Perform Spot analysis and get recommendations")
        print("   2. No - I'll choose capacity type manually")
        print("=" * 60)
        
        while True:
            try:
                choice = input(f"Perform Spot analysis? (1-2) [default: Yes]: ").strip()
                
                self.log_operation('INFO', f"User spot analysis choice: '{choice}'")
                
                if not choice or choice == '1':
                    self.log_operation('INFO', "User chose to perform Spot analysis")
                    return True
                elif choice == '2':
                    self.log_operation('INFO', "User chose manual capacity selection")
                    return False
                else:
                    print(f"{Symbols.ERROR} Please enter 1 or 2")
                    self.log_operation('WARNING', f"Invalid spot analysis choice: {choice}")
            except ValueError:
                print("[ERROR] Please enter a valid number")
    def select_capacity_type_manual(self):
        """Allow user to manually select capacity type without analysis"""
        print(f"\n[LIGHTNING] Instance Capacity Type Selection")
        print("=" * 60)
        print("Available capacity types:")
        print("  1. On-Demand - Standard pricing, guaranteed availability")
        print("  2. Spot - Up to 90% savings, may be interrupted")
        print("=" * 60)
        
        while True:
            try:
                choice = input(f"Select capacity type (1-2) [default: On-Demand]: ").strip()
                
                self.log_operation('INFO', f"User manual capacity selection input: '{choice}'")
                
                if not choice or choice == '1':
                    self.log_operation('INFO', "User selected On-Demand capacity (manual)")
                    return 'on-demand'
                elif choice == '2':
                    self.log_operation('INFO', "User selected Spot capacity (manual)")
                    return 'spot'
                else:
                    print(f"{Symbols.ERROR} Please enter 1 or 2")
                    self.log_operation('WARNING', f"Invalid manual capacity choice: {choice}")
            except ValueError:
                print("[ERROR] Please enter a valid number")
    def get_spot_price_history(self, ec2_client, instance_type, region, days=7):
        """Get Spot price history to analyze price stability"""
        try:
            from datetime import datetime, timedelta
            
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            response = ec2_client.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=['Linux/UNIX'],
                StartTime=start_time,
                EndTime=end_time,
                MaxResults=100
            )
            
            prices = []
            for price_point in response['SpotPriceHistory']:
                prices.append({
                    'price': float(price_point['SpotPrice']),
                    'timestamp': price_point['Timestamp'],
                    'az': price_point['AvailabilityZone']
                })
            
            return prices
        except Exception as e:
            self.log_operation('ERROR', f"Failed to get Spot price history: {e}")
            return []

    def analyze_spot_price_stability(self, prices):
        """Analyze price stability and volatility"""
        if not prices:
            return None
        
        price_values = [p['price'] for p in prices]
        
        if len(price_values) < 2:
            return None
        
        avg_price = sum(price_values) / len(price_values)
        min_price = min(price_values)
        max_price = max(price_values)
        
        # Calculate volatility (standard deviation)
        variance = sum((p - avg_price) ** 2 for p in price_values) / len(price_values)
        volatility = variance ** 0.5
        
        # Price stability score (lower is more stable)
        volatility_percent = (volatility / avg_price) * 100 if avg_price > 0 else 100
        
        return {
            'avg_price': avg_price,
            'min_price': min_price,
            'max_price': max_price,
            'current_price': price_values[-1] if price_values else avg_price,
            'volatility_percent': volatility_percent,
            'price_trend': 'stable' if volatility_percent < 10 else 'volatile',
            'sample_count': len(price_values)
        }

    def check_spot_capacity_availability(self, ec2_client, instance_type, region):
        """Check Spot capacity availability across AZs"""
        try:
            # Get availability zones in the region
            azs_response = ec2_client.describe_availability_zones(
                Filters=[{'Name': 'state', 'Values': ['available']}]
            )
            
            availability_info = {}
            
            for az_info in azs_response['AvailabilityZones']:
                az_name = az_info['ZoneName']
                
                # Skip unsupported AZs
                unsupported_azs = self._get_unsupported_azs(region)
                if az_name in unsupported_azs:
                    continue
                
                try:
                    # Request spot fleet to check capacity (dry run)
                    response = ec2_client.request_spot_fleet(
                        DryRun=True,  # This won't actually create anything
                        SpotFleetRequestConfig={
                            'IamFleetRole': 'arn:aws:iam::123456789012:role/fleet-role',  # Dummy role
                            'AllocationStrategy': 'lowestPrice',
                            'TargetCapacity': 1,
                            'SpotPrice': '0.001',  # Very low price for testing
                            'LaunchSpecifications': [{
                                'ImageId': self.ami_config['region_ami_mapping'].get(region, 'ami-12345'),
                                'InstanceType': instance_type,
                                'Placement': {'AvailabilityZone': az_name}
                            }]
                        }
                    )
                    availability_info[az_name] = 'available'
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    if error_code == 'DryRunOperation':
                        availability_info[az_name] = 'available'
                    elif 'InsufficientSpotCapacity' in error_code:
                        availability_info[az_name] = 'insufficient_capacity'
                    elif 'SpotMaxPriceTooLow' in error_code:
                        availability_info[az_name] = 'available'  # Price too low, but capacity exists
                    else:
                        availability_info[az_name] = f'error: {error_code}'
            
            return availability_info
        except Exception as e:
            self.log_operation('ERROR', f"Failed to check Spot capacity: {e}")
            return {}
    
    def get_ondemand_price(self, instance_type, region):
        """Get On-Demand pricing using AWS Pricing API"""
        try:
            import boto3
            pricing_client = boto3.client('pricing', region_name='us-east-1')  # Pricing API only available in us-east-1
            
            response = pricing_client.get_products(
                ServiceCode='AmazonEC2',
                Filters=[
                    {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
                    {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region},
                    {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
                    {'Type': 'TERM_MATCH', 'Field': 'operating-system', 'Value': 'Linux'},
                    {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'}
                ]
            )
            
            for price_item in response['PriceList']:
                price_data = json.loads(price_item)
                terms = price_data.get('terms', {}).get('OnDemand', {})
                
                for term_key, term_data in terms.items():
                    price_dimensions = term_data.get('priceDimensions', {})
                    for dim_key, dim_data in price_dimensions.items():
                        price_per_hour = float(dim_data['pricePerUnit']['USD'])
                        return price_per_hour
            
            return None
        except Exception as e:
            self.log_operation('WARNING', f"Could not get On-Demand price: {e}")
            return None

    def get_region_display_name(self, region):
        """Convert region code to display name for pricing API"""
        region_names = {
            'us-east-1': 'US East (N. Virginia)',
            'us-west-2': 'US West (Oregon)',
            'eu-west-1': 'Europe (Ireland)',
            # Add more mappings as needed
        }
        return region_names.get(region, region)
    
    def should_use_spot_instance(self, ec2_client, instance_type, region):
        """Analyze whether to use Spot instances based on multiple factors"""
        analysis = {
            'recommendation': 'on-demand',  # Default to safer option
            'reasoning': [],
            'spot_price_analysis': None,
            'capacity_analysis': None,
            'cost_savings': None,
            'confidence_score': 0
        }
        
        try:
            # Get Spot price history
            self.log_operation('INFO', f"Analyzing Spot availability for {instance_type} in {region}")
            
            spot_prices = self.get_spot_price_history(ec2_client, instance_type, region)
            if spot_prices:
                price_analysis = self.analyze_spot_price_stability(spot_prices)
                analysis['spot_price_analysis'] = price_analysis
                
                if price_analysis:
                    # Check price stability (less than 15% volatility is good)
                    if price_analysis['volatility_percent'] < 15:
                        analysis['confidence_score'] += 30
                        analysis['reasoning'].append(f"{Symbols.OK} Price stable (volatility: {price_analysis['volatility_percent']:.1f}%)")
                    else:
                        analysis['reasoning'].append(f"{Symbols.WARN} Price volatile (volatility: {price_analysis['volatility_percent']:.1f}%)")
            
            # Check capacity availability
            capacity_info = self.check_spot_capacity_availability(ec2_client, instance_type, region)
            analysis['capacity_analysis'] = capacity_info
            
            available_azs = [az for az, status in capacity_info.items() if status == 'available']
            if len(available_azs) >= 2:  # At least 2 AZs with capacity
                analysis['confidence_score'] += 25
                analysis['reasoning'].append(f"{Symbols.OK} Capacity available in {len(available_azs)} AZs")
            elif len(available_azs) == 1:
                analysis['confidence_score'] += 10
                analysis['reasoning'].append(f"{Symbols.WARN} Capacity available in only {len(available_azs)} AZ")
            else:
                analysis['reasoning'].append(f"{Symbols.ERROR} No Spot capacity available")
            
            # Compare with On-Demand pricing
            ondemand_price = self.get_ondemand_price(instance_type, region)
            if ondemand_price and analysis['spot_price_analysis']:
                current_spot_price = analysis['spot_price_analysis']['current_price']
                savings_percent = ((ondemand_price - current_spot_price) / ondemand_price) * 100
                analysis['cost_savings'] = {
                    'ondemand_price': ondemand_price,
                    'spot_price': current_spot_price,
                    'savings_percent': savings_percent,
                    'savings_per_hour': ondemand_price - current_spot_price
                }
                
                if savings_percent > 50:  # More than 50% savings
                    analysis['confidence_score'] += 25
                    analysis['reasoning'].append(f"{Symbols.OK} Excellent savings: {savings_percent:.1f}%")
                elif savings_percent > 30:  # More than 30% savings
                    analysis['confidence_score'] += 15
                    analysis['reasoning'].append(f"{Symbols.OK} Good savings: {savings_percent:.1f}%")
                else:
                    analysis['reasoning'].append(f"{Symbols.WARN} Limited savings: {savings_percent:.1f}%")
            
            # Make recommendation based on confidence score
            if analysis['confidence_score'] >= 60:
                analysis['recommendation'] = 'spot'
                analysis['reasoning'].append(f"{Symbols.TARGET} Recommendation: USE SPOT (confidence: {analysis['confidence_score']}/100)")
            elif analysis['confidence_score'] >= 35:
                analysis['recommendation'] = 'spot-with-caution'
                analysis['reasoning'].append(f"{Symbols.WARN} Recommendation: SPOT WITH CAUTION (confidence: {analysis['confidence_score']}/100)")
            else:
                analysis['recommendation'] = 'on-demand'
                analysis['reasoning'].append(f"{Symbols.PROTECTED} Recommendation: USE ON-DEMAND (confidence: {analysis['confidence_score']}/100)")
            
            return analysis
            
        except Exception as e:
            self.log_operation('ERROR', f"Error in Spot analysis: {e}")
            analysis['reasoning'].append(f"{Symbols.ERROR} Analysis failed: {e}")
            return analysis
        
    def display_spot_analysis_menu(self, selected_accounts, instance_type):
        """Display enhanced Spot instance analysis with alternatives and get user preference"""
        
        # Analyze all regions that will be used
        regions_to_analyze = set()
        for account_data in selected_accounts.values():
            for user_data in account_data.get('users', []):
                regions_to_analyze.add(user_data.get('region', 'us-east-1'))
        
        print(f"\n{Symbols.SCAN} Enhanced Spot Instance Analysis")
        print("=" * 80)
        print(f"Requested Instance Type: {instance_type}")
        print(f"Regions to analyze: {', '.join(sorted(regions_to_analyze))}")
        print("-" * 80)
        
        region_analyses = {}
        overall_recommendation = 'on-demand'
        alternative_suggestions = {}
        
        # Define instance type alternatives based on performance characteristics
        instance_alternatives = {
            't3.micro': ['t3a.micro', 't2.micro', 't4g.micro'],
            't3.small': ['t3a.small', 't2.small', 't4g.small', 't3.medium'],
            't3.medium': ['t3a.medium', 't2.medium', 't4g.medium', 't3.large'],
            't3.large': ['t3a.large', 't2.large', 't4g.large', 't3.xlarge'],
            't3.xlarge': ['t3a.xlarge', 't2.xlarge', 't4g.xlarge', 't3.2xlarge'],
            'c5.large': ['c5a.large', 'c4.large', 'c6i.large', 'c5.xlarge'],
            'c5.xlarge': ['c5a.xlarge', 'c4.xlarge', 'c6i.xlarge', 'c5.2xlarge'],
            'm5.large': ['m5a.large', 'm4.large', 'm6i.large', 'm5.xlarge'],
            'm5.xlarge': ['m5a.xlarge', 'm4.xlarge', 'm6i.xlarge', 'm5.2xlarge']
        }
        
        for region in regions_to_analyze:
            print(f"\n{Symbols.REGION} Analyzing {region}...")
            
            # Create a temporary client for analysis
            try:
                # Use first available user's credentials for analysis
                sample_user = None
                for account_data in selected_accounts.values():
                    for user_data in account_data.get('users', []):
                        if user_data.get('region') == region:
                            sample_user = user_data
                            break
                    if sample_user:
                        break
                
                if not sample_user:
                    print(f"   {Symbols.ERROR} No user credentials found for {region}")
                    continue
                    
                ec2_client = self.create_ec2_client(
                    sample_user['access_key_id'],
                    sample_user['secret_access_key'],
                    region
                )
                
                # Analyze primary instance type
                analysis = self.should_use_spot_instance(ec2_client, instance_type, region)
                
                # If spot is not recommended, analyze alternatives
                alternatives_analysis = {}
                if analysis['recommendation'] in ['on-demand', 'not-available']:
                    print(f"   {Symbols.SCAN} Analyzing alternative instance types...")
                    
                    alternatives = instance_alternatives.get(instance_type, [])
                    for alt_instance in alternatives[:3]:  # Check top 3 alternatives
                        try:
                            alt_analysis = self.should_use_spot_instance(ec2_client, alt_instance, region)
                            if alt_analysis['recommendation'] == 'spot':
                                alternatives_analysis[alt_instance] = alt_analysis
                                print(f"      {Symbols.OK} {alt_instance}: Good spot availability")
                        except Exception as e:
                            print(f"      {Symbols.ERROR} {alt_instance}: Analysis failed")
                            continue
                
                region_analyses[region] = {
                    'primary': analysis,
                    'alternatives': alternatives_analysis
                }
                
                # Display detailed analysis for this region
                print(f"   {Symbols.STATS} Primary Instance ({instance_type}) Analysis:")
                for reason in analysis['reasoning']:
                    print(f"      {reason}")
                
                if analysis['cost_savings']:
                    savings = analysis['cost_savings']
                    print(f"   {Symbols.COST} Primary Instance Pricing:")
                    print(f"      On-Demand: ${savings['ondemand_price']:.4f}/hour")
                    print(f"      Spot:      ${savings['spot_price']:.4f}/hour")
                    print(f"      Savings:   {savings['savings_percent']:.1f}% (${savings['savings_per_hour']:.4f}/hour)")
                
                # Show alternative recommendations
                if alternatives_analysis:
                    print(f"   {Symbols.SCAN} Recommended Alternatives for Spot:")
                    for alt_instance, alt_analysis in alternatives_analysis.items():
                        if alt_analysis['cost_savings']:
                            alt_savings = alt_analysis['cost_savings']
                            print(f"      {Symbols.OK} {alt_instance}:")
                            print(f"         Spot: ${alt_savings['spot_price']:.4f}/hour")
                            print(f"         Savings: {alt_savings['savings_percent']:.1f}%")
                            
                            # Calculate performance comparison
                            perf_comparison = self.compare_instance_performance(instance_type, alt_instance)
                            if perf_comparison:
                                print(f"         Performance: {perf_comparison}")
                
            except Exception as e:
                print(f"   {Symbols.ERROR} Analysis failed for {region}: {e}")
                continue
        
        # Determine overall recommendation with alternatives
        spot_regions = 0
        alternative_regions = 0
        
        for region, analyses in region_analyses.items():
            if analyses['primary']['recommendation'] == 'spot':
                spot_regions += 1
            elif analyses['alternatives']:
                alternative_regions += 1
        
        total_regions = len(region_analyses)
        
        if spot_regions == total_regions:
            overall_recommendation = 'spot-primary'
        elif spot_regions + alternative_regions >= total_regions * 0.7:
            overall_recommendation = 'mixed-with-alternatives'
        elif alternative_regions > spot_regions:
            overall_recommendation = 'alternatives-recommended'
        else:
            overall_recommendation = 'on-demand'
        
        # Display enhanced recommendation summary
        print(f"\n{Symbols.TARGET} Enhanced Spot Analysis Summary:")
        print("=" * 80)
        
        # Show region-by-region breakdown
        print(f"{Symbols.LIST} Region Analysis Breakdown:")
        for region, analyses in region_analyses.items():
            primary_rec = analyses['primary']['recommendation']
            alt_count = len(analyses['alternatives'])
            
            print(f"   {Symbols.REGION} {region}:")
            print(f"      Primary ({instance_type}): {primary_rec}")
            
            if analyses['alternatives']:
                print(f"      Alternative options: {alt_count} spot-suitable alternatives found")
                for alt_instance in analyses['alternatives'].keys():
                    print(f"         • {alt_instance} (spot recommended)")
            else:
                print(f"      Alternative options: None suitable for spot")
        
        # Calculate potential cost savings
        total_savings = self.calculate_total_savings(selected_accounts, region_analyses, instance_type)
        if total_savings:
            print(f"\n{Symbols.COST} Potential Monthly Savings (730 hours):")
            print(f"   Primary instance savings: ${total_savings['primary_savings']:.2f}")
            if total_savings['alternative_savings'] > 0:
                print(f"   With alternatives: ${total_savings['alternative_savings']:.2f}")
            print(f"   Best case scenario: ${total_savings['best_case']:.2f}")
        
        # Display enhanced menu options
        print(f"\n{Symbols.LIST} Instance Creation Options:")
        print("=" * 60)
        print("  1. Use Spot instances (primary type where recommended)")
        print("  2. Use On-Demand instances (safest, most expensive)")
        print("  3. Smart Mixed approach (Spot + alternatives where beneficial)")
        print("  4. Use alternative instances for better Spot availability")
        print("  5. Show detailed analysis again")
        print("  6. Show instance type comparison")
        print("  7. Cancel")
        
        # Add recommendation based on analysis
        print(f"\n{Symbols.TIP} AI Recommendation: ", end="")
        if overall_recommendation == 'spot-primary':
            print(f"{Symbols.OK} Use Spot instances - excellent availability across all regions")
        elif overall_recommendation == 'mixed-with-alternatives':
            print(f"{Symbols.SCAN} Use Smart Mixed approach - combines savings with reliability")
        elif overall_recommendation == 'alternatives-recommended':
            print(f"{Symbols.SCAN} Consider alternative instance types for better Spot savings")
        else:
            print(f"{Symbols.WARN}  Use On-Demand instances - limited Spot availability")
        
        while True:
            choice = input(f"\n[#] Choose your approach (1-7): ").strip()
            
            if choice == '1':
                return 'spot', region_analyses
            elif choice == '2':
                return 'on-demand', region_analyses
            elif choice == '3':
                return 'smart-mixed', region_analyses
            elif choice == '4':
                return 'alternatives', region_analyses
            elif choice == '5':
                # Show detailed analysis again (loop continues)
                continue
            elif choice == '6':
                self.show_instance_comparison(instance_type, instance_alternatives.get(instance_type, []))
                continue
            elif choice == '7':
                return 'cancel', region_analyses
            else:
                print(f"{Symbols.ERROR} Invalid choice. Please enter 1-7.")

    def compare_instance_performance(self, primary_instance, alternative_instance):
        """Compare performance characteristics between instance types"""
        
        # Instance specifications (simplified - you'd want to use AWS API for real data)
        instance_specs = {
            't3.micro': {'vcpu': 2, 'memory': 1, 'network': 'Up to 5 Gbps', 'score': 10},
            't3a.micro': {'vcpu': 2, 'memory': 1, 'network': 'Up to 5 Gbps', 'score': 9},
            't2.micro': {'vcpu': 1, 'memory': 1, 'network': 'Low to Moderate', 'score': 7},
            't4g.micro': {'vcpu': 2, 'memory': 1, 'network': 'Up to 5 Gbps', 'score': 11},
            't3.small': {'vcpu': 2, 'memory': 2, 'network': 'Up to 5 Gbps', 'score': 20},
            't3a.small': {'vcpu': 2, 'memory': 2, 'network': 'Up to 5 Gbps', 'score': 19},
            't2.small': {'vcpu': 1, 'memory': 2, 'network': 'Low to Moderate', 'score': 15},
            't4g.small': {'vcpu': 2, 'memory': 2, 'network': 'Up to 5 Gbps', 'score': 21}
        }
        
        primary_spec = instance_specs.get(primary_instance)
        alt_spec = instance_specs.get(alternative_instance)
        
        if not primary_spec or not alt_spec:
            return "Comparison data not available"
        
        if alt_spec['score'] >= primary_spec['score']:
            return f"Similar or better performance ({alt_spec['vcpu']} vCPU, {alt_spec['memory']}GB RAM)"
        elif alt_spec['score'] >= primary_spec['score'] * 0.8:
            return f"Slightly lower performance ({alt_spec['vcpu']} vCPU, {alt_spec['memory']}GB RAM)"
        else:
            return f"Lower performance ({alt_spec['vcpu']} vCPU, {alt_spec['memory']}GB RAM)"

    def calculate_total_savings(self, selected_accounts, region_analyses, primary_instance):
        """Calculate potential cost savings across all selected users"""
        
        total_users = sum(len(account_data.get('users', [])) 
                        for account_data in selected_accounts.values())
        
        if total_users == 0:
            return None
        
        primary_savings_per_hour = 0
        alternative_savings_per_hour = 0
        
        user_count_by_region = {}
        for account_data in selected_accounts.values():
            for user_data in account_data.get('users', []):
                region = user_data.get('region', 'us-east-1')
                user_count_by_region[region] = user_count_by_region.get(region, 0) + 1
        
        for region, user_count in user_count_by_region.items():
            if region in region_analyses:
                analysis = region_analyses[region]
                
                # Primary instance savings
                if analysis['primary']['cost_savings']:
                    primary_savings_per_hour += (
                        analysis['primary']['cost_savings']['savings_per_hour'] * user_count
                    )
                
                # Best alternative savings
                if analysis['alternatives']:
                    best_alt_savings = max(
                        alt['cost_savings']['savings_per_hour'] 
                        for alt in analysis['alternatives'].values() 
                        if alt['cost_savings']
                    )
                    alternative_savings_per_hour += best_alt_savings * user_count
        
        return {
            'primary_savings': primary_savings_per_hour * 730,  # Monthly
            'alternative_savings': alternative_savings_per_hour * 730,
            'best_case': max(primary_savings_per_hour, alternative_savings_per_hour) * 730
    }

    def show_instance_comparison(self, primary_instance, alternatives):
        """Show detailed comparison of instance types"""
        
        print(f"\n{Symbols.STATS} Instance Type Comparison")
        print("=" * 80)
        print(f"Primary: {primary_instance}")
        print(f"Alternatives: {', '.join(alternatives[:5])}")
        print("-" * 80)
        
        # This would ideally call AWS API for real-time pricing and specs
        print("[TIP] Comparison factors to consider:")
        print("   • vCPU count and performance")
        print("   • Memory (RAM) allocation") 
        print("   • Network performance")
        print("   • Storage options")
        print("   • Spot instance availability")
        print("   • Hourly pricing (On-Demand vs Spot)")
        print("\n[TIP] Tip: t3a instances are often 10% cheaper than t3")
        print("[TIP] Tip: t4g instances (ARM-based) offer better price/performance")
        print("[TIP] Tip: Consider one size larger if spot availability is better")
        
        input("\nPress Enter to continue...")

    def create_instances_for_selected_accounts(self, selected_accounts, instance_type='t3.micro', capacity_type='spot', wait_for_running=True):
        """Create EC2 instances for users in selected accounts"""
        created_instances = []
        failed_instances = []
        
        self.log_operation('INFO', f"{Symbols.START} Starting EC2 instance creation process")
        self.log_operation('INFO', f"Instance type: {instance_type}")
        self.log_operation('INFO', f"Capacity type: {capacity_type}")  # Add this line
        self.log_operation('INFO', f"User data script: {self.userdata_file}")
        self.log_operation('INFO', f"Credentials source: {self.credentials_file}")
        self.log_operation('INFO', f"Wait for running: {wait_for_running}")
        
        # Calculate total users
        total_users = sum(len(account_data.get('users', [])) 
                        for account_data in selected_accounts.values())
        self.log_operation('INFO', f"Total users to process: {total_users}")
        
        user_count = 0
        for account_name, account_data in selected_accounts.items():
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            self.log_operation('INFO', f"{Symbols.ACCOUNT} Processing account: {account_name} ({account_id})")
            
            if 'users' not in account_data:
                self.log_operation('WARNING', f"No users found in account: {account_name}")
                continue
                
            for user_data in account_data['users']:
                user_count += 1
                username = user_data.get('username', 'unknown')
                region = user_data.get('region', 'us-east-1')
                access_key = user_data.get('access_key_id', '')
                secret_key = user_data.get('secret_access_key', '')
                real_user_info = user_data.get('real_user', {})
                
                real_name = real_user_info.get('full_name', username)
                
                self.log_operation('INFO', f"👤 [{user_count}/{total_users}] Processing user: {username} ({real_name}) in {region}")
                
                if not access_key or not secret_key:
                    error_msg = "Missing AWS credentials"
                    self.log_operation('ERROR', f"{Symbols.ERROR} {username}: {error_msg}")
                    failed_instances.append({
                        'username': username,
                        'real_name': real_name,
                        'region': region,
                        'account_name': account_name,
                        'account_id': account_id,
                        'error': error_msg
                    })
                    continue
                
                try:
                    # Create EC2 client with user's credentials
                    ec2_client = self.create_ec2_client(access_key, secret_key, region)
                    
                    # Create instance with specified capacity type
                    instance_info = self.create_instance_with_capacity_type(
                        ec2_client, 
                        self.user_data_script, 
                        region, 
                        username,
                        real_user_info,
                        access_key,      # Pass credentials
                        secret_key,      # Pass credentials
                        instance_type,
                        capacity_type    # Pass the capacity type
                    )
                    
                    # Wait for instance to be running (optional)
                    if wait_for_running:
                        running_info = self.wait_for_instance_running(
                            ec2_client, 
                            instance_info['instance_id'], 
                            username
                        )
                        if running_info:
                            instance_info.update(running_info)
                    
                    # Add account and user details
                    instance_info.update({
                        'account_name': account_name,
                        'account_id': account_id,
                        'account_email': account_email,
                        'user_data': user_data,
                        'created_at': self.current_time,
                        'capacity_type': capacity_type  # Add this line
                    })
                    
                    created_instances.append(instance_info)
                    
                    # Print success message
                    capacity_emoji = f"{Symbols.COST}" if capacity_type == 'spot' else f"{Symbols.SECURE}"
                    print(f"\n[PARTY] SUCCESS: {capacity_type.upper()} instance created for {real_name}")
                    print(f"   👤 Username: {username}")
                    print(f"   📍 Instance ID: {instance_info['instance_id']}")
                    print(f"   {Symbols.REGION} Region: {region}")
                    print(f"   💻 Instance Type: {instance_info['instance_type']}")
                    print(f"   {capacity_emoji} Capacity: {capacity_type.upper()}")
                    print(f"   {Symbols.ACCOUNT} Account: {account_name} ({account_id})")
                    if 'public_ip' in instance_info:
                        print(f"   🌐 Public IP: {instance_info['public_ip']}")
                    if 'startup_time_seconds' in instance_info:
                        print(f"   {Symbols.TIMER}  Startup Time: {instance_info['startup_time_seconds']}s")
                    print("-" * 60)
                    
                except Exception as e:
                    error_msg = str(e)
                    self.log_operation('ERROR', f"{Symbols.ERROR} Failed to create instance for {username}: {error_msg}")
                    failed_instances.append({
                        'username': username,
                        'real_name': real_name,
                        'region': region,
                        'account_name': account_name,
                        'account_id': account_id,
                        'error': error_msg
                    })
                    print(f"\n{Symbols.ERROR} FAILED: Instance creation failed for {real_name}")
                    print(f"   👤 Username: {username}")
                    print(f"   {Symbols.ACCOUNT} Account: {account_name}")
                    print(f"   Error: {error_msg}")
                    print("-" * 60)
                    continue
        
        self.log_operation('INFO', f"Instance creation completed - Created: {len(created_instances)}, Failed: {len(failed_instances)}")
        return created_instances, failed_instances

    def wait_for_instance_running(self, ec2_client, instance_id, username, timeout=300):
        """Wait for instance to be in running state"""
        self.log_operation('INFO', f"⏳ Waiting for instance {instance_id} to reach running state (timeout: {timeout}s)")
        
        start_time = time.time()
        last_state = None
        
        while time.time() - start_time < timeout:
            try:
                response = ec2_client.describe_instances(InstanceIds=[instance_id])
                instance = response['Reservations'][0]['Instances'][0]
                state = instance['State']['Name']
                
                # Log state changes
                if state != last_state:
                    self.log_operation('INFO', f"Instance {instance_id} state changed: {last_state} → {state}")
                    last_state = state
                
                if state == 'running':
                    public_ip = instance.get('PublicIpAddress', 'N/A')
                    private_ip = instance.get('PrivateIpAddress', 'N/A')
                    
                    elapsed_time = int(time.time() - start_time)
                    self.log_operation('INFO', f"{Symbols.OK} Instance {instance_id} is running (took {elapsed_time}s) - Public: {public_ip}, Private: {private_ip}")
                    
                    return {
                        'state': state,
                        'public_ip': public_ip,
                        'private_ip': private_ip,
                        'startup_time_seconds': elapsed_time
                    }
                elif state in ['terminated', 'terminating']:
                    self.log_operation('ERROR', f"{Symbols.ERROR} Instance {instance_id} terminated unexpectedly")
                    return None
                else:
                    time.sleep(10)
                    
            except Exception as e:
                self.log_operation('ERROR', f"Error checking instance {instance_id} state: {e}")
                time.sleep(10)
        
        elapsed_time = int(time.time() - start_time)
        self.log_operation('ERROR', f"{Symbols.TIMER} Timeout waiting for instance {instance_id} after {elapsed_time} seconds")
        return None
    
    def prepare_userdata_with_aws_config(self, base_userdata, access_key, secret_key, region):
        """Add AWS credentials to userdata script"""
        
        # Replace placeholder variables in userdata
        enhanced_userdata = base_userdata.replace('${AWS_ACCESS_KEY_ID}', access_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_SECRET_ACCESS_KEY}', secret_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_DEFAULT_REGION}', region)
        
        return enhanced_userdata

    def select_capacity_type_ec2(self, user_name: str = None) -> str:
        """Allow user to select EC2 capacity type (Spot or On-Demand)"""
        capacity_options = ['spot', 'on-demand']
        default_type = 'spot'  # Default to spot for cost efficiency
        
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n{Symbols.COST} EC2 Capacity Type Selection {user_prefix}")
        print("=" * 60)
        print("Available capacity types:")
        
        for i, capacity_type in enumerate(capacity_options, 1):
            is_default = " (default)" if capacity_type == default_type else ""
            cost_info = " - Up to 90% savings, may be interrupted" if capacity_type == 'spot' else " - Standard pricing, stable"
            print(f"  {i}. {capacity_type.title()}{is_default}{cost_info}")
        
        print("=" * 60)
        
        while True:
            try:
                choice = input(f"Select capacity type (1-{len(capacity_options)}) [default: {default_type}]: ").strip()
                
                if not choice:
                    selected_type = default_type
                    break
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(capacity_options):
                    selected_type = capacity_options[choice_num - 1]
                    break
                else:
                    print(f"{Symbols.ERROR} Please enter a number between 1 and {len(capacity_options)}")
            except ValueError:
                print("[ERROR] Please enter a valid number")
        
        print(f"{Symbols.OK} Selected capacity type: {selected_type}")
        return selected_type
    
    def create_instance_with_capacity_type(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro', capacity_type='spot'):
        """Create EC2 instance with specified capacity type"""
        self.log_operation('INFO', f"Creating {capacity_type} instance for {username}")
        
        if capacity_type.lower() == 'spot':
            return self.create_instance_spot(ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type, capacity_type)
        else:
            return self.create_instance(ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type, capacity_type)
        
    def create_instance_spot(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro', capacity_type='spot'):
        """Create a Spot EC2 instance for a specific IAM user with enhanced error handling"""
        try:
            # Get AMI for the region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            self.log_operation('INFO', f"Starting Spot instance creation for {username} in {region} with AMI: {ami_id}")
            
            # Get default VPC
            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")
            
            # Get default subnet
            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")
            
            random_suffix = self.generate_random_suffix(4)
            
            # Create security group
            sg_name = f"{username}-spot-sg-{random_suffix}"  # Changed to indicate spot
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)
            
            # Prepare tags with real user information
            tags = [
                {'Key': 'Name', 'Value': f'{username}-spot-instance-{random_suffix}'},  # Added 'spot' to name
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Spot-Instance'},  # Updated purpose
                {'Key': 'CapacityType', 'Value': 'spot'},  # Added capacity type tag
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp},
                {'Key': 'InstanceType', 'Value': instance_type}
            ]
            
            # Add real user information to tags
            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})
            
            self.log_operation('INFO', f"Spot instance configuration - Type: {instance_type}, VPC: {vpc_id}, Subnet: {subnet_id}, SG: {sg_id}")
            
            # Enhanced Spot Instance configuration with better error handling
            try:
                # Get current spot price for reference (optional logging)
                try:
                    spot_prices = ec2_client.describe_spot_price_history(
                        InstanceTypes=[instance_type],
                        ProductDescriptions=['Linux/UNIX'],
                        MaxResults=1
                    )
                    if spot_prices['SpotPriceHistory']:
                        current_spot_price = spot_prices['SpotPriceHistory'][0]['SpotPrice']
                        self.log_operation('INFO', f"Current spot price for {instance_type}: ${current_spot_price}/hour")
                except Exception as spot_price_error:
                    self.log_operation('WARNING', f"Could not retrieve spot price: {spot_price_error}")
                
                # Create Spot Instance with enhanced configuration
                response = ec2_client.run_instances(
                    ImageId=ami_id,
                    MinCount=1,
                    MaxCount=1,
                    InstanceType=instance_type,
                    SecurityGroupIds=[sg_id],
                    SubnetId=subnet_id,
                    UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                    InstanceMarketOptions={
                        'MarketType': 'spot',
                        'SpotOptions': {
                            'SpotInstanceType': 'one-time',
                            'InstanceInterruptionBehavior': 'terminate',
                            # Optional: Set max price to prevent unexpected charges
                            # 'MaxPrice': '0.05'  # Uncomment and adjust as needed
                        }
                    },
                    TagSpecifications=[
                        {
                            'ResourceType': 'instance',
                            'Tags': tags
                        },
                        {
                            'ResourceType': 'volume',  # Also tag the EBS volume
                            'Tags': [
                                {'Key': 'Name', 'Value': f'{username}-spot-volume-{random_suffix}'},
                                {'Key': 'Owner', 'Value': username},
                                {'Key': 'CapacityType', 'Value': 'spot'}
                            ]
                        }
                    ],
                    # Enable detailed monitoring for better spot instance management
                    Monitoring={'Enabled': True}
                )
                
                instance_id = response['Instances'][0]['InstanceId']
                instance_type_actual = response['Instances'][0]['InstanceType']
                instance_state = response['Instances'][0]['State']['Name']
                
                # Log spot instance specific information
                if 'SpotInstanceRequestId' in response['Instances'][0]:
                    spot_request_id = response['Instances'][0]['SpotInstanceRequestId']
                    self.log_operation('INFO', f"Spot request ID: {spot_request_id}")
                
                self.log_operation('INFO', f"{Symbols.OK} Successfully created Spot instance {instance_id} for user {username} with suffix {random_suffix}")
                self.log_operation('INFO', f"Instance state: {instance_state}, Actual type: {instance_type_actual}")
                
                # Return enhanced instance information
                return {
                    'instance_id': instance_id,
                    'instance_type': instance_type_actual,
                    'capacity_type': 'spot',  # Explicitly mark as spot
                    'instance_state': instance_state,
                    'region': region,
                    'ami_id': ami_id,
                    'vpc_id': vpc_id,
                    'subnet_id': subnet_id,
                    'security_group_id': sg_id,
                    'username': username,
                    'real_user_info': real_user_info,
                    'userdata_file': self.userdata_file,
                    'credentials_file': self.credentials_file,
                    'random_suffix': random_suffix,
                    'market_type': 'spot'  # For compatibility
                }
                
            except Exception as spot_creation_error:
                # Handle specific spot instance creation errors
                error_msg = str(spot_creation_error)
                
                if 'SpotMaxPriceTooLow' in error_msg:
                    self.log_operation('ERROR', f"Spot price too low for {instance_type} in {region}")
                    raise ValueError(f"Spot capacity not available for {instance_type} in {region} at current price")
                elif 'InsufficientInstanceCapacity' in error_msg:
                    self.log_operation('ERROR', f"Insufficient spot capacity for {instance_type} in {region}")
                    raise ValueError(f"No spot capacity available for {instance_type} in {region}")
                elif 'SpotFleetRequestConfigurationInvalid' in error_msg:
                    self.log_operation('ERROR', f"Invalid spot configuration for {instance_type}")
                    raise ValueError(f"Invalid spot instance configuration for {instance_type}")
                else:
                    self.log_operation('ERROR', f"Spot instance creation failed: {error_msg}")
                    raise
                
        except ValueError as ve:
            # Re-raise ValueError with context
            self.log_operation('ERROR', f"{Symbols.ERROR} Configuration error for Spot instance {username}: {str(ve)}")
            raise
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to create Spot instance for user {username}: {error_msg}")
            
            # Provide helpful error context
            if 'InvalidInstanceType' in error_msg:
                raise ValueError(f"Instance type {instance_type} is not available in region {region}")
            elif 'UnauthorizedOperation' in error_msg:
                raise ValueError(f"Insufficient permissions to create spot instances for user {username}")
            else:
                raise

    def create_instance(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro', capacity_type='on-demand'):        
        """Create an On-Demand EC2 instance for a specific IAM user"""
        try:
            # Get AMI for the region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            self.log_operation('INFO', f"Starting On-Demand instance creation for {username} in {region} with AMI: {ami_id}")
            
            # Get default VPC
            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")
            
            # Get default subnet
            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")
            
            random_suffix = self.generate_random_suffix(4)
            
            # Create security group
            sg_name = f"{username}-all-traffic-sg-{random_suffix}"
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)
            
            # Prepare tags
            tags = [
                {'Key': 'Name', 'Value': f'{username}-instance-{random_suffix}'},
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Instance'},
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp},
                {'Key': 'InstanceType', 'Value': 'on-demand'}
            ]
            
            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})
            
            self.log_operation('INFO', f"Creating on-demand instance with type {instance_type}, VPC {vpc_id}, Subnet {subnet_id}, SG {sg_id}")
            
            # Create On-Demand Instance (NO Spot options)
            response = ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                SecurityGroupIds=[sg_id],
                SubnetId=subnet_id,
                UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': tags
                    }
                ]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            instance_type_actual = response['Instances'][0]['InstanceType']
            
            self.log_operation('INFO', f"{Symbols.OK} Successfully created On-Demand instance {instance_id} for user {username} with suffix {random_suffix}")
            
            return {
                'instance_id': instance_id,
                'instance_type': instance_type_actual,
                'region': region,
                'ami_id': ami_id,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'username': username,
                'real_user_info': real_user_info,
                'userdata_file': self.userdata_file,
                'credentials_file': self.credentials_file,
                'market_type': 'on-demand'
            }
        
        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to create On-Demand instance for user {username}: {str(e)}")
            raise

    def create_instance_bk(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro'):
        """Try creating a Spot instance; fallback to On-Demand if Spot capacity is unavailable"""
        def run_instance(market_type):
            try:
                instance_market_options = None
                if market_type == 'spot':
                    instance_market_options = {
                        'MarketType': 'spot',
                        'SpotOptions': {
                            'SpotInstanceType': 'one-time',
                            'InstanceInterruptionBehavior': 'terminate'
                        }
                    }

                return ec2_client.run_instances(
                    ImageId=ami_id,
                    MinCount=1,
                    MaxCount=1,
                    InstanceType=instance_type,
                    SecurityGroupIds=[sg_id],
                    SubnetId=subnet_id,
                    UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                    InstanceMarketOptions=instance_market_options,
                    TagSpecifications=[
                        {
                            'ResourceType': 'instance',
                            'Tags': tags
                        }
                    ]
                )
            except Exception as e:
                raise RuntimeError(f"{market_type.capitalize()} instance request failed: {str(e)}")

        try:
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")

            self.log_operation('INFO', f"Starting instance creation for {username} in {region} (attempting Spot instance first)")

            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")

            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")

            random_suffix = self.generate_random_suffix(4)
            sg_name = f"{username}-all-traffic-sg-{random_suffix}"
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)

            tags = [
                {'Key': 'Name', 'Value': f'{username}-instance-{random_suffix}'},
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Instance'},
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp}
            ]

            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})

            self.log_operation('INFO', f"Config - Type: {instance_type}, VPC: {vpc_id}, Subnet: {subnet_id}, SG: {sg_id}")

            # Attempt Spot instance first
            try:
                response = run_instance('spot')
                instance_type_used = 'spot'
            except RuntimeError as spot_error:
                self.log_operation('WARNING', f"{Symbols.WARN} Spot failed: {str(spot_error)}. Retrying as On-Demand.")
                response = run_instance('ondemand')
                instance_type_used = 'ondemand'

            instance_id = response['Instances'][0]['InstanceId']
            actual_type = response['Instances'][0]['InstanceType']
            self.log_operation('INFO', f"{Symbols.OK} Created {instance_type_used} instance {instance_id} for {username} (suffix: {random_suffix})")

            return {
                'instance_id': instance_id,
                'instance_type': actual_type,
                'instance_market_type': instance_type_used,
                'region': region,
                'ami_id': ami_id,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'username': username,
                'real_user_info': real_user_info,
                'userdata_file': self.userdata_file,
                'credentials_file': self.credentials_file
            }

        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Instance creation failed for user {username}: {str(e)}")
            raise

    def create_instance_ondemand(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro'):
        """Create an EC2 instance for a specific IAM user"""
        try:
            # Get AMI for the region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            self.log_operation('INFO', f"Starting instance creation for {username} in {region} with AMI: {ami_id}")
            
            # Get default VPC
            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")
            
            # Get default subnet
            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")
            
            random_suffix = self.generate_random_suffix(4)
            
            # Create security group
            sg_name = f"{username}-all-traffic-sg-{random_suffix}"
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)
            
            # Prepare tags with real user information
            tags = [
                {'Key': 'Name', 'Value': f'{username}-instance-{random_suffix}'},
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Instance'},
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp}
            ]
            
            # Add real user information to tags
            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})
            
            self.log_operation('INFO', f"Instance configuration - Type: {instance_type}, VPC: {vpc_id}, Subnet: {subnet_id}, SG: {sg_id}")
            
            # Create instance with AWS CLI configuration
            response = ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                SecurityGroupIds=[sg_id],
                SubnetId=subnet_id,
                UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': tags
                    }
                ]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            instance_type_actual = response['Instances'][0]['InstanceType']
            
            self.log_operation('INFO', f"{Symbols.OK} Successfully created instance {instance_id} for user {username} with suffix {random_suffix}")            
            
            return {
                'instance_id': instance_id,
                'instance_type': instance_type_actual,
                'region': region,
                'ami_id': ami_id,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'username': username,
                'real_user_info': real_user_info,
                'userdata_file': self.userdata_file,
                'credentials_file': self.credentials_file
            }
            
        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to create instance for user {username}: {str(e)}")
            raise

    def save_user_instance_mapping(self, created_instances, failed_instances):
        """Save IAM user to instance ID mapping as JSON file"""
        try:
            mapping_filename = f"iam_user_instance_mapping_{self.execution_timestamp}.json"
            
            # Create mapping data
            mapping_data = {
                "metadata": {
                    "creation_date": self.current_time.split()[0],
                    "creation_time": self.current_time.split()[1],
                    "created_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "credentials_source": self.credentials_file,
                    "userdata_script": self.userdata_file,
                    "total_processed": len(created_instances) + len(failed_instances),
                    "successful_creations": len(created_instances),
                    "failed_creations": len(failed_instances),
                    "success_rate": f"{len(created_instances)/(len(created_instances)+len(failed_instances))*100:.1f}%" if (created_instances or failed_instances) else "0%"
                },
                "successful_mappings": {},
                "failed_mappings": {},
                "detailed_info": {
                    "successful_instances": created_instances,
                    "failed_instances": failed_instances
                }
            }
            
            # Create successful mappings (username -> instance details)
            for instance in created_instances:
                username = instance['username']
                real_user = instance.get('real_user_info', {})
                
                mapping_data["successful_mappings"][username] = {
                    "instance_id": instance['instance_id'],
                    "region": instance['region'],
                    "instance_type": instance['instance_type'],
                    "public_ip": instance.get('public_ip', 'N/A'),
                    "private_ip": instance.get('private_ip', 'N/A'),
                    "account_name": instance['account_name'],
                    "account_id": instance['account_id'],
                    "real_user": {
                        "full_name": real_user.get('full_name', ''),
                        "email": real_user.get('email', ''),
                        "first_name": real_user.get('first_name', ''),
                        "last_name": real_user.get('last_name', '')
                    },
                    "created_at": instance['created_at'],
                    "startup_time_seconds": instance.get('startup_time_seconds', 'N/A'),
                    "aws_console_url": instance.get('user_data', {}).get('console_url', 'N/A'),
                    "tags": {
                        "name": f"{username}-instance",
                        "owner": username,
                        "purpose": "IAM-User-Instance",
                        "created_by": self.current_user
                    }
                }
            
            # Create failed mappings (username -> error details)
            for failure in failed_instances:
                username = failure['username']
                mapping_data["failed_mappings"][username] = {
                    "reason": failure['error'],
                    "region": failure['region'],
                    "account_name": failure['account_name'],
                    "account_id": failure.get('account_id', 'Unknown'),
                    "real_user_name": failure.get('real_name', username),
                    "attempted_at": self.current_time
                }
            
            # Save to file
            with open(mapping_filename, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"{Symbols.OK} IAM user to instance mapping saved to: {mapping_filename}")
            return mapping_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to save user-instance mapping: {e}")
            return None

    def save_instance_report(self, created_instances, failed_instances):
        """Save detailed instance creation report to JSON file"""
        try:
            report_filename = f"ec2_instances_report_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "creation_date": self.current_time.split()[0],
                    "creation_time": self.current_time.split()[1],
                    "created_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "credentials_source": self.credentials_file,
                    "userdata_script": self.userdata_file,
                    "ami_mapping_file": self.ami_mapping_file,
                    "log_file": self.log_filename
                },
                "summary": {
                    "total_processed": len(created_instances) + len(failed_instances),
                    "total_created": len(created_instances),
                    "total_failed": len(failed_instances),
                    "success_rate": f"{len(created_instances)/(len(created_instances)+len(failed_instances))*100:.1f}%" if (created_instances or failed_instances) else "0%",
                    "accounts_processed": len(set(instance.get('account_name', '') for instance in created_instances + failed_instances)),
                    "regions_used": list(set(instance.get('region', '') for instance in created_instances + failed_instances))
                },
                "created_instances": created_instances,
                "failed_instances": failed_instances,
                "statistics": {
                    "by_region": {},
                    "by_account": {},
                    "by_instance_type": {},
                    "startup_times": []
                }
            }
            
            # Generate statistics
            for instance in created_instances:
                region = instance.get('region', 'unknown')
                account = instance.get('account_name', 'unknown')
                instance_type = instance.get('instance_type', 'unknown')
                startup_time = instance.get('startup_time_seconds', 0)
                
                # Region statistics
                if region not in report_data["statistics"]["by_region"]:
                    report_data["statistics"]["by_region"][region] = 0
                report_data["statistics"]["by_region"][region] += 1
                
                # Account statistics
                if account not in report_data["statistics"]["by_account"]:
                    report_data["statistics"]["by_account"][account] = 0
                report_data["statistics"]["by_account"][account] += 1
                
                # Instance type statistics
                if instance_type not in report_data["statistics"]["by_instance_type"]:
                    report_data["statistics"]["by_instance_type"][instance_type] = 0
                report_data["statistics"]["by_instance_type"][instance_type] += 1
                
                # Startup times
                if isinstance(startup_time, (int, float)) and startup_time > 0:
                    report_data["statistics"]["startup_times"].append(startup_time)
            
            # Calculate startup time statistics
            startup_times = report_data["statistics"]["startup_times"]
            if startup_times:
                report_data["statistics"]["startup_time_stats"] = {
                    "min": min(startup_times),
                    "max": max(startup_times),
                    "average": sum(startup_times) / len(startup_times),
                    "count": len(startup_times)
                }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"{Symbols.OK} Detailed instance report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"{Symbols.ERROR} Failed to save instance report: {e}")
            return None
        
    def convert_selected_users_to_accounts(self, selected_user_indices, user_mapping):
        """Convert selected user indices back to account format for instance creation"""
        if not selected_user_indices or not user_mapping:
            return {}
        
        accounts_data = {}
        
        for user_index in selected_user_indices:
            user_info = user_mapping[user_index]
            account_name = user_info['account_name']
            
            # Initialize account if not exists
            if account_name not in accounts_data:
                accounts_data[account_name] = {
                    'account_id': user_info['account_id'],
                    'account_email': user_info['account_email'],
                    'users': []
                }
            
            # Add user to account
            accounts_data[account_name]['users'].append(user_info['user_data'])
        
        self.log_operation('INFO', f"Converted {len(selected_user_indices)} selected users into {len(accounts_data)} accounts")
        
        # Log conversion details
        for account_name, account_data in accounts_data.items():
            user_count = len(account_data['users'])
            usernames = [u.get('username', 'unknown') for u in account_data['users']]
            self.log_operation('INFO', f"Account {account_name}: {user_count} users - {', '.join(usernames)}")
        
        return accounts_data
    
    def display_users_menu(self, selected_accounts):
        """Display available users and return user selection"""
        # Collect all users from selected accounts
        all_users = []
        for account_name, account_data in selected_accounts.items():
            for user_data in account_data.get('users', []):
                user_info = {
                    'account_name': account_name,
                    'account_id': account_data.get('account_id', 'Unknown'),
                    'account_email': account_data.get('account_email', 'Unknown'),
                    'user_data': user_data,
                    'username': user_data.get('username', 'unknown'),
                    'region': user_data.get('region', 'us-east-1'),
                    'real_user': user_data.get('real_user', {}),
                    'access_key': user_data.get('access_key_id', ''),
                    'secret_key': user_data.get('secret_access_key', ''),
                }
                all_users.append(user_info)
        
        if not all_users:
            self.log_operation('ERROR', "No users found in selected accounts")
            return []
        
        self.log_operation('INFO', f"Displaying {len(all_users)} available users for selection")
        
        print(f"\n👥 Available Users ({len(all_users)} total):")
        print("=" * 100)
        
        # Group users by account for better display
        users_by_account = {}
        for user_info in all_users:
            account_name = user_info['account_name']
            if account_name not in users_by_account:
                users_by_account[account_name] = []
            users_by_account[account_name].append(user_info)
        
        user_index = 1
        user_mapping = {}  # Map display index to user info
        
        for account_name, users in users_by_account.items():
            account_id = users[0]['account_id']
            print(f"\n{Symbols.ACCOUNT} {account_name} ({account_id}) - {len(users)} users:")
            print("-" * 80)
            
            for user_info in users:
                real_user = user_info['real_user']
                full_name = real_user.get('full_name', user_info['username'])
                email = real_user.get('email', 'N/A')
                region = user_info['region']
                
                print(f"  {user_index:3}. {full_name}")
                print(f"       👤 Username: {user_info['username']}")
                print(f"       📧 Email: {email}")
                print(f"       {Symbols.REGION} Region: {region}")
                print(f"       {Symbols.KEY} Has Credentials: {'{Symbols.OK}' if user_info['access_key'] and user_info['secret_key'] else '{Symbols.ERROR}'}")
                
                user_mapping[user_index] = user_info
                user_index += 1
                print()
        
        print("=" * 100)
        print(f"{Symbols.STATS} Summary:")
        print(f"   [UP] Total accounts: {len(users_by_account)}")
        print(f"   👥 Total users: {len(all_users)}")
        
        # Count users by region
        regions = {}
        for user_info in all_users:
            region = user_info['region']
            regions[region] = regions.get(region, 0) + 1
        print(f"   {Symbols.REGION} Regions: {', '.join(f'{region}({count})' for region, count in sorted(regions.items()))}")
        
        self.log_operation('INFO', f"User summary: {len(all_users)} users across {len(users_by_account)} accounts in {len(regions)} regions")
        
        print(f"\n{Symbols.LOG} Selection Options:")
        print(f"   • Single users: 1,3,5")
        print(f"   • Ranges: 1-{len(all_users)} (users 1 through {len(all_users)})")
        print(f"   • Mixed: 1-5,8,10-12 (users 1-5, 8, and 10-12)")
        print(f"   • All users: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n[#] Select users to process: ").strip()
            
            self.log_operation('INFO', f"User input for user selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all users")
                return list(range(1, len(all_users) + 1)), user_mapping
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled user selection")
                return [], {}
            
            try:
                selected_indices = self.parse_user_selection(selection, len(all_users))
                if selected_indices:
                    # Show what was selected
                    selected_user_info = []
                    selected_regions = set()
                    selected_accounts = set()
                    
                    for idx in selected_indices:
                        user_info = user_mapping[idx]
                        real_user = user_info['real_user']
                        full_name = real_user.get('full_name', user_info['username'])
                        
                        selected_user_info.append({
                            'index': idx,
                            'username': user_info['username'],
                            'full_name': full_name,
                            'account_name': user_info['account_name'],
                            'account_id': user_info['account_id'],
                            'region': user_info['region'],
                            'has_credentials': bool(user_info['access_key'] and user_info['secret_key'])
                        })
                        
                        selected_regions.add(user_info['region'])
                        selected_accounts.add(user_info['account_name'])
                    
                    print(f"\n{Symbols.OK} Selected {len(selected_indices)} users:")
                    print("-" * 80)
                    
                    # Group by account for display
                    by_account = {}
                    for user in selected_user_info:
                        account = user['account_name']
                        if account not in by_account:
                            by_account[account] = []
                        by_account[account].append(user)
                    
                    for account_name, users in by_account.items():
                        account_id = users[0]['account_id']
                        print(f"\n{Symbols.ACCOUNT} {account_name} ({account_id}) - {len(users)} users:")
                        for user in users:
                            creds_status = "[OK]" if user['has_credentials'] else f"{Symbols.ERROR}"
                            print(f"   • {user['full_name']} ({user['username']}) in {user['region']} {creds_status}")
                    
                    print("-" * 80)
                    print(f"{Symbols.STATS} Selection Summary:")
                    print(f"   👥 Users: {len(selected_indices)}")
                    print(f"   {Symbols.ACCOUNT} Accounts: {len(selected_accounts)}")
                    print(f"   {Symbols.REGION} Regions: {len(selected_regions)}")
                    
                    # Check for users without credentials
                    users_without_creds = [u for u in selected_user_info if not u['has_credentials']]
                    if users_without_creds:
                        print(f"   {Symbols.WARN}  Users without credentials: {len(users_without_creds)}")
                    
                    # Log selection details
                    self.log_operation('INFO', f"Selected users: {[u['username'] for u in selected_user_info]}")
                    self.log_operation('INFO', f"Selection summary: {len(selected_indices)} users, {len(selected_accounts)} accounts, {len(selected_regions)} regions")
                    
                    confirm = input(f"\n{Symbols.START} Proceed with these {len(selected_indices)} users? (y/N): ").lower().strip()
                    self.log_operation('INFO', f"User confirmation for user selection: '{confirm}'")
                    
                    if confirm == 'y':
                        return selected_indices, user_mapping
                    else:
                        print(f"{Symbols.ERROR} Selection cancelled, please choose again.")
                        self.log_operation('INFO', "User cancelled user selection, requesting new input")
                        continue
                else:
                    print(f"{Symbols.ERROR} No valid users selected. Please try again.")
                    self.log_operation('WARNING', "No valid users selected from user input")
                    continue
                    
            except ValueError as e:
                print(f"{Symbols.ERROR} Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                self.log_operation('ERROR', f"Invalid user selection format: {e}")
                continue

    def parse_user_selection(self, selection, max_users):
        """Parse user selection string and return list of user indices"""
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
                    
                    if start < 1 or end > max_users:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_users})")
                    
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
                    if num < 1 or num > max_users:
                        raise ValueError(f"User number {num} is out of bounds (1-{max_users})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid user number: {part}")
        
        return sorted(list(selected_indices))
    
    def display_instance_menu(self):
        """Display instance type selection menu"""
        allowed_types = self.ami_config['allowed_instance_types']
        default_type = self.ami_config['default_instance_type']
        
        self.log_operation('INFO', f"Displaying instance type menu - {len(allowed_types)} options available")
        
        print("\n🖥️  Available Instance Types:")
        for i, instance_type in enumerate(allowed_types, 1):
            marker = " (default)" if instance_type == default_type else ""
            print(f"  {i}. {instance_type}{marker}")
        
        while True:
            try:
                choice = input(f"\n[#] Select instance type (1-{len(allowed_types)}) or press Enter for default: ").strip()
                
                self.log_operation('INFO', f"User input for instance type: '{choice}'")
                
                if not choice:
                    self.log_operation('INFO', f"User selected default instance type: {default_type}")
                    return default_type
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(allowed_types):
                    selected_type = allowed_types[choice_num - 1]
                    self.log_operation('INFO', f"User selected instance type: {selected_type}")
                    return selected_type
                else:
                    print(f"{Symbols.ERROR} Invalid choice. Please enter a number between 1 and {len(allowed_types)}")
                    self.log_operation('WARNING', f"Invalid instance type choice: {choice}")
            except ValueError:
                print("[ERROR] Invalid input. Please enter a number or press Enter for default.")
                self.log_operation('WARNING', f"Invalid instance type input format: {choice}")

    # Add cost estimation display for both scripts:

    def display_approach_menu(self):
        """Display approach selection menu and return user choice"""
        print(f"\n{Symbols.TARGET} EC2 Instance Creation Approaches:")
        print("=" * 60)
        print("  1. Create instances for ALL accounts and users")
        print("  2. Select specific accounts to process")
        print("  3. Select specific users from accounts")
        print("  4. Show detailed analysis only (no creation)")
        print("  5. Exit")
        print("=" * 60)
        
        while True:
            choice = input("[#] Choose your approach (1-5): ").strip()
            self.log_operation('INFO', f"User input for approach selection: '{choice}'")
            
            if choice in ['1', '2', '3', '4', '5']:
                approach_names = {
                    '1': 'Create instances for ALL accounts and users',
                    '2': 'Select specific accounts to process',
                    '3': 'Select specific users from accounts',
                    '4': 'Show detailed analysis only',
                    '5': 'Exit'
                }
                print(f"{Symbols.OK} Selected approach: {choice}. {approach_names[choice]}")
                self.log_operation('INFO', f"User selected approach {choice}: {approach_names[choice]}")
                return int(choice)
            else:
                print("[ERROR] Invalid choice. Please enter a number between 1 and 5.")
                self.log_operation('WARNING', f"Invalid approach choice: {choice}")

    def show_detailed_analysis(self):
        """Show detailed analysis of accounts, users, and costs without creating instances"""
        print(f"\n{Symbols.STATS} DETAILED ANALYSIS")
        print("=" * 80)
        
        if 'accounts' not in self.credentials_data:
            print(f"{Symbols.ERROR} No accounts found in credentials data")
            return
        
        accounts = list(self.credentials_data['accounts'].items())
        total_users = 0
        regions_used = set()
        users_by_region = {}
        
        print(f"\n{Symbols.ACCOUNT} ACCOUNT ANALYSIS ({len(accounts)} accounts):")
        print("-" * 80)
        
        for i, (account_name, account_data) in enumerate(accounts, 1):
            user_count = len(account_data.get('users', []))
            total_users += user_count
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            account_regions = set()
            for user in account_data.get('users', []):
                region = user.get('region', 'unknown')
                account_regions.add(region)
                regions_used.add(region)
                users_by_region[region] = users_by_region.get(region, 0) + 1
            
            print(f"  {i:2}. {account_name}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      📧 Email: {account_email}")
            print(f"      👥 Users: {user_count}")
            print(f"      {Symbols.REGION} Regions: {', '.join(sorted(account_regions))}")
            print()
        
        # Regional analysis
        print(f"\n{Symbols.REGION} REGIONAL DISTRIBUTION:")
        print("-" * 60)
        for region in sorted(regions_used):
            user_count = users_by_region.get(region, 0)
            print(f"  {region}: {user_count} users")
        
        # Cost analysis
        print(f"\n{Symbols.COST} COST ESTIMATION (if all instances were created):")
        print("-" * 60)
        default_instance_type = self.ami_config.get('default_instance_type', 't3.micro')
        
        print(f"  Instance Type: {default_instance_type}")
        print(f"  Total Users: {total_users}")
        self.display_cost_estimation(default_instance_type, 'spot', total_users)
        self.display_cost_estimation(default_instance_type, 'on-demand', total_users)
        
        # Summary
        print(f"\n{Symbols.LIST} SUMMARY:")
        print("-" * 40)
        print(f"  [UP] Total accounts: {len(accounts)}")
        print(f"  👥 Total users: {total_users}")
        print(f"  {Symbols.REGION} Total regions: {len(regions_used)}")
        print(f"  📄 Credentials file: {self.credentials_file}")
        print(f"  📜 User data script: {self.userdata_file}")
        
        input("\nPress Enter to continue...")

    def display_cost_estimation(self, instance_type: str, capacity_type: str, node_count: int = 1):
        """Display estimated cost information"""
        # This is a simplified estimation - you'd want to use actual AWS pricing API
        base_costs = {
            't3.micro': 0.0104,
            't3.small': 0.0208,
            't3.medium': 0.0416,
            'c6a.large': 0.0864,
            'c6a.xlarge': 0.1728
        }
        
        base_cost = base_costs.get(instance_type, 0.05)  # Default fallback
        
        if capacity_type.lower() in ['spot', 'SPOT']:
            estimated_cost = base_cost * 0.3  # Spot instances are typically 70% cheaper
            savings = base_cost * 0.7
            print(f"\n{Symbols.COST} Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Spot: ${estimated_cost:.4f}")
            print(f"   Savings: ${savings:.4f} ({70}%)")
            print(f"   Monthly (730 hrs): ${estimated_cost * 730 * node_count:.2f}")
        else:
            print(f"\n{Symbols.COST} Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Monthly (730 hrs): ${base_cost * 730 * node_count:.2f}")

    def run(self):
        """Main execution method with integrated intelligent spot analysis"""
        try:
            self.log_operation('INFO', f"{Symbols.START} Starting EC2 Instance Creation Session")
            
            print(f"{Symbols.START} EC2 Instance Creation for IAM Users")
            print("=" * 80)
            print(f"{Symbols.DATE} Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📄 Credentials Source: {self.credentials_file}")
            print(f"📜 User Data Script: {self.userdata_file}")
            print(f"{Symbols.LIST} Log File: {self.log_filename}")
            
            # Display credential file info
            if 'created_date' in self.credentials_data:
                cred_time = f"{self.credentials_data['created_date']} {self.credentials_data.get('created_time', '')}"
                print(f"{Symbols.DATE} Credentials created: {cred_time}")
                self.log_operation('INFO', f"Using credentials created: {cred_time}")
            if 'created_by' in self.credentials_data:
                print(f"👤 Credentials created by: {self.credentials_data['created_by']}")
            
            print("=" * 80)
            
            # Verify user data file exists
            if os.path.exists(self.userdata_file):
                file_size = os.path.getsize(self.userdata_file)
                print(f"{Symbols.OK} User data script found: {self.userdata_file}")
                print(f"📏 Script size: {file_size} bytes")
                self.log_operation('INFO', f"User data script verified: {self.userdata_file} ({file_size} bytes)")
            else:
                print(f"{Symbols.ERROR} User data script not found: {self.userdata_file}")
                self.log_operation('ERROR', f"User data script not found: {self.userdata_file}")
                return
            
            # Step 1: Select accounts to process
            selected_account_indices = self.display_accounts_menu()
            if not selected_account_indices:
                self.log_operation('INFO', "Session cancelled - no accounts selected")
                print(f"{Symbols.ERROR} Account selection cancelled")
                return
            
            selected_accounts = self.get_selected_accounts_data(selected_account_indices)
            
            # Step 2: User selection level
            print(f"\n{Symbols.TARGET} Selection Level:")
            print("=" * 50)
            print("  1. Process ALL users in selected accounts")
            print("  2. Select specific users from selected accounts")
            print("=" * 50)
            
            while True:
                selection_level = input("[#] Choose selection level (1-2): ").strip()
                self.log_operation('INFO', f"User input for selection level: '{selection_level}'")
                
                if selection_level == '1':
                    self.log_operation('INFO', "User chose to process all users in selected accounts")
                    final_accounts = selected_accounts
                    break
                elif selection_level == '2':
                    self.log_operation('INFO', "User chose user-level selection")
                    selected_user_indices, user_mapping = self.display_users_menu(selected_accounts)
                    if not selected_user_indices:
                        self.log_operation('INFO', "Session cancelled - no users selected")
                        print(f"{Symbols.ERROR} User selection cancelled")
                        return
                    final_accounts = self.convert_selected_users_to_accounts(selected_user_indices, user_mapping)
                    break
                else:
                    print(f"{Symbols.ERROR} Invalid choice. Please enter 1 or 2.")
                    self.log_operation('WARNING', f"Invalid selection level choice: {selection_level}")
            
            # Step 3: Intelligent instance selection (includes all analysis)
            print(f"\n[BRAIN] Intelligent Instance & Capacity Selection")
            print("=" * 55)
            print("This includes automatic spot availability analysis and recommendations.")
            instance_type, capacity_type = self.select_instance_with_smart_analysis()
            
            # Calculate totals
            total_users = sum(len(account_data.get('users', [])) 
                            for account_data in final_accounts.values())
            
            # Step 4: Final confirmation and execution
            print(f"\n{Symbols.STATS} Final Execution Summary:")
            print("=" * 60)
            print(f"   [UP] Selected accounts: {len(final_accounts)}")
            print(f"   👥 Total users: {total_users}")
            print(f"   💻 Instance type: {instance_type}")
            print(f"   [TAG]  Capacity type: {capacity_type.upper()}")
            
            # Show cost estimation
            print(f"\n{Symbols.COST} Cost Estimation for {total_users} {capacity_type} instances:")
            self.display_cost_estimation(instance_type, capacity_type, total_users)
            
            # Show account/user breakdown
            print(f"\n{Symbols.ACCOUNT} Account/User Breakdown:")
            for account_name, account_data in final_accounts.items():
                user_count = len(account_data.get('users', []))
                account_id = account_data.get('account_id', 'Unknown')
                print(f"   • {account_name} ({account_id}): {user_count} users")
                
                # Show first few users as sample
                for i, user_data in enumerate(account_data.get('users', [])[:3]):
                    username = user_data.get('username', 'unknown')
                    real_user = user_data.get('real_user', {})
                    full_name = real_user.get('full_name', username)
                    region = user_data.get('region', 'unknown')
                    print(f"     - {full_name} ({username}) in {region}")
                
                if user_count > 3:
                    print(f"     ... and {user_count - 3} more users")
            
            print(f"\n🔧 Configuration:")
            print(f"   📜 User data: {self.userdata_file}")
            print(f"   📄 Credentials: {self.credentials_file}")
            print(f"   {Symbols.LIST} Log file: {self.log_filename}")
            
            # Show capacity-specific information
            if capacity_type == 'spot':
                print(f"\n{Symbols.TIP} Spot Instance Information:")
                print(f"   {Symbols.OK} Estimated 60-70% cost savings")
                print(f"   {Symbols.WARN}  May be interrupted if AWS needs capacity")
                print(f"   {Symbols.SCAN} Automatic termination on interruption")
            else:
                print(f"\n{Symbols.SECURE} On-Demand Instance Information:")
                print(f"   {Symbols.OK} Guaranteed availability and stability")
                print(f"   {Symbols.COST} Standard AWS pricing")
                print(f"   {Symbols.SECURE} No interruption risk")
            
            print("=" * 60)
            
            # Log final configuration
            self.log_operation('INFO', f"Final configuration - Accounts: {len(final_accounts)}, Users: {total_users}, Instance: {instance_type}, Capacity: {capacity_type}")
            
            # Final confirmation
            capacity_emoji = "[COST]" if capacity_type == 'spot' else f"{Symbols.SECURE}"
            confirm = input(f"\n{Symbols.START} Create {total_users} {capacity_emoji} {capacity_type.upper()} EC2 instances? (y/N): ").lower().strip()
            self.log_operation('INFO', f"Final confirmation: '{confirm}'")
            
            if confirm != 'y':
                self.log_operation('INFO', "Session cancelled by user at final confirmation")
                print(f"{Symbols.ERROR} Instance creation cancelled")
                return
            
            # Execute instance creation
            print(f"\n{Symbols.SCAN} Starting {capacity_type} instance creation for {total_users} users...")
            print("This may take several minutes depending on the number of instances...")
            self.log_operation('INFO', f"{Symbols.SCAN} Beginning {capacity_type} instance creation for {total_users} users")
            
            created_instances, failed_instances = self.create_instances_for_selected_accounts(
                final_accounts,
                instance_type=instance_type,
                capacity_type=capacity_type,
                wait_for_running=True
            )
            
            # Display comprehensive results
            print(f"\n" + "[TARGET]" * 20 + " CREATION RESULTS " + "[TARGET]" * 20)
            print("=" * 80)
            
            success_count = len(created_instances)
            failure_count = len(failed_instances)
            total_processed = success_count + failure_count
            success_rate = (success_count / total_processed * 100) if total_processed > 0 else 0
            
            print(f"{Symbols.STATS} SUMMARY:")
            print(f"   {Symbols.OK} Successfully created: {success_count}")
            print(f"   {Symbols.ERROR} Failed: {failure_count}")
            print(f"   [UP] Success rate: {success_rate:.1f}%")
            print(f"   [TAG]  Capacity type: {capacity_type.upper()}")
            print(f"   💻 Instance type: {instance_type}")
            
            # Show successful instances
            if created_instances:
                print(f"\n{Symbols.OK} SUCCESSFUL INSTANCES ({success_count}):")
                print("-" * 60)
                
                # Group by account for better organization
                by_account = {}
                for instance in created_instances:
                    account_name = instance.get('account_name', 'Unknown')
                    if account_name not in by_account:
                        by_account[account_name] = []
                    by_account[account_name].append(instance)
                
                for account_name, instances in by_account.items():
                    account_id = instances[0].get('account_id', 'Unknown')
                    print(f"\n{Symbols.ACCOUNT} {account_name} ({account_id}) - {len(instances)} instances:")
                    
                    for instance in instances:
                        real_name = instance.get('real_user_info', {}).get('full_name', instance['username'])
                        capacity_symbol = f"{Symbols.COST}" if instance.get('capacity_type') == 'spot' else f"{Symbols.SECURE}"
                        
                        print(f"   {capacity_symbol} {real_name} ({instance['username']})")
                        print(f"      📍 ID: {instance['instance_id']}")
                        print(f"      {Symbols.REGION} Region: {instance['region']}")
                        
                        if 'public_ip' in instance and instance['public_ip'] != 'N/A':
                            print(f"      🌐 Public IP: {instance['public_ip']}")
                        
                        if 'startup_time_seconds' in instance:
                            print(f"      {Symbols.TIMER}  Startup: {instance['startup_time_seconds']}s")
                        
                        print()
            
            # Show failed instances
            if failed_instances:
                print(f"\n{Symbols.ERROR} FAILED INSTANCES ({failure_count}):")
                print("-" * 60)
                
                for failure in failed_instances:
                    print(f"   • {failure.get('real_name', failure['username'])} ({failure['username']})")
                    print(f"     {Symbols.ACCOUNT} Account: {failure['account_name']}")
                    print(f"     {Symbols.REGION} Region: {failure['region']}")
                    print(f"     {Symbols.ERROR} Error: {failure['error']}")
                    print()
            
            # Cost savings summary for spot instances
            spot_instances = [i for i in created_instances if i.get('capacity_type') == 'spot']
            if spot_instances:
                print(f"\n{Symbols.COST} COST SAVINGS SUMMARY:")
                print("-" * 40)
                print(f"   [TAG]  Spot instances: {len(spot_instances)}")
                print(f"   💵 Estimated savings: 60-70% vs On-Demand")
                print(f"   {Symbols.STATS} Monthly savings: Significant cost reduction")
                print(f"   {Symbols.WARN}  Interruption risk: Monitor for capacity changes")
            
            # Save reports
            print(f"\n📄 Saving reports and logs...")
            
            mapping_file = self.save_user_instance_mapping(created_instances, failed_instances)
            if mapping_file:
                print(f"{Symbols.OK} User-instance mapping: {mapping_file}")
            
            report_file = self.save_instance_report(created_instances, failed_instances)
            if report_file:
                print(f"{Symbols.OK} Detailed report: {report_file}")
            
            print(f"{Symbols.OK} Session log: {self.log_filename}")
            
            # Final summary log
            self.log_operation('INFO', "=" * 80)
            self.log_operation('INFO', "SESSION COMPLETED SUCCESSFULLY")
            self.log_operation('INFO', f"Total processed: {total_processed}")
            self.log_operation('INFO', f"Successfully created: {success_count}")
            self.log_operation('INFO', f"Failed: {failure_count}")
            self.log_operation('INFO', f"Success rate: {success_rate:.1f}%")
            self.log_operation('INFO', f"Capacity type: {capacity_type}")
            self.log_operation('INFO', f"Instance type: {instance_type}")
            
            if spot_instances:
                self.log_operation('INFO', f"Spot instances created: {len(spot_instances)}")
                self.log_operation('INFO', "Estimated cost savings: 60-70% vs On-Demand")
            
            if mapping_file:
                self.log_operation('INFO', f"Mapping file: {mapping_file}")
            if report_file:
                self.log_operation('INFO', f"Report file: {report_file}")
            self.log_operation('INFO', "=" * 80)
            
            # Final success message
            print(f"\n[PARTY] EC2 Instance Creation Completed!")
            print(f"{Symbols.STATS} Success Rate: {success_rate:.1f}%")
            print(f"[TAG]  Capacity: {capacity_type.upper()}")
            print(f"💻 Type: {instance_type}")
            
            if success_count > 0:
                print(f"{Symbols.OK} {success_count} instances are now running and ready to use!")
            
            if spot_instances:
                print(f"{Symbols.COST} You're saving an estimated 60-70% with {len(spot_instances)} spot instances!")
            
            print("=" * 80)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in main execution: {str(e)}")
            print(f"\n{Symbols.ERROR} FATAL ERROR: {str(e)}")
            print("Check the log file for detailed error information.")
            raise
            
def main():
    """Main function"""
    try:
        manager = EC2InstanceManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n[ERROR] Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"{Symbols.ERROR} Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()