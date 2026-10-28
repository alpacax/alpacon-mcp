"""Enhanced error handling utilities for Alpacon MCP server."""

import re
import uuid
from typing import Literal, TypeGuard

from mcp.server.mcpserver.exceptions import ToolError

# 'dev' is internal-only: tool schemas refuse it, so only region resolution yields it.
type ServedRegion = Literal['ap1', 'us1']
type Region = ServedRegion | Literal['dev']
SERVED_REGIONS: tuple[ServedRegion, ...] = ('ap1', 'us1')
VALID_REGIONS: tuple[Region, ...] = (*SERVED_REGIONS, 'dev')


class UpstreamAuthError(ToolError):
    """Re-authentication is required (a ToolError, logged at INFO). Raising only cuts
    the call short; request_signal records what the middleware reads."""

    def __init__(self, mfa_required: bool = False, source: str = ''):
        self.mfa_required = mfa_required
        self.source = source
        msg = 'MFA verification required' if mfa_required else 'Authentication expired'
        super().__init__(msg)


def validate_workspace_format(workspace: str) -> bool:
    """Alphanumeric with inner hyphens/underscores, at most 63 characters."""
    if not workspace or not isinstance(workspace, str):
        return False

    # Workspace should be alphanumeric with possible hyphens/underscores
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$'
    return bool(re.match(pattern, workspace)) and len(workspace) <= 63


def validate_region_format(region: object) -> TypeGuard[Region]:
    if not region or not isinstance(region, str):
        return False

    return region in VALID_REGIONS


def validate_uuid_format(value: str) -> bool:
    if not value or not isinstance(value, str):
        return False

    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def validate_file_path(file_path: str, allow_relative: bool = False) -> bool:
    """True only for a path that is absolute unless allow_relative, holds no ../ or /./
    (either slash), no null byte and none of <>|*?."""
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
    field: str, value: object, expected_format: str | None = None
) -> dict[str, str]:
    """Build a validation error response; expected_format overrides the per-field
    hint."""
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


def uuid_field_error(field: str, value: str) -> dict[str, str] | None:
    """Return the validation error for a non-UUID `value`, or None if it is one."""
    if validate_uuid_format(value):
        return None
    return format_validation_error(
        field,
        value,
        'Must be a valid UUID. Example: 550e8400-e29b-41d4-a716-446655440000',
    )
