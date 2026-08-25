"""Alert management tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

# Mirrors AlertAcknowledgement.ACTION_TYPE_CHOICES; the server takes nothing else.
ALERT_ACTION_TYPES = frozenset({'checked', 'dismissed'})
_ACTION_TYPES_SENTENCE = f'One of {", ".join(sorted(ALERT_ACTION_TYPES))}.'

# Mirrors AlertRule.TARGET_METRICS; a value outside this list is a guaranteed 400.
ALERT_RULE_TARGETS = (
    'cpu-usage',
    'memory-usage',
    'disk-usage',
    'peak-read-bps',
    'peak-write-bps',
    'avg-read-bps',
    'avg-write-bps',
    'peak-input-pps',
    'peak-input-bps',
    'peak-output-pps',
    'peak-output-bps',
    'avg-input-pps',
    'avg-input-bps',
    'avg-output-pps',
    'avg-output-bps',
)
_TARGETS_SENTENCE = f'target must be one of: {", ".join(ALERT_RULE_TARGETS)}.'

# ===============================
# ALERT TOOLS
# ===============================


@mcp_tool_handler(
    description='List alerts with optional filtering by server, alert type, severity, or server name. When to use: checking active alerts or reviewing alert history. Related: get_alert (full details), get_alert_rules (threshold configuration), acknowledge_alert (mark one as seen).',
    annotations=READ_ONLY,
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'alerts active triggered notifications monitoring',
    },
)
async def list_alerts(
    workspace: str,
    server_id: str | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
    server_name: str | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    acknowledged: bool | None = None,
    dismissed: bool | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List alerts.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by server ID (optional)
        alert_type: Filter by alert type, e.g. metric_threshold, server_disconnected (optional)
        severity: Filter by severity: critical, warning, info (optional)
        server_name: Filter by a substring of the server name (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)
        acknowledged: Filter by acknowledgement state (False = active/unacknowledged)
        dismissed: Filter by dismissed state

    Returns:
        Alerts list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if server_id:
        params['server'] = server_id
    if alert_type is not None:
        params['alert_type'] = alert_type
    if severity is not None:
        params['severity'] = severity
    if server_name is not None:
        params['server_name'] = server_name
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size
    if acknowledged is not None:
        params['acknowledged'] = acknowledged
    if dismissed is not None:
        params['dismissed'] = dismissed

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/alerts/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list alerts',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, server_id=server_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='Get detailed information about a specific alert. When to use: need full context about a triggered alert. Related: list_alerts (browse alerts), acknowledge_alert (mark this alert as seen).',
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

    err = unwrap_http_result(
        result,
        default_message='Failed to get alert',
        alert_id=alert_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, alert_id=alert_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Record an acknowledgement against an alert. When to use: marking an '
        'alert as seen (action_type="checked") or as not worth acting on '
        '(action_type="dismissed"). The server allows one acknowledgement per '
        'user per alert and it cannot be changed afterwards, so a second call '
        'is refused. Related: list_alerts, get_alert.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'alert acknowledge checked dismissed confirm'},
)
async def acknowledge_alert(
    alert_id: str,
    workspace: str,
    action_type: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Acknowledge an alert.

    Args:
        alert_id: Alert ID to acknowledge
        workspace: Workspace name. Required parameter
        action_type: One of ALERT_ACTION_TYPES ('checked' or 'dismissed')
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Acknowledge response
    """
    if action_type not in ALERT_ACTION_TYPES:
        return format_validation_error(
            'action_type',
            action_type,
            _ACTION_TYPES_SENTENCE,
        )

    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/alerts/{alert_id}/acknowledge/',
        token=token,
        data={'action_type': action_type},
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to acknowledge alert',
        alert_id=alert_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, alert_id=alert_id, region=region, workspace=workspace
    )


# ===============================
# ALERT RULE TOOLS
# ===============================


@mcp_tool_handler(
    description=(
        'Create a workspace-level alert rule that watches one target metric. '
        'When to use: defining a new threshold before attaching it to servers '
        f'with attach_alert_rule. {_TARGETS_SENTENCE} Authoring a rule needs a '
        'paid plan, while attaching one works on any plan. Only one rule per '
        'target may carry is_default=true. Related: get_alert_rules, '
        'attach_alert_rule, update_alert_rule.'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'alert rule create threshold target monitoring'},
)
async def create_alert_rule(
    workspace: str,
    name: str,
    target: str,
    threshold: float,
    is_default: bool = False,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create an alert rule.

    Args:
        workspace: Workspace name. Required parameter
        name: Rule name, unique within the workspace
        target: Target metric; one of ALERT_RULE_TARGETS
        threshold: Value the metric must cross to fire
        is_default: Make this the default rule for the target
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Created alert rule
    """
    if target not in ALERT_RULE_TARGETS:
        return format_validation_error('target', target, _TARGETS_SENTENCE)

    token = kwargs.get('token')

    rule_data: dict[str, Any] = {
        'name': name,
        'target': target,
        'threshold': threshold,
        'is_default': is_default,
    }

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/alert-rules/',
        token=token,
        data=rule_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to create alert rule',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Update an existing alert rule. When to use: retuning a threshold or '
        f'renaming a rule. {_TARGETS_SENTENCE} Updating a rule needs a paid '
        'plan, and only one rule per target may carry is_default=true. '
        'Related: get_alert_rules, create_alert_rule, delete_alert_rule.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'alert rule update modify threshold target'},
)
async def update_alert_rule(
    rule_id: str,
    workspace: str,
    name: str | None = None,
    target: str | None = None,
    threshold: float | None = None,
    is_default: bool | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update an alert rule.

    Args:
        rule_id: Alert rule ID to update
        workspace: Workspace name. Required parameter
        name: New rule name (optional)
        target: New target metric; one of ALERT_RULE_TARGETS (optional)
        threshold: New threshold (optional)
        is_default: Make this the default rule for the target (optional)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Updated alert rule
    """
    if target is not None and target not in ALERT_RULE_TARGETS:
        return format_validation_error('target', target, _TARGETS_SENTENCE)

    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if name is not None:
        update_data['name'] = name
    if target is not None:
        update_data['target'] = target
    if threshold is not None:
        update_data['threshold'] = threshold
    if is_default is not None:
        update_data['is_default'] = is_default

    if not update_data:
        return format_validation_error(
            'name, target, threshold or is_default',
            None,
            'At least one field must be provided.',
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/alert-rules/{rule_id}/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update alert rule',
        rule_id=rule_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, rule_id=rule_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Attach an existing alert rule to a server so the rule watches it. When to use: after create_alert_rule, to put the rule to work. Works on any plan, unlike authoring a rule. Attaching a rule that is already attached succeeds without change. Related: get_alert_rules, detach_alert_rule.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'alert rule attach server association monitor'},
)
async def attach_alert_rule(
    server_id: str,
    rule_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Attach an alert rule to a server.

    Args:
        server_id: Server UUID the rule should watch
        rule_id: Alert rule UUID to attach
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Attach response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/attach-rule/',
        token=token,
        data={'rule': rule_id},
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to attach alert rule',
        server_id=server_id,
        rule_id=rule_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result,
        server_id=server_id,
        rule_id=rule_id,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description=(
        'Detach an alert rule from a server so the rule stops watching it. When to use: retiring a rule from one server without deleting it. Works on any plan. Detaching a rule that was never attached succeeds without change. Related: get_alert_rules, attach_alert_rule.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'alert rule detach server remove association'},
)
async def detach_alert_rule(
    server_id: str,
    rule_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Detach an alert rule from a server.

    Args:
        server_id: Server UUID the rule should stop watching
        rule_id: Alert rule UUID to detach
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Detach response
    """
    token = kwargs.get('token')

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/detach-rule/',
        token=token,
        data={'rule': rule_id},
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to detach alert rule',
        server_id=server_id,
        rule_id=rule_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result,
        server_id=server_id,
        rule_id=rule_id,
        region=region,
        workspace=workspace,
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

    err = unwrap_http_result(
        result,
        default_message='Failed to delete alert rule',
        rule_id=rule_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, rule_id=rule_id, region=region, workspace=workspace
    )
