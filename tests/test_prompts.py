"""Tests for MCP prompts (agent workflow guides)."""

import pytest

import tools.prompts  # noqa: F401  (registers prompts on import)
from server import mcp

EXPECTED = {
    'work_session_workflow': {'intent': 'restart nginx'},
    'guarded_execution': {'work_session_id': 'sess-123'},
    'incident_response': {'server_id': 'srv-1'},
    'security_audit': {'work_session_id': 'sess-9'},
}


@pytest.mark.asyncio
async def test_all_four_prompts_registered():
    names = {p.name for p in await mcp.list_prompts()}
    assert set(EXPECTED) <= names


@pytest.mark.asyncio
@pytest.mark.parametrize('name, args', EXPECTED.items())
async def test_prompt_renders_nonempty_text(name, args):
    result = await mcp.get_prompt(name, args)
    text = result.messages[0].content.text
    assert text.strip()
    for arg_value in args.values():
        assert arg_value in text  # argument is interpolated into the guidance
