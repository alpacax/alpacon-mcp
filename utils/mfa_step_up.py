"""The MFA step-up Alpacon asks for with 401 ``auth_mfa_required``: the tool call
answers ``mfa_required`` with a link instead of a 403 re-login challenge."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ToolError

from utils.error_handler import UpstreamAuthError
from utils.logger import get_logger
from utils.types import JsonValue

if TYPE_CHECKING:  # http_client imports this module
    from utils.http_client import AlpaconHTTPClient

logger = get_logger('mfa_step_up')

_LINK_ENDPOINT = '/api/auth0/mfa/'

_LEAD_LINK = (
    'Alpacon needs a fresh MFA for this action. Show the mfa_url link to the person '
    'and wait until they finish MFA in the browser, '
)
_LEAD_ALREADY_DONE = 'Alpacon reports MFA already completed; '
_LEAD_NO_LINK = (
    'Alpacon needs a fresh MFA for this action and no link could be fetched. Ask a '
    'person to complete MFA in the Alpacon web console, '
)
_RETRY_WHOLE = 'then retry the same call once with the same arguments.'
_RETRY_PARTIAL = 'then retry only the refused parts, never the whole call.'
_PARTIAL_PREFIX = (
    'Part of this call was refused for MFA and partial_result shows what already ran. '
)


def _execute_file_note(arguments: Mapping[str, object]) -> str | None:
    if arguments.get('write_file') is not True:
        return None
    return (
        'then retry with read_from_server=true and without write_file and content: '
        'write_file was true, so the file may already be on the host, and a repeat '
        'write without overwrite fails with file_write_failed.'
    )


# Per tool: replaces the whole-call retry when a plain retry would repeat a side effect.
_RETRY_NOTES: dict[str, Callable[[Mapping[str, object]], str | None]] = {
    'execute_file': _execute_file_note,
}


class MfaStepUpRequired(ToolError):  # noqa: N818  # a signal, named for the state
    """Alpacon refused with ``auth_mfa_required``. Not an UpstreamAuthError, which comes
    with a request_signal entry and so a re-auth challenge in place of the result."""

    def __init__(self, source: str = ''):
        self.source = source
        super().__init__('MFA step-up required')


@dataclass
class _Holder:
    required: bool = False
    source: str = ''


# A mutable holder, never rebound below the call that installed it: child tasks of a
# fan-out copy the context, so only mutation reaches the outer call.
_holder: ContextVar[_Holder | None] = ContextVar('mfa_step_up_holder', default=None)


@contextmanager
def tool_call() -> Iterator[_Holder | None]:
    """Install the holder for the outermost tool call; a nested call, finding one
    already installed, gets None."""
    if _holder.get() is not None:
        yield None
        return
    holder = _Holder()
    token = _holder.set(holder)
    try:
        yield holder
    finally:
        _holder.reset(token)


def record(source: str) -> None:
    """Note the step-up for the tool call in flight; the first source wins."""
    holder = _holder.get()
    if holder is not None and not holder.required:
        holder.required, holder.source = True, source


def refuse_if_recorded() -> None:
    """Raise MfaStepUpRequired once the call in flight recorded a step-up, so a refused
    call sends nothing more."""
    holder = _holder.get()
    if holder is not None and holder.required:
        raise MfaStepUpRequired(holder.source)


async def step_up_result(
    client: 'AlpaconHTTPClient',
    *,
    workspace: str,
    region: str,
    token: str | None,
    source: str,
    tool_name: str,
    arguments: Mapping[str, object],
    retry_whole: bool,
    partial_result: JsonValue = None,
) -> dict[str, JsonValue]:
    """The ``mfa_required`` result. An UpstreamAuthError from the link fetch propagates; any
    other failure leaves ``mfa_url`` None. Without retry_whole the tool's result is partial_result."""
    mfa_url: str | None = None
    lead = _LEAD_NO_LINK
    try:
        body = await client.get(
            region,
            workspace,
            _LINK_ENDPOINT,
            token=token,
            # TODO(#427 step 3): location=mcp once Alpacon accepts it
            params={'location': 'cli', 'workspace': workspace},
        )
    except UpstreamAuthError:
        raise
    except Exception as exc:
        logger.warning('MFA link fetch for %s.%s raised %s', workspace, region, exc)
    else:
        url = body.get('mfa_url') if isinstance(body, dict) else None
        if isinstance(url, str) and url:
            mfa_url, lead = url, _LEAD_LINK
        elif isinstance(body, dict) and set(body) == {'detail'}:
            # Alpacon's answer when the token's MFA is still fresh; detail may be translated
            lead = _LEAD_ALREADY_DONE
        else:
            logger.warning(
                'MFA link fetch for %s.%s returned no link (keys: %s)',
                workspace,
                region,
                sorted(body) if isinstance(body, dict) else type(body).__name__,
            )

    if retry_whole:
        note_for = _RETRY_NOTES.get(tool_name)
        note = note_for(arguments) if note_for else None
        message = lead + (note or _RETRY_WHOLE)
    else:
        message = _PARTIAL_PREFIX + lead + _RETRY_PARTIAL

    result: dict[str, JsonValue] = {
        'status': 'mfa_required',
        'mfa_url': mfa_url,
        'message': message,
        'workspace': workspace,
        'region': region,
    }
    if source:
        result['source'] = source
    if not retry_whole:
        result['partial_result'] = partial_result
    return result
