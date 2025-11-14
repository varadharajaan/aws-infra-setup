import glob
import json
import os
import re
import sys
from datetime import datetime


def sanitize_credentials(input_file=None, output_dir=None):
    """
    Sanitize AWS IAM credentials file by masking sensitive information.
    Masks access keys, passwords, personal identity, emails, and account ID in console URLs.
    """

    # Default directory & file pattern
    if not input_file:
        iam_dir = "aws/iam"
        if not os.path.exists(iam_dir):
            print(f"❌ Directory {iam_dir} not found")
            return False

        pattern = os.path.join(iam_dir, "iam_users_credentials_*.json")
        files = glob.glob(pattern)

        if not files:
            print(f"❌ No credential files found in {iam_dir}")
            return False

        # Sort by timestamp (reverse = latest first)
        files.sort(reverse=True)
        input_file = files[0]

    if not output_dir:
        output_dir = os.getcwd()

    print(f"🔍 Processing file: {input_file}")

    try:
        with open(input_file, "r") as f:
            creds_data = json.load(f)

        # Load metadata
        created_date = creds_data.get("created_date", "")
        created_time = creds_data.get("created_time", "")
        created_by = creds_data.get("created_by", "")
        total_users = creds_data.get("total_users", 0)

        # ----------- MASKING HELPERS ------------
        def mask(value, keep_ends=True, stars=6):
            if not isinstance(value, str) or not value:
                return "********"
            if len(value) <= 6:
                return "*" * len(value)
            if keep_ends:
                return value[:3] + "*" * stars + value[-3:]
            else:
                return "masked"

        def mask_email(email):
            if not isinstance(email, str) or "@" not in email:
                return "masked@masked.com"
            user, _ = email.split("@", 1)
            masked_user = user[:3] + "*" * 6 if len(user) > 3 else "***"
            return masked_user + "@masked.com"

        def mask_console_url(url):
            return re.sub(r"https://\d{12}", "https://************", url)

        # ----------- MAIN SANITIZATION ----------
        sanitized_data = {
            "created_date": created_date,
            "created_time": created_time,
            "created_by": created_by,
            "total_users": total_users,
            "sanitized": True,
            "sanitized_by": "varadharajaan",
            "sanitized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "accounts": {},
        }

        for account_id, account in creds_data.get("accounts", {}).items():
            sanitized_account = {
                "account_id": account.get("account_id", ""),
                "account_email": mask_email(account.get("account_email", "")),
                "users": [],
            }

            for user in account.get("users", []):
                real_user = user.get("real_user", {})
                sanitized_user = {
                    "username": user.get("username", ""),
                    "real_user": {
                        "first_name": mask(real_user.get("first_name", "")),
                        "last_name": mask(real_user.get("last_name", "")),
                        "full_name": mask(real_user.get("full_name", "")),
                        "email": mask_email(real_user.get("email", "")),
                    },
                    "region": user.get("region", ""),
                    "access_key_id": mask(user.get("access_key_id", "")),
                    "secret_access_key": mask(user.get("secret_access_key", "")),
                    "console_password": mask(
                        user.get("console_password", ""), keep_ends=False
                    ),
                    "console_url": mask_console_url(user.get("console_url", "")),
                }
                sanitized_account["users"].append(sanitized_user)

            sanitized_data["accounts"][account_id] = sanitized_account

        # Output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"sanitized_iam_users_credentials_{timestamp}.json"
        output_path = os.path.join(output_dir, output_filename)

        # Write to file
        with open(output_path, "w") as f:
            json.dump(sanitized_data, f, indent=2)

        print(f"✅ Successfully sanitized credentials")
        print(f"📄 Sanitized file saved to: {output_path}")
        return True

    except Exception as e:
        print(f"❌ Error during sanitization: {e}")
        return False


if __name__ == "__main__":
    input_file = None
    output_dir = None

    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_dir = sys.argv[2]

    sanitize_credentials(input_file, output_dir)
