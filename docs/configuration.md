# Configuration guide

Comprehensive configuration guide for the Alpacon MCP Server.

## 🔐 Authentication configuration

### Method 1: Environment variables (recommended for uvx)

The Alpacon MCP Server supports environment variables for token management, perfect for uvx usage:

#### Environment variable format

```bash
# Format: ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="your-ap1-production-token"
export ALPACON_MCP_AP1_STAGING_TOKEN="your-ap1-staging-token"
export ALPACON_MCP_US1_BACKUP_TOKEN="your-us1-backup-token"
```

#### Using with uvx

Environment variables are best for CLI usage and testing:

```bash
# Set environment variables
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="your-token-here"

# Run with uvx
uvx alpacon-mcp

# Or inline for one-time use
ALPACON_MCP_AP1_PRODUCTION_TOKEN="your-token" uvx alpacon-mcp
```

### Method 2: Configuration file

#### Token file structure

```json
{
  "ap1": {
    "company-main": "ap1-company-main-token-here",
    "company-backup": "ap1-company-backup-token-here"
  },
  "us1": {
    "org-primary": "us1-org-primary-token-here",
    "org-secondary": "us1-org-secondary-token-here"
  }
}
```

#### Configuration priority

The server uses this priority system to find tokens:

1. **Environment variables**: `ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN`
2. **Config file**: Path from `ALPACON_MCP_CONFIG_FILE` environment variable
3. **Global config**: `~/.alpacon-mcp/token.json` (if exists)
4. **Local config**: `config/token.json` (fallback)

#### Examples

```bash
# Use default location (config/token.json)
uvx alpacon-mcp

# Use custom config file with uvx
ALPACON_MCP_CONFIG_FILE="/path/to/tokens.json" uvx alpacon-mcp

# Use environment variable for config path
export ALPACON_MCP_CONFIG_FILE="$HOME/.alpacon-mcp/token.json"
uvx alpacon-mcp
```

---

## 🖥️ MCP client configuration

### Claude Desktop

**Configuration file locations:**
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

**Using uvx (recommended):**
```json
{
  "mcpServers": {
    "alpacon": {
      "command": "uvx",
      "args": ["alpacon-mcp"],
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "/Users/username/.config/alpacon/tokens.json"
      }
    }
  }
}
```

**Development setup:**
```json
{
  "mcpServers": {
    "alpacon-mcp-dev": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "./config/token.json"
      },
      "cwd": "/absolute/path/to/alpacon-mcp"
    }
  }
}
```

### Cursor IDE

**Configuration file**: `.cursor/mcp.json` in your project root

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/absolute/path/to/alpacon-mcp",
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "/absolute/path/to/config/token.json"
      }
    }
  }
}
```

### VS Code

**Requires**: MCP extension for VS Code

**Configuration**: Add to VS Code `settings.json`:
```json
{
  "mcp.servers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/absolute/path/to/alpacon-mcp",
      "env": {
        "ALPACON_MCP_CONFIG_FILE": "/absolute/path/to/config/token.json"
      }
    }
  }
}
```

### Continue (VS Code extension)

**Configuration**: Add to Continue configuration:
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

---

## ⚙️ Server configuration options

### Command line arguments

```bash
# Basic usage
python main.py

# Custom config file
python main.py --config-file /path/to/config.json

# Register only some toolsets (local mode)
python main.py --toolsets servers,commands,webftp

# SSE mode
python main_sse.py

# Help
python main.py --help
```

The `alpacon-mcp` CLI takes the same flags plus the `setup`, `test`, `list`, and `add` subcommands. `--toolsets` is also accepted by `main_sse.py`; the `ALPACON_MCP_TOOLSETS` environment variable is the equivalent, and the flag wins when both are set. Available toolsets: `servers`, `commands`, `webftp`, `metrics`, `alerts`, `events`, `system-info`, `iam`, `security`, `audit`, `approvals`, `webhooks`, `packages`, `certs`, `tokens`. Workspace, health, Work Session tools, and prompts are always registered. Remote mode ignores the setting. A few resources cross module boundaries—`alpacon://servers/.../overview` is backed by `system_info_tools`, so `--toolsets servers` alone silently drops it; add `system-info` to keep it.

### Transport modes

#### STDIO mode (default)
- Standard MCP protocol transport
- Bidirectional communication via stdin/stdout
- Recommended for most MCP clients

```bash
python main.py
```

#### SSE mode (Server-Sent Events)
- HTTP-based transport with Server-Sent Events
- Useful for web-based integrations
- Binds `127.0.0.1:8237` by default; override with `ALPACON_MCP_HOST` and `ALPACON_MCP_PORT`

```bash
python main_sse.py
```

#### Streamable-HTTP mode (remote deployment)
- HTTP-based transport for hosting a remote MCP server
- Authenticates clients with Auth0 JWT (browser OAuth)—no `token.json` or API token on the client
- `main_http.py` validates `AUTH0_DOMAIN` and `AUTH0_CLIENT_ID` at startup; the OAuth proxy endpoints additionally require `AUTH0_CLIENT_SECRET`, and accept an optional `AUTH0_AUDIENCE` (default `https://alpacon.io/access/`)
- The OAuth `state` parameter is signed and expires after 10 minutes. The signing key is derived from `AUTH0_CLIENT_SECRET` by default; set the optional `ALPACON_MCP_STATE_SECRET` to use an explicit key instead. It must be hex decoding to at least 32 bytes, matching what the derived key always is—generate it with `openssl rand -hex 32` rather than typing a passphrase, because the state travels in URLs and proxy logs and a guessable key is an offline brute-force target. A value that is not hex, or is shorter, fails the server at startup, when the OAuth routes are registered
- The signed state is also bound to the browser that started the flow: `/oauth/authorize` sets a `__Host-alpacon_oauth_nonce` cookie and carries only its hash in the state, and `/oauth/callback` rejects a state whose hash does not match the cookie. A signature alone says the state came from this server, not that it came back to the browser that started the flow, so a callback now only completes where it began. Because the `__Host-` prefix requires the `Secure` attribute, the server's public URL (`ALPACON_MCP_RESOURCE_URL`) must be `https`, and any proxy in front of it must pass `Set-Cookie` and `Cookie` through; otherwise every callback fails with `invalid_request`
- A client's `redirect_uri` must be a loopback URL or one of the callback endpoints the server knows: the built-in list covers Claude, ChatGPT, Cursor, VS Code, Antigravity, and Copilot Studio. `ALLOWED_REDIRECT_URIS` replaces that list, and `ALPACON_MCP_REDIRECT_URI_REPORT_ONLY=true` logs an unlisted endpoint instead of rejecting it
- Report-only accepts *any path* on the built-in hosts, which is wider than the enforcing list: turn it off once the missing endpoint is listed in `ALLOWED_REDIRECT_URIS`, rather than leaving it on
- `/oauth/authorize` requires S256 PKCE: a request with no `code_challenge`, or one that sends a `code_challenge` under any `code_challenge_method` other than `S256`, is rejected with `invalid_request`. The challenge must also have the shape RFC 7636 §4.1 fixes—43 to 128 characters from `[A-Za-z0-9-._~]`—so a malformed one is refused here rather than by Auth0 several redirects later. One callback is exempt—`https://global.consent.azure-apim.net/redirect`, the Power Platform gateway a Copilot Studio connector uses, which has no PKCE support to turn on. That destination may omit the challenge, but it may not downgrade to `plain`, and the exemption is the exact URI: another path on the same host is not exempt, and report-only mode does not widen it
- The requirement is on what the client sends, not on every request this server makes upstream: an MFA re-authentication starts with a leg to the MFA audience that carries no `code_challenge`. The client's challenge is held in the signed `state` and replayed on the second leg, which is the one whose code the client exchanges. The first leg's code never reaches the client—it is exchanged server-to-server with `AUTH0_CLIENT_SECRET` and discarded—so client authentication, not PKCE, is what protects it
- `/oauth/register` applies the same check to the `redirect_uris` a client registers, rejecting an unlisted one with `invalid_redirect_uri` rather than accepting it and failing later at `/oauth/authorize`. The registration response echoes the URIs only after they clear it
- A browser-based client reaches `/oauth/register` and `/oauth/token` with `fetch`, so both answer the CORS preflight and send `Access-Control-Allow-Origin: *`, as the discovery document already did. `Access-Control-Allow-Credentials` is deliberately absent: neither endpoint reads a cookie, and granting it alongside a wildcard origin would let any page spend the user's session. `/oauth/authorize` and `/oauth/callback` are top-level navigations, which CORS does not govern, and stay closed
- `ALLOWED_REDIRECT_DOMAINS` no longer admits a host by itself—it now only bounds which hosts report-only mode will let through. A deployment that relied on it alone must list the full callback URIs in `ALLOWED_REDIRECT_URIS`, or turn report-only on; route registration logs a warning when the domain list is set with neither
- Alpacon operates a managed instance at `https://mcp.alpacon.io/mcp`

```bash
python main_http.py
```

To connect a client to a remote streamable-http server, point it at the server URL instead of a local command. See the [hosted remote MCP guide in the README](../README.md#-remote-mcp-server-hosted-no-install) for per-client examples.

### Environment configuration

#### Environment variables

```bash
# Token configuration
export ALPACON_MCP_CONFIG_FILE="/path/to/custom-tokens.json"  # Custom token file (optional)
export ALPACON_MCP_AP1_PRODUCTION_TOKEN="alpat-..."           # Per-workspace token
export ALPACON_MCP_AP1_PRODUCTION_URL="https://production.ap1.alpacon.io"  # Pin the API host

# Tool registration (local mode only)
export ALPACON_MCP_TOOLSETS="servers,commands,webftp"

# Default Work Session for tools called without work_session_id
export ALPACON_WORK_SESSION="<work-session-uuid>"

# Transport binding (SSE and streamable-http)
export ALPACON_MCP_HOST=127.0.0.1
export ALPACON_MCP_PORT=8237

# Logging configuration
export ALPACON_MCP_LOG_LEVEL=DEBUG   # For development
export ALPACON_MCP_LOG_LEVEL=INFO    # For standard use (default)
export ALPACON_MCP_LOG_LEVEL=ERROR   # For production

# WebFTP configuration
export ALPACON_MCP_WEBFTP_DOWNLOAD_TIMEOUT=60   # Seconds to poll for S3 staging in remote-mode downloads (default: 60). Raise for large folder ZIPs.

# OAuth callback allowlist (remote mode only)
export ALLOWED_REDIRECT_URIS="https://app.example.com/oauth/callback"   # Comma-separated full URIs; replaces the built-in list
export ALPACON_MCP_REDIRECT_URI_REPORT_ONLY=true                       # Log an unlisted endpoint instead of rejecting it; accepts any path on the fallback hosts
export ALLOWED_REDIRECT_DOMAINS="app.example.com"                      # Hosts report-only mode may fall back to; admits nothing on its own

# Auth0 (remote mode only; main_http.py refuses to start without the first two)
export AUTH0_DOMAIN="your-tenant.auth0.com"
export AUTH0_CLIENT_ID="..."
export AUTH0_CLIENT_SECRET="..."                # Required by the OAuth proxy endpoints
export AUTH0_AUDIENCE="https://alpacon.io/access/"   # Optional; this is the default
export AUTH0_MFA_AUDIENCE="https://your-tenant.auth0.com/mfa/"  # Optional; stage 1 of the MFA re-auth flow
export AUTH0_NAMESPACE="https://alpacon.io/"    # Optional; custom claim namespace (this is the default)
export ALPACON_MCP_RESOURCE_URL="https://mcp.example.com"  # Public https URL of this server
export ALPACON_MCP_STATE_SECRET="$(openssl rand -hex 32)"  # Optional; derived from the client secret otherwise
export ALPACON_ACCOUNT_URL="https://account.example.com"   # Optional; unset skips the security-settings prefetch
```

#### Configuration examples

```bash
# Development setup
export ALPACON_MCP_CONFIG_FILE="./config/token.json"
export ALPACON_MCP_LOG_LEVEL=DEBUG

# Production setup
export ALPACON_MCP_CONFIG_FILE="/etc/alpacon-mcp/production-tokens.json"
export ALPACON_MCP_LOG_LEVEL=ERROR

# User-specific setup
export ALPACON_MCP_CONFIG_FILE="~/.alpacon/my-tokens.json"
export ALPACON_MCP_LOG_LEVEL=INFO
```

---

## 🏗️ Advanced configuration

### Multiple workspace setup

**Token configuration:**
```json
{
  "ap1": {
    "company-main": "token-for-main-workspace",
    "company-backup": "token-for-backup-workspace"
  },
  "us1": {
    "backup-site": "token-for-us-backup",
    "disaster-recovery": "token-for-dr-site"
  }
}
```

**Usage in AI prompts:**
```
"List servers in the company-backup workspace in ap1 region"
"Get metrics for servers in the company-main workspace"
```

### Region-specific configuration

#### Asia Pacific (ap1)
```json
{
  "ap1": {
    "tokyo-main": "ap1-tokyo-token",
    "singapore-branch": "ap1-sg-token",
    "sydney-backup": "ap1-syd-token"
  }
}
```

#### United States (us1)
```json
{
  "us1": {
    "east-coast": "us1-east-token",
    "west-coast": "us1-west-token",
    "central": "us1-central-token"
  }
}
```

### Docker configuration

Building the image and the `docker-compose.yml` to run it live in the [installation guide](installation.md#-docker-installation). What follows is only what a container needs configured.

The shipped image runs `main_http.py`—the remote (streamable-http) transport with JWT auth—so it needs the `AUTH0_*` variables above and no token file. Override the command to `python main.py` to run the stdio server instead; that path authenticates from `token.json`, so mount the config directory and point `ALPACON_MCP_CONFIG_FILE` at the mounted file.

#### MCP client Docker configuration
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/config:/app/config:ro",
        "alpacon-mcp:latest"
      ]
    }
  }
}
```

---

## 📊 Logging configuration

```bash
# Debug logging (local)
export ALPACON_MCP_LOG_LEVEL=DEBUG

# Info logging (standard, default)
export ALPACON_MCP_LOG_LEVEL=INFO

# Error logging only
export ALPACON_MCP_LOG_LEVEL=ERROR
```

`ALPACON_MCP_LOG_LEVEL` is the only logging knob the server reads. See [LOGGING.md](../LOGGING.md) for where the log output goes and why stdio mode never writes to stdout.

---

## 🔒 Security configuration

### Token security

#### File permissions
```bash
# Secure token files
chmod 600 config/token.json
chmod 700 config/
```

#### Environment-based tokens
```bash
# Alternative to file-based tokens (uses ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN format)
export ALPACON_MCP_AP1_COMPANY_MAIN_TOKEN="your-token-here"
export ALPACON_MCP_US1_BACKUP_TOKEN="your-backup-token"
```

### Network security

All API calls go to `https://{workspace}.{region}.alpacon.io` (or the URL you pinned per workspace), and TLS verification is httpx's default. There is no setting that turns either off.

### Access control

Access is decided by the token, not by local configuration: a workspace is reachable exactly when the config holds a token for it, and what that token may do comes from its ACL and scopes in the Alpacon web console.

---

## 🚦 Health check

```bash
# HTTP transports (SSE, streamable-http) expose a health route
curl http://127.0.0.1:8237/health
```

The same information is available in any transport through the `health_check` MCP tool: version, uptime, authentication mode, and connection pool state.

---

## 🔄 Backup and recovery

### Configuration backup

```bash
# Backup token configuration
cp config/token.json config/token.json.backup

# Backup with timestamp
cp config/token.json "config/token.json.backup.$(date +%Y%m%d_%H%M%S)"
```

### Disaster recovery

```bash
# Recovery script
#!/bin/bash
# Restore from backup
cp config/token.json.backup config/token.json

# Verify configuration
python -c "from utils.token_manager import TokenManager; tm = TokenManager(); print('Config OK')"

# Restart service
python main.py
```

---

## 📋 Configuration validation

```bash
# List the workspaces the current configuration knows about
uvx alpacon-mcp list

# Ask for a region and workspace, then call the API with that token
uvx alpacon-mcp test
```

Both read the same configuration the server does, so together they answer "is this file in the right place and does the token work". `test` is interactive—it prompts for the region and workspace and checks that one. From a checkout, `python main.py list` and `python main.py test` do the same thing.

To check the API by hand, call the workspace host directly:

```bash
curl -H "Authorization: Bearer alpat-..." \
     "https://your-workspace.ap1.alpacon.io/api/servers/servers/"
```

---

For troubleshooting configuration issues, see the [Troubleshooting Guide](troubleshooting.md).