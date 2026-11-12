"""The token endpoint: grant handling and the proxied Auth0 exchange."""

import json
import sys
from http import HTTPStatus
from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from tests.oauth._support import (
    DEVICE_ID,
    OTHER_DEVICE_ID,
    TEST_AUTH0_ALPACON_DOMAIN,
    TEST_CLIENT_ID,
    TEST_CLIENT_SECRET,
    TEST_RESOURCE_URL,
    MockMCPServer,
    _mock_auth0_response,
)
from utils.oauth import register_oauth_routes
from utils.oauth._http import (
    _CALLBACK_PATH,
    _ERROR_INVALID_GRANT,
    _ERROR_INVALID_REQUEST,
    _FORM_CONTENT_TYPE,
    _GRANT_AUTHORIZATION_CODE,
    _GRANT_REFRESH_TOKEN,
    _JSON_CONTENT_TYPE,
    _MAX_REQUEST_BODY_BYTES,
    _TOKEN_PATH,
)
from utils.oauth._sealing import (
    _SEAL_KIND_REFRESH,
    _mint_client_id,
    _open_seal,
    _registered_device_id,
    _seal_code,
    _seal_refresh_token,
)


class TestOAuthToken:
    def test_token_allows_authorization_code_grant(self, oauth_app):
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

    def test_token_allows_refresh_token_grant(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('test-refresh', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.OK

    def test_token_requires_a_grant_type(self, oauth_app):
        """The seal is keyed off grant_type, so an absent one cannot reach Auth0."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={'code': _seal_code('test-code', DEVICE_ID)},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        mock_client.post.assert_not_called()

    def test_token_rejects_a_non_string_grant_type(self, oauth_app):
        """An unhashable one would raise on the allow-list test instead of 400."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=json.dumps({'grant_type': [_GRANT_REFRESH_TOKEN]}).encode(),
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'
        mock_client.post.assert_not_called()

    def test_token_refuses_an_oversized_body(self, oauth_app):
        """The route takes no auth, so one caller cannot pick the allocation."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=b'grant_type=refresh_token&refresh_token=' + b'a' * 20000,
                headers={'content-type': _FORM_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.json()['error'] == 'invalid_request'
        mock_client.post.assert_not_called()

    def test_token_refuses_an_oversized_chunked_body(self, oauth_app):
        """A chunked request declares no length, so the cap has to count bytes."""

        def chunks():
            for _ in range(4):
                yield b'a' * 8192

        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=chunks(),
                headers={'content-type': _FORM_CONTENT_TYPE},
            )
        assert 'content-length' not in response.request.headers
        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        mock_client.post.assert_not_called()

    def test_token_rejects_client_credentials_grant(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            data={'grant_type': 'client_credentials'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'unsupported_grant_type'

    def test_token_rejects_password_grant(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            data={'grant_type': 'password', 'username': 'user', 'password': 'pass'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'unsupported_grant_type'

    def test_token_rejects_mismatched_client_id(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            data={
                'grant_type': _GRANT_AUTHORIZATION_CODE,
                'code': _seal_code('test-code', DEVICE_ID),
                'client_id': 'wrong-client-id',
            },
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_client'

    def test_token_injects_configured_client_id(self, oauth_app):
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
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['client_id'] == TEST_CLIENT_ID

    def test_token_injects_configured_client_secret(self, oauth_app):
        """Token proxy should inject client_secret for Auth0 RWA token exchange."""
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
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['client_secret'] == TEST_CLIENT_SECRET

    def test_token_refresh_unseals_the_device_id(self, oauth_app):
        """A sealed refresh token reaches Auth0 bare, with its device id beside it."""
        mock_client = _mock_auth0_response(
            json_data={'access_token': 'new-access', 'refresh_token': 'v1.rotated'}
        )
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.OK
        sent = mock_client.post.call_args.kwargs['data']
        assert sent['refresh_token'] == 'v1.refresh'
        assert sent['device_id'] == DEVICE_ID

    def test_token_refresh_reseals_the_rotated_token(self, oauth_app):
        """Auth0 rotates refresh tokens, so the new one leaves under the same id."""
        mock_client = _mock_auth0_response(
            json_data={'access_token': 'new-access', 'refresh_token': 'v1.rotated'}
        )
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                },
            )
        body = response.json()
        assert body['access_token'] == 'new-access'
        assert _open_seal(_SEAL_KIND_REFRESH, body['refresh_token']) == (
            'v1.rotated',
            DEVICE_ID,
            '',
        )

    def test_token_refresh_ignores_a_client_device_id_under_a_seal(self, oauth_app):
        """The sealed id is the grant's; a body param cannot point at another record."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                    'device_id': OTHER_DEVICE_ID,
                },
            )
        assert mock_client.post.call_args.kwargs['data']['device_id'] == DEVICE_ID

    def test_token_refresh_strips_a_client_device_scope(self, oauth_app):
        """The action reads the scope ahead of the field, so it has to go too."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                    'scope': f'openid offline_access device:{OTHER_DEVICE_ID}',
                },
            )
        sent = mock_client.post.call_args.kwargs['data']
        assert sent['scope'] == 'openid offline_access'
        assert sent['device_id'] == DEVICE_ID

    def test_token_refresh_drops_a_non_string_device_scope(self, oauth_app):
        """httpx encodes a list scope as one the action reads like any other."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            oauth_app.post(
                _TOKEN_PATH,
                content=json.dumps(
                    {
                        'grant_type': _GRANT_REFRESH_TOKEN,
                        'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                        'scope': [f'device:{OTHER_DEVICE_ID}'],
                    }
                ).encode(),
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        sent = mock_client.post.call_args.kwargs['data']
        assert 'scope' not in sent
        assert sent['device_id'] == DEVICE_ID

    def test_token_refresh_drops_a_scope_the_strip_empties(self, oauth_app):
        """An omitted scope is the grant's own; RFC 6749 defines no empty one."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                    'scope': f'device:{OTHER_DEVICE_ID}',
                },
            )
        sent = mock_client.post.call_args.kwargs['data']
        assert 'scope' not in sent
        assert sent['device_id'] == DEVICE_ID

    def test_token_refresh_rejects_a_tampered_seal(self, oauth_app):
        """A value under our prefix that does not verify never reaches Auth0."""
        sealed = _seal_refresh_token('v1.refresh', DEVICE_ID)
        prefix, encoded, signature = sealed.split('.')
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': f'{prefix}.{encoded}.{signature[:-4]}AAAA',
                },
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_refresh_rejects_a_sealed_code(self, oauth_app):
        """A code cannot be replayed as a refresh token."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_code('auth-code', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_refresh_rejects_a_bare_refresh_token(self, oauth_app, caplog):
        """A refresh token issued before sealing would refresh under a shared key, so it
        is refused. Every pre-sealing session hits this once at rollout; not a warning.
        """
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            with caplog.at_level('INFO'):
                response = oauth_app.post(
                    _TOKEN_PATH,
                    data={
                        'grant_type': _GRANT_REFRESH_TOKEN,
                        'refresh_token': 'v1.legacy',
                    },
                )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()
        [record] = [r for r in caplog.records if 'unsealed refresh token' in r.message]
        assert record.levelname == 'INFO'

    def test_token_refresh_warns_on_a_failed_seal(self, oauth_app, caplog):
        """Under our prefix but not verifying is tampering or corruption."""
        sealed = _seal_refresh_token('v1.refresh', DEVICE_ID)
        prefix, encoded, signature = sealed.split('.')
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            with caplog.at_level('INFO'):
                response = oauth_app.post(
                    _TOKEN_PATH,
                    data={
                        'grant_type': _GRANT_REFRESH_TOKEN,
                        'refresh_token': f'{prefix}.{encoded}.{signature[:-4]}AAAA',
                    },
                )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        [record] = [r for r in caplog.records if 'seal verification' in r.message]
        assert record.levelname == 'WARNING'

    def test_token_refresh_rejects_a_non_string_refresh_token(self, oauth_app):
        """A JSON body can type the field as anything; it must not reach a
        string method and come back as a 500."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=json.dumps(
                    {'grant_type': _GRANT_REFRESH_TOKEN, 'refresh_token': 123}
                ).encode(),
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_refresh_rejects_a_missing_refresh_token(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH, data={'grant_type': _GRANT_REFRESH_TOKEN}
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_auth_code_unseals_the_code(self, oauth_app):
        """Auth0 sees the code it issued, and no client device id on this grant.
        The scope sent to /authorize already carried the id, so no body field is needed.
        """
        mock_client = _mock_auth0_response(
            json_data={'access_token': 'jwt', 'refresh_token': 'v1.first'}
        )
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': _seal_code('auth-code', DEVICE_ID),
                    'device_id': OTHER_DEVICE_ID,
                    'scope': f'openid device:{OTHER_DEVICE_ID}',
                },
            )
        assert response.status_code == HTTPStatus.OK
        sent = mock_client.post.call_args.kwargs['data']
        assert sent['code'] == 'auth-code'
        assert 'device_id' not in sent
        assert sent['scope'] == 'openid'

    def test_token_auth_code_seals_the_refresh_token(self, oauth_app):
        """The refresh token leaves under the id the code came in with."""
        mock_client = _mock_auth0_response(
            json_data={'access_token': 'jwt', 'refresh_token': 'v1.first'}
        )
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': _seal_code('auth-code', DEVICE_ID),
                },
            )
        body = response.json()
        assert body['access_token'] == 'jwt'
        assert _open_seal(_SEAL_KIND_REFRESH, body['refresh_token']) == (
            'v1.first',
            DEVICE_ID,
            '',
        )

    def test_token_auth_code_rejects_a_tampered_seal(self, oauth_app):
        sealed = _seal_code('auth-code', DEVICE_ID)
        prefix, encoded, signature = sealed.split('.')
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': f'{prefix}.{encoded}.{signature[:-4]}AAAA',
                },
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_auth_code_rejects_a_sealed_refresh_token(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': _seal_refresh_token('v1.refresh', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_auth_code_rejects_a_bare_code(self, oauth_app):
        """A code that did not pass through the callback carries no id."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={'grant_type': _GRANT_AUTHORIZATION_CODE, 'code': 'auth-code'},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_auth_code_rejects_a_non_string_code(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=json.dumps(
                    {'grant_type': _GRANT_AUTHORIZATION_CODE, 'code': ['auth-code']}
                ).encode(),
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_grant'
        mock_client.post.assert_not_called()

    def test_token_error_response_is_forwarded_unsealed(self, oauth_app):
        """An Auth0 error body has no refresh token to seal and passes through."""
        mock_client = _mock_auth0_response(
            status_code=HTTPStatus.FORBIDDEN,
            json_data={'error': _ERROR_INVALID_GRANT, 'error_description': 'expired'},
        )
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('v1.refresh', DEVICE_ID),
                },
            )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {
            'error': _ERROR_INVALID_GRANT,
            'error_description': 'expired',
        }

    def test_token_fails_without_client_secret(self):
        """Token endpoint should return 500 when AUTH0_ALPACON_LOGIN_CLIENT_SECRET is missing."""
        sealed_code = _seal_code('test-code', DEVICE_ID)
        env_without_secret = {
            'AUTH0_ALPACON_DOMAIN': TEST_AUTH0_ALPACON_DOMAIN,
            'AUTH0_ALPACON_LOGIN_CLIENT_ID': TEST_CLIENT_ID,
            'AUTH0_ALPACON_USER_AUDIENCE': 'https://alpacon.io/access/',
            'ALPACON_MCP_AUTH_ENABLED': 'true',
            'ALPACON_MCP_RESOURCE_URL': TEST_RESOURCE_URL,
        }

        mock_server = MockMCPServer()
        with patch.dict('os.environ', env_without_secret, clear=False):
            # Unset AUTH0_ALPACON_LOGIN_CLIENT_SECRET if present
            with patch.dict(
                'os.environ', {'AUTH0_ALPACON_LOGIN_CLIENT_SECRET': ''}, clear=False
            ):
                register_oauth_routes(mock_server)
                app = Starlette(routes=mock_server.routes)
                client = TestClient(app, raise_server_exceptions=False)
                response = client.post(
                    _TOKEN_PATH,
                    data={
                        'grant_type': _GRANT_AUTHORIZATION_CODE,
                        'code': sealed_code,
                    },
                )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert 'AUTH0_ALPACON_LOGIN_CLIENT_SECRET' in data.get('error', '')

    def test_token_overrides_redirect_uri_for_auth_code(self, oauth_app):
        """Token exchange should use server's callback URL, not client's."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': _seal_code('test-code', DEVICE_ID),
                    'redirect_uri': 'http://localhost:52048/callback',
                },
            )
        assert response.status_code == HTTPStatus.OK
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['redirect_uri'] == (
            f'{TEST_RESOURCE_URL}{_CALLBACK_PATH}'
        )

    def test_token_sets_redirect_uri_even_if_client_omits_it(self, oauth_app):
        """Auth0 requires redirect_uri in token exchange when used in authorize."""
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
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs['data']['redirect_uri'] == (
            f'{TEST_RESOURCE_URL}{_CALLBACK_PATH}'
        )

    @pytest.mark.usefixtures('default_int_digit_limit')
    @pytest.mark.parametrize(
        'body',
        [
            b'not valid json',
            b'\xff',
            b'{"grant_type": "\xff"}',
            b'[' * _MAX_REQUEST_BODY_BYTES,
            b'1' * (sys.int_info.default_max_str_digits + 1),
            b'{"grant_type": "\\ud800"}',
            b'{"grant_type": "\xed\xa0\x80"}',
        ],
        ids=[
            'not-json',
            'not-utf8',
            'inside-a-string',
            'nested-to-the-size-cap',
            'integer-over-the-digit-limit',
            'escaped-lone-surrogate',
            'raw-lone-surrogate',
        ],
    )
    def test_token_rejects_json_body_that_cannot_be_decoded(self, oauth_app, body):
        response = oauth_app.post(
            _TOKEN_PATH,
            content=body,
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            'error': _ERROR_INVALID_REQUEST,
            'error_description': 'Invalid JSON',
        }

    def test_token_rejects_json_body_that_overflows_the_parser(self, oauth_app):
        with patch('utils.oauth._http.json.loads', side_effect=RecursionError):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=b'[]',
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {
            'error': _ERROR_INVALID_REQUEST,
            'error_description': 'Invalid JSON',
        }

    def test_token_rejects_non_object_json(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            content=json.dumps(['not', 'an', 'object']).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == 'invalid_request'

    def test_token_rejects_non_utf8_body(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            content=b'\xff\xfe',
            headers={'content-type': _FORM_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data['error'] == 'invalid_request'
        assert 'UTF-8' in data['error_description']


class TestRefreshFailureLogging:
    @pytest.mark.parametrize('status', [400, 401, 429, 500])
    def test_failure_logs_only_diagnostic_fields(self, oauth_app, caplog, status):
        refresh_token = 'opaque_refresh_' + 'r' * 40
        access_token = 'opaque_access_' + 'a' * 40
        id_token = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature1234567890'
        description = (
            'Refresh token revoked.\n\r\x00\x1b'
            f'{refresh_token} {access_token} {id_token} '
            'person@example.com auth0|private-subject ' + 'ordinary prose ' * 30
        )
        body = {
            'error': 'invalid_grant',
            'error_description': description,
            'refresh_token': refresh_token,
            'access_token': access_token,
            'id_token': id_token,
            'email': 'person@example.com',
            'sub': 'auth0|private-subject',
        }
        mock_client = _mock_auth0_response(status_code=status, json_data=body)
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token(refresh_token, DEVICE_ID),
                },
            )
        assert response.status_code == status
        assert response.json() == body
        [record] = [r for r in caplog.records if r.levelname == 'WARNING']
        assert 'error: invalid_grant' in record.getMessage()
        assert f'description_class: other, status: {status}' in record.getMessage()
        assert 'grant_type: refresh_token' in record.getMessage()
        assert 'client_id:' not in record.getMessage()
        assert 'rotating: unknown' in record.getMessage()
        for secret in (
            refresh_token,
            access_token,
            id_token,
            body['email'],
            body['sub'],
            TEST_CLIENT_SECRET,
            TEST_CLIENT_ID,
            description,
            'Refresh token revoked.',
            'ordinary prose',
        ):
            assert secret not in str(record.__dict__)
        for control in ('\n', '\r', '\x00', '\x1b'):
            assert control not in record.getMessage()

    @pytest.mark.parametrize(
        ('error', 'expected_error'),
        [
            ('invalid_grant', 'invalid_grant'),
            ('a' * 64, 'unknown'),
            ('a' * 65, 'unknown'),
            ('access_denied', 'access_denied'),
            ('invalid_client', 'invalid_client'),
            ('unauthorized_client', 'unauthorized_client'),
            ('invalid_request', 'invalid_request'),
            ('server_error', 'server_error'),
            ('temporarily_unavailable', 'temporarily_unavailable'),
            ('unknown', 'unknown'),
            ([], 'unknown'),
            ({}, 'unknown'),
            ('invalid_grant\n', 'unknown'),
            ('Invalid grant', 'unknown'),
            ('', 'unknown'),
            (None, 'unknown'),
        ],
    )
    def test_failure_classifies_description_and_validates_error(
        self, oauth_app, caplog, error, expected_error
    ):
        description = 'Unknown or invalid refresh token.'
        mock_client = _mock_auth0_response(
            status_code=400,
            json_data={'error': error, 'error_description': description},
        )
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('r' * 40, DEVICE_ID),
                },
            )
        assert response.status_code == 400
        [record] = [r for r in caplog.records if r.levelname == 'WARNING']
        assert f'error: {expected_error},' in record.getMessage()
        classification = (
            'action_denied'
            if error == 'access_denied'
            else 'invalid_or_unknown_refresh_token'
        )
        assert f'description_class: {classification},' in record.getMessage()
        assert description not in str(record.__dict__)

    @pytest.mark.parametrize(
        ('error', 'description', 'classification'),
        [
            (
                'invalid_grant',
                'Unknown or invalid refresh token.',
                'invalid_or_unknown_refresh_token',
            ),
            ('invalid_grant', 'Refresh token has been reused.', 'refresh_token_reused'),
            ('invalid_grant', 'Refresh token reuse detected', 'refresh_token_reused'),
            ('invalid_grant', 'Refresh token expired', 'refresh_token_expired'),
            ('access_denied', 'signed_out', 'action_denied_signed_out'),
            (
                'access_denied',
                'Denied person@example.com auth0|subject',
                'action_denied',
            ),
            ('access_denied', 'Refresh token expired', 'action_denied'),
            ('invalid_grant', 'signed_out', 'other'),
            ('invalid_grant', None, 'other'),
            ('invalid_grant', ['private-response'], 'other'),
            ('invalid_grant', {'private': 'response'}, 'other'),
        ],
    )
    def test_failure_logs_fixed_description_classification(
        self, oauth_app, caplog, error, description, classification
    ):
        body = {'error': error, 'error_description': description}
        mock_client = _mock_auth0_response(status_code=400, json_data=body)
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('private-refresh', DEVICE_ID),
                },
            )
        assert response.json() == body
        [record] = [r for r in caplog.records if r.levelname == 'WARNING']
        assert f'description_class: {classification},' in record.getMessage()
        if isinstance(description, str):
            assert description not in record.args
            assert description not in record.msg
        for private in ('private-refresh', 'person@example.com', 'auth0|subject'):
            assert private not in str(record.__dict__)

    @pytest.mark.parametrize('malformed', ['non-json', 'non-object'])
    def test_malformed_failure_logs_once(self, oauth_app, caplog, malformed):
        mock_client = _mock_auth0_response(status_code=502, json_data=['unexpected'])
        if malformed == 'non-json':
            mock_client.post.return_value.json.side_effect = ValueError('not JSON')
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('private-refresh', DEVICE_ID),
                },
            )
        assert response.status_code == 502
        [record] = [r for r in caplog.records if r.levelname == 'WARNING']
        assert 'status: 502' in record.getMessage()
        assert 'client_id:' not in record.getMessage()

    def test_success_has_no_new_warning(self, oauth_app, caplog):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                data={
                    'grant_type': _GRANT_REFRESH_TOKEN,
                    'refresh_token': _seal_refresh_token('private-refresh', DEVICE_ID),
                },
            )
        assert response.status_code == 200
        assert not [r for r in caplog.records if r.levelname == 'WARNING']


@pytest.mark.parametrize(
    'grant_type', [_GRANT_AUTHORIZATION_CODE, _GRANT_REFRESH_TOKEN]
)
def test_registered_client_exchanges_grants_with_pinned_auth0_client(
    oauth_app, grant_type
):
    client_id = _mint_client_id()
    device_id = _registered_device_id(client_id)
    assert device_id is not None
    mock_client = _mock_auth0_response(
        json_data={
            'access_token': 'access',
            'refresh_token': 'rotated',
            'expires_in': 3600,
        }
    )
    field, seal = (
        ('code', _seal_code)
        if grant_type == _GRANT_AUTHORIZATION_CODE
        else ('refresh_token', _seal_refresh_token)
    )
    with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
        response = oauth_app.post(
            _TOKEN_PATH,
            data={
                'grant_type': grant_type,
                'client_id': client_id,
                field: seal('upstream-value', device_id),
            },
        )
    assert response.status_code == HTTPStatus.OK
    sent = mock_client.post.call_args.kwargs['data']
    assert sent['client_id'] == TEST_CLIENT_ID
    assert sent['client_secret'] == TEST_CLIENT_SECRET
    assert response.json()['expires_in'] == 3600
    opened = _open_seal(_SEAL_KIND_REFRESH, response.json()['refresh_token'])
    assert opened is not None
    assert opened.device_id == device_id


@pytest.mark.parametrize('client_id', ['tampered', 'wrong_kind'])
def test_token_rejects_invalid_registration(oauth_app, client_id):
    client_id = (
        _mint_client_id() + 'x'
        if client_id == 'tampered'
        else _seal_code('code', DEVICE_ID)
    )
    response = oauth_app.post(
        _TOKEN_PATH,
        data={
            'grant_type': _GRANT_AUTHORIZATION_CODE,
            'client_id': client_id,
            'code': _seal_code('code', DEVICE_ID),
        },
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['error'] == 'invalid_client'
