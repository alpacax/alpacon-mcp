"""Common utilities for all MCP tools."""

import importlib.metadata
import platform
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
MCP_USER_AGENT = f'alpacon-mcp/{MCP_VERSION} (MCP-Server; persistent-pool) Python/{platform.python_version()}'


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


# The human-resolvable next action differs by category: SUDO_APPROVAL_REQUIRED /
# WORK_SESSION_PENDING need an out-of-band approval, while SUDO_PRESENCE_REQUIRED
# is an MFA step-up and SUDO_NO_WORKSESSION_POLICY is a scope addition — none of
# which the agent can perform itself. APPROVAL_DECISION_HUMAN_ONLY is a pure
# explanation that approving/rejecting is human-only; there is nothing to retry.
_NEXT_ACTION_BY_CATEGORY: dict[str, str] = {
    'SUDO_APPROVAL_REQUIRED': (
        'A human must approve this out-of-band (Alpacon web console or Slack). '
        'You cannot approve it yourself. Wait for approval, then retry; do not '
        'repeatedly resubmit.'
    ),
    'WORK_SESSION_PENDING': (
        'A human must approve this Work Session out-of-band (Alpacon web console '
        'or Slack) before it activates. You cannot approve it yourself. Wait for '
        'approval, then retry.'
    ),
    'SUDO_PRESENCE_REQUIRED': (
        'A human must complete a fresh MFA step-up out-of-band, then retry. You '
        'cannot complete MFA yourself.'
    ),
    'SUDO_NO_WORKSESSION_POLICY': (
        'This command is not covered by the Work Session sudo policy. A human '
        'must add it to the session scope (which may itself require approval), '
        'then retry. You cannot grant it yourself.'
    ),
    'APPROVAL_DECISION_HUMAN_ONLY': (
        'Surface this request to a human reviewer; only a human can approve or '
        'reject it, out-of-band (Alpacon web console or Slack). You cannot make '
        'this decision and no MCP tool does it for you. Wait for the human '
        'decision — there is nothing for you to retry or resubmit.'
    ),
}
_DEFAULT_NEXT_ACTION = _NEXT_ACTION_BY_CATEGORY['SUDO_APPROVAL_REQUIRED']


def pending_approval_response(
    message: str,
    *,
    category: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a structured "pending human approval" result (ADR 0015).

    AI agents reaching Alpacon through MCP are a request/execution surface and
    cannot approve privileged-access requests. When an action needs human
    approval (a sudo HITL denial such as ``SUDO_APPROVAL_REQUIRED``, or a Work
    Session that lands ``pending``), the agent must be told—in a
    machine-actionable way—that the request is pending, a human must approve it
    out-of-band (web/Slack), and the agent cannot approve it itself. This keeps
    the agent waiting/escalating instead of retry-spamming or hallucinating
    success.

    The result uses ``status='pending_approval'`` (distinct from ``success`` and
    ``error``) plus stable boolean flags so a caller can branch without parsing
    free text. Only the denial *category* and the next action are disclosed—
    never internal risk scores or factors.

    Args:
        message: Human-readable explanation of what is pending and what to do.
        category: Stable machine code for the denial/pending category
            (e.g. ``SUDO_APPROVAL_REQUIRED``, ``WORK_SESSION_PENDING``).
        **kwargs: Additional context fields (region, workspace, ids, raw data).

    Returns:
        Structured pending-approval response dict.
    """
    # Apply caller context first so the fixed, security-relevant fields below
    # (the flags and category) always win and cannot be overridden by a kwarg.
    response: dict[str, Any] = {**kwargs}
    response.update(
        {
            'status': 'pending_approval',
            'category': category,
            'message': message,
            # Machine-actionable flags: the agent must wait/escalate, not act.
            'requires_human_approval': True,
            'approvable_by_agent': False,
            'next_action': _NEXT_ACTION_BY_CATEGORY.get(category, _DEFAULT_NEXT_ACTION),
        }
    )
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
