"""
Unit tests for OAuth proxy endpoints.

Tests the OAuth metadata, authorize, token, and callback endpoints
including security constraints (grant_type allowlist, client_id enforcement,
error handling).
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

# Test configuration constants
TEST_AUTH0_DOMAIN = 'test.us.auth0.com'
TEST_CLIENT_ID = 'test-client-id'
TEST_CLIENT_SECRET = 'test-client-secret'
TEST_RESOURCE_URL = 'https://mcp.test.alpacon.io'

# Environment variables needed for OAuth config
OAUTH_ENV = {
    'AUTH0_DOMAIN': TEST_AUTH0_DOMAIN,
    'AUTH0_CLIENT_ID': TEST_CLIENT_ID,
    'AUTH0_CLIENT_SECRET': TEST_CLIENT_SECRET,
    'AUTH0_AUDIENCE': 'https://alpacon.io/access/',
    'ALPACON_MCP_AUTH_ENABLED': 'true',
    'ALPACON_MCP_RESOURCE_URL': TEST_RESOURCE_URL,
}


@pytest.fixture(autouse=True)
def _set_oauth_env():
    """Ensure OAuth env vars are set for all tests."""
    with patch.dict('os.environ', OAUTH_ENV):
        yield


@pytest.fixture
def oauth_app():
    """Create a minimal Starlette app with OAuth routes registered."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    routes = []

    class MockMCPServer:
        def custom_route(self, path, methods=None):
            def decorator(func):
                routes.append(Route(path, func, methods=methods))
                return func

            return decorator

    mock_server = MockMCPServer()

    from utils.oauth import register_oauth_routes

    register_oauth_routes(mock_server)

    app = Starlette(routes=routes)
    return TestClient(app, raise_server_exceptions=False)


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
        from urllib.parse import parse_qs, urlparse

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
        from urllib.parse import parse_qs, urlparse

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
        state_data = json.loads(base64.urlsafe_b64decode(composite_state))
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
        assert 'trusted' in data['error_description']

    def test_authorize_allows_claude_ai_redirect_uri(self, oauth_app):
        """Claude web redirect_uri should be allowed as a trusted domain."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

    def test_authorize_allows_chatgpt_redirect_uri(self, oauth_app):
        """ChatGPT redirect_uri should be allowed as a trusted domain."""
        response = oauth_app.get(
            '/oauth/authorize',
            params={
                'response_type': 'code',
                'redirect_uri': 'https://chatgpt.com/connector_platform_oauth_redirect',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

    def test_authorize_allows_custom_redirect_domains(self, oauth_app):
        """Custom ALLOWED_REDIRECT_DOMAINS env var should override defaults."""
        with patch.dict(
            'os.environ', {'ALLOWED_REDIRECT_DOMAINS': 'custom.example.com'}
        ):
            # Custom domain should be allowed
            response = oauth_app.get(
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://custom.example.com/callback',
                },
                follow_redirects=False,
            )
            assert response.status_code == 302

            # Default domains should no longer be allowed when overridden
            response = oauth_app.get(
                '/oauth/authorize',
                params={
                    'response_type': 'code',
                    'redirect_uri': 'https://claude.ai/api/mcp/auth_callback',
                },
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

    def test_authorize_converts_mfa_scope_to_acr_values(self, oauth_app):
        """When 'mfa' pseudo-scope is present, it is converted to acr_values."""
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
        # acr_values should be added to force MFA in Auth0
        assert 'acr_values' in location
        assert 'schemas.openid.net' in location
        # 'mfa' pseudo-scope should be removed from the scope parameter
        # Parse the scope from the redirect URL
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        scope_value = params.get('scope', [''])[0]
        assert 'mfa' not in scope_value.split()
        assert 'openid' in scope_value

    def test_authorize_without_mfa_scope_no_acr_values(self, oauth_app):
        """When 'mfa' is not in scope, no acr_values are added."""
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
        assert 'acr_values' not in location


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
        from starlette.applications import Starlette
        from starlette.routing import Route

        routes = []

        class MockMCPServer:
            def custom_route(self, path, methods=None):
                def decorator(func):
                    routes.append(Route(path, func, methods=methods))
                    return func

                return decorator

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
                from utils.oauth import register_oauth_routes

                register_oauth_routes(mock_server)
                app = Starlette(routes=routes)
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


def _make_composite_state(redirect_uri='', state=''):
    """Helper to create composite state as the authorize endpoint does."""
    state_data = json.dumps({'redirect_uri': redirect_uri, 'state': state})
    return base64.urlsafe_b64encode(state_data.encode()).decode()


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

    def test_callback_handles_invalid_state_gracefully(self, oauth_app):
        """Invalid composite state should not crash — echoes raw state back."""
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': 'opaque-state-value'},
        )
        assert response.status_code == 200
        data = response.json()
        assert data['code'] == 'auth-code'
        assert data['state'] == 'opaque-state-value'

    def test_callback_does_not_redirect_to_untrusted_uri(self, oauth_app):
        """Callback must not redirect to an untrusted redirect_uri from state."""
        composite = _make_composite_state('https://evil.com/cb', 'xyz')
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
        )
        # Should fall back to JSON instead of redirecting to evil.com
        assert response.status_code == 200
        assert 'location' not in response.headers
        data = response.json()
        assert data['code'] == 'auth-code'

    def test_callback_redirects_to_trusted_domain(self, oauth_app):
        """Callback should redirect to trusted domains like claude.ai."""
        composite = _make_composite_state(
            'https://claude.ai/api/mcp/auth_callback', 'xyz'
        )
        response = oauth_app.get(
            '/oauth/callback',
            params={'code': 'auth-code', 'state': composite},
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert location.startswith('https://claude.ai/api/mcp/auth_callback')
        assert 'code=auth-code' in location
