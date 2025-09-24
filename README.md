# Alpacon MCP Server

> 🚀 **AI-Powered Server Management** - Connect Claude, Cursor, and other AI tools directly to your Alpacon infrastructure

An advanced MCP (Model Context Protocol) server that bridges AI assistants with Alpacon's server management platform, enabling natural language server administration, monitoring, and automation.

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## ✨ What is Alpacon MCP Server?

The Alpacon MCP Server transforms how you interact with your server infrastructure by connecting AI assistants directly to Alpacon's management platform. Instead of switching between interfaces, you can now manage servers, monitor metrics, execute commands, and troubleshoot issues using natural language.

### 🎯 Key Benefits

- **Natural Language Server Management** - "Show me CPU usage for all web servers in production"
- **AI-Powered Troubleshooting** - "Investigate why server-web-01 is slow and suggest fixes"
- **Unified Multi-Region Control** - Manage servers across AP1, US1, EU1 regions seamlessly
- **Real-Time Monitoring Integration** - Access metrics, logs, and events through AI conversations
- **Secure WebSH & File Operations** - Execute commands and transfer files via AI interface

## 🌟 Core Features

### 🖥️ **Server Management**
- List and monitor servers across regions
- Get detailed system information and specifications
- Create and manage server documentation
- Multi-workspace and multi-region support

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
- WebSH sessions for secure shell access
- Command execution with real-time output
- File upload/download via WebFTP
- Session management and monitoring

### 📋 **Event Management**
- Command acknowledgment and tracking
- Event search and filtering
- Execution history and status
- Automated workflow coordination

## 🚀 Quick Start

### 1. **Installation**
```bash
# Clone and setup
git clone https://github.com/your-repo/alpacon-mcp.git
cd alpacon-mcp

# Install with UV (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv && source .venv/bin/activate
uv pip install mcp[cli] httpx

# Test installation
python main.py --test
```

### 2. **Configure Authentication**
```bash
# Setup tokens
mkdir -p config
cp config/token.json.example config/token.json
# Edit with your Alpacon API tokens
```

**Token Configuration:**
```json
{
  "ap1": {
    "company-prod": "your-company-prod-token",
    "company-dev": "your-company-dev-token"
  },
  "us1": {
    "backup-site": "your-backup-token"
  }
}
```

### 3. **Connect to AI Client**

#### Claude Desktop
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/path/to/alpacon-mcp"
    }
  }
}
```

#### Cursor IDE
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./alpacon-mcp"
    }
  }
}
```

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

## 🔧 Available Tools

### 🖥️ Server Management
- **servers_list** - List all servers in region/workspace
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
- **websh_session_create** - Start secure shell sessions
- **websh_command_execute** - Execute commands remotely
- **webftp_upload_file** - Transfer files to servers
- **webftp_downloads_list** - Browse downloadable content

### 📋 Event Management
- **list_events** - Browse server events and logs
- **search_events** - Find specific events
- **acknowledge_command** - Confirm command receipt
- **finish_command** - Mark commands as complete

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

### Multi-Region Management
```bash
# Configure tokens for multiple regions
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
tm.set_token('ap1', 'company-prod', 'ap1-company-prod-token')
tm.set_token('us1', 'backup-site', 'us1-backup-token')
tm.set_token('eu1', 'company-eu', 'eu1-company-token')
"
```

### Custom Config File
```bash
# Use custom config file location
export ALPACON_CONFIG_FILE="/path/to/custom-tokens.json"
python main.py
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
# Server available at http://localhost:8005
```

## 🔒 Security & Best Practices

- **Secure Token Storage** - Tokens encrypted and never committed to git
- **Region-Based Access Control** - Separate tokens per environment
- **Audit Logging** - All operations logged for security review
- **Connection Validation** - API endpoints verified before execution

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