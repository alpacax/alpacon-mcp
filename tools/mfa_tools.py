"""MFA step-up tools that show Alpacon's MFA link as an MCP App panel.
Remote mode only: Alpacon serves the link and its completion to an Auth0 JWT alone."""

import json
from pathlib import Path
from typing import Annotated

from mcp.server.apps import APP_MIME_TYPE
from mcp.server.mcpserver.resources import TextResource
from mcp.types import CallToolResult, TextContent

from server import mcp
from utils.api_call import http_call_response
from utils.client_surfaces import apps_declaration
from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler, require_jwt_auth
from utils.http_client import http_client
from utils.mfa_link import (
    MFA_COMPLETION_ENDPOINT,
    MFAAlreadyDone,
    MFALink,
    MFALinkRaised,
    MFALinkUnusable,
    fetch_mfa_link,
)
from utils.mfa_step_up import lead
from utils.tool_annotations import ADDITIVE, READ_ONLY
from utils.types import ToolResponse

MFA_APP_URI = 'ui://alpacon/mfa'
# Result _meta stays out of the model's context; structuredContent may not.
MFA_LINK_META_KEY = 'alpacon/mfa'

# show_mfa never knows how much of the refused call ran; its mfa_required result does.
_RETRY = (
    "then retry as the refused call's own mfa_required result says; it may allow only "
    'part of the call again.'
)
_LINK_SHOWN = (
    'The Authenticate panel is showing the MFA link. Tell the person to press '
    'Authenticate and wait until the panel reports MFA complete, ' + _RETRY + ' If '
    'they say the panel cannot open the link, tell them to copy the link the panel '
    'shows instead; do not call show_mfa again.'
)
_NO_LINK = 'Failed to get the MFA link'

# The SDK forbids a CallToolResult union; the metadata keeps the dict output schema.
MFAToolResult = Annotated[CallToolResult, ToolResponse]

mcp.add_resource(
    TextResource(
        uri=MFA_APP_URI,
        name='mfa_app',
        title='Alpacon MFA',
        description='The Authenticate panel show_mfa renders.',
        mime_type=APP_MIME_TYPE,
        text=Path(__file__).with_name('mfa_app.html').read_text(encoding='utf-8'),
    )
)


def _tool_result(
    response: ToolResponse, meta: dict[str, object] | None = None
) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type='text', text=json.dumps(response, indent=2))],
        structured_content=response,
        _meta=meta,
    )


@mcp_tool_handler(
    description=(
        'Show the user an Authenticate button for a fresh MFA check, in a panel the '
        'client renders as an MCP App. When to use: right after a tool returned '
        'status="mfa_required" whose message names show_mfa; pass the same '
        'workspace and region. Returns status="mfa_link_shown" while the panel holds '
        'the link; otherwise the refused call\'s own shape, status="mfa_required" '
        'with mfa_url to show as text. Returns completed=true when MFA is already '
        'fresh. Each call mints a single-use link.'
    ),
    annotations=ADDITIVE,
    meta={
        'ui': {'resourceUri': MFA_APP_URI},
        'anthropic/searchHint': 'mfa step-up authenticate verify panel',
    },
)
@require_jwt_auth
async def show_mfa(workspace: str, region: str = '', **kwargs: str) -> MFAToolResult:
    """Fetch Alpacon's MFA link; on an MCP Apps client it rides in result _meta alone."""
    ids = {'region': region, 'workspace': workspace}
    outcome = await fetch_mfa_link(
        http_client, region=region, workspace=workspace, token=kwargs.get('token')
    )
    match outcome:
        case MFALinkRaised():
            return _tool_result(error_response(_NO_LINK, **ids))
        case MFALinkUnusable(body=body):
            return _tool_result(
                unwrap_http_result(body, default_message=_NO_LINK, **ids)
                or error_response('Alpacon answered without an MFA link', **ids)
            )
        case MFAAlreadyDone():
            message = lead(outcome, names_show_mfa=False) + _RETRY
            return _tool_result(
                success_response(completed=True, message=message, **ids)
            )
        case MFALink(url=url):
            apps = apps_declaration()
            meta: dict[str, object] = {MFA_LINK_META_KEY: {'mfa_url': url}}
            if apps == 'declared':
                return _tool_result(
                    {'status': 'mfa_link_shown', 'message': _LINK_SHOWN, **ids}, meta
                )
            message = lead(outcome, names_show_mfa=False) + _RETRY
            # unknown: a pre-2026-07-28 host declares nothing yet may render the panel.
            return _tool_result(
                {'status': 'mfa_required', 'mfa_url': url, 'message': message, **ids},
                meta if apps == 'unknown' else None,
            )


@mcp_tool_handler(
    description=(
        'Report whether the MFA check show_mfa started is complete, as data.completed '
        'true or false. Called by the show_mfa panel while it waits, not by the model.'
    ),
    annotations=READ_ONLY,
    meta={'ui': {'resourceUri': MFA_APP_URI, 'visibility': ['app']}},
)
@require_jwt_auth
async def get_mfa_completion(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=MFA_COMPLETION_ENDPOINT,
        token=kwargs.get('token'),
        default_message='Failed to read MFA completion',
    )
