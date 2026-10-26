"""Type aliases shared across modules; importing it has no side effects."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

# Every value response.json() can produce; AlpaconHTTPClient methods return it.
type JsonValue = (
    dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
)

# Query params httpx accepts: each value a scalar or a sequence of them.
type QueryValue = str | int | float | bool | None
type QueryParam = QueryValue | Sequence[QueryValue]
type QueryParams = Mapping[str, QueryParam]

type RequestBody = Mapping[str, object]  # a JSON request body

type ApiMethod = Callable[..., Awaitable[JsonValue]]  # a bound AlpaconHTTPClient method

# What a tool returns, whatever its status; a TypedDict once mypy supports PEP 728
# extra_items, since the response helpers merge caller-chosen **kwargs into it.
ToolResponse = dict[str, Any]  # not object: callers index it without narrowing

# The {'status': 'error', ...} ToolResponse; the decorator can return it for any tool.
ToolErrorResponse = dict[str, Any]
type ToolResult[R] = R | ToolErrorResponse
