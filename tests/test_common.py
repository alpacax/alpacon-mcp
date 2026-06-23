"""Unit tests for utils.common WorkSession gate helpers."""

import pytest

from utils.common import (
    _WORK_SESSION_GATE_CODES,
    work_session_gate_response,
)


class TestWorkSessionGateResponse:
    def test_not_active_maps_to_pending_approval(self):
        out = work_session_gate_response('work_session_not_active')
        assert out['status'] == 'pending_approval'
        assert out['category'] == 'WORK_SESSION_PENDING'
        assert out['requires_human_approval'] is True
        assert out['approvable_by_agent'] is False

    def test_required_maps_to_error_with_next_action(self):
        out = work_session_gate_response('work_session_required')
        assert out['status'] == 'error'
        assert out['code'] == 'work_session_required'
        assert 'work_session_create' in out['next_action']
        assert out['requires_human_approval'] is False

    @pytest.mark.parametrize(
        'code',
        [
            'work_session_not_usable',
            'work_session_expired',
            'work_session_scope_not_allowed',
            'work_session_server_not_allowed',
            'work_session_assignee_mismatch',
        ],
    )
    def test_other_codes_are_actionable_errors(self, code):
        out = work_session_gate_response(code)
        assert out['status'] == 'error'
        assert out['code'] == code
        assert out['next_action']

    def test_kwargs_are_passed_through(self):
        out = work_session_gate_response(
            'work_session_required', region='ap1', workspace='ws'
        )
        assert out['region'] == 'ap1'
        assert out['workspace'] == 'ws'

    def test_all_seven_codes_recognized(self):
        assert len(_WORK_SESSION_GATE_CODES) == 7
