#!/bin/bash
set -e

echo "Updating system..."
sudo dnf update -y

echo "Installing base packages..."
sudo dnf install -y git vim htop awscli python3-pip openssl jq docker conntrack

echo "Enabling Docker..."
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# Create .aws directory with proper permissions
sudo -u ec2-user mkdir -p /home/ec2-user/.aws
sudo chown -R ec2-user:ec2-user /home/ec2-user/.aws

# Check if AWS credentials are set
if [[ -n "${AWS_ACCESS_KEY_ID}" && -n "${AWS_SECRET_ACCESS_KEY}" ]]; then
  echo "Configuring AWS CLI for ec2-user..."
  sudo -u ec2-user bash <<EOF
aws configure set aws_access_key_id "${AWS_ACCESS_KEY_ID}"
aws configure set aws_secret_access_key "${AWS_SECRET_ACCESS_KEY}"
aws configure set default.region "${AWS_DEFAULT_REGION:-us-east-1}"
aws configure set default.output text
EOF
  echo "✅ AWS CLI configured for ec2-user."

  # Optional: Check identity
  sudo -u ec2-user aws sts get-caller-identity || echo "⚠️ AWS credentials may be invalid or blocked."
else
  echo "⚠️ AWS credentials not found in environment variables. Skipping AWS CLI configuration."
fi

# Install kubectl
echo "Installing kubectl..."
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/kubectl

# Install Minikube
echo "Installing Minikube..."
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-latest.x86_64.rpm
sudo rpm -Uvh minikube-latest.x86_64.rpm

# Install eksctl
echo "Installing eksctl..."
curl -sL "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz" | tar xz -C /tmp
sudo mv /tmp/eksctl /usr/local/bin

echo ""
echo "✅ All tools installed successfully!"
echo "🔍 Tool Versions:"

echo "Docker version:       $(docker --version)"
echo "kubectl version:      $(kubectl version --client --short)"
echo "Minikube version:     $(minikube version | grep version)"
echo "eksctl version:       $(eksctl version)"
echo "AWS CLI version:      $(aws --version)"

echo ""
echo "✅ Setup completed at $(date)"
echo "User data script completed successfully at $(date)" > /tmp/userdata-completion.log
