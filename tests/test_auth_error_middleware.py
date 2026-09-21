"""Tests for UpstreamAuthErrorMiddleware."""

import asyncio
import json
import logging
from http import HTTPStatus

import pytest

from utils import request_signal
from utils.auth_error_middleware import UpstreamAuthErrorMiddleware
from utils.error_handler import UpstreamAuthError

# Default body that mimics http_client's 401 error response dict.
_DEFAULT_401_BODY = {
    'error': 'HTTP Error',
    'status_code': HTTPStatus.UNAUTHORIZED,
    'message': 'Unauthorized',
    'mfa_required': False,
}


class _MockApp:
    """Minimal ASGI app that returns a 200 JSON response.

    Optionally signals an upstream auth error via the request signal,
    simulating what http_client does when it receives a 401.
    """

    def __init__(
        self,
        body: dict | None = None,
        signal_error: dict | None = None,
        auth_value: str = 'test-jwt',  # noqa: S107
    ):
        if body is not None:
            self._body = json.dumps(body).encode()
        elif signal_error is not None:
            self._body = json.dumps(_DEFAULT_401_BODY).encode()
        else:
            self._body = json.dumps({'ok': True}).encode()
        self._signal_error = signal_error
        self._token = auth_value

    async def __call__(self, scope, receive, send):
        # Simulate http_client signaling upstream 401
        if self._signal_error is not None:
            request_signal.signal_upstream_auth_error(self._signal_error)

        await send(
            {
                'type': 'http.response.start',
                'status': HTTPStatus.OK,
                'headers': [(b'content-type', b'application/json')],
            }
        )
        await send(
            {
                'type': 'http.response.body',
                'body': self._body,
            }
        )


class _DispatchingApp:
    """ASGI app whose behavior depends on request path, not on which instance
    called it — so one middleware instance can serve two concurrent requests
    that behave differently, with its cooldown dict shared between them."""

    def __init__(self, fail_path: str, signal_error: dict):
        self._fail_path = fail_path
        self._signal_error = signal_error

    async def __call__(self, scope, receive, send):
        if scope.get('path') == self._fail_path:
            request_signal.signal_upstream_auth_error(self._signal_error)

        await send(
            {
                'type': 'http.response.start',
                'status': HTTPStatus.OK,
                'headers': [(b'content-type', b'application/json')],
            }
        )
        await send(
            {
                'type': 'http.response.body',
                'body': json.dumps({'ok': True}).encode(),
            }
        )


def _http_scope(auth_header: str = 'Bearer test-jwt', path: str = '/') -> dict:
    return {
        'type': 'http',
        'method': 'POST',
        'path': path,
        'headers': [(b'authorization', auth_header.encode())],
    }


async def _collect_response(messages: list[dict]) -> tuple[int, dict, str]:
    status = 0
    headers = {}
    body = b''
    for msg in messages:
        if msg['type'] == 'http.response.start':
            status = msg['status']
            for k, v in msg.get('headers', []):
                headers[k.decode()] = v.decode()
        elif msg['type'] == 'http.response.body':
            body += msg.get('body', b'')
    return status, headers, body.decode()


async def _run(middleware, scope=None):
    if scope is None:
        scope = _http_scope()
    sent: list[dict] = []

    async def mock_send(msg):
        sent.append(msg)

    async def mock_receive():
        return {'type': 'http.request', 'body': b''}

    await middleware(scope, mock_receive, mock_send)
    return sent


def _make(
    error_value=None,
    body=None,
    resource_metadata_url='',
    cooldown_seconds=60,
    auth_value='test-jwt',
):
    """Create middleware with mock app that optionally signals upstream error."""
    app = _MockApp(body=body, signal_error=error_value, auth_value=auth_value)
    mw = UpstreamAuthErrorMiddleware(
        app,
        resource_metadata_url=resource_metadata_url,
        cooldown_seconds=cooldown_seconds,
    )
    return mw


@pytest.mark.asyncio
async def test_no_flag_passes_through():
    """When no error is signaled, response passes through as-is."""
    mw = _make()
    sent = await _run(mw)
    status, _, body = await _collect_response(sent)
    assert status == HTTPStatus.OK
    assert 'ok' in body


@pytest.mark.asyncio
async def test_flag_triggers_401():
    """When error is signaled, middleware returns HTTP 401."""
    mw = _make(
        error_value={'mfa_required': False, 'source': ''},
        resource_metadata_url='https://example.com/.well-known/oauth-protected-resource',
    )
    sent = await _run(mw)
    status, headers, body = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'www-authenticate' in headers
    assert 'invalid_token' in headers['www-authenticate']
    assert (
        'resource_metadata="https://example.com/.well-known/oauth-protected-resource"'
        in headers['www-authenticate']
    )
    assert json.loads(body)['error'] == 'invalid_token'


@pytest.mark.asyncio
async def test_mfa_flag_includes_mfa_scope():
    """MFA flag adds 'mfa' to WWW-Authenticate scope."""
    mw = _make(error_value={'mfa_required': True, 'source': 'websh'})
    sent = await _run(mw)
    status, headers, body = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'offline_access mfa' in headers['www-authenticate']
    assert 'MFA' in json.loads(body)['error_description']


@pytest.mark.asyncio
async def test_non_mfa_flag_excludes_mfa_scope():
    """Non-MFA flag does NOT add 'mfa' to scope."""
    mw = _make(error_value={'mfa_required': False, 'source': ''})
    sent = await _run(mw)
    status, headers, _ = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'mfa' not in headers['www-authenticate']


@pytest.mark.asyncio
async def test_cooldown_passes_through_on_second_401():
    """Second 401 within cooldown passes through as normal response."""
    # Use a shared token for both requests
    token = 'cooldown-test-token'

    # Create middleware with mock app that signals error.
    app = _MockApp(
        signal_error={'mfa_required': False, 'source': ''},
        auth_value=token,
    )
    mw = UpstreamAuthErrorMiddleware(app, cooldown_seconds=60)

    scope = _http_scope(f'Bearer {token}')

    # First: 401
    sent1 = await _run(mw, scope=scope)
    assert (await _collect_response(sent1))[0] == HTTPStatus.UNAUTHORIZED

    # Second (same client, within cooldown): pass through as tool error
    sent2 = await _run(mw, scope=scope)
    status2, _, body2 = await _collect_response(sent2)
    assert status2 == HTTPStatus.OK
    assert 'status_code' in body2


@pytest.mark.asyncio
async def test_per_client_cooldown_isolation():
    """Different clients have independent cooldowns."""
    token_a = 'token-A'
    token_b = 'token-B'

    # Client A's app signals error with token A
    app_a = _MockApp(
        signal_error={'mfa_required': False, 'source': ''}, auth_value=token_a
    )
    # Client B's app signals error with token B
    app_b = _MockApp(
        signal_error={'mfa_required': False, 'source': ''}, auth_value=token_b
    )

    # Use same middleware instance but swap inner app for each client
    mw = UpstreamAuthErrorMiddleware(app_a, cooldown_seconds=60)

    # Client A: 401
    sent_a = await _run(mw, scope=_http_scope(f'Bearer {token_a}'))
    assert (await _collect_response(sent_a))[0] == HTTPStatus.UNAUTHORIZED

    # Client B (different token): swap app and test
    mw.app = app_b
    sent_b = await _run(mw, scope=_http_scope(f'Bearer {token_b}'))
    assert (await _collect_response(sent_b))[0] == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_non_http_scope_passes_through():
    """Non-HTTP scopes are passed through without buffering."""
    call_count = 0

    async def mock_app(scope, receive, send):
        nonlocal call_count
        call_count += 1

    mw = UpstreamAuthErrorMiddleware(mock_app)
    await mw({'type': 'websocket'}, lambda: {}, lambda msg: None)
    assert call_count == 1


@pytest.mark.asyncio
async def test_a_signal_left_before_the_request_does_not_leak_in():
    """Given a signal written before the middleware begins a request, When that
    request runs with a clean app, Then it is not treated as this request's signal.

    A per-request ContextVar object replaces the old module-level dict, so a
    signal recorded outside begin_request() cannot bleed into the next call.
    """
    token = 'shared-token'

    # Simulate a signal recorded outside any request (no begin_request() yet).
    request_signal.signal_upstream_auth_error({'mfa_required': False, 'source': ''})

    # This app succeeds (no signal, body has no 401)
    app = _MockApp(body={'ok': True})
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw, scope=_http_scope(f'Bearer {token}'))
    status, _, body = await _collect_response(sent)

    assert status == HTTPStatus.OK
    assert 'ok' in body


@pytest.mark.asyncio
async def test_flag_triggers_401_with_any_body():
    """Middleware triggers 401 based on signal, regardless of body content.

    The middleware no longer inspects response body. The signal from
    http_client is the sole source of truth for upstream 401 detection.
    """
    token = 'any-body-test-jwt'
    mw = _make(
        error_value={'mfa_required': False, 'source': ''},
        body={'status': 'success', 'data': {'ok': True}},
        auth_value=token,
    )

    sent = await _run(mw, scope=_http_scope(f'Bearer {token}'))
    status, headers, _ = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'www-authenticate' in headers


@pytest.mark.asyncio
async def test_no_signal_passes_through_regardless_of_body():
    """Without a signal, response passes through even if body contains 401-like content."""
    token = 'no-signal-jwt'

    # Body looks like a 401 error but no signal was set
    app = _MockApp(
        body={
            'error': 'HTTP Error',
            'status_code': HTTPStatus.UNAUTHORIZED,
            'message': 'Unauthorized',
        }
    )
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw, scope=_http_scope(f'Bearer {token}'))
    status, _, body = await _collect_response(sent)

    # No signal → passes through as 200
    assert status == HTTPStatus.OK
    assert '401' in body


# --- Exception-based path tests ---


class _RaisingApp:
    """Mock ASGI app that raises UpstreamAuthError, simulating the new exception path."""

    def __init__(
        self,
        mfa_required: bool = True,
        source: str = 'websh',
        auth_value: str = 'test-jwt',
    ):  # noqa: S107
        self.mfa_required = mfa_required
        self.source = source
        self._token = auth_value

    async def __call__(self, scope, receive, send):
        # Also record the request signal (like real http_client does before raising)
        request_signal.signal_upstream_auth_error(
            {'mfa_required': self.mfa_required, 'source': self.source},
        )
        raise UpstreamAuthError(mfa_required=self.mfa_required, source=self.source)


@pytest.mark.asyncio
async def test_exception_triggers_401():
    """UpstreamAuthError exception should trigger HTTP 401."""
    app = _RaisingApp(mfa_required=True, source='websh')
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw)
    status, headers, _ = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'www-authenticate' in headers
    assert 'mfa' in headers['www-authenticate']


@pytest.mark.asyncio
async def test_exception_non_mfa_triggers_401_without_mfa_scope():
    """Non-MFA UpstreamAuthError should trigger 401 without mfa scope."""
    app = _RaisingApp(mfa_required=False, source='')
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw)
    status, headers, _ = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'www-authenticate' in headers
    assert 'mfa' not in headers['www-authenticate']


@pytest.mark.asyncio
async def test_exception_path_signal_does_not_leak_into_the_next_request():
    """Given a request whose app raises UpstreamAuthError, When a later request with
    the same token runs against a clean app, Then it sees no leftover signal.

    cooldown_seconds=0 so a cooldown, not signal leakage, cannot be the reason
    the second request comes back 200.
    """
    token = 'test-jwt'
    raising_app = _RaisingApp(auth_value=token)
    mw = UpstreamAuthErrorMiddleware(raising_app, cooldown_seconds=0)
    scope = _http_scope(f'Bearer {token}')

    await _run(mw, scope=scope)

    mw.app = _MockApp(body={'ok': True})
    sent = await _run(mw, scope=scope)
    status, _, body = await _collect_response(sent)

    assert status == HTTPStatus.OK
    assert 'ok' in body


@pytest.mark.asyncio
async def test_normal_return_signal_does_not_leak_into_the_next_request():
    """Given a request whose app signals a 401 and returns normally, When a later
    request with the same token runs against a clean app, Then it sees no
    leftover signal.

    cooldown_seconds=0 so a cooldown cannot be mistaken for signal isolation.
    """
    token = 'test-jwt'
    signaling_app = _MockApp(
        signal_error={'mfa_required': True, 'source': 'exec'}, auth_value=token
    )
    mw = UpstreamAuthErrorMiddleware(signaling_app, cooldown_seconds=0)
    scope = _http_scope(f'Bearer {token}')

    sent1 = await _run(mw, scope=scope)
    assert (await _collect_response(sent1))[0] == HTTPStatus.UNAUTHORIZED

    mw.app = _MockApp(body={'ok': True})
    sent2 = await _run(mw, scope=scope)
    status2, _, body2 = await _collect_response(sent2)

    assert status2 == HTTPStatus.OK
    assert 'ok' in body2


@pytest.mark.asyncio
async def test_exception_respects_cooldown():
    """Exception path should respect cooldown like signal path."""
    app = _RaisingApp(mfa_required=True)
    mw = UpstreamAuthErrorMiddleware(app, cooldown_seconds=60)

    # First call: should get 401
    sent1 = await _run(mw)
    status1, _, _ = await _collect_response(sent1)
    assert status1 == HTTPStatus.UNAUTHORIZED

    # Second call within cooldown: should get 500 fallback (no buffered response
    # because _RaisingApp raises before writing any response)
    sent2 = await _run(mw)
    status2, _, _ = await _collect_response(sent2)
    assert status2 == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_same_token_concurrent_requests_do_not_steal_each_others_signal():
    """Given two requests with the same token on one middleware instance, one
    failing and one fine, When they run together, Then only the failing one
    is answered with 401.

    Both requests go through the same UpstreamAuthErrorMiddleware instance
    (shared _client_cooldowns), so cooldown_seconds=0 keeps the first 401
    from suppressing the second request's check.
    """
    app = _DispatchingApp(
        fail_path='/fail', signal_error={'mfa_required': True, 'source': 'exec'}
    )
    mw = UpstreamAuthErrorMiddleware(app, cooldown_seconds=0)

    failing_scope = _http_scope(path='/fail')
    passing_scope = _http_scope(path='/ok')

    results = await asyncio.gather(
        _run(mw, scope=failing_scope), _run(mw, scope=passing_scope)
    )
    failing_status, _, _ = await _collect_response(results[0])
    passing_status, _, _ = await _collect_response(results[1])

    assert failing_status == HTTPStatus.UNAUTHORIZED
    assert passing_status == HTTPStatus.OK


@pytest.mark.asyncio
async def test_debug_instrumentation_logs_at_debug_level(caplog):
    """[DEBUG-MW] records are leftover instrumentation, so ALPACON_MCP_LOG_LEVEL must silence them."""
    mw = _make()

    with caplog.at_level(logging.DEBUG, logger='alpacon_mcp.auth_error_middleware'):
        await _run(mw)

    records = [r for r in caplog.records if '[DEBUG-MW]' in r.getMessage()]
    assert records
    assert all(r.levelno == logging.DEBUG for r in records)
