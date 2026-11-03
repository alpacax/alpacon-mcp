"""
Which MCP surfaces the connected client declared, logged on every tools/call, and the
round a retry echoes back. apps means the extension lists the MCP App HTML type.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import ClientCapabilities, InputResponseRequestParams, InputResponses
from pydantic import ValidationError

from utils.logger import get_logger

logger = get_logger('client_surfaces')

# The first version that sends capabilities on every request rather than only once.
PER_REQUEST_CAPABILITIES_VERSION = '2026-07-28'

# unknown: no capabilities at tool time (a pre-2026-07-28 stateless request).
type Declaration = Literal['declared', 'absent', 'unknown']


@dataclass(frozen=True)
class ClientSurfaces:
    url_elicitation: Declaration
    apps: Declaration


@dataclass(frozen=True)
class ToolCallRound:
    """One tools/call round: what the client can show, and what a retry echoed back."""

    protocol_version: str
    surfaces: ClientSurfaces
    request_state: str | None = None  # plaintext: the SDK verified and unsealed it
    input_responses: InputResponses = field(default_factory=dict)


_round: ContextVar[ToolCallRound | None] = ContextVar('tool_call_round', default=None)


def _renders_app_html(capabilities: ClientCapabilities) -> bool:
    settings = (capabilities.extensions or {}).get(EXTENSION_ID)
    mime_types = settings.get('mimeTypes') if isinstance(settings, dict) else None
    return isinstance(mime_types, list) and APP_MIME_TYPE in mime_types


def client_surfaces(capabilities: ClientCapabilities | None) -> ClientSurfaces:
    if capabilities is None:
        return ClientSurfaces(url_elicitation='unknown', apps='unknown')
    elicitation = capabilities.elicitation
    return ClientSurfaces(
        url_elicitation='declared'
        if elicitation is not None and elicitation.url is not None
        else 'absent',
        apps='declared' if _renders_app_html(capabilities) else 'absent',
    )


def current_round() -> ToolCallRound | None:
    """The tools/call in flight; None outside one."""
    return _round.get()


def apps_declaration() -> Declaration:
    """What the tools/call in flight declared about MCP Apps; unknown outside one."""
    round_ = current_round()
    return round_.surfaces.apps if round_ is not None else 'unknown'


def _round_of(ctx: ServerRequestContext[object, object]) -> ToolCallRound:
    surfaces = client_surfaces(ctx.session.client_capabilities)
    params = ctx.params or {}
    echoed = {k: params[k] for k in ('requestState', 'inputResponses') if k in params}
    try:
        parsed = InputResponseRequestParams.model_validate(echoed)
    except ValidationError:
        logger.info('Ignoring a malformed tools/call retry: %s', sorted(echoed))
        return ToolCallRound(ctx.protocol_version, surfaces)
    return ToolCallRound(
        ctx.protocol_version,
        surfaces,
        parsed.request_state,
        parsed.input_responses or {},
    )


async def bind_tool_call_round(
    ctx: ServerRequestContext[object, object], call_next: CallNext
) -> HandlerResult:
    """Bind each tools/call's round, so the tool can read what the client echoed."""
    if ctx.method != 'tools/call':
        return await call_next(ctx)
    round_ = _round_of(ctx)
    logger.info(
        'tools/call protocol_version=%s elicitation.url=%s apps=%s',
        round_.protocol_version,
        round_.surfaces.url_elicitation,
        round_.surfaces.apps,
    )
    token = _round.set(round_)
    try:
        return await call_next(ctx)
    finally:
        _round.reset(token)
