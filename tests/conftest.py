"""Shared fixtures for all tests.
Autouse fixtures keep tests off the real TokenManager and its token.json.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server import create_streamable_http_app, mcp
from utils import request_signal
from utils.http_client import AlpaconHTTPClient

# The AlpaconHTTPClient methods a tool calls.
HTTP_VERBS = ('get', 'post', 'put', 'patch', 'delete')

# Canonical http_client error envelope (the shape utils/http_client returns on
# 4xx/5xx). Shared across error-path tests so the envelope is defined once.
HTTP_ERROR_ENVELOPE = {
    'error': 'HTTP Error',
    'status_code': HTTPStatus.NOT_FOUND,
    'message': 'Not found',
}

# Any well-formed UUID: a public tool's decorator rejects any other server_id.
VALID_SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'


@asynccontextmanager
async def streamable_http_client(
    host: str = '0.0.0.0',  # noqa: S104
) -> AsyncIterator[httpx.AsyncClient]:
    """Drive the streamable-http app's own ASGI lifespan, which is what
    initializes the session manager's task group."""
    app = create_streamable_http_app(host=host)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            yield client


async def tool_descriptions() -> dict[str, str]:
    """Every registered tool's description, by name; each must be set."""
    tools = await mcp.list_tools()
    descriptions = {t.name: t.description for t in tools if t.description}
    if len(descriptions) != len(tools):
        raise AssertionError('a tool is registered without a description')
    return descriptions


@pytest.fixture(autouse=True)
def _reset_request_signal():
    """A sync test's begin_request() call sets the ContextVar in the main
    thread, which then leaks into the next test unless reverted here."""
    request_signal.end_request()
    yield
    request_signal.end_request()


def http_client_fixture(module_name: str):
    """Build a `mock_http_client` fixture patching the tool module's `http_client`."""

    @pytest.fixture
    def _mock_http_client():
        mock_client = MagicMock()
        for verb in HTTP_VERBS:  # patch() alone leaves these un-awaitable
            setattr(mock_client, verb, AsyncMock())
        # The host-transfer waits poll through their own module's reference.
        with (
            patch(f'{module_name}.http_client', mock_client),
            patch('utils.host_transfer.http_client', mock_client),
        ):
            yield mock_client

    return _mock_http_client


class FakeClock:
    """A monotonic clock that moves only when the host-transfer waits sleep."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock():
    clock = FakeClock()
    with (
        patch('utils.host_transfer.monotonic', clock.monotonic),
        patch('utils.host_transfer.sleep', clock.sleep),
    ):
        yield clock


@pytest.fixture
def mock_token_manager():
    """Mock token manager so tests never read a real ~/.alpacon-mcp/token.json."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


@pytest.fixture(autouse=True)
def mock_region_auto_detect():
    """Keep _resolve_region_local off the real token.json when a test omits region.
    A test needing its own get_token_manager behavior patches it over this one.
    """
    mock_tm = MagicMock()
    mock_tm.find_region_for_workspace.return_value = 'ap1'
    mock_tm.get_default_region.return_value = 'ap1'
    mock_tm.get_available_regions.return_value = ['ap1']
    # No pinned host override by default: http_client.get_base_url derives the
    # default Alpacon Cloud host. (get_base_url also type-guards this, but being
    # explicit keeps the mock's behavior obvious.)
    mock_tm.get_base_url_override.return_value = None

    # patch() rebinds one name at a time, so every module that imported
    # get_token_manager at its own top level needs its own entry here.
    with (
        patch('utils.token_manager.get_token_manager', return_value=mock_tm),
        patch('utils.health.get_token_manager', return_value=mock_tm),
        patch('tools.workspace_tools.get_token_manager', return_value=mock_tm),
    ):
        yield mock_tm


@pytest.fixture(autouse=True)
def isolated_device_id_dir(tmp_path):
    """Keep the stdio device id file out of the real ~/.alpacon-mcp."""
    manager = MagicMock()
    manager.config_dir = tmp_path
    with patch('utils.device_id.get_token_manager', return_value=manager):
        yield tmp_path


@pytest.fixture
async def make_client():
    """Build AlpaconHTTPClients over a given transport, with no retry delay."""
    clients: list[AlpaconHTTPClient] = []

    def build(transport: httpx.AsyncBaseTransport) -> AlpaconHTTPClient:
        client = AlpaconHTTPClient(transport=transport)
        client.retry_delay = 0
        clients.append(client)
        return client

    yield build
    for client in clients:
        await client.close()
