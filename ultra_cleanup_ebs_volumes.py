#!/usr/bin/env python3

import json
import os
import sys
import time
from datetime import datetime

import boto3


class UltraEBSVolumeCleanupManager:
    def __init__(self, config_file="aws_accounts_config.json"):
        self.config_file = config_file
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"

        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Initialize log file
        self.setup_detailed_logging()

        # Load configuration
        self.load_configuration()

        # Storage for cleanup results
        self.cleanup_results = {
            "accounts_processed": [],
            "regions_processed": [],
            "deleted_volumes": [],
            "deleted_snapshots": [],
            "skipped_volumes": [],
            "skipped_snapshots": [],
            "failed_deletions": [],
            "errors": [],
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            log_dir = "aws/ebs/logs"
            os.makedirs(log_dir, exist_ok=True)

            self.log_filename = (
                f"{log_dir}/ultra_ebs_cleanup_log_{self.execution_timestamp}.log"
            )

            import logging

            self.operation_logger = logging.getLogger("ultra_ebs_cleanup")
            self.operation_logger.setLevel(logging.INFO)

            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)

            file_handler = logging.FileHandler(self.log_filename, encoding="utf-8")
            file_handler.setLevel(logging.INFO)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)

            self.operation_logger.info("=" * 100)
            self.operation_logger.info(
                "🚨 ULTRA EBS VOLUME & SNAPSHOT CLEANUP SESSION STARTED 🚨"
            )
            self.operation_logger.info("=" * 100)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Config File: {self.config_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 100)

        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Simple logging operation"""
        if self.operation_logger:
            if level.upper() == "INFO":
                self.operation_logger.info(message)
            elif level.upper() == "WARNING":
                self.operation_logger.warning(message)
            elif level.upper() == "ERROR":
                self.operation_logger.error(message)
            elif level.upper() == "DEBUG":
                self.operation_logger.debug(message)
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

            if "accounts" not in self.config_data:
                raise ValueError("No 'accounts' section found in configuration")

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

            self.user_regions = self.config_data.get("user_settings", {}).get(
                "user_regions",
                ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ap-south-1"],
            )

            self.log_operation("INFO", f"🌍 Regions to process: {self.user_regions}")

        except FileNotFoundError as e:
            self.log_operation("ERROR", f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log_operation("ERROR", f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.log_operation("ERROR", f"Error loading configuration: {e}")
            sys.exit(1)

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using account credentials"""
        try:
            client = boto3.client(
                "ec2",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )

            # Test the connection
            client.describe_volumes(MaxResults=5)

            return client

        except Exception as e:
            self.log_operation(
                "ERROR", f"Failed to create EC2 client for {region}: {e}"
            )
            raise

    def get_all_volumes(self, ec2_client, region, account_name):
        """Get all EBS volumes in a specific region"""
        try:
            volumes = []

            self.log_operation(
                "INFO", f"🔍 Scanning for EBS volumes in {region} ({account_name})"
            )
            print(f"   🔍 Scanning for EBS volumes in {region} ({account_name})...")

            paginator = ec2_client.get_paginator("describe_volumes")

            for page in paginator.paginate():
                for volume in page["Volumes"]:
                    volume_id = volume["VolumeId"]
                    state = volume["State"]
                    size = volume["Size"]
                    volume_type = volume["VolumeType"]
                    create_time = volume["CreateTime"]
                    encrypted = volume.get("Encrypted", False)

                    # Get tags
                    tags = {tag["Key"]: tag["Value"] for tag in volume.get("Tags", [])}
                    name = tags.get("Name", "N/A")

                    # Check if attached to instance
                    attachments = volume.get("Attachments", [])
                    is_attached = len(attachments) > 0
                    attached_to = (
                        attachments[0].get("InstanceId", "N/A")
                        if is_attached
                        else "N/A"
                    )

                    volume_info = {
                        "volume_id": volume_id,
                        "name": name,
                        "state": state,
                        "size": size,
                        "volume_type": volume_type,
                        "create_time": create_time,
                        "encrypted": encrypted,
                        "is_attached": is_attached,
                        "attached_to": attached_to,
                        "tags": tags,
                        "region": region,
                        "account_name": account_name,
                    }

                    volumes.append(volume_info)

            self.log_operation(
                "INFO",
                f"📦 Found {len(volumes)} EBS volumes in {region} ({account_name})",
            )
            print(
                f"   📦 Found {len(volumes)} EBS volumes in {region} ({account_name})"
            )

            # Count by state
            available_count = sum(1 for v in volumes if v["state"] == "available")
            in_use_count = sum(1 for v in volumes if v["state"] == "in-use")
            other_count = len(volumes) - available_count - in_use_count

            print(
                f"      ✓ Available: {available_count}, In-use: {in_use_count}, Other: {other_count}"
            )

            return volumes

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error getting EBS volumes in {region} ({account_name}): {e}"
            )
            print(f"   ❌ Error getting volumes in {region}: {e}")
            return []

    def get_all_snapshots(self, ec2_client, region, account_name, account_id):
        """Get all EBS snapshots owned by this account"""
        try:
            snapshots = []

            self.log_operation(
                "INFO", f"🔍 Scanning for EBS snapshots in {region} ({account_name})"
            )
            print(f"   🔍 Scanning for EBS snapshots in {region} ({account_name})...")

            paginator = ec2_client.get_paginator("describe_snapshots")

            # Only get snapshots owned by this account
            for page in paginator.paginate(OwnerIds=[account_id]):
                for snapshot in page["Snapshots"]:
                    snapshot_id = snapshot["SnapshotId"]
                    state = snapshot["State"]
                    volume_id = snapshot.get("VolumeId", "N/A")
                    volume_size = snapshot["VolumeSize"]
                    start_time = snapshot["StartTime"]
                    description = snapshot.get("Description", "N/A")
                    encrypted = snapshot.get("Encrypted", False)

                    # Get tags
                    tags = {
                        tag["Key"]: tag["Value"] for tag in snapshot.get("Tags", [])
                    }
                    name = tags.get("Name", "N/A")

                    snapshot_info = {
                        "snapshot_id": snapshot_id,
                        "name": name,
                        "state": state,
                        "volume_id": volume_id,
                        "volume_size": volume_size,
                        "start_time": start_time,
                        "description": description,
                        "encrypted": encrypted,
                        "tags": tags,
                        "region": region,
                        "account_name": account_name,
                    }

                    snapshots.append(snapshot_info)

            self.log_operation(
                "INFO",
                f"📸 Found {len(snapshots)} EBS snapshots in {region} ({account_name})",
            )
            print(
                f"   📸 Found {len(snapshots)} EBS snapshots in {region} ({account_name})"
            )

            return snapshots

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Error getting EBS snapshots in {region} ({account_name}): {e}",
            )
            print(f"   ❌ Error getting snapshots in {region}: {e}")
            return []

    def delete_volume(self, ec2_client, volume_info):
        """Delete an EBS volume"""
        try:
            volume_id = volume_info["volume_id"]
            state = volume_info["state"]
            region = volume_info["region"]
            account_name = volume_info["account_name"]

            # Skip volumes that are in-use
            if state == "in-use":
                self.log_operation(
                    "INFO",
                    f"⏭️  Skipping volume {volume_id} - currently in use (attached to {volume_info['attached_to']})",
                )
                print(f"      ⏭️  Skipping {volume_id} - in use")

                self.cleanup_results["skipped_volumes"].append(
                    {
                        "volume_id": volume_id,
                        "name": volume_info["name"],
                        "state": state,
                        "attached_to": volume_info["attached_to"],
                        "region": region,
                        "account_name": account_name,
                        "reason": "Volume in use",
                    }
                )

                return False

            # Delete available volumes
            if state == "available":
                self.log_operation(
                    "INFO",
                    f"🗑️  Deleting volume {volume_id} ({volume_info['name']}) - {volume_info['size']}GB, {volume_info['volume_type']}",
                )
                print(
                    f"      🗑️  Deleting {volume_id} ({volume_info['name']}) - {volume_info['size']}GB"
                )

                ec2_client.delete_volume(VolumeId=volume_id)

                self.log_operation(
                    "INFO", f"✅ Successfully deleted volume {volume_id}"
                )

                self.cleanup_results["deleted_volumes"].append(
                    {
                        "volume_id": volume_id,
                        "name": volume_info["name"],
                        "size": volume_info["size"],
                        "volume_type": volume_info["volume_type"],
                        "create_time": str(volume_info["create_time"]),
                        "encrypted": volume_info["encrypted"],
                        "region": region,
                        "account_name": account_name,
                        "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

                return True
            else:
                # Skip volumes in other states (creating, deleting, error)
                self.log_operation(
                    "WARNING", f"⏭️  Skipping volume {volume_id} - state: {state}"
                )
                print(f"      ⏭️  Skipping {volume_id} - state: {state}")

                self.cleanup_results["skipped_volumes"].append(
                    {
                        "volume_id": volume_id,
                        "name": volume_info["name"],
                        "state": state,
                        "region": region,
                        "account_name": account_name,
                        "reason": f"Volume in {state} state",
                    }
                )

                return False

        except Exception as e:
            self.log_operation(
                "ERROR", f"Failed to delete volume {volume_info['volume_id']}: {e}"
            )
            print(f"      ❌ Failed to delete {volume_info['volume_id']}: {e}")

            self.cleanup_results["failed_deletions"].append(
                {
                    "resource_type": "volume",
                    "resource_id": volume_info["volume_id"],
                    "name": volume_info["name"],
                    "region": volume_info["region"],
                    "account_name": volume_info["account_name"],
                    "error": str(e),
                }
            )
            return False

    def delete_snapshot(self, ec2_client, snapshot_info):
        """Delete an EBS snapshot"""
        try:
            snapshot_id = snapshot_info["snapshot_id"]
            region = snapshot_info["region"]
            account_name = snapshot_info["account_name"]

            self.log_operation(
                "INFO",
                f"🗑️  Deleting snapshot {snapshot_id} ({snapshot_info['name']}) - {snapshot_info['volume_size']}GB",
            )
            print(
                f"      🗑️  Deleting snapshot {snapshot_id} ({snapshot_info['name']}) - {snapshot_info['volume_size']}GB"
            )

            ec2_client.delete_snapshot(SnapshotId=snapshot_id)

            self.log_operation(
                "INFO", f"✅ Successfully deleted snapshot {snapshot_id}"
            )

            self.cleanup_results["deleted_snapshots"].append(
                {
                    "snapshot_id": snapshot_id,
                    "name": snapshot_info["name"],
                    "volume_id": snapshot_info["volume_id"],
                    "volume_size": snapshot_info["volume_size"],
                    "start_time": str(snapshot_info["start_time"]),
                    "description": snapshot_info["description"],
                    "encrypted": snapshot_info["encrypted"],
                    "region": region,
                    "account_name": account_name,
                    "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

            return True

        except Exception as e:
            self.log_operation(
                "ERROR",
                f"Failed to delete snapshot {snapshot_info['snapshot_id']}: {e}",
            )
            print(
                f"      ❌ Failed to delete snapshot {snapshot_info['snapshot_id']}: {e}"
            )

            self.cleanup_results["failed_deletions"].append(
                {
                    "resource_type": "snapshot",
                    "resource_id": snapshot_info["snapshot_id"],
                    "name": snapshot_info["name"],
                    "region": snapshot_info["region"],
                    "account_name": snapshot_info["account_name"],
                    "error": str(e),
                }
            )
            return False

    def cleanup_account_region(self, account_name, account_data, region):
        """Clean up all available EBS volumes and snapshots in a specific account and region"""
        try:
            access_key = account_data["access_key"]
            secret_key = account_data["secret_key"]
            account_id = account_data["account_id"]

            self.log_operation(
                "INFO",
                f"🧹 Starting cleanup for {account_name} ({account_id}) in {region}",
            )
            print(
                f"\n🧹 Starting cleanup for {account_name} ({account_id}) in {region}"
            )

            # Create EC2 client
            try:
                ec2_client = self.create_ec2_client(access_key, secret_key, region)
            except Exception as client_error:
                self.log_operation(
                    "ERROR", f"Could not create EC2 client for {region}: {client_error}"
                )
                print(f"   ❌ Could not create EC2 client for {region}: {client_error}")
                return False

            # Get all EBS volumes
            volumes = self.get_all_volumes(ec2_client, region, account_name)

            # Get all EBS snapshots
            snapshots = self.get_all_snapshots(
                ec2_client, region, account_name, account_id
            )

            if not volumes and not snapshots:
                self.log_operation(
                    "INFO", f"No EBS resources found in {account_name} ({region})"
                )
                print(f"   ✓ No EBS resources found in {account_name} ({region})")
                return True

            # Record region summary
            region_summary = {
                "account_name": account_name,
                "account_id": account_id,
                "region": region,
                "volumes_found": len(volumes),
                "snapshots_found": len(snapshots),
                "available_volumes": sum(
                    1 for v in volumes if v["state"] == "available"
                ),
                "in_use_volumes": sum(1 for v in volumes if v["state"] == "in-use"),
            }
            self.cleanup_results["regions_processed"].append(region_summary)

            # Add account to processed accounts if not already there
            if account_name not in [
                a["account_name"] for a in self.cleanup_results["accounts_processed"]
            ]:
                self.cleanup_results["accounts_processed"].append(
                    {"account_name": account_name, "account_id": account_id}
                )

            # Delete available volumes
            if volumes:
                available_volumes = [v for v in volumes if v["state"] == "available"]

                if available_volumes:
                    print(
                        f"\n   🗑️  Deleting {len(available_volumes)} available volumes..."
                    )
                    for volume in available_volumes:
                        self.delete_volume(ec2_client, volume)
                else:
                    print(
                        f"   ✓ No available volumes to delete (all are in-use or in other states)"
                    )

            # Delete all snapshots
            if snapshots:
                print(f"\n   🗑️  Deleting {len(snapshots)} snapshots...")
                for snapshot in snapshots:
                    self.delete_snapshot(ec2_client, snapshot)

            self.log_operation(
                "INFO", f"✅ Cleanup completed for {account_name} ({region})"
            )
            print(f"   ✅ Cleanup completed for {account_name} ({region})")
            return True

        except Exception as e:
            self.log_operation(
                "ERROR", f"Error cleaning up {account_name} ({region}): {e}"
            )
            print(f"   ❌ Error cleaning up {account_name} ({region}): {e}")
            self.cleanup_results["errors"].append(
                {"account_name": account_name, "region": region, "error": str(e)}
            )
            return False

    def save_cleanup_report(self):
        """Save comprehensive cleanup results to JSON report"""
        try:
            report_dir = "aws/ebs/reports"
            os.makedirs(report_dir, exist_ok=True)
            report_filename = (
                f"{report_dir}/ultra_ebs_cleanup_report_{self.execution_timestamp}.json"
            )

            total_volumes_deleted = len(self.cleanup_results["deleted_volumes"])
            total_snapshots_deleted = len(self.cleanup_results["deleted_snapshots"])
            total_volumes_skipped = len(self.cleanup_results["skipped_volumes"])
            total_failed = len(self.cleanup_results["failed_deletions"])

            # Calculate storage saved
            total_gb_deleted = sum(
                v["size"] for v in self.cleanup_results["deleted_volumes"]
            )
            total_snapshot_gb_deleted = sum(
                s["volume_size"] for s in self.cleanup_results["deleted_snapshots"]
            )

            # Group by account and region
            deletions_by_account = {}
            deletions_by_region = {}

            for volume in self.cleanup_results["deleted_volumes"]:
                account = volume["account_name"]
                region = volume["region"]

                if account not in deletions_by_account:
                    deletions_by_account[account] = {
                        "volumes": 0,
                        "snapshots": 0,
                        "gb_saved": 0,
                    }
                deletions_by_account[account]["volumes"] += 1
                deletions_by_account[account]["gb_saved"] += volume["size"]

                if region not in deletions_by_region:
                    deletions_by_region[region] = {
                        "volumes": 0,
                        "snapshots": 0,
                        "gb_saved": 0,
                    }
                deletions_by_region[region]["volumes"] += 1
                deletions_by_region[region]["gb_saved"] += volume["size"]

            for snapshot in self.cleanup_results["deleted_snapshots"]:
                account = snapshot["account_name"]
                region = snapshot["region"]

                if account not in deletions_by_account:
                    deletions_by_account[account] = {
                        "volumes": 0,
                        "snapshots": 0,
                        "gb_saved": 0,
                    }
                deletions_by_account[account]["snapshots"] += 1
                deletions_by_account[account]["gb_saved"] += snapshot["volume_size"]

                if region not in deletions_by_region:
                    deletions_by_region[region] = {
                        "volumes": 0,
                        "snapshots": 0,
                        "gb_saved": 0,
                    }
                deletions_by_region[region]["snapshots"] += 1
                deletions_by_region[region]["gb_saved"] += snapshot["volume_size"]

            report_data = {
                "metadata": {
                    "cleanup_type": "ULTRA_EBS_VOLUMES_SNAPSHOTS_CLEANUP",
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "config_file": self.config_file,
                    "log_file": self.log_filename,
                    "accounts_in_config": list(self.config_data["accounts"].keys()),
                    "regions_processed": self.user_regions,
                },
                "summary": {
                    "total_accounts_processed": len(
                        self.cleanup_results["accounts_processed"]
                    ),
                    "total_regions_processed": len(
                        self.cleanup_results["regions_processed"]
                    ),
                    "total_volumes_deleted": total_volumes_deleted,
                    "total_snapshots_deleted": total_snapshots_deleted,
                    "total_volumes_skipped": total_volumes_skipped,
                    "total_failed_deletions": total_failed,
                    "total_gb_deleted": total_gb_deleted,
                    "total_snapshot_gb_deleted": total_snapshot_gb_deleted,
                    "total_storage_freed_gb": total_gb_deleted
                    + total_snapshot_gb_deleted,
                    "deletions_by_account": deletions_by_account,
                    "deletions_by_region": deletions_by_region,
                },
                "detailed_results": {
                    "accounts_processed": self.cleanup_results["accounts_processed"],
                    "regions_processed": self.cleanup_results["regions_processed"],
                    "deleted_volumes": self.cleanup_results["deleted_volumes"],
                    "deleted_snapshots": self.cleanup_results["deleted_snapshots"],
                    "skipped_volumes": self.cleanup_results["skipped_volumes"],
                    "failed_deletions": self.cleanup_results["failed_deletions"],
                    "errors": self.cleanup_results["errors"],
                },
            }

            with open(report_filename, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, default=str)

            self.log_operation(
                "INFO", f"✅ Ultra cleanup report saved to: {report_filename}"
            )
            return report_filename

        except Exception as e:
            self.log_operation("ERROR", f"❌ Failed to save ultra cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.log_operation(
                "INFO", "🚨 STARTING ULTRA EBS VOLUME & SNAPSHOT CLEANUP SESSION 🚨"
            )

            print("🚨" * 30)
            print("💥 ULTRA EBS VOLUME & SNAPSHOT CLEANUP 💥")
            print("🚨" * 30)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📋 Log File: {self.log_filename}")

            # Display available accounts
            accounts = self.config_data["accounts"]

            print(f"\n🏦 AVAILABLE AWS ACCOUNTS:")
            print("=" * 80)

            account_list = []

            for i, (account_name, account_data) in enumerate(accounts.items(), 1):
                account_id = account_data.get("account_id", "Unknown")
                email = account_data.get("email", "Unknown")

                account_list.append(
                    {
                        "name": account_name,
                        "account_id": account_id,
                        "email": email,
                        "data": account_data,
                    }
                )

                print(f"  {i}. {account_name}: {account_id} ({email})")

            # Selection prompt
            print("\nAccount Selection Options:")
            print("  • Single accounts: 1,3,5")
            print("  • Ranges: 1-3")
            print("  • Mixed: 1-2,4")
            print("  • All accounts: 'all' or press Enter")
            print("  • Cancel: 'cancel' or 'quit'")

            selection = input("\n🔢 Select accounts to process: ").strip().lower()

            if selection in ["cancel", "quit"]:
                self.log_operation("INFO", "EBS cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return

            # Process account selection
            selected_accounts = {}
            if not selection or selection == "all":
                selected_accounts = accounts
                self.log_operation("INFO", f"All accounts selected: {len(accounts)}")
                print(f"✅ Selected all {len(accounts)} accounts")
            else:
                try:
                    parts = []
                    for part in selection.split(","):
                        if "-" in part:
                            start, end = map(int, part.split("-"))
                            if start < 1 or end > len(account_list):
                                raise ValueError(
                                    f"Range {part} out of bounds (1-{len(account_list)})"
                                )
                            parts.extend(range(start, end + 1))
                        else:
                            num = int(part)
                            if num < 1 or num > len(account_list):
                                raise ValueError(
                                    f"Selection {part} out of bounds (1-{len(account_list)})"
                                )
                            parts.append(num)

                    for idx in parts:
                        account = account_list[idx - 1]
                        selected_accounts[account["name"]] = account["data"]

                    if not selected_accounts:
                        raise ValueError("No valid accounts selected")

                    self.log_operation(
                        "INFO", f"Selected accounts: {list(selected_accounts.keys())}"
                    )
                    print(
                        f"✅ Selected {len(selected_accounts)} accounts: {', '.join(selected_accounts.keys())}"
                    )

                except ValueError as e:
                    self.log_operation("ERROR", f"Invalid account selection: {e}")
                    print(f"❌ Invalid selection: {e}")
                    return

            regions = self.user_regions

            # Calculate total operations
            total_operations = len(selected_accounts) * len(regions)

            print(f"\n🎯 CLEANUP CONFIGURATION")
            print("=" * 80)
            print(f"🏦 Selected accounts: {len(selected_accounts)}")
            print(f"🌍 Regions per account: {len(regions)}")
            print(f"📋 Total operations: {total_operations}")
            print(f"🗑️  Target: Available EBS volumes + All snapshots")
            print(f"⏭️  Skipped: In-use volumes (attached to instances)")
            print("=" * 80)

            # Confirmation
            print(f"\n⚠️  WARNING: This will delete:")
            print(f"    • ALL available (unattached) EBS volumes")
            print(f"    • ALL EBS snapshots owned by the account")
            print(
                f"    • Across {len(selected_accounts)} accounts in {len(regions)} regions"
            )
            print(f"    • In-use volumes will be SKIPPED")
            print(f"    This action CANNOT be undone!")

            confirm1 = input(f"\nContinue with cleanup? (y/n): ").strip().lower()
            self.log_operation("INFO", f"First confirmation: '{confirm1}'")

            if confirm1 not in ["y", "yes"]:
                self.log_operation("INFO", "Ultra cleanup cancelled by user")
                print("❌ Cleanup cancelled")
                return

            confirm2 = input(f"Are you sure? Type 'yes' to confirm: ").strip().lower()
            self.log_operation("INFO", f"Final confirmation: '{confirm2}'")

            if confirm2 != "yes":
                self.log_operation(
                    "INFO", "Ultra cleanup cancelled at final confirmation"
                )
                print("❌ Cleanup cancelled")
                return

            # Start cleanup
            print(f"\n💥 STARTING CLEANUP...")
            self.log_operation(
                "INFO",
                f"🚨 CLEANUP INITIATED - {len(selected_accounts)} accounts, {len(regions)} regions",
            )

            start_time = time.time()

            successful_tasks = 0
            failed_tasks = 0

            # Create tasks list
            tasks = []
            for account_name, account_data in selected_accounts.items():
                for region in regions:
                    tasks.append((account_name, account_data, region))

            # Process each task sequentially
            for i, (account_name, account_data, region) in enumerate(tasks, 1):
                print(f"\n[{i}/{len(tasks)}] Processing {account_name} in {region}...")

                try:
                    success = self.cleanup_account_region(
                        account_name, account_data, region
                    )
                    if success:
                        successful_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    self.log_operation(
                        "ERROR", f"Task failed for {account_name} ({region}): {e}"
                    )
                    print(f"❌ Task failed for {account_name} ({region}): {e}")

            end_time = time.time()
            total_time = int(end_time - start_time)

            # Calculate storage freed
            total_gb_freed = sum(
                v["size"] for v in self.cleanup_results["deleted_volumes"]
            )
            total_snapshot_gb_freed = sum(
                s["volume_size"] for s in self.cleanup_results["deleted_snapshots"]
            )
            total_storage_freed = total_gb_freed + total_snapshot_gb_freed

            # Display final results
            print(f"\n💥" + "=" * 25 + " CLEANUP COMPLETE " + "=" * 25)
            print(f"⏱️  Total execution time: {total_time} seconds")
            print(f"✅ Successful operations: {successful_tasks}")
            print(f"❌ Failed operations: {failed_tasks}")
            print(
                f"💾 Volumes deleted: {len(self.cleanup_results['deleted_volumes'])} ({total_gb_freed} GB)"
            )
            print(
                f"📸 Snapshots deleted: {len(self.cleanup_results['deleted_snapshots'])} ({total_snapshot_gb_freed} GB)"
            )
            print(f"💰 Total storage freed: {total_storage_freed} GB")
            print(
                f"⏭️  Volumes skipped (in-use): {len(self.cleanup_results['skipped_volumes'])}"
            )
            print(
                f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}"
            )

            self.log_operation("INFO", f"CLEANUP COMPLETED")
            self.log_operation("INFO", f"Execution time: {total_time} seconds")
            self.log_operation(
                "INFO",
                f"Volumes deleted: {len(self.cleanup_results['deleted_volumes'])} ({total_gb_freed} GB)",
            )
            self.log_operation(
                "INFO",
                f"Snapshots deleted: {len(self.cleanup_results['deleted_snapshots'])} ({total_snapshot_gb_freed} GB)",
            )

            # Show account summary
            if (
                self.cleanup_results["deleted_volumes"]
                or self.cleanup_results["deleted_snapshots"]
            ):
                print(f"\n📊 Deletion Summary by Account:")

                account_summary = {}
                for volume in self.cleanup_results["deleted_volumes"]:
                    account = volume["account_name"]
                    if account not in account_summary:
                        account_summary[account] = {
                            "volumes": 0,
                            "snapshots": 0,
                            "gb": 0,
                            "regions": set(),
                        }
                    account_summary[account]["volumes"] += 1
                    account_summary[account]["gb"] += volume["size"]
                    account_summary[account]["regions"].add(volume["region"])

                for snapshot in self.cleanup_results["deleted_snapshots"]:
                    account = snapshot["account_name"]
                    if account not in account_summary:
                        account_summary[account] = {
                            "volumes": 0,
                            "snapshots": 0,
                            "gb": 0,
                            "regions": set(),
                        }
                    account_summary[account]["snapshots"] += 1
                    account_summary[account]["gb"] += snapshot["volume_size"]
                    account_summary[account]["regions"].add(snapshot["region"])

                for account, summary in account_summary.items():
                    regions_list = ", ".join(sorted(summary["regions"]))
                    print(f"   🏦 {account}:")
                    print(f"      💾 Volumes: {summary['volumes']}")
                    print(f"      📸 Snapshots: {summary['snapshots']}")
                    print(f"      💰 Storage freed: {summary['gb']} GB")
                    print(f"      🌍 Regions: {regions_list}")

            # Show failures if any
            if self.cleanup_results["failed_deletions"]:
                print(f"\n❌ Failed Deletions:")
                for failure in self.cleanup_results["failed_deletions"][:10]:
                    print(
                        f"   • {failure['resource_type']} {failure['resource_id']} in {failure['account_name']} ({failure['region']})"
                    )
                    print(f"     Error: {failure['error']}")

                if len(self.cleanup_results["failed_deletions"]) > 10:
                    remaining = len(self.cleanup_results["failed_deletions"]) - 10
                    print(f"   ... and {remaining} more failures (see detailed report)")

            # Save report
            print(f"\n📄 Saving cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                print(f"✅ Cleanup report saved to: {report_file}")

            print(f"✅ Session log saved to: {self.log_filename}")

            print(f"\n💥 CLEANUP COMPLETE! 💥")
            print("🚨" * 30)

        except Exception as e:
            self.log_operation("ERROR", f"FATAL ERROR in cleanup execution: {str(e)}")
            print(f"\n❌ FATAL ERROR: {e}")
            import traceback

            traceback.print_exc()
            raise


def main():
    """Main function"""
    try:
        manager = UltraEBSVolumeCleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
