"""Common utilities for all MCP tools."""

import importlib.metadata
from typing import Any

from utils.logger import get_logger
from utils.token_manager import get_token_manager

# Initialize shared instances
token_manager = get_token_manager()
logger = get_logger('common')

# Get version from package metadata (pyproject.toml)
try:
    MCP_VERSION = importlib.metadata.version('alpacon-mcp')
except importlib.metadata.PackageNotFoundError:
    # Fallback for development environment
    MCP_VERSION = '0.4.2-dev'

# MCP User-Agent for identification
MCP_USER_AGENT = f'alpacon-mcp/{MCP_VERSION} (MCP-Server; persistent-pool) Python/3.12 websockets/15.0.1'


def validate_token(region: str, workspace: str) -> str | None:
    """Validate and retrieve token for given region and workspace.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Token string if found, None otherwise
    """
    token = token_manager.get_token(region, workspace)
    if not token:
        logger.error(f'No token found for {workspace}.{region}')
    return token


def error_response(message: str, **kwargs) -> dict[str, Any]:
    """Create standardized error response.

    Args:
        message: Error message
        **kwargs: Additional fields to include in response

    Returns:
        Standardized error response dict
    """
    response = {'status': 'error', 'message': message}
    response.update(kwargs)
    return response


def success_response(data: Any = None, **kwargs) -> dict[str, Any]:
    """Create standardized success response.

    Args:
        data: Response data
        **kwargs: Additional fields to include in response

    Returns:
        Standardized success response dict
    """
    response = {'status': 'success'}
    if data is not None:
        response['data'] = data
    response.update(kwargs)
    return response


def token_error_response(region: str, workspace: str) -> dict[str, Any]:
    """Create standardized token error response.

    Args:
        region: Region
        workspace: Workspace name

    Returns:
        Token error response
    """
    return error_response(
        f'No token found for {workspace}.{region}. Please set token first.',
        region=region,
        workspace=workspace,
    )


def unwrap_http_result(
    result: Any,
    *,
    default_message: str,
    **id_context: Any,
) -> dict[str, Any] | None:
    """Convert an http_client error-dict into an error_response.

    Returns the error_response dict if `result` is the error envelope produced
    by `utils.http_client` on 4xx/5xx; otherwise returns None so the caller
    can wrap the payload with `success_response`.

    Args:
        result: Raw value returned by an http_client method.
        default_message: Fallback message when the upstream response has none.
        **id_context: Extra identifiers (e.g. note_id, region, workspace) merged
            into the error response for caller debugging.

    Returns:
        error_response dict if result is an error envelope, else None.
    """
    if not (isinstance(result, dict) and 'error' in result):
        return None

    error_kwargs: dict[str, Any] = dict(id_context)
    status_code = result.get('status_code')
    if status_code is not None:
        error_kwargs['status_code'] = status_code
    return error_response(
        result.get('message', default_message),
        **error_kwargs,
    )
