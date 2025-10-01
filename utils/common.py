"""Common utilities for all MCP tools."""

from typing import Dict, Any, Optional
from utils.token_manager import get_token_manager
from utils.logger import get_logger

# Initialize shared instances
token_manager = get_token_manager()
logger = get_logger("common")


def validate_token(region: str, workspace: str) -> Optional[str]:
    """Validate and retrieve token for given region and workspace.

    Args:
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name

    Returns:
        Token string if found, None otherwise
    """
    token = token_manager.get_token(region, workspace)
    if not token:
        logger.error(f"No token found for {workspace}.{region}")
    return token


def error_response(message: str, **kwargs) -> Dict[str, Any]:
    """Create standardized error response.

    Args:
        message: Error message
        **kwargs: Additional fields to include in response

    Returns:
        Standardized error response dict
    """
    response = {
        "status": "error",
        "message": message
    }
    response.update(kwargs)
    return response


def success_response(data: Any = None, **kwargs) -> Dict[str, Any]:
    """Create standardized success response.

    Args:
        data: Response data
        **kwargs: Additional fields to include in response

    Returns:
        Standardized success response dict
    """
    response = {
        "status": "success"
    }
    if data is not None:
        response["data"] = data
    response.update(kwargs)
    return response


def token_error_response(region: str, workspace: str) -> Dict[str, Any]:
    """Create standardized token error response.

    Args:
        region: Region
        workspace: Workspace name

    Returns:
        Token error response
    """
    return error_response(
        f"No token found for {workspace}.{region}. Please set token first.",
        region=region,
        workspace=workspace
    )


async def handle_api_call(
    http_client,
    method: str,
    region: str,
    workspace: str,
    endpoint: str,
    token: str,
    **kwargs
) -> Dict[str, Any]:
    """Handle API calls with consistent error handling.

    Args:
        http_client: HTTP client instance
        method: HTTP method (get, post, put, delete)
        region: Region
        workspace: Workspace name
        endpoint: API endpoint
        token: Authentication token
        **kwargs: Additional arguments for the API call

    Returns:
        API response or error response
    """
    try:
        # Get the method function
        api_method = getattr(http_client, method.lower())

        # Make the API call
        result = await api_method(
            region=region,
            workspace=workspace,
            endpoint=endpoint,
            token=token,
            **kwargs
        )

        # Check for HTTP client errors
        if isinstance(result, dict) and "error" in result:
            return error_response(
                result.get("message", str(result.get("error", "Unknown error"))),
                region=region,
                workspace=workspace
            )

        return result

    except Exception as e:
        logger.error(f"API call failed: {e}", exc_info=True)
        raise