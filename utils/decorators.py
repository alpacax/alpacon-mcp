"""Decorators for MCP tools to reduce boilerplate code."""

from functools import wraps
from typing import Callable, Dict, Any
import inspect
from utils.common import validate_token, token_error_response, success_response, error_response
from utils.logger import get_logger

logger = get_logger("decorators")


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

        if not workspace:
            return error_response("workspace parameter is required")

        # Validate token
        token = validate_token(region, workspace)
        if not token:
            return token_error_response(region, workspace)

        # Add token to kwargs for the function
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
                f"{func_name} failed for {workspace}.{region}: {e}",
                exc_info=True
            )

            # Return standardized error response
            return error_response(
                f"Failed in {func_name}: {str(e)}",
                workspace=workspace,
                region=region
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
            k: v for k, v in arguments.items()
            if k not in ['_token', 'password', 'secret', 'key']
        }

        # Log function entry
        logger.info(f"{func_name} called with: {log_args}")

        # Call the original function
        result = await func(*args, **kwargs)

        # Log completion if successful
        if isinstance(result, dict) and result.get('status') == 'success':
            logger.info(f"{func_name} completed successfully")

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