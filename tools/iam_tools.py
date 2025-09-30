"""IAM (Identity and Access Management) tools for Alpacon MCP server."""

from typing import Dict, Any, Optional, List
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager
from utils.logger import get_logger

# Initialize token manager and logger
token_manager = get_token_manager()
logger = get_logger("iam_tools")


# ===============================
# USER MANAGEMENT TOOLS
# ===============================

@mcp.tool(description="List all IAM users in workspace")
async def list_iam_users(
    workspace: str,
    region: str = "ap1",
    page: Optional[int] = None,
    page_size: Optional[int] = None
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
    logger.info(f"iam_users_list called - workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if page:
            params["page"] = page
        if page_size:
            params["page_size"] = page_size

        logger.debug(f"Token found for {workspace}.{region}, making API call")

        # Make async call to IAM users endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/iam/users/",
            token=token,
            params=params
        )

        logger.info(f"iam_users_list completed successfully for {workspace}.{region}")
        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_users_list failed for {workspace}.{region}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to get IAM users list: {str(e)}"
        }


@mcp.tool(description="Get detailed information about a specific IAM user")
async def get_iam_user(
    user_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get detailed information about a specific IAM user.

    Args:
        user_id: IAM user ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        IAM user details response
    """
    logger.info(f"iam_user_get called - user_id: {user_id}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        logger.debug(f"Token found for {workspace}.{region}, making API call")

        # Make async call to specific IAM user endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/iam/users/{user_id}/",
            token=token
        )

        logger.info(f"iam_user_get completed successfully for user {user_id}")
        return {
            "status": "success",
            "data": result,
            "user_id": user_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_user_get failed for user {user_id}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to get IAM user details: {str(e)}"
        }


@mcp.tool(description="Create a new IAM user")
async def create_iam_user(
    username: str,
    email: str,
    workspace: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_active: bool = True,
    groups: Optional[List[str]] = None,
    region: str = "ap1"
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
    logger.info(f"iam_user_create called - username: {username}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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

        logger.debug(f"Token found for {workspace}.{region}, creating user with data: {user_data}")

        # Make async call to create IAM user
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint="/api/iam/users/",
            token=token,
            data=user_data
        )

        logger.info(f"iam_user_create completed successfully for username {username}")
        return {
            "status": "success",
            "data": result,
            "username": username,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_user_create failed for username {username}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to create IAM user: {str(e)}"
        }


@mcp.tool(description="Update an existing IAM user")
async def update_iam_user(
    user_id: str,
    workspace: str,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    groups: Optional[List[str]] = None,
    region: str = "ap1"
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
    logger.info(f"iam_user_update called - user_id: {user_id}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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
            return {
                "status": "error",
                "message": "No update data provided"
            }

        logger.debug(f"Token found for {workspace}.{region}, updating user with data: {update_data}")

        # Make async call to update IAM user
        result = await http_client.patch(
            region=region,
            workspace=workspace,
            endpoint=f"/api/iam/users/{user_id}/",
            token=token,
            data=update_data
        )

        logger.info(f"iam_user_update completed successfully for user {user_id}")
        return {
            "status": "success",
            "data": result,
            "user_id": user_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_user_update failed for user {user_id}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to update IAM user: {str(e)}"
        }


@mcp.tool(description="Delete an IAM user")
async def delete_iam_user(
    user_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Delete an IAM user.

    Args:
        user_id: IAM user ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User deletion response
    """
    logger.info(f"iam_user_delete called - user_id: {user_id}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        logger.debug(f"Token found for {workspace}.{region}, deleting user {user_id}")

        # Make async call to delete IAM user
        result = await http_client.delete(
            region=region,
            workspace=workspace,
            endpoint=f"/api/iam/users/{user_id}/",
            token=token
        )

        logger.info(f"iam_user_delete completed successfully for user {user_id}")
        return {
            "status": "success",
            "data": result,
            "user_id": user_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_user_delete failed for user {user_id}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to delete IAM user: {str(e)}"
        }


# ===============================
# GROUP MANAGEMENT TOOLS
# ===============================

@mcp.tool(description="List all IAM groups in workspace")
async def list_iam_groups(
    workspace: str,
    region: str = "ap1",
    page: Optional[int] = None,
    page_size: Optional[int] = None
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
    logger.info(f"iam_groups_list called - workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if page:
            params["page"] = page
        if page_size:
            params["page_size"] = page_size

        logger.debug(f"Token found for {workspace}.{region}, making API call")

        # Make async call to IAM groups endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/iam/groups/",
            token=token,
            params=params
        )

        logger.info(f"iam_groups_list completed successfully for {workspace}.{region}")
        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_groups_list failed for {workspace}.{region}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to get IAM groups list: {str(e)}"
        }


@mcp.tool(description="Create a new IAM group")
async def create_iam_group(
    name: str,
    workspace: str,
    description: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    region: str = "ap1"
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
    logger.info(f"iam_group_create called - name: {name}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare group data
        group_data = {
            "name": name
        }

        if description:
            group_data["description"] = description
        if permissions:
            group_data["permissions"] = permissions

        logger.debug(f"Token found for {workspace}.{region}, creating group with data: {group_data}")

        # Make async call to create IAM group
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint="/api/iam/groups/",
            token=token,
            data=group_data
        )

        logger.info(f"iam_group_create completed successfully for group {name}")
        return {
            "status": "success",
            "data": result,
            "group_name": name,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_group_create failed for group {name}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to create IAM group: {str(e)}"
        }


# ===============================
# ROLE MANAGEMENT TOOLS
# ===============================

@mcp.tool(description="List all IAM roles in workspace")
async def list_iam_roles(
    workspace: str,
    region: str = "ap1",
    page: Optional[int] = None,
    page_size: Optional[int] = None
) -> Dict[str, Any]:
    """List all IAM roles in workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        page: Page number for pagination (optional)
        page_size: Number of roles per page (optional)

    Returns:
        IAM roles list response
    """
    logger.info(f"iam_roles_list called - workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if page:
            params["page"] = page
        if page_size:
            params["page_size"] = page_size

        logger.debug(f"Token found for {workspace}.{region}, making API call")

        # Make async call to IAM roles endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/iam/roles/",
            token=token,
            params=params
        )

        logger.info(f"iam_roles_list completed successfully for {workspace}.{region}")
        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_roles_list failed for {workspace}.{region}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to get IAM roles list: {str(e)}"
        }


@mcp.tool(description="Assign a role to a user")
async def assign_iam_user_role(
    user_id: str,
    role_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Assign a role to a user.

    Args:
        user_id: IAM user ID
        role_id: IAM role ID to assign
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Role assignment response
    """
    logger.info(f"iam_user_assign_role called - user_id: {user_id}, role_id: {role_id}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare assignment data
        assignment_data = {
            "role_id": role_id
        }

        logger.debug(f"Token found for {workspace}.{region}, assigning role {role_id} to user {user_id}")

        # Make async call to assign role to user
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint=f"/api/iam/users/{user_id}/roles/",
            token=token,
            data=assignment_data
        )

        logger.info(f"iam_user_assign_role completed successfully for user {user_id}")
        return {
            "status": "success",
            "data": result,
            "user_id": user_id,
            "role_id": role_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_user_assign_role failed for user {user_id}, role {role_id}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to assign role to user: {str(e)}"
        }


# ===============================
# PERMISSION MANAGEMENT TOOLS
# ===============================

@mcp.tool(description="List all available permissions in workspace")
async def list_iam_permissions(
    workspace: str,
    region: str = "ap1",
    page: Optional[int] = None,
    page_size: Optional[int] = None
) -> Dict[str, Any]:
    """List all available permissions in workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        page: Page number for pagination (optional)
        page_size: Number of permissions per page (optional)

    Returns:
        IAM permissions list response
    """
    logger.info(f"iam_permissions_list called - workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {}
        if page:
            params["page"] = page
        if page_size:
            params["page_size"] = page_size

        logger.debug(f"Token found for {workspace}.{region}, making API call")

        # Make async call to IAM permissions endpoint
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/iam/permissions/",
            token=token,
            params=params
        )

        logger.info(f"iam_permissions_list completed successfully for {workspace}.{region}")
        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_permissions_list failed for {workspace}.{region}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to get IAM permissions list: {str(e)}"
        }


@mcp.tool(description="Get user's effective permissions")
async def get_iam_user_permissions(
    user_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get user's effective permissions (combines direct permissions and group permissions).

    Args:
        user_id: IAM user ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User's effective permissions response
    """
    logger.info(f"iam_user_permissions_get called - user_id: {user_id}, workspace: {workspace}, region: {region}")

    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            logger.error(f"No token found for {workspace}.{region}")
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        logger.debug(f"Token found for {workspace}.{region}, getting permissions for user {user_id}")

        # Make async call to get user permissions
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/iam/users/{user_id}/permissions/",
            token=token
        )

        logger.info(f"iam_user_permissions_get completed successfully for user {user_id}")
        return {
            "status": "success",
            "data": result,
            "user_id": user_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        logger.error(f"iam_user_permissions_get failed for user {user_id}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to get user permissions: {str(e)}"
        }


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
    users_data = await iam_users_list(region=region, workspace=workspace)
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
    groups_data = await iam_groups_list(region=region, workspace=workspace)
    return {
        "content": groups_data
    }


@mcp.resource(
    uri="iam://roles/{region}/{workspace}",
    name="IAM Roles List",
    description="Get list of IAM roles",
    mime_type="application/json"
)
async def iam_roles_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get IAM roles as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        IAM roles information
    """
    roles_data = await iam_roles_list(region=region, workspace=workspace)
    return {
        "content": roles_data
    }