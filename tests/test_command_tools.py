"""Unit tests for command tools module."""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from server import mcp
from tools.command_tools import (
    _SUDO_DENIAL_HINTS,
    PURPOSE_DEADLINE_SECONDS,
    PURPOSE_MAX_LENGTH,
    _answer_purpose_demand,
    _submit_command,
    _sudo_denial,
    execute_command,
    execute_command_multi_server,
    list_commands,
    state_command_purpose,
)
from utils.common import _NEXT_ACTION_BY_CATEGORY

_GATE_ENVELOPE_REQUIRED = {
    'error': 'HTTP Error',
    'status_code': HTTPStatus.BAD_REQUEST,
    'response': '{"code":"work_session_required"}',
}

_GATE_ENVELOPE_NOT_ACTIVE = {
    'error': 'HTTP Error',
    'status_code': HTTPStatus.BAD_REQUEST,
    'response': '{"code":"work_session_not_active"}',
}


class TestSudoDenialHint:
    """The exec-sudo denial code -> agent guidance mapping."""

    @staticmethod
    def _hint(result: dict) -> str | None:
        denial = _sudo_denial(result)
        return denial[1] if denial else None

    def test_presence_required(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_PRESENCE_REQUIRED).\n'}
        hint = self._hint(out)
        assert hint is not None
        assert 'step-up' in hint

    def test_approval_required(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_APPROVAL_REQUIRED).\n'}
        hint = self._hint(out)
        assert hint is not None
        assert 'approv' in hint

    def test_risk_denied_no_score_disclosed(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_RISK_DENIED).\n'}
        hint = self._hint(out)
        assert hint is not None
        assert 'risk' in hint
        # Disclosure: never echo a score / reasoning, only the category.
        assert 'score' not in hint

    def test_policy_mfa_required(self):
        out = {
            'result': 'Alpacon denied this sudo command (SUDO_POLICY_MFA_REQUIRED).\n'
        }
        hint = self._hint(out)
        assert hint is not None
        # vs SUDO_NO_WORKSESSION_POLICY: a policy matched, just not a bypass one.
        assert 'allow_bypass_mfa' in hint

    def test_intent_deviation(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_INTENT_DEVIATION).\n'}
        hint = self._hint(out)
        assert hint is not None
        # 'queue' keeps the restated-description path from reading as approval-free.
        assert 'work_session_update' in hint
        assert 'queue' in hint

    def test_session_missing(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_SESSION_MISSING).\n'}
        hint = self._hint(out)
        assert hint is not None
        assert 'approv' not in hint

    def test_no_authority(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_NO_AUTHORITY).\n'}
        hint = self._hint(out)
        assert hint is not None
        assert 'local' in hint
        assert 'approv' not in hint

    def test_command_not_authorized(self):
        out = {
            'result': 'Alpacon denied this sudo command '
            '(SUDO_COMMAND_NOT_AUTHORIZED).\n'
        }
        hint = self._hint(out)
        assert hint is not None
        assert 'approv' not in hint

    def test_work_session_scope_not_allowed(self):
        out = {
            'result': 'Alpacon denied this sudo command '
            '(WORK_SESSION_SCOPE_NOT_ALLOWED).\n'
        }
        hint = self._hint(out)
        assert hint is not None
        assert 'scope' in hint
        # The agent can start this itself; saying "a human must" would send it
        # to wait instead. 'queue' keeps that from reading as approval-free.
        assert 'work_session_update' in hint
        assert 'queue' in hint

    def test_workspace_sudo_with_mfa_disabled(self):
        out = {
            'result': 'Alpacon denied this sudo command '
            '(WORKSPACE_SUDO_WITH_MFA_DISABLED).\n'
        }
        hint = self._hint(out)
        assert hint is not None
        assert 'workspace' in hint
        assert 'approv' not in hint

    def test_no_denial(self):
        assert self._hint({'result': 'uid=0(root)\n'}) is None
        assert self._hint({'result': ''}) is None
        assert self._hint({'result': None}) is None
        assert self._hint({}) is None

    def test_bare_code_is_not_a_false_positive(self):
        # A command that merely prints the code (no denial line) is not a hit.
        assert self._hint({'result': 'echo SUDO_RISK_DENIED\n'}) is None

    def test_unmapped_code_yields_no_hint(self):
        # The line parses but the code is unknown: no hint rather than a wrong
        # one. This is the gap the mapping closes code by code.
        out = {'result': 'Alpacon denied this sudo command (SUDO_SOMETHING_NEW).\n'}
        assert _sudo_denial(out) is None

    def test_forged_parenthesized_token_is_not_a_false_positive(self):
        # A command whose own output prints the parenthesized token, without the
        # plugin's denial line, must not forge a hint (the command succeeded).
        forged = {'result': 'echo "(SUDO_RISK_DENIED)"\n(SUDO_RISK_DENIED)\n'}
        assert self._hint(forged) is None

    def test_closing_period_is_required(self):
        # Every emitter ends the line with a period; requiring it narrows what a
        # command's own output can forge.
        out = {'result': 'Alpacon denied this sudo command (SUDO_RISK_DENIED)\n'}
        assert self._hint(out) is None

    def test_matches_when_appended_to_a_partial_line(self):
        # The plugin writes to stderr, so the denial lands mid-line whenever the
        # command's own output left no trailing newline. Anchoring to a line
        # start would drop a real denial here—the failure this mapping exists to
        # prevent.
        out = {
            'result': 'writing...Alpacon denied this sudo command (SUDO_RISK_DENIED).\n'
        }
        assert self._hint(out) is not None

    @pytest.mark.parametrize(
        'code', ['SUDO_SESSION_MISSING', 'SUDO_NO_WORKSESSION_POLICY']
    )
    def test_invocation_wording_is_matched(self, code):
        # pam_sm_authenticate's hard-deny path says "invocation", not "command",
        # and is scoped to the deploy shell execute_command produces. Matching
        # only the "command" wording lost that denial's hint entirely.
        out = {'result': f'Alpacon denied this sudo invocation ({code}).\n'}
        assert self._hint(out) is not None


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.command_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestSubmitCommand:
    """Test _submit_command internal helper."""

    @pytest.mark.asyncio
    async def test_submit_basic(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-123', 'status': 'running'}

        result = await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls -la',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        assert result['id'] == 'cmd-123'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': '550e8400-e29b-41d4-a716-446655440001',
                'shell': 'system',
                'line': 'ls -la',
                'groupname': 'alpacon',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_with_optional_params(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-456'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='echo done',
            workspace='testworkspace',
            username='testuser',
            env={'PATH': '/usr/bin'},
            run_after=['cmd-100'],
            scheduled_at='2026-04-03T03:00:00Z',
            data='stdin input',
            region='ap1',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['username'] == 'testuser'
        assert call_data['env'] == {'PATH': '/usr/bin'}
        assert call_data['run_after'] == ['cmd-100']
        assert call_data['scheduled_at'] == '2026-04-03T03:00:00Z'
        assert call_data['data'] == 'stdin input'

    @pytest.mark.asyncio
    async def test_submit_omits_none_params(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-789'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert 'username' not in call_data
        assert 'run_after' not in call_data
        assert 'scheduled_at' not in call_data
        assert 'data' not in call_data

    @pytest.mark.asyncio
    async def test_submit_uses_env_work_session_when_unset(
        self, mock_http_client, monkeypatch
    ):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'ws-from-env')
        mock_http_client.post.return_value = {'id': 'cmd-env'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['work_session'] == 'ws-from-env'

    @pytest.mark.asyncio
    async def test_submit_explicit_work_session_wins_over_env(
        self, mock_http_client, monkeypatch
    ):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'ws-from-env')
        mock_http_client.post.return_value = {'id': 'cmd-explicit'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            work_session_id='explicit-ws',
            region='ap1',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['work_session'] == 'explicit-ws'


class TestListCommands:
    """Test list_commands function."""

    @pytest.mark.asyncio
    async def test_list_commands_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'cmd-123', 'command': 'ls -la', 'status': 'completed'},
                {'id': 'cmd-124', 'command': 'ps aux', 'status': 'running'},
            ],
        }

        result = await list_commands(workspace='testworkspace', limit=10, region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            params={'page_size': 10, 'ordering': '-added_at'},
        )

    @pytest.mark.asyncio
    async def test_list_commands_with_server_filter(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'count': 1, 'results': []}

        result = await list_commands(
            workspace='testworkspace',
            server_id='550e8400-e29b-41d4-a716-446655440001',
        )

        assert result['status'] == 'success'
        call_args = mock_http_client.get.call_args
        assert (
            call_args[1]['params']['server'] == '550e8400-e29b-41d4-a716-446655440001'
        )

    @pytest.mark.asyncio
    async def test_list_commands_no_token(self, mock_http_client, mock_token_manager):
        mock_token_manager.get_token.return_value = None

        result = await list_commands(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']

    @pytest.mark.asyncio
    async def test_list_commands_http_error(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {
            'error': 'Forbidden',
            'message': 'Permission denied',
            'status_code': HTTPStatus.FORBIDDEN,
        }

        result = await list_commands(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert 'Permission denied' in result['message']


class TestListCommandsSudoDenialAnnotation:
    """execute_command_multi_server only submits, so denials surface only here."""

    @staticmethod
    def _denied(command_id: str, code: str) -> dict:
        return {
            'id': command_id,
            'result': f'Alpacon denied this sudo command ({code}).\n',
        }

    @pytest.mark.asyncio
    async def test_annotates_entry_with_hint(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [self._denied('cmd-1', 'SUDO_RISK_DENIED')],
        }

        result = await list_commands(workspace='testworkspace')

        entry = result['data']['results'][0]
        assert 'risk' in entry['sudo_hint']
        assert 'sudo_denial' not in entry

    @pytest.mark.asyncio
    async def test_annotates_entry_with_pending_block(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [self._denied('cmd-2', 'SUDO_APPROVAL_REQUIRED')],
        }

        result = await list_commands(workspace='testworkspace')

        entry = result['data']['results'][0]
        assert entry['sudo_denial']['status'] == 'pending_approval'
        assert entry['sudo_denial']['category'] == 'SUDO_APPROVAL_REQUIRED'

    @pytest.mark.asyncio
    async def test_only_denied_entries_are_annotated(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'cmd-3', 'result': 'uid=0(root)\n'},
                self._denied('cmd-4', 'SUDO_PRESENCE_REQUIRED'),
            ],
        }

        result = await list_commands(workspace='testworkspace')

        clean, denied = result['data']['results']
        assert 'sudo_hint' not in clean
        assert denied['sudo_denial']['category'] == 'SUDO_PRESENCE_REQUIRED'

    @pytest.mark.asyncio
    async def test_non_list_results_are_tolerated(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'detail': 'no results key'}

        result = await list_commands(workspace='testworkspace')

        assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_non_dict_entry_is_skipped(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 2,
            'results': ['unexpected', self._denied('cmd-5', 'SUDO_RISK_DENIED')],
        }

        result = await list_commands(workspace='testworkspace')

        assert result['status'] == 'success'
        assert 'sudo_hint' in result['data']['results'][1]


class TestExecuteCommand:
    """Test execute_command function (renamed from execute_command_sync)."""

    @pytest.mark.asyncio
    async def test_success(self, mock_http_client, mock_token_manager):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-123'}
            # Real Command API shape: handled_at signals completion, no 'finished_at'.
            mock_poll.return_value = {
                'id': 'cmd-123',
                'status': 'success',
                'success': True,
                'exit_code': 0,
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert result['command_id'] == 'cmd-123'
            assert result['command'] == 'echo test'

    @pytest.mark.asyncio
    async def test_completes_after_polling(self, mock_http_client, mock_token_manager):
        # The exact path the bug broke: first poll is still in-progress
        # (handled_at=None), a later poll reports handled_at set. Detection
        # must recognize completion on the transition, not only the first poll.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-123'}
            mock_poll.side_effect = [
                {'id': 'cmd-123', 'status': 'running', 'handled_at': None},
                {'id': 'cmd-123', 'status': 'verifying', 'handled_at': None},
                {
                    'id': 'cmd-123',
                    'status': 'success',
                    'success': True,
                    'exit_code': 0,
                    'handled_at': '2024-01-01T00:00:03Z',
                },
            ]

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert result['command_id'] == 'cmd-123'
            assert mock_poll.call_count == 3

    @pytest.mark.asyncio
    async def test_array_response(self, mock_http_client, mock_token_manager):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = [{'id': 'cmd-123'}]
            mock_poll.return_value = {
                'id': 'cmd-123',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
            )

            assert result['status'] == 'success'
            assert result['command_id'] == 'cmd-123'

    @pytest.mark.asyncio
    async def test_timeout(self, mock_http_client, mock_token_manager):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-123'}
            mock_poll.return_value = {
                'id': 'cmd-123',
                'status': 'running',
                'handled_at': None,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sleep 100',
                workspace='testworkspace',
                timeout=1,
            )

            assert result['status'] == 'error'
            assert result['error_type'] == 'timeout'
            assert 'timed out' in result['message']

    @pytest.mark.asyncio
    async def test_acl_error(self, mock_http_client, mock_token_manager):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {
                'error': 'Permission denied',
                'message': 'Permission denied',
                'status_code': HTTPStatus.FORBIDDEN,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls',
                workspace='testworkspace',
            )

            assert result['status'] == 'error'
            assert 'Permission denied' in result['message']

    @pytest.mark.asyncio
    async def test_empty_data_array(self, mock_http_client, mock_token_manager):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = []

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
            )

            assert result['status'] == 'error'
            assert 'No command data returned' in result['message']

    @pytest.mark.asyncio
    async def test_failed_command_completes(self, mock_http_client, mock_token_manager):
        # A non-zero exit is a completed command ('failed'), not still-running.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-400'}
            mock_poll.return_value = {
                'id': 'cmd-400',
                'status': 'failed',
                'success': False,
                'exit_code': 2,
                'result': 'ls: cannot access',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls /nope',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert result['data']['exit_code'] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize('status', ['stuck', 'denied', 'rejected'])
    async def test_terminal_failure_status(
        self, status, mock_http_client, mock_token_manager
    ):
        # Terminal non-approval statuses: the command will not produce a result,
        # so error out immediately instead of polling until timeout.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-401'}
            mock_poll.return_value = {
                'id': 'cmd-401',
                'status': status,
                'handled_at': None,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='rm -rf /',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'error'
            assert status in result['message']

    @pytest.mark.asyncio
    async def test_awaiting_approval_returns_pending(
        self, mock_http_client, mock_token_manager
    ):
        # HITL verification: a human must approve out-of-band (ADR 0015), so
        # return a structured pending result instead of burning the poll window.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-402'}
            mock_poll.return_value = {
                'id': 'cmd-402',
                'status': 'awaiting_approval',
                'handled_at': None,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sudo reboot',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'pending_approval'
            assert result['category'] == 'COMMAND_AWAITING_APPROVAL'
            assert result['requires_human_approval'] is True
            assert result['command_id'] == 'cmd-402'
            # Category has a registered next_action (not the generic fallback).
            assert 'list_commands' in result['next_action']

    @pytest.mark.asyncio
    async def test_forwards_all_params(self, mock_http_client, mock_token_manager):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-200'}
            mock_poll.return_value = {
                'id': 'cmd-200',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='echo test',
                workspace='testworkspace',
                run_after=['cmd-100'],
                scheduled_at='2026-04-03T03:00:00Z',
                data='stdin input',
                timeout=10,
            )

            call_kwargs = mock_submit.call_args[1]
            assert call_kwargs['run_after'] == ['cmd-100']
            assert call_kwargs['scheduled_at'] == '2026-04-03T03:00:00Z'
            assert call_kwargs['data'] == 'stdin input'

    @pytest.mark.asyncio
    async def test_no_token(self, mock_http_client, mock_token_manager):
        mock_token_manager.get_token.return_value = None

        result = await execute_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls -la',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']

    @pytest.mark.asyncio
    async def test_surfaces_sudo_hint_on_denial(
        self, mock_http_client, mock_token_manager
    ):
        # A finished command whose output carries a parenthesized denial code
        # must get a category-level sudo_hint attached to the response.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-789'}
            mock_poll.return_value = {
                'id': 'cmd-789',
                'status': 'failed',
                'success': False,
                'exit_code': 1,
                'result': 'Alpacon denied this sudo command '
                '(SUDO_PRESENCE_REQUIRED).\n',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sudo systemctl restart nginx',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert 'sudo_hint' in result
            assert 'step-up' in result['sudo_hint']
            # Disclosure guard: never echo a score/reasoning, only the category.
            assert 'score' not in result['sudo_hint']
            # Structured, machine-actionable pending-approval block (ADR 0015).
            assert result['sudo_denial']['status'] == 'pending_approval'
            assert result['sudo_denial']['category'] == 'SUDO_PRESENCE_REQUIRED'
            assert result['sudo_denial']['requires_human_approval'] is True
            assert result['sudo_denial']['approvable_by_agent'] is False

    @pytest.mark.asyncio
    async def test_approval_required_surfaces_structured_block(
        self, mock_http_client, mock_token_manager
    ):
        # SUDO_APPROVAL_REQUIRED is the ADR 0015 case: a human must approve
        # out-of-band, so a structured pending-approval block is attached.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-791'}
            mock_poll.return_value = {
                'id': 'cmd-791',
                'status': 'failed',
                'success': False,
                'exit_code': 1,
                'result': 'Alpacon denied this sudo command '
                '(SUDO_APPROVAL_REQUIRED).\n',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sudo systemctl restart nginx',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['sudo_denial']['category'] == 'SUDO_APPROVAL_REQUIRED'
            assert result['sudo_denial']['approvable_by_agent'] is False

    @pytest.mark.asyncio
    async def test_risk_denied_has_hint_but_no_pending_block(
        self, mock_http_client, mock_token_manager
    ):
        # A hard risk denial is not a pending human approval: it gets the
        # free-text hint but no machine-actionable pending-approval block, so an
        # agent does not wait for an approval that will never come.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-792'}
            mock_poll.return_value = {
                'id': 'cmd-792',
                'status': 'failed',
                'success': False,
                'exit_code': 1,
                'result': 'Alpacon denied this sudo command (SUDO_RISK_DENIED).\n',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sudo rm -rf /',
                workspace='testworkspace',
                timeout=10,
            )

            assert 'sudo_hint' in result
            assert 'sudo_denial' not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'code',
        [
            'SUDO_POLICY_MFA_REQUIRED',
            'SUDO_INTENT_DEVIATION',
            'WORK_SESSION_SCOPE_NOT_ALLOWED',
        ],
    )
    async def test_human_resolvable_codes_surface_structured_block(
        self, code, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-800'}
            mock_poll.return_value = {
                'id': 'cmd-800',
                'status': 'failed',
                'success': False,
                'exit_code': 1,
                'result': f'Alpacon denied this sudo command ({code}).\n',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sudo systemctl restart nginx',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['sudo_denial']['category'] == code
            assert result['sudo_denial']['approvable_by_agent'] is False
            assert result['sudo_denial']['next_action']

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'code',
        [
            'SUDO_COMMAND_NOT_AUTHORIZED',
            'WORKSPACE_SUDO_WITH_MFA_DISABLED',
            'SUDO_SESSION_MISSING',
            'SUDO_NO_AUTHORITY',
        ],
    )
    async def test_hard_denial_codes_have_hint_but_no_pending_block(
        self, code, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-801'}
            mock_poll.return_value = {
                'id': 'cmd-801',
                'status': 'failed',
                'success': False,
                'exit_code': 1,
                'result': f'Alpacon denied this sudo command ({code}).\n',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='sudo id',
                workspace='testworkspace',
                timeout=10,
            )

            assert 'sudo_hint' in result
            assert 'sudo_denial' not in result

    def test_sudo_denial_returns_code_and_hint(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_APPROVAL_REQUIRED).\n'}
        denial = _sudo_denial(out)
        assert denial is not None
        code, hint = denial
        assert code == 'SUDO_APPROVAL_REQUIRED'
        assert 'approv' in hint
        assert _sudo_denial({'result': 'uid=0(root)\n'}) is None

    @pytest.mark.asyncio
    async def test_no_sudo_hint_when_no_denial(
        self, mock_http_client, mock_token_manager
    ):
        # A clean command must not carry a sudo_hint field.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-790'}
            mock_poll.return_value = {
                'id': 'cmd-790',
                'status': 'success',
                'success': True,
                'exit_code': 0,
                'result': 'uid=0(root)\n',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='id',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert 'sudo_hint' not in result
            assert 'sudo_denial' not in result


class TestSubmitCommandWithSession:
    """Test _submit_command forwards work_session to API payload."""

    @pytest.mark.asyncio
    async def test_submit_includes_work_session_when_provided(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-ws-001'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            work_session_id='ws-uuid-abcd',
            region='ap1',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['work_session'] == 'ws-uuid-abcd'

    @pytest.mark.asyncio
    async def test_submit_omits_work_session_when_none(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-ws-002'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert 'work_session' not in call_data


class TestExecuteCommandWithSession:
    @pytest.mark.asyncio
    async def test_execute_command_passes_session_id(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'cmd-123'}
        mock_http_client.get.return_value = {
            'id': 'cmd-123',
            'handled_at': '2026-05-19T10:00:00Z',
            'status': 'success',
        }

        await execute_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='ls',
            workspace='testworkspace',
            work_session_id='ws-uuid-abcd',
            region='ap1',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['work_session'] == 'ws-uuid-abcd'


class TestExecuteCommandMultiServerWithSession:
    @pytest.mark.asyncio
    async def test_multi_server_passes_session_id(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'cmd-multi-1'}

        await execute_command_multi_server(
            server_ids=['550e8400-e29b-41d4-a716-446655440001'],
            command='ls',
            workspace='testworkspace',
            work_session_id='ws-uuid-abcd',
            region='ap1',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['work_session'] == 'ws-uuid-abcd'


class TestExecuteCommandGateTranslation:
    """Gate-code envelopes from _submit_command must be translated through unwrap_http_result."""

    @pytest.mark.asyncio
    async def test_work_session_required_is_translated(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = _GATE_ENVELOPE_REQUIRED

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls',
                workspace='testworkspace',
                region='ap1',
            )

        assert result.get('code') == 'work_session_required'
        assert 'next_action' in result

    @pytest.mark.asyncio
    async def test_work_session_not_active_becomes_pending_approval(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = _GATE_ENVELOPE_NOT_ACTIVE

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls',
                workspace='testworkspace',
                region='ap1',
            )

        assert result.get('status') == 'pending_approval'

    @pytest.mark.asyncio
    async def test_gate_response_does_not_leak_raw_envelope(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = _GATE_ENVELOPE_REQUIRED

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls',
                workspace='testworkspace',
                region='ap1',
            )

        assert 'response' not in result
        assert 'details' not in result


class TestExecuteCommandMultiServerGateTranslation:
    """Per-server gate envelopes must be translated in multi-server execution."""

    @pytest.mark.asyncio
    async def test_work_session_required_translated_in_parallel(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _GATE_ENVELOPE_REQUIRED

        result = await execute_command_multi_server(
            server_ids=['550e8400-e29b-41d4-a716-446655440001'],
            command='ls',
            workspace='testworkspace',
            region='ap1',
        )

        sid = '550e8400-e29b-41d4-a716-446655440001'
        server_entry = result['deploy_shell_results'][sid]
        assert server_entry.get('code') == 'work_session_required'
        assert 'next_action' in server_entry


class TestSudoGuidanceInToolDescriptions:
    """MCP prompts are opt-in—clients that read only tool schemas (Codex) must
    still learn that an unneeded sudo prefix blocks the session on a human.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'tool_name', ['execute_command', 'execute_command_multi_server']
    )
    async def test_description_states_the_sudo_cost(self, tool_name):
        descriptions = {t.name: t.description for t in await mcp.list_tools()}
        text = descriptions[tool_name]
        assert 'Do not prefix the command with sudo by default' in text
        assert 'human-in-the-loop' in text
        # The carve-out and the hard-denial path are the reason the rule is
        # qualified rather than absolute; pin both so neither regresses.
        assert 'sudo policy already covers' in text
        assert 'denied outright' in text
        assert 'sudo_denial.category' in text


def test_no_worksession_policy_hint_names_the_request_tool():
    """The hint must not claim a policy cannot be asked for through MCP anymore."""
    hint = _SUDO_DENIAL_HINTS['SUDO_NO_WORKSESSION_POLICY']

    assert 'request_sudo_policy' in hint
    assert 'no MCP tool' not in hint
    assert 'approve' in hint


def test_no_worksession_policy_next_action_names_the_request_tool():
    """The structured next action carries the same route as the hint."""
    next_action = _NEXT_ACTION_BY_CATEGORY['SUDO_NO_WORKSESSION_POLICY']

    assert 'request_sudo_policy' in next_action


class TestPurposeDemand:
    """The client half of the ADR 0052 purpose gate."""

    @pytest.mark.asyncio
    async def test_execute_command_declares_demand_support(
        self, mock_http_client, mock_token_manager
    ):
        # The gate arms only for a client that declares it answers. Without
        # this field the server feature is unreachable from MCP.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-500'}
            mock_poll.return_value = {
                'id': 'cmd-500',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls -la',
                workspace='testworkspace',
                timeout=10,
            )

        assert mock_submit.call_args.kwargs['purpose_demand_supported'] is True

    @pytest.mark.asyncio
    async def test_multi_server_does_not_declare_demand_support(
        self, mock_http_client, mock_token_manager
    ):
        # Nothing waits on a fleet submission, so a demand would park every
        # command for the deadline with no one to answer it.
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {'id': 'cmd-501'}

            await execute_command_multi_server(
                server_ids=['550e8400-e29b-41d4-a716-446655440001'],
                command='uptime',
                workspace='testworkspace',
                purpose='Confirm the reboot window actually took.',
            )

        assert mock_submit.call_args.kwargs.get('purpose_demand_supported') is None
        assert (
            mock_submit.call_args.kwargs['purpose']
            == 'Confirm the reboot window actually took.'
        )

    @pytest.mark.asyncio
    async def test_submit_sends_purpose_and_capability(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-502'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='systemctl restart chronyd',
            workspace='testworkspace',
            purpose='The host clock is 40s ahead, so the cert reads as not-yet-valid.',
            purpose_demand_supported=True,
            region='ap1',
            token='test-token',
        )

        sent = mock_http_client.post.call_args.kwargs['data']
        assert sent['purpose'] == (
            'The host clock is 40s ahead, so the cert reads as not-yet-valid.'
        )
        assert sent['purpose_demand_supported'] is True

    @pytest.mark.asyncio
    async def test_submit_truncates_purpose_to_the_server_ceiling(
        self, mock_http_client
    ):
        # A purpose over the ceiling is a 400, and a 400 costs the command its
        # one demand—so trim rather than let the server refuse.
        mock_http_client.post.return_value = {'id': 'cmd-503'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='true',
            workspace='testworkspace',
            purpose='x' * (PURPOSE_MAX_LENGTH + 500),
            region='ap1',
            token='test-token',
        )

        sent = mock_http_client.post.call_args.kwargs['data']
        assert len(sent['purpose']) == PURPOSE_MAX_LENGTH

    @pytest.mark.asyncio
    async def test_submit_treats_a_blank_purpose_as_unstated(self, mock_http_client):
        # Whitespace is truthy, so without a strip this reaches the server as a
        # purpose, earns a 400, and the 400 spends the command's one demand. The
        # arming check reads absence, so it has to be an absent field.
        mock_http_client.post.return_value = {'id': 'cmd-509'}

        await _submit_command(
            server_id='550e8400-e29b-41d4-a716-446655440001',
            command='true',
            workspace='testworkspace',
            purpose='   \n\t ',
            purpose_demand_supported=True,
            region='ap1',
            token='test-token',
        )

        sent = mock_http_client.post.call_args.kwargs['data']
        assert 'purpose' not in sent
        assert sent['purpose_demand_supported'] is True

    @pytest.mark.asyncio
    async def test_state_purpose_omits_metadata_it_was_never_given(
        self, mock_http_client, mock_token_manager
    ):
        # This caller knows neither the server nor the command line. An empty
        # string reads as a real value, so the keys must be absent instead.
        with (
            patch('tools.command_tools._answer_purpose_demand') as mock_answer,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_answer.return_value = {'status': 'success', 'status_code': 202}
            mock_poll.return_value = {
                'id': 'cmd-510',
                'status': 'success',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            result = await state_command_purpose(
                command_id='cmd-510',
                purpose='chronyd drifted 40s.',
                workspace='testworkspace',
                timeout=10,
            )

        assert 'server_id' not in result
        assert 'command' not in result
        assert 'shell' not in result
        # The polled row carries both anyway, which is why dropping the echo
        # loses the caller nothing.
        assert result['data']['id'] == 'cmd-510'

    @pytest.mark.asyncio
    async def test_execute_command_still_echoes_what_it_knows(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-511'}
            mock_poll.return_value = {
                'id': 'cmd-511',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='ls -la',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440001'
        assert result['command'] == 'ls -la'
        assert result['shell'] == 'system'

    @pytest.mark.asyncio
    async def test_awaiting_purpose_is_the_agents_move_not_a_humans(
        self, mock_http_client, mock_token_manager
    ):
        # No ApprovalRequest exists while the demand is open, so an agent that
        # reads this as "wait for a human" strands a command nobody was asked
        # about. The flags must say the opposite of the approval shape.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-504'}
            mock_poll.return_value = {
                'id': 'cmd-504',
                'status': 'awaiting_purpose',
                'handled_at': None,
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='bash /tmp/rotate.sh',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'purpose_required'
        assert result['category'] == 'COMMAND_PURPOSE_REQUIRED'
        assert result['requires_human_approval'] is False
        assert result['answerable_by_agent'] is True
        assert result['command_id'] == 'cmd-504'
        assert 'state_command_purpose' in result['next_action']
        # No timestamp on this row, so no deadline is invented for it.
        assert 'deadline_seconds' not in result

    @pytest.mark.asyncio
    async def test_awaiting_purpose_returns_without_burning_the_window(
        self, mock_http_client, mock_token_manager
    ):
        # One poll, then out. Sleeping through a 60s demand spends the only
        # chance the command gets to be explained.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-505'}
            mock_poll.return_value = {
                'id': 'cmd-505',
                'status': 'awaiting_purpose',
                'handled_at': None,
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='bash /tmp/rotate.sh',
                workspace='testworkspace',
                timeout=10,
            )

        assert mock_poll.call_count == 1

    @pytest.mark.asyncio
    async def test_state_purpose_answers_then_waits_for_the_rejudgment(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._answer_purpose_demand') as mock_answer,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_answer.return_value = {'status': 'success', 'status_code': 202}
            mock_poll.return_value = {
                'id': 'cmd-506',
                'status': 'success',
                'handled_at': '2026-04-03T03:00:01Z',
                'result': 'ok',
            }

            result = await state_command_purpose(
                command_id='cmd-506',
                purpose='chronyd drifted 40s, so the renewed cert reads as future-dated.',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'success'
        assert mock_answer.call_args.kwargs['command_id'] == 'cmd-506'
        # The wait after the answer is the same wait a never-parked command gets.
        assert mock_poll.call_count == 1

    @pytest.mark.asyncio
    async def test_state_purpose_rejects_a_blank_answer_before_spending_the_demand(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._answer_purpose_demand') as mock_answer:
            result = await state_command_purpose(
                command_id='cmd-507',
                purpose='   ',
                workspace='testworkspace',
            )

        assert result['status'] == 'error'
        mock_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_purpose_refusal_does_not_tell_the_agent_to_resubmit(
        self, mock_http_client, mock_token_manager
    ):
        # A settled command and a bystander's answer share one error code, so
        # the guidance cannot claim which happened—and must not send the agent
        # into a resubmission, which needs its own approval and may run twice.
        with (
            patch('tools.command_tools._answer_purpose_demand') as mock_answer,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_answer.return_value = {
                'error': 'HTTP Error',
                'status_code': HTTPStatus.BAD_REQUEST,
                'response': '{"code":"command_purpose_not_demanded"}',
            }

            result = await state_command_purpose(
                command_id='cmd-508',
                purpose='Too late.',
                workspace='testworkspace',
            )

        assert result['status'] == 'error'
        assert 'Do not resubmit' in result['message']
        mock_poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_descriptions_teach_the_demand(self):
        descriptions = {t.name: t.description for t in await mcp.list_tools()}

        exec_text = descriptions['execute_command']
        assert 'purpose_required' in exec_text
        assert 'state_command_purpose' in exec_text
        # What makes a purpose useful, not just that the field exists.
        assert 'local to this host' in exec_text

        answer_text = descriptions['state_command_purpose']
        assert 'one demand per command' in answer_text
        assert 'cannot lower' in answer_text


class TestPurposeDemandWindow:
    """What the response says about how long is left."""

    @staticmethod
    def _parked(requested_at: str | None) -> dict[str, Any]:
        row: dict[str, Any] = {
            'id': 'cmd-600',
            'status': 'awaiting_purpose',
            'handled_at': None,
        }
        if requested_at is not None:
            row['purpose_requested_at'] = requested_at
        return row

    async def _demand(self, row: dict[str, Any]) -> dict[str, Any]:
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-600'}
            mock_poll.return_value = row
            return await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='bash /tmp/rotate.sh',
                workspace='testworkspace',
                timeout=10,
            )

    @pytest.mark.asyncio
    async def test_the_window_counts_from_the_servers_timestamp(
        self, mock_http_client, mock_token_manager
    ):
        # Half the window already gone. Reporting a flat 60 is the error the
        # timestamp exists to remove.
        opened = datetime.now(UTC) - timedelta(seconds=PURPOSE_DEADLINE_SECONDS // 2)
        result = await self._demand(self._parked(opened.isoformat()))

        assert abs(result['deadline_seconds'] - PURPOSE_DEADLINE_SECONDS // 2) <= 2

    @pytest.mark.asyncio
    async def test_an_elapsed_window_reports_zero_not_a_negative(
        self, mock_http_client, mock_token_manager
    ):
        opened = datetime.now(UTC) - timedelta(hours=1)
        result = await self._demand(self._parked(opened.isoformat()))

        assert result['deadline_seconds'] == 0

    @pytest.mark.asyncio
    async def test_no_timestamp_means_no_deadline_rather_than_a_guess(
        self, mock_http_client, mock_token_manager
    ):
        # COMMAND_PURPOSE_DEADLINE is env-overridable, so a hard-coded 60 would
        # be a deadline that does not exist on a workspace which raised it.
        result = await self._demand(self._parked(None))

        assert 'deadline_seconds' not in result

    @pytest.mark.asyncio
    async def test_an_unparseable_timestamp_is_not_a_crash(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._demand(self._parked('not-a-timestamp'))

        assert result['status'] == 'purpose_required'
        assert 'deadline_seconds' not in result


class TestPurposeDemandHonesty:
    """The declaration and the trimming both have to be true when made."""

    @pytest.mark.asyncio
    async def test_a_scheduled_command_does_not_declare_support(
        self, mock_http_client, mock_token_manager
    ):
        # Verification runs at delivery, not submission
        # (`Command.execute_all_scheduled` filters `scheduled_at__lte=now`), so
        # this call is long gone by the time a demand could open. Declaring
        # support would park the command for the full deadline with nobody left
        # to answer, then drop it into the human queue.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-601'}
            mock_poll.return_value = {
                'id': 'cmd-601',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='uptime',
                workspace='testworkspace',
                scheduled_at='2099-01-01T00:00:00Z',
                timeout=10,
            )

        assert mock_submit.call_args.kwargs['purpose_demand_supported'] is False

    @pytest.mark.asyncio
    async def test_a_run_after_chain_does_not_declare_support(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-602'}
            mock_poll.return_value = {
                'id': 'cmd-602',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='uptime',
                workspace='testworkspace',
                run_after=['cmd-100'],
                timeout=10,
            )

        assert mock_submit.call_args.kwargs['purpose_demand_supported'] is False

    @pytest.mark.asyncio
    async def test_execute_command_forwards_the_stated_purpose(
        self, mock_http_client, mock_token_manager
    ):
        # The capability flag was pinned; the value itself was not, so the
        # wiring could have broken silently.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-603'}
            mock_poll.return_value = {
                'id': 'cmd-603',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='systemctl restart chronyd',
                workspace='testworkspace',
                purpose='The host clock is 40s ahead of the cert window.',
                timeout=10,
            )

        assert (
            mock_submit.call_args.kwargs['purpose']
            == 'The host clock is 40s ahead of the cert window.'
        )

    @pytest.mark.asyncio
    async def test_a_trimmed_purpose_is_reported_as_trimmed(
        self, mock_http_client, mock_token_manager
    ):
        # The assessor judges what was sent. A caller that is not told its
        # sentence was cut reads a verdict on words it did not write.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-604'}
            mock_poll.return_value = {
                'id': 'cmd-604',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='true',
                workspace='testworkspace',
                purpose='x' * (PURPOSE_MAX_LENGTH + 1),
                timeout=10,
            )

        assert result['purpose_truncated'] is True

    @pytest.mark.asyncio
    async def test_a_purpose_within_the_ceiling_is_not_flagged(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-605'}
            mock_poll.return_value = {
                'id': 'cmd-605',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            result = await execute_command(
                server_id='550e8400-e29b-41d4-a716-446655440001',
                command='true',
                workspace='testworkspace',
                purpose='short',
                timeout=10,
            )

        assert 'purpose_truncated' not in result

    @pytest.mark.asyncio
    async def test_the_answer_path_trims_the_same_way_the_submit_path_does(
        self, mock_http_client
    ):
        # Both write paths strip first, so leading whitespace never eats into
        # the 2000-character budget on one path and not the other.
        mock_http_client.post.return_value = {'status': 'success', 'status_code': 202}

        await _answer_purpose_demand(
            command_id='cmd-606',
            purpose='   ' + 'x' * (PURPOSE_MAX_LENGTH + 10),
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        sent = mock_http_client.post.call_args.kwargs['data']['purpose']
        assert len(sent) == PURPOSE_MAX_LENGTH
        assert not sent.startswith(' ')

    @pytest.mark.asyncio
    async def test_a_rejudgment_that_still_needs_a_human_says_so(
        self, mock_http_client, mock_token_manager
    ):
        # The tool description promises "an approval-pending result when a
        # human is still needed"; nothing held it to that.
        with (
            patch('tools.command_tools._answer_purpose_demand') as mock_answer,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_answer.return_value = {'status': 'success', 'status_code': 202}
            mock_poll.return_value = {
                'id': 'cmd-607',
                'status': 'awaiting_approval',
                'handled_at': None,
            }

            result = await state_command_purpose(
                command_id='cmd-607',
                purpose='chronyd drifted 40s.',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'pending_approval'
        assert result['requires_human_approval'] is True
