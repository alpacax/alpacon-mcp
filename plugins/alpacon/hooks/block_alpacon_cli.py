"""PreToolUse hook: exit 2 refuses a Bash command running the alpacon CLI, exit 0 allows it.
A habit guard, not a boundary: eval, aliases, case patterns and arrays escape it.
"""

from __future__ import annotations  # the user's python3 may predate 3.10

import json
import os
import re
import shlex
import sys

HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')
COMMENT = re.compile(r'(?:^|(?<=[ \t]))#[^\n]*', re.M)
FALLBACK_SEPARATORS = re.compile(r'&&|\|\||[;|&\n()]')
KEYWORDS = {'!', '{', 'if', 'then', 'elif', 'else', 'do', 'while', 'until'}
WRAPPERS = {
    'sudo': {'-u', '-g', '-h', '-p', '-C', '--user', '--group'},
    'nice': {'-n'},
    'watch': {'-n'},
    'stdbuf': {'-i', '-o', '-e'},
    'timeout': {'-s', '-k'},
    'xargs': {'-n', '-I', '-P', '-L', '-d', '-E', '-s'},
    'env': {'-u', '-C', '-S'},
    'exec': set(),
    'nohup': set(),
    'time': set(),
    'command': set(),
}
SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh'}
SHELL_WORD = re.compile(rf'(?:^|[\s|;&(])(?:\S*/)?(?:{"|".join(SHELLS)})(?:\s|$)')
REFUSAL = (
    'Alpacon is reached only through the alpacon MCP tools, not the alpacon CLI. '
    'Call the matching mcp__alpacon tool; if one failed, report its error instead.'
)


def strip_heredoc_bodies(command: str) -> tuple[str, list[str]]:
    """Drop heredoc bodies from the command; return those fed to a shell as scripts."""
    kept: list[str] = []
    scripts: list[str] = []
    pending: list[tuple[str, list[str], bool]] = []  # delimiter, body, fed to a shell
    for line in command.split('\n'):
        if pending:
            delimiter, body, to_shell = pending[0]
            if line.strip() != delimiter:
                body.append(line)
                continue
            pending.pop(0)
            if to_shell:
                scripts.append('\n'.join(body))
            continue
        kept.append(line)
        to_shell = bool(SHELL_WORD.search(QUOTED.sub('', line)))
        pending.extend((m.group(2), [], to_shell) for m in HEREDOC.finditer(line))
    return '\n'.join(kept), scripts


def split_substitutions(command: str) -> tuple[str, list[str]]:
    """Replace each $(...) and `...` outside single quotes with one word; return their bodies."""
    outer, inner, quote, i = [], [], None, 0
    while i < len(command):
        char = command[i]
        if char == '\\' and quote != "'":
            outer.append(command[i : i + 2])
            i += 2
            continue
        if quote == "'":
            quote = None if char == "'" else quote
        elif char == "'" and quote is None:
            quote = "'"
        elif char == '"':
            quote = None if quote == '"' else '"'
        elif command.startswith('$(', i):
            depth, j = 1, i + 2
            while j < len(command) and depth:
                depth += {'(': 1, ')': -1}.get(command[j], 0)
                j += 1
            inner.append(command[i + 2 : j - 1 if depth == 0 else j])
            outer.append('_')
            i = j
            continue
        elif char == '`':
            j = command.find('`', i + 1)
            j = len(command) if j < 0 else j
            inner.append(command[i + 1 : j])
            outer.append('_')
            i = j + 1
            continue
        outer.append(char)
        i += 1
    return ''.join(outer), inner


def segments(command: str) -> list[list[str]]:
    # a line continuation joins the words around it
    command = command.replace('\\\n', '')
    lexer = shlex.shlex(command, posix=True, punctuation_chars='();<>|&\n')
    lexer.whitespace = ' \t\r'  # a newline separates commands
    lexer.whitespace_split = True
    lexer.commenters = ''  # shlex's comment skip also eats the newline that ends it
    try:
        tokens = list(lexer)
    except ValueError:  # an unbalanced quote, often an apostrophe in a comment
        uncommented = COMMENT.sub('', command)
        if uncommented != command:
            return segments(uncommented)
        return [s.split() for s in FALLBACK_SEPARATORS.split(command)]
    result: list[list[str]] = []
    current: list[str] = []
    skip_next = in_comment = False
    for token in tokens:
        # shlex merges adjacent punctuation, so a comment can end in '\n\n' or ')\n'
        if in_comment and '\n' not in token:
            continue
        in_comment = False
        if skip_next:
            skip_next = False
        elif token.startswith('#'):
            in_comment = True
        elif token and set(token) <= set('<>&') and token not in ('&', '&&'):
            skip_next = True  # the redirection target is not a command
        elif token and set(token) <= set('();<>|&\n'):
            result.append(current)
            current = []
        else:
            current.append(token)
    result.append(current)
    return result


def program_index(words: list[str]) -> int | None:
    i = 0
    while i < len(words):
        word = words[i]
        if ASSIGNMENT.match(word) or word in KEYWORDS:
            i += 1
        elif word == 'function':
            i += 2  # the function's name
        elif os.path.basename(word) in WRAPPERS:
            word = os.path.basename(word)
            i += 1
            while i < len(words) and words[i].startswith('-'):
                if word == 'command' and words[i] in ('-v', '-V'):
                    return None  # a lookup, not a run
                i += 2 if words[i] in WRAPPERS[word] else 1
            if word == 'timeout':
                i += 1  # the duration
        else:
            return i
    return None


def segment_runs_alpacon(words: list[str]) -> bool:
    i = program_index(words)
    if i is None:
        return False
    # a wrapper such as watch hands this one word to sh
    if ' ' in words[i]:
        return runs_alpacon_cli(words[i])
    name = os.path.basename(words[i])
    if name == 'alpacon':
        return True
    if name in SHELLS:
        for j in range(i + 1, len(words) - 1):
            flag = words[j]
            if flag.startswith('-') and 'c' in flag and runs_alpacon_cli(words[j + 1]):
                return True
    return False


def runs_alpacon_cli(command: str) -> bool:
    command, scripts = strip_heredoc_bodies(command)
    outer, inner = split_substitutions(command)
    return any(runs_alpacon_cli(script) for script in scripts + inner) or any(
        segment_runs_alpacon(words) for words in segments(outer)
    )


def main() -> int:
    command = json.load(sys.stdin).get('tool_input', {}).get('command', '')
    if runs_alpacon_cli(command):
        print(REFUSAL, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
