"""Unit tests for the command pre-approval ledger tools, against a stubbed ledger."""

import json
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import http_client_fixture
from tools.ledger_tools import (
    disable_ledger_entry,
    enable_ledger_entry,
    get_ledger_capability,
    grant_ledger_admin,
    issue_ledger_entries,
    list_ledger_admins,
    list_ledger_entries,
    revoke_ledger_admin,
    revoke_ledger_entries,
    revoke_ledger_entry,
)
from utils.ledger_auth import AUTHORIZATION_REQUIRED, LedgerTarget

WORKSPACE_ID = '11111111-2222-3333-4444-555555555555'
ENTRY_ID = '7e3984de-49ab-4cc6-bcdf-21fbd35858b8'
SECOND_ENTRY_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
SERVICE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440001'
LEDGER = 'https://alpacon.ai/api/acl/'

AI_ENV = {
    'auth0': {
        'method': 'auth0',
        'client_id': 'cli-client',
        'domain': 'auth.example.com',
        'audience': 'https://alpacon.io/',
        'schema_name': 'testworkspace',
        'workspace_id': WORKSPACE_ID,
    },
    'language': 'en',
    'command_acl_surface': 'ai',
}

PENDING = {
    'status': AUTHORIZATION_REQUIRED,
    'message': 'sign in',
    'verification_uri_complete': 'https://auth.example.com/activate?user_code=X',
    'verification_uri': 'https://auth.example.com/activate',
    'user_code': 'X',
    'expires_in': 900,
    'requires_human_action': True,
}

mock_http_client = http_client_fixture('tools.ledger_tools')


@pytest.fixture
def ledger(mock_http_client, mock_token_manager, monkeypatch):
    """A workspace on the `ai` surface whose ledger token is already authorized."""
    monkeypatch.delenv('ALPACON_MCP_LEDGER_URL', raising=False)
    mock_http_client.get.return_value = AI_ENV
    mock_http_client.request = AsyncMock(return_value={'ok': True})
    authorizer = MagicMock()
    authorizer.token_for = AsyncMock(return_value='ledger-jwt')
    with patch('tools.ledger_tools.ledger_authorizer', authorizer):
        yield mock_http_client, authorizer


def _request(mock_http_client):
    call = mock_http_client.request.call_args
    return call.args[0], call.args[1], call.kwargs


class TestSurface:
    @pytest.mark.asyncio
    async def test_reads_the_surface_from_the_auth_env(self, ledger):
        client, _ = ledger

        await list_ledger_entries(workspace='testworkspace', region='ap1')

        client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/env/',
            token='test-token',
            params={'client': 'cli'},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'env',
        [
            {**AI_ENV, 'command_acl_surface': 'upstream'},
            # A server that predates the ledger does not send the field.
            {k: v for k, v in AI_ENV.items() if k != 'command_acl_surface'},
        ],
    )
    async def test_upstream_points_to_the_command_acl_tools(self, ledger, env):
        client, _ = ledger
        client.get.return_value = env

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['command_acl_surface'] == 'upstream'
        assert 'create_command_acl' in result['message']
        client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_capability_on_upstream_is_a_success(self, ledger):
        client, authorizer = ledger
        client.get.return_value = {**AI_ENV, 'command_acl_surface': 'upstream'}

        result = await get_ledger_capability(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['command_acl_surface'] == 'upstream'
        assert 'list_command_acls' in result['message']
        authorizer.token_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_mode_is_refused(self, ledger):
        client, authorizer = ledger
        with patch('tools.ledger_tools.is_auth_enabled', return_value=True):
            result = await issue_ledger_entries(
                workspace='testworkspace',
                region='ap1',
                entries=[
                    {
                        'principal_type': 'service_token',
                        'principal_id': SERVICE_TOKEN_ID,
                        'command_pattern': 'uptime',
                        'username': '*',
                    }
                ],
            )

        assert result['status'] == 'error'
        assert 'local (stdio)' in result['message']
        assert 'Pre-approved commands' in result['message']
        authorizer.token_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_capability_in_remote_mode_is_refused(self, ledger):
        _, authorizer = ledger
        with patch('tools.ledger_tools.is_auth_enabled', return_value=True):
            result = await get_ledger_capability(
                workspace='testworkspace', region='ap1'
            )

        assert result['status'] == 'error'
        assert result['command_acl_surface'] == 'ai'
        authorizer.token_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_workspace_without_auth0_is_refused(self, ledger):
        client, authorizer = ledger
        client.get.return_value = {
            'auth0': {'method': 'local'},
            'command_acl_surface': 'ai',
        }

        result = await list_ledger_admins(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert 'Auth0' in result['message']
        authorizer.token_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_auth_env_failure_passes_through(self, ledger):
        client, _ = ledger
        client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.NOT_FOUND,
            'message': 'Not found',
        }

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        client.request.assert_not_called()


class TestAuthorization:
    @pytest.mark.asyncio
    async def test_authorization_required_is_returned_without_a_ledger_call(
        self, ledger
    ):
        client, authorizer = ledger
        authorizer.token_for.return_value = PENDING

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert result['status'] == AUTHORIZATION_REQUIRED
        assert (
            result['verification_uri_complete'] == PENDING['verification_uri_complete']
        )
        assert result['workspace'] == 'testworkspace'
        assert result['region'] == 'ap1'
        client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_target_is_the_workspace_org(self, ledger):
        _, authorizer = ledger

        await list_ledger_entries(workspace='testworkspace', region='ap1')

        authorizer.token_for.assert_awaited_once_with(
            LedgerTarget(
                domain='auth.example.com',
                client_id='cli-client',
                org_name='testworkspace',
                workspace_id=WORKSPACE_ID,
            )
        )

    @pytest.mark.asyncio
    async def test_a_ledger_401_forgets_the_token_and_asks_again(self, ledger):
        client, authorizer = ledger
        authorizer.token_for.side_effect = ['ledger-jwt', PENDING]
        client.request.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.UNAUTHORIZED,
            'message': 'Unauthorized',
        }

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        authorizer.forget.assert_called_once()
        assert result['status'] == AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_a_ledger_error_carries_its_detail(self, ledger):
        client, _ = ledger
        body = {'workspace_id': ['This account does not administer that workspace.']}
        client.request.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.BAD_REQUEST,
            'message': "Client error '400 Bad Request'",
            'response': json.dumps(body),
        }

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.BAD_REQUEST
        assert result['detail'] == body

    @pytest.mark.asyncio
    async def test_a_non_json_error_has_no_detail(self, ledger):
        client, _ = ledger
        client.request.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'Forbidden',
            'response': '<html>',
        }

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert 'detail' not in result


class TestCapability:
    @pytest.mark.asyncio
    async def test_reports_admin_of_this_workspace(self, ledger):
        client, _ = ledger
        client.request.return_value = {
            'is_ledger_admin': True,
            'workspace_ids': [WORKSPACE_ID],
        }

        result = await get_ledger_capability(workspace='testworkspace', region='ap1')

        assert _request(client)[:2] == ('GET', f'{LEDGER}me/')
        assert result['status'] == 'success'
        assert result['command_acl_surface'] == 'ai'
        assert result['is_ledger_admin'] is True
        assert result['administers_workspace'] is True
        assert result['workspace_id'] == WORKSPACE_ID

    @pytest.mark.asyncio
    async def test_an_admin_elsewhere_does_not_administer_this_workspace(self, ledger):
        client, _ = ledger
        client.request.return_value = {
            'is_ledger_admin': True,
            'workspace_ids': [SECOND_ENTRY_ID],
        }

        result = await get_ledger_capability(workspace='testworkspace', region='ap1')

        assert result['is_ledger_admin'] is True
        assert result['administers_workspace'] is False

    @pytest.mark.asyncio
    async def test_authorization_required_passes_through(self, ledger):
        _, authorizer = ledger
        authorizer.token_for.return_value = PENDING

        result = await get_ledger_capability(workspace='testworkspace', region='ap1')

        assert result['status'] == AUTHORIZATION_REQUIRED


class TestEntries:
    @pytest.mark.asyncio
    async def test_list_names_the_workspace_and_filters(self, ledger):
        client, _ = ledger

        result = await list_ledger_entries(
            workspace='testworkspace',
            region='ap1',
            principal_type='service_token',
            principal_id=SERVICE_TOKEN_ID,
            page=2,
            page_size=50,
        )

        method, url, kwargs = _request(client)
        assert (method, url) == ('GET', f'{LEDGER}entries/')
        assert kwargs['token'] == 'ledger-jwt'
        assert kwargs['params'] == {
            'workspace_id': WORKSPACE_ID,
            'principal_type': 'service_token',
            'principal_id': SERVICE_TOKEN_ID,
            'page': 2,
            'page_size': 50,
        }
        assert result['status'] == 'success'
        assert result['data'] == {'ok': True}

    @pytest.mark.asyncio
    async def test_the_ledger_url_can_be_overridden(self, ledger, monkeypatch):
        client, _ = ledger
        monkeypatch.setenv('ALPACON_MCP_LEDGER_URL', 'https://ledger.test/')

        await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert _request(client)[1] == 'https://ledger.test/api/acl/entries/'

    @pytest.mark.asyncio
    async def test_issue_sends_the_bulk_envelope(self, ledger):
        client, _ = ledger
        entry = {
            'principal_type': 'service_token',
            'principal_id': SERVICE_TOKEN_ID,
            'command_pattern': 'systemctl restart nginx',
            'username': 'root',
            'server_ids': [ENTRY_ID],
        }

        result = await issue_ledger_entries(
            workspace='testworkspace', region='ap1', entries=[entry]
        )

        method, url, kwargs = _request(client)
        assert (method, url) == ('POST', f'{LEDGER}entries/bulk/')
        assert kwargs['json_data'] == {
            'workspace_id': WORKSPACE_ID,
            'entries': [entry],
        }
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_issue_refuses_an_empty_batch(self, ledger):
        client, _ = ledger

        result = await issue_ledger_entries(
            workspace='testworkspace', region='ap1', entries=[]
        )

        assert result['status'] == 'error'
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_issue_refuses_an_oversized_batch(self, ledger):
        client, _ = ledger
        entry = {
            'principal_type': 'service_token',
            'principal_id': SERVICE_TOKEN_ID,
            'command_pattern': 'uptime',
            'username': '*',
        }

        result = await issue_ledger_entries(
            workspace='testworkspace', region='ap1', entries=[entry] * 201
        )

        assert result['status'] == 'error'
        assert '200' in result['message']
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_one(self, ledger):
        client, _ = ledger
        client.request.return_value = {'status': 'success', 'status_code': 204}

        result = await revoke_ledger_entry(
            workspace='testworkspace', region='ap1', entry_id=ENTRY_ID
        )

        assert _request(client)[:2] == ('DELETE', f'{LEDGER}entries/{ENTRY_ID}/')
        assert result['status'] == 'success'
        assert result['entry_id'] == ENTRY_ID

    @pytest.mark.asyncio
    async def test_revoke_rejects_a_path_escaping_id(self, ledger):
        client, _ = ledger

        result = await revoke_ledger_entry(
            workspace='testworkspace', region='ap1', entry_id='../admins'
        )

        assert result['status'] == 'error'
        client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_several(self, ledger):
        client, _ = ledger
        client.request.return_value = {'revoked': 2}

        result = await revoke_ledger_entries(
            workspace='testworkspace',
            region='ap1',
            entry_ids=[ENTRY_ID, SECOND_ENTRY_ID],
        )

        method, url, kwargs = _request(client)
        assert (method, url) == ('POST', f'{LEDGER}entries/bulk/delete/')
        assert kwargs['json_data'] == {'ids': [ENTRY_ID, SECOND_ENTRY_ID]}
        assert result['data'] == {'revoked': 2}

    @pytest.mark.asyncio
    async def test_revoke_several_refuses_an_empty_list(self, ledger):
        client, _ = ledger

        result = await revoke_ledger_entries(
            workspace='testworkspace', region='ap1', entry_ids=[]
        )

        assert result['status'] == 'error'
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_several_refuses_an_oversized_list(self, ledger):
        client, _ = ledger

        result = await revoke_ledger_entries(
            workspace='testworkspace', region='ap1', entry_ids=[ENTRY_ID] * 201
        )

        assert result['status'] == 'error'
        client.get.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('tool', 'action'),
        [(disable_ledger_entry, 'disable'), (enable_ledger_entry, 'enable')],
    )
    async def test_disable_and_enable(self, ledger, tool, action):
        client, _ = ledger

        result = await tool(workspace='testworkspace', region='ap1', entry_id=ENTRY_ID)

        method, url, kwargs = _request(client)
        assert (method, url) == ('POST', f'{LEDGER}entries/{ENTRY_ID}/{action}/')
        assert kwargs['json_data'] is None
        assert result['status'] == 'success'
        assert result['entry_id'] == ENTRY_ID


class TestAdmins:
    @pytest.mark.asyncio
    async def test_list(self, ledger):
        client, _ = ledger

        await list_ledger_admins(
            workspace='testworkspace', region='ap1', page=1, page_size=20
        )

        method, url, kwargs = _request(client)
        assert (method, url) == ('GET', f'{LEDGER}admins/')
        assert kwargs['params'] == {
            'workspace_id': WORKSPACE_ID,
            'page': 1,
            'page_size': 20,
        }

    @pytest.mark.asyncio
    async def test_grant(self, ledger):
        client, _ = ledger

        result = await grant_ledger_admin(
            workspace='testworkspace',
            region='ap1',
            subject='auth0|abc',
            email='kim@example.com',
        )

        method, url, kwargs = _request(client)
        assert (method, url) == ('POST', f'{LEDGER}admins/')
        assert kwargs['json_data'] == {
            'workspace_id': WORKSPACE_ID,
            'subject': 'auth0|abc',
            'email': 'kim@example.com',
        }
        assert result['status'] == 'success'

    @pytest.mark.asyncio
    async def test_grant_refuses_an_empty_subject(self, ledger):
        client, _ = ledger

        result = await grant_ledger_admin(
            workspace='testworkspace', region='ap1', subject='  '
        )

        assert result['status'] == 'error'
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke(self, ledger):
        client, _ = ledger
        admin_id = SECOND_ENTRY_ID

        result = await revoke_ledger_admin(
            workspace='testworkspace', region='ap1', admin_id=admin_id
        )

        assert _request(client)[:2] == ('DELETE', f'{LEDGER}admins/{admin_id}/')
        assert result['admin_id'] == admin_id
