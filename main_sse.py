# main_sse.py
from server import run

import tools.auth_tools
import tools.command_tools
import tools.server_tools
import tools.websh_tools

# Entry point to run the server with SSE
if __name__ == "__main__":
    run("sse")
