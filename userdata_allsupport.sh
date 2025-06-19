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
    log "Detected package manager: dnf (Amazon Linux 2023/Fedora/RHEL)"
else
    log "ERROR: No supported package manager found!"
    exit 1
fi

log "Updating system packages..."
$PKG_MANAGER update -y

log "Installing basic packages..."
$PKG_MANAGER install -y python3-pip openssl jq wget unzip conntrack

log "Installing Docker..."
$PKG_MANAGER install -y docker
systemctl enable docker
systemctl start docker

# Add ec2-user to docker group
usermod -aG docker ec2-user
log "Added ec2-user to docker group"

log "Installing kubectl..."
KUBECTL_VERSION=$(curl -Ls https://dl.k8s.io/release/stable.txt)
curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
chmod +x kubectl
mv kubectl /usr/local/bin/kubectl
log "kubectl installed: $(kubectl version --client --short 2>/dev/null || echo 'version check failed')"

log "Installing Minikube (binary)..."
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
install minikube-linux-amd64 /usr/local/bin/minikube
rm minikube-linux-amd64
log "Minikube installed: $(minikube version --short 2>/dev/null || echo 'version check failed')"

log "Installing eksctl..."
ARCH=$(uname -m)
if [[ $ARCH == "aarch64" ]]; then
    ARCH="arm64"
fi
PLATFORM="linux_$ARCH"
curl --silent --location "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_${PLATFORM}.tar.gz" | tar xz -C /tmp
mv /tmp/eksctl /usr/local/bin
chmod +x /usr/local/bin/eksctl
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

log "Creating environment setup script..."
cat > /home/ec2-user/.bashrc_additions << 'EOF'
# kubectl completion
if command -v kubectl &> /dev/null; then
    source <(kubectl completion bash)
    alias k=kubectl
    complete -F __start_kubectl k
fi

# eksctl completion
if command -v eksctl &> /dev/null; then
    source <(eksctl completion bash)
fi

# Docker aliases
alias d=docker
alias dc=docker-compose

# Show versions on login
echo "=== Available Tools ==="
echo "Docker: $(docker --version 2>/dev/null || echo 'Not available')"
echo "kubectl: $(kubectl version --client --short 2>/dev/null || echo 'Not available')"
echo "minikube: $(minikube version --short 2>/dev/null || echo 'Not available')" 
echo "eksctl: $(eksctl version 2>/dev/null || echo 'Not available')"
echo ""
EOF

# Append additions to .bashrc
if ! grep -q "bashrc_additions" /home/ec2-user/.bashrc; then
    echo "source ~/.bashrc_additions" >> /home/ec2-user/.bashrc
fi
chown ec2-user:ec2-user /home/ec2-user/.bashrc_additions

log "Setting up PATH..."
if ! grep -q "/usr/local/bin" /etc/environment; then
    echo 'PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' > /etc/environment
fi

log "Final verification..."
for tool in docker kubectl minikube eksctl; do
    if command -v $tool &> /dev/null; then
        log "✅ $tool installed successfully"
    else
        log "❌ $tool installation failed"
    fi
done

# Completion marker
echo "userdata-completed-$(date -Iseconds)" > /tmp/userdata-completion.log
log "User data script completed successfully!"

# Restart docker to apply group changes
systemctl restart docker
log "Docker service restarted"

log "=== INSTALLATION COMPLETE ==="
log "Please log out and log back in for group changes to take effect"
log "Or run: newgrp docker"
