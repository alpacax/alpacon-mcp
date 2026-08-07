# Troubleshooting guide

Common issues and solutions for the Alpacon MCP Server.

## 🔍 Diagnostic tools

### Quick health check

```bash
# Check one workspace's token against the API (prompts for region and workspace)
python main.py test

# List the workspaces the configuration knows about
python main.py list

# Verify the server imports and tools register
python -c "from server import mcp; print('MCP Server initialized successfully')"
```

### Debug mode

```bash
# Enable debug logging (stderr + logs/alpacon-mcp.log)
export ALPACON_MCP_LOG_LEVEL=DEBUG
python main.py
```

### Connection test

```bash
# Test API connectivity by hand (host is per workspace)
curl -H "Authorization: Bearer alpat-..." \
     "https://company-main.ap1.alpacon.io/api/servers/servers/"
```

---

## 🚨 Common issues

### 1. Server won't start

#### Symptoms
```
ModuleNotFoundError: No module named 'mcp'
ImportError: No module named 'httpx'
```

#### Solutions
```bash
# Install dependencies from pyproject.toml
uv sync

# Or using pip, from a checkout
pip install -e .

# Verify virtual environment is activated
source .venv/bin/activate

# Check Python path
which python
python --version
```

#### Check installation
```bash
# List installed packages
uv pip list

# Verify MCP installation
python -c "import mcp; print(mcp.__version__)"
```

---

### 2. Authentication failures

#### Symptoms
```json
{
  "status": "error",
  "message": "No token found for workspace.region"
}
```

#### Solutions

**Check token file:**
```bash
# Verify a token file exists in one of the discovered locations
ls -la ~/.alpacon-mcp/token.json
ls -la config/token.json

# Check file permissions
chmod 600 config/token.json

# Validate JSON format
python -c "import json; json.load(open('config/token.json'))"
```

**Discovery order:** `ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN` env var → `ALPACON_MCP_CONFIG_FILE` → `~/.alpacon-mcp/token.json` → `./config/token.json`.

**Verify token format:**
```json
{
  "ap1": {
    "your-workspace": "your-actual-token-here"
  }
}
```

**Test token manually:**
```bash
curl -H "Authorization: Bearer your-token-here" \
     "https://your-workspace.ap1.alpacon.io/api/servers/servers/"
```

**Debug token loading:**
```python
from utils.token_manager import TokenManager

tm = TokenManager()
print('Config file:', tm.token_file)
print('Workspaces:', {r: list(ws) for r, ws in tm.get_all_tokens().items()})
print('Token found:', bool(tm.get_token('ap1', 'your-workspace')))
```

Print the workspace names and a boolean, never the token values—this output usually ends up pasted into an issue.

---

### 3. MCP client connection issues

#### Symptoms
- Client shows "MCP server not responding"
- Tools don't appear in client
- Connection timeouts

#### Solutions

**Check configuration paths:**
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/ABSOLUTE/path/to/alpacon-mcp"  // Must be absolute
    }
  }
}
```

**Test manual execution:**
```bash
# Navigate to project directory
cd /path/to/alpacon-mcp

# Test command from MCP config
uv run python main.py

# Alternative test
/path/to/alpacon-mcp/.venv/bin/python main.py
```

**Common path issues:**
```bash
# ❌ Wrong - relative path
"cwd": "./alpacon-mcp"

# ✅ Correct - absolute path
"cwd": "/Users/username/projects/alpacon-mcp"

# ❌ Wrong - missing uv command
"command": "python"

# ✅ Correct - using uv
"command": "uv"
"args": ["run", "python", "main.py"]
```

**Client-specific solutions:**

**Claude Desktop:**
```bash
# Check logs (macOS)
tail -f ~/Library/Logs/Claude/claude_desktop.log

# Check logs (Windows)
tail -f %APPDATA%/Claude/logs/claude_desktop.log

# Restart Claude Desktop after config changes
```

**Cursor IDE:**
```bash
# Check .cursor/mcp.json exists
ls -la .cursor/mcp.json

# Check Cursor's MCP status in developer console
# Ctrl+Shift+I (Windows/Linux) or Cmd+Option+I (macOS)
```

**VS Code:**
```bash
# Verify MCP extension is installed
code --list-extensions | grep mcp

# Check VS Code settings.json
cat ~/.config/Code/User/settings.json | grep -A5 "mcp.servers"
```

---

### 4. API request failures

#### Symptoms
```json
{
  "status": "error",
  "message": "HTTP 401: Unauthorized"
}
```

```json
{
  "status": "error",
  "message": "HTTP 404: Not Found"
}
```

#### Solutions

**Check API endpoints:**
```bash
# Test server list endpoint
curl -H "Authorization: Bearer your-token" \
     "https://your-workspace.ap1.alpacon.io/api/servers/servers/"

# Test specific server
curl -H "Authorization: Bearer your-token" \
     "https://your-workspace.ap1.alpacon.io/api/servers/servers/<server-uuid>/"
```

**Verify server status:**
```python
# Check if server exists
from tools.server_tools import list_servers

result = await list_servers(region='ap1', workspace='your-workspace')
print(result)
```

**Common API issues:**
- **401 Unauthorized**: Invalid or expired token
- **403 Forbidden**: Token lacks required permissions
- **404 Not Found**: Server ID doesn't exist or incorrect endpoint
- **500 Internal Error**: Alpacon API server issue

---

### 5. Work Session gate blocks a command or transfer

#### Symptoms
```json
{
  "status": "pending_approval",
  "code": "work_session_not_active",
  "next_action": "..."
}
```

or a `status="error"` result carrying `work_session_required`, `work_session_not_usable`, `work_session_expired`, `work_session_scope_not_allowed`, `work_session_server_not_allowed`, or `work_session_assignee_mismatch`.

#### Why

An OAuth/browser caller must run infrastructure actions inside an active Work Session. Static API tokens and service tokens bypass the gate, so this appears in hosted mode, not in stdio mode with `token.json`.

#### Solutions

- `work_session_not_active`: the session exists but awaits human approval. Someone approves it in the Alpacon web console or Slack; then retry
- `work_session_required`: open one with `work_session_create`, requesting only the scopes you need (`command`, `webftp`, `tunnel`)
- `work_session_scope_not_allowed` / `work_session_server_not_allowed`: the session's scope or server list doesn't cover this call—`work_session_update` it, or open a session that does
- `work_session_expired`: extend it with `work_session_extend`, or open a new one
- Pass the session explicitly as `work_session_id`, or set `ALPACON_WORK_SESSION` so tools pick it up by default

### 5a. Sudo needs approval

A command that escalates privileges can come back as `status="pending_approval"` with `SUDO_APPROVAL_REQUIRED` or `SUDO_INTENT_DEVIATION`. An agent cannot approve its own request—that is deliberate. Surface it to a human, who approves out of band, then retry the call.

---

### 6. File upload/download issues

#### Symptoms
```json
{
  "status": "error",
  "message": "Failed to upload file"
}
```

#### Solutions

**Check the target directory:**
```
execute_command(
    server_id="7e3984de-49ab-4cc6-bcdf-21fbd35858b8",
    command="ls -la /target/directory/",
    workspace="production",
)
```
The upload fails if the directory does not exist or the transfer user cannot write to it.

**Check the paths:** both `local_file_path` and `remote_file_path` must be absolute. Relative paths, `../`, and null bytes are rejected before the request is sent.

**Hosted mode has no access to your disk.** `webftp_upload_file` reads a local file, which only works when the server runs on your machine. From the hosted server, use `webftp_upload_content` with base64-encoded bytes instead.

**Large folder downloads time out.** A folder downloads as a ZIP staged through S3; raise `ALPACON_MCP_WEBFTP_DOWNLOAD_TIMEOUT` (default 60 seconds) when staging takes longer, and use `webftp_check_status` to follow an in-flight transfer.

---

### 7. Performance issues

#### Symptoms
- Slow response times
- Timeouts
- High memory usage

#### Solutions

**Monitor resource usage:**
```bash
# Check memory usage
ps aux | grep python | grep main.py

# Monitor network connections
netstat -an | grep :8237
```

**Check API latency:**
```bash
# Test API response time
time curl -H "Authorization: Bearer token" \
          "https://your-workspace.ap1.alpacon.io/api/servers/servers/"
```

---

### 8. Configuration issues

#### Development vs production mode

**Issue:** Wrong configuration directory being used

**Debug:**
```bash
# The startup log says which file was chosen
ALPACON_MCP_LOG_LEVEL=INFO python main.py list
# -> "Using global config file: /Users/you/.alpacon-mcp/token.json"
```

**Solutions:**
```bash
# Point at a specific config file
export ALPACON_MCP_CONFIG_FILE="/path/to/token.json"

# Back to the default discovery order
unset ALPACON_MCP_CONFIG_FILE

# Same thing as a flag
python main.py --config-file /path/to/custom/config.json
```

**Note:** the variable is `ALPACON_MCP_CONFIG_FILE`. A plain `ALPACON_CONFIG_FILE` has no effect.

---

## 🛠️ Advanced debugging

### Enable verbose logging

```bash
export ALPACON_MCP_LOG_LEVEL=DEBUG
python main.py
```

DEBUG records request and response bodies. Authorization headers are masked as `[REDACTED]`; everything else is written as-is to `logs/alpacon-mcp.log`, so treat that file as sensitive.

### MCP protocol debugging

```bash
# Test MCP protocol manually
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}}}' | python main.py
```

### Memory debugging

```python
import tracemalloc

tracemalloc.start()

# Your code here

current, peak = tracemalloc.get_traced_memory()
print(f'Current memory usage: {current / 1024 / 1024:.1f} MB')
print(f'Peak memory usage: {peak / 1024 / 1024:.1f} MB')
```

---

## 🔧 Environment-specific issues

### macOS issues

**Python path issues:**
```bash
# Use system Python
/usr/bin/python3 -m venv venv

# Use Homebrew Python
/opt/homebrew/bin/python3 -m venv venv

# Check which Python is being used
which python3
```

**Permission issues:**
```bash
# Fix permissions on config directory
chmod 700 ~/.alpacon-mcp/
chmod 600 ~/.alpacon-mcp/token.json
```

### Windows issues

**Path separator issues:**
```json
{
  "cwd": "C:\\Users\\username\\alpacon-mcp"
}
```

**Virtual environment activation:**
```cmd
# Windows Command Prompt
.venv\Scripts\activate

# PowerShell
.venv\Scripts\Activate.ps1
```

### Linux issues

**Python version issues:**
```bash
# Install Python 3.12+
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-pip

# Create virtual environment with specific Python
python3.12 -m venv .venv
```

**Service configuration:**
```ini
# systemd service file
[Unit]
Description=Alpacon MCP Server
After=network.target

[Service]
Type=simple
User=alpacon
WorkingDirectory=/opt/alpacon-mcp
ExecStart=/opt/alpacon-mcp/.venv/bin/python main.py
Restart=always
Environment=ALPACON_MCP_CONFIG_FILE=/etc/alpacon-mcp/token.json

[Install]
WantedBy=multi-user.target
```

---

## 🆘 Getting help

### Collect debug information

Create a debug report:

```bash
#!/bin/bash
echo "=== Alpacon MCP Debug Report ===" > debug_report.txt
echo "Date: $(date)" >> debug_report.txt
echo "" >> debug_report.txt

echo "=== Environment ===" >> debug_report.txt
echo "OS: $(uname -a)" >> debug_report.txt
echo "Python: $(python --version)" >> debug_report.txt
echo "UV: $(uv --version 2>/dev/null || echo 'Not installed')" >> debug_report.txt
echo "" >> debug_report.txt

echo "=== Dependencies ===" >> debug_report.txt
pip list | grep -E "(mcp|httpx)" >> debug_report.txt
echo "" >> debug_report.txt

echo "=== Configuration ===" >> debug_report.txt
echo "Global config exists: $([ -f ~/.alpacon-mcp/token.json ] && echo 'Yes' || echo 'No')" >> debug_report.txt
echo "Local config exists: $([ -f config/token.json ] && echo 'Yes' || echo 'No')" >> debug_report.txt
echo "ALPACON_MCP_CONFIG_FILE: ${ALPACON_MCP_CONFIG_FILE:-'Not set'}" >> debug_report.txt
echo "" >> debug_report.txt

echo "=== Workspaces ===" >> debug_report.txt
python main.py list >> debug_report.txt 2>&1

echo "Debug report saved to debug_report.txt"
```

### Contact support

When reporting issues, include:

1. **Debug report** (from script above)
2. **Error messages** (complete stack traces)
3. **Configuration files** (with tokens redacted)
4. **Steps to reproduce** the issue
5. **Expected vs actual behavior**

### Community resources

- **Documentation**: Check the [API Reference](api-reference.md)
- **Examples**: See [Usage Examples](examples.md)
- **Configuration**: Review [Configuration Guide](configuration.md)

---

## ✅ Quick fix checklist

Before seeking help, verify:

- [ ] Virtual environment is activated
- [ ] All dependencies are installed (`mcp`, `httpx`, `PyJWT[crypto]`)
- [ ] Token configuration file exists and is properly formatted
- [ ] Absolute paths are used in MCP client configuration
- [ ] Server can be started manually with `python main.py`
- [ ] API tokens are valid and have proper permissions
- [ ] Target servers exist and are accessible
- [ ] Network connectivity to Alpacon API endpoints

---

*Still having issues? Check the [Configuration Guide](configuration.md) or [API Reference](api-reference.md) for more details.*