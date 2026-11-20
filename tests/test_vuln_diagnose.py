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
        command = [node, '-e', code, fixes, str(package)]
    return run_with_fakes(command, tmp_path, PYTHONPATH=str(tmp_path))


def _rhel_verdict(
    tmp_path: Path,
    available: tuple[int, str],
    installed: tuple[int, str],
) -> subprocess.CompletedProcess[str]:
    """Run the documented RHEL check; each query answers (exit code, advisory lines)."""
    script = doc_blocks('vuln-diagnose/references/distro-package.md', 'sh')[1]
    script = script.replace('. /etc/os-release', 'ID=rocky; VERSION_ID=9')
    install_fakes(tmp_path, {'rpm': 'echo openssh-server-9.0', 'dnf': RHEL_DNF})
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
        assert result.stdout.startswith(f'verdict={verdict} package=openssh-server')

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
