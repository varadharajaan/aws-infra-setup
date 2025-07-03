import boto3
import json
import os

# Load account config
def load_accounts_config(config_file="aws_accounts_config.json"):
    if not os.path.exists(config_file):
        print(f"❌ Config file {config_file} not found.")
        return None
    with open(config_file, "r") as f:
        return json.load(f)

# Ask user to select one account
def select_account(accounts):
    print("📦 Available Accounts:")
    index_map = {}
    for idx, key in enumerate(accounts.keys(), start=1):
        print(f" {idx}. {key}")
        index_map[str(idx)] = key

    selection = input("\n👉 Enter account number to fetch AMI from: ").strip()
    selected = index_map.get(selection)
    if not selected:
        print("❌ Invalid selection.")
        return None
    return selected

# Try to use the profile, fallback to -bk
def get_boto3_session(account_key):
    for suffix in ["", "-bk"]:
        profile = f"{account_key}{suffix}"
        try:
            session = boto3.Session(profile_name=profile)
            # Force test to confirm it's valid
            session.client("sts").get_caller_identity()
            print(f"✅ Using profile: {profile}")
            return session
        except Exception as e:
            print(f"⚠️ Failed with profile '{profile}': {e}")
    print("❌ No working profile found.")
    return None

# Get latest Amazon Linux 3 AMI per region
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
        images = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
        return images[0]["ImageId"] if images else None
    except Exception as e:
        print(f"[{region}] ❌ Failed to fetch AMI: {e}")
        return None

# Main execution
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

    regions = config.get("user_settings", {}).get("user_regions", [
        "us-east-1", "us-east-2", "us-west-1", "us-west-2", "ap-south-1"
    ])

    regions += [r for r in ["eu-north-1", "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3", "ca-central-1"] if r not in regions]

    ami_mapping = {}
    print("\n🔄 Fetching latest Amazon Linux 3 AMIs:")
    for region in regions:
        ami = get_latest_amazon_linux_3_ami(region, session)
        if ami:
            ami_mapping[region] = ami

    print("\n✅ Latest Amazon Linux 3 AMI Mapping:")
    for region, ami in ami_mapping.items():
        print(f"{region}: {ami}")

if __name__ == "__main__":
    main()
