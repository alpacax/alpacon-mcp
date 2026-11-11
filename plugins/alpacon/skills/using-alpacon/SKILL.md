---
name: using-alpacon
description: Rules for operating servers through the Alpacon MCP tools—server UUIDs, Work Sessions, human-only approvals, sudo and refusal results, MFA, and never resending a write whose outcome is unknown. Use whenever a task calls an Alpacon tool such as list_servers, execute_command, execute_file, or work_session_create, whatever prefix the client gives it, or asks to inspect, run commands on, transfer files to, or change servers in an Alpacon workspace.
---

# Using Alpacon

Alpacon is reached only through its MCP tools. Clients name them differently (`list_servers` may appear behind a prefix such as `mcp__alpacon__` or `mcp__plugin_alpacon_alpacon__`); this skill uses the bare tool names. When a call fails on a read or a connection error, report the exact error, try another Alpacon tool that answers the same question, or ask the person for the missing sign-in or permission. A refusal or a `pending_approval` result is not such a failure: follow the sections below, and never move the same work to another tool to get past it. Never fall back to the `alpacon` CLI, `ssh`, or another shell route.

## Find the workspace and server

1. Call `list_workspaces` and use a workspace name exactly as it returns it. Pass `region` (`ap1` or `us1`) only when the same workspace appears in both.
2. Call `list_servers` and take the server's `id`. Every `server_id` and `servers` argument is a UUID; a server name is refused before the request is sent. The list is paginated, so follow `next` when `count` is larger than the page.

## Read every result before the next call

- Branch on `status`, not on prose: `success`, `error`, `pending_approval`, `purpose_required`, and `mfa_required` are the common values. For any other value, read `message` and `next_action`.
- When a result carries `next_action`, do what it says. `requires_human_approval: true` means a person decides; `approvable_by_agent: false` means no tool of yours can.
- A command result can say `success` and still carry `sudo_denial` or `sudo_hint`: the sudo inside it did not run. With `sudo_denial`, a person can resolve it; rerun the command after they act, knowing the whole line runs again. With `sudo_hint` alone, it is a hard denial: do not wait for it and do not rerun it unchanged.
- A refusal carrying `rejection_cause`, `gate`, or `missing` is not cleared by resending it unchanged. Follow its hint: some ask you to fix the call, some to wait for a person's decision or MFA, after which the same call can succeed.

## Run commands inside a Work Session

Personal API tokens, MCP OAuth and browser callers use an active, approved Work Session for command execution and REST file-transfer creation. The Alpacon server enforces this requirement; personal-token enforcement requires a server release that supports it. This MCP server adds no local authorization check. Service tokens retain their endpoint-specific authorization rules.

1. Reuse a session that covers the task (`work_session_list`), or open one with `work_session_create`: the `scopes` (`command`; add `webftp` for transfers and for `execute_file` with `write_file` or `read_from_server`; `sudo` only to elevate), every target server UUID, `expires_at`, and a `description` that tells the approver which servers, what action, and what will not be touched. To run as another OS account such as `root`, set `target_account_username` here and pass the same account as `username` on each command.
2. If it returns `status="pending_approval"`, tell the person the session waits for approval, then poll `work_session_get` until `data.status` is `active`. Stop on `rejected`, `cancelled`, `expired`, `revoked`, or `completed`.
3. Pass its id as `work_session_id` on every command and transfer. When the task is done, close a session you opened for it with `work_session_close`; leave a session you reused open.

Give each non-routine command a `purpose` naming a fact about this host. A `status="purpose_required"` result is not an approval request: the command is already held under its `command_id`. Answer it with `state_command_purpose` within the deadline; if the deadline passes, read the command with `check_command_status` and do not resubmit it. Send a script or heredoc through `execute_file`, not `execute_command`.

## Approvals belong to people

A person approves Work Sessions, held commands, sudo, and sudo policy requests, in the Alpacon web console or Slack. No tool approves these, and the agent must not try. When a result has `status="pending_approval"`, show the person what is waiting and where it is decided, then act on its `category`:

- `COMMAND_AWAITING_APPROVAL`: the command runs on its own once approved. Read its result with `check_command_status` and the `command_id`. Do not submit it again, through `execute_command` or `execute_file`; a second submission may run it twice.
- `WORK_SESSION_PENDING`, `WORK_SESSION_MOD_PENDING`, `WORK_SESSION_EXTENSION_PENDING`: poll `work_session_get` until the session shows the decision. Do not send the create, update, or extension again.
- `SUDO_POLICY_REQUEST_PENDING`: rerun the sudo command once the policy request is approved. Do not file the request again.

When a refusal says the workspace does not allow this agent (`error_code="work_session_agent_not_allowed"`, `missing="allowed_agent"`, usually on `work_session_create`), stop and tell the person: only a workspace admin can change it, and retrying or another route will not succeed.

Certificate sign and revoke requests have their own approve and deny tools. Use them only when the person explicitly asks you to decide that specific request. Never approve a request you filed yourself, even though Alpacon would let you.

## Confirm before destructive calls

Before a call to a tool marked destructive, such as a delete, deny, cancellation, removal, revocation, or token rotation, restarting or upgrading a server's agent, unregistering a server, or a bulk ACL change, say what it will change and wait for the person to confirm, unless they already asked for that exact change. Closing a Work Session you opened for this task, once the task is done, needs no extra confirmation.

## A write whose outcome is unknown

An error carrying `outcome_unknown: true` means the request may have reached the server and may have run. Do not resend it. For a command, check `list_commands` for that server, and resubmit only if it is not there. `list_commands` returns the newest 20 by default, so raise `limit` until the oldest entry predates the call; it returns at most 100, so when 100 newer commands fill the page, or the history cannot settle it, ask a person to check before resubmitting. For another write, read the object back first, for a Work Session with `work_session_list`. A command that timed out while waiting is different: it has a `command_id`, so read it with `check_command_status`.

## When to read the references

- [approvals.md](references/approvals.md): any `pending_approval`, sudo result, or question about why something waits.
- [refusals.md](references/refusals.md): an `error` with `rejection_cause`, `gate`, `missing`, a plan limit, or a credential refusal.
- [work-sessions.md](references/work-sessions.md): changing, extending, or closing a session, or a Work Session gate `code`.
- [files.md](references/files.md): `execute_file`, WebFTP transfers, `file_exec_*` codes.
- [mfa.md](references/mfa.md): `status="mfa_required"` or `show_mfa`.
- [fleet.md](references/fleet.md): `execute_command_multi_server`, `wait=false`, timeouts.
- [reading-results.md](references/reading-results.md): paging through lists, or empty metrics.
