# Alpacon MCP Server Installation Guide

Comprehensive installation and setup guide for the Alpacon MCP Server across different platforms and use cases.

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation Methods](#installation-methods)
3. [Platform-Specific Setup](#platform-specific-setup)
4. [Token Configuration](#token-configuration)
5. [AI Client Integration](#ai-client-integration)
6. [Verification and Testing](#verification-and-testing)
7. [Advanced Configuration](#advanced-configuration)
8. [Troubleshooting](#troubleshooting)

## System Requirements

### Minimum Requirements

- **Python**: 3.12 or higher
- **Memory**: 256MB RAM available
- **Storage**: 100MB free disk space
- **Network**: Internet connection for API calls
- **Operating System**: Windows 10+, macOS 10.15+, or Linux (any modern distribution)

### Recommended Requirements

- **Python**: 3.12+ with pip and venv
- **Memory**: 512MB RAM available
- **Storage**: 500MB free disk space for logs and cache
- **Network**: Stable broadband connection (1Mbps+)

### Dependencies

The following dependencies are automatically installed:

- **mcp[cli]** ≥1.9.4 - Model Context Protocol framework
- **httpx** ≥0.25.0 - Async HTTP client for API calls
- **websockets** ≥15.0.1 - WebSocket support for real-time features

## Installation Methods

### Method 1: uvx (Recommended)

**Best for:** End users who want zero-configuration setup.

```bash
# Install UV package manager (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run Alpacon MCP Server directly (no installation required)
uvx alpacon-mcp --help

# Run with configuration
uvx alpacon-mcp --config-file ~/.config/alpacon/tokens.json
```

**Advantages:**
- No manual installation or dependency management
- Always uses the latest version
- Isolated environment prevents conflicts
- Works across all platforms

### Method 2: pip Installation

**Best for:** Users familiar with Python package management.

```bash
# Install from PyPI
pip install alpacon-mcp

# Verify installation
alpacon-mcp --help

# Run the server
alpacon-mcp
```

### Method 3: UV Tool Installation

**Best for:** Users who prefer UV's package management.

```bash
# Install UV first
pip install uv

# Install Alpacon MCP as a tool
uv tool install alpacon-mcp

# Run the server
alpacon-mcp
```

### Method 4: Development Installation

**Best for:** Developers, contributors, or users who need the latest features.

```bash
# Clone the repository
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Create and activate virtual environment
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in development mode
uv pip install -e .

# Run from source
python main.py
```

## Platform-Specific Setup

### macOS

**Prerequisites:**
```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python via Homebrew
brew install python@3.12

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Installation:**
```bash
# Method 1: uvx (recommended)
uvx alpacon-mcp --help

# Method 2: pip
pip3 install alpacon-mcp
```

**Configuration Path:**
```bash
# Create configuration directory
mkdir -p ~/.config/alpacon

# Configuration file location
~/.config/alpacon/tokens.json
```

### Windows

**Prerequisites:**
1. **Install Python 3.12+** from [python.org](https://python.org) or Microsoft Store
2. **Install UV:**
   ```powershell
   # Using PowerShell
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

**Installation:**
```powershell
# Method 1: uvx (recommended)
uvx alpacon-mcp --help

# Method 2: pip
pip install alpacon-mcp
```

**Configuration Path:**
```powershell
# Create configuration directory
mkdir %APPDATA%\alpacon

# Configuration file location
%APPDATA%\alpacon\tokens.json
```

### Linux

**Ubuntu/Debian:**
```bash
# Update package list
sudo apt update

# Install Python and pip
sudo apt install python3.12 python3.12-pip python3.12-venv

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

**CentOS/RHEL/Fedora:**
```bash
# Install Python
sudo dnf install python3.12 python3.12-pip

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

**Arch Linux:**
```bash
# Install Python
sudo pacman -S python python-pip

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

**Installation:**
```bash
# Method 1: uvx (recommended)
uvx alpacon-mcp --help

# Method 2: pip
pip3 install --user alpacon-mcp
```

**Configuration Path:**
```bash
# Create configuration directory
mkdir -p ~/.config/alpacon

# Configuration file location
~/.config/alpacon/tokens.json
```

## Token Configuration

### Step 1: Obtain API Tokens

1. **Access Alpacon Workspace:**
   ```
   https://alpacon.io
   ```
   - Or for specific workspace: `https://alpacon.io/workspace/`
   - Currently supports `ap1` region

2. **Generate Tokens:**
   - Navigate to **Settings** → **API Tokens**
   - Click **"Generate New Token"**
   - Copy the token immediately (shown only once)

3. **Configure Permissions:**
   - Click on the token to access settings
   - Configure **Access Control List (ACL)**
   - Set allowed servers, commands, and operations

### Step 2: Create Configuration File

**Linux/macOS:**
```bash
mkdir -p ~/.config/alpacon
nano ~/.config/alpacon/tokens.json
```

**Windows:**
```powershell
mkdir $env:APPDATA\alpacon
notepad $env:APPDATA\alpacon\tokens.json
```

**Configuration Format:**
```json
{
  "ap1": {
    "production": "alpat-ABC123...",
    "staging": "alpat-DEF456...",
    "development": "alpat-GHI789..."
  },
  "us1": {
    "backup": "alpat-JKL012...",
    "disaster-recovery": "alpat-MNO345..."
  },
  "eu1": {
    "europe-main": "alpat-PQR678...",
    "compliance": "alpat-STU901..."
  }
}
```

### Step 3: Environment Variables (Alternative)

Instead of a configuration file, use environment variables:

**Linux/macOS:**
```bash
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="alpat-ABC123..."
export ALPACON_MCP_AP1_STAGING_TOKEN="alpat-DEF456..."
export ALPACON_MCP_US1_BACKUP_TOKEN="alpat-JKL012..."
```

**Windows:**
```powershell
$env:ALPACON_MCP_AP1_PRODUCTION_TOKEN="alpat-ABC123..."
$env:ALPACON_MCP_AP1_STAGING_TOKEN="alpat-DEF456..."
$env:ALPACON_MCP_US1_BACKUP_TOKEN="alpat-JKL012..."
```

**Format:** `ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN`

## AI Client Integration

### Claude Desktop

**Configuration File Location:**
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

**Configuration (uvx method):**
```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"],
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "~/.config/alpacon/tokens.json"
      }
    }
  }
}
```

**Configuration (pip method):**
```json
{
  "mcpServers": {
    "alpacon": {
      "command": "alpacon-mcp",
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "~/.config/alpacon/tokens.json"
      }
    }
  }
}
```

### Cursor IDE

Create `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"],
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "~/.config/alpacon/tokens.json"
      }
    }
  }
}
```

### VS Code with MCP Extension

Add to your VS Code `settings.json`:

```json
{
  "mcp.servers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"],
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "~/.config/alpacon/tokens.json"
      }
    }
  }
}
```

### Continue Extension

Configure in your Continue config:

```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"],
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "~/.config/alpacon/tokens.json"
      }
    }
  }
}
```

## Verification and Testing

### Step 1: Test MCP Server

**Direct server test:**
```bash
# With configuration file
ALPACON_MCP_CONFIG_FILE=~/.config/alpacon/tokens.json uvx alpacon-mcp

# Should show server starting with available tools
```

**Token verification:**
```bash
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
print('Available regions:', tm.get_available_regions())
print('Available workspaces for ap1:', tm.get_available_workspaces('ap1'))
token = tm.get_token('ap1', 'your-workspace')
print('Token status:', '✅ Found' if token else '❌ Not found')
"
```

### Step 2: Test AI Client Connection

**Claude Desktop:**
1. Restart Claude Desktop completely
2. Start a new conversation
3. Try: "What MCP tools are available?"

**Cursor IDE:**
1. Reload the window (Cmd/Ctrl + Shift + P → "Developer: Reload Window")
2. Open a new chat
3. Try: "List available MCP servers"

### Step 3: Test Basic Operations

**Server Listing:**
```
Show me all servers in my production workspace in the ap1 region.
```

**System Information:**
```
Get system information for server [server-id].
```

**Command Execution:**
```
Execute 'uname -a' on server [server-id].
```

## Advanced Configuration

### Custom Configuration File Location

```bash
# Set custom configuration file
export ALPACON_MCP_CONFIG_FILE="/path/to/custom/tokens.json"
uvx alpacon-mcp
```

### Server-Sent Events (SSE) Mode

For web-based integrations:

```bash
# Run in SSE mode
python main_sse.py

# Server available at http://localhost:8237
```

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install -e .

EXPOSE 8237
CMD ["python", "main_sse.py"]
```

```bash
# Build and run
docker build -t alpacon-mcp .
docker run -v $(pwd)/config:/app/config:ro -p 8237:8237 alpacon-mcp
```

### Logging Configuration

Create `logging.conf`:

```ini
[loggers]
keys=root,alpacon_mcp

[handlers]
keys=consoleHandler,fileHandler

[formatters]
keys=simpleFormatter

[logger_root]
level=INFO
handlers=consoleHandler,fileHandler

[logger_alpacon_mcp]
level=DEBUG
handlers=consoleHandler,fileHandler
qualname=alpacon_mcp
propagate=0

[handler_consoleHandler]
class=StreamHandler
level=INFO
formatter=simpleFormatter
args=(sys.stdout,)

[handler_fileHandler]
class=FileHandler
level=DEBUG
formatter=simpleFormatter
args=('alpacon-mcp.log',)

[formatter_simpleFormatter]
format=%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

### Performance Tuning

**Environment Variables:**
```bash
# HTTP timeout settings
export ALPACON_HTTP_TIMEOUT=30
export ALPACON_MAX_CONNECTIONS=100

# Logging level
export ALPACON_LOG_LEVEL=INFO

# Cache settings
export ALPACON_CACHE_TTL=300
```

## Troubleshooting

### Common Installation Issues

#### 1. Python Version Errors

**Problem:** "Python 3.12 is required"

**Solution:**
```bash
# Check Python version
python --version

# Install correct version (Ubuntu example)
sudo apt install python3.12 python3.12-pip python3.12-venv
```

#### 2. Permission Errors

**Problem:** "Permission denied" during installation

**Solution:**
```bash
# Linux/macOS - use user installation
pip install --user alpacon-mcp

# Or use virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install alpacon-mcp
```

#### 3. Network/Firewall Issues

**Problem:** Cannot connect to PyPI or Alpacon API

**Solution:**
```bash
# Test PyPI connectivity
curl -I https://pypi.org

# Test Alpacon API connectivity
curl -I https://api.alpacon.io

# Configure proxy if needed
pip install --proxy http://proxy:port alpacon-mcp
```

### Configuration Issues

#### 1. Token Not Found

**Problem:** "No token found for workspace.region"

**Solution:**
```bash
# Verify configuration file exists and format
cat ~/.config/alpacon/tokens.json

# Check environment variable
echo $ALPACON_MCP_CONFIG_FILE

# Test token loading
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
print('Config file:', tm.config_file)
print('Tokens loaded:', bool(tm.tokens))
"
```

#### 2. Invalid JSON Format

**Problem:** JSON parsing errors

**Solution:**
```bash
# Validate JSON format
python -c "import json; print('Valid JSON' if json.loads(open('~/.config/alpacon/tokens.json').read()) else 'Invalid JSON')"

# Or use online JSON validator
cat ~/.config/alpacon/tokens.json | python -m json.tool
```

### AI Client Issues

#### 1. MCP Server Not Starting

**Problem:** Client shows "MCP server failed to start"

**Solutions:**
1. **Check command path:**
   ```bash
   which uvx
   which alpacon-mcp
   ```

2. **Use absolute paths:**
   ```json
   {
     "command": "/full/path/to/uvx",
     "args": ["alpacon-mcp"]
   }
   ```

3. **Test command manually:**
   ```bash
   uvx alpacon-mcp --help
   ```

#### 2. Claude Desktop Configuration

**Problem:** Claude doesn't recognize MCP server

**Solutions:**
1. **Verify configuration file location:**
   ```bash
   ls -la ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

2. **Restart Claude completely** (not just refresh)

3. **Check JSON syntax:**
   ```bash
   python -m json.tool ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

### API Connection Issues

#### 1. Authentication Failures

**Problem:** "401 Unauthorized" or "403 Forbidden"

**Solutions:**
1. **Verify token validity:**
   - Login to Alpacon web interface
   - Check token hasn't expired
   - Regenerate if necessary

2. **Check ACL permissions:**
   - Click on token in Alpacon interface
   - Verify allowed servers and commands
   - Update permissions as needed

#### 2. Network Timeouts

**Problem:** "Request timeout" or "Connection failed"

**Solutions:**
```bash
# Test connectivity
curl -H "Authorization: Bearer your-token" https://alpacon.io/api/servers/

# Increase timeout
export ALPACON_HTTP_TIMEOUT=60
```

### Getting Help

1. **Enable Debug Mode:**
   ```bash
   DEBUG=1 uvx alpacon-mcp
   ```

2. **Check Logs:**
   ```bash
   # Find log files
   find ~ -name "*.log" -path "*alpacon*" 2>/dev/null

   # View recent logs
   tail -f ~/.local/share/alpacon-mcp/logs/*.log
   ```

3. **Collect System Information:**
   ```bash
   # System info for support
   echo "OS: $(uname -a)"
   echo "Python: $(python --version)"
   echo "Pip: $(pip --version)"
   echo "UV: $(uv --version 2>/dev/null || echo 'Not installed')"
   echo "Config file: $ALPACON_MCP_CONFIG_FILE"
   ```

4. **Contact Support:**
   - **GitHub Issues:** https://github.com/alpacax/alpacon-mcp/issues
   - **Email:** support@alpacax.com
   - **Include:** Error messages, system info, configuration (without tokens)

## Next Steps

After successful installation:

1. **[Getting Started Guide](getting-started.md)** - Basic usage and first tasks
2. **[API Reference](api-reference.md)** - Complete tool documentation
3. **[Configuration Guide](configuration.md)** - Advanced configuration options
4. **[Usage Examples](examples.md)** - Real-world usage scenarios

---

**Installation complete?** Continue with the [Getting Started Guide](getting-started.md) to begin managing your infrastructure with AI!