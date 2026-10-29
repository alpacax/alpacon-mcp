"""Streamable-http entry point with Auth0 JWT auth. Needs AUTH0_ALPACON_DOMAIN and
AUTH0_ALPACON_LOGIN_CLIENT_ID (the old AUTH0_DOMAIN and AUTH0_CLIENT_ID still work)."""

import os
import sys

import uvicorn

from utils.auth0_env import get_auth0_env
from utils.auth_error_middleware import UpstreamAuthErrorMiddleware
from utils.logger import get_logger, json_logs_requested, logger_manager

logger = get_logger('main_http')


def main() -> None:
    json_logs = json_logs_requested()
    if json_logs:
        logger_manager.use_json_stdout()

    # Validate required Auth0 configuration (fail fast on missing env vars)
    missing = [
        var
        for var in ('AUTH0_ALPACON_DOMAIN', 'AUTH0_ALPACON_LOGIN_CLIENT_ID')
        if not get_auth0_env(var)
    ]

    if missing:
        # One record, not print(): JSON mode owns stdout, and Datadog reads the level.
        logger.error(
            'Required environment variable(s) not set: %s. AUTH0_ALPACON_DOMAIN is the '
            'Auth0 tenant domain and AUTH0_ALPACON_LOGIN_CLIENT_ID the application client ID; '
            'see docs/configuration.md',
            ', '.join(missing),
        )
        sys.exit(1)

    # Enable auth mode BEFORE importing server module
    # (server.py reads this at module level to create MCP instance with JWT auth)
    os.environ['ALPACON_MCP_AUTH_ENABLED'] = 'true'

    # Default to 0.0.0.0 for container deployment (server.py defaults to 127.0.0.1)
    if 'ALPACON_MCP_HOST' not in os.environ:
        os.environ['ALPACON_MCP_HOST'] = '0.0.0.0'  # noqa: S104

    logger.info('Starting Alpacon MCP Server (HTTP Streamable transport)')

    from server import (
        TOOLSETS_ENV_VAR,
        TRANSPORT_STREAMABLE_HTTP,
        ToolsetError,
        create_streamable_http_app,
        prepare,
        resolve_host,
        resolve_port,
        resource_metadata_url,
    )

    try:
        prepare(TRANSPORT_STREAMABLE_HTTP)

        host = resolve_host()
        port = resolve_port()
        app = UpstreamAuthErrorMiddleware(
            create_streamable_http_app(host=host),
            resource_metadata_url=resource_metadata_url(),
        )
        logger.info(
            'Upstream auth error middleware installed on the streamable-http app'
        )
        uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level='info',
                log_config=None if json_logs else uvicorn.config.LOGGING_CONFIG,
                server_header=False,
            )
        ).run()
    except ToolsetError as e:
        # A toolsets typo is a config error, not a crash: one clean line, no traceback.
        logger.error('Invalid %s: %s', TOOLSETS_ENV_VAR, e)
        raise SystemExit(2)
    except Exception as e:
        logger.exception('Failed to start MCP server: %s', e)
        raise


if __name__ == '__main__':
    main()
