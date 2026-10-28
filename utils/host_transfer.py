"""Wait for a WebFTP transfer the host runs; its URL exists before the file."""

from asyncio import sleep
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypedDict

from pydantic import TypeAdapter

from utils.common import (
    UnexpectedResponseShapeError,
    http_error_code,
    is_http_error,
    validate_response,
)
from utils.http_client import http_client
from utils.types import JsonValue
from utils.webftp_shapes import TRANSFER_STATE

#: Command statuses that mean it never ran and never will.
COMMAND_NEVER_RAN = frozenset({'denied', 'rejected', 'stuck'})

# The file_download and file_transfer token presets carry no command:read.
_SCOPE_MISSING = 'api_token_scope_missing'


class _CommandState(TypedDict, total=False):  # as /api/events/commands/{id}/ reports it
    status: str
    handled_at: str | None
    success: bool | None
    result: str | None


_COMMAND_STATE = TypeAdapter(_CommandState)


@dataclass(frozen=True)
class Refused:  # an http_client error envelope, for the caller to render
    response: JsonValue


@dataclass(frozen=True)
class Failed:
    reason: str | None  # None when the host gave no reason


@dataclass(frozen=True)
class TimedOut:
    pass


type Stalled = Refused | Failed | TimedOut


@dataclass(frozen=True)
class CommandHidden:  # the token may not read the command; only the transfer shows
    pass


class _Pending:
    pass


_PENDING = _Pending()


def deadline_after(seconds: float) -> float:
    return monotonic() + seconds


async def _poll[T](
    check: Callable[[], Awaitable[T | _Pending]],
    *,
    deadline: float,
    interval: float,
) -> T | TimedOut:
    """Run ``check`` until it settles; the last run starts at or after ``deadline``."""
    while True:
        final = monotonic() >= deadline
        outcome = await check()
        if not isinstance(outcome, _Pending):
            return outcome
        if final:
            return TimedOut()
        await sleep(max(min(interval, deadline - monotonic()), 0))


async def await_command_handled(
    command_id: str,
    *,
    region: str,
    workspace: str,
    token: str | None,
    deadline: float,
    interval: float,
) -> Stalled | CommandHidden | None:
    """Wait until the host has handled command_id; None once it succeeded."""

    async def check() -> Stalled | CommandHidden | _Pending | None:
        command = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f'/api/events/commands/{command_id}/',
            token=token,
        )
        if is_http_error(command):
            if isinstance(command, dict) and http_error_code(command) == _SCOPE_MISSING:
                return CommandHidden()
            return Refused(command)
        try:
            state = validate_response(_COMMAND_STATE, command)
        except UnexpectedResponseShapeError as e:
            return Failed(str(e))
        if (status := state.get('status')) in COMMAND_NEVER_RAN:
            return Failed(f'the transfer command ended as {status}')
        if state.get('handled_at') is None:
            return _PENDING
        return Failed(state.get('result')) if state.get('success') is False else None

    return await _poll(check, deadline=deadline, interval=interval)


async def await_transfer_success(
    status_endpoint: str,
    *,
    region: str,
    workspace: str,
    token: str | None,
    deadline: float,
    interval: float,
) -> Stalled | None:
    """Wait until the server reports the transfer succeeded; None once it has."""

    async def check() -> Stalled | _Pending | None:
        status = await http_client.get(
            region=region, workspace=workspace, endpoint=status_endpoint, token=token
        )
        if is_http_error(status):
            return Refused(status)
        try:
            transfer = validate_response(TRANSFER_STATE, status)
        except UnexpectedResponseShapeError as e:
            return Failed(str(e))
        match transfer.get('success'):
            case True:
                return None
            case False:
                return Failed(transfer.get('message'))
        return _PENDING

    return await _poll(check, deadline=deadline, interval=interval)
