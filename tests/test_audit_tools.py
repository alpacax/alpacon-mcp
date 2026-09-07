"""Unit tests for audit and logging tools."""

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


class TestListActivityLogs:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': [], 'count': 0}

        result = await list_activity_logs(workspace='test-ws', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/audit/activity/',
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


class TestListServerLogs:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_server_logs(workspace='test-ws', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/history/logs/',
            token='test-token',
            params={},
        )


class TestListWebftpLogs:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_webftp_logs(workspace='test-ws', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/history/webftp-logs/',
            token='test-token',
            params={},
        )


class TestListSessionAnalyses:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_session_analyses(workspace='test-ws', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-ws',
            endpoint='/api/history/session-analyses/',
            token='test-token',
            params={},
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


@pytest.mark.parametrize(
    'func, endpoint',
    [
        (list_server_logs, '/api/history/logs/'),
        (list_webftp_logs, '/api/history/webftp-logs/'),
        (list_session_analyses, '/api/history/session-analyses/'),
    ],
    ids=['list_server_logs', 'list_webftp_logs', 'list_session_analyses'],
)
@pytest.mark.asyncio
async def test_server_id_is_sent_as_server(
    func, endpoint, mock_http_client, mock_token_manager
):
    mock_http_client.get.return_value = {'results': []}

    result = await func(workspace='test-ws', region='ap1', server_id=SERVER_ID)

    assert result['status'] == 'success'
    mock_http_client.get.assert_called_once_with(
        region='ap1',
        workspace='test-ws',
        endpoint=endpoint,
        token='test-token',
        params={'server': SERVER_ID},
    )


# All audit endpoints are GET reads; one parametrized case covers every tool's
# error-envelope path instead of repeating an identical test per class.
@pytest.mark.parametrize(
    'func, kwargs',
    [
        (list_activity_logs, {}),
        (get_activity_log, {'log_id': 'log-1'}),
        (list_server_logs, {}),
        (list_webftp_logs, {}),
        (list_session_analyses, {}),
        (get_session_analysis_detail, {'analysis_id': 'analysis-1'}),
    ],
    ids=[
        'list_activity_logs',
        'get_activity_log',
        'list_server_logs',
        'list_webftp_logs',
        'list_session_analyses',
        'get_session_analysis_detail',
    ],
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
        mock_http_client.get.return_value = {'results': []}

        result = await list_session_analyses(
            workspace='test-ws', region='ap1', status='', risk_score=''
        )

        assert result['status'] == 'success'
        assert mock_http_client.get.call_args.kwargs['params'] == {
            'status': '',
            'risk_score': '',
        }
