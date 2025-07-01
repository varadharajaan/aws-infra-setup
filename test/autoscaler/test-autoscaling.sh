#!/bin/bash

# End-to-end autoscaling test for single nodegroup
# Time: 2025-06-19 04:33:47 UTC (10:03:47 AM IST)
# User: varadharajaan

CLUSTER_NAME="eks-cluster-root-account03-us-west-1-diuh"
REGION="us-west-1"
NODEGROUP="nodegroup-1"

log_with_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S UTC')] $1"
}

echo "========================================"
echo "  EKS AUTOSCALING TEST SUITE (Single NG)"
echo "========================================"
echo "Cluster: $CLUSTER_NAME"
echo "Nodegroup: $NODEGROUP"
echo "Region: $REGION"
echo "User: varadharajaan"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================"

# Step 1: Check initial state
log_with_timestamp "Step 1: Checking initial cluster state..."
initial_nodes=$(kubectl get nodes --no-headers | wc -l)
echo "Initial node count: $initial_nodes"

# Step 2: Deploy test applications
log_with_timestamp "Step 2: Deploying test applications..."
kubectl apply -f stress-test-app.yaml

# Step 3: Deploy cluster autoscaler
#log_with_timestamp "Step 3: Deploying cluster autoscaler..."
#kubectl apply -f cluster-autoscaler.yaml

# Step 4: Wait for basic setup
log_with_timestamp "Step 4: Waiting for initial deployment (60 seconds)..."
sleep 60

# Step 5: Scale up test
log_with_timestamp "Step 5: Testing scale-up (increasing replicas to 6)..."
kubectl scale deployment stress-test --replicas=20

echo -e "\n🔍 Current status after scale-up request:"
kubectl get pods -l app=stress-test
kubectl get nodes

# Step 6: Monitor scale-up
log_with_timestamp "Step 6: Monitoring scale-up process..."
echo "Monitoring for 10 minutes. Watch for new nodes to appear..."

for i in {1..20}; do
    current_nodes=$(kubectl get nodes --no-headers | wc -l)
    running_pods=$(kubectl get pods -l app=stress-test --field-selector=status.phase=Running --no-headers | wc -l)
    pending_pods=$(kubectl get pods -l app=stress-test --field-selector=status.phase=Pending --no-headers | wc -l)
    
    echo -e "\n--- Check $i/20 at $(date '+%H:%M:%S UTC') ---"
    echo "Nodes: $current_nodes (started with $initial_nodes)"
    echo "Running stress pods: $running_pods/6"
    echo "Pending stress pods: $pending_pods/6"
    
    # Check if scale-up completed
    if [ $pending_pods -eq 0 ] && [ $running_pods -eq 6 ]; then
        log_with_timestamp "✅ Scale-up completed! All 6 pods are running on $current_nodes nodes."
        break
    fi
    
    # Show autoscaler activity
    if [ $((i % 4)) -eq 0 ]; then
        echo "Autoscaler logs:"
        kubectl logs -n kube-system -l app=cluster-autoscaler --tail=2 --since=60s 2>/dev/null | grep -E "scale|Scale" | tail -1 || echo "No scaling activity"
    fi
    
    sleep 30
done

# Step 7: Scale down test
log_with_timestamp "Step 7: Testing scale-down (reducing replicas to 1)..."
kubectl scale deployment stress-test --replicas=1

echo -e "\n🔍 Current status after scale-down request:"
kubectl get pods -l app=stress-test

# Step 8: Monitor scale-down
log_with_timestamp "Step 8: Monitoring scale-down process (this may take 10-15 minutes)..."
echo "Note: Cluster autoscaler typically waits 10 minutes before removing underutilized nodes"

scale_up_nodes=$(kubectl get nodes --no-headers | wc -l)
echo "Nodes after scale-up: $scale_up_nodes"

for i in {1..30}; do
    current_nodes=$(kubectl get nodes --no-headers | wc -l)
    running_pods=$(kubectl get pods -l app=stress-test --field-selector=status.phase=Running --no-headers | wc -l)
    
    echo -e "\n--- Check $i/30 at $(date '+%H:%M:%S UTC') ---"
    echo "Nodes: $current_nodes (peak was $scale_up_nodes)"
    echo "Running stress pods: $running_pods"
    
    if [ $current_nodes -lt $scale_up_nodes ]; then
        log_with_timestamp "✅ Scale-down detected! Nodes reduced from $scale_up_nodes to $current_nodes"
        break
    fi
    
    # Show autoscaler activity every 2 minutes
    if [ $((i % 4)) -eq 0 ]; then
        echo "Autoscaler logs:"
        kubectl logs -n kube-system -l app=cluster-autoscaler --tail=2 --since=120s 2>/dev/null | grep -E "scale|Scale|unneeded" | tail -1 || echo "No scaling activity"
    fi
    
    sleep 30
done

log_with_timestamp "Test completed at $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo -e "\n📊 FINAL SUMMARY:"
echo "Initial nodes: $initial_nodes"
echo "Peak nodes: $scale_up_nodes"
echo "Final nodes: $(kubectl get nodes --no-headers | wc -l)"
echo -e "\nRun 'bash monitor-autoscaling.sh' for continuous monitoring."