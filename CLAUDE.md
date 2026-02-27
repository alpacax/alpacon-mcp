---
language: en
stack: python
---

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Alpacon MCP Server** - A Model Context Protocol (MCP) server that provides AI assistants with direct access to Alpacon's server management platform. The server enables natural language server administration, monitoring, and automation through HTTP API calls.

## Quick Start Guide

### Simple Setup (Recommended)

```bash
# 1. Run the MCP server - it will automatically start setup wizard
uvx alpacon-mcp

# 2. Follow the interactive prompts:
#    - Enter region (default: ap1)
#    - Enter workspace name
#    - Enter API token (get from https://alpacon.io)

# 3. Add to Claude Desktop config as shown in the output

# 4. Restart Claude Desktop
```

That's it! The setup wizard handles everything automatically.

### Alternative: Manual Setup

If you prefer manual configuration or need to use specific paths:

```bash
# 1. Create config directory
mkdir -p ~/.alpacon-mcp

# 2. Create token.json
echo '{"ap1": {"your-workspace": "your-api-token"}}' > ~/.alpacon-mcp/token.json

# 3. Add to Claude Desktop config:
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"]
    }
  }
}

# 4. Restart Claude Desktop
```

### CLI Commands

```bash
uvx alpacon-mcp                                       # Start MCP server (auto-setup if needed)
uvx alpacon-mcp setup                                 # Run setup wizard (shows token file path)
uvx alpacon-mcp setup --local                         # Configure for current project only
uvx alpacon-mcp setup --token-file ~/my-tokens.json   # Use custom location
uvx alpacon-mcp test                                  # Test API connection
uvx alpacon-mcp list                                  # Show configured workspaces
uvx alpacon-mcp add                                   # Add another workspace (shows path)
```

## Development Commands

### Environment Setup
```bash
uv venv                    # Create virtual environment
source .venv/bin/activate  # Activate virtual environment (Linux/Mac)
uv install                 # Install dependencies from pyproject.toml
```

### Running the MCP Server
```bash
# Run with stdio transport (default MCP mode)
python main.py

# Run with SSE transport (Server-Sent Events mode)
python main_sse.py

# Test the server locally
python -c "from server import mcp; print('MCP Server initialized successfully')"
```

### Testing and Development
```bash
# Run with specific workspace for testing
python main.py  # Then connect via MCP client

# Check server status
curl -X GET "https://alpacon.io/api/servers/servers/" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Architecture Overview

This MCP server provides a **pure HTTP API bridge** to Alpacon's infrastructure management platform. No external CLI dependencies required.

### Core Components

**MCP Server (`server.py`)**
- Built with FastMCP framework
- Supports stdio and SSE transports
- Single shared instance across all tools
- Thread-safe HTTP client for concurrent operations

**Tool Modules** (all in `tools/` directory):
- `server_tools.py` - Server listing, details, and management
- `command_tools.py` - Remote command execution and monitoring (ACL-based)
- `websh_tools.py` - Websh session management, persistent connections, and terminal operations
- `webftp_tools.py` - File transfer and management via S3 presigned URLs
- `metrics_tools.py` - Performance monitoring, metrics, and alerting
- `events_tools.py` - Event logging and search
- `system_info_tools.py` - System information, hardware details, user/group/package management
- `iam_tools.py` - Identity and access management (users, groups)
- `workspace_tools.py` - Workspace and configuration management

**Utilities** (all in `utils/` directory):
- `http_client.py` - Async HTTP client for Alpacon API
- `token_manager.py` - Secure token storage and management
- `decorators.py` - MCP tool decorators (token validation, input validation, error handling, logging)
- `error_handler.py` - Input validators, validation error formatting, circuit breaker
- `common.py` - Shared helpers (token validation, response formatting)
- `logger.py` - Logging configuration
- `setup_wizard.py` - Interactive setup wizard for first-time configuration

**Configuration**:
- `config/token.json` - API tokens by region and workspace
- `pyproject.toml` - Project dependencies and metadata

### Authentication & Token Management

**Authentication Flow**:
1. **Get Token**: Obtain API token from Alpacon web interface (see "API Token Setup" section)
2. **Store Token**: Save in `config/token.json` by region and workspace
3. **Token Retrieval**: `TokenManager` provides secure token access
4. **API Authentication**: HTTP client uses tokens for all API requests
5. **Request Format**: All requests go to Alpacon's API endpoints

**Token Storage Structure**:
```json
{
  "ap1": {
    "workspace-name": "your-api-token-from-web-interface"
  },
  "us1": {
    "workspace-name": "your-api-token-from-web-interface"
  }
}
```

### Tool Registration Pattern

All tools use the unified `@mcp_tool_handler` decorator pattern for consistent error handling and token management:

```python
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler

@mcp_tool_handler(description="Tool description")
async def tool_function(
    server_id: str,
    workspace: str,  # Required parameter (no default)
    region: str = "ap1",
    **kwargs  # Receives token from decorator
) -> Dict[str, Any]:
    """Tool implementation using HTTP API."""
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/endpoint/",
        token=token
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )
```

**Key Benefits**:
- Automatic input validation (region, workspace, server_id, server_ids) before any API call
- Automatic token injection via decorator
- Unified error handling and response formatting
- Reduced boilerplate code (~60% less per function)
- Consistent logging across all tools

### Input Validation

The `with_token_validation` decorator (`utils/decorators.py`) validates inputs **before** token lookup:

1. **Region format** - Must be one of: `ap1`, `us1`, `eu1`, `dev`
2. **Workspace format** - Alphanumeric with hyphens/underscores, 1-63 characters
3. **Server ID format** - Must be valid UUID (when present)
4. **Server IDs list** - Each element must be valid UUID (when present)

File path validation is applied inline in `webftp_upload_file` and `webftp_download_file` using `validate_file_path()` from `utils/error_handler.py`. Rejects path traversal (`../`), relative paths, null bytes, and dangerous characters.

All validators are defined in `utils/error_handler.py` and return user-friendly error responses via `format_validation_error()`.

### Key Architecture Principles

1. **HTTP-First**: All operations use direct HTTP API calls
2. **Async/Await**: Concurrent operations with asyncio
3. **No CLI Dependencies**: Pure Python implementation
4. **Workspace Explicit**: All operations require workspace parameter
5. **Input Validation**: Early validation of region, workspace, server_id, and file paths before API calls
6. **Error Handling**: Comprehensive error handling and reporting
7. **Multi-Workspace**: Support for multiple workspaces across regions

## Available MCP Tools

### 🖥️ Server Management
- `list_servers` - List all servers in workspace
- `get_server` - Get detailed server information
- `get_server_overview` - Get comprehensive server overview (system info + metrics)
- `list_server_notes` - List server documentation
- `create_server_note` - Create server notes

### 💻 Remote Operations (Command API - requires ACL permission)
- `execute_command_with_acl` - Execute commands on servers using Command API
- `execute_command_sync` - Execute and wait for results using Command API
- `get_command_result` - Get command execution results
- `list_commands` - List recent command history
- `execute_command_multi_server` - Execute command on multiple servers simultaneously

**Note**: These tools require API token with command execution ACL permission enabled.

### 🔧 Websh (Command Execution)

**⭐ Recommended: Persistent Connection Tools** (efficient, automatic connection pooling, no ACL required):
- `execute_command` - Execute single command (automatically reuses WebSocket connections)
- `execute_command_batch` - Execute multiple commands efficiently on same server

These tools automatically:
- Reuse existing WebSocket connections for the same server
- Handle session creation and connection management
- Perform health checks and auto-recovery
- Minimize API calls (1 session creation per server instead of per command)

**Session Management**:
- `websh_session_create` - Create Websh session for command execution (non-interactive)
- `websh_sessions_list` - List active sessions
- `websh_session_reconnect` - Create a new user channel for an existing session
- `websh_session_terminate` - Close sessions

**WebSocket-based Execution** (for single-use commands):
- `websh_websocket_execute` - Execute single command via WebSocket
- `websh_websocket_batch_execute` - Execute multiple commands sequentially

**Manual Channel Management** (advanced use only):
- `websh_channel_connect` - Connect to Websh user channel and maintain persistent connection
- `websh_channel_execute` - Execute commands using existing WebSocket connection
- `websh_channels_list` - List active WebSocket channels
- `websh_channel_disconnect` - Disconnect and clean up WebSocket connections

**Note**: Websh tools are for programmatic command execution only. For interactive terminal access, use the Alpacon web interface at https://alpacon.io

### 📁 File Management (WebFTP)
- `webftp_session_create` - Create file transfer session
- `webftp_sessions_list` - List active FTP sessions
- `webftp_upload_file` - Upload local files to servers using S3 presigned URLs with automatic processing
- `webftp_download_file` - Download server files or folders to local storage (folders as .zip)
- `webftp_uploads_list` - List uploaded files (upload history)
- `webftp_downloads_list` - List download requests (download history)

**WebFTP Architecture**: Uses S3 presigned URLs for efficient file transfers. Upload process: local file → S3 → server processing. Download process: server → S3 → local file. Supports both individual files and folder downloads (as ZIP archives).

### 📊 Monitoring & Metrics
- `get_cpu_usage` - CPU utilization metrics
- `get_memory_usage` - Memory usage statistics
- `get_disk_usage` - Disk space metrics
- `get_disk_io` - Disk I/O performance metrics
- `get_network_traffic` - Network interface statistics
- `get_top_servers` - Get top performing servers by metric type(s) - supports multiple metrics in one call
- `get_alert_rules` - Get alert rules configuration
- `get_server_metrics_summary` - Comprehensive metrics overview

### 📋 Events & Logging
- `list_events` - List server events
- `get_event` - Get event details by ID
- `search_events` - Search server events and logs

### 🔍 System Information
- `get_system_info` - Hardware and OS information
- `get_os_version` - Operating system details
- `list_system_users` - User account management
- `list_system_groups` - Group management
- `list_system_packages` - Installed software packages
- `get_network_interfaces` - Network configuration
- `get_disk_info` - Storage and partition information
- `get_system_time` - System time and uptime

### 🔐 Identity and Access Management (IAM)

**User Management**:
- `list_iam_users` - List all IAM users in workspace with pagination support
- `get_iam_user` - Get detailed information about a specific IAM user
- `create_iam_user` - Create new IAM user with groups assignment
- `update_iam_user` - Update existing IAM user (email, name, active status, groups)
- `delete_iam_user` - Delete IAM user from workspace

**Group Management**:
- `list_iam_groups` - List all IAM groups in workspace with pagination support
- `create_iam_group` - Create new IAM group

**IAM Architecture**: Basic identity management supporting users and groups with workspace-level isolation. Group-based permission management.

**Note**: Role and permission management endpoints are not currently implemented in the Alpacon server. The following tools have been removed:
- ~~`list_iam_roles`~~ - Not available
- ~~`assign_iam_user_role`~~ - Not available
- ~~`list_iam_permissions`~~ - Not available
- ~~`get_iam_user_permissions`~~ - Not available

### ⚙️ Authentication & Workspace
- `list_workspaces` - List available workspaces

**Note**: User settings and profile endpoints are not currently implemented in the Alpacon server. The following tools have been removed:
- ~~`get_user_settings`~~ - Not available (was using `/api/user/settings/`)
- ~~`update_user_settings`~~ - Not available (was using `/api/user/settings/`)
- ~~`get_user_profile`~~ - Not available (was using `/api/user/profile/`)

Alternative endpoints available in the server:
- `/api/profiles/preferences/` (profiles app)
- `/api/workspaces/preferences/` (workspaces app)
- `/api/auth0/users/` (auth0 app)

## Dependencies

**Runtime Dependencies** (from `pyproject.toml`):
- `mcp[cli]>=1.9.4` - Model Context Protocol framework
- `httpx>=0.25.0` - Async HTTP client
- `websockets>=15.0.1` - WebSocket support for real-time features

**Development Dependencies**:
- `pytest>=7.0.0` - Testing framework
- `pytest-asyncio>=0.21.0` - Async test support
- `black>=23.0.0` - Code formatting
- `isort>=5.12.0` - Import sorting
- `flake8>=6.0.0` - Linting
- `mypy>=1.0.0` - Type checking

**No External Dependencies**:
- ✅ No alpacon CLI required
- ✅ No subprocess calls
- ✅ Pure Python HTTP implementation
- ✅ Cross-platform compatibility

## Language Guidelines

- **ALL Code Comments**: English only
- **ALL Documentation**: English only
- **ALL Commit Messages**: English only
- **ALL PR Titles/Descriptions**: English only
- **ALL Docstrings**: English only
- **ALL Variable/Function/Class Names**: English only
- **User-facing Output Messages**: Korean for better user experience in CLI/console output

## Naming Conventions

### Technology Names
- **Websh**: Always use "Websh" (not "WebSH") for web shell functionality
  - Correct: `websh_session_create`, "Websh session", "Websh tools"
  - Incorrect: `webSH_session_create`, "WebSH session", "WebSH tools"
- **WebFTP**: Use "WebFTP" for file transfer functionality (maintain existing convention)
- **MCP**: Use "MCP" for Model Context Protocol (maintain existing convention)

### Rationale
- Consistent capitalization reduces confusion across documentation and code
- Matches Alpacon's internal naming conventions
- Ensures uniformity across all project materials

## CRITICAL: MCP-Only Policy

**🚨 ABSOLUTE RULE: Never use alpacon CLI or any external CLI tools**

- ✅ **ONLY USE MCP Tools**: All operations must use MCP tools (`mcp__alpacon__*`)
- ❌ **NO CLI FALLBACK**: Never fall back to CLI commands when MCP fails
- ❌ **NO SUBPROCESS**: Never use `subprocess` or shell commands
- ❌ **NO DIRECT COMMANDS**: Never execute `alpacon`, `ssh`, or any external commands

**If MCP operations fail:**
1. Report the exact error message
2. Suggest alternative MCP approaches
3. Ask user for additional authentication/configuration
4. **NEVER** suggest or attempt CLI solutions

**This ensures:**
- Pure API-based operations
- Consistent authentication model
- No external dependencies
- Reliable cross-platform compatibility

## Important Usage Notes

### Server ID Requirements
⚠️ **Critical**: Always use server UUIDs, not server names for all operations:
- ✅ Correct: `server_id="7e3984de-49ab-4cc6-bcdf-21fbd35858b8"`
- ❌ Incorrect: `server_id="amazon-linux-1"`
- Use `servers_list` to get the correct UUID from the server name

### WebFTP File Paths
- **Local paths**: Absolute paths on the local machine (e.g., `/Users/user/file.txt`)
- **Remote paths**: Absolute paths on the server (e.g., `/home/user/file.txt`)
- **Username**: Optional parameter; if omitted, uses authenticated user's name

### Websh Connection Management
- **Single commands**: Use `websh_websocket_execute` for simplicity
- **Multiple commands**: Use `websh_channel_*` tools for efficiency
- **Channel cleanup**: Always disconnect channels when finished to free resources

## Development Workflow

### Adding New Tools
1. Create function in appropriate `tools/*.py` file
2. Use `@mcp_tool_handler(description="...")` decorator
3. Add `**kwargs` parameter to receive token from decorator
4. Use `success_response()` and `error_response()` helpers
5. Follow async/await pattern for HTTP calls
6. For file path parameters, add inline `validate_file_path()` checks
7. Common parameters (`region`, `workspace`, `server_id`) are validated automatically by the decorator
8. Update this documentation

### API Token Setup

#### Simple Method (Recommended)

Use the interactive setup wizard:

```bash
uvx alpacon-mcp setup
```

The wizard will:
1. Ask for your region (default: ap1)
2. Ask for your workspace name
3. Ask for your API token (hidden input)
4. Save configuration to `~/.alpacon-mcp/token.json`
5. Test the connection
6. Show Claude Desktop config to copy

#### Manual Method

If you need to manually configure or use project-specific settings:

**Global Configuration** (`~/.alpacon-mcp/token.json`):
```bash
mkdir -p ~/.alpacon-mcp
echo '{
  "ap1": {
    "production": "your-api-token-here",
    "staging": "your-staging-token-here"
  }
}' > ~/.alpacon-mcp/token.json
```

**Local Configuration** (`./config/token.json`):
```bash
mkdir -p config
echo '{
  "ap1": {
    "project-workspace": "your-api-token-here"
  }
}' > config/token.json
```

**Priority Order**:
1. Project-local config (`./config/token.json`)
2. Global config (`~/.alpacon-mcp/token.json`)
3. Environment variable (`ALPACON_MCP_AP1_WORKSPACE_TOKEN`)

#### Get API Token from Alpacon

1. Visit `https://alpacon.io`
2. Log in to your account
3. Click **"API Token"** in the left sidebar
4. Create a new token or copy existing token

#### Test Configuration

```bash
# Test connection
uvx alpacon-mcp test

# List configured workspaces
uvx alpacon-mcp list

# Add another workspace
uvx alpacon-mcp add-workspace
```

**Supported Regions**: `ap1` (Asia Pacific), `us1` (US), `eu1` (Europe), `dev` (Development)

### Testing MCP Integration
```bash
# Test with Claude Code or other MCP client
# Add to .mcp.json in your project:
{
  "mcpServers": {
    "alpacon": {
      "command": "python",
      "args": ["/path/to/alpacon-mcp/main.py"]
    }
  }
}
```

## Common Usage Patterns

### Server Management Example:
```python
# List servers
servers = await servers_list(workspace="production", region="ap1")

# Execute command
result = await execute_command_sync(
    server_id="web-server-01",
    command="df -h",
    workspace="production"
)
```

### Monitoring Example:
```python
# Get comprehensive server overview
overview = await get_server_metrics_summary(
    server_id="web-server-01",
    hours=24,
    workspace="production"
)

# Check specific metrics
cpu = await get_cpu_usage(
    server_id="web-server-01",
    start_date="2024-01-01T00:00:00Z",
    end_date="2024-01-02T00:00:00Z",
    workspace="production"
)
```

### Websh Channel Management Example:
```python
# Create Websh session
session = await websh_session_create(
    server_id="server-uuid",
    workspace="production"
)

# Connect to persistent channel
connect_result = await websh_channel_connect(
    channel_id=session["data"]["userchannel_id"],
    websocket_url=session["data"]["websocket_url"],
    session_id=session["data"]["id"]
)

# Execute multiple commands using same connection
result1 = await websh_channel_execute(channel_id, "pwd")
result2 = await websh_channel_execute(channel_id, "ls -la")
result3 = await websh_channel_execute(channel_id, "touch test_file")

# List active channels
channels = await websh_channels_list()

# Clean up connection
await websh_channel_disconnect(channel_id)
```

### WebFTP Example:
```python
# Upload a local file to server using S3 presigned URLs
upload_result = await webftp_upload_file(
    server_id="server-uuid",  # Use server UUID, not name
    local_file_path="/Users/user/config.txt",
    remote_file_path="/home/user/config.txt",
    workspace="production",
    username="optional-username"  # Optional, uses authenticated user if omitted
)

# Download a server file to local storage
download_result = await webftp_download_file(
    server_id="server-uuid",
    remote_file_path="/var/log/app.log",
    local_file_path="/Users/user/Downloads/app.log",
    workspace="production"
)

# Download a folder (creates zip)
folder_download = await webftp_download_file(
    server_id="server-uuid",
    remote_file_path="/var/log/app",
    local_file_path="/Users/user/Downloads/app_logs.zip",
    resource_type="folder",
    workspace="production"
)

# List upload/download history
uploads = await webftp_uploads_list(workspace="production")
downloads = await webftp_downloads_list(workspace="production")
```

## Task Master AI Instructions
**Import Task Master's development workflow commands and guidelines, treat as if import is in the main CLAUDE.md file.**
@./.taskmaster/CLAUDE.md

---

*This MCP server enables AI-powered infrastructure management through natural language interactions with Alpacon's platform.*