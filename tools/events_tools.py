"""Event management tools for Alpacon MCP server - Refactored version."""

from typing import Any

from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client


@mcp_tool_handler(description='List server events')
async def list_events(
    workspace: str,
    server_id: str | None = None,
    reporter: str | None = None,
    limit: int = 50,
    region: str = 'ap1',
    **kwargs,
) -> dict[str, Any]:
    """List events from servers."""
    token = kwargs.get('token')

    params = {'page_size': limit, 'ordering': '-added_at'}

    if server_id:
        params['server'] = server_id
    if reporter:
        params['reporter'] = reporter

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/events/events/',
        token=token,
        params=params,
    )

    return success_response(
        data=result,
        server_id=server_id,
        reporter=reporter,
        limit=limit,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(description='Get event details by ID')
async def get_event(
    event_id: str, workspace: str, region: str = 'ap1', **kwargs
) -> dict[str, Any]:
    """Get detailed information about a specific event."""
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/events/{event_id}/',
        token=token,
    )

    return success_response(
        data=result, event_id=event_id, region=region, workspace=workspace
    )


@mcp_tool_handler(description='Search events by criteria')
async def search_events(
    search_query: str,
    workspace: str,
    server_id: str | None = None,
    limit: int = 20,
    region: str = 'ap1',
    **kwargs,
) -> dict[str, Any]:
    """Search events by server name, reporter, record, or description."""
    token = kwargs.get('token')

    params = {'search': search_query, 'page_size': limit, 'ordering': '-added_at'}

    if server_id:
        params['server'] = server_id

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/events/events/',
        token=token,
        params=params,
    )

    return success_response(
        data=result,
        search_query=search_query,
        server_id=server_id,
        limit=limit,
        region=region,
        workspace=workspace,
    )
