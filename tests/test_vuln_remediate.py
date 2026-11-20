import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.skill_scripts import doc_blocks, install_fakes, run_with_fakes

RECIPES = 'vuln-remediate/references/recipes.md'
APPROVED = 'Inst openssh-server [old] (fixed repo [amd64])'
VULNERABLE = '1:9.6p1-3ubuntu13.4'
DEBIAN_FAKES = {
    'dpkg-query': '[ -f "$INSTALL_MARKER" ] && echo 1:9.6p1-3ubuntu13.5 || echo "$BEFORE"',
    'dpkg': """[ "$1" = --compare-versions ] && [ "$3" = ge ] && [ "$4" = 1:9.6p1-3ubuntu13.5 ] || exit 2
case "$2" in 1:9.6p1-3ubuntu13.5|1:9.6p1-3ubuntu13.6) exit 0 ;; *) exit 1 ;; esac""",
    'apt-get': """case "$1" in
update) echo UPDATE_REACHED; exit 0 ;;
-s) printf '%s\\n' "$SIMULATION"; exit "$SIM_EXIT" ;;
install)
  printf '%s\\n' "$@" > "$INSTALL_ARGV"
  touch "$INSTALL_MARKER"; echo INSTALL_REACHED ;;
esac""",
}
NPM_FAKE = """[ "$*" = 'install axios@1.7.4 --save-exact' ] || exit 2
printf '{"version":"%s"}\\n' "$AFTER" > node_modules/axios/package.json
echo INSTALL_REACHED"""


def _debian_recipe(
    tmp_path: Path,
    shell: str,
    simulation: str = APPROVED,
    exit_code: int = 0,
    before: str = VULNERABLE,
) -> subprocess.CompletedProcess[str]:
    """Run the documented Debian recipe, approved for `APPROVED`, against a fake apt."""
    script = doc_blocks(RECIPES, 'bash')[0]
    script = script.replace('. /etc/os-release', 'VERSION_CODENAME=noble')
    script = re.sub(
        r"approved_changes='[^']*'", f"approved_changes='{APPROVED}'", script
    )
    install_fakes(tmp_path, DEBIAN_FAKES)
    return run_with_fakes(
        [shell, '-c', script],
        tmp_path,
        SIMULATION=simulation,
        SIM_EXIT=str(exit_code),
        INSTALL_MARKER=str(tmp_path / 'installed'),
        INSTALL_ARGV=str(tmp_path / 'install-argv'),
        BEFORE=before,
    )


def _npm_recipe(
    tmp_path: Path, before: str, after: str
) -> subprocess.CompletedProcess[str]:
    """Run the documented npm recipe on axios at `before`; the fake install leaves `after`."""
    if shutil.which('node') is None:
        pytest.skip('node is needed to run the documented npm recipe')
    script = doc_blocks(RECIPES, 'bash')[-1].replace('cd /srv/app', 'cd "$APP_DIR"')
    package = tmp_path / 'node_modules/axios/package.json'
    package.parent.mkdir(parents=True)
    package.write_text('{"version": "' + before + '"}')
    install_fakes(tmp_path, {'npm': NPM_FAKE})
    return run_with_fakes(
        ['/bin/bash', '-c', script], tmp_path, APP_DIR=str(tmp_path), AFTER=after
    )


@pytest.mark.parametrize('shell', ['bash', 'sh'])
class TestDebianRecipe:
    # happy path
    def test_installs_the_approved_transaction_without_removals_or_prompts(
        self, tmp_path: Path, shell: str
    ):
        result = _debian_recipe(tmp_path, shell)

        assert result.returncode == 0, result.stderr
        assert 'INSTALL_REACHED' in result.stdout
        argv = (tmp_path / 'install-argv').read_text().splitlines()
        assert '--no-remove' in argv
        assert '--only-upgrade' in argv
        options = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '-o']
        assert 'Dpkg::Options::=--force-confold' in options
        assert 'DPkg::Lock::Timeout=120' in options

    # unhappy paths
    @pytest.mark.parametrize(
        ('simulation', 'exit_code'),
        [
            (APPROVED + '\nInst unexpected-daemon (1.0 repo [amd64])', 0),
            ('Inst openssh-server [old] (newer repo [amd64])', 0),
            ('Remv openssh-server [old]', 0),
            (APPROVED, 100),
        ],
    )
    def test_refuses_a_transaction_other_than_the_approved_one(
        self, tmp_path: Path, shell: str, simulation: str, exit_code: int
    ):
        result = _debian_recipe(tmp_path, shell, simulation, exit_code)

        assert result.returncode != 0
        assert 'INSTALL_REACHED' not in result.stdout

    # edge cases
    @pytest.mark.parametrize('before', ['1:9.6p1-3ubuntu13.5', '1:9.6p1-3ubuntu13.6'])
    def test_leaves_a_server_at_or_past_the_fix_untouched(
        self, tmp_path: Path, shell: str, before: str
    ):
        result = _debian_recipe(tmp_path, shell, before=before)

        assert result.returncode == 0, result.stderr
        assert 'INSTALL_REACHED' not in result.stdout
        assert 'UPDATE_REACHED' not in result.stdout


class TestNpmRecipe:
    # happy path
    def test_installs_the_fix_over_a_vulnerable_version(self, tmp_path: Path):
        result = _npm_recipe(tmp_path, '1.7.3', '1.7.4')

        assert result.returncode == 0, result.stderr
        assert 'INSTALL_REACHED' in result.stdout

    # unhappy paths
    def test_refuses_a_prerelease_before_npm_runs(self, tmp_path: Path):
        result = _npm_recipe(tmp_path, '1.7.4-beta.1', '1.7.4')

        assert result.returncode != 0
        assert 'INSTALL_REACHED' not in result.stdout

    def test_fails_when_the_install_did_not_reach_the_fix(self, tmp_path: Path):
        result = _npm_recipe(tmp_path, '1.7.3', '1.7.3')

        assert result.returncode != 0
        assert 'INSTALL_REACHED' in result.stdout

    # edge cases
    @pytest.mark.parametrize('before', ['1.7.4', '1.7.5'])
    def test_leaves_an_install_at_or_past_the_fix_untouched(
        self, tmp_path: Path, before: str
    ):
        result = _npm_recipe(tmp_path, before, '1.7.4')

        assert result.returncode == 0, result.stderr
        assert 'INSTALL_REACHED' not in result.stdout
        assert f'after={before}' in result.stdout
