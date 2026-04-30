"""Alert management tools for Alpacon MCP server."""

from typing import Any

from utils.common import error_response, filter_non_none, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

# ===============================
# ALERT TOOLS
# ===============================


@mcp_tool_handler(
    description='List alerts with optional filtering by server or status. When to use: checking active alerts or reviewing alert history. Related: get_alert (full details), get_alert_rules (threshold configuration), mute_alert (suppress notifications).',
    annotations=READ_ONLY,
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'alerts active triggered notifications monitoring',
    },
)
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

    params = filter_non_none(page=page, page_size=page_size, server=server_id, status=status)

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


@mcp_tool_handler(
    description='Get detailed information about a specific alert. When to use: need full context about a triggered alert. Related: list_alerts (browse alerts), mute_alert (suppress this alert).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'alert detail info specific'},
)
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


@mcp_tool_handler(
    description='Mute an alert to suppress notifications temporarily. When to use: an alert is known and being worked on, and you want to stop repeated notifications. Related: list_alerts (find alert ID), get_alert (check alert details first).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'alert mute suppress silence notification'},
)
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

    mute_data = filter_non_none(duration=duration)

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
    description='Create an alert rule to define monitoring thresholds and notifications. When to use: setting up new monitoring for cpu, memory, or disk metrics. Related: get_alert_rules (view existing rules), update_alert_rule (modify rules), list_alerts (see triggered alerts).',
    annotations=ADDITIVE,
    meta={
        'anthropic/searchHint': 'alert rule create threshold monitoring notification'
    },
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

    rule_data = {
        'name': name,
        'metric_type': metric_type,
        'condition': condition,
        'threshold': threshold,
        'enabled': enabled,
        **filter_non_none(
            servers=servers,
            notification_channels=notification_channels,
            description=description,
        ),
    }

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/alert-rules/',
        token=token,
        data=rule_data,
    )

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Update an existing alert rule configuration. When to use: adjusting thresholds or notification settings. Related: get_alert_rules (find rule ID), create_alert_rule (create new), delete_alert_rule (remove).',
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'alert rule update modify threshold'},
)
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

    update_data = filter_non_none(
        name=name,
        metric_type=metric_type,
        condition=condition,
        threshold=threshold,
        servers=servers,
        notification_channels=notification_channels,
        description=description,
        enabled=enabled,
    )

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


@mcp_tool_handler(
    description='Delete an alert rule permanently. When to use: removing alert rules that are no longer needed. Related: get_alert_rules (find rule ID), update_alert_rule (modify instead of deleting). Note: This cannot be undone.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'alert rule delete remove'},
)
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
