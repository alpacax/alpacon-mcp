"""Work Session management tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

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
        'Get details of a Work Session: status, scopes, servers, requester_type, expires_at. '
        'Related: work_session_list (list all sessions), work_session_timeline '
        '(chronological activity), work_session_close (end session).'
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
        '"pending", "approved", "active", "completed", "rejected", "cancelled", '
        '"expired", "revoked". '
        'Optional requester_type filter: "user" (human) or "agent" (AI agent). '
        'Related: work_session_create (create session), work_session_get (single session detail).'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'work session list history audit'},
)
async def work_session_list(
    workspace: str,
    status: str | None = None,
    requester_type: str | None = None,
    limit: int = 20,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """List Work Sessions with optional status and requester_type filtering."""
    token = kwargs.get('token')

    params: dict[str, str | int] = {'page_size': limit}
    if status:
        params['status'] = status
    if requester_type:
        params['requester_type'] = requester_type

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


@mcp_tool_handler(
    description=(
        'Update a Work Session (partial update). Only provided fields are sent. '
        'Pending sessions update immediately; approved/active sessions go through '
        'the modification flow and may return HTTP 202 when an approval request is queued. '
        'expires_at is only honored for pending sessions—for approved/active sessions '
        'it is ignored, so use work_session_extend instead. '
        'Terminal sessions (completed/rejected/cancelled/expired/revoked) cannot be updated. '
        'Related: work_session_get (check status), work_session_extend (extend expiry only).'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'work session update modify scopes servers description'
    },
)
async def work_session_update(
    session_id: str,
    workspace: str,
    title: str | None = None,
    description: str | None = None,
    scopes: list[str] | None = None,
    servers: list[str] | None = None,
    expires_at: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Partially update a Work Session."""
    token = kwargs.get('token')

    data: dict[str, str | list[str]] = {}
    if title is not None:
        data['title'] = title
    if description is not None:
        data['description'] = description
    if scopes is not None:
        data['scopes'] = scopes
    if servers is not None:
        data['servers'] = servers
    if expires_at is not None:
        data['expires_at'] = expires_at

    if not data:
        return error_response(
            'No fields to update. Provide at least one of: '
            'title, description, scopes, servers, expires_at.',
            session_id=session_id,
            region=region,
            workspace=workspace,
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/',
        token=token,
        data=data,
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to update Work Session',
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
        'Extend the expiry time of a Work Session. Only approved or active sessions '
        'can be extended, and the new expires_at must be later than the current one. '
        'Bound sudo policies are extended together. '
        'expires_at is an ISO 8601 datetime string. '
        'Related: work_session_update (modify other fields), work_session_get (check current expiry).'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'work session extend expiry expires prolong'},
)
async def work_session_extend(
    session_id: str,
    workspace: str,
    expires_at: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Extend a Work Session's expiry time."""
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/extend/',
        token=token,
        data={'expires_at': expires_at},
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to extend Work Session',
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
        'Get the unified chronological timeline of a Work Session: commands, '
        'file transfers, websh activity, and sudo grants in execution order. '
        'Set include_records=False to omit websh terminal records for a lighter response. '
        'Related: work_session_get (session detail), list_session_analyses / '
        'get_session_analysis_detail (AI security analysis results).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'work session timeline history commands chronological'
    },
)
async def work_session_timeline(
    session_id: str,
    workspace: str,
    include_records: bool = True,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get the unified timeline of a Work Session."""
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/timeline/',
        token=token,
        params={'include_records': 'true' if include_records else 'false'},
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to get Work Session timeline',
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
        'Manually trigger AI security analysis for a terminal Work Session '
        '(completed, expired, or revoked). Analysis runs automatically on '
        'work_session_close; use this to re-run a failed analysis. '
        'Set force=True to retry an analysis stuck in pending/processing '
        '(the server enforces a minimum age guard and never discards completed results). '
        'Related: list_session_analyses / get_session_analysis_detail (view results).'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'work session analyze AI security analysis retry'},
)
async def work_session_analyze(
    session_id: str,
    workspace: str,
    force: bool = False,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Manually trigger AI analysis for a terminal Work Session."""
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/analyze/',
        token=token,
        data={},
        params={'force': 'true'} if force else None,
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to trigger Work Session analysis',
        session_id=session_id,
        region=region,
        workspace=workspace,
    ):
        return err

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )
