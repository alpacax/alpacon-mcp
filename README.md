# Alpacon MCP Server

This project is an MCP server based on the FastMCP framework that provides server management, web shell, and web FTP functionality by directly calling the Alpacon API.

## 1. Environment Setup

### Install uv (skip if already installed)

```bash
pipx install uv  # or brew install uv
```

### Create virtual environment and install packages

```bash
uv venv
source .venv/bin/activate
uv pip install mcp[cli] httpx
```

## 2. Token Configuration

### Development Environment Setup (using .config directory)

For development, use the `.config` directory:

```bash
# Set development mode environment variable (optional)
export ALPACON_DEV=true

# Set up tokens in .config directory
mkdir -p .config
cp .config/token.json.example .config/token.json
# Edit token.json file to input actual tokens
```

### Production Environment Setup (using config directory)

When using with MCP clients, use the `config` directory:

```bash
mkdir -p config
# Set up tokens in config/token.json file
```

### Token File Format

The new simplified format:

```json
{
  "dev": {
    "alpacax": "your-dev-api-token-here",
    "test": "your-test-api-token-here"
  },
  "ap1": {
    "alpacax": "your-prod-api-token-here",
    "production": "your-prod-api-token-here"
  }
}
```

Where:
- **Region** (first level): Region name like `dev`, `ap1`, `us1`, `eu1`
- **Workspace** (second level): Workspace/schema name like `alpacax`, `test`, `production`
- **Token** (value): The actual API token string

## 3. Running MCP Server

### Stdio Mode (Default MCP mode)

```bash
# Using default config file discovery
python main.py

# Using specific config file
python main.py --config-file /path/to/your/token.json
```

### SSE Mode (Server-Sent Events)

```bash
# Using default config file discovery
python main_sse.py

# Using specific config file
python main_sse.py --config-file /path/to/your/token.json
```

### Direct Execution

```bash
# Stdio mode
python -c "from server import run; run('stdio')"

# SSE mode
python -c "from server import run; run('sse')"
```

## 4. Available MCP Tools

### Authentication Management
- `auth_set_token`: Set API token
- `auth_remove_token`: Remove API token
- `alpacon_login`: Alpacon server login (legacy compatibility)
- `alpacon_logout`: Alpacon server logout (legacy compatibility)

### Authentication Resources
- `auth://status`: Check authentication status
- `auth://config`: Check configuration directory information
- `auth://tokens/{env}/{workspace}`: Query specific token

## 5. Configuration Directory Priority

1. **Development Mode**: Use `.config` directory with priority
   - When `.config` directory exists or
   - When `ALPACON_DEV=true` environment variable is set

2. **Production Mode**: Use `config` directory
   - General MCP client environment

3. **Token Search**: If tokens are not found in the configured directory, search in other directories as well

## 6. MCP Client Integration

This section explains how to integrate the Alpacon MCP server with various MCP clients like Claude Desktop, Cursor, VS Code, and others.

### Claude Desktop

Add the following configuration to your Claude Desktop settings file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/path/to/alpacon-mcp"
    }
  }
}
```

Alternative using virtual environment directly:
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "/path/to/alpacon-mcp/.venv/bin/python",
      "args": ["main.py"],
      "cwd": "/path/to/alpacon-mcp"
    }
  }
}
```

### Cursor IDE

Create or update `.cursor/mcp_config.json` in your project root:

```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./path/to/alpacon-mcp"
    }
  }
}
```

### VS Code with MCP Extension

Install the MCP extension and add to your VS Code settings (`settings.json`):

```json
{
  "mcp.servers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "./path/to/alpacon-mcp"
    }
  }
}
```

### Generic MCP Client Configuration

For any MCP client that supports the Model Context Protocol:

**Using uv (recommended):**
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py"],
      "cwd": "/absolute/path/to/alpacon-mcp",
      "env": {
        "ALPACON_DEV": "true"
      }
    }
  }
}
```

**Using virtual environment directly:**
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "/absolute/path/to/alpacon-mcp/.venv/bin/python",
      "args": ["main.py"],
      "cwd": "/absolute/path/to/alpacon-mcp",
      "env": {
        "ALPACON_DEV": "true"
      }
    }
  }
}
```

**Using custom config file path:**
```json
{
  "mcpServers": {
    "alpacon-mcp": {
      "command": "uv",
      "args": ["run", "python", "main.py", "--config-file", "/path/to/your/custom-token.json"],
      "cwd": "/absolute/path/to/alpacon-mcp"
    }
  }
}
```

### Configuration Options

- **command**:
  - `uv` (recommended): Uses uv to run Python with proper virtual environment
  - `/path/to/.venv/bin/python`: Direct path to virtual environment Python
  - `python` or `python3`: System Python (not recommended unless globally installed)
- **args**: Arguments to pass to the server script
  - With uv: `["run", "python", "main.py"]`
  - With direct Python: `["main.py"]`
  - With custom config: `["run", "python", "main.py", "--config-file", "/path/to/config.json"]`
- **cwd**: Working directory (absolute path recommended)
- **env**: Environment variables (optional)
  - `ALPACON_DEV=true`: Use development mode with `.config` directory

### Config File Options

- **Default config discovery**: Uses `.config/token.json` (dev mode) or `config/token.json` (prod mode)
- **Custom config path**: Use `--config-file` argument to specify exact path to your token configuration file
- **Priority**: Custom config file > environment variable > default discovery

### Verification

After configuration, restart your MCP client and verify the connection:

1. Check that the Alpacon MCP server appears in available tools
2. Test basic functionality with `auth_set_token` tool
3. Verify authentication resources are accessible

### Troubleshooting

- Ensure Python virtual environment is activated if using one
- Check that all dependencies are installed (`mcp[cli]`, `httpx`)
- Verify file paths are absolute and correct
- Check server logs for connection errors

## 7. Security Considerations

- `config/token.json` and `.config/` directory are included in `.gitignore` and will not be committed to Git
- Never upload token files to public repositories
- Keep development and production tokens separated 