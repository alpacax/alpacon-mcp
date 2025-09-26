"""
Unit tests for Websh tools module.

Tests Websh session management functionality including session creation,
command execution, WebSocket connections, and session termination.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio
import json


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.websh_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.websh_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


@pytest.fixture
def mock_websocket():
    """Mock WebSocket connection for testing."""
    with patch('tools.websh_tools.websockets') as mock_ws:
        mock_connection = AsyncMock()
        mock_connection.send = AsyncMock()
        mock_connection.recv = AsyncMock()
        mock_connection.close = AsyncMock()
        mock_connection.ping = AsyncMock()

        # Mock the connect function to return an async context manager for "async with"
        async_context_manager = AsyncMock()
        async_context_manager.__aenter__ = AsyncMock(return_value=mock_connection)
        async_context_manager.__aexit__ = AsyncMock(return_value=None)

        # Create a proper async context manager mock
        class AsyncContextMock:
            def __init__(self, return_value):
                self.return_value = return_value

            async def __aenter__(self):
                return self.return_value

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        # Mock connect to return our async context manager
        def mock_connect_func(url):
            # For "async with websockets.connect()" pattern
            context_manager = AsyncContextMock(mock_connection)
            # Also set it as direct return value for "await websockets.connect()" pattern
            context_manager.return_value = mock_connection
            return context_manager

        mock_ws.connect = mock_connect_func

        yield mock_ws, mock_connection


class TestWebshSessionCreate:
    """Test websh_session_create function."""

    @pytest.mark.asyncio
    async def test_session_create_success(self, mock_http_client, mock_token_manager):
        """Test successful Websh session creation."""
        from tools.websh_tools import websh_session_create

        # Mock successful response
        mock_http_client.post.return_value = {
            "id": "session-123",
            "server": "server-001",
            "username": "testuser",
            "websocket_url": "wss://test.alpacon.io/websh/123",
            "userchannel_id": "channel-456"
        }

        result = await websh_session_create(
            server_id="server-001",
            workspace="testworkspace",
            username="testuser",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["username"] == "testuser"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/websh/sessions/",
            token="test-token",
            data={
                "server": "server-001",
                "rows": 24,
                "cols": 80,
                "username": "testuser"
            }
        )

    @pytest.mark.asyncio
    async def test_session_create_without_username(self, mock_http_client, mock_token_manager):
        """Test Websh session creation without username."""
        from tools.websh_tools import websh_session_create

        mock_http_client.post.return_value = {"id": "session-123"}

        result = await websh_session_create(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["username"] == "auto"

        # Verify username was not included in request data
        call_args = mock_http_client.post.call_args
        assert "username" not in call_args[1]["data"]

    @pytest.mark.asyncio
    async def test_session_create_no_token(self, mock_http_client, mock_token_manager):
        """Test session creation when no token is available."""
        from tools.websh_tools import websh_session_create

        mock_token_manager.get_token.return_value = None

        result = await websh_session_create(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_create_http_error(self, mock_http_client, mock_token_manager):
        """Test session creation with HTTP error."""
        from tools.websh_tools import websh_session_create

        mock_http_client.post.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await websh_session_create(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to create Websh session" in result["message"]


class TestWebshSessionsList:
    """Test websh_sessions_list function."""

    @pytest.mark.asyncio
    async def test_sessions_list_success(self, mock_http_client, mock_token_manager):
        """Test successful Websh sessions listing."""
        from tools.websh_tools import websh_sessions_list

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "id": "session-123",
                    "server": "server-001",
                    "status": "active"
                },
                {
                    "id": "session-124",
                    "server": "server-002",
                    "status": "idle"
                }
            ]
        }

        result = await websh_sessions_list(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/websh/sessions/",
            token="test-token",
            params={}
        )

    @pytest.mark.asyncio
    async def test_sessions_list_with_server_filter(self, mock_http_client, mock_token_manager):
        """Test sessions listing with server filter."""
        from tools.websh_tools import websh_sessions_list

        mock_http_client.get.return_value = {"count": 1, "results": []}

        result = await websh_sessions_list(
            workspace="testworkspace",
            server_id="server-001"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"

        # Verify server filter was applied
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"]["server"] == "server-001"


class TestWebshCommandExecute:
    """Test websh_command_execute function."""

    @pytest.mark.asyncio
    async def test_command_execute_success(self, mock_http_client, mock_token_manager):
        """Test successful command execution."""
        from tools.websh_tools import websh_command_execute

        # Mock successful response
        mock_http_client.post.return_value = {
            "id": "exec-123",
            "command": "ls -la",
            "status": "completed",
            "output": "total 8\ndrwxr-xr-x 2 root root 4096 Jan 1 00:00 ."
        }

        result = await websh_command_execute(
            session_id="session-123",
            command="ls -la",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["session_id"] == "session-123"
        assert result["command"] == "ls -la"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/websh/sessions/session-123/execute/",
            token="test-token",
            data={"command": "ls -la"}
        )


class TestWebshSessionReconnect:
    """Test websh_session_reconnect function."""

    @pytest.mark.asyncio
    async def test_session_reconnect_success(self, mock_http_client, mock_token_manager):
        """Test successful session reconnection."""
        from tools.websh_tools import websh_session_reconnect

        # Mock session info response
        mock_http_client.get.return_value = {
            "id": "session-123",
            "server": "server-001",
            "status": "active"
        }

        # Mock channel creation response
        mock_http_client.post.return_value = {
            "id": "channel-789",
            "session": "session-123",
            "websocket_url": "wss://test.alpacon.io/websh/789"
        }

        result = await websh_session_reconnect(
            session_id="session-123",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["session_id"] == "session-123"
        assert "New user channel created" in result["message"]

        # Verify both GET and POST calls were made
        assert mock_http_client.get.call_count == 1
        assert mock_http_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_session_reconnect_session_not_found(self, mock_http_client, mock_token_manager):
        """Test reconnection when session is not found."""
        from tools.websh_tools import websh_session_reconnect

        # Mock session not found
        mock_http_client.get.side_effect = Exception("HTTP 404 Not Found")

        result = await websh_session_reconnect(
            session_id="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Session nonexistent not found" in result["message"]


class TestWebshSessionTerminate:
    """Test websh_session_terminate function."""

    @pytest.mark.asyncio
    async def test_session_terminate_success(self, mock_http_client, mock_token_manager):
        """Test successful session termination."""
        from tools.websh_tools import websh_session_terminate

        # Mock successful response
        mock_http_client.post.return_value = {
            "status": "closed",
            "message": "Session terminated successfully"
        }

        result = await websh_session_terminate(
            session_id="session-123",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["session_id"] == "session-123"

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/websh/sessions/session-123/close/",
            token="test-token",
            data={}
        )


class TestWebshChannelManagement:
    """Test WebSocket channel management functions."""

    def test_websh_channel_connect_already_connected(self):
        """Test connecting to already connected channel."""
        from tools.websh_tools import websh_channel_connect, websocket_pool
        import asyncio

        # Pre-populate the pool
        websocket_pool["channel-123"] = {
            'websocket': MagicMock(),
            'url': "wss://test.alpacon.io/websh/123",
            'session_id': "session-123"
        }

        async def test_already_connected():
            result = await websh_channel_connect(
                channel_id="channel-123",
                websocket_url="wss://test.alpacon.io/websh/123",
                session_id="session-123"
            )

            assert result["status"] == "already_connected"
            assert "already has active" in result["message"]

        asyncio.run(test_already_connected())

    def test_websh_channels_list(self):
        """Test listing active channels."""
        from tools.websh_tools import websh_channels_list, websocket_pool
        import asyncio

        # Setup mock pool
        websocket_pool.clear()
        mock_ws = AsyncMock()
        mock_ws.ping = AsyncMock()
        websocket_pool["channel-123"] = {
            'websocket': mock_ws,
            'url': "wss://test.alpacon.io/websh/123",
            'session_id': "session-123"
        }

        async def test_list():
            result = await websh_channels_list()

            assert result["status"] == "success"
            assert result["active_channels"] == 1
            assert len(result["channels"]) == 1
            assert result["channels"][0]["channel_id"] == "channel-123"

        asyncio.run(test_list())

    def test_websh_channel_disconnect_success(self):
        """Test successful channel disconnection."""
        from tools.websh_tools import websh_channel_disconnect, websocket_pool
        import asyncio

        # Setup mock pool
        mock_ws = AsyncMock()
        websocket_pool["channel-123"] = {
            'websocket': mock_ws,
            'url': "wss://test.alpacon.io/websh/123",
            'session_id': "session-123"
        }

        async def test_disconnect():
            result = await websh_channel_disconnect(channel_id="channel-123")

            assert result["status"] == "success"
            assert result["channel_id"] == "channel-123"
            assert "channel-123" not in websocket_pool
            mock_ws.close.assert_called_once()

        asyncio.run(test_disconnect())

    def test_websh_channel_disconnect_not_found(self):
        """Test disconnecting non-existent channel."""
        from tools.websh_tools import websh_channel_disconnect, websocket_pool
        import asyncio

        websocket_pool.clear()

        async def test_not_found():
            result = await websh_channel_disconnect(channel_id="nonexistent")

            assert result["status"] == "not_found"
            assert "not found in active connections" in result["message"]

        asyncio.run(test_not_found())


class TestWebSocketExecution:
    """Test WebSocket-based command execution."""

    @pytest.mark.asyncio
    async def test_websocket_execute_success(self, mock_websocket):
        """Test successful WebSocket command execution."""
        from tools.websh_tools import websh_websocket_execute

        mock_ws, mock_connection = mock_websocket

        # Mock received messages
        mock_connection.recv.side_effect = [
            '{"type": "output", "data": "Hello World\\n"}',
            asyncio.TimeoutError  # End the loop
        ]

        result = await websh_websocket_execute(
            websocket_url="wss://test.alpacon.io/websh/123",
            command="echo 'Hello World'",
            timeout=5
        )

        assert result["status"] == "success"
        assert result["command"] == "echo 'Hello World'"
        assert "Hello World" in result["output"]
        mock_connection.send.assert_called_once_with("echo 'Hello World'\n")

    @pytest.mark.asyncio
    async def test_websocket_execute_binary_message(self, mock_websocket):
        """Test WebSocket execution with binary messages."""
        from tools.websh_tools import websh_websocket_execute

        mock_ws, mock_connection = mock_websocket

        # Mock binary message
        mock_connection.recv.side_effect = [
            b"Binary output\n",
            asyncio.TimeoutError
        ]

        result = await websh_websocket_execute(
            websocket_url="wss://test.alpacon.io/websh/123",
            command="cat binary_file",
            timeout=5
        )

        assert result["status"] == "success"
        assert "Binary output" in result["output"]

    @pytest.mark.asyncio
    async def test_websocket_execute_connection_error(self, mock_websocket):
        """Test WebSocket execution with connection error."""
        from tools.websh_tools import websh_websocket_execute

        mock_ws, _ = mock_websocket
        mock_ws.connect.side_effect = Exception("Connection failed")

        result = await websh_websocket_execute(
            websocket_url="wss://invalid.url",
            command="echo test",
            timeout=5
        )

        assert result["status"] == "error"
        assert "WebSocket execution failed" in result["message"]

    @pytest.mark.asyncio
    async def test_websocket_batch_execute_success(self, mock_websocket):
        """Test successful batch WebSocket command execution."""
        from tools.websh_tools import websh_websocket_batch_execute

        mock_ws, mock_connection = mock_websocket

        # Mock responses for multiple commands
        mock_connection.recv.side_effect = [
            "Command 1 output\n",
            asyncio.TimeoutError,  # End first command
            "Command 2 output\n",
            asyncio.TimeoutError,  # End second command
        ]

        result = await websh_websocket_batch_execute(
            websocket_url="wss://test.alpacon.io/websh/123",
            commands=["echo cmd1", "echo cmd2"],
            timeout=30
        )

        assert result["status"] == "success"
        assert result["total_commands"] == 2
        assert len(result["results"]) == 2
        assert result["results"][0]["command"] == "echo cmd1"
        assert result["results"][1]["command"] == "echo cmd2"


class TestWebshChannelExecute:
    """Test persistent channel command execution."""

    def test_channel_execute_success(self):
        """Test successful channel command execution."""
        from tools.websh_tools import websh_channel_execute, websocket_pool
        import asyncio

        # Setup mock pool
        mock_ws = AsyncMock()
        mock_ws.ping = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock()
        mock_ws.recv.side_effect = [
            "Command output\n",
            asyncio.TimeoutError
        ]

        websocket_pool["channel-123"] = {
            'websocket': mock_ws,
            'url': "wss://test.alpacon.io/websh/123",
            'session_id': "session-123"
        }

        async def test_execute():
            result = await websh_channel_execute(
                channel_id="channel-123",
                command="ls -la",
                timeout=5
            )

            assert result["status"] == "success"
            assert result["command"] == "ls -la"
            assert "Command output" in result["output"]
            mock_ws.send.assert_called_once_with("ls -la\n")

        asyncio.run(test_execute())

    def test_channel_execute_not_connected(self):
        """Test channel execution when not connected."""
        from tools.websh_tools import websh_channel_execute, websocket_pool
        import asyncio

        websocket_pool.clear()

        async def test_not_connected():
            result = await websh_channel_execute(
                channel_id="nonexistent",
                command="ls -la"
            )

            assert result["status"] == "not_connected"
            assert "not connected" in result["message"]

        asyncio.run(test_not_connected())

    def test_channel_execute_connection_closed(self):
        """Test channel execution with closed connection."""
        from tools.websh_tools import websh_channel_execute, websocket_pool
        import asyncio
        import websockets

        # Setup mock pool with closed connection
        mock_ws = AsyncMock()
        try:
            from websockets.exceptions import ConnectionClosed
            mock_ws.ping.side_effect = ConnectionClosed(None, None)
        except ImportError:
            # Fallback for different websockets versions
            mock_ws.ping.side_effect = Exception("Connection closed")

        websocket_pool["channel-123"] = {
            'websocket': mock_ws,
            'url': "wss://test.alpacon.io/websh/123",
            'session_id': "session-123"
        }

        async def test_connection_closed():
            result = await websh_channel_execute(
                channel_id="channel-123",
                command="ls -la"
            )

            assert result["status"] == "connection_closed"
            assert "connection was closed" in result["message"]
            assert "channel-123" not in websocket_pool

        asyncio.run(test_connection_closed())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
