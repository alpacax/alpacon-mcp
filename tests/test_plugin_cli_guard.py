"""The alpacon plugin's Bash hook refuses the alpacon CLI and passes everything else."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).parent.parent / 'plugins' / 'alpacon'
HOOK = PLUGIN / 'hooks' / 'block_alpacon_cli.py'


def run_hook(command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
    return subprocess.run(  # noqa: S603
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    'command',
    [
        'alpacon server ls',
        'cd /tmp && alpacon websh my-server',
        'cat cmds.txt | alpacon exec my-server',
        '/usr/local/bin/alpacon login',
        'ALPACON_REGION=ap1 alpacon server ls',
        'sudo alpacon server ls',
        'echo $(alpacon token ls)',
        '(alpacon server ls)',
        'echo "$(alpacon token ls)"',
        'echo `alpacon token ls`',
        'for h in a b; do alpacon exec $h uptime; done',
        'while read h; do alpacon exec $h uptime; done < hosts.txt',
        'if true; then alpacon server ls; fi',
        '{ alpacon server ls; }',
        '! alpacon server ls',
        'timeout 60 alpacon websh my-server',
        'timeout -s KILL 60 alpacon websh my-server',
        'nice -n 10 alpacon server ls',
        'sudo -u root alpacon server ls',
        'bash -c "alpacon server ls"',
        "sh -lc 'cd /tmp; alpacon server ls'",
        'alpacon server ls 2>&1 | tee out.txt',
        "cat <<'EOF' > notes.txt\nnotes\nEOF\nalpacon server ls",
        'gh pr create --body "Refuse the `alpacon` CLI"',
        "bash <<'EOF'\nset -e\nalpacon server ls\nEOF",
        'cat <<EOF | sh\nalpacon server ls\nEOF',
        'sudo --user root alpacon server ls',
        'watch -n 5 alpacon server ls',
        'function f { alpacon server ls; }',
        'PATH=$HOME/bin:$PATH alpacon server ls',
        'ALPACON_URL=https://x.alpacon.io alpacon server ls',
        'X=a,b alpacon server ls',
        "watch -n 5 'alpacon server ls'",
        'stdbuf -oL alpacon server ls',
        'cd /tmp  # go to tmp\nalpacon server ls',
        "cd /tmp  # don't stay\nalpacon server ls",
        'stdbuf -o L alpacon server ls',
        'alpacon server ls \\\n  --output json',
        'sudo \\\n  alpacon server ls',
        '/usr/bin/env alpacon server ls',
        '# list servers\n\nalpacon server ls',
        '# list servers (prod)\nalpacon server ls',
        'cd /tmp # then;\nalpacon server ls',
        'diff <(alpacon server ls) old.txt',
        'sleep 1 & alpacon server ls',
        '>/dev/null alpacon server ls',
        'cat <<EOF | bash\nset -e  # strict\nalpacon server ls\nEOF',
    ],
)
def test_hook_refuses_a_command_that_runs_the_alpacon_cli(command):
    result = run_hook(command)

    assert result.returncode == 2
    assert 'mcp__alpacon' in result.stderr


@pytest.mark.parametrize(
    'command',
    [
        'grep -rn alpacon README.md',
        'uvx alpacon-mcp',
        'pip install alpacon-mcp',
        'git log --oneline -- plugins/alpacon',
        'echo "alpacon server ls"',
        'git commit -m "x; alpacon server ls"',
        "gh pr create --body 'Refuse the `alpacon` CLI in the hook'",
        'echo a && echo "b (alpacon c)"',
        "git commit -F - <<'EOF'\nfeat: guard\n\nalpacon is refused; don't run it\nEOF",
        'cat <<<"alpacon server ls"',
        'command -v alpacon',
        'echo done # alpacon server ls',
        'zip -r alpacon.zip \\\n  plugins/alpacon',
        'git log --oneline -- \\\n  plugins/alpacon',
        'grep -rn \\\n  alpacon README.md',
        'pytest -q 2>&1 | tail -5',
        'uvx alpacon-mcp &>/dev/null &',
        'cat <<\\EOF > notes.md\nalpacon server ls lists servers\nEOF',
        '# don\'t touch prod\ngh pr create --body "Fixes the hook.\nalpacon server ls is now refused"',
        'ls  # it\'s here\ngit commit -m "x\nalpacon is refused"',
        "git commit -m 'Block $(alpacon token ls) too'",
        "grep -rn '$(alpacon' tests",
        'ls $(git rev-parse --show-toplevel)/plugins/alpacon',
        'claude --plugin-dir "$(pwd)/plugins/alpacon"',
        'cd "$(git rev-parse --show-toplevel)/plugins/alpacon" && ls',
        'zip -r alpacon.zip "$(pwd)/plugins/alpacon"',
        'gh pr create --title "Refuse the CLI in the bash hook" --body "$(cat <<\'EOF\'\nalpacon is refused by the hook; it doesn\'t run\nEOF\n)"',
        "git commit -m \"$(cat <<'EOF'\nfix(hook): guard (part 1)\n\nalpacon is refused; 1) don't\nEOF\n)\"",
        '',
    ],
)
def test_hook_passes_a_command_that_only_mentions_alpacon(command):
    result = run_hook(command)

    assert result.returncode == 0
    assert result.stderr == ''


def test_hooks_json_runs_the_guard_script_on_bash():
    hooks = json.loads((PLUGIN / 'hooks' / 'hooks.json').read_text())

    (entry,) = hooks['hooks']['PreToolUse']

    assert entry['matcher'] == 'Bash'
    assert entry['hooks'][0]['command'].endswith(f'/hooks/{HOOK.name}"')
