"""Integration tests for the decorator chain.

Tests the full decorator stack: with_logging -> with_token_validation -> with_error_handling.
Uses MockTransport at the httpx transport layer so the real HTTP client code runs.

The decorators' own contracts—the error shape, the exceptions that propagate,
the marker every registered tool carries—are unit-tested in
``tests/test_decorators.py``.
"""

import ast
import base64
import importlib
import inspect
import logging
from collections.abc import Callable
from http import HTTPStatus
from types import ModuleType
from unittest.mock import patch

import httpx
import pytest
from mcp.types import CallToolResult, InputRequiredResult

import utils.decorators as decorators
from server import ALL_TOOL_MODULES, ALWAYS_ON_MODULES, TOOLS_PACKAGE, mcp
from tools.approval_tools import request_sudo_policy
from tools.command_tools import execute_command
from tools.server_tools import get_server, list_servers
from tools.webftp_tools import webftp_upload_content

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SERVER_ID = '11111111-1111-1111-1111-111111111111'

# Base64 far past _MAX_LOGGED_VALUE_LEN: the shape #233 was reported as.
_OVERSIZED_PAYLOAD = base64.b64encode(b'\x00' * 65536).decode()

# Past _MAX_LOGGED_VALUE_LEN under a key the log keeps.
_LONG_ID = 'a' * 300

ToolPayload = dict[str, object]


def _entry_log(caplog, tool: str) -> str:
    """The tool's one ``called with`` line. Raises if it was never emitted."""
    return next(r.message for r in caplog.records if f'{tool} called with' in r.message)


async def _upload_to(remote_file_path: str) -> None:
    await webftp_upload_content(
        server_id=_SERVER_ID,
        file_content=_OVERSIZED_PAYLOAD,
        remote_file_path=remote_file_path,
        workspace='testworkspace',
        region='invalid',
    )


async def _upload_oversized_content() -> None:
    await _upload_to('/tmp/upload.bin')


async def _request_sudo_policy(
    commands: list[str], servers: list[str] | None = None
) -> None:
    await request_sudo_policy(
        workspace='testworkspace',
        servers=servers or [_SERVER_ID],
        commands=commands,
        reason='Before the deploy',
        region='invalid',
    )


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
    """Test that with_logging decorator logs entry and exit.

    Every test below that passes ``region='invalid'`` does so to stop the call
    right after the entry log, before any HTTP.
    """

    async def test_logging_logs_entry_and_success(
        self, patched_http_client, mock_token_for_integration, caplog
    ):
        """Entry log carries the call's arguments, never the token; success is logged."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(HTTPStatus.OK, json={'count': 0, 'results': []})

        patched_http_client.set_handler(handler)

        with caplog.at_level(logging.INFO):
            result = await list_servers(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'

        entry = _entry_log(caplog, 'list_servers')
        assert "'workspace': 'testworkspace'" in entry
        assert "'region': 'ap1'" in entry
        assert 'integration-test-token' not in entry
        assert 'kwargs' not in entry

        success_logged = any(
            'list_servers completed successfully' in record.message
            for record in caplog.records
        )
        assert success_logged

    async def test_logging_before_validation(self, caplog):
        """Logging runs before validation, so the rejected input is what gets logged."""
        with caplog.at_level(logging.INFO):
            result = await list_servers(workspace='testworkspace', region='invalid')

        assert result['status'] == 'error'

        entry = _entry_log(caplog, 'list_servers')
        assert "'region': 'invalid'" in entry

    async def test_logging_records_the_uploaded_payload_by_size(self, caplog):
        """The entry log never carries file_content, only its length (#233)."""
        with caplog.at_level(logging.INFO):
            await _upload_oversized_content()

        entry = _entry_log(caplog, 'webftp_upload_content')
        assert _OVERSIZED_PAYLOAD not in entry
        assert f"'file_content': '<str len={len(_OVERSIZED_PAYLOAD)}>'" in entry
        assert "'remote_file_path': '/tmp/upload.bin'" in entry
        assert len(entry) < 1024

    async def test_logging_bounds_a_long_verbatim_argument(self, caplog):
        """A value the log keeps records its length past the bound (#233)."""
        long_path = '/srv/' + 'a' * 300
        with caplog.at_level(logging.INFO):
            await _upload_to(long_path)

        entry = _entry_log(caplog, 'webftp_upload_content')
        assert long_path not in entry
        assert f"'remote_file_path': '<str len={len(long_path)}>'" in entry

    async def test_logging_skips_argument_work_when_info_disabled(self, caplog):
        """Below INFO, with_logging summarizes nothing and writes no entry (#233)."""
        with patch.object(
            decorators,
            '_log_arguments',
            wraps=decorators._log_arguments,
        ) as summarize:
            with caplog.at_level(logging.WARNING, logger='alpacon_mcp.decorators'):
                await _upload_oversized_content()

        assert summarize.call_count == 0
        assert not [
            r
            for r in caplog.records
            if 'webftp_upload_content called with' in r.message
        ]

    async def test_logging_records_free_text_and_env_by_size(self, caplog):
        """An argument outside the reviewed set keeps its key and loses its value."""
        with caplog.at_level(logging.INFO):
            await execute_command(
                server_id=_SERVER_ID,
                command='uptime',
                workspace='testworkspace',
                region='invalid',
                purpose='Check load before the deploy',
                data='stdin payload line',
                env={'DEPLOY_TOKEN': 'hunter2'},
            )

        entry = _entry_log(caplog, 'execute_command')

        assert "'purpose': '<str len=28>'" in entry
        assert "'data': '<str len=18>'" in entry
        assert "'env': '<dict items=1>'" in entry
        assert "'command': '<str len=6>'" in entry
        assert 'hunter2' not in entry
        assert 'DEPLOY_TOKEN' not in entry
        assert 'Check load' not in entry
        assert 'stdin payload' not in entry
        assert 'uptime' not in entry
        assert _SERVER_ID in entry

    async def test_logging_bounds_the_elements_of_a_container_argument(self, caplog):
        """A verbatim list is summarized element by element, not passed through (#233)."""
        with caplog.at_level(logging.INFO):
            await _request_sudo_policy(['uptime'], servers=[_SERVER_ID, _LONG_ID])

        entry = _entry_log(caplog, 'request_sudo_policy')

        assert _LONG_ID not in entry
        assert f'<str len={len(_LONG_ID)}>' in entry
        assert f"'{_SERVER_ID}'" in entry

    async def test_logging_replaces_an_oversized_container_with_its_item_count(
        self, caplog
    ):
        """Past the element bound the container itself becomes the placeholder (#233)."""
        servers = [f'{n:08d}-1111-1111-1111-111111111111' for n in range(50)]

        with caplog.at_level(logging.INFO):
            await _request_sudo_policy(['uptime'], servers=servers)

        entry = _entry_log(caplog, 'request_sudo_policy')

        assert "'servers': '<list items=50>'" in entry
        assert servers[49] not in entry


# Every shape of an inline credential the entry log used to keep whole.
_SECRET = 'S3cr3t-Pa55'
_SECRET_COMMANDS = (
    f'mysql -uroot -p{_SECRET} -e "select 1"',
    f'curl -H "Authorization: Bearer {_SECRET}" https://example.com/?k={_SECRET}',
    f'PGPASSWORD={_SECRET} psql -h db -c "select 1"',
)


class TestCredentialsStayOutOfLogs:
    """No log line at any level carries what a caller typed into a command (#311)."""

    @pytest.mark.parametrize('command', _SECRET_COMMANDS)
    async def test_execute_command_writes_no_part_of_the_command(
        self, patched_http_client, mock_token_for_integration, caplog, command
    ):
        """The upstream error echoes the command back, as a validation error can."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                HTTPStatus.BAD_REQUEST, json={'line': [f'Rejected: {command}']}
            )

        patched_http_client.set_handler(handler)

        with caplog.at_level(logging.DEBUG):
            await execute_command(
                server_id=_SERVER_ID,
                command=command,
                workspace='testworkspace',
                region='ap1',
                env={'DB_PASSWORD': _SECRET},
                data=_SECRET,
            )

        assert caplog.records
        assert _SECRET not in caplog.text
        entry = _entry_log(caplog, 'execute_command')
        assert f"'command': '<str len={len(command)}>'" in entry
        assert _SERVER_ID in entry

    async def test_a_command_list_is_recorded_by_size(self, caplog):
        with caplog.at_level(logging.DEBUG):
            await _request_sudo_policy(list(_SECRET_COMMANDS))

        assert _SECRET not in caplog.text
        entry = _entry_log(caplog, 'request_sudo_policy')
        assert "'commands': '<list items=3>'" in entry


def _tool_modules() -> list[ModuleType]:
    """Every toolset module, imported.

    Registration is an import-time side effect on the process-global ``mcp``,
    so this widens ``list_tools()`` for whatever test runs next.
    """
    return [
        importlib.import_module(f'{TOOLS_PACKAGE}.{module}')
        for module in sorted(ALL_TOOL_MODULES | ALWAYS_ON_MODULES)
    ]


def _tool_functions() -> dict[str, Callable]:
    """Every decorated tool on the surface, by name."""
    functions: dict[str, Callable] = {}
    for imported in _tool_modules():
        for name, attr in vars(imported).items():
            if inspect.iscoroutinefunction(attr) and hasattr(attr, '__wrapped__'):
                functions[name] = attr
    return functions


def _structured(result: CallToolResult | InputRequiredResult) -> ToolPayload:
    """Pull structured_content out of a CallToolResult, refusing anything else.

    SDK 2.x returns CallToolResult | InputRequiredResult where 1.x returned a
    2-tuple. A multi-round result here would mean the tool asked for input,
    which none of these tools do.
    """
    assert isinstance(result, CallToolResult), f'unexpected result type: {type(result)}'
    assert result.structured_content is not None, 'tool returned no structured content'
    return result.structured_content


class TestPublishedSchema:
    """Every test above awaits the coroutine directly and never reaches the
    pydantic validation the SDK puts in front of it. These go through ``mcp``.
    """

    async def test_no_tool_publishes_a_catch_all_parameter(self):
        functions = _tool_functions()
        tools = await mcp.list_tools()

        assert len(tools) >= len(functions), (
            f'registration looks broken: {len(tools)} tools for '
            f'{len(functions)} decorated functions'
        )
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
            published = catch_alls & set(tool.input_schema.get('properties', {}))
            if published:
                leaking[tool.name] = sorted(published)

        assert not leaking, (
            f'These publish the token-injection catch-all as a client-facing '
            f'field: {leaking}'
        )

    async def test_the_documented_arguments_survive_the_filter(self):
        _tool_functions()
        schemas = {t.name: t.input_schema for t in await mcp.list_tools()}

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

        structured = _structured(
            await mcp.call_tool(
                'list_servers', {'workspace': 'testworkspace', 'region': 'ap1'}
            )
        )
        assert structured['status'] == 'success'

        # The workaround the broken schema forced on clients still goes through:
        # The SDK's argument model leaves pydantic's extra='ignore' in place.
        with_workaround = _structured(
            await mcp.call_tool(
                'list_servers',
                {'workspace': 'testworkspace', 'region': 'ap1', 'kwargs': ''},
            )
        )
        assert with_workaround['status'] == 'success'

    async def test_call_tool_with_no_arguments(self):
        """The shape #211 was reported as: list_workspaces has no required field."""
        structured = _structured(await mcp.call_tool('list_workspaces', {}))

        assert structured['status'] == 'success'


class TestLoggedParameterSurface:
    """The entry log writes an argument's value only when its name is in
    ``_LOGGED_VERBATIM_KEYS``; every other argument keeps its key and is
    recorded by type and size, so a new parameter is safe until reviewed.
    """

    # Reviewed out of the verbatim set: a value here can carry a credential
    # or text a person wrote, and the log keeps its size alone (#311).
    NEVER_VERBATIM = frozenset(
        {
            'command',
            'commands',
            'search',
            'search_query',
            'token',
            'password',
            'secret',
            'key',
            'content',
            'data',
            'file_content',
            'description',
            'purpose',
            'reason',
            'requested_reason',
            'url',
            'front_url',
            'package_proxy',
            'email',
            'env',
            'args',
        }
    )

    @staticmethod
    def _declared_parameters() -> dict[str, set[str]]:
        """Every parameter on the tool surface, mapped to the tools declaring it."""
        declared: dict[str, set[str]] = {}
        for name, func in _tool_functions().items():
            for parameter in inspect.signature(
                inspect.unwrap(func)
            ).parameters.values():
                if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                    continue
                declared.setdefault(parameter.name, set()).add(name)
        return declared

    async def test_no_credential_bearing_name_is_verbatim(self):
        overlap = decorators._LOGGED_VERBATIM_KEYS & self.NEVER_VERBATIM
        assert not overlap, (
            f'These can carry a credential or free text and must be logged by '
            f'size: {sorted(overlap)}'
        )

    async def test_the_verbatim_set_is_current(self):
        stale = decorators._LOGGED_VERBATIM_KEYS - set(self._declared_parameters())
        assert not stale, (
            f'No tool declares these any more; drop them from '
            f'_LOGGED_VERBATIM_KEYS: {sorted(stale)}'
        )


class TestCatchAllForwarding:
    """``with_logging`` binds the published signature and so refuses a
    forwarded catch-all, but only while INFO is enabled. The rule that no tool
    forwards its own ``**kwargs`` into another tool—the catch-all holds the
    resolved credential (#211)—is pinned here instead, independently of the
    log level.
    """

    async def test_no_tool_forwards_its_catch_all_to_another_tool(self):
        tool_names = set(_tool_functions())

        offenders = set()
        for imported in _tool_modules():
            tree = ast.parse(inspect.getsource(imported))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                catch_all = node.args.kwarg
                if catch_all is None:
                    continue
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call):
                        continue
                    callee = getattr(call.func, 'id', None) or getattr(
                        call.func, 'attr', None
                    )
                    if callee not in tool_names:
                        continue
                    if any(
                        keyword.arg is None
                        and isinstance(keyword.value, ast.Name)
                        and keyword.value.id == catch_all.arg
                        for keyword in call.keywords
                    ):
                        offenders.add(
                            f'{imported.__name__}.{node.name} -> {callee} '
                            f'(line {call.lineno})'
                        )

        assert not offenders, (
            f'These forward their own catch-all, which holds the resolved '
            f'credential, into another tool: {sorted(offenders)}'
        )
