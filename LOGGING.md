# Alpacon MCP server logging guide

A comprehensive logging system has been added to the MCP server. Debugging and monitoring are now much easier.

## 📋 Features

### Logging levels
- **DEBUG**: Detailed debugging information (API request/response bodies, token lookup, etc.)
- **INFO**: General operational information (server start, successful API calls, etc.)
- **WARNING**: Situations requiring attention (no token, retries, etc.)
- **ERROR**: Error situations (API failures, exceptions, etc.)

### Log output destinations
- **stderr**: Real-time logs on the console. Never stdout—in stdio mode stdout carries the MCP protocol itself
- **File**: All logs saved to `logs/alpacon-mcp.log`, relative to the working directory. The file sink runs on a `QueueListener` thread, so a log call never puts a disk write on the event loop the request path shares

## 🚀 Usage

### 1. Basic execution (INFO level)
```bash
python main.py
```

### 2. Setting log level via environment variable
```bash
# Debug mode
export ALPACON_MCP_LOG_LEVEL=DEBUG
python main.py

# Error only output
export ALPACON_MCP_LOG_LEVEL=ERROR
python main.py
```

## 📊 Log examples

### Server start
```
2024-01-20 10:30:15 - alpacon_mcp.main - INFO - [main.py:17] - Starting Alpacon MCP Server
2024-01-20 10:30:15 - alpacon_mcp.server - INFO - [server.py:11] - Initializing FastMCP server - host: 127.0.0.1, port: 8237
2024-01-20 10:30:15 - alpacon_mcp.token_manager - INFO - [token_manager.py:37] - Using default config file: config/token.json
```

### API calls
```
2024-01-20 10:30:20 - alpacon_mcp.server_tools - INFO - [server_tools.py:26] - list_servers called - workspace: production, region: ap1
2024-01-20 10:30:20 - alpacon_mcp.token_manager - INFO - [token_manager.py:130] - Found token for production.ap1 from config file
2024-01-20 10:30:20 - alpacon_mcp.http_client - INFO - [http_client.py:87] - HTTP GET request to https://production.ap1.alpacon.io/api/servers/servers/
2024-01-20 10:30:21 - alpacon_mcp.http_client - INFO - [http_client.py:109] - HTTP GET success - Status: 200, Content-Length: 1024
```

### Error situations
```
2024-01-20 10:30:25 - alpacon_mcp.token_manager - WARNING - [token_manager.py:133] - No token found for invalid.ap1
2024-01-20 10:30:25 - alpacon_mcp.server_tools - ERROR - [server_tools.py:32] - No token found for invalid.ap1
```

## 🔧 Logging components

### 1. Centralized Logger (`utils/logger.py`)
- Consistent logging format across all modules
- Simultaneous output to file and console: stderr directly, the file through a `QueueHandler`
- Log level control via environment variables
- `stop_log_listener()` drains the queue on shutdown—`app_lifespan` calls it last, after every other cleanup has logged

### 2. Module-specific loggers
- `main`: Server startup/shutdown
- `server`: FastMCP server initialization
- `http_client`: HTTP requests/responses
- `token_manager`: Token management
- `server_tools`: Server management tools

### 3. HTTP request logging
- Request URL, method, parameters
- Response status code, content length
- Detailed information in error situations
- Retry logic tracking
- **Security**: Authorization headers are automatically processed as [REDACTED]

## 🛠️ Debugging tips

### 1. Token issues resolution
```
WARNING - No token found for workspace.region
```
→ Check if token is properly configured

### 2. API call failures
```
ERROR - HTTP GET error - Status: 401, URL: https://...
```
→ Verify if token is valid and API endpoint is correct

### 3. Network issues
```
WARNING - Network error: ..., retrying (1/3) in 1s
```
→ Check network connection status

## 📁 Log file management

### Log file location
- `logs/alpacon-mcp.log`: Main log file
- Log directory is automatically created

### Log rotation (future plan)
Currently, logs accumulate in a single file. Log rotation functionality can be added if needed.

## 🔒 What the entry log records

Every tool call behind `@mcp_tool_handler` writes one `called with` line at INFO. Read this before deciding what your log file may hold.

- Dropped by name: credential names (`token`, `password`, `secret`, `key`), the upload payload `file_content`, URLs that are themselves a credential (`url`, `package_proxy`), free text such as `content`, `description`, and `purpose`, personal data such as `email`, the `env` map, and config lists such as `allowed_domains`. See `_UNLOGGED_KEYS` in `utils/decorators.py` for the full set.
- Bounded by size: a remaining string longer than 256 characters is replaced by `<len=N>`, a list or dict longer than ten entries by `<items=N>`. A shorter list or dict keeps its entries, each under the same 256-character bound.
- Kept whole, up to 256 characters each: the commands a call ran (`command`, `commands`, `run_after`, `shell`) and the text a caller typed into a filter (`search`, `search_query`). A credential passed inline on a command line (`-p`, `--token`, an `Authorization` header on `curl`) is recorded, and no key filter can catch it—the secret sits inside a value the log exists to keep.
- Outside the entry log: at DEBUG the HTTP client writes each request and response body whole (`Request body`, `Response body`), so the fields dropped above are recorded one layer down. Run at INFO wherever that matters. One exception survives the level: an upstream 4xx or 5xx writes the response body at ERROR, 401 alone excepted (`utils/http_client.py`). That is the response and not the request.

## 🎯 Performance considerations

- DEBUG level records request/response bodies in logs, which may impact performance
- INFO level is recommended for production environments

---

Now you can track all MCP server operations through logs, enabling quick debugging when issues occur! 🎉