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


class TestListSessionAnalyses:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'results': []}

        result = await list_session_analyses(workspace='test-ws', region='ap1')

        assert result['status'] == 'success'


class TestGetSessionAnalysisDetail:
    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {'id': 'analysis-1'}

        result = await get_session_analysis_detail(
            analysis_id='analysis-1', workspace='test-ws', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['analysis_id'] == 'analysis-1'


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
