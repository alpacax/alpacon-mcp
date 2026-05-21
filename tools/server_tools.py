"""Server management tools for Alpacon MCP server - Refactored version."""

from typing import Any

from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error, validate_server_id_format
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

VALID_PLATFORMS = frozenset({'debian', 'rhel', 'darwin', 'windows'})
_PLATFORM_LIST_STR = ', '.join(f'"{p}"' for p in sorted(VALID_PLATFORMS))


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


@mcp_tool_handler(
    description=(
        "Rename or relabel a host's Alpacon entry (`name`, `description`) by UUID. "
        'Use when a server is re-purposed or moved between teams—this updates the '
        'fleet-inventory metadata only. '
        'Related: get_server (view current state), unregister_server.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server update edit modify rename relabel'},
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

    if not update_data:
        return format_validation_error(
            'name or description',
            None,
            'At least one of name or description must be provided.',
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update server',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Unregister a host from this workspace by UUID. The host is removed from '
        'all listings and no new Work Sessions can target it, but the Alpamon agent '
        'on the host keeps running until uninstalled. Cannot be undone by this '
        'tool—re-enrolling the host requires running the install script with a '
        'registration token again. '
        'Related: list_servers (find UUID), get_server (confirm before unregistering).'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server unregister deregister delete remove'},
)
async def unregister_server(
    server_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Unregister a server from the workspace.

    Args:
        server_id: Server UUID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Unregister confirmation
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to unregister server',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Pin or unpin a server for the caller for faster access—a personal-preference '
        'flag, not a fleet-wide setting. Does not change visibility, RBAC, or ACLs '
        'for any other principal. Use `status=True` to pin, `False` to unpin. '
        'Related: list_servers (the unfiltered inventory).'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server star pin favorite bookmark personalization'},
)
async def star_server(
    server_id: str, status: bool, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Set star status on a server.

    Args:
        server_id: Server UUID
        status: True to star, False to unstar
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Star update response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/star/',
        token=token,
        data={'status': status},
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update server star status',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'List Alpamon registration tokens issued in this workspace—credentials '
        'embedded in the install script to authenticate a host on first run. '
        'Returns token IDs, names, and creation metadata. Use before issuing new '
        'tokens or rotating compromised ones. '
        'Related: create_registration_token, delete_registration_token, get_registration_guide.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'registration token list alpamon install'},
)
async def list_registration_tokens(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List server registration tokens.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of results per page (optional)

    Returns:
        List of registration tokens
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/registration-tokens/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list registration tokens',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Mint a new Alpamon registration token for installing the agent on a new '
        'host. The returned token is embedded in the install script '
        '(get_registration_guide). Name the token per cohort/batch '
        '(e.g., `prod-web-2026-q2`) for clean rotation later. '
        'Related: list_registration_tokens, delete_registration_token, get_registration_guide.'
    ),
    annotations=ADDITIVE,
    meta={
        'anthropic/searchHint': 'registration token create mint issue alpamon install new host'
    },
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

    err = unwrap_http_result(
        result,
        default_message='Failed to create registration token',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Revoke an Alpamon registration token by ID. Already-enrolled hosts keep '
        'working—this only blocks future enrollments using the same token. Use to '
        'rotate after a suspected token leak or when a rollout cohort is complete. '
        'Related: list_registration_tokens (find token ID first), create_registration_token.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'registration token delete revoke rotate invalidate'},
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

    err = _validate_token_id(token_id)
    if err:
        return err

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/registration-tokens/{token_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to delete registration token',
        token_id=token_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, token_id=token_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Get the platform-specific Alpamon install script for a registration token. '
        'Returns the exact shell commands an Operator runs on the target host to '
        "bring it under Alpacon's control plane. "
        f'The `platform` must be one of: {_PLATFORM_LIST_STR}. '
        'Optionally pre-name the host via `server_name`. '
        'Related: list_registration_tokens (get token ID), create_registration_token.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'registration guide install script alpamon setup operator'
    },
)
async def get_registration_guide(
    token_id: str,
    workspace: str,
    platform: str,
    server_name: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get agent installation guide for a platform and registration token.

    Args:
        token_id: Registration token UUID to embed in the install script
        workspace: Workspace name. Required parameter
        platform: Target platform ("debian" | "rhel" | "darwin" | "windows")
        server_name: Optional server name to pre-configure during installation
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Installation guide with commands/instructions
    """
    token = kwargs.get('token')

    err = _validate_token_id(token_id)
    if err:
        return err
    err = _validate_platform(platform)
    if err:
        return err

    data: dict[str, Any] = {'platform': platform, 'token': token_id}
    if server_name is not None:
        data['server_name'] = server_name

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/servers/registration-methods/token-install/guide/',
        token=token,
        data=data,
        params={'response_type': 'json'},
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get registration guide',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


def _validate_platform(platform: str) -> dict[str, Any] | None:
    if platform not in VALID_PLATFORMS:
        return format_validation_error(
            'platform',
            platform,
            f'Must be one of: {", ".join(sorted(VALID_PLATFORMS))}',
        )
    return None


def _validate_token_id(token_id: str) -> dict[str, Any] | None:
    if not validate_server_id_format(token_id):
        return format_validation_error(
            'token_id',
            token_id,
            'Must be a valid UUID. Example: 550e8400-e29b-41d4-a716-446655440000',
        )
    return None
