"""OAuth 2.0 proxy endpoints for Auth0 integration.

These endpoints allow MCP clients (e.g. claude.ai) to perform
OAuth authorization code flow through this MCP server, which
proxies requests to Auth0.

All routes are registered via FastMCP's custom_route decorator,
which bypasses MCP authentication — appropriate for OAuth flow endpoints.
"""

import base64
import json
import os

import httpx

from utils.logger import get_logger

logger = get_logger('oauth')


_ALLOWED_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')

# Default trusted redirect domains for cloud-based MCP clients (e.g. Claude web, ChatGPT).
# Override via ALLOWED_REDIRECT_DOMAINS env var (comma-separated).
_DEFAULT_REDIRECT_DOMAINS = (
    'claude.ai',
    'chatgpt.com',
    'chat.openai.com',
)


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
    env_domains = os.getenv('ALLOWED_REDIRECT_DOMAINS', '').strip()
    if env_domains:
        return tuple(d.strip().lower() for d in env_domains.split(',') if d.strip())
    return _DEFAULT_REDIRECT_DOMAINS


def _is_allowed_redirect_url(url: str) -> bool:
    """Validate that a redirect URL is allowed.

    Allows localhost URLs (http/https) and trusted redirect domains (https only).
    Non-loopback domains must use https to prevent authorization code leakage
    over plaintext connections.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False

    hostname = parsed.hostname or ''

    # Allow localhost with http or https (for local development)
    if hostname in _ALLOWED_LOOPBACK_HOSTS:
        return True

    # Trusted domains must use https to prevent code leakage via plaintext
    if parsed.scheme != 'https':
        return False

    # Allow trusted redirect domains (exact match)
    allowed_domains = _get_allowed_redirect_domains()
    return hostname in allowed_domains


def _build_redirect_url(base_url: str, extra_params: dict) -> str:
    """Safely merge query params into a URL, preserving existing params."""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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


def register_oauth_routes(mcp_server):
    """Register OAuth proxy routes on the FastMCP server.

    Args:
        mcp_server: FastMCP server instance
    """

    @mcp_server.custom_route('/.well-known/oauth-authorization-server', methods=['GET'])
    async def oauth_metadata(request):
        """OAuth 2.0 Authorization Server Metadata (RFC 8414).

        Returns metadata advertising this MCP server as the OAuth
        authorization server. The authorize, token, and register
        endpoints proxy to Auth0; only jwks_uri points to Auth0 directly.
        """
        from starlette.responses import JSONResponse

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
            headers={
                'Cache-Control': 'public, max-age=3600',
                'Access-Control-Allow-Origin': os.getenv(
                    'ALPACON_MCP_RESOURCE_URL', request.url.netloc
                ),
            },
        )

    @mcp_server.custom_route('/oauth/authorize', methods=['GET'])
    async def oauth_authorize(request):
        """Redirect to Auth0's authorization endpoint.

        Proxies the OAuth authorize request to Auth0, adding the
        configured client_id and audience.
        """
        from urllib.parse import urlencode

        from starlette.responses import RedirectResponse

        try:
            config = _get_oauth_config()
        except ValueError as e:
            from starlette.responses import JSONResponse

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
        # Allow localhost and trusted cloud MCP client domains to prevent
        # open redirect attacks while supporting Claude web, ChatGPT, etc.
        client_redirect_uri = params.get('redirect_uri', '')
        if client_redirect_uri and not _is_allowed_redirect_url(client_redirect_uri):
            from starlette.responses import JSONResponse

            return JSONResponse(
                {
                    'error': 'invalid_request',
                    'error_description': (
                        'redirect_uri must be a localhost URL or a trusted domain'
                    ),
                },
                status_code=400,
            )

        original_state = params.get('state', '')

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
            for key in ('code_challenge', 'code_challenge_method', 'nonce', 'resource'):
                if key in params:
                    stage2_authorize_params[key] = params[key]

            state_data = json.dumps(
                {
                    'redirect_uri': client_redirect_uri,
                    'state': original_state,
                    'stage': 'mfa',
                    'original_scope': scope,
                    'authorize_params': stage2_authorize_params,
                }
            )
            mfa_params['state'] = base64.urlsafe_b64encode(state_data.encode()).decode()

            auth0_url = f'{config["auth0_base_url"]}/authorize?{urlencode(mfa_params)}'
            logger.info(
                'Stage 1: Redirecting to Auth0 MFA audience for MFA verification'
            )
        else:
            # Standard single-stage OAuth flow (no MFA required)
            state_data = json.dumps(
                {
                    'redirect_uri': client_redirect_uri,
                    'state': original_state,
                }
            )
            composite_state = base64.urlsafe_b64encode(state_data.encode()).decode()

            params['redirect_uri'] = f'{server_url}/oauth/callback'
            params['state'] = composite_state

            auth0_url = f'{config["auth0_base_url"]}/authorize?{urlencode(params)}'
            logger.info('Redirecting to Auth0 authorize endpoint')
        return RedirectResponse(url=auth0_url, status_code=302)

    @mcp_server.custom_route('/oauth/token', methods=['POST'])
    async def oauth_token(request):
        """Proxy token exchange to Auth0.

        Forwards the token request to Auth0's /oauth/token endpoint.
        Injects the configured client_id and client_secret for
        Auth0 token exchange (confidential client / RWA).
        """
        from starlette.responses import JSONResponse

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
            from urllib.parse import parse_qs

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

    @mcp_server.custom_route('/oauth/register', methods=['POST'])
    async def oauth_register(request):
        """Dynamic Client Registration endpoint (RFC 7591).

        Auth0 does not support Dynamic Client Registration on non-Enterprise
        plans, so this endpoint returns the server's pre-configured client_id
        to satisfy the MCP SDK's registration requirement.
        """
        from starlette.responses import JSONResponse

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

        # Return pre-configured client_id with metadata echoed back
        response_data = {
            'client_id': config['client_id'],
            'token_endpoint_auth_method': 'none',
        }

        # Echo back redirect_uris if provided
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
        from urllib.parse import urlencode

        from starlette.responses import JSONResponse, RedirectResponse

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
        authorize_params: dict = {}
        if composite_state:
            try:
                state_data = json.loads(
                    base64.urlsafe_b64decode(composite_state.encode()).decode()
                )
                client_redirect_uri = state_data.get('redirect_uri', '')
                original_state = state_data.get('state', '')
                stage = state_data.get('stage', '')
                original_scope = state_data.get('original_scope', '')
                authorize_params = state_data.get('authorize_params', {})
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                base64.binascii.Error,
            ) as e:
                logger.warning(f'Failed to decode composite state: {e}')
                # Fall back to treating the raw state as the original opaque state
                # so it can be echoed back to the client per OAuth spec.
                original_state = composite_state

        # Defense-in-depth: re-validate redirect_uri from state is allowed.
        # The authorize endpoint already validates this, but an attacker could craft
        # a composite state directly and hit Auth0 with our callback URL.
        if client_redirect_uri and not _is_allowed_redirect_url(client_redirect_uri):
            logger.warning(
                f'Callback rejected untrusted redirect_uri from state: '
                f'{client_redirect_uri}'
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
        if stage == 'mfa':
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
            stage2_state = json.dumps(
                {
                    'redirect_uri': client_redirect_uri,
                    'state': original_state,
                    'stage': 'regular',
                }
            )

            stage2_params = {
                'response_type': 'code',
                'client_id': config['client_id'],
                'audience': config['audience'],
                'redirect_uri': f'{server_url}/oauth/callback',
                'scope': original_scope or 'openid profile email offline_access',
                'state': base64.urlsafe_b64encode(stage2_state.encode()).decode(),
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
            return RedirectResponse(url=auth0_url, status_code=302)

        # --- Standard callback (stage 'regular' or absent) ---
        logger.info('Auth0 callback received authorization code')

        # Redirect back to the MCP client's original redirect_uri with the code
        if client_redirect_uri:
            params = {'code': code}
            if original_state:
                params['state'] = original_state
            return RedirectResponse(
                url=_build_redirect_url(client_redirect_uri, params),
                status_code=302,
            )

        # Fallback: return as JSON if no client redirect_uri was found
        result = {'code': code}
        if original_state:
            result['state'] = original_state
        return JSONResponse(result)

    @mcp_server.custom_route('/token', methods=['POST'])
    async def oauth_token_fallback(request):
        """Fallback token endpoint at /token.

        MCP SDK clients fall back to /token (instead of /oauth/token) when
        oauth_metadata is not cached — e.g. after a client restart that
        still has a stored refresh_token but lost the server metadata.
        Delegating to the canonical handler avoids a silent 404.
        """
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

    @mcp_server.custom_route('/register', methods=['POST'])
    async def oauth_register_fallback(request):
        """Fallback register endpoint at /register.

        MCP SDK clients fall back to /register when oauth_metadata
        is not cached.
        """
        logger.info('/register fallback hit — delegating to /oauth/register handler')
        return await oauth_register(request)

    logger.info(
        'OAuth proxy routes registered (including /token, /authorize, /register fallbacks)'
    )
