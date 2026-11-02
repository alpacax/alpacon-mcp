"""Which MCP surfaces the connected client declared, and a log line of it on every tools/call.
ClientSurfaces is kept for Steps 2 and 4 of #427; apps means the extension key is declared."""

import logging
from dataclasses import dataclass
from typing import Literal

from mcp.server.apps import EXTENSION_ID
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import ClientCapabilities

from utils.logger import get_logger

logger = get_logger('client_surfaces')

# unknown: no capabilities at tool time (a pre-2026-07-28 stateless request).
type Declaration = Literal['declared', 'absent', 'unknown']


@dataclass(frozen=True)
class ClientSurfaces:
    url_elicitation: Declaration
    apps: Declaration


def client_surfaces(capabilities: ClientCapabilities | None) -> ClientSurfaces:
    if capabilities is None:
        return ClientSurfaces(url_elicitation='unknown', apps='unknown')
    elicitation = capabilities.elicitation
    return ClientSurfaces(
        url_elicitation='declared'
        if elicitation is not None and elicitation.url is not None
        else 'absent',
        apps='declared'
        if EXTENSION_ID in (capabilities.extensions or {})
        else 'absent',
    )


async def log_client_surfaces(
    ctx: ServerRequestContext[object, object], call_next: CallNext
) -> HandlerResult:
    if ctx.method == 'tools/call' and logger.isEnabledFor(logging.INFO):
        surfaces = client_surfaces(ctx.session.client_capabilities)
        logger.info(
            'tools/call protocol_version=%s elicitation.url=%s apps=%s',
            ctx.protocol_version,
            surfaces.url_elicitation,
            surfaces.apps,
        )
    return await call_next(ctx)
