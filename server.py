import os
from mcp.server.fastmcp import FastMCP

# This is the shared MCP server instance
mcp = FastMCP(
    "alpacon",
    host=os.getenv("ALPACON_MCP_HOST", "127.0.0.1"),  # Default to localhost for security
    port=int(os.getenv("ALPACON_MCP_PORT", "8237")),  # Default port 8237 (MCAR - MCP Alpacon Remote)
)


def run(transport: str = "stdio", config_file: str = None):
    """Run MCP server with optional config file path.

    Args:
        transport: Transport type ('stdio' or 'sse')
        config_file: Path to token config file (optional)
    """
    # Set config file path as environment variable if provided
    if config_file:
        os.environ["ALPACON_MCP_CONFIG_FILE"] = config_file

    mcp.run(transport=transport)
