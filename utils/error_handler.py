"""Enhanced error handling utilities for Alpacon MCP server."""

import re
import uuid
from typing import Dict, Any, Optional, List
from utils.logger import get_logger

logger = get_logger("error_handler")


class ValidationError(Exception):
    """Custom exception for input validation errors."""
    def __init__(self, field: str, value: Any, message: str):
        self.field = field
        self.value = value
        self.message = message
        super().__init__(f"Validation error in {field}: {message}")


def validate_workspace_format(workspace: str) -> bool:
    """Validate workspace name format.

    Args:
        workspace: Workspace name to validate

    Returns:
        True if valid, False otherwise
    """
    if not workspace or not isinstance(workspace, str):
        return False

    # Workspace should be alphanumeric with possible hyphens/underscores
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$'
    return bool(re.match(pattern, workspace)) and len(workspace) <= 63


def validate_region_format(region: str) -> bool:
    """Validate region format.

    Args:
        region: Region to validate

    Returns:
        True if valid, False otherwise
    """
    if not region or not isinstance(region, str):
        return False

    # Known regions: ap1, us1, eu1, dev
    valid_regions = {'ap1', 'us1', 'eu1', 'dev'}
    return region in valid_regions


def validate_server_id_format(server_id: str) -> bool:
    """Validate server ID (should be UUID format).

    Args:
        server_id: Server ID to validate

    Returns:
        True if valid UUID, False otherwise
    """
    if not server_id or not isinstance(server_id, str):
        return False

    try:
        uuid.UUID(server_id)
        return True
    except ValueError:
        return False


def validate_file_path(file_path: str, allow_relative: bool = False) -> bool:
    """Validate file path for security.

    Args:
        file_path: File path to validate
        allow_relative: Whether to allow relative paths

    Returns:
        True if path is safe, False otherwise
    """
    if not file_path or not isinstance(file_path, str):
        return False

    # Check for path traversal attempts
    dangerous_patterns = ['../', '..\\', '/./', '\\.\\']
    if any(pattern in file_path for pattern in dangerous_patterns):
        return False

    # Check for absolute path requirement
    if not allow_relative and not file_path.startswith('/'):
        return False

    # Check for null bytes or other dangerous characters
    if '\x00' in file_path or any(char in file_path for char in ['<', '>', '|', '*', '?']):
        return False

    return True


def format_user_friendly_error(error_code: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Format technical errors into user-friendly messages.

    Args:
        error_code: HTTP status code or error type
        context: Additional context for error formatting

    Returns:
        Formatted error response with user-friendly message and suggestions
    """
    context = context or {}

    error_messages = {
        "400": {
            "message": "Bad request.",
            "suggestion": "Please check your input and try again."
        },
        "401": {
            "message": "Authentication failed.",
            "suggestion": "Please check your API token or set a new token."
        },
        "403": {
            "message": "Access denied.",
            "suggestion": "Please check if you have permission to perform this action."
        },
        "404": {
            "message": "Resource not found.",
            "suggestion": "Please check the server ID or resource name."
        },
        "429": {
            "message": "Too many requests.",
            "suggestion": "Please wait a moment and try again."
        },
        "500": {
            "message": "Server encountered a temporary problem.",
            "suggestion": "Please try again later. Contact support if the problem persists."
        },
        "502": {
            "message": "Gateway error occurred.",
            "suggestion": "Service is temporarily unavailable. Please try again later."
        },
        "503": {
            "message": "Service unavailable.",
            "suggestion": "Server is under maintenance or overloaded. Please try again later."
        },
        "timeout": {
            "message": "Request timed out.",
            "suggestion": "Please check your network connection and try again."
        },
        "network": {
            "message": "Network connection failed.",
            "suggestion": "Please check your internet connection and try again."
        },
        "validation": {
            "message": "Invalid input.",
            "suggestion": "Please check the input format and try again."
        }
    }

    error_info = error_messages.get(error_code, {
        "message": "Unknown error occurred.",
        "suggestion": "Please try again later."
    })

    # Add specific context if available
    if error_code == "404" and context.get("server_id"):
        error_info["message"] = f"Server '{context['server_id']}' not found."
    elif error_code == "404" and context.get("workspace"):
        error_info["message"] = f"Workspace '{context['workspace']}' not found."

    result = {
        "status": "error",
        "error_code": error_code,
        "message": error_info["message"],
        "suggestion": error_info["suggestion"]
    }

    if context:
        result["context"] = context

    logger.debug(f"Formatted user-friendly error: {result}")
    return result


def format_validation_error(field: str, value: Any, expected_format: str = None) -> Dict[str, Any]:
    """Format validation error with helpful message.

    Args:
        field: Field name that failed validation
        value: The invalid value
        expected_format: Description of expected format

    Returns:
        Formatted validation error response
    """
    message = f"'{field}' value is invalid."

    if expected_format:
        suggestion = f"Expected format: {expected_format}"
    else:
        suggestions = {
            "workspace": "Only alphanumeric characters, hyphens (-), and underscores (_) allowed. Length: 1-63 characters.",
            "region": "Supported regions: ap1, us1, eu1, dev",
            "server_id": "Server ID must be in UUID format. (e.g., 550e8400-e29b-41d4-a716-446655440000)",
            "file_path": "Use absolute paths and avoid dangerous characters (.., <, >, |, *, ?)."
        }
        suggestion = suggestions.get(field, "Please enter in correct format.")

    return {
        "status": "error",
        "error_code": "validation",
        "field": field,
        "value": str(value)[:100],  # Limit value length for security
        "message": message,
        "suggestion": suggestion
    }


class CircuitBreaker:
    """Circuit breaker pattern implementation for API calls."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open

    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
            else:
                raise Exception("Circuit breaker is open - service temporarily unavailable")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        import time
        return time.time() - self.last_failure_time >= self.recovery_timeout

    def _on_success(self):
        """Reset circuit breaker on successful call."""
        self.failure_count = 0
        self.state = "closed"

    def _on_failure(self):
        """Handle failure - may open circuit."""
        import time
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


# Global circuit breakers for different services
api_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)