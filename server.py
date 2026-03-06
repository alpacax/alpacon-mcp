import os
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

        issuer_url_str = f'https://{auth0_domain}/'

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

        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url_str),
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


@mcp.custom_route('/health', methods=['GET'])
async def health_endpoint(request):
    """HTTP health check endpoint for container orchestration.

    Bypasses auth - suitable for unauthenticated health probes
    (e.g., Kubernetes liveness/readiness checks).
    Available on SSE and streamable-http transports only.
    """
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


def run(transport: str = 'stdio', config_file: str = None):
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

    # Register OAuth proxy routes if auth is enabled
    if os.getenv('ALPACON_MCP_AUTH_ENABLED', '').lower() == 'true':
        # Validate OAuth config at startup to fail fast on misconfiguration
        auth0_client_id = os.getenv('AUTH0_CLIENT_ID', '')
        if not auth0_client_id:
            raise RuntimeError(
                'AUTH0_CLIENT_ID environment variable is required when '
                'ALPACON_MCP_AUTH_ENABLED=true.'
            )

        from utils.oauth import register_oauth_routes

        register_oauth_routes(mcp)

    # Import all tool modules to register MCP tools via decorators
    import tools.command_tools  # noqa: F401
    import tools.events_tools  # noqa: F401
    import tools.health_tools  # noqa: F401
    import tools.iam_tools  # noqa: F401
    import tools.metrics_tools  # noqa: F401
    import tools.server_tools  # noqa: F401
    import tools.system_info_tools  # noqa: F401
    import tools.webftp_tools  # noqa: F401
    import tools.websh_tools  # noqa: F401
    import tools.workspace_tools  # noqa: F401

    try:
        logger.info('Starting FastMCP server...')
        mcp.run(transport=transport)
    except Exception as e:
        logger.error(f'FastMCP server failed to run: {e}', exc_info=True)
        raise
