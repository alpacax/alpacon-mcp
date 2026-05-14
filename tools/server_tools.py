"""Server management tools for Alpacon MCP server - Refactored version."""

from typing import Any

from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY


@mcp_tool_handler(
    description=(
        'List all servers in a workspace. Returns server names, UUIDs, status, OS, and connection info. '
        'Use this to discover available servers and obtain server IDs required by other tools. '
        'Related: get_server (single server details), get_server_overview (full system info).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'server list inventory discover find all',
    },
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
    description=(
        'Get detailed information about a specific server by its UUID. Returns hostname, IP address, OS, agent version, and online status. '
        'Use this when you need full details about a single server rather than the summary list. '
        'Related: list_servers (find server UUID first), get_server_overview (includes hardware and OS details).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'server detail info status hostname IP',
    },
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
    description=(
        'List documentation notes attached to a server. Returns note titles, content, and timestamps. '
        'Use this to review existing server documentation or operational records. '
        'Related: create_server_note (add new notes).'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server notes documentation'},
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
    description=(
        'Create a documentation note on a server with a title and content body. '
        'Use this to record operational notes, maintenance logs, or configuration documentation for a server. '
        'Related: list_server_notes (view existing notes).'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'server note create documentation'},
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


@mcp_tool_handler(
    description=(
        'Get detailed information about a specific server note by its ID. '
        'Returns the note title, content, server, author, timestamps, and privacy settings. '
        'Use this when you need full details about one note. '
        'Related: list_server_notes (find note ID first), update_server_note, delete_server_note.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server note detail describe single get'},
)
async def get_server_note(
    note_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get a single server note by ID.

    Args:
        note_id: Note ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server note detail response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/{note_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get server note details',
        note_id=note_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, note_id=note_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Update an existing server note by its ID. Can change title or content. '
        'Only the fields you provide will be updated (partial update). '
        'Related: get_server_note (view existing note), delete_server_note.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server note update edit modify'},
)
async def update_server_note(
    note_id: str,
    workspace: str,
    title: str | None = None,
    content: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing server note.

    Args:
        note_id: Note ID
        workspace: Workspace name. Required parameter
        title: New title (optional)
        content: New content (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server note update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if title is not None:
        update_data['title'] = title
    if content is not None:
        update_data['content'] = content

    if not update_data:
        return format_validation_error(
            'title or content',
            None,
            'At least one of title or content must be provided.',
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/{note_id}/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update server note',
        note_id=note_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, note_id=note_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Permanently delete a server note by its ID. This action cannot be undone. '
        'Use with caution. Related: get_server_note (verify note before deleting), update_server_note.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server note delete remove'},
)
async def delete_server_note(
    note_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a server note.

    Args:
        note_id: Note ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server note delete response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/notes/{note_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to delete server note',
        note_id=note_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, note_id=note_id, region=region, workspace=workspace
    )


# ===============================
# AGENT ACTION TOOLS
# ===============================


@mcp_tool_handler(
    description=(
        'Restart the Alpacon agent process on a server. The agent will briefly go offline during restart. '
        'Use this when the agent is unresponsive or after configuration changes. Returns a command object tracking the restart operation. '
        'Related: shutdown_agent, upgrade_agent. Note: Server will briefly go offline.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'agent restart alpacon process'},
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
    description=(
        'Shut down the Alpacon agent process on a server. The server will appear offline in the workspace until the agent is manually restarted. '
        'Use with caution as remote access will be lost. Returns a command object tracking the shutdown operation. '
        'Related: restart_agent. Note: Remote access will be lost until manual restart.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'agent shutdown stop process'},
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
    description=(
        'Upgrade the Alpacon agent on a server to the latest available version. The agent will briefly restart during the upgrade process. '
        'Use this to keep agents up to date with the latest features and security patches. Returns a command object tracking the upgrade operation. '
        'Related: restart_agent. Note: Agent briefly restarts during upgrade.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'agent upgrade update version'},
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


@mcp_tool_handler(
    description=(
        'Refresh system information for a server by triggering the agent to re-collect hardware, OS, network, and package data. '
        'Use this after hardware changes or OS updates to ensure the dashboard reflects the current state. '
        'Returns a command object tracking the operation.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'refresh system info hardware OS rescan'},
)
async def update_information(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Trigger system information update on a server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Update information response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'update_information'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Upgrade all system packages on a server via the OS package manager (e.g., apt upgrade, yum update). '
        'This may take several minutes depending on the number of pending updates. Use with caution in production environments. '
        'Returns a command object tracking the upgrade operation. '
        'Related: list_system_packages (check pending updates), reboot_system (may be required after kernel updates). Note: May take several minutes.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'system packages upgrade apt yum update all'},
)
async def upgrade_system(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Upgrade all system packages on a server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        System upgrade response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'upgrade_system'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Reboot a server. The server will go offline briefly during the reboot process and reconnect automatically when the agent starts back up. '
        'Use this after kernel updates or when a full system restart is required. Returns a command object tracking the reboot operation. '
        'Related: shutdown_system (full power off), upgrade_system (often precedes reboot). Note: Server reconnects automatically.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server reboot restart machine'},
)
async def reboot_system(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Reboot a server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        System reboot response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'reboot_system'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Shut down a server completely. The server will power off and will NOT automatically reconnect. '
        'Manual intervention is required to bring the server back online. Use with extreme caution. '
        'Returns a command object tracking the shutdown operation. '
        'Related: reboot_system (use if you want the server to come back). Note: Requires manual intervention to power on again.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server shutdown power off halt'},
)
async def shutdown_system(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Shut down a server.

    Args:
        server_id: Server ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        System shutdown response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/actions/',
        token=token,
        data={'action': 'shutdown_system'},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


# ===============================
# SERVER CRUD TOOLS
# ===============================


@mcp_tool_handler(
    description=(
        'Create a new server record in a workspace. '
        'The platform must be one of: "debian", "rhel", "darwin", "windows". '
        'After creation, use get_registration_guide to get the agent installation instructions. '
        'Related: list_servers (view after creation), delete_server.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'server create add new register'},
)
async def create_server(
    workspace: str,
    name: str,
    platform: str,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new server in the workspace.

    Args:
        workspace: Workspace name. Required parameter
        name: Server name
        platform: Server platform ("debian" | "rhel" | "darwin" | "windows")
        description: Optional server description
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Created server data
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {'name': name, 'platform': platform}
    if description is not None:
        data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/servers/',
        token=token,
        data=data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Update an existing server record by its UUID. '
        'Supports partial updates: only fields you provide will be changed. '
        'Related: get_server (view current state), delete_server.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server update edit modify rename'},
)
async def update_server(
    server_id: str,
    workspace: str,
    name: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing server record.

    Args:
        server_id: Server UUID
        workspace: Workspace name. Required parameter
        name: New server name (optional)
        description: New server description (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Updated server data
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if name is not None:
        update_data['name'] = name
    if description is not None:
        update_data['description'] = description

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Permanently delete a server record from the workspace by its UUID. '
        'This action cannot be undone. The server will be removed from all listings. '
        'Related: list_servers (find server UUID first), get_server (confirm before deleting).'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server delete remove permanently'},
)
async def delete_server(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a server from the workspace.

    Args:
        server_id: Server UUID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Deletion confirmation
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/',
        token=token,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Toggle the starred/favorite status of a server. '
        'Starred servers can be quickly accessed in the workspace dashboard. '
        'Related: list_servers, get_server.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server star favorite bookmark'},
)
async def star_server(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Toggle star status on a server.

    Args:
        server_id: Server UUID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Star toggle response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/star/',
        token=token,
        data={},
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Get the sync status of a server, showing whether the agent data is up to date with the platform. '
        'Use this to check if a server is in sync after configuration changes. '
        'Related: update_information (trigger a resync), get_server.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server sync status check drift'},
)
async def get_server_sync(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get sync status for a server.

    Args:
        server_id: Server UUID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server sync status
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/sync/',
        token=token,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Get the access policy for a server, showing which users and groups have access and what permissions they hold. '
        'Related: list_server_acls (command ACLs), list_servers.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server access policy permissions who can access'},
)
async def get_server_access_policy(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the access policy for a server.

    Args:
        server_id: Server UUID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server access policy
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/access-policy/',
        token=token,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


# ===============================
# REGISTRATION TOKEN TOOLS
# ===============================


@mcp_tool_handler(
    description=(
        'List all server registration tokens in a workspace. '
        'Registration tokens are used to install the Alpacon agent on new servers. '
        'Related: create_registration_token, delete_registration_token, get_registration_guide.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'registration token list agent install'},
)
async def list_registration_tokens(
    workspace: str,
    region: str = '',
    page: int = 1,
    page_size: int = 20,
    **kwargs,
) -> dict[str, Any]:
    """List server registration tokens.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (default: 1)
        page_size: Number of results per page (default: 20)

    Returns:
        List of registration tokens
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/registration-tokens/',
        token=token,
        params={'page': page, 'page_size': page_size},
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Create a new server registration token. '
        'The token is used to authenticate the Alpacon agent during installation on a new server. '
        'After creating a token, use get_registration_guide to get the installation instructions. '
        'Related: list_registration_tokens, delete_registration_token, get_registration_guide.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'registration token create new agent install'},
)
async def create_registration_token(
    workspace: str,
    name: str,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a server registration token.

    Args:
        workspace: Workspace name. Required parameter
        name: Token name
        description: Optional token description
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Created registration token data
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {'name': name}
    if description is not None:
        data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/registration-tokens/',
        token=token,
        data=data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Delete a server registration token by its ID. '
        'This invalidates the token and prevents any future agent installations using it. '
        'Related: list_registration_tokens (find token ID first), create_registration_token.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'registration token delete remove invalidate'},
)
async def delete_registration_token(
    token_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a server registration token.

    Args:
        token_id: Registration token UUID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Deletion confirmation
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/registration-tokens/{token_id}/',
        token=token,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Get the agent installation guide for a specific platform and registration token. '
        'Returns shell commands or instructions to install the Alpacon agent on a new server. '
        'The platform must be one of: "debian", "rhel", "darwin", "windows". '
        'Related: list_registration_tokens (get token ID), create_registration_token.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'registration guide install agent setup script'},
)
async def get_registration_guide(
    workspace: str,
    platform: str,
    token_id: str,
    server_name: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get agent installation guide for a platform and registration token.

    Args:
        workspace: Workspace name. Required parameter
        platform: Target platform ("debian" | "rhel" | "darwin" | "windows")
        token_id: Registration token UUID to embed in the install script
        server_name: Optional server name to pre-configure during installation
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Installation guide with commands/instructions
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {'platform': platform, 'token': token_id}
    if server_name is not None:
        data['server_name'] = server_name

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/registration-methods/token-install/guide/?response_type=json',
        token=token,
        data=data,
    )

    return success_response(data=result, region=region, workspace=workspace)
