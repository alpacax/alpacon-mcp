"""The plugin's eval mocks stay what the tools return, and every guarded tool is offered."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
import yaml  # type: ignore[import-untyped]

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


def case_directories(root: Path) -> list[Path]:
    return sorted(
        {
            p.parent
            for name in ('prompt.md', 'case.yaml')
            for p in root.glob(f'*/{name}')
        }
    )


CASES = case_directories(EVALS)


def frontmatter(path: Path) -> Mapping[str, object]:
    _, head, _ = path.read_text().split('---\n', 2)
    return dict(line.split(': ', 1) for line in head.splitlines() if ': ' in line)


def case_graders(case: Path) -> list[Mapping[str, object]]:
    graders: list[Mapping[str, object]] = []
    if (case / 'case.yaml').exists():
        config = cast(
            dict[str, object], yaml.safe_load((case / 'case.yaml').read_text())
        )
        graders.extend(cast(list[Mapping[str, object]], config.get('graders', [])))
    graders.extend(frontmatter(g) for g in sorted((case / 'graders').glob('*.md')))
    return graders


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


async def test_tools_json_refuses_a_mock_named_after_no_published_tool():
    # Given a mock whose file name is not a published tool
    stray = Mock(f'{SHARED}/no_such_tool.md', {}, MOCKS[0].call)

    # When the schemas are rendered, then the name is reported, not dropped
    with (
        patch('tests.eval_mocks.MOCKS', [*MOCKS, stray]),
        pytest.raises(ValueError, match='no_such_tool'),
    ):
        await render_tools_json()


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
        tool.removeprefix(PLUGIN_TOOL_PREFIX)
        for grader in case_graders(case)
        if grader.get('type') == 'tool_used'
        and isinstance(tool := grader.get('tool'), str)
        and tool.startswith(PLUGIN_TOOL_PREFIX)
    }

    # When the tools the case offers are listed (a mock file is what offers one)
    offered = {
        p.stem for d in (case / 'mocks/alpacon', EVALS / SHARED) for p in d.glob('*.md')
    }

    # Then a grader never watches a tool the agent cannot call
    assert watched <= offered, (
        f'graders watch tools with no mock: {sorted(watched - offered)}'
    )


def test_case_discovery_finds_both_formats_without_duplicating_mixed_cases(
    tmp_path: Path,
):
    for name, files in {
        'markdown': ['prompt.md'],
        'yaml': ['case.yaml'],
        'mixed': ['prompt.md', 'case.yaml'],
        'not-a-case': ['notes.md'],
    }.items():
        case = tmp_path / name
        case.mkdir()
        for file in files:
            (case / file).touch()

    cases = case_directories(tmp_path)

    assert [case.name for case in cases] == ['markdown', 'mixed', 'yaml']


@pytest.mark.parametrize('layout', ['markdown', 'yaml', 'mixed'])
def test_mock_coverage_checks_graders_in_each_case_format(tmp_path: Path, layout: str):
    if layout in ('yaml', 'mixed'):
        (tmp_path / 'case.yaml').write_text(
            'schema_version: "1.1"\nname: fixture\ngraders:\n'
            '  - name: yaml-check\n    type: tool_used\n'
            f'    tool: {PLUGIN_TOOL_PREFIX}missing_tool\n'
        )
    if layout in ('markdown', 'mixed'):
        (tmp_path / 'graders').mkdir()
        (tmp_path / 'graders/check.md').write_text(
            f'---\ntype: tool_used\ntool: {PLUGIN_TOOL_PREFIX}missing_tool\n---\n'
        )

    with pytest.raises(AssertionError, match='missing_tool'):
        test_every_tool_a_grader_watches_is_offered_in_its_case(tmp_path)


def test_mixed_case_keeps_yaml_and_markdown_graders(tmp_path: Path):
    (tmp_path / 'case.yaml').write_text(
        'graders:\n  - name: yaml-check\n    type: tool_used\n    tool: yaml_tool\n'
    )
    (tmp_path / 'graders').mkdir()
    (tmp_path / 'graders/check.md').write_text(
        '---\ntype: tool_used\ntool: markdown_tool\n---\n'
    )

    graders = case_graders(tmp_path)

    assert [grader['tool'] for grader in graders] == ['yaml_tool', 'markdown_tool']
