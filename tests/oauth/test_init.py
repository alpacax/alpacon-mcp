"""The route table and the un-prefixed fallback routes."""

import json
from http import HTTPStatus
from unittest.mock import patch

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    PKCE_PARAMS,
    TEST_AUTH0_ALPACON_DOMAIN,
    _mock_auth0_response,
)
from utils.oauth._http import (
    _FALLBACK_AUTHORIZE_PATH,
    _FALLBACK_REGISTER_PATH,
    _FALLBACK_TOKEN_PATH,
    _GRANT_AUTHORIZATION_CODE,
    _JSON_CONTENT_TYPE,
    _RESPONSE_TYPE_CODE,
)
from utils.oauth._sealing import _registered_device_id, _seal_code


class TestOAuthFallbackRoutes:
    """Tests for fallback routes (/token, /authorize, /register)."""

    def test_token_fallback_delegates_to_canonical(self, oauth_app):
        """POST /token should behave identically to POST /oauth/token."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _FALLBACK_TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': _seal_code('test-code', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert 'access_token' in data

    def test_token_fallback_rejects_unsupported_grant(self, oauth_app):
        """POST /token should enforce the same grant_type allowlist."""
        response = oauth_app.post(
            _FALLBACK_TOKEN_PATH,
            data={'grant_type': 'client_credentials'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'unsupported_grant_type'

    def test_authorize_fallback_redirects_to_auth0(self, oauth_app):
        """GET /authorize should redirect to Auth0 like /oauth/authorize."""
        response = oauth_app.get(
            _FALLBACK_AUTHORIZE_PATH,
            params={
                'response_type': _RESPONSE_TYPE_CODE,
                'redirect_uri': 'http://localhost:52048/callback',
                **PKCE_PARAMS,
            },
            follow_redirects=False,
        )
        assert response.status_code == HTTPStatus.FOUND
        location = response.headers['location']
        assert location.startswith(f'https://{TEST_AUTH0_ALPACON_DOMAIN}/authorize')

    def test_register_fallback_returns_client_id(self, oauth_app):
        """POST /register returns an installation client_id."""
        response = oauth_app.post(
            _FALLBACK_REGISTER_PATH,
            content=json.dumps({'client_name': 'test'}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert _registered_device_id(response.json()['client_id']) is not None

    def test_register_fallback_rejects_an_unlisted_redirect_uri(self, oauth_app):
        """The fallback delegates, so the check must not be bypassable through it."""
        response = oauth_app.post(
            _FALLBACK_REGISTER_PATH,
            content=json.dumps({'redirect_uris': [EVIL_REDIRECT_URI]}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_redirect_uri'
