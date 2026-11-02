"""Best-effort desktop signals for the person running a stdio server."""

import asyncio
import base64
import ctypes
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from time import monotonic
from typing import Literal, get_args
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

import httpx

from utils.common import WorkSessionGateCode, resolve_work_session_id
from utils.http_client import http_client
from utils.logger import get_logger
from utils.notification_context import ConsoleLinks

logger = get_logger('local_signal')

type SignalKind = Literal['denied', 'approval_pending', 'paused']

_stdio: ContextVar[bool] = ContextVar('local_signal_stdio', default=False)
_tasks: set[asyncio.Task[None]] = set()

# Only tools that submit host commands or move files can report a denial.
DENIAL_TOOLS = frozenset(
    {
        'execute_command',
        'execute_command_multi_server',
        'execute_file',
        'state_command_purpose',
        'webftp_upload_file',
        'webftp_upload_content',
        'webftp_download_file',
        'webftp_bulk_upload',
        'webftp_bulk_download',
        'restart_agent',
        'upgrade_agent',
        'install_pam',
        'update_information',
        'install_system_package',
        'remove_system_package',
        'install_python_package',
        'remove_python_package',
    }
)
# alpacon-cli mirrors this allowlist; keep the two clients in sync.
_REFUSAL_GATES = frozenset(
    {
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
)
_WORK_SESSION_GATE_CODES = frozenset(get_args(WorkSessionGateCode.__value__))
_APPROVAL_LAPSES = frozenset({'approval_expired', 'approval_cancelled'})
_CONTROL_CHARACTERS = re.compile(
    r'[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]'
)
_ARGV0 = re.compile(r'[A-Za-z0-9._+-]{1,64}')
_MAX_BODY = 256


def is_stdio() -> bool:
    return _stdio.get()


def clean(value: str) -> str:
    return _CONTROL_CHARACTERS.sub('', value)


def _normalized_host(host: str) -> str:
    host = host.lower()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        host = httpx.URL(host=host).raw_host.decode('ascii').removesuffix('.')
        if not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in host.split('.')
        ):
            raise ValueError('Invalid URL host')
        return host


def _origin(value: str) -> tuple[str, str, int]:
    if len(value) > 2048 or any(
        unicodedata.category(character) in ('Cc', 'Cf') for character in value
    ):
        raise ValueError('Invalid URL text')
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ('http', 'https')
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(':')
    ):
        raise ValueError('Invalid URL origin')
    default_port = 443 if parsed.scheme == 'https' else 80
    port = parsed.port if parsed.port is not None else default_port
    return parsed.scheme, _normalized_host(parsed.hostname), port


def _console_url(value: str, workspace_url: str, base_domain: str = '') -> str:
    try:
        scheme, host, port = _origin(value)
        workspace_scheme, workspace_host, workspace_port = _origin(workspace_url)
        if scheme != workspace_scheme:
            return ''
        if host == workspace_host and port == workspace_port:
            return value
        if base_domain:
            domain = _normalized_host(base_domain)
            if (host == domain or host.endswith('.' + domain)) and port == (
                443 if scheme == 'https' else 80
            ):
                return value
        return ''
    except (ValueError, httpx.InvalidURL):
        return ''


@contextmanager
def stdio_transport() -> Iterator[None]:
    token = _stdio.set(True)
    try:
        yield
    finally:
        _stdio.reset(token)


def command_argv0(command: str) -> str:
    remaining = command.lstrip()
    while re.match(r'[A-Za-z_][A-Za-z0-9_]*=', remaining):
        quote = ''
        escaped = False
        for index, character in enumerate(remaining):
            if escaped:
                escaped = False
            elif character == '\\' and quote != "'":
                escaped = True
            elif quote:
                if character == quote:
                    quote = ''
            elif character in '"\'':
                quote = character
            elif character in ';|&<>()$`':
                return ''
            elif character.isspace():
                remaining = remaining[index:].lstrip()
                break
        else:
            return ''
    word = re.split(r"[\s;|&<>()$`'\"\\]", remaining, maxsplit=1)[0]
    basename = word.rsplit('/', 1)[-1]
    return basename if _ARGV0.fullmatch(basename) else ''


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    argv0: str = ''
    server: str = ''
    account: str = ''
    gate: str = ''
    session: str = ''
    session_id: str = ''
    console_url: str = ''
    workspace_url: str = ''
    base_domain: str = ''

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            'console_url',
            _console_url(self.console_url, self.workspace_url, self.base_domain),
        )
        for field in fields(self):
            object.__setattr__(self, field.name, clean(getattr(self, field.name)))

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
        body = body[:_MAX_BODY]
        if self.console_url and len(body) + len(self.console_url) + 1 <= _MAX_BODY:
            body += f' {self.console_url}'
        return title, body


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[tuple[str, SignalKind], tuple[float, int]] = {}

    def take(self, session_id: str, kind: SignalKind) -> int | None:
        now = monotonic()
        self._windows = {
            key: value
            for key, value in self._windows.items()
            if now - value[0] <= 24 * 60 * 60
        }
        key = (session_id[:128], kind)
        previous = self._windows.get(key)
        if previous is not None:
            started, folded = previous
            if 0 <= now - started < 60:
                self._windows[key] = (started, folded + 1)
                return None
            if started > now:
                folded = 0
        else:
            folded = 0
        self._windows[key] = (now, 0)
        return folded


_limiter = RateLimiter()


def _windows_session_zero() -> bool:
    # WinDLL is available only on Windows.
    load_library = getattr(ctypes, 'WinDLL', None)
    if load_library is None:
        return False
    try:
        kernel32 = load_library('kernel32', use_last_error=True)
        session = ctypes.c_ulong()
        if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            return False
        return session.value == 0
    except Exception:
        return False


def is_headless() -> bool:
    if os.environ.get('CI'):
        return True
    if 'SSH_CONNECTION' in os.environ or 'SSH_TTY' in os.environ:
        return True
    # A plain str so mypy checks every branch on every platform it runs on.
    platform: str = sys.platform
    if platform.startswith('linux'):
        return not (
            (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
            and os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        )
    return platform == 'win32' and _windows_session_zero()


def _powershell_toast(title: str, body: str, console_url: str) -> list[str]:
    payload = base64.b64encode(
        json.dumps({'title': title, 'body': body, 'console_url': console_url}).encode(
            'utf-8'
        )
    ).decode('ascii')
    # Only base64 enters script text; decoded values become XML text nodes.
    script = f"""$ErrorActionPreference = 'Stop'
$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text></text><text></text></binding></visual></toast>')
if ($data.console_url) {{
    $xml.DocumentElement.SetAttribute('launch', $data.console_url)
    $xml.DocumentElement.SetAttribute('activationType', 'protocol')
}}
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).InnerText = $data.title
$nodes.Item(1).InnerText = $data.body
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)
"""
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return [
        'powershell.exe',
        '-NoProfile',
        '-NonInteractive',
        '-EncodedCommand',
        encoded,
    ]


def notify(
    title: str,
    body: str,
    console_url: str = '',
    *,
    workspace_url: str = '',
    base_domain: str = '',
) -> None:
    try:
        title, body = clean(title), clean(body)
        console_url = _console_url(console_url, workspace_url, base_domain)
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
                escape(title),
                escape(body),
            ]
        elif sys.platform == 'win32':
            command = _powershell_toast(title, body, console_url)
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
    return clean(value).strip() if isinstance(value, str) else ''


def _raw_console_url(fields: Mapping[str, object]) -> str:
    value = fields.get('console_url')
    return value if isinstance(value, str) else ''


def _from_result(
    result: Mapping[str, object],
    arguments: Mapping[str, object],
    tool_name: str,
    console_url: str = '',
) -> Signal | None:
    data = result.get('data')
    details = result.get('details')
    row = data if isinstance(data, dict) else details
    row = row if isinstance(row, dict) else {}
    status = result.get('status')
    code = result.get('code') or result.get('error_code')
    gate = (
        _string(result, 'gate')
        or _string(result, 'rejection_gate')
        or _string(row, 'rejection_gate')
    )
    if not gate and isinstance(code, str) and code in _WORK_SESSION_GATE_CODES:
        gate = 'work_session'
    cause = _string(result, 'rejection_cause') or _string(row, 'rejection_cause')
    missing = result.get('missing')
    missing_classes = missing if isinstance(missing, list) else [missing]
    excluded_missing = any(
        value in ('presence', 'role', 'token_scope', 'auth')
        for value in missing_classes
    )
    if status == 'error' and code == 'session_paused':
        kind: SignalKind = 'paused'
    elif status == 'pending_approval':
        kind = 'approval_pending'
    elif (
        tool_name in DENIAL_TOOLS
        and gate in _REFUSAL_GATES
        and cause not in _APPROVAL_LAPSES
        and _string(result, 'error_code') not in _APPROVAL_LAPSES
        and _string(result, 'code') not in _APPROVAL_LAPSES
        and not excluded_missing
        and not (
            isinstance(code, str) and code.startswith(('auth_', 'mfa_', 'validation'))
        )
        and (
            (status == 'error' and result.get('status_code') == 403)
            or status == 'rejected'
            or row.get('status') == 'rejected'
            # Polling also flattens a rejected row into an error result.
            or (status == 'error' and bool(cause))
        )
    ):
        kind = 'denied'
    else:
        return None

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
    command = arguments.get('command') or result.get('command') or row.get('command')
    console_url = _raw_console_url(result) or _raw_console_url(row) or console_url
    workspace, region = arguments.get('workspace'), arguments.get('region')
    workspace_url = ''
    if console_url and isinstance(workspace, str) and isinstance(region, str):
        workspace_url = http_client.get_base_url(region, workspace)
    return Signal(
        kind=kind,
        argv0=command_argv0(command if isinstance(command, str) else ''),
        server=server,
        account=_string(arguments, 'username') or _string(row, 'username'),
        gate=gate,
        session=session,
        session_id=session_id,
        console_url=console_url,
        workspace_url=workspace_url,
        # MCP has no base_domain configuration; never infer one from the API host.
    )


async def _deliver(title: str, body: str, signal: Signal) -> None:
    try:
        if signal.console_url:
            await asyncio.to_thread(
                notify,
                title,
                body,
                signal.console_url,
                workspace_url=signal.workspace_url,
                base_domain=signal.base_domain,
            )
        else:
            await asyncio.to_thread(notify, title, body, '')
    except Exception:
        logger.debug('Desktop notification skipped: background notifier failed')


def signal_result(
    result: object,
    arguments: Mapping[str, object],
    *,
    tool_name: str,
    console_links: ConsoleLinks | None = None,
) -> None:
    try:
        if not is_stdio() or not isinstance(result, dict):
            return
        link = console_links.get(id(result)) if console_links else None
        signal = _from_result(result, arguments, tool_name, link[1] if link else '')
        if signal is not None:
            folded = _limiter.take(signal.session_id, signal.kind)
            if folded is not None:
                task = asyncio.create_task(_deliver(*signal.text(folded), signal))
                _tasks.add(task)
                task.add_done_callback(_tasks.discard)
        # Batch submissions return normalized, per-server tool results here.
        batch = result.get('deploy_shell_results')
        if isinstance(batch, dict):
            for entry in batch.values():
                signal_result(
                    entry, arguments, tool_name=tool_name, console_links=console_links
                )
    except Exception:
        logger.debug('Desktop notification skipped: result hook failed')
