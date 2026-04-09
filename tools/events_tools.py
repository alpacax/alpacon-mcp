"""Event management tools for Alpacon MCP server - Refactored version."""

from typing import Any

from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import READ_ONLY


@mcp_tool_handler(
    description='List recent server events and activity logs ordered by newest first. Filterable by server ID and reporter. When to use: reviewing audit trails, operational history, or troubleshooting recent changes. Related: search_events (keyword search), get_event (full details).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'events activity log audit recent'},
)
async def list_events(
    workspace: str,
    server_id: str | None = None,
    reporter: str | None = None,
    limit: int = 50,
    region: str = '',
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


@mcp_tool_handler(
    description='Get full details of a specific event by its ID. Returns description, timestamp, associated server, reporter, and event record. When to use: need complete information about a particular event. Related: list_events (browse events), search_events (find events by keyword).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'event detail specific'},
)
async def get_event(
    event_id: str, workspace: str, region: str = '', **kwargs
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


@mcp_tool_handler(
    description='Search events by keyword query across server name, reporter, record, and description fields. Supports full-text search and can be further filtered by server ID. When to use: looking for specific events instead of browsing the full list. Related: list_events (browse without search), get_event (full details of a found event).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'events search find query keyword'},
)
async def search_events(
    search_query: str,
    workspace: str,
    server_id: str | None = None,
    limit: int = 20,
    region: str = '',
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
