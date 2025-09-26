"""Logging configuration for Alpacon MCP Server."""

import logging
import sys
import os
from pathlib import Path


class AlpaconLogger:
    """Centralized logging configuration for Alpacon MCP Server."""

    def __init__(self):
        self._loggers = {}
        self._setup_logging()

    def _setup_logging(self):
        """Setup logging configuration."""
        # Get log level from environment variable
        log_level = os.getenv("ALPACON_MCP_LOG_LEVEL", "INFO").upper()

        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Configure root logger
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.StreamHandler(sys.stderr),  # Console output
                logging.FileHandler(log_dir / "alpacon-mcp.log"),  # File output
            ]
        )

    def get_logger(self, name: str) -> logging.Logger:
        """Get logger for specific module.

        Args:
            name: Logger name (usually module name)

        Returns:
            Configured logger instance
        """
        if name not in self._loggers:
            logger = logging.getLogger(f"alpacon_mcp.{name}")

            # Add context information
            logger = logging.LoggerAdapter(logger, {
                'component': name,
                'pid': os.getpid()
            })

            self._loggers[name] = logger

        return self._loggers[name]


# Singleton instance
logger_manager = AlpaconLogger()


def get_logger(name: str) -> logging.Logger:
    """Get logger for module.

    Args:
        name: Module name

    Returns:
        Configured logger instance
    """
    return logger_manager.get_logger(name)


# Pre-configured loggers for common modules
server_logger = get_logger("server")
http_logger = get_logger("http_client")
token_logger = get_logger("token_manager")
tools_logger = get_logger("tools")