"""Integration tests for the decorator chain.

Tests the full decorator stack: with_logging -> with_token_validation -> with_error_handling.
Uses MockTransport at the httpx transport layer so the real HTTP client code runs.
"""

import logging

import httpx
import pytest

from tools.server_tools import list_servers

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestDecoratorChainSuccess:
    """Test successful flow through the full decorator chain."""

    async def test_full_chain_success_flow(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        """Valid inputs through MockTransport 200 produce success_response."""
        api_data = sample_api_responses()
        servers_payload = api_data['servers_list']

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=servers_payload)

        patched_http_client.set_handler(handler)

        result = await list_servers(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == servers_payload
        assert result['data']['count'] == 2

    async def test_decorator_passes_token_to_function(
        self, patched_http_client, mock_token_for_integration
    ):
        """Token injected by with_token_validation reaches the HTTP request."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={'count': 0, 'results': []})

        patched_http_client.set_handler(handler)

        await list_servers(workspace='testworkspace', region='ap1')

        assert 'authorization' in captured_headers
        assert captured_headers['authorization'] == 'token=integration-test-token'


class TestTokenValidation:
    """Test token validation decorator rejects invalid inputs."""

    async def test_invalid_region_rejected(self, patched_http_client):
        """Invalid region format returns validation error before any HTTP call."""
        handler_called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal handler_called
            handler_called = True
            return httpx.Response(200, json={})

        patched_http_client.set_handler(handler)

        result = await list_servers(workspace='testworkspace', region='invalid-region')

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'region'
        assert not handler_called

    async def test_invalid_workspace_rejected(self, patched_http_client):
        """Invalid workspace format returns validation error."""
        result = await list_servers(workspace='!!!invalid!!!', region='ap1')

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'workspace'

    async def test_invalid_server_id_rejected(
        self, patched_http_client, mock_token_for_integration
    ):
        """Invalid server_id format returns validation error."""
        from tools.server_tools import get_server

        result = await get_server(
            server_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'server_id'

    async def test_missing_token_returns_token_error(self, patched_http_client):
        """Missing token (no token_manager configured) returns token error."""
        from unittest.mock import patch

        with patch('utils.common.token_manager') as mock_tm:
            mock_tm.get_token.return_value = None

            result = await list_servers(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestErrorHandlingDecorator:
    """Test that with_error_handling catches exceptions from HTTP layer."""

    async def test_http_exception_caught_by_error_handler(
        self, patched_http_client, mock_token_for_integration
    ):
        """Exception raised inside the tool function is caught by with_error_handling."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('Connection refused')

        patched_http_client.set_handler(handler)

        result = await list_servers(workspace='testworkspace', region='ap1')

        # The http_client.request() catches exceptions and returns error dicts,
        # then the tool function checks for 'error' key and returns error_response.
        assert result['status'] == 'error'


class TestLoggingDecorator:
    """Test that with_logging decorator logs entry and exit."""

    async def test_logging_logs_entry_and_success(
        self, patched_http_client, mock_token_for_integration, caplog
    ):
        """Logging decorator logs function entry and successful completion."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={'count': 0, 'results': []})

        patched_http_client.set_handler(handler)

        with caplog.at_level(logging.INFO):
            result = await list_servers(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'

        # Check that logging decorator recorded entry
        log_messages = [record.message for record in caplog.records]
        entry_logged = any('list_servers called with' in msg for msg in log_messages)
        success_logged = any(
            'list_servers completed successfully' in msg for msg in log_messages
        )

        assert entry_logged, f'Expected entry log, got: {log_messages}'
        assert success_logged, f'Expected success log, got: {log_messages}'

    async def test_logging_before_validation(self, patched_http_client, caplog):
        """Logging decorator runs before token validation (logs even for invalid inputs)."""
        with caplog.at_level(logging.INFO):
            result = await list_servers(workspace='testworkspace', region='invalid')

        assert result['status'] == 'error'

        # Logging should still record the function call even though validation fails
        log_messages = [record.message for record in caplog.records]
        entry_logged = any('list_servers called with' in msg for msg in log_messages)
        assert entry_logged, (
            f'Expected entry log even for invalid input, got: {log_messages}'
        )
