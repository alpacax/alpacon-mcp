# Installation guide

Complete installation guide for the Alpacon MCP Server across different platforms and environments.

## 📋 Prerequisites

### System requirements

- **Python 3.12 or higher**
- **Git** (for cloning the repository)
- **UV package manager** (recommended) or **pip**
- **Active Alpacon account** with API access
- **MCP-compatible client** (Claude Desktop, Cursor, VS Code, etc.)

### Platform support

| Platform | Status | Notes |
|----------|--------|-------|
| macOS (Intel) | ✅ Fully supported | Tested on macOS 10.15+ |
| macOS (Apple Silicon) | ✅ Fully supported | Tested on macOS 11+ |
| Linux (Ubuntu/Debian) | ✅ Fully supported | Tested on Ubuntu 20.04+ |
| Linux (RHEL/CentOS) | ✅ Fully supported | Tested on RHEL 8+ |
| Windows 10/11 | ✅ Fully supported | PowerShell or WSL2 recommended |
| Docker | ✅ Fully supported | Multi-arch images available |

---

## 🚀 Quick installation

### Using uvx (recommended)

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run Alpacon MCP Server directly
uvx alpacon-mcp

# Run with environment variables
ALPACON_MCP_AP1_PRODUCTION_TOKEN="your-token" uvx alpacon-mcp

# Pin a version — pick a tag from https://github.com/alpacax/alpacon-mcp/releases
uvx alpacon-mcp@<version>
```

**Benefits of uvx:**
- ✅ No installation required
- ✅ Automatic dependency management
- ✅ Version isolation
- ✅ Always runs latest version
- ✅ Easy to update

### Installing as a tool

```bash
# Keep it on PATH as `alpacon-mcp`
uv tool install alpacon-mcp

# Or with pip
pip install alpacon-mcp
```

### Manual installation

```bash
# Clone the repository
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup project
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate     # Windows

# Install dependencies
uv sync

# Configure tokens
mkdir -p config
echo '{"ap1": {"your-workspace": "your-token"}}' > config/token.json
# Edit config/token.json with your actual API tokens

# Test installation
python main.py test
```

---

## 🔧 Detailed installation by platform

### macOS

#### Method 1: Using Homebrew (recommended)

```bash
# Install prerequisites
brew install python@3.12 git

# Install UV
brew install uv

# Clone and setup
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv sync
```

#### Method 2: Using system Python

```bash
# Verify Python version
python3 --version  # Should be 3.12+

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Clone and setup
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv sync
```

#### macOS-specific configuration

```bash
# Add UV to PATH (add to ~/.zshrc or ~/.bash_profile)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

# Set up Claude Desktop configuration
mkdir -p ~/Library/Application\ Support/Claude/
```

### Linux (Ubuntu/Debian)

#### Install prerequisites

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
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv sync

# Test installation
python main.py test
```

#### Linux service setup (optional)

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
Environment=ALPACON_MCP_CONFIG_FILE=$PWD/config/token.json

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

#### Install prerequisites

```bash
# RHEL/CentOS 8+
sudo dnf install python3.12 python3.12-pip git curl

# Or using yum (older versions)
sudo yum install python312 python312-pip git curl

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

#### Setup process

```bash
# Clone and setup (same as Ubuntu)
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

uv venv
source .venv/bin/activate
uv sync
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

#### Method 1: PowerShell (recommended)

```powershell
# Install UV
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Clone repository
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv
.venv\Scripts\Activate.ps1

# Install dependencies
uv sync

# Test installation
python main.py test
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

#### Windows-specific configuration

```powershell
# Set execution policy (if needed)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Add UV to PATH (add to PowerShell profile)
$env:PATH += ";$env:USERPROFILE\.local\bin"
```

---

## 🐳 Docker installation

Images are published to Docker Hub by the release workflow; the repository name comes from the deployment's `DOCKER_IMAGE` setting, with a `-dev` suffix for pre-release builds. Ask your operator for the exact name, or build from source as shown below.

The image's default command is `main_http.py`—the remote transport with Auth0 JWT auth, which needs the `AUTH0_*` variables. Override the command to run the stdio server instead.

### Building from source

```bash
# Clone repository
git clone https://github.com/alpacax/alpacon-mcp.git
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
services:
  alpacon-mcp:
    build: .
    container_name: alpacon-mcp
    volumes:
      - ./config:/app/config:ro
    ports:
      - "8237:8237"
    environment:
      - ALPACON_MCP_CONFIG_FILE=/app/config/token.json
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8237/health').raise_for_status()"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Run with:
```bash
docker-compose up -d
```

---

## 🔒 Security considerations

### File permissions

```bash
# Secure configuration directory
chmod 700 config/
chmod 600 config/token.json

# Global configuration
chmod 700 ~/.alpacon-mcp/
chmod 600 ~/.alpacon-mcp/token.json
```

### Network security

```bash
# Firewall rules (if needed for SSE mode)
sudo ufw allow 8237/tcp  # Ubuntu/Debian
sudo firewall-cmd --add-port=8237/tcp --permanent  # RHEL/CentOS
```

### User isolation

```bash
# Create dedicated user (Linux)
sudo useradd -r -s /bin/false alpacon-mcp
sudo chown -R alpacon-mcp:alpacon-mcp /opt/alpacon-mcp
```

---

## 🧪 Development installation

### For contributing

```bash
# Clone and setup for development
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Install project dependencies
uv venv
source .venv/bin/activate
uv sync --extra dev

# ruff and pre-commit ship as tools, not as dev dependencies
uv tool install ruff
uv tool install pre-commit

# Install pre-commit hooks (ruff + mypy)
pre-commit install

# Run tests
pytest

# Lint and format
ruff check .
ruff format .

# Type check
mypy --ignore-missing-imports --no-strict-optional .
```

CI runs the same checks: `ruff check`, `ruff format --check`, `mypy`, and `pytest` under a coverage floor. `.github/workflows/test.yml` holds the current threshold.

### Custom configuration

```bash
# Use custom config file location (optional)
export ALPACON_MCP_CONFIG_FILE="/path/to/custom-tokens.json"

# Or for local development
export ALPACON_MCP_CONFIG_FILE="./config/token.json"
```

---

## 🚦 Verification

### Test installation

```bash
# Check a token against the API (prompts for region and workspace)
python main.py test

# Show the configured workspaces
python main.py list

# Verify the server and its tools import
python -c "from server import mcp; print('MCP Server initialized successfully')"
```

### Integration test

```bash
# Test with MCP client
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}}}' | python main.py
```

---

## 🔄 Updates and maintenance

### Update installation

```bash
# Pull latest changes
git pull origin main

# Update dependencies to match the lockfile
uv sync

# Restart service if running
sudo systemctl restart alpacon-mcp  # Linux service
# Or restart Docker container
docker-compose restart alpacon-mcp
```

### Backup configuration

```bash
# Backup tokens before updates
cp config/token.json config/token.json.backup.$(date +%Y%m%d)

# Backup entire configuration
tar -czf alpacon-mcp-backup-$(date +%Y%m%d).tar.gz config/ ~/.alpacon-mcp/
```

---

## ❓ Installation troubleshooting

### Common issues

#### Python version issues
```bash
# Check Python version
python --version
python3 --version

# Use specific Python version
python3.12 -m venv .venv
```

#### UV installation issues
```bash
# Alternative UV installation methods
pip install uv
conda install uv

# Manual installation
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Permission issues
```bash
# Fix common permission issues
sudo chown -R $USER:$USER ~/.local/
chmod +x ~/.local/bin/uv
```

#### Virtual environment issues
```bash
# Recreate virtual environment
rm -rf .venv
uv venv
source .venv/bin/activate
uv sync
```

### Platform-specific issues

#### macOS: Command line tools
```bash
# Install Xcode Command Line Tools if needed
xcode-select --install
```

#### Windows: Long path names
```powershell
# Enable long path names
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

#### Linux: Missing development headers
```bash
# Ubuntu/Debian
sudo apt install python3-dev build-essential

# RHEL/CentOS
sudo dnf install python3-devel gcc
```

---

## 📚 Next steps

After successful installation:

1. **Configure authentication**: See [Configuration Guide](configuration.md)
2. **Set up MCP client**: Follow [Getting Started Guide](getting-started.md)
3. **Test basic functionality**: Try [Usage Examples](examples.md)
4. **Review documentation**: Check [API Reference](api-reference.md)

---

*Need help? Check the [Troubleshooting Guide](troubleshooting.md) or [Getting Started Guide](getting-started.md).*