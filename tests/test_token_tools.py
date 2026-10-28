"""Unit tests for API token management tools."""

import inspect
from http import HTTPStatus
from unittest.mock import patch

import pytest

from server import mcp
from tests.conftest import http_client_fixture
from tools.token_tools import (
    create_api_token,
    delete_api_token,
    duplicate_api_token,
    get_api_token,
    list_api_token_presets,
    list_api_token_scopes,
    list_api_tokens,
    rotate_api_token,
    update_api_token,
)

mock_http_client = http_client_fixture('tools.token_tools')

DELETE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440001'
DELETE_RESPONSE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440002'
UNKNOWN_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440099'
DUPLICATE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440003'
DUPLICATE_EMPTY_NAME_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440005'
DUPLICATE_RESPONSE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440004'
GET_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440010'
UPDATE_TOGGLE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440020'
UPDATE_ALL_FIELDS_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440021'
CLEAR_EXPIRES_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440024'
CLEAR_EXPIRES_WITH_FIELDS_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440027'
CLEAR_AND_SET_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440025'
CLEAR_FALSE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440026'
NO_FIELDS_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440022'
HTTP_ERROR_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440023'
NON_JWT_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440000'
ROTATE_TOKEN_ID = '550e8400-e29b-41d4-a716-446655440006'


@pytest.fixture
def mock_token_manager():
    """Most token tools stack @require_jwt_auth, which conftest's 'test-token' fails."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'header.payload.signature'
        yield mock_manager


class TestListApiTokens:
    def test_list_api_tokens_has_no_remote_ip_filter(self):
        """The server dropped remote_ip, and django-filter discards it silently."""
        assert 'remote_ip' not in inspect.signature(list_api_tokens).parameters

    @pytest.mark.asyncio
    async def test_list_api_tokens_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'tok-1', 'name': 'Token A'},
                {'id': 'tok-2', 'name': 'Token B'},
            ],
        }

        result = await list_api_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_api_tokens_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'count': 10, 'results': []}

        result = await list_api_tokens(
            workspace='testworkspace', region='ap1', page=2, page_size=5
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            params={'page': 2, 'page_size': 5},
        )

    @pytest.mark.asyncio
    async def test_list_api_tokens_with_filters(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_api_tokens(
            workspace='testworkspace',
            region='ap1',
            name='deploy-bot',
            enabled=True,
            search='deploy',
            ordering='-updated_at',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            params={
                'name': 'deploy-bot',
                'enabled': True,
                'search': 'deploy',
                'ordering': '-updated_at',
            },
        )

    @pytest.mark.asyncio
    async def test_list_api_tokens_enabled_false_forwarded(
        self, mock_http_client, mock_token_manager
    ):
        """Test that enabled=False is still forwarded (not treated as missing)."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        await list_api_tokens(workspace='testworkspace', region='ap1', enabled=False)

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            params={'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_list_api_tokens_http_error(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'Permission denied',
        }

        result = await list_api_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'


class TestCreateApiToken:
    @pytest.mark.asyncio
    async def test_create_api_token_success(self, mock_http_client, mock_token_manager):
        mock_http_client.post.return_value = {
            'id': 'tok-new',
            'name': 'My Token',
            'key': 'secret-key-value',
        }

        result = await create_api_token(
            workspace='testworkspace', region='ap1', name='My Token'
        )

        assert result['status'] == 'success'
        assert result['data']['name'] == 'My Token'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            data={'name': 'My Token'},
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_all_params(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'tok-full', 'name': 'Full Token'}

        result = await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Full Token',
            scopes=['read', 'write'],
            expires_at='2026-12-31T23:59:59Z',
            presets=['file_upload'],
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            data={
                'name': 'Full Token',
                'scopes': ['read', 'write'],
                'expires_at': '2026-12-31T23:59:59Z',
                'presets': ['file_upload'],
            },
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_scopes_only(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'tok-scoped',
            'name': 'Scoped Token',
        }

        result = await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Scoped Token',
            scopes=['servers:read'],
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            data={'name': 'Scoped Token', 'scopes': ['servers:read']},
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_enabled_false(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'tok-disabled',
            'name': 'Disabled Token',
            'enabled': False,
        }

        result = await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Disabled Token',
            enabled=False,
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            data={'name': 'Disabled Token', 'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_enabled_true(
        self, mock_http_client, mock_token_manager
    ):
        """Test create_api_token forwards enabled=True (guards against falsy bugs)."""
        mock_http_client.post.return_value = {
            'id': 'tok-enabled',
            'name': 'Enabled Token',
            'enabled': True,
        }

        await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Enabled Token',
            enabled=True,
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            data={'name': 'Enabled Token', 'enabled': True},
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_presets_only(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'tok-preset',
            'name': 'Preset Token',
        }

        result = await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Preset Token',
            presets=['file_upload'],
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='header.payload.signature',
            data={'name': 'Preset Token', 'presets': ['file_upload']},
        )

    @pytest.mark.asyncio
    async def test_create_api_token_empty_name_returns_server_error(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.BAD_REQUEST,
            'message': 'This field may not be blank.',
        }

        result = await create_api_token(
            workspace='testworkspace', region='ap1', name=''
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_create_api_token_http_error(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.BAD_REQUEST,
            'message': 'Token name already exists',
        }

        result = await create_api_token(
            workspace='testworkspace', region='ap1', name='Duplicate Token'
        )

        assert result['status'] == 'error'


class TestDeleteApiToken:
    @pytest.mark.asyncio
    async def test_delete_api_token_success(self, mock_http_client, mock_token_manager):
        mock_http_client.delete.return_value = {}

        result = await delete_api_token(
            token_id=DELETE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{DELETE_TOKEN_ID}/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_delete_api_token_includes_token_id_in_response(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.delete.return_value = {}

        result = await delete_api_token(
            token_id=DELETE_RESPONSE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == DELETE_RESPONSE_TOKEN_ID

    @pytest.mark.asyncio
    async def test_delete_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await delete_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_api_token_not_found(
        self, mock_http_client, mock_token_manager
    ):
        """Test that delete_api_token returns error when token does not exist (404)."""
        mock_http_client.delete.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.NOT_FOUND,
            'message': 'Not found',
        }

        result = await delete_api_token(
            token_id=UNKNOWN_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestDuplicateApiToken:
    @pytest.mark.asyncio
    async def test_duplicate_api_token_success(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'tok-copy',
            'name': 'My Token (copy)',
            'key': 'new-secret-key',
        }

        result = await duplicate_api_token(
            token_id=DUPLICATE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['name'] == 'My Token (copy)'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{DUPLICATE_TOKEN_ID}/duplicate/',
            token='header.payload.signature',
            data={},
        )

    @pytest.mark.asyncio
    async def test_duplicate_api_token_with_custom_name(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {
            'id': 'tok-named',
            'name': 'My Backup Token',
        }

        result = await duplicate_api_token(
            token_id=DUPLICATE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            name='My Backup Token',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{DUPLICATE_TOKEN_ID}/duplicate/',
            token='header.payload.signature',
            data={'name': 'My Backup Token'},
        )

    @pytest.mark.asyncio
    async def test_duplicate_api_token_with_empty_name_forwarded(
        self, mock_http_client, mock_token_manager
    ):
        """Test duplicate_api_token forwards empty string name (server treats it
        as 'auto-generate' via APITokenDuplicateSerializer.allow_blank=True)."""
        mock_http_client.post.return_value = {
            'id': 'tok-blank',
            'name': 'Source (copy)',
        }

        await duplicate_api_token(
            token_id=DUPLICATE_EMPTY_NAME_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            name='',
        )

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{DUPLICATE_EMPTY_NAME_TOKEN_ID}/duplicate/',
            token='header.payload.signature',
            data={'name': ''},
        )

    @pytest.mark.asyncio
    async def test_duplicate_api_token_includes_token_id_in_response(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.post.return_value = {'id': 'tok-dup', 'name': 'Token (copy)'}

        result = await duplicate_api_token(
            token_id=DUPLICATE_RESPONSE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == DUPLICATE_RESPONSE_TOKEN_ID

    @pytest.mark.asyncio
    async def test_duplicate_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await duplicate_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_api_token_not_found(
        self, mock_http_client, mock_token_manager
    ):
        """Test that duplicate_api_token returns error when source token does not exist (404)."""
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.NOT_FOUND,
            'message': 'Not found',
        }

        result = await duplicate_api_token(
            token_id=UNKNOWN_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestListApiTokenScopes:
    @pytest.mark.asyncio
    async def test_list_api_token_scopes_success(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'resources': [
                {'name': 'servers:read', 'description': 'Read server information'},
                {
                    'name': 'commands:execute',
                    'description': 'Execute commands on servers',
                },
            ],
            'wildcards': ['*'],
        }

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert len(result['data']['resources']) == 2
        assert result['data']['wildcards'] == ['*']
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/scopes/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_list_api_token_scopes_empty(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'resources': [], 'wildcards': []}

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == {'resources': [], 'wildcards': []}

    @pytest.mark.asyncio
    async def test_list_api_token_scopes_http_error(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'Permission denied',
        }

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'


class TestGetApiToken:
    @pytest.mark.asyncio
    async def test_get_api_token_success(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {
            'id': GET_TOKEN_ID,
            'name': 'Detail Token',
            'enabled': True,
            'scopes': ['*'],
        }

        result = await get_api_token(
            token_id=GET_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == GET_TOKEN_ID
        assert result['data']['name'] == 'Detail Token'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{GET_TOKEN_ID}/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_get_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await get_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_api_token_not_found(self, mock_http_client, mock_token_manager):
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.NOT_FOUND,
            'message': 'Not found',
        }

        result = await get_api_token(
            token_id=UNKNOWN_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestUpdateApiToken:
    @pytest.mark.asyncio
    async def test_update_api_token_toggle_enabled(
        self, mock_http_client, mock_token_manager
    ):
        """Test disabling a token via update_api_token (enabled=False)."""
        mock_http_client.patch.return_value = {
            'id': UPDATE_TOGGLE_TOKEN_ID,
            'name': 'Active Token',
            'enabled': False,
        }

        result = await update_api_token(
            token_id=UPDATE_TOGGLE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{UPDATE_TOGGLE_TOKEN_ID}/',
            token='header.payload.signature',
            data={'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_update_api_token_with_all_fields(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {
            'id': UPDATE_ALL_FIELDS_TOKEN_ID,
            'name': 'Renamed',
            'enabled': True,
            'scopes': ['server:read'],
            'expires_at': '2027-01-01T00:00:00Z',
        }

        result = await update_api_token(
            token_id=UPDATE_ALL_FIELDS_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            name='Renamed',
            enabled=True,
            expires_at='2027-01-01T00:00:00Z',
            scopes=['server:read'],
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{UPDATE_ALL_FIELDS_TOKEN_ID}/',
            token='header.payload.signature',
            data={
                'name': 'Renamed',
                'enabled': True,
                'expires_at': '2027-01-01T00:00:00Z',
                'scopes': ['server:read'],
            },
        )

    @pytest.mark.asyncio
    async def test_update_api_token_clear_expires_at(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {
            'id': CLEAR_EXPIRES_TOKEN_ID,
            'expires_at': None,
        }

        result = await update_api_token(
            token_id=CLEAR_EXPIRES_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            clear_expires_at=True,
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{CLEAR_EXPIRES_TOKEN_ID}/',
            token='header.payload.signature',
            data={'expires_at': None},
        )

    @pytest.mark.asyncio
    async def test_update_api_token_clear_expires_at_with_other_fields(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {
            'id': CLEAR_EXPIRES_WITH_FIELDS_TOKEN_ID,
            'name': 'Renamed',
            'expires_at': None,
        }

        await update_api_token(
            token_id=CLEAR_EXPIRES_WITH_FIELDS_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            name='Renamed',
            clear_expires_at=True,
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{CLEAR_EXPIRES_WITH_FIELDS_TOKEN_ID}/',
            token='header.payload.signature',
            data={'name': 'Renamed', 'expires_at': None},
        )

    @pytest.mark.asyncio
    async def test_update_api_token_clear_and_set_expires_at_conflicts(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_api_token(
            token_id=CLEAR_AND_SET_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            expires_at='2027-01-01T00:00:00Z',
            clear_expires_at=True,
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_api_token_clear_expires_at_false_is_noop(
        self, mock_http_client, mock_token_manager
    ):
        """Test clear_expires_at=False (default) does not inject expires_at."""
        mock_http_client.patch.return_value = {
            'id': CLEAR_FALSE_TOKEN_ID,
            'enabled': False,
        }

        await update_api_token(
            token_id=CLEAR_FALSE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{CLEAR_FALSE_TOKEN_ID}/',
            token='header.payload.signature',
            data={'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_update_api_token_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_api_token(
            token_id=NO_FIELDS_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        result = await update_api_token(
            token_id='not-a-uuid',
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_api_token_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """update_api_token surfaces server error responses as errors,
        e.g. API_TOKEN_PRESETS_NOT_ALLOWED_ON_UPDATE and the scope-ceiling rejection.
        """
        mock_http_client.patch.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.BAD_REQUEST,
            'message': 'Presets are not allowed on update.',
        }

        result = await update_api_token(
            token_id=HTTP_ERROR_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            scopes=['server:read'],
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_update_api_token_not_found(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.patch.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.NOT_FOUND,
            'message': 'Not found',
        }

        result = await update_api_token(
            token_id=UNKNOWN_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        assert result['status'] == 'error'


class TestListApiTokenPresets:
    @pytest.mark.asyncio
    async def test_list_api_token_presets_success(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'file_upload': {
                'name': 'File upload',
                'scopes': ['webftp:upload'],
            },
        }

        result = await list_api_token_presets(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert 'file_upload' in result['data']
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/presets/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_list_api_token_presets_empty(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {}

        result = await list_api_token_presets(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == {}

    @pytest.mark.asyncio
    async def test_list_api_token_presets_http_error(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'Permission denied',
        }

        result = await list_api_token_presets(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'


class TestApiTokenMutationAuthGuard:
    """Preflight guard: create, update, delete, duplicate and rotate refuse a non-JWT
    token. APITokenObjectPermission 403s it; read and catalog tools stay unguarded.
    """

    @pytest.mark.asyncio
    async def test_create_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await create_api_token(
            workspace='testworkspace', region='ap1', name='New token'
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        assert mock_http_client.method_calls == []

    @pytest.mark.asyncio
    async def test_update_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await update_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id=NON_JWT_TOKEN_ID,
            name='Renamed',
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        assert mock_http_client.method_calls == []

    @pytest.mark.asyncio
    async def test_duplicate_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await duplicate_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id=NON_JWT_TOKEN_ID,
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        assert mock_http_client.method_calls == []

    @pytest.mark.asyncio
    async def test_delete_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await delete_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id=NON_JWT_TOKEN_ID,
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        assert mock_http_client.method_calls == []

    @pytest.mark.asyncio
    async def test_rotate_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await rotate_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id=NON_JWT_TOKEN_ID,
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        assert mock_http_client.method_calls == []

    @pytest.mark.asyncio
    async def test_jwt_token_passes_guard(self, mock_http_client, mock_token_manager):
        """JWT-shaped token (3 dotted non-empty parts) bypasses the guard
        and reaches the underlying HTTP call."""
        mock_token_manager.get_token.return_value = 'header.payload.signature'
        mock_http_client.post.return_value = {
            'id': 'tok-new',
            'name': 'New token',
            'key': 'alpat-secret',
        }

        result = await create_api_token(
            workspace='testworkspace', region='ap1', name='New token'
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once()


class TestRotateApiToken:
    @pytest.mark.asyncio
    async def test_rotate_api_token_success(self, mock_http_client, mock_token_manager):
        """Rotation posts to the rotate action on the same token id."""
        mock_http_client.post.return_value = {
            'id': ROTATE_TOKEN_ID,
            'key': 'new-secret',
        }

        result = await rotate_api_token(
            token_id=ROTATE_TOKEN_ID,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == ROTATE_TOKEN_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=f'/api/auth/tokens/{ROTATE_TOKEN_ID}/rotate/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_rotate_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """A non-UUID token id is refused before any request goes out."""
        result = await rotate_api_token(
            token_id='not-a-uuid',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_rotate_api_token_is_annotated_destructive(self):
        """idempotent_hint would invite a retry that kills the secret the first call issued."""
        tools = {t.name: t for t in await mcp.list_tools()}

        annotations = tools['rotate_api_token'].annotations
        assert annotations is not None
        assert annotations.destructive_hint is True
        assert annotations.idempotent_hint is not True
