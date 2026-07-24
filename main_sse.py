# main_sse.py
import argparse

from server import TOOLSETS_HELP, ToolsetError, run
from utils.logger import get_logger

logger = get_logger('main_sse')


def main():
    """Entry point for the alpacon-mcp-sse console script."""
    parser = argparse.ArgumentParser(description='Alpacon MCP Server (SSE mode)')
    parser.add_argument(
        '--config-file',
        type=str,
        help='Path to token configuration file (overrides default config discovery)',
    )
    parser.add_argument(
        '--toolsets',
        type=str,
        help=TOOLSETS_HELP,
    )

    args = parser.parse_args()
    try:
        run('sse', config_file=args.config_file, toolsets=args.toolsets)
    except ToolsetError as e:
        # A toolsets typo is user error, not a crash: one clean line, no traceback.
        # Scoped to ToolsetError so an unrelated ValueError during tool import is
        # not mislabeled as an --toolsets problem.
        logger.error(f'Invalid --toolsets: {e}')
        raise SystemExit(2)


if __name__ == '__main__':
    main()
