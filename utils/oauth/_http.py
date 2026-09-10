"""Wire constants and the request/response plumbing the routes share."""

import os
import re
from functools import wraps
from http import HTTPStatus
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_RESOURCE_URL_ENV = 'ALPACON_MCP_RESOURCE_URL'


_METADATA_PATH = '/.well-known/oauth-authorization-server'


_AUTHORIZE_PATH = '/oauth/authorize'


_TOKEN_PATH = '/oauth/token'


_REGISTER_PATH = '/oauth/register'


_CALLBACK_PATH = '/oauth/callback'


_RESPONSE_TYPE_CODE = 'code'


_GRANT_AUTHORIZATION_CODE = 'authorization_code'


_GRANT_REFRESH_TOKEN = 'refresh_token'


# Anything else would turn the token endpoint into a generic credential
# exchange against the client_secret it injects.
_ALLOWED_GRANT_TYPES = (_GRANT_AUTHORIZATION_CODE, _GRANT_REFRESH_TOKEN)


_ERROR_INVALID_REQUEST = 'invalid_request'


_ERROR_INVALID_CLIENT = 'invalid_client'


_ERROR_INVALID_GRANT = 'invalid_grant'


_ERROR_UNSUPPORTED_GRANT_TYPE = 'unsupported_grant_type'


_ERROR_SERVER_ERROR = 'server_error'


_ERROR_INVALID_CLIENT_METADATA = 'invalid_client_metadata'


_ERROR_INVALID_REDIRECT_URI = 'invalid_redirect_uri'


_JSON_CONTENT_TYPE = 'application/json'


_FORM_CONTENT_TYPE = 'application/x-www-form-urlencoded'


_DEFAULT_AUDIENCE = 'https://alpacon.io/access/'


_OFFLINE_ACCESS_SCOPE = 'offline_access'


_DEFAULT_SCOPES = ('openid', 'profile', 'email', _OFFLINE_ACCESS_SCOPE)


# Preflight for the two endpoints a browser client posts to. No
# Allow-Credentials: with a wildcard origin it would let any page ride the
# user's cookies, and neither endpoint reads one.
_CORS_PREFLIGHT_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Max-Age': '3600',
}


# Shared by the authorize gate and the discovery document, so the enforced and
# the advertised method cannot drift. plain is refused: its challenge is the
# verifier, so anyone who reads the request can replay it.
_PKCE_CHALLENGE_METHOD = 'S256'


# RFC 7636 §4.1: a base64url SHA-256 digest. Matched, never normalized, since
# the value checked here is the one forwarded upstream.
_PKCE_CHALLENGE_PATTERN = re.compile(r'^[A-Za-z0-9\-._~]{43,128}\Z')


# Both body-reading routes are unauthenticated and a real request is well under
# a kilobyte; without a cap, one request decides how much the server allocates.
_MAX_REQUEST_BODY_BYTES = 16 * 1024


# Escaping expands a byte up to sixfold, so an unbounded client value on an
# unauthenticated route inflates log volume.
_LOG_VALUE_MAX_CHARS = 512


class _OAuthRequestError(Exception):
    """Raised by a stage to end the handler with one error response.

    Without a description the body is the bare `{'error': ...}` the
    configuration failures answer with, not the RFC 6749 shape.
    """

    def __init__(
        self,
        status: HTTPStatus,
        error: str,
        description: str | None = None,
        headers: dict | None = None,
    ) -> None:
        super().__init__(description)
        self.status = status
        self.error = error
        self.description = description
        self.headers = headers


def _get_oauth_config() -> dict[str, str]:
    """Get OAuth configuration from environment variables."""
    domain = os.getenv('AUTH0_DOMAIN', '')
    client_id = os.getenv('AUTH0_CLIENT_ID', '')
    client_secret = os.getenv('AUTH0_CLIENT_SECRET', '')
    audience = os.getenv('AUTH0_AUDIENCE', _DEFAULT_AUDIENCE)
    mfa_audience = os.getenv('AUTH0_MFA_AUDIENCE', '')

    if not domain:
        raise ValueError('AUTH0_DOMAIN environment variable is required')
    if not client_id:
        raise ValueError('AUTH0_CLIENT_ID environment variable is required')
    if not client_secret:
        raise ValueError('AUTH0_CLIENT_SECRET environment variable is required')

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


def _get_server_url(request) -> str:
    """The server's base URL: ALPACON_MCP_RESOURCE_URL if set, else the request's.

    The env var takes precedence so spoofable forwarding headers are not trusted.
    """
    configured_base_url = os.getenv(_RESOURCE_URL_ENV)
    if configured_base_url:
        return configured_base_url.rstrip('/')
    return f'{request.url.scheme}://{request.url.netloc}'


def _callback_url(server_url: str) -> str:
    """Build the callback this server hands Auth0 as redirect_uri."""
    return f'{server_url}{_CALLBACK_PATH}'


def _auth0_authorize_url(config: dict[str, str], params: dict) -> str:
    return f'{config["auth0_base_url"]}/authorize?{urlencode(params)}'


def _auth0_token_url(config: dict[str, str]) -> str:
    return f'{config["auth0_base_url"]}/oauth/token'


def _build_redirect_url(base_url: str, extra_params: dict) -> str:
    """Safely merge query params into a URL, preserving existing params."""
    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    merged = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
    merged.update(extra_params)
    new_query = urlencode(merged, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _escape_for_log(value: str) -> str:
    """Escape control characters in a client-supplied value.

    A raw newline would otherwise let a client forge a second log line.
    """
    escaped = ''.join(
        c if c.isprintable() else repr(c)[1:-1] for c in value[:_LOG_VALUE_MAX_CHARS]
    )
    if len(value) > _LOG_VALUE_MAX_CHARS or len(escaped) > _LOG_VALUE_MAX_CHARS:
        return escaped[:_LOG_VALUE_MAX_CHARS] + '...(truncated)'
    return escaped


async def _read_bounded_body(request: Request) -> bytes | None:
    """The body, or None once it passes `_MAX_REQUEST_BODY_BYTES`.

    Streamed rather than read whole: a chunked request declares no length, so a
    Content-Length check alone would still buffer everything before rejecting it.
    """
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


def _oauth_error_response(
    error: str,
    description: str,
    status: HTTPStatus = HTTPStatus.BAD_REQUEST,
) -> JSONResponse:
    """Build a standard OAuth error response (RFC 6749 section 5.2 shape)."""
    return JSONResponse(
        {'error': error, 'error_description': description}, status_code=status
    )


def _reject_response(exc: _OAuthRequestError) -> JSONResponse:
    if exc.description is None:
        response = JSONResponse({'error': exc.error}, status_code=exc.status)
    else:
        response = _oauth_error_response(exc.error, exc.description, status=exc.status)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def _allow_browser_clients(handler):
    """Answer the CORS preflight and mark the response readable cross-origin.

    Only for endpoints a browser client reaches with fetch: /oauth/authorize and
    /oauth/callback are top-level navigations, which CORS never governs. Starlette
    ships CORSMiddleware, but custom_route takes no per-route middleware and
    installing it app-wide would also open the MCP transport endpoint.
    """

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
