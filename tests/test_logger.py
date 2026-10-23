"""Tests for the logging setup in utils/logger.py.

The file sink must not run on the caller's thread: in remote mode every tool
call shares one event loop, and a FileHandler flushes to disk on every record.
"""

import io
import json
import logging
import logging.handlers
import sys
import threading
from contextlib import contextmanager

import pytest
import uvicorn

from utils.logger import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    LOG_VALUE_MAX_CHARS,
    AlpaconLogger,
    JsonFormatter,
    SharedRotatingFileHandler,
    SingleLineFormatter,
    describe_for_log,
    escape_for_log,
    json_logs_requested,
    redact_for_log,
)


async def _unserved_app(scope, receive, send) -> None:
    """Stand-in ASGI app: these tests build a uvicorn Config only for its logging."""


@contextmanager
def _built_manager():
    """Build a logger manager, restoring the root logger afterwards."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    # basicConfig does nothing when the root logger already has handlers, and
    # pytest installs its own.
    root.handlers.clear()
    instance = AlpaconLogger()
    assert instance.listener is not None
    file_sinks = instance.listener.handlers
    try:
        yield instance, root.handlers[:]
    finally:
        instance.stop_listener()
        for sink in file_sinks:
            sink.close()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """Build a logger manager in a scratch cwd."""
    monkeypatch.chdir(tmp_path)
    with _built_manager() as built:
        yield built


def _queue_handler(handlers):
    return next(h for h in handlers if isinstance(h, logging.handlers.QueueHandler))


class TestRotatingFileSink:
    """The log file is capped, so a long-running server cannot fill the disk."""

    def test_the_listener_writes_through_a_rotating_file_handler(self, manager):
        instance, _ = manager

        (sink,) = instance.listener.handlers

        assert isinstance(sink, SharedRotatingFileHandler)
        assert sink.maxBytes == LOG_MAX_BYTES
        assert sink.backupCount == LOG_BACKUP_COUNT

    def test_a_full_log_file_rolls_over_and_keeps_only_the_backup_count(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr('utils.logger.LOG_MAX_BYTES', 200)
        monkeypatch.setattr('utils.logger.LOG_BACKUP_COUNT', 2)
        with _built_manager() as (instance, handlers):
            queue_handler = _queue_handler(handlers)

            for i in range(20):
                queue_handler.handle(_record('rotation record %s', i))
            instance.stop_listener()

        log_dir = tmp_path / 'logs'
        assert sorted(p.name for p in log_dir.iterdir()) == [
            'alpacon-mcp.log',
            'alpacon-mcp.log.1',
            'alpacon-mcp.log.2',
            'alpacon-mcp.log.lock',
        ]
        assert all(p.stat().st_size <= 200 for p in log_dir.iterdir())
        assert 'rotation record 19' in (log_dir / 'alpacon-mcp.log').read_text()


def _shared_sink(path, max_bytes, backup_count=1000):
    handler = SharedRotatingFileHandler(
        path, max_bytes=max_bytes, backup_count=backup_count
    )
    handler.setFormatter(logging.Formatter('%(message)s'))
    return handler


def _logged_lines(log_dir):
    return [
        line
        for path in log_dir.iterdir()
        if not path.name.endswith('.lock')
        for line in path.read_text().splitlines()
    ]


class TestSharedFileSink:
    """Each handler stands in for one stdio server: its own descriptors, and a lock
    that conflicts the way another process's would."""

    def test_a_record_after_another_writer_rolled_over_lands_in_the_live_file(
        self, tmp_path
    ):
        log_file = tmp_path / 'alpacon-mcp.log'
        first, second = _shared_sink(log_file, 200), _shared_sink(log_file, 200)
        second.handle(_record('second writer opened the file'))

        for i in range(10):
            first.handle(_record('first writer record %s', i))
        second.handle(_record('second writer after rollover'))
        first.close()
        second.close()

        assert (tmp_path / 'alpacon-mcp.log.1').exists()
        assert 'second writer after rollover' in log_file.read_text()

    def test_concurrent_writers_lose_no_record_and_never_overfill_a_file(
        self, tmp_path
    ):
        log_file = tmp_path / 'alpacon-mcp.log'
        writers = [_shared_sink(log_file, 500) for _ in range(2)]

        def write_all(index, handler):
            for i in range(200):
                handler.handle(_record('writer %s record %s', index, i))

        threads = [
            threading.Thread(target=write_all, args=(index, handler))
            for index, handler in enumerate(writers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for handler in writers:
            handler.close()

        expected = {f'writer {w} record {i}' for w in range(2) for i in range(200)}
        lines = _logged_lines(tmp_path)
        assert len(lines) == len(expected)
        assert set(lines) == expected
        assert all(p.stat().st_size <= 500 for p in tmp_path.iterdir())

    def test_no_log_file_stays_open_between_records(self, tmp_path):
        """On Windows a file another process holds open cannot be renamed."""
        handler = _shared_sink(tmp_path / 'alpacon-mcp.log', 200)

        handler.handle(_record('one record'))

        assert handler.stream is None
        handler.close()


class TestQueuedFileSink:
    """The FileHandler belongs to the listener thread, not to the root logger."""

    def test_root_handlers_carry_a_queue_handler_and_no_file_handler(self, manager):
        """A FileHandler on the root logger would write from the event loop thread."""
        _, handlers = manager

        assert any(isinstance(h, logging.handlers.QueueHandler) for h in handlers)
        assert not any(isinstance(h, logging.FileHandler) for h in handlers)

    def test_stderr_stream_handler_is_kept(self, manager):
        """Container log collection reads stderr, so that sink stays direct."""
        _, handlers = manager

        assert any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
            and h.stream is sys.stderr
            for h in handlers
        )

    def test_records_reach_the_log_file_through_the_listener(self, manager, tmp_path):
        """Stopping the listener drains the queue, so the record lands in the file."""
        instance, handlers = manager
        queue_handler = next(
            h for h in handlers if isinstance(h, logging.handlers.QueueHandler)
        )

        queue_handler.handle(
            logging.LogRecord(
                'alpacon_mcp.test',
                logging.INFO,
                __file__,
                1,
                'listener carried this',
                None,
                None,
            )
        )
        instance.stop_listener()

        log_file = tmp_path / 'logs' / 'alpacon-mcp.log'
        line = next(
            entry
            for entry in log_file.read_text().splitlines()
            if 'listener carried this' in entry
        )
        # Twice means the queue handler formatted the prefix the file handler adds.
        assert line.count('alpacon_mcp.test - INFO') == 1
        assert line.endswith('listener carried this')

    def test_stop_listener_is_idempotent(self, manager):
        """Shutdown may run twice; the second call must not raise."""
        instance, _ = manager

        instance.stop_listener()
        instance.stop_listener()


# A client value carrying a line break and what a real record looks like
# after it: unescaped, a log reader starts a second record at the timestamp.
FORGED_LINE = '\r\n2026-09-30 01:02:03 - alpacon_mcp.auth - INFO - [auth.py:1] - forged'


def _record(msg, *args, exc_info=None):
    return logging.LogRecord(
        'alpacon_mcp.test', logging.WARNING, __file__, 1, msg, args, exc_info
    )


class TestOneRecordOneLine:
    """No value inside a record can make a sink print a line a reader takes
    for a record of its own."""

    def test_a_line_break_in_a_value_stays_on_the_record_line(self, manager):
        instance, _ = manager

        output = instance.stream_handler.format(
            _record('Rejected value: %s', FORGED_LINE)
        )

        assert '\n' not in output
        assert '\r' not in output
        assert output.endswith(
            'Rejected value: \\r\\n2026-09-30 01:02:03 - '
            'alpacon_mcp.auth - INFO - [auth.py:1] - forged'
        )

    def test_no_traceback_line_starts_where_a_record_would(self, manager):
        """A traceback keeps its lines, each indented under the record line."""
        instance, _ = manager
        try:
            raise ValueError(f'bad value {FORGED_LINE}')
        except ValueError:
            exc_info = sys.exc_info()

        output = instance.stream_handler.format(_record('failed', exc_info=exc_info))
        first, *rest = output.split('\n')

        assert first.endswith('failed')
        assert rest, 'the traceback should follow the record line'
        assert all(line == '' or line[0].isspace() for line in rest)
        assert '\r' not in output

    def test_the_log_file_gets_the_same_single_line_record(self, manager, tmp_path):
        instance, handlers = manager
        queue_handler = next(
            h for h in handlers if isinstance(h, logging.handlers.QueueHandler)
        )

        queue_handler.handle(_record('file value: %s', FORGED_LINE))
        instance.stop_listener()

        lines = (tmp_path / 'logs' / 'alpacon-mcp.log').read_text().splitlines()
        assert len(lines) == 1
        assert 'file value: \\r\\n2026-09-30' in lines[0]


class TestUvicornRecords:
    """uvicorn writes through its own stderr handler and formatter."""

    def test_an_application_traceback_stays_under_its_record(self, manager, capsys):
        uvicorn.Config(app=_unserved_app, log_level='info')
        try:
            raise ValueError(f'bad value {FORGED_LINE}\nINFO:     forged')
        except ValueError:
            logging.getLogger('uvicorn.error').exception(
                'Exception in ASGI application'
            )

        first, *rest = capsys.readouterr().err.rstrip('\n').split('\n')

        assert first.endswith('Exception in ASGI application')
        assert rest
        assert all(line == '' or line[0].isspace() for line in rest)

    def test_a_message_value_is_escaped(self, manager, capsys):
        uvicorn.Config(app=_unserved_app, log_level='info')

        logging.getLogger('uvicorn.error').warning('value: %s', FORGED_LINE)

        assert capsys.readouterr().err.count('\n') == 1


@pytest.fixture
def http_json_manager(manager, monkeypatch):
    monkeypatch.setenv('LOG_FORMAT', 'json')
    instance, _ = manager
    instance.use_json_stdout()
    return manager


@pytest.fixture
def uvicorn_loggers_as_log_config_none(monkeypatch):
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        monkeypatch.setattr(logging.getLogger(name), 'handlers', [])
        monkeypatch.setattr(logging.getLogger(name), 'propagate', True)


class TestHttpJsonFormat:
    def test_a_record_carries_the_standard_envelope(self, http_json_manager):
        instance, _ = http_json_manager

        record = _record('token %s', 'expired')
        record.created = 0.0123
        record.msecs = 12.3

        output = instance.stream_handler.format(record)

        entry = json.loads(output)
        assert entry['level'] == 'WARNING'
        assert entry['message'] == 'token expired'
        assert entry['name'] == 'alpacon_mcp.test'
        assert entry['timestamp'] == '1970-01-01T00:00:00.012Z'

    def test_records_go_to_stdout(self, http_json_manager):
        instance, _ = http_json_manager

        assert instance.stream_handler.stream is sys.stdout
        assert isinstance(instance.stream_handler.formatter, JsonFormatter)

    def test_a_line_break_in_a_value_stays_on_the_record_line(self, http_json_manager):
        instance, _ = http_json_manager

        output = instance.stream_handler.format(
            _record('Rejected value: %s', FORGED_LINE)
        )

        assert '\n' not in output
        assert json.loads(output)['message'] == f'Rejected value: {FORGED_LINE}'

    def test_a_traceback_goes_into_the_error_fields_on_one_line(
        self, http_json_manager
    ):
        instance, _ = http_json_manager
        try:
            raise ValueError('bad value')
        except ValueError:
            exc_info = sys.exc_info()

        output = instance.stream_handler.format(_record('failed', exc_info=exc_info))

        assert '\n' not in output
        entry = json.loads(output)
        assert entry['error.kind'] == 'ValueError'
        assert entry['error.message'] == 'bad value'
        assert entry['error.stack'].endswith('ValueError: bad value')

    def test_no_log_file_is_written(self, http_json_manager, tmp_path):
        instance, _ = http_json_manager

        logging.getLogger('alpacon_mcp.test').warning('stdout only')

        assert instance.queue_handler not in logging.getLogger().handlers
        assert instance.listener is None
        assert not (tmp_path / 'logs' / 'alpacon-mcp.log').exists()

    def test_uvicorn_records_come_out_as_json(
        self, http_json_manager, uvicorn_loggers_as_log_config_none, monkeypatch
    ):
        instance, _ = http_json_manager
        stdout = io.StringIO()
        monkeypatch.setattr(instance.stream_handler, 'stream', stdout)
        uvicorn.Config(app=_unserved_app, log_level='info', log_config=None)

        logging.getLogger('uvicorn.error').warning('value: %s', FORGED_LINE)
        logging.getLogger('uvicorn.access').info(
            '%s - "%s %s HTTP/%s" %d', '10.0.0.1:5000', 'GET', '/mcp?code=x', '1.1', 401
        )

        entries = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert [e['level'] for e in entries] == ['WARNING', 'INFO']
        assert entries[0]['message'] == f'value: {FORGED_LINE}'
        assert entries[1]['message'] == '10.0.0.1:5000 - "GET /mcp HTTP/1.1" 401'

    @pytest.mark.parametrize(
        ('value', 'expected'),
        [
            ('json', True),
            ('JSON', True),
            (' json\n', True),
            (None, False),
            ('', False),
            ('console', False),
            ('yaml', False),
        ],
    )
    def test_json_logs_are_requested_only_for_json(self, monkeypatch, value, expected):
        if value is None:
            monkeypatch.delenv('LOG_FORMAT', raising=False)
        else:
            monkeypatch.setenv('LOG_FORMAT', value)

        requested = json_logs_requested()

        assert requested is expected

    def test_an_empty_exception_tuple_adds_no_error_fields(self, http_json_manager):
        instance, _ = http_json_manager
        record = _record('no exception', exc_info=(None, None, None))

        entry = json.loads(instance.stream_handler.format(record))

        assert not any(key.startswith('error.') for key in entry)

    def test_stdio_keeps_text_on_stderr_even_with_log_format_json(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('LOG_FORMAT', 'json')

        with _built_manager() as (instance, _):
            handler = instance.stream_handler

        assert handler.stream is sys.stderr
        assert isinstance(handler.formatter, SingleLineFormatter)


class TestThirdPartyLoggers:
    """Libraries below this server log what it deliberately keeps out."""

    @pytest.mark.parametrize('name', ['httpx', 'httpcore', 'httpx2', 'httpcore2'])
    def test_http_libraries_log_warnings_only(self, manager, name):
        """At INFO httpx writes each request URL with its query string, and at
        DEBUG httpcore writes the response headers."""
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING

    def test_the_mcp_sdk_stays_at_info_under_debug(self, manager, monkeypatch):
        """At DEBUG the SDK writes each client message, tool arguments included."""
        monkeypatch.setenv('ALPACON_MCP_LOG_LEVEL', 'DEBUG')
        root = logging.getLogger()
        root.handlers.clear()
        instance = AlpaconLogger()
        try:
            assert logging.getLogger('mcp').getEffectiveLevel() == logging.INFO
        finally:
            instance.stop_listener()

    def test_the_access_log_drops_the_query_string(self, manager):
        """The OAuth callback carries the authorization code in its query."""
        uvicorn.Config(app=_unserved_app, log_level='info')
        record = logging.LogRecord(
            'uvicorn.access',
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ('10.0.0.1:5000', 'GET', '/oauth/callback?code=abc&state=xyz', '1.1', 302),
            None,
        )

        assert logging.getLogger('uvicorn.access').filter(record)
        assert 'code=abc' not in record.getMessage()
        assert '/oauth/callback' in record.getMessage()


class TestEscapeForLog:
    """Tests for the client-value escaping helper."""

    def test_escapes_a_line_break(self):
        assert escape_for_log('a\r\nb') == 'a\\r\\nb'

    def test_accepts_a_value_that_is_not_a_string(self):
        assert escape_for_log(ValueError('bad\nkid')) == 'bad\\nkid'

    def test_truncates_an_oversized_value(self):
        escaped = escape_for_log('a' * (LOG_VALUE_MAX_CHARS + 100))

        assert escaped == 'a' * LOG_VALUE_MAX_CHARS + '...(truncated)'

    def test_truncates_when_escaping_expands_the_value(self):
        """Escaping grows a control character, so the input cap alone is not enough."""
        escaped = escape_for_log('\n' * LOG_VALUE_MAX_CHARS)

        assert escaped == '\\n' * (LOG_VALUE_MAX_CHARS // 2) + '...(truncated)'


class TestRedactForLog:
    """Keys survive; values are reduced to their type and size."""

    @pytest.mark.parametrize(
        ('value', 'expected'),
        [
            ('mysql -pX', '<str len=9>'),
            (b'abc', '<bytes len=3>'),
            (['a', 'b'], '<list items=2>'),
            ({'k': 'v'}, '<dict items=1>'),
            (None, None),
            (True, True),
            (300, 300),
            (object(), '<object>'),
        ],
    )
    def test_describe(self, value, expected):
        assert describe_for_log(value) == expected

    def test_a_mapping_keeps_its_keys(self):
        body = {'line': 'PGPASSWORD=x psql', 'env': {'A': 'x'}, 'timeout': 30}

        assert redact_for_log(body) == {
            'line': '<str len=17>',
            'env': '<dict items=1>',
            'timeout': 30,
        }


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
