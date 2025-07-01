#!/bin/bash
# Fix cluster autoscaler credentials
# Current time: 2025-06-19 05:11:45 UTC (10:41:45 AM IST)
# User: varadharajaan

echo "========================================"
echo "    FIXING CLUSTER AUTOSCALER"
echo "========================================"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "User: varadharajaan"
echo "Issue: Missing AWS credentials for autoscaler"
echo "========================================"

# Step 1: Delete existing broken deployment
echo "Step 1: Removing broken autoscaler deployment..."
kubectl delete deployment cluster-autoscaler -n kube-system

# Step 2: Apply fixed configuration
echo "Step 2: Applying fixed autoscaler with IAM role..."
kubectl apply -f fix-cluster-autoscaler.yaml

# Step 3: Wait for deployment
echo "Step 3: Waiting for new deployment..."
sleep 30

# Step 4: Check status
echo "Step 4: Checking new autoscaler status..."
kubectl get po -n kube-system -l app=cluster-autoscaler

echo -e "\nStep 5: Checking logs..."
kubectl logs -l app=cluster-autoscaler -n kube-system --tail=20

echo -e "\nStep 6: Checking service account..."
kubectl get sa cluster-autoscaler -n kube-system -o yaml | grep -A 3 annotations