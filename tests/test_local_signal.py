"""Desktop signals never affect a tool's answer or transport output."""

import ast
import asyncio
import base64
import ctypes
import importlib
import json
import re
import shutil
import subprocess
import threading
from copy import deepcopy
from html import escape
from pathlib import Path
from time import perf_counter
from typing import get_args
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent

import server
from tests.conftest import streamable_http_client
from tools import command_tools
from utils import local_signal, mfa_step_up
from utils.common import (
    WorkSessionGateCode,
    unwrap_http_result,
    work_session_gate_response,
)
from utils.decorators import mcp_tool_handler, with_error_handling
from utils.error_handler import MfaStepUpRequired
from utils.http_client import http_client
from utils.local_signal import notify as platform_notify


@pytest.fixture(autouse=True)
def signal_environment(monkeypatch):
    for key in (
        'CI',
        'SSH_CONNECTION',
        'SSH_TTY',
        'DISPLAY',
        'WAYLAND_DISPLAY',
        'DBUS_SESSION_BUS_ADDRESS',
        'ALPACON_WORK_SESSION',
        'SystemRoot',
    ):
        monkeypatch.delenv(key, raising=False)

    def get_system_directory(buffer, size):
        buffer.value = r'C:\Windows\System32'
        return len(buffer.value)

    kernel = Mock()
    kernel.GetSystemDirectoryW.side_effect = get_system_directory
    monkeypatch.setattr(ctypes, 'windll', Mock(kernel32=kernel), raising=False)
    monkeypatch.setattr(local_signal, '_limiter', local_signal.RateLimiter())
    monkeypatch.setattr('utils.local_signal.sys.platform', 'darwin')
    return kernel


async def drain_signals():
    if local_signal._tasks:
        await asyncio.gather(*local_signal._tasks)


_CLOUD_WORKSPACE = 'https://alpacax.ap1.alpacon.io'
CONSOLE_LINK_CASES = [
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io/alpacax/x', True, id='cloud console'
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://alpacax.ap1.alpacon.io/commands/1',
        True,
        id='same workspace',
    ),
    pytest.param(
        'http://10.0.0.5:8080',
        'http://10.0.0.5:8080/commands/1',
        True,
        id='self hosted same origin',
    ),
    pytest.param(
        'http://10.0.0.5:8080',
        'http://10.0.0.6:8080/commands/1',
        False,
        id='self hosted different host',
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://evil-alpacon.io/', False, id='prefix lookalike'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io.evil.com/', False, id='suffix lookalike'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io:8443/', False, id='base nondefault port'
    ),
    pytest.param(_CLOUD_WORKSPACE, 'http://alpacon.io/', False, id='different scheme'),
    pytest.param(_CLOUD_WORKSPACE, 'https://alice@alpacon.io/', False, id='userinfo'),
    pytest.param(_CLOUD_WORKSPACE, 'file:///tmp/approval', False, id='file'),
    pytest.param(_CLOUD_WORKSPACE, 'javascript:alert%281%29', False, id='javascript'),
    pytest.param(_CLOUD_WORKSPACE, 'search-ms:query=approval', False, id='search'),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io/', True, id='built in cloud domain'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://other.ap1.alpacon.io/', True, id='cloud sibling'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://console.alpacon.io/', True, id='base subdomain'
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://CONSOLE.ALPACON.IO./',
        True,
        id='case and trailing dot',
    ),
    pytest.param(
        'https://bücher.example',
        'https://xn--bcher-kva.example/',
        False,
        id='non ASCII workspace',
    ),
    pytest.param(
        'https://xn--bcher-kva.example',
        'https://xn--bcher-kva.example/',
        True,
        id='ASCII punycode same host',
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://console.bücher.example/',
        False,
        id='non ASCII link host',
    ),
    pytest.param(
        'http://10.0.0.5:8080',
        'http://192.168.0.5/x',
        False,
        id='login derived IP base',
    ),
    pytest.param(
        'https://alpacon.corp.example.co.uk',
        'https://attacker.co.uk/',
        False,
        id='login derived public suffix',
    ),
    pytest.param(
        'https://alpacon.corp.example.co.uk',
        'https://ALPACON.CORP.EXAMPLE.CO.UK.:443/x',
        True,
        id='self hosted DNS same origin',
    ),
    pytest.param(
        'https://my-server.example',
        'https://alpacon.io/',
        False,
        id='cloud base on unrelated workspace',
    ),
    pytest.param(
        'https://10.0.0.5',
        'https://alpacon.io/',
        False,
        id='cloud base on IP workspace',
    ),
    pytest.param(
        'https://alpacon.io',
        'https://console.alpacon.io/',
        False,
        id='cloud base on apex workspace',
    ),
    pytest.param(
        'https://evil-alpacon.io',
        'https://alpacon.io/',
        False,
        id='workspace prefix lookalike',
    ),
    pytest.param(
        'https://alpacon.io.evil.com',
        'https://alpacon.io/',
        False,
        id='workspace suffix lookalike',
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://ａｌｐａｃｏｎ.io/', False, id='fullwidth host'
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://console。alpacon.io/',
        False,
        id='ideographic dot host',
    ),
    pytest.param(
        'http://10.0.0.5:8080',
        'http://[::ffff:10.0.0.5]:8080/x',
        False,
        id='mapped IPv6 against IPv4',
    ),
    pytest.param(
        'http://[::ffff:10.0.0.5]:8080',
        'http://[::ffff:10.0.0.5]:8080/x',
        False,
        id='mapped IPv6 same host',
    ),
    pytest.param(
        'http://[::ffff:a00:5]:8080',
        'http://[::ffff:10.0.0.5]:8080/x',
        False,
        id='mapped IPv6 spelling',
    ),
    pytest.param(
        'http://[::ffff:10.0.0.5]:8080',
        'http://10.0.0.5:8080/x',
        False,
        id='IPv4 against mapped IPv6 workspace',
    ),
    pytest.param(
        'http://[::1]:8080', 'http://[0:0:0:0:0:0:0:1]:8080/x', True, id='IPv6 spelling'
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://alpacax.ap1.alpacon.io:443/',
        True,
        id='same host default port',
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://alpacon.io:443/',
        True,
        id='base explicit default port',
    ),
    pytest.param(
        'http://my-server', 'http://my-server:80/', True, id='http default port'
    ),
    pytest.param(
        'http://10.0.0.5:8080', 'http://10.0.0.5/', False, id='same host wrong port'
    ),
    pytest.param('http://[::1]:8080', 'http://[::1]:8080/', True, id='IPv6 same host'),
    pytest.param(_CLOUD_WORKSPACE, 'https://alpacon.io/\x01', False, id='control'),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io/' + 'a' * 2048, False, id='too long'
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://alpacon.io/' + 'a' * (2048 - len('https://alpacon.io/')),
        True,
        id='at length limit',
    ),
    pytest.param(_CLOUD_WORKSPACE, '/commands/1', False, id='relative'),
    pytest.param(_CLOUD_WORKSPACE, 'https:///commands/1', False, id='no host'),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io/%zz', False, id='invalid escape'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io:65536/', False, id='invalid port'
    ),
    pytest.param(_CLOUD_WORKSPACE, 'https://alpacon.io:/', False, id='empty port'),
    pytest.param('', 'https://alpacon.io/', False, id='missing workspace'),
    pytest.param(
        'https://faß.example',
        'https://xn--fa-hia.example/1',
        False,
        id='sharp s workspace',
    ),
    pytest.param(
        'https://faß.example', 'https://fass.example/1', False, id='sharp s is not ss'
    ),
    pytest.param(
        'http://workspace.example:8080',
        'http://console.example:80/1',
        False,
        id='self hosted DNS different host',
    ),
    pytest.param(
        'http://workspace.example:8080',
        'http://console.example:8080/1',
        False,
        id='self hosted DNS different origin',
    ),
    pytest.param(
        'http://10.0.0.5:8080',
        'https://10.0.0.5:8080/1',
        False,
        id='IP different scheme',
    ),
    pytest.param(_CLOUD_WORKSPACE, 'https://alpacon.io/\n1', False, id='newline'),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io/\x851', False, id='non ASCII control'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io/\u200e1', False, id='format control'
    ),
    pytest.param(
        _CLOUD_WORKSPACE, 'https://alpacon.io:invalid/1', False, id='nonnumeric port'
    ),
    pytest.param(
        _CLOUD_WORKSPACE,
        'https://alpacon.io\\@evil.com/1',
        False,
        id='backslash userinfo',
    ),
    pytest.param(_CLOUD_WORKSPACE, '//alpacon.io/1', False, id='scheme relative'),
    pytest.param(
        'https://[::1]:8443', 'https://[::1]:8443/1', True, id='IPv6 custom port'
    ),
    pytest.param(
        'https://alpacon.io', 'https://alpacon.io../1', False, id='double trailing dot'
    ),
]


@pytest.mark.parametrize('workspace_url, url, kept', CONSOLE_LINK_CASES)
def test_console_link_uses_resolved_workspace_origin(
    monkeypatch, workspace_url, url, kept
):
    base_url = Mock(return_value=workspace_url)
    monkeypatch.setattr('utils.http_client.http_client.get_base_url', base_url)
    signal = local_signal._from_result(
        {'status': 'pending_approval', 'console_url': url},
        {'workspace': 'alpacax', 'region': 'ap1'},
        'execute_command',
    )
    assert signal is not None
    assert signal.console_url == (url if kept else '')
    base_url.assert_called_once_with('ap1', 'alpacax')


@pytest.mark.asyncio
@pytest.mark.parametrize('platform', ['darwin', 'linux', 'win32'])
@pytest.mark.parametrize('workspace_url, url, kept', CONSOLE_LINK_CASES)
async def test_console_link_rule_on_every_platform(
    monkeypatch, capsys, platform, workspace_url, url, kept
):
    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr(local_signal, 'notify', platform_notify)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name, **kwargs: '/usr/bin/notify-send'
    )
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    signal = local_signal.Signal('denied', console_url=url, workspace_url=workspace_url)
    assert signal.console_url == (url if kept else '')
    title, body = signal.text()
    await local_signal._deliver(title, body, signal)
    run.assert_called_once()
    command = run.call_args.args[0]
    if platform == 'win32':
        script = base64.b64decode(command[-1]).decode('utf-16-le')
        payload = re.search(r"FromBase64String\('([^']+)'\)", script)
        assert payload is not None
        arguments = json.loads(base64.b64decode(payload[1]))
        assert arguments == {
            'title': title,
            'body': body,
            'console_url': signal.console_url,
        }
    elif platform == 'linux':
        assert command[-2:] == [escape(title, quote=False), escape(body, quote=False)]
        arguments = command
    else:
        assert command[-2:] == [title, body]
        arguments = command
    if not kept:
        assert url not in json.dumps(arguments)
        assert body == local_signal.Signal('denied').text()[1]
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize(
    'kind, title, body',
    [
        (
            'denied',
            'Alpacon: command denied',
            'sudo on web-1 as root was refused by the risk gate and did not run. Session session-1.',
        ),
        (
            'approval_pending',
            'Alpacon: approval pending',
            'sudo on web-1 as root is waiting for approval. Session session-1. Open the approval or wait for an approver.',
        ),
        (
            'paused',
            'Alpacon: session paused',
            'Work Session session-1 is paused after a critical denial. Open the web console for the available recovery actions.',
        ),
    ],
)
def test_exact_text_and_command_privacy(kind, title, body):
    command = '/usr/bin/sudo deploy --secret confidential-value'
    signal = local_signal.Signal(
        kind,
        argv0=local_signal.command_argv0(command),
        server='web-1',
        account='root',
        gate='risk',
        session='session-1',
    )
    assert signal.text() == (title, body)
    assert signal.text(2) == (title, body + ' +2 more.')
    assert command not in body
    assert 'confidential-value' not in body


@pytest.mark.parametrize(
    'command, expected',
    [
        ('/usr/bin/sudo -u x id', 'sudo'),
        ('  echo secret', 'echo'),
        ('"/opt/my tools/run" secret', ''),
        ('/usr/bin/echo "unclosed argument', 'echo'),
        ('"unclosed command', ''),
        ('', ''),
        ('PGPASSWORD=hunter2 psql -h db', 'psql'),
        ('AWS_SECRET_ACCESS_KEY=abc123 aws s3 ls', 'aws'),
        ('"/opt/my tool/run --token=SECRET" x', ''),
        ('token=abc;curl x', ''),
        ('echo;cat /etc/shadow', 'echo'),
        ('echo\tSECRET', 'echo'),
        ('echo\nSECRET', 'echo'),
        ('PGPASSWORD="two words" OTHER=abc123 psql -h db', 'psql'),
        ("PGPASSWORD='two words' psql", 'psql'),
        ('X="$(printf "%s" "a b")" psql', ''),
        ('X=`printf a b` psql', ''),
        ('X="${HOME}" psql', ''),
        ('X="plain value" psql', 'psql'),
        ('X="plain" Y="$(printf "%s" "a b")" psql', ''),
        ("""X="plain 'value'" psql""", ''),
        ("""X='plain "value"' psql""", ''),
        (r'X="plain \"value\"" psql', ''),
        ('psql$(printf "%s" "a b")', ''),
        ('psql`printf a b`', ''),
        ('psql${HOME}', ''),
        ('psql$X$(printf a b)', ''),
        (r'psql\ $(printf a b)', ''),
        ('psql "$(printf a b)"', 'psql'),
        ('cu"rl" secret', ''),
        ("cu'rl' secret", ''),
        (r'cu\rl secret', ''),
        ('/opt/"tools"/curl secret', ''),
        ('curl" secret', ''),
        ("curl' secret", ''),
        (r'curl\ secret', ''),
        ('bad=name', ''),
        ('a' * 65, ''),
        ('/opt/雪/run', ''),
        ('雪', ''),
    ],
)
def test_argv0(command, expected):
    argv0 = local_signal.command_argv0(command)
    assert argv0 == expected
    text = ' '.join(local_signal.Signal('denied', argv0=argv0).text())
    for forbidden in ('=', 'hunter2', 'SECRET', 'abc123'):
        assert forbidden not in text
    assert not re.search(r'\b(?:a|b|printf)\b', text)


def test_windows_argv0(monkeypatch):
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    assert local_signal.command_argv0('"C:\\Program Files\\tool.exe" secret') == ''


def test_unknown_clauses_and_session_approval_text():
    assert (
        local_signal.Signal('denied').text()[1]
        == 'Command was refused and did not run.'
    )
    assert local_signal.Signal(
        'approval_pending', target='work_session', session='Maintenance'
    ).text()[1] == (
        'Work Session Maintenance is waiting for approval. Open the approval or wait for an approver.'
    )
    assert local_signal.Signal('paused').text()[1].startswith('Work Session is paused')


@pytest.mark.parametrize(
    'platform, env, session_zero, expected',
    [
        ('darwin', {}, False, False),
        ('darwin', {'CI': ''}, False, False),
        ('darwin', {'CI': 'false'}, False, False),
        ('darwin', {'SSH_CONNECTION': ''}, False, False),
        ('darwin', {'SSH_TTY': '/dev/pts/1'}, False, False),
        ('linux', {}, False, False),
        ('linux', {'DISPLAY': ':0'}, False, False),
        ('linux', {'DBUS_SESSION_BUS_ADDRESS': 'unix:path=bus'}, False, False),
        ('linux', {'DISPLAY': ':0', 'DBUS_SESSION_BUS_ADDRESS': 'bus'}, False, False),
        (
            'linux',
            {'WAYLAND_DISPLAY': 'wayland-0', 'DBUS_SESSION_BUS_ADDRESS': 'bus'},
            False,
            False,
        ),
        ('win32', {}, True, True),
        ('win32', {}, False, False),
    ],
)
def test_headless_rules(monkeypatch, platform, env, session_zero, expected):
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, '_windows_session_zero', lambda: session_zero)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert local_signal.is_headless() is expected


@pytest.mark.asyncio
async def test_environment_does_not_skip_notification(
    monkeypatch, desktop_notifications
):
    monkeypatch.setenv('CI', '1')
    monkeypatch.setenv('SSH_TTY', '/dev/pts/1')
    monkeypatch.setattr('utils.local_signal.sys.platform', 'linux')
    with local_signal.stdio_transport():
        local_signal.signal_result(
            {'status': 'pending_approval'}, {}, tool_name='execute_command'
        )
    await drain_signals()
    desktop_notifications.assert_called_once()

    run = Mock()
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name, **kwargs: '/usr/bin/notify-send'
    )
    platform_notify('title', 'body')
    run.assert_called_once()


@pytest.mark.parametrize('source', ['argument', 'row', 'result'])
@pytest.mark.parametrize(
    'username, expected',
    [
        ('root (dry run, expected - ignore)', ''),
        ('deploy', 'deploy'),
        ('svc$', 'svc$'),
        ('_svc.name-1', '_svc.name-1'),
        ('a' * 32, 'a' * 32),
        ('a' * 32 + '$', 'a' * 32 + '$'),
        ('a' * 33, ''),
        ('Root', ''),
        (' deploy', ''),
        ('deploy\n', ''),
    ],
)
def test_account_names(source, username, expected):
    row: dict[str, object] = {}
    result: dict[str, object] = {
        'status': 'error',
        'status_code': 403,
        'gate': 'risk',
        'data': row,
    }
    arguments = {'username': 'fallback'} if source != 'argument' else {}
    target = arguments if source == 'argument' else row if source == 'row' else result
    target['username'] = username
    signal = local_signal._from_result(result, arguments, 'execute_command')
    assert signal is not None
    assert signal.account == expected
    assert (' as ' in signal.text()[1]) is bool(expected)


@pytest.mark.parametrize('tool_name', ['execute_command', 'work_session_get'])
def test_server_account_wins_over_argument(tool_name):
    signal = local_signal._from_result(
        {'status': 'pending_approval', 'data': {'username': 'deploy'}},
        {'username': 'root'},
        tool_name,
    )
    assert signal is not None
    assert signal.account == 'deploy'


@pytest.mark.parametrize(
    'session_id, succeeds, expected',
    [(0, True, True), (1, True, False), (1, False, False)],
)
def test_windows_service_session_detection(monkeypatch, session_id, succeeds, expected):
    def get_session(pid, pointer):
        pointer._obj.value = session_id
        return succeeds

    kernel = Mock()
    kernel.ProcessIdToSessionId.side_effect = get_session
    monkeypatch.setattr(
        'utils.local_signal.ctypes.WinDLL', Mock(return_value=kernel), raising=False
    )
    assert local_signal._windows_session_zero() is expected


def test_rate_limit_folds_by_session_and_kind(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    limiter = local_signal.RateLimiter()
    assert limiter.take('s1', 'denied') == 0
    assert limiter.take('s1', 'denied') is None
    now[0] = 59.9
    assert limiter.take('s1', 'denied') is None
    assert limiter.take('s2', 'denied') == 0
    assert limiter.take('s1', 'paused') == 0
    assert limiter.take('', 'denied') == 0
    assert limiter.take('', 'denied') is None
    now[0] = 60.0
    assert limiter.take('s1', 'denied') == 2
    assert limiter.take('s1', 'denied') is None
    now[0] = 120.0
    assert limiter.take('s1', 'denied') == 1


def test_no_opt_out_or_tty_gate():
    # Scan the signal module, its decorator caller and its transport entry point.
    sources = {
        'utils/local_signal.py': None,
        'utils/notification_context.py': None,
        'utils/common.py': {'unwrap_http_result'},
        'tools/command_tools.py': {'_poll_command_result'},
        'utils/decorators.py': {'with_error_handling'},
        'server.py': {'run'},
    }
    approved_file_env_reads = {
        'utils/local_signal.py': set(),
        'utils/notification_context.py': set(),
        'utils/common.py': {
            'ALPACON_MCP_TRANSPORT',
            'ALPACON_MCP_AUTH_ENABLED',
            'ALPACON_WORK_SESSION',
            'REMOTE_LEDGER_ENV',
        },
        'tools/command_tools.py': set(),
        'utils/decorators.py': set(),
        'server.py': {
            'ALPACON_MCP_HOST',
            'ALPACON_MCP_PORT',
            'ALPACON_MCP_RESOURCE_URL',
            'TOOLSETS_ENV_VAR',
        },
    }
    env_reads = set()
    for path, functions in sources.items():
        tree = ast.parse((Path(__file__).parent.parent / path).read_text())
        file_env_reads = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name in ('os.environ.get', 'os.getenv'):
                    argument = node.args[0]
                    file_env_reads.add(
                        argument.value
                        if isinstance(argument, ast.Constant)
                        else ast.unparse(argument)
                    )
                if any(
                    word in name.lower()
                    for word in ('config', 'settings', 'argparse', 'isatty')
                ):
                    assert name == 'AuthSettings'
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                assert ast.unparse(node.value) != 'os.environ'
        assert file_env_reads == approved_file_env_reads[path]

        nodes = (
            [tree]
            if functions is None
            else [
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in functions
            ]
        )
        assert nodes
        for root in nodes:
            for node in ast.walk(root):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    assert not any(
                        word in name.lower()
                        for word in (
                            'getenv',
                            'isatty',
                            'argparse',
                            'config',
                            'settings',
                        )
                    )
                    if name == 'os.environ.get':
                        assert isinstance(node.args[0], ast.Constant)
                        env_reads.add(node.args[0].value)
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                    assert ast.unparse(node.value) != 'os.environ'
                if (
                    isinstance(node, ast.Compare)
                    and ast.unparse(node.comparators[-1]) == 'os.environ'
                ):
                    assert isinstance(node.left, ast.Constant)
                    env_reads.add(node.left.value)
    assert env_reads == set()


@pytest.mark.parametrize('platform', ['darwin', 'linux', 'win32'])
def test_platform_invocation_keeps_values_as_data(monkeypatch, platform):
    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name, **kwargs: '/usr/bin/notify-send'
    )
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    title, body = 'Alpacon: "title"', 'quotes " \\ ; $(touch unwanted) <>&'
    platform_notify(title, body)
    command = run.call_args.args[0]
    assert run.call_args.kwargs == {
        'timeout': 2,
        'check': True,
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
    }
    if platform == 'darwin':
        assert command[0] == '/usr/bin/osascript'
        assert command[-3:] == ['--', title, body]
        assert body not in command[2]
    elif platform == 'linux':
        assert command == [
            '/usr/bin/notify-send',
            '--app-name=Alpacon',
            '-u',
            'normal',
            '--',
            title,
            escape(body, quote=False),
        ]
    else:
        assert command[:4] == [
            r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
            '-NoProfile',
            '-NonInteractive',
            '-EncodedCommand',
        ]
        script = base64.b64decode(command[4]).decode('utf-16-le')
        assert script.startswith("$ErrorActionPreference = 'Stop'\n")
        payload = re.search(r"FromBase64String\('([^']+)'\)", script)
        assert payload is not None
        assert json.loads(base64.b64decode(payload[1])) == {
            'title': title,
            'body': body,
            'console_url': '',
        }
        assert body not in script
        assert '.InnerText = $data.body' in script
        assert 'Windows.UI.Notifications' in script


@pytest.mark.parametrize('reason', ['headless', 'missing_tool', 'unsupported'])
def test_platform_skip(monkeypatch, reason):
    run = Mock()
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: reason == 'headless')
    monkeypatch.setattr(
        'utils.local_signal.sys.platform',
        'other' if reason == 'unsupported' else 'linux',
    )
    monkeypatch.setattr('utils.local_signal.shutil.which', lambda name, **kwargs: None)
    platform_notify('title', 'body')
    run.assert_not_called()


@pytest.mark.parametrize(
    'error',
    [
        OSError('missing'),
        subprocess.TimeoutExpired('notifier', 2),
        subprocess.CalledProcessError(1, 'notifier'),
    ],
)
def test_platform_errors_never_raise(monkeypatch, error, capsys):
    monkeypatch.setattr('utils.local_signal.subprocess.run', Mock(side_effect=error))
    platform_notify('title', 'body')
    assert capsys.readouterr() == ('', '')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'result, expected_title',
    [
        (
            {'status': 'error', 'status_code': 403, 'gate': 'risk'},
            'Alpacon: command denied',
        ),
        (
            {
                'status': 'error',
                'rejection_gate': 'risk',
                'rejection_cause': 'risk_denied',
            },
            'Alpacon: command denied',
        ),
        (
            {'status': 'pending_approval', 'gate': 'approval'},
            'Alpacon: approval pending',
        ),
        (
            {'status': 'error', 'error_code': 'session_paused', 'gate': 'work_session'},
            'Alpacon: session paused',
        ),
        ({'status': 'error', 'code': 'session_paused'}, 'Alpacon: session paused'),
        ({'status': 'error', 'error_code': 'auth_failed'}, None),
        ({'status': 'error', 'error_code': 'validation'}, None),
        ({'status': 'error', 'message': 'network failure'}, None),
        ({'status': 'success', 'gate': 'risk'}, None),
    ],
)
async def test_hook_classification_and_unchanged_result(
    desktop_notifications, result, expected_title, capsys
):
    original = deepcopy(result)

    @with_error_handling
    async def execute_command(command, username='root', work_session_id='s1'):
        return result

    with local_signal.stdio_transport():
        answer = await execute_command('/usr/bin/sudo --secret hidden')
    await drain_signals()
    assert answer is result
    assert answer == original
    if expected_title:
        assert desktop_notifications.call_args.args[0] == expected_title
        assert 'hidden' not in desktop_notifications.call_args.args[1]
        assert ' on ' not in desktop_notifications.call_args.args[1]
    else:
        desktop_notifications.assert_not_called()
    assert capsys.readouterr() == ('', '')


@pytest.mark.asyncio
async def test_validated_arguments_and_http_refusal(
    monkeypatch, mock_token_manager, desktop_notifications
):
    monkeypatch.setattr(server.mcp, 'tool', Mock(return_value=lambda func: func))

    @mcp_tool_handler(description='Signal test')
    async def execute_command(
        workspace,
        command,
        server_id,
        username='root',
        work_session_id=None,
        region='',
        **kwargs,
    ):
        return unwrap_http_result(
            {
                'error': 'HTTP Error',
                'status_code': 403,
                'response': '{"code":"risk_denied","gate":"risk"}',
            },
            default_message='Refused',
        )

    monkeypatch.setenv('ALPACON_WORK_SESSION', 'default-session')
    with local_signal.stdio_transport():
        invalid = await execute_command('ws', '/bin/sudo hidden', 'invalid')
        assert invalid['field'] == 'server_id'
        desktop_notifications.assert_not_called()
        result = await execute_command(
            'ws', '/bin/sudo hidden', '550e8400-e29b-41d4-a716-446655440001'
        )
    await drain_signals()
    assert result['gate'] == 'risk'
    desktop_notifications.assert_called_once_with(
        'Alpacon: command denied',
        'sudo as root was refused by the risk gate and did not run. Session default-session.',
        '',
        workspace_url='',
    )


@pytest.mark.asyncio
async def test_session_id_and_batch_folding(monkeypatch, desktop_notifications):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    with local_signal.stdio_transport():
        local_signal.signal_result(
            {
                'status': 'pending_approval',
                'data': {'id': 's1', 'title': 'Maintenance'},
            },
            {},
            tool_name='work_session_create',
        )
        batch = {
            'deploy_shell_results': {
                str(i): {
                    'status': 'error',
                    'status_code': 403,
                    'gate': 'risk',
                    'server_name': 'web-1',
                }
                for i in range(3)
            }
        }
        arguments = {'command': '/bin/id hidden', 'work_session_id': 's1'}
        local_signal.signal_result(
            batch, arguments, tool_name='execute_command_multi_server'
        )
        now[0] = 60
        local_signal.signal_result(
            batch['deploy_shell_results']['0'], arguments, tool_name='execute_command'
        )
    await drain_signals()
    bodies = [call.args[1] for call in desktop_notifications.call_args_list]
    assert (
        'Work Session s1 is waiting for approval. Open the approval or wait for an approver.'
    ) in bodies
    assert (
        'id on web-1 was refused by the risk gate and did not run. Session s1. +2 more.'
    ) in bodies
    assert desktop_notifications.call_count == 3


@pytest.mark.asyncio
async def test_command_context_already_in_result(desktop_notifications):
    with local_signal.stdio_transport():
        local_signal.signal_result(
            {
                'status': 'error',
                'rejection_gate': 'risk',
                'details': {
                    'status': 'rejected',
                    'command': '/usr/bin/sudo secret',
                    'username': 'operator',
                    'server': {'id': 'server-id', 'name': 'web-1'},
                    'work_session': 's1',
                },
            },
            {},
            tool_name='state_command_purpose',
        )
    await drain_signals()
    desktop_notifications.assert_called_once_with(
        'Alpacon: command denied',
        'sudo on web-1 as operator was refused by the risk gate and did not run. Session s1.',
        '',
        workspace_url='',
    )


@pytest.mark.asyncio
async def test_only_stdio_run_enables_notifications(monkeypatch, desktop_notifications):
    monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'stdio')
    monkeypatch.setattr(server, 'prepare', Mock())
    payload = {'status': 'pending_approval'}

    def serve(**kwargs):
        local_signal.signal_result(payload, {}, tool_name='tool')

    monkeypatch.setattr(server.mcp, 'run', serve)
    server.run(transport='stdio')
    await drain_signals()
    assert desktop_notifications.call_count == 1
    desktop_notifications.reset_mock()
    # Outside the stdio run, as in the streamable-http app, nothing is raised.
    serve()
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_run_refuses_streamable_http_without_enabling_notifications(
    monkeypatch, desktop_notifications
):
    monkeypatch.setattr(server, 'prepare', Mock())
    with pytest.raises(RuntimeError):
        server.run(transport='streamable-http')  # type: ignore[arg-type]
    local_signal.signal_result({'status': 'pending_approval'}, {}, tool_name='tool')
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_notifier_runs_off_loop_without_delaying_result(monkeypatch):
    started, release = threading.Event(), threading.Event()
    thread_ids = []
    loop_thread = threading.get_ident()

    def blocking_notifier(title, body, console_url='', *, workspace_url=''):
        thread_ids.append(threading.get_ident())
        started.set()
        release.wait(timeout=3)

    monkeypatch.setattr(local_signal, 'notify', blocking_notifier)

    @with_error_handling
    async def tool():
        return {'status': 'pending_approval'}

    try:
        with local_signal.stdio_transport():
            assert await tool() == {'status': 'pending_approval'}
        assert not release.is_set()
        assert await asyncio.to_thread(started.wait, 1)
        assert len(thread_ids) == 1
        assert thread_ids[0] != loop_thread
    finally:
        release.set()
        await drain_signals()


@pytest.mark.asyncio
async def test_background_failure_is_swallowed(monkeypatch, capsys):
    monkeypatch.setattr(
        local_signal, 'notify', Mock(side_effect=RuntimeError('failed'))
    )
    result = {'status': 'pending_approval'}

    @with_error_handling
    async def tool():
        return result

    with local_signal.stdio_transport():
        assert await tool() is result
    await drain_signals()
    assert capsys.readouterr() == ('', '')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'error', [OSError('missing'), subprocess.TimeoutExpired('notifier', 2)]
)
async def test_platform_failure_keeps_tool_result(monkeypatch, error, capsys):
    monkeypatch.setattr('utils.local_signal.subprocess.run', Mock(side_effect=error))
    monkeypatch.setattr(local_signal, 'notify', platform_notify)
    result = {'status': 'pending_approval', 'data': {'id': 's1'}}
    original = deepcopy(result)

    @with_error_handling
    async def tool():
        return result

    with local_signal.stdio_transport():
        answer = await tool()
    await drain_signals()
    assert answer is result
    assert answer == original
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('failure', ['missing', 'load', 'call'])
def test_windows_session_detection_failure_attempts_notification(monkeypatch, failure):
    loader = Mock()
    if failure == 'load':
        loader.side_effect = OSError('unavailable')
    elif failure == 'call':
        loader.return_value.ProcessIdToSessionId.side_effect = OSError('unavailable')
    monkeypatch.setattr(
        'utils.local_signal.ctypes.WinDLL',
        None if failure == 'missing' else loader,
        raising=False,
    )
    assert local_signal._windows_session_zero() is False


def test_rate_state_expiration_key_cap_and_pruning(monkeypatch):
    now = [100_000.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    limiter = local_signal.RateLimiter()
    limiter._windows.update(
        {
            ('old', 'denied', '', ''): (0, 0, set()),
            ('folded', 'denied', '', ''): (0, 2, set()),
        }
    )
    assert limiter.take('new', 'denied') == 0
    assert ('old', 'denied', '', '') not in limiter._windows
    assert ('folded', 'denied', '', '') not in limiter._windows
    assert limiter.take('folded', 'denied') == 0
    assert limiter.take('s' * 1000, 'denied') == 0
    assert limiter.take('s' * 128, 'denied') is None
    assert max(len(key[0]) for key in limiter._windows) <= 128
    now[0] += 24 * 60 * 60 + 1
    limiter.take('new', 'paused')
    assert ('folded', 'denied', '', '') not in limiter._windows
    assert ('s' * 128, 'denied', '', '') not in limiter._windows
    assert limiter.take('s' * 128, 'denied') == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_name', sorted(local_signal.DENIAL_TOOLS))
async def test_denial_tools_only_on_refusal(desktop_notifications, tool_name):
    result = {'status': 'error', 'status_code': 403, 'gate': 'risk'}
    with local_signal.stdio_transport():
        local_signal.signal_result(result, {}, tool_name=tool_name)
    await drain_signals()
    desktop_notifications.assert_called_once()


@pytest.mark.asyncio
async def test_denial_tool_allowlist_is_registered():
    for module in server.ALL_TOOL_MODULES | server.ALWAYS_ON_MODULES:
        importlib.import_module(f'{server.TOOLS_PACKAGE}.{module}')
    registered = {tool.name for tool in await server.mcp.list_tools()}
    assert local_signal.DENIAL_TOOLS <= registered
    assert local_signal.SUDO_PENDING_TOOLS <= registered


@pytest.mark.parametrize(
    'gate',
    [
        'server_reach',
        'command_preapproval',
        'command_acl',
        'file_acl',
        'risk',
        'approval',
        'sudo',
        'work_session',
        'block',
        'plan',
        'rate',
        'token_scope',
        'role',
        'presence',
        'network',
        'future_gate',
        '',
    ],
)
@pytest.mark.parametrize('shape', ['http', 'row', 'details', 'flat', 'raw_row'])
def test_denial_gate_allowlist(gate, shape):
    allowed = {
        'server_reach',
        'command_preapproval',
        'command_acl',
        'file_acl',
        'risk',
        'approval',
        'sudo',
        'work_session',
        'block',
    }
    row = {
        'status': 'rejected',
        'rejection_gate': gate,
        'rejection_cause': 'risk_denied',
    }
    if shape == 'http':
        result = {'status': 'error', 'status_code': 403, 'gate': gate}
    elif shape == 'row':
        result = {'status': 'success', 'data': row}
    elif shape == 'details':
        result = {'status': 'error', 'details': row}
    elif shape == 'flat':
        result = {**row, 'status': 'error'}
    else:
        result = row
    signal = local_signal._from_result(result, {}, 'execute_command')
    assert (signal is not None) is (gate in allowed)
    if signal is not None:
        assert signal.kind == 'denied'
        assert signal.gate == gate


@pytest.mark.parametrize('code', get_args(WorkSessionGateCode.__value__))
def test_work_session_code_without_gate_is_denied(code):
    result = unwrap_http_result(
        {
            'error': 'HTTP Error',
            'status_code': 403,
            'response': json.dumps({'code': code}),
        },
        default_message='Refused',
    )
    assert result is not None
    signal = local_signal._from_result(result, {}, 'execute_command')
    assert signal is not None
    if code == 'work_session_not_active':
        assert signal.kind == 'approval_pending'
        return
    assert signal.kind == 'denied'
    assert signal.gate == 'work_session'
    assert local_signal._from_result(result, {}, 'list_servers') is None
    result['gate'] = 'role'
    assert local_signal._from_result(result, {}, 'execute_command') is None
    result.pop('gate')
    result['status_code'] = 400
    assert local_signal._from_result(result, {}, 'execute_command') is None


@pytest.mark.parametrize(
    'cause', ['approval_expired', 'approval_cancelled', 'approval_rule_changed']
)
@pytest.mark.parametrize('shape', ['http', 'row', 'details', 'flat'])
def test_approval_lapse_never_denies(cause, shape):
    row = {'status': 'rejected', 'rejection_gate': 'approval', 'rejection_cause': cause}
    if shape == 'http':
        result = {
            'status': 'error',
            'status_code': 403,
            'gate': 'approval',
            'rejection_cause': cause,
        }
    elif shape == 'row':
        result = {'status': 'success', 'data': row}
    elif shape == 'details':
        result = {'status': 'error', 'details': row}
    else:
        result = {**row, 'status': 'error'}
    assert local_signal._from_result(result, {}, 'execute_command') is None


@pytest.mark.parametrize(
    'code', ['approval_expired', 'approval_cancelled', 'approval_rule_changed']
)
@pytest.mark.parametrize('field', ['error_code', 'code'])
@pytest.mark.parametrize('shape', ['http', 'row', 'details', 'flat'])
def test_approval_lapse_code_never_denies(code, field, shape):
    row: dict[str, object] = {'status': 'rejected', 'rejection_gate': 'approval'}
    if shape == 'http':
        result = {'status': 'error', 'status_code': 403, 'gate': 'approval'}
    elif shape == 'row':
        result = {'status': 'success', 'data': row}
    elif shape == 'details':
        result = {'status': 'error', 'details': row}
    else:
        result = row
    result['code' if field == 'error_code' else 'error_code'] = 'approval_denied'
    result[field] = code
    assert local_signal._from_result(result, {}, 'execute_command') is None


@pytest.mark.parametrize('status', ['success', 'running', 'awaiting_purpose'])
def test_rejection_gate_alone_is_not_a_rejected_command(status):
    result = {'status': 'success', 'data': {'status': status, 'rejection_gate': 'risk'}}
    assert local_signal._from_result(result, {}, 'execute_command') is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name',
    [
        'list_servers',
        'get_system_info',
        'work_session_get',
        'list_commands',
        'webftp_session_create',
        'webftp_check_status',
        'list_api_tokens',
    ],
)
@pytest.mark.parametrize(
    'result',
    [
        {'status': 'error', 'status_code': 403, 'gate': 'risk'},
        {'status': 'error', 'status_code': 402, 'gate': 'plan', 'axis': 'server'},
        {'status': 'error', 'rejection_gate': 'risk'},
    ],
)
async def test_non_command_tools_never_deny(desktop_notifications, tool_name, result):
    with local_signal.stdio_transport():
        local_signal.signal_result(result, {}, tool_name=tool_name)
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'result',
    [
        {'status': 'error', 'gate': 'risk'},
        {'status': 'error', 'status_code': 402, 'gate': 'plan'},
        {'status': 'error', 'status_code': 429, 'gate': 'rate'},
        {'status': 'error', 'status_code': 401, 'gate': 'risk'},
        {'status': 'error', 'status_code': 400, 'gate': 'risk'},
        {'status': 'error', 'status_code': 503, 'gate': 'risk'},
        *[
            {'status': 'error', 'status_code': 403, 'gate': gate}
            for gate in ('token_scope', 'role', 'presence', 'auth', 'plan', 'rate')
        ],
        *[
            {
                'status': 'error',
                'status_code': 403,
                'gate': 'approval',
                'error_code': code,
            }
            for code in (
                'auth_mfa_required',
                'auth_token_mfa_missing',
                'validation',
                'auth_failed',
            )
        ],
        {
            'status': 'error',
            'status_code': 403,
            'gate': 'approval',
            'missing': 'presence',
        },
        {
            'status': 'error',
            'status_code': 403,
            'gate': 'approval',
            'missing': ['presence'],
        },
        {'status': 'mfa_required', 'gate': 'presence'},
        {'status': 'error', 'error_type': 'network'},
    ],
)
async def test_non_refusal_errors_never_deny(desktop_notifications, result):
    with local_signal.stdio_transport():
        local_signal.signal_result(result, {}, tool_name='execute_command')
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'row',
    [
        {'status': 'rejected', 'rejection_gate': 'risk'},
        {
            'status': 'rejected',
            'rejection_gate': 'approval',
            'rejection_cause': 'approval_rejected',
        },
    ],
)
async def test_rejected_command_row(desktop_notifications, row):
    with local_signal.stdio_transport():
        local_signal.signal_result(
            {'status': 'success', 'data': row}, {}, tool_name='execute_command'
        )
    await drain_signals()
    desktop_notifications.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'result',
    [
        {'status': 'error', 'status_code': 403, 'gate': 'risk'},
        {'status': 'error', 'error_code': 'session_paused'},
        {'status': 'pending_approval'},
        {'status': 'success', 'data': {'status': 'rejected', 'rejection_gate': 'risk'}},
    ],
)
async def test_console_link_from_response(desktop_notifications, result):
    url = 'https://example.ap1.alpacon.io/session/1'
    target = result.get('data', result)
    target['console_url'] = url
    original = deepcopy(result)
    with local_signal.stdio_transport():
        local_signal.signal_result(
            result,
            {'workspace': 'example', 'region': 'ap1'},
            tool_name='execute_command',
        )
    await drain_signals()
    title, body, link = desktop_notifications.call_args.args
    assert url in body
    assert link == url
    assert result == original


def test_long_console_link_does_not_truncate_body():
    signal = local_signal.Signal(
        'denied',
        console_url='https://alpacon.io/' + 'x' * 256,
        workspace_url='https://alpacon.io',
    )
    assert signal.console_url
    assert signal.text() == local_signal.Signal('denied').text()
    assert 'http' not in local_signal.Signal('denied').text()[1]


@pytest.mark.parametrize(
    'url',
    [
        'file:///tmp/example',
        'search-ms:query=example',
        'ms-settings:privacy',
        'http://alpacon.io/example',
        '/example/commands/1',
        'javascript:alert(1)',
        'https:///example',
        'https://',
        'https://[]/example',
        '//alpacon.io/example',
    ],
)
def test_invalid_console_url_is_dropped(monkeypatch, url):
    signal = local_signal._from_result(
        {'status': 'error', 'status_code': 403, 'gate': 'risk', 'console_url': url},
        {'workspace': 'example', 'region': 'ap1'},
        'execute_command',
    )
    assert signal is not None
    assert signal.console_url == ''
    assert url not in signal.text()[1]
    assert (
        local_signal.Signal(
            'denied', console_url=url, workspace_url=_CLOUD_WORKSPACE
        ).console_url
        == ''
    )

    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    platform_notify('title', 'body', url, workspace_url=_CLOUD_WORKSPACE)
    script = base64.b64decode(run.call_args.args[0][-1]).decode('utf-16-le')
    payload = re.search(r"FromBase64String\('([^']+)'\)", script)
    assert payload is not None
    assert json.loads(base64.b64decode(payload[1]))['console_url'] == ''


@pytest.mark.parametrize('platform', ['darwin', 'linux', 'win32'])
def test_platform_cleans_controls_and_linux_markup(monkeypatch, platform):
    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name, **kwargs: '/usr/bin/notify-send'
    )
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    controls = ''.join(
        chr(c)
        for c in [
            *range(32),
            127,
            0x200E,
            0x200F,
            *range(0x202A, 0x202F),
            *range(0x2066, 0x206A),
        ]
    )
    title, body, url = 'A&<B>', 'body&<text>', 'https://alpacon.io/example?a=1&b=2'
    platform_notify(
        title + controls, body + controls, url, workspace_url='https://alpacon.io'
    )
    command = run.call_args.args[0]
    if platform == 'win32':
        script = base64.b64decode(command[-1]).decode('utf-16-le')
        payload = re.search(r"FromBase64String\('([^']+)'\)", script)
        assert payload is not None
        assert json.loads(base64.b64decode(payload[1])) == {
            'title': title,
            'body': body,
            'console_url': url,
        }
        assert "SetAttribute('launch', $data.console_url)" in script
        assert "SetAttribute('activationType', 'protocol')" in script
        assert (
            "CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe')"
            in script
        )
    elif platform == 'linux':
        assert command[-2:] == [escape(title, quote=False), escape(body, quote=False)]
    else:
        assert command[-2:] == [title, body]
    assert url not in command


def test_server_fields_are_cleaned():
    signal = local_signal._from_result(
        {
            'status': 'error',
            'status_code': 403,
            'gate': 'ri\u202ask',
            'server_name': 'we\x1bb',
            'console_url': 'https://example.ap1.alpacon.io/\u200ex',
        },
        {
            'username': 'ro\x00ot',
            'work_session_id': 's\u20661',
            'workspace': 'example',
            'region': 'ap1',
        },
        'execute_command',
    )
    assert signal is not None
    assert signal.server == 'web'
    assert signal.account == ''
    assert signal.session == 's1'
    assert signal.console_url == ''


@pytest.mark.asyncio
async def test_remote_call_does_not_bind_signal_arguments(monkeypatch):
    signature = Mock()
    monkeypatch.setattr(
        'utils.decorators.inspect.signature', Mock(return_value=signature)
    )

    @with_error_handling
    async def tool():
        return {'status': 'success'}

    assert await tool() == {'status': 'success'}
    signature.bind.assert_not_called()


@pytest.mark.asyncio
async def test_decorator_pending_approval_in_mfa_holder_signals_once(
    desktop_notifications,
):
    result = {'status': 'pending_approval', 'data': {'message': 'original'}}
    original = deepcopy(result)

    @with_error_handling
    async def tool():
        with mfa_step_up.tool_call() as nested:
            assert nested is None
        return result

    with local_signal.stdio_transport():
        answer = await tool()
    await drain_signals()
    assert answer is result
    assert answer == original
    desktop_notifications.assert_called_once()


@pytest.mark.asyncio
async def test_decorator_mfa_step_up_returns_link_without_notification(
    monkeypatch, desktop_notifications
):
    link = 'https://tenant.auth0.com/authorize?ticket=test'
    fetch = AsyncMock(return_value={'mfa_url': link})
    monkeypatch.setattr(http_client, 'get', fetch)

    async def refuse(*args, **kwargs):
        mfa_step_up.record('command')
        raise MfaStepUpRequired('command')

    post = AsyncMock(side_effect=refuse)
    monkeypatch.setattr(http_client, 'post', post)

    @with_error_handling
    async def tool(workspace='example', region='ap1'):
        return await http_client.post(region, workspace, '/api/events/commands/')

    with local_signal.stdio_transport():
        answer = await tool()
    await drain_signals()
    assert answer['status'] == 'mfa_required'
    assert answer['mfa_url'] == link
    assert answer['source'] == 'command'
    post.assert_awaited_once_with('ap1', 'example', '/api/events/commands/')
    fetch.assert_awaited_once_with(
        'ap1',
        'example',
        '/api/auth0/mfa/',
        token=None,
        params={'location': 'cli', 'workspace': 'example'},
    )
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_decorator_mfa_call_tool_result_is_unchanged_without_notification(
    desktop_notifications,
):
    body = {'status': 'mfa_link_shown'}
    result = CallToolResult(
        content=[TextContent(type='text', text=json.dumps(body))],
        structured_content=body,
    )
    original = result.model_dump()

    @with_error_handling
    async def tool():
        return result

    with local_signal.stdio_transport():
        answer = await tool()
    await drain_signals()
    assert answer is result
    assert answer.model_dump() == original
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_package_fixture_never_invokes_platform_notifier(
    desktop_notifications, monkeypatch
):
    real_sink = Mock(side_effect=AssertionError('platform notifier reached'))
    monkeypatch.setattr('utils.local_signal.subprocess.run', real_sink)
    with local_signal.stdio_transport():
        local_signal.signal_result({'status': 'pending_approval'}, {}, tool_name='tool')
    await drain_signals()
    desktop_notifications.assert_called_once()
    real_sink.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['raise', 'hang'])
async def test_fail_open_result_bytes_match_no_signal(monkeypatch, capsys, failure):
    started, release = threading.Event(), threading.Event()
    result = {
        'status': 'pending_approval',
        'data': {'message': 'original', 'bytes': [0, 255]},
    }

    @with_error_handling
    async def tool():
        return deepcopy(result)

    baseline = json.dumps(await tool(), ensure_ascii=False).encode()
    baseline_output = capsys.readouterr()

    def notifier(*args, **kwargs):
        started.set()
        if failure == 'raise':
            raise OSError('unavailable')
        release.wait(timeout=3)

    monkeypatch.setattr(local_signal, 'notify', notifier)
    try:
        with local_signal.stdio_transport():
            answer = await asyncio.wait_for(tool(), timeout=1)
        assert json.dumps(answer, ensure_ascii=False).encode() == baseline
        assert capsys.readouterr() == baseline_output
        assert await asyncio.to_thread(started.wait, 1)
    finally:
        release.set()
        await drain_signals()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'code, gate',
    [
        ('risk_denied', 'risk'),
        ('session_paused', 'work_session'),
        ('work_session_not_active', 'work_session'),
    ],
)
async def test_upstream_refusal_link_preserves_tool_response(
    desktop_notifications, code, gate
):
    url = 'https://example.ap1.alpacon.io/sessions/1'
    raw = {
        'error': 'HTTP Error',
        'status_code': 403,
        'response': json.dumps({'code': code, 'gate': gate, 'console_url': url}),
    }

    @with_error_handling
    async def execute_command(workspace='example', region='ap1'):
        return unwrap_http_result(raw, default_message='Refused')

    baseline = json.dumps(await execute_command()).encode()
    with local_signal.stdio_transport():
        result = await execute_command()
    await drain_signals()
    assert json.dumps(result).encode() == baseline
    assert 'console_url' not in result
    assert desktop_notifications.call_args.args[2] == url
    assert url in desktop_notifications.call_args.args[1]


@pytest.mark.asyncio
async def test_pending_command_row_link_preserves_tool_response(
    monkeypatch, desktop_notifications
):
    url = 'https://example.ap1.alpacon.io/commands/1'
    monkeypatch.setattr(
        command_tools,
        '_get_command_result',
        AsyncMock(return_value={'status': 'awaiting_approval', 'console_url': url}),
    )

    @with_error_handling
    async def execute_command(workspace='example', region='ap1'):
        return await command_tools._poll_command_result(
            'cmd-1', 'example', 1, 'ap1', None
        )

    baseline = json.dumps(await execute_command()).encode()
    with local_signal.stdio_transport():
        result = await execute_command()
    await drain_signals()
    assert json.dumps(result).encode() == baseline
    assert 'console_url' not in result
    assert desktop_notifications.call_args.args[2] == url


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_name', sorted(local_signal.SUDO_PENDING_TOOLS))
async def test_completed_sudo_pending_row_preserves_result_and_rate_limit(
    monkeypatch, desktop_notifications, tool_name
):
    row = {
        'status': 'failed',
        'handled_at': '2026-11-02T00:00:00Z',
        'result': 'Alpacon denied this sudo command (SUDO_APPROVAL_REQUIRED).',
        'command': '/usr/bin/sudo id',
        'server': {'name': 'web-1'},
        'username': 'operator',
        'work_session': 'session-1',
    }
    monkeypatch.setattr(
        command_tools, '_get_command_result', AsyncMock(return_value=row)
    )
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    deliver = AsyncMock()
    monkeypatch.setattr(local_signal, '_deliver', deliver)

    async def poll(workspace='example', region='ap1'):
        return await command_tools._poll_command_result(
            'cmd-1', workspace, 1, region, None
        )

    poll.__name__ = tool_name
    tool = with_error_handling(poll)
    baseline = await tool()
    baseline_bytes = json.dumps(baseline).encode()
    assert baseline['status'] == 'success'
    assert baseline['sudo_denial']['status'] == 'pending_approval'
    with local_signal.stdio_transport():
        result = await tool()
        repeated = await tool()
    await drain_signals()
    assert json.dumps(result).encode() == baseline_bytes
    assert json.dumps(repeated).encode() == baseline_bytes
    assert result['data'] is row
    deliver.assert_awaited_once()
    title, body, signal = deliver.call_args.args
    assert signal.kind == 'approval_pending'
    assert (signal.argv0, signal.server, signal.account, signal.session_id) == (
        'sudo',
        'web-1',
        'operator',
        'session-1',
    )
    assert title == 'Alpacon: approval pending'
    assert body == (
        'sudo on web-1 as operator is waiting for approval. Session session-1. '
        'Open the approval or wait for an approver.'
    )
    now[0] = 60
    with local_signal.stdio_transport():
        assert await tool() == baseline
    await drain_signals()
    deliver.assert_awaited_once()
    assert ' more.' not in deliver.call_args.args[1]
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['SUDO_APPROVAL_REQUIRED', 'SUDO_RISK_DENIED'])
async def test_history_sudo_guidance_preserves_result(
    monkeypatch, mock_token_manager, desktop_notifications, code
):
    row = {
        'status': 'failed',
        'handled_at': '2026-11-02T00:00:00Z',
        'result': f'Alpacon denied this sudo command ({code}).',
        'command': '/usr/bin/sudo id',
        'server': {'name': 'web-1'},
        'username': 'operator',
        'work_session': 'session-1',
    }
    monkeypatch.setattr(
        http_client,
        'get',
        AsyncMock(side_effect=lambda **kwargs: {'results': [deepcopy(row)]}),
    )
    baseline = await command_tools.list_commands(workspace='example', region='ap1')
    with local_signal.stdio_transport():
        result = await command_tools.list_commands(workspace='example', region='ap1')
        repeated = await command_tools.list_commands(workspace='example', region='ap1')
    await drain_signals()
    assert json.dumps(result).encode() == json.dumps(baseline).encode()
    assert repeated == baseline
    desktop_notifications.assert_not_called()


def test_command_controls_are_delimiters_before_cleaning():
    signal = local_signal._from_result(
        {'status': 'error', 'status_code': 403, 'gate': 'risk'},
        {'command': 'echo\tSECRET'},
        'execute_command',
    )
    assert signal is not None
    assert signal.argv0 == 'echo'
    assert 'SECRET' not in signal.text()[1]


@pytest.mark.parametrize(
    'separator', ['\u00a0', '\u2003', '\u3000', '\u0085', '\x1c', '\u2028']
)
def test_argv0_omits_non_ascii_and_controls(separator):
    assert local_signal.command_argv0(f'TOKEN=abc{separator}sk_live_X') == ''
    assert local_signal.command_argv0(f'echo{separator}secret') == ''
    assert local_signal.command_argv0(f'{separator}echo') == ''


def test_argv0_input_limit_and_linear_assignment_scan():
    command = 'X=a ' * 256 + 'echo'
    assert local_signal.command_argv0(command) == 'echo'
    assert local_signal.command_argv0(' ' * 4092 + 'echo') == 'echo'
    assert local_signal.command_argv0(' ' * 4093 + 'echo') == ''
    command = 'X=a ' * (128 * 1024) + 'echo'
    started = perf_counter()
    assert local_signal.command_argv0(command) == ''
    assert perf_counter() - started < 0.05


@pytest.mark.parametrize(
    'suffix',
    [
        '/a b https://evil.example/x',
        '/\u00a0',
        '/\u2028',
        '/a#fragment',
        '/a#',
        '/caf\u00e9',
    ],
)
def test_console_link_rejects_raw_display_characters(suffix):
    origin = 'https://example.ap1.alpacon.io'
    assert (
        local_signal.Signal(
            'denied', console_url=origin + suffix, workspace_url=origin
        ).console_url
        == ''
    )


@pytest.mark.parametrize(
    'session', ['a b', ' s1 ', 'https://example.com', 'a' * 65, '雪']
)
def test_session_clause_omits_invalid_id(session):
    assert (
        local_signal.Signal('paused', session=session).text()
        == local_signal.Signal('paused').text()
    )
    signal = local_signal._from_result(
        {'status': 'pending_approval', 'work_session_id': session},
        {},
        'execute_command',
    )
    assert signal is not None
    assert signal.session == ''


def test_work_session_signal_uses_id_instead_of_title():
    signal = local_signal._from_result(
        {
            'status': 'pending_approval',
            'data': {'id': 'session-1', 'title': 'Maintenance title'},
        },
        {},
        'work_session_create',
    )
    assert signal is not None
    assert signal.session == 'session-1'
    assert 'Maintenance' not in signal.text()[1]


def test_server_and_account_display_limits():
    signal = local_signal.Signal('denied', server='雪' * 65, account='a' * 65)
    assert signal.server == '雪' * 64
    assert signal.account == ''
    assert len(signal.text()[1]) <= 256
    assert (
        local_signal.Signal(
            'denied', server='https://example.com', account='http://example.com'
        ).text()
        == local_signal.Signal('denied').text()
    )


@pytest.mark.parametrize(
    'character', ['\x85', '\u061c', '\u200b', '\ufeff', '\u00ad', '\u2028', '\u2029']
)
def test_all_display_values_strip_unicode_controls(character):
    assert local_signal.clean(f'a{character}b') == 'ab'
    signal = local_signal.Signal(
        'denied',
        argv0=f'e{character}cho',
        server=f'we{character}b',
        account=f'ro{character}ot',
        gate=f'ri{character}sk',
        session=f's{character}1',
    )
    assert (
        signal.text()
        == local_signal.Signal(
            'denied',
            argv0='echo',
            server='web',
            account='',
            gate='risk',
            session='s1',
        ).text()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('session_id', ['', 'session-1'])
async def test_rate_limit_is_scoped_to_workspace_and_region(
    desktop_notifications,
    session_id,
):
    with local_signal.stdio_transport():
        for workspace, region in [
            ('one', 'ap1'),
            ('two', 'ap1'),
            ('one', 'us1'),
            ('one', 'ap1'),
        ]:
            local_signal.signal_result(
                {'status': 'error', 'status_code': 403, 'gate': 'risk'},
                {
                    'workspace': workspace,
                    'region': region,
                    'work_session_id': session_id,
                },
                tool_name='execute_command',
            )
    await drain_signals()
    assert desktop_notifications.call_count == 3


def test_linux_notifier_ignores_path(monkeypatch, tmp_path):
    fake = tmp_path / 'notify-send'
    fake.write_text('#!/bin/sh\nexit 1\n')
    fake.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path))
    monkeypatch.setattr('utils.local_signal.sys.platform', 'linux')
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    run = Mock()
    which = Mock(wraps=shutil.which)
    monkeypatch.setattr('utils.local_signal.shutil.which', which)
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    platform_notify('title', 'body')
    which.assert_called_once_with('notify-send', path='/usr/bin:/bin')
    if run.called:
        assert run.call_args.args[0][0] in ('/usr/bin/notify-send', '/bin/notify-send')


@pytest.mark.parametrize('system_root', [None, '', '.', r'C:\Windows', r'E:\Other'])
def test_windows_notifier_uses_os_system_directory(
    monkeypatch, system_root, signal_environment
):
    if system_root is not None:
        monkeypatch.setenv('SystemRoot', system_root)

    def get_system_directory(buffer, size):
        assert size == len(buffer)
        buffer.value = r'D:\Windows\System32'
        return len(buffer.value)

    kernel = signal_environment
    kernel.GetSystemDirectoryW.side_effect = get_system_directory
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    run = Mock()
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    platform_notify('title', 'body')
    kernel.GetSystemDirectoryW.assert_called_once()
    assert run.call_args.args[0][0] == (
        r'D:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    )


@pytest.mark.parametrize('length', [0, 32768, 32769])
def test_windows_system_directory_failure_is_silent(
    monkeypatch, length, capsys, signal_environment
):
    kernel = signal_environment
    kernel.GetSystemDirectoryW.side_effect = None
    kernel.GetSystemDirectoryW.return_value = length
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    run = Mock()
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    platform_notify('title', 'body')
    run.assert_not_called()
    assert capsys.readouterr() == ('', '')


@pytest.mark.asyncio
@pytest.mark.parametrize('platform', ['darwin', 'linux', 'win32'])
async def test_console_link_is_reserialized_for_every_display(monkeypatch, platform):
    origin = 'https://example.ap1.alpacon.io'
    url = origin + '/approval'
    signal = local_signal.Signal(
        'denied',
        console_url='HTTPS://example.ap1.alpacon.io/approval?',
        workspace_url=origin,
    )
    assert signal.console_url == url
    title, body = signal.text()
    assert body.endswith(' ' + url)
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr(local_signal, 'notify', platform_notify)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name, **kwargs: '/usr/bin/notify-send'
    )
    run = Mock()
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    await local_signal._deliver(title, body, signal)
    command = run.call_args.args[0]
    if platform == 'win32':
        script = base64.b64decode(command[-1]).decode('utf-16-le')
        payload = re.search(r"FromBase64String\('([^']+)'\)", script)
        assert payload is not None
        data = json.loads(base64.b64decode(payload[1]))
        assert data['console_url'] == url
        assert data['body'] == body
    else:
        assert command[-1] == body


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_name', ['list_commands', 'list_servers'])
@pytest.mark.parametrize(
    'result',
    [
        {'status': 'pending_approval'},
        {'status': 'error', 'code': 'session_paused'},
        {'sudo_denial': {'status': 'pending_approval'}},
    ],
)
async def test_list_tools_never_signal(desktop_notifications, tool_name, result):
    with local_signal.stdio_transport():
        local_signal.signal_result(result, {}, tool_name=tool_name)
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_explain_approval_decision_never_signals(desktop_notifications):
    with local_signal.stdio_transport():
        local_signal.signal_result(
            {'status': 'pending_approval', 'category': 'APPROVAL_DECISION_HUMAN_ONLY'},
            {},
            tool_name='explain_approval_decision',
        )
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.parametrize(
    'tool_name, result, arguments, subject',
    [
        ('execute_file', {'status': 'pending_approval'}, {}, 'Command'),
        (
            'execute_command',
            {'status': 'pending_approval'},
            {'command': 'cu"rl" secret'},
            'Command',
        ),
        (
            'request_sudo_policy',
            {'status': 'pending_approval', 'category': 'SUDO_POLICY_REQUEST_PENDING'},
            {},
            'Sudo policy request',
        ),
        (
            'webftp_upload_content',
            {'status': 'error', 'status_code': 403, 'gate': 'file_acl'},
            {},
            'File transfer',
        ),
    ],
)
def test_signal_target_comes_from_tool(tool_name, result, arguments, subject):
    signal = local_signal._from_result(result, arguments, tool_name)
    assert signal is not None
    title, body = signal.text()
    assert body.startswith(subject + ' ')
    assert 'Work Session' not in body
    if subject == 'File transfer':
        assert title == 'Alpacon: file transfer denied'
        assert 'was refused by the file_acl gate' in body
    else:
        assert 'is waiting for approval' in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'result, title',
    [
        (
            {'status': 'error', 'status_code': 403, 'gate': 'risk'},
            'Alpacon: command denied',
        ),
        (
            {'status': 'success', 'sudo_denial': {'status': 'pending_approval'}},
            'Alpacon: approval pending',
        ),
        (
            {
                'status': 'error',
                'details': {'status': 'denied', 'rejection_gate': 'risk'},
            },
            'Alpacon: command denied',
        ),
    ],
)
async def test_check_command_status_refusals_notify(
    desktop_notifications, result, title
):
    original = json.dumps(result).encode()
    with local_signal.stdio_transport():
        local_signal.signal_result(
            result, {'command_id': 'cmd-1'}, tool_name='check_command_status'
        )
    await drain_signals()
    desktop_notifications.assert_called_once()
    assert desktop_notifications.call_args.args[0] == title
    assert json.dumps(result).encode() == original


@pytest.mark.asyncio
async def test_pending_command_polling_notifies_once(
    monkeypatch, desktop_notifications
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    result = {'status': 'pending_approval', 'command_id': 'cmd-1'}
    with local_signal.stdio_transport():
        for seconds in range(0, 121, 10):
            now[0] = seconds
            local_signal.signal_result(result, {}, tool_name='check_command_status')
        await drain_signals()
        desktop_notifications.assert_called_once()
        now[0] = 130
        local_signal.signal_result(
            {**result, 'command_id': 'cmd-2'}, {}, tool_name='check_command_status'
        )
    await drain_signals()
    assert desktop_notifications.call_count == 2
    assert all(
        '+N more' not in call.args[1] and ' more.' not in call.args[1]
        for call in desktop_notifications.call_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, result, arguments',
    [
        (
            'execute_command',
            {'status': 'rejected', 'gate': 'risk', 'command_id': 'cmd-1'},
            {},
        ),
        (
            'check_command_status',
            {
                'status': 'error',
                'details': {'status': 'denied', 'rejection_gate': 'risk'},
            },
            {'command_id': 'cmd-1'},
        ),
        (
            'webftp_upload_file',
            {'status': 'rejected', 'gate': 'file_acl', 'data': {'id': 'transfer-1'}},
            {},
        ),
    ],
)
async def test_denied_item_polling_notifies_once_until_expiry(
    monkeypatch, desktop_notifications, tool_name, result, arguments
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    original = json.dumps(result).encode()
    with local_signal.stdio_transport():
        for seconds in [0, 10, 20, 70, 599]:
            now[0] = seconds
            local_signal.signal_result(result, arguments, tool_name=tool_name)
        await drain_signals()
        desktop_notifications.assert_called_once()
        now[0] = 600
        local_signal.signal_result(result, arguments, tool_name=tool_name)
        now[0] = 610
        local_signal.signal_result(result, arguments, tool_name=tool_name)
    await drain_signals()
    assert desktop_notifications.call_count == 2
    assert all(
        ' more.' not in call.args[1] for call in desktop_notifications.call_args_list
    )
    assert json.dumps(result).encode() == original


@pytest.mark.asyncio
async def test_pending_then_denied_command_announces_both(
    monkeypatch, desktop_notifications
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    with local_signal.stdio_transport():
        for seconds, status in [
            (0, 'pending_approval'),
            (10, 'rejected'),
            (20, 'rejected'),
            (70, 'rejected'),
        ]:
            now[0] = seconds
            local_signal.signal_result(
                {'status': status, 'command_id': 'cmd-1', 'gate': 'risk'},
                {},
                tool_name='check_command_status',
            )
            await drain_signals()
    await drain_signals()
    assert [call.args[0] for call in desktop_notifications.call_args_list] == [
        'Alpacon: approval pending',
        'Alpacon: command denied',
    ]
    assert all(
        ' more.' not in call.args[1] for call in desktop_notifications.call_args_list
    )


def test_fold_suffix_survives_body_limit():
    signal = local_signal.Signal(
        'approval_pending',
        argv0='a' * 64,
        server='s' * 64,
        account='u' * 32,
        session='i' * 64,
    )
    body = signal.text(123)[1]
    assert len(body) == 256
    assert body.endswith(' +123 more.')


@pytest.mark.asyncio
async def test_streamable_http_pending_tool_never_notifies(
    authenticated_mcp: MCPServer[None], desktop_notifications: Mock
) -> None:
    payload = {'status': 'pending_approval', 'command_id': 'cmd-1'}

    @authenticated_mcp.tool()
    @with_error_handling
    async def pending_signal() -> dict[str, str]:
        return payload

    async with streamable_http_client() as client:
        response = await client.post(
            '/mcp',
            headers={'Accept': 'application/json, text/event-stream'},
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {'name': 'pending_signal', 'arguments': {}},
            },
        )
    assert response.status_code == 200, response.text
    assert json.loads(response.json()['result']['content'][0]['text']) == payload
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, result, arguments',
    [
        ('execute_file', {'status': 'pending_approval', 'command_id': 'item-1'}, {}),
        (
            'check_command_status',
            {
                'status': 'success',
                'data': {'id': 'item-1'},
                'sudo_denial': {'status': 'pending_approval'},
            },
            {},
        ),
        (
            'state_command_purpose',
            {'status': 'pending_approval'},
            {'command_id': 'item-1'},
        ),
        (
            'work_session_get',
            {'status': 'pending_approval', 'data': {'id': 'item-1'}},
            {},
        ),
        (
            'request_sudo_policy',
            {
                'status': 'pending_approval',
                'category': 'SUDO_POLICY_REQUEST_PENDING',
                'data': {'id': 'item-1'},
            },
            {},
        ),
    ],
)
async def test_pending_item_identity_and_workspace_scope(
    monkeypatch, desktop_notifications, tool_name, result, arguments
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    original = json.dumps(result).encode()
    with local_signal.stdio_transport():
        for workspace, region in [('one', 'ap1'), ('two', 'ap1'), ('one', 'us1')]:
            args = {**arguments, 'workspace': workspace, 'region': region}
            local_signal.signal_result(result, args, tool_name=tool_name)
            now[0] += 60
            local_signal.signal_result(result, args, tool_name=tool_name)
    await drain_signals()
    assert desktop_notifications.call_count == 3
    assert all(
        ' more.' not in call.args[1] for call in desktop_notifications.call_args_list
    )
    assert json.dumps(result).encode() == original


@pytest.mark.parametrize('kind', ['approval_pending', 'denied'])
def test_pending_identity_cache_is_bounded_and_oldest_evicted(monkeypatch, kind):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    limiter = local_signal.RateLimiter()
    for index in range(256):
        assert limiter.take(str(index), kind, pending_id=str(index)) == 0
        now[0] += 1
    assert limiter.take('', kind, pending_id='0') is None
    assert limiter.take('', kind, pending_id='256') == 0
    now[0] += 60
    assert limiter.take('', kind, pending_id='0') == 0
    assert limiter.take('', kind, pending_id='256') is None
    assert len(limiter._pending) == 256


def test_duplicate_pending_item_does_not_fold_or_suppress_denials(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    limiter = local_signal.RateLimiter()
    assert limiter.take('', 'approval_pending', pending_id='one') == 0
    assert limiter.take('', 'approval_pending', pending_id='one') is None
    assert limiter.take('', 'approval_pending', pending_id='two') is None
    assert limiter.take('', 'denied', pending_id='one') == 0
    assert limiter.take('', 'paused', pending_id='one') == 0
    now[0] = 60
    assert limiter.take('', 'approval_pending', pending_id='one') is None
    assert limiter.take('', 'approval_pending', pending_id='two') == 0
    assert limiter.take('', 'approval_pending', pending_id='two') is None
    assert limiter.take('', 'approval_pending', pending_id='three') is None
    now[0] = 120
    assert limiter.take('', 'approval_pending', pending_id='three') == 0
    assert limiter.take('', 'denied', pending_id='one') is None
    assert limiter.take('', 'paused', pending_id='one') == 0


@pytest.mark.asyncio
async def test_folded_pending_item_notifies_on_later_read(
    monkeypatch, desktop_notifications
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    with local_signal.stdio_transport():
        for seconds, command_id in [
            (0, 'cmd-A'),
            (10, 'cmd-B'),
            (70, 'cmd-B'),
            (130, 'cmd-B'),
        ]:
            now[0] = seconds
            local_signal.signal_result(
                {'status': 'pending_approval', 'command_id': command_id},
                {},
                tool_name='check_command_status',
            )
    await drain_signals()
    assert desktop_notifications.call_count == 2
    assert all(
        ' more.' not in call.args[1] for call in desktop_notifications.call_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['approval_pending', 'denied'])
async def test_repeated_folded_pending_item_counts_once(
    monkeypatch, desktop_notifications, kind
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    with local_signal.stdio_transport():
        for seconds, command_id in [
            (0, 'cmd-A'),
            *[(10 + i, 'cmd-B') for i in range(5)],
            (70, 'cmd-C'),
        ]:
            now[0] = seconds
            local_signal.signal_result(
                {
                    'status': 'pending_approval'
                    if kind == 'approval_pending'
                    else 'rejected',
                    'gate': 'risk',
                    'command_id': command_id,
                },
                {},
                tool_name='check_command_status',
            )
    await drain_signals()
    assert desktop_notifications.call_count == 2
    assert desktop_notifications.call_args_list[1].args[1].endswith(' +1 more.')


@pytest.mark.asyncio
@pytest.mark.parametrize('expiry', [600, 601])
async def test_announced_work_session_notifies_after_ten_minutes(
    monkeypatch, desktop_notifications, expiry
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    result = {'status': 'pending_approval', 'data': {'id': 'session-1'}}
    with local_signal.stdio_transport():
        local_signal.signal_result(result, {}, tool_name='work_session_get')
        await drain_signals()
        desktop_notifications.assert_called_once()
        now[0] = 300
        local_signal.signal_result(result, {}, tool_name='work_session_get')
        await drain_signals()
        desktop_notifications.assert_called_once()
        now[0] = expiry
        local_signal.signal_result(result, {}, tool_name='work_session_get')
        now[0] += 1
        local_signal.signal_result(result, {}, tool_name='work_session_get')
    await drain_signals()
    assert desktop_notifications.call_count == 2
    assert all(
        ' more.' not in call.args[1] for call in desktop_notifications.call_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('first_tool', ['execute_command', 'webftp_upload_file'])
@pytest.mark.parametrize('session_source', ['result', 'row', 'argument', 'environment'])
async def test_work_session_pending_through_other_tools_uses_session_identity(
    monkeypatch, desktop_notifications, first_tool, session_source
):
    now = [0.0]
    monkeypatch.setattr(local_signal, 'monotonic', lambda: now[0])
    monkeypatch.setenv(
        'ALPACON_WORK_SESSION',
        'session-1' if session_source == 'environment' else 'fallback',
    )
    result = work_session_gate_response('work_session_not_active')
    arguments = {'command': 'ls', 'work_session_id': 'argument-session'}
    if session_source == 'result':
        result['work_session_id'] = 'session-1'
    elif session_source == 'row':
        result['data'] = {'work_session_id': 'session-1'}
    elif session_source == 'argument':
        arguments['work_session_id'] = 'session-1'
    else:
        arguments.pop('work_session_id')
    with local_signal.stdio_transport():
        for seconds, tool_name in [
            (0, first_tool),
            (
                70,
                'webftp_upload_file'
                if first_tool == 'execute_command'
                else 'execute_command',
            ),
        ]:
            now[0] = seconds
            result['command_id'] = f'cmd-{seconds}'
            original = json.dumps(result).encode()
            local_signal.signal_result(result, arguments, tool_name=tool_name)
            assert json.dumps(result).encode() == original
    await drain_signals()
    desktop_notifications.assert_called_once()
    title, body, *_ = desktop_notifications.call_args.args
    assert title == 'Alpacon: approval pending'
    assert body.startswith('Work Session session-1 is waiting for approval.')
    assert ' more.' not in body


def test_assignee_confirmation_text_is_the_persons_own():
    url = 'https://example.ap1.alpacon.io/commands/1'
    signal = local_signal.Signal(
        'approval_pending',
        argv0='systemctl',
        server='web-1',
        account='root',
        session='session-1',
        lane='assignee',
        console_url=url,
        workspace_url='https://example.ap1.alpacon.io',
    )
    assert signal.text() == (
        'Alpacon: confirmation pending',
        'systemctl on web-1 as root needs your own confirmation. '
        'Session session-1. Confirm or reject it in the Alpacon web console. ' + url,
    )


@pytest.mark.parametrize('lane', ['assignee', 'single_approver'])
def test_approval_pending_keeps_the_console_link_with_ordinary_identifiers(lane):
    url = (
        'https://my-workspace.ap1.alpacon.io/commands/'
        '7c9e6679-7425-40de-944b-e07fc1f90ae7'
    )
    signal = local_signal.Signal(
        'approval_pending',
        argv0='systemctl',
        server='prod-web-server-01',
        account='www-data',
        session='3f2b8c1e-9a4d-4e7b-8c2a-1d5e6f7a8b9c',
        lane=lane,
        console_url=url,
        workspace_url='https://my-workspace.ap1.alpacon.io',
    )

    _, body = signal.text()

    assert body.endswith(' ' + url)


@pytest.mark.parametrize('folded', [0, 123])
@pytest.mark.parametrize('lane', ['assignee', 'single_approver'])
@pytest.mark.parametrize(
    'argv0, server, account, session',
    [
        (
            'systemctl',
            'production-web-server-0001',
            'www-data',
            '3f2b8c1e-9a4d-4e7b-8c2a-1d5e6f7a8b9c',
        ),
        ('a' * 64, 's' * 64, 'u' * 32, 'i' * 64),
    ],
)
def test_approval_pending_body_yields_to_the_console_link(
    argv0, server, account, session, lane, folded
):
    url = (
        'https://my-workspace.ap1.alpacon.io/commands/'
        '7c9e6679-7425-40de-944b-e07fc1f90ae7'
    )
    signal = local_signal.Signal(
        'approval_pending',
        argv0=argv0,
        server=server,
        account=account,
        session=session,
        lane=lane,
        console_url=url,
        workspace_url='https://my-workspace.ap1.alpacon.io',
    )

    _, body = signal.text(folded)

    assert len(body) <= 256
    assert body.endswith(' ' + url)
    assert body.startswith(f'{argv0} on {server}')
    if folded:
        assert f' +{folded} more. ' in body


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_name', ['execute_command', 'check_command_status'])
@pytest.mark.parametrize(
    'lane, title, body',
    [
        (
            'assignee',
            'Alpacon: confirmation pending',
            (
                'Command needs your own confirmation. '
                'Confirm or reject it in the Alpacon web console.'
            ),
        ),
        (
            'single_approver',
            'Alpacon: approval pending',
            (
                'Command is waiting for approval. Open the approval or wait for an '
                'approver.'
            ),
        ),
        (
            None,
            'Alpacon: approval pending',
            (
                'Command is waiting for approval. Open the approval or wait for an '
                'approver.'
            ),
        ),
    ],
)
async def test_held_command_notification_by_lane(
    monkeypatch, desktop_notifications, tool_name, lane, title, body
):
    url = 'https://example.ap1.alpacon.io/commands/1'
    row: dict[str, object] = {
        'id': 'cmd-1',
        'status': 'awaiting_approval',
        'handled_at': None,
        'console_url': url,
    }
    if lane is not None:
        row['approval_lane'] = lane
    monkeypatch.setattr(
        command_tools, '_get_command_result', AsyncMock(return_value=row)
    )

    async def poll(workspace='example', region='ap1', command_id='cmd-1'):
        return await command_tools._poll_command_result(
            'cmd-1', 'example', 1, 'ap1', None
        )

    # The hook reads the tool name at decoration.
    poll.__name__ = tool_name
    call = with_error_handling(poll)
    with local_signal.stdio_transport():
        result = await call()
    await drain_signals()
    assert 'console_url' not in result
    desktop_notifications.assert_called_once()
    sent_title, sent_body, link = desktop_notifications.call_args.args
    assert (sent_title, sent_body) == (title, f'{body} {url}')
    assert link == url


@pytest.mark.asyncio
async def test_assignee_confirmation_keeps_the_rate_limit(desktop_notifications):
    pending = {'status': 'pending_approval', 'approval_lane': 'assignee'}
    with local_signal.stdio_transport():
        for command_id in ('cmd-1', 'cmd-2', 'cmd-3'):
            local_signal.signal_result(
                {**pending, 'command_id': command_id, 'work_session_id': 's1'},
                {},
                tool_name='execute_command',
            )
    await drain_signals()
    desktop_notifications.assert_called_once()
