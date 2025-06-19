#!/bin/bash
# Simple monitoring without OIDC complexity
# Current time: 2025-06-19 05:29:01 UTC
# User: varadharajaan

export AWS_PROFILE=root-account03

while true; do
    clear
    echo "========================================"
    echo "    SIMPLE AUTOSCALING MONITOR"
    echo "========================================"
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
    echo "User: varadharajaan"
    echo "Method: Default AWS credentials"
    echo "========================================"
    
    echo -e "\n🚀 AUTOSCALER STATUS:"
    kubectl get po -n kube-system -l app=cluster-autoscaler
    
    echo -e "\n📊 CLUSTER:"
    echo "Nodes: $(kubectl get nodes --no-headers | wc -l)"
    echo "Stress pods running: $(kubectl get po -l app=stress-test --field-selector=status.phase=Running --no-headers | wc -l)"
    echo "Stress pods total: $(kubectl get po -l app=stress-test --no-headers | wc -l)"
    
    echo -e "\n📝 AUTOSCALER LOGS (last 3 lines):"
    kubectl logs -l app=cluster-autoscaler -n kube-system --tail=3 2>/dev/null | tail -3
    
    echo -e "\n⏰ Next update in 30 seconds..."
    sleep 30
done