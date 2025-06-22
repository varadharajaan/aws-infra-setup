# EKS Cluster Continuation Setup

A standalone script that allows users to continue configuration of an existing EKS cluster when the initial creation had partial failures.

## Features

✅ **Menu-driven interface** for component selection  
✅ **Cluster verification** and status checking  
✅ **Nodegroup management** (on-demand, spot, mixed strategies)  
✅ **Essential add-ons** installation (EBS CSI, EFS CSI, VPC CNI, etc.)  
✅ **Container Insights** setup  
✅ **Cluster Autoscaler** configuration  
✅ **Scheduled Scaling** with Lambda functions  
✅ **CloudWatch monitoring** and alarms  
✅ **Cost monitoring** alarms  
✅ **Comprehensive health checks**  
✅ **Cost estimation** and optimization tips  
✅ **User instructions** generation  
✅ **Error handling** and logging  

## Prerequisites

- Python 3.7 or higher
- AWS credentials with EKS administrative permissions
- An existing EKS cluster (can be partially configured)
- Required Python packages (see `requirements.txt`)

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Make the script executable:**
   ```bash
   chmod +x continue_cluster_setup.py
   ```

## Usage

### Interactive Mode (Recommended)

```bash
./continue_cluster_setup.py
```

The script will prompt you for:
- Cluster name
- Admin access key
- Admin secret key
- Region (auto-detected if possible)

### Command Line Mode

```bash
./continue_cluster_setup.py \
  --cluster-name my-cluster \
  --access-key AKIA... \
  --secret-key ... \
  --region us-west-2
```

## Menu Options

### 1. 🔸 Nodegroups Management
- **Add On-Demand Nodegroup**: Create managed nodegroups with on-demand instances
- **Add Spot Nodegroup**: Create cost-effective spot instance nodegroups
- **Add Mixed Nodegroup**: Create nodegroups with both on-demand and spot instances
- **Instance Type Selection**: Choose from available instance types or use defaults
- **Auto-scaling Configuration**: Set min/desired/max node counts

### 2. 🔧 Essential Add-ons
Installs and configures essential EKS add-ons:
- **vpc-cni**: Container networking
- **kube-proxy**: Network proxy
- **coredns**: DNS resolution
- **aws-ebs-csi-driver**: EBS volume support
- **aws-efs-csi-driver**: EFS file system support

### 3. 📊 Container Insights
- Enables CloudWatch Container Insights for cluster monitoring
- Provides detailed metrics for containers, pods, and services
- Automatic log aggregation and analysis

### 4. 🔄 Cluster Autoscaler
- Installs and configures Cluster Autoscaler
- Automatically scales nodegroups based on pod requirements
- Sets up proper IAM permissions and policies

### 5. ⏰ Scheduled Scaling
- Creates Lambda functions for scheduled scaling
- Configures EventBridge rules for scale-up/scale-down
- Supports multiple nodegroups
- Customizable timing (default: 8:30 AM scale-up, 6:30 PM scale-down IST)

### 6. 📈 CloudWatch Monitoring & Alarms
- Deploys CloudWatch agent for detailed metrics
- Creates alarms for:
  - CPU utilization
  - Memory utilization
  - Node health
  - Pod failures

### 7. 💰 Cost Monitoring Alarms
- Sets up cost-based alarms
- Monitors EKS cluster spending
- Alerts on budget thresholds
- Integration with AWS Budgets

### 8. 🔍 Comprehensive Health Check
- Verifies cluster status
- Checks nodegroup health
- Validates add-on status
- Tests connectivity and permissions
- Generates health score

### 9. 💵 Cost Estimation
- Estimates monthly costs for current configuration
- Provides cost breakdown by component
- Offers optimization recommendations
- Compares spot vs on-demand pricing

### 10. 📋 Generate User Instructions
- Creates detailed access instructions
- Generates kubectl configuration commands
- Provides troubleshooting guides
- Saves to timestamped files

## Example Session

```bash
$ ./continue_cluster_setup.py

================================================================================
🚀 EKS Cluster Continuation Setup
   Continue configuration of partially configured EKS clusters
================================================================================

📝 Enter cluster details:
   Cluster name: my-production-cluster
   Admin Access Key: AKIA...
   Admin Secret Key: ...
🔍 Auto-detecting cluster region...
✅ Found cluster in region: us-west-2

🔍 Verifying cluster status for 'my-production-cluster'...

============================================================
📋 CLUSTER STATUS
============================================================
Name: my-production-cluster
Status: ACTIVE
Version: 1.28
Region: us-west-2
Account: 123456789012

📊 Nodegroups (1):
   • ng-spot-a1b2c3 - ACTIVE (SPOT)
     Instance Types: t3.medium, t3.large

🔧 Add-ons (2):
   • vpc-cni - ACTIVE (v1.12.0)
   • kube-proxy - ACTIVE (v1.28.0)
============================================================

============================================================
🛠️  COMPONENT CONFIGURATION MENU
============================================================
   1. 🔸 Nodegroups Management
   2. 🔧 Essential Add-ons (EBS CSI, EFS CSI, VPC CNI)
   3. 📊 Container Insights
   4. 🔄 Cluster Autoscaler
   5. ⏰ Scheduled Scaling
   6. 📈 CloudWatch Monitoring & Alarms
   7. 💰 Cost Monitoring Alarms
   8. 🔍 Comprehensive Health Check
   9. 💵 Cost Estimation
   10. 📋 Generate User Instructions
   11. ❌ Exit
============================================================
Select option (1-11): 2

🔧 Essential Add-ons Installation
----------------------------------------
Current add-ons:
   ✅ vpc-cni
   ✅ kube-proxy

Missing essential add-ons:
   ❌ coredns
   ❌ aws-ebs-csi-driver
   ❌ aws-efs-csi-driver

Install missing add-ons? (Y/n): y
✅ Essential add-ons installation completed
```

## Error Handling

The script includes comprehensive error handling for:
- **Network issues**: Automatic retries and fallbacks
- **Permission errors**: Clear guidance on required permissions
- **Resource conflicts**: Detection and resolution suggestions
- **Timeout scenarios**: Configurable timeouts with status updates

## Cost Optimization

The script provides several cost optimization features:
- **Spot instance recommendations**: Up to 90% savings on compute costs
- **Right-sizing suggestions**: Based on actual resource usage
- **Scheduled scaling**: Automatic scale-down during off-hours
- **Resource cleanup**: Identification of unused resources

## Security Considerations

- **Credential security**: No credentials stored or logged
- **IAM least privilege**: Uses minimal required permissions
- **Audit logging**: All actions logged for compliance
- **Encryption**: Supports encrypted EBS volumes and secrets

## Troubleshooting

### Common Issues

1. **"Cluster not found"**
   - Verify cluster name spelling
   - Check region configuration
   - Ensure credentials have proper permissions

2. **"Insufficient permissions"**
   - Admin credentials need EKS full access
   - IAM permissions for creating roles and policies
   - CloudWatch and Lambda permissions for monitoring

3. **"Nodegroup creation failed"**
   - Check AWS service quotas
   - Verify subnet capacity
   - Ensure instance types are available in the region

4. **"Add-on installation timeout"**
   - Some add-ons take 5-10 minutes to install
   - Check cluster networking configuration
   - Verify internet connectivity for EKS nodes

### Debug Mode

Enable verbose logging by setting environment variable:
```bash
export EKS_DEBUG=true
./continue_cluster_setup.py
```

## Integration with EKSClusterManager

This script integrates seamlessly with the existing `EKSClusterManager` class:
- **Reuses existing methods**: No code duplication
- **Consistent logging**: Same logging patterns and formats  
- **Shared utilities**: Uses common helper functions
- **Configuration compatibility**: Works with existing config files

## Testing

Run the test suite:
```bash
python3 -m unittest continue_cluster_setup_tests -v
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review AWS EKS documentation