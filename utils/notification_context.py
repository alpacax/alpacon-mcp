"""Carry server console links to the local signal without changing tool results."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

type ConsoleLinks = dict[int, tuple[object, str]]

_links: ContextVar[ConsoleLinks | None] = ContextVar('notification_links', default=None)


@contextmanager
def capture_console_links(enabled: bool) -> Iterator[ConsoleLinks | None]:
    links: ConsoleLinks | None = {} if enabled else None
    token = _links.set(links)
    try:
        yield links
    finally:
        _links.reset(token)


def remember_console_link[T](result: T, source: Mapping[str, object] | None) -> T:
    links = _links.get()
    if links is not None and source is not None:
        url = source.get('console_url')
        if isinstance(url, str) and url:
            # Hold the result too, so another result cannot reuse its id in this call.
            links[id(result)] = (result, url)
    return result
