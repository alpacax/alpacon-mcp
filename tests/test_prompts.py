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


@pytest.mark.asyncio
async def test_guarded_execution_covers_intent_deviation():
    # Assert on the code, not on work_session_update alone—that verb also
    # serves the scope case, so a deleted sentence would still pass.
    result = await mcp.get_prompt('guarded_execution', {'work_session_id': 'sess-123'})
    text = result.messages[0].content.text
    assert 'SUDO_INTENT_DEVIATION' in text
    assert 'work_session_update(description=...)' in text


@pytest.mark.asyncio
async def test_guarded_execution_names_both_denial_fields():
    # pending_approval_response carries `category`, gate errors carry `code`.
    # Naming only one sends the agent looking for a field that is not there.
    result = await mcp.get_prompt('guarded_execution', {'work_session_id': 'sess-123'})
    text = result.messages[0].content.text
    assert '`code`' in text
    assert '`category`' in text


@pytest.mark.asyncio
async def test_work_session_workflow_renders_servers():
    result = await mcp.get_prompt(
        'work_session_workflow',
        {'intent': 'restart nginx', 'servers': 'uuid-a, uuid-b'},
    )
    text = result.messages[0].content.text
    assert 'Target servers (UUIDs): uuid-a, uuid-b' in text


@pytest.mark.asyncio
async def test_work_session_workflow_pending_approval_names_status_and_stop_states():
    result = await mcp.get_prompt('work_session_workflow', {'intent': 'restart nginx'})
    text = result.messages[0].content.text
    assert 'data.status' in text
    for state in ('rejected', 'cancelled', 'expired', 'revoked', 'completed'):
        assert state in text


@pytest.mark.asyncio
async def test_security_audit_tells_the_model_to_check_walk_completeness():
    """Lens 1 drives the one workflow #325 is about, over a bounded walk.

    Without this instruction the prompt reproduces the defect the tool was
    fixed for: a model answering "what happened in this session" from a prefix
    it cannot tell from the whole. The tool reports the bound, but only the
    prompt tells the model to look.
    """
    result = await mcp.get_prompt('security_audit', {'work_session_id': 'sess-9'})
    text = result.messages[0].content.text

    assert 'pagination.stopped_because' in text
    assert 'page_bound' in text
    assert 'pagination.next_cursor' in text
    # The promise the bound can violate. The tool description dropped it; the
    # prompt kept it for three releases after the tool stopped keeping it.
    assert 'unified' not in text


@pytest.mark.asyncio
async def test_security_audit_does_not_read_complete_as_more_records():
    """`complete: false` has three causes and only one of them means "read on".

    A resumed call reports it with nothing left, and a failed walk reports it
    with `next_cursor` pointing back at where the walk started.
    """
    result = await mcp.get_prompt('security_audit', {'work_session_id': 'sess-9'})
    text = result.messages[0].content.text

    assert 'complete: false' in text
    assert 'retry point' in text


@pytest.mark.asyncio
async def test_security_audit_names_every_lens_that_walks_a_cursor():
    """Three of the five lenses are bounded, not just the timeline.

    Warning about lens 1 alone would leave the cross-session and mutation
    trails to be read as whole, which is the same error in a wider scope.
    """
    result = await mcp.get_prompt('security_audit', {'work_session_id': 'sess-9'})
    text = result.messages[0].content.text

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
    """The walk reads forward, so the prefix is the beginning, not a sample.

    That asymmetry is the whole reason a bounded timeline misleads: the part
    an audit asks about is the part a cut result drops.
    """
    result = await mcp.get_prompt('security_audit', {'work_session_id': 'sess-9'})
    text = result.messages[0].content.text

    assert 'reads' in text and 'forward' in text
    assert 'start of the session' in text
