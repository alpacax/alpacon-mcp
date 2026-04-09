"""Health check tool for MCP clients (stdio transport)."""

from typing import Any

from mcp.types import ToolAnnotations

from server import mcp
from utils.common import success_response


@mcp.tool(
    description='Check MCP server health status. Returns server version, uptime, authentication mode, and connection pool info. When to use: verifying the MCP server is running and reachable before making other calls. Note: No parameters required.',
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'health check status ping connectivity',
    },
)
async def health_check() -> dict[str, Any]:
    """Check MCP server health and return status information.

    This tool provides health status for stdio transport clients
    where the HTTP /health endpoint is not reachable.

    No parameters required - returns server health metrics including
    version, uptime, authentication status, and connection pool info.

    Returns:
        Health status dictionary with server metrics
    """
    from utils.health import get_health_info

    health = await get_health_info()
    return success_response(data=health)
