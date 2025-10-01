"""Metrics and monitoring tools for Alpacon MCP server."""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import asyncio
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler


@mcp_tool_handler(description="Get server CPU usage metrics")
async def get_cpu_usage(
    server_id: str,
    workspace: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get CPU usage metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        CPU usage metrics response
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

    return success_response(
        data=result,
        server_id=server_id,
        metric_type="cpu_usage",
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get server memory usage metrics")
async def get_memory_usage(
    server_id: str,
    workspace: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get memory usage metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Memory usage metrics response
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

    return success_response(
        data=result,
        server_id=server_id,
        metric_type="memory_usage",
        region=region,
        workspace=workspace
    )


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
    """Get disk usage metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        device: Optional device path (e.g., '/dev/sda1')
        partition: Optional partition path (e.g., '/')
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Disk usage metrics response
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

    return success_response(
        data=result,
        server_id=server_id,
        metric_type="disk_usage",
        device=device,
        partition=partition,
        region=region,
        workspace=workspace
    )


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
    """Get network traffic metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        workspace: Workspace name. Required parameter
        interface: Optional network interface (e.g., 'eth0')
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'

    Returns:
        Network traffic metrics response
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

    return success_response(
        data=result,
        server_id=server_id,
        metric_type="network_traffic",
        interface=interface,
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
    # Limit hours to prevent response size overflow
    if hours > 168:  # Max 1 week
        hours = 168

    # Calculate time range
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    start_date = start_time.isoformat()
    end_date = end_time.isoformat()

    # Get all metrics concurrently
    cpu_task = get_cpu_usage(server_id, workspace, start_date, end_date, region, **kwargs)
    memory_task = get_memory_usage(server_id, workspace, start_date, end_date, region, **kwargs)
    disk_task = get_disk_usage(server_id, workspace, None, None, start_date, end_date, region, **kwargs)
    traffic_task = get_network_traffic(server_id, workspace, None, start_date, end_date, region, **kwargs)

    # Wait for all metrics
    cpu_result, memory_result, disk_result, traffic_result = await asyncio.gather(
        cpu_task, memory_task, disk_task, traffic_task,
        return_exceptions=True
    )

    # Helper function to extract summary from metric result
    def extract_summary(result, metric_type):
        if isinstance(result, dict) and result.get("status") == "success":
            data = result.get("data", {})
            # Return only summary info, not full data arrays
            if isinstance(data, dict):
                if "error" in data:
                    # Extract actual error message from response if available
                    if "response" in data:
                        return {"available": False, "error": f"{data.get('message', 'Error')} - {data.get('response', '')}"}
                    return {"available": False, "error": data.get("message", "Data unavailable")}
                # Return metadata only, not the full data points
                if "results" in data:
                    return {
                        "available": True,
                        "data_points": len(data.get("results", [])),
                        "note": f"Full {metric_type} data available via dedicated endpoint"
                    }
                # If no results but no error, might be empty data
                return {"available": False, "error": "No data available"}
            return {"available": False, "error": "Unexpected data format"}
        else:
            error_msg = str(result) if isinstance(result, Exception) else result.get("message", "Unknown error")
            return {"available": False, "error": error_msg}

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
