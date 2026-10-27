"""Shared call-unwrap-respond pipeline for tool implementations."""

from utils.common import exclude_none, success_response, unwrap_http_result
from utils.types import ApiMethod, QueryParams, RequestBody, ToolResponse


async def http_call_response(
    method: ApiMethod,
    *,
    region: str,
    workspace: str,
    endpoint: str,
    token: str | None,
    default_message: str,
    data: RequestBody | None = None,
    params: QueryParams | None = None,
    **id_context: object,
) -> ToolResponse:
    """Return the error envelope or a success response; id_context is merged into
    either. Pass method from the tool module so test patches intercept it."""
    call_kwargs: dict[str, object] = {
        'region': region,
        'workspace': workspace,
        'endpoint': endpoint,
        'token': token,
        **exclude_none(data=data, params=params),
    }

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
