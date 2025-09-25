"""Metrics and monitoring tools for Alpacon MCP server."""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="Get server CPU usage metrics")
async def get_cpu_usage(
    server_id: str,
    workspace: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get CPU usage metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        CPU usage metrics response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "metric_type": "cpu_usage",
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get CPU usage: {str(e)}"
        }


@mcp.tool(description="Get server memory usage metrics")
async def get_memory_usage(
    server_id: str,
    workspace: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get memory usage metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Memory usage metrics response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "metric_type": "memory_usage",
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get memory usage: {str(e)}"
        }


@mcp.tool(description="Get server disk usage metrics")
async def get_disk_usage(
    server_id: str,
    workspace: str,
    device: Optional[str] = None,
    partition: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get disk usage metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        device: Optional device path (e.g., '/dev/sda1')
        partition: Optional partition path (e.g., '/')
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Disk usage metrics response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "metric_type": "disk_usage",
            "device": device,
            "partition": partition,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get disk usage: {str(e)}"
        }


@mcp.tool(description="Get server network traffic metrics")
async def get_network_traffic(
    server_id: str,
    workspace: str,
    interface: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get network traffic metrics for a server.

    Args:
        server_id: Server ID to get metrics for
        interface: Optional network interface (e.g., 'eth0')
        start_date: Start date in ISO format (e.g., '2024-01-01T00:00:00Z')
        end_date: End date in ISO format (e.g., '2024-01-02T00:00:00Z')
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Network traffic metrics response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "metric_type": "network_traffic",
            "interface": interface,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get network traffic: {str(e)}"
        }


@mcp.tool(description="Get top performing servers by CPU usage")
async def get_cpu_top_servers(
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get top 5 servers by CPU usage in the last 24 hours.

    Args:
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Top CPU usage servers response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get top CPU servers
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/metrics/realtime/cpu/top/",
            token=token
        )

        return {
            "status": "success",
            "data": result,
            "metric_type": "cpu_top",
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get top CPU servers: {str(e)}"
        }


@mcp.tool(description="Get alert rules")
async def get_alert_rules(
    workspace: str,
    server_id: Optional[str] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get alert rules for servers.

    Args:
        server_id: Optional server ID to filter rules
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Alert rules response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

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

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get alert rules: {str(e)}"
        }


@mcp.tool(description="Get server metrics summary")
async def get_server_metrics_summary(
    server_id: str,
    workspace: str,
    hours: int = 24,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get comprehensive metrics summary for a server.

    Args:
        server_id: Server ID to get metrics for
        hours: Number of hours back to get metrics (default: 24)
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Comprehensive server metrics summary
    """
    try:
        import asyncio
        from datetime import datetime, timedelta, timezone

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        start_date = start_time.isoformat()
        end_date = end_time.isoformat()

        # Get all metrics concurrently
        cpu_task = get_cpu_usage(server_id, start_date, end_date, region, workspace)
        memory_task = get_memory_usage(server_id, start_date, end_date, region, workspace)
        disk_task = get_disk_usage(server_id, None, None, start_date, end_date, region, workspace)
        traffic_task = get_network_traffic(server_id, None, start_date, end_date, region, workspace)

        # Wait for all metrics
        cpu_result, memory_result, disk_result, traffic_result = await asyncio.gather(
            cpu_task, memory_task, disk_task, traffic_task,
            return_exceptions=True
        )

        # Prepare summary
        summary = {
            "server_id": server_id,
            "time_range": {
                "start": start_date,
                "end": end_date,
                "hours": hours
            },
            "metrics": {},
            "region": region,
            "workspace": workspace
        }

        # Add CPU metrics if successful
        if isinstance(cpu_result, dict) and cpu_result.get("status") == "success":
            summary["metrics"]["cpu"] = cpu_result["data"]
        else:
            summary["metrics"]["cpu"] = {"error": str(cpu_result) if isinstance(cpu_result, Exception) else cpu_result.get("message", "Unknown error")}

        # Add memory metrics if successful
        if isinstance(memory_result, dict) and memory_result.get("status") == "success":
            summary["metrics"]["memory"] = memory_result["data"]
        else:
            summary["metrics"]["memory"] = {"error": str(memory_result) if isinstance(memory_result, Exception) else memory_result.get("message", "Unknown error")}

        # Add disk metrics if successful
        if isinstance(disk_result, dict) and disk_result.get("status") == "success":
            summary["metrics"]["disk"] = disk_result["data"]
        else:
            summary["metrics"]["disk"] = {"error": str(disk_result) if isinstance(disk_result, Exception) else disk_result.get("message", "Unknown error")}

        # Add traffic metrics if successful
        if isinstance(traffic_result, dict) and traffic_result.get("status") == "success":
            summary["metrics"]["network"] = traffic_result["data"]
        else:
            summary["metrics"]["network"] = {"error": str(traffic_result) if isinstance(traffic_result, Exception) else traffic_result.get("message", "Unknown error")}

        return {
            "status": "success",
            "data": summary
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get server metrics summary: {str(e)}"
        }
