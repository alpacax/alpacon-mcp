"""Tests for MCP prompts (agent workflow guides)."""

import pytest
from mcp.types import GetPromptResult, TextContent

import tools.prompts  # noqa: F401  (registers prompts on import)
from server import mcp

EXPECTED = {
    'work_session_workflow': {'intent': 'restart nginx'},
    'guarded_execution': {'work_session_id': 'sess-123'},
    'incident_response': {'server_id': 'srv-1'},
    'security_audit': {'work_session_id': 'sess-9'},
}


async def _render(name: str, args: dict[str, str]) -> str:
    """Render prompt `name` and return the text of its first message."""
    result = await mcp.get_prompt(name, args)
    assert isinstance(result, GetPromptResult)
    content = result.messages[0].content
    assert isinstance(content, TextContent)
    return content.text


@pytest.mark.asyncio
async def test_all_four_prompts_registered():
    names = {p.name for p in await mcp.list_prompts()}
    assert set(EXPECTED) <= names


@pytest.mark.asyncio
@pytest.mark.parametrize('name, args', EXPECTED.items())
async def test_prompt_renders_nonempty_text(name, args):
    text = await _render(name, args)
    assert text.strip()
    for arg_value in args.values():
        assert arg_value in text  # argument is interpolated into the guidance


@pytest.mark.asyncio
async def test_guarded_execution_covers_intent_deviation():
    # Assert on the code, not on work_session_update alone—that verb also
    # serves the scope case, so a deleted sentence would still pass.
    text = await _render('guarded_execution', {'work_session_id': 'sess-123'})
    assert 'SUDO_INTENT_DEVIATION' in text
    assert 'work_session_update(description=...)' in text


@pytest.mark.asyncio
async def test_guarded_execution_names_both_denial_fields():
    # pending_approval_response carries `category`, gate errors carry `code`.
    # Naming only one sends the agent looking for a field that is not there.
    text = await _render('guarded_execution', {'work_session_id': 'sess-123'})
    assert '`code`' in text
    assert '`category`' in text


@pytest.mark.asyncio
async def test_work_session_workflow_renders_servers():
    text = await _render(
        'work_session_workflow',
        {'intent': 'restart nginx', 'servers': 'uuid-a, uuid-b'},
    )
    assert 'Target servers (UUIDs): uuid-a, uuid-b' in text


@pytest.mark.asyncio
async def test_work_session_workflow_pending_approval_names_status_and_stop_states():
    text = await _render('work_session_workflow', {'intent': 'restart nginx'})
    assert 'data.status' in text
    for state in ('rejected', 'cancelled', 'expired', 'revoked', 'completed'):
        assert state in text


@pytest.mark.asyncio
async def test_security_audit_tells_the_model_to_check_walk_completeness():
    text = await _render('security_audit', {'work_session_id': 'sess-9'})

    assert 'pagination.stopped_because' in text
    assert 'page_bound' in text
    assert 'pagination.next_cursor' in text
    # "unified" promises a whole timeline, which a bounded walk cannot.
    assert 'unified' not in text


@pytest.mark.asyncio
async def test_security_audit_does_not_read_complete_as_more_records():
    """A resumed or failed walk also reports `complete: false`."""
    text = await _render('security_audit', {'work_session_id': 'sess-9'})

    assert 'complete: false' in text
    assert 'retry point' in text


@pytest.mark.asyncio
async def test_security_audit_names_every_lens_that_walks_a_cursor():
    text = await _render('security_audit', {'work_session_id': 'sess-9'})

    bounded = text.split('Lenses 1, 2 and 4')[1]
    for tool in (
        'work_session_timeline',
        'list_server_logs',
        'list_webftp_logs',
        'list_activity_logs',
    ):
        assert tool in bounded


@pytest.mark.asyncio
async def test_security_audit_says_a_bounded_timeline_omits_the_sessions_end():
    text = await _render('security_audit', {'work_session_id': 'sess-9'})

    assert 'reads' in text and 'forward' in text
    assert 'start of the session' in text
