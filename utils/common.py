"""Common utilities for all MCP tools."""

import importlib.metadata
import json
import os
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


# WorkSession gate error codes returned by alpacon-server
# (utils/error_codes.py, enforced in work_sessions/services.py). The server
# requires every interactive/OAuth caller to scope infrastructure actions under
# a WorkSession; these codes tell the agent how to get inside a valid session.
# Mirrors alpacon-cli's worksession_error.go reason/next-action mapping.
_WORK_SESSION_GATE_NEXT_ACTION: dict[str, str] = {
    'work_session_required': (
        'No Work Session is attached. Create one with work_session_create '
        '(scope covering this operation—"command" for command execution, '
        '"webftp" for file transfers—plus the target server), have a human '
        'approve it out-of-band, then retry passing its id as work_session_id.'
    ),
    'work_session_not_usable': (
        'The attached Work Session is in a terminal state and cannot be used. '
        'Create a new Work Session, get it approved, then retry.'
    ),
    'work_session_expired': (
        'The attached Work Session has expired. Extend it with '
        'work_session_extend, or create a new one, then retry.'
    ),
    'work_session_scope_not_allowed': (
        'The attached Work Session does not include the scope for this '
        'operation. Add the scope with work_session_update (may require '
        'approval) or create a new session with the right scope, then retry.'
    ),
    'work_session_server_not_allowed': (
        'The target server is not in the attached Work Session. Add it with '
        'work_session_update, or create a new session including the server, '
        'then retry.'
    ),
    'work_session_assignee_mismatch': (
        'The attached Work Session is assigned to a different principal. Use a '
        'session assigned to you, or create your own, then retry.'
    ),
}

# Handled separately: the session exists but a human has not approved it yet,
# so it maps to the existing pending-approval flow rather than an error.
_WORK_SESSION_PENDING_CODE = 'work_session_not_active'

_WORK_SESSION_GATE_CODES: frozenset[str] = frozenset(_WORK_SESSION_GATE_NEXT_ACTION) | {
    _WORK_SESSION_PENDING_CODE
}


def work_session_gate_response(code: str, **kwargs: Any) -> dict[str, Any]:
    """Translate a server WorkSession gate error code into an agent-actionable result.

    ``work_session_not_active`` becomes a pending-approval result (a human must
    approve the existing session). Every other gate code becomes an error result
    carrying the gate ``code`` and a ``next_action`` describing how to get inside
    a valid session. See ADR 0014 (zero standing privilege).
    """
    if code == _WORK_SESSION_PENDING_CODE:
        return pending_approval_response(
            'The attached Work Session is not active yet. A human must approve '
            'it out-of-band (Alpacon web console or Slack) before this operation '
            'will run. Poll work_session_get and retry once it is active.',
            category='WORK_SESSION_PENDING',
            **kwargs,
        )
    return error_response(
        f'Operation blocked by the Work Session gate: {code}.',
        code=code,
        next_action=_WORK_SESSION_GATE_NEXT_ACTION[code],
        requires_human_approval=False,
        **kwargs,
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

    gate_code = _extract_work_session_gate_code(result)
    if gate_code is not None:
        return work_session_gate_response(gate_code, **error_kwargs)

    return error_response(
        result.get('message', default_message),
        **error_kwargs,
    )


def _extract_work_session_gate_code(result: dict[str, Any]) -> str | None:
    """Return the WorkSession gate code carried by an http error envelope, if any.

    alpacon-server's exception handler returns 4xx bodies shaped as
    ``{"code": "<error_code>"}``; ``utils.http_client`` carries the raw body in
    the ``response`` key. Returns None when the body is missing, not JSON, or not
    a recognized gate code (so the caller falls back to a generic error).
    """
    raw = result.get('response')
    if not isinstance(raw, str):
        return None
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    code = body.get('code')
    if isinstance(code, str) and code in _WORK_SESSION_GATE_CODES:
        return code
    return None


def resolve_work_session_id(explicit: str | None) -> str | None:
    """Resolve the effective Work Session id: explicit arg > ALPACON_WORK_SESSION env.

    Mirrors alpacon-cli's resolve.go (flag > env). Returns None when neither is set.
    """
    if explicit:
        return explicit
    return os.environ.get('ALPACON_WORK_SESSION', '').strip() or None
