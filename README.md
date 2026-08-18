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
- Command execution on one server or many, gated by the token's ACL
- File upload/download via WebFTP with S3 presigned URLs
- Work Sessions that scope every action to an approved, auditable window
- Structured denials that tell the agent how to get authorized instead of failing blind

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

## 🌐 Remote MCP server (hosted, no install)

Don't want to run anything locally? Alpacon hosts a managed MCP server at **`https://mcp.alpacon.io/mcp`** using the streamable-http transport. Just point your AI client at the URL and sign in through your browser.

### Why use the hosted server?

- **No install**: No `uvx`, no Python, no local process to keep running
- **No API token**: You authenticate through your browser (OAuth), not by pasting a token into a config file
- **No `token.json`**: Nothing to create, store, or rotate on your machine
- **No region/workspace config**: The workspaces you can access come from your login—you just say which one to use in your prompt (e.g. *"list servers in the `production` workspace"*)
- **Always up to date**: Run the latest tools without upgrading anything

### How authentication works

The first time your client connects, it opens a browser window for you to log in to Alpacon (Auth0). After you sign in, the client receives a short-lived token and uses it for every request—the same identity, RBAC, and audit trail as the Alpacon web console. If your session needs multi-factor re-verification (for example after an MFA timeout), the client automatically reopens the browser to complete it.

Because access is granted per login, you **do not** set `region`, `workspace`, or any API token in your client config. Instead, you name the **workspace** in your prompt (e.g. *"in the `production` workspace"*)—tools require it, and the AI passes it along. The **region** is resolved automatically from your authorized workspaces, so you rarely need to mention it.

### Add it to your AI client

**Claude Code** (CLI):
```bash
claude mcp add --transport http alpacon https://mcp.alpacon.io/mcp
```
On first use, Claude Code opens your browser to sign in. Verify with `claude mcp list`.

**Claude Desktop**—add a custom connector (Settings → Connectors → Add custom connector) with the URL `https://mcp.alpacon.io/mcp`, or use the `mcp-remote` bridge in `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "alpacon": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.alpacon.io/mcp"]
    }
  }
}
```

**Cursor**—add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "alpacon": {
      "url": "https://mcp.alpacon.io/mcp"
    }
  }
}
```

**VS Code** (native MCP)—add to `.vscode/mcp.json`:
```json
{
  "servers": {
    "alpacon": {
      "type": "http",
      "url": "https://mcp.alpacon.io/mcp"
    }
  }
}
```

> **Tip**: Any MCP client that supports remote/streamable-http servers can connect—just give it the URL `https://mcp.alpacon.io/mcp`. Clients that only support local (stdio) servers should use the `mcp-remote` bridge shown above for Claude Desktop.

### Hosted vs. local—which should I use?

| | Hosted (remote MCP) | Local (`uvx alpacon-mcp`) |
|---|---|---|
| Setup | Add a URL, sign in via browser | Install + configure token |
| Authentication | Browser OAuth (Auth0) | API token in `token.json`/env |
| Region/workspace | Resolved from login; named in prompt | Configured per token |
| Maintenance | None (managed) | Self-managed upgrades |
| Best for | Quick start, most users | Air-gapped/custom deployments, self-hosting |

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
uvx alpacon-mcp --toolsets servers,commands,webftp   # Register only these toolsets
```

---

### Toolsets (selective tool registration)

Local (stdio/SSE) mode can register a subset of toolsets to stay within
client tool limits and reduce per-request token cost. Remote mode
(streamable-http with JWT auth, i.e. `ALPACON_MCP_AUTH_ENABLED=true`)
always registers all tools and relies on the client's tool search
optimization.

```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp", "--toolsets", "servers,commands,webftp,metrics"]
    }
  }
}
```

The `ALPACON_MCP_TOOLSETS` environment variable is also supported; the CLI
argument wins when both are set. Default: `all` (register everything).

Available toolsets (1:1 with tool modules): `servers`, `commands`, `webftp`,
`metrics`, `alerts`, `events`, `system-info`, `iam`, `security`, `audit`,
`approvals`, `webhooks`, `packages`, `certs`, `tokens`. Workspace, health,
and Work Session tools are always registered regardless of selection, as are
the MCP prompts; their names (`workspace`, `health`, `work-sessions`,
`prompts`) are accepted in `--toolsets` but have no effect. Any other
unrecognized name fails at startup.

Narrow selections cut real capability: the workflow prompts still reference
tools such as `execute_command` and `webftp_upload_file`, so an agent
following them will hit "tool not found" if you excluded `commands` or
`webftp`. Select the toolsets your workflows actually use. A few resources
also cross module boundaries: `alpacon://servers/.../overview` is backed by
`system_info_tools`, so `--toolsets servers` alone silently drops it—add
`system-info` to keep it.

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

**Pinning a workspace API host** (optional):

By default the API host is derived from the workspace name as
`https://{workspace}.{region}.alpacon.io`. A workspace's URL slug is a mutable
label, and a freed slug can later be reused by a different workspace, so
re-deriving the host from a stale label could resolve to the wrong
workspace's host. Pin a fixed base URL with the object form of a token entry
instead—the old host stays alive as an alias, so a pinned URL keeps working
across a slug change:

```bash
echo '{
  "us1": {
    "production": {
      "token": "alpat-ABC123xyz789...",
      "url": "https://production.us1.alpacon.io"
    }
  }
}' > ~/.alpacon-mcp/token.json
```

Or via environment variable (wins over the config file):
```bash
export ALPACON_MCP_US1_PRODUCTION_URL="https://production.us1.alpacon.io"
```

### Option C: run from a checkout
```bash
git clone https://github.com/alpacax/alpacon-mcp.git
cd alpacon-mcp
uv venv && source .venv/bin/activate
uv sync
python main.py
```

---

## 🔌 Connect to other AI tools

> Prefer not to install anything? Skip this section and use the [hosted remote MCP server](#-remote-mcp-server-hosted-no-install) instead—just point your client at `https://mcp.alpacon.io/mcp` and sign in via browser.

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

### Audited work under approval
> *"Open a Work Session for restarting nginx on web-01, and once it's approved run the restart and close the session"*

## 🔧 Available tools

### 🖥️ Server management
- **list_servers**: List all servers in workspace
- **get_server**: Get detailed server information
- **get_server_overview**: Comprehensive server overview (hardware, OS, network, disks)
- **update_server**: Rename or relabel a server entry
- **unregister_server**: Unregister a host from the workspace
- **star_server**: Pin or unpin a server for yourself
- **list_server_notes** / **get_server_note** / **create_server_note** / **update_server_note** / **delete_server_note**: Server documentation notes
- **restart_agent** / **shutdown_agent** / **upgrade_agent** / **update_information**: Alpacon agent lifecycle
- **upgrade_system** / **reboot_system** / **shutdown_system**: Host-level actions
- **list_registration_tokens** / **create_registration_token** / **delete_registration_token** / **get_registration_guide**: Register new hosts with Alpamon

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

#### WebFTP (file management)
- **webftp_session_create**: Create file transfer session
- **webftp_upload_file**: Upload files using S3 presigned URLs
- **webftp_upload_content**: Upload base64-encoded content without a local file
- **webftp_download_file**: Download files/folders (folders as .zip)
- **webftp_bulk_upload** / **webftp_bulk_download**: Multi-file transfers in one operation
- **webftp_check_status**: Check the status of an in-flight transfer
- **webftp_uploads_list** / **webftp_downloads_list**: Transfer history
- **webftp_sessions_list**: Active FTP sessions

### 🗂️ Work sessions
- **work_session_create**: Open an auditable, approval-gated session for infrastructure work
- **work_session_get** / **work_session_list**: Inspect sessions and their status
- **work_session_update** / **work_session_extend**: Adjust scope, servers, or expiry
- **work_session_timeline**: Chronological record of everything done in the session
- **work_session_close** / **work_session_analyze**: Close a session and run AI security analysis

OAuth/browser callers must scope command execution and file transfers under an active Work Session; static API tokens bypass the gate.

### 🔔 Alert management
- **list_alerts**: List alerts with optional filtering
- **get_alert**: Get alert details
- **mute_alert**: Mute an alert temporarily
- **create_alert_rule**: Create monitoring thresholds
- **update_alert_rule**: Update alert rule configuration
- **delete_alert_rule**: Delete an alert rule

### 🛡️ Security ACLs
- **list_command_acls** / **create_command_acl** / **update_command_acl** / **delete_command_acl**: Which commands a token may run
- **list_server_acls** / **create_server_acl** / **update_server_acl** / **delete_server_acl** / **bulk_server_acl**: Which servers a token may reach
- **list_file_acls** / **create_file_acl** / **update_file_acl** / **delete_file_acl**: Which paths a token may transfer

### ✅ Approvals & sudo
- **list_approval_requests** / **get_approval_request**: Pending and historical approval requests
- **explain_approval_decision**: Why an agent cannot approve, and who can
- **list_sudo_policies** / **create_sudo_policy**: Elevated-privilege policies

Approving or rejecting a request is deliberately human-only and happens out of band (web console or Slack).

### 📦 Package management
- **list_system_package_entries** / **install_system_package** / **remove_system_package**: OS packages
- **list_python_packages** / **install_python_package** / **remove_python_package**: Python packages

### 📜 Certificates
- **list_certificate_authorities** / **create_certificate_authority** / **get_certificate_authority** / **update_certificate_authority** / **delete_certificate_authority**: CAs
- **list_sign_requests** / **create_sign_request** / **get_sign_request** / **approve_sign_request** / **deny_sign_request** / **retry_sign_request** / **delete_sign_request**: Signing requests
- **list_certificates** / **get_certificate** / **revoke_certificate**: Issued certificates
- **list_revoke_requests** / **get_revoke_request** / **approve_revoke_request** / **deny_revoke_request** / **retry_revoke_request** / **cancel_revoke_request**: Revocation requests

### 🔗 Webhooks & subscriptions
- **list_webhooks** / **get_webhook** / **create_webhook** / **update_webhook** / **delete_webhook**: Webhook endpoints
- **list_event_subscriptions** / **create_event_subscription** / **delete_event_subscription**: Which events get delivered

### 🎫 API tokens
- **list_api_tokens** / **get_api_token** / **create_api_token** / **update_api_token** / **delete_api_token** / **duplicate_api_token**: Token lifecycle
- **list_api_token_scopes** / **list_api_token_presets**: Available scopes and presets

These tools need a JWT/OAuth session (hosted server), a browser session, or a login-source token—an API token from `token.json` gets a 403 from the server. Scopes and presets are readable either way.

### 📋 Events & logging
- **list_events**: Browse server events and logs
- **get_event**: Get event details by ID
- **search_events**: Search and filter events

### 📝 Audit logs
- **list_activity_logs**: Audit user and system actions
- **get_activity_log**: Get activity log details
- **list_server_logs**: Server command execution logs
- **list_webftp_logs**: WebFTP file transfer logs
- **list_session_analyses** / **get_session_analysis_detail**: AI security analysis with MITRE ATT&CK mapping

### 🔐 Identity and access management (IAM)

**User management**:
- **list_iam_users**: List workspace IAM users with pagination
- **get_iam_user**: Get detailed user information
- **create_iam_user**: Create a new IAM user
- **update_iam_user**: Update a user's email, name, or active status
- **delete_iam_user**: Remove users from workspace
- **invite_workspace_user**: Send an email invitation to join the workspace

**Group and membership management**:
- **list_iam_groups** / **get_iam_group** / **create_iam_group** / **update_iam_group** / **delete_iam_group**: Groups
- **list_iam_memberships** / **add_iam_member** / **remove_iam_member**: Who belongs to which group, and in what role

**Applications** (machine service accounts):
- **list_iam_applications** / **get_iam_application** / **create_iam_application** / **update_iam_application** / **delete_iam_application**: Application lifecycle
- **assign_application_system_users** / **unassign_application_system_users**: Bind OS-level accounts to an application

### ⚙️ Workspace
- **list_workspaces**: List available workspaces
- **get_current_user**: Get the currently authenticated user
- **get_workspace_access_control**: Get access control settings (read-only)
- **get_workspace_security**: Get authentication/security settings (JWT/SSO auth only, SaaS only)
- **list_workspace_mfa_methods**: List allowed MFA methods (JWT/SSO auth only, SaaS only)
- **get_workspace_preferences**: Get workspace-wide preferences
- **update_workspace_preferences**: Update workspace-wide preferences (partial)
- **health_check**: MCP server health, version, and authentication mode

### 🧩 Resources and prompts

Most read tools are also exposed as read-only `alpacon://` resources—for example `alpacon://servers/{region}/{workspace}`, `alpacon://metrics/{region}/{workspace}/{server_id}/cpu`, or `alpacon://audit/activity/{region}/{workspace}`—so a client can pull data without a tool call.

Four MCP prompts teach the operating discipline: `work_session_workflow` (open a scoped session), `guarded_execution` (act inside it), `incident_response` (triage first, then remediate), and `security_audit` (pick the right audit lens).

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
- 🔐 **[MFA Re-authentication Flow](docs/mfa-reauth-flow.md)** - How the hosted server re-verifies MFA

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
- **Session recording**: Command execution and WebFTP transfers are recorded for audit
- **Workspace-based access control**: Separate tokens per workspace with RBAC
- **ACL configuration required**: Configure token permissions in Alpacon web interface for command execution
- **Audit logging**: All operations logged with full traceability

### ⚠️ Command execution limitations

**Important**: command execution tools can only run **pre-approved commands** configured in your token's ACL settings:

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