"""Contracts shared by every tool using the error-handling decorator.

These are unit tests over the decorators themselves. The same chain is
exercised end to end against a real tool in
``tests/integration/test_decorator_chain.py``.
"""

import importlib
from unittest.mock import MagicMock

import pytest

import server
from utils.decorators import (
    ERROR_HANDLING_MARKER,
    mcp_tool_handler,
    with_error_handling,
)
from utils.error_handler import UpstreamAuthError


@pytest.mark.parametrize(
    'args, kwargs, workspace, region',
    [
        ((), {'workspace': 'other-ws', 'region': 'us1'}, 'other-ws', 'us1'),
        (('other-ws', 'us1'), {}, 'other-ws', 'us1'),
        ((), {}, 'default-ws', 'ap1'),
    ],
    ids=['keywords', 'positional', 'defaults'],
)
@pytest.mark.asyncio
async def test_exception_becomes_error_with_call_context(
    args, kwargs, workspace, region
):
    @with_error_handling
    async def failing_tool(workspace='default-ws', region='ap1'):
        raise RuntimeError('backend exploded')

    result = await failing_tool(*args, **kwargs)

    assert result == {
        'status': 'error',
        'message': 'Failed in failing_tool: backend exploded',
        'workspace': workspace,
        'region': region,
    }


@pytest.mark.asyncio
async def test_upstream_auth_error_propagates_for_reauthentication():
    error = UpstreamAuthError(mfa_required=True, source='command')

    @with_error_handling
    async def failing_tool():
        raise error

    with pytest.raises(UpstreamAuthError) as raised:
        await failing_tool()

    assert raised.value is error


@pytest.mark.asyncio
async def test_success_response_is_preserved():
    payload = {'status': 'success', 'data': {'results': []}}

    @with_error_handling
    async def successful_tool():
        return payload

    assert await successful_tool() is payload
    assert payload == {'status': 'success', 'data': {'results': []}}


@pytest.mark.asyncio
async def test_registered_tool_includes_exception_handling(
    monkeypatch, mock_token_manager
):
    # Keep the real decorator stack without registering a test tool on the server.
    register = MagicMock(return_value=lambda func: func)
    monkeypatch.setattr('server.mcp.tool', register)

    @mcp_tool_handler(description='Error handling probe')
    async def failing_tool(workspace, region='', **kwargs):
        raise RuntimeError('backend exploded')

    result = await failing_tool(workspace='testworkspace', region='us1')

    assert result == {
        'status': 'error',
        'message': 'Failed in failing_tool: backend exploded',
        'workspace': 'testworkspace',
        'region': 'us1',
    }
    register.assert_called_once_with(
        description='Error handling probe', annotations=None, meta=None
    )


def _registered_tools():
    for module in sorted(server.ALL_TOOL_MODULES | server.ALWAYS_ON_MODULES):
        importlib.import_module(f'{server.TOOLS_PACKAGE}.{module}')
    # Reaching into the manager: no public FastMCP API hands back the function.
    return server.mcp._tool_manager.list_tools()


def test_every_registered_tool_carries_error_handling():
    """One sweep, in place of the per-tool copies of the error-path test."""
    tools = _registered_tools()

    assert {'health_check', 'list_servers'} <= {tool.name for tool in tools}
    unguarded = [
        tool.name
        for tool in tools
        if not getattr(tool.fn, ERROR_HANDLING_MARKER, False)
    ]
    assert not unguarded
