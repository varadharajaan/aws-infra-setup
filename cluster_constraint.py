import boto3
import subprocess
import tempfile
import os
import json
import glob
from kubernetes import config

class K8sPolicyInstaller:
    def __init__(self, access_key, secret_key, account_id, region, manifests_dir='k8s_manifests'):
        self.access_key = access_key
        self.secret_key = secret_key
        self.account_id = account_id
        self.region = region
        self.manifests_dir = manifests_dir

    def update_kubeconfig(self, cluster_name):
        session = boto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region
        )
        eks = session.client('eks')
        cluster_info = eks.describe_cluster(name=cluster_name)['cluster']
        endpoint = cluster_info['endpoint']
        cert_data = cluster_info['certificateAuthority']['data']

        kubeconfig_path = tempfile.NamedTemporaryFile(delete=False).name
        kubeconfig_yaml = f"""
apiVersion: v1
clusters:
- cluster:
    server: {endpoint}
    certificate-authority-data: {cert_data}
  name: {cluster_name}
contexts:
- context:
    cluster: {cluster_name}
    user: {cluster_name}
  name: {cluster_name}
current-context: {cluster_name}
kind: Config
preferences: {{}}
users:
- name: {cluster_name}
  user:
    exec:
      apiVersion: "client.authentication.k8s.io/v1beta1"
      command: "aws"
      args:
        - "eks"
        - "get-token"
        - "--cluster-name"
        - "{cluster_name}"
        - "--region"
        - "{self.region}"
      env:
        - name: AWS_ACCESS_KEY_ID
          value: "{self.access_key}"
        - name: AWS_SECRET_ACCESS_KEY
          value: "{self.secret_key}"
"""
        with open(kubeconfig_path, 'w') as f:
            f.write(kubeconfig_yaml)

        os.environ['KUBECONFIG'] = kubeconfig_path
        config.load_kube_config(config_file=kubeconfig_path)
        return kubeconfig_path

    def install_kyverno(self):
        subprocess.run([
            "kubectl", "create", "-f",
            "https://raw.githubusercontent.com/kyverno/kyverno/main/config/release/install.yaml"
        ], check=True)

    def install_gatekeeper(self):
        subprocess.run([
            "kubectl", "apply", "-f",
            "https://raw.githubusercontent.com/open-policy-agent/gatekeeper/master/deploy/gatekeeper.yaml"
        ], check=True)

    def apply_yaml(self, file_name):
        file_path = os.path.join(self.manifests_dir, file_name)
        subprocess.run(["kubectl", "apply", "-f", file_path], check=True)

    def install_policies(self, cluster_name):
        print(f"\n--- Processing cluster: {cluster_name} ({self.region}) ---")
        self.update_kubeconfig(cluster_name)
        self.install_kyverno()
        self.apply_yaml("kyverno-replica-policy.yaml")
        # Uncomment for Gatekeeper
        # self.install_gatekeeper()
        # self.apply_yaml("gatekeeper-template.yaml")
        # self.apply_yaml("gatekeeper-constraint.yaml")

def select_accounts(accounts):
    keys = list(accounts.keys())
    print("Available accounts:")
    for idx, k in enumerate(keys, 1):
        print(f" {idx}. {k}")
    sel = input("Select accounts (number, comma, range, all): ").strip().lower()
    if sel == "all":
        return keys
    result = set()
    for part in sel.split(","):
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-"))
            result.update(keys[start-1:end])
        elif part.isdigit():
            result.add(keys[int(part)-1])
        elif part in keys:
            result.add(part)
    return list(result)

def main():
    with open("aws_accounts_config.json") as f:
        config_data = json.load(f)
    accounts = config_data["accounts"]
    selected_accounts = select_accounts(accounts)
    for account in selected_accounts:
        acc_info = accounts[account]
        access_key = acc_info["access_key"]
        secret_key = acc_info["secret_key"]
        account_id = acc_info["account_id"]
        eks_dir = f"aws/eks/{account}*"
        for eks_path in glob.glob(eks_dir):
            for file in glob.glob(os.path.join(eks_path, "eks_cluster_eks-cluster-*.json")):
                with open(file) as f:
                    cluster_data = json.load(f)
                cluster_name = cluster_data["cluster_info"]["cluster_name"]
                region = cluster_data["account_info"]["region"]
                installer = K8sPolicyInstaller(access_key, secret_key, account_id, region)
                installer.install_policies(cluster_name)

if __name__ == "__main__":
    main()