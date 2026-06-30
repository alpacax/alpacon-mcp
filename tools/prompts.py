"""MCP prompts — workflow guides that teach an agent the Alpacon operating discipline.

Unlike tools (which act) and resources (which expose data), these prompts inject the
*rules* an MCP agent must follow: every infrastructure action is wrapped in a Work
Session, approval gates route to a human (an agent can never self-approve), and denials
are structured so the agent self-corrects instead of brute-forcing. Grounded in the
alpacon-handbook product model (ACCESS -> EXECUTION -> AUDIT, Work Session as the single
primitive). Each prompt returns static guidance text; arguments only scope the context.
"""

from server import mcp


@mcp.prompt()
def work_session_workflow(intent: str, servers: str = '') -> str:
    """ACCESS: how to scope and open a Work Session before any infrastructure action."""
    target = f'\nTarget servers (UUIDs): {servers}' if servers else ''
    return f"""You are operating Alpacon as an AI agent over MCP. Goal: {intent}{target}

In Alpacon there is NO out-of-session path: every command, file transfer, or connection
must belong to an approved Work Session. Follow this order.

1. Declare intent and minimal scope, then call `work_session_create`.
   - Pass the goal above as the session intent.
   - As an agent (MCP channel) you can scope `command` and `webftp`/`cp` directly; `sudo`
     is available but every sudo invocation routes to human approval (HITL). `websh` and
     `editor` require human presence (MFA) and are NOT available to you.
   - Scope to the specific target servers only — do not request workspace-wide access.

2. Handle the result by status:
   - `pending_approval`: you cannot approve your own work — an agent has no presence (MFA),
     so the session routes to a human approver. Surface the request to a human and WAIT.
     Do not retry-spam.
     Use `explain_approval_decision` to relay why a human must act out-of-band.
   - `error` with a gate `code` (`work_session_required`, `work_session_scope_not_allowed`,
     `work_session_server_not_allowed`, `work_session_expired`, ...): read `next_action`,
     narrow the scope or server set, and retry deliberately — never brute-force.

3. Once the session is `active`, proceed to execution. Confirm with `work_session_get`
   and read the session state from `data.status` (the top-level `status` is just the
   tool-call result, always `success` on a good call). Follow the `guarded_execution`
   workflow for the running commands.

Read-only context needs no session: `alpacon://servers/{{region}}/{{workspace}}` lists
servers and their UUIDs for the calls above.
"""


@mcp.prompt()
def guarded_execution(work_session_id: str) -> str:
    """EXECUTION: run commands and transfers inside an approved session, handling HITL."""
    return f"""You are executing work inside Work Session `{work_session_id}`. Every action
here is judged in real time and recorded. Follow this discipline.

1. Confirm the session is `active` with `work_session_get` before any action. Read the
   session state from `data.status`, not the top-level `status` (that is just the
   tool-call result, always `success` on a good call). Any other state (`pending`,
   `approved`, `rejected`, `expired`, `revoked`, `completed`) means stop — do not execute.

2. Run actions through the session:
   - Commands: `execute_command` (single host) or `execute_command_multi_server` (fleet).
   - File transfers: `webftp_upload_file` / `webftp_download_file`.

3. Expect risk verdicts. Each action is scored; a HIGH-risk command or any `sudo`
   invocation routes to human-in-the-loop. You cannot self-approve (an agent has no
   presence/MFA). When a result is `pending_approval`, surface it to a human and wait.

4. On a denial, read the structured `code` and `next_action` and self-correct — adjust
   the command, narrow the target, or escalate to a human. Never re-run the identical
   denied command in a loop.

5. When the work is done, call `work_session_close` to mark it completed and trigger the
   AI security analysis over the session.
"""


@mcp.prompt()
def incident_response(server_id: str = '', workspace: str = '') -> str:
    """Scenario: triage read-only first, then bounded remediation inside a Work Session."""
    scope = server_id or workspace or 'the affected scope'
    return f"""Respond to an incident on {scope}. Triage before you touch anything.

1. Triage (no Work Session needed — read-only):
   - Active alerts: `alpacon://alerts/active/{{region}}/{{workspace}}` or `list_alerts`.
   - Server state: `get_server_overview`, `get_cpu_usage`, `get_memory_usage`.
   - Recent events: `list_events`. Identify the likely cause before acting.

2. If remediation requires running commands, do NOT execute directly. Open a Work Session
   via the `work_session_workflow`: scope it to the affected server(s) only, with the
   `command` scope, and wait for human approval.

3. Execute remediation under the `guarded_execution` workflow. Risky remediation
   (restarts, sudo, destructive commands) will route to human-in-the-loop — surface it
   and wait; you cannot self-approve.

4. After the incident is resolved, `work_session_close` the session to mark it complete
   and trigger AI security analysis for the audit trail.
"""


@mcp.prompt()
def security_audit(work_session_id: str = '', server_id: str = '') -> str:
    """AUDIT: pick the right one of Alpacon's five audit lenses for the question."""
    anchor = work_session_id or server_id or 'the workspace'
    return f"""Audit privileged activity for {anchor}. Choose the lens that fits the question.

- Lens 1 — Session forensic ("what happened in this session?"):
  `work_session_timeline` for the unified command/transfer/risk timeline.
- Lens 2 — Event forensic, cross-session ("every sudo / every `rm -rf` / every transfer
  of /etc/*"): `list_server_logs`, `list_webftp_logs`, `search_events`.
- Lens 3 — Decision audit ("why was access granted, who approved, when revoked?"):
  `list_approval_requests`, `get_approval_request`.
- Lens 4 — Mutation audit ("what changed in workspace state — roles, tokens, policy?"):
  `list_activity_logs`, `get_activity_log`.
- Lens 5 — AI-derived analysis (attack patterns, MITRE ATT&CK mapping, kill-chain):
  `list_session_analyses`, then `get_session_analysis_detail` for a specific session.

Start from the anchor above, then link findings back to the Work Session that contains
each event — the session is the primary primitive for the audit story.
"""
