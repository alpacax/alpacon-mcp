"""Shared wire vocabulary, configuration and response helpers for the OAuth proxy."""

import os
from functools import wraps
from http import HTTPStatus
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from utils.auth0_env import get_auth0_env
from utils.logger import get_logger
from utils.routes import RouteHandler

logger = get_logger('oauth')

# This server's own routes, advertised in the metadata.
_METADATA_PATH = '/.well-known/oauth-authorization-server'
_AUTHORIZE_PATH = '/oauth/authorize'
_TOKEN_PATH = '/oauth/token'
_REGISTER_PATH = '/oauth/register'
_CALLBACK_PATH = '/oauth/callback'
# Un-prefixed copies for clients that skip the metadata document.
_FALLBACK_AUTHORIZE_PATH = '/authorize'
_FALLBACK_TOKEN_PATH = '/token'
_FALLBACK_REGISTER_PATH = '/register'

_RESOURCE_URL_ENV = 'ALPACON_MCP_RESOURCE_URL'

# Paths on the Auth0 tenant.
_AUTH0_AUTHORIZE_PATH = '/authorize'
_AUTH0_TOKEN_PATH = '/oauth/token'
_AUTH0_TIMEOUT_SECONDS = 30.0

_GRANT_AUTHORIZATION_CODE = 'authorization_code'
_GRANT_REFRESH_TOKEN = 'refresh_token'
_RESPONSE_TYPE_CODE = 'code'

_ERROR_INVALID_REQUEST = 'invalid_request'
_ERROR_INVALID_CLIENT = 'invalid_client'
_ERROR_INVALID_GRANT = 'invalid_grant'
_ERROR_UNSUPPORTED_GRANT_TYPE = 'unsupported_grant_type'
_ERROR_SERVER_ERROR = 'server_error'
_ERROR_INVALID_CLIENT_METADATA = 'invalid_client_metadata'
_ERROR_INVALID_REDIRECT_URI = 'invalid_redirect_uri'

_JSON_CONTENT_TYPE = 'application/json'
_FORM_CONTENT_TYPE = 'application/x-www-form-urlencoded'
_FORM_HEADERS = {'Content-Type': _FORM_CONTENT_TYPE}
_CACHE_CONTROL_NO_STORE = 'no-store'

_TOKEN_ENDPOINT_AUTH_NONE = 'none'

_DEFAULT_AUDIENCE = 'https://alpacon.io/access/'
_OFFLINE_ACCESS_SCOPE = 'offline_access'
_DEFAULT_SCOPES = ('openid', 'profile', 'email', _OFFLINE_ACCESS_SCOPE)
_MFA_SCOPE = 'mfa'

# Enforced by authorize and advertised by the metadata, so the two cannot drift.
# plain is refused: its challenge is the verifier, so a request reader can replay it.
_PKCE_CHALLENGE_METHOD = 'S256'

# Copied from the first authorize leg into the last and nothing else, so a forged
# state cannot inject parameters into the final code exchange.
_REPLAYED_AUTHORIZE_PARAMS = (
    'code_challenge',
    'code_challenge_method',
    'nonce',
    'resource',
)

# Preflight for the two endpoints a browser client posts to. No Allow-Credentials:
# with a wildcard origin any page could ride the user's cookies, and neither reads one.
_CORS_PREFLIGHT_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Max-Age': '3600',
}

# Both body-reading routes are unauthenticated and a real request is under a
# kilobyte; without a cap, the client decides how much the server allocates.
_MAX_REQUEST_BODY_BYTES = 16 * 1024


def _get_oauth_config() -> dict[str, str]:
    """Read the Auth0 login settings; raises ValueError if domain, id or secret is unset."""
    domain = get_auth0_env('AUTH0_ALPACON_DOMAIN', '')
    client_id = get_auth0_env('AUTH0_ALPACON_LOGIN_CLIENT_ID', '')
    client_secret = get_auth0_env('AUTH0_ALPACON_LOGIN_CLIENT_SECRET', '')
    audience = get_auth0_env('AUTH0_ALPACON_USER_AUDIENCE', _DEFAULT_AUDIENCE)
    mfa_audience = get_auth0_env('AUTH0_ALPACON_MFA_AUDIENCE', '')

    if not domain:
        raise ValueError('AUTH0_ALPACON_DOMAIN environment variable is required')
    if not client_id:
        raise ValueError(
            'AUTH0_ALPACON_LOGIN_CLIENT_ID environment variable is required'
        )
    if not client_secret:
        raise ValueError(
            'AUTH0_ALPACON_LOGIN_CLIENT_SECRET environment variable is required'
        )

    if not mfa_audience:
        mfa_audience = f'https://{domain}/mfa/'

    return {
        'domain': domain,
        'client_id': client_id,
        'client_secret': client_secret,
        'audience': audience,
        'mfa_audience': mfa_audience,
        'auth0_base_url': f'https://{domain}',
    }


def _get_server_url(request: Request) -> str:
    """Build the server's base URL from ALPACON_MCP_RESOURCE_URL when set, else the
    request, since forwarding headers can be spoofed."""
    configured_base_url = os.getenv(_RESOURCE_URL_ENV)
    if configured_base_url:
        return configured_base_url.rstrip('/')
    return f'{request.url.scheme}://{request.url.netloc}'


def _callback_url(server_url: str) -> str:
    """The redirect_uri Auth0 sends the browser back to: this server's own callback."""
    return f'{server_url}{_CALLBACK_PATH}'


def _auth0_authorize_url(config: dict[str, str], params: dict[str, str]) -> str:
    return f'{config["auth0_base_url"]}{_AUTH0_AUTHORIZE_PATH}?{urlencode(params)}'


class _OAuthRequestError(Exception):
    """A stage's refusal; the handler returns `response` exactly as built."""

    def __init__(self, response: Response) -> None:
        super().__init__(response.status_code)
        self.response = response


def _oauth_error_response(
    error: str,
    description: str,
    status: HTTPStatus = HTTPStatus.BAD_REQUEST,
) -> JSONResponse:
    """Build a standard OAuth error response (RFC 6749 section 5.2 shape)."""
    return JSONResponse(
        {'error': error, 'error_description': description}, status_code=status
    )


def _misconfiguration_response(error: ValueError) -> JSONResponse:
    """The 500 a handler answers when the OAuth config or a secret is unusable."""
    return JSONResponse(
        {'error': str(error)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
    )


def _require_oauth_config() -> dict[str, str]:
    try:
        return _get_oauth_config()
    except ValueError as e:
        raise _OAuthRequestError(_misconfiguration_response(e)) from e


def _invalid_grant_response(what: str) -> JSONResponse:
    """The OAuth answer that makes a client start over with a fresh login."""
    return JSONResponse(
        {
            'error': _ERROR_INVALID_GRANT,
            'error_description': f'The {what} was not issued by this server',
        },
        status_code=HTTPStatus.BAD_REQUEST,
    )


async def _read_bounded_body(request: Request) -> bytes | None:
    """The body, or None once it passes the size cap. Streamed because a chunked
    request declares no length."""
    declared = request.headers.get('content-length', '')
    if declared.isdigit() and int(declared) > _MAX_REQUEST_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_REQUEST_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b''.join(chunks)


def _build_redirect_url(base_url: str, extra_params: dict[str, str]) -> str:
    """Safely merge query params into a URL, preserving existing params."""
    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    merged = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
    merged.update(extra_params)
    new_query = urlencode(merged, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _allow_browser_clients(handler: RouteHandler) -> RouteHandler:
    """Answer the CORS preflight and mark responses cross-origin readable, per route:
    CORSMiddleware app-wide would also open the MCP transport endpoint."""

    @wraps(handler)
    async def with_cors(request: Request) -> Response:
        if request.method == 'OPTIONS':
            return Response(
                status_code=HTTPStatus.NO_CONTENT, headers=_CORS_PREFLIGHT_HEADERS
            )

        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    return with_cors
