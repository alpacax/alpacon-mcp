"""Unit tests for the bounded cursor-page walk."""

from unittest.mock import AsyncMock

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE
from utils import cursor_pagination
from utils.cursor_pagination import MAX_CURSOR_PAGES, cursor_list_response

ENDPOINT = '/api/audit/activity/'


def _page(records, next_cursor=None, count=None):
    """An ESCursorPagination response body."""
    return {
        'count': count if count is not None else len(records),
        'next': next_cursor,
        'previous': None,
        'results': records,
    }


async def _walk(bodies, *, params=None):
    """Run a walk over `bodies`, returning (response, the mock that served them)."""
    method = AsyncMock(side_effect=list(bodies))
    result = await cursor_list_response(
        method,
        region='ap1',
        workspace='test-ws',
        endpoint=ENDPOINT,
        token='test-token',
        default_message='Failed to list',
        params={} if params is None else params,
    )
    return result, method


@pytest.fixture
def max_pages(monkeypatch):
    """Lower the request bound for one test: `max_pages(n)`."""
    return lambda n: monkeypatch.setattr(cursor_pagination, 'MAX_CURSOR_PAGES', n)


def _sent_params(method):
    """The `params` dict of every request the walk issued, in order."""
    return [call.kwargs['params'] for call in method.await_args_list]


class TestCursorFollowing:
    @pytest.mark.asyncio
    async def test_follows_next_cursor_and_merges_every_page(self):
        result, method = await _walk(
            [
                _page([{'id': 'a'}], next_cursor='c1', count=3),
                _page([{'id': 'b'}], next_cursor='c2', count=3),
                _page([{'id': 'c'}], count=3),
            ]
        )

        assert result['status'] == 'success'
        assert [r['id'] for r in result['data']['results']] == ['a', 'b', 'c']
        assert _sent_params(method) == [{}, {'cursor': 'c1'}, {'cursor': 'c2'}]

    @pytest.mark.asyncio
    async def test_page_is_never_sent(self):
        """`page` is the parameter ESCursorPagination does not have (#325).

        Sending it is answered with the first page again, so a walk that used it
        would repeat page one and report the repetition as a complete list.
        """
        _, method = await _walk(
            [_page([{'id': 'a'}], next_cursor='c1'), _page([{'id': 'b'}])]
        )

        assert all('page' not in params for params in _sent_params(method))

    @pytest.mark.asyncio
    async def test_page_size_and_filters_are_resent_on_every_request(self):
        """The paginator rebuilds its query per request, so every param repeats.

        `page_size` is re-read from the query string each time, and a cursor is
        refused when the filters no longer select the index set it was minted
        against.
        """
        _, method = await _walk(
            [_page([{'id': 'a'}], next_cursor='c1'), _page([{'id': 'b'}])],
            params={'page_size': 100, 'server': 'srv-1'},
        )

        assert _sent_params(method) == [
            {'page_size': 100, 'server': 'srv-1'},
            {'page_size': 100, 'server': 'srv-1', 'cursor': 'c1'},
        ]

    @pytest.mark.asyncio
    async def test_a_supplied_cursor_starts_the_walk(self):
        _, method = await _walk([_page([{'id': 'z'}])], params={'cursor': 'resume-me'})

        assert _sent_params(method) == [{'cursor': 'resume-me'}]

    @pytest.mark.asyncio
    async def test_an_empty_cursor_is_a_walk_from_the_start(self):
        """The server reads `cursor=''` as the first page, so the walk does too."""
        result, method = await _walk([_page([{'id': 'a'}])], params={'cursor': ''})

        assert _sent_params(method) == [{}]
        assert result['pagination']['started_from_cursor'] is False
        assert result['pagination']['complete'] is True

    @pytest.mark.asyncio
    async def test_a_repeated_cursor_is_an_error_not_a_duplicate_page(self):
        result, method = await _walk(
            [
                _page([{'id': 'a'}], next_cursor='c1'),
                _page([{'id': 'a'}], next_cursor='c1'),
            ]
        )

        assert result['status'] == 'error'
        assert result['pagination']['stopped_because'] == 'upstream_error'
        assert method.await_count == 2

    @pytest.mark.asyncio
    async def test_an_integer_next_is_an_error_not_the_end_of_the_list(self):
        """A page-number body also carries `next`, as an int, which is not a cursor.

        Feeding one back would fail the cursor paginator's signature check, and
        stopping there would report `complete` while upstream says another page
        exists, so a walk mis-wired to a page-number endpoint fails instead.
        """
        result, method = await _walk(
            [{'count': 30, 'next': 2, 'results': [{'id': 'a'}]}]
        )

        assert result['status'] == 'error'
        assert result['pagination']['complete'] is False
        assert result['pagination']['stopped_because'] == 'upstream_error'
        assert _sent_params(method) == [{}]

    @pytest.mark.asyncio
    async def test_a_bare_array_body_is_a_single_page(self):
        result, method = await _walk([[{'id': 'a'}, {'id': 'b'}]])

        assert result['data']['results'] == [{'id': 'a'}, {'id': 'b'}]
        assert method.await_count == 1


class TestWalkReport:
    @pytest.mark.asyncio
    async def test_a_finished_walk_reports_end_of_list(self):
        result, _ = await _walk(
            [_page([{'id': 'a'}], next_cursor='c1', count=2), _page([{'id': 'b'}])]
        )

        assert result['pagination'] == {
            'pages_read': 2,
            'max_pages': MAX_CURSOR_PAGES,
            'complete': True,
            'stopped_because': 'end_of_list',
            'started_from_cursor': False,
            'next_cursor': None,
            'records_returned': 2,
        }
        assert 'note' not in result['pagination']

    @pytest.mark.asyncio
    async def test_a_resumed_walk_that_reaches_the_end_is_not_complete(self):
        """Its results omit every record before the cursor it was handed."""
        result, _ = await _walk(
            [_page([{'id': 'y'}], next_cursor='c9'), _page([{'id': 'z'}])],
            params={'cursor': 'resume-me'},
        )

        report = result['pagination']
        assert result['status'] == 'success'
        assert report['complete'] is False
        assert report['stopped_because'] == 'end_of_list'
        assert report['started_from_cursor'] is True
        assert report['next_cursor'] is None
        assert 'only the records after it' in report['note']

    @pytest.mark.asyncio
    async def test_the_page_bound_is_visible_in_the_payload(self, max_pages):
        """Truncation has to be stated, not left to be inferred from absence."""
        max_pages(2)
        result, method = await _walk(
            [
                _page([{'id': 'a'}], next_cursor='c1', count=99),
                _page([{'id': 'b'}], next_cursor='c2', count=99),
            ]
        )

        assert method.await_count == 2
        report = result['pagination']
        assert report['complete'] is False
        assert report['stopped_because'] == 'page_bound'
        assert report['next_cursor'] == 'c2'
        assert report['pages_read'] == 2
        assert report['records_returned'] == 2
        assert 'incomplete' in report['note']

    @pytest.mark.asyncio
    async def test_count_is_the_servers_total_not_the_merged_length(self, max_pages):
        max_pages(1)
        result, _ = await _walk([_page([{'id': 'a'}], next_cursor='c1', count=500)])

        assert result['data']['count'] == 500
        assert len(result['data']['results']) == 1

    @pytest.mark.asyncio
    async def test_data_carries_no_next_or_previous(self, max_pages):
        """Every `next` but the last was consumed; the resume point lives in one place."""
        max_pages(1)
        result, _ = await _walk([_page([{'id': 'a'}], next_cursor='c1')])

        assert set(result['data']) == {'count', 'results'}


class TestWalkFailure:
    @pytest.mark.asyncio
    async def test_a_failure_on_the_first_request_returns_the_error(self):
        result, _ = await _walk([HTTP_ERROR_ENVELOPE])

        assert result['status'] == 'error'
        assert result['pagination']['pages_read'] == 0
        assert result['pagination']['records_discarded'] == 0
        assert result['pagination']['next_cursor'] is None
        assert 'first request' in result['pagination']['note']
        assert 'discarded' not in result['pagination']['note']

    @pytest.mark.asyncio
    async def test_a_failure_midway_is_an_error_not_a_partial_success(self):
        """A partial list under `status: "success"` is the defect this walk avoids."""
        result, method = await _walk(
            [_page([{'id': 'a'}], next_cursor='c1'), HTTP_ERROR_ENVELOPE]
        )

        assert result['status'] == 'error'
        assert 'data' not in result
        report = result['pagination']
        assert report['complete'] is False
        assert report['stopped_because'] == 'upstream_error'
        assert report['pages_read'] == 1
        assert report['records_discarded'] == 1
        # Where the walk started, not the failed request's 'c1': page one was
        # discarded, so resuming at 'c1' would skip it.
        assert report['next_cursor'] is None
        assert _sent_params(method) == [{}, {'cursor': 'c1'}]

    @pytest.mark.asyncio
    async def test_a_resumed_walk_that_fails_hands_back_its_starting_cursor(self):
        result, _ = await _walk(
            [_page([{'id': 'a'}], next_cursor='c1'), HTTP_ERROR_ENVELOPE],
            params={'cursor': 'c0'},
        )

        assert result['pagination']['next_cursor'] == 'c0'

    @pytest.mark.parametrize(
        'malformed',
        [
            'unexpected',
            {'results': 'oops', 'next': None},
            {'count': 2, 'next': 'c2'},
            {'count': 2, 'results': [{'id': 'b'}]},
            {'results': [{'id': 'b'}], 'next': ''},
        ],
        ids=['scalar', 'non-list-results', 'no-results', 'no-next', 'empty-next'],
    )
    @pytest.mark.asyncio
    async def test_a_malformed_later_page_is_an_error_with_the_report(self, malformed):
        result, _ = await _walk(
            [_page([{'id': 'a'}], next_cursor='c1'), malformed],
            params={'cursor': 'c0'},
        )

        assert result['status'] == 'error'
        assert 'data' not in result
        report = result['pagination']
        assert report['stopped_because'] == 'upstream_error'
        assert report['pages_read'] == 1
        assert report['records_discarded'] == 1
        assert report['next_cursor'] == 'c0'


def _refused_cursor(code):
    """A 400 envelope carrying alpacon-server's cursor error code."""
    return {
        'error': 'HTTP Error',
        'status_code': 400,
        'message': 'Bad request',
        'error_code': code,
    }


@pytest.mark.parametrize('code', ['api_cursor_expired', 'api_invalid_cursor'])
@pytest.mark.asyncio
async def test_a_refused_cursor_is_not_handed_back(code):
    """Retrying a cursor the server refused only meets the same refusal."""
    result, _ = await _walk([_refused_cursor(code)], params={'cursor': 'stale'})

    assert result['error_code'] == code
    assert result['pagination']['next_cursor'] is None
    assert 'from the start' in result['pagination']['note']
