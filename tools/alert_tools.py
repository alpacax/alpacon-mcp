"""Alert management tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client

# ===============================
# ALERT TOOLS
# ===============================


@mcp_tool_handler(description='List alerts with optional filtering by server or status')
async def list_alerts(
    workspace: str,
    server_id: str | None = None,
    status: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List alerts.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by server ID (optional)
        status: Filter by alert status (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Alerts list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if server_id:
        params['server'] = server_id
    if status:
        params['status'] = status
    if page:
        params['page'] = page
    if page_size:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/alerts/',
        token=token,
        params=params,
    )

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(description='Get detailed information about a specific alert')
async def get_alert(
    alert_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get alert details by ID.

    Args:
        alert_id: Alert ID to retrieve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Alert details response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/alerts/{alert_id}/',
        token=token,
    )

    return success_response(
        data=result, alert_id=alert_id, region=region, workspace=workspace
    )


@mcp_tool_handler(description='Mute an alert to suppress notifications temporarily')
async def mute_alert(
    alert_id: str,
    workspace: str,
    duration: int | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Mute an alert.

    Args:
        alert_id: Alert ID to mute
        workspace: Workspace name. Required parameter
        duration: Mute duration in minutes (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Alert mute response
    """
    token = kwargs.get('token')

    mute_data: dict[str, Any] = {}
    if duration is not None:
        mute_data['duration'] = duration

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/alerts/{alert_id}/mute/',
        token=token,
        data=mute_data,
    )

    return success_response(
        data=result, alert_id=alert_id, region=region, workspace=workspace
    )


# ===============================
# ALERT RULE TOOLS
# ===============================


@mcp_tool_handler(
    description='Create an alert rule to define monitoring thresholds and notifications'
)
async def create_alert_rule(
    workspace: str,
    name: str,
    metric_type: str,
    condition: str,
    threshold: float,
    servers: list[str] | None = None,
    notification_channels: list[str] | None = None,
    description: str | None = None,
    enabled: bool = True,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create an alert rule.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the alert rule
        metric_type: Metric type to monitor (e.g., 'cpu', 'memory', 'disk')
        condition: Condition operator (e.g., 'gt', 'lt', 'gte', 'lte')
        threshold: Threshold value that triggers the alert
        servers: List of server IDs to apply the rule to (optional)
        notification_channels: List of notification channel IDs (optional)
        description: Description of the alert rule (optional)
        enabled: Whether the rule is enabled (default: True)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Alert rule creation response
    """
    token = kwargs.get('token')

    rule_data: dict[str, Any] = {
        'name': name,
        'metric_type': metric_type,
        'condition': condition,
        'threshold': threshold,
        'enabled': enabled,
    }

    if servers is not None:
        rule_data['servers'] = servers
    if notification_channels is not None:
        rule_data['notification_channels'] = notification_channels
    if description is not None:
        rule_data['description'] = description

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/alert-rules/',
        token=token,
        data=rule_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(description='Update an existing alert rule configuration')
async def update_alert_rule(
    rule_id: str,
    workspace: str,
    name: str | None = None,
    metric_type: str | None = None,
    condition: str | None = None,
    threshold: float | None = None,
    servers: list[str] | None = None,
    notification_channels: list[str] | None = None,
    description: str | None = None,
    enabled: bool | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an existing alert rule.

    Args:
        rule_id: Alert rule ID to update
        workspace: Workspace name. Required parameter
        name: Name of the alert rule (optional)
        metric_type: Metric type to monitor (optional)
        condition: Condition operator (optional)
        threshold: Threshold value (optional)
        servers: List of server IDs (optional)
        notification_channels: List of notification channel IDs (optional)
        description: Description of the alert rule (optional)
        enabled: Whether the rule is enabled (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Alert rule update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if name is not None:
        update_data['name'] = name
    if metric_type is not None:
        update_data['metric_type'] = metric_type
    if condition is not None:
        update_data['condition'] = condition
    if threshold is not None:
        update_data['threshold'] = threshold
    if servers is not None:
        update_data['servers'] = servers
    if notification_channels is not None:
        update_data['notification_channels'] = notification_channels
    if description is not None:
        update_data['description'] = description
    if enabled is not None:
        update_data['enabled'] = enabled

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/alert-rules/{rule_id}/',
        token=token,
        data=update_data,
    )

    return success_response(
        data=result, rule_id=rule_id, region=region, workspace=workspace
    )


@mcp_tool_handler(description='Delete an alert rule')
async def delete_alert_rule(
    rule_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete an alert rule.

    Args:
        rule_id: Alert rule ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Alert rule deletion response
    """
    token = kwargs.get('token')

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/alert-rules/{rule_id}/',
        token=token,
    )

    return success_response(
        data=result, rule_id=rule_id, region=region, workspace=workspace
    )
