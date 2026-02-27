# main_sse.py
import argparse
from server import run

import tools.command_tools  # noqa: F401 - side-effect: registers MCP tools
import tools.events_tools  # noqa: F401
import tools.iam_tools  # noqa: F401
import tools.metrics_tools  # noqa: F401
import tools.server_tools  # noqa: F401
import tools.system_info_tools  # noqa: F401
import tools.webftp_tools  # noqa: F401
import tools.websh_tools  # noqa: F401
import tools.workspace_tools  # noqa: F401


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
