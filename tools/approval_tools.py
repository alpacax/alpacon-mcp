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

from utils.common import pending_approval_response, success_response
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
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Approval requests list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if status:
        params['status'] = status
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/approvals/approvals/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


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
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Approval request details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/approvals/approvals/{request_id}/',
        token=token,
    )

    return success_response(
        data=result, request_id=request_id, region=region, workspace=workspace
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
        region: Region (ap1, us1, eu1). Auto-detected if not provided

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
    description='List sudo policies that define elevated privilege rules. Returns policy names, allowed commands, assigned users/servers, and validity periods. Filterable by user or server ID. Use this to audit which sudo privileges are configured in the workspace.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'sudo policy privilege elevation rules'},
)
async def list_sudo_policies(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List sudo policies.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Sudo policies list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/approvals/sudo-policies/',
        token=token,
        params=params,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Create a sudo policy to define elevated privilege rules. Specify allowed commands, target users/servers, and whether passwordless sudo is permitted. Empty users or servers fields mean the policy applies to all. Requires superuser permission.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'sudo policy create privilege elevation'},
)
async def create_sudo_policy(
    workspace: str,
    name: str,
    commands: list[str],
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[str] | None = None,
    run_as: str | None = None,
    no_password: bool = False,
    description: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a sudo policy.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the sudo policy
        commands: List of commands allowed by this policy
        users: List of user IDs to apply the policy to (optional)
        groups: List of group IDs to apply the policy to (optional)
        servers: List of server IDs to apply the policy to (optional)
        run_as: User to run commands as (optional)
        no_password: Whether to allow passwordless sudo (default: False)
        description: Description of the sudo policy (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Sudo policy creation response
    """
    token = kwargs.get('token')

    policy_data: dict[str, Any] = {
        'name': name,
        'commands': commands,
        'no_password': no_password,
    }

    if users is not None:
        policy_data['users'] = users
    if groups is not None:
        policy_data['groups'] = groups
    if servers is not None:
        policy_data['servers'] = servers
    if run_as is not None:
        policy_data['run_as'] = run_as
    if description is not None:
        policy_data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/approvals/sudo-policies/',
        token=token,
        data=policy_data,
    )

    return success_response(data=result, region=region, workspace=workspace)
