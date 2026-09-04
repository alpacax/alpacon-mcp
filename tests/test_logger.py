"""Tests for the logging setup in utils/logger.py.

The file sink must not run on the caller's thread: in remote mode every tool
call shares one event loop, and a FileHandler flushes to disk on every record.
"""

import logging
import logging.handlers
import sys
from unittest.mock import patch

import pytest

from utils.logger import AlpaconLogger


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """Build a logger manager in a scratch cwd, without touching the root logger."""
    monkeypatch.chdir(tmp_path)
    with patch('utils.logger.logging.basicConfig') as basic_config:
        instance = AlpaconLogger()
    try:
        yield instance, basic_config.call_args.kwargs['handlers']
    finally:
        instance.stop_listener()


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
        assert 'listener carried this' in log_file.read_text()

    def test_stop_listener_is_idempotent(self, manager):
        """Shutdown may run twice; the second call must not raise."""
        instance, _ = manager

        instance.stop_listener()
        instance.stop_listener()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
