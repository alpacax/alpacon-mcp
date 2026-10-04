"""A workspace URL slug may be renamed while its schema_name stays fixed.

In JWT mode the `workspace` argument is matched against the token claim's
`schema_name`. These tests pin that a renamed slug is resolved through the
account service lookup first, and that every failure keeps the rejection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from utils.decorators import with_token_validation
from utils.workspace_resolver import clear_cache

CLAIMS = [
    {'schema_name': 'acme_internal', 'region': 'ap1'},
    {'schema_name': 'other_internal', 'region': 'us1'},
]


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _make_tool():
    async def _inner(workspace: str, region: str = '', **kwargs):
        return {'status': 'success', 'workspace': workspace, 'region': region}

    return with_token_validation(_inner)


def _lookup_client(status=200, body=None, error=None):
    """Patch target for httpx.AsyncClient used by the slug lookup."""
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body if body is not None else {}
    client = MagicMock()
    client.get = AsyncMock(side_effect=error, return_value=response)
    client_cls = MagicMock()
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return client_cls, client


def _jwt_mode():
    return (
        patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'}),
        patch('utils.decorators._get_jwt_token', return_value='jwt'),
        patch('utils.decorators.get_token_workspaces', return_value=CLAIMS),
        patch('utils.auth.get_token_workspaces', return_value=CLAIMS),
        patch('utils.decorators._check_mfa_requirement', new=AsyncMock()),
    )


async def _call(workspace, client_cls):
    patches = _jwt_mode()
    for p in patches:
        p.start()
    try:
        with patch('httpx.AsyncClient', client_cls):
            return await _make_tool()(workspace=workspace, region='')
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_renamed_slug_is_accepted_and_mapped():
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})

    result = await _call('acme-renamed', client_cls)

    assert result['status'] == 'success'
    assert result['workspace'] == 'acme_internal'
    assert result['region'] == 'ap1'
    client.get.assert_awaited_once()
    assert client.get.await_args.kwargs['params'] == {'slug': 'acme-renamed'}


@pytest.mark.asyncio
async def test_exact_schema_name_makes_no_network_call():
    client_cls, client = _lookup_client(body={'organization': 'other_internal'})

    result = await _call('acme_internal', client_cls)

    assert result['status'] == 'success'
    assert result['workspace'] == 'acme_internal'
    client_cls.assert_not_called()
    client.get.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'kwargs',
    [
        {'status': 404, 'body': {}},
        {'status': 429, 'body': {}},
        {'error': httpx.ConnectError('down')},
        {'error': httpx.ReadTimeout('slow')},
    ],
    ids=['not-found', 'rate-limited', 'network-error', 'timeout'],
)
async def test_lookup_failure_keeps_rejection(kwargs):
    client_cls, _ = _lookup_client(**kwargs)

    result = await _call('failing-slug', client_cls)

    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_resolved_name_not_in_claims_is_rejected():
    client_cls, _ = _lookup_client(body={'organization': 'unrelated_internal'})

    result = await _call('foreign-slug', client_cls)

    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_successful_resolution_is_cached():
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})

    await _call('acme-renamed', client_cls)
    result = await _call('acme-renamed', client_cls)

    assert result['workspace'] == 'acme_internal'
    client.get.assert_awaited_once()
