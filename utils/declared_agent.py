"""Carry the agent's self-reported clientInfo to alpacon-server in two headers.
Unverified; dropped if not header-safe, and stdio falls back to environment markers."""

import os
from contextvars import ContextVar

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

from utils.agent_environment import agent_from_environment

DECLARED_AGENT_NAME_HEADER = 'X-Alpacon-Declared-Agent-Name'
DECLARED_AGENT_VERSION_HEADER = 'X-Alpacon-Declared-Agent-Version'

# alpacon-server's limits (``auth0/declared_agent.py``); anything longer is
# dropped there anyway.
DECLARED_AGENT_NAME_MAX_LENGTH = 64
DECLARED_AGENT_VERSION_MAX_LENGTH = 32

_declared_agent: ContextVar[tuple[str, str] | None] = ContextVar(
    'declared_agent', default=None
)

# Set at startup from the transport; only stdio reads the environment.
_environment_fallback = False


def use_environment_fallback(enabled: bool) -> None:
    """Declare the agent from the environment when clientInfo names none."""
    global _environment_fallback
    _environment_fallback = enabled


async def capture_declared_agent(
    ctx: ServerRequestContext[object, object], call_next: CallNext
) -> HandlerResult:
    """Bind the client's ``clientInfo`` for the rest of this request."""
    params = ctx.session.client_params
    info = params.client_info if params is not None else None
    declared = (info.name, info.version) if info else None
    if _environment_fallback and (declared is None or not declared[0].strip()):
        declared = agent_from_environment(os.environ) or declared
    token = _declared_agent.set(declared)
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
