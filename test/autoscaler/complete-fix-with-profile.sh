#!/bin/bash
# Fix autoscaler with proper secret creation
# Current time: 2025-06-19 05:31:55 UTC
# User: varadharajaan

echo "========================================"
echo "    AUTOSCALER FIX (Fixed Secret)"
echo "========================================"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "User: varadharajaan"
echo "Method: Default AWS credentials (fixed)"
echo "========================================"

# Set AWS profile
export AWS_PROFILE=root-account03

# Step 1: Clean up existing autoscaler
echo "Step 1: Cleaning up existing autoscaler..."
kubectl delete deployment cluster-autoscaler -n kube-system --ignore-not-found=true
kubectl delete clusterrolebinding cluster-autoscaler --ignore-not-found=true
kubectl delete clusterrole cluster-autoscaler --ignore-not-found=true
kubectl delete serviceaccount cluster-autoscaler -n kube-system --ignore-not-found=true
kubectl delete secret cluster-autoscaler-aws-credentials -n kube-system --ignore-not-found=true

# Step 2: Get AWS credentials
echo "Step 2: Getting AWS credentials from profile..."
AWS_ACCESS_KEY=$(aws configure get aws_access_key_id --profile root-account03)
AWS_SECRET_KEY=$(aws configure get aws_secret_access_key --profile root-account03)

if [ -z "$AWS_ACCESS_KEY" ] || [ -z "$AWS_SECRET_KEY" ]; then
    echo "❌ Cannot get AWS credentials from profile root-account03"
    echo "Please check: aws configure list-profiles"
    exit 1
fi

echo "✅ Got AWS credentials from profile root-account03"

# Step 3: Create secret separately
echo "Step 3: Creating AWS credentials secret..."
kubectl create secret generic cluster-autoscaler-aws-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_KEY" \
    -n kube-system

# Step 4: Create autoscaler resources
echo "Step 4: Creating autoscaler resources..."
cat << 'EOF' | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  labels:
    k8s-addon: cluster-autoscaler.addons.k8s.io
    k8s-app: cluster-autoscaler
  name: cluster-autoscaler
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cluster-autoscaler
  labels:
    k8s-addon: cluster-autoscaler.addons.k8s.io
    k8s-app: cluster-autoscaler
rules:
  - apiGroups: [""]
    resources: ["events", "endpoints"]
    verbs: ["create", "patch"]
  - apiGroups: [""]
    resources: ["pods/eviction"]
    verbs: ["create"]
  - apiGroups: [""]
    resources: ["pods/status"]
    verbs: ["update"]
  - apiGroups: [""]
    resources: ["endpoints"]
    resourceNames: ["cluster-autoscaler"]
    verbs: ["get", "update"]
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["watch", "list", "get", "update"]
  - apiGroups: [""]
    resources: ["namespaces", "pods", "services", "replicationcontrollers", "persistentvolumeclaims", "persistentvolumes"]
    verbs: ["watch", "list", "get"]
  - apiGroups: ["extensions"]
    resources: ["replicasets", "daemonsets"]
    verbs: ["watch", "list", "get"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["watch", "list"]
  - apiGroups: ["apps"]
    resources: ["statefulsets", "replicasets", "daemonsets"]
    verbs: ["watch", "list", "get"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses", "csinodes", "csidrivers", "csistoragecapacities"]
    verbs: ["watch", "list", "get"]
  - apiGroups: ["batch", "extensions"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch", "patch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["create"]
  - apiGroups: ["coordination.k8s.io"]
    resourceNames: ["cluster-autoscaler"]
    resources: ["leases"]
    verbs: ["get", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cluster-autoscaler
  labels:
    k8s-addon: cluster-autoscaler.addons.k8s.io
    k8s-app: cluster-autoscaler
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-autoscaler
subjects:
  - kind: ServiceAccount
    name: cluster-autoscaler
    namespace: kube-system
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app: cluster-autoscaler
spec:
  selector:
    matchLabels:
      app: cluster-autoscaler
  template:
    metadata:
      labels:
        app: cluster-autoscaler
      annotations:
        prometheus.io/scrape: 'true'
        prometheus.io/port: '8085'
    spec:
      priorityClassName: system-cluster-critical
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        fsGroup: 65534
      serviceAccountName: cluster-autoscaler
      containers:
        - image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.28.2
          name: cluster-autoscaler
          resources:
            limits:
              cpu: 100m
              memory: 600Mi
            requests:
              cpu: 100m
              memory: 600Mi
          command:
            - ./cluster-autoscaler
            - --v=4
            - --stderrthreshold=info
            - --cloud-provider=aws
            - --skip-nodes-with-local-storage=false
            - --expander=least-waste
            - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/eks-cluster-root-account03-us-west-1-diuh
            - --balance-similar-node-groups
            - --skip-nodes-with-system-pods=false
            - --scale-down-enabled=true
            - --scale-down-delay-after-add=2m
            - --scale-down-unneeded-time=2m
          env:
            - name: AWS_REGION
              value: us-west-1
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: cluster-autoscaler-aws-credentials
                  key: AWS_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: cluster-autoscaler-aws-credentials
                  key: AWS_SECRET_ACCESS_KEY
          volumeMounts:
            - name: ssl-certs
              mountPath: /etc/ssl/certs/ca-certificates.crt
              readOnly: true
          imagePullPolicy: "Always"
      volumes:
        - name: ssl-certs
          hostPath:
            path: "/etc/ssl/certs/ca-bundle.crt"
      nodeSelector:
        kubernetes.io/os: linux
EOF

# Step 5: Wait for deployment
echo "Step 5: Waiting for autoscaler deployment..."
sleep 30

# Step 6: Add ASG tags
echo "Step 6: Adding required ASG tags..."
ASG_NAMES=$(aws autoscaling describe-auto-scaling-groups \
    --region us-west-1 \
    --profile root-account03 \
    --query 'AutoScalingGroups[?contains(Tags[?Key==`eks:cluster-name`].Value, `eks-cluster-root-account03-us-west-1-diuh`)].AutoScalingGroupName' \
    --output text)

if [ ! -z "$ASG_NAMES" ]; then
    echo "Found ASGs: $ASG_NAMES"
    for asg in $ASG_NAMES; do
        echo "Adding autoscaler tags to ASG: $asg"
        
        aws autoscaling create-or-update-tags \
            --tags "ResourceId=$asg,ResourceType=auto-scaling-group,Key=k8s.io/cluster-autoscaler/enabled,Value=true,PropagateAtLaunch=false" \
            --region us-west-1 \
            --profile root-account03
        
        aws autoscaling create-or-update-tags \
            --tags "ResourceId=$asg,ResourceType=auto-scaling-group,Key=k8s.io/cluster-autoscaler/eks-cluster-root-account03-us-west-1-diuh,Value=owned,PropagateAtLaunch=false" \
            --region us-west-1 \
            --profile root-account03
        
        echo "✅ Tags added to ASG: $asg"
        
        # Show current ASG config
        echo "Current ASG config:"
        aws autoscaling describe-auto-scaling-groups \
            --auto-scaling-group-names $asg \
            --region us-west-1 \
            --profile root-account03 \
            --query 'AutoScalingGroups[0].{Name:AutoScalingGroupName,Min:MinSize,Desired:DesiredCapacity,Max:MaxSize}' \
            --output table
    done
else
    echo "❌ No ASGs found. Listing all ASGs to debug..."
    aws autoscaling describe-auto-scaling-groups \
        --region us-west-1 \
        --profile root-account03 \
        --query 'AutoScalingGroups[].{Name:AutoScalingGroupName,Tags:Tags[?Key==`eks:cluster-name`]}' \
        --output table
fi

# Step 7: Final verification
echo -e "\nStep 7: Final verification..."
sleep 30

echo "Autoscaler pod status:"
kubectl get po -n kube-system -l app=cluster-autoscaler

echo -e "\nSecret verification:"
kubectl get secret cluster-autoscaler-aws-credentials -n kube-system

echo -e "\nAutoscaler logs:"
kubectl logs -l app=cluster-autoscaler -n kube-system --tail=15

echo -e "\nCluster status:"
echo "Nodes: $(kubectl get nodes --no-headers | wc -l)"
echo "Stress pods: $(kubectl get po -l app=stress-test --no-headers | wc -l)"

echo -e "\n✅ Setup complete!"
echo "Monitor with: watch 'kubectl get po -n kube-system -l app=cluster-autoscaler; echo; kubectl get nodes; echo; kubectl get po -l app=stress-test'"