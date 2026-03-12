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


def _get_oauth_config() -> dict[str, str]:
    """Get OAuth configuration from environment variables."""
    domain = os.getenv('AUTH0_DOMAIN', '')
    client_id = os.getenv('AUTH0_CLIENT_ID', '')
    audience = os.getenv('AUTH0_AUDIENCE', 'https://alpacon.io/access/')

    if not domain:
        raise ValueError('AUTH0_DOMAIN environment variable is required')
    if not client_id:
        raise ValueError('AUTH0_CLIENT_ID environment variable is required')

    return {
        'domain': domain,
        'client_id': client_id,
        'audience': audience,
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

        Returns metadata that points to Auth0 as the authorization server,
        with token and authorization endpoints proxied through this server.
        """
        from starlette.responses import JSONResponse

        try:
            config = _get_oauth_config()
        except ValueError as e:
            return JSONResponse({'error': str(e)}, status_code=500)

        # Build server base URL from trusted config or request URL.
        # Prefer an explicit environment variable to avoid relying on
        # potentially spoofable forwarding headers.
        configured_base_url = os.getenv('ALPACON_MCP_RESOURCE_URL')
        if configured_base_url:
            server_url = configured_base_url.rstrip('/')
        else:
            server_url = f'{request.url.scheme}://{request.url.netloc}'

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
                'client_secret_post',
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

        # Build MCP server's own callback URL as redirect_uri for Auth0.
        # Store the client's original redirect_uri in the state so we can
        # forward the authorization code back to the client after Auth0 callback.
        configured_base_url = os.getenv('ALPACON_MCP_RESOURCE_URL')
        if configured_base_url:
            server_url = configured_base_url.rstrip('/')
        else:
            server_url = f'{request.url.scheme}://{request.url.netloc}'

        # Save client's original redirect_uri to relay the code later.
        # Only allow localhost redirect_uris (MCP clients run local HTTP servers)
        # to prevent open redirect attacks that could leak authorization codes.
        client_redirect_uri = params.get('redirect_uri', '')
        if client_redirect_uri:
            from urllib.parse import urlparse

            parsed = urlparse(client_redirect_uri)
            allowed_hosts = ('localhost', '127.0.0.1', '::1')
            if parsed.scheme not in ('http', 'https') or parsed.hostname not in allowed_hosts:
                from starlette.responses import JSONResponse

                return JSONResponse(
                    {
                        'error': 'invalid_request',
                        'error_description': (
                            'redirect_uri must be a localhost URL using http/https'
                        ),
                    },
                    status_code=400,
                )

        original_state = params.get('state', '')

        # Encode client redirect_uri and original state into a composite state
        state_data = json.dumps(
            {
                'redirect_uri': client_redirect_uri,
                'state': original_state,
            }
        )
        composite_state = base64.urlsafe_b64encode(state_data.encode()).decode()

        # Override redirect_uri to point to this server's callback
        params['redirect_uri'] = f'{server_url}/oauth/callback'
        params['state'] = composite_state

        auth0_url = f'{config["auth0_base_url"]}/authorize?{urlencode(params)}'
        logger.info('Redirecting to Auth0 authorize endpoint')
        return RedirectResponse(url=auth0_url, status_code=302)

    @mcp_server.custom_route('/oauth/token', methods=['POST'])
    async def oauth_token(request):
        """Proxy token exchange to Auth0.

        Forwards the token request to Auth0's /oauth/token endpoint.
        Only injects the configured client_id when not provided by the
        client. Never injects client_secret, so it is safe for use
        with public PKCE clients.
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

        # Override redirect_uri to match what was sent to Auth0 during /authorize.
        # Auth0 requires the redirect_uri in token exchange to match exactly.
        # Always set it for authorization_code grants since /authorize always
        # sends redirect_uri to Auth0.
        if params.get('grant_type') == 'authorization_code':
            configured_base_url = os.getenv('ALPACON_MCP_RESOURCE_URL')
            if configured_base_url:
                server_url = configured_base_url.rstrip('/')
            else:
                server_url = f'{request.url.scheme}://{request.url.netloc}'
            params['redirect_uri'] = f'{server_url}/oauth/callback'

        # Forward to Auth0
        auth0_token_url = f'{config["auth0_base_url"]}/oauth/token'
        logger.info('Proxying token request to Auth0')

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

        This endpoint receives the authorization code from Auth0
        and redirects the user back to the MCP client's original
        redirect_uri with the code and state.
        """
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        from starlette.responses import JSONResponse, RedirectResponse

        def _build_redirect_url(base_url: str, extra_params: dict) -> str:
            """Safely merge query params into a URL, preserving existing params."""
            parsed = urlparse(base_url)
            existing_params = parse_qs(parsed.query, keep_blank_values=True)
            # Flatten single-value lists from parse_qs
            merged = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
            merged.update(extra_params)
            new_query = urlencode(merged, doseq=True)
            return urlunparse(parsed._replace(query=new_query))

        def _is_localhost_url(url: str) -> bool:
            """Validate that a URL points to a localhost address."""
            parsed = urlparse(url)
            allowed_hosts = ('localhost', '127.0.0.1', '::1')
            return parsed.scheme in ('http', 'https') and parsed.hostname in allowed_hosts

        # Extract callback parameters
        code = request.query_params.get('code')
        composite_state = request.query_params.get('state')
        error = request.query_params.get('error')
        error_description = request.query_params.get('error_description')

        # Decode the composite state to get client's redirect_uri and original state
        client_redirect_uri = ''
        original_state = ''
        if composite_state:
            try:
                state_data = json.loads(
                    base64.urlsafe_b64decode(composite_state.encode()).decode()
                )
                client_redirect_uri = state_data.get('redirect_uri', '')
                original_state = state_data.get('state', '')
            except (json.JSONDecodeError, UnicodeDecodeError, Exception) as e:
                logger.warning(f'Failed to decode composite state: {e}')

        # Defense-in-depth: re-validate redirect_uri from state is a localhost URL.
        # The authorize endpoint already validates this, but an attacker could craft
        # a composite state directly and hit Auth0 with our callback URL.
        if client_redirect_uri and not _is_localhost_url(client_redirect_uri):
            logger.warning(
                f'Callback rejected non-localhost redirect_uri from state: '
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

    logger.info('OAuth proxy routes registered')
