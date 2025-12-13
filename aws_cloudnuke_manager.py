#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path
import logging
from datetime import datetime
import time
import threading
import queue
import re
from text_symbols import Symbols


class CloudNukeManager:
    def __init__(self):
        self.config_file = "aws_accounts_config.json"
        self.cloudnuke_exe = "./cloud-nuke_windows_amd64.exe"
        self.aws_regions = [
            "us-east-1", "us-east-2", "us-west-1", "us-west-2",
            "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1",
            "eu-north-1", "eu-south-1", "ap-south-1", "ap-southeast-1",
            "ap-southeast-2", "ap-northeast-1", "ap-northeast-2",
            "ap-northeast-3", "ap-east-1", "sa-east-1", "ca-central-1",
            "me-south-1", "af-south-1"
        ]
        self.resource_types = [
            "accessanalyzer", "acm", "acmpca", "ami", "apigateway",
            "apigatewayv2", "app-runner-service", "asg", "backup-vault",
            "cloudtrail", "cloudwatch-alarm", "cloudwatch-dashboard",
            "cloudwatch-loggroup", "codedeploy-application", "config-recorders",
            "config-rules", "data-sync-location", "data-sync-task", "dynamodb",
            "ebs", "ec2", "ec2-dedicated-hosts", "ec2-endpoint", "ec2-keypairs",
            "ec2-placement-groups", "ec2-subnet", "ec2_dhcp_option", "ecr",
            "ecscluster", "ecsserv", "efs", "egress-only-internet-gateway",
            "eip", "ekscluster", "elastic-beanstalk", "elasticache",
            "elasticacheParameterGroups", "elasticacheSubnetGroups",
            "elasticcache-serverless", "elb", "elbv2", "event-bridge",
            "event-bridge-archive", "event-bridge-rule", "event-bridge-schedule",
            "event-bridge-schedule-group", "grafana", "guardduty", "iam",
            "iam-group", "iam-instance-profile", "iam-policy", "iam-role",
            "iam-service-linked-role", "internet-gateway", "ipam", "ipam-byoasn",
            "ipam-custom-allocation", "ipam-pool", "ipam-resource-discovery",
            "ipam-scope", "kinesis-firehose", "kinesis-stream", "kmscustomerkeys",
            "lambda", "lambda_layer", "lc", "lt", "macie-member",
            "managed-prometheus", "msk-cluster", "nat-gateway", "network-acl",
            "network-firewall", "network-firewall-policy",
            "network-firewall-resource-policy", "network-firewall-rule-group",
            "network-firewall-tls-config", "network-interface", "oidcprovider",
            "opensearchdomain", "rds", "rds-cluster", "rds-global-cluster",
            "rds-global-cluster-membership", "rds-parameter-group", "rds-proxy",
            "rds-snapshot", "rds-subnet-group", "redshift",
            "route53-cidr-collection", "route53-hosted-zone",
            "route53-traffic-policy", "s3", "s3-ap", "s3-mrap", "s3-olap",
            "sagemaker-notebook-smni", "sagemaker-studio", "secretsmanager",
            "security-group", "security-hub", "ses-configuration-set",
            "ses-email-template", "ses-identity", "ses-receipt-filter",
            "ses-receipt-rule-set", "snap", "snstopic", "sqs", "transit-gateway",
            "transit-gateway-attachment", "transit-gateway-peering-attachment",
            "transit-gateway-route-table", "vpc", "vpc-lattice-service",
            "vpc-lattice-service-network", "vpc-lattice-target-group"
        ]
        self.setup_enhanced_logging()
        
    def setup_logging(self):
        """Setup logging configuration"""
        log_filename = f"cloudnuke_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def load_config(self):
        """Load AWS accounts configuration from JSON file"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.logger.info(f"Successfully loaded configuration from {self.config_file}")
            return config
        except FileNotFoundError:
            self.logger.error(f"Configuration file {self.config_file} not found!")
            sys.exit(1)
        except json.JSONDecodeError:
            self.logger.error(f"Invalid JSON in {self.config_file}")
            sys.exit(1)
            
    def setup_aws_profiles(self, accounts):
        """Setup AWS profiles using AWS CLI"""
        self.logger.info("Setting up AWS profiles...")
        
        for profile_name, account_info in accounts.items():
            try:
                subprocess.run([
                    "aws", "configure", "set", "aws_access_key_id",
                    account_info["access_key"], "--profile", profile_name
                ], check=True, capture_output=True)
                
                subprocess.run([
                    "aws", "configure", "set", "aws_secret_access_key",
                    account_info["secret_key"], "--profile", profile_name
                ], check=True, capture_output=True)
                
                subprocess.run([
                    "aws", "configure", "set", "region",
                    "us-east-1", "--profile", profile_name
                ], check=True, capture_output=True)
                
                self.logger.info(f"Profile '{profile_name}' configured successfully")
                
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to configure profile '{profile_name}': {e}")
                
    def display_options(self, items, item_type):
        """Display numbered list of options"""
        print(f"\n{item_type}:")
        for i, item in enumerate(items, 1):
            print(f"{i:3d}. {item}")
        print(f"{len(items)+1:3d}. ALL")
        
    def get_user_selection(self, items, item_type, action="select"):
        """Get user selection for regions or resource types"""
        self.display_options(items, item_type)
        
        selection = input(f"\nEnter numbers to {action} (comma-separated, range with -, or 'all'): ").strip()
        
        if not selection:
            return []
            
        if selection.lower() == 'all' or selection == str(len(items) + 1):
            return items
            
        selected = []
        parts = selection.split(',')
        
        for part in parts:
            part = part.strip()
            if '-' in part and not part.startswith('-'):
                try:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        if 1 <= i <= len(items):
                            selected.append(items[i-1])
                except ValueError:
                    self.logger.warning(f"Invalid range: {part}")
            else:
                try:
                    num = int(part)
                    if 1 <= num <= len(items):
                        selected.append(items[num-1])
                except ValueError:
                    self.logger.warning(f"Invalid number: {part}")
                    
        return list(set(selected))
        
    def get_region_configuration(self):
        """Get region configuration from user"""
        print("\nRegion Configuration:")
        print("1. Include specific regions")
        print("2. Exclude specific regions")
        
        choice = input("Enter choice (press Enter for all regions): ").strip()
        
        if not choice:
            return "all", []
            
        if choice == "1":
            selected = self.get_user_selection(self.aws_regions, "Available Regions", "include")
            return "include", selected
        elif choice == "2":
            selected = self.get_user_selection(self.aws_regions, "Available Regions", "exclude")
            return "exclude", selected
        else:
            return "all", []
            
    def get_resource_configuration(self):
        """Get resource type configuration from user"""
        print("\nResource Type Configuration:")
        print("1. Include specific resource types")
        print("2. Exclude specific resource types")
        
        choice = input("Enter choice (press Enter for all resources): ").strip()
        
        if not choice:
            return "all", []
            
        if choice == "1":
            selected = self.get_user_selection(self.resource_types, "Available Resource Types", "include")
            return "include", selected
        elif choice == "2":
            selected = self.get_user_selection(self.resource_types, "Available Resource Types", "exclude")
            return "exclude", selected
        else:
            return "all", []
            
    def select_accounts(self, accounts):
        """Let user select which accounts to run cloudnuke on"""
        account_list = list(accounts.keys())
        self.display_options(account_list, "Available AWS Accounts")
        
        selection = input("\nSelect accounts to run cloudnuke on (comma-separated, range with -, or 'all'): ").strip()
        
        if selection.lower() == 'all' or selection == str(len(account_list) + 1):
            return account_list
        
        # Handle the selection directly instead of calling get_user_selection
        selected = []
        parts = selection.split(',')
        
        for part in parts:
            part = part.strip()
            if '-' in part and not part.startswith('-'):
                try:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        if 1 <= i <= len(account_list):
                            selected.append(account_list[i-1])
                except ValueError:
                    self.logger.warning(f"Invalid range: {part}")
            else:
                try:
                    num = int(part)
                    if 1 <= num <= len(account_list):
                        selected.append(account_list[num-1])
                except ValueError:
                    self.logger.warning(f"Invalid number: {part}")
                    
        return list(set(selected))
        
    def build_cloudnuke_command(self, profile, region_mode, regions, resource_mode, resources):
        """Build the cloudnuke command based on user selections"""
        cmd = [self.cloudnuke_exe, "aws"]
        
        if region_mode == "include" and regions:
            for region in regions:
                cmd.extend(["--region", region])
        elif region_mode == "exclude" and regions:
            for region in regions:
                cmd.extend(["--exclude-region", region])
        
        if resource_mode == "include" and resources:
            for resource in resources:
                cmd.extend(["--resource-type", resource])
        elif resource_mode == "exclude" and resources:
            for resource in resources:
                cmd.extend(["--exclude-resource-type", resource])
        
        return cmd

    def execute_cloudnuke(self, profile, command, account_info, auto_confirm_enabled, auto_confirm_value):
        """Execute cloudnuke command with improved auto-confirmation"""
        env = os.environ.copy()
        env["AWS_PROFILE"] = profile
        
        cmd_string = f"AWS_PROFILE={profile} {' '.join(command)}"
        self.logger.info(f"Executing: {cmd_string}")
        
        print(f"\n{'='*80}")
        print(f"{Symbols.TARGET} EXECUTING CLOUDNUKE")
        print(f"{'='*80}")
        print(f"📍 Profile: {profile}")
        print(f"🆔 Account ID: {account_info['account_id']}")
        print(f"📧 Email: {account_info['email']}")
        print(f"💻 Command: {cmd_string}")
        print(f"🤖 Auto-confirmation: {'Enabled' if auto_confirm_enabled else 'Disabled'}")
        if auto_confirm_enabled:
            print(f"🤖 Confirmation value: '{auto_confirm_value}'")
        print(f"{'='*80}")
        
        confirm = input("\n[WARN]  Do you want to proceed with this account? (yes/no): ").strip().lower()
        if confirm != 'yes':
            self.logger.info(f"Skipped execution for profile {profile}")
            return False
            
        try:
            start_time = datetime.now(datetime.UTC)
            print(f"\n{Symbols.START} Starting execution at {start_time.strftime('%H:%M:%S')} UTC...")
            
            if auto_confirm_enabled:
                return self._execute_with_auto_confirm(command, env, auto_confirm_value, profile, start_time)
            else:
                return self._execute_manual(command, env, profile, start_time)
                
        except Exception as e:
            self.logger.error(f"Failed to execute cloudnuke: {e}")
            print(f"\n{Symbols.ERROR} Error: {e}")
            return False
        
    def _execute_with_auto_confirm_simple(self, command, env, auto_confirm_value, profile, start_time):
        """Execute with auto-confirmation - simplified approach"""
        print(f"🤖 Auto-confirmation enabled. Will send '{auto_confirm_value}' when prompted...")
        
        process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding='utf-8',
            errors='replace',
            universal_newlines=True
        )
        
        confirmation_sent = False
        
        try:
            # Read output line by line
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                    
                # Print the line
                print(line, end='')
                self.logger.info(f"CloudNuke Output: {line.strip()}")
                
                # Check for the exact prompt pattern we see in the logs
                if not confirmation_sent and ("Enter 'nuke' to confirm" in line or 
                                            "Are you sure you want to nuke all listed resources" in line):
                    print(f"\n🤖 Confirmation prompt detected in line: {line.strip()}")
                    print(f"🤖 Sending '{auto_confirm_value}'...")
                    
                    # Send the confirmation
                    process.stdin.write(f'{auto_confirm_value}\n')
                    process.stdin.flush()
                    confirmation_sent = True
                    print(f"{Symbols.OK} Auto-confirmation sent!")
                    
                    # Continue reading remaining output
                    continue
            
            # Wait for process to complete
            returncode = process.wait()
            
        except Exception as e:
            self.logger.error(f"Error in auto-confirmation: {e}")
            returncode = 1
        
        end_time = datetime.now(datetime.UTC)
        duration = end_time - start_time
        
        if returncode == 0:
            print(f"\n{Symbols.OK} Successfully completed cloudnuke for profile {profile}")
            print(f"{Symbols.TIMER}  Duration: {duration}")
            print(f"🕒 Completed at: {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            self.logger.info(f"Successfully completed cloudnuke for profile {profile} in {duration}")
            return True
        else:
            print(f"\n{Symbols.ERROR} Cloudnuke failed for profile {profile} with return code: {returncode}")
            self.logger.error(f"Cloudnuke failed for profile {profile} with return code: {returncode}")
            return False

    def _execute_with_auto_confirm(self, command, env, auto_confirm_value, profile, start_time):
        """Execute with auto-confirmation - fixed logic"""
        print(f"🤖 Auto-confirmation enabled. Will send '{auto_confirm_value}' when prompted...")
        
        process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding='utf-8',
            errors='replace',
            bufsize=0,  # Unbuffered
            universal_newlines=True
        )
        
        output_buffer = []
        confirmation_sent = False
        prompt_detected = False
        
        # Enhanced patterns that match the actual CloudNuke output
        confirmation_patterns = [
            r"Enter 'nuke' to confirm",
            r"Enter \*nuke\*",
            r"type.*nuke.*to proceed",
            r"please confirm.*nuke",
            r"to continue.*nuke",
            r".*nuke.*to delete",
            r"Are you sure you want to nuke",
            r"Enter 'nuke' to confirm \(or exit with \^C\)"
        ]
        
        def read_output():
            nonlocal confirmation_sent, prompt_detected
            try:
                while True:
                    char = process.stdout.read(1)
                    if not char:
                        break
                    
                    output_buffer.append(char)
                    
                    # Print character immediately
                    print(char, end='', flush=True)
                    
                    # Check for prompt patterns in the accumulated buffer
                    current_buffer = ''.join(output_buffer)
                    
                    # Check if we see the confirmation prompt
                    if not confirmation_sent and not prompt_detected:
                        for pattern in confirmation_patterns:
                            if re.search(pattern, current_buffer, re.IGNORECASE):
                                prompt_detected = True
                                print(f"\n🤖 Confirmation prompt detected!")
                                print(f"🤖 Sending '{auto_confirm_value}'...")
                                
                                # Small delay to ensure CloudNuke is ready for input
                                time.sleep(1)
                                
                                # Send confirmation
                                process.stdin.write(f'{auto_confirm_value}\n')
                                process.stdin.flush()
                                confirmation_sent = True
                                print(f"{Symbols.OK} Auto-confirmation sent!")
                                break
                    
                    # Clear buffer when it gets too long or on newline
                    if char == '\n' or len(output_buffer) > 500:
                        line = ''.join(output_buffer).strip()
                        if line:
                            self.logger.info(f"CloudNuke Output: {line}")
                        output_buffer.clear()
                        
            except Exception as e:
                self.logger.error(f"Error reading output: {e}")
        
        # Start output reader thread
        output_thread = threading.Thread(target=read_output)
        output_thread.daemon = True
        output_thread.start()
        
        # Wait for process to complete with enhanced timeout handling
        max_wait_time = 1800  # 30 minutes maximum
        start_wait = time.time()
        last_check_time = time.time()
        
        while process.poll() is None:
            current_time = time.time()
            
            # Check for timeout
            if current_time - start_wait > max_wait_time:
                print(f"\n{Symbols.TIMER} Process timeout after {max_wait_time} seconds")
                process.terminate()
                break
            
            # Force send confirmation if prompt detected but not sent after 10 seconds
            if prompt_detected and not confirmation_sent and (current_time - last_check_time > 10):
                print(f"\n🤖 Force sending confirmation after 10 seconds...")
                try:
                    process.stdin.write(f'{auto_confirm_value}\n')
                    process.stdin.flush()
                    confirmation_sent = True
                    print(f"{Symbols.OK} Force auto-confirmation sent!")
                except Exception as e:
                    self.logger.error(f"Error force sending confirmation: {e}")
            
            # If no prompt detected after 60 seconds but process is running, force send
            if not prompt_detected and not confirmation_sent and (current_time - start_wait > 60):
                # Check if the current buffer contains any prompt-like text
                current_output = ''.join(output_buffer)
                if any(keyword in current_output.lower() for keyword in ['nuke', 'confirm', 'sure', 'delete']):
                    print(f"\n🤖 Detected possible prompt, force sending confirmation...")
                    try:
                        process.stdin.write(f'{auto_confirm_value}\n')
                        process.stdin.flush()
                        confirmation_sent = True
                        prompt_detected = True
                        print(f"{Symbols.OK} Force auto-confirmation sent!")
                    except Exception as e:
                        self.logger.error(f"Error force sending confirmation: {e}")
            
            time.sleep(0.5)  # Check more frequently
        
        # Wait for output thread to finish
        output_thread.join(timeout=5)
        
        # Get any remaining output
        try:
            remaining_output, _ = process.communicate(timeout=5)
            if remaining_output:
                print(remaining_output, end='')
                self.logger.info(f"Remaining output: {remaining_output}")
        except:
            pass
        
        returncode = process.returncode
        end_time = datetime.now()
        duration = end_time - start_time
        
        if returncode == 0:
            print(f"\n{Symbols.OK} Successfully completed cloudnuke for profile {profile}")
            print(f"{Symbols.TIMER}  Duration: {duration}")
            print(f"🕒 Completed at: {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            self.logger.info(f"Successfully completed cloudnuke for profile {profile} in {duration}")
            return True
        else:
            print(f"\n{Symbols.ERROR} Cloudnuke failed for profile {profile} with return code: {returncode}")
            self.logger.error(f"Cloudnuke failed for profile {profile} with return code: {returncode}")
            return False
        
    def _execute_manual(self, command, env, profile, start_time):
        """Execute in manual mode"""
        print("[LOG] Manual confirmation mode - please respond to prompts as they appear...")
        
        process = subprocess.Popen(
            command,
            env=env,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        
        returncode = process.wait()
        end_time = datetime.now(datetime.UTC)
        duration = end_time - start_time
        
        if returncode == 0:
            print(f"\n{Symbols.OK} Successfully completed cloudnuke for profile {profile}")
            print(f"{Symbols.TIMER}  Duration: {duration}")
            self.logger.info(f"Successfully completed cloudnuke for profile {profile} in {duration}")
            return True
        else:
            print(f"\n{Symbols.ERROR} Cloudnuke failed for profile {profile} with return code: {returncode}")
            self.logger.error(f"Cloudnuke failed for profile {profile} with return code: {returncode}")
            return False
    
    def get_auto_confirmation_settings(self):
        """Get auto-confirmation settings from user"""
        print(f"\n{'='*80}")
        print("🤖 AUTO-CONFIRMATION SETTINGS")
        print(f"{'='*80}")
        
        enable_auto = input("Enable auto-confirmation for resource deletion? (yes/no): ").strip().lower()
        
        if enable_auto == 'yes':
            print("\nCloudnuke will automatically send 'nuke' when prompted after resource scanning.")
            print("This will skip manual confirmation and proceed with deletion.")
            
            custom_value = input("Use custom confirmation value? (press Enter for 'nuke', or type custom value): ").strip()
            confirm_value = custom_value if custom_value else "nuke"
                
            print(f"\n{Symbols.OK} Auto-confirmation enabled with value: '{confirm_value}'")
            return True, confirm_value
        else:
            print("\n[OK] Manual confirmation mode - you'll need to confirm deletions manually")
            return False, None

    def delete_aws_profiles(self, profiles):
        """Delete AWS profiles"""
        for profile in profiles:
            try:
                # Get the AWS config and credentials file paths
                aws_dir = Path.home() / '.aws'
                config_file = aws_dir / 'config'
                credentials_file = aws_dir / 'credentials'
                
                # Remove from config file
                if config_file.exists():
                    subprocess.run([
                        "aws", "configure", "--profile", profile, "set", "aws_access_key_id", ""
                    ], capture_output=True)
                
                # Remove from credentials file  
                if credentials_file.exists():
                    subprocess.run([
                        "aws", "configure", "--profile", profile, "set", "aws_secret_access_key", ""
                    ], capture_output=True)
                    
                self.logger.info(f"Deleted profile: {profile}")
                
            except Exception as e:
                self.logger.error(f"Failed to delete profile {profile}: {e}")

    def create_directory_structure(self):
        """Create the aws/nuke directory structure if it doesn't exist"""
        base_path = Path("aws/nuke")
        directories = [
            base_path / "logs" / datetime.now().strftime("%Y-%m-%d"),
            base_path / "reports" / "json",
            base_path / "reports" / "html", 
            base_path / "reports" / "csv",
            base_path / "ui" / "assets" / "css",
            base_path / "ui" / "assets" / "js",
            base_path / "ui" / "assets" / "images",
            base_path / "configs" / "saved_configs"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            
        return base_path

    def setup_enhanced_logging(self):
        """Setup enhanced logging with organized file structure"""
        # Create directory structure first
        self.base_path = self.create_directory_structure()
        
        # Setup log paths
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H%M%S")
        
        log_dir = self.base_path / "logs" / today
        execution_log = log_dir / f"execution_{timestamp}.log"
        summary_log = log_dir / f"summary_{timestamp}.log"
        
        # Clear any existing handlers
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        
        # Setup multiple loggers
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(execution_log, encoding='utf-8'),
                logging.FileHandler(summary_log, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.execution_log_path = execution_log
        self.summary_log_path = summary_log
        
        # Store execution metadata
        self.execution_metadata = {
            "execution_id": f"{today}_{timestamp}",
            "start_time": datetime.now(datetime.UTC).isoformat(),
            "user": "varadharajaan",
            "execution_log": str(execution_log),
            "summary_log": str(summary_log),
            "accounts_processed": [],
            "results": {}
        }
        
        self.logger.info(f"Enhanced logging setup complete")
        self.logger.info(f"Execution Log: {execution_log}")
        self.logger.info(f"Summary Log: {summary_log}")

    def track_execution_progress(self, account, status, details=None):
        """Track execution progress for reporting"""
        if not hasattr(self, 'execution_data'):
            self.execution_data = {
                "accounts": {},
                "overall_stats": {
                    "total_accounts": 0,
                    "successful": 0,
                    "failed": 0,
                    "start_time": None,
                    "end_time": None
                }
            }
        
        if account not in self.execution_data["accounts"]:
            self.execution_data["accounts"][account] = {
                "start_time": datetime.now(datetime.UTC).isoformat(),
                "status": "in_progress",
                "resources_deleted": [],
                "errors": [],
                "duration": None
            }
        
        # Update account data
        account_data = self.execution_data["accounts"][account]
        account_data["status"] = status
        
        if details:
            if "error" in details:
                account_data["errors"].append({
                    "timestamp": datetime.now(datetime.UTC).isoformat(),
                    "error": details["error"]
                })
            if "resources" in details:
                account_data["resources_deleted"].extend(details["resources"])
            if "duration" in details:
                account_data["duration"] = str(details["duration"])
                account_data["end_time"] = datetime.now(datetime.UTC).isoformat()
        
        self.logger.info(f"Progress tracked for {account}: {status}")

    def generate_json_report(self):
        """Generate detailed JSON report"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = self.base_path / "reports" / "json" / f"report_{timestamp}.json"
        
        # Compile comprehensive report data
        report_data = {
            "execution_metadata": self.execution_metadata,
            "execution_summary": {
                "total_accounts": len(self.execution_data["accounts"]) if hasattr(self, 'execution_data') else 0,
                "successful_accounts": sum(1 for acc in self.execution_data["accounts"].values() if acc["status"] == "success") if hasattr(self, 'execution_data') else 0,
                "failed_accounts": sum(1 for acc in self.execution_data["accounts"].values() if acc["status"] == "failed") if hasattr(self, 'execution_data') else 0,
                "total_duration": str(datetime.now(datetime.UTC) - datetime.fromisoformat(self.execution_metadata["start_time"])),
                "end_time": datetime.now(datetime.UTC).isoformat()
            },
            "account_details": self.execution_data["accounts"] if hasattr(self, 'execution_data') else {},
            "configuration": {
                "cloudnuke_executable": self.cloudnuke_exe,
                "config_file": self.config_file,
                "regions_used": getattr(self, 'selected_regions', []),
                "resources_targeted": getattr(self, 'selected_resources', [])
            },
            "system_info": {
                "python_version": sys.version,
                "platform": os.name,
                "working_directory": str(Path.cwd())
            }
        }
        
        # Write JSON report
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"JSON report generated: {report_path}")
        return report_path

    def generate_html_report(self):
        """Generate HTML report with styling"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = self.base_path / "reports" / "html" / f"report_{timestamp}.html"
        
        # Get summary data
        total_accounts = len(self.execution_data["accounts"]) if hasattr(self, 'execution_data') else 0
        successful = sum(1 for acc in self.execution_data["accounts"].values() if acc["status"] == "success") if hasattr(self, 'execution_data') else 0
        failed = total_accounts - successful
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>CloudNuke Execution Report - {timestamp}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 20px; margin-bottom: 30px; }}
                .summary-cards {{ display: flex; justify-content: space-around; margin: 20px 0; flex-wrap: wrap; }}
                .card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; min-width: 200px; margin: 10px; }}
                .card.success {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); }}
                .card.failed {{ background: linear-gradient(135deg, #f44336 0%, #da190b 100%); }}
                .card h3 {{ margin: 0; font-size: 2em; }}
                .card p {{ margin: 5px 0 0 0; }}
                .section {{ margin: 30px 0; }}
                .section h2 {{ color: #333; border-bottom: 1px solid #ddd; padding-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f8f9fa; font-weight: bold; }}
                .status-success {{ color: #4CAF50; font-weight: bold; }}
                .status-failed {{ color: #f44336; font-weight: bold; }}
                .metadata {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .timestamp {{ color: #666; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="headerf">
                    <h1>{Symbols.START} CloudNuke Execution Report</h1>
                    <p class="timestamp">Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                    <p class="timestamp">Execution ID: {self.execution_metadata['execution_id']}</p>
                    <p class="timestamp">User: varadharajaan</p>
                </div>
                
                <div class="summary-cards">
                    <div class="card">
                        <h3>{total_accounts}</h3>
                        <p>Total Accounts</p>
                    </div>
                    <div class="card success">
                        <h3>{successful}</h3>
                        <p>Successful</p>
                    </div>
                    <div class="card failed">
                        <h3>{failed}</h3>
                        <p>Failed</p>
                    </div>
                </div>
                
                <div class="section">
                    <h2>[LIST] Execution Details</h2>
                    <div class="metadata">
                        <p><strong>Start Time:</strong> {self.execution_metadata['start_time']}</p>
                        <p><strong>End Time:</strong> {datetime.now(datetime.UTC).isoformat()}</p>
                        <p><strong>CloudNuke Executable:</strong> {self.cloudnuke_exe}</p>
                        <p><strong>Config File:</strong> {self.config_file}</p>
                        <p><strong>Execution Log:</strong> {self.execution_log_path}</p>
                        <p><strong>Summary Log:</strong> {self.summary_log_path}</p>
                    </div>
                </div>
                
                <div class="section">
                    <h2>[STATS] Account Results</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Account</th>
                                <th>Status</th>
                                <th>Start Time</th>
                                <th>Duration</th>
                                <th>Errors</th>
                            </tr>
                        </thead>
                        <tbody>
        """
        
        # Add account rows
        if hasattr(self, 'execution_data'):
            for account, data in self.execution_data["accounts"].items():
                status_class = "status-success" if data["status"] == "success" else "status-failed"
                error_count = len(data.get("errors", []))
                html_content += f"""
                            <tr>
                                <td>{account}</td>
                                <td><span class="{status_class}">{data["status"].upper()}</span></td>
                                <td>{data.get("start_time", "N/A")}</td>
                                <td>{data.get("duration", "N/A")}</td>
                                <td>{error_count}</td>
                            </tr>
                """
        
        html_content += """
                        </tbody>
                    </table>
                </div>
                
                <div class="sectionf">
                    <h2>{Symbols.INFO} System Information</h2>
                    <div class="metadata">
                        <p><strong>Python Version:</strong> """ + sys.version + """</p>
                        <p><strong>Platform:</strong> """ + os.name + """</p>
                        <p><strong>Working Directory:</strong> """ + str(Path.cwd()) + """</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Write HTML report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        self.logger.info(f"HTML report generated: {report_path}")
        return report_path

    def generate_csv_report(self):
        """Generate CSV report for data analysis"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = self.base_path / "reports" / "csv" / f"results_{timestamp}.csv"
        
        import csv
        
        # Prepare CSV data
        csv_data = []
        if hasattr(self, 'execution_data'):
            for account, data in self.execution_data["accounts"].items():
                csv_data.append({
                    "Execution_ID": self.execution_metadata['execution_id'],
                    "Account": account,
                    "Status": data["status"],
                    "Start_Time": data.get("start_time", ""),
                    "End_Time": data.get("end_time", ""),
                    "Duration": data.get("duration", ""),
                    "Error_Count": len(data.get("errors", [])),
                    "Resources_Deleted": len(data.get("resources_deleted", [])),
                    "User": "varadharajaan",
                    "Execution_Date": datetime.now().strftime("%Y-%m-%d")
                })
        
        # Write CSV file
        if csv_data:
            with open(report_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = csv_data[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_data)
        
        self.logger.info(f"CSV report generated: {report_path}")
        return report_path

    def create_ui_dashboard(self):
        """Create interactive HTML dashboard"""
        dashboard_path = self.base_path / "ui" / "dashboard.html"
        
        # Get recent reports for dashboard
        reports_dir = self.base_path / "reports" / "json"
        recent_reports = []
        
        if reports_dir.exists():
            json_files = list(reports_dir.glob("*.json"))
            json_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            for json_file in json_files[:10]:  # Last 10 reports
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                        recent_reports.append({
                            "file": json_file.name,
                            "execution_id": data.get("execution_metadata", {}).get("execution_id", "Unknown"),
                            "total_accounts": data.get("execution_summary", {}).get("total_accounts", 0),
                            "successful": data.get("execution_summary", {}).get("successful_accounts", 0),
                            "failed": data.get("execution_summary", {}).get("failed_accounts", 0),
                            "timestamp": data.get("execution_metadata", {}).get("start_time", "")
                        })
                except:
                    continue
        
        dashboard_html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>CloudNuke Dashboard - varadharajaan</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 0; text-align: center; }}
                .container {{ max-width: 1400px; margin: 20px auto; padding: 0 20px; }}
                .dashboard-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }}
                .card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                .card h3 {{ color: #333; margin-bottom: 15px; border-bottom: 2px solid #007bff; padding-bottom: 5px; }}
                .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 15px; }}
                .stat-item {{ text-align: center; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
                .stat-number {{ font-size: 2em; font-weight: bold; color: #007bff; }}
                .stat-label {{ color: #666; font-size: 0.9em; }}
                .chart-container {{ height: 300px; position: relative; }}
                .recent-executions {{ max-height: 400px; overflow-y: auto; }}
                .execution-item {{ padding: 10px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }}
                .execution-item:hover {{ background: #f8f9fa; }}
                .status-badge {{ padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold; }}
                .status-success {{ background: #d4edda; color: #155724; }}
                .status-failed {{ background: #f8d7da; color: #721c24; }}
                .refresh-btn {{ background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }}
                .refresh-btn:hover {{ background: #0056b3; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>[START] CloudNuke Management Dashboard</h1>
                <p>User: varadharajaan | Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <button class="refresh-btn" onclick="location.reload()">[SCAN] Refresh Dashboard</button>
            </div>
            
            <div class="container">
                <div class="dashboard-grid">
                    <div class="card">
                        <h3>[STATS] Overall Statistics</h3>
                        <div class="stats-grid">
                            <div class="stat-item">
                                <div class="stat-number">{len(recent_reports)}</div>
                                <div class="stat-label">Total Executions</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-number">{sum(r['successful'] for r in recent_reports)}</div>
                                <div class="stat-label">Total Success</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-number">{sum(r['failed'] for r in recent_reports)}</div>
                                <div class="stat-label">Total Failed</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-number">{sum(r['total_accounts'] for r in recent_reports)}</div>
                                <div class="stat-label">Accounts Processed</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>[UP] Success Rate Chart</h3>
                        <div class="chart-container">
                            <canvas id="successChart"></canvas>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>[DATE] Recent Executions</h3>
                        <div class="recent-executions">
        """
        
        # Add recent executions
        for report in recent_reports:
            success_rate = (report['successful'] / report['total_accounts'] * 100) if report['total_accounts'] > 0 else 0
            status_class = "status-success" if success_rate == 100 else "status-failed"
            
            dashboard_html += f"""
                            <div class="execution-item">
                                <div>
                                    <strong>{report['execution_id']}</strong><br>
                                    <small>{report['timestamp']}</small>
                                </div>
                                <div>
                                    <span class="status-badge {status_class}">{success_rate:.1f}% Success</span><br>
                                    <small>{report['successful']}/{report['total_accounts']} accounts</small>
                                </div>
                            </div>
            """
        
        dashboard_html += f"""
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>🔗 Quick Links</h3>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <a href="reports/html/" style="padding: 10px; background: #e3f2fd; border-radius: 5px; text-decoration: none; color: #1976d2;">📄 HTML Reports</a>
                            <a href="reports/json/" style="padding: 10px; background: #f3e5f5; border-radius: 5px; text-decoration: none; color: #7b1fa2;f">{Symbols.LIST} JSON Reports</a>
                            <a href="reports/csv/" style="padding: 10px; background: #e8f5e8; border-radius: 5px; text-decoration: none; color: #388e3c;f">{Symbols.STATS} CSV Reports</a>
                            <a href="logs/" style="padding: 10px; background: #fff3e0; border-radius: 5px; text-decoration: none; color: #f57c00;">[LOG] Execution Logs</a>
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
                // Create success rate chart
                const ctx = document.getElementById('successChart').getContext('2d');
                const chartData = {json.dumps([{"execution": r['execution_id'][:10], "success": r['successful'], "failed": r['failed']} for r in recent_reports[-7:]])};
                
                new Chart(ctx, {{
                    type: 'bar',
                    data: {{
                        labels: chartData.map(d => d.execution),
                        datasets: [{{
                            label: 'Successful',
                            data: chartData.map(d => d.success),
                            backgroundColor: '#4CAF50'
                        }}, {{
                            label: 'Failed', 
                            data: chartData.map(d => d.failed),
                            backgroundColor: '#f44336'
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {{
                            y: {{
                                beginAtZero: true
                            }}
                        }}
                    }}
                }});
            </script>
        </body>
        </html>
        """
        
        # Write dashboard
        with open(dashboard_path, 'w', encoding='utf-8') as f:
            f.write(dashboard_html)
        
        self.logger.info(f"Dashboard created: {dashboard_path}")
        return dashboard_path

    def save_execution_config(self, config_name, region_mode, regions, resource_mode, resources, auto_confirm_enabled, auto_confirm_value):
        """Save execution configuration for reuse"""
        config_path = self.base_path / "configs" / "saved_configs" / f"{config_name}.json"
        
        config_data = {
            "name": config_name,
            "created_by": "varadharajaan",
            "created_at": datetime.now(datetime.UTC).isoformat(),
            "region_mode": region_mode,
            "regions": regions,
            "resource_mode": resource_mode,
            "resources": resources,
            "auto_confirm_enabled": auto_confirm_enabled,
            "auto_confirm_value": auto_confirm_value
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        
        self.logger.info(f"Execution configuration saved: {config_path}")
        return config_path

    def generate_all_reports(self):
        """Generate all types of reports"""
        self.logger.info("Generating comprehensive reports...")
        
        reports_generated = {}
        
        try:
            reports_generated['json'] = self.generate_json_report()
            reports_generated['html'] = self.generate_html_report() 
            reports_generated['csv'] = self.generate_csv_report()
            reports_generated['dashboard'] = self.create_ui_dashboard()
            
            print(f"\n{'='*80}")
            print("[STATS] REPORTS GENERATED")
            print(f"{'='*80}")
            print(f"📄 JSON Report: {reports_generated['json']}")
            print(f"🌐 HTML Report: {reports_generated['html']}")
            print(f"{Symbols.STATS} CSV Report: {reports_generated['csv']}")
            print(f"{Symbols.START} Dashboard: {reports_generated['dashboard']}")
            print(f"{'='*80}")
            
            self.logger.info("All reports generated successfully")
            
        except Exception as e:
            self.logger.error(f"Error generating reports: {e}")
            
        return reports_generated
            
    def run(self):
        """Main execution flow"""
        start_time = datetime.now(datetime.UTC)
        
        # Check if cloudnuke executable exists
        if not Path(self.cloudnuke_exe).exists():
            self.logger.error(f"Cloudnuke executable not found: {self.cloudnuke_exe}")
            sys.exit(1)
            
        # Load configuration
        config = self.load_config()
        accounts = config.get("accounts", {})
        
        if not accounts:
            self.logger.error("No accounts found in configuration")
            sys.exit(1)
            
        # Setup AWS profiles
        self.setup_aws_profiles(accounts)
        
        # Get auto-confirmation settings
        auto_confirm_enabled, auto_confirm_value = self.get_auto_confirmation_settings()
        
        # Select accounts to process
        selected_accounts = self.select_accounts(accounts)
        if not selected_accounts:
            self.logger.info("No accounts selected. Exiting.")
            return
            
        # Get region configuration
        region_mode, selected_regions = self.get_region_configuration()
        self.logger.info(f"Region mode: {region_mode}, Selected regions: {selected_regions}")
        
        # Get resource configuration
        resource_mode, selected_resources = self.get_resource_configuration()
        self.logger.info(f"Resource mode: {resource_mode}, Selected resources: {selected_resources}")
        
        # Build command
        base_command = self.build_cloudnuke_command(
            "", region_mode, selected_regions, resource_mode, selected_resources
        )
        
        # Pre-execution summary
        print(f"\n{'='*80}")
        print("[LIST] PRE-EXECUTION SUMMARY")
        print(f"{'='*80}")
        print(f"🏢 Selected accounts: {', '.join(selected_accounts)}")
        print(f"{Symbols.REGION} Region configuration: {region_mode}")
        if region_mode != "all":
            print(f"   Regions: {', '.join(selected_regions)}")
        print(f"🔧 Resource configuration: {resource_mode}")
        if resource_mode != "all":
            print(f"   Resources: {', '.join(selected_resources)}")
        print(f"🤖 Auto-confirmation: {'Enabled' if auto_confirm_enabled else 'Disabled'}")
        if auto_confirm_enabled:
            print(f"   Confirmation value: '{auto_confirm_value}'")
        print(f"{'='*80}\n")
        
        # Execute for each selected account
        successful_executions = 0
        failed_accounts = []
        
        for i, account in enumerate(selected_accounts, 1):
            print(f"\n{'='*80}")
            print(f"📌 Processing account {i}/{len(selected_accounts)}: {account}")
            print(f"{'='*80}")
            
            success = self.execute_cloudnuke(
                account, 
                base_command, 
                accounts[account], 
                auto_confirm_enabled, 
                auto_confirm_value
            )
            
            if success:
                successful_executions += 1
            else:
                failed_accounts.append(account)
                
            # Add a pause between accounts if not the last one
            if i < len(selected_accounts):
                print(f"\n⏸️  Pausing before next account...")
                time.sleep(3)
        
        end_time = datetime.now(datetime.UTC)
        duration = end_time - start_time
        
        # Final summary
        print(f"\n{'='*100}")
        print("[STATS] FINAL EXECUTION SUMMARY")
        print(f"{'='*100}")
        print(f"{Symbols.TIMER} Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{Symbols.TIMER} End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{Symbols.TIMER}  Total Duration: {duration}")
        print(f"👤 User: varadharajaan")
        print(f"{Symbols.FOLDER} Config File: {self.config_file}")
        print(f"🔧 Executable: {self.cloudnuke_exe}")
        print(f"🏢 Total accounts: {len(selected_accounts)}")
        print(f"{Symbols.OK} Successful executions: {successful_executions}")
        print(f"{Symbols.ERROR} Failed executions: {len(selected_accounts) - successful_executions}")
        
        if failed_accounts:
            print(f"\n{Symbols.ERROR} Failed accounts: {', '.join(failed_accounts)}")
            
        print(f"{'='*100}\n")
        
        # Ask user if they want to delete the profiles
        delete_confirm = input("\n[DELETE]  Do you want to delete the AWS profiles that were created? (yes/no): ").strip().lower()
        if delete_confirm == 'yes':
            self.delete_aws_profiles(selected_accounts)
            print(f"{Symbols.OK} AWS profiles have been deleted")
        else:
            print(f"{Symbols.INFO}  AWS profiles retained")
        
        self.logger.info("Cloudnuke execution completed for all selected accounts")

if __name__ == "__main__":
    manager = CloudNukeManager()
    manager.run()