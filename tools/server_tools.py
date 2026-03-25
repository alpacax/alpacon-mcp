"""Server management tools for Alpacon MCP server - Refactored version."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client


@mcp_tool_handler(
    description='List all servers in a workspace. Returns server names, UUIDs, status, OS, and connection info. Use this to discover available servers and obtain server IDs required by other tools.'
)
async def list_servers(workspace: str, region: str = '', **kwargs) -> dict[str, Any]:
    """Get list of servers.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server list response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to servers endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/servers/',
        token=token,
    )

    # Check if result is an error response from http_client
    if isinstance(result, dict) and 'error' in result:
        error_kwargs: dict[str, Any] = {'region': region, 'workspace': workspace}
        status_code = result.get('status_code')
        if status_code is not None:
            error_kwargs['status_code'] = status_code
        return error_response(
            result.get('message', 'Failed to get servers list'),
            **error_kwargs,
        )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific server by its UUID. Returns hostname, IP address, OS, agent version, and online status. Use this when you need full details about a single server rather than the summary list.'
)
async def get_server(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get detailed information about a specific server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

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
        endpoint='/api/servers/servers/',
        token=token,
        params={'id': server_id},
    )

    # Check if result is an error response from http_client
    if isinstance(result, dict) and 'error' in result:
        error_kwargs: dict[str, Any] = {
            'server_id': server_id,
            'region': region,
            'workspace': workspace,
        }
        status_code = result.get('status_code')
        if status_code is not None:
            error_kwargs['status_code'] = status_code
        return error_response(
            result.get('message', 'Failed to get server details'),
            **error_kwargs,
        )

    # Extract the first result from the list if results exist
    if isinstance(result, dict) and 'results' in result and len(result['results']) > 0:
        server_data = result['results'][0]
    else:
        return error_response(
            'Server not found', server_id=server_id, region=region, workspace=workspace
        )

    return success_response(
        data=server_data, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='List documentation notes attached to a server. Returns note titles, content, and timestamps. Use this to review existing server documentation or operational records.'
)
async def list_server_notes(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get list of notes for a specific server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server notes list response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to server notes endpoint with server filter
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/?server={server_id}',
        token=token,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Create a documentation note on a server with a title and content body. Use this to record operational notes, maintenance logs, or configuration documentation for a server.'
)
async def create_server_note(
    server_id: str,
    title: str,
    content: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new note for a specific server.

    Args:
        server_id: Server ID
        title: Note title
        content: Note content
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Note creation response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Prepare note data with server field
    note_data = {'server': server_id, 'title': title, 'content': content}

    # Make async call to create note
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/notes/',
        token=token,
        data=note_data,
    )

    return success_response(
        data=result,
        server_id=server_id,
        note_title=title,
        region=region,
        workspace=workspace,
    )


# ===============================
# AGENT ACTION TOOLS
# ===============================


@mcp_tool_handler(
    description='Restart the Alpacon agent on a server. Use this when the agent is unresponsive or after configuration changes.'
)
async def restart_agent(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Restart the Alpacon agent on a server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Agent restart response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'restart_agent'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Shut down the Alpacon agent on a server. The agent will stop and the server will appear offline until manually restarted.'
)
async def shutdown_agent(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Shut down the Alpacon agent on a server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Agent shutdown response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'shutdown_agent'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Upgrade the Alpacon agent on a server to the latest version. The agent will briefly restart during the upgrade.'
)
async def upgrade_agent(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Upgrade the Alpacon agent on a server to the latest version.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Agent upgrade response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'upgrade_agent'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )
