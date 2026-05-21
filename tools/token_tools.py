"""API token management tools for Alpacon MCP server."""

from typing import Any

from utils.common import success_response, unwrap_http_result
from utils.decorators import mcp_tool_handler
from utils.error_handler import format_validation_error, validate_server_id_format
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, DESTRUCTIVE, READ_ONLY


@mcp_tool_handler(
    description='List API tokens in the workspace. When to use: reviewing existing API tokens or auditing access. Related: create_api_token (create new), delete_api_token (remove), list_api_token_scopes (available scopes).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token list credentials access'},
)
async def list_api_tokens(
    workspace: str,
    region: str = '',
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """List API tokens.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided
        page: Page number for pagination (optional)
        page_size: Number of items per page (optional)

    Returns:
        API tokens list response
    """
    token = kwargs.get('token')

    params: dict[str, Any] = {}
    if page is not None:
        params['page'] = page
    if page_size is not None:
        params['page_size'] = page_size

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/auth/tokens/',
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
    description='Create a new API token in the workspace. When to use: generating credentials for programmatic access or integrations. Related: list_api_tokens (view existing), delete_api_token (remove), list_api_token_scopes (check available scopes).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'api token create generate credentials'},
)
async def create_api_token(
    workspace: str,
    name: str,
    scopes: list[str] | None = None,
    expires_at: str | None = None,
    enabled: bool | None = None,
    presets: list[str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Create a new API token.

    Args:
        workspace: Workspace name. Required parameter
        name: Name of the API token
        scopes: List of permission scopes for the token (optional)
        expires_at: Expiration datetime in ISO 8601 format (optional)
        enabled: Whether the token is active. Defaults to True on the server (optional)
        presets: Preset scope keys resolved server-side (e.g. "file_upload"). Merged
            with explicit scopes; stored as granular scope strings (optional)
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        API token creation response
    """
    token = kwargs.get('token')

    token_data: dict[str, Any] = {'name': name}
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
        endpoint='/api/auth/tokens/',
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
    description='Delete an API token permanently. When to use: revoking access for a specific token. Related: list_api_tokens (find token ID), duplicate_api_token (create a copy before deleting). Note: This cannot be undone.',
    annotations=DESTRUCTIVE,
    meta={'anthropic/searchHint': 'api token delete revoke remove'},
)
async def delete_api_token(
    token_id: str,
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Delete an API token.

    Args:
        token_id: ID of the API token to delete
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1). Auto-detected if not provided

    Returns:
        API token deletion response
    """
    token = kwargs.get('token')

    if not validate_server_id_format(token_id):
        return format_validation_error(
            'token_id',
            token_id,
            'Must be a valid UUID. Example: 550e8400-e29b-41d4-a716-446655440000',
        )

    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f'/api/auth/tokens/{token_id}/',
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
    description='Duplicate an existing API token to create a copy with the same configuration. When to use: creating a backup token or rotating credentials. Related: list_api_tokens (find token ID), create_api_token (create from scratch), delete_api_token (remove old token after rotation).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'api token duplicate copy clone rotate'},
)
async def duplicate_api_token(
    token_id: str,
    workspace: str,
    name: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
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

    if not validate_server_id_format(token_id):
        return format_validation_error(
            'token_id',
            token_id,
            'Must be a valid UUID. Example: 550e8400-e29b-41d4-a716-446655440000',
        )

    data: dict[str, Any] = {}
    if name is not None:
        data['name'] = name

    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/auth/tokens/{token_id}/duplicate/',
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
    description='List available API token scopes. When to use: before creating a token, to see which permission scopes can be assigned. Related: create_api_token (use scopes when creating), list_api_tokens (view tokens and their scopes).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'api token scopes permissions available'},
)
async def list_api_token_scopes(
    workspace: str,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
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
        endpoint='/api/auth/tokens/scopes/',
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
