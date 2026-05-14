"""IAM (Identity and Access Management) tools for Alpacon MCP server."""

from typing import Any

from server import mcp
from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

# ===============================
# USER MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='List all IAM users in a workspace. Returns username, email, active status, and group memberships for each user. Supports pagination for large user lists. Related: get_iam_user (details), create_iam_user, list_system_users (OS-level users, not IAM).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam users list workspace identity access'},
)
async def list_iam_users(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
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

    # Prepare query parameters
    params = {}
    if page:
        params['page'] = page
    if page_size:
        params['page_size'] = page_size

    # Make async call to IAM users endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific IAM user by their user ID. Returns email, first/last name, active status, and assigned groups. Use this when you need full profile details for a single user.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam user detail profile'},
)
async def get_iam_user(
    user_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get detailed information about a specific IAM user.

    Args:
        user_id: IAM user ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM user details response
    """
    token = kwargs.get('token')

    # Make async call to specific IAM user endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/users/{user_id}/',
        token=token,
    )

    return success_response(
        data=result, user_id=user_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Create a new IAM user account in the workspace. Requires username and email. Optionally assign the user to groups and set first/last name. The user is active by default. Related: list_iam_groups (find groups to assign), update_iam_user, delete_iam_user.',
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
    groups: list[str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new IAM user.

    Args:
        username: Username for the new user
        email: Email address for the new user
        workspace: Workspace name. Required parameter
        first_name: First name (optional)
        last_name: Last name (optional)
        is_active: Whether user is active (default: True)
        groups: List of group IDs to assign to user (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        User creation response
    """
    token = kwargs.get('token')

    # Prepare user data
    user_data = {'username': username, 'email': email, 'is_active': is_active}

    if first_name:
        user_data['first_name'] = first_name
    if last_name:
        user_data['last_name'] = last_name
    if groups:
        user_data['groups'] = groups

    # Make async call to create IAM user
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/',
        token=token,
        data=user_data,
    )

    return success_response(
        data=result, username=username, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Update an existing IAM user profile. Can change email, first/last name, active/inactive status, or group memberships. Only the fields you provide will be updated (partial update).',
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
    groups: list[str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing IAM user.

    Args:
        user_id: IAM user ID to update
        workspace: Workspace name. Required parameter
        email: New email address (optional)
        first_name: New first name (optional)
        last_name: New last name (optional)
        is_active: New active status (optional)
        groups: New list of group IDs (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        User update response
    """
    token = kwargs.get('token')

    # Prepare update data (only include provided fields)
    update_data: dict[str, Any] = {}
    if email is not None:
        update_data['email'] = email
    if first_name is not None:
        update_data['first_name'] = first_name
    if last_name is not None:
        update_data['last_name'] = last_name
    if is_active is not None:
        update_data['is_active'] = is_active
    if groups is not None:
        update_data['groups'] = groups

    if not update_data:
        return error_response('No update data provided')

    # Make async call to update IAM user
    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/users/{user_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, user_id=user_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Permanently delete an IAM user account from the workspace. This action cannot be undone. Use update_iam_user to deactivate a user instead if you want to preserve the account.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam user delete remove'},
)
async def delete_iam_user(
    user_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete an IAM user.

    Args:
        user_id: IAM user ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        User deletion response
    """
    token = kwargs.get('token')

    # Make async call to delete IAM user
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/users/{user_id}/',
        token=token,
    )

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
    **kwargs,
) -> dict[str, Any]:
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

    # Prepare query parameters
    params = {}
    if page:
        params['page'] = page
    if page_size:
        params['page_size'] = page_size

    # Make async call to IAM groups endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/groups/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a new IAM permission group in the workspace. Requires a group name. Optionally set a description and assign permissions. Users can then be added to this group via create_iam_user or update_iam_user.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam group create add new'},
)
async def create_iam_group(
    name: str,
    workspace: str,
    description: str | None = None,
    permissions: list[str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new IAM group.

    Args:
        name: Name for the new group
        workspace: Workspace name. Required parameter
        description: Description of the group (optional)
        permissions: List of permission IDs to assign to group (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Group creation response
    """
    token = kwargs.get('token')

    # Prepare group data
    group_data: dict[str, Any] = {'name': name}

    if description:
        group_data['description'] = description
    if permissions:
        group_data['permissions'] = permissions

    # Make async call to create IAM group
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/groups/',
        token=token,
        data=group_data,
    )

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
# RESOURCE MANAGEMENT
# ===============================


@mcp.resource(
    uri='iam://users/{region}/{workspace}',
    name='IAM Users List',
    description='Get list of IAM users',
    mime_type='application/json',
)
async def iam_users_resource(region: str, workspace: str) -> dict[str, Any]:
    """Get IAM users as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        IAM users information
    """
    users_data = await list_iam_users(region=region, workspace=workspace)
    return {'content': users_data}


@mcp.resource(
    uri='iam://groups/{region}/{workspace}',
    name='IAM Groups List',
    description='Get list of IAM groups',
    mime_type='application/json',
)
async def iam_groups_resource(region: str, workspace: str) -> dict[str, Any]:
    """Get IAM groups as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        IAM groups information
    """
    groups_data = await list_iam_groups(region=region, workspace=workspace)
    return {'content': groups_data}


# NOTE: IAM roles resource removed - endpoint not implemented in server


# ===============================
# EXTENDED GROUP MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='Get detailed information about a specific IAM group by its group ID. Returns group name, description, and member information. Related: list_iam_groups (all groups), update_iam_group, delete_iam_group.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam group detail get'},
)
async def get_iam_group(
    group_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get IAM group details.

    Args:
        group_id: Group ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM group detail response
    """
    token = kwargs.get('token')
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/groups/{group_id}/',
        token=token,
    )
    return success_response(data=result, group_id=group_id, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing IAM group. Can change the group name or description. Only the fields you provide will be updated (partial update). Related: get_iam_group, delete_iam_group.',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'iam group update modify edit'},
)
async def update_iam_group(
    group_id: str,
    workspace: str,
    name: str | None = None,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing IAM group.

    Args:
        group_id: Group ID to update
        workspace: Workspace name. Required parameter
        name: New group name (optional)
        description: New group description (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM group update response
    """
    token = kwargs.get('token')

    # Prepare update data (only include provided fields)
    update_data: dict[str, Any] = {}
    if name is not None:
        update_data['name'] = name
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
    return success_response(data=result, group_id=group_id, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Permanently delete an IAM group from the workspace. This action cannot be undone. Users in the group will lose group-based permissions. Related: get_iam_group, list_iam_groups.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam group delete remove'},
)
async def delete_iam_group(
    group_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Delete an IAM group.

    Args:
        group_id: Group ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM group deletion response
    """
    token = kwargs.get('token')
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/groups/{group_id}/',
        token=token,
    )
    return success_response(data=result, group_id=group_id, region=region, workspace=workspace)


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
    **kwargs,
) -> dict[str, Any]:
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
    token = kwargs.get('token')

    params: dict[str, Any] = {}
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
    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Add a user to an IAM group by creating a membership. Requires both group ID and user ID. Related: remove_iam_member, list_iam_memberships.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam member add group user membership'},
)
async def add_iam_member(
    group_id: str,
    user_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Add a user to an IAM group.

    Args:
        group_id: Group ID to add the user to
        user_id: User ID to add to the group
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM membership creation response
    """
    token = kwargs.get('token')
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/memberships/',
        token=token,
        data={'group': group_id, 'user': user_id},
    )
    return success_response(data=result, group_id=group_id, user_id=user_id, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Remove a user from an IAM group by deleting a membership record. Requires the membership ID (not user or group ID). Use list_iam_memberships to find the membership ID. Related: add_iam_member, list_iam_memberships.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam member remove group user membership delete'},
)
async def remove_iam_member(
    membership_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Remove a user from an IAM group.

    Args:
        membership_id: Membership ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM membership deletion response
    """
    token = kwargs.get('token')
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/memberships/{membership_id}/',
        token=token,
    )
    return success_response(data=result, membership_id=membership_id, region=region, workspace=workspace)


# ===============================
# USER INVITATION TOOLS
# ===============================


@mcp_tool_handler(
    description='Send an email invitation to a user to join the workspace. Requires the user ID and the target email address. The user must already exist in IAM. Related: create_iam_user, get_iam_user.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam user invite email send'},
)
async def invite_iam_user(
    user_id: str,
    email: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Invite an IAM user by email.

    Args:
        user_id: IAM user ID to invite
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
        endpoint=f'/api/iam/users/{user_id}/invite/',
        token=token,
        data={'email': email},
    )
    return success_response(data=result, user_id=user_id, region=region, workspace=workspace)


# ===============================
# APPLICATION MANAGEMENT TOOLS
# ===============================


@mcp_tool_handler(
    description='List all IAM applications (service accounts / OAuth apps) in the workspace. Supports pagination. Related: create_iam_application, get_iam_application.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam applications list service accounts oauth'},
)
async def list_iam_applications(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
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

    params: dict[str, Any] = {}
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
    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a new IAM application (service account / OAuth app) in the workspace. Requires a name. Optionally set a description. Related: list_iam_applications, get_iam_application, provision_service_account.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam application create new service account oauth'},
)
async def create_iam_application(
    name: str,
    workspace: str,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new IAM application.

    Args:
        name: Name of the new application
        workspace: Workspace name. Required parameter
        description: Description of the application (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application creation response
    """
    token = kwargs.get('token')

    app_data: dict[str, Any] = {'name': name}
    if description is not None:
        app_data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/applications/',
        token=token,
        data=app_data,
    )
    return success_response(data=result, app_name=name, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific IAM application by its application ID. Returns name, description, and configuration details. Related: list_iam_applications, update_iam_application.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'iam application detail get service account'},
)
async def get_iam_application(
    app_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get IAM application details.

    Args:
        app_id: Application ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application detail response
    """
    token = kwargs.get('token')
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/',
        token=token,
    )
    return success_response(data=result, app_id=app_id, region=region, workspace=workspace)


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
    **kwargs,
) -> dict[str, Any]:
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
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
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
    return success_response(data=result, app_id=app_id, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Permanently delete an IAM application from the workspace. This action cannot be undone. Related: get_iam_application, list_iam_applications.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'iam application delete remove'},
)
async def delete_iam_application(
    app_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Delete an IAM application.

    Args:
        app_id: Application ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        IAM application deletion response
    """
    token = kwargs.get('token')
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/',
        token=token,
    )
    return success_response(data=result, app_id=app_id, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Provision a service account for an IAM application. This creates a system-level account linked to the application for machine-to-machine authentication. Related: create_iam_application, get_iam_application.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'iam application provision service account machine'},
)
async def provision_service_account(
    app_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Provision a service account for an IAM application.

    Args:
        app_id: Application ID to provision a service account for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Service account provisioning response
    """
    token = kwargs.get('token')
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/iam/applications/{app_id}/provision-account/',
        token=token,
        data={},
    )
    return success_response(data=result, app_id=app_id, region=region, workspace=workspace)
