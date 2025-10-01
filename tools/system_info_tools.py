"""System information tools for Alpacon MCP server."""

from typing import Dict, Any, Optional
import asyncio
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler


@mcp_tool_handler(description="Get system information for a server")
async def get_system_info(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get detailed system information for a server.

    Args:
        server_id: Server ID to get system info for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        System information response
    """
    token = kwargs.get('token')

    # Make async call to get system info
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/proc/info/",
        token=token,
        params={"server": server_id}
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get OS version information for a server")
async def get_os_version(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get operating system version information for a server.

    Args:
        server_id: Server ID to get OS info for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        OS version information response
    """
    token = kwargs.get('token')

    # Make async call to get OS version
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/proc/os/",
        token=token,
        params={"server": server_id}
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="List system users on a server")
async def list_system_users(
    server_id: str,
    workspace: str,
    username_filter: Optional[str] = None,
    login_enabled_only: bool = False,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """List system users on a server.

    Args:
        server_id: Server ID to get users from
        workspace: Workspace name. Required parameter
        username_filter: Optional username to search for
        login_enabled_only: Only return users that can login. Defaults to False
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        System users list response
    """
    token = kwargs.get('token')

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

    return success_response(
        data=result,
        server_id=server_id,
        username_filter=username_filter,
        login_enabled_only=login_enabled_only,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="List system groups on a server")
async def list_system_groups(
    server_id: str,
    workspace: str,
    groupname_filter: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """List system groups on a server.

    Args:
        server_id: Server ID to get groups from
        workspace: Workspace name. Required parameter
        groupname_filter: Optional group name to search for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        System groups list response
    """
    token = kwargs.get('token')

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

    return success_response(
        data=result,
        server_id=server_id,
        groupname_filter=groupname_filter,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="List installed packages on a server")
async def list_system_packages(
    server_id: str,
    workspace: str,
    package_name: Optional[str] = None,
    architecture: Optional[str] = None,
    limit: int = 100,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """List installed system packages on a server.

    Args:
        server_id: Server ID to get packages from
        workspace: Workspace name. Required parameter
        package_name: Optional package name to search for
        architecture: Optional architecture filter (e.g., 'x86_64', 'aarch64')
        limit: Maximum number of packages to return. Defaults to 100
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        System packages list response
    """
    token = kwargs.get('token')

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

    return success_response(
        data=result,
        server_id=server_id,
        package_name=package_name,
        architecture=architecture,
        limit=limit,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get network interfaces information")
async def get_network_interfaces(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get network interfaces information for a server.

    Args:
        server_id: Server ID to get network interfaces for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Network interfaces information response
    """
    token = kwargs.get('token')

    # Make async call to get network interfaces
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/proc/interfaces/",
        token=token,
        params={"server": server_id}
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get disk and partition information")
async def get_disk_info(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get disk and partition information for a server.

    Args:
        server_id: Server ID to get disk info for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Disk and partition information response
    """
    token = kwargs.get('token')

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

    return success_response(data=disk_info)


@mcp_tool_handler(description="Get system time information")
async def get_system_time(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get system time and uptime information for a server.

    Args:
        server_id: Server ID to get time info for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        System time information response
    """
    token = kwargs.get('token')

    # Make async call to get system time
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/proc/time/",
        token=token,
        params={"server": server_id}
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get comprehensive server overview")
async def get_server_overview(
    server_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get comprehensive overview of server system information.

    Args:
        server_id: Server ID to get overview for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Comprehensive server overview
    """
    # Get all system information concurrently
    tasks = [
        get_system_info(server_id, workspace, region, **kwargs),
        get_os_version(server_id, workspace, region, **kwargs),
        get_system_time(server_id, workspace, region, **kwargs),
        get_network_interfaces(server_id, workspace, region, **kwargs),
        get_disk_info(server_id, workspace, region, **kwargs)
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

    return success_response(data=overview)
