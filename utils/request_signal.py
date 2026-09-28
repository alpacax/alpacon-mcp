"""Per-request carrying of the upstream authentication signal.

The tool handler runs in a task the transport spawns, so rebinding a ContextVar
there never reaches the ASGI middleware. Mutating the dict the middleware put in
the ContextVar does, and it keeps one request's signal out of another's response.
"""

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
    """Clear the signal. Symmetric counterpart to begin_request()."""
    _signal.set(None)


def current_signal() -> AuthSignal | None:
    return _signal.get()


def signal_upstream_auth_error(error_info: AuthSignal) -> None:
    """Record an upstream 401 for the request in flight.

    Does nothing outside a request: stdio and SSE never install a signal.
    """
    holder = _signal.get()
    if holder is None:
        return

    mfa_required = holder.get('mfa_required') or error_info.get('mfa_required')
    holder.update(error_info)
    if mfa_required:
        holder['mfa_required'] = True
