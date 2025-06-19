#!/bin/bash
# kubectl cheat sheet for varadharajaan
# Time: 2025-06-19 05:02:39 UTC

cat << 'EOF'
╔══════════════════════════════════════════════════════════════╗
║                    kubectl SHORTCUTS                        ║
╠══════════════════════════════════════════════════════════════╣
║ RESOURCE SHORTCUTS:                                          ║
║   po = pods          svc = services      deploy = deployment ║
║   no = nodes         ns = namespaces     cm = configmaps     ║
║   ing = ingress      pv = persistentvolume                   ║
║                                                              ║
║ PARTIAL NAME MATCHING:                                       ║
║   kubectl get po cluster-auto*           # wildcard         ║
║   kubectl get po -l app=cluster-auto*    # label selector   ║
║   kubectl describe po cluster-auto       # partial match    ║
║                                                              ║
║ USEFUL COMBINATIONS:                                         ║
║   kubectl get po -A -o wide              # all pods, wide   ║
║   kubectl logs -l app=myapp --tail=50    # logs by label    ║
║   kubectl describe po -l app=myapp       # describe by label║
║   kubectl get events --sort-by='.lastTimestamp'             ║
║                                                              ║
║ AUTOSCALER SPECIFIC:                                         ║
║   kubectl logs -l app=cluster-autoscaler -n kube-system     ║
║   kubectl describe po cluster-auto -n kube-system           ║
║   kubectl get po cluster-auto* -n kube-system -o wide       ║
╚══════════════════════════════════════════════════════════════╝
EOF