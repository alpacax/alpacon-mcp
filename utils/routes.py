"""Types for registering Starlette routes on an MCPServer."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from starlette.requests import Request
from starlette.responses import Response

type RouteHandler = Callable[[Request], Awaitable[Response]]


class RouteRegistry(Protocol):
    """The one MCPServer method route registration needs; tests pass a stand-in."""

    def custom_route(
        self, path: str, methods: list[str]
    ) -> Callable[[RouteHandler], RouteHandler]: ...
