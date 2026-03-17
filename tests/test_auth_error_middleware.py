"""Tests for UpstreamAuthErrorMiddleware."""

import json

import pytest

from utils.auth_error_middleware import UpstreamAuthErrorMiddleware
from utils.error_handler import upstream_auth_error_flag


@pytest.fixture(autouse=True)
def _reset_auth_error_flag():
    """Reset the upstream auth error flag before and after each test."""
    upstream_auth_error_flag.set(None)
    yield
    upstream_auth_error_flag.set(None)


class _FakeFlag:
    """Deterministic flag replacement that always returns a predetermined value.

    Avoids all contextvars/async isolation issues by making get() return the
    value set at construction time, ignoring set() calls from the middleware.
    """

    def __init__(self, return_value=None):
        self._return_value = return_value

    def get(self, *args):
        return self._return_value

    def set(self, value):
        pass  # No-op: value is controlled at construction time


class _MockApp:
    """Minimal ASGI app that returns a 200 JSON response."""

    def __init__(self, body: dict | None = None):
        self._body = json.dumps(body or {'ok': True}).encode()

    async def __call__(self, scope, receive, send):
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


def _make(flag_value=None, body=None, resource_metadata_url='', cooldown_seconds=60):
    """Create middleware with injected FakeFlag (no contextvars, no patching).

    The FakeFlag always returns flag_value from get(), making tests
    deterministic regardless of async context isolation behavior.
    """
    fake = _FakeFlag(return_value=flag_value)
    app = _MockApp(body=body)
    mw = UpstreamAuthErrorMiddleware(
        app,
        resource_metadata_url=resource_metadata_url,
        cooldown_seconds=cooldown_seconds,
        flag_provider=fake,
    )
    return mw


@pytest.mark.asyncio
async def test_no_flag_passes_through():
    """When no flag is set, response passes through as-is."""
    mw = _make()
    sent = await _run(mw)
    status, _, body = await _collect_response(sent)
    assert status == 200


@pytest.mark.asyncio
async def test_flag_triggers_401():
    """When flag is set, middleware returns HTTP 401."""
    mw = _make(
        flag_value={'mfa_required': False, 'source': ''},
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
    mw = _make(flag_value={'mfa_required': True, 'source': 'websh'})
    sent = await _run(mw)
    status, headers, body = await _collect_response(sent)

    assert status == 401
    assert 'offline_access mfa' in headers['www-authenticate']
    assert 'MFA' in json.loads(body)['error_description']


@pytest.mark.asyncio
async def test_non_mfa_flag_excludes_mfa_scope():
    """Non-MFA flag does NOT add 'mfa' to scope."""
    mw = _make(flag_value={'mfa_required': False, 'source': ''})
    sent = await _run(mw)
    status, headers, _ = await _collect_response(sent)

    assert status == 401
    assert 'mfa' not in headers['www-authenticate']


@pytest.mark.asyncio
async def test_cooldown_passes_through_on_second_401():
    """Second 401 within cooldown passes through as normal response."""
    mw = _make(
        flag_value={'mfa_required': False, 'source': ''},
        body={'tool_error': 'auth failed'},
        cooldown_seconds=60,
    )

    # First: 401
    sent1 = await _run(mw)
    assert (await _collect_response(sent1))[0] == 401

    # Second (same client, within cooldown): pass through
    sent2 = await _run(mw)
    status2, _, body2 = await _collect_response(sent2)
    assert status2 == 200
    assert 'tool_error' in body2


@pytest.mark.asyncio
async def test_per_client_cooldown_isolation():
    """Different clients have independent cooldowns."""
    mw = _make(
        flag_value={'mfa_required': False, 'source': ''},
        cooldown_seconds=60,
    )

    # Client A: 401
    sent_a = await _run(mw, scope=_http_scope('Bearer token-A'))
    assert (await _collect_response(sent_a))[0] == 401

    # Client B (different token): also 401 (not affected by A's cooldown)
    sent_b = await _run(mw, scope=_http_scope('Bearer token-B'))
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
