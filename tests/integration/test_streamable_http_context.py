"""Prove the ContextVar token survives the streamable-http task machinery.

utils/http_client.py:643 documents ContextVar writes being invisible across
the anyio task boundary between tool handlers and the ASGI middleware. Here
both the write (decorator) and the read (tool body) sit inside the handler
coroutine chain; this test is the go/no-go gate for that assumption, and so
for every later PR of #86 that reads the token from this store.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from utils.auth_context import current_token
from utils.decorators import mcp_tool_handler

PROBE_TOOL = '_probe_auth_context'

# FastMCP exposes the tools' **kwargs as a required schema field (every real
# tool carries it too), so the call has to supply it.
_PROBE_ARGS = {'workspace': 'testws', 'region': 'ap1', 'kwargs': ''}

# DNS-rebinding guard: the Host header has to be a loopback name carrying a port
# ('127.0.0.1:*'), so httpx's default 'testserver' host earns a 421. The port is
# arbitrary and only mirrors the server default.
_BASE_URL = 'http://127.0.0.1:8237'


@pytest.fixture(autouse=True)
def no_sleep() -> Iterator[None]:
    """Override the package-wide fixture: it patches asyncio.sleep globally.

    Its replacement never awaits, so the client and server loops below never
    yield to each other and the handshake spins instead of completing.
    """
    yield


@pytest.mark.asyncio
async def test_context_token_visible_inside_streamable_http_handler(
    monkeypatch, mock_token_for_integration
) -> None:
    monkeypatch.setenv('ALPACON_MCP_AUTH_ENABLED', 'false')

    from server import mcp

    @mcp_tool_handler(description='Probe: report the token seen inside the body.')
    async def _probe_auth_context(workspace: str, region: str = '', **kwargs):
        return {
            'status': 'success',
            'data': {
                'context_token': current_token(),
                'kwargs_token': kwargs.get('token'),
            },
        }

    try:
        app = mcp.streamable_http_app()
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=_BASE_URL
        )

        # ASGITransport does not drive lifespan; run it by hand so the
        # StreamableHTTPSessionManager task group exists.
        async with app.router.lifespan_context(app):
            async with streamable_http_client(
                f'{_BASE_URL}/mcp', http_client=http_client
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(PROBE_TOOL, _PROBE_ARGS)
    finally:
        # The probe registered itself on the module-global server; remove it
        # so tool-listing tests are unaffected.
        mcp._tool_manager._tools.pop(PROBE_TOOL, None)

    content = result.content[0]
    assert isinstance(content, TextContent)
    payload = json.loads(content.text)
    assert payload['data']['context_token'] == 'integration-test-token'
    assert payload['data']['kwargs_token'] == 'integration-test-token'
