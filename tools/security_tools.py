"""Security ACL tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

VALID_BULK_ACTIONS = ('add', 'remove')
_BULK_ACTIONS_STR = ', '.join(f"'{a}'" for a in VALID_BULK_ACTIONS)
VALID_FILE_ACL_ACTIONS = ('upload', 'download', '*')
_FILE_ACL_ACTIONS_STR = ', '.join(f"'{a}'" for a in VALID_FILE_ACL_ACTIONS)

_API_COMMAND_ACL = '/api/security/command-acl/'
_API_SERVER_ACL = '/api/security/server-acl/'
_API_FILE_ACL = '/api/security/file-acl/'
_API_SERVER_ACL_BULK = f'{_API_SERVER_ACL}bulk/'
_API_SERVER_ACL_BULK_DELETE = f'{_API_SERVER_ACL}bulk/delete/'

# Mirrors the server-side bulk serializer cap (servers list max_length=100)
_BULK_MAX_SERVERS = 100

_BOTH_TOKENS_ERROR = 'Provide either api_token_id or service_token_id, not both'
_TOKEN_REQUIRED_ERROR = 'Either api_token_id or service_token_id must be provided'


# ===============================
# COMMAND ACL TOOLS
# ===============================


@mcp_tool_handler(
    description='List command ACL rules that control which commands can be executed. When to use: checking command execution permissions or debugging 403 errors from execute_command. Related: create_command_acl (add rules), list_server_acls (server access rules), list_file_acls (file access rules).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'command acl permission rules security'},
)
async def list_command_acls(
    workspace: str,
    region: str = '',
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List command ACL rules.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        api_token_id: Filter by API token ID (optional)
        service_token_id: Filter by service token ID (optional)
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Command ACL rules list response
    """
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if api_token_id is not None:
        params['api_token'] = api_token_id
    if service_token_id is not None:
        params['service_token'] = service_token_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_COMMAND_ACL,
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a command ACL rule to allow a token to execute specific commands. When to use: granting command execution permissions to an API or service token. Related: list_command_acls (view existing), update_command_acl (modify), delete_command_acl (remove).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'command acl create permission allow deny'},
)
async def create_command_acl(
    workspace: str,
    command: str,
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    username: str = '',
    groupname: str = '',
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a command ACL rule.

    Exactly one of api_token_id or service_token_id must be provided.

    Args:
        workspace: Workspace name. Required parameter
        command: Command pattern to allow (e.g., 'docker *', 'ls -la'). Wildcards (*) supported
        api_token_id: API token ID this rule applies to (mutually exclusive with service_token_id)
        service_token_id: Service token ID this rule applies to (mutually exclusive with api_token_id)
        username: System username restriction. Empty = token owner only, '*' = any user (optional)
        groupname: System groupname restriction. Empty = no restriction (any group), exact name to restrict (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Command ACL creation response
    """
    if api_token_id is None and service_token_id is None:
        return error_response(_TOKEN_REQUIRED_ERROR)
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    acl_data: dict[str, Any] = {
        'command': command,
        'username': username,
        'groupname': groupname,
    }
    if api_token_id is not None:
        acl_data['token'] = api_token_id
    else:
        acl_data['service_token'] = service_token_id

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_COMMAND_ACL,
        token=token,
        data=acl_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing command ACL rule. Related: list_command_acls (find rule ID), delete_command_acl (remove rule).',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'command acl update modify'},
)
async def update_command_acl(
    acl_id: str,
    workspace: str,
    command: str | None = None,
    username: str | None = None,
    groupname: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing command ACL rule.

    Note: This tool does not support changing the token binding. Delete and recreate to rebind to a different token.

    Args:
        acl_id: Command ACL rule ID to update
        workspace: Workspace name. Required parameter
        command: Command pattern to allow (optional)
        username: System username restriction. Pass '' explicitly to clear an existing restriction; omit to leave unchanged (optional)
        groupname: System groupname restriction. Pass '' explicitly to clear an existing restriction; omit to leave unchanged (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Command ACL update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if command is not None:
        update_data['command'] = command
    if username is not None:
        update_data['username'] = username
    if groupname is not None:
        update_data['groupname'] = groupname

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_COMMAND_ACL}{acl_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Delete a command ACL rule permanently. Related: list_command_acls (find rule ID), update_command_acl (modify instead). Note: Cannot be undone.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'command acl delete remove'},
)
async def delete_command_acl(
    acl_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a command ACL rule.

    Args:
        acl_id: Command ACL rule ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Command ACL deletion response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_COMMAND_ACL}{acl_id}/',
        token=token,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


# ===============================
# SERVER ACL TOOLS
# ===============================


@mcp_tool_handler(
    description='List server ACL rules that control which servers a token can access. When to use: checking server access permissions. Related: create_server_acl, list_command_acls (command permissions), list_file_acls (file permissions).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server acl access permission rules'},
)
async def list_server_acls(
    workspace: str,
    region: str = '',
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List server ACL rules.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        api_token_id: Filter by API token ID (optional)
        service_token_id: Filter by service token ID (optional)
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Server ACL rules list response
    """
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if api_token_id is not None:
        params['api_token'] = api_token_id
    if service_token_id is not None:
        params['service_token'] = service_token_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_SERVER_ACL,
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a server ACL rule granting a token access to a specific server. When to use: allowing an API or service token to execute commands on a server. Related: list_server_acls (view existing), bulk_server_acl (add multiple at once).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'server acl create permission allow access'},
)
async def create_server_acl(
    workspace: str,
    server_id: str,
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a server ACL rule.

    Exactly one of api_token_id or service_token_id must be provided.
    Each rule grants the token access to exactly one server.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Server UUID to grant access to
        api_token_id: API token ID to grant access (mutually exclusive with service_token_id)
        service_token_id: Service token ID to grant access (mutually exclusive with api_token_id)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server ACL creation response
    """
    if api_token_id is None and service_token_id is None:
        return error_response(_TOKEN_REQUIRED_ERROR)
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    acl_data: dict[str, Any] = {'server': server_id}
    if api_token_id is not None:
        acl_data['token'] = api_token_id
    else:
        acl_data['service_token'] = service_token_id

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_SERVER_ACL,
        token=token,
        data=acl_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing server ACL rule. Related: list_server_acls (find rule ID), delete_server_acl (remove rule).',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server acl update modify'},
)
async def update_server_acl(
    acl_id: str,
    workspace: str,
    server_id: str | None = None,
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing server ACL rule.

    Note: Token binding can be updated by providing api_token_id or service_token_id.

    Args:
        acl_id: Server ACL rule ID to update
        workspace: Workspace name. Required parameter
        server_id: New server UUID (optional)
        api_token_id: New API token ID to rebind this rule to (optional)
        service_token_id: New service token ID to rebind this rule to (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server ACL update response
    """
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if server_id is not None:
        update_data['server'] = server_id
    # When rebinding, null the opposing field explicitly: the server enforces
    # exactly-one-token-type, and PATCH keeps the old binding otherwise.
    if api_token_id is not None:
        update_data['token'] = api_token_id
        update_data['service_token'] = None
    if service_token_id is not None:
        update_data['service_token'] = service_token_id
        update_data['token'] = None

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SERVER_ACL}{acl_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Delete a server ACL rule permanently. Related: list_server_acls (find rule ID), update_server_acl (modify instead). Note: Cannot be undone.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server acl delete remove'},
)
async def delete_server_acl(
    acl_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a server ACL rule.

    Args:
        acl_id: Server ACL rule ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server ACL deletion response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SERVER_ACL}{acl_id}/',
        token=token,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Bulk add or remove server ACL entries for multiple servers in a single operation. When to use: applying the same token access to many servers at once. Related: list_server_acls (view existing), create_server_acl (single create).',
    # Annotations are fixed at decorator-time; the destructive 'remove' path dominates.
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server acl bulk add remove multiple'},
)
async def bulk_server_acl(
    workspace: str,
    action: str,
    server_ids: list[str],
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Bulk add or remove server ACL entries.

    Exactly one of api_token_id or service_token_id must be provided.

    Args:
        workspace: Workspace name. Required parameter
        action: Bulk action - 'add' (grant access) or 'remove' (revoke access)
        server_ids: List of server UUIDs to add or remove access for (1-100 items)
        api_token_id: API token ID to operate on (mutually exclusive with service_token_id)
        service_token_id: Service token ID to operate on (mutually exclusive with api_token_id)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Bulk server ACL operation response
    """
    if action not in VALID_BULK_ACTIONS:
        return error_response(
            f"Invalid action '{action}'. Must be one of: {_BULK_ACTIONS_STR}."
        )
    if not server_ids:
        return error_response('server_ids must not be empty')
    if len(server_ids) > _BULK_MAX_SERVERS:
        return error_response(
            f'server_ids must contain at most {_BULK_MAX_SERVERS} items'
        )
    if api_token_id is None and service_token_id is None:
        return error_response(_TOKEN_REQUIRED_ERROR)
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    body: dict[str, Any] = {'servers': server_ids}
    if api_token_id is not None:
        body['token'] = api_token_id
    else:
        body['service_token'] = service_token_id

    endpoint = _API_SERVER_ACL_BULK if action == 'add' else _API_SERVER_ACL_BULK_DELETE

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=endpoint,
        token=token,
        data=body,
    )

    return success_response(
        data=result, action=action, region=region, workspace=workspace
    )


# ===============================
# FILE ACL TOOLS
# ===============================


@mcp_tool_handler(
    description='List file ACL rules that control file access permissions (WebFTP). When to use: checking file transfer permissions. Related: create_file_acl, list_command_acls (command permissions), list_server_acls (server permissions).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'file acl access permission rules path'},
)
async def list_file_acls(
    workspace: str,
    region: str = '',
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List file ACL rules.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        api_token_id: Filter by API token ID (optional)
        service_token_id: Filter by service token ID (optional)
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        File ACL rules list response
    """
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if api_token_id is not None:
        params['api_token'] = api_token_id
    if service_token_id is not None:
        params['service_token'] = service_token_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_FILE_ACL,
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a file ACL rule to control file upload/download access. When to use: granting or restricting file transfer permissions for specific paths. Related: list_file_acls (view existing), update_file_acl (modify), delete_file_acl (remove).',
    annotations=ADDITIVE,
    meta={
        'anthropic/searchHint': 'file acl create permission allow deny path upload download'
    },
)
async def create_file_acl(
    workspace: str,
    path: str,
    action: str,
    api_token_id: str | None = None,
    service_token_id: str | None = None,
    username: str = '',
    groupname: str = '',
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a file ACL rule.

    Exactly one of api_token_id or service_token_id must be provided.

    Args:
        workspace: Workspace name. Required parameter
        path: File path pattern to match (e.g., '/etc/nginx/*', '/var/log/*.log'). Wildcards (*) supported
        action: Allowed action - 'upload', 'download', or '*' (both)
        api_token_id: API token ID this rule applies to (mutually exclusive with service_token_id)
        service_token_id: Service token ID this rule applies to (mutually exclusive with api_token_id)
        username: System username restriction. Empty = token owner only, '*' = any user (optional)
        groupname: System groupname restriction. Empty = no restriction (any group), exact name to restrict (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        File ACL creation response
    """
    if action not in VALID_FILE_ACL_ACTIONS:
        return error_response(
            f"Invalid action '{action}'. Must be one of: {_FILE_ACL_ACTIONS_STR}."
        )
    if api_token_id is None and service_token_id is None:
        return error_response(_TOKEN_REQUIRED_ERROR)
    if api_token_id is not None and service_token_id is not None:
        return error_response(_BOTH_TOKENS_ERROR)

    token = kwargs.get('token')

    acl_data: dict[str, Any] = {
        'path': path,
        'action': action,
        'username': username,
        'groupname': groupname,
    }
    if api_token_id is not None:
        acl_data['token'] = api_token_id
    else:
        acl_data['service_token'] = service_token_id

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_FILE_ACL,
        token=token,
        data=acl_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing file ACL rule. Related: list_file_acls (find rule ID), delete_file_acl (remove rule).',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'file acl update modify path action'},
)
async def update_file_acl(
    acl_id: str,
    workspace: str,
    path: str | None = None,
    action: str | None = None,
    username: str | None = None,
    groupname: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing file ACL rule.

    Note: This tool does not support changing the token binding. Delete and recreate to rebind to a different token.

    Args:
        acl_id: File ACL rule ID to update
        workspace: Workspace name. Required parameter
        path: New file path pattern (optional)
        action: New allowed action - 'upload', 'download', or '*' (optional)
        username: System username restriction. Pass '' explicitly to clear an existing restriction; omit to leave unchanged (optional)
        groupname: System groupname restriction. Pass '' explicitly to clear an existing restriction; omit to leave unchanged (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        File ACL update response
    """
    if action is not None and action not in VALID_FILE_ACL_ACTIONS:
        return error_response(
            f"Invalid action '{action}'. Must be one of: {_FILE_ACL_ACTIONS_STR}."
        )

    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if path is not None:
        update_data['path'] = path
    if action is not None:
        update_data['action'] = action
    if username is not None:
        update_data['username'] = username
    if groupname is not None:
        update_data['groupname'] = groupname

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_FILE_ACL}{acl_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Delete a file ACL rule permanently. Related: list_file_acls (find rule ID), update_file_acl (modify instead). Note: Cannot be undone.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'file acl delete remove'},
)
async def delete_file_acl(
    acl_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a file ACL rule.

    Args:
        acl_id: File ACL rule ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        File ACL deletion response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_FILE_ACL}{acl_id}/',
        token=token,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )
