"""Recovery hints for error responses to help LLM self-recover."""

from http import HTTPStatus
from typing import Any

# Hint registry: (status_code, domain) -> {recovery_hints, related_tools}
_HINT_REGISTRY: dict[tuple[int, str], dict[str, list[str]]] = {
    (HTTPStatus.UNAUTHORIZED, 'general'): {
        'recovery_hints': [
            'API token may be expired or invalid.',
            'Re-run setup to refresh your token: uvx alpacon-mcp setup',
        ],
        'related_tools': ['list_workspaces'],
    },
    (HTTPStatus.PAYMENT_REQUIRED, 'general'): {
        'recovery_hints': [
            'This action needs a paid plan. Creating and updating alert rules '
            'and webhooks are gated; reading them, and attaching a rule to a '
            'server, are not.',
            'Retrying will not change the answer. Ask a workspace owner to '
            'upgrade the plan.',
        ],
        'related_tools': ['get_workspace_preferences'],
    },
    (HTTPStatus.FORBIDDEN, 'command'): {
        'recovery_hints': [
            "Check if the API token has 'command_execute' ACL permission.",
            'Use list_command_acls to view current permissions.',
            'Ask a workspace admin to grant command ACL via create_command_acl.',
        ],
        'related_tools': ['list_command_acls', 'create_command_acl'],
    },
    (HTTPStatus.FORBIDDEN, 'server'): {
        'recovery_hints': [
            'Check if you have access to this server.',
            'Use list_server_acls to view current server permissions.',
        ],
        'related_tools': ['list_server_acls', 'create_server_acl'],
    },
    (HTTPStatus.FORBIDDEN, 'file'): {
        'recovery_hints': [
            'Check if you have file access permission for this server.',
            'Use list_file_acls to view current file permissions.',
        ],
        'related_tools': ['list_file_acls', 'create_file_acl'],
    },
    (HTTPStatus.FORBIDDEN, 'general'): {
        'recovery_hints': [
            'Check if your token has the required permissions for this action.',
            'Contact your workspace administrator for access.',
        ],
        'related_tools': [],
    },
    (HTTPStatus.NOT_FOUND, 'server'): {
        'recovery_hints': [
            'The server ID may be incorrect. Server IDs must be UUIDs.',
            'Use list_servers to find the correct server UUID.',
        ],
        'related_tools': ['list_servers'],
    },
    (HTTPStatus.NOT_FOUND, 'user'): {
        'recovery_hints': [
            'The user may not exist in this workspace.',
            'Use list_iam_users to check available users.',
        ],
        'related_tools': ['list_iam_users'],
    },
    (HTTPStatus.NOT_FOUND, 'alert'): {
        'recovery_hints': [
            'The alert or alert rule ID may be incorrect.',
            'Use list_alerts or get_alert_rules to find valid IDs.',
            'A 404 on attach_alert_rule or detach_alert_rule means a wrong server_id.',
            'A bad alert rule ID gives a 400 instead of a 404.',
        ],
        'related_tools': ['list_alerts', 'get_alert_rules', 'list_servers'],
    },
    (HTTPStatus.NOT_FOUND, 'general'): {
        'recovery_hints': [
            'The resource was not found. Check the ID or name.',
            'Use the corresponding list tool to find valid IDs.',
        ],
        'related_tools': [],
    },
    (HTTPStatus.TOO_MANY_REQUESTS, 'general'): {
        'recovery_hints': [
            'Too many requests. Wait a few seconds before retrying.',
        ],
        'related_tools': [],
    },
    (HTTPStatus.INTERNAL_SERVER_ERROR, 'general'): {
        'recovery_hints': [
            'The server encountered an internal error. Try again in a moment.',
            'If the issue persists, check server health.',
        ],
        'related_tools': [],
    },
}


def _detect_error_domain(
    status_code: int | None,
    message: str,
    tool_name: str | None = None,
    endpoint: str | None = None,
) -> str:
    """Detect the error domain from context clues."""
    msg_lower = message.lower()
    tool_lower = (tool_name or '').lower()
    ep_lower = (endpoint or '').lower()

    if 'command' in msg_lower or 'command' in tool_lower:
        return 'command'
    if (
        any(k in msg_lower for k in ('webftp', 'upload', 'download', 'file'))
        or 'webftp' in tool_lower
    ):
        return 'file'
    if any(k in msg_lower for k in ('server',)) or 'server' in tool_lower:
        return 'server'
    if 'user' in msg_lower or 'iam' in tool_lower:
        return 'user'
    if 'alert' in msg_lower or 'alert' in tool_lower:
        return 'alert'
    if '/api/events/commands/' in ep_lower:
        return 'command'
    if '/api/webftp/' in ep_lower:
        return 'file'
    if '/api/servers/' in ep_lower:
        return 'server'
    if '/api/iam/' in ep_lower:
        return 'user'

    return 'general'


def _parse_status_code(raw: int | str | None) -> int | None:
    """Normalize status_code to int, or None if missing/invalid."""
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _copy_hints(hints: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return a shallow copy of a hints entry to protect the registry."""
    return {
        'recovery_hints': list(hints['recovery_hints']),
        'related_tools': list(hints['related_tools']),
    }


def get_recovery_hints(
    status_code: int | str | None = None,
    message: str = '',
    tool_name: str | None = None,
    endpoint: str | None = None,
) -> dict[str, list[str]]:
    """Look up recovery hints for an error.

    Args:
        status_code: HTTP status code (int or string) or None
        message: Error message text
        tool_name: Name of the tool that failed
        endpoint: API endpoint that was called

    Returns:
        Dict with 'recovery_hints' and 'related_tools' lists.
        Returns empty lists if no hints match.
    """
    code = _parse_status_code(status_code)

    # No hints when status code is missing or unrecognized
    if code is None:
        return {'recovery_hints': [], 'related_tools': []}

    domain = _detect_error_domain(code, message, tool_name, endpoint)

    # Try domain-specific first, then general fallback
    hints = _HINT_REGISTRY.get((code, domain))
    if hints:
        return _copy_hints(hints)

    hints = _HINT_REGISTRY.get((code, 'general'))
    if hints:
        return _copy_hints(hints)

    return {'recovery_hints': [], 'related_tools': []}


def enrich_error_response(
    response: dict[str, Any],
    tool_name: str | None = None,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Add recovery hints to an error response dict.

    Only modifies dicts that look like error responses (have status='error'
    or 'error' key). Returns the original dict unmodified for success
    responses.

    Args:
        response: The response dict to enrich
        tool_name: Name of the tool that produced the error
        endpoint: API endpoint that was called

    Returns:
        The response dict, potentially with recovery_hints and related_tools added
    """
    if not isinstance(response, dict):
        return response

    is_error = response.get('status') == 'error' or 'error' in response
    if not is_error:
        return response

    # Already enriched — don't overwrite
    if 'recovery_hints' in response:
        return response

    status_code = response.get('status_code') or response.get('error_code')
    message = response.get('message', '')

    hints = get_recovery_hints(
        status_code=status_code,
        message=message,
        tool_name=tool_name,
        endpoint=endpoint,
    )

    if hints['recovery_hints']:
        response['recovery_hints'] = hints['recovery_hints']
    if hints['related_tools']:
        response['related_tools'] = hints['related_tools']

    return response
