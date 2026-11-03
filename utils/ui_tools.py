"""Keep MCP App tools, the ones carrying ``_meta.ui``, out of tools/list for a client
that cannot render them."""

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

from utils.client_surfaces import client_surfaces
from utils.types import JsonValue


def _is_ui_bound(tool: JsonValue) -> bool:
    meta = tool.get('_meta') if isinstance(tool, dict) else None
    return isinstance(meta, dict) and 'ui' in meta


async def hide_ui_tools(
    ctx: ServerRequestContext[object, object], call_next: CallNext
) -> HandlerResult:
    """Drop UI tools from tools/list for a client that declared capabilities without
    MCP Apps; an unknown client sees them."""
    result = await call_next(ctx)
    if ctx.method != 'tools/list' or not isinstance(result, dict):
        return result  # call_next hands back the wire dict the SDK already serialized
    if client_surfaces(ctx.session.client_capabilities).apps != 'absent':
        return result
    tools = result.get('tools')
    if not isinstance(tools, list):
        return result
    return {**result, 'tools': [t for t in tools if not _is_ui_bound(t)]}
