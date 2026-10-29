"""API token tools; a `source='api'` token (stdio token.json) is refused by the API.
The write tools refuse it up front, list/get 403 upstream; the catalogs are exempt."""

from utils.api_call import http_call_response
from utils.common import build_list_params, error_response, exclude_none
from utils.decorators import mcp_tool_handler, require_jwt_auth
from utils.error_handler import uuid_field_error
from utils.http_client import http_client
from utils.tool_annotations import (
    ADDITIVE,
    DESTRUCTIVE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from utils.types import ToolResponse

_API_TOKENS = '/api/auth/tokens/'
_API_TOKEN_SCOPES = f'{_API_TOKENS}scopes/'
_API_TOKEN_PRESETS = f'{_API_TOKENS}presets/'

_JWT_REQUIRED_NOTE = (
    "Returns 403 Forbidden when called with a source='api' API token; "
    'use JWT/OAuth, a browser session, or a login-source token instead.'
)


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
    search: str | None = None,
    ordering: str | None = None,
    **kwargs: str,
) -> ToolResponse:
    """List API tokens.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)
        name: Filter by exact token name (optional)
        enabled: Filter by enabled status (optional)
        search: Free-text search across name (optional)
        ordering: Sort field, e.g. "-updated_at" (server default), "added_at".
            Multiple fields may be comma-separated. Available fields:
            added_at, updated_at, last_used_at. Not validated client-side - the
            server rejects unknown fields (optional)

    Returns:
        API tokens list response
    """
    token = kwargs.get('token')

    params = build_list_params(
        page=page,
        page_size=page_size,
        name=name,
        enabled=enabled,
        search=search,
        ordering=ordering,
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=_API_TOKENS,
        token=token,
        default_message='Failed to list API tokens',
        params=params,
    )


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
    **kwargs: str,
) -> ToolResponse:
    """Get a single API token.

    Args:
        token_id: ID of the API token to retrieve
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        API token detail response
    """
    token = kwargs.get('token')

    err = uuid_field_error('token_id', token_id)
    if err:
        return err

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/',
        token=token,
        default_message='Failed to get API token',
        token_id=token_id,
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
    **kwargs: str,
) -> ToolResponse:
    """Create a token; `presets` merge with `scopes` server-side, expiry defaults to the
    workspace maximum."""
    token = kwargs.get('token')

    token_data: dict[str, object] = {
        'name': name,
        **exclude_none(
            scopes=scopes, expires_at=expires_at, enabled=enabled, presets=presets
        ),
    }

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=_API_TOKENS,
        token=token,
        default_message='Failed to create API token',
        data=token_data,
    )


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
    **kwargs: str,
) -> ToolResponse:
    """PATCH only the fields passed; `expires_at` and `clear_expires_at` are exclusive.
    `clear_expires_at` resets expiry to the maximum; `scopes` face the RBAC cap."""
    token = kwargs.get('token')

    err = uuid_field_error('token_id', token_id)
    if err:
        return err

    if expires_at is not None and clear_expires_at:
        return error_response('expires_at and clear_expires_at are mutually exclusive')

    update_data: dict[str, object] = exclude_none(
        name=name, enabled=enabled, scopes=scopes
    )
    if expires_at is not None:
        update_data['expires_at'] = expires_at
    elif clear_expires_at:
        update_data['expires_at'] = None

    if not update_data:
        return error_response('No update data provided')

    return await http_call_response(
        http_client.patch,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/',
        token=token,
        default_message='Failed to update API token',
        data=update_data,
        token_id=token_id,
    )


@mcp_tool_handler(
    description=(
        'Delete an API token permanently. When to use: revoking access for a specific token. '
        'Related: list_api_tokens (find token ID), update_api_token (disable instead of deleting), '
        f'rotate_api_token (regenerate the secret instead of deleting). Note: This cannot be undone. {_JWT_REQUIRED_NOTE}'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'api token delete revoke remove'},
)
@require_jwt_auth
async def delete_api_token(
    token_id: str,
    workspace: str,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """Delete an API token; this cannot be undone."""
    token = kwargs.get('token')

    err = uuid_field_error('token_id', token_id)
    if err:
        return err

    return await http_call_response(
        http_client.delete,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/',
        token=token,
        default_message='Failed to delete API token',
        token_id=token_id,
    )


@mcp_tool_handler(
    description=(
        'Duplicate an existing API token, copying its configuration subject to current scope and expiry '
        'policy: scopes that can no longer be granted are dropped, and expiry is capped at the '
        "workspace's current maximum. When to use: creating a second token like an existing one. "
        'To roll a leaked or aging key use '
        'rotate_api_token; duplicate leaves the original key live. Related: list_api_tokens (find token ID), '
        'create_api_token (create from scratch), rotate_api_token (regenerate the secret in place), '
        'delete_api_token (revoke the original key). '
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
    **kwargs: str,
) -> ToolResponse:
    """Copy a token under current policy: ungrantable scopes are dropped and expiry is
    capped at the workspace maximum."""
    token = kwargs.get('token')

    err = uuid_field_error('token_id', token_id)
    if err:
        return err

    data: dict[str, object] = exclude_none(name=name)

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/duplicate/',
        token=token,
        default_message='Failed to duplicate API token',
        data=data,
        token_id=token_id,
    )


@mcp_tool_handler(
    description=(
        'Rotate an API token: regenerate its secret in place. The old secret stops '
        'authenticating the moment this returns, with no grace period, so anything still using it '
        'breaks until it is given the new one. The token id, name, scopes and Command/Server/'
        'File ACLs are preserved, and so is an expiry the token already had—but a token with no '
        'expiry comes back carrying the workspace maximum, so rotation cannot keep a '
        'never-expiring key never-expiring. A token already past its expiry is refused with 400 '
        'API_TOKEN_ALREADY_EXPIRED, so this is not a way to revive one. Otherwise only the secret '
        'and the usage counters change. Requires a '
        'paid plan. Prefer this over duplicate_api_token when rolling a leaked or aging key: '
        'duplicate leaves the old key live. '
        'Related: list_api_tokens (find token ID), duplicate_api_token (copy instead of rotate), '
        'delete_api_token (revoke outright). '
        f'{_JWT_REQUIRED_NOTE}'
    ),
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'api token rotate regenerate reissue key secret'},
)
@require_jwt_auth
async def rotate_api_token(
    token_id: str, workspace: str, region: str = '', **kwargs: str
) -> ToolResponse:
    """Replace the secret in place; no expiry becomes the workspace maximum, and
    an expired token is refused with 400 API_TOKEN_ALREADY_EXPIRED."""
    token = kwargs.get('token')

    err = uuid_field_error('token_id', token_id)
    if err:
        return err

    return await http_call_response(
        http_client.post,
        region=region,
        workspace=workspace,
        endpoint=f'{_API_TOKENS}{token_id}/rotate/',
        token=token,
        default_message='Failed to rotate API token',
        token_id=token_id,
    )


@mcp_tool_handler(
    description='List available API token scopes. When to use: before creating a token, to see which permission scopes can be assigned. Related: create_api_token (use scopes when creating), list_api_token_presets (bundled preset keys), list_api_tokens (view tokens and their scopes).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token scopes permissions available'},
)
async def list_api_token_scopes(
    workspace: str,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """List available API token scopes.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Available API token scopes response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=_API_TOKEN_SCOPES,
        token=token,
        default_message='Failed to list API token scopes',
    )


@mcp_tool_handler(
    description='List available API token scope presets. When to use: before creating a token, to discover bundled scope shortcuts (e.g. "file_upload") that can be passed to create_api_token. Related: list_api_token_scopes (granular scopes), create_api_token (use presets when creating).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token preset scopes bundle catalog'},
)
async def list_api_token_presets(
    workspace: str,
    region: str = '',
    **kwargs: str,
) -> ToolResponse:
    """List available API token scope presets.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Available API token presets response
    """
    token = kwargs.get('token')

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint=_API_TOKEN_PRESETS,
        token=token,
        default_message='Failed to list API token presets',
    )
