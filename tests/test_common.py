"""Unit tests for utils.common WorkSession gate and denial-guidance helpers."""

import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from utils.common import (
    _ERROR_CODE_HINT,
    _LIMIT_EXCEEDED_CODE_TO_AXIS,
    _MONTHLY_PLAN_LIMIT_AXES,
    _NEXT_ACTION_BY_CATEGORY,
    _PLAN_LIMIT_AXIS_NAME,
    _WORK_SESSION_GATE_CODES,
    _WORK_SESSION_GATE_NEXT_ACTION,
    _plan_limit_axis,
    _plan_limit_billing_link,
    build_list_params,
    plan_limit_response,
    resolve_time_window,
    resolve_work_session_id,
    unwrap_http_result,
    work_session_gate_response,
)


class TestSudoDenialNextActions:
    """Falling through to _DEFAULT_NEXT_ACTION would tell the agent to wait on an
    approval request that, for some of these codes, does not exist.
    """

    @pytest.mark.parametrize(
        'category',
        [
            'SUDO_POLICY_MFA_REQUIRED',
            'SUDO_INTENT_DEVIATION',
            'WORK_SESSION_SCOPE_NOT_ALLOWED',
        ],
    )
    def test_category_has_own_next_action(self, category):
        assert _NEXT_ACTION_BY_CATEGORY[category].strip()

    def test_policy_mfa_required_names_the_policy_edit(self):
        # _DEFAULT_NEXT_ACTION is SUDO_APPROVAL_REQUIRED's own text, so a key
        # silently pointing at it still passes a non-emptiness check.
        assert (
            'allow_bypass_mfa' in _NEXT_ACTION_BY_CATEGORY['SUDO_POLICY_MFA_REQUIRED']
        )

    def test_intent_deviation_states_both_paths(self):
        text = _NEXT_ACTION_BY_CATEGORY['SUDO_INTENT_DEVIATION']
        assert 'work_session_update' in text
        # Saying otherwise sends the agent down a path it cannot finish.
        assert 'queue' in text

    def test_scope_not_allowed_wording_is_shared(self):
        # One denial, two transports; one string so the wording cannot drift.
        assert (
            _NEXT_ACTION_BY_CATEGORY['WORK_SESSION_SCOPE_NOT_ALLOWED']
            == _WORK_SESSION_GATE_NEXT_ACTION['work_session_scope_not_allowed']
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
            'status_code': HTTPStatus.BAD_REQUEST,
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
        assert out['status_code'] == HTTPStatus.BAD_REQUEST

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
        # Generic path does not route through the gate-response shape...
        assert 'code' not in out
        assert 'next_action' not in out
        # ...but the server's error code must still surface, not be dropped.
        assert out['error_code'] == 'some_other_error'

    def test_non_json_body_is_generic_error(self):
        env = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.BAD_REQUEST,
            'response': '<html>500</html>',
        }
        out = unwrap_http_result(env, default_message='failed')
        assert out['status'] == 'error'
        assert 'error_code' not in out

    def test_no_response_key_is_generic_error(self):
        env = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.INTERNAL_SERVER_ERROR,
            'message': 'boom',
        }
        out = unwrap_http_result(env, default_message='failed')
        assert out['status'] == 'error'
        assert 'error_code' not in out
        assert out['message'] == 'boom'

    def test_success_envelope_returns_none(self):
        assert unwrap_http_result({'status': 'success'}, default_message='x') is None

    def test_command_inline_credential_gets_actionable_hint(self):
        out = unwrap_http_result(
            self._envelope('command_inline_credential'), default_message='failed'
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'command_inline_credential'
        assert 'env' in out['message']
        assert 'audit log' in out['message']

    def test_unhinted_code_has_no_hint_text_appended(self):
        out = unwrap_http_result(
            self._envelope('some_other_error'), default_message='failed'
        )
        # No entry in _ERROR_CODE_HINT for this code: message is untouched.
        assert out['message'] == 'HTTP 400'

    def test_workspace_extension_plan_required_gets_actionable_hint(self):
        out = unwrap_http_result(
            self._envelope('workspace_extension_plan_required'),
            default_message='failed',
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'workspace_extension_plan_required'
        assert 'plan' in out['message']
        assert 'upgrading' in out['message']

    def test_workspace_extension_not_enabled_gets_actionable_hint(self):
        out = unwrap_http_result(
            self._envelope('workspace_extension_not_enabled'),
            default_message='failed',
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'workspace_extension_not_enabled'
        assert 'workspace admin' in out['message']
        assert 'workspace settings' in out['message']

    @pytest.mark.parametrize(
        ('code', 'expected_snippet'),
        [
            ('preferences_agent_rollout_policy_invalid', 'mode'),
            ('preferences_agent_rollout_mode_invalid', 'n_minus_1'),
            ('preferences_agent_rollout_mode_unavailable', 'pinned'),
            ('preferences_agent_rollout_window_days_invalid', 'window.days'),
            (
                'preferences_agent_rollout_window_start_hour_invalid',
                'window.start_hour',
            ),
            (
                'preferences_agent_rollout_window_length_invalid',
                'window.length_hours',
            ),
            (
                'preferences_agent_rollout_window_timezone_invalid',
                'window.timezone',
            ),
        ],
    )
    def test_agent_rollout_policy_codes_get_actionable_hints(
        self, code, expected_snippet
    ):
        out = unwrap_http_result(self._envelope(code), default_message='failed')
        assert out['status'] == 'error'
        assert out['error_code'] == code
        assert expected_snippet in out['message']


class TestErrorCodeHint:
    def test_command_inline_credential_names_env_and_reason(self):
        hint = _ERROR_CODE_HINT['command_inline_credential']
        assert 'env' in hint
        assert 'audit log' in hint
        # No new opt-in param: this hint must not tell the agent to pass one.
        assert 'credential_exposure_acknowledged' not in hint

    def test_workspace_extension_plan_required_names_the_upgrade_path(self):
        hint = _ERROR_CODE_HINT['workspace_extension_plan_required']
        assert 'plan' in hint
        assert 'metrics' in hint

    def test_workspace_extension_not_enabled_names_the_admin_path(self):
        hint = _ERROR_CODE_HINT['workspace_extension_not_enabled']
        assert 'workspace admin' in hint
        assert 'workspace settings' in hint

    def test_gate_codes_have_no_hint_entries(self):
        # Gate codes are handled entirely by work_session_gate_response;
        # _ERROR_CODE_HINT is only consulted on the generic error path.
        assert not (set(_ERROR_CODE_HINT) & _WORK_SESSION_GATE_CODES)

    def test_mode_unavailable_names_pinned_upgrades_not_a_retry(self):
        hint = _ERROR_CODE_HINT['preferences_agent_rollout_mode_unavailable']
        assert 'pinned' in hint
        assert 'latest' in hint
        assert 'manual' in hint

    @pytest.mark.parametrize(
        'code',
        [
            'preferences_agent_rollout_policy_invalid',
            'preferences_agent_rollout_mode_invalid',
            'preferences_agent_rollout_mode_unavailable',
            'preferences_agent_rollout_window_days_invalid',
            'preferences_agent_rollout_window_start_hour_invalid',
            'preferences_agent_rollout_window_length_invalid',
            'preferences_agent_rollout_window_timezone_invalid',
        ],
    )
    def test_agent_rollout_policy_hints_are_registered_and_non_empty(self, code):
        assert _ERROR_CODE_HINT[code].strip()


class TestPlanLimitAxisClassification:
    """Classification rules for a plan-limit 402 (#296): rule 1 and rule 2."""

    @pytest.mark.parametrize('code', list(_LIMIT_EXCEEDED_CODE_TO_AXIS))
    def test_rule1_gate_plan_reads_axis_off_the_body_not_the_code(self, code):
        # Rule 1 reads `axis` straight off the body; a current server always
        # sends the matching code too, but here `axis` is deliberately made
        # to disagree with what the code table would say, to prove axis wins.
        assert (
            _plan_limit_axis({'code': code, 'gate': 'plan', 'axis': 'user'}, code)
            == 'user'
        )

    def test_rule1_gate_plan_without_axis_is_a_feature_lock(self):
        assert (
            _plan_limit_axis(
                {'gate': 'plan', 'code': 'workspace_enterprise_plan_required'}, None
            )
            is None
        )

    @pytest.mark.parametrize(
        ('code', 'expected_axis'), list(_LIMIT_EXCEEDED_CODE_TO_AXIS.items())
    )
    def test_rule2_gate_absent_legacy_code_maps_to_its_axis(self, code, expected_axis):
        assert _plan_limit_axis({'code': code}, code) == expected_axis

    def test_gate_absent_unrecognized_code_is_not_a_plan_limit(self):
        assert (
            _plan_limit_axis({'code': 'some_other_error'}, 'some_other_error') is None
        )

    def test_gate_present_but_not_plan_never_falls_back_to_rule2(self):
        # Even though the code matches the legacy table, a non-plan gate is a
        # different kind of 402 entirely (role, token_scope, approval, rate).
        assert (
            _plan_limit_axis(
                {'gate': 'role', 'code': 'server_limit_exceeded'},
                'server_limit_exceeded',
            )
            is None
        )

    def test_non_dict_body_is_not_a_plan_limit(self):
        assert _plan_limit_axis(None, 'server_limit_exceeded') is None

    def test_axis_must_be_a_non_empty_string(self):
        assert _plan_limit_axis({'gate': 'plan', 'axis': ''}, None) is None
        assert _plan_limit_axis({'gate': 'plan', 'axis': 5}, None) is None


class TestPlanLimitBillingLink:
    """The console billing link a plan-limit next_action carries (#296)."""

    def test_derived_cloud_host_resolves_a_link(self, mock_token_manager):
        mock_token_manager.get_base_url_override.return_value = None
        assert (
            _plan_limit_billing_link('us1', 'acme')
            == 'https://alpacon.io/acme/settings/billing'
        )

    def test_pinned_cloud_override_resolves_its_own_label(self, mock_token_manager):
        # ADR 0027: the pinned host, not the (possibly stale) workspace label.
        mock_token_manager.get_base_url_override.return_value = (
            'https://old-slug.us1.alpacon.io'
        )
        assert (
            _plan_limit_billing_link('us1', 'new-slug')
            == 'https://alpacon.io/old-slug/settings/billing'
        )

    def test_self_hosted_override_gets_words(self, mock_token_manager):
        mock_token_manager.get_base_url_override.return_value = (
            'https://onprem.acme-corp.internal'
        )
        assert (
            _plan_limit_billing_link('ap1', 'onprem')
            == 'Settings → Billing in your Alpacon console'
        )

    def test_missing_region_or_workspace_gets_words(self):
        assert (
            _plan_limit_billing_link(None, 'acme')
            == 'Settings → Billing in your Alpacon console'
        )
        assert (
            _plan_limit_billing_link('us1', None)
            == 'Settings → Billing in your Alpacon console'
        )


class TestPlanLimitResponse:
    def test_shape_and_fields(self):
        out = plan_limit_response(
            error_code='server_limit_exceeded',
            axis='server',
            next_value='/api/workspaces/workspaces/ws-1/entitlements/',
            region=None,
            workspace=None,
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'server_limit_exceeded'
        assert out['gate'] == 'plan'
        assert out['axis'] == 'server'
        assert out['next'] == '/api/workspaces/workspaces/ws-1/entitlements/'
        assert out['requires_human_approval'] is False
        assert out['next_action'].startswith('Do not retry.')

    def test_next_value_passes_through_none_unmodified(self):
        out = plan_limit_response(
            error_code='websh_limit_exceeded', axis='websh', next_value=None
        )
        assert out['next'] is None

    def test_extra_kwargs_are_carried_and_cannot_override_fixed_fields(self):
        out = plan_limit_response(
            error_code='server_limit_exceeded',
            axis='server',
            next_value=None,
            region='us1',
            workspace='acme',
            status_code=HTTPStatus.PAYMENT_REQUIRED,
            gate='role',  # a caller-supplied 'gate' must not leak through
        )
        assert out['region'] == 'us1'
        assert out['workspace'] == 'acme'
        assert out['status_code'] == HTTPStatus.PAYMENT_REQUIRED
        assert out['gate'] == 'plan'

    @pytest.mark.parametrize('axis', list(_PLAN_LIMIT_AXIS_NAME))
    def test_every_known_axis_gets_a_non_empty_next_action(self, axis):
        out = plan_limit_response(error_code='x', axis=axis, next_value=None)
        assert out['next_action']

    def test_unknown_axis_falls_back_to_the_raw_token(self):
        # Defensive: a server axis this client does not yet know about should
        # still produce a readable (if unpolished) next_action, not a KeyError.
        out = plan_limit_response(
            error_code='x', axis='brand-new-axis', next_value=None
        )
        assert 'brand-new-axis plan limit was reached' in out['next_action']


class TestUnwrapHttpResultPlanLimit:
    """unwrap_http_result on a plan-limit 402 (#296)."""

    def _envelope(
        self,
        *,
        code: str,
        gate: str | None = 'plan',
        axis: str | None = None,
        next: str | None = None,  # noqa: A002 - mirrors the body's own field name
        status_code: HTTPStatus = HTTPStatus.PAYMENT_REQUIRED,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {'code': code}
        if gate is not None:
            body['gate'] = gate
        if axis is not None:
            body['axis'] = axis
        if next is not None:
            body['next'] = next
        return {
            'error': 'HTTP Error',
            'status_code': status_code,
            'message': f'HTTP {int(status_code)}',
            'response': json.dumps(body),
        }

    def test_current_server_envelope_becomes_plan_limit_response(
        self, mock_token_manager
    ):
        mock_token_manager.get_base_url_override.return_value = None
        out = unwrap_http_result(
            self._envelope(
                code='server_limit_exceeded',
                axis='server',
                next='/api/workspaces/workspaces/ws-1/entitlements/',
            ),
            default_message='failed',
            region='us1',
            workspace='acme',
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'server_limit_exceeded'
        assert out['gate'] == 'plan'
        assert out['axis'] == 'server'
        assert out['next'] == '/api/workspaces/workspaces/ws-1/entitlements/'
        assert out['requires_human_approval'] is False
        assert out['region'] == 'us1'
        assert out['workspace'] == 'acme'
        assert out['status_code'] == HTTPStatus.PAYMENT_REQUIRED
        next_action = out['next_action']
        assert next_action.startswith('Do not retry.')
        assert 'servers plan limit was reached' in next_action
        assert 'https://alpacon.io/acme/settings/billing' in next_action
        assert 'https://www.alpacax.com/alpacon/pricing' in next_action
        # Re-registration guidance (C9) is server-axis only.
        assert 'delete the old server entry' in next_action

    def test_gate_less_legacy_code_becomes_the_same_shape(self, mock_token_manager):
        mock_token_manager.get_base_url_override.return_value = None
        out = unwrap_http_result(
            self._envelope(code='user_limit_exceeded', gate=None),
            default_message='failed',
            region='ap1',
            workspace='corp',
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'user_limit_exceeded'
        assert out['gate'] == 'plan'
        assert out['axis'] == 'user'
        assert out['next'] is None
        assert out['requires_human_approval'] is False
        next_action = out['next_action']
        assert 'users (pending invitations count) plan limit was reached' in next_action
        assert 'https://alpacon.io/corp/settings/billing' in next_action

    def test_feature_lock_stays_on_the_generic_path(self):
        # gate:"plan" with no axis is a feature lock, not a plan limit: the
        # existing (402, "general") recovery-hint path (utils/recovery_hints.py,
        # applied by the decorator, not here) is what handles it.
        out = unwrap_http_result(
            self._envelope(code='workspace_enterprise_plan_required'),
            default_message='failed',
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'workspace_enterprise_plan_required'
        assert 'axis' not in out
        assert 'next' not in out
        assert 'next_action' not in out
        assert 'requires_human_approval' not in out
        assert 'gate' not in out

    def test_feature_lock_keeps_its_existing_error_code_hint(self):
        # workspace_extension_plan_required already had a curated hint before
        # this change (a different, older feature lock); it must be unaffected.
        out = unwrap_http_result(
            self._envelope(code='workspace_extension_plan_required'),
            default_message='failed',
        )
        assert 'axis' not in out
        assert 'plan' in out['message']
        assert 'upgrading' in out['message']

    def test_no_next_in_body_is_still_fine(self):
        out = unwrap_http_result(
            self._envelope(code='application_limit_exceeded', axis='application'),
            default_message='failed',
        )
        assert out['next'] is None
        assert 'applications plan limit was reached' in out['next_action']
        assert 'remove one no longer used or upgrade' in out['next_action']

    @pytest.mark.parametrize('axis', sorted(_MONTHLY_PLAN_LIMIT_AXES))
    def test_monthly_axis_remedy_names_the_reset_not_a_day_count(self, axis):
        code = next(c for c, a in _LIMIT_EXCEEDED_CODE_TO_AXIS.items() if a == axis)
        out = unwrap_http_result(
            self._envelope(code=code, axis=axis), default_message='failed'
        )
        assert 'resets at the end of the month' in out['next_action']
        # No fabricated day count: utils.http_client's error dict never
        # carries the Retry-After header.
        assert 'day' not in out['next_action']

    def test_self_hosted_host_gets_words_not_a_url(self, mock_token_manager):
        mock_token_manager.get_base_url_override.return_value = (
            'https://onprem.acme-corp.internal'
        )
        out = unwrap_http_result(
            self._envelope(code='server_limit_exceeded', axis='server'),
            default_message='failed',
            region='ap1',
            workspace='onprem',
        )
        assert 'alpacon.io' not in out['next_action']
        assert 'Settings → Billing in your Alpacon console' in out['next_action']

    def test_missing_region_or_workspace_gets_words_not_a_url(self):
        out = unwrap_http_result(
            self._envelope(code='server_limit_exceeded', axis='server'),
            default_message='failed',
        )
        assert 'alpacon.io' not in out['next_action']
        assert 'Settings → Billing in your Alpacon console' in out['next_action']

    def test_non_402_status_never_becomes_a_plan_limit_response(self):
        # The plan-limit contract is 402-specific; a different status that
        # happens to carry a similarly shaped body (gate/axis) must stay on
        # the generic error path, not be misread as a plan limit.
        out = unwrap_http_result(
            self._envelope(
                code='server_limit_exceeded',
                axis='server',
                status_code=HTTPStatus.BAD_REQUEST,
            ),
            default_message='failed',
        )
        assert out['status'] == 'error'
        assert out['error_code'] == 'server_limit_exceeded'
        assert 'axis' not in out
        assert 'next_action' not in out
        assert 'gate' not in out

    def test_workspace_axis_does_not_crash(self):
        # workspace_free_limit_exceeded is not one of the six legacy codes
        # (rule 2), but a current server still sends gate:"plan"+axis (rule 1).
        out = unwrap_http_result(
            self._envelope(code='workspace_free_limit_exceeded', axis='workspace'),
            default_message='failed',
        )
        assert out['axis'] == 'workspace'
        assert 'Free workspaces plan limit was reached' in out['next_action']


class TestPlanLimitDoesNotTouchOtherPaths:
    """Must NOT change: the work-session gate table, _ERROR_CODE_HINT, 401/403 hints."""

    def test_legacy_limit_codes_are_not_work_session_gate_codes(self):
        assert not (set(_LIMIT_EXCEEDED_CODE_TO_AXIS) & _WORK_SESSION_GATE_CODES)

    def test_legacy_limit_codes_have_no_error_code_hint_entries(self):
        # They are classified structurally by _plan_limit_axis before
        # _ERROR_CODE_HINT is ever consulted; an entry here would be dead code.
        assert not (set(_LIMIT_EXCEEDED_CODE_TO_AXIS) & set(_ERROR_CODE_HINT))

    def test_work_session_gate_check_still_runs_first(self):
        # A WorkSession gate code takes that path even though it is unrelated
        # to plan limits, confirming the new check was inserted after it.
        out = unwrap_http_result(
            {
                'error': 'HTTP Error',
                'status_code': HTTPStatus.BAD_REQUEST,
                'response': json.dumps({'code': 'work_session_required'}),
            },
            default_message='failed',
        )
        assert out['code'] == 'work_session_required'
        assert 'axis' not in out


class TestResolveWorkSessionId:
    def test_explicit_wins(self, monkeypatch):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'from-env')
        assert resolve_work_session_id('explicit-id') == 'explicit-id'

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'from-env')
        assert resolve_work_session_id(None) == 'from-env'

    def test_none_when_neither_set(self, monkeypatch):
        monkeypatch.delenv('ALPACON_WORK_SESSION', raising=False)
        assert resolve_work_session_id(None) is None

    def test_empty_env_is_none(self, monkeypatch):
        monkeypatch.setenv('ALPACON_WORK_SESSION', '')
        assert resolve_work_session_id(None) is None

    def test_whitespace_only_env_is_none(self, monkeypatch):
        monkeypatch.setenv('ALPACON_WORK_SESSION', '   ')
        assert resolve_work_session_id(None) is None

    def test_whitespace_only_explicit_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'from-env')
        assert resolve_work_session_id('   ') == 'from-env'


class TestBuildListParams:
    """One rule for an omitted value, so no list tool re-derives its own."""

    def test_omitted_arguments_are_dropped(self):
        assert build_list_params() == {}

    def test_pagination_is_forwarded(self):
        assert build_list_params(page=2, page_size=50) == {'page': 2, 'page_size': 50}

    def test_filters_keep_the_api_field_name(self):
        assert build_list_params(server='srv-1', status='pending') == {
            'server': 'srv-1',
            'status': 'pending',
        }

    def test_none_filter_is_dropped_while_its_siblings_stay(self):
        assert build_list_params(page=1, server=None, status='failed') == {
            'page': 1,
            'status': 'failed',
        }

    @pytest.mark.parametrize('value', [False, 0, '', []])
    def test_falsy_but_supplied_values_are_forwarded(self, value):
        assert build_list_params(acknowledged=value) == {'acknowledged': value}


class TestResolveTimeWindow:
    """A metrics window always has a start; only the start gets a default."""

    def test_both_dates_are_returned_unchanged(self):
        assert resolve_time_window('2024-01-01T00:00:00Z', '2024-01-02T00:00:00Z') == (
            '2024-01-01T00:00:00Z',
            '2024-01-02T00:00:00Z',
        )

    def test_missing_end_stays_missing(self):
        start, end = resolve_time_window('2024-01-01T00:00:00Z', None)
        assert start == '2024-01-01T00:00:00Z'
        assert end is None

    def test_blank_end_is_returned_as_is(self):
        # The caller supplied it; build_list_params decides whether to send it.
        assert resolve_time_window('2024-01-01T00:00:00Z', '')[1] == ''

    @pytest.mark.parametrize('blank', [None, ''])
    def test_missing_start_defaults_to_24_hours_ago(self, blank):
        frozen = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
        with patch('utils.common.datetime') as mock_datetime:
            mock_datetime.now.return_value = frozen

            start, _ = resolve_time_window(blank, None)

        assert start == (frozen - timedelta(hours=24)).isoformat()
        assert start == '2024-05-31T12:00:00+00:00'
