"""Unit tests for command tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.command_tools import (
    _submit_command,
    _sudo_denial,
    execute_command,
    execute_command_multi_server,
    list_commands,
)

_GATE_ENVELOPE_REQUIRED = {
    'error': 'HTTP Error',
    'status_code': 400,
    'response': '{"code":"work_session_required"}',
}

_GATE_ENVELOPE_NOT_ACTIVE = {
    'error': 'HTTP Error',
    'status_code': 400,
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
            'status_code': 403,
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
                'status_code': 403,
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
