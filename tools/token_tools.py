"""API token management tools for Alpacon MCP server.

Authentication note: ``api/apitoken/permissions.py:APITokenObjectPermission``
rejects any request whose ``request.auth`` is an ``APIToken`` with
``source='api'``. The list/retrieve/create/update/delete/duplicate
tools below therefore return ``403 Forbidden`` when called from stdio
mode using a token from ``token.json`` (which is a ``source='api'``
token). Other authentication paths (JWT/OAuth in streamable-http
remote mode, browser session, ``source='login'`` token) pass the
check. The scopes and presets catalog endpoints are not subject to
this restriction.
"""

from typing import Unpack

from utils.api_types import ToolKwargs, ToolResponse
from utils.common import error_response, success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler, require_jwt_auth
from utils.error_handler import format_validation_error, validate_server_id_format
from utils.http_client import http_client
from utils.tool_annotations import (
    ADDITIVE,
    DESTRUCTIVE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)

_API_TOKENS = '/api/auth/tokens/'
_API_TOKEN_SCOPES = f'{_API_TOKENS}scopes/'
_API_TOKEN_PRESETS = f'{_API_TOKENS}presets/'

_JWT_REQUIRED_NOTE = (
    "Returns 403 Forbidden when called with a source='api' API token; "
    'use JWT/OAuth, a browser session, or a login-source token instead.'
)


def _validate_token_id(token_id: str) -> ToolResponse | None:
    if not validate_server_id_format(token_id):
        return format_validation_error(
            'token_id',
            token_id,
            'Must be a valid UUID. Example: 550e8400-e29b-41d4-a716-446655440000',
        )
    return None


@mcp_tool_handler(
    description=(
        'List API tokens in the workspace. When to use: reviewing existing API tokens or auditing access. '
        'Related: get_api_token (detail), create_api_token (create new), update_api_token (modify), '
        'delete_api_token (remove), list_api_token_scopes (available scopes). '
        f'{_JWT_REQUIRED_NOTE}'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token list credentials access'},
)
async def list_api_tokens(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    name: str | None = None,
    enabled: bool | None = None,
    remote_ip: str | None = None,
    search: str | None = None,
    ordering: str | None = None,
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List API tokens.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)
        name: Filter by exact token name (optional)
        enabled: Filter by enabled status (optional)
        remote_ip: Filter by remote IP that last used the token (optional)
        search: Free-text search across name, user_agent, remote_ip (optional)
        ordering: Sort field, e.g. "-updated_at" (server default), "added_at".
            Multiple fields may be comma-separated. Available fields:
            updated_at, added_at. Not validated client-side - the server
            rejects unknown fields (optional)

    Returns:
        API tokens list response
    """
    token = kwargs.get('token')

    params: dict[str, object] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size
    if name is not None:
        params['name'] = name
    if enabled is not None:
        params['enabled'] = enabled
    if remote_ip is not None:
        params['remote_ip'] = remote_ip
    if search is not None:
        params['search'] = search
    if ordering is not None:
        params['ordering'] = ordering

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_TOKENS,
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list API tokens',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        "Get detailed information about a specific API token by ID. When to use: inspecting a token's "
        'scopes, expiry, or enabled status. Related: list_api_tokens (find token ID), update_api_token '
        f'(modify), delete_api_token (remove). {_JWT_REQUIRED_NOTE}'
    ),
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token get detail retrieve'},
)
async def get_api_token(
    token_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Get a single API token.

    Args:
        token_id: ID of the API token to retrieve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        API token detail response
    """
    token = kwargs.get('token')

    err = _validate_token_id(token_id)
    if err:
        return err

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get API token',
        token_id=token_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, token_id=token_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Create a new API token in the workspace. When to use: generating credentials for programmatic '
        'access or integrations. Related: list_api_tokens (view existing), update_api_token (modify), '
        'delete_api_token (remove), list_api_token_scopes (check available scopes), '
        f'list_api_token_presets (preset catalog). {_JWT_REQUIRED_NOTE}'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'api token create generate credentials'},
)
@require_jwt_auth
async def create_api_token(
    workspace: str,
    name: str,
    scopes: list[str] | None = None,
    expires_at: str | None = None,
    enabled: bool | None = None,
    presets: list[str] | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Create a new API token.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the API token
        scopes: List of permission scopes for the token (optional)
        expires_at: Expiration datetime in ISO 8601 format (optional)
        enabled: Whether the token is active. Defaults to True on the server (optional)
        presets: Preset scope keys resolved server-side. Merged with explicit
            scopes; stored as granular scope strings. Call
            list_api_token_presets to discover available keys (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        API token creation response
    """
    token = kwargs.get('token')

    token_data: dict[str, object] = {'name': name}
    if scopes is not None:
        token_data['scopes'] = scopes
    if expires_at is not None:
        token_data['expires_at'] = expires_at
    if enabled is not None:
        token_data['enabled'] = enabled
    if presets is not None:
        token_data['presets'] = presets

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=_API_TOKENS,
        token=token,
        data=token_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to create API token',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description=(
        'Update an existing API token. When to use: toggling enabled status, changing the expiration '
        'time, renaming, or narrowing scopes without rotating the key. Related: get_api_token (read '
        'current state), create_api_token (create new), delete_api_token (remove). '
        f'Note: presets are create-only and rejected on update. {_JWT_REQUIRED_NOTE}'
    ),
    annotations=IDEMPOTENT_WRITE,
    meta={
        'anthropic/searchHint': 'api token update modify enable disable expire rename'
    },
)
@require_jwt_auth
async def update_api_token(
    token_id: str,
    workspace: str,
    name: str | None = None,
    enabled: bool | None = None,
    expires_at: str | None = None,
    clear_expires_at: bool = False,
    scopes: list[str] | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Update an API token via PATCH.

    Only the fields you pass are sent; everything else is left untouched
    on the server. The server enforces the caller's RBAC scope ceiling
    when ``scopes`` is included.

    Args:
        token_id: ID of the API token to update
        workspace: Workspace name. Required parameter
        name: New token name (optional)
        enabled: Toggle the token's enabled state (optional)
        expires_at: New expiration datetime in ISO 8601 format. Mutually
            exclusive with clear_expires_at (optional)
        clear_expires_at: When True, remove the expiry so the token never
            expires. Mutually exclusive with expires_at (optional)
        scopes: Replacement scope list. Re-validated against the caller's
            RBAC ceiling (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        API token update response
    """
    token = kwargs.get('token')

    err = _validate_token_id(token_id)
    if err:
        return err

    if expires_at is not None and clear_expires_at:
        return error_response('expires_at and clear_expires_at are mutually exclusive')

    update_data: dict[str, object] = {}
    if name is not None:
        update_data['name'] = name
    if enabled is not None:
        update_data['enabled'] = enabled
    if expires_at is not None:
        update_data['expires_at'] = expires_at
    elif clear_expires_at:
        update_data['expires_at'] = None
    if scopes is not None:
        update_data['scopes'] = scopes

    if not update_data:
        return error_response('No update data provided')

    result = await http_client.patch(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/',
        token=token,
        data=update_data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to update API token',
        token_id=token_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, token_id=token_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Delete an API token permanently. When to use: revoking access for a specific token. '
        'Related: list_api_tokens (find token ID), update_api_token (disable instead of deleting), '
        f'duplicate_api_token (create a copy before deleting). Note: This cannot be undone. {_JWT_REQUIRED_NOTE}'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'api token delete revoke remove'},
)
@require_jwt_auth
async def delete_api_token(
    token_id: str,
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Delete an API token.

    Args:
        token_id: ID of the API token to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        API token deletion response
    """
    token = kwargs.get('token')

    err = _validate_token_id(token_id)
    if err:
        return err

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/',
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to delete API token',
        token_id=token_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, token_id=token_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description=(
        'Duplicate an existing API token to create a copy with the same configuration. When to use: '
        'creating a backup token or rotating credentials. Related: list_api_tokens (find token ID), '
        'create_api_token (create from scratch), delete_api_token (remove old token after rotation). '
        f'{_JWT_REQUIRED_NOTE}'
    ),
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'api token duplicate copy clone rotate'},
)
@require_jwt_auth
async def duplicate_api_token(
    token_id: str,
    workspace: str,
    name: str | None = None,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """Duplicate an API token.

    The duplicate inherits all configuration (scopes, expiry) from the source
    token. If name is omitted, the server generates one (e.g. "Token (copy)").

    Args:
        token_id: ID of the API token to duplicate
        workspace: Workspace name. Required parameter
        name: Name for the duplicated token (optional; server auto-generates if omitted)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Duplicated API token response
    """
    token = kwargs.get('token')

    err = _validate_token_id(token_id)
    if err:
        return err

    data: dict[str, object] = {}
    if name is not None:
        data['name'] = name

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/duplicate/',
        token=token,
        data=data,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to duplicate API token',
        token_id=token_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result, token_id=token_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='List available API token scopes. When to use: before creating a token, to see which permission scopes can be assigned. Related: create_api_token (use scopes when creating), list_api_token_presets (bundled preset keys), list_api_tokens (view tokens and their scopes).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token scopes permissions available'},
)
async def list_api_token_scopes(
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List available API token scopes.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Available API token scopes response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_TOKEN_SCOPES,
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list API token scopes',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)


@mcp_tool_handler(
    description='List available API token scope presets. When to use: before creating a token, to discover bundled scope shortcuts (e.g. "file_upload") that can be passed to create_api_token. Related: list_api_token_scopes (granular scopes), create_api_token (use presets when creating).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token preset scopes bundle catalog'},
)
async def list_api_token_presets(
    workspace: str,
    region: str = '',
    **kwargs: Unpack[ToolKwargs],
) -> ToolResponse:
    """List available API token scope presets.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        Available API token presets response
    """
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=_API_TOKEN_PRESETS,
        token=token,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to list API token presets',
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(data=result, region=region, workspace=workspace)
