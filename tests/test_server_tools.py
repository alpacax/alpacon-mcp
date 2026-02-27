"""
Unit tests for server tools module.

Tests all server management functions including server listing, details, and notes management.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tools.server_tools import (
    create_server_note,
    get_server,
    list_server_notes,
    list_servers,
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
        'id': 'server-123',
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
                'id': 'server-123',
                'name': 'web-server-01',
                'ip': '192.168.1.10',
                'status': 'running',
                'os': 'Ubuntu 20.04',
                'tags': ['web', 'production'],
            },
            {
                'id': 'server-456',
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

        result = await get_server(server_id='server-123', workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['data'] == sample_server
        assert result['server_id'] == 'server-123'

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
            params={'id': 'server-123'},
        )

    @pytest.mark.asyncio
    async def test_get_server_no_token(self, mock_http_client, mock_token_manager):
        """Test server details with no token."""
        mock_token_manager.get_token.return_value = None

        result = await get_server(server_id='server-123', workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_server_not_found(self, mock_http_client, mock_token_manager):
        """Test server details with non-existent server."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await get_server(server_id='nonexistent', workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'Server not found' in result['message']

    @pytest.mark.asyncio
    async def test_get_server_different_region(
        self, mock_http_client, mock_token_manager, sample_server
    ):
        """Test server details with different region."""
        mock_http_client.get.return_value = {'count': 1, 'results': [sample_server]}

        result = await get_server(
            server_id='server-123', workspace='testworkspace', region='eu1'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='eu1',
            workspace='testworkspace',
            endpoint='/api/servers/servers/',
            token='test-token',
            params={'id': 'server-123'},
        )

    @pytest.mark.asyncio
    async def test_get_server_http_error(self, mock_http_client, mock_token_manager):
        """Test server details with HTTP error."""
        mock_http_client.get.side_effect = Exception('HTTP 404: Server not found')

        result = await get_server(server_id='nonexistent', workspace='testworkspace')

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
            server_id='server-123', workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['data'] == sample_server_notes
        assert len(result['data']['results']) == 2

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/servers/notes/?server=server-123',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_list_server_notes_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """Test server notes list with no token."""
        mock_token_manager.get_token.return_value = None

        result = await list_server_notes(
            server_id='server-123', workspace='testworkspace'
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
            server_id='server-123',
            title='New Note',
            content='This is a new note about the server',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['data'] == created_note
        assert result['server_id'] == 'server-123'

        expected_data = {
            'server': 'server-123',
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
            server_id='server-123',
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
            server_id='server-123',
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
            server_id='server-123',
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
