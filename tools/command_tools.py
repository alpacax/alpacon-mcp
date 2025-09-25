"""Command execution tools for Alpacon MCP server."""

import asyncio
from typing import Dict, Any, Optional
from server import mcp
from utils.http_client import http_client
from utils.token_manager import get_token_manager

# Initialize token manager
token_manager = get_token_manager()



@mcp.tool(description="Execute a command on a server")
async def execute_command(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = "internal",
    username: Optional[str] = None,
    groupname: str = "alpacon",
    env: Optional[Dict[str, str]] = None,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Execute a command on a specified server.

    Args:
        server_id: Server ID to execute command on
        command: Command line to execute
        shell: Shell type (internal, bash, sh, etc.). Defaults to 'internal'
        username: Optional username for the command execution
        groupname: Group name for the command execution. Defaults to 'alpacon'
        env: Optional environment variables as key-value pairs
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Command execution response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Prepare command data
        command_data = {
            "server": server_id,
            "shell": shell,
            "line": command,
            "groupname": groupname
        }

        # Add optional fields if provided
        if username:
            command_data["username"] = username

        if env:
            command_data["env"] = env

        # Make async call to execute command
        result = await http_client.post(
            region=region,
            workspace=workspace,
            endpoint="/api/events/commands/",
            token=token,
            data=command_data
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "command": command,
            "shell": shell,
            "username": username or "auto",
            "groupname": groupname,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to execute command: {str(e)}"
        }


@mcp.tool(description="Get command execution result by command ID")
async def get_command_result(
    command_id: str,
    workspace: str,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Get the result of a previously executed command.

    Args:
        command_id: Command ID to get result for
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Command result response
    """
    try:
        # Get stored token
        token = token_manager.get_token(region, workspace)
        if not token:
            return {
                "status": "error",
                "message": f"No token found for {workspace}.{region}. Please set token first."
            }

        # Make async call to get command result
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
            "message": f"Failed to get command result: {str(e)}"
        }


@mcp.tool(description="List recent commands executed on servers")
async def list_commands(
    workspace: str,
    server_id: Optional[str] = None,
    limit: int = 20,
    region: str = "ap1",
) -> Dict[str, Any]:
    """List recent commands executed on servers.

    Args:
        server_id: Optional server ID to filter commands
        limit: Maximum number of commands to return. Defaults to 20
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Commands list response
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

        # Make async call to list commands
        result = await http_client.get(
            region=region,
            workspace=workspace,
            endpoint="/api/events/commands/",
            token=token,
            params=params
        )

        return {
            "status": "success",
            "data": result,
            "server_id": server_id,
            "limit": limit,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list commands: {str(e)}"
        }


@mcp.tool(description="Execute a command and wait for result")
async def execute_command_sync(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = "bash",
    username: Optional[str] = None,
    groupname: str = "alpacon",
    env: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    region: str = "ap1",
) -> Dict[str, Any]:
    """Execute a command and wait for the result (synchronous execution).

    Args:
        server_id: Server ID to execute command on
        command: Command line to execute
        shell: Shell type (bash, sh, internal, etc.). Defaults to 'bash'
        username: Optional username for the command execution
        groupname: Group name for the command execution. Defaults to 'alpacon'
        env: Optional environment variables as key-value pairs
        timeout: Timeout in seconds to wait for result. Defaults to 30
        region: Region (ap1, us1, eu1, etc.). Defaults to 'ap1'
        workspace: Workspace name. Required parameter

    Returns:
        Command execution result
    """
    try:
        # First, execute the command
        exec_result = await execute_command(
            server_id=server_id,
            command=command,
            shell=shell,
            username=username,
            groupname=groupname,
            env=env,
            region=region,
            workspace=workspace
        )

        if exec_result["status"] != "success":
            return exec_result

        # Handle case where data is a list (array) instead of object
        if isinstance(exec_result["data"], list):
            if len(exec_result["data"]) > 0:
                command_id = exec_result["data"][0]["id"]
            else:
                return {
                    "status": "error",
                    "message": "No command data returned from execute_command",
                }
        else:
            command_id = exec_result["data"]["id"]

        # Wait for command completion
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            result = await get_command_result(
                command_id=command_id,
                region=region,
                workspace=workspace
            )

            if result["status"] == "success":
                command_data = result["data"]

                # Check if command is completed
                if command_data.get("finished_at") is not None:
                    return {
                        "status": "success",
                        "data": command_data,
                        "command_id": command_id,
                        "server_id": server_id,
                        "command": command,
                        "shell": shell,
                        "region": region,
                        "workspace": workspace
                    }

            # Wait before next check
            await asyncio.sleep(1)

        # Timeout reached
        return {
            "status": "timeout",
            "message": f"Command execution timed out after {timeout} seconds",
            "command_id": command_id,
            "server_id": server_id,
            "command": command,
            "region": region,
            "workspace": workspace
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to execute command synchronously: {str(e)}"
        }
