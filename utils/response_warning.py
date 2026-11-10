"""Carry response warnings to the outermost tool result without changing API data."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC
from email.utils import parsedate_to_datetime
from functools import wraps
from typing import cast

import httpx
from mcp.types import CallToolResult, TextContent

from utils.logger import get_logger
from utils.types import ToolResult

logger = get_logger('http_client')
_MONTHS = (
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
)
_warning: ContextVar[list[str] | None] = ContextVar('response_warning', default=None)


def record(headers: httpx.Headers) -> None:
    warnings = {part.strip() for part in headers.get('Alpacon-Warning', '').split(',')}
    if 'work_session_required_soon' not in warnings:
        return
    try:
        sunset = parsedate_to_datetime(headers.get('Sunset', ''))
        if sunset.tzinfo is None:
            sunset = sunset.replace(tzinfo=UTC)
        sunset = sunset.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        date = 'the date announced by the server'
    else:
        date = f'{_MONTHS[sunset.month - 1]} {sunset.day}, {sunset.year}'
    message = (
        f'Starting {date}, this personal API token will need a Work Session '
        'for this action. Open a Work Session, or use a service token for automation.'
    )
    holder = _warning.get()
    if holder is None or not holder:
        logger.warning('%s', message)
    if holder is not None and not holder:
        holder.append(message)


def with_response_warning[**P, R](
    func: Callable[P, Awaitable[ToolResult[R]]],
) -> Callable[P, Awaitable[ToolResult[R]]]:
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult[R]:
        if _warning.get() is not None:
            return await func(*args, **kwargs)
        holder: list[str] = []
        token = _warning.set(holder)
        try:
            result = await func(*args, **kwargs)
        finally:
            _warning.reset(token)
        if not holder:
            return result
        message = holder[0]
        if isinstance(result, dict):
            return {**result, 'warning': message}
        if isinstance(result, CallToolResult):
            return cast(
                ToolResult[R],
                result.model_copy(
                    update={
                        'content': [
                            *result.content,
                            TextContent(type='text', text=f'Warning: {message}'),
                        ],
                        'structured_content': (
                            {**result.structured_content, 'warning': message}
                            if isinstance(result.structured_content, dict)
                            else result.structured_content
                        ),
                    }
                ),
            )
        return result

    return wrapper
