import json
import re
from datetime import datetime

# Load the configuration file
with open("aws_accounts_config.json") as f:
    config = json.load(f)

# Function to mask sensitive values
def mask(value):
    return value[:5] + "*" * (len(value) - 10) + value[-5:]

# Mask access and secret keys
for acc in config["accounts"].values():
    acc["access_key"] = mask(acc["access_key"])
    acc["secret_key"] = mask(acc["secret_key"])

# Add timestamp
current_time = datetime.now()
created_by= 'varadharajaan'
timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
config["metadata"] = {
    "created_at": timestamp,
    "sanitized": True,  
    "created_by": created_by,
    "source_file": "aws_accounts_config.json"
}

# Save the sanitized configuration
with open("sanitized_aws_accounts_config.json", "w") as f:
    json.dump(config, f, indent=2)
    
print(f"Sanitized AWS accounts configuration has been saved to 'sanitized_aws_accounts_config.json' at {timestamp}")