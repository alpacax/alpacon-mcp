# Configuration Guide

Comprehensive configuration guide for the Alpacon MCP Server.

## 🔐 Authentication Configuration

### Token Management

The Alpacon MCP Server uses a flexible token management system that supports multiple regions and workspaces.

#### Token File Structure

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

#### Configuration File Location

The server uses a simple priority system to find the token configuration:

1. **Environment Variable**: If `ALPACON_CONFIG_FILE` is set, use that path
2. **Default Location**: Otherwise, use `config/token.json`

#### Examples

```bash
# Use default location (config/token.json)
python main.py

# Use custom config file
export ALPACON_CONFIG_FILE="/path/to/custom-tokens.json"
python main.py

# Use local config for development
export ALPACON_CONFIG_FILE=".config/token.json"
python main.py
```

---

## 🖥️ MCP Client Configuration

### Claude Desktop

**Configuration File Locations:**
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

**Basic Configuration:**
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

**Custom Config File:**
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "env": {
        "ALPACON_CONFIG_FILE": "/path/to/custom-config.json"
      },
      "cwd": "/absolute/path/to/alpacon-mcp"
    }
  }
}
```

### Cursor IDE

**Configuration File**: `.cursor/mcp_config.json` in your project root

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./path/to/alpacon-mcp",
      "env": {
        "ALPACON_CONFIG_FILE": ".config/token.json"
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
        "ALPACON_CONFIG_FILE": ".config/token.json"
      }
    }
  }
}
```

### Continue (VS Code Extension)

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

## ⚙️ Server Configuration Options

### Command Line Arguments

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

### Transport Modes

#### STDIO Mode (Default)
- Standard MCP protocol transport
- Bidirectional communication via stdin/stdout
- Recommended for most MCP clients

```bash
python main.py
```

#### SSE Mode (Server-Sent Events)
- HTTP-based transport with Server-Sent Events
- Useful for web-based integrations
- Runs on host 0.0.0.0:8237

```bash
python main_sse.py
```

### Environment Configuration

#### Environment Variables

```bash
# Token configuration
export ALPACON_CONFIG_FILE="/path/to/custom-tokens.json"  # Custom token file (optional)

# Logging configuration
export LOG_LEVEL=DEBUG   # For development
export LOG_LEVEL=INFO    # For standard use (default)
export LOG_LEVEL=ERROR   # For production

# Debug mode
export DEBUG=true        # Enable debug logging
```

#### Configuration Examples

```bash
# Development setup
export ALPACON_CONFIG_FILE=".config/local-tokens.json"
export LOG_LEVEL=DEBUG

# Production setup
export ALPACON_CONFIG_FILE="/etc/alpacon-mcp/production-tokens.json"
export LOG_LEVEL=ERROR

# User-specific setup
export ALPACON_CONFIG_FILE="~/.alpacon/my-tokens.json"
export LOG_LEVEL=INFO
```

---

## 🏗️ Advanced Configuration

### Multiple Workspace Setup

**Token Configuration:**
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

**Usage in AI Prompts:**
```
"List servers in the company-backup workspace in ap1 region"
"Get metrics for servers in the company-main workspace"
```

### Region-Specific Configuration

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

### Docker Configuration

#### Dockerfile Configuration
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install uv
RUN uv venv && uv pip install mcp[cli] httpx

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
      - ALPACON_CONFIG_FILE=/app/config/tokens.json
    ports:
      - "8237:8237"  # For SSE mode
```

#### MCP Client Docker Configuration
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

## 🔧 Performance Configuration

### Connection Pooling

The server uses connection pooling for better performance:

```python
# HTTP client configuration (internal)
HTTP_TIMEOUT = 30  # seconds
MAX_CONNECTIONS = 100
MAX_KEEPALIVE_CONNECTIONS = 20
```

### Request Timeout Configuration

```bash
# Environment variables for timeout control
export ALPACON_REQUEST_TIMEOUT=30
export ALPACON_CONNECT_TIMEOUT=10
export ALPACON_READ_TIMEOUT=30
```

### Concurrent Request Limits

```python
# Internal configuration
MAX_CONCURRENT_REQUESTS = 50
REQUEST_QUEUE_SIZE = 100
```

---

## 📊 Logging Configuration

### Log Levels

```bash
# Debug logging (local)
export LOG_LEVEL=DEBUG

# Info logging (standard)
export LOG_LEVEL=INFO

# Error logging only
export LOG_LEVEL=ERROR
```

### Log Format

```bash
# Structured JSON logging
export LOG_FORMAT=json

# Human-readable logging
export LOG_FORMAT=text
```

### Log File Configuration

```bash
# Enable file logging
export LOG_FILE=/var/log/alpacon-mcp/server.log

# Log rotation
export LOG_MAX_SIZE=100MB
export LOG_BACKUP_COUNT=5
```

---

## 🔒 Security Configuration

### Token Security

#### File Permissions
```bash
# Secure token files
chmod 600 config/token.json
chmod 700 config/
```

#### Environment-based Tokens
```bash
# Alternative to file-based tokens
export ALPACON_AP1_COMPANY_MAIN_TOKEN="your-token-here"
export ALPACON_US1_BACKUP_TOKEN="your-backup-token"
```

#### Token Encryption (Optional)
```python
# Enable token encryption in storage
export ALPACON_ENCRYPT_TOKENS=true
export ALPACON_ENCRYPTION_KEY="your-encryption-key"
```

### Network Security

#### HTTPS Configuration
```bash
# Force HTTPS for all API calls
export ALPACON_FORCE_HTTPS=true

# Certificate verification
export ALPACON_VERIFY_SSL=true
```

#### IP Restrictions
```bash
# Restrict API access to specific IPs
export ALPACON_ALLOWED_IPS="10.0.0.0/8,192.168.0.0/16"
```

### Access Control

#### Workspace Restrictions
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

## 🚦 Health Checks and Monitoring

### Health Check Endpoints

```bash
# Check server health (SSE mode)
curl http://localhost:8237/health

# Check authentication status
curl http://localhost:8237/auth/status
```

### Monitoring Configuration

```bash
# Enable metrics collection
export ALPACON_METRICS_ENABLED=true

# Metrics export interval
export ALPACON_METRICS_INTERVAL=60

# Prometheus metrics endpoint
export ALPACON_PROMETHEUS_PORT=9090
```

### Status Monitoring

```python
# Internal health checks
HEALTH_CHECK_INTERVAL = 300  # 5 minutes
AUTH_TOKEN_CHECK_INTERVAL = 3600  # 1 hour
CONNECTION_TEST_INTERVAL = 600  # 10 minutes
```

---

## 🔄 Backup and Recovery

### Configuration Backup

```bash
# Backup token configuration
cp config/token.json config/token.json.backup

# Backup with timestamp
cp config/token.json "config/token.json.backup.$(date +%Y%m%d_%H%M%S)"
```

### Disaster Recovery

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

## 📋 Configuration Validation

### Validate Token Configuration

```bash
# Test all tokens
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
tokens = tm.get_all_tokens()
for (region, workspace), token in tokens.items():
    print(f'{region}/{workspace}: {'✓' if token else '✗'}')
"
```

### Test MCP Client Connection

```bash
# Test MCP protocol
echo '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}' | python main.py
```

### Validate API Access

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