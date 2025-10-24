# main.py
import argparse
import sys
from pathlib import Path

from server import run
from utils.logger import get_logger
from utils.token_manager import TokenManager

import tools.command_tools
import tools.events_tools
import tools.iam_tools
import tools.metrics_tools
import tools.server_tools
import tools.system_info_tools
import tools.webftp_tools
import tools.websh_tools
import tools.workspace_tools

logger = get_logger("main")


def check_token_exists() -> bool:
    """Check if any token configuration exists."""
    tm = TokenManager()
    global_path = Path.home() / ".alpacon-mcp" / "token.json"
    local_path = Path("config") / "token.json"
    return global_path.exists() or local_path.exists()


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Alpacon MCP Server - AI-powered server management",
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
        """
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["setup", "test", "list", "add"],
        help="Command to execute"
    )
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to token configuration file (overrides default config discovery)"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local config (./config/token.json) instead of global (~/.alpacon-mcp/token.json)"
    )
    parser.add_argument(
        "--token-file",
        type=str,
        help="Custom path to token.json file (overrides --local and default locations)"
    )

    args = parser.parse_args()

    # Handle commands
    if args.command == "setup":
        from utils.setup_wizard import run_setup_wizard
        run_setup_wizard(force_local=args.local, custom_path=args.token_file)
        return

    if args.command == "test":
        from utils.setup_wizard import test_credentials
        test_credentials()
        return

    if args.command == "list":
        from utils.setup_wizard import list_workspaces
        list_workspaces()
        return

    if args.command == "add":
        from utils.setup_wizard import add_workspace
        add_workspace()
        return

    # No command provided - start MCP server
    logger.info("Starting Alpacon MCP Server")

    # Check if tokens are configured
    if not check_token_exists() and not args.config_file and not args.token_file:
        print("\n" + "="*60)
        print("⚠️  No API tokens configured")
        print("="*60)
        print("\nRunning setup wizard...\n")

        from utils.setup_wizard import run_setup_wizard
        run_setup_wizard(force_local=args.local, custom_path=args.token_file)

        print("\n✨ Setup complete!")
        print("Restart Claude Desktop and the MCP server will start automatically.")
        return

    logger.info(f"Configuration: config_file={args.config_file}")

    try:
        run("stdio", config_file=args.config_file)
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}", exc_info=True)
        raise


# Entry point to run the server
if __name__ == "__main__":
    logger.info("Alpacon MCP Server entry point called")
    main()
