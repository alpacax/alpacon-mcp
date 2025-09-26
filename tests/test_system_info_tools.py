"""
Unit tests for system_info_tools module.

Tests system information functionality including system details,
OS version, users, groups, packages, network interfaces, and disk information.
"""
import pytest
from unittest.mock import AsyncMock, patch


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
    with patch('tools.system_info_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


class TestGetSystemInfo:
    """Test get_system_info function."""

    @pytest.mark.asyncio
    async def test_system_info_success(self, mock_http_client, mock_token_manager):
        """Test successful system information retrieval."""
        from tools.system_info_tools import get_system_info

        # Mock successful response
        mock_http_client.get.return_value = {
            "hostname": "web-server-1",
            "kernel": "Linux 5.4.0-74-generic",
            "architecture": "x86_64",
            "cpu_cores": 4,
            "cpu_model": "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz",
            "total_memory": 8589934592,
            "uptime": 123456,
            "load_average": [0.5, 0.7, 0.8]
        }

        result = await get_system_info(
            server_id="server-001",
            workspace="testworkspace",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result
        assert result["data"]["hostname"] == "web-server-1"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/info/",
            token="test-token",
            params={"server": "server-001"}
        )

    @pytest.mark.asyncio
    async def test_system_info_no_token(self, mock_http_client, mock_token_manager):
        """Test system info when no token is available."""
        from tools.system_info_tools import get_system_info

        mock_token_manager.get_token.return_value = None

        result = await get_system_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_info_http_error(self, mock_http_client, mock_token_manager):
        """Test system info with HTTP error."""
        from tools.system_info_tools import get_system_info

        mock_http_client.get.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await get_system_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get system info" in result["message"]


class TestGetOsVersion:
    """Test get_os_version function."""

    @pytest.mark.asyncio
    async def test_os_version_success(self, mock_http_client, mock_token_manager):
        """Test successful OS version retrieval."""
        from tools.system_info_tools import get_os_version

        # Mock successful response
        mock_http_client.get.return_value = {
            "name": "Ubuntu",
            "version": "20.04.2 LTS",
            "codename": "focal",
            "id": "ubuntu",
            "id_like": "debian",
            "version_id": "20.04",
            "version_codename": "focal",
            "description": "Ubuntu 20.04.2 LTS"
        }

        result = await get_os_version(
            server_id="server-001",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["name"] == "Ubuntu"
        assert result["data"]["version"] == "20.04.2 LTS"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/os/",
            token="test-token",
            params={"server": "server-001"}
        )

    @pytest.mark.asyncio
    async def test_os_version_no_token(self, mock_http_client, mock_token_manager):
        """Test OS version when no token is available."""
        from tools.system_info_tools import get_os_version

        mock_token_manager.get_token.return_value = None

        result = await get_os_version(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestListSystemUsers:
    """Test list_system_users function."""

    @pytest.mark.asyncio
    async def test_list_users_success(self, mock_http_client, mock_token_manager):
        """Test successful system users listing."""
        from tools.system_info_tools import list_system_users

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 3,
            "results": [
                {
                    "username": "root",
                    "uid": 0,
                    "gid": 0,
                    "home": "/root",
                    "shell": "/bin/bash",
                    "login_enabled": True
                },
                {
                    "username": "ubuntu",
                    "uid": 1000,
                    "gid": 1000,
                    "home": "/home/ubuntu",
                    "shell": "/bin/bash",
                    "login_enabled": True
                },
                {
                    "username": "www-data",
                    "uid": 33,
                    "gid": 33,
                    "home": "/var/www",
                    "shell": "/usr/sbin/nologin",
                    "login_enabled": False
                }
            ]
        }

        result = await list_system_users(
            server_id="server-001",
            workspace="testworkspace",
            username_filter="ubuntu",
            login_enabled_only=True,
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["username_filter"] == "ubuntu"
        assert result["login_enabled_only"] == True
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 3

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/users/",
            token="test-token",
            params={
                "server": "server-001",
                "search": "ubuntu",
                "login_enabled": "true"
            }
        )

    @pytest.mark.asyncio
    async def test_list_users_minimal_params(self, mock_http_client, mock_token_manager):
        """Test users listing with minimal parameters."""
        from tools.system_info_tools import list_system_users

        mock_http_client.get.return_value = {"count": 10, "results": []}

        result = await list_system_users(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["username_filter"] is None
        assert result["login_enabled_only"] == False

        # Verify only server parameter was included
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"] == {"server": "server-001"}

    @pytest.mark.asyncio
    async def test_list_users_no_token(self, mock_http_client, mock_token_manager):
        """Test users listing when no token is available."""
        from tools.system_info_tools import list_system_users

        mock_token_manager.get_token.return_value = None

        result = await list_system_users(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestListSystemGroups:
    """Test list_system_groups function."""

    @pytest.mark.asyncio
    async def test_list_groups_success(self, mock_http_client, mock_token_manager):
        """Test successful system groups listing."""
        from tools.system_info_tools import list_system_groups

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 4,
            "results": [
                {
                    "groupname": "root",
                    "gid": 0,
                    "members": ["root"]
                },
                {
                    "groupname": "sudo",
                    "gid": 27,
                    "members": ["ubuntu"]
                },
                {
                    "groupname": "docker",
                    "gid": 999,
                    "members": ["ubuntu", "user1"]
                },
                {
                    "groupname": "www-data",
                    "gid": 33,
                    "members": []
                }
            ]
        }

        result = await list_system_groups(
            server_id="server-001",
            workspace="testworkspace",
            groupname_filter="docker",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["groupname_filter"] == "docker"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 4

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/groups/",
            token="test-token",
            params={
                "server": "server-001",
                "search": "docker"
            }
        )

    @pytest.mark.asyncio
    async def test_list_groups_no_filter(self, mock_http_client, mock_token_manager):
        """Test groups listing without filter."""
        from tools.system_info_tools import list_system_groups

        mock_http_client.get.return_value = {"count": 0, "results": []}

        result = await list_system_groups(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["groupname_filter"] is None

        # Verify only server parameter was included
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"] == {"server": "server-001"}

    @pytest.mark.asyncio
    async def test_list_groups_no_token(self, mock_http_client, mock_token_manager):
        """Test groups listing when no token is available."""
        from tools.system_info_tools import list_system_groups

        mock_token_manager.get_token.return_value = None

        result = await list_system_groups(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestListSystemPackages:
    """Test list_system_packages function."""

    @pytest.mark.asyncio
    async def test_list_packages_success(self, mock_http_client, mock_token_manager):
        """Test successful system packages listing."""
        from tools.system_info_tools import list_system_packages

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 2,
            "results": [
                {
                    "name": "nginx",
                    "version": "1.18.0-6ubuntu14.3",
                    "architecture": "amd64",
                    "status": "installed",
                    "description": "small, powerful, scalable web/proxy server"
                },
                {
                    "name": "nginx-common",
                    "version": "1.18.0-6ubuntu14.3",
                    "architecture": "all",
                    "status": "installed",
                    "description": "small, powerful, scalable web/proxy server - common files"
                }
            ]
        }

        result = await list_system_packages(
            server_id="server-001",
            workspace="testworkspace",
            package_name="nginx",
            architecture="amd64",
            limit=50,
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["package_name"] == "nginx"
        assert result["architecture"] == "amd64"
        assert result["limit"] == 50
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/packages/",
            token="test-token",
            params={
                "server": "server-001",
                "page_size": 50,
                "search": "nginx",
                "arch": "amd64"
            }
        )

    @pytest.mark.asyncio
    async def test_list_packages_minimal_params(self, mock_http_client, mock_token_manager):
        """Test packages listing with minimal parameters."""
        from tools.system_info_tools import list_system_packages

        mock_http_client.get.return_value = {"count": 500, "results": []}

        result = await list_system_packages(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["package_name"] is None
        assert result["architecture"] is None
        assert result["limit"] == 100  # Default value

        # Verify correct parameters were sent
        call_args = mock_http_client.get.call_args
        expected_params = {
            "server": "server-001",
            "page_size": 100
        }
        assert call_args[1]["params"] == expected_params

    @pytest.mark.asyncio
    async def test_list_packages_no_token(self, mock_http_client, mock_token_manager):
        """Test packages listing when no token is available."""
        from tools.system_info_tools import list_system_packages

        mock_token_manager.get_token.return_value = None

        result = await list_system_packages(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetNetworkInterfaces:
    """Test get_network_interfaces function."""

    @pytest.mark.asyncio
    async def test_network_interfaces_success(self, mock_http_client, mock_token_manager):
        """Test successful network interfaces retrieval."""
        from tools.system_info_tools import get_network_interfaces

        # Mock successful response
        mock_http_client.get.return_value = {
            "interfaces": [
                {
                    "name": "lo",
                    "type": "loopback",
                    "state": "up",
                    "mtu": 65536,
                    "addresses": ["127.0.0.1/8", "::1/128"]
                },
                {
                    "name": "eth0",
                    "type": "ethernet",
                    "state": "up",
                    "mtu": 1500,
                    "addresses": ["192.168.1.100/24", "fe80::a00:27ff:fe4e:66a1/64"],
                    "mac": "08:00:27:4e:66:a1"
                }
            ]
        }

        result = await get_network_interfaces(
            server_id="server-001",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "interfaces" in result["data"]
        assert len(result["data"]["interfaces"]) == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/interfaces/",
            token="test-token",
            params={"server": "server-001"}
        )

    @pytest.mark.asyncio
    async def test_network_interfaces_no_token(self, mock_http_client, mock_token_manager):
        """Test network interfaces when no token is available."""
        from tools.system_info_tools import get_network_interfaces

        mock_token_manager.get_token.return_value = None

        result = await get_network_interfaces(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetDiskInfo:
    """Test get_disk_info function."""

    @pytest.mark.asyncio
    async def test_disk_info_success(self, mock_http_client, mock_token_manager):
        """Test successful disk info retrieval."""
        from tools.system_info_tools import get_disk_info

        # Mock successful responses for both disks and partitions
        disks_data = {
            "disks": [
                {
                    "device": "/dev/sda",
                    "size": 107374182400,
                    "model": "VBOX HARDDISK",
                    "type": "hdd"
                }
            ]
        }

        partitions_data = {
            "partitions": [
                {
                    "device": "/dev/sda1",
                    "mountpoint": "/",
                    "filesystem": "ext4",
                    "size": 107374182400,
                    "used": 45964566528,
                    "available": 61409615872
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
            server_id="server-001",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["data"]["server_id"] == "server-001"
        assert result["data"]["region"] == "ap1"
        assert result["data"]["workspace"] == "testworkspace"
        assert "disks" in result["data"]
        assert "partitions" in result["data"]
        assert result["data"]["disks"] == disks_data
        assert result["data"]["partitions"] == partitions_data

        # Verify both endpoints were called
        assert mock_http_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_disk_info_partial_failure(self, mock_http_client, mock_token_manager):
        """Test disk info with partial failure."""
        from tools.system_info_tools import get_disk_info

        disks_data = {"disks": [{"device": "/dev/sda"}]}
        partitions_error = Exception("Partitions service unavailable")

        def mock_get_side_effect(*args, **kwargs):
            endpoint = kwargs.get('endpoint', '')
            if 'disks' in endpoint:
                return disks_data
            elif 'partitions' in endpoint:
                raise partitions_error
            return {}

        mock_http_client.get.side_effect = mock_get_side_effect

        result = await get_disk_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"]["disks"] == disks_data
        assert "error" in result["data"]["partitions"]
        assert "Partitions service unavailable" in result["data"]["partitions"]["error"]

    @pytest.mark.asyncio
    async def test_disk_info_no_token(self, mock_http_client, mock_token_manager):
        """Test disk info when no token is available."""
        from tools.system_info_tools import get_disk_info

        mock_token_manager.get_token.return_value = None

        result = await get_disk_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetSystemTime:
    """Test get_system_time function."""

    @pytest.mark.asyncio
    async def test_system_time_success(self, mock_http_client, mock_token_manager):
        """Test successful system time retrieval."""
        from tools.system_info_tools import get_system_time

        # Mock successful response
        mock_http_client.get.return_value = {
            "current_time": "2024-01-01T12:00:00Z",
            "timezone": "UTC",
            "uptime": 3600,
            "boot_time": "2024-01-01T11:00:00Z",
            "uptime_human": "1 hour, 0 minutes"
        }

        result = await get_system_time(
            server_id="server-001",
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["current_time"] == "2024-01-01T12:00:00Z"
        assert result["data"]["timezone"] == "UTC"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/proc/time/",
            token="test-token",
            params={"server": "server-001"}
        )

    @pytest.mark.asyncio
    async def test_system_time_no_token(self, mock_http_client, mock_token_manager):
        """Test system time when no token is available."""
        from tools.system_info_tools import get_system_time

        mock_token_manager.get_token.return_value = None

        result = await get_system_time(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetServerOverview:
    """Test get_server_overview function."""

    @pytest.mark.asyncio
    async def test_server_overview_success(self, mock_http_client, mock_token_manager):
        """Test successful server overview retrieval."""
        from tools.system_info_tools import get_server_overview

        # Mock successful responses for all individual functions
        with patch('tools.system_info_tools.get_system_info') as mock_sys_info, \
             patch('tools.system_info_tools.get_os_version') as mock_os_version, \
             patch('tools.system_info_tools.get_system_time') as mock_sys_time, \
             patch('tools.system_info_tools.get_network_interfaces') as mock_network, \
             patch('tools.system_info_tools.get_disk_info') as mock_disk:

            # Mock successful responses
            mock_sys_info.return_value = {"status": "success", "data": {"hostname": "web-server"}}
            mock_os_version.return_value = {"status": "success", "data": {"name": "Ubuntu"}}
            mock_sys_time.return_value = {"status": "success", "data": {"uptime": 3600}}
            mock_network.return_value = {"status": "success", "data": {"interfaces": []}}
            mock_disk.return_value = {"status": "success", "data": {"disks": []}}

            result = await get_server_overview(
                server_id="server-001",
                workspace="testworkspace",
                region="ap1"
            )

            assert result["status"] == "success"
            assert result["data"]["server_id"] == "server-001"
            assert result["data"]["region"] == "ap1"
            assert result["data"]["workspace"] == "testworkspace"

            # Verify all sections are present
            assert "system_info" in result["data"]
            assert "os_version" in result["data"]
            assert "system_time" in result["data"]
            assert "network_interfaces" in result["data"]
            assert "disk_info" in result["data"]

            # Verify data was populated correctly
            assert result["data"]["system_info"]["hostname"] == "web-server"
            assert result["data"]["os_version"]["name"] == "Ubuntu"

            # Verify all functions were called
            mock_sys_info.assert_called_once()
            mock_os_version.assert_called_once()
            mock_sys_time.assert_called_once()
            mock_network.assert_called_once()
            mock_disk.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_overview_partial_failure(self, mock_http_client, mock_token_manager):
        """Test server overview with some functions failing."""
        from tools.system_info_tools import get_server_overview

        with patch('tools.system_info_tools.get_system_info') as mock_sys_info, \
             patch('tools.system_info_tools.get_os_version') as mock_os_version, \
             patch('tools.system_info_tools.get_system_time') as mock_sys_time, \
             patch('tools.system_info_tools.get_network_interfaces') as mock_network, \
             patch('tools.system_info_tools.get_disk_info') as mock_disk:

            # Mock mixed success/failure responses
            mock_sys_info.return_value = {"status": "success", "data": {"hostname": "web-server"}}
            mock_os_version.return_value = {"status": "error", "message": "OS service unavailable"}
            mock_sys_time.side_effect = Exception("Time service error")
            mock_network.return_value = {"status": "success", "data": {"interfaces": []}}
            mock_disk.return_value = {"status": "success", "data": {"disks": []}}

            result = await get_server_overview(
                server_id="server-001",
                workspace="testworkspace"
            )

            assert result["status"] == "success"

            # Successful functions should have data
            assert result["data"]["system_info"]["hostname"] == "web-server"
            assert result["data"]["network_interfaces"]["interfaces"] == []

            # Failed functions should have error information
            assert "error" in result["data"]["os_version"]
            assert "OS service unavailable" in result["data"]["os_version"]["error"]
            assert "error" in result["data"]["system_time"]
            assert "Time service error" in result["data"]["system_time"]["error"]

    @pytest.mark.asyncio
    async def test_server_overview_exception(self, mock_http_client, mock_token_manager):
        """Test server overview with general exception."""
        from tools.system_info_tools import get_server_overview

        with patch('asyncio.gather') as mock_gather:
            # Mock asyncio.gather to raise an exception
            mock_gather.side_effect = Exception("Async processing failed")

            result = await get_server_overview(
                server_id="server-001",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "Failed to get server overview" in result["message"]
            assert "Async processing failed" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])