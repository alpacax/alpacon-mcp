"""Server management tools for Alpacon MCP server - Refactored version."""

from typing import Dict, Any
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler


@mcp_tool_handler(description="Get list of servers")
async def list_servers(workspace: str, region: str = "ap1", **kwargs) -> Dict[str, Any]:
    """Get list of servers.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Server list response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to servers endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/servers/servers/",
        token=token
    )

    # Check if result is an error response from http_client
    if isinstance(result, dict) and "error" in result:
        return error_response(
            result.get("message", "Failed to get servers list"),
            region=region,
            workspace=workspace
        )

    return success_response(
        data=result,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get detailed information of a specific server")
async def get_server(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get detailed information about a specific server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Server details response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to server detail endpoint
    # Use servers/servers/ endpoint with ID filter instead of direct ID endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/servers/servers/",
        token=token,
        params={"id": server_id}
    )

    # Check if result is an error response from http_client
    if isinstance(result, dict) and "error" in result:
        return error_response(
            result.get("message", "Failed to get server details"),
            server_id=server_id,
            region=region,
            workspace=workspace
        )

    # Extract the first result from the list if results exist
    if isinstance(result, dict) and "results" in result and len(result["results"]) > 0:
        server_data = result["results"][0]
    else:
        return error_response(
            "Server not found",
            server_id=server_id,
            region=region,
            workspace=workspace
        )

    return success_response(
        data=server_data,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get list of server notes")
async def list_server_notes(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get list of notes for a specific server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Server notes list response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to server notes endpoint with server filter
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f"/api/servers/notes/?server={server_id}",
        token=token
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Create a new note for server")
async def create_server_note(
    server_id: str,
    title: str,
    content: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Create a new note for a specific server.

    Args:
        server_id: Server ID
        title: Note title
        content: Note content
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Note creation response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Prepare note data with server field
    note_data = {
        "server": server_id,
        "title": title,
        "content": content
    }

    # Make async call to create note
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint="/api/servers/notes/",
        token=token,
        data=note_data
    )

    return success_response(
        data=result,
        server_id=server_id,
        note_title=title,
        region=region,
        workspace=workspace
    )