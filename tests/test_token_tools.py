"""Unit tests for API token management tools."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.token_tools import (
    create_api_token,
    delete_api_token,
    duplicate_api_token,
    list_api_token_scopes,
    list_api_tokens,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.token_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestListApiTokens:
    """Tests for list_api_tokens tool."""

    @pytest.mark.asyncio
    async def test_list_api_tokens_success(self, mock_http_client, mock_token_manager):
        """Test successful API tokens list retrieval."""
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [{'id': 'tok-1', 'name': 'Token A'}, {'id': 'tok-2', 'name': 'Token B'}],
        }

        result = await list_api_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 2
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_api_tokens_with_pagination(self, mock_http_client, mock_token_manager):
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
            token='test-token',
            params={'page': 2, 'page_size': 5},
        )

    @pytest.mark.asyncio
    async def test_list_api_tokens_empty(self, mock_http_client, mock_token_manager):
        """Test list_api_tokens with no tokens."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_api_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data']['count'] == 0


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
            token='test-token',
            data={'name': 'My Token'},
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_all_params(self, mock_http_client, mock_token_manager):
        """Test create_api_token with all optional parameters."""
        mock_http_client.post.return_value = {'id': 'tok-full', 'name': 'Full Token'}

        result = await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Full Token',
            scopes=['read', 'write'],
            expires_at='2026-12-31T23:59:59Z',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/',
            token='test-token',
            data={
                'name': 'Full Token',
                'scopes': ['read', 'write'],
                'expires_at': '2026-12-31T23:59:59Z',
            },
        )

    @pytest.mark.asyncio
    async def test_create_api_token_with_scopes_only(self, mock_http_client, mock_token_manager):
        """Test create_api_token with scopes but no other optional params."""
        mock_http_client.post.return_value = {'id': 'tok-scoped', 'name': 'Scoped Token'}

        result = await create_api_token(
            workspace='testworkspace',
            region='ap1',
            name='Scoped Token',
            scopes=['servers:read'],
        )

        assert result['status'] == 'success'
        call_data = mock_http_client.post.call_args[1]['data']
        assert call_data['scopes'] == ['servers:read']
        assert 'description' not in call_data
        assert 'expires_at' not in call_data


class TestDeleteApiToken:
    """Tests for delete_api_token tool."""

    @pytest.mark.asyncio
    async def test_delete_api_token_success(self, mock_http_client, mock_token_manager):
        """Test successful API token deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440001', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440001/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_delete_api_token_includes_token_id_in_response(
        self, mock_http_client, mock_token_manager
    ):
        """Test that delete_api_token includes token_id in response metadata."""
        mock_http_client.delete.return_value = {}

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440002', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['token_id'] == '550e8400-e29b-41d4-a716-446655440002'

    @pytest.mark.asyncio
    async def test_delete_api_token_invalid_token_id(self, mock_http_client, mock_token_manager):
        """Test that delete_api_token returns error for non-UUID token_id."""
        result = await delete_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_api_token_http_exception(self, mock_http_client, mock_token_manager):
        """Test that delete_api_token returns error when http_client raises an exception."""
        mock_http_client.delete.side_effect = Exception('Network failure')

        result = await delete_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440000',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestDuplicateApiToken:
    """Tests for duplicate_api_token tool."""

    @pytest.mark.asyncio
    async def test_duplicate_api_token_success(self, mock_http_client, mock_token_manager):
        """Test successful API token duplication."""
        mock_http_client.post.return_value = {
            'id': 'tok-copy',
            'name': 'My Token (copy)',
            'key': 'new-secret-key',
        }

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440003', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['name'] == 'My Token (copy)'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/550e8400-e29b-41d4-a716-446655440003/duplicate/',
            token='test-token',
            data={},
        )

    @pytest.mark.asyncio
    async def test_duplicate_api_token_includes_token_id_in_response(
        self, mock_http_client, mock_token_manager
    ):
        """Test that duplicate_api_token includes token_id in response metadata."""
        mock_http_client.post.return_value = {'id': 'tok-dup', 'name': 'Token (copy)'}

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440004', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['token_id'] == '550e8400-e29b-41d4-a716-446655440004'

    @pytest.mark.asyncio
    async def test_duplicate_api_token_invalid_token_id(self, mock_http_client, mock_token_manager):
        """Test that duplicate_api_token returns error for non-UUID token_id."""
        result = await duplicate_api_token(
            token_id='not-a-uuid', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_api_token_http_exception(self, mock_http_client, mock_token_manager):
        """Test that duplicate_api_token returns error when http_client raises an exception."""
        mock_http_client.post.side_effect = Exception('Network failure')

        result = await duplicate_api_token(
            token_id='550e8400-e29b-41d4-a716-446655440000',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'


class TestListApiTokenScopes:
    """Tests for list_api_token_scopes tool."""

    @pytest.mark.asyncio
    async def test_list_api_token_scopes_success(self, mock_http_client, mock_token_manager):
        """Test successful API token scopes retrieval."""
        mock_http_client.get.return_value = {
            'resources': [
                {'name': 'servers:read', 'description': 'Read server information'},
                {'name': 'commands:execute', 'description': 'Execute commands on servers'},
            ],
            'wildcards': ['*'],
        }

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert len(result['data']['resources']) == 2
        assert result['data']['wildcards'] == ['*']
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/auth/tokens/scopes/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_list_api_token_scopes_empty(self, mock_http_client, mock_token_manager):
        """Test list_api_token_scopes when no scopes are available."""
        mock_http_client.get.return_value = {'resources': [], 'wildcards': []}

        result = await list_api_token_scopes(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == {'resources': [], 'wildcards': []}
