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
export ALPACON_MCP_EU1_ENTERPRISE_TOKEN="your-eu1-enterprise-token"
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
  },
  "eu1": {
    "enterprise": "eu1-enterprise-token-here"
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
export ALPACON_MCP_CONFIG_FILE=".config/token.json"
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

**Configuration file**: `.cursor/mcp_config.json` in your project root

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./path/to/alpacon-mcp",
      "env": {
        "ALPACON_MCP_CONFIG_FILE": ".config/token.json"
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
      "cwd": "./path/to/alpacon-mcp",
      "env": {
        "ALPACON_MCP_CONFIG_FILE": ".config/token.json"
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

# SSE mode
python main_sse.py

# Help
python main.py --help
```

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
- Runs on host 0.0.0.0:8237

```bash
python main_sse.py
```

#### Streamable-HTTP mode (remote deployment)
- HTTP-based transport for hosting a remote MCP server
- Authenticates clients with Auth0 JWT (browser OAuth)—no `token.json` or API token on the client
- `main_http.py` validates `AUTH0_DOMAIN` and `AUTH0_CLIENT_ID` at startup; the OAuth proxy endpoints additionally require `AUTH0_CLIENT_SECRET`, and accept an optional `AUTH0_AUDIENCE` (default `https://alpacon.io/access/`)
- The OAuth `state` parameter is signed and expires after 10 minutes. The signing key is derived from `AUTH0_CLIENT_SECRET` by default; set the optional `ALPACON_MCP_STATE_SECRET` to use an explicit key instead. It must be hex decoding to at least 32 bytes, matching what the derived key always is—generate it with `openssl rand -hex 32` rather than typing a passphrase, because the state travels in URLs and proxy logs and a guessable key is an offline brute-force target. A value that is not hex, or is shorter, is rejected when the OAuth endpoints first sign or verify a state
- The signed state is also bound to the browser that started the flow: `/oauth/authorize` sets a `__Host-alpacon_oauth_nonce` cookie and carries only its hash in the state, and `/oauth/callback` rejects a state whose hash does not match the cookie. A signature alone says the state came from this server, not that it came back to the browser that started the flow, so a callback now only completes where it began. Because the `__Host-` prefix requires the `Secure` attribute, the server's public URL (`ALPACON_MCP_RESOURCE_URL`) must be `https`, and any proxy in front of it must pass `Set-Cookie` and `Cookie` through; otherwise every callback fails with `invalid_request`
- A client's `redirect_uri` must be a loopback URL or one of the callback endpoints the server knows: the built-in list covers Claude, ChatGPT, Cursor, VS Code, Antigravity, and Copilot Studio. `ALLOWED_REDIRECT_URIS` replaces that list, and `ALPACON_MCP_REDIRECT_URI_REPORT_ONLY=true` logs an unlisted endpoint instead of rejecting it
- Report-only accepts *any path* on the built-in hosts, which is wider than the enforcing list: turn it off once the missing endpoint is listed in `ALLOWED_REDIRECT_URIS`, rather than leaving it on
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

# Logging configuration
export ALPACON_MCP_LOG_LEVEL=DEBUG   # For development
export ALPACON_MCP_LOG_LEVEL=INFO    # For standard use (default)
export ALPACON_MCP_LOG_LEVEL=ERROR   # For production

# Debug mode
export DEBUG=true        # Enable debug logging

# WebFTP configuration
export ALPACON_MCP_WEBFTP_DOWNLOAD_TIMEOUT=60   # Seconds to poll for S3 staging in remote-mode downloads (default: 60). Raise for large folder ZIPs.

# OAuth callback allowlist (remote mode only)
export ALLOWED_REDIRECT_URIS="https://app.example.com/oauth/callback"   # Comma-separated full URIs; replaces the built-in list
export ALPACON_MCP_REDIRECT_URI_REPORT_ONLY=true                       # Log an unlisted endpoint instead of rejecting it; accepts any path on the fallback hosts
export ALLOWED_REDIRECT_DOMAINS="app.example.com"                      # Hosts report-only mode may fall back to; admits nothing on its own
```

#### Configuration examples

```bash
# Development setup
export ALPACON_MCP_CONFIG_FILE=".config/local-tokens.json"
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

#### Europe (eu1)
```json
{
  "eu1": {
    "frankfurt": "eu1-fra-token",
    "london": "eu1-lon-token",
    "paris": "eu1-par-token"
  }
}
```

### Docker configuration

#### Dockerfile configuration
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install uv
RUN uv venv && uv pip install mcp httpx "PyJWT[crypto]"

# Use config volume for tokens
VOLUME ["/app/config"]

CMD ["python", "main.py"]
```

#### Docker Compose
```yaml
version: '3.8'
services:
  alpacon-mcp:
    build: .
    volumes:
      - ./config:/app/config:ro
    environment:
      - ALPACON_MCP_CONFIG_FILE=/app/config/tokens.json
    ports:
      - "8237:8237"  # For SSE mode
```

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

## 🔧 Performance configuration

### Connection pooling

The server uses connection pooling for better performance:

```python
# HTTP client configuration (internal)
HTTP_TIMEOUT = 30  # seconds
MAX_CONNECTIONS = 100
MAX_KEEPALIVE_CONNECTIONS = 20
```

### Request timeout configuration

```bash
# Environment variables for timeout control
export ALPACON_REQUEST_TIMEOUT=30
export ALPACON_CONNECT_TIMEOUT=10
export ALPACON_READ_TIMEOUT=30
```

### Concurrent request limits

```python
# Internal configuration
MAX_CONCURRENT_REQUESTS = 50
REQUEST_QUEUE_SIZE = 100
```

---

## 📊 Logging configuration

### Log levels

```bash
# Debug logging (local)
export ALPACON_MCP_LOG_LEVEL=DEBUG

# Info logging (standard)
export ALPACON_MCP_LOG_LEVEL=INFO

# Error logging only
export ALPACON_MCP_LOG_LEVEL=ERROR
```

### Log format

```bash
# Structured JSON logging
export LOG_FORMAT=json

# Human-readable logging
export LOG_FORMAT=text
```

### Log file configuration

```bash
# Enable file logging
export LOG_FILE=/var/log/alpacon-mcp/server.log

# Log rotation
export LOG_MAX_SIZE=100MB
export LOG_BACKUP_COUNT=5
```

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

#### Token encryption (optional)
```python
# Enable token encryption in storage
export ALPACON_ENCRYPT_TOKENS=true
export ALPACON_ENCRYPTION_KEY="your-encryption-key"
```

### Network security

#### HTTPS configuration
```bash
# Force HTTPS for all API calls
export ALPACON_FORCE_HTTPS=true

# Certificate verification
export ALPACON_VERIFY_SSL=true
```

#### IP restrictions
```bash
# Restrict API access to specific IPs
export ALPACON_ALLOWED_IPS="10.0.0.0/8,192.168.0.0/16"
```

### Access control

#### Workspace restrictions
```json
{
  "access_control": {
    "ap1": ["company-main", "company-backup"],
    "us1": ["backup-site"],
    "eu1": ["enterprise"]
  }
}
```

---

## 🚦 Health checks and monitoring

### Health check endpoints

```bash
# Check server health (SSE mode)
curl http://localhost:8237/health

# Check authentication status
curl http://localhost:8237/auth/status
```

### Monitoring configuration

```bash
# Enable metrics collection
export ALPACON_METRICS_ENABLED=true

# Metrics export interval
export ALPACON_METRICS_INTERVAL=60

# Prometheus metrics endpoint
export ALPACON_PROMETHEUS_PORT=9090
```

### Status monitoring

```python
# Internal health checks
HEALTH_CHECK_INTERVAL = 300  # 5 minutes
AUTH_TOKEN_CHECK_INTERVAL = 3600  # 1 hour
CONNECTION_TEST_INTERVAL = 600  # 10 minutes
```

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

### Validate token configuration

```bash
# Test all tokens
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
tokens = tm.get_all_tokens()
for region, workspaces in tokens.items():
    for workspace, token in workspaces.items():
        status = '✓' if token else '✗'
        print(f'{region}/{workspace}: {status}')
"
```

### Test MCP client connection

```bash
# Test MCP protocol
echo '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}' | python main.py
```

### Validate API access

```python
# Test API connectivity
import asyncio
from utils.http_client import http_client
from utils.token_manager import TokenManager

async def test_connection():
    tm = TokenManager()
    token = tm.get_token('ap1', 'company-main')

    result = await http_client.get(
        region='ap1',
        workspace='company-main',
        endpoint='/api/servers/',
        token=token
    )
    print('✓ API connection successful' if result else '✗ API connection failed')

asyncio.run(test_connection())
```

---

For troubleshooting configuration issues, see the [Troubleshooting Guide](troubleshooting.md).