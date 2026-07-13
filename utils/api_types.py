"""Shared type definitions for tool responses and API-boundary payloads.

``Any`` is quarantined in this module: ``ApiPayload`` (and the other
aliases below) are the only sanctioned appearances of ``Any`` in the
codebase. Every other module imports these aliases instead of using
``Any`` directly, so untyped data can only enter through named boundary
functions typed with these aliases.
"""

from collections.abc import MutableMapping
from typing import Any, Literal, NotRequired, TypedDict, TypeGuard

# Raw JSON crossing the Alpacon API boundary. The single sanctioned Any.
type ApiPayload = dict[str, Any] | list[Any]

# Decoded JWT claims from Auth0 (external schema, not ours).
type JwtClaims = dict[str, Any]

# ASGI protocol messages (key set varies by message type).
type AsgiMessage = MutableMapping[str, Any]


class ApiErrorEnvelope(TypedDict):
    """Standardized error shape AlpaconHTTPClient returns on failure."""

    error: str
    message: str
    status_code: NotRequired[int]
    response: NotRequired[str]
    mfa_required: NotRequired[bool]
    request_index: NotRequired[int]


type ApiResult = ApiPayload | ApiErrorEnvelope


def is_api_error(result: object) -> TypeGuard[ApiErrorEnvelope]:
    """Narrow an ApiResult to the standardized error envelope."""
    return isinstance(result, dict) and 'error' in result


class ToolKwargs(TypedDict, total=False):
    """Keyword args injected into tool functions by with_token_validation."""

    token: str


class ResponseContext(TypedDict, total=False):
    """Superset of context keys tool code attaches to response envelopes.

    Field list is the exhaustive result of an AST-based scan (Task 2 Step 1)
    over every keyword argument passed to success_response, error_response,
    pending_approval_response, work_session_gate_response, and
    unwrap_http_result across tools/ and utils/. Kept alphabetical.

    ``data`` and ``message`` are deliberately not listed here even though both
    are attached to response envelopes: each is instead an explicit named
    parameter on the response-builder functions that need it (mypy's Unpack
    machinery rejects a function whose own parameter name overlaps with a key
    of its ``**kwargs: Unpack[ResponseContext]`` type).
    """

    acl_id: str
    action: str
    alert_id: str
    analysis_id: str
    app_id: str
    app_name: str
    architecture: str | None
    ca_id: str
    certificate_id: str
    code: str
    command: str
    command_id: str
    csr_id: str
    deploy_shell_results: dict[str, object]
    details: object
    device: str | None
    download_url: str | None
    email: str
    end_date: str | None
    entry_id: str
    error_type: str
    event_id: str
    execution_type: str
    expires_in: str
    failed_count: int
    file_id: str
    file_size: int
    group_id: str
    group_name: str
    groupname_filter: str | None
    limit: int
    local_file_path: str
    log_id: str
    login_enabled_only: bool
    membership_id: str
    metric_type: str
    metric_types: list[str]
    next_action: str
    note_id: str
    note_title: str
    package_name: str | None
    region: str
    remote_directory: str
    remote_file_path: str
    remote_paths: list[str]
    reporter: str | None
    request_id: str
    requires_human_approval: bool
    resource_type: str
    revoke_id: str
    rule_id: str
    search_query: str
    server_id: str | None
    session_id: str | None
    shell: str
    start_date: str | None
    status_code: int
    subscription_id: str
    successful_count: int
    sudo_denial: object
    sudo_hint: str
    tip: str
    token_id: str
    total_files: int
    total_servers: int
    transfer_type: str
    upload_url: str
    user_id: str
    username: str | None
    username_filter: str | None
    webhook_id: str
    workspace: str


class SuccessResponse(ResponseContext):
    status: Literal['success']
    data: NotRequired[object]
    message: NotRequired[str]


class ErrorResponse(ResponseContext):
    status: Literal['error']
    message: str


class PendingApprovalResponse(ResponseContext):
    status: Literal['pending_approval']
    category: str
    message: str
    approvable_by_agent: bool
    data: NotRequired[object]
    # requires_human_approval / next_action are inherited (NotRequired) from
    # ResponseContext rather than re-declared here: mypy rejects narrowing an
    # inherited field from NotRequired to Required in a TypedDict subclass.
    # pending_approval_response() always sets both at runtime regardless.


type ToolResponse = SuccessResponse | ErrorResponse | PendingApprovalResponse
