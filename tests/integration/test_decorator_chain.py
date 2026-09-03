"""Integration tests for the decorator chain.

Tests the full decorator stack: with_logging -> with_token_validation -> with_error_handling.
Uses MockTransport at the httpx transport layer so the real HTTP client code runs.
"""

import importlib
import inspect
import logging
from collections.abc import Callable
from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

from server import ALL_TOOL_MODULES, ALWAYS_ON_MODULES, TOOLS_PACKAGE, mcp
from tools.server_tools import get_server, list_servers

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
            return httpx.Response(HTTPStatus.OK, json=servers_payload)

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
            return httpx.Response(HTTPStatus.OK, json={'count': 0, 'results': []})

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
            return httpx.Response(HTTPStatus.OK, json={})

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
        result = await get_server(
            server_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'server_id'

    async def test_missing_token_returns_token_error(self, patched_http_client):
        """Missing token (no token_manager configured) returns token error."""
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
        """ConnectError from http_client is returned as error dict, which the tool converts to error_response."""

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
            return httpx.Response(HTTPStatus.OK, json={'count': 0, 'results': []})

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


class TestPublishedSchema:
    """Every test above awaits the coroutine directly and never reaches the
    pydantic validation FastMCP puts in front of it. These go through ``mcp``.
    """

    @staticmethod
    def _tool_functions() -> dict[str, Callable]:
        """Import every toolset and return the decorated tools by name.

        Registration is an import-time side effect on the process-global ``mcp``,
        so this widens ``list_tools()`` for whatever test runs next.
        """
        functions: dict[str, Callable] = {}
        for module in sorted(ALL_TOOL_MODULES | ALWAYS_ON_MODULES):
            imported = importlib.import_module(f'{TOOLS_PACKAGE}.{module}')
            for name, attr in vars(imported).items():
                if inspect.iscoroutinefunction(attr) and hasattr(attr, '__wrapped__'):
                    functions[name] = attr
        return functions

    async def test_no_tool_publishes_a_catch_all_parameter(self):
        functions = self._tool_functions()
        tools = await mcp.list_tools()

        assert len(tools) > 100, f'registration looks broken: {len(tools)} tools'
        unresolved = sorted(t.name for t in tools if t.name not in functions)
        assert not unresolved, f'no backing function found for: {unresolved}'

        leaking = {}
        for tool in tools:
            signature = inspect.signature(inspect.unwrap(functions[tool.name]))
            catch_alls = {
                p.name
                for p in signature.parameters.values()
                if p.kind is inspect.Parameter.VAR_KEYWORD
            }
            published = catch_alls & set(tool.inputSchema.get('properties', {}))
            if published:
                leaking[tool.name] = sorted(published)

        assert not leaking, (
            f'These publish the token-injection catch-all as a client-facing '
            f'field: {leaking}'
        )

    async def test_the_documented_arguments_survive_the_filter(self):
        self._tool_functions()
        schemas = {t.name: t.inputSchema for t in await mcp.list_tools()}

        assert set(schemas['list_servers']['properties']) == {
            'workspace',
            'region',
            'page',
            'page_size',
        }
        assert schemas['list_servers']['required'] == ['workspace']
        # kwargs was the only required field list_workspaces had, so the whole
        # key is gone from its schema rather than just the one entry.
        assert set(schemas['list_workspaces']['properties']) == {'region'}
        assert 'required' not in schemas['list_workspaces']

    async def test_call_tool_takes_the_documented_arguments_alone(
        self, patched_http_client, mock_token_for_integration, sample_api_responses
    ):
        servers_payload = sample_api_responses()['servers_list']

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(HTTPStatus.OK, json=servers_payload)

        patched_http_client.set_handler(handler)

        _, structured = await mcp.call_tool(
            'list_servers', {'workspace': 'testworkspace', 'region': 'ap1'}
        )
        assert structured['status'] == 'success'

        # The workaround the broken schema forced on clients still goes through:
        # FastMCP's argument model leaves pydantic's extra='ignore' in place.
        _, with_workaround = await mcp.call_tool(
            'list_servers',
            {'workspace': 'testworkspace', 'region': 'ap1', 'kwargs': ''},
        )
        assert with_workaround['status'] == 'success'

    async def test_call_tool_with_no_arguments(self):
        """The shape #211 was reported as: list_workspaces has no required field."""
        _, structured = await mcp.call_tool('list_workspaces', {})

        assert structured['status'] == 'success'
