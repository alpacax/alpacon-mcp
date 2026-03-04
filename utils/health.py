"""Health check utilities for Alpacon MCP server."""

import os
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger('health')

# Track server start time
_start_time = time.monotonic()


async def get_health_info() -> dict[str, Any]:
    """Collect health information for the MCP server.

    Returns a sanitized health status dict that never exposes
    token values, workspace names, file paths, or internal URLs.

    Returns:
        Health status dictionary
    """
    from utils.common import MCP_VERSION
    from utils.http_client import http_client
    from utils.token_manager import get_token_manager

    # Token config (sanitized: no workspace names, paths, or token values)
    token_manager = get_token_manager()
    auth_status = token_manager.get_auth_status()
    token_config = {
        'authenticated': auth_status.get('authenticated', False),
        'total_tokens': auth_status.get('total_tokens', 0),
        'regions_configured': len(auth_status.get('regions', [])),
    }

    # HTTP client pool status
    http_pool_active = http_client.pool_active
    http_cache_size = http_client.cache_size

    # WebSocket pool status (deferred import to avoid circular imports)
    try:
        from tools.websh_tools import session_pool, websocket_pool

        ws_info = {
            'active_channels': len(websocket_pool),
            'active_sessions': len(session_pool),
        }
    except ImportError:
        ws_info = {
            'active_channels': 0,
            'active_sessions': 0,
        }

    health_info = {
        'status': 'ok',
        'version': MCP_VERSION,
        'uptime_seconds': round(time.monotonic() - _start_time, 2),
        'transport': os.getenv('ALPACON_MCP_TRANSPORT', 'unknown'),
        'token_config': token_config,
        'http_client': {
            'pool_active': http_pool_active,
            'cache_size': http_cache_size,
        },
        'websocket_pool': ws_info,
    }
    logger.debug(
        f'Health check: status={health_info["status"]}, uptime={health_info["uptime_seconds"]}s'
    )
    return health_info
