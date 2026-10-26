"""Bounded cursor-page traversal for alpacon-server's cursor-paginated lists.

alpacon-server's Elasticsearch-backed lists use ``ESCursorPagination``, which
ignores ``page``: a caller stepping ``page=1,2,3`` gets the first page three
times. Those endpoints are walked by cursor here instead (#325), with the walk
bounded and its outcome reported under ``pagination``.

The work-session timeline pages only when a request names ``cursor``; unasked,
alpacon-server serves the whole session in one body, and a release that predates
the paginator does so whatever the request names. ``opt_in_pagination`` is how a
walk asks, and how it reads the answer of a server that cannot.
"""

from typing import NamedTuple

from utils.common import (
    UnexpectedResponseShapeError,
    error_response,
    expect_json_object,
    json_records,
    success_response,
    unwrap_http_result,
)
from utils.types import ApiMethod, JsonValue, QueryParams, ToolResponse

# Requests one walk may issue. A walk cut short hands back a cursor to resume.
MAX_CURSOR_PAGES = 10

# Why the walk stopped, reported as ``pagination.stopped_because``.
END_OF_LIST = 'end_of_list'
PAGE_BOUND = 'page_bound'
UPSTREAM_ERROR = 'upstream_error'
# The first answer was the whole list, not a page: reachable only under
# ``opt_in_pagination``, and only on the first request.
UNPAGINATED_SERVER = 'unpaginated_server'

# Shared by the three tool descriptions so they cannot drift apart.
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

# alpacon-server's codes for a cursor it will not read: retrying it fails again.
_REFUSED_CURSOR_CODES = frozenset({'api_cursor_expired', 'api_invalid_cursor'})

_PAGE_BOUND_NOTE = (
    'Stopped at the {max_pages}-request bound with more records still '
    'available, so this list is incomplete. Pass `pagination.next_cursor` back '
    'as `cursor` to continue.'
)

_UNPAGINATED_NOTE = (
    'The server answered with the whole list in one response carrying no '
    '`next`, which is the shape it serves a client that did not ask for a '
    'page. Nothing was cut: these are all the records there are.'
)

_UNPAGINATED_IGNORED_CURSOR_NOTE = (
    ' It ignored the `cursor` sent with the request too, so these records '
    'start at the beginning of the list rather than after that cursor.'
)

_RESUMED_END_NOTE = (
    'Read to the end of the list, but this call started from a supplied '
    '`cursor`, so `data.results` holds only the records after it. The whole '
    'list is these records together with those of the calls before it.'
)

_FIRST_REQUEST_FAILED = 'The walk failed on its first request.'

_RECORDS_DISCARDED = (
    'The walk failed after reading {records} record(s), which were discarded '
    'rather than returned as a partial list reported as a success.'
)

_RETRY_FROM_START_CURSOR = (
    ' Retry from `pagination.next_cursor`, where this walk started; null means '
    'from the start.'
)

_RETRY_FROM_THE_START = (
    ' The server refused the cursor (`error_code`), so `pagination.next_cursor` '
    'is null: retry from the start.'
)


class _Page(NamedTuple):
    """One upstream page: its records, the server's total, and where to resume.

    ``unpaginated`` marks a body with no ``next`` at all, read as the whole list.
    """

    records: list[JsonValue]
    total: JsonValue  # the server's `count` (tuple.count owns that name)
    next_cursor: str | None
    unpaginated: bool = False


def _read_page(
    result: JsonValue, sent_cursor: str | None, *, opt_in: bool, first: bool
) -> _Page:
    """Return a page's records, its ``count``, and its ``next`` cursor.

    Raises UnexpectedResponseShapeError for a body alpacon-server's schema does
    not allow, rather than reading it as an empty page or the end of the list.
    """
    whole_list_ok = opt_in and first
    if isinstance(result, list):
        if opt_in and not first:
            raise UnexpectedResponseShapeError(
                'Expected a cursor-paginated object after the first page, got a '
                'bare array'
            )
        return _Page(result, None, None, unpaginated=whole_list_ok)
    body = expect_json_object(result)
    if 'results' not in body:
        raise UnexpectedResponseShapeError(
            'Expected `results` in a cursor-paginated upstream page'
        )
    if 'next' not in body:
        if not whole_list_ok:
            raise UnexpectedResponseShapeError(
                'Expected `next` in a cursor-paginated upstream page'
            )
        return _Page(json_records(body), body.get('count'), None, unpaginated=True)
    records = json_records(body)
    token = body['next']
    if token is not None and not (isinstance(token, str) and token):
        raise UnexpectedResponseShapeError(
            f'Expected a cursor string or null in upstream `next`, got {token!r}'
        )
    if token is not None and token == sent_cursor:
        raise UnexpectedResponseShapeError(
            'Upstream `next` repeats the cursor this page was requested with'
        )
    return _Page(records, body.get('count'), token)


def _report(
    *,
    pages: int,
    stopped_because: str,
    started_from_cursor: bool,
    next_cursor: str | None,
) -> dict[str, object]:
    """Build the walk's own account of itself, minus the per-outcome fields.

    ``complete`` means this response holds the whole list, so a walk resumed
    from a cursor is never complete, even when it reaches the end. An
    unpaginated answer is the exception: it carries the list entire whatever
    cursor the request named, because the server ignored that too.
    """
    return {
        'pages_read': pages,
        'max_pages': MAX_CURSOR_PAGES,
        'complete': stopped_because == UNPAGINATED_SERVER
        or (stopped_because == END_OF_LIST and not started_from_cursor),
        'stopped_because': stopped_because,
        'started_from_cursor': started_from_cursor,
        'next_cursor': next_cursor,
    }


async def cursor_list_response(
    method: ApiMethod,
    *,
    region: str,
    workspace: str,
    endpoint: str,
    token: str | None,
    default_message: str,
    params: QueryParams,
    opt_in_pagination: bool = False,
    **id_context: object,
) -> ToolResponse:
    """Walk a cursor-paginated list, bounded by ``MAX_CURSOR_PAGES``, as one response.

    ``params`` is re-sent on every request with only ``cursor`` rewritten,
    since the server re-reads the filters and ``page_size`` each time. A
    ``cursor`` in ``params`` is where the walk starts.

    Under ``opt_in_pagination`` the first request names ``cursor``, empty when
    there is nothing to resume from, which is what makes an opt-in endpoint
    page. A first answer that still carries no ``next`` came from a server
    that does not page and is the whole list, reported ``stopped_because:
    unpaginated_server`` and ``complete: true``; a later answer without
    ``next`` is a shape error, since by then the server was paging.

    On success ``data`` carries the server's ``count`` and the merged
    ``results``; the envelope's ``next`` and ``previous`` are dropped, leaving
    ``pagination.next_cursor`` as the one resume point. On any failure, the
    records read so far are discarded and the error response carries the
    ``pagination`` report, whose ``next_cursor`` is the walk's own start.

    Args:
        method: Bound http_client method, passed from the tool module so tests
            patching that module's ``http_client`` keep intercepting the call.
        region: Region (ap1, us1)
        workspace: Workspace name
        endpoint: API endpoint path
        token: API token (injected by @mcp_tool_handler)
        default_message: Fallback message when the upstream response has none.
        params: Query parameters, including an optional starting ``cursor``.
        opt_in_pagination: The endpoint pages only when a request names
            ``cursor`` and serves the whole list otherwise. Off by default: for
            a list that always pages, a body with no ``next`` is a page of
            unknown extent and stays a shape error.
        **id_context: Extra identifiers merged into the response.

    Returns:
        Standardized success or error response, with a ``pagination`` report.
    """
    base_params = {
        name: value for name, value in params.items() if name != _CURSOR_PARAM
    }
    # The server reads an empty cursor as the first page, and so does the walk.
    sent = params.get(_CURSOR_PARAM)
    start_cursor = sent if isinstance(sent, str) and sent else None
    started_from_cursor = start_cursor is not None
    cursor = start_cursor
    records: list[JsonValue] = []
    count: JsonValue = None
    pages = 0
    unpaginated = False

    while pages < MAX_CURSOR_PAGES:
        page_params = dict(base_params)
        if cursor is not None:
            page_params[_CURSOR_PARAM] = cursor
        elif opt_in_pagination:
            # Naming the key, even empty, is the request to page.
            page_params[_CURSOR_PARAM] = ''

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
                page = _read_page(
                    result, cursor, opt_in=opt_in_pagination, first=pages == 0
                )
            except UnexpectedResponseShapeError as e:
                err = error_response(
                    str(e), region=region, workspace=workspace, **id_context
                )
        if err:
            refused = err.get('error_code') in _REFUSED_CURSOR_CODES
            report = _report(
                pages=pages,
                stopped_because=UPSTREAM_ERROR,
                started_from_cursor=started_from_cursor,
                next_cursor=None if refused else start_cursor,
            )
            report['records_discarded'] = len(records)
            report['note'] = (
                _RECORDS_DISCARDED.format(records=len(records))
                if pages
                else _FIRST_REQUEST_FAILED
            ) + (_RETRY_FROM_THE_START if refused else _RETRY_FROM_START_CURSOR)
            err['pagination'] = report
            return err

        pages += 1
        records.extend(page.records)
        if page.total is not None:
            count = page.total
        cursor = page.next_cursor
        unpaginated = page.unpaginated
        if cursor is None:
            break

    if unpaginated:
        stopped_because = UNPAGINATED_SERVER
    elif cursor is not None:
        stopped_because = PAGE_BOUND
    else:
        stopped_because = END_OF_LIST
    report = _report(
        pages=pages,
        stopped_because=stopped_because,
        started_from_cursor=started_from_cursor,
        next_cursor=cursor,
    )
    report['records_returned'] = len(records)
    if stopped_because == PAGE_BOUND:
        report['note'] = _PAGE_BOUND_NOTE.format(max_pages=MAX_CURSOR_PAGES)
    elif stopped_because == UNPAGINATED_SERVER:
        report['note'] = _UNPAGINATED_NOTE + (
            _UNPAGINATED_IGNORED_CURSOR_NOTE if started_from_cursor else ''
        )
    elif started_from_cursor:
        report['note'] = _RESUMED_END_NOTE

    return success_response(
        data={'count': count, 'results': records},
        region=region,
        workspace=workspace,
        pagination=report,
        **id_context,
    )
