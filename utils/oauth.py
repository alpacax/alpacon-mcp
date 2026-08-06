"""OAuth 2.0 proxy endpoints for Auth0 integration.

These endpoints allow MCP clients (e.g. claude.ai) to perform
OAuth authorization code flow through this MCP server, which
proxies requests to Auth0.

All routes are registered via FastMCP's custom_route decorator,
which bypasses MCP authentication — appropriate for OAuth flow endpoints.
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
from functools import wraps
from http import HTTPStatus
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from utils.logger import get_logger

logger = get_logger('oauth')


# Explicit state signing key; when unset, the key is derived from the client secret.
_STATE_SECRET_ENV = 'ALPACON_MCP_STATE_SECRET'

# Stage tags carried through the state in the two-stage MFA flow.
_STAGE_MFA = 'mfa'
_STAGE_REGULAR = 'regular'

# Domain-separates the state key from other keys derived from the client secret.
_STATE_SECRET_INFO = b'alpacon-mcp-oauth-state-v1'

# Matches the 32 bytes the derived key always has, so an explicit key cannot be
# weaker than leaving the variable unset.
_STATE_SECRET_MIN_BYTES = 32

# Covers an Auth0 login plus MFA; keeps a leaked state only briefly usable.
_STATE_TTL_SECONDS = 600

# The __Host- prefix makes the browser itself require Secure, Path=/ and no
# Domain, so the cookie cannot be planted by a sibling host.
_NONCE_COOKIE_NAME = '__Host-alpacon_oauth_nonce'

# Shared by set and delete: the delete has to repeat Path, or it addresses a
# different cookie, and Secure, or the browser rejects the whole Set-Cookie
# under a __Host- name and the cookie survives. SameSite stays Lax because
# Strict drops the cookie on the top-level return from Auth0.
_NONCE_COOKIE_ATTRS = {
    'path': '/',
    'secure': True,
    'httponly': True,
    'samesite': 'lax',
}

_ALLOWED_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')

# Caps a client-supplied value in a log line. Escaping expands a byte up to
# sixfold, so an unbounded value on an unauthenticated route inflates log volume.
_LOG_VALUE_MAX_CHARS = 512

# A real client registers one or two callbacks. The cap keeps one unauthenticated
# registration from driving a check — and in report-only mode a warning — per entry.
_MAX_REGISTERED_REDIRECT_URIS = 20

# Sent on the preflight for the two endpoints a browser-based client posts to.
# Allow-Credentials stays unset: with it, a wildcard origin would let any page
# ride the user's ambient cookies, and neither endpoint reads a cookie anyway.
_CORS_PREFLIGHT_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Max-Age': '3600',
}

_ENV_ALLOWED_REDIRECT_DOMAINS = 'ALLOWED_REDIRECT_DOMAINS'
_ENV_ALLOWED_REDIRECT_URIS = 'ALLOWED_REDIRECT_URIS'
_ENV_REDIRECT_URI_REPORT_ONLY = 'ALPACON_MCP_REDIRECT_URI_REPORT_ONLY'

# Trusting a whole domain lets an authorization code land on any path an
# attacker can influence there, so each entry pins one callback endpoint.
_DEFAULT_REDIRECT_URIS = (
    # Anthropic — hosted surfaces (web, Desktop, mobile, Cowork)
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
    # OpenAI — legacy connector callback, still served for published apps
    'https://chatgpt.com/connector_platform_oauth_redirect',
    # Cursor — web and Cursor Agents
    'https://www.cursor.com/agents/mcp/oauth/callback',
    # VS Code / GitHub Copilot — web
    'https://vscode.dev/redirect/',
    'https://antigravity.google/oauth-callback',
    # Microsoft Copilot Studio, via the Power Platform connector gateway
    'https://global.consent.azure-apim.net/redirect',
)

# OpenAI issues one opaque callback id per connector, so the last segment
# cannot be pinned. The character class excludes "/" so no deeper path matches,
# and \Z rather than $ so a trailing newline cannot ride along.
_DEFAULT_REDIRECT_URI_PATTERNS = (
    re.compile(r'^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,64}\Z'),
)

# Hosts report-only mode may fall back to, derived from the endpoint list so a
# client whose endpoint moves stays covered without a second edit.
# chat.openai.com has no endpoint entry and stays as the legacy OpenAI host.
# Override via ALLOWED_REDIRECT_DOMAINS (comma-separated).
_DEFAULT_REDIRECT_DOMAINS = tuple(
    sorted(
        {host for uri in _DEFAULT_REDIRECT_URIS if (host := urlparse(uri).hostname)}
        | {'chat.openai.com'}
    )
)


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


def _get_server_url(request) -> str:
    """Build the MCP server's base URL from config or request.

    Prefers ALPACON_MCP_RESOURCE_URL env var to avoid relying on
    potentially spoofable forwarding headers.
    """
    configured_base_url = os.getenv('ALPACON_MCP_RESOURCE_URL')
    if configured_base_url:
        return configured_base_url.rstrip('/')
    return f'{request.url.scheme}://{request.url.netloc}'


def _get_allowed_redirect_domains() -> tuple[str, ...]:
    """Return the set of allowed non-localhost redirect domains.

    Reads from ALLOWED_REDIRECT_DOMAINS env var (comma-separated).
    Falls back to _DEFAULT_REDIRECT_DOMAINS if not set.
    """
    env_domains = os.getenv(_ENV_ALLOWED_REDIRECT_DOMAINS, '').strip()
    if env_domains:
        return tuple(d.strip().lower() for d in env_domains.split(',') if d.strip())
    return _DEFAULT_REDIRECT_DOMAINS


def _get_allowed_redirect_uris() -> tuple[str, ...]:
    """Return the allowed non-loopback callback endpoints.

    Reads ALLOWED_REDIRECT_URIS (comma-separated full URIs) when set.
    """
    env_uris = os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip()
    if env_uris:
        return tuple(u.strip() for u in env_uris.split(',') if u.strip())
    return _DEFAULT_REDIRECT_URIS


def _redirect_uris_are_overridden() -> bool:
    return bool(os.getenv(_ENV_ALLOWED_REDIRECT_URIS, '').strip())


def _is_allowed_redirect_host(url: str) -> bool:
    """Whether the URL's host clears the legacy host allowlist.

    https only, so an authorization code never travels over plaintext.
    Clearing this check is not sufficient on its own — see _check_redirect_uri.
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


def _redirect_uri_report_only() -> bool:
    """Escape hatch: recover from a missing allowlist entry without a code change."""
    return os.getenv(_ENV_REDIRECT_URI_REPORT_ONLY, '').lower() == 'true'


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


def _allow_browser_clients(handler):
    """Answer the CORS preflight and mark the response readable cross-origin.

    Only for endpoints a browser-based client reaches with fetch: /oauth/authorize
    and /oauth/callback are top-level navigations, which CORS never governs.
    Starlette ships CORSMiddleware, but custom_route takes no per-route middleware
    and installing it app-wide would also open the MCP transport endpoint.
    """

    @wraps(handler)
    async def with_cors(request: Request) -> Response:
        if request.method == 'OPTIONS':
            return Response(status_code=204, headers=_CORS_PREFLIGHT_HEADERS)

        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    return with_cors


def _log_authorize_client_profile(
    redirect_uri: str, code_challenge_method: str
) -> None:
    """Record what each client sends, to settle the allowlist and PKCE questions.

    Remove once PKCE is required and no deployment still needs report-only mode
    to cover a missing allowlist entry.
    """
    logger.info(
        'authorize observed - redirect_uri: %s, pkce: %s',
        _escape_for_log(redirect_uri) or '(none)',
        _escape_for_log(code_challenge_method) or 'none',
    )


def _build_redirect_url(base_url: str, extra_params: dict) -> str:
    """Safely merge query params into a URL, preserving existing params."""
    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    merged = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
    merged.update(extra_params)
    new_query = urlencode(merged, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _get_oauth_config() -> dict[str, str]:
    """Get OAuth configuration from environment variables."""
    domain = os.getenv('AUTH0_DOMAIN', '')
    client_id = os.getenv('AUTH0_CLIENT_ID', '')
    client_secret = os.getenv('AUTH0_CLIENT_SECRET', '')
    audience = os.getenv('AUTH0_AUDIENCE', 'https://alpacon.io/access/')
    mfa_audience = os.getenv('AUTH0_MFA_AUDIENCE', '')

    if not domain:
        raise ValueError('AUTH0_DOMAIN environment variable is required')
    if not client_id:
        raise ValueError('AUTH0_CLIENT_ID environment variable is required')
    if not client_secret:
        raise ValueError('AUTH0_CLIENT_SECRET environment variable is required')

    # Derive MFA audience from domain if not explicitly set
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


def _get_state_secret() -> bytes:
    """Falls back to deriving from AUTH0_CLIENT_SECRET so no extra secret needs
    provisioning; the derived key is identical across replicas, so state
    verifies without shared server-side storage.
    """
    explicit = os.getenv(_STATE_SECRET_ENV, '')
    if explicit:
        # The state travels in URLs and proxy logs, so the key is an offline
        # brute-force target; hex-only input keeps a typed passphrase out.
        try:
            key = bytes.fromhex(explicit)
        except ValueError:
            raise ValueError(
                f'{_STATE_SECRET_ENV} must be hex; '
                f'generate one with openssl rand -hex {_STATE_SECRET_MIN_BYTES}'
            ) from None
        if len(key) < _STATE_SECRET_MIN_BYTES:
            raise ValueError(
                f'{_STATE_SECRET_ENV} must decode to at least '
                f'{_STATE_SECRET_MIN_BYTES} bytes'
            )
        return key

    client_secret = _get_oauth_config()['client_secret']
    return hmac.new(client_secret.encode(), _STATE_SECRET_INFO, hashlib.sha256).digest()


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


def register_oauth_routes(mcp_server):
    """Register OAuth proxy routes on the FastMCP server.

    Args:
        mcp_server: FastMCP server instance
    """

    # RFC 8414 metadata is public and carries no credentials. Decorating covers
    # the 500 path too, so a misconfiguration is readable rather than a CORS error.
    @mcp_server.custom_route('/.well-known/oauth-authorization-server', methods=['GET'])
    @_allow_browser_clients
    async def oauth_metadata(request):
        """OAuth 2.0 Authorization Server Metadata (RFC 8414).

        Returns metadata advertising this MCP server as the OAuth
        authorization server. The authorize, token, and register
        endpoints proxy to Auth0; only jwks_uri points to Auth0 directly.
        """
        try:
            config = _get_oauth_config()
        except ValueError as e:
            return JSONResponse({'error': str(e)}, status_code=500)

        server_url = _get_server_url(request)

        metadata = {
            'issuer': f'{server_url}/',
            'authorization_endpoint': f'{server_url}/oauth/authorize',
            'token_endpoint': f'{server_url}/oauth/token',
            'registration_endpoint': f'{server_url}/oauth/register',
            'jwks_uri': f'{config["auth0_base_url"]}/.well-known/jwks.json',
            'response_types_supported': ['code'],
            'grant_types_supported': [
                'authorization_code',
                'refresh_token',
            ],
            'token_endpoint_auth_methods_supported': [
                'none',
            ],
            'scopes_supported': ['openid', 'profile', 'email', 'offline_access'],
            'code_challenge_methods_supported': ['S256'],
        }

        return JSONResponse(
            metadata,
            headers={'Cache-Control': 'public, max-age=3600'},
        )

    @mcp_server.custom_route('/oauth/authorize', methods=['GET'])
    async def oauth_authorize(request):
        """Redirect to Auth0's authorization endpoint.

        Proxies the OAuth authorize request to Auth0, adding the
        configured client_id and audience.
        """
        try:
            config = _get_oauth_config()
        except ValueError as e:
            return JSONResponse({'error': str(e)}, status_code=500)

        # Forward all query parameters to Auth0
        params = dict(request.query_params)

        # Enforce configured client_id — prevent open proxy for arbitrary clients
        params['client_id'] = config['client_id']

        # Set audience for Alpacon API access
        if 'audience' not in params:
            params['audience'] = config['audience']

        # Ensure response_type is set
        if 'response_type' not in params:
            params['response_type'] = 'code'

        # Ensure offline_access scope is included so Auth0 issues a refresh token.
        # Without this, the MCP client cannot refresh expired access tokens.
        scope = params.get('scope', '')
        if 'offline_access' not in scope:
            scope = f'{scope} offline_access'.strip()

        # Detect MFA pseudo-scope from re-auth flow.
        # When the ASGI middleware returns 401 with scope="... mfa",
        # the MCP client includes 'mfa' in the authorize request scope.
        scope_parts = scope.split()
        mfa_requested = 'mfa' in scope_parts
        if mfa_requested:
            scope = ' '.join(s for s in scope_parts if s != 'mfa')
            logger.info('MFA scope detected, will use two-stage OAuth flow')

        params['scope'] = scope

        # Build MCP server's own callback URL as redirect_uri for Auth0.
        # Store the client's original redirect_uri in the state so we can
        # forward the authorization code back to the client after Auth0 callback.
        server_url = _get_server_url(request)

        # Save client's original redirect_uri to relay the code later.
        client_redirect_uri = params.get('redirect_uri', '')
        _log_authorize_client_profile(
            client_redirect_uri, params.get('code_challenge_method', '')
        )
        if client_redirect_uri and not _check_redirect_uri(client_redirect_uri):
            return JSONResponse(
                {
                    'error': 'invalid_request',
                    'error_description': (
                        'redirect_uri must be a loopback URL or an allowlisted '
                        'callback endpoint'
                    ),
                },
                status_code=400,
            )

        original_state = params.get('state', '')
        nonce = _new_nonce()
        nonce_hash = _hash_nonce(nonce)

        # _build_state signs with the configured key, so a malformed
        # ALPACON_MCP_STATE_SECRET raises here — on the endpoint an operator
        # reaches before the callback. Carry the message instead of a bare 500.
        try:
            if mfa_requested:
                # Two-stage OAuth flow: Stage 1 — redirect to Auth0 MFA audience
                # to force MFA verification. After MFA completion, the callback
                # handler will redirect again to the regular audience (Stage 2).
                mfa_params = {
                    'response_type': 'code',
                    'client_id': config['client_id'],
                    'audience': config['mfa_audience'],
                    'redirect_uri': f'{server_url}/oauth/callback',
                    'scope': 'enroll read:authenticators',
                }

                # Preserve PKCE and other client authorize params for Stage 2.
                # The MCP client's PKCE code_challenge must be replayed when
                # redirecting to the regular audience so the final code exchange
                # succeeds with the client's code_verifier.
                stage2_authorize_params = {}
                for key in (
                    'code_challenge',
                    'code_challenge_method',
                    'nonce',
                    'resource',
                ):
                    if key in params:
                        stage2_authorize_params[key] = params[key]

                mfa_params['state'] = _build_state(
                    client_redirect_uri,
                    original_state,
                    stage=_STAGE_MFA,
                    original_scope=scope,
                    authorize_params=stage2_authorize_params,
                    nonce_hash=nonce_hash,
                )

                auth0_url = (
                    f'{config["auth0_base_url"]}/authorize?{urlencode(mfa_params)}'
                )
                logger.info(
                    'Stage 1: Redirecting to Auth0 MFA audience for MFA verification'
                )
            else:
                # Standard single-stage OAuth flow (no MFA required)
                params['redirect_uri'] = f'{server_url}/oauth/callback'
                params['state'] = _build_state(
                    client_redirect_uri, original_state, nonce_hash=nonce_hash
                )

                auth0_url = f'{config["auth0_base_url"]}/authorize?{urlencode(params)}'
                logger.info('Redirecting to Auth0 authorize endpoint')
        except ValueError as e:
            return JSONResponse(
                {'error': str(e)}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
            )

        response = RedirectResponse(url=auth0_url, status_code=302)
        _set_nonce_cookie(response, nonce)
        return response

    @mcp_server.custom_route('/oauth/token', methods=['POST', 'OPTIONS'])
    @_allow_browser_clients
    async def oauth_token(request):
        """Proxy token exchange to Auth0.

        Forwards the token request to Auth0's /oauth/token endpoint.
        Injects the configured client_id and client_secret for
        Auth0 token exchange (confidential client / RWA).
        """
        try:
            config = _get_oauth_config()
        except ValueError as e:
            return JSONResponse({'error': str(e)}, status_code=500)

        # Parse request body
        body = await request.body()
        content_type = request.headers.get('content-type', '')

        if 'application/json' in content_type:
            try:
                params = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse(
                    {'error': 'invalid_request', 'error_description': 'Invalid JSON'},
                    status_code=400,
                )

            if not isinstance(params, dict):
                return JSONResponse(
                    {
                        'error': 'invalid_request',
                        'error_description': 'Request body must be a JSON object',
                    },
                    status_code=400,
                )
        else:
            # application/x-www-form-urlencoded (standard OAuth)
            try:
                decoded_body = body.decode('utf-8')
            except UnicodeDecodeError:
                return JSONResponse(
                    {
                        'error': 'invalid_request',
                        'error_description': 'Request body must be UTF-8 encoded',
                    },
                    status_code=400,
                )

            parsed = parse_qs(decoded_body)
            params = {k: v[0] for k, v in parsed.items()}

        # Restrict allowed grant types to prevent credential abuse
        allowed_grant_types = {'authorization_code', 'refresh_token'}
        grant_type = params.get('grant_type', '')
        if grant_type and grant_type not in allowed_grant_types:
            return JSONResponse(
                {
                    'error': 'unsupported_grant_type',
                    'error_description': (
                        f'Grant type "{grant_type}" is not supported. '
                        f'Allowed: {", ".join(sorted(allowed_grant_types))}'
                    ),
                },
                status_code=400,
            )

        # Enforce configured client_id to prevent this endpoint from
        # acting as a generic token proxy for arbitrary Auth0 clients.
        configured_client_id = config['client_id']
        provided_client_id = params.get('client_id')
        if provided_client_id and provided_client_id != configured_client_id:
            logger.warning(
                'Rejected /oauth/token request with mismatched client_id: %s',
                provided_client_id,
            )
            return JSONResponse(
                {
                    'error': 'invalid_client',
                    'error_description': 'client_id is not allowed for this endpoint',
                },
                status_code=400,
            )
        params['client_id'] = configured_client_id
        params['client_secret'] = config['client_secret']

        # Override redirect_uri to match what was sent to Auth0 during /authorize.
        # Auth0 requires the redirect_uri in token exchange to match exactly.
        # Always set it for authorization_code grants since /authorize always
        # sends redirect_uri to Auth0.
        if params.get('grant_type') == 'authorization_code':
            server_url = _get_server_url(request)
            params['redirect_uri'] = f'{server_url}/oauth/callback'

        # Forward to Auth0
        auth0_token_url = f'{config["auth0_base_url"]}/oauth/token'
        logger.info(
            'Proxying token request to Auth0 - grant_type: %s, has_refresh_token: %s',
            grant_type,
            'refresh_token' in params,
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    auth0_token_url,
                    data=params,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                )

            try:
                response_data = response.json()
            except Exception:
                logger.warning(
                    f'Auth0 returned non-JSON response: {response.status_code}'
                )
                response_data = {
                    'error': 'server_error',
                    'error_description': 'Auth0 returned unexpected response format',
                }

            # Log token response details for debugging refresh issues
            if isinstance(response_data, dict):
                if response.status_code == 200:
                    has_access = 'access_token' in response_data
                    has_refresh = 'refresh_token' in response_data
                    expires_in = response_data.get('expires_in')
                    logger.debug(
                        'Auth0 token response - grant_type: %s, '
                        'has_access_token: %s, has_refresh_token: %s, '
                        'expires_in: %s',
                        grant_type,
                        has_access,
                        has_refresh,
                        expires_in,
                    )
                else:
                    logger.warning(
                        'Auth0 token request failed - grant_type: %s, '
                        'status: %s, error: %s',
                        grant_type,
                        response.status_code,
                        response_data.get('error', 'unknown'),
                    )
            else:
                logger.warning(
                    'Auth0 token response is not a dict - grant_type: %s, '
                    'status: %s, type: %s',
                    grant_type,
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
            return JSONResponse(
                {
                    'error': 'server_error',
                    'error_description': 'Failed to communicate with Auth0',
                },
                status_code=502,
            )

    @mcp_server.custom_route('/oauth/register', methods=['POST', 'OPTIONS'])
    @_allow_browser_clients
    async def oauth_register(request):
        """Dynamic Client Registration endpoint (RFC 7591).

        Auth0 does not support Dynamic Client Registration on non-Enterprise
        plans, so this endpoint returns the server's pre-configured client_id
        to satisfy the MCP SDK's registration requirement.
        """
        try:
            config = _get_oauth_config()
        except ValueError as e:
            logger.error(f'OAuth config error in /oauth/register: {e}')
            return JSONResponse(
                {
                    'error': 'server_error',
                    'error_description': 'OAuth configuration is incomplete',
                },
                status_code=500,
            )

        # Parse and validate client metadata from request body (RFC 7591)
        body = await request.body()
        content_type = request.headers.get('content-type', '')

        if 'application/json' not in content_type:
            return JSONResponse(
                {
                    'error': 'invalid_request',
                    'error_description': 'Content-Type must be application/json',
                },
                status_code=400,
            )

        if not body:
            return JSONResponse(
                {
                    'error': 'invalid_client_metadata',
                    'error_description': (
                        'Request body must be a JSON object with client metadata'
                    ),
                },
                status_code=400,
            )

        try:
            client_metadata = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                {
                    'error': 'invalid_client_metadata',
                    'error_description': 'Request body must be valid JSON',
                },
                status_code=400,
            )

        if not isinstance(client_metadata, dict):
            return JSONResponse(
                {
                    'error': 'invalid_client_metadata',
                    'error_description': 'Client metadata must be a JSON object',
                },
                status_code=400,
            )

        if 'redirect_uris' in client_metadata:
            redirect_uris = client_metadata['redirect_uris']
            # The shape check comes first: _check_redirect_uri parses a str.
            if not _is_registrable_uri_list(redirect_uris):
                return JSONResponse(
                    {
                        'error': 'invalid_client_metadata',
                        'error_description': (
                            'redirect_uris must be an array of 1 to '
                            f'{_MAX_REGISTERED_REDIRECT_URIS} strings'
                        ),
                    },
                    status_code=400,
                )
            if not all(_check_redirect_uri(uri) for uri in redirect_uris):
                return JSONResponse(
                    {
                        'error': 'invalid_redirect_uri',
                        'error_description': (
                            'One or more redirect_uris are invalid or not allowed '
                            'by this server'
                        ),
                    },
                    status_code=400,
                )

        # Return pre-configured client_id with metadata echoed back
        response_data = {
            'client_id': config['client_id'],
            'token_endpoint_auth_method': 'none',
        }

        # Truthful only because these URIs cleared the check /oauth/authorize applies.
        if 'redirect_uris' in client_metadata:
            response_data['redirect_uris'] = client_metadata['redirect_uris']

        # Echo back client_name if provided
        if 'client_name' in client_metadata:
            response_data['client_name'] = client_metadata['client_name']

        logger.info('Dynamic client registration: returning pre-configured client_id')

        return JSONResponse(
            response_data,
            status_code=201,
            headers={
                'Cache-Control': 'no-store',
            },
        )

    @mcp_server.custom_route('/oauth/callback', methods=['GET'])
    async def oauth_callback(request):
        """Handle Auth0 callback after authorization.

        Supports two-stage MFA flow:
        - Stage 'mfa': MFA completed, exchange code then redirect to
          regular audience (Stage 2) using Auth0 SSO session.
        - Stage 'regular' or absent: forward code to MCP client.
        """
        # Extract callback parameters
        code = request.query_params.get('code')
        composite_state = request.query_params.get('state')
        error = request.query_params.get('error')
        error_description = request.query_params.get('error_description')

        # Decode the composite state to get client's redirect_uri and original state
        client_redirect_uri = ''
        original_state = ''
        stage = ''
        original_scope = ''
        nonce_hash = ''
        authorize_params: dict = {}
        # An absent state is not rejected: Auth0 error callbacks can arrive
        # without one, and it names no redirect target a forgery could steer.
        if composite_state:
            try:
                state_data = _verify_state(composite_state)
            except ValueError as e:
                # Without an explicit state secret, verification needs the OAuth
                # config; surface misconfiguration as the other handlers do.
                return JSONResponse(
                    {'error': str(e)},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            if state_data is None:
                logger.warning('Callback rejected an invalid or expired state')
                return JSONResponse(
                    {
                        'error': 'invalid_request',
                        'error_description': 'Invalid or expired state parameter',
                    },
                    status_code=400,
                )
            # Placed before the error branch so the gate lives in one spot; an
            # error callback carries no code, so nothing is lost by rejecting it.
            if not _nonce_cookie_matches(request, state_data):
                logger.warning('Callback rejected a state not bound to this browser')
                return JSONResponse(
                    {
                        'error': 'invalid_request',
                        'error_description': 'Invalid or expired state parameter',
                    },
                    status_code=400,
                )
            client_redirect_uri = state_data.get('redirect_uri', '')
            original_state = state_data.get('state', '')
            stage = state_data.get('stage', '')
            original_scope = state_data.get('original_scope', '')
            nonce_hash = state_data.get('nonce_hash', '')
            authorize_params = state_data.get('authorize_params', {})

        # Defense-in-depth: re-validate redirect_uri from state is allowed.
        # The authorize endpoint already validates this, but an attacker could craft
        # a composite state directly and hit Auth0 with our callback URL.
        if client_redirect_uri and not _check_redirect_uri(client_redirect_uri):
            logger.warning(
                'Callback rejected untrusted redirect_uri from state: %s',
                _escape_for_log(client_redirect_uri),
            )
            client_redirect_uri = ''

        if error:
            logger.warning(f'Auth0 callback error: {error} - {error_description}')
            if client_redirect_uri:
                params = {'error': error, 'error_description': error_description or ''}
                if original_state:
                    params['state'] = original_state
                return RedirectResponse(
                    url=_build_redirect_url(client_redirect_uri, params),
                    status_code=302,
                )
            return JSONResponse(
                {'error': error, 'error_description': error_description},
                status_code=400,
            )

        if not code:
            return JSONResponse(
                {
                    'error': 'invalid_request',
                    'error_description': 'Missing authorization code',
                },
                status_code=400,
            )

        # --- Two-stage MFA flow: Stage 1 callback ---
        if stage == _STAGE_MFA:
            logger.info(
                'Stage 1 complete: MFA authorization code received, '
                'exchanging and proceeding to Stage 2 (regular audience)'
            )

            try:
                config = _get_oauth_config()
            except ValueError as e:
                return JSONResponse({'error': str(e)}, status_code=500)

            server_url = _get_server_url(request)

            # Exchange the MFA code to confirm MFA was completed.
            # The resulting MFA token is discarded — we only need
            # the side effect of MFA completion in the Auth0 session.
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    mfa_response = await client.post(
                        f'{config["auth0_base_url"]}/oauth/token',
                        data={
                            'grant_type': 'authorization_code',
                            'code': code,
                            'redirect_uri': f'{server_url}/oauth/callback',
                            'client_id': config['client_id'],
                            'client_secret': config['client_secret'],
                        },
                        headers={
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                    )
                    # MFA token is discarded — we only need the side effect
                    # of MFA completion in the Auth0 session. Log non-2xx
                    # responses for debugging misconfiguration.
                    if mfa_response.status_code >= 400:
                        logger.warning(
                            'MFA token exchange returned %s (non-fatal): %s',
                            mfa_response.status_code,
                            mfa_response.text[:200],
                        )
                    else:
                        logger.info('MFA token exchange succeeded (token discarded)')
            except httpx.HTTPError as e:
                logger.warning(f'MFA token exchange failed (non-fatal): {e}')

            # Stage 2: redirect to Auth0 with regular audience.
            # The Auth0 SSO session will skip the login prompt since
            # the user just authenticated (with MFA) moments ago.
            stage2_params = {
                'response_type': 'code',
                'client_id': config['client_id'],
                'audience': config['audience'],
                'redirect_uri': f'{server_url}/oauth/callback',
                'scope': original_scope or 'openid profile email offline_access',
                'state': _build_state(
                    client_redirect_uri,
                    original_state,
                    stage=_STAGE_REGULAR,
                    nonce_hash=nonce_hash,
                ),
            }
            # Replay PKCE and other client params preserved from Stage 1
            # so the final code exchange succeeds with the client's verifier.
            # Validate authorize_params is a dict with only expected keys
            # to prevent forged state from injecting arbitrary params.
            _ALLOWED_REPLAY_KEYS = {
                'code_challenge',
                'code_challenge_method',
                'nonce',
                'resource',
            }
            if isinstance(authorize_params, dict):
                for key, value in authorize_params.items():
                    if key in _ALLOWED_REPLAY_KEYS and isinstance(value, str):
                        stage2_params[key] = value

            auth0_url = (
                f'{config["auth0_base_url"]}/authorize?{urlencode(stage2_params)}'
            )
            logger.info('Stage 2: Redirecting to Auth0 regular audience (SSO)')
            response = RedirectResponse(url=auth0_url, status_code=302)
            # Stage 2 restarts the state expiry; re-set the cookie so the two
            # do not drift apart.
            _set_nonce_cookie(response, request.cookies[_NONCE_COOKIE_NAME])
            return response

        # --- Standard callback (stage 'regular' or absent) ---
        logger.info('Auth0 callback received authorization code')

        # Redirect back to the MCP client's original redirect_uri with the code
        if client_redirect_uri:
            params = {'code': code}
            if original_state:
                params['state'] = original_state
            response = RedirectResponse(
                url=_build_redirect_url(client_redirect_uri, params),
                status_code=302,
            )
            _clear_nonce_cookie(response)
            return response

        # Fallback: return as JSON if no client redirect_uri was found
        result = {'code': code}
        if original_state:
            result['state'] = original_state
        response = JSONResponse(result)
        _clear_nonce_cookie(response)
        return response

    @mcp_server.custom_route('/token', methods=['POST', 'OPTIONS'])
    async def oauth_token_fallback(request):
        """Fallback token endpoint at /token.

        MCP SDK clients fall back to /token (instead of /oauth/token) when
        oauth_metadata is not cached — e.g. after a client restart that
        still has a stored refresh_token but lost the server metadata.
        Delegating to the canonical handler avoids a silent 404.
        """
        if request.method != 'OPTIONS':
            logger.info('/token fallback hit — delegating to /oauth/token handler')
        return await oauth_token(request)

    @mcp_server.custom_route('/authorize', methods=['GET'])
    async def oauth_authorize_fallback(request):
        """Fallback authorize endpoint at /authorize.

        MCP SDK clients fall back to /authorize when oauth_metadata
        is not cached.
        """
        logger.info('/authorize fallback hit — delegating to /oauth/authorize handler')
        return await oauth_authorize(request)

    @mcp_server.custom_route('/register', methods=['POST', 'OPTIONS'])
    async def oauth_register_fallback(request):
        """Fallback register endpoint at /register.

        MCP SDK clients fall back to /register when oauth_metadata
        is not cached.
        """
        if request.method != 'OPTIONS':
            logger.info(
                '/register fallback hit — delegating to /oauth/register handler'
            )
        return await oauth_register(request)

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
        '/register fallbacks) - state secret: %s',
        'explicit env'
        if os.getenv(_STATE_SECRET_ENV)
        else 'derived from client secret',
    )
