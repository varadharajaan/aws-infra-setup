# Ultra Route53 Cleanup Manager

## Overview

The **Ultra Route53 Cleanup Manager** is a comprehensive tool designed to safely and efficiently clean up all Route53 resources across multiple AWS accounts. It provides intelligent resource deletion with proper dependency handling and safety protections.

## Features

### ✅ Supported Resources for Deletion

1. **Hosted Zones**
   - Public hosted zones
   - Private hosted zones
   - Automatic VPC disassociation for private zones

2. **DNS Record Sets**
   - A records (IPv4 addresses)
   - AAAA records (IPv6 addresses)
   - CNAME records (canonical names)
   - MX records (mail exchange)
   - TXT records (text records)
   - PTR records (pointer records)
   - SRV records (service records)
   - SPF records (sender policy framework)
   - CAA records (certification authority authorization)
   - DS records (delegation signer)

3. **Health Checks**
   - All HTTP/HTTPS/TCP health checks
   - Calculated health checks
   - CloudWatch alarm-based health checks

4. **Traffic Management**
   - Traffic policies (all versions)
   - Traffic policy instances

5. **Logging & Configuration**
   - Query logging configurations
   - Reusable delegation sets

6. **DNSSEC**
   - DNSSEC configurations are handled during zone deletion

### 🛡️ Safety Protections

#### What is PRESERVED (NOT deleted):

- **VPCs**: VPCs associated with private hosted zones are only disassociated, never deleted
- **Security Groups**: Not touched by this tool
- **Network Infrastructure**: Subnets, route tables, internet gateways, NAT gateways, etc.
- **Managed Records**: NS and SOA records are automatically handled during zone deletion

#### Smart Dependency Handling:

1. **Query Logging Configs** → Deleted first
2. **Traffic Policy Instances** → Deleted before policies
3. **Traffic Policies** → All versions deleted
4. **Hosted Zones** → VPCs disassociated, then records deleted, then zones
5. **Health Checks** → Deleted after zones (with retry logic for in-use checks)
6. **Reusable Delegation Sets** → Deleted last (if not in use)

## Installation

### Prerequisites

```bash
# Python 3.7 or higher required
python --version

# Install required dependencies
pip install boto3 botocore
```

### Dependencies

The script requires:
- `boto3`: AWS SDK for Python
- `botocore`: Low-level AWS client
- `root_iam_credential_manager.py`: For credential management (must be in same directory)

## Configuration

### AWS Credentials Setup

The tool uses the `root_iam_credential_manager` for credential management. Ensure you have:

1. **Root accounts configuration file**: `~/.aws_automation/aws_accounts_config.json`

```json
{
  "accounts": {
    "production-account": {
      "account_id": "123456789012",
      "email": "prod@example.com",
      "access_key": "AKIAIOSFODNN7EXAMPLE",
      "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
      "users_per_account": 3
    },
    "development-account": {
      "account_id": "123456789013",
      "email": "dev@example.com",
      "access_key": "AKIAIOSFODNN7EXAMPLE2",
      "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY2",
      "users_per_account": 2
    }
  },
  "user_settings": {
    "user_regions": ["us-east-1", "us-west-2", "eu-west-1"]
  }
}
```

## Usage

### Interactive Mode (Recommended)

```bash
python ultra_cleanup_route53.py
```

The interactive mode will:

1. **Display all available AWS accounts**
2. **Allow you to select specific accounts or all accounts**
3. **Offer a DRY-RUN option** (highly recommended for first run)
4. **Require explicit confirmation** for actual deletions
5. **Show real-time progress** with colored output
6. **Generate comprehensive reports**

### Example Workflow

```
🚀 ULTRA ROUTE53 CLEANUP MANAGER
================================================================================

📋 Available AWS Accounts:
  1. production-account (ID: 123456789012)
  2. staging-account (ID: 123456789013)
  3. development-account (ID: 123456789014)

🔍 Select accounts to clean:
  Enter account numbers (comma-separated, or 'all' for all accounts)
Your choice: 1,3

🔒 Run in DRY-RUN mode? (recommended for first run)
  Dry-run will show what would be deleted without making changes
Dry-run? (yes/no) [yes]: yes

🔍 Running in DRY-RUN mode...
```

### Dry-Run Mode

**Always run in dry-run mode first!**

```bash
# Dry-run will:
# ✅ Show exactly what would be deleted
# ✅ Not make any actual changes
# ✅ Generate a complete report
# ✅ Help you verify the cleanup scope
```

Example dry-run output:
```
[DRY-RUN] Would delete A record: api.example.com
[DRY-RUN] Would delete AAAA record: www.example.com
[DRY-RUN] Would disassociate VPC vpc-12345678 from zone Z1234567890ABC
[DRY-RUN] Would delete hosted zone: example.com
[DRY-RUN] Would delete health check: 1234567890abc
```

### Actual Cleanup

When ready to perform actual cleanup:

1. Select accounts
2. Choose **NO** for dry-run
3. Type **DELETE** to confirm

```
⚠️  WARNING: This will DELETE Route53 resources!
⚠️  VPCs will NOT be deleted (only disassociated from zones)
Type 'DELETE' to confirm: DELETE
```

## Outputs

### 1. Real-time Console Output

Colored, real-time feedback showing:
- 🔍 Resources being scanned
- ✅ Successful deletions
- ⚠️ Warnings and skipped resources
- ❌ Errors and failures

### 2. Detailed Log File

Location: `~/.aws_automation/aws/route53/route53_cleanup_YYYYMMDD_HHMMSS.log`

Contains:
- Timestamp for each action
- Detailed error messages
- Resource IDs and names
- Full operation history

Example:
```
[2025-12-01 10:30:15] [INFO] Found 5 hosted zones
[2025-12-01 10:30:16] [INFO] Processing hosted zone: example.com (Z1234567890ABC) - Private: False
[2025-12-01 10:30:17] [INFO] Deleted A record: api.example.com
[2025-12-01 10:30:18] [INFO] Deleted hosted zone: example.com (Z1234567890ABC)
```

### 3. JSON Summary Report

Location: `~/.aws_automation/aws/route53/reports/route53_cleanup_summary_YYYYMMDD_HHMMSS.json`

Contains:
- Execution metadata
- Counts of deleted resources by type
- Complete list of all operations
- Error details and failed deletions

Example structure:
```json
{
  "execution_timestamp": "20251201_103000",
  "execution_time": "2025-12-01 10:30:00",
  "user": "varadharajaan",
  "accounts_processed": ["production-account", "development-account"],
  "summary": {
    "total_hosted_zones_deleted": 10,
    "total_record_sets_deleted": 45,
    "total_health_checks_deleted": 3,
    "total_traffic_policies_deleted": 2,
    "total_query_logging_configs_deleted": 1,
    "total_vpcs_disassociated": 5,
    "total_failed_deletions": 0,
    "total_errors": 0
  },
  "details": {
    "deleted_hosted_zones": [
      {
        "zone_id": "Z1234567890ABC",
        "name": "example.com",
        "private": false
      }
    ],
    "deleted_record_sets": [
      {
        "zone_id": "Z1234567890ABC",
        "name": "api.example.com",
        "type": "A"
      }
    ]
  }
}
```

## Cleanup Order & Logic

The tool follows this intelligent cleanup order to handle dependencies:

1. **Query Logging Configurations** (no dependencies)
2. **Traffic Policy Instances** (depend on policies)
3. **Traffic Policies** (all versions, depend on instances being gone)
4. **Hosted Zones** (includes record set deletion and VPC disassociation)
   - Disassociate all VPCs from private zones
   - Delete all deletable record sets (A, AAAA, CNAME, etc.)
   - NS and SOA records are handled automatically
   - Delete the hosted zone
5. **Health Checks** (may be in use by zones, with retry logic)
6. **Reusable Delegation Sets** (may be in use by zones)

## Error Handling

### Retry Logic

- **Health Checks**: Automatically retried after zone deletion (may be in use initially)
- **Rate Limiting**: Built-in delays between API calls to avoid throttling
- **Graceful Failures**: Individual resource failures don't stop the entire cleanup

### Common Issues & Solutions

#### Issue: "HealthCheckInUse"
**Solution**: The tool automatically retries health check deletion after zones are deleted

#### Issue: "InvalidChangeBatch" for record sets
**Solution**: NS/SOA records and alias records are skipped automatically

#### Issue: "DelegationSetInUse"
**Solution**: Delegation sets in use are logged but not deleted

#### Issue: Rate limiting / throttling
**Solution**: Built-in delays between operations (configurable if needed)

## Safety Features

### 🔒 Multiple Confirmation Steps

1. Account selection required
2. Dry-run option offered
3. Explicit "DELETE" confirmation for actual deletion
4. Clear warnings before destructive operations

### 🛡️ Resource Protection

- VPCs are **NEVER deleted** - only disassociated
- Default NS/SOA records handled automatically during zone deletion
- Invalid record types are automatically skipped
- Managed records are protected

### 📊 Complete Audit Trail

- Every action logged with timestamp
- Complete JSON report of all operations
- Success/failure tracking for each resource
- Error details captured for troubleshooting

## Best Practices

### Before Running

1. ✅ **Always run dry-run first** to understand the scope
2. ✅ **Review the dry-run output** carefully
3. ✅ **Verify you have proper backups** if needed
4. ✅ **Check if any zones are critical** for production services
5. ✅ **Ensure you have proper AWS permissions**

### During Cleanup

1. ✅ Monitor the console output for errors
2. ✅ Check the log file if issues occur
3. ✅ Don't interrupt the process (Ctrl+C if necessary, but avoid)

### After Cleanup

1. ✅ Review the summary report
2. ✅ Check for any failed deletions
3. ✅ Verify VPCs are intact (only disassociated, not deleted)
4. ✅ Clean up CloudWatch log groups if desired (not handled by this tool)

## Required AWS Permissions

The IAM user/role needs these Route53 permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:GetHostedZone",
        "route53:DeleteHostedZone",
        "route53:ListResourceRecordSets",
        "route53:ChangeResourceRecordSets",
        "route53:ListHealthChecks",
        "route53:DeleteHealthCheck",
        "route53:ListTrafficPolicies",
        "route53:ListTrafficPolicyVersions",
        "route53:DeleteTrafficPolicy",
        "route53:ListTrafficPolicyInstances",
        "route53:DeleteTrafficPolicyInstance",
        "route53:ListQueryLoggingConfigs",
        "route53:DeleteQueryLoggingConfig",
        "route53:ListReusableDelegationSets",
        "route53:DeleteReusableDelegationSet",
        "route53:DisassociateVPCFromHostedZone",
        "route53:GetChange"
      ],
      "Resource": "*"
    }
  ]
}
```

## Troubleshooting

### Script won't start

**Check:**
- Python version (3.7+)
- Dependencies installed (`pip install boto3`)
- Credential file exists and is valid

### No resources found

**Possible reasons:**
- No Route53 resources exist in the account
- Credentials lack proper permissions
- Wrong account selected

### Partial failures

**What to do:**
- Check the log file for specific errors
- Review the summary report's "failed_deletions" section
- Re-run the cleanup (it will skip already-deleted resources)

### Rate limiting errors

**Solution:**
- The script includes built-in rate limiting
- If you still hit limits, you can increase delays in the code
- Wait a few minutes and re-run

## Advanced Usage

### Programmatic Usage

You can also use the manager programmatically:

```python
from ultra_cleanup_route53 import UltraCleanupRoute53Manager

# Initialize
manager = UltraCleanupRoute53Manager()

# Load credentials
credentials = {
    'access_key': 'AKIAIOSFODNN7EXAMPLE',
    'secret_key': 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
}

# Clean up specific account
results = manager.cleanup_account_route53_resources(
    account_name='my-account',
    credentials=credentials,
    dry_run=True  # Set to False for actual cleanup
)

# Generate report
manager.generate_summary_report()
```

### Customization

You can modify the script to:
- Add additional record types to delete
- Change rate limiting delays
- Customize logging format
- Add email notifications
- Integrate with CI/CD pipelines

## Comparison with AWS Console

| Feature | This Tool | AWS Console |
|---------|-----------|-------------|
| Bulk zone deletion | ✅ Yes | ❌ No (one by one) |
| Automatic record deletion | ✅ Yes | ❌ Manual |
| VPC disassociation | ✅ Automatic | ❌ Manual |
| Multi-account support | ✅ Yes | ❌ Account switching |
| Dry-run mode | ✅ Yes | ❌ No |
| Comprehensive reporting | ✅ Yes | ❌ No |
| Dependency handling | ✅ Automatic | ❌ Manual |
| Audit trail | ✅ Complete | ❌ Limited |

## Important Notes

### ⚠️ Route53 is Global

- Route53 is a global service (not regional)
- Resources are accessible from any region
- All zones and records are managed globally
- VPC associations are regional for private zones

### ⚠️ DNS Propagation

- After deletion, DNS changes may take time to propagate
- TTL settings affect how quickly changes are visible
- Consider DNS caching by resolvers and clients

### ⚠️ No Undo

- **Deleted resources cannot be recovered**
- Always backup critical DNS configurations
- Export zone files before deletion if needed

### ⚠️ Cost Implications

- Hosted zones have monthly costs ($0.50/zone)
- Health checks have costs ($0.50/health check)
- Query charges apply for DNS queries
- Deleting resources stops charges

## Related Tools

This tool is part of the AWS Ultra Cleanup suite:

- `ultra_cleanup_vpc.py` - VPC resource cleanup
- `ultra_cleanup_rds.py` - RDS resource cleanup
- `ultra_cleanup_route53.py` - Route53 resource cleanup (this tool)

## Support & Contribution

For issues, questions, or contributions:
- Review the log files for detailed error information
- Check the summary report for operation results
- Ensure credentials have proper permissions
- Verify AWS service health status

## License

Created by: varadharajaan
Created on: 2025-12-01

## Changelog

### Version 1.0.0 (2025-12-01)
- Initial release
- Support for all major Route53 resource types
- Dry-run mode implementation
- Multi-account support
- Comprehensive logging and reporting
- VPC disassociation (without VPC deletion)
- Intelligent dependency handling
- Health check retry logic
