"""Command execution tools for Alpacon MCP server."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
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

#: Ceiling the server puts on a stated purpose, on both write paths (ADR 0052).
#: Truncating here rather than letting the server refuse keeps a long purpose
#: from costing the command its one demand.
PURPOSE_MAX_LENGTH = 2000

#: The server's default COMMAND_PURPOSE_DEADLINE, used only when the row itself
#: carries no ``purpose_requested_at`` to measure from. The setting is
#: env-overridable, so this is a fallback and never a timer this client enforces.
PURPOSE_DEADLINE_SECONDS = 60

#: The one prohibition every held-command response repeats. Each site appends
#: its own reason—double execution here, a second approval request there—but the
#: instruction itself lives in one place so one copy cannot be reworded alone.
DO_NOT_RESUBMIT = 'Do not resubmit the command'

# Non-interactive sudo denial codes, as they reach the command output via
# alpacon_approval.c's [A-Z0-9_] sanitizer (UPPERCASE). Kept in sync with
# alpacon-server utils/error_codes.py. Surfaced to the agent as category-level
# guidance only—the server never sends the risk score or reasoning to a client.
_SUDO_DENIAL_HINTS: dict[str, str] = {
    'SUDO_NO_WORKSESSION_POLICY': (
        'sudo was denied: this command is not covered by an MFA-bypass policy '
        'in the Work Session. You can ask for a policy with '
        'request_sudo_policy, but an admin has to approve that request before '
        'it takes effect, and the request cannot carry MFA bypass—the server '
        'refuses it on that endpoint. A bypass policy still needs a human, who '
        'sets allow_bypass_mfa on a Work Session policy in the Alpacon web '
        "console or with the CLI's 'work-session update --sudo'. Re-run once "
        'the policy is live.'
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
        'wait for a reviewer, or—if the session description understates the work '
        'it was always meant to cover—restate that purpose in prose with '
        'work_session_update(description=...) and re-run. Never put the command '
        'text in the description: it is a purpose statement for the approver and '
        'nothing in it is executed. Note the server queues a description change '
        'for its own approval unless you are an admin or hold owner/manager on '
        'every server in the session.'
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


# The exact terminal-facing denial line. Three sites emit one carrying a code,
# in two wordings: "...this sudo command (CODE)." from alpacon_approval.c
# (g_plugin_printf) and pam_alpamon.c's pam_authorize_sudo_rs (pam_error), and
# "...this sudo invocation (CODE)." from pam_alpamon.c's pam_sm_authenticate
# hard-deny path (pam_error), which is scoped to a deploy shell—exactly what
# execute_command produces. Both wordings must match or a real hard-deny loses
# its hint. Matching the whole line—closing period included—rather than a bare
# '(CODE)' token is what stops a command that prints the token in its own output
# from forging a hint on a run that actually succeeded. Deliberately not
# anchored to a line start: the line is written to stderr and lands mid-line
# whenever preceding output left no trailing newline, and losing a real denial
# to that is worse than the residual false positive. The other
# "Permission denied (CODE)" form is assigned to *errstr, which only reaches the
# audit log—not the invoking terminal—so it must not be matched here.
_SUDO_DENIAL_LINE_RE = re.compile(
    r'Alpacon denied this sudo (?:command|invocation) \(([A-Z0-9_]+)\)\.'
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
    purpose: str | None = None,
    purpose_demand_supported: bool = False,
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
    # Strip first: a whitespace-only purpose is truthy, so without this it is
    # sent, refused with a 400, and the 400 costs the command its one demand.
    # Blank means unstated, and unstated has to arrive as an absent field—the
    # arming check reads absence, not emptiness.
    if stated := (purpose or '').strip():
        command_data['purpose'] = stated[:PURPOSE_MAX_LENGTH]
    # Declared only by a caller that will actually answer the demand (ADR 0052).
    # The gate parks the command for COMMAND_PURPOSE_DEADLINE and nobody is
    # listening on a fire-and-forget submit, so declaring it there would buy a
    # silent delay of that length per command and nothing else.
    if purpose_demand_supported:
        command_data['purpose_demand_supported'] = True

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


async def _answer_purpose_demand(
    command_id: str,
    purpose: str,
    workspace: str,
    region: str = '',
    *,
    token: str | None = None,
) -> dict[str, Any]:
    return await http_client.post(
        region=region,
        workspace=workspace,
        endpoint=f'/api/events/commands/{command_id}/purpose/',
        token=token,
        data={'purpose': purpose.strip()[:PURPOSE_MAX_LENGTH]},
    )


def _purpose_required_response(
    deadline_seconds: int | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Report an open purpose demand as something this agent must answer itself.

    Deliberately not ``pending_approval_response``: that shape says a human
    holds the next move (``requires_human_approval``, ``approvable_by_agent:
    False``), and here the opposite is true. No approval request exists yet—the
    whole point of ADR 0052 is that the approver is not notified while the
    demand is open—so an agent that reads this as "wait for a human" strands a
    command nobody was asked about.

    The response carries the instructions rather than leaving them to the tool
    description. An agent reads the answer to its own call far more reliably
    than it recalls a description that context compaction may have dropped.
    """
    response: dict[str, Any] = {**kwargs}
    response.update(
        {
            'status': 'purpose_required',
            'category': 'COMMAND_PURPOSE_REQUIRED',
            'message': (
                'The gate is asking what this command is for. Answer now with '
                'state_command_purpose; the assessor re-judges once and that '
                'call returns the outcome. The demand expires shortly, and '
                f'{DO_NOT_RESUBMIT.lower()}: there is one demand per command, '
                'and a resubmission may double-execute it.'
            ),
            # Only the rules that bind the next call. The worked examples and
            # the manipulation paragraph live in the tool descriptions, which
            # the agent already has; repeating them here spends context on
            # every held command to say the same thing twice.
            'purpose_guidance': (
                'State a fact local to this host that the work session '
                'description does not already imply. A purpose cannot lower '
                'intrinsic risk, outrank the session description, or make an '
                'unmeasurable command measurable.'
            ),
            # Machine-actionable flags, inverted from the approval shape: this
            # is the agent's move and no human has been asked anything.
            'requires_human_approval': False,
            'answerable_by_agent': True,
            'next_action': 'call state_command_purpose with command_id and purpose',
        }
    )
    if deadline_seconds is not None:
        response['deadline_seconds'] = deadline_seconds
    return response


def _purpose_was_truncated(purpose: str | None) -> bool:
    """Whether trimming to the ceiling actually cut anything off.

    Trimming avoids a 400 that would cost the command its one demand, but a
    purpose cut mid-sentence is what the assessor then judges. The caller has to
    be told, or it reads a verdict on words it did not write.
    """
    return len((purpose or '').strip()) > PURPOSE_MAX_LENGTH


def _remaining_purpose_window(requested_at: Any) -> int | None:
    """Seconds left before the demand expires, or None when unknowable.

    Measured from the row's own ``purpose_requested_at`` rather than reported as
    a flat constant: ``COMMAND_PURPOSE_DEADLINE`` is env-overridable, so a
    hard-coded number is a deadline that does not exist on a workspace which
    raised it. Elapsed time is the larger error either way—without it, a demand
    seen four minutes later still reads as a full window.

    Returns None when the server sends no timestamp, so the response omits the
    field instead of inventing one. A window already gone reports 0, never a
    negative, which would invite arithmetic on it.
    """
    if not isinstance(requested_at, str):
        return None
    try:
        opened = datetime.fromisoformat(requested_at)
    except ValueError:
        return None
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    left = (
        opened + timedelta(seconds=PURPOSE_DEADLINE_SECONDS) - datetime.now(UTC)
    ).total_seconds()
    return max(0, int(left))


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
    description='Run a shell command on a server and wait for the result (up to 5 minutes by default). Returns stdout, stderr, and exit code in a single call. Requires ACL permission. Do not prefix the command with sudo by default: unless a Work Session sudo policy already covers the command, a sudo invocation either routes to human-in-the-loop approval and blocks until a human acts, or is denied outright with no request anyone can approve. Check sudo_denial.category before waiting; a sudo_hint with no sudo_denial is a hard denial that creates no request, so do not wait on it. Use sudo only when the command genuinely requires root and the Work Session carries the "sudo" scope. The timeout resets when the command is actively running. Supports dependency chains (run_after), scheduled execution (scheduled_at), and stdin data. Pass work_session_id to link this command to a Work Session for audit—the server enforces this for MCP OAuth and browser-based auth. Pass purpose to say what this particular command is for, in one or two sentences, whenever the command is not trivially routine: the assessor judges it with the purpose in hand, and a command that would otherwise queue for a human may clear on its own. State a fact local to this host that the Work Session description does not already imply; general knowledge adds nothing the assessor does not have, and a purpose cannot lower a command\'s intrinsic risk. If you omit it the gate may hold the command and ask—a status of purpose_required, which you answer with state_command_purpose within about a minute. A purpose over 2000 characters is trimmed to fit rather than refused, and the response then carries purpose_truncated: true—the assessor judges what was sent, so keep it short enough to survive whole. When to use: the recommended way to run a command on a server. Related: execute_command_multi_server (run on multiple servers), state_command_purpose (answer a held command\'s purpose demand), list_commands (browse history), work_session_create (create a Work Session). Note: Default timeout is 300 seconds (5 minutes).',
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
    purpose: str | None = None,
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
        purpose=purpose,
        # Only when this call will still be here when the verdict lands.
        # Verification runs at delivery, not at submission
        # (`Command.execute_all_scheduled` filters `scheduled_at__lte=now`), so
        # a command scheduled for later—or queued behind a `run_after` chain
        # that outlasts the hard cap—is judged long after this call has timed
        # out. Declaring support there opens a demand nobody is left to answer,
        # which parks the command for the full deadline and then drops it into
        # the human queue: exactly the cost the fleet tool declines to pay.
        purpose_demand_supported=not scheduled_at and not run_after,
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

    response = await _poll_command_result(
        command_id=command_id,
        server_id=server_id,
        command=command,
        workspace=workspace,
        shell=shell,
        timeout=timeout,
        region=region,
        token=token,
    )
    if _purpose_was_truncated(purpose):
        response['purpose_truncated'] = True
    return response


async def _poll_command_result(
    command_id: str,
    workspace: str,
    timeout: int,
    region: str,
    token: str | None,
    server_id: str = '',
    command: str = '',
    # Empty, not 'system': the default is what a caller who never chose a shell
    # gets echoed back, and reporting a shell the command may not have run under
    # is the misleading metadata this echo exists to avoid.
    shell: str = '',
) -> dict[str, Any]:
    """Wait for a submitted command to reach a state worth reporting.

    Shared by ``execute_command`` and ``state_command_purpose``: answering a
    purpose demand puts the command back on exactly the path a never-parked one
    takes, so the wait after the answer has to be the same wait.
    """
    # A caller that did not submit the command—state_command_purpose—knows
    # neither the server nor the line. Echo only what is known: the polled row
    # carries both anyway, and an empty string reads as a real value where an
    # absent key reads as "not supplied".
    echo = {
        key: value
        for key, value in (
            ('server_id', server_id),
            ('command', command),
            ('shell', shell),
        )
        if value
    }

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
                region=region,
                workspace=workspace,
                details=result,
                **echo,
            )

        if isinstance(result, dict):
            status = result.get('status', '')

            # handled_at is set once the agent reports the result (status then
            # becomes 'success'/'failed'); the Command API has no 'finished_at'.
            if result.get('handled_at') is not None:
                response = success_response(
                    data=result,
                    command_id=command_id,
                    region=region,
                    workspace=workspace,
                    **echo,
                )
                _attach_sudo_denial(response, result)
                return response

            match status:
                # Parked for its purpose (ADR 0052). No approval request exists
                # and none will until the re-judgment says so, so this returns
                # rather than polling: the demand is answered by this agent, and
                # the window is short enough that burning it on sleep wastes the
                # one chance the command gets.
                case 'awaiting_purpose':
                    return _purpose_required_response(
                        command_id=command_id,
                        region=region,
                        workspace=workspace,
                        deadline_seconds=_remaining_purpose_window(
                            result.get('purpose_requested_at')
                        ),
                        **echo,
                    )

                # HITL verification gate: a human must approve out-of-band
                # (ADR 0015); polling would only burn the timeout window.
                case 'awaiting_approval':
                    return pending_approval_response(
                        'Command is awaiting human approval. A human must '
                        'approve it out-of-band (Alpacon web console or Slack); '
                        'it then runs automatically. Wait, then retrieve the '
                        f'result via list_commands. {DO_NOT_RESUBMIT}: a '
                        'resubmission needs its own approval and may '
                        'double-execute the command.',
                        category='COMMAND_AWAITING_APPROVAL',
                        command_id=command_id,
                        region=region,
                        workspace=workspace,
                        **echo,
                    )

                # Terminal non-approval statuses: the command will not produce a
                # result (denied/rejected never run; stuck gave up), so fail
                # fast instead of polling until timeout. ('error' is omitted:
                # the server's compute_status never emits it given the
                # scheduled_at default, so it is unreachable here.)
                case 'denied' | 'rejected' | 'stuck':
                    return error_response(
                        f'Command failed with status: {status}',
                        command_id=command_id,
                        region=region,
                        workspace=workspace,
                        details=result,
                        **echo,
                    )

                # Command still in progress—reset deadline (within hard cap) so
                # a slow AI verification or delayed delivery does not time out a
                # command that is still advancing. Covers both pre-execution
                # states (queued/scheduled/delivered/verifying) and execution
                # (running). 'acked' is intentionally absent: compute_status
                # returns 'running' once acked_at is set, so it is never
                # emitted.
                case 'running' | 'verifying' | 'delivered' | 'queued' | 'scheduled':
                    deadline = min(loop.time() + timeout, hard_deadline)

        await asyncio.sleep(1)

    return error_response(
        f'Command execution timed out after {timeout} seconds',
        error_type='timeout',
        command_id=command_id,
        region=region,
        workspace=workspace,
        **echo,
    )


@mcp_tool_handler(
    description='Answer the purpose demand on a command the verification gate is holding, then wait for the outcome. Use this when execute_command returned status "purpose_required"; the command_id is in that response. The command re-enters judgment once with your purpose attached and this call returns whatever that second verdict produces—the command output when it clears, an approval-pending result when a human is still needed, or an error when it is denied. Answer promptly: the demand expires in about a minute, and there is exactly one demand per command, so a late or second answer is refused. Write a purpose that states a fact local to this host which the Work Session description does not already imply. General knowledge carries nothing the assessor lacks, a purpose cannot lower the command\'s intrinsic risk or outrank the session description, and an attempt to argue the verdict down is reported and denied. Only the principal that submitted the command may answer. When to use: only in response to a purpose_required result. Related: execute_command (pass purpose up front and skip this round trip entirely).',
    annotations=ADDITIVE,
    meta={'anthropic/searchHint': 'command purpose demand answer held justification'},
)
async def state_command_purpose(
    command_id: str,
    purpose: str,
    workspace: str,
    timeout: int = 300,
    region: str = '',
    **kwargs,
) -> dict[str, Any]:
    """Answer a parked command's purpose demand and wait for the re-judgment."""
    token = kwargs.get('token')

    if not purpose.strip():
        return error_response(
            'A purpose is required: the server refuses a blank answer and the '
            'command only gets one demand.',
            command_id=command_id,
            region=region,
            workspace=workspace,
        )

    answer = await _answer_purpose_demand(
        command_id=command_id,
        purpose=purpose,
        workspace=workspace,
        region=region,
        token=token,
    )

    if err := unwrap_http_result(
        answer,
        # The server answers a settled command and a bystander's answer with the
        # same code on purpose, so this cannot tell the agent which it was.
        default_message=(
            'The purpose was not accepted. Either the demand already expired and '
            'the command moved on, it was already answered, or this credential '
            'did not submit the command. Do not resubmit the command: check its '
            'state with list_commands.'
        ),
        command_id=command_id,
        region=region,
        workspace=workspace,
    ):
        return err

    # The polled row carries the server and the command line, so neither has to
    # be re-stated here—and `server_id` is a validated tool parameter, so
    # accepting one this call does not need would only invite a rejected UUID.
    return await _poll_command_result(
        command_id=command_id,
        workspace=workspace,
        timeout=timeout,
        region=region,
        token=token,
    )


@mcp_tool_handler(
    description='Run the same shell command on multiple servers simultaneously or sequentially. Returns per-server results with success/failure status. Requires ACL permission. Do not prefix the command with sudo by default: unless a Work Session sudo policy already covers the command, a sudo invocation either routes to human-in-the-loop approval and stalls that server\'s command until a human acts—once per server—or is denied outright with no request anyone can approve. The denial surfaces on that server\'s list_commands entry: check sudo_denial.category there before waiting; a sudo_hint with no sudo_denial is a hard denial that creates no request, so do not wait on it. Use sudo only when the command genuinely requires root and the Work Session carries the "sudo" scope. Pass work_session_id to link commands to a Work Session for audit—the server enforces this for MCP OAuth and browser-based auth. Pass purpose to state what the batch is for; it rides every submission and the assessor judges each command with it in hand. Unlike execute_command this tool never waits, so it is never asked for a purpose after the fact—stating it up front is the only chance. A purpose over 2000 characters is trimmed rather than refused, and the response then carries purpose_truncated: true. When to use: batch operations like deploying configs, checking status, or running diagnostics across a fleet. Related: execute_command (single server), work_session_create (create a Work Session). Note: Set parallel=false for sequential execution. This submits commands without waiting for results—use list_commands to check status.',
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
    purpose: str | None = None,
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
            purpose=purpose,
            # Nothing here waits on a submission, so a demand would hold every
            # command for the deadline and be answered by no one (ADR 0052).
            region=region,
            token=token,
        )

    deploy_results: dict[str, Any] = {}
    successful_count = 0
    failed_count = 0
    purpose_truncated = _purpose_was_truncated(purpose)

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

    response = success_response(
        deploy_shell_results=deploy_results,
        command=command,
        total_servers=len(server_ids),
        successful_count=successful_count,
        failed_count=failed_count,
        execution_type='parallel' if parallel else 'sequential',
        region=region,
        workspace=workspace,
    )
    if purpose_truncated:
        response['purpose_truncated'] = True
    return response
