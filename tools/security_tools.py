"""Security ACL tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client

# ===============================
# COMMAND ACL TOOLS
# ===============================


@mcp_tool_handler(
    description='List command ACL rules for controlling command execution permissions'
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
    if page:
        params['page'] = page
    if page_size:
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
    description='Create a command ACL rule to allow or deny command execution'
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


@mcp_tool_handler(description='Update an existing command ACL rule')
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


@mcp_tool_handler(description='Delete a command ACL rule')
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
    description='List server ACL rules for controlling server access permissions'
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
    if page:
        params['page'] = page
    if page_size:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/security/server-acl/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(description='Create a server ACL rule to control server access')
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


# ===============================
# FILE ACL TOOLS
# ===============================


@mcp_tool_handler(
    description='List file ACL rules for controlling file access permissions'
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
    if page:
        params['page'] = page
    if page_size:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/security/file-acl/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(description='Create a file ACL rule to control file access')
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
