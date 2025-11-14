import json
from datetime import datetime

# Load JSON file
with open("user_mapping.json") as f:
    data = json.load(f)

# Masking function (first 3 + 6 asterisks + last 3)
def mask(value, stars=6):
    if not isinstance(value, str) or len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * stars + value[-3:]

# Mask fields in user_mappings
for user_id, user_info in data.get("user_mappings", {}).items():
    for field in ["first_name", "last_name", "email"]:
        if field in user_info:
            user_info[field] = mask(user_info[field])

# Mask the organization in metadata
if "metadata" in data and "organization" in data["metadata"]:
    data["metadata"]["organization"] = mask(data["metadata"]["organization"])

# Add/Update sanitization metadata
data["metadata"]["sanitized"] = True
data["metadata"]["sanitized_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
data["metadata"]["sanitized_by"] = "varadharajaan"

# Save the sanitized output
with open("sanitized_users_mapping.json", "w") as f:
    json.dump(data, f, indent=2)

print("✅ Sanitized user mapping saved to 'sanitized_users_mapping.json'")
