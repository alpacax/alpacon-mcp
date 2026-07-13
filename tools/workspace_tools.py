"""Workspace management tools for Alpacon MCP server."""

from typing import TypedDict, Unpack

from mcp.types import ToolAnnotations

from server import mcp
from utils.api_types import ToolKwargs, ToolResponse
from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import READ_ONLY


class WorkspaceEntry(TypedDict):
    """Single workspace entry derived from token.json data."""

    workspace: str
    region: str
    has_token: bool
    domain: str


def _collect_workspaces_from_tokens(
    all_tokens: dict[str, object],
    target_region: str = '',
) -> list[WorkspaceEntry]:
    """Collect workspace info from token.json data.

    Args:
        all_tokens: Token data from TokenManager
        target_region: If provided, filter to this region only. Empty means all regions.

    Returns:
        List of workspace info dicts
    """
    workspaces: list[WorkspaceEntry] = []
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
    description='List all available workspaces and their regions. Returns workspace names, region codes, and domain hostnames. In local mode reads from token.json; in server mode extracts from JWT claims. When to use: first tool to call to discover which workspaces are configured. Related: list_servers (find servers in a workspace). Note: Most other tools require a workspace parameter from this list.',
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'workspace list regions configured available',
    },
)
async def list_workspaces(region: str = '') -> ToolResponse:
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
        jwt_ws_list: list[dict[str, str]] = []
        for ws in jwt_workspaces:
            ws_name = ws.get('schema_name', '')
            ws_region = ws.get('region', '')
            if region and ws_region != region:
                continue
            jwt_ws_list.append(
                {
                    'workspace': ws_name,
                    'region': ws_region,
                    'auth0_id': ws.get('auth0_id', ''),
                    'domain': f'{ws_name}.{ws_region}.alpacon.io',
                }
            )

        return success_response(
            data={
                'workspaces': jwt_ws_list,
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
    workspace: str, region: str = '', **kwargs: Unpack[ToolKwargs]
) -> ToolResponse:
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
