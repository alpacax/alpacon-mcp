"""
Unit tests for HTTP client utility.

Tests the HTTP client functionality including GET, POST, PATCH, DELETE operations
and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from utils.http_client import AlpaconHTTPClient, http_client


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


def create_mock_response(status_code=200, json_data=None, text_data='', headers=None):
    """Create a properly configured mock response."""
    # Use MagicMock instead of AsyncMock for response to avoid coroutine issues
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    mock_response.content = text_data.encode() if text_data else b''

    if json_data is not None:
        mock_response.json.return_value = json_data
        # Set text to string representation that won't be empty
        mock_response.text = 'mock response text'
    else:
        mock_response.json.return_value = {}
        mock_response.text = ''

    # Mock raise_for_status to raise HTTPStatusError for error codes
    if status_code >= 400:
        error = httpx.HTTPStatusError(
            'HTTP Error', request=MagicMock(), response=mock_response
        )
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
            status_code=200, json_data={'result': 'success'}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert result == {'result': 'success'}

    @pytest.mark.asyncio
    async def test_get_with_params(self, mock_httpx_client):
        """Test GET request with query parameters."""
        mock_response = create_mock_response(status_code=200, json_data={'results': []})
        mock_httpx_client.request.return_value = mock_response

        params = {'page': 1, 'page_size': 20}
        result = await http_client.get(
            region='us1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
            params=params,
        )

        assert result == {'results': []}

    @pytest.mark.asyncio
    async def test_get_404_error(self, mock_httpx_client):
        """Test GET request with 404 error."""
        mock_response = create_mock_response(status_code=404)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/notfound/',
            token='test-token',
        )

        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == 404

    @pytest.mark.asyncio
    async def test_get_500_error(self, mock_httpx_client):
        """Test GET request with 500 error (should retry and then fail)."""
        mock_response = create_mock_response(status_code=500)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/error/',
            token='test-token',
        )

        assert result['error'] == 'Max retries exceeded'
        # Should have retried 3 times
        assert mock_httpx_client.request.call_count == 3


class TestHTTPClientPost:
    """Test HTTP POST operations."""

    @pytest.mark.asyncio
    async def test_post_success(self, mock_httpx_client):
        """Test successful POST request."""
        mock_response = create_mock_response(
            status_code=201, json_data={'id': 123, 'created': True}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.post(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/create/',
            token='test-token',
            data={'name': 'test'},
        )

        assert result == {'id': 123, 'created': True}

    @pytest.mark.asyncio
    async def test_post_validation_error(self, mock_httpx_client):
        """Test POST request with validation error."""
        mock_response = create_mock_response(status_code=400)
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.post(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/create/',
            token='test-token',
            data={'invalid': 'data'},
        )

        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == 400


class TestHTTPClientPatch:
    """Test HTTP PATCH operations."""

    @pytest.mark.asyncio
    async def test_patch_success(self, mock_httpx_client):
        """Test successful PATCH request."""
        mock_response = create_mock_response(
            status_code=200, json_data={'updated': True}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.patch(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/update/123/',
            token='test-token',
            data={'name': 'updated'},
        )

        assert result == {'updated': True}


class TestHTTPClientDelete:
    """Test HTTP DELETE operations."""

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_httpx_client):
        """Test successful DELETE request (no content)."""
        mock_response = create_mock_response(status_code=204, text_data='')
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.delete(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/delete/123/',
            token='test-token',
        )

        assert result == {'status': 'success', 'status_code': 204}

    @pytest.mark.asyncio
    async def test_delete_with_response(self, mock_httpx_client):
        """Test DELETE request with response body."""
        mock_response = create_mock_response(
            status_code=200, json_data={'deleted': True, 'id': 123}
        )
        mock_httpx_client.request.return_value = mock_response

        result = await http_client.delete(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/delete/123/',
            token='test-token',
        )

        assert result == {'deleted': True, 'id': 123}


class TestURLConstruction:
    """Test URL construction for different regions."""

    @pytest.mark.asyncio
    async def test_url_construction_all_regions(self, mock_httpx_client):
        """Test URL construction for all supported regions."""
        mock_response = create_mock_response(
            status_code=200, json_data={'region': 'test'}
        )
        mock_httpx_client.request.return_value = mock_response

        regions = ['ap1', 'us1', 'eu1']
        for region in regions:
            await http_client.get(
                region=region,
                workspace='testworkspace',
                endpoint='/api/test/',
                token='test-token',
            )

        # Verify URLs were constructed correctly
        calls = mock_httpx_client.request.call_args_list
        expected_urls = [
            'https://testworkspace.ap1.alpacon.io/api/test/',
            'https://testworkspace.us1.alpacon.io/api/test/',
            'https://testworkspace.eu1.alpacon.io/api/test/',
        ]
        for i, expected_url in enumerate(expected_urls):
            assert calls[i][1]['url'] == expected_url


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_network_timeout(self, mock_httpx_client):
        """Test network timeout handling."""
        mock_httpx_client.request.side_effect = httpx.TimeoutException(
            'Request timeout'
        )

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert result['error'] == 'Timeout'

    @pytest.mark.asyncio
    async def test_connection_error(self, mock_httpx_client):
        """Test connection error handling."""
        mock_httpx_client.request.side_effect = httpx.ConnectError('Connection failed')

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert result['error'] == 'Request Error'

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_httpx_client):
        """Test handling of invalid JSON response."""
        # Create a response that will cause json() to fail
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.content = b'invalid json response'
        mock_response.text = 'invalid json response'
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = Exception('JSON decode error')

        mock_httpx_client.request.return_value = mock_response

        result = await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token='test-token',
        )

        assert result['error'] == 'Unexpected Error'


class TestHTTPClientJWTAuth:
    """Test JWT vs API token authentication header selection."""

    @pytest.mark.asyncio
    async def test_jwt_token_uses_bearer_header(self, mock_httpx_client):
        """Test that JWT-like tokens use Bearer authorization header."""
        mock_response = create_mock_response(
            status_code=200, json_data={'result': 'success'}
        )
        mock_httpx_client.request.return_value = mock_response

        # JWT tokens have 3 dot-separated parts (header.payload.signature)
        jwt_token = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature'

        await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token=jwt_token,
        )

        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs.kwargs['headers']['Authorization'] == f'Bearer {jwt_token}'

    @pytest.mark.asyncio
    async def test_api_token_uses_token_header(self, mock_httpx_client):
        """Test that API tokens use token= authorization header."""
        mock_response = create_mock_response(
            status_code=200, json_data={'result': 'success'}
        )
        mock_httpx_client.request.return_value = mock_response

        api_token = 'alpacon-api-token-abc123'

        await http_client.get(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/test/',
            token=api_token,
        )

        call_kwargs = mock_httpx_client.request.call_args
        assert call_kwargs.kwargs['headers']['Authorization'] == f'token={api_token}'

    def test_is_jwt_detection(self):
        """Test JWT format detection logic."""
        from utils.http_client import AlpaconHTTPClient

        assert AlpaconHTTPClient._is_jwt('a.b.c') is True
        assert AlpaconHTTPClient._is_jwt('eyJ.eyJ.sig') is True
        assert AlpaconHTTPClient._is_jwt('simple-token') is False
        assert AlpaconHTTPClient._is_jwt('two.parts') is False
        assert AlpaconHTTPClient._is_jwt('a..c') is False


class TestHandleUpstream401:
    """Test _handle_upstream_401 MFA detection and flag signaling."""

    def _make_401_exc(self, json_body=None, text=''):
        """Create a mock HTTPStatusError with 401 response."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = text or str(json_body)
        if json_body is not None:
            mock_response.json.return_value = json_body
        else:
            mock_response.json.side_effect = Exception('No JSON')
        exc = httpx.HTTPStatusError(
            'HTTP 401',
            request=MagicMock(),
            response=mock_response,
        )
        return exc

    def test_mfa_required_detection(self):
        """Detects auth_mfa_required code from response body."""
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is True
        assert result['status_code'] == 401
        assert result['error'] == 'MFA Required'

    def test_non_mfa_401(self):
        """Regular 401 without MFA code."""
        exc = self._make_401_exc({'detail': 'Unauthorized'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is False
        assert result['error'] == 'HTTP Error'

    def test_non_json_body(self):
        """Handles non-JSON 401 response gracefully."""
        exc = self._make_401_exc(json_body=None, text='Unauthorized')
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert result['mfa_required'] is False
        assert result['status_code'] == 401

    def test_no_response_body_in_result(self):
        """Error dict should NOT contain raw response body (PII protection)."""
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        result = AlpaconHTTPClient._handle_upstream_401(exc)
        assert 'response' not in result

    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'true'})
    def test_sets_flag_in_remote_mode(self):
        """Sets upstream_auth_error_flag when auth is enabled."""
        from utils.error_handler import upstream_auth_error_flag

        upstream_auth_error_flag.set(None)
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        AlpaconHTTPClient._handle_upstream_401(exc)

        flag = upstream_auth_error_flag.get()
        assert flag is not None
        assert flag['mfa_required'] is True
        assert flag['source'] == 'websh'

    @patch.dict('os.environ', {'ALPACON_MCP_AUTH_ENABLED': 'false'})
    def test_no_flag_in_stdio_mode(self):
        """Does NOT set flag when auth is disabled (stdio mode)."""
        from utils.error_handler import upstream_auth_error_flag

        upstream_auth_error_flag.set(None)
        exc = self._make_401_exc({'code': 'auth_mfa_required', 'source': 'websh'})
        AlpaconHTTPClient._handle_upstream_401(exc)

        flag = upstream_auth_error_flag.get()
        assert flag is None
