import os
import re
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.eval_mocks import EXPOSURE_RESULT
from tests.skill_scripts import doc_blocks, install_fakes, run_with_fakes

CHECKS = 'exposure-check/references/checks.md'
FAKES = {
    'ss': 'printf \'%s\\n\' "$SS_OUT"; exit "${SS_EXIT:-0}"',
    'curl': """for a; do last=$a; done
printf '%s\\n' "$*" >> "$CURL_LOG"
case " $* " in (*' -D '*) printf '%s\\n' "${HEADERS-}" ;; esac
printf '%s\\n' "$CODES" | awk -v u="$last" '$1 == u {printf "%s", $2; f = 1} END {if (!f) printf "000"}'""",
    'systemctl': '[ "$*" != \'show -p ExecStart docker.service\' ] || printf \'%s\\n\' "$UNIT"; exit "${UNIT_EXIT:-0}"',
    'ps': 'printf \'%s\\n\' "$PS_OUT"; exit "${PS_EXIT:-0}"',
    'stat': '[ -z "$STAT_EXIT" ] || exit "$STAT_EXIT"; printf \'%s\\n\' "$3" | sed "s/%a/$SOCK_MODE/; s/%U/root/; s/%G/docker/"',
}
SS_HEADER = 'State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process'
SSHD = 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=812,fd=3))'
DOCKERD = 'LISTEN 0 4096 0.0.0.0:2375 0.0.0.0:* users:(("dockerd",pid=901,fd=7))'
MINIO_BODY = '{"accessKey":"minioadmin","secretKey":"minioadmin"}'
MINIO_TOKEN = 'HTTP/1.1 204 No Content\r\nSet-Cookie: token=abc; Path=/; HttpOnly'


def _ss(*rows: str) -> str:
    return '\n'.join([SS_HEADER, *rows])


def _fill(script: str, **values: str) -> str:
    for name, value in values.items():
        script = re.sub(rf"^{name}='[^']*'$", f"{name}='{value}'", script, flags=re.M)
        script = re.sub(rf'^{name}=\S*$', f"{name}='{value}'", script, flags=re.M)
    return script


def _run(
    tmp_path: Path,
    shell: str,
    block: int,
    values: dict[str, str],
    *,
    sock: Path | None = None,
    daemon_json: Path | None = None,
    **env: str,
) -> tuple[str, str]:
    """Run one documented block, filled with `values`; returns its stdout and the curl calls."""
    script = _fill(doc_blocks(CHECKS, 'sh')[block], **values)
    script = script.replace(
        '/etc/docker/daemon.json', str(daemon_json or tmp_path / 'daemon.json')
    )
    script = script.replace('/var/run/docker.sock', str(tmp_path / 'var-docker.sock'))
    script = script.replace('/run/docker.sock', str(sock or tmp_path / 'docker.sock'))
    install_fakes(tmp_path / 'bin', FAKES)
    log = tmp_path / 'curl.log'
    result = run_with_fakes(
        [shell, '-c', script],
        tmp_path / 'bin',
        **{
            'SS_OUT': _ss(),
            'CODES': '',
            'UNIT': '',
            'PS_OUT': '',
            'SOCK_MODE': '660',
            'CURL_LOG': str(log),
        }
        | env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout, log.read_text() if log.exists() else ''


def _check(
    tmp_path: Path,
    shell: str,
    ports: str = '',
    endpoints: str = '',
    sock: Path | None = None,
    daemon_json: Path | None = None,
    **env: str,
) -> tuple[dict[str, str], list[str], str]:
    """Run the documented check; returns its key=value lines, its other lines, and the curl calls."""
    assert 'docker_sock' in doc_blocks(CHECKS, 'sh')[0], (
        'the first sh block is no longer the check'
    )
    out, calls = _run(
        tmp_path,
        shell,
        0,
        {'ports': ports, 'endpoints': endpoints},
        sock=sock,
        daemon_json=daemon_json,
        **env,
    )
    lines = out.splitlines()
    keys = dict(line.split('=', 1) for line in lines if ' ' not in line and '=' in line)
    return keys, [line for line in lines if ' ' in line], calls


def _login(
    tmp_path: Path, shell: str, values: dict[str, str] | None = None, **env: str
) -> tuple[str, str]:
    assert 'accepted=' in doc_blocks(CHECKS, 'sh')[1], (
        'the second sh block is no longer the login check'
    )
    env = {'EXPOSURE_BODY': MINIO_BODY, 'HEADERS': MINIO_TOKEN} | env
    return _run(tmp_path, shell, 1, values or {}, sock=None, daemon_json=None, **env)


@pytest.fixture
def docker_sock() -> Iterator[Path]:
    """A real Unix socket on a path short enough for macOS's 104-byte limit."""
    with (
        tempfile.TemporaryDirectory(dir='/tmp') as short,
        socket.socket(socket.AF_UNIX) as sock,
    ):
        path = Path(short) / 'd.sock'
        sock.bind(str(path))
        yield path


@pytest.mark.parametrize('shell', ['bash', 'sh'])
class TestExposureCheck:
    def test_reports_an_unauthenticated_docker_api_on_every_interface(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, calls = _check(
            tmp_path,
            shell,
            ports='2375',
            endpoints='GET http 2375 /version',
            SS_OUT=_ss(SSHD, DOCKERD),
            CODES='http://127.0.0.1:2375/version 200',
        )

        assert keys['verdict'] == 'exposed'
        assert keys['findings'] == 'port:2375@0.0.0.0,endpoint:2375/version'
        assert (
            'listen addr=0.0.0.0 port=2375 scope=all watched=yes process=dockerd'
            in rows
        )
        assert 'listen addr=0.0.0.0 port=22 scope=all watched=no process=sshd' in rows
        assert (
            calls
            == '-q --noproxy * -sk -o /dev/null -m 5 -w %{http_code} http://127.0.0.1:2375/version\n'
        )

    def test_counts_an_ipv6_wildcard_bind_and_probes_ipv6_loopback(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            ports='2375',
            endpoints='GET http 2375 /version',
            SS_OUT=_ss('LISTEN 0 4096 [::]:2375 [::]:*'),
            CODES='http://[::1]:2375/version 200',
        )

        assert keys['verdict'] == 'exposed'
        assert 'listen addr=:: port=2375 scope=all watched=yes process=' in rows

    def test_probes_a_service_bound_to_one_interface_on_that_address(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, calls = _check(
            tmp_path,
            shell,
            endpoints='GET http 9001 /api/v1/session',
            SS_OUT=_ss('LISTEN 0 4096 10.0.0.5:9001 0.0.0.0:*'),
            CODES='http://10.0.0.5:9001/api/v1/session 401',
        )

        assert keys['verdict'] == 'not_exposed'
        assert 'http://10.0.0.5:9001/api/v1/session' in calls
        assert (
            'listen addr=10.0.0.5 port=9001 scope=interface watched=no process=' in rows
        )

    def test_leaves_loopback_listeners_out_and_sends_them_no_request(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, calls = _check(
            tmp_path,
            shell,
            ports='2375',
            endpoints='GET http 2375 /version',
            SS_OUT=_ss(
                'LISTEN 0 4096 127.0.0.1:2375 0.0.0.0:*',
                'LISTEN 0 4096 [::1]:2375 [::]:*',
                'LISTEN 0 4096 [::ffff:127.0.0.1]:2375 *:*',
                'LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*',
            ),
        )

        assert keys['verdict'] == 'not_exposed'
        assert not [row for row in rows if row.startswith('listen ')]
        assert (
            'endpoint method=GET port=2375 path=/version url=- code=none result=loopback_only'
            in rows
        )
        assert calls == ''

    def test_sends_no_request_to_a_port_with_no_listener(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, calls = _check(tmp_path, shell, endpoints='GET http 2375 /version')

        assert keys['verdict'] == 'not_exposed'
        assert (
            'endpoint method=GET port=2375 path=/version url=- code=none result=not_listening'
            in rows
        )
        assert calls == ''

    def test_lists_unwatched_listeners_without_counting_them(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(tmp_path, shell, SS_OUT=_ss(SSHD))

        assert keys['verdict'] == 'not_exposed'
        assert keys['findings'] == ''
        assert 'listen addr=0.0.0.0 port=22 scope=all watched=no process=sshd' in rows

    def test_reports_a_docker_tcp_host_in_daemon_json_that_is_not_listening_yet(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'daemon.json').write_text(
            '{\n  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2375"]\n}\n'
        )

        keys, rows, _ = _check(tmp_path, shell)

        assert keys['verdict'] == 'exposed'
        assert keys['findings'] == 'docker_host:daemon.json'
        assert (
            'docker_host source=daemon.json host=tcp://0.0.0.0:2375 scope=all' in rows
        )

    def test_shows_a_loopback_docker_tcp_host_without_counting_it(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            UNIT='ExecStart={ path=/usr/bin/dockerd ; argv[]=/usr/bin/dockerd -H fd:// -H tcp://127.0.0.1:2375 ; ignore_errors=no }',
        )

        assert keys['verdict'] == 'not_exposed'
        assert (
            'docker_host source=unit host=tcp://127.0.0.1:2375 scope=loopback' in rows
        )

    def test_reads_a_daemon_json_host_listed_after_an_ipv6_one(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'daemon.json').write_text(
            '{"hosts": ["tcp://[::1]:2375", "tcp://0.0.0.0:4243"],'
            ' "log-opts": {"syslog-address": "tcp://10.0.0.9:514"}}'
        )

        keys, rows, _ = _check(tmp_path, shell)

        assert keys['findings'] == 'docker_host:daemon.json'
        assert (
            'docker_host source=daemon.json host=tcp://0.0.0.0:4243 scope=all' in rows
        )
        assert not [row for row in rows if '10.0.0.9' in row]

    def test_reads_an_escaped_daemon_json_host(self, tmp_path: Path, shell: str):
        (tmp_path / 'daemon.json').write_text('{"hosts":["tcp:\\/\\/0.0.0.0:2375"]}')

        keys, rows, _ = _check(tmp_path, shell)

        assert keys['findings'] == 'docker_host:daemon.json'
        assert (
            'docker_host source=daemon.json host=tcp://0.0.0.0:2375 scope=all' in rows
        )

    def test_a_syslog_address_on_the_dockerd_command_line_is_not_a_host(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            PS_OUT='/usr/bin/dockerd -H fd:// --log-opt syslog-address=tcp://10.0.0.9:514',
            UNIT='ExecStart={ path=/usr/bin/dockerd ; argv[]=/usr/bin/dockerd -H fd:// --log-opt syslog-address=tcp://10.0.0.9:514 ; ignore_errors=no }',
        )

        assert keys['verdict'] == 'not_exposed'
        assert not [row for row in rows if row.startswith('docker_host ')]

    def test_reads_every_host_flag_form_on_the_dockerd_command_line(
        self, tmp_path: Path, shell: str
    ):
        _, rows, _ = _check(
            tmp_path,
            shell,
            PS_OUT='/usr/bin/dockerd -H tcp://10.0.0.1:2375 -Htcp://10.0.0.2:2375 --host=tcp://10.0.0.3:2375 --host tcp://10.0.0.4:2375',
        )

        assert [row for row in rows if row.startswith('docker_host ')] == [
            f'docker_host source=process host=tcp://10.0.0.{n}:2375 scope=interface'
            for n in range(1, 5)
        ]

    def test_reads_a_docker_host_written_without_a_scheme(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'daemon.json').write_text(
            '{"hosts": ["unix:///var/run/docker.sock", "0.0.0.0:4243"]}'
        )

        keys, rows, _ = _check(
            tmp_path,
            shell,
            PS_OUT='/usr/bin/dockerd -H fd:// -H 10.0.0.1:2375 --tlsverify',
        )

        assert keys['findings'] == 'docker_host:daemon.json,docker_host:process'
        assert [row for row in rows if row.startswith('docker_host ')] == [
            'docker_host source=daemon.json host=tcp://0.0.0.0:4243 scope=all',
            'docker_host source=process host=tcp://10.0.0.1:2375 scope=interface',
        ]

    def test_a_daemon_json_with_unicode_escapes_is_unknown(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'daemon.json').write_text('{"\\u0068osts": ["tcp://0.0.0.0:2375"]}')

        keys, _, _ = _check(tmp_path, shell)

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_host:daemon.json'

    def test_reads_tcp_hosts_from_the_running_dockerd(self, tmp_path: Path, shell: str):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            PS_OUT='/usr/sbin/sshd -D\n/usr/bin/dockerd --host=tcp://[::]:2376 --tlsverify',
        )

        assert keys['findings'] == 'docker_host:process'
        assert 'docker_host source=process host=tcp://[::]:2376 scope=all' in rows

    @pytest.mark.skipif(os.geteuid() == 0, reason='root reads a mode-000 file')
    def test_an_unreadable_daemon_json_leaves_the_server_unknown(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'daemon.json').write_text('{}')
        (tmp_path / 'daemon.json').chmod(0)

        keys, _, _ = _check(tmp_path, shell)

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_host:daemon.json'

    @pytest.mark.skipif(os.geteuid() == 0, reason='root searches a mode-000 directory')
    def test_a_daemon_json_behind_an_unsearchable_directory_is_unknown(
        self, locked_dir: Path, tmp_path: Path, shell: str
    ):
        (locked_dir / 'daemon.json').write_text('{}')
        locked_dir.chmod(0)

        keys, rows, _ = _check(tmp_path, shell, daemon_json=locked_dir / 'daemon.json')

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_host:daemon.json'
        assert 'docker_host source=daemon.json host=unreadable scope=unknown' in rows

    def test_a_missing_docker_directory_is_not_unknown(
        self, tmp_path: Path, shell: str
    ):
        keys, _, _ = _check(
            tmp_path, shell, daemon_json=tmp_path / 'none' / 'daemon.json'
        )

        assert keys['verdict'] == 'not_exposed'
        assert keys['unknowns'] == ''

    def test_reports_a_world_writable_docker_socket(
        self, tmp_path: Path, shell: str, docker_sock: Path
    ):
        keys, rows, _ = _check(tmp_path, shell, sock=docker_sock, SOCK_MODE='666')

        assert keys['findings'] == 'docker_sock:world_writable'
        assert (
            f'docker_sock path={docker_sock} mode=666 owner=root group=docker' in rows
        )

    def test_a_group_only_docker_socket_is_not_a_finding(
        self, tmp_path: Path, shell: str, docker_sock: Path
    ):
        keys, rows, _ = _check(tmp_path, shell, sock=docker_sock, SOCK_MODE='660')

        assert keys['verdict'] == 'not_exposed'
        assert (
            f'docker_sock path={docker_sock} mode=660 owner=root group=docker' in rows
        )

    def test_reports_a_world_writable_socket_the_daemon_is_configured_to_use(
        self, tmp_path: Path, shell: str, docker_sock: Path
    ):
        (tmp_path / 'daemon.json').write_text(f'{{"hosts": ["unix://{docker_sock}"]}}')

        keys, rows, _ = _check(tmp_path, shell, SOCK_MODE='666')

        assert keys['findings'] == 'docker_sock:world_writable'
        assert (
            f'docker_sock path={docker_sock} mode=666 owner=root group=docker' in rows
        )

    @pytest.mark.skipif(os.geteuid() == 0, reason='root searches a mode-000 directory')
    def test_a_configured_socket_behind_an_unsearchable_directory_is_unknown(
        self, locked_dir: Path, tmp_path: Path, shell: str
    ):
        sock = locked_dir / 'run' / 'd.sock'
        (tmp_path / 'daemon.json').write_text(f'{{"hosts": ["unix://{sock}"]}}')
        locked_dir.chmod(0)

        keys, rows, _ = _check(tmp_path, shell)

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_sock:unreadable'
        assert f'docker_sock path={sock} mode=unknown' in rows

    def test_a_configured_socket_that_does_not_exist_is_skipped(
        self, tmp_path: Path, shell: str
    ):
        sock = tmp_path / 'none' / 'd.sock'
        (tmp_path / 'daemon.json').write_text(f'{{"hosts": ["unix://{sock}"]}}')

        keys, rows, _ = _check(tmp_path, shell)

        assert keys['verdict'] == 'not_exposed'
        assert not any(row.startswith('docker_sock') for row in rows)

    def test_an_unreadable_docker_socket_mode_is_unknown(
        self, tmp_path: Path, shell: str, docker_sock: Path
    ):
        keys, _, _ = _check(tmp_path, shell, sock=docker_sock, STAT_EXIT='1')

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_sock:unreadable'

    def test_a_failing_process_list_is_unknown(self, tmp_path: Path, shell: str):
        keys, _, _ = _check(tmp_path, shell, PS_EXIT='1')

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_host:process'

    def test_a_failing_systemctl_is_unknown(self, tmp_path: Path, shell: str):
        keys, _, _ = _check(tmp_path, shell, UNIT_EXIT='1')

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'docker_host:unit'

    def test_a_redirect_is_unknown_not_safe(self, tmp_path: Path, shell: str):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            endpoints='GET http 8080 /admin',
            SS_OUT=_ss('LISTEN 0 511 0.0.0.0:8080 0.0.0.0:*'),
            CODES='http://127.0.0.1:8080/admin 302',
        )

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'endpoint:8080/admin'

    def test_an_endpoint_that_does_not_answer_is_unknown_not_safe(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            endpoints='GET http 8080 /admin',
            SS_OUT=_ss('LISTEN 0 511 0.0.0.0:8080 0.0.0.0:*'),
        )

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'endpoint:8080/admin'
        assert (
            'endpoint method=GET port=8080 path=/admin url=http://127.0.0.1:8080/admin code=000 result=no_answer'
            in rows
        )

    def test_probes_every_interface_a_port_is_bound_to(
        self, tmp_path: Path, shell: str
    ):
        keys, _, calls = _check(
            tmp_path,
            shell,
            endpoints='GET http 8080 /admin',
            SS_OUT=_ss(
                'LISTEN 0 511 10.0.0.1:8080 0.0.0.0:*',
                'LISTEN 0 511 10.0.0.2:8080 0.0.0.0:*',
            ),
            CODES='http://10.0.0.1:8080/admin 401\nhttp://10.0.0.2:8080/admin 200',
        )

        assert keys['verdict'] == 'exposed'
        assert keys['findings'] == 'endpoint:8080/admin'
        assert len(calls.splitlines()) == 2

    def test_probes_the_ipv4_and_ipv6_wildcards_separately(
        self, tmp_path: Path, shell: str
    ):
        keys, _, calls = _check(
            tmp_path,
            shell,
            endpoints='GET http 8080 /admin',
            SS_OUT=_ss(
                'LISTEN 0 511 0.0.0.0:8080 0.0.0.0:*',
                'LISTEN 0 511 [::]:8080 [::]:*',
            ),
            CODES='http://127.0.0.1:8080/admin 401\nhttp://[::1]:8080/admin 200',
        )

        assert keys['findings'] == 'endpoint:8080/admin'
        assert len(calls.splitlines()) == 2

    def test_probes_both_families_of_a_dual_stack_listener(
        self, tmp_path: Path, shell: str
    ):
        keys, _, calls = _check(
            tmp_path,
            shell,
            endpoints='GET http 8080 /admin',
            SS_OUT=_ss('LISTEN 0 511 *:8080 *:*'),
            CODES='http://127.0.0.1:8080/admin 403\nhttp://[::1]:8080/admin 204',
        )

        assert keys['findings'] == 'endpoint:8080/admin'
        assert len(calls.splitlines()) == 2

    def test_probes_a_link_local_listener_through_its_interface(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(
            tmp_path,
            shell,
            endpoints='GET http 8080 /admin',
            SS_OUT=_ss('LISTEN 0 511 [fe80::1%eth0]:8080 [::]:*'),
            CODES='http://[fe80::1%25eth0]:8080/admin 200',
        )

        assert keys['findings'] == 'endpoint:8080/admin'
        assert (
            'listen addr=fe80::1 port=8080 scope=interface watched=no process=' in rows
        )

    def test_a_websocket_path_answering_plain_200_is_unknown(
        self, tmp_path: Path, shell: str
    ):
        keys, _, _ = _check(
            tmp_path,
            shell,
            endpoints='WS http 2718 /terminal/ws',
            SS_OUT=_ss('LISTEN 0 2048 0.0.0.0:2718 0.0.0.0:*'),
            CODES='http://127.0.0.1:2718/terminal/ws 200',
        )

        assert keys['verdict'] == 'unknown'
        assert keys['unknowns'] == 'endpoint:2718/terminal/ws'

    def test_a_websocket_upgrade_accepted_without_login_is_a_finding(
        self, tmp_path: Path, shell: str
    ):
        keys, _, calls = _check(
            tmp_path,
            shell,
            endpoints='WS http 2718 /terminal/ws',
            SS_OUT=_ss('LISTEN 0 2048 0.0.0.0:2718 0.0.0.0:*'),
            CODES='http://127.0.0.1:2718/terminal/ws 101',
        )

        assert keys['findings'] == 'endpoint:2718/terminal/ws'
        assert 'Upgrade: websocket' in calls

    def test_a_failing_ss_leaves_the_server_unknown(self, tmp_path: Path, shell: str):
        out, _ = _run(tmp_path, shell, 0, {}, SS_EXIT='1')

        assert out == 'verdict=unknown reason=ss-failed\n'

    @pytest.mark.skipif(os.geteuid() == 0, reason='root sees every process name')
    def test_the_eval_mock_answers_what_the_check_prints_for_minio(
        self, tmp_path: Path, shell: str
    ):
        out, _ = _run(
            tmp_path,
            shell,
            0,
            {'ports': '9000 9001', 'endpoints': ''},
            SS_OUT=_ss(
                'LISTEN 0 4096 0.0.0.0:9000 0.0.0.0:*',
                'LISTEN 0 4096 0.0.0.0:9001 0.0.0.0:*',
                'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*',
                'LISTEN 0 128 [::]:22 [::]:*',
            ),
        )

        assert out == EXPOSURE_RESULT

    def test_says_other_accounts_process_names_are_hidden(
        self, tmp_path: Path, shell: str
    ):
        keys, _, _ = _check(tmp_path, shell)

        assert keys['processes'] == ('all' if os.geteuid() == 0 else 'own-only')


@pytest.mark.parametrize('shell', ['bash', 'sh'])
class TestDefaultCredentialLogin:
    def test_reports_the_minio_factory_login_as_accepted(
        self, tmp_path: Path, shell: str
    ):
        out, calls = _login(
            tmp_path,
            shell,
            SS_OUT=_ss('LISTEN 0 4096 0.0.0.0:9001 0.0.0.0:*'),
            CODES='http://127.0.0.1:9001/api/v1/login 204',
        )

        assert (
            out
            == 'login url=http://127.0.0.1:9001/api/v1/login code=204 result=accepted\n'
        )
        assert calls.startswith('-q --noproxy * ')
        assert f'Content-Type: application/json --data-binary {MINIO_BODY}' in calls

    def test_keeps_the_credential_out_of_the_command_text(
        self, tmp_path: Path, shell: str
    ):
        script = doc_blocks(CHECKS, 'sh')[1]

        assert 'minioadmin' not in script
        assert '"$EXPOSURE_BODY"' in script

    def test_a_204_without_the_services_session_cookie_is_unclear(
        self, tmp_path: Path, shell: str
    ):
        out, _ = _login(
            tmp_path,
            shell,
            SS_OUT=_ss('LISTEN 0 4096 0.0.0.0:9001 0.0.0.0:*'),
            CODES='http://127.0.0.1:9001/api/v1/login 204',
            HEADERS='HTTP/1.1 204 No Content',
        )

        assert out.endswith('code=204 result=unclear\n')

    def test_reports_a_changed_credential_as_rejected(self, tmp_path: Path, shell: str):
        out, _ = _login(
            tmp_path,
            shell,
            SS_OUT=_ss('LISTEN 0 4096 0.0.0.0:9001 0.0.0.0:*'),
            CODES='http://127.0.0.1:9001/api/v1/login 401',
        )

        assert out.endswith('code=401 result=rejected\n')

    def test_never_logs_in_to_a_loopback_only_console(self, tmp_path: Path, shell: str):
        out, calls = _login(
            tmp_path, shell, SS_OUT=_ss('LISTEN 0 4096 127.0.0.1:9001 0.0.0.0:*')
        )

        assert out == 'login port=9001 result=loopback_only\n'
        assert calls == ''

    def test_a_failing_ss_leaves_the_login_unknown(self, tmp_path: Path, shell: str):
        out, calls = _login(tmp_path, shell, SS_EXIT='1')

        assert out == 'login port=9001 result=unknown reason=ss-failed\n'
        assert calls == ''

    def test_tries_the_login_once_per_bound_interface(self, tmp_path: Path, shell: str):
        out, _ = _login(
            tmp_path,
            shell,
            SS_OUT=_ss(
                'LISTEN 0 4096 10.0.0.1:9001 0.0.0.0:*',
                'LISTEN 0 4096 10.0.0.2:9001 0.0.0.0:*',
            ),
            CODES='http://10.0.0.1:9001/api/v1/login 401\nhttp://10.0.0.2:9001/api/v1/login 204',
        )

        assert out.splitlines() == [
            'login url=http://10.0.0.1:9001/api/v1/login code=401 result=rejected',
            'login url=http://10.0.0.2:9001/api/v1/login code=204 result=accepted',
        ]

    def test_tries_both_families_of_a_dual_stack_listener(
        self, tmp_path: Path, shell: str
    ):
        out, _ = _login(
            tmp_path,
            shell,
            SS_OUT=_ss('LISTEN 0 4096 *:9001 *:*'),
            CODES='http://127.0.0.1:9001/api/v1/login 401\nhttp://[::1]:9001/api/v1/login 204',
        )

        assert out.splitlines() == [
            'login url=http://127.0.0.1:9001/api/v1/login code=401 result=rejected',
            'login url=http://[::1]:9001/api/v1/login code=204 result=accepted',
        ]

    def test_never_logs_in_where_nothing_listens(self, tmp_path: Path, shell: str):
        out, calls = _login(tmp_path, shell)

        assert out == 'login port=9001 result=not_listening\n'
        assert calls == ''

    def test_sends_basic_auth_instead_of_a_body_when_given(
        self, tmp_path: Path, shell: str
    ):
        out, calls = _login(
            tmp_path,
            shell,
            {'port': '8080', 'path': '/manager/html', 'accepted': '200', 'expect': ''},
            EXPOSURE_BASIC='tomcat:tomcat',
            EXPOSURE_BODY='',
            SS_OUT=_ss('LISTEN 0 100 0.0.0.0:8080 0.0.0.0:*'),
            CODES='http://127.0.0.1:8080/manager/html 200',
        )

        assert out.endswith('result=accepted\n')
        assert '-u tomcat:tomcat' in calls
        assert '--data-binary' not in calls
