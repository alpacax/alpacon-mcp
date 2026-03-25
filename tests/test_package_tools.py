"""Unit tests for package management tools module."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.package_tools import (
    install_python_package,
    install_system_package,
    list_python_packages,
    list_system_package_entries,
    remove_python_package,
    remove_system_package,
)


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.package_tools.http_client') as mock_client:
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


SERVER_ID = '550e8400-e29b-41d4-a716-446655440123'


class TestSystemPackages:
    """Test system package tools."""

    @pytest.mark.asyncio
    async def test_list_system_package_entries_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful system package entries listing."""
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'pkg-1', 'name': 'nginx'},
                {'id': 'pkg-2', 'name': 'curl'},
            ],
        }

        result = await list_system_package_entries(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/entries/',
            token='test-token',
            params={'server': SERVER_ID},
        )

    @pytest.mark.asyncio
    async def test_list_system_package_entries_with_pagination(
        self, mock_http_client, mock_token_manager
    ):
        """Test system package entries listing with pagination."""
        mock_http_client.get.return_value = {'count': 50, 'results': []}

        result = await list_system_package_entries(
            server_id=SERVER_ID,
            workspace='testworkspace',
            page=2,
            page_size=10,
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/entries/',
            token='test-token',
            params={'server': SERVER_ID, 'page': 2, 'page_size': 10},
        )

    @pytest.mark.asyncio
    async def test_install_system_package_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful system package installation."""
        mock_http_client.post.return_value = {
            'id': 'pkg-3',
            'name': 'htop',
            'server': SERVER_ID,
        }

        result = await install_system_package(
            server_id=SERVER_ID,
            package_name='htop',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/entries/',
            token='test-token',
            data={'server': SERVER_ID, 'name': 'htop'},
        )

    @pytest.mark.asyncio
    async def test_install_system_package_with_version(
        self, mock_http_client, mock_token_manager
    ):
        """Test system package installation with specific version."""
        mock_http_client.post.return_value = {'id': 'pkg-4', 'name': 'nginx'}

        result = await install_system_package(
            server_id=SERVER_ID,
            package_name='nginx',
            workspace='testworkspace',
            version='1.24.0',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/entries/',
            token='test-token',
            data={'server': SERVER_ID, 'name': 'nginx', 'version': '1.24.0'},
        )

    @pytest.mark.asyncio
    async def test_remove_system_package_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful system package removal."""
        mock_http_client.delete.return_value = {}

        result = await remove_system_package(
            entry_id='pkg-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['entry_id'] == 'pkg-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/entries/pkg-1/',
            token='test-token',
        )


class TestPythonPackages:
    """Test Python package tools."""

    @pytest.mark.asyncio
    async def test_list_python_packages_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful Python packages listing."""
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {'id': 'py-1', 'name': 'requests'},
                {'id': 'py-2', 'name': 'flask'},
            ],
        }

        result = await list_python_packages(
            server_id=SERVER_ID, workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/python/',
            token='test-token',
            params={'server': SERVER_ID},
        )

    @pytest.mark.asyncio
    async def test_install_python_package_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful Python package installation."""
        mock_http_client.post.return_value = {
            'id': 'py-3',
            'name': 'django',
            'server': SERVER_ID,
        }

        result = await install_python_package(
            server_id=SERVER_ID,
            package_name='django',
            workspace='testworkspace',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/python/',
            token='test-token',
            data={'server': SERVER_ID, 'name': 'django'},
        )

    @pytest.mark.asyncio
    async def test_install_python_package_with_version(
        self, mock_http_client, mock_token_manager
    ):
        """Test Python package installation with specific version."""
        mock_http_client.post.return_value = {'id': 'py-4', 'name': 'django'}

        result = await install_python_package(
            server_id=SERVER_ID,
            package_name='django',
            workspace='testworkspace',
            version='4.2.0',
            region='ap1',
        )

        assert result['status'] == 'success'
        mock_http_client.post.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/python/',
            token='test-token',
            data={'server': SERVER_ID, 'name': 'django', 'version': '4.2.0'},
        )

    @pytest.mark.asyncio
    async def test_remove_python_package_success(
        self, mock_http_client, mock_token_manager
    ):
        """Test successful Python package removal."""
        mock_http_client.delete.return_value = {}

        result = await remove_python_package(
            entry_id='py-1', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['entry_id'] == 'py-1'
        mock_http_client.delete.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/packages/python/py-1/',
            token='test-token',
        )
