"""Regression tests for FastMCP-generated tool input schemas.

The token-injection **kwargs on tool functions must never surface in the
MCP inputSchema—FastMCP's func_metadata() does not special-case
VAR_KEYWORD parameters, so the decorator has to strip them from the
exposed signature.
"""

from unittest.mock import patch

import pytest

import tools.command_tools  # noqa: F401 - trigger tool registration
import tools.server_tools  # noqa: F401 - trigger tool registration
from server import mcp


@pytest.mark.asyncio
async def test_tool_schemas_do_not_expose_kwargs():
    tools_ = await mcp.list_tools()
    assert tools_, 'no tools registered'
    for tool in tools_:
        props = tool.inputSchema.get('properties', {})
        required = tool.inputSchema.get('required', [])
        assert 'kwargs' not in props, f'{tool.name} exposes kwargs in schema'
        assert 'kwargs' not in required, f'{tool.name} requires kwargs'


@pytest.mark.asyncio
async def test_call_tool_without_kwargs_argument():
    # Before the fix this raises ToolError: "kwargs Field required".
    with patch('utils.decorators.validate_token', return_value=None):
        result = await mcp.call_tool('list_servers', {'workspace': 'testws'})
    # Reaching here proves validation passed without kwargs; the call itself
    # short-circuits at token lookup (no network).
    assert result is not None
