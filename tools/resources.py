"""alpacon:// MCP resources — thin read-only wrappers over list_/get_ tools.

Resources are generated from the RESOURCES registry table to avoid ~70 copies
of identical boilerplate. Each wrapper is built via exec with real named
parameters because FastMCP matches URI template params to the function
signature by name; a **kwargs wrapper fails its func_metadata check.

Tool refs are `module.func` strings resolved lazily: importing this module must
not import (and thereby register) any tool module, or --toolsets breaks.
"""

import importlib
import inspect
import re
from collections.abc import Callable

from server import TOOLS_PACKAGE, mcp


def register_resource(
    uri: str, fn: Callable, name: str, extra: dict | None = None
) -> None:
    """Register an alpacon:// resource that proxies a read-only tool.

    Path params in `uri` (e.g. {region}) become the wrapper's named arguments;
    `extra` injects fixed keyword args (e.g. acknowledged=False) into the call.
    """
    path_params = re.findall(r'\{(\w+)\}', uri)
    sig = ', '.join(f'{p}: str' for p in path_params)
    parts = [f'{p}={p}' for p in path_params]
    if extra:
        parts += [f'{k}={v!r}' for k, v in extra.items()]
    call = ', '.join(parts)
    # FastMCP needs a real named signature; a **kwargs wrapper fails func_metadata.
    src = f"async def _wrapper({sig}):\n    return {{'content': await _fn({call})}}\n"
    # __name__/__file__ give the wrapper a real __module__ and traceback frame.
    ns: dict = {'_fn': fn, '__name__': __name__}
    exec(compile(src, __file__, 'exec'), ns)  # noqa: S102
    wrapper = ns['_wrapper']
    wrapper.__name__ = wrapper.__qualname__ = name
    doc = inspect.getdoc(fn) or name
    if extra:
        # Surface the pinned filter so a filtered resource isn't mistaken for the bare one.
        pinned = ', '.join(f'{k}={v!r}' for k, v in extra.items())
        doc = f'{doc}\n\nThis resource pins: {pinned}.'
    wrapper.__doc__ = doc
    mcp.resource(uri, name=name, description=doc, mime_type='application/json')(wrapper)


# (resource name, `module.func` reference, URI template)
RESOURCES: list[tuple[str, str, str]] = [
    (
        'servers_list',
        'server_tools.list_servers',
        'alpacon://servers/{region}/{workspace}',
    ),
    (
        'server_detail',
        'server_tools.get_server',
        'alpacon://servers/{region}/{workspace}/{server_id}',
    ),
    (
        'server_notes_list',
        'server_tools.list_server_notes',
        'alpacon://servers/{region}/{workspace}/{server_id}/notes',
    ),
    (
        'server_overview',
        'system_info_tools.get_server_overview',
        'alpacon://servers/{region}/{workspace}/{server_id}/overview',
    ),
    (
        'server_note_detail',
        'server_tools.get_server_note',
        'alpacon://server-notes/{region}/{workspace}/{note_id}',
    ),
    (
        'registration_tokens_list',
        'server_tools.list_registration_tokens',
        'alpacon://registration-tokens/{region}/{workspace}',
    ),
    (
        'system_info',
        'system_info_tools.get_system_info',
        'alpacon://system/{region}/{workspace}/{server_id}/info',
    ),
    (
        'system_os_version',
        'system_info_tools.get_os_version',
        'alpacon://system/{region}/{workspace}/{server_id}/os-version',
    ),
    (
        'system_users',
        'system_info_tools.list_system_users',
        'alpacon://system/{region}/{workspace}/{server_id}/users',
    ),
    (
        'system_groups',
        'system_info_tools.list_system_groups',
        'alpacon://system/{region}/{workspace}/{server_id}/groups',
    ),
    (
        'system_packages',
        'system_info_tools.list_system_packages',
        'alpacon://system/{region}/{workspace}/{server_id}/packages',
    ),
    (
        'system_network_interfaces',
        'system_info_tools.get_network_interfaces',
        'alpacon://system/{region}/{workspace}/{server_id}/network-interfaces',
    ),
    (
        'system_disk_info',
        'system_info_tools.get_disk_info',
        'alpacon://system/{region}/{workspace}/{server_id}/disk-info',
    ),
    (
        'system_time',
        'system_info_tools.get_system_time',
        'alpacon://system/{region}/{workspace}/{server_id}/time',
    ),
    (
        'metrics_cpu',
        'metrics_tools.get_cpu_usage',
        'alpacon://metrics/{region}/{workspace}/{server_id}/cpu',
    ),
    (
        'metrics_memory',
        'metrics_tools.get_memory_usage',
        'alpacon://metrics/{region}/{workspace}/{server_id}/memory',
    ),
    (
        'metrics_disk',
        'metrics_tools.get_disk_usage',
        'alpacon://metrics/{region}/{workspace}/{server_id}/disk',
    ),
    (
        'metrics_disk_io',
        'metrics_tools.get_disk_io',
        'alpacon://metrics/{region}/{workspace}/{server_id}/disk-io',
    ),
    (
        'metrics_network',
        'metrics_tools.get_network_traffic',
        'alpacon://metrics/{region}/{workspace}/{server_id}/network',
    ),
    (
        'metrics_summary',
        'metrics_tools.get_server_metrics_summary',
        'alpacon://metrics/{region}/{workspace}/{server_id}/summary',
    ),
    (
        'metrics_top',
        'metrics_tools.get_top_servers',
        'alpacon://metrics/{region}/{workspace}/top',
    ),
    (
        'alert_rules',
        'metrics_tools.get_alert_rules',
        'alpacon://alert-rules/{region}/{workspace}',
    ),
    ('alerts_list', 'alert_tools.list_alerts', 'alpacon://alerts/{region}/{workspace}'),
    (
        'alert_detail',
        'alert_tools.get_alert',
        'alpacon://alerts/{region}/{workspace}/{alert_id}',
    ),
    (
        'approvals_list',
        'approval_tools.list_approval_requests',
        'alpacon://approvals/{region}/{workspace}',
    ),
    (
        'approval_detail',
        'approval_tools.get_approval_request',
        'alpacon://approvals/{region}/{workspace}/{request_id}',
    ),
    (
        'sudo_policies_list',
        'approval_tools.list_sudo_policies',
        'alpacon://sudo-policies/{region}/{workspace}',
    ),
    (
        'audit_activity_list',
        'audit_tools.list_activity_logs',
        'alpacon://audit/activity/{region}/{workspace}',
    ),
    (
        'audit_activity_detail',
        'audit_tools.get_activity_log',
        'alpacon://audit/activity/{region}/{workspace}/{log_id}',
    ),
    (
        'audit_server_logs',
        'audit_tools.list_server_logs',
        'alpacon://audit/server-logs/{region}/{workspace}',
    ),
    (
        'audit_webftp_logs',
        'audit_tools.list_webftp_logs',
        'alpacon://audit/webftp-logs/{region}/{workspace}',
    ),
    (
        'audit_session_analyses',
        'audit_tools.list_session_analyses',
        'alpacon://audit/session-analyses/{region}/{workspace}',
    ),
    (
        'audit_session_analysis_detail',
        'audit_tools.get_session_analysis_detail',
        'alpacon://audit/session-analyses/{region}/{workspace}/{analysis_id}',
    ),
    (
        'cert_authorities_list',
        'cert_tools.list_certificate_authorities',
        'alpacon://certs/authorities/{region}/{workspace}',
    ),
    (
        'cert_authority_detail',
        'cert_tools.get_certificate_authority',
        'alpacon://certs/authorities/{region}/{workspace}/{ca_id}',
    ),
    (
        'cert_sign_requests_list',
        'cert_tools.list_sign_requests',
        'alpacon://certs/sign-requests/{region}/{workspace}',
    ),
    (
        'cert_sign_request_detail',
        'cert_tools.get_sign_request',
        'alpacon://certs/sign-requests/{region}/{workspace}/{csr_id}',
    ),
    (
        'certs_list',
        'cert_tools.list_certificates',
        'alpacon://certs/{region}/{workspace}',
    ),
    (
        'cert_detail',
        'cert_tools.get_certificate',
        'alpacon://certs/{region}/{workspace}/{certificate_id}',
    ),
    (
        'cert_revoke_requests_list',
        'cert_tools.list_revoke_requests',
        'alpacon://certs/revoke-requests/{region}/{workspace}',
    ),
    (
        'cert_revoke_request_detail',
        'cert_tools.get_revoke_request',
        'alpacon://certs/revoke-requests/{region}/{workspace}/{revoke_id}',
    ),
    (
        'commands_list',
        'command_tools.list_commands',
        'alpacon://commands/{region}/{workspace}',
    ),
    (
        'events_list',
        'events_tools.list_events',
        'alpacon://events/{region}/{workspace}',
    ),
    (
        'event_detail',
        'events_tools.get_event',
        'alpacon://events/{region}/{workspace}/{event_id}',
    ),
    (
        'iam_users_list',
        'iam_tools.list_iam_users',
        'alpacon://iam/users/{region}/{workspace}',
    ),
    (
        'iam_user_detail',
        'iam_tools.get_iam_user',
        'alpacon://iam/users/{region}/{workspace}/{user_id}',
    ),
    (
        'iam_groups_list',
        'iam_tools.list_iam_groups',
        'alpacon://iam/groups/{region}/{workspace}',
    ),
    (
        'iam_group_detail',
        'iam_tools.get_iam_group',
        'alpacon://iam/groups/{region}/{workspace}/{group_id}',
    ),
    (
        'iam_memberships_list',
        'iam_tools.list_iam_memberships',
        'alpacon://iam/memberships/{region}/{workspace}',
    ),
    (
        'iam_applications_list',
        'iam_tools.list_iam_applications',
        'alpacon://iam/applications/{region}/{workspace}',
    ),
    (
        'iam_application_detail',
        'iam_tools.get_iam_application',
        'alpacon://iam/applications/{region}/{workspace}/{app_id}',
    ),
    (
        'packages_system',
        'package_tools.list_system_package_entries',
        'alpacon://packages/system/{region}/{workspace}/{server_id}',
    ),
    (
        'packages_python',
        'package_tools.list_python_packages',
        'alpacon://packages/python/{region}/{workspace}/{server_id}',
    ),
    (
        'acls_command',
        'security_tools.list_command_acls',
        'alpacon://acls/command/{region}/{workspace}',
    ),
    (
        'acls_server',
        'security_tools.list_server_acls',
        'alpacon://acls/server/{region}/{workspace}',
    ),
    (
        'acls_file',
        'security_tools.list_file_acls',
        'alpacon://acls/file/{region}/{workspace}',
    ),
    (
        'tokens_list',
        'token_tools.list_api_tokens',
        'alpacon://tokens/{region}/{workspace}',
    ),
    (
        'token_detail',
        'token_tools.get_api_token',
        'alpacon://tokens/{region}/{workspace}/{token_id}',
    ),
    (
        'token_scopes',
        'token_tools.list_api_token_scopes',
        'alpacon://tokens/scopes/{region}/{workspace}',
    ),
    (
        'token_presets',
        'token_tools.list_api_token_presets',
        'alpacon://tokens/presets/{region}/{workspace}',
    ),
    (
        'event_subscriptions_list',
        'webhook_tools.list_event_subscriptions',
        'alpacon://event-subscriptions/{region}/{workspace}',
    ),
    (
        'webhooks_list',
        'webhook_tools.list_webhooks',
        'alpacon://webhooks/{region}/{workspace}',
    ),
    (
        'webhook_detail',
        'webhook_tools.get_webhook',
        'alpacon://webhooks/{region}/{workspace}/{webhook_id}',
    ),
    (
        'webftp_sessions',
        'webftp_tools.webftp_sessions_list',
        'alpacon://webftp/sessions/{region}/{workspace}',
    ),
    (
        'webftp_downloads',
        'webftp_tools.webftp_downloads_list',
        'alpacon://webftp/downloads/{region}/{workspace}',
    ),
    (
        'webftp_uploads',
        'webftp_tools.webftp_uploads_list',
        'alpacon://webftp/uploads/{region}/{workspace}',
    ),
    (
        'work_sessions_list',
        'work_session_tools.work_session_list',
        'alpacon://work-sessions/{region}/{workspace}',
    ),
    (
        'work_session_detail',
        'work_session_tools.work_session_get',
        'alpacon://work-sessions/{region}/{workspace}/{session_id}',
    ),
    ('workspaces_all', 'workspace_tools.list_workspaces', 'alpacon://workspaces'),
    (
        'workspaces_list',
        'workspace_tools.list_workspaces',
        'alpacon://workspaces/{region}',
    ),
    (
        'current_user',
        'workspace_tools.get_current_user',
        'alpacon://current-user/{region}/{workspace}',
    ),
    (
        'workspace_settings_access_control',
        'workspace_tools.get_workspace_access_control',
        'alpacon://workspace-settings/access-control/{region}/{workspace}',
    ),
    (
        'workspace_settings_security',
        'workspace_tools.get_workspace_security',
        'alpacon://workspace-settings/security/{region}/{workspace}',
    ),
    (
        'workspace_settings_mfa_methods',
        'workspace_tools.list_workspace_mfa_methods',
        'alpacon://workspace-settings/mfa-methods/{region}/{workspace}',
    ),
    (
        'workspace_settings_notifications',
        'workspace_tools.get_workspace_notifications',
        'alpacon://workspace-settings/notifications/{region}/{workspace}',
    ),
    (
        'workspace_settings_preferences',
        'workspace_tools.get_workspace_preferences',
        'alpacon://workspace-settings/preferences/{region}/{workspace}',
    ),
]

# (name, `module.func` ref, uri, extra) — extra pins fixed kwargs for filtered resources.
REGISTRATIONS: list[tuple[str, str, str, dict | None]] = [
    (n, ref, uri, None) for n, ref, uri in RESOURCES
] + [
    (
        'alerts_active',
        'alert_tools.list_alerts',
        'alpacon://alerts/active/{region}/{workspace}',
        {'acknowledged': False},
    ),
]


def _resolve(ref: str) -> Callable:
    module_name, func_name = ref.split('.', 1)
    return getattr(importlib.import_module(f'{TOOLS_PACKAGE}.{module_name}'), func_name)


def register_resources(enabled_modules: set[str]) -> None:
    """Fewer placeholders first so a literal segment (/active/) beats a sibling
    {id} wildcard — FastMCP takes the first match. That holds only within one
    call, so pass the complete enabled set at once.
    """
    selected = [r for r in REGISTRATIONS if r[1].split('.', 1)[0] in enabled_modules]
    for name, ref, uri, extra in sorted(selected, key=lambda r: r[2].count('{')):
        register_resource(uri, _resolve(ref), name, extra)
