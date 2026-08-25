"""Shared call-unwrap-respond pipeline for MCP tool implementations.

Lives in its own module because utils.http_client imports utils.common;
placing this in either would create a circular import.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from utils.common import success_response, unwrap_http_result


async def http_call_response(
    method: Callable[..., Awaitable[Any]],
    *,
    region: str,
    workspace: str,
    endpoint: str,
    token: str | None,
    default_message: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    **id_context: Any,
) -> dict[str, Any]:
    """Call an http_client method and shape the result as a standard tool response.

    Collapses the idiom shared by every tool: run the request, return the
    ``unwrap_http_result`` error envelope if the call failed, otherwise wrap
    the payload with ``success_response``. ``id_context`` kwargs (e.g.
    ``server_id``) are merged into both the error and the success response,
    alongside ``region`` and ``workspace``.

    Args:
        method: Bound http_client method (``http_client.get``, ``.post``, ...).
            Passed from the tool module so tests patching that module's
            ``http_client`` name keep intercepting the call.
        region: Region (ap1, us1, eu1, etc.)
        workspace: Workspace name
        endpoint: API endpoint path
        token: API token (injected by @mcp_tool_handler)
        default_message: Fallback error message when the upstream response has none.
        data: Request body (post/put/patch only).
        params: Query parameters (get/post only).
        **id_context: Extra identifiers merged into the response.

    Returns:
        Standardized success or error response dict.
    """
    call_kwargs: dict[str, Any] = {
        'region': region,
        'workspace': workspace,
        'endpoint': endpoint,
        'token': token,
    }
    if data is not None:
        call_kwargs['data'] = data
    if params is not None:
        call_kwargs['params'] = params

    result = await method(**call_kwargs)

    err = unwrap_http_result(
        result,
        default_message=default_message,
        region=region,
        workspace=workspace,
        **id_context,
    )
    if err:
        return err

    return success_response(
        data=result, region=region, workspace=workspace, **id_context
    )
