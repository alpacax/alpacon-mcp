"""The workspace the tool call in flight acts on, for the step-up link's redirect."""

from contextvars import ContextVar, Token

_workspace: ContextVar[str | None] = ContextVar('request_workspace', default=None)
_minted: ContextVar[set[tuple[str, str, str]] | None] = ContextVar(
    'request_minted_links', default=None
)


def bind_workspace(workspace: str | None) -> Token[str | None]:
    return _workspace.set(workspace)


def reset_workspace(token: Token[str | None]) -> None:
    _workspace.reset(token)


def current_workspace() -> str | None:
    return _workspace.get()


def bind_minted() -> Token[set[tuple[str, str, str]] | None]:
    """Start tracking the step-up links this tool call mints; tasks it spawns share it."""
    return _minted.set(set())


def reset_minted(token: Token[set[tuple[str, str, str]] | None]) -> None:
    _minted.reset(token)


def minted_in_call() -> set[tuple[str, str, str]] | None:
    return _minted.get()
