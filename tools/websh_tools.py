"""Websh (Web Shell) management tools for Alpacon MCP server."""

import asyncio
import json
import websockets
from typing import Dict, Any, Optional, List
from server import mcp
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler


# WebSocket connection pool for persistent connections
websocket_pool = {}  # {channel_id: {'websocket': connection, 'url': url, 'session_id': id}}


@mcp_tool_handler(description="Create a new Websh session")
async def websh_session_create(
    server_id: str,
    workspace: str,
    username: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Create a new Websh session.

    Args:
        server_id: Server ID to create session on
        workspace: Workspace name. Required parameter
        username: Optional username for the session (if not provided, uses authenticated user's name)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Session creation response
    """
    token = kwargs.get('token')

    # Prepare session data with terminal size
    session_data = {
        "server": server_id,
        "rows": 24,     # Terminal height
        "cols": 80      # Terminal width
    }

    # Only include username if it's provided
    if username:
        session_data["username"] = username

    # Make async call to create session
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint="/api/websh/sessions/",
        token=token,
        data=session_data
    )

    return success_response(
        data=result,
        server_id=server_id,
        username=username or "auto",
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get list of Websh sessions")
async def websh_sessions_list(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
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
        params["server"] = server_id

    # Make async call to get sessions
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/websh/sessions/",
        token=token,
        params=params
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Create a new user channel for an existing Websh session")
async def websh_session_reconnect(
    session_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
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
        session_info = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/websh/sessions/{session_id}/",
            token=token
        )
    except Exception as e:
        return error_response(f"Session {session_id} not found or not accessible: {str(e)}")

    # Create new user channel for existing session using the correct API endpoint
    channel_data = {
        "session": session_id,
        "is_master": True,  # Set as master channel for reconnection
        "read_only": False
    }

    # Make async call to create new user channel
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint="/api/websh/user-channels/",
        token=token,
        data=channel_data
    )

    return success_response(
        data=result,
        session_id=session_id,
        region=region,
        workspace=workspace,
        message="New user channel created for existing session"
    )


@mcp_tool_handler(description="Terminate a Websh session")
async def websh_session_terminate(
    session_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
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
        endpoint=f"/api/websh/sessions/{session_id}/close/",
        token=token,
        data={}  # Empty data for POST request
    )

    return success_response(
        data=result,
        session_id=session_id,
        region=region,
        workspace=workspace
    )


@mcp.tool(
    description="Connect to Websh user channel and maintain persistent connection"
)
async def websh_channel_connect(
    channel_id: str,
    websocket_url: str,
    session_id: str
) -> Dict[str, Any]:
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
                "status": "already_connected",
                "channel_id": channel_id,
                "message": "Channel already has active WebSocket connection"
            }

        # Connect to WebSocket
        websocket = await websockets.connect(websocket_url)

        # Store in pool
        websocket_pool[channel_id] = {
            'websocket': websocket,
            'url': websocket_url,
            'session_id': session_id
        }

        return {
            "status": "success",
            "channel_id": channel_id,
            "session_id": session_id,
            "websocket_url": websocket_url,
            "message": "WebSocket connection established and stored"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to connect WebSocket: {str(e)}",
            "channel_id": channel_id
        }


@mcp.tool(description="List active WebSocket channels")
async def websh_channels_list() -> Dict[str, Any]:
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
            except:
                is_open = False

            channels.append({
                "channel_id": channel_id,
                "session_id": info['session_id'],
                "websocket_url": info['url'],
                "is_connected": is_open
            })

        return {
            "status": "success",
            "active_channels": len(channels),
            "channels": channels
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list channels: {str(e)}"
        }


@mcp.tool(description="Disconnect WebSocket channel")
async def websh_channel_disconnect(
    channel_id: str
) -> Dict[str, Any]:
    """Disconnect and remove WebSocket connection from pool.

    Args:
        channel_id: User channel ID to disconnect

    Returns:
        Disconnection status
    """
    try:
        if channel_id not in websocket_pool:
            return {
                "status": "not_found",
                "channel_id": channel_id,
                "message": "Channel not found in active connections"
            }

        # Get connection info
        info = websocket_pool[channel_id]
        websocket = info['websocket']

        # Close WebSocket connection
        try:
            await websocket.close()
        except:
            pass  # Connection might already be closed

        # Remove from pool
        del websocket_pool[channel_id]

        return {
            "status": "success",
            "channel_id": channel_id,
            "message": "WebSocket connection closed and removed from pool"
        }

    except Exception as e:
        # Remove from pool even if close failed
        if channel_id in websocket_pool:
            del websocket_pool[channel_id]

        return {
            "status": "error",
            "message": f"Error disconnecting channel: {str(e)}",
            "channel_id": channel_id
        }


@mcp.tool(description="Execute command using persistent WebSocket connection")
async def websh_channel_execute(
    channel_id: str,
    command: str,
    timeout: int = 10
) -> Dict[str, Any]:
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
                "status": "not_connected",
                "channel_id": channel_id,
                "message": "Channel not connected. Use websh_channel_connect first."
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
                "status": "connection_closed",
                "channel_id": channel_id,
                "message": "WebSocket connection was closed. Reconnect required."
            }

        # Send command
        await websocket.send(command + "\n")

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
                        if data.get("type") == "output":
                            output_lines.append(data.get("data", ""))
                    except json.JSONDecodeError:
                        output_lines.append(message)
                else:
                    output_lines.append(message)

            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                # Remove closed connection
                del websocket_pool[channel_id]
                return {
                    "status": "connection_lost",
                    "channel_id": channel_id,
                    "message": "WebSocket connection lost during execution"
                }

        return {
            "status": "success",
            "channel_id": channel_id,
            "command": command,
            "output": "".join(output_lines),
            "session_id": info['session_id']
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Command execution failed: {str(e)}",
            "channel_id": channel_id,
            "command": command
        }


@mcp.tool(description="Execute commands in Websh session via WebSocket")
async def websh_websocket_execute(
    websocket_url: str,
    command: str,
    timeout: int = 10
) -> Dict[str, Any]:
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
            await websocket.send(command + "\n")

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
                            if data.get("type") == "output":
                                output_lines.append(data.get("data", ""))
                        except json.JSONDecodeError:
                            output_lines.append(message)
                    else:
                        output_lines.append(message)

                except asyncio.TimeoutError:
                    # No more messages, command likely completed
                    break
                except websockets.exceptions.ConnectionClosed:
                    break

            return {
                "status": "success",
                "command": command,
                "output": "".join(output_lines),
                "websocket_url": websocket_url
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"WebSocket execution failed: {str(e)}",
            "command": command,
            "websocket_url": websocket_url
        }


@mcp.tool(description="Execute multiple commands in Websh session via WebSocket")
async def websh_websocket_batch_execute(
    websocket_url: str,
    commands: List[str],
    timeout: int = 30
) -> Dict[str, Any]:
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
                await websocket.send(command + "\n")

                # Collect output for each command
                output_lines = []
                start_time = asyncio.get_event_loop().time()

                while (asyncio.get_event_loop().time() - start_time) < 5:  # 5 sec per command
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)

                        if isinstance(message, bytes):
                            output_lines.append(message.decode('utf-8', errors='ignore'))
                        elif message.startswith('{"type":'):
                            try:
                                data = json.loads(message)
                                if data.get("type") == "output":
                                    output_lines.append(data.get("data", ""))
                            except json.JSONDecodeError:
                                output_lines.append(message)
                        else:
                            output_lines.append(message)

                    except asyncio.TimeoutError:
                        break
                    except websockets.exceptions.ConnectionClosed:
                        break

                results.append({
                    "command": command,
                    "output": "".join(output_lines)
                })

                # Small delay between commands
                await asyncio.sleep(0.5)

        return {
            "status": "success",
            "results": results,
            "total_commands": len(commands),
            "websocket_url": websocket_url
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"WebSocket batch execution failed: {str(e)}",
            "commands": commands,
            "websocket_url": websocket_url
        }


# Websh sessions resource
@mcp.resource(
    uri="websh://sessions/{region}/{workspace}",
    name="Websh Sessions List",
    description="Get list of Websh sessions",
    mime_type="application/json",
)
async def websh_sessions_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get Websh sessions as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Websh sessions information
    """
    sessions_data = websh_sessions_list(region=region, workspace=workspace)
    return {
        "content": sessions_data
    }
