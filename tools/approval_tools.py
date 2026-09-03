"""Approval and sudo policy tools for Alpacon MCP server.

ADR 0015 (out-of-band approval channel): AI agents reach Alpacon through MCP and
are a request/execution surface only. They CANNOT approve or reject
privileged-access requests—the Alpacon server refuses approve/reject from
agent/token channels with HTTP 403. These tools therefore expose approval
requests read-only (list/get) so an agent can observe what is pending and tell a
human, but provide no approve/reject mutation. The agent must escalate to a human
who approves out-of-band (Alpacon web console or Slack).
"""

from typing import Any

from utils.api_call import http_call_response
from utils.common import build_list_params, pending_approval_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, READ_ONLY

# ===============================
# APPROVAL REQUEST TOOLS
# ===============================


@mcp_tool_handler(
    description='List pending and historical approval requests in a workspace. Returns request ID, type, status, and requester details. Filterable by status (pending, approved, rejected, cancelled, expired). Use this to review access requests that need approval or check approval history.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'approval requests pending review'},
)
async def list_approval_requests(
    workspace: str,
    status: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List approval requests.

    Args:
        workspace: Workspace name. Required parameter
        status: Filter by status: pending, approved, rejected (optional)
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Approval requests list response
    """
    token = kwargs.get('token')

    params = build_list_params(page=page, page_size=page_size, status=status)

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/approvals/approvals/',
        token=token,
        default_message='Failed to list approval requests',
        params=params,
    )


@mcp_tool_handler(
    description='Get detailed information about a specific approval request by its ID. Returns requester, request type, reason, status, and timestamps. Use this when you need full details about a single approval request.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'approval request detail'},
)
async def get_approval_request(
    request_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get approval request details by ID.

    Args:
        request_id: Approval request ID to retrieve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Approval request details response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'/api/approvals/approvals/{request_id}/',
        token=token,
        default_message='Failed to get approval request',
        request_id=request_id,
    )


# ===============================
# APPROVAL DECISION (HUMAN-ONLY, OUT-OF-BAND)
# ===============================
#
# Per ADR 0015 there is intentionally NO approve_request / reject_request tool.
# An AI agent is the requester/executor and must never be the approver:
# approving its own (or any) privileged-access request would defeat the
# human-in-the-loop control. The Alpacon server enforces this server-side by
# refusing approve/reject from agent/token channels with HTTP 403, so even a
# direct POST would fail; we do not expose such a tool here. To act on a pending
# request, use list_approval_requests / get_approval_request to observe it, then
# escalate to a human who approves it out-of-band (Alpacon web console or Slack).


@mcp_tool_handler(
    description='Explains how a pending approval request gets decided. Approval and rejection are human-only and happen out-of-band (Alpacon web console or Slack); an AI agent cannot approve or reject requests and there is no MCP tool to do so. Use this to understand what to tell a human, or after you hit SUDO_APPROVAL_REQUIRED or a pending Work Session. Related: list_approval_requests (observe pending requests), get_approval_request (single request detail).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'approve reject approval decision human out-of-band'},
)
async def explain_approval_decision(
    workspace: str,
    request_id: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Explain that approving/rejecting a request is a human-only, out-of-band action.

    This tool performs no mutation and contacts no server endpoint—an agent must
    never be the approver. It returns the structured ADR 0015 pending-approval
    guidance so the agent waits/escalates instead of attempting to self-approve.

    Args:
        workspace: Workspace name. Required parameter
        request_id: Approval request ID this guidance refers to (optional)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Structured pending-approval guidance (no approve/reject is performed)
    """
    context: dict[str, Any] = {'region': region, 'workspace': workspace}
    if request_id is not None:
        context['request_id'] = request_id

    return pending_approval_response(
        'Approval requests can only be approved or rejected by a human, '
        'out-of-band (Alpacon web console or Slack). As an AI agent you cannot '
        'approve or reject this request, and no MCP tool can do it for you. '
        'Surface the request to a human reviewer and wait for their decision.',
        category='APPROVAL_DECISION_HUMAN_ONLY',
        **context,
    )


# ===============================
# SUDO POLICY TOOLS
# ===============================


@mcp_tool_handler(
    description='List sudo policies that define elevated privilege rules. Returns policy names, allowed commands, assigned users/servers, and validity periods. Filterable by user UUID or server UUID. Use this to audit which sudo privileges are configured in the workspace.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'sudo policy privilege elevation rules'},
)
async def list_sudo_policies(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    user: str | None = None,
    server_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List sudo policies.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)
        user: Filter by user UUID the policy applies to (optional)
        server_id: Filter by server UUID the policy applies to (optional)

    Returns:
        Sudo policies list response
    """
    token = kwargs.get('token')

    params = build_list_params(
        page=page,
        page_size=page_size,
        user=user,
        server=server_id,
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/sudo/policies/',
        token=token,
        default_message='Failed to list sudo policies',
        params=params,
    )


@mcp_tool_handler(
    description=(
        'Request a sudo policy: ask for named commands to be allowed under sudo on named servers. '
        'This creates an approval request, not a policy—an admin must approve it out-of-band '
        '(Alpacon web console or Slack) before the policy exists, and the tool returns '
        'status="pending_approval". Omitting users scopes the approved policy to the requester '
        'alone, not to the whole workspace, and the server reports no error when it narrows it '
        'that way; a non-superuser may name only themselves. An MFA-bypass policy cannot be '
        'requested here at all—the server refuses it on this endpoint, and such a policy needs an '
        'enterprise plan and a Work Session binding a human sets up. '
        'Related: list_sudo_policies (audit existing policies), list_approval_requests (watch the '
        'request), explain_approval_decision (what a human has to do).'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'sudo policy request privilege elevation approval'},
)
async def request_sudo_policy(
    workspace: str,
    servers: list[str],
    commands: list[str],
    reason: str,
    users: list[str] | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Request a sudo policy that an admin must approve.

    Args:
        workspace: Workspace name. Required parameter
        servers: Server UUIDs the policy should cover. Required parameter
        commands: Command patterns to allow under sudo. Required parameter
        reason: Justification shown to the approver. Required parameter
        users: User UUIDs the policy should cover (optional; omitting it scopes
            the approved policy to the requester alone, and a non-superuser may
            name only themselves)
        valid_from: ISO 8601 start of the validity window (optional)
        valid_until: ISO 8601 end of the validity window (optional)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Pending-approval response carrying the created approval request
    """
    token = kwargs.get('token')

    policy_request: dict[str, Any] = {
        'servers': servers,
        'commands': commands,
        'reason': reason,
    }
    if users is not None:
        policy_request['users'] = users
    if valid_from is not None:
        policy_request['valid_from'] = valid_from
    if valid_until is not None:
        policy_request['valid_until'] = valid_until

    result = await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint='/api/sudo/policy-requests/',
        token=token,
        default_message='Failed to request sudo policy',
        data=policy_request,
    )
    if result.get('status') != 'success':
        return result

    return pending_approval_response(
        'The sudo policy was requested, not created. An admin must approve the '
        'request out-of-band (Alpacon web console or Slack); the policy takes '
        'effect only after that.',
        category='SUDO_POLICY_REQUEST_PENDING',
        data=result.get('data'),
        region=result.get('region'),
        workspace=workspace,
    )
