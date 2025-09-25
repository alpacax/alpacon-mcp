# Installation Guide

Complete installation guide for the Alpacon MCP Server across different platforms and environments.

## 📋 Prerequisites

### System Requirements

- **Python 3.12 or higher**
- **Git** (for cloning the repository)
- **UV package manager** (recommended) or **pip**
- **Active Alpacon account** with API access
- **MCP-compatible client** (Claude Desktop, Cursor, VS Code, etc.)

### Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| macOS (Intel) | ✅ Fully Supported | Tested on macOS 10.15+ |
| macOS (Apple Silicon) | ✅ Fully Supported | Tested on macOS 11+ |
| Linux (Ubuntu/Debian) | ✅ Fully Supported | Tested on Ubuntu 20.04+ |
| Linux (RHEL/CentOS) | ✅ Fully Supported | Tested on RHEL 8+ |
| Windows 10/11 | ✅ Fully Supported | PowerShell or WSL2 recommended |
| Docker | ✅ Fully Supported | Multi-arch images available |

---

## 🚀 Quick Installation

### One-Line Installation (Unix/Linux/macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/your-repo/alpacon-mcp/main/install.sh | bash
```

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup project
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate     # Windows

# Install dependencies
uv pip install mcp[cli] httpx

# Configure tokens
mkdir -p config
echo '{"ap1": {"your-workspace": "your-token"}}' > config/token.json
# Edit config/token.json with your actual API tokens

# Test installation
python main.py --test
```

---

## 🔧 Detailed Installation by Platform

### macOS

#### Method 1: Using Homebrew (Recommended)

```bash
# Install prerequisites
brew install python@3.11 git

# Install UV
brew install uv

# Clone and setup
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install mcp[cli] httpx
```

#### Method 2: Using System Python

```bash
# Verify Python version
python3 --version  # Should be 3.12+

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Clone and setup
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install mcp[cli] httpx
```

#### macOS-Specific Configuration

```bash
# Add UV to PATH (add to ~/.zshrc or ~/.bash_profile)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

# Set up Claude Desktop configuration
mkdir -p ~/Library/Application\ Support/Claude/
```

### Linux (Ubuntu/Debian)

#### Install Prerequisites

```bash
# Update package list
sudo apt update

# Install Python and dependencies
sudo apt install python3.12 python3.12-venv python3.12-pip git curl

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

#### Setup Alpacon MCP

```bash
# Clone repository
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install mcp[cli] httpx

# Test installation
python main.py --test
```

#### Linux Service Setup (Optional)

```bash
# Create systemd service file
sudo tee /etc/systemd/system/alpacon-mcp.service > /dev/null <<EOF
[Unit]
Description=Alpacon MCP Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/.venv/bin/python main.py
Restart=always
Environment=ALPACON_CONFIG_FILE=$PWD/config/token.json

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl enable alpacon-mcp
sudo systemctl start alpacon-mcp

# Check status
sudo systemctl status alpacon-mcp
```

### Linux (RHEL/CentOS/Fedora)

#### Install Prerequisites

```bash
# RHEL/CentOS 8+
sudo dnf install python3.12 python3.12-pip git curl

# Or using yum (older versions)
sudo yum install python312 python312-pip git curl

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

#### Setup Process

```bash
# Clone and setup (same as Ubuntu)
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

uv venv
source .venv/bin/activate
uv pip install mcp[cli] httpx
```

### Windows

#### Prerequisites

```powershell
# Install Python from Microsoft Store or python.org
# Verify installation
python --version

# Install Git from git-scm.com
git --version
```

#### Method 1: PowerShell (Recommended)

```powershell
# Install UV
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Clone repository
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
.venv\Scripts\Activate.ps1

# Install dependencies
uv pip install mcp[cli] httpx

# Test installation
python main.py --test
```

#### Method 2: WSL2 (Windows Subsystem for Linux)

```bash
# Install WSL2 first, then use Linux instructions
wsl --install -d Ubuntu

# In WSL2, follow Ubuntu installation steps
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-pip git curl
# ... continue with Linux setup
```

#### Windows-Specific Configuration

```powershell
# Set execution policy (if needed)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Add UV to PATH (add to PowerShell profile)
$env:PATH += ";$env:USERPROFILE\.local\bin"
```

---

## 🐳 Docker Installation

### Using Pre-built Image

```bash
# Pull the image
docker pull alpacon/mcp-server:latest

# Run with volume for configuration
docker run -d \
  --name alpacon-mcp \
  -v $(pwd)/config:/app/config:ro \
  -p 8237:8237 \
  alpacon/mcp-server:latest
```

### Building from Source

```bash
# Clone repository
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Build image
docker build -t alpacon-mcp:local .

# Run container
docker run -d \
  --name alpacon-mcp \
  -v $(pwd)/config:/app/config:ro \
  -p 8237:8237 \
  alpacon-mcp:local
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'
services:
  alpacon-mcp:
    build: .
    container_name: alpacon-mcp
    volumes:
      - ./config:/app/config:ro
    ports:
      - "8237:8237"
    environment:
      - ALPACON_CONFIG_FILE=/app/config/token.json
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8237/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Run with:
```bash
docker-compose up -d
```

---

## 🔒 Security Considerations

### File Permissions

```bash
# Secure configuration directory
chmod 700 config/
chmod 600 config/token.json

# For .config directory
chmod 700 .config/
chmod 600 .config/token.json
```

### Network Security

```bash
# Firewall rules (if needed for SSE mode)
sudo ufw allow 8237/tcp  # Ubuntu/Debian
sudo firewall-cmd --add-port=8237/tcp --permanent  # RHEL/CentOS
```

### User Isolation

```bash
# Create dedicated user (Linux)
sudo useradd -r -s /bin/false alpacon-mcp
sudo chown -R alpacon-mcp:alpacon-mcp /opt/alpacon-mcp
```

---

## 🧪 Development Installation

### For Contributing

```bash
# Clone and setup for development
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Install project dependencies
uv venv
source .venv/bin/activate
uv pip install -e .[dev]

# Install pre-commit hooks
pre-commit install

# Run tests
python -m pytest tests/

# Run linting
black .
isort .
flake8 .
```

### Custom Configuration

```bash
# Use custom config file location (optional)
export ALPACON_CONFIG_FILE="/path/to/custom-tokens.json"

# Or for local development
export ALPACON_CONFIG_FILE=".config/local-tokens.json"
```

---

## 🚦 Verification

### Test Installation

```bash
# Basic functionality test
python main.py --test

# Test token configuration
python -c "from utils.token_manager import TokenManager; tm = TokenManager(); print('Tokens loaded:', len(tm.get_all_tokens()))"

# Test MCP tools loading
python -c "from server import mcp; print('MCP tools loaded:', len(mcp.get_tools()))"

# Test API connectivity (requires valid token)
python -c "
import asyncio
from tools.server_tools import servers_list
result = asyncio.run(servers_list(region='ap1', workspace='your-workspace'))
print('API test result:', result['status'])
"
```

### Integration Test

```bash
# Test with MCP client
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}}}' | python main.py
```

---

## 🔄 Updates and Maintenance

### Update Installation

```bash
# Pull latest changes
git pull origin main

# Update dependencies
uv pip install --upgrade mcp[cli] httpx

# Restart service if running
sudo systemctl restart alpacon-mcp  # Linux service
# Or restart Docker container
docker-compose restart alpacon-mcp
```

### Backup Configuration

```bash
# Backup tokens before updates
cp config/token.json config/token.json.backup.$(date +%Y%m%d)

# Backup entire configuration
tar -czf alpacon-mcp-backup-$(date +%Y%m%d).tar.gz config/ .config/
```

---

## ❓ Installation Troubleshooting

### Common Issues

#### Python Version Issues
```bash
# Check Python version
python --version
python3 --version

# Use specific Python version
python3.12 -m venv .venv
```

#### UV Installation Issues
```bash
# Alternative UV installation methods
pip install uv
conda install uv

# Manual installation
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Permission Issues
```bash
# Fix common permission issues
sudo chown -R $USER:$USER ~/.local/
chmod +x ~/.local/bin/uv
```

#### Virtual Environment Issues
```bash
# Recreate virtual environment
rm -rf .venv
uv venv
source .venv/bin/activate
uv pip install mcp[cli] httpx
```

### Platform-Specific Issues

#### macOS: Command Line Tools
```bash
# Install Xcode Command Line Tools if needed
xcode-select --install
```

#### Windows: Long Path Names
```powershell
# Enable long path names
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

#### Linux: Missing Development Headers
```bash
# Ubuntu/Debian
sudo apt install python3-dev build-essential

# RHEL/CentOS
sudo dnf install python3-devel gcc
```

---

## 📚 Next Steps

After successful installation:

1. **Configure Authentication**: See [Configuration Guide](configuration.md)
2. **Set up MCP Client**: Follow [Getting Started Guide](getting-started.md)
3. **Test Basic Functionality**: Try [Usage Examples](examples.md)
4. **Review Documentation**: Check [API Reference](api-reference.md)

---

*Need help? Check the [Troubleshooting Guide](troubleshooting.md) or [Getting Started Guide](getting-started.md).*