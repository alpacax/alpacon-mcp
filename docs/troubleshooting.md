# Troubleshooting guide

Common issues and solutions for the Alpacon MCP Server.

## 🔍 Diagnostic tools

### Quick health check

```bash
# Test server startup
python main.py --test

# Check token configuration
python -c "from utils.token_manager import TokenManager; tm = TokenManager(); print(tm.get_all_tokens())"

# Verify MCP tools are loaded
python -c "from server import mcp; print([tool.name for tool in mcp.get_tools()])"
```

### Debug mode

```bash
# Enable debug logging
export DEBUG=true
export ALPACON_MCP_LOG_LEVEL=DEBUG
python main.py
```

### Connection test

```python
# Test API connectivity
python -c "
import asyncio
from utils.http_client import http_client
from utils.token_manager import TokenManager

async def test():
    tm = TokenManager()
    token = tm.get_token('ap1', 'company-main')  # Adjust region/workspace
    try:
        result = await http_client.get(
            region='ap1',
            workspace='company-main',
            endpoint='/api/servers/',
            token=token
        )
        print('✅ API connection successful')
        print(f'Response: {result}')
    except Exception as e:
        print(f'❌ API connection failed: {e}')

asyncio.run(test())
"
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
# Install missing dependencies
uv pip install mcp[cli] httpx

# Or using pip
pip install mcp httpx

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
# Verify token file exists
ls -la config/token.json
ls -la .config/token.json

# Check file permissions
chmod 600 config/token.json

# Validate JSON format
python -c "import json; json.load(open('config/token.json'))"
```

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
     "https://alpacon.io/api/servers/"
```

**Debug token loading:**
```python
from utils.token_manager import TokenManager
tm = TokenManager()
print("Config directory:", tm.config_dir)
print("Available tokens:", tm.get_all_tokens())
print("Specific token:", tm.get_token('ap1', 'your-workspace'))
```

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
# Check .cursor/mcp_config.json exists
ls -la .cursor/mcp_config.json

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
     "https://alpacon.io/api/servers/"

# Test specific server
curl -H "Authorization: Bearer your-token" \
     "https://alpacon.io/api/servers/server-id/"
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

### 5. Websh session issues

#### Symptoms
```json
{
  "status": "error",
  "message": "Failed to create Websh session"
}
```

#### Solutions

**Check server connectivity:**
```python
# Verify server is online
from tools.server_tools import get_server
result = await get_server(server_id='your-server-id')
print("Server status:", result.get('data', {}).get('status'))
```

**Test Websh prerequisites:**
```bash
# Ensure server allows SSH connections
# Check with Alpacon web interface first
```

**Debug session creation:**
```python
from tools.websh_tools import websh_session_create
result = await websh_session_create(
    server_id='your-server-id',
    username='admin',  # Make sure user exists
    region='ap1',
    workspace='your-workspace'
)
print(result)
```

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

**Check file permissions:**
```bash
# Ensure target directory exists and is writable
# Check via Websh first:
execute_command(command="ls -la /target/directory/")
```

**Verify file encoding:**
```python
# For binary files, use base64 encoding
import base64

with open('file.pdf', 'rb') as f:
    file_data = base64.b64encode(f.read()).decode()

# For text files, use plain text
with open('file.txt', 'r') as f:
    file_data = f.read()
```

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
          "https://alpacon.io/api/servers/"
```

---

### 8. Configuration issues

#### Development vs production mode

**Issue:** Wrong configuration directory being used

**Debug:**
```python
from utils.token_manager import TokenManager
tm = TokenManager()
print("Using config directory:", tm.config_dir)
print("ALPACON_CONFIG_FILE:", os.getenv('ALPACON_CONFIG_FILE'))
```

**Solutions:**
```bash
# Use custom config file location
export ALPACON_CONFIG_FILE=".config/token.json"

# Use default config location
unset ALPACON_CONFIG_FILE

# Use custom config file
python main.py --config-file /path/to/custom/config.json
```

---

## 🛠️ Advanced debugging

### Enable verbose logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or set environment variable
export ALPACON_MCP_LOG_LEVEL=DEBUG
```

### Network debugging

```bash
# Monitor HTTP traffic
export HTTPX_LOG_LEVEL=DEBUG
python main.py
```

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
print(f"Current memory usage: {current / 1024 / 1024:.1f} MB")
print(f"Peak memory usage: {peak / 1024 / 1024:.1f} MB")
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
chmod 700 ~/.config/
chmod 600 ~/.config/token.json
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
Environment=ALPACON_CONFIG_FILE=/etc/alpacon-mcp/token.json

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
echo "Config dir exists: $([ -d config ] && echo 'Yes' || echo 'No')" >> debug_report.txt
echo ".config dir exists: $([ -d .config ] && echo 'Yes' || echo 'No')" >> debug_report.txt
echo "ALPACON_CONFIG_FILE: ${ALPACON_CONFIG_FILE:-'Not set'}" >> debug_report.txt
echo "" >> debug_report.txt

echo "=== Token Test ===" >> debug_report.txt
python -c "
try:
    from utils.token_manager import TokenManager
    tm = TokenManager()
    tokens = tm.get_all_tokens()
    print(f'Found {len(tokens)} token configurations')
    for (region, workspace) in tokens:
        print(f'- {region}/{workspace}')
except Exception as e:
    print(f'Error: {e}')
" >> debug_report.txt

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
- [ ] All dependencies are installed (`mcp[cli]`, `httpx`)
- [ ] Token configuration file exists and is properly formatted
- [ ] Absolute paths are used in MCP client configuration
- [ ] Server can be started manually with `python main.py`
- [ ] API tokens are valid and have proper permissions
- [ ] Target servers exist and are accessible
- [ ] Network connectivity to Alpacon API endpoints

---

*Still having issues? Check the [Configuration Guide](configuration.md) or [API Reference](api-reference.md) for more details.*