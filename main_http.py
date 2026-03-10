"""HTTP Streamable transport entry point for Alpacon MCP server.

This module starts the MCP server with Auth0 JWT authentication
and streamable-http transport for remote deployment.

Environment variables must be set before running:
    AUTH0_DOMAIN        - Auth0 tenant domain (required)
    AUTH0_CLIENT_ID     - Auth0 application client ID (required)
    AUTH0_AUDIENCE      - Auth0 API audience (default: https://alpacon.io/access/)
    AUTH0_NAMESPACE     - Auth0 custom claim namespace (default: https://alpacon.io/)

Usage:
    alpacon-mcp-http          # Via installed script entry
    python main_http.py       # Direct execution
"""

import os
import sys

from utils.logger import get_logger

logger = get_logger('main_http')


def main():
    """Main entry point for HTTP transport mode."""
    # Validate required Auth0 configuration (fail fast on missing env vars)
    missing = []
    for var in ['AUTH0_DOMAIN', 'AUTH0_CLIENT_ID']:
        if not os.getenv(var, ''):
            missing.append(var)

    if missing:
        print(
            f'\nError: Required environment variable(s) not set: {", ".join(missing)}'
        )
        print('\nRequired environment variables:')
        print('  AUTH0_DOMAIN        - Auth0 tenant domain')
        print('  AUTH0_CLIENT_ID     - Auth0 application client ID')
        print('\nOptional environment variables:')
        print(
            '  AUTH0_AUDIENCE      - Auth0 API audience (default: https://alpacon.io/access/)'
        )
        print(
            '  AUTH0_CLIENT_SECRET - Auth0 client secret (only for confidential clients)'
        )
        sys.exit(1)

    # Enable auth mode BEFORE importing server module
    # (server.py reads this at module level to create MCP instance with JWT auth)
    os.environ['ALPACON_MCP_AUTH_ENABLED'] = 'true'

    # Default to 0.0.0.0 for container deployment (server.py defaults to 127.0.0.1)
    if 'ALPACON_MCP_HOST' not in os.environ:
        os.environ['ALPACON_MCP_HOST'] = '0.0.0.0'  # noqa: S104

    logger.info('Starting Alpacon MCP Server (HTTP Streamable transport)')

    from server import run

    try:
        run('streamable-http')
    except Exception as e:
        logger.error(f'Failed to start MCP server: {e}', exc_info=True)
        raise


if __name__ == '__main__':
    main()
