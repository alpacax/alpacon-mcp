"""Startup contract for the three transports: server imports in both modes, and the
streamable-http app keeps host, json_response and stateless_http (SDK 2.x moved them).
"""

import os
import subprocess
import sys

import httpx
import pytest

from server import MAX_REQUEST_BODY_SIZE, create_streamable_http_app, mcp
from tests.conftest import streamable_http_client
from utils.common import MCP_VERSION

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_import(entry: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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
    async with streamable_http_client() as client:
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

    assert response.status_code == 200, response.text
    assert response.headers['content-type'].startswith('application/json')


@pytest.mark.asyncio
async def test_initialize_reports_package_version():
    """Given the server, When a client initializes, Then serverInfo carries the
    package version rather than an empty string."""
    async with streamable_http_client() as client:
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


@pytest.mark.asyncio
async def test_streamable_http_app_mints_no_session():
    """Given the app this deployment serves, When a client initializes, Then no
    mcp-session-id comes back, which the same app built stateful does return."""
    stateless = create_streamable_http_app(host='0.0.0.0')  # noqa: S104
    stateful = mcp.streamable_http_app(
        host='0.0.0.0',  # noqa: S104
        json_response=True,
        stateless_http=False,
    )

    sessions = {}
    for name, app in (('stateless', stateless), ('stateful', stateful)):
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
        assert response.status_code == 200, response.text
        sessions[name] = response.headers.get('mcp-session-id')

    assert sessions['stateful'] is not None
    assert sessions['stateless'] is None


@pytest.mark.asyncio
async def test_streamable_http_app_raises_body_limit_above_sdk_default():
    """A body over the SDK's 4 MiB default is accepted, not rejected as too large:
    MAX_REQUEST_BODY_SIZE (5 MiB) lets uploads reach the tool's error, not a 413 (#144).
    """
    oversized_body = b'{"pad": "' + b'x' * (4 * 1024 * 1024) + b'"}'

    async with streamable_http_client() as client:
        response = await client.post(
            '/mcp',
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream',
            },
            content=oversized_body,
        )

    assert response.status_code != 413, response.text


@pytest.mark.asyncio
async def test_streamable_http_app_rejects_body_over_configured_limit():
    """A body over MAX_REQUEST_BODY_SIZE gets a 413 at the ASGI layer,
    proving the limit is enforced and not raised without bound.
    """
    oversized_body = b'{"pad": "' + b'x' * (MAX_REQUEST_BODY_SIZE + 1) + b'"}'

    async with streamable_http_client() as client:
        response = await client.post(
            '/mcp',
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream',
            },
            content=oversized_body,
        )

    assert response.status_code == 413, response.text
