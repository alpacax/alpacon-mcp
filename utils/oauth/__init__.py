"""OAuth 2.0 proxy endpoints for Auth0.

MCP clients such as claude.ai run the authorization code flow against this
server, which proxies to Auth0. The routes go through FastMCP's custom_route,
which bypasses MCP authentication, as OAuth endpoints must.
"""

from utils.oauth._routes import register_oauth_routes

__all__ = ['register_oauth_routes']
