"""Notes on the targets a reader does not reach (#480).

The bodies below follow the Alpacon API's response shapes: a session targets servers
or one cluster, never both, and every list keeps its shape beside a sibling count.
"""

import copy

import pytest

from tests.conftest import VALID_SERVER_ID, work_session_body
from utils.unreached_targets import (
    ANALYSIS_PAGE,
    APPROVAL_PAGE,
    SESSION_PAGE,
    analysis_note,
    approval_note,
    attach_hidden_targets_note,
    session_note,
)

WEB_1 = {'id': VALID_SERVER_ID, 'name': 'web-1'}
SESSION_ID = '550e8400-e29b-41d4-a716-446655440020'
OTHER_SESSION_ID = '550e8400-e29b-41d4-a716-446655440021'
REQUEST_ID = '550e8400-e29b-41d4-a716-446655440030'


class TestSessionNote:
    def test_fully_named_session_has_no_note(self):
        assert session_note(work_session_body()) is None

    def test_body_from_a_server_without_counts_has_no_note(self):
        assert session_note({'id': SESSION_ID, 'servers': [WEB_1]}) is None

    @pytest.mark.parametrize('value', [True, -1, '2', 2.0, None, [], {}])
    def test_a_count_that_is_not_a_positive_integer_is_ignored(self, value):
        assert session_note(work_session_body(servers_hidden=value)) is None

    def test_servers_hidden_names_the_count_and_the_field(self):
        note = session_note(work_session_body(servers_hidden=2))

        assert note is not None
        assert '2 more servers' in note
        assert '`servers_hidden`' in note
        assert 'Do not report `servers` as the session' in note

    def test_one_hidden_server_is_singular(self):
        note = session_note(work_session_body(servers_hidden=1))

        assert note is not None
        assert '1 more server ' in note
        assert '1 more servers' not in note

    def test_cluster_session_gets_its_own_opening(self):
        note = session_note(
            work_session_body(servers=[], clusters=[], clusters_hidden=1),
        )

        assert note is not None
        assert '1 more cluster' in note
        assert '`clusters_hidden`' in note
        assert 'servers_hidden' not in note

    def test_cluster_session_is_not_described_as_counting_servers_only(self):
        session = work_session_body(servers=[], clusters=[], clusters_hidden=1)
        request = {'id': REQUEST_ID, 'status': 'pending', 'work_session': session}

        for note in (session_note(session), approval_note(request)):
            assert note is not None
            assert 'counts servers only' not in note
            assert 'names every server to' not in note
            assert 'counts servers and clusters only' in note

    def test_adjustments_counts_are_read_inside_adjustments_servers(self):
        note = session_note(
            work_session_body(
                adjustments={
                    'servers': {
                        'old': [WEB_1],
                        'new': [WEB_1],
                        'old_hidden': 2,
                        'new_hidden': 1,
                    }
                }
            )
        )

        assert note is not None
        assert '2 more before (`old_hidden`)' in note
        assert '1 more after (`new_hidden`)' in note
        assert 'do not show every server added or removed' in note
        assert 'was not removed' not in note

    def test_only_old_hidden_is_named_alone(self):
        note = session_note(
            work_session_body(
                adjustments={'servers': {'old': [], 'new': [], 'old_hidden': 3}}
            )
        )

        assert note is not None
        assert '3 more before (`old_hidden`)' in note
        assert 'new_hidden' not in note

    def test_pending_modification_count_is_read_inside_changes(self):
        note = session_note(
            work_session_body(
                pending_modification_request={
                    'id': REQUEST_ID,
                    'changes': {'servers': [WEB_1], 'servers_hidden': 4},
                }
            )
        )

        assert note is not None
        assert '`pending_modification_request.changes`' in note
        assert '4 more servers' in note

    def test_account_flag_count(self):
        note = session_note(
            work_session_body(
                account_flag={
                    'code': 'account_bound_to_other_person',
                    'servers': [],
                    'servers_hidden': 1,
                }
            )
        )

        assert note is not None
        assert '`account_flag`' in note
        assert '1 more server' in note

    @pytest.mark.parametrize(
        'fields',
        [
            {'adjustments': {'servers': [WEB_1]}},
            {'adjustments': []},
            {'adjustments': 'x'},
            {'pending_modification_request': {'changes': None}},
            {'pending_modification_request': {'changes': ['servers']}},
            {'account_flag': ['servers_hidden']},
        ],
    )
    def test_a_nest_of_the_wrong_type_reads_zero(self, fields):
        assert session_note(work_session_body(**fields)) is None

    def test_not_a_dict_has_no_note(self):
        assert session_note(None) is None
        assert session_note([work_session_body(servers_hidden=1)]) is None

    def test_a_count_says_the_reader_does_not_manage_the_session(self):
        note = session_note(work_session_body(servers_hidden=1))

        assert note is not None
        assert 'only for a reader who does not manage the session' in note
        assert 'work_session_update' not in note

    def test_decider_clause_on_a_session_waiting_for_its_approval(self):
        note = session_note(
            work_session_body(
                status='pending', approval_request_id=REQUEST_ID, servers_hidden=1
            )
        )

        assert note is not None
        assert 'anyone who may decide its pending approval' in note

    @pytest.mark.parametrize(
        ('status', 'approval_request_id'),
        [('active', REQUEST_ID), ('pending', None), ('active', None)],
        ids=['approved-session', 'pending-without-request', 'no-request'],
    )
    def test_no_decider_clause_unless_both_hold(self, status, approval_request_id):
        note = session_note(
            work_session_body(
                status=status,
                approval_request_id=approval_request_id,
                servers_hidden=1,
            )
        )

        assert note is not None
        assert 'decide' not in note


class TestApprovalNote:
    def test_work_session_request_reads_the_nested_session(self):
        note = approval_note(
            {
                'id': REQUEST_ID,
                'request_type': 'work_session',
                'status': 'pending',
                'work_session': work_session_body(status='pending', servers_hidden=2),
                'metadata': {},
            }
        )

        assert note is not None
        assert '`work_session.servers_hidden`' in note
        assert '2 more servers' in note

    def test_the_same_diff_on_both_paths_is_described_once(self):
        diff = {'servers': {'old': [], 'new': [], 'old_hidden': 1, 'new_hidden': 0}}
        note = approval_note(
            {
                'id': REQUEST_ID,
                'request_type': 'work_session',
                'status': 'approved',
                'work_session': work_session_body(adjustments=copy.deepcopy(diff)),
                'metadata': {'adjustments': copy.deepcopy(diff)},
            }
        )

        assert note is not None
        assert note.count("The approver's diff") == 1
        assert '1 more before (`old_hidden`) is counted' in note

    def test_mod_request_reads_metadata_adjustments_and_changes(self):
        note = approval_note(
            {
                'id': REQUEST_ID,
                'request_type': 'work_session_mod',
                'status': 'pending',
                'work_session': None,
                'metadata': {
                    'adjustments': {
                        'servers': {
                            'old': [],
                            'new': [],
                            'old_hidden': 1,
                            'new_hidden': 2,
                        }
                    },
                    'changes': {'servers': [WEB_1], 'servers_hidden': 3},
                },
            }
        )

        assert note is not None
        assert '`metadata.adjustments.servers`' in note
        assert '1 more before (`old_hidden`)' in note
        assert '2 more after (`new_hidden`)' in note
        assert '`metadata.changes`' in note
        assert '3 more servers' in note

    def test_overlapping_sessions_name_their_row(self):
        note = approval_note(
            {
                'id': REQUEST_ID,
                'request_type': 'work_session',
                'status': 'pending',
                'work_session': work_session_body(status='pending'),
                'overlapping_sessions': [
                    {'id': SESSION_ID, 'servers': [WEB_1], 'servers_hidden': 0},
                    {'id': OTHER_SESSION_ID, 'servers': [], 'servers_hidden': 1},
                    'not a row',
                ],
            }
        )

        assert note is not None
        assert OTHER_SESSION_ID in note
        assert SESSION_ID not in note.replace(OTHER_SESSION_ID, '')
        assert 'shares 1 more server with this request than it names' in note

    def test_decider_clause_follows_the_request_status(self):
        def body(status: str) -> dict[str, object]:
            return {
                'id': REQUEST_ID,
                'request_type': 'work_session',
                'status': status,
                'work_session': work_session_body(servers_hidden=1),
            }

        pending = approval_note(body('pending'))
        decided = approval_note(body('approved'))

        assert pending is not None and decided is not None
        assert 'neither manages the session nor may decide this request' in pending
        assert 'anyone who may decide its pending approval' in pending
        assert 'decide' not in decided

    def test_request_without_counts_has_no_note(self):
        assert (
            approval_note(
                {
                    'id': REQUEST_ID,
                    'request_type': 'command',
                    'status': 'pending',
                    'metadata': {'work_session': {'id': SESSION_ID}},
                }
            )
            is None
        )


class TestAnalysisNote:
    def test_detail_count(self):
        note = analysis_note(
            {
                'id': 'analysis-1',
                'work_session': SESSION_ID,
                'work_session_detail': {
                    'id': SESSION_ID,
                    'status': 'completed',
                    'servers': [WEB_1],
                    'servers_hidden': 2,
                },
            }
        )

        assert note is not None
        assert '`work_session_detail.servers_hidden`' in note
        assert '2 more servers' in note
        assert 'decide' not in note

    def test_detail_withheld_from_the_reader_has_no_note(self):
        assert analysis_note({'id': 'a', 'work_session_detail': None}) is None


class TestPageNote:
    def test_lists_only_rows_with_counts_in_page_order(self):
        page = {
            'count': 4,
            'results': [
                work_session_body(id='s-a', servers_hidden=2),
                work_session_body(id='s-b'),
                'not a row',
                work_session_body(id='s-c', servers=[], clusters_hidden=1),
            ],
        }

        note = SESSION_PAGE(page)

        assert note is not None
        assert note.index('s-a') < note.index('s-c')
        assert 's-b' not in note
        assert '2 of the sessions on this page' in note
        assert 's-a (2 more servers)' in note
        assert 's-c (1 more cluster)' in note

    def test_row_summary_names_only_the_nonzero_side_of_a_diff(self):
        row = work_session_body(
            adjustments={'servers': {'old_hidden': 0, 'new_hidden': 2}}
        )

        note = SESSION_PAGE({'results': [row]})

        assert note is not None
        assert "approver's diff: 2 more after" in note
        assert 'before' not in note

    def test_row_summary_names_the_account_warning(self):
        row = work_session_body(
            id='s-flag',
            account_flag={
                'code': 'account_bound_to_other_person',
                'servers': [],
                'servers_hidden': 2,
            },
        )

        note = SESSION_PAGE({'results': [row]})

        assert note is not None
        assert 's-flag (account warning: 2 more servers)' in note

    def test_page_with_nothing_counted_has_no_note(self):
        assert SESSION_PAGE({'results': [work_session_body()]}) is None
        assert SESSION_PAGE({'results': None}) is None
        assert SESSION_PAGE(None) is None

    def test_approval_page_rows(self):
        note = APPROVAL_PAGE(
            {
                'results': [
                    {
                        'id': REQUEST_ID,
                        'status': 'pending',
                        'work_session': work_session_body(
                            status='pending', servers_hidden=1
                        ),
                    }
                ]
            }
        )

        assert note is not None
        assert f'request {REQUEST_ID} (1 more server)' in note
        assert 'get_approval_request' in note

    def test_analysis_page_rows(self):
        note = ANALYSIS_PAGE(
            {
                'results': [
                    {
                        'id': 'analysis-1',
                        'work_session': SESSION_ID,
                        'work_session_detail': {'servers': [], 'servers_hidden': 3},
                    }
                ]
            }
        )

        assert note is not None
        assert f'analysis analysis-1 of session {SESSION_ID} (3 more servers)' in note

    def test_one_row_is_singular(self):
        note = SESSION_PAGE({'results': [work_session_body(servers_hidden=1)]})

        assert note is not None
        assert '1 of the sessions on this page names' in note


class TestAttachScopeNote:
    def test_success_gains_the_note_and_keeps_data(self):
        body = work_session_body(servers_hidden=2)
        response = {'status': 'success', 'data': body, 'region': 'ap1'}
        expected = copy.deepcopy(body)

        result = attach_hidden_targets_note(response, session_note)

        assert result['data'] == expected
        assert '2 more servers' in result['hidden_targets_note']

    def test_no_count_adds_no_key(self):
        result = attach_hidden_targets_note(
            {'status': 'success', 'data': work_session_body()}, session_note
        )

        assert 'hidden_targets_note' not in result

    def test_a_result_that_is_not_a_success_is_returned_as_is(self):
        response = {'status': 'error', 'data': work_session_body(servers_hidden=1)}
        expected = copy.deepcopy(response)

        assert attach_hidden_targets_note(response, session_note) == expected
