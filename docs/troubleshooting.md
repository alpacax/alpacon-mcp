# Troubleshooting Guide

Common issues and solutions for the Alpacon MCP Server.

## 🔍 Diagnostic Tools

### Quick Health Check

```bash
# Test server startup
python main.py --test

# Check token configuration
python -c "from utils.token_manager import TokenManager; tm = TokenManager(); print(tm.get_all_tokens())"

# Verify MCP tools are loaded
python -c "from server import mcp; print([tool.name for tool in mcp.get_tools()])"
```

### Debug Mode

```bash
# Enable debug logging
export DEBUG=true
export LOG_LEVEL=DEBUG
python main.py
```

### Connection Test

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

## 🚨 Common Issues

### 1. Server Won't Start

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

#### Check Installation
```bash
# List installed packages
uv pip list

# Verify MCP installation
python -c "import mcp; print(mcp.__version__)"
```

---

### 2. Authentication Failures

#### Symptoms
```json
{
  "status": "error",
  "message": "No token found for workspace.region"
}
```

#### Solutions

**Check Token File:**
```bash
# Verify token file exists
ls -la config/token.json
ls -la .config/token.json

# Check file permissions
chmod 600 config/token.json

# Validate JSON format
python -c "import json; json.load(open('config/token.json'))"
```

**Verify Token Format:**
```json
{
  "ap1": {
    "your-workspace": "your-actual-token-here"
  }
}
```

**Test Token Manually:**
```bash
curl -H "Authorization: Bearer your-token-here" \
     "https://your-workspace.ap1.alpacon.io/api/servers/"
```

**Debug Token Loading:**
```python
from utils.token_manager import TokenManager
tm = TokenManager()
print("Config directory:", tm.config_dir)
print("Available tokens:", tm.get_all_tokens())
print("Specific token:", tm.get_token('ap1', 'your-workspace'))
```

---

### 3. MCP Client Connection Issues

#### Symptoms
- Client shows "MCP server not responding"
- Tools don't appear in client
- Connection timeouts

#### Solutions

**Check Configuration Paths:**
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

**Test Manual Execution:**
```bash
# Navigate to project directory
cd /path/to/alpacon-mcp

# Test command from MCP config
uv run python main.py

# Alternative test
/path/to/alpacon-mcp/.venv/bin/python main.py
```

**Common Path Issues:**
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

**Client-Specific Solutions:**

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

### 4. API Request Failures

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

**Check API Endpoints:**
```bash
# Test server list endpoint
curl -H "Authorization: Bearer your-token" \
     "https://workspace.ap1.alpacon.io/api/servers/"

# Test specific server
curl -H "Authorization: Bearer your-token" \
     "https://workspace.ap1.alpacon.io/api/servers/server-id/"
```

**Verify Server Status:**
```python
# Check if server exists
from tools.server_tools import servers_list
result = await servers_list(region='ap1', workspace='your-workspace')
print(result)
```

**Common API Issues:**
- **401 Unauthorized**: Invalid or expired token
- **403 Forbidden**: Token lacks required permissions
- **404 Not Found**: Server ID doesn't exist or incorrect endpoint
- **500 Internal Error**: Alpacon API server issue

---

### 5. WebSH Session Issues

#### Symptoms
```json
{
  "status": "error",
  "message": "Failed to create WebSH session"
}
```

#### Solutions

**Check Server Connectivity:**
```python
# Verify server is online
from tools.server_tools import server_get
result = await server_get(server_id='your-server-id')
print("Server status:", result.get('data', {}).get('status'))
```

**Test WebSH Prerequisites:**
```bash
# Ensure server allows SSH connections
# Check with Alpacon web interface first
```

**Debug Session Creation:**
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

### 6. File Upload/Download Issues

#### Symptoms
```json
{
  "status": "error",
  "message": "Failed to upload file"
}
```

#### Solutions

**Check File Permissions:**
```bash
# Ensure target directory exists and is writable
# Check via WebSH first:
websh_command_execute(command="ls -la /target/directory/")
```

**Verify File Encoding:**
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

### 7. Performance Issues

#### Symptoms
- Slow response times
- Timeouts
- High memory usage

#### Solutions

**Monitor Resource Usage:**
```bash
# Check memory usage
ps aux | grep python | grep main.py

# Monitor network connections
netstat -an | grep :8237
```

**Optimize Configuration:**
```bash
# Increase timeout values
export ALPACON_REQUEST_TIMEOUT=60
export ALPACON_CONNECT_TIMEOUT=30

# Reduce concurrent requests
export MAX_CONCURRENT_REQUESTS=20
```

**Check API Latency:**
```bash
# Test API response time
time curl -H "Authorization: Bearer token" \
          "https://workspace.ap1.alpacon.io/api/servers/"
```

---

### 8. Configuration Issues

#### Development vs Production Mode

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

## 🛠️ Advanced Debugging

### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or set environment variable
export LOG_LEVEL=DEBUG
```

### Network Debugging

```bash
# Monitor HTTP traffic
export HTTPX_LOG_LEVEL=DEBUG
python main.py
```

### MCP Protocol Debugging

```bash
# Test MCP protocol manually
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"test","version":"1.0"}}}' | python main.py
```

### Memory Debugging

```python
import tracemalloc
tracemalloc.start()

# Your code here

current, peak = tracemalloc.get_traced_memory()
print(f"Current memory usage: {current / 1024 / 1024:.1f} MB")
print(f"Peak memory usage: {peak / 1024 / 1024:.1f} MB")
```

---

## 🔧 Environment-Specific Issues

### macOS Issues

**Python Path Issues:**
```bash
# Use system Python
/usr/bin/python3 -m venv venv

# Use Homebrew Python
/opt/homebrew/bin/python3 -m venv venv

# Check which Python is being used
which python3
```

**Permission Issues:**
```bash
# Fix permissions on config directory
chmod 700 ~/.config/
chmod 600 ~/.config/token.json
```

### Windows Issues

**Path Separator Issues:**
```json
{
  "cwd": "C:\\Users\\username\\alpacon-mcp"
}
```

**Virtual Environment Activation:**
```cmd
# Windows Command Prompt
.venv\Scripts\activate

# PowerShell
.venv\Scripts\Activate.ps1
```

### Linux Issues

**Python Version Issues:**
```bash
# Install Python 3.12+
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-pip

# Create virtual environment with specific Python
python3.12 -m venv .venv
```

**Service Configuration:**
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

## 🆘 Getting Help

### Collect Debug Information

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

### Contact Support

When reporting issues, include:

1. **Debug report** (from script above)
2. **Error messages** (complete stack traces)
3. **Configuration files** (with tokens redacted)
4. **Steps to reproduce** the issue
5. **Expected vs actual behavior**

### Community Resources

- **Documentation**: Check the [API Reference](api-reference.md)
- **Examples**: See [Usage Examples](examples.md)
- **Configuration**: Review [Configuration Guide](configuration.md)

---

## ✅ Quick Fix Checklist

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