"""Unit tests for agent action tools in server_tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.server_tools import restart_agent, shutdown_agent, upgrade_agent


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.server_tools.http_client') as mock_client:
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'


class TestRestartAgent:
    """Test agent restart functionality."""

    @pytest.mark.asyncio
    async def test_restart_agent_success(self, mock_http_client, mock_token_manager):
        """Test successful agent restart."""
        mock_http_client.post.return_value = {'status': 'restarting'}

        result = await restart_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/action/',
            token='test-token',
            data={'action': 'restart'},
        )

    @pytest.mark.asyncio
    async def test_restart_agent_http_error(self, mock_http_client, mock_token_manager):
        """Test agent restart with HTTP error."""
        mock_http_client.post.side_effect = Exception('HTTP 503: Service Unavailable')

        result = await restart_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'HTTP 503' in result['message']


class TestShutdownAgent:
    """Test agent shutdown functionality."""

    @pytest.mark.asyncio
    async def test_shutdown_agent_success(self, mock_http_client, mock_token_manager):
        """Test successful agent shutdown."""
        mock_http_client.post.return_value = {'status': 'shutting_down'}

        result = await shutdown_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/action/',
            token='test-token',
            data={'action': 'shutdown'},
        )


class TestUpgradeAgent:
    """Test agent upgrade functionality."""

    @pytest.mark.asyncio
    async def test_upgrade_agent_success(self, mock_http_client, mock_token_manager):
        """Test successful agent upgrade."""
        mock_http_client.post.return_value = {'status': 'upgrading'}

        result = await upgrade_agent(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/servers/servers/{SERVER_ID}/action/',
            token='test-token',
            data={'action': 'upgrade'},
        )

    @pytest.mark.asyncio
    async def test_upgrade_agent_no_token(self, mock_http_client, mock_token_manager):
        """Test agent upgrade with no token."""
        mock_token_manager.get_token.return_value = None

        result = await upgrade_agent(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()
