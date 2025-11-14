#!/bin/bash
# Debug autoscaler - Current time: 2025-06-19 05:02:39 UTC
# User: varadharajaan

echo "========================================"
echo "    AUTOSCALER DEBUG SESSION"
echo "========================================"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "User: varadharajaan"
echo "========================================"

# Method 1: Using partial pod name (easiest)
echo -e "\n🔍 AUTOSCALER LOGS (Recent errors):"
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=50 | grep -i error

echo -e "\n🔍 AUTOSCALER LOGS (Recent activity):"
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=20 | grep -E "(scale|Scale|node|group|unable|failed)"

echo -e "\n🔍 AUTOSCALER LOGS (Full recent logs):"
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=30

# Method 2: Using pod shorthand
echo -e "\n📊 AUTOSCALER POD STATUS:"
kubectl get pod -n kube-system -l app=cluster-autoscaler

echo -e "\n🔧 AUTOSCALER CONFIGURATION:"
kubectl describe deployment -n kube-system cluster-autoscaler | grep -A 20 "Args:"

echo -e "\n🏗️ NODEGROUP TAGS CHECK:"
aws ec2 describe-instances \
    --filters "Name=tag:eks:cluster-name,Values=eks-cluster-root-account03-us-west-1-diuh" \
    --region us-west-1 \
    --query 'Reservations[].Instances[].Tags[?Key==`k8s.io/cluster-autoscaler/enabled` || Key==`k8s.io/cluster-autoscaler/eks-cluster-account01_clouduser01-us-east-1-rtip`]' 2>/dev/null || echo "Cannot check instance tags"