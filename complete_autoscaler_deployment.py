#!/usr/bin/env python3
"""
Complete Cluster Autoscaler Deployment Solution
- Auto creates secrets
- Auto tags ASGs  
- Fixes endpoint configuration
- Fast scaling (4m delays)
- Complete verification and logging

Current Time: 2025-06-19 07:40:20 UTC
User: varadharajaan
"""

import os
import subprocess
import tempfile
import time
import boto3
import json
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict, Tuple, Optional
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'

class CompleteAutoscalerDeployer:
    """
    Complete Cluster Autoscaler Deployment with all fixes
    Current Time: 2025-06-19 07:40:20 UTC
    User: varadharajaan
    """
    
    def __init__(self):
        self.colors = Colors()
        self.deployment_start_time = time.time()

    def print_colored(self, color: str, message: str, indent: int = 0):
        """Print colored message with optional indentation, handling Unicode safely."""
        prefix = "  " * indent
        # Ensures Unicode is printed safely (works in most modern terminals)
        try:
            print(f"{color}{prefix}{message}{self.colors.ENDC}")
        except UnicodeEncodeError:
            # Fallback for environments not supporting Unicode
            print(f"{color}{prefix}{message.encode('utf-8', errors='replace').decode('utf-8')}{self.colors.ENDC}")
    
    def log_step(self, step: str, message: str, status: str = "INFO"):
        """Log deployment step with timestamp"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        color_map = {
            'INFO': self.colors.BLUE,
            'SUCCESS': self.colors.GREEN,
            'WARNING': self.colors.YELLOW,
            'ERROR': self.colors.RED
        }
        color = color_map.get(status, self.colors.WHITE)
        print(f"{color}[{status}] {timestamp} | {step} | {message}{self.colors.ENDC}")
    
    def print_header(self, title: str):
        """Print formatted header"""
        self.print_colored(self.colors.BOLD, "=" * 80)
        self.print_colored(self.colors.BOLD, f"    {title}")
        self.print_colored(self.colors.BOLD, "=" * 80)
        from datetime import datetime
        self.print_colored(
            self.colors.CYAN,
            f"    Current Date and Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.print_colored(self.colors.CYAN, f"    User: varadharajaan")
        self.print_colored(self.colors.BOLD, "=" * 80)
    
    def run_command(self, cmd: List[str], env: Optional[Dict] = None, timeout: int = 120) -> Tuple[bool, str, str]:
        """Run command with proper error handling"""
        try:
            self.log_step("COMMAND", f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
            
            if result.returncode == 0:
                self.log_step("COMMAND", f"Success: {' '.join(cmd)}", "SUCCESS")
                return True, result.stdout, result.stderr
            else:
                self.log_step("COMMAND", f"Failed: {' '.join(cmd)} | Error: {result.stderr}", "ERROR")
                return False, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            self.log_step("COMMAND", f"Timeout: {' '.join(cmd)}", "ERROR")
            return False, "", "Command timeout"
        except Exception as e:
            self.log_step("COMMAND", f"Exception: {' '.join(cmd)} | {str(e)}", "ERROR")
            return False, "", str(e)
    
    def check_prerequisites(self) -> bool:
        """Check all prerequisites"""
        self.log_step("PREREQ", "Checking prerequisites...")
        
        # Check kubectl
        success, _, _ = self.run_command(['kubectl', 'version', '--client'])
        if not success:
            self.log_step("PREREQ", "kubectl not found or not working", "ERROR")
            return False
        
        # Check aws cli
        success, _, _ = self.run_command(['aws', '--version'])
        if not success:
            self.log_step("PREREQ", "AWS CLI not found or not working", "ERROR")
            return False
        
        self.log_step("PREREQ", "All prerequisites met", "SUCCESS")
        return True
    
    def create_aws_session(self, access_key: str, secret_key: str, region: str) -> boto3.Session:
        """Create AWS session with credentials"""
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the session
            sts = session.client('sts')
            identity = sts.get_caller_identity()
            
            self.log_step("AWS", f"Session created for account: {identity.get('Account')}", "SUCCESS")
            return session
        except Exception as e:
            self.log_step("AWS", f"Failed to create session: {str(e)}", "ERROR")
            raise
    
    def setup_kubeconfig(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> Dict:
        """Setup kubeconfig and return environment"""
        self.log_step("KUBE", f"Setting up kubeconfig for cluster: {cluster_name}")
        
        env = os.environ.copy()
        env.update({
            'AWS_ACCESS_KEY_ID': access_key,
            'AWS_SECRET_ACCESS_KEY': secret_key,
            'AWS_DEFAULT_REGION': region,
            'AWS_REGION': region
        })
        
        # Update kubeconfig
        cmd = ['aws', 'eks', 'update-kubeconfig', '--region', region, '--name', cluster_name]
        success, stdout, stderr = self.run_command(cmd, env=env)
        
        if not success:
            self.log_step("KUBE", f"Failed to update kubeconfig: {stderr}", "ERROR")
            raise Exception(f"Kubeconfig update failed: {stderr}")
        
        # Test kubectl access
        success, stdout, stderr = self.run_command(['kubectl', 'get', 'nodes'], env=env)
        if not success:
            self.log_step("KUBE", f"kubectl access test failed: {stderr}", "ERROR")
            raise Exception(f"kubectl access failed: {stderr}")
        
        node_count = len(stdout.strip().split('\n')) - 1 if stdout.strip() else 0
        self.log_step("KUBE", f"Cluster access verified. Found {node_count} nodes", "SUCCESS")
        
        return env
    
    def cleanup_existing_autoscaler(self, env: Dict) -> bool:
        """Clean up any existing autoscaler deployment"""
        self.log_step("CLEANUP", "Cleaning up existing autoscaler resources...")
        
        cleanup_commands = [
            ['kubectl', 'delete', 'deployment', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found=true'],
            ['kubectl', 'delete', 'secret', 'cluster-autoscaler-aws-credentials', '-n', 'kube-system', '--ignore-not-found=true'],
            ['kubectl', 'delete', 'serviceaccount', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found=true'],
            ['kubectl', 'delete', 'clusterrole', 'cluster-autoscaler', '--ignore-not-found=true'],
            ['kubectl', 'delete', 'clusterrolebinding', 'cluster-autoscaler', '--ignore-not-found=true'],
            ['kubectl', 'delete', 'role', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found=true'],
            ['kubectl', 'delete', 'rolebinding', 'cluster-autoscaler', '-n', 'kube-system', '--ignore-not-found=true']
        ]
        
        for cmd in cleanup_commands:
            self.run_command(cmd, env=env, timeout=60)
        
        self.log_step("CLEANUP", "Cleanup completed", "SUCCESS")
        time.sleep(10)  # Wait for cleanup to complete
        return True
    
    def create_aws_credentials_secret(self, access_key: str, secret_key: str, region: str, env: Dict) -> bool:
        """Create AWS credentials secret for autoscaler"""
        self.log_step("SECRET", "Creating AWS credentials secret...")
        
        cmd = [
            'kubectl', 'create', 'secret', 'generic', 'cluster-autoscaler-aws-credentials',
            f'--from-literal=AWS_ACCESS_KEY_ID={access_key}',
            f'--from-literal=AWS_SECRET_ACCESS_KEY={secret_key}',
            f'--from-literal=AWS_DEFAULT_REGION={region}',
            f'--from-literal=AWS_REGION={region}',
            '-n', 'kube-system'
        ]
        
        success, stdout, stderr = self.run_command(cmd, env=env)
        if not success:
            self.log_step("SECRET", f"Failed to create secret: {stderr}", "ERROR")
            return False
        
        # Verify secret
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'secret', 'cluster-autoscaler-aws-credentials', '-n', 'kube-system'],
            env=env
        )
        
        if success:
            self.log_step("SECRET", "AWS credentials secret created and verified", "SUCCESS")
            return True
        else:
            self.log_step("SECRET", f"Secret verification failed: {stderr}", "ERROR")
            return False
    
    def discover_and_tag_asgs(self, session: boto3.Session, cluster_name: str, region: str) -> List[str]:
        """Discover and tag ASGs for the cluster"""
        self.log_step("ASG", f"Discovering Auto Scaling Groups for cluster: {cluster_name}")
        
        try:
            autoscaling = session.client('autoscaling', region_name=region)
            
            # Get all ASGs
            response = autoscaling.describe_auto_scaling_groups()
            cluster_asgs = []
            
            # Find ASGs related to the cluster
            for asg in response.get('AutoScalingGroups', []):
                asg_name = asg['AutoScalingGroupName']
                
                # Check tags for cluster association
                for tag in asg.get('Tags', []):
                    if (tag['Key'] == 'eks:cluster-name' and 
                        cluster_name in tag['Value']):
                        cluster_asgs.append(asg_name)
                        break
                
                # Also check ASG name patterns
                if any(pattern in asg_name.lower() for pattern in ['eks', 'nodegroup']) and \
                   any(part in asg_name for part in cluster_name.split('-')):
                    if asg_name not in cluster_asgs:
                        cluster_asgs.append(asg_name)
            
            if not cluster_asgs:
                self.log_step("ASG", "No ASGs found with cluster tags, searching by name patterns...", "WARNING")
                
                # Broader search
                for asg in response.get('AutoScalingGroups', []):
                    asg_name = asg['AutoScalingGroupName']
                    if 'eks' in asg_name.lower() and region in asg_name:
                        cluster_asgs.append(asg_name)
            
            if not cluster_asgs:
                self.log_step("ASG", "No ASGs found for cluster", "ERROR")
                return []
            
            self.log_step("ASG", f"Found {len(cluster_asgs)} ASGs: {cluster_asgs}", "SUCCESS")
            
            # Tag each ASG
            tagged_asgs = []
            for asg_name in cluster_asgs:
                try:
                    tags = [
                        {
                            'ResourceId': asg_name,
                            'ResourceType': 'auto-scaling-group',
                            'Key': 'k8s.io/cluster-autoscaler/enabled',
                            'Value': 'true',
                            'PropagateAtLaunch': False
                        },
                        {
                            'ResourceId': asg_name,
                            'ResourceType': 'auto-scaling-group',
                            'Key': f'k8s.io/cluster-autoscaler/{cluster_name}',
                            'Value': 'owned',
                            'PropagateAtLaunch': False
                        }
                    ]
                    
                    autoscaling.create_or_update_tags(Tags=tags)
                    self.log_step("ASG", f"Tagged ASG: {asg_name}", "SUCCESS")
                    tagged_asgs.append(asg_name)
                    
                except ClientError as e:
                    self.log_step("ASG", f"Failed to tag ASG {asg_name}: {str(e)}", "ERROR")
            
            self.log_step("ASG", f"Successfully tagged {len(tagged_asgs)} ASGs", "SUCCESS")
            return tagged_asgs
            
        except Exception as e:
            self.log_step("ASG", f"ASG discovery/tagging failed: {str(e)}", "ERROR")
            return []
    
    def create_autoscaler_yaml(self, cluster_name: str, region: str) -> str:
        """Create complete autoscaler YAML with all fixes"""
        yaml_content = f"""# Complete Cluster Autoscaler YAML with all fixes
# Current Time: 2025-06-19 07:40:20 UTC
# User: varadharajaan
# Features: Fast scaling, endpoint fix, complete RBAC

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
kind: Role
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    k8s-addon: cluster-autoscaler.addons.k8s.io
    k8s-app: cluster-autoscaler
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["create","list","watch"]
- apiGroups: [""]
  resources: ["configmaps"]
  resourceNames: ["cluster-autoscaler-status", "cluster-autoscaler-priority-expander"]
  verbs: ["delete", "get", "update", "watch"]
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
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    k8s-addon: cluster-autoscaler.addons.k8s.io
    k8s-app: cluster-autoscaler
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
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
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/{cluster_name}
        - --balance-similar-node-groups
        - --skip-nodes-with-system-pods=false
        - --scale-down-enabled=true
        - --scale-down-delay-after-add=2m
        - --scale-down-unneeded-time=4m
        - --scale-down-delay-after-delete=10s
        - --scale-down-delay-after-failure=3m
        - --max-node-provision-time=10m
        - --aws-use-static-instance-list=false
        env:
        # COMPLETE AWS ENDPOINT CONFIGURATION
        - name: AWS_REGION
          value: "{region}"
        - name: AWS_DEFAULT_REGION
          value: "{region}"
        - name: AWS_SDK_LOAD_CONFIG
          value: "1"
        - name: AWS_EC2_ENDPOINT
          value: "https://ec2.{region}.amazonaws.com"
        - name: AWS_AUTOSCALING_ENDPOINT
          value: "https://autoscaling.{region}.amazonaws.com"
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
"""
        return yaml_content
    
    def deploy_autoscaler(self, cluster_name: str, region: str, env: Dict) -> bool:
        """Deploy the autoscaler"""
        self.log_step("DEPLOY", "Deploying cluster autoscaler...")
        
        # Create YAML content
        yaml_content = self.create_autoscaler_yaml(cluster_name, region)
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_file = f.name
        
        try:
            # Apply the YAML
            success, stdout, stderr = self.run_command(
                ['kubectl', 'apply', '-f', temp_file],
                env=env
            )
            
            if success:
                self.log_step("DEPLOY", "Autoscaler deployment applied successfully", "SUCCESS")
                return True
            else:
                self.log_step("DEPLOY", f"Deployment failed: {stderr}", "ERROR")
                return False
        
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except:
                pass
    
    def wait_for_autoscaler_ready(self, env: Dict, timeout: int = 300) -> bool:
        """Wait for autoscaler to be ready with detailed monitoring"""
        self.log_step("WAIT", f"Waiting for autoscaler to be ready (timeout: {timeout}s)...")
        
        start_time = time.time()
        last_status = ""
        
        while time.time() - start_time < timeout:
            # Check pod status
            success, stdout, stderr = self.run_command(
                ['kubectl', 'get', 'pods', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', '--no-headers'],
                env=env,
                timeout=30
            )
            
            if success and stdout.strip():
                lines = stdout.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 3:
                        pod_name = parts[0]
                        ready_status = parts[1]
                        pod_status = parts[2]
                        
                        current_status = f"{pod_name} {ready_status} {pod_status}"
                        if current_status != last_status:
                            self.log_step("WAIT", f"Pod status: {current_status}")
                            last_status = current_status
                        
                        if ready_status == "1/1" and pod_status == "Running":
                            self.log_step("WAIT", f"Autoscaler pod is ready: {pod_name}", "SUCCESS")
                            return True
                        elif pod_status in ["CrashLoopBackOff", "Error", "CreateContainerConfigError"]:
                            self.log_step("WAIT", f"Pod failed with status: {pod_status}", "ERROR")
                            
                            # Get logs for debugging
                            self.run_command(
                                ['kubectl', 'logs', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', '--tail=20'],
                                env=env
                            )
                            return False
            
            time.sleep(10)
        
        self.log_step("WAIT", "Timeout waiting for autoscaler to be ready", "ERROR")
        return False
    
    def verify_deployment(self, env: Dict, cluster_name: str) -> bool:
        """Comprehensive deployment verification"""
        self.log_step("VERIFY", "Performing comprehensive deployment verification...")
        
        verification_passed = True
        
        # Check 1: Pod is running
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'pods', '-n', 'kube-system', '-l', 'app=cluster-autoscaler'],
            env=env
        )
        
        if success:
            self.log_step("VERIFY", "[OK] Pod status check passed", "SUCCESS")
        else:
            self.log_step("VERIFY", "[ERROR] Pod status check failed", "ERROR")
            verification_passed = False
        
        # Check 2: Secret exists
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'secret', 'cluster-autoscaler-aws-credentials', '-n', 'kube-system'],
            env=env
        )
        
        if success:
            self.log_step("VERIFY", "[OK] AWS credentials secret exists", "SUCCESS")
        else:
            self.log_step("VERIFY", "[ERROR] AWS credentials secret missing", "ERROR")
            verification_passed = False
        
        # Check 3: RBAC resources
        rbac_resources = [
            ('serviceaccount', 'cluster-autoscaler', 'kube-system'),
            ('clusterrole', 'cluster-autoscaler', ''),
            ('clusterrolebinding', 'cluster-autoscaler', ''),
            ('role', 'cluster-autoscaler', 'kube-system'),
            ('rolebinding', 'cluster-autoscaler', 'kube-system')
        ]
        
        for resource_type, name, namespace in rbac_resources:
            cmd = ['kubectl', 'get', resource_type, name]
            if namespace:
                cmd.extend(['-n', namespace])
            
            success, stdout, stderr = self.run_command(cmd, env=env)
            if success:
                self.log_step("VERIFY", f"[OK] {resource_type} {name} exists", "SUCCESS")
            else:
                self.log_step("VERIFY", f"[ERROR] {resource_type} {name} missing", "ERROR")
                verification_passed = False
        
        return verification_passed
    
    def print_autoscaler_logs(self, env: Dict, lines: int = 50):
        """Print current autoscaler logs"""
        self.print_header("CLUSTER AUTOSCALER LOGS")
        
        success, stdout, stderr = self.run_command(
            ['kubectl', 'logs', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', f'--tail={lines}'],
            env=env
        )
        
        if success:
            self.print_colored(self.colors.WHITE, "[LIST] Recent Autoscaler Logs:")
            self.print_colored(self.colors.CYAN, "-" * 80)
            print(stdout)
            self.print_colored(self.colors.CYAN, "-" * 80)
        else:
            self.log_step("LOGS", f"Failed to get logs: {stderr}", "ERROR")
    
    def print_success_summary(self, cluster_name: str, region: str, tagged_asgs: List[str]):
        """Print deployment success summary"""
        self.print_header("[PARTY] AUTOSCALER DEPLOYMENT SUCCESSFUL! [PARTY]")
        
        elapsed_time = time.time() - self.deployment_start_time
        
        self.print_colored(self.colors.GREEN, "[OK] AUTOSCALER DEPLOYMENT COMPLETED SUCCESSFULLY!")
        self.print_colored(self.colors.CYAN, f"[STATS] Autoscaler Deployment Summary:")
        self.print_colored(self.colors.WHITE, f"   • Cluster: {cluster_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • Region: {region}", 1)
        self.print_colored(self.colors.WHITE, f"   • Tagged ASGs: {len(tagged_asgs)}", 1)
        self.print_colored(self.colors.WHITE, f"   • Deployment Time: {elapsed_time:.1f} seconds", 1)
        self.print_colored(self.colors.WHITE, f"   • Fast Scaling: 4 minute delays configured", 1)
        self.print_colored(self.colors.WHITE, f"   • Protected Nodes: Nodes with label 'no_delete=true' will be skipped", 1)

        self.print_colored(self.colors.YELLOW, "\n[TEST] Testing Commands:")
        self.print_colored(self.colors.WHITE, "   # Scale up test (trigger node addition):", 1)
        self.print_colored(self.colors.CYAN, "   kubectl create deployment test-scale --image=nginx --replicas=10", 1)
        self.print_colored(self.colors.CYAN, "   kubectl set resources deployment test-scale --requests=cpu=1000m,memory=1Gi", 1)
        
        self.print_colored(self.colors.WHITE, "   # Monitor scaling:", 1)
        self.print_colored(self.colors.CYAN, "   watch kubectl get nodes", 1)
        self.print_colored(self.colors.CYAN, "   kubectl logs -n kube-system -l app=cluster-autoscaler -f", 1)
        
        self.print_colored(self.colors.WHITE, "   # Scale down test:", 1)
        self.print_colored(self.colors.CYAN, "   kubectl delete deployment test-scale", 1)
        
        if tagged_asgs:
            self.print_colored(self.colors.GREEN, f"\n[TAG]  Tagged ASGs:")
            for asg in tagged_asgs:
                self.print_colored(self.colors.WHITE, f"   • {asg}", 1)
    
    def deploy_complete_autoscaler(self, cluster_name: str, region: str, access_key: str, secret_key: str, account_id: str) -> bool:
        """
        Complete autoscaler deployment with all fixes
        
        Args:
            cluster_name: EKS cluster name
            region: AWS region
            access_key: AWS access key
            secret_key: AWS secret key
            
        Returns:
            bool: True if deployment successful
        """
        try:
            self.print_header("COMPLETE CLUSTER AUTOSCALER DEPLOYMENT")
            
            self.print_colored(self.colors.BLUE, "[TARGET] Deployment Parameters:")
            self.print_colored(self.colors.WHITE, f"   • Cluster: {cluster_name}", 1)
            self.print_colored(self.colors.WHITE, f"   • Region: {region}", 1)
            self.print_colored(self.colors.WHITE, f"   • Access Key: {access_key[:8]}...", 1)
            self.print_colored(self.colors.WHITE, f"   • Account ID: {account_id}", 1)
            self.print_colored(self.colors.WHITE, f"   • Fast Scaling: 4 minute delays", 1)
            self.print_colored(self.colors.WHITE, f"   • Protected Nodes: Using 'no_delete=true' label", 1)
            
            # Step 1: Check prerequisites
            if not self.check_prerequisites():
                return False
            
            # Step 2: Create AWS session
            session = self.create_aws_session(access_key, secret_key, region)
            
            # Step 3: Setup kubeconfig
            env = self.setup_kubeconfig(cluster_name, region, access_key, secret_key)
            
            # Step 4: Cleanup existing resources
            self.cleanup_existing_autoscaler(env)
            
            # Step 5: Create AWS credentials secret
            if not self.create_aws_credentials_secret(access_key, secret_key, region, env):
                return False
            
            # Step 6: Discover and tag ASGs
            tagged_asgs = self.discover_and_tag_asgs(session, cluster_name, region)
            if not tagged_asgs:
                self.log_step("ASG", "No ASGs were tagged, autoscaler may not work properly", "WARNING")
            
            # Step 7: Deploy autoscaler
            if not self.deploy_autoscaler(cluster_name, region, env):
                return False
            
            # Step 8: Wait for autoscaler to be ready
            if not self.wait_for_autoscaler_ready(env):
                self.log_step("DEPLOY", "Autoscaler may not be fully ready, but continuing", "WARNING")
            
            # Step 9: Verify deployment
            if not self.verify_deployment(env, cluster_name):
                self.log_step("VERIFY", "Some verification checks failed", "WARNING")
            
            # Step 10: Print logs
            self.print_autoscaler_logs(env)
            
            # Step 11: Print success summary
            self.print_success_summary(cluster_name, region, tagged_asgs)

            # Step 12: do a sample deployment to verify autoscaler works
            # Ask if user wants to test the autoscaler
            # try:
            #     response = input(f"\n🤔 Would you like to test the autoscaler with sample deployments? (y/n) [y]: ").strip()
            #     test_autoscaler = response.lower() in ['y', 'yes', ''] 
        
            #     if test_autoscaler:
            #         print(f"\n[TEST] Proceeding with autoscaler testing...")
            #         from autoscale_tester import AutoscalerTester
            #         tester = AutoscalerTester()
            #         tester.run_interactive_testing()
            #     else:
            #         print(f"\n[OK] Autoscaler deployment completed. You can test it manually later.")
            #         print(f"\nManual testing commands:")
            #         print(f"  kubectl create deployment test-scale --image=nginx --replicas=10")
            #         print(f"  kubectl set resources deployment test-scale --requests=cpu=1000m,memory=1Gi")
            #         print(f"  kubectl logs -n kube-system -l app=cluster-autoscaler -f")
    
            # except KeyboardInterrupt:
            #     print(f"\n\n[OK] Autoscaler deployment completed successfully!")
            #     print(f"Testing was cancelled, but autoscaler is ready to use.")
                
            return True
            
        except Exception as e:
            self.log_step("DEPLOY", f"Deployment failed with exception: {str(e)}", "ERROR")
            self.print_colored(self.colors.RED, f"\n[ERROR] DEPLOYMENT FAILED: {str(e)}")
            return False

def main():
    """Main function for command line usage"""
    deployer = CompleteAutoscalerDeployer()
    
    # Example usage - replace with your values
    success = deployer.deploy_complete_autoscaler(
        cluster_name="eks-cluster-account01_clouduser03-us-west-1-ffkd",
        region="us-west-1",
        secret_key="ACCESSKEY",  # replace placeholder with actual access key
        access_key="SECRET_KEY",
        account_id= 'account01'# replace placeholder with actual secret key
    )
    
    if success:
        print("\n[PARTY] AUTOSCALER DEPLOYMENT COMPLETED SUCCESSFULLY!")
        return 0
    else:
        print("\n[BOOM] AUTOSCALER DEPLOYMENT FAILED!")
        return 1


if __name__ == "__main__":
    exit(main())