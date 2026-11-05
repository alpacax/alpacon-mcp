"""The callback endpoint: state checks, the MFA stage and code delivery."""

import base64
import json
from http import HTTPStatus
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    LISTED_REDIRECT_URI,
    PKCE_PARAMS,
    TEST_NONCE,
    TEST_NONCE_SET_COOKIE,
    TRUSTED_REDIRECT_URI,
    UNLISTED_PATH_URI,
    _browser_client,
    _forge_state_under_valid_signature,
    _mock_auth0_response,
    _state_payload,
)
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CALLBACK_PATH,
    _RESPONSE_TYPE_CODE,
)
from utils.oauth._sealing import (
    _MAX_LIVE_FLOWS,
    _NONCE_COOKIE_PREFIX,
    _SEAL_KIND_CODE,
    _STAGE_MFA,
    _hash_nonce,
    _nonce_cookie_name,
    _open_seal,
    _sign_state,
)


def _make_composite_state(redirect_uri='', state='', **extra):
    """Helper to create signed composite state as the authorize endpoint does."""
    extra.setdefault('nonce_hash', _hash_nonce(TEST_NONCE))
    extra.setdefault('device_id', DEVICE_ID)
    return _sign_state({'redirect_uri': redirect_uri, 'state': state, **extra})


class TestMfaPkceReplay:
    """The client's PKCE challenge must survive the two-stage MFA flow.
    Stage 1 authorizes without it, so the signed state holds the only copy.
    """

    def test_stage1_stashes_the_challenge_in_the_state(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': _RESPONSE_TYPE_CODE,
                'scope': 'openid profile email offline_access mfa',
                'redirect_uri': 'http://localhost:8080/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        stage1 = parse_qs(urlparse(response.headers['location']).query)
        assert 'code_challenge' not in stage1

        payload = _state_payload(stage1['state'][0])
        stashed = payload.get('authorize_params')
        assert isinstance(stashed, dict)
        assert stashed.get('code_challenge') == PKCE_PARAMS['code_challenge']
        assert (
            stashed.get('code_challenge_method') == PKCE_PARAMS['code_challenge_method']
        )

    def test_stage2_replays_the_stashed_challenge(self, oauth_app):
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage=_STAGE_MFA,
            original_scope='openid profile email offline_access',
            authorize_params=dict(PKCE_PARAMS),
        )

        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )

        assert response.status_code == HTTPStatus.FOUND
        stage2 = parse_qs(urlparse(response.headers['location']).query)
        assert stage2['code_challenge'] == [PKCE_PARAMS['code_challenge']]
        assert stage2['code_challenge_method'] == [PKCE_PARAMS['code_challenge_method']]

    def test_stage2_carries_the_device_id_forward(self, oauth_app):
        """The id minted at stage 1 is the one the final code is sealed under."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage=_STAGE_MFA,
            original_scope=f'openid offline_access device:{DEVICE_ID}',
            authorize_params=dict(PKCE_PARAMS),
            device_id=DEVICE_ID,
        )

        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )

        assert response.status_code == HTTPStatus.FOUND
        stage2 = parse_qs(urlparse(response.headers['location']).query)
        assert f'device:{DEVICE_ID}' in stage2['scope'][0].split()
        payload = _state_payload(stage2['state'][0])
        assert payload.get('device_id') == DEVICE_ID

    def test_stage2_replays_only_the_allowlisted_keys(self, oauth_app):
        """A key outside the replay allowlist cannot ride the state into stage 2."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage=_STAGE_MFA,
            original_scope='openid',
            authorize_params={**PKCE_PARAMS, 'audience': 'https://evil.example/'},
        )

        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )

        assert response.status_code == HTTPStatus.FOUND
        stage2 = parse_qs(urlparse(response.headers['location']).query)
        assert stage2['audience'] == ['https://alpacon.io/access/']


class TestOAuthCallback:
    def test_callback_redirects_to_client(self, oauth_app):
        """Callback should redirect to the client's original redirect_uri."""
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', device_id=DEVICE_ID
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert location.startswith('http://localhost:52048/callback')
        query = parse_qs(urlparse(location).query)
        assert query['state'] == ['xyz']
        assert _open_seal(_SEAL_KIND_CODE, query['code'][0]) == (
            'auth-code',
            DEVICE_ID,
            '',
        )

    def test_callback_rejects_a_state_without_a_device_id(self, oauth_app):
        """Every state this server mints carries an id; one without it cannot
        seal the code, so it is refused like any other invalid state."""
        composite = _sign_state(
            {
                'redirect_uri': 'http://localhost:52048/callback',
                'state': 'xyz',
                'nonce_hash': _hash_nonce(TEST_NONCE),
            }
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    def test_callback_rejects_unsigned_state(self, oauth_app):
        """A state we never signed must not steer the redirect."""
        unsigned = base64.urlsafe_b64encode(
            json.dumps({'redirect_uri': TRUSTED_REDIRECT_URI, 'state': 'x'}).encode()
        ).decode()
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': unsigned},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    def test_callback_rejects_tampered_state(self, oauth_app):
        """Swapping the payload under a valid signature must be rejected."""
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': _forge_state_under_valid_signature()},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'location' not in response.headers

    def test_callback_rejects_expired_state(self, oauth_app):
        """A state past its expiry must be rejected."""
        with patch('utils.oauth._sealing.time.time', return_value=1000):
            expired = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': expired},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_callback_reports_missing_config_instead_of_crashing(self, oauth_app):
        """Missing client secret: same JSON 500 as other handlers, not a stack trace."""
        with patch.dict('os.environ', {'AUTH0_ALPACON_LOGIN_CLIENT_SECRET': ''}):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'auth-code', 'state': 'aGVsbG8.c2ln'},
            )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'AUTH0_ALPACON_LOGIN_CLIENT_SECRET' in response.json()['error']

    def test_callback_returns_json_without_redirect_uri(self, oauth_app):
        """Without a client redirect_uri in state, return JSON as fallback."""
        composite = _make_composite_state('', 'xyz', device_id=DEVICE_ID)
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert _open_seal(_SEAL_KIND_CODE, data['code']) == ('auth-code', DEVICE_ID, '')
        assert data['state'] == 'xyz'

    def test_callback_missing_code(self, oauth_app):
        response = oauth_app.get(_CALLBACK_PATH, params={'state': 'xyz'})
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'

    def test_callback_rejects_a_code_without_a_state(self, oauth_app):
        """No state means no device id, so the code could never be exchanged."""
        response = oauth_app.get(_CALLBACK_PATH, params={'code': 'auth-code'})
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'

    def test_callback_error_redirects_to_client(self, oauth_app):
        """Auth0 errors should be forwarded to the client's redirect_uri."""
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={
                'error': 'access_denied',
                'error_description': 'User denied',
                'state': composite,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert 'error=access_denied' in location
        assert 'state=xyz' in location

    def test_callback_error_without_description_redirects_an_empty_description(
        self, oauth_app
    ):
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')

        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'error': 'access_denied', 'state': composite},
            follow_redirects=False,
        )

        assert response.status_code == HTTPStatus.FOUND
        query = parse_qs(
            urlparse(response.headers['location']).query, keep_blank_values=True
        )
        assert query['error_description'] == ['']

    @pytest.mark.parametrize(
        ('query', 'expected_description'),
        [({'error_description': 'User denied'}, 'User denied'), ({}, '')],
        ids=['with_description', 'without_description'],
    )
    def test_callback_error_returns_json_without_redirect_uri(
        self, oauth_app, query, expected_description
    ):
        """Auth0 errors without client redirect_uri fall back to JSON."""
        response = oauth_app.get(
            _CALLBACK_PATH, params={'error': 'access_denied', **query}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            'error': 'access_denied',
            'error_description': expected_description,
        }

    def test_callback_rejects_opaque_state(self, oauth_app):
        """A state that is not one of ours is rejected, not echoed back."""
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': 'opaque-state-value'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'

    def test_callback_does_not_redirect_to_untrusted_uri(self, oauth_app):
        """Callback must not redirect to an untrusted redirect_uri from state."""
        composite = _make_composite_state(EVIL_REDIRECT_URI, 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
        )
        # Should fall back to JSON instead of redirecting to evil.com
        assert response.status_code == HTTPStatus.OK
        assert 'location' not in response.headers
        data = response.json()
        assert _open_seal(_SEAL_KIND_CODE, data['code']) == ('auth-code', DEVICE_ID, '')

    def test_callback_does_not_relay_to_untracked_path(self, oauth_app):
        composite = _make_composite_state(UNLISTED_PATH_URI, 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        # 200 as well as the missing header: a 500 would also have no location.
        assert response.status_code == HTTPStatus.OK
        assert 'location' not in response.headers

    def test_callback_redirects_to_allowlisted_endpoint(self, oauth_app):
        """Callback relays the code to an allowlisted endpoint like claude.ai."""
        composite = _make_composite_state(LISTED_REDIRECT_URI, 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert location.startswith(LISTED_REDIRECT_URI)
        query = parse_qs(urlparse(location).query)
        assert _open_seal(_SEAL_KIND_CODE, query['code'][0]) == (
            'auth-code',
            DEVICE_ID,
            '',
        )

    def test_callback_mfa_stage_exchanges_code_and_redirects_to_stage2(self, oauth_app):
        """MFA stage callback should exchange MFA code and redirect to regular audience."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage=_STAGE_MFA,
            original_scope='openid profile email offline_access',
        )

        mock_client = _mock_auth0_response(status_code=HTTPStatus.OK)

        with patch('httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )

        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)

        # Should redirect to Auth0 with regular audience (not MFA)
        audience = params.get('audience', [''])[0]
        assert audience == 'https://alpacon.io/access/'
        assert '/mfa/' not in audience

        # Scope should be the original scope (not enroll)
        scope = params.get('scope', [''])[0]
        assert 'openid' in scope
        assert 'enroll' not in scope

        # State should contain stage='regular'
        state = params.get('state', [''])[0]
        state_data = _state_payload(state)
        assert state_data.get('stage') == 'regular'
        assert state_data.get('redirect_uri') == 'http://localhost:8080/callback'
        assert state_data.get('state') == 'orig-state'

        # MFA code should have been exchanged
        mock_client.post.assert_called_once()

    def test_final_redirect_clears_the_cookie(self, oauth_app):
        """The mark is spent once the code is relayed."""
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        raw = response.headers['set-cookie'].lower()
        assert TEST_NONCE_SET_COOKIE in raw
        assert 'max-age=0' in raw or 'expires=' in raw

    def test_json_fallback_clears_the_cookie(self, oauth_app):
        """The fallback ends the flow too, so it clears the mark as well."""
        composite = _make_composite_state('', 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH, params={'code': 'auth-code', 'state': composite}
        )
        assert response.status_code == HTTPStatus.OK
        raw = response.headers['set-cookie'].lower()
        assert TEST_NONCE_SET_COOKIE in raw
        assert 'max-age=0' in raw or 'expires=' in raw

    def test_relayed_auth0_error_clears_the_cookie(self, oauth_app):
        """An Auth0 refusal ends the flow, so its mark is spent like a code's."""
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'error': 'access_denied', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        assert parse_qs(urlparse(response.headers['location']).query)['error'] == [
            'access_denied'
        ]
        raw = response.headers['set-cookie'].lower()
        assert raw.startswith(TEST_NONCE_SET_COOKIE)
        assert 'max-age=0' in raw

    def test_rejection_leaves_the_cookie_alone(self, oauth_app):
        """Otherwise a forced callback could wipe a live flow's cookie."""
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', nonce_hash=_hash_nonce('other')
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'set-cookie' not in response.headers

    def test_mfa_stage2_state_keeps_the_same_binding(self, oauth_app):
        """Stage 2 must stay bound to the browser that cleared MFA."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage=_STAGE_MFA,
            original_scope='openid profile email offline_access',
        )
        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        payload = _state_payload(state)
        assert payload['nonce_hash'] == _hash_nonce(TEST_NONCE)

    def test_mfa_stage2_refreshes_the_cookie_lifetime(self, oauth_app):
        """Stage 2 mints a fresh state expiry, so the cookie is re-set to match."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage=_STAGE_MFA,
            original_scope='openid profile email offline_access',
        )
        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )
        raw = response.headers['set-cookie'].lower()
        assert f'{TEST_NONCE_SET_COOKIE}{TEST_NONCE}' in raw
        assert 'max-age=600' in raw

    def test_callback_rejects_a_browser_without_the_cookie(self, oauth_app_no_cookie):
        """A code must not reach a browser that never started the flow."""
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app_no_cookie.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    def test_callback_rejects_a_mismatched_cookie(self, oauth_app_no_cookie):
        """A different browser's nonce must not unlock someone else's state."""
        oauth_app_no_cookie.cookies.set(
            _nonce_cookie_name(_hash_nonce('other')), TEST_NONCE
        )
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', nonce_hash=_hash_nonce('other')
        )
        response = oauth_app_no_cookie.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    def test_callback_ignores_the_old_fixed_name_cookie(self, oauth_app_no_cookie):
        """A cookie under the pre-#160 name binds no flow."""
        oauth_app_no_cookie.cookies.set(_NONCE_COOKIE_PREFIX, TEST_NONCE)
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app_no_cookie.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'

    def test_callback_rejects_state_without_a_binding(self, oauth_app):
        """Fail closed: a state carrying no nonce_hash is not accepted."""
        composite = _sign_state(
            {'redirect_uri': 'http://localhost:52048/callback', 'state': 'xyz'}
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'location' not in response.headers

    def test_callback_rejects_a_non_ascii_binding(self, oauth_app):
        """hmac.compare_digest raises TypeError on non-ASCII str, so compare bytes."""
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', nonce_hash='서명'
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    @pytest.mark.parametrize('binding', ['', None, 0, True, ['hash'], {'v': 'hash'}])
    def test_callback_rejects_a_binding_that_is_not_a_hash(self, oauth_app, binding):
        """Fail closed on whatever else a forged state could carry as nonce_hash."""
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', nonce_hash=binding
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'location' not in response.headers

    def test_error_callback_rejects_an_unbound_state(self, oauth_app):
        """The gate sits before the error branch, so an error callback passes it too."""
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', nonce_hash=_hash_nonce('other')
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'error': 'access_denied', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        # invalid_request, not access_denied: the gate rejected it before the
        # error was relayed anywhere.
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    def test_callback_rejects_loopback_when_the_cookie_disagrees(self, oauth_app):
        """The binding closes the loopback hole the URI allowlist cannot."""
        composite = _make_composite_state(
            'http://localhost:9999/steal', 'xyz', nonce_hash=_hash_nonce('attacker')
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'location' not in response.headers


@pytest.fixture
def browser():
    return _browser_client()


def _start_flow(browser, client_state):
    """Run /oauth/authorize as a client would and return the state Auth0 echoes."""
    response = browser.get(
        _AUTHORIZE_PATH,
        params={
            'redirect_uri': 'http://localhost:52048/callback',
            'state': client_state,
            **PKCE_PARAMS,
        },
        follow_redirects=False,
    )
    assert response.status_code == HTTPStatus.FOUND
    return parse_qs(urlparse(response.headers['location']).query)['state'][0]


class TestLiveFlowLimit:
    """A browser's cookies stay small enough for its callbacks to reach the server."""

    def test_authorize_past_the_limit_is_refused_and_keeps_earlier_flows(self, browser):
        states = [_start_flow(browser, str(i)) for i in range(_MAX_LIVE_FLOWS)]
        held = dict(browser.cookies)

        refused = browser.get(
            _AUTHORIZE_PATH,
            params={'redirect_uri': 'http://localhost:52048/callback', **PKCE_PARAMS},
            follow_redirects=False,
        )

        assert refused.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert refused.json()['error'] == 'temporarily_unavailable'
        assert 'location' not in refused.headers
        assert 'set-cookie' not in refused.headers
        assert dict(browser.cookies) == held
        finished = browser.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': states[0]},
            follow_redirects=False,
        )
        assert finished.status_code == HTTPStatus.FOUND

    def test_finishing_a_flow_frees_room_for_a_new_one(self, browser):
        states = [_start_flow(browser, str(i)) for i in range(_MAX_LIVE_FLOWS)]
        browser.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': states[0]},
            follow_redirects=False,
        )

        _start_flow(browser, 'next')

    @pytest.mark.parametrize(
        ('padding', 'expected'),
        [(7800, HTTPStatus.FOUND), (7900, HTTPStatus.TOO_MANY_REQUESTS)],
    )
    def test_authorize_needs_room_for_its_nonce_cookie(
        self, oauth_app_no_cookie, padding, expected
    ):
        oauth_app_no_cookie.cookies.set('unrelated', 'x' * padding)

        response = oauth_app_no_cookie.get(
            _AUTHORIZE_PATH,
            params={'redirect_uri': 'http://localhost:52048/callback', **PKCE_PARAMS},
            follow_redirects=False,
        )

        assert response.status_code == expected


class TestOverlappingFlows:
    """Two MCP clients signing in through the same browser at the same time."""

    def test_first_flow_completes_after_a_second_authorize(self, browser):
        first = _start_flow(browser, 'client-1')
        _start_flow(browser, 'client-2')

        response = browser.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': first},
            follow_redirects=False,
        )

        assert response.status_code == HTTPStatus.FOUND
        params = parse_qs(urlparse(response.headers['location']).query)
        assert params['state'] == ['client-1']

    @pytest.mark.parametrize('order', [(0, 1), (1, 0)])
    def test_both_flows_complete_in_either_order(self, browser, order):
        states = [_start_flow(browser, 'client-1'), _start_flow(browser, 'client-2')]

        answers = [
            browser.get(
                _CALLBACK_PATH,
                params={'code': 'auth-code', 'state': states[i]},
                follow_redirects=False,
            )
            for i in order
        ]

        assert [r.status_code for r in answers] == [HTTPStatus.FOUND] * 2
        delivered = [
            parse_qs(urlparse(r.headers['location']).query)['state'] for r in answers
        ]
        assert delivered == [[f'client-{i + 1}'] for i in order]

    def test_finishing_one_flow_leaves_the_other_flows_cookie(self, browser):
        first = _start_flow(browser, 'client-1')
        second = _start_flow(browser, 'client-2')
        done = browser.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': first},
            follow_redirects=False,
        )

        replay = browser.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': first},
            follow_redirects=False,
        )
        response = browser.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': second},
            follow_redirects=False,
        )

        first_cookie = _nonce_cookie_name(str(_state_payload(first)['nonce_hash']))
        second_cookie = _nonce_cookie_name(str(_state_payload(second)['nonce_hash']))
        cleared = done.headers.get_list('set-cookie')
        assert done.status_code == HTTPStatus.FOUND
        assert [c.split('=', 1)[0] for c in cleared] == [first_cookie]
        assert 'max-age=0' in cleared[0].lower()
        assert second_cookie not in ' '.join(cleared)
        assert replay.status_code == HTTPStatus.BAD_REQUEST
        assert replay.json()['error'] == 'invalid_request'
        assert response.status_code == HTTPStatus.FOUND
