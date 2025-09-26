"""
Unit tests for events_tools module.

Tests event management functionality including event listing,
event retrieval, command acknowledgment, and event search.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.events_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.events_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


class TestListEvents:
    """Test list_events function."""

    @pytest.mark.asyncio
    async def test_list_events_success(self, mock_http_client, mock_token_manager):
        """Test successful events listing."""
        from tools.events_tools import list_events

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 3,
            "results": [
                {
                    "id": "event-123",
                    "server": "server-001",
                    "reporter": "system",
                    "record": "service_started",
                    "description": "Apache service started",
                    "added_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "event-124",
                    "server": "server-001",
                    "reporter": "user",
                    "record": "command_executed",
                    "description": "ls -la executed",
                    "added_at": "2024-01-01T00:01:00Z"
                },
                {
                    "id": "event-125",
                    "server": "server-002",
                    "reporter": "system",
                    "record": "disk_warning",
                    "description": "Disk usage above 80%",
                    "added_at": "2024-01-01T00:02:00Z"
                }
            ]
        }

        result = await list_events(
            workspace="testworkspace",
            server_id="server-001",
            reporter="system",
            limit=25,
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["reporter"] == "system"
        assert result["limit"] == 25
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result
        assert result["data"]["count"] == 3

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/events/",
            token="test-token",
            params={
                "page_size": 25,
                "ordering": "-added_at",
                "server": "server-001",
                "reporter": "system"
            }
        )

    @pytest.mark.asyncio
    async def test_list_events_minimal_params(self, mock_http_client, mock_token_manager):
        """Test events listing with minimal parameters."""
        from tools.events_tools import list_events

        mock_http_client.get.return_value = {"count": 0, "results": []}

        result = await list_events(workspace="testworkspace")

        assert result["status"] == "success"
        assert result["server_id"] is None
        assert result["reporter"] is None
        assert result["limit"] == 50  # Default value

        # Verify only required parameters were included
        call_args = mock_http_client.get.call_args
        expected_params = {
            "page_size": 50,
            "ordering": "-added_at"
        }
        assert call_args[1]["params"] == expected_params

    @pytest.mark.asyncio
    async def test_list_events_no_token(self, mock_http_client, mock_token_manager):
        """Test events listing when no token is available."""
        from tools.events_tools import list_events

        mock_token_manager.get_token.return_value = None

        result = await list_events(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_events_http_error(self, mock_http_client, mock_token_manager):
        """Test events listing with HTTP error."""
        from tools.events_tools import list_events

        mock_http_client.get.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await list_events(workspace="testworkspace")

        assert result["status"] == "error"
        assert "Failed to list events" in result["message"]
        assert "HTTP 500" in result["message"]


class TestGetEvent:
    """Test get_event function."""

    @pytest.mark.asyncio
    async def test_get_event_success(self, mock_http_client, mock_token_manager):
        """Test successful event details retrieval."""
        from tools.events_tools import get_event

        # Mock successful response
        mock_http_client.get.return_value = {
            "id": "event-123",
            "server": "server-001",
            "server_name": "web-server-1",
            "reporter": "system",
            "record": "service_started",
            "description": "Apache service started successfully",
            "added_at": "2024-01-01T00:00:00Z",
            "details": {
                "service": "apache2",
                "pid": 1234,
                "status": "active"
            }
        }

        result = await get_event(
            event_id="event-123",
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["event_id"] == "event-123"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result
        assert result["data"]["id"] == "event-123"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/events/event-123/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_get_event_no_token(self, mock_http_client, mock_token_manager):
        """Test event retrieval when no token is available."""
        from tools.events_tools import get_event

        mock_token_manager.get_token.return_value = None

        result = await get_event(
            event_id="event-123",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, mock_http_client, mock_token_manager):
        """Test event retrieval when event doesn't exist."""
        from tools.events_tools import get_event

        mock_http_client.get.side_effect = Exception("HTTP 404 Not Found")

        result = await get_event(
            event_id="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get event" in result["message"]
        assert "404" in result["message"]


class TestAcknowledgeCommand:
    """Test acknowledge_command function."""

    @pytest.mark.asyncio
    async def test_acknowledge_command_success(self, mock_http_client, mock_token_manager):
        """Test successful command acknowledgment."""
        from tools.events_tools import acknowledge_command

        # Mock successful response
        mock_http_client.post.return_value = {
            "id": "cmd-123",
            "status": "acknowledged",
            "acknowledged_at": "2024-01-01T00:00:00Z"
        }

        result = await acknowledge_command(
            command_id="cmd-123",
            workspace="testworkspace",
            success=True,
            result="Command received and started",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["command_id"] == "cmd-123"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/cmd-123/ack/",
            token="test-token",
            data={
                "success": True,
                "result": "Command received and started"
            }
        )

    @pytest.mark.asyncio
    async def test_acknowledge_command_minimal(self, mock_http_client, mock_token_manager):
        """Test command acknowledgment with minimal parameters."""
        from tools.events_tools import acknowledge_command

        mock_http_client.post.return_value = {"status": "acknowledged"}

        result = await acknowledge_command(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "success"

        # Verify only success parameter was included
        call_args = mock_http_client.post.call_args
        assert call_args[1]["data"] == {"success": True}

    @pytest.mark.asyncio
    async def test_acknowledge_command_failure(self, mock_http_client, mock_token_manager):
        """Test command acknowledgment with failure status."""
        from tools.events_tools import acknowledge_command

        mock_http_client.post.return_value = {"status": "failed"}

        result = await acknowledge_command(
            command_id="cmd-123",
            workspace="testworkspace",
            success=False,
            result="Command execution failed"
        )

        assert result["status"] == "success"

        # Verify failure was acknowledged
        call_args = mock_http_client.post.call_args
        assert call_args[1]["data"]["success"] == False
        assert call_args[1]["data"]["result"] == "Command execution failed"

    @pytest.mark.asyncio
    async def test_acknowledge_command_no_token(self, mock_http_client, mock_token_manager):
        """Test command acknowledgment when no token is available."""
        from tools.events_tools import acknowledge_command

        mock_token_manager.get_token.return_value = None

        result = await acknowledge_command(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.post.assert_not_called()


class TestFinishCommand:
    """Test finish_command function."""

    @pytest.mark.asyncio
    async def test_finish_command_success(self, mock_http_client, mock_token_manager):
        """Test successful command completion."""
        from tools.events_tools import finish_command

        # Mock successful response
        mock_http_client.post.return_value = {
            "id": "cmd-123",
            "status": "finished",
            "finished_at": "2024-01-01T00:00:05Z",
            "elapsed_time": 5.2
        }

        result = await finish_command(
            command_id="cmd-123",
            workspace="testworkspace",
            success=True,
            result="Command completed successfully",
            elapsed_time=5.2,
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["command_id"] == "cmd-123"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.post.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/cmd-123/fin/",
            token="test-token",
            data={
                "success": True,
                "result": "Command completed successfully",
                "elapsed_time": 5.2
            }
        )

    @pytest.mark.asyncio
    async def test_finish_command_minimal(self, mock_http_client, mock_token_manager):
        """Test command finish with minimal parameters."""
        from tools.events_tools import finish_command

        mock_http_client.post.return_value = {"status": "finished"}

        result = await finish_command(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "success"

        # Verify only success parameter was included
        call_args = mock_http_client.post.call_args
        assert call_args[1]["data"] == {"success": True}

    @pytest.mark.asyncio
    async def test_finish_command_with_zero_elapsed_time(self, mock_http_client, mock_token_manager):
        """Test command finish with zero elapsed time."""
        from tools.events_tools import finish_command

        mock_http_client.post.return_value = {"status": "finished"}

        result = await finish_command(
            command_id="cmd-123",
            workspace="testworkspace",
            elapsed_time=0.0
        )

        assert result["status"] == "success"

        # Verify elapsed_time=0.0 was included
        call_args = mock_http_client.post.call_args
        assert call_args[1]["data"]["elapsed_time"] == 0.0

    @pytest.mark.asyncio
    async def test_finish_command_no_token(self, mock_http_client, mock_token_manager):
        """Test command finish when no token is available."""
        from tools.events_tools import finish_command

        mock_token_manager.get_token.return_value = None

        result = await finish_command(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetCommandStatus:
    """Test get_command_status function."""

    @pytest.mark.asyncio
    async def test_get_command_status_success(self, mock_http_client, mock_token_manager):
        """Test successful command status retrieval."""
        from tools.events_tools import get_command_status

        # Mock successful response
        mock_http_client.get.return_value = {
            "id": "cmd-123",
            "server": "server-001",
            "command": "ls -la",
            "status": "finished",
            "success": True,
            "started_at": "2024-01-01T00:00:00Z",
            "finished_at": "2024-01-01T00:00:05Z",
            "elapsed_time": 5.2,
            "result": "total 8\ndrwxr-xr-x 2 root root 4096 Jan 1 00:00 .",
            "exit_code": 0
        }

        result = await get_command_status(
            command_id="cmd-123",
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["command_id"] == "cmd-123"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result
        assert result["data"]["status"] == "finished"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/cmd-123/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_get_command_status_no_token(self, mock_http_client, mock_token_manager):
        """Test command status when no token is available."""
        from tools.events_tools import get_command_status

        mock_token_manager.get_token.return_value = None

        result = await get_command_status(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]

    @pytest.mark.asyncio
    async def test_get_command_status_not_found(self, mock_http_client, mock_token_manager):
        """Test command status when command doesn't exist."""
        from tools.events_tools import get_command_status

        mock_http_client.get.side_effect = Exception("HTTP 404 Not Found")

        result = await get_command_status(
            command_id="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get command status" in result["message"]


class TestDeleteCommand:
    """Test delete_command function."""

    @pytest.mark.asyncio
    async def test_delete_command_success(self, mock_http_client, mock_token_manager):
        """Test successful command deletion."""
        from tools.events_tools import delete_command

        # Mock successful response
        mock_http_client.delete.return_value = {
            "message": "Command deleted successfully"
        }

        result = await delete_command(
            command_id="cmd-123",
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["command_id"] == "cmd-123"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.delete.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/commands/cmd-123/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_delete_command_no_token(self, mock_http_client, mock_token_manager):
        """Test command deletion when no token is available."""
        from tools.events_tools import delete_command

        mock_token_manager.get_token.return_value = None

        result = await delete_command(
            command_id="cmd-123",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_command_not_found(self, mock_http_client, mock_token_manager):
        """Test command deletion when command doesn't exist."""
        from tools.events_tools import delete_command

        mock_http_client.delete.side_effect = Exception("HTTP 404 Not Found")

        result = await delete_command(
            command_id="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to delete command" in result["message"]


class TestSearchEvents:
    """Test search_events function."""

    @pytest.mark.asyncio
    async def test_search_events_success(self, mock_http_client, mock_token_manager):
        """Test successful event search."""
        from tools.events_tools import search_events

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "id": "event-123",
                    "server": "server-001",
                    "reporter": "system",
                    "record": "service_error",
                    "description": "Apache service error: connection refused",
                    "added_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "event-124",
                    "server": "server-002",
                    "reporter": "user",
                    "record": "command_error",
                    "description": "Command failed: apache2 restart",
                    "added_at": "2024-01-01T00:01:00Z"
                }
            ]
        }

        result = await search_events(
            search_query="apache",
            workspace="testworkspace",
            server_id="server-001",
            limit=10,
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["search_query"] == "apache"
        assert result["server_id"] == "server-001"
        assert result["limit"] == 10
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/events/events/",
            token="test-token",
            params={
                "search": "apache",
                "page_size": 10,
                "ordering": "-added_at",
                "server": "server-001"
            }
        )

    @pytest.mark.asyncio
    async def test_search_events_minimal_params(self, mock_http_client, mock_token_manager):
        """Test event search with minimal parameters."""
        from tools.events_tools import search_events

        mock_http_client.get.return_value = {"count": 0, "results": []}

        result = await search_events(
            search_query="error",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["search_query"] == "error"
        assert result["server_id"] is None
        assert result["limit"] == 20  # Default value

        # Verify correct parameters were sent
        call_args = mock_http_client.get.call_args
        expected_params = {
            "search": "error",
            "page_size": 20,
            "ordering": "-added_at"
        }
        assert call_args[1]["params"] == expected_params

    @pytest.mark.asyncio
    async def test_search_events_no_results(self, mock_http_client, mock_token_manager):
        """Test event search with no results."""
        from tools.events_tools import search_events

        mock_http_client.get.return_value = {"count": 0, "results": []}

        result = await search_events(
            search_query="nonexistent",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"]["count"] == 0
        assert result["data"]["results"] == []

    @pytest.mark.asyncio
    async def test_search_events_no_token(self, mock_http_client, mock_token_manager):
        """Test event search when no token is available."""
        from tools.events_tools import search_events

        mock_token_manager.get_token.return_value = None

        result = await search_events(
            search_query="test",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]

    @pytest.mark.asyncio
    async def test_search_events_http_error(self, mock_http_client, mock_token_manager):
        """Test event search with HTTP error."""
        from tools.events_tools import search_events

        mock_http_client.get.side_effect = Exception("Search service unavailable")

        result = await search_events(
            search_query="test",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to search events" in result["message"]
        assert "Search service unavailable" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])