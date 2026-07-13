"""Decorators for MCP tools to reduce boilerplate code."""

from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from mcp.types import ToolAnnotations

from utils.api_types import JwtClaims, ToolMeta, ToolResponse
from utils.common import error_response, token_error_response, validate_token
from utils.error_handler import (
    UpstreamAuthError,
    format_validation_error,
    validate_region_format,
    validate_server_id_format,
    validate_workspace_format,
)
from utils.http_client import AlpaconHTTPClient
from utils.logger import get_logger

logger = get_logger('decorators')

P = ParamSpec('P')
R = TypeVar('R')


def _is_auth_enabled() -> bool:
    """Check if OAuth2 authentication mode is enabled (streamable-http transport).

    Returns True when running in streamable-http mode with Auth0 JWT auth.
    Returns False when running in stdio/SSE mode with token.json.
    """
    return os.getenv('ALPACON_MCP_AUTH_ENABLED', '').lower() == 'true'


def _get_jwt_token() -> str | None:
    """Get JWT token from FastMCP auth context if available.

    Returns the raw JWT string when running in HTTP transport mode
    with JWT authentication. Returns None in stdio/SSE mode.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access_token = get_access_token()
        if access_token is not None:
            return access_token.token
    except ImportError:
        pass
    return None


def _decode_jwt_claims(jwt_token: str) -> JwtClaims | None:
    """Decode JWT claims without verification (already verified by middleware)."""
    try:
        import jwt as pyjwt

        return pyjwt.decode(
            jwt_token,
            options={
                'verify_signature': False,
                'verify_aud': False,
                'verify_iss': False,
                'verify_exp': False,
            },
        )
    except Exception as e:
        logger.error(f'JWT decode failed: {e}')
        return None


def _get_jwt_workspaces(jwt_token: str) -> list[dict[str, str]]:
    """Extract workspace list from JWT claims."""
    from utils.auth import extract_workspaces

    claims = _decode_jwt_claims(jwt_token)
    if not claims:
        return []

    namespace = os.getenv('AUTH0_NAMESPACE', 'https://alpacon.io/').rstrip('/') + '/'
    return extract_workspaces(claims, namespace)


def _validate_jwt_workspace(jwt_token: str, region: str, workspace: str) -> bool:
    """Validate that the JWT authorizes access to the given workspace/region."""
    try:
        from utils.auth import match_workspace

        workspaces = _get_jwt_workspaces(jwt_token)
        return match_workspace(workspaces, region, workspace)
    except Exception as e:
        logger.error(f'JWT workspace validation failed: {e}')
        return False


def _resolve_region_from_jwt(
    jwt_token: str, workspace: str | None = None
) -> str | None:
    """Resolve region from JWT claims.

    If workspace is given, find its region. Otherwise, return region if only one exists.
    """
    workspaces = _get_jwt_workspaces(jwt_token)
    if not workspaces:
        return None

    if workspace:
        matching = [
            ws.get('region') for ws in workspaces if ws.get('schema_name') == workspace
        ]
        if len(matching) == 1:
            return matching[0]
        return None

    regions = list({ws.get('region') for ws in workspaces if ws.get('region')})
    if len(regions) == 1:
        return regions[0]
    return None


def _resolve_region_jwt(
    jwt_token: str, workspace: str | None
) -> tuple[str | None, str | None]:
    """Resolve region from JWT claims.

    Returns:
        (resolved_region, error_message) - one of them will be None
    """
    region = _resolve_region_from_jwt(jwt_token, workspace)
    if region:
        return region, None

    ws_list = _get_jwt_workspaces(jwt_token)
    available_regions = sorted(
        {ws.get('region') or '?' for ws in ws_list if isinstance(ws, dict)}
    )
    if available_regions:
        return None, (
            f'Multiple regions available in token: {", ".join(available_regions)}. '
            f'Please specify a region parameter.'
        )
    return None, 'No regions found in JWT token.'


def _resolve_region_local(workspace: str | None) -> tuple[str | None, str | None]:
    """Resolve region from token.json configuration.

    Returns:
        (resolved_region, error_message) - one of them will be None
    """
    from utils.token_manager import get_token_manager

    tm = get_token_manager()

    if workspace:
        region = tm.find_region_for_workspace(workspace)
        if region:
            return region, None

    default_region = tm.get_default_region()
    if default_region:
        return default_region, None

    available_regions = tm.get_available_regions()
    if available_regions:
        return None, (
            f'Multiple regions available: {", ".join(sorted(available_regions))}. '
            f'Please specify a region parameter.'
        )
    return None, 'No regions configured. Please run setup first.'


async def _check_mfa_requirement(
    tool_name: str, jwt_token: str, workspace: str
) -> None:
    """Check if MFA is required for this tool call and raise if needed.

    Fetches workspace security settings, checks the JWT's MFA completion
    claims, and raises UpstreamAuthError if MFA is required but
    expired/missing. The ASGI middleware catches this exception and
    returns HTTP 401 with MFA scope to trigger re-authentication.

    Fails open on errors — the upstream API will catch it as a fallback.

    Raises:
        UpstreamAuthError: If MFA is required but not completed.
    """
    from utils.security_settings import (
        check_mfa_completed,
        get_action_for_tool,
        security_cache,
    )

    action = get_action_for_tool(tool_name)
    if not action:
        return

    try:
        settings = await security_cache.get_settings(jwt_token, workspace)
        if not settings or not settings.is_action_mfa_required(action):
            return

        claims = _decode_jwt_claims(jwt_token)
        if not claims:
            return

        if check_mfa_completed(claims, settings):
            return

        # MFA required but not completed — also set dict signal as fallback
        from utils.error_handler import make_auth_error_key, signal_upstream_auth_error

        token_key = make_auth_error_key(jwt_token)
        signal_upstream_auth_error(
            token_key,
            {'mfa_required': True, 'source': action},
        )
        logger.info(
            'MFA pre-check: %s requires MFA for workspace %s, raising UpstreamAuthError',
            action,
            workspace,
        )
        raise UpstreamAuthError(mfa_required=True, source=action)
    except UpstreamAuthError:
        raise
    except Exception as e:
        # Fail-open: if pre-check fails, let the API call proceed.
        # The upstream API's own MFA check will catch it as a fallback.
        logger.debug('MFA pre-check failed (non-fatal): %s', e)


def with_token_validation[R, **P](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Decorator to add automatic token validation to MCP tools.

    Transport mode is determined by ALPACON_MCP_AUTH_ENABLED env var:
    - 'true' (streamable-http): Uses JWT from auth context only.
      Never falls back to token.json.
    - unset/other (stdio): Uses token.json only.
      Never tries JWT auth context.

    Args:
        func: The async function to decorate

    Returns:
        Decorated async function with modified signature (removes _token parameter)
    """

    def _fail(resp: ToolResponse) -> R:
        # Concrete R is always ToolResponse, which the generic decorator
        # can't express; every validation early-exit shares this one cast.
        return cast(R, resp)

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Remove _token from kwargs if present (MCP doesn't allow _ prefix)
        kwargs.pop('_token', None)

        # Get function signature
        sig = inspect.signature(func)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        arguments = bound_args.arguments

        # Extract region and workspace
        region = arguments.get('region', '')
        workspace = arguments.get('workspace')

        # Validate workspace is present
        if not workspace:
            return _fail(error_response('workspace parameter is required'))

        # Validate workspace format
        if not validate_workspace_format(workspace):
            return _fail(format_validation_error('workspace', workspace))

        auth_enabled = _is_auth_enabled()

        # Retrieve JWT token once upfront in streamable-http mode
        jwt_token = None
        if auth_enabled:
            jwt_token = _get_jwt_token()
            if not jwt_token:
                return _fail(
                    error_response(
                        'Authentication required. No JWT token found in request context.'
                    ),
                )

        # Auto-detect region if not provided
        if not region:
            if auth_enabled:
                # jwt_token was narrowed to str above; mypy can't carry it here.
                resolved_region, err_msg = _resolve_region_jwt(
                    cast(str, jwt_token), workspace
                )
            else:
                resolved_region, err_msg = _resolve_region_local(workspace)

            if err_msg:
                return _fail(error_response(err_msg))
            region = resolved_region
            bound_args.arguments['region'] = region

        # Validate region format
        if not validate_region_format(region):
            return _fail(format_validation_error('region', region))

        # Validate server_id format if present
        server_id = arguments.get('server_id')
        if server_id is not None and not validate_server_id_format(server_id):
            return _fail(format_validation_error('server_id', server_id))

        # Validate server_ids list if present
        server_ids = arguments.get('server_ids')
        if server_ids is not None:
            if not isinstance(server_ids, list):
                return _fail(
                    format_validation_error(
                        'server_ids',
                        server_ids,
                        'Must be a list of server UUIDs.',
                    ),
                )
            invalid_ids = [
                sid for sid in server_ids if not validate_server_id_format(sid)
            ]
            if invalid_ids:
                return _fail(
                    format_validation_error(
                        'server_ids',
                        invalid_ids,
                        'Each server ID must be in UUID format. (e.g., 550e8400-e29b-41d4-a716-446655440000)',
                    ),
                )

        # Validate servers list if present (server UUIDs sent in request bodies)
        servers = arguments.get('servers')
        if servers is not None:
            if not isinstance(servers, list):
                return _fail(
                    format_validation_error(
                        'servers',
                        servers,
                        'Must be a list of server UUIDs.',
                    ),
                )
            invalid_servers = [
                sid for sid in servers if not validate_server_id_format(sid)
            ]
            if invalid_servers:
                return _fail(
                    format_validation_error(
                        'servers',
                        invalid_servers,
                        'Each server ID must be in UUID format. (e.g., 550e8400-e29b-41d4-a716-446655440000)',
                    ),
                )

        # session_id is interpolated into URL paths, so reject non-UUID values that could retarget the request.
        session_id = arguments.get('session_id')
        if session_id is not None and not validate_server_id_format(session_id):
            return _fail(format_validation_error('session_id', session_id))

        # Get the **kwargs dict from bound arguments to inject token
        extra_kwargs = bound_args.arguments.get('kwargs', {})

        if auth_enabled:
            # Streamable-HTTP mode — JWT auth only
            if not _validate_jwt_workspace(cast(str, jwt_token), region, workspace):
                return _fail(
                    error_response(
                        f'Workspace {workspace}.{region} not authorized by JWT',
                        region=region,
                        workspace=workspace,
                    ),
                )
            extra_kwargs['token'] = jwt_token

            # MFA pre-check: verify MFA completion for actions that require it.
            # Raises UpstreamAuthError if MFA is required but not satisfied.
            # The ASGI middleware catches this and returns HTTP 401.
            await _check_mfa_requirement(func.__name__, cast(str, jwt_token), workspace)
        else:
            # stdio mode — token.json only
            token = validate_token(region, workspace)
            if not token:
                return _fail(token_error_response(region, workspace))
            extra_kwargs['token'] = token

        bound_args.arguments['kwargs'] = extra_kwargs

        # Call the original function using bound_args to handle
        # both positional and keyword region correctly
        return await func(*bound_args.args, **bound_args.kwargs)

    # Strip internal params from the exposed signature: _token is an
    # internal marker (MCP forbids leading underscores) and VAR_KEYWORD
    # would otherwise surface as a bogus required "kwargs" field in the
    # FastMCP-generated JSON schema (func_metadata ignores param.kind).
    original_sig = inspect.signature(func)
    new_params = [
        p
        for p in original_sig.parameters.values()
        if p.name != '_token' and p.kind is not inspect.Parameter.VAR_KEYWORD
    ]
    wrapper.__signature__ = original_sig.replace(parameters=new_params)  # type: ignore[attr-defined]

    return wrapper


def with_error_handling[R, **P](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Decorator to add consistent error handling to MCP tools.

    This decorator:
    1. Wraps the function in try-except
    2. Logs errors with context
    3. Returns standardized error responses
    4. Enriches error responses with recovery hints for LLM self-recovery

    Args:
        func: The async function to decorate

    Returns:
        Decorated async function
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        from utils.recovery_hints import enrich_error_response

        # Extract function name for logging
        func_name = func.__name__

        try:
            # Call the original function
            result = await func(*args, **kwargs)

            # result is statically the generic R, so the enrich call and
            # its result both need boundary casts.
            if isinstance(result, dict):
                enriched = enrich_error_response(
                    cast(ToolResponse, result), tool_name=func_name
                )
                result = cast(R, enriched)

            return result

        except UpstreamAuthError:
            # Let upstream auth errors propagate to the ASGI middleware
            # which converts them to HTTP 401 for MCP client re-auth.
            raise

        except Exception as e:
            # Get workspace and region for context
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            arguments = bound_args.arguments

            workspace = arguments.get('workspace', 'unknown')
            region = arguments.get('region', 'unknown')

            # Log the error with context
            logger.error(
                f'{func_name} failed for {workspace}.{region}: {e}', exc_info=True
            )

            # Return standardized error response with recovery hints
            resp = error_response(
                f'Failed in {func_name}: {str(e)}', workspace=workspace, region=region
            )
            # resp is ErrorResponse; the decorator's static return is the generic R.
            return cast(R, enrich_error_response(resp, tool_name=func_name))

    return wrapper


def with_logging[R, **P](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Decorator to add automatic logging to MCP tools.

    This decorator:
    1. Logs function entry with parameters
    2. Logs successful completion
    3. Logs errors (works with with_error_handling)

    Args:
        func: The async function to decorate

    Returns:
        Decorated async function
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        func_name = func.__name__

        # Get function arguments for logging
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        arguments = bound_args.arguments

        # Create log-safe arguments (exclude sensitive data)
        log_args = {
            k: v
            for k, v in arguments.items()
            if k not in ['_token', 'password', 'secret', 'key']
        }

        # Log function entry
        logger.info(f'{func_name} called with: {log_args}')

        # Call the original function
        result = await func(*args, **kwargs)

        # Log completion if successful
        if isinstance(result, dict) and result.get('status') == 'success':
            logger.info(f'{func_name} completed successfully')

        return result

    return wrapper


def require_jwt_auth[R, **P](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Reject non-JWT (API) tokens before any upstream call.

    Stack INSIDE ``@mcp_tool_handler`` so the resolved token is already
    in the wrapped function's ``**kwargs`` when this guard runs. Used on
    tools whose endpoint ``APITokenObjectPermission`` would 403 for
    ``source='api'`` requests — short-circuiting here skips the wasted
    round-trip and returns a clearer error.

    Usage::

        @mcp_tool_handler(description='...')
        @require_jwt_auth
        async def create_api_token(...): ...
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        token = kwargs.get('token')
        if token and not AlpaconHTTPClient._is_jwt(cast(str, token)):
            return cast(
                R,
                error_response(
                    f'{func.__name__} requires JWT (OAuth/SSO) authentication; '
                    'API tokens cannot manage other API tokens. '
                    'Re-authenticate via browser-based SSO and retry.'
                ),
            )
        return await func(*args, **kwargs)

    return wrapper


def mcp_tool_handler(
    description: str,
    annotations: ToolAnnotations | None = None,
    meta: ToolMeta = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Combined decorator for MCP tools that adds all common functionality.

    This decorator combines:
    1. MCP tool registration (with optional annotations and meta)
    2. Token validation (JWT for streamable-http, token.json for stdio)
    3. Error handling
    4. Logging

    Args:
        description: Tool description for MCP
        annotations: MCP ToolAnnotations (readOnlyHint, destructiveHint, etc.)
        meta: MCP meta dict (anthropic/alwaysLoad, anthropic/searchHint, etc.)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        # Apply decorators in order (innermost first)
        func = with_error_handling(func)
        func = with_token_validation(func)
        func = with_logging(func)

        # Register with MCP
        from server import mcp

        registered = mcp.tool(
            description=description,
            annotations=annotations,
            meta=meta,
        )(func)
        # mcp.tool() is typed with bare Callables upstream, dropping P/R even
        # though it returns the same object unchanged at runtime.
        return cast(Callable[P, Awaitable[R]], registered)

    return decorator
