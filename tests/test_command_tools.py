"""Unit tests for command tools module."""

import json
from collections.abc import Awaitable, Iterator
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Protocol
from unittest.mock import ANY, MagicMock, patch

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from server import mcp
from tests.conftest import (
    VALID_SERVER_ID,
    http_client_fixture,
    published_rule,
    tool_descriptions,
)
from tools.command_tools import (
    _COMMAND_DESCRIPTION,
    _FILE_PHASE_GENERIC_HINT,
    _FILE_PHASE_HINTS,
    _SUDO_DENIAL_HINTS,
    _SUDO_HUMAN_APPROVAL_CODES,
    DO_NOT_RESUBMIT,
    FILE_CONTENT_MAX_BYTES,
    FILE_REUSE_DAYS_MAX,
    FILE_REUSE_DAYS_MIN,
    PURPOSE_MAX_LENGTH,
    _answer_purpose_demand,
    _CommandRecord,
    _file_phase_hint,
    _get_capped,
    _submit_command,
    _submit_file_execution,
    _sudo_denial_codes,
    check_command_status,
    execute_command,
    execute_command_multi_server,
    execute_file,
    list_commands,
    state_command_purpose,
)
from utils.common import (
    _NEXT_ACTION_BY_CATEGORY,
    FILE_EXEC_INLINE_CREDENTIAL_HINT,
    FILE_EXEC_REFUSAL_HINTS,
    INLINE_CREDENTIAL_HINT,
    REFUSAL_GATE_HINT,
    pending_approval_response,
)
from utils.http_client import AlpaconHTTPClient
from utils.types import JsonValue, ToolResponse

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


_FILE_SCRIPT = '#!/bin/bash\nset -euo pipefail\necho deploy\n'

_FILE_EXEC_CODES = frozenset(
    {
        'file_exec_unsupported_agent',
        'file_exec_assessor_disabled',
        'file_exec_invalid_path',
        'file_exec_content_too_large',
        'file_exec_empty_content',
        'file_exec_line_too_long',
        'file_exec_invalid_reuse_days',
        'file_exec_reuse_exceeds_max',
    }
)

mock_http_client = http_client_fixture('tools.command_tools')


class TestSudoDenialHint:
    """The exec-sudo denial code -> agent guidance mapping."""

    @staticmethod
    def _hint(result: _CommandRecord) -> str | None:
        codes = _sudo_denial_codes(result)
        return _SUDO_DENIAL_HINTS[codes[0]] if codes else None

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
        # A policy matched, but it does not authorize sudo for the session.
        assert 'session-authorized sudo policy' in hint
        assert 'session_authorized' in hint
        assert 'Alpacon web console' in hint

    def test_intent_deviation(self):
        out = {'result': 'Alpacon denied this sudo command (SUDO_INTENT_DEVIATION).\n'}
        hint = self._hint(out)
        assert hint is not None
        # 'queue' keeps the restated-description path from reading as approval-free.
        assert 'work_session_update' in hint
        assert 'queue' in hint
        assert 'even for an admin' in hint
        assert 'advisory' in hint
        assert 'title' in hint

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
        assert 'even for an admin' in hint
        assert 'advisory' in hint
        assert 'title' in hint

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
        assert _sudo_denial_codes(out) == []

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


class TestSubmitCommand:
    @pytest.mark.asyncio
    async def test_submit_basic(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-123', 'status': 'running'}

        result = await _submit_command(
            server_id=VALID_SERVER_ID,
            command='ls -la',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        assert isinstance(result, dict)
        assert result['id'] == 'cmd-123'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls -la',
                'groupname': 'alpacon',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_with_optional_params(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-456'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
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

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'echo done',
                'groupname': 'alpacon',
                'env': {'PATH': '/usr/bin'},
                'data': 'stdin input',
                'username': 'testuser',
                'run_after': ['cmd-100'],
                'scheduled_at': '2026-04-03T03:00:00Z',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_omits_none_params(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-789'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_uses_env_work_session_when_unset(
        self, mock_http_client, monkeypatch
    ):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'ws-from-env')
        mock_http_client.post.return_value = {'id': 'cmd-env'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
                'work_session': 'ws-from-env',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_explicit_work_session_wins_over_env(
        self, mock_http_client, monkeypatch
    ):
        monkeypatch.setenv('ALPACON_WORK_SESSION', 'ws-from-env')
        mock_http_client.post.return_value = {'id': 'cmd-explicit'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            work_session_id='explicit-ws',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
                'work_session': 'explicit-ws',
            },
        )


class TestListCommands:
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
            server_id=VALID_SERVER_ID,
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            params={
                'page_size': 20,
                'ordering': '-added_at',
                'server': VALID_SERVER_ID,
            },
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


class TestFilePhaseHints:
    """A file-lane refusal's error_phase gets a hint instead of a bare code."""

    # The closed set of file-lane phases the server emits for an agent refusal.
    SERVER_PHASES = (
        'file_hash_mismatch',
        'file_payload_invalid',
        'file_open_failed',
        'file_exec_unsupported',
        'file_too_large',
    )

    def test_every_server_phase_has_a_specific_hint(self):
        assert set(self.SERVER_PHASES) == set(_FILE_PHASE_HINTS)
        for phase in self.SERVER_PHASES:
            hint = _file_phase_hint({'error_phase': phase})
            assert hint == _FILE_PHASE_HINTS[phase]
            assert hint != _FILE_PHASE_GENERIC_HINT

    def test_hash_mismatch_says_to_reverify(self):
        hint = _file_phase_hint({'error_phase': 'file_hash_mismatch'})
        assert hint is not None
        assert 'execute_file' in hint
        assert 'standing approval' in hint

    def test_unknown_file_phase_gets_generic_hint(self):
        hint = _file_phase_hint({'error_phase': 'file_something_new'})
        assert hint == _FILE_PHASE_GENERIC_HINT

    @pytest.mark.parametrize(
        'result',
        [
            {'error_phase': 'agent_timeout'},
            {'error_phase': 'remote_command_not_found'},
            {'error_phase': None},
            {'error_phase': 7},
            {},
        ],
    )
    def test_other_phases_are_unchanged(self, result):
        assert _file_phase_hint(result) is None

    @pytest.mark.asyncio
    async def test_execute_file_poll_attaches_hint(self, mock_token_manager):
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-f1'}
            mock_poll.return_value = {
                'id': 'cmd-f1',
                'status': 'failed',
                'success': False,
                'exit_code': 1,
                'error_phase': 'file_hash_mismatch',
                'result': 'FILE_HASH_MISMATCH: digest differs',
                'handled_at': '2024-01-01T00:00:01Z',
            }

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/run.sh',
                interpreter='/bin/bash',
                content='echo hi\n',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['error_phase_hint'] == _FILE_PHASE_HINTS['file_hash_mismatch']

    @pytest.mark.asyncio
    async def test_list_commands_annotates_file_entries_only(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'a', 'error_phase': 'file_open_failed'},
                {'id': 'b', 'error_phase': 'agent_timeout'},
            ],
        }

        result = await list_commands(workspace='testworkspace')

        first, second = result['data']['results']
        assert first['error_phase_hint'] == _FILE_PHASE_HINTS['file_open_failed']
        assert 'error_phase_hint' not in second


class TestListCommandsSudoDenialAnnotation:
    """execute_command_multi_server only submits, so denials surface only here."""

    @staticmethod
    def _denied(command_id: str, code: str) -> dict[str, str]:
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
                command='sleep 100',
                workspace='testworkspace',
                timeout=1,
            )

            assert result['status'] == 'error'
            assert result['error_type'] == 'timeout'
            assert 'timed out' in result['message']
            assert result['command_id'] == 'cmd-123'
            assert 'check_command_status' in result['next_action']
            assert 'resubmission runs it again' in result['next_action']

    @pytest.mark.asyncio
    async def test_a_stuck_command_times_out_instead_of_failing(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command', return_value={'id': 'cmd-st'}),
            patch(
                'tools.command_tools._get_command_result',
                return_value={'id': 'cmd-st', 'status': 'stuck', 'handled_at': None},
            ),
        ):
            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='sleep 900',
                workspace='testworkspace',
                timeout=1,
            )

        assert result['status'] == 'error'
        assert result['error_type'] == 'timeout'
        assert 'check_command_status' in result['next_action']

    @pytest.mark.asyncio
    async def test_acl_error(self, mock_http_client, mock_token_manager):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {
                'error': 'Permission denied',
                'message': 'Permission denied',
                'status_code': HTTPStatus.FORBIDDEN,
            }

            result = await execute_command(
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
                command='ls /nope',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert result['data']['exit_code'] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize('status', ['denied', 'rejected'])
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
                command='sudo reboot',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'pending_approval'
            assert result['category'] == 'COMMAND_AWAITING_APPROVAL'
            assert result['requires_human_approval'] is True
            assert result['command_id'] == 'cmd-402'
            # Category has a registered next_action (not the generic fallback).
            assert 'check_command_status' in result['next_action']

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
                server_id=VALID_SERVER_ID,
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
            server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
                command='sudo id',
                workspace='testworkspace',
                timeout=10,
            )

            assert 'sudo_hint' in result
            assert 'sudo_denial' not in result

    @pytest.mark.parametrize('doc', ['docs/examples.md', 'docs/troubleshooting.md'])
    def test_docs_name_every_human_resolvable_sudo_denial_category(self, doc):
        text = (Path(__file__).resolve().parent.parent / doc).read_text()

        missing = {
            code for code in _SUDO_HUMAN_APPROVAL_CODES if f'`{code}`' not in text
        }

        assert missing == set()

    def test_sudo_denial_codes_lists_known_codes_in_run_order(self):
        out = {
            'result': 'Alpacon denied this sudo command (SUDO_APPROVAL_REQUIRED).\n'
            'Alpacon denied this sudo command (SUDO_SOMETHING_NEW).\n'
            'Alpacon denied this sudo command (SUDO_RISK_DENIED).\n'
        }

        assert _sudo_denial_codes(out) == ['SUDO_APPROVAL_REQUIRED', 'SUDO_RISK_DENIED']
        assert _sudo_denial_codes({'result': 'uid=0(root)\n'}) == []

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
                server_id=VALID_SERVER_ID,
                command='id',
                workspace='testworkspace',
                timeout=10,
            )

            assert result['status'] == 'success'
            assert 'sudo_hint' not in result
            assert 'sudo_denial' not in result


class TestSubmitCommandWithSession:
    @pytest.mark.asyncio
    async def test_submit_includes_work_session_when_provided(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-ws-001'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            work_session_id='ws-uuid-abcd',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
                'work_session': 'ws-uuid-abcd',
            },
        )

    @pytest.mark.asyncio
    async def test_submit_omits_work_session_when_none(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-ws-002'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
            },
        )


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
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            work_session_id='ws-uuid-abcd',
            region='ap1',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
                'work_session': 'ws-uuid-abcd',
                'purpose_demand_supported': True,
            },
        )


class TestExecuteCommandMultiServerWithSession:
    @pytest.mark.asyncio
    async def test_multi_server_passes_session_id(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'cmd-multi-1'}

        await execute_command_multi_server(
            server_ids=[VALID_SERVER_ID],
            command='ls',
            workspace='testworkspace',
            work_session_id='ws-uuid-abcd',
            region='ap1',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'ls',
                'groupname': 'alpacon',
                'work_session': 'ws-uuid-abcd',
            },
        )


class TestExecuteCommandGateTranslation:
    """Gate-code envelopes from _submit_command must be translated through unwrap_http_result."""

    @pytest.mark.asyncio
    async def test_work_session_required_is_translated(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = _GATE_ENVELOPE_REQUIRED

            result = await execute_command(
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
                command='ls',
                workspace='testworkspace',
                region='ap1',
            )

        assert 'response' not in result
        assert 'details' not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'submitted', [{'id': 'cmd-multi-2'}, [{'id': 'cmd-multi-2'}]]
    )
    async def test_an_accepted_entry_carries_its_command_id(
        self, submitted, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = submitted

        result = await execute_command_multi_server(
            server_ids=[VALID_SERVER_ID], command='ls', workspace='testworkspace'
        )

        entry = result['deploy_shell_results'][VALID_SERVER_ID]
        assert result['status'] == 'success'
        assert entry == {
            'status': 'success',
            'data': submitted,
            'command_id': 'cmd-multi-2',
        }


class TestExecuteCommandMultiServerGateTranslation:
    """Per-server gate envelopes must be translated in multi-server execution."""

    @pytest.mark.asyncio
    async def test_work_session_required_translated_in_parallel(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _GATE_ENVELOPE_REQUIRED

        result = await execute_command_multi_server(
            server_ids=[VALID_SERVER_ID],
            command='ls',
            workspace='testworkspace',
            region='ap1',
        )

        server_entry = result['deploy_shell_results'][VALID_SERVER_ID]
        assert server_entry.get('code') == 'work_session_required'
        assert 'next_action' in server_entry


@pytest.fixture
async def lost_command_posts():
    """A real client whose every command POST loses its response; yields what was sent."""
    posts: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        posts.append(request)
        raise httpx.ReadTimeout('read timed out', request=request)

    client = AlpaconHTTPClient(transport=httpx.MockTransport(answer))
    client.retry_delay = 0
    with patch('tools.command_tools.http_client', client):
        yield posts
    await client.close()


class TestLostSubmissionIsNotResubmitted:
    """A command POST whose response was lost may have run; it is sent once."""

    @pytest.mark.asyncio
    async def test_execute_command_sends_once_and_points_at_list_commands(
        self, lost_command_posts, mock_token_manager
    ):
        result = await execute_command(
            server_id=VALID_SERVER_ID,
            command='rm -rf /tmp/x',
            workspace='testworkspace',
            region='ap1',
        )

        assert [r.method for r in lost_command_posts] == ['POST']
        assert result['status'] == 'error'
        assert result['outcome_unknown'] is True
        assert DO_NOT_RESUBMIT in result['message']
        assert 'list_commands' in result['message']
        assert 'raise limit until the oldest entry predates it' in result['message']
        assert 'if 100 newer ones fill the page, ask a human' in result['message']

    @pytest.mark.asyncio
    async def test_execute_file_sends_once_and_points_at_list_commands(
        self, lost_command_posts, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content='echo deploy\n',
            workspace='testworkspace',
            region='ap1',
        )

        assert [r.method for r in lost_command_posts] == ['POST']
        assert result['status'] == 'error'
        assert result['outcome_unknown'] is True
        assert DO_NOT_RESUBMIT in result['message']
        assert 'list_commands' in result['message']

    @pytest.mark.asyncio
    async def test_execute_file_lost_upload_is_not_resent_and_runs_nothing(
        self, lost_command_posts, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content='echo deploy\n',
            write_file=True,
            workspace='testworkspace',
            region='ap1',
        )

        assert [r.url.path for r in lost_command_posts] == ['/api/webftp/uploads/']
        assert result['status'] == 'error'
        assert result['outcome_unknown'] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize('parallel', [True, False])
    async def test_multi_server_marks_each_lost_submission(
        self, lost_command_posts, mock_token_manager, parallel
    ):
        other_server = '22222222-2222-2222-2222-222222222222'

        result = await execute_command_multi_server(
            server_ids=[VALID_SERVER_ID, other_server],
            command='ls',
            workspace='testworkspace',
            region='ap1',
            parallel=parallel,
        )

        sent_to = sorted(json.loads(r.content)['server'] for r in lost_command_posts)
        assert sent_to == sorted([VALID_SERVER_ID, other_server])
        assert result['failed_count'] == 2
        for entry in result['deploy_shell_results'].values():
            assert entry['outcome_unknown'] is True
            assert DO_NOT_RESUBMIT in entry['message']

    @pytest.mark.asyncio
    async def test_refused_submission_does_not_claim_the_command_may_have_run(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'Permission denied',
        }

        result = await execute_command(
            server_id=VALID_SERVER_ID,
            command='ls',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'outcome_unknown' not in result
        assert 'list_commands' not in result['message']


class TestSudoGuidanceInToolDescriptions:
    """MCP prompts are opt-in—clients that read only tool schemas (Codex) must
    still learn what a sudo inside a command does to it.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'tool_name', ['execute_command', 'execute_command_multi_server']
    )
    async def test_description_states_the_sudo_cost(self, tool_name):
        descriptions = await tool_descriptions()
        text = descriptions[tool_name]
        # The carve-out and both denial paths qualify the parameter's sudo rule;
        # pin them on the tool so neither regresses.
        assert 'sudo policy already covers' in text
        assert 'denied at once' in text
        assert 'sudo_denial' in text
        assert 'with no sudo_denial' in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'tool_name',
        ['execute_command', 'execute_command_multi_server', 'execute_file'],
    )
    async def test_description_does_not_promise_a_sudo_that_resumes(self, tool_name):
        # A denied sudo is over when the command finishes, so the agent reruns.
        text = (await tool_descriptions())[tool_name]

        assert 'until a human acts' not in text
        assert 'routes to human' not in text
        assert 'rerun' in text.lower()

    @pytest.mark.asyncio
    async def test_execute_file_names_the_status_it_returns(self):
        text = (await tool_descriptions())['execute_file']

        assert 'awaiting_approval' not in text
        assert 'status of pending_approval' in text
        assert 'COMMAND_AWAITING_APPROVAL' in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'tool_name', ['execute_command', 'execute_command_multi_server']
    )
    async def test_command_parameter_carries_the_sudo_rule(self, tool_name):
        # Given the published tool list
        tools = {t.name: t for t in await mcp.list_tools()}
        descriptions = await tool_descriptions()

        # When reading the command property
        command = tools[tool_name].input_schema['properties']['command']

        # Then the parameter carries the rule and the tool description does not
        assert command['description'] == _COMMAND_DESCRIPTION
        assert 'whitespace-only' in command['description']
        assert 'with sudo by default' in command['description']
        assert _COMMAND_DESCRIPTION not in descriptions[tool_name]
        assert 'with sudo by default' not in descriptions[tool_name]
        assert 'use sudo only when' not in descriptions[tool_name].lower()


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
                server_id=VALID_SERVER_ID,
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
                server_ids=[VALID_SERVER_ID],
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
            server_id=VALID_SERVER_ID,
            command='systemctl restart chronyd',
            workspace='testworkspace',
            purpose='The host clock is 40s ahead, so the cert reads as not-yet-valid.',
            purpose_demand_supported=True,
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'systemctl restart chronyd',
                'groupname': 'alpacon',
                'purpose': (
                    'The host clock is 40s ahead, so the cert reads as not-yet-valid.'
                ),
                'purpose_demand_supported': True,
            },
        )

    @pytest.mark.asyncio
    async def test_submit_truncates_purpose_to_the_server_ceiling(
        self, mock_http_client
    ):
        # A purpose over the ceiling is a 400, and a 400 costs the command its
        # one demand—so trim rather than let the server refuse.
        mock_http_client.post.return_value = {'id': 'cmd-503'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='true',
            workspace='testworkspace',
            purpose='x' * (PURPOSE_MAX_LENGTH + 500),
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'true',
                'groupname': 'alpacon',
                'purpose': 'x' * PURPOSE_MAX_LENGTH,
            },
        )

    @pytest.mark.asyncio
    async def test_submit_treats_a_blank_purpose_as_unstated(self, mock_http_client):
        # Whitespace is truthy, so without a strip this reaches the server as a
        # purpose, earns a 400, and the 400 spends the command's one demand. The
        # arming check reads absence, so it has to be an absent field.
        mock_http_client.post.return_value = {'id': 'cmd-509'}

        await _submit_command(
            server_id=VALID_SERVER_ID,
            command='true',
            workspace='testworkspace',
            purpose='   \n\t ',
            purpose_demand_supported=True,
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'shell': 'system',
                'line': 'true',
                'groupname': 'alpacon',
                'purpose_demand_supported': True,
            },
        )

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
                server_id=VALID_SERVER_ID,
                command='ls -la',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['server_id'] == VALID_SERVER_ID
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
        self, mock_http_client, mock_token_manager, make_client
    ):
        # A settled command and a bystander's answer share one error code, so
        # the guidance cannot claim which happened—and must not send the agent
        # into a resubmission, which needs its own approval and may run twice.
        refused = httpx.Response(
            HTTPStatus.BAD_REQUEST, json={'code': 'command_purpose_not_demanded'}
        )
        client = make_client(httpx.MockTransport(lambda _: refused))
        with (
            patch('tools.command_tools._answer_purpose_demand') as mock_answer,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_answer.return_value = await client.request(
                'POST', 'https://ws.ap1.alpacon.io/api/events/commands/cmd-508/purpose/'
            )

            result = await state_command_purpose(
                command_id='cmd-508',
                purpose='Too late.',
                workspace='testworkspace',
            )

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.BAD_REQUEST
        assert result['error_code'] == 'command_purpose_not_demanded'
        assert 'Do not resubmit' in result['message']
        assert 'check_command_status' in result['message']
        mock_poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_descriptions_teach_the_demand(self):
        descriptions = await tool_descriptions()

        exec_text = descriptions['execute_command']
        assert 'purpose_required' in exec_text
        assert 'state_command_purpose' in exec_text

        answer_text = descriptions['state_command_purpose']
        assert 'one demand per command' in answer_text

    @pytest.mark.asyncio
    async def test_purpose_parameters_teach_what_makes_a_purpose_useful(self):
        tools = {t.name: t for t in await mcp.list_tools()}

        for name in ('execute_command', 'state_command_purpose'):
            purpose = tools[name].input_schema['properties']['purpose']['description']
            assert 'local to this host' in purpose
            assert 'cannot lower' in purpose
            assert 'local to this host' not in (tools[name].description or '')


class TestPurposeDemandWindow:
    """What the response says about how long is left."""

    @staticmethod
    def _parked(expires_at: str | None) -> dict[str, JsonValue]:
        row: dict[str, JsonValue] = {
            'id': 'cmd-600',
            'status': 'awaiting_purpose',
            'handled_at': None,
        }
        if expires_at is not None:
            row['purpose_expires_at'] = expires_at
        return row

    async def _demand(self, row: dict[str, JsonValue]) -> ToolResponse:
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-600'}
            mock_poll.return_value = row
            return await execute_command(
                server_id=VALID_SERVER_ID,
                command='bash /tmp/rotate.sh',
                workspace='testworkspace',
                timeout=10,
            )

    @pytest.mark.asyncio
    async def test_the_window_measures_against_the_servers_expiry(
        self, mock_http_client, mock_token_manager
    ):
        # The server derives the expiry because the window's length is a
        # setting no endpoint publishes, so this client has no length to assume
        # and cannot be wrong about one.
        expiry = datetime.now(UTC) + timedelta(seconds=30)
        result = await self._demand(self._parked(expiry.isoformat()))

        assert abs(result['deadline_seconds'] - 30) <= 2
        assert result['deadline_at'] == expiry.isoformat()
        assert (
            f'If no purpose arrives by {expiry.isoformat()} '
            f'(about {result["deadline_seconds"]} s), the command is judged again '
            'without one: it runs, waits for a human approver (who is notified '
            'then), or is refused. Read the result with check_command_status; do not '
            'resubmit.'
        ) in result['message']

    @pytest.mark.asyncio
    async def test_an_elapsed_window_reports_zero_not_a_negative(
        self, mock_http_client, mock_token_manager
    ):
        expiry = datetime.now(UTC) - timedelta(hours=1)
        result = await self._demand(self._parked(expiry.isoformat()))

        assert result['deadline_seconds'] == 0
        assert result['deadline_at'] == expiry.isoformat()
        assert (
            f'If no purpose arrives by {expiry.isoformat()} (about 0 s), '
            'the command is judged again without one: it runs, waits for a '
            'human approver (who is notified then), or is refused. Read the '
            'result with check_command_status; do not resubmit.'
        ) in result['message']

    @pytest.mark.asyncio
    async def test_no_expiry_means_no_deadline_rather_than_a_guess(
        self, mock_http_client, mock_token_manager
    ):
        # Inventing one would publish a deadline that does not exist on a
        # workspace which raised COMMAND_PURPOSE_DEADLINE.
        result = await self._demand(self._parked(None))

        assert 'deadline_seconds' not in result
        assert 'deadline_at' not in result
        assert 'the command is judged again without one' in result['message']
        assert (
            'Read the result with check_command_status; do not resubmit.'
            in result['message']
        )

    @pytest.mark.asyncio
    async def test_an_unparseable_expiry_is_not_a_crash(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._demand(self._parked('not-a-timestamp'))

        assert result['status'] == 'purpose_required'
        assert 'deadline_seconds' not in result
        assert 'deadline_at' not in result


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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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
                server_id=VALID_SERVER_ID,
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

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/cmd-606/purpose/',
            token='test-token',
            data={'purpose': 'x' * PURPOSE_MAX_LENGTH},
        )

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

    @pytest.mark.asyncio
    async def test_the_fleet_tool_reports_its_own_truncation(
        self, mock_http_client, mock_token_manager
    ):
        # The flag is computed near the top and attached after the dispatch
        # loop, which is the shape most likely to come apart in a later edit.
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {'id': 'cmd-608'}

            result = await execute_command_multi_server(
                server_ids=[VALID_SERVER_ID],
                command='uptime',
                workspace='testworkspace',
                purpose='x' * (PURPOSE_MAX_LENGTH + 1),
            )

        assert result['purpose_truncated'] is True

    @pytest.mark.asyncio
    async def test_the_fleet_tool_does_not_flag_a_purpose_that_fits(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {'id': 'cmd-609'}

            result = await execute_command_multi_server(
                server_ids=[VALID_SERVER_ID],
                command='uptime',
                workspace='testworkspace',
                purpose='short',
            )

        assert 'purpose_truncated' not in result

    @pytest.mark.asyncio
    async def test_the_answer_path_reports_its_own_truncation(
        self, mock_http_client, mock_token_manager
    ):
        # This is the command's one chance and the verdict returns in the same
        # call, so a caller reading a denial has to know which sentence was
        # judged: the one it wrote, or the one that survived the cut.
        with (
            patch('tools.command_tools._answer_purpose_demand') as mock_answer,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_answer.return_value = {'status': 'success', 'status_code': 202}
            mock_poll.return_value = {
                'id': 'cmd-610',
                'status': 'success',
                'handled_at': '2026-04-03T03:00:01Z',
            }

            result = await state_command_purpose(
                command_id='cmd-610',
                purpose='x' * (PURPOSE_MAX_LENGTH + 1),
                workspace='testworkspace',
                timeout=10,
            )

        assert result['purpose_truncated'] is True


class TestEmptyCommandRejected:
    """A command that is empty or whitespace-only never reaches the API."""

    @pytest.mark.asyncio
    async def test_execute_command_empty_rejected(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='',
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert 'command' in result['message']
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_command_whitespace_rejected(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='  \n\t ',
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert 'command' in result['message']
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_server_empty_command_rejected(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_command_multi_server(
            server_ids=[VALID_SERVER_ID],
            command='',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'command' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_server_whitespace_command_rejected(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_command_multi_server(
            server_ids=[VALID_SERVER_ID],
            command='   ',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert 'command' in result['message']
        mock_http_client.post.assert_not_called()


def _file_exec_envelope(code: str) -> dict[str, JsonValue]:
    return {
        'error': 'HTTP Error',
        'status_code': HTTPStatus.BAD_REQUEST,
        'response': f'{{"code":"{code}"}}',
    }


class TestSubmitFileExecution:
    """The body the file lane (ADR 0053) puts on the wire."""

    @pytest.mark.asyncio
    async def test_body_selects_the_file_lane_and_names_nothing_else(
        self, mock_http_client
    ):
        mock_http_client.post.return_value = {'id': 'cmd-700'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            interpreter='/bin/bash',
            args=['--fast', ''],
            username='root',
            groupname='root',
            region='ap1',
            token='test-token',
        )

        # The server refuses line and data on key presence (an empty string
        # included) and a non-empty env, so the keys the other lane needs must
        # be absent here rather than blank; shell is the server's to set.
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'groupname': 'root',
                'file': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': ['--fast', ''],
                    'content': _FILE_SCRIPT,
                },
                'username': 'root',
            },
        )

    @pytest.mark.asyncio
    async def test_content_travels_byte_for_byte(self, mock_http_client):
        # Trailing newline, CRLF, tabs, trailing spaces, non-ASCII: every one
        # of these is bytes the on-disk file carries and the agent hashes.
        content = '#!/bin/sh\r\n\techo "héllo"   \r\n\n\n'
        mock_http_client.post.return_value = {'id': 'cmd-701'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=content,
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'groupname': 'alpacon',
                'file': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': [],
                    'content': content,
                },
            },
        )

    @pytest.mark.asyncio
    async def test_args_default_to_an_empty_list_and_interpreter_to_bash(
        self, mock_http_client
    ):
        mock_http_client.post.return_value = {'id': 'cmd-702'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'groupname': 'alpacon',
                'file': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': [],
                    'content': _FILE_SCRIPT,
                },
            },
        )

    @pytest.mark.asyncio
    async def test_requester_fields_ride_the_file_lane_unchanged(
        self, mock_http_client
    ):
        mock_http_client.post.return_value = {'id': 'cmd-703'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            run_after=['cmd-100'],
            scheduled_at='2026-09-10T03:00:00Z',
            work_session_id='ws-1',
            purpose='  The release tag moved; redeploy picks it up.  ',
            purpose_demand_supported=True,
            region='ap1',
            token='test-token',
        )

        # The same rules as the shell lane: a purpose is stripped and capped,
        # and the capability flag is sent only when asked for.
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'groupname': 'alpacon',
                'file': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': [],
                    'content': _FILE_SCRIPT,
                },
                'run_after': ['cmd-100'],
                'scheduled_at': '2026-09-10T03:00:00Z',
                'work_session': 'ws-1',
                'purpose': 'The release tag moved; redeploy picks it up.',
                'purpose_demand_supported': True,
            },
        )

    @pytest.mark.asyncio
    async def test_blank_purpose_is_unstated_on_the_file_lane_too(
        self, mock_http_client
    ):
        mock_http_client.post.return_value = {'id': 'cmd-704'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            purpose='   ',
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'groupname': 'alpacon',
                'file': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': [],
                    'content': _FILE_SCRIPT,
                },
            },
        )

    @pytest.mark.asyncio
    async def test_reuse_days_rides_inside_the_file_object(self, mock_http_client):
        mock_http_client.post.return_value = {'id': 'cmd-705'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            reuse_days=30,
            region='ap1',
            token='test-token',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            data={
                'server': VALID_SERVER_ID,
                'groupname': 'alpacon',
                'file': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': [],
                    'content': _FILE_SCRIPT,
                    'reuse_days': 30,
                },
            },
        )

    @pytest.mark.asyncio
    async def test_no_reuse_days_leaves_the_body_as_it_was(self, mock_http_client):
        # A server that predates the field never sees the key, and a run with no
        # proposal sends nothing rather than null.
        mock_http_client.post.return_value = {'id': 'cmd-706'}

        await _submit_file_execution(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            reuse_days=None,
            region='ap1',
            token='test-token',
        )

        sent = mock_http_client.post.call_args.kwargs['data']
        assert sent['file'] == {
            'path': '/opt/deploy.sh',
            'interpreter': '/bin/bash',
            'args': [],
            'content': _FILE_SCRIPT,
        }
        assert 'reuse_days' not in sent


class TestExecuteFileLocalValidation:
    """What execute_file refuses before spending a round trip."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'field, override',
        [
            ('path', {'path': 'opt/deploy.sh'}),
            ('interpreter', {'interpreter': 'bash'}),
            ('interpreter', {'interpreter': 'usr/bin/python3'}),
        ],
    )
    async def test_relative_path_or_interpreter_is_refused_locally(
        self, mock_http_client, mock_token_manager, field, override
    ):
        kwargs: dict[str, str] = {
            'path': '/opt/deploy.sh',
            'interpreter': '/bin/bash',
            **override,
        }

        result = await execute_file(
            server_id=VALID_SERVER_ID,
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            region='ap1',
            path=kwargs['path'],
            interpreter=kwargs['interpreter'],
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_exec_invalid_path'
        assert result['field'] == field
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_content_is_refused_locally(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content='',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_exec_empty_content'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_content_is_bytes_not_blank(
        self, mock_http_client, mock_token_manager
    ):
        # The shell lane treats a whitespace command as empty; this lane never
        # strips, so a newline is content the host file may well carry.
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _file_exec_envelope('file_exec_empty_content')

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content='\n',
                workspace='testworkspace',
                region='ap1',
            )

        assert mock_submit.call_args.kwargs['content'] == '\n'

    @pytest.mark.asyncio
    async def test_content_over_the_ceiling_is_refused_locally(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content='a' * (FILE_CONTENT_MAX_BYTES + 1),
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_exec_content_too_large'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ceiling_is_measured_in_utf8_bytes_not_characters(
        self, mock_http_client, mock_token_manager
    ):
        # 21846 three-byte characters are 65538 bytes: under the cap by
        # character count, over it by the measure the server uses.
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content='가' * 21846,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['error_code'] == 'file_exec_content_too_large'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_content_exactly_at_the_ceiling_goes_out(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _file_exec_envelope('file_exec_line_too_long')

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content='a' * FILE_CONTENT_MAX_BYTES,
                workspace='testworkspace',
                region='ap1',
            )

        mock_submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_local_refusal_reads_like_the_servers(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['message'] == FILE_EXEC_REFUSAL_HINTS['file_exec_invalid_path']
        assert result['server_id'] == VALID_SERVER_ID
        # The same echo a server-side refusal carries, so the error shape does
        # not depend on which side caught the problem.
        assert result['file'] == {
            'path': 'deploy.sh',
            'interpreter': '/bin/bash',
            'args': [],
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'reuse_days',
        [
            0,
            -1,
            FILE_REUSE_DAYS_MIN - 1,
            FILE_REUSE_DAYS_MAX + 1,
            1000,
        ],
    )
    async def test_reuse_days_outside_the_contract_is_refused_locally(
        self, mock_http_client, mock_token_manager, reuse_days
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            reuse_days=reuse_days,
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_exec_invalid_reuse_days'
        assert (
            result['message'] == FILE_EXEC_REFUSAL_HINTS['file_exec_invalid_reuse_days']
        )
        assert result['file']['path'] == '/opt/deploy.sh'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('reuse_days', [1.5, 30.0, True, '30'])
    async def test_a_non_integer_reuse_days_is_refused_by_the_sdk(
        self, mock_http_client, mock_token_manager, reuse_days
    ):
        # Through the SDK, as a client calls it: lax validation would coerce
        # True to 1 and '30' to 30 before the tool body ever saw them.
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            with pytest.raises(ToolError):
                await mcp.call_tool(
                    'execute_file',
                    {
                        'server_id': VALID_SERVER_ID,
                        'path': '/opt/deploy.sh',
                        'content': _FILE_SCRIPT,
                        'workspace': 'testworkspace',
                        'reuse_days': reuse_days,
                        'region': 'ap1',
                    },
                )

        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize('reuse_days', [FILE_REUSE_DAYS_MIN, FILE_REUSE_DAYS_MAX])
    async def test_reuse_days_at_the_bounds_goes_out(
        self, mock_http_client, mock_token_manager, reuse_days
    ):
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _file_exec_envelope('file_exec_line_too_long')

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                reuse_days=reuse_days,
                region='ap1',
            )

        assert mock_submit.call_args.kwargs['reuse_days'] == reuse_days

    @pytest.mark.asyncio
    async def test_absolute_but_traversing_path_names_the_real_reason(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/../etc/deploy.sh',
            content=_FILE_SCRIPT,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['error_code'] == 'file_exec_invalid_path'
        assert 'absolute but contains' in result['message']
        assert result['field'] == 'path'
        mock_http_client.post.assert_not_called()


class TestExecuteFileRefusalRendering:
    """A file-lane 400 comes back as something to act on, never to wait on."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'code, keyword',
        [
            ('file_exec_unsupported_agent', '2.8.3'),
            ('file_exec_assessor_disabled', 'assessor'),
            ('file_exec_invalid_path', 'absolute'),
            ('file_exec_content_too_large', '64 KB'),
            ('file_exec_empty_content', 'empty'),
            ('file_exec_line_too_long', 'args'),
            ('file_exec_invalid_reuse_days', '1 to 366'),
            ('file_exec_reuse_exceeds_max', 'shorter duration'),
        ],
    )
    async def test_server_refusal_carries_its_code_and_hint(
        self, mock_http_client, mock_token_manager, code, keyword
    ):
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _file_exec_envelope(code)

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == code
        assert keyword in result['message']
        # No request exists behind any of these; a pending shape would tell the
        # agent to wait for a human who was never asked.
        assert 'requires_human_approval' not in result
        assert result['file']['path'] == '/opt/deploy.sh'

    def test_every_refusal_code_has_a_hint(self):
        assert set(FILE_EXEC_REFUSAL_HINTS) == _FILE_EXEC_CODES

    def test_unsupported_agent_hint_separates_old_agent_from_platform(self):
        # One code covers two cases with different fixes: an old agent is
        # upgraded, a platform build without the lane is not helped by one.
        hint = FILE_EXEC_REFUSAL_HINTS['file_exec_unsupported_agent']

        assert 'older than 2.8.3' in hint
        assert 'upgrade_agent' in hint
        assert 'already runs 2.8.3 or newer' in hint
        assert 'upgrading does not help' in hint
        assert 'execute_command' in hint

    @pytest.mark.asyncio
    async def test_inline_credential_hint_keeps_the_caller_on_the_file_lane(
        self, mock_http_client, mock_token_manager
    ):
        # The shell lane's hint says "move it into env"; env is refused here,
        # and the script is what the reviewer reads, so the hint must not
        # steer the caller onto the unreviewed lane.
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _file_exec_envelope('command_inline_credential')

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'command_inline_credential'
        assert INLINE_CREDENTIAL_HINT not in result['message']
        assert result['message'].endswith(FILE_EXEC_INLINE_CREDENTIAL_HINT)

    @pytest.mark.asyncio
    async def test_work_session_gate_is_translated_on_the_file_lane(
        self, mock_http_client, mock_token_manager
    ):
        # The lanes share what happens after the POST, gate translation included.
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _GATE_ENVELOPE_NOT_ACTIVE

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'pending_approval'


class TestExecuteFileRun:
    """The wait and the answer, on the same path the shell lane takes."""

    @pytest.mark.asyncio
    async def test_success_echoes_the_file_but_not_its_content(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-710'}
            mock_poll.return_value = {
                'id': 'cmd-710',
                'status': 'success',
                'shell': 'file',
                'line': '/bin/bash /opt/deploy.sh --fast',
                'exit_code': 0,
                'handled_at': '2026-09-09T00:00:01Z',
            }

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                args=['--fast'],
                workspace='testworkspace',
                region='ap1',
                timeout=10,
            )

        assert result['status'] == 'success'
        assert result['command_id'] == 'cmd-710'
        assert result['server_id'] == VALID_SERVER_ID
        assert result['file'] == {
            'path': '/opt/deploy.sh',
            'interpreter': '/bin/bash',
            'args': ['--fast'],
        }
        # The polled row carries the server-rendered line; echoing a command
        # or shell this lane never chose would be misleading metadata.
        assert 'command' not in result
        assert 'shell' not in result

    @pytest.mark.asyncio
    async def test_declares_demand_support_only_when_it_will_wait(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            mock_submit.return_value = _file_exec_envelope('file_exec_empty_content')

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                region='ap1',
            )
            # Rebound each time: mypy keeps the narrowed literal across the await.
            supported = mock_submit.call_args.kwargs['purpose_demand_supported']
            assert supported is True

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                scheduled_at='2026-09-10T03:00:00Z',
                region='ap1',
            )
            supported = mock_submit.call_args.kwargs['purpose_demand_supported']
            assert supported is False

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                run_after=['cmd-700'],
                region='ap1',
            )
            supported = mock_submit.call_args.kwargs['purpose_demand_supported']
            assert supported is False

    @pytest.mark.asyncio
    async def test_truncated_purpose_is_reported(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-711'}
            mock_poll.return_value = {
                'id': 'cmd-711',
                'status': 'success',
                'handled_at': '2026-09-09T00:00:01Z',
            }

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                purpose='x' * (PURPOSE_MAX_LENGTH + 1),
                region='ap1',
                timeout=10,
            )

        assert result['purpose_truncated'] is True


class _Route(Protocol):  # an http_client.get side effect
    def __call__(self, *, endpoint: str, **kw: object) -> Awaitable[JsonValue]: ...


_UPLOAD_ROW = {'id': 'up-1', 'upload_url': 'https://s3.example/put'}


def _route_get(status: JsonValue = None) -> _Route:
    """Answer the WebFTP trigger and status GETs the write path makes."""

    async def _get(*, endpoint: str, **_: object) -> JsonValue:
        if endpoint.endswith('/status/'):
            return {'success': True} if status is None else status
        return {}

    return _get


class TestExecuteFileWriteFile:
    """write_file puts the submitted bytes on the host before the run is submitted."""

    @pytest.fixture(autouse=True)
    def _clock(self, fake_clock):
        return fake_clock

    @pytest.mark.asyncio
    async def test_off_by_default_writes_nothing(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3') as mock_put,
        ):
            mock_submit.return_value = _file_exec_envelope('file_exec_empty_content')

            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                workspace='testworkspace',
                region='ap1',
            )

        mock_http_client.post.assert_not_called()
        mock_put.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_the_same_bytes_then_submits(
        self, mock_http_client, mock_token_manager
    ):
        calls: list[str] = []

        def _post(**kw: object) -> dict[str, str]:
            calls.append('upload')
            return _UPLOAD_ROW

        mock_http_client.post.side_effect = _post
        route = _route_get()

        async def _get(*, endpoint: str, **kw: object) -> JsonValue:
            calls.append('status' if endpoint.endswith('/status/') else 'trigger')
            return await route(endpoint=endpoint, **kw)

        async def _put(*_: object) -> None:
            calls.append('put')

        mock_http_client.get.side_effect = _get
        script = '#!/bin/bash\r\necho é\n'

        async def _submit(**kw: object) -> dict[str, JsonValue]:
            calls.append('submit')
            return _file_exec_envelope('file_exec_empty_content')

        with (
            patch(
                'tools.command_tools._submit_file_execution', side_effect=_submit
            ) as mock_submit,
            patch('tools.command_tools._put_to_s3', side_effect=_put) as mock_put,
        ):
            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=script,
                write_file=True,
                username='deploy',
                work_session_id='ws-1',
                workspace='testworkspace',
                region='ap1',
            )

        assert calls == ['upload', 'put', 'trigger', 'status', 'submit']
        upload = mock_http_client.post.call_args.kwargs
        assert upload['endpoint'] == '/api/webftp/uploads/'
        assert upload['data'] == {
            'server': VALID_SERVER_ID,
            'name': 'deploy.sh',
            'path': '/opt/deploy.sh',
            'allow_overwrite': False,
            'username': 'deploy',
            'work_session': 'ws-1',
        }
        # The bytes on disk are the bytes under review: no normalization.
        mock_put.assert_awaited_once_with(
            'https://s3.example/put', script.encode('utf-8')
        )
        assert mock_submit.call_args.kwargs['content'] == script
        endpoints = [c.kwargs['endpoint'] for c in mock_http_client.get.call_args_list]
        assert endpoints[0] == '/api/webftp/uploads/up-1/upload/'
        assert endpoints[-1] == '/api/webftp/uploads/up-1/status/'

    @pytest.mark.asyncio
    async def test_success_echoes_the_file(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = _UPLOAD_ROW
        mock_http_client.get.side_effect = _route_get()
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
            patch('tools.command_tools._put_to_s3', return_value=None),
        ):
            mock_submit.return_value = {'id': 'cmd-720'}
            mock_poll.return_value = {
                'id': 'cmd-720',
                'status': 'success',
                'exit_code': 0,
                'handled_at': '2026-09-09T00:00:01Z',
            }

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
                timeout=10,
            )

        assert result['status'] == 'success'
        assert result['file'] == {
            'path': '/opt/deploy.sh',
            'interpreter': '/bin/bash',
            'args': [],
        }

    @pytest.mark.asyncio
    async def test_local_refusal_writes_nothing(
        self, mock_http_client, mock_token_manager
    ):
        with patch('tools.command_tools._put_to_s3') as mock_put:
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content='',
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_exec_empty_content'
        mock_http_client.post.assert_not_called()
        mock_put.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'post, put, status',
        [
            pytest.param(
                {'error': 'HTTP Error', 'status_code': 403, 'response': 'denied'},
                None,
                None,
                id='upload_refused',
            ),
            pytest.param({'id': 'up-1'}, None, None, id='no_upload_url'),
            pytest.param(_UPLOAD_ROW, 'Failed to upload to S3: 500', None, id='s3_put'),
            pytest.param(
                _UPLOAD_ROW,
                None,
                {'success': False, 'message': 'Permission denied'},
                id='host_write',
            ),
        ],
    )
    async def test_failed_write_submits_nothing(
        self, mock_http_client, mock_token_manager, post, put, status
    ):
        mock_http_client.post.return_value = post
        mock_http_client.get.side_effect = _route_get(status=status)
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3', return_value=put),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_write_failed'
        assert result['file']['path'] == '/opt/deploy.sh'
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_that_never_lands_times_out(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _UPLOAD_ROW
        mock_http_client.get.side_effect = _route_get(status={'success': None})
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3', return_value=None),
            patch('tools.command_tools._FILE_WRITE_TIMEOUT', 2),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_write_timeout'
        assert result['upload_id'] == 'up-1'
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('envelope', 'status'),
        [
            pytest.param(_GATE_ENVELOPE_REQUIRED, 'error', id='required'),
            pytest.param(_GATE_ENVELOPE_NOT_ACTIVE, 'pending_approval', id='pending'),
        ],
    )
    async def test_gate_refusal_of_the_write_keeps_its_own_shape(
        self, mock_http_client, mock_token_manager, envelope, status
    ):
        mock_http_client.post.return_value = envelope
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == status
        assert 'error_code' not in result
        assert result['message'].startswith('Could not write /opt/deploy.sh')
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_coded_refusal_of_the_write_keeps_the_server_code(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'response': '{"code":"permission_denied"}',
        }
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == 'permission_denied'
        assert result['message'].startswith('Could not write /opt/deploy.sh')
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_plan_limit_refusal_of_the_write_keeps_its_shape(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.PAYMENT_REQUIRED,
            'response': (
                '{"code":"webftp_limit_exceeded","gate":"plan","axis":"webftp"}'
            ),
        }
        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'webftp_limit_exceeded'
        assert result['axis'] == 'webftp'
        assert 'testworkspace/settings/billing' in result['next_action']
        assert result['message'].startswith('Could not write /opt/deploy.sh')
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_schema_publishes_write_file_off_by_default(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        descriptions = await tool_descriptions()
        schema = tools['execute_file'].input_schema

        assert schema['properties']['write_file']['default'] is False
        assert 'write_file' not in schema['required']
        text = descriptions['execute_file']
        command_text = descriptions['execute_command']
        assert 'write_file' in text
        assert 'overwrite' in text
        assert 'write_file' in command_text

    @pytest.mark.asyncio
    async def test_overwrite_and_a_named_group_reach_the_upload(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _UPLOAD_ROW
        mock_http_client.get.side_effect = _route_get()
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3', return_value=None),
        ):
            mock_submit.return_value = _file_exec_envelope('file_exec_empty_content')
            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                overwrite=True,
                username='deploy',
                groupname='ops',
                workspace='testworkspace',
                region='ap1',
            )

        upload = mock_http_client.post.call_args.kwargs['data']
        assert upload['allow_overwrite'] is True
        assert upload['groupname'] == 'ops'

    @pytest.mark.asyncio
    async def test_default_group_stays_off_the_upload(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _UPLOAD_ROW
        mock_http_client.get.side_effect = _route_get()
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3', return_value=None),
        ):
            mock_submit.return_value = _file_exec_envelope('file_exec_empty_content')
            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert 'groupname' not in mock_http_client.post.call_args.kwargs['data']
        # The run itself still carries the group it executes as.
        assert mock_submit.call_args.kwargs['groupname'] == 'alpacon'

    @pytest.mark.asyncio
    async def test_existing_file_refusal_names_both_ways_out(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _UPLOAD_ROW
        mock_http_client.get.side_effect = _route_get(
            status={'success': False, 'message': '/opt/deploy.sh already exists.'}
        )
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3', return_value=None),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_write_failed'
        assert '/opt/deploy.sh already exists.' in result['message']
        assert 'overwrite=true' in result['message']
        assert 'read_from_server=true' in result['message']
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'post, status',
        [
            ({**_UPLOAD_ROW, 'id': 7}, None),
            (_UPLOAD_ROW, {'success': 'yes'}),
        ],
        ids=['create', 'status'],
    )
    async def test_a_wrong_typed_transfer_field_is_a_write_failure(
        self, mock_http_client, mock_token_manager, post, status
    ):
        mock_http_client.post.return_value = post
        mock_http_client.get.side_effect = _route_get(status=status)
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._put_to_s3', return_value=None),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                content=_FILE_SCRIPT,
                write_file=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_write_failed'
        assert 'Unexpected upstream response shape' in result['message']
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_overwrite_without_write_file_is_refused(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            content=_FILE_SCRIPT,
            overwrite=True,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['error_code'] == 'file_exec_invalid_options'
        mock_http_client.post.assert_not_called()


# The server's real shapes: the create answers with the URL and the transfer
# command at once, and the status carries only `success` and `message`.
_DOWNLOAD_ROW = {
    'id': 'down-1',
    'download_url': 'https://s3.example/get',
    'command': 'cmd-d1',
}
_DOWNLOAD_COMMAND_DONE: dict[str, JsonValue] = {
    'id': 'cmd-d1',
    'status': 'success',
    'success': True,
    'handled_at': '2026-09-09T00:00:01Z',
}


def _route_download_status(
    status: JsonValue = None,
    command: JsonValue = None,
    *,
    commands: list[JsonValue] | None = None,
    log: list[str] | None = None,
) -> _Route:
    """Answer the transfer command and download status GETs the read path makes.
    `commands` answers the command polls in order, its last entry repeating.
    """

    async def _get(*, endpoint: str, **_: object) -> JsonValue:
        if log is not None:
            log.append(endpoint)
        if endpoint == '/api/events/commands/cmd-d1/':
            if commands:
                return commands.pop(0) if len(commands) > 1 else commands[0]
            return _DOWNLOAD_COMMAND_DONE if command is None else command
        assert endpoint == '/api/webftp/downloads/down-1/status/'
        return {'success': True, 'message': None} if status is None else status

    return _get


class TestExecuteFileReadFromServer:
    """read_from_server submits the bytes already on the host as content."""

    @pytest.fixture(autouse=True)
    def _clock(self, fake_clock):
        return fake_clock

    @pytest.mark.asyncio
    async def test_reads_the_file_then_submits_its_exact_bytes(
        self, mock_http_client, mock_token_manager
    ):
        script = '#!/bin/bash\r\necho é\n'
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        mock_http_client.get.side_effect = _route_download_status()

        with (
            patch(
                'tools.command_tools._submit_file_execution',
                return_value=_file_exec_envelope('file_exec_empty_content'),
            ) as mock_submit,
            patch(
                'tools.command_tools._get_capped',
                return_value=script.encode('utf-8'),
            ) as mock_get,
            patch('tools.command_tools._put_to_s3') as mock_put,
        ):
            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                username='deploy',
                work_session_id='ws-1',
                workspace='testworkspace',
                region='ap1',
            )

        download = mock_http_client.post.call_args.kwargs
        assert download['endpoint'] == '/api/webftp/downloads/'
        # Read as the account the script runs as.
        assert download['data'] == {
            'server': VALID_SERVER_ID,
            'name': 'deploy.sh',
            'path': '/opt/deploy.sh',
            'resource_type': 'file',
            'username': 'deploy',
            'work_session': 'ws-1',
        }
        mock_get.assert_awaited_once_with(
            'https://s3.example/get', FILE_CONTENT_MAX_BYTES
        )
        # No normalization between the host's bytes and the reviewed content.
        assert mock_submit.call_args.kwargs['content'] == script
        assert mock_submit.call_args.kwargs['path'] == '/opt/deploy.sh'
        # Nothing is written back.
        mock_put.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_url_is_fetched_only_after_the_host_sends_the_file(
        self, mock_http_client, mock_token_manager
    ):
        calls: list[str] = []
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        answers: Iterator[JsonValue] = iter([{'status': 'running', 'handled_at': None}])
        route = _route_download_status()

        async def _get(*, endpoint: str, **kw: object) -> JsonValue:
            if endpoint.startswith('/api/events/commands/'):
                calls.append('command')
                if (answer := next(answers, None)) is not None:
                    return answer
            else:
                calls.append('status')
            return await route(endpoint=endpoint, **kw)

        async def _fetch(*_: object) -> bytes:
            calls.append('fetch')
            return b'echo hi\n'

        async def _submit(**kw: object) -> dict[str, JsonValue]:
            calls.append('submit')
            return _file_exec_envelope('file_exec_empty_content')

        mock_http_client.get.side_effect = _get
        with (
            patch(
                'tools.command_tools._submit_file_execution', side_effect=_submit
            ) as mock_submit,
            patch('tools.command_tools._get_capped', side_effect=_fetch),
        ):
            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert calls == ['command', 'command', 'status', 'fetch', 'submit']
        assert mock_submit.call_args.kwargs['content'] == 'echo hi\n'

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'overrides',
        [
            {'write_file': True},
            {'content': _FILE_SCRIPT},
            {'write_file': True, 'content': _FILE_SCRIPT},
        ],
    )
    async def test_cannot_be_combined_with_write_file_or_content(
        self, mock_http_client, mock_token_manager, overrides
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            read_from_server=True,
            workspace='testworkspace',
            region='ap1',
            **overrides,
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_exec_invalid_options'
        assert 'read_from_server' in result['message']
        mock_http_client.post.assert_not_called()
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_neither_content_nor_read_from_server_is_refused_locally(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='/opt/deploy.sh',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_exec_empty_content'
        # The refusal names the way out for a script already on the host.
        assert 'read_from_server=true' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_local_refusal_reads_nothing(
        self, mock_http_client, mock_token_manager
    ):
        result = await execute_file(
            server_id=VALID_SERVER_ID,
            path='opt/deploy.sh',
            read_from_server=True,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['error_code'] == 'file_exec_invalid_path'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'body, code, phrase',
        [
            (b'', 'file_exec_empty_content', 'is empty on the host'),
            (
                b'x' * (FILE_CONTENT_MAX_BYTES + 1),
                'file_exec_content_too_large',
                '64 KB',
            ),
            (b'\xff\xfe', 'file_read_failed', 'not UTF-8'),
            ('Failed to download from S3: 404 - gone', 'file_read_failed', '404'),
        ],
    )
    async def test_an_unusable_file_submits_nothing(
        self, mock_http_client, mock_token_manager, body, code, phrase
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        mock_http_client.get.side_effect = _route_download_status()

        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_capped', return_value=body),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == code
        assert phrase in result['message']
        assert '/opt/deploy.sh' in result['message']
        assert result['file']['path'] == '/opt/deploy.sh'
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_file_exactly_at_the_ceiling_goes_out(
        self, mock_http_client, mock_token_manager
    ):
        body = b'x' * FILE_CONTENT_MAX_BYTES
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        mock_http_client.get.side_effect = _route_download_status()

        with (
            patch(
                'tools.command_tools._submit_file_execution',
                return_value=_file_exec_envelope('file_exec_empty_content'),
            ) as mock_submit,
            patch('tools.command_tools._get_capped', return_value=body),
        ):
            await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert mock_submit.call_args.kwargs['content'] == body.decode()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'post, status, command',
        [
            # The download request itself is refused.
            (
                {
                    'error': 'HTTP Error',
                    'status_code': HTTPStatus.BAD_REQUEST,
                    'response': '{"detail":"No such file"}',
                },
                None,
                None,
            ),
            # The host's transfer command fails.
            (
                _DOWNLOAD_ROW,
                None,
                {
                    'status': 'failed',
                    'success': False,
                    'result': 'Permission denied',
                    'handled_at': '2026-09-09T00:00:01Z',
                },
            ),
            # The request answers without the transfer command to wait on.
            ({**_DOWNLOAD_ROW, 'command': None}, None, None),
            # The request answers with neither id nor URL.
            ({}, None, None),
            # The server denies the transfer command.
            (_DOWNLOAD_ROW, None, {'status': 'denied'}),
            # The request or the command answers with a wrong-typed field.
            ({**_DOWNLOAD_ROW, 'id': 7}, None, None),
            (_DOWNLOAD_ROW, None, {'status': 'running', 'handled_at': 5}),
        ],
    )
    async def test_a_failed_read_submits_nothing(
        self, mock_http_client, mock_token_manager, post, status, command
    ):
        mock_http_client.post.return_value = post
        mock_http_client.get.side_effect = _route_download_status(
            status=status, command=command
        )

        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_capped') as mock_get,
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_read_failed'
        assert result['message'].startswith('Could not read /opt/deploy.sh')
        mock_get.assert_not_called()
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_transfer_the_host_reports_failed_submits_nothing(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        mock_http_client.get.side_effect = _route_download_status(
            status={'success': False, 'message': 'Permission denied'}
        )

        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_capped', return_value=b'echo hi\n'),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_read_failed'
        assert 'Permission denied' in result['message']
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_wrong_typed_transfer_status_is_a_read_failure(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        mock_http_client.get.side_effect = _route_download_status(
            status={'success': 'yes'}
        )

        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_capped', return_value=b'echo hi\n'),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['status'] == 'error'
        assert result['error_code'] == 'file_read_failed'
        assert result['download_id'] == 'down-1'
        assert 'success: ' in result['message']
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'command, status, gets',
        [
            # The host never finishes sending the file.
            ({'status': 'running', 'handled_at': None}, None, 3),
            # The host sent it but never reports the transfer.
            (None, {'success': None}, 4),
        ],
    )
    async def test_a_read_that_never_lands_times_out(
        self, mock_http_client, mock_token_manager, command, status, gets
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        mock_http_client.get.side_effect = _route_download_status(
            status=status, command=command
        )

        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_capped', return_value=b'echo hi\n'),
            patch('tools.command_tools._FILE_READ_TIMEOUT', 2),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_read_timeout'
        assert result['download_id'] == 'down-1'
        assert mock_http_client.get.call_count == gets
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_handled_at_the_deadline_still_checks_transfer_status(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        calls: list[str] = []
        mock_http_client.get.side_effect = _route_download_status(
            commands=[
                {'status': 'running', 'handled_at': None},
                _DOWNLOAD_COMMAND_DONE,
            ],
            log=calls,
        )

        with (
            patch(
                'tools.command_tools._submit_file_execution',
                return_value=_file_exec_envelope('file_exec_empty_content'),
            ) as mock_submit,
            patch('tools.command_tools._get_capped', return_value=b'echo hi\n'),
            patch('tools.command_tools._FILE_READ_TIMEOUT', 1),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_exec_empty_content'  # the submit's answer
        assert mock_submit.call_args.kwargs['content'] == 'echo hi\n'
        assert calls == [
            '/api/events/commands/cmd-d1/',
            '/api/events/commands/cmd-d1/',
            '/api/webftp/downloads/down-1/status/',
        ]

    @pytest.mark.asyncio
    async def test_a_token_that_cannot_read_the_command_reads_after_the_transfer(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        calls: list[str] = []
        mock_http_client.get.side_effect = _route_download_status(
            command={
                'error': 'HTTP Error',
                'status_code': HTTPStatus.FORBIDDEN,
                'response': '{"code":"api_token_scope_missing"}',
            },
            log=calls,
        )

        async def _fetch(url: str, limit: int) -> bytes:
            calls.append('GET')
            return b'echo hi\n'

        with (
            patch(
                'tools.command_tools._submit_file_execution',
                return_value=_file_exec_envelope('file_exec_empty_content'),
            ) as mock_submit,
            patch('tools.command_tools._get_capped', new=_fetch),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_exec_empty_content'  # the submit's answer
        assert mock_submit.call_args.kwargs['content'] == 'echo hi\n'
        assert calls == [
            '/api/events/commands/cmd-d1/',
            '/api/webftp/downloads/down-1/status/',
            'GET',
        ]

    @pytest.mark.asyncio
    async def test_a_failed_fetch_after_a_confirmed_transfer_is_reported(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = _DOWNLOAD_ROW
        calls: list[str] = []
        mock_http_client.get.side_effect = _route_download_status(log=calls)

        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch(
                'tools.command_tools._get_capped',
                return_value='Failed to download from S3: 404 - Not Found',
            ),
        ):
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['error_code'] == 'file_read_failed'
        assert '404 - Not Found' in result['message']
        assert calls == [
            '/api/events/commands/cmd-d1/',
            '/api/webftp/downloads/down-1/status/',
        ]
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_gate_refusal_of_the_read_keeps_its_own_code(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'response': '{"code":"work_session_required"}',
        }

        with patch('tools.command_tools._submit_file_execution') as mock_submit:
            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/deploy.sh',
                read_from_server=True,
                workspace='testworkspace',
                region='ap1',
            )

        assert result['code'] == 'work_session_required'
        assert 'error_code' not in result
        assert result['message'].startswith('Could not read /opt/deploy.sh')
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_schema_publishes_read_from_server_off_by_default(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        descriptions = await tool_descriptions()
        schema = tools['execute_file'].input_schema

        assert schema['properties']['read_from_server']['default'] is False
        assert 'read_from_server' not in schema['required']
        assert 'content' not in schema['required']
        file_text = descriptions['execute_file']
        command_text = descriptions['execute_command']
        assert 'read_from_server' in file_text
        assert 'read_from_server' in command_text


class TestGetCapped:
    """The presigned GET stops one byte past the ceiling."""

    @staticmethod
    def _client(handler):
        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient
        return patch(
            'tools.command_tools.httpx.AsyncClient',
            lambda *a, **kw: real(transport=transport),
        )

    @pytest.mark.asyncio
    async def test_returns_the_body_unchanged(self):
        with self._client(lambda req: httpx.Response(200, content=b'a\r\nb')):
            assert await _get_capped('https://s3.example/get', 10) == b'a\r\nb'

    @pytest.mark.asyncio
    async def test_stops_one_byte_past_the_limit(self):
        with self._client(lambda req: httpx.Response(200, content=b'x' * 100)):
            assert await _get_capped('https://s3.example/get', 10) == b'x' * 11

    @pytest.mark.asyncio
    async def test_an_error_status_is_a_message(self):
        with self._client(lambda req: httpx.Response(403, content=b'denied')):
            result = await _get_capped('https://s3.example/get', 10)
        assert isinstance(result, str)
        assert '403' in result

    @pytest.mark.asyncio
    async def test_a_transport_error_is_a_message(self):
        def _boom(req):
            raise httpx.ConnectError('down')

        with self._client(_boom):
            result = await _get_capped('https://s3.example/get', 10)
        assert isinstance(result, str)
        assert 'down' in result


class TestHeldCommandSuggestsTheFileLane:
    """A held shell line is pointed at execute_file with read_from_server."""

    async def _held(
        self,
        row_extra: dict[str, JsonValue],
        *,
        username: str | None = None,
        groupname: str = 'alpacon',
        work_session_id: str | None = None,
        data: str | None = None,
    ) -> ToolResponse:
        with (
            patch(
                'tools.command_tools._submit_command',
                return_value={'id': 'cmd-910'},
            ),
            patch(
                'tools.command_tools._get_command_result',
                return_value={
                    'id': 'cmd-910',
                    'status': 'awaiting_approval',
                    'handled_at': None,
                    **row_extra,
                },
            ),
        ):
            return await execute_command(
                server_id=VALID_SERVER_ID,
                command='bash /opt/deploy.sh --fast',
                workspace='testworkspace',
                region='ap1',
                timeout=10,
                username=username,
                groupname=groupname,
                work_session_id=work_session_id,
                data=data,
            )

    @pytest.mark.asyncio
    async def test_a_named_script_becomes_a_ready_call(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held(
            {
                'file_execution_suggestion': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': ['--fast'],
                }
            }
        )

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'COMMAND_AWAITING_APPROVAL'
        assert result['execute_file_suggestion'] == {
            'tool': 'execute_file',
            'arguments': {
                'server_id': VALID_SERVER_ID,
                'path': '/opt/deploy.sh',
                'interpreter': '/bin/bash',
                'args': ['--fast'],
                'read_from_server': True,
                'workspace': 'testworkspace',
                'region': 'ap1',
            },
        }
        assert 'read_from_server=true' in result['message']

    @pytest.mark.asyncio
    async def test_without_the_field_only_the_prose_hint_is_added(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held({})

        assert result['status'] == 'pending_approval'
        assert 'execute_file_suggestion' not in result
        assert 'read_from_server=true' in result['message']
        # The hold itself still reads as before.
        assert 'Do not resubmit the command' in result['message']

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'suggestion',
        [
            'bash /opt/deploy.sh',
            {'path': 'opt/deploy.sh'},
            {'path': '/opt/../etc/deploy.sh'},
            {'path': '/opt/deploy.sh', 'interpreter': 'bash'},
            {'path': '/opt/deploy.sh', 'args': '--fast'},
            {'path': '/opt/deploy.sh', 'args': [1]},
            {'path': '/opt/deploy.sh', 'interpreter': ''},
            {'path': '/opt/deploy.sh', 'args': False},
            # Nothing names the interpreter, so nothing is guessed.
            {'path': '/opt/deploy.sh'},
            {'path': '/opt/deploy.sh', 'interpreter_name': '/bin/bash'},
            {'path': '/opt/deploy.sh', 'interpreter_name': 'ba sh'},
            {'path': '/opt/deploy.sh', 'interpreter_name': ''},
            {
                'path': '/opt/deploy.sh',
                'interpreter': '/bin/bash',
                'interpreter_name': 'bash',
            },
        ],
    )
    async def test_a_malformed_suggestion_is_dropped_whole(
        self, mock_http_client, mock_token_manager, suggestion
    ):
        result = await self._held({'file_execution_suggestion': suggestion})

        assert result['status'] == 'pending_approval'
        assert 'execute_file_suggestion' not in result
        assert 'read_from_server=true' in result['message']

    @pytest.mark.asyncio
    async def test_a_script_body_points_at_execute_file_with_write_file(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held(
            {'script_body_suggestion': {'signal': 'embedded_script'}}
        )

        assert result['status'] == 'pending_approval'
        assert result['script_body_suggestion'] == {'signal': 'embedded_script'}
        assert 'write_file=true' in result['message']
        assert 'Multi-step work inside a container' in result['message']
        # The generic read_from_server hint gives way to the specific one.
        assert 'read_from_server=true' not in result['message']
        assert 'execute_file_suggestion' not in result
        assert 'Do not resubmit the command' in result['message']

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'body',
        [
            None,
            {},
            {'signal': 'something_else'},
            {'signal': 1},
            {'signal': []},
            'embedded_script',
        ],
    )
    async def test_an_absent_or_unknown_script_body_signal_changes_nothing(
        self, mock_http_client, mock_token_manager, body
    ):
        extra = {} if body is None else {'script_body_suggestion': body}
        result = await self._held(extra)

        assert 'script_body_suggestion' not in result
        assert 'write_file=true' not in result['message']
        assert 'read_from_server=true' in result['message']

    @pytest.mark.asyncio
    async def test_a_script_path_suggestion_wins_over_a_script_body(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held(
            {
                'file_execution_suggestion': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                    'args': ['--fast'],
                },
                'script_body_suggestion': {'signal': 'embedded_script'},
            }
        )

        assert result['execute_file_suggestion']['tool'] == 'execute_file'
        assert 'script_body_suggestion' not in result
        assert 'write_file=true' not in result['message']

    @pytest.mark.asyncio
    async def test_missing_args_take_an_empty_list(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held(
            {
                'file_execution_suggestion': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                }
            }
        )

        arguments = result['execute_file_suggestion']['arguments']
        assert arguments['interpreter'] == '/bin/bash'
        assert arguments['args'] == []
        assert 'interpreter_name' not in result['execute_file_suggestion']
        assert 'instruction' not in result['execute_file_suggestion']

    @pytest.mark.asyncio
    async def test_a_bare_interpreter_is_left_for_the_caller(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held(
            {
                'file_execution_suggestion': {
                    'path': '/opt/deploy.sh',
                    'interpreter': None,
                    'interpreter_name': 'bash',
                    'args': ['--fast'],
                }
            }
        )

        suggestion = result['execute_file_suggestion']
        assert suggestion['tool'] == 'execute_file'
        assert suggestion['interpreter_name'] == 'bash'
        assert 'command -v bash' in suggestion['instruction']
        assert suggestion['arguments'] == {
            'server_id': VALID_SERVER_ID,
            'path': '/opt/deploy.sh',
            'interpreter': None,
            'args': ['--fast'],
            'read_from_server': True,
            'workspace': 'testworkspace',
            'region': 'ap1',
        }
        assert 'read_from_server=true' in result['message']

    @pytest.mark.asyncio
    async def test_the_held_run_identity_carries_into_the_call(
        self, mock_http_client, mock_token_manager
    ):
        work_session_id = '660e8400-e29b-41d4-a716-446655440000'
        result = await self._held(
            {
                'file_execution_suggestion': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                }
            },
            username='deploy',
            groupname='ops',
            work_session_id=work_session_id,
        )

        arguments = result['execute_file_suggestion']['arguments']
        assert arguments['username'] == 'deploy'
        assert arguments['groupname'] == 'ops'
        assert arguments['work_session_id'] == work_session_id

    @pytest.mark.asyncio
    async def test_after_a_stated_purpose_the_call_comes_off_the_row(
        self, mock_http_client, mock_token_manager
    ):
        # state_command_purpose knows neither the server nor the account, and
        # the row renders the server and the Work Session as nested objects.
        work_session_id = '660e8400-e29b-41d4-a716-446655440000'
        with (
            patch(
                'tools.command_tools._answer_purpose_demand',
                return_value={'status': 'success', 'status_code': 202},
            ),
            patch(
                'tools.command_tools._get_command_result',
                return_value={
                    'id': 'cmd-911',
                    'status': 'awaiting_approval',
                    'handled_at': None,
                    'line': 'bash /opt/deploy.sh',
                    'server': {'id': VALID_SERVER_ID, 'name': 'web-1'},
                    'username': 'deploy',
                    'groupname': 'ops',
                    'work_session': {'id': work_session_id, 'title': 'deploy'},
                    'file_execution_suggestion': {
                        'path': '/opt/deploy.sh',
                        'interpreter': '/bin/bash',
                    },
                },
            ),
        ):
            result = await state_command_purpose(
                command_id='cmd-911',
                purpose='Deploys the release staged in /opt.',
                workspace='testworkspace',
                region='ap1',
                timeout=10,
            )

        assert result['execute_file_suggestion']['arguments'] == {
            'server_id': VALID_SERVER_ID,
            'path': '/opt/deploy.sh',
            'interpreter': '/bin/bash',
            'args': [],
            'read_from_server': True,
            'workspace': 'testworkspace',
            'region': 'ap1',
            'username': 'deploy',
            'groupname': 'ops',
            'work_session_id': work_session_id,
        }

    @pytest.mark.asyncio
    async def test_a_work_session_rendered_as_an_id_carries_too(
        self, mock_http_client, mock_token_manager
    ):
        # The refusal hint already reads either shape; the held one must match.
        work_session_id = '660e8400-e29b-41d4-a716-446655440000'
        with (
            patch(
                'tools.command_tools._answer_purpose_demand',
                return_value={'status': 'success', 'status_code': 202},
            ),
            patch(
                'tools.command_tools._get_command_result',
                return_value={
                    'id': 'cmd-912',
                    'status': 'awaiting_approval',
                    'handled_at': None,
                    'line': 'bash /opt/deploy.sh',
                    'server': VALID_SERVER_ID,
                    'work_session': work_session_id,
                    'file_execution_suggestion': {
                        'path': '/opt/deploy.sh',
                        'interpreter': '/bin/bash',
                    },
                },
            ),
        ):
            result = await state_command_purpose(
                command_id='cmd-912',
                purpose='Deploys the release staged in /opt.',
                workspace='testworkspace',
                region='ap1',
                timeout=10,
            )

        arguments = result['execute_file_suggestion']['arguments']
        assert arguments['work_session_id'] == work_session_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'row_extra, call_extra',
        [
            ({}, {'data': 'yes\n'}),
            # A caller other than the submitter learns it from the row.
            ({'data': 'yes\n'}, {}),
        ],
    )
    async def test_a_run_fed_stdin_gets_only_the_prose_hint(
        self, mock_http_client, mock_token_manager, row_extra, call_extra
    ):
        result = await self._held(
            {
                'file_execution_suggestion': {
                    'path': '/opt/deploy.sh',
                    'interpreter': '/bin/bash',
                },
                **row_extra,
            },
            **call_extra,
        )

        assert result['status'] == 'pending_approval'
        assert 'execute_file_suggestion' not in result
        assert 'read_from_server=true' in result['message']

    @pytest.mark.asyncio
    async def test_a_run_fed_stdin_gets_no_script_body_hint(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._held(
            {'script_body_suggestion': {'signal': 'embedded_script'}},
            data='yes\n',
        )

        assert result['status'] == 'pending_approval'
        assert 'script_body_suggestion' not in result
        assert 'write_file=true' not in result['message']

    @pytest.mark.asyncio
    async def test_check_command_status_carries_the_script_body_hint(
        self, mock_http_client, mock_token_manager
    ):
        row = {
            'id': 'cmd-910',
            'status': 'awaiting_approval',
            'handled_at': None,
            'script_body_suggestion': {'signal': 'embedded_script'},
        }
        with patch('tools.command_tools._get_command_result', return_value=row):
            result = await check_command_status(
                command_id='cmd-910', workspace='testworkspace', region='ap1'
            )

        assert result['status'] == 'pending_approval'
        assert result['script_body_suggestion'] == {'signal': 'embedded_script'}
        assert 'write_file=true' in result['message']


class TestExecuteFileRegistration:
    """The published tool is what teaches a model to take this lane."""

    @pytest.mark.asyncio
    async def test_schema_has_no_shell_lane_fields(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools['execute_file'].input_schema

        properties = schema['properties']
        for forbidden in ('line', 'command', 'data', 'env', 'shell', 'kwargs'):
            assert forbidden not in properties
        assert set(schema['required']) == {'server_id', 'path', 'workspace'}
        assert properties['interpreter']['default'] == '/bin/bash'
        for shared in ('username', 'groupname', 'run_after', 'scheduled_at'):
            assert shared in properties
        for shared in ('timeout', 'work_session_id', 'purpose', 'region'):
            assert shared in properties

    @pytest.mark.asyncio
    async def test_reuse_days_is_published_as_optional(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools['execute_file'].input_schema

        assert 'reuse_days' in schema['properties']
        assert 'reuse_days' not in schema['required']
        assert schema['properties']['reuse_days'].get('default') is None

    @pytest.mark.asyncio
    async def test_description_states_the_lane_semantics(self):
        descriptions = await tool_descriptions()
        text = descriptions['execute_file']

        # Only what a client depends on: the on-disk contract, the cross-
        # reference, the codes and the agent floor. Wording is free to move.
        assert 'must already exist' in text
        assert 'never shipped to the host' in text
        assert 'execute_command' in text
        for code in _FILE_EXEC_CODES:
            assert code in text
        assert '2.8.3' in text
        assert 'Windows' in text
        assert 'file_exec_reuse_exceeds_max' in text
        assert 'Standing approvals always expire' not in text

    @pytest.mark.asyncio
    async def test_reuse_days_parameter_states_the_proposal_rules(self):
        tools = {t.name: t for t in await mcp.list_tools()}

        reuse = tools['execute_file'].input_schema['properties']['reuse_days']

        # The approver only opts in or not, and omitting reuse_days still lets
        # an opted-in grant reach the ceiling, so neither may read otherwise.
        text = reuse['description']
        assert 'proposal' in text
        assert 'the approver cannot choose another period' in text
        assert 'Standing approvals always expire' in text
        assert 'default 90' in text
        assert 'never a longer one' in text
        assert 'Omitting it proposes no duration' in text
        assert 'never expires' not in text

    @pytest.mark.asyncio
    async def test_execute_command_points_scripts_at_execute_file(self):
        descriptions = await tool_descriptions()
        text = descriptions['execute_command']

        assert 'execute_file' in text
        assert 'heredoc' in text


class TestListCommandsParams:
    LIST_COMMANDS_CASES = [
        pytest.param({}, {'page_size': 20, 'ordering': '-added_at'}, id='no_filters'),
    ]

    @pytest.mark.parametrize(('tool_kwargs', 'expected_params'), LIST_COMMANDS_CASES)
    @pytest.mark.asyncio
    async def test_params(
        self, tool_kwargs, expected_params, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await list_commands(
            workspace='testworkspace', region='ap1', **tool_kwargs
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/events/commands/',
            token='test-token',
            params=expected_params,
        )


_OTHER_SERVER_ID = '550e8400-e29b-41d4-a716-446655440002'

_REFUSED_ROW = {
    'id': 'cmd-uf1',
    'server': VALID_SERVER_ID,
    'username': 'deploy',
    'status': 'rejected',
    'verification_status': 'rejected',
    'rejection_cause': 'use_file_execution',
    'rejection_gate': 'approval',
    'result': 'Run this script as a file instead.',
    'handled_at': None,
}


class TestUseFileExecutionRefusal:
    """A script-body line is refused after verification, read off the command row."""

    @pytest.mark.asyncio
    async def test_execute_command_returns_structured_refusal(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-uf1'}
            mock_poll.return_value = dict(_REFUSED_ROW)

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command="bash <<'EOF'\necho hi\nEOF",
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert result['error_code'] == 'use_file_execution'
        assert result['command_id'] == 'cmd-uf1'
        assert result['message'].startswith('Run this script as a file instead.')
        assert result['rejection_cause'] == 'use_file_execution'
        assert result['rejection_gate'] == 'approval'
        assert 'execute_file' in result['rejection_hint']
        assert result['rejection_hint'] not in result['message']
        next_action = result['next_action']
        assert 'execute_file' in next_action
        assert 'write_file=true' in next_action
        assert f'server_id={VALID_SERVER_ID}' in next_action
        assert 'username=deploy' in next_action
        assert 'interpreter' in next_action
        # A single-server call has no fleet batch to warn about.
        assert 'original target set' not in next_action

    @pytest.mark.asyncio
    async def test_refusal_is_read_ahead_of_the_status(
        self, mock_http_client, mock_token_manager
    ):
        # A non-terminal status would otherwise keep the poll going to timeout.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-uf1'}
            mock_poll.return_value = {**_REFUSED_ROW, 'status': 'verifying'}

            await execute_command(
                server_id=VALID_SERVER_ID,
                command='echo aGk= | base64 -d | sh',
                workspace='testworkspace',
                timeout=10,
            )

        mock_poll.assert_called_once()

    @pytest.mark.asyncio
    async def test_next_action_keeps_session_group_and_flags_stdin(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-uf5'}
            mock_poll.return_value = {
                **_REFUSED_ROW,
                'groupname': 'ops',
                'work_session': {'id': 'ws-uuid-abcd'},
                'data': 'payload',
            }

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command="python3 - <<'EOF'\nprint(1)\nEOF",
                workspace='testworkspace',
                data='payload',
                timeout=10,
            )

        next_action = result['next_action']
        assert 'groupname=ops' in next_action
        assert 'work_session_id=ws-uuid-abcd' in next_action
        assert next_action.count('no stdin') == 1

    @pytest.mark.asyncio
    async def test_stdin_flagged_from_the_call_when_the_row_omits_data(
        self, mock_http_client, mock_token_manager
    ):
        # Some rows withhold data, so the call's own argument has to count.
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-uf6'}
            mock_poll.return_value = dict(_REFUSED_ROW)

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command="python3 - <<'EOF'\nprint(1)\nEOF",
                workspace='testworkspace',
                data='payload',
                timeout=10,
            )

        assert result['error_code'] == 'use_file_execution'
        assert result['next_action'].count('no stdin') == 1

    @pytest.mark.asyncio
    async def test_other_rejection_keeps_generic_error(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-uf2'}
            mock_poll.return_value = {
                **_REFUSED_ROW,
                'rejection_cause': 'assessor_denied',
            }

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='rm -rf /',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert 'error_code' not in result
        assert 'next_action' not in result

    @pytest.mark.asyncio
    async def test_missing_guidance_falls_back_to_hint(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-uf3'}
            mock_poll.return_value = {**_REFUSED_ROW, 'result': None}

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command="python3 -c 'import os\nprint(1)'",
                workspace='testworkspace',
                timeout=10,
            )

        assert result['error_code'] == 'use_file_execution'
        assert 'execute_file' in result['message']

    @pytest.mark.asyncio
    async def test_state_command_purpose_surfaces_refusal(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'cmd-uf1'}
        with patch('tools.command_tools._get_command_result') as mock_poll:
            mock_poll.return_value = {
                **_REFUSED_ROW,
                'server': {'id': VALID_SERVER_ID, 'name': 'web-1'},
            }

            result = await state_command_purpose(
                command_id='cmd-uf1',
                purpose='Rotate the nginx log on this host.',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['error_code'] == 'use_file_execution'
        # The server comes off the polled row when the caller has none.
        assert f'server_id={VALID_SERVER_ID}' in result['next_action']

    @pytest.mark.asyncio
    async def test_state_command_purpose_flags_stdin_from_the_row(
        self, mock_http_client, mock_token_manager
    ):
        # This caller did not submit the command, so only the row knows.
        mock_http_client.post.return_value = {'id': 'cmd-uf1'}
        with patch('tools.command_tools._get_command_result') as mock_poll:
            mock_poll.return_value = {**_REFUSED_ROW, 'data': 'payload'}

            result = await state_command_purpose(
                command_id='cmd-uf1',
                purpose='Rotate the nginx log on this host.',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['error_code'] == 'use_file_execution'
        assert result['next_action'].count('no stdin') == 1

    @pytest.mark.asyncio
    async def test_list_commands_marks_only_refused_servers(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'results': [
                dict(_REFUSED_ROW),
                {
                    'id': 'cmd-uf4',
                    'server': _OTHER_SERVER_ID,
                    'status': 'success',
                    'result': 'hi',
                },
            ]
        }

        result = await list_commands(workspace='testworkspace', region='ap1')

        refused, ran = result['data']['results']
        assert refused['error_code'] == 'use_file_execution'
        assert f'server_id={VALID_SERVER_ID}' in refused['next_action']
        assert 'do not resubmit the original target set' in refused['next_action']
        assert 'error_code' not in ran
        assert 'next_action' not in ran

    @pytest.mark.asyncio
    async def test_list_commands_flags_stdin_from_the_row(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'results': [{**_REFUSED_ROW, 'data': 'payload'}]
        }

        result = await list_commands(workspace='testworkspace', region='ap1')

        (refused,) = result['data']['results']
        assert refused['next_action'].count('no stdin') == 1

    @pytest.mark.asyncio
    async def test_tool_descriptions_name_the_refusal(self):
        descriptions = await tool_descriptions()

        for name in (
            'execute_command',
            'execute_command_multi_server',
            'list_commands',
        ):
            assert 'use_file_execution' in descriptions[name], name
        assert (
            'file_exec_unsupported_agent'
            in descriptions['execute_command_multi_server']
        )


def _rejected_row(**fields: object) -> dict[str, object]:
    return {'id': 'cmd-r1', 'status': 'rejected', 'handled_at': None, **fields}


class TestRejectionCause:
    """A command a gate refused before it ran says why and whom to ask (#242)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'cause,expected,absent',
        [
            (
                'approval_expired',
                (
                    'The approval request expired with no decision. Do not resubmit on '
                    'your own; ask the user whether an approver can decide a new request.'
                ),
                'A human approver rejected this command',
            ),
            (
                'approval_rejected',
                (
                    'A human approver rejected this command. Do not resubmit it; ask '
                    'the approver why, out-of-band.'
                ),
                'The approval request expired',
            ),
            (
                'approval_rule_changed',
                (
                    'The approval rule changed while the command waited, so it was '
                    'closed without running. Sending it again applies the current '
                    'rule, which may ask a different person to decide. Ask the user '
                    'whether to send it again.'
                ),
                'A human approver rejected this command',
            ),
        ],
    )
    @pytest.mark.parametrize(
        'tool',
        ['execute_command', 'execute_file', 'state_command_purpose', 'list_commands'],
    )
    async def test_expiry_is_not_a_human_rejection(
        self, tool, cause, expected, absent, mock_http_client, mock_token_manager
    ):
        row = _rejected_row(rejection_cause=cause, rejection_gate='approval')
        with (
            patch('tools.command_tools._submit_command', return_value={'id': 'cmd-r1'}),
            patch(
                'tools.command_tools._submit_file_execution',
                return_value={'id': 'cmd-r1'},
            ),
            patch('tools.command_tools._answer_purpose_demand', return_value={}),
            patch('tools.command_tools._get_command_result', return_value=row),
        ):
            if tool == 'execute_command':
                result = await self._run(row)
            elif tool == 'execute_file':
                result = await execute_file(
                    server_id=VALID_SERVER_ID,
                    path='/opt/run.sh',
                    content='echo hi',
                    workspace='testworkspace',
                    timeout=10,
                )
            elif tool == 'state_command_purpose':
                result = await state_command_purpose(
                    command_id='cmd-r1',
                    purpose='Check the service on this host',
                    workspace='testworkspace',
                    timeout=10,
                )
            else:
                mock_http_client.get.return_value = {'count': 1, 'results': [row]}
                result = await list_commands(workspace='testworkspace')
                result = result['data']['results'][0]

        assert result['rejection_cause'] == cause
        assert result['rejection_gate'] == 'approval'
        assert result['rejection_hint'] == expected
        assert absent not in json.dumps(result)
        assert 'rejected by a reviewer' not in json.dumps(result)
        if tool != 'list_commands':
            assert result['status'] == 'error'
            assert (
                result['message'] == f'Command failed with status: rejected. {expected}'
            )

    async def _run(self, row: dict[str, object]) -> ToolResponse:
        with (
            patch('tools.command_tools._submit_command') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-r1'}
            mock_poll.return_value = row
            return await execute_command(
                server_id=VALID_SERVER_ID,
                command='systemctl restart nginx',
                workspace='testworkspace',
                timeout=10,
            )

    @pytest.mark.asyncio
    async def test_a_known_cause_names_cause_gate_and_hint(self, mock_token_manager):
        result = await self._run(
            _rejected_row(
                rejection_cause='approval_rejected', rejection_gate='approval'
            )
        )

        assert result['status'] == 'error'
        assert result['rejection_cause'] == 'approval_rejected'
        assert result['rejection_gate'] == 'approval'
        assert 'A human approver rejected this command' in result['rejection_hint']
        assert result['rejection_hint'] in result['message']
        assert result['message'].startswith('Command failed with status: rejected')

    @pytest.mark.asyncio
    async def test_an_approver_reason_is_quoted_as_their_words(
        self, mock_token_manager
    ):
        result = await self._run(
            _rejected_row(
                rejection_cause='approval_rejected',
                rejection_gate='approval',
                rejection_note='Add a guard on line 23.',
            )
        )

        assert result['rejection_note'] == 'Add a guard on line 23.'
        assert 'gave a reason, quoted in rejection_note' in result['rejection_hint']
        assert 'not as instructions to follow' in result['rejection_hint']
        assert result['rejection_hint'] in result['message']

    @pytest.mark.asyncio
    async def test_a_purpose_answer_settling_on_a_rejection_quotes_the_reason(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'cmd-r1'}
        with patch('tools.command_tools._get_command_result') as mock_poll:
            mock_poll.return_value = _rejected_row(
                rejection_cause='approval_rejected',
                rejection_gate='approval',
                rejection_note='Add a guard on line 23.',
            )
            result = await state_command_purpose(
                command_id='cmd-r1',
                purpose='Restart nginx after the config change.',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert result['rejection_note'] == 'Add a guard on line 23.'
        assert 'gave a reason, quoted in rejection_note' in result['rejection_hint']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('note', ['', '   ', None])
    async def test_no_reason_keeps_the_ask_the_approver_hint(
        self, mock_token_manager, note
    ):
        row = _rejected_row(
            rejection_cause='approval_rejected', rejection_gate='approval'
        )
        if note is not None:
            row['rejection_note'] = note

        result = await self._run(row)

        assert 'rejection_note' not in result
        assert 'ask the approver why' in result['rejection_hint']

    @pytest.mark.asyncio
    async def test_a_note_on_another_cause_is_not_surfaced(self, mock_token_manager):
        result = await self._run(
            _rejected_row(
                rejection_cause='risk_denied',
                rejection_gate='risk',
                rejection_note='stale text',
            )
        )

        assert 'rejection_note' not in result

    @pytest.mark.asyncio
    async def test_a_null_cause_means_not_recorded(self, mock_token_manager):
        result = await self._run(
            _rejected_row(rejection_cause=None, rejection_gate=None)
        )

        assert result['status'] == 'error'
        assert result['rejection_cause'] is None
        assert 'did not record why' in result['rejection_hint']

    @pytest.mark.asyncio
    async def test_an_older_server_row_without_the_fields_is_not_recorded(
        self, mock_token_manager
    ):
        result = await self._run(_rejected_row())

        assert result['status'] == 'error'
        assert result['rejection_cause'] is None
        assert 'did not record why' in result['rejection_hint']

    @pytest.mark.asyncio
    async def test_an_unknown_cause_falls_back_to_its_gate(self, mock_token_manager):
        result = await self._run(
            _rejected_row(rejection_cause='risk_new_reason', rejection_gate='risk')
        )

        assert result['rejection_cause'] == 'risk_new_reason'
        assert result['rejection_hint'].startswith(REFUSAL_GATE_HINT['risk'])
        assert (
            'Resubmitting the same command gets the same answer'
            in (result['rejection_hint'])
        )

    @pytest.mark.asyncio
    async def test_an_unknown_cause_and_gate_gets_the_generic_hint(
        self, mock_token_manager
    ):
        result = await self._run(
            _rejected_row(rejection_cause='brand_new', rejection_gate='brand_new_gate')
        )

        assert 'A gate refused this command before it ran' in result['rejection_hint']

    @pytest.mark.asyncio
    async def test_a_denied_command_without_a_cause_keeps_todays_error(
        self, mock_token_manager
    ):
        result = await self._run(
            {'id': 'cmd-r1', 'status': 'denied', 'handled_at': None}
        )

        assert result['status'] == 'error'
        assert result['message'] == 'Command failed with status: denied'
        assert 'rejection_hint' not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'cause',
        [
            'command_acl_denied',
            'command_acl_unavailable',
            'risk_denied',
            'risk_unavailable',
            'approval_policy_denied',
            'approval_rejected',
            'approval_expired',
            'approval_cancelled',
            'approval_rule_changed',
            'work_session_terminated',
            'account_bound_to_other_person',
            'unsigned_file',
            'signature_invalid',
        ],
    )
    async def test_every_known_cause_never_says_to_retry(
        self, cause, mock_token_manager
    ):
        result = await self._run(_rejected_row(rejection_cause=cause))

        assert (
            'A gate refused this command before it ran' not in result['rejection_hint']
        )
        assert 'retry' not in result['rejection_hint'].lower()

    @pytest.mark.asyncio
    async def test_execute_file_carries_the_same_fields(self, mock_token_manager):
        with (
            patch('tools.command_tools._submit_file_execution') as mock_submit,
            patch('tools.command_tools._get_command_result') as mock_poll,
        ):
            mock_submit.return_value = {'id': 'cmd-r1'}
            mock_poll.return_value = _rejected_row(
                rejection_cause='signature_invalid', rejection_gate=None
            )

            result = await execute_file(
                server_id=VALID_SERVER_ID,
                path='/opt/run.sh',
                interpreter='/bin/bash',
                content='echo hi\n',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert result['rejection_cause'] == 'signature_invalid'
        assert result['rejection_gate'] is None
        assert 'could not verify' in result['rejection_hint']

    @pytest.mark.asyncio
    async def test_list_commands_annotates_rejected_entries_only(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {
                    'id': 'cmd-1',
                    'status': 'rejected',
                    'rejection_cause': 'approval_expired',
                    'rejection_gate': 'approval',
                },
                {'id': 'cmd-2', 'status': 'success', 'rejection_cause': None},
            ],
        }

        result = await list_commands(workspace='testworkspace', region='ap1')

        rejected, succeeded = result['data']['results']
        assert result['status'] == 'success'
        assert 'expired with no decision' in rejected['rejection_hint']
        assert 'rejection_hint' not in succeeded


class TestRefusalEnvelopeThroughTheTool:
    """A coded refusal reaches the caller with its gate and missing (#242)."""

    @pytest.mark.asyncio
    async def test_a_403_with_gate_and_missing_suggests_no_endpoint(
        self, mock_token_manager
    ):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {
                'error': 'HTTP Error',
                'status_code': HTTPStatus.FORBIDDEN,
                'message': 'HTTP 403',
                'response': json.dumps(
                    {
                        'code': 'command_not_preapproved',
                        'gate': 'command_acl',
                        'missing': 'command_preapproval',
                    }
                ),
            }

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='ls',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.FORBIDDEN
        assert result['gate'] == 'command_acl'
        assert result['missing'] == 'command_preapproval'
        assert 'create_command_acl' not in json.dumps(result)

    @pytest.mark.asyncio
    async def test_a_server_hint_reaches_the_caller_as_sent(self, mock_token_manager):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {
                'error': 'HTTP Error',
                'status_code': HTTPStatus.FORBIDDEN,
                'message': 'HTTP 403',
                'response': json.dumps(
                    {'code': 'some_new_code', 'hint': 'Ask your admin for X.'}
                ),
            }

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='ls',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert result['hint'] == 'Ask your admin for X.'
        assert result['error_code'] == 'some_new_code'
        assert 'recovery_hints' not in result

    @pytest.mark.asyncio
    async def test_an_older_server_403_keeps_its_status_hints(self, mock_token_manager):
        with patch('tools.command_tools._submit_command') as mock_submit:
            mock_submit.return_value = {
                'error': 'HTTP Error',
                'status_code': HTTPStatus.FORBIDDEN,
                'message': 'HTTP 403',
                'response': json.dumps({'code': 'permission_denied'}),
            }

            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='ls',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['status'] == 'error'
        assert 'gate' not in result
        assert 'create_command_acl' in result['related_tools']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, param, phrase, gone',
    [
        (
            'execute_command',
            'timeout',
            'resets while the command is actively running',
            'timeout resets',
        ),
        ('execute_command', 'timeout', 'default 300', 'Default timeout is'),
        (
            'execute_command_multi_server',
            'purpose',
            'purpose_truncated',
            'purpose_truncated',
        ),
        (
            'state_command_purpose',
            'command_id',
            'purpose_required response',
            'the command_id is in that response',
        ),
        ('execute_file', 'path', '/opt/deploy.sh', 'must be absolute'),
        ('execute_file', 'interpreter', 'a bare "bash" is refused', 'a bare "bash"'),
        ('execute_file', 'content', 'byte-for-byte', 'byte-for-byte'),
        ('execute_file', 'content', '64 KB', 'capped at 64 KB'),
        ('execute_file', 'username', 'WebFTP default', 'pass username whenever'),
        ('execute_file', 'timeout', 'default 300', 'Default timeout is'),
        ('execute_file', 'purpose', 'What this run is for', 'Pass purpose to say'),
    ],
)
async def test_command_argument_rule_lives_on_the_parameter(
    tool_name, param, phrase, gone
):
    # Given a tool whose argument rule used to sit in its description

    # When reading the published parameter and tool description
    on_parameter, on_tool = await published_rule(tool_name, param)

    # Then the parameter states the rule and the tool no longer does
    assert phrase in on_parameter
    assert gone not in on_tool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool_name, param, phrase, gone',
    [
        (
            'execute_command_multi_server',
            'parallel',
            'one after another',
            'parallel=false',
        ),
    ],
)
async def test_parallel_rule_lives_on_the_parameter(tool_name, param, phrase, gone):
    # Given a tool whose argument rule used to sit in its description

    # When reading the published parameter and tool description
    on_parameter, on_tool = await published_rule(tool_name, param)

    # Then the parameter states the rule and the tool no longer does
    assert phrase in on_parameter
    assert gone not in on_tool


class TestCheckCommandStatus:
    """One GET by command_id that never waits and never resubmits."""

    @staticmethod
    async def _check(row: object) -> tuple[ToolResponse, MagicMock]:
        with patch(
            'tools.command_tools._get_command_result', return_value=row
        ) as mock_poll:
            result = await check_command_status(
                command_id='cmd-s1', workspace='testworkspace', region='ap1'
            )
        return result, mock_poll

    @pytest.mark.asyncio
    async def test_a_finished_command_returns_its_row(
        self, mock_http_client, mock_token_manager
    ):
        row = {
            'id': 'cmd-s1',
            'status': 'success',
            'result': 'ok',
            'handled_at': '2026-04-03T03:00:01Z',
        }

        result, _ = await self._check(row)

        assert result['status'] == 'success'
        assert result['data'] == row
        assert result['command_id'] == 'cmd-s1'
        assert 'server_id' not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize('status', ['running', 'queued', 'verifying'])
    async def test_a_running_command_succeeds_with_a_message_and_one_read(
        self, status, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-s1', 'status': status, 'handled_at': None}

        result, mock_poll = await self._check(row)

        assert result['status'] == 'success'
        assert result['message'] == f'Command still {status}; check again shortly.'
        assert 'check_command_status' in result['next_action']
        assert result['data'] == row
        mock_poll.assert_called_once_with(
            command_id='cmd-s1', region='ap1', workspace='testworkspace', token=ANY
        )

    @pytest.mark.asyncio
    async def test_a_stuck_command_is_not_reported_as_a_failure(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-s1', 'status': 'stuck', 'handled_at': None}

        result, _ = await self._check(row)

        assert result['status'] == 'success'
        assert 'may still finish' in result['message']
        assert 'Do not resubmit' in result['message']
        assert 'check_command_status' in result['next_action']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('row_status', [{}, {'status': 'archived'}])
    async def test_an_unrecognized_status_is_not_called_running(
        self, row_status, mock_http_client, mock_token_manager
    ):
        result, _ = await self._check(
            {'id': 'cmd-s1', 'handled_at': None, **row_status}
        )

        assert result['status'] == 'success'
        assert 'not one this tool recognizes' in result['message']
        assert 'still' not in result['message']
        assert 'check_command_status' in result['next_action']

    @pytest.mark.asyncio
    async def test_awaiting_approval_returns_the_pending_approval_shape(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-s1', 'status': 'awaiting_approval', 'handled_at': None}

        result, mock_poll = await self._check(row)

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'COMMAND_AWAITING_APPROVAL'
        assert result['requires_human_approval'] is True
        assert result['command_id'] == 'cmd-s1'
        assert 'check_command_status' in result['message']
        assert mock_poll.call_count == 1

    @pytest.mark.asyncio
    async def test_awaiting_purpose_returns_purpose_required(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-s1', 'status': 'awaiting_purpose', 'handled_at': None}

        result, _ = await self._check(row)

        assert result['status'] == 'purpose_required'
        assert result['answerable_by_agent'] is True
        assert result['command_id'] == 'cmd-s1'
        assert 'state_command_purpose' in result['next_action']

    @pytest.mark.asyncio
    async def test_a_command_that_never_ran_is_an_error(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-s1', 'status': 'denied', 'handled_at': None}

        result, _ = await self._check(row)

        assert result['status'] == 'error'
        assert result['message'] == 'Command failed with status: denied'
        assert result['command_id'] == 'cmd-s1'

    @pytest.mark.asyncio
    async def test_a_script_body_refusal_keeps_its_error_code(
        self, mock_http_client, mock_token_manager
    ):
        row = {
            'id': 'cmd-s1',
            'status': 'rejected',
            'rejection_cause': 'use_file_execution',
            'handled_at': None,
        }

        result, _ = await self._check(row)

        assert result['status'] == 'error'
        assert result['error_code'] == 'use_file_execution'
        assert 'execute_file' in result['next_action']

    @pytest.mark.asyncio
    async def test_an_http_error_is_an_error_result(
        self, mock_http_client, mock_token_manager
    ):
        envelope = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.NOT_FOUND,
            'response': '{"detail":"Not found."}',
        }

        result, mock_poll = await self._check(envelope)

        assert result['status'] == 'error'
        assert result['command_id'] == 'cmd-s1'
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        assert mock_poll.call_count == 1

    @pytest.mark.asyncio
    async def test_a_non_object_body_is_an_error_result(
        self, mock_http_client, mock_token_manager
    ):
        result, _ = await self._check(['unexpected'])

        assert result['status'] == 'error'
        assert 'Unexpected response format' in result['message']


class TestExecuteCommandWithoutWaiting:
    """wait=False submits once and hands back the command_id."""

    @staticmethod
    async def _submit(row: object, purpose: str | None = None):
        with (
            patch('tools.command_tools._submit_command', return_value=row) as submit,
            patch('tools.command_tools._get_command_result') as poll,
        ):
            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='sleep 600',
                workspace='testworkspace',
                wait=False,
                purpose=purpose,
            )
        return result, submit, poll

    @pytest.mark.asyncio
    async def test_it_returns_the_command_id_without_polling(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-w1', 'status': 'queued', 'handled_at': None}

        result, _, poll = await self._submit(row)

        assert result['status'] == 'success'
        assert result['command_id'] == 'cmd-w1'
        assert result['data'] == row
        assert result['server_id'] == VALID_SERVER_ID
        assert result['command'] == 'sleep 600'
        assert 'Do not resubmit' in result['message']
        assert 'check_command_status' in result['message']
        assert 'check_command_status' in result['next_action']
        poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_it_declines_the_purpose_demand(
        self, mock_http_client, mock_token_manager
    ):
        _, submit, _ = await self._submit({'id': 'cmd-w1'})

        assert submit.call_args.kwargs['purpose_demand_supported'] is False

    @pytest.mark.asyncio
    async def test_a_denial_stamped_at_creation_is_an_error(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-w2', 'status': 'rejected', 'handled_at': None}

        result, _, poll = await self._submit(row)

        assert result['status'] == 'error'
        assert result['message'].startswith('Command failed with status: rejected')
        assert result['command_id'] == 'cmd-w2'
        poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_hold_stamped_at_creation_returns_pending_approval(
        self, mock_http_client, mock_token_manager
    ):
        row = {'id': 'cmd-w5', 'status': 'awaiting_approval', 'handled_at': None}

        result, _, poll = await self._submit([row])

        assert result['status'] == 'pending_approval'
        assert result['command_id'] == 'cmd-w5'
        assert result['server_id'] == VALID_SERVER_ID
        poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failed_submission_is_an_error(
        self, mock_http_client, mock_token_manager
    ):
        envelope = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'response': '{"detail":"no"}',
        }

        result, _, poll = await self._submit(envelope)

        assert result['status'] == 'error'
        assert 'command_id' not in result
        poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_overlong_purpose_is_still_flagged(
        self, mock_http_client, mock_token_manager
    ):
        result, _, _ = await self._submit(
            {'id': 'cmd-w3'}, purpose='x' * (PURPOSE_MAX_LENGTH + 1)
        )

        assert result['status'] == 'success'
        assert result['purpose_truncated'] is True

    @pytest.mark.asyncio
    async def test_waiting_stays_the_default(
        self, mock_http_client, mock_token_manager
    ):
        with (
            patch('tools.command_tools._submit_command') as submit,
            patch('tools.command_tools._get_command_result') as poll,
        ):
            submit.return_value = {'id': 'cmd-w4'}
            poll.return_value = {
                'id': 'cmd-w4',
                'status': 'success',
                'handled_at': '2026-04-03T03:00:01Z',
            }
            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='uptime',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['data']['status'] == 'success'
        assert submit.call_args.kwargs['purpose_demand_supported'] is True
        poll.assert_called()


_ENV_REFUSALS = [
    (
        'command_dangerous_env',
        (
            'The command environment policy refuses `PATH`, `LD_PRELOAD`: '
            'these variables can change which program runs. Remove them, or set '
            'them inside the command (`env NAME=value cmd`).'
        ),
    ),
    (
        'command_invalid_env',
        (
            'The command environment policy refuses `BAD-NAME`: '
            'variable names must be valid environment identifiers.'
        ),
    ),
]


@pytest.mark.parametrize(('code', 'message'), _ENV_REFUSALS)
@pytest.mark.asyncio
async def test_execute_command_environment_refusal(
    mock_http_client, mock_token_manager, code, message
):
    mock_http_client.post.return_value = {
        'error': 'HTTP Error',
        'status_code': 400,
        'response': json.dumps(
            {
                'code': code,
                'field_errors': {
                    'non_field_errors': [{'code': code, 'message': message}]
                },
            }
        ),
    }
    response = await execute_command(
        server_id=VALID_SERVER_ID,
        command='true',
        workspace='testworkspace',
        region='ap1',
        env={'PATH': 'private-environment-value'},
    )
    assert response['status'] == 'error'
    assert response['error_code'] == code
    assert response['message'] == f'Command execution failed: {message}'
    assert 'private-environment-value' not in json.dumps(response)


@pytest.mark.parametrize(('code', 'message'), _ENV_REFUSALS)
@pytest.mark.parametrize('handled_at', [None, '2026-11-09T10:00:00Z'])
@pytest.mark.asyncio
async def test_execute_command_late_environment_denial(
    mock_http_client, mock_token_manager, code, message, handled_at
):
    mock_http_client.post.return_value = {'id': 'cmd-env-denied'}
    mock_http_client.get.return_value = {
        'id': 'cmd-env-denied',
        'status': 'denied',
        'denial_code': code,
        'result': message,
        'handled_at': handled_at,
    }
    response = await execute_command(
        server_id=VALID_SERVER_ID,
        command='true',
        workspace='testworkspace',
        region='ap1',
    )
    assert response['status'] == 'error'
    assert response['denial_code'] == code
    assert response['message'] == message
    assert response['command_id'] == 'cmd-env-denied'


@pytest.mark.parametrize('denial_code', [['command_invalid_env'], {'a': 1}])
@pytest.mark.asyncio
async def test_execute_command_unhashable_denial_code_keeps_normal_result(
    mock_http_client, mock_token_manager, denial_code
):
    mock_http_client.post.return_value = {'id': 'cmd-odd-code'}
    mock_http_client.get.return_value = {
        'id': 'cmd-odd-code',
        'status': 'denied',
        'denial_code': denial_code,
        'result': 'refused',
        'handled_at': '2026-11-09T10:00:00Z',
    }
    response = await execute_command(
        server_id=VALID_SERVER_ID,
        command='true',
        workspace='testworkspace',
        region='ap1',
    )
    assert response['status'] == 'success'
    assert response['command_id'] == 'cmd-odd-code'


@pytest.mark.asyncio
async def test_execute_command_description_explains_environment_policy():
    description = (await tool_descriptions())['execute_command']
    assert 'PATH, LD_*' in description
    assert 'refused by the server; set them inside the command instead' in description


class TestAssigneeLane:
    """A held command the session's assignee decides (ADR 0114)."""

    @staticmethod
    def _held(**fields: object) -> dict[str, object]:
        return {
            'id': 'cmd-a1',
            'status': 'awaiting_approval',
            'handled_at': None,
            'console_url': 'https://example.ap1.alpacon.io/commands/cmd-a1',
            **fields,
        }

    @staticmethod
    async def _execute(row: dict[str, object]) -> ToolResponse:
        with (
            patch('tools.command_tools._submit_command', return_value={'id': 'cmd-a1'}),
            patch('tools.command_tools._get_command_result', return_value=row),
        ):
            return await execute_command(
                server_id=VALID_SERVER_ID,
                command='systemctl restart nginx',
                workspace='testworkspace',
                region='ap1',
                timeout=10,
            )

    @staticmethod
    async def _check(row: dict[str, object]) -> ToolResponse:
        with patch('tools.command_tools._get_command_result', return_value=row):
            return await check_command_status(
                command_id='cmd-a1', workspace='testworkspace', region='ap1'
            )

    @pytest.mark.asyncio
    async def test_the_assignee_lane_tells_the_model_the_user_confirms(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._execute(self._held(approval_lane='assignee'))

        assert result['status'] == 'pending_approval'
        assert result['category'] == 'COMMAND_AWAITING_APPROVAL'
        assert result['approvable_by_agent'] is False
        assert result['requires_human_approval'] is True
        assert result['approval_lane'] == 'assignee'
        assert result['command_id'] == 'cmd-a1'
        assert result['next_action'] == (
            'The user must confirm this command themselves in the Alpacon web '
            'console; you cannot confirm it. Tell the user and wait, then retrieve '
            'the result with check_command_status. Do not re-run: a resubmission '
            'is held again and may double-execute the command.'
        )
        assert result['message'] == (
            "Command is waiting for the user's own confirmation. As this Work "
            "Session's assignee, the user must confirm it themselves in the "
            'Alpacon web console; it then runs automatically. Tell the user, '
            'wait, then retrieve the result with check_command_status. Do not '
            'resubmit the command: a resubmission is held again and may '
            'double-execute the command.'
        )

    @pytest.mark.asyncio
    async def test_the_assignee_lane_carries_no_judgment_or_console_link(
        self, mock_http_client, mock_token_manager
    ):
        row = self._held(
            approval_lane='assignee',
            risk_score=42,
            reasoning='low confidence on the target',
        )

        result = await self._execute(row)

        text = json.dumps(result)
        assert 'console_url' not in result
        assert 'alpacon.io/commands' not in text
        assert 'low confidence on the target' not in text
        assert 'risk_score' not in text

    @pytest.mark.asyncio
    async def test_the_assignee_lane_carries_no_file_lane_hint(
        self, mock_http_client, mock_token_manager
    ):
        row = self._held(
            approval_lane='assignee',
            file_execution_suggestion={
                'path': '/opt/deploy.sh',
                'interpreter': '/bin/bash',
                'args': [],
            },
        )

        result = await self._execute(row)

        assert 'execute_file_suggestion' not in result
        assert 'approv' not in result['message'].lower()
        assert 'execute_file' not in result['message']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('lane', [None, 'single_approver', 'auto_approve', ''])
    async def test_any_other_lane_keeps_the_approver_result(
        self, lane, mock_http_client, mock_token_manager
    ):
        baseline = await self._execute(self._held())
        fields = {} if lane is None else {'approval_lane': lane}

        result = await self._execute(self._held(**fields))

        assert result == baseline
        assert 'approval_lane' not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize('lane', ['assignee', 'single_approver', None])
    async def test_check_command_status_matches_execute_command(
        self, lane, mock_http_client, mock_token_manager
    ):
        fields = {} if lane is None else {'approval_lane': lane}
        row = self._held(**fields)

        executed = await self._execute(row)
        checked = await self._check(row)

        # Only execute_command knows it sent a shell line, so the message's
        # file-lane hint is its own; every field the lane decides is shared.
        for key in (
            'status',
            'category',
            'requires_human_approval',
            'approvable_by_agent',
            'next_action',
            'command_id',
        ):
            assert checked[key] == executed[key]
        assert checked.get('approval_lane') == executed.get('approval_lane')
        assert checked['message'] in executed['message']

    @pytest.mark.asyncio
    async def test_a_changed_rule_says_sending_it_again_applies_the_current_rule(
        self, mock_http_client, mock_token_manager
    ):
        row = _rejected_row(
            rejection_cause='approval_rule_changed', rejection_gate='approval'
        )

        result = await self._execute(row)

        expected = (
            'The approval rule changed while the command waited, so it was closed '
            'without running. Sending it again applies the current rule, which may '
            'ask a different person to decide. Ask the user whether to send it again.'
        )
        assert result['status'] == 'error'
        assert result['rejection_cause'] == 'approval_rule_changed'
        assert result['rejection_hint'] == expected
        assert result['message'] == f'Command failed with status: rejected. {expected}'


_HELD_COMMAND_ID = '0a6f4d9c-2232-4703-b924-b370229ba52f'
_HELD_REQUEST_ID = '6f1c1a52-8d0e-4a0b-9c55-0d7f1f6f2b11'
_HELD_STATUS_PATH = f'/api/events/commands/{_HELD_COMMAND_ID}/'
_HELD_DEADLINE = '2999-11-06T17:20:00+09:00'
_PASSED_DEADLINE = '2000-11-06T17:20:00+09:00'


def _held(**fields: JsonValue) -> dict[str, JsonValue]:
    held: dict[str, JsonValue] = {
        'approval_request': _HELD_REQUEST_ID,
        'expires_at': _HELD_DEADLINE,
        'status_path': _HELD_STATUS_PATH,
    }
    held.update(fields)
    return held


def _sudo_held_row(**fields: JsonValue) -> dict[str, JsonValue]:
    """A finished command whose sudo the plugin denied pending approval."""
    row: dict[str, JsonValue] = {
        'id': _HELD_COMMAND_ID,
        'status': 'completed',
        'success': False,
        'exit_code': 1,
        'result': 'Alpacon denied this sudo command (SUDO_APPROVAL_REQUIRED).\n',
        'handled_at': '2026-11-06T17:10:01+09:00',
        'sudo_approval_request_id': _HELD_REQUEST_ID,
        'sudo_grant_status': 'pending_approval',
    }
    row.update(fields)
    return row


def _denial_lines(*codes: str) -> str:
    return ''.join(f'Alpacon denied this sudo command ({code}).\n' for code in codes)


# Both lines in the output mean both sudo calls ran; `&&` would stop at the first.
_HARD_AND_PENDING = [
    ['SUDO_RISK_DENIED', 'SUDO_APPROVAL_REQUIRED'],
    ['SUDO_APPROVAL_REQUIRED', 'SUDO_RISK_DENIED'],
]
_HARD_AND_PENDING_IDS = ['sudo hard || sudo pending', 'sudo pending; sudo hard']

_TODAYS_SUDO_DENIAL = pending_approval_response(
    _SUDO_DENIAL_HINTS['SUDO_APPROVAL_REQUIRED'], category='SUDO_APPROVAL_REQUIRED'
)


class TestHeldSudoApproval:
    """The command detail's `held` rides the sudo pending result (#469)."""

    @staticmethod
    async def _check(mock_http_client: MagicMock, row: object) -> ToolResponse:
        mock_http_client.get.return_value = row
        return await check_command_status(
            command_id=_HELD_COMMAND_ID, workspace='testworkspace', region='ap1'
        )

    @pytest.mark.asyncio
    async def test_check_command_status_carries_the_held_approval(
        self, mock_http_client, mock_token_manager
    ):
        result = await self._check(mock_http_client, _sudo_held_row(held=_held()))

        denial = result['sudo_denial']
        assert result['status'] == 'success'
        assert denial['status'] == 'pending_approval'
        assert denial['approvable_by_agent'] is False
        assert denial['held'] == _held()
        assert f'decided by {_HELD_DEADLINE}' in denial['wait_hint']
        assert (
            'reads authorized only after that time, ask the user' in denial['wait_hint']
        )
        assert (
            f'check_command_status with command_id {_HELD_COMMAND_ID}'
            in denial['wait_hint']
        )
        assert 'sudo_grant_status' in denial['wait_hint']
        assert 're-submit the whole command' in denial['wait_hint']
        assert 'held turning null does not end the wait' in denial['wait_hint']
        assert 'not a place to wait' in denial['wait_hint']
        assert 'denied outright' not in denial['wait_hint']
        assert 'follow only the newest' not in denial['wait_hint']
        mock_http_client.get.assert_awaited_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=_HELD_STATUS_PATH,
            token=ANY,
        )

    @pytest.mark.asyncio
    async def test_execute_command_carries_the_held_approval(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = _sudo_held_row(held=_held())

        with patch(
            'tools.command_tools._submit_command',
            return_value={'id': _HELD_COMMAND_ID},
        ):
            result = await execute_command(
                server_id=VALID_SERVER_ID,
                command='sudo systemctl restart nginx',
                workspace='testworkspace',
                timeout=10,
            )

        assert result['sudo_denial']['held'] == _held()
        assert _HELD_COMMAND_ID in result['sudo_denial']['wait_hint']

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'held_field',
        [{}, {'held': None}],
        ids=['an older server sends no key', 'held null after a cancel'],
    )
    async def test_no_held_keeps_todays_sudo_denial(
        self, held_field, mock_http_client, mock_token_manager
    ):
        result = await self._check(mock_http_client, _sudo_held_row(**held_field))

        assert result['status'] == 'success'
        assert result['sudo_denial'] == _TODAYS_SUDO_DENIAL
        assert result['data']['sudo_grant_status'] == 'pending_approval'

    @pytest.mark.asyncio
    async def test_a_null_expiry_is_reported_as_no_known_deadline(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(expires_at=None))

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert denial['held'] == _held(expires_at=None)
        assert 'no deadline' in denial['wait_hint']
        assert 'check_command_status' in denial['wait_hint']

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'expires_at',
        ['next tuesday', '2999-11-06T17:20:00', 42],
        ids=['not a datetime', 'no offset', 'not a string'],
    )
    async def test_an_unreadable_expiry_is_not_reported_as_a_deadline(
        self, expires_at, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(expires_at=expires_at))

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert denial['held']['expires_at'] is None
        assert 'no deadline' in denial['wait_hint']

    @pytest.mark.asyncio
    async def test_a_passed_deadline_asks_the_user_instead_of_waiting(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(expires_at=_PASSED_DEADLINE))

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert denial['held'] == {
            'approval_request': _HELD_REQUEST_ID,
            'expires_at': _PASSED_DEADLINE,
        }
        assert f'deadline ({_PASSED_DEADLINE}) has passed' in denial['wait_hint']
        assert 'ask the user whether to re-submit' in denial['wait_hint']
        assert 'check_command_status' not in denial['wait_hint']
        assert denial['message'] == denial['wait_hint']
        assert result['sudo_hint'] == denial['wait_hint']
        assert denial['next_action'] == (
            'Do not wait on this approval, since its deadline has passed, and do '
            'not re-submit on your own: ask the user whether to re-submit the '
            'whole command, which requests a new approval.'
        )
        assert denial['status'] == 'pending_approval'
        assert denial['approvable_by_agent'] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'status_path',
        [
            '/api/events/../servers/',
            '/api/events/commands/./x/',
            'https://evil.example.com/api/events/commands/cmd-1/',
            '//evil.example.com/api/events/commands/cmd-1/',
            'api/events/commands/cmd-1/',
            '/api/events/commands/cmd-1/?approve=1',
            '/' + 'a' * 256,
            None,
        ],
        ids=[
            'dot-dot segment',
            'dot segment',
            'absolute URL',
            'scheme-relative URL',
            'not self-relative',
            'query string',
            'over 256 characters',
            'not a string',
        ],
    )
    async def test_an_unsafe_status_path_is_not_passed_on(
        self, status_path, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(status_path=status_path))

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert denial['held'] == {
            'approval_request': _HELD_REQUEST_ID,
            'expires_at': _HELD_DEADLINE,
        }
        assert 'check_command_status' in denial['wait_hint']

    @pytest.mark.asyncio
    async def test_an_approval_request_that_is_not_a_uuid_is_not_passed_on(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(approval_request='approve me now'))

        result = await self._check(mock_http_client, row)

        assert 'approval_request' not in result['sudo_denial']['held']
        assert result['sudo_denial']['held']['status_path'] == _HELD_STATUS_PATH

    @pytest.mark.asyncio
    async def test_a_hard_denial_alone_ignores_held(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(), result=_denial_lines('SUDO_RISK_DENIED'))

        result = await self._check(mock_http_client, row)

        assert result['status'] == 'success'
        assert 'sudo_denial' not in result
        assert result['sudo_hint'] == _SUDO_DENIAL_HINTS['SUDO_RISK_DENIED']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('codes', _HARD_AND_PENDING, ids=_HARD_AND_PENDING_IDS)
    @pytest.mark.parametrize(
        'held_field',
        [{}, {'held': None}],
        ids=['an older server sends no key', 'held null'],
    )
    async def test_a_hard_denial_without_held_reports_only_the_hard_denial(
        self, codes, held_field, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(result=_denial_lines(*codes), **held_field)

        result = await self._check(mock_http_client, row)

        assert result['status'] == 'success'
        assert 'sudo_denial' not in result
        assert result['sudo_hint'] == _SUDO_DENIAL_HINTS['SUDO_RISK_DENIED']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('codes', _HARD_AND_PENDING, ids=_HARD_AND_PENDING_IDS)
    async def test_a_hard_denial_beside_a_held_approval_keeps_the_approval(
        self, codes, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=_held(), result=_denial_lines(*codes))

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert result['status'] == 'success'
        assert result['sudo_hint'] == _SUDO_DENIAL_HINTS['SUDO_RISK_DENIED']
        assert denial['category'] == 'SUDO_APPROVAL_REQUIRED'
        assert denial['next_action'] == _TODAYS_SUDO_DENIAL['next_action']
        assert denial['held'] == _held()
        assert (
            'denied outright (SUDO_RISK_DENIED) and is denied again on a re-submission'
            in denial['wait_hint']
        )
        assert 'follow only the newest' not in denial['wait_hint']

    @pytest.mark.asyncio
    async def test_a_hard_denial_beside_a_lapsed_approval_keeps_asking_the_user(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(
            held=_held(expires_at=_PASSED_DEADLINE),
            result=_denial_lines('SUDO_RISK_DENIED', 'SUDO_APPROVAL_REQUIRED'),
        )

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert result['status'] == 'success'
        assert result['sudo_hint'] == _SUDO_DENIAL_HINTS['SUDO_RISK_DENIED']
        assert 'ask the user whether to re-submit' in denial['next_action']
        assert 'ask the user whether to re-submit' in denial['message']
        assert 'denied outright (SUDO_RISK_DENIED)' in denial['wait_hint']

    @pytest.mark.asyncio
    async def test_several_pending_denials_say_held_names_only_the_newest(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(
            held=_held(),
            result=_denial_lines('SUDO_INTENT_DEVIATION', 'SUDO_APPROVAL_REQUIRED'),
        )

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert result['status'] == 'success'
        assert denial['category'] == 'SUDO_INTENT_DEVIATION'
        assert result['sudo_hint'] == denial['message']
        assert 'follow only the newest approval' in denial['wait_hint']
        assert 'denied outright' not in denial['wait_hint']

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('grant_status', 'says'),
        [
            ('authorized', 'Re-submit the whole command, unless a held.expires_at'),
            ('rejected', 'Do not re-submit the command; tell the user.'),
            ('expired', 'ask the user whether to re-submit'),
        ],
    )
    async def test_a_settled_grant_replaces_the_wait_once_held_is_null(
        self, grant_status, says, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(held=None, sudo_grant_status=grant_status)

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert result['status'] == 'success'
        assert denial['category'] == 'SUDO_APPROVAL_REQUIRED'
        assert says in denial['message']
        assert denial['next_action'] == denial['message']
        assert result['sudo_hint'] == denial['message']
        assert 'held' not in denial

    @pytest.mark.asyncio
    async def test_a_settled_grant_after_several_pending_denials_warns_of_the_others(
        self, mock_http_client, mock_token_manager
    ):
        row = _sudo_held_row(
            held=None,
            sudo_grant_status='authorized',
            result=_denial_lines('SUDO_INTENT_DEVIATION', 'SUDO_APPROVAL_REQUIRED'),
        )

        result = await self._check(mock_http_client, row)

        denial = result['sudo_denial']
        assert result['status'] == 'success'
        assert 'Re-submit the whole command' in denial['next_action']
        assert 'follow only the newest approval' in denial['next_action']

    @pytest.mark.asyncio
    async def test_list_commands_keeps_todays_denial_for_a_settled_grant(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [_sudo_held_row(sudo_grant_status='rejected')],
        }

        result = await list_commands(workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data']['results'][0]['sudo_denial'] == _TODAYS_SUDO_DENIAL

    @pytest.mark.asyncio
    async def test_list_commands_keeps_its_result_even_when_a_row_carries_held(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'count': 1,
            'results': [_sudo_held_row(held=_held())],
        }

        result = await list_commands(workspace='testworkspace')

        assert result['data']['results'][0]['sudo_denial'] == _TODAYS_SUDO_DENIAL
