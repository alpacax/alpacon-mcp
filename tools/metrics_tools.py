"""Metrics and monitoring tools for Alpacon MCP server."""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import asyncio
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler


def parse_cpu_metrics(results: list) -> Dict[str, Any]:
    """Parse CPU usage metrics to extract meaningful statistics.

    Args:
        results: List of CPU usage data points

    Returns:
        Parsed statistics including average, min, max, current usage
    """
    if not results or len(results) == 0:
        return {"available": False, "message": "No CPU data available"}

    usage_values = [entry.get('usage', 0) for entry in results if 'usage' in entry]

    if not usage_values:
        return {"available": False, "message": "No usage values found"}

    return {
        "available": True,
        "current_usage": usage_values[-1],
        "average_usage": round(sum(usage_values) / len(usage_values), 2),
        "min_usage": min(usage_values),
        "max_usage": max(usage_values),
        "data_points": len(usage_values),
        "time_range": {
            "start": results[0].get('timestamp') if results else None,
            "end": results[-1].get('timestamp') if results else None
        }
    }


@mcp_tool_handler(description="Get server CPU usage metrics")
async def get_cpu_usage(
    server_id: str,
    workspace: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get CPU usage metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        CPU usage metrics with parsed statistics (current, average, min, max)
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {"server": server_id}
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    # Make async call to get CPU metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/metrics/realtime/cpu/",
        token=token,
        params=params
    )

    # Parse metrics for better readability
    parsed_data = {
        "server_id": server_id,
        "metric_type": "cpu_usage",
        "statistics": parse_cpu_metrics(result.get('results', [])) if isinstance(result, dict) else parse_cpu_metrics(result if isinstance(result, list) else []),
        "raw_data_available": True
    }

    return success_response(
        data=parsed_data,
        region=region,
        workspace=workspace
    )


def parse_memory_metrics(results: list) -> Dict[str, Any]:
    """Parse memory usage metrics to extract meaningful statistics.

    Args:
        results: List of memory usage data points

    Returns:
        Parsed statistics including average, min, max, current usage
    """
    if not results or len(results) == 0:
        return {"available": False, "message": "No memory data available"}

    usage_values = [entry.get('usage', 0) for entry in results if 'usage' in entry]

    if not usage_values:
        return {"available": False, "message": "No usage values found"}

    return {
        "available": True,
        "current_usage": usage_values[-1],
        "average_usage": round(sum(usage_values) / len(usage_values), 2),
        "min_usage": min(usage_values),
        "max_usage": max(usage_values),
        "data_points": len(usage_values),
        "time_range": {
            "start": results[0].get('timestamp') if results else None,
            "end": results[-1].get('timestamp') if results else None
        }
    }


@mcp_tool_handler(description="Get server memory usage metrics")
async def get_memory_usage(
    server_id: str,
    workspace: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get memory usage metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Memory usage metrics with parsed statistics (current, average, min, max)
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {"server": server_id}
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    # Make async call to get memory metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/metrics/realtime/memory/",
        token=token,
        params=params
    )

    # Parse metrics for better readability
    parsed_data = {
        "server_id": server_id,
        "metric_type": "memory_usage",
        "statistics": parse_memory_metrics(result.get('results', [])) if isinstance(result, dict) else parse_memory_metrics(result if isinstance(result, list) else []),
        "raw_data_available": True
    }

    return success_response(
        data=parsed_data,
        region=region,
        workspace=workspace
    )


def parse_disk_metrics(results: list) -> Dict[str, Any]:
    """Parse disk usage metrics to extract meaningful statistics.

    Args:
        results: List of disk usage data points

    Returns:
        Parsed statistics including average, min, max, current usage and space info
    """
    if not results or len(results) == 0:
        return {"available": False, "message": "No disk data available"}

    usage_values = [entry.get('usage', 0) for entry in results if 'usage' in entry]

    if not usage_values:
        return {"available": False, "message": "No usage values found"}

    # Get space information from the latest entry
    latest_entry = results[-1]
    total_bytes = latest_entry.get('total', 0)
    used_bytes = latest_entry.get('used', 0)
    free_bytes = latest_entry.get('free', 0)

    # Convert bytes to human-readable format
    def bytes_to_human(bytes_value):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"

    return {
        "available": True,
        "current_usage": usage_values[-1],
        "average_usage": round(sum(usage_values) / len(usage_values), 2),
        "min_usage": min(usage_values),
        "max_usage": max(usage_values),
        "space_info": {
            "total": bytes_to_human(total_bytes),
            "used": bytes_to_human(used_bytes),
            "free": bytes_to_human(free_bytes),
            "device": latest_entry.get('device'),
            "mount_point": latest_entry.get('mount_point')
        },
        "data_points": len(usage_values),
        "time_range": {
            "start": results[0].get('timestamp') if results else None,
            "end": results[-1].get('timestamp') if results else None
        }
    }


@mcp_tool_handler(description="Get server disk usage metrics")
async def get_disk_usage(
    server_id: str,
    workspace: str,
    device: Optional[str] = None,
    partition: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get disk usage metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        device: Optional device path (e.g., '/dev/sda1')
        partition: Optional partition path (e.g., '/')
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Disk usage metrics with parsed statistics (current, average, min, max, space info)
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {"server": server_id}
    if device:
        params["device"] = device
    if partition:
        params["partition"] = partition
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    # Make async call to get disk metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/metrics/realtime/disk-usage/",
        token=token,
        params=params
    )

    # Parse metrics for better readability
    parsed_data = {
        "server_id": server_id,
        "metric_type": "disk_usage",
        "device": device,
        "partition": partition,
        "statistics": parse_disk_metrics(result.get('results', [])) if isinstance(result, dict) else parse_disk_metrics(result if isinstance(result, list) else []),
        "raw_data_available": True
    }

    return success_response(
        data=parsed_data,
        region=region,
        workspace=workspace
    )


def parse_network_metrics(results: list) -> Dict[str, Any]:
    """Parse network traffic metrics to extract meaningful statistics.

    Args:
        results: List of network traffic data points

    Returns:
        Parsed statistics including average, peak input/output in bps and pps
    """
    if not results or len(results) == 0:
        return {"available": False, "message": "No network data available"}

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
                return f"{bps_value:.2f} {unit}"
            bps_value /= 1024.0
        return f"{bps_value:.2f} Tbps"

    latest_entry = results[-1]

    return {
        "available": True,
        "interface": latest_entry.get('interface'),
        "current": {
            "peak_input_bps": bps_to_human(peak_input_bps[-1]) if peak_input_bps else "0 bps",
            "peak_output_bps": bps_to_human(peak_output_bps[-1]) if peak_output_bps else "0 bps",
            "avg_input_bps": bps_to_human(avg_input_bps[-1]) if avg_input_bps else "0 bps",
            "avg_output_bps": bps_to_human(avg_output_bps[-1]) if avg_output_bps else "0 bps",
            "peak_input_pps": f"{peak_input_pps[-1]:.2f} pps" if peak_input_pps else "0 pps",
            "peak_output_pps": f"{peak_output_pps[-1]:.2f} pps" if peak_output_pps else "0 pps"
        },
        "averages": {
            "peak_input_bps": bps_to_human(sum(peak_input_bps) / len(peak_input_bps)) if peak_input_bps else "0 bps",
            "peak_output_bps": bps_to_human(sum(peak_output_bps) / len(peak_output_bps)) if peak_output_bps else "0 bps",
            "avg_input_bps": bps_to_human(sum(avg_input_bps) / len(avg_input_bps)) if avg_input_bps else "0 bps",
            "avg_output_bps": bps_to_human(sum(avg_output_bps) / len(avg_output_bps)) if avg_output_bps else "0 bps"
        },
        "peaks": {
            "max_input_bps": bps_to_human(max(peak_input_bps)) if peak_input_bps else "0 bps",
            "max_output_bps": bps_to_human(max(peak_output_bps)) if peak_output_bps else "0 bps",
            "max_input_pps": f"{max(peak_input_pps):.2f} pps" if peak_input_pps else "0 pps",
            "max_output_pps": f"{max(peak_output_pps):.2f} pps" if peak_output_pps else "0 pps"
        },
        "data_points": len(results),
        "time_range": {
            "start": results[0].get('timestamp') if results else None,
            "end": results[-1].get('timestamp') if results else None
        }
    }


@mcp_tool_handler(description="Get server network traffic metrics")
async def get_network_traffic(
    server_id: str,
    workspace: str,
    interface: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get network traffic metrics for a server with parsed statistics.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        interface: Optional network interface (e.g., 'eth0')
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Network traffic metrics with parsed statistics (current, averages, peaks for bps/pps)
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {"server": server_id}
    if interface:
        params["interface"] = interface
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    # Make async call to get traffic metrics
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/metrics/realtime/traffic/",
        token=token,
        params=params
    )

    # Parse metrics for better readability
    parsed_data = {
        "server_id": server_id,
        "metric_type": "network_traffic",
        "interface": interface,
        "statistics": parse_network_metrics(result.get('results', [])) if isinstance(result, dict) else parse_network_metrics(result if isinstance(result, list) else []),
        "raw_data_available": True
    }

    return success_response(
        data=parsed_data,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get top performing servers by CPU usage")
async def get_top_cpu_servers(
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get top 5 servers by CPU usage in the last 24 hours.

    Args:
        workspace: Workspace name. Required parameter
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Top CPU usage servers response
    """
    token = kwargs.get('token')

    # Make async call to get top CPU servers
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/metrics/realtime/cpu/top/",
        token=token
    )

    return success_response(
        data=result,
        metric_type="cpu_top",
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get alert rules")
async def get_alert_rules(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get alert rules for servers.

    Args:
        workspace: Workspace name. Required parameter
        server_id: Optional server ID to filter rules
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Alert rules response
    """
    token = kwargs.get('token')

    # Prepare query parameters
    params = {}
    if server_id:
        params["server"] = server_id

    # Make async call to get alert rules
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/metrics/alert-rules/",
        token=token,
        params=params
    )

    return success_response(
        data=result,
        server_id=server_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get server metrics summary")
async def get_server_metrics_summary(
    server_id: str,
    workspace: str,
    hours: int = 24,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get comprehensive metrics summary for a server.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        hours: Number of hours back to get metrics (default: 24, max: 168)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Comprehensive server metrics summary (limited size response)
    """
    token = kwargs.get('token')

    # Limit hours to prevent response size overflow
    if hours > 168:  # Max 1 week
        hours = 168

    # Calculate time range
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    start_date = start_time.isoformat()
    end_date = end_time.isoformat()

    # Prepare query parameters
    cpu_params = {"server": server_id, "start": start_date, "end": end_date}
    memory_params = {"server": server_id, "start": start_date, "end": end_date}
    disk_params = {"server": server_id, "start": start_date, "end": end_date}
    traffic_params = {"server": server_id, "start": start_date, "end": end_date}

    # Get all metrics concurrently using http_client directly
    cpu_task = http_client.get(region, workspace, "/api/metrics/realtime/cpu/", token, params=cpu_params)
    memory_task = http_client.get(region, workspace, "/api/metrics/realtime/memory/", token, params=memory_params)
    disk_task = http_client.get(region, workspace, "/api/metrics/realtime/disk-usage/", token, params=disk_params)
    traffic_task = http_client.get(region, workspace, "/api/metrics/realtime/traffic/", token, params=traffic_params)

    # Wait for all metrics
    cpu_result, memory_result, disk_result, traffic_result = await asyncio.gather(
        cpu_task, memory_task, disk_task, traffic_task,
        return_exceptions=True
    )

    # Helper function to extract summary from metric result (from http_client directly)
    def extract_summary(result, metric_type):
        # Handle exceptions first
        if isinstance(result, Exception):
            return {"available": False, "error": str(result)}

        # http_client returns data directly (not wrapped in success/status)
        if isinstance(result, dict):
            # Check for HTTP error
            if "error" in result:
                # Extract actual error message from response if available
                if "response" in result:
                    return {"available": False, "error": f"{result.get('message', 'Error')} - {result.get('response', '')}"}
                return {"available": False, "error": result.get("message", "Data unavailable")}

            # Return metadata only, not the full data points
            if "results" in result:
                return {
                    "available": True,
                    "data_points": len(result.get("results", [])),
                    "note": f"Full {metric_type} data available via dedicated endpoint"
                }

            # If no results and no error, might be empty data
            return {"available": False, "error": "No data available"}

        # Handle list results (API may return empty list when no data)
        if isinstance(result, list):
            if len(result) > 0:
                return {
                    "available": True,
                    "data_points": len(result),
                    "note": f"Full {metric_type} data available via dedicated endpoint"
                }
            # Empty list means no metrics data available
            return {"available": False, "error": "No metrics data available (empty response)"}

        return {"available": False, "error": f"Unexpected result type: {type(result).__name__}"}

    # Prepare compact summary
    summary = {
        "server_id": server_id,
        "time_range": {
            "start": start_date,
            "end": end_date,
            "hours": hours
        },
        "metrics": {
            "cpu": extract_summary(cpu_result, "CPU"),
            "memory": extract_summary(memory_result, "memory"),
            "disk": extract_summary(disk_result, "disk"),
            "network": extract_summary(traffic_result, "network")
        },
        "note": "This is a summary. Use individual metric endpoints for full data.",
        "region": region,
        "workspace": workspace
    }

    return success_response(data=summary)
