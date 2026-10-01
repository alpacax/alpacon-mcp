"""Carry the agent's self-reported clientInfo to alpacon-server.

The agent names itself in MCP ``clientInfo`` (``name`` and ``version``), either
once in the ``initialize`` handshake or, from protocol 2026-07-28, in every
request's ``_meta``. The SDK exposes both the same way, on
``session.client_params``. A server middleware binds it here for the request in
flight, and the HTTP client forwards it in two headers.

The value is self-reported and nobody checks it. alpacon-server records it as
``declared_agent``, beside the channel it derived from the credential, and no
gate reads it. Composition into ``name/version`` and sanitization happen on the
server, so this module passes the values through, with three exceptions that
keep a header sendable. Boundary whitespace is trimmed, since h11 refuses a
value that starts or ends with it. Each value is cut to the server's own limit
(64 for the name, 32 for the version), since an oversized header is refused
before the server can truncate it. A value that still cannot travel as a header
is left out: httpx refuses a non-ASCII value and h11 a newline, and either
would fail the tool call.

A stateless streamable-http server builds a fresh connection for each request,
so a pre-2026 client's handshake does not reach the tool call there, and
nothing is sent. Once that client speaks 2026-07-28, the value arrives on every
request.
"""

from contextvars import ContextVar
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

DECLARED_AGENT_NAME_HEADER = 'X-Alpacon-Declared-Agent-Name'
DECLARED_AGENT_VERSION_HEADER = 'X-Alpacon-Declared-Agent-Version'

# alpacon-server's limits (``auth0/declared_agent.py``); anything longer is
# dropped there anyway.
DECLARED_AGENT_NAME_MAX_LENGTH = 64
DECLARED_AGENT_VERSION_MAX_LENGTH = 32

_declared_agent: ContextVar[tuple[str, str] | None] = ContextVar(
    'declared_agent', default=None
)


async def capture_declared_agent(
    ctx: ServerRequestContext[Any, Any], call_next: CallNext
) -> HandlerResult:
    """Bind the client's ``clientInfo`` for the rest of this request."""
    params = ctx.session.client_params
    info = params.client_info if params is not None else None
    token = _declared_agent.set((info.name, info.version) if info else None)
    try:
        return await call_next(ctx)
    finally:
        _declared_agent.reset(token)


def _header_safe(value: str) -> bool:
    return value.isascii() and value.isprintable()


def _bounded(value: str, max_length: int) -> str:
    """Trim and cut the way the server does, so a sendable value stores as sent."""
    return value.strip()[:max_length].rstrip()


def declared_agent_headers() -> dict[str, str]:
    """The headers to send for the request in flight; empty outside one."""
    declared = _declared_agent.get()
    if declared is None:
        return {}
    name = _bounded(declared[0], DECLARED_AGENT_NAME_MAX_LENGTH)
    version = _bounded(declared[1], DECLARED_AGENT_VERSION_MAX_LENGTH)
    headers = {}
    if name and _header_safe(name):
        headers[DECLARED_AGENT_NAME_HEADER] = name
    if version and _header_safe(version):
        headers[DECLARED_AGENT_VERSION_HEADER] = version
    return headers
