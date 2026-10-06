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

from utils.common import (
    UnexpectedResponseShapeError,
    error_response,
    expect_json_object,
    json_records,
    success_response,
    unwrap_http_result,
)

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
    'at the bound. A resumed call holds only the records after its `cursor`, so it '
    'is never `complete` on its own; `stopped_because: end_of_list` says it read '
    'to the end.'
)

_CURSOR_PARAM = 'cursor'

_PAGE_BOUND_NOTE = (
    'Stopped at the {max_pages}-request bound with more records still '
    'available, so this list is incomplete. Pass `pagination.next_cursor` back '
    'as `cursor` to continue, or raise `page_size` (max 100) to cover more '
    'ground per request.'
)

_RESUMED_END_NOTE = (
    'Read to the end of the list, but this call started from a supplied '
    '`cursor`, so `data.results` holds only the records after it. The whole '
    'list is these records together with those of the calls before it.'
)

_UPSTREAM_ERROR_NOTE = (
    'The walk failed partway through. The {records} record(s) read before the '
    'failure were discarded rather than handed back as a whole list, because a '
    'partial list reported as a success is the failure this walk exists to '
    'avoid. `pagination.next_cursor` is where this walk started, so retrying it '
    'reads those records again; retry from the start instead when '
    '`error_code` is `api_cursor_expired`.'
)


def _read_page(result: Any) -> tuple[list[Any], Any, str | None]:
    """Return a page's records, its ``count``, and its ``next`` cursor.

    A bare array is one page with nothing to follow. An object must carry a
    ``results`` list and a ``next`` that is null or a non-empty string; anything
    else raises UnexpectedResponseShapeError rather than being read as the end
    of the list. A missing ``results`` would otherwise merge as an empty page,
    and an integer ``next``—what a page-number paginator answers with, and which
    the cursor paginator's signature check refuses—would end the walk as
    ``complete`` while upstream says another page exists.
    """
    if isinstance(result, list):
        return result, None, None
    body = expect_json_object(result)
    if 'results' not in body:
        raise UnexpectedResponseShapeError(
            'Expected `results` in a cursor-paginated upstream page'
        )
    records = json_records(body)
    token = body.get('next')
    if token is not None and not (isinstance(token, str) and token):
        raise UnexpectedResponseShapeError(
            f'Expected a cursor string or null in upstream `next`, got {token!r}'
        )
    return records, body.get('count'), token


def _report(
    *,
    pages: int,
    max_pages: int,
    stopped_because: str,
    started_from_cursor: bool,
    next_cursor: str | None,
) -> dict[str, Any]:
    """Build the walk's own account of itself, minus the per-outcome record count.

    ``complete`` means this response holds the whole list, not that the walk
    reached the end: a walk resumed from a cursor reaches the end without the
    records before that cursor.
    """
    return {
        'mode': 'cursor',
        'pages_read': pages,
        'max_pages': max_pages,
        'complete': stopped_because == END_OF_LIST and not started_from_cursor,
        'stopped_because': stopped_because,
        'started_from_cursor': started_from_cursor,
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

    Any failed request, or a page whose body ``_read_page`` refuses, returns
    an error response instead, carrying the same ``pagination`` report. Records
    read before the failure are discarded rather than returned under
    ``status: "success"``, so the report's ``next_cursor`` is the walk's own
    starting cursor: retrying it reads the discarded pages again.

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
    start_cursor = params.get(_CURSOR_PARAM)
    cursor = start_cursor
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
        if err is None:
            try:
                page_records, page_count, cursor_after = _read_page(result)
            except UnexpectedResponseShapeError as e:
                err = error_response(
                    str(e), region=region, workspace=workspace, **id_context
                )
        if err:
            report = _report(
                pages=pages,
                max_pages=max_pages,
                stopped_because=UPSTREAM_ERROR,
                started_from_cursor=start_cursor is not None,
                # Where this walk started, not the failed request's cursor: the
                # pages before it are discarded, so resuming there would skip
                # them. None means from the start.
                next_cursor=start_cursor,
            )
            report['records_discarded'] = len(records)
            report['note'] = _UPSTREAM_ERROR_NOTE.format(records=len(records))
            err['pagination'] = report
            return err

        pages += 1
        records.extend(page_records)
        if page_count is not None:
            count = page_count
        cursor = cursor_after
        if cursor is None:
            break

    stopped_because = PAGE_BOUND if cursor is not None else END_OF_LIST
    report = _report(
        pages=pages,
        max_pages=max_pages,
        stopped_because=stopped_because,
        started_from_cursor=start_cursor is not None,
        next_cursor=cursor,
    )
    report['records_returned'] = len(records)
    if stopped_because == PAGE_BOUND:
        report['note'] = _PAGE_BOUND_NOTE.format(max_pages=max_pages)
    elif start_cursor is not None:
        report['note'] = _RESUMED_END_NOTE

    return success_response(
        data={'count': count, 'results': records},
        region=region,
        workspace=workspace,
        pagination=report,
        **id_context,
    )
