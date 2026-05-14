"""Security ACL tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

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
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List command ACL rules.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Command ACL rules list response
    """
    token = kwargs.get('token')

    params = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/security/command-acl/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a command ACL rule to allow or deny command execution. When to use: granting or restricting command execution permissions. Related: list_command_acls (view existing), update_command_acl (modify), delete_command_acl (remove). Note: Higher priority values take precedence.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'command acl create permission allow deny'},
)
async def create_command_acl(
    workspace: str,
    effect: str,
    command_pattern: str,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    description: str | None = None,
    priority: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a command ACL rule.

    Args:
        workspace: Workspace name. Required parameter
        effect: ACL effect - 'allow' or 'deny'
        command_pattern: Command pattern to match (e.g., 'rm -rf *', 'sudo *')
        users: List of user IDs this rule applies to (optional)
        groups: List of group IDs this rule applies to (optional)
        servers: List of server IDs this rule applies to (optional)
        description: Description of the ACL rule (optional)
        priority: Rule priority - higher values take precedence (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Command ACL creation response
    """
    token = kwargs.get('token')

    acl_data: dict[str, Any] = {
        'effect': effect,
        'command_pattern': command_pattern,
    }

    if users is not None:
        acl_data['users'] = users
    if groups is not None:
        acl_data['groups'] = groups
    if servers is not None:
        acl_data['servers'] = servers
    if description is not None:
        acl_data['description'] = description
    if priority is not None:
        acl_data['priority'] = priority

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/security/command-acl/',
        token=token,
        data=acl_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing command ACL rule. Related: list_command_acls (find rule ID).',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'command acl update modify'},
)
async def update_command_acl(
    acl_id: str,
    workspace: str,
    effect: str | None = None,
    command_pattern: str | None = None,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    description: str | None = None,
    priority: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing command ACL rule.

    Args:
        acl_id: Command ACL rule ID to update
        workspace: Workspace name. Required parameter
        effect: ACL effect - 'allow' or 'deny' (optional)
        command_pattern: Command pattern to match (optional)
        users: List of user IDs this rule applies to (optional)
        groups: List of group IDs this rule applies to (optional)
        servers: List of server IDs this rule applies to (optional)
        description: Description of the ACL rule (optional)
        priority: Rule priority (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Command ACL update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if effect is not None:
        update_data['effect'] = effect
    if command_pattern is not None:
        update_data['command_pattern'] = command_pattern
    if users is not None:
        update_data['users'] = users
    if groups is not None:
        update_data['groups'] = groups
    if servers is not None:
        update_data['servers'] = servers
    if description is not None:
        update_data['description'] = description
    if priority is not None:
        update_data['priority'] = priority

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/security/command-acl/{acl_id}/',
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
        endpoint=f'/api/security/command-acl/{acl_id}/',
        token=token,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


# ===============================
# SERVER ACL TOOLS
# ===============================


@mcp_tool_handler(
    description='List server ACL rules that control which users can access which servers. When to use: checking server access permissions. Related: create_server_acl, list_command_acls (command permissions), list_file_acls (file permissions).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'server acl access permission rules'},
)
async def list_server_acls(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List server ACL rules.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Server ACL rules list response
    """
    token = kwargs.get('token')

    params = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/security/server-acl/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a server ACL rule to control server access. When to use: granting or restricting server access for users or groups. Related: list_server_acls (view existing). Note: Higher priority values take precedence.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'server acl create permission allow deny'},
)
async def create_server_acl(
    workspace: str,
    effect: str,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    description: str | None = None,
    priority: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a server ACL rule.

    Args:
        workspace: Workspace name. Required parameter
        effect: ACL effect - 'allow' or 'deny'
        users: List of user IDs this rule applies to (optional)
        groups: List of group IDs this rule applies to (optional)
        servers: List of server IDs this rule applies to (optional)
        description: Description of the ACL rule (optional)
        priority: Rule priority - higher values take precedence (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server ACL creation response
    """
    token = kwargs.get('token')

    acl_data: dict[str, Any] = {'effect': effect}

    if users is not None:
        acl_data['users'] = users
    if groups is not None:
        acl_data['groups'] = groups
    if servers is not None:
        acl_data['servers'] = servers
    if description is not None:
        acl_data['description'] = description
    if priority is not None:
        acl_data['priority'] = priority

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/security/server-acl/',
        token=token,
        data=acl_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing server ACL rule. Related: list_server_acls (find rule ID), delete_server_acl (remove rule). Note: Higher priority values take precedence.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'server acl update modify'},
)
async def update_server_acl(
    acl_id: str,
    workspace: str,
    effect: str | None = None,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    description: str | None = None,
    priority: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing server ACL rule.

    Args:
        acl_id: Server ACL rule ID to update
        workspace: Workspace name. Required parameter
        effect: ACL effect - 'allow' or 'deny' (optional)
        users: List of user IDs this rule applies to (optional)
        groups: List of group IDs this rule applies to (optional)
        servers: List of server IDs this rule applies to (optional)
        description: Description of the ACL rule (optional)
        priority: Rule priority (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Server ACL update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if effect is not None:
        update_data['effect'] = effect
    if users is not None:
        update_data['users'] = users
    if groups is not None:
        update_data['groups'] = groups
    if servers is not None:
        update_data['servers'] = servers
    if description is not None:
        update_data['description'] = description
    if priority is not None:
        update_data['priority'] = priority

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/security/server-acl/{acl_id}/',
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
        endpoint=f'/api/security/server-acl/{acl_id}/',
        token=token,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Bulk add or remove server ACL entries in a single operation. When to use: applying multiple server ACL changes at once. Related: list_server_acls (view existing), create_server_acl (single create).',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'server acl bulk add remove multiple'},
)
async def bulk_server_acl(
    workspace: str,
    action: str,
    acl_list: list[dict],
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Bulk add or remove server ACL entries.

    Args:
        workspace: Workspace name. Required parameter
        action: Bulk action - 'add' or 'remove'
        acl_list: List of ACL entry dicts.
                  For action='add': each dict should contain keys matching create_server_acl fields (effect, users, groups, servers, etc.).
                  For action='remove': each dict should contain key 'id' (ACL rule ID to remove).
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Bulk server ACL operation response
    """
    if action not in ('add', 'remove'):
        return error_response(f"Invalid action '{action}'. Must be 'add' or 'remove'.")

    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/security/server-acl/bulk/',
        token=token,
        data={'action': action, 'acls': acl_list},
    )

    return success_response(data=result, action=action, region=region, workspace=workspace)


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
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List file ACL rules.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        File ACL rules list response
    """
    token = kwargs.get('token')

    params = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/security/file-acl/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a file ACL rule to control file access. When to use: granting or restricting file transfer permissions for specific paths. Related: list_file_acls (view existing). Note: Higher priority values take precedence.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'file acl create permission allow deny'},
)
async def create_file_acl(
    workspace: str,
    effect: str,
    file_pattern: str,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    description: str | None = None,
    priority: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a file ACL rule.

    Args:
        workspace: Workspace name. Required parameter
        effect: ACL effect - 'allow' or 'deny'
        file_pattern: File path pattern to match (e.g., '/etc/passwd', '/var/log/*')
        users: List of user IDs this rule applies to (optional)
        groups: List of group IDs this rule applies to (optional)
        servers: List of server IDs this rule applies to (optional)
        description: Description of the ACL rule (optional)
        priority: Rule priority - higher values take precedence (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        File ACL creation response
    """
    token = kwargs.get('token')

    acl_data: dict[str, Any] = {
        'effect': effect,
        'file_pattern': file_pattern,
    }

    if users is not None:
        acl_data['users'] = users
    if groups is not None:
        acl_data['groups'] = groups
    if servers is not None:
        acl_data['servers'] = servers
    if description is not None:
        acl_data['description'] = description
    if priority is not None:
        acl_data['priority'] = priority

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/security/file-acl/',
        token=token,
        data=acl_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing file ACL rule. Related: list_file_acls (find rule ID), delete_file_acl (remove rule). Note: Higher priority values take precedence.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'file acl update modify'},
)
async def update_file_acl(
    acl_id: str,
    workspace: str,
    effect: str | None = None,
    file_pattern: str | None = None,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    description: str | None = None,
    priority: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing file ACL rule.

    Args:
        acl_id: File ACL rule ID to update
        workspace: Workspace name. Required parameter
        effect: ACL effect - 'allow' or 'deny' (optional)
        file_pattern: File path pattern to match (optional)
        users: List of user IDs this rule applies to (optional)
        groups: List of group IDs this rule applies to (optional)
        servers: List of server IDs this rule applies to (optional)
        description: Description of the ACL rule (optional)
        priority: Rule priority (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        File ACL update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if effect is not None:
        update_data['effect'] = effect
    if file_pattern is not None:
        update_data['file_pattern'] = file_pattern
    if users is not None:
        update_data['users'] = users
    if groups is not None:
        update_data['groups'] = groups
    if servers is not None:
        update_data['servers'] = servers
    if description is not None:
        update_data['description'] = description
    if priority is not None:
        update_data['priority'] = priority

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/security/file-acl/{acl_id}/',
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
        endpoint=f'/api/security/file-acl/{acl_id}/',
        token=token,
    )

    return success_response(
        data=result, acl_id=acl_id, region=region, workspace=workspace
    )
