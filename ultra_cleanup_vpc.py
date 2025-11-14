#!/usr/bin/env python3

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from root_iam_credential_manager import AWSCredentialManager, Colors


class UltraVPCCleanupManager:
    """
    Enhanced Ultra VPC Cleanup Manager - Complete Custom VPC Resource Coverage

    Handles ALL custom VPC resources while ensuring default VPC resources are completely ignored.
    Follows the same patterns as other ultra cleanup scripts with proper dependency management.
    """

    def __init__(self, config_file="aws_accounts_config.json"):
        self.config_file = config_file
        self.cred_manager = AWSCredentialManager()
        self.current_time = datetime.now()
        self.current_time_str = self.current_time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.user_regions = self._get_user_regions()

        # Operation mode
        self.dry_run = False
        self.max_retries = 3
        self.retry_delay = 30  # seconds

        # Initialize log file
        self.setup_detailed_logging()

        # Load configuration
        self.load_configuration()

        # VPC resource cleanup order (dependency-aware)
        self.cleanup_order = [
            "vpc_flow_logs",
            "transit_gateway_attachments",
            "vpn_gateways",
            "vpc_peering_connections",
            "network_interfaces",
            "nat_gateways",
            "vpc_endpoints",
            "elastic_ips",
            "security_group_rules",
            "security_groups",
            "route_table_routes",
            "route_tables",
            "network_acls",
            "subnets",
            "internet_gateways",
            "dhcp_options_sets",
            "customer_gateways",
        ]

        # Storage for cleanup results
        self.cleanup_results = {
            "accounts_processed": [],
            "regions_processed": [],
            "vpcs_analyzed": [],
            "resources_deleted": {
                "vpc_endpoints": [],
                "nat_gateways": [],
                "internet_gateways": [],
                "security_groups": [],
                "vpc_peering_connections": [],
                "route_tables": [],
                "network_acls": [],
                "elastic_ips": [],
                "vpc_flow_logs": [],
                "vpn_gateways": [],
                "transit_gateway_attachments": [],
                "network_interfaces": [],
                "subnets": [],
                "dhcp_options_sets": [],
                "customer_gateways": [],
            },
            "default_resources_skipped": [],
            "failed_deletions": [],
            "dependency_violations": [],
            "errors": [],
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/vpc/logs"
            os.makedirs(log_dir, exist_ok=True)

            self.log_filename = (
                f"{log_dir}/ultra_vpc_cleanup_{self.execution_timestamp}.log"
            )

            # Create logger for detailed operations
            self.logger = logging.getLogger("ultra_vpc_cleanup")
            self.logger.setLevel(logging.INFO)

            # Remove existing handlers to avoid duplicates
            for handler in self.logger.handlers[:]:
                self.logger.removeHandler(handler)

            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding="utf-8")
            file_handler.setLevel(logging.INFO)

            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # Formatter
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

            # Log initial information
            self.logger.info("=" * 100)
            self.logger.info("🚨 ENHANCED ULTRA VPC CLEANUP SESSION STARTED 🚨")
            self.logger.info("=" * 100)
            self.logger.info(f"Execution Time: {self.current_time_str}")
            self.logger.info(f"Executed By: {self.current_user}")
            self.logger.info(f"Config File: {self.config_file}")
            self.logger.info(f"Log File: {self.log_filename}")
            self.logger.info("=" * 100)

        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.logger = None

    def _get_user_regions(self) -> List[str]:
        """Get user regions from root accounts config."""
        try:
            config = self.cred_manager.load_root_accounts_config()
            if config:
                return config.get("user_settings", {}).get(
                    "user_regions",
                    ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ap-south-1"],
                )
        except Exception as e:
            self.print_colored(
                Colors.YELLOW, f"⚠️  Warning: Could not load user regions: {e}"
            )

        return ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ap-south-1"]

    def log_operation(self, level, message):
        """Simple logging operation"""
        if self.logger:
            if level.upper() == "INFO":
                self.logger.info(message)
            elif level.upper() == "WARNING":
                self.logger.warning(message)
            elif level.upper() == "ERROR":
                self.logger.error(message)
            elif level.upper() == "DEBUG":
                self.logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")

    def load_configuration(self):
        """Load AWS accounts configuration"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(
                    f"Configuration file '{self.config_file}' not found"
                )

            with open(self.config_file, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)

            self.log_operation(
                "INFO", f"✅ Configuration loaded from: {self.config_file}"
            )

            # Validate accounts
            if "accounts" not in self.config_data:
                raise ValueError("No 'accounts' section found in configuration")

            # Filter out incomplete accounts
            valid_accounts = {}
            for account_name, account_data in self.config_data["accounts"].items():
                if (
                    account_data.get("access_key")
                    and account_data.get("secret_key")
                    and account_data.get("account_id")
                    and not account_data.get("access_key").startswith("ADD_")
                ):
                    valid_accounts[account_name] = account_data
                else:
                    self.log_operation(
                        "WARNING", f"Skipping incomplete account: {account_name}"
                    )

            self.config_data["accounts"] = valid_accounts

            self.log_operation(
                "INFO", f"📊 Valid accounts loaded: {len(valid_accounts)}"
            )
            for account_name, account_data in valid_accounts.items():
                account_id = account_data.get("account_id", "Unknown")
                email = account_data.get("email", "Unknown")
                self.log_operation(
                    "INFO", f"   • {account_name}: {account_id} ({email})"
                )

            # Get user regions
            user_settings = self.config_data.get("user_settings", {})
            self.regions = user_settings.get(
                "user_regions", ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]
            )
            self.log_operation("INFO", f"🌍 Regions to process: {self.regions}")

        except FileNotFoundError as e:
            self.log_operation("ERROR", f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation("ERROR", f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation("ERROR", f"Error loading configuration: {e}")
            sys.exit(1)

    def create_ec2_client(self, access_key: str, secret_key: str, region: str):
        """Create EC2 client for the specified region"""
        try:
            return boto3.client(
                "ec2",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
        except Exception as e:
            self.log_operation(
                "ERROR", f"Failed to create EC2 client for {region}: {e}"
            )
            return None

    def is_default_vpc(self, vpc_info: Dict) -> bool:
        """Check if VPC is a default VPC"""
        return vpc_info.get("IsDefault", False)

    def is_default_security_group(self, sg_info: Dict) -> bool:
        """Check if security group is default"""
        return sg_info.get("GroupName") == "default"

    def is_main_route_table(self, rt_info: Dict) -> bool:
        """Check if route table is the main route table"""
        associations = rt_info.get("Associations", [])
        return any(assoc.get("Main", False) for assoc in associations)

    def is_default_network_acl(self, acl_info: Dict) -> bool:
        """Check if network ACL is default"""
        return acl_info.get("IsDefault", False)

    def is_default_dhcp_options(self, dhcp_info: Dict, vpc_info: Dict) -> bool:
        """Check if DHCP options set is default for the VPC"""
        # Default DHCP options typically have domain-name and domain-name-servers
        # and are associated with default VPCs
        if self.is_default_vpc(vpc_info):
            return True

        # Check if it's the standard default DHCP options
        dhcp_options = dhcp_info.get("DhcpConfigurations", [])
        has_domain_name = any(opt.get("Key") == "domain-name" for opt in dhcp_options)
        has_dns_servers = any(
            opt.get("Key") == "domain-name-servers" for opt in dhcp_options
        )

        return has_domain_name and has_dns_servers

    def get_all_vpcs_in_region(
        self, ec2_client, region: str, account_name: str
    ) -> List[Dict]:
        """Get all VPCs in the specified region"""
        try:
            self.log_operation("INFO", f"🔍 Scanning VPCs in {region} ({account_name})")

            response = ec2_client.describe_vpcs()
            vpcs = response.get("Vpcs", [])

            custom_vpcs = []
            default_vpcs = []

            for vpc in vpcs:
                if self.is_default_vpc(vpc):
                    default_vpcs.append(vpc)
                    self.cleanup_results["default_resources_skipped"].append(
                        {
                            "type": "VPC",
                            "id": vpc["VpcId"],
                            "reason": "Default VPC - protected from deletion",
                            "region": region,
                            "account": account_name,
                        }
                    )
                else:
                    custom_vpcs.append(vpc)

            self.log_operation(
                "INFO",
                f"📊 Found {len(custom_vpcs)} custom VPCs and {len(default_vpcs)} default VPCs in {region}",
            )

            return custom_vpcs

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting VPCs in {region} ({account_name}): {e}"
            )
            return []

    def get_vpc_flow_logs(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get VPC Flow Logs for custom VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning VPC Flow Logs in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_flow_logs(
                Filters=[{"Name": "resource-id", "Values": vpc_ids}]
            )

            flow_logs = response.get("FlowLogs", [])
            self.log_operation(
                "INFO", f"📊 Found {len(flow_logs)} VPC Flow Logs in {region}"
            )

            return flow_logs

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting VPC Flow Logs in {region} ({account_name}): {e}",
            )
            return []

    def get_vpc_endpoints(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get VPC Endpoints for custom VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning VPC Endpoints in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": vpc_ids}]
            )

            endpoints = response.get("VpcEndpoints", [])
            self.log_operation(
                "INFO", f"📊 Found {len(endpoints)} VPC Endpoints in {region}"
            )

            return endpoints

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting VPC Endpoints in {region} ({account_name}): {e}",
            )
            return []

    def get_nat_gateways(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get NAT Gateways for custom VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning NAT Gateways in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_nat_gateways(
                Filters=[{"Name": "vpc-id", "Values": vpc_ids}]
            )

            nat_gateways = response.get("NatGateways", [])
            # Only include available or pending NAT gateways
            active_nat_gateways = [
                ng for ng in nat_gateways if ng.get("State") in ["available", "pending"]
            ]

            self.log_operation(
                "INFO",
                f"📊 Found {len(active_nat_gateways)} active NAT Gateways in {region}",
            )

            return active_nat_gateways

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting NAT Gateways in {region} ({account_name}): {e}"
            )
            return []

    def get_internet_gateways(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get Internet Gateways for custom VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Internet Gateways in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            # Get all internet gateways and filter by VPC
            response = ec2_client.describe_internet_gateways()
            all_igws = response.get("InternetGateways", [])

            custom_igws = []
            for igw in all_igws:
                attachments = igw.get("Attachments", [])
                for attachment in attachments:
                    if attachment.get("VpcId") in vpc_ids:
                        custom_igws.append(igw)
                        break

            self.log_operation(
                "INFO", f"📊 Found {len(custom_igws)} Internet Gateways in {region}"
            )

            return custom_igws

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting Internet Gateways in {region} ({account_name}): {e}",
            )
            return []

    def get_security_groups(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get Security Groups for custom VPCs (excluding default)"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Security Groups in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_security_groups(
                Filters=[{"Name": "vpc-id", "Values": vpc_ids}]
            )

            all_sgs = response.get("SecurityGroups", [])
            custom_sgs = []
            default_sgs = []

            for sg in all_sgs:
                if self.is_default_security_group(sg):
                    default_sgs.append(sg)
                    self.cleanup_results["default_resources_skipped"].append(
                        {
                            "type": "SecurityGroup",
                            "id": sg["GroupId"],
                            "name": sg["GroupName"],
                            "reason": "Default security group - protected from deletion",
                            "region": region,
                            "account": account_name,
                        }
                    )
                else:
                    custom_sgs.append(sg)

            self.log_operation(
                "INFO",
                f"📊 Found {len(custom_sgs)} custom Security Groups and {len(default_sgs)} default SGs in {region}",
            )

            return custom_sgs

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting Security Groups in {region} ({account_name}): {e}",
            )
            return []

    def delete_vpc_flow_logs(
        self, ec2_client, flow_logs: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete VPC Flow Logs"""
        try:
            if not flow_logs:
                return True

            action_text = "Would delete" if self.dry_run else "Deleting"
            self.log_operation(
                "INFO",
                f"🗑️ {action_text} {len(flow_logs)} VPC Flow Logs in {region} ({account_name})",
            )

            for flow_log in flow_logs:
                flow_log_id = flow_log["FlowLogId"]
                try:
                    if self.dry_run:
                        self.log_operation(
                            "INFO",
                            f"🔍 [DRY RUN] Would delete VPC Flow Log: {flow_log_id}",
                        )
                    else:
                        ec2_client.delete_flow_logs(FlowLogIds=[flow_log_id])
                        self.log_operation(
                            "INFO", f"✅ Deleted VPC Flow Log: {flow_log_id}"
                        )

                    self.cleanup_results["resources_deleted"]["vpc_flow_logs"].append(
                        {
                            "id": flow_log_id,
                            "region": region,
                            "account": account_name,
                            "dry_run": self.dry_run,
                        }
                    )
                except ClientError as e:
                    if "InvalidFlowLogId.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ VPC Flow Log {flow_log_id} already deleted"
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete VPC Flow Log {flow_log_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "VPC Flow Log",
                                "id": flow_log_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        if not self.dry_run:
                            return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting VPC Flow Logs in {region} ({account_name}): {e}",
            )
            return False

    def delete_vpc_endpoints(
        self, ec2_client, endpoints: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete VPC Endpoints"""
        try:
            if not endpoints:
                return True

            action_text = "Would delete" if self.dry_run else "Deleting"
            self.log_operation(
                "INFO",
                f"🗑️ {action_text} {len(endpoints)} VPC Endpoints in {region} ({account_name})",
            )

            for endpoint in endpoints:
                endpoint_id = endpoint["VpcEndpointId"]
                endpoint_type = endpoint.get("VpcEndpointType", "Unknown")

                try:
                    if self.dry_run:
                        self.log_operation(
                            "INFO",
                            f"🔍 [DRY RUN] Would delete VPC Endpoint ({endpoint_type}): {endpoint_id}",
                        )
                    else:
                        ec2_client.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
                        self.log_operation(
                            "INFO",
                            f"✅ Deleted VPC Endpoint ({endpoint_type}): {endpoint_id}",
                        )

                    self.cleanup_results["resources_deleted"]["vpc_endpoints"].append(
                        {
                            "id": endpoint_id,
                            "type": endpoint_type,
                            "region": region,
                            "account": account_name,
                            "dry_run": self.dry_run,
                        }
                    )
                except ClientError as e:
                    if "InvalidVpcEndpointId.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ VPC Endpoint {endpoint_id} already deleted"
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete VPC Endpoint {endpoint_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "VPC Endpoint",
                                "id": endpoint_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        if not self.dry_run:
                            return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting VPC Endpoints in {region} ({account_name}): {e}",
            )
            return False

    def delete_nat_gateways_with_wait(
        self, ec2_client, nat_gateways: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete NAT Gateways and wait for completion"""
        try:
            if not nat_gateways:
                return True

            action_text = "Would delete" if self.dry_run else "Deleting"
            self.log_operation(
                "INFO",
                f"🗑️ {action_text} {len(nat_gateways)} NAT Gateways in {region} ({account_name})",
            )

            # Start deletion
            nat_gateway_ids = []
            for nat_gw in nat_gateways:
                nat_gw_id = nat_gw["NatGatewayId"]
                try:
                    if self.dry_run:
                        self.log_operation(
                            "INFO",
                            f"🔍 [DRY RUN] Would delete NAT Gateway: {nat_gw_id}",
                        )
                        nat_gateway_ids.append(nat_gw_id)
                    else:
                        ec2_client.delete_nat_gateway(NatGatewayId=nat_gw_id)
                        nat_gateway_ids.append(nat_gw_id)
                        self.log_operation(
                            "INFO", f"🗑️ Started deletion of NAT Gateway: {nat_gw_id}"
                        )
                except ClientError as e:
                    if "InvalidNatGatewayID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ NAT Gateway {nat_gw_id} already deleted"
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete NAT Gateway {nat_gw_id}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "NAT Gateway",
                                "id": nat_gw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        if not self.dry_run:
                            return False

            # Wait for deletion to complete (only if not dry run)
            if nat_gateway_ids and not self.dry_run:
                self.log_operation(
                    "INFO", f"⏳ Waiting for NAT Gateway deletion to complete..."
                )
                max_wait_time = 300  # 5 minutes
                wait_time = 0
                check_interval = 30

                while wait_time < max_wait_time:
                    try:
                        response = ec2_client.describe_nat_gateways(
                            NatGatewayIds=nat_gateway_ids
                        )
                        remaining_gateways = []

                        for nat_gw in response.get("NatGateways", []):
                            if nat_gw.get("State") not in ["deleted", "deleting"]:
                                remaining_gateways.append(nat_gw["NatGatewayId"])

                        if not remaining_gateways:
                            self.log_operation(
                                "INFO", f"✅ All NAT Gateways deleted successfully"
                            )
                            break

                        self.log_operation(
                            "INFO",
                            f"⏳ Still waiting for {len(remaining_gateways)} NAT Gateways to delete...",
                        )
                        time.sleep(check_interval)
                        wait_time += check_interval

                    except ClientError as e:
                        if "InvalidNatGatewayID.NotFound" in str(e):
                            # All deleted
                            self.log_operation(
                                "INFO", f"✅ All NAT Gateways deleted successfully"
                            )
                            break
                        else:
                            self.log_operation(
                                "ERROR", f"Error checking NAT Gateway status: {e}"
                            )
                            return False

                if wait_time >= max_wait_time:
                    self.log_operation(
                        "WARNING",
                        f"⚠️ NAT Gateway deletion timed out after {max_wait_time} seconds",
                    )

            # Record the deletions/analysis
            for nat_gw_id in nat_gateway_ids:
                self.cleanup_results["resources_deleted"]["nat_gateways"].append(
                    {
                        "id": nat_gw_id,
                        "region": region,
                        "account": account_name,
                        "dry_run": self.dry_run,
                    }
                )

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting NAT Gateways in {region} ({account_name}): {e}",
            )
            return False

    def get_route_tables(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get Route Tables for custom VPCs (excluding main route tables)"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Route Tables in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_route_tables(
                Filters=[{"Name": "vpc-id", "Values": vpc_ids}]
            )

            all_rts = response.get("RouteTables", [])
            custom_rts = []
            main_rts = []

            for rt in all_rts:
                if self.is_main_route_table(rt):
                    main_rts.append(rt)
                    self.cleanup_results["default_resources_skipped"].append(
                        {
                            "type": "RouteTable",
                            "id": rt["RouteTableId"],
                            "reason": "Main route table - protected from deletion",
                            "region": region,
                            "account": account_name,
                        }
                    )
                else:
                    custom_rts.append(rt)

            self.log_operation(
                "INFO",
                f"📊 Found {len(custom_rts)} custom Route Tables and {len(main_rts)} main RTs in {region}",
            )

            return custom_rts

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting Route Tables in {region} ({account_name}): {e}"
            )
            return []

    def get_network_acls(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get Network ACLs for custom VPCs (excluding default)"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Network ACLs in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_network_acls(
                Filters=[{"Name": "vpc-id", "Values": vpc_ids}]
            )

            all_acls = response.get("NetworkAcls", [])
            custom_acls = []
            default_acls = []

            for acl in all_acls:
                if self.is_default_network_acl(acl):
                    default_acls.append(acl)
                    self.cleanup_results["default_resources_skipped"].append(
                        {
                            "type": "NetworkAcl",
                            "id": acl["NetworkAclId"],
                            "reason": "Default network ACL - protected from deletion",
                            "region": region,
                            "account": account_name,
                        }
                    )
                else:
                    custom_acls.append(acl)

            self.log_operation(
                "INFO",
                f"📊 Found {len(custom_acls)} custom Network ACLs and {len(default_acls)} default ACLs in {region}",
            )

            return custom_acls

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting Network ACLs in {region} ({account_name}): {e}"
            )
            return []

    def get_elastic_ips(self, ec2_client, region: str, account_name: str) -> List[Dict]:
        """Get VPC-associated Elastic IPs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning VPC Elastic IPs in {region} ({account_name})"
            )

            response = ec2_client.describe_addresses(
                Filters=[{"Name": "domain", "Values": ["vpc"]}]
            )

            addresses = response.get("Addresses", [])
            # Only include unassociated EIPs to avoid disrupting running instances
            unassociated_eips = [
                addr for addr in addresses if "AssociationId" not in addr
            ]

            self.log_operation(
                "INFO",
                f"📊 Found {len(unassociated_eips)} unassociated VPC Elastic IPs in {region}",
            )

            return unassociated_eips

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting Elastic IPs in {region} ({account_name}): {e}"
            )
            return []

    def get_vpn_gateways(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get VPN Gateways attached to custom VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning VPN Gateways in {region} ({account_name})"
            )

            response = ec2_client.describe_vpn_gateways()
            all_vgws = response.get("VpnGateways", [])

            vpc_vgws = []
            for vgw in all_vgws:
                if vgw.get("State") not in ["available", "pending"]:
                    continue

                attachments = vgw.get("VpcAttachments", [])
                for attachment in attachments:
                    if (
                        attachment.get("VpcId") in vpc_ids
                        and attachment.get("State") == "attached"
                    ):
                        vpc_vgws.append(vgw)
                        break

            self.log_operation(
                "INFO", f"📊 Found {len(vpc_vgws)} VPN Gateways in {region}"
            )

            return vpc_vgws

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting VPN Gateways in {region} ({account_name}): {e}"
            )
            return []

    def get_transit_gateway_attachments(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get Transit Gateway Attachments for custom VPCs"""
        try:
            self.log_operation(
                "INFO",
                f"🔍 Scanning Transit Gateway Attachments in {region} ({account_name})",
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_transit_gateway_attachments(
                Filters=[
                    {"Name": "resource-type", "Values": ["vpc"]},
                    {"Name": "resource-id", "Values": vpc_ids},
                ]
            )

            attachments = response.get("TransitGatewayAttachments", [])
            # Only include available attachments
            active_attachments = [
                att
                for att in attachments
                if att.get("State") in ["available", "pending"]
            ]

            self.log_operation(
                "INFO",
                f"📊 Found {len(active_attachments)} Transit Gateway Attachments in {region}",
            )

            return active_attachments

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting Transit Gateway Attachments in {region} ({account_name}): {e}",
            )
            return []

    def get_network_interfaces(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get unattached Network Interfaces in custom VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Network Interfaces in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_network_interfaces(
                Filters=[
                    {"Name": "vpc-id", "Values": vpc_ids},
                    {
                        "Name": "status",
                        "Values": ["available"],
                    },  # Only unattached interfaces
                ]
            )

            interfaces = response.get("NetworkInterfaces", [])
            self.log_operation(
                "INFO",
                f"📊 Found {len(interfaces)} unattached Network Interfaces in {region}",
            )

            return interfaces

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting Network Interfaces in {region} ({account_name}): {e}",
            )
            return []

    def get_subnets(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get all custom subnets in VPCs"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Subnets in {region} ({account_name})"
            )

            if not vpc_ids:
                return []

            response = ec2_client.describe_subnets(
                Filters=[{"Name": "vpc-id", "Values": vpc_ids}]
            )

            subnets = response.get("Subnets", [])
            self.log_operation("INFO", f"📊 Found {len(subnets)} Subnets in {region}")

            return subnets

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting Subnets in {region} ({account_name}): {e}"
            )
            return []

    def get_dhcp_options_sets(
        self, ec2_client, custom_vpcs: List[Dict], region: str, account_name: str
    ) -> List[Dict]:
        """Get custom DHCP Options Sets"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning DHCP Options Sets in {region} ({account_name})"
            )

            if not custom_vpcs:
                return []

            response = ec2_client.describe_dhcp_options()
            all_dhcp = response.get("DhcpOptions", [])

            # Get DHCP options associated with custom VPCs
            vpc_dhcp_map = {vpc["DhcpOptionsId"]: vpc for vpc in custom_vpcs}
            custom_dhcp = []

            for dhcp in all_dhcp:
                dhcp_id = dhcp["DhcpOptionsId"]
                if dhcp_id in vpc_dhcp_map:
                    vpc_info = vpc_dhcp_map[dhcp_id]
                    if not self.is_default_dhcp_options(dhcp, vpc_info):
                        custom_dhcp.append(dhcp)
                    else:
                        self.cleanup_results["default_resources_skipped"].append(
                            {
                                "type": "DhcpOptions",
                                "id": dhcp_id,
                                "reason": "Default DHCP options - protected from deletion",
                                "region": region,
                                "account": account_name,
                            }
                        )

            self.log_operation(
                "INFO",
                f"📊 Found {len(custom_dhcp)} custom DHCP Options Sets in {region}",
            )

            return custom_dhcp

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting DHCP Options Sets in {region} ({account_name}): {e}",
            )
            return []

    def get_customer_gateways(
        self, ec2_client, region: str, account_name: str
    ) -> List[Dict]:
        """Get Customer Gateways (these are typically VPC-independent but included for completeness)"""
        try:
            self.log_operation(
                "INFO", f"🔍 Scanning Customer Gateways in {region} ({account_name})"
            )

            response = ec2_client.describe_customer_gateways()
            customer_gateways = response.get("CustomerGateways", [])

            # Only include available customer gateways
            available_cgws = [
                cgw for cgw in customer_gateways if cgw.get("State") == "available"
            ]

            self.log_operation(
                "INFO", f"📊 Found {len(available_cgws)} Customer Gateways in {region}"
            )

            return available_cgws

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting Customer Gateways in {region} ({account_name}): {e}",
            )
            return []

    def get_vpc_peering_connections(
        self, ec2_client, vpc_ids: List[str], region: str, account_name: str
    ) -> List[Dict]:
        """Get VPC Peering Connections for custom VPCs"""
        try:
            self.log_operation(
                "INFO",
                f"🔍 Scanning VPC Peering Connections in {region} ({account_name})",
            )

            if not vpc_ids:
                return []

            # Get peering connections where our VPCs are either requester or accepter
            response = ec2_client.describe_vpc_peering_connections()
            all_peering = response.get("VpcPeeringConnections", [])

            vpc_peering = []
            for peering in all_peering:
                if peering.get("Status", {}).get("Code") not in [
                    "active",
                    "pending-acceptance",
                ]:
                    continue

                requester_vpc = peering.get("RequesterVpcInfo", {}).get("VpcId")
                accepter_vpc = peering.get("AccepterVpcInfo", {}).get("VpcId")

                if requester_vpc in vpc_ids or accepter_vpc in vpc_ids:
                    vpc_peering.append(peering)

            self.log_operation(
                "INFO",
                f"📊 Found {len(vpc_peering)} VPC Peering Connections in {region}",
            )

            return vpc_peering

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting VPC Peering Connections in {region} ({account_name}): {e}",
            )
            return []

    def delete_internet_gateways(
        self, ec2_client, internet_gateways: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete Internet Gateways (detach then delete)"""
        try:
            if not internet_gateways:
                return True

            action_text = "Would delete" if self.dry_run else "Deleting"
            self.log_operation(
                "INFO",
                f"🗑️ {action_text} {len(internet_gateways)} Internet Gateways in {region} ({account_name})",
            )

            for igw in internet_gateways:
                igw_id = igw["InternetGatewayId"]
                try:
                    if self.dry_run:
                        self.log_operation(
                            "INFO",
                            f"🔍 [DRY RUN] Would detach and delete Internet Gateway: {igw_id}",
                        )
                    else:
                        # First detach from VPCs
                        attachments = igw.get("Attachments", [])
                        for attachment in attachments:
                            vpc_id = attachment.get("VpcId")
                            if vpc_id:
                                ec2_client.detach_internet_gateway(
                                    InternetGatewayId=igw_id, VpcId=vpc_id
                                )
                                self.log_operation(
                                    "INFO",
                                    f"🔌 Detached IGW {igw_id} from VPC {vpc_id}",
                                )

                        # Then delete the IGW
                        ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
                        self.log_operation(
                            "INFO", f"✅ Deleted Internet Gateway: {igw_id}"
                        )

                    self.cleanup_results["resources_deleted"][
                        "internet_gateways"
                    ].append(
                        {
                            "id": igw_id,
                            "region": region,
                            "account": account_name,
                            "dry_run": self.dry_run,
                        }
                    )
                except ClientError as e:
                    if "InvalidInternetGatewayID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Internet Gateway {igw_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete IGW {igw_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Internet Gateway",
                                "id": igw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete Internet Gateway {igw_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Internet Gateway",
                                "id": igw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        if not self.dry_run:
                            return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Internet Gateways in {region} ({account_name}): {e}",
            )
            return False

    def delete_security_groups(
        self, ec2_client, security_groups: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete Security Groups (clear rules then delete)"""
        try:
            if not security_groups:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(security_groups)} Security Groups in {region} ({account_name})",
            )

            # First pass: Clear all rules from security groups
            for sg in security_groups:
                sg_id = sg["GroupId"]
                try:
                    # Clear ingress rules
                    if sg.get("IpPermissions"):
                        ec2_client.revoke_security_group_ingress(
                            GroupId=sg_id, IpPermissions=sg["IpPermissions"]
                        )
                        self.log_operation(
                            "INFO", f"🧹 Cleared ingress rules for SG {sg_id}"
                        )

                    # Clear egress rules
                    if sg.get("IpPermissionsEgress"):
                        # Don't remove the default allow-all egress rule
                        custom_egress = [
                            rule
                            for rule in sg["IpPermissionsEgress"]
                            if not (
                                rule.get("IpProtocol") == "-1"
                                and rule.get("IpRanges") == [{"CidrIp": "0.0.0.0/0"}]
                            )
                        ]
                        if custom_egress:
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg_id, IpPermissions=custom_egress
                            )
                            self.log_operation(
                                "INFO", f"🧹 Cleared custom egress rules for SG {sg_id}"
                            )

                except ClientError as e:
                    if "InvalidGroupId.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Security Group {sg_id} already deleted"
                        )
                    else:
                        self.log_operation(
                            "WARNING", f"⚠️ Failed to clear rules for SG {sg_id}: {e}"
                        )

            # Second pass: Delete security groups
            for sg in security_groups:
                sg_id = sg["GroupId"]
                sg_name = sg["GroupName"]
                try:
                    ec2_client.delete_security_group(GroupId=sg_id)
                    self.log_operation(
                        "INFO", f"✅ Deleted Security Group: {sg_id} ({sg_name})"
                    )
                    self.cleanup_results["resources_deleted"]["security_groups"].append(
                        {
                            "id": sg_id,
                            "name": sg_name,
                            "region": region,
                            "account": account_name,
                        }
                    )
                except ClientError as e:
                    if "InvalidGroupId.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Security Group {sg_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete SG {sg_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Security Group",
                                "id": sg_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete Security Group {sg_id}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Security Group",
                                "id": sg_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Security Groups in {region} ({account_name}): {e}",
            )
            return False

    def delete_route_tables(
        self, ec2_client, route_tables: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete Route Tables (non-main)"""
        try:
            if not route_tables:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(route_tables)} Route Tables in {region} ({account_name})",
            )

            for rt in route_tables:
                rt_id = rt["RouteTableId"]
                try:
                    # Disassociate from subnets first
                    associations = rt.get("Associations", [])
                    for assoc in associations:
                        if not assoc.get("Main", False) and assoc.get("SubnetId"):
                            assoc_id = assoc["RouteTableAssociationId"]
                            ec2_client.disassociate_route_table(AssociationId=assoc_id)
                            self.log_operation(
                                "INFO", f"🔌 Disassociated RT {rt_id} from subnet"
                            )

                    # Delete the route table
                    ec2_client.delete_route_table(RouteTableId=rt_id)
                    self.log_operation("INFO", f"✅ Deleted Route Table: {rt_id}")
                    self.cleanup_results["resources_deleted"]["route_tables"].append(
                        {"id": rt_id, "region": region, "account": account_name}
                    )
                except ClientError as e:
                    if "InvalidRouteTableID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Route Table {rt_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete RT {rt_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Route Table",
                                "id": rt_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete Route Table {rt_id}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Route Table",
                                "id": rt_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Route Tables in {region} ({account_name}): {e}",
            )
            return False

    def delete_network_acls(
        self, ec2_client, network_acls: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete Network ACLs (non-default)"""
        try:
            if not network_acls:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(network_acls)} Network ACLs in {region} ({account_name})",
            )

            for acl in network_acls:
                acl_id = acl["NetworkAclId"]
                try:
                    ec2_client.delete_network_acl(NetworkAclId=acl_id)
                    self.log_operation("INFO", f"✅ Deleted Network ACL: {acl_id}")
                    self.cleanup_results["resources_deleted"]["network_acls"].append(
                        {"id": acl_id, "region": region, "account": account_name}
                    )
                except ClientError as e:
                    if "InvalidNetworkAclID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Network ACL {acl_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete ACL {acl_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Network ACL",
                                "id": acl_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete Network ACL {acl_id}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Network ACL",
                                "id": acl_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Network ACLs in {region} ({account_name}): {e}",
            )
            return False

    def delete_elastic_ips(
        self, ec2_client, elastic_ips: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete unassociated Elastic IPs"""
        try:
            if not elastic_ips:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Releasing {len(elastic_ips)} Elastic IPs in {region} ({account_name})",
            )

            for eip in elastic_ips:
                allocation_id = eip.get("AllocationId")
                public_ip = eip.get("PublicIp")

                try:
                    if allocation_id:
                        ec2_client.release_address(AllocationId=allocation_id)
                    else:
                        # Classic EIP
                        ec2_client.release_address(PublicIp=public_ip)

                    self.log_operation(
                        "INFO", f"✅ Released Elastic IP: {public_ip} ({allocation_id})"
                    )
                    self.cleanup_results["resources_deleted"]["elastic_ips"].append(
                        {
                            "allocation_id": allocation_id,
                            "public_ip": public_ip,
                            "region": region,
                            "account": account_name,
                        }
                    )
                except ClientError as e:
                    if "InvalidAllocationID.NotFound" in str(
                        e
                    ) or "InvalidAddress.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Elastic IP {public_ip} already released"
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to release Elastic IP {public_ip}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Elastic IP",
                                "id": allocation_id or public_ip,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error releasing Elastic IPs in {region} ({account_name}): {e}",
            )
            return False

    def delete_vpn_gateways(
        self, ec2_client, vpn_gateways: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete VPN Gateways (detach then delete)"""
        try:
            if not vpn_gateways:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(vpn_gateways)} VPN Gateways in {region} ({account_name})",
            )

            for vgw in vpn_gateways:
                vgw_id = vgw["VpnGatewayId"]
                try:
                    # Detach from VPCs first
                    attachments = vgw.get("VpcAttachments", [])
                    for attachment in attachments:
                        if attachment.get("State") == "attached":
                            vpc_id = attachment["VpcId"]
                            ec2_client.detach_vpn_gateway(
                                VpnGatewayId=vgw_id, VpcId=vpc_id
                            )
                            self.log_operation(
                                "INFO",
                                f"🔌 Detached VPN Gateway {vgw_id} from VPC {vpc_id}",
                            )

                    # Wait a moment for detachment
                    time.sleep(5)

                    # Delete the VPN Gateway
                    ec2_client.delete_vpn_gateway(VpnGatewayId=vgw_id)
                    self.log_operation("INFO", f"✅ Deleted VPN Gateway: {vgw_id}")
                    self.cleanup_results["resources_deleted"]["vpn_gateways"].append(
                        {"id": vgw_id, "region": region, "account": account_name}
                    )
                except ClientError as e:
                    if "InvalidVpnGatewayID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ VPN Gateway {vgw_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete VPN Gateway {vgw_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "VPN Gateway",
                                "id": vgw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete VPN Gateway {vgw_id}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "VPN Gateway",
                                "id": vgw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting VPN Gateways in {region} ({account_name}): {e}",
            )
            return False

    def delete_transit_gateway_attachments(
        self, ec2_client, tgw_attachments: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete Transit Gateway Attachments"""
        try:
            if not tgw_attachments:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(tgw_attachments)} Transit Gateway Attachments in {region} ({account_name})",
            )

            for attachment in tgw_attachments:
                attachment_id = attachment["TransitGatewayAttachmentId"]
                try:
                    ec2_client.delete_transit_gateway_vpc_attachment(
                        TransitGatewayAttachmentId=attachment_id
                    )
                    self.log_operation(
                        "INFO", f"✅ Deleted TGW Attachment: {attachment_id}"
                    )
                    self.cleanup_results["resources_deleted"][
                        "transit_gateway_attachments"
                    ].append(
                        {"id": attachment_id, "region": region, "account": account_name}
                    )
                except ClientError as e:
                    if "InvalidTransitGatewayAttachmentID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ TGW Attachment {attachment_id} already deleted",
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete TGW Attachment {attachment_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Transit Gateway Attachment",
                                "id": attachment_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Transit Gateway Attachments in {region} ({account_name}): {e}",
            )
            return False

    def delete_network_interfaces(
        self, ec2_client, network_interfaces: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete unattached Network Interfaces"""
        try:
            if not network_interfaces:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(network_interfaces)} Network Interfaces in {region} ({account_name})",
            )

            for eni in network_interfaces:
                eni_id = eni["NetworkInterfaceId"]
                try:
                    ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
                    self.log_operation(
                        "INFO", f"✅ Deleted Network Interface: {eni_id}"
                    )
                    self.cleanup_results["resources_deleted"][
                        "network_interfaces"
                    ].append({"id": eni_id, "region": region, "account": account_name})
                except ClientError as e:
                    if "InvalidNetworkInterfaceID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Network Interface {eni_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete ENI {eni_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Network Interface",
                                "id": eni_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete Network Interface {eni_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Network Interface",
                                "id": eni_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Network Interfaces in {region} ({account_name}): {e}",
            )
            return False

    def print_colored(self, color: str, message: str):
        """Print colored message to console"""
        print(f"{color}{message}{Colors.END}")

    def delete_subnets(
        self, ec2_client, subnets: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete all custom subnets"""
        try:
            if not subnets:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(subnets)} Subnets in {region} ({account_name})",
            )

            for subnet in subnets:
                subnet_id = subnet["SubnetId"]
                try:
                    ec2_client.delete_subnet(SubnetId=subnet_id)
                    self.log_operation("INFO", f"✅ Deleted Subnet: {subnet_id}")
                    self.cleanup_results["resources_deleted"]["subnets"].append(
                        {
                            "id": subnet_id,
                            "cidr": subnet.get("CidrBlock"),
                            "az": subnet.get("AvailabilityZone"),
                            "region": region,
                            "account": account_name,
                        }
                    )
                except ClientError as e:
                    if "InvalidSubnetID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Subnet {subnet_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete Subnet {subnet_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Subnet",
                                "id": subnet_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete Subnet {subnet_id}: {e}"
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Subnet",
                                "id": subnet_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error deleting Subnets in {region} ({account_name}): {e}"
            )
            return False

    def delete_dhcp_options_sets(
        self, ec2_client, dhcp_options: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete custom DHCP Options Sets"""
        try:
            if not dhcp_options:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(dhcp_options)} DHCP Options Sets in {region} ({account_name})",
            )

            for dhcp in dhcp_options:
                dhcp_id = dhcp["DhcpOptionsId"]
                try:
                    ec2_client.delete_dhcp_options(DhcpOptionsId=dhcp_id)
                    self.log_operation(
                        "INFO", f"✅ Deleted DHCP Options Set: {dhcp_id}"
                    )
                    self.cleanup_results["resources_deleted"][
                        "dhcp_options_sets"
                    ].append({"id": dhcp_id, "region": region, "account": account_name})
                except ClientError as e:
                    if "InvalidDhcpOptionID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ DHCP Options Set {dhcp_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete DHCP Options {dhcp_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "DHCP Options Set",
                                "id": dhcp_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete DHCP Options Set {dhcp_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "DHCP Options Set",
                                "id": dhcp_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting DHCP Options Sets in {region} ({account_name}): {e}",
            )
            return False

    def delete_customer_gateways(
        self, ec2_client, customer_gateways: List[Dict], region: str, account_name: str
    ) -> bool:
        """Delete Customer Gateways"""
        try:
            if not customer_gateways:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(customer_gateways)} Customer Gateways in {region} ({account_name})",
            )

            for cgw in customer_gateways:
                cgw_id = cgw["CustomerGatewayId"]
                try:
                    ec2_client.delete_customer_gateway(CustomerGatewayId=cgw_id)
                    self.log_operation("INFO", f"✅ Deleted Customer Gateway: {cgw_id}")
                    self.cleanup_results["resources_deleted"][
                        "customer_gateways"
                    ].append({"id": cgw_id, "region": region, "account": account_name})
                except ClientError as e:
                    if "InvalidCustomerGatewayID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING", f"⚠️ Customer Gateway {cgw_id} already deleted"
                        )
                    elif "DependencyViolation" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ Cannot delete Customer Gateway {cgw_id}: dependency violation",
                        )
                        self.cleanup_results["dependency_violations"].append(
                            {
                                "type": "Customer Gateway",
                                "id": cgw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete Customer Gateway {cgw_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "Customer Gateway",
                                "id": cgw_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting Customer Gateways in {region} ({account_name}): {e}",
            )
            return False

    def delete_vpc_peering_connections(
        self,
        ec2_client,
        peering_connections: List[Dict],
        region: str,
        account_name: str,
    ) -> bool:
        """Delete VPC Peering Connections"""
        try:
            if not peering_connections:
                return True

            self.log_operation(
                "INFO",
                f"🗑️ Deleting {len(peering_connections)} VPC Peering Connections in {region} ({account_name})",
            )

            for peering in peering_connections:
                peering_id = peering["VpcPeeringConnectionId"]
                try:
                    ec2_client.delete_vpc_peering_connection(
                        VpcPeeringConnectionId=peering_id
                    )
                    self.log_operation(
                        "INFO", f"✅ Deleted VPC Peering Connection: {peering_id}"
                    )
                    self.cleanup_results["resources_deleted"][
                        "vpc_peering_connections"
                    ].append(
                        {"id": peering_id, "region": region, "account": account_name}
                    )
                except ClientError as e:
                    if "InvalidVpcPeeringConnectionID.NotFound" in str(e):
                        self.log_operation(
                            "WARNING",
                            f"⚠️ VPC Peering Connection {peering_id} already deleted",
                        )
                    else:
                        self.log_operation(
                            "ERROR",
                            f"❌ Failed to delete VPC Peering Connection {peering_id}: {e}",
                        )
                        self.cleanup_results["failed_deletions"].append(
                            {
                                "type": "VPC Peering Connection",
                                "id": peering_id,
                                "error": str(e),
                                "region": region,
                                "account": account_name,
                            }
                        )
                        return False

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting VPC Peering Connections in {region} ({account_name}): {e}",
            )
            return False

    def _get_user_regions(self) -> List[str]:
        """Get user regions from root accounts config."""
        try:
            config = self.cred_manager.load_root_accounts_config()
            if config:
                return config.get("user_settings", {}).get(
                    "user_regions",
                    ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ap-south-1"],
                )
        except Exception as e:
            self.print_colored(
                Colors.YELLOW, f"⚠️  Warning: Could not load user regions: {e}"
            )

        return ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ap-south-1"]

    def select_operation_mode(self) -> bool:
        """Select between dry-run and actual deletion"""
        print("\n" + "=" * 80)
        print("🔧 OPERATION MODE SELECTION")
        print("=" * 80)
        print("   1. Dry Run (Analyze only - NO deletions)")
        print("   2. Actual Cleanup (REAL deletions)")
        print("=" * 80)

        while True:
            try:
                choice = input(
                    "Select operation mode (1 for Dry Run, 2 for Actual Cleanup) or 'q' to quit: "
                ).strip()

                if choice.lower() == "q":
                    return False

                if choice == "1":
                    self.dry_run = True
                    print("✅ Dry Run mode selected - NO actual deletions will occur")
                    return True
                elif choice == "2":
                    self.dry_run = False
                    print("⚠️ Actual Cleanup mode selected - REAL deletions will occur")
                    return True
                else:
                    print("❌ Invalid choice. Please enter 1 or 2")

            except Exception as e:
                print(f"❌ Error in selection: {e}")

    def select_accounts_interactive(self) -> List[str]:
        """Interactive account selection"""
        accounts = list(self.config_data["accounts"].keys())

        if not accounts:
            self.log_operation("ERROR", "No valid accounts found in configuration")
            return []

        print("\n" + "=" * 80)
        print("🏢 ACCOUNT SELECTION")
        print("=" * 80)

        for i, account_name in enumerate(accounts, 1):
            account_data = self.config_data["accounts"][account_name]
            account_id = account_data.get("account_id", "Unknown")
            email = account_data.get("email", "Unknown")
            print(f"   {i}. {account_name} ({account_id}) - {email}")

        print(f"   {len(accounts) + 1}. All accounts")
        print("=" * 80)

        while True:
            try:
                choice = input(
                    "Select accounts (comma-separated numbers) or 'q' to quit: "
                ).strip()

                if choice.lower() == "q":
                    return []

                if choice == str(len(accounts) + 1):
                    return accounts

                selected_indices = [int(x.strip()) for x in choice.split(",")]
                selected_accounts = []

                for idx in selected_indices:
                    if 1 <= idx <= len(accounts):
                        selected_accounts.append(accounts[idx - 1])
                    else:
                        print(
                            f"❌ Invalid choice: {idx}. Please select numbers between 1 and {len(accounts)}"
                        )
                        break
                else:
                    if selected_accounts:
                        print(f"\n✅ Selected accounts: {', '.join(selected_accounts)}")
                        return selected_accounts

            except ValueError:
                print("❌ Please enter valid numbers separated by commas")
            except Exception as e:
                print(f"❌ Error in selection: {e}")

    def select_regions_interactive(self) -> Optional[List[str]]:
        """Interactive region selection."""
        self.print_colored(Colors.YELLOW, "\n🌍 Available AWS Regions:")
        self.print_colored(Colors.YELLOW, "=" * 80)

        for i, region in enumerate(self.user_regions, 1):
            self.print_colored(Colors.CYAN, f"   {i}. {region}")

        self.print_colored(Colors.YELLOW, "=" * 80)
        self.print_colored(Colors.YELLOW, "💡 Selection options:")
        self.print_colored(Colors.WHITE, "   • Single: 1")
        self.print_colored(Colors.WHITE, "   • Multiple: 1,3,5")
        self.print_colored(Colors.WHITE, "   • Range: 1-5")
        self.print_colored(Colors.WHITE, "   • All: all")
        self.print_colored(Colors.YELLOW, "=" * 80)

        while True:
            try:
                choice = input(
                    f"Select regions (1-{len(self.user_regions)}, comma-separated, range, or 'all') or 'q' to quit: "
                ).strip()

                if choice.lower() == "q":
                    return None

                if choice.lower() == "all" or not choice:
                    self.print_colored(
                        Colors.GREEN,
                        f"✅ Selected all {len(self.user_regions)} regions",
                    )
                    return self.user_regions

                selected_indices = self.cred_manager._parse_selection(
                    choice, len(self.user_regions)
                )
                if not selected_indices:
                    self.print_colored(Colors.RED, "❌ Invalid selection format")
                    continue

                selected_regions = [self.user_regions[i - 1] for i in selected_indices]
                self.print_colored(
                    Colors.GREEN,
                    f"✅ Selected {len(selected_regions)} regions: {', '.join(selected_regions)}",
                )
                return selected_regions

            except Exception as e:
                self.print_colored(
                    Colors.RED, f"❌ Error processing selection: {str(e)}"
                )

    # Replace the run_interactive_cleanup method with this version:
    def run_interactive_cleanup(self):
        """Simplified cleanup flow using shared account/region selection"""
        try:
            print("\n" + "=" * 100)
            print("🚨 ENHANCED ULTRA VPC CLEANUP MANAGER 🚨")
            print("=" * 100)
            print("⚠️  WARNING: This tool can DELETE ALL CUSTOM VPC resources!")
            print("✅ DEFAULT VPC resources will be COMPLETELY PROTECTED and IGNORED")
            print("=" * 100)

            # Use shared account/region selection

            root_accounts = self.cred_manager.select_root_accounts_interactive(
                allow_multiple=True
            )
            if not root_accounts:
                self.print_colored(
                    Colors.RED, "❌ No root accounts selected, exiting..."
                )
                return
            selected_accounts = [acc["account_key"] for acc in root_accounts]

            # STEP 2: Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                self.print_colored(Colors.RED, "❌ No regions selected, exiting...")
                return

            # STEP 3: Calculate total operations and confirm
            total_operations = len(selected_accounts) * len(selected_regions)
            print(
                f"\n📊 Total operations: {total_operations} (Accounts: {len(selected_accounts)}, Regions: {len(selected_regions)})"
            )

            # Simple yes/no confirmation
            confirm = (
                input(
                    f"\nProceed to DELETE all custom VPC resources in selected accounts/regions? (y/n): "
                )
                .strip()
                .lower()
            )
            if confirm != "y" and confirm != "yes":
                print("❌ Operation cancelled")
                return

            self.dry_run = False  # Always actual cleanup in this flow

            self.log_operation(
                "INFO",
                f"🚀 Starting VPC cleanup for {len(selected_accounts)} accounts and {len(selected_regions)} regions",
            )
            total_operations = len(selected_accounts) * len(selected_regions)
            current_operation = 0

            for account_name in selected_accounts:
                account_data = self.config_data["accounts"][account_name]
                access_key = account_data["access_key"]
                secret_key = account_data["secret_key"]

                self.cleanup_results["accounts_processed"].append(account_name)

                for region in selected_regions:
                    current_operation += 1
                    print(
                        f"\n[{current_operation}/{total_operations}] Processing {account_name} - {region}"
                    )
                    self.log_operation("INFO", f"Processing {account_name} - {region}")

                    ec2_client = self.create_ec2_client(access_key, secret_key, region)
                    if not ec2_client:
                        continue

                    self.cleanup_results["regions_processed"].append(
                        f"{account_name}:{region}"
                    )

                    success = self.cleanup_vpc_resources_in_region(
                        ec2_client, region, account_name
                    )

                    # Delete unused EBS volumes
                    ebs_deleted = self.delete_unused_ebs_volumes(
                        ec2_client, region, account_name
                    )
                    print(f"   🗑️ Deleted {ebs_deleted} unused EBS volumes in {region}")

                    # Delete unused EFS file systems
                    efs_deleted = self.delete_unused_efs_filesystems(
                        access_key, secret_key, region, account_name
                    )
                    print(
                        f"   🗑️ Deleted {efs_deleted} unused EFS file systems in {region}"
                    )

                    if success:
                        print(f"   ✅ Completed cleanup for {account_name} - {region}")
                    else:
                        print(
                            f"   ⚠️ Cleanup completed with some issues for {account_name} - {region}"
                        )

            self.generate_cleanup_report()

        except KeyboardInterrupt:
            self.log_operation("WARNING", "🛑 Cleanup interrupted by user")
            print("\n🛑 Cleanup interrupted by user")
        except Exception as e:
            self.log_operation("ERROR", f"Error in cleanup: {e}")
            print(f"❌ Error in cleanup: {e}")

    def run_interactive_cleanup_bk(self):
        """Main interactive cleanup flow"""
        try:
            print("\n" + "=" * 100)
            print("🚨 ENHANCED ULTRA VPC CLEANUP MANAGER 🚨")
            print("=" * 100)
            print("⚠️  WARNING: This tool can DELETE ALL CUSTOM VPC resources!")
            print("✅ DEFAULT VPC resources will be COMPLETELY PROTECTED and IGNORED")
            print("=" * 100)

            # Select operation mode first
            if not self.select_operation_mode():
                print("❌ Operation cancelled")
                return

            # Confirm user wants to proceed
            if not self.dry_run:
                confirm = input(
                    "\nDo you want to proceed with ACTUAL VPC cleanup? (type 'YES' to continue): "
                ).strip()
                if confirm != "YES":
                    print("❌ Operation cancelled")
                    return

            # Select accounts
            selected_accounts = self.select_accounts_interactive()
            if not selected_accounts:
                print("❌ No accounts selected. Exiting...")
                return

            # Select regions
            selected_regions = self.select_regions_interactive()
            if not selected_regions:
                print("❌ No regions selected. Exiting...")
                return

            # Final confirmation
            mode_text = "DRY RUN ANALYSIS" if self.dry_run else "ACTUAL CLEANUP"
            print(f"\n⚠️  FINAL CONFIRMATION - {mode_text}")
            print(f"📊 Accounts to process: {len(selected_accounts)}")
            print(f"🌍 Regions to process: {len(selected_regions)}")

            if self.dry_run:
                print(f"🔍 This will ANALYZE VPC resources (no deletions)")
                final_confirm = input(
                    "\nType 'ANALYZE VPC RESOURCES' to proceed: "
                ).strip()
                if final_confirm != "ANALYZE VPC RESOURCES":
                    print("❌ Operation cancelled")
                    return
            else:
                print(
                    f"🗑️ This will DELETE ALL CUSTOM VPC resources in selected accounts/regions"
                )
                print(f"✅ Default VPC resources will be PROTECTED")
                final_confirm = input(
                    "\nType 'DELETE CUSTOM VPC RESOURCES' to proceed: "
                ).strip()
                if final_confirm != "DELETE CUSTOM VPC RESOURCES":
                    print("❌ Operation cancelled")
                    return

            # Start cleanup
            operation_text = "analysis" if self.dry_run else "cleanup"
            self.log_operation(
                "INFO",
                f"🚀 Starting VPC {operation_text} for {len(selected_accounts)} accounts and {len(selected_regions)} regions",
            )

            total_operations = len(selected_accounts) * len(selected_regions)
            current_operation = 0

            for account_name in selected_accounts:
                account_data = self.config_data["accounts"][account_name]
                access_key = account_data["access_key"]
                secret_key = account_data["secret_key"]

                self.cleanup_results["accounts_processed"].append(account_name)

                for region in selected_regions:
                    current_operation += 1
                    print(
                        f"\n[{current_operation}/{total_operations}] Processing {account_name} - {region}"
                    )
                    self.log_operation("INFO", f"Processing {account_name} - {region}")

                    # Create EC2 client
                    ec2_client = self.create_ec2_client(access_key, secret_key, region)
                    if not ec2_client:
                        continue

                    self.cleanup_results["regions_processed"].append(
                        f"{account_name}:{region}"
                    )

                    # Clean up VPC resources in the specified order
                    success = self.cleanup_vpc_resources_in_region(
                        ec2_client, region, account_name
                    )

                    if success:
                        print(
                            f"   ✅ Completed {operation_text} for {account_name} - {region}"
                        )
                    else:
                        print(
                            f"   ⚠️ {operation_text.title()} completed with some issues for {account_name} - {region}"
                        )

                    # Delete unused EBS volumes
                    ebs_deleted = self.delete_unused_ebs_volumes(
                        ec2_client, region, account_name
                    )
                    print(f"   🗑️ Deleted {ebs_deleted} unused EBS volumes in {region}")

                    # Delete unused EFS file systems
                    efs_deleted = self.delete_unused_efs_filesystems(
                        access_key, secret_key, region, account_name
                    )
                    print(
                        f"   🗑️ Deleted {efs_deleted} unused EFS file systems in {region}"
                    )

            # Generate final report
            self.generate_cleanup_report()

        except KeyboardInterrupt:
            self.log_operation(
                "WARNING", f"🛑 {operation_text.title()} interrupted by user"
            )
            print(f"\n🛑 {operation_text.title()} interrupted by user")
        except Exception as e:
            self.log_operation("ERROR", f"Error in interactive {operation_text}: {e}")
            print(f"❌ Error in {operation_text}: {e}")

    def delete_unused_ebs_volumes(
        self, ec2_client, region: str, account_name: str
    ) -> int:
        """Delete all unattached (available) EBS volumes in the region."""
        try:
            response = ec2_client.describe_volumes(
                Filters=[{"Name": "status", "Values": ["available"]}]
            )
            volumes = response.get("Volumes", [])
            count = 0
            for vol in volumes:
                vol_id = vol["VolumeId"]
                try:
                    ec2_client.delete_volume(VolumeId=vol_id)
                    self.log_operation(
                        "INFO", f"✅ Deleted unused EBS volume: {vol_id}"
                    )
                    count += 1
                except Exception as e:
                    self.log_operation(
                        "ERROR", f"❌ Failed to delete EBS volume {vol_id}: {e}"
                    )
            return count
        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting unused EBS volumes in {region} ({account_name}): {e}",
            )
            return 0

    def delete_unused_efs_filesystems(
        self, access_key: str, secret_key: str, region: str, account_name: str
    ) -> int:
        """Delete all EFS file systems with no mount targets in the region."""
        try:
            efs_client = boto3.client(
                "efs",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
            response = efs_client.describe_file_systems()
            filesystems = response.get("FileSystems", [])
            count = 0
            for fs in filesystems:
                fs_id = fs["FileSystemId"]
                mt_resp = efs_client.describe_mount_targets(FileSystemId=fs_id)
                if not mt_resp.get("MountTargets"):
                    try:
                        efs_client.delete_file_system(FileSystemId=fs_id)
                        self.log_operation(
                            "INFO", f"✅ Deleted unused EFS file system: {fs_id}"
                        )
                        count += 1
                    except Exception as e:
                        self.log_operation(
                            "ERROR", f"❌ Failed to delete EFS file system {fs_id}: {e}"
                        )
            return count
        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error deleting unused EFS file systems in {region} ({account_name}): {e}",
            )
            return 0

    def cleanup_vpc_resources_in_region(
        self, ec2_client, region: str, account_name: str
    ) -> bool:
        """Clean up all VPC resources in a region following dependency order"""
        try:
            # Get all custom VPCs first
            custom_vpcs = self.get_all_vpcs_in_region(ec2_client, region, account_name)
            if not custom_vpcs:
                self.log_operation(
                    "INFO", f"No custom VPCs found in {region} ({account_name})"
                )
                return True

            vpc_ids = [vpc["VpcId"] for vpc in custom_vpcs]
            self.log_operation(
                "INFO", f"Processing {len(custom_vpcs)} custom VPCs: {vpc_ids}"
            )

            for vpc in custom_vpcs:
                self.cleanup_results["vpcs_analyzed"].append(
                    {
                        "vpc_id": vpc["VpcId"],
                        "cidr": vpc["CidrBlock"],
                        "region": region,
                        "account": account_name,
                    }
                )

            # Clean up resources in dependency order
            cleanup_success = True

            # 1. VPC Flow Logs
            flow_logs = self.get_vpc_flow_logs(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_vpc_flow_logs(
                ec2_client, flow_logs, region, account_name
            ):
                cleanup_success = False

            # 2. VPC Endpoints
            endpoints = self.get_vpc_endpoints(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_vpc_endpoints(
                ec2_client, endpoints, region, account_name
            ):
                cleanup_success = False

            # 3. NAT Gateways (with waiting)
            nat_gateways = self.get_nat_gateways(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_nat_gateways_with_wait(
                ec2_client, nat_gateways, region, account_name
            ):
                cleanup_success = False

            # 4. Internet Gateways (detach then delete)
            internet_gateways = self.get_internet_gateways(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_internet_gateways(
                ec2_client, internet_gateways, region, account_name
            ):
                cleanup_success = False

            # 5. Security Groups (clear rules then delete non-default)
            security_groups = self.get_security_groups(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_security_groups(
                ec2_client, security_groups, region, account_name
            ):
                cleanup_success = False

            # 6. Route Tables (non-main)
            route_tables = self.get_route_tables(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_route_tables(
                ec2_client, route_tables, region, account_name
            ):
                cleanup_success = False

            # 7. Network ACLs (non-default)
            network_acls = self.get_network_acls(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_network_acls(
                ec2_client, network_acls, region, account_name
            ):
                cleanup_success = False

            # 8. Elastic IPs (VPC-associated)
            elastic_ips = self.get_elastic_ips(ec2_client, region, account_name)
            if not self.delete_elastic_ips(
                ec2_client, elastic_ips, region, account_name
            ):
                cleanup_success = False

            # 9. VPN Gateways
            vpn_gateways = self.get_vpn_gateways(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_vpn_gateways(
                ec2_client, vpn_gateways, region, account_name
            ):
                cleanup_success = False

            # 10. Transit Gateway Attachments
            tgw_attachments = self.get_transit_gateway_attachments(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_transit_gateway_attachments(
                ec2_client, tgw_attachments, region, account_name
            ):
                cleanup_success = False

            # 11. Network Interfaces (unattached)
            network_interfaces = self.get_network_interfaces(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_network_interfaces(
                ec2_client, network_interfaces, region, account_name
            ):
                cleanup_success = False

            # 12. Subnets (all custom subnets)
            subnets = self.get_subnets(ec2_client, vpc_ids, region, account_name)
            if not self.delete_subnets(ec2_client, subnets, region, account_name):
                cleanup_success = False

            # 13. DHCP Options Sets (custom ones)
            dhcp_options = self.get_dhcp_options_sets(
                ec2_client, custom_vpcs, region, account_name
            )
            if not self.delete_dhcp_options_sets(
                ec2_client, dhcp_options, region, account_name
            ):
                cleanup_success = False

            # 14. Customer Gateways (if VPC-specific)
            customer_gateways = self.get_customer_gateways(
                ec2_client, region, account_name
            )
            if not self.delete_customer_gateways(
                ec2_client, customer_gateways, region, account_name
            ):
                cleanup_success = False

            # 15. VPC Peering Connections
            peering_connections = self.get_vpc_peering_connections(
                ec2_client, vpc_ids, region, account_name
            )
            if not self.delete_vpc_peering_connections(
                ec2_client, peering_connections, region, account_name
            ):
                cleanup_success = False

            return cleanup_success

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error cleaning up VPC resources in {region} ({account_name}): {e}",
            )
            return False

    def generate_cleanup_report(self):
        """Generate comprehensive cleanup report"""
        try:
            report_file = (
                f"aws/vpc/logs/vpc_cleanup_report_{self.execution_timestamp}.json"
            )
            os.makedirs(os.path.dirname(report_file), exist_ok=True)

            # Prepare report summary
            report = {
                "execution_summary": {
                    "timestamp": self.current_time_str,
                    "user": self.current_user,
                    "dry_run": self.dry_run,
                    "accounts_processed": len(
                        self.cleanup_results["accounts_processed"]
                    ),
                    "regions_processed": len(self.cleanup_results["regions_processed"]),
                    "vpcs_analyzed": len(self.cleanup_results["vpcs_analyzed"]),
                },
                "resources_deleted_summary": {},
                "protection_summary": {
                    "default_resources_protected": len(
                        self.cleanup_results["default_resources_skipped"]
                    )
                },
                "detailed_results": self.cleanup_results,
            }

            # Calculate deletion summary
            for resource_type, resources in self.cleanup_results[
                "resources_deleted"
            ].items():
                report["resources_deleted_summary"][resource_type] = len(resources)

            # Save report
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)

            # Print summary
            print("\n" + "=" * 100)
            mode_text = "DRY RUN ANALYSIS" if self.dry_run else "VPC CLEANUP"
            print(f"📊 {mode_text} SUMMARY REPORT")
            print("=" * 100)
            print(
                f"✅ Accounts processed: {report['execution_summary']['accounts_processed']}"
            )
            print(
                f"🌍 Regions processed: {report['execution_summary']['regions_processed']}"
            )
            print(f"🏗️ VPCs analyzed: {report['execution_summary']['vpcs_analyzed']}")
            print(
                f"🛡️ Default resources protected: {report['protection_summary']['default_resources_protected']}"
            )

            action_text = (
                "Resources that would be deleted:"
                if self.dry_run
                else "Resources deleted:"
            )
            print(f"\n🗑️ {action_text.upper()}")
            total_resources = 0
            for resource_type, count in report["resources_deleted_summary"].items():
                if count > 0:
                    print(f"   • {resource_type.replace('_', ' ').title()}: {count}")
                    total_resources += count

            print(
                f"\n📈 Total resources {'identified for deletion' if self.dry_run else 'deleted'}: {total_resources}"
            )

            if self.cleanup_results["failed_deletions"]:
                print(
                    f"⚠️ Failed {'analyses' if self.dry_run else 'deletions'}: {len(self.cleanup_results['failed_deletions'])}"
                )

            if self.cleanup_results["dependency_violations"]:
                print(
                    f"🔗 Dependency violations detected: {len(self.cleanup_results['dependency_violations'])}"
                )

            print(f"\n📄 Detailed report saved: {report_file}")
            print("=" * 100)

            self.log_operation(
                "INFO",
                f"{'Analysis' if self.dry_run else 'Cleanup'} report generated: {report_file}",
            )

        except Exception as e:
            self.log_operation("ERROR", f"Error generating cleanup report: {e}")


def main():
    """Main function"""
    try:
        manager = UltraVPCCleanupManager()
        manager.run_interactive_cleanup()
    except KeyboardInterrupt:
        print(f"\n\n❌ VPC Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
