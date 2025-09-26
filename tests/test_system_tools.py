"""
Unit tests for system_tools module.

Tests system tools functionality including hardware information,
users list, packages list, and disk information.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.system_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.system_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


class TestSystemInfo:
    """Test system_info function."""

    @pytest.mark.asyncio
    async def test_system_info_success(self, mock_http_client, mock_token_manager):
        """Test successful system info retrieval."""
        from tools.system_tools import system_info

        # Mock successful response
        mock_http_client.get.return_value = {
            "hostname": "web-server-01",
            "kernel": "Linux 5.4.0-74-generic",
            "architecture": "x86_64",
            "cpu": {
                "cores": 4,
                "model": "Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz",
                "threads": 8,
                "frequency": "3.70GHz"
            },
            "memory": {
                "total": 17179869184,
                "available": 8589934592,
                "used": 8589934592,
                "percent": 50.0
            },
            "uptime": 86400,
            "load_average": [1.25, 1.15, 1.05]
        }

        result = await system_info(
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
        assert result["data"]["hostname"] == "web-server-01"
        assert result["data"]["cpu"]["cores"] == 4

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/servers/server-001/system/info/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_system_info_no_token(self, mock_http_client, mock_token_manager):
        """Test system info when no token is available."""
        from tools.system_tools import system_info

        mock_token_manager.get_token.return_value = None

        result = await system_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_info_http_error(self, mock_http_client, mock_token_manager):
        """Test system info with HTTP error."""
        from tools.system_tools import system_info

        mock_http_client.get.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await system_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get system info" in result["message"]
        assert "HTTP 500" in result["message"]

    @pytest.mark.asyncio
    async def test_system_info_different_region(self, mock_http_client, mock_token_manager):
        """Test system info with different region."""
        from tools.system_tools import system_info

        mock_http_client.get.return_value = {"hostname": "eu-server"}

        result = await system_info(
            server_id="server-001",
            workspace="testworkspace",
            region="eu1"
        )

        assert result["status"] == "success"
        assert result["region"] == "eu1"

        # Verify correct region was used
        call_args = mock_http_client.get.call_args
        assert call_args[1]["region"] == "eu1"


class TestSystemUsersList:
    """Test system_users_list function."""

    @pytest.mark.asyncio
    async def test_users_list_success(self, mock_http_client, mock_token_manager):
        """Test successful users list retrieval."""
        from tools.system_tools import system_users_list

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 5,
            "users": [
                {
                    "username": "root",
                    "uid": 0,
                    "gid": 0,
                    "home": "/root",
                    "shell": "/bin/bash",
                    "description": "root",
                    "login_enabled": True
                },
                {
                    "username": "ubuntu",
                    "uid": 1000,
                    "gid": 1000,
                    "home": "/home/ubuntu",
                    "shell": "/bin/bash",
                    "description": "Ubuntu",
                    "login_enabled": True
                },
                {
                    "username": "www-data",
                    "uid": 33,
                    "gid": 33,
                    "home": "/var/www",
                    "shell": "/usr/sbin/nologin",
                    "description": "www-data",
                    "login_enabled": False
                },
                {
                    "username": "mysql",
                    "uid": 116,
                    "gid": 125,
                    "home": "/nonexistent",
                    "shell": "/bin/false",
                    "description": "MySQL Server",
                    "login_enabled": False
                },
                {
                    "username": "sshd",
                    "uid": 117,
                    "gid": 65534,
                    "home": "/run/sshd",
                    "shell": "/usr/sbin/nologin",
                    "description": "",
                    "login_enabled": False
                }
            ]
        }

        result = await system_users_list(
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
        assert result["data"]["count"] == 5
        assert len(result["data"]["users"]) == 5

        # Verify user data structure
        root_user = result["data"]["users"][0]
        assert root_user["username"] == "root"
        assert root_user["uid"] == 0
        assert root_user["login_enabled"] == True

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/servers/server-001/system/users/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_users_list_no_token(self, mock_http_client, mock_token_manager):
        """Test users list when no token is available."""
        from tools.system_tools import system_users_list

        mock_token_manager.get_token.return_value = None

        result = await system_users_list(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_users_list_http_error(self, mock_http_client, mock_token_manager):
        """Test users list with HTTP error."""
        from tools.system_tools import system_users_list

        mock_http_client.get.side_effect = Exception("HTTP 503 Service Unavailable")

        result = await system_users_list(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get users list" in result["message"]
        assert "503" in result["message"]


class TestSystemPackagesList:
    """Test system_packages_list function."""

    @pytest.mark.asyncio
    async def test_packages_list_success(self, mock_http_client, mock_token_manager):
        """Test successful packages list retrieval."""
        from tools.system_tools import system_packages_list

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 3,
            "packages": [
                {
                    "name": "nginx",
                    "version": "1.18.0-6ubuntu14.3",
                    "architecture": "amd64",
                    "status": "installed",
                    "description": "small, powerful, scalable web/proxy server",
                    "size": 1024000,
                    "maintainer": "Ubuntu Developers",
                    "section": "httpd"
                },
                {
                    "name": "mysql-server-8.0",
                    "version": "8.0.28-0ubuntu0.20.04.3",
                    "architecture": "amd64",
                    "status": "installed",
                    "description": "MySQL database server binaries and system database setup",
                    "size": 15728640,
                    "maintainer": "Ubuntu Developers",
                    "section": "database"
                },
                {
                    "name": "python3",
                    "version": "3.8.2-0ubuntu2",
                    "architecture": "amd64",
                    "status": "installed",
                    "description": "interactive high-level object-oriented language (default python3 version)",
                    "size": 102400,
                    "maintainer": "Ubuntu Developers",
                    "section": "python"
                }
            ]
        }

        result = await system_packages_list(
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
        assert result["data"]["count"] == 3
        assert len(result["data"]["packages"]) == 3

        # Verify package data structure
        nginx_package = result["data"]["packages"][0]
        assert nginx_package["name"] == "nginx"
        assert nginx_package["version"] == "1.18.0-6ubuntu14.3"
        assert nginx_package["status"] == "installed"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/servers/server-001/system/packages/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_packages_list_empty(self, mock_http_client, mock_token_manager):
        """Test packages list with empty response."""
        from tools.system_tools import system_packages_list

        mock_http_client.get.return_value = {
            "count": 0,
            "packages": []
        }

        result = await system_packages_list(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["data"]["count"] == 0
        assert result["data"]["packages"] == []

    @pytest.mark.asyncio
    async def test_packages_list_no_token(self, mock_http_client, mock_token_manager):
        """Test packages list when no token is available."""
        from tools.system_tools import system_packages_list

        mock_token_manager.get_token.return_value = None

        result = await system_packages_list(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_packages_list_http_error(self, mock_http_client, mock_token_manager):
        """Test packages list with HTTP error."""
        from tools.system_tools import system_packages_list

        mock_http_client.get.side_effect = Exception("Connection timeout")

        result = await system_packages_list(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get packages list" in result["message"]
        assert "Connection timeout" in result["message"]


class TestSystemDiskInfo:
    """Test system_disk_info function."""

    @pytest.mark.asyncio
    async def test_disk_info_success(self, mock_http_client, mock_token_manager):
        """Test successful disk info retrieval."""
        from tools.system_tools import system_disk_info

        # Mock successful response
        mock_http_client.get.return_value = {
            "disks": [
                {
                    "device": "/dev/sda",
                    "size": 107374182400,
                    "size_human": "100GB",
                    "model": "VBOX HARDDISK",
                    "type": "hdd",
                    "removable": False,
                    "readonly": False
                }
            ],
            "partitions": [
                {
                    "device": "/dev/sda1",
                    "mountpoint": "/",
                    "filesystem": "ext4",
                    "size": 105906176000,
                    "size_human": "98.6GB",
                    "used": 45964566528,
                    "used_human": "42.8GB",
                    "available": 59941609472,
                    "available_human": "55.8GB",
                    "percent": 43.4
                }
            ],
            "usage": {
                "total": 105906176000,
                "used": 45964566528,
                "free": 59941609472,
                "percent": 43.4
            }
        }

        result = await system_disk_info(
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

        # Verify disk data structure
        assert "disks" in result["data"]
        assert "partitions" in result["data"]
        assert "usage" in result["data"]
        assert len(result["data"]["disks"]) == 1
        assert len(result["data"]["partitions"]) == 1

        # Verify disk details
        disk = result["data"]["disks"][0]
        assert disk["device"] == "/dev/sda"
        assert disk["size"] == 107374182400
        assert disk["model"] == "VBOX HARDDISK"

        # Verify partition details
        partition = result["data"]["partitions"][0]
        assert partition["device"] == "/dev/sda1"
        assert partition["mountpoint"] == "/"
        assert partition["filesystem"] == "ext4"
        assert partition["percent"] == 43.4

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/servers/server-001/system/disk/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_disk_info_multiple_disks(self, mock_http_client, mock_token_manager):
        """Test disk info with multiple disks and partitions."""
        from tools.system_tools import system_disk_info

        # Mock response with multiple disks
        mock_http_client.get.return_value = {
            "disks": [
                {
                    "device": "/dev/sda",
                    "size": 107374182400,
                    "model": "VBOX HARDDISK",
                    "type": "hdd"
                },
                {
                    "device": "/dev/sdb",
                    "size": 53687091200,
                    "model": "VBOX HARDDISK",
                    "type": "hdd"
                }
            ],
            "partitions": [
                {
                    "device": "/dev/sda1",
                    "mountpoint": "/",
                    "filesystem": "ext4",
                    "percent": 43.4
                },
                {
                    "device": "/dev/sdb1",
                    "mountpoint": "/home",
                    "filesystem": "ext4",
                    "percent": 25.6
                }
            ],
            "usage": {
                "total": 159061273600,
                "used": 68719476736,
                "free": 90341796864,
                "percent": 43.2
            }
        }

        result = await system_disk_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert len(result["data"]["disks"]) == 2
        assert len(result["data"]["partitions"]) == 2
        assert result["data"]["usage"]["percent"] == 43.2

    @pytest.mark.asyncio
    async def test_disk_info_no_token(self, mock_http_client, mock_token_manager):
        """Test disk info when no token is available."""
        from tools.system_tools import system_disk_info

        mock_token_manager.get_token.return_value = None

        result = await system_disk_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_disk_info_http_error(self, mock_http_client, mock_token_manager):
        """Test disk info with HTTP error."""
        from tools.system_tools import system_disk_info

        mock_http_client.get.side_effect = Exception("Disk service unavailable")

        result = await system_disk_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get disk info" in result["message"]
        assert "Disk service unavailable" in result["message"]


class TestSystemToolsEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_different_regions_and_workspaces(self, mock_http_client, mock_token_manager):
        """Test all functions with different regions and workspaces."""
        from tools.system_tools import system_info, system_users_list, system_packages_list, system_disk_info

        # Mock successful responses
        mock_http_client.get.return_value = {"test": "data"}

        # Test with different regions
        functions_to_test = [system_info, system_users_list, system_packages_list, system_disk_info]

        for func in functions_to_test:
            result = await func(
                server_id="eu-server-001",
                workspace="eu-workspace",
                region="eu1"
            )

            assert result["status"] == "success"
            assert result["server_id"] == "eu-server-001"
            assert result["workspace"] == "eu-workspace"
            assert result["region"] == "eu1"

    @pytest.mark.asyncio
    async def test_token_manager_exceptions(self, mock_http_client, mock_token_manager):
        """Test functions when token manager raises exceptions."""
        from tools.system_tools import system_info

        mock_token_manager.get_token.side_effect = Exception("Token manager error")

        result = await system_info(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get system info" in result["message"]
        assert "Token manager error" in result["message"]

    @pytest.mark.asyncio
    async def test_server_not_found_errors(self, mock_http_client, mock_token_manager):
        """Test functions with server not found errors."""
        from tools.system_tools import system_users_list

        mock_http_client.get.side_effect = Exception("HTTP 404 Server Not Found")

        result = await system_users_list(
            server_id="nonexistent-server",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get users list" in result["message"]
        assert "404" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])