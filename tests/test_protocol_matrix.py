"""What each protocol revision negotiates, and how many times lifespan runs.

2026-07-28 is not reachable through initialize: the SDK answers that handshake
with the newest handshake revision instead. It is reached through server/discover
carrying a per-request _meta envelope.
"""

import contextlib

import httpx
import pytest

from server import create_streamable_http_app
from utils.common import MCP_VERSION


def _initialize(protocol_version: str) -> dict:
    return {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'initialize',
        'params': {
            'protocolVersion': protocol_version,
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '0'},
        },
    }


def _discover() -> dict:
    return {
        'jsonrpc': '2.0',
        'id': 2,
        'method': 'server/discover',
        'params': {
            '_meta': {
                'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                'io.modelcontextprotocol/clientCapabilities': {},
                'io.modelcontextprotocol/clientInfo': {'name': 'test', 'version': '0'},
            }
        },
    }


@pytest.fixture
def app():
    return create_streamable_http_app(host='0.0.0.0')  # noqa: S104


@pytest.mark.asyncio
@pytest.mark.parametrize('revision', ['2025-03-26', '2025-06-18'])
async def test_2025_revisions_are_echoed_back(app, revision):
    # Given a 2025-era client, When it initializes, Then its revision is accepted.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            response = await client.post(
                '/mcp',
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream',
                },
                json=_initialize(revision),
            )

    assert response.json()['result']['protocolVersion'] == revision


@pytest.mark.asyncio
async def test_initialize_does_not_negotiate_the_2026_revision(app):
    """Given a client asking for 2026-07-28 over initialize, When it handshakes,
    Then the server answers with a handshake revision instead of failing."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            response = await client.post(
                '/mcp',
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream',
                },
                json=_initialize('2026-07-28'),
            )

    negotiated = response.json()['result']['protocolVersion']
    assert negotiated != '2026-07-28'
    assert negotiated.startswith('2025-')


@pytest.mark.asyncio
async def test_discover_reports_the_2026_revision_and_the_package_version(app):
    """Given a modern client, When it discovers the server, Then it learns the
    supported revision, the server name and a real package version."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            response = await client.post(
                '/mcp',
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream',
                    'MCP-Protocol-Version': '2026-07-28',
                    'Mcp-Method': 'server/discover',
                },
                json=_discover(),
            )

    result = response.json()['result']
    server_info = result['_meta']['io.modelcontextprotocol/serverInfo']

    assert '2026-07-28' in result['supportedVersions']
    assert server_info['name'] == 'alpacon'
    assert server_info['version'] == MCP_VERSION
    assert server_info['version'] != ''
    assert 'tools' in result['capabilities']


@pytest.mark.asyncio
async def test_lifespan_runs_once_across_several_stateless_requests(monkeypatch):
    """Given stateless HTTP, When several requests arrive, Then the lifespan that
    owns the shared HTTP client is entered once and left once."""
    entered = 0
    exited = 0

    import server as server_module

    original = server_module.mcp._lowlevel_server.lifespan

    @contextlib.asynccontextmanager
    async def counting_lifespan(app):
        nonlocal entered, exited
        entered += 1
        async with original(app) as value:
            yield value
        exited += 1

    monkeypatch.setattr(server_module.mcp._lowlevel_server, 'lifespan', counting_lifespan)
    app = create_streamable_http_app(host='0.0.0.0')  # noqa: S104

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            for _ in range(3):
                await client.post(
                    '/mcp',
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream',
                    },
                    json=_initialize('2025-06-18'),
                )

    assert entered == 1
    assert exited == 1
