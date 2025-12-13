# Databricks notebook source
import boto3
import pandas as pd
import requests
import json
import re
import os
from datetime import datetime, timedelta
from pathlib import Path
import logging
import pytz

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EC2SpotAnalyzer:
    def __init__(self, region='us-east-1', cache_dir='cache'):
        self.region = region
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_ttl_hours = 1
        # Set IST timezone
        self.ist_tz = pytz.timezone('Asia/Kolkata')
        
    def _get_current_ist_time(self):
        """Get current time in IST"""
        return datetime.now(self.ist_tz)
    
    def _get_cache_filename(self, data_type, region, instance_types_hash):
        """Generate cache filename based on data type and parameters"""
        return self.cache_dir / f"{data_type}_{region}_{instance_types_hash}.json"
    
    def _get_instance_types_hash(self, instance_types):
        """Generate a hash for instance types to use in cache filename"""
        return str(hash(tuple(sorted(instance_types))))
    
    def _is_cache_valid(self, cache_file):
        """Check if cache file exists and is within TTL"""
        if not cache_file.exists():
            return False
        
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            
            cache_time = datetime.fromisoformat(cache_data.get('timestamp', ''))
            # Convert to IST if timezone info is present
            if cache_time.tzinfo:
                cache_time_ist = cache_time.astimezone(self.ist_tz)
            else:
                cache_time_ist = self.ist_tz.localize(cache_time)
            
            current_time_ist = self._get_current_ist_time()
            return current_time_ist - cache_time_ist < timedelta(hours=self.cache_ttl_hours)
        except Exception as e:
            logger.warning(f"Cache validation error: {e}")
            return False
    
    def _save_to_cache(self, data, cache_file, created_by="system"):
        """Save data to cache with metadata"""
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
    
    def _load_from_cache(self, cache_file):
        """Load data from cache"""
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        return cache_data['data']

    def get_service_quotas(self, instance_types, created_by="system"):
        """
        Fetch EC2 Spot instance quotas for specific instance families in the given region.
        Returns a dictionary of quotas by instance family.
        """
        instance_types_hash = self._get_instance_types_hash(instance_types)
        cache_file = self._get_cache_filename('quotas', self.region, instance_types_hash)
        
        # Check cache first
        if self._is_cache_valid(cache_file):
            logger.info("Loading service quotas from cache")
            return self._load_from_cache(cache_file)
        
        logger.info("Fetching service quotas from AWS API")
        service_quotas = boto3.client('service-quotas', region_name=self.region)
        
        # Get instance families like "m7g" from instance types like "m7g.medium"
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
                        'QuotaValue': quota['Value'],
                        'Unit': quota['Unit']
                    }

        # If no specific spot quotas found, add default values
        for family in instance_families:
            if family not in quotas_by_family:
                quotas_by_family[family] = {
                    'QuotaName': f"Default {family.upper()} Spot Instance Requests",
                    'QuotaValue': 256,  # Default quota
                    'Unit': 'None'
                }

        # Cache the results
        self._save_to_cache(quotas_by_family, cache_file, created_by)
        return quotas_by_family

    def get_spot_analysis(self, instance_types, created_by="system"):
        """
        Perform comprehensive spot instance analysis including prices, placement scores, and interruption rates.
        """
        instance_types_hash = self._get_instance_types_hash(instance_types)
        cache_file = self._get_cache_filename('spot_analysis', self.region, instance_types_hash)
        
        # Check cache first
        if self._is_cache_valid(cache_file):
            logger.info("Loading spot analysis from cache")
            return self._load_from_cache(cache_file)
        
        logger.info("Performing fresh spot analysis")
        
        try:
            # Get all spot analysis data
            prices = self._get_spot_prices(instance_types)
            scores = self._get_spot_placement_scores(instance_types)
            interrupt_rates = self._fetch_real_interruption_rates()
            
            analysis_data = {
                'prices': prices,
                'scores': scores,
                'interrupt_rates': interrupt_rates
            }
            
            # Cache the results
            self._save_to_cache(analysis_data, cache_file, created_by)
            return analysis_data
            
        except Exception as e:
            logger.error(f"Error in spot analysis: {e}")
            raise

    def _fetch_real_interruption_rates(self):
        """Scrapes the real-time interruption rates from Spot Advisor embedded JSON."""
        logger.info("Fetching interruption rates from AWS Spot Advisor")
        url = "https://aws.amazon.com/ec2/spot/instance-advisor/"
        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.warning("Failed to fetch Spot Advisor page, using default rates")
                return {}

            match = re.search(r"window\.spotAdvisorData\s*=\s*(\{.*?\});", response.text, re.DOTALL)
            if not match:
                logger.warning("Could not find embedded spotAdvisorData, using default rates")
                return {}

            raw_json = match.group(1)
            data = json.loads(raw_json)
            result = {}

            for itype, details in data.get("instanceTypeData", {}).items():
                try:
                    rate = float(details.get("interruptionRate", "10%").replace("%", ""))
                    result[itype] = rate
                except:
                    continue

            return result
        except Exception as e:
            logger.warning(f"Error fetching interruption rates: {e}, using defaults")
            return {}

    def _get_spot_placement_scores(self, instance_types):
        """Get spot placement scores for instance types"""
        logger.info("Fetching spot placement scores")
        ec2 = boto3.client('ec2', region_name=self.region)
        
        try:
            response = ec2.get_spot_placement_scores(
                InstanceTypes=instance_types,
                TargetCapacity=5,
                SingleAvailabilityZone=True
            )

            scores = []
            for score in response['SpotPlacementScores']:
                for az in score.get('AvailabilityZoneScores', []):
                    scores.append({
                        'Region': score['Region'],
                        'AZ': az['AvailabilityZone'],
                        'Score': az['Score']
                    })
            return scores
        except Exception as e:
            logger.warning(f"Error fetching placement scores: {e}")
            return []

    def _get_spot_prices(self, instance_types):
        """Get current spot prices for instance types"""
        logger.info("Fetching spot prices")
        ec2 = boto3.client('ec2', region_name=self.region)

        spot_prices = []
        for itype in instance_types:
            try:
                response = ec2.describe_spot_price_history(
                    InstanceTypes=[itype],
                    ProductDescriptions=["Linux/UNIX"],
                    MaxResults=3  # Get multiple AZs
                )
                for price_info in response['SpotPriceHistory']:
                    spot_prices.append({
                        'InstanceType': itype,
                        'AZ': price_info['AvailabilityZone'],
                        'SpotPrice': float(price_info['SpotPrice'])
                    })
            except Exception as e:
                logger.warning(f"Error fetching price for {itype}: {e}")
                continue
                
        return spot_prices

    def merge_analysis_data(self, spot_analysis_data, service_quotas_data):
        """
        Utility method to merge spot analysis data with service quotas data.
        Returns a sorted DataFrame with comprehensive analysis.
        Sorting: InterruptRate (asc), Score (desc), ServiceQuota (desc)
        """
        logger.info("Merging analysis data")
        
        prices = spot_analysis_data['prices']
        scores = spot_analysis_data['scores']
        interrupt_rates = spot_analysis_data['interrupt_rates']

        # Create DataFrames
        df_prices = pd.DataFrame(prices)
        df_scores = pd.DataFrame(scores)
        
        if df_prices.empty:
            logger.warning("No price data available")
            return pd.DataFrame()

        # If no scores available, create dummy scores
        if df_scores.empty:
            logger.warning("No placement scores available, using default scores")
            unique_azs = df_prices['AZ'].unique()
            df_scores = pd.DataFrame([
                {'Region': self.region, 'AZ': az, 'Score': 5} 
                for az in unique_azs
            ])

        # Merge price and score data
        df = pd.merge(df_prices, df_scores, how='left', on='AZ')
        df['Score'] = df['Score'].fillna(5)  # Default score if missing

        # Add interruption rates
        df['InterruptRate'] = df['InstanceType'].map(interrupt_rates).fillna(10.0)
        
        # Add service quota information
        df['ServiceQuota'] = df['InstanceType'].apply(
            lambda x: self._get_quota_for_instance(x, service_quotas_data)
        )
        
        # Sort by: InterruptRate (ascending), Score (descending), ServiceQuota (descending)
        df = df.sort_values(
            by=['InterruptRate', 'Score', 'ServiceQuota'], 
            ascending=[True, False, False]
        ).reset_index(drop=True)
        
        # Add analysis metadata with IST timestamp
        df['AnalysisTimestamp'] = self._get_current_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')
        df['Region'] = self.region
        df['Rank'] = range(1, len(df) + 1)  # Add ranking based on sort order
        
        return df

    def _get_quota_for_instance(self, instance_type, service_quotas_data):
        """Get service quota for a specific instance type"""
        family = instance_type.split('.')[0]
        quota_info = service_quotas_data.get(family, {})
        return quota_info.get('QuotaValue', 256)  # Default quota if not found

    def save_to_json(self, df, filename=None):
        """Save DataFrame to JSON file"""
        if filename is None:
            timestamp = self._get_current_ist_time().strftime("%Y%m%d_%H%M%S")
            filename = f"ec2_spot_analysis_{self.region}_{timestamp}.json"
        
        filepath = self.cache_dir / filename
        
        # Convert DataFrame to JSON with metadata
        output_data = {
            'metadata': {
                'analysis_timestamp': self._get_current_ist_time().isoformat(),
                'timezone': 'Asia/Kolkata',
                'region': self.region,
                'total_records': len(df),
                'sorting_criteria': [
                    {'field': 'InterruptRate', 'order': 'ascending'},
                    {'field': 'Score', 'order': 'descending'}, 
                    {'field': 'ServiceQuota', 'order': 'descending'}
                ]
            },
            'data': df.to_dict('records')
        }
        
        with open(filepath, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        logger.info(f"JSON results saved to {filepath}")
        return filepath

    def save_to_excel(self, df, filename=None):
        """Save DataFrame to Excel file"""
        if filename is None:
            timestamp = self._get_current_ist_time().strftime("%Y%m%d_%H%M%S")
            filename = f"ec2_spot_analysis_{self.region}_{timestamp}.xlsx"
        
        filepath = self.cache_dir / filename
        
        # Create Excel writer with multiple sheets
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Main analysis sheet (sorted data)
            df_display = df[[
                'Rank', 'InstanceType', 'AZ', 'SpotPrice', 'Score', 
                'InterruptRate', 'ServiceQuota', 'AnalysisTimestamp', 'Region'
            ]].copy()
            df_display.to_excel(writer, sheet_name='Sorted_Analysis', index=False)
            
            # Summary sheet
            summary_df = self._create_summary(df)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Best recommendations (top 5)
            best_df = df.head(5)[[
                'Rank', 'InstanceType', 'AZ', 'SpotPrice', 'Score', 
                'InterruptRate', 'ServiceQuota'
            ]].copy()
            best_df.to_excel(writer, sheet_name='Top_Recommendations', index=False)
        
        logger.info(f"Excel results saved to {filepath}")
        return filepath

    def _create_summary(self, df):
        """Create a summary DataFrame grouped by instance type"""
        if df.empty:
            return pd.DataFrame()
        
        summary = df.groupby('InstanceType').agg({
            'SpotPrice': ['min', 'max', 'mean', 'count'],
            'Score': ['min', 'max', 'mean'],
            'InterruptRate': 'first',
            'ServiceQuota': 'first',
            'Rank': 'min'  # Best rank for this instance type
        }).round(4)
        
        # Flatten column names
        summary.columns = ['_'.join(col).strip() for col in summary.columns]
        summary = summary.reset_index()
        
        # Rename columns for better readability
        column_mapping = {
            'SpotPrice_count': 'AZ_Count',
            'Rank_min': 'Best_Rank'
        }
        summary = summary.rename(columns=column_mapping)
        
        # Sort by best rank
        summary = summary.sort_values('Best_Rank').reset_index(drop=True)
        
        return summary

    def run_full_analysis(self, instance_types, created_by="system", save_json=True, save_excel=True):
        """
        Run complete analysis including service quotas and spot analysis.
        """
        logger.info(f"Starting full analysis for {len(instance_types)} instance types in {self.region}")
        logger.info(f"Current IST time: {self._get_current_ist_time().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Get service quotas
            service_quotas = self.get_service_quotas(instance_types, created_by)
            
            # Get spot analysis
            spot_analysis = self.get_spot_analysis(instance_types, created_by)
            
            # Merge data
            result_df = self.merge_analysis_data(spot_analysis, service_quotas)
            
            if result_df.empty:
                logger.warning("No data available for analysis")
                return None
            
            # Save files
            json_file = None
            excel_file = None
            
            if save_json:
                json_file = self.save_to_json(result_df)
            
            if save_excel:
                excel_file = self.save_to_excel(result_df)
            
            logger.info("Full analysis completed successfully")
            logger.info(f"Results sorted by: InterruptRate↑, Score↓, ServiceQuota↓")
            
            return {
                'dataframe': result_df,
                'json_file': json_file,
                'excel_file': excel_file,
                'service_quotas': service_quotas,
                'spot_analysis': spot_analysis,
                'summary_stats': {
                    'total_combinations': len(result_df),
                    'unique_instance_types': result_df['InstanceType'].nunique(),
                    'unique_azs': result_df['AZ'].nunique(),
                    'best_combination': result_df.iloc[0].to_dict() if not result_df.empty else None
                }
            }
            
        except Exception as e:
            logger.error(f"Error in full analysis: {e}")
            raise


def main():
    """Example usage"""
    # Initialize analyzer
    analyzer = EC2SpotAnalyzer(region='us-east-1')
    
    # Define instance types to analyze
    instance_types = ['m7g.medium', 'r6g.large', 'c6gd.large']
    
    # Run full analysis
    try:
        results = analyzer.run_full_analysis(
            instance_types=instance_types,
            created_by="varadharajaan",
            save_json=True,
            save_excel=True
        )
        
        if results:
            print("\n" + "="*80)
            print("EC2 SPOT INSTANCE ANALYSIS RESULTS")
            print("="*80)
            print(f"Analysis Time: {analyzer._get_current_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')}")
            print(f"Region: {analyzer.region}")
            print(f"Sorting: InterruptRate↑, Score↓, ServiceQuota↓")
            print("="*80)
            
            # Display results table
            display_df = results['dataframe'][[
                'Rank', 'InstanceType', 'AZ', 'SpotPrice', 'Score', 
                'InterruptRate', 'ServiceQuota'
            ]].copy()
            
            print(display_df.to_string(index=False, float_format='%.4f'))
            
            print("\n" + "-"*50)
            print("SUMMARY STATISTICS")
            print("-"*50)
            stats = results['summary_stats']
            print(f"Total Combinations: {stats['total_combinations']}")
            print(f"Unique Instance Types: {stats['unique_instance_types']}")
            print(f"Unique Availability Zones: {stats['unique_azs']}")
            
            if stats['best_combination']:
                best = stats['best_combination']
                print(f"\nBEST RECOMMENDATION:")
                print(f"  Instance: {best['InstanceType']} in {best['AZ']}")
                print(f"  Price: ${best['SpotPrice']:.4f}/hour")
                print(f"  Interruption Rate: {best['InterruptRate']}%")
                print(f"  Placement Score: {best['Score']}")
                print(f"  Service Quota: {best['ServiceQuota']}")
            
            print("\n" + "-"*50)
            print("FILES CREATED")
            print("-"*50)
            if results['json_file']:
                print(f"JSON: {results['json_file']}")
            if results['excel_file']:
                print(f"Excel: {results['excel_file']}")
                
        else:
            print("No results available")
            
    except Exception as e:
        logger.error(f"Analysis failed: {e}")


if __name__ == "__main__":
    main()