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

mcp = FastMCP(
    'alpacon',
    host=host,
    port=port,
    lifespan=app_lifespan,
)


def run(transport: str = 'stdio', config_file: str = None):
    """Run MCP server with optional config file path.

    Args:
        transport: Transport type ('stdio' or 'sse')
        config_file: Path to token config file (optional)
    """
    logger.info(f'Starting MCP server with transport: {transport}')

    # Import all tool modules to register MCP tools via decorators
    import tools.command_tools  # noqa: F401
    import tools.events_tools  # noqa: F401
    import tools.iam_tools  # noqa: F401
    import tools.metrics_tools  # noqa: F401
    import tools.server_tools  # noqa: F401
    import tools.system_info_tools  # noqa: F401
    import tools.webftp_tools  # noqa: F401
    import tools.websh_tools  # noqa: F401
    import tools.workspace_tools  # noqa: F401

    # Set config file path as environment variable if provided
    if config_file:
        logger.info(f'Using config file: {config_file}')
        os.environ['ALPACON_MCP_CONFIG_FILE'] = config_file
    else:
        logger.info('No config file specified, using default config discovery')

    try:
        logger.info('Starting FastMCP server...')
        mcp.run(transport=transport)
    except Exception as e:
        logger.error(f'FastMCP server failed to run: {e}', exc_info=True)
        raise
