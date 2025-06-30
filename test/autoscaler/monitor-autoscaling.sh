#!/bin/bash

# Continuous monitoring script for EKS autoscaling - Single Nodegroup
# Current time: 2025-06-19 04:33:47 UTC (10:03:47 AM IST)
# User: varadharajaan

CLUSTER_NAME="eks-cluster-root-account03-us-west-1-diuh"
REGION="us-west-1"
NODEGROUP="nodegroup-1"

log_with_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S UTC')] $1"
}

clear_and_header() {
    clear
    echo "========================================"
    echo "    EKS AUTOSCALING MONITOR (Single NG)"
    echo "========================================"
    echo "Cluster: $CLUSTER_NAME"
    echo "Nodegroup: $NODEGROUP"
    echo "Region: $REGION"
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC') ($(TZ='Asia/Kolkata' date '+%I:%M %p IST'))"
    echo "User: varadharajaan"
    echo "Press Ctrl+C to stop monitoring"
    echo "========================================"
}

show_cluster_status() {
    echo -e "\n🔍 CLUSTER STATUS:"
    local node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    local pod_count=$(kubectl get pods --all-namespaces --no-headers 2>/dev/null | wc -l)
    echo "   Nodes: $node_count"
    echo "   Pods:  $pod_count"
    
    echo -e "\n📊 NODE DETAILS:"
    kubectl get nodes -o custom-columns="NAME:.metadata.name,STATUS:.status.conditions[?(@.type=='Ready')].status,CPU:.status.capacity.cpu,MEMORY:.status.capacity.memory,INSTANCE:.metadata.labels.node\.kubernetes\.io/instance-type" 2>/dev/null || echo "   Unable to fetch node details"
    
    echo -e "\n🏗️  NODEGROUP SCALING CONFIG:"
    local config=$(aws eks describe-nodegroup \
        --cluster-name $CLUSTER_NAME \
        --nodegroup-name $NODEGROUP \
        --region $REGION \
        --query 'nodegroup.scalingConfig.{min:minSize,desired:desiredSize,max:maxSize}' \
        --output text 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "   $NODEGROUP: min/desired/max = $config"
    else
        echo "   $NODEGROUP: Unable to fetch config"
    fi
}

show_pod_status() {
    echo -e "\n🚀 POD STATUS:"
    local pending=$(kubectl get pods --all-namespaces --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l)
    local running=$(kubectl get pods --all-namespaces --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    local stress_running=$(kubectl get pods -l app=stress-test --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    local stress_pending=$(kubectl get pods -l app=stress-test --field-selector=status.phase=Pending --no-headers 2>/dev/null | wc -l)
    
    echo "   Total Running: $running | Total Pending: $pending"
    echo "   Stress-test Running: $stress_running | Stress-test Pending: $stress_pending"
    
    if [ $pending -gt 0 ]; then
        echo -e "\n   ⏳ PENDING PODS:"
        kubectl get pods --all-namespaces --field-selector=status.phase=Pending -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,REASON:.status.conditions[?(@.type=='PodScheduled')].reason" 2>/dev/null | head -5
    fi
}

show_autoscaler_status() {
    echo -e "\n🤖 CLUSTER AUTOSCALER:"
    local ca_pod=$(kubectl get pod -n kube-system -l app=cluster-autoscaler --no-headers 2>/dev/null | head -1 | awk '{print $1}')
    if [ ! -z "$ca_pod" ]; then
        local ca_status=$(kubectl get pod -n kube-system $ca_pod -o jsonpath='{.status.phase}' 2>/dev/null)
        echo "   Status: $ca_status (Pod: $ca_pod)"
        echo -e "\n   📝 RECENT AUTOSCALER LOGS:"
        kubectl logs -n kube-system $ca_pod --tail=3 --since=60s 2>/dev/null | grep -E "(scale|Scale|node|Node|group)" | tail -3 || echo "   No recent scaling activity"
    else
        echo "   Status: Not Found"
    fi
}

show_recent_events() {
    echo -e "\n📅 RECENT EVENTS:"
    kubectl get events --sort-by='.lastTimestamp' --all-namespaces 2>/dev/null | grep -E "(scale|Scale|node|Node|autoscal)" | tail -3 || echo "   No recent scaling events"
}

# Main monitoring loop
echo "Starting monitoring at $(date '+%Y-%m-%d %H:%M:%S UTC')..."
while true; do
    clear_and_header
    show_cluster_status
    show_pod_status
    show_autoscaler_status
    show_recent_events
    
    echo -e "\n⏰ Next update in 30 seconds..."
    sleep 30
done