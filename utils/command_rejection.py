"""Guidance for a command a gate refused before it ran (`rejection_cause`, #242)."""

from collections.abc import Mapping, MutableMapping

from utils.common import REFUSAL_GATE_HINT
from utils.types import JsonValue

_SAME_ANSWER = 'Resubmitting the same command gets the same answer.'

#: Keyed by the server's closed set of causes. Each says whom to ask or where to
#: wait: a gate refused before execution, unlike an `error_phase`.
_REJECTION_CAUSE_HINT: dict[str, str] = {
    'command_acl_denied': f'{REFUSAL_GATE_HINT["command_acl"]} {_SAME_ANSWER}',
    'command_acl_unavailable': (
        'The command pre-approval ledger gave no verdict, so the command was '
        'refused rather than run unchecked. Tell a workspace admin, and do not '
        'resubmit until they say the ledger is back.'
    ),
    'risk_denied': f'{REFUSAL_GATE_HINT["risk"]} {_SAME_ANSWER}',
    'risk_unavailable': (
        'The risk assessor was unavailable, so the command was refused rather '
        'than run unjudged. Tell a workspace admin, and do not resubmit until '
        'they say the assessor is back.'
    ),
    'approval_policy_denied': (
        "The workspace's approval policy refused this command outright, or nobody "
        'but the requester could decide it. Ask a workspace admin about the '
        f'policy, or another member with approval rights. {_SAME_ANSWER}'
    ),
    'approval_rejected': (
        'A human approver rejected this command. Do not resubmit it; ask the '
        'approver why, out-of-band.'
    ),
    'approval_expired': (
        'The approval request expired with no decision. Do not resubmit on your '
        'own; ask the user whether an approver can decide a new request.'
    ),
    'approval_cancelled': (
        'The requester cancelled the approval request. Do not resubmit unless '
        'the user asks for the command again.'
    ),
    'work_session_terminated': (
        'The Work Session ended while the command was held, so it never ran. Do '
        'not resubmit it into that session; ask the user whether the work should '
        'go on in a new session a human approves.'
    ),
    'account_bound_to_other_person': (
        'The account this command would run as was linked to another person '
        'before it was delivered. Ask a workspace admin which account you may '
        f'use. {_SAME_ANSWER}'
    ),
    'unsigned_file': (
        'The file command reached the agent without a signature, so the agent '
        f'refused it. Report it to a workspace admin. {_SAME_ANSWER}'
    ),
    'signature_invalid': (
        "The agent could not verify the command's signature, so it refused to "
        'run it. Report it to a workspace admin: the signing key or the command '
        f'may have been altered. {_SAME_ANSWER}'
    ),
    'use_file_execution': (
        'The line carries a script body the approval policy blocks. Run the '
        'script with execute_file instead, as next_action says.'
    ),
}

_CAUSE_NOT_RECORDED_HINT = (
    'The server did not record why this command was rejected (an older server '
    'or an older row). Do not resubmit it; ask a workspace admin, or check '
    'list_approval_requests for its approval.'
)

_UNKNOWN_CAUSE_HINT = (
    'A gate refused this command before it ran. Tell the user and ask a '
    f'workspace admin. {_SAME_ANSWER}'
)


def rejection_hint(record: Mapping[str, JsonValue]) -> str | None:
    """Guidance for a rejected command row: by cause, then by gate, else generic.
    None for a row that was not rejected."""
    cause = record.get('rejection_cause')
    if not isinstance(cause, str) or not cause:
        return _CAUSE_NOT_RECORDED_HINT if record.get('status') == 'rejected' else None
    if hint := _REJECTION_CAUSE_HINT.get(cause):
        return hint
    gate = record.get('rejection_gate')
    if isinstance(gate, str) and (gate_hint := REFUSAL_GATE_HINT.get(gate)):
        return f'{gate_hint} {_SAME_ANSWER}'
    return _UNKNOWN_CAUSE_HINT


def attach_rejection(
    target: MutableMapping[str, JsonValue],
    source: Mapping[str, JsonValue] | None = None,
) -> str | None:
    """Copy `source`'s rejection_cause and rejection_gate onto `target` with a
    rejection_hint, and return the hint; `source` defaults to `target`."""
    row = target if source is None else source
    hint = rejection_hint(row)
    if hint is not None:
        target['rejection_cause'] = row.get('rejection_cause')
        target['rejection_gate'] = row.get('rejection_gate')
        target['rejection_hint'] = hint
    return hint
