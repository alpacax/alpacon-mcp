"""Websh (Web Shell) management tools for Alpacon MCP server."""

import asyncio
import json
from typing import Any, Optional

import websockets

from server import mcp
from utils.common import MCP_USER_AGENT, error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client

# WebSocket connection pool for persistent connections
# Format: {channel_id: {'websocket': connection, 'url': url, 'session_id': id}}
websocket_pool = {}

# Session pool for reusing sessions by server
# Format: {f"{region}:{workspace}:{server_id}": session_info}
session_pool = {}


async def get_or_create_channel(
    server_id: str,
    workspace: str,
    region: str = 'ap1',
    username: Optional[str] = None,
    token: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    """Get existing channel or create new session+channel for a server.

    This helper function maintains persistent WebSocket connections by:
    1. Checking if we already have an active channel for this server
    2. If not, creating a new session and connecting to its channel
    3. Storing the connection for future reuse

    Args:
        server_id: Server ID
        workspace: Workspace name
        region: Region (default: ap1)
        username: Optional username for session
        token: API token

    Returns:
        Tuple of (channel_id, session_info)
    """
    pool_key = f'{region}:{workspace}:{server_id}'

    # Step 1: Check if we have an existing session in memory
    if pool_key in session_pool:
        session_info = session_pool[pool_key]
        channel_id = session_info.get('userchannel_id')

        # Verify the channel is still connected
        if channel_id in websocket_pool:
            try:
                websocket = websocket_pool[channel_id]['websocket']
                await websocket.ping()
                # Connection still alive, reuse it
                return channel_id, session_info
            except Exception:
                # Connection dead, clean up
                if channel_id in websocket_pool:
                    del websocket_pool[channel_id]
                del session_pool[pool_key]

    # Step 2: Check if there's an existing MCP session in Alpacon API
    try:
        sessions_response = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint='/api/websh/sessions/',
            token=token,
            params={'page_size': 50},  # Get recent sessions
        )

        # Find active MCP sessions for this server
        for session in sessions_response.get('results', []):
            # Check if: same server, MCP user-agent, not closed
            if (
                session.get('server') == server_id
                and session.get('closed_at') is None
                and session.get('user_agent')
                and 'alpacon-mcp' in session.get('user_agent', '')
            ):
                # Try to reconnect to this session
                try:
                    session_id = session['id']
                    # Get fresh session details to get WebSocket URL
                    session_detail = await http_client.get(
                        region=region,
                        workspace=workspace,
                        endpoint=f'/api/websh/sessions/{session_id}/',
                        token=token,
                    )

                    websocket_url = session_detail.get('websocket_url')
                    channel_id = session_detail.get('userchannel_id')

                    if websocket_url and channel_id:
                        # Try to connect to existing session
                        websocket = await websockets.connect(
                            websocket_url, user_agent_header=MCP_USER_AGENT
                        )

                        # Test connection
                        await websocket.ping()

                        # Store in pools
                        websocket_pool[channel_id] = {
                            'websocket': websocket,
                            'url': websocket_url,
                            'session_id': session_id,
                        }
                        session_pool[pool_key] = session_detail

                        return channel_id, session_detail
                except Exception:  # noqa: S112
                    # This session is not reusable, try next one
                    continue
    except Exception:
        # If fetching sessions fails, just proceed to create new one
        pass

    # Step 3: Create new session
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

    # Extract session info
    channel_id = result['userchannel_id']
    websocket_url = result['websocket_url']
    session_id = result['id']

    # Connect to WebSocket with custom User-Agent for identification
    websocket = await websockets.connect(
        websocket_url, user_agent_header=MCP_USER_AGENT
    )

    # Store in pools
    websocket_pool[channel_id] = {
        'websocket': websocket,
        'url': websocket_url,
        'session_id': session_id,
    }

    session_pool[pool_key] = result

    return channel_id, result


async def execute_command_via_channel(
    channel_id: str, command: str, timeout: int = 10
) -> str:
    """Execute command using existing channel connection.

    Args:
        channel_id: Channel ID from get_or_create_channel
        command: Command to execute
        timeout: Timeout in seconds

    Returns:
        Command output as string
    """
    if channel_id not in websocket_pool:
        raise ValueError(f'Channel {channel_id} not connected')

    websocket = websocket_pool[channel_id]['websocket']

    # Send command
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
            # Remove dead connection
            del websocket_pool[channel_id]
            raise ConnectionError(f'WebSocket connection lost for channel {channel_id}')

    return ''.join(output_lines)


@mcp_tool_handler(description='Create a new Websh session')
async def websh_session_create(
    server_id: str,
    workspace: str,
    username: Optional[str] = None,
    region: str = 'ap1',
    **kwargs,
) -> dict[str, Any]:
    """Create a new Websh session and establish WebSocket connection.

    This function creates a session and immediately connects via WebSocket
    to ensure user_agent is properly recorded in the UserChannel.

    Args:
        server_id: Server ID to create session on
        workspace: Workspace name. Required parameter
        username: Optional username for the session (if not provided, uses authenticated user's name)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

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
            # Connect with MCP User-Agent header
            websocket = await websockets.connect(
                websocket_url, user_agent_header=MCP_USER_AGENT
            )

            # Store in connection pool for reuse
            websocket_pool[channel_id] = {
                'websocket': websocket,
                'url': websocket_url,
                'session_id': result['id'],
            }

            # Store in session pool
            pool_key = f'{region}:{workspace}:{server_id}'
            session_pool[pool_key] = result

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


@mcp_tool_handler(description='Get list of Websh sessions')
async def websh_sessions_list(
    workspace: str, server_id: Optional[str] = None, region: str = 'ap1', **kwargs
) -> dict[str, Any]:
    """Get list of Websh sessions.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter sessions
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

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


@mcp_tool_handler(description='Create a new user channel for an existing Websh session')
async def websh_session_reconnect(
    session_id: str, workspace: str, region: str = 'ap1', **kwargs
) -> dict[str, Any]:
    """Create a new user channel for an existing Websh session.
    This allows reconnecting to a session that has lost its user channel connection.
    Only works for sessions created by the current user.

    Args:
        session_id: Existing Websh session ID to reconnect to
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

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


@mcp_tool_handler(description='Terminate a Websh session')
async def websh_session_terminate(
    session_id: str, workspace: str, region: str = 'ap1', **kwargs
) -> dict[str, Any]:
    """Terminate a Websh session.

    Args:
        session_id: Websh session ID to terminate
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

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
    description='Connect to Websh user channel and maintain persistent connection'
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
        # Check if already connected
        if channel_id in websocket_pool:
            return {
                'status': 'already_connected',
                'channel_id': channel_id,
                'message': 'Channel already has active WebSocket connection',
            }

        # Connect to WebSocket
        websocket = await websockets.connect(websocket_url)

        # Store in pool
        websocket_pool[channel_id] = {
            'websocket': websocket,
            'url': websocket_url,
            'session_id': session_id,
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


@mcp.tool(description='List active WebSocket channels')
async def websh_channels_list() -> dict[str, Any]:
    """List all active WebSocket connections in the pool.

    Returns:
        List of active channels with connection info
    """
    try:
        channels = []
        for channel_id, info in websocket_pool.items():
            websocket = info['websocket']

            # Check connection status
            try:
                # Quick ping test to verify connection
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


@mcp.tool(description='Disconnect WebSocket channel')
async def websh_channel_disconnect(channel_id: str) -> dict[str, Any]:
    """Disconnect and remove WebSocket connection from pool.

    Args:
        channel_id: User channel ID to disconnect

    Returns:
        Disconnection status
    """
    try:
        if channel_id not in websocket_pool:
            return {
                'status': 'not_found',
                'channel_id': channel_id,
                'message': 'Channel not found in active connections',
            }

        # Get connection info
        info = websocket_pool[channel_id]
        websocket = info['websocket']

        # Close WebSocket connection
        try:
            await websocket.close()
        except Exception:
            pass  # Connection might already be closed

        # Remove from pool
        del websocket_pool[channel_id]

        return {
            'status': 'success',
            'channel_id': channel_id,
            'message': 'WebSocket connection closed and removed from pool',
        }

    except Exception as e:
        # Remove from pool even if close failed
        if channel_id in websocket_pool:
            del websocket_pool[channel_id]

        return {
            'status': 'error',
            'message': f'Error disconnecting channel: {str(e)}',
            'channel_id': channel_id,
        }


@mcp.tool(description='Execute command using persistent WebSocket connection')
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
        # Check if channel exists in pool
        if channel_id not in websocket_pool:
            return {
                'status': 'not_connected',
                'channel_id': channel_id,
                'message': 'Channel not connected. Use websh_channel_connect first.',
            }

        info = websocket_pool[channel_id]
        websocket = info['websocket']

        # Check if connection is still alive
        try:
            # Test connection by checking if we can send a ping
            await websocket.ping()
        except (websockets.exceptions.ConnectionClosed, AttributeError):
            # Remove dead connection
            del websocket_pool[channel_id]
            return {
                'status': 'connection_closed',
                'channel_id': channel_id,
                'message': 'WebSocket connection was closed. Reconnect required.',
            }

        # Send command
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
                # Remove closed connection
                del websocket_pool[channel_id]
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


@mcp.tool(description='Execute commands in Websh session via WebSocket')
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
        # Connect to WebSocket
        async with websockets.connect(websocket_url) as websocket:
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
    description='Execute command using persistent connection (recommended)'
)
async def execute_command(
    server_id: str,
    command: str,
    workspace: str,
    username: Optional[str] = None,
    region: str = 'ap1',
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
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
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


@mcp_tool_handler(description='Execute multiple commands using persistent connection')
async def execute_command_batch(
    server_id: str,
    commands: list[str],
    workspace: str,
    username: Optional[str] = None,
    region: str = 'ap1',
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
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
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


@mcp.tool(description='Execute multiple commands in Websh session via WebSocket')
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

        async with websockets.connect(websocket_url) as websocket:
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
