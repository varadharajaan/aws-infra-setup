import boto3
import json
import os
from text_symbols import Symbols

def load_accounts_config(config_file="aws_accounts_config.json"):
    if not os.path.exists(config_file):
        print(f"{Symbols.ERROR} Config file {config_file} not found.")
        return None
    with open(config_file, "r") as f:
        return json.load(f)

def select_account(accounts):
    print("[PACKAGE] Available Accounts:")
    index_map = {}
    for idx, key in enumerate(accounts.keys(), start=1):
        print(f" {idx}. {key}")
        index_map[str(idx)] = key

    selection = input("\n👉 Enter account number to fetch AMI from: ").strip()
    selected = index_map.get(selection)
    if not selected:
        print("[ERROR] Invalid selection.")
        return None
    return selected

def get_boto3_session(account_key):
    for suffix in ["", "-bk"]:
        profile = f"{account_key}{suffix}"
        try:
            session = boto3.Session(profile_name=profile)
            session.client("sts").get_caller_identity()
            print(f"{Symbols.OK} Using profile: {profile}")
            return session
        except Exception as e:
            print(f"{Symbols.WARN} Failed with profile '{profile}': {e}")
    print("[ERROR] No working profile found.")
    return None

def get_latest_amazon_linux_3_ami(region, session):
    ec2 = session.client("ec2", region_name=region)
    try:
        response = ec2.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": ["al2023-ami-*-x86_64"]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "architecture", "Values": ["x86_64"]},
                {"Name": "virtualization-type", "Values": ["hvm"]},
                {"Name": "root-device-type", "Values": ["ebs"]}
            ]
        )
        images = response["Images"]
        # Prefer AMIs with ec2-instance-connect in name or description
        preferred = [
            img for img in images
            if "ec2-instance-connect" in img.get("Name", "").lower() or
               "ec2-instance-connect" in img.get("Description", "").lower()
        ]
        images = preferred if preferred else images
        images = sorted(images, key=lambda x: x["CreationDate"], reverse=True)
        return images[0]["ImageId"] if images else None
    except Exception as e:
        print(f"[{region}] {Symbols.ERROR} Failed to fetch AL2023 AMI: {e}")
        return None

def get_latest_amazon_linux_2_ami(region, session):
    ec2 = session.client("ec2", region_name=region)
    try:
        response = ec2.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": ["amzn2-ami-hvm-*-x86_64-gp2"]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "architecture", "Values": ["x86_64"]},
                {"Name": "virtualization-type", "Values": ["hvm"]},
                {"Name": "root-device-type", "Values": ["ebs"]}
            ]
        )
        images = response["Images"]
        images = sorted(images, key=lambda x: x["CreationDate"], reverse=True)
        return images[0]["ImageId"] if images else None
    except Exception as e:
        print(f"[{region}] {Symbols.ERROR} Failed to fetch AL2 AMI: {e}")
        return None

def main():
    config = load_accounts_config()
    if not config:
        return

    accounts = config.get("accounts", {})
    selected_account = select_account(accounts)
    if not selected_account:
        return

    session = get_boto3_session(selected_account)
    if not session:
        return

    regions = config.get("user_settings", {}).get("user_regions", [])
    if not regions:
        print("[ERROR] No regions found in user_settings.user_regions.")
        return

    al2023_ami_mapping = {}
    al2_ami_mapping = {}
    print("\n[SCAN] Fetching latest Amazon Linux 2023 and Amazon Linux 2 AMIs:")
    for region in regions:
        al2023_ami = get_latest_amazon_linux_3_ami(region, session)
        al2_ami = get_latest_amazon_linux_2_ami(region, session)
        if al2023_ami:
            al2023_ami_mapping[region] = al2023_ami
        if al2_ami:
            al2_ami_mapping[region] = al2_ami

    print("\n[OK] Latest Amazon Linux 2023 AMI Mapping (with EC2 Instance Connect):")
    for region, ami in al2023_ami_mapping.items():
        print(f'    "{region}": "{ami}",')

    print(f"\n{Symbols.OK} Latest Amazon Linux 2 AMI Mapping:")
    for region, ami in al2_ami_mapping.items():
        print(f'    "{region}": "{ami}",')

if __name__ == "__main__":
    main()