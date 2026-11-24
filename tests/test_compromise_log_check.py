import bz2
import gzip
import json
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
import yaml  # type: ignore[import-untyped]

from tests.eval_mocks import LOG_RESULT
from tests.skill_scripts import doc_blocks, install_fakes

SEARCH = 'compromise-log-check/references/search.md'
TIME = '[04/Aug/2026:10:12:01 +0900]'
HOME = f'198.51.100.7 - - {TIME} "GET / HTTP/1.1" 200 512 "-" "curl/8"'
RESET = (
    f'203.0.113.9 - - {TIME} "POST /api/session/reset_password?token=s3cret HTTP/1.1"'
    ' 400 64 "https://ref.example/private" "agent-x"'
)
CURRENT = (
    f'203.0.113.9 - - {TIME} "GET /api/user/current HTTP/1.1" 200 900 "-" "agent-x"'
)
SECOND = doc_blocks(SEARCH, 'text')[0].strip()
NOTICE = '2026/08/04 10:12:01 [notice] 42#42: signal process started'
NOTICE_MARK = '^[0-9/]+ [0-9:]+ [[]notice[]] '

pytestmark = pytest.mark.parametrize('shell', ['sh', 'bash'])


def _search(shell: str, *logs: Path, **values: str) -> list[str]:
    """Run the documented search, filled with `values`; returns its output lines."""
    script = doc_blocks(SEARCH, 'sh')[0]
    for name, value in {'logs': '\n'.join(map(str, logs)), **values}.items():
        found = re.search(rf"^{name}='[^']*'$", script, re.M)
        assert found, f'{name} is not a fillable value'
        script = script.replace(found[0], f"{name}='{value}'", 1)
    with NamedTemporaryFile('w', suffix='.sh') as file:
        file.write(script)
        file.flush()
        result = subprocess.run(  # noqa: S603  # repository snippet on temporary files
            [shell, file.name], text=True, capture_output=True, check=False, timeout=10
        )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def _file_lines(out: list[str]) -> dict[str, str]:
    rows = (re.match(r'file path=(\S+) status=(\w+)', line) for line in out)
    return {Path(m[1]).name: m[2] for m in rows if m}


@pytest.fixture
def log(tmp_path: Path) -> Path:
    path = tmp_path / 'access.log'
    path.write_text(HOME + '\n')
    return path


@pytest.fixture
def locked_dir(tmp_path: Path) -> Iterator[Path]:
    """A directory the test locks; restored afterwards so pytest can remove it."""
    path = tmp_path / 'locked'
    path.mkdir()
    yield path
    path.chmod(0o700)


def test_search_counts_matches_in_rotated_and_compressed_copies(
    shell: str, log: Path
) -> None:
    Path(f'{log}.1').write_text(RESET + '\n')
    Path(f'{log}.2.gz').write_bytes(gzip.compress((RESET + '\n').encode()))
    Path(f'{log}-20260801.bz2').write_bytes(bz2.compress((RESET + '\n').encode()))

    out = _search(shell, log)

    assert 'total pattern=1 count=3 shown=3' in out
    assert out[-1] == 'search=complete files=4 problems=0'


def test_search_reports_zero_and_complete_when_nothing_matches(
    shell: str, log: Path
) -> None:
    out = _search(shell, log)

    assert 'total pattern=1 count=0 shown=0' in out
    assert out[-1] == 'search=complete files=1 problems=0'


def test_match_leaves_query_referer_and_agent_on_the_host(
    shell: str, log: Path
) -> None:
    log.write_text(RESET + '\n')

    out = _search(shell, log)

    assert (
        f'match pattern=1 file={log} line=1 text=203.0.113.9 - - {TIME} '
        '"POST /api/session/reset_password?..." 400 '
    ) in out
    assert not re.search('s3cret|ref.example|agent-x', '\n'.join(out))


def test_file_line_shows_only_what_precedes_the_request(shell: str, log: Path) -> None:
    log.write_text(HOME.replace('GET /', 'GET /hidden-path') + '\n')

    out = _search(shell, log)

    prefix = f'198.51.100.7 - - {TIME} '
    assert (
        f'file path={log} status=ok lines=1 control=1 first=[{prefix}] last=[{prefix}]'
        in out
    )
    assert 'hidden-path' not in '\n'.join(out)


@pytest.mark.parametrize(
    'body', [b'junk', gzip.compress((RESET + '\n').encode())[:-12]]
)
def test_broken_archive_is_not_read_as_no_match(
    shell: str, log: Path, body: bytes
) -> None:
    Path(f'{log}.1.gz').write_bytes(body)

    out = _search(shell, log)

    assert _file_lines(out)['access.log.1.gz'] == 'read_failed'
    assert out[-1] == 'search=incomplete files=2 problems=1'


def test_match_in_a_readable_file_survives_a_broken_archive(
    shell: str, log: Path
) -> None:
    log.write_text(RESET + '\n')
    Path(f'{log}.1.gz').write_bytes(b'junk')

    out = _search(shell, log)

    assert 'total pattern=1 count=1 shown=1' in out
    assert out[-1] == 'search=incomplete files=2 problems=1'


def test_log_in_another_format_is_incomplete(shell: str, log: Path) -> None:
    log.write_text('{"path": "/api/session/reset_password", "status": 400}\n')

    out = _search(shell, log)

    assert _file_lines(out) == {'access.log': 'no_control'}
    assert out[-1] == 'search=incomplete files=1 problems=1'


def test_only_empty_logs_are_incomplete(shell: str, log: Path) -> None:
    log.write_text('')

    out = _search(shell, log)

    assert _file_lines(out) == {'access.log': 'empty'}
    assert out[-1] == 'search=incomplete files=1 problems=0'


def test_missing_log_is_incomplete(shell: str, log: Path) -> None:
    out = _search(shell, log, log.with_name('other.log'))

    assert _file_lines(out)['other.log'] == 'missing'
    assert out[-1] == 'search=incomplete files=2 problems=1'


@pytest.mark.skipif(os.geteuid() == 0, reason='root reads everything')
def test_unreadable_rotated_copy_is_incomplete(shell: str, log: Path) -> None:
    old = Path(f'{log}.1')
    old.write_text(RESET + '\n')
    old.chmod(0)

    out = _search(shell, log)

    assert _file_lines(out)['access.log.1'] == 'unreadable'
    assert out[-1] == 'search=incomplete files=2 problems=1'


@pytest.mark.skipif(os.geteuid() == 0, reason='root lists everything')
def test_directory_that_cannot_be_listed_is_incomplete(
    shell: str, locked_dir: Path
) -> None:
    log = locked_dir / 'access.log'
    log.write_text(HOME + '\n')
    Path(f'{log}.1').write_text(RESET + '\n')
    locked_dir.chmod(0o311)

    out = _search(shell, log)

    assert f'file path={log} status=dir_unreadable' in out
    assert out[-1] == 'search=incomplete files=2 problems=1'


def test_base_log_that_is_a_pipe_does_not_hang_the_search(
    shell: str, tmp_path: Path
) -> None:
    log = tmp_path / 'access.log'
    os.mkfifo(log)

    out = _search(shell, log)

    assert _file_lines(out) == {'access.log': 'not_regular'}
    assert out[-1] == 'search=incomplete files=1 problems=1'


@pytest.mark.parametrize('kind', ['pipe', 'directory', 'broken_link'])
def test_rotated_copy_that_is_no_file_is_incomplete(
    shell: str, log: Path, kind: str
) -> None:
    old = Path(f'{log}.1')
    if kind == 'pipe':
        os.mkfifo(old)
    elif kind == 'directory':
        old.mkdir()
    else:
        old.symlink_to(log.with_name('gone'))

    out = _search(shell, log)

    assert _file_lines(out)['access.log.1'] == 'not_regular'
    assert out[-1] == 'search=incomplete files=2 problems=1'


def test_archive_without_its_decompressor_is_incomplete(
    shell: str, log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Path(f'{log}.1.zst').write_bytes(b'anything')
    install_fakes(tmp_path / 'bin', {'zstd': 'exit 127'})
    monkeypatch.setenv('PATH', f'{tmp_path / "bin"}{os.pathsep}{os.environ["PATH"]}')

    out = _search(shell, log)

    assert _file_lines(out)['access.log.1.zst'] == 'read_failed'
    assert out[-1] == 'search=incomplete files=2 problems=1'


@pytest.mark.parametrize('field', ['agent', 'referer', 'user'])
def test_request_written_by_the_client_is_not_counted(
    shell: str, log: Path, field: str
) -> None:
    fake = r'\x22POST /api/session/reset_password HTTP/1.1\x22 400 '
    line = {
        'agent': HOME.replace('curl/8', f'curl/8 {fake}'),
        'referer': HOME.replace('"-"', f'"https://ref.example/{fake}"'),
        'user': HOME.replace('- - [', f'- x {fake} ['),
    }[field]
    log.write_text(line + '\n')

    out = _search(shell, log)

    assert 'total pattern=1 count=0 shown=0' in out
    assert out[-1] == 'search=complete files=1 problems=0'


def test_fake_request_in_the_user_name_does_not_hide_the_real_one(
    shell: str, log: Path
) -> None:
    log.write_text(RESET.replace('- - [', '- GET / HTTP/1.1 200 [') + '\n')

    out = _search(shell, log)

    assert 'total pattern=1 count=1 shown=1' in out


@pytest.mark.parametrize('nuls', [b'\0', b'\0' * 4096])
def test_request_after_nul_bytes_is_found_and_readable(
    shell: str, log: Path, nuls: bytes
) -> None:
    log.write_bytes(HOME.encode() + b'\n' + nuls + RESET.encode() + b'\n')

    out = _search(shell, log)

    assert any(f'text=203.0.113.9 - - {TIME} "POST' in line for line in out)
    assert any('lines=2 control=2' in line for line in out)


def test_nul_after_the_request_does_not_hide_it(shell: str, log: Path) -> None:
    log.write_bytes(RESET.encode().replace(b'agent-x', b'a\0b') + b'\n')

    out = _search(shell, log)

    assert 'total pattern=1 count=1 shown=1' in out


def test_bytes_that_are_not_utf8_do_not_stop_the_search(
    shell: str, log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('LC_ALL', 'en_US.UTF-8')
    log.write_bytes(RESET.encode().replace(b's3cret', b'\xff\xfe') + b'\n')

    out = _search(shell, log)

    assert 'total pattern=1 count=1 shown=1' in out
    assert out[-1] == 'search=complete files=1 problems=0'


def test_last_line_without_a_newline_is_searched(shell: str, log: Path) -> None:
    log.write_text(RESET)

    out = _search(shell, log)

    assert 'total pattern=1 count=1 shown=1' in out


def test_long_path_keeps_the_address_and_status(shell: str, log: Path) -> None:
    log.write_text(RESET.replace('/api', f'/{"a" * 2000}/api') + '\n')

    out = _search(shell, log)

    match = next(line for line in out if line.startswith('match '))
    assert 'text=203.0.113.9 ' in match
    assert match.endswith('" 400 ')
    assert 'a' * 400 not in match


def test_each_pattern_gets_its_own_total(shell: str, log: Path) -> None:
    anchor = re.search(r"^patterns='(.*)'$", doc_blocks(SEARCH, 'sh')[0], re.M)
    assert anchor
    log.write_text('\n'.join([RESET, CURRENT, CURRENT, '']))

    out = _search(shell, log, patterns=f'{anchor[1]}\n{SECOND}')

    assert 'total pattern=1 count=1 shown=1' in out
    assert 'total pattern=2 count=2 shown=2' in out


@pytest.mark.parametrize('name', ['patterns', 'control', 'skip'])
@pytest.mark.parametrize(
    'value', [r'POST \S+', r'HTTP/\d', '(?i)post', '[[:digit:]]', 'a{3}']
)
def test_expression_some_awk_builds_misread_is_refused(
    shell: str, log: Path, name: str, value: str
) -> None:
    out = _search(shell, log, **{name: value})

    assert out == ['search=incomplete reason=unsupported-expression']


@pytest.mark.parametrize(
    'values',
    [
        {'patterns': 'POST ('},
        {'patterns': 'POST (', 'also': '^other '},
        {'control': '"[^"'},
        {'skip': '['},
    ],
)
def test_bad_expression_is_refused_before_any_file_is_read(
    shell: str, log: Path, values: dict[str, str]
) -> None:
    out = _search(shell, log, **values)

    assert out == ['search=incomplete reason=bad-expression']


@pytest.mark.parametrize(
    'value', [r'a\<b', r'a\>b', r'a\`b', r'[^\]]', r'x\\\]', '/{,2}api', 'a{2,}']
)
def test_escape_some_awk_builds_misread_is_refused(
    shell: str, log: Path, value: str
) -> None:
    out = _search(shell, log, patterns=value)

    assert out == ['search=incomplete reason=unsupported-expression']


def test_record_run_into_the_tail_of_a_broken_line_is_not_read(
    shell: str, log: Path
) -> None:
    log.write_bytes(
        b'blog.example 198.51.100.8 - - [04/Au' + b'\0' * 8 + RESET.encode() + b'\n'
    )

    out = _search(shell, log)

    assert 'total pattern=1 count=0 shown=0' in out
    assert any('status=no_control lines=1 control=0' in line for line in out)


@pytest.mark.parametrize('show', ['', '0', '-1', '1.5'])
def test_show_that_is_not_a_positive_whole_number_is_refused(
    shell: str, log: Path, show: str
) -> None:
    out = _search(shell, log, show=show)

    assert out == ['search=incomplete reason=bad-show']


def test_patterns_of_empty_lines_only_are_empty_input(shell: str, log: Path) -> None:
    out = _search(shell, log, patterns='\n\n')

    assert out == ['search=incomplete reason=empty-input']


@pytest.mark.parametrize('tail', ['', '\nlast'])
def test_end_marker_written_in_the_log_is_counted_as_a_line(
    shell: str, log: Path, tail: str
) -> None:
    log.write_text(f'END-OF-LOG 0\n{RESET}{tail}\n')

    out = _search(shell, log)

    lines = 3 if tail else 2
    assert any(' line=2 ' in line for line in out if line.startswith('match '))
    assert any(f'status=partial lines={lines} control=1' in line for line in out)


@pytest.mark.parametrize('name', ['patterns', 'control', 'logs'])
def test_empty_input_is_incomplete(shell: str, log: Path, name: str) -> None:
    out = _search(shell, log, **{name: ''})

    assert out == ['search=incomplete reason=empty-input']


def test_shown_matches_are_capped_and_the_count_is_not(shell: str, log: Path) -> None:
    log.write_text((RESET + '\n') * 25)

    out = _search(shell, log)

    assert 'total pattern=1 count=25 shown=10' in out
    assert sum(line.startswith('match ') for line in out) == 10


def test_matches_come_oldest_file_first(shell: str, log: Path) -> None:
    log.write_text(RESET + '\n')
    old = Path(f'{log}.1')
    old.write_text(RESET + '\n')
    os.utime(old, (1_700_000_000, 1_700_000_000))

    out = _search(shell, log)

    files = [line.split()[2] for line in out if line.startswith('match ')]
    assert files == [f'file={old}', f'file={log}']
    assert f'mtime path={old} utc=2023-11-14T22:13:20Z' in out


def test_match_gives_its_place_so_same_second_requests_keep_their_order(
    shell: str, log: Path
) -> None:
    log.write_text(f'{HOME}\n\n{CURRENT}\n{RESET}\n')

    anchor = re.search("^patterns='(.*)'$", doc_blocks(SEARCH, 'sh')[0], re.M)
    assert anchor

    out = _search(
        shell, log, patterns=f'{anchor[1]}\n{SECOND}', also=f'^203.0.113.9 \n{TIME}'
    )

    places = [line.split()[1:4] for line in out if line.startswith('match ')]
    assert places == [
        ['pattern=2', f'file={log}', 'line=2'],
        ['pattern=1', f'file={log}', 'line=3'],
    ]


def test_method_outside_the_common_list_is_still_read(shell: str, log: Path) -> None:
    log.write_text(HOME.replace('GET /', 'PROPFIND /dav') + '\n')

    out = _search(shell, log, patterns='^"PROPFIND /dav ')

    assert 'total pattern=1 count=1 shown=1' in out
    assert out[-1] == 'search=complete files=1 problems=0'


@pytest.mark.parametrize(
    'request_text', ['', '-', r'\x16\x03\x01', r'GET /a\"b HTTP/1.1']
)
def test_malformed_request_is_counted_as_read(
    shell: str, log: Path, request_text: str
) -> None:
    log.write_text(HOME.replace('GET / HTTP/1.1', request_text) + '\n')

    out = _search(shell, log)

    assert any('status=ok lines=1 control=1' in line for line in out)


def test_line_in_another_format_makes_the_file_partial(shell: str, log: Path) -> None:
    log.write_text(HOME + '\n{"method":"POST","path":"/x","status":400}\n')

    out = _search(shell, log)

    assert any('status=partial lines=2 control=1' in line for line in out)
    assert out[-1] == 'search=incomplete files=1 problems=1'


def test_known_non_request_line_is_left_out(shell: str, log: Path) -> None:
    log.write_text(f'{HOME}\n{NOTICE}\n{RESET}\n')

    out = _search(shell, log, skip=NOTICE_MARK)

    assert any('status=ok lines=2 control=2' in line for line in out)
    assert any(
        line.startswith('match pattern=1 ') and ' line=2 ' in line for line in out
    )
    assert out[-1] == 'search=complete files=1 problems=0'


def test_request_in_another_format_beside_a_skipped_line_is_partial(
    shell: str, log: Path
) -> None:
    unparsed = '{"method":"POST","path":"/api/session/reset_password","status":400}'
    log.write_text(f'{HOME}\n{NOTICE}\n{unparsed}\n')

    out = _search(shell, log, skip=NOTICE_MARK)

    assert any('status=partial lines=2 control=1' in line for line in out)
    assert out[-1] == 'search=incomplete files=1 problems=1'


def test_skip_does_not_hide_a_request_line(shell: str, log: Path) -> None:
    log.write_text(RESET.replace('agent-x', '[notice] x') + '\n')

    out = _search(shell, log, skip='[[]notice[]]')

    assert 'total pattern=1 count=1 shown=1' in out


def test_file_of_skipped_lines_only_is_empty(shell: str, log: Path) -> None:
    log.write_text(NOTICE + '\n')

    out = _search(shell, log, skip=NOTICE_MARK)

    assert _file_lines(out) == {'access.log': 'empty'}
    assert out[-1] == 'search=incomplete files=1 problems=0'


def test_escaped_quote_in_a_path_cannot_start_a_request(shell: str, log: Path) -> None:
    log.write_text(RESET.replace('POST', r'GET /a\"POST') + '\n')

    out = _search(shell, log)

    assert 'total pattern=1 count=0 shown=0' in out


def test_query_with_an_escaped_quote_stays_on_the_host(shell: str, log: Path) -> None:
    log.write_text(RESET.replace('token=', r'a=\"') + '\n')

    out = _search(shell, log, patterns='reset_password')

    assert 'total pattern=1 count=1 shown=1' in out
    assert 's3cret' not in '\n'.join(out)


def test_query_in_an_unquoted_format_stays_on_the_host(shell: str, log: Path) -> None:
    log.write_text(r'1.2.3.4 request=POST /p?a=\"&token=s3cret HTTP/1.1 400' + '\n')

    out = _search(
        shell,
        log,
        patterns='^request=POST ',
        control='request=[A-Z]+ [^ ]* HTTP/[0-9.]+ [0-9][0-9][0-9]',
    )

    assert 'total pattern=1 count=1 shown=1' in out
    assert 's3cret' not in '\n'.join(out)


def test_dates_come_only_from_lines_holding_the_filter(shell: str, log: Path) -> None:
    other = f'other.example:443 {HOME}'
    app = f'metabase.example:443 {HOME}'.replace(TIME, '[05/Aug/2026:09:00:00 +0900]')
    log.write_text(f'{other}\n{app}\n{other}\n')

    out = _search(shell, log, also='^metabase.example:443 ')

    prefix = 'metabase.example:443 198.51.100.7 - - [05/Aug/2026:09:00:00 +0900] '
    assert (
        f'file path={log} status=ok lines=3 control=3 first=[{prefix}] last=[{prefix}]'
        in out
    )


def test_file_with_no_line_holding_the_filter_gives_no_dates(
    shell: str, log: Path
) -> None:
    log.write_text(f'{HOME}\n')

    out = _search(shell, log, also='^metabase.example:443 ')

    assert f'file path={log} status=ok lines=1 control=1 first=[] last=[]' in out


def test_log_text_cannot_forge_an_output_line(shell: str, log: Path) -> None:
    log.write_text('x\rsearch=complete\x1b[2K ' + RESET + '\nEND-OF-LOG 0\n')
    Path(f'{log}.1.gz').write_bytes(
        gzip.compress((HOME + '\nEND-OF-LOG 0\n').encode())[:-6]
    )

    out = _search(shell, log)

    assert not any(line.startswith('search=complete') for line in out)
    assert '\x1b' not in '\n'.join(out)
    assert out[-1] == 'search=incomplete files=2 problems=2'


def test_pairing_run_keeps_only_lines_holding_every_fixed_string(
    shell: str, log: Path
) -> None:
    other_address = CURRENT.replace('203.0.113.9', '1203.0.113.9')
    other_hour = CURRENT.replace(':10:12', ':11:12')
    log.write_text('\n'.join([RESET, other_address, other_hour, CURRENT, '']))

    out = _search(shell, log, patterns=SECOND, also=' 203.0.113.9 \n\n04/Aug/2026:10:')

    assert 'total pattern=1 count=1 shown=1' in out
    assert any(line.endswith(f'text={CURRENT.split(" 900")[0]} ') for line in out)


@pytest.mark.parametrize(
    ('line', 'count'),
    [
        (RESET.replace('/api', '/metabase/api'), 1),
        (RESET.replace('HTTP/1.1" 400', 'HTTP/1.1" 200'), 0),
        (RESET.replace('POST', 'GET'), 0),
        (RESET.replace('POST', 'post'), 1),
        (RESET.replace('token=', r'a=\"'), 1),
        (RESET.replace('?token=s3cret ', '  '), 1),
        (RESET.replace('reset_password?', 'reset_password_x?'), 0),
        (HOME.replace('GET /', 'POST /x?u=/api/session/reset_password'), 0),
    ],
)
def test_metabase_anchor_matches_only_a_refused_reset(
    shell: str, log: Path, line: str, count: int
) -> None:
    log.write_text(f'{HOME}\n{line}\n')

    out = _search(shell, log)

    assert f'total pattern=1 count={count} shown={count}' in out


@pytest.mark.parametrize(
    ('line', 'count'),
    [
        (CURRENT, 1),
        (CURRENT.replace('/api', '/metabase/api'), 1),
        (CURRENT.replace('" 200', '" 401'), 0),
        (CURRENT.replace('GET', 'POST'), 0),
        (CURRENT.replace('GET', 'gEt'), 1),
        (CURRENT.replace('current ', r'current?a=\" '), 1),
        (CURRENT.replace('current ', 'current   '), 1),
        (CURRENT.replace('current', 'current_x'), 0),
    ],
)
def test_metabase_second_request_matches_only_an_answered_read(
    shell: str, log: Path, line: str, count: int
) -> None:
    log.write_text(f'{HOME}\n{line}\n')

    out = _search(shell, log, patterns=SECOND)

    assert f'total pattern=1 count={count} shown={count}' in out


def test_user_name_equal_to_the_address_does_not_crowd_out_the_pair(
    shell: str, log: Path
) -> None:
    decoy = CURRENT.replace('203.0.113.9 - -', '198.51.100.7 - 203.0.113.9')
    log.write_text('\n'.join([decoy] * 11 + [CURRENT, '']))

    out = _search(shell, log, patterns=SECOND, also='^203.0.113.9 ')

    assert 'total pattern=1 count=1 shown=1' in out


@pytest.mark.parametrize('suffix', ['.1 status=ok', '.1\tstatus=ok', '.1\nstatus=ok'])
def test_rotated_name_cannot_forge_a_status(shell: str, log: Path, suffix: str) -> None:
    Path(f'{log}{suffix}').symlink_to(log.with_name('gone'))

    out = _search(shell, log)

    assert out[-1].startswith('search=incomplete')


def test_listing_that_fails_is_incomplete(
    shell: str, log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fakes(tmp_path / 'bin', {'ls': f'echo "{log}"; exit 1'})
    monkeypatch.setenv('PATH', f'{tmp_path / "bin"}{os.pathsep}{os.environ["PATH"]}')

    out = _search(shell, log)

    assert f'file path={log} status=list_failed' in out
    assert not any('not_regular' in line or 'list-failed' in line for line in out)
    assert out[-1].startswith('search=incomplete')


@pytest.mark.parametrize('name', ['list-failed', 'unsafe-name'])
def test_log_named_like_an_error_reads_as_a_log(
    shell: str, tmp_path: Path, name: str
) -> None:
    log = tmp_path / f'{name}.log'
    log.write_text(HOME + '\n')

    out = _search(shell, log)

    assert _file_lines(out) == {f'{name}.log': 'ok'}
    assert out[-1] == 'search=complete files=1 problems=0'


@pytest.mark.parametrize(
    'rotate',
    [
        'mv "$LOG.1" "$LOG.2"; mv "$LOG" "$LOG.1"; : > "$LOG"',
        'rm "$LOG.1"',
        ': > "$LOG"',
        'cp "$LOG" "$LOG.1"; : > "$LOG"',
        (
            'tr a-z A-Z < "$LOG.1" > "$LOG.x"; /bin/cat "$LOG.x" > "$LOG.1"; '
            'rm "$LOG.x"; TZ=UTC touch -t 202311142213.20 "$LOG.1"'
        ),
    ],
)
def test_rotation_during_the_search_is_incomplete(
    shell: str,
    log: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rotate: str,
) -> None:
    old = Path(f'{log}.1')
    old.write_text(HOME + '\n')
    os.utime(old, (1_700_000_000, 1_700_000_000))
    done = tmp_path / 'rotated'
    install_fakes(
        tmp_path / 'bin',
        {'cat': f'/bin/cat; [ -e "{done}" ] || {{ : > "{done}"; {rotate}; }}'},
    )
    monkeypatch.setenv('LOG', str(log))
    monkeypatch.setenv('PATH', f'{tmp_path / "bin"}{os.pathsep}{os.environ["PATH"]}')

    out = _search(shell, log)

    assert f'file path={log} status=changed' in out
    assert out[-1].startswith('search=incomplete')


def test_newline_in_a_rotated_name_reads_no_other_file(
    shell: str, log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log.with_name('other.txt').write_text(RESET + '\n')
    Path(f'{log}.1\nother.txt').write_text(HOME + '\n')
    monkeypatch.chdir(log.parent)

    out = _search(shell, log)

    assert 'total pattern=1 count=0 shown=0' in out
    assert f'file path={log} status=unsafe_name' in out
    assert out[-1] == 'search=incomplete files=2 problems=1'


def test_eval_mock_output_is_what_the_search_prints(shell: str, log: Path) -> None:
    def row(time: str) -> str:
        return HOME.replace(TIME, f'[{time} +0900]') + '\n'

    old = Path(f'{log}.1')
    old.write_text(row('10/Nov/2026:00:00:04') + row('22/Nov/2026:23:59:51'))
    log.write_text(row('23/Nov/2026:15:59:58'))
    os.utime(old, (1_795_359_600, 1_795_359_600))
    os.utime(log, (1_795_417_198, 1_795_417_198))

    out = _search(shell, log)

    printed = [line.replace(str(log), '/var/log/nginx/access.log') for line in out]
    assert printed[1:] == LOG_RESULT.splitlines()[1:]


PAIR_MOCK = (
    Path(__file__).parent.parent
    / 'plugins/alpacon/evals/compromise-log-check-pairs-only-a-later-request'
    / 'mocks/alpacon/execute_file.md'
)


def _pair_case_logs(log: Path) -> None:
    """The nginx logs the pairing eval's answers describe, at their line numbers."""

    def row(address: str, time: str, request: str = 'GET / HTTP/1.1" 200 1') -> str:
        return f'{address} - - [{time} +0900] "{request}'

    filler = row('192.0.2.5', '01/Aug/2026:00:00:04')
    old = [filler] * 81200
    old[-1] = row('192.0.2.5', '22/Nov/2026:23:59:51')
    for place, address, time, request in [
        (
            20077,
            '198.51.100.44',
            '04/Aug/2026:10:04:17',
            'GET /api/user/current HTTP/1.1" 200 900',
        ),
        (
            20113,
            '198.51.100.44',
            '04/Aug/2026:10:12:01',
            'POST /api/session/reset_password HTTP/1.1" 400 64',
        ),
        (
            27450,
            '203.0.113.9',
            '05/Aug/2026:02:31:40',
            'POST /api/session/reset_password HTTP/1.1" 400 64',
        ),
        (
            27452,
            '203.0.113.9',
            '05/Aug/2026:02:31:43',
            'GET /api/user/current HTTP/1.1" 200 900',
        ),
    ]:
        old[place - 1] = row(address, time, request)
    new = [row('192.0.2.5', '23/Nov/2026:00:00:02')] * 409 + [
        row('192.0.2.5', '23/Nov/2026:15:59:58')
    ]
    rotated = Path(f'{log}.1')
    rotated.write_text('\n'.join(old) + '\n')
    log.write_text('\n'.join(new) + '\n')
    os.utime(rotated, (1_795_359_600, 1_795_359_600))
    os.utime(log, (1_795_417_198, 1_795_417_198))


def test_pairing_eval_answers_are_what_the_search_prints(shell: str, log: Path) -> None:
    _pair_case_logs(log)
    anchor = re.search("^patterns='(.*)'$", doc_blocks(SEARCH, 'sh')[0], re.M)
    assert anchor
    answers = re.findall(r'```text\n(.*?)```', PAIR_MOCK.read_text(), re.S)

    runs = [
        _search(shell, log),
        _search(shell, log, patterns=SECOND, also='^198.51.100.44 '),
        _search(shell, log, patterns=SECOND, also='^203.0.113.9 '),
    ]

    for out, answer in zip(runs, answers, strict=True):
        printed = [line.replace(str(log), '/var/log/nginx/access.log') for line in out]
        assert printed[1:] == answer.splitlines()[1:]


def _graders() -> list[tuple[str, str]]:
    evals = Path(__file__).parent.parent / 'plugins/alpacon/evals'
    return [
        (grader['name'], grader['input_match'])
        for case in sorted(evals.glob('compromise-log-check-*/case.yaml'))
        for grader in yaml.safe_load(case.read_text())['graders']
        if grader.get('tool', '').endswith('execute_file')
        and 'patterns=' in grader.get('input_match', '')
        and grader.get('max') != 0
    ]


@pytest.mark.parametrize(('name', 'input_match'), _graders())
def test_eval_grader_accepts_only_the_documented_expression(
    shell: str, name: str, input_match: str
) -> None:
    script = doc_blocks(SEARCH, 'sh')[0]
    anchor = re.search("^patterns='(.*)'$", script, re.M)
    assert anchor
    if 'user/current' in input_match:
        script = script.replace(anchor[1], SECOND)
    address = re.search(r"also='\\\^([0-9.\\]+) '", input_match)
    if address:
        script = script.replace(
            "also=''", f"also='^{address[1].replace(chr(92), '')} '"
        )

    def submitted(text: str) -> str:
        return json.dumps({'content': text})

    assert re.search(input_match, submitted(script)), name
    for wrong in [
        ('[Pp][Oo][Ss][Tt]', 'GET'),
        ('[Gg][Ee][Tt]', 'POST'),
        ('" 400', '" 200'),
        ('" 200', '" 401'),
    ]:
        if wrong[0] in script:
            assert not re.search(
                input_match, submitted(script.replace(wrong[0], wrong[1], 1))
            ), (name, wrong)
