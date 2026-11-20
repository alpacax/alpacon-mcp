"""Say when a Work Session result names only part of its scope (#480).

Alpacon names only the servers and clusters the reader reaches and counts the
rest in a sibling integer; the field paths follow the Alpacon API's Work
Session, approval request and session analysis responses. The body passes
through untouched; this module only reads those counts and writes a
`hidden_targets_note`, so an agent does not take a partial list for the whole
scope. It decides nothing: a server that sends no count gets no note.

The notes state Alpacon's own rule, not one of this module: a reader who manages
the session (its assignee, its token's owner, its Application's direct
maintainer, a superuser) is named every target, and so is one who may decide its
pending approval. Every write needs the first, so a count above 0 also tells the
reader the session is not theirs to run or change.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from utils.types import ToolResponse

_NO_TOOL_SHOWS = 'No tool shows what is counted.'

_MANAGERS = (
    'Alpacon names every server and cluster to its assignee, the owner of its '
    'token, the direct maintainer of its Application and a superuser'
)

_DECIDERS = ', and to anyone who may decide its pending approval'

_NOT_A_MANAGER = (
    'Alpacon counts servers and clusters only for a reader who does not manage the '
    'session, and it lets only a manager run commands under it, change, extend or '
    'close it.'
)


class _Counts(NamedTuple):
    """One object's counts, each 0 when the server sent none."""

    servers: int = 0
    clusters: int = 0
    old: int = 0
    new: int = 0
    changes: int = 0
    flagged: int = 0
    overlaps: tuple[tuple[str, int], ...] = ()

    def __bool__(self) -> bool:
        return any(self)


def _get(obj: object, *path: str) -> object:
    for key in path:
        if not isinstance(obj, Mapping):
            return None
        obj = obj.get(key)
    return obj


def _count(value: object) -> int:
    """A count the server sent; anything but a positive int (bool included) is 0."""
    return value if type(value) is int and value > 0 else 0


def _more(count: int, noun: str) -> str:
    return f'{count} more {noun}' if count == 1 else f'{count} more {noun}s'


def _verb(count: int) -> str:
    return 'is' if count == 1 else 'are'


def _session_counts(session: object) -> _Counts:
    return _Counts(
        servers=_count(_get(session, 'servers_hidden')),
        clusters=_count(_get(session, 'clusters_hidden')),
        old=_count(_get(session, 'adjustments', 'servers', 'old_hidden')),
        new=_count(_get(session, 'adjustments', 'servers', 'new_hidden')),
        changes=_count(
            _get(session, 'pending_modification_request', 'changes', 'servers_hidden')
        ),
        flagged=_count(_get(session, 'account_flag', 'servers_hidden')),
    )


def _read_approval(approval: object) -> tuple[_Counts, bool]:
    """The request's counts, and whether they come from a nested session."""
    overlaps = _get(approval, 'overlapping_sessions')
    shared = tuple(
        (str(row.get('id')), hidden)
        for row in (overlaps if isinstance(overlaps, list) else ())
        if isinstance(row, Mapping) and (hidden := _count(row.get('servers_hidden')))
    )
    nested = _get(approval, 'work_session')
    if isinstance(nested, Mapping):
        # A work_session request renders metadata.adjustments from the same diff,
        # with the same reach, as the nested session: count it once.
        return _session_counts(nested)._replace(overlaps=shared), True
    return _Counts(
        old=_count(_get(approval, 'metadata', 'adjustments', 'servers', 'old_hidden')),
        new=_count(_get(approval, 'metadata', 'adjustments', 'servers', 'new_hidden')),
        changes=_count(_get(approval, 'metadata', 'changes', 'servers_hidden')),
        overlaps=shared,
    ), False


def _approval_counts(approval: object) -> _Counts:
    return _read_approval(approval)[0]


def _analysis_counts(analysis: object) -> _Counts:
    return _Counts(
        servers=_count(_get(analysis, 'work_session_detail', 'servers_hidden'))
    )


def _diff_sentence(counts: _Counts, path: str) -> str | None:
    parts = []
    if counts.old:
        parts.append(f'{counts.old} more before (`old_hidden`)')
    if counts.new:
        parts.append(f'{counts.new} more after (`new_hidden`)')
    if not parts:
        return None
    verb = _verb(counts.old + counts.new) if len(parts) == 1 else 'are'
    return (
        f"The approver's diff (`{path}`) names only servers you can reach: "
        f'{" and ".join(parts)} {verb} counted without names, so `old` and `new` '
        'do not show every server added or removed.'
    )


def _target_sentences(
    counts: _Counts, prefix: str, scope: str, whole: str
) -> list[str]:
    """The servers and cluster openings; ``prefix`` is where the session sits."""
    sentences = []
    if counts.servers:
        sentences.append(
            f'`{prefix}servers` names only the servers you can reach: '
            f'{_more(counts.servers, "server")} in {scope} {_verb(counts.servers)} '
            f'counted in `{prefix}servers_hidden`, with no name or id. Do not '
            f'report `{prefix}servers` as {whole}.'
        )
    if counts.clusters:
        sentences.append(
            f'`{prefix}clusters` names only the clusters you can reach: '
            f'{_more(counts.clusters, "cluster")} in {scope} '
            f'{_verb(counts.clusters)} counted in `{prefix}clusters_hidden`, with no '
            'name or id.'
        )
    return sentences


def _session_sentences(counts: _Counts, prefix: str) -> list[str]:
    sentences = _target_sentences(
        counts, prefix, "this session's scope", "the session's whole scope"
    )
    if diff := _diff_sentence(counts, f'{prefix}adjustments.servers'):
        sentences.append(diff)
    if counts.changes:
        sentences.append(
            f'The pending modification (`{prefix}pending_modification_request.'
            f'changes`) covers {_more(counts.changes, "server")} you cannot see, '
            'counted in its `servers_hidden`.'
        )
    if counts.flagged:
        sentences.append(
            f'The account warning (`{prefix}account_flag`) also holds on '
            f'{_more(counts.flagged, "server")} you cannot see, counted in its '
            '`servers_hidden`.'
        )
    return sentences


def _waits_on_its_approval(session: object) -> bool:
    return _get(session, 'status') == 'pending' and bool(
        _get(session, 'approval_request_id')
    )


def session_note(session: object) -> str | None:
    """The note for one Work Session body; None when it names its whole scope."""
    counts = _session_counts(session)
    if not counts:
        return None
    deciders = _DECIDERS if _waits_on_its_approval(session) else ''
    return ' '.join(
        [
            *_session_sentences(counts, ''),
            _NOT_A_MANAGER,
            _NO_TOOL_SHOWS,
            f'{_MANAGERS}{deciders}.',
        ]
    )


def approval_note(approval: object) -> str | None:
    """The note for one approval request body; None when nothing is counted."""
    counts, nested = _read_approval(approval)
    if not counts:
        return None
    if nested:
        sentences = _session_sentences(counts, 'work_session.')
    else:
        sentences = []
        if diff := _diff_sentence(counts, 'metadata.adjustments.servers'):
            sentences.append(diff)
        if counts.changes:
            sentences.append(
                'The requested modification (`metadata.changes`) covers '
                f'{_more(counts.changes, "server")} you cannot see, counted in its '
                '`servers_hidden`.'
            )
    for session_id, hidden in counts.overlaps:
        sentences.append(
            f'`overlapping_sessions` names only shared servers you can reach: '
            f'session {session_id} shares {_more(hidden, "server")} with this '
            'request than it names, counted in its `servers_hidden`.'
        )
    if _get(approval, 'status') == 'pending':
        sentences.append(
            'Alpacon counts servers and clusters only for a reader who neither '
            'manages the session nor may decide this request.'
        )
        deciders = _DECIDERS
    else:
        sentences.append(
            'Alpacon counts servers and clusters only for a reader who does not '
            'manage the session.'
        )
        deciders = ''
    sentences += [_NO_TOOL_SHOWS, f'{_MANAGERS}{deciders}.']
    return ' '.join(sentences)


def analysis_note(analysis: object) -> str | None:
    """The note for one session analysis body; None when nothing is counted."""
    counts = _analysis_counts(analysis)
    if not counts:
        return None
    return ' '.join(
        [
            *_target_sentences(
                counts,
                'work_session_detail.',
                "the analyzed session's scope",
                'every server the session covered',
            ),
            'Alpacon counts servers only for a reader who does not manage the session.',
            _NO_TOOL_SHOWS,
            f'{_MANAGERS}.',
        ]
    )


def _brief(counts: _Counts) -> str:
    """A row's counts in a few words, for a page note."""
    parts = []
    if counts.servers:
        parts.append(_more(counts.servers, 'server'))
    if counts.clusters:
        parts.append(_more(counts.clusters, 'cluster'))
    diff = [
        f'{count} more {when}'
        for count, when in ((counts.old, 'before'), (counts.new, 'after'))
        if count
    ]
    if diff:
        parts.append(f"approver's diff: {', '.join(diff)}")
    if counts.changes:
        parts.append(f'modification: {_more(counts.changes, "server")}')
    if counts.flagged:
        parts.append(f'account warning: {_more(counts.flagged, "server")}')
    for session_id, hidden in counts.overlaps:
        parts.append(
            f'overlapping session {session_id}: {_more(hidden, "shared server")}'
        )
    return '; '.join(parts)


#: Tool description sentences, kept beside the field paths they name.
SESSION_TARGETS_DESCRIPTION = (
    "A Work Session's servers and clusters name only the targets you can reach; "
    'servers_hidden and clusters_hidden count the rest, with no name or id (also '
    'old_hidden and new_hidden in adjustments.servers, and servers_hidden in '
    'pending_modification_request.changes and account_flag). When a count is above '
    '0 the result carries hidden_targets_note: the named list is not the whole '
    'scope; Alpacon sends a count above 0 only to a reader who does not manage that '
    'session.'
)

APPROVAL_TARGETS_DESCRIPTION = (
    'Server and cluster lists name only the targets you can reach, and a sibling '
    'count holds the rest with no name or id: servers_hidden and clusters_hidden on '
    'work_session, old_hidden and new_hidden in metadata.adjustments.servers, '
    'servers_hidden in metadata.changes and each overlapping_sessions row. When a '
    'count is above 0 the result carries hidden_targets_note: the named list is not '
    "the request's whole scope."
)

ANALYSIS_TARGETS_DESCRIPTION = (
    'In a Work Session analysis, work_session_detail.servers names only the servers '
    'you can reach, and work_session_detail.servers_hidden counts the rest with no '
    'name or id. When it is above 0 the result carries hidden_targets_note: the '
    'named list is not every server the session covered.'
)


@dataclass(frozen=True)
class _Page:
    """How to read and name one kind of row; calling it gives a page's note."""

    noun: str
    counts: Callable[[object], _Counts]
    label: Callable[[Mapping[str, object]], str]
    guidance: str

    def __call__(self, data: object) -> str | None:
        rows = _get(data, 'results')
        counted = [
            f'{self.label(row)} ({_brief(counts)})'
            for row in (rows if isinstance(rows, list) else ())
            if isinstance(row, Mapping) and (counts := self.counts(row))
        ]
        if not counted:
            return None
        many = len(counted)
        return (
            f'{many} of the {self.noun} on this page '
            f'{"names" if many == 1 else "name"} only part of '
            f'{"its" if many == 1 else "their"} scope: {"; ".join(counted)}. '
            f'{self.guidance}'
        )


#: Page notes; each names every row that counts anything.
SESSION_PAGE = _Page(
    noun='sessions',
    counts=_session_counts,
    label=lambda row: str(row.get('id')),
    guidance=(
        "Each row's `servers` and `clusters`, and the server lists inside it, hold "
        'only what you can reach; the `*_hidden` count beside each is the rest, with '
        "no name or id. Do not report a row's named servers as that session's whole "
        f'scope. {_NOT_A_MANAGER} So do not reuse such a session. work_session_get '
        'on its id explains each count.'
    ),
)

APPROVAL_PAGE = _Page(
    noun='approval requests',
    counts=_approval_counts,
    label=lambda row: f'request {row.get("id")}',
    guidance=(
        "A row's `work_session`, `metadata.adjustments.servers`, `metadata.changes` "
        'and `overlapping_sessions` name only the servers you can reach; the '
        '`*_hidden` count beside each list is the rest, with no name or id. Do not '
        "report a row's named servers as the request's whole scope. "
        'get_approval_request on its id explains each count.'
    ),
)

ANALYSIS_PAGE = _Page(
    noun='session analyses',
    counts=_analysis_counts,
    label=lambda row: f'analysis {row.get("id")} of session {row.get("work_session")}',
    guidance=(
        "A row's `work_session_detail.servers` names only the servers you can reach; "
        '`work_session_detail.servers_hidden` is the rest, with no name or id. Do not '
        "report a row's named servers as every server the analyzed session covered. "
        'get_session_analysis_detail on its id explains the count.'
    ),
)


def attach_hidden_targets_note(
    response: ToolResponse, describe: Callable[[object], str | None]
) -> ToolResponse:
    """Add ``hidden_targets_note`` to a successful result that counts a target.

    ``data`` stays exactly as the server sent it; an error result is returned as is.
    """
    if response.get('status') != 'success':
        return response
    if note := describe(response.get('data')):
        response['hidden_targets_note'] = note
    return response
