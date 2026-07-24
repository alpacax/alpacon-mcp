# main_sse.py
import argparse

from server import TOOLSETS_HELP, run


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
    run('sse', config_file=args.config_file, toolsets=args.toolsets)


if __name__ == '__main__':
    main()
