"""
Decide between starting the stdio server and running the setup wizard.

The wizard writes to stdout and reads stdin, which are the JSON-RPC channel
when an MCP client launches main.py, so it must run only when nothing is
configured and a person is at a terminal.
"""

import os
import sys
from pathlib import Path

import pytest

import main


@pytest.fixture
def unconfigured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No token file, no ALPACON_MCP_* variable, cwd without config/."""
    for name in list(os.environ):
        if name.startswith('ALPACON_MCP_'):
            monkeypatch.delenv(name)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_nothing_configured(unconfigured):
    assert main.check_token_exists() is False


def test_workspace_token_variable_counts(unconfigured, monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AP1_PRODUCTION_TOKEN', 'alpat-x')
    assert main.check_token_exists() is True


def test_empty_workspace_token_variable_does_not_count(unconfigured, monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AP1_PRODUCTION_TOKEN', '')
    assert main.check_token_exists() is False


def test_unrelated_alpacon_variable_does_not_count(unconfigured, monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AP1_PRODUCTION_URL', 'https://example.com')
    assert main.check_token_exists() is False


def test_config_file_variable_counts(unconfigured, monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_CONFIG_FILE', str(unconfigured / 'tokens.json'))
    assert main.check_token_exists() is True


def test_global_token_file_counts(unconfigured):
    token_file = unconfigured / '.alpacon-mcp' / 'token.json'
    token_file.parent.mkdir()
    token_file.write_text('{}')
    assert main.check_token_exists() is True


class _Stdin:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _run_main(monkeypatch, *, tty: bool) -> list[str]:
    """Run main() with no arguments; return the wizard calls it made."""
    calls: list[str] = []
    monkeypatch.setattr(sys, 'argv', ['main.py'])
    monkeypatch.setattr(sys, 'stdin', _Stdin(tty))
    monkeypatch.setattr(
        'utils.setup_wizard.run_setup_wizard',
        lambda **kwargs: calls.append('wizard'),
    )
    monkeypatch.setattr(main, 'run', lambda *a, **k: calls.append('server'))
    main.main()
    return calls


def test_client_launch_without_tokens_exits_without_touching_stdout(
    unconfigured, monkeypatch, capsys
):
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tty=False)

    assert exc.value.code == 1
    assert capsys.readouterr().out == ''


def test_terminal_launch_without_tokens_runs_the_wizard(unconfigured, monkeypatch):
    assert _run_main(monkeypatch, tty=True) == ['wizard']


def test_client_launch_with_env_token_starts_the_server(unconfigured, monkeypatch):
    monkeypatch.setenv('ALPACON_MCP_AP1_PRODUCTION_TOKEN', 'alpat-x')
    assert _run_main(monkeypatch, tty=False) == ['server']
