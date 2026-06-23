"""Unit tests for utils.common WorkSession gate helpers."""

import pytest

from utils.common import (
    _WORK_SESSION_GATE_CODES,
    unwrap_http_result,
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


class TestUnwrapHttpResultGate:
    def _envelope(self, code):
        return {
            'error': 'HTTP Error',
            'status_code': 400,
            'message': 'HTTP 400',
            'response': f'{{"code": "{code}"}}',
        }

    def test_gate_code_becomes_gate_response(self):
        out = unwrap_http_result(
            self._envelope('work_session_required'),
            default_message='failed',
            region='ap1',
        )
        assert out['code'] == 'work_session_required'
        assert out['next_action']
        assert out['region'] == 'ap1'
        assert out['status_code'] == 400

    def test_not_active_becomes_pending(self):
        out = unwrap_http_result(
            self._envelope('work_session_not_active'), default_message='failed'
        )
        assert out['status'] == 'pending_approval'

    def test_non_gate_code_is_generic_error(self):
        out = unwrap_http_result(
            self._envelope('some_other_error'), default_message='failed'
        )
        assert out['status'] == 'error'
        assert 'code' not in out  # generic path does not attach a gate code

    def test_non_json_body_is_generic_error(self):
        env = {
            'error': 'HTTP Error',
            'status_code': 400,
            'response': '<html>500</html>',
        }
        out = unwrap_http_result(env, default_message='failed')
        assert out['status'] == 'error'

    def test_no_response_key_is_generic_error(self):
        env = {'error': 'HTTP Error', 'status_code': 500, 'message': 'boom'}
        out = unwrap_http_result(env, default_message='failed')
        assert out['status'] == 'error'

    def test_success_envelope_returns_none(self):
        assert unwrap_http_result({'status': 'success'}, default_message='x') is None
