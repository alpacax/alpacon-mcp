"""Audit and logging tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client

# ===============================
# ACTIVITY LOG TOOLS
# ===============================


@mcp_tool_handler(description='List activity logs for auditing user and system actions')
async def list_activity_logs(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List activity logs.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Activity logs list response
    """
    token = kwargs.get('token')

    params = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/audit/activity/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get detailed information about a specific activity log entry'
)
async def get_activity_log(
    log_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get activity log details by ID.

    Args:
        log_id: Activity log entry ID
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Activity log details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/audit/activity/{log_id}/',
        token=token,
    )

    return success_response(
        data=result, log_id=log_id, region=region, workspace=workspace
    )


# ===============================
# HISTORY LOG TOOLS
# ===============================


@mcp_tool_handler(description='List server command execution logs from history')
async def list_server_logs(
    workspace: str,
    server_id: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List server command execution logs.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by server ID (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Server logs list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if server_id:
        params['server'] = server_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/history/logs/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(description='List WebFTP file transfer logs from history')
async def list_webftp_logs(
    workspace: str,
    server_id: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List WebFTP file transfer logs.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by server ID (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        WebFTP logs list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if server_id:
        params['server'] = server_id
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/history/webftp-logs/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )
