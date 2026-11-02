"""Remote-mode command pre-approval ledger: the grant, the proxy, the verifier, the tools.

The ledger token of a remote caller lives only in that caller's own credential,
so these tests pin who can read it: the person who authorized it, through the
connection that authorized it, until it expires, on any replica.
"""

import json
import time
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from mcp.client.auth.utils import union_scopes
from mcp.server.auth.provider import AccessToken
from starlette.applications import Starlette
from starlette.testclient import TestClient

import server
from tests.conftest import http_client_fixture
from tests.test_ledger_tools import AI_ENV, LEDGER, UNAUTHORIZED_ENVELOPE
from tests.test_oauth import (
    OAUTH_ENV,
    PKCE_PARAMS,
    TEST_NONCE,
    MockMCPServer,
    _mock_auth0_response,
)
from tools import resources as res
from tools.ledger_tools import get_ledger_capability, list_ledger_entries
from utils import declared_agent, request_signal
from utils.auth import Auth0TokenVerifier
from utils.auth_error_middleware import UpstreamAuthErrorMiddleware
from utils.common import is_remote_ledger_enabled, serves_ledger_tools
from utils.error_handler import UpstreamAuthError
from utils.ledger_auth import AUTHORIZATION_REQUIRED
from utils.ledger_grant import (
    EXPIRY_SKEW_SECONDS,
    WRAPPED_ACCESS_PREFIX,
    LedgerGrant,
    decrypt,
    encrypt,
    grant_from_token_response,
    ledger_claims,
    ledger_grant_of,
    open_grant,
    open_stage,
    seal_grant,
    seal_stage,
    unwrap_access_token,
    wrap_access_token,
)
from utils.oauth import (
    _LEDGER_COOKIE_NAME,
    _NONCE_COOKIE_NAME,
    _build_state,
    _hash_nonce,
    _ledger_org,
    _open_seal,
    _seal_code,
    _seal_refresh_token,
    _verify_state,
    ledger_grant_key,
    register_oauth_routes,
)

KEY = b'k' * 32
OTHER_KEY = b'o' * 32
DEVICE_ID = 'a' * 32
ALICE = 'auth0|alice'
BOB = 'auth0|bob'
WORKSPACE = 'testworkspace'
REMOTE_ENV = {
    **OAUTH_ENV,
    'ALPACON_MCP_TRANSPORT': 'streamable-http',
    'ALPACON_MCP_REMOTE_LEDGER': 'true',
}


def _jwt(sub: str, exp: int | None = None, **extra: object) -> str:
    claims: dict[str, object] = {'sub': sub, **extra}
    if exp is not None:
        claims['exp'] = exp
    return jwt.encode(claims, 'unverified-test-key-of-32-bytes!!', algorithm='HS256')


def _grant(
    sub: str = ALICE, org: str = WORKSPACE, ttl: int = 3600, age: int = 3600
) -> LedgerGrant:
    """A grant issued `age` seconds ago; the default is past the retry window."""
    now = int(time.time())
    return LedgerGrant(
        token=_jwt(sub, now + ttl, aud='https://alpacon.ai/'),
        org=org,
        subject=sub,
        expires_at=now + ttl,
        issued_at=now - age,
    )


@pytest.fixture
def remote_env(monkeypatch):
    for name, value in REMOTE_ENV.items():
        monkeypatch.setenv(name, value)


class TestFlag:
    @pytest.mark.parametrize(
        ('auth', 'transport', 'flag', 'enabled'),
        [
            ('true', 'streamable-http', 'true', True),
            ('true', 'streamable-http', '', False),
            ('true', 'sse', 'true', False),
            ('', 'sse', 'true', False),
            ('', 'stdio', 'true', False),
        ],
    )
    def test_only_authenticated_streamable_http_with_the_flag(
        self, monkeypatch, auth, transport, flag, enabled
    ):
        monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', auth)
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', transport)
        monkeypatch.setenv('ALPACON_MCP_REMOTE_LEDGER', flag)
        assert is_remote_ledger_enabled() is enabled
        assert serves_ledger_tools() is (enabled or transport == 'stdio')

    @pytest.mark.parametrize(
        ('transport', 'auth', 'flag', 'registered'),
        [
            ('streamable-http', 'true', 'true', True),
            ('streamable-http', 'true', '', False),
            ('sse', '', 'true', False),
            ('stdio', '', '', True),
        ],
    )
    def test_registration_follows_the_flag(
        self, monkeypatch, transport, auth, flag, registered
    ):
        handed: dict[str, set[str]] = {}
        monkeypatch.setattr(res, 'register_resources', lambda m: handed.update(m=m))
        monkeypatch.setattr(declared_agent, '_environment_fallback', False)
        monkeypatch.setattr(server, 'mcp', MagicMock())
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'restored-on-teardown')
        monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', auth)
        monkeypatch.setenv('ALPACON_MCP_REMOTE_LEDGER', flag)
        for name in (
            'AUTH0_ALPACON_DOMAIN',
            'AUTH0_ALPACON_LOGIN_CLIENT_ID',
            'AUTH0_ALPACON_LOGIN_CLIENT_SECRET',
        ):
            monkeypatch.setenv(name, OAUTH_ENV[name])

        with patch('importlib.import_module'):
            server.prepare(transport, toolsets='ledger')

        assert ('ledger_tools' in handed['m']) is registered


class TestEnvelopes:
    def test_round_trip(self):
        assert decrypt(KEY, b'p', encrypt(KEY, b'p', {'a': 1})) == {'a': 1}

    @pytest.mark.parametrize(
        'blob',
        [None, '', 'not-base64!', 'c2hvcnQ', 123],
    )
    def test_garbage_does_not_open(self, blob):
        assert decrypt(KEY, b'p', blob) is None

    def test_a_purpose_does_not_open_another(self):
        assert decrypt(KEY, b'other', encrypt(KEY, b'p', {'a': 1})) is None

    def test_another_key_does_not_open_it(self):
        assert decrypt(OTHER_KEY, b'p', encrypt(KEY, b'p', {'a': 1})) is None

    def test_a_flipped_byte_does_not_open(self):
        blob = encrypt(KEY, b'p', {'a': 1})
        flipped = blob[:-2] + ('A' if blob[-2] != 'A' else 'B') + blob[-1]
        assert decrypt(KEY, b'p', flipped) is None

    def test_grant_seal_round_trip(self):
        grant = _grant()
        assert open_grant(KEY, seal_grant(KEY, grant)) == grant

    def test_a_stage_seal_opens_only_for_its_browser(self):
        grant = _grant()
        sealed = seal_stage(KEY, grant, 'nonce-a')
        assert open_stage(KEY, sealed, 'nonce-a') == grant
        assert open_stage(KEY, sealed, 'nonce-b') is None
        assert open_stage(KEY, sealed, '') is None

    def test_a_stage_seal_is_not_a_grant_seal(self):
        grant = _grant()
        assert open_grant(KEY, seal_stage(KEY, grant, 'n')) is None
        assert open_stage(KEY, seal_grant(KEY, grant), 'n') is None

    def test_wrap_round_trip(self):
        grant = _grant()
        wrapped = wrap_access_token(KEY, 'auth0-access', grant)
        assert wrapped.startswith(WRAPPED_ACCESS_PREFIX)
        assert 'auth0-access' not in wrapped
        assert grant.token not in wrapped
        assert unwrap_access_token(KEY, wrapped) == ('auth0-access', grant)

    def test_an_unwrapped_or_foreign_token_does_not_unwrap(self):
        grant = _grant()
        assert unwrap_access_token(KEY, 'eyJ.plain.jwt') is None
        assert (
            unwrap_access_token(OTHER_KEY, wrap_access_token(KEY, 'a', grant)) is None
        )
        # A grant envelope under the access prefix is still the wrong purpose.
        assert (
            unwrap_access_token(KEY, WRAPPED_ACCESS_PREFIX + seal_grant(KEY, grant))
            is None
        )


class TestGrant:
    def test_from_a_token_response(self):
        exp = int(time.time()) + 600
        grant = grant_from_token_response(
            {'access_token': _jwt(ALICE, exp), 'expires_in': 9999}, WORKSPACE
        )
        assert grant is not None
        assert (grant.subject, grant.org, grant.expires_at) == (ALICE, WORKSPACE, exp)

    def test_expires_in_when_the_token_has_no_exp(self):
        grant = grant_from_token_response(
            {'access_token': _jwt(ALICE), 'expires_in': 600}, WORKSPACE, now=1000
        )
        assert grant is not None
        assert grant.expires_at == 1600

    @pytest.mark.parametrize(
        'body',
        [
            {},
            {'access_token': ''},
            {'access_token': 'not-a-jwt', 'expires_in': 600},
            {'access_token': _jwt(''), 'expires_in': 600},
            {'access_token': _jwt(ALICE)},
        ],
    )
    def test_refused_without_subject_or_lifetime(self, body):
        assert grant_from_token_response(body, WORKSPACE) is None

    def test_usable_only_for_its_org_and_before_expiry(self):
        grant = _grant(ttl=3600)
        assert grant.usable_for(WORKSPACE)
        assert not grant.usable_for('otherworkspace')
        assert not grant.usable_for(WORKSPACE, now=grant.expires_at)
        assert not grant.usable_for(
            WORKSPACE, now=grant.expires_at - EXPIRY_SKEW_SECONDS
        )

    def test_a_failure_record(self):
        record = LedgerGrant.failed(WORKSPACE, now=1000)
        assert record.is_failure
        assert not record.usable_for(WORKSPACE, now=1000)
        assert record.is_recent(now=1000 + 599)
        assert not record.is_recent(now=1000 + 600)
        assert record.is_live(now=1000 + 599)
        assert not record.is_live(now=1000 + 600)
        assert LedgerGrant.from_json(record.to_json()) == record

    def test_a_token_without_a_subject_does_not_parse(self):
        half = {**_grant().to_json(), 's': ''}
        assert LedgerGrant.from_json(half) is None

    def test_claims_round_trip_through_an_access_token(self):
        grant = _grant()
        access = AccessToken(
            token='t', client_id=ALICE, scopes=[], claims=ledger_claims(grant)
        )
        assert ledger_grant_of(access) == grant
        assert (
            ledger_grant_of(AccessToken(token='t', client_id=ALICE, scopes=[])) is None
        )
        assert ledger_grant_of(None) is None


@pytest.fixture
def oauth(remote_env):
    mock_server = MockMCPServer()
    register_oauth_routes(mock_server)
    return TestClient(
        Starlette(routes=mock_server.routes),
        raise_server_exceptions=False,
        cookies={_NONCE_COOKIE_NAME: TEST_NONCE},
    )


def _query(response) -> dict[str, str]:
    return {
        k: v[0]
        for k, v in parse_qs(urlparse(response.headers['location']).query).items()
    }


def _authorize(client, scope):
    return client.get(
        '/oauth/authorize',
        params={
            'response_type': 'code',
            'redirect_uri': 'http://localhost:8080/callback',
            'scope': scope,
            'state': 'client-state',
            **PKCE_PARAMS,
        },
        follow_redirects=False,
    )


def _state(**extra: object) -> str:
    return _build_state(
        'http://localhost:8080/callback',
        'client-state',
        nonce_hash=_hash_nonce(TEST_NONCE),
        device_id=DEVICE_ID,
        original_scope='openid profile email offline_access device:' + DEVICE_ID,
        authorize_params=dict(PKCE_PARAMS),
        **extra,
    )


class TestAuthorize:
    def test_a_ledger_scope_signs_in_to_the_ledger_first(self, oauth):
        response = _authorize(oauth, f'openid profile ledger:{WORKSPACE}')

        assert response.status_code == HTTPStatus.FOUND
        query = _query(response)
        assert query['audience'] == 'https://alpacon.ai/'
        assert query['client_id'] == OAUTH_ENV['AUTH0_ALPACON_LOGIN_CLIENT_ID']
        state = _verify_state(query['state'])
        assert state is not None
        assert query['scope'] == (
            f'openid profile email org:{WORKSPACE} device:{state["device_id"]}'
        )
        assert 'offline_access' not in query['scope']
        assert 'code_challenge' not in query
        state = _verify_state(query['state'])
        assert state is not None
        assert state['stage'] == 'ledger'
        assert state['ledger_org'] == WORKSPACE
        assert 'ledger:' not in str(state['original_scope'])
        assert state['authorize_params'] == PKCE_PARAMS

    def test_the_flag_off_drops_the_ledger_scope(self, oauth, monkeypatch):
        monkeypatch.setenv('ALPACON_MCP_REMOTE_LEDGER', '')
        query = _query(_authorize(oauth, f'openid ledger:{WORKSPACE}'))
        assert query['audience'] == OAUTH_ENV['AUTH0_ALPACON_USER_AUDIENCE']
        assert 'ledger:' not in query['scope']
        state = _verify_state(query['state'])
        assert state is not None
        assert 'ledger_org' not in state

    @pytest.mark.parametrize('org', ['', 'bad"name', 'a/b', '-x'])
    def test_a_malformed_workspace_is_ignored(self, oauth, org):
        query = _query(_authorize(oauth, f'openid ledger:{org}'))
        assert query['audience'] == OAUTH_ENV['AUTH0_ALPACON_USER_AUDIENCE']
        assert 'ledger:' not in query['scope']

    def test_the_latest_challenged_workspace_wins(self, oauth):
        # Clients append the new challenge to their scope union.
        query = _query(
            _authorize(oauth, 'openid ledger:workspace-a ledger:workspace-b')
        )
        assert query['scope'].startswith('openid profile email org:workspace-b ')
        state = _verify_state(query['state'])
        assert state is not None
        assert state['ledger_org'] == 'workspace-b'
        assert 'ledger:' not in str(state['original_scope'])

    def test_a_tagged_challenge_wins_by_its_tag_not_its_position(self, oauth):
        # A union keeps the first copy of a scope, so position alone can lie.
        query = _query(
            _authorize(oauth, 'openid ledger:workspace-a:300 ledger:workspace-b:200')
        )
        assert query['scope'].startswith('openid profile email org:workspace-a ')

    @pytest.mark.parametrize(
        'tag', ['x1', '1.5', '\u00b2', '1' * 21, '-1'], ids=lambda t: repr(t)
    )
    def test_a_malformed_tag_is_ignored(self, oauth, tag):
        query = _query(_authorize(oauth, f'openid ledger:workspace-a:{tag}'))
        assert query['audience'] == OAUTH_ENV['AUTH0_ALPACON_USER_AUDIENCE']

    def test_mfa_runs_first_and_keeps_the_ledger_for_later(self, oauth):
        query = _query(_authorize(oauth, f'openid mfa ledger:{WORKSPACE}'))
        assert query['audience'].endswith('/mfa/')
        state = _verify_state(query['state'])
        assert state is not None
        assert state['stage'] == 'mfa'
        assert state['ledger_org'] == WORKSPACE


class TestCallback:
    def test_ledger_stage_keeps_the_token_in_a_cookie_and_goes_on(self, oauth):
        token = _jwt(ALICE, int(time.time()) + 600)
        auth0 = _mock_auth0_response(json_data={'access_token': token})
        with patch('utils.oauth.httpx.AsyncClient', return_value=auth0):
            response = oauth.get(
                '/oauth/callback',
                params={
                    'code': 'ledger-code',
                    'state': _state(stage='ledger', ledger_org=WORKSPACE),
                },
                follow_redirects=False,
            )

        assert response.status_code == HTTPStatus.FOUND
        sent = auth0.post.call_args.kwargs['data']
        assert sent['code'] == 'ledger-code'
        assert sent['client_secret'] == OAUTH_ENV['AUTH0_ALPACON_LOGIN_CLIENT_SECRET']
        query = _query(response)
        assert query['audience'] == OAUTH_ENV['AUTH0_ALPACON_USER_AUDIENCE']
        assert query['code_challenge'] == PKCE_PARAMS['code_challenge']
        state = _verify_state(query['state'])
        assert state is not None
        assert (state['stage'], state['ledger_org']) == ('regular', WORKSPACE)
        cookie = response.cookies.get(_LEDGER_COOKIE_NAME)
        assert token not in response.headers['location']
        grant = open_stage(ledger_grant_key(), cookie, _hash_nonce(TEST_NONCE))
        assert grant is not None
        assert (grant.token, grant.subject, grant.org) == (token, ALICE, WORKSPACE)

    def _assert_failure_staged(self, response):
        assert response.status_code == HTTPStatus.FOUND
        assert _query(response)['audience'] == OAUTH_ENV['AUTH0_ALPACON_USER_AUDIENCE']
        staged = open_stage(
            ledger_grant_key(),
            response.cookies.get(_LEDGER_COOKIE_NAME),
            _hash_nonce(TEST_NONCE),
        )
        assert staged is not None
        assert staged.is_failure
        assert staged.org == WORKSPACE

    def test_a_failed_ledger_exchange_still_signs_the_person_in(self, oauth):
        auth0 = _mock_auth0_response(
            status_code=HTTPStatus.FORBIDDEN, json_data={'error': 'access_denied'}
        )
        with patch('utils.oauth.httpx.AsyncClient', return_value=auth0):
            response = oauth.get(
                '/oauth/callback',
                params={
                    'code': 'ledger-code',
                    'state': _state(stage='ledger', ledger_org=WORKSPACE),
                },
                follow_redirects=False,
            )
        self._assert_failure_staged(response)

    def test_an_auth0_error_on_the_ledger_stage_still_signs_the_person_in(self, oauth):
        auth0 = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=auth0):
            response = oauth.get(
                '/oauth/callback',
                params={
                    'error': 'access_denied',
                    'error_description': 'not a member of the organization',
                    'state': _state(stage='ledger', ledger_org=WORKSPACE),
                },
                follow_redirects=False,
            )
        self._assert_failure_staged(response)
        auth0.post.assert_not_called()

    def test_mfa_stage_hands_over_to_the_ledger_stage(self, oauth):
        with patch(
            'utils.oauth.httpx.AsyncClient', return_value=_mock_auth0_response()
        ):
            response = oauth.get(
                '/oauth/callback',
                params={
                    'code': 'mfa-code',
                    'state': _state(stage='mfa', ledger_org=WORKSPACE),
                },
                follow_redirects=False,
            )
        query = _query(response)
        assert query['audience'] == 'https://alpacon.ai/'
        state = _verify_state(query['state'])
        assert state is not None
        assert state['stage'] == 'ledger'
        # The same id as the grant's regular sign-in, not a new one.
        assert f'device:{DEVICE_ID}' in query['scope'].split()
        assert state['device_id'] == DEVICE_ID

    def test_the_ledger_leg_uses_the_grants_device_id(self, oauth):
        response = oauth.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
                'scope': f'openid device:{DEVICE_ID} ledger:{WORKSPACE}',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        scope = _query(response)['scope'].split()
        assert [p for p in scope if p.startswith('device:')] == [f'device:{DEVICE_ID}']

    def _final(self, oauth, cookie: str | None, ledger_org: str = WORKSPACE):
        if cookie is not None:
            oauth.cookies.set(_LEDGER_COOKIE_NAME, cookie)
        return oauth.get(
            '/oauth/callback',
            params={
                'code': 'final-code',
                'state': _state(stage='regular', ledger_org=ledger_org),
            },
            follow_redirects=False,
        )

    def test_the_final_code_carries_the_staged_grant(self, oauth):
        grant = _grant()
        cookie = seal_stage(ledger_grant_key(), grant, _hash_nonce(TEST_NONCE))

        response = self._final(oauth, cookie)

        code = _query(response)['code']
        opened = _open_seal('code', code)
        assert opened is not None
        assert opened[:2] == ('final-code', DEVICE_ID)
        assert open_grant(ledger_grant_key(), opened[2]) == grant
        assert grant.token not in response.headers['location']
        cleared = [
            c
            for c in response.headers.get_list('set-cookie')
            if c.startswith(f'{_LEDGER_COOKIE_NAME}=')
        ]
        assert len(cleared) == 1
        assert cleared[0].startswith(f'{_LEDGER_COOKIE_NAME}="";')
        assert 'max-age=0' in cleared[0].lower()

    @pytest.mark.parametrize('case', ['other-browser', 'other-org', 'garbage', 'none'])
    def test_a_grant_that_is_not_this_flows_is_left_out(self, oauth, case):
        grant = _grant(org='otherworkspace' if case == 'other-org' else WORKSPACE)
        nonce = _hash_nonce(
            'another-browser' if case == 'other-browser' else TEST_NONCE
        )
        cookie = {
            'garbage': 'garbage',
            'none': None,
        }.get(case, seal_stage(ledger_grant_key(), grant, nonce))

        response = self._final(oauth, cookie)

        opened = _open_seal('code', _query(response)['code'])
        assert opened is not None
        assert opened[2] == ''


class TestTokenEndpoint:
    def test_a_refresh_never_forwards_the_pseudo_scopes(self, oauth):
        auth0 = _mock_auth0_response(json_data={'access_token': 'a'})
        with patch('utils.oauth.httpx.AsyncClient', return_value=auth0):
            oauth.post(
                '/oauth/token',
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': _seal_refresh_token('r', DEVICE_ID),
                    'scope': f'openid offline_access mfa ledger:{WORKSPACE}',
                },
            )
        assert auth0.post.call_args.kwargs['data']['scope'] == 'openid offline_access'

    def test_a_failure_record_rides_without_a_subject_check(self, oauth):
        access = _jwt(ALICE, int(time.time()) + 600)
        failed = LedgerGrant.failed(WORKSPACE)
        body = self._exchange(
            oauth, {'access_token': access}, seal_grant(ledger_grant_key(), failed)
        )
        assert unwrap_access_token(ledger_grant_key(), body['access_token']) == (
            access,
            failed,
        )

    def _exchange(
        self, oauth, auth0_body, ledger: str, grant_type='authorization_code'
    ):
        auth0 = _mock_auth0_response(json_data=auth0_body)
        if grant_type == 'authorization_code':
            data = {
                'grant_type': grant_type,
                'code': _seal_code('c', DEVICE_ID, ledger),
            }
        else:
            data = {
                'grant_type': grant_type,
                'refresh_token': _seal_refresh_token('r', DEVICE_ID, ledger),
            }
        with patch('utils.oauth.httpx.AsyncClient', return_value=auth0):
            response = oauth.post('/oauth/token', data=data)
        assert response.status_code == HTTPStatus.OK
        return response.json()

    def test_the_access_token_carries_the_grant(self, oauth):
        grant = _grant()
        access = _jwt(ALICE, int(time.time()) + 600)
        body = self._exchange(
            oauth,
            {'access_token': access, 'refresh_token': 'v1.rt'},
            seal_grant(ledger_grant_key(), grant),
        )

        assert unwrap_access_token(ledger_grant_key(), body['access_token']) == (
            access,
            grant,
        )
        opened = _open_seal('refresh', body['refresh_token'])
        assert opened is not None
        assert open_grant(ledger_grant_key(), opened[2]) == grant

    def test_a_grant_for_another_person_is_dropped(self, oauth):
        access = _jwt(BOB, int(time.time()) + 600)
        body = self._exchange(
            oauth,
            {'access_token': access, 'refresh_token': 'v1.rt'},
            seal_grant(ledger_grant_key(), _grant(sub=ALICE)),
        )
        assert body['access_token'] == access
        opened = _open_seal('refresh', body['refresh_token'])
        assert opened is not None
        assert opened[2] == ''

    def test_a_refresh_carries_the_grant_until_it_expires(self, oauth):
        access = _jwt(ALICE, int(time.time()) + 600)
        live = self._exchange(
            oauth,
            {'access_token': access, 'refresh_token': 'v1.rt'},
            seal_grant(ledger_grant_key(), _grant()),
            grant_type='refresh_token',
        )
        assert live['access_token'].startswith(WRAPPED_ACCESS_PREFIX)

        expired = self._exchange(
            oauth,
            {'access_token': access, 'refresh_token': 'v1.rt'},
            seal_grant(ledger_grant_key(), _grant(ttl=10)),
            grant_type='refresh_token',
        )
        assert expired['access_token'] == access
        opened = _open_seal('refresh', expired['refresh_token'])
        assert opened is not None
        assert opened[2] == ''

    def test_no_grant_leaves_the_access_token_bare(self, oauth):
        access = _jwt(ALICE, int(time.time()) + 600)
        body = self._exchange(oauth, {'access_token': access}, '')
        assert body['access_token'] == access


class TestVerifier:
    @pytest.fixture
    def verifier(self, remote_env):
        verifier = Auth0TokenVerifier()
        with (
            patch('utils.auth._fetch_jwks', AsyncMock(return_value={'keys': []})),
            patch('utils.auth._get_signing_key', return_value=MagicMock()),
        ):
            yield verifier

    def _decoded(self, sub: str):
        return patch(
            'utils.auth.decode_jwt',
            return_value={'sub': sub, 'scope': 'openid', 'exp': 2000000000},
        )

    @pytest.mark.asyncio
    async def test_a_wrapped_token_verifies_its_inner_token(self, verifier):
        grant = _grant()
        wrapped = wrap_access_token(ledger_grant_key(), 'inner-jwt', grant)
        with self._decoded(ALICE) as decode:
            access = await verifier.verify_token(wrapped)
        assert access is not None
        assert decode.call_args.args[0] == 'inner-jwt'
        assert access.token == 'inner-jwt'
        assert ledger_grant_of(access) == grant

    @pytest.mark.asyncio
    async def test_a_grant_for_another_subject_is_dropped(self, verifier):
        wrapped = wrap_access_token(ledger_grant_key(), 'inner-jwt', _grant(sub=BOB))
        with self._decoded(ALICE):
            access = await verifier.verify_token(wrapped)
        assert access is not None
        assert access.token == 'inner-jwt'
        assert ledger_grant_of(access) is None

    @pytest.mark.asyncio
    async def test_a_wrapped_token_that_does_not_open_is_rejected(self, verifier):
        forged = wrap_access_token(OTHER_KEY, 'inner-jwt', _grant())
        with self._decoded(ALICE) as decode:
            assert await verifier.verify_token(forged) is None
        decode.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failure_record_reaches_the_tool(self, verifier):
        failed = LedgerGrant.failed(WORKSPACE)
        wrapped = wrap_access_token(ledger_grant_key(), 'inner-jwt', failed)
        with self._decoded(ALICE):
            access = await verifier.verify_token(wrapped)
        assert access is not None
        assert ledger_grant_of(access) == failed

    @pytest.mark.asyncio
    async def test_a_bare_token_carries_no_grant(self, verifier):
        with self._decoded(ALICE):
            access = await verifier.verify_token('plain-jwt')
        assert access is not None
        assert access.claims is None


class TestWorkspaceSwitching:
    """A, B, then A again: the SDK's own scope union must not pin the ledger to B."""

    async def _challenge_scope(self, org: str):
        sent: list[dict[str, object]] = []

        async def app(scope, receive, send):
            request_signal.signal_upstream_auth_error({'ledger_org': org})
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{}'})

        async def send(message):
            sent.append(message)

        async def receive():
            return {'type': 'http.request', 'body': b''}

        await UpstreamAuthErrorMiddleware(app)(
            {'type': 'http', 'path': '/mcp', 'headers': []}, receive, send
        )
        raw_headers = sent[0]['headers']
        assert isinstance(raw_headers, list)
        header = dict(raw_headers)[b'www-authenticate'].decode()
        return header.split('scope="', 1)[1].split('"', 1)[0]

    @pytest.mark.asyncio
    async def test_switching_back_signs_in_for_the_workspace_asked(self, remote_env):
        scope = 'openid profile email offline_access'
        signed_in_for = []
        for org in ['ws-a', 'ws-b', 'ws-a', 'ws-b', 'ws-a']:
            time.sleep(0.002)  # distinct millisecond tags
            scope = union_scopes(scope, await self._challenge_scope(org)) or ''
            signed_in_for.append(_ledger_org(scope))
        assert signed_in_for == ['ws-a', 'ws-b', 'ws-a', 'ws-b', 'ws-a']


class TestChallenge:
    async def _run(self, signal):
        async def app(scope, receive, send):
            request_signal.signal_upstream_auth_error(signal)
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{}'})

        sent: list[dict[str, object]] = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {'type': 'http.request', 'body': b''}

        scope = {
            'type': 'http',
            'path': '/mcp',
            'headers': [(b'authorization', b'Bearer x')],
        }
        await UpstreamAuthErrorMiddleware(app)(scope, receive, send)
        start = sent[0]
        raw_headers = start['headers']
        assert isinstance(raw_headers, list)
        headers = {name: value for name, value in raw_headers}
        return start['status'], headers.get(b'www-authenticate', b'').decode()

    @pytest.mark.asyncio
    async def test_a_ledger_signal_asks_for_the_ledger_scope(self):
        status, header = await self._run({'ledger_org': WORKSPACE, 'source': 'ledger'})
        assert status == HTTPStatus.FORBIDDEN
        assert 'insufficient_scope' in header
        assert f'ledger:{WORKSPACE}' in header
        assert ' mfa' not in header

    @pytest.mark.asyncio
    async def test_mfa_and_ledger_together(self):
        status, header = await self._run(
            {'ledger_org': WORKSPACE, 'mfa_required': True}
        )
        assert status == HTTPStatus.FORBIDDEN
        assert f'mfa ledger:{WORKSPACE}' in header

    @pytest.mark.asyncio
    async def test_a_malformed_workspace_never_reaches_the_header(self):
        status, header = await self._run({'ledger_org': 'x" injected="y'})
        assert status == HTTPStatus.UNAUTHORIZED
        assert 'ledger:' not in header
        assert 'injected' not in header


mock_http_client = http_client_fixture('tools.ledger_tools')


@pytest.fixture
def remote(mock_http_client, remote_env):
    """A remote session on an `ai` workspace; the stdio cache must stay untouched."""
    mock_http_client.get.return_value = AI_ENV
    mock_http_client.request = AsyncMock(return_value={'ok': True})
    stdio_cache = MagicMock()
    stdio_cache.token_for = AsyncMock(side_effect=AssertionError('stdio cache read'))
    stdio_cache.has_token.side_effect = AssertionError('stdio cache read')
    claims = [{'schema_name': WORKSPACE, 'region': 'ap1'}]
    with (
        patch('tools.ledger_tools.ledger_authorizer', stdio_cache),
        patch('utils.decorators._get_jwt_token', return_value='session-jwt'),
        patch('utils.decorators.get_token_workspaces', return_value=claims),
    ):
        yield mock_http_client


def _session(grant: LedgerGrant | None, sub: str = ALICE):
    access = AccessToken(
        token='session-jwt',
        client_id=sub,
        scopes=[],
        claims=ledger_claims(grant) if grant is not None else None,
    )
    return patch('tools.ledger_tools.get_access_token', return_value=access)


def _sent_token(client):
    return client.request.call_args.kwargs['token']


class TestRemoteTools:
    @pytest.mark.asyncio
    async def test_each_caller_uses_only_its_own_grant(self, remote):
        alice, bob = _grant(sub=ALICE), _grant(sub=BOB)

        with _session(alice):
            await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        assert _sent_token(remote) == alice.token

        with _session(bob, sub=BOB):
            await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        assert _sent_token(remote) == bob.token
        assert remote.request.call_args.args[1] == f'{LEDGER}entries/'

    @pytest.mark.asyncio
    async def test_another_connection_does_not_reuse_an_earlier_grant(self, remote):
        with _session(_grant()):
            first = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        assert first['status'] == 'success'
        remote.request.reset_mock()

        signal = request_signal.begin_request()
        try:
            with _session(None):
                second = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        finally:
            request_signal.end_request()

        assert second['status'] == AUTHORIZATION_REQUIRED
        assert second['requires_human_action'] is True
        assert signal['ledger_org'] == WORKSPACE
        remote.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'grant',
        [_grant(ttl=-1), _grant(ttl=EXPIRY_SKEW_SECONDS // 2), _grant(org='otherws')],
        ids=['expired', 'about-to-expire', 'other-workspace'],
    )
    async def test_an_unusable_grant_asks_to_sign_in_again(self, remote, grant):
        signal = request_signal.begin_request()
        try:
            with _session(grant):
                result = await get_ledger_capability(workspace=WORKSPACE, region='ap1')
        finally:
            request_signal.end_request()

        assert result['status'] == AUTHORIZATION_REQUIRED
        assert WORKSPACE in result['message']
        assert signal['ledger_org'] == WORKSPACE
        remote.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_ledger_401_asks_to_sign_in_again(self, remote):
        remote.request.return_value = UNAUTHORIZED_ENVELOPE
        signal = request_signal.begin_request()
        try:
            with _session(_grant()):
                result = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        finally:
            request_signal.end_request()

        assert result['status'] == AUTHORIZATION_REQUIRED
        assert result['detail'] == {'detail': 'Invalid token audience.'}
        assert signal['ledger_org'] == WORKSPACE
        remote.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_ledger_401_right_after_sign_in_is_not_asked_again(self, remote):
        remote.request.return_value = UNAUTHORIZED_ENVELOPE
        signal = request_signal.begin_request()
        try:
            with _session(_grant(age=5)):
                result = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        finally:
            request_signal.end_request()

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED
        assert result['detail'] == {'detail': 'Invalid token audience.'}
        assert 'operator' in result['message']
        assert signal == {}

    @pytest.mark.asyncio
    async def test_a_recent_failed_sign_in_is_not_asked_again(self, remote):
        signal = request_signal.begin_request()
        try:
            with _session(LedgerGrant.failed(WORKSPACE)):
                result = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        finally:
            request_signal.end_request()

        assert result['status'] == 'error'
        assert 'did not produce a token' in result['message']
        assert signal == {}
        remote.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'record',
        [
            LedgerGrant.failed(WORKSPACE, now=time.time() - 3600),
            LedgerGrant.failed('otherws'),
        ],
        ids=['past-the-window', 'other-workspace'],
    )
    async def test_an_old_or_other_failed_sign_in_asks_again(self, remote, record):
        signal = request_signal.begin_request()
        try:
            with _session(record):
                result = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        finally:
            request_signal.end_request()

        assert result['status'] == AUTHORIZATION_REQUIRED
        assert signal['ledger_org'] == WORKSPACE

    @pytest.mark.asyncio
    async def test_a_ledger_call_never_triggers_the_session_reauth(self, remote):
        with _session(_grant()):
            await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        assert remote.request.call_args.kwargs['reauth_on_401'] is False

    @pytest.mark.asyncio
    async def test_the_flag_off_refuses_before_any_grant_is_read(
        self, remote, monkeypatch
    ):
        monkeypatch.setenv('ALPACON_MCP_REMOTE_LEDGER', '')
        with _session(_grant()) as session:
            result = await list_ledger_entries(workspace=WORKSPACE, region='ap1')
        assert result['status'] == 'error'
        assert 'stdio MCP server' in result['message']
        session.assert_not_called()
        remote.request.assert_not_called()


class TestLedgerUnauthorizedIsNotASessionReauth:
    """A 401 from the ledger is about the ledger token, not the session's JWT."""

    @pytest.mark.asyncio
    async def test_the_401_comes_back_with_its_body(self, make_client, remote_env):
        body = {'detail': 'Invalid token audience.'}
        client = make_client(
            httpx.MockTransport(lambda r: httpx.Response(401, json=body))
        )
        signal = request_signal.begin_request()
        try:
            result = await client.request(
                'GET', f'{LEDGER}entries/', token=_grant().token, reauth_on_401=False
            )
        finally:
            request_signal.end_request()

        assert isinstance(result, dict)
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED
        assert json.loads(str(result['response'])) == body
        assert signal == {}

    @pytest.mark.asyncio
    async def test_the_default_still_reauthenticates_the_session(
        self, make_client, remote_env
    ):
        client = make_client(httpx.MockTransport(lambda r: httpx.Response(401)))
        signal = request_signal.begin_request()
        try:
            with pytest.raises(UpstreamAuthError):
                await client.request('GET', f'{LEDGER}entries/', token=_grant().token)
        finally:
            request_signal.end_request()
        assert 'mfa_required' in signal
