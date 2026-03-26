import os
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from mcp.server.fastmcp import FastMCP

from utils.logger import get_logger

logger = get_logger('server')


@asynccontextmanager
async def app_lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle.

    On startup: install SIGTERM handler (Unix only).
    On shutdown: close all WebSocket connections and HTTP client.
    """
    original_handler = None
    handler_installed = False

    # Install SIGTERM handler on Unix to reuse anyio's KeyboardInterrupt shutdown path
    if sys.platform != 'win32':
        try:
            original_handler = signal.signal(signal.SIGTERM, _sigterm_handler)
            handler_installed = True
            logger.info('SIGTERM handler installed')
        except Exception as e:
            logger.warning(f'Could not install SIGTERM handler: {e}')

    logger.info('Application lifespan started')
    try:
        yield
    finally:
        logger.info('Application shutting down, cleaning up resources...')
        # Lazy imports to avoid circular imports (server.py <-> tools/*.py)
        from tools.websh_tools import cleanup_all_connections
        from utils.http_client import http_client

        try:
            await cleanup_all_connections()
        except Exception as e:
            logger.error(f'Error during WebSocket cleanup: {e}')

        try:
            await http_client.close()
        except Exception as e:
            logger.error(f'Error during HTTP client cleanup: {e}')

        if handler_installed:
            try:
                signal.signal(signal.SIGTERM, original_handler)
            except Exception as e:
                logger.warning(f'Could not restore SIGTERM handler: {e}')

        logger.info('Graceful shutdown complete')


def _sigterm_handler(signum, frame):
    """Handle SIGTERM by raising KeyboardInterrupt for anyio's shutdown path."""
    raise KeyboardInterrupt


# This is the shared MCP server instance
host = os.getenv('ALPACON_MCP_HOST', '127.0.0.1')  # Default to localhost for security
port = int(
    os.getenv('ALPACON_MCP_PORT', '8237')
)  # Default port 8237 (MCAR - MCP Alpacon Remote)

logger.info(f'Initializing FastMCP server - host: {host}, port: {port}')


def _create_mcp_server() -> FastMCP:
    """Create FastMCP server instance with optional JWT auth.

    When ALPACON_MCP_AUTH_ENABLED=true (set by main_http.py before import),
    creates the server with Auth0 JWT authentication for HTTP transport.
    Otherwise creates a standard server for stdio/SSE transport.
    """
    auth_enabled = os.getenv('ALPACON_MCP_AUTH_ENABLED', '').lower() == 'true'

    if auth_enabled:
        from mcp.server.auth.settings import AuthSettings
        from pydantic import AnyHttpUrl

        from utils.auth import Auth0TokenVerifier

        auth0_domain = os.getenv('AUTH0_DOMAIN', '')
        resource_url = os.getenv('ALPACON_MCP_RESOURCE_URL', 'https://mcp.alpacon.io')

        if not auth0_domain or not auth0_domain.strip():
            message = (
                'AUTH0_DOMAIN environment variable must be set when '
                'ALPACON_MCP_AUTH_ENABLED=true.'
            )
            logger.error(message)
            raise RuntimeError(message)

        if '://' in auth0_domain or '/' in auth0_domain:
            message = (
                'AUTH0_DOMAIN must be a bare domain such as '
                "'example.us.auth0.com', without scheme or path."
            )
            logger.error(message)
            raise RuntimeError(message)

        # Validate resource_url with proper URL parsing before passing to AnyHttpUrl
        from urllib.parse import urlparse

        parsed_url = urlparse(resource_url)
        if parsed_url.scheme != 'https' or not parsed_url.netloc:
            message = (
                'ALPACON_MCP_RESOURCE_URL must be a valid HTTPS URL '
                "(e.g., 'https://mcp.alpacon.io'). "
                f'Got: {resource_url!r}'
            )
            logger.error(message)
            raise RuntimeError(message)
        # Reconstruct from parsed components to ensure canonical form
        resource_url = (
            f'{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}'.rstrip('/')
        )

        # Use the MCP server's own URL as issuer_url so that clients discover
        # our OAuth proxy endpoints (authorize, token, register) instead of
        # going directly to Auth0 — which doesn't support Dynamic Client
        # Registration on non-Enterprise plans.
        # JWT token verification still validates against Auth0's issuer
        # independently via Auth0TokenVerifier.
        # Ensure issuer_url has a trailing slash to match the issuer value
        # in /.well-known/oauth-authorization-server metadata (RFC 8414
        # requires exact string match for issuer identifiers).
        issuer_url = resource_url.rstrip('/') + '/'
        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(resource_url),
        )
        token_verifier = Auth0TokenVerifier()

        logger.info(f'Creating FastMCP server with JWT auth - domain: {auth0_domain}')
        return FastMCP(
            'alpacon',
            host=host,
            port=port,
            auth=auth_settings,
            token_verifier=token_verifier,
            lifespan=app_lifespan,
            json_response=True,
            stateless_http=True,
        )
    else:
        logger.info('Creating FastMCP server without auth (stdio/SSE mode)')
        return FastMCP(
            'alpacon',
            host=host,
            port=port,
            lifespan=app_lifespan,
        )


mcp = _create_mcp_server()


def _is_remote_mode() -> bool:
    """Check if running in remote (streamable-http) mode with JWT auth."""
    return os.getenv('ALPACON_MCP_AUTH_ENABLED', '').lower() == 'true'


def _install_upstream_auth_middleware():
    """Override run_streamable_http_async to wrap app with auth error middleware.

    When the Alpacon API returns 401 (e.g., MFA timeout), the middleware
    replaces the HTTP 200 JSON-RPC response with HTTP 401, triggering
    the MCP client's automatic OAuth re-authentication flow.
    """
    from utils.auth_error_middleware import UpstreamAuthErrorMiddleware

    resource_url = os.getenv('ALPACON_MCP_RESOURCE_URL', 'https://mcp.alpacon.io')
    resource_metadata_url = (
        f'{resource_url.rstrip("/")}/.well-known/oauth-protected-resource'
    )

    async def patched_run():
        import uvicorn

        starlette_app = mcp.streamable_http_app()
        wrapped_app = UpstreamAuthErrorMiddleware(
            starlette_app,
            resource_metadata_url=resource_metadata_url,
        )

        config = uvicorn.Config(
            wrapped_app,
            host=host,
            port=port,
            log_level='info',
            server_header=False,
        )
        server = uvicorn.Server(config)
        await server.serve()

    mcp.run_streamable_http_async = patched_run
    logger.info('Upstream auth error middleware installed for remote mode')


def _register_http_health_endpoint():
    """Register HTTP /health endpoint for HTTP transports (SSE, streamable-http).

    Bypasses auth for unauthenticated health probes
    (e.g., Kubernetes liveness/readiness checks, docker-compose).
    """

    @mcp.custom_route('/health', methods=['GET'])
    async def health_endpoint(request):
        from starlette.responses import JSONResponse

        from utils.health import get_health_info

        health = await get_health_info()
        return JSONResponse(
            health,
            headers={
                'Cache-Control': 'no-store',
                'Pragma': 'no-cache',
                'Expires': '0',
            },
        )


def run(
    transport: Literal['stdio', 'sse', 'streamable-http'] = 'stdio',
    config_file: str | None = None,
):
    """Run MCP server with optional config file path.

    Args:
        transport: Transport type ('stdio', 'sse', or 'streamable-http')
        config_file: Path to token config file (optional)
    """
    logger.info(f'Starting MCP server with transport: {transport}')

    # Set transport type for health check reporting
    os.environ['ALPACON_MCP_TRANSPORT'] = transport

    # Set config file path as environment variable if provided (before tool imports
    # so that tools that read config at import time see the correct path)
    if config_file:
        logger.info(f'Using config file: {config_file}')
        os.environ['ALPACON_MCP_CONFIG_FILE'] = config_file
    else:
        logger.info('No config file specified, using default config discovery')

    remote_mode = _is_remote_mode()

    if remote_mode:
        # Remote (streamable-http) mode: register OAuth routes
        auth0_client_id = os.getenv('AUTH0_CLIENT_ID', '')
        if not auth0_client_id:
            raise RuntimeError(
                'AUTH0_CLIENT_ID environment variable is required when '
                'ALPACON_MCP_AUTH_ENABLED=true.'
            )

        from utils.oauth import register_oauth_routes

        register_oauth_routes(mcp)
        logger.info('Remote mode: OAuth routes registered')

    if transport in ('sse', 'streamable-http'):
        # HTTP transports: register HTTP /health endpoint (bypasses auth)
        _register_http_health_endpoint()
        logger.info('HTTP /health endpoint registered for transport: %s', transport)

    if not remote_mode:
        # Local (stdio/SSE) mode: register health_check MCP tool
        import tools.health_tools  # noqa: F401

        logger.info('Local mode: health_check MCP tool registered')

    # Import all tool modules to register MCP tools via decorators
    import tools.alert_tools  # noqa: F401
    import tools.audit_tools  # noqa: F401
    import tools.command_tools  # noqa: F401
    import tools.events_tools  # noqa: F401
    import tools.iam_tools  # noqa: F401
    import tools.metrics_tools  # noqa: F401
    import tools.security_tools  # noqa: F401
    import tools.server_tools  # noqa: F401
    import tools.system_info_tools  # noqa: F401
    import tools.webftp_tools  # noqa: F401
    import tools.websh_tools  # noqa: F401
    import tools.workspace_tools  # noqa: F401

    # In remote mode, wrap the Starlette app with upstream auth error
    # middleware to propagate Alpacon API 401 as MCP transport 401.
    if remote_mode:
        _install_upstream_auth_middleware()

    try:
        logger.info('Starting FastMCP server...')
        mcp.run(transport=transport)
    except Exception as e:
        logger.error(f'FastMCP server failed to run: {e}', exc_info=True)
        raise
