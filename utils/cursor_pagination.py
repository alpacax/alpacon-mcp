"""Bounded cursor-page traversal for alpacon-server's cursor-paginated lists.

A handful of alpacon-server's list endpoints are Elasticsearch-backed and
paginate with ``history.pagination.ESCursorPagination``, which reads ``cursor``
and ``page_size`` from the query string and nothing else. ``page`` is not a
parameter it has, and an unrecognized query parameter is ignored rather than
refused, so a request carrying ``page=2`` is answered with the first page
again. A caller stepping ``page=1,2,3`` receives the same rows three times with
nothing in the response to say so—which is why those endpoints are walked here
instead (alpacax/alpacon-mcp#325).

Two properties the walk owes its caller:

* It is bounded. A tool result large enough to fill the model's context window
  is its own failure, so ``MAX_CURSOR_PAGES`` caps the requests one call makes.
* It reports what it did, under ``pagination`` on the response. Completeness
  that a reader has to infer from rows which are not there is the defect this
  module exists to prevent, so a truncated walk and a failed walk each say so.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from utils.common import json_records, success_response, unwrap_http_result

# Requests one walk may issue. ESCursorPagination defaults ``page_size`` to 15
# and caps it at 100, so a call reads 150 records by default and 1000 at most;
# the caller's own ``page_size`` is what moves it between the two. Nothing
# becomes unreachable at the bound—the walk hands back a cursor instead of
# reading further, so the rest costs another call.
MAX_CURSOR_PAGES = 10

# Why the walk stopped, reported as ``pagination.stopped_because``.
END_OF_LIST = 'end_of_list'
PAGE_BOUND = 'page_bound'
UPSTREAM_ERROR = 'upstream_error'

# One sentence for the three tool descriptions, so what the agent is told about
# the walk cannot drift between them.
CURSOR_WALK_DESCRIPTION = (
    'This endpoint is cursor-paginated, not page-numbered: the tool follows the '
    f'cursor for up to {MAX_CURSOR_PAGES} requests and merges the pages into one '
    'result. Check `pagination.complete` before concluding the list is whole, and '
    'pass `pagination.next_cursor` back as `cursor` to resume a walk that stopped '
    'at the bound.'
)

_CURSOR_PARAM = 'cursor'

_PAGE_BOUND_NOTE = (
    'Stopped at the {max_pages}-request bound with more records still '
    'available, so this list is incomplete. Pass `pagination.next_cursor` back '
    'as `cursor` to continue, or raise `page_size` (max 100) to cover more '
    'ground per request.'
)

_UPSTREAM_ERROR_NOTE = (
    'The walk failed partway through. The {records} record(s) read before the '
    'failure were discarded rather than handed back as a whole list, because a '
    'partial list reported as a success is the failure this walk exists to '
    'avoid. Retry from `pagination.next_cursor`, or from the start when '
    '`error_code` is `api_cursor_expired`.'
)


def _next_cursor(body: dict[str, Any]) -> str | None:
    """Return the body's ``next`` cursor, or None when there is no next page.

    Strict about the type on purpose: a page-number paginator also answers with
    ``next``, as an integer, and feeding that back as ``cursor`` would fail the
    cursor paginator's signature check. Only a non-empty string is a cursor.
    """
    token = body.get('next')
    return token if isinstance(token, str) and token else None


def _report(
    *, pages: int, max_pages: int, stopped_because: str, next_cursor: str | None
) -> dict[str, Any]:
    """Build the walk's own account of itself, minus the per-outcome record count."""
    return {
        'mode': 'cursor',
        'pages_read': pages,
        'max_pages': max_pages,
        'complete': stopped_because == END_OF_LIST,
        'stopped_because': stopped_because,
        'next_cursor': next_cursor,
    }


async def cursor_list_response(
    method: Callable[..., Awaitable[Any]],
    *,
    region: str,
    workspace: str,
    endpoint: str,
    token: str | None,
    default_message: str,
    params: dict[str, Any],
    max_pages: int = MAX_CURSOR_PAGES,
    **id_context: Any,
) -> dict[str, Any]:
    """Walk a cursor-paginated list to its end or to ``max_pages``, as one response.

    ``params`` is re-sent verbatim on every request with only ``cursor``
    rewritten, because the paginator rebuilds its query from the query string
    each time: it re-reads ``page_size`` per request, and it refuses a cursor
    whose recorded index set no longer matches the one the filters select. A
    ``cursor`` already in ``params`` is where the walk starts, which is how a
    caller resumes one the bound cut short.

    On success the merged page is a standard success response whose ``data``
    carries ``count`` (the server's total match count, which exceeds
    ``len(results)`` when the walk stopped early) and ``results``. The envelope's
    ``next`` and ``previous`` are deliberately not forwarded: every ``next`` but
    the last was already consumed, and leaving one on ``data`` invites a reader
    to treat a merged list as its own first page. ``pagination.next_cursor`` is
    the one place a resume point lives.

    Any failed request returns that request's error response instead, carrying
    the same ``pagination`` report. Records read before the failure are
    discarded rather than returned under ``status: "success"``.

    Args:
        method: Bound http_client method, passed from the tool module so tests
            patching that module's ``http_client`` keep intercepting the call.
        region: Region (ap1, us1)
        workspace: Workspace name
        endpoint: API endpoint path
        token: API token (injected by @mcp_tool_handler)
        default_message: Fallback message when the upstream response has none.
        params: Query parameters, including an optional starting ``cursor``.
        max_pages: Requests this walk may issue.
        **id_context: Extra identifiers merged into the response.

    Returns:
        Standardized success or error response, with a ``pagination`` report.
    """
    base_params = {
        name: value for name, value in params.items() if name != _CURSOR_PARAM
    }
    cursor = params.get(_CURSOR_PARAM)
    records: list[Any] = []
    count: Any = None
    pages = 0

    while pages < max_pages:
        # A fresh dict per request rather than one mutated in place: the same
        # object handed to every call would leave the caller holding a params
        # dict that changes under it after the call returns.
        page_params = dict(base_params)
        if cursor is not None:
            page_params[_CURSOR_PARAM] = cursor

        result = await method(
            region=region,
            workspace=workspace,
            endpoint=endpoint,
            token=token,
            params=page_params,
        )

        err = unwrap_http_result(
            result,
            default_message=default_message,
            region=region,
            workspace=workspace,
            **id_context,
        )
        if err:
            report = _report(
                pages=pages,
                max_pages=max_pages,
                stopped_because=UPSTREAM_ERROR,
                # The cursor this request carried: retrying it is where a
                # transient failure resumes, and None means from the start.
                next_cursor=cursor,
            )
            report['records_discarded'] = len(records)
            report['note'] = _UPSTREAM_ERROR_NOTE.format(records=len(records))
            err['pagination'] = report
            return err

        pages += 1
        records.extend(json_records(result))
        # A bare array is not a paginated body, so it carries nothing to follow.
        body = result if isinstance(result, dict) else {}
        count = body.get('count', count)
        cursor = _next_cursor(body)
        if cursor is None:
            break

    stopped_because = PAGE_BOUND if cursor is not None else END_OF_LIST
    report = _report(
        pages=pages,
        max_pages=max_pages,
        stopped_because=stopped_because,
        next_cursor=cursor,
    )
    report['records_returned'] = len(records)
    if stopped_because == PAGE_BOUND:
        report['note'] = _PAGE_BOUND_NOTE.format(max_pages=max_pages)

    return success_response(
        data={'count': count, 'results': records},
        region=region,
        workspace=workspace,
        pagination=report,
        **id_context,
    )
