"""Workspace management tools for Alpacon MCP server."""

import asyncio
from typing import Dict, Any
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="Get list of available workspaces")
async def workspace_list(
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get list of available workspaces.

    Args:
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Workspaces list response
    """
    try:
        # Get all stored tokens to find available workspaces
        all_tokens = token_manager.get_all_tokens()

        workspaces = []
        for region_key, region_data in all_tokens.items():
            if region_key == region:
                for workspace_key, workspace_data in region_data.items():
                    workspaces.append({
                        "workspace": workspace_key,
                        "region": region_key,
                        "has_token": bool(workspace_data.get("token")),
                        "domain": f"{workspace_key}.{region_key}.alpacon.io"
                    })

        return {
            "status": "success",
            "data": {
                "workspaces": workspaces,
                "region": region
            },
            "region": region
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get workspaces list: {str(e)}"
        }


@mcp.tool(description="Get user settings")
async def user_settings_get(
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get user settings.

    Args:
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        User settings response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get user settings
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint="/api/user/settings/",
                token=token
        )

        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get user settings: {str(e)}"
        }


@mcp.tool(description="Update user settings")
async def user_settings_update(
    settings: Dict[str, Any],
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Update user settings.

    Args:
        settings: Settings to update (dict format)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        User settings update response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to update user settings
        result = await http_client.patch(
                region=region,
                workspace=workspace,
                endpoint="/api/user/settings/",
                token=token,
                data=settings
        )
        return {
            "status": "success",
            "data": result,
            "settings": settings,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update user settings: {str(e)}"
        }


@mcp.tool(description="Get user profile information")
async def user_profile_get(
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get user profile information.

    Args:
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        User profile response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get user profile
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint="/api/user/profile/",
                token=token
        )

        return {
            "status": "success",
            "data": result,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get user profile: {str(e)}"
        }


# Workspaces resource
@mcp.resource(
    uri="workspace://list/{region}",
    name="Workspaces List",
    description="Get list of available workspaces",
    mime_type="application/json"
)
def workspaces_resource(region: str) -> Dict[str, Any]:
    """Get workspaces as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)

    Returns:
        Workspaces information
    """
    workspaces_data = workspace_list(region=region)
    return {
        "content": workspaces_data
    }


# User settings resource
@mcp.resource(
    uri="user://settings/{region}/{workspace}",
    name="User Settings",
    description="Get user settings",
    mime_type="application/json"
)
async def user_settings_resource(region: str, workspace: str) -> Dict[str, Any]:
    """Get user settings as a resource.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        User settings information
    """
    settings_data = user_settings_get(region=region, workspace=workspace)
    return {
        "content": settings_data
    }