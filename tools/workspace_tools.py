"""Workspace management tools for Alpacon MCP server."""

from typing import Any

from mcp.types import ToolAnnotations

from server import mcp
from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.token_manager import TokenManager
from utils.tool_annotations import IDEMPOTENT_WRITE, READ_ONLY


def _collect_workspaces_from_tokens(
    token_manager: TokenManager,
    target_region: str = '',
) -> list[dict[str, Any]]:
    """Collect workspace info from token.json data.

    Args:
        token_manager: TokenManager to read entries and pinned URL overrides from.
        target_region: If provided, filter to this region only. Empty means all regions.

    Returns:
        List of workspace info dicts
    """
    workspaces = []
    for region_key, region_data in token_manager.get_all_tokens().items():
        if target_region and region_key != target_region:
            continue

        if isinstance(region_data, dict):
            for workspace_key, workspace_data in region_data.items():
                if isinstance(workspace_data, dict):
                    has_token = bool(workspace_data.get('token'))
                else:
                    has_token = bool(workspace_data)

                # Resolve the displayed host through the same helper request
                # routing uses (env-var precedence + normalization), so the
                # reported domain always matches http_client.get_base_url()
                # (ADR 0027 slug safety).
                pinned_url = token_manager.get_base_url_override(
                    region_key, workspace_key
                )
                workspaces.append(
                    {
                        'workspace': workspace_key,
                        'region': region_key,
                        'has_token': has_token,
                        'domain': pinned_url
                        or f'{workspace_key}.{region_key}.alpacon.io',
                    }
                )
        else:
            workspaces.append(
                {
                    'workspace': region_key,
                    'region': region_key,
                    'has_token': bool(region_data),
                    'domain': f'{region_key}.{region_key}.alpacon.io',
                }
            )
    return workspaces


def _saas_only_security_404(
    result: Any, region: str, workspace: str
) -> dict[str, Any] | None:
    """Translate a SaaS-only 404 into a clear "not available" error.

    The SecuritySettingsViewSet routes (security settings and their mfa-methods
    sub-route) are only registered under AUTH0_ENABLED, so on-premise
    deployments return 404. Requires the http_client `error` key (matching
    unwrap_http_result) so a success payload carrying status_code 404 is not
    misread. Returns an error_response when the result is a 404 error envelope,
    else None so the caller continues with normal unwrapping.
    """
    if (
        isinstance(result, dict)
        and 'error' in result
        and result.get('status_code') == 404
    ):
        return error_response(
            'Workspace security settings are not available on this deployment '
            '(this endpoint is SaaS-only and returns 404 on-premise).',
            region=region,
            workspace=workspace,
            status_code=404,
        )
    return None


@mcp.tool(
    description='List all available workspaces and their regions. Returns workspace names, region codes, and domain hostnames. In local mode reads from token.json; in server mode extracts from JWT claims. When to use: first tool to call to discover which workspaces are configured. Related: list_servers (find servers in a workspace). Note: Most other tools require a workspace parameter from this list.',
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'workspace list regions configured available',
    },
)
async def list_workspaces(region: str = '') -> dict[str, Any]:
    """Get list of available workspaces.

    In local (stdio/SSE) mode, reads from token.json. If region is not specified,
    lists workspaces across all configured regions.

    In server (HTTP/JWT) mode, decodes the JWT token to extract workspace information.
    If region is provided, it filters results to that region only.

    Args:
        region: Region filter (e.g., ap1, us1, eu1). Empty string means all regions.

    Returns:
        Workspaces list response
    """
    from utils.decorators import _get_jwt_token, _get_jwt_workspaces, _is_auth_enabled

    # Use explicit transport mode check, not JWT presence
    if _is_auth_enabled():
        jwt_token = _get_jwt_token()
        if not jwt_token:
            return error_response(
                'Authentication required. No JWT token found in request context.'
            )
        # Server mode: extract workspaces from JWT claims
        jwt_workspaces = _get_jwt_workspaces(jwt_token)
        workspaces = []
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
                'source': 'jwt',
                'region': region or 'all',
            },
            region=region or 'all',
        )

    # Local mode: read from token.json
    from utils.token_manager import get_token_manager

    token_manager = get_token_manager()
    workspaces = _collect_workspaces_from_tokens(token_manager, target_region=region)

    return success_response(
        data={
            'workspaces': workspaces,
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
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the currently authenticated user.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Current user info response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/iam/users/-/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get current user',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


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
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the workspace access control settings.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Workspace access control settings response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/access-control/-/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get workspace access control settings',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Get the workspace authentication/security settings: mfa_required, allowed_mfa_methods, '
        'mfa_timeout, and which actions require MFA. '
        'Note: this route is SaaS-only; on-premise deployments return 404 from the upstream '
        'API, and this tool reports that the settings are not available on this deployment '
        'rather than a generic error. '
        'Related: list_workspace_mfa_methods (allowed methods only), get_workspace_access_control.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace security mfa authentication settings',
    },
)
async def get_workspace_security(
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the workspace authentication/security settings.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

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
        'Related: get_workspace_security (full security settings).'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace mfa methods list allowed passkey reauth',
    },
)
async def list_workspace_mfa_methods(
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """List MFA methods allowed for the workspace.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

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
        'Get the workspace notification settings: disconnection_notification and the '
        'notification_channels used to deliver workspace-level alerts. '
        'Related: update_workspace_notifications, list_webhooks, list_event_subscriptions.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace notifications settings disconnection channels',
    },
)
async def get_workspace_notifications(
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the workspace notification settings.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Workspace notification settings response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/notifications/-/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get workspace notification settings',
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
        'auto_agent_upgrade, package_proxy, billing_email, and allowed_domains. '
        'This is workspace-global configuration, not a per-user preference. '
        'Related: update_workspace_preferences, get_workspace_notifications.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'workspace preferences settings timezone locale billing',
    },
)
async def get_workspace_preferences(
    workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the workspace-wide preferences.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Workspace preferences response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/preferences/-/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get workspace preferences',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Update workspace notification settings. Only the fields you provide are sent '
        '(partial update). Fields: disconnection_notification (bool, notify when a server '
        'disconnects/goes offline), notification_channels (list of channel types to notify '
        'through: email, webhook, push). Related: get_workspace_notifications.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'workspace notifications update modify settings',
    },
)
async def update_workspace_notifications(
    workspace: str,
    disconnection_notification: bool | None = None,
    notification_channels: list[str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update the workspace notification settings (partial update).

    Args:
        workspace: Workspace name. Required parameter
        disconnection_notification: Notify when a server disconnects (optional)
        notification_channels: Channel types to notify through, e.g. email/webhook/push (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Workspace notification update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if disconnection_notification is not None:
        update_data['disconnection_notification'] = disconnection_notification
    if notification_channels is not None:
        update_data['notification_channels'] = notification_channels

    if not update_data:
        return error_response(
            'No update data provided', region=region, workspace=workspace
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/notifications/-/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update workspace notification settings',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Update workspace-wide preferences. Only the fields you provide are sent (partial '
        'update). Fields: front_url, country, language, timezone, invite_ttl, '
        'enabled_extensions, websh_session_timeout, auto_agent_upgrade, package_proxy, '
        'billing_email, allowed_domains. '
        "Warning: timezone is the workspace's billing clock—changing it shifts the daily "
        'usage-aggregation boundary. '
        'Warning: billing_email and allowed_domains are only accepted by the server on SaaS '
        'deployments. '
        'Related: get_workspace_preferences.'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'workspace preferences update modify timezone billing',
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
    auto_agent_upgrade: bool | None = None,
    package_proxy: str | None = None,
    billing_email: str | None = None,
    allowed_domains: list[str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Update the workspace-wide preferences (partial update).

    Args:
        workspace: Workspace name. Required parameter
        front_url: Workspace front-end URL (optional)
        country: Workspace country code (optional)
        language: Workspace locale/language code (optional)
        timezone: Workspace timezone; also the billing clock (optional)
        invite_ttl: Invitation link time-to-live, in seconds (optional)
        enabled_extensions: List of enabled extension names (optional)
        websh_session_timeout: Websh idle session timeout, in seconds (optional)
        auto_agent_upgrade: Whether agents auto-upgrade (optional)
        package_proxy: Proxy server URL for package installation, e.g.
            http://proxy.example.com:8080 (optional)
        billing_email: Billing contact email; SaaS-only field (optional)
        allowed_domains: Allowed email domains for invites; SaaS-only field (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Workspace preferences update response
    """
    token = kwargs.get('token')

    update_data: dict[str, Any] = {}
    if front_url is not None:
        update_data['front_url'] = front_url
    if country is not None:
        update_data['country'] = country
    if language is not None:
        update_data['language'] = language
    if timezone is not None:
        update_data['timezone'] = timezone
    if invite_ttl is not None:
        update_data['invite_ttl'] = invite_ttl
    if enabled_extensions is not None:
        update_data['enabled_extensions'] = enabled_extensions
    if websh_session_timeout is not None:
        update_data['websh_session_timeout'] = websh_session_timeout
    if auto_agent_upgrade is not None:
        update_data['auto_agent_upgrade'] = auto_agent_upgrade
    if package_proxy is not None:
        update_data['package_proxy'] = package_proxy
    if billing_email is not None:
        update_data['billing_email'] = billing_email
    if allowed_domains is not None:
        update_data['allowed_domains'] = allowed_domains

    if not update_data:
        return error_response(
            'No update data provided', region=region, workspace=workspace
        )

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint='/api/workspaces/preferences/-/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update workspace preferences',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)
