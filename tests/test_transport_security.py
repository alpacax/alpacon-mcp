import pytest

from server import resolve_transport_security
from tests.conftest import streamable_http_client
from utils.common import MCP_VERSION

INITIALIZE_REQUEST = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'initialize',
    'params': {
        'protocolVersion': '2025-06-18',
        'capabilities': {},
        'clientInfo': {'name': 'test', 'version': '0'},
    },
}


@pytest.fixture(autouse=True)
def clear_transport_security_environment(monkeypatch):
    monkeypatch.delenv('ALPACON_MCP_ALLOWED_HOSTS', raising=False)
    monkeypatch.delenv('ALPACON_MCP_ALLOWED_ORIGINS', raising=False)


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('allowed_hosts', 'allowed_origins', 'host', 'origin'),
    [
        (None, None, 'mcp.dev.alpacon.io', None),
        ('mcp.dev.alpacon.io', None, 'mcp.dev.alpacon.io', None),
        (
            'mcp.dev.alpacon.io',
            'https://inspector.example',
            'mcp.dev.alpacon.io',
            'https://inspector.example',
        ),
        ('mcp.dev.alpacon.io:*', None, 'mcp.dev.alpacon.io:8237', None),
    ],
)
async def test_initialize_accepts_hosts_and_origins_allowed_by_configuration(
    monkeypatch, allowed_hosts, allowed_origins, host, origin
):
    if allowed_hosts is not None:
        monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', allowed_hosts)
    if allowed_origins is not None:
        monkeypatch.setenv('ALPACON_MCP_ALLOWED_ORIGINS', allowed_origins)
    headers = {'Host': host, 'Accept': 'application/json, text/event-stream'}
    if origin is not None:
        headers['Origin'] = origin

    async with streamable_http_client(host='0.0.0.0') as client:  # noqa: S104
        response = await client.post('/mcp', headers=headers, json=INITIALIZE_REQUEST)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['jsonrpc'] == '2.0'
    assert body['id'] == 1
    assert body['result']['protocolVersion'] == '2025-06-18'
    assert body['result']['serverInfo'] == {'name': 'alpacon', 'version': MCP_VERSION}


@pytest.mark.usefixtures('authenticated_mcp')
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('allowed_hosts', 'bind_host', 'host', 'origin', 'status', 'body'),
    [
        (
            'mcp.dev.alpacon.io',
            '0.0.0.0',  # noqa: S104
            'attacker.example',
            None,
            421,
            'Invalid Host header',
        ),
        (
            'mcp.dev.alpacon.io',
            '0.0.0.0',  # noqa: S104
            'mcp.dev.alpacon.io',
            'https://inspector.example',
            403,
            'Invalid Origin header',
        ),
        (
            '127.0.0.1:*',
            '127.0.0.1',
            'localhost:8237',
            None,
            421,
            'Invalid Host header',
        ),
    ],
)
async def test_initialize_rejects_unlisted_hosts_and_origins(
    monkeypatch, allowed_hosts, bind_host, host, origin, status, body
):
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', allowed_hosts)
    headers = {'Host': host, 'Accept': 'application/json, text/event-stream'}
    if origin is not None:
        headers['Origin'] = origin

    async with streamable_http_client(host=bind_host) as client:
        response = await client.post('/mcp', headers=headers, json=INITIALIZE_REQUEST)

    assert response.status_code == status, response.text
    assert response.text == body


@pytest.mark.parametrize('hosts', [None, '', ' ,  , '])
def test_empty_hosts_preserve_sdk_defaults_and_ignore_origins(monkeypatch, hosts):
    if hosts is not None:
        monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', hosts)
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_ORIGINS', 'invalid-origin')

    settings = resolve_transport_security()

    assert settings is None


def test_transport_security_strips_entries_and_drops_blanks(monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', ' a.example , ,b.example ')
    monkeypatch.setenv(
        'ALPACON_MCP_ALLOWED_ORIGINS', ' https://a.example , , http://b.example:* '
    )

    settings = resolve_transport_security()

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ['a.example', 'b.example']
    assert settings.allowed_origins == ['https://a.example', 'http://b.example:*']


def test_unset_origins_allow_no_origin_values(monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', 'a.example')

    settings = resolve_transport_security()

    assert settings is not None
    assert settings.allowed_origins == []


@pytest.mark.parametrize(
    'entry',
    [
        'https://mcp.alpacon.io',
        'https:mcp.alpacon.io',
        'mcp.alpacon.io/',
        'mcp.alpacon.io:',
        'mcp.alpacon.io:99999',
        'mcp.alpacon.io:８４４３',
        'mcp.alpacon.io:٨٤٤٣',
        'mcp.alpacon.io:8443:*',
        'user@mcp.alpacon.io',
        '[::1',
        '*.alpacon.io',
        'éxample.com',
    ],
)
def test_invalid_hosts_raise_an_error_naming_the_variable_and_entry(monkeypatch, entry):
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', entry)

    with pytest.raises(ValueError, match='ALPACON_MCP_ALLOWED_HOSTS') as error:
        resolve_transport_security()

    assert entry in str(error.value)


@pytest.mark.parametrize(
    'entry',
    [
        'mcp.alpacon.io',
        'https://x.example/path',
        'https://x.example/',
        'https://x.example?query',
        'https://x.example#fragment',
        'https://',
        'https://[invalid',
        'https://x.example:443',
        'http://x.example:80',
        'https://user@x.example',
        'https://x.example:99999',
        'https://X.example',
        'https://x.example:',
        'https://x.example:08443',
        'https://x.example:8443:*',
        'https://*.example',
        'https://éxample.com',
        'http://[0:0:0:0:0:0:0:1]:6274',
        'http://127.1:6274',
        'http://0x7f000001:6274',
        'http://2130706433:6274',
        'http://a.0x7f:6274',
        'http://[::ffff:127.0.0.1]:6274',
        'https://xn--.example',
        'https://xn--abc-.example',
        'https://xn--99999999999.example',
        'https://xn--a.example',
        'https://xn--e-xbb.example',
        'https://xn--bc-jga.example',
        'https://xn--ab-l13a.example',
        'https://xn--1ug.example',
        'https://xn--a-ecp.example',
    ],
)
def test_invalid_origins_raise_an_error_naming_the_variable_and_entry(
    monkeypatch, entry
):
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', 'a.example')
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_ORIGINS', entry)

    with pytest.raises(ValueError, match='ALPACON_MCP_ALLOWED_ORIGINS') as error:
        resolve_transport_security()

    assert entry in str(error.value)


def test_well_formed_host_and_origin_entries_are_accepted(monkeypatch):
    hosts = [
        'mcp.alpacon.io',
        'mcp.alpacon.io:8443',
        '127.0.0.1:*',
        '[::1]:8237',
        'mcp_service:8237',
        'MCP.example',
    ]
    origins = [
        'https://a.example',
        'http://localhost:6274',
        'http://[::1]:*',
        'http://127.0.0.1:6274',
        'http://[::ffff:7f00:1]:6274',
        'https://xn--bcher-kva.example',
        'https://xn--ls8h.example',
        'https://xn--11b6iy14e.example',
    ]
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_HOSTS', ','.join(hosts))
    monkeypatch.setenv('ALPACON_MCP_ALLOWED_ORIGINS', ','.join(origins))

    settings = resolve_transport_security()

    assert settings is not None
    assert settings.allowed_hosts == hosts
    assert settings.allowed_origins == origins
