"""
Unit tests for system_info_tools module - additional edge case tests.

Tests additional edge cases and cross-function scenarios for
system information tools. The module was previously named system_tools
and has been refactored to system_info_tools.

Note: Core function tests are in test_system_info_tools.py.
This file covers additional scenarios like region variations,
error conditions, and parameter handling.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.system_info_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = 'test-token'
        yield mock_manager


class TestSystemInfoEdgeCases:
    """Test get_system_info edge cases."""

    @pytest.mark.asyncio
    async def test_system_info_success(self, mock_http_client, mock_token_manager):
        """Test successful system info retrieval."""
        from tools.system_info_tools import get_system_info

        # Mock successful response
        mock_http_client.get.return_value = {
            'hostname': 'web-server-01',
            'kernel': 'Linux 5.4.0-74-generic',
            'architecture': 'x86_64',
            'cpu_cores': 4,
            'uptime': 86400,
            'load_average': [1.25, 1.15, 1.05],
        }

        result = await get_system_info(
            server_id='server-001', workspace='testworkspace', region='ap1'
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['server_id'] == 'server-001'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result
        assert result['data']['hostname'] == 'web-server-01'

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/proc/info/',
            token='test-token',
            params={'server': 'server-001'},
        )

    @pytest.mark.asyncio
    async def test_system_info_no_token(self, mock_http_client, mock_token_manager):
        """Test system info when no token is available."""
        from tools.system_info_tools import get_system_info

        mock_token_manager.get_token.return_value = None

        result = await get_system_info(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_info_http_error(self, mock_http_client, mock_token_manager):
        """Test system info with HTTP error."""
        from tools.system_info_tools import get_system_info

        mock_http_client.get.side_effect = Exception('HTTP 500 Internal Server Error')

        result = await get_system_info(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'Failed in get_system_info' in result['message']
        assert 'HTTP 500' in result['message']

    @pytest.mark.asyncio
    async def test_system_info_different_region(
        self, mock_http_client, mock_token_manager
    ):
        """Test system info with different region."""
        from tools.system_info_tools import get_system_info

        mock_http_client.get.return_value = {'hostname': 'eu-server'}

        result = await get_system_info(
            server_id='server-001', workspace='testworkspace', region='eu1'
        )

        assert result['status'] == 'success'
        assert result['region'] == 'eu1'

        # Verify correct region was used
        call_args = mock_http_client.get.call_args
        assert call_args[1]['region'] == 'eu1'


class TestListSystemUsersEdgeCases:
    """Test list_system_users edge cases."""

    @pytest.mark.asyncio
    async def test_users_list_success(self, mock_http_client, mock_token_manager):
        """Test successful users list retrieval."""
        from tools.system_info_tools import list_system_users

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 3,
            'results': [
                {
                    'username': 'root',
                    'uid': 0,
                    'gid': 0,
                    'home': '/root',
                    'shell': '/bin/bash',
                    'login_enabled': True,
                },
                {
                    'username': 'ubuntu',
                    'uid': 1000,
                    'gid': 1000,
                    'home': '/home/ubuntu',
                    'shell': '/bin/bash',
                    'login_enabled': True,
                },
                {
                    'username': 'www-data',
                    'uid': 33,
                    'gid': 33,
                    'home': '/var/www',
                    'shell': '/usr/sbin/nologin',
                    'login_enabled': False,
                },
            ],
        }

        result = await list_system_users(
            server_id='server-001', workspace='testworkspace', region='ap1'
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['server_id'] == 'server-001'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result
        assert result['data']['count'] == 3

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/proc/users/',
            token='test-token',
            params={'server': 'server-001'},
        )

    @pytest.mark.asyncio
    async def test_users_list_no_token(self, mock_http_client, mock_token_manager):
        """Test users list when no token is available."""
        from tools.system_info_tools import list_system_users

        mock_token_manager.get_token.return_value = None

        result = await list_system_users(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_users_list_http_error(self, mock_http_client, mock_token_manager):
        """Test users list with HTTP error."""
        from tools.system_info_tools import list_system_users

        mock_http_client.get.side_effect = Exception('HTTP 503 Service Unavailable')

        result = await list_system_users(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'Failed in list_system_users' in result['message']
        assert '503' in result['message']


class TestListSystemPackagesEdgeCases:
    """Test list_system_packages edge cases."""

    @pytest.mark.asyncio
    async def test_packages_list_success(self, mock_http_client, mock_token_manager):
        """Test successful packages list retrieval."""
        from tools.system_info_tools import list_system_packages

        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 2,
            'results': [
                {
                    'name': 'nginx',
                    'version': '1.18.0-6ubuntu14.3',
                    'architecture': 'amd64',
                    'status': 'installed',
                },
                {
                    'name': 'python3',
                    'version': '3.8.2-0ubuntu2',
                    'architecture': 'amd64',
                    'status': 'installed',
                },
            ],
        }

        result = await list_system_packages(
            server_id='server-001', workspace='testworkspace', region='ap1'
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['server_id'] == 'server-001'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result
        assert result['data']['count'] == 2

    @pytest.mark.asyncio
    async def test_packages_list_empty(self, mock_http_client, mock_token_manager):
        """Test packages list with empty response."""
        from tools.system_info_tools import list_system_packages

        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_system_packages(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert result['data']['count'] == 0

    @pytest.mark.asyncio
    async def test_packages_list_no_token(self, mock_http_client, mock_token_manager):
        """Test packages list when no token is available."""
        from tools.system_info_tools import list_system_packages

        mock_token_manager.get_token.return_value = None

        result = await list_system_packages(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_packages_list_http_error(self, mock_http_client, mock_token_manager):
        """Test packages list with HTTP error."""
        from tools.system_info_tools import list_system_packages

        mock_http_client.get.side_effect = Exception('Connection timeout')

        result = await list_system_packages(
            server_id='server-001', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'Failed in list_system_packages' in result['message']
        assert 'Connection timeout' in result['message']


class TestGetDiskInfoEdgeCases:
    """Test get_disk_info edge cases."""

    @pytest.mark.asyncio
    async def test_disk_info_success(self, mock_http_client, mock_token_manager):
        """Test successful disk info retrieval."""
        from tools.system_info_tools import get_disk_info

        # Mock successful responses for both disks and partitions
        disks_data = {
            'disks': [
                {
                    'device': '/dev/sda',
                    'size': 107374182400,
                    'model': 'VBOX HARDDISK',
                    'type': 'hdd',
                }
            ]
        }

        partitions_data = {
            'partitions': [
                {
                    'device': '/dev/sda1',
                    'mountpoint': '/',
                    'filesystem': 'ext4',
                    'size': 107374182400,
                }
            ]
        }

        def mock_get_side_effect(*args, **kwargs):
            endpoint = kwargs.get('endpoint', '')
            if 'disks' in endpoint:
                return disks_data
            elif 'partitions' in endpoint:
                return partitions_data
            return {}

        mock_http_client.get.side_effect = mock_get_side_effect

        result = await get_disk_info(
            server_id='server-001', workspace='testworkspace', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['data']['server_id'] == 'server-001'
        assert result['data']['region'] == 'ap1'
        assert result['data']['workspace'] == 'testworkspace'
        assert 'disks' in result['data']
        assert 'partitions' in result['data']

        # Verify both endpoints were called
        assert mock_http_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_disk_info_no_token(self, mock_http_client, mock_token_manager):
        """Test disk info when no token is available."""
        from tools.system_info_tools import get_disk_info

        mock_token_manager.get_token.return_value = None

        result = await get_disk_info(server_id='server-001', workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_disk_info_http_error(self, mock_http_client, mock_token_manager):
        """Test disk info with HTTP error from both endpoints."""
        from tools.system_info_tools import get_disk_info

        mock_http_client.get.side_effect = Exception('Disk service unavailable')

        result = await get_disk_info(server_id='server-001', workspace='testworkspace')

        # get_disk_info uses asyncio.gather with return_exceptions=True
        # so it returns success with error info in the data
        assert result['status'] == 'success'
        assert 'error' in result['data']['disks']
        assert 'error' in result['data']['partitions']


class TestCrossFunctionScenarios:
    """Test cross-function scenarios and edge cases."""

    @pytest.mark.asyncio
    async def test_different_regions_and_workspaces(
        self, mock_http_client, mock_token_manager
    ):
        """Test functions with different regions and workspaces."""
        from tools.system_info_tools import get_system_info, list_system_users

        # Mock successful responses
        mock_http_client.get.return_value = {'test': 'data'}

        # Test with different regions
        for func in [get_system_info, list_system_users]:
            result = await func(
                server_id='eu-server-001', workspace='eu-workspace', region='eu1'
            )

            assert result['status'] == 'success'
            assert result['server_id'] == 'eu-server-001'
            assert result['workspace'] == 'eu-workspace'
            assert result['region'] == 'eu1'

    @pytest.mark.asyncio
    async def test_server_not_found_errors(self, mock_http_client, mock_token_manager):
        """Test functions with server not found errors."""
        from tools.system_info_tools import list_system_users

        mock_http_client.get.side_effect = Exception('HTTP 404 Server Not Found')

        result = await list_system_users(
            server_id='nonexistent-server', workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'Failed in list_system_users' in result['message']
        assert '404' in result['message']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
