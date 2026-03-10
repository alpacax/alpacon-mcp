"""
Unit tests for OAuth proxy endpoints.

Tests the OAuth metadata, authorize, token, and callback endpoints
including security constraints (grant_type allowlist, client_id enforcement,
error handling).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

# Test configuration constants
TEST_AUTH0_DOMAIN = 'test.us.auth0.com'
TEST_CLIENT_ID = 'test-client-id'
TEST_RESOURCE_URL = 'https://mcp.test.alpacon.io'

# Environment variables needed for OAuth config
OAUTH_ENV = {
    'AUTH0_DOMAIN': TEST_AUTH0_DOMAIN,
    'AUTH0_CLIENT_ID': TEST_CLIENT_ID,
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

        assert data['issuer'] == f'https://{TEST_AUTH0_DOMAIN}/'
        assert data['authorization_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/authorize'
        assert data['token_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/token'
        assert data['jwks_uri'] == f'https://{TEST_AUTH0_DOMAIN}/.well-known/jwks.json'
        assert 'code' in data['response_types_supported']
        assert 'S256' in data['code_challenge_methods_supported']

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
                'redirect_uri': 'https://example.com/callback',
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers['location']
        assert location.startswith(f'https://{TEST_AUTH0_DOMAIN}/authorize')

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
            params={'redirect_uri': 'https://example.com/callback'},
            follow_redirects=False,
        )
        location = response.headers['location']
        assert 'response_type=code' in location


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


class TestOAuthCallback:
    """Tests for /oauth/callback endpoint."""

    def test_callback_returns_code(self, oauth_app):
        response = oauth_app.get(
            '/oauth/callback', params={'code': 'auth-code', 'state': 'xyz'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['code'] == 'auth-code'
        assert data['state'] == 'xyz'

    def test_callback_missing_code(self, oauth_app):
        response = oauth_app.get('/oauth/callback', params={'state': 'xyz'})
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_request'

    def test_callback_error_from_auth0(self, oauth_app):
        response = oauth_app.get(
            '/oauth/callback',
            params={'error': 'access_denied', 'error_description': 'User denied'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'access_denied'

    def test_callback_does_not_redirect(self, oauth_app):
        """Callback returns JSON, not a redirect -- prevents open redirect."""
        response = oauth_app.get(
            '/oauth/callback',
            params={
                'code': 'auth-code',
                'redirect_uri': 'https://evil.com',
            },
        )
        assert response.status_code == 200
        assert 'location' not in response.headers
