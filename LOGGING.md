# Alpacon MCP server logging guide

A comprehensive logging system has been added to the MCP server. Debugging and monitoring are now much easier.

## 📋 Features

### Logging levels
- **DEBUG**: Detailed debugging information (API request/response field names and sizes, token lookup, etc.)
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
2024-01-20 10:30:15 - alpacon_mcp.main - INFO - [main.py:96] - Starting Alpacon MCP Server
2024-01-20 10:30:15 - alpacon_mcp.server - INFO - [server.py:206] - Creating MCP server without auth (stdio/SSE mode)
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
- `server`: MCP server creation and application lifespan
- `http_client`: HTTP requests/responses
- `token_manager`: Token management
- `server_tools`: Server management tools

### 3. HTTP request logging
- Request URL and method; at DEBUG, the names of the parameters, body fields and headers, with each value's type and size
- Response status code, content length
- On an upstream error, the status and the error body's field names, never its text
- Retry logic tracking
- **Security**: no header value, parameter value, or body value is written at any level

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

- Written as given, bounded: the arguments in `_LOGGED_VERBATIM_KEYS` (`utils/decorators.py`), which are identifiers, names, paths, enums and filters, timestamps, and the `workspace` and `region` a call targets. A string longer than 256 characters is replaced by `<str len=N>`, a list or dict longer than ten entries by `<list items=N>` or `<dict items=N>`. A shorter list or dict keeps its entries, each under the same bound.
- Recorded by type and size alone: every other argument, under its own key. `{"command": "<str len=42>"}` is all the log keeps of a command (`command`, `commands`), and the same goes for filter text (`search`, `search_query`), payloads, free text, URLs, personal data, and `env` maps. A credential typed inline on a command line never reaches the log. A parameter added later is recorded this way until someone reviews it into the verbatim set.
- Numbers, flags and `None` are written as given, since they carry no text.
- The audit trail of what a command ran is the server's own command record, not this log.

## 🧱 One record per line

- A client-supplied value such as an OAuth `error_description`, a `client_id`, a JWT `kid`, or a claim is escaped and bounded at the call site (`escape_for_log` in `utils/logger.py`).
- Both sinks escape every control character in a message, so no value can start a second line. A traceback keeps its line breaks, and each of its lines is indented under the record line, so none starts where a record would.

## 🔌 Libraries

- `httpx` and `httpcore` write warnings and errors only: at INFO httpx writes each request URL with its query string, and at DEBUG httpcore writes the response headers.
- The MCP SDK (`mcp`) never writes below INFO, even with `ALPACON_MCP_LOG_LEVEL=DEBUG`: at DEBUG it writes each client message, tool arguments included.
- The uvicorn access log records the request path without its query string, which on `/oauth/callback` carries the authorization code.
- uvicorn's own records, which go to stderr through uvicorn's handler, get the same escaping and traceback indentation as this server's.

## 🎯 Performance considerations

- DEBUG level records the shape of every request and response, which may impact performance
- INFO level is recommended for production environments

---

Now you can track all MCP server operations through logs, enabling quick debugging when issues occur! 🎉