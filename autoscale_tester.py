#!/usr/bin/env python3
"""
Usage example for complete autoscaler deployment with interactive testing
Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): 2025-06-19 08:55:32
Current User's Login: varadharajaan
"""

import time
import subprocess
import os

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'

class AutoscalerTester:
    """
    Interactive autoscaler testing with stress scenarios
    Current Date and Time (UTC): 2025-06-19 08:55:32
    User: varadharajaan
    """
    
    def __init__(self):
        self.colors = Colors()
    
    def print_colored(self, color: str, message: str, indent: int = 0):
        """Print colored message with optional indentation"""
        prefix = "  " * indent
        print(f"{color}{prefix}{message}{self.colors.ENDC}")
    
    def print_header(self, title: str):
        """Print formatted header"""
        self.print_colored(self.colors.BOLD, "=" * 80)
        self.print_colored(self.colors.BOLD, f"    {title}")
        self.print_colored(self.colors.BOLD, "=" * 80)
        self.print_colored(self.colors.CYAN, "    Current Date and Time (UTC): 2025-06-19 08:55:32")
        self.print_colored(self.colors.CYAN, "    Current User's Login: varadharajaan")
        self.print_colored(self.colors.BOLD, "=" * 80)
    
    def run_command(self, cmd: list, timeout: int = 60) -> tuple:
        """Run command and return success, stdout, stderr"""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timeout"
        except Exception as e:
            return False, "", str(e)
    
    def get_user_input(self, prompt: str, default: str = "y") -> str:
        """Get user input with default value"""
        try:
            response = input(f"{self.colors.YELLOW}{prompt} [{default}]: {self.colors.ENDC}").strip()
            return response if response else default
        except KeyboardInterrupt:
            print(f"\n{self.colors.YELLOW}Operation cancelled by user.{self.colors.ENDC}")
            return "n"
    
    def wait_with_countdown(self, seconds: int, message: str):
        """Wait with countdown display"""
        self.print_colored(self.colors.BLUE, f"⏳ {message}")
        for i in range(seconds, 0, -1):
            print(f"\r{self.colors.CYAN}    Waiting {i} seconds...{self.colors.ENDC}", end="", flush=True)
            time.sleep(1)
        print(f"\r{self.colors.GREEN}    ✅ Wait completed!{self.colors.ENDC}")
    
    def check_nodes(self) -> int:
        """Check current number of nodes"""
        success, stdout, stderr = self.run_command(['kubectl', 'get', 'nodes', '--no-headers'])
        if success:
            node_count = len(stdout.strip().split('\n')) if stdout.strip() else 0
            self.print_colored(self.colors.WHITE, f"Current node count: {node_count}", 1)
            return node_count
        else:
            self.print_colored(self.colors.RED, f"Failed to get nodes: {stderr}", 1)
            return 0
    
    def check_pods(self, label_selector: str = None) -> dict:
        """Check pod status"""
        cmd = ['kubectl', 'get', 'pods', '--no-headers']
        if label_selector:
            cmd.extend(['-l', label_selector])
        
        success, stdout, stderr = self.run_command(cmd)
        if success and stdout.strip():
            lines = stdout.strip().split('\n')
            pod_status = {'Running': 0, 'Pending': 0, 'Failed': 0, 'Other': 0}
            
            for line in lines:
                parts = line.split()
                if len(parts) >= 3:
                    status = parts[2]
                    if status == 'Running':
                        pod_status['Running'] += 1
                    elif status == 'Pending':
                        pod_status['Pending'] += 1
                    elif status in ['Failed', 'Error', 'CrashLoopBackOff']:
                        pod_status['Failed'] += 1
                    else:
                        pod_status['Other'] += 1
            
            return pod_status
        return {'Running': 0, 'Pending': 0, 'Failed': 0, 'Other': 0}
    
    def show_autoscaler_logs(self, lines: int = 10):
        """Show recent autoscaler logs"""
        self.print_colored(self.colors.BLUE, f"📋 Recent autoscaler logs ({lines} lines):")
        success, stdout, stderr = self.run_command([
            'kubectl', 'logs', '-n', 'kube-system', '-l', 'app=cluster-autoscaler', f'--tail={lines}'
        ])
        
        if success:
            self.print_colored(self.colors.CYAN, "-" * 60, 1)
            for line in stdout.strip().split('\n'):
                if line.strip():
                    self.print_colored(self.colors.WHITE, line.strip(), 1)
            self.print_colored(self.colors.CYAN, "-" * 60, 1)
        else:
            self.print_colored(self.colors.RED, f"Failed to get logs: {stderr}", 1)
    
    def deploy_stress_test_app(self) -> bool:
        """Deploy stress test application"""
        self.print_header("🧪 DEPLOYING STRESS TEST APPLICATION")
        
        # Create stress test deployment YAML
        stress_yaml = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: stress-test
  labels:
    app: stress-test
spec:
  replicas: 1
  selector:
    matchLabels:
      app: stress-test
  template:
    metadata:
      labels:
        app: stress-test
    spec:
      containers:
      - name: stress-test
        image: polinux/stress
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        command: ["stress"]
        args: ["--vm", "1", "--vm-bytes", "200M", "--vm-hang", "1", "--verbose"]
      nodeSelector:
        kubernetes.io/os: linux
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cpu-intensive
  labels:
    app: cpu-intensive
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cpu-intensive
  template:
    metadata:
      labels:
        app: cpu-intensive
    spec:
      containers:
      - name: cpu-intensive
        image: progrium/stress
        resources:
          requests:
            memory: "256Mi"
            cpu: "800m"
          limits:
            memory: "512Mi"
            cpu: "1500m"
        command: ["stress"]
        args: ["--cpu", "2", "--timeout", "3600s", "--verbose"]
      nodeSelector:
        kubernetes.io/os: linux
"""
        
        # Write to temporary file
        with open('/tmp/stress-test.yaml', 'w') as f:
            f.write(stress_yaml)
        
        # Apply the deployment
        self.print_colored(self.colors.BLUE, "🚀 Deploying stress test applications...")
        success, stdout, stderr = self.run_command(['kubectl', 'apply', '-f', '/tmp/stress-test.yaml'])
        
        if success:
            self.print_colored(self.colors.GREEN, "✅ Stress test applications deployed successfully", 1)
            
            # Wait for pods to be ready
            self.wait_with_countdown(30, "Waiting for initial pods to start...")
            
            # Show initial status
            self.print_colored(self.colors.WHITE, "Initial deployment status:", 1)
            success, stdout, stderr = self.run_command(['kubectl', 'get', 'deployments', '-l', 'app in (stress-test,cpu-intensive)'])
            if success:
                for line in stdout.split('\n'):
                    if line.strip():
                        self.print_colored(self.colors.WHITE, line, 2)
            
            return True
        else:
            self.print_colored(self.colors.RED, f"❌ Failed to deploy: {stderr}", 1)
            return False
    
    def run_scale_up_scenario(self):
        """Run automatic scale-up scenario"""
        self.print_header("📈 SCALE-UP SCENARIO")
        
        self.print_colored(self.colors.YELLOW, "🎯 Scale-Up Test: Increasing workload to trigger node addition")
        
        # Check initial state
        initial_nodes = self.check_nodes()
        initial_pods = self.check_pods()
        
        self.print_colored(self.colors.WHITE, f"Initial state: {initial_nodes} nodes, {initial_pods['Running']} running pods", 1)
        
        # Scale up stress-test deployment
        self.print_colored(self.colors.BLUE, "📊 Step 1: Scaling stress-test to 5 replicas...")
        success, stdout, stderr = self.run_command(['kubectl', 'scale', 'deployment', 'stress-test', '--replicas=5'])
        if success:
            self.print_colored(self.colors.GREEN, "✅ Stress-test scaled to 5 replicas", 1)
        else:
            self.print_colored(self.colors.RED, f"❌ Failed to scale stress-test: {stderr}", 1)
        
        # Wait and check
        self.wait_with_countdown(60, "Waiting for pods to be scheduled...")
        
        # Scale up cpu-intensive deployment
        self.print_colored(self.colors.BLUE, "📊 Step 2: Scaling cpu-intensive to 3 replicas...")
        success, stdout, stderr = self.run_command(['kubectl', 'scale', 'deployment', 'cpu-intensive', '--replicas=3'])
        if success:
            self.print_colored(self.colors.GREEN, "✅ CPU-intensive scaled to 3 replicas", 1)
        else:
            self.print_colored(self.colors.RED, f"❌ Failed to scale cpu-intensive: {stderr}", 1)
        
        # Monitor scaling progress
        for i in range(5):  # Monitor for 5 minutes
            self.print_colored(self.colors.CYAN, f"\n🔍 Monitoring progress - Check {i+1}/5")
            
            # Check nodes
            current_nodes = self.check_nodes()
            
            # Check pods
            current_pods = self.check_pods('app in (stress-test,cpu-intensive)')
            self.print_colored(self.colors.WHITE, f"Test app pods - Running: {current_pods['Running']}, Pending: {current_pods['Pending']}", 1)
            
            # Show autoscaler logs
            self.show_autoscaler_logs(5)
            
            # Check if scaling happened
            if current_nodes > initial_nodes:
                self.print_colored(self.colors.GREEN, f"🎉 SUCCESS: Nodes scaled from {initial_nodes} to {current_nodes}!", 1)
                break
            elif current_pods['Pending'] > 0:
                self.print_colored(self.colors.YELLOW, f"⏳ Pods pending, autoscaler should add nodes soon...", 1)
            else:
                self.print_colored(self.colors.BLUE, f"ℹ️  No pending pods, checking if more capacity needed...", 1)
            
            if i < 4:  # Don't wait after last iteration
                self.wait_with_countdown(60, "Waiting before next check...")
        
        # Final status
        final_nodes = self.check_nodes()
        final_pods = self.check_pods('app in (stress-test,cpu-intensive)')
        
        self.print_colored(self.colors.CYAN, "\n📊 Scale-Up Results:")
        self.print_colored(self.colors.WHITE, f"Nodes: {initial_nodes} → {final_nodes} (Change: +{final_nodes - initial_nodes})", 1)
        self.print_colored(self.colors.WHITE, f"Running pods: {initial_pods['Running']} → {final_pods['Running']}", 1)
        self.print_colored(self.colors.WHITE, f"Pending pods: {final_pods['Pending']}", 1)
    
    def run_scale_down_scenario(self):
        """Run automatic scale-down scenario"""
        self.print_header("📉 SCALE-DOWN SCENARIO")
        
        self.print_colored(self.colors.YELLOW, "🎯 Scale-Down Test: Reducing workload to trigger node removal")
        
        # Check initial state
        initial_nodes = self.check_nodes()
        initial_pods = self.check_pods()
        
        self.print_colored(self.colors.WHITE, f"Initial state: {initial_nodes} nodes, {initial_pods['Running']} running pods", 1)
        
        # Scale down deployments
        self.print_colored(self.colors.BLUE, "📊 Step 1: Scaling stress-test to 1 replica...")
        success, stdout, stderr = self.run_command(['kubectl', 'scale', 'deployment', 'stress-test', '--replicas=1'])
        if success:
            self.print_colored(self.colors.GREEN, "✅ Stress-test scaled down to 1 replica", 1)
        else:
            self.print_colored(self.colors.RED, f"❌ Failed to scale down stress-test: {stderr}", 1)
        
        self.wait_with_countdown(30, "Waiting for pods to terminate...")
        
        self.print_colored(self.colors.BLUE, "📊 Step 2: Scaling cpu-intensive to 0 replicas...")
        success, stdout, stderr = self.run_command(['kubectl', 'scale', 'deployment', 'cpu-intensive', '--replicas=0'])
        if success:
            self.print_colored(self.colors.GREEN, "✅ CPU-intensive scaled down to 0 replicas", 1)
        else:
            self.print_colored(self.colors.RED, f"❌ Failed to scale down cpu-intensive: {stderr}", 1)
        
        # Monitor scale-down (takes longer due to 2m delays)
        self.print_colored(self.colors.YELLOW, "⏳ Scale-down monitoring (autoscaler waits 2 minutes before removing nodes)", 1)
        
        for i in range(4):  # Monitor for 8 minutes (scale-down takes longer)
            self.print_colored(self.colors.CYAN, f"\n🔍 Scale-down monitoring - Check {i+1}/4")
            
            # Check nodes
            current_nodes = self.check_nodes()
            
            # Check pods
            current_pods = self.check_pods('app in (stress-test,cpu-intensive)')
            self.print_colored(self.colors.WHITE, f"Test app pods - Running: {current_pods['Running']}", 1)
            
            # Show autoscaler logs
            self.show_autoscaler_logs(5)
            
            # Check if scaling happened
            if current_nodes < initial_nodes:
                self.print_colored(self.colors.GREEN, f"🎉 SUCCESS: Nodes scaled down from {initial_nodes} to {current_nodes}!", 1)
                break
            else:
                self.print_colored(self.colors.BLUE, f"ℹ️  Nodes unchanged, autoscaler waiting for scale-down delay...", 1)
            
            if i < 3:  # Don't wait after last iteration
                self.wait_with_countdown(120, "Waiting 2 minutes for scale-down delay...")
        
        # Final status
        final_nodes = self.check_nodes()
        final_pods = self.check_pods('app in (stress-test,cpu-intensive)')
        
        self.print_colored(self.colors.CYAN, "\n📊 Scale-Down Results:")
        self.print_colored(self.colors.WHITE, f"Nodes: {initial_nodes} → {final_nodes} (Change: {final_nodes - initial_nodes})", 1)
        self.print_colored(self.colors.WHITE, f"Running test pods: {final_pods['Running']}", 1)
        
        if final_nodes < initial_nodes:
            self.print_colored(self.colors.GREEN, "✅ Scale-down successful!", 1)
        else:
            self.print_colored(self.colors.YELLOW, "⚠️  Scale-down may take more time (can take up to 10+ minutes)", 1)
    
    def cleanup_test_deployments(self):
        """Clean up test deployments"""
        self.print_header("🗑️ CLEANING UP TEST DEPLOYMENTS")
        
        deployments = ['stress-test', 'cpu-intensive']
        
        for deployment in deployments:
            self.print_colored(self.colors.BLUE, f"🗑️ Deleting deployment: {deployment}")
            success, stdout, stderr = self.run_command(['kubectl', 'delete', 'deployment', deployment, '--ignore-not-found=true'])
            
            if success:
                self.print_colored(self.colors.GREEN, f"✅ Deleted {deployment}", 1)
            else:
                self.print_colored(self.colors.YELLOW, f"⚠️  {deployment} may not exist or already deleted", 1)
        
        self.wait_with_countdown(30, "Waiting for pods to terminate...")
        
        # Show final status
        remaining_pods = self.check_pods('app in (stress-test,cpu-intensive)')
        if remaining_pods['Running'] == 0:
            self.print_colored(self.colors.GREEN, "✅ All test pods cleaned up successfully", 1)
        else:
            self.print_colored(self.colors.YELLOW, f"⚠️  {remaining_pods['Running']} test pods still running", 1)
    
    def run_interactive_testing(self):
        """Run interactive autoscaler testing"""
        self.print_header("🧪 INTERACTIVE AUTOSCALER TESTING")
        
        self.print_colored(self.colors.CYAN, "This will test your autoscaler with real workloads!")
        self.print_colored(self.colors.WHITE, "• Deploy stress test applications", 1)
        self.print_colored(self.colors.WHITE, "• Scale up to trigger node addition", 1)
        self.print_colored(self.colors.WHITE, "• Scale down to trigger node removal", 1)
        self.print_colored(self.colors.WHITE, "• Clean up test resources", 1)
        
        # Ask if user wants to proceed
        proceed = self.get_user_input("\n🤔 Do you want to proceed with autoscaler testing? (y/n)", "y")
        
        if proceed.lower() not in ['y', 'yes']:
            self.print_colored(self.colors.YELLOW, "Testing cancelled by user.")
            return False
        
        try:
            # Deploy stress test apps
            if not self.deploy_stress_test_app():
                return False
            
            # Ask for scale-up test
            scale_up = self.get_user_input("\n📈 Run scale-up scenario? (y/n)", "y")
            if scale_up.lower() in ['y', 'yes']:
                self.run_scale_up_scenario()
            
            # Ask for scale-down test
            scale_down = self.get_user_input("\n📉 Run scale-down scenario? (y/n)", "y")
            if scale_down.lower() in ['y', 'yes']:
                self.run_scale_down_scenario()
            
            # Ask for cleanup
            cleanup = self.get_user_input("\n🗑️ Clean up test deployments? (y/n)", "y")
            if cleanup.lower() in ['y', 'yes']:
                self.cleanup_test_deployments()
            
            self.print_colored(self.colors.GREEN, "\n🎉 Autoscaler testing completed!")
            return True
            
        except KeyboardInterrupt:
            self.print_colored(self.colors.YELLOW, "\n⚠️  Testing interrupted by user.")
            
            # Ask if user wants to clean up
            cleanup = self.get_user_input("🗑️ Clean up test deployments before exit? (y/n)", "y")
            if cleanup.lower() in ['y', 'yes']:
                self.cleanup_test_deployments()
            
            return False
        except Exception as e:
            self.print_colored(self.colors.RED, f"\n❌ Testing failed with error: {str(e)}")
            return False

def deploy_my_autoscaler():
    """Deploy autoscaler with your specific parameters"""
    
    # Initialize deployer
    from complete_autoscaler_deployment import CompleteAutoscalerDeployer
    deployer = CompleteAutoscalerDeployer()
    
    # Your cluster configuration
    cluster_name = "eks-cluster-root-account03-us-west-1-olpg"
    region = "us-west-1"
    access_key = "your_access_key_here"  # replace placeholder with actual access key
    secret_key = "your_secret_key_here"   # replace placeholder with actual secret key
    
    print(f"\n🚀 Starting autoscaler deployment...")
    print(f"Current Date and Time (UTC): 2025-06-19 08:55:32")
    print(f"Current User's Login: varadharajaan")
    print(f"Cluster: {cluster_name}")
    print(f"Region: {region}")
    
    # Deploy complete autoscaler
    success = deployer.deploy_complete_autoscaler(
        cluster_name=cluster_name,
        region=region,
        access_key=access_key,
        secret_key=secret_key
    )
    
    if not success:
        print(f"\n❌ Autoscaler deployment failed!")
        return False
    
    print(f"\n✅ Autoscaler deployment completed successfully!")
    
    # Ask if user wants to test the autoscaler
    try:
        response = input(f"\n🤔 Would you like to test the autoscaler with sample deployments? (y/n) [y]: ").strip()
        test_autoscaler = response.lower() in ['y', 'yes', ''] 
        
        if test_autoscaler:
            print(f"\n🧪 Proceeding with autoscaler testing...")
            tester = AutoscalerTester()
            tester.run_interactive_testing()
        else:
            print(f"\n✅ Autoscaler deployment completed. You can test it manually later.")
            print(f"\nManual testing commands:")
            print(f"  kubectl create deployment test-scale --image=nginx --replicas=10")
            print(f"  kubectl set resources deployment test-scale --requests=cpu=1000m,memory=1Gi")
            print(f"  kubectl logs -n kube-system -l app=cluster-autoscaler -f")
    
    except KeyboardInterrupt:
        print(f"\n\n✅ Autoscaler deployment completed successfully!")
        print(f"Testing was cancelled, but autoscaler is ready to use.")
    
    return success

if __name__ == "__main__":
    success = deploy_my_autoscaler()
    exit(0 if success else 1)