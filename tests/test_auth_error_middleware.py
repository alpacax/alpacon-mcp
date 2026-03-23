"""Tests for UpstreamAuthErrorMiddleware."""

import json

import pytest

from utils.auth_error_middleware import UpstreamAuthErrorMiddleware
from utils.error_handler import make_auth_error_key, signal_upstream_auth_error

# Default body that mimics http_client's 401 error response dict.
_DEFAULT_401_BODY = {
    'error': 'HTTP Error',
    'status_code': 401,
    'message': 'Unauthorized',
    'mfa_required': False,
}


class _MockApp:
    """Minimal ASGI app that returns a 200 JSON response.

    Optionally signals an upstream auth error via the module-level dict,
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
            token_key = make_auth_error_key(self._token)
            signal_upstream_auth_error(token_key, self._signal_error)

        await send(
            {
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'application/json')],
            }
        )
        await send(
            {
                'type': 'http.response.body',
                'body': self._body,
            }
        )


def _http_scope(auth_header: str = 'Bearer test-jwt') -> dict:
    return {
        'type': 'http',
        'method': 'POST',
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
    assert status == 200
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

    assert status == 401
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

    assert status == 401
    assert 'offline_access mfa' in headers['www-authenticate']
    assert 'MFA' in json.loads(body)['error_description']


@pytest.mark.asyncio
async def test_non_mfa_flag_excludes_mfa_scope():
    """Non-MFA flag does NOT add 'mfa' to scope."""
    mw = _make(error_value={'mfa_required': False, 'source': ''})
    sent = await _run(mw)
    status, headers, _ = await _collect_response(sent)

    assert status == 401
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
    assert (await _collect_response(sent1))[0] == 401

    # Second (same client, within cooldown): pass through as tool error
    sent2 = await _run(mw, scope=scope)
    status2, _, body2 = await _collect_response(sent2)
    assert status2 == 200
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
    assert (await _collect_response(sent_a))[0] == 401

    # Client B (different token): swap app and test
    mw.app = app_b
    sent_b = await _run(mw, scope=_http_scope(f'Bearer {token_b}'))
    assert (await _collect_response(sent_b))[0] == 401


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
async def test_stale_signal_triggers_401_on_next_request():
    """A stale signal from a previous request triggers 401 on the next request.

    This is correct behavior: if the upstream returned 401 for this token,
    all requests with that token need re-auth regardless of body content.
    The signal is per-client (token hash), not per-request.
    """
    token = 'shared-token'
    token_key = make_auth_error_key(token)

    # Simulate a stale signal left by a previous/concurrent request
    signal_upstream_auth_error(token_key, {'mfa_required': False, 'source': ''})

    # This app succeeds (no signal, body has no 401)
    app = _MockApp(body={'ok': True})
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw, scope=_http_scope(f'Bearer {token}'))
    status, headers, _ = await _collect_response(sent)

    # Signal is consumed → 401 returned to trigger re-auth
    assert status == 401
    assert 'www-authenticate' in headers


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

    assert status == 401
    assert 'www-authenticate' in headers


@pytest.mark.asyncio
async def test_no_signal_passes_through_regardless_of_body():
    """Without a signal, response passes through even if body contains 401-like content."""
    token = 'no-signal-jwt'

    # Body looks like a 401 error but no signal was set
    app = _MockApp(
        body={'error': 'HTTP Error', 'status_code': 401, 'message': 'Unauthorized'}
    )
    mw = UpstreamAuthErrorMiddleware(app)

    sent = await _run(mw, scope=_http_scope(f'Bearer {token}'))
    status, _, body = await _collect_response(sent)

    # No signal → passes through as 200
    assert status == 200
    assert '401' in body
