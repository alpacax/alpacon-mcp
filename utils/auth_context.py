"""ContextVar-backed store for the per-request Alpacon API token.

Set by with_token_validation; read by tool bodies (and, from PR 2 on, the
typed API client). Every new entry point that is not an MCP tool call—websocket,
scheduled task—must call set_token itself.
"""

from contextvars import ContextVar

_token_var: ContextVar[str | None] = ContextVar('alpacon_token', default=None)


def set_token(token: str) -> None:
    _token_var.set(token)


def current_token() -> str | None:
    return _token_var.get()
