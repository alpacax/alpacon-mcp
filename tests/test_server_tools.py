"""
Unit tests for server tools module.

Tests all server management functions including server listing, details, and notes management.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tools.server_tools import (
    create_registration_token,
    create_server,
    create_server_note,
    delete_registration_token,
    delete_server,
    delete_server_note,
    get_registration_guide,
    get_server,
    get_server_access_policy,
    get_server_note,
    get_server_sync,
    list_registration_tokens,
    list_server_notes,
    list_servers,
    star_server,
    update_server,
    update_server_note,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.server_tools.http_client') as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.delete = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


@pytest.fixture
def sample_server():
    """Sample server data for testing."""
    return {
        'id': '550e8400-e29b-41d4-a716-446655440123',
        'name': 'web-server-01',
        'ip': '192.168.1.10',
        'status': 'running',
        'os': 'Ubuntu 20.04',
        'cpu': 2,
        'memory': 4096,
        'storage': 50,
        'created_at': '2024-01-01T00:00:00Z',
        'tags': ['web', 'production'],
    }


@pytest.fixture
def sample_servers_list():
    """Sample servers list response for testing."""
    return {
        'count': 5,
        'next': None,
        'previous': None,
        'results': [
            {
                'id': '550e8400-e29b-41d4-a716-446655440123',
                'name': 'web-server-01',
                'ip': '192.168.1.10',
                'status': 'running',
                'os': 'Ubuntu 20.04',
                'tags': ['web', 'production'],
            },
            {
                'id': '550e8400-e29b-41d4-a716-446655440456',
                'name': 'db-server-01',
                'ip': '192.168.1.11',
                'status': 'running',
                'os': 'Ubuntu 20.04',
                'tags': ['database', 'production'],
            },
        ],
    }


@pytest.fixture
def sample_server_notes():
    """Sample server notes response for testing."""
    return {
        'count': 3,
        'results': [
            {
                'id': 'note-123',
                'title': 'Maintenance Schedule',
                'content': 'Weekly maintenance on Sundays 2 AM UTC',
                'created_at': '2024-01-01T00:00:00Z',
                'updated_at': '2024-01-01T00:00:00Z',
            },
            {
                'id': 'note-456',
                'title': 'SSL Certificate',
                'content': 'SSL certificate expires on 2024-12-31',
                'created_at': '2024-01-02T00:00:00Z',
                'updated_at': '2024-01-02T00:00:00Z',
            },
        ],
    }


class TestListServers:
    """Test servers list functionality."""

    @pytest.mark.asyncio
    async def test_list_servers_success(
        self, mock_http_client, mock_token_manager, sample_servers_list
    ):
        """Test successful servers list retrieval."""
        mock_http_client.get.return_value = sample_servers_list

        result = await list_servers(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == sample_servers_list
        assert len(result['data']['results']) == 2

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_list_servers_no_token(self, mock_http_client, mock_token_manager):
        """Test servers list with no token."""
        mock_token_manager.get_token.return_value = None

        result = await list_servers(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_servers_different_region(
        self, mock_http_client, mock_token_manager, sample_servers_list
    ):
        """Test servers list with different region."""
        mock_http_client.get.return_value = sample_servers_list

        result = await list_servers(workspace='testworkspace', region='us1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='us1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_list_servers_http_error(self, mock_http_client, mock_token_manager):
        """Test servers list with HTTP error."""
        mock_http_client.get.side_effect = Exception('HTTP 500: Internal Server Error')

        result = await list_servers(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'HTTP 500' in result['message']


class TestGetServer:
    """Test server details functionality."""

    @pytest.mark.asyncio
    async def test_get_server_success(
        self, mock_http_client, mock_token_manager, sample_server
    ):
        """Test successful server details retrieval."""
        mock_http_client.get.return_value = {'count': 1, 'results': [sample_server]}

        result = await get_server(
            server_id='550e8400-e29b-41d4-a716-446655440123', workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['data'] == sample_server
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440123'

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
            params={'id': '550e8400-e29b-41d4-a716-446655440123'},
        )

    @pytest.mark.asyncio
    async def test_get_server_no_token(self, mock_http_client, mock_token_manager):
        """Test server details with no token."""
        mock_token_manager.get_token.return_value = None

        result = await get_server(
            server_id='550e8400-e29b-41d4-a716-446655440123', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_server_not_found(self, mock_http_client, mock_token_manager):
        """Test server details with non-existent server."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await get_server(
            server_id='99999999-9999-9999-9999-999999999999', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'Server not found' in result['message']

    @pytest.mark.asyncio
    async def test_get_server_different_region(
        self, mock_http_client, mock_token_manager, sample_server
    ):
        """Test server details with different region."""
        mock_http_client.get.return_value = {'count': 1, 'results': [sample_server]}

        result = await get_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            region='eu1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='eu1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
            params={'id': '550e8400-e29b-41d4-a716-446655440123'},
        )

    @pytest.mark.asyncio
    async def test_get_server_http_error(self, mock_http_client, mock_token_manager):
        """Test server details with HTTP error."""
        mock_http_client.get.side_effect = Exception('HTTP 404: Server not found')

        result = await get_server(
            server_id='99999999-9999-9999-9999-999999999999', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'HTTP 404' in result['message']


class TestServerNotes:
    """Test server notes functionality."""

    @pytest.mark.asyncio
    async def test_list_server_notes_success(
        self, mock_http_client, mock_token_manager, sample_server_notes
    ):
        """Test successful server notes list retrieval."""
        mock_http_client.get.return_value = sample_server_notes

        result = await list_server_notes(
            server_id='550e8400-e29b-41d4-a716-446655440123', workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['data'] == sample_server_notes
        assert len(result['data']['results']) == 2

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/?server=550e8400-e29b-41d4-a716-446655440123',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_list_server_notes_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Test server notes list with no token."""
        mock_token_manager.get_token.return_value = None

        result = await list_server_notes(
            server_id='550e8400-e29b-41d4-a716-446655440123', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_server_note_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful server note creation."""
        created_note = {
            'id': 'note-789',
            'title': 'New Note',
            'content': 'This is a new note about the server',
            'created_at': '2024-01-03T00:00:00Z',
            'updated_at': '2024-01-03T00:00:00Z',
        }
        mock_http_client.post.return_value = created_note

        result = await create_server_note(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            title='New Note',
            content='This is a new note about the server',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['data'] == created_note
        assert result['server_id'] == '550e8400-e29b-41d4-a716-446655440123'

        expected_data = {
            'server': '550e8400-e29b-41d4-a716-446655440123',
            'title': 'New Note',
            'content': 'This is a new note about the server',
        }

        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/',
            token='test-token',
            data=expected_data,
        )

    @pytest.mark.asyncio
    async def test_create_server_note_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Test server note creation with no token."""
        mock_token_manager.get_token.return_value = None

        result = await create_server_note(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            title='New Note',
            content='This is a new note about the server',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_server_note_validation_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test server note creation with validation error."""
        mock_http_client.post.side_effect = Exception('HTTP 400: Title cannot be empty')

        result = await create_server_note(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            title='',
            content='This is a new note about the server',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'HTTP 400' in result['message']


class TestParameterValidation:
    """Test parameter validation and edge cases."""

    @pytest.mark.asyncio
    async def test_special_characters_in_workspace(
        self, mock_http_client, mock_token_manager, sample_servers_list
    ):
        """Test with special characters in workspace name."""
        mock_http_client.get.return_value = sample_servers_list

        result = await list_servers(workspace='test-workspace_123', region='ap1')

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='test-workspace_123',
            endpoint='/api/servers/servers/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_long_note_content(self, mock_http_client, mock_token_manager):
        """Test server note creation with long content."""
        long_content = 'x' * 10000
        created_note = {
            'id': 'note-789',
            'title': 'Long Note',
            'content': long_content,
            'created_at': '2024-01-03T00:00:00Z',
            'updated_at': '2024-01-03T00:00:00Z',
        }
        mock_http_client.post.return_value = created_note

        result = await create_server_note(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            title='Long Note',
            content=long_content,
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert len(result['data']['content']) == 10000


class TestRegionHandling:
    """Test region parameter handling."""

    @pytest.mark.asyncio
    async def test_all_supported_regions(
        self, mock_http_client, mock_token_manager, sample_servers_list
    ):
        """Test with all supported regions."""
        mock_http_client.get.return_value = sample_servers_list
        regions = ['ap1', 'us1', 'eu1', 'dev']

        for region in regions:
            result = await list_servers(workspace='testworkspace', region=region)

            assert result['status'] == 'success'

        assert mock_http_client.get.call_count == len(regions)

        mock_http_client.get.assert_called_with(
            region='dev',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
        )


class TestServerNoteCRUD:
    """Tests for get_server_note, update_server_note, delete_server_note."""

    @pytest.mark.asyncio
    async def test_get_server_note_success(self, mock_http_client, mock_token_manager):
        """Returns single note detail by ID."""
        mock_http_client.get.return_value = {
            'id': 'note-1',
            'title': 'Maintenance',
            'content': 'Sundays 2 AM UTC',
        }

        result = await get_server_note(
            note_id='note-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['id'] == 'note-1'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/note-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_update_server_note_success(
        self, mock_http_client, mock_token_manager
    ):
        """Updates fields and returns updated note."""
        mock_http_client.patch.return_value = {
            'id': 'note-1',
            'title': 'New title',
            'content': 'New content',
        }

        result = await update_server_note(
            note_id='note-1',
            workspace='testworkspace',
            region='ap1',
            title='New title',
            content='New content',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/note-1/',
            token='test-token',
            data={'title': 'New title', 'content': 'New content'},
        )

    @pytest.mark.asyncio
    async def test_update_server_note_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """No update fields returns validation error and no API call."""
        result = await update_server_note(
            note_id='note-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'error'
        assert result.get('error_code') == 'validation'
        assert result.get('field') == 'title or content'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_server_note_partial(
        self, mock_http_client, mock_token_manager
    ):
        """Only non-None fields are sent in PATCH body."""
        mock_http_client.patch.return_value = {'id': 'note-1', 'title': 'Only title'}

        await update_server_note(
            note_id='note-1',
            workspace='testworkspace',
            region='ap1',
            title='Only title',
        )

        _, kwargs = mock_http_client.patch.call_args
        assert kwargs['data'] == {'title': 'Only title'}

    @pytest.mark.asyncio
    async def test_delete_server_note_success(
        self, mock_http_client, mock_token_manager
    ):
        """Deletes note by ID."""
        mock_http_client.delete.return_value = {}

        result = await delete_server_note(
            note_id='note-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/note-1/',
            token='test-token',
        )


class TestCreateServer:
    """Tests for create_server tool."""

    @pytest.mark.asyncio
    async def test_create_server_success(self, mock_http_client, mock_token_manager):
        """Creates a server with required fields and returns success."""
        created_server = {
            'id': '550e8400-e29b-41d4-a716-446655440001',
            'name': 'new-server',
            'platform': 'debian',
        }
        mock_http_client.post.return_value = created_server

        result = await create_server(
            workspace='testworkspace',
            name='new-server',
            platform='debian',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data'] == created_server
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
            data={'name': 'new-server', 'platform': 'debian'},
        )

    @pytest.mark.asyncio
    async def test_create_server_with_description(
        self, mock_http_client, mock_token_manager
    ):
        """Creates a server with optional description included in request body."""
        mock_http_client.post.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440001',
            'name': 'new-server',
            'platform': 'rhel',
            'description': 'A production RHEL server',
        }

        result = await create_server(
            workspace='testworkspace',
            name='new-server',
            platform='rhel',
            description='A production RHEL server',
            region='ap1',
        )

        assert result['status'] == 'success'
        _, kwargs = mock_http_client.post.call_args
        assert kwargs['data']['description'] == 'A production RHEL server'

    @pytest.mark.asyncio
    async def test_create_server_no_token(self, mock_http_client, mock_token_manager):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await create_server(
            workspace='testworkspace', name='new-server', platform='debian'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_server_invalid_platform(
        self, mock_http_client, mock_token_manager
    ):
        """Returns validation error when platform is not a valid value."""
        result = await create_server(
            workspace='testworkspace',
            name='new-server',
            platform='ubuntu',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'platform'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_server_http_error(self, mock_http_client, mock_token_manager):
        """Returns error when http_client returns an upstream error envelope."""
        mock_http_client.post.return_value = {
            'error': 'Bad Request',
            'status_code': 400,
            'message': 'Server name already exists',
        }

        result = await create_server(
            workspace='testworkspace',
            name='existing-server',
            platform='debian',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['message'] == 'Server name already exists'


class TestUpdateServer:
    """Tests for update_server tool."""

    @pytest.mark.asyncio
    async def test_update_server_success(self, mock_http_client, mock_token_manager):
        """Updates server fields via PATCH and returns updated data."""
        updated_server = {
            'id': '550e8400-e29b-41d4-a716-446655440123',
            'name': 'renamed-server',
        }
        mock_http_client.patch.return_value = updated_server

        result = await update_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            name='renamed-server',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data'] == updated_server
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/550e8400-e29b-41d4-a716-446655440123/',
            token='test-token',
            data={'name': 'renamed-server'},
        )

    @pytest.mark.asyncio
    async def test_update_server_no_token(self, mock_http_client, mock_token_manager):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await update_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            name='renamed-server',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_server_no_fields_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """Returns error when no update fields are provided and makes no API call."""
        result = await update_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert (
            'At least one of name or description must be provided.'
            in result['suggestion']
        )
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_server_partial_fields(
        self, mock_http_client, mock_token_manager
    ):
        """Only provided fields are sent in PATCH body."""
        mock_http_client.patch.return_value = {
            'id': '550e8400-e29b-41d4-a716-446655440123',
            'description': 'Updated description',
        }

        await update_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            description='Updated description',
            region='ap1',
        )

        _, kwargs = mock_http_client.patch.call_args
        assert kwargs['data'] == {'description': 'Updated description'}
        assert 'name' not in kwargs['data']


class TestDeleteServer:
    """Tests for delete_server tool."""

    @pytest.mark.asyncio
    async def test_delete_server_success(self, mock_http_client, mock_token_manager):
        """Deletes server by UUID and returns success."""
        mock_http_client.delete.return_value = {}

        result = await delete_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/550e8400-e29b-41d4-a716-446655440123/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_delete_server_no_token(self, mock_http_client, mock_token_manager):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await delete_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.delete.assert_not_called()


class TestStarServer:
    """Tests for star_server tool."""

    @pytest.mark.asyncio
    async def test_star_server_success(self, mock_http_client, mock_token_manager):
        """Posts to star endpoint with starred flag and returns success."""
        mock_http_client.post.return_value = {'starred': True}

        result = await star_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            status=True,
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/550e8400-e29b-41d4-a716-446655440123/star/',
            token='test-token',
            data={'status': True},
        )

    @pytest.mark.asyncio
    async def test_star_server_no_token(self, mock_http_client, mock_token_manager):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await star_server(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            status=True,
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()


class TestGetServerSync:
    """Tests for get_server_sync tool."""

    @pytest.mark.asyncio
    async def test_get_server_sync_success(self, mock_http_client, mock_token_manager):
        """Returns sync status for a server."""
        mock_http_client.get.return_value = {
            'synced': True,
            'last_sync': '2024-01-01T00:00:00Z',
        }

        result = await get_server_sync(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/550e8400-e29b-41d4-a716-446655440123/sync/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_server_sync_no_token(self, mock_http_client, mock_token_manager):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await get_server_sync(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()


class TestGetServerAccessPolicy:
    """Tests for get_server_access_policy tool."""

    @pytest.mark.asyncio
    async def test_get_server_access_policy_success(
        self, mock_http_client, mock_token_manager
    ):
        """Returns access policy for a server."""
        mock_http_client.get.return_value = {
            'users': ['alice', 'bob'],
            'groups': ['admins'],
        }

        result = await get_server_access_policy(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/550e8400-e29b-41d4-a716-446655440123/access-policy/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_get_server_access_policy_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await get_server_access_policy(
            server_id='550e8400-e29b-41d4-a716-446655440123',
            workspace='testworkspace',
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()


class TestListRegistrationTokens:
    """Tests for list_registration_tokens tool."""

    @pytest.mark.asyncio
    async def test_list_registration_tokens_success(
        self, mock_http_client, mock_token_manager
    ):
        """Returns paginated list of registration tokens."""
        token_list = {
            'count': 2,
            'results': [
                {'id': 'tok-1', 'name': 'prod-token'},
                {'id': 'tok-2', 'name': 'staging-token'},
            ],
        }
        mock_http_client.get.return_value = token_list

        result = await list_registration_tokens(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['data'] == token_list
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/registration-tokens/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_registration_tokens_pagination(
        self, mock_http_client, mock_token_manager
    ):
        """Passes page and page_size params to the API."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        await list_registration_tokens(
            workspace='testworkspace', region='ap1', page=2, page_size=5
        )

        _, kwargs = mock_http_client.get.call_args
        assert kwargs['params'] == {'page': 2, 'page_size': 5}

    @pytest.mark.asyncio
    async def test_list_registration_tokens_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Returns error when token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await list_registration_tokens(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()


class TestCreateRegistrationToken:
    """Tests for create_registration_token tool."""

    @pytest.mark.asyncio
    async def test_create_registration_token_success(
        self, mock_http_client, mock_token_manager
    ):
        """Creates a registration token with required name."""
        created_token = {'id': 'tok-123', 'name': 'my-token', 'token': 'abc123xyz'}
        mock_http_client.post.return_value = created_token

        result = await create_registration_token(
            workspace='testworkspace', name='my-token', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data'] == created_token
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/registration-tokens/',
            token='test-token',
            data={'name': 'my-token'},
        )

    @pytest.mark.asyncio
    async def test_create_registration_token_with_description(
        self, mock_http_client, mock_token_manager
    ):
        """Includes description in POST body when provided."""
        mock_http_client.post.return_value = {
            'id': 'tok-123',
            'name': 'my-token',
            'description': 'For production servers',
        }

        result = await create_registration_token(
            workspace='testworkspace',
            name='my-token',
            description='For production servers',
            region='ap1',
        )

        assert result['status'] == 'success'
        _, kwargs = mock_http_client.post.call_args
        assert kwargs['data']['description'] == 'For production servers'

    @pytest.mark.asyncio
    async def test_create_registration_token_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Returns error when auth token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await create_registration_token(
            workspace='testworkspace', name='my-token'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()


class TestDeleteRegistrationToken:
    """Tests for delete_registration_token tool."""

    @pytest.mark.asyncio
    async def test_delete_registration_token_success(
        self, mock_http_client, mock_token_manager
    ):
        """Deletes registration token by ID."""
        mock_http_client.delete.return_value = {}

        result = await delete_registration_token(
            token_id='a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/registration-tokens/a1b2c3d4-e5f6-7890-abcd-ef1234567890/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_delete_registration_token_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Returns error when auth token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await delete_registration_token(
            token_id='a1b2c3d4-e5f6-7890-abcd-ef1234567890', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_registration_token_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """Returns validation error when token_id is not a valid UUID."""
        result = await delete_registration_token(
            token_id='not-a-uuid',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'token_id'
        mock_http_client.delete.assert_not_called()


class TestGetRegistrationGuide:
    """Tests for get_registration_guide tool."""

    @pytest.mark.asyncio
    async def test_get_registration_guide_success(
        self, mock_http_client, mock_token_manager
    ):
        """Returns installation guide for the specified platform and token."""
        guide = {
            'platform': 'debian',
            'commands': ['curl -s https://install.sh | bash'],
        }
        mock_http_client.post.return_value = guide

        result = await get_registration_guide(
            workspace='testworkspace',
            platform='debian',
            token_id='a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data'] == guide
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/registration-methods/token-install/guide/',
            token='test-token',
            data={
                'platform': 'debian',
                'token': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            },
            params={'response_type': 'json'},
        )

    @pytest.mark.asyncio
    async def test_get_registration_guide_with_server_name(
        self, mock_http_client, mock_token_manager
    ):
        """Includes server_name in POST body when provided."""
        mock_http_client.post.return_value = {'platform': 'rhel', 'commands': []}

        await get_registration_guide(
            workspace='testworkspace',
            platform='rhel',
            token_id='a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            server_name='my-new-server',
            region='ap1',
        )

        _, kwargs = mock_http_client.post.call_args
        assert kwargs['data']['server_name'] == 'my-new-server'

    @pytest.mark.asyncio
    async def test_get_registration_guide_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Returns error when auth token is missing."""
        mock_token_manager.get_token.return_value = None

        result = await get_registration_guide(
            workspace='testworkspace', platform='debian', token_id='tok-123'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_registration_guide_invalid_token_id(
        self, mock_http_client, mock_token_manager
    ):
        """Returns validation error when token_id is not a valid UUID."""
        result = await get_registration_guide(
            workspace='testworkspace',
            platform='debian',
            token_id='not-a-uuid',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'token_id'
        mock_http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_registration_guide_invalid_platform(
        self, mock_http_client, mock_token_manager
    ):
        """Returns validation error when platform is unsupported."""
        result = await get_registration_guide(
            workspace='testworkspace',
            platform='solaris',
            token_id='a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            region='ap1',
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'platform'
        mock_http_client.post.assert_not_called()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
