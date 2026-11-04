"""Behavior shared by the handlers: CORS and what reaches the log."""

import json
import logging
from http import HTTPStatus
from unittest.mock import patch

import pytest

from tests.oauth._support import (
    DEVICE_ID,
    EVIL_REDIRECT_URI,
    _mock_auth0_response,
)
from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _CALLBACK_PATH,
    _CORS_PREFLIGHT_HEADERS,
    _FALLBACK_REGISTER_PATH,
    _FALLBACK_TOKEN_PATH,
    _GRANT_AUTHORIZATION_CODE,
    _GRANT_REFRESH_TOKEN,
    _JSON_CONTENT_TYPE,
    _REGISTER_PATH,
    _TOKEN_PATH,
)
from utils.oauth._sealing import _seal_code, _seal_refresh_token


class TestOAuthCors:
    """CORS on the endpoints a browser-based client posts to."""

    @pytest.mark.parametrize('path', [_REGISTER_PATH, _TOKEN_PATH])
    def test_preflight_is_answered(self, oauth_app, path):
        response = oauth_app.options(path)
        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.headers['access-control-allow-origin'] == '*'
        assert 'POST' in response.headers['access-control-allow-methods']
        assert 'content-type' in response.headers['access-control-allow-headers']

    @pytest.mark.parametrize('path', [_FALLBACK_REGISTER_PATH, _FALLBACK_TOKEN_PATH])
    def test_fallback_preflight_is_answered(self, oauth_app, path, caplog):
        """A client that never read the metadata preflights the fallback path.
        The log there flags a client that lost its metadata; a preflight is not that.
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


# A line break and what a real record looks like after it: unescaped, a log
# reader starts a second record at the timestamp.
FORGED_LINE = '\r\n2026-09-30 01:02:03 - alpacon_mcp.oauth - INFO - forged'


def _assert_single_line_records(caplog):
    assert caplog.records
    for record in caplog.records:
        message = record.getMessage()
        assert '\n' not in message, message
        assert '\r' not in message, message


class TestClientValuesInLogs:
    """A value the client sends reaches the log escaped, one record per line."""

    def test_callback_error_values_are_escaped(self, oauth_app, caplog):
        with caplog.at_level(logging.DEBUG, logger='alpacon_mcp'):
            oauth_app.get(
                _CALLBACK_PATH,
                params={
                    'error': f'access_denied{FORGED_LINE}',
                    'error_description': f'denied{FORGED_LINE}',
                },
                follow_redirects=False,
            )

        _assert_single_line_records(caplog)
        assert 'access_denied\\r\\n2026-09-30' in caplog.text

    def test_callback_error_description_is_bounded(self, oauth_app, caplog):
        with caplog.at_level(logging.WARNING, logger='alpacon_mcp'):
            oauth_app.get(
                _CALLBACK_PATH,
                params={'error': 'access_denied', 'error_description': 'x' * 5000},
                follow_redirects=False,
            )

        assert 'x' * 600 not in caplog.text

    def test_mismatched_client_id_is_escaped(self, oauth_app, caplog):
        with caplog.at_level(logging.DEBUG, logger='alpacon_mcp'):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('test-refresh', DEVICE_ID),
                    'client_id': f'other-client{FORGED_LINE}',
                },
            )

        assert response.json()['error'] == 'invalid_client'
        _assert_single_line_records(caplog)
        assert 'other-client\\r\\n2026-09-30' in caplog.text
