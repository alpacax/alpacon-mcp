"""
Unit tests for metrics_tools module.

Tests metrics and monitoring functionality including CPU, memory, disk,
network traffic monitoring and server performance analytics.
"""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta


@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    with patch('tools.metrics_tools.http_client') as mock_client:
        # Mock the async methods properly
        mock_client.get = AsyncMock()
        yield mock_client


@pytest.fixture
def mock_token_manager():
    """Mock token manager for testing."""
    with patch('tools.metrics_tools.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


class TestGetCpuUsage:
    """Test get_cpu_usage function."""

    @pytest.mark.asyncio
    async def test_cpu_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful CPU usage retrieval."""
        from tools.metrics_tools import get_cpu_usage

        # Mock successful response
        mock_http_client.get.return_value = {
            "data": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "cpu_percent": 25.5,
                    "load_average": [1.2, 1.1, 1.0]
                }
            ],
            "server": "server-001",
            "metric": "cpu_usage"
        }

        result = await get_cpu_usage(
            server_id="server-001",
            workspace="testworkspace",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-01T01:00:00Z",
            region="ap1"
        )

        # Verify response structure
        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["metric_type"] == "cpu_usage"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/realtime/cpu/",
            token="test-token",
            params={
                "server": "server-001",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T01:00:00Z"
            }
        )

    @pytest.mark.asyncio
    async def test_cpu_usage_without_dates(self, mock_http_client, mock_token_manager):
        """Test CPU usage retrieval without date parameters."""
        from tools.metrics_tools import get_cpu_usage

        mock_http_client.get.return_value = {"data": []}

        result = await get_cpu_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"

        # Verify only server parameter was included
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"] == {"server": "server-001"}

    @pytest.mark.asyncio
    async def test_cpu_usage_no_token(self, mock_http_client, mock_token_manager):
        """Test CPU usage when no token is available."""
        from tools.metrics_tools import get_cpu_usage

        mock_token_manager.get_token.return_value = None

        result = await get_cpu_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_cpu_usage_http_error(self, mock_http_client, mock_token_manager):
        """Test CPU usage with HTTP error."""
        from tools.metrics_tools import get_cpu_usage

        mock_http_client.get.side_effect = Exception("HTTP 500 Internal Server Error")

        result = await get_cpu_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get CPU usage" in result["message"]


class TestGetMemoryUsage:
    """Test get_memory_usage function."""

    @pytest.mark.asyncio
    async def test_memory_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful memory usage retrieval."""
        from tools.metrics_tools import get_memory_usage

        # Mock successful response
        mock_http_client.get.return_value = {
            "data": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "memory_percent": 65.2,
                    "memory_total": 8589934592,
                    "memory_used": 5599194112,
                    "memory_free": 2990740480
                }
            ],
            "server": "server-001",
            "metric": "memory_usage"
        }

        result = await get_memory_usage(
            server_id="server-001",
            workspace="testworkspace",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-01T01:00:00Z",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["metric_type"] == "memory_usage"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/realtime/memory/",
            token="test-token",
            params={
                "server": "server-001",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T01:00:00Z"
            }
        )

    @pytest.mark.asyncio
    async def test_memory_usage_no_token(self, mock_http_client, mock_token_manager):
        """Test memory usage when no token is available."""
        from tools.metrics_tools import get_memory_usage

        mock_token_manager.get_token.return_value = None

        result = await get_memory_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]

    @pytest.mark.asyncio
    async def test_memory_usage_http_error(self, mock_http_client, mock_token_manager):
        """Test memory usage with HTTP error."""
        from tools.metrics_tools import get_memory_usage

        mock_http_client.get.side_effect = Exception("Connection timeout")

        result = await get_memory_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "Failed to get memory usage" in result["message"]


class TestGetDiskUsage:
    """Test get_disk_usage function."""

    @pytest.mark.asyncio
    async def test_disk_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful disk usage retrieval."""
        from tools.metrics_tools import get_disk_usage

        # Mock successful response
        mock_http_client.get.return_value = {
            "data": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "device": "/dev/sda1",
                    "partition": "/",
                    "disk_percent": 42.8,
                    "disk_total": 107374182400,
                    "disk_used": 45964566528,
                    "disk_free": 61409615872
                }
            ],
            "server": "server-001",
            "metric": "disk_usage"
        }

        result = await get_disk_usage(
            server_id="server-001",
            workspace="testworkspace",
            device="/dev/sda1",
            partition="/",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-01T01:00:00Z",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["metric_type"] == "disk_usage"
        assert result["device"] == "/dev/sda1"
        assert result["partition"] == "/"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/realtime/disk-usage/",
            token="test-token",
            params={
                "server": "server-001",
                "device": "/dev/sda1",
                "partition": "/",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T01:00:00Z"
            }
        )

    @pytest.mark.asyncio
    async def test_disk_usage_minimal_params(self, mock_http_client, mock_token_manager):
        """Test disk usage with minimal parameters."""
        from tools.metrics_tools import get_disk_usage

        mock_http_client.get.return_value = {"data": []}

        result = await get_disk_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["device"] is None
        assert result["partition"] is None

        # Verify only server parameter was included
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"] == {"server": "server-001"}

    @pytest.mark.asyncio
    async def test_disk_usage_no_token(self, mock_http_client, mock_token_manager):
        """Test disk usage when no token is available."""
        from tools.metrics_tools import get_disk_usage

        mock_token_manager.get_token.return_value = None

        result = await get_disk_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetNetworkTraffic:
    """Test get_network_traffic function."""

    @pytest.mark.asyncio
    async def test_network_traffic_success(self, mock_http_client, mock_token_manager):
        """Test successful network traffic retrieval."""
        from tools.metrics_tools import get_network_traffic

        # Mock successful response
        mock_http_client.get.return_value = {
            "data": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "interface": "eth0",
                    "bytes_sent": 1073741824,
                    "bytes_recv": 2147483648,
                    "packets_sent": 1000000,
                    "packets_recv": 1500000
                }
            ],
            "server": "server-001",
            "metric": "network_traffic"
        }

        result = await get_network_traffic(
            server_id="server-001",
            workspace="testworkspace",
            interface="eth0",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-01T01:00:00Z",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["metric_type"] == "network_traffic"
        assert result["interface"] == "eth0"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/realtime/traffic/",
            token="test-token",
            params={
                "server": "server-001",
                "interface": "eth0",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-01T01:00:00Z"
            }
        )

    @pytest.mark.asyncio
    async def test_network_traffic_without_interface(self, mock_http_client, mock_token_manager):
        """Test network traffic without interface parameter."""
        from tools.metrics_tools import get_network_traffic

        mock_http_client.get.return_value = {"data": []}

        result = await get_network_traffic(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"
        assert result["interface"] is None

        # Verify interface parameter was not included
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"] == {"server": "server-001"}

    @pytest.mark.asyncio
    async def test_network_traffic_no_token(self, mock_http_client, mock_token_manager):
        """Test network traffic when no token is available."""
        from tools.metrics_tools import get_network_traffic

        mock_token_manager.get_token.return_value = None

        result = await get_network_traffic(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetCpuTopServers:
    """Test get_cpu_top_servers function."""

    @pytest.mark.asyncio
    async def test_cpu_top_servers_success(self, mock_http_client, mock_token_manager):
        """Test successful top CPU servers retrieval."""
        from tools.metrics_tools import get_cpu_top_servers

        # Mock successful response
        mock_http_client.get.return_value = {
            "data": [
                {
                    "server_id": "server-001",
                    "server_name": "web-server-1",
                    "cpu_percent": 89.5,
                    "timestamp": "2024-01-01T00:00:00Z"
                },
                {
                    "server_id": "server-002",
                    "server_name": "api-server-1",
                    "cpu_percent": 72.3,
                    "timestamp": "2024-01-01T00:00:00Z"
                }
            ],
            "total_servers": 15,
            "time_range": "24h"
        }

        result = await get_cpu_top_servers(
            workspace="testworkspace",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["metric_type"] == "cpu_top"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert len(result["data"]["data"]) == 2

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/realtime/cpu/top/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_cpu_top_servers_no_token(self, mock_http_client, mock_token_manager):
        """Test top CPU servers when no token is available."""
        from tools.metrics_tools import get_cpu_top_servers

        mock_token_manager.get_token.return_value = None

        result = await get_cpu_top_servers(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]

    @pytest.mark.asyncio
    async def test_cpu_top_servers_http_error(self, mock_http_client, mock_token_manager):
        """Test top CPU servers with HTTP error."""
        from tools.metrics_tools import get_cpu_top_servers

        mock_http_client.get.side_effect = Exception("Service unavailable")

        result = await get_cpu_top_servers(workspace="testworkspace")

        assert result["status"] == "error"
        assert "Failed to get top CPU servers" in result["message"]


class TestGetAlertRules:
    """Test get_alert_rules function."""

    @pytest.mark.asyncio
    async def test_alert_rules_success(self, mock_http_client, mock_token_manager):
        """Test successful alert rules retrieval."""
        from tools.metrics_tools import get_alert_rules

        # Mock successful response
        mock_http_client.get.return_value = {
            "count": 3,
            "results": [
                {
                    "id": "rule-001",
                    "name": "High CPU Alert",
                    "metric": "cpu_percent",
                    "threshold": 80.0,
                    "comparison": "gt",
                    "server": "server-001",
                    "enabled": True
                },
                {
                    "id": "rule-002",
                    "name": "Low Disk Space",
                    "metric": "disk_percent",
                    "threshold": 90.0,
                    "comparison": "gt",
                    "server": "server-001",
                    "enabled": True
                }
            ]
        }

        result = await get_alert_rules(
            workspace="testworkspace",
            server_id="server-001",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["server_id"] == "server-001"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert result["data"]["count"] == 3

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/alert-rules/",
            token="test-token",
            params={"server": "server-001"}
        )

    @pytest.mark.asyncio
    async def test_alert_rules_all_servers(self, mock_http_client, mock_token_manager):
        """Test alert rules for all servers."""
        from tools.metrics_tools import get_alert_rules

        mock_http_client.get.return_value = {"count": 10, "results": []}

        result = await get_alert_rules(workspace="testworkspace")

        assert result["status"] == "success"
        assert result["server_id"] is None

        # Verify no server filter was applied
        call_args = mock_http_client.get.call_args
        assert call_args[1]["params"] == {}

    @pytest.mark.asyncio
    async def test_alert_rules_no_token(self, mock_http_client, mock_token_manager):
        """Test alert rules when no token is available."""
        from tools.metrics_tools import get_alert_rules

        mock_token_manager.get_token.return_value = None

        result = await get_alert_rules(workspace="testworkspace")

        assert result["status"] == "error"
        assert "No token found" in result["message"]


class TestGetServerMetricsSummary:
    """Test get_server_metrics_summary function."""

    @pytest.mark.asyncio
    async def test_metrics_summary_success(self, mock_http_client, mock_token_manager):
        """Test successful metrics summary retrieval."""
        from tools.metrics_tools import get_server_metrics_summary

        # Mock individual metric responses
        cpu_data = {"cpu_percent": 45.2, "load_average": [1.5, 1.3, 1.1]}
        memory_data = {"memory_percent": 68.5, "memory_used": 5599194112}
        disk_data = {"disk_percent": 42.8, "disk_used": 45964566528}
        network_data = {"bytes_sent": 1073741824, "bytes_recv": 2147483648}

        with patch('tools.metrics_tools.get_cpu_usage') as mock_cpu, \
             patch('tools.metrics_tools.get_memory_usage') as mock_memory, \
             patch('tools.metrics_tools.get_disk_usage') as mock_disk, \
             patch('tools.metrics_tools.get_network_traffic') as mock_network:

            # Mock successful responses for all metrics
            mock_cpu.return_value = {"status": "success", "data": cpu_data}
            mock_memory.return_value = {"status": "success", "data": memory_data}
            mock_disk.return_value = {"status": "success", "data": disk_data}
            mock_network.return_value = {"status": "success", "data": network_data}

            result = await get_server_metrics_summary(
                server_id="server-001",
                workspace="testworkspace",
                hours=24,
                region="ap1"
            )

            assert result["status"] == "success"
            assert result["data"]["server_id"] == "server-001"
            assert result["data"]["time_range"]["hours"] == 24
            assert result["data"]["region"] == "ap1"
            assert result["data"]["workspace"] == "testworkspace"

            # Verify all metrics are included
            metrics = result["data"]["metrics"]
            assert "cpu" in metrics
            assert "memory" in metrics
            assert "disk" in metrics
            assert "network" in metrics
            assert metrics["cpu"] == cpu_data
            assert metrics["memory"] == memory_data
            assert metrics["disk"] == disk_data
            assert metrics["network"] == network_data

            # Verify all individual functions were called
            mock_cpu.assert_called_once()
            mock_memory.assert_called_once()
            mock_disk.assert_called_once()
            mock_network.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_summary_partial_failure(self, mock_http_client, mock_token_manager):
        """Test metrics summary with some metrics failing."""
        from tools.metrics_tools import get_server_metrics_summary

        with patch('tools.metrics_tools.get_cpu_usage') as mock_cpu, \
             patch('tools.metrics_tools.get_memory_usage') as mock_memory, \
             patch('tools.metrics_tools.get_disk_usage') as mock_disk, \
             patch('tools.metrics_tools.get_network_traffic') as mock_network:

            # Mock mixed success/failure responses
            mock_cpu.return_value = {"status": "success", "data": {"cpu_percent": 45.2}}
            mock_memory.return_value = {"status": "error", "message": "Connection timeout"}
            mock_disk.return_value = {"status": "success", "data": {"disk_percent": 42.8}}
            mock_network.side_effect = Exception("Network error")

            result = await get_server_metrics_summary(
                server_id="server-001",
                workspace="testworkspace",
                hours=12
            )

            assert result["status"] == "success"
            assert result["data"]["time_range"]["hours"] == 12

            metrics = result["data"]["metrics"]

            # Successful metrics should have data
            assert metrics["cpu"] == {"cpu_percent": 45.2}
            assert metrics["disk"] == {"disk_percent": 42.8}

            # Failed metrics should have error information
            assert "error" in metrics["memory"]
            assert "Connection timeout" in metrics["memory"]["error"]
            assert "error" in metrics["network"]
            assert "Network error" in metrics["network"]["error"]

    @pytest.mark.asyncio
    async def test_metrics_summary_exception(self, mock_http_client, mock_token_manager):
        """Test metrics summary with general exception."""
        from tools.metrics_tools import get_server_metrics_summary

        # Mock datetime.datetime.now to raise an exception
        # Since datetime is imported locally in the function, we patch the module-level import
        with patch('datetime.datetime') as mock_datetime_class:
            mock_datetime_class.now.side_effect = Exception("Time service unavailable")

            result = await get_server_metrics_summary(
                server_id="server-001",
                workspace="testworkspace"
            )

            assert result["status"] == "error"
            assert "Failed to get server metrics summary" in result["message"]
            assert "Time service unavailable" in result["message"]

    @pytest.mark.asyncio
    async def test_metrics_summary_custom_hours(self, mock_http_client, mock_token_manager):
        """Test metrics summary with custom hours parameter."""
        from tools.metrics_tools import get_server_metrics_summary

        with patch('tools.metrics_tools.get_cpu_usage') as mock_cpu, \
             patch('tools.metrics_tools.get_memory_usage') as mock_memory, \
             patch('tools.metrics_tools.get_disk_usage') as mock_disk, \
             patch('tools.metrics_tools.get_network_traffic') as mock_network:

            # Mock successful responses
            mock_cpu.return_value = {"status": "success", "data": {}}
            mock_memory.return_value = {"status": "success", "data": {}}
            mock_disk.return_value = {"status": "success", "data": {}}
            mock_network.return_value = {"status": "success", "data": {}}

            result = await get_server_metrics_summary(
                server_id="server-001",
                workspace="testworkspace",
                hours=6,
                region="us1"
            )

            assert result["status"] == "success"
            assert result["data"]["time_range"]["hours"] == 6
            assert result["data"]["region"] == "us1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])