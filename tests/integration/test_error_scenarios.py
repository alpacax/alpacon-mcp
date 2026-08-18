"""Integration tests for error scenarios.

Tests error handling through the full request path: timeout after retries,
malformed JSON, empty body, connection errors, and various HTTP status codes.
"""

from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

from tools.server_tools import list_servers
from utils.http_client import http_client

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestTimeoutScenarios:
    """Test timeout handling through the full path."""

    async def test_timeout_after_retries(self, patched_http_client, no_sleep):
        """Timeout on every attempt exhausts retries and returns timeout error."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout('Read timed out')

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 3
        assert result['error'] == 'Timeout'
        assert 'timed out' in result['message']


class TestMalformedResponses:
    """Test handling of malformed or unexpected responses."""

    async def test_malformed_json_response(self, patched_http_client):
        """Response with invalid JSON body returns unexpected error."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Return a response with a 200 status but content that will fail json()
            # httpx.Response with text content that is not valid JSON
            return httpx.Response(
                HTTPStatus.OK,
                content=b'this is not valid json {{{',
                headers={'content-type': 'text/plain'},
            )

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        # The response has text content, so response.text is truthy,
        # and response.json() will raise an exception caught by the
        # generic except handler
        assert result['error'] == 'Unexpected Error'

    async def test_empty_body_response(self, patched_http_client):
        """Response with empty body returns status-only success dict."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(HTTPStatus.NO_CONTENT, content=b'')

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='DELETE',
            url='https://test.ap1.alpacon.io/api/test/123/',
            token='test-token',
        )

        assert result['status'] == 'success'
        assert result['status_code'] == HTTPStatus.NO_CONTENT


class TestConnectionErrors:
    """Test connection error handling."""

    async def test_connect_error_retried_then_fails(
        self, patched_http_client, no_sleep
    ):
        """ConnectError triggers retries and eventually returns error."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError('Connection refused')

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 3
        assert result['error'] == 'Request Error'
        assert 'Connection refused' in result['message']


class TestHTTPStatusErrorHandling:
    """Test specific HTTP status code handling."""

    async def test_400_returns_error_not_retried(self, patched_http_client, no_sleep):
        """400 Bad Request returns error without retry."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                HTTPStatus.BAD_REQUEST,
                json={'detail': 'Invalid input', 'field': 'name'},
            )

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='POST',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
            json_data={'name': ''},
        )

        assert call_count == 1
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.BAD_REQUEST

    async def test_403_returns_error_not_retried(self, patched_http_client, no_sleep):
        """403 Forbidden returns error without retry."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                HTTPStatus.FORBIDDEN, json={'detail': 'Permission denied'}
            )

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 1
        assert result['error'] == 'HTTP Error'
        assert result['status_code'] == HTTPStatus.FORBIDDEN

    async def test_500_retry_with_eventual_success(self, patched_http_client, no_sleep):
        """500 errors are retried and succeed if server recovers."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(
                    HTTPStatus.INTERNAL_SERVER_ERROR, json={'error': 'Internal Error'}
                )
            return httpx.Response(HTTPStatus.OK, json={'recovered': True})

        patched_http_client.set_handler(handler)

        result = await http_client.request(
            method='GET',
            url='https://test.ap1.alpacon.io/api/test/',
            token='test-token',
        )

        assert call_count == 3
        assert result == {'recovered': True}

    async def test_tool_level_http_error_handling(self, patched_http_client, no_sleep):
        """Tool function correctly interprets http_client error dict."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(HTTPStatus.NOT_FOUND, json={'detail': 'Not found'})

        patched_http_client.set_handler(handler)

        with patch('utils.common.token_manager') as mock_tm:
            mock_tm.get_token.return_value = 'test-token'
            result = await list_servers(workspace='production', region='ap1')

        # http_client returns {'error': 'HTTP Error', ...}
        # list_servers checks for 'error' key and converts to error_response
        assert result['status'] == 'error'
