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


class TestHealthCheckRemoteMode:
    """Tests verifying health_check tool works in remote (streamable-http) mode."""

    @pytest.mark.asyncio
    async def test_health_check_callable_in_remote_mode(self, patched_health_remote):
        """health_check tool must work even when ALPACON_MCP_AUTH_ENABLED=true."""
        from tools.health_tools import health_check

        result = await health_check()

        assert result['status'] == 'success'
        assert result['data']['status'] == 'ok'
        assert result['data']['auth']['mode'] == 'jwt'

    def test_server_module_imports_health_tools_unconditionally(self):
        """server.run() must import tools.health_tools regardless of remote_mode.

        Verifies the guard `if not remote_mode: import tools.health_tools` has been
        removed so the MCP tool is registered in all transports. Uses AST inspection
        so the assertion isn't sensitive to whitespace or comment changes.
        """
        import ast
        import inspect

        import server

        tree = ast.parse(inspect.getsource(server.run))
        function_def = tree.body[0]
        assert isinstance(function_def, (ast.FunctionDef, ast.AsyncFunctionDef))

        def imports_health_tools(node: ast.AST) -> bool:
            return isinstance(node, ast.Import) and any(
                alias.name == 'tools.health_tools' for alias in node.names
            )

        # The import must appear at the top level of run(), not nested inside any
        # conditional or other compound statement.
        assert any(imports_health_tools(stmt) for stmt in function_def.body), (
            'tools.health_tools must be imported unconditionally inside server.run()'
        )

        # No If/Try/With block inside run() may guard the import.
        for node in ast.walk(function_def):
            if isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith)):
                for child in ast.walk(node):
                    assert not imports_health_tools(child), (
                        'tools.health_tools import must not be guarded by a control-flow block'
                    )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
