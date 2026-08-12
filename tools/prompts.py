"""MCP prompts—workflow guides that teach an agent the Alpacon operating discipline.

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
   - Required arguments: `workspace`, `scopes` (list), `servers` (list of UUIDs),
     `expires_at` (ISO 8601), and `description`—fill them all or the call is rejected.
   - Pass the goal above as the session `description` (the API has no `intent` field).
     The description is prose for the human who approves the session—never a list of
     commands. Nothing in it is executed; commands run via `execute_command` in step 3.
   - Valid scopes are `command`, `webftp`, `tunnel`, and `sudo`. As an agent (MCP channel)
     you can request `command`/`webftp`/`tunnel` directly; `sudo` is available but unless a
     Work Session sudo policy already covers the command, a sudo invocation routes to human
     approval (HITL)—and some are denied outright, leaving no request a human can unblock.
     Request `sudo` only when the work genuinely requires root. Interactive `websh`/`editor`
     access requires human presence (MFA) and is NOT available to you.
   - Scope to the specific target servers only—do not request workspace-wide access.

2. Handle the result by status:
   - `pending_approval`: you cannot approve your own work—an agent has no presence (MFA),
     so the session routes to a human approver. Surface the request to a human and WAIT.
     Do not retry-spam.
     Use `explain_approval_decision` (pass `workspace`) to relay why a human must
     act out-of-band.
   - `error` with a gate `code` (`work_session_required`, `work_session_scope_not_allowed`,
     `work_session_server_not_allowed`, `work_session_expired`, ...): read `next_action`,
     narrow the scope or server set, and retry deliberately—never brute-force.

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
   `approved`, `rejected`, `cancelled`, `expired`, `revoked`, `completed`) means stop:
   do not execute.

2. Run actions through the session. Pass `work_session_id` on every call (it falls back to
   the `ALPACON_WORK_SESSION` env var if omitted; without either the server rejects the
   scoped action):
   - Commands: `execute_command` (single host) or `execute_command_multi_server` (fleet).
   - File transfers: `webftp_download_file`. `webftp_upload_file` is local-mode only—in
     remote/OAuth mode it returns `remote_mode_unsupported`.

3. Expect risk verdicts. Each action is scored. A HIGH-risk command routes to
   human-in-the-loop, and so does any `sudo` invocation that no Work Session sudo policy
   already covers. You cannot self-approve (an agent has no presence/MFA). When a result
   is `pending_approval`, surface
   it to a human and wait—but read the category first: a hard denial such as
   `SUDO_RISK_DENIED` creates no request anyone can approve, so waiting on it never ends
   (see step 4). So do not prefix commands with `sudo` by default—a needless `sudo` blocks
   the whole session on a human. Use it only when the command genuinely requires root.

4. On a denial, read the structured category and `next_action` and self-correct—the
   field is `code` on an `error` result and `category` on a `pending_approval` one. Adjust
   the command, narrow the target, or escalate to a human. Never re-run the identical
   denied command in a loop. Some denials have a second path you can start yourself:
   `SUDO_INTENT_DEVIATION` means the command was judged off-purpose for the session, so
   besides waiting for the approval it created you may restate in prose what the session
   is for with `work_session_update(description=...)`—never paste the command text into
   the description, which is read by the approver and never executed.
   `WORK_SESSION_SCOPE_NOT_ALLOWED` means you may add the missing scope with
   `work_session_update(scopes=[...])`. Either edit is normally queued for its own
   approval, so it is a correction, not a way around the reviewer.

5. When the work is done, call `work_session_close` to mark it completed and trigger the
   AI security analysis over the session.
"""


@mcp.prompt()
def incident_response(server_id: str = '', workspace: str = '') -> str:
    """Scenario: triage read-only first, then bounded remediation inside a Work Session."""
    scope = server_id or workspace or 'the affected scope'
    return f"""Respond to an incident on {scope}. Triage before you touch anything.

1. Triage (no Work Session needed—read-only):
   - Active alerts: `alpacon://alerts/active/{{region}}/{{workspace}}` or `list_alerts`.
   - Server state: `get_server_overview`, `get_cpu_usage`, `get_memory_usage`.
   - Recent events: `list_events`. Identify the likely cause before acting.

2. If remediation requires running commands, do NOT execute directly. Open a Work Session
   via the `work_session_workflow`: scope it to the affected server(s) only, with the
   `command` scope, and wait for human approval.

3. Execute remediation under the `guarded_execution` workflow. Risky remediation
   (restarts, sudo, destructive commands) will route to human-in-the-loop—surface it
   and wait; you cannot self-approve.

4. After the incident is resolved, `work_session_close` the session to mark it complete
   and trigger AI security analysis for the audit trail.
"""


@mcp.prompt()
def security_audit(work_session_id: str = '', server_id: str = '') -> str:
    """AUDIT: pick the right one of Alpacon's five audit lenses for the question."""
    anchor = work_session_id or server_id or 'the workspace'
    return f"""Audit privileged activity for {anchor}. Choose the lens that fits the question.

- Lens 1—Session forensic ("what happened in this session?"):
  `work_session_timeline` for the unified command/transfer/risk timeline.
- Lens 2—Event forensic, cross-session ("every sudo / every `rm -rf` / every transfer
  of /etc/*"): `list_server_logs`, `list_webftp_logs`, `search_events`.
- Lens 3—Decision audit ("why was access granted, who approved, when revoked?"):
  `list_approval_requests`, `get_approval_request`.
- Lens 4—Mutation audit ("what changed in workspace state—roles, tokens, policy?"):
  `list_activity_logs`, `get_activity_log`.
- Lens 5—AI-derived analysis (attack patterns, MITRE ATT&CK mapping, kill-chain):
  `list_session_analyses`, then `get_session_analysis_detail` for a specific session.

Start from the anchor above, then link findings back to the Work Session that contains
each event—the session is the primary primitive for the audit story.
"""
