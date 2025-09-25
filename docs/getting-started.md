# Getting Started with Alpacon MCP Server

This guide will help you set up and configure the Alpacon MCP Server in just a few minutes.

## 📋 Prerequisites

Before you begin, make sure you have:

- [ ] **Python 3.12 or higher** installed on your system
- [ ] **An active Alpacon account** with server access
- [ ] **API tokens** for your Alpacon workspace
- [ ] **An MCP-compatible client** (Claude Desktop, Cursor, VS Code, etc.)

## 🚀 Quick Setup

### Method 1: Using uvx (Recommended - Zero Installation)

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run directly without any installation
uvx alpacon-mcp --help

# Set up environment variables and run
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="your-token-here"
uvx alpacon-mcp
```

### Method 2: Traditional Installation

#### Step 1: Install UV Package Manager

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using pip
pip install uv

# Or using brew (macOS)
brew install uv
```

#### Step 2: Install from PyPI

```bash
# Install alpacon-mcp
pip install alpacon-mcp

# Or using UV
uv tool install alpacon-mcp

# Run the server
alpacon-mcp
```

### Method 3: Development Setup

```bash
# Clone the repository
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp

# Create virtual environment
uv venv

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate     # Windows

# Install dependencies
uv pip install mcp[cli] httpx
```

### Step 3: Get API Token from Alpacon

Before configuring authentication, you need to obtain API tokens from your Alpacon workspace:

#### 3.1 Generate API Token

1. **Visit your Alpacon workspace**: `https://workspace.region.alpacon.io`
   - Example: `https://production.ap1.alpacon.io`
   - Example: `https://alpacax.dev.alpacon.io`

2. **Log in** to your Alpacon account

3. **Navigate to API Token**:
   - Click **"API Token"** in the left sidebar
   - This section manages your authentication tokens

4. **Generate or Copy Token**:
   - Click "Create New Token" if you don't have one
   - Or copy an existing token
   - **Save this token securely** - you'll need it for configuration

5. **Configure Token Permissions (ACL)**:
   - **Click on the token** to open its details page
   - Navigate to **Access Control List (ACL)** settings
   - **Configure permissions** for:
     - Allowed commands (e.g., `ls`, `pwd`, `systemctl status`)
     - Server access permissions
     - File transfer operations
   - **Save the ACL configuration**

> ⚠️ **Important**: Command execution will fail with 403/404 errors if commands are not pre-approved in ACL settings

#### 3.2 Configure Authentication

Create your token configuration file:

```bash
# Create config directory
mkdir -p config

# Create token file
cat > config/token.json << 'EOF'
{
  "ap1": {
    "your-workspace": "your-api-token-here"
  }
}
EOF

# Edit with your actual tokens
nano config/token.json  # or your preferred editor
```

**Token Configuration Format:**
```json
{
  "ap1": {
    "company-main": "your-api-token-here",
    "company-backup": "your-backup-token-here"
  },
  "us1": {
    "backup-site": "your-us-token-here"
  },
  "eu1": {
    "enterprise": "your-eu-token-here"
  }
}
```

### Step 4: Test the Server

Verify everything is working:

```bash
# Test the server
python main.py --test

# Or run in stdio mode
python main.py
```

You should see output indicating the server is running and tools are loaded.

### Step 5: Configure Your MCP Client

Choose your preferred AI client and follow the setup:

#### Claude Desktop

Edit your Claude configuration file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/absolute/path/to/alpacon-mcp"
    }
  }
}
```

#### Cursor IDE

Create `.cursor/mcp_config.json` in your project:

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./path/to/alpacon-mcp"
    }
  }
}
```

#### VS Code

Install the MCP extension and add to `settings.json`:

```json
{
  "mcp.servers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./path/to/alpacon-mcp"
    }
  }
}
```

## ✅ Verification

Test your setup with these simple commands in your AI client:

1. **Check server list**:
   > "Show me all servers in the ap1 region"

2. **Get system information**:
   > "Get system information for server [server-id]"

3. **Check metrics**:
   > "Show CPU usage for the last hour for server [server-id]"

## 🎯 First Tasks

Now that you're set up, try these common tasks:

### Monitor Server Health
```
"Give me a comprehensive health check for server [server-id] including CPU, memory, and disk usage"
```

### Manage System Users
```
"List all system users on server [server-id] who can login"
```

### Execute Commands
```
"Execute 'df -h' command on server [server-id] and show the results"
```

### Set Up Alerts
```
"Show me current alert rules and help me create a new CPU usage alert"
```

## 🔧 Advanced Configuration

### Custom Config File Path

```bash
python main.py --config-file /path/to/custom-tokens.json
```

### Custom Config File

```bash
export ALPACON_CONFIG_FILE=".config/token.json"
python main.py
```

### SSE Mode (Server-Sent Events)

```bash
python main_sse.py
```

## 🚨 Common Issues

### 1. Python Not Found
```bash
# Make sure Python is in your PATH
which python  # Should show Python location

# Or use python3
python3 main.py
```

### 2. Permission Errors
```bash
# Make sure virtual environment is activated
source .venv/bin/activate
```

### 3. Token Authentication Failed
- Double-check your API tokens in `.config/token.json`
- Verify workspace names match your Alpacon account
- Ensure tokens have proper permissions

### 4. MCP Client Connection Issues
- Use absolute paths in configuration
- Restart your MCP client after configuration
- Check client logs for error messages

## 📚 Next Steps

Now that you're up and running:

- 📖 **[Configuration Guide](configuration.md)** - Learn about advanced settings
- 🔧 **[API Reference](api-reference.md)** - Explore all available tools
- 💡 **[Examples](examples.md)** - See common usage patterns
- 🛟 **[Troubleshooting](troubleshooting.md)** - Solve common problems

## 💡 Pro Tips

1. **Use .config directory** for local testing and development
2. **Keep tokens secure** - never commit them to repositories
3. **Test with simple commands** first before complex operations
4. **Check server logs** if something isn't working as expected

---

**Ready to explore?** Head to the [API Reference](api-reference.md) to see all available tools and capabilities!