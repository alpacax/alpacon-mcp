"""Command execution tools for Alpacon MCP server."""

import asyncio
from typing import Any

from utils.common import error_response, success_response
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, READ_ONLY


async def _submit_command(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = 'system',
    username: str | None = None,
    groupname: str = 'alpacon',
    env: dict[str, str] | None = None,
    run_after: list[str] | None = None,
    scheduled_at: str | None = None,
    data: str | None = None,
    region: str = '',
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Submit a command to the Command API. Internal helper, not an MCP tool."""
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
    if run_after:
        command_data['run_after'] = run_after
    if scheduled_at:
        command_data['scheduled_at'] = scheduled_at
    if data:
        command_data['data'] = data

    return await http_client.post(
        region=region,
        workspace=workspace,
        endpoint='/api/events/commands/',
        token=token,
        data=command_data,
    )


async def _get_command_result(
    command_id: str,
    workspace: str,
    region: str = '',
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Poll a command result by ID. Internal helper, not an MCP tool."""
    return await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/commands/{command_id}/',
        token=token,
    )


@mcp_tool_handler(
    description='List recent command execution history with status, output, and timestamps. Filterable by server ID. When to use: reviewing past commands or checking what has been run on a server. Related: get_command_result (get full output of a specific command).',
    annotations=READ_ONLY,
    meta={'anthropic/searchHint': 'command history list recent'},
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
    description='Run a shell command on a server and wait for the result (up to 5 minutes by default). Returns stdout, stderr, and exit code in a single call. Requires ACL permission. The timeout resets when the command is actively running. Supports dependency chains (run_after), scheduled execution (scheduled_at), and stdin data. When to use: the recommended way to run a command on a server. Related: execute_command_multi_server (run on multiple servers), list_commands (browse history). Note: Default timeout is 300 seconds (5 minutes).',
    annotations=ADDITIVE,
    meta={
        'anthropic/alwaysLoad': True,
        'anthropic/searchHint': 'command run shell execute wait result ACL',
    },
)
async def execute_command(
    server_id: str,
    command: str,
    workspace: str,
    shell: str = 'system',
    username: str | None = None,
    groupname: str = 'alpacon',
    env: dict[str, str] | None = None,
    run_after: list[str] | None = None,
    scheduled_at: str | None = None,
    data: str | None = None,
    timeout: int = 300,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Execute a command on a server and wait for the result (requires ACL permission)."""
    token = kwargs.get('token')

    # Submit the command
    exec_data = await _submit_command(
        server_id=server_id,
        command=command,
        workspace=workspace,
        shell=shell,
        username=username,
        groupname=groupname,
        env=env,
        run_after=run_after,
        scheduled_at=scheduled_at,
        data=data,
        region=region,
        token=token,
    )

    # Check if exec_data contains an error (like ACL permission denied)
    if isinstance(exec_data, dict) and 'error' in exec_data:
        return error_response(
            f'Command execution failed: {exec_data.get("error", "Unknown error")}',
            workspace=workspace,
            region=region,
            details=exec_data,
        )

    # Extract command ID from response (API may return dict or list)
    if isinstance(exec_data, list):
        if len(exec_data) > 0:
            command_id = exec_data[0].get('id')
        else:
            return error_response(
                'No command data returned', workspace=workspace, region=region
            )
    elif isinstance(exec_data, dict):
        command_id = exec_data.get('id')
    else:
        return error_response(
            f'Unexpected response format: {type(exec_data).__name__}',
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

    # Poll for command completion with progress-based timeout reset
    # Hard cap at 3x timeout to prevent indefinite waiting
    hard_deadline = asyncio.get_event_loop().time() + timeout * 3
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = await _get_command_result(
            command_id=command_id,
            region=region,
            workspace=workspace,
            token=token,
        )

        if isinstance(result, dict) and 'error' not in result:
            status = result.get('status', '')

            # Command completed
            if result.get('finished_at') is not None:
                return success_response(
                    data=result,
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    shell=shell,
                    region=region,
                    workspace=workspace,
                )

            # Command failed with terminal status
            if status in ('stuck', 'error'):
                return error_response(
                    f'Command failed with status: {status}',
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    region=region,
                    workspace=workspace,
                    details=result,
                )

            # Command still in progress — reset deadline (within hard cap)
            if status in ('running', 'acked'):
                deadline = min(
                    asyncio.get_event_loop().time() + timeout,
                    hard_deadline,
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
    description='Run the same shell command on multiple servers simultaneously or sequentially. Returns per-server results with success/failure status. Requires ACL permission. When to use: batch operations like deploying configs, checking status, or running diagnostics across a fleet. Related: execute_command (single server). Note: Set parallel=false for sequential execution. This submits commands without waiting for results — use list_commands to check status.',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'command multi server batch deploy fleet parallel'},
)
async def execute_command_multi_server(
    server_ids: list[str],
    command: str,
    workspace: str,
    shell: str = 'system',
    username: str | None = None,
    groupname: str = 'alpacon',
    env: dict[str, str] | None = None,
    region: str = '',
    parallel: bool = True,
    **kwargs,
) -> dict[str, Any]:
    """Execute a command on multiple servers using Command API (requires ACL permission)."""
    token = kwargs.get('token')

    if not server_ids:
        return error_response('server_ids cannot be empty')

    async def _submit_one(sid: str) -> dict[str, Any]:
        return await _submit_command(
            server_id=sid,
            command=command,
            workspace=workspace,
            shell=shell,
            username=username,
            groupname=groupname,
            env=env,
            region=region,
            token=token,
        )

    deploy_results: dict[str, Any] = {}
    successful_count = 0
    failed_count = 0

    if parallel:
        results = await asyncio.gather(
            *[_submit_one(sid) for sid in server_ids], return_exceptions=True
        )
        for i, result in enumerate(results):
            sid = server_ids[i]
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                deploy_results[sid] = {
                    'status': 'error',
                    'message': str(result),
                }
                failed_count += 1
            elif isinstance(result, dict) and 'error' in result:
                deploy_results[sid] = {'status': 'error', **result}
                failed_count += 1
            else:
                deploy_results[sid] = {'status': 'success', 'data': result}
                successful_count += 1
    else:
        for sid in server_ids:
            try:
                result = await _submit_one(sid)
                if isinstance(result, dict) and 'error' in result:
                    deploy_results[sid] = {'status': 'error', **result}
                    failed_count += 1
                else:
                    deploy_results[sid] = {'status': 'success', 'data': result}
                    successful_count += 1
            except Exception as e:
                deploy_results[sid] = {'status': 'error', 'message': str(e)}
                failed_count += 1

    return success_response(
        deploy_shell_results=deploy_results,
        command=command,
        total_servers=len(server_ids),
        successful_count=successful_count,
        failed_count=failed_count,
        execution_type='parallel' if parallel else 'sequential',
        region=region,
        workspace=workspace,
    )
