"""Desktop signals never affect a tool's answer or transport output."""

import ast
import asyncio
import base64
import importlib
import json
import re
import subprocess
import threading
from copy import deepcopy
from html import escape
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import server
from tools import command_tools
from utils import local_signal
from utils.common import unwrap_http_result
from utils.decorators import mcp_tool_handler, with_error_handling
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
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(local_signal, '_limiter', local_signal.RateLimiter())
    monkeypatch.setattr('utils.local_signal.sys.platform', 'darwin')


async def drain_signals():
    if local_signal._tasks:
        await asyncio.gather(*local_signal._tasks)


@pytest.mark.parametrize(
    'workspace_url, url, kept',
    [
        ('https://alpacax.ap1.alpacon.io', 'https://alpacon.io/alpacax/1', False),
        ('https://alpacax.ap1.alpacon.io', 'https://alpacax.ap1.alpacon.io/1', True),
        ('http://10.0.0.5:8080', 'http://10.0.0.5:8080/1', True),
        ('http://10.0.0.5:8080', 'http://10.0.0.6:8080/1', False),
        ('https://alpacax.ap1.alpacon.io', 'https://evil-alpacon.io/1', False),
        ('https://alpacax.ap1.alpacon.io', 'https://alpacon.io.evil.com/1', False),
    ],
)
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
@pytest.mark.parametrize(
    'workspace_url, base_domain, url, kept',
    [
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://alpacon.io/alpacax/1',
            True,
        ),
        (
            'https://alpacax.ap1.alpacon.io',
            '',
            'https://alpacax.ap1.alpacon.io/1',
            True,
        ),
        ('http://10.0.0.5:8080', '', 'http://10.0.0.5:8080/1', True),
        ('http://10.0.0.5:8080', '', 'http://10.0.0.6:8080/1', False),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://evil-alpacon.io/1',
            False,
        ),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://alpacon.io.evil.com/1',
            False,
        ),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://alpacon.io:8443/1',
            False,
        ),
        ('https://alpacax.ap1.alpacon.io', 'alpacon.io', 'http://alpacon.io/1', False),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://user@alpacon.io/1',
            False,
        ),
        ('https://alpacax.ap1.alpacon.io', 'alpacon.io', 'file:///tmp/example', False),
        ('https://alpacax.ap1.alpacon.io', 'alpacon.io', 'javascript:alert(1)', False),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'search-ms:query=example',
            False,
        ),
        ('https://alpacax.ap1.alpacon.io', '', 'https://alpacon.io/alpacax/1', False),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://x.alpacon.io/1',
            True,
        ),
        (
            'https://alpacax.ap1.alpacon.io',
            'alpacon.io',
            'https://ALPACON.IO.:443/1',
            True,
        ),
        ('https://bücher.example', '', 'https://xn--bcher-kva.example/1', True),
        ('https://faß.example', '', 'https://xn--fa-hia.example/1', True),
        ('https://faß.example', '', 'https://fass.example/1', False),
        (
            'https://workspace.example',
            'bücher.example',
            'https://x.xn--bcher-kva.example/1',
            True,
        ),
        (
            'https://alpacax.ap1.alpacon.io',
            '',
            'https://alpacax.ap1.alpacon.io:443/1',
            True,
        ),
        ('http://10.0.0.5:8080', '', 'http://10.0.0.5/1', False),
        (
            'http://workspace.example:8080',
            'example',
            'http://console.example:80/1',
            True,
        ),
        (
            'http://workspace.example:8080',
            'example',
            'http://console.example:8080/1',
            False,
        ),
        ('http://10.0.0.5:8080', '', 'https://10.0.0.5:8080/1', False),
        ('https://alpacon.io', '', 'https://alpacon.io/\n1', False),
        ('https://alpacon.io', '', 'https://alpacon.io/\x851', False),
        ('https://alpacon.io', '', 'https://alpacon.io/\u200e1', False),
        ('https://alpacon.io', '', 'https://alpacon.io/' + 'x' * 2030, False),
        ('https://alpacon.io', '', 'https://alpacon.io/' + 'x' * 2029, True),
        ('https://alpacon.io', '', 'https://alpacon.io:invalid/1', False),
        ('https://alpacon.io', '', 'https://alpacon.io:65536/1', False),
        ('https://alpacon.io', '', 'https://alpacon.io:/1', False),
        ('https://alpacon.io', '', 'https://alpacon.io\\@evil.com/1', False),
        ('https://alpacon.io', '', '//alpacon.io/1', False),
        ('https://alpacon.io', '', '/1', False),
        ('https://[::1]:8443', '', 'https://[::1]:8443/1', True),
        ('https://alpacon.io', '', 'https://alpacon.io../1', False),
    ],
)
async def test_console_link_rule_on_every_platform(
    monkeypatch, capsys, platform, workspace_url, base_domain, url, kept
):
    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr(local_signal, 'notify', platform_notify)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name: '/usr/bin/notify-send'
    )
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    signal = local_signal.Signal(
        'denied', console_url=url, workspace_url=workspace_url, base_domain=base_domain
    )
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
            'Work Session session-1 is paused after a critical denial. The owner or an approver can resume or end it.',
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
        ('bad=name', ''),
        ('a' * 65, ''),
        ('/opt/雪/run', 'run'),
        ('雪', ''),
    ],
)
def test_argv0(command, expected):
    argv0 = local_signal.command_argv0(command)
    assert argv0 == expected
    text = ' '.join(local_signal.Signal('denied', argv0=argv0).text())
    for forbidden in ('=', 'hunter2', 'SECRET', 'abc123'):
        assert forbidden not in text


def test_windows_argv0(monkeypatch):
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    assert local_signal.command_argv0('"C:\\Program Files\\tool.exe" secret') == ''


def test_unknown_clauses_and_session_approval_text():
    assert (
        local_signal.Signal('denied').text()[1]
        == 'Command was refused and did not run.'
    )
    assert local_signal.Signal('approval_pending', session='Maintenance').text()[1] == (
        'Work Session Maintenance is waiting for approval. Open the approval or wait for an approver.'
    )
    assert local_signal.Signal('paused').text()[1].startswith('Work Session is paused')


@pytest.mark.parametrize(
    'platform, env, session_zero, expected',
    [
        ('darwin', {}, False, False),
        ('darwin', {'CI': ''}, False, False),
        ('darwin', {'CI': 'false'}, False, True),
        ('darwin', {'SSH_CONNECTION': ''}, False, True),
        ('darwin', {'SSH_TTY': '/dev/pts/1'}, False, True),
        ('linux', {}, False, True),
        ('linux', {'DISPLAY': ':0'}, False, True),
        ('linux', {'DBUS_SESSION_BUS_ADDRESS': 'unix:path=bus'}, False, True),
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
        'utils/local_signal.py': {
            'CI',
            'DISPLAY',
            'WAYLAND_DISPLAY',
            'DBUS_SESSION_BUS_ADDRESS',
        },
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
        tree = ast.parse(Path(path).read_text())
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
    assert env_reads == {
        'CI',
        'DISPLAY',
        'WAYLAND_DISPLAY',
        'DBUS_SESSION_BUS_ADDRESS',
        'SSH_CONNECTION',
        'SSH_TTY',
    }


@pytest.mark.parametrize('platform', ['darwin', 'linux', 'win32'])
def test_platform_invocation_keeps_values_as_data(monkeypatch, platform):
    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', platform)
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr(
        'utils.local_signal.shutil.which', lambda name: '/usr/bin/notify-send'
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
            'powershell.exe',
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
    monkeypatch.setattr('utils.local_signal.shutil.which', lambda name: None)
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
    )


@pytest.mark.asyncio
async def test_session_title_name_and_batch_folding(monkeypatch, desktop_notifications):
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
        'Work Session Maintenance is waiting for approval. Open the approval or wait for an approver.'
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
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['stdio', 'sse', 'streamable-http'])
async def test_only_stdio_run_enables_notifications(
    monkeypatch, desktop_notifications, transport
):
    monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'stdio')
    monkeypatch.setattr(server, 'prepare', Mock())
    payload = {'status': 'pending_approval'}

    def serve(**kwargs):
        local_signal.signal_result(payload, {}, tool_name='tool')

    monkeypatch.setattr(server.mcp, 'run', serve)
    if transport == 'streamable-http':
        server.create_streamable_http_app(host='127.0.0.1')
        serve()
    else:
        server.run(transport=transport)
    await drain_signals()
    assert desktop_notifications.call_count == (1 if transport == 'stdio' else 0)
    desktop_notifications.reset_mock()
    serve()
    await drain_signals()
    desktop_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_notifier_runs_off_loop_without_delaying_result(monkeypatch):
    started, release = threading.Event(), threading.Event()
    thread_ids = []
    loop_thread = threading.get_ident()

    def blocking_notifier(title, body, console_url=''):
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
    limiter._windows = {
        ('old', 'denied'): (0, 0),
        ('folded', 'denied'): (0, 2),
        ('future', 'denied'): (now[0] + 100, 4),
    }
    assert limiter.take('future', 'denied') == 0
    assert ('old', 'denied') not in limiter._windows
    assert ('folded', 'denied') not in limiter._windows
    assert limiter.take('folded', 'denied') == 0
    assert limiter.take('s' * 1000, 'denied') == 0
    assert limiter.take('s' * 128, 'denied') is None
    assert max(len(key[0]) for key in limiter._windows) <= 128
    now[0] += 24 * 60 * 60 + 1
    limiter.take('new', 'paused')
    assert ('future', 'denied') not in limiter._windows
    assert ('folded', 'denied') not in limiter._windows
    assert ('s' * 128, 'denied') not in limiter._windows
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


@pytest.mark.parametrize(
    'code',
    [
        'work_session_required',
        'work_session_not_usable',
        'work_session_expired',
        'work_session_scope_not_allowed',
        'work_session_server_not_allowed',
        'work_session_assignee_mismatch',
    ],
)
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
    assert signal.kind == 'denied'
    assert signal.gate == 'work_session'
    assert local_signal._from_result(result, {}, 'list_servers') is None
    result['gate'] = 'role'
    assert local_signal._from_result(result, {}, 'execute_command') is None
    result.pop('gate')
    result['status_code'] = 400
    assert local_signal._from_result(result, {}, 'execute_command') is None


@pytest.mark.parametrize('cause', ['approval_expired', 'approval_cancelled'])
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


@pytest.mark.parametrize('code', ['approval_expired', 'approval_cancelled'])
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
        {},
        'execute_command',
    )
    assert signal is not None
    assert signal.console_url == ''
    assert url not in signal.text()[1]
    assert local_signal.Signal('denied', console_url=url).console_url == ''

    run = Mock()
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    monkeypatch.setattr(local_signal, 'is_headless', lambda: False)
    monkeypatch.setattr('utils.local_signal.subprocess.run', run)
    platform_notify('title', 'body', url)
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
        'utils.local_signal.shutil.which', lambda name: '/usr/bin/notify-send'
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
    assert signal.account == 'root'
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

    def notifier(*args):
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


def test_command_controls_are_delimiters_before_cleaning():
    signal = local_signal._from_result(
        {'status': 'error', 'status_code': 403, 'gate': 'risk'},
        {'command': 'echo\tSECRET'},
        'execute_command',
    )
    assert signal is not None
    assert signal.argv0 == 'echo'
    assert 'SECRET' not in signal.text()[1]
