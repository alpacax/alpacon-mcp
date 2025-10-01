"""Event management tools for Alpacon MCP server - Refactored version."""

from typing import Dict, Any, Optional
from utils.http_client import http_client
from utils.common import success_response
from utils.decorators import mcp_tool_handler


@mcp_tool_handler(description="List server events")
async def list_events(
    workspace: str,
    server_id: Optional[str] = None,
    reporter: Optional[str] = None,
    limit: int = 50,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """List events from servers."""
    token = kwargs.get('token')
    
    params = {
        "page_size": limit,
        "ordering": "-added_at"
    }
    
    if server_id:
        params["server"] = server_id
    if reporter:
        params["reporter"] = reporter
    
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/events/events/",
        token=token,
        params=params
    )
    
    return success_response(
        data=result,
        server_id=server_id,
        reporter=reporter,
        limit=limit,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get event details by ID")
async def get_event(
    event_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get detailed information about a specific event."""
    token = kwargs.get('token')
    
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f"/api/events/events/{event_id}/",
        token=token
    )
    
    return success_response(
        data=result,
        event_id=event_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Acknowledge command execution")
async def acknowledge_command(
    command_id: str,
    workspace: str,
    success: bool = True,
    result: Optional[str] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Acknowledge that a command has been received and started."""
    token = kwargs.get('token')
    
    ack_data = {"success": success}
    if result:
        ack_data["result"] = result
    
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f"/api/events/commands/{command_id}/ack/",
        token=token,
        data=ack_data
    )
    
    return success_response(
        data=result,
        command_id=command_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Mark command as finished")
async def finish_command(
    command_id: str,
    workspace: str,
    success: bool = True,
    result: Optional[str] = None,
    elapsed_time: Optional[float] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Mark a command as finished with results."""
    token = kwargs.get('token')
    
    finish_data = {"success": success}
    if result:
        finish_data["result"] = result
    if elapsed_time is not None:
        finish_data["elapsed_time"] = elapsed_time
    
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f"/api/events/commands/{command_id}/fin/",
        token=token,
        data=finish_data
    )
    
    return success_response(
        data=result,
        command_id=command_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get command execution status and history")
async def get_command_status(
    command_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get detailed status and execution information for a command."""
    token = kwargs.get('token')
    
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f"/api/events/commands/{command_id}/",
        token=token
    )
    
    return success_response(
        data=result,
        command_id=command_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Delete a scheduled command")
async def delete_command(
    command_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Delete a scheduled command that hasn't been delivered yet."""
    token = kwargs.get('token')
    
    result = await http_client.delete(
        region=region,
        workspace=workspace,
        endpoint=f"/api/events/commands/{command_id}/",
        token=token
    )
    
    return success_response(
        data=result,
        command_id=command_id,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Search events by criteria")
async def search_events(
    search_query: str,
    workspace: str,
    server_id: Optional[str] = None,
    limit: int = 20,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Search events by server name, reporter, record, or description."""
    token = kwargs.get('token')
    
    params = {
        "search": search_query,
        "page_size": limit,
        "ordering": "-added_at"
    }
    
    if server_id:
        params["server"] = server_id
    
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/events/events/",
        token=token,
        params=params
    )
    
    return success_response(
        data=result,
        search_query=search_query,
        server_id=server_id,
        limit=limit,
        region=region,
        workspace=workspace
    )
