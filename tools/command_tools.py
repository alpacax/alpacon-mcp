"""Command execution tools for Alpacon MCP server - Refactored version."""

import asyncio
from typing import Dict, Any, Optional, List
from utils.http_client import http_client
from utils.common import success_response, error_response
from utils.decorators import mcp_tool_handler


@mcp_tool_handler(description="Execute a command on a server")
async def execute_command(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = "internal",
    username: Optional[str] = None,
    groupname: str = "alpacon",
    env: Optional[Dict[str, str]] = None,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Execute a command on a specified server."""
    token = kwargs.get('token')

    # Prepare command data
    command_data = {
        "server": server_id,
        "shell": shell,
        "line": command,
        "groupname": groupname
    }

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

    return success_response(
        data=result,
        server_id=server_id,
        command=command,
        shell=shell,
        username=username or "auto",
        groupname=groupname,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Get command execution result by command ID")
async def get_command_result(
    command_id: str,
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get the result of a previously executed command."""
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


@mcp_tool_handler(description="List recent commands executed on servers")
async def list_commands(
    workspace: str,
    server_id: Optional[str] = None,
    limit: int = 20,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """List recent commands executed on servers."""
    token = kwargs.get('token')

    # Prepare query parameters
    params = {
        "page_size": limit,
        "ordering": "-added_at"
    }

    if server_id:
        params["server"] = server_id

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/events/commands/",
        token=token,
        params=params
    )

    return success_response(
        data=result,
        server_id=server_id,
        limit=limit,
        region=region,
        workspace=workspace
    )


@mcp_tool_handler(description="Execute a command and wait for result")
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
    **kwargs
) -> Dict[str, Any]:
    """Execute a command and wait for the result (synchronous execution)."""
    # First, execute the command
    try:
        exec_result = await execute_command(
            server_id=server_id,
            command=command,
            shell=shell,
            username=username,
            groupname=groupname,
            env=env,
            region=region,
            workspace=workspace,
            **kwargs  # Pass token through
        )
    except Exception as e:
        return error_response(
            f"Failed to execute command: {str(e)}",
            workspace=workspace,
            region=region
        )

    # Check if execution was successful
    if exec_result.get("status") != "success":
        return exec_result

    # Handle case where data is a list (array) instead of object
    exec_data = exec_result.get("data", {})

    # Check if exec_data contains an error (like ACL permission denied)
    if isinstance(exec_data, dict) and "error" in exec_data:
        return error_response(
            f"Command execution failed: {exec_data.get('error', 'Unknown error')}",
            workspace=workspace,
            region=region,
            details=exec_data
        )

    if isinstance(exec_data, list):
        if len(exec_data) > 0:
            command_id = exec_data[0].get("id")
        else:
            return error_response(
                "No command data returned from execute_command",
                workspace=workspace,
                region=region
            )
    elif isinstance(exec_data, dict):
        command_id = exec_data.get("id")
    else:
        return error_response(
            f"Unexpected command data format: {type(exec_data).__name__}",
            workspace=workspace,
            region=region
        )

    if not command_id:
        return error_response(
            "Command ID not found in response - possible permission issue or API error",
            workspace=workspace,
            region=region,
            details=exec_data
        )

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
                return success_response(
                    data=command_data,
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    shell=shell,
                    region=region,
                    workspace=workspace
                )

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


@mcp_tool_handler(description="Execute command on multiple servers simultaneously (Deploy Shell)")
async def execute_command_multi_server(
    server_ids: List[str],
    command: str,
    workspace: str,
    shell: str = "internal",
    username: Optional[str] = None,
    groupname: str = "alpacon",
    env: Optional[Dict[str, str]] = None,
    region: str = "ap1",
    parallel: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Execute a command on multiple servers using Deploy Shell."""
    # Validate inputs
    if not server_ids:
        return error_response("server_ids cannot be empty")

    if parallel:
        # Execute commands in parallel on all servers
        tasks = []
        for server_id in server_ids:
            task = execute_command(
                server_id=server_id,
                command=command,
                workspace=workspace,
                shell=shell,
                username=username,
                groupname=groupname,
                env=env,
                region=region
            )
            tasks.append(task)

        # Wait for all commands to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        deploy_results = {}
        successful_count = 0
        failed_count = 0

        for i, result in enumerate(results):
            server_id = server_ids[i]
            if isinstance(result, Exception):
                deploy_results[server_id] = {
                    "status": "error",
                    "message": f"Exception occurred: {str(result)}"
                }
                failed_count += 1
            else:
                deploy_results[server_id] = result
                if result.get("status") == "success":
                    successful_count += 1
                else:
                    failed_count += 1

        return success_response(
            deploy_shell_results=deploy_results,
            command=command,
            total_servers=len(server_ids),
            successful_count=successful_count,
            failed_count=failed_count,
            execution_type="parallel",
            region=region,
            workspace=workspace
        )
    else:
        # Execute commands sequentially
        deploy_results = {}
        successful_count = 0
        failed_count = 0

        for server_id in server_ids:
            result = await execute_command(
                server_id=server_id,
                command=command,
                workspace=workspace,
                shell=shell,
                username=username,
                groupname=groupname,
                env=env,
                region=region
            )

            deploy_results[server_id] = result
            if result.get("status") == "success":
                successful_count += 1
            else:
                failed_count += 1

        return success_response(
            deploy_shell_results=deploy_results,
            command=command,
            total_servers=len(server_ids),
            successful_count=successful_count,
            failed_count=failed_count,
            execution_type="sequential",
            region=region,
            workspace=workspace
        )


@mcp_tool_handler(description="Get ACL-approved commands for Deploy Shell")
async def get_deploy_shell_acl_commands(
    workspace: str,
    region: str = "ap1",
    **kwargs
) -> Dict[str, Any]:
    """Get list of ACL-approved commands for Deploy Shell execution."""
    token = kwargs.get('token')

    # Get ACL commands from the security/command-acl endpoint
    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint="/api/security/command-acl/",
        token=token
    )

    return success_response(
        acl_commands=result,
        workspace=workspace,
        region=region,
        note="These are the commands approved for Deploy Shell execution via ACL"
    )
