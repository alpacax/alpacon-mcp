# main.py
import argparse
from server import run

import tools.command_tools
import tools.server_tools
import tools.websh_tools
import tools.webftp_tools
import tools.system_tools
import tools.workspace_tools

def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Alpacon MCP Server")
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to token configuration file (overrides default config discovery)"
    )

    args = parser.parse_args()
    run("stdio", config_file=args.config_file)


# Entry point to run the server
if __name__ == "__main__":
    main()
