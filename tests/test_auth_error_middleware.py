"""Tests for UpstreamAuthErrorMiddleware."""

import json
from unittest.mock import patch

import pytest

from utils.auth_error_middleware import UpstreamAuthErrorMiddleware
from utils.error_handler import upstream_auth_error_flag


@pytest.fixture(autouse=True)
def _reset_auth_error_flag():
    """Reset the upstream auth error flag before and after each test."""
    upstream_auth_error_flag.set(None)
    yield
    upstream_auth_error_flag.set(None)


class _FakeContextVar:
    """A simple replacement for contextvars.ContextVar used in tests.

    Unlike real ContextVar, this is NOT affected by asyncio.create_task()
    context copying, making tests reliable across all async runtimes.
    """

    def __init__(self, value=None):
        self._value = value

    def get(self, *args):
        return self._value

    def set(self, value):
        self._value = value


class _MockApp:
    """Minimal ASGI app that returns HTTP 200 with a JSON body.

    If auth_error_flag is provided, sets it on the fake_flag during execution
    (simulating a tool that detects upstream 401).
    """

    def __init__(
        self,
        body: dict | None = None,
        auth_error_flag: dict | None = None,
        fake_flag: _FakeContextVar | None = None,
    ):
        self._body = json.dumps(body or {'ok': True}).encode()
        self._auth_error_flag = auth_error_flag
        self._fake_flag = fake_flag

    async def __call__(self, scope, receive, send):
        if self._auth_error_flag is not None and self._fake_flag is not None:
            self._fake_flag.set(self._auth_error_flag)

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


def _http_scope(auth_header: str = 'Bearer test-token') -> dict:
    """Create a minimal HTTP ASGI scope."""
    return {
        'type': 'http',
        'method': 'POST',
        'headers': [(b'authorization', auth_header.encode())],
    }


async def _collect_response(messages: list[dict]) -> tuple[int, dict, str]:
    """Parse buffered ASGI messages into (status, headers_dict, body)."""
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


async def _run_middleware(middleware, scope=None):
    """Helper to run middleware and collect sent messages."""
    if scope is None:
        scope = _http_scope()
    sent: list[dict] = []

    async def mock_send(msg):
        sent.append(msg)

    async def mock_receive():
        return {'type': 'http.request', 'body': b''}

    await middleware(scope, mock_receive, mock_send)
    return sent


def _create_middleware_with_flag(
    flag_value: dict | None = None,
    body: dict | None = None,
    resource_metadata_url: str = '',
    cooldown_seconds: float = 60,
):
    """Create middleware + mock app with a shared FakeContextVar.

    Returns (middleware, fake_flag) so the flag can be inspected.
    """
    fake_flag = _FakeContextVar()
    app = _MockApp(
        body=body,
        auth_error_flag=flag_value,
        fake_flag=fake_flag,
    )
    middleware = UpstreamAuthErrorMiddleware(
        app,
        resource_metadata_url=resource_metadata_url,
        cooldown_seconds=cooldown_seconds,
    )
    return middleware, fake_flag


@pytest.mark.asyncio
async def test_no_flag_passes_through():
    """When no upstream auth error flag is set, response passes through."""
    app = _MockApp({'result': 'ok'})
    middleware = UpstreamAuthErrorMiddleware(app)

    sent = await _run_middleware(middleware)
    status, _, body = await _collect_response(sent)
    assert status == 200
    assert 'ok' in body


@pytest.mark.asyncio
async def test_flag_triggers_401():
    """When upstream auth error flag is set, middleware returns HTTP 401."""
    flag = {'mfa_required': False, 'source': ''}
    middleware, fake_flag = _create_middleware_with_flag(
        flag_value=flag,
        resource_metadata_url='https://example.com/.well-known/oauth-protected-resource',
    )

    with patch('utils.auth_error_middleware.upstream_auth_error_flag', fake_flag):
        sent = await _run_middleware(middleware)

    status, headers, body = await _collect_response(sent)

    assert status == 401
    assert 'www-authenticate' in headers
    assert 'invalid_token' in headers['www-authenticate']
    assert (
        'resource_metadata="https://example.com/.well-known/oauth-protected-resource"'
        in headers['www-authenticate']
    )

    body_data = json.loads(body)
    assert body_data['error'] == 'invalid_token'


@pytest.mark.asyncio
async def test_mfa_flag_includes_mfa_scope():
    """When mfa_required is True, WWW-Authenticate scope includes 'mfa'."""
    flag = {'mfa_required': True, 'source': 'websh'}
    middleware, fake_flag = _create_middleware_with_flag(flag_value=flag)

    with patch('utils.auth_error_middleware.upstream_auth_error_flag', fake_flag):
        sent = await _run_middleware(middleware)

    status, headers, body = await _collect_response(sent)

    assert status == 401
    assert 'mfa' in headers['www-authenticate']
    assert 'offline_access mfa' in headers['www-authenticate']

    body_data = json.loads(body)
    assert 'MFA' in body_data['error_description']


@pytest.mark.asyncio
async def test_non_mfa_flag_excludes_mfa_scope():
    """When mfa_required is False, WWW-Authenticate scope does not include 'mfa'."""
    flag = {'mfa_required': False, 'source': ''}
    middleware, fake_flag = _create_middleware_with_flag(flag_value=flag)

    with patch('utils.auth_error_middleware.upstream_auth_error_flag', fake_flag):
        sent = await _run_middleware(middleware)

    status, headers, _ = await _collect_response(sent)

    assert status == 401
    assert 'mfa' not in headers['www-authenticate']


@pytest.mark.asyncio
async def test_cooldown_passes_through_on_second_401():
    """After a 401, subsequent flags within cooldown pass through normally."""
    flag = {'mfa_required': False, 'source': ''}
    middleware, fake_flag = _create_middleware_with_flag(
        flag_value=flag,
        body={'tool_error': 'auth failed'},
        cooldown_seconds=60,
    )

    with patch('utils.auth_error_middleware.upstream_auth_error_flag', fake_flag):
        # First request: should return 401
        sent1 = await _run_middleware(middleware)
        status1, _, _ = await _collect_response(sent1)
        assert status1 == 401

        # Second request (same client, within cooldown): should pass through
        sent2 = await _run_middleware(middleware)
        status2, _, body2 = await _collect_response(sent2)
        assert status2 == 200
        assert 'tool_error' in body2


@pytest.mark.asyncio
async def test_per_client_cooldown_isolation():
    """Cooldown is per-client: different Authorization headers have separate cooldowns."""
    flag = {'mfa_required': False, 'source': ''}
    middleware, fake_flag = _create_middleware_with_flag(
        flag_value=flag,
        cooldown_seconds=60,
    )

    with patch('utils.auth_error_middleware.upstream_auth_error_flag', fake_flag):
        # Client A triggers 401
        sent_a = await _run_middleware(middleware, scope=_http_scope('Bearer token-A'))
        status_a, _, _ = await _collect_response(sent_a)
        assert status_a == 401

        # Client B (different token) should ALSO get 401 (not affected by A's cooldown)
        sent_b = await _run_middleware(middleware, scope=_http_scope('Bearer token-B'))
        status_b, _, _ = await _collect_response(sent_b)
        assert status_b == 401


@pytest.mark.asyncio
async def test_non_http_scope_passes_through():
    """Non-HTTP scopes (e.g., websocket) are passed through without buffering."""
    call_count = 0

    async def mock_app(scope, receive, send):
        nonlocal call_count
        call_count += 1

    middleware = UpstreamAuthErrorMiddleware(mock_app)

    async def mock_receive():
        return {}

    async def mock_send(msg):
        pass

    await middleware({'type': 'websocket'}, mock_receive, mock_send)
    assert call_count == 1
