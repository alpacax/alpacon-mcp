# Alpacon MCP Server

> 🚀 **AI-Powered Server Management** - Connect Claude, Cursor, and other AI tools directly to your Alpacon infrastructure

An advanced MCP (Model Context Protocol) server that bridges AI assistants with Alpacon's server management platform, enabling natural language server administration, monitoring, and automation.

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://python.org)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## ✨ What is Alpacon MCP Server?

The Alpacon MCP Server transforms how you interact with your server infrastructure by connecting AI assistants directly to Alpacon's management platform. Instead of switching between interfaces, you can now manage servers, monitor metrics, execute commands, and troubleshoot issues using natural language.

### 🎯 Key Benefits

- **Natural Language Server Management** - "Show me CPU usage for all web servers in production"
- **AI-Powered Troubleshooting** - "Investigate why server-web-01 is slow and suggest fixes"
- **Multi-Workspace Support** - Connect to your Alpacon workspaces with secure API authentication
- **Real-Time Monitoring Integration** - Access metrics, logs, and events through AI conversations
- **Secure Websh & File Operations** - Execute commands and transfer files via AI interface

## 🌟 Core Features

### 🖥️ **Server Management**
- List and monitor servers in your workspace
- Get detailed system information and specifications
- Create and manage server documentation
- Multi-workspace support with API token management

### 📊 **Real-Time Monitoring**
- CPU, memory, disk, and network metrics
- Performance trend analysis
- Top server identification
- Custom alert rule management
- Comprehensive health dashboards

### 💻 **System Administration**
- User and group management
- Package inventory and updates
- Network interface monitoring
- Disk and partition analysis
- System time and uptime tracking

### 🔧 **Remote Operations**
- Websh sessions for secure shell access
- Command execution with real-time output
- File upload/download via WebFTP
- Session management and monitoring

### 📋 **Event Management**
- Command acknowledgment and tracking
- Event search and filtering
- Execution history and status
- Automated workflow coordination

## 🚀 Quick Start

### For First-Time Users (Recommended)

**Just run this command and follow the interactive setup:**

```bash
uvx alpacon-mcp
```

That's it! The setup wizard will:
1. ✅ Ask for your region (default: ap1)
2. ✅ Ask for your workspace name
3. ✅ Ask for your API token
4. ✅ Save configuration automatically
5. ✅ Test the connection
6. ✅ Show you the Claude Desktop config to copy

**No manual file editing required!**

### Get Your API Token

Before running the setup, get your API token:

1. Visit `https://alpacon.io`
2. Log in to your account
3. Click **"API Token"** in left sidebar
4. Create new token or copy existing one
5. **Configure ACL permissions** (important for command execution)
6. Copy the token (starts with `alpat-...`)

### Connect to Your MCP Client

After setup completes, add the configuration to your MCP client:

```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"]
    }
  }
}
```

**Client-specific locations:**
- **Claude Desktop**:
  - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
  - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- **Cursor**: `.cursor/mcp.json` in your project
- **VS Code**: MCP extension settings

**Restart or reconnect your MCP client** and you're ready! 🎉

---

## 📋 CLI Commands Reference

```bash
uvx alpacon-mcp                                # Start server (auto-setup if needed)
uvx alpacon-mcp setup                          # Run setup wizard (shows token file path)
uvx alpacon-mcp setup --local                  # Use project config instead of global
uvx alpacon-mcp setup --token-file ~/my.json   # Use custom file location
uvx alpacon-mcp test                           # Test your connection
uvx alpacon-mcp list                           # Show configured workspaces
uvx alpacon-mcp add                            # Add another workspace (shows path)
```

---

## 🔧 Advanced Installation Options

### Option A: Install UV (if not already installed)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Option B: Manual Configuration

If you prefer to manually configure tokens:

**Global Configuration** (recommended):
```bash
mkdir -p ~/.alpacon-mcp
echo '{
  "ap1": {
    "production": "alpat-ABC123xyz789...",
    "staging": "alpat-DEF456uvw012..."
  }
}' > ~/.alpacon-mcp/token.json
```

**Project-Local Configuration**:
```bash
mkdir -p config
echo '{
  "ap1": {
    "my-workspace": "alpat-ABC123xyz789..."
  }
}' > config/token.json
```

**Environment Variables**:
```bash
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="alpat-ABC123xyz789..."
uvx alpacon-mcp
```

### Option C: Development Installation
```bash
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp
uv venv && source .venv/bin/activate
uv install
python main.py
```

---

## 🔌 Connect to Other AI Tools

### Cursor IDE

Create `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"]
    }
  }
}
```

### VS Code with MCP Extension

Install the MCP extension and add to settings:

```json
{
  "mcp.servers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"]
    }
  }
}
```

**Note**: Token configuration is automatically discovered from:
1. `~/.alpacon-mcp/token.json` (global - recommended)
2. `./config/token.json` (project-local)
3. Environment variables

## 💬 Usage Examples

### Server Health Monitoring
> *"Give me a comprehensive health check for server web-01 including CPU, memory, and disk usage for the last 24 hours"*

### Performance Analysis
> *"Show me the top 5 servers with highest CPU usage and analyze performance trends"*

### System Administration
> *"List all users who can login on server web-01 and check for any users with sudo privileges"*

### Automated Troubleshooting
> *"Server web-01 is responding slowly. Help me investigate CPU, memory, disk I/O, and network usage to find the bottleneck"*

### Command Execution
> *"Execute 'systemctl status nginx' on server web-01 and check the service logs"*

### File Management
> *"Upload my config.txt file to /home/user/ on server web-01 and then download the logs folder as a zip"*

### Persistent Shell Sessions
> *"Create a persistent shell connection to server web-01 and run these commands: check disk usage, list running processes, and create a backup directory"*

## 🔧 Available Tools

### 🖥️ Server Management
- **servers_list** - List all servers in workspace
- **server_get** - Get detailed server information
- **server_notes_list** - View server documentation
- **server_note_create** - Create server notes

### 📊 Monitoring & Metrics
- **get_cpu_usage** - CPU utilization metrics
- **get_memory_usage** - Memory consumption data
- **get_disk_usage** - Disk space and I/O metrics
- **get_network_traffic** - Network bandwidth usage
- **get_server_metrics_summary** - Comprehensive health overview
- **get_cpu_top_servers** - Identify performance leaders

### 💻 System Information
- **get_system_info** - Hardware specifications and details
- **get_os_version** - Operating system information
- **list_system_users** - User account management
- **list_system_groups** - Group membership details
- **list_system_packages** - Installed software inventory
- **get_network_interfaces** - Network configuration
- **get_disk_info** - Storage device information

### 🔧 Remote Operations

#### Websh (Shell Access)
- **websh_session_create** - Create secure shell sessions
- **websh_command_execute** - Execute single commands
- **websh_websocket_execute** - Single command via WebSocket
- **websh_channel_connect** - Persistent connection management
- **websh_channel_execute** - Execute commands using persistent channels
- **websh_channels_list** - List active WebSocket channels
- **websh_session_terminate** - Close sessions

#### WebFTP (File Management)
- **webftp_upload_file** - Upload files using S3 presigned URLs
- **webftp_download_file** - Download files/folders (folders as .zip)
- **webftp_uploads_list** - Upload history
- **webftp_downloads_list** - Download history
- **webftp_sessions_list** - Active FTP sessions

### 📋 Event Management
- **list_events** - Browse server events and logs
- **search_events** - Find specific events
- **acknowledge_command** - Confirm command receipt
- **finish_command** - Mark commands as complete

### 🔐 Identity and Access Management (IAM)

**User Management**:
- **iam_users_list** - List workspace IAM users with pagination
- **iam_user_get** - Get detailed user information
- **iam_user_create** - Create new users with group assignment
- **iam_user_update** - Update user details and group memberships
- **iam_user_delete** - Remove users from workspace
- **iam_user_permissions_get** - View effective user permissions
- **iam_user_assign_role** - Assign roles to users

**Group & Role Management**:
- **iam_groups_list** - List all workspace groups
- **iam_group_create** - Create groups with permissions
- **iam_roles_list** - List available roles
- **iam_permissions_list** - View all permissions

**Advanced IAM Features**:
- Workspace-level isolation for multi-tenant security
- Role-based access control (RBAC) implementation
- Group-based permission inheritance
- Comprehensive audit trails and logging

### 🔐 Authentication
- **auth_set_token** - Configure API tokens
- **auth_remove_token** - Remove stored tokens

## 🌍 Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| **Claude Desktop** | ✅ Full Support | Recommended client |
| **Cursor IDE** | ✅ Full Support | Native MCP integration |
| **VS Code** | ✅ Full Support | Requires MCP extension |
| **Continue** | ✅ Full Support | Via MCP protocol |
| **Other MCP Clients** | ✅ Compatible | Standard protocol support |

## 📖 Documentation

- 📚 **[Complete Documentation](docs/README.md)** - Full documentation index
- 🚀 **[Getting Started Guide](docs/getting-started.md)** - Step-by-step setup
- ⚙️ **[Configuration Guide](docs/configuration.md)** - Advanced configuration
- 🔧 **[API Reference](docs/api-reference.md)** - Complete tool documentation
- 💡 **[Usage Examples](docs/examples.md)** - Real-world scenarios
- 🛠️ **[Installation Guide](docs/installation.md)** - Platform-specific setup
- 🔍 **[Troubleshooting](docs/troubleshooting.md)** - Common issues and solutions

## 🚀 Advanced Usage

### Multi-Workspace Management
```bash
# Configure tokens for multiple workspaces (ap1 region)
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
tm.set_token('ap1', 'company-prod', 'ap1-company-prod-token')
tm.set_token('ap1', 'company-staging', 'ap1-company-staging-token')
tm.set_token('ap1', 'company-dev', 'ap1-company-dev-token')
"
```

### Custom Config File
```bash
# Use custom config file location
export ALPACON_MCP_CONFIG_FILE="/path/to/custom-tokens.json"
uvx alpacon-mcp
```

### Docker Deployment
```bash
# Build and run with Docker
docker build -t alpacon-mcp .
docker run -v $(pwd)/config:/app/config:ro alpacon-mcp
```

### SSE Mode (HTTP Transport)
```bash
# Run in Server-Sent Events mode for web integration
python main_sse.py
# Server available at http://localhost:8237
```

## 🔒 Security & Best Practices

- **Secure Token Storage** - Tokens encrypted and never committed to git
- **Workspace-Based Access Control** - Separate tokens per workspace environment
- **ACL Configuration Required** - Configure token permissions in Alpacon web interface for command execution
- **Audit Logging** - All operations logged for security review
- **Connection Validation** - API endpoints verified before execution

### ⚠️ Command Execution Limitations

**Important**: Websh and command execution tools can only run **pre-approved commands** configured in your token's ACL settings:

1. **Visit token details** in Alpacon web interface (click on your token)
2. **Configure ACL permissions** for allowed commands, servers, and operations
3. **Commands not in ACL** will be rejected with 403/404 errors
4. **Contact your administrator** if you need additional command permissions

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

- 🐛 **Bug Reports** - Use GitHub issues
- 💡 **Feature Requests** - Open discussions
- 📝 **Documentation** - Help improve guides
- 🔧 **Code Contributions** - Submit pull requests

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Ready to transform your server management experience?**
- 📖 Start with our [Getting Started Guide](docs/getting-started.md)
- 🔧 Explore the [API Reference](docs/api-reference.md)
- 💬 Join our community discussions

*Built with ❤️ for the Alpacon ecosystem* 