"""
Unit tests for HTTP client utility.

Tests the HTTP client functionality including GET, POST, PATCH, DELETE operations
and error handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from utils.http_client import http_client


@pytest.fixture
def mock_httpx_client():
    """Mock httpx AsyncClient for testing."""
    with patch('utils.http_client.httpx.AsyncClient') as mock_client_class:
        # Disable connection pooling for all tests
        http_client._disable_pooling = True

        # Create a mock client with AsyncMock methods
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Set up async context manager
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Make sure the client is closed property returns False
        mock_client.is_closed = False

        # HTTP methods should be AsyncMock so they can be awaited
        mock_client.request = AsyncMock()
        yield mock_client

        # Clean up after tests
        if hasattr(http_client, '_disable_pooling'):
            delattr(http_client, '_disable_pooling')

def create_mock_response(status_code=200, json_data=None, text_data="", headers=None):
    """Create a properly configured mock response."""
    # Use MagicMock instead of AsyncMock for response to avoid coroutine issues
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    mock_response.content = text_data.encode() if text_data else b""

    if json_data is not None:
        mock_response.json.return_value = json_data
        # Set text to string representation that won't be empty
        mock_response.text = "mock response text"
    else:
        mock_response.json.return_value = {}
        mock_response.text = ""

    # Mock raise_for_status to raise HTTPStatusError for error codes
    if status_code >= 400:
        error = httpx.HTTPStatusError("HTTP Error", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status.side_effect = error
    else:
        mock_response.raise_for_status.return_value = None

    return mock_response


class TestHTTPClientGet:
    """Test HTTP GET operations."""

    @pytest.mark.asyncio
    async def test_get_success(self, mock_httpx_client):
        """Test successful GET request."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"result": "success"}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/test/",
            token="test-token"
        )

        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_get_with_params(self, mock_httpx_client):
        """Test GET request with query parameters."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"results": []}
        )
        mock_httpx_client.request.return_value = mock_response

        params = {"page": 1, "page_size": 20}
        result = await http_client.get(
            region="us1",
            workspace="testworkspace",
            endpoint="/api/test/",
            token="test-token",
            params=params
        )

        assert result == {"results": []}

    @pytest.mark.asyncio
    async def test_get_404_error(self, mock_httpx_client):
        """Test GET request with 404 error."""
        mock_response = create_mock_response(status_code=404)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/notfound/",
            token="test-token"
        )

        assert result["error"] == "HTTP Error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_get_500_error(self, mock_httpx_client):
        """Test GET request with 500 error (should retry and then fail)."""
        mock_response = create_mock_response(status_code=500)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/error/",
            token="test-token"
        )

        assert result["error"] == "Max retries exceeded"
        # Should have retried 3 times
        assert mock_httpx_client.request.call_count == 3


class TestHTTPClientPost:
    """Test HTTP POST operations."""

    @pytest.mark.asyncio
    async def test_post_success(self, mock_httpx_client):
        """Test successful POST request."""
        mock_response = create_mock_response(
            status_code=201,
            json_data={"id": 123, "created": True}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.post(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/create/",
            token="test-token",
            data={"name": "test"}
        )

        assert result == {"id": 123, "created": True}

    @pytest.mark.asyncio
    async def test_post_validation_error(self, mock_httpx_client):
        """Test POST request with validation error."""
        mock_response = create_mock_response(status_code=400)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.post(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/create/",
            token="test-token",
            data={"invalid": "data"}
        )

        assert result["error"] == "HTTP Error"
        assert result["status_code"] == 400


class TestHTTPClientPatch:
    """Test HTTP PATCH operations."""

    @pytest.mark.asyncio
    async def test_patch_success(self, mock_httpx_client):
        """Test successful PATCH request."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"updated": True}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.patch(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/update/123/",
            token="test-token",
            data={"name": "updated"}
        )

        assert result == {"updated": True}


class TestHTTPClientDelete:
    """Test HTTP DELETE operations."""

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_httpx_client):
        """Test successful DELETE request (no content)."""
        mock_response = create_mock_response(status_code=204, text_data="")
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.delete(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/delete/123/",
            token="test-token"
        )

        assert result == {"status": "success", "status_code": 204}

    @pytest.mark.asyncio
    async def test_delete_with_response(self, mock_httpx_client):
        """Test DELETE request with response body."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"deleted": True, "id": 123}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.delete(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/delete/123/",
            token="test-token"
        )

        assert result == {"deleted": True, "id": 123}


class TestURLConstruction:
    """Test URL construction for different regions."""

    @pytest.mark.asyncio
    async def test_url_construction_all_regions(self, mock_httpx_client):
        """Test URL construction for all supported regions."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"region": "test"}
        )
        mock_httpx_client.request.return_value = mock_response

        regions = ["ap1", "us1", "eu1"]
        for region in regions:
            await http_client.get(
                region=region,
                workspace="testworkspace",
                endpoint="/api/test/",
                token="test-token"
            )

        # Verify URLs were constructed correctly
        calls = mock_httpx_client.request.call_args_list
        expected_urls = [
            "https://testworkspace.ap1.alpacon.io/api/test/",
            "https://testworkspace.us1.alpacon.io/api/test/",
            "https://testworkspace.eu1.alpacon.io/api/test/"
        ]
        for i, expected_url in enumerate(expected_urls):
            assert calls[i][1]["url"] == expected_url


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_network_timeout(self, mock_httpx_client):
        """Test network timeout handling."""
        mock_httpx_client.request.side_effect = httpx.TimeoutException("Request timeout")

        result = await http_client.get(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/test/",
            token="test-token"
        )

        assert result["error"] == "Timeout"

    @pytest.mark.asyncio
    async def test_connection_error(self, mock_httpx_client):
        """Test connection error handling."""
        mock_httpx_client.request.side_effect = httpx.ConnectError("Connection failed")

        result = await http_client.get(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/test/",
            token="test-token"
        )

        assert result["error"] == "Request Error"

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_httpx_client):
        """Test handling of invalid JSON response."""
        # Create a response that will cause json() to fail
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.content = b"invalid json response"
        mock_response.text = "invalid json response"
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = Exception("JSON decode error")

        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/test/",
            token="test-token"
        )

        assert result["error"] == "Unexpected Error"