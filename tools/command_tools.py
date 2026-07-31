"""Command execution tools for Alpacon MCP server."""

import asyncio
import re
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
_SUDO_DENIAL_HINTS: dict[str, str] = {
    'SUDO_NO_WORKSESSION_POLICY': (
        'sudo was denied: this command is not covered by an MFA-bypass policy '
        'in the Work Session. There is no MCP tool to add one—a human must add '
        'the command to the Work Session sudo policy (via the Alpacon web '
        "console or the CLI's 'work-session update --sudo'). Re-run once it is "
        'added.'
    ),
    'SUDO_PRESENCE_REQUIRED': (
        'sudo needs a recent human MFA: a human must complete a step-up, then '
        're-run. An agent cannot satisfy this.'
    ),
    'SUDO_APPROVAL_REQUIRED': (
        'sudo needs human approval: an approval request was created. Re-run '
        'after a reviewer approves it.'
    ),
    'SUDO_RISK_DENIED': (
        'sudo was denied by runtime risk assessment; this command is not '
        'permitted in this Work Session.'
    ),
    'SUDO_POLICY_MFA_REQUIRED': (
        'sudo was denied: a Work Session sudo policy covers this command, but '
        'it is not an MFA-bypass policy and a command runs non-interactively, '
        'so it can never supply MFA. A human must set allow_bypass_mfa on that '
        'policy (enterprise plan; the policy must be tied to a usable Work '
        'Session). Re-run once it is set.'
    ),
    'SUDO_INTENT_DEVIATION': (
        'sudo was denied: this command was judged off-purpose for the Work '
        "Session's declared intent, and an approval request was created. Either "
        'wait for a reviewer, or re-declare what the session is for with '
        'work_session_update(description=...) and re-run—note the server '
        'queues a description change for its own approval unless you are an '
        'admin or hold owner/manager on every server in the session.'
    ),
    'SUDO_COMMAND_NOT_AUTHORIZED': (
        'sudo was denied: the command carries no requesting identity, so no '
        'sudo policy can be matched to it. Re-running as-is will fail the same '
        'way; report this to a workspace administrator.'
    ),
    'WORK_SESSION_SCOPE_NOT_ALLOWED': (
        'sudo was denied: the Work Session does not carry the sudo scope. Add '
        'it with work_session_update(scopes=[...]), or open a session that has '
        'it, then re-run—note the server queues a scope addition for its own '
        'approval unless you are an admin or hold owner/manager on every '
        'server in the session.'
    ),
    'SUDO_SESSION_MISSING': (
        'sudo was denied: the server could not tie this sudo request back to '
        'the command that issued it, so no policy can be evaluated. This is an '
        'agent/server plumbing failure, not a permissions one—report it rather '
        'than re-running.'
    ),
    'SUDO_NO_AUTHORITY': (
        'sudo was denied: the OS user running the command is a local account '
        'not mapped to an Alpacon identity, and local users cannot use sudo '
        'through Alpacon. Re-run as a system user bound to an Alpacon account.'
    ),
    'WORKSPACE_SUDO_WITH_MFA_DISABLED': (
        'sudo was denied: this workspace has sudo-with-MFA turned off in its '
        'security settings, which blocks every sudo command workspace-wide. '
        'Re-running changes nothing; a workspace administrator must change the '
        'setting.'
    ),
}


# The exact terminal-facing denial line, emitted identically by
# alpacon_approval.c (g_plugin_printf) and pam_alpamon.c (pam_error) as
# "Alpacon denied this sudo command (CODE).". Matching the whole line—closing
# period included—rather than a bare '(CODE)' token is what stops a command that
# prints the token in its own output from forging a hint on a run that actually
# succeeded. Deliberately not anchored to a line start: the line is written to
# stderr and lands mid-line whenever preceding output left no trailing newline,
# and losing a real denial to that is worse than the residual false positive.
# The other "Permission denied (CODE)" form is assigned to *errstr, which only
# reaches the audit log—not the invoking terminal—so it must not be matched here.
_SUDO_DENIAL_LINE_RE = re.compile(
    r'Alpacon denied this sudo command \(([A-Z0-9_]+)\)\.'
)


# Denial categories a human can resolve out-of-band (approve / step-up / grant).
# These also get a machine-actionable pending-approval block (ADR 0015) so an
# agent branches on stable flags instead of prose, and waits rather than
# retry-spams. Codes absent here are hard denials with nothing pending behind
# them: telling the agent to wait would mean waiting forever.
_SUDO_HUMAN_APPROVAL_CODES = frozenset(
    {
        'SUDO_NO_WORKSESSION_POLICY',
        'SUDO_PRESENCE_REQUIRED',
        'SUDO_APPROVAL_REQUIRED',
        'SUDO_POLICY_MFA_REQUIRED',
        'SUDO_INTENT_DEVIATION',
        'WORK_SESSION_SCOPE_NOT_ALLOWED',
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
    match = _SUDO_DENIAL_LINE_RE.search(output)
    if not match:
        return None
    code = match.group(1)
    hint = _SUDO_DENIAL_HINTS.get(code)
    return (code, hint) if hint else None


def _attach_sudo_denial(
    target: dict[str, Any], source: dict[str, Any] | None = None
) -> None:
    """Attach denial guidance found in ``source`` onto ``target``.

    ``source`` defaults to ``target``: a listing entry carries its own output,
    while a single command's guidance goes on the tool response rather than on
    the raw API result it was read from.
    """
    denial = _sudo_denial(target if source is None else source)
    if not denial:
        return
    code, hint = denial
    # Backward-compatible free-text hint.
    target['sudo_hint'] = hint
    # Only the category is disclosed—never the risk score or reasoning.
    if code in _SUDO_HUMAN_APPROVAL_CODES:
        target['sudo_denial'] = pending_approval_response(hint, category=code)


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
    description='List recent command execution history with status, output, and timestamps. Filterable by server ID. An entry whose output is a sudo denial also carries sudo_hint and, when a human can clear it, a structured sudo_denial block. When to use: reviewing past commands, retrieving the result of a command whose execute_command call timed out, or reading the results of an execute_command_multi_server batch. Related: execute_command (run a command and wait).',
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

    # execute_command_multi_server only submits, so a fleet command's sudo
    # denial is observable nowhere else.
    entries = result.get('results') if isinstance(result, dict) else None
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, dict):
            _attach_sudo_denial(entry)

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
                _attach_sudo_denial(response, result)
                return response

            if status == 'awaiting_approval':
                # HITL verification gate: a human must approve out-of-band
                # (ADR 0015); polling would only burn the timeout window.
                return pending_approval_response(
                    'Command is awaiting human approval. A human must approve '
                    'it out-of-band (Alpacon web console or Slack); it then runs '
                    'automatically. Wait, then retrieve the result via '
                    'list_commands. Do not re-run: a resubmission needs its own '
                    'approval and may double-execute the command.',
                    category='COMMAND_AWAITING_APPROVAL',
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    region=region,
                    workspace=workspace,
                )

            # Terminal non-approval statuses: the command will not produce a
            # result (denied/rejected never run; stuck gave up), so fail fast
            # instead of polling until timeout. ('error' is omitted: the
            # server's compute_status never emits it given the scheduled_at
            # default, so it is unreachable here.)
            if status in ('denied', 'rejected', 'stuck'):
                return error_response(
                    f'Command failed with status: {status}',
                    command_id=command_id,
                    server_id=server_id,
                    command=command,
                    region=region,
                    workspace=workspace,
                    details=result,
                )

            # Command still in progress — reset deadline (within hard cap) so a
            # slow AI verification or delayed delivery does not time out a
            # command that is still advancing. Covers both pre-execution states
            # (queued/scheduled/delivered/verifying) and execution (running).
            # 'acked' is intentionally absent: compute_status returns 'running'
            # once acked_at is set, so it is never emitted.
            if status in (
                'running',
                'verifying',
                'delivered',
                'queued',
                'scheduled',
            ):
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
