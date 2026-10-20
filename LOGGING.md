# Alpacon MCP server logging guide

A comprehensive logging system has been added to the MCP server. Debugging and monitoring are now much easier.

## 📋 Features

### Logging levels
- **DEBUG**: Detailed debugging information (API request/response field names and sizes, token lookup, etc.)
- **INFO**: General operational information (server start, successful API calls, etc.)
- **WARNING**: Situations requiring attention (no token, retries, etc.)
- **ERROR**: Error situations (API failures, exceptions, etc.)

### Log output destinations
- **Console**: Text mode writes real-time logs to stderr; streamable-http with `LOG_FORMAT=json` writes JSON to stdout. Stdio always keeps stdout for the MCP protocol
- **File**: All logs saved to `logs/alpacon-mcp.log`, relative to the working directory, except in streamable-http with `LOG_FORMAT=json`, which writes no file. The file sink runs on a `QueueListener` thread, so a log call never puts a disk write on the event loop the request path shares

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
2024-01-20 10:30:15 - alpacon_mcp.token_manager - INFO - [token_manager.py:48] - Using local config file: config/token.json
2024-01-20 10:30:15 - alpacon_mcp.server - INFO - [server.py:208] - Creating MCP server without auth (stdio/SSE mode)
2024-01-20 10:30:15 - alpacon_mcp.main - INFO - [main.py:126] - Starting Alpacon MCP Server
```

### API calls
```
2024-01-20 10:30:20 - alpacon_mcp.decorators - INFO - [decorators.py:704] - list_servers called with: {'workspace': 'production', 'region': 'ap1', 'page': None, 'page_size': None}
2024-01-20 10:30:20 - alpacon_mcp.http_client - INFO - [http_client.py:213] - HTTP GET request to https://production.ap1.alpacon.io/api/servers/servers/
2024-01-20 10:30:21 - alpacon_mcp.http_client - INFO - [http_client.py:239] - HTTP GET success - Status: 200, Content-Length: 1024
2024-01-20 10:30:21 - alpacon_mcp.decorators - INFO - [decorators.py:713] - list_servers completed successfully
```

### Error situations
```
2024-01-20 10:30:25 - alpacon_mcp.token_manager - WARNING - [token_manager.py:185] - No token found for invalid.ap1
2024-01-20 10:30:25 - alpacon_mcp.common - ERROR - [common.py:542] - No token found for invalid.ap1
```

## 🔧 Logging components

### 1. Centralized Logger (`utils/logger.py`)
- Consistent logging format across all modules
- Simultaneous output to file and console: text directly to stderr, or JSON to stdout in streamable-http with `LOG_FORMAT=json`; the file through a `QueueHandler`, which JSON mode removes
- Log level control via environment variables
- `stop_log_listener()` drains the queue on shutdown—`app_lifespan` calls it last, after every other cleanup has logged

### 2. Module-specific loggers
`get_logger('<name>')` returns the standard `logging.Logger` named `alpacon_mcp.<name>`. The main ones:
- `main`, `main_sse`, `main_http`: Server startup for each transport
- `server`: MCP server creation and application lifespan
- `decorators`: The entry and completion line of every tool call
- `http_client`: HTTP requests/responses
- `auth`, `oauth`, `auth_error_middleware`: JWT verification, the OAuth routes, and the re-auth challenge
- `token_manager`: Token management

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
- `logs/alpacon-mcp.log.lock`: Empty lock file the servers sharing `logs/` take before each write
- Log directory is automatically created

### Log rotation
The file rolls over at 10 MiB, keeping five backups (`alpacon-mcp.log.1` through `alpacon-mcp.log.5`, oldest last), so the log stays under about 60 MiB. The limits are `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT` in `utils/logger.py`.

Stdio servers started from the same working directory share `logs/`, so their records interleave in one file. Each record is written under a lock on `logs/alpacon-mcp.log.lock`, and the file is opened for that record and closed after it. A server that rolls the file over therefore never leaves another writing to the renamed file, and on Windows no other server holds the file open to block the rename.

## 🔒 What the entry log records

Every tool call behind `@mcp_tool_handler` writes one `called with` line at INFO. Read this before deciding what your log file may hold.

- Written as given, bounded: the arguments in `_LOGGED_VERBATIM_KEYS` (`utils/decorators.py`), which are identifiers, names, paths, enums and filters, timestamps, and the `workspace` and `region` a call targets. A string longer than 256 characters is replaced by `<str len=N>`, a list or dict longer than ten entries by `<list items=N>` or `<dict items=N>`. A shorter list or dict keeps its entries, each under the same bound.
- Recorded by type and size alone: every other argument, under its own key. `{"command": "<str len=42>"}` is all the log keeps of a command (`command`, `commands`), and the same goes for filter text (`search`, `search_query`), payloads, free text, URLs, personal data, and `env` maps. A credential typed inline on a command line never reaches the log. A parameter added later is recorded this way until someone reviews it into the verbatim set.
- Numbers, flags and `None` are written as given, since they carry no text.
- The audit trail of what a command ran is the server's own command record, not this log.

## 🧱 One record per line

- A client-supplied value such as an OAuth `error_description`, a `client_id`, a JWT `kid`, or a claim is escaped and bounded at the call site (`escape_for_log` in `utils/logger.py`).
- No value can start a second line. In text mode, both sinks escape every control character in a message, and traceback lines are indented under the record line. In streamable-http with `LOG_FORMAT=json`, console JSON on stdout escapes line breaks and puts the traceback in `error.stack`.

## 🧾 JSON records in an HTTP deployment

`main_http.py` (streamable-http) reads `LOG_FORMAT`, the same switch alpacon-server reads. With `LOG_FORMAT=json` the console sink writes one JSON object per line to stdout, carrying `timestamp` (UTC), `level`, `message` and `name`:

```json
{"timestamp": "2026-10-20T01:43:55.066Z", "level": "INFO", "message": "172.17.0.1:61240 - \"GET /mcp HTTP/1.1\" 401", "name": "uvicorn.access"}
```

- Datadog takes the status from `level`. A plain-text line has no level it can read, so it falls back to the stream: every stderr line becomes an error.
- A record with a traceback carries it as `error.kind`, `error.message` and `error.stack` on the same line.
- uvicorn's records, access log included, go through the same handler in this mode, so they come out as JSON too.
- No log file is written: stdout is the only sink, as in alpacon-server.
- A startup that fails because `AUTH0_DOMAIN` or `AUTH0_CLIENT_ID` is unset writes one `ERROR` record naming the missing variables, then exits with status 1.
- Any other value, or none, keeps the text format on stderr.
- stdio and SSE never read the switch. In stdio, stdout carries the MCP protocol itself.

## 🔌 Libraries

- `httpx` and `httpcore` write warnings and errors only: at INFO httpx writes each request URL with its query string, and at DEBUG httpcore writes the response headers.
- The MCP SDK (`mcp`) never writes below INFO, even with `ALPACON_MCP_LOG_LEVEL=DEBUG`: at DEBUG it writes each client message, tool arguments included.
- The uvicorn access log records the request path without its query string, which on `/oauth/callback` carries the authorization code.
- In text mode, uvicorn's own records go to stderr through its handler with the same escaping and traceback indentation as this server's. In streamable-http with `LOG_FORMAT=json`, uvicorn records propagate to the root handler as console JSON on stdout, with tracebacks in `error.stack`, and skip the escaping filter, which JSON makes redundant.

## 🎯 Performance considerations

- DEBUG level records the shape of every request and response, which may impact performance
- INFO level is recommended for production environments

---

Now you can track all MCP server operations through logs, enabling quick debugging when issues occur! 🎉