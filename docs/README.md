# Alpacon MCP Server documentation

Welcome to the Alpacon MCP (Model Context Protocol) Server documentation. This comprehensive guide will help you get started with server management, monitoring, and automation through AI-powered interfaces.

## 📖 Documentation structure

- **[Getting Started](getting-started.md)**: Quick setup and first steps
- **[Installation Guide](installation.md)**: Detailed installation instructions
- **[Configuration](configuration.md)**: Authentication and settings
- **[API Reference](api-reference.md)**: Complete tool documentation
- **[Examples](examples.md)**: Common usage patterns
- **[Troubleshooting](troubleshooting.md)**: Common issues and solutions
- **[Contributing](../CONTRIBUTING.md)**: How to contribute to the project

## 🚀 Quick start

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

- **Server management**: Monitor and control servers across regions
- **Real-time metrics**: CPU, memory, disk, and network monitoring
- **System information**: Hardware details, OS info, users, and packages
- **Event management**: Command execution and event tracking
- **Websh & WebFTP**: Secure shell and file transfer capabilities

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
- **UV** package manager (recommended)
- **Alpacon API tokens** for your workspace
- **Active Alpacon account** with server access

## 🛠️ Core features

### Server management tools
- List servers across regions
- Get detailed server information
- Create notes and documentation

### Monitoring & metrics
- Real-time CPU, memory, disk usage
- Network traffic monitoring
- Top performing servers analysis
- Custom alert rules

### System information
- Hardware specifications
- Operating system details
- User and group management
- Installed packages inventory
- Network interface details

### Websh & command execution
- Secure shell sessions
- Command execution with history
- Session management
- Real-time output streaming

### Event management
- Command acknowledgment
- Event tracking and logging
- Search and filtering
- Status monitoring

## 🔧 Supported platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Claude Desktop | ✅ Full | Recommended |
| Cursor IDE | ✅ Full | Native integration |
| VS Code | ✅ Full | With MCP extension |
| Continue | ✅ Full | Via MCP protocol |
| Other MCP clients | ✅ Full | Standard MCP protocol |

## 📊 Workspaces

Supports Alpacon workspaces with secure API authentication:
- **ap1**: Currently supported region
- Multiple workspaces per region supported

## 🔐 Security

- Secure token management
- Workspace-based access control
- No token storage in repositories
- Multi-workspace separation

## 📚 Next steps

- **New users**: Start with [Getting Started](getting-started.md)
- **Existing users**: Check [API Reference](api-reference.md)
- **Developers**: See [Contributing Guidelines](../CONTRIBUTING.md)

## 🆘 Need help?

- 📖 Check the [Troubleshooting Guide](troubleshooting.md)
- 🐛 [Report Issues](https://github.com/your-repo/alpacon-mcp/issues)
- 💬 [Discussions](https://github.com/your-repo/alpacon-mcp/discussions)

---

*Built with ❤️ for the Alpacon community*