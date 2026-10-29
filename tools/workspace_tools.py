"""Workspace management tools for Alpacon MCP server."""

from collections.abc import Mapping
from http import HTTPStatus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils.api_call import http_call_response
from utils.auth import get_token_workspaces_with_dropped
from utils.common import (
    error_response,
    exclude_none,
    is_auth_enabled,
    success_response,
    unwrap_http_result,
)
from utils.decorators import mcp_tool_handler, require_jwt_auth
from utils.error_handler import ServedRegion
from utils.http_client import http_client
from utils.token_manager import TokenManager, get_token_manager
from utils.tool_annotations import IDEMPOTENT_WRITE, READ_ONLY
from utils.types import ToolErrorResponse, ToolResponse

# Mirrors alpacon-server's AgentUpgradePolicy choices
# (workspaces/api/agent_rollout.py); kept here rather than imported since this
# is a separate deployable that talks to the server only over HTTP.
_ROLLOUT_MODES = frozenset({'latest', 'n_minus_1', 'manual'})
_ROLLOUT_POLICY_KEYS = frozenset({'mode', 'window'})
_ROLLOUT_WINDOW_KEYS = frozenset({'days', 'start_hour', 'length_hours', 'timezone'})


def _is_plain_int(value: object) -> bool:
    """True for a real int, not the `bool` subclass (`True`/`False` are ints)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_rollout_policy(policy: object) -> str | None:
    """Check an `agent_rollout_policy` write locally; returns an error message, or None.
    The server can still refuse a valid shape by state, e.g. `n_minus_1`."""
    if not isinstance(policy, dict) or not set(policy) <= _ROLLOUT_POLICY_KEYS:
        return (
            "agent_rollout_policy must be an object with only 'mode' and/or "
            "'window' keys."
        )
    if 'mode' in policy and (
        not isinstance(policy['mode'], str) or policy['mode'] not in _ROLLOUT_MODES
    ):
        # isinstance guard first: an unhashable mode (a list or dict) would
        # otherwise raise TypeError on the frozenset membership test below,
        # turning a validation error into an unhandled exception.
        return (
            "agent_rollout_policy.mode must be one of 'latest', 'n_minus_1', "
            "or 'manual'."
        )
    if 'window' in policy:
        window = policy['window']
        if not isinstance(window, dict) or not set(window) <= _ROLLOUT_WINDOW_KEYS:
            return (
                'agent_rollout_policy.window must be an object with only '
                "'days', 'start_hour', 'length_hours', 'timezone' keys."
            )
        if 'days' in window:
            days = window['days']
            if (
                not isinstance(days, list)
                or not days
                or not all(_is_plain_int(day) and 0 <= day <= 6 for day in days)
                or len(set(days)) != len(days)
            ):
                return (
                    'agent_rollout_policy.window.days must be a non-empty '
                    'list of distinct integers 0-6 (Monday is 0).'
                )
        if 'start_hour' in window:
            start_hour = window['start_hour']
            if not _is_plain_int(start_hour) or not 0 <= start_hour <= 23:
                return 'agent_rollout_policy.window.start_hour must be an integer 0-23.'
        if 'length_hours' in window:
            length_hours = window['length_hours']
            if not _is_plain_int(length_hours) or not 1 <= length_hours <= 24:
                return (
                    'agent_rollout_policy.window.length_hours must be an integer 1-24.'
                )
        if 'timezone' in window:
            timezone_name = window['timezone']
            if (
                not isinstance(timezone_name, str)
                or not timezone_name
                or len(timezone_name) > 64
            ):
                return (
                    'agent_rollout_policy.window.timezone must be a valid '
                    'IANA timezone name.'
                )
            try:
                ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                return (
                    'agent_rollout_policy.window.timezone must be a valid '
                    'IANA timezone name.'
                )
    return None


def _collect_workspaces_from_tokens(
    token_manager: TokenManager,
    target_region: str | None = None,
) -> list[dict[str, object]]:
    """Workspace info dicts from token.json, limited to `target_region` when given."""
    workspaces = []
    for region_key, region_data in token_manager.get_all_tokens().items():
        if target_region and region_key != target_region:
            continue

        for workspace_key, workspace_data in region_data.items():
            if isinstance(workspace_data, dict):
                has_token = bool(workspace_data.get('token'))
            else:
                has_token = bool(workspace_data)

            # Resolve the displayed host through the same helper request
            # routing uses (env-var precedence + normalization), so the
            # reported domain always matches http_client.get_base_url()
            # (ADR 0027 slug safety).
            pinned_url = token_manager.get_base_url_override(region_key, workspace_key)
            workspaces.append(
                {
                    'workspace': workspace_key,
                    'region': region_key,
                    'has_token': has_token,
                    'domain': pinned_url or f'{workspace_key}.{region_key}.alpacon.io',
                }
            )
    return workspaces


def _saas_only_security_404(
    result: object, region: str, workspace: str
) -> ToolErrorResponse | None:
    """Turn a 404 error envelope into 'not available' (cloud-only routes), else None;
    a success payload carrying status_code 404 is left alone."""
    if (
        isinstance(result, dict)
        and 'error' in result
        and result.get('status_code') == HTTPStatus.NOT_FOUND
    ):
        return error_response(
            'Workspace security settings are not available on this deployment '
            '(this endpoint is SaaS-only and returns 404 on-premise).',
            region=region,
            workspace=workspace,
            status_code=HTTPStatus.NOT_FOUND,
        )
    return None


@mcp_tool_handler(
    description='List all available workspaces and their regions. Returns workspace names, region codes, domain hostnames, and unusable_entries: the count of workspace claim entries left out because they name no workspace or region, which is non-zero when an Auth0 organization has no region in its metadata; a region filter does not narrow it, and it is always 0 in local mode. In local mode reads from token.json; in server mode extracts from JWT claims. When to use: first tool to call to discover which workspaces are configured. Related: list_servers (find servers in a workspace). Note: Most other tools require a workspace parameter from this list.',
    annotations=READ_ONLY,
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'workspace list regions configured available',
    },
    requires_workspace=False,
)
async def list_workspaces(
    region: ServedRegion | None = None, **kwargs: str
) -> ToolResponse:
    """Get list of available workspaces.

    In local (stdio/SSE) mode, reads from token.json. If region is not specified,
    lists workspaces across all configured regions.

    In server (HTTP/JWT) mode, decodes the JWT token to extract workspace information.
    If region is provided, it filters results to that region only.

    Args:
        region: Region filter (ap1 or us1). None means all regions.

    Returns:
        Workspaces list response. `unusable_entries` counts the JWT workspace
        claim entries that were dropped because they name no workspace or no
        region; a region filter does not narrow it, since such an entry belongs
        to no region. It is always 0 in local mode, which reads token.json.
    """
    # Use explicit transport mode check, not JWT presence
    if is_auth_enabled():
        token = kwargs['token']  # always set: the decorator rejected a missing one
        jwt_workspaces, unusable_entries = get_token_workspaces_with_dropped(token)
        workspaces: list[dict[str, object]] = []
        for ws in jwt_workspaces:
            ws_name = ws.get('schema_name', '')
            ws_region = ws.get('region', '')
            if region and ws_region != region:
                continue
            workspaces.append(
                {
                    'workspace': ws_name,
                    'region': ws_region,
                    'auth0_id': ws.get('auth0_id', ''),
                    'domain': f'{ws_name}.{ws_region}.alpacon.io',
                }
            )

        return success_response(
            data={
                'workspaces': workspaces,
                'unusable_entries': unusable_entries,
                'source': 'jwt',
                'region': region or 'all',
            },
            region=region or 'all',
        )

    # Local mode: read from token.json
    token_manager = get_token_manager()
    workspaces = _collect_workspaces_from_tokens(token_manager, target_region=region)

    return success_response(
        data={
            'workspaces': workspaces,
            'unusable_entries': 0,
            'source': 'token_file',
            'region': region or 'all',
        },
        region=region or 'all',
    )


@mcp_tool_handler(
    description=(
        'Get the current authenticated user info (username, email, role, UID, shell, home directory). '
        'Returns info about the user authenticated for this call. '
        'Use this to verify identity before performing privileged actions. '
        'Related: list_workspaces (find configured workspaces).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'whoami current user identity me authenticated principal',
    },
)
async def get_current_user(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Get the currently authenticated user.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Current user info response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/-/',
        token=token,
        default_message='Failed to get current user',
    )


@mcp_tool_handler(
    description=(
        'Get the workspace access control settings: sudo/root access policy '
        '(allow_sudo_with_mfa, allow_direct_root, block_local_sudo, sudo_timeout), '
        'tunnel/editor defaults, home_directory_permission, Work Session TTLs '
        '(work_session_max_ttl, work_session_pending_ttl), command-env audit exposure, '
        'and shared_account_names. Use this to check what privilege-escalation and '
        'session-lifetime rules apply workspace-wide before requesting elevated access. '
        'Note: on-premise deployments omit the MFA-related fields (allow_sudo_with_mfa, '
        'block_local_sudo, sudo_timeout). '
        'Related: get_workspace_security (MFA/authentication settings), list_sudo_policies.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace access control sudo root tunnel editor home directory work session ttl shared accounts policy',
    },
)
async def get_workspace_access_control(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Get the workspace access control settings.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Workspace access control settings response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/access-control/-/',
        token=token,
        default_message='Failed to get workspace access control settings',
    )


@mcp_tool_handler(
    description=(
        'Get the workspace authentication/security settings: mfa_required, allowed_mfa_methods, '
        'mfa_timeout, and which actions require MFA. '
        'Note: the upstream route authenticates JWT (OAuth/SSO) sessions only, so a static '
        'API token (stdio mode) is rejected before any request is sent; use remote/'
        'streamable-http (browser SSO) mode to read these settings. '
        'Note: this route is also SaaS-only; on-premise deployments return 404 from the '
        'upstream API, and this tool reports that the settings are not available on this '
        'deployment rather than a generic error. '
        'Related: list_workspace_mfa_methods (allowed methods only), get_workspace_access_control.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace security mfa authentication settings',
    },
)
@require_jwt_auth
async def get_workspace_security(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Get the workspace authentication/security settings.

    Requires JWT (OAuth/SSO) authentication: the upstream SecuritySettingsViewSet
    has no APITokenAuthentication, so a static API token is rejected up front.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Workspace security settings response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/security/-/',
        token=token,
    )

    saas_only = _saas_only_security_404(result, region, workspace)
    if saas_only:
        return saas_only

    err = unwrap_http_result(
        result,
        default_message='Failed to get workspace security settings',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'List the MFA methods allowed for this workspace. Returns allowed_mfa_methods and '
        'whether a passkey can satisfy MFA (passkey_as_mfa). Useful when a tool call fails '
        'with an MFA re-authentication requirement (remote/streamable-http mode) and you need '
        'to tell the user which methods they can use to complete the browser re-auth step. '
        'Note: like get_workspace_security, the upstream route authenticates JWT (OAuth/SSO) '
        'sessions only; a static API token (stdio mode) is rejected before any request is '
        'sent, and the route is SaaS-only (on-premise returns a clear not-available message). '
        'Related: get_workspace_security (full security settings).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace mfa methods list allowed passkey reauth',
    },
)
@require_jwt_auth
async def list_workspace_mfa_methods(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """List MFA methods allowed for the workspace.

    Requires JWT (OAuth/SSO) authentication: the upstream mfa-methods action has
    no APITokenAuthentication, so a static API token is rejected up front.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Allowed MFA methods response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/security/-/mfa-methods/',
        token=token,
    )

    saas_only = _saas_only_security_404(result, region, workspace)
    if saas_only:
        return saas_only

    err = unwrap_http_result(
        result,
        default_message='Failed to list workspace MFA methods',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Get the workspace-wide preferences: timezone, locale (country/language), '
        'front_url, invite_ttl, enabled_extensions, websh_session_timeout, '
        'agent_rollout_policy, package_proxy, and billing_email. '
        'agent_rollout_policy is {"mode": "latest"|"n_minus_1"|"manual", "window": '
        '{"days": [0-6, Monday is 0], "start_hour": 0-23, "length_hours": 1-24, '
        '"timezone": "<IANA>"}} and controls automatic agent upgrades. '
        'The response also includes auto_agent_upgrade, a deprecated boolean derived '
        'from agent_rollout_policy (true unless mode is manual) that will be removed '
        'from the server response; read '
        'agent_rollout_policy. This is workspace-global configuration, not a per-user preference. '
        'Related: update_workspace_preferences.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace preferences settings timezone locale billing',
    },
)
async def get_workspace_preferences(
    workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Get the workspace-wide preferences.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Workspace preferences response. `agent_rollout_policy` is the current
        agent-upgrade rollout policy (`mode` plus its upgrade `window`).
        The response also includes `auto_agent_upgrade`, a deprecated boolean
        derived from `agent_rollout_policy` (`true` unless `mode` is `manual`)
        that will be removed from the server response; read `agent_rollout_policy`.
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/preferences/-/',
        token=token,
        default_message='Failed to get workspace preferences',
    )


@mcp_tool_handler(
    description=(
        'Update workspace-wide preferences. Only the fields you provide are sent (partial '
        'update). Fields: front_url, country, language, timezone, invite_ttl, '
        'enabled_extensions, websh_session_timeout, agent_rollout_policy, package_proxy, '
        'billing_email. '
        'agent_rollout_policy controls automatic agent upgrades: {"mode": '
        '"latest"|"n_minus_1"|"manual", "window": {"days": [0-6, Monday is 0], '
        '"start_hour": 0-23, "length_hours": 1-24, "timezone": "<IANA>"}}. A write may '
        'name only part of the object (e.g. just "mode"); what it leaves out keeps its '
        'current value. Validated locally before sending; the server may still refuse '
        'n_minus_1 with 400 preferences_agent_rollout_mode_unavailable when this '
        'deployment has no pinned-upgrade targets enabled yet. '
        "Warning: timezone is the workspace's billing clock—changing it shifts the daily "
        'usage-aggregation boundary. '
        'Warning: enabled_extensions REPLACES the whole list, it does not append; '
        'read the current value via get_workspace_preferences, '
        'merge, then send the full list to avoid dropping existing entries. Narrowing '
        'enabled_extensions additionally fails with HTTP 402 on non-enterprise plans. '
        'Warning: billing_email is only accepted by the server on SaaS '
        'deployments. '
        'Related: get_workspace_preferences.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'workspace preferences update modify timezone billing agent rollout upgrade',
    },
)
async def update_workspace_preferences(
    workspace: str,
    front_url: str | None = None,
    country: str | None = None,
    language: str | None = None,
    timezone: str | None = None,
    invite_ttl: int | None = None,
    enabled_extensions: list[str] | None = None,
    websh_session_timeout: int | None = None,
    package_proxy: str | None = None,
    billing_email: str | None = None,
    agent_rollout_policy: Mapping[str, object] | None = None,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Partial update: only given fields are sent, and an empty
    `agent_rollout_policy` counts as omitted. Errors when nothing is left to send."""
    token = kwargs.get('token')

    update_data: dict[str, object] = exclude_none(
        front_url=front_url,
        country=country,
        language=language,
        timezone=timezone,
        invite_ttl=invite_ttl,
        enabled_extensions=enabled_extensions,
        websh_session_timeout=websh_session_timeout,
        package_proxy=package_proxy,
        billing_email=billing_email,
    )

    if agent_rollout_policy is not None:
        validation_error = _validate_rollout_policy(agent_rollout_policy)
        if validation_error:
            return error_response(validation_error, region=region, workspace=workspace)
        if agent_rollout_policy:
            update_data['agent_rollout_policy'] = agent_rollout_policy

    if not update_data:
        return error_response(
            'No update data provided', region=region, workspace=workspace
        )

    return await http_call_response(
        http_client.patch,
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/preferences/-/',
        token=token,
        default_message='Failed to update workspace preferences',
        data=update_data,
    )
