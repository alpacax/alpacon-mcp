"""Which MCP surfaces the client declared is logged on each tools/call (#427)."""

import logging
from types import SimpleNamespace
from typing import cast

import pytest
from mcp.server.apps import EXTENSION_ID
from mcp.server.context import ServerRequestContext
from mcp.types import ClientCapabilities

import server as server_module
from utils.client_surfaces import ClientSurfaces, client_surfaces, log_client_surfaces

type _Context = ServerRequestContext[object, object]

LOGGER = 'alpacon_mcp.client_surfaces'


def _capabilities(**fields: object) -> ClientCapabilities:
    return ClientCapabilities.model_validate(fields)


class TestClientSurfaces:
    def test_no_capabilities_is_unknown(self):
        assert client_surfaces(None) == ClientSurfaces('unknown', 'unknown')

    def test_empty_capabilities_declare_nothing(self):
        assert client_surfaces(_capabilities()) == ClientSurfaces('absent', 'absent')

    def test_url_elicitation_is_declared(self):
        caps = _capabilities(elicitation={'url': {}})

        assert client_surfaces(caps) == ClientSurfaces('declared', 'absent')

    def test_form_only_elicitation_does_not_declare_url(self):
        caps = _capabilities(elicitation={'form': {}})

        assert client_surfaces(caps).url_elicitation == 'absent'

    def test_apps_extension_is_declared(self):
        caps = _capabilities(extensions={EXTENSION_ID: {'mimeTypes': []}})

        assert client_surfaces(caps) == ClientSurfaces('absent', 'declared')

    def test_other_extensions_do_not_declare_apps(self):
        caps = _capabilities(extensions={'io.example/other': {}})

        assert client_surfaces(caps).apps == 'absent'


def _ctx(method: str, capabilities: ClientCapabilities | None) -> _Context:
    return cast(
        _Context,
        SimpleNamespace(
            method=method,
            protocol_version='2026-07-28',
            session=SimpleNamespace(client_capabilities=capabilities),
        ),
    )


async def _call(ctx: _Context) -> object:
    async def call_next(_: object) -> dict[str, str]:
        return {'passed': 'through'}

    return await log_client_surfaces(ctx, call_next)


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_tools_call_logs_version_and_both_states(self, caplog):
        ctx = _ctx('tools/call', _capabilities(elicitation={'url': {}}))

        with caplog.at_level(logging.INFO, logger=LOGGER):
            result = await _call(ctx)

        assert result == {'passed': 'through'}
        message = caplog.records[-1].getMessage()
        assert 'protocol_version=2026-07-28' in message
        assert 'elicitation.url=declared' in message
        assert 'apps=absent' in message

    @pytest.mark.asyncio
    async def test_tools_call_without_capabilities_logs_unknown(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            await _call(_ctx('tools/call', None))

        message = caplog.records[-1].getMessage()
        assert 'elicitation.url=unknown' in message
        assert 'apps=unknown' in message

    @pytest.mark.asyncio
    async def test_tools_call_still_passes_through_when_info_is_disabled(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            result = await _call(_ctx('tools/call', None))

        assert result == {'passed': 'through'}
        assert caplog.records == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize('method', ['tools/list', 'resources/read', 'ping'])
    async def test_other_methods_log_nothing_and_still_pass_through(
        self, caplog, method
    ):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            result = await _call(_ctx(method, None))

        assert result == {'passed': 'through'}
        assert caplog.records == []


def test_the_server_registers_the_shared_middleware_list():
    registered = server_module.mcp._lowlevel_server.middleware

    assert all(m in registered for m in server_module.SERVER_MIDDLEWARE)
    assert log_client_surfaces in server_module.SERVER_MIDDLEWARE
