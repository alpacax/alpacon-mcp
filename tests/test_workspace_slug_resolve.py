"""A workspace URL slug may be renamed while its schema_name stays fixed.

In JWT mode the `workspace` argument is matched against the token claim's
`schema_name`. These tests pin that a renamed slug is resolved through the
account service lookup first, and that every failure keeps the rejection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from utils import workspace_resolver
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


def _jwt_mode(claims=None, mfa=None, decode=None):
    claims = CLAIMS if claims is None else claims
    return (
        patch.dict(
            'os.environ',
            {
                'ALPACON_MCP_AUTH_ENABLED': 'true',
                'ALPACON_ACCOUNT_URL': 'https://acct.test',
            },
        ),
        patch('utils.decorators._get_jwt_token', return_value='jwt'),
        patch(
            'utils.decorators.get_token_workspaces',
            new=decode or MagicMock(return_value=claims),
        ),
        patch('utils.decorators._check_mfa_requirement', new=mfa or AsyncMock()),
    )


async def _call(workspace, client_cls, claims=None, region='', mfa=None, decode=None):
    patches = _jwt_mode(claims, mfa, decode)
    for p in patches:
        p.start()
    try:
        with patch('httpx.AsyncClient', client_cls):
            return await _make_tool()(workspace=workspace, region=region)
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_renamed_slug_is_accepted_and_mapped():
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})
    decode = MagicMock(return_value=CLAIMS)

    result = await _call('acme-renamed', client_cls, decode=decode)

    assert result['status'] == 'success'
    assert result['workspace'] == 'acme_internal'
    assert result['region'] == 'ap1'
    client.get.assert_awaited_once()
    assert client.get.await_args.kwargs['params'] == {'slug': 'acme-renamed'}
    # Mapping the slug reads the claims the handler already decoded.
    decode.assert_called_once_with('jwt')


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


OTHER_CLAIMS = [{'schema_name': 'other_internal', 'region': 'us1'}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'name',
    ['Acme', 'acme_x', '-acme', 'acme-', 'a' * 64, 'acme\n'],
    ids=['upper', 'underscore', 'lead-dash', 'trail-dash', 'too-long', 'newline'],
)
async def test_argument_that_cannot_be_a_slug_makes_no_lookup(name):
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})

    result = await _call(name, client_cls)

    assert result['status'] == 'error'
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_empty_claims_make_no_lookup():
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})

    result = await _call('acme-renamed', client_cls, claims=[])

    assert result['status'] == 'error'
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_not_found_is_cached():
    client_cls, client = _lookup_client(status=404)

    await _call('typo-name', client_cls)
    await _call('typo-name', client_cls)

    client.get.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'kwargs',
    [
        {'status': 429},
        {'error': httpx.ConnectError('x')},
        {'error': httpx.ReadTimeout('x')},
    ],
    ids=['rate-limited', 'network-error', 'timeout'],
)
async def test_transient_failures_are_not_cached(kwargs):
    bad_cls, _ = _lookup_client(**kwargs)
    await _call('acme-renamed', bad_cls)

    good_cls, good = _lookup_client(body={'organization': 'acme_internal'})
    result = await _call('acme-renamed', good_cls)

    assert result['status'] == 'success'
    good.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_unset_account_url_makes_no_lookup(monkeypatch):
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})
    monkeypatch.delenv('ALPACON_ACCOUNT_URL', raising=False)

    with patch('httpx.AsyncClient', client_cls):
        assert await workspace_resolver.lookup_schema_name('acme-renamed') is None
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_stdio_mode_makes_no_lookup():
    client_cls, _ = _lookup_client(body={'organization': 'acme_internal'})
    with (
        patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'false'}),
        patch('utils.decorators.validate_token', return_value=None),
        patch('httpx.AsyncClient', client_cls),
    ):
        result = await _make_tool()(workspace='acme-renamed', region='ap1')

    assert result['status'] == 'error'
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_mfa_check_receives_schema_name():
    client_cls, _ = _lookup_client(body={'organization': 'acme_internal'})
    mfa = AsyncMock()

    await _call('acme-renamed', client_cls, mfa=mfa)

    assert mfa.await_args.args[2] == 'acme_internal'


@pytest.mark.asyncio
async def test_cached_mapping_does_not_authorize_another_caller():
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})
    assert (await _call('acme-renamed', client_cls))['status'] == 'success'

    result = await _call('acme-renamed', client_cls, claims=OTHER_CLAIMS, region='us1')

    assert result['status'] == 'error'
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_wrong_region_is_rejected_by_the_jwt_gate():
    client_cls, _ = _lookup_client(body={'organization': 'acme_internal'})

    result = await _call('acme-renamed', client_cls, region='us1')

    assert result['status'] == 'error'
    assert 'not authorized by JWT' in result['message']


@pytest.mark.asyncio
async def test_timeout_and_override_url_are_wired(monkeypatch):
    client_cls, client = _lookup_client(body={'organization': 'acme_internal'})
    monkeypatch.setenv('ALPACON_ACCOUNT_URL', 'https://acct.test/')

    with patch('httpx.AsyncClient', client_cls):
        await workspace_resolver.lookup_schema_name('a-b')

    assert client_cls.call_args.kwargs['timeout'] == 3.0
    assert (
        client.get.await_args.args[0]
        == 'https://acct.test/api/workspaces/organization/'
    )
