"""
Unit tests for OAuth proxy endpoints.

Tests the OAuth metadata, authorize, token, and callback endpoints
including security constraints (grant_type allowlist, client_id enforcement,
error handling).
"""

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from utils.oauth import (
    _STATE_SECRET_ENV,
    _STATE_SECRET_INFO,
    _STATE_TTL_SECONDS,
    _build_state,
    _check_redirect_uri,
    _get_allowed_redirect_uris,
    _get_state_secret,
    _is_exact_allowed_redirect_uri,
    _sign_state,
    _verify_state,
    register_oauth_routes,
)

# Test configuration constants
TEST_AUTH0_DOMAIN = 'test.us.auth0.com'
TEST_CLIENT_ID = 'test-client-id'
TEST_CLIENT_SECRET = 'test-client-secret'
TEST_RESOURCE_URL = 'https://mcp.test.alpacon.io'

# Redirect targets used across the state tests
TRUSTED_REDIRECT_URI = 'https://claude.ai/cb'
EVIL_REDIRECT_URI = 'https://evil.com/cb'

# An exp far enough ahead that a forged payload is never rejected as expired
FAR_FUTURE_EXP = 9999999999

LISTED_REDIRECT_URI = 'https://claude.ai/api/mcp/auth_callback'
UNLISTED_PATH_URI = 'https://chatgpt.com/evil/path'
CONNECTOR_REDIRECT_URI = 'https://chatgpt.com/connector/oauth/abc123'

# Environment variables needed for OAuth config
OAUTH_ENV = {
    'AUTH0_DOMAIN': TEST_AUTH0_DOMAIN,
    'AUTH0_CLIENT_ID': TEST_CLIENT_ID,
    'AUTH0_CLIENT_SECRET': TEST_CLIENT_SECRET,
    'AUTH0_AUDIENCE': 'https://alpacon.io/access/',
    'ALPACON_MCP_AUTH_ENABLED': 'true',
    'ALPACON_MCP_RESOURCE_URL': TEST_RESOURCE_URL,
    # Pinned empty so a developer's exported redirect_uri settings cannot
    # invert the default-behavior assertions below.
    'ALLOWED_REDIRECT_URIS': '',
    'ALLOWED_REDIRECT_DOMAINS': '',
    'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY': '',
}

REPORT_ONLY = {'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY': 'true'}


@pytest.fixture(autouse=True)
def _set_oauth_env():
    """Ensure OAuth env vars are set for all tests."""
    with patch.dict('os.environ', OAUTH_ENV):
        yield


class MockMCPServer:
    """Stands in for FastMCP, collecting whatever register_oauth_routes registers."""

    def __init__(self):
        self.routes = []

    def custom_route(self, path, methods=None):
        def decorator(func):
            self.routes.append(Route(path, func, methods=methods))
            return func

        return decorator


@pytest.fixture
def oauth_app():
    """Create a minimal Starlette app with OAuth routes registered."""
    mock_server = MockMCPServer()
    register_oauth_routes(mock_server)
    return TestClient(
        Starlette(routes=mock_server.routes), raise_server_exceptions=False
    )


def _forge_state_under_valid_signature():
    """A state whose payload was swapped out after signing, keeping the signature."""
    signed = _sign_state({'redirect_uri': TRUSTED_REDIRECT_URI})
    _, _, signature = signed.rpartition('.')
    forged = base64.urlsafe_b64encode(
        json.dumps({'redirect_uri': EVIL_REDIRECT_URI, 'exp': FAR_FUTURE_EXP}).encode()
    ).decode()
    return f'{forged}.{signature}'


def _mock_auth0_response(status_code=200, json_data=None):
    """Create a mock httpx AsyncClient that returns the given response."""
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {'access_token': 'test-token'}
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


class TestAllowedRedirectUris:
    """Tests for the endpoint-level redirect_uri allowlist configuration."""

    def test_defaults_cover_known_remote_clients(self):
        uris = _get_allowed_redirect_uris()
        assert 'https://claude.ai/api/mcp/auth_callback' in uris
        assert 'https://claude.com/api/mcp/auth_callback' in uris
        assert 'https://chatgpt.com/connector_platform_oauth_redirect' in uris
        assert 'https://www.cursor.com/agents/mcp/oauth/callback' in uris
        assert 'https://vscode.dev/redirect/' in uris
        assert 'https://antigravity.google/oauth-callback' in uris
        assert 'https://global.consent.azure-apim.net/redirect' in uris

    def test_env_override_replaces_defaults(self):
        with patch.dict(
            'os.environ',
            {'ALLOWED_REDIRECT_URIS': 'https://a.example/cb, https://b.example/cb'},
        ):
            assert _get_allowed_redirect_uris() == (
                'https://a.example/cb',
                'https://b.example/cb',
            )

    def test_warns_when_only_legacy_domain_var_is_set(self, caplog):
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com'}
        ):
            with caplog.at_level('WARNING'):
                register_oauth_routes(MockMCPServer())

        assert 'ALLOWED_REDIRECT_URIS' in caplog.text

    def test_blank_domain_var_does_not_warn(self, caplog):
        """A whitespace-only value is unset to _get_allowed_redirect_domains."""
        with patch.dict('os.environ', {'ALLOWED_REDIRECT_DOMAINS': '  '}):
            with caplog.at_level('WARNING'):
                register_oauth_routes(MockMCPServer())

        assert 'ALLOWED_REDIRECT_URIS' not in caplog.text

    def test_domain_var_with_report_only_does_not_warn(self, caplog):
        """Report-only mode is what makes the domain list usable on its own."""
        with patch.dict(
            'os.environ',
            {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com', **REPORT_ONLY},
        ):
            with caplog.at_level('WARNING'):
                register_oauth_routes(MockMCPServer())

        assert 'ALLOWED_REDIRECT_URIS' not in caplog.text


class TestExactRedirectUriMatch:
    """Tests for endpoint-level redirect_uri matching."""

    def test_listed_uri_matches(self):
        assert _is_exact_allowed_redirect_uri(LISTED_REDIRECT_URI)
        assert _is_exact_allowed_redirect_uri(
            'https://antigravity.google/oauth-callback'
        )

    def test_other_path_on_trusted_domain_is_rejected(self):
        assert not _is_exact_allowed_redirect_uri(UNLISTED_PATH_URI)
        assert not _is_exact_allowed_redirect_uri('https://claude.ai/')

    def test_query_or_fragment_is_rejected(self):
        base = LISTED_REDIRECT_URI
        assert not _is_exact_allowed_redirect_uri(f'{base}?x=1')
        assert not _is_exact_allowed_redirect_uri(f'{base}#frag')

    def test_chatgpt_connector_id_segment_matches(self):
        assert _is_exact_allowed_redirect_uri(
            'https://chatgpt.com/connector/oauth/abc123_-XYZ'
        )

    def test_chatgpt_connector_extra_segment_is_rejected(self):
        assert not _is_exact_allowed_redirect_uri(
            'https://chatgpt.com/connector/oauth/abc/evil'
        )
        assert not _is_exact_allowed_redirect_uri(
            'https://chatgpt.com/connector/oauth/'
        )

    def test_chatgpt_connector_trailing_newline_is_rejected(self):
        """$ would match before a trailing newline; the pattern uses \\Z."""

        assert not _is_exact_allowed_redirect_uri(f'{CONNECTOR_REDIRECT_URI}\n')

    def test_env_override_is_honoured(self):
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_URIS': 'https://a.example/cb'}
        ):
            assert _is_exact_allowed_redirect_uri('https://a.example/cb')
            assert not _is_exact_allowed_redirect_uri(LISTED_REDIRECT_URI)
            # The built-in patterns are part of the built-in list, so an
            # override drops them too.
            assert not _is_exact_allowed_redirect_uri(CONNECTOR_REDIRECT_URI)

    def test_plaintext_uri_is_rejected(self):
        with patch.dict('os.environ', {'ALLOWED_REDIRECT_URIS': 'http://a.example/cb'}):
            assert not _is_exact_allowed_redirect_uri('http://a.example/cb')


class TestRedirectUriGate:
    """Tests for the redirect_uri endpoint gate."""

    def test_rejects_untracked_path_by_default(self):
        assert not _check_redirect_uri(UNLISTED_PATH_URI)

    def test_allows_listed_endpoint(self):
        assert _check_redirect_uri(LISTED_REDIRECT_URI)

    def test_every_default_endpoint_passes_the_gate(self):
        """A listed endpoint must not be blocked by the legacy host allowlist."""

        for uri in _get_allowed_redirect_uris():
            assert _check_redirect_uri(uri), uri
        assert _check_redirect_uri(CONNECTOR_REDIRECT_URI)

    def test_keeps_every_loopback_path(self):
        assert _check_redirect_uri('http://localhost:1234/callback')
        assert _check_redirect_uri('http://localhost:1234/oauth/callback')
        assert _check_redirect_uri('http://127.0.0.1:33418/')

    def test_untrusted_domain_is_rejected_in_either_mode(self):
        assert not _check_redirect_uri('https://evil.com/cb')
        with patch.dict('os.environ', REPORT_ONLY):
            assert not _check_redirect_uri('https://evil.com/cb')

    def test_report_only_covers_every_built_in_client_host(self):
        """The escape hatch is useless on a host whose endpoint it cannot reach."""

        with patch.dict('os.environ', REPORT_ONLY):
            for uri in _get_allowed_redirect_uris():
                moved = uri.rstrip('/') + '/moved'
                assert _check_redirect_uri(moved), moved

    def test_report_only_allows_untracked_path_with_a_warning(self, caplog):
        with patch.dict('os.environ', REPORT_ONLY):
            with caplog.at_level('WARNING'):
                assert _check_redirect_uri(UNLISTED_PATH_URI)
        assert 'report-only' in caplog.text

    def test_authorize_rejects_untracked_path(self, oauth_app):
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': UNLISTED_PATH_URI,
            },
            follow_redirects=False,
        )
        assert response.status_code == 400

    def test_callback_does_not_relay_to_untracked_path(self, oauth_app):
        composite = _make_composite_state(UNLISTED_PATH_URI, 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        # 200 as well as the missing header: a 500 would also have no location.
        assert response.status_code == 200
        assert 'location' not in response.headers


class TestAuthorizeObservation:
    """Tests for the observation-window log line."""

    def test_logs_redirect_uri_and_pkce_method(self, oauth_app, caplog):
        with caplog.at_level('INFO'):
            oauth_app.get(
                '/oauth/authorize',
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
                '/oauth/authorize',
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
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://evil.example/cb\nforged line',
                },
                follow_redirects=False,
            )

        assert 'cb\\nforged line' in caplog.text
        assert 'cb\nforged line' not in caplog.text


class TestStateSecret:
    """Tests for state signing key derivation."""

    def test_explicit_env_secret_wins(self):
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'a1' * 32}):
            assert _get_state_secret() == b'\xa1' * 32

    def test_rejects_non_hex_explicit_secret(self):
        # A typed passphrase is the weak key this check exists to keep out.
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'correct-horse-battery'}):
            with pytest.raises(ValueError, match='must be hex'):
                _get_state_secret()

    def test_rejects_short_explicit_secret(self):
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'a1' * 31}):
            with pytest.raises(ValueError, match='at least 32 bytes'):
                _get_state_secret()

    def test_derives_from_client_secret_when_env_unset(self):
        expected = hmac.new(
            TEST_CLIENT_SECRET.encode(), _STATE_SECRET_INFO, hashlib.sha256
        ).digest()
        assert _get_state_secret() == expected

    def test_derived_secret_is_deterministic(self):
        assert _get_state_secret() == _get_state_secret()

    def test_registration_logs_state_secret_source(self, caplog):
        with caplog.at_level('INFO'):
            register_oauth_routes(MockMCPServer())

        assert 'derived from client secret' in caplog.text


class TestStateEnvelope:
    """Tests for state signing and verification."""

    def test_round_trip_preserves_payload(self):
        signed = _sign_state({'redirect_uri': TRUSTED_REDIRECT_URI, 'state': 'xyz'})
        payload = _verify_state(signed)
        assert payload['redirect_uri'] == TRUSTED_REDIRECT_URI
        assert payload['state'] == 'xyz'

    def test_sign_adds_expiry(self):
        payload = _verify_state(_sign_state({'state': 'xyz'}))
        assert payload['exp'] <= int(time.time()) + _STATE_TTL_SECONDS

    def test_tampered_payload_is_rejected(self):
        assert _verify_state(_forge_state_under_valid_signature()) is None

    def test_unsigned_state_is_rejected(self):
        unsigned = base64.urlsafe_b64encode(
            json.dumps({'redirect_uri': EVIL_REDIRECT_URI}).encode()
        ).decode()
        assert _verify_state(unsigned) is None

    def test_wrong_signature_is_rejected(self):
        encoded, _, _ = _sign_state({'state': 'xyz'}).rpartition('.')
        assert _verify_state(f'{encoded}.bm90LWEtc2ln') is None

    def test_expired_state_is_rejected(self):
        with patch('utils.oauth.time.time', return_value=1000):
            signed = _sign_state({'state': 'xyz'})
        with patch('utils.oauth.time.time', return_value=99999999):
            assert _verify_state(signed) is None

    def test_malformed_state_is_rejected(self):
        assert _verify_state('not-a-state') is None
        assert _verify_state('') is None

    def test_non_ascii_state_is_rejected(self):
        """hmac.compare_digest raises TypeError on non-ASCII str, so compare bytes."""
        assert _verify_state('payload.서명') is None


class TestBuildState:
    """Tests for state payload assembly."""

    def test_carries_redirect_uri_and_client_state(self):
        decoded = _verify_state(_build_state(TRUSTED_REDIRECT_URI, 'xyz'))
        assert decoded['redirect_uri'] == TRUSTED_REDIRECT_URI
        assert decoded['state'] == 'xyz'

    def test_carries_extra_flow_fields(self):
        decoded = _verify_state(
            _build_state('', '', stage='mfa', original_scope='openid')
        )
        assert decoded['stage'] == 'mfa'
        assert decoded['original_scope'] == 'openid'


class TestOAuthMetadata:
    """Tests for /.well-known/oauth-authorization-server endpoint."""

    def test_metadata_returns_correct_endpoints(self, oauth_app):
        response = oauth_app.get('/.well-known/oauth-authorization-server')
        assert response.status_code == 200
        data = response.json()

        assert data['issuer'] == f'{TEST_RESOURCE_URL}/'
        assert data['authorization_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/authorize'
        assert data['token_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/token'
        assert data['registration_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/register'
        assert data['jwks_uri'] == f'https://{TEST_AUTH0_DOMAIN}/.well-known/jwks.json'
        assert 'code' in data['response_types_supported']
        assert 'S256' in data['code_challenge_methods_supported']

    def test_metadata_advertises_none_auth_method(self, oauth_app):
        """Metadata should advertise 'none' since clients don't send client_secret."""
        response = oauth_app.get('/.well-known/oauth-authorization-server')
        assert response.status_code == 200
        data = response.json()
        assert data['token_endpoint_auth_methods_supported'] == ['none']

    def test_metadata_uses_configured_resource_url(self, oauth_app):
        response = oauth_app.get('/.well-known/oauth-authorization-server')
        data = response.json()
        assert data['token_endpoint'].startswith(TEST_RESOURCE_URL)

    def test_metadata_cache_control(self, oauth_app):
        response = oauth_app.get('/.well-known/oauth-authorization-server')
        assert 'max-age=3600' in response.headers.get('cache-control', '')


class TestOAuthAuthorize:
    """Tests for /oauth/authorize endpoint."""

    def test_authorize_redirects_to_auth0(self, oauth_app):
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:52048/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert location.startswith(f'https://{TEST_AUTH0_DOMAIN}/authorize')

    def test_authorize_overrides_redirect_uri_to_server_callback(self, oauth_app):
        """redirect_uri sent to Auth0 should be the MCP server's own callback."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:52048/callback',
            },
            follow_redirects=False,
        )
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert params['redirect_uri'] == [f'{TEST_RESOURCE_URL}/oauth/callback']

    def test_authorize_stores_client_redirect_uri_in_state(self, oauth_app):
        """Client's original redirect_uri should be encoded in the state param."""
        client_uri = 'http://localhost:52048/callback'
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': client_uri,
                'state': 'original-state',
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
            '/oauth/authorize',
            params={'client_id': 'attacker-client-id', 'response_type': 'code'},
            follow_redirects=False,
        )
        location = response.headers['location']
        assert f'client_id={TEST_CLIENT_ID}' in location
        assert 'attacker-client-id' not in location

    def test_authorize_sets_default_response_type(self, oauth_app):
        response = oauth_app.get(
            '/oauth/authorize',
            params={'redirect_uri': 'http://localhost:3000/callback'},
            follow_redirects=False,
        )
        location = response.headers['location']
        assert 'response_type=code' in location

    def test_authorize_rejects_untrusted_redirect_uri(self, oauth_app):
        """Untrusted redirect_uris should be rejected to prevent open redirect."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'https://evil.com/callback',
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert data['error'] == 'invalid_request'
        assert 'allowlisted' in data['error_description']

    def test_authorize_reports_malformed_state_secret(self, oauth_app):
        """Signing is the first place a bad key raises; the message must survive."""
        with patch.dict('os.environ', {_STATE_SECRET_ENV: 'correct-horse-battery'}):
            response = oauth_app.get(
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': 'http://localhost:52048/callback',
                },
                follow_redirects=False,
            )
        assert response.status_code == 500
        assert 'must be hex' in response.json()['error']

    def test_authorize_allows_claude_ai_redirect_uri(self, oauth_app):
        """Claude web redirect_uri is one of the allowlisted callback endpoints."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': LISTED_REDIRECT_URI,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

    def test_authorize_allows_chatgpt_redirect_uri(self, oauth_app):
        """ChatGPT redirect_uri is one of the allowlisted callback endpoints."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'https://chatgpt.com/connector_platform_oauth_redirect',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

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
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://custom.example.com/callback',
                },
                follow_redirects=False,
            )
            assert response.status_code == 302

            response = oauth_app.get(
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': LISTED_REDIRECT_URI,
                },
            )
            assert response.status_code == 400

    def test_authorize_rejects_domain_override_without_uri_override(self, oauth_app):
        """ALLOWED_REDIRECT_DOMAINS alone no longer admits a host.

        Breaking change: the domain list clears the host check, but the endpoint
        allowlist still has to list the callback URI.
        """
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com'}
        ):
            response = oauth_app.get(
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://custom.example.com/callback',
                },
                follow_redirects=False,
            )
        assert response.status_code == 400

    def test_authorize_rejects_http_trusted_domain(self, oauth_app):
        """Trusted domains must use https to prevent code leakage over plaintext."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://claude.ai/api/mcp/auth_callback',
            },
        )
        assert response.status_code == 400

    def test_authorize_allows_127_0_0_1_redirect_uri(self, oauth_app):
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://127.0.0.1:8080/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

    def test_authorize_adds_offline_access_when_missing(self, oauth_app):
        """offline_access scope is added automatically for refresh token support."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
                'scope': 'openid profile',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert 'offline_access' in location

    def test_authorize_preserves_existing_offline_access(self, oauth_app):
        """offline_access scope is not duplicated when already present."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
                'scope': 'openid offline_access',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        # Should appear exactly once
        assert location.count('offline_access') == 1

    def test_authorize_adds_offline_access_when_no_scope(self, oauth_app):
        """offline_access scope is added even when no scope parameter is provided."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert 'offline_access' in location

    def test_authorize_mfa_scope_redirects_to_mfa_audience(self, oauth_app):
        """When 'mfa' pseudo-scope is present, redirects to Auth0 MFA audience."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'scope': 'openid profile email offline_access mfa',
                'redirect_uri': 'http://localhost:8080/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
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
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'scope': 'openid profile email offline_access',
                'redirect_uri': 'http://localhost:8080/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        audience = params.get('audience', [''])[0]
        assert '/mfa/' not in audience


class TestOAuthToken:
    """Tests for /oauth/token endpoint."""

    def test_token_allows_authorization_code_grant(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/oauth/token',
                data={'grant_type': 'authorization_code', 'code': 'test-code'},
            )
        assert response.status_code == 200

    def test_token_allows_refresh_token_grant(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/oauth/token',
                data={'grant_type': 'refresh_token', 'refresh_token': 'test-refresh'},
            )
        assert response.status_code == 200

    def test_token_rejects_client_credentials_grant(self, oauth_app):
        response = oauth_app.post(
            '/oauth/token',
            data={'grant_type': 'client_credentials'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'unsupported_grant_type'

    def test_token_rejects_password_grant(self, oauth_app):
        response = oauth_app.post(
            '/oauth/token',
            data={'grant_type': 'password', 'username': 'user', 'password': 'pass'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'unsupported_grant_type'

    def test_token_rejects_mismatched_client_id(self, oauth_app):
        response = oauth_app.post(
            '/oauth/token',
            data={
                'grant_type': 'authorization_code',
                'code': 'test-code',
                'client_id': 'wrong-client-id',
            },
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_client'

    def test_token_injects_configured_client_id(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/oauth/token',
                data={'grant_type': 'authorization_code', 'code': 'test-code'},
            )
        assert response.status_code == 200
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['client_id'] == TEST_CLIENT_ID

    def test_token_injects_configured_client_secret(self, oauth_app):
        """Token proxy should inject client_secret for Auth0 RWA token exchange."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/oauth/token',
                data={'grant_type': 'authorization_code', 'code': 'test-code'},
            )
        assert response.status_code == 200
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['client_secret'] == TEST_CLIENT_SECRET

    def test_token_fails_without_client_secret(self):
        """Token endpoint should return 500 when AUTH0_CLIENT_SECRET is missing."""
        env_without_secret = {
            'AUTH0_DOMAIN': TEST_AUTH0_DOMAIN,
            'AUTH0_CLIENT_ID': TEST_CLIENT_ID,
            'AUTH0_AUDIENCE': 'https://alpacon.io/access/',
            'ALPACON_MCP_AUTH_ENABLED': 'true',
            'ALPACON_MCP_RESOURCE_URL': TEST_RESOURCE_URL,
        }

        mock_server = MockMCPServer()
        with patch.dict('os.environ', env_without_secret, clear=False):
            # Unset AUTH0_CLIENT_SECRET if present
            with patch.dict('os.environ', {'AUTH0_CLIENT_SECRET': ''}, clear=False):
                register_oauth_routes(mock_server)
                app = Starlette(routes=mock_server.routes)
                client = TestClient(app, raise_server_exceptions=False)
                response = client.post(
                    '/oauth/token',
                    data={'grant_type': 'authorization_code', 'code': 'test-code'},
                )
        assert response.status_code == 500
        data = response.json()
        assert 'AUTH0_CLIENT_SECRET' in data.get('error', '')

    def test_token_overrides_redirect_uri_for_auth_code(self, oauth_app):
        """Token exchange should use server's callback URL, not client's."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/oauth/token',
                data={
                    'grant_type': 'authorization_code',
                    'code': 'test-code',
                    'redirect_uri': 'http://localhost:52048/callback',
                },
            )
        assert response.status_code == 200
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['redirect_uri'] == (
            f'{TEST_RESOURCE_URL}/oauth/callback'
        )

    def test_token_sets_redirect_uri_even_if_client_omits_it(self, oauth_app):
        """Auth0 requires redirect_uri in token exchange when used in authorize."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/oauth/token',
                data={'grant_type': 'authorization_code', 'code': 'test-code'},
            )
        assert response.status_code == 200
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['redirect_uri'] == (
            f'{TEST_RESOURCE_URL}/oauth/callback'
        )

    def test_token_rejects_invalid_json(self, oauth_app):
        response = oauth_app.post(
            '/oauth/token',
            content=b'not valid json',
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'

    def test_token_rejects_non_object_json(self, oauth_app):
        response = oauth_app.post(
            '/oauth/token',
            content=json.dumps(['not', 'an', 'object']).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'

    def test_token_rejects_non_utf8_body(self, oauth_app):
        response = oauth_app.post(
            '/oauth/token',
            content=b'\xff\xfe',
            headers={'content-type': 'application/x-www-form-urlencoded'},
        )
        assert response.status_code == 400
        data = response.json()
        assert data['error'] == 'invalid_request'
        assert 'UTF-8' in data['error_description']


class TestOAuthRegister:
    """Tests for /oauth/register endpoint (RFC 7591 Dynamic Client Registration)."""

    def test_register_returns_configured_client_id(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            content=json.dumps(
                {
                    'client_name': 'test-client',
                    'redirect_uris': ['http://localhost:3000/callback'],
                }
            ).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 201
        data = response.json()
        assert data['client_id'] == TEST_CLIENT_ID
        assert data['token_endpoint_auth_method'] == 'none'
        assert 'client_id_issued_at' not in data

    def test_register_echoes_redirect_uris(self, oauth_app):
        uris = ['http://localhost:3000/callback']
        response = oauth_app.post(
            '/oauth/register',
            content=json.dumps({'redirect_uris': uris}).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 201
        assert response.json()['redirect_uris'] == uris

    def test_register_echoes_client_name(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            content=json.dumps({'client_name': 'my-app'}).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 201
        assert response.json()['client_name'] == 'my-app'

    def test_register_no_store_cache_control(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            content=json.dumps({}).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 201
        assert 'no-store' in response.headers.get('cache-control', '')

    def test_register_rejects_non_json_content_type(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            data='client_name=test',
            headers={'content-type': 'application/x-www-form-urlencoded'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'

    def test_register_rejects_empty_body(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            content=b'',
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_client_metadata'

    def test_register_rejects_invalid_json(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            content=b'not valid json',
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_client_metadata'

    def test_register_rejects_non_object_json(self, oauth_app):
        response = oauth_app.post(
            '/oauth/register',
            content=json.dumps(['not', 'an', 'object']).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_client_metadata'


class TestOAuthFallbackRoutes:
    """Tests for fallback routes (/token, /authorize, /register)."""

    def test_token_fallback_delegates_to_canonical(self, oauth_app):
        """POST /token should behave identically to POST /oauth/token."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/token',
                data={'grant_type': 'authorization_code', 'code': 'test-code'},
            )
        assert response.status_code == 200
        data = response.json()
        assert 'access_token' in data

    def test_token_fallback_rejects_unsupported_grant(self, oauth_app):
        """POST /token should enforce the same grant_type allowlist."""
        response = oauth_app.post(
            '/token',
            data={'grant_type': 'client_credentials'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'unsupported_grant_type'

    def test_authorize_fallback_redirects_to_auth0(self, oauth_app):
        """GET /authorize should redirect to Auth0 like /oauth/authorize."""
        response = oauth_app.get(
            '/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'http://localhost:52048/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert location.startswith(f'https://{TEST_AUTH0_DOMAIN}/authorize')

    def test_register_fallback_returns_client_id(self, oauth_app):
        """POST /register should return the configured client_id."""
        response = oauth_app.post(
            '/register',
            content=json.dumps({'client_name': 'test'}).encode(),
            headers={'content-type': 'application/json'},
        )
        assert response.status_code == 201
        assert response.json()['client_id'] == TEST_CLIENT_ID


def _make_composite_state(redirect_uri='', state='', **extra):
    """Helper to create signed composite state as the authorize endpoint does."""
    return _sign_state({'redirect_uri': redirect_uri, 'state': state, **extra})


class TestOAuthCallback:
    """Tests for /oauth/callback endpoint."""

    def test_callback_redirects_to_client(self, oauth_app):
        """Callback should redirect to the client's original redirect_uri."""
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert location.startswith('http://localhost:52048/callback')
        assert 'code=auth-code' in location
        assert 'state=xyz' in location

    def test_callback_rejects_unsigned_state(self, oauth_app):
        """A state we never signed must not steer the redirect."""
        unsigned = base64.urlsafe_b64encode(
            json.dumps({'redirect_uri': TRUSTED_REDIRECT_URI, 'state': 'x'}).encode()
        ).decode()
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': unsigned},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'
        assert 'location' not in response.headers

    def test_callback_rejects_tampered_state(self, oauth_app):
        """Swapping the payload under a valid signature must be rejected."""
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': _forge_state_under_valid_signature()},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert 'location' not in response.headers

    def test_callback_rejects_expired_state(self, oauth_app):
        """A state past its expiry must be rejected."""
        with patch('utils.oauth.time.time', return_value=1000):
            expired = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': expired},
            follow_redirects=False,
        )
        assert response.status_code == 400

    def test_callback_reports_missing_config_instead_of_crashing(self, oauth_app):
        """Missing client secret: same JSON 500 as other handlers, not a stack trace."""
        with patch.dict('os.environ', {'AUTH0_CLIENT_SECRET': ''}):
            response = oauth_app.get(
                '/oauth/callback',
                params={'code': 'auth-code', 'state': 'aGVsbG8.c2ln'},
            )
        assert response.status_code == 500
        assert 'AUTH0_CLIENT_SECRET' in response.json()['error']

    def test_callback_returns_json_without_redirect_uri(self, oauth_app):
        """Without a client redirect_uri in state, return JSON as fallback."""
        composite = _make_composite_state('', 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
        )
        assert response.status_code == 200
        data = response.json()
        assert data['code'] == 'auth-code'
        assert data['state'] == 'xyz'

    def test_callback_missing_code(self, oauth_app):
        response = oauth_app.get('/oauth/callback', params={'state': 'xyz'})
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'

    def test_callback_error_redirects_to_client(self, oauth_app):
        """Auth0 errors should be forwarded to the client's redirect_uri."""
        composite = _make_composite_state('http://localhost:52048/callback', 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={
                'error': 'access_denied',
                'error_description': 'User denied',
                'state': composite,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert 'error=access_denied' in location
        assert 'state=xyz' in location

    def test_callback_error_returns_json_without_redirect_uri(self, oauth_app):
        """Auth0 errors without client redirect_uri fall back to JSON."""
        response = oauth_app.get(
            '/oauth/callback',
            params={'error': 'access_denied', 'error_description': 'User denied'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'access_denied'

    def test_callback_rejects_opaque_state(self, oauth_app):
        """A state that is not one of ours is rejected, not echoed back."""
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': 'opaque-state-value'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'

    def test_callback_does_not_redirect_to_untrusted_uri(self, oauth_app):
        """Callback must not redirect to an untrusted redirect_uri from state."""
        composite = _make_composite_state(EVIL_REDIRECT_URI, 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
        )
        # Should fall back to JSON instead of redirecting to evil.com
        assert response.status_code == 200
        assert 'location' not in response.headers
        data = response.json()
        assert data['code'] == 'auth-code'

    def test_callback_redirects_to_allowlisted_endpoint(self, oauth_app):
        """Callback relays the code to an allowlisted endpoint like claude.ai."""
        composite = _make_composite_state(LISTED_REDIRECT_URI, 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert location.startswith(LISTED_REDIRECT_URI)
        assert 'code=auth-code' in location

    def test_callback_mfa_stage_exchanges_code_and_redirects_to_stage2(self, oauth_app):
        """MFA stage callback should exchange MFA code and redirect to regular audience."""
        composite = _make_composite_state(
            redirect_uri='http://localhost:8080/callback',
            state='orig-state',
            stage='mfa',
            original_scope='openid profile email offline_access',
        )

        mock_client = _mock_auth0_response(status_code=200)

        with patch('httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.get(
                '/oauth/callback',
                params={'code': 'mfa-auth-code', 'state': composite},
                follow_redirects=False,
            )

        assert response.status_code == 302
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
        state_data = _verify_state(state)
        assert state_data.get('stage') == 'regular'
        assert state_data.get('redirect_uri') == 'http://localhost:8080/callback'
        assert state_data.get('state') == 'orig-state'

        # MFA code should have been exchanged
        mock_client.post.assert_called_once()
