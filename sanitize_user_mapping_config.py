import json
from datetime import datetime
from text_symbols import Symbols

# Load JSON file
with open("user_mapping.json") as f:
    data = json.load(f)

# Masking function - minimal masking (only middle 2-3 chars)
def mask(value, stars=6):
    if not isinstance(value, str):
        return "***"
    if len(value) <= 4:
        return value  # Keep short values as-is
    elif len(value) <= 8:
        # Medium: keep first 3, mask 2, keep rest
        return value[:3] + "**" + value[5:]
    else:
        # Long: keep first 4, mask 3, keep rest
        return value[:4] + "***" + value[7:]

def mask_email(email):
    if not isinstance(email, str) or '@' not in email:
        return email
    user, domain = email.split('@', 1)
    if len(user) <= 4:
        return email  # Keep short emails as-is
    elif len(user) <= 8:
        return user[:3] + "**" + user[5:] + "@" + domain
    else:
        return user[:4] + "***" + user[7:] + "@" + domain

# Mask fields in user_mappings
for user_id, user_info in data.get("user_mappings", {}).items():
    if "first_name" in user_info:
        user_info["first_name"] = mask(user_info["first_name"])
    if "last_name" in user_info:
        user_info["last_name"] = mask(user_info["last_name"])
    if "email" in user_info:
        user_info["email"] = mask_email(user_info["email"])

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

print("[OK] Sanitized user mapping saved to 'sanitized_users_mapping.json'")
