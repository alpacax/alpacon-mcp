"""Unit tests for API token management tools."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.token_tools import (
    create_api_token,
    delete_api_token,
    duplicate_api_token,
    get_api_token,
    list_api_token_presets,
    list_api_token_scopes,
    list_api_tokens,
    update_api_token,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.token_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'header.payload.signature'
        yield mock_manager


class TestListApiTokens:
    """Tests for list_api_tokens tool."""

    @pytest.mark.asyncio
    async def test_list_api_tokens_success(self, mock_http_client, mock_token_manager):
        """Test successful API tokens list retrieval."""
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
        """Test list_api_tokens with pagination parameters."""
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
        """Test that filter/search/ordering params are forwarded to the API."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_api_tokens(
            workspace='testworkspace',
            region='ap1',
            name='deploy-bot',
            enabled=True,
            remote_ip='10.0.0.5',
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
                'remote_ip': '10.0.0.5',
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

        assert mock_http_client.get.call_args[1]['params'] == {'enabled': False}

    @pytest.mark.asyncio
    async def test_list_api_tokens_empty(self, mock_http_client, mock_token_manager):
        """Test list_api_tokens with no tokens."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_api_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 0

    @pytest.mark.asyncio
    async def test_list_api_tokens_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that list_api_tokens surfaces API error responses as errors."""
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': 403,
            'message': 'Permission denied',
        }

        result = await list_api_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'


class TestCreateApiToken:
    """Tests for create_api_token tool."""

    @pytest.mark.asyncio
    async def test_create_api_token_success(self, mock_http_client, mock_token_manager):
        """Test successful API token creation."""
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
        """Test create_api_token with all optional parameters."""
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
        """Test create_api_token with scopes but no other optional params."""
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
        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['scopes'] == ['servers:read']
        assert 'expires_at' not in call_data

    @pytest.mark.asyncio
    async def test_create_api_token_with_enabled_false(
        self, mock_http_client, mock_token_manager
    ):
        """Test create_api_token with enabled=False creates a disabled token."""
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
        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['enabled'] is False

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

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['enabled'] is True

    @pytest.mark.asyncio
    async def test_create_api_token_with_presets_only(
        self, mock_http_client, mock_token_manager
    ):
        """Test create_api_token with presets but no explicit scopes."""
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
        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['presets'] == ['file_upload']
        assert 'scopes' not in call_data

    @pytest.mark.asyncio
    async def test_create_api_token_empty_name_returns_server_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that create_api_token with empty name surfaces the server 400 as error."""
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': 400,
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
        """Test that create_api_token surfaces API error responses as errors."""
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': 400,
            'message': 'Token name already exists',
        }

        result = await create_api_token(
            workspace='testworkspace', region='ap1', name='Duplicate Token'
        )

        assert result['status'] == 'error'


class TestDeleteApiToken:
    """Tests for delete_api_token tool."""

    @pytest.mark.asyncio
    async def test_delete_api_token_success(self, mock_http_client, mock_token_manager):
        """Test successful API token deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440001',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440001/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_delete_api_token_includes_token_id_in_response(
        self, mock_http_client, mock_token_manager
    ):
        """Test that delete_api_token includes token_id in response metadata."""
        mock_http_client.delete.return_value = {}

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440002',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == '550e8400-e29b-41d4-a716-446655440002'

    @pytest.mark.asyncio
    async def test_delete_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """Test that delete_api_token returns error for non-UUID token_id."""
        result = await delete_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_api_token_http_exception(
        self, mock_http_client, mock_token_manager
    ):
        """Test that delete_api_token returns error when http_client raises an exception."""
        mock_http_client.delete.side_effect = Exception('Network failure')

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440000',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_delete_api_token_not_found(
        self, mock_http_client, mock_token_manager
    ):
        """Test that delete_api_token returns error when token does not exist (404)."""
        mock_http_client.delete.return_value = {
            'error': 'HTTP Error',
            'status_code': 404,
            'message': 'Not found',
        }

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440099',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestDuplicateApiToken:
    """Tests for duplicate_api_token tool."""

    @pytest.mark.asyncio
    async def test_duplicate_api_token_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful API token duplication."""
        mock_http_client.post.return_value = {
            'id': 'tok-copy',
            'name': 'My Token (copy)',
            'key': 'new-secret-key',
        }

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440003',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['name'] == 'My Token (copy)'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440003/duplicate/',
            token='header.payload.signature',
            data={},
        )

    @pytest.mark.asyncio
    async def test_duplicate_api_token_with_custom_name(
        self, mock_http_client, mock_token_manager
    ):
        """Test duplicate_api_token forwards optional name to the API."""
        mock_http_client.post.return_value = {
            'id': 'tok-named',
            'name': 'My Backup Token',
        }

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440003',
            workspace='testworkspace',
            region='ap1',
            name='My Backup Token',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440003/duplicate/',
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
            token_id='550e8400-e29b-41d4-a716-446655440005',
            workspace='testworkspace',
            region='ap1',
            name='',
        )

        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data == {'name': ''}

    @pytest.mark.asyncio
    async def test_duplicate_api_token_includes_token_id_in_response(
        self, mock_http_client, mock_token_manager
    ):
        """Test that duplicate_api_token includes token_id in response metadata."""
        mock_http_client.post.return_value = {'id': 'tok-dup', 'name': 'Token (copy)'}

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440004',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == '550e8400-e29b-41d4-a716-446655440004'

    @pytest.mark.asyncio
    async def test_duplicate_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """Test that duplicate_api_token returns error for non-UUID token_id."""
        result = await duplicate_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_api_token_http_exception(
        self, mock_http_client, mock_token_manager
    ):
        """Test that duplicate_api_token returns error when http_client raises an exception."""
        mock_http_client.post.side_effect = Exception('Network failure')

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440000',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_duplicate_api_token_not_found(
        self, mock_http_client, mock_token_manager
    ):
        """Test that duplicate_api_token returns error when source token does not exist (404)."""
        mock_http_client.post.return_value = {
            'error': 'HTTP Error',
            'status_code': 404,
            'message': 'Not found',
        }

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440099',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestListApiTokenScopes:
    """Tests for list_api_token_scopes tool."""

    @pytest.mark.asyncio
    async def test_list_api_token_scopes_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful API token scopes retrieval."""
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
        """Test list_api_token_scopes when no scopes are available."""
        mock_http_client.get.return_value = {'resources': [], 'wildcards': []}

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == {'resources': [], 'wildcards': []}

    @pytest.mark.asyncio
    async def test_list_api_token_scopes_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that list_api_token_scopes surfaces API error responses as errors."""
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': 403,
            'message': 'Permission denied',
        }

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'


class TestGetApiToken:
    """Tests for get_api_token tool."""

    @pytest.mark.asyncio
    async def test_get_api_token_success(self, mock_http_client, mock_token_manager):
        """Test successful single API token retrieval."""
        mock_http_client.get.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440010',
            'name': 'Detail Token',
            'enabled': True,
            'scopes': ['*'],
        }

        result = await get_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440010',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['token_id'] == '550e8400-e29b-41d4-a716-446655440010'
        assert result['data']['name'] == 'Detail Token'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440010/',
            token='header.payload.signature',
        )

    @pytest.mark.asyncio
    async def test_get_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """Test that get_api_token returns error for non-UUID token_id."""
        result = await get_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_api_token_not_found(self, mock_http_client, mock_token_manager):
        """Test that get_api_token returns error when token does not exist."""
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': 404,
            'message': 'Not found',
        }

        result = await get_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440099',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestUpdateApiToken:
    """Tests for update_api_token tool."""

    @pytest.mark.asyncio
    async def test_update_api_token_toggle_enabled(
        self, mock_http_client, mock_token_manager
    ):
        """Test disabling a token via update_api_token (enabled=False)."""
        mock_http_client.patch.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440020',
            'name': 'Active Token',
            'enabled': False,
        }

        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440020',
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440020/',
            token='header.payload.signature',
            data={'enabled': False},
        )

    @pytest.mark.asyncio
    async def test_update_api_token_with_all_fields(
        self, mock_http_client, mock_token_manager
    ):
        """Test update_api_token forwards every supplied field."""
        mock_http_client.patch.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440021',
            'name': 'Renamed',
            'enabled': True,
            'scopes': ['server:read'],
            'expires_at': '2027-01-01T00:00:00Z',
        }

        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440021',
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
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440021/',
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
        """Test clear_expires_at=True sends expires_at=null to remove the expiry."""
        mock_http_client.patch.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440024',
            'expires_at': None,
        }

        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440024',
            workspace='testworkspace',
            region='ap1',
            clear_expires_at=True,
        )

        assert result['status'] == 'success'
        call_data = mock_http_client.patch.call_args[1]['data']
        assert call_data == {'expires_at': None}

    @pytest.mark.asyncio
    async def test_update_api_token_clear_expires_at_with_other_fields(
        self, mock_http_client, mock_token_manager
    ):
        """Test clear_expires_at combines with other fields in a single PATCH."""
        mock_http_client.patch.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440027',
            'name': 'Renamed',
            'expires_at': None,
        }

        await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440027',
            workspace='testworkspace',
            region='ap1',
            name='Renamed',
            clear_expires_at=True,
        )

        call_data = mock_http_client.patch.call_args[1]['data']
        assert call_data == {'name': 'Renamed', 'expires_at': None}

    @pytest.mark.asyncio
    async def test_update_api_token_clear_and_set_expires_at_conflicts(
        self, mock_http_client, mock_token_manager
    ):
        """Test mutual exclusion of expires_at and clear_expires_at."""
        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440025',
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
            'id': '550e8400-e29b-41d4-a716-446655440026',
            'enabled': False,
        }

        await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440026',
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        call_data = mock_http_client.patch.call_args[1]['data']
        assert 'expires_at' not in call_data

    @pytest.mark.asyncio
    async def test_update_api_token_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test update_api_token returns error when no field is provided."""
        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440022',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_api_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """Test update_api_token returns error for non-UUID token_id."""
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
        """Test update_api_token surfaces server error responses as errors.

        Covers e.g. API_TOKEN_PRESETS_NOT_ALLOWED_ON_UPDATE / scope
        ceiling rejection returned by the server.
        """
        mock_http_client.patch.return_value = {
            'error': 'HTTP Error',
            'status_code': 400,
            'message': 'Presets are not allowed on update.',
        }

        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440023',
            workspace='testworkspace',
            region='ap1',
            scopes=['server:read'],
        )

        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_update_api_token_not_found(
        self, mock_http_client, mock_token_manager
    ):
        """Test update_api_token returns error when token does not exist."""
        mock_http_client.patch.return_value = {
            'error': 'HTTP Error',
            'status_code': 404,
            'message': 'Not found',
        }

        result = await update_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440099',
            workspace='testworkspace',
            region='ap1',
            enabled=False,
        )

        assert result['status'] == 'error'


class TestListApiTokenPresets:
    """Tests for list_api_token_presets tool."""

    @pytest.mark.asyncio
    async def test_list_api_token_presets_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful preset catalog retrieval."""
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
        """Test preset catalog when workspace has no enabled presets."""
        mock_http_client.get.return_value = {}

        result = await list_api_token_presets(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == {}

    @pytest.mark.asyncio
    async def test_list_api_token_presets_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test list_api_token_presets surfaces API error responses as errors."""
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': 403,
            'message': 'Permission denied',
        }

        result = await list_api_token_presets(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'


class TestApiTokenMutationAuthGuard:
    """Preflight guard: the 4 mutation tools (create/update/duplicate/delete)
    must short-circuit on the MCP side when the caller's resolved token is
    not a JWT — because the server's APITokenObjectPermission would 403
    every such request. The guard saves the round-trip and surfaces a
    clearer error to the client.

    Read-only tools (list/get/list_scopes/list_presets) are intentionally
    NOT guarded — list/get because callers may legitimately enumerate
    their own tokens with whichever auth they hold, and the catalog
    endpoints because the server itself does not gate them with
    APITokenObjectPermission.
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
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await update_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id='550e8400-e29b-41d4-a716-446655440000',
            name='Renamed',
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await duplicate_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id='550e8400-e29b-41d4-a716-446655440000',
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_rejected_for_non_jwt_token(
        self, mock_http_client, mock_token_manager
    ):
        mock_token_manager.get_token.return_value = 'opaque-api-token'

        result = await delete_api_token(
            workspace='testworkspace',
            region='ap1',
            token_id='550e8400-e29b-41d4-a716-446655440000',
        )

        assert result['status'] == 'error'
        assert 'JWT' in result['message']
        mock_http_client.delete.assert_not_called()

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
