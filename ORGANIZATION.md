# AWS Infrastructure Setup - File Organization

## Directory Structure

```
aws-infra-setup/
├── ultra_cleanup/          # Ultra cleanup scripts for AWS resources
│   ├── __init__.py
│   ├── ultra_cleanup_ami.py
│   ├── ultra_cleanup_apigateway.py
│   ├── ultra_cleanup_asg.py
│   ├── ultra_cleanup_athena.py
│   ├── ultra_cleanup_cloudwatch.py
│   ├── ultra_cleanup_dynamodb.py
│   ├── ultra_cleanup_ebs.py
│   ├── ultra_cleanup_ebs_volumes.py
│   ├── ultra_cleanup_ec2.py
│   ├── ultra_cleanup_ecr.py
│   ├── ultra_cleanup_ecs.py
│   ├── ultra_cleanup_eks.py
│   ├── ultra_cleanup_elasticache.py
│   ├── ultra_cleanup_elb.py
│   ├── ultra_cleanup_iam.py
│   ├── ultra_cleanup_lambda.py
│   ├── ultra_cleanup_rds.py
│   ├── ultra_cleanup_route53.py
│   ├── ultra_cleanup_sns.py
│   ├── ultra_cleanup_sqs.py
│   ├── ultra_cleanup_vpc.py
│   ├── ultra_cleanup_vpc_bk.py
│   └── demo_ultra_cleanup_vpc.py
│
├── docs/                   # Documentation files
│   ├── README.md
│   ├── README_ultra_cleanup_rds.md
│   ├── README_ultra_cleanup_route53.md
│   └── README_ultra_cleanup_vpc.md
│
├── root_iam_credential_manager.py  # Core credential manager
├── iam_policy_manager.py           # IAM policy management
└── ... (other core files)
```

## Usage

### Running Ultra Cleanup Scripts

All ultra cleanup scripts are now in the `ultra_cleanup/` folder. To run them:

```powershell
# From the root directory
python ultra_cleanup/ultra_cleanup_ec2.py
python ultra_cleanup/ultra_cleanup_rds.py
python ultra_cleanup/ultra_cleanup_route53.py
# etc.
```

Or navigate to the folder first:

```powershell
cd ultra_cleanup
python ultra_cleanup_ec2.py
```

### Import Changes

All ultra cleanup scripts now include path updates to import from the parent directory:

```python
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from root_iam_credential_manager import AWSCredentialManager, Colors
```

This allows the scripts to properly import core modules from the root directory.

## Documentation

All README files have been moved to the `docs/` folder for better organization:

- **Main README**: `docs/README.md`
- **RDS Cleanup**: `docs/README_ultra_cleanup_rds.md`
- **Route53 Cleanup**: `docs/README_ultra_cleanup_route53.md`
- **VPC Cleanup**: `docs/README_ultra_cleanup_vpc.md`

## Key Changes

1. **Organized Structure**: Ultra cleanup scripts separated from core utilities
2. **Updated Imports**: All scripts updated to work from the new location
3. **Documentation Centralized**: All README files in dedicated docs folder
4. **No Breaking Changes**: Scripts work exactly as before, just from new locations

## Benefits

- **Cleaner Root Directory**: Core utilities and configs at top level
- **Easier Navigation**: Related scripts grouped together
- **Better Maintenance**: Clear separation of concerns
- **Scalable Structure**: Easy to add new cleanup scripts or docs
