"""Command pre-approval ledger tools for Alpacon MCP server.

On a workspace whose command ACL surface is `ai`, the pre-approvals that let a
token run a command without a human approval live on the command pre-approval
ledger rather than on the workspace server (the "Pre-approved commands" card in
the web console). The ledger is its own service: it takes a person's token for
its own audience, never an API or service token, and only a Command ACL admin
of the workspace may change it. `utils.ledger_auth` obtains that token.

A workspace whose surface is `upstream` keeps using the command ACL tools in
`security_tools`; every tool here refuses it and says so. Any transport other
than stdio is refused too, before the sign-in cache is touched: that cache is
per process, and a network transport may share a process between callers.
"""

import json
from http import HTTPStatus
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field

from utils.common import (
    build_list_params,
    error_response,
    is_auth_enabled,
    is_stdio_transport,
    success_response,
    unwrap_http_result,
)
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.ledger_auth import (
    LedgerTarget,
    ledger_authorizer,
    ledger_base_url,
)
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY
from utils.types import (
    JsonValue,
    QueryParams,
    RequestBody,
    ToolErrorResponse,
    ToolResponse,
)

_API_AUTH_ENV = '/api/auth/env/'
_API_ACL = '/api/acl/'

# Mirrors the ledger's own batch bound.
_BULK_MAX_ENTRIES = 200

SURFACE_AI = 'ai'
SURFACE_UPSTREAM = 'upstream'

_UPSTREAM_SURFACE_MESSAGE = (
    'This workspace manages command ACLs on the workspace server, not on the '
    'command pre-approval ledger (command_acl_surface is "upstream"). Use '
    'list_command_acls, create_command_acl, update_command_acl and '
    'delete_command_acl instead.'
)
_STDIO_ONLY_MESSAGE = (
    'Managing the command pre-approval ledger needs a local stdio MCP server: '
    "the ledger accepts only a person's own sign-in, and a network transport "
    '(SSE or streamable-http) may share one process between several callers, '
    "so it could hand one person's sign-in to another. A Command ACL admin "
    "can manage the entries under Pre-approved commands on the service token's "
    'page in the web console.'
)


class LedgerEntryInput(TypedDict):
    """One pre-approval to issue.

    Only a service token may be given a new entry. `api_token` entries remain
    on the ledger for tokens that already had them, so the list and revoke
    tools still reach them, but a personal API token gets no new command list.
    """

    # A plain string rather than a one-value Literal: the SDK validates the
    # schema before the tool runs, and a const would refuse 'api_token' with a
    # bare literal_error instead of the reason issue_ledger_entries gives.
    principal_type: Annotated[
        str,
        Field(
            description=(
                "Must be 'service_token'. A personal API token has no command "
                "list on the ledger, so 'api_token' is refused."
            ),
        ),
    ]
    principal_id: str
    command_pattern: str
    username: str
    groupname: NotRequired[str]
    server_ids: NotRequired[list[str]]
    expires_at: NotRequired[str | None]
    enabled: NotRequired[bool]


async def _ledger_target(
    region: str, workspace: str, token: str | None
) -> LedgerTarget | ToolErrorResponse:
    """Read the workspace's ACL surface and Auth0 settings; refuse what cannot reach the ledger."""
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_AUTH_ENV,
        token=token,
        params={'client': 'cli'},
    )
    err = unwrap_http_result(
        result,
        default_message='Failed to read the workspace authentication settings',
        region=region,
        workspace=workspace,
    )
    if err:
        return err
    env = result if isinstance(result, dict) else {}

    # A server that predates the ledger does not send the field, and it
    # manages command ACLs itself.
    surface = env.get('command_acl_surface') or SURFACE_UPSTREAM
    if surface != SURFACE_AI:
        return error_response(
            _UPSTREAM_SURFACE_MESSAGE,
            command_acl_surface=surface,
            region=region,
            workspace=workspace,
        )

    # An unset transport means a caller outside prepare(), and fails closed.
    if is_auth_enabled() or not is_stdio_transport():
        return error_response(
            _STDIO_ONLY_MESSAGE,
            command_acl_surface=surface,
            region=region,
            workspace=workspace,
        )

    auth0 = env.get('auth0')
    auth0 = auth0 if isinstance(auth0, dict) else {}
    fields = ('domain', 'client_id', 'schema_name', 'workspace_id')
    if auth0.get('method') != 'auth0' or not all(auth0.get(f) for f in fields):
        return error_response(
            'This workspace does not sign in through Auth0, so the command '
            'pre-approval ledger cannot authorize anyone here.',
            command_acl_surface=surface,
            region=region,
            workspace=workspace,
        )

    return LedgerTarget(
        domain=str(auth0['domain']),
        client_id=str(auth0['client_id']),
        org_name=str(auth0['schema_name']),
        workspace_id=str(auth0['workspace_id']),
    )


async def _ledger_request(
    target: LedgerTarget,
    method: str,
    path: str,
    *,
    region: str,
    workspace: str,
    default_message: str,
    json_data: RequestBody | None = None,
    params: QueryParams | None = None,
    **id_context: object,
) -> ToolResponse:
    """Call the ledger as the person who authorized it, and shape the response."""
    context = {'region': region, 'workspace': workspace, **id_context}

    reused = ledger_authorizer.has_token(target)
    ledger_token = await ledger_authorizer.token_for(target)
    if isinstance(ledger_token, dict):
        return {**ledger_token, **context}

    result = await http_client.request(
        method,
        f'{ledger_base_url()}{_API_ACL}{path}',
        token=ledger_token,
        json_data=json_data,
        params=params,
    )

    if (
        isinstance(result, dict)
        and result.get('status_code') == HTTPStatus.UNAUTHORIZED
    ):
        # The token is useless either way.
        ledger_authorizer.forget(target)
        detail = _error_detail(result)
        if not reused:
            # Issued by this very call, so a new sign-in would only be refused
            # again: the ledger does not accept what the sign-in service mints
            # here. Say so instead of handing out another link.
            return error_response(
                'The command pre-approval ledger refused the token this sign-in '
                'just issued. Check that ALPACON_MCP_LEDGER_URL and '
                'ALPACON_MCP_LEDGER_AUDIENCE name the same ledger (both unset '
                'uses the default). Calling again starts a new sign-in.',
                status_code=HTTPStatus.UNAUTHORIZED,
                detail=detail,
                **context,
            )
        # A cached token expired or was revoked early; sign in again.
        restarted = await ledger_authorizer.token_for(target)
        if isinstance(restarted, dict):
            return {**restarted, 'detail': detail, **context}

    err = unwrap_http_result(result, default_message=default_message, **context)
    if err:
        detail = _error_detail(result)
        if detail is not None:
            err['detail'] = detail
        return err
    return success_response(data=result, **context)


async def _ledger_call(
    method: str,
    path: str,
    *,
    region: str,
    workspace: str,
    token: str | None,
    default_message: str,
    scope_to_workspace: Literal['query', 'body'] | None = None,
    json_data: RequestBody | None = None,
    params: QueryParams | None = None,
    **id_context: object,
) -> ToolResponse:
    """Resolve the ledger target, then call it.

    `scope_to_workspace` names where the workspace's id goes: a list names it
    in the query and a write in the body, and the ledger refuses either
    without it.
    """
    target = await _ledger_target(region, workspace, token)
    if isinstance(target, dict):
        return target
    if scope_to_workspace == 'query':
        params = {'workspace_id': target.workspace_id, **(params or {})}
    elif scope_to_workspace == 'body':
        json_data = {'workspace_id': target.workspace_id, **(json_data or {})}

    return await _ledger_request(
        target,
        method,
        path,
        region=region,
        workspace=workspace,
        default_message=default_message,
        json_data=json_data,
        params=params,
        **id_context,
    )


def _error_detail(result: object) -> JsonValue:
    """The ledger's error body, which names the field and the reason."""
    raw = result.get('response') if isinstance(result, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        body: JsonValue = json.loads(raw)
    except ValueError:
        return None
    return body


@mcp_tool_handler(
    description=(
        'Check whether this workspace manages command pre-approvals on the '
        'command pre-approval ledger, and whether the signed-in person is a '
        'Command ACL admin of it. When to use: before listing or changing '
        'Pre-approved commands. A workspace reporting command_acl_surface '
        '"upstream" uses list_command_acls and its siblings instead. On the '
        'ledger, the first call returns status "authorization_required" with a '
        'link a person must open; call again after they sign in.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'pre-approved commands ledger admin capability'},
)
async def get_ledger_capability(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Report the command ACL surface and the caller's ledger authority.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        `command_acl_surface`, and on the ledger `is_ledger_admin`,
        `administers_workspace` and `workspace_ids`
    """
    token = kwargs.get('token')
    target = await _ledger_target(region, workspace, token)
    if isinstance(target, dict):
        if target.get('command_acl_surface') == SURFACE_UPSTREAM:
            return success_response(
                command_acl_surface=SURFACE_UPSTREAM,
                message=_UPSTREAM_SURFACE_MESSAGE,
                region=region,
                workspace=workspace,
            )
        return target

    result = await _ledger_request(
        target,
        'GET',
        'me/',
        region=region,
        workspace=workspace,
        default_message='Failed to read the command pre-approval ledger capability',
    )
    if result.get('status') != 'success':
        return result
    data = result.get('data')
    data = data if isinstance(data, dict) else {}
    workspace_ids = [str(w) for w in data.get('workspace_ids') or []]
    return success_response(
        command_acl_surface=SURFACE_AI,
        is_ledger_admin=bool(data.get('is_ledger_admin')),
        administers_workspace=target.workspace_id in workspace_ids,
        workspace_id=target.workspace_id,
        workspace_ids=workspace_ids,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description=(
        "List the workspace's active command pre-approvals (Pre-approved "
        'commands) on the command pre-approval ledger. Requires a Command ACL '
        'admin. Related: get_ledger_capability, issue_ledger_entries, '
        'revoke_ledger_entry, disable_ledger_entry.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'pre-approved commands ledger list entries acl'},
)
async def list_ledger_entries(
    workspace: str,
    region: str = '',
    principal_type: Literal['service_token', 'api_token'] | None = None,
    principal_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: str,
) -> ToolResponse:
    """List active ledger entries.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided
        principal_type: Only entries for this kind of token (optional).
            'api_token' lists entries a personal API token kept from before;
            none can be issued
        principal_id: Only entries for this token's UUID (optional)
        page: Page number (optional)
        page_size: Entries per page, at most 200 (optional)

    Returns:
        A page with `count`, `current`, `next`, `previous`, `last`, `results`
    """
    params = build_list_params(
        page=page,
        page_size=page_size,
        principal_type=principal_type,
        principal_id=principal_id,
    )

    return await _ledger_call(
        'GET',
        'entries/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        scope_to_workspace='query',
        params=params,
        default_message='Failed to list command pre-approval ledger entries',
    )


@mcp_tool_handler(
    description=(
        'Issue one or more command pre-approvals on the command pre-approval '
        'ledger, so a service token may run a matching command without a human '
        'approval. Service tokens only: a personal API token has no command '
        'list on the ledger, so an api_token entry cannot be issued; the ones a '
        "token already has are listed with list_ledger_entries(principal_type='api_token') "
        'and revoked with revoke_ledger_entry. All or nothing: one rejected entry refuses the batch. An '
        'entry is never edited; revoke it and issue a new one. Requires a '
        'Command ACL admin. Related: list_ledger_entries, revoke_ledger_entry.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'pre-approved commands ledger issue add acl'},
)
async def issue_ledger_entries(
    workspace: str,
    entries: list[LedgerEntryInput],
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Issue ledger entries in one request.

    Args:
        workspace: Workspace name. Required parameter
        entries: 1 to 200 entries. Each takes `principal_type`
            ('service_token' only), `principal_id` (the service token's UUID),
            `command_pattern`, and `username` ('*' for any user). Optional:
            `groupname`, `server_ids` (UUIDs; omit to apply on every server),
            `expires_at` (ISO 8601) and `enabled`
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        The issued entries, each with its `id` and any `warnings`
    """
    if not entries:
        return error_response('entries must not be empty')
    if len(entries) > _BULK_MAX_ENTRIES:
        return error_response(
            f'entries holds {len(entries)} items; at most {_BULK_MAX_ENTRIES} '
            'may be issued in one call'
        )
    refused = [
        index
        for index, entry in enumerate(entries)
        if entry.get('principal_type') != 'service_token'
    ]
    if refused:
        return error_response(
            'Only a service token can be given a command pre-approval; a '
            'personal API token has no command list on the ledger. Entries '
            f'at index {refused} name another principal_type.',
            region=region,
            workspace=workspace,
        )

    return await _ledger_call(
        'POST',
        'entries/bulk/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        scope_to_workspace='body',
        json_data={'entries': [dict(e) for e in entries]},
        default_message='Failed to issue command pre-approval ledger entries',
    )


@mcp_tool_handler(
    description=(
        'Revoke one command pre-approval on the command pre-approval ledger. '
        'The entry stops matching at once and stays readable for audit. '
        'Requires a Command ACL admin. Related: revoke_ledger_entries (several), '
        'disable_ledger_entry (reversible).'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'pre-approved commands ledger revoke delete'},
)
async def revoke_ledger_entry(
    workspace: str, entry_id: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Revoke one ledger entry.

    Args:
        workspace: Workspace name. Required parameter
        entry_id: Ledger entry UUID
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Revocation response
    """
    return await _ledger_call(
        'DELETE',
        f'entries/{entry_id}/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        default_message='Failed to revoke the command pre-approval ledger entry',
        entry_id=entry_id,
    )


@mcp_tool_handler(
    description=(
        'Revoke several command pre-approvals on the command pre-approval '
        'ledger in one request. All or nothing: an id that is unknown, already '
        'revoked or outside your authority refuses the batch. Requires a '
        'Command ACL admin. Related: revoke_ledger_entry, list_ledger_entries.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'pre-approved commands ledger bulk revoke'},
)
async def revoke_ledger_entries(
    workspace: str, entry_ids: list[str], region: str = '', **kwargs: str
) -> ToolResponse:
    """Revoke several ledger entries.

    Args:
        workspace: Workspace name. Required parameter
        entry_ids: 1 to 200 ledger entry UUIDs
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        `revoked`: how many entries were revoked
    """
    if not entry_ids:
        return error_response('entry_ids must not be empty')
    if len(entry_ids) > _BULK_MAX_ENTRIES:
        return error_response(
            f'entry_ids holds {len(entry_ids)} items; at most '
            f'{_BULK_MAX_ENTRIES} may be revoked in one call'
        )

    return await _ledger_call(
        'POST',
        'entries/bulk/delete/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        json_data={'ids': list(entry_ids)},
        default_message='Failed to revoke the command pre-approval ledger entries',
    )


async def _set_entry_enabled(
    action: Literal['disable', 'enable'],
    workspace: str,
    entry_id: str,
    region: str,
    token: str | None,
) -> ToolResponse:
    return await _ledger_call(
        'POST',
        f'entries/{entry_id}/{action}/',
        region=region,
        workspace=workspace,
        token=token,
        default_message=f'Failed to {action} the command pre-approval ledger entry',
        entry_id=entry_id,
    )


@mcp_tool_handler(
    description=(
        'Stop one command pre-approval from matching without revoking it. '
        'Reversible with enable_ledger_entry. Requires a Command ACL admin.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'pre-approved commands ledger disable pause'},
)
async def disable_ledger_entry(
    workspace: str, entry_id: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Disable one ledger entry.

    Args:
        workspace: Workspace name. Required parameter
        entry_id: Ledger entry UUID
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        The entry with `enabled: false`
    """
    return await _set_entry_enabled(
        'disable', workspace, entry_id, region, kwargs.get('token')
    )


@mcp_tool_handler(
    description=(
        'Let a disabled command pre-approval match again. Requires a Command '
        'ACL admin. Related: disable_ledger_entry.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'pre-approved commands ledger enable resume'},
)
async def enable_ledger_entry(
    workspace: str, entry_id: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Enable one ledger entry.

    Args:
        workspace: Workspace name. Required parameter
        entry_id: Ledger entry UUID
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        The entry with `enabled: true`
    """
    return await _set_entry_enabled(
        'enable', workspace, entry_id, region, kwargs.get('token')
    )


@mcp_tool_handler(
    description=(
        "List the workspace's Command ACL admins: the people who may change its "
        'command pre-approval ledger. Requires a Command ACL admin. Related: '
        'grant_ledger_admin, revoke_ledger_admin.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'command acl admin ledger list'},
)
async def list_ledger_admins(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs: str,
) -> ToolResponse:
    """List the workspace's Command ACL admins.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number (optional)
        page_size: Admins per page, at most 200 (optional)

    Returns:
        A page of admins, each with `id`, `subject` and `email`
    """
    params = build_list_params(page=page, page_size=page_size)

    return await _ledger_call(
        'GET',
        'admins/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        scope_to_workspace='query',
        params=params,
        default_message='Failed to list Command ACL admins',
    )


@mcp_tool_handler(
    description=(
        'Make a person a Command ACL admin of the workspace, so they may change '
        'its command pre-approval ledger. Takes the Auth0 user id (subject); a '
        'machine principal is refused. Requires a Command ACL admin. Related: '
        'list_ledger_admins, revoke_ledger_admin.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'command acl admin ledger grant add'},
)
async def grant_ledger_admin(
    workspace: str,
    subject: str,
    email: str = '',
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Grant Command ACL admin.

    Args:
        workspace: Workspace name. Required parameter
        subject: The person's Auth0 user id, e.g. 'auth0|abc123'
        email: The person's email, recorded for display (optional)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        The new admin record
    """
    if not subject.strip():
        return error_response('subject must not be empty')

    return await _ledger_call(
        'POST',
        'admins/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        scope_to_workspace='body',
        json_data={'subject': subject, 'email': email},
        default_message='Failed to grant Command ACL admin',
    )


@mcp_tool_handler(
    description=(
        'Remove a Command ACL admin from the workspace. The last admin cannot '
        'be removed; grant another first. Requires a Command ACL admin. '
        'Related: list_ledger_admins (find admin_id).'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'command acl admin ledger revoke remove'},
)
async def revoke_ledger_admin(
    workspace: str, admin_id: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Revoke Command ACL admin.

    Args:
        workspace: Workspace name. Required parameter
        admin_id: Admin record UUID from list_ledger_admins
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Revocation response
    """
    return await _ledger_call(
        'DELETE',
        f'admins/{admin_id}/',
        region=region,
        workspace=workspace,
        token=kwargs.get('token'),
        default_message='Failed to revoke Command ACL admin',
        admin_id=admin_id,
    )
