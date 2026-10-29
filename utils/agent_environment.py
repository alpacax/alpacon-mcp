"""Name the AI agent that launched this process from its environment markers.
Reads only the environment, never the process tree; CI and editors do not count."""

import re
from collections.abc import Callable, Mapping

# The cross-agent variable: any agent can set AI_AGENT=<name> or
# AI_AGENT=<name>/<version> to be detected. It is read before the table.
AI_AGENT = 'AI_AGENT'

# The server's limits, as in utils.declared_agent.
_NAME_MAX_LENGTH = 64
_VERSION_MAX_LENGTH = 32


def _equals(want: str) -> Callable[[str], bool]:
    return lambda value: value == want


def _equals_fold(want: str) -> Callable[[str], bool]:
    return lambda value: value.casefold() == want.casefold()


def _non_empty(value: str) -> bool:
    return value != ''


# (canonical name, variable, the values that mark the agent), in order; the
# first match names the agent.
_ROWS: tuple[tuple[str, str, Callable[[str], bool]], ...] = (
    ('claude-code', 'CLAUDE_CODE_CHILD_SESSION', _equals('1')),
    ('codex', 'CODEX_CI', _equals('1')),
    ('codex', 'CODEX_THREAD_ID', _non_empty),
    ('codex', 'CODEX_SANDBOX', _non_empty),
    ('gemini-cli', 'GEMINI_CLI', _equals('1')),
    ('github-copilot', 'COPILOT_AGENT', _equals('1')),
    ('github-copilot', 'COPILOT_CLI', _equals('1')),
    ('cursor', 'CURSOR_AGENT', _equals('1')),
    ('cline', 'CLINE_ACTIVE', _equals_fold('true')),
    ('goose', 'GOOSE_TERMINAL', _equals('1')),
    ('goose', 'AGENT', _equals_fold('goose')),
)

# Every variable detection reads.
VARIABLES: tuple[str, ...] = (AI_AGENT, *(row[1] for row in _ROWS))

# Each name an agent is known to send, reduced to one canonical name. A name
# outside the table is lowercased and stands for itself.
_ALIASES = {
    'claude-code': 'claude-code',
    'codex': 'codex',
    'codex-mcp-client': 'codex',
    'gemini-cli': 'gemini-cli',
    'gemini-cli-mcp-client': 'gemini-cli',
    'github-copilot': 'github-copilot',
    'github_copilot_vscode_agent': 'github-copilot',
    'github-copilot-cli': 'github-copilot',
    'cursor': 'cursor',
    'cline': 'cline',
    'goose': 'goose',
    'aider': 'aider',
}

# The "<name>_<version>_agent" form Claude Code puts in AI_AGENT, such as
# claude-code_2-1-120_agent. The version starts with a digit, so
# github_copilot_vscode_agent is not read as one.
_VERSIONED_AGENT = re.compile(r'(.+?)_([0-9][^_]*)_agent', re.IGNORECASE)

# A version written with dashes for dots (2-1-120).
_DASHED_VERSION = re.compile(r'[0-9]+(-[0-9]+)+')


def _clean(value: str, limit: int) -> str:
    """Keep printable ASCII only, then trim and cut to limit characters."""
    kept = ''.join(c for c in value if ' ' <= c <= '~').strip()
    return kept[:limit].strip()


def _parse_ai_agent(value: str) -> tuple[str, str] | None:
    """An AI_AGENT value as (canonical name, version); only the name is lowercased."""
    value = _clean(value, len(value))
    if not value:
        return None
    if value.lower() in _ALIASES:
        return _ALIASES[value.lower()], ''
    version = ''
    if match := _VERSIONED_AGENT.fullmatch(value):
        name, version = match.group(1), match.group(2)
    else:
        name, _, version = value.partition('/')
    if _DASHED_VERSION.fullmatch(version):
        version = version.replace('-', '.')
    name = _clean(name, _NAME_MAX_LENGTH).lower()
    name = _ALIASES.get(name, name)
    if not name:
        return None
    return name, _clean(version, _VERSION_MAX_LENGTH)


def agent_from_environment(environ: Mapping[str, str]) -> tuple[str, str] | None:
    """The agent the environment names as (name, version), or None.
    The version is empty unless AI_AGENT states one."""
    if declared := _parse_ai_agent(environ.get(AI_AGENT, '')):
        return declared
    for name, variable, matches in _ROWS:
        if matches(environ.get(variable, '').strip()):
            return name, ''
    return None
