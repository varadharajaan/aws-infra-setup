#!/bin/bash

set -e

echo "🔄 Updating system..."
sudo dnf update -y

echo "📦 Installing required packages..."
echo "🔹 Installing python3 pip openssl..."
sudo dnf install -y python3-pip openssl
echo "🔹 Installing jq..."
sudo dnf install -y jq
echo "🔹 Installing curl..."
sudo dnf install -y curl

echo "🐳 Installing Docker..."
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

echo "📦 Installing kubectl (latest stable)..."
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/kubectl

echo "🟢 Installing Minikube..."
sudo dnf install -y conntrack
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-latest.x86_64.rpm
sudo rpm -Uvh minikube-latest.x86_64.rpm

echo "🌲 Installing eksctl..."
curl --silent --location "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz" | tar xz -C /tmp
sudo mv /tmp/eksctl /usr/local/bin

echo ""
echo "🎉 All tools installed successfully!"
echo ""
echo "🧾 Tool Versions:"
echo "🔹 Docker:       $(docker --version)"
echo "🔹 kubectl:      $(kubectl version --client --short)"
echo "🔹 Minikube:     $(minikube version | grep version)"
echo "🔹 eksctl:       $(eksctl version)"

echo ""
echo "✅ Setup completed at $(date)"
echo "📍 Instance is ready for use!"

# Log completion to a file for verification
echo "User data script completed successfully at $(date)" > /tmp/userdata-completion.log