"""tools/list drops MCP App tools for a client that declared no MCP Apps support."""

import pytest
from mcp.client import Client, advertise
from mcp.server import MCPServer
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

import server as server_module
from tests.conftest import request_context
from utils.ui_tools import hide_ui_tools


def _probe_server() -> MCPServer[None]:
    probe = MCPServer('probe', middleware=[hide_ui_tools])

    @probe.tool(meta={'ui': {'resourceUri': 'ui://probe'}})
    async def ui_tool() -> str:
        return 'ui'

    @probe.tool(meta={'anthropic/searchHint': 'plain'})
    async def plain() -> str:
        return 'plain'

    return probe


def test_only_the_remote_server_filters_tools_list():
    assert hide_ui_tools in server_module.REMOTE_MIDDLEWARE
    assert hide_ui_tools not in server_module.SERVER_MIDDLEWARE


class TestToolsList:
    """Through the SDK's own request path, handshake and per-request capabilities."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize('mode', ['legacy', 'auto'])
    async def test_client_without_mcp_apps_does_not_see_ui_bound_tools(self, mode):
        async with Client(_probe_server(), mode=mode) as client:
            listing = await client.list_tools()

        assert [t.name for t in listing.tools] == ['plain']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('mode', ['legacy', 'auto'])
    async def test_client_rendering_mcp_apps_sees_every_tool(self, mode):
        apps = advertise(EXTENSION_ID, {'mimeTypes': [APP_MIME_TYPE]})

        async with Client(_probe_server(), mode=mode, extensions=[apps]) as client:
            listing = await client.list_tools()

        assert sorted(t.name for t in listing.tools) == ['plain', 'ui_tool']


@pytest.mark.asyncio
async def test_client_of_unknown_support_sees_every_tool():
    # No in-process client sends a stateless pre-2026 request, so the wire dict is built.
    listing: dict[str, object] = {'tools': [{'name': 'ui_tool', '_meta': {'ui': {}}}]}

    async def call_next(_: object) -> dict[str, object]:
        return listing

    result = await hide_ui_tools(request_context('tools/list', None), call_next)

    assert result == listing
