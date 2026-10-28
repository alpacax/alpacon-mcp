"""Carry the upstream authentication signal per request.
Handlers must mutate the middleware's dict; rebinding never reaches it."""

from contextvars import ContextVar

AuthSignal = dict[str, object]

_signal: ContextVar[AuthSignal | None] = ContextVar(
    'upstream_auth_signal', default=None
)


def begin_request() -> AuthSignal:
    """Install an empty signal for this request and return it."""
    holder: AuthSignal = {}
    _signal.set(holder)
    return holder


def end_request() -> None:
    _signal.set(None)


def current_signal() -> AuthSignal | None:
    return _signal.get()


def signal_upstream_auth_error(error_info: AuthSignal) -> None:
    """Record an upstream 401 for the request in flight; a no-op outside a request
    (stdio, SSE)."""
    holder = _signal.get()
    if holder is None:
        return

    mfa_required = holder.get('mfa_required') or error_info.get('mfa_required')
    holder.update(error_info)
    if mfa_required:
        holder['mfa_required'] = True
