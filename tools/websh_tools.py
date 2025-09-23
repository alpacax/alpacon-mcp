"""WebSH (Web Shell) management tools for Alpacon MCP server."""

import asyncio
from typing import Dict, Any, Optional
from server import mcp
from utils.http_client import http_client
from utils.token_manager import TokenManager

# Initialize token manager
token_manager = TokenManager()


@mcp.tool(description="Create a new WebSH session")
def websh_session_create(
    server_id: str,
    username: str,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Create a new WebSH session.

    Args:
        server_id: Server ID to create session on
        username: Username for the session
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Session creation response
    """
    try:
        # Get stored token
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

        # Prepare session data with terminal size
        session_data = {
            "server": server_id,
            "username": username,
            "rows": 24,     # Terminal height
            "cols": 80      # Terminal width
        }

        # Make async call to create session
        result = asyncio.run(
            http_client.post(
                region=region,
                workspace=workspace,
                endpoint="/api/websh/sessions/",
                token=token,
                data=session_data
            )
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "username": username,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create WebSH session: {str(e)}"
        }


@mcp.tool(description="Get list of WebSH sessions")
def websh_sessions_list(
    server_id: Optional[str] = None,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Get list of WebSH sessions.

    Args:
        server_id: Optional server ID to filter sessions
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Sessions list response
    """
    try:
        # Get stored token
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

        # Prepare query parameters
        params = {}
        if server_id:
            params["server"] = server_id

        # Make async call to get sessions
        result = asyncio.run(
            http_client.get(
                region=region,
                workspace=workspace,
                endpoint="/api/websh/sessions/",
                token=token,
                params=params
            )
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
def websh_command_execute(
    session_id: str,
    command: str,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Execute a command in a WebSH session.

    Args:
        session_id: WebSH session ID
        command: Command to execute
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Command execution response
    """
    try:
        # Get stored token
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

        # Prepare command data
        command_data = {
            "command": command
        }

        # Make async call to execute command
        result = asyncio.run(
            http_client.post(
                region=region,
                workspace=workspace,
                endpoint=f"/api/websh/sessions/{session_id}/execute/",
                token=token,
                data=command_data
            )
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


@mcp.tool(description="Terminate a WebSH session")
def websh_session_terminate(
    session_id: str,
    region: str = "ap1",
    workspace: str = "alpamon"
) -> Dict[str, Any]:
    """Terminate a WebSH session.

    Args:
        session_id: WebSH session ID to terminate
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Defaults to 'alpamon'

    Returns:
        Session termination response
    """
    try:
        # Get stored token
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

        # Make async call to close session using POST to /close/ endpoint
        result = asyncio.run(
            http_client.post(
                region=region,
                workspace=workspace,
                endpoint=f"/api/websh/sessions/{session_id}/close/",
                token=token,
                data={}  # Empty data for POST request
            )
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
def websh_sessions_resource(region: str, workspace: str) -> Dict[str, Any]:
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