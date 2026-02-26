"""
Unit tests for metrics_tools module.

Tests metrics and monitoring functionality including CPU, memory, disk,
network traffic monitoring and server performance analytics.
"""
import pytest
from unittest.mock import AsyncMock, patch, call
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
    with patch('utils.common.token_manager') as mock_manager:
        mock_manager.get_token.return_value = "test-token"
        yield mock_manager


class TestGetCpuUsage:
    """Test get_cpu_usage function."""

    @pytest.mark.asyncio
    async def test_cpu_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful CPU usage retrieval."""
        from tools.metrics_tools import get_cpu_usage

        # Mock successful response with results format
        mock_http_client.get.return_value = {
            "results": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "usage": 25.5
                }
            ]
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
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify parsed data structure
        data = result["data"]
        assert data["server_id"] == "server-001"
        assert data["metric_type"] == "cpu_usage"
        assert "statistics" in data
        assert data["raw_data_available"] is True

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
        """Test CPU usage retrieval without date parameters (defaults to 24h)."""
        from tools.metrics_tools import get_cpu_usage

        mock_http_client.get.return_value = {"results": []}

        result = await get_cpu_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"

        # Verify start parameter was auto-generated (default 24h)
        call_args = mock_http_client.get.call_args
        params = call_args[1]["params"]
        assert params["server"] == "server-001"
        assert "start" in params  # Default start date is auto-generated

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
        assert "Failed in get_cpu_usage" in result["message"]


class TestGetMemoryUsage:
    """Test get_memory_usage function."""

    @pytest.mark.asyncio
    async def test_memory_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful memory usage retrieval."""
        from tools.metrics_tools import get_memory_usage

        # Mock successful response with results format
        mock_http_client.get.return_value = {
            "results": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "usage": 65.2
                }
            ]
        }

        result = await get_memory_usage(
            server_id="server-001",
            workspace="testworkspace",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-01T01:00:00Z",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify parsed data
        data = result["data"]
        assert data["server_id"] == "server-001"
        assert data["metric_type"] == "memory_usage"
        assert "statistics" in data

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
        assert "Failed in get_memory_usage" in result["message"]


class TestGetDiskUsage:
    """Test get_disk_usage function."""

    @pytest.mark.asyncio
    async def test_disk_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful disk usage retrieval with device and partition."""
        from tools.metrics_tools import get_disk_usage

        # Mock successful response with results format
        mock_http_client.get.return_value = {
            "results": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "device": "/dev/sda1",
                    "usage": 42.8,
                    "total": 107374182400,
                    "used": 45964566528,
                    "free": 61409615872
                }
            ]
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
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify parsed data
        data = result["data"]
        assert data["server_id"] == "server-001"
        assert data["metric_type"] == "disk_usage"
        assert data["device"] == "/dev/sda1"
        assert data["partition"] == "/"
        assert "statistics" in data

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
    async def test_disk_usage_auto_device_detection(self, mock_http_client, mock_token_manager):
        """Test disk usage auto-detects device when not provided."""
        from tools.metrics_tools import get_disk_usage

        # First call: device discovery; Second call: actual disk metrics
        mock_http_client.get.side_effect = [
            {"devices": ["/dev/sda1", "/dev/sdb1"]},  # Device discovery
            {"results": [{"usage": 50.0, "total": 100, "used": 50, "free": 50}]}  # Disk metrics
        ]

        result = await get_disk_usage(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"

        # Verify two calls: device discovery + actual metrics
        assert mock_http_client.get.call_count == 2

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

        # Mock successful response with results format
        mock_http_client.get.return_value = {
            "results": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "interface": "eth0",
                    "peak_input_bps": 1000000,
                    "peak_output_bps": 500000,
                    "avg_input_bps": 800000,
                    "avg_output_bps": 400000,
                    "peak_input_pps": 1000,
                    "peak_output_pps": 500
                }
            ]
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
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Verify parsed data
        data = result["data"]
        assert data["server_id"] == "server-001"
        assert data["metric_type"] == "network_traffic"
        assert data["interface"] == "eth0"
        assert "statistics" in data

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

        mock_http_client.get.return_value = {"results": []}

        result = await get_network_traffic(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "success"

        # Verify interface parameter was not included but start was auto-generated
        call_args = mock_http_client.get.call_args
        params = call_args[1]["params"]
        assert params["server"] == "server-001"
        assert "interface" not in params
        assert "start" in params  # Default start date is auto-generated

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


class TestGetTopServers:
    """Test get_top_servers function."""

    @pytest.mark.asyncio
    async def test_top_servers_single_metric(self, mock_http_client, mock_token_manager):
        """Test top servers with single metric type (cpu)."""
        from tools.metrics_tools import get_top_servers

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

        result = await get_top_servers(
            workspace="testworkspace",
            metric_types="cpu",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["metric_type"] == "cpu_top"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"
        assert "data" in result

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region="ap1",
            workspace="testworkspace",
            endpoint="/api/metrics/realtime/cpu/top/",
            token="test-token"
        )

    @pytest.mark.asyncio
    async def test_top_servers_multiple_metrics(self, mock_http_client, mock_token_manager):
        """Test top servers with multiple metric types."""
        from tools.metrics_tools import get_top_servers

        # Mock responses for multiple metrics (asyncio.gather returns in order)
        mock_http_client.get.return_value = {"data": [{"server_id": "s1"}]}

        result = await get_top_servers(
            workspace="testworkspace",
            metric_types="cpu,memory",
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["region"] == "ap1"
        assert result["workspace"] == "testworkspace"

        # Multiple metrics - returns combined data
        assert "data" in result

    @pytest.mark.asyncio
    async def test_top_servers_invalid_metric(self, mock_http_client, mock_token_manager):
        """Test top servers with invalid metric type."""
        from tools.metrics_tools import get_top_servers

        result = await get_top_servers(
            workspace="testworkspace",
            metric_types="invalid_metric",
            region="ap1"
        )

        assert result["status"] == "error"
        assert "Invalid metric types" in result["message"]
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_top_servers_no_token(self, mock_http_client, mock_token_manager):
        """Test top servers when no token is available."""
        from tools.metrics_tools import get_top_servers

        mock_token_manager.get_token.return_value = None

        result = await get_top_servers(
            workspace="testworkspace",
            metric_types="cpu"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]

    @pytest.mark.asyncio
    async def test_top_servers_all_metrics(self, mock_http_client, mock_token_manager):
        """Test top servers with empty metric_types (all metrics)."""
        from tools.metrics_tools import get_top_servers

        # Mock responses for all 4 metrics
        mock_http_client.get.return_value = {"data": []}

        result = await get_top_servers(
            workspace="testworkspace",
            metric_types="",
            region="ap1"
        )

        assert result["status"] == "success"

        # All 4 metrics should be queried
        assert mock_http_client.get.call_count == 4


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

        # The function calls http_client.get directly for partitions, interfaces,
        # and then for cpu, memory, disk, traffic metrics
        # Calls: partitions, interfaces, cpu, memory, disk, traffic
        mock_http_client.get.return_value = {
            "results": [
                {"timestamp": "2024-01-01T00:00:00Z", "usage": 45.0}
            ]
        }

        result = await get_server_metrics_summary(
            server_id="server-001",
            workspace="testworkspace",
            hours=24,
            region="ap1"
        )

        assert result["status"] == "success"
        assert result["data"]["server_id"] == "server-001"
        assert result["data"]["time_range"]["hours"] == 24

        # Verify all metric sections are present
        metrics = result["data"]["metrics"]
        assert "cpu" in metrics
        assert "memory" in metrics
        assert "disk" in metrics
        assert "network" in metrics

    @pytest.mark.asyncio
    async def test_metrics_summary_custom_hours(self, mock_http_client, mock_token_manager):
        """Test metrics summary with custom hours parameter."""
        from tools.metrics_tools import get_server_metrics_summary

        mock_http_client.get.return_value = {
            "results": [{"usage": 30.0}]
        }

        result = await get_server_metrics_summary(
            server_id="server-001",
            workspace="testworkspace",
            hours=6,
            region="us1"
        )

        assert result["status"] == "success"
        assert result["data"]["time_range"]["hours"] == 6

    @pytest.mark.asyncio
    async def test_metrics_summary_max_hours_capped(self, mock_http_client, mock_token_manager):
        """Test that hours parameter is capped at 168."""
        from tools.metrics_tools import get_server_metrics_summary

        mock_http_client.get.return_value = {"results": []}

        result = await get_server_metrics_summary(
            server_id="server-001",
            workspace="testworkspace",
            hours=500  # Exceeds max
        )

        assert result["status"] == "success"
        assert result["data"]["time_range"]["hours"] == 168  # Capped

    @pytest.mark.asyncio
    async def test_metrics_summary_no_token(self, mock_http_client, mock_token_manager):
        """Test metrics summary when no token is available."""
        from tools.metrics_tools import get_server_metrics_summary

        mock_token_manager.get_token.return_value = None

        result = await get_server_metrics_summary(
            server_id="server-001",
            workspace="testworkspace"
        )

        assert result["status"] == "error"
        assert "No token found" in result["message"]

    @pytest.mark.asyncio
    async def test_metrics_summary_http_error(self, mock_http_client, mock_token_manager):
        """Test metrics summary with HTTP errors - returns success with unavailable metrics."""
        from tools.metrics_tools import get_server_metrics_summary

        mock_http_client.get.side_effect = Exception("Service unavailable")

        result = await get_server_metrics_summary(
            server_id="server-001",
            workspace="testworkspace"
        )

        # get_server_metrics_summary uses asyncio.gather with return_exceptions=True
        # so it returns success but individual metrics show as unavailable
        assert result["status"] == "success"
        metrics = result["data"]["metrics"]
        # All metrics should show errors since http_client.get always fails
        for metric_key in ["cpu", "memory", "disk", "network"]:
            assert metrics[metric_key]["available"] is False


class TestParseCpuMetrics:
    """Test parse_cpu_metrics helper function."""

    def test_parse_cpu_metrics_with_data(self):
        """Test CPU metrics parsing with valid data."""
        from tools.metrics_tools import parse_cpu_metrics

        results = [
            {"timestamp": "2024-01-01T00:00:00Z", "usage": 25.0},
            {"timestamp": "2024-01-01T01:00:00Z", "usage": 50.0},
            {"timestamp": "2024-01-01T02:00:00Z", "usage": 75.0}
        ]

        parsed = parse_cpu_metrics(results)

        assert parsed["available"] is True
        assert parsed["raw_values"]["current"] == 75.0
        assert parsed["raw_values"]["min"] == 25.0
        assert parsed["raw_values"]["max"] == 75.0
        assert parsed["data_points"] == 3

    def test_parse_cpu_metrics_empty(self):
        """Test CPU metrics parsing with empty data."""
        from tools.metrics_tools import parse_cpu_metrics

        parsed = parse_cpu_metrics([])

        assert parsed["available"] is False

    def test_parse_cpu_metrics_none(self):
        """Test CPU metrics parsing with None."""
        from tools.metrics_tools import parse_cpu_metrics

        parsed = parse_cpu_metrics(None)

        assert parsed["available"] is False


class TestParseMemoryMetrics:
    """Test parse_memory_metrics helper function."""

    def test_parse_memory_metrics_with_data(self):
        """Test memory metrics parsing with valid data."""
        from tools.metrics_tools import parse_memory_metrics

        results = [
            {"timestamp": "2024-01-01T00:00:00Z", "usage": 40.0},
            {"timestamp": "2024-01-01T01:00:00Z", "usage": 60.0}
        ]

        parsed = parse_memory_metrics(results)

        assert parsed["available"] is True
        assert parsed["raw_values"]["current"] == 60.0
        assert parsed["data_points"] == 2

    def test_parse_memory_metrics_empty(self):
        """Test memory metrics parsing with empty data."""
        from tools.metrics_tools import parse_memory_metrics

        parsed = parse_memory_metrics([])

        assert parsed["available"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
