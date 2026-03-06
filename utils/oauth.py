"""OAuth 2.0 proxy endpoints for Auth0 integration.

These endpoints allow MCP clients (e.g. claude.ai) to perform
OAuth authorization code flow through this MCP server, which
proxies requests to Auth0.

All routes are registered via FastMCP's custom_route decorator,
which bypasses MCP authentication — appropriate for OAuth flow endpoints.
"""

import os

import httpx

from utils.logger import get_logger

logger = get_logger('oauth')


def _get_oauth_config() -> dict[str, str]:
    """Get OAuth configuration from environment variables."""
    domain = os.getenv('AUTH0_DOMAIN', '')
    client_id = os.getenv('AUTH0_CLIENT_ID', '')
    client_secret = os.getenv('AUTH0_CLIENT_SECRET', '')
    audience = os.getenv('AUTH0_AUDIENCE', 'https://alpacon.io/access/')

    if not domain:
        raise ValueError('AUTH0_DOMAIN environment variable is required')
    if not client_id:
        raise ValueError('AUTH0_CLIENT_ID environment variable is required')

    return {
        'domain': domain,
        'client_id': client_id,
        'client_secret': client_secret,
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

        # Build server base URL from request
        scheme = request.headers.get('x-forwarded-proto', request.url.scheme)
        host = request.headers.get('x-forwarded-host', request.url.netloc)
        server_url = f'{scheme}://{host}'

        metadata = {
            'issuer': f'{config["auth0_base_url"]}/',
            'authorization_endpoint': f'{server_url}/oauth/authorize',
            'token_endpoint': f'{server_url}/oauth/token',
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
                'Access-Control-Allow-Origin': '*',
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

        # Set client_id if not provided by the MCP client
        if 'client_id' not in params:
            params['client_id'] = config['client_id']

        # Set audience for Alpacon API access
        if 'audience' not in params:
            params['audience'] = config['audience']

        # Ensure response_type is set
        if 'response_type' not in params:
            params['response_type'] = 'code'

        auth0_url = f'{config["auth0_base_url"]}/authorize?{urlencode(params)}'
        logger.info('Redirecting to Auth0 authorize endpoint')
        return RedirectResponse(url=auth0_url, status_code=302)

    @mcp_server.custom_route('/oauth/token', methods=['POST'])
    async def oauth_token(request):
        """Proxy token exchange to Auth0.

        Forwards the token request to Auth0's /oauth/token endpoint,
        injecting client credentials if not provided.
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
            import json

            try:
                params = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse(
                    {'error': 'invalid_request', 'error_description': 'Invalid JSON'},
                    status_code=400,
                )
        else:
            # application/x-www-form-urlencoded (standard OAuth)
            from urllib.parse import parse_qs

            parsed = parse_qs(body.decode('utf-8'))
            params = {k: v[0] for k, v in parsed.items()}

        # Inject client credentials
        if 'client_id' not in params:
            params['client_id'] = config['client_id']
        if 'client_secret' not in params and config['client_secret']:
            params['client_secret'] = config['client_secret']

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

            return JSONResponse(
                response.json(),
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

    @mcp_server.custom_route('/oauth/callback', methods=['GET'])
    async def oauth_callback(request):
        """Handle Auth0 callback after authorization.

        This endpoint receives the authorization code from Auth0
        and redirects back to the MCP client's redirect_uri.
        """

        from starlette.responses import JSONResponse

        # Extract callback parameters
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        error = request.query_params.get('error')
        error_description = request.query_params.get('error_description')

        if error:
            logger.warning(f'Auth0 callback error: {error} - {error_description}')
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

        # The MCP client's redirect_uri should be in the state or
        # stored during the authorize step. For now, return the code
        # as a JSON response that the client can process.
        logger.info('Auth0 callback received authorization code')

        result = {'code': code}
        if state:
            result['state'] = state

        return JSONResponse(result)

    logger.info('OAuth proxy routes registered')
