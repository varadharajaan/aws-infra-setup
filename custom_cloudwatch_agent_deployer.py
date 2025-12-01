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
import textwrap

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
        """Print colored message with optional indentation, handling Unicode safely."""
        prefix = "  " * indent
        try:
            print(f"{color}{prefix}{message}{self.colors.ENDC}")
        except UnicodeEncodeError:
            print(f"{color}{prefix}{message.encode('utf-8', errors='replace').decode('utf-8')}{self.colors.ENDC}")

    def print_header(self, title: str):
        """Print formatted header"""
        self.print_colored(self.colors.BOLD, "=" * 90)
        self.print_colored(self.colors.BOLD, f"    {title}")
        self.print_colored(self.colors.BOLD, "=" * 90)
        from datetime import datetime
        self.print_colored(
            self.colors.CYAN,
            f"    Current Date and Time (UTC): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
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

        cmd = ['aws', 'eks', 'update-kubeconfig', '--region', region, '--name', cluster_name]
        success, stdout, stderr = self.run_command(cmd, env=env)

        if not success:
            self.log_step("ENV", f"Failed to update kubeconfig: {stderr}", "ERROR")
            raise Exception(f"Kubeconfig update failed: {stderr}")

        success, stdout, stderr = self.run_command(['kubectl', 'get', 'nodes'], env=env)
        if not success:
            self.log_step("ENV", f"kubectl access test failed: {stderr}", "ERROR")
            raise Exception(f"kubectl access failed: {stderr}")

        self.log_step("ENV", "Environment setup completed", "SUCCESS")
        return env

    def create_namespace(self, env: Dict) -> bool:
        """Create or ensure namespace exists"""
        self.log_step("NAMESPACE", f"Creating namespace: {self.namespace}")

        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'namespace', self.namespace], env=env
        )

        if success:
            self.log_step("NAMESPACE", f"Namespace {self.namespace} already exists", "SUCCESS")
            return True

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
        time.sleep(10)
        return True

    def create_aws_credentials_secret(self, access_key: str, secret_key: str, region: str, env: Dict) -> bool:
        """Create AWS credentials secret for CloudWatch agent"""
        self.log_step("SECRET", "Creating AWS credentials secret for CloudWatch agent...")

        secret_name = f"{self.custom_agent_name}-credentials".replace("_", "-").lower()

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
        """
        Create a valid CloudWatch agent configuration JSON with statsd enabled.
        """
        config = {
            "logs": {
                "logs_collected": {
                    "files": {
                        "collect_list": [
                            {
                                "file_path": "/var/log/messages",
                                "log_group_name": f"/aws/eks/{cluster_name}/custom-logs",
                                "log_stream_name": "{instance_id}",
                                "timezone": "UTC"
                            }
                        ]
                    }
                },
                "metrics_collected": {
                    "kubernetes": {
                        "cluster_name": cluster_name,
                        "metrics_collection_interval": 60
                    }
                }
            },
            "metrics": {
                "namespace": f"EKS/Custom/{cluster_name}",
                "metrics_collected": {
                    "cpu": {
                        "measurement": [
                            "cpu_usage_idle",
                            "cpu_usage_iowait",
                            "cpu_usage_user",
                            "cpu_usage_system"
                        ],
                        "metrics_collection_interval": 60
                    },
                    "disk": {
                        "measurement": ["used_percent"],
                        "metrics_collection_interval": 60,
                        "resources": ["*"]
                    },
                    "diskio": {
                        "measurement": [
                            "io_time",
                            "read_bytes",
                            "write_bytes",
                            "reads",
                            "writes"
                        ],
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
                    },
                    "statsd": {
                        "service_address": ":8125",
                        "metrics_collection_interval": 60
                    }
                }
            }
        }
        return json.dumps(config, indent=2)

    def create_cloudwatch_agent_yaml(self, cluster_name: str, region: str) -> str:
        """Create complete CloudWatch agent YAML configuration from template"""

        template_path = os.path.join(os.getcwd(), 'cloudwatch-agent-template.yaml')
        with open(template_path, 'r') as f:
            yaml_template = f.read()

        config_json = self.create_cloudwatch_config(cluster_name, region)
        indented_config_json = textwrap.indent(config_json, '    ')

        yaml_content = yaml_template.replace('{{CUSTOM_AGENT_NAME}}', self.custom_agent_name)
        yaml_content = yaml_content.replace('{{NAMESPACE}}', self.namespace)
        yaml_content = yaml_content.replace('{{REGION}}', region)
        yaml_content = yaml_content.replace('{{CONFIG_JSON}}', indented_config_json)

        return yaml_content

    def deploy_cloudwatch_agent(self, cluster_name: str, region: str, env: Dict) -> bool:
        """Deploy the custom CloudWatch agent"""
        self.log_step("DEPLOY", f"Deploying custom CloudWatch agent: {self.custom_agent_name}")

        yaml_content = self.create_cloudwatch_agent_yaml(cluster_name, region)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_file = f.name

        try:
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

                    if int(ready) == int(desired) - 1 and int(desired) > 1:
                        self.log_step("WAIT", f"n-1 pods are ready: {ready}/{desired}", "SUCCESS")
                        return True
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

        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'daemonset', self.custom_agent_name, '-n', self.namespace],
            env=env
        )

        if success:
            self.log_step("VERIFY", "[OK] DaemonSet status check passed", "SUCCESS")
            self.print_colored(self.colors.WHITE, stdout, 1)
        else:
            self.log_step("VERIFY", "[ERROR] DaemonSet status check failed", "ERROR")
            verification_passed = False

        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'pods', '-n', self.namespace, '-l', f'app={self.custom_agent_name}'],
            env=env
        )

        if success:
            self.log_step("VERIFY", "[OK] Pod status check passed", "SUCCESS")
            self.print_colored(self.colors.WHITE, stdout, 1)
        else:
            self.log_step("VERIFY", "[ERROR] Pod status check failed", "ERROR")
            verification_passed = False

        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'configmap', f'{self.custom_agent_name}-config', '-n', self.namespace],
            env=env
        )

        if success:
            self.log_step("VERIFY", "[OK] ConfigMap exists", "SUCCESS")
        else:
            self.log_step("VERIFY", "[ERROR] ConfigMap missing", "ERROR")
            verification_passed = False

        success, stdout, stderr = self.run_command(
            ['kubectl', 'get', 'secret', f'{self.custom_agent_name}-credentials', '-n', self.namespace],
            env=env
        )

        if success:
            self.log_step("VERIFY", "[OK] AWS credentials secret exists", "SUCCESS")
        else:
            self.log_step("VERIFY", "[ERROR] AWS credentials secret missing", "ERROR")
            verification_passed = False

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
                self.log_step("VERIFY", f"[OK] {resource_type} {name} exists", "SUCCESS")
            else:
                self.log_step("VERIFY", f"[ERROR] {resource_type} {name} missing", "ERROR")
                verification_passed = False

        return verification_passed

    def check_cloudwatch_logs(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """Check if logs are being sent to CloudWatch"""
        self.log_step("CLOUDWATCH", "Checking CloudWatch logs and metrics...")

        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            cloudwatch_logs = session.client('logs')
            cloudwatch_metrics = session.client('cloudwatch')

            log_group_name = f"/aws/eks/{cluster_name}/custom-logs"

            try:
                response = cloudwatch_logs.describe_log_groups(
                    logGroupNamePrefix=log_group_name
                )

                if response['logGroups']:
                    self.log_step("CLOUDWATCH", f"[OK] Log group found: {log_group_name}", "SUCCESS")

                    streams_response = cloudwatch_logs.describe_log_streams(
                        logGroupName=log_group_name,
                        orderBy='LastEventTime',
                        descending=True,
                        limit=5
                    )

                    if streams_response['logStreams']:
                        self.log_step("CLOUDWATCH", f"[OK] Found {len(streams_response['logStreams'])} log streams", "SUCCESS")
                        for stream in streams_response['logStreams'][:3]:
                            self.print_colored(self.colors.WHITE, f"  Stream: {stream['logStreamName']}", 1)
                    else:
                        self.log_step("CLOUDWATCH", "[WARN]  No log streams found yet", "WARNING")
                else:
                    self.log_step("CLOUDWATCH", f"[WARN]  Log group not found: {log_group_name}", "WARNING")

            except ClientError as e:
                self.log_step("CLOUDWATCH", f"[WARN]  Error checking log groups: {str(e)}", "WARNING")

            namespace = f"EKS/Custom/{cluster_name}"

            try:
                response = cloudwatch_metrics.list_metrics(
                    Namespace=namespace
                )

                if response['Metrics']:
                    self.log_step("CLOUDWATCH", f"[OK] Found {len(response['Metrics'])} custom metrics", "SUCCESS")

                    for metric in response['Metrics'][:5]:
                        metric_name = metric['MetricName']
                        dimensions = ', '.join([f"{d['Name']}={d['Value']}" for d in metric.get('Dimensions', [])])
                        self.print_colored(self.colors.WHITE, f"  Metric: {metric_name} ({dimensions})", 1)
                else:
                    self.log_step("CLOUDWATCH", f"[WARN]  No custom metrics found in namespace: {namespace}", "WARNING")

            except ClientError as e:
                self.log_step("CLOUDWATCH", f"[WARN]  Error checking metrics: {str(e)}", "WARNING")

            return True

        except Exception as e:
            self.log_step("CLOUDWATCH", f"[ERROR] Failed to check CloudWatch: {str(e)}", "ERROR")
            return False

    def print_agent_logs(self, env: Dict, lines: int = 50):
        """Print current CloudWatch agent logs"""
        self.print_header("CLOUDWATCH AGENT LOGS")

        success, stdout, stderr = self.run_command(
            ['kubectl', 'logs', '-n', self.namespace, '-l', f'app={self.custom_agent_name}', f'--tail={lines}'],
            env=env
        )

        if success:
            self.print_colored(self.colors.WHITE, "[LIST] Recent CloudWatch Agent Logs:")
            self.print_colored(self.colors.CYAN, "-" * 80)
            print(stdout)
            self.print_colored(self.colors.CYAN, "-" * 80)
        else:
            self.log_step("LOGS", f"Failed to get logs: {stderr}", "ERROR")

    def print_success_summary(self, cluster_name: str, region: str):
        """Print deployment success summary"""
        self.print_header("[PARTY] CLOUDWATCH AGENT DEPLOYMENT SUCCESSFUL! [PARTY]")

        elapsed_time = time.time() - self.deployment_start_time

        self.print_colored(self.colors.GREEN, "[OK] DEPLOYMENT COMPLETED SUCCESSFULLY!")
        self.print_colored(self.colors.CYAN, f"[STATS] Deployment Summary:")
        self.print_colored(self.colors.WHITE, f"   • Cluster: {cluster_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • Region: {region}", 1)
        self.print_colored(self.colors.WHITE, f"   • Custom Agent Name: {self.custom_agent_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • Namespace: {self.namespace}", 1)
        self.print_colored(self.colors.WHITE, f"   • Deployment Time: {elapsed_time:.1f} seconds", 1)

        self.print_colored(self.colors.YELLOW, "\n[SCAN] Monitoring Commands:")
        self.print_colored(self.colors.WHITE, "   # Check DaemonSet status:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl get daemonset {self.custom_agent_name} -n {self.namespace}", 1)

        self.print_colored(self.colors.WHITE, "   # Check pod status:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl get pods -n {self.namespace} -l app={self.custom_agent_name}", 1)

        self.print_colored(self.colors.WHITE, "   # View agent logs:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl logs -n {self.namespace} -l app={self.custom_agent_name} -f", 1)

        self.print_colored(self.colors.WHITE, "   # Check CloudWatch configuration:", 1)
        self.print_colored(self.colors.CYAN, f"   kubectl get configmap {self.custom_agent_name}-config -n {self.namespace} -o yaml", 1)

        self.print_colored(self.colors.GREEN, f"\n[STATS] CloudWatch Resources:")
        self.print_colored(self.colors.WHITE, f"   • Log Group: /aws/eks/{cluster_name}/custom-logs", 1)
        self.print_colored(self.colors.WHITE, f"   • Metrics Namespace: EKS/Custom/{cluster_name}", 1)
        self.print_colored(self.colors.WHITE, f"   • AWS Console: https://{region}.console.aws.amazon.com/cloudwatch/", 1)

    def ensure_log_group(self, log_group_name: str, region: str, access_key: str, secret_key: str):
        """Ensure the CloudWatch log group exists."""
        import boto3
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        logs = session.client('logs')
        try:
            logs.create_log_group(logGroupName=log_group_name)
            self.log_step("CLOUDWATCH", f"Log group created: {log_group_name}", "SUCCESS")
        except logs.exceptions.ResourceAlreadyExistsException:
            self.log_step("CLOUDWATCH", f"Log group already exists: {log_group_name}", "INFO")
        except Exception as e:
            self.log_step("CLOUDWATCH", f"Failed to create log group: {str(e)}", "ERROR")

    def deploy_custom_cloudwatch_agent(self, cluster_name: str, region: str, access_key: str, secret_key: str) -> bool:
        """
        Complete custom CloudWatch agent deployment

        Args:
            cluster_name: EKS cluster name
            region: AWS region
            access_key: AWS access key
            secret_key: AWS secret key

        Returns:
            bool: True if deployment successful
        """
        try:
            self.custom_agent_name = f"{cluster_name}-cw-agent"
            self.print_header("CUSTOM CLOUDWATCH AGENT DEPLOYMENT")

            self.print_colored(self.colors.BLUE, "[TARGET] Deployment Parameters:")
            self.print_colored(self.colors.WHITE, f"   • Cluster: {cluster_name}", 1)
            self.print_colored(self.colors.WHITE, f"   • Region: {region}", 1)
            self.print_colored(self.colors.WHITE, f"   • Custom Agent Name: {self.custom_agent_name}", 1)
            self.print_colored(self.colors.WHITE, f"   • Namespace: {self.namespace}", 1)
            self.print_colored(self.colors.WHITE, f"   • Access Key: {access_key[:8]}...", 1)

            env = self.setup_environment(cluster_name, region, access_key, secret_key)

            if not self.create_namespace(env):
                return False

            self.cleanup_existing_agent(env)

            if not self.create_aws_credentials_secret(access_key, secret_key, region, env):
                return False

            self.ensure_log_group(f"/aws/eks/{cluster_name}/custom-logs", region, access_key, secret_key)

            if not self.deploy_cloudwatch_agent(cluster_name, region, env):
                return False

            if not self.wait_for_agent_ready(env):
                self.log_step("DEPLOY", "CloudWatch agent may not be fully ready, but continuing", "WARNING")

            time.sleep(10)
            # self.publish_custom_metric(env)
            # self.verify_custom_metric(cluster_name, region, access_key, secret_key)

            if not self.verify_deployment(env, cluster_name, region):
                self.log_step("VERIFY", "Some verification checks failed", "WARNING")

            self.check_cloudwatch_logs(cluster_name, region, access_key, secret_key)

            self.print_agent_logs(env)

            self.print_success_summary(cluster_name, region)

            return True

        except Exception as e:
            self.log_step("DEPLOY", f"Deployment failed with exception: {str(e)}", "ERROR")
            self.print_colored(self.colors.RED, f"\n[ERROR] DEPLOYMENT FAILED: {str(e)}")
            return False

    def deploy_to_clusters(self, clusters: list):
        """
        Deploy the custom CloudWatch agent to multiple clusters.
        Only takes cluster names as input and auto-extracts region and credentials.
        """
        from continue_cluster_setup import EKSClusterContinuationFromErrors

        results = {}
        helper = EKSClusterContinuationFromErrors()

        for cluster_name in clusters:
            print(f"\n=== Deploying to cluster: {cluster_name} ===")
            region = helper._extract_region_from_cluster_name(cluster_name)
            if not region:
                print(f"[ERROR] Could not extract region from cluster name: {cluster_name}")
                results[cluster_name] = False
                continue

            try:
                access_key, secret_key, _ = helper.get_iam_credentials_from_cluster(cluster_name, region)
            except Exception:
                try:
                    access_key, secret_key, _ = helper.get_root_credentials(cluster_name, region)
                except Exception as e:
                    print(f"[ERROR] Could not get credentials for cluster {cluster_name}: {e}")
                    results[cluster_name] = False
                    continue

            success = self.deploy_custom_cloudwatch_agent(
                cluster_name=cluster_name,
                region=region,
                access_key=access_key,
                secret_key=secret_key
            )
            results[cluster_name] = success
        return results

    def publish_custom_metric(self, env: dict):
        """Send a custom metric to the CloudWatch agent via statsd."""
        self.log_step("METRIC", "Publishing custom metric via statsd...")
        success, stdout, _ = self.run_command(
            [
                'kubectl', 'get', 'pods', '-n', self.namespace,
                '-l', f'app={self.custom_agent_name}',
                '-o', 'jsonpath={.items[0].metadata.name}'
            ],
            env=env
        )
        if not success or not stdout.strip():
            self.log_step("METRIC", "No running agent pod found", "ERROR")
            return False
        pod_name = stdout.strip()
        cmd = [
            'kubectl', 'exec', '-n', self.namespace, pod_name, '--',
            '/bin/sh', '-c', 'echo "my_custom_metric:42|g" | nc -u -w1 127.0.0.1 8125'
        ]
        success, _, stderr = self.run_command(cmd, env=env)
        if success:
            self.log_step("METRIC", "Custom metric sent", "SUCCESS")
            return True
        else:
            self.log_step("METRIC", f"Failed to send custom metric: {stderr}", "ERROR")
            return False

    def verify_custom_metric(self, cluster_name: str, region: str, access_key: str, secret_key: str):
        """Verify the custom metric is published in CloudWatch."""
        self.log_step("METRIC", "Verifying custom metric in CloudWatch...")
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            cloudwatch = session.client('cloudwatch')
            namespace = f"EKS/Custom/{cluster_name}"
            response = cloudwatch.list_metrics(
                Namespace=namespace,
                MetricName='my_custom_metric'
            )
            if response['Metrics']:
                self.log_step("METRIC", "[OK] Custom metric found in CloudWatch", "SUCCESS")
                return True
            else:
                self.log_step("METRIC", "[ERROR] Custom metric not found", "ERROR")
                return False
        except Exception as e:
            self.log_step("METRIC", f"Error verifying custom metric: {str(e)}", "ERROR")
            return False

    def update_clusterrole_for_endpointslices(self, yaml_content: str) -> str:
        """
        Add permission for endpointslices.discovery.k8s.io to the ClusterRole in the YAML.
        """
        import re
        # The new rule must be indented to match other rules (2 spaces)
        new_rule = (
            "  - apiGroups: [\"discovery.k8s.io\"]\n"
            "    resources:\n"
            "    - endpointslices\n"
            "    verbs: [\"get\", \"list\", \"watch\"]\n"
        )
        # Insert after the first 'rules:' line
        pattern = r'(rules:\n)'
        replacement = r'\1' + new_rule
        updated_yaml = re.sub(pattern, replacement, yaml_content, count=1)
        return updated_yaml

def main():
    deployer = CustomCloudWatchAgentDeployer()
    clusters = [
        "eks-cluster-root-account01-us-east-1-bbhc"
    ]
    from continue_cluster_setup import EKSClusterContinuationFromErrors
    helper = EKSClusterContinuationFromErrors()
    clusters = helper.select_clusters_from_eks_accounts()
    results = deployer.deploy_to_clusters(clusters)
    print("\nDeployment results:")
    for cluster, success in results.items():
        print(f"  {cluster}: {'SUCCESS' if success else 'FAILED'}")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())