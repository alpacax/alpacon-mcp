"""The agent's clientInfo reaches alpacon-server as two headers (#317)."""

from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import h11
import pytest
from mcp.client.client import Client
from mcp.server import MCPServer
from mcp.types import Implementation

import server as server_module
import tools.resources as resources_module
import utils.declared_agent as declared_agent_module
from tests.test_http_client import (  # noqa: F401  (fixture)
    create_mock_response,
    mock_httpx_client,
)
from utils.agent_environment import VARIABLES, agent_from_environment
from utils.declared_agent import (
    DECLARED_AGENT_NAME_HEADER,
    DECLARED_AGENT_VERSION_HEADER,
    capture_declared_agent,
    declared_agent_headers,
)
from utils.http_client import http_client

# Signals a person meets every day; none of them names an agent.
NEVER_AN_AGENT = ('CLAUDECODE', 'CI', 'TERM_PROGRAM', 'REPL_ID', 'GOOSE_PROVIDER')

CLAUDE_CODE = {
    DECLARED_AGENT_NAME_HEADER: 'claude-code',
    DECLARED_AGENT_VERSION_HEADER: '2.1.0',
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No marker from the shell running the tests, and the fallback off."""
    for variable in (*VARIABLES, *NEVER_AN_AGENT):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(declared_agent_module, '_environment_fallback', False)


@pytest.fixture
def stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(declared_agent_module, '_environment_fallback', True)


def _no_client_info() -> Any:
    return SimpleNamespace(session=SimpleNamespace(client_params=None))


def _ctx(name: str, version: str) -> Any:
    """A request context whose session carries this clientInfo."""
    info = Implementation(name=name, version=version)
    return SimpleNamespace(
        session=SimpleNamespace(client_params=SimpleNamespace(client_info=info))
    )


async def _headers_inside(ctx: Any) -> dict[str, str]:
    async def call_next(_: Any) -> dict[str, str]:
        return declared_agent_headers()

    result = await capture_declared_agent(ctx, call_next)
    assert isinstance(result, dict)
    return result


class TestCapture:
    @pytest.mark.asyncio
    @pytest.mark.parametrize('mode', ['legacy', 'auto'])
    async def test_a_tool_sees_the_client_info_on_either_protocol(
        self, mode: str
    ) -> None:
        """Through the SDK's own request path, handshake and per-request _meta."""
        probe = MCPServer('probe', middleware=[capture_declared_agent])

        @probe.tool()
        async def headers() -> dict[str, str]:
            return declared_agent_headers()

        info = Implementation(name='claude-code', version='2.1.0')
        async with Client(probe, client_info=info, mode=mode) as client:
            result = await client.call_tool('headers', {})

        assert result.structured_content == CLAUDE_CODE

    @pytest.mark.asyncio
    async def test_nothing_is_bound_outside_a_request(self) -> None:
        await _headers_inside(_ctx('claude-code', '2.1.0'))

        assert declared_agent_headers() == {}

    @pytest.mark.asyncio
    async def test_a_session_without_client_params_sends_nothing(self) -> None:
        assert await _headers_inside(_no_client_info()) == {}

    def test_the_server_registers_the_middleware(self) -> None:
        assert capture_declared_agent in server_module.mcp._lowlevel_server.middleware


class TestHeaderSafety:
    """A value that cannot travel as a header is left out, not sent broken."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize('bad', ['클로드', 'claude\ncode', 'claude\tcode', 'é'])
    async def test_an_unsafe_name_is_left_out(self, bad: str) -> None:
        assert await _headers_inside(_ctx(bad, '2.1.0')) == {
            DECLARED_AGENT_VERSION_HEADER: '2.1.0'
        }

    @pytest.mark.asyncio
    async def test_an_unsafe_version_is_left_out(self) -> None:
        assert await _headers_inside(_ctx('claude-code', '2.1\n0')) == {
            DECLARED_AGENT_NAME_HEADER: 'claude-code'
        }

    @pytest.mark.asyncio
    async def test_values_pass_through_unrewritten(self) -> None:
        """Composition and sanitization belong to the server: no ``/`` rewrite."""
        assert await _headers_inside(_ctx('acme/agent', '1.0/beta')) == {
            DECLARED_AGENT_NAME_HEADER: 'acme/agent',
            DECLARED_AGENT_VERSION_HEADER: '1.0/beta',
        }

    @pytest.mark.asyncio
    async def test_boundary_whitespace_is_trimmed(self) -> None:
        """h11 refuses a value that starts or ends with whitespace."""
        assert await _headers_inside(_ctx(' acme agent ', ' 1.0 ')) == {
            DECLARED_AGENT_NAME_HEADER: 'acme agent',
            DECLARED_AGENT_VERSION_HEADER: '1.0',
        }

    @pytest.mark.asyncio
    async def test_oversized_values_are_cut_to_the_server_limits(self) -> None:
        """The server would truncate them too, but only if the request reaches it.

        The limits are written out because they are alpacon-server's, not ours.
        """
        headers = await _headers_inside(_ctx('a' * 100_000, '1' * 100_000))
        assert headers == {
            DECLARED_AGENT_NAME_HEADER: 'a' * 64,
            DECLARED_AGENT_VERSION_HEADER: '1' * 32,
        }

    @pytest.mark.asyncio
    async def test_a_cut_that_lands_on_a_space_leaves_no_trailing_whitespace(
        self,
    ) -> None:
        headers = await _headers_inside(_ctx('a' * 63 + ' tail', '2.1.0'))
        assert headers[DECLARED_AGENT_NAME_HEADER] == 'a' * 63

    @pytest.mark.asyncio
    async def test_an_oversized_value_does_not_break_the_request(self) -> None:
        """The pinned h11 refuses a header block past 16 KiB on the receiving side."""
        headers = await _headers_inside(_ctx('a' * 100_000, '1' * 100_000))
        sender = h11.Connection(h11.CLIENT)
        data = sender.send(
            h11.Request(
                method='GET',
                target='/',
                headers=[('Host', 'x'), *headers.items()],
            )
        )
        receiver = h11.Connection(h11.SERVER)
        for start in range(0, len(data), 1024):
            receiver.receive_data(data[start : start + 1024])
            event = receiver.next_event()
            if event is not h11.NEED_DATA:
                break
        assert isinstance(event, h11.Request)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'name', ['claude-code', 'acme agent', ' acme ', 'acme/agent', '클로드', 'a\nb']
    )
    async def test_whatever_is_sent_is_a_header_h11_accepts(self, name: str) -> None:
        """End to end against the pinned h11, which the mocked client never reaches."""
        headers = await _headers_inside(_ctx(name, '2.1.0'))
        connection = h11.Connection(h11.CLIENT)
        connection.send(
            h11.Request(
                method='GET',
                target='/',
                headers=[('Host', 'x'), *headers.items()],
            )
        )


class TestHTTPClientForwards:
    @pytest.mark.asyncio
    async def test_both_headers_reach_the_request(self, mock_httpx_client) -> None:  # noqa: F811
        mock_httpx_client.request.return_value = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'result': 'ok'}
        )

        async def call_next(_: Any) -> None:
            await http_client.get(
                region='ap1', workspace='ws', endpoint='/api/test/', token='t'
            )

        await capture_declared_agent(_ctx('claude-code', '2.1.0'), call_next)

        sent = mock_httpx_client.request.call_args.kwargs['headers']
        assert sent[DECLARED_AGENT_NAME_HEADER] == 'claude-code'
        assert sent[DECLARED_AGENT_VERSION_HEADER] == '2.1.0'

    @pytest.mark.asyncio
    async def test_no_headers_outside_a_request(self, mock_httpx_client) -> None:  # noqa: F811
        mock_httpx_client.request.return_value = create_mock_response(
            status_code=HTTPStatus.OK, json_data={'result': 'ok'}
        )

        await http_client.get(
            region='ap1', workspace='ws', endpoint='/api/test/', token='t'
        )

        sent = mock_httpx_client.request.call_args.kwargs['headers']
        assert DECLARED_AGENT_NAME_HEADER not in sent
        assert DECLARED_AGENT_VERSION_HEADER not in sent


class TestEnvironmentFallback:
    """Over stdio, a client that sends no clientInfo is named by its markers."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    async def test_client_info_wins_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('AI_AGENT', 'codex/0.9.0')

        assert await _headers_inside(_ctx('claude-code', '2.1.0')) == CLAUDE_CODE

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    async def test_claude_codes_ai_agent_form_names_the_agent_and_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('AI_AGENT', 'claude-code_2-1-120_agent')

        assert await _headers_inside(_no_client_info()) == {
            DECLARED_AGENT_NAME_HEADER: 'claude-code',
            DECLARED_AGENT_VERSION_HEADER: '2.1.120',
        }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    async def test_a_marker_without_a_version_sends_no_version_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('CODEX_THREAD_ID', 'thread-1')

        assert await _headers_inside(_no_client_info()) == {
            DECLARED_AGENT_NAME_HEADER: 'codex'
        }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    async def test_a_client_info_with_an_empty_name_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('GEMINI_CLI', '1')

        assert await _headers_inside(_ctx(' ', '1.0')) == {
            DECLARED_AGENT_NAME_HEADER: 'gemini-cli'
        }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    async def test_oversized_values_are_cut_to_the_server_limits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('AI_AGENT', 'a' * 1000 + '/' + '1' * 1000)

        assert await _headers_inside(_no_client_info()) == {
            DECLARED_AGENT_NAME_HEADER: 'a' * 64,
            DECLARED_AGENT_VERSION_HEADER: '1' * 32,
        }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    @pytest.mark.parametrize(
        ('variable', 'value'),
        [
            ('CLAUDECODE', '1'),
            ('CI', 'true'),
            ('TERM_PROGRAM', 'vscode'),
            ('REPL_ID', 'repl-1'),
            ('GOOSE_PROVIDER', 'openai'),
            ('AGENT', 'amp'),
        ],
    )
    async def test_a_never_an_agent_signal_declares_nothing(
        self, monkeypatch: pytest.MonkeyPatch, variable: str, value: str
    ) -> None:
        monkeypatch.setenv(variable, value)

        assert await _headers_inside(_no_client_info()) == {}

    @pytest.mark.asyncio
    @pytest.mark.usefixtures('stdio')
    async def test_no_markers_declare_nothing(self) -> None:
        assert await _headers_inside(_no_client_info()) == {}

    @pytest.mark.asyncio
    async def test_http_transports_never_read_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('AI_AGENT', 'claude-code_2-1-120_agent')
        monkeypatch.setenv('CODEX_THREAD_ID', 'thread-1')

        assert await _headers_inside(_no_client_info()) == {}

    @pytest.mark.parametrize(
        ('transport', 'enabled'),
        [
            (server_module.TRANSPORT_STDIO, True),
            (server_module.TRANSPORT_SSE, False),
            (server_module.TRANSPORT_STREAMABLE_HTTP, False),
        ],
    )
    def test_only_stdio_turns_the_fallback_on(
        self, monkeypatch: pytest.MonkeyPatch, transport: Any, enabled: bool
    ) -> None:
        monkeypatch.setattr(server_module.importlib, 'import_module', lambda _: None)
        monkeypatch.setattr(resources_module, 'register_resources', lambda _: None)
        monkeypatch.setattr(
            server_module, '_register_http_health_endpoint', lambda: None
        )
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'restored-on-teardown')
        monkeypatch.delenv('ALPACON_MCP_AUTH_ENABLED', raising=False)
        monkeypatch.setattr(declared_agent_module, '_environment_fallback', not enabled)

        server_module.prepare(transport)

        assert declared_agent_module._environment_fallback is enabled


class TestAgentFromEnvironment:
    """The detection table the Alpacon CLI reads, row for row."""

    @pytest.mark.parametrize(
        ('variable', 'value', 'name'),
        [
            ('CLAUDE_CODE_CHILD_SESSION', '1', 'claude-code'),
            ('CODEX_CI', '1', 'codex'),
            ('CODEX_THREAD_ID', 'thread-1', 'codex'),
            ('CODEX_SANDBOX', 'seatbelt', 'codex'),
            ('GEMINI_CLI', '1', 'gemini-cli'),
            ('COPILOT_AGENT', '1', 'github-copilot'),
            ('COPILOT_CLI', '1', 'github-copilot'),
            ('CURSOR_AGENT', '1', 'cursor'),
            ('CLINE_ACTIVE', 'TRUE', 'cline'),
            ('GOOSE_TERMINAL', '1', 'goose'),
            ('AGENT', 'Goose', 'goose'),
        ],
    )
    def test_each_row_names_its_agent(
        self, variable: str, value: str, name: str
    ) -> None:
        assert agent_from_environment({variable: value}) == (name, '')

    @pytest.mark.parametrize(
        ('variable', 'value'),
        [
            ('CLAUDE_CODE_CHILD_SESSION', '0'),
            ('GEMINI_CLI', 'yes'),
            ('CLINE_ACTIVE', 'false'),
            ('CODEX_THREAD_ID', '  '),
        ],
    )
    def test_a_marker_with_another_value_names_nothing(
        self, variable: str, value: str
    ) -> None:
        assert agent_from_environment({variable: value}) is None

    @pytest.mark.parametrize(
        ('value', 'expected'),
        [
            ('claude-code', ('claude-code', '')),
            ('Claude-Code', ('claude-code', '')),
            ('claude-code_2-1-120_agent', ('claude-code', '2.1.120')),
            ('codex/0.9.0', ('codex', '0.9.0')),
            ('codex-mcp-client/1-2', ('codex', '1.2')),
            ('gemini-cli-mcp-client', ('gemini-cli', '')),
            ('github_copilot_vscode_agent', ('github-copilot', '')),
            ('github-copilot-cli', ('github-copilot', '')),
            ('my-agent', ('my-agent', '')),
            ('my-agent/1.0/beta', ('my-agent', '1.0/beta')),
            (' aider\n', ('aider', '')),
        ],
    )
    def test_ai_agent_forms(self, value: str, expected: tuple[str, str]) -> None:
        assert agent_from_environment({'AI_AGENT': value}) == expected

    @pytest.mark.parametrize('value', ['', '  ', '/1.0', '클로드'])
    def test_an_ai_agent_value_naming_nothing_falls_through_to_the_table(
        self, value: str
    ) -> None:
        assert agent_from_environment({'AI_AGENT': value}) is None
        assert agent_from_environment({'AI_AGENT': value, 'CURSOR_AGENT': '1'}) == (
            'cursor',
            '',
        )

    def test_ai_agent_is_read_before_the_table(self) -> None:
        environ = {'AI_AGENT': 'aider', 'CLAUDE_CODE_CHILD_SESSION': '1'}

        assert agent_from_environment(environ) == ('aider', '')

    def test_the_first_row_that_matches_names_the_agent(self) -> None:
        environ = {'CLAUDE_CODE_CHILD_SESSION': '1', 'CODEX_THREAD_ID': 'thread-1'}

        assert agent_from_environment(environ) == ('claude-code', '')
