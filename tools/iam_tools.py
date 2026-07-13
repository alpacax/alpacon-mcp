"""IAM (Identity and Access Management) tools for Alpacon MCP server."""

import re
from typing import Unpack

from utils.api_types import ToolKwargs, ToolResponse
from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error, validate_server_id_format
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

VALID_MEMBERSHIP_ROLES = frozenset({'member', 'manager', 'owner'})
VALID_SERVICE_TYPES = frozenset({'ci_cd', 'monitoring', 'automation', 'integration'})
GROUP_NAME_PATTERN = re.compile(r'^[a-z0-9_-]+$')


def _validate_uuid(field: str, value: str) -> ToolResponse | None:
    if not validate_server_id_format(value):
        return format_validation_error(
            field,
            value,
            'Must be a valid UUID. Example: 550e8400-e29b-41d4-a716-446655440000',
        )
    return None


# ===============================
# USER MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='List all IAM users in a workspace. Returns username, email, active status, and group count (num_groups) for each user. Supports pagination for large user lists. Related: get_iam_user (details), create_iam_user, list_system_users (OS-level users, not IAM).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam users list workspace identity access'},
)
async def list_iam_users(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List all IAM users in workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of users per page (optional)

    Returns:
        IAM users list response
    """
    token = kwargs.get('token')

    params: dict[str, object] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list IAM users',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific IAM user by their user ID. Returns email, first/last name, active status, and group count (num_groups). Use list_iam_memberships to see which groups the user belongs to. Use this when you need full profile details for a single user.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam user detail profile'},
)
async def get_iam_user(
    user_id: str, workspace: str, region: str = '', **kwargs: Unpack[ToolKwargs]
) -> ToolResponse:
    """Get detailed information about a specific IAM user.

    Group memberships are not included in the user payload (the user
    serializer has no groups field); use list_iam_memberships to look up
    the groups a user belongs to.

    Args:
        user_id: IAM user ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM user details response
    """
    err = _validate_uuid('user_id', user_id)
    if err:
        return err

    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/users/{user_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get IAM user',
        user_id=user_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, user_id=user_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Create a new IAM user account in the workspace. Requires username and email. Optionally set first/last name. The user is active by default. Use add_iam_member to assign the user to groups after creation. Related: update_iam_user, delete_iam_user, add_iam_member.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam user create add new account'},
)
async def create_iam_user(
    username: str,
    email: str,
    workspace: str,
    first_name: str | None = None,
    last_name: str | None = None,
    is_active: bool = True,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Create a new IAM user.

    Group assignment is handled separately via add_iam_member
    (the user serializer has no groups field).

    Args:
        username: Username for the new user
        email: Email address for the new user
        workspace: Workspace name. Required parameter
        first_name: First name (optional)
        last_name: Last name (optional)
        is_active: Whether user is active (default: True)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        User creation response
    """
    token = kwargs.get('token')

    user_data: dict[str, object] = {
        'username': username,
        'email': email,
        'is_active': is_active,
    }

    if first_name is not None:
        user_data['first_name'] = first_name
    if last_name is not None:
        user_data['last_name'] = last_name

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/',
        token=token,
        data=user_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to create IAM user',
        username=username,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, username=username, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Update an existing IAM user profile. Can change email, first/last name, or active/inactive status. Only the fields you provide will be updated (partial update). Use add_iam_member/remove_iam_member to change group memberships.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'iam user update modify edit'},
)
async def update_iam_user(
    user_id: str,
    workspace: str,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    is_active: bool | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Update an existing IAM user.

    Group membership changes are handled separately via
    add_iam_member/remove_iam_member (the user serializer has no groups field).

    Args:
        user_id: IAM user ID to update
        workspace: Workspace name. Required parameter
        email: New email address (optional)
        first_name: New first name (optional)
        last_name: New last name (optional)
        is_active: New active status (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        User update response
    """
    err = _validate_uuid('user_id', user_id)
    if err:
        return err

    token = kwargs.get('token')

    update_data: dict[str, object] = {}
    if email is not None:
        update_data['email'] = email
    if first_name is not None:
        update_data['first_name'] = first_name
    if last_name is not None:
        update_data['last_name'] = last_name
    if is_active is not None:
        update_data['is_active'] = is_active

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/users/{user_id}/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update IAM user',
        user_id=user_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, user_id=user_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Permanently delete an IAM user account from the workspace. This action cannot be undone. Use update_iam_user to deactivate a user instead if you want to preserve the account.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam user delete remove'},
)
async def delete_iam_user(
    user_id: str, workspace: str, region: str = '', **kwargs: Unpack[ToolKwargs]
) -> ToolResponse:
    """Delete an IAM user.

    Args:
        user_id: IAM user ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        User deletion response
    """
    err = _validate_uuid('user_id', user_id)
    if err:
        return err

    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/users/{user_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to delete IAM user',
        user_id=user_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, user_id=user_id, region=region, workspace=workspace
    )


# ===============================
# GROUP MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='List all IAM permission groups in a workspace. Returns group names, descriptions, and member information. Supports pagination for large group lists. Related: create_iam_group, list_system_groups (OS-level groups, not IAM).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam groups list workspace'},
)
async def list_iam_groups(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List all IAM groups in workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of groups per page (optional)

    Returns:
        IAM groups list response
    """
    token = kwargs.get('token')

    params: dict[str, object] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/groups/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list IAM groups',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a new IAM permission group in the workspace. Requires a group name (lowercase letters, digits, hyphens, and underscores only). Optionally set a display name and description. Users can then be added to this group via add_iam_member.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam group create add new'},
)
async def create_iam_group(
    name: str,
    workspace: str,
    display_name: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Create a new IAM group.

    Args:
        name: Name for the new group (lowercase letters, digits, hyphens, and underscores only)
        workspace: Workspace name. Required parameter
        display_name: Human-readable display name (optional)
        description: Description of the group (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Group creation response
    """
    if not GROUP_NAME_PATTERN.match(name):
        return format_validation_error(
            'name',
            name,
            'Must contain only lowercase letters, digits, hyphens, and underscores',
        )

    token = kwargs.get('token')

    group_data: dict[str, object] = {'name': name}

    if display_name is not None:
        group_data['display_name'] = display_name
    if description is not None:
        group_data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/groups/',
        token=token,
        data=group_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to create IAM group',
        group_name=name,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, group_name=name, region=region, workspace=workspace
    )


# ===============================
# NOTE: Role and Permission management endpoints are not implemented in the server
# The following sections have been removed:
# - ROLE MANAGEMENT TOOLS (list_iam_roles, assign_iam_user_role)
# - PERMISSION MANAGEMENT TOOLS (list_iam_permissions, get_iam_user_permissions)
# ===============================


# ===============================
# EXTENDED GROUP MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='Get detailed information about a specific IAM group by its group ID. Returns group name, display name, description, member count (num_members), and member names. Related: list_iam_groups (all groups), update_iam_group, delete_iam_group.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam group detail get'},
)
async def get_iam_group(
    group_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Get IAM group details.

    Args:
        group_id: Group ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM group detail response
    """
    err = _validate_uuid('group_id', group_id)
    if err:
        return err

    token = kwargs.get('token')
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/groups/{group_id}/',
        token=token,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to get IAM group',
        group_id=group_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, group_id=group_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Update an existing IAM group. Can change the display name or description (the group name itself is immutable on the server). Only the fields you provide will be updated (partial update). Related: get_iam_group, delete_iam_group.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'iam group update modify edit'},
)
async def update_iam_group(
    group_id: str,
    workspace: str,
    display_name: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Update an existing IAM group.

    The group name is read-only on the server (GroupUpdateSerializer);
    only display_name and description are exposed here.

    Args:
        group_id: Group ID to update
        workspace: Workspace name. Required parameter
        display_name: New display name (optional)
        description: New group description (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM group update response
    """
    err = _validate_uuid('group_id', group_id)
    if err:
        return err

    token = kwargs.get('token')

    update_data: dict[str, object] = {}
    if display_name is not None:
        update_data['display_name'] = display_name
    if description is not None:
        update_data['description'] = description

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/groups/{group_id}/',
        token=token,
        data=update_data,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to update IAM group',
        group_id=group_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, group_id=group_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Permanently delete an IAM group from the workspace. This action cannot be undone. Users in the group will lose group-based permissions. Related: get_iam_group, list_iam_groups.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam group delete remove'},
)
async def delete_iam_group(
    group_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Delete an IAM group.

    Args:
        group_id: Group ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM group deletion response
    """
    err = _validate_uuid('group_id', group_id)
    if err:
        return err

    token = kwargs.get('token')
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/groups/{group_id}/',
        token=token,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to delete IAM group',
        group_id=group_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, group_id=group_id, region=region, workspace=workspace
    )


# ===============================
# MEMBERSHIP MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='List IAM group memberships in the workspace. Optionally filter by group ID to see members of a specific group. Supports pagination. Related: add_iam_member, remove_iam_member.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam memberships list group members'},
)
async def list_iam_memberships(
    workspace: str,
    group_id: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List IAM group memberships.

    Args:
        workspace: Workspace name. Required parameter
        group_id: Filter by group ID (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of memberships per page (optional)

    Returns:
        IAM memberships list response
    """
    if group_id is not None:
        err = _validate_uuid('group_id', group_id)
        if err:
            return err

    token = kwargs.get('token')

    params: dict[str, object] = {}
    if group_id is not None:
        params['group'] = group_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/memberships/',
        token=token,
        params=params,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to list IAM memberships',
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Add a user to an IAM group by creating a membership. Requires both group ID and user ID. Optionally set the role (member, manager, or owner; default member). Related: remove_iam_member, list_iam_memberships.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam member add group user membership'},
)
async def add_iam_member(
    group_id: str,
    user_id: str,
    workspace: str,
    role: str = 'member',
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Add a user to an IAM group.

    Args:
        group_id: Group ID to add the user to
        user_id: User ID to add to the group
        workspace: Workspace name. Required parameter
        role: Role in the group: member, manager, or owner (default: member)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM membership creation response
    """
    err = _validate_uuid('group_id', group_id) or _validate_uuid('user_id', user_id)
    if err:
        return err
    if role not in VALID_MEMBERSHIP_ROLES:
        return format_validation_error(
            'role',
            role,
            f'Must be one of: {", ".join(sorted(VALID_MEMBERSHIP_ROLES))}',
        )

    token = kwargs.get('token')
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/memberships/',
        token=token,
        data={'group': group_id, 'user': user_id, 'role': role},
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to add IAM member',
        group_id=group_id,
        user_id=user_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result,
        group_id=group_id,
        user_id=user_id,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Remove a user from an IAM group by deleting a membership record. Requires the membership ID (not user or group ID). Use list_iam_memberships to find the membership ID. Related: add_iam_member, list_iam_memberships.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam member remove group user membership delete'},
)
async def remove_iam_member(
    membership_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Remove a user from an IAM group.

    Args:
        membership_id: Membership ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM membership deletion response
    """
    err = _validate_uuid('membership_id', membership_id)
    if err:
        return err

    token = kwargs.get('token')
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/memberships/{membership_id}/',
        token=token,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to remove IAM member',
        membership_id=membership_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result,
        membership_id=membership_id,
        region=region,
        workspace=workspace,
    )


# ===============================
# WORKSPACE INVITATION TOOLS
# ===============================


@mcp_tool_handler(
    description='Send an email invitation to join the workspace. Requires only the target email address; the invitee does not need an existing IAM user record. Available on Auth0-enabled (cloud) deployments only. Related: list_iam_users, create_iam_user.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'workspace user invite email send'},
)
async def invite_workspace_user(
    email: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Invite a user to the workspace by email.

    Sends an Auth0 organization invitation and records a pending
    InvitedUser entry. The invitee is identified by email only.

    Args:
        email: Email address to send the invitation to
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Invitation response
    """
    token = kwargs.get('token')
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/users/invite/',
        token=token,
        data={'email': email},
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to invite workspace user',
        email=email,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, email=email, region=region, workspace=workspace
    )


# ===============================
# APPLICATION MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='List all IAM applications (machine service accounts for CI/CD, monitoring, automation, or external integrations) in the workspace. Supports pagination. Related: create_iam_application, get_iam_application.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam applications list service accounts oauth'},
)
async def list_iam_applications(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List all IAM applications in the workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of applications per page (optional)

    Returns:
        IAM applications list response
    """
    token = kwargs.get('token')

    params: dict[str, object] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/applications/',
        token=token,
        params=params,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to list IAM applications',
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a new IAM application (machine service account) in the workspace. Requires a name. Optionally set a description and service type (ci_cd, monitoring, automation, or integration; default integration). Related: list_iam_applications, get_iam_application, assign_application_system_users.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam application create new service account'},
)
async def create_iam_application(
    name: str,
    workspace: str,
    description: str | None = None,
    service_type: str | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Create a new IAM application.

    Args:
        name: Name of the new application
        workspace: Workspace name. Required parameter
        description: Description of the application (optional)
        service_type: ci_cd, monitoring, automation, or integration
            (optional; server defaults to integration)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application creation response
    """
    if service_type is not None and service_type not in VALID_SERVICE_TYPES:
        return format_validation_error(
            'service_type',
            service_type,
            f'Must be one of: {", ".join(sorted(VALID_SERVICE_TYPES))}',
        )

    token = kwargs.get('token')

    app_data: dict[str, object] = {'name': name}
    if description is not None:
        app_data['description'] = description
    if service_type is not None:
        app_data['service_type'] = service_type

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/applications/',
        token=token,
        data=app_data,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to create IAM application',
        app_name=name,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, app_name=name, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Get detailed information about a specific IAM application by its application ID. Returns name, description, and configuration details. Related: list_iam_applications, update_iam_application.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam application detail get service account'},
)
async def get_iam_application(
    app_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Get IAM application details.

    Args:
        app_id: Application ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application detail response
    """
    err = _validate_uuid('app_id', app_id)
    if err:
        return err

    token = kwargs.get('token')
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/',
        token=token,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to get IAM application',
        app_id=app_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, app_id=app_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Update an existing IAM application. Can change the application name or description. Only provided fields will be updated (partial update). Related: get_iam_application, delete_iam_application.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'iam application update modify edit'},
)
async def update_iam_application(
    app_id: str,
    workspace: str,
    name: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Update an existing IAM application.

    Args:
        app_id: Application ID to update
        workspace: Workspace name. Required parameter
        name: New application name (optional)
        description: New application description (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application update response
    """
    err = _validate_uuid('app_id', app_id)
    if err:
        return err

    token = kwargs.get('token')

    update_data: dict[str, object] = {}
    if name is not None:
        update_data['name'] = name
    if description is not None:
        update_data['description'] = description

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/',
        token=token,
        data=update_data,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to update IAM application',
        app_id=app_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, app_id=app_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Permanently delete an IAM application from the workspace. This action cannot be undone. Related: get_iam_application, list_iam_applications.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam application delete remove'},
)
async def delete_iam_application(
    app_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Delete an IAM application.

    Args:
        app_id: Application ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application deletion response
    """
    err = _validate_uuid('app_id', app_id)
    if err:
        return err

    token = kwargs.get('token')
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/',
        token=token,
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to delete IAM application',
        app_id=app_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, app_id=app_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Assign existing system users (OS-level accounts on servers) to an IAM application, binding them as the application service accounts. Requires the application ID and a list of system user IDs. Related: unassign_application_system_users, get_iam_application, list_system_users.',
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'iam application assign system users service account bind'
    },
)
async def assign_application_system_users(
    app_id: str,
    system_user_ids: list[str],
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Assign system users to an IAM application.

    Args:
        app_id: Application ID to assign system users to
        system_user_ids: List of system user IDs (UUIDs) to bind
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Assigned system users response
    """
    err = _validate_uuid('app_id', app_id)
    if err:
        return err
    if not system_user_ids:
        return format_validation_error(
            'system_user_ids',
            system_user_ids,
            'Must contain at least one system user ID',
        )
    for su_id in system_user_ids:
        err = _validate_uuid('system_user_ids', su_id)
        if err:
            return err

    token = kwargs.get('token')
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/system-users/',
        token=token,
        data={'system_user_ids': system_user_ids},
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to assign system users to IAM application',
        app_id=app_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, app_id=app_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Unassign system users from an IAM application, releasing them as application service accounts. Requires the application ID and a list of system user IDs. Related: assign_application_system_users, get_iam_application.',
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'iam application unassign system users service account release'
    },
)
async def unassign_application_system_users(
    app_id: str,
    system_user_ids: list[str],
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Unassign system users from an IAM application.

    Args:
        app_id: Application ID to unassign system users from
        system_user_ids: List of system user IDs (UUIDs) to release
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Unassigned system users response
    """
    err = _validate_uuid('app_id', app_id)
    if err:
        return err
    if not system_user_ids:
        return format_validation_error(
            'system_user_ids',
            system_user_ids,
            'Must contain at least one system user ID',
        )
    for su_id in system_user_ids:
        err = _validate_uuid('system_user_ids', su_id)
        if err:
            return err

    token = kwargs.get('token')
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/system-users/unassign/',
        token=token,
        data={'system_user_ids': system_user_ids},
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to unassign system users from IAM application',
        app_id=app_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    return success_response(
        data=result, app_id=app_id, region=region, workspace=workspace
    )
