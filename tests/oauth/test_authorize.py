"""Tests for the /oauth/authorize endpoint."""

import re
from http import HTTPStatus
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    EXEMPT_REDIRECT_URI,
    FULL_SCOPE,
    LISTED_REDIRECT_URI,
    NONCE_COOKIE_PREFIX,
    OTHER_DEVICE_ID,
    PKCE_CHALLENGE,
    PKCE_PARAMS,
    REPORT_ONLY,
    TEST_AUTH0_DOMAIN,
    TEST_CLIENT_ID,
    TEST_NONCE,
    TEST_RESOURCE_URL,
    UNLISTED_PATH_URI,
    _authorize,
    _authorize_device_id,
    _authorize_scope_parts,
)
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CALLBACK_PATH,
    _ERROR_INVALID_REQUEST,
    _METADATA_PATH,
    _OFFLINE_ACCESS_SCOPE,
    _PKCE_CHALLENGE_METHOD,
)
from utils.oauth._sealing import (
    _NONCE_COOKIE_NAME,
    _STATE_SECRET_ENV,
    _hash_nonce,
    _verify_state,
)


class TestAuthorizeObservation:
    """Tests for the observation-window log line."""

    def test_logs_redirect_uri_and_pkce_method(self, oauth_app, caplog):
        with caplog.at_level('INFO'):
            oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': LISTED_REDIRECT_URI,
                    'code_challenge': 'abc',
                    'code_challenge_method': 'S256',
                },
                follow_redirects=False,
            )

        assert LISTED_REDIRECT_URI in caplog.text
        assert 'S256' in caplog.text

    def test_records_absent_pkce(self, oauth_app, caplog):
        with caplog.at_level('INFO'):
            oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': LISTED_REDIRECT_URI,
                },
                follow_redirects=False,
            )

        assert 'pkce: none' in caplog.text

    def test_escapes_control_characters(self, oauth_app, caplog):
        """A raw newline would otherwise look like a second log line."""
        with caplog.at_level('INFO'):
            oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://evil.example/cb\nforged line',
                },
                follow_redirects=False,
            )

        assert 'cb\\nforged line' in caplog.text
        assert 'cb\nforged line' not in caplog.text


class TestOAuthAuthorize:
    """Tests for /oauth/authorize endpoint."""

    def test_authorize_redirects_to_auth0(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:52048/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert location.startswith(f'https://{TEST_AUTH0_DOMAIN}/authorize')

    def test_authorize_overrides_redirect_uri_to_server_callback(self, oauth_app):
        """redirect_uri sent to Auth0 should be the MCP server's own callback."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:52048/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert params['redirect_uri'] == [f'{TEST_RESOURCE_URL}{_CALLBACK_PATH}']

    def test_authorize_stores_client_redirect_uri_in_state(self, oauth_app):
        """Client's original redirect_uri should be encoded in the state param."""
        client_uri = 'http://localhost:52048/callback'
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': client_uri,
                'state': 'original-state',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        composite_state = params['state'][0]
        state_data = _verify_state(composite_state)
        assert state_data['redirect_uri'] == client_uri
        assert state_data['state'] == 'original-state'

    def test_authorize_enforces_configured_client_id(self, oauth_app):
        """Even if a different client_id is provided, configured one is used."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'client_id': 'attacker-client-id',
                'response_type': 'code',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        location = response.headers['location']
        assert f'client_id={TEST_CLIENT_ID}' in location
        assert 'attacker-client-id' not in location

    def test_authorize_sets_default_response_type(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'redirect_uri': 'http://localhost:3000/callback', **PKCE_PARAMS},
            follow_redirects=False,
        )
        location = response.headers['location']
        assert 'response_type=code' in location

    def test_authorize_rejects_untrusted_redirect_uri(self, oauth_app):
        """Untrusted redirect_uris should be rejected to prevent open redirect."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'https://evil.com/callback',
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data['error'] == _ERROR_INVALID_REQUEST
        assert 'allowlisted' in data['error_description']

    def test_authorize_rejects_untracked_path(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': UNLISTED_PATH_URI,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_authorize_reports_malformed_state_secret(self, oauth_app):
        """Signing is the first place a bad key raises; the message must survive."""
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'correct-horse-battery'}):
            response = oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': 'http://localhost:52048/callback',
                    **PKCE_PARAMS,
                },
                follow_redirects=False,
            )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'must be hex' in response.json()['error']

    def test_authorize_allows_claude_ai_redirect_uri(self, oauth_app):
        """Claude web redirect_uri is one of the allowlisted callback endpoints."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND

    def test_authorize_allows_chatgpt_redirect_uri(self, oauth_app):
        """ChatGPT redirect_uri is one of the allowlisted callback endpoints."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'https://chatgpt.com/connector_platform_oauth_redirect',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND

    def test_authorize_allows_custom_redirect_uris(self, oauth_app):
        """Overriding both env vars admits a custom endpoint and drops the defaults."""
        with patch.dict(
            'os.environ',
            {
                'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com',
                'ALLOWED_REDIRECT_URIS': 'https://custom.example.com/callback',
            },
        ):
            response = oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://custom.example.com/callback',
                    **PKCE_PARAMS,
                },
                follow_redirects=False,
            )
            assert response.status_code == HTTPStatus.FOUND

            response = oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': LISTED_REDIRECT_URI,
                },
            )
            assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_authorize_rejects_domain_override_without_uri_override(self, oauth_app):
        """ALLOWED_REDIRECT_DOMAINS alone no longer admits a host.

        Breaking change: the domain list clears the host check, but the endpoint
        allowlist still has to list the callback URI.
        """
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com'}
        ):
            response = oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://custom.example.com/callback',
                },
                follow_redirects=False,
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_authorize_rejects_http_trusted_domain(self, oauth_app):
        """Trusted domains must use https to prevent code leakage over plaintext."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://claude.ai/api/mcp/auth_callback',
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_authorize_allows_127_0_0_1_redirect_uri(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://127.0.0.1:8080/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND

    def test_authorize_adds_offline_access_when_missing(self, oauth_app):
        """offline_access scope is added automatically for refresh token support."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
                'scope': 'openid profile',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert _OFFLINE_ACCESS_SCOPE in location

    def test_authorize_preserves_existing_offline_access(self, oauth_app):
        """offline_access scope is not duplicated when already present."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
                'scope': f'openid {_OFFLINE_ACCESS_SCOPE}',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        # Should appear exactly once
        assert location.count(_OFFLINE_ACCESS_SCOPE) == 1

    def test_authorize_adds_offline_access_when_no_scope(self, oauth_app):
        """offline_access scope is added even when no scope parameter is provided."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert _OFFLINE_ACCESS_SCOPE in location

    def test_authorize_mints_a_device_id_per_grant(self, oauth_app):
        """Each grant gets its own id, so two clients never share an MFA record."""
        with patch(
            'utils.oauth._authorize._mint_device_id',
            side_effect=[DEVICE_ID, OTHER_DEVICE_ID],
        ) as mint:
            first = _authorize_device_id(_authorize(oauth_app))
            second = _authorize_device_id(_authorize(oauth_app))
        assert mint.call_count == 2
        assert (first, second) == (DEVICE_ID, OTHER_DEVICE_ID)

    def test_authorize_mints_an_id_the_action_accepts(self, oauth_app):
        """The minted id has to clear the Auth0 action's validator."""
        assert re.fullmatch(
            r'[A-Za-z0-9-]{8,64}', _authorize_device_id(_authorize(oauth_app))
        )

    def test_authorize_preserves_client_device_scope(self, oauth_app):
        response = _authorize(oauth_app, 'openid device:client-own-id')
        assert response.status_code == HTTPStatus.FOUND
        assert _authorize_device_id(response) == 'client-own-id'

    @pytest.mark.parametrize('client_scope', ['device:', 'device:ab', 'device:my_id'])
    def test_authorize_mints_over_an_unusable_grant(self, oauth_app, client_scope):
        """A grant the Auth0 action rejects must not suppress the minted one."""
        response = _authorize(oauth_app, f'openid {client_scope}')
        assert response.status_code == HTTPStatus.FOUND
        assert _authorize_device_id(response) != client_scope.removeprefix('device:')

    def test_authorize_replaces_a_device_scope_the_action_cannot_reach(self, oauth_app):
        """A usable grant behind an unusable one is unreachable, so it does not count."""
        response = _authorize(oauth_app, 'openid device:ab device:good-id-1234')
        assert response.status_code == HTTPStatus.FOUND
        assert _authorize_device_id(response) != 'good-id-1234'

    def test_authorize_normalizes_a_second_device_scope_away(self, oauth_app):
        """One token leaves, so nothing rests on which one the action reads."""
        response = _authorize(oauth_app, 'openid device:good-id-1234 device:other-5678')
        assert response.status_code == HTTPStatus.FOUND
        assert _authorize_device_id(response) == 'good-id-1234'

    def test_authorize_mints_despite_device_substring(self, oauth_app):
        """A scope merely containing 'device:' is not a device id grant."""
        response = _authorize(oauth_app, 'openid read:device:status')
        assert response.status_code == HTTPStatus.FOUND
        _authorize_device_id(response)
        assert 'read:device:status' in _authorize_scope_parts(response)

    def test_authorize_mfa_state_carries_the_device_id(self, oauth_app):
        """Stage 1 parks the id in the state so Stage 2 keys on the same record."""
        response = _authorize(oauth_app, 'openid profile mfa')
        assert response.status_code == HTTPStatus.FOUND
        query = parse_qs(urlparse(response.headers['location']).query)
        state_data = _verify_state(query['state'][0])
        assert state_data.get('stage') == 'mfa'
        device_id = state_data.get('device_id')
        assert re.fullmatch(r'[A-Za-z0-9-]{8,64}', device_id)
        assert f'device:{device_id}' in state_data.get('original_scope', '').split()

    def test_authorize_mfa_scope_redirects_to_mfa_audience(self, oauth_app):
        """When 'mfa' pseudo-scope is present, redirects to Auth0 MFA audience."""
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
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        # Should redirect to MFA audience with enroll scope
        audience = params.get('audience', [''])[0]
        assert '/mfa/' in audience
        scope_value = params.get('scope', [''])[0]
        assert 'enroll' in scope_value
        assert 'read:authenticators' in scope_value
        # State should contain stage='mfa'
        state = params.get('state', [''])[0]
        state_data = _verify_state(state)
        assert state_data.get('stage') == 'mfa'

    def test_authorize_without_mfa_scope_uses_regular_audience(self, oauth_app):
        """When 'mfa' is not in scope, redirects to regular audience."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'scope': FULL_SCOPE,
                'redirect_uri': 'http://localhost:8080/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        audience = params.get('audience', [''])[0]
        assert '/mfa/' not in audience

    def test_authorize_sets_the_nonce_cookie(self, oauth_app):
        """The browser that starts the flow gets marked."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'redirect_uri': 'http://localhost:52048/callback', **PKCE_PARAMS},
            follow_redirects=False,
        )
        raw = response.headers['set-cookie'].lower()
        assert raw.startswith(NONCE_COOKIE_PREFIX)
        assert 'secure' in raw
        assert 'httponly' in raw
        assert 'samesite=lax' in raw
        assert 'path=/' in raw
        assert 'max-age=600' in raw

    def test_authorize_state_carries_the_cookie_hash(self, oauth_app):
        """The state names the browser by hash, never by the raw nonce."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'redirect_uri': 'http://localhost:52048/callback', **PKCE_PARAMS},
            follow_redirects=False,
        )
        nonce = response.cookies[_NONCE_COOKIE_NAME]
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        payload = _verify_state(state)
        assert payload['nonce_hash'] == _hash_nonce(nonce)
        assert nonce not in state

    def test_mfa_authorize_state_carries_the_cookie_hash(self, oauth_app):
        """The MFA stage-1 state is bound to the browser too."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'redirect_uri': 'http://localhost:52048/callback',
                'scope': 'openid profile mfa',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        nonce = response.cookies[_NONCE_COOKIE_NAME]
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        payload = _verify_state(state)
        assert payload['stage'] == 'mfa'
        assert payload['nonce_hash'] == _hash_nonce(nonce)

    def test_authorize_replaces_a_stale_nonce_cookie(self, oauth_app):
        """A browser arriving with an old cookie is re-marked, not trusted as it is."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'redirect_uri': 'http://localhost:52048/callback', **PKCE_PARAMS},
            follow_redirects=False,
        )
        assert TEST_NONCE not in response.headers['set-cookie']
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        assert _verify_state(state)['nonce_hash'] != _hash_nonce(TEST_NONCE)


class TestAuthorizePkce:
    """Tests for the S256 PKCE requirement at /oauth/authorize."""

    def test_pkce_missing_challenge_is_rejected(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'response_type': 'code', 'redirect_uri': LISTED_REDIRECT_URI},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data['error'] == _ERROR_INVALID_REQUEST
        assert 'code_challenge' in data['error_description']

    def test_pkce_empty_challenge_is_rejected(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': '',
                'code_challenge_method': 'S256',
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    def test_pkce_missing_method_is_rejected(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': PKCE_CHALLENGE,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'code_challenge_method' in response.json()['error_description']

    def test_pkce_plain_method_is_rejected(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': PKCE_CHALLENGE,
                'code_challenge_method': 'plain',
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'S256' in response.json()['error_description']

    def test_pkce_s256_is_accepted(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND

    def test_pkce_exempt_redirect_uri_may_omit_the_challenge(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'response_type': 'code', 'redirect_uri': EXEMPT_REDIRECT_URI},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        forwarded = parse_qs(urlparse(response.headers['location']).query)
        assert 'code_challenge' not in forwarded

    def test_pkce_exempt_redirect_uri_may_not_downgrade_to_plain(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': EXEMPT_REDIRECT_URI,
                'code_challenge': PKCE_CHALLENGE,
                'code_challenge_method': 'plain',
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pkce_deeper_path_on_the_exempt_host_is_not_exempt(self, oauth_app):
        with patch.dict('os.environ', REPORT_ONLY):
            response = oauth_app.get(
                _AUTHORIZE_PATH,
                params={
                    'response_type': 'code',
                    'redirect_uri': f'{EXEMPT_REDIRECT_URI}/deeper',
                },
                follow_redirects=False,
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'code_challenge' in response.json()['error_description']

    def test_pkce_is_required_without_a_redirect_uri(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'response_type': 'code'},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'code_challenge' in response.json()['error_description']

    def test_pkce_check_runs_after_the_redirect_uri_gate(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={'response_type': 'code', 'redirect_uri': EVIL_REDIRECT_URI},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'allowlisted' in response.json()['error_description']

    def test_pkce_challenge_reaches_auth0_unchanged(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        forwarded = parse_qs(urlparse(response.headers['location']).query)
        assert forwarded['code_challenge'] == [PKCE_CHALLENGE]
        assert forwarded['code_challenge_method'] == [_PKCE_CHALLENGE_METHOD]

    def test_pkce_fallback_route_enforces_the_same_rule(self, oauth_app):
        """/authorize delegates, so it must reject what /oauth/authorize rejects."""
        response = oauth_app.get(
            '/authorize',
            params={'response_type': 'code', 'redirect_uri': LISTED_REDIRECT_URI},
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    def test_pkce_advertised_method_is_the_enforced_one(self, oauth_app):
        advertised = oauth_app.get(_METADATA_PATH).json()[
            'code_challenge_methods_supported'
        ]
        assert advertised == [_PKCE_CHALLENGE_METHOD]

        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': PKCE_CHALLENGE,
                'code_challenge_method': advertised[0],
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND


class TestAuthorizePkceChallengeFormat:
    """RFC 7636 §4.1 fixes the challenge shape."""

    @pytest.mark.parametrize(
        'challenge',
        [
            ' ',
            'x',
            'a+b/c=',  # standard base64, not base64url
            'A' * 42,
            'A' * 129,
            f'{PKCE_CHALLENGE}\n',
        ],
    )
    def test_pkce_malformed_challenge_is_rejected(self, oauth_app, challenge):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': challenge,
                'code_challenge_method': _PKCE_CHALLENGE_METHOD,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    @pytest.mark.parametrize('length', [43, 128])
    def test_pkce_challenge_length_bounds_are_inclusive(self, oauth_app, length):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': 'A' * length,
                'code_challenge_method': _PKCE_CHALLENGE_METHOD,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND

    def test_pkce_method_is_rejected_before_the_challenge_format(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': 'x',
                'code_challenge_method': 'plain',
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'code_challenge_method' in response.json()['error_description']

    def test_pkce_exempt_redirect_uri_does_not_forward_an_uninspected_method(
        self, oauth_app
    ):
        """With no challenge the method is never inspected."""
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': EXEMPT_REDIRECT_URI,
                'code_challenge_method': 'garbage',
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        forwarded = parse_qs(urlparse(response.headers['location']).query)
        assert 'code_challenge_method' not in forwarded

    @pytest.mark.parametrize('method', ['s256', 'S256 ', ' S256', 'SHA256'])
    def test_pkce_method_comparison_is_exact(self, oauth_app, method):
        """RFC 7636 §4.3 makes the method case-sensitive.

        These pass only because the comparison is != on the raw string. A later
        .strip().upper() cleanup would start accepting all four.
        """
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
                'code_challenge': PKCE_CHALLENGE,
                'code_challenge_method': method,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'S256' in response.json()['error_description']


class TestAuthorizePkceDuplicateParams:
    """The value the gate checks must be the value forwarded upstream.

    dict(request.query_params) is last-wins and urlencode re-encodes that same
    dict, so the two agree. The agreement is load-bearing and incidental: a move
    to getlist, or a framework with first-wins semantics, would break it.
    """

    def test_pkce_duplicate_challenge_checks_the_forwarded_value(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params=[
                ('response_type', 'code'),
                ('redirect_uri', LISTED_REDIRECT_URI),
                ('code_challenge', ''),
                ('code_challenge', PKCE_CHALLENGE),
                ('code_challenge_method', _PKCE_CHALLENGE_METHOD),
            ],
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        forwarded = parse_qs(urlparse(response.headers['location']).query)
        assert forwarded['code_challenge'] == [PKCE_CHALLENGE]

    def test_pkce_duplicate_challenge_rejects_on_the_last_value(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params=[
                ('response_type', 'code'),
                ('redirect_uri', LISTED_REDIRECT_URI),
                ('code_challenge', PKCE_CHALLENGE),
                ('code_challenge', ''),
                ('code_challenge_method', _PKCE_CHALLENGE_METHOD),
            ],
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pkce_duplicate_method_checks_the_forwarded_value(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params=[
                ('response_type', 'code'),
                ('redirect_uri', LISTED_REDIRECT_URI),
                ('code_challenge', PKCE_CHALLENGE),
                ('code_challenge_method', 'plain'),
                ('code_challenge_method', _PKCE_CHALLENGE_METHOD),
            ],
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        forwarded = parse_qs(urlparse(response.headers['location']).query)
        assert forwarded['code_challenge_method'] == [_PKCE_CHALLENGE_METHOD]

    def test_pkce_duplicate_method_rejects_on_the_last_value(self, oauth_app):
        response = oauth_app.get(
            _AUTHORIZE_PATH,
            params=[
                ('response_type', 'code'),
                ('redirect_uri', LISTED_REDIRECT_URI),
                ('code_challenge', PKCE_CHALLENGE),
                ('code_challenge_method', _PKCE_CHALLENGE_METHOD),
                ('code_challenge_method', 'plain'),
            ],
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'S256' in response.json()['error_description']
