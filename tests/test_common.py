"""Unit tests for utils.common WorkSession gate and denial-guidance helpers."""

import os
import subprocess
import sys
import textwrap
from http import HTTPStatus
from pathlib import Path

import pytest

from utils.common import (
    _ERROR_CODE_HINT,
    _NEXT_ACTION_BY_CATEGORY,
    _WORK_SESSION_GATE_CODES,
    _WORK_SESSION_GATE_NEXT_ACTION,
    build_list_params,
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


class TestErrorCodeHint:
    def test_command_inline_credential_names_env_and_reason(self):
        hint = _ERROR_CODE_HINT['command_inline_credential']
        assert 'env' in hint
        assert 'audit log' in hint
        # No new opt-in param: this hint must not tell the agent to pass one.
        assert 'credential_exposure_acknowledged' not in hint

    def test_gate_codes_have_no_hint_entries(self):
        # Gate codes are handled entirely by work_session_gate_response;
        # _ERROR_CODE_HINT is only consulted on the generic error path.
        assert not (set(_ERROR_CODE_HINT) & _WORK_SESSION_GATE_CODES)


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


class TestImportSideEffects:
    """utils.common once built a TokenManager at module scope, so importing it
    read ~/.alpacon-mcp/token.json before any fixture could intervene.
    """

    _PROBE = textwrap.dedent("""
        import pathlib
        import sys

        home_config = str(pathlib.Path.home() / '.alpacon-mcp')
        hits = []

        def audit(event, args):
            if event in ('open', 'os.mkdir') and home_config in str(args[0]):
                hits.append((event, str(args[0])))

        sys.addaudithook(audit)

        import utils.common  # noqa: F401

        print('HITS', hits)
    """)

    def test_importing_utils_common_leaves_the_user_config_untouched(self, tmp_path):
        fake_home = tmp_path / 'home'
        config_dir = fake_home / '.alpacon-mcp'
        config_dir.mkdir(parents=True)
        (config_dir / 'token.json').write_text('{"ap1": {"workspace": "secret"}}')

        repo_root = Path(__file__).resolve().parent.parent
        env = {
            **os.environ,
            'HOME': str(fake_home),
            'PYTHONPATH': str(repo_root),
        }
        env.pop('ALPACON_MCP_CONFIG_FILE', None)

        result = subprocess.run(  # noqa: S603 - argv is this file's own probe
            [sys.executable, '-c', self._PROBE],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        assert 'HITS []' in result.stdout, result.stdout
