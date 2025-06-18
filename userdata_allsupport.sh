#!/bin/bash

set -e

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/userdata-execution.log
}

log "Starting userdata script execution..."
log "Current user: $(whoami)"
log "OS Information: $(grep PRETTY_NAME /etc/os-release)"

# Detect package manager and OS
if command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    log "Detected package manager: dnf"
elif command -v yum &> /dev/null; then
    PKG_MANAGER="yum"
    log "Detected package manager: yum"
elif command -v apt-get &> /dev/null; then
    PKG_MANAGER="apt-get"
    log "Detected package manager: apt-get"
else
    log "ERROR: No supported package manager found!"
    exit 1
fi

log "Updating system packages..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    apt-get update -y && apt-get upgrade -y
else
    $PKG_MANAGER update -y
fi

log "Installing basic packages..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    apt-get install -y python3-pip openssl jq wget unzip conntrack
else
    $PKG_MANAGER install -y python3-pip openssl jq wget unzip
    if [ "$PKG_MANAGER" = "dnf" ]; then
        $PKG_MANAGER install -y conntrack
    else
        $PKG_MANAGER install -y conntrack-tools || log "Warning: conntrack-tools not found"
    fi
fi

log "Installing Docker..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    apt-get install -y docker.io
elif [ "$PKG_MANAGER" = "yum" ]; then
    yum install -y docker
else
    dnf install -y docker
fi
systemctl enable docker && systemctl start docker
usermod -aG docker ec2-user
log "Docker installed and ec2-user added to docker group"

log "Installing kubectl..."
KUBECTL_VERSION=$(curl -Ls https://dl.k8s.io/release/stable.txt)
curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
rm kubectl
log "kubectl installed: $(kubectl version --client --short 2>/dev/null || echo 'version check failed')"

log "Installing Minikube..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
    install minikube-linux-amd64 /usr/local/bin/minikube
    rm minikube-linux-amd64
else
    curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-latest.x86_64.rpm
    $PKG_MANAGER install -y minikube-latest.x86_64.rpm
    rm minikube-latest.x86_64.rpm
fi
log "Minikube installed: $(minikube version --short 2>/dev/null || echo 'version check failed')"

log "Installing eksctl..."
ARCH=$(uname -m)
case "$ARCH" in
  x86_64) ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
  *) log "Unsupported architecture: $ARCH" && exit 1 ;;
esac
PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')_${ARCH}"
EKSCTL_URL="https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_${PLATFORM}.tar.gz"
log "Downloading eksctl from $EKSCTL_URL"
curl -sSL "$EKSCTL_URL" -o /tmp/eksctl.tar.gz
if tar -xzf /tmp/eksctl.tar.gz -C /tmp; then
    mv /tmp/eksctl /usr/local/bin/eksctl
    chmod +x /usr/local/bin/eksctl
else
    log "ERROR: Failed to extract eksctl. File type: $(file /tmp/eksctl.tar.gz)"
    exit 1
fi
log "eksctl installed: $(eksctl version 2>/dev/null || echo 'version check failed')"

log "Creating version check script..."
cat > /home/ec2-user/check-versions.sh << 'EOF'
#!/bin/bash
echo "=== Installed Tool Versions ==="
echo "OS: $(grep PRETTY_NAME /etc/os-release | cut -d'"' -f2)"
echo "Docker: $(docker --version 2>/dev/null || echo 'Not found')"
echo "kubectl: $(kubectl version --client --short 2>/dev/null || echo 'Not found')"
echo "Minikube: $(minikube version --short 2>/dev/null || echo 'Not found')"
echo "eksctl: $(eksctl version 2>/dev/null || echo 'Not found')"
echo ""
echo "=== Path Check ==="
echo "Docker path: $(which docker 2>/dev/null || echo 'Not in PATH')"
echo "kubectl path: $(which kubectl 2>/dev/null || echo 'Not in PATH')"
echo "minikube path: $(which minikube 2>/dev/null || echo 'Not in PATH')"
echo "eksctl path: $(which eksctl 2>/dev/null || echo 'Not in PATH')"
echo ""
echo "=== Docker Service Status ==="
systemctl status docker --no-pager -l
EOF
chmod +x /home/ec2-user/check-versions.sh
chown ec2-user:ec2-user /home/ec2-user/check-versions.sh

log "Adding environment setup to .bashrc..."
cat > /home/ec2-user/.bashrc_additions << 'EOF'
if command -v kubectl &> /dev/null; then
    source <(kubectl completion bash)
    alias k=kubectl
    complete -F __start_kubectl k
fi
if command -v eksctl &> /dev/null; then
    source <(eksctl completion bash)
fi
alias d=docker
alias dc=docker-compose
echo "=== Available Tools ==="
echo "Docker: $(docker --version 2>/dev/null || echo 'Not available')"
echo "kubectl: $(kubectl version --client --short 2>/dev/null || echo 'Not available')"
echo "Minikube: $(minikube version --short 2>/dev/null || echo 'Not available')"
echo "eksctl: $(eksctl version 2>/dev/null || echo 'Not available')"
echo ""
EOF
if ! grep -q "bashrc_additions" /home/ec2-user/.bashrc; then
    echo "source ~/.bashrc_additions" >> /home/ec2-user/.bashrc
fi
chown ec2-user:ec2-user /home/ec2-user/.bashrc_additions

log "Ensuring /usr/local/bin is in PATH..."
echo 'PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' > /etc/environment

log "Verifying final installations..."
for cmd in docker kubectl minikube eksctl; do
    if command -v $cmd &> /dev/null; then
        log "✅ $cmd installed successfully"
    else
        log "❌ $cmd installation failed"
    fi
done

echo "userdata-completed-$(date -Iseconds)" > /tmp/userdata-completion.log
log "User data script completed successfully!"

systemctl restart docker
log "Docker service restarted"
log "=== INSTALLATION COMPLETE ==="
log "Please log out and log back in for group changes to take effect"
log "Or run: newgrp docker"
