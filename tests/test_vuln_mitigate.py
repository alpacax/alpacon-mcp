import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / 'plugins/alpacon/skills'


def _dropin_script(
    tmp_path: Path,
    *,
    filled: bool = True,
    expect: str = 'example_setting => on => on',
    baseline: str = 'example_setting => off => off',
    override: str | None = None,
    settings: str = 'example_setting',
    extra_override: str | None = None,
) -> tuple[str, Path]:
    reference = (SKILLS / 'vuln-mitigate/references/dropin.md').read_text()
    script = reference.split('```bash\n', 1)[1].split('```', 1)[0]
    dropin = tmp_path / '99-CVE-2026-0001-mitigation.ini'
    pools = tmp_path / 'pool.d'
    pools.mkdir()
    if override:
        (pools / 'www.conf').write_text(override + '\n')
    script = re.sub(r"dropin='[^']*'", f"dropin='{dropin}'", script)
    dirs = str(pools)
    if extra_override:
        extra = tmp_path / 'extra.d'
        extra.mkdir()
        (extra / 'more.conf').write_text(extra_override + '\n')
        dirs += f'\n{extra}'
    script = re.sub(r"pooldirs='[^']*'", f"pooldirs='{dirs}'", script)
    if filled:
        script = script.replace(
            'REPLACE_SETTING = REPLACE_VALUE', 'example_setting = on'
        )
        script = script.replace("expect='REPLACE_SETTING'", f"expect='{expect}'")
        script = script.replace("baseline='REPLACE_BASELINE'", f"baseline='{baseline}'")
        script = script.replace("settings='REPLACE_SETTING'", f"settings='{settings}'")
        script = script.replace('REPLACE-CVE-ID', 'CVE-2026-0001')
    fake = tmp_path / 'php-fpm8.1'
    fake.write_text(
        '#!/bin/sh\ncase "$1" in\n'
        '-t) [ -z "$FPM_LOCKDIR" ] || chmod 555 "$FPM_LOCKDIR"; [ "$FPM_OK" = 1 ] ;;\n'
        '-i) if grep -q "example_setting = on" "$DROPIN" 2>/dev/null; then\n'
        '      printf "%s\\n" "$FPM_INFO"; exit "${FPM_INFO_EXIT:-0}"\n'
        '    else printf "%s\\n" "$FPM_BEFORE"; fi ;;\n'
        'esac\n'
    )
    fake.chmod(0o755)
    return script, dropin


def _run_dropin(
    tmp_path: Path,
    script: str,
    fpm_ok: str,
    info: str = 'example_setting => on => on',
    info_exit: str = '0',
):
    return subprocess.run(  # noqa: S603  # repository examples and isolated fixtures
        [shutil.which('bash') or 'bash', '-c', script],
        env={
            **os.environ,
            'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
            'FPM_OK': fpm_ok,
            'FPM_INFO': info,
            'FPM_INFO_EXIT': info_exit,
            'FPM_BEFORE': 'example_setting => off => off',
            'DROPIN': str(tmp_path / '99-CVE-2026-0001-mitigation.ini'),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_dropin_is_written_once_and_a_rerun_leaves_it_unchanged(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)

    first = _run_dropin(tmp_path, script, '1')
    content = dropin.read_text()
    second = _run_dropin(tmp_path, script, '1')

    assert first.returncode == 0, first.stderr
    assert 'mitigation=applied' in first.stdout
    assert 'example_setting = on' in content
    assert second.returncode == 0, second.stderr
    assert 'mitigation=unchanged' in second.stdout
    assert dropin.read_text() == content
    assert 'vulnerable=still-present' in second.stdout
    assert list(tmp_path.glob('*.prev')) == []


def test_failed_config_test_removes_a_new_dropin(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)

    result = _run_dropin(tmp_path, script, '0')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert not dropin.exists()
    assert list(tmp_path.glob('*.prev')) == []


def test_failed_config_test_restores_the_previous_dropin(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    dropin.write_text('; older mitigation\n')

    result = _run_dropin(tmp_path, script, '0')

    assert result.returncode != 0
    assert dropin.read_text() == '; older mitigation\n'
    assert list(tmp_path.glob('*.prev')) == []


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores file modes')
def test_failed_write_restores_the_previous_dropin(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    dropin.write_text('; older mitigation\n')
    dropin.chmod(0o444)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert dropin.read_text() == '; older mitigation\n'
    assert list(tmp_path.glob('*.prev')) == []


def test_a_backup_that_cannot_be_removed_rolls_the_dropin_back(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    dropin.write_text('; older mitigation\n')
    fake_rm = tmp_path / 'rm'
    fake_rm.write_text(
        '#!/bin/sh\ncase "$*" in *.prev) exit 1 ;; esac\nexec /bin/rm "$@"\n'
    )
    fake_rm.chmod(0o755)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode == 1
    assert 'mitigation=' not in result.stdout
    assert 'drop-in rolled back' in result.stderr
    assert dropin.read_text() == '; older mitigation\n'
    assert list(tmp_path.glob('*.prev')) == []


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores file modes')
def test_a_rollback_that_fails_is_reported_and_leaves_the_file_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    script, dropin = _dropin_script(tmp_path)
    monkeypatch.setenv('FPM_LOCKDIR', str(tmp_path))

    result = _run_dropin(tmp_path, script, '0')
    tmp_path.chmod(0o755)

    assert result.returncode != 0
    assert 'rollback failed' in result.stderr
    assert str(dropin) in result.stderr
    assert 'drop-in rolled back' not in result.stderr


def test_dropin_is_rolled_back_when_the_value_in_effect_is_not_the_advised_one(
    tmp_path: Path,
):
    script, dropin = _dropin_script(tmp_path)

    result = _run_dropin(tmp_path, script, '1', info='example_setting => off => off')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert not dropin.exists()


def test_unfilled_template_writes_nothing(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path, filled=False)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert not dropin.exists()


def test_read_back_fails_when_the_read_command_fails_after_printing_the_line(
    tmp_path: Path,
):
    script, dropin = _dropin_script(tmp_path)

    result = _run_dropin(tmp_path, script, '1', info_exit='7')

    assert result.returncode != 0
    assert not dropin.exists()


def test_read_back_matches_the_whole_line_not_a_substring(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)

    result = _run_dropin(tmp_path, script, '1', info='xexample_setting => on => on')

    assert result.returncode != 0
    assert not dropin.exists()


def test_dropin_that_is_a_symlink_is_refused_and_its_target_left_alone(
    tmp_path: Path,
):
    script, dropin = _dropin_script(tmp_path)
    target = tmp_path / 'shared.conf'
    target.write_text('; shared\n')
    dropin.symlink_to(target)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert dropin.is_symlink()
    assert target.read_text() == '; shared\n'


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='needs a POSIX FIFO')
def test_dropin_that_is_a_fifo_is_refused_without_blocking(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    os.mkfifo(dropin)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'not a regular file' in result.stderr
    assert 'mitigation=' not in result.stdout


def test_dropin_that_is_a_directory_is_refused_before_any_backup(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    dropin.mkdir()

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'not a regular file' in result.stderr
    assert not Path(f'{dropin}.prev').exists()


def test_read_back_requires_every_expected_line(tmp_path: Path):
    script, dropin = _dropin_script(
        tmp_path, expect='example_setting => on => on\nsecond_setting => 1 => 1'
    )

    partial = _run_dropin(tmp_path, script, '1')
    missing_after_partial = dropin.exists()
    full = _run_dropin(
        tmp_path,
        script,
        '1',
        info='example_setting => on => on\nsecond_setting => 1 => 1',
    )

    assert partial.returncode != 0
    assert not missing_after_partial
    assert full.returncode == 0, full.stderr
    assert 'mitigation=applied' in full.stdout


def test_a_stale_backup_is_refused_and_nothing_is_changed(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    stale = Path(f'{dropin}.prev')
    stale.write_text('; left by an earlier run\n')

    result = _run_dropin(tmp_path, script, '0')

    assert result.returncode != 0
    assert not dropin.exists()
    assert stale.read_text() == '; left by an earlier run\n'


def test_a_value_changed_since_review_is_refused_before_anything_is_written(
    tmp_path: Path,
):
    script, dropin = _dropin_script(
        tmp_path, baseline='example_setting => other => other'
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert not dropin.exists()
    assert list(tmp_path.glob('*.prev')) == []


def test_a_pool_override_added_since_review_is_refused_before_anything_is_written(
    tmp_path: Path,
):
    script, dropin = _dropin_script(
        tmp_path, override='php_admin_value[example_setting] = off'
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert not dropin.exists()


def test_a_pool_override_added_after_the_first_run_is_caught_on_the_rerun(
    tmp_path: Path,
):
    script, dropin = _dropin_script(tmp_path)
    first = _run_dropin(tmp_path, script, '1')
    (tmp_path / 'pool.d/www.conf').write_text(
        'php_admin_value[example_setting] = off\n'
    )

    rerun = _run_dropin(tmp_path, script, '1')

    assert first.returncode == 0, first.stderr
    assert rerun.returncode != 0
    assert 'mitigation=' not in rerun.stdout


def test_a_pool_override_of_any_listed_setting_is_refused(tmp_path: Path):
    script, dropin = _dropin_script(
        tmp_path,
        settings='example_setting\nsecond_setting',
        override='php_admin_flag[second_setting] = off',
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert not dropin.exists()


def test_a_commented_pool_line_is_not_an_override(tmp_path: Path):
    script, dropin = _dropin_script(
        tmp_path, override=';php_admin_value[example_setting] = off'
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode == 0, result.stderr
    assert 'mitigation=applied' in result.stdout


def test_a_dot_in_a_setting_name_matches_only_a_dot(tmp_path: Path):
    script, dropin = _dropin_script(
        tmp_path,
        settings='example_setting\nfoo.bar',
        override='php_admin_value[fooXbar] = off',
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode == 0, result.stderr
    assert 'mitigation=applied' in result.stdout


def test_a_pool_override_in_a_second_listed_directory_is_refused(tmp_path: Path):
    script, dropin = _dropin_script(
        tmp_path, extra_override='php_admin_value[example_setting] = off'
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert not dropin.exists()


def test_a_pool_override_behind_a_symlinked_pool_file_is_refused(tmp_path: Path):
    script, dropin = _dropin_script(tmp_path)
    target = tmp_path / 'elsewhere.conf'
    target.write_text('php_admin_value[example_setting] = off\n')
    (tmp_path / 'pool.d/linked.conf').symlink_to(target)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert not dropin.exists()


def test_a_pool_override_with_space_before_the_bracket_is_refused(tmp_path: Path):
    script, dropin = _dropin_script(
        tmp_path, override='php_admin_value [example_setting] = off'
    )

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert not dropin.exists()


@pytest.mark.parametrize(
    'line',
    [
        'php_admin_value[ example_setting ] = off',
        'php_admin_value["example_setting"] = off',
        "php_admin_flag['example_setting'] = off",
    ],
)
def test_a_pool_override_with_spaces_or_quotes_in_the_brackets_is_refused(
    tmp_path: Path, line: str
):
    script, dropin = _dropin_script(tmp_path, override=line)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert not dropin.exists()


def test_a_hard_linked_dropin_is_refused_and_its_other_path_left_alone(
    tmp_path: Path,
):
    script, dropin = _dropin_script(tmp_path)
    other = tmp_path / 'shared.conf'
    other.write_text('; shared\n')
    os.link(other, dropin)

    result = _run_dropin(tmp_path, script, '1')

    assert result.returncode != 0
    assert 'mitigation=' not in result.stdout
    assert other.read_text() == '; shared\n'
