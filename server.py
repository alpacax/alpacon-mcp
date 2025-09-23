from mcp.server.fastmcp import FastMCP

# This is the shared MCP server instance
mcp = FastMCP(
    "alpacon",
    host="0.0.0.0",
    port=8005,
)


def run(transport: str = "stdio"):
    mcp.run(transport=transport)
