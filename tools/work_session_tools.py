"""Work Session management tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, READ_ONLY

_API_SESSIONS = '/api/work-sessions/sessions/'


@mcp_tool_handler(
    description=(
        'Create a Work Session to scope all infrastructure actions under an auditable, '
        'approval-gated session. Every execute_command and file transfer should be linked '
        'to a Work Session—the server enforces this for MCP OAuth and browser-based auth '
        '(session_id is optional for other auth methods such as service tokens). '
        'description is the declared intent: the WHY of the session '
        '(e.g. "fix nginx 502 on prod-web-1"). '
        'scopes declares which operations are allowed: '
        '"command" (execute_command), "webftp" (file transfers), '
        '"websh" (interactive terminal), "tunnel" (port forwarding), "sudo" (privilege elevation). '
        'servers is the list of target server UUIDs. '
        'expires_at is an ISO 8601 datetime string. '
        'Related: work_session_close (end session), execute_command (pass session_id).'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'work session create audit approval scope intent'},
)
async def work_session_create(
    workspace: str,
    scopes: list[str],
    servers: list[str],
    expires_at: str,
    description: str,
    title: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a Work Session for auditable, approval-gated infrastructure access."""
    token = kwargs.get('token')

    data: dict[str, str | list[str]] = {
        'requester_type': 'agent',
        'scopes': scopes,
        'servers': servers,
        'expires_at': expires_at,
        'description': description,
    }
    if title:
        data['title'] = title

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_SESSIONS,
        token=token,
        data=data,
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to create Work Session',
        region=region,
        workspace=workspace,
    ):
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Mark a Work Session as completed and trigger AI security analysis (Pass 1–4). '
        'Call after all commands and file transfers for this session are done. '
        'Related: work_session_create (create session), work_session_get (check status).'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'work session close complete end finish'},
)
async def work_session_close(
    session_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Complete a Work Session."""
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/complete/',
        token=token,
        data={},
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to close Work Session',
        session_id=session_id,
        region=region,
        workspace=workspace,
    ):
        return err

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Get details of a Work Session: status, scopes, servers, timeline, auth_method. '
        'Related: work_session_list (list all sessions), work_session_close (end session).'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'work session get detail status timeline'},
)
async def work_session_get(
    session_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get detailed information about a specific Work Session."""
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/',
        token=token,
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to get Work Session',
        session_id=session_id,
        region=region,
        workspace=workspace,
    ):
        return err

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'List Work Sessions in a workspace. Optional status filter: '
        '"pending", "active", "completed", "rejected", "cancelled", "expired". '
        'Optional auth_method filter: "web", "cli", "service_token", "mcp_oauth". '
        'Related: work_session_create (create session), work_session_get (single session detail).'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'work session list history audit'},
)
async def work_session_list(
    workspace: str,
    status: str | None = None,
    auth_method: str | None = None,
    limit: int = 20,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """List Work Sessions with optional status and auth_method filtering."""
    token = kwargs.get('token')

    params: dict[str, str | int] = {'page_size': limit}
    if status:
        params['status'] = status
    if auth_method:
        params['auth_method'] = auth_method

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_SESSIONS,
        token=token,
        params=params,
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to list Work Sessions',
        region=region,
        workspace=workspace,
    ):
        return err

    return success_response(data=result, region=region, workspace=workspace)
