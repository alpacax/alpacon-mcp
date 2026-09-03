"""Tests for the /oauth/callback endpoint and the two-stage MFA flow."""

import base64
import json
from http import HTTPStatus
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    FULL_SCOPE,
    LISTED_REDIRECT_URI,
    NONCE_COOKIE_PREFIX,
    PKCE_PARAMS,
    TEST_NONCE,
    TRUSTED_REDIRECT_URI,
    UNLISTED_PATH_URI,
    _forge_state_under_valid_signature,
    _make_composite_state,
    _mock_auth0_response,
)
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CALLBACK_PATH,
    _DEFAULT_AUDIENCE,
    _ERROR_INVALID_REQUEST,
    _OFFLINE_ACCESS_SCOPE,
)
from utils.oauth._sealing import _hash_nonce, _sign_state, _unseal_code, _verify_state


class TestMfaPkceReplay:
    """The client's challenge has to survive the two-stage MFA flow.

    Stage 1 authorizes against the MFA audience without the challenge, so the
    signed state holds the only copy. Losing it strands the client: it still
    holds a verifier, and the code it finally exchanges was issued without one.
    """

    def test_stage1_stashes_the_challenge_in_the_state(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'scope': f'{FULL_SCOPE} mfa',
                'redirect_uri': 'http://localhost:8080/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        stage1 = parse_qs(urlparse(response.headers['location']).query)
        assert 'code_challenge' not in stage1

        stashed = _verify_state(stage1['state'][0]).get('authorize_params', {})
        assert stashed.get('code_challenge') == PKCE_PARAMS['code_challenge']
        assert (
            stashed.get('code_challenge_method') == PKCE_PARAMS['code_challenge_method']
        )

    def test_stage2_replays_the_stashed_challenge(self, oauth_app):
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage='mfa',
            original_scope=FULL_SCOPE,
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
            stage='mfa',
            original_scope=f'openid {_OFFLINE_ACCESS_SCOPE} device:{DEVICE_ID}',
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
        assert _verify_state(stage2['state'][0]).get('device_id') == DEVICE_ID

    def test_stage2_replays_only_the_allowlisted_keys(self, oauth_app):
        """A key outside the replay allowlist cannot ride the state into stage 2."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage='mfa',
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
        assert stage2['audience'] == [_DEFAULT_AUDIENCE]


class TestOAuthCallback:
    """Tests for /oauth/callback endpoint."""

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
        assert _unseal_code(query['code'][0]) == ('auth-code', DEVICE_ID)

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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
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
        with patch.dict('os.environ', {'AUTH0_CLIENT_SECRET': ''}):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'auth-code', 'state': 'aGVsbG8.c2ln'},
            )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'AUTH0_CLIENT_SECRET' in response.json()['error']

    def test_callback_returns_json_without_redirect_uri(self, oauth_app):
        """Without a client redirect_uri in state, return JSON as fallback."""
        composite = _make_composite_state('', 'xyz', device_id=DEVICE_ID)
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert _unseal_code(data['code']) == ('auth-code', DEVICE_ID)
        assert data['state'] == 'xyz'

    def test_callback_missing_code(self, oauth_app):
        response = oauth_app.get(_CALLBACK_PATH, params={'state': 'xyz'})
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    def test_callback_rejects_a_code_without_a_state(self, oauth_app):
        """No state means no device id, so the code could never be exchanged."""
        response = oauth_app.get(_CALLBACK_PATH, params={'code': 'auth-code'})
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

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

    def test_callback_error_returns_json_without_redirect_uri(self, oauth_app):
        """Auth0 errors without client redirect_uri fall back to JSON."""
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'error': 'access_denied', 'error_description': 'User denied'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'access_denied'

    def test_callback_rejects_opaque_state(self, oauth_app):
        """A state that is not one of ours is rejected, not echoed back."""
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': 'opaque-state-value'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

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
        assert _unseal_code(data['code']) == ('auth-code', DEVICE_ID)

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
        assert _unseal_code(query['code'][0]) == ('auth-code', DEVICE_ID)

    def test_callback_mfa_stage_exchanges_code_and_redirects_to_stage2(self, oauth_app):
        """MFA stage callback should exchange MFA code and redirect to regular audience."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage='mfa',
            original_scope=FULL_SCOPE,
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
        assert audience == _DEFAULT_AUDIENCE
        assert '/mfa/' not in audience

        # Scope should be the original scope (not enroll)
        scope = params.get('scope', [''])[0]
        assert 'openid' in scope
        assert 'enroll' not in scope

        # State should contain stage='regular'
        state = params.get('state', [''])[0]
        state_data = _verify_state(state)
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
        assert NONCE_COOKIE_PREFIX in raw
        assert 'max-age=0' in raw or 'expires=' in raw

    def test_json_fallback_clears_the_cookie(self, oauth_app):
        """The fallback ends the flow too, so it clears the mark as well."""
        composite = _make_composite_state('', 'xyz')
        response = oauth_app.get(
            _CALLBACK_PATH, params={'code': 'auth-code', 'state': composite}
        )
        assert response.status_code == HTTPStatus.OK
        raw = response.headers['set-cookie'].lower()
        assert NONCE_COOKIE_PREFIX in raw
        assert 'max-age=0' in raw or 'expires=' in raw

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
            stage='mfa',
            original_scope=FULL_SCOPE,
        )
        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        assert _verify_state(state)['nonce_hash'] == _hash_nonce(TEST_NONCE)

    def test_mfa_stage2_refreshes_the_cookie_lifetime(self, oauth_app):
        """Stage 2 mints a fresh state expiry, so the cookie is re-set to match."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage='mfa',
            original_scope=FULL_SCOPE,
        )
        with patch('httpx.AsyncClient', return_value=_mock_auth0_response()):
            response = oauth_app.get(
                _CALLBACK_PATH,
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )
        raw = response.headers['set-cookie'].lower()
        assert f'{NONCE_COOKIE_PREFIX}{TEST_NONCE}' in raw
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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
        assert 'location' not in response.headers

    def test_callback_rejects_a_mismatched_cookie(self, oauth_app):
        """A different browser's nonce must not unlock someone else's state."""
        composite = _make_composite_state(
            'http://localhost:52048/callback', 'xyz', nonce_hash=_hash_nonce('other')
        )
        response = oauth_app.get(
            _CALLBACK_PATH,
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'location' not in response.headers

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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
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
