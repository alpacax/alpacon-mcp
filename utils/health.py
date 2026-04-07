"""Health check utilities for Alpacon MCP server."""

import os
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger('health')

# Track server start time
_start_time = time.monotonic()


def _is_remote_mode() -> bool:
    """Check if running in remote (streamable-http) mode with JWT auth."""
    return os.getenv('ALPACON_MCP_AUTH_ENABLED', '').lower() == 'true'


def _get_auth_info_remote() -> dict[str, Any]:
    """Get auth info for remote (JWT) mode."""
    return {
        'mode': 'jwt',
        'auth_required': True,
    }


def _get_auth_info_local() -> dict[str, Any]:
    """Get auth info for local (token.json) mode."""
    from utils.token_manager import get_token_manager

    token_manager = get_token_manager()
    auth_status = token_manager.get_auth_status()
    return {
        'mode': 'token_file',
        'authenticated': auth_status.get('authenticated', False),
        'total_tokens': auth_status.get('total_tokens', 0),
        'regions_configured': len(auth_status.get('regions', [])),
    }


async def get_health_info() -> dict[str, Any]:
    """Collect health information for the MCP server.

    Returns a sanitized health status dict that never exposes
    token values, workspace names, file paths, or internal URLs.

    Returns:
        Health status dictionary
    """
    import importlib.metadata

    from utils.http_client import http_client

    try:
        MCP_VERSION = importlib.metadata.version('alpacon-mcp')
    except importlib.metadata.PackageNotFoundError:
        MCP_VERSION = '0.4.2-dev'

    # Auth config — mode-appropriate info only
    auth_info = _get_auth_info_remote() if _is_remote_mode() else _get_auth_info_local()

    # HTTP client pool status
    http_pool_active = http_client.pool_active
    http_cache_size = http_client.cache_size

    health_info = {
        'status': 'ok',
        'version': MCP_VERSION,
        'uptime_seconds': round(time.monotonic() - _start_time, 2),
        'transport': os.getenv('ALPACON_MCP_TRANSPORT', 'unknown'),
        'auth': auth_info,
        'http_client': {
            'pool_active': http_pool_active,
            'cache_size': http_cache_size,
        },
    }
    logger.debug(
        f'Health check: status={health_info["status"]}, uptime={health_info["uptime_seconds"]}s'
    )
    return health_info
