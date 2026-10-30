"""The MFA step-up Alpacon asks for with 401 ``auth_mfa_required``: the tool call
answers ``mfa_required`` with a link instead of a 403 re-login challenge."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

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
_RETRY_SENT = (
    'then check what the already_sent requests did (list_commands shows a submitted '
    'command) and retry only what did not run, never the whole call.'
)
_SENT_PREFIX = (
    'This call was refused for MFA after the already_sent requests changed state, '
    'so a whole retry would repeat them. '
)

# whole: nothing ran or the tool is read-only; sent: writes went through before the
# refusal ended the call; partial: the tool caught the refusal and returned.
Retry = Literal['whole', 'sent', 'partial']


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
    sent: list[str] = field(
        default_factory=list
    )  # 'METHOD /path' of each write that ran


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


def note_sent(request: str) -> None:
    """Note a state-changing request that succeeded in the tool call in flight."""
    holder = _holder.get()
    if holder is not None and request not in holder.sent:
        holder.sent.append(request)


def refuse_if_recorded() -> None:
    """Raise MfaStepUpRequired once the call in flight recorded a step-up, so the refused
    tool sends nothing more."""
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
    retry: Retry,
    already_sent: list[str],
    partial_result: JsonValue = None,
) -> dict[str, JsonValue]:
    """The ``mfa_required`` result. An UpstreamAuthError from the link fetch propagates; any
    other failure leaves ``mfa_url`` None. partial_result is kept only for a partial retry."""
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

    match retry:
        case 'whole':
            message = lead + _RETRY_WHOLE
        case 'sent':
            message = _SENT_PREFIX + lead + _RETRY_SENT
        case 'partial':
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
    if retry == 'sent':
        result['already_sent'] = list(already_sent)
    elif retry == 'partial':
        result['partial_result'] = partial_result
    return result
