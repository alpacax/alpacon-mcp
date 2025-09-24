import os
from mcp.server.fastmcp import FastMCP

# This is the shared MCP server instance
mcp = FastMCP(
    "alpacon",
    host="0.0.0.0",
    port=8005,
)


def run(transport: str = "stdio", config_file: str = None):
    """Run MCP server with optional config file path.

    Args:
        transport: Transport type ('stdio' or 'sse')
        config_file: Path to token config file (optional)
    """
    # Set config file path as environment variable if provided
    if config_file:
        os.environ["ALPACON_CONFIG_FILE"] = config_file

    mcp.run(transport=transport)
