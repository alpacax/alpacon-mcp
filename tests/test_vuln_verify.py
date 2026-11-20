import re
import subprocess
from pathlib import Path

import pytest

from tests.skill_scripts import doc_blocks, install_fakes, run_with_fakes

DPKG_LOG = (
    '2026-11-15 10:00:00 upgrade openssh-server:arm64'
    ' 1:9.6p1-3ubuntu13.4 1:9.6p1-3ubuntu13.6\n'
    '2026-11-15 10:00:01 upgrade openssh-sftp-server:arm64'
    ' 1:9.6p1-3ubuntu13.4 1:9.6p1-3ubuntu13.6\n'
)


def _combined_line(
    tmp_path: Path, needrestart: str, package: str = 'openssh-server'
) -> subprocess.CompletedProcess[str]:
    """Run the documented one-line verify on a fixed noble server; `needrestart` is the fake's body."""
    os_release = tmp_path / 'os-release'
    os_release.write_text('VERSION_CODENAME=noble\n')
    (tmp_path / 'dpkg.log').write_text(DPKG_LOG)
    script = re.sub(r'^\s+', '', doc_blocks('vuln-verify/SKILL.md', 'sh')[0]).strip()
    script = script.replace('/etc/os-release', str(os_release))
    script = script.replace('/var/log/dpkg.log', str(tmp_path / 'dpkg.log'))
    script = script.replace('p=openssh-server;', f'p={package};', 1)
    install_fakes(
        tmp_path,
        {
            'dpkg-query': "printf 'Status: install ok installed\\nVersion: 1:9.6p1-3ubuntu13.6\\n'",
            'dpkg': 'exit 1',
            'systemctl': "printf 'Id=ssh.service\\nActiveState=active\\n'",
            'needrestart': needrestart,
        },
    )
    return run_with_fakes(['/bin/sh', '-c', script], tmp_path)


def test_combined_line_avoids_the_constructs_the_approval_gate_grades_high():
    line = doc_blocks('vuln-verify/SKILL.md', 'sh')[0]

    assert '$(' not in line
    assert '${' not in line
    assert '. /etc/os-release' not in line


class TestCombinedLine:
    def test_reports_the_verdict_the_units_and_the_stale_services(self, tmp_path: Path):
        result = _combined_line(
            tmp_path, 'echo "NEEDRESTART-VER: 3.6"; echo "NEEDRESTART-SVC: ssh.service"'
        )

        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert lines[0].startswith('verdict=not_affected package=openssh-server')
        assert 'ActiveState=active' in lines
        assert [line for line in lines if line.startswith('NEEDRESTART-')] == [
            'NEEDRESTART-SVC: ssh.service'
        ]
        assert 'needrestart_exit: 0' in lines

    @pytest.mark.parametrize(
        ('needrestart', 'exit_line'),
        [
            ('echo "NEEDRESTART-VER: 3.6"', 'needrestart_exit: 0'),
            ('exit 127', 'needrestart_exit: 127'),
            ('echo "NEEDRESTART-VER: 3.6"; exit 1', 'needrestart_exit: 1'),
        ],
        ids=['empty-list', 'missing', 'failed'],
    )
    def test_tells_an_empty_scan_from_one_that_never_ran(
        self, tmp_path: Path, needrestart: str, exit_line: str
    ):
        result = _combined_line(tmp_path, needrestart)

        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert lines[0].startswith('verdict=not_affected package=openssh-server')
        assert 'ActiveState=active' in lines
        assert not [line for line in lines if line.startswith('NEEDRESTART-')]
        assert [line for line in lines if line.startswith('needrestart_exit:')] == [
            exit_line
        ]

    @pytest.mark.parametrize('package', ['openssh-server', 'openssh-server:arm64'])
    def test_finds_the_last_upgrade_with_or_without_an_architecture(
        self, tmp_path: Path, package: str
    ):
        result = _combined_line(tmp_path, 'exit 127', package)

        assert result.returncode == 0, result.stderr
        assert [
            line
            for line in result.stdout.splitlines()
            if line.startswith('last_upgrade:')
        ] == [
            (
                'last_upgrade: 2026-11-15 10:00:00 upgrade openssh-server:arm64'
                ' 1:9.6p1-3ubuntu13.4 1:9.6p1-3ubuntu13.6'
            )
        ]
