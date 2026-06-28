"""alpacon:// MCP resources — thin read-only wrappers over list_/get_ tools.

Resources are generated from the RESOURCES registry table to avoid ~70 copies
of identical boilerplate. Each wrapper is built via exec with real named
parameters because FastMCP matches URI template params to the function
signature by name (server.py:603).
"""

import inspect
import re
from collections.abc import Callable

from server import mcp
from tools.alert_tools import get_alert, list_alerts
from tools.approval_tools import (
    get_approval_request,
    list_approval_requests,
    list_sudo_policies,
)
from tools.audit_tools import (
    get_activity_log,
    get_session_analysis_detail,
    list_activity_logs,
    list_server_logs,
    list_session_analyses,
    list_webftp_logs,
)
from tools.cert_tools import (
    get_certificate,
    get_certificate_authority,
    get_revoke_request,
    get_sign_request,
    list_certificate_authorities,
    list_certificates,
    list_revoke_requests,
    list_sign_requests,
)
from tools.command_tools import list_commands
from tools.events_tools import get_event, list_events
from tools.iam_tools import (
    get_iam_application,
    get_iam_group,
    get_iam_user,
    list_iam_applications,
    list_iam_groups,
    list_iam_memberships,
    list_iam_users,
)
from tools.metrics_tools import (
    get_alert_rules,
    get_cpu_usage,
    get_disk_io,
    get_disk_usage,
    get_memory_usage,
    get_network_traffic,
    get_server_metrics_summary,
    get_top_servers,
)
from tools.package_tools import list_python_packages, list_system_package_entries
from tools.security_tools import (
    list_command_acls,
    list_file_acls,
    list_server_acls,
)
from tools.server_tools import (
    get_server,
    get_server_note,
    list_registration_tokens,
    list_server_notes,
    list_servers,
)
from tools.system_info_tools import (
    get_disk_info,
    get_network_interfaces,
    get_os_version,
    get_server_overview,
    get_system_info,
    get_system_time,
    list_system_groups,
    list_system_packages,
    list_system_users,
)
from tools.token_tools import (
    get_api_token,
    list_api_token_presets,
    list_api_token_scopes,
    list_api_tokens,
)
from tools.webftp_tools import (
    webftp_downloads_list,
    webftp_sessions_list,
    webftp_uploads_list,
)
from tools.webhook_tools import get_webhook, list_event_subscriptions, list_webhooks
from tools.work_session_tools import work_session_get, work_session_list
from tools.workspace_tools import get_current_user, list_workspaces


def register_resource(
    uri: str, fn: Callable, name: str, extra: dict | None = None
) -> None:
    """Register an alpacon:// resource that proxies a read-only tool.

    Path params in `uri` (e.g. {region}) become the wrapper's named arguments;
    `extra` injects fixed keyword args (e.g. acknowledged=False) into the call.
    """
    path_params = re.findall(r'\{(\w+)\}', uri)
    sig = ', '.join(f'{p}: str' for p in path_params)
    call = ', '.join(f'{p}={p}' for p in path_params)
    if extra:
        call += ''.join(f', {k}={v!r}' for k, v in extra.items())
    # exec: FastMCP requires a real named signature matching the URI template;
    # a **kwargs wrapper with a synthetic __signature__ fails func_metadata.
    src = f"async def _wrapper({sig}):\n    return {{'content': await _fn({call})}}\n"
    ns: dict = {'_fn': fn}
    exec(src, ns)  # noqa: S102
    wrapper = ns['_wrapper']
    wrapper.__doc__ = inspect.getdoc(fn) or name
    mcp.resource(
        uri, name=name, description=wrapper.__doc__, mime_type='application/json'
    )(wrapper)


RESOURCES: list[tuple[str, Callable, str]] = [
    ('servers_list', list_servers, 'alpacon://servers/{region}/{workspace}'),
    ('server_detail', get_server, 'alpacon://servers/{region}/{workspace}/{server_id}'),
    (
        'server_notes_list',
        list_server_notes,
        'alpacon://servers/{region}/{workspace}/{server_id}/notes',
    ),
    (
        'server_overview',
        get_server_overview,
        'alpacon://servers/{region}/{workspace}/{server_id}/overview',
    ),
    (
        'server_note_detail',
        get_server_note,
        'alpacon://server-notes/{region}/{workspace}/{note_id}',
    ),
    (
        'registration_tokens_list',
        list_registration_tokens,
        'alpacon://registration-tokens/{region}/{workspace}',
    ),
    (
        'system_info',
        get_system_info,
        'alpacon://system/{region}/{workspace}/{server_id}/info',
    ),
    (
        'system_os_version',
        get_os_version,
        'alpacon://system/{region}/{workspace}/{server_id}/os-version',
    ),
    (
        'system_users',
        list_system_users,
        'alpacon://system/{region}/{workspace}/{server_id}/users',
    ),
    (
        'system_groups',
        list_system_groups,
        'alpacon://system/{region}/{workspace}/{server_id}/groups',
    ),
    (
        'system_packages',
        list_system_packages,
        'alpacon://system/{region}/{workspace}/{server_id}/packages',
    ),
    (
        'system_network_interfaces',
        get_network_interfaces,
        'alpacon://system/{region}/{workspace}/{server_id}/network-interfaces',
    ),
    (
        'system_disk_info',
        get_disk_info,
        'alpacon://system/{region}/{workspace}/{server_id}/disk-info',
    ),
    (
        'system_time',
        get_system_time,
        'alpacon://system/{region}/{workspace}/{server_id}/time',
    ),
    (
        'metrics_cpu',
        get_cpu_usage,
        'alpacon://metrics/{region}/{workspace}/{server_id}/cpu',
    ),
    (
        'metrics_memory',
        get_memory_usage,
        'alpacon://metrics/{region}/{workspace}/{server_id}/memory',
    ),
    (
        'metrics_disk',
        get_disk_usage,
        'alpacon://metrics/{region}/{workspace}/{server_id}/disk',
    ),
    (
        'metrics_disk_io',
        get_disk_io,
        'alpacon://metrics/{region}/{workspace}/{server_id}/disk-io',
    ),
    (
        'metrics_network',
        get_network_traffic,
        'alpacon://metrics/{region}/{workspace}/{server_id}/network',
    ),
    (
        'metrics_summary',
        get_server_metrics_summary,
        'alpacon://metrics/{region}/{workspace}/{server_id}/summary',
    ),
    ('metrics_top', get_top_servers, 'alpacon://metrics/{region}/{workspace}/top'),
    ('alert_rules', get_alert_rules, 'alpacon://alert-rules/{region}/{workspace}'),
    ('alerts_list', list_alerts, 'alpacon://alerts/{region}/{workspace}'),
    ('alert_detail', get_alert, 'alpacon://alerts/{region}/{workspace}/{alert_id}'),
    (
        'approvals_list',
        list_approval_requests,
        'alpacon://approvals/{region}/{workspace}',
    ),
    (
        'approval_detail',
        get_approval_request,
        'alpacon://approvals/{region}/{workspace}/{request_id}',
    ),
    (
        'sudo_policies_list',
        list_sudo_policies,
        'alpacon://sudo-policies/{region}/{workspace}',
    ),
    (
        'audit_activity_list',
        list_activity_logs,
        'alpacon://audit/activity/{region}/{workspace}',
    ),
    (
        'audit_activity_detail',
        get_activity_log,
        'alpacon://audit/activity/{region}/{workspace}/{log_id}',
    ),
    (
        'audit_server_logs',
        list_server_logs,
        'alpacon://audit/server-logs/{region}/{workspace}',
    ),
    (
        'audit_webftp_logs',
        list_webftp_logs,
        'alpacon://audit/webftp-logs/{region}/{workspace}',
    ),
    (
        'audit_session_analyses',
        list_session_analyses,
        'alpacon://audit/session-analyses/{region}/{workspace}',
    ),
    (
        'audit_session_analysis_detail',
        get_session_analysis_detail,
        'alpacon://audit/session-analyses/{region}/{workspace}/{analysis_id}',
    ),
    (
        'cert_authorities_list',
        list_certificate_authorities,
        'alpacon://certs/authorities/{region}/{workspace}',
    ),
    (
        'cert_authority_detail',
        get_certificate_authority,
        'alpacon://certs/authorities/{region}/{workspace}/{ca_id}',
    ),
    (
        'cert_sign_requests_list',
        list_sign_requests,
        'alpacon://certs/sign-requests/{region}/{workspace}',
    ),
    (
        'cert_sign_request_detail',
        get_sign_request,
        'alpacon://certs/sign-requests/{region}/{workspace}/{csr_id}',
    ),
    ('certs_list', list_certificates, 'alpacon://certs/{region}/{workspace}'),
    (
        'cert_detail',
        get_certificate,
        'alpacon://certs/{region}/{workspace}/{certificate_id}',
    ),
    (
        'cert_revoke_requests_list',
        list_revoke_requests,
        'alpacon://certs/revoke-requests/{region}/{workspace}',
    ),
    (
        'cert_revoke_request_detail',
        get_revoke_request,
        'alpacon://certs/revoke-requests/{region}/{workspace}/{revoke_id}',
    ),
    ('commands_list', list_commands, 'alpacon://commands/{region}/{workspace}'),
    ('events_list', list_events, 'alpacon://events/{region}/{workspace}'),
    ('event_detail', get_event, 'alpacon://events/{region}/{workspace}/{event_id}'),
    ('iam_users_list', list_iam_users, 'alpacon://iam/users/{region}/{workspace}'),
    (
        'iam_user_detail',
        get_iam_user,
        'alpacon://iam/users/{region}/{workspace}/{user_id}',
    ),
    ('iam_groups_list', list_iam_groups, 'alpacon://iam/groups/{region}/{workspace}'),
    (
        'iam_group_detail',
        get_iam_group,
        'alpacon://iam/groups/{region}/{workspace}/{group_id}',
    ),
    (
        'iam_memberships_list',
        list_iam_memberships,
        'alpacon://iam/memberships/{region}/{workspace}',
    ),
    (
        'iam_applications_list',
        list_iam_applications,
        'alpacon://iam/applications/{region}/{workspace}',
    ),
    (
        'iam_application_detail',
        get_iam_application,
        'alpacon://iam/applications/{region}/{workspace}/{app_id}',
    ),
    (
        'packages_system',
        list_system_package_entries,
        'alpacon://packages/system/{region}/{workspace}/{server_id}',
    ),
    (
        'packages_python',
        list_python_packages,
        'alpacon://packages/python/{region}/{workspace}/{server_id}',
    ),
    ('acls_command', list_command_acls, 'alpacon://acls/command/{region}/{workspace}'),
    ('acls_server', list_server_acls, 'alpacon://acls/server/{region}/{workspace}'),
    ('acls_file', list_file_acls, 'alpacon://acls/file/{region}/{workspace}'),
    ('tokens_list', list_api_tokens, 'alpacon://tokens/{region}/{workspace}'),
    ('token_detail', get_api_token, 'alpacon://tokens/{region}/{workspace}/{token_id}'),
    (
        'token_scopes',
        list_api_token_scopes,
        'alpacon://tokens/scopes/{region}/{workspace}',
    ),
    (
        'token_presets',
        list_api_token_presets,
        'alpacon://tokens/presets/{region}/{workspace}',
    ),
    (
        'event_subscriptions_list',
        list_event_subscriptions,
        'alpacon://event-subscriptions/{region}/{workspace}',
    ),
    ('webhooks_list', list_webhooks, 'alpacon://webhooks/{region}/{workspace}'),
    (
        'webhook_detail',
        get_webhook,
        'alpacon://webhooks/{region}/{workspace}/{webhook_id}',
    ),
    (
        'webftp_sessions',
        webftp_sessions_list,
        'alpacon://webftp/sessions/{region}/{workspace}',
    ),
    (
        'webftp_downloads',
        webftp_downloads_list,
        'alpacon://webftp/downloads/{region}/{workspace}',
    ),
    (
        'webftp_uploads',
        webftp_uploads_list,
        'alpacon://webftp/uploads/{region}/{workspace}',
    ),
    (
        'work_sessions_list',
        work_session_list,
        'alpacon://work-sessions/{region}/{workspace}',
    ),
    (
        'work_session_detail',
        work_session_get,
        'alpacon://work-sessions/{region}/{workspace}/{session_id}',
    ),
    ('workspaces_list', list_workspaces, 'alpacon://workspaces/{region}'),
    ('current_user', get_current_user, 'alpacon://current-user/{region}/{workspace}'),
]

# (name, fn, uri, extra) — extra pins fixed kwargs for the few filtered resources.
_REGISTRATIONS = [(n, f, u, None) for n, f, u in RESOURCES] + [
    (
        'alerts_active',
        list_alerts,
        'alpacon://alerts/active/{region}/{workspace}',
        {'acknowledged': False},
    ),
]


# Register most-specific first: a literal path segment (e.g. /active/) must win
# over a sibling {id} wildcard that would otherwise shadow it — FastMCP returns
# the first registered template that matches. Fewer {placeholders} = more
# literal segments (colliding templates share a segment count), so sort ascending.
for _name, _fn, _uri, _extra in sorted(_REGISTRATIONS, key=lambda r: r[2].count('{')):
    register_resource(_uri, _fn, _name, _extra)
