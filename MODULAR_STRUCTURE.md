# AWS Infrastructure Setup - Modular Structure

## Overview
The repository has been reorganized into a modular structure under the `functionality/` directory to improve maintainability and code organization. Each module contains related functionality grouped by AWS service or utility type.

## Directory Structure

```
functionality/
├── ec2/                    # EC2 Instance Management
├── eks/                    # EKS Cluster Management
├── iam/                    # IAM User and Policy Management
├── asg/                    # Auto Scaling Group Management
├── cleanup/                # Ultra Cleanup Utilities
├── aws_management/         # AWS Credential and Account Management
├── core_utils/             # Core Utilities and Helpers
├── lambda_functions/       # Lambda Function Templates
├── *.json                  # Configuration files
├── *.yaml                  # CloudWatch and Kubernetes templates
├── *.sh                    # Shell scripts
└── k8s_manifests/          # Kubernetes manifest files
```

## Module Breakdown

### 📁 EC2 Module (`functionality/ec2/`)
EC2 instance management and automation scripts:
- `ec2_asg_automation_main.py` - Main EC2+ASG orchestrator
- `ec2_cleanup.py` - EC2 instance cleanup utilities
- `ec2_eks_lookup_resource.py` - EC2/EKS resource lookup
- `ec2_instance_manager.py` - EC2 instance lifecycle management
- `ec2_ssh_connector.py` - SSH connection management
- `nuclear_deleteall_ec2.py` - Comprehensive EC2 deletion
- `spot_instance_analyzer.py` - Spot instance analysis and reporting

### 📁 EKS Module (`functionality/eks/`)
EKS cluster management and Kubernetes operations:
- `eks_cluster_manager.py` - Core EKS cluster management
- `eks_cluster_automation.py` - Automated EKS operations
- `eks_cluster_cleanup_enhanced.py` - Enhanced cluster cleanup
- `eks_cluster_cleanup_enhanced_delete.py` - Advanced deletion utilities
- `eks_cluster_manager_tests.py` - EKS manager test suite
- `eks_lambda_scaler.py` - Lambda-based EKS scaling
- `configure_existing_eks_auth.py` - EKS authentication configuration
- `continue_cluster_setup.py` - Cluster setup continuation
- `interactive_cluster_editor.py` - Interactive cluster management

### 📁 IAM Module (`functionality/iam/`)
IAM user, policy, and credential management:
- `root_iam_credential_manager.py` - Root IAM credential management
- `iam_policy_manager.py` - IAM policy operations
- `iam_policy_deletion_automation.py` - Automated policy deletion
- `iam_cleanup_files.py` - IAM resource cleanup
- `create_iam_users_logging.py` - IAM user creation with logging

### 📁 ASG Module (`functionality/asg/`)
Auto Scaling Group management and automation:
- `auto_scaling_group_manager.py` - Core ASG management
- `asg_cleanup.py` - ASG cleanup utilities
- `asg_cleanup_files.py` - ASG file cleanup
- `autoscale_tester.py` - ASG testing utilities
- `complete_autoscaler_deployment.py` - Complete autoscaler deployment
- `launch_template_manager.py` - Launch template management

### 📁 Cleanup Module (`functionality/cleanup/`)
Ultra cleanup utilities for comprehensive resource removal:
- `ultra_cleanup_vpc.py` - VPC cleanup manager
- `ultra_cleanup_ec2.py` - EC2 cleanup utilities
- `ultra_cleanup_eks.py` - EKS cleanup utilities
- `ultra_cleanup_elb.py` - ELB cleanup utilities
- `ultra_cleanup_ebs.py` - EBS cleanup utilities
- `ultra_cleanup_iam.py` - IAM cleanup utilities
- `ultra_cleanup_asg.py` - ASG cleanup utilities
- `demo_ultra_cleanup_vpc.py` - VPC cleanup demo

### 📁 AWS Management Module (`functionality/aws_management/`)
AWS credential, account, and service management:
- `aws_credential_manager.py` - Basic AWS credential management
- `enhanced_aws_credential_manager.py` - Enhanced credential management
- `aws_credential_diagnostics.py` - Credential diagnostic tools
- `aws_default_vpc_checker.py` - Default VPC validation
- `aws_vpc_recovery_tool.py` - VPC recovery utilities
- `compare_credentials.py` - Credential comparison tools
- `examine_working_credentials.py` - Working credential analysis
- `custom_cloudwatch_agent_deployer.py` - CloudWatch agent deployment
- `live_health_cost_lookup.py` - Health and cost monitoring

### 📁 Core Utils Module (`functionality/core_utils/`)
Core utilities and helper functions:
- `logger.py` - Logging utilities
- `excel_helper.py` - Excel file operations
- `httpsession.py` - HTTP session management
- `move_aws_files.py` - File movement utilities
- `sanitize_accounts_config.py` - Account config sanitization
- `sanitize_iam_users_config.py` - IAM user config sanitization
- `git-filter.py` - Git filtering utilities

### 📁 Lambda Functions Module (`functionality/lambda_functions/`)
Lambda function templates and utilities:
- `lambda_asg_scaling_template.py` - ASG scaling Lambda template
- `lambda_eks_scaling_template.py` - EKS scaling Lambda template

## Import Structure

### Within Modules (Same Directory)
```python
# Relative imports within the same module
from .module_file import ClassName
```

### Between Modules
```python
# Import from another module
from ..module_name.file_name import ClassName
from ..aws_management.aws_credential_manager import CredentialInfo
from ..ec2.spot_instance_analyzer import SpotInstanceAnalyzer
```

### From Root/Test Files
```python
# Import from test files or external scripts
from functionality.module_name.file_name import ClassName
from functionality.cleanup.ultra_cleanup_vpc import UltraVPCCleanupManager
```

## Configuration Files and Assets

### Configuration Files (in `functionality/`)
- `ec2-region-ami-mapping.json` - EC2 AMI mappings by region
- `aws_csi_policy.json` - AWS CSI driver policy
- `policy.json` - General AWS policies
- `instance_specs.json` - EC2 instance specifications
- `user_mapping.json` - User mapping configuration
- `sanitized_aws_accounts_config.json` - Sanitized account configs
- `sanitized_iam_users_credentials_*.json` - Sanitized user credentials

### Templates and Manifests
- `cloudwatch-agent-template.yaml` - CloudWatch agent configuration
- `lambda_scale_down_event.json` - Lambda scale down event template
- `lambda_scale_up_event.json` - Lambda scale up event template
- `k8s_manifests/` - Kubernetes manifest files
- `userdata_allsupport.sh` - EC2 user data script
- `ec2_python_enable_https.sh` - EC2 HTTPS enablement script

## Benefits of Modular Structure

1. **🎯 Clear Organization**: Related functionality grouped together
2. **🔧 Better Maintainability**: Easier to find and modify specific functionality
3. **📚 Logical Separation**: Clear boundaries between different AWS services
4. **⚡ Reduced Coupling**: Minimized cross-dependencies between unrelated components
5. **🔄 Scalability**: Easy to add new modules for additional AWS services
6. **🧪 Testability**: Each module can be tested independently

## Migration Notes

### Import Changes Required
All import statements have been updated to reflect the new modular structure:
- Cross-module imports use relative paths (`..module_name.file_name`)
- Same-module imports use relative paths (`.file_name`)
- External imports remain unchanged

### Test File Updates
- Test files updated to include proper module paths in `sys.path`
- Import statements updated to use the new module structure
- All existing tests continue to pass

### Backwards Compatibility
- All existing functionality preserved
- No breaking changes to external APIs
- Configuration files remain in the same accessible locations