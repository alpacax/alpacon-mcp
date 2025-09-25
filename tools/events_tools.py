"""Event management tools for Alpacon MCP server."""

from typing import Dict, Any, Optional, List
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()


@mcp.tool(description="List server events")
async def list_events(
    workspace: str,
    server_id: Optional[str] = None,
    reporter: Optional[str] = None,
    limit: int = 50,
    region: str = "ap1"
) -> Dict[str, Any]:
    """List events from servers.

    Args:
        server_id: Optional server ID to filter events
        reporter: Optional reporter name to filter events
        limit: Maximum number of events to return. Defaults to 50
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Events list response
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
        params = {
            "page_size": limit,
            "ordering": "-added_at"
        }

        if server_id:
            params["server"] = server_id
        if reporter:
            params["reporter"] = reporter

        # Make async call to list events
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/events/events/",
            token=token,
            params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "reporter": reporter,
            "limit": limit,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list events: {str(e)}"
        }


@mcp.tool(description="Get event details by ID")
async def get_event(
    event_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get detailed information about a specific event.

    Args:
        event_id: Event ID to get details for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Event details response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get event details
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/events/events/{event_id}/",
            token=token
        )

        return {
            "status": "success",
            "data": result,
            "event_id": event_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get event: {str(e)}"
        }


@mcp.tool(description="Acknowledge command execution")
async def acknowledge_command(
    command_id: str,
    workspace: str,
    success: bool = True,
    result: Optional[str] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Acknowledge that a command has been received and started.

    Args:
        command_id: Command ID to acknowledge
        success: Whether command started successfully. Defaults to True
        result: Optional result message
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Acknowledgment response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare acknowledgment data
        ack_data = {
            "success": success
        }

        if result:
            ack_data["result"] = result

        # Make async call to acknowledge command
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint=f"/api/events/commands/{command_id}/ack/",
            token=token,
            data=ack_data
        )

        return {
            "status": "success",
            "data": result,
            "command_id": command_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to acknowledge command: {str(e)}"
        }


@mcp.tool(description="Mark command as finished")
async def finish_command(
    command_id: str,
    workspace: str,
    success: bool = True,
    result: Optional[str] = None,
    elapsed_time: Optional[float] = None,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Mark a command as finished with results.

    Args:
        command_id: Command ID to mark as finished
        success: Whether command completed successfully. Defaults to True
        result: Optional result output or error message
        elapsed_time: Optional execution time in seconds
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Finish response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare finish data
        finish_data = {
            "success": success
        }

        if result:
            finish_data["result"] = result
        if elapsed_time is not None:
            finish_data["elapsed_time"] = elapsed_time

        # Make async call to finish command
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint=f"/api/events/commands/{command_id}/fin/",
            token=token,
            data=finish_data
        )

        return {
            "status": "success",
            "data": result,
            "command_id": command_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to finish command: {str(e)}"
        }


@mcp.tool(description="Get command execution status and history")
async def get_command_status(
    command_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Get detailed status and execution information for a command.

    Args:
        command_id: Command ID to get status for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Command status response with detailed execution info
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get command status
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint=f"/api/events/commands/{command_id}/",
            token=token
        )

        return {
            "status": "success",
            "data": result,
            "command_id": command_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get command status: {str(e)}"
        }


@mcp.tool(description="Delete a scheduled command")
async def delete_command(
    command_id: str,
    workspace: str,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Delete a scheduled command that hasn't been delivered yet.

    Args:
        command_id: Command ID to delete
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Deletion response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to delete command
        result = await http_client.delete(
            region=region,
            workspace=workspace,
            endpoint=f"/api/events/commands/{command_id}/",
            token=token
        )

        return {
            "status": "success",
            "data": result,
            "command_id": command_id,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete command: {str(e)}"
        }


@mcp.tool(description="Search events by criteria")
async def search_events(
    search_query: str,
    workspace: str,
    server_id: Optional[str] = None,
    limit: int = 20,
    region: str = "ap1"
) -> Dict[str, Any]:
    """Search events by server name, reporter, record, or description.

    Args:
        search_query: Search term to look for in events
        server_id: Optional server ID to limit search scope
        limit: Maximum number of results to return. Defaults to 20
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Search results response
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
        params = {
            "search": search_query,
            "page_size": limit,
            "ordering": "-added_at"
        }

        if server_id:
            params["server"] = server_id

        # Make async call to search events
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/events/events/",
            token=token,
            params=params
        )

        return {
            "status": "success",
            "data": result,
            "search_query": search_query,
            "server_id": server_id,
            "limit": limit,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to search events: {str(e)}"
        }