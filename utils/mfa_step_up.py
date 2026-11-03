"""The MFA step-up Alpacon asks for with 401 ``auth_mfa_required``: the tool call
answers ``mfa_required`` with a link instead of a 403 re-login challenge."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from utils.error_handler import MfaStepUpRequired
from utils.mfa_link import (
    MFAAlreadyDone,
    MFALink,
    MFALinkOutcome,
    MFALinkRaised,
    fetch_mfa_link,
)
from utils.types import JsonValue

if TYPE_CHECKING:  # http_client imports this module
    from utils.http_client import AlpaconHTTPClient

_NEEDS_MFA = 'Alpacon needs a fresh MFA for this action'
_WAIT = 'and wait until they finish MFA in the browser, '
_LEAD_LINK = f'{_NEEDS_MFA}. Show the mfa_url link to the person {_WAIT}'
_LEAD_SHOW_MFA = (
    f'{_NEEDS_MFA}. Call show_mfa with the same workspace and region so the person '
    f'gets an Authenticate button, or show them the mfa_url link if no panel appears, '
    f'{_WAIT}'
)
_LEAD_ALREADY_DONE = 'Alpacon reports MFA already completed; '
_LEAD_NO_LINK = (
    f'{_NEEDS_MFA}, but no link could be fetched. MFA done in the web console does '
    'not count for this connection, so wait for the service to recover, '
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


def lead(outcome: MFALinkOutcome, *, names_show_mfa: bool) -> str:
    """The message's opening for a link fetch outcome; it ends ready for a retry clause."""
    match outcome:
        case MFALink():
            return _LEAD_SHOW_MFA if names_show_mfa else _LEAD_LINK
        case MFAAlreadyDone():
            return _LEAD_ALREADY_DONE
        case _:
            return _LEAD_NO_LINK


# whole: nothing ran or the tool is read-only; sent: writes went through before the
# refusal ended the call; partial: the tool caught the refusal and returned.
Retry = Literal['whole', 'sent', 'partial']


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
    apps_declared: bool,
    partial_result: JsonValue = None,
) -> dict[str, JsonValue]:
    """The ``mfa_required`` result. An UpstreamAuthError from the link fetch propagates; any
    other failure leaves ``mfa_url`` None. partial_result is kept only for a partial retry."""
    try:
        outcome = await fetch_mfa_link(
            client, region=region, workspace=workspace, token=token
        )
    except MfaStepUpRequired:  # the link endpoint itself wants MFA: no link to give
        outcome = MFALinkRaised()
    mfa_url = outcome.url if isinstance(outcome, MFALink) else None
    opening = lead(outcome, names_show_mfa=apps_declared)

    match retry:
        case 'whole':
            message = opening + _RETRY_WHOLE
        case 'sent':
            message = _SENT_PREFIX + opening + _RETRY_SENT
        case 'partial':
            message = _PARTIAL_PREFIX + opening + _RETRY_PARTIAL

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
