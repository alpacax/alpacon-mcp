"""Decorators for MCP tools to reduce boilerplate code."""

import inspect
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

# Lazy imports for auth module to avoid circular imports and
# keep stdio/SSE mode working without Auth0 config
_auth_module = None

logger = get_logger('decorators')


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


def _validate_jwt_workspace(jwt_token: str, region: str, workspace: str) -> bool:
    """Validate that the JWT authorizes access to the given workspace/region."""
    try:
        import jwt as pyjwt

        from utils.auth import extract_workspaces, match_workspace

        # Decode without verification — already verified by FastMCP middleware
        claims = pyjwt.decode(jwt_token, options={'verify_signature': False})

        import os

        namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/')
        workspaces = extract_workspaces(claims, namespace)
        return match_workspace(workspaces, region, workspace)
    except Exception as e:
        logger.error(f'JWT workspace validation failed: {e}')
        return False


def with_token_validation(func: Callable) -> Callable:
    """Decorator to add automatic token validation to MCP tools.

    This decorator:
    1. Extracts region and workspace from function arguments
    2. Validates the token exists
    3. Returns error response if token is missing
    4. Adds token to kwargs if valid

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
        region = arguments.get('region', 'ap1')
        workspace = arguments.get('workspace')

        # Validate region format
        if not validate_region_format(region):
            return format_validation_error('region', region)

        # Validate workspace is present
        if not workspace:
            return error_response('workspace parameter is required')

        # Validate workspace format
        if not validate_workspace_format(workspace):
            return format_validation_error('workspace', workspace)

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

        # Try JWT auth first (HTTP transport mode)
        jwt_token = _get_jwt_token()
        if jwt_token is not None:
            # JWT mode — validate workspace access from JWT claims
            if not _validate_jwt_workspace(jwt_token, region, workspace):
                return error_response(
                    f'Workspace {workspace}.{region} not authorized by JWT',
                    region=region,
                    workspace=workspace,
                )
            # Pass JWT through for downstream API calls
            kwargs['token'] = jwt_token
        else:
            # stdio/SSE mode — use token.json lookup
            token = validate_token(region, workspace)
            if not token:
                return token_error_response(region, workspace)
            kwargs['token'] = token

        # Call the original function
        return await func(*args, **kwargs)

    # Remove _token parameter from the wrapper signature
    original_sig = inspect.signature(func)
    new_params = [p for p in original_sig.parameters.values() if p.name != '_token']
    wrapper.__signature__ = original_sig.replace(parameters=new_params)

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
    2. Token validation
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
