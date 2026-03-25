"""Package management tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client

# ===============================
# SYSTEM PACKAGE TOOLS
# ===============================


@mcp_tool_handler(
    description='List system package entries (installed via package manager) on a specific server. Use this to audit installed OS-level packages.'
)
async def list_system_package_entries(
    server_id: str,
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List system package entries on a server.

    Args:
        server_id: Server ID to list packages for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        System package entries list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {'server': server_id}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/packages/system/entries/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Install a system package on a server via the package manager. Specify the package name and optionally a version.'
)
async def install_system_package(
    server_id: str,
    package_name: str,
    workspace: str,
    version: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Install a system package on a server.

    Args:
        server_id: Server ID to install the package on
        package_name: Name of the package to install
        workspace: Workspace name. Required parameter
        version: Specific version to install (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Package installation response
    """
    token = kwargs.get('token')

    package_data: dict[str, Any] = {
        'server': server_id,
        'name': package_name,
    }

    if version is not None:
        package_data['version'] = version

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/packages/system/entries/',
        token=token,
        data=package_data,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Remove a system package entry by its ID. Use list_system_package_entries to find the entry ID first.'
)
async def remove_system_package(
    entry_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Remove a system package entry.

    Args:
        entry_id: Package entry ID to remove
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Package removal response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/packages/system/entries/{entry_id}/',
        token=token,
    )

    return success_response(
        data=result, entry_id=entry_id, region=region, workspace=workspace
    )


# ===============================
# PYTHON PACKAGE TOOLS
# ===============================


@mcp_tool_handler(
    description='List Python packages installed on a specific server. Use this to audit Python dependencies.'
)
async def list_python_packages(
    server_id: str,
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List Python packages on a server.

    Args:
        server_id: Server ID to list Python packages for
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Python packages list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {'server': server_id}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/packages/python/entries/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Install a Python package on a server. Specify the package name and optionally a version.'
)
async def install_python_package(
    server_id: str,
    package_name: str,
    workspace: str,
    version: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Install a Python package on a server.

    Args:
        server_id: Server ID to install the package on
        package_name: Name of the Python package to install
        workspace: Workspace name. Required parameter
        version: Specific version to install (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Python package installation response
    """
    token = kwargs.get('token')

    package_data: dict[str, Any] = {
        'server': server_id,
        'name': package_name,
    }

    if version is not None:
        package_data['version'] = version

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/packages/python/entries/',
        token=token,
        data=package_data,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Remove a Python package entry by its ID. Use list_python_packages to find the entry ID first.'
)
async def remove_python_package(
    entry_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Remove a Python package entry.

    Args:
        entry_id: Python package entry ID to remove
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Python package removal response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/packages/python/entries/{entry_id}/',
        token=token,
    )

    return success_response(
        data=result, entry_id=entry_id, region=region, workspace=workspace
    )
