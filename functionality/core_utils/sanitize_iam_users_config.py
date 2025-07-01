import json
import os
import glob
import re
from datetime import datetime
import sys


def sanitize_credentials(input_file=None, output_dir=None):
    """
    Sanitize AWS IAM credentials file by masking sensitive information
    Keeps first 5 and last 5 characters of sensitive values

    Args:
        input_file: Path to input credentials file
        output_dir: Directory to save sanitized file
    """
    # Find the latest credentials file if not provided
    if not input_file:
        iam_dir = "aws/iam"
        if not os.path.exists(iam_dir):
            print(f"❌ Directory {iam_dir} not found")
            return False

        # Find the latest iam_users_credentials file
        pattern = os.path.join(iam_dir, "iam_users_credentials_*.json")
        files = glob.glob(pattern)

        if not files:
            print(f"❌ No credential files found in {iam_dir}")
            return False

        # Sort by timestamp in filename
        files.sort(reverse=True)
        input_file = files[0]

    # Set output directory to current directory if not provided
    if not output_dir:
        output_dir = os.getcwd()

    print(f"🔍 Processing file: {input_file}")

    try:
        # Load credentials file
        with open(input_file, 'r') as f:
            creds_data = json.load(f)

        # Get original metadata
        created_date = creds_data.get("created_date", "")
        created_time = creds_data.get("created_time", "")
        created_by = creds_data.get("created_by", "")
        total_users = creds_data.get("total_users", 0)

        # Create sanitized data structure
        sanitized_data = {
            "created_date": created_date,
            "created_time": created_time,
            "created_by": created_by,
            "total_users": total_users,
            "accounts": {}
        }

        # Function to mask sensitive values
        def mask(value, keep_ends=True):
            if not value or len(value) <= 12:  # Too short to mask effectively
                return "********"

            if keep_ends:
                return value[:5] + "*" * (len(value) - 10) + value[-5:]
            else:
                return "sanitized" + value[-3:] if len(value) > 3 else "sanitized"

        # Process each account
        for account_id, account_info in creds_data.get("accounts", {}).items():
            sanitized_data["accounts"][account_id] = {
                "account_id": account_info.get("account_id", ""),
                "account_email": mask(account_info.get("account_email", ""), keep_ends=False),
                "users": []
            }

            # Process each user
            for user in account_info.get("users", []):
                sanitized_user = {
                    "username": user.get("username", ""),
                    "real_user": {
                        "first_name": user.get("real_user", {}).get("first_name", ""),
                        "last_name": user.get("real_user", {}).get("last_name", ""),
                        "full_name": user.get("real_user", {}).get("full_name", ""),
                        "email": mask(user.get("real_user", {}).get("email", ""), keep_ends=False)
                    },
                    "region": user.get("region", ""),
                    "access_key_id": mask(user.get("access_key_id", "")),
                    "secret_access_key": mask(user.get("secret_access_key", "")),
                    "console_password": mask("password123", keep_ends=False),
                    "console_url": user.get("console_url", "")
                }
                sanitized_data["accounts"][account_id]["users"].append(sanitized_user)

        # Create output filename with current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"sanitized_iam_users_credentials_{timestamp}.json"
        output_path = os.path.join(output_dir, output_filename)

        # Write sanitized data to file
        with open(output_path, 'w') as f:
            json.dump(sanitized_data, f, indent=2)

        print(f"✅ Successfully sanitized credentials")
        print(f"📄 Sanitized file saved to: {output_path}")
        return True

    except Exception as e:
        print(f"❌ Error sanitizing credentials: {str(e)}")
        return False


if __name__ == "__main__":
    # Parse command-line arguments if provided
    input_file = None
    output_dir = None

    if len(sys.argv) > 1:
        input_file = sys.argv[1]

    if len(sys.argv) > 2:
        output_dir = sys.argv[2]

    # Run sanitization
    sanitize_credentials(input_file, output_dir)