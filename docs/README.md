# Alpacon MCP Server Documentation

Welcome to the Alpacon MCP (Model Context Protocol) Server documentation. This comprehensive guide will help you get started with server management, monitoring, and automation through AI-powered interfaces.

## 📖 Documentation Structure

- **[Getting Started](getting-started.md)** - Quick setup and first steps
- **[Installation Guide](installation.md)** - Detailed installation instructions
- **[Configuration](configuration.md)** - Authentication and settings
- **[API Reference](api-reference.md)** - Complete tool documentation
- **[Examples](examples.md)** - Common usage patterns
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions
- **[Contributing](../CONTRIBUTING.md)** - How to contribute to the project

## 🚀 Quick Start

1. **Install dependencies**
   ```bash
   uv venv && source .venv/bin/activate
   uv pip install mcp[cli] httpx
   ```

2. **Configure tokens**
   ```bash
   mkdir -p .config
   cp .config/token.json.example .config/token.json
   # Edit with your actual tokens
   ```

3. **Run the server**
   ```bash
   python main.py
   ```

## 🎯 What is Alpacon MCP?

Alpacon MCP Server connects AI tools directly to Alpacon's server management platform, enabling:

- **Server Management**: Monitor and control servers across regions
- **Real-time Metrics**: CPU, memory, disk, and network monitoring
- **System Information**: Hardware details, OS info, users, and packages
- **Event Management**: Command execution and event tracking
- **WebSH & WebFTP**: Secure shell and file transfer capabilities

## 🏗️ Architecture

```
AI Client (Claude/Cursor/VS Code)
         ↓ MCP Protocol
   Alpacon MCP Server
         ↓ HTTPS API
    Alpacon Platform
         ↓
   Your Servers
```

## 📋 Prerequisites

- **Python 3.12+**
- **uv** package manager (recommended)
- **Alpacon API tokens** for your workspace
- **Active Alpacon account** with server access

## 🛠️ Core Features

### Server Management Tools
- List servers across regions
- Get detailed server information
- Create notes and documentation

### Monitoring & Metrics
- Real-time CPU, memory, disk usage
- Network traffic monitoring
- Top performing servers analysis
- Custom alert rules

### System Information
- Hardware specifications
- Operating system details
- User and group management
- Installed packages inventory
- Network interface details

### WebSH & Command Execution
- Secure shell sessions
- Command execution with history
- Session management
- Real-time output streaming

### Event Management
- Command acknowledgment
- Event tracking and logging
- Search and filtering
- Status monitoring

## 🔧 Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Claude Desktop | ✅ Full | Recommended |
| Cursor IDE | ✅ Full | Native integration |
| VS Code | ✅ Full | With MCP extension |
| Continue | ✅ Full | Via MCP protocol |
| Other MCP Clients | ✅ Full | Standard MCP protocol |

## 📊 Regions & Workspaces

Supports multiple Alpacon regions:
- **ap1** - Asia Pacific 1
- **us1** - US East 1
- **eu1** - Europe 1
- **dev** - Development environment

## 🔐 Security

- Secure token management
- Region-based access control
- No token storage in repositories
- Multi-workspace separation

## 📚 Next Steps

- **New Users**: Start with [Getting Started](getting-started.md)
- **Existing Users**: Check [API Reference](api-reference.md)
- **Developers**: See [Contributing Guidelines](../CONTRIBUTING.md)

## 🆘 Need Help?

- 📖 Check the [Troubleshooting Guide](troubleshooting.md)
- 🐛 [Report Issues](https://github.com/your-repo/alpacon-mcp/issues)
- 💬 [Discussions](https://github.com/your-repo/alpacon-mcp/discussions)

---

*Built with ❤️ for the Alpacon community*