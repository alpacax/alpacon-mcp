"""Enhanced error handling utilities for Alpacon MCP server."""

import re
import uuid
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

# 'dev' is internal-only: the validator accepts it, but it is never advertised.
SERVED_REGIONS = ('ap1', 'us1')
VALID_REGIONS = (*SERVED_REGIONS, 'dev')


class UpstreamAuthError(ToolError):
    """Raised when re-authentication is required for the Alpacon API.

    Used in remote (streamable-http) mode to signal that the current call
    requires OAuth re-authentication. As a ``ToolError``, the SDK logs it
    at INFO without a traceback and keeps the message intact for the client.

    Typically raised when the upstream Alpacon API returns 401 or when
    local checks (such as MFA pre-checks) determine that the current
    session requires re-authentication. The ``mfa_required`` flag
    indicates whether multi-factor verification is specifically needed.

    Raising this only cuts the current call short; the signal the
    middleware reads is recorded separately via
    ``utils.request_signal.signal_upstream_auth_error``.
    """

    def __init__(self, mfa_required: bool = False, source: str = ''):
        self.mfa_required = mfa_required
        self.source = source
        msg = 'MFA verification required' if mfa_required else 'Authentication expired'
        super().__init__(msg)


class ValidationError(Exception):
    """Custom exception for input validation errors."""

    def __init__(self, field: str, value: Any, message: str):
        self.field = field
        self.value = value
        self.message = message
        super().__init__(f'Validation error in {field}: {message}')


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

    return region in VALID_REGIONS


def validate_uuid_format(value: str) -> bool:
    """Validate that a value is a UUID.

    Args:
        value: Value to validate

    Returns:
        True if valid UUID, False otherwise
    """
    if not value or not isinstance(value, str):
        return False

    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def validate_server_id_format(server_id: str) -> bool:
    """Validate server ID (should be UUID format).

    Args:
        server_id: Server ID to validate

    Returns:
        True if valid UUID, False otherwise
    """
    return validate_uuid_format(server_id)


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
    if '\x00' in file_path or any(
        char in file_path for char in ['<', '>', '|', '*', '?']
    ):
        return False

    return True


def format_validation_error(
    field: str, value: Any, expected_format: str | None = None
) -> dict[str, Any]:
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
        suggestion = f'Expected format: {expected_format}'
    else:
        suggestions = {
            'workspace': 'Only alphanumeric characters, hyphens (-), and underscores (_) allowed. Length: 1-63 characters.',
            'region': f'Supported regions: {", ".join(SERVED_REGIONS)}',
            'server_id': 'Server ID must be in UUID format. (e.g., 550e8400-e29b-41d4-a716-446655440000)',
            'session_id': 'Session ID must be in UUID format. (e.g., 550e8400-e29b-41d4-a716-446655440000)',
            'file_path': 'Use absolute paths and avoid dangerous characters (.., <, >, |, *, ?).',
        }
        suggestion = suggestions.get(field, 'Please enter in correct format.')

    return {
        'status': 'error',
        'error_code': 'validation',
        'field': field,
        'value': str(value)[:100],  # Limit value length for security
        'message': message,
        'suggestion': suggestion,
    }
