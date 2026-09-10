"""Tests for the /oauth/token endpoint."""

import json
from http import HTTPStatus
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.testclient import TestClient

from tests.oauth._support import (
    DEVICE_ID,
    OTHER_DEVICE_ID,
    TEST_AUTH0_DOMAIN,
    TEST_CLIENT_ID,
    TEST_CLIENT_SECRET,
    TEST_RESOURCE_URL,
    MockMCPServer,
    _mock_auth0_response,
)
from utils.oauth import register_oauth_routes
from utils.oauth._http import (
    _CALLBACK_PATH,
    _DEFAULT_AUDIENCE,
    _ERROR_INVALID_GRANT,
    _ERROR_INVALID_REQUEST,
    _ERROR_UNSUPPORTED_GRANT_TYPE,
    _FORM_CONTENT_TYPE,
    _GRANT_AUTHORIZATION_CODE,
    _GRANT_REFRESH_TOKEN,
    _JSON_CONTENT_TYPE,
    _OFFLINE_ACCESS_SCOPE,
    _TOKEN_PATH,
)
from utils.oauth._sealing import _seal_code, _seal_refresh_token, _unseal_refresh_token


class TestOAuthToken:
    """Tests for /oauth/token endpoint."""

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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
        mock_client.post.assert_not_called()

    def test_token_rejects_a_non_string_grant_type(self, oauth_app):
        """An unhashable one would raise on the allow-list test instead of 400."""
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH,
                content=json.dumps({'grant_type': ['refresh_token']}).encode(),
                headers={'content-type': _JSON_CONTENT_TYPE},
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
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
        assert response.json()['error'] == _ERROR_INVALID_REQUEST
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
        assert response.json()['error'] == _ERROR_UNSUPPORTED_GRANT_TYPE

    def test_token_rejects_password_grant(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            data={'grant_type': 'password', 'username': 'user', 'password': 'pass'},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_UNSUPPORTED_GRANT_TYPE

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
        assert _unseal_refresh_token(body['refresh_token']) == ('v1.rotated', DEVICE_ID)

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
                    'scope': f'openid {_OFFLINE_ACCESS_SCOPE} device:{OTHER_DEVICE_ID}',
                },
            )
        sent = mock_client.post.call_args.kwargs['data']
        assert sent['scope'] == f'openid {_OFFLINE_ACCESS_SCOPE}'
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
        mock_client.post.assert_not_called()

    def test_token_refresh_rejects_a_bare_refresh_token(self, oauth_app, caplog):
        """A refresh token issued before sealing would refresh under a shared
        key, so it is refused and the client logs in again. Every pre-sealing
        session hits this once at rollout, so it is not a warning."""
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
        mock_client.post.assert_not_called()

    def test_token_refresh_rejects_a_missing_refresh_token(self, oauth_app):
        mock_client = _mock_auth0_response()
        with patch('utils.oauth._token.httpx.AsyncClient', return_value=mock_client):
            response = oauth_app.post(
                _TOKEN_PATH, data={'grant_type': _GRANT_REFRESH_TOKEN}
            )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_GRANT
        mock_client.post.assert_not_called()

    def test_token_auth_code_unseals_the_code(self, oauth_app):
        """Auth0 sees the code it issued, and no client device id on this grant.

        The scope sent to /authorize already carried the id, so neither the body
        field nor a `device:` scope has anything to replace here.
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
        assert _unseal_refresh_token(body['refresh_token']) == ('v1.first', DEVICE_ID)

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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
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
        assert response.json()['error'] == _ERROR_INVALID_GRANT
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
        """Token endpoint should return 500 when AUTH0_CLIENT_SECRET is missing."""
        sealed_code = _seal_code('test-code', DEVICE_ID)
        env_without_secret = {
            'AUTH0_DOMAIN': TEST_AUTH0_DOMAIN,
            'AUTH0_CLIENT_ID': TEST_CLIENT_ID,
            'AUTH0_AUDIENCE': _DEFAULT_AUDIENCE,
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
                    _TOKEN_PATH,
                    data={
                        'grant_type': _GRANT_AUTHORIZATION_CODE,
                        'code': sealed_code,
                    },
                )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        data = response.json()
        assert 'AUTH0_CLIENT_SECRET' in data.get('error', '')

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

    def test_token_rejects_invalid_json(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            content=b'not valid json',
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    def test_token_rejects_non_object_json(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            content=json.dumps(['not', 'an', 'object']).encode(),
            headers={'content-type': _JSON_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()['error'] == _ERROR_INVALID_REQUEST

    def test_token_rejects_non_utf8_body(self, oauth_app):
        response = oauth_app.post(
            _TOKEN_PATH,
            content=b'\xff\xfe',
            headers={'content-type': _FORM_CONTENT_TYPE},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data['error'] == _ERROR_INVALID_REQUEST
        assert 'UTF-8' in data['error_description']
