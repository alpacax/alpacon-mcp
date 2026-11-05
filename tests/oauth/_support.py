"""Constants, a stand-in MCP server and request helpers shared by the OAuth proxy tests."""

import base64
import json
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import httpx
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from utils.oauth import register_oauth_routes
from utils.oauth._http import _PKCE_CHALLENGE_METHOD
from utils.oauth._sealing import (
    _NONCE_COOKIE_PREFIX,
    _hash_nonce,
    _nonce_cookie_name,
    _sign_state,
    _verify_state,
)

# Test configuration constants
TEST_AUTH0_ALPACON_DOMAIN = 'test.us.auth0.com'
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

# Environment variables needed for OAuth config
OAUTH_ENV = {
    'AUTH0_ALPACON_DOMAIN': TEST_AUTH0_ALPACON_DOMAIN,
    'AUTH0_ALPACON_LOGIN_CLIENT_ID': TEST_CLIENT_ID,
    'AUTH0_ALPACON_LOGIN_CLIENT_SECRET': TEST_CLIENT_SECRET,
    'AUTH0_ALPACON_USER_AUDIENCE': 'https://alpacon.io/access/',
    'AUTH0_DOMAIN': '',
    'AUTH0_CLIENT_ID': '',
    'AUTH0_CLIENT_SECRET': '',
    'AUTH0_AUDIENCE': '',
    'AUTH0_MFA_AUDIENCE': '',
    'AUTH0_NAMESPACE': '',
    'ALPACON_MCP_AUTH_ENABLED': 'true',
    'ALPACON_MCP_RESOURCE_URL': TEST_RESOURCE_URL,
    # Pinned empty so a developer's exported redirect_uri settings cannot
    # invert the default-behavior assertions below.
    'ALLOWED_REDIRECT_URIS': '',
    'ALLOWED_REDIRECT_DOMAINS': '',
    'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY': '',
}

REPORT_ONLY = {'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY': 'true'}

# RFC 7636 appendix B's challenge—43 characters, so it clears the format check
PKCE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'

# Every non-exempt authorize request has to carry these
PKCE_PARAMS = {
    'code_challenge': PKCE_CHALLENGE,
    'code_challenge_method': _PKCE_CHALLENGE_METHOD,
}

# The nonce a browser is pretending to carry through the callback tests
TEST_NONCE = 'test-nonce-value'
TEST_NONCE_COOKIE = _nonce_cookie_name(_hash_nonce(TEST_NONCE))

# Set-Cookie assertions lowercase the whole header, so the name must match in kind
TEST_NONCE_SET_COOKIE = f'{TEST_NONCE_COOKIE.lower()}='


class MockMCPServer:
    """Stands in for the MCP server, collecting whatever register_oauth_routes registers."""

    def __init__(self):
        self.routes = []

    def custom_route(self, path, methods=None):
        def decorator(func):
            self.routes.append(Route(path, func, methods=methods))
            return func

        return decorator


def _browser_client() -> TestClient:
    """One cookie jar across requests, over https so it keeps __Host- cookies."""
    mock_server = MockMCPServer()
    register_oauth_routes(mock_server)
    return TestClient(
        Starlette(routes=mock_server.routes),
        base_url='https://testserver',
        raise_server_exceptions=False,
    )


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


def _issued_nonce(response: httpx.Response) -> str:
    issued = {
        name: value
        for name, value in response.cookies.items()
        if name.startswith(f'{_NONCE_COOKIE_PREFIX}_')
    }
    assert len(issued) == 1
    [(name, nonce)] = issued.items()
    assert name == _nonce_cookie_name(_hash_nonce(nonce))
    return nonce


def _state_payload(state: str) -> dict[str, object]:
    """_verify_state on a state the test expects to verify."""
    payload = _verify_state(state)
    assert payload is not None
    return payload
