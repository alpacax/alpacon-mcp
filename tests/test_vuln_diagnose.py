import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.skill_scripts import doc_blocks, install_fakes, run_with_fakes

FIXES = '0.28=0.28.1 1.7=1.7.4'
RHEL_DNF = """case " $* " in
*" --available "*) printf '%s\\n' "$AVAILABLE"; exit "$AVAILABLE_EXIT" ;;
*" --installed "*) printf '%s\\n' "$INSTALLED"; exit "$INSTALLED_EXIT" ;;
*) exit 2 ;;
esac"""
RHEL_RPM = """case "$*" in *--qf*) echo 'version 0:9.0-1' ;; esac"""
FIXED_ADVISORY = 'RHSA-1 Security openssh-server-9.0'
PENDING_ADVISORY = 'RHSA-1 Security openssh-server-9.1'


def _language_verdict(
    tmp_path: Path, runtime: str, installed: str, fixes: str
) -> subprocess.CompletedProcess[str]:
    """Run the documented pip or npm check on a package installed at `installed`."""
    snippets = doc_blocks('vuln-diagnose/references/language-package.md', 'sh')
    if runtime == 'pip':
        tokens = shlex.split(snippets[0])
        code = tokens[tokens.index('-c') + 1]
        metadata = tmp_path / 'sample-1.0.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_text(f'Name: sample\nVersion: {installed}\n')
        command = [sys.executable, '-c', code, 'sample', fixes]
    else:
        node = shutil.which('node')
        if node is None:
            pytest.skip('node is needed to run the documented npm check')
        tokens = shlex.split(snippets[1])
        code = tokens[tokens.index('-e') + 1]
        package = tmp_path / 'package.json'
        package.write_text('{"version": "' + installed + '"}')
        command = [node, '-e', code, fixes]
        return run_with_fakes(command, tmp_path, stdin=f'{package}\nexit 0\n')
    return run_with_fakes(command, tmp_path, PYTHONPATH=str(tmp_path))


def _rhel_verdict(
    tmp_path: Path,
    available: tuple[int, str],
    installed: tuple[int, str],
) -> subprocess.CompletedProcess[str]:
    """Run the documented RHEL check; each query answers (exit code, advisory lines)."""
    script = doc_blocks('vuln-diagnose/references/distro-package.md', 'sh')[1]
    os_release = tmp_path / 'os-release'
    os_release.write_text('NAME="Rocky Linux"\nID=\'rocky\'\nVERSION_ID=9\n')
    script = script.replace('/etc/os-release', str(os_release))
    install_fakes(tmp_path, {'rpm': RHEL_RPM, 'dnf': RHEL_DNF})
    return run_with_fakes(
        ['/bin/sh', '-c', script],
        tmp_path,
        AVAILABLE_EXIT=str(available[0]),
        AVAILABLE=available[1],
        INSTALLED_EXIT=str(installed[0]),
        INSTALLED=installed[1],
    )


@pytest.mark.parametrize('runtime', ['pip', 'npm'])
class TestLanguageCheck:
    # happy path
    @pytest.mark.parametrize(
        ('installed', 'verdict'), [('1.7.3', 'affected'), ('1.7.5', 'not_affected')]
    )
    def test_judges_an_install_against_the_fix_on_its_release_line(
        self, tmp_path: Path, runtime: str, installed: str, verdict: str
    ):
        result = _language_verdict(tmp_path, runtime, installed, FIXES)

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(f'verdict={verdict} installed={installed}')

    # unhappy paths
    @pytest.mark.parametrize(
        ('installed', 'fixes'), [('2.0.0', FIXES), ('1.7.4rc1', '1.7=1.7.4')]
    )
    def test_an_install_the_advisory_cannot_place_is_unknown(
        self, tmp_path: Path, runtime: str, installed: str, fixes: str
    ):
        result = _language_verdict(tmp_path, runtime, installed, fixes)

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(f'verdict=unknown installed={installed}')

    # edge cases
    @pytest.mark.parametrize(
        ('installed', 'fixes'), [('1.7.4', FIXES), ('2.0.0', '=1.7.4')]
    )
    def test_the_fixed_release_itself_and_a_single_fix_for_every_line_are_not_affected(
        self, tmp_path: Path, runtime: str, installed: str, fixes: str
    ):
        result = _language_verdict(tmp_path, runtime, installed, fixes)

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(f'verdict=not_affected installed={installed}')


class TestRhelCheck:
    # happy path
    @pytest.mark.parametrize(
        ('available', 'installed', 'verdict'),
        [
            (PENDING_ADVISORY, '', 'affected'),
            ('', FIXED_ADVISORY, 'not_affected'),
        ],
    )
    def test_judges_a_server_by_the_advisory_dnf_lists(
        self, tmp_path: Path, available: str, installed: str, verdict: str
    ):
        result = _rhel_verdict(tmp_path, (0, available), (0, installed))

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            f'verdict={verdict} package=openssh-server release=rocky-9 installed=0:9.0-1\n'
        )

    # unhappy paths
    @pytest.mark.parametrize(
        ('available', 'installed'),
        [((1, ''), (0, FIXED_ADVISORY)), ((0, ''), (1, ''))],
    )
    def test_never_uses_a_failed_query_as_absence_of_an_advisory(
        self, tmp_path: Path, available: tuple[int, str], installed: tuple[int, str]
    ):
        result = _rhel_verdict(tmp_path, available, installed)

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith('verdict=unknown package=openssh-server')

    # edge cases
    def test_a_server_no_advisory_mentions_is_unknown(self, tmp_path: Path):
        result = _rhel_verdict(tmp_path, (0, ''), (0, ''))

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith('verdict=unknown package=openssh-server')


DEBIAN_STANZA = 'Package: openssh-server\nStatus: {}\nVersion: {}\n'
DEBIAN_FAKES = {
    'dpkg-query': '[ "$1" = -s ] || exit 9; printf %s "$STANZA"; exit "$DPKG_EXIT"',
    'dpkg': '[ "$1" = --compare-versions ] || exit 9; exit "$COMPARE_EXIT"',
}


def _debian_verdict(
    tmp_path: Path,
    stanza: str,
    *,
    codename: str = 'noble',
    dpkg_exit: int = 0,
    compare_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run the documented Debian check; `dpkg --compare-versions` answers `compare_exit`."""
    os_release = tmp_path / 'os-release'
    os_release.write_text(f'NAME="Ubuntu"\nVERSION_CODENAME={codename}\n')
    script = doc_blocks('vuln-diagnose/references/distro-package.md', 'sh')[0]
    script = script.replace('/etc/os-release', str(os_release))
    install_fakes(tmp_path, DEBIAN_FAKES)
    return run_with_fakes(
        ['/bin/sh', '-c', script],
        tmp_path,
        STANZA=stanza,
        DPKG_EXIT=str(dpkg_exit),
        COMPARE_EXIT=str(compare_exit),
    )


def test_checks_avoid_the_constructs_the_approval_gate_grades_high():
    debian, rpm, kernel = doc_blocks('vuln-diagnose/references/distro-package.md', 'sh')
    npm = doc_blocks('vuln-diagnose/references/language-package.md', 'sh')[1]

    for line in [debian, rpm, kernel, npm]:
        assert '$(' not in line
        assert '${' not in line
        assert '. /etc/os-release' not in line


class TestDebianCheck:
    # happy path
    @pytest.mark.parametrize(
        ('status', 'compare_exit', 'expected'),
        [
            (
                'hold ok installed',
                0,
                (
                    'verdict=affected package=openssh-server release=noble'
                    ' installed=1:9.6p1-3ubuntu13 fixed=1:9.6p1-3ubuntu13.5 status=hi'
                ),
            ),
            (
                'install ok installed',
                1,
                (
                    'verdict=not_affected package=openssh-server release=noble'
                    ' installed=1:9.6p1-3ubuntu13 fixed=1:9.6p1-3ubuntu13.5 status=ii'
                ),
            ),
        ],
    )
    def test_judges_an_installed_package_and_shows_its_dpkg_status(
        self, tmp_path: Path, status: str, compare_exit: int, expected: str
    ):
        stanza = DEBIAN_STANZA.format(status, '1:9.6p1-3ubuntu13')

        result = _debian_verdict(tmp_path, stanza, compare_exit=compare_exit)

        assert result.returncode == 0, result.stderr
        assert result.stdout == expected + '\n'

    # unhappy paths
    @pytest.mark.parametrize(
        ('stanza', 'dpkg_exit', 'reason'),
        [
            (
                DEBIAN_STANZA.format('install reinstreq half-installed', '1:9.6p1'),
                0,
                'reason=dpkg-query-exit-0 status=iHR',
            ),
            ('', 2, 'reason=dpkg-query-exit-2 status=u'),
        ],
    )
    def test_a_state_the_check_cannot_judge_is_unknown(
        self, tmp_path: Path, stanza: str, dpkg_exit: int, reason: str
    ):
        result = _debian_verdict(tmp_path, stanza, dpkg_exit=dpkg_exit)

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            f'verdict=unknown package=openssh-server release=noble {reason}\n'
        )

    def test_a_version_dpkg_cannot_order_is_unknown_not_fixed(self, tmp_path: Path):
        stanza = DEBIAN_STANZA.format('install ok installed', 'bad version')

        result = _debian_verdict(tmp_path, stanza, compare_exit=2)

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            'verdict=unknown package=openssh-server release=noble'
            ' installed=bad status=ii reason=unorderable-version\n'
        )

    def test_a_release_the_advisory_does_not_list_is_unknown(self, tmp_path: Path):
        stanza = DEBIAN_STANZA.format('install ok installed', '1:10.0p1')

        result = _debian_verdict(tmp_path, stanza, codename='questing')

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            'verdict=unknown release=questing reason=release-not-in-advisory\n'
        )

    # edge cases
    @pytest.mark.parametrize(
        ('stanza', 'dpkg_exit', 'status'),
        [
            (
                DEBIAN_STANZA.format('deinstall ok config-files', '1:9.6p1'),
                0,
                ' status=rc',
            ),
            (DEBIAN_STANZA.format('purge ok not-installed', ''), 0, ' status=pn'),
            ('', 1, ''),
        ],
    )
    def test_a_package_with_only_config_files_or_none_at_all_is_not_affected(
        self, tmp_path: Path, stanza: str, dpkg_exit: int, status: str
    ):
        result = _debian_verdict(tmp_path, stanza, dpkg_exit=dpkg_exit)

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            'verdict=not_affected package=openssh-server release=noble'
            f' installed=none{status}\n'
        )

    @pytest.mark.parametrize('codename', ['"focal"', "'focal'"])
    def test_a_quoted_codename_and_a_release_with_no_fix_are_read(
        self, tmp_path: Path, codename: str
    ):
        stanza = DEBIAN_STANZA.format('hold ok installed', '1:8.2p1-4ubuntu0.11')

        result = _debian_verdict(tmp_path, stanza, codename=codename)

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            'verdict=affected package=openssh-server release=focal'
            ' installed=1:8.2p1-4ubuntu0.11 status=hi reason=no-fix-available\n'
        )


class TestKernelCheck:
    # happy path
    def test_a_fixed_image_installed_beside_an_old_running_kernel_is_reboot_pending(
        self, tmp_path: Path
    ):
        result = _kernel_verdict(
            tmp_path, 'ii  linux-image-6.8.0-50-generic 6.8.0-50.51 arm64 x'
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            'verdict=affected running=6.8.0-40.40 flavour=generic'
            ' fixed=6.8.0-45.45 reason=reboot-pending\n'
        )

    # edge cases
    def test_an_image_with_only_config_files_left_is_not_reboot_pending(
        self, tmp_path: Path
    ):
        result = _kernel_verdict(
            tmp_path, 'rc  linux-image-6.8.0-50-generic 6.8.0-50.51 arm64 x'
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            'verdict=affected running=6.8.0-40.40 flavour=generic fixed=6.8.0-45.45\n'
        )


def _kernel_verdict(tmp_path: Path, images: str) -> subprocess.CompletedProcess[str]:
    """Run the documented kernel check on a noble 6.8.0-40 generic kernel with `images` listed."""
    os_release = tmp_path / 'os-release'
    os_release.write_text('VERSION_CODENAME=noble\n')
    signature = tmp_path / 'version_signature'
    signature.write_text('Ubuntu 6.8.0-40.40-generic 6.8.12\n')
    script = doc_blocks('vuln-diagnose/references/distro-package.md', 'sh')[2]
    script = script.replace('/etc/os-release', str(os_release))
    script = script.replace('/proc/version_signature', str(signature))
    install_fakes(
        tmp_path,
        {
            'dpkg-query': '[ "$1 $2" = "-l linux-image-6.8.0-[0-9]*-generic" ] || exit 9;'
            ' echo "||/ Name Version"; printf "%s\\n" "$IMAGES"',
            'dpkg': 'case "$2" in 6.8.0-50.51) exit 0 ;; *) exit 1 ;; esac',
        },
    )
    return run_with_fakes(['/bin/sh', '-c', script], tmp_path, IMAGES=images)
