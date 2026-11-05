"""The plugin's eval mocks stay what the tools return, and every guarded tool is offered."""

from pathlib import Path

import pytest

from tests.eval_mocks import (
    EVALS,
    HAND_WRITTEN,
    MOCKS,
    SHARED,
    TOOLS_JSON,
    Mock,
    render,
    render_tools_json,
)

PLUGIN_TOOL_PREFIX = 'mcp__plugin_alpacon_alpacon__'
REGENERATE = 'regenerate with `python -m tests.eval_mocks`'
CASES = sorted(p.parent for p in EVALS.glob('*/prompt.md'))


def frontmatter(path: Path) -> dict[str, str]:
    _, head, _ = path.read_text().split('---\n', 2)
    return dict(line.split(': ', 1) for line in head.splitlines() if ': ' in line)


def mock_files() -> set[str]:
    return {str(p.relative_to(EVALS)) for p in EVALS.glob('**/mocks/alpacon/*.md')}


@pytest.mark.parametrize('mock', MOCKS, ids=[m.path for m in MOCKS])
async def test_eval_mock_is_what_the_tool_returns_for_its_canned_answer(mock: Mock):
    # Given the mock file on disk
    on_disk = (EVALS / mock.path).read_text()

    # When the real tool runs against the mock's canned HTTP answers
    rendered = await render(mock)

    # Then the file holds that result
    assert on_disk == rendered, f'{mock.path} drifted from the tool; {REGENERATE}'


async def test_tools_json_holds_the_published_schema_of_every_mocked_tool():
    # Given the shared schema file
    on_disk = TOOLS_JSON.read_text()

    # When the published schemas are read again
    rendered = await render_tools_json()

    # Then they match
    assert on_disk == rendered, f'_tools.json drifted from the tools; {REGENERATE}'


def test_every_mock_file_is_generated_or_listed_as_hand_written():
    # Given the generator's list and the hand-written list
    known = {m.path for m in MOCKS} | HAND_WRITTEN

    # When the mock files on disk are listed
    on_disk = mock_files()

    # Then none is unaccounted for
    assert on_disk == known


@pytest.mark.parametrize('case', CASES, ids=[c.name for c in CASES])
def test_every_tool_a_grader_watches_is_offered_in_its_case(case: Path):
    # Given the case's tool graders on plugin tools
    watched = {
        fm['tool'].removeprefix(PLUGIN_TOOL_PREFIX)
        for g in sorted((case / 'graders').glob('*.md'))
        if (fm := frontmatter(g)).get('type') == 'tool_used'
        and fm.get('tool', '').startswith(PLUGIN_TOOL_PREFIX)
    }

    # When the tools the case offers are listed (a mock file is what offers one)
    offered = {
        p.stem for d in (case / 'mocks/alpacon', EVALS / SHARED) for p in d.glob('*.md')
    }

    # Then a grader never watches a tool the agent cannot call
    assert watched <= offered, (
        f'graders watch tools with no mock: {sorted(watched - offered)}'
    )
