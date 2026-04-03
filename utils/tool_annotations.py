"""Reusable MCP tool annotation presets.

Centralizes tool classification so every tool file imports a preset
instead of constructing ToolAnnotations inline.
"""

from mcp.types import ToolAnnotations

# Read-only tools: list_*, get_*, search_*
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False)

# Create/execute tools that add data but don't destroy existing resources
ADDITIVE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False
)

# Update tools that modify existing resources idempotently
IDEMPOTENT_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True
)

# Destructive tools: delete_*, shutdown_*, reboot_*, revoke_*
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
