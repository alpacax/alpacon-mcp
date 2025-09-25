# main_sse.py
import argparse
from server import run

import tools.command_tools
import tools.server_tools
import tools.websh_tools

# Entry point to run the server with SSE
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alpacon MCP Server (SSE mode)")
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to token configuration file (overrides default config discovery)"
    )

    args = parser.parse_args()
    run("sse", config_file=args.config_file)
