"""Command execution tools for Alpacon MCP server."""

import asyncio
from typing import Any, cast

from utils.common import (
    error_response,
    pending_approval_response,
    resolve_work_session_id,
    success_response,
    unwrap_http_result,
)
from utils.decorators import mcp_tool_handler
from utils.http_client import http_client
from utils.tool_annotations import ADDITIVE, READ_ONLY

# Non-interactive sudo denial codes, as they reach the command output via
# alpacon_approval.c's [A-Z0-9_] sanitizer (UPPERCASE). Kept in sync with
# alpacon-server utils/error_codes.py. Surfaced to the agent as category-level
# guidance only—the server never sends the risk score or reasoning to a client.
_SUDO_DENIAL_HINTS: tuple[tuple[str, str], ...] = (
    (
        'SUDO_NO_WORKSESSION_POLICY',
        'sudo was denied: this command is not covered by an MFA-bypass policy '
        'in the Work Session. There is no MCP tool to add one—a human must add '
        'the command to the Work Session sudo policy (via the Alpacon web '
        "console or the CLI's 'work-session update --sudo'). Re-run once it is "
        'added.',
    ),
    (
        'SUDO_PRESENCE_REQUIRED',
        'sudo needs a recent human MFA: a human must complete a step-up, then '
        're-run. An agent cannot satisfy this.',
    ),
    (
        'SUDO_APPROVAL_REQUIRED',
        'sudo needs human approval: an approval request was created. Re-run '
        'after a reviewer approves it.',
    ),
    (
        'SUDO_RISK_DENIED',
        'sudo was denied by runtime risk assessment; this command is not '
        'permitted in this Work Session.',
    ),
)


# The exact terminal-facing denial line alpacon_approval.c emits via
# g_plugin_printf ("Alpacon denied this sudo command (CODE)."). The other
# "Permission denied (CODE)" form is assigned to *errstr, which only reaches the
# audit log—not the invoking terminal—so it must not be matched here.
_SUDO_DENIAL_LINE_PREFIX = 'Alpacon denied this sudo command'


# Denial categories that a human can resolve out-of-band (approve / step-up).
# For these we attach a machine-actionable pending-approval block (ADR 0015) in
# addition to the free-text hint, so an agent can branch on stable flags instead
# of parsing prose, and waits/escalates rather than retry-spamming. Risk-denied
# is excluded: it is a hard policy denial, not a pending human approval.
_SUDO_HUMAN_APPROVAL_CODES = frozenset(
    {
        'SUDO_NO_WORKSESSION_POLICY',
        'SUDO_PRESENCE_REQUIRED',
        'SUDO_APPROVAL_REQUIRED',
    }
)


def _sudo_denial(result: dict[str, Any]) -> tuple[str, str] | None:
    """Detect a non-interactive sudo denial in the command output.

    Returns ``(code, hint)`` for the matched denial category so the caller can
    surface category-level guidance—and, for human-resolvable categories, a
    structured pending-approval signal—without the agent parsing free text.
    Returns None when no denial is present.
    """
    output = result.get('result') or ''
    if not isinstance(output, str):
        return None
    for code, hint in _SUDO_DENIAL_HINTS:
        # Anchor on the plugin's full denial line, not a bare '(CODE)' token:
        # otherwise a command whose own output prints '(SUDO_RISK_DENIED)' could
        # forge a hint on a command that actually succeeded and mislead the
        # agent into a wrong action.
        if f'{_SUDO_DENIAL_LINE_PREFIX} ({code})' in output:
            return code, hint
    return None


def _sudo_denial_hint(result: dict[str, Any]) -> str | None:
    """Return the free-text denial hint for a sudo denial, or None.

    Thin wrapper over :func:`_sudo_denial` kept for callers/tests that only need
    the human-readable guidance string.
    """
    denial = _sudo_denial(result)
    return denial[1] if denial else None


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
    work_session_id: str | None = None,
    region: str = '',
    *,
    token: str | None = None,
) -> dict[str, Any] | list[Any]:
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
    if ws_id := resolve_work_session_id(work_session_id):
        command_data['work_session'] = ws_id

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
    return await http_client.get(
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/commands/{command_id}/',
        token=token,
    )


@mcp_tool_handler(
    description='List recent command execution history with status, output, and timestamps. Filterable by server ID. When to use: reviewing past commands, or retrieving the result of a command whose execute_command call timed out. Related: execute_command (run a command and wait).',
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

    if err := unwrap_http_result(
        result,
        default_message='Failed to list commands',
        region=region,
        workspace=workspace,
    ):
        return err

    return success_response(
        data=result,
        server_id=server_id,
        limit=limit,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Run a shell command on a server and wait for the result (up to 5 minutes by default). Returns stdout, stderr, and exit code in a single call. Requires ACL permission. The timeout resets when the command is actively running. Supports dependency chains (run_after), scheduled execution (scheduled_at), and stdin data. Pass work_session_id to link this command to a Work Session for audit—the server enforces this for MCP OAuth and browser-based auth. When to use: the recommended way to run a command on a server. Related: execute_command_multi_server (run on multiple servers), list_commands (browse history), work_session_create (create a Work Session). Note: Default timeout is 300 seconds (5 minutes).',
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
    work_session_id: str | None = None,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Execute a command on a server and wait for the result (requires ACL permission)."""
    token = kwargs.get('token')

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
        work_session_id=work_session_id,
        region=region,
        token=token,
    )

    if isinstance(exec_data, dict) and 'error' in exec_data:
        # unwrap_http_result returns non-None whenever 'error' is in the dict
        return cast(
            dict[str, Any],
            unwrap_http_result(
                exec_data,
                default_message='Command execution failed',
                server_id=server_id,
                region=region,
                workspace=workspace,
            ),
        )

    if isinstance(exec_data, list):
        if exec_data:
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
    loop = asyncio.get_running_loop()
    hard_deadline = loop.time() + timeout * 3
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = await _get_command_result(
            command_id=command_id,
            region=region,
            workspace=workspace,
            token=token,
        )

        if isinstance(result, dict) and 'error' in result:
            return error_response(
                f'Failed to poll command result: {result.get("error")}',
                command_id=command_id,
                server_id=server_id,
                command=command,
                region=region,
                workspace=workspace,
                details=result,
            )

        if isinstance(result, dict):
            status = result.get('status', '')

            # handled_at is set once the agent reports the result (status then
            # becomes 'success'/'failed'); the Command API has no 'finished_at'.
            if result.get('handled_at') is not None:
                response = success_response(
                    data=result,
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    shell=shell,
                    region=region,
                    workspace=workspace,
                )
                denial = _sudo_denial(result)
                if denial:
                    code, hint = denial
                    # Backward-compatible free-text hint.
                    response['sudo_hint'] = hint
                    # For human-resolvable denials, also attach a structured,
                    # machine-actionable pending-approval block (ADR 0015): the
                    # command did not run and a human must act out-of-band. Only
                    # the category is disclosed—never the risk score/reasoning.
                    if code in _SUDO_HUMAN_APPROVAL_CODES:
                        response['sudo_denial'] = pending_approval_response(
                            hint,
                            category=code,
                        )
                return response

            if status == 'awaiting_approval':
                # HITL verification gate: a human must approve out-of-band
                # (ADR 0015); polling would only burn the timeout window.
                return pending_approval_response(
                    'Command is awaiting human approval. A human must approve '
                    'it out-of-band (Alpacon web console or Slack); then check '
                    'the result via list_commands or re-run.',
                    category='COMMAND_AWAITING_APPROVAL',
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    region=region,
                    workspace=workspace,
                )

            # Terminal non-approval statuses: the command will not produce a
            # result (denied/rejected never run; stuck/error gave up), so fail
            # fast instead of polling until timeout.
            if status in ('denied', 'rejected', 'stuck', 'error'):
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
                    loop.time() + timeout,
                    hard_deadline,
                )

        await asyncio.sleep(1)

    return error_response(
        f'Command execution timed out after {timeout} seconds',
        error_type='timeout',
        command_id=command_id,
        server_id=server_id,
        command=command,
        region=region,
        workspace=workspace,
    )


@mcp_tool_handler(
    description='Run the same shell command on multiple servers simultaneously or sequentially. Returns per-server results with success/failure status. Requires ACL permission. Pass work_session_id to link commands to a Work Session for audit—the server enforces this for MCP OAuth and browser-based auth. When to use: batch operations like deploying configs, checking status, or running diagnostics across a fleet. Related: execute_command (single server), work_session_create (create a Work Session). Note: Set parallel=false for sequential execution. This submits commands without waiting for results — use list_commands to check status.',
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
    work_session_id: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Execute a command on multiple servers using Command API (requires ACL permission)."""
    token = kwargs.get('token')

    if not server_ids:
        return error_response('server_ids cannot be empty')

    async def _submit_one(sid: str) -> dict[str, Any] | list[Any]:
        return await _submit_command(
            server_id=sid,
            command=command,
            workspace=workspace,
            shell=shell,
            username=username,
            groupname=groupname,
            env=env,
            work_session_id=work_session_id,
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
        for sid, result in zip(server_ids, results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                deploy_results[sid] = {
                    'status': 'error',
                    'message': str(result),
                }
                failed_count += 1
            elif isinstance(result, dict) and 'error' in result:
                # unwrap_http_result returns non-None whenever 'error' is in the dict
                deploy_results[sid] = unwrap_http_result(
                    result,
                    default_message='Command execution failed',
                    server_id=sid,
                    region=region,
                    workspace=workspace,
                )
                failed_count += 1
            else:
                deploy_results[sid] = {'status': 'success', 'data': result}
                successful_count += 1
    else:
        for sid in server_ids:
            try:
                result = await _submit_one(sid)
                if isinstance(result, dict) and 'error' in result:
                    # unwrap_http_result returns non-None whenever 'error' is in the dict
                    deploy_results[sid] = unwrap_http_result(
                        result,
                        default_message='Command execution failed',
                        server_id=sid,
                        region=region,
                        workspace=workspace,
                    )
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
