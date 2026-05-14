"""Unit tests for security ACL tools."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.security_tools import (
    bulk_server_acl,
    delete_file_acl,
    delete_server_acl,
    update_file_acl,
    update_server_acl,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.security_tools.http_client') as mock_client:
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


class TestUpdateServerAcl:
    """Test update_server_acl tool."""

    @pytest.mark.asyncio
    async def test_update_server_acl_success(self, mock_http_client, mock_token_manager):
        """Test successful server ACL rule update."""
        mock_http_client.patch.return_value = {
            'id': 'acl-1',
            'effect': 'deny',
            'description': 'Updated rule',
        }

        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            effect='deny',
            description='Updated rule',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
            data={'effect': 'deny', 'description': 'Updated rule'},
        )

    @pytest.mark.asyncio
    async def test_update_server_acl_users_and_groups(
        self, mock_http_client, mock_token_manager
    ):
        """Test server ACL update with users and groups."""
        mock_http_client.patch.return_value = {'id': 'acl-1', 'effect': 'allow'}

        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            users=['user-1', 'user-2'],
            groups=['group-1'],
            priority=10,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
            data={'users': ['user-1', 'user-2'], 'groups': ['group-1'], 'priority': 10},
        )

    @pytest.mark.asyncio
    async def test_update_server_acl_no_data_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that updating with no fields returns an error."""
        result = await update_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_server_acl_servers_field(
        self, mock_http_client, mock_token_manager
    ):
        """Test server ACL update with servers field."""
        mock_http_client.patch.return_value = {'id': 'acl-2', 'effect': 'allow'}

        result = await update_server_acl(
            acl_id='acl-2',
            workspace='testworkspace',
            servers=['server-uuid-1'],
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-2/',
            token='test-token',
            data={'servers': ['server-uuid-1']},
        )


class TestDeleteServerAcl:
    """Test delete_server_acl tool."""

    @pytest.mark.asyncio
    async def test_delete_server_acl_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful server ACL rule deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_server_acl(
            acl_id='acl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_delete_server_acl_default_region(
        self, mock_http_client, mock_token_manager
    ):
        """Test server ACL deletion with default region (auto-resolved to ap1)."""
        mock_http_client.delete.return_value = {}

        result = await delete_server_acl(
            acl_id='acl-99',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'acl-99'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/acl-99/',
            token='test-token',
        )


class TestBulkServerAcl:
    """Test bulk_server_acl tool."""

    @pytest.mark.asyncio
    async def test_bulk_server_acl_add_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful bulk add of server ACL entries."""
        acl_entries = [
            {'effect': 'allow', 'users': ['user-1'], 'servers': ['server-1']},
            {'effect': 'allow', 'users': ['user-2'], 'servers': ['server-2']},
        ]
        mock_http_client.post.return_value = {'created': 2}

        result = await bulk_server_acl(
            workspace='testworkspace',
            action='add',
            acl_list=acl_entries,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['action'] == 'add'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/bulk/',
            token='test-token',
            data={'action': 'add', 'acls': acl_entries},
        )

    @pytest.mark.asyncio
    async def test_bulk_server_acl_remove_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful bulk remove of server ACL entries."""
        acl_entries = [{'id': 'acl-1'}, {'id': 'acl-2'}]
        mock_http_client.post.return_value = {'deleted': 2}

        result = await bulk_server_acl(
            workspace='testworkspace',
            action='remove',
            acl_list=acl_entries,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['action'] == 'remove'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/server-acl/bulk/',
            token='test-token',
            data={'action': 'remove', 'acls': acl_entries},
        )

    @pytest.mark.asyncio
    async def test_bulk_server_acl_invalid_action_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that an invalid action returns an error without calling the API."""
        result = await bulk_server_acl(
            workspace='testworkspace',
            action='delete',
            acl_list=[{'id': 'acl-1'}],
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.post.assert_not_called()


class TestUpdateFileAcl:
    """Test update_file_acl tool."""

    @pytest.mark.asyncio
    async def test_update_file_acl_success(self, mock_http_client, mock_token_manager):
        """Test successful file ACL rule update."""
        mock_http_client.patch.return_value = {
            'id': 'facl-1',
            'effect': 'deny',
            'file_pattern': '/etc/passwd',
        }

        result = await update_file_acl(
            acl_id='facl-1',
            workspace='testworkspace',
            effect='deny',
            file_pattern='/etc/passwd',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'facl-1'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/facl-1/',
            token='test-token',
            data={'effect': 'deny', 'file_pattern': '/etc/passwd'},
        )

    @pytest.mark.asyncio
    async def test_update_file_acl_with_all_fields(
        self, mock_http_client, mock_token_manager
    ):
        """Test file ACL update with all optional fields."""
        mock_http_client.patch.return_value = {'id': 'facl-1'}

        result = await update_file_acl(
            acl_id='facl-1',
            workspace='testworkspace',
            effect='allow',
            file_pattern='/var/log/*',
            users=['user-1'],
            groups=['group-1'],
            servers=['server-1'],
            description='Allow log access',
            priority=5,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.patch.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/facl-1/',
            token='test-token',
            data={
                'effect': 'allow',
                'file_pattern': '/var/log/*',
                'users': ['user-1'],
                'groups': ['group-1'],
                'servers': ['server-1'],
                'description': 'Allow log access',
                'priority': 5,
            },
        )

    @pytest.mark.asyncio
    async def test_update_file_acl_no_data_returns_error(
        self, mock_http_client, mock_token_manager
    ):
        """Test that updating with no fields returns an error."""
        result = await update_file_acl(
            acl_id='facl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'error'
        mock_http_client.patch.assert_not_called()


class TestDeleteFileAcl:
    """Test delete_file_acl tool."""

    @pytest.mark.asyncio
    async def test_delete_file_acl_success(self, mock_http_client, mock_token_manager):
        """Test successful file ACL rule deletion."""
        mock_http_client.delete.return_value = {}

        result = await delete_file_acl(
            acl_id='facl-1',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'facl-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/facl-1/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_delete_file_acl_default_region(
        self, mock_http_client, mock_token_manager
    ):
        """Test file ACL deletion with default region (auto-resolved to ap1)."""
        mock_http_client.delete.return_value = {}

        result = await delete_file_acl(
            acl_id='facl-42',
            workspace='testworkspace',
        )

        assert result['status'] == 'success'
        assert result['acl_id'] == 'facl-42'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/security/file-acl/facl-42/',
            token='test-token',
        )
