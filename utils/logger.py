"""Logging configuration for Alpacon MCP Server."""

import logging
import logging.handlers
import os
import queue
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LOG_FORMAT = (
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Caps a client-supplied value in a log line. Escaping expands a byte up to
# sixfold, so an unbounded value on an unauthenticated route inflates log volume.
LOG_VALUE_MAX_CHARS = 512

# Traceback lines keep their line breaks but never start a line at column 0,
# where a log reader looks for the timestamp that opens a record.
_TRACEBACK_INDENT = '    '

# These write what this server keeps out of its own lines: httpx each request
# URL with its query string at INFO, httpcore the response headers at DEBUG,
# and the MCP SDK every client message, tool arguments included, at DEBUG.
_LIBRARY_LEVEL_FLOORS = {
    'httpx': logging.WARNING,
    'httpcore': logging.WARNING,
    'httpx2': logging.WARNING,
    'httpcore2': logging.WARNING,
    'mcp': logging.INFO,
}

# Position of the request target in a uvicorn access record's arguments.
_ACCESS_LOG_PATH_ARG = 2


def _escape_controls(text: str) -> str:
    """Replace every non-printable character with its escape sequence."""
    if text.isprintable():
        return text
    return ''.join(c if c.isprintable() else repr(c)[1:-1] for c in text)


def escape_for_log(value: object, max_chars: int = LOG_VALUE_MAX_CHARS) -> str:
    """Escape control characters in a client-supplied value and bound its size.

    A raw newline would otherwise let a client forge a second log line.
    """
    text = value if isinstance(value, str) else str(value)
    escaped = _escape_controls(text[:max_chars])
    if len(text) > max_chars or len(escaped) > max_chars:
        return escaped[:max_chars] + '...(truncated)'
    return escaped


def describe_for_log(value: Any) -> Any:
    """Stand in for a value with its type and size.

    A number, a flag or None cannot carry text and passes through; a string,
    container, or anything else is recorded as a placeholder such as
    ``<str len=42>`` so no part of it reaches the log.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, bytes)):
        return f'<{type(value).__name__} len={len(value)}>'
    if isinstance(value, (list, tuple, set, frozenset)):
        return f'<list items={len(value)}>'
    if isinstance(value, Mapping):
        return f'<dict items={len(value)}>'
    return f'<{type(value).__name__}>'


def redact_for_log(value: Any) -> Any:
    """Keep a mapping's keys and describe each value; describe anything else.

    For payloads whose values the log has no business holding: request and
    response bodies, query parameters, upstream error bodies.
    """
    if isinstance(value, Mapping):
        return {key: describe_for_log(item) for key, item in value.items()}
    return describe_for_log(value)


class SingleLineFormatter(logging.Formatter):
    """Format a record so no value inside it can pass for another record.

    The message is escaped whole, and a traceback keeps its lines but indents
    each one under the record line.
    """

    def format(self, record: logging.LogRecord) -> str:
        record.message = _escape_controls(record.getMessage())
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)
        output = self.formatMessage(record)
        # Not read from record.exc_text: another handler may have cached an
        # unindented copy there.
        blocks = []
        if record.exc_info:
            blocks.append(self.formatException(record.exc_info))
        elif record.exc_text:
            blocks.append(record.exc_text)
        if record.stack_info:
            blocks.append(self.formatStack(record.stack_info))
        for block in blocks:
            output += '\n' + '\n'.join(
                _TRACEBACK_INDENT + _escape_controls(line) if line else line
                for line in block.split('\n')
            )
        return output


class AccessLogQueryFilter(logging.Filter):
    """Drop the query string from a uvicorn access record.

    The OAuth callback receives the authorization code and state in its query.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > _ACCESS_LOG_PATH_ARG:
            target = args[_ACCESS_LOG_PATH_ARG]
            if isinstance(target, str) and '?' in target:
                path = target.split('?', 1)[0]
                record.args = (
                    *args[:_ACCESS_LOG_PATH_ARG],
                    path,
                    *args[_ACCESS_LOG_PATH_ARG + 1 :],
                )
        return True


class AlpaconLogger:
    """Centralized logging configuration for Alpacon MCP Server."""

    def __init__(self):
        self._loggers: dict[str, logging.LoggerAdapter] = {}
        self.listener: logging.handlers.QueueListener | None = None
        self._setup_logging()

    def _setup_logging(self):
        """Setup logging configuration."""
        # Get log level from environment variable
        log_level = os.getenv('ALPACON_MCP_LOG_LEVEL', 'INFO').upper()

        # Create logs directory if it doesn't exist
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)

        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(
            SingleLineFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        )

        # Plain: the queue handler below has already escaped what reaches it.
        file_handler = logging.FileHandler(log_dir / 'alpacon-mcp.log')
        file_handler.setFormatter(
            logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        )

        # The file sink flushes on every record, so a direct FileHandler would put
        # that disk write on the event loop shared by every in-flight tool call.
        log_queue: queue.SimpleQueue = queue.SimpleQueue()
        queue_handler = logging.handlers.QueueHandler(log_queue)
        # Prefix comes from the file handler; formatting here would repeat it.
        queue_handler.setFormatter(SingleLineFormatter('%(message)s'))
        self.listener = logging.handlers.QueueListener(log_queue, file_handler)
        self.listener.start()

        root_level = getattr(logging, log_level, logging.INFO)
        logging.basicConfig(
            level=root_level,
            handlers=[stream_handler, queue_handler],
        )
        for name, floor in _LIBRARY_LEVEL_FLOORS.items():
            logging.getLogger(name).setLevel(max(floor, root_level))

        # On the logger, not a handler: uvicorn replaces the handlers when it
        # configures logging and leaves logger filters in place.
        access_logger = logging.getLogger('uvicorn.access')
        if not any(isinstance(f, AccessLogQueryFilter) for f in access_logger.filters):
            access_logger.addFilter(AccessLogQueryFilter())

    def stop_listener(self) -> None:
        """Stop the queue listener, draining pending records to the log file."""
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

    def get_logger(self, name: str) -> logging.LoggerAdapter:
        """Get logger for specific module.

        Args:
            name: Logger name (usually module name)

        Returns:
            Configured logger adapter instance
        """
        if name not in self._loggers:
            base_logger = logging.getLogger(f'alpacon_mcp.{name}')
            adapter = logging.LoggerAdapter(
                base_logger, {'component': name, 'pid': os.getpid()}
            )
            self._loggers[name] = adapter

        return self._loggers[name]


# Singleton instance
logger_manager = AlpaconLogger()


def get_logger(name: str) -> logging.LoggerAdapter:
    """Get logger for module.

    Args:
        name: Module name

    Returns:
        Configured logger adapter instance
    """
    return logger_manager.get_logger(name)


def stop_log_listener() -> None:
    """Stop the log queue listener on shutdown."""
    logger_manager.stop_listener()


# Pre-configured loggers for common modules
server_logger = get_logger('server')
http_logger = get_logger('http_client')
token_logger = get_logger('token_manager')
tools_logger = get_logger('tools')
