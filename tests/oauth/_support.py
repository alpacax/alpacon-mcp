"""Constants, the mock MCP server, and request helpers shared by the OAuth tests."""

import base64
import json
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

from starlette.routing import Route

from utils.oauth._http import (
    _AUTHORIZE_PATH,
    _DEFAULT_AUDIENCE,
    _DEFAULT_SCOPES,
    _PKCE_CHALLENGE_METHOD,
)
from utils.oauth._sealing import (
    _NONCE_COOKIE_NAME,
    _hash_nonce,
    _sign_state,
    _verify_state,
)

FULL_SCOPE = ' '.join(_DEFAULT_SCOPES)


# Test configuration constants
TEST_AUTH0_DOMAIN = 'test.us.auth0.com'


TEST_CLIENT_ID = 'test-client-id'


TEST_CLIENT_SECRET = 'test-client-secret'


TEST_RESOURCE_URL = 'https://mcp.test.alpacon.io'


# Redirect targets used across the state tests
TRUSTED_REDIRECT_URI = 'https://claude.ai/cb'


EVIL_REDIRECT_URI = 'https://evil.com/cb'


# Device ids the Auth0 action's validator accepts
DEVICE_ID = 'a' * 32


OTHER_DEVICE_ID = 'b' * 32


# An exp far enough ahead that a forged payload is never rejected as expired
FAR_FUTURE_EXP = 9999999999


LISTED_REDIRECT_URI = 'https://claude.ai/api/mcp/auth_callback'


EXEMPT_REDIRECT_URI = 'https://global.consent.azure-apim.net/redirect'


UNLISTED_PATH_URI = 'https://chatgpt.com/evil/path'


CONNECTOR_REDIRECT_URI = 'https://chatgpt.com/connector/oauth/abc123'


# Environment variables needed for OAuth config
OAUTH_ENV = {
    'AUTH0_DOMAIN': TEST_AUTH0_DOMAIN,
    'AUTH0_CLIENT_ID': TEST_CLIENT_ID,
    'AUTH0_CLIENT_SECRET': TEST_CLIENT_SECRET,
    'AUTH0_AUDIENCE': _DEFAULT_AUDIENCE,
    'ALPACON_MCP_AUTH_ENABLED': 'true',
    'ALPACON_MCP_RESOURCE_URL': TEST_RESOURCE_URL,
    # Pinned empty so a developer's exported redirect_uri settings cannot
    # invert the default-behavior assertions below.
    'ALLOWED_REDIRECT_URIS': '',
    'ALLOWED_REDIRECT_DOMAINS': '',
    'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY': '',
}


REPORT_ONLY = {'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY': 'true'}


# RFC 7636 appendix B's challenge — 43 characters, so it clears the format check
PKCE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'


# Every non-exempt authorize request has to carry these
PKCE_PARAMS = {
    'code_challenge': PKCE_CHALLENGE,
    'code_challenge_method': _PKCE_CHALLENGE_METHOD,
}


# The nonce a browser is pretending to carry through the callback tests
TEST_NONCE = 'test-nonce-value'


# Set-Cookie assertions lowercase the whole header, so the name must match in kind
NONCE_COOKIE_PREFIX = f'{_NONCE_COOKIE_NAME.lower()}='


class MockMCPServer:
    """Stands in for FastMCP, collecting whatever register_oauth_routes registers."""

    def __init__(self):
        self.routes = []

    def custom_route(self, path, methods=None):
        def decorator(func):
            self.routes.append(Route(path, func, methods=methods))
            return func

        return decorator


def _forge_state_under_valid_signature():
    """A state whose payload was swapped out after signing, keeping the signature."""
    signed = _sign_state({'redirect_uri': TRUSTED_REDIRECT_URI})
    _, _, signature = signed.rpartition('.')
    forged = base64.urlsafe_b64encode(
        json.dumps({'redirect_uri': EVIL_REDIRECT_URI, 'exp': FAR_FUTURE_EXP}).encode()
    ).decode()
    return f'{forged}.{signature}'


def _mock_auth0_response(status_code=HTTPStatus.OK, json_data=None):
    """Create a mock httpx AsyncClient that returns the given response."""
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {'access_token': 'test-token'}
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _authorize_scope_parts(response):
    """Return the scope tokens of an /oauth/authorize redirect."""
    query = parse_qs(urlparse(response.headers['location']).query)
    return query.get('scope', [''])[0].split()


def _authorize_device_id(response):
    """The one device id in the redirect's scope, checked against its state."""
    scope_ids = [
        s.removeprefix('device:')
        for s in _authorize_scope_parts(response)
        if s.startswith('device:')
    ]
    assert len(scope_ids) == 1, scope_ids
    query = parse_qs(urlparse(response.headers['location']).query)
    state_data = _verify_state(query['state'][0])
    assert state_data.get('device_id') == scope_ids[0]
    return scope_ids[0]


def _authorize(oauth_app, scope='openid profile'):
    return oauth_app.get(
        _AUTHORIZE_PATH,
        params={
            'response_type': 'code',
            'redirect_uri': 'http://localhost:8080/callback',
            'scope': scope,
            **PKCE_PARAMS,
        },
        follow_redirects=False,
    )


def _make_composite_state(redirect_uri='', state='', **extra):
    """Helper to create signed composite state as the authorize endpoint does."""
    extra.setdefault('nonce_hash', _hash_nonce(TEST_NONCE))
    extra.setdefault('device_id', DEVICE_ID)
    return _sign_state({'redirect_uri': redirect_uri, 'state': state, **extra})
