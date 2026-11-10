"""Best-effort desktop signals for the person running a stdio server."""

import asyncio
import base64
import ctypes
import ipaddress
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import escape

import httpx

from utils.common import is_work_session_gate_code, resolve_work_session_id
from utils.http_client import http_client
from utils.logger import get_logger
from utils.notification_context import ConsoleLinks

logger = get_logger('local_signal')

type SignalKind = Literal['denied', 'approval_pending', 'paused']
type SignalTarget = Literal['command', 'file_transfer', 'work_session', 'sudo_policy']
type PendingKey = tuple[SignalKind, SignalTarget, str, str, str]

_stdio: ContextVar[bool] = ContextVar('local_signal_stdio', default=False)
_tasks: set[asyncio.Task[None]] = set()

# Only tools that submit or read host commands, or move files, report denials.
DENIAL_TOOLS = frozenset(
    {
        'execute_command',
        'execute_command_multi_server',
        'execute_file',
        'check_command_status',
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
SUDO_PENDING_TOOLS = frozenset(
    {
        'execute_command',
        'execute_command_multi_server',
        'execute_file',
        'state_command_purpose',
        'check_command_status',
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
_APPROVAL_LAPSES = frozenset({'approval_expired', 'approval_cancelled'})
_ARGV0 = re.compile(r'[A-Za-z0-9._+-]{1,64}')
_ACCOUNT = re.compile(r'[a-z_][a-z0-9_.-]{0,31}\$?')
_ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*=')
_SESSION_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
_WORD_SPACE = ' \t\n\r'
_MAX_BODY = 256
_PENDING_TTL = 10 * 60
# Cloud console links use the built-in domain, never an inferred API parent.
_CLOUD_BASE_DOMAIN = 'alpacon.io'


def is_stdio() -> bool:
    return _stdio.get()


def clean(value: str) -> str:
    return ''.join(
        character
        for character in value
        if unicodedata.category(character) not in ('Cc', 'Cf', 'Zl', 'Zp')
    )


def _normalized_host(host: str) -> str:
    host = host.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        host = httpx.URL(host=host).raw_host.decode('ascii').removesuffix('.')
        if not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in host.split('.')
        ):
            raise ValueError('Invalid URL host')
        return host
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        raise ValueError('Mapped IPv6 host')
    return str(address)


def _origin(value: str) -> tuple[str, str, int]:
    if (
        len(value) > 2048
        or not value.isascii()
        or '#' in value
        or re.search(r'%(?![0-9A-Fa-f]{2})', value)
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
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


def _console_url(value: str, workspace_url: str) -> str:
    try:
        scheme, host, port = _origin(value)
        serialized = urlunsplit(urlsplit(value))
        workspace_scheme, workspace_host, workspace_port = _origin(workspace_url)
        if scheme != workspace_scheme:
            return ''
        if host == workspace_host and port == workspace_port:
            return serialized
        if (
            workspace_host.endswith('.' + _CLOUD_BASE_DOMAIN)
            and (host == _CLOUD_BASE_DOMAIN or host.endswith('.' + _CLOUD_BASE_DOMAIN))
            and port == (443 if scheme == 'https' else 80)
        ):
            return serialized
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
    if (
        len(command) > 4096
        or len(command.encode('utf-8', errors='surrogatepass')) > 4096
    ):
        return ''
    index = 0
    while index < len(command):
        if command[index] in _WORD_SPACE:
            index += 1
            continue
        start = index
        assignment = bool(_ASSIGNMENT.match(command, index))
        quote = ''
        escaped = False
        while index < len(command):
            character = command[index]
            if not assignment and character in '\'"\\':
                return ''
            if (not character.isascii()) or (
                (ord(character) < 32 or ord(character) == 127)
                and character not in _WORD_SPACE
            ):
                return ''
            if character == '`' or command.startswith(('$(', '${'), index):
                return ''
            if quote and character in '"\'' and (escaped or character != quote):
                return ''
            if escaped:
                escaped = False
            elif character == '\\' and quote != "'":
                escaped = True
            elif quote:
                if character == quote:
                    quote = ''
            elif character in '"\'':
                quote = character
            elif character in ';|&<>()' or (character == '$' and assignment):
                if assignment:
                    return ''
                break
            elif character in _WORD_SPACE:
                break
            index += 1
        else:
            if assignment:
                return ''
        if not assignment:
            word = re.split(
                r"[ \t\n\r;|&<>()$`'\"\\]", command[start:index], maxsplit=1
            )[0]
            basename = word.rsplit('/', 1)[-1]
            return basename if _ARGV0.fullmatch(basename) else ''
    return ''


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    target: SignalTarget = 'command'
    pending_id: str = ''
    argv0: str = ''
    server: str = ''
    account: str = ''
    gate: str = ''
    session: str = ''
    session_id: str = ''
    console_url: str = ''
    workspace_url: str = ''
    # `assignee` when the session's assignee confirms the held command (ADR 0114).
    lane: str = ''

    def __post_init__(self) -> None:
        if not _ACCOUNT.fullmatch(self.account):
            object.__setattr__(self, 'account', '')
        object.__setattr__(
            self,
            'console_url',
            _console_url(self.console_url, self.workspace_url),
        )
        for field in fields(self):
            object.__setattr__(self, field.name, clean(getattr(self, field.name)))
        if not _SESSION_ID.fullmatch(self.session):
            object.__setattr__(self, 'session', '')
        object.__setattr__(
            self, 'server', '' if '://' in self.server else self.server[:64]
        )

    def text(self, folded: int = 0) -> tuple[str, str]:
        if self.kind == 'paused':
            title = 'Alpacon: session paused'
            subject = f'Work Session {self.session}' if self.session else 'Work Session'
            body = (
                f'{subject} is paused after a critical denial. '
                'Open the web console for the available recovery actions.'
            )
        elif self.kind == 'approval_pending' and self.target in (
            'work_session',
            'sudo_policy',
        ):
            title = 'Alpacon: approval pending'
            if self.target == 'sudo_policy':
                subject = 'Sudo policy request'
            else:
                subject = (
                    f'Work Session {self.session}' if self.session else 'Work Session'
                )
            body = (
                f'{subject} is waiting for approval. '
                'Open the approval or wait for an approver.'
            )
        else:
            subject = (
                'File transfer'
                if self.target == 'file_transfer'
                else self.argv0 or 'Command'
            )
            if self.server:
                subject += f' on {self.server}'
            if self.account:
                subject += f' as {self.account}'
            assignee = self.kind == 'approval_pending' and self.lane == 'assignee'
            if self.kind == 'denied':
                title = (
                    'Alpacon: file transfer denied'
                    if self.target == 'file_transfer'
                    else 'Alpacon: command denied'
                )
                gate = f' by the {self.gate} gate' if self.gate else ''
                action = 'proceed' if self.target == 'file_transfer' else 'run'
                body = f'{subject} was refused{gate} and did not {action}.'
            elif assignee:
                title = 'Alpacon: your confirmation needed'
                body = f'{subject} is waiting for your own confirmation.'
            else:
                title = 'Alpacon: approval pending'
                body = f'{subject} is waiting for approval.'
            if self.session:
                body += f' Session {self.session}.'
            if assignee:
                body += ' Confirm it yourself in the web console.'
            elif self.kind == 'approval_pending':
                body += ' Open the approval or wait for an approver.'
        suffix = f' +{folded} more.' if folded else ''
        body = body[: _MAX_BODY - len(suffix)] + suffix
        if self.console_url and len(body) + len(self.console_url) + 1 <= _MAX_BODY:
            body += f' {self.console_url}'
        return title, body


class RateLimiter:
    def __init__(self) -> None:
        self._windows: OrderedDict[
            tuple[str, SignalKind, str, str], tuple[float, int, set[PendingKey]]
        ] = OrderedDict()
        self._pending: OrderedDict[PendingKey, float] = OrderedDict()

    def take(
        self,
        session_id: str,
        kind: SignalKind,
        workspace: str = '',
        region: str = '',
        *,
        target: SignalTarget = 'command',
        pending_id: str = '',
    ) -> int | None:
        now = monotonic()
        while (
            self._pending and now - next(iter(self._pending.values())) >= _PENDING_TTL
        ):
            self._pending.popitem(last=False)
        pending_key = None
        if kind in ('approval_pending', 'denied') and pending_id:
            pending_key = (kind, target, pending_id, workspace, region)
            if pending_key in self._pending:
                return None
        while (
            self._windows and now - next(iter(self._windows.values()))[0] > 24 * 60 * 60
        ):
            self._windows.popitem(last=False)
        key = (session_id[:128], kind, workspace, region)
        previous = self._windows.get(key)
        if previous is not None:
            started, folded, folded_pending = previous
            if now - started < 60:
                if pending_key is not None:
                    if pending_key in folded_pending:
                        return None
                    folded_pending.add(pending_key)
                self._windows[key] = (started, folded + 1, folded_pending)
                return None
            if pending_key in folded_pending:
                folded -= 1
        else:
            folded = 0
        self._windows[key] = (now, 0, set())
        self._windows.move_to_end(key)
        if pending_key is not None:
            self._pending[pending_key] = now
            if len(self._pending) > 256:
                self._pending.popitem(last=False)
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
    return sys.platform == 'win32' and _windows_session_zero()


def _powershell_toast(title: str, body: str, console_url: str) -> list[str]:
    payload = base64.b64encode(
        json.dumps({'title': title, 'body': body, 'console_url': console_url}).encode(
            'utf-8'
        )
    ).decode('ascii')
    # Only base64 enters script text; decoded values become XML text and attribute values.
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
    system_directory = ctypes.create_unicode_buffer(32768)
    # windll is available only on Windows.
    windll = getattr(ctypes, 'windll')  # noqa: B009
    length = windll.kernel32.GetSystemDirectoryW(
        system_directory, len(system_directory)
    )
    if not 0 < length < len(system_directory):
        raise OSError('Could not resolve the Windows system directory')
    return [
        ntpath.join(
            system_directory.value,
            r'WindowsPowerShell\v1.0\powershell.exe',
        ),
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
) -> None:
    try:
        title, body = clean(title), clean(body)
        console_url = _console_url(console_url, workspace_url)
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
            executable = shutil.which('notify-send', path='/usr/bin:/bin')
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


def _raw_string(fields: Mapping[str, object], key: str) -> str:
    value = fields.get(key)
    return value if isinstance(value, str) else ''


def _from_result(
    result: Mapping[str, object],
    arguments: Mapping[str, object],
    tool_name: str,
    console_url: str = '',
) -> Signal | None:
    if tool_name.startswith('list_') or tool_name == 'explain_approval_decision':
        return None
    data = result.get('data')
    details = result.get('details')
    row = data if isinstance(data, dict) else details
    row = row if isinstance(row, dict) else {}
    status = result.get('status')
    sudo_denial = result.get('sudo_denial') or row.get('sudo_denial')
    code = result.get('code') or result.get('error_code')
    gate = (
        _string(result, 'gate')
        or _string(result, 'rejection_gate')
        or _string(row, 'rejection_gate')
    )
    if not gate and isinstance(code, str) and is_work_session_gate_code(code):
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
    elif status == 'pending_approval' or (
        tool_name in SUDO_PENDING_TOOLS
        and isinstance(sudo_denial, dict)
        and sudo_denial.get('status') == 'pending_approval'
    ):
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
            # Polling wraps a denied row in an error result without a 403 or cause.
            or row.get('status') in ('rejected', 'denied')
            or (status == 'error' and bool(cause))
        )
    ):
        kind = 'denied'
    else:
        return None

    session_id = _raw_string(result, 'work_session_id') or _raw_string(
        result, 'session_id'
    )
    work_session_wait = result.get('category') == 'WORK_SESSION_PENDING'
    if work_session_wait:
        session_id = session_id or _raw_string(row, 'work_session_id')
    session_id = session_id or _raw_string(arguments, 'work_session_id')
    session_id = session_id or _raw_string(row, 'work_session')
    if tool_name.startswith('work_session_'):
        session_id = session_id or _raw_string(arguments, 'session_id')
    session_id = session_id or resolve_work_session_id(None) or ''
    if tool_name.startswith('work_session_') and isinstance(data, dict):
        session_id = _raw_string(data, 'id') or session_id
    target: SignalTarget = 'command'
    if result.get('category') == 'SUDO_POLICY_REQUEST_PENDING':
        target = 'sudo_policy'
        pending_id = _raw_string(row, 'id') or _raw_string(result, 'request_id')
    elif work_session_wait or tool_name.startswith('work_session_'):
        target = 'work_session'
        pending_id = session_id
    else:
        if tool_name.startswith('webftp_'):
            target = 'file_transfer'
        pending_id = (
            _raw_string(result, 'command_id')
            or _raw_string(arguments, 'command_id')
            or _raw_string(row, 'id')
        )
    server = _string(result, 'server_name') or _string(row, 'server_name')
    server_object = row.get('server')
    if not server and isinstance(server_object, dict):
        server = _string(server_object, 'name')
    command = arguments.get('command') or result.get('command') or row.get('command')
    console_url = (
        _raw_string(result, 'console_url')
        or _raw_string(row, 'console_url')
        or console_url
    )
    workspace, region = arguments.get('workspace'), arguments.get('region')
    workspace_url = ''
    if console_url and isinstance(workspace, str) and isinstance(region, str):
        workspace_url = http_client.get_base_url(region, workspace)
    return Signal(
        kind=kind,
        target=target,
        pending_id=pending_id,
        argv0=command_argv0(command if isinstance(command, str) else ''),
        server=server,
        account=(
            _raw_string(result, 'username')
            or _raw_string(row, 'username')
            or _raw_string(arguments, 'username')
        ),
        gate=gate,
        session=session_id,
        session_id=session_id,
        console_url=console_url,
        workspace_url=workspace_url,
        lane=_string(result, 'approval_lane'),
    )


async def _deliver(title: str, body: str, signal: Signal) -> None:
    try:
        await asyncio.to_thread(
            notify,
            title,
            body,
            signal.console_url,
            workspace_url=signal.workspace_url,
        )
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
            folded = _limiter.take(
                signal.session_id,
                signal.kind,
                _string(arguments, 'workspace'),
                _string(arguments, 'region'),
                target=signal.target,
                pending_id=signal.pending_id,
            )
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
