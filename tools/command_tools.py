"""Command execution tools for Alpacon MCP server - Refactored version."""

import asyncio
from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.error_handler import UpstreamAuthError
from utils.http_client import http_client


@mcp_tool_handler(
    description='Run a shell command on a remote server asynchronously via Command API. Returns a command ID that can be polled with get_command_result. Requires ACL permission on the API token. For synchronous execution, use execute_command_sync instead.'
)
async def execute_command_with_acl(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = 'internal',
    username: str | None = None,
    groupname: str = 'alpacon',
    env: dict[str, str] | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Execute a command on a specified server using Command API (requires ACL permission)."""
    token = kwargs.get('token')

    # Prepare command data
    command_data: dict[str, Any] = {
        'server': server_id,
        'shell': shell,
        'line': command,
        'groupname': groupname,
    }

    if username:
        command_data['username'] = username
    if env:
        command_data['env'] = env

    # Make async call to execute command
    result = await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/events/commands/',
        token=token,
        data=command_data,
    )

    return success_response(
        data=result,
        server_id=server_id,
        command=command,
        shell=shell,
        username=username or 'auto',
        groupname=groupname,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Retrieve the result of a previously executed command by its command ID. Returns stdout, stderr, exit code, and completion status. Use this to poll for results after execute_command_with_acl.'
)
async def get_command_result(
    command_id: str, workspace: str, region: str = '', **kwargs
) -> dict[str, Any]:
    """Get the result of a previously executed command."""
    token = kwargs.get('token')

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/commands/{command_id}/',
        token=token,
    )

    return success_response(
        data=result, command_id=command_id, region=region, workspace=workspace
    )


@mcp_tool_handler(
    description='List recent command execution history with status, output, and timestamps. Filterable by server ID. Use this to review what commands have been run or check past results.'
)
async def list_commands(
    workspace: str,
    server_id: str | None = None,
    limit: int = 20,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """List recent commands executed on servers."""
    token = kwargs.get('token')

    # Prepare query parameters
    params = {'page_size': limit, 'ordering': '-added_at'}

    if server_id:
        params['server'] = server_id

    result = await http_client.get(
        region=region,
        workspace=workspace,
        endpoint='/api/events/commands/',
        token=token,
        params=params,
    )

    return success_response(
        data=result,
        server_id=server_id,
        limit=limit,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Run a shell command on a server and wait for it to complete. Returns stdout, stderr, and exit code in a single call. Requires ACL permission. This is the simplest way to run a command via the Command API when you need the result immediately.'
)
async def execute_command_sync(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = 'bash',
    username: str | None = None,
    groupname: str = 'alpacon',
    env: dict[str, str] | None = None,
    timeout: int = 30,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Execute a command and wait for the result using Command API (requires ACL permission)."""
    # First, execute the command
    try:
        exec_result = await execute_command_with_acl(
            server_id=server_id,
            command=command,
            shell=shell,
            username=username,
            groupname=groupname,
            env=env,
            region=region,
            workspace=workspace,
            **kwargs,  # Pass token through
        )
    except UpstreamAuthError:
        raise
    except Exception as e:
        return error_response(
            f'Failed to execute command: {str(e)}', workspace=workspace, region=region
        )

    # Check if execution was successful
    if exec_result.get('status') != 'success':
        return exec_result

    # Handle case where data is a list (array) instead of object
    exec_data = exec_result.get('data', {})

    # Check if exec_data contains an error (like ACL permission denied)
    if isinstance(exec_data, dict) and 'error' in exec_data:
        return error_response(
            f'Command execution failed: {exec_data.get("error", "Unknown error")}',
            workspace=workspace,
            region=region,
            details=exec_data,
        )

    if isinstance(exec_data, list):
        if len(exec_data) > 0:
            command_id = exec_data[0].get('id')
        else:
            return error_response(
                'No command data returned from execute_command',
                workspace=workspace,
                region=region,
            )
    elif isinstance(exec_data, dict):
        command_id = exec_data.get('id')
    else:
        return error_response(
            f'Unexpected command data format: {type(exec_data).__name__}',
            workspace=workspace,
            region=region,
        )

    if not command_id:
        return error_response(
            'Command ID not found in response - possible permission issue or API error',
            workspace=workspace,
            region=region,
            details=exec_data,
        )

    # Wait for command completion
    start_time = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start_time) < timeout:
        result = await get_command_result(
            command_id=command_id, region=region, workspace=workspace
        )

        if result['status'] == 'success':
            command_data = result['data']

            # Check if command is completed
            if command_data.get('finished_at') is not None:
                return success_response(
                    data=command_data,
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    shell=shell,
                    region=region,
                    workspace=workspace,
                )

        # Wait before next check
        await asyncio.sleep(1)

    # Timeout reached
    return {
        'status': 'timeout',
        'message': f'Command execution timed out after {timeout} seconds',
        'command_id': command_id,
        'server_id': server_id,
        'command': command,
        'region': region,
        'workspace': workspace,
    }


@mcp_tool_handler(
    description='Run the same shell command on multiple servers simultaneously or sequentially. Returns per-server results with success/failure status. Requires ACL permission. Use this for batch operations like deploying configs or checking status across a fleet.'
)
async def execute_command_multi_server(
    server_ids: list[str],
    command: str,
    workspace: str,
    shell: str = 'internal',
    username: str | None = None,
    groupname: str = 'alpacon',
    env: dict[str, str] | None = None,
    region: str = '',
    parallel: bool = True,
    **kwargs,
) -> dict[str, Any]:
    """Execute a command on multiple servers using Command API Deploy Shell (requires ACL permission)."""
    # Validate inputs
    if not server_ids:
        return error_response('server_ids cannot be empty')

    if parallel:
        # Execute commands in parallel on all servers
        tasks = []
        for server_id in server_ids:
            task = execute_command_with_acl(
                server_id=server_id,
                command=command,
                workspace=workspace,
                shell=shell,
                username=username,
                groupname=groupname,
                env=env,
                region=region,
                **kwargs,
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
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result  # Re-raise CancelledError, KeyboardInterrupt, etc.
                deploy_results[server_id] = {
                    'status': 'error',
                    'message': f'Exception occurred: {str(result)}',
                }
                failed_count += 1
            else:
                deploy_results[server_id] = result
                if result.get('status') == 'success':
                    successful_count += 1
                else:
                    failed_count += 1

        return success_response(
            deploy_shell_results=deploy_results,
            command=command,
            total_servers=len(server_ids),
            successful_count=successful_count,
            failed_count=failed_count,
            execution_type='parallel',
            region=region,
            workspace=workspace,
        )
    else:
        # Execute commands sequentially
        deploy_results = {}
        successful_count = 0
        failed_count = 0

        for server_id in server_ids:
            result = await execute_command_with_acl(
                server_id=server_id,
                command=command,
                workspace=workspace,
                shell=shell,
                username=username,
                groupname=groupname,
                env=env,
                region=region,
                **kwargs,
            )

            deploy_results[server_id] = result
            if result.get('status') == 'success':
                successful_count += 1
            else:
                failed_count += 1

        return success_response(
            deploy_shell_results=deploy_results,
            command=command,
            total_servers=len(server_ids),
            successful_count=successful_count,
            failed_count=failed_count,
            execution_type='sequential',
            region=region,
            workspace=workspace,
        )
