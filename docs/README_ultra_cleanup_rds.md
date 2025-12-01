# Ultra RDS Cleanup Manager

Comprehensive cleanup tool for AWS RDS (Relational Database Service) resources across multiple accounts and regions.

**Author:** varadharajaan  
**Created:** 2025-11-24  
**Style:** Matches ultra_cleanup_eks.py

## 🎯 Features

### Resources Cleaned Up
- ✅ **RDS DB Instances** - All database instances
- ✅ **RDS DB Clusters** - Aurora clusters  
- ✅ **DB Snapshots** - Manual snapshots
- ✅ **Cluster Snapshots** - Aurora cluster snapshots
- ✅ **Automated Backups** - Retained automated backups
- ✅ **Snapshot Export Tasks** - Ongoing or completed exports
- ✅ **Event Subscriptions** - RDS event notifications
- ✅ **CloudWatch Alarms** - RDS-related alarms (AWS/RDS namespace)
- ✅ **CloudWatch Log Groups** - RDS logs (/aws/rds/*)
- ✅ **Custom Parameter Groups** - DB parameter groups (custom only)
- ✅ **Custom Cluster Parameter Groups** - Aurora parameter groups (custom only)
- ✅ **Custom Option Groups** - DB option groups (custom only)

### 🛡️ Protected Resources
- ❌ **DB Subnet Groups** - PRESERVED (not deleted as requested)
- ❌ **Default Security Groups** - PRESERVED (not touched)
- ❌ **Default VPC Subnets** - PRESERVED (not touched)
- ❌ **Default Parameter Groups** - PRESERVED (e.g., `default.mysql8.0`)
- ❌ **Default Option Groups** - PRESERVED (e.g., `default:mysql-8-0`)

## 📋 Prerequisites

### Python Dependencies
The script uses the `root_iam_credential_manager` module which should be in the same directory.

```bash
pip install boto3 botocore
```

### AWS Configuration
The script uses the `AWSCredentialManager` from `root_iam_credential_manager.py` to manage AWS accounts.

Ensure your AWS accounts config file exists (typically in `aws/accounts_config/root_accounts_config.json`):
```json
{
  "root_accounts": {
    "production-account": {
      "account_id": "123456789012",
      "email": "prod@example.com",
      "access_key": "AKIAXXXXXXXXXXXXXXXX",
      "secret_key": "your-secret-key-here",
      "account_key": "production-account"
    }
  },
  "user_settings": {
    "user_regions": [
      "us-east-1",
      "us-west-2",
      "eu-west-1"
    ]
  }
}
```

### Required IAM Permissions

The IAM user/role needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "rds:DescribeDBSnapshots",
        "rds:DescribeDBClusterSnapshots",
        "rds:DescribeDBInstanceAutomatedBackups",
        "rds:DescribeExportTasks",
        "rds:DescribeEventSubscriptions",
        "rds:DescribeDBParameterGroups",
        "rds:DescribeDBClusterParameterGroups",
        "rds:DescribeOptionGroups",
        "rds:DeleteDBInstance",
        "rds:DeleteDBCluster",
        "rds:DeleteDBSnapshot",
        "rds:DeleteDBClusterSnapshot",
        "rds:DeleteDBInstanceAutomatedBackup",
        "rds:CancelExportTask",
        "rds:DeleteEventSubscription",
        "rds:DeleteDBParameterGroup",
        "rds:DeleteDBClusterParameterGroup",
        "rds:DeleteOptionGroup",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:DeleteAlarms",
        "logs:DescribeLogGroups",
        "logs:DeleteLogGroup"
      ],
      "Resource": "*"
    }
  ]
}
```

## 🚀 Usage

### Basic Usage
```bash
python ultra_cleanup_rds.py
```

### Interactive Flow

1. **Select AWS Accounts**
   - Choose specific account(s) from your configuration
   - Or select all accounts

2. **Select Regions**
   - Choose specific region(s)
   - Or select all configured regions
   - Supports single, multiple (1,3,5), range (1-5), or all

3. **Confirm Deletion**
   - Type `DELETE` to confirm the operation
   - This is a safety measure to prevent accidental deletions

4. **Processing**
   - Script processes each account and region
   - Deletes resources in dependency-safe order
   - Progress is logged in real-time

5. **Review Reports**
   - Check the generated JSON report
   - Review the detailed log file

## 📊 Output

### Console Output
Real-time colored output showing:
- ✅ Successful deletions (green)
- ❌ Failed operations (red)
- ⚠️  Warnings and skipped items (yellow)
- 🛡️  Protected resources (yellow)
- 📊 Summary statistics (cyan)

### Log Files
Located in `aws/rds/`:
- `ultra_rds_cleanup_log_TIMESTAMP.log` - Detailed execution log
- `reports/ultra_rds_cleanup_report_TIMESTAMP.json` - Structured JSON report

### Report Structure
```json
{
  "metadata": {
    "cleanup_type": "ULTRA_RDS_CLEANUP",
    "cleanup_date": "2025-11-24",
    "cleanup_time": "10:30:45",
    "cleaned_by": "varadharajaan",
    "execution_timestamp": "20251124_103045",
    "regions_processed": ["us-east-1", "us-west-2"]
  },
  "summary": {
    "total_accounts_processed": 2,
    "total_regions_processed": 2,
    "total_instances_deleted": 5,
    "total_clusters_deleted": 2,
    "total_snapshots_deleted": 15,
    "total_failed_deletions": 0,
    "total_skipped_resources": 3
  },
  "detailed_results": {
    "deleted_instances": [...],
    "deleted_clusters": [...],
    "deleted_snapshots": [...],
    "failed_deletions": [],
    "skipped_resources": [...]
  }
}
```

## 🔧 Cleanup Order

Resources are cleaned up in this dependency-aware order:

1. **DB Instances** - Delete database instances first
2. **DB Clusters** - Delete Aurora clusters
3. **Snapshots** - Delete manual DB and cluster snapshots
4. **Automated Backups** - Delete retained automated backups
5. **Export Tasks** - Cancel snapshot export tasks
6. **Event Subscriptions** - Remove event notifications
7. **CloudWatch Alarms** - Delete RDS monitoring alarms
8. **CloudWatch Logs** - Delete RDS log groups
9. **Parameter Groups** - Delete custom parameter groups (preserve defaults)
10. **Option Groups** - Delete custom option groups (preserve defaults)

**Note:** DB Subnet Groups are intentionally **NOT** deleted as per requirements.

## ⚠️  Important Notes

### Deletion Without Snapshots
- DB instances are deleted with `SkipFinalSnapshot=True`
- DB clusters are deleted with `SkipFinalSnapshot=True`
- Automated backups are deleted with the instance
- This is intentional for complete cleanup

### Protected Resources
- Default parameter groups (e.g., `default.mysql8.0`, `default.postgres13`) are **NOT** deleted
- Default option groups (e.g., `default:mysql-8-0`) are **NOT** deleted
- DB subnet groups are **NOT** deleted (as requested)
- Default security groups are **NOT** touched

### Safety Features

1. **Interactive Confirmation**: Type `DELETE` to confirm
2. **Protected Resources**: Critical infrastructure preserved
3. **Detailed Logging**: Full audit trail in log files
4. **Dependency Order**: Resources cleaned in safe order
5. **Error Handling**: Graceful failure handling with retry logic
6. **Progress Tracking**: Real-time status updates
7. **Comprehensive Reporting**: JSON report with full details

## 📝 Examples

### Example 1: Cleanup Single Account, All Regions
```bash
python ultra_cleanup_rds.py
# Select account: 1
# Select regions: all
# Type: DELETE
```

### Example 2: Cleanup Multiple Accounts, Specific Regions
```bash
python ultra_cleanup_rds.py
# Select accounts: 1,2,3
# Select regions: 1,2 (us-east-1, us-east-2)
# Type: DELETE
```

### Example 3: Cleanup All Accounts, Single Region
```bash
python ultra_cleanup_rds.py
# Select accounts: all
# Select regions: 1 (us-east-1)
# Type: DELETE
```

## 🔍 Troubleshooting

### Issue: "InvalidDBInstanceState"
**Cause**: Instance is in a state that prevents deletion (e.g., creating, modifying)  
**Solution**: Script will wait for instance to reach "available" state before deletion

### Issue: "InvalidDBParameterGroupState"
**Cause**: Parameter group is in use by existing instances  
**Solution**: Script deletes instances first, handles this automatically

### Issue: Permission Denied
**Cause**: IAM user lacks required permissions  
**Solution**: Add the permissions listed in Prerequisites section

### Issue: No Resources Found
**Cause**: Region has no RDS resources  
**Solution**: This is normal, script will continue to next region

### Issue: Timeout Waiting for Deletion
**Cause**: RDS resource deletion taking longer than expected  
**Solution**: Check AWS Console for resource status, may need manual intervention

## 🎯 Use Cases

1. **Environment Teardown**: Complete cleanup after testing
2. **Cost Reduction**: Remove unused RDS resources
3. **Account Cleanup**: Prepare account for new projects
4. **Compliance**: Remove test data and databases
5. **Resource Audit**: Identify and cleanup RDS resources

## 📚 Related Scripts

- `ultra_cleanup_eks.py` - EKS cluster cleanup
- `ultra_cleanup_vpc.py` - VPC resource cleanup
- `ultra_cleanup_ami.py` - AMI and snapshot cleanup
- `ec2_cleanup.py` - EC2 instance cleanup

## 🤝 Contributing

When modifying this script:
1. Maintain the cleanup order
2. Preserve protection logic for defaults and DB subnet groups
3. Add logging for all operations
4. Update this README with changes
5. Follow the style of `ultra_cleanup_eks.py`

## ⚖️  License

Use at your own risk. Always test in non-production environments first.

## 📞 Support

For issues or questions:
1. Check the log files in `aws/rds/`
2. Review the JSON report for detailed results
3. Verify IAM permissions
4. Ensure `root_iam_credential_manager.py` is available

---

**⚠️  WARNING**: This script deletes RDS resources permanently without final snapshots. DB Subnet Groups are preserved as requested, but all other RDS resources (instances, clusters, snapshots, backups, etc.) will be deleted. Always verify before confirming deletion.
