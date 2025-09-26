import os
from mcp.server.fastmcp import FastMCP
from utils.logger import get_logger

logger = get_logger("server")

# This is the shared MCP server instance
host = os.getenv("ALPACON_MCP_HOST", "127.0.0.1")  # Default to localhost for security
port = int(os.getenv("ALPACON_MCP_PORT", "8237"))  # Default port 8237 (MCAR - MCP Alpacon Remote)

logger.info(f"Initializing FastMCP server - host: {host}, port: {port}")

mcp = FastMCP(
    "alpacon",
    host=host,
    port=port,
)


def run(transport: str = "stdio", config_file: str = None):
    """Run MCP server with optional config file path.

    Args:
        transport: Transport type ('stdio' or 'sse')
        config_file: Path to token config file (optional)
    """
    logger.info(f"Starting MCP server with transport: {transport}")

    # Set config file path as environment variable if provided
    if config_file:
        logger.info(f"Using config file: {config_file}")
        os.environ["ALPACON_MCP_CONFIG_FILE"] = config_file
    else:
        logger.info("No config file specified, using default config discovery")

    try:
        logger.info("Starting FastMCP server...")
        mcp.run(transport=transport)
    except Exception as e:
        logger.error(f"FastMCP server failed to run: {e}", exc_info=True)
        raise
