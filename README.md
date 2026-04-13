# Alpacon MCP Server

> 🚀 **Zero-trust server access for AI agents**: Let Claude, Cursor, and other AI tools operate your own and your customers' infrastructure through Alpacon—no VPN, no SSH keys

An MCP (Model Context Protocol) server that extends Alpacon's browser-based, zero-trust infrastructure access to AI assistants. Execute commands, transfer files, monitor metrics, and manage servers across your own and customer environments using natural language.

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://python.org)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## ✨ What is Alpacon MCP server?

[Alpacon](https://www.alpacax.com/alpacon/) provides browser-based server access with zero-trust security built in—no SSH keys, no VPNs. The Alpacon MCP Server brings that same secure access to AI assistants, so you can operate your own and your customers' infrastructure through natural language while every action is authenticated, authorized, and recorded.

### 🎯 Key benefits

- **Zero-trust access for AI**: AI agents authenticate through Alpacon's identity layer—same RBAC, audit trails, and session recording as human users
- **No credential management**: No SSH keys or VPN configs to distribute—one identity, every server
- **Natural language operations**: "Show me CPU usage for all web servers in production"
- **AI-powered troubleshooting**: "Investigate why server-web-01 is slow and suggest fixes"
- **Multi-workspace support**: Access servers across your own and customer environments with a single interface
- **Compliance-ready**: Every AI operation is logged with full session recording and audit trails

## 🌟 Core features

### 🔐 **Zero-trust infrastructure access**
- Authenticate once, access every authorized server
- Role-based access control (RBAC) with time-limited permissions
- Full audit trail for every AI operation
- Automatic session recording for compliance

### 🔧 **Secure remote operations**
- Websh sessions for browser-based terminal access
- Command execution with real-time output
- File upload/download via WebFTP with S3 presigned URLs
- Persistent connections with automatic session management

### 📊 **Real-time monitoring**
- CPU, memory, disk, and network metrics
- Performance trend analysis and top server identification
- Custom alert rule management
- Comprehensive health dashboards

### 💻 **System administration**
- User, group, and IAM management
- Package inventory and system information
- Network interface and disk analysis
- Event tracking and search

## 🚀 Quick start

### For first-time users (recommended)

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

### Get your API token

Before running the setup, get your API token:

1. Visit `https://alpacon.io`
2. Log in to your account
3. Click **"API Token"** in left sidebar
4. Create new token or copy existing one
5. **Configure ACL permissions** (important for command execution)
6. Copy the token (starts with `alpat-...`)

### Connect to your MCP client

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

## 📋 CLI commands reference

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

## 🔧 Advanced installation options

### Option A: install UV (if not already installed)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Option B: manual configuration

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

### Option C: development installation
```bash
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp
uv venv && source .venv/bin/activate
uv install
python main.py
```

---

## 🔌 Connect to other AI tools

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

### VS Code with MCP extension

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

## 💬 Usage examples

### Server health monitoring
> *"Give me a comprehensive health check for server web-01 including CPU, memory, and disk usage for the last 24 hours"*

### Performance analysis
> *"Show me the top 5 servers with highest CPU usage and analyze performance trends"*

### System administration
> *"List all users who can login on server web-01 and check for any users with sudo privileges"*

### Automated troubleshooting
> *"Server web-01 is responding slowly. Help me investigate CPU, memory, disk I/O, and network usage to find the bottleneck"*

### Command execution
> *"Execute 'systemctl status nginx' on server web-01 and check the service logs"*

### File management
> *"Upload my config.txt file to /home/user/ on server web-01 and then download the logs folder as a zip"*

### Persistent shell sessions
> *"Create a persistent shell connection to server web-01 and run these commands: check disk usage, list running processes, and create a backup directory"*

## 🔧 Available tools

### 🖥️ Server management
- **list_servers**: List all servers in workspace
- **get_server**: Get detailed server information
- **get_server_overview**: Comprehensive server overview (system info + metrics)
- **list_server_notes**: View server documentation
- **create_server_note**: Create server notes

### 📊 Monitoring & metrics
- **get_cpu_usage**: CPU utilization metrics
- **get_memory_usage**: Memory consumption data
- **get_disk_usage**: Disk space metrics
- **get_disk_io**: Disk I/O performance metrics
- **get_network_traffic**: Network bandwidth usage
- **get_top_servers**: Top servers by metric type(s)
- **get_alert_rules**: Alert rules configuration
- **get_server_metrics_summary**: Comprehensive health overview

### 💻 System information
- **get_system_info**: Hardware specifications and details
- **get_os_version**: Operating system information
- **list_system_users**: User account management
- **list_system_groups**: Group membership details
- **list_system_packages**: Installed software inventory
- **get_network_interfaces**: Network configuration
- **get_disk_info**: Storage device information
- **get_system_time**: System time and uptime

### 🔧 Remote operations

#### Command API (requires ACL permission)
- **execute_command**: Execute a command on a server and wait for the result
- **list_commands**: List recent command history
- **execute_command_multi_server**: Execute on multiple servers simultaneously

#### Websh (shell access)
- **execute_command**: Execute single command (auto-manages connections)
- **execute_command_batch**: Execute multiple commands on same server
- **websh_session_create**: Create Websh session
- **websh_sessions_list**: List active sessions
- **websh_session_reconnect**: Create new channel for existing session
- **websh_session_terminate**: Close sessions
- **websh_websocket_execute**: Single command via WebSocket
- **websh_websocket_batch_execute**: Multiple commands via WebSocket
- **websh_channel_connect**: Persistent connection management
- **websh_channel_execute**: Execute using persistent channels
- **websh_channels_list**: List active WebSocket channels
- **websh_channel_disconnect**: Disconnect and clean up connections

#### WebFTP (file management)
- **webftp_session_create**: Create file transfer session
- **webftp_upload_file**: Upload files using S3 presigned URLs
- **webftp_download_file**: Download files/folders (folders as .zip)
- **webftp_uploads_list**: Upload history
- **webftp_downloads_list**: Download history
- **webftp_sessions_list**: Active FTP sessions

### 🔔 Alert management
- **list_alerts**: List alerts with optional filtering
- **get_alert**: Get alert details
- **mute_alert**: Mute an alert temporarily
- **create_alert_rule**: Create monitoring thresholds
- **update_alert_rule**: Update alert rule configuration
- **delete_alert_rule**: Delete an alert rule

### 🛡️ Security ACLs
- **list_command_acls**: List command ACL rules
- **create_command_acl**: Create command ACL rule
- **update_command_acl**: Update command ACL rule
- **delete_command_acl**: Delete command ACL rule
- **list_server_acls**: List server ACL rules
- **create_server_acl**: Create server ACL rule
- **list_file_acls**: List file ACL rules
- **create_file_acl**: Create file ACL rule

### 📋 Events & logging
- **list_events**: Browse server events and logs
- **get_event**: Get event details by ID
- **search_events**: Search and filter events

### 📝 Audit logs
- **list_activity_logs**: Audit user and system actions
- **get_activity_log**: Get activity log details
- **list_server_logs**: Server command execution logs
- **list_webftp_logs**: WebFTP file transfer logs

### 🔐 Identity and access management (IAM)

**User management**:
- **list_iam_users**: List workspace IAM users with pagination
- **get_iam_user**: Get detailed user information
- **create_iam_user**: Create new users with group assignment
- **update_iam_user**: Update user details and group memberships
- **delete_iam_user**: Remove users from workspace

**Group management**:
- **list_iam_groups**: List all workspace groups
- **create_iam_group**: Create new IAM group

### ⚙️ Workspace
- **list_workspaces**: List available workspaces

## 🌍 Supported platforms

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

## 🚀 Advanced usage

### Multi-workspace management
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

### Custom config file
```bash
# Use custom config file location
export ALPACON_MCP_CONFIG_FILE="/path/to/custom-tokens.json"
uvx alpacon-mcp
```

### Docker deployment
```bash
# Build and run with Docker
docker build -t alpacon-mcp .
docker run -v $(pwd)/config:/app/config:ro alpacon-mcp
```

### SSE mode (HTTP transport)
```bash
# Run in Server-Sent Events mode for web integration
python main_sse.py
# Server available at http://localhost:8237
```

## 🔒 Security & best practices

- **Zero-trust architecture**: Every request authenticated and authorized through Alpacon's identity layer
- **Session recording**: All Websh and WebFTP operations automatically recorded for audit
- **Workspace-based access control**: Separate tokens per workspace with RBAC
- **ACL configuration required**: Configure token permissions in Alpacon web interface for command execution
- **Audit logging**: All operations logged with full traceability

### ⚠️ Command execution limitations

**Important**: Websh and command execution tools can only run **pre-approved commands** configured in your token's ACL settings:

1. **Visit token details** in Alpacon web interface (click on your token)
2. **Configure ACL permissions** for allowed commands, servers, and operations
3. **Commands not in ACL** will be rejected with 403/404 errors
4. **Contact your administrator** if you need additional command permissions

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

- 🐛 **Bug reports**: Use GitHub issues
- 💡 **Feature requests**: Open discussions
- 📝 **Documentation**: Help improve guides
- 🔧 **Code contributions**: Submit pull requests

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Ready to give your AI agents secure infrastructure access?**
- 📖 Start with our [Getting Started Guide](docs/getting-started.md)
- 🔧 Explore the [API Reference](docs/api-reference.md)
- 💬 Join our community discussions

*Built with ❤️ by [AlpacaX](https://www.alpacax.com/) for the Alpacon ecosystem*