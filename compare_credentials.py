#!/usr/bin/env python3

import json
import os


def compare_credential_files():
    """Compare credentials between different config files"""
    print("🔍 COMPARING CREDENTIAL FILES")
    print("=" * 60)

    # Files to check
    files_to_check = [
        "aws_accounts_config.json",
        "iam_users_credentials_20250606_001929.json",
        # Add any other credential files you might have
    ]

    for filename in files_to_check:
        print(f"\n📄 Checking: {filename}")
        if os.path.exists(filename):
            try:
                with open(filename, "r") as f:
                    data = json.load(f)

                print(f"✅ File exists and is valid JSON")

                # Look for account02 credentials
                if "accounts" in data and "account02" in data["accounts"]:
                    account02 = data["accounts"]["account02"]
                    access_key = account02.get("access_key", "Not found")
                    print(
                        f"🔑 account02 access_key: {access_key[:10]}...{access_key[-4:] if len(access_key) > 10 else access_key}"
                    )

                elif isinstance(data, dict):
                    # Check if it's a different structure
                    for key, value in data.items():
                        if isinstance(value, dict) and "access_key" in value:
                            access_key = value["access_key"]
                            print(
                                f"🔑 {key} access_key: {access_key[:10]}...{access_key[-4:] if len(access_key) > 10 else access_key}"
                            )
                        elif key == "account02" and isinstance(value, dict):
                            access_key = value.get("access_key", "Not found")
                            print(
                                f"🔑 account02 access_key: {access_key[:10]}...{access_key[-4:] if len(access_key) > 10 else access_key}"
                            )

                else:
                    print("🔍 Structure doesn't match expected format, showing keys:")
                    if isinstance(data, dict):
                        print(f"   Top-level keys: {list(data.keys())}")

            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON: {e}")
            except Exception as e:
                print(f"❌ Error reading file: {e}")
        else:
            print(f"❌ File not found")

    print(f"\n💡 RECOMMENDATIONS:")
    print(f"1. Use the same credential file that worked for EC2 creation")
    print(
        f"2. Update your cleanup script to use: iam_users_credentials_20250605_224146.json"
    )
    print(f"3. Or copy the working credentials to aws_accounts_config.json")


if __name__ == "__main__":
    compare_credential_files()
