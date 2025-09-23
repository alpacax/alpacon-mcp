# main.py
from server import run

import tools.auth_tools
import tools.command_tools
import tools.server_tools
import tools.websh_tools
import tools.webftp_tools
import tools.system_tools
import tools.workspace_tools

# Entry point to run the server
if __name__ == "__main__":
    run("stdio")
