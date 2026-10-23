"""Unit tests for the command pre-approval ledger tools, against a stubbed ledger."""

import importlib
import json
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import server
from tests.conftest import http_client_fixture
from tools import resources as res
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
from tools.security_tools import _command_acl_list_note, _command_acl_moved_note
from utils import declared_agent
from utils.common import unwrap_http_result
from utils.ledger_auth import (
    AUTHORIZATION_REQUIRED,
    LedgerAuthorizer,
    LedgerTarget,
    _CachedToken,
)
from utils.recovery_hints import get_recovery_hints

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

UNAUTHORIZED_BODY = {'detail': 'Invalid token audience.'}
UNAUTHORIZED_ENVELOPE = {
    'error': 'HTTP Error',
    'status_code': HTTPStatus.UNAUTHORIZED,
    'message': 'Unauthorized',
    'response': json.dumps(UNAUTHORIZED_BODY),
}

mock_http_client = http_client_fixture('tools.ledger_tools')


@pytest.fixture
def ledger(mock_http_client, mock_token_manager, monkeypatch):
    """A workspace on the `ai` surface whose ledger token is already authorized."""
    monkeypatch.delenv('ALPACON_MCP_LEDGER_URL', raising=False)
    monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'stdio')
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
        assert 'stdio MCP server' in result['message']
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


TARGET = LedgerTarget(
    domain='auth.example.com',
    client_id='cli-client',
    org_name='testworkspace',
    workspace_id=WORKSPACE_ID,
)


class TestStdioOnly:
    """A network transport may share one process, and so one sign-in cache,
    between callers; the ledger tools must refuse there before touching it."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize('cached', [True, False])
    @pytest.mark.parametrize('transport', ['sse', 'streamable-http', None])
    async def test_a_network_or_unknown_transport_never_reaches_the_cache(
        self, mock_http_client, mock_token_manager, monkeypatch, cached, transport
    ):
        monkeypatch.delenv('ALPACON_MCP_AUTH_ENABLED', raising=False)
        if transport is None:
            monkeypatch.delenv('ALPACON_MCP_TRANSPORT', raising=False)
        else:
            monkeypatch.setenv('ALPACON_MCP_TRANSPORT', transport)
        mock_http_client.get.return_value = AI_ENV
        mock_http_client.request = AsyncMock()
        authorizer = LedgerAuthorizer()
        if cached:
            # Another caller of the same process signed in first.
            authorizer._tokens[TARGET.key] = _CachedToken('first-person', 1e12)
        spy = AsyncMock(wraps=authorizer.token_for)

        with (
            patch('tools.ledger_tools.ledger_authorizer', authorizer),
            patch.object(authorizer, 'token_for', spy),
        ):
            listed = await list_ledger_entries(workspace='testworkspace', region='ap1')
            capability = await get_ledger_capability(
                workspace='testworkspace', region='ap1'
            )

        for result in (listed, capability):
            assert result['status'] == 'error'
            assert 'stdio MCP server' in result['message']
            assert 'Pre-approved commands' in result['message']
        spy.assert_not_called()
        mock_http_client.request.assert_not_called()

    @pytest.mark.parametrize(
        ('transport', 'registered'), [('sse', False), ('stdio', True)]
    )
    def test_the_toolset_is_registered_on_stdio_only(
        self, monkeypatch, transport, registered
    ):
        imported: list[str] = []
        real_import = importlib.import_module
        handed: dict = {}

        def spy(name, *args, **kwargs):
            imported.append(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(server.importlib, 'import_module', spy)
        monkeypatch.setattr(res, 'register_resources', lambda m: handed.update(m=m))
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', 'restored-on-teardown')
        monkeypatch.delenv('ALPACON_MCP_AUTH_ENABLED', raising=False)
        monkeypatch.setattr(declared_agent, '_environment_fallback', False)

        server.prepare(transport, toolsets='ledger')

        assert ('tools.ledger_tools' in imported) is registered
        assert ('ledger_tools' in handed['m']) is registered


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
        authorizer.has_token.return_value = True  # cached by an earlier call
        authorizer.token_for.side_effect = ['ledger-jwt', PENDING]
        client.request.return_value = UNAUTHORIZED_ENVELOPE

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        authorizer.forget.assert_called_once()
        assert authorizer.token_for.await_count == 2
        assert result['status'] == AUTHORIZATION_REQUIRED
        assert result['detail'] == UNAUTHORIZED_BODY

    @pytest.mark.asyncio
    async def test_a_401_on_a_token_this_call_obtained_does_not_loop(self, ledger):
        """A token the ledger refuses right after sign-in (a wrong audience,
        say) would be refused again; another link would only repeat that."""
        client, authorizer = ledger
        authorizer.has_token.return_value = False  # issued by this call's poll
        client.request.return_value = UNAUTHORIZED_ENVELOPE

        result = await list_ledger_entries(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.UNAUTHORIZED
        assert 'ALPACON_MCP_LEDGER_AUDIENCE' in result['message']
        assert result['detail'] == UNAUTHORIZED_BODY
        assert result['workspace'] == 'testworkspace'
        authorizer.forget.assert_called_once()
        authorizer.token_for.assert_awaited_once()

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
    async def test_issue_refuses_an_api_token_entry_before_any_request(self, ledger):
        client, authorizer = ledger
        service_entry = {
            'principal_type': 'service_token',
            'principal_id': SERVICE_TOKEN_ID,
            'command_pattern': 'uptime',
            'username': '*',
        }
        api_token_entry = {**service_entry, 'principal_type': 'api_token'}

        result = await issue_ledger_entries(
            workspace='testworkspace',
            region='ap1',
            entries=[service_entry, api_token_entry],
        )

        assert result['status'] == 'error'
        assert 'personal API token has no command list' in result['message']
        assert '[1]' in result['message']
        client.get.assert_not_called()
        client.request.assert_not_called()
        authorizer.token_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_api_token_entry_is_refused_with_the_reason_through_the_sdk(
        self, ledger
    ):
        """The SDK validates arguments against the schema first, so the reason
        reaches the caller only if the schema lets the value through."""
        client, authorizer = ledger

        result = await server.mcp.call_tool(
            'issue_ledger_entries',
            {
                'workspace': 'testworkspace',
                'region': 'ap1',
                'entries': [
                    {
                        'principal_type': 'api_token',
                        'principal_id': SERVICE_TOKEN_ID,
                        'command_pattern': 'uptime',
                        'username': '*',
                    }
                ],
            },
        )

        payload = result.structured_content
        assert payload['status'] == 'error'
        assert 'personal API token has no command list' in payload['message']
        client.get.assert_not_called()
        client.request.assert_not_called()
        authorizer.token_for.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_schema_says_only_service_token_can_be_issued(self):
        tools = {t.name: t for t in await server.mcp.list_tools()}
        tool = tools['issue_ledger_entries']
        field = tool.input_schema['$defs']['LedgerEntryInput']['properties'][
            'principal_type'
        ]

        assert field['type'] == 'string'
        assert "'service_token'" in field['description']
        assert 'cannot be issued' in tool.description

    @pytest.mark.asyncio
    async def test_list_still_filters_by_api_token(self, ledger):
        client, _ = ledger

        result = await list_ledger_entries(
            workspace='testworkspace', region='ap1', principal_type='api_token'
        )

        assert result['status'] == 'success'
        assert _request(client)[2]['params']['principal_type'] == 'api_token'

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


class TestTransportAwarePointers:
    """Only a stdio server registers the ledger tools, so nothing returned on
    another transport may tell the caller to use them."""

    MOVED = {
        'error': 'HTTP Error',
        'status_code': HTTPStatus.METHOD_NOT_ALLOWED,
        'message': "Client error '405 Method Not Allowed'",
        'response': '{"code": "command_acl_moved"}',
    }

    @pytest.mark.parametrize(('transport', 'named'), [('stdio', True), ('sse', False)])
    def test_command_acl_moved_hint(self, monkeypatch, transport, named):
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', transport)

        result = unwrap_http_result(self.MOVED, default_message='failed')

        assert result is not None
        assert 'web console' in result['message']
        assert 'personal API token has no command list' in result['message']
        assert ('issue_ledger_entries' in result['message']) is named

    @pytest.mark.parametrize(('transport', 'named'), [('stdio', True), ('sse', False)])
    def test_recovery_hints(self, monkeypatch, transport, named):
        monkeypatch.setenv('ALPACON_MCP_TRANSPORT', transport)

        hints = get_recovery_hints(
            HTTPStatus.FORBIDDEN, 'command ACL denied', tool_name='execute_command'
        )

        assert 'list_command_acls' in hints['related_tools']
        assert ('issue_ledger_entries' in hints['related_tools']) is named
        assert ('get_ledger_capability' in hints['related_tools']) is named
        text = ' '.join(hints['recovery_hints'])
        assert 'web console' in text
        assert ('issue_ledger_entries' in text) is named

    @pytest.mark.parametrize('stdio', [True, False])
    def test_command_acl_tool_notes(self, stdio):
        moved = _command_acl_moved_note(stdio)
        listed = _command_acl_list_note(stdio)

        assert 'web console' in moved
        assert 'personal API token has no command list' in moved
        assert ('issue_ledger_entries' in moved) is stdio
        assert ('list_ledger_entries' in listed) is stdio
        assert ('web console' in listed) is not stdio
