"""Startup contract for stdio and streamable-http: server imports in both modes, and the
streamable-http app keeps host, json_response and stateless_http (SDK 2.x moved them).
"""

import os
import re
import subprocess
import sys

import httpx
import pytest
from mcp.server.transport_security import TransportSecuritySettings

import server as server_module
from server import MAX_REQUEST_BODY_SIZE, create_streamable_http_app
from tests.conftest import STREAMABLE_HTTP_TOKEN, streamable_http_client
from utils.common import MCP_VERSION
from utils.oauth import register_oauth_routes

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
            'AUTH0_ALPACON_DOMAIN': 'example.us.auth0.com',
            'ALPACON_MCP_RESOURCE_URL': 'https://mcp.example.com',
        },
    )
    assert result.returncode == 0, result.stderr


_INITIALIZE = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'initialize',
    'params': {
        'protocolVersion': '2025-06-18',
        'capabilities': {},
        'clientInfo': {'name': 'test', 'version': '0'},
    },
}


async def _initialize(
    *,
    host: str = '0.0.0.0',  # noqa: S104
    transport_security: TransportSecuritySettings | None = None,
    **headers: str,
) -> httpx.Response:
    async with streamable_http_client(
        host=host, transport_security=transport_security
    ) as client:
        return await client.post(
            '/mcp',
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream',
                **headers,
            },
            json=_INITIALIZE,
        )


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_wildcard_bind_without_allowlist_serves_any_host():
    response = await _initialize(Host='mcp.dev.alpacon.io')

    _assert_served(response)
    assert response.headers['content-type'].startswith('application/json')


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_initialize_reports_package_version():
    """Given the server, When a client initializes, Then serverInfo carries the
    package version rather than an empty string."""
    response = await _initialize()

    server_info = response.json()['result']['serverInfo']
    assert server_info['name'] == 'alpacon'
    assert server_info['version'] == MCP_VERSION
    assert server_info['version'] != ''


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_streamable_http_app_mints_no_session(authenticated_mcp):
    """Given the app this deployment serves, When a client initializes, Then no
    mcp-session-id comes back, which the same app built stateful does return."""
    stateless = create_streamable_http_app(host='0.0.0.0')  # noqa: S104
    stateful = authenticated_mcp.streamable_http_app(
        host='0.0.0.0',  # noqa: S104
        json_response=True,
        stateless_http=False,
    )

    sessions = {}
    for name, app in (('stateless', stateless), ('stateful', stateful)):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url='http://testserver',
                headers={'Authorization': f'Bearer {STREAMABLE_HTTP_TOKEN}'},
            ) as client:
                response = await client.post(
                    '/mcp',
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/event-stream',
                    },
                    json=_INITIALIZE,
                )
        assert response.status_code == 200, response.text
        sessions[name] = response.headers.get('mcp-session-id')

    assert sessions['stateful'] is not None
    assert sessions['stateless'] is None


@pytest.mark.usefixtures('authenticated_mcp')
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


@pytest.mark.usefixtures('authenticated_mcp')
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


@pytest.mark.parametrize('auth_enabled', ['false', 'true'])
def test_streamable_http_app_requires_auth_settings(monkeypatch, auth_enabled):
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'false')
    unauthenticated = server_module._create_mcp_server()
    monkeypatch.setattr(server_module, 'mcp', unauthenticated)
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', auth_enabled)

    with pytest.raises(RuntimeError, match='requires ALPACON_MCP_AUTH_ENABLED=true'):
        create_streamable_http_app(host='127.0.0.1')


def _settings(
    hosts: list[str], origins: list[str] | None = None
) -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins or [],
    )


def _assert_served(response: httpx.Response) -> None:
    assert response.status_code == 200, response.text
    assert response.json()['result']['serverInfo']['name'] == 'alpacon'


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('allowed', 'host'),
    [
        ('mcp.example.com', 'mcp.example.com'),
        ('mcp.example.com:*', 'mcp.example.com:8237'),
    ],
)
async def test_listed_host_is_served(allowed, host):
    response = await _initialize(transport_security=_settings([allowed]), Host=host)

    _assert_served(response)


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('allowed', 'host'),
    [
        ('mcp.example.com', 'evil.example.net'),
        ('mcp.example.com:*', 'mcp.example.com'),
        ('mcp.example.com', 'MCP.EXAMPLE.COM'),
    ],
)
async def test_unlisted_host_is_rejected_with_421(allowed, host):
    response = await _initialize(transport_security=_settings([allowed]), Host=host)

    assert response.status_code == 421
    assert response.text == 'Invalid Host header'


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_allowlist_replaces_the_loopback_default_on_a_loopback_bind():
    response = await _initialize(
        host='127.0.0.1',
        transport_security=_settings(['mcp.example.com']),
        Host='localhost:8237',
    )

    assert response.status_code == 421
    assert response.text == 'Invalid Host header'


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('allowed_origins', 'origin'),
    [
        ([], 'https://app.example.com'),
        (['https://app.example.com'], 'https://evil.example.net'),
    ],
)
async def test_unlisted_origin_is_rejected_with_403(allowed_origins, origin):
    response = await _initialize(
        transport_security=_settings(['mcp.example.com'], allowed_origins),
        Host='mcp.example.com',
        Origin=origin,
    )

    assert response.status_code == 403
    assert response.text == 'Invalid Origin header'


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_listed_origin_is_served():
    response = await _initialize(
        transport_security=_settings(['mcp.example.com'], ['https://app.example.com']),
        Host='mcp.example.com',
        Origin='https://app.example.com',
    )

    _assert_served(response)


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_health_ignores_host_allowlist():
    server_module._register_http_health_endpoint()

    async with streamable_http_client(
        transport_security=_settings(['mcp.example.com'])
    ) as client:
        response = await client.get('/health', headers={'Host': 'probe.internal'})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['status'] == 'ok'
    assert body['version'] == MCP_VERSION


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
async def test_protected_resource_metadata_ignores_host_allowlist():
    async with streamable_http_client(
        transport_security=_settings(['mcp.example.com'])
    ) as client:
        response = await client.get(
            '/.well-known/oauth-protected-resource',
            headers={'Host': 'probe.internal'},
        )

    assert response.status_code == 200, response.text
    assert response.json()['resource'] == 'https://mcp.example.com/'


@pytest.fixture
def no_transport_env(monkeypatch):
    monkeypatch.delenv('ALPACON_MCP_ALLOWED_HOSTS', raising=False)
    monkeypatch.delenv('ALPACON_MCP_ALLOWED_ORIGINS', raising=False)
    return monkeypatch


def test_resolve_transport_security_ignores_whitespace_and_trailing_commas(
    no_transport_env,
):
    no_transport_env.setenv(
        'ALPACON_MCP_ALLOWED_HOSTS', ' a.example.com , ,b.example.com:*,'
    )
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_ORIGINS', 'https://a.example.com, ')

    settings = server_module.resolve_transport_security()

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ['a.example.com', 'b.example.com:*']
    assert settings.allowed_origins == ['https://a.example.com']


@pytest.mark.parametrize('blank', ['', '   '])
def test_resolve_transport_security_treats_blank_as_unset(no_transport_env, blank):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_HOSTS', blank)
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_ORIGINS', blank)

    assert server_module.resolve_transport_security() is None


@pytest.mark.parametrize(
    'bad',
    [
        'https://mcp.example.com',
        'MCP.Example.com',
        'mcp.example.com/mcp',
        '*',
        'mcp.example.com:abc',
        'mcp.example.com:123456',
        '..',
        '-',
    ],
)
def test_resolve_transport_security_rejects_a_malformed_host(no_transport_env, bad):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_HOSTS', f'mcp.example.com,{bad}')

    with pytest.raises(
        RuntimeError, match=f'ALPACON_MCP_ALLOWED_HOSTS.*{re.escape(bad)}'
    ):
        server_module.resolve_transport_security()


@pytest.mark.parametrize(
    'bad',
    ['app.example.com', 'https://app.example.com/', 'https://App.example.com', 'null'],
)
def test_resolve_transport_security_rejects_a_malformed_origin(no_transport_env, bad):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_HOSTS', 'mcp.example.com')
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_ORIGINS', bad)

    with pytest.raises(
        RuntimeError, match=f'ALPACON_MCP_ALLOWED_ORIGINS.*{re.escape(bad)}'
    ):
        server_module.resolve_transport_security()


@pytest.mark.parametrize(
    'host',
    [
        'mcp.example.com',
        'mcp.example.com:8443',
        'mcp.example.com:*',
        '127.0.0.1:*',
        '[::1]:*',
        'alpacon_mcp:8237',
    ],
)
def test_resolve_transport_security_accepts_a_wellformed_host(no_transport_env, host):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_HOSTS', host)

    settings = server_module.resolve_transport_security()

    assert settings is not None
    assert settings.allowed_hosts == [host]


@pytest.mark.parametrize(
    'origin',
    ['https://app.example.com', 'http://localhost:*', 'vscode-webview://abc123'],
)
def test_resolve_transport_security_accepts_a_wellformed_origin(
    no_transport_env, origin
):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_HOSTS', 'mcp.example.com')
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_ORIGINS', origin)

    settings = server_module.resolve_transport_security()

    assert settings is not None
    assert settings.allowed_origins == [origin]


@pytest.mark.parametrize(
    'name', ['ALPACON_MCP_ALLOWED_HOSTS', 'ALPACON_MCP_ALLOWED_ORIGINS']
)
def test_resolve_transport_security_rejects_a_value_of_only_separators(
    no_transport_env, name
):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_HOSTS', 'mcp.example.com')
    no_transport_env.setenv(name, ' , ')

    with pytest.raises(RuntimeError, match=f'{name} holds no entries'):
        server_module.resolve_transport_security()


def test_resolve_transport_security_lists_every_malformed_entry(no_transport_env):
    no_transport_env.setenv(
        'ALPACON_MCP_ALLOWED_HOSTS', 'good.example.com,Bad.example.com,https://x.test'
    )

    with pytest.raises(RuntimeError) as excinfo:
        server_module.resolve_transport_security()

    message = str(excinfo.value)
    assert 'Bad.example.com' in message
    assert 'https://x.test' in message
    assert 'good.example.com' not in message


def test_resolve_transport_security_rejects_origins_without_hosts(no_transport_env):
    no_transport_env.setenv('ALPACON_MCP_ALLOWED_ORIGINS', 'https://app.example.com')

    with pytest.raises(
        RuntimeError, match='ALPACON_MCP_ALLOWED_ORIGINS.*ALPACON_MCP_ALLOWED_HOSTS'
    ):
        server_module.resolve_transport_security()


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('method', 'path'),
    [
        ('GET', '/oauth/authorize'),
        ('POST', '/oauth/token'),
        ('POST', '/oauth/register'),
        ('GET', '/authorize'),
        ('POST', '/token'),
        ('POST', '/register'),
    ],
)
async def test_oauth_routes_reach_their_handler_past_the_host_allowlist(
    monkeypatch, method, path
):
    monkeypatch.setenv('AUTH0_ALPACON_LOGIN_CLIENT_ID', 'test-client-id')
    monkeypatch.setenv('AUTH0_ALPACON_LOGIN_CLIENT_SECRET', 'test-client-secret')
    register_oauth_routes(server_module.mcp)

    async with streamable_http_client(
        transport_security=_settings(['mcp.example.com'])
    ) as client:
        response = await client.request(
            method, path, headers={'Host': 'probe.internal'}
        )

    assert response.status_code == 400, response.text
    assert response.json()['error'] == 'invalid_request'
