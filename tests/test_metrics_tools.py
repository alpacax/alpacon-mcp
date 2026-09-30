"""
Unit tests for metrics_tools module.

Tests metrics and monitoring functionality including CPU, memory, disk,
network traffic monitoring and server performance analytics.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import patch

import pytest

from server import mcp
from tests.conftest import HTTP_ERROR_ENVELOPE, http_client_fixture
from tools.metrics_tools import (
    _MAX_INTERFACE_PAGES,
    _oldest_first,
    get_alert_rules,
    get_cpu_usage,
    get_disk_io,
    get_disk_usage,
    get_memory_usage,
    get_network_traffic,
    get_server_metrics_summary,
    get_top_servers,
    list_latest_metrics,
    parse_cpu_metrics,
    parse_disk_metrics,
    parse_memory_metrics,
    parse_network_metrics,
)

mock_http_client = http_client_fixture('tools.metrics_tools')

SERVER_ID = '550e8400-e29b-41d4-a716-446655440001'
INTERFACE_ID = '7c9e6679-7425-40de-944b-e07fc1f90ae7'
ROOT_PARTITION_ID = '16fd2706-8baf-433b-82eb-8c7fada847da'
BOOT_PARTITION_ID = '0b8a1f4e-1111-4c1e-9d7a-000000000001'
LOOPBACK_INTERFACE_ID = 'a1b2c3d4-0000-4000-8000-000000000001'
ETHERNET_INTERFACE_ID = 'a1b2c3d4-0000-4000-8000-000000000002'
SECOND_SERVER_ID = '550e8400-e29b-41d4-a716-446655440002'
GROUP_ID = '550e8400-e29b-41d4-a716-446655440099'
START = '2024-01-01T00:00:00Z'
END = '2024-01-01T01:00:00Z'


class TestGetCpuUsage:
    """Test get_cpu_usage function."""

    @pytest.mark.asyncio
    async def test_cpu_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful CPU usage retrieval."""
        # Mock successful response with results format
        mock_http_client.get.return_value = {
            'results': [{'timestamp': '2024-01-01T00:00:00Z', 'usage': 25.5}]
        }

        result = await get_cpu_usage(
            server_id=SERVER_ID,
            workspace='testworkspace',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-01T01:00:00Z',
            region='ap1',
        )

        # Verify response structure
        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result

        # Verify parsed data structure
        data = result['data']
        assert data['server_id'] == SERVER_ID
        assert data['metric_type'] == 'cpu_usage'
        assert 'statistics' in data
        assert data['raw_data_available'] is True

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/cpu/',
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': '2024-01-01T00:00:00Z',
                'end': '2024-01-01T01:00:00Z',
            },
        )

    @pytest.mark.asyncio
    async def test_cpu_usage_without_dates(self, mock_http_client, mock_token_manager):
        """Test CPU usage retrieval without date parameters (defaults to 12h)."""
        mock_http_client.get.return_value = {'results': []}
        frozen = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

        with patch('utils.common.datetime') as mock_datetime:
            mock_datetime.now.return_value = frozen
            result = await get_cpu_usage(
                server_id=SERVER_ID,
                workspace='testworkspace',
            )

        assert result['status'] == 'success'

        expected_start = (frozen - timedelta(hours=12)).isoformat()
        assert expected_start == '2024-06-01T00:00:00+00:00'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/cpu/',
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': expected_start,
            },
        )

    @pytest.mark.asyncio
    async def test_cpu_usage_http_error_envelope(
        self, mock_http_client, mock_token_manager
    ):
        """Test CPU usage returns error when http_client returns an error envelope."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_cpu_usage(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        assert result['message'] == 'Not found'

    @pytest.mark.asyncio
    async def test_cpu_usage_no_token(self, mock_http_client, mock_token_manager):
        """Test CPU usage when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_cpu_usage(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']
        mock_http_client.get.assert_not_called()


class TestGetMemoryUsage:
    @pytest.mark.asyncio
    async def test_memory_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful memory usage retrieval."""
        # Mock successful response with results format
        mock_http_client.get.return_value = {
            'results': [{'timestamp': '2024-01-01T00:00:00Z', 'usage': 65.2}]
        }

        result = await get_memory_usage(
            server_id=SERVER_ID,
            workspace='testworkspace',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-01T01:00:00Z',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'

        # Verify parsed data
        data = result['data']
        assert data['server_id'] == SERVER_ID
        assert data['metric_type'] == 'memory_usage'
        assert 'statistics' in data

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/memory/',
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': '2024-01-01T00:00:00Z',
                'end': '2024-01-01T01:00:00Z',
            },
        )

    @pytest.mark.asyncio
    async def test_memory_usage_no_token(self, mock_http_client, mock_token_manager):
        """Test memory usage when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_memory_usage(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestGetDiskUsage:
    @pytest.mark.asyncio
    async def test_disk_usage_success(self, mock_http_client, mock_token_manager):
        """Test successful disk usage retrieval with device and partition."""
        # Mock successful response with results format
        mock_http_client.get.return_value = {
            'results': [
                {
                    'timestamp': '2024-01-01T00:00:00Z',
                    'device': '/dev/sda1',
                    'usage': 42.8,
                    'total': 107374182400,
                    'used': 45964566528,
                    'free': 61409615872,
                }
            ]
        }

        result = await get_disk_usage(
            server_id=SERVER_ID,
            workspace='testworkspace',
            device='/dev/sda1',
            partition='/',
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-01T01:00:00Z',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'

        # Verify parsed data
        data = result['data']
        assert data['server_id'] == SERVER_ID
        assert data['metric_type'] == 'disk_usage'
        assert data['device'] == '/dev/sda1'
        assert data['partition'] == '/'
        assert 'statistics' in data

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/disk-usage/',
            token='test-token',
            params={
                'server': SERVER_ID,
                'device': '/dev/sda1',
                'partition': '/',
                'start': '2024-01-01T00:00:00Z',
                'end': '2024-01-01T01:00:00Z',
            },
        )

    @pytest.mark.asyncio
    async def test_disk_usage_auto_device_detection(
        self, mock_http_client, mock_token_manager
    ):
        """Test disk usage auto-detects device when not provided."""
        # First call: device discovery; Second call: actual disk metrics
        mock_http_client.get.side_effect = [
            {'devices': ['/dev/sda1', '/dev/sdb1']},  # Device discovery
            {
                'results': [{'usage': 50.0, 'total': 100, 'used': 50, 'free': 50}]
            },  # Disk metrics
        ]

        result = await get_disk_usage(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'success'

        # Verify two calls: device discovery + actual metrics
        assert mock_http_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_disk_usage_device_discovery_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """Device-discovery 4xx/5xx must surface as an error, not 'no devices'."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_disk_usage(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        assert 'No disk devices found' not in result['message']
        # The metrics call must be skipped once discovery fails.
        assert mock_http_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_disk_usage_no_token(self, mock_http_client, mock_token_manager):
        """Test disk usage when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_disk_usage(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestGetNetworkTraffic:
    """Test get_network_traffic function."""

    @pytest.mark.asyncio
    async def test_network_traffic_success(self, mock_http_client, mock_token_manager):
        """Test successful network traffic retrieval."""
        # Mock successful response with results format
        mock_http_client.get.return_value = {
            'results': [
                {
                    'timestamp': '2024-01-01T00:00:00Z',
                    'interface': INTERFACE_ID,
                    'peak_input_bps': 1000000,
                    'peak_output_bps': 500000,
                    'avg_input_bps': 800000,
                    'avg_output_bps': 400000,
                    'peak_input_pps': 1000,
                    'peak_output_pps': 500,
                }
            ]
        }

        result = await get_network_traffic(
            server_id=SERVER_ID,
            workspace='testworkspace',
            interface=INTERFACE_ID,
            start_date='2024-01-01T00:00:00Z',
            end_date='2024-01-01T01:00:00Z',
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'

        # Verify parsed data
        data = result['data']
        assert data['server_id'] == SERVER_ID
        assert data['metric_type'] == 'network_traffic'
        assert data['interface'] == INTERFACE_ID
        assert 'statistics' in data

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/traffic/',
            token='test-token',
            params={
                'server': SERVER_ID,
                'interface': INTERFACE_ID,
                'start': '2024-01-01T00:00:00Z',
                'end': '2024-01-01T01:00:00Z',
            },
        )

    @pytest.mark.asyncio
    async def test_network_traffic_schema_requires_an_interface(self):
        tools = {t.name: t for t in await mcp.list_tools()}

        schema = tools['get_network_traffic'].input_schema

        assert 'interface' in schema['required']

    @pytest.mark.asyncio
    async def test_network_traffic_no_token(self, mock_http_client, mock_token_manager):
        """Test network traffic when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_network_traffic(
            server_id=SERVER_ID,
            workspace='testworkspace',
            interface=INTERFACE_ID,
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestGetDiskIo:
    """Test get_disk_io function."""

    @pytest.mark.asyncio
    async def test_disk_io_http_error_envelope(
        self, mock_http_client, mock_token_manager
    ):
        """Test disk I/O returns error when http_client returns an error envelope."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_disk_io(server_id=SERVER_ID, workspace='testworkspace')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        assert result['message'] == 'Not found'


class TestGetTopServers:
    """Test get_top_servers function."""

    @pytest.mark.asyncio
    async def test_top_servers_single_metric(
        self, mock_http_client, mock_token_manager
    ):
        """Test top servers with single metric type (cpu)."""
        # Mock successful response
        mock_http_client.get.return_value = {
            'data': [
                {
                    'server_id': SERVER_ID,
                    'server_name': 'web-server-1',
                    'cpu_percent': 89.5,
                    'timestamp': '2024-01-01T00:00:00Z',
                },
                {
                    'server_id': SECOND_SERVER_ID,
                    'server_name': 'api-server-1',
                    'cpu_percent': 72.3,
                    'timestamp': '2024-01-01T00:00:00Z',
                },
            ],
            'total_servers': 15,
            'time_range': '24h',
        }

        result = await get_top_servers(
            workspace='testworkspace', metric_types='cpu', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['metric_type'] == 'cpu_top'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert 'data' in result

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/cpu/top/',
            token='test-token',
        )

    @pytest.mark.asyncio
    async def test_top_servers_multiple_metrics(
        self, mock_http_client, mock_token_manager
    ):
        """Test top servers with multiple metric types."""
        # Mock responses for multiple metrics (asyncio.gather returns in order)
        mock_http_client.get.return_value = {'data': [{'server_id': 's1'}]}

        result = await get_top_servers(
            workspace='testworkspace', metric_types='cpu,memory', region='ap1'
        )

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'

        # Multiple metrics - returns combined data
        assert 'data' in result

    @pytest.mark.asyncio
    async def test_top_servers_single_metric_http_error(
        self, mock_http_client, mock_token_manager
    ):
        """A single-metric error envelope must not be wrapped as success."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_top_servers(
            workspace='testworkspace', metric_types='cpu', region='ap1'
        )

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_top_servers_invalid_metric(
        self, mock_http_client, mock_token_manager
    ):
        """Test top servers with invalid metric type."""
        result = await get_top_servers(
            workspace='testworkspace', metric_types='invalid_metric', region='ap1'
        )

        assert result['status'] == 'error'
        assert 'Invalid metric types' in result['message']
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_top_servers_no_token(self, mock_http_client, mock_token_manager):
        """Test top servers when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_top_servers(workspace='testworkspace', metric_types='cpu')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']

    @pytest.mark.asyncio
    async def test_top_servers_all_metrics(self, mock_http_client, mock_token_manager):
        """Test top servers with empty metric_types (all metrics)."""
        # Mock responses for all 4 metrics
        mock_http_client.get.return_value = {'data': []}

        result = await get_top_servers(
            workspace='testworkspace', metric_types='', region='ap1'
        )

        assert result['status'] == 'success'

        # All 4 metrics should be queried
        assert mock_http_client.get.call_count == 4


class TestGetAlertRules:
    """Test get_alert_rules function."""

    @pytest.mark.asyncio
    async def test_alert_rules_success(self, mock_http_client, mock_token_manager):
        """Test successful alert rules retrieval."""
        # Mock successful response
        mock_http_client.get.return_value = {
            'count': 3,
            'results': [
                {
                    'id': 'rule-001',
                    'name': 'High CPU Alert',
                    'metric': 'cpu_percent',
                    'threshold': 80.0,
                    'comparison': 'gt',
                    'server': SERVER_ID,
                    'enabled': True,
                },
                {
                    'id': 'rule-002',
                    'name': 'Low Disk Space',
                    'metric': 'disk_percent',
                    'threshold': 90.0,
                    'comparison': 'gt',
                    'server': SERVER_ID,
                    'enabled': True,
                },
            ],
        }

        result = await get_alert_rules(
            workspace='testworkspace',
            server_id=SERVER_ID,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['server_id'] == SERVER_ID
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert result['data']['count'] == 3

        # Verify HTTP client was called correctly
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/alert-rules/',
            token='test-token',
            params={'server': SERVER_ID},
        )

    @pytest.mark.asyncio
    async def test_alert_rules_all_servers(self, mock_http_client, mock_token_manager):
        """Test alert rules for all servers."""
        mock_http_client.get.return_value = {'count': 10, 'results': []}

        result = await get_alert_rules(workspace='testworkspace')

        assert result['status'] == 'success'
        assert result['server_id'] is None

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/alert-rules/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_alert_rules_http_error_envelope(
        self, mock_http_client, mock_token_manager
    ):
        """Test alert rules returns error when http_client returns an error envelope."""
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_alert_rules(workspace='testworkspace')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.NOT_FOUND
        assert result['message'] == 'Not found'

    @pytest.mark.asyncio
    async def test_alert_rules_no_token(self, mock_http_client, mock_token_manager):
        """Test alert rules when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_alert_rules(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


class TestGetServerMetricsSummary:
    """Test get_server_metrics_summary function."""

    @pytest.mark.asyncio
    async def test_metrics_summary_success(self, mock_http_client, mock_token_manager):
        """Test successful metrics summary retrieval."""
        # The function calls http_client.get directly for partitions, interfaces,
        # and then for cpu, memory, disk, traffic metrics
        # Calls: partitions, interfaces, cpu, memory, disk, traffic
        mock_http_client.get.return_value = {
            'results': [{'timestamp': '2024-01-01T00:00:00Z', 'usage': 45.0}]
        }

        result = await get_server_metrics_summary(
            server_id=SERVER_ID,
            workspace='testworkspace',
            hours=12,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert result['data']['server_id'] == SERVER_ID
        assert result['data']['time_range']['hours'] == 12

        # Verify all metric sections are present
        metrics = result['data']['metrics']
        assert 'cpu' in metrics
        assert 'memory' in metrics
        assert 'disk' in metrics
        assert 'network' in metrics

    @pytest.mark.asyncio
    async def test_metrics_summary_custom_hours(
        self, mock_http_client, mock_token_manager
    ):
        """Test metrics summary with custom hours parameter."""
        mock_http_client.get.return_value = {'results': [{'usage': 30.0}]}

        result = await get_server_metrics_summary(
            server_id=SERVER_ID,
            workspace='testworkspace',
            hours=6,
            region='us1',
        )

        assert result['status'] == 'success'
        assert result['data']['time_range']['hours'] == 6

    @pytest.mark.asyncio
    async def test_metrics_summary_hours_default_to_the_realtime_window(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['data']['time_range']['hours'] == 12

    @pytest.mark.asyncio
    async def test_metrics_summary_hours_are_capped_at_the_realtime_window(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace', hours=500
        )

        time_range = result['data']['time_range']
        assert result['status'] == 'success'
        assert time_range['hours'] == 12
        span = datetime.fromisoformat(time_range['end']) - datetime.fromisoformat(
            time_range['start']
        )
        assert span == timedelta(hours=12)

    @pytest.mark.asyncio
    async def test_metrics_summary_no_token(self, mock_http_client, mock_token_manager):
        """Test metrics summary when no token is available."""
        mock_token_manager.get_token.return_value = None

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'error'
        assert 'No token found' in result['message']

    @pytest.mark.asyncio
    async def test_metrics_summary_reports_every_section_unavailable_on_http_errors(
        self, mock_http_client, mock_token_manager
    ):
        mock_http_client.get.return_value = HTTP_ERROR_ENVELOPE

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        metrics = result['data']['metrics']
        for metric_key in ['cpu', 'memory', 'disk', 'network']:
            assert metrics[metric_key]['available'] is False
        assert metrics['disk']['error'].startswith('Partition lookup failed: ')
        assert metrics['network']['error'] == 'Interface lookup failed: Not found'


class TestServerMetricsSummaryLookups:
    """The summary sends /api/proc/ record ids, never names."""

    PARTITIONS = [
        {
            'id': BOOT_PARTITION_ID,
            'name': '/dev/nvme0n1p1',
            'mount_points': ['/boot/efi'],
        },
        {
            'id': ROOT_PARTITION_ID,
            'name': '/dev/nvme0n1p2',
            'mount_points': ['/'],
        },
    ]
    INTERFACES = {
        'results': [
            {
                'id': LOOPBACK_INTERFACE_ID,
                'name': 'lo',
                'is_loopback': True,
                'is_up': True,
            },
            {
                'id': ETHERNET_INTERFACE_ID,
                'name': 'enp4s0',
                'is_loopback': False,
                'is_up': False,
            },
            {'id': INTERFACE_ID, 'name': 'enp3s0', 'is_loopback': False, 'is_up': True},
        ]
    }

    def route_calls(self, mock_http_client, **overrides):
        """Answer summary calls by endpoint; return the last params sent per endpoint.
        An override may be a callable of the params, to answer per page."""
        responses = {
            '/api/proc/partitions/': self.PARTITIONS,
            '/api/proc/interfaces/': self.INTERFACES,
        }
        responses.update(overrides)
        sent = {}

        async def fake_get(*args, **kwargs):
            # The lookups pass endpoint by keyword, the metric reads positionally.
            endpoint = kwargs['endpoint'] if 'endpoint' in kwargs else args[2]
            sent[endpoint] = kwargs.get('params')
            response = responses.get(endpoint, {'results': [{'usage': 1.0}]})
            return response(kwargs['params']) if callable(response) else response

        mock_http_client.get.side_effect = fake_get
        return sent

    @pytest.mark.asyncio
    async def test_summary_sends_partition_and_interface_ids_not_names(
        self, mock_http_client, mock_token_manager
    ):
        sent = self.route_calls(mock_http_client)

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert sent['/api/proc/partitions/'] == {'server': SERVER_ID}
        assert sent['/api/proc/interfaces/'] == {
            'server': SERVER_ID,
            'page_size': 100,
        }
        disk_params = sent['/api/metrics/realtime/disk-usage/']
        assert set(disk_params) == {'server', 'start', 'end', 'partition'}
        assert disk_params['server'] == SERVER_ID
        assert disk_params['partition'] == ROOT_PARTITION_ID
        assert isinstance(disk_params['start'], str)
        assert isinstance(disk_params['end'], str)
        traffic_params = sent['/api/metrics/realtime/traffic/']
        assert set(traffic_params) == {'server', 'start', 'end', 'interface'}
        assert traffic_params['server'] == SERVER_ID
        assert traffic_params['interface'] == INTERFACE_ID
        assert isinstance(traffic_params['start'], str)
        assert isinstance(traffic_params['end'], str)
        metrics = result['data']['metrics']
        assert metrics['disk']['available'] is True
        assert metrics['network']['available'] is True

    @pytest.mark.asyncio
    async def test_summary_prefers_a_physical_interface_over_a_virtual_one(
        self, mock_http_client, mock_token_manager
    ):
        interfaces = [
            {'id': 'v1', 'name': 'br-1a2b3c', 'is_loopback': False, 'is_up': True},
            {'id': 'v2', 'name': 'docker0', 'is_loopback': False, 'is_up': True},
            {'id': INTERFACE_ID, 'name': 'eth0', 'is_loopback': False, 'is_up': True},
        ]
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/interfaces/': interfaces}
        )

        await get_server_metrics_summary(server_id=SERVER_ID, workspace='testworkspace')

        assert sent['/api/metrics/realtime/traffic/']['interface'] == INTERFACE_ID

    @pytest.mark.asyncio
    async def test_summary_falls_back_to_a_virtual_interface_when_none_is_physical(
        self, mock_http_client, mock_token_manager
    ):
        interfaces = [
            {'id': 'lo', 'name': 'lo', 'is_loopback': True, 'is_up': True},
            {'id': 'v1', 'name': 'br-1a2b3c', 'is_loopback': False, 'is_up': True},
            {'id': 'v2', 'name': 'docker0', 'is_loopback': False, 'is_up': True},
        ]
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/interfaces/': interfaces}
        )

        await get_server_metrics_summary(server_id=SERVER_ID, workspace='testworkspace')

        assert sent['/api/metrics/realtime/traffic/']['interface'] == 'v1'

    @pytest.mark.asyncio
    async def test_summary_skips_a_physical_interface_that_is_down(
        self, mock_http_client, mock_token_manager
    ):
        interfaces = [
            {'id': 'p1', 'name': 'eth0', 'is_loopback': False, 'is_up': False},
            {'id': 'v1', 'name': 'docker0', 'is_loopback': False, 'is_up': True},
        ]
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/interfaces/': interfaces}
        )

        await get_server_metrics_summary(server_id=SERVER_ID, workspace='testworkspace')

        assert sent['/api/metrics/realtime/traffic/']['interface'] == 'v1'

    @pytest.mark.asyncio
    async def test_summary_prefers_a_non_virtual_root_partition(
        self, mock_http_client, mock_token_manager
    ):
        partitions = [
            {'id': 'tmp', 'name': 'overlay', 'mount_points': ['/'], 'is_virtual': True},
            {
                'id': ROOT_PARTITION_ID,
                'name': '/dev/sda1',
                'mount_points': ['/'],
                'is_virtual': False,
            },
        ]
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/partitions/': partitions}
        )

        await get_server_metrics_summary(server_id=SERVER_ID, workspace='testworkspace')

        disk_params = sent['/api/metrics/realtime/disk-usage/']
        assert disk_params['partition'] == ROOT_PARTITION_ID

    @pytest.mark.asyncio
    async def test_summary_falls_back_to_a_virtual_root_partition(
        self, mock_http_client, mock_token_manager
    ):
        partitions = [
            {'id': 'tmp', 'name': 'overlay', 'mount_points': ['/'], 'is_virtual': True},
        ]
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/partitions/': partitions}
        )

        await get_server_metrics_summary(server_id=SERVER_ID, workspace='testworkspace')

        assert sent['/api/metrics/realtime/disk-usage/']['partition'] == 'tmp'

    @pytest.mark.asyncio
    async def test_summary_accepts_a_paginated_partitions_response(
        self, mock_http_client, mock_token_manager
    ):
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/partitions/': {'results': self.PARTITIONS}}
        )

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        disk_params = sent['/api/metrics/realtime/disk-usage/']
        assert set(disk_params) == {'server', 'start', 'end', 'partition'}
        assert disk_params['partition'] == ROOT_PARTITION_ID

    @pytest.mark.asyncio
    async def test_summary_skips_disk_usage_when_no_partition_is_mounted_at_root(
        self, mock_http_client, mock_token_manager
    ):
        sent = self.route_calls(
            mock_http_client,
            **{
                '/api/proc/partitions/': self.PARTITIONS[:1],
                '/api/proc/interfaces/': [],
            },
        )

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert '/api/metrics/realtime/disk-usage/' not in sent
        assert result['data']['metrics']['disk'] == {
            'available': False,
            'error': 'No partition mounted at / was found for this server',
        }
        assert '/api/metrics/realtime/traffic/' not in sent
        assert result['data']['metrics']['network'] == {
            'available': False,
            'error': 'No active non-loopback interface was found',
        }

    @pytest.mark.asyncio
    async def test_summary_names_a_failed_partition_lookup(
        self, mock_http_client, mock_token_manager
    ):
        sent = self.route_calls(
            mock_http_client,
            **{
                '/api/proc/partitions/': {
                    'error': 'HTTP Error',
                    'status_code': HTTPStatus.FORBIDDEN,
                    'message': 'Forbidden',
                }
            },
        )

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert '/api/metrics/realtime/disk-usage/' not in sent
        disk = result['data']['metrics']['disk']
        assert disk['available'] is False
        assert disk['error'] == 'Partition lookup failed: Forbidden'
        assert disk['status_code'] == HTTPStatus.FORBIDDEN

    @pytest.mark.asyncio
    async def test_summary_skips_traffic_when_interface_lookup_fails(
        self, mock_http_client, mock_token_manager
    ):
        sent = self.route_calls(
            mock_http_client, **{'/api/proc/interfaces/': HTTP_ERROR_ENVELOPE}
        )

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert '/api/metrics/realtime/traffic/' not in sent
        network = result['data']['metrics']['network']
        assert network['available'] is False
        assert network['error'] == 'Interface lookup failed: Not found'

    @pytest.mark.asyncio
    async def test_summary_finds_an_interface_that_is_only_on_the_second_page(
        self, mock_http_client, mock_token_manager
    ):
        page_params = []
        loopback, down, active = self.INTERFACES['results']

        def interfaces(params):
            page_params.append(params)
            if params.get('page') == 2:
                return {'next': None, 'results': [active]}
            return {'next': 2, 'results': [loopback, down]}

        sent = self.route_calls(
            mock_http_client, **{'/api/proc/interfaces/': interfaces}
        )

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert page_params == [
            {'server': SERVER_ID, 'page_size': 100},
            {'server': SERVER_ID, 'page_size': 100, 'page': 2},
        ]
        assert sent['/api/metrics/realtime/traffic/']['interface'] == INTERFACE_ID
        assert result['data']['metrics']['network']['available'] is True

    @pytest.mark.asyncio
    async def test_summary_treats_a_failed_later_interface_page_as_a_lookup_failure(
        self, mock_http_client, mock_token_manager
    ):
        loopback = self.INTERFACES['results'][0]

        def interfaces(params):
            if params.get('page') == 2:
                return HTTP_ERROR_ENVELOPE
            return {'next': 2, 'results': [loopback]}

        sent = self.route_calls(
            mock_http_client, **{'/api/proc/interfaces/': interfaces}
        )

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert '/api/metrics/realtime/traffic/' not in sent
        assert (
            result['data']['metrics']['network']['error']
            == 'Interface lookup failed: Not found'
        )

    @pytest.mark.asyncio
    async def test_summary_stops_paging_when_a_page_comes_back_empty(
        self, mock_http_client, mock_token_manager
    ):
        page_params = []

        def interfaces(params):
            page_params.append(params.get('page'))
            return {'next': 2, 'results': []}

        self.route_calls(mock_http_client, **{'/api/proc/interfaces/': interfaces})

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert page_params == [None]
        assert (
            result['data']['metrics']['network']['error']
            == 'No active non-loopback interface was found'
        )

    @pytest.mark.asyncio
    async def test_summary_stops_after_the_interface_page_cap(
        self, mock_http_client, mock_token_manager
    ):
        loopback = self.INTERFACES['results'][0]
        pages = []

        def interfaces(params):
            pages.append(params.get('page'))
            return {'next': len(pages) + 1, 'results': [loopback]}

        self.route_calls(mock_http_client, **{'/api/proc/interfaces/': interfaces})

        result = await get_server_metrics_summary(
            server_id=SERVER_ID, workspace='testworkspace'
        )

        assert result['status'] == 'success'
        assert len(pages) == _MAX_INTERFACE_PAGES


class TestParseCpuMetrics:
    """Test parse_cpu_metrics helper function."""

    def test_parse_cpu_metrics_with_data(self):
        """Test CPU metrics parsing with valid data."""
        results = [
            {'timestamp': '2024-01-01T00:00:00Z', 'usage': 25.0},
            {'timestamp': '2024-01-01T01:00:00Z', 'usage': 50.0},
            {'timestamp': '2024-01-01T02:00:00Z', 'usage': 75.0},
        ]

        parsed = parse_cpu_metrics(results)

        assert parsed['available'] is True
        assert parsed['raw_values']['current'] == 75.0
        assert parsed['raw_values']['min'] == 25.0
        assert parsed['raw_values']['max'] == 75.0
        assert parsed['data_points'] == 3

    def test_parse_cpu_metrics_empty(self):
        """Test CPU metrics parsing with empty data."""
        parsed = parse_cpu_metrics([])

        assert parsed['available'] is False

    def test_parse_cpu_metrics_none(self):
        """Test CPU metrics parsing with None."""
        parsed = parse_cpu_metrics(None)

        assert parsed['available'] is False


class TestParseMemoryMetrics:
    """Test parse_memory_metrics helper function."""

    def test_parse_memory_metrics_with_data(self):
        """Test memory metrics parsing with valid data."""
        results = [
            {'timestamp': '2024-01-01T00:00:00Z', 'usage': 40.0},
            {'timestamp': '2024-01-01T01:00:00Z', 'usage': 60.0},
        ]

        parsed = parse_memory_metrics(results)

        assert parsed['available'] is True
        assert parsed['raw_values']['current'] == 60.0
        assert parsed['data_points'] == 2

    def test_parse_memory_metrics_empty(self):
        """Test memory metrics parsing with empty data."""
        parsed = parse_memory_metrics([])

        assert parsed['available'] is False


class TestOldestFirst:
    """Rows order by the instant they name, not by the timestamp text."""

    def test_mixed_utc_offsets_order_by_instant(self):
        later = {'timestamp': '2024-01-01T10:00:00+09:00'}  # 01:00 UTC
        earlier = {'timestamp': '2024-01-01T00:30:00Z'}

        assert _oldest_first([earlier, later]) == [earlier, later]
        assert _oldest_first([later, earlier]) == [earlier, later]

    def test_a_naive_timestamp_is_read_as_utc(self):
        naive = {'timestamp': '2024-01-01T00:00:00'}
        aware = {'timestamp': '2024-01-01T01:00:00Z'}

        assert _oldest_first([aware, naive]) == [naive, aware]

    def test_rows_without_a_usable_timestamp_sort_first(self):
        good = {'timestamp': '2024-01-01T00:00:00Z'}
        missing = {'usage': 1.0}
        garbage = {'timestamp': 'not-a-date'}

        assert _oldest_first([good, missing, garbage]) == [missing, garbage, good]


class TestParsersReadNewestFirstRows:
    """The metrics API orders rows newest first; current must be the newest row."""

    NEWEST = '2024-01-01T02:00:00Z'
    OLDEST = '2024-01-01T00:00:00Z'

    def test_cpu_current_is_the_newest_row(self):
        results = [
            {'timestamp': self.NEWEST, 'usage': 75.0},
            {'timestamp': '2024-01-01T01:00:00Z', 'usage': 50.0},
            {'timestamp': self.OLDEST, 'usage': 25.0},
        ]

        parsed = parse_cpu_metrics(results)

        assert parsed['raw_values']['current'] == 75.0
        assert parsed['time_range'] == {'start': self.OLDEST, 'end': self.NEWEST}

    def test_memory_current_is_the_newest_row(self):
        results = [
            {'timestamp': self.NEWEST, 'usage': 60.0},
            {'timestamp': self.OLDEST, 'usage': 40.0},
        ]

        parsed = parse_memory_metrics(results)

        assert parsed['raw_values']['current'] == 60.0
        assert parsed['time_range'] == {'start': self.OLDEST, 'end': self.NEWEST}

    def test_disk_current_and_space_info_come_from_the_newest_row(self):
        gib = 1024**3
        results = [
            {
                'timestamp': self.NEWEST,
                'usage': 80.0,
                'total': 100 * gib,
                'used': 80 * gib,
                'free': 20 * gib,
                'device': '/dev/new',
            },
            {
                'timestamp': self.OLDEST,
                'usage': 10.0,
                'total': 100 * gib,
                'used': 10 * gib,
                'free': 90 * gib,
                'device': '/dev/old',
            },
        ]

        parsed = parse_disk_metrics(results)

        assert parsed['current_usage'] == 80.0
        assert parsed['space_info']['used'] == '80.00 GB'
        assert parsed['space_info']['device'] == '/dev/new'
        assert parsed['time_range'] == {'start': self.OLDEST, 'end': self.NEWEST}

    def test_network_current_is_the_newest_row(self):
        results = [
            {
                'timestamp': self.NEWEST,
                'interface': INTERFACE_ID,
                'peak_input_bps': 2048,
                'peak_output_bps': 0,
                'avg_input_bps': 0,
                'avg_output_bps': 0,
                'peak_input_pps': 7,
                'peak_output_pps': 0,
            },
            {
                'timestamp': self.OLDEST,
                'interface': INTERFACE_ID,
                'peak_input_bps': 512,
                'peak_output_bps': 0,
                'avg_input_bps': 0,
                'avg_output_bps': 0,
                'peak_input_pps': 1,
                'peak_output_pps': 0,
            },
        ]

        parsed = parse_network_metrics(results)

        assert parsed['current']['peak_input_bps'] == '2.00 Kbps'
        assert parsed['current']['peak_input_pps'] == '7.00 pps'
        assert parsed['time_range'] == {'start': self.OLDEST, 'end': self.NEWEST}


class TestMetricsWindowParams:
    """Every window tool builds start and end the same way."""

    WINDOW_TOOLS = [
        pytest.param(
            get_cpu_usage, '/api/metrics/realtime/cpu/', {}, {}, id='get_cpu_usage'
        ),
        pytest.param(
            get_memory_usage,
            '/api/metrics/realtime/memory/',
            {},
            {},
            id='get_memory_usage',
        ),
        # A blank device and partition would start auto-discovery instead.
        pytest.param(
            get_disk_usage,
            '/api/metrics/realtime/disk-usage/',
            {'device': '/dev/sda1'},
            {'device': '/dev/sda1'},
            id='get_disk_usage',
        ),
        pytest.param(
            get_disk_io, '/api/metrics/realtime/disk-io/', {}, {}, id='get_disk_io'
        ),
        pytest.param(
            get_network_traffic,
            '/api/metrics/realtime/traffic/',
            {'interface': INTERFACE_ID},
            {'interface': INTERFACE_ID},
            id='get_network_traffic',
        ),
    ]

    @pytest.mark.parametrize(
        ('tool', 'endpoint', 'call_kwargs', 'extra_params'), WINDOW_TOOLS
    )
    @pytest.mark.asyncio
    async def test_no_dates_defaults_start_and_omits_end(
        self,
        tool,
        endpoint,
        call_kwargs,
        extra_params,
        mock_http_client,
        mock_token_manager,
    ):
        mock_http_client.get.return_value = {'results': []}
        frozen = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

        with patch('utils.common.datetime') as mock_datetime:
            mock_datetime.now.return_value = frozen
            result = await tool(
                server_id=SERVER_ID,
                workspace='testworkspace',
                region='ap1',
                **call_kwargs,
            )

        assert result['status'] == 'success'
        expected_start = (frozen - timedelta(hours=12)).isoformat()
        assert expected_start == '2024-06-01T00:00:00+00:00'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=endpoint,
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': expected_start,
                **extra_params,
            },
        )

    @pytest.mark.parametrize(
        ('tool', 'endpoint', 'call_kwargs', 'extra_params'), WINDOW_TOOLS
    )
    @pytest.mark.asyncio
    async def test_explicit_dates_are_forwarded(
        self,
        tool,
        endpoint,
        call_kwargs,
        extra_params,
        mock_http_client,
        mock_token_manager,
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await tool(
            server_id=SERVER_ID,
            workspace='testworkspace',
            start_date=START,
            end_date=END,
            region='ap1',
            **call_kwargs,
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=endpoint,
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': START,
                'end': END,
                **extra_params,
            },
        )

    @pytest.mark.parametrize(
        ('tool', 'endpoint', 'call_kwargs', 'extra_params'), WINDOW_TOOLS
    )
    @pytest.mark.asyncio
    async def test_blank_start_falls_back_to_the_default(
        self,
        tool,
        endpoint,
        call_kwargs,
        extra_params,
        mock_http_client,
        mock_token_manager,
    ):
        mock_http_client.get.return_value = {'results': []}
        frozen = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

        with patch('utils.common.datetime') as mock_datetime:
            mock_datetime.now.return_value = frozen
            result = await tool(
                server_id=SERVER_ID,
                workspace='testworkspace',
                start_date='',
                region='ap1',
                **call_kwargs,
            )

        assert result['status'] == 'success'
        expected_start = (frozen - timedelta(hours=12)).isoformat()
        assert expected_start == '2024-06-01T00:00:00+00:00'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=endpoint,
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': expected_start,
                **extra_params,
            },
        )

    @pytest.mark.parametrize(
        ('tool', 'endpoint', 'call_kwargs', 'extra_params'), WINDOW_TOOLS
    )
    @pytest.mark.asyncio
    async def test_blank_end_is_forwarded(
        self,
        tool,
        endpoint,
        call_kwargs,
        extra_params,
        mock_http_client,
        mock_token_manager,
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await tool(
            server_id=SERVER_ID,
            workspace='testworkspace',
            start_date=START,
            end_date='',
            region='ap1',
            **call_kwargs,
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=endpoint,
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': START,
                'end': '',
                **extra_params,
            },
        )


class TestMetricsDeviceFilters:
    """The device, partition, and interface filters, on top of an explicit window."""

    DEVICE_FILTER_CASES = [
        pytest.param(
            get_disk_usage,
            '/api/metrics/realtime/disk-usage/',
            {'device': 'sda', 'partition': 'sda1'},
            {'device': 'sda', 'partition': 'sda1'},
            id='get_disk_usage_device_and_partition',
        ),
        pytest.param(
            get_disk_usage,
            '/api/metrics/realtime/disk-usage/',
            {'device': '', 'partition': 'sda1'},
            {'device': '', 'partition': 'sda1'},
            id='get_disk_usage_blank_device_with_partition_forwarded',
        ),
        pytest.param(
            get_disk_io,
            '/api/metrics/realtime/disk-io/',
            {'device': 'sda'},
            {'device': 'sda'},
            id='get_disk_io_device',
        ),
        pytest.param(
            get_disk_io,
            '/api/metrics/realtime/disk-io/',
            {'device': ''},
            {'device': ''},
            id='get_disk_io_blank_device_forwarded',
        ),
        pytest.param(
            get_network_traffic,
            '/api/metrics/realtime/traffic/',
            {'interface': INTERFACE_ID},
            {'interface': INTERFACE_ID},
            id='get_network_traffic_interface',
        ),
        pytest.param(
            get_network_traffic,
            '/api/metrics/realtime/traffic/',
            {'interface': ''},
            {'interface': ''},
            id='get_network_traffic_blank_interface_forwarded',
        ),
    ]

    @pytest.mark.parametrize(
        ('tool', 'endpoint', 'tool_kwargs', 'extra_params'), DEVICE_FILTER_CASES
    )
    @pytest.mark.asyncio
    async def test_params(
        self,
        tool,
        endpoint,
        tool_kwargs,
        extra_params,
        mock_http_client,
        mock_token_manager,
    ):
        mock_http_client.get.return_value = {'results': []}

        result = await tool(
            server_id=SERVER_ID,
            workspace='testworkspace',
            start_date=START,
            end_date=END,
            region='ap1',
            **tool_kwargs,
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint=endpoint,
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': START,
                'end': END,
                **extra_params,
            },
        )

    @pytest.mark.asyncio
    async def test_disk_usage_blank_device_and_partition_auto_discovers(
        self, mock_http_client, mock_token_manager
    ):
        """Blank device/partition leave both falsy, so the tool discovers one."""
        mock_http_client.get.side_effect = [
            {'devices': ['/dev/sda1']},
            {'results': []},
        ]

        result = await get_disk_usage(
            server_id=SERVER_ID,
            workspace='testworkspace',
            device='',
            partition='',
            start_date=START,
            end_date=END,
            region='ap1',
        )

        assert result['status'] == 'success'
        assert mock_http_client.get.call_count == 2
        mock_http_client.get.assert_called_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/realtime/disk-usage/',
            token='test-token',
            params={
                'server': SERVER_ID,
                'start': START,
                'end': END,
                'device': '/dev/sda1',
                'partition': '',
            },
        )


class TestListLatestMetrics:
    """Test list_latest_metrics function."""

    @pytest.mark.asyncio
    async def test_list_latest_metrics_no_filters(
        self, mock_http_client, mock_token_manager
    ):
        """A bare call forwards an empty params dict."""
        mock_http_client.get.return_value = {
            'count': 1,
            'current': 1,
            'next': None,
            'previous': None,
            'last': 1,
            'results': [
                {
                    'id': SERVER_ID,
                    'name': 'web-01',
                    'is_connected': True,
                    'cpu': {
                        'value': 12.3,
                        'unit': 'percent',
                        'sampled_at': START,
                        'device': None,
                        'collected': True,
                        'reason': None,
                        'interval_s': 60,
                    },
                }
            ],
        }

        result = await list_latest_metrics(workspace='testworkspace', region='ap1')

        assert result['status'] == 'success'
        assert result['region'] == 'ap1'
        assert result['workspace'] == 'testworkspace'
        assert result['data']['count'] == 1

        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={},
        )

    @pytest.mark.asyncio
    async def test_list_latest_metrics_forwards_all_filters(
        self, mock_http_client, mock_token_manager
    ):
        """Every filter, search, and pagination argument reaches the query
        params under the name the server expects."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_latest_metrics(
            workspace='testworkspace',
            region='ap1',
            search='web',
            groups=GROUP_ID,
            tag='env:prod',
            is_connected=True,
            state='stale',
            ordering='-cpu',
            page=2,
            page_size=50,
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={
                'page': 2,
                'page_size': 50,
                'search': 'web',
                'groups': GROUP_ID,
                'tag': 'env:prod',
                'is_connected': True,
                'state': 'stale',
                'ordering': '-cpu',
            },
        )

    @pytest.mark.asyncio
    async def test_list_latest_metrics_is_connected_false_is_not_dropped(
        self, mock_http_client, mock_token_manager
    ):
        """A falsy filter value must survive build_list_params' None-only check."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_latest_metrics(
            workspace='testworkspace', region='ap1', is_connected=False
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={'is_connected': False},
        )

    @pytest.mark.asyncio
    async def test_list_latest_metrics_ordering_accepts_hyphenated_family_name(
        self, mock_http_client, mock_token_manager
    ):
        """The server aliases a family's hyphenated wire name (disk-usage) to
        its underscore ordering_fields spelling (disk_usage); both must pass
        client-side validation and reach the request unchanged."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_latest_metrics(
            workspace='testworkspace', region='ap1', ordering='disk-usage'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={'ordering': 'disk-usage'},
        )

    @pytest.mark.asyncio
    async def test_list_latest_metrics_ordering_accepts_underscore_family_name(
        self, mock_http_client, mock_token_manager
    ):
        """The underscore spelling works too, with the descending prefix."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_latest_metrics(
            workspace='testworkspace', region='ap1', ordering='-disk_io'
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={'ordering': '-disk_io'},
        )

    @pytest.mark.asyncio
    async def test_list_latest_metrics_invalid_state_rejected(
        self, mock_http_client, mock_token_manager
    ):
        """An unknown state is rejected client-side, before any HTTP call."""
        result = await list_latest_metrics(
            workspace='testworkspace', region='ap1', state='bogus'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'state'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_latest_metrics_invalid_ordering_rejected(
        self, mock_http_client, mock_token_manager
    ):
        """An unknown ordering field is rejected client-side even with the
        descending prefix stripped first."""
        result = await list_latest_metrics(
            workspace='testworkspace', region='ap1', ordering='-bogus'
        )

        assert result['status'] == 'error'
        assert result['error_code'] == 'validation'
        assert result['field'] == 'ordering'
        mock_http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_latest_metrics_page_size_over_100_is_forwarded(
        self, mock_http_client, mock_token_manager
    ):
        """No client-side ceiling: page_size is forwarded as-is and the server
        enforces its own cap, matching list_servers (tools/server_tools.py),
        which also documents a max of 100 without rejecting a larger value
        locally."""
        mock_http_client.get.return_value = {'count': 0, 'results': []}

        result = await list_latest_metrics(
            workspace='testworkspace', region='ap1', page_size=250
        )

        assert result['status'] == 'success'
        mock_http_client.get.assert_called_once_with(
            region='ap1',
            workspace='testworkspace',
            endpoint='/api/metrics/latest/',
            token='test-token',
            params={'page_size': 250},
        )

    @pytest.mark.asyncio
    async def test_list_latest_metrics_plan_floor_402_passthrough(
        self, mock_http_client, mock_token_manager
    ):
        """A 402 plan-floor error envelope passes through unchanged."""
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.PAYMENT_REQUIRED,
            'message': 'Payment required',
        }

        result = await list_latest_metrics(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.PAYMENT_REQUIRED
        assert result['message'] == 'Payment required'

    @pytest.mark.asyncio
    async def test_list_latest_metrics_extension_off_403_passthrough(
        self, mock_http_client, mock_token_manager
    ):
        """A 403 extension-disabled error envelope passes through unchanged."""
        mock_http_client.get.return_value = {
            'error': 'HTTP Error',
            'status_code': HTTPStatus.FORBIDDEN,
            'message': 'Forbidden',
        }

        result = await list_latest_metrics(workspace='testworkspace', region='ap1')

        assert result['status'] == 'error'
        assert result['status_code'] == HTTPStatus.FORBIDDEN
        assert result['message'] == 'Forbidden'

    @pytest.mark.asyncio
    async def test_list_latest_metrics_no_token(
        self, mock_http_client, mock_token_manager
    ):
        """No token available surfaces the standard token error."""
        mock_token_manager.get_token.return_value = None

        result = await list_latest_metrics(workspace='testworkspace')

        assert result['status'] == 'error'
        assert 'No token found' in result['message']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
