#!/bin/bash
# Comprehensive autoscaling debug
# Current time: 2025-06-19 05:02:39 UTC
# User: varadharajaan

CLUSTER_NAME="eks-cluster-root-account03-us-west-1-diuh"
REGION="us-west-1"
NODEGROUP="nodegroup-1"

echo "========================================"
echo "    COMPREHENSIVE AUTOSCALING DEBUG"
echo "========================================"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "User: varadharajaan"
echo "Cluster: $CLUSTER_NAME"
echo "========================================"

# 1. Check autoscaler pod status (using shortcuts)
echo -e "\n1️⃣ AUTOSCALER POD STATUS:"
kubectl get po -n kube-system -l app=cluster-autoscaler -o wide

# 2. Check autoscaler logs for errors
echo -e "\n2️⃣ AUTOSCALER ERROR LOGS:"
kubectl logs -l app=cluster-autoscaler -n kube-system --tail=100 | grep -i -E "(error|failed|unable|denied|forbidden)" | tail -10

# 3. Check autoscaler configuration
echo -e "\n3️⃣ AUTOSCALER CONFIGURATION:"
kubectl get deploy cluster-autoscaler -n kube-system -o jsonpath='{.spec.template.spec.containers[0].command}' | jq -r '.[]' | grep -E "(cluster-name|node-group)"

# 4. Check IAM permissions (autoscaler service account)
echo -e "\n4️⃣ SERVICE ACCOUNT & IAM:"
kubectl get sa cluster-autoscaler -n kube-system -o yaml | grep -A 5 annotations

# 5. Check nodegroup tags
echo -e "\n5️⃣ NODEGROUP AUTO SCALING GROUP:"
ASG_NAME=$(aws autoscaling describe-auto-scaling-groups \
    --region $REGION \
    --query "AutoScalingGroups[?contains(Tags[?Key=='eks:nodegroup-name'].Value, 'nodegroup-1')].AutoScalingGroupName" \
    --output text 2>/dev/null)

if [ ! -z "$ASG_NAME" ]; then
    echo "ASG Name: $ASG_NAME"
    
    echo -e "\n   ASG Tags:"
    aws autoscaling describe-auto-scaling-groups \
        --auto-scaling-group-names $ASG_NAME \
        --region $REGION \
        --query 'AutoScalingGroups[0].Tags[?Key==`k8s.io/cluster-autoscaler/enabled` || Key==`k8s.io/cluster-autoscaler/eks-cluster-root-account03-us-west-1-diuh`]' 2>/dev/null
    
    echo -e "\n   ASG Current Status:"
    aws autoscaling describe-auto-scaling-groups \
        --auto-scaling-group-names $ASG_NAME \
        --region $REGION \
        --query 'AutoScalingGroups[0].{Desired:DesiredCapacity,Min:MinSize,Max:MaxSize,Instances:length(Instances)}' 2>/dev/null
else
    echo "❌ Cannot find Auto Scaling Group for nodegroup-1"
fi

# 6. Check current cluster capacity
echo -e "\n6️⃣ CLUSTER CAPACITY:"
echo "Current nodes: $(kubectl get no --no-headers | wc -l)"
echo "Running pods: $(kubectl get po -A --field-selector=status.phase=Running --no-headers | wc -l)"
echo "Pending pods: $(kubectl get po -A --field-selector=status.phase=Pending --no-headers | wc -l)"

# 7. Check for pods that need more resources
echo -e "\n7️⃣ RESOURCE-HUNGRY PODS:"
kubectl get po -A --field-selector=status.phase=Pending -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,REASON:.status.conditions[?(@.type=='PodScheduled')].reason"

# 8. Check node resource usage
echo -e "\n8️⃣ NODE RESOURCE USAGE:"
kubectl top nodes 2>/dev/null || echo "Metrics server not available"

# 9. Recent events
echo -e "\n9️⃣ RECENT SCALING EVENTS:"
kubectl get events -A --sort-by='.lastTimestamp' | grep -E "(scale|Scale|autoscal|Autoscal)" | tail -5

# 10. Test scaling trigger
echo -e "\n🔟 TESTING SCALING TRIGGER:"
echo "Current stress-test pods:"
kubectl get po -l app=stress-test 2>/dev/null || echo "No stress-test pods found"

echo -e "\nTo trigger scaling, run:"
echo "kubectl apply -f stress-test-app.yaml"
echo "kubectl scale deployment stress-test --replicas=8"