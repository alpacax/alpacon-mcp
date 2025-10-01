"""IAM (Identity and Access Management) tools for Alpacon MCP server."""

from typing import Dict, Any, Optional, List
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler
from server import mcp


# ===============================
# USER MANAGEMENT TOOLS
# ===============================

@mcp_tool_handler(description="List all IAM users in workspace")
async def list_iam_users(
    workspace: str,
    region: str = "ap1",
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """List all IAM users in workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        page: Page number for pagination (optional)
        page_size: Number of users per page (optional)

    Returns:
        IAM users list response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if page:
        params["page"] = page
    if page_size:
        params["page_size"] = page_size

    # Make async call to IAM users endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/iam/users/",
        token=token,
        params=params
    )

    return success_response(
        data=result,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get detailed information about a specific IAM user")
async def get_iam_user(
    user_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get detailed information about a specific IAM user.

    Args:
        user_id: IAM user ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        IAM user details response
    """
    token = kwargs.get('token')

    # Make async call to specific IAM user endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f"/api/iam/users/{user_id}/",
        token=token
    )

    return success_response(
        data=result,
        user_id=user_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Create a new IAM user")
async def create_iam_user(
    username: str,
    email: str,
    workspace: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_active: bool = True,
    groups: Optional[List[str]] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Create a new IAM user.

    Args:
        username: Username for the new user
        email: Email address for the new user
        workspace: Workspace name. Required parameter
        first_name: First name (optional)
        last_name: Last name (optional)
        is_active: Whether user is active (default: True)
        groups: List of group IDs to assign to user (optional)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User creation response
    """
    token = kwargs.get('token')

    # Prepare user data
    user_data = {
        "username": username,
        "email": email,
        "is_active": is_active
    }

    if first_name:
        user_data["first_name"] = first_name
    if last_name:
        user_data["last_name"] = last_name
    if groups:
        user_data["groups"] = groups

    # Make async call to create IAM user
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint="/api/iam/users/",
        token=token,
        data=user_data
    )

    return success_response(
        data=result,
        username=username,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Update an existing IAM user")
async def update_iam_user(
    user_id: str,
    workspace: str,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    groups: Optional[List[str]] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Update an existing IAM user.

    Args:
        user_id: IAM user ID to update
        workspace: Workspace name. Required parameter
        email: New email address (optional)
        first_name: New first name (optional)
        last_name: New last name (optional)
        is_active: New active status (optional)
        groups: New list of group IDs (optional)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User update response
    """
    token = kwargs.get('token')

    # Prepare update data (only include provided fields)
    update_data = {}
    if email is not None:
        update_data["email"] = email
    if first_name is not None:
        update_data["first_name"] = first_name
    if last_name is not None:
        update_data["last_name"] = last_name
    if is_active is not None:
        update_data["is_active"] = is_active
    if groups is not None:
        update_data["groups"] = groups

    if not update_data:
        return error_response("No update data provided")

    # Make async call to update IAM user
    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f"/api/iam/users/{user_id}/",
        token=token,
        data=update_data
    )

    return success_response(
        data=result,
        user_id=user_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Delete an IAM user")
async def delete_iam_user(
    user_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Delete an IAM user.

    Args:
        user_id: IAM user ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User deletion response
    """
    token = kwargs.get('token')

    # Make async call to delete IAM user
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f"/api/iam/users/{user_id}/",
        token=token
    )

    return success_response(
        data=result,
        user_id=user_id,
        region=region,
        workspace=workspace
    )


# ===============================
# GROUP MANAGEMENT TOOLS
# ===============================

@mcp_tool_handler(description="List all IAM groups in workspace")
async def list_iam_groups(
    workspace: str,
    region: str = "ap1",
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """List all IAM groups in workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        page: Page number for pagination (optional)
        page_size: Number of groups per page (optional)

    Returns:
        IAM groups list response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if page:
        params["page"] = page
    if page_size:
        params["page_size"] = page_size

    # Make async call to IAM groups endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/iam/groups/",
        token=token,
        params=params
    )

    return success_response(
        data=result,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Create a new IAM group")
async def create_iam_group(
    name: str,
    workspace: str,
    description: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Create a new IAM group.

    Args:
        name: Name for the new group
        workspace: Workspace name. Required parameter
        description: Description of the group (optional)
        permissions: List of permission IDs to assign to group (optional)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Group creation response
    """
    token = kwargs.get('token')

    # Prepare group data
    group_data = {
        "name": name
    }

    if description:
        group_data["description"] = description
    if permissions:
        group_data["permissions"] = permissions

    # Make async call to create IAM group
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint="/api/iam/groups/",
        token=token,
        data=group_data
    )

    return success_response(
        data=result,
        group_name=name,
        region=region,
        workspace=workspace
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
    uri="iam://users/{region}/{workspace}",
    name="IAM Users List",
    description="Get list of IAM users",
    mime_type="application/json"
)
async def iam_users_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get IAM users as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        IAM users information
    """
    users_data = await list_iam_users(region=region, workspace=workspace)
    return {
        "content": users_data
    }


@mcp.resource(
    uri="iam://groups/{region}/{workspace}",
    name="IAM Groups List",
    description="Get list of IAM groups",
    mime_type="application/json"
)
async def iam_groups_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get IAM groups as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        IAM groups information
    """
    groups_data = await list_iam_groups(region=region, workspace=workspace)
    return {
        "content": groups_data
    }


# NOTE: IAM roles resource removed - endpoint not implemented in server
