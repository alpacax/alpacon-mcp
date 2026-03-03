"""Tests for health check functionality."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_token_manager():
    """Mock token manager returning sanitized auth status."""
    mock_manager = MagicMock()
    mock_manager.get_auth_status.return_value = {
        'authenticated': True,
        'total_tokens': 3,
        'regions': [
            {'region': 'ap1', 'workspaces': ['prod', 'staging'], 'count': 2},
            {'region': 'us1', 'workspaces': ['backup'], 'count': 1},
        ],
        'config_dir': '/home/user/.alpacon-mcp',
        'token_file': '/home/user/.alpacon-mcp/token.json',
    }
    return mock_manager


@pytest.fixture
def mock_http_client():
    """Mock HTTP client with pool state."""
    mock_client = MagicMock()
    mock_client.pool_active = True
    mock_client.cache_size = 2
    return mock_client


@pytest.fixture
def patched_health(mock_token_manager, mock_http_client):
    """Patch dependencies used by get_health_info via deferred imports."""
    with (
        patch(
            'utils.token_manager.get_token_manager',
            return_value=mock_token_manager,
        ),
        patch('utils.http_client.http_client', mock_http_client),
    ):
        yield


class TestGetHealthInfo:
    """Tests for get_health_info utility function."""

    @pytest.mark.asyncio
    async def test_returns_required_fields(self, patched_health):
        """Health info must contain all required top-level keys."""
        from utils.health import get_health_info

        result = await get_health_info()

        required_keys = {
            'status',
            'version',
            'uptime_seconds',
            'transport',
            'token_config',
            'http_client',
            'websocket_pool',
        }
        assert required_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_status_is_ok(self, patched_health):
        """Status field must always be 'ok'."""
        from utils.health import get_health_info

        result = await get_health_info()

        assert result['status'] == 'ok'

    @pytest.mark.asyncio
    async def test_version_matches_mcp_version(self, patched_health):
        """Version must match the MCP_VERSION constant."""
        from utils.common import MCP_VERSION
        from utils.health import get_health_info

        result = await get_health_info()

        assert result['version'] == MCP_VERSION

    @pytest.mark.asyncio
    async def test_uptime_is_positive(self, patched_health):
        """Uptime must be a positive number."""
        from utils.health import get_health_info

        result = await get_health_info()

        assert isinstance(result['uptime_seconds'], float)
        assert result['uptime_seconds'] >= 0

    @pytest.mark.asyncio
    async def test_no_secrets_in_token_config(self, patched_health):
        """Token config must not expose sensitive information."""
        from utils.health import get_health_info

        result = await get_health_info()

        token_config = result['token_config']

        # Must not contain paths or workspace names
        assert 'config_dir' not in token_config
        assert 'token_file' not in token_config
        assert 'regions' not in token_config  # regions contain workspace names

        # Must only contain safe fields
        allowed_keys = {'authenticated', 'total_tokens', 'regions_configured'}
        assert set(token_config.keys()) == allowed_keys

    @pytest.mark.asyncio
    async def test_http_client_info(self, patched_health):
        """HTTP client section must report pool_active and cache_size."""
        from utils.health import get_health_info

        result = await get_health_info()

        http_info = result['http_client']
        assert http_info['pool_active'] is True
        assert http_info['cache_size'] == 2

    @pytest.mark.asyncio
    async def test_http_client_no_pool(self, mock_token_manager):
        """HTTP client reports pool_active=False when no client exists."""
        mock_client = MagicMock()
        mock_client.pool_active = False
        mock_client.cache_size = 0

        with (
            patch(
                'utils.token_manager.get_token_manager',
                return_value=mock_token_manager,
            ),
            patch('utils.http_client.http_client', mock_client),
        ):
            from utils.health import get_health_info

            result = await get_health_info()

        assert result['http_client']['pool_active'] is False
        assert result['http_client']['cache_size'] == 0

    @pytest.mark.asyncio
    async def test_websocket_pool_info(self, patched_health):
        """WebSocket pool section must report channel and session counts."""
        with (
            patch(
                'tools.websh_tools.websocket_pool',
                {'ch1': {}, 'ch2': {}},
            ),
            patch(
                'tools.websh_tools.session_pool',
                {'sess1': {}},
            ),
        ):
            from utils.health import get_health_info

            result = await get_health_info()

        ws_info = result['websocket_pool']
        assert ws_info['active_channels'] == 2
        assert ws_info['active_sessions'] == 1


class TestHealthCheckTool:
    """Tests for the health_check MCP tool."""

    @pytest.mark.asyncio
    async def test_health_check_tool_returns_success(self, patched_health):
        """health_check tool must wrap health info in success response."""
        from tools.health_tools import health_check

        result = await health_check()

        assert result['status'] == 'success'
        assert 'data' in result
        assert result['data']['status'] == 'ok'
        assert 'version' in result['data']

    @pytest.mark.asyncio
    async def test_health_check_tool_no_params_required(self, patched_health):
        """health_check tool must work with zero arguments."""
        from tools.health_tools import health_check

        # Should not raise
        result = await health_check()

        assert result['status'] == 'success'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
