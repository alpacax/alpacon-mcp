"""Server management tools for Alpacon MCP server."""

import asyncio
from typing import Dict, List, Any, Optional
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Get global token manager instance
token_manager = get_token_manager()


@mcp.tool(description="Get list of servers")
async def servers_list(workspace: str, region: str = "ap1") -> Dict[str, Any]:
    """Get list of servers.

    Args:
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Server list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to servers endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/servers/servers/",
            token=token
        )

        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get servers list: {str(e)}"
        }


@mcp.tool(description="Get detailed information of a specific server")
async def server_get(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get detailed information about a specific server.

    Args:
        server_id: Server ID
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Server details response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to server detail endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/servers/{server_id}/",
            token=token
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
            "message": f"Failed to get server details: {str(e)}"
        }


@mcp.tool(description="Get list of server notes")
async def server_notes_list(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get list of notes for a specific server.

    Args:
        server_id: Server ID
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Server notes list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to server notes endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/servers/{server_id}/notes/",
            token=token
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
            "message": f"Failed to get server notes: {str(e)}"
        }


@mcp.tool(description="Create a new note for server")
async def server_note_create(
    server_id: str,
    title: str,
    content: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Create a new note for a specific server.

    Args:
        server_id: Server ID
        title: Note title
        content: Note content
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Note creation response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare note data
        note_data = {
            "title": title,
            "content": content
        }

        # Make async call to create note
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint=f"/api/servers/{server_id}/notes/",
            token=token,
            data=note_data
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "note_title": title,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create server note: {str(e)}"
        }
