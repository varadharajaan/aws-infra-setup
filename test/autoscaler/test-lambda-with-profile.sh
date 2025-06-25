#!/bin/bash
# Test scaling with current setup
# Current time: 2025-06-19 05:29:01 UTC
# User: varadharajaan

export AWS_PROFILE=root-account03

echo "========================================"
echo "    TEST SCALING"
echo "========================================"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "User: varadharajaan"
echo "========================================"

echo "Current status:"
echo "Nodes: $(kubectl get nodes --no-headers | wc -l)"
echo "Stress pods: $(kubectl get po -l app=stress-test --no-headers | wc -l)"

echo -e "\nScaling stress-test to 10 pods to trigger autoscaling..."
kubectl scale deployment stress-test --replicas=10

echo -e "\nWaiting 30 seconds..."
sleep 30

echo -e "\nNew status:"
echo "Nodes: $(kubectl get nodes --no-headers | wc -l)"
echo "Running stress pods: $(kubectl get po -l app=stress-test --field-selector=status.phase=Running --no-headers | wc -l)"
echo "Pending stress pods: $(kubectl get po -l app=stress-test --field-selector=status.phase=Pending --no-headers | wc -l)"

echo -e "\nAutoscaler logs:"
kubectl logs -l app=cluster-autoscaler -n kube-system --tail=10

echo -e "\n✅ Test initiated. Monitor with ./simple-monitor.sh"