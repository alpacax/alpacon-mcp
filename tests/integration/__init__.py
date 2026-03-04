"""Integration tests for Alpacon MCP server.

These tests use httpx.MockTransport to inject mock HTTP responses at the
transport layer, allowing the full request path to execute:
decorator chain -> token validation -> HTTP client retry/cache -> httpx -> response parsing.
"""
