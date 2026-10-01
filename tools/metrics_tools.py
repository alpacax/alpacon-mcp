"""Metrics and monitoring tools for Alpacon MCP server."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from utils.api_call import http_call_response
from utils.common import (
    build_list_params,
    error_response,
    expect_json_object,
    json_records,
    resolve_time_window,
    success_response,
    unwrap_http_result,
)
from utils.decorators import mcp_tool_handler
from utils.error_handler import UpstreamAuthError, format_validation_error
from utils.http_client import http_client
from utils.tool_annotations import READ_ONLY

#: `?state=` values `/api/metrics/latest/` accepts; mirrors alpacon-server's
#: `metrics.latest.LATEST_STATES`. `stale` covers `no_data`: never-stored is overdue.
VALID_LATEST_METRIC_STATES = frozenset({'stale', 'no_data'})
_LATEST_STATE_SENTENCE = (
    f'state must be one of: {", ".join(sorted(VALID_LATEST_METRIC_STATES))}.'
)

#: `?ordering=` base names, optionally `-` prefixed. Only disk usage and disk I/O
#: repeat: alpacon-server aliases the hyphenated wire name to the underscore one.
VALID_LATEST_METRIC_ORDERING_FIELDS = frozenset(
    {
        'name',
        'starred',
        'sampled_at',
        'cpu',
        'memory',
        'disk_usage',
        'disk-usage',
        'disk_io',
        'disk-io',
        'net',
    }
)
_LATEST_ORDERING_SENTENCE = (
    'ordering must be one of: '
    f'{", ".join(sorted(VALID_LATEST_METRIC_ORDERING_FIELDS))}, '
    "optionally prefixed with '-' for descending."
)


_EPOCH = datetime.min.replace(tzinfo=UTC)


def _timestamp_key(entry: dict[str, Any]) -> datetime:
    """Parse a row's timestamp; a naive one is read as UTC, a bad one sorts first."""
    try:
        parsed = datetime.fromisoformat(
            str(entry.get('timestamp')).replace('Z', '+00:00')
        )
    except ValueError:
        return _EPOCH
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _oldest_first(results: list) -> list:
    """Order metric rows by the instant of their timestamp; the API returns newest first."""
    return sorted(results, key=_timestamp_key)


def parse_cpu_metrics(results: list) -> dict[str, Any]:
    """Parse CPU usage metrics to extract meaningful statistics.

    Args:
        results: List of CPU usage data points

    Returns:
        Parsed statistics including average, min, max, current usage with user-friendly format
    """
    if not results:
        return {'available': False, 'message': 'No CPU data available'}

    results = _oldest_first(results)

    usage_values = [entry.get('usage', 0) for entry in results if 'usage' in entry]

    if not usage_values:
        return {'available': False, 'message': 'No usage values found'}

    current = usage_values[-1]
    average = round(sum(usage_values) / len(usage_values), 2)
    minimum = min(usage_values)
    maximum = max(usage_values)

    # Determine usage status
    def get_status(usage):
        if usage < 20:
            return 'idle'
        elif usage < 50:
            return 'low'
        elif usage < 70:
            return 'moderate'
        elif usage < 90:
            return 'high'
        else:
            return 'critical'

    return {
        'available': True,
        'current_usage_percent': f'{current:.2f}%',
        'average_usage_percent': f'{average:.2f}%',
        'min_usage_percent': f'{minimum:.2f}%',
        'max_usage_percent': f'{maximum:.2f}%',
        'status': get_status(current),
        'health': 'healthy'
        if current < 80
        else 'warning'
        if current < 95
        else 'critical',
        'data_points': len(usage_values),
        'time_range': {
            'start': results[0].get('timestamp') if results else None,
            'end': results[-1].get('timestamp') if results else None,
        },
        'raw_values': {
            'current': current,
            'average': average,
            'min': minimum,
            'max': maximum,
        },
    }


@mcp_tool_handler(
    description='Get CPU utilization metrics for a server over a time range. Returns current, average, min, max usage percentage with health status. When to use: investigating performance issues or checking server load. Related: get_memory_usage (pair with CPU for full picture), get_server_metrics_summary (quick overview of all metrics), get_top_servers (compare across servers). Note: Defaults to the last 12 hours if no date range is specified; the realtime endpoint returns at most the last 12 hours.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'cpu usage load processor utilization performance'},
)
async def get_cpu_usage(
    server_id: str,
    workspace: str,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get CPU usage metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        CPU usage metrics with parsed statistics (current, average, min, max)
    """
    token = kwargs.get('token')

    start, end = resolve_time_window(start_date, end_date)
    params = build_list_params(server=server_id, start=start, end=end)

    # Make async call to get CPU metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/realtime/cpu/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get CPU usage metrics',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    # Parse metrics for better readability
    parsed_data = {
        'server_id': server_id,
        'metric_type': 'cpu_usage',
        'statistics': parse_cpu_metrics(json_records(result)),
        'raw_data_available': True,
    }

    return success_response(data=parsed_data, region=region, workspace=workspace)


def parse_memory_metrics(results: list) -> dict[str, Any]:
    """Parse memory usage metrics to extract meaningful statistics.

    Args:
        results: List of memory usage data points

    Returns:
        Parsed statistics including average, min, max, current usage with user-friendly format
    """
    if not results:
        return {'available': False, 'message': 'No memory data available'}

    results = _oldest_first(results)

    usage_values = [entry.get('usage', 0) for entry in results if 'usage' in entry]

    if not usage_values:
        return {'available': False, 'message': 'No usage values found'}

    current = usage_values[-1]
    average = round(sum(usage_values) / len(usage_values), 2)
    minimum = min(usage_values)
    maximum = max(usage_values)

    # Determine usage status
    def get_status(usage):
        if usage < 30:
            return 'idle'
        elif usage < 60:
            return 'low'
        elif usage < 80:
            return 'moderate'
        elif usage < 95:
            return 'high'
        else:
            return 'critical'

    return {
        'available': True,
        'current_usage_percent': f'{current:.2f}%',
        'average_usage_percent': f'{average:.2f}%',
        'min_usage_percent': f'{minimum:.2f}%',
        'max_usage_percent': f'{maximum:.2f}%',
        'status': get_status(current),
        'health': 'healthy'
        if current < 85
        else 'warning'
        if current < 95
        else 'critical',
        'data_points': len(usage_values),
        'time_range': {
            'start': results[0].get('timestamp') if results else None,
            'end': results[-1].get('timestamp') if results else None,
        },
        'raw_values': {
            'current': current,
            'average': average,
            'min': minimum,
            'max': maximum,
        },
    }


@mcp_tool_handler(
    description='Get RAM memory utilization metrics for a server over a time range. Returns current, average, min, max usage percentage with health status. When to use: investigating memory pressure or OOM issues. Related: get_cpu_usage (pair for full resource picture), get_server_metrics_summary (quick overview). Note: Defaults to the last 12 hours; the realtime endpoint returns at most the last 12 hours.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'memory ram usage utilization'},
)
async def get_memory_usage(
    server_id: str,
    workspace: str,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get memory usage metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Memory usage metrics with parsed statistics (current, average, min, max)
    """
    token = kwargs.get('token')

    start, end = resolve_time_window(start_date, end_date)
    params = build_list_params(server=server_id, start=start, end=end)

    # Make async call to get memory metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/realtime/memory/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get memory usage metrics',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    # Parse metrics for better readability
    parsed_data = {
        'server_id': server_id,
        'metric_type': 'memory_usage',
        'statistics': parse_memory_metrics(json_records(result)),
        'raw_data_available': True,
    }

    return success_response(data=parsed_data, region=region, workspace=workspace)


def parse_disk_metrics(results: list) -> dict[str, Any]:
    """Parse disk usage metrics to extract meaningful statistics.

    Args:
        results: List of disk usage data points

    Returns:
        Parsed statistics including average, min, max, current usage and space info
    """
    if not results:
        return {'available': False, 'message': 'No disk data available'}

    results = _oldest_first(results)

    usage_values = [entry.get('usage', 0) for entry in results if 'usage' in entry]

    if not usage_values:
        return {'available': False, 'message': 'No usage values found'}

    # Get space information from the latest entry
    latest_entry = results[-1]
    total_bytes = latest_entry.get('total', 0)
    used_bytes = latest_entry.get('used', 0)
    free_bytes = latest_entry.get('free', 0)

    # Convert bytes to human-readable format
    def bytes_to_human(bytes_value):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f'{bytes_value:.2f} {unit}'
            bytes_value /= 1024.0
        return f'{bytes_value:.2f} PB'

    return {
        'available': True,
        'current_usage': usage_values[-1],
        'average_usage': round(sum(usage_values) / len(usage_values), 2),
        'min_usage': min(usage_values),
        'max_usage': max(usage_values),
        'space_info': {
            'total': bytes_to_human(total_bytes),
            'used': bytes_to_human(used_bytes),
            'free': bytes_to_human(free_bytes),
            'device': latest_entry.get('device'),
            'mount_point': latest_entry.get('mount_point'),
        },
        'data_points': len(usage_values),
        'time_range': {
            'start': results[0].get('timestamp') if results else None,
            'end': results[-1].get('timestamp') if results else None,
        },
    }


@mcp_tool_handler(
    description='Get disk space usage metrics for a server by device or partition. Returns usage percentage and total/used/free space. When to use: checking available disk space or monitoring storage growth. Related: get_disk_io (I/O throughput, not space), get_disk_info (physical disk layout). Note: Auto-discovers first device if none specified. Defaults to the last 12 hours; the realtime endpoint returns at most the last 12 hours.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'disk space storage partition mount usage'},
)
async def get_disk_usage(
    server_id: str,
    workspace: str,
    device: str | None = None,
    partition: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get disk usage metrics for a server with parsed statistics.

    Note: This endpoint requires either 'device' or 'partition' parameter.
    If neither is provided, it will automatically fetch available devices first.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        device: Optional device path (e.g., '/dev/sda1'). If not provided, will fetch first available device
        partition: Optional partition ID (UUID) from /api/proc/partitions/
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Disk usage metrics with parsed statistics (current, average, min, max, space info)
    """
    token = kwargs.get('token')

    # If no device or partition provided, fetch available devices first
    if not device and not partition:
        try:
            devices_result = await http_client.get(
                region=region,
                workspace=workspace,
                endpoint='/api/metrics/realtime/disk-usage/device/',
                token=token,
                params={'server': server_id},
            )

            # A 4xx/5xx here must surface as the real error, not be masked as
            # "no devices found" by the empty-list fallback below.
            err = unwrap_http_result(
                devices_result,
                default_message='Failed to fetch disk devices',
                server_id=server_id,
                region=region,
                workspace=workspace,
            )
            if err:
                return err

            # Extract device list from response
            available_devices = (
                devices_result.get('devices', [])
                if isinstance(devices_result, dict)
                else []
            )

            if available_devices:
                # Use the first available device
                device = available_devices[0]
            else:
                return error_response(
                    message='No disk devices found for this server',
                    server_id=server_id,
                    region=region,
                    workspace=workspace,
                )
        except UpstreamAuthError:
            raise
        except Exception as e:
            return error_response(
                message=f'Failed to fetch disk devices: {str(e)}',
                server_id=server_id,
                region=region,
                workspace=workspace,
            )

    start, end = resolve_time_window(start_date, end_date)
    params = build_list_params(
        server=server_id,
        device=device,
        partition=partition,
        start=start,
        end=end,
    )

    # Make async call to get disk metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/realtime/disk-usage/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get disk usage metrics',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    # Parse metrics for better readability
    parsed_data = {
        'server_id': server_id,
        'metric_type': 'disk_usage',
        'device': device,
        'partition': partition,
        'statistics': parse_disk_metrics(json_records(result)),
        'raw_data_available': True,
    }

    return success_response(data=parsed_data, region=region, workspace=workspace)


def parse_network_metrics(results: list) -> dict[str, Any]:
    """Parse network traffic metrics to extract meaningful statistics.

    Args:
        results: List of network traffic data points

    Returns:
        Parsed statistics including average, peak input/output in bps and pps
    """
    if not results:
        return {'available': False, 'message': 'No network data available'}

    results = _oldest_first(results)

    # Extract various metrics
    peak_input_bps = [entry.get('peak_input_bps', 0) for entry in results]
    peak_output_bps = [entry.get('peak_output_bps', 0) for entry in results]
    avg_input_bps = [entry.get('avg_input_bps', 0) for entry in results]
    avg_output_bps = [entry.get('avg_output_bps', 0) for entry in results]
    peak_input_pps = [entry.get('peak_input_pps', 0) for entry in results]
    peak_output_pps = [entry.get('peak_output_pps', 0) for entry in results]

    # Convert bps to human-readable format
    def bps_to_human(bps_value):
        for unit in ['bps', 'Kbps', 'Mbps', 'Gbps']:
            if bps_value < 1024.0:
                return f'{bps_value:.2f} {unit}'
            bps_value /= 1024.0
        return f'{bps_value:.2f} Tbps'

    latest_entry = results[-1]

    return {
        'available': True,
        'interface': latest_entry.get('interface'),
        'current': {
            'peak_input_bps': bps_to_human(peak_input_bps[-1])
            if peak_input_bps
            else '0 bps',
            'peak_output_bps': bps_to_human(peak_output_bps[-1])
            if peak_output_bps
            else '0 bps',
            'avg_input_bps': bps_to_human(avg_input_bps[-1])
            if avg_input_bps
            else '0 bps',
            'avg_output_bps': bps_to_human(avg_output_bps[-1])
            if avg_output_bps
            else '0 bps',
            'peak_input_pps': f'{peak_input_pps[-1]:.2f} pps'
            if peak_input_pps
            else '0 pps',
            'peak_output_pps': f'{peak_output_pps[-1]:.2f} pps'
            if peak_output_pps
            else '0 pps',
        },
        'averages': {
            'peak_input_bps': bps_to_human(sum(peak_input_bps) / len(peak_input_bps))
            if peak_input_bps
            else '0 bps',
            'peak_output_bps': bps_to_human(sum(peak_output_bps) / len(peak_output_bps))
            if peak_output_bps
            else '0 bps',
            'avg_input_bps': bps_to_human(sum(avg_input_bps) / len(avg_input_bps))
            if avg_input_bps
            else '0 bps',
            'avg_output_bps': bps_to_human(sum(avg_output_bps) / len(avg_output_bps))
            if avg_output_bps
            else '0 bps',
        },
        'peaks': {
            'max_input_bps': bps_to_human(max(peak_input_bps))
            if peak_input_bps
            else '0 bps',
            'max_output_bps': bps_to_human(max(peak_output_bps))
            if peak_output_bps
            else '0 bps',
            'max_input_pps': f'{max(peak_input_pps):.2f} pps'
            if peak_input_pps
            else '0 pps',
            'max_output_pps': f'{max(peak_output_pps):.2f} pps'
            if peak_output_pps
            else '0 pps',
        },
        'data_points': len(results),
        'time_range': {
            'start': results[0].get('timestamp') if results else None,
            'end': results[-1].get('timestamp') if results else None,
        },
    }


@mcp_tool_handler(
    description='Get disk I/O read/write throughput metrics for a server. Returns peak and average transfer rates per device. When to use: diagnosing storage performance bottlenecks or slow I/O. Related: get_disk_usage (space, not I/O), get_top_servers (compare I/O across servers). Note: Defaults to the last 12 hours; the realtime endpoint returns at most the last 12 hours.',
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'disk io read write throughput iops storage performance'
    },
)
async def get_disk_io(
    server_id: str,
    workspace: str,
    device: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get disk I/O performance metrics for a server.

    Returns disk read/write throughput metrics with peak and average values.

    Args:
        server_id: Server ID to get disk I/O metrics for
        workspace: Workspace name. Required parameter
        device: Optional disk device name (e.g., 'sda', 'nvme0n1')
        start_date: Start date for metrics (ISO 8601 format). Defaults to the last 12 hours; older data is not returned
        end_date: End date for metrics (ISO 8601 format)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Disk I/O metrics response with device, read/write rates, and timestamps
    """
    token = kwargs.get('token')

    start, end = resolve_time_window(start_date, end_date)
    params = build_list_params(
        server=server_id,
        device=device,
        start=start,
        end=end,
    )

    # Make async call to get disk I/O metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/realtime/disk-io/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get disk I/O metrics',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    return success_response(
        data=result,
        server_id=server_id,
        device=device,
        start_date=start_date,
        end_date=end_date,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Get network bandwidth and traffic metrics for a server by interface. Returns current, average, and peak values for input/output in bps and pps. When to use: investigating network bottlenecks or monitoring bandwidth. Related: get_network_interfaces (list available interfaces), get_top_servers (compare traffic across servers). Note: Defaults to the last 12 hours; the realtime endpoint returns at most the last 12 hours.',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'network traffic bandwidth interface bps packets'},
)
async def get_network_traffic(
    server_id: str,
    workspace: str,
    interface: str,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Get network traffic metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        interface: Required interface ID (UUID) from /api/proc/interfaces/, not a name like 'eth0'
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Network traffic metrics with parsed statistics (current, averages, peaks for bps/pps)
    """
    token = kwargs.get('token')

    start, end = resolve_time_window(start_date, end_date)
    params = build_list_params(
        server=server_id,
        interface=interface,
        start=start,
        end=end,
    )

    # Make async call to get traffic metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/realtime/traffic/',
        token=token,
        params=params,
    )

    err = unwrap_http_result(
        result,
        default_message='Failed to get network traffic metrics',
        server_id=server_id,
        region=region,
        workspace=workspace,
    )
    if err:
        return err

    # Parse metrics for better readability
    parsed_data = {
        'server_id': server_id,
        'metric_type': 'network_traffic',
        'interface': interface,
        'statistics': parse_network_metrics(json_records(result)),
        'raw_data_available': True,
    }

    return success_response(data=parsed_data, region=region, workspace=workspace)


@mcp_tool_handler(
    description='Get the top servers ranked by resource usage in the last 24 hours. When to use: finding the busiest or most loaded servers in a workspace, comparing resource usage across servers. Related: get_cpu_usage, get_memory_usage (detailed metrics for a specific server). Note: Supports cpu, memory, disk_io, traffic. Pass comma-separated or leave empty for all.',
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'top servers ranking busiest compare metrics workspace'
    },
)
async def get_top_servers(
    workspace: str, metric_types: str = '', region: str = '', **kwargs
) -> dict[str, Any]:
    """Get top 5 servers by specified metric types in the last 24 hours.

    Supports querying multiple metrics simultaneously for efficiency.

    Args:
        workspace: Workspace name. Required parameter
        metric_types: Comma-separated metric types (e.g., "cpu,memory,disk_io,traffic").
                     Leave empty to get all metrics. Valid values: cpu, memory, disk_io, traffic
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Top servers response with usage/performance statistics for requested metrics.
        When multiple metrics requested, returns dict with each metric type as key.
        When single metric requested, returns data directly with metric_type field.

    Examples:
        - metric_types="": Get all metrics (cpu, memory, disk_io, traffic)
        - metric_types="cpu": Get CPU top servers only
        - metric_types="cpu,memory": Get CPU and memory top servers
    """
    token = kwargs.get('token')

    # Define available metrics and their endpoints
    metric_endpoints = {
        'cpu': '/api/metrics/realtime/cpu/top/',
        'memory': '/api/metrics/realtime/memory/top/',
        'disk_io': '/api/metrics/realtime/disk-io/top/',
        'traffic': '/api/metrics/realtime/traffic/top/',
    }

    # Parse requested metric types
    if metric_types.strip():
        requested_metrics = [m.strip() for m in metric_types.split(',')]
        # Validate all requested metrics
        invalid_metrics = [m for m in requested_metrics if m not in metric_endpoints]
        if invalid_metrics:
            return error_response(
                message=f'Invalid metric types: {", ".join(invalid_metrics)}. Valid values: {", ".join(metric_endpoints.keys())}',
                region=region,
                workspace=workspace,
            )
    else:
        # Empty string means all metrics
        requested_metrics = list(metric_endpoints.keys())

    # Create async tasks for all requested metrics
    tasks = {}
    for metric in requested_metrics:
        tasks[metric] = http_client.get(
            region=region,
            workspace=workspace,
            endpoint=metric_endpoints[metric],
            token=token,
        )

    # Execute all requests in parallel
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    # Combine results - preserve original format for single metric
    if len(requested_metrics) == 1:
        # Single metric - return in original format for backward compatibility
        metric = requested_metrics[0]
        result = results[0]

        if isinstance(result, Exception):
            return error_response(
                message=f'Failed to fetch {metric} metrics: {str(result)}',
                region=region,
                workspace=workspace,
            )

        err = unwrap_http_result(
            result,
            default_message=f'Failed to fetch {metric} metrics',
            region=region,
            workspace=workspace,
        )
        if err:
            return err

        return success_response(
            data=result, metric_type=f'{metric}_top', region=region, workspace=workspace
        )

    # Multiple metrics - combine into dict
    combined_data: dict[str, Any] = {}
    for metric, result in zip(tasks.keys(), results, strict=False):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result  # Re-raise CancelledError, KeyboardInterrupt, etc.
            combined_data[metric] = {'error': str(result), 'available': False}
        else:
            err = unwrap_http_result(
                result, default_message=f'Failed to fetch {metric} metrics'
            )
            combined_data[metric] = (
                {'error': err['message'], 'available': False} if err else result
            )

    return success_response(
        data=combined_data,
        metric_types=requested_metrics,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Get the monitoring alert rules configured for servers. Each rule carries a name, a target metric, a threshold, and whether it is the workspace default. When to use: reviewing what alerts are configured or checking thresholds. Pass server_id to list only the rules attached to that server. Related: list_alerts (triggered alerts), create_alert_rule, update_alert_rule.',
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'alert rules monitoring threshold notification configuration'
    },
)
async def get_alert_rules(
    workspace: str, server_id: str | None = None, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get alert rules for servers.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter rules
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Alert rules response
    """
    token = kwargs.get('token')

    params = build_list_params(server=server_id)

    # Make async call to get alert rules
    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/alert-rules/',
        token=token,
        default_message='Failed to get alert rules',
        params=params,
        server_id=server_id,
    )


def _is_http_error(result: object) -> bool:
    return isinstance(result, dict) and 'error' in result


def _find_record_id(
    result: object, predicate: Callable[[dict[str, Any]], bool]
) -> str | None:
    """Return the id of the first /api/proc/ record matching predicate.

    Those endpoints answer with a plain list or a paginated `results` dict.
    """
    if isinstance(result, dict) and not _is_http_error(result):
        result = result.get('results')
    if not isinstance(result, list):
        return None
    for record in result:
        if isinstance(record, dict) and predicate(record):
            return record.get('id')
    return None


_MAX_SUMMARY_HOURS = 12  # the server clamps a realtime `start` older than this

# Interfaces the server has no virtual flag for; the summary avoids them by name.
_VIRTUAL_INTERFACE_PREFIXES = (
    'docker',
    'br-',
    'veth',
    'virbr',
    'cni',
    'flannel',
    'cali',
    'vxlan',
    'tun',
    'tap',
    'lxc',
    'kube',
)

_MAX_INTERFACE_PAGES = 20  # with page_size=100, at most 2000 interfaces


async def _list_all_interfaces(
    *, region: str, workspace: str, token: Any, server_id: str
) -> list[Any] | dict[str, Any]:
    """Collect a server's /api/proc/interfaces/ records, or return the error dict.

    `next` is a page number; paging stops after `_MAX_INTERFACE_PAGES` pages.
    """
    base_params = {'server': server_id, 'page_size': 100}
    params = base_params
    records: list[Any] = []
    for _ in range(_MAX_INTERFACE_PAGES):
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint='/api/proc/interfaces/',
            token=token,
            params=params,
        )
        if isinstance(result, list):
            return records + result
        result = expect_json_object(result)
        if 'error' in result:
            return result
        page = result.get('results')
        if not page:
            return records
        records.extend(page)
        next_page = result.get('next')
        if not next_page:
            return records
        params = {**base_params, 'page': next_page}
    return records


@mcp_tool_handler(
    description="Get one server's detail: a comprehensive monitoring overview combining CPU, memory, disk, and network metrics for that single server. Returns a compact summary with data availability status. When to use: quick health check of one server or starting point for investigation. Related: get_cpu_usage, get_memory_usage, get_disk_usage, get_network_traffic (full detailed data per metric), list_latest_metrics (latest reading for many servers at once). Note: Use individual metric tools for time-series data.",
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'server metrics summary overview health monitoring dashboard single server detail',
        'anthropic/alwaysLoad': True,
    },
)
async def get_server_metrics_summary(
    server_id: str, workspace: str, hours: int = 12, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get comprehensive metrics summary for a server.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        hours: Hours back to read (default and max: 12, all the realtime endpoints keep)
        region: Region (ap1, us1). Auto-detected if not provided

    Returns:
        Comprehensive server metrics summary (limited size response)
    """
    token = kwargs.get('token')

    hours = min(hours, _MAX_SUMMARY_HOURS)

    # Calculate time range
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(hours=hours)

    start_date = start_time.isoformat()
    end_date = end_time.isoformat()

    # The disk-usage endpoint refuses a request without `device` or `partition`, and
    # both filters take record ids from /api/proc/, never device names.
    partitions_result, interfaces_result = await asyncio.gather(
        http_client.get(
            region=region,
            workspace=workspace,
            endpoint='/api/proc/partitions/',
            token=token,
            params={'server': server_id},
        ),
        _list_all_interfaces(
            region=region,
            workspace=workspace,
            token=token,
            server_id=server_id,
        ),
    )

    def is_root(p):
        return '/' in (p.get('mount_points') or [])

    root_partition_id = _find_record_id(
        partitions_result, lambda p: is_root(p) and not p.get('is_virtual', False)
    ) or _find_record_id(partitions_result, is_root)

    def is_active(i):
        return not i.get('is_loopback', False) and i.get('is_up', False)

    interface_id = _find_record_id(
        interfaces_result,
        lambda i: (
            is_active(i)
            and not str(i.get('name', '')).startswith(_VIRTUAL_INTERFACE_PREFIXES)
        ),
    ) or _find_record_id(interfaces_result, is_active)

    window = {'server': server_id, 'start': start_date, 'end': end_date}
    tasks = {
        'cpu': http_client.get(
            region, workspace, '/api/metrics/realtime/cpu/', token, params=window
        ),
        'memory': http_client.get(
            region, workspace, '/api/metrics/realtime/memory/', token, params=window
        ),
    }
    if root_partition_id:
        tasks['disk'] = http_client.get(
            region,
            workspace,
            '/api/metrics/realtime/disk-usage/',
            token,
            params={**window, 'partition': root_partition_id},
        )
    if interface_id:
        tasks['network'] = http_client.get(
            region,
            workspace,
            '/api/metrics/realtime/traffic/',
            token,
            params={**window, 'interface': interface_id},
        )

    # Wait for all metrics
    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)

    # Re-raise BaseExceptions that are not regular Exceptions (e.g. CancelledError)
    for r in gathered:
        if isinstance(r, BaseException) and not isinstance(r, Exception):
            raise r

    metric_results = dict(zip(tasks, gathered, strict=True))

    # Helper function to extract summary from metric result (from http_client directly)
    def extract_summary(result, metric_type):
        # Handle exceptions first
        if isinstance(result, Exception):
            return {'available': False, 'error': str(result)}

        # http_client returns data directly (not wrapped in success/status)
        if isinstance(result, dict):
            # Check for HTTP error
            if 'error' in result:
                # Extract actual error message from response if available
                if 'response' in result:
                    error_info = {
                        'available': False,
                        'error': f'{result.get("message", "Error")} - {result.get("response", "")}',
                    }
                else:
                    error_info = {
                        'available': False,
                        'error': result.get('message', 'Data unavailable'),
                    }
                status_code = result.get('status_code')
                if status_code is not None:
                    error_info['status_code'] = status_code
                return error_info

            # Return metadata only, not the full data points
            if 'results' in result:
                return {
                    'available': True,
                    'data_points': len(result.get('results', [])),
                    'note': f'Full {metric_type} data available via dedicated endpoint',
                }

            # If no results and no error, might be empty data
            return {'available': False, 'error': 'No data available'}

        # Handle list results (API may return empty list when no data)
        if isinstance(result, list):
            if result:
                return {
                    'available': True,
                    'data_points': len(result),
                    'note': f'Full {metric_type} data available via dedicated endpoint',
                }
            # Empty list means no metrics data available
            return {
                'available': False,
                'error': 'No metrics data available (empty response)',
            }

        return {
            'available': False,
            'error': f'Unexpected result type: {type(result).__name__}',
        }

    if root_partition_id:
        disk_summary = extract_summary(metric_results['disk'], 'disk')
    elif _is_http_error(partitions_result):
        disk_summary = extract_summary(partitions_result, 'partition lookup')
        disk_summary['error'] = f'Partition lookup failed: {disk_summary["error"]}'
    else:
        disk_summary = {
            'available': False,
            'error': 'No partition mounted at / was found for this server',
        }

    if interface_id:
        network_summary = extract_summary(metric_results['network'], 'network')
    elif _is_http_error(interfaces_result):
        network_summary = extract_summary(interfaces_result, 'interface lookup')
        network_summary['error'] = (
            f'Interface lookup failed: {network_summary["error"]}'
        )
    else:
        network_summary = {
            'available': False,
            'error': 'No active non-loopback interface was found',
        }

    summary = {
        'server_id': server_id,
        'time_range': {'start': start_date, 'end': end_date, 'hours': hours},
        'metrics': {
            'cpu': extract_summary(metric_results['cpu'], 'CPU'),
            'memory': extract_summary(metric_results['memory'], 'memory'),
            'disk': disk_summary,
            'network': network_summary,
        },
        'note': 'This is a summary. Use individual metric endpoints for full data.',
        'region': region,
        'workspace': workspace,
    }

    return success_response(data=summary)


@mcp_tool_handler(
    description=(
        'Latest CPU, memory, disk usage, disk I/O and network reading for many '
        'servers in one request; each cell says whether the value is missing, '
        "stale or not collected. For one server's time series use get_cpu_usage "
        "etc.; for one server's detail use get_server_metrics_summary. Requires "
        'alpacon-server 2.37.0 or later.'
    ),
    annotations=READ_ONLY,
    meta={
        'anthropic/searchHint': 'latest metrics many servers fleet overview cpu memory disk network stale summary'
    },
)
async def list_latest_metrics(
    workspace: str,
    region: str = '',
    search: str | None = None,
    groups: str | None = None,
    tag: str | None = None,
    is_connected: bool | None = None,
    state: str | None = None,
    ordering: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get the latest metric reading for every server in a workspace, a page at a time.

    Requires alpacon-server 2.37.0 or later. It is the servers list with five
    metric cells added: the filters, search, and pagination are `list_servers`'
    own, plus `state` and `ordering`.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1). Auto-detected if not provided
        search: Free-text search across server name, version, owner, and group name (optional)
        groups: Filter by group ID(s) (optional)
        tag: Filter by tag(s) in "key:value" form (optional)
        is_connected: Filter by live agent connection state (optional)
        state: Filter by staleness: "stale" (some family is overdue, including a
            server storing nothing at all) or "no_data" (nothing stored for any
            family). "stale" is the wider set and includes every "no_data"
            server. (optional)
        ordering: Sort field, one of VALID_LATEST_METRIC_ORDERING_FIELDS
            (name, starred, sampled_at, cpu, memory, disk_usage/disk-usage,
            disk_io/disk-io, net), optionally prefixed with "-" for descending.
            A server with no value for the field sorts last. (optional)
        page: Page number for pagination (optional)
        page_size: Number of results per page, up to 100 (optional)

    Returns:
        Paginated response: `count`, `current`, `next`, `previous`, `last`, and
        `results` — each result an `{id, name, is_connected, cpu, memory,
        "disk-usage", "disk-io", net}` row, every metric cell an object with
        `value`, `unit` ("percent" or "bytes_per_sec"), `sampled_at`, `device`,
        `collected`, `reason`, and `interval_s` (`value`, `sampled_at`, and
        `device` are null when no sample is stored for that family).
    """
    if state is not None and state not in VALID_LATEST_METRIC_STATES:
        return format_validation_error('state', state, _LATEST_STATE_SENTENCE)

    if ordering is not None:
        base = ordering[1:] if ordering.startswith('-') else ordering
        if base not in VALID_LATEST_METRIC_ORDERING_FIELDS:
            return format_validation_error(
                'ordering', ordering, _LATEST_ORDERING_SENTENCE
            )

    token = kwargs.get('token')

    params = build_list_params(
        page=page,
        page_size=page_size,
        search=search,
        groups=groups,
        tag=tag,
        is_connected=is_connected,
        state=state,
        ordering=ordering,
    )

    return await http_call_response(
        http_client.get,
        region=region,
        workspace=workspace,
        endpoint='/api/metrics/latest/',
        token=token,
        default_message='Failed to list latest metrics',
        params=params,
    )
