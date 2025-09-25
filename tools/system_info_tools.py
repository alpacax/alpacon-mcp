"""System information tools for Alpacon MCP server."""

from typing import Dict, Any, Optional, List
from server import mcp
from utils.http_client import http_client
from utils.token_manager import TokenManager

# Initialize token manager
token_manager = TokenManager()


@mcp.tool(description="Get system information for a server")
async def get_system_info(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get detailed system information for a server.

    Args:
        server_id: Server ID to get system info for
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
            endpoint="/api/proc/info/",
            token=token,
            params={"server": server_id}
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


@mcp.tool(description="Get OS version information for a server")
async def get_os_version(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get operating system version information for a server.

    Args:
        server_id: Server ID to get OS info for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        OS version information response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get OS version
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/os/",
            token=token,
            params={"server": server_id}
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
            "message": f"Failed to get OS version: {str(e)}"
        }


@mcp.tool(description="List system users on a server")
async def list_system_users(
    server_id: str,
    workspace: str,
    username_filter: Optional[str] = None,
    login_enabled_only: bool = False,
    region: str = "ap1",
) -> Dict[str, Any]:
    """List system users on a server.

    Args:
        server_id: Server ID to get users from
        username_filter: Optional username to search for
        login_enabled_only: Only return users that can login. Defaults to False
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

        # Prepare query parameters
        params = {"server": server_id}
        if username_filter:
            params["search"] = username_filter
        if login_enabled_only:
            params["login_enabled"] = "true"

        # Make async call to get system users
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/users/",
            token=token,
            params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "username_filter": username_filter,
            "login_enabled_only": login_enabled_only,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list system users: {str(e)}"
        }


@mcp.tool(description="List system groups on a server")
async def list_system_groups(
    server_id: str,
    workspace: str,
    groupname_filter: Optional[str] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """List system groups on a server.

    Args:
        server_id: Server ID to get groups from
        groupname_filter: Optional group name to search for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        System groups list response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare query parameters
        params = {"server": server_id}
        if groupname_filter:
            params["search"] = groupname_filter

        # Make async call to get system groups
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/groups/",
            token=token,
            params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "groupname_filter": groupname_filter,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list system groups: {str(e)}"
        }


@mcp.tool(description="List installed packages on a server")
async def list_system_packages(
    server_id: str,
    workspace: str,
    package_name: Optional[str] = None,
    architecture: Optional[str] = None,
    limit: int = 100,
    region: str = "ap1",
) -> Dict[str, Any]:
    """List installed system packages on a server.

    Args:
        server_id: Server ID to get packages from
        package_name: Optional package name to search for
        architecture: Optional architecture filter (e.g., 'x86_64', 'aarch64')
        limit: Maximum number of packages to return. Defaults to 100
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

        # Prepare query parameters
        params = {
            "server": server_id,
            "page_size": limit
        }
        if package_name:
            params["search"] = package_name
        if architecture:
            params["arch"] = architecture

        # Make async call to get system packages
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/packages/",
            token=token,
            params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "package_name": package_name,
            "architecture": architecture,
            "limit": limit,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list system packages: {str(e)}"
        }


@mcp.tool(description="Get network interfaces information")
async def get_network_interfaces(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get network interfaces information for a server.

    Args:
        server_id: Server ID to get network interfaces for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Network interfaces information response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get network interfaces
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/interfaces/",
            token=token,
            params={"server": server_id}
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
            "message": f"Failed to get network interfaces: {str(e)}"
        }


@mcp.tool(description="Get disk and partition information")
async def get_disk_info(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get disk and partition information for a server.

    Args:
        server_id: Server ID to get disk info for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Disk and partition information response
    """
    try:
        import asyncio

        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Get both disks and partitions concurrently
        disks_task = http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/disks/",
            token=token,
            params={"server": server_id}
        )

        partitions_task = http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/partitions/",
            token=token,
            params={"server": server_id}
        )

        # Wait for both requests
        disks_result, partitions_result = await asyncio.gather(
            disks_task, partitions_task,
            return_exceptions=True
        )

        # Prepare response
        disk_info = {
            "server_id": server_id,
            "disks": disks_result if not isinstance(disks_result, Exception) else {"error": str(disks_result)},
            "partitions": partitions_result if not isinstance(partitions_result, Exception) else {"error": str(partitions_result)},
            "region": region,
            "workspace": workspace
        }

        return {
            "status": "success",
            "data": disk_info
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get disk info: {str(e)}"
        }


@mcp.tool(description="Get system time information")
async def get_system_time(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get system time and uptime information for a server.

    Args:
        server_id: Server ID to get time info for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        System time information response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get system time
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/proc/time/",
            token=token,
            params={"server": server_id}
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
            "message": f"Failed to get system time: {str(e)}"
        }


@mcp.tool(description="Get comprehensive server overview")
async def get_server_overview(
    server_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get comprehensive overview of server system information.

    Args:
        server_id: Server ID to get overview for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Comprehensive server overview
    """
    try:
        import asyncio

        # Get all system information concurrently
        tasks = [
            get_system_info(server_id, region, workspace),
            get_os_version(server_id, region, workspace),
            get_system_time(server_id, region, workspace),
            get_network_interfaces(server_id, region, workspace),
            get_disk_info(server_id, region, workspace)
        ]

        # Wait for all requests
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Prepare overview
        overview = {
            "server_id": server_id,
            "region": region,
            "workspace": workspace,
            "system_info": {},
            "os_version": {},
            "system_time": {},
            "network_interfaces": {},
            "disk_info": {}
        }

        # Process results
        task_keys = ["system_info", "os_version", "system_time", "network_interfaces", "disk_info"]

        for i, result in enumerate(results):
            key = task_keys[i]
            if isinstance(result, dict) and result.get("status") == "success":
                overview[key] = result["data"]
            else:
                overview[key] = {
                    "error": str(result) if isinstance(result, Exception) else result.get("message", "Unknown error")
                }

        return {
            "status": "success",
            "data": overview
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get server overview: {str(e)}"
        }
