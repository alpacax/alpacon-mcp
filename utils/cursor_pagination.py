"""Bounded cursor-page traversal for alpacon-server's cursor-paginated lists.

alpacon-server's Elasticsearch-backed lists use ``ESCursorPagination``, which
ignores ``page``: a caller stepping ``page=1,2,3`` gets the first page three
times. Those endpoints are walked by cursor here instead (#325), with the walk
bounded and its outcome reported under ``pagination``.

The work-session timeline is cursor-paginated too, by a paginator of its own
rather than by Elasticsearch, and only when a request names ``cursor`` or
``page_size``; named by neither, it renders the whole session in one response.
``work_session_timeline`` always names ``page_size`` so that it is this walk,
and not the session's length, that bounds what comes back.
"""

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

from utils.common import (
    UnexpectedResponseShapeError,
    error_response,
    expect_json_object,
    json_records,
    success_response,
    unwrap_http_result,
)

# Requests one walk may issue: 150 records at an ES list's default page size of
# 15, 1000 at its cap of 100, 5000 at the work-session timeline's cap of 500. A
# walk cut short hands back a cursor to resume.
MAX_CURSOR_PAGES = 10

# The ceiling a walk names when it tells a caller to raise `page_size`. It is
# per endpoint, not repo-wide: the ES-backed lists stop at 100, the work-session
# timeline paginates its own way and stops at 500.
DEFAULT_MAX_PAGE_SIZE = 100

# Why the walk stopped, reported as ``pagination.stopped_because``.
END_OF_LIST = 'end_of_list'
PAGE_BOUND = 'page_bound'
UPSTREAM_ERROR = 'upstream_error'
# The server served the whole list rather than a page, so there was never a
# second request to make. Only a caller that passed ``unpaginated_is_whole_list``
# can see this; for everyone else a page with no ``next`` is a shape error.
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
    'as `cursor` to continue, or raise `page_size` (max {max_page_size}) to '
    'cover more ground per request.'
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

    ``unpaginated`` marks the body that carried no ``next`` at all, which only
    an endpoint whose pagination is opt-in can send and only a caller that
    allowed it can receive.
    """

    records: list[Any]
    count: Any
    next_cursor: str | None
    unpaginated: bool = False


def _read_page(
    result: Any, sent_cursor: str | None, unpaginated_is_whole_list: bool
) -> _Page:
    """Return a page's records, its ``count``, and its ``next`` cursor.

    A bare array is one final page. An object must carry ``results`` and a
    ``next`` that is null or a new non-empty string, as alpacon-server's schema
    requires; anything else raises UnexpectedResponseShapeError instead of
    being read as an empty page or the end of the list.

    ``unpaginated_is_whole_list`` relaxes the ``next`` requirement alone, for
    the one endpoint that paginates only when asked and serves the whole list
    otherwise. Everywhere else a missing ``next`` is a page of unknown extent,
    and reading it as the end would be the false completeness claim this walk
    exists to prevent.
    """
    if isinstance(result, list):
        return _Page(result, None, None)
    body = expect_json_object(result)
    if 'results' not in body:
        raise UnexpectedResponseShapeError(
            'Expected `results` in a cursor-paginated upstream page'
        )
    if 'next' not in body:
        if not unpaginated_is_whole_list:
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
) -> dict[str, Any]:
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
    method: Callable[..., Awaitable[Any]],
    *,
    region: str,
    workspace: str,
    endpoint: str,
    token: str | None,
    default_message: str,
    params: dict[str, Any],
    max_page_size: int = DEFAULT_MAX_PAGE_SIZE,
    unpaginated_is_whole_list: bool = False,
    **id_context: Any,
) -> dict[str, Any]:
    """Walk a cursor-paginated list, bounded by ``MAX_CURSOR_PAGES``, as one response.

    ``params`` is re-sent on every request with only ``cursor`` rewritten,
    since the server re-reads the filters and ``page_size`` each time. A
    ``cursor`` in ``params`` is where the walk starts.

    A server that answers the whole list in one body is reported
    ``stopped_because: unpaginated_server`` and ``complete: true``, which is
    the accurate reading: nothing was cut, so nothing is owed a resume.

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
        max_page_size: This endpoint's ``page_size`` ceiling, which the bound's
            note tells a caller it may raise ``page_size`` to.
        unpaginated_is_whole_list: Read a body with no ``next`` as the whole
            list rather than a shape error. Pass it only for an endpoint whose
            pagination is opt-in, where a server that has not yet learned the
            page parameters answers with everything; it is off by default
            because for a list that is always paginated the same body is a
            page of unknown extent.
        **id_context: Extra identifiers merged into the response.

    Returns:
        Standardized success or error response, with a ``pagination`` report.
    """
    base_params = {
        name: value for name, value in params.items() if name != _CURSOR_PARAM
    }
    # The server reads an empty cursor as the first page, and so does the walk.
    start_cursor = params.get(_CURSOR_PARAM) or None
    started_from_cursor = start_cursor is not None
    cursor = start_cursor
    records: list[Any] = []
    count: Any = None
    pages = 0
    unpaginated = False

    while pages < MAX_CURSOR_PAGES:
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
                page = _read_page(result, cursor, unpaginated_is_whole_list)
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
        if page.count is not None:
            count = page.count
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
        report['note'] = _PAGE_BOUND_NOTE.format(
            max_pages=MAX_CURSOR_PAGES, max_page_size=max_page_size
        )
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
