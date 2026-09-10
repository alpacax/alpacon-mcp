"""Tests for dynamic client registration."""

import json
from http import HTTPStatus
from unittest.mock import patch

from tests.oauth._support import (
    EVIL_REDIRECT_URI,
    LISTED_REDIRECT_URI,
    REPORT_ONLY,
    TEST_CLIENT_ID,
    UNLISTED_PATH_URI,
)
from utils.oauth._http import (
    _ERROR_INVALID_CLIENT_METADATA,
    _ERROR_INVALID_REDIRECT_URI,
    _ERROR_INVALID_REQUEST,
    _FORM_CONTENT_TYPE,
    _JSON_CONTENT_TYPE,
    _REGISTER_PATH,
)
from utils.oauth._redirect_uris import _MAX_REGISTERED_REDIRECT_URIS


class TestOAuthRegister:
    """Tests for /oauth/register endpoint (RFC 7591 Dynamic Client Registration)."""

    def test_register_returns_configured_client_id(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps(
                {
                    'client_name': 'test-client',
                    'redirect_uris': ['http://localhost:3000/callback'],
                }
            ).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        data = response.json()
        assert data['client_id'] == TEST_CLIENT_ID
        assert data['token_endpoint_auth_method'] == 'none'
        assert 'client_id_issued_at' not in data

    def test_register_echoes_redirect_uris(self, oauth_app):
        uris = ['http://localhost:3000/callback']
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': uris}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()['redirect_uris'] == uris

    def test_register_echoes_client_name(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'client_name': 'my-app'}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()['client_name'] == 'my-app'
        assert 'redirect_uris' not in response.json()

    def test_register_no_store_cache_control(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert 'no-store' in response.headers.get('cache-control', '')

    def test_register_refuses_an_oversized_body(self, oauth_app):
        """Registration takes no auth either, and the cap is shared with /token."""
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': ['https://claude.ai/' + 'a' * 20000]}),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_non_json_content_type(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            data='client_name=test',
            headers={'content-type': _FORM_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    def test_register_rejects_empty_body(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=b'',
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_invalid_json(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=b'not valid json',
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_non_object_json(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps(['not', 'an', 'object']).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_non_list_redirect_uris(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': LISTED_REDIRECT_URI}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_empty_redirect_uris(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': []}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_non_string_redirect_uri_entry(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': [LISTED_REDIRECT_URI, 42]}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_too_many_redirect_uris(self, oauth_app):
        """One unauthenticated body must not buy a check, or a warning, per entry."""
        uris = [LISTED_REDIRECT_URI] * (_MAX_REGISTERED_REDIRECT_URIS + 1)
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': uris}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_accepts_redirect_uris_at_the_cap(self, oauth_app):
        uris = [LISTED_REDIRECT_URI] * _MAX_REGISTERED_REDIRECT_URIS
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': uris}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED

    def test_register_rejects_null_redirect_uris(self, oauth_app):
        """A client that will use the code flow has to name where the code goes."""
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': None}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_CLIENT_METADATA

    def test_register_rejects_unlisted_redirect_uri(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': [EVIL_REDIRECT_URI]}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REDIRECT_URI

    def test_register_rejects_a_list_with_one_unlisted_uri(self, oauth_app):
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps(
                {'redirect_uris': [LISTED_REDIRECT_URI, EVIL_REDIRECT_URI]}
            ).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REDIRECT_URI

    def test_register_accepts_a_listed_redirect_uri(self, oauth_app):
        uris = [LISTED_REDIRECT_URI]
        response = oauth_app.post(
            _REGISTER_PATH,
            content=json.dumps({'redirect_uris': uris}).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()['redirect_uris'] == uris

    def test_register_accepts_a_domain_match_in_report_only(self, oauth_app):
        with patch.dict('os.environ', REPORT_ONLY):
            response = oauth_app.post(
                _REGISTER_PATH,
                content=json.dumps({'redirect_uris': [UNLISTED_PATH_URI]}).encode(),
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.CREATED
