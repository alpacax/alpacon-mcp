"""Subscription lifecycle over the composed, authenticated app.

Two things shape this harness. httpx's ASGITransport waits for the response to
finish, which never happens for a subscription, so these tests talk over TCP to
a real uvicorn. And the app under test is the one the deployment serves: OAuth
routes registered, wrapped in UpstreamAuthErrorMiddleware, requests carrying a
bearer token. Only the token verifier is mocked. `tests/subscription_harness.py`
builds it in a child process, because remote mode is decided when `server` is
imported.

At the 2026-07-28 revision the transport rejects a POST whose `Mcp-Method`
header is absent or disagrees with the body (-32020), so every request here
carries it.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator

import httpx
import pytest

JsonObject = dict[str, object]

_TOKEN = 'test-jwt'  # noqa: S105
_PROTOCOL_VERSION = '2026-07-28'
_LISTEN = {'notifications': {'toolsListChanged': True}}
_SIGNALLING_TOOL = 'raise_upstream_401'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HARNESS = os.path.join(REPO_ROOT, 'tests', 'subscription_harness.py')


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope='module')
def base_url():
    """Serve the composed app in a child process and hand back its base URL."""
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, _HARNESS, str(port)],
        cwd=REPO_ROOT,
        env={**os.environ, 'PYTHONPATH': REPO_ROOT},
    )
    url = f'http://127.0.0.1:{port}'
    deadline = time.monotonic() + 60
    try:
        while True:
            if process.poll() is not None:
                raise RuntimeError(f'harness exited with {process.returncode}')
            try:
                if httpx.get(f'{url}/health', timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('harness did not become ready')
            time.sleep(0.1)
        yield url
    finally:
        # SIGINT, not SIGTERM: server.py turns SIGTERM into KeyboardInterrupt
        # from inside the loop, which uvicorn logs as a crash.
        process.send_signal(signal.SIGINT)
        process.wait(timeout=30)


def _headers(
    method: str, token: str | None = _TOKEN, tool: str | None = None
) -> dict[str, str]:
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': _PROTOCOL_VERSION,
        'Mcp-Method': method,
    }
    if tool is not None:
        headers['Mcp-Name'] = tool
    if token is not None:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _envelope(method: str, params: JsonObject, request_id: int) -> JsonObject:
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'method': method,
        'params': {
            **params,
            '_meta': {
                'io.modelcontextprotocol/protocolVersion': _PROTOCOL_VERSION,
                'io.modelcontextprotocol/clientCapabilities': {},
                'io.modelcontextprotocol/clientInfo': {'name': 'test', 'version': '0'},
            },
        },
    }


async def _next_sse_payload(lines: AsyncIterator[str]) -> JsonObject:
    """Read the next `data:` frame off an open subscription stream.

    The caller keeps the iterator: dropping httpx's line iterator closes the
    response, which would end the very subscription these tests watch.
    """

    async def read() -> JsonObject:
        async for line in lines:
            if line.startswith('data: '):
                return json.loads(line[len('data: ') :])
        raise AssertionError('stream ended before a data frame arrived')

    return await asyncio.wait_for(read(), timeout=10)


async def _live_subscriptions(base_url: str) -> int:
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        response = await client.get('/_test/subscriptions')
        return response.json()['listeners']


async def _wait_for_subscriptions(base_url: str, expected: int) -> int:
    deadline = time.monotonic() + 10
    live = await _live_subscriptions(base_url)
    while live != expected and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        live = await _live_subscriptions(base_url)
    return live


@pytest.mark.asyncio
async def test_an_unauthenticated_request_is_rejected(base_url):
    """Given the composed app, When a request arrives with no token, Then it is
    refused—proving these tests run behind the real auth boundary."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        response = await client.post(
            '/mcp',
            headers=_headers('tools/list', token=None),
            json=_envelope('tools/list', {}, 1),
        )

    assert response.status_code == 401
    assert 'www-authenticate' in response.headers


@pytest.mark.asyncio
async def test_oauth_metadata_is_served_by_the_composed_app(base_url):
    """Given the composed app, When a client fetches protected-resource metadata,
    Then the OAuth routes registered by prepare() answer."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        response = await client.get('/.well-known/oauth-protected-resource')

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_an_authenticated_subscription_connects_stays_idle_and_cancels(base_url):
    """Given a bearer token, When a subscription is opened, left idle and then
    cancelled, Then it is acknowledged, survives the idle period and is released."""
    assert await _wait_for_subscriptions(base_url, 0) == 0

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        async with client.stream(
            'POST',
            '/mcp',
            headers=_headers('subscriptions/listen'),
            json=_envelope('subscriptions/listen', _LISTEN, 1),
        ) as response:
            assert response.status_code == 200
            assert response.headers['content-type'].startswith('text/event-stream')

            lines = response.aiter_lines()
            acknowledged = await _next_sse_payload(lines)
            assert acknowledged['method'] == 'notifications/subscriptions/acknowledged'
            assert acknowledged['params']['notifications'] == _LISTEN['notifications']

            await asyncio.sleep(2)  # idle

            assert await _live_subscriptions(base_url) == 1

            await response.aclose()  # cancel

    assert await _wait_for_subscriptions(base_url, 0) == 0


@pytest.mark.asyncio
async def test_an_unauthenticated_subscription_is_refused(base_url):
    """Given no token, When a subscription is attempted, Then the auth boundary
    refuses it rather than opening a stream."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        response = await client.post(
            '/mcp',
            headers=_headers('subscriptions/listen', token=None),
            json=_envelope('subscriptions/listen', _LISTEN, 1),
        )

    assert response.status_code == 401
    assert await _live_subscriptions(base_url) == 0


@pytest.mark.asyncio
async def test_ordinary_requests_work_while_a_subscription_is_open(base_url):
    """Given an open subscription, When a tools/list arrives on the same token,
    Then it is answered."""
    assert await _wait_for_subscriptions(base_url, 0) == 0

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        async with client.stream(
            'POST',
            '/mcp',
            headers=_headers('subscriptions/listen'),
            json=_envelope('subscriptions/listen', _LISTEN, 1),
        ) as response:
            assert response.status_code == 200
            lines = response.aiter_lines()
            await _next_sse_payload(lines)

            async with httpx.AsyncClient(base_url=base_url, timeout=30) as other:
                listed = await other.post(
                    '/mcp',
                    headers=_headers('tools/list'),
                    json=_envelope('tools/list', {}, 2),
                )

            assert listed.status_code == 200
            assert 'tools' in listed.json()['result']
            assert await _live_subscriptions(base_url) == 1


@pytest.mark.asyncio
async def test_disconnecting_a_subscription_releases_it(base_url):
    """Given a subscription that the client drops, When the server settles, Then
    the subscription it held is unregistered."""
    assert await _wait_for_subscriptions(base_url, 0) == 0

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        async with client.stream(
            'POST',
            '/mcp',
            headers=_headers('subscriptions/listen'),
            json=_envelope('subscriptions/listen', _LISTEN, 1),
        ) as response:
            assert response.status_code == 200
            lines = response.aiter_lines()
            await _next_sse_payload(lines)
            assert await _live_subscriptions(base_url) == 1

    assert await _wait_for_subscriptions(base_url, 0) == 0


@pytest.mark.asyncio
async def test_a_signalled_request_still_becomes_401_under_the_composed_app(base_url):
    """Given the composed app, When a tool records an upstream auth signal in its
    own task, Then the middleware answers 401 rather than the tool's own error."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        response = await client.post(
            '/mcp',
            headers=_headers('tools/call', tool=_SIGNALLING_TOOL),
            json=_envelope(
                'tools/call', {'name': _SIGNALLING_TOOL, 'arguments': {}}, 1
            ),
        )

    assert response.status_code == 401
    assert 'invalid_token' in response.headers['www-authenticate']
