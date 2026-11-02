"""Best-effort desktop signals for the person running a stdio server."""

import asyncio
import base64
import ctypes
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from utils.common import resolve_work_session_id
from utils.logger import get_logger

logger = get_logger('local_signal')

type SignalKind = Literal['denied', 'approval_pending', 'paused']

_stdio: ContextVar[bool] = ContextVar('local_signal_stdio', default=False)
_tasks: set[asyncio.Task[None]] = set()


@contextmanager
def stdio_transport() -> Iterator[None]:
    token = _stdio.set(True)
    try:
        yield
    finally:
        _stdio.reset(token)


def command_argv0(command: str) -> str:
    # Read only the first shell word; a malformed argument later is irrelevant.
    lexer = shlex.shlex(command, posix=sys.platform != 'win32')
    lexer.whitespace_split = True
    lexer.commenters = ''
    try:
        word = next(lexer, '').strip('"\'')
    except ValueError:
        return ''
    return word.replace('\\', '/').rsplit('/', 1)[-1]


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    argv0: str = ''
    server: str = ''
    account: str = ''
    gate: str = ''
    session: str = ''
    session_id: str = ''

    def text(self, folded: int = 0) -> tuple[str, str]:
        if self.kind == 'paused':
            title = 'Alpacon: session paused'
            subject = f'Work Session {self.session}' if self.session else 'Work Session'
            body = (
                f'{subject} is paused after a critical denial. '
                'The owner or an approver can resume or end it.'
            )
        elif self.kind == 'approval_pending' and not self.argv0:
            title = 'Alpacon: approval pending'
            subject = f'Work Session {self.session}' if self.session else 'Work Session'
            body = (
                f'{subject} is waiting for approval. '
                'Open the approval or wait for an approver.'
            )
        else:
            subject = self.argv0 or 'Command'
            if self.server:
                subject += f' on {self.server}'
            if self.account:
                subject += f' as {self.account}'
            if self.kind == 'denied':
                title = 'Alpacon: command denied'
                gate = f' by the {self.gate} gate' if self.gate else ''
                body = f'{subject} was refused{gate} and did not run.'
            else:
                title = 'Alpacon: approval pending'
                body = f'{subject} is waiting for approval.'
            if self.session:
                body += f' Session {self.session}.'
            if self.kind == 'approval_pending':
                body += ' Open the approval or wait for an approver.'
        if folded:
            body += f' +{folded} more.'
        return title, body


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[tuple[str, SignalKind], tuple[float, int]] = {}

    def take(self, session_id: str, kind: SignalKind) -> int | None:
        key = (session_id, kind)
        now = monotonic()
        previous = self._windows.get(key)
        if previous is not None:
            started, folded = previous
            if now - started < 60:
                self._windows[key] = (started, folded + 1)
                return None
        else:
            folded = 0
        self._windows[key] = (now, 0)
        return folded


_limiter = RateLimiter()


def _windows_session_zero() -> bool:
    # WinDLL is available only on Windows.
    load_library = getattr(ctypes, 'WinDLL', None)
    if load_library is None:
        return True
    kernel32 = load_library('kernel32', use_last_error=True)
    session = ctypes.c_ulong()
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        return True
    return session.value == 0


def is_headless() -> bool:
    if os.environ.get('CI'):
        return True
    if 'SSH_CONNECTION' in os.environ or 'SSH_TTY' in os.environ:
        return True
    if sys.platform.startswith('linux'):
        return not (
            (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
            and os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        )
    return sys.platform == 'win32' and _windows_session_zero()


def _powershell_toast(title: str, body: str) -> list[str]:
    payload = base64.b64encode(
        json.dumps({'title': title, 'body': body}).encode('utf-8')
    ).decode('ascii')
    # Only base64 enters script text; decoded values become XML text nodes.
    script = f"""$ErrorActionPreference = 'Stop'
$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text></text><text></text></binding></visual></toast>')
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).InnerText = $data.title
$nodes.Item(1).InnerText = $data.body
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Alpacon').Show($toast)
"""
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return [
        'powershell.exe',
        '-NoProfile',
        '-NonInteractive',
        '-EncodedCommand',
        encoded,
    ]


def notify(title: str, body: str) -> None:
    try:
        if is_headless():
            return
        if sys.platform == 'darwin':
            command = [
                '/usr/bin/osascript',
                '-e',
                (
                    'on run argv\n'
                    'display notification (item 2 of argv) with title (item 1 of argv)\n'
                    'end run'
                ),
                '--',
                title,
                body,
            ]
        elif sys.platform.startswith('linux'):
            executable = shutil.which('notify-send')
            if executable is None:
                return
            command = [
                executable,
                '--app-name=Alpacon',
                '-u',
                'normal',
                '--',
                title,
                body,
            ]
        elif sys.platform == 'win32':
            command = _powershell_toast(title, body)
        else:
            return
        # Platform tools only; values are data, never shell text.
        subprocess.run(  # noqa: S603
            command,
            timeout=2,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        logger.debug('Desktop notification skipped: platform notifier failed')


def _string(fields: Mapping[str, object], key: str) -> str:
    value = fields.get(key)
    return value.strip() if isinstance(value, str) else ''


def _from_result(
    result: Mapping[str, object], arguments: Mapping[str, object], tool_name: str
) -> Signal | None:
    status = result.get('status')
    code = result.get('code') or result.get('error_code')
    gate = _string(result, 'gate') or _string(result, 'rejection_gate')
    if status == 'error' and code == 'session_paused':
        kind: SignalKind = 'paused'
    elif status == 'pending_approval':
        kind = 'approval_pending'
    elif status == 'error' and gate:
        kind = 'denied'
    else:
        return None

    data = result.get('data')
    details = result.get('details')
    row = data if isinstance(data, dict) else details
    row = row if isinstance(row, dict) else {}
    session_id = _string(result, 'work_session_id') or _string(result, 'session_id')
    session_id = session_id or _string(arguments, 'work_session_id')
    session_id = session_id or _string(row, 'work_session')
    if tool_name.startswith('work_session_'):
        session_id = session_id or _string(arguments, 'session_id')
    session_id = session_id or resolve_work_session_id(None) or ''
    session = session_id
    if tool_name.startswith('work_session_') and isinstance(data, dict):
        session_id = _string(data, 'id') or session_id
        session = _string(data, 'title') or session_id
    server = _string(result, 'server_name') or _string(row, 'server_name')
    server_object = row.get('server')
    if not server and isinstance(server_object, dict):
        server = _string(server_object, 'name')
    return Signal(
        kind=kind,
        argv0=command_argv0(
            _string(arguments, 'command')
            or _string(result, 'command')
            or _string(row, 'command')
        ),
        server=server,
        account=_string(arguments, 'username') or _string(row, 'username'),
        gate=gate,
        session=session,
        session_id=session_id,
    )


async def _deliver(title: str, body: str) -> None:
    try:
        await asyncio.to_thread(notify, title, body)
    except Exception:
        logger.debug('Desktop notification skipped: background notifier failed')


def signal_result(
    result: object, arguments: Mapping[str, object], *, tool_name: str
) -> None:
    try:
        if not _stdio.get() or not isinstance(result, dict):
            return
        signal = _from_result(result, arguments, tool_name)
        if signal is not None:
            folded = _limiter.take(signal.session_id, signal.kind)
            if folded is not None:
                task = asyncio.create_task(_deliver(*signal.text(folded)))
                _tasks.add(task)
                task.add_done_callback(_tasks.discard)
        # Batch submissions return normalized, per-server tool results here.
        batch = result.get('deploy_shell_results')
        if isinstance(batch, dict):
            for entry in batch.values():
                signal_result(entry, arguments, tool_name=tool_name)
    except Exception:
        logger.debug('Desktop notification skipped: result hook failed')
