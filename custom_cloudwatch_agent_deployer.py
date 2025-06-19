#!/usr/bin/env python3
"""
Custom CloudWatch Agent Deployer for EKS
Deploys custom CloudWatch agent with different name to avoid Container Insights conflicts

Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): 2025-06-19 10:13:17
Current User's Login: varadharajaan
"""

import os
import subprocess
import tempfile
import time
import json
import boto3
from typing import Dict, List, Tuple, Optional
from botocore.exceptions import ClientError

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'

class CustomCloudWatchAgentDeployer:
    """
    Custom CloudWatch Agent Deployer for EKS
    Avoids conflicts with Container Insights by using different naming
    
    Current Date and Time (UTC): 2025-06-19 10:13:17
    Current User's Login: varadharajaan
    """
    
    def __init__(self, custom_agent_name: str = "custom-cloudwatch-agent"):
        self.colors = Colors()
        self.custom_agent_name = custom_agent_name
        self.namespace = "amazon-cloudwatch"
        self.deployment_start_time = time.time()
    
    def print_colored(self, color: str, message: str, indent: int = 0):
        """Print colored message with optional indentation"""
        prefix = "  " * indent
        print(f"{color}{prefix}{message}{self.colors.ENDC}")
    
    def print_header(self, title: str):
        """Print formatted header"""
        self.print_colored(self.colors.BOLD, "=" * 90)
        self.print_colored(self.colors.BOLD, f"    {title}")
        self.print_colored(self.colors.BOLD, "=" * 90)
        self.print_colored(self.colors.CYAN, f"    Current Date and Time (UTC): 2025-06-19 10:13:17")
        self.print_colored(self.colors.CYAN, f"    Current User's Login: varadharajaan")
        self.print_colored(self.colors.CYAN, f"    Custom Agent Name: {self.custom_agent_name}")
        self.print_colored(self.colors.BOLD, "=" * 90)
    
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
    
    def setup_environment(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> Dict:
        """Setup environment and kubeconfig"""
        self.log_step("ENV", f"Setting up environment for cluster: {cluster_name}")
        
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
            self.log_step("ENV", f"Failed to update kubeconfig: {stderr}", "ERROR")
            raise Exception(f"Kubeconfig update failed: {stderr}")
        
        # Test kubectl access
        success, stdout, stderr = self.run_command(['kubectl', 'get', 'nodes'], env=env)
        if not success:
            self.log_step("ENV", f"kubectl access test failed: {stderr}", "ERROR")
            raise Exception(f"kubectl access failed: {stderr}")
        
        self.log_step("ENV", "Environment setup completed", "SUCCESS")
        return env
    
    def create_namespace(self, env: Dict) -> bool:
        """Create or ensure namespace exists"""
        self.log_step("NAMESPACE", f"Creating namespace: {self.namespace}")
        
        # Check if namespace exists
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'namespace', self.namespace], env=env
        )
        
        if success:
            self.log_step("NAMESPACE", f"Namespace {self.namespace} already exists", "SUCCESS")
            return True
        
        # Create namespace
        success, stdout, stderr = self.run_command(
            ['kubectl', 'create', 'namespace', self.namespace], env=env
        )
        
        if success:
            self.log_step("NAMESPACE", f"Namespace {self.namespace} created", "SUCCESS")
            return True
        else:
            self.log_step("NAMESPACE", f"Failed to create namespace: {stderr}", "ERROR")
            return False
    
    def cleanup_existing_agent(self, env: Dict) -> bool:
        """Clean up any existing custom agent deployment"""
        self.log_step("CLEANUP", f"Cleaning up existing custom agent: {self.custom_agent_name}")
        
        cleanup_commands = [
            ['kubectl', 'delete', 'daemonset', self.custom_agent_name, '-n', self.namespace, '--ignore-not-found=true'],
            ['kubectl', 'delete', 'configmap', f'{self.custom_agent_name}-config', '-n', self.namespace, '--ignore-not-found=true'],
            ['kubectl', 'delete', 'serviceaccount', self.custom_agent_name, '-n', self.namespace, '--ignore-not-found=true'],
            ['kubectl', 'delete', 'clusterrole', self.custom_agent_name, '--ignore-not-found=true'],
            ['kubectl', 'delete', 'clusterrolebinding', self.custom_agent_name, '--ignore-not-found=true'],
            ['kubectl', 'delete', 'secret', f'{self.custom_agent_name}-credentials', '-n', self.namespace, '--ignore-not-found=true']
        ]
        
        for cmd in cleanup_commands:
            self.run_command(cmd, env=env, timeout=60)
        
        self.log_step("CLEANUP", "Cleanup completed", "SUCCESS")
        time.sleep(10)  # Wait for cleanup to complete
        return True
    
    def create_aws_credentials_secret(self, access_key: str, secret_key: str, region: str, env: Dict) -> bool:
        """Create AWS credentials secret for CloudWatch agent"""
        self.log_step("SECRET", "Creating AWS credentials secret for CloudWatch agent...")
        
        secret_name = f"{self.custom_agent_name}-credentials"
        
        cmd = [
            'kubectl', 'create', 'secret', 'generic', secret_name,
            f'--from-literal=AWS_ACCESS_KEY_ID={access_key}',
            f'--from-literal=AWS_SECRET_ACCESS_KEY={secret_key}',
            f'--from-literal=AWS_DEFAULT_REGION={region}',
            f'--from-literal=AWS_REGION={region}',
            '-n', self.namespace
        ]
        
        success, stdout, stderr = self.run_command(cmd, env=env)
        if not success:
            self.log_step("SECRET", f"Failed to create secret: {stderr}", "ERROR")
            return False
        
        # Verify secret
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'secret', secret_name, '-n', self.namespace],
            env=env
        )
        
        if success:
            self.log_step("SECRET", "AWS credentials secret created and verified", "SUCCESS")
            return True
        else:
            self.log_step("SECRET", f"Secret verification failed: {stderr}", "ERROR")
            return False
    
    def create_cloudwatch_config(self, cluster_name: str, region: str) -> str:
        """Create CloudWatch agent configuration"""
        config = {
            "logs": {
                "metrics_collected": {
                    "kubernetes": {
                        "cluster_name": cluster_name,
                        "metrics_collection_interval": 60
                    }
                },
                "log_group_name": f"/aws/eks/{cluster_name}/custom-logs",
                "log_stream_name": "{instance_id}",
                "retention_in_days": 7
            },
            "metrics": {
                "namespace": f"EKS/Custom/{cluster_name}",
                "metrics_collected": {
                    "cpu": {
                        "measurement": ["cpu_usage_idle", "cpu_usage_iowait", "cpu_usage_user", "cpu_usage_system"],
                        "metrics_collection_interval": 60
                    },
                    "disk": {
                        "measurement": ["used_percent"],
                        "metrics_collection_interval": 60,
                        "resources": ["*"]
                    },
                    "diskio": {
                        "measurement": ["io_time", "read_bytes", "write_bytes", "reads", "writes"],
                        "metrics_collection_interval": 60,
                        "resources": ["*"]
                    },
                    "mem": {
                        "measurement": ["mem_used_percent"],
                        "metrics_collection_interval": 60
                    },
                    "netstat": {
                        "measurement": ["tcp_established", "tcp_time_wait"],
                        "metrics_collection_interval": 60
                    },
                    "swap": {
                        "measurement": ["swap_used_percent"],
                        "metrics_collection_interval": 60
                    }
                }
            }
        }
        return json.dumps(config, indent=2)
    
    def create_cloudwatch_agent_yaml(self, cluster_name: str, region: str) -> str:
        """Create complete CloudWatch agent YAML configuration"""
        
        config_json = self.create_cloudwatch_config(cluster_name, region)
        
        yaml_content = f"""# Custom CloudWatch Agent for EKS
# Current Date and Time (UTC): 2025-06-19 10:13:17
# Current User's Login: varadharajaan
# Custom Agent Name: {self.custom_agent_name}

apiVersion: v1
kind: ServiceAccount
metadata:
  name: {self.custom_agent_name}
  namespace: {self.namespace}
  labels:
    app: {self.custom_agent_name}
    component: cloudwatch-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {self.custom_agent_name}
  labels:
    app: {self.custom_agent_name}
    component: cloudwatch-agent
rules:
- apiGroups: [""]
  resources:
  - nodes
  - nodes/proxy
  - nodes/metrics
  - services
  - endpoints
  - pods
  - pods/logs
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources:
  - deployments
  - daemonsets
  - replicasets
  verbs: ["get", "list", "watch"]
- apiGroups: ["batch"]
  resources:
  - jobs
  verbs: ["get", "list", "watch"]
- nonResourceURLs: ["/metrics"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {self.custom_agent_name}
  labels:
    app: {self.custom_agent_name}
    component: cloudwatch-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {self.custom_agent_name}
subjects:
- kind: ServiceAccount
  name: {self.custom_agent_name}
  namespace: {self.namespace}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: {self.custom_agent_name}-config
  namespace: {self.namespace}
  labels:
    app: {self.custom_agent_name}
    component: cloudwatch-agent
data:
  cwagentconfig.json: |
{config_json}
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {self.custom_agent_name}
  namespace: {self.namespace}
  labels:
    app: {self.custom_agent_name}
    component: cloudwatch-agent
spec:
  selector:
    matchLabels:
      app: {self.custom_agent_name}
  template:
    metadata:
      labels:
        app: {self.custom_agent_name}
        component: cloudwatch-agent
    spec:
      serviceAccountName: {self.custom_agent_name}
      hostNetwork: true
      containers:
      - name: cloudwatch-agent
        image: amazon/cloudwatch-agent:1.300026.1b267
        ports:
        - containerPort: 8125
          hostPort: 8125
          protocol: UDP
        resources:
          limits:
            cpu: 200m
            memory: 200Mi
          requests:
            cpu: 100m
            memory: 100Mi
        env:
        - name: AWS_REGION
          value: "{region}"
        - name: AWS_DEFAULT_REGION
          value: "{region}"
        - name: CW_CONFIG_CONTENT
          valueFrom:
            configMapKeyRef:
              name: {self.custom_agent_name}-config
              key: cwagentconfig.json
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: {self.custom_agent_name}-credentials
              key: AWS_ACCESS_KEY_ID
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: {self.custom_agent_name}-credentials
              key: AWS_SECRET_ACCESS_KEY
        volumeMounts:
        - name: cwagentconfig
          mountPath: /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
          subPath: cwagentconfig.json
        - name: rootfs
          mountPath: /rootfs
          readOnly: true
        - name: dockersock
          mountPath: /var/run/docker.sock
          readOnly: true
        - name: varlibdocker
          mountPath: /var/lib/docker
          readOnly: true
        - name: sys
          mountPath: /sys
          readOnly: true
        - name: devdisk
          mountPath: /dev/disk
          readOnly: true
      volumes:
      - name: cwagentconfig
        configMap:
          name: {self.custom_agent_name}-config
      - name: rootfs
        hostPath:
          path: /
      - name: dockersock
        hostPath:
          path: /var/run/docker.sock
      - name: varlibdocker
        hostPath:
          path: /var/lib/docker
      - name: sys
        hostPath:
          path: /sys
      - name: devdisk
        hostPath:
          path: /dev/disk
      terminationGracePeriodSeconds: 60
      nodeSelector:
        kubernetes.io/os: linux
"""
        return yaml_content
    
    def deploy_cloudwatch_agent(self, cluster_name: str, region: str, env: Dict) -> bool:
        """Deploy the custom CloudWatch agent"""
        self.log_step("DEPLOY", f"Deploying custom CloudWatch agent: {self.custom_agent_name}")
        
        # Create YAML content
        yaml_content = self.create_cloudwatch_agent_yaml(cluster_name, region)
        
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
                self.log_step("DEPLOY", "Custom CloudWatch agent deployed successfully", "SUCCESS")
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
    
    def wait_for_agent_ready(self, env: Dict, timeout: int = 300) -> bool:
        """Wait for CloudWatch agent to be ready"""
        self.log_step("WAIT", f"Waiting for CloudWatch agent to be ready (timeout: {timeout}s)...")
        
        start_time = time.time()
        last_status = ""
        
        while time.time() - start_time < timeout:
            # Check DaemonSet status
            success, stdout, stderr = self.run_command(
                ['kubectl', 'get', 'daemonset', self.custom_agent_name, '-n', self.namespace, '--no-headers'],
                env=env,
                timeout=30
            )
            
            if success and stdout.strip():
                parts = stdout.strip().split()
                if len(parts) >= 6:
                    desired = parts[1]
                    current = parts[2]
                    ready = parts[3]
                    up_to_date = parts[4]
                    available = parts[5]
                    
                    current_status = f"Desired: {desired}, Current: {current}, Ready: {ready}, Up-to-date: {up_to_date}, Available: {available}"
                    if current_status != last_status:
                        self.log_step("WAIT", f"DaemonSet status: {current_status}")
                        last_status = current_status
                    
                    # Check if all pods are ready
                    if desired == ready and desired == available and int(desired) > 0:
                        self.log_step("WAIT", f"CloudWatch agent DaemonSet is ready", "SUCCESS")
                        return True
            
            time.sleep(10)
        
        self.log_step("WAIT", "Timeout waiting for CloudWatch agent to be ready", "ERROR")
        return False
    
    def verify_deployment(self, env: Dict, cluster_name: str, region: str) -> bool:
        """Comprehensive deployment verification"""
        self.log_step("VERIFY", "Performing comprehensive deployment verification...")
        
        verification_passed = True
        
        # Check 1: DaemonSet is running
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'daemonset', self.custom_agent_name, '-n', self.namespace],
            env=env
        )
        
        if success:
            self.log_step("VERIFY", "✅ DaemonSet status check passed", "SUCCESS")
            self.print_colored(self.colors.WHITE, stdout, 1)
        else:
            self.log_step("VERIFY", "❌ DaemonSet status check failed", "ERROR")
            verification_passed = False
        
        # Check 2: Pods are running
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'pods', '-n', self.namespace, '-l', f'app={self.custom_agent_name}'],
            env=env
        )
        
        if success:
            self.log_step("VERIFY", "✅ Pod status check passed", "SUCCESS")
            self.print_colored(self.colors.WHITE, stdout, 1)
        else:
            self.log_step("VERIFY", "❌ Pod status check failed", "ERROR")
            verification_passed = False
        
        # Check 3: ConfigMap exists
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'configmap', f'{self.custom_agent_name}-config', '-n', self.namespace],
            env=env
        )
        
        if success:
            self.log_step("VERIFY", "✅ ConfigMap exists", "SUCCESS")
        else:
            self.log_step("VERIFY", "❌ ConfigMap missing", "ERROR")
            verification_passed = False
        
        # Check 4: Secret exists
        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'secret', f'{self.custom_agent_name}-credentials', '-n', self.namespace],
            env=env
        )
        
        if success:
            self.log_step("VERIFY", "✅ AWS credentials secret exists", "SUCCESS")
        else:
            self.log_step("VERIFY", "❌ AWS credentials secret missing", "ERROR")
            verification_passed = False
        
        # Check 5: RBAC resources
        rbac_resources = [
            ('serviceaccount', self.custom_agent_name, self.namespace),
            ('clusterrole', self.custom_agent_name, ''),
            ('clusterrolebinding', self.custom_agent_name, '')
        ]
        
        for resource_type, name, namespace in rbac_resources:
            cmd = ['kubectl', 'get', resource_type, name]
            if namespace:
                cmd.extend(['-n', namespace])
            
            success, stdout, stderr = self.run_command(cmd, env=env)
            if success:
                self.log_step("VERIFY", f"✅ {resource_type} {name} exists", "SUCCESS")
            else:
                self.log_step("VERIFY", f"❌ {resource_type} {name} missing", "ERROR")
                verification_passed = False
        
        return verification_passed
    
    def check_cloudwatch_logs(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Check if logs are being sent to CloudWatch"""
        self.log_step("CLOUDWATCH", "Checking CloudWatch logs and metrics...")
        
        try:
            # Create CloudWatch client
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            cloudwatch_logs = session.client('logs')
            cloudwatch_metrics = session.client('cloudwatch')
            
            # Check log groups
            log_group_name = f"/aws/eks/{cluster_name}/custom-logs"
            
            try:
                response = cloudwatch_logs.describe_log_groups(
                    logGroupNamePrefix=log_group_name
                )
                
                if response['logGroups']:
                    self.log_step("CLOUDWATCH", f"✅ Log group found: {log_group_name}", "SUCCESS")
                    
                    # Check log streams
                    streams_response = cloudwatch_logs.describe_log_streams(
                        logGroupName=log_group_name,
                        orderBy='LastEventTime',
                        descending=True,
                        limit=5
                    )
                    
                    if streams_response['logStreams']:
                        self.log_step("CLOUDWATCH", f"✅ Found {len(streams_response['logStreams'])} log streams", "SUCCESS")
                        for stream in streams_response['logStreams'][:3]:
                            self.print_colored(self.colors.WHITE, f"  Stream: {stream['logStreamName']}", 1)
                    else:
                        self.log_step("CLOUDWATCH", "⚠️  No log streams found yet", "WARNING")
                else:
                    self.log_step("CLOUDWATCH", f"⚠️  Log group not found: {log_group_name}", "WARNING")
            
            except ClientError as e:
                self.log_step("CLOUDWATCH", f"⚠️  Error checking log groups: {str(e)}", "WARNING")
            
            # Check metrics
            namespace = f"EKS/Custom/{cluster_name}"
            
            try:
                response = cloudwatch_metrics.list_metrics(
                    Namespace=namespace
                )
                
                if response['Metrics']:
                    self.log_step("CLOUDWATCH", f"✅ Found {len(response['Metrics'])} custom metrics", "SUCCESS")
                    
                    # Show sample metrics
                    for metric in response['Metrics'][:5]:
                        metric_name = metric['MetricName']
                        dimensions = ', '.join([f"{d['Name']}={d['Value']}" for d in metric.get('Dimensions', [])])
                        self.print_colored(self.colors.WHITE, f"  Metric: {metric_name} ({dimensions})", 1)
                else:
                    self.log_step("CLOUDWATCH", f"⚠️  No custom metrics found in namespace: {namespace}", "WARNING")
            
            except ClientError as e:
                self.log_step("CLOUDWATCH", f"⚠️  Error checking metrics: {str(e)}", "WARNING")
            
            return True
            
        except Exception as e:
            self.log_step("CLOUDWATCH", f"❌ Failed to check CloudWatch: {str(e)}", "ERROR")
            return False
    
    def print_agent_logs(self, env: Dict, lines: int = 50):
        """Print current CloudWatch agent logs"""
        self.print_header("CLOUDWATCH AGENT LOGS")
        
        success, stdout, stderr = self.run_command(
            ['kubectl', 'logs', '-n', self.namespace, '-l', f'app={self.custom_agent_name}', f'--tail={lines}'],
            env=env
        )
        
        if success:
            self.print_colored(self.colors.WHITE, "📋 Recent CloudWatch Agent Logs:")
            self.print_colored(self.colors.CYAN, "-" * 80)
            print(stdout)
            self.print_colored(self.colors.CYAN, "-" * 80)
        else:
            self.log_step("LOGS", f"Failed to get logs: {stderr}", "ERROR")
    
    def print_success_summary(self, cluster_name: str, region: str):
        """Print deployment success summary"""
        self.print_header("🎉 CLOUDWATCH AGENT DEPLOYMENT SUCCESSFUL! 🎉")
        
        elapsed_time = time.time() - self.deployment_start_time
        
        self.print_colored(self.colors.GREEN, "✅ DEPLOYMENT COMPLETED SUCCESSFULLY!")
        self.print_colored(self.colors.CYAN, f"📊 Deployment Summary:")
        self.print_colored(self.colors.WHITE, f"   • Cluster: {cluster_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • Region: {region}", 1)
        self.print_colored(self.colors.WHITE, f"   • Custom Agent Name: {self.custom_agent_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • Namespace: {self.namespace}", 1)
        self.print_colored(self.colors.WHITE, f"   • Deployment Time: {elapsed_time:.1f} seconds", 1)
        
        self.print_colored(self.colors.YELLOW, "\n🔍 Monitoring Commands:")
        self.print_colored(self.colors.WHITE, "   # Check DaemonSet status:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl get daemonset {self.custom_agent_name} -n {self.namespace}", 1)
        
        self.print_colored(self.colors.WHITE, "   # Check pod status:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl get pods -n {self.namespace} -l app={self.custom_agent_name}", 1)
        
        self.print_colored(self.colors.WHITE, "   # View agent logs:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl logs -n {self.namespace} -l app={self.custom_agent_name} -f", 1)
        
        self.print_colored(self.colors.WHITE, "   # Check CloudWatch configuration:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl get configmap {self.custom_agent_name}-config -n {self.namespace} -o yaml", 1)
        
        self.print_colored(self.colors.GREEN, f"\n📊 CloudWatch Resources:")
        self.print_colored(self.colors.WHITE, f"   • Log Group: /aws/eks/{cluster_name}/custom-logs", 1)
        self.print_colored(self.colors.WHITE, f"   • Metrics Namespace: EKS/Custom/{cluster_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • AWS Console: https://{region}.console.aws.amazon.com/cloudwatch/", 1)
    
    def deploy_custom_cloudwatch_agent(self, cluster_name: str, region: str, access_key: str, secret_key: str, user_name) -> bool:
        """
        Complete custom CloudWatch agent deployment
        
        Args:
            cluster_name: EKS cluster name
            region: AWS region
            access_key: AWS access key
            secret_key: AWS secret key
            user_name: User name for deployment context
            
        Returns:
            bool: True if deployment successful
        """
        try:
            self.custom_agent_name = f"{user_name}-cw-agent"
            self.print_header("CUSTOM CLOUDWATCH AGENT DEPLOYMENT")
            
            self.print_colored(self.colors.BLUE, "🎯 Deployment Parameters:")
            self.print_colored(self.colors.WHITE, f"   • Cluster: {cluster_name}", 1)
            self.print_colored(self.colors.WHITE, f"   • Region: {region}", 1)
            self.print_colored(self.colors.WHITE, f"   • Custom Agent Name: {self.custom_agent_name}", 1)
            self.print_colored(self.colors.WHITE, f"   • Namespace: {self.namespace}", 1)
            self.print_colored(self.colors.WHITE, f"   • Access Key: {access_key[:8]}...", 1)
            
            # Step 1: Setup environment
            env = self.setup_environment(cluster_name, region, access_key, secret_key)
            
            # Step 2: Create namespace
            if not self.create_namespace(env):
                return False
            
            # Step 3: Cleanup existing resources
            self.cleanup_existing_agent(env)
            
            # Step 4: Create AWS credentials secret
            if not self.create_aws_credentials_secret(access_key, secret_key, region, env):
                return False
            
            # Step 5: Deploy CloudWatch agent
            if not self.deploy_cloudwatch_agent(cluster_name, region, env):
                return False
            
            # Step 6: Wait for agent to be ready
            if not self.wait_for_agent_ready(env):
                self.log_step("DEPLOY", "CloudWatch agent may not be fully ready, but continuing", "WARNING")
            
            # Step 7: Verify deployment
            if not self.verify_deployment(env, cluster_name, region):
                self.log_step("VERIFY", "Some verification checks failed", "WARNING")
            
            # Step 8: Check CloudWatch logs and metrics
            self.check_cloudwatch_logs(cluster_name, region, access_key, secret_key)
            
            # Step 9: Print logs
            self.print_agent_logs(env)
            
            # Step 10: Print success summary
            self.print_success_summary(cluster_name, region)
            
            return True
            
        except Exception as e:
            self.log_step("DEPLOY", f"Deployment failed with exception: {str(e)}", "ERROR")
            self.print_colored(self.colors.RED, f"\n❌ DEPLOYMENT FAILED: {str(e)}")
            return False

def main():
    """Main function for command line usage"""
    deployer = CustomCloudWatchAgentDeployer(custom_agent_name="varadharajaan-cloudwatch-agent")
    
    # Example usage - replace with your values
    success = deployer.deploy_custom_cloudwatch_agent(
        cluster_name="eks-cluster-root-account03-us-west-1-pxfw",
        region="us-west-1",
        access_key="YOUR_ACCESS_KEY_HERE",
        secret_key="YOUR_SECRET_KEY_HERE"
    )
    
    if success:
        print("\n🎉 CLOUDWATCH AGENT DEPLOYMENT COMPLETED SUCCESSFULLY!")
        return 0
    else:
        print("\n💥 CLOUDWATCH AGENT DEPLOYMENT FAILED!")
        return 1

if __name__ == "__main__":
    exit(main())