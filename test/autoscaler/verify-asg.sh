#!/bin/bash
# Verify ASG tags for autoscaler discovery
# Current time: 2025-06-19 05:11:45 UTC (10:41:45 AM IST)
# User: varadharajaan

echo "========================================"
echo "    VERIFY AUTO SCALING GROUPS"
echo "========================================"

# Find ASGs for your cluster
echo "1. Finding Auto Scaling Groups for your cluster..."
aws autoscaling describe-auto-scaling-groups \
    --region us-west-1 \
    --query 'AutoScalingGroups[?contains(Tags[?Key==`eks:cluster-name`].Value, `eks-cluster-root-account03-us-west-1-diuh`)].{Name:AutoScalingGroupName,Tags:Tags[?Key==`k8s.io/cluster-autoscaler/enabled` || Key==`k8s.io/cluster-autoscaler/eks-cluster-root-account03-us-west-1-diuh`]}' \
    --output table \
    --profile root-account03

# Check if ASGs have required tags
echo -e "\n2. Checking required tags on ASGs..."
ASG_NAMES=$(aws autoscaling describe-auto-scaling-groups \
    --region us-west-1 \
    --query 'AutoScalingGroups[?contains(Tags[?Key==`eks:cluster-name`].Value, `eks-cluster-root-account03-us-west-1-diuh`)].AutoScalingGroupName' \
    --output text \
    --profile root-account03)

if [ ! -z "$ASG_NAMES" ]; then
    for asg in $ASG_NAMES; do
        echo "Checking ASG: $asg"
        
        # Check for required tags
        has_enabled=$(aws autoscaling describe-auto-scaling-groups \
            --auto-scaling-group-names $asg \
            --region us-west-1\
            --profile root-account03\
            --query 'AutoScalingGroups[0].Tags[?Key==`k8s.io/cluster-autoscaler/enabled`].Value' \
            --output text)
        
        has_cluster=$(aws autoscaling describe-auto-scaling-groups \
            --auto-scaling-group-names $asg \
            --region us-west-1\
            --profile root-account03\
            --query 'AutoScalingGroups[0].Tags[?Key==`k8s.io/cluster-autoscaler/eks-cluster-root-account03-us-west-1-diuh`].Value' \
            --output text)
        
        if [ -z "$has_enabled" ] || [ -z "$has_cluster" ]; then
            echo "❌ ASG $asg is missing required tags for autoscaler!"
            echo "   Adding required tags..."
            
            # Add required tags
            aws autoscaling create-or-update-tags \
                --tags "ResourceId=$asg,ResourceType=auto-scaling-group,Key=k8s.io/cluster-autoscaler/enabled,Value=true,PropagateAtLaunch=false" \
                --region us-west-1 --profile root-account03
            
            aws autoscaling create-or-update-tags \
                --tags "ResourceId=$asg,ResourceType=auto-scaling-group,Key=k8s.io/cluster-autoscaler/eks-cluster-root-account03-us-west-1-diuh,Value=owned,PropagateAtLaunch=false" \
                --region us-west-1 --profile root-account03
            
            echo "✅ Tags added to ASG $asg"
        else
            echo "✅ ASG $asg has required tags"
        fi
    done
else
    echo "❌ No Auto Scaling Groups found for your cluster!"
fi