import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / 'plugins/alpacon/skills'

APPROVED = 'Inst openssh-server [old] (fixed repo [amd64])'


@pytest.mark.parametrize('shell', ['bash', 'sh'])
@pytest.mark.parametrize(
    ('simulation', 'exit_code', 'before', 'installs', 'succeeds'),
    [
        (APPROVED, 0, '1:9.6p1-3ubuntu13.4', True, True),
        (
            APPROVED + '\nInst unexpected-daemon (1.0 repo [amd64])',
            0,
            '1:9.6p1-3ubuntu13.4',
            False,
            False,
        ),
        (
            'Inst openssh-server [old] (newer repo [amd64])',
            0,
            '1:9.6p1-3ubuntu13.4',
            False,
            False,
        ),
        ('Remv openssh-server [old]', 0, '1:9.6p1-3ubuntu13.4', False, False),
        (APPROVED, 100, '1:9.6p1-3ubuntu13.4', False, False),
        (APPROVED, 0, '1:9.6p1-3ubuntu13.5', False, True),
        (APPROVED, 0, '1:9.6p1-3ubuntu13.6', False, True),
    ],
)
def test_debian_recipe_installs_only_a_successful_approved_transaction(
    tmp_path: Path,
    shell: str,
    simulation: str,
    exit_code: int,
    before: str,
    installs: bool,
    succeeds: bool,
):
    recipe = (SKILLS / 'vuln-remediate/references/recipes.md').read_text()
    script = recipe.split('```bash\n', 1)[1].split('```', 1)[0]
    script = script.replace('. /etc/os-release', 'VERSION_CODENAME=noble')
    script = re.sub(
        r"approved_changes='[^']*'", f"approved_changes='{APPROVED}'", script
    )
    commands = {
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
    for name, body in commands.items():
        executable = tmp_path / name
        executable.write_text('#!/bin/sh\n' + body + '\n')
        executable.chmod(0o755)

    result = subprocess.run(  # noqa: S603  # repository examples and isolated fixtures
        [shell, '-c', script],
        env={
            **os.environ,
            'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
            'SIMULATION': simulation,
            'SIM_EXIT': str(exit_code),
            'INSTALL_MARKER': str(tmp_path / 'installed'),
            'INSTALL_ARGV': str(tmp_path / 'install-argv'),
            'BEFORE': before,
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert ('INSTALL_REACHED' in result.stdout) is installs, result.stderr
    assert (result.returncode == 0) is succeeds, result.stderr
    if installs:
        argv = (tmp_path / 'install-argv').read_text().splitlines()
        assert '--no-remove' in argv
        assert '--only-upgrade' in argv
        options = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '-o']
        assert 'Dpkg::Options::=--force-confold' in options
        assert 'DPkg::Lock::Timeout=120' in options
    if before != '1:9.6p1-3ubuntu13.4':
        assert 'UPDATE_REACHED' not in result.stdout


@pytest.mark.parametrize(
    ('before', 'after', 'installs', 'succeeds'),
    [
        ('1.7.3', '1.7.4', True, True),
        ('1.7.4', '1.7.4', False, True),
        ('1.7.5', '1.7.4', False, True),
        ('1.7.4-beta.1', '1.7.4', False, False),
        ('1.7.3', '1.7.3', True, False),
    ],
)
def test_npm_recipe_refuses_prereleases_and_preserves_fixed_installs(
    tmp_path: Path,
    before: str,
    after: str,
    installs: bool,
    succeeds: bool,
):
    if shutil.which('node') is None:
        pytest.skip('node is needed to run the documented npm recipe')
    reference = (SKILLS / 'vuln-remediate/references/recipes.md').read_text()
    script = re.findall(r'```bash\n(.*?)```', reference, re.S)[-1]
    script = script.replace('cd /srv/app', 'cd "$APP_DIR"')
    package = tmp_path / 'node_modules/axios/package.json'
    package.parent.mkdir(parents=True)
    package.write_text('{"version": "' + before + '"}')
    npm = tmp_path / 'npm'
    npm.write_text("""#!/bin/sh
[ "$*" = 'install axios@1.7.4 --save-exact' ] || exit 2
printf '{"version":"%s"}\\n' "$AFTER" > node_modules/axios/package.json
echo INSTALL_REACHED
""")
    npm.chmod(0o755)

    result = subprocess.run(  # noqa: S603  # repository example and isolated npm
        ['/bin/bash', '-c', script],
        env={
            **os.environ,
            'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
            'APP_DIR': str(tmp_path),
            'AFTER': after,
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert ('INSTALL_REACHED' in result.stdout) is installs, result.stderr
    assert (result.returncode == 0) is succeeds, result.stderr
    if succeeds and not installs:
        assert f'after={before}' in result.stdout
