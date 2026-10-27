"""Bounded cursor-page walk for alpacon-server's cursor-paginated lists, whose ES-backed
endpoints ignore page; the outcome is reported under pagination."""

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
    """One upstream page; unpaginated marks a body with no next, read as the whole
    list."""

    records: list[JsonValue]
    total: JsonValue  # the server's `count` (tuple.count owns that name)
    next_cursor: str | None
    unpaginated: bool = False


def _read_page(
    result: JsonValue, sent_cursor: str | None, *, opt_in: bool, first: bool
) -> _Page:
    """A page's records, count and next cursor; raises UnexpectedResponseShapeError for
    a body the schema disallows."""
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
    """The walk's report minus per-outcome fields; complete means the response holds the
    whole list, so a resumed walk never is unless the server ignored pagination."""
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
    """Walk a cursor list in up to MAX_CURSOR_PAGES requests; a failure discards the
    records read. opt_in_pagination: the endpoint pages only if cursor is named."""
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
