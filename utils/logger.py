"""Logging configuration for Alpacon MCP Server."""

import logging
import logging.handlers
import os
import queue
import sys
from pathlib import Path

LOG_FORMAT = (
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


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

        formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(log_dir / 'alpacon-mcp.log')
        file_handler.setFormatter(formatter)

        # The file sink flushes on every record, so a direct FileHandler would put
        # that disk write on the event loop shared by every in-flight tool call.
        log_queue: queue.SimpleQueue = queue.SimpleQueue()
        queue_handler = logging.handlers.QueueHandler(log_queue)
        # Prefix comes from the file handler; formatting here would repeat it.
        queue_handler.setFormatter(logging.Formatter('%(message)s'))
        self.listener = logging.handlers.QueueListener(log_queue, file_handler)
        self.listener.start()

        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            handlers=[stream_handler, queue_handler],
        )

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
