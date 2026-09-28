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
    called it—so one middleware instance can serve two concurrent requests
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
async def test_cooldown_passes_the_apps_own_response_through_on_a_second_401():
    """Given a client within cooldown, When a second signal fires, Then the app's
    own response reaches the client untouched, with no second challenge.

    Nothing has gone out yet when the check runs—the start message is still held
    and the first body chunk is in hand—so the original is still forwardable.
    """
    token = 'cooldown-test-token'
    original = {'jsonrpc': '2.0', 'result': {'isError': True, 'reason': 'upstream'}}

    app = _MockApp(
        body=original,
        signal_error={'mfa_required': False, 'source': ''},
        auth_value=token,
    )
    mw = UpstreamAuthErrorMiddleware(app, cooldown_seconds=60)

    scope = _http_scope(f'Bearer {token}')

    # First: 401
    sent1 = await _run(mw, scope=scope)
    assert (await _collect_response(sent1))[0] == HTTPStatus.UNAUTHORIZED

    # Second (same client, within cooldown): the app's own 200, byte for byte
    sent2 = await _run(mw, scope=scope)
    status2, headers2, body2 = await _collect_response(sent2)
    assert status2 == HTTPStatus.OK
    assert json.loads(body2) == original
    assert 'www-authenticate' not in headers2


@pytest.mark.asyncio
async def test_cooldown_pass_through_does_not_log_a_late_signal_warning(caplog):
    """Given a client within cooldown, When the app's own response is passed
    through, Then no 'cannot replace it' warning fires—the cooldown, not a
    late signal, is why nothing was replaced, and it already logs at INFO."""
    token = 'cooldown-warning-token'
    original = {'jsonrpc': '2.0', 'result': {'isError': True, 'reason': 'upstream'}}

    app = _MockApp(
        body=original,
        signal_error={'mfa_required': False, 'source': ''},
        auth_value=token,
    )
    mw = UpstreamAuthErrorMiddleware(app, cooldown_seconds=60)

    scope = _http_scope(f'Bearer {token}')

    await _run(mw, scope=scope)  # First: consumes the 401, starts the cooldown.

    with caplog.at_level(logging.WARNING, logger='alpacon_mcp.auth_error_middleware'):
        sent2 = await _run(mw, scope=scope)

    status2, _, body2 = await _collect_response(sent2)
    assert status2 == HTTPStatus.OK
    assert json.loads(body2) == original
    assert not any('cannot replace it' in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_an_expired_cooldown_lets_the_next_401_through_and_is_pruned():
    """Given a cooldown that has run out, When the same client signals again, Then
    it gets a fresh 401, and the stale entry is dropped on a later request."""
    token_a = 'expiring-token-a'
    token_b = 'other-token-b'
    scope_a = _http_scope(f'Bearer {token_a}')
    key_a = UpstreamAuthErrorMiddleware._extract_token_key(scope_a)

    app = _MockApp(signal_error={'mfa_required': False, 'source': ''})
    mw = UpstreamAuthErrorMiddleware(app, cooldown_seconds=0.01)

    sent1 = await _run(mw, scope=scope_a)
    assert (await _collect_response(sent1))[0] == HTTPStatus.UNAUTHORIZED
    assert key_a in mw._client_cooldowns

    await asyncio.sleep(0.05)

    sent2 = await _run(mw, scope=scope_a)
    assert (await _collect_response(sent2))[0] == HTTPStatus.UNAUTHORIZED

    await asyncio.sleep(0.05)

    await _run(mw, scope=_http_scope(f'Bearer {token_b}'))
    assert key_a not in mw._client_cooldowns


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
    request runs with a clean app, Then nothing was stored to leak into it.

    A per-request ContextVar object replaces the old module-level dict, so a
    signal recorded outside begin_request() is dropped rather than parked.
    """
    token = 'shared-token'

    # Simulate a signal recorded outside any request (no begin_request() yet).
    request_signal.signal_upstream_auth_error({'mfa_required': True, 'source': 'exec'})
    assert request_signal.current_signal() is None

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


class _HandshakeApp:
    """Sends one chunk, then waits for the receiver to acknowledge it.

    A middleware that buffers never lets that acknowledgement happen, so the wait
    times out. That is what makes this app able to tell the two apart.
    """

    def __init__(self, delivered: asyncio.Event):
        self.delivered = delivered
        self.finished = False

    async def __call__(self, scope, receive, send):
        await send(
            {
                'type': 'http.response.start',
                'status': HTTPStatus.OK,
                'headers': [(b'content-type', b'text/event-stream')],
            }
        )
        await send({'type': 'http.response.body', 'body': b'chunk0', 'more_body': True})

        await asyncio.wait_for(self.delivered.wait(), timeout=2)

        await send(
            {'type': 'http.response.body', 'body': b'chunk1', 'more_body': False}
        )
        self.finished = True


@pytest.mark.asyncio
async def test_a_chunk_reaches_the_client_while_the_app_is_still_running():
    """Given a long-lived response, When the app emits its first chunk, Then the
    client has it before the app produces the next one, and the wire sees exactly
    one `http.response.start`."""
    delivered = asyncio.Event()
    app = _HandshakeApp(delivered)
    mw = UpstreamAuthErrorMiddleware(app)

    sent: list[dict] = []

    async def recording_send(message):
        sent.append(message)
        if message['type'] == 'http.response.body' and message['body'] == b'chunk0':
            assert not app.finished, 'the app had already finished'
            delivered.set()

    async def mock_receive():
        return {'type': 'http.request', 'body': b''}

    await mw(_http_scope(), mock_receive, recording_send)

    types = [msg['type'] for msg in sent]
    assert types == [
        'http.response.start',
        'http.response.body',
        'http.response.body',
    ]
    bodies = [msg['body'] for msg in sent if msg['type'] == 'http.response.body']
    assert bodies == [b'chunk0', b'chunk1']


class _LateSignalApp:
    """Sends a start and one chunk, then signals an upstream 401 mid-stream, then
    sends a final chunk. Mirrors an SSE tool call whose upstream token expires
    after the response has already begun."""

    async def __call__(self, scope, receive, send):
        await send(
            {
                'type': 'http.response.start',
                'status': HTTPStatus.OK,
                'headers': [(b'content-type', b'text/event-stream')],
            }
        )
        await send({'type': 'http.response.body', 'body': b'chunk0', 'more_body': True})
        request_signal.signal_upstream_auth_error(
            {'mfa_required': True, 'source': 'exec'}
        )
        await send(
            {'type': 'http.response.body', 'body': b'chunk1', 'more_body': False}
        )


@pytest.mark.asyncio
async def test_a_late_signal_does_not_send_a_second_response_start(caplog):
    """Given a response that already started, When the signal fires mid-stream,
    Then the wire still sees exactly one `http.response.start` and the original
    chunks, not a 401—the client already got a 200 it cannot take back."""
    app = _LateSignalApp()
    mw = UpstreamAuthErrorMiddleware(app)

    with caplog.at_level(logging.WARNING, logger='alpacon_mcp.auth_error_middleware'):
        sent = await _run(mw)

    starts = [msg for msg in sent if msg['type'] == 'http.response.start']
    assert len(starts) == 1
    assert starts[0]['status'] == HTTPStatus.OK

    bodies = [msg['body'] for msg in sent if msg['type'] == 'http.response.body']
    assert bodies == [b'chunk0', b'chunk1']

    assert any('cannot replace it' in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_signalled_request_gets_the_full_401_not_the_original_body():
    """Given a signalled request, When the response is replaced, Then the client
    receives the OAuth error body and WWW-Authenticate, not the app's own body."""
    app = _MockApp(
        body={'jsonrpc': '2.0', 'result': {'isError': True}},
        signal_error={'mfa_required': True, 'source': 'exec'},
    )
    mw = UpstreamAuthErrorMiddleware(
        app,
        resource_metadata_url='https://example.com/.well-known/oauth-protected-resource',
    )

    sent = await _run(mw)
    status, headers, body = await _collect_response(sent)

    assert status == HTTPStatus.UNAUTHORIZED
    assert 'mfa' in headers['www-authenticate']
    assert 'resource_metadata=' in headers['www-authenticate']
    assert json.loads(body)['error'] == 'invalid_token'
    assert 'jsonrpc' not in body


@pytest.mark.asyncio
async def test_debug_instrumentation_logs_at_debug_level(caplog):
    """[DEBUG-MW] records are leftover instrumentation, so ALPACON_MCP_LOG_LEVEL must silence them."""
    mw = _make()

    with caplog.at_level(logging.DEBUG, logger='alpacon_mcp.auth_error_middleware'):
        await _run(mw)

    records = [r for r in caplog.records if '[DEBUG-MW]' in r.getMessage()]
    assert records
    assert all(r.levelno == logging.DEBUG for r in records)


class _StartOnlyApp:
    """Signals an upstream 401 and answers with a start message and no body,
    leaving the middleware's post-``self.app()`` check as the only one that runs."""

    def __init__(self, signal_error: dict):
        self._signal_error = signal_error

    async def __call__(self, scope, receive, send):
        request_signal.signal_upstream_auth_error(self._signal_error)
        await send(
            {
                'type': 'http.response.start',
                'status': HTTPStatus.OK,
                'headers': [(b'content-type', b'application/json')],
            }
        )


@pytest.mark.asyncio
async def test_a_bodyless_signalled_response_is_still_replaced_with_a_401():
    """Given an app that sends a start and no body, When it signalled an upstream
    401, Then the held start is dropped and the client gets the 401 instead."""
    app = _StartOnlyApp({'mfa_required': True, 'source': 'exec'})
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw)
    status, headers, body = await _collect_response(sent)

    starts = [msg for msg in sent if msg['type'] == 'http.response.start']
    assert len(starts) == 1
    assert status == HTTPStatus.UNAUTHORIZED
    assert 'mfa' in headers['www-authenticate']
    assert json.loads(body)['error'] == 'invalid_token'
