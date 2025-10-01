# main.py
import argparse
from server import run
from utils.logger import get_logger

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

def main():
    """Main entry point for the CLI."""
    logger.info("Starting Alpacon MCP Server")

    parser = argparse.ArgumentParser(description="Alpacon MCP Server")
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to token configuration file (overrides default config discovery)"
    )

    args = parser.parse_args()
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
