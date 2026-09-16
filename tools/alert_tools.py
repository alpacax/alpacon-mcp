"""Alert management tools for Alpacon MCP server."""

from typing import Any

from utils.api_call import http_call_response
from utils.common import build_list_params
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, IDEMPOTENT_WRITE, READ_ONLY

# Mirrors AlertAcknowledgement.ACTION_TYPE_CHOICES; the server takes nothing else.
ALERT_ACTION_TYPES = frozenset({'checked', 'dismissed'})
_ACTION_TYPES_SENTENCE = f'One of {", ".join(sorted(ALERT_ACTION_TYPES))}.'

# Mirrors AlertRule.EmailDestination; the server takes nothing else.
ALERT_EMAIL_DESTINATIONS = frozenset({'all', 'admins', 'group_members', 'none'})
_EMAIL_DESTINATIONS_SENTENCE = f'One of {", ".join(sorted(ALERT_EMAIL_DESTINATIONS))}.'

# Common target metrics, e.g. cpu-usage, memory-usage, disk-usage,
# peak/avg-{read,write}-bps, peak/avg-{input,output}-{pps,bps}. The server's
# AlertRule.TARGET_METRICS is the authoritative list; an unrecognized target
# is rejected there with a 400, not pre-validated here.
_TARGETS_SENTENCE = (
    'target must be a metric the workspace exposes, e.g. cpu-usage, '
    'memory-usage, disk-usage, or one of the peak/avg bps or pps network and '
    'disk rates; the server rejects an unrecognized one with a 400. Every '
    'target but cpu-usage and memory-usage is device-scoped and accepts a '
    'device narrowing the rule to one disk or interface; the two host-wide '
    'targets do not.'
)

# ===============================
# ALERT TOOLS
# ===============================


@mcp_tool_handler(
    description='List alerts with optional filtering by server, alert type, severity, resolution state, or server name. When to use: checking active alerts or reviewing alert history. Related: get_alert (full details), get_alert_rules (threshold configuration), acknowledge_alert (mark one as seen).',
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
    resolved: bool | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List alerts.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by server ID (optional)
        alert_type: Filter by alert type, e.g. metric_threshold, server_disconnected (optional)
        severity: Filter by severity: critical, warning, info (optional)
        server_name: Filter by a substring of the server name (optional)
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)
        acknowledged: Filter by acknowledgement state (False = active/unacknowledged)
        dismissed: Filter by dismissed state
        resolved: Filter by resolution state. Omitted returns open alerts
            only; true returns the resolved history instead; false is the
            explicit spelling of the default (optional)

    Returns:
        Alerts list response. Each alert can carry device and severity from
        the rule that raised it, and resolved_at once the condition clears.
    """
    token = kwargs.get('token')

    params = build_list_params(
        page=page,
        page_size=page_size,
        server=server_id,
        alert_type=alert_type,
        severity=severity,
        server_name=server_name,
        acknowledged=acknowledged,
        dismissed=dismissed,
        resolved=resolved,
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/alerts/',
        token=token,
        default_message='Failed to list alerts',
        params=params,
        server_id=server_id,
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
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Alert details response. Can carry device and severity from the rule
        that raised it, and resolved_at once the condition clears.
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'/api/alerts/{alert_id}/',
        token=token,
        default_message='Failed to get alert',
        alert_id=alert_id,
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

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'/api/alerts/{alert_id}/acknowledge/',
        token=token,
        default_message='Failed to acknowledge alert',
        data={'action_type': action_type},
        alert_id=alert_id,
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
        'target may carry is_default=true. notify_email and '
        'notify_slack_channel decide who hears about alerts this rule '
        'raises; only a human caller may name them—a service-token or agent '
        'write naming either is refused with a 400. Related: get_alert_rules, '
        'attach_alert_rule, update_alert_rule, get_alert_rule_recipients '
        '(preview who a rule reaches).'
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
    operator: str | None = None,
    duration_s: int | None = None,
    recovery_threshold: float | None = None,
    no_data_after_s: int | None = None,
    device: str | None = None,
    severity: str | None = None,
    notify_email: str | None = None,
    notify_slack_channel: bool | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Create an alert rule.

    Args:
        workspace: Workspace name. Required parameter
        name: Rule name, unique within the workspace
        target: Target metric, e.g. cpu-usage, memory-usage, disk-usage, or
            one of the peak/avg bps or pps network and disk rates. The server
            holds the authoritative list and rejects an unrecognized one.
        threshold: Value the metric must cross to fire
        is_default: Make this the default rule for the target
        region: Region (ap1, us1). Auto-detected if not provided
        operator: Which side of the threshold breaches: gte (default) fires
            at or above it, lte fires at or below it (optional)
        duration_s: How long the condition must hold before firing, in
            seconds; 0 (the default) fires on a single breaching sample
            (optional)
        recovery_threshold: Value the metric must return to before the alert
            resolves; omitted, the threshold itself resolves it (optional)
        no_data_after_s: Raise an alert when no sample arrives for this many
            seconds; the server floors it at the target's own collection
            interval (optional)
        device: Narrow the rule to one disk, partition, or network interface.
            Only accepted for a device-scoped target (disk-usage, disk I/O,
            network); cpu-usage and memory-usage are host-wide and reject it
            (optional)
        severity: Severity the raised alert carries: critical, warning
            (default), or info (optional)
        notify_email: Who the alert mail is addressed to, within the people
            who already can see the server: all (server default), admins,
            group_members (the same fan-out minus admins), or none. No
            setting here sends mail for an info-severity rule. Omitted keeps
            the server default of all. Refused with a 400 from a
            service-token or agent caller (optional)
        notify_slack_channel: Whether a raise and its resolution post to the
            workspace alert channel. Independent of notify_email—either
            can be turned off without touching the other. Omitted keeps the
            server default of true. Refused with a 400 from a service-token
            or agent caller (optional)

    Returns:
        Created alert rule
    """
    if notify_email is not None and notify_email not in ALERT_EMAIL_DESTINATIONS:
        return format_validation_error(
            'notify_email',
            notify_email,
            _EMAIL_DESTINATIONS_SENTENCE,
        )

    token = kwargs.get('token')

    rule_data: dict[str, Any] = {
        'name': name,
        'target': target,
        'threshold': threshold,
        'is_default': is_default,
    }
    if operator is not None:
        rule_data['operator'] = operator
    if duration_s is not None:
        rule_data['duration_s'] = duration_s
    if recovery_threshold is not None:
        rule_data['recovery_threshold'] = recovery_threshold
    if no_data_after_s is not None:
        rule_data['no_data_after_s'] = no_data_after_s
    if device is not None:
        rule_data['device'] = device
    if severity is not None:
        rule_data['severity'] = severity
    if notify_email is not None:
        rule_data['notify_email'] = notify_email
    if notify_slack_channel is not None:
        rule_data['notify_slack_channel'] = notify_slack_channel

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/alert-rules/',
        token=token,
        default_message='Failed to create alert rule',
        data=rule_data,
    )


@mcp_tool_handler(
    description=(
        'Update an existing alert rule. When to use: retuning a threshold or '
        f'renaming a rule. {_TARGETS_SENTENCE} Updating a rule needs a paid '
        'plan, and only one rule per target may carry is_default=true. '
        'notify_email and notify_slack_channel decide who hears about alerts '
        'this rule raises; only a human caller may name them—a '
        'service-token or agent write naming either is refused with a 400. '
        'Related: get_alert_rules, create_alert_rule, delete_alert_rule, '
        'get_alert_rule_recipients (preview who a rule reaches).'
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
    operator: str | None = None,
    duration_s: int | None = None,
    recovery_threshold: float | None = None,
    no_data_after_s: int | None = None,
    device: str | None = None,
    severity: str | None = None,
    notify_email: str | None = None,
    notify_slack_channel: bool | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Update an alert rule.

    Args:
        rule_id: Alert rule ID to update
        workspace: Workspace name. Required parameter
        name: New rule name (optional)
        target: New target metric, e.g. cpu-usage, memory-usage, disk-usage,
            or one of the peak/avg bps or pps network and disk rates. The
            server holds the authoritative list and rejects an unrecognized
            one. (optional)
        threshold: New threshold (optional)
        is_default: Make this the default rule for the target (optional)
        region: Region (ap1, us1). Auto-detected if not provided
        operator: Which side of the threshold breaches: gte fires at or
            above it, lte fires at or below it (optional)
        duration_s: How long the condition must hold before firing, in
            seconds; 0 fires on a single breaching sample (optional)
        recovery_threshold: Value the metric must return to before the alert
            resolves; omitted, the threshold itself resolves it (optional)
        no_data_after_s: Raise an alert when no sample arrives for this many
            seconds; the server floors it at the target's own collection
            interval (optional)
        device: Narrow the rule to one disk, partition, or network interface.
            Only accepted for a device-scoped target (disk-usage, disk I/O,
            network); cpu-usage and memory-usage are host-wide and reject it
            (optional)
        severity: Severity the raised alert carries: critical, warning, or
            info (optional)
        notify_email: Who the alert mail is addressed to, within the people
            who already can see the server: all, admins, group_members (the
            same fan-out minus admins), or none. No setting here sends mail
            for an info-severity rule. Omitted leaves the rule's current
            value unchanged. Refused with a 400 from a service-token or
            agent caller (optional)
        notify_slack_channel: Whether a raise and its resolution post to the
            workspace alert channel. Independent of notify_email—either
            can be turned off without touching the other. Omitted leaves the
            rule's current value unchanged. Refused with a 400 from a
            service-token or agent caller (optional)

    Returns:
        Updated alert rule
    """
    if notify_email is not None and notify_email not in ALERT_EMAIL_DESTINATIONS:
        return format_validation_error(
            'notify_email',
            notify_email,
            _EMAIL_DESTINATIONS_SENTENCE,
        )

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
    if operator is not None:
        update_data['operator'] = operator
    if duration_s is not None:
        update_data['duration_s'] = duration_s
    if recovery_threshold is not None:
        update_data['recovery_threshold'] = recovery_threshold
    if no_data_after_s is not None:
        update_data['no_data_after_s'] = no_data_after_s
    if device is not None:
        update_data['device'] = device
    if severity is not None:
        update_data['severity'] = severity
    if notify_email is not None:
        update_data['notify_email'] = notify_email
    if notify_slack_channel is not None:
        update_data['notify_slack_channel'] = notify_slack_channel

    if not update_data:
        return format_validation_error(
            'payload',
            None,
            'At least one of name, target, threshold, is_default, operator, '
            'duration_s, recovery_threshold, no_data_after_s, device, '
            'severity, notify_email or notify_slack_channel must be '
            'provided.',
        )

    return await http_call_response(
        http_client.patch,
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/alert-rules/{rule_id}/',
        token=token,
        default_message='Failed to update alert rule',
        data=update_data,
        rule_id=rule_id,
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

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/attach-rule/',
        token=token,
        default_message='Failed to attach alert rule',
        data={'rule': rule_id},
        server_id=server_id,
        rule_id=rule_id,
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

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'/api/servers/servers/{server_id}/detach-rule/',
        token=token,
        default_message='Failed to detach alert rule',
        data={'rule': rule_id},
        server_id=server_id,
        rule_id=rule_id,
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
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Alert rule deletion response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.delete,
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/alert-rules/{rule_id}/',
        token=token,
        default_message='Failed to delete alert rule',
        rule_id=rule_id,
    )


@mcp_tool_handler(
    description=(
        'Preview who an alert rule would notify—counts only, never names. '
        'When to use: checking the effect of notify_email/notify_slack_channel '
        "before or after changing them, without exposing anyone's identity. "
        'Requires alpacon-server 2.36.0 or later. Counted over the servers '
        'the rule is attached to that you can see and that the rule can '
        'actually fire on; the reasons in email.reasons overlap each other, '
        'so they do not have to sum to email.count. slack_channel.enabled '
        'and .connected reflect configuration as-is even for an '
        'info-severity rule, which posts to neither channel regardless. A '
        '404 here while the rule itself reads fine through get_alert_rules '
        'means every server the rule is attached to is outside what you can '
        'see—not that the rule is gone. Related: get_alert_rules, '
        'create_alert_rule, update_alert_rule (set the destinations).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'alert rule recipients preview notify who email slack'
    },
)
async def get_alert_rule_recipients(
    rule_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Preview who an alert rule would notify, as counts only.

    Requires alpacon-server 2.36.0 or later—an older server has no
    recipients action on this rule and answers 404.

    Three traps in reading the response. First, the reasons in
    email.reasons overlap: someone who is both a workspace admin and a
    member of the server's group is counted under both admins and
    group_members, and once in email.count, so admins + group_members +
    owner can exceed count—never sum them to reconstruct it. Second,
    slack_channel.enabled and .connected stay as configured even for an
    info-severity rule: info raises the bell alone and posts to neither
    the mail nor the channel, whatever these two booleans say—they echo
    the rule's and the workspace's settings, not what actually goes out.
    Third, a 404 here does not mean the rule is gone: it means every
    server the rule is attached to is outside what the caller can see. A
    rule that reads fine through get_alert_rules can still 404 here; a
    rule attached to no server at all answers zeros instead, not a 404.

    Args:
        rule_id: Alert rule ID to preview
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        email (mode, count, reasons with admins/group_members/owner),
        slack_channel (enabled, connected), and event_subscriptions (a
        count of machine listeners, unaffected by either destination). No
        user id, name, or address appears anywhere in it.
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/alert-rules/{rule_id}/recipients/',
        token=token,
        default_message='Failed to get alert rule recipients',
        rule_id=rule_id,
    )


# ===============================
# RULE OVERRIDE TOOLS
# ===============================


@mcp_tool_handler(
    description=(
        'List per-server departures from workspace alert rules. When to use: '
        'auditing which servers exempt themselves from a rule or run a '
        'different threshold than the fleet. Filter by server, rule, or '
        'enabled state. Related: get_rule_override (full details), '
        'create_rule_override, get_alert_rules (the workspace-wide rules '
        'these depart from).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'rule override list server exempt threshold per-server'
    },
)
async def list_rule_overrides(
    workspace: str,
    server_id: str | None = None,
    rule_id: str | None = None,
    enabled: bool | None = None,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List rule overrides.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Filter by the server the override applies to (optional)
        rule_id: Filter by the alert rule being overridden (optional)
        enabled: Filter by the override's enabled state; false is a whole-rule
            exemption (optional)
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        Rule overrides list response
    """
    token = kwargs.get('token')

    params = build_list_params(
        page=page,
        page_size=page_size,
        server=server_id,
        rule=rule_id,
        enabled=enabled,
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/rule-overrides/',
        token=token,
        default_message='Failed to list rule overrides',
        params=params,
    )


@mcp_tool_handler(
    description=(
        'Get a single rule override by ID. When to use: need full context '
        'about one server-rule departure. Related: list_rule_overrides '
        '(browse overrides), update_rule_override, delete_rule_override.'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'rule override detail info specific'},
)
async def get_rule_override(
    override_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get a rule override by ID.

    Args:
        override_id: Rule override ID to retrieve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Rule override details response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/rule-overrides/{override_id}/',
        token=token,
        default_message='Failed to get rule override',
        override_id=override_id,
    )


@mcp_tool_handler(
    description=(
        'Create a per-server departure from a workspace alert rule: replace '
        'the threshold, recovery_threshold, or duration_s for one server, or '
        'set enabled=False to exempt the server from the rule entirely. When '
        'to use: a rule fits the fleet but one host needs a different number '
        "or should not fire at all. A field left unset keeps the rule's own "
        'value for that server—an override only overrides what it is given. '
        'At most one override per (server, rule) pair; a second '
        'create for the same pair is refused. Related: list_rule_overrides, '
        'update_rule_override, delete_rule_override, create_alert_rule.'
    ),
    annotations=ADDITIVE,
    meta={
        'anthropic/searchHint': 'rule override create exempt threshold per-server alert'
    },
)
async def create_rule_override(
    server_id: str,
    rule_id: str,
    workspace: str,
    threshold: float | None = None,
    recovery_threshold: float | None = None,
    duration_s: int | None = None,
    enabled: bool | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a rule override.

    Args:
        server_id: Server UUID the override applies to
        rule_id: Alert rule UUID being overridden
        workspace: Workspace name. Required parameter
        threshold: Replace the rule's threshold for this server; unset keeps
            the rule's value (optional)
        recovery_threshold: Replace the rule's recovery threshold for this
            server; unset keeps the rule's value (optional)
        duration_s: Replace the rule's duration for this server, in seconds;
            unset keeps the rule's value, 0 fires on a single breaching
            sample (optional)
        enabled: False exempts this server from the rule entirely, whatever
            the other fields hold (default: true, matching the server)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Created rule override
    """
    token = kwargs.get('token')

    override_data: dict[str, Any] = {'server': server_id, 'rule': rule_id}
    if threshold is not None:
        override_data['threshold'] = threshold
    if recovery_threshold is not None:
        override_data['recovery_threshold'] = recovery_threshold
    if duration_s is not None:
        override_data['duration_s'] = duration_s
    if enabled is not None:
        override_data['enabled'] = enabled

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/rule-overrides/',
        token=token,
        default_message='Failed to create rule override',
        data=override_data,
        server_id=server_id,
        rule_id=rule_id,
    )


@mcp_tool_handler(
    description=(
        'Update an existing rule override. When to use: retuning an '
        'overridden threshold or flipping enabled to exempt or re-include a '
        'server. Only the fields given are sent; an omitted field keeps its '
        "current value on the override—it does not clear back to the rule's "
        'own value. Related: get_rule_override, list_rule_overrides, '
        'delete_rule_override.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={'anthropic/searchHint': 'rule override update modify threshold enabled'},
)
async def update_rule_override(
    override_id: str,
    workspace: str,
    server_id: str | None = None,
    rule_id: str | None = None,
    threshold: float | None = None,
    recovery_threshold: float | None = None,
    duration_s: int | None = None,
    enabled: bool | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update a rule override.

    Args:
        override_id: Rule override ID to update
        workspace: Workspace name. Required parameter
        server_id: Move the override to a different server (optional)
        rule_id: Move the override to a different alert rule (optional)
        threshold: New threshold override (optional)
        recovery_threshold: New recovery threshold override (optional)
        duration_s: New duration override, in seconds (optional)
        enabled: False exempts this server from the rule entirely (optional)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Updated rule override
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if server_id is not None:
        update_data['server'] = server_id
    if rule_id is not None:
        update_data['rule'] = rule_id
    if threshold is not None:
        update_data['threshold'] = threshold
    if recovery_threshold is not None:
        update_data['recovery_threshold'] = recovery_threshold
    if duration_s is not None:
        update_data['duration_s'] = duration_s
    if enabled is not None:
        update_data['enabled'] = enabled

    if not update_data:
        return format_validation_error(
            'payload',
            None,
            'At least one of server_id, rule_id, threshold, recovery_threshold, '
            'duration_s or enabled must be provided.',
        )

    return await http_call_response(
        http_client.patch,
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/rule-overrides/{override_id}/',
        token=token,
        default_message='Failed to update rule override',
        data=update_data,
        override_id=override_id,
    )


@mcp_tool_handler(
    description=(
        'Delete a rule override permanently, returning that server to the '
        "workspace rule's own values. When to use: the per-server departure "
        'is no longer needed. Related: get_rule_override (find override ID), '
        'update_rule_override (modify instead of deleting). Note: This '
        'cannot be undone.'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'rule override delete remove'},
)
async def delete_rule_override(
    override_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Delete a rule override.

    Args:
        override_id: Rule override ID to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Rule override deletion response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.delete,
        region=region,
        workspace=workspace,
        endpoint=f'/api/metrics/rule-overrides/{override_id}/',
        token=token,
        default_message='Failed to delete rule override',
        override_id=override_id,
    )
