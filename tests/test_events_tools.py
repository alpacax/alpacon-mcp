"""
Unit tests for events_tools module.

Tests event management functionality including event listing,
event retrieval, and event search.
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
    with patch('utils.common.token_manager') as mock_manager:
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
        assert "404" in result["message"]


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
        assert "Search service unavailable" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
