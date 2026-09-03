"""OAuth 2.0 proxy endpoints for Auth0.

MCP clients such as claude.ai run the authorization code flow against this
server, which proxies to Auth0. The routes go through FastMCP's custom_route,
which bypasses MCP authentication, as OAuth endpoints must.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from functools import wraps
from http import HTTPStatus
from typing import Literal, TypedDict
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from utils.logger import get_logger

logger = get_logger('oauth')


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

_METADATA_CACHE_SECONDS = 3600

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


# Explicit state signing key; unset, it is derived from the client secret.
_STATE_SECRET_ENV = 'ALPACON_MCP_STATE_SECRET'

# Domain-separates the state key from other keys derived from the client secret.
_STATE_SECRET_INFO = b'alpacon-mcp-oauth-state-v1'

# Separate from the state key: a state lives ten minutes, a sealed refresh token
# as long as Auth0 allows, so rotating one must not cost the other.
_GRANT_SECRET_ENV = 'ALPACON_MCP_GRANT_SECRET'
_GRANT_SECRET_INFO = b'alpacon-mcp-oauth-grant-v1'

# The 32 bytes a derived key always has, so an explicit key cannot be weaker
# than none.
_SECRET_MIN_BYTES = 32

# Marks every value this server sealed, so a bare Auth0 token, which also
# contains dots, is never taken for a tampered seal.
_SEALED_PREFIX = 'amcp1'
_SEAL_KIND_CODE = 'code'
_SEAL_KIND_REFRESH = 'refresh'

# Covers an Auth0 login plus MFA; keeps a leaked state only briefly usable.
_STATE_TTL_SECONDS = 600

# Stage tags carried through the state in the two-stage MFA flow.
_STAGE_MFA = 'mfa'
_STAGE_REGULAR = 'regular'

# Mirrors the validator in the Auth0 action's code.js: a value accepted here but
# rejected there would silently fall back to fingerprint keying.
_DEVICE_ID_PATTERN = re.compile(r'^[A-Za-z0-9-]{8,64}$')


# The __Host- prefix makes the browser itself require Secure, Path=/ and no
# Domain, so the cookie cannot be planted by a sibling host.
_NONCE_COOKIE_NAME = '__Host-alpacon_oauth_nonce'


class _NonceCookieAttrs(TypedDict):
    path: Literal['/']
    secure: Literal[True]
    httponly: bool
    samesite: Literal['lax', 'strict', 'none']


# Shared by set and delete: a delete without Path addresses a different cookie,
# and one without Secure is rejected outright under a __Host- name, so the
# cookie survives. Lax, not Strict: Strict drops the cookie on the top-level
# return from Auth0.
_NONCE_COOKIE_ATTRS: _NonceCookieAttrs = {
    'path': '/',
    'secure': True,
    'httponly': True,
    'samesite': 'lax',
}


_ENV_ALLOWED_REDIRECT_DOMAINS = 'ALLOWED_REDIRECT_DOMAINS'
_ENV_ALLOWED_REDIRECT_URIS = 'ALLOWED_REDIRECT_URIS'
_ENV_REDIRECT_URI_REPORT_ONLY = 'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY'

_ALLOWED_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')

# Trusting a whole domain lets an authorization code land on any path an
# attacker can influence there, so each entry pins one callback endpoint.
_DEFAULT_REDIRECT_URIS = (
    # Anthropic: web, Desktop, mobile, Cowork
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
    # OpenAI: legacy connector callback, still served for published apps
    'https://chatgpt.com/connector_platform_oauth_redirect',
    # Cursor: web and Cursor Agents
    'https://www.cursor.com/agents/mcp/oauth/callback',
    # VS Code and GitHub Copilot: web
    'https://vscode.dev/redirect/',
    'https://antigravity.google/oauth-callback',
    # Microsoft Copilot Studio: the Power Platform connector gateway
    'https://global.consent.azure-apim.net/redirect',
)

# OpenAI issues one opaque callback id per connector, so the last segment cannot
# be pinned. No "/" in the class, so no deeper path matches; \Z rather than $,
# so a trailing newline cannot ride along.
_DEFAULT_REDIRECT_URI_PATTERNS = (
    re.compile(r'^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,64}\Z'),
)

# Copilot Studio's Power Platform connector cannot send a challenge, so its
# gateway callback may start a flow without one. Redundant with the allowlist
# today; kept so dropping the callback there cannot leave an exemption behind.
_PKCE_EXEMPT_REDIRECT_URIS = frozenset(
    {'https://global.consent.azure-apim.net/redirect'}
)

# Hosts report-only mode falls back to, derived from the endpoint list so a
# moved endpoint stays covered without a second edit. chat.openai.com has no
# endpoint entry and stays as the legacy OpenAI host. ALLOWED_REDIRECT_DOMAINS
# (comma-separated) overrides the list.
_DEFAULT_REDIRECT_DOMAINS = tuple(
    sorted(
        {host for uri in _DEFAULT_REDIRECT_URIS if (host := urlparse(uri).hostname)}
        | {'chat.openai.com'}
    )
)

# A real client registers one or two callbacks; the cap keeps one unauthenticated
# registration from driving a check, and in report-only mode a warning, per entry.
_MAX_REGISTERED_REDIRECT_URIS = 20


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


def _explicit_hex_secret(env_name: str) -> bytes | None:
    """The key an operator set, or None when the variable is unset."""
    explicit = os.getenv(env_name, '')
    if not explicit:
        return None
    # Signed values travel in URLs and proxy logs, so the key is an offline
    # brute-force target; hex-only input keeps a typed passphrase out.
    try:
        key = bytes.fromhex(explicit)
    except ValueError:
        raise ValueError(
            f'{env_name} must be hex; '
            f'generate one with openssl rand -hex {_SECRET_MIN_BYTES}'
        ) from None
    if len(key) < _SECRET_MIN_BYTES:
        raise ValueError(
            f'{env_name} must decode to at least {_SECRET_MIN_BYTES} bytes'
        )
    return key


def _derived_secret(info: bytes) -> bytes:
    """Derived from AUTH0_CLIENT_SECRET so no extra secret needs provisioning,
    and identical across replicas so a signed value verifies without shared
    storage.
    """
    client_secret = _get_oauth_config()['client_secret']
    return hmac.new(client_secret.encode(), info, hashlib.sha256).digest()


def _get_state_secret() -> bytes:
    return _explicit_hex_secret(_STATE_SECRET_ENV) or _derived_secret(
        _STATE_SECRET_INFO
    )


def _get_grant_secret() -> bytes:
    return _explicit_hex_secret(_GRANT_SECRET_ENV) or _derived_secret(
        _GRANT_SECRET_INFO
    )


def _sign_state(payload: dict) -> str:
    """Serialise a state payload with an expiry and an HMAC signature."""
    body = {**payload, 'exp': int(time.time()) + _STATE_TTL_SECONDS}
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, separators=(',', ':')).encode()
    ).decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(_get_state_secret(), encoded.encode(), hashlib.sha256).digest()
    ).decode()
    return f'{encoded}.{signature}'


def _verify_state(state: str) -> dict | None:
    """Return the state payload, or None when it is forged or expired.

    The signature covers the encoded payload rather than the raw JSON so it can
    be checked before anything is decoded.
    """
    encoded, _, signature = state.rpartition('.')
    if not encoded or not signature:
        return None

    expected = base64.urlsafe_b64encode(
        hmac.new(_get_state_secret(), encoded.encode(), hashlib.sha256).digest()
    )
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    if not hmac.compare_digest(expected, signature.encode()):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
    except (json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None

    if not isinstance(payload, dict):
        return None

    expires_at = payload.get('exp')
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        return None

    return payload


def _build_state(redirect_uri: str, state: str, **extra) -> str:
    """Pack everything the callback needs to recover into one signed state value."""
    return _sign_state({'redirect_uri': redirect_uri, 'state': state, **extra})


def _is_device_id(value: str) -> bool:
    """Whether the Auth0 action will honor this as a client-supplied device id."""
    return bool(_DEVICE_ID_PATTERN.match(value.strip()))


def _client_device_id(scope: str) -> str | None:
    """The first `device:` token if the Auth0 action would accept it; the action
    reads only the first, so a usable one behind an unusable one does not count.
    """
    first = next((s for s in scope.split() if s.startswith('device:')), None)
    if first is None:
        return None
    candidate = first.removeprefix('device:').strip()
    return candidate if _is_device_id(candidate) else None


def _strip_device_scopes(scope: str) -> str:
    """The scope without any `device:` token, so a client's cannot outrank ours."""
    return ' '.join(s for s in scope.split() if not s.startswith('device:'))


def _mint_device_id() -> str:
    """One id per grant; 32 hex characters clear the Auth0 action's validator."""
    return secrets.token_hex(16)


def _seal(kind: str, value: str, device_id: str) -> str:
    """Bind a value the client echoes back opaquely to its grant's device id.

    Codes and refresh tokens are the only carrier for the id without server-side
    storage; the signature keeps a client from pointing one at another grant's
    record.
    """
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {'k': kind, 'v': value, 'd': device_id}, separators=(',', ':')
        ).encode()
    ).decode()
    signed = f'{_SEALED_PREFIX}.{encoded}'
    signature = base64.urlsafe_b64encode(
        hmac.new(_get_grant_secret(), signed.encode(), hashlib.sha256).digest()
    ).decode()
    return f'{signed}.{signature}'


def _unseal(kind: str, sealed: object) -> tuple[str, str] | None:
    """(value, device_id), or None unless this server sealed it as `kind`, so a
    code cannot be replayed as a refresh token.
    """
    prefix = f'{_SEALED_PREFIX}.'
    if not isinstance(sealed, str) or not sealed.startswith(prefix):
        return None
    signed, _, signature = sealed.rpartition('.')
    expected = base64.urlsafe_b64encode(
        hmac.new(_get_grant_secret(), signed.encode(), hashlib.sha256).digest()
    )
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    if not hmac.compare_digest(expected, signature.encode()):
        return None
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(signed.removeprefix(prefix).encode()).decode()
        )
    except (json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None
    if not isinstance(payload, dict) or payload.get('k') != kind:
        return None
    value = payload.get('v')
    device_id = payload.get('d')
    if not isinstance(value, str) or not value:
        return None
    if not isinstance(device_id, str) or not _is_device_id(device_id):
        return None
    return value, device_id


def _seal_code(code: str, device_id: str) -> str:
    return _seal(_SEAL_KIND_CODE, code, device_id)


def _unseal_code(sealed: object) -> tuple[str, str] | None:
    return _unseal(_SEAL_KIND_CODE, sealed)


def _seal_refresh_token(refresh_token: str, device_id: str) -> str:
    return _seal(_SEAL_KIND_REFRESH, refresh_token, device_id)


def _unseal_refresh_token(sealed: object) -> tuple[str, str] | None:
    return _unseal(_SEAL_KIND_REFRESH, sealed)


def _log_unsealed_rejection(what: str, value: object) -> None:
    """Log a value this server did not seal, before it is rejected.

    One under our prefix that fails to verify is tampering or corruption and
    worth a warning; a bare one is a session from before sealing, which every
    client hits once at rollout, or an Auth0 token handed to the proxy directly.
    """
    if isinstance(value, str) and value.startswith(f'{_SEALED_PREFIX}.'):
        logger.warning('Rejected a %s that failed seal verification', what)
    else:
        logger.info('Rejected an unsealed %s', what)


def _new_nonce() -> str:
    """Mint the per-flow value that proves a callback reached the same browser."""
    return secrets.token_urlsafe(32)


def _hash_nonce(nonce: str) -> str:
    """State travels through URLs and proxy logs, so it carries only the hash."""
    return base64.urlsafe_b64encode(hashlib.sha256(nonce.encode()).digest()).decode()


def _set_nonce_cookie(response: Response, nonce: str) -> None:
    response.set_cookie(
        _NONCE_COOKIE_NAME, nonce, max_age=_STATE_TTL_SECONDS, **_NONCE_COOKIE_ATTRS
    )


def _nonce_cookie_matches(request: Request, state_data: dict) -> bool:
    """Fail closed: a state with no binding, or a browser with no cookie, is a no."""
    expected = state_data.get('nonce_hash')
    nonce = request.cookies.get(_NONCE_COOKIE_NAME, '')
    if not isinstance(expected, str) or not expected or not nonce:
        return False
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
    return hmac.compare_digest(expected.encode(), _hash_nonce(nonce).encode())


def _clear_nonce_cookie(response: Response) -> None:
    response.delete_cookie(_NONCE_COOKIE_NAME, **_NONCE_COOKIE_ATTRS)


def _get_allowed_redirect_domains() -> tuple[str, ...]:
    """Allowed non-loopback redirect hosts.

    ALLOWED_REDIRECT_DOMAINS (comma-separated) when set, else the built-in list.
    """
    env_domains = os.getenv(_ENV_ALLOWED_REDIRECT_DOMAINS, '').strip()
    if env_domains:
        return tuple(d.strip().lower() for d in env_domains.split(',') if d.strip())
    return _DEFAULT_REDIRECT_DOMAINS


def _get_allowed_redirect_uris() -> tuple[str, ...]:
    """Allowed non-loopback callback endpoints.

    ALLOWED_REDIRECT_URIS (comma-separated full URIs) when set, else the built-in
    list.
    """
    env_uris = os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip()
    if env_uris:
        return tuple(u.strip() for u in env_uris.split(',') if u.strip())
    return _DEFAULT_REDIRECT_URIS


def _redirect_uris_are_overridden() -> bool:
    return bool(os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip())


def _redirect_uri_report_only() -> bool:
    """Escape hatch: recover from a missing allowlist entry without a code change."""
    return os.getenv(_ENV_REDIRECT_URI_REPORT_ONLY, '').lower() == 'true'


def _is_allowed_redirect_host(url: str) -> bool:
    """Whether the URL's host clears the legacy host allowlist.

    https only, so an authorization code never travels over plaintext. Not
    sufficient on its own; see _check_redirect_uri.
    """
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        return False

    return (parsed.hostname or '') in _get_allowed_redirect_domains()


def _is_exact_allowed_redirect_uri(url: str) -> bool:
    """Return True when the URL is one of the allowed callback endpoints.

    https only: a pinned endpoint bypasses the host allowlist, so the scheme
    check that keeps authorization codes off plaintext lives here too.
    """
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment:
        return False

    if url in _get_allowed_redirect_uris():
        return True

    # An override is the whole allowlist: the built-in patterns go out with the
    # built-in URIs, so narrowing the list cannot leave one behind.
    if _redirect_uris_are_overridden():
        return False

    return any(pattern.match(url) for pattern in _DEFAULT_REDIRECT_URI_PATTERNS)


def _is_pkce_exempt_redirect_uri(url: str) -> bool:
    """Whether a destination may start an authorization flow with no PKCE.

    Goes through _is_exact_allowed_redirect_uri, not _check_redirect_uri: the
    latter accepts any path on an allowlisted host in report-only mode, which
    would let an unrelated environment variable widen the exemption.
    """
    return url in _PKCE_EXEMPT_REDIRECT_URIS and _is_exact_allowed_redirect_uri(url)


def _check_redirect_uri(url: str) -> bool:
    """Decide whether a client redirect_uri may receive an authorization code.

    Loopback is exempt: callback paths differ per client (/callback,
    /oauth/callback, /) and pinning them would break clients without closing
    the local-listener risk, which browser-session binding handles instead.
    """
    # A pinned endpoint is stricter than a host match, so it stands on its own;
    # otherwise every listed host would also have to be in the domain list.
    if _is_exact_allowed_redirect_uri(url):
        return True

    parsed = urlparse(url)
    if (parsed.hostname or '') in _ALLOWED_LOOPBACK_HOSTS:
        return parsed.scheme in ('http', 'https')

    if not _is_allowed_redirect_host(url):
        return False

    if _redirect_uri_report_only():
        logger.warning(
            'redirect_uri is outside the endpoint allowlist and is allowed only '
            'because report-only mode is on: %s',
            _escape_for_log(url),
        )
        return True

    logger.warning(
        'Rejected redirect_uri outside the endpoint allowlist: %s',
        _escape_for_log(url),
    )
    return False


def _is_registrable_uri_list(value: object) -> bool:
    """Whether redirect_uris has the shape RFC 7591 asks for, at a length we accept."""
    return (
        isinstance(value, list)
        and 1 <= len(value) <= _MAX_REGISTERED_REDIRECT_URIS
        and all(isinstance(uri, str) and uri for uri in value)
    )


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


def _oauth_error(
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
        response = _oauth_error(exc.error, exc.description, status=exc.status)
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


# RFC 8414 metadata is public and carries no credentials. Decorating covers the
# 500 path too, so a misconfiguration reads as an error, not a CORS failure.
@_allow_browser_clients
async def oauth_metadata(request):
    """RFC 8414 metadata naming this server as the authorization server.

    authorize, token and register proxy to Auth0; only jwks_uri points at Auth0
    directly.
    """
    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    server_url = _get_server_url(request)

    metadata = {
        'issuer': f'{server_url}/',
        'authorization_endpoint': f'{server_url}{_AUTHORIZE_PATH}',
        'token_endpoint': f'{server_url}{_TOKEN_PATH}',
        'registration_endpoint': f'{server_url}{_REGISTER_PATH}',
        'jwks_uri': f'{config["auth0_base_url"]}/.well-known/jwks.json',
        'response_types_supported': [_RESPONSE_TYPE_CODE],
        'grant_types_supported': list(_ALLOWED_GRANT_TYPES),
        'token_endpoint_auth_methods_supported': [
            'none',
        ],
        'scopes_supported': list(_DEFAULT_SCOPES),
        'code_challenge_methods_supported': [_PKCE_CHALLENGE_METHOD],
    }

    return JSONResponse(
        metadata,
        headers={'Cache-Control': f'public, max-age={_METADATA_CACHE_SECONDS}'},
    )


def _log_authorize_client_profile(
    redirect_uri: str, code_challenge_method: str
) -> None:
    """Record what each client sends, to settle who reaches the exempt callback.

    Remove once no client uses the PKCE-exempt redirect_uri and no deployment
    needs report-only mode to cover a missing allowlist entry.
    """
    logger.info(
        'authorize observed - redirect_uri: %s, pkce: %s',
        _escape_for_log(redirect_uri) or '(none)',
        _escape_for_log(code_challenge_method) or 'none',
    )


def _normalize_authorize_params(request: Request, config: dict) -> tuple[dict, bool]:
    """Build the outbound Auth0 params and detect the MFA re-auth pseudo-scope.

    client_id is forced so the endpoint cannot proxy an arbitrary Auth0 client, and
    offline_access is added so Auth0 issues a refresh token. The scope leaves with
    exactly one `device:` token, the first being what the Auth0 action reads, so the
    callback can seal the code under this grant. The `mfa` pseudo-scope the 401
    middleware asks for is detected and stripped.
    """
    params = dict(request.query_params)
    params['client_id'] = config['client_id']
    if 'audience' not in params:
        params['audience'] = config['audience']
    if 'response_type' not in params:
        params['response_type'] = _RESPONSE_TYPE_CODE

    scope = params.get('scope', '')
    if _OFFLINE_ACCESS_SCOPE not in scope:
        scope = f'{scope} {_OFFLINE_ACCESS_SCOPE}'.strip()
    device_id = _client_device_id(scope) or _mint_device_id()
    scope = f'{_strip_device_scopes(scope)} device:{device_id}'.strip()

    scope_parts = scope.split()
    mfa_requested = 'mfa' in scope_parts
    if mfa_requested:
        scope = ' '.join(s for s in scope_parts if s != 'mfa')
        logger.info('MFA scope detected, will use two-stage OAuth flow')
    params['scope'] = scope

    return params, mfa_requested


def _validate_authorize_request(params: dict, client_redirect_uri: str) -> None:
    """Reject a redirect_uri or PKCE setup Auth0 must not receive.

    Only a `_PKCE_EXEMPT_REDIRECT_URIS` destination may start a flow without a
    challenge, since Copilot Studio's gateway cannot send one; every other client
    needs one that clears RFC 7636 and this server's method. With no challenge the
    method is dropped rather than forwarded uninspected.
    """
    if client_redirect_uri and not _check_redirect_uri(client_redirect_uri):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'redirect_uri must be a loopback URL or an allowlisted callback endpoint',
        )

    code_challenge = params.get('code_challenge', '')
    code_challenge_method = params.get('code_challenge_method', '')
    if not code_challenge and not _is_pkce_exempt_redirect_uri(client_redirect_uri):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'code_challenge is required; this server accepts only '
            f'{_PKCE_CHALLENGE_METHOD} PKCE',
        )
    if code_challenge and code_challenge_method != _PKCE_CHALLENGE_METHOD:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            f'code_challenge_method must be {_PKCE_CHALLENGE_METHOD}',
        )
    if code_challenge and not _PKCE_CHALLENGE_PATTERN.match(code_challenge):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'code_challenge must be 43 to 128 characters from the '
            'RFC 7636 unreserved set',
        )
    if not code_challenge:
        params.pop('code_challenge_method', None)


def _build_auth0_redirect(
    config: dict,
    server_url: str,
    params: dict,
    client_redirect_uri: str,
    mfa_requested: bool,
    original_state: str,
) -> RedirectResponse:
    """Sign the state Auth0 will echo back and redirect to it.

    A malformed ALPACON_MCP_STATE_SECRET raises here, on the endpoint an operator
    reaches first, rather than as a bare 500 at the callback. An MFA-requested
    client goes to the MFA audience first (stage 1); the callback continues to the
    regular audience (stage 2), replaying the PKCE and other authorize params
    carried in the state so the exchange succeeds with the client's verifier.
    """
    nonce = _new_nonce()
    nonce_hash = _hash_nonce(nonce)
    device_id = _client_device_id(params['scope'])

    if mfa_requested:
        mfa_params = {
            'response_type': _RESPONSE_TYPE_CODE,
            'client_id': config['client_id'],
            'audience': config['mfa_audience'],
            'redirect_uri': _callback_url(server_url),
            'scope': 'enroll read:authenticators',
        }
        stage2_authorize_params = {
            key: params[key]
            for key in ('code_challenge', 'code_challenge_method', 'nonce', 'resource')
            if key in params
        }
        mfa_params['state'] = _build_state(
            client_redirect_uri,
            original_state,
            stage=_STAGE_MFA,
            original_scope=params['scope'],
            authorize_params=stage2_authorize_params,
            nonce_hash=nonce_hash,
            device_id=device_id,
        )
        auth0_url = _auth0_authorize_url(config, mfa_params)
        logger.info('Stage 1: Redirecting to Auth0 MFA audience for MFA verification')
    else:
        params['redirect_uri'] = _callback_url(server_url)
        params['state'] = _build_state(
            client_redirect_uri,
            original_state,
            nonce_hash=nonce_hash,
            device_id=device_id,
        )
        auth0_url = _auth0_authorize_url(config, params)
        logger.info('Redirecting to Auth0 authorize endpoint')

    response = RedirectResponse(url=auth0_url, status_code=HTTPStatus.FOUND)
    _set_nonce_cookie(response, nonce)
    return response


async def oauth_authorize(request):
    """Redirect to Auth0's authorize endpoint with our client_id and audience."""
    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    params, mfa_requested = _normalize_authorize_params(request, config)
    client_redirect_uri = params.get('redirect_uri', '')
    original_state = params.get('state', '')
    _log_authorize_client_profile(
        client_redirect_uri, params.get('code_challenge_method', '')
    )

    try:
        _validate_authorize_request(params, client_redirect_uri)
    except _OAuthRequestError as e:
        return _reject_response(e)

    try:
        return _build_auth0_redirect(
            config,
            _get_server_url(request),
            params,
            client_redirect_uri,
            mfa_requested,
            original_state,
        )
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )


async def _parse_token_request(request: Request) -> dict:
    """Read and decode the token request body, then validate grant_type.

    grant_type gates the allow-list and the injected client_secret, so it must be
    present; checking it is a str first keeps a JSON body's unhashable value from
    raising on the membership test instead of answering 400.
    """
    body = await _read_bounded_body(request)
    if body is None:
        raise _OAuthRequestError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            _ERROR_INVALID_REQUEST,
            'Request body is too large',
        )
    content_type = request.headers.get('content-type', '')

    if _JSON_CONTENT_TYPE in content_type:
        try:
            params = json.loads(body)
        except json.JSONDecodeError:
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST, _ERROR_INVALID_REQUEST, 'Invalid JSON'
            ) from None
        if not isinstance(params, dict):
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST,
                _ERROR_INVALID_REQUEST,
                'Request body must be a JSON object',
            )
    else:
        try:
            decoded_body = body.decode('utf-8')
        except UnicodeDecodeError:
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST,
                _ERROR_INVALID_REQUEST,
                'Request body must be UTF-8 encoded',
            ) from None
        parsed = parse_qs(decoded_body)
        params = {k: v[0] for k, v in parsed.items()}

    grant_type = params.get('grant_type', '')
    if not isinstance(grant_type, str) or not grant_type:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'grant_type must be a non-empty string',
        )
    if grant_type not in _ALLOWED_GRANT_TYPES:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_UNSUPPORTED_GRANT_TYPE,
            f'Grant type "{grant_type}" is not supported. '
            f'Allowed: {", ".join(sorted(_ALLOWED_GRANT_TYPES))}',
        )
    return params


def _inject_client_credentials(params: dict, config: dict) -> None:
    """Force this endpoint's client_id and secret and drop any client device scope.

    A mismatched client_id would make this a generic credential exchange against the
    injected secret, so it is rejected, not overridden. The `device:` scope is
    stripped so a client-supplied one cannot outrank the sealed id injected after
    unsealing; a non-str scope is dropped, and an empty result drops the key, since
    RFC 6749 reads an absent scope as the grant's own.
    """
    configured_client_id = config['client_id']
    provided_client_id = params.get('client_id')
    if provided_client_id and provided_client_id != configured_client_id:
        logger.warning(
            'Rejected /oauth/token request with mismatched client_id: %s',
            provided_client_id,
        )
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT,
            'client_id is not allowed for this endpoint',
        )
    params['client_id'] = configured_client_id
    params['client_secret'] = config['client_secret']

    scope = params.pop('scope', None)
    if isinstance(scope, str):
        stripped = _strip_device_scopes(scope)
        if stripped:
            params['scope'] = stripped


def _unseal_grant(params: dict) -> str:
    """Unseal the code or refresh_token, binding the exchange to its grant.

    An unsealed value, tampered or issued before sealing, would refresh under a key
    shared by every session of the user, so the client is sent to a fresh login
    instead. A client-supplied device id never reaches Auth0: dropped for the code
    grant, which already sent it in the /authorize scope, and overwritten for the
    refresh grant, which may omit scope.
    """
    grant_type = params['grant_type']
    if grant_type == _GRANT_AUTHORIZATION_CODE:
        raw = params.get('code')
        unsealed = _unseal_code(raw)
        what = 'authorization code'
    else:
        raw = params.get('refresh_token')
        unsealed = _unseal_refresh_token(raw)
        what = 'refresh token'

    if unsealed is None:
        _log_unsealed_rejection(what, raw)
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_GRANT,
            f'The {what} was not issued by this server',
        )

    value, sealed_device_id = unsealed
    if grant_type == _GRANT_AUTHORIZATION_CODE:
        params['code'] = value
        params.pop('device_id', None)
    else:
        params['refresh_token'] = value
        params['device_id'] = sealed_device_id
    return sealed_device_id


async def _exchange_with_auth0(
    config: dict, params: dict, sealed_device_id: str
) -> JSONResponse:
    """POST the token request to Auth0 and reseal any refresh token it returns.

    Every refresh token that leaves here is sealed under the grant's device
    id, or the next refresh loses that binding.
    """
    auth0_token_url = _auth0_token_url(config)
    logger.info(
        'Proxying token request to Auth0 - grant_type: %s, has_refresh_token: %s',
        params.get('grant_type'),
        'refresh_token' in params,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                auth0_token_url,
                data=params,
                headers={'Content-Type': _FORM_CONTENT_TYPE},
            )

        try:
            response_data = response.json()
        except Exception:
            logger.warning(f'Auth0 returned non-JSON response: {response.status_code}')
            response_data = {
                'error': _ERROR_SERVER_ERROR,
                'error_description': 'Auth0 returned unexpected response format',
            }

        if (
            sealed_device_id
            and response.status_code == HTTPStatus.OK
            and isinstance(response_data, dict)
            and isinstance(response_data.get('refresh_token'), str)
        ):
            response_data['refresh_token'] = _seal_refresh_token(
                response_data['refresh_token'], sealed_device_id
            )

        if isinstance(response_data, dict):
            if response.status_code == HTTPStatus.OK:
                logger.debug(
                    'Auth0 token response - grant_type: %s, '
                    'has_access_token: %s, has_refresh_token: %s, '
                    'expires_in: %s',
                    params.get('grant_type'),
                    'access_token' in response_data,
                    'refresh_token' in response_data,
                    response_data.get('expires_in'),
                )
            else:
                logger.warning(
                    'Auth0 token request failed - grant_type: %s, '
                    'status: %s, error: %s',
                    params.get('grant_type'),
                    response.status_code,
                    response_data.get('error', 'unknown'),
                )
        else:
            logger.warning(
                'Auth0 token response is not a dict - grant_type: %s, '
                'status: %s, type: %s',
                params.get('grant_type'),
                response.status_code,
                type(response_data).__name__,
            )

        return JSONResponse(
            response_data,
            status_code=response.status_code,
            headers={
                'Cache-Control': 'no-store',
                'Pragma': 'no-cache',
            },
        )
    except httpx.HTTPError as e:
        logger.error(f'Auth0 token request failed: {e}')
        return _oauth_error(
            _ERROR_SERVER_ERROR,
            'Failed to communicate with Auth0',
            status=HTTPStatus.BAD_GATEWAY,
        )


@_allow_browser_clients
async def oauth_token(request):
    """Proxy the token exchange to Auth0 with the configured client_id and secret."""
    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    try:
        params = await _parse_token_request(request)
        _inject_client_credentials(params, config)
        sealed_device_id = _unseal_grant(params)
    except _OAuthRequestError as e:
        return _reject_response(e)

    # Auth0 requires this to match /authorize's exactly, which always sent one.
    if params.get('grant_type') == _GRANT_AUTHORIZATION_CODE:
        params['redirect_uri'] = _callback_url(_get_server_url(request))

    return await _exchange_with_auth0(config, params, sealed_device_id)


async def _parse_client_metadata(request: Request) -> dict:
    """Read, decode, and shape-check the client metadata body (RFC 7591)."""
    body = await _read_bounded_body(request)
    if body is None:
        raise _OAuthRequestError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            _ERROR_INVALID_CLIENT_METADATA,
            'Request body is too large',
        )
    content_type = request.headers.get('content-type', '')

    if _JSON_CONTENT_TYPE not in content_type:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Content-Type must be application/json',
        )
    if not body:
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'Request body must be a JSON object with client metadata',
        )

    try:
        client_metadata = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'Request body must be valid JSON',
        ) from None
    if not isinstance(client_metadata, dict):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'Client metadata must be a JSON object',
        )
    return client_metadata


def _validate_redirect_uris(metadata: dict) -> None:
    """Reject redirect_uris that are malformed or outside the allowlist.

    The shape check runs first: _check_redirect_uri parses each entry as a
    URL string.
    """
    if 'redirect_uris' not in metadata:
        return
    redirect_uris = metadata['redirect_uris']
    if not _is_registrable_uri_list(redirect_uris):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_CLIENT_METADATA,
            'redirect_uris must be an array of 1 to '
            f'{_MAX_REGISTERED_REDIRECT_URIS} strings',
        )
    if not all(_check_redirect_uri(uri) for uri in redirect_uris):
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REDIRECT_URI,
            'One or more redirect_uris are invalid or not allowed by this server',
        )


@_allow_browser_clients
async def oauth_register(request):
    """Dynamic client registration (RFC 7591).

    Auth0 offers it only on Enterprise plans, so this answers with the pre-
    configured client_id to satisfy the MCP SDK.
    """
    try:
        config = _get_oauth_config()
    except ValueError as e:
        logger.error(f'OAuth config error in /oauth/register: {e}')
        return _oauth_error(
            _ERROR_SERVER_ERROR,
            'OAuth configuration is incomplete',
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    try:
        client_metadata = await _parse_client_metadata(request)
        _validate_redirect_uris(client_metadata)
    except _OAuthRequestError as e:
        return _reject_response(e)

    response_data = {
        'client_id': config['client_id'],
        'token_endpoint_auth_method': 'none',
    }
    # Truthful only because these URIs cleared the check /oauth/authorize applies.
    if 'redirect_uris' in client_metadata:
        response_data['redirect_uris'] = client_metadata['redirect_uris']
    if 'client_name' in client_metadata:
        response_data['client_name'] = client_metadata['client_name']

    logger.info('Dynamic client registration: returning pre-configured client_id')

    return JSONResponse(
        response_data,
        status_code=HTTPStatus.CREATED,
        headers={
            'Cache-Control': 'no-store',
        },
    )


@dataclass
class _CallbackState:
    """The authorize-time context recovered from a callback's signed state."""

    client_redirect_uri: str = ''
    original_state: str = ''
    stage: str = ''
    original_scope: str = ''
    nonce_hash: str = ''
    device_id: str = ''
    authorize_params: dict = field(default_factory=dict)


def _restore_callback_state(request: Request) -> _CallbackState:
    """Recover the authorize-time context from the signed state, or reject it.

    An absent state is not rejected: an Auth0 error callback may arrive without one,
    and it names no redirect target a forgery could steer. The nonce-cookie check
    runs before the caller looks at `error` so the gate lives in one place. A state
    without a device id is rejected, since the code could never be sealed. The
    redirect_uri in the state is re-checked as defense in depth: a forged state
    could name our callback directly.
    """
    composite_state = request.query_params.get('state')
    state = _CallbackState()
    if not composite_state:
        return state

    try:
        state_data = _verify_state(composite_state)
    except ValueError as e:
        raise _OAuthRequestError(HTTPStatus.INTERNAL_SERVER_ERROR, str(e)) from e
    if state_data is None:
        logger.warning('Callback rejected an invalid or expired state')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Invalid or expired state parameter',
        )
    if not _nonce_cookie_matches(request, state_data):
        logger.warning('Callback rejected a state not bound to this browser')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Invalid or expired state parameter',
        )

    state.client_redirect_uri = state_data.get('redirect_uri', '')
    state.original_state = state_data.get('state', '')
    state.stage = state_data.get('stage', '')
    state.original_scope = state_data.get('original_scope', '')
    state.nonce_hash = state_data.get('nonce_hash', '')
    state.authorize_params = state_data.get('authorize_params', {})
    state.device_id = state_data.get('device_id', '')
    if not isinstance(state.device_id, str) or not _is_device_id(state.device_id):
        logger.warning('Callback rejected a state without a device id')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST,
            _ERROR_INVALID_REQUEST,
            'Invalid or expired state parameter',
        )

    if state.client_redirect_uri and not _check_redirect_uri(state.client_redirect_uri):
        logger.warning(
            'Callback rejected untrusted redirect_uri from state: %s',
            _escape_for_log(state.client_redirect_uri),
        )
        state.client_redirect_uri = ''

    return state


def _forward_auth0_error(
    client_redirect_uri: str, original_state: str, error: str, error_description: str
) -> Response:
    """Relay an Auth0-reported error to the client, or answer it directly."""
    logger.warning(f'Auth0 callback error: {error} - {error_description}')
    if client_redirect_uri:
        params = {'error': error, 'error_description': error_description or ''}
        if original_state:
            params['state'] = original_state
        return RedirectResponse(
            url=_build_redirect_url(client_redirect_uri, params),
            status_code=HTTPStatus.FOUND,
        )
    return _oauth_error(error, error_description)


async def _handle_mfa_stage1(request: Request, state: _CallbackState) -> Response:
    """Confirm MFA in the Auth0 session, then redirect to the regular audience.

    The MFA code is exchanged only for its effect on the Auth0 SSO session; the
    token is discarded, so every failure here is logged, not surfaced. Stage 1
    client params are replayed into stage 2 only from a dict-shaped, allow-listed
    set, so a forged state cannot inject params. Stage 2 restarts the state's
    expiry, so the nonce cookie is re-set to match.
    """
    logger.info(
        'Stage 1 complete: MFA authorization code received, '
        'exchanging and proceeding to Stage 2 (regular audience)'
    )

    try:
        config = _get_oauth_config()
    except ValueError as e:
        return JSONResponse(
            {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    server_url = _get_server_url(request)
    code = request.query_params.get('code')

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            mfa_response = await client.post(
                _auth0_token_url(config),
                data={
                    'grant_type': _GRANT_AUTHORIZATION_CODE,
                    'code': code,
                    'redirect_uri': _callback_url(server_url),
                    'client_id': config['client_id'],
                    'client_secret': config['client_secret'],
                },
                headers={'Content-Type': _FORM_CONTENT_TYPE},
            )
            if mfa_response.status_code >= HTTPStatus.BAD_REQUEST:
                logger.warning(
                    'MFA token exchange returned %s (non-fatal): %s',
                    mfa_response.status_code,
                    mfa_response.text[:200],
                )
            else:
                logger.info('MFA token exchange succeeded (token discarded)')
    except httpx.HTTPError as e:
        logger.warning(f'MFA token exchange failed (non-fatal): {e}')

    stage2_params = {
        'response_type': _RESPONSE_TYPE_CODE,
        'client_id': config['client_id'],
        'audience': config['audience'],
        'redirect_uri': _callback_url(server_url),
        'scope': state.original_scope or ' '.join(_DEFAULT_SCOPES),
        'state': _build_state(
            state.client_redirect_uri,
            state.original_state,
            stage=_STAGE_REGULAR,
            nonce_hash=state.nonce_hash,
            device_id=state.device_id,
        ),
    }
    _ALLOWED_REPLAY_KEYS = {
        'code_challenge',
        'code_challenge_method',
        'nonce',
        'resource',
    }
    if isinstance(state.authorize_params, dict):
        for key, value in state.authorize_params.items():
            if key in _ALLOWED_REPLAY_KEYS and isinstance(value, str):
                stage2_params[key] = value

    auth0_url = _auth0_authorize_url(config, stage2_params)
    logger.info('Stage 2: Redirecting to Auth0 regular audience (SSO)')
    response = RedirectResponse(url=auth0_url, status_code=HTTPStatus.FOUND)
    _set_nonce_cookie(response, request.cookies[_NONCE_COOKIE_NAME])
    return response


def _deliver_code(code: str, state: _CallbackState) -> Response:
    """Seal the code to this grant's device id and hand it back to the client.

    A code that arrived without a state has no device id to seal under and would die
    at the token exchange, so it is rejected here.
    """
    if not _is_device_id(state.device_id):
        logger.warning('Callback rejected a code that arrived without a state')
        raise _OAuthRequestError(
            HTTPStatus.BAD_REQUEST, _ERROR_INVALID_REQUEST, 'Missing state parameter'
        )
    try:
        sealed_code = _seal_code(code, state.device_id)
    except ValueError as e:
        raise _OAuthRequestError(HTTPStatus.INTERNAL_SERVER_ERROR, str(e)) from e

    if state.client_redirect_uri:
        params = {'code': sealed_code}
        if state.original_state:
            params['state'] = state.original_state
        response = RedirectResponse(
            url=_build_redirect_url(state.client_redirect_uri, params),
            status_code=HTTPStatus.FOUND,
        )
        _clear_nonce_cookie(response)
        return response

    result = {'code': sealed_code}
    if state.original_state:
        result['state'] = state.original_state
    response = JSONResponse(result)
    _clear_nonce_cookie(response)
    return response


async def oauth_callback(request):
    """Handle the Auth0 callback.

    In the MFA stage, exchange the code and redirect to the regular audience;
    otherwise forward the code to the MCP client.
    """
    code = request.query_params.get('code')
    error = request.query_params.get('error')
    error_description = request.query_params.get('error_description')

    try:
        state = _restore_callback_state(request)

        if error:
            return _forward_auth0_error(
                state.client_redirect_uri,
                state.original_state,
                error,
                error_description,
            )
        if not code:
            raise _OAuthRequestError(
                HTTPStatus.BAD_REQUEST,
                _ERROR_INVALID_REQUEST,
                'Missing authorization code',
            )

        if state.stage == _STAGE_MFA:
            return await _handle_mfa_stage1(request, state)

        logger.info('Auth0 callback received authorization code')
        return _deliver_code(code, state)
    except _OAuthRequestError as e:
        return _reject_response(e)


async def oauth_token_fallback(request):
    """Fallback token endpoint at /token.

    MCP SDK clients fall back to /token when the metadata is not cached, e.g. after
    a restart that kept a refresh_token; delegating avoids a silent 404.
    """
    if request.method != 'OPTIONS':
        logger.info('/token fallback hit — delegating to /oauth/token handler')
    return await oauth_token(request)


async def oauth_authorize_fallback(request):
    """Fallback at /authorize for MCP SDK clients without cached metadata."""
    logger.info('/authorize fallback hit — delegating to /oauth/authorize handler')
    return await oauth_authorize(request)


async def oauth_register_fallback(request):
    """Fallback at /register for MCP SDK clients without cached metadata."""
    if request.method != 'OPTIONS':
        logger.info('/register fallback hit — delegating to /oauth/register handler')
    return await oauth_register(request)


def register_oauth_routes(mcp_server):
    """Register the OAuth proxy routes on the FastMCP server.

    Raises ValueError when ALPACON_MCP_STATE_SECRET or ALPACON_MCP_GRANT_SECRET is
    set to a malformed value.
    """
    # A malformed key would otherwise surface on the first user's OAuth request,
    # long after the deployment reported success. Only explicit keys are checked:
    # deriving one needs OAuth config, and deployments without it must keep
    # starting.
    if os.getenv(_STATE_SECRET_ENV):
        _get_state_secret()
    if os.getenv(_GRANT_SECRET_ENV):
        _get_grant_secret()

    for path, methods, handler in (
        (_METADATA_PATH, ['GET'], oauth_metadata),
        (_AUTHORIZE_PATH, ['GET'], oauth_authorize),
        (_TOKEN_PATH, ['POST', 'OPTIONS'], oauth_token),
        (_REGISTER_PATH, ['POST', 'OPTIONS'], oauth_register),
        (_CALLBACK_PATH, ['GET'], oauth_callback),
        ('/token', ['POST', 'OPTIONS'], oauth_token_fallback),
        ('/authorize', ['GET'], oauth_authorize_fallback),
        ('/register', ['POST', 'OPTIONS'], oauth_register_fallback),
    ):
        mcp_server.custom_route(path, methods=methods)(handler)

    # Report-only mode is what makes the domain list meaningful on its own, so
    # a deployment running it is configured, not misconfigured.
    domains_only = (
        os.getenv(_ENV_ALLOWED_REDIRECT_DOMAINS, '').strip()
        and not _redirect_uris_are_overridden()
        and not _redirect_uri_report_only()
    )
    if domains_only:
        logger.warning(
            'ALLOWED_REDIRECT_DOMAINS is set but ALLOWED_REDIRECT_URIS is not; '
            'those hosts are being rejected. List their full callback URIs in '
            'ALLOWED_REDIRECT_URIS, or set ALPACON_MCP_REDIRECT_URI_REPORT_ONLY=true '
            'to fall back to logging only'
        )

    logger.info(
        'OAuth proxy routes registered (including /token, /authorize, '
        '/register fallbacks) - state secret: %s, grant secret: %s',
        'explicit env'
        if os.getenv(_STATE_SECRET_ENV)
        else 'derived from client secret',
        'explicit env'
        if os.getenv(_GRANT_SECRET_ENV)
        else 'derived from client secret',
    )
