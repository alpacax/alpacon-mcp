"""WebSH (Web Shell) management tools for Alpacon MCP server."""

import asyncio
import json
import websockets
from typing import Dict, Any, Optional
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="Create a new WebSH session")
async def websh_session_create(
    server_id: str,
    workspace: str,
    username: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Create a new WebSH session.

    Args:
        server_id: Server ID to create session on
        username: Optional username for the session (if not provided, uses authenticated user's name)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Session creation response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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
        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "username": username or "auto",
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create WebSH session: {str(e)}"
        }


@mcp.tool(description="Get list of WebSH sessions")
async def websh_sessions_list(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get list of WebSH sessions.

    Args:
        server_id: Optional server ID to filter sessions
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Sessions list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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
        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get WebSH sessions: {str(e)}"
        }


@mcp.tool(description="Execute a command in a WebSH session")
async def websh_command_execute(
    session_id: str,
    command: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Execute a command in a WebSH session.

    Args:
        session_id: WebSH session ID
        command: Command to execute
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Command execution response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare command data
        command_data = {
            "command": command
        }

        # Make async call to execute command
        result = await http_client.post(
                region=region,
                workspace=workspace,
                endpoint=f"/api/websh/sessions/{session_id}/execute/",
                token=token,
                data=command_data
        )
        return {
            "status": "success",
            "data": result,
            "session_id": session_id,
            "command": command,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to execute WebSH command: {str(e)}"
        }


@mcp.tool(description="Create a new user channel for an existing WebSH session")
async def websh_session_reconnect(
    session_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Create a new user channel for an existing WebSH session.
    This allows reconnecting to a session that has lost its user channel connection.
    Only works for sessions created by the current user.

    Args:
        session_id: Existing WebSH session ID to reconnect to
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Reconnection response with new WebSocket URL and user channel
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # First, verify the session exists and belongs to current user
        try:
            session_info = await http_client.get(
                    region=region,
                    workspace=workspace,
                    endpoint=f"/api/websh/sessions/{session_id}/",
                    token=token
            )
        except Exception as e:
            return {
                "status": "error",
                "message": f"Session {session_id} not found or not accessible: {str(e)}"
            }

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

        return {
            "status": "success",
            "data": result,
            "session_id": session_id,
            "region": region,
            "workspace": workspace,
            "message": "New user channel created for existing session"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to reconnect to WebSH session: {str(e)}"
        }


@mcp.tool(description="Terminate a WebSH session")
async def websh_session_terminate(
    session_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Terminate a WebSH session.

    Args:
        session_id: WebSH session ID to terminate
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Session termination response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to close session using POST to /close/ endpoint
        result = await http_client.post(
                region=region,
                workspace=workspace,
                endpoint=f"/api/websh/sessions/{session_id}/close/",
                token=token,
                data={}  # Empty data for POST request
        )

        return {
            "status": "success",
            "data": result,
            "session_id": session_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to terminate WebSH session: {str(e)}"
        }


# WebSH sessions resource
@mcp.resource(
    uri="websh://sessions/{region}/{workspace}",
    name="WebSH Sessions List",
    description="Get list of WebSH sessions",
    mime_type="application/json"
)
async def websh_sessions_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get WebSH sessions as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        WebSH sessions information
    """
    sessions_data = websh_sessions_list(region=region, workspace=workspace)
    return {
        "content": sessions_data
    }


# WebSocket connection pool for persistent connections
websocket_pool = {}  # {channel_id: {'websocket': connection, 'url': url, 'session_id': id}}

# WebSocket-based tools for direct terminal interaction

@mcp.tool(description="Connect to WebSH user channel and maintain persistent connection")
async def websh_channel_connect(
    channel_id: str,
    websocket_url: str,
    session_id: str
) -> Dict[str, Any]:
    """Connect to WebSH user channel and store connection for reuse.

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


@mcp.tool(description="Execute commands in WebSH session via WebSocket")
async def websh_websocket_execute(
    websocket_url: str,
    command: str,
    timeout: int = 10
) -> Dict[str, Any]:
    """Execute a command via WebSocket connection to WebSH session.

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
                        # Parse JSON messages (WebSH protocol)
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


@mcp.tool(description="Execute multiple commands in WebSH session via WebSocket")
async def websh_websocket_batch_execute(
    websocket_url: str,
    commands: list,
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