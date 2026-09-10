"""Tests for the fallback routes and CORS preflight."""

import json
import logging
from http import HTTPStatus
from unittest.mock import patch

import pytest

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    PKCE_PARAMS,
    TEST_AUTH0_DOMAIN,
    TEST_CLIENT_ID,
    _mock_auth0_response,
)
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CORS_PREFLIGHT_HEADERS,
    _ERROR_INVALID_REDIRECT_URI,
    _ERROR_UNSUPPORTED_GRANT_TYPE,
    _GRANT_AUTHORIZATION_CODE,
    _JSON_CONTENT_TYPE,
    _REGISTER_PATH,
    _TOKEN_PATH,
)
from utils.oauth._sealing import _seal_code


class TestOAuthFallbackRoutes:
    """Tests for fallback routes (/token, /authorize, /register)."""

    def test_token_fallback_delegates_to_canonical(self, oauth_app):
        """POST /token should behave identically to POST /oauth/token."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                '/token',
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
            '/token',
            data={'grant_type': 'client_credentials'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_UNSUPPORTED_GRANT_TYPE

    def test_authorize_fallback_redirects_to_auth0(self, oauth_app):
        """GET /authorize should redirect to Auth0 like /oauth/authorize."""
        response = oauth_app.get(
            '/authorize',
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

    def test_register_fallback_returns_client_id(self, oauth_app):
        """POST /register should return the configured client_id."""
        response = oauth_app.post(
            '/register',
            content=json.dumps({'client_name': 'test'}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()['client_id'] == TEST_CLIENT_ID

    def test_register_fallback_rejects_an_unlisted_redirect_uri(self, oauth_app):
        """The fallback delegates, so the check must not be bypassable through it."""
        response = oauth_app.post(
            '/register',
            content=json.dumps({'redirect_uris': [EVIL_REDIRECT_URI]}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REDIRECT_URI


class TestOAuthCors:
    """CORS on the endpoints a browser-based client posts to."""

    @pytest.mark.parametrize('path', [_REGISTER_PATH, _TOKEN_PATH])
    def test_preflight_is_answered(self, oauth_app, path):
        response = oauth_app.options(path)
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.headers['access-control-allow-origin'] == '*'
        assert 'POST' in response.headers['access-control-allow-methods']
        assert 'content-type' in response.headers['access-control-allow-headers']

    @pytest.mark.parametrize('path', ['/register', '/token'])
    def test_fallback_preflight_is_answered(self, oauth_app, path, caplog):
        """A client that never read the metadata preflights the fallback path.

        The log there flags a client that lost its metadata; a preflight is not
        that, so it must not appear in the log.
        """
        with caplog.at_level(logging.INFO, logger='alpacon_mcp.oauth'):
            response = oauth_app.options(path)
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.headers['access-control-allow-origin'] == '*'
        assert 'fallback hit' not in caplog.text

    def test_preflight_grants_no_credentials(self):
        """A wildcard origin plus credentials would let any page use the session."""
        assert 'Access-Control-Allow-Credentials' not in _CORS_PREFLIGHT_HEADERS

    def test_register_response_is_readable_cross_origin(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'client_name': 'my-app'}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.headers['access-control-allow-origin'] == '*'

    def test_token_response_is_readable_cross_origin(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': _seal_code('test-code', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.OK
        assert response.headers['access-control-allow-origin'] == '*'

    def test_rejected_register_is_readable_cross_origin(self, oauth_app):
        """The client can only act on the error code if it can read the body."""
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': [EVIL_REDIRECT_URI]}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.headers['access-control-allow-origin'] == '*'

    def test_navigation_endpoints_stay_closed(self, oauth_app):
        """CORS never governs a top-level navigation, so authorize must not open."""
        response = oauth_app.get(_AUTHORIZE_PATH)
        assert 'access-control-allow-origin' not in response.headers
