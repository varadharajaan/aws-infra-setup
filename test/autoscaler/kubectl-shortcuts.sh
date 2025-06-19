#!/bin/bash
# kubectl shortcuts and partial matching
# Time: 2025-06-19 05:02:39 UTC - User: varadharajaan

echo "=== kubectl SHORTHAND COMMANDS ==="

# 1. DESCRIBE PODS (no need for full name)
echo "# Describe pod by partial name:"
kubectl describe pod cluster-autoscaler -n kube-system
# OR
kubectl describe pod -l app=cluster-autoscaler -n kube-system

echo -e "\n# Get pod with partial name:"
kubectl get pod cluster-auto* -n kube-system
# OR
kubectl get pod -l app=cluster-autoscaler -n kube-system

echo -e "\n# Logs with partial name:"
kubectl logs cluster-auto* -n kube-system --tail=20
# OR (best method)
kubectl logs -l app=cluster-autoscaler -n kube-system --tail=20

# 2. RESOURCE SHORTCUTS
echo -e "\n# Resource shortcuts:"
echo "kubectl get po          # pods"
echo "kubectl get svc         # services" 
echo "kubectl get deploy      # deployments"
echo "kubectl get ns          # namespaces"
echo "kubectl get no          # nodes"
echo "kubectl get ing         # ingress"
echo "kubectl get cm          # configmaps"
echo "kubectl get secrets     # secrets"
echo "kubectl get pv          # persistent volumes"
echo "kubectl get pvc         # persistent volume claims"

# 3. ADVANCED SHORTCUTS
echo -e "\n# Advanced shortcuts:"
echo "kubectl get po -A                    # all pods in all namespaces"
echo "kubectl get po -o wide               # detailed pod info"
echo "kubectl get po --show-labels         # show labels"
echo "kubectl get po -l app=stress-test    # filter by label"
echo "kubectl get po --field-selector=status.phase=Running"

# 4. DESCRIBE SHORTCUTS
echo -e "\n# Describe shortcuts:"
echo "kubectl describe po <partial-name>   # describe pod"
echo "kubectl describe no                  # describe all nodes"
echo "kubectl describe svc <service-name>  # describe service"
echo "kubectl describe deploy <deployment> # describe deployment"