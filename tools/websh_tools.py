"""Websh (Web Shell) management tools for Alpacon MCP server."""

import asyncio
import json
import time
from typing import Any

import websockets

from server import mcp
from utils.common import MCP_USER_AGENT, error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.logger import get_logger

logger = get_logger('websh_tools')


def _ws_connect_kwargs(token: str | None = None) -> dict[str, Any]:
    """Build kwargs for websockets.connect() with optional JWT auth header.

    When running in HTTP transport mode with JWT authentication,
    passes the JWT as a Bearer token header for WebSocket auth.
    In stdio/SSE mode, no extra headers are added (token is in URL path).

    Args:
        token: The auth token (JWT or API token). If JWT, adds Bearer header.

    Returns:
        Dict of extra kwargs to pass to websockets.connect()
    """
    kwargs: dict[str, Any] = {'user_agent_header': MCP_USER_AGENT}
    if token and http_client._is_jwt(token):
        # JWT format (header.payload.signature) — pass as Bearer header
        kwargs['additional_headers'] = {'Authorization': f'Bearer {token}'}
    return kwargs


def _ws_kwargs_from_auth_context() -> dict[str, Any]:
    """Build WebSocket connect kwargs using JWT from FastMCP auth context.

    Attempts to extract a JWT from the MCP auth context (HTTP transport mode)
    and returns appropriate websockets.connect() kwargs. Falls back to default
    kwargs when running in stdio/SSE mode or when auth context is unavailable.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access_token = get_access_token()
        if access_token:
            return _ws_connect_kwargs(access_token.token)
    except ImportError:
        pass
    return _ws_connect_kwargs()


# WebSocket connection pool for persistent connections
# Format: {channel_id: {'websocket': connection, 'url': url, 'session_id': id}}
websocket_pool: dict[str, dict[str, Any]] = {}

# Session pool for reusing sessions by server
# Format: {f"{region}:{workspace}:{server_id}": session_info}
session_pool: dict[str, dict[str, Any]] = {}

# Lock guarding both websocket_pool and session_pool against concurrent access.
# Single lock for both dicts since they are always modified together.
_pool_lock = asyncio.Lock()

# TTL for stale session cleanup (seconds)
_SESSION_TTL = 3600  # 1 hour


def _cleanup_stale_sessions() -> list:
    """Remove stale session pool entries and return websockets to close.

    Must be called while holding _pool_lock.
    Returns list of websocket objects that should be closed outside the lock.
    """
    now = time.monotonic()
    stale_keys = [
        key
        for key, info in session_pool.items()
        if now - info.get('_created_at', 0) > _SESSION_TTL
    ]
    ws_to_close = []
    for key in stale_keys:
        info = session_pool.pop(key, None)
        if info:
            channel_id = info.get('userchannel_id')
            if channel_id and channel_id in websocket_pool:
                ws_info = websocket_pool.pop(channel_id, None)
                if ws_info:
                    ws_to_close.append(ws_info['websocket'])
    return ws_to_close


async def cleanup_all_connections():
    """Close all WebSocket connections and clear connection pools.

    Called during graceful shutdown to ensure all resources are released.
    Each websocket.close() is wrapped with a timeout to prevent hanging.
    """
    logger.info(
        f'Cleaning up WebSocket connections: {len(websocket_pool)} channels, '
        f'{len(session_pool)} sessions'
    )

    for channel_id, info in list(websocket_pool.items()):
        try:
            ws = info['websocket']
            await asyncio.wait_for(ws.close(), timeout=5)
            logger.debug(f'Closed WebSocket for channel {channel_id}')
        except Exception as e:
            logger.warning(f'Error closing WebSocket for channel {channel_id}: {e}')

    websocket_pool.clear()
    session_pool.clear()
    logger.info('All WebSocket connections cleaned up')


async def get_or_create_channel(
    server_id: str,
    workspace: str,
    region: str = '',
    username: str | None = None,
    token: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Get existing channel or create new session+channel for a server.

    This helper function maintains persistent WebSocket connections by:
    1. Checking if we already have an active channel for this server
    2. If not, creating a new session and connecting to its channel
    3. Storing the connection for future reuse

    Thread-safe: pool access is guarded by _pool_lock.
    Network I/O (HTTP calls, WebSocket connect/ping) runs outside the lock.

    Args:
        server_id: Server ID
        workspace: Workspace name
        region: Region (auto-detected from token if not specified)
        username: Optional username for session
        token: API token

    Returns:
        Tuple of (channel_id, session_info)
    """
    pool_key = f'{region}:{workspace}:{server_id}'

    # Phase 1: Check pool for existing connection (lock for reads only)
    cached_ws = None
    cached_channel_id = None
    cached_session_info = None

    async with _pool_lock:
        stale_ws = _cleanup_stale_sessions()

        if pool_key in session_pool:
            session_info = session_pool[pool_key]
            channel_id = session_info.get('userchannel_id')
            if channel_id and channel_id in websocket_pool:
                cached_ws = websocket_pool[channel_id]['websocket']
                cached_channel_id = channel_id
                cached_session_info = session_info

    # Close stale websockets outside lock
    for ws in stale_ws:
        try:
            await ws.close()
        except Exception:
            pass

    # Phase 2: Verify cached connection (outside lock)
    if (
        cached_ws is not None
        and cached_channel_id is not None
        and cached_session_info is not None
    ):
        try:
            await cached_ws.ping()
            return cached_channel_id, cached_session_info
        except Exception:
            # Connection dead, clean up under lock
            async with _pool_lock:
                websocket_pool.pop(cached_channel_id, None)
                session_pool.pop(pool_key, None)

    # Phase 3: Check for existing MCP session in Alpacon API (outside lock)
    try:
        sessions_response = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint='/api/websh/sessions/',
            token=token,
            params={'page_size': 50},
        )

        for session in sessions_response.get('results', []):
            if (
                session.get('server') == server_id
                and session.get('closed_at') is None
                and session.get('user_agent')
                and 'alpacon-mcp' in session.get('user_agent', '')
            ):
                try:
                    session_id = session['id']
                    session_detail = await http_client.get(
                        region=region,
                        workspace=workspace,
                        endpoint=f'/api/websh/sessions/{session_id}/',
                        token=token,
                    )

                    websocket_url = session_detail.get('websocket_url')
                    channel_id = session_detail.get('userchannel_id')

                    if websocket_url and channel_id:
                        ws = await websockets.connect(
                            websocket_url, **_ws_connect_kwargs(token)
                        )
                        await ws.ping()

                        # Store in pools under lock (copy to avoid leaking metadata)
                        async with _pool_lock:
                            websocket_pool[channel_id] = {
                                'websocket': ws,
                                'url': websocket_url,
                                'session_id': session_id,
                            }
                            pool_entry = dict(session_detail)
                            pool_entry['_created_at'] = time.monotonic()
                            session_pool[pool_key] = pool_entry

                        return channel_id, session_detail
                except Exception:  # noqa: S112
                    continue
    except Exception:
        pass

    # Phase 4: Create new session (outside lock)
    session_data = {'server': server_id, 'rows': 24, 'cols': 80}
    if username:
        session_data['username'] = username

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/websh/sessions/',
        token=token,
        data=session_data,
    )

    channel_id = result['userchannel_id']
    websocket_url = result['websocket_url']
    session_id = result['id']

    ws = await websockets.connect(websocket_url, **_ws_connect_kwargs(token))

    # Store in pools under lock (copy to avoid leaking metadata)
    async with _pool_lock:
        websocket_pool[channel_id] = {
            'websocket': ws,
            'url': websocket_url,
            'session_id': session_id,
        }
        pool_entry = dict(result)
        pool_entry['_created_at'] = time.monotonic()
        session_pool[pool_key] = pool_entry

    return channel_id, result


async def execute_command_via_channel(
    channel_id: str, command: str, timeout: int = 10
) -> str:
    """Execute command using existing channel connection.

    Thread-safe: pool reads and deletes are guarded by _pool_lock.
    WebSocket I/O runs outside the lock.

    Args:
        channel_id: Channel ID from get_or_create_channel
        command: Command to execute
        timeout: Timeout in seconds

    Returns:
        Command output as string
    """
    async with _pool_lock:
        if channel_id not in websocket_pool:
            raise ValueError(f'Channel {channel_id} not connected')
        websocket = websocket_pool[channel_id]['websocket']

    # Send command (outside lock - WebSocket I/O)
    await websocket.send(command + '\n')

    # Collect output
    output_lines = []
    start_time = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start_time) < timeout:
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=1.0)

            if isinstance(message, bytes):
                output_lines.append(message.decode('utf-8', errors='ignore'))
            elif message.startswith('{"type":'):
                try:
                    data = json.loads(message)
                    if data.get('type') == 'output':
                        output_lines.append(data.get('data', ''))
                except json.JSONDecodeError:
                    output_lines.append(message)
            else:
                output_lines.append(message)

        except TimeoutError:
            break
        except websockets.exceptions.ConnectionClosed:
            # Remove dead connection under lock
            async with _pool_lock:
                websocket_pool.pop(channel_id, None)
            raise ConnectionError(f'WebSocket connection lost for channel {channel_id}')

    return ''.join(output_lines)


@mcp_tool_handler(
    description='Create a new Websh terminal session on a server and establish a WebSocket connection. Returns session ID, channel ID, and WebSocket URL for command execution. Use this for manual session management; for simpler usage, prefer execute_command instead.'
)
async def websh_session_create(
    server_id: str,
    workspace: str,
    username: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new Websh session and establish WebSocket connection.

    This function creates a session and immediately connects via WebSocket
    to ensure user_agent is properly recorded in the UserChannel.

    Args:
        server_id: Server ID to create session on
        workspace: Workspace name. Required parameter
        username: Optional username for the session (if not provided, uses authenticated user's name)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Session creation response with WebSocket connection established
    """
    token = kwargs.get('token')

    # Prepare session data with terminal size
    session_data = {
        'server': server_id,
        'rows': 24,  # Terminal height
        'cols': 80,  # Terminal width
    }

    # Only include username if it's provided
    if username:
        session_data['username'] = username

    # Make async call to create session
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/websh/sessions/',
        token=token,
        data=session_data,
    )

    # Establish WebSocket connection to record user_agent
    websocket_url = result.get('websocket_url')
    channel_id = result.get('userchannel_id')

    if websocket_url and channel_id:
        try:
            # Connect with MCP User-Agent header (and JWT if available)
            websocket = await websockets.connect(
                websocket_url, **_ws_connect_kwargs(token)
            )

            # Store in pools under lock (copy to avoid leaking metadata)
            async with _pool_lock:
                websocket_pool[channel_id] = {
                    'websocket': websocket,
                    'url': websocket_url,
                    'session_id': result['id'],
                }

                pool_key = f'{region}:{workspace}:{server_id}'
                pool_entry = dict(result)
                pool_entry['_created_at'] = time.monotonic()
                session_pool[pool_key] = pool_entry

            result['websocket_connected'] = True
            result['mcp_note'] = 'WebSocket connected with MCP user-agent'
        except Exception as e:
            # Connection failed but session was created
            result['websocket_connected'] = False
            result['websocket_error'] = str(e)

    return success_response(
        data=result,
        server_id=server_id,
        username=username or 'auto',
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='List active and past Websh terminal sessions in a workspace. Filterable by server ID. Use this to check which sessions are currently open or to find a session ID for reconnection.'
)
async def websh_sessions_list(
    workspace: str, server_id: str | None = None, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get list of Websh sessions.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter sessions
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Sessions list response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if server_id:
        params['server'] = server_id

    # Make async call to get sessions
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/websh/sessions/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Reconnect to an existing Websh session by creating a new user channel. Returns a fresh WebSocket URL and channel ID. Use this when a previous channel connection was lost but the session is still active on the server.'
)
async def websh_session_reconnect(
    session_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Create a new user channel for an existing Websh session.
    This allows reconnecting to a session that has lost its user channel connection.
    Only works for sessions created by the current user.

    Args:
        session_id: Existing Websh session ID to reconnect to
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Reconnection response with new WebSocket URL and user channel
    """
    token = kwargs.get('token')

    # First, verify the session exists and belongs to current user
    try:
        await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f'/api/websh/sessions/{session_id}/',
            token=token,
        )
    except Exception as e:
        return error_response(
            f'Session {session_id} not found or not accessible: {str(e)}'
        )

    # Create new user channel for existing session using the correct API endpoint
    channel_data = {
        'session': session_id,
        'is_master': True,  # Set as master channel for reconnection
        'read_only': False,
    }

    # Make async call to create new user channel
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/websh/user-channels/',
        token=token,
        data=channel_data,
    )

    return success_response(
        data=result,
        session_id=session_id,
        region=region,
        workspace=workspace,
        message='New user channel created for existing session',
    )


@mcp_tool_handler(
    description='Terminate and close a Websh terminal session on the server. Use this to clean up sessions that are no longer needed and free server resources.'
)
async def websh_session_terminate(
    session_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Terminate a Websh session.

    Args:
        session_id: Websh session ID to terminate
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Session termination response
    """
    token = kwargs.get('token')

    # Make async call to close session using POST to /close/ endpoint
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/close/',
        token=token,
        data={},  # Empty data for POST request
    )

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp.tool(
    description='Open a persistent WebSocket connection to a Websh user channel and store it in the connection pool. The connection can be reused for multiple commands via websh_channel_execute. Use websh_channel_disconnect to close it when done.'
)
async def websh_channel_connect(
    channel_id: str, websocket_url: str, session_id: str
) -> dict[str, Any]:
    """Connect to Websh user channel and store connection for reuse.

    Args:
        channel_id: User channel ID
        websocket_url: WebSocket URL from user channel creation
        session_id: Session ID for reference

    Returns:
        Connection status
    """
    try:
        async with _pool_lock:
            # Check if already connected
            if channel_id in websocket_pool:
                return {
                    'status': 'already_connected',
                    'channel_id': channel_id,
                    'message': 'Channel already has active WebSocket connection',
                }

        # Connect to WebSocket (outside lock - network I/O)
        ws_kwargs = _ws_kwargs_from_auth_context()
        websocket = await websockets.connect(websocket_url, **ws_kwargs)

        async with _pool_lock:
            # Double-check: another coroutine may have connected while we awaited
            if channel_id in websocket_pool:
                ws_to_close = websocket
            else:
                ws_to_close = None
                # Store in pool
                websocket_pool[channel_id] = {
                    'websocket': websocket,
                    'url': websocket_url,
                    'session_id': session_id,
                }

        # Close duplicate connection outside lock
        if ws_to_close is not None:
            try:
                await ws_to_close.close()
            except Exception:
                pass
            return {
                'status': 'already_connected',
                'channel_id': channel_id,
                'message': 'Channel already has active WebSocket connection',
            }

        return {
            'status': 'success',
            'channel_id': channel_id,
            'session_id': session_id,
            'websocket_url': websocket_url,
            'message': 'WebSocket connection established and stored',
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': f'Failed to connect WebSocket: {str(e)}',
            'channel_id': channel_id,
        }


@mcp.tool(
    description='List all active WebSocket channel connections in the local connection pool. Returns channel IDs, session IDs, and live health status via ping check. Use this to see which persistent connections are currently available.'
)
async def websh_channels_list() -> dict[str, Any]:
    """List all active WebSocket connections in the pool.

    Returns:
        List of active channels with connection info
    """
    try:
        # Snapshot pool entries under lock
        async with _pool_lock:
            pool_snapshot = list(websocket_pool.items())

        # Ping outside lock to avoid holding it during network I/O
        channels = []
        for channel_id, info in pool_snapshot:
            websocket = info['websocket']

            try:
                await websocket.ping()
                is_open = True
            except Exception:
                is_open = False

            channels.append(
                {
                    'channel_id': channel_id,
                    'session_id': info['session_id'],
                    'websocket_url': info['url'],
                    'is_connected': is_open,
                }
            )

        return {
            'status': 'success',
            'active_channels': len(channels),
            'channels': channels,
        }

    except Exception as e:
        return {'status': 'error', 'message': f'Failed to list channels: {str(e)}'}


@mcp.tool(
    description='Close a WebSocket channel connection and remove it from the connection pool. Always disconnect channels when finished to free resources. The channel ID comes from websh_channel_connect or websh_channels_list.'
)
async def websh_channel_disconnect(channel_id: str) -> dict[str, Any]:
    """Disconnect and remove WebSocket connection from pool.

    Args:
        channel_id: User channel ID to disconnect

    Returns:
        Disconnection status
    """
    try:
        async with _pool_lock:
            if channel_id not in websocket_pool:
                return {
                    'status': 'not_found',
                    'channel_id': channel_id,
                    'message': 'Channel not found in active connections',
                }

            # Pop from pool before closing (no other coroutine can see it)
            info = websocket_pool.pop(channel_id)
            websocket = info['websocket']

        # Close WebSocket connection outside lock
        try:
            await websocket.close()
        except Exception:
            pass  # Connection might already be closed

        return {
            'status': 'success',
            'channel_id': channel_id,
            'message': 'WebSocket connection closed and removed from pool',
        }

    except Exception as e:
        # Ensure removal from pool even if close failed
        async with _pool_lock:
            websocket_pool.pop(channel_id, None)

        return {
            'status': 'error',
            'message': f'Error disconnecting channel: {str(e)}',
            'channel_id': channel_id,
        }


@mcp.tool(
    description='Execute a shell command on an already-connected WebSocket channel and return the terminal output. The channel must have been opened with websh_channel_connect first. Use this for running multiple commands efficiently on the same connection.'
)
async def websh_channel_execute(
    channel_id: str, command: str, timeout: int = 10
) -> dict[str, Any]:
    """Execute command using existing WebSocket connection from pool.

    Args:
        channel_id: User channel ID
        command: Command to execute
        timeout: Timeout in seconds (default: 10)

    Returns:
        Command execution result
    """
    try:
        # Read pool under lock
        async with _pool_lock:
            if channel_id not in websocket_pool:
                return {
                    'status': 'not_connected',
                    'channel_id': channel_id,
                    'message': 'Channel not connected. Use websh_channel_connect first.',
                }
            info = websocket_pool[channel_id]
            websocket = info['websocket']

        # Check if connection is still alive (outside lock - network I/O)
        try:
            await websocket.ping()
        except (websockets.exceptions.ConnectionClosed, AttributeError):
            # Remove dead connection under lock
            async with _pool_lock:
                websocket_pool.pop(channel_id, None)
            return {
                'status': 'connection_closed',
                'channel_id': channel_id,
                'message': 'WebSocket connection was closed. Reconnect required.',
            }

        # Send command (outside lock)
        await websocket.send(command + '\n')

        # Collect output
        output_lines = []
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=1.0)

                # Handle different message types
                if isinstance(message, bytes):
                    output_lines.append(message.decode('utf-8', errors='ignore'))
                elif message.startswith('{"type":'):
                    try:
                        data = json.loads(message)
                        if data.get('type') == 'output':
                            output_lines.append(data.get('data', ''))
                    except json.JSONDecodeError:
                        output_lines.append(message)
                else:
                    output_lines.append(message)

            except TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                # Remove closed connection under lock
                async with _pool_lock:
                    websocket_pool.pop(channel_id, None)
                return {
                    'status': 'connection_lost',
                    'channel_id': channel_id,
                    'message': 'WebSocket connection lost during execution',
                }

        return {
            'status': 'success',
            'channel_id': channel_id,
            'command': command,
            'output': ''.join(output_lines),
            'session_id': info['session_id'],
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': f'Command execution failed: {str(e)}',
            'channel_id': channel_id,
            'command': command,
        }


@mcp.tool(
    description='Execute a single command via a disposable WebSocket connection to a Websh session URL. The connection is opened, used once, and closed automatically. For running multiple commands, use execute_command_batch or websh_channel_* tools instead.'
)
async def websh_websocket_execute(
    websocket_url: str, command: str, timeout: int = 10
) -> dict[str, Any]:
    """Execute a command via WebSocket connection to Websh session.

    Args:
        websocket_url: WebSocket URL from user channel creation
        command: Command to execute
        timeout: Timeout in seconds (default: 10)

    Returns:
        Command execution result
    """
    try:
        # Connect to WebSocket with JWT auth if available
        ws_kwargs = _ws_kwargs_from_auth_context()
        async with websockets.connect(websocket_url, **ws_kwargs) as websocket:
            # Send command with newline (simulating terminal input)
            await websocket.send(command + '\n')

            # Collect output for specified timeout
            output_lines = []
            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    # Wait for message with short timeout
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)

                    # Handle both text and binary messages
                    if isinstance(message, bytes):
                        output_lines.append(message.decode('utf-8', errors='ignore'))
                    elif message.startswith('{"type":'):
                        # Parse JSON messages (Websh protocol)
                        try:
                            data = json.loads(message)
                            if data.get('type') == 'output':
                                output_lines.append(data.get('data', ''))
                        except json.JSONDecodeError:
                            output_lines.append(message)
                    else:
                        output_lines.append(message)

                except TimeoutError:
                    # No more messages, command likely completed
                    break
                except websockets.exceptions.ConnectionClosed:
                    break

            return {
                'status': 'success',
                'command': command,
                'output': ''.join(output_lines),
                'websocket_url': websocket_url,
            }

    except Exception as e:
        return {
            'status': 'error',
            'message': f'WebSocket execution failed: {str(e)}',
            'command': command,
            'websocket_url': websocket_url,
        }


@mcp_tool_handler(
    description='Execute a shell command on a server using automatic connection pooling. This is the recommended way to run commands — it creates or reuses Websh sessions and WebSocket connections transparently. No ACL permission required unlike Command API tools.'
)
async def execute_command(
    server_id: str,
    command: str,
    workspace: str,
    username: str | None = None,
    region: str = '',
    timeout: int = 10,
    **kwargs,
) -> dict[str, Any]:
    """Execute command on server using persistent WebSocket connection.

    This is the recommended way to execute commands as it:
    - Reuses existing sessions and WebSocket connections
    - Reduces API calls by maintaining connection pool
    - Automatically handles connection failures and retries

    For multiple commands on the same server, this will reuse the same connection.

    Args:
        server_id: Server ID to execute command on
        command: Command to execute
        workspace: Workspace name. Required parameter
        username: Optional username for the session
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        timeout: Command timeout in seconds (default: 10)

    Returns:
        Command execution response with output
    """
    token = kwargs.get('token')

    try:
        # Get or create persistent channel
        channel_id, session_info = await get_or_create_channel(
            server_id=server_id,
            workspace=workspace,
            region=region,
            username=username,
            token=token,
        )

        # Execute command
        output = await execute_command_via_channel(
            channel_id=channel_id, command=command, timeout=timeout
        )

        return success_response(
            data={
                'command': command,
                'output': output,
                'channel_id': channel_id,
                'session_id': session_info['id'],
                'reused_connection': True,
            },
            server_id=server_id,
            region=region,
            workspace=workspace,
            message='Command executed via persistent connection',
        )

    except Exception as e:
        return error_response(
            f'Command execution failed: {str(e)}', server_id=server_id, command=command
        )


@mcp_tool_handler(
    description='Execute multiple shell commands sequentially on the same server using a single persistent connection. Much more efficient than calling execute_command repeatedly. Returns per-command output. No ACL permission required.'
)
async def execute_command_batch(
    server_id: str,
    commands: list[str],
    workspace: str,
    username: str | None = None,
    region: str = '',
    timeout: int = 30,
    **kwargs,
) -> dict[str, Any]:
    """Execute multiple commands sequentially using persistent connection.

    All commands will be executed on the same WebSocket connection,
    making this very efficient for multiple operations.

    Args:
        server_id: Server ID to execute commands on
        commands: List of commands to execute
        workspace: Workspace name. Required parameter
        username: Optional username for the session
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        timeout: Total timeout in seconds (default: 30)

    Returns:
        Batch execution response with all results
    """
    token = kwargs.get('token')

    try:
        # Get or create persistent channel
        channel_id, session_info = await get_or_create_channel(
            server_id=server_id,
            workspace=workspace,
            region=region,
            username=username,
            token=token,
        )

        # Execute all commands
        results = []
        for command in commands:
            try:
                output = await execute_command_via_channel(
                    channel_id=channel_id,
                    command=command,
                    timeout=timeout // len(commands),  # Distribute timeout
                )
                results.append(
                    {'command': command, 'output': output, 'status': 'success'}
                )
            except Exception as e:
                results.append({'command': command, 'error': str(e), 'status': 'error'})

        return success_response(
            data={
                'results': results,
                'total_commands': len(commands),
                'channel_id': channel_id,
                'session_id': session_info['id'],
                'reused_connection': True,
            },
            server_id=server_id,
            region=region,
            workspace=workspace,
            message=f'Executed {len(commands)} commands via persistent connection',
        )

    except Exception as e:
        return error_response(
            f'Batch execution failed: {str(e)}', server_id=server_id, commands=commands
        )


@mcp.tool(
    description='Execute multiple commands sequentially via a disposable WebSocket connection to a Websh session URL. Returns per-command output. The connection is opened once and closed after all commands complete. For persistent connections, use execute_command_batch instead.'
)
async def websh_websocket_batch_execute(
    websocket_url: str, commands: list[str], timeout: int = 30
) -> dict[str, Any]:
    """Execute multiple commands sequentially via WebSocket connection.

    Args:
        websocket_url: WebSocket URL from user channel creation
        commands: List of commands to execute
        timeout: Total timeout in seconds (default: 30)

    Returns:
        Batch execution results
    """
    try:
        results = []

        # Get JWT auth headers if available
        ws_kwargs = _ws_kwargs_from_auth_context()
        async with websockets.connect(websocket_url, **ws_kwargs) as websocket:
            for command in commands:
                # Send command
                await websocket.send(command + '\n')

                # Collect output for each command
                output_lines = []
                start_time = asyncio.get_event_loop().time()

                while (
                    asyncio.get_event_loop().time() - start_time
                ) < 5:  # 5 sec per command
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)

                        if isinstance(message, bytes):
                            output_lines.append(
                                message.decode('utf-8', errors='ignore')
                            )
                        elif message.startswith('{"type":'):
                            try:
                                data = json.loads(message)
                                if data.get('type') == 'output':
                                    output_lines.append(data.get('data', ''))
                            except json.JSONDecodeError:
                                output_lines.append(message)
                        else:
                            output_lines.append(message)

                    except TimeoutError:
                        break
                    except websockets.exceptions.ConnectionClosed:
                        break

                results.append({'command': command, 'output': ''.join(output_lines)})

                # Small delay between commands
                await asyncio.sleep(0.5)

        return {
            'status': 'success',
            'results': results,
            'total_commands': len(commands),
            'websocket_url': websocket_url,
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': f'WebSocket batch execution failed: {str(e)}',
            'commands': commands,
            'websocket_url': websocket_url,
        }


# ===============================
# WEBSH TUNNEL TOOLS
# ===============================


@mcp_tool_handler(
    description='List Websh tunnel sessions in a workspace. Tunnels provide port forwarding to remote servers. Filterable by server ID or username. Returns tunnel ID, target port, status, and connection details.'
)
async def list_websh_tunnels(
    workspace: str,
    server_id: str | None = None,
    username: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List Websh tunnel sessions.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by server ID (optional)
        username: Filter by username (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Tunnel sessions list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if server_id:
        params['server'] = server_id
    if username:
        params['username'] = username
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/websh/tunnels/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Create a Websh tunnel session for port forwarding to a remote server. Returns tunnel ID, WebSocket URL for CLI/Web connections, and connect URL for editor connections. Requires tunnel_enabled on the target server.'
)
async def create_websh_tunnel(
    server_id: str,
    workspace: str,
    target_port: int | None = None,
    username: str | None = None,
    groupname: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new Websh tunnel session.

    Args:
        server_id: Server ID to create tunnel to
        workspace: Workspace name. Required parameter
        target_port: Target port for port forwarding (1-65535). Required for CLI tunnels, optional for editor tunnels
        username: Optional username for the tunnel session
        groupname: Optional group name for the tunnel session
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Tunnel creation response with connection URLs
    """
    token = kwargs.get('token')

    tunnel_data: dict[str, Any] = {'server': server_id}
    if target_port is not None:
        tunnel_data['target_port'] = target_port
    if username:
        tunnel_data['username'] = username
    if groupname:
        tunnel_data['groupname'] = groupname

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/websh/tunnels/',
        token=token,
        data=tunnel_data,
    )

    return success_response(
        data=result,
        server_id=server_id,
        target_port=target_port,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Close an active Websh tunnel session. Terminates the port forwarding connection. Use list_websh_tunnels to find the tunnel ID.'
)
async def close_websh_tunnel(
    tunnel_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Close a Websh tunnel session.

    Args:
        tunnel_id: Tunnel session ID to close
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Tunnel closure response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/tunnels/{tunnel_id}/close/',
        token=token,
        data={},
    )

    return success_response(
        data=result, tunnel_id=tunnel_id, region=region, workspace=workspace
    )


# ===============================
# WEBSH SESSION SHARING TOOLS
# ===============================


@mcp_tool_handler(
    description='Generate a shareable link for a Websh session with password protection. The link allows temporary access to the session for collaboration. Only the session owner can share. Returns shared URL, password, and expiration time.'
)
async def share_websh_session(
    session_id: str,
    workspace: str,
    read_only: bool = True,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Share a Websh session via shareable link.

    Args:
        session_id: Session ID to share
        workspace: Workspace name. Required parameter
        read_only: Whether shared access is read-only (default: True)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Shared session details with URL, password, and expiration
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/share/',
        token=token,
        data={'read_only': read_only},
    )

    return success_response(
        data=result,
        session_id=session_id,
        read_only=read_only,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Send email invitations to collaborate on a Websh session. Invitees receive a link with temporary access token. Only the session owner can invite. Supports bulk invitations to multiple email addresses.'
)
async def invite_to_websh_session(
    session_id: str,
    emails: list[str],
    workspace: str,
    read_only: bool = True,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Invite users to a Websh session via email.

    Args:
        session_id: Session ID to invite users to
        emails: List of email addresses to invite
        workspace: Workspace name. Required parameter
        read_only: Whether invitees get read-only access (default: True)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Invitation status response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/invite/',
        token=token,
        data={'emails': emails, 'read_only': read_only},
    )

    return success_response(
        data=result,
        session_id=session_id,
        invited_count=len(emails),
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Join a shared Websh session using a password or invitation token. Returns WebSocket URL for connecting to the shared session. Requires MCP authentication. The password or token provides session-level access on top of the authenticated connection.'
)
async def join_shared_session(
    channel_id: str,
    workspace: str,
    password: str | None = None,
    token_value: str | None = None,
    username: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Join a shared Websh session.

    Args:
        channel_id: User channel ID from the shared session link
        workspace: Workspace name. Required parameter
        password: Password from share_websh_session (for unauthenticated access)
        token_value: Invitation token (for authenticated access via invite)
        username: Display name for the session (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Join response with WebSocket URL and session details
    """
    auth_token = kwargs.get('token')

    join_data: dict[str, Any] = {}
    if password:
        join_data['password'] = password
    if token_value:
        join_data['token'] = token_value
    if username:
        join_data['username'] = username

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/user-channels/{channel_id}/join/',
        token=auth_token,
        data=join_data,
    )

    return success_response(
        data=result,
        channel_id=channel_id,
        region=region,
        workspace=workspace,
    )


# ===============================
# WEBSH SESSION RECORDS & ANALYSIS TOOLS
# ===============================


@mcp_tool_handler(
    description='Retrieve terminal recording data for a closed Websh session. Returns paginated terminal output with timestamps for session playback and auditing. Useful for reviewing what commands were executed and their output.'
)
async def get_session_records(
    session_id: str,
    workspace: str,
    region: str = '',
    page: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get session recording data.

    Args:
        session_id: Session ID to get records for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)

    Returns:
        Session recording data with timestamps
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/records/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Search terminal recording content within a Websh session using fuzzy matching. Finds specific commands or output text in session history. Useful for finding when a particular command was run or locating specific output.'
)
async def search_session_records(
    session_id: str,
    query: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Search session records by content.

    Args:
        session_id: Session ID to search records in
        query: Search query string (fuzzy match on terminal content)
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Matching session records with timestamps
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/search/',
        token=token,
        params={'q': query},
    )

    return success_response(
        data=result,
        session_id=session_id,
        query=query,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Get AI-generated security analysis results for a Websh session. Returns risk score, detected commands, threat indicators, MITRE ATT&CK mapping, and recommended actions. The session must have been analyzed first via request_session_analysis.'
)
async def get_session_analysis(
    session_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get session security analysis results.

    Args:
        session_id: Session ID to get analysis for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Session analysis with risk score, commands, threat indicators, and recommendations
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/analysis/',
        token=token,
    )

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Request AI security analysis for a closed Websh session. Queues the session for analysis by the AI service. Returns accepted (202) if queued, or already_exists if previously analyzed. Use get_session_analysis to retrieve results after processing.'
)
async def request_session_analysis(
    session_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Request AI analysis of a closed Websh session.

    Args:
        session_id: Session ID to analyze (must be a closed session)
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Analysis request status (accepted, no_content, or already_exists)
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/websh/sessions/{session_id}/analyze/',
        token=token,
        data={},
    )

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


# Websh sessions resource
@mcp.resource(
    uri='websh://sessions/{region}/{workspace}',
    name='Websh Sessions List',
    description='Get list of Websh sessions',
    mime_type='application/json',
)
async def websh_sessions_resource(region: str, workspace: str) -> dict[str, Any]:
    """Get Websh sessions as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Websh sessions information
    """
    sessions_data = websh_sessions_list(region=region, workspace=workspace)
    return {'content': sessions_data}
