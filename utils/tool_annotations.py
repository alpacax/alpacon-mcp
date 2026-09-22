"""Reusable MCP tool annotation presets.

Centralizes common tool classifications so tool files can import shared
presets instead of duplicating the same ToolAnnotations values inline.
Prefer these presets for reusable patterns, and add new presets here when
a classification is shared by multiple tools.
"""

from mcp.types import ToolAnnotations

# Read-only tools: list_*, get_*, search_*
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)

# Create/execute tools that add data but don't destroy existing resources
ADDITIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False
)

# Update tools that modify existing resources idempotently
IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True
)

# Destructive tools: delete_*, shutdown_*, reboot_*, revoke_*
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)
