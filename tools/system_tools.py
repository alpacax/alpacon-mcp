"""System information management tools for Alpacon MCP server."""

import asyncio
from typing import Dict, Any
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="Get system hardware information")
async def system_info(
    server_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get system hardware information.

    Args:
        server_id: Server ID to get system info from
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        System information response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get system info
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/servers/{server_id}/system/info/",
            token=token
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get system info: {str(e)}"
        }


@mcp.tool(description="Get system users list")
async def system_users_list(
    server_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get system users list.

    Args:
        server_id: Server ID to get users from
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        System users list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get users list
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint=f"/api/servers/{server_id}/system/users/",
                token=token
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get users list: {str(e)}"
        }


@mcp.tool(description="Get system packages list")
async def system_packages_list(
    server_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get system packages list.

    Args:
        server_id: Server ID to get packages from
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        System packages list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get packages list
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint=f"/api/servers/{server_id}/system/packages/",
                token=token
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get packages list: {str(e)}"
        }


@mcp.tool(description="Get system disk information")
async def system_disk_info(
    server_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get system disk information.

    Args:
        server_id: Server ID to get disk info from
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        System disk information response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get disk info
        result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint=f"/api/servers/{server_id}/system/disk/",
                token=token
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get disk info: {str(e)}"
        }


# System info resource
@mcp.resource(
    uri="system://info/{server_id}/{region}/{workspace}",
    name="System Information",
    description="Get system hardware information",
    mime_type="application/json"
)
def system_info_resource(server_id: str, region: str, workspace: str) -> Dict[str, Any]:
    """Get system info as a resource.

    Args:
        server_id: Server ID
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        System information
    """
    info_data = system_info(server_id=server_id, region=region, workspace=workspace)
    return {
        "content": info_data
    }


# System users resource
@mcp.resource(
    uri="system://users/{server_id}/{region}/{workspace}",
    name="System Users List",
    description="Get system users list",
    mime_type="application/json"
)
def system_users_resource(server_id: str, region: str, workspace: str) -> Dict[str, Any]:
    """Get system users as a resource.

    Args:
        server_id: Server ID
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        System users information
    """
    users_data = system_users_list(server_id=server_id, region=region, workspace=workspace)
    return {
        "content": users_data
    }