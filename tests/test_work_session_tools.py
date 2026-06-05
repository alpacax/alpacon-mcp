"""Unit tests for work_session_tools module."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_http_client():
    with patch('tools.work_session_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestWorkSessionCreate:
    @pytest.mark.asyncio
    async def test_create_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_create

        mock_http_client.post.return_value = {
            'id': 'ws-uuid-1234',
            'status': 'pending',
            'auth_method': 'mcp_oauth',
        }

        result = await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=['550e8400-e29b-41d4-a716-446655440001'],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Fix nginx config',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'ws-uuid-1234'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            data={
                'requester_type': 'agent',
                'scopes': ['command'],
                'servers': ['550e8400-e29b-41d4-a716-446655440001'],
                'expires_at': '2026-05-19T13:00:00+00:00',
                'description': 'Fix nginx config',
            },
        )

    @pytest.mark.asyncio
    async def test_create_with_title_and_description(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_create

        mock_http_client.post.return_value = {'id': 'ws-uuid-5678', 'status': 'pending'}

        await work_session_create(
            workspace='testworkspace',
            scopes=['command', 'webftp'],
            servers=['550e8400-e29b-41d4-a716-446655440001'],
            expires_at='2026-05-19T13:00:00+00:00',
            title='Deploy session',
            description='Deploying config files',
            region='ap1',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['title'] == 'Deploy session'
        assert call_data['description'] == 'Deploying config files'
        assert call_data['requester_type'] == 'agent'
        assert 'auth_method' not in call_data

    @pytest.mark.asyncio
    async def test_create_omits_empty_title(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_create

        mock_http_client.post.return_value = {'id': 'ws-uuid-0000', 'status': 'pending'}

        await work_session_create(
            workspace='testworkspace',
            scopes=['command'],
            servers=['550e8400-e29b-41d4-a716-446655440001'],
            expires_at='2026-05-19T13:00:00+00:00',
            description='Routine maintenance',
            region='ap1',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert 'title' not in call_data
        assert call_data['description'] == 'Routine maintenance'


class TestWorkSessionClose:
    @pytest.mark.asyncio
    async def test_close_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_close

        mock_http_client.post.return_value = {
            'id': 'ws-uuid-1234',
            'status': 'completed',
        }

        result = await work_session_close(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/ws-uuid-1234/complete/',
            token='test-token',
            data={},
        )


class TestWorkSessionGet:
    @pytest.mark.asyncio
    async def test_get_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_get

        mock_http_client.get.return_value = {
            'id': 'ws-uuid-1234',
            'status': 'active',
            'auth_method': 'mcp_oauth',
        }

        result = await work_session_get(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'ws-uuid-1234'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/ws-uuid-1234/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_propagates_api_error(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_get

        mock_http_client.get.return_value = {
            'error': 'Not found',
            'message': 'Work Session not found',
            'status_code': 404,
        }

        result = await work_session_get(
            session_id='ws-nonexistent',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'Work Session not found' in result['message']


class TestWorkSessionList:
    @pytest.mark.asyncio
    async def test_list_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_list

        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'ws-1', 'status': 'active'},
                {'id': 'ws-2', 'status': 'completed'},
            ],
        }

        result = await work_session_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/',
            token='test-token',
            params={'page_size': 20},
        )

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_list

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        await work_session_list(
            workspace='testworkspace', status='active', region='ap1'
        )

        call_params = mock_http_client.get.call_args[1]['params']
        assert call_params['status'] == 'active'

    @pytest.mark.asyncio
    async def test_list_with_requester_type_filter(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_list

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        await work_session_list(
            workspace='testworkspace', requester_type='agent', region='ap1'
        )

        call_params = mock_http_client.get.call_args[1]['params']
        assert call_params['requester_type'] == 'agent'
        assert 'status' not in call_params

    @pytest.mark.asyncio
    async def test_list_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_list

        mock_http_client.get.return_value = {
            'error': 'Forbidden',
            'message': 'Permission denied',
            'status_code': 403,
        }

        result = await work_session_list(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert 'Permission denied' in result['message']


class TestWorkSessionUpdate:
    @pytest.mark.asyncio
    async def test_update_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_update

        mock_http_client.patch.return_value = {
            'id': 'ws-uuid-1234',
            'status': 'pending',
            'description': 'Updated intent',
        }

        result = await work_session_update(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            title='New title',
            description='Updated intent',
            scopes=['command', 'webftp'],
            servers=['550e8400-e29b-41d4-a716-446655440001'],
            expires_at='2026-06-06T13:00:00+00:00',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/ws-uuid-1234/',
            token='test-token',
            data={
                'title': 'New title',
                'description': 'Updated intent',
                'scopes': ['command', 'webftp'],
                'servers': ['550e8400-e29b-41d4-a716-446655440001'],
                'expires_at': '2026-06-06T13:00:00+00:00',
            },
        )

    @pytest.mark.asyncio
    async def test_update_sends_only_provided_fields(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_update

        mock_http_client.patch.return_value = {'id': 'ws-uuid-1234'}

        await work_session_update(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            description='Only description changed',
            region='ap1',
        )

        call_data = mock_http_client.patch.call_args[1]['data']
        assert call_data == {'description': 'Only description changed'}

    @pytest.mark.asyncio
    async def test_update_rejects_empty_update(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_update

        result = await work_session_update(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'No fields to update' in result['message']
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_update

        mock_http_client.patch.return_value = {
            'error': 'Validation error',
            'message': 'Work session is not modifiable',
            'status_code': 400,
        }

        result = await work_session_update(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            description='Too late',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'not modifiable' in result['message']


class TestWorkSessionExtend:
    @pytest.mark.asyncio
    async def test_extend_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_extend

        mock_http_client.post.return_value = {
            'id': 'ws-uuid-1234',
            'status': 'active',
            'expires_at': '2026-06-06T18:00:00+00:00',
        }

        result = await work_session_extend(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            expires_at='2026-06-06T18:00:00+00:00',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/ws-uuid-1234/extend/',
            token='test-token',
            data={'expires_at': '2026-06-06T18:00:00+00:00'},
        )

    @pytest.mark.asyncio
    async def test_extend_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_extend

        mock_http_client.post.return_value = {
            'error': 'Validation error',
            'message': 'New expiry must be later than current expiry',
            'status_code': 400,
        }

        result = await work_session_extend(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            expires_at='2026-06-05T00:00:00+00:00',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'later than current' in result['message']


class TestWorkSessionTimeline:
    @pytest.mark.asyncio
    async def test_timeline_success_includes_records_by_default(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_timeline

        mock_http_client.get.return_value = {
            'results': [
                {'type': 'command', 'added_at': '2026-06-05T10:00:00+00:00'},
                {'type': 'websh_record', 'added_at': '2026-06-05T10:01:00+00:00'},
            ],
        }

        result = await work_session_timeline(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert len(result['data']['results']) == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/ws-uuid-1234/timeline/',
            token='test-token',
            params={'include_records': 'true'},
        )

    @pytest.mark.asyncio
    async def test_timeline_without_records(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_timeline

        mock_http_client.get.return_value = {'results': []}

        await work_session_timeline(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            include_records=False,
            region='ap1',
        )

        call_params = mock_http_client.get.call_args[1]['params']
        assert call_params == {'include_records': 'false'}

    @pytest.mark.asyncio
    async def test_timeline_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_timeline

        mock_http_client.get.return_value = {
            'error': 'Not found',
            'message': 'Work Session not found',
            'status_code': 404,
        }

        result = await work_session_timeline(
            session_id='ws-nonexistent',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'not found' in result['message'].lower()


class TestWorkSessionAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_success(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_analyze

        mock_http_client.post.return_value = {
            'id': 'analysis-uuid-1',
            'status': 'pending',
        }

        result = await work_session_analyze(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/work-sessions/sessions/ws-uuid-1234/analyze/',
            token='test-token',
            data={},
            params=None,
        )

    @pytest.mark.asyncio
    async def test_analyze_with_force(self, mock_http_client, mock_token_manager):
        from tools.work_session_tools import work_session_analyze

        mock_http_client.post.return_value = {
            'id': 'analysis-uuid-2',
            'status': 'pending',
        }

        await work_session_analyze(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            force=True,
            region='ap1',
        )

        call_params = mock_http_client.post.call_args[1]['params']
        assert call_params == {'force': 'true'}

    @pytest.mark.asyncio
    async def test_analyze_propagates_api_error(
        self, mock_http_client, mock_token_manager
    ):
        from tools.work_session_tools import work_session_analyze

        mock_http_client.post.return_value = {
            'error': 'Validation error',
            'message': 'Work session is not in a terminal state',
            'status_code': 400,
        }

        result = await work_session_analyze(
            session_id='ws-uuid-1234',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'terminal state' in result['message']
