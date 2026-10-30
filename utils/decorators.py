"""Decorators for MCP tools to reduce boilerplate code."""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Annotated, Protocol

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations
from pydantic import Field

from utils import request_signal, token_manager
from utils.auth import (
    WorkspaceClaim,
    decode_claims_unverified,
    get_token_workspaces,
    match_workspace,
)
from utils.common import (
    error_response,
    is_auth_enabled,
    token_error_response,
    validate_token,
)
from utils.error_handler import (
    Region,
    ServedRegion,
    UpstreamAuthError,
    format_validation_error,
    serves_dev_region,
    validate_region_format,
    validate_uuid_format,
    validate_workspace_format,
)
from utils.http_client import AlpaconHTTPClient
from utils.logger import describe_for_log, get_logger
from utils.recovery_hints import enrich_error_response
from utils.security_settings import (
    check_mfa_completed,
    get_action_for_tool,
    security_cache,
)
from utils.types import ToolErrorResponse, ToolResult
from utils.workspace_resolver import resolve_workspace

logger = get_logger('decorators')

_SPECIFY_REGION_HINT = 'Please specify a region parameter.'

# Marker left on every function with_error_handling wraps. functools.wraps copies
# __dict__ outward, so a registered tool can still be swept for it.
ERROR_HANDLING_MARKER = '_error_handled'

# The arguments the entry log writes as given. Every other argument is
# recorded by type and size alone (``<str len=42>``), so a parameter added
# later stays out of the log until someone reviews it into this set. What is
# left out on purpose: the command a call runs (``command``, ``commands``),
# where a credential typed inline cannot be told apart from the rest; filter
# text (``search``, ``search_query``, the ``*_filter`` names, ``tag``);
# credentials, payloads and free text; URLs, which carry their own
# credential; personal data; and env maps.
_LOGGED_VERBATIM_KEYS = frozenset(
    {
        # identifiers minted upstream
        'acl_id',
        'alert_id',
        'analysis_id',
        'api_token_id',
        'app_id',
        'authority_id',
        'ca_id',
        'certificate_id',
        'command_id',
        'csr_id',
        'entry_id',
        'event_id',
        'file_id',
        'group_id',
        'log_id',
        'membership_id',
        'mentioned_users',
        'note_id',
        'override_id',
        'request_id',
        'revoke_id',
        'rule_id',
        'run_after',
        'server_id',
        'server_ids',
        'service_token_id',
        'session_id',
        'subscription_id',
        'system_user_ids',
        'target_id',
        'token_id',
        'user_id',
        'webhook_id',
        'websh_session_id',
        'work_session_id',
        # names and the permission context a call ran under
        'channel',
        'display_name',
        'domain',
        'groupname',
        'name',
        'organization',
        'owner',
        'package_name',
        'reporter',
        'role',
        'server_name',
        'servers',
        'target',
        'user',
        'username',
        'users',
        # paths and files
        'file_name',
        'interpreter',
        'local_file_path',
        'local_file_paths',
        'path',
        'remote_directory',
        'remote_file_path',
        'remote_paths',
        # workspace-scoped configuration objects; no secrets, and useful
        # in the audit trail to see what policy a write actually asked for
        'agent_rollout_policy',
        # the authority a credential was granted
        'presets',
        'scopes',
        # the subject alternative names a CSR asks for, published in
        # the certificate itself
        'domain_list',
        'ip_list',
        # filters and enums
        'action',
        'action_type',
        'alert_type',
        'architecture',
        'country',
        'device',
        'event_type',
        'groups',
        'interface',
        'key_algorithm',
        'language',
        'metric_types',
        'operator',
        'ordering',
        'partition',
        'platform',
        'provider',
        'requester_type',
        'resource_type',
        'risk_score',
        'service_type',
        'severity',
        'shell',
        'state',
        'status',
        'timezone',
        'transfer_type',
        'version',
        # timestamps
        'end_date',
        'expires_at',
        'scheduled_at',
        'start_date',
        'valid_from',
        'valid_until',
        # the call target itself
        'region',
        'workspace',
    }
)

# Bounds on a verbatim argument. A payload reaches a tool as an ordinary
# string, under whatever name that tool gives it, so the guard is on the
# value's size and not only on the key (#233).
_MAX_LOGGED_VALUE_LEN = 256

# Containers carry identifier, path, and enum lists today, which is what the
# log is for, so a short one is summarized element by element rather than
# dropped.
_MAX_LOGGED_ITEMS = 10

# RFC 3986 unreserved characters—nothing in this set can restructure a URL.
# Wide enough in practice: every identifier upstream mints is a UUID or an
# opaque slug, and both sit well inside it.
_PATH_IDENTIFIER_RE = re.compile(r'[A-Za-z0-9._~-]+')

# Nothing above can hold a separator or an escape, so the value is always a
# single path segment and only the two dot-segments still retarget the request.
_DOT_SEGMENTS = frozenset({'.', '..'})

# Validated above as UUIDs, which is stricter than the path check.
_UUID_IDENTIFIERS = frozenset({'server_id', 'session_id'})

# Exempt because resolve_work_session_id strips the value's padding on
# purpose. Gating it would reject padding that resolution tolerates, while the
# same value through ALPACON_WORK_SESSION passed.
_EXEMPT_IDENTIFIERS = frozenset({'work_session_id'})

# Both names mean a page size and reach the API as page_size; no tool has both.
_PAGINATION_FIELDS = ('limit', 'page_size')


def _get_jwt_token() -> str | None:
    """The raw JWT from the SDK auth context; None in stdio/SSE mode."""
    access_token = get_access_token()
    return access_token.token if access_token is not None else None


def _validate_jwt_workspace(
    workspaces: list[WorkspaceClaim], region: str, workspace: str
) -> bool:
    return match_workspace(workspaces, region, workspace)


def _resolve_region_from_jwt(
    workspaces: list[WorkspaceClaim], workspace: str | None = None
) -> str | None:
    """The workspace's region, or the only region when no workspace is given; None if
    ambiguous."""
    if not workspaces:
        return None

    if workspace:
        matching = [
            ws.get('region') for ws in workspaces if ws.get('schema_name') == workspace
        ]
        if len(matching) == 1:
            return matching[0]
        return None

    regions = list({ws['region'] for ws in workspaces})
    if len(regions) == 1:
        return regions[0]
    return None


def _resolve_region_jwt(
    workspaces: list[WorkspaceClaim], workspace: str | None
) -> tuple[str | None, str | None]:
    """(region, error_message) from the JWT; exactly one is None."""
    region = _resolve_region_from_jwt(workspaces, workspace)
    if region:
        return region, None

    available_regions = sorted({ws['region'] for ws in workspaces})
    if available_regions:
        return None, (
            f'Multiple regions available in token: {", ".join(available_regions)}. '
            + _SPECIFY_REGION_HINT
        )
    return None, 'No regions found in JWT token.'


def _resolve_region_local(workspace: str | None) -> tuple[str | None, str | None]:
    """(region, error_message) from token.json; exactly one is None."""
    tm = token_manager.get_token_manager()

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
            + _SPECIFY_REGION_HINT
        )
    return None, 'No regions configured. Please run setup first.'


async def _check_mfa_requirement(
    tool_name: str, jwt_token: str, workspace: str
) -> None:
    """Signal and raise UpstreamAuthError when the tool's MFA action is required but not
    completed; any other failure is ignored (fail-open)."""
    action = get_action_for_tool(tool_name)
    if not action:
        return

    try:
        settings = await security_cache.get_settings(jwt_token, workspace)
        if not settings or not settings.is_action_mfa_required(action):
            return

        claims = decode_claims_unverified(jwt_token)
        if not claims:
            return

        if check_mfa_completed(claims, settings):
            return

        # MFA required but not completed
        request_signal.signal_upstream_auth_error(
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


def _validate_path_identifier(field: str, value: object) -> ToolErrorResponse | None:
    # A non-str never matches the pattern, but the f-string that builds the
    # endpoint stringifies it anyway, so its separators reach the path.
    # fullmatch, not match: '$' also matches before a trailing newline.
    if (
        not isinstance(value, str)
        or not _PATH_IDENTIFIER_RE.fullmatch(value)
        or value in _DOT_SEGMENTS
    ):
        return format_validation_error(
            field,
            value,
            'Must be a string of one or more letters, digits, ".", "_", '
            '"~" or "-", and must not be "." or "..". '
            'Identifiers accept only characters that cannot retarget '
            'the API request.',
        )
    return None


def _validate_page_size(field: str, value: object) -> ToolErrorResponse | None:
    # bool is an int subclass, so True would otherwise pass as a page size of 1.
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return format_validation_error(
            field,
            value,
            'A positive integer.',
        )
    return None


def _validate_uuid_list(field: str, value: object) -> ToolErrorResponse | None:
    if not isinstance(value, list):
        return format_validation_error(
            field,
            value,
            'Must be a list of server UUIDs.',
        )

    invalid = [item for item in value if not validate_uuid_format(item)]
    if invalid:
        return format_validation_error(
            field,
            invalid,
            'Each server ID must be in UUID format. '
            '(e.g., 550e8400-e29b-41d4-a716-446655440000)',
        )
    return None


REGION_DESCRIPTION = (
    "Region, ap1 or us1. Omit it to use the workspace's region: read from the JWT "
    'in remote mode and from token.json in local mode. The call fails when that '
    'region cannot be determined; pass region when several regions match.'
)

ALL_REGIONS_DESCRIPTION = 'Lists only the workspaces in this region, ap1 or us1. Omit it to list every region.'


WORKSPACE_DESCRIPTION = 'Workspace name, as list_workspaces returns it.'


def _published_workspace(param: inspect.Parameter) -> inspect.Parameter:
    """Attach the workspace rule to the published signature; the annotation stays str."""
    return param.replace(
        annotation=Annotated[str, Field(description=WORKSPACE_DESCRIPTION)]
    )


def _published_region(
    param: inspect.Parameter, requires_workspace: bool
) -> inspect.Parameter:
    """Advertise the served regions and what an omitted one means; it arrives as None."""
    description = REGION_DESCRIPTION if requires_workspace else ALL_REGIONS_DESCRIPTION
    accepted = Region.__value__ if serves_dev_region() else ServedRegion.__value__
    return param.replace(
        annotation=Annotated[accepted | None, Field(description=description)],
        default=None,
    )


def with_token_validation[**P, R](
    func: Callable[P, Awaitable[R]], requires_workspace: bool = True
) -> Callable[P, Awaitable[ToolResult[R]]]:
    """The single validation gate, run before the token lookup: workspace, region,
    server and session UUIDs, every _id-suffixed argument (not work_session_id, whose
    padding resolve_work_session_id strips) and limit/page_size. Only the _id suffix
    triggers, so another path parameter name or an _id inside **kwargs reaches the
    URL unchecked. func must declare **kwargs: the token is injected there, and the
    catch-all is dropped from the published signature, which also offers region as
    ap1, us1 or None. requires_workspace=False (list_workspaces only) is for a tool
    that answers before a workspace is known; it skips workspace checks, region
    resolution, JWT authorization, the MFA pre-check and stdio token injection, and
    reads an omitted region as all regions (a given one is still validated), so a tool
    reaching any workspace-scoped resource must not set it. ALPACON_MCP_AUTH_ENABLED=true
    uses the JWT and never token.json; otherwise token.json and never JWT."""
    original_sig = inspect.signature(func)
    catch_all = next(
        (
            p.name
            for p in original_sig.parameters.values()
            if p.kind is inspect.Parameter.VAR_KEYWORD
        ),
        None,
    )
    if catch_all is None:
        raise TypeError(
            f'{func.__name__} declares no **kwargs, so there is nowhere to inject '
            'the token'
        )

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult[R]:
        bound_args = original_sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        arguments = bound_args.arguments

        # Extract region and workspace
        region = arguments.get('region', '')
        workspace: str = arguments.get('workspace') or ''

        if requires_workspace:
            if not workspace:
                return error_response('workspace parameter is required')

            if not validate_workspace_format(workspace):
                return format_validation_error('workspace', workspace)

        auth_enabled = is_auth_enabled()

        # Retrieve JWT token once upfront in streamable-http mode
        jwt_token = ''
        jwt_workspaces: list[WorkspaceClaim] = []
        if auth_enabled:
            jwt_token = _get_jwt_token() or ''
            if not jwt_token:
                return error_response(
                    'Authentication required. No JWT token found in request context.'
                )
            # Decoded once: region resolution and authorization both read it.
            if requires_workspace:
                jwt_workspaces = get_token_workspaces(jwt_token)

        if auth_enabled and requires_workspace:
            # A renamed URL slug is not in the claims; map it to its schema_name.
            resolved_workspace = await resolve_workspace(workspace, jwt_workspaces)
            if resolved_workspace != workspace:
                workspace = resolved_workspace
                bound_args.arguments['workspace'] = workspace

        if not region and requires_workspace:  # workspace-less: omitted means all
            if auth_enabled:
                resolved_region, err_msg = _resolve_region_jwt(
                    jwt_workspaces, workspace
                )
            else:
                resolved_region, err_msg = _resolve_region_local(workspace)

            if err_msg:
                return error_response(err_msg)
            region = resolved_region
            bound_args.arguments['region'] = region

        # Validate region format
        if region and not validate_region_format(region):
            return format_validation_error('region', region)

        # Validate server_id format if present
        server_id = arguments.get('server_id')
        if server_id is not None and not validate_uuid_format(server_id):
            return format_validation_error('server_id', server_id)

        # 'servers' carries server UUIDs sent in request bodies.
        # Tuple order is the reporting order when both are invalid.
        for field in ('server_ids', 'servers'):
            value = arguments.get(field)
            if value is not None:
                validation_error = _validate_uuid_list(field, value)
                if validation_error:
                    return validation_error

        # session_id is interpolated into URL paths, so reject non-UUID values that could retarget the request.
        session_id = arguments.get('session_id')
        if session_id is not None and not validate_uuid_format(session_id):
            return format_validation_error('session_id', session_id)

        # Every other *_id may be interpolated into an endpoint path. Their
        # upstream format is not always a UUID, so reject only what escapes the
        # path segment rather than requiring one.
        for field, value in arguments.items():
            if (
                field in _UUID_IDENTIFIERS
                or field in _EXEMPT_IDENTIFIERS
                or not field.endswith('_id')
            ):
                continue
            # None is an omitted optional argument, not a bad type.
            if value is None:
                continue
            path_error = _validate_path_identifier(field, value)
            if path_error:
                return path_error

        for field in _PAGINATION_FIELDS:
            value = arguments.get(field)
            if value is None:
                continue
            page_size_error = _validate_page_size(field, value)
            if page_size_error:
                return page_size_error

        extra_kwargs = bound_args.arguments.get(catch_all, {})

        if auth_enabled:
            # Streamable-HTTP mode — JWT auth only
            if requires_workspace:
                if not _validate_jwt_workspace(jwt_workspaces, region, workspace):
                    return error_response(
                        f'Workspace {workspace}.{region} not authorized by JWT',
                        region=region,
                        workspace=workspace,
                    )

                # Signals request_signal and raises when MFA is required but
                # not done; the ASGI middleware reads the signal for HTTP 401.
                await _check_mfa_requirement(func.__name__, jwt_token, workspace)

            extra_kwargs['token'] = jwt_token
        elif requires_workspace:
            # stdio mode — token.json only
            token = validate_token(region, workspace)
            if not token:
                return token_error_response(region, workspace)
            extra_kwargs['token'] = token

        bound_args.arguments[catch_all] = extra_kwargs

        # bound_args carries a positional or keyword region alike
        return await func(*bound_args.args, **bound_args.kwargs)

    # The SDK publishes a VAR_KEYWORD as a required field, not a catch-all.
    new_params = []
    for p in original_sig.parameters.values():
        if p.name == catch_all:
            continue
        if p.name == 'region':
            p = _published_region(p, requires_workspace)
        elif p.name == 'workspace' and requires_workspace:
            p = _published_workspace(p)
        new_params.append(p)
    wrapper.__signature__ = original_sig.replace(parameters=new_params)  # type: ignore[attr-defined]

    return wrapper


def with_error_handling[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[ToolResult[R]]]:
    """Turn an unhandled exception into an error response with recovery hints;
    UpstreamAuthError propagates. Marks the wrapper with ERROR_HANDLING_MARKER."""

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult[R]:
        func_name = func.__name__

        try:
            result = await func(*args, **kwargs)

            if isinstance(result, dict):
                return enrich_error_response(result, tool_name=func_name)

            return result

        except UpstreamAuthError:
            # Only ends the tool call: SDK 2.x keeps handler exceptions off the
            # ASGI boundary, and request_signal carries the re-auth signal there.
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
            logger.exception('%s failed for %s.%s: %s', func_name, workspace, region, e)

            # Return standardized error response with recovery hints
            resp = error_response(
                f'Failed in {func_name}: {str(e)}', workspace=workspace, region=region
            )
            return enrich_error_response(resp, tool_name=func_name)

    setattr(wrapper, ERROR_HANDLING_MARKER, True)
    return wrapper


def _summarize_log_value(value: object, _nested: bool = False) -> object:
    """Bound a verbatim log value: an over-long string or container becomes a
    placeholder like <str len=N>; short containers are summarized one level down."""
    if isinstance(value, str) and len(value) > _MAX_LOGGED_VALUE_LEN:
        return describe_for_log(value)
    if isinstance(value, (list, tuple, dict)):
        if _nested or len(value) > _MAX_LOGGED_ITEMS:
            return describe_for_log(value)
        if isinstance(value, dict):
            return {
                _summarize_log_value(k, _nested=True): _summarize_log_value(
                    v, _nested=True
                )
                for k, v in value.items()
            }
        return [_summarize_log_value(item, _nested=True) for item in value]
    return value


def _log_arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    """The entry log's view of a call: every key, a value only if in
    _LOGGED_VERBATIM_KEYS."""
    return {
        key: (
            _summarize_log_value(value)
            if key in _LOGGED_VERBATIM_KEYS
            else describe_for_log(value)
        )
        for key, value in arguments.items()
    }


def with_logging[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Log entry (arguments per _LOGGED_VERBATIM_KEYS, others by type and size) and
    completion on a success status."""
    # with_token_validation has already published the catch-all-free signature
    # this binds against, and nothing assigns __signature__ afterwards, so the
    # object is fixed for the life of the process.
    sig = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        func_name = func.__name__

        # Guarded, not merely lazy: %s defers the formatting but not the bind
        # and the summary, which run before the record exists.
        if logger.isEnabledFor(logging.INFO):
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            logger.info(
                '%s called with: %s', func_name, _log_arguments(bound_args.arguments)
            )

        result = await func(*args, **kwargs)

        if isinstance(result, dict) and result.get('status') == 'success':
            logger.info('%s completed successfully', func_name)

        return result

    return wrapper


def require_jwt_auth[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[ToolResult[R]]]:
    """Reject a static API token before any upstream call; stack inside
    @mcp_tool_handler so the token is in kwargs."""

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult[R]:
        token = kwargs.get('token')
        if token not in (None, '') and not (
            isinstance(token, str) and AlpaconHTTPClient._is_jwt(token)
        ):
            return error_response(
                f'{func.__name__} requires JWT (OAuth/SSO) authentication and '
                'cannot be performed with a static API token. '
                'Re-authenticate via browser-based SSO and retry.'
            )
        return await func(*args, **kwargs)

    return wrapper


class _ToolDecorator(Protocol):
    def __call__[**P, R](
        self, func: Callable[P, Awaitable[R]], /
    ) -> Callable[P, Awaitable[ToolResult[R]]]: ...


def mcp_tool_handler(
    description: str,
    annotations: ToolAnnotations | None = None,
    meta: dict[str, object] | None = None,
    requires_workspace: bool = True,
) -> _ToolDecorator:
    """Register a tool wrapped in error handling, validation and token injection, then
    logging."""

    def decorator[**P, R](
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[ToolResult[R]]]:
        handled = with_error_handling(func)
        validated = with_token_validation(
            handled, requires_workspace=requires_workspace
        )
        logged = with_logging(validated)

        # Deliberately local: server.py builds the MCP server at module
        # level from ALPACON_MCP_AUTH_ENABLED, which main_http.py sets just
        # before importing it. Hoisting this would decide the auth mode
        # whenever anything first reaches this module.
        from server import mcp

        return mcp.tool(
            description=description,
            annotations=annotations,
            meta=meta,
        )(logged)

    return decorator
