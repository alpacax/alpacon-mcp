"""Unit tests for command tools module."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.command_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestSubmitCommand:
    """Test _submit_command internal helper."""

    @pytest.mark.asyncio
    async def test_submit_basic(self, mock_http_client):
        from tools.command_tools import _submit_command

        mock_http_client.post.return_value = {'id': 'cmd-123', 'status': 'running'}

        result = await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls -la',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        assert result['id'] == 'cmd-123'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': '550e8400-e29b-41d4-a716-446655440001',
                'shell': 'system',
                'line': 'ls -la',
                'groupname': 'alpacon',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_with_optional_params(self, mock_http_client):
        from tools.command_tools import _submit_command

        mock_http_client.post.return_value = {'id': 'cmd-456'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='echo done',
            workspace='testworkspace',
            username='testuser',
            env={'PATH': '/usr/bin'},
            run_after=['cmd-100'],
            scheduled_at='2026-04-03T03:00:00Z',
            data='stdin input',
            region='ap1',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['username'] == 'testuser'
        assert call_data['env'] == {'PATH': '/usr/bin'}
        assert call_data['run_after'] == ['cmd-100']
        assert call_data['scheduled_at'] == '2026-04-03T03:00:00Z'
        assert call_data['data'] == 'stdin input'

    @pytest.mark.asyncio
    async def test_submit_omits_none_params(self, mock_http_client):
        from tools.command_tools import _submit_command

        mock_http_client.post.return_value = {'id': 'cmd-789'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert 'username' not in call_data
        assert 'run_after' not in call_data
        assert 'scheduled_at' not in call_data
        assert 'data' not in call_data


class TestListCommands:
    """Test list_commands function."""

    @pytest.mark.asyncio
    async def test_list_commands_success(self, mock_http_client, mock_token_manager):
        from tools.command_tools import list_commands

        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'cmd-123', 'command': 'ls -la', 'status': 'completed'},
                {'id': 'cmd-124', 'command': 'ps aux', 'status': 'running'},
            ],
        }

        result = await list_commands(workspace='testworkspace', limit=10, region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            params={'page_size': 10, 'ordering': '-added_at'},
        )

    @pytest.mark.asyncio
    async def test_list_commands_with_server_filter(
        self, mock_http_client, mock_token_manager
    ):
        from tools.command_tools import list_commands

        mock_http_client.get.return_value = {'count': 1, 'results': []}

        result = await list_commands(
            workspace='testworkspace',
            server_id='550e8400-e29b-41d4-a716-446655440001',
        )

        assert result['status'] == 'success'
        call_args = mock_http_client.get.call_args
        assert (
            call_args[1]['params']['server'] == '550e8400-e29b-41d4-a716-446655440001'
        )

    @pytest.mark.asyncio
    async def test_list_commands_no_token(self, mock_http_client, mock_token_manager):
        from tools.command_tools import list_commands

        mock_token_manager.get_token.return_value = None

        result = await list_commands(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestExecuteCommand:
    """Test execute_command function (renamed from execute_command_sync)."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-123'}
            mock_poll.return_value = {
                'id': 'cmd-123',
                'status': 'completed',
                'exit_code': 0,
                'finished_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert result['command_id'] == 'cmd-123'
            assert result['command'] == 'echo test'

    @pytest.mark.asyncio
    async def test_array_response(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = [{'id': 'cmd-123'}]
            mock_poll.return_value = {
                'id': 'cmd-123',
                'finished_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
            )

            assert result['status'] == 'success'
            assert result['command_id'] == 'cmd-123'

    @pytest.mark.asyncio
    async def test_timeout(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-123'}
            mock_poll.return_value = {
                'id': 'cmd-123',
                'status': 'running',
                'finished_at': None,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sleep 100',
                workspace='testworkspace',
                timeout=1,
            )

            assert result['status'] == 'error'
            assert result['error_type'] == 'timeout'
            assert 'timed out' in result['message']

    @pytest.mark.asyncio
    async def test_acl_error(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {
                'error': 'Permission denied',
                'status_code': 403,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls',
                workspace='testworkspace',
            )

            assert result['status'] == 'error'
            assert 'Permission denied' in result['message']

    @pytest.mark.asyncio
    async def test_empty_data_array(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = []

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
            )

            assert result['status'] == 'error'
            assert 'No command data returned' in result['message']

    @pytest.mark.asyncio
    async def test_stuck_status(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-300'}
            mock_poll.return_value = {
                'id': 'cmd-300',
                'status': 'stuck',
                'finished_at': None,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='bad command',
                workspace='testworkspace',
                timeout=2,
            )

            assert result['status'] == 'error'
            assert 'stuck' in result['message']

    @pytest.mark.asyncio
    async def test_forwards_all_params(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-200'}
            mock_poll.return_value = {
                'id': 'cmd-200',
                'finished_at': '2024-01-01T00:00:01Z',
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
                run_after=['cmd-100'],
                scheduled_at='2026-04-03T03:00:00Z',
                data='stdin input',
                timeout=10,
            )

            call_kwargs = mock_submit.call_args[1]
            assert call_kwargs['run_after'] == ['cmd-100']
            assert call_kwargs['scheduled_at'] == '2026-04-03T03:00:00Z'
            assert call_kwargs['data'] == 'stdin input'

    @pytest.mark.asyncio
    async def test_no_token(self, mock_http_client, mock_token_manager):
        from tools.command_tools import execute_command

        mock_token_manager.get_token.return_value = None

        result = await execute_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls -la',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
