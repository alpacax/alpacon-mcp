# main.py
import argparse
import os
import sys
from pathlib import Path

from server import TOOLSETS_HELP, TRANSPORT_STDIO, ToolsetError, run
from utils.error_handler import VALID_REGIONS
from utils.logger import get_logger

logger = get_logger('main')


def _is_workspace_token_variable(name: str) -> bool:
    """Whether name has the ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN shape TokenManager reads.

    TokenManager builds the name from upper-cased region and workspace, so a name
    with any lowercase letter is never read.
    """
    prefix, suffix = 'ALPACON_MCP_', '_TOKEN'
    if name != name.upper():
        return False
    if not (name.startswith(prefix) and name.endswith(suffix)):
        return False
    region, _, workspace = name[len(prefix) : -len(suffix)].partition('_')
    return region.lower() in VALID_REGIONS and bool(workspace)


def check_token_exists() -> bool:
    """Check if any token source the server reads is configured.

    Mirrors TokenManager: ALPACON_MCP_CONFIG_FILE, any
    ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN variable (read before any file),
    and the global and local token files.
    """
    if os.getenv('ALPACON_MCP_CONFIG_FILE'):
        return True
    if any(
        _is_workspace_token_variable(name) and value
        for name, value in os.environ.items()
    ):
        return True
    global_path = Path.home() / '.alpacon-mcp' / 'token.json'
    local_path = Path('config') / 'token.json'
    return global_path.exists() or local_path.exists()


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description='Alpacon MCP Server - AI-powered server management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (no command)      Start MCP server (runs setup if not configured)
  setup             Run interactive configuration wizard
  test              Test API connection with configured credentials
  list              List all configured workspaces
  add               Add a new workspace configuration

Examples:
  uvx alpacon-mcp                    # Start server (auto-setup if needed)
  uvx alpacon-mcp setup              # Configure credentials
  uvx alpacon-mcp setup --local      # Configure for current project only
  uvx alpacon-mcp test               # Test connection
  uvx alpacon-mcp list               # Show configured workspaces
  uvx alpacon-mcp add                # Add another workspace
  uvx alpacon-mcp --toolsets servers # Register only the listed toolsets
        """,
    )
    parser.add_argument(
        'command',
        nargs='?',
        choices=['setup', 'test', 'list', 'add'],
        help='Command to execute',
    )
    parser.add_argument(
        '--config-file',
        type=str,
        help='Path to token configuration file (overrides default config discovery)',
    )
    parser.add_argument(
        '--local',
        action='store_true',
        help='Use local config (./config/token.json) instead of global (~/.alpacon-mcp/token.json)',
    )
    parser.add_argument(
        '--token-file',
        type=str,
        help='Custom path to token.json file (overrides --local and default locations)',
    )
    parser.add_argument(
        '--toolsets',
        type=str,
        help=TOOLSETS_HELP,
    )

    args = parser.parse_args()

    # Handle commands. Each utils.setup_wizard import below stays local: rarely-used CLI paths shouldn't cost the common case.
    if args.command == 'setup':
        from utils.setup_wizard import run_setup_wizard

        run_setup_wizard(force_local=args.local, custom_path=args.token_file)
        return

    if args.command == 'test':
        from utils.setup_wizard import test_credentials

        test_credentials()
        return

    if args.command == 'list':
        from utils.setup_wizard import list_workspaces

        list_workspaces()
        return

    if args.command == 'add':
        from utils.setup_wizard import add_workspace

        add_workspace()
        return

    # No command provided - start MCP server
    logger.info('Starting Alpacon MCP Server')

    # Check if tokens are configured
    if not check_token_exists() and not args.config_file and not args.token_file:
        if not sys.stdin.isatty():
            # An MCP client launched us: stdout is the JSON-RPC channel and stdin
            # its pipe, so the wizard would corrupt the handshake and read
            # protocol frames as answers. Say why on stderr and stop instead.
            logger.error(
                'No API tokens configured. Run `alpacon-mcp setup` in a terminal, '
                'or set ALPACON_MCP_<REGION>_<WORKSPACE>_TOKEN.'
            )
            raise SystemExit(1)

        print('\n' + '=' * 60)
        print('⚠️  No API tokens configured')
        print('=' * 60)
        print('\nRunning setup wizard...\n')

        from utils.setup_wizard import run_setup_wizard

        run_setup_wizard(force_local=args.local, custom_path=args.token_file)

        print('\n✨ Setup complete!')
        print('Restart Claude Desktop and the MCP server will start automatically.')
        return

    logger.info('Configuration: config_file=%s', args.config_file)

    try:
        run(TRANSPORT_STDIO, config_file=args.config_file, toolsets=args.toolsets)
    except ToolsetError as e:
        # A toolsets typo is user error, not a crash: one clean line, no traceback.
        # Scoped to ToolsetError so an unrelated ValueError during tool import
        # (e.g. a bad numeric env var) still gets the full-traceback path below.
        logger.error('Invalid --toolsets: %s', e)
        raise SystemExit(2)
    except Exception as e:
        logger.exception('Failed to start MCP server: %s', e)
        raise


# Entry point to run the server
if __name__ == '__main__':
    logger.info('Alpacon MCP Server entry point called')
    main()
