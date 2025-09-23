"""WebSH WebSocket connection tools for real-time terminal interaction."""

import asyncio
import websockets
import json
from typing import Dict, Any, Optional
from server import mcp
from utils.token_manager import TokenManager

# Initialize token manager
token_manager = TokenManager()


@mcp.tool(description="Execute commands in WebSH session via WebSocket")
async def websh_websocket_connect(
    session_id: str,
    websocket_url: str,
    command: str,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Connect to WebSH session via WebSocket and execute commands.

    Args:
        session_id: WebSH session ID
        websocket_url: WebSocket URL from session creation
        command: Command to execute
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Command execution response
    """
    try:
        # Get stored token for authentication
        token_info = token_manager.get_token(region, workspace)
        if not token_info:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        token = token_info.get("token")
        if not token:
            return {
                "status": "error",
                "message": f"Invalid token data for {workspace}.{region}"
            }

        # Connect to WebSocket with debugging
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        headers = {
            'Origin': f'https://{workspace}.{region}.alpacon.io',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        print(f"Connecting to: {websocket_url}")
        print(f"Headers: {headers}")

        async with websockets.connect(
            websocket_url,
            ssl=ssl_context,
            additional_headers=headers
        ) as websocket:
            print("WebSocket connected successfully!")

            # Send command character by character (like browser typing)
            full_command = command + "\n"
            for char in full_command:
                await websocket.send(char.encode('utf-8'))
                await asyncio.sleep(0.01)  # Small delay to simulate typing
            print(f"Sent command character by character: {command}")

            # Collect responses for a short time
            responses = []
            try:
                async with asyncio.timeout(3.0):
                    while True:
                        response = await websocket.recv()
                        responses.append(response)
                        if len(responses) > 50:  # Prevent infinite loop
                            break
            except asyncio.TimeoutError:
                pass

            # Return collected responses
            all_response = b''.join(resp if isinstance(resp, bytes) else resp.encode() for resp in responses)

            return {
                "status": "success",
                "session_id": session_id,
                "command": command,
                "response": all_response.decode('utf-8', errors='ignore'),
                "responses_count": len(responses),
                "region": region,
                "workspace": workspace
            }

    except websockets.exceptions.WebSocketException as e:
        return {
            "status": "error",
            "message": f"WebSocket connection error: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to execute command via WebSocket: {str(e)}"
        }


@mcp.tool(description="Generate PTY channel WebSocket URL")
def create_pty_websocket_url(websocket_url: str) -> str:
    """Convert user WebSocket URL to PTY WebSocket URL.

    User URL: /ws/websh/{sessionID}/{channelID}/{token}/
    PTY URL:  /ws/websh/{sessionID}/pty/{channelID}/{token}/
    """
    # URL format: wss://domain/ws/websh/sessionID/channelID/token/
    parts = websocket_url.split('/')
    if len(parts) >= 7 and parts[-4] == 'websh':
        # Insert 'pty' before channelID
        pty_parts = parts[:-3] + ['pty'] + parts[-3:]
        return '/'.join(pty_parts)
    return websocket_url  # Fallback


@mcp.tool(description="Create interactive WebSH connection with PTY channel via WebSocket")
async def websh_websocket_with_pty(
    session_id: str,
    websocket_url: str,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Create an interactive WebSocket connection to WebSH session with PTY channel.

    Args:
        session_id: WebSH session ID
        websocket_url: WebSocket URL from session creation
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Connection status and responses from both channels
    """
    try:
        # Get stored token for authentication
        token_info = token_manager.get_token(region, workspace)
        if not token_info:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        token = token_info.get("token")
        if not token:
            return {
                "status": "error",
                "message": f"Invalid token data for {workspace}.{region}"
            }

        # Connect to WebSocket directly (URL already contains auth token)
        async with websockets.connect(websocket_url) as websocket:
            # Send initial connection message
            await websocket.send(json.dumps({
                "type": "connect",
                "session_id": session_id
            }))

            # Receive initial response
            initial_response = await websocket.recv()

            # Send a test command character by character
            test_command = "whoami\n"
            for char in test_command:
                await websocket.send(char.encode('utf-8'))
                await asyncio.sleep(0.01)

            # Collect responses for 2 seconds
            responses = []
            try:
                async with asyncio.timeout(2.0):
                    while True:
                        response = await websocket.recv()
                        responses.append(response)
            except asyncio.TimeoutError:
                pass

            return {
                "status": "success",
                "session_id": session_id,
                "initial_response": initial_response,
                "command_responses": responses,
                "region": region,
                "workspace": workspace
            }

    except websockets.exceptions.WebSocketException as e:
        return {
            "status": "error",
            "message": f"WebSocket connection error: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to establish interactive WebSocket connection: {str(e)}"
        }


# Wrapper function for synchronous execution
def websh_execute_via_websocket(
    session_id: str,
    websocket_url: str,
    command: str,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Synchronous wrapper for WebSocket command execution.

    Args:
        session_id: WebSH session ID
        websocket_url: WebSocket URL from session creation
        command: Command to execute
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Command execution response
    """
    return asyncio.run(websh_websocket_connect(
        session_id=session_id,
        websocket_url=websocket_url,
        command=command,
        region=region,
        workspace=workspace
    ))