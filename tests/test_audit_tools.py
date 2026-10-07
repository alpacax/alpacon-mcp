"""Unit tests for audit and logging tools."""

import inspect

import pytest

from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture
from tools.audit_tools import (
    get_activity_log,
    get_session_analysis_detail,
    list_activity_logs,
    list_server_logs,
    list_session_analyses,
    list_webftp_logs,
)

mock_http_client = http_client_fixture('tools.audit_tools')

SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'


LIST_ENDPOINTS = {
    list_activity_logs: '/api/audit/activity/',
    list_server_logs: '/api/history/logs/',
    list_webftp_logs: '/api/history/webftp-logs/',
    list_session_analyses: '/api/history/session-analyses/',
}

# list_activity_logs takes no server_id, so it sits out the rename test below.
SERVER_FILTER_TOOLS = [list_server_logs, list_webftp_logs, list_session_analyses]


@pytest.mark.parametrize(
    'func, endpoint',
    LIST_ENDPOINTS.items(),
    ids=[f.__name__ for f in LIST_ENDPOINTS],
)
@pytest.mark.asyncio
async def test_list_sends_no_params_when_no_filter_given(
    func, endpoint, mock_http_client, mock_token_manager
):
    mock_http_client.get.return_value = {'next': None, 'results': []}

    result = await func(workspace='test-ws', region='ap1')

    assert result['status'] == 'success'
    mock_http_client.get.assert_called_once_with(
        region='ap1',
        workspace='test-ws',
        endpoint=endpoint,
        token='test-token',
        params={},
    )


class TestGetActivityLog:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'id': 'log-1'}

        result = await get_activity_log(
            log_id='log-1', workspace='test-ws', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['log_id'] == 'log-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/audit/activity/log-1/',
            token='test-token',
        )


class TestGetSessionAnalysisDetail:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'id': 'analysis-1'}

        result = await get_session_analysis_detail(
            analysis_id='analysis-1', workspace='test-ws', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['analysis_id'] == 'analysis-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/history/session-analyses/analysis-1/',
            token='test-token',
        )


@pytest.mark.parametrize(
    'func', SERVER_FILTER_TOOLS, ids=[f.__name__ for f in SERVER_FILTER_TOOLS]
)
@pytest.mark.asyncio
async def test_server_id_is_sent_as_server(func, mock_http_client, mock_token_manager):
    mock_http_client.get.return_value = {'next': None, 'results': []}

    result = await func(workspace='test-ws', region='ap1', server_id=SERVER_ID)

    assert result['status'] == 'success'
    mock_http_client.get.assert_called_once_with(
        region='ap1',
        workspace='test-ws',
        endpoint=LIST_ENDPOINTS[func],
        token='test-token',
        params={'server': SERVER_ID},
    )


# All audit endpoints are GET reads, so one case covers every error-envelope path.
ERROR_CASES = [
    (list_activity_logs, {}),
    (get_activity_log, {'log_id': 'log-1'}),
    (list_server_logs, {}),
    (list_webftp_logs, {}),
    (list_session_analyses, {}),
    (get_session_analysis_detail, {'analysis_id': 'analysis-1'}),
]


@pytest.mark.parametrize(
    'func, kwargs', ERROR_CASES, ids=[f.__name__ for f, _ in ERROR_CASES]
)
@pytest.mark.asyncio
async def test_http_error_returns_error(
    func, kwargs, mock_http_client, mock_token_manager
):
    mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

    result = await func(workspace='test-ws', region='ap1', **kwargs)

    assert result['status'] == 'error'


class TestListSessionAnalysesFilterRule:
    @pytest.mark.asyncio
    async def test_supplied_but_falsy_filters_are_forwarded(
        self, mock_http_client, mock_token_manager
    ):
        """A supplied filter reaches the server even when it is falsy.

        Dropping it here would silently widen the listing to every session
        instead of letting the server reject the value the caller passed.
        """
        mock_http_client.get.return_value = {'next': None, 'results': []}

        result = await list_session_analyses(
            workspace='test-ws', region='ap1', status='', risk_score=''
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/history/session-analyses/',
            token='test-token',
            params={'status': '', 'risk_score': ''},
        )


# /api/audit/activity/, /api/history/logs/ and /api/history/webftp-logs/ are
# paginated by alpacon-server's history.pagination.ESCursorPagination, which
# reads `cursor` and `page_size` and has no `page` at all (#325).
CURSOR_TOOLS = [list_activity_logs, list_server_logs, list_webftp_logs]


@pytest.mark.parametrize('func', CURSOR_TOOLS, ids=[f.__name__ for f in CURSOR_TOOLS])
def test_cursor_tool_offers_cursor_and_not_page(func):
    """A `page` argument here is a promise the endpoint does not keep.

    The server ignores an unknown query parameter, so a documented `page` would
    answer page two with page one and present the repeat as the whole list.
    """
    params = inspect.signature(func).parameters

    assert 'cursor' in params
    assert 'page' not in params


@pytest.mark.parametrize('func', CURSOR_TOOLS, ids=[f.__name__ for f in CURSOR_TOOLS])
@pytest.mark.asyncio
async def test_cursor_tool_follows_the_cursor(
    func, mock_http_client, mock_token_manager
):
    mock_http_client.get.side_effect = [
        {'count': 2, 'next': 'cursor-2', 'previous': None, 'results': [{'id': 'a'}]},
        {'count': 2, 'next': None, 'previous': None, 'results': [{'id': 'b'}]},
    ]

    result = await func(workspace='test-ws', region='ap1')

    assert result['status'] == 'success'
    assert result['data']['results'] == [{'id': 'a'}, {'id': 'b'}]
    assert result['pagination']['complete'] is True
    sent = [call.kwargs['params'] for call in mock_http_client.get.await_args_list]
    assert sent == [{}, {'cursor': 'cursor-2'}]


@pytest.mark.parametrize('func', CURSOR_TOOLS, ids=[f.__name__ for f in CURSOR_TOOLS])
@pytest.mark.asyncio
async def test_cursor_tool_resumes_from_a_supplied_cursor(
    func, mock_http_client, mock_token_manager
):
    mock_http_client.get.return_value = {'count': 1, 'next': None, 'results': []}

    result = await func(workspace='test-ws', region='ap1', cursor='resume-me')

    assert result['status'] == 'success'
    mock_http_client.get.assert_called_once_with(
        region='ap1',
        workspace='test-ws',
        endpoint=LIST_ENDPOINTS[func],
        token='test-token',
        params={'cursor': 'resume-me'},
    )


@pytest.mark.parametrize('func', CURSOR_TOOLS, ids=[f.__name__ for f in CURSOR_TOOLS])
@pytest.mark.asyncio
async def test_cursor_tool_refuses_a_page_with_no_next(
    func, mock_http_client, mock_token_manager
):
    """`work_session_timeline` reads such a body as the whole list; these do not.

    That tolerance is opt-in because its premise is the timeline's alone: that
    endpoint paginates only when asked, so an unpaginated answer is a complete
    one. ESCursorPagination always paginates, so here the same body is a page
    of unknown extent, and reading it as the end would report a prefix as the
    whole list. If this test starts passing a `success`, the opt-in has become
    the default.
    """
    mock_http_client.get.return_value = {'count': 2, 'results': [{'id': 'a'}]}

    result = await func(workspace='test-ws', region='ap1')

    assert result['status'] == 'error'
    assert 'next' in result['message']
    assert 'data' not in result


class TestListSessionAnalysesStaysPageNumbered:
    """/api/history/session-analyses/ is a plain model list on the default
    page-number paginator, so `page` is the parameter it does honor."""

    @pytest.mark.asyncio
    async def test_page_is_forwarded(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'count': 0, 'next': None, 'results': []}

        result = await list_session_analyses(workspace='test-ws', region='ap1', page=2)

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/history/session-analyses/',
            token='test-token',
            params={'page': 2},
        )
