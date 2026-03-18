"""Workspace management tools for Alpacon MCP server."""

from typing import Any

from server import mcp
from utils.common import success_response


def _collect_workspaces_from_tokens(
    all_tokens: dict[str, Any],
    target_region: str = '',
) -> list[dict[str, Any]]:
    """Collect workspace info from token.json data.

    Args:
        all_tokens: Token data from TokenManager
        target_region: If provided, filter to this region only. Empty means all regions.

    Returns:
        List of workspace info dicts
    """
    workspaces = []
    for region_key, region_data in all_tokens.items():
        if target_region and region_key != target_region:
            continue

        if isinstance(region_data, dict):
            for workspace_key, workspace_data in region_data.items():
                if isinstance(workspace_data, dict):
                    has_token = bool(workspace_data.get('token'))
                else:
                    has_token = bool(workspace_data)

                workspaces.append(
                    {
                        'workspace': workspace_key,
                        'region': region_key,
                        'has_token': has_token,
                        'domain': f'{workspace_key}.{region_key}.alpacon.io',
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


@mcp.tool(
    description='List all available workspaces and their regions. Returns workspace names, region codes, and domain hostnames. In local mode reads from token.json; in server mode extracts from JWT claims. Use this to discover which workspaces are configured before calling other tools.'
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
            from utils.common import error_response

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
    all_tokens = token_manager.get_all_tokens()
    workspaces = _collect_workspaces_from_tokens(all_tokens, target_region=region)

    return success_response(
        data={
            'workspaces': workspaces,
            'source': 'token_file',
            'region': region or 'all',
        },
        region=region or 'all',
    )


# ===============================
# NOTE: User settings and profile endpoints are not implemented in the server
# The following functions have been removed:
# - get_user_settings (was using /api/user/settings/)
# - update_user_settings (was using /api/user/settings/)
# - get_user_profile (was using /api/user/profile/)
#
# Alternative endpoints available in the server:
# - /api/profiles/preferences/ (profiles app)
# - /api/workspaces/preferences/ (workspaces app)
# - /api/auth0/users/ (auth0 app)
# ===============================
