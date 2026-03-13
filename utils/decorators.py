"""Decorators for MCP tools to reduce boilerplate code."""

import inspect
import os
from collections.abc import Callable
from functools import wraps

from utils.common import error_response, token_error_response, validate_token
from utils.error_handler import (
    format_validation_error,
    validate_region_format,
    validate_server_id_format,
    validate_workspace_format,
)
from utils.logger import get_logger

logger = get_logger('decorators')


def _is_auth_enabled() -> bool:
    """Check if OAuth2 authentication mode is enabled (streamable-http transport).

    Returns True when running in streamable-http mode with Auth0 JWT auth.
    Returns False when running in stdio/SSE mode with token.json.
    """
    return os.getenv('ALPACON_MCP_AUTH_ENABLED') == 'true'


def _get_jwt_token() -> str | None:
    """Get JWT token from FastMCP auth context if available.

    Returns the raw JWT string when running in HTTP transport mode
    with JWT authentication. Returns None in stdio/SSE mode.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access_token = get_access_token()
        if access_token is not None:
            return access_token.token
    except ImportError:
        pass
    return None


def _decode_jwt_claims(jwt_token: str) -> dict | None:
    """Decode JWT claims without verification (already verified by middleware)."""
    try:
        import jwt as pyjwt

        return pyjwt.decode(
            jwt_token,
            options={
                'verify_signature': False,
                'verify_aud': False,
                'verify_iss': False,
                'verify_exp': False,
            },
        )
    except Exception as e:
        logger.error(f'JWT decode failed: {e}')
        return None


def _get_jwt_workspaces(jwt_token: str) -> list[dict[str, str]]:
    """Extract workspace list from JWT claims."""
    from utils.auth import extract_workspaces

    claims = _decode_jwt_claims(jwt_token)
    if not claims:
        return []

    return extract_workspaces(claims, 'https://alpacon.io/')


def _validate_jwt_workspace(jwt_token: str, region: str, workspace: str) -> bool:
    """Validate that the JWT authorizes access to the given workspace/region."""
    try:
        from utils.auth import match_workspace

        workspaces = _get_jwt_workspaces(jwt_token)
        return match_workspace(workspaces, region, workspace)
    except Exception as e:
        logger.error(f'JWT workspace validation failed: {e}')
        return False


def _resolve_region_from_jwt(
    jwt_token: str, workspace: str | None = None
) -> str | None:
    """Resolve region from JWT claims.

    If workspace is given, find its region. Otherwise, return region if only one exists.
    """
    workspaces = _get_jwt_workspaces(jwt_token)
    if not workspaces:
        return None

    if workspace:
        matching = [
            ws.get('region') for ws in workspaces if ws.get('schema_name') == workspace
        ]
        if len(matching) == 1:
            return matching[0]
        return None

    regions = list({ws.get('region') for ws in workspaces if ws.get('region')})
    if len(regions) == 1:
        return regions[0]
    return None


def _resolve_region_jwt(
    jwt_token: str, workspace: str | None
) -> tuple[str | None, str | None]:
    """Resolve region from JWT claims.

    Returns:
        (resolved_region, error_message) - one of them will be None
    """
    region = _resolve_region_from_jwt(jwt_token, workspace)
    if region:
        return region, None

    ws_list = _get_jwt_workspaces(jwt_token)
    available_regions = sorted(
        {ws.get('region') or '?' for ws in ws_list if isinstance(ws, dict)}
    )
    if available_regions:
        return None, (
            f'Multiple regions available in token: {", ".join(available_regions)}. '
            f'Please specify a region parameter.'
        )
    return None, 'No regions found in JWT token.'


def _resolve_region_local(workspace: str | None) -> tuple[str | None, str | None]:
    """Resolve region from token.json configuration.

    Returns:
        (resolved_region, error_message) - one of them will be None
    """
    from utils.token_manager import get_token_manager

    tm = get_token_manager()

    if workspace:
        region = tm.find_region_for_workspace(workspace)
        if region:
            return region, None

    default_region = tm.get_default_region()
    if default_region:
        return default_region, None

    available_regions = tm.get_available_regions()
    if available_regions:
        return None, (
            f'Multiple regions available: {", ".join(sorted(available_regions))}. '
            f'Please specify a region parameter.'
        )
    return None, 'No regions configured. Please run setup first.'


def with_token_validation(func: Callable) -> Callable:
    """Decorator to add automatic token validation to MCP tools.

    Transport mode is determined by ALPACON_MCP_AUTH_ENABLED env var:
    - 'true' (streamable-http): Uses JWT from auth context only.
      Never falls back to token.json.
    - unset/other (stdio): Uses token.json only.
      Never tries JWT auth context.

    Args:
        func: The async function to decorate

    Returns:
        Decorated async function with modified signature (removes _token parameter)
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Remove _token from kwargs if present (MCP doesn't allow _ prefix)
        kwargs.pop('_token', None)

        # Get function signature
        sig = inspect.signature(func)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        arguments = bound_args.arguments

        # Extract region and workspace
        region = arguments.get('region', '')
        workspace = arguments.get('workspace')

        # Validate workspace is present
        if not workspace:
            return error_response('workspace parameter is required')

        # Validate workspace format
        if not validate_workspace_format(workspace):
            return format_validation_error('workspace', workspace)

        auth_enabled = _is_auth_enabled()

        # Auto-detect region if not provided
        if not region:
            if auth_enabled:
                jwt_token = _get_jwt_token()
                if not jwt_token:
                    return error_response(
                        'Authentication required. No JWT token found in request context.'
                    )
                resolved_region, err_msg = _resolve_region_jwt(jwt_token, workspace)
            else:
                resolved_region, err_msg = _resolve_region_local(workspace)

            if err_msg:
                return error_response(err_msg)
            region = resolved_region
            bound_args.arguments['region'] = region

        # Validate region format
        if not validate_region_format(region):
            return format_validation_error('region', region)

        # Validate server_id format if present
        server_id = arguments.get('server_id')
        if server_id is not None and not validate_server_id_format(server_id):
            return format_validation_error('server_id', server_id)

        # Validate server_ids list if present
        server_ids = arguments.get('server_ids')
        if server_ids is not None:
            invalid_ids = [
                sid for sid in server_ids if not validate_server_id_format(sid)
            ]
            if invalid_ids:
                return format_validation_error(
                    'server_ids',
                    invalid_ids,
                    'Each server ID must be in UUID format. (e.g., 550e8400-e29b-41d4-a716-446655440000)',
                )

        # Get the **kwargs dict from bound arguments to inject token
        extra_kwargs = bound_args.arguments.get('kwargs', {})

        if auth_enabled:
            # Streamable-HTTP mode — JWT auth only
            jwt_token = _get_jwt_token()
            if not jwt_token:
                return error_response(
                    'Authentication required. No JWT token found in request context.'
                )
            if not _validate_jwt_workspace(jwt_token, region, workspace):
                return error_response(
                    f'Workspace {workspace}.{region} not authorized by JWT',
                    region=region,
                    workspace=workspace,
                )
            extra_kwargs['token'] = jwt_token
        else:
            # stdio mode — token.json only
            token = validate_token(region, workspace)
            if not token:
                return token_error_response(region, workspace)
            extra_kwargs['token'] = token

        bound_args.arguments['kwargs'] = extra_kwargs

        # Call the original function using bound_args to handle
        # both positional and keyword region correctly
        return await func(*bound_args.args, **bound_args.kwargs)

    # Remove _token parameter from the wrapper signature
    original_sig = inspect.signature(func)
    new_params = [p for p in original_sig.parameters.values() if p.name != '_token']
    wrapper.__signature__ = original_sig.replace(parameters=new_params)  # type: ignore[attr-defined]

    return wrapper


def with_error_handling(func: Callable) -> Callable:
    """Decorator to add consistent error handling to MCP tools.

    This decorator:
    1. Wraps the function in try-except
    2. Logs errors with context
    3. Returns standardized error responses

    Args:
        func: The async function to decorate

    Returns:
        Decorated async function
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract function name for logging
        func_name = func.__name__

        try:
            # Call the original function
            result = await func(*args, **kwargs)
            return result

        except Exception as e:
            # Get workspace and region for context
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            arguments = bound_args.arguments

            workspace = arguments.get('workspace', 'unknown')
            region = arguments.get('region', 'unknown')

            # Log the error with context
            logger.error(
                f'{func_name} failed for {workspace}.{region}: {e}', exc_info=True
            )

            # Return standardized error response
            return error_response(
                f'Failed in {func_name}: {str(e)}', workspace=workspace, region=region
            )

    return wrapper


def with_logging(func: Callable) -> Callable:
    """Decorator to add automatic logging to MCP tools.

    This decorator:
    1. Logs function entry with parameters
    2. Logs successful completion
    3. Logs errors (works with with_error_handling)

    Args:
        func: The async function to decorate

    Returns:
        Decorated async function
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        func_name = func.__name__

        # Get function arguments for logging
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        arguments = bound_args.arguments

        # Create log-safe arguments (exclude sensitive data)
        log_args = {
            k: v
            for k, v in arguments.items()
            if k not in ['_token', 'password', 'secret', 'key']
        }

        # Log function entry
        logger.info(f'{func_name} called with: {log_args}')

        # Call the original function
        result = await func(*args, **kwargs)

        # Log completion if successful
        if isinstance(result, dict) and result.get('status') == 'success':
            logger.info(f'{func_name} completed successfully')

        return result

    return wrapper


def mcp_tool_handler(description: str):
    """Combined decorator for MCP tools that adds all common functionality.

    This decorator combines:
    1. MCP tool registration
    2. Token validation (JWT for streamable-http, token.json for stdio)
    3. Error handling
    4. Logging

    Args:
        description: Tool description for MCP

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        # Apply decorators in order (innermost first)
        func = with_error_handling(func)
        func = with_token_validation(func)
        func = with_logging(func)

        # Register with MCP
        from server import mcp

        return mcp.tool(description=description)(func)

    return decorator
