#!/bin/bash

# Quick setup script for EKS autoscaling test - Single Nodegroup
# Time: 2025-06-19 04:33:47 UTC (10:03:47 AM IST)
# User: varadharajaan

echo "🚀 Quick EKS Autoscaling Setup (Single Nodegroup)"
echo "=================================================="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "User: varadharajaan"
echo "=================================================="

# Make scripts executable
chmod +x monitor-autoscaling.sh
chmod +x test-autoscaling.sh

# Verify kubectl connectivity
echo "📋 Verifying cluster connectivity..."
kubectl get nodes || { echo "❌ Cannot connect to cluster. Check your kubeconfig."; exit 1; }

echo "✅ Cluster connection verified"

# Show current cluster state
echo -e "\n📊 Current cluster state:"
NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
POD_COUNT=$(kubectl get pods --all-namespaces --no-headers | wc -l)
echo "Nodes: $NODE_COUNT"
echo "Pods: $POD_COUNT"

# Verify nodegroup
echo -e "\n🏗️ Nodegroup verification:"
aws eks describe-nodegroup \
    --cluster-name eks-cluster-root-account03-us-west-1-diuh \
    --nodegroup-name nodegroup-1 \
    --region us-west-1 \
    --query 'nodegroup.{Name:nodegroupName,Status:status,Scaling:scalingConfig}' 2>/dev/null || echo "❌ Cannot access nodegroup information"

echo -e "\n🎯 Setup completed! Available commands:"
echo "  ./test-autoscaling.sh                    # Run full autoscaling test"
echo "  ./monitor-autoscaling.sh                 # Start continuous monitoring"
echo "  kubectl apply -f stress-test-app.yaml    # Deploy test app only"
echo ""
echo "📋 Lambda test commands:"
echo "  aws lambda invoke --function-name eks-scale-diuh --region us-west-1 --payload file://lambda-scale-up-event.json response.json"
echo "  aws lambda invoke --function-name eks-scale-diuh --region us-west-1 --payload file://lambda-scale-down-event.json response.json"