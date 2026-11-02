"""Desktop signals never affect a tool's answer or transport output."""

import asyncio
import base64
import inspect
import json
import re
import subprocess
import threading
from copy import deepcopy
from unittest.mock import Mock

import pytest

import server
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
        ('/usr/bin/sudo -u root id', 'sudo'),
        ('  echo secret', 'echo'),
        ('"/opt/my tools/run" secret', 'run'),
        ('/usr/bin/echo "unclosed argument', 'echo'),
        ('"unclosed command', ''),
        ('', ''),
    ],
)
def test_argv0(command, expected):
    assert local_signal.command_argv0(command) == expected


def test_windows_argv0(monkeypatch):
    monkeypatch.setattr('utils.local_signal.sys.platform', 'win32')
    assert (
        local_signal.command_argv0('"C:\\Program Files\\tool.exe" secret') == 'tool.exe'
    )


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
    [(0, True, True), (1, True, False), (1, False, True)],
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
    source = inspect.getsource(local_signal)
    env_reads = set(re.findall(r"os\.environ\.get\('([^']+)'", source))
    assert env_reads == {'CI', 'DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'}
    assert set(re.findall(r"'([^']+)' in os\.environ", source)) == {
        'SSH_CONNECTION',
        'SSH_TTY',
    }
    assert 'getenv(' not in source
    assert 'isatty' not in source
    assert 'argparse' not in source


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
            body,
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
        ({'status': 'error', 'gate': 'risk'}, 'Alpacon: command denied'),
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
    async def tool(command, username='root', work_session_id='s1'):
        return result

    with local_signal.stdio_transport():
        answer = await tool('/usr/bin/sudo --secret hidden')
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
    async def tool(
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
        invalid = await tool('ws', '/bin/sudo hidden', 'invalid')
        assert invalid['field'] == 'server_id'
        desktop_notifications.assert_not_called()
        result = await tool(
            'ws', '/bin/sudo hidden', '550e8400-e29b-41d4-a716-446655440001'
        )
    await drain_signals()
    assert result['gate'] == 'risk'
    desktop_notifications.assert_called_once_with(
        'Alpacon: command denied',
        'sudo as root was refused by the risk gate and did not run. Session default-session.',
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
                str(i): {'status': 'error', 'gate': 'risk', 'server_name': 'web-1'}
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
                    'command': '/usr/bin/sudo secret',
                    'username': 'operator',
                    'server': {'id': 'server-id', 'name': 'web-1'},
                    'work_session': 's1',
                },
            },
            {},
            tool_name='answer_command_purpose',
        )
    await drain_signals()
    desktop_notifications.assert_called_once_with(
        'Alpacon: command denied',
        'sudo on web-1 as operator was refused by the risk gate and did not run. Session s1.',
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

    def blocking_notifier(title, body):
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
