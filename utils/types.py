"""Type aliases shared across modules; importing it has no side effects."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field

# Every value response.json() can produce; AlpaconHTTPClient methods return it.
type JsonValue = (
    dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
)

# Query params httpx accepts: each value a scalar or a sequence of them.
type QueryValue = str | int | float | bool | None
type QueryParam = QueryValue | Sequence[QueryValue]
type QueryParams = Mapping[str, QueryParam]

SERVER_ID_DESCRIPTION = (
    'Server UUID, never a server name; list_servers maps a name to its UUID.'
)

SERVER_IDS_DESCRIPTION = (
    'Server UUIDs, never server names; list_servers maps a name to its UUID.'
)

SESSION_ID_DESCRIPTION = (
    'Work Session UUID, as work_session_create or work_session_list returns it.'
)

WORK_SESSION_ID_DESCRIPTION = (
    'Work Session to link this call to for audit. The server requires one for MCP '
    'OAuth and browser-login callers; static API and service tokens may omit it. '
    "Omitted, it falls back to ALPACON_WORK_SESSION in this MCP server's "
    'environment; an explicit value wins.'
)

# Plain assignments, not `type`: pydantic publishes a TypeAliasType as a bare $ref.
ServerId = Annotated[str, Field(description=SERVER_ID_DESCRIPTION)]
OptionalServerId = Annotated[str | None, Field(description=SERVER_ID_DESCRIPTION)]
ServerIds = Annotated[list[str], Field(description=SERVER_IDS_DESCRIPTION)]
OptionalServerIds = Annotated[
    list[str] | None, Field(description=SERVER_IDS_DESCRIPTION)
]
SessionId = Annotated[str, Field(description=SESSION_ID_DESCRIPTION)]
WorkSessionId = Annotated[str | None, Field(description=WORK_SESSION_ID_DESCRIPTION)]

type RequestBody = Mapping[str, object]  # a JSON request body

type ApiMethod = Callable[..., Awaitable[JsonValue]]  # a bound AlpaconHTTPClient method

# What a tool returns, whatever its status; a TypedDict once mypy supports PEP 728
# extra_items, since the response helpers merge caller-chosen **kwargs into it.
ToolResponse = dict[str, Any]  # not object: callers index it without narrowing

# The {'status': 'error', ...} ToolResponse; the decorator can return it for any tool.
ToolErrorResponse = dict[str, Any]
type ToolResult[R] = R | ToolErrorResponse
