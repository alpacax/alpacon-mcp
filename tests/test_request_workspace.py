"""The workspace a tool call is acting on, as the step-up link needs it."""

from unittest.mock import MagicMock

import pytest

from utils import request_workspace
from utils.decorators import mcp_tool_handler


@pytest.fixture(autouse=True)
def unbound_workspace():
    token = request_workspace.bind_workspace(None)
    yield
    request_workspace.reset_workspace(token)


async def test_current_workspace_is_none_before_any_tool_binds_one():
    # Given a fresh context
    # When nothing has bound a workspace
    result = request_workspace.current_workspace()
    # Then there is no workspace
    assert result is None


async def test_current_workspace_returns_the_bound_workspace():
    # Given a tool call acting on alpacax
    request_workspace.bind_workspace('alpacax')
    # When the HTTP layer asks for it
    result = request_workspace.current_workspace()
    # Then it reads alpacax
    assert result == 'alpacax'


async def test_tool_handler_binds_the_resolved_workspace_for_the_tool_body(
    monkeypatch, mock_token_manager
):
    # Given a stdio-mode tool that records the workspace its body sees
    monkeypatch.setattr('server.mcp.tool', MagicMock(return_value=lambda func: func))
    seen = {}

    @mcp_tool_handler(description='probe')
    async def probe(workspace, region='', **kwargs):
        seen['workspace'] = request_workspace.current_workspace()
        return {'status': 'success'}

    # When the tool runs for alpacax
    await probe(workspace='alpacax', region='ap1')

    # Then its body saw alpacax
    assert seen['workspace'] == 'alpacax'


async def test_tool_handler_binds_no_workspace_for_a_workspaceless_tool(
    monkeypatch, mock_token_manager
):
    # Given a workspace-less tool called after another call bound a workspace
    monkeypatch.setattr('server.mcp.tool', MagicMock(return_value=lambda func: func))
    request_workspace.bind_workspace('stale-ws')
    seen = {}

    @mcp_tool_handler(description='probe', requires_workspace=False)
    async def probe(region='', **kwargs):
        seen['workspace'] = request_workspace.current_workspace()
        return {'status': 'success'}

    # When the tool runs
    await probe()

    # Then its body saw no workspace
    assert seen['workspace'] is None


async def test_tool_handler_resets_the_binding_after_the_tool_call(
    monkeypatch, mock_token_manager
):
    # Given a tool that fails after the handler bound its workspace
    monkeypatch.setattr('server.mcp.tool', MagicMock(return_value=lambda func: func))

    @mcp_tool_handler(description='probe')
    async def probe(workspace, region='', **kwargs):
        raise RuntimeError('boom')

    # When the tool runs and returns its error
    await probe(workspace='alpacax', region='ap1')

    # Then no workspace stays bound once the call ends
    assert request_workspace.current_workspace() is None


async def test_tool_handler_starts_each_call_with_an_empty_set_of_minted_links(
    monkeypatch, mock_token_manager
):
    # Given a tool that records the links minted so far and mints one
    monkeypatch.setattr('server.mcp.tool', MagicMock(return_value=lambda func: func))
    seen = []

    @mcp_tool_handler(description='probe')
    async def probe(workspace, region='', **kwargs):
        seen.append(set(request_workspace.minted_in_call()))
        request_workspace.minted_in_call().add(('sub', 'instance', 'origin'))
        return {'status': 'success'}

    # When the tool runs twice
    await probe(workspace='alpacax', region='ap1')
    await probe(workspace='alpacax', region='ap1')

    # Then neither call saw a link the other minted, and none is tracked afterwards
    assert seen == [set(), set()]
    assert request_workspace.minted_in_call() is None
