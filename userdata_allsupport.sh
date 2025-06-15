#!/bin/bash

set -e

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/userdata-execution.log
}

log "Starting userdata script execution..."
log "Current user: $(whoami)"
log "OS Information: $(cat /etc/os-release | grep PRETTY_NAME)"

# Detect package manager and OS
if command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    log "Detected package manager: dnf (Amazon Linux 2023/Fedora/RHEL)"
elif command -v yum &> /dev/null; then
    PKG_MANAGER="yum"
    log "Detected package manager: yum (Amazon Linux 2/CentOS)"
elif command -v apt-get &> /dev/null; then
    PKG_MANAGER="apt-get"
    log "Detected package manager: apt-get (Ubuntu/Debian)"
else
    log "ERROR: No supported package manager found!"
    exit 1
fi

log "Updating system packages..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    apt-get update -y
    apt-get upgrade -y
else
    $PKG_MANAGER update -y
fi

log "Installing basic packages..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    apt-get install -y python3-pip openssl jq wget unzip conntrack
else
    $PKG_MANAGER install -y python3-pip openssl jq wget unzip
    # conntrack might have different package name
    if [ "$PKG_MANAGER" = "dnf" ]; then
        $PKG_MANAGER install -y conntrack
    else
        $PKG_MANAGER install -y conntrack-tools || log "Warning: conntrack-tools not found"
    fi
fi

log "Installing Docker..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    # Ubuntu/Debian Docker installation
    apt-get install -y docker.io
    systemctl enable docker
    systemctl start docker
elif [ "$PKG_MANAGER" = "yum" ]; then
    # Amazon Linux 2 Docker installation
    yum install -y docker
    systemctl enable docker
    systemctl start docker
else
    # Amazon Linux 2023/Fedora Docker installation
    dnf install -y docker
    systemctl enable docker
    systemctl start docker
fi

# Add ec2-user to docker group
usermod -aG docker ec2-user
log "Added ec2-user to docker group"

log "Installing kubectl..."
# Get latest stable kubectl version
KUBECTL_VERSION=$(curl -Ls https://dl.k8s.io/release/stable.txt)
curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
chmod +x kubectl
mv kubectl /usr/local/bin/kubectl
log "kubectl installed: $(/usr/local/bin/kubectl version --client --short 2>/dev/null || echo 'version check failed')"

log "Installing Minikube..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
    # Ubuntu installation
    curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
    install minikube-linux-amd64 /usr/local/bin/minikube
    rm minikube-linux-amd64
else
    # RPM-based installation
    curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-latest.x86_64.rpm
    if [ "$PKG_MANAGER" = "dnf" ]; then
        dnf install -y minikube-latest.x86_64.rpm
        dnf install -y mariadb105
    else
        yum install -y minikube-latest.x86_64.rpm
        yum install -y mariadb105
    fi
    rm minikube-latest.x86_64.rpm
fi
log "Minikube installed: $(minikube version --short 2>/dev/null || echo 'version check failed')"

log "Installing eksctl..."
# Download and install eksctl
ARCH=$(uname -m)
PLATFORM=$(uname -s)_$ARCH
curl --silent --location "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_$PLATFORM.tar.gz" | tar xz -C /tmp
mv /tmp/eksctl /usr/local/bin
chmod +x /usr/local/bin/eksctl
log "eksctl installed: $(/usr/local/bin/eksctl version 2>/dev/null || echo 'version check failed')"

log "Creating version check script..."
cat > /home/ec2-user/check-versions.sh << 'EOF'
#!/bin/bash
echo "=== Installed Tool Versions ==="
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
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
# Add kubectl completion
if command -v kubectl &> /dev/null; then
    source <(kubectl completion bash)
    alias k=kubectl
    complete -F __start_kubectl k
fi

# Add eksctl completion
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

# Add to existing .bashrc
if ! grep -q "bashrc_additions" /home/ec2-user/.bashrc; then
    echo "source ~/.bashrc_additions" >> /home/ec2-user/.bashrc
fi
chown ec2-user:ec2-user /home/ec2-user/.bashrc_additions

log "Setting up PATH..."
# Ensure /usr/local/bin is in PATH
if ! grep -q "/usr/local/bin" /etc/environment; then
    echo 'PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' > /etc/environment
fi

log "Final verification..."
# Test installations
if command -v docker &> /dev/null; then
    log "✅ Docker installed successfully"
else
    log "❌ Docker installation failed"
fi

if command -v kubectl &> /dev/null; then
    log "✅ kubectl installed successfully"
else
    log "❌ kubectl installation failed"
fi

if command -v minikube &> /dev/null; then
    log "✅ minikube installed successfully"
else
    log "❌ minikube installation failed"
fi

if command -v eksctl &> /dev/null; then
    log "✅ eksctl installed successfully"
else
    log "❌ eksctl installation failed"
fi

# Create completion marker
echo "userdata-completed-$(date -Iseconds)" > /tmp/userdata-completion.log
log "User data script completed successfully!"

# Restart docker to ensure ec2-user group membership takes effect
systemctl restart docker
log "Docker service restarted"

log "=== INSTALLATION COMPLETE ==="
log "Please log out and log back in for group changes to take effect"
log "Or run: newgrp docker"