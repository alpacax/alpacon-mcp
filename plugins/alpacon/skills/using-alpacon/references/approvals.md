# Approvals and sudo

## Who decides

A person decides every access approval: Work Sessions and changes to them, held commands, sudo, and sudo policy requests. They decide in the Alpacon web console or in Slack. No MCP tool approves or rejects these, and a `pending_approval` result carries `approvable_by_agent: false`. Tell the person what waits and where, then follow the result's `next_action`.

## Next step by `category`

The `category` on a `pending_approval` result says what is waiting, and the right next step differs:

- `WORK_SESSION_PENDING`: the session is not active yet. Poll `work_session_get` until `data.status` is `active`, then go on. Do not open another session. See [work-sessions.md](work-sessions.md).
- `WORK_SESSION_MOD_PENDING`: a modification request from `work_session_update` waits. The session keeps its old settings meanwhile. Poll `work_session_get` until `pending_modification_request` clears, then check that the servers and scopes you asked for are there before relying on them. Do not send the update again, even when `next_action` says to retry.
- `WORK_SESSION_EXTENSION_PENDING`: a `work_session_extend` waits. The session keeps its old `expires_at`. Poll `work_session_get` until `expires_at` changes; do not send the extension again, which files a second request. A rejected extension leaves `expires_at` as it was, so if it stays unchanged, ask the person whether the extension was decided.
- `COMMAND_AWAITING_APPROVAL`: the command is held, and it runs on its own once approved. Keep its `command_id` and read the result with `check_command_status`. Do not run the command again, through `execute_command` or `execute_file`: a second submission needs its own approval and may run the command twice. When the result also carries `approval_lane: "assignee"`, the person you work for confirms it themselves in the Alpacon web console: tell them so, and do not wait for an approver or point them to Slack.
- `SUDO_POLICY_REQUEST_PENDING`: a `request_sudo_policy` request waits for an admin. Once it is approved, rerun the sudo command. Do not file the request again, which only creates a duplicate.
- `APPROVAL_DECISION_HUMAN_ONLY`: `explain_approval_decision` returns this. It is a fixed explanation, not a live request; there is nothing to wait for.

A held command that a person rejects, or whose request expires, comes back from `check_command_status` as an error with `rejection_cause` (`approval_rejected`, `approval_expired`, `approval_cancelled`, `approval_rule_changed`). See [refusals.md](refusals.md).

## Sudo

Do not prefix a command with `sudo` unless it needs root and the Work Session has the `sudo` scope. A sudo the session does not cover is refused inside the command, and the command result can still have `status="success"`. Read these fields on every command result, successful or not:

- `sudo_denial`: a person can resolve it. It carries a `category` and a `next_action` like a `pending_approval` result, but the command result's own `status` does not change. The sudo did not run, so rerun the command once the person has acted; the whole line runs again, not only the sudo part. This is the opposite of a held command.
- `sudo_hint` with no `sudo_denial`: a hard denial with no request behind it. Nobody can approve it, so do not wait and do not rerun it unchanged. Tell the person what the hint says.

Categories inside `sudo_denial`:

- `SUDO_APPROVAL_REQUIRED`: an approval request was created. Rerun after a reviewer approves it. When `sudo_denial` carries `held`, the server named the request: `held.expires_at` is the deadline for the decision (`null` when none is known), and `held.approval_request` is a reference to give the person, not a place to wait. Follow `wait_hint`: call `check_command_status` with the same `command_id` until `data.sudo_grant_status` reads `authorized`, then rerun the whole command; stop on `rejected` or `expired`. Approval does not resume the command, `held` turning `null` does not end the wait, and a rerun before the decision never reports it. Once `expires_at` has passed, an approval cannot be used, so rerun to request a new one.
- `SUDO_INTENT_DEVIATION`: the command was judged off-purpose for the session, and a request was created. Wait for the reviewer. If the session description understated the work it was always meant to cover, you may restate that purpose in prose with `work_session_update(description=...)`; never put command text there. The change itself is queued for approval, even for an admin or group manager, unless the workspace uses advisory execution control, so a reworded purpose is not a way around the reviewer.
- `SUDO_PRESENCE_REQUIRED`: a person must complete a fresh MFA check. Rerun after they do.
- `SUDO_NO_WORKSESSION_POLICY`: no session-authorized sudo policy on the session covers this command. A person must set `session_authorized` on a Work Session sudo policy in the web console. `request_sudo_policy` cannot ask for a session-authorized policy, so it does not unblock this command. Rerun once the policy is live.
- `SUDO_POLICY_MFA_REQUIRED`: a policy covers the command but cannot be used without a person present. A person must change the policy in the web console; nothing is waiting until they do.
- `WORK_SESSION_SCOPE_NOT_ALLOWED`: the session lacks the `sudo` scope. Add it with `work_session_update(scopes=[...])`, keeping the existing scopes; the addition is queued for approval, even for an admin, unless the workspace uses advisory execution control.

Hard denials (`sudo_hint` only) include `SUDO_RISK_DENIED`, `SUDO_COMMAND_NOT_AUTHORIZED`, `SUDO_SESSION_MISSING`, `SUDO_NO_AUTHORITY`, and `WORKSPACE_SUDO_WITH_MFA_DISABLED`.

## Explaining a wait or a refusal

- `get_approval_request` and `list_approval_requests` show the live state of approval requests: who asked, what, and whether it is decided.
- `explain_approval_decision` returns a fixed explanation that approval is a human decision. It makes no request, so it never tells you the current state.
- `check_command_status` shows where a held command stands.

## Certificate requests

`approve_sign_request`, `deny_sign_request`, `approve_revoke_request`, and `deny_revoke_request` decide certificate sign and revoke requests. These are ordinary admin actions, not access approvals: Alpacon lets whoever manages the CA's host and holds the needed permissions decide them, the requester included. This skill is stricter. Call one only when the person explicitly asks you to decide that specific request, and never approve a request you filed yourself.
