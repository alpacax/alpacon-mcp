"""Startup contract for the three transports.

SDK 2.x moved host, port, json_response and stateless_http off the MCPServer
constructor. These tests pin that each entry point still starts and that
streamable-http keeps its json_response and stateless_http contract.
"""

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_import(entry: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    full_env = {**os.environ, 'PYTHONPATH': REPO_ROOT, **env}
    return subprocess.run(  # noqa: S603
        [sys.executable, '-c', f'import {entry}'],
        cwd=REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_server_module_imports_without_transport_kwargs():
    # Given a repo on SDK 2.x, When server is imported, Then no TypeError.
    result = _run_import('server', {})
    assert result.returncode == 0, result.stderr


def test_server_module_imports_in_auth_mode():
    # Given remote mode env, When server is imported, Then no TypeError.
    result = _run_import(
        'server',
        {
            'ALPACON_MCP_AUTH_ENABLED': 'true',
            'AUTH0_DOMAIN': 'example.us.auth0.com',
            'ALPACON_MCP_RESOURCE_URL': 'https://mcp.example.com',
        },
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_streamable_http_app_accepts_external_host():
    """Given an app built for 0.0.0.0, When a request arrives with the public
    Host header, Then it is served rather than rejected as a rebinding attempt."""
    import httpx

    from server import create_streamable_http_app

    app = create_streamable_http_app(host='0.0.0.0')  # noqa: S104

    # The session manager's task group is initialized by the app's own ASGI
    # lifespan, so drive it directly instead of routing through httpx.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            response = await client.post(
                '/mcp',
                headers={
                    'Host': 'mcp.dev.alpacon.io',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json, text/event-stream',
                },
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'initialize',
                    'params': {
                        'protocolVersion': '2025-06-18',
                        'capabilities': {},
                        'clientInfo': {'name': 'test', 'version': '0'},
                    },
                },
            )

    assert response.status_code != 421, response.text
    assert response.headers['content-type'].startswith('application/json')


@pytest.mark.asyncio
async def test_initialize_reports_package_version():
    """Given the server, When a client initializes, Then serverInfo carries the
    package version rather than an empty string."""
    import httpx

    from server import create_streamable_http_app
    from utils.common import MCP_VERSION

    app = create_streamable_http_app(host='0.0.0.0')  # noqa: S104

    # The session manager's task group is initialized by the app's own ASGI
    # lifespan, so drive it directly instead of routing through httpx.
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
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'initialize',
                    'params': {
                        'protocolVersion': '2025-06-18',
                        'capabilities': {},
                        'clientInfo': {'name': 'test', 'version': '0'},
                    },
                },
            )

    server_info = response.json()['result']['serverInfo']
    assert server_info['name'] == 'alpacon'
    assert server_info['version'] == MCP_VERSION
    assert server_info['version'] != ''
