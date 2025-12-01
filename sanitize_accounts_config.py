import json
from datetime import datetime

# Load the configuration file
with open("aws_accounts_config.json") as f:
    config = json.load(f)


# Function to mask a sensitive string, showing only first 3 and last 3 characters
def mask(value, stars=6):
    if not isinstance(value, str):
        return value
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * stars + value[-3:]


# Fields to mask at root level of each account
fields_to_mask = [
    "access_key",
    "secret_key",
    "backup_access_key",
    "backup_secret_key",
    "password",
    "canonical_user_id"
]

# Fields inside billing address to mask (if needed)
address_fields_to_mask = ["street", "city", "state", "zip_code", "country"]

# Mask values in each account
for acc in config.get("accounts", {}).values():
    for field in fields_to_mask:
        if field in acc:
            acc[field] = mask(acc[field])

    # If billing address is present, mask each part
    billing_addr = acc.get("Billing", {}).get("billing_address", {})
    for field in address_fields_to_mask:
        if field in billing_addr:
            billing_addr[field] = mask(billing_addr[field])

# Add metadata
current_time = datetime.now()
created_by = 'varadharajaan'
timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
config["metadata"] = {
    "created_at": timestamp,
    "sanitized": True,
    "created_by": created_by,
    "source_file": "aws_accounts_config.json"
}

# Save sanitized configuration
with open("sanitized_aws_accounts_config.json", "w") as f:
    json.dump(config, f, indent=2)

print(f"[OK] Sanitized config saved to 'sanitized_aws_accounts_config.json' at {timestamp}")
