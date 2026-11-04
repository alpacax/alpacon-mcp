"""The authorization server metadata endpoint."""

from http import HTTPStatus
from unittest.mock import patch

from tests.oauth._support import TEST_AUTH0_ALPACON_DOMAIN, TEST_RESOURCE_URL
from utils.oauth._http import (
    _METADATA_PATH,
)


class TestOAuthMetadata:
    def test_metadata_returns_correct_endpoints(self, oauth_app):
        response = oauth_app.get(_METADATA_PATH)
        assert response.status_code == HTTPStatus.OK
        data = response.json()

        assert data['issuer'] == f'{TEST_RESOURCE_URL}/'
        assert data['authorization_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/authorize'
        assert data['token_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/token'
        assert data['registration_endpoint'] == f'{TEST_RESOURCE_URL}/oauth/register'
        assert (
            data['jwks_uri']
            == f'https://{TEST_AUTH0_ALPACON_DOMAIN}/.well-known/jwks.json'
        )
        assert 'code' in data['response_types_supported']
        assert 'S256' in data['code_challenge_methods_supported']

    def test_metadata_advertises_none_auth_method(self, oauth_app):
        """Metadata should advertise 'none' since clients don't send client_secret."""
        response = oauth_app.get(_METADATA_PATH)
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data['token_endpoint_auth_methods_supported'] == ['none']

    def test_metadata_uses_configured_resource_url(self, oauth_app):
        response = oauth_app.get(_METADATA_PATH)
        data = response.json()
        assert data['token_endpoint'].startswith(TEST_RESOURCE_URL)

    def test_metadata_cache_control(self, oauth_app):
        response = oauth_app.get(_METADATA_PATH)
        assert 'max-age=3600' in response.headers.get('cache-control', '')

    def test_metadata_allows_any_cors_origin(self, oauth_app):
        """Public per RFC 8414."""
        response = oauth_app.get(_METADATA_PATH)
        assert response.headers['access-control-allow-origin'] == '*'

    def test_metadata_error_is_readable_cross_origin(self, oauth_app):
        """Without the header a misconfigured deployment reads as a CORS failure."""
        with patch.dict('os.environ', {'AUTH0_ALPACON_DOMAIN': ''}):
            response = oauth_app.get(_METADATA_PATH)
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.headers['access-control-allow-origin'] == '*'
