"""Work Session management tools for Alpacon MCP server."""

from typing import Annotated

from pydantic import Field

from utils.api_call import http_call_response
from utils.command_rejection import attach_rejection
from utils.common import (
    build_list_params,
    error_response,
    exclude_none,
    pending_approval_response,
    success_response,
    unwrap_http_result,
)
from utils.cursor_pagination import (
    CURSOR_DESCRIPTION,
    CURSOR_WALK_DESCRIPTION,
    cursor_list_response,
)
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY
from utils.types import OptionalServerIds, ServerIds, SessionId, ToolResponse

_API_SESSIONS = '/api/work-sessions/sessions/'

# The paged timeline refuses a `page_size` above this with a 400.
_TIMELINE_MAX_PAGE_SIZE = 500

# `include_records` stays declared because the SDK drops an argument the
# published schema does not name before the call, where it could not be refused.
_INCLUDE_RECORDS_REFUSED = (
    'omit it. The paged timeline carries no recordings, so include_records '
    'cannot be honoured and is refused rather than dropped. Read a recording '
    'with work_session_records instead, which pages one websh session of this '
    'work session, named by the `id` of a `websh_session` item here.'
)

# The record page's own bounds. The server reads a page of recording chunks,
# each up to 128 KiB raw, so these are far below the timeline's.
_RECORD_MAX_PAGE_SIZE = 16
_RECORD_DEFAULT_PAGE_SIZE = 8

_INCLUDE_RECORDS_DESCRIPTION = (
    'Do not pass it: the timeline carries no recordings, so any value is refused '
    'rather than quietly ignored. Read a recording with work_session_records.'
)

_WEBSH_SESSION_ID_DESCRIPTION = (
    'Websh session to read: the `id` of a `websh_session` item on '
    'work_session_timeline, so call that first to learn which sessions a Work '
    'Session recorded.'
)

_RECORDS_CURSOR_DESCRIPTION = (
    "The previous page's `data.next`, to read the page after it; stop when `next` "
    'is null. It is bound to the websh session it was minted for, so keep sending '
    'the same websh_session_id while paging one recording.'
)

_RECORDS_PAGE_SIZE_DESCRIPTION = (
    f'1 to {_RECORD_MAX_PAGE_SIZE}, default {_RECORD_DEFAULT_PAGE_SIZE}; a value '
    'outside that is refused before any request.'
)

_ISO_EXPIRES_DESCRIPTION = 'ISO 8601 datetime string.'

_UPDATE_EXPIRES_DESCRIPTION = (
    'ISO 8601 datetime string. Honored only for pending sessions; for approved or '
    'active ones it is ignored, so use work_session_extend instead.'
)

_EXTEND_EXPIRES_DESCRIPTION = (
    'New expiry as an ISO 8601 datetime string; it must be later than the current one.'
)

_EXTEND_REASON_DESCRIPTION = (
    'Required on every request: a short justification for why more time is needed, '
    'shown to the human approver when this extension needs a decision.'
)

_TARGET_ACCOUNT_DESCRIPTION = (
    'The single OS account the commands will run as, such as "root". Set it whenever '
    'you intend to run commands as another account, so that account is approved '
    'together with the session, then pass the same account as username to '
    'execute_command and execute_file; omit it to run as the default account. '
    'Running directly as root is declared here; the "sudo" scope is for elevation '
    'from another account.'
)

_STATUS_FILTER_DESCRIPTION = (
    'Filter by status: "pending", "approved", "active", "completed", "rejected", '
    '"cancelled", "expired" or "revoked".'
)

_REQUESTER_TYPE_DESCRIPTION = (
    'Filter by requester: "user" (human) or "agent" (AI agent).'
)

_TITLE_DESCRIPTION = 'Pass an empty string to clear it.'

_FORCE_DESCRIPTION = (
    'Retry an analysis stuck in pending or processing; the server enforces a '
    'minimum age guard and never discards completed results.'
)

_SCOPES_DESCRIPTION = (
    'Operations the session allows: "command" (execute_command, execute_file), '
    '"webftp" (file transfers), "tunnel" (port forwarding), "sudo" (privilege elevation). '
    'Request "sudo" only when the work genuinely requires root.'
)

_SESSION_DESCRIPTION = (
    'What you are doing and why, written as prose for the human who approves the '
    'session. It is NOT a command list and nothing in it is executed—commands run '
    'via execute_command once the session is active. Be specific: name the targets, '
    'the action, and what will not be touched; a bare word like "maintenance" gives '
    'the approver nothing to decide on. Markdown supported.'
)


@mcp_tool_handler(
    description=(
        'Create a Work Session to scope all infrastructure actions under an auditable, '
        'approval-gated session. Every execute_command and file transfer should be linked '
        'to a Work Session—the server enforces this for MCP OAuth and browser-based auth. '
        'A new session usually lands in pending: this tool then returns '
        'status="pending_approval", and no command or file transfer runs in it until a '
        'human approves out-of-band (Alpacon web console or Slack). Do not open another '
        'session; call work_session_get and proceed once data.status is active, or stop '
        'if it is rejected, cancelled, expired, revoked, or completed, since those never become active. '
        'Related: work_session_close (end session), execute_command (pass work_session_id).'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'work session create audit approval scope intent'},
)
async def work_session_create(
    workspace: str,
    scopes: Annotated[list[str], Field(description=_SCOPES_DESCRIPTION)],
    servers: ServerIds,
    expires_at: Annotated[str, Field(description=_ISO_EXPIRES_DESCRIPTION)],
    description: Annotated[str, Field(description=_SESSION_DESCRIPTION)],
    title: str | None = None,
    region: str = '',
    target_account_username: Annotated[
        str | None, Field(description=_TARGET_ACCOUNT_DESCRIPTION)
    ] = None,
    **kwargs: str,
) -> ToolResponse:
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
    if target_account_username:
        data['target_account_username'] = target_account_username

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

    # A Work Session created by an agent commonly lands in `pending`: it must be
    # approved by a human out-of-band before any scoped action (command/file
    # transfer) is allowed (ADR 0015). Surface that as a structured
    # pending-approval signal so the agent waits/escalates instead of proceeding
    # to run commands against a session that is not yet active.
    if isinstance(result, dict) and result.get('status') == 'pending':
        session_id = result.get('id')
        return pending_approval_response(
            'This Work Session was created but is pending human approval. A '
            'human must approve it out-of-band (Alpacon web console or Slack) '
            'before any command or file transfer in this session will run. Call '
            'work_session_get and proceed only once data.status is active; stop if '
            'it is rejected, cancelled, expired, revoked, or completed.',
            category='WORK_SESSION_PENDING',
            data=result,
            session_id=session_id,
            region=region,
            workspace=workspace,
        )

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
    session_id: SessionId,
    workspace: str,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Complete a Work Session."""
    token = kwargs.get('token')

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/complete/',
        token=token,
        default_message='Failed to close Work Session',
        data={},
        session_id=session_id,
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
    session_id: SessionId,
    workspace: str,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Get detailed information about a specific Work Session."""
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/',
        token=token,
        default_message='Failed to get Work Session',
        session_id=session_id,
    )


@mcp_tool_handler(
    description=(
        'List Work Sessions in a workspace. '
        'Related: work_session_create (create session), work_session_get (single session detail).'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'work session list history audit'},
)
async def work_session_list(
    workspace: str,
    status: Annotated[str | None, Field(description=_STATUS_FILTER_DESCRIPTION)] = None,
    requester_type: Annotated[
        str | None, Field(description=_REQUESTER_TYPE_DESCRIPTION)
    ] = None,
    limit: int = 20,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """List Work Sessions with optional status and requester_type filtering."""
    token = kwargs.get('token')

    params = build_list_params(
        page_size=limit, status=status, requester_type=requester_type
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=_API_SESSIONS,
        token=token,
        default_message='Failed to list Work Sessions',
        params=params,
    )


# IDEMPOTENT_WRITE: repeated PATCH cannot stack approval requests (server WORK_SESSION_MOD_ALREADY_PENDING guard).
@mcp_tool_handler(
    description=(
        'Update a Work Session (partial update). Only provided fields are sent. '
        'Pending sessions update immediately; approved/active sessions go through '
        'the modification flow—when the server queues an approval request, this '
        'tool returns status="pending_approval" and the changes only apply after '
        'a human approves them out-of-band. '
        'Terminal sessions (completed/rejected/cancelled/expired/revoked) cannot be updated. '
        'Related: work_session_get (check status), work_session_extend (extend expiry only).'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'work session update modify scopes servers description'
    },
)
async def work_session_update(
    session_id: SessionId,
    workspace: str,
    title: Annotated[str | None, Field(description=_TITLE_DESCRIPTION)] = None,
    description: Annotated[str | None, Field(description=_SESSION_DESCRIPTION)] = None,
    scopes: Annotated[
        list[str] | None,
        Field(
            description='Replaces the whole scope list, so list every scope the '
            'session keeps. ' + _SCOPES_DESCRIPTION
        ),
    ] = None,
    servers: OptionalServerIds = None,
    expires_at: Annotated[
        str | None, Field(description=_UPDATE_EXPIRES_DESCRIPTION)
    ] = None,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Partially update a Work Session."""
    token = kwargs.get('token')

    data: dict[str, str | list[str]] = exclude_none(
        title=title,
        description=description,
        scopes=scopes,
        servers=servers,
        expires_at=expires_at,
    )

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

    # Queued modification (server 202): http_client hides 2xx status codes, so branch on the body marker (ADR 0015).
    if isinstance(result, dict) and result.get('pending_modification_request'):
        return pending_approval_response(
            'This update was queued as a modification request and is pending '
            'human approval. A human must approve it out-of-band (Alpacon web '
            'console or Slack) before the requested changes apply. Poll '
            'work_session_get and only rely on the new scopes/servers once '
            'pending_modification_request is cleared.',
            category='WORK_SESSION_MOD_PENDING',
            data=result,
            session_id=session_id,
            region=region,
            workspace=workspace,
        )

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Extend the expiry time of a Work Session. Only approved or active sessions '
        'can be extended. Bound sudo policies are extended together. '
        'Whether the extension applies immediately or waits for approval follows the '
        "workspace's approval policy, the same rule work_session_create uses: an "
        'auto-approve lane extends directly and this tool returns a normal success; '
        'any other lane queues an extension request instead, and this tool returns '
        'status="pending_approval"—the session keeps its prior expires_at until a '
        'human decides out-of-band. Poll work_session_get until expires_at changes to '
        'see the outcome. '
        'Related: work_session_update (modify other fields), work_session_get (check current expiry).'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'work session extend expiry expires prolong'},
)
async def work_session_extend(
    session_id: SessionId,
    workspace: str,
    expires_at: Annotated[str, Field(description=_EXTEND_EXPIRES_DESCRIPTION)],
    reason: Annotated[str, Field(description=_EXTEND_REASON_DESCRIPTION)],
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Extend a Work Session's expiry time."""
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/extend/',
        token=token,
        data={'expires_at': expires_at, 'reason': reason},
    )

    if err := unwrap_http_result(
        result,
        default_message='Failed to extend Work Session',
        session_id=session_id,
        region=region,
        workspace=workspace,
    ):
        return err

    # Queued extension (server 202): http_client hides 2xx status codes, so branch on the body marker (ADR 0015).
    if isinstance(result, dict) and result.get('pending_extension_request'):
        return pending_approval_response(
            'This extension was queued as an extension request and is pending '
            'human approval. A human must approve it out-of-band (Alpacon web '
            'console or Slack) before the new expiry applies; the approver may '
            'adjust the requested expiry. The session keeps its prior expires_at '
            'until then. Poll work_session_get and only rely on the new expiry '
            'once it changes.',
            category='WORK_SESSION_EXTENSION_PENDING',
            data=result,
            session_id=session_id,
            region=region,
            workspace=workspace,
        )

    return success_response(
        data=result, session_id=session_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Get the chronological timeline of a Work Session: commands, file '
        'transfers, websh activity, and sudo grants in execution order, oldest '
        f'first. {CURSOR_WALK_DESCRIPTION} An alpacon-server that predates the '
        'paged timeline ignores `cursor` and returns the whole session: that '
        'answer is `complete` with `stopped_because: unpaginated_server` even '
        'when a cursor was passed. The walk only reads forward, so a '
        'result stopped at the bound covers the start of the session and omits '
        'its most recent activity—do not read it as what the session ended up '
        'doing. The timeline carries no websh terminal recordings: it names the '
        'sessions that have one, as `websh_session` items whose `id` '
        'work_session_records then reads the recording of. A `command` item '
        'with a rejection_cause also carries rejection_hint, saying whom to ask. '
        'Related: work_session_get (session detail), work_session_records (one '
        "websh session's recording), list_session_analyses / "
        'get_session_analysis_detail (AI security analysis results).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'work session timeline history commands chronological'
    },
)
async def work_session_timeline(
    session_id: SessionId,
    workspace: str,
    region: str = '',
    cursor: Annotated[str | None, Field(description=CURSOR_DESCRIPTION)] = None,
    page_size: int | None = None,
    include_records: Annotated[
        bool | None, Field(description=_INCLUDE_RECORDS_DESCRIPTION)
    ] = None,
    **kwargs: str,
) -> ToolResponse:
    """Read the timeline, following the cursor up to the request bound; `page_size`
    is 1 to 500. `include_records` is refused: use work_session_records."""
    if include_records is not None:
        return format_validation_error(
            'include_records', include_records, _INCLUDE_RECORDS_REFUSED
        )
    if page_size is not None and page_size > _TIMELINE_MAX_PAGE_SIZE:
        return format_validation_error(
            'page_size', page_size, f'An integer from 1 to {_TIMELINE_MAX_PAGE_SIZE}.'
        )

    token = kwargs.get('token')

    # The paged shape ignores `include_records`; the whole-session shape a
    # pre-paging server answers with defaults it to true, up to 2 MiB of it.
    params = build_list_params(
        page_size=page_size, cursor=cursor, include_records='false'
    )

    response = await cursor_list_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/timeline/',
        token=token,
        default_message='Failed to get Work Session timeline',
        params=params,
        opt_in_pagination=True,
        session_id=session_id,
    )
    data = response.get('data')
    items = data.get('results') if isinstance(data, dict) else None
    for item in items if isinstance(items, list) else ():
        if isinstance(item, dict) and item.get('type') == 'command':
            attach_rejection(item)
    return response


@mcp_tool_handler(
    description=(
        'Read one page of a websh terminal recording captured inside a Work '
        "Session: the terminal's output in chunks, oldest first, as "
        '`{added_at, record}` items. The websh session must belong to this Work Session and '
        'must not be a tunnel, which records no terminal. '
        'One call reads one page and never pages on by itself. A page is cut by '
        'a byte budget as well as by page_size, so a page holding fewer items '
        'than asked for is not the end of the recording—only `next: null` is. '
        'Reading a recording is a paid-plan feature: a Free workspace, and a '
        "session older than the plan's audit window, is answered 402. "
        'Related: work_session_timeline (which sessions have a recording, and '
        'everything else that happened in the session), '
        'get_session_analysis_detail (the AI analysis of a session).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'work session websh recording record terminal replay'
    },
)
async def work_session_records(
    session_id: SessionId,
    websh_session_id: Annotated[str, Field(description=_WEBSH_SESSION_ID_DESCRIPTION)],
    workspace: str,
    region: str = '',
    cursor: Annotated[
        str | None, Field(description=_RECORDS_CURSOR_DESCRIPTION)
    ] = None,
    page_size: Annotated[
        int, Field(description=_RECORDS_PAGE_SIZE_DESCRIPTION)
    ] = _RECORD_DEFAULT_PAGE_SIZE,
    **kwargs: str,
) -> ToolResponse:
    """Read one page of a Websh recording; pass `next` back as `cursor`, and only
    `next: null` ends it. `page_size` is 1 to 16 (default 8); a byte cap can cut it."""
    if not 1 <= page_size <= _RECORD_MAX_PAGE_SIZE:
        return format_validation_error(
            'page_size', page_size, f'An integer from 1 to {_RECORD_MAX_PAGE_SIZE}.'
        )

    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/records/',
        token=token,
        default_message='Failed to read the Work Session recording',
        params=build_list_params(
            page_size=page_size, session=websh_session_id, cursor=cursor
        ),
        session_id=session_id,
        websh_session_id=websh_session_id,
    )


# IDEMPOTENT_WRITE: repeated triggers converge—the server replies
# already_exists instead of re-running a healthy or completed analysis.
@mcp_tool_handler(
    description=(
        'Manually trigger AI security analysis for a terminal Work Session '
        '(completed, expired, or revoked—rejected and cancelled sessions never '
        'activated, so there is nothing to analyze). Analysis runs automatically on '
        'work_session_close; use this to re-run a failed analysis. '
        'Related: list_session_analyses / get_session_analysis_detail (view results).'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'work session analyze AI security analysis retry'},
)
async def work_session_analyze(
    session_id: SessionId,
    workspace: str,
    force: Annotated[bool, Field(description=_FORCE_DESCRIPTION)] = False,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Manually trigger AI analysis for a terminal Work Session."""
    token = kwargs.get('token')

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_SESSIONS}{session_id}/analyze/',
        token=token,
        default_message='Failed to trigger Work Session analysis',
        data={},
        params={'force': 'true'} if force else None,
        session_id=session_id,
    )
