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

```json
{
  "dev": {
    "alpacax": {
      "token": "your-dev-api-token-here",
      "workspace": "alpacax",
      "env": "dev"
    }
  },
  "prod": {
    "alpacax": {
      "token": "your-prod-api-token-here",
      "workspace": "alpacax",
      "env": "prod"
    }
  }
}
```

## 3. Running MCP Server

### Stdio Mode (Default MCP mode)

```bash
python main.py
```

### SSE Mode (Server-Sent Events)

```bash
python main_sse.py
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

## 6. Security Considerations

- `config/token.json` and `.config/` directory are included in `.gitignore` and will not be committed to Git
- Never upload token files to public repositories
- Keep development and production tokens separated 