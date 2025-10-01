"""Workspace management tools for Alpacon MCP server."""

from typing import Dict, Any
from utils.common import success_response
from server import mcp


@mcp.tool(description="Get list of available workspaces")
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
            # region_data can be either a dict or a string (token directly)
            if isinstance(region_data, dict):
                for workspace_key, workspace_data in region_data.items():
                    # workspace_data can be either a dict or a string (token directly)
                    if isinstance(workspace_data, dict):
                        has_token = bool(workspace_data.get("token"))
                    else:
                        # If workspace_data is a string, it's the token itself
                        has_token = bool(workspace_data)

                    workspaces.append({
                        "workspace": workspace_key,
                        "region": region_key,
                        "has_token": has_token,
                        "domain": f"{workspace_key}.{region_key}.alpacon.io"
                    })
            else:
                # If region_data is a string (token directly), it's a single workspace with region name
                workspaces.append({
                    "workspace": region_key,
                    "region": region_key,
                    "has_token": bool(region_data),
                    "domain": f"{region_key}.{region_key}.alpacon.io"
                })

    return success_response(
        data={"workspaces": workspaces, "region": region},
        region=region
    )


# ===============================
# NOTE: User settings and profile endpoints are not implemented in the server
# The following functions have been removed:
# - get_user_settings (was using /api/user/settings/)
# - update_user_settings (was using /api/user/settings/)
# - get_user_profile (was using /api/user/profile/)
#
# Alternative endpoints available in the server:
# - /api/profiles/preferences/ (profiles app)
# - /api/workspaces/preferences/ (workspaces app)
# - /api/auth0/users/ (auth0 app)
# ===============================
