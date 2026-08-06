# Getting started with Alpacon MCP Server

This guide will help you set up and configure the Alpacon MCP Server in just a few minutes.

## 📋 Prerequisites

Before you begin, make sure you have:

- [ ] **Python 3.12 or higher** installed on your system
- [ ] **An active Alpacon account** with server access
- [ ] **API tokens** for your Alpacon workspace
- [ ] **An MCP-compatible client** (Claude Desktop, Cursor, VS Code, etc.)

> **Want nothing installed at all?** Alpacon hosts a managed MCP server at `https://mcp.alpacon.io/mcp`. Point your client at the URL and sign in through the browser—no token file, no region or workspace configuration. See the [hosted server section in the README](../README.md#-remote-mcp-server-hosted-no-install). The rest of this guide covers running it yourself.

## 🚀 Quick setup

### Method 1: Using uvx (recommended—zero installation)

```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run directly without any installation; the setup wizard starts if nothing is configured yet
uvx alpacon-mcp

# Or configure explicitly first
uvx alpacon-mcp setup
uvx alpacon-mcp test
```

Prefer environment variables? Skip the wizard entirely:

```bash
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="your-token-here"
uvx alpacon-mcp
```

### Method 2: Traditional installation

#### Step 1: Install UV package manager

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

### Method 3: Development setup

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
uv sync
```

### Step 3: Get API token from Alpacon

Before configuring authentication, you need to obtain API tokens from your Alpacon workspace:

#### 3.1 Generate API token

1. **Visit your Alpacon workspace**: `https://alpacon.io`
   - Or if you have a specific workspace: `https://alpacon.io/workspace/`

2. **Log in** to your Alpacon account

3. **Navigate to API Token**:
   - Click **"API Token"** in the left sidebar
   - This section manages your authentication tokens

4. **Generate or Copy Token**:
   - Click "Create New Token" if you don't have one
   - Or copy an existing token
   - **Save this token securely**—you'll need it for configuration

5. **Configure Token Permissions (ACL)**:
   - **Click on the token** to open its details page
   - Navigate to **Access Control List (ACL)** settings
   - **Configure permissions** for:
     - Allowed commands (e.g., `ls`, `pwd`, `systemctl status`)
     - Server access permissions
     - File transfer operations
   - **Save the ACL configuration**

> ⚠️ **Important**: Command execution will fail with 403/404 errors if commands are not pre-approved in ACL settings

#### 3.2 Configure authentication

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

**Token configuration format:**
```json
{
  "ap1": {
    "company-main": "your-api-token-here",
    "company-backup": "your-backup-token-here"
  },
  "us1": {
    "backup-site": "your-us-token-here"
  }
}
```

### Step 4: Test the server

Verify everything is working:

```bash
# Check a token against the API (prompts for region and workspace)
python main.py test

# List the workspaces the configuration knows about
python main.py list

# Or run in stdio mode (waits for an MCP client on stdin)
python main.py
```

`test` asks for a region and workspace, then reports whether that token reaches the API. In stdio mode the log lines go to stderr, so a quiet stdout is expected.

### Step 5: Configure your MCP client

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

Create `.cursor/mcp.json` in your project:

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

#### VS Code

Install the MCP extension and add to `settings.json`:

```json
{
  "mcp.servers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/absolute/path/to/alpacon-mcp"
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

## 🎯 First tasks

Now that you're set up, try these common tasks:

### Monitor server health
```
"Give me a comprehensive health check for server [server-id] including CPU, memory, and disk usage"
```

### Manage system users
```
"List all system users on server [server-id] who can login"
```

### Execute commands
```
"Execute 'df -h' command on server [server-id] and show the results"
```

### Set up alerts
```
"Show me current alert rules and help me create a new CPU usage alert"
```

## 🔧 Advanced configuration

### Custom config file path

```bash
python main.py --config-file /path/to/custom-tokens.json

# Same thing through the environment
export ALPACON_MCP_CONFIG_FILE="/path/to/custom-tokens.json"
python main.py
```

### Registering only some tools

```bash
python main.py --toolsets servers,commands,webftp,metrics
```

Useful when your client has a tool limit. Workspace, health, and Work Session tools are always registered.

### SSE mode (Server-Sent Events)

```bash
python main_sse.py   # 127.0.0.1:8237 by default
```

## 🚨 Common issues

### 1. Python not found
```bash
# Make sure Python is in your PATH
which python  # Should show Python location

# Or use python3
python3 main.py
```

### 2. Permission errors
```bash
# Make sure virtual environment is activated
source .venv/bin/activate
```

### 3. Token authentication failed
- Double-check your API tokens in `~/.alpacon-mcp/token.json` or `./config/token.json`
- Verify workspace names match your Alpacon account
- Ensure tokens have proper permissions

### 4. MCP client connection issues
- Use absolute paths in configuration
- Restart your MCP client after configuration
- Check client logs for error messages

## 📚 Next steps

Now that you're up and running:

- 📖 **[Configuration Guide](configuration.md)**: Learn about advanced settings
- 🔧 **[API Reference](api-reference.md)**: Explore all available tools
- 💡 **[Examples](examples.md)**: See common usage patterns
- 🛟 **[Troubleshooting](troubleshooting.md)**: Solve common problems

## 💡 Pro tips

1. **Use `./config/token.json`** for local testing, `~/.alpacon-mcp/token.json` for everyday use
2. **Keep tokens secure**—never commit them to repositories
3. **Test with simple commands** first before complex operations
4. **Check server logs** if something isn't working as expected

---

**Ready to explore?** Head to the [API Reference](api-reference.md) to see all available tools and capabilities!