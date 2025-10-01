"""Workspace management tools for Alpacon MCP server - Refactored version."""

from typing import Dict, Any
from utils.http_client import http_client
from utils.common import success_response, error_response, validate_token
from utils.decorators import mcp_tool_handler


@mcp_tool_handler(description="Get list of available workspaces")
async def list_workspaces(region: str = "ap1") -> Dict[str, Any]:
    """Get list of available workspaces.

    Args:
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Workspaces list response
    """
    from utils.token_manager import get_token_manager
    token_manager = get_token_manager()

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

    return success_response(
        data={"workspaces": workspaces, "region": region},
        region=region
    )


@mcp_tool_handler(description="Get user settings")
async def get_user_settings(
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get user settings.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User settings response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to get user settings
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/user/settings/",
        token=token
    )

    return success_response(
        data=result,
        workspace=workspace,
        region=region
    )


@mcp_tool_handler(description="Update user settings")
async def update_user_settings(
    settings: Dict[str, Any],
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Update user settings.

    Args:
        settings: Settings data to update
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Settings update response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to update settings
    result = await http_client.put(
        region=region,
        workspace=workspace,
        endpoint="/api/user/settings/",
        token=token,
        data=settings
    )

    return success_response(
        data=result,
        workspace=workspace,
        region=region
    )


@mcp_tool_handler(description="Get user profile information")
async def get_user_profile(
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get user profile information.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        User profile response
    """
    # Get token (injected by decorator)
    token = kwargs.get('token')

    # Make async call to get user profile
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/user/profile/",
        token=token
    )

    return success_response(
        data=result,
        workspace=workspace,
        region=region
    )