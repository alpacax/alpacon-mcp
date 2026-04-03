"""Approval and sudo policy tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, READ_ONLY

# ===============================
# APPROVAL REQUEST TOOLS
# ===============================


@mcp_tool_handler(
    description='List pending and historical approval requests in a workspace. Returns request ID, type, status, and requestor details. Filterable by status (pending, approved, rejected, cancelled, expired). Use this to review access requests that need approval or check approval history.',
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
    description='Get detailed information about a specific approval request by its ID. Returns requestor, request type, reason, status, and timestamps. Use this when you need full details about a single approval request.',
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


@mcp_tool_handler(
    description='Approve a pending approval request by its ID. Optionally include a comment explaining the approval decision. Only pending requests can be approved. Requires superuser or approval permission. Related: list_approval_requests (find pending requests), reject_request (deny instead).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'approval approve accept grant'},
)
async def approve_request(
    request_id: str,
    workspace: str,
    comment: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Approve a pending approval request.

    Args:
        request_id: Approval request ID to approve
        workspace: Workspace name. Required parameter
        comment: Comment explaining the approval decision (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Approval response
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {}
    if comment is not None:
        data['comment'] = comment

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/approvals/approvals/{request_id}/approve/',
        token=token,
        data=data,
    )

    return success_response(
        data=result, request_id=request_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Reject a pending approval request by its ID. Optionally include a comment explaining the rejection reason. Only pending requests can be rejected. Requires superuser or approval permission. Related: list_approval_requests (find pending requests), approve_request (approve instead). Note: Rejection is irreversible.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'approval reject deny refuse'},
)
async def reject_request(
    request_id: str,
    workspace: str,
    comment: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Reject a pending approval request.

    Args:
        request_id: Approval request ID to reject
        workspace: Workspace name. Required parameter
        comment: Reason for the rejection (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Rejection response
    """
    token = kwargs.get('token')

    data: dict[str, Any] = {}
    if comment is not None:
        data['comment'] = comment

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/approvals/approvals/{request_id}/reject/',
        token=token,
        data=data,
    )

    return success_response(
        data=result, request_id=request_id, region=region, workspace=workspace
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
