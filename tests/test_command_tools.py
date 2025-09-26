"""
Unit tests for command tools module.

Tests command execution functionality including command execution,
result retrieval, command listing, and synchronous execution.
"""
import pytest
from unittest.mock import AsyncMock, patch
import asyncio


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.command_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.command_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


class TestExecuteCommand:
    """Test execute_command function."""

    @pytest.mark.asyncio
    async def test_execute_command_success(self, mock_http_client, mock_token_manager):
        """Test successful command execution."""
        from tools.command_tools import execute_command

        # Mock successful response
        mock_http_client.post.return_value = {
            "id": "cmd-123",
            "server": "server-001",
            "command": "ls -la",
            "status": "running"
        }

        result = await execute_command(
            server_id="server-001",
            command="ls -la",
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["command"] == "ls -la"
        assert result["shell"] == "internal"  # default value
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/",
            token="test-token",
            data={
                "server": "server-001",
                "shell": "internal",
                "line": "ls -la",
                "groupname": "alpacon"
            }
        )

    @pytest.mark.asyncio
    async def test_execute_command_with_optional_params(self, mock_http_client, mock_token_manager):
        """Test command execution with optional parameters."""
        from tools.command_tools import execute_command

        mock_http_client.post.return_value = {"id": "cmd-123"}

        result = await execute_command(
            server_id="server-001",
            command="echo hello",
            workspace="testworkspace",
            shell="bash",
            username="testuser",
            groupname="testgroup",
            env={"PATH": "/usr/bin", "HOME": "/home/test"},
            region="us1"
        )

        assert result["status"] == "success"
        assert result["shell"] == "bash"
        assert result["username"] == "testuser"
        assert result["groupname"] == "testgroup"

        # Verify correct data was sent
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        assert call_args[1]["data"]["username"] == "testuser"
        assert call_args[1]["data"]["env"] == {"PATH": "/usr/bin", "HOME": "/home/test"}

    @pytest.mark.asyncio
    async def test_execute_command_no_token(self, mock_http_client, mock_token_manager):
        """Test command execution when no token is available."""
        from tools.command_tools import execute_command

        # Mock no token available
        mock_token_manager.get_token.return_value = None

        result = await execute_command(
            server_id="server-001",
            command="ls -la",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_command_http_error(self, mock_http_client, mock_token_manager):
        """Test command execution with HTTP error."""
        from tools.command_tools import execute_command

        # Mock HTTP client to raise exception
        mock_http_client.post.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await execute_command(
            server_id="server-001",
            command="ls -la",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to execute command" in result["message"]
        assert "HTTP 500" in result["message"]


class TestGetCommandResult:
    """Test get_command_result function."""

    @pytest.mark.asyncio
    async def test_get_command_result_success(self, mock_http_client, mock_token_manager):
        """Test successful command result retrieval."""
        from tools.command_tools import get_command_result

        # Mock successful response
        mock_http_client.get.return_value = {
            "id": "cmd-123",
            "command": "ls -la",
            "status": "completed",
            "exit_code": 0,
            "stdout": "total 8\ndrwxr-xr-x 2 root root 4096 Jan 1 00:00 .\n",
            "stderr": "",
            "started_at": "2024-01-01T00:00:00Z",
            "finished_at": "2024-01-01T00:00:01Z"
        }

        result = await get_command_result(
            command_id="cmd-123",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["command_id"] == "cmd-123"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["exit_code"] == 0

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/cmd-123/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_get_command_result_no_token(self, mock_http_client, mock_token_manager):
        """Test command result retrieval when no token is available."""
        from tools.command_tools import get_command_result

        mock_token_manager.get_token.return_value = None

        result = await get_command_result(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_command_result_http_error(self, mock_http_client, mock_token_manager):
        """Test command result retrieval with HTTP error."""
        from tools.command_tools import get_command_result

        mock_http_client.get.side_effect = Exception("HTTP 404 Not Found")

        result = await get_command_result(
            command_id="cmd-nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get command result" in result["message"]


class TestListCommands:
    """Test list_commands function."""

    @pytest.mark.asyncio
    async def test_list_commands_success(self, mock_http_client, mock_token_manager):
        """Test successful command listing."""
        from tools.command_tools import list_commands

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "id": "cmd-123",
                    "command": "ls -la",
                    "status": "completed",
                    "server": "server-001",
                    "added_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "cmd-124",
                    "command": "ps aux",
                    "status": "running",
                    "server": "server-002",
                    "added_at": "2024-01-01T00:01:00Z"
                }
            ]
        }

        result = await list_commands(
            workspace="testworkspace",
            limit=10,
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["limit"] == 10
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/",
            token="test-token",
            params={
                "page_size": 10,
                "ordering": "-added_at"
            }
        )

    @pytest.mark.asyncio
    async def test_list_commands_with_server_filter(self, mock_http_client, mock_token_manager):
        """Test command listing with server filter."""
        from tools.command_tools import list_commands

        mock_http_client.get.return_value = {"count": 1, "results": []}

        result = await list_commands(
            workspace="testworkspace",
            server_id="server-001",
            limit=20
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"]["server"] == "server-001"

    @pytest.mark.asyncio
    async def test_list_commands_no_token(self, mock_http_client, mock_token_manager):
        """Test command listing when no token is available."""
        from tools.command_tools import list_commands

        mock_token_manager.get_token.return_value = None

        result = await list_commands(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()


class TestExecuteCommandSync:
    """Test execute_command_sync function."""

    @pytest.mark.asyncio
    async def test_execute_command_sync_success(self, mock_http_client, mock_token_manager):
        """Test successful synchronous command execution."""
        from tools.command_tools import execute_command_sync

        # Mock execute_command response
        with patch('tools.command_tools.execute_command') as mock_execute:
            with patch('tools.command_tools.get_command_result') as mock_get_result:
                # Mock successful execution
                mock_execute.return_value = {
                    "status": "success",
                    "data": {"id": "cmd-123"}
                }

                # Mock completed command result
                mock_get_result.return_value = {
                    "status": "success",
                    "data": {
                        "id": "cmd-123",
                        "status": "completed",
                        "exit_code": 0,
                        "finished_at": "2024-01-01T00:00:01Z"
                    }
                }

                result = await execute_command_sync(
                    server_id="server-001",
                    command="echo test",
                    workspace="testworkspace",
                    timeout=10
                )

                assert result["status"] == "success"
                assert result["command_id"] == "cmd-123"
                assert result["server_id"] == "server-001"
                assert result["command"] == "echo test"

    @pytest.mark.asyncio
    async def test_execute_command_sync_with_array_response(self, mock_http_client, mock_token_manager):
        """Test synchronous command execution with array response."""
        from tools.command_tools import execute_command_sync

        with patch('tools.command_tools.execute_command') as mock_execute:
            with patch('tools.command_tools.get_command_result') as mock_get_result:
                # Mock execute_command returning array
                mock_execute.return_value = {
                    "status": "success",
                    "data": [{"id": "cmd-123"}]
                }

                mock_get_result.return_value = {
                    "status": "success",
                    "data": {
                        "id": "cmd-123",
                        "finished_at": "2024-01-01T00:00:01Z"
                    }
                }

                result = await execute_command_sync(
                    server_id="server-001",
                    command="echo test",
                    workspace="testworkspace"
                )

                assert result["status"] == "success"
                assert result["command_id"] == "cmd-123"

    @pytest.mark.asyncio
    async def test_execute_command_sync_timeout(self, mock_http_client, mock_token_manager):
        """Test synchronous command execution timeout."""
        from tools.command_tools import execute_command_sync

        with patch('tools.command_tools.execute_command') as mock_execute:
            with patch('tools.command_tools.get_command_result') as mock_get_result:
                # Mock successful execution
                mock_execute.return_value = {
                    "status": "success",
                    "data": {"id": "cmd-123"}
                }

                # Mock command still running (no finished_at)
                mock_get_result.return_value = {
                    "status": "success",
                    "data": {
                        "id": "cmd-123",
                        "status": "running",
                        "finished_at": None
                    }
                }

                result = await execute_command_sync(
                    server_id="server-001",
                    command="sleep 100",
                    workspace="testworkspace",
                    timeout=1  # Short timeout
                )

                assert result["status"] == "timeout"
                assert "timed out" in result["message"]
                assert result["command_id"] == "cmd-123"

    @pytest.mark.asyncio
    async def test_execute_command_sync_execute_fails(self, mock_http_client, mock_token_manager):
        """Test synchronous command execution when initial execute fails."""
        from tools.command_tools import execute_command_sync

        with patch('tools.command_tools.execute_command') as mock_execute:
            # Mock execution failure
            mock_execute.return_value = {
                "status": "error",
                "message": "Server not found"
            }

            result = await execute_command_sync(
                server_id="nonexistent",
                command="echo test",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert result["message"] == "Server not found"

    @pytest.mark.asyncio
    async def test_execute_command_sync_empty_data_array(self, mock_http_client, mock_token_manager):
        """Test synchronous command execution with empty data array."""
        from tools.command_tools import execute_command_sync

        with patch('tools.command_tools.execute_command') as mock_execute:
            # Mock execute_command returning empty array
            mock_execute.return_value = {
                "status": "success",
                "data": []
            }

            result = await execute_command_sync(
                server_id="server-001",
                command="echo test",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "No command data returned" in result["message"]

    @pytest.mark.asyncio
    async def test_execute_command_sync_exception(self, mock_http_client, mock_token_manager):
        """Test synchronous command execution with exception."""
        from tools.command_tools import execute_command_sync

        with patch('tools.command_tools.execute_command') as mock_execute:
            # Mock exception during execution
            mock_execute.side_effect = Exception("Network error")

            result = await execute_command_sync(
                server_id="server-001",
                command="echo test",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "Failed to execute command synchronously" in result["message"]
            assert "Network error" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])