import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / 'plugins/alpacon/skills'


@pytest.mark.parametrize('runtime', ['pip', 'npm'])
@pytest.mark.parametrize(
    ('installed', 'fixes', 'verdict'),
    [
        ('2.0.0', '0.28=0.28.1 1.7=1.7.4', 'unknown'),
        ('1.7.3', '0.28=0.28.1 1.7=1.7.4', 'affected'),
        ('1.7.4', '0.28=0.28.1 1.7=1.7.4', 'not_affected'),
        ('1.7.5', '0.28=0.28.1 1.7=1.7.4', 'not_affected'),
        ('2.0.0', '=1.7.4', 'not_affected'),
        ('1.7.4rc1', '1.7=1.7.4', 'unknown'),
    ],
)
def test_language_check_uses_only_advisory_release_lines(
    tmp_path: Path, runtime: str, installed: str, fixes: str, verdict: str
):
    reference = (SKILLS / 'vuln-diagnose/references/language-package.md').read_text()
    snippets = re.findall(r'```sh\n(.*?)```', reference, re.S)
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

    result = subprocess.run(  # noqa: S603  # repository examples and isolated fixtures
        command,
        env={**os.environ, 'PYTHONPATH': str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f'verdict={verdict} installed={installed}')


@pytest.mark.parametrize(
    ('available_exit', 'available', 'installed_exit', 'installed', 'verdict'),
    [
        (1, '', 0, 'RHSA-1 Security openssh-server-9.0', 'unknown'),
        (0, '', 1, '', 'unknown'),
        (0, '', 0, 'RHSA-1 Security openssh-server-9.0', 'not_affected'),
        (0, 'RHSA-1 Security openssh-server-9.1', 0, '', 'affected'),
        (0, '', 0, '', 'unknown'),
    ],
)
def test_rhel_check_never_uses_a_failed_query_as_absence_of_an_advisory(
    tmp_path: Path,
    available_exit: int,
    available: str,
    installed_exit: int,
    installed: str,
    verdict: str,
):
    reference = (SKILLS / 'vuln-diagnose/references/distro-package.md').read_text()
    script = re.findall(r'```sh\n(.*?)```', reference, re.S)[1]
    script = script.replace('. /etc/os-release', 'ID=rocky; VERSION_ID=9')
    commands = {
        'rpm': 'echo openssh-server-9.0',
        'dnf': """case " $* " in
*" --available "*) printf '%s\\n' "$AVAILABLE"; exit "$AVAILABLE_EXIT" ;;
*" --installed "*) printf '%s\\n' "$INSTALLED"; exit "$INSTALLED_EXIT" ;;
*) exit 2 ;;
esac""",
    }
    for name, body in commands.items():
        executable = tmp_path / name
        executable.write_text('#!/bin/sh\n' + body + '\n')
        executable.chmod(0o755)

    result = subprocess.run(  # noqa: S603  # repository example and isolated commands
        ['/bin/sh', '-c', script],
        env={
            **os.environ,
            'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
            'AVAILABLE': available,
            'AVAILABLE_EXIT': str(available_exit),
            'INSTALLED': installed,
            'INSTALLED_EXIT': str(installed_exit),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f'verdict={verdict} package=openssh-server')
