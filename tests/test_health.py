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
def patched_health_local(mock_token_manager, mock_http_client):
    """Patch dependencies for local (stdio) mode health checks."""
    with (
        patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': ''}, clear=False),
        patch(
            'utils.token_manager.get_token_manager',
            return_value=mock_token_manager,
        ),
        patch('utils.http_client.http_client', mock_http_client),
    ):
        yield


@pytest.fixture
def patched_health_remote(mock_http_client):
    """Patch dependencies for remote (streamable-http) mode health checks."""
    with (
        patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'}, clear=False),
        patch('utils.http_client.http_client', mock_http_client),
    ):
        yield


class TestGetHealthInfoLocal:
    """Tests for get_health_info in local (stdio/SSE) mode."""

    @pytest.mark.asyncio
    async def test_returns_required_fields(self, patched_health_local):
        """Health info must contain all required top-level keys."""
        from utils.health import get_health_info

        result = await get_health_info()

        required_keys = {
            'status',
            'version',
            'uptime_seconds',
            'transport',
            'auth',
            'http_client',
            'websocket_pool',
        }
        assert required_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_status_is_ok(self, patched_health_local):
        """Status field must always be 'ok'."""
        from utils.health import get_health_info

        result = await get_health_info()

        assert result['status'] == 'ok'

    @pytest.mark.asyncio
    async def test_version_matches_mcp_version(self, patched_health_local):
        """Version must match the MCP_VERSION constant."""
        from utils.common import MCP_VERSION
        from utils.health import get_health_info

        result = await get_health_info()

        assert result['version'] == MCP_VERSION

    @pytest.mark.asyncio
    async def test_uptime_is_positive(self, patched_health_local):
        """Uptime must be a positive number."""
        from utils.health import get_health_info

        result = await get_health_info()

        assert isinstance(result['uptime_seconds'], float)
        assert result['uptime_seconds'] >= 0

    @pytest.mark.asyncio
    async def test_local_auth_info(self, patched_health_local):
        """Local mode auth must report token_file info without secrets."""
        from utils.health import get_health_info

        result = await get_health_info()

        auth = result['auth']
        assert auth['mode'] == 'token_file'
        assert auth['authenticated'] is True
        assert auth['total_tokens'] == 3
        assert auth['regions_configured'] == 2

        # Must not contain paths or workspace names
        assert 'config_dir' not in auth
        assert 'token_file' not in auth
        assert 'regions' not in auth

    @pytest.mark.asyncio
    async def test_http_client_info(self, patched_health_local):
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
            patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': ''}, clear=False),
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
    async def test_websocket_pool_info(self, patched_health_local):
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


class TestGetHealthInfoRemote:
    """Tests for get_health_info in remote (streamable-http) mode."""

    @pytest.mark.asyncio
    async def test_remote_auth_info(self, patched_health_remote):
        """Remote mode auth must report JWT mode without token.json info."""
        from utils.health import get_health_info

        result = await get_health_info()

        auth = result['auth']
        assert auth['mode'] == 'jwt'
        assert auth['auth_required'] is True

        # Must NOT contain token_file-specific fields
        assert 'total_tokens' not in auth
        assert 'regions_configured' not in auth

    @pytest.mark.asyncio
    async def test_remote_does_not_touch_token_manager(self, patched_health_remote):
        """Remote mode must not import or call token_manager.

        Patches at both utils.token_manager and utils.health level to
        ensure no token_manager access regardless of module caching.
        """
        sentinel = AssertionError('token_manager should not be called in remote mode')
        with (
            patch('utils.token_manager.get_token_manager', side_effect=sentinel),
            patch.dict(
                'sys.modules', {'utils.common': MagicMock(MCP_VERSION='0.0.0-test')}
            ),
        ):
            import importlib
            import sys

            # Force fresh import of utils.health to avoid cached module paths
            sys.modules.pop('utils.health', None)
            import utils.health

            importlib.reload(utils.health)
            result = await utils.health.get_health_info()

        assert result['auth']['mode'] == 'jwt'


class TestHealthCheckTool:
    """Tests for the health_check MCP tool (local mode only)."""

    @pytest.mark.asyncio
    async def test_health_check_tool_returns_success(self, patched_health_local):
        """health_check tool must wrap health info in success response."""
        from tools.health_tools import health_check

        result = await health_check()

        assert result['status'] == 'success'
        assert 'data' in result
        assert result['data']['status'] == 'ok'
        assert 'version' in result['data']

    @pytest.mark.asyncio
    async def test_health_check_tool_no_params_required(self, patched_health_local):
        """health_check tool must work with zero arguments."""
        from tools.health_tools import health_check

        # Should not raise
        result = await health_check()

        assert result['status'] == 'success'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
