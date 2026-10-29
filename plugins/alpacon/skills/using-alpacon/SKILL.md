---
name: using-alpacon
description: Rules for operating servers through the Alpacon MCP tools—server UUIDs, Work Sessions, human-only approvals, and retrying a write whose outcome is unknown. Use whenever a task calls an mcp__alpacon tool or asks to inspect, run commands on, or change servers in an Alpacon workspace.
---

# Using Alpacon

Alpacon is reached only through its MCP tools. When a call fails, report the exact error, try another MCP tool that answers the same question, or ask the user for the missing sign-in or permission. Never fall back to the `alpacon` CLI, `ssh`, or another shell route.

## Find the workspace and server

1. Call `list_workspaces` and use a workspace name exactly as it returns it. Pass `region` (`ap1` or `us1`) only when the same workspace appears in both.
2. Call `list_servers` and take the server's `id`. Every `server_id` and `servers` argument is a UUID; a server name is refused before the request is sent. The list is paginated, so follow `next` when `count` is larger than the page.

## Run commands inside a Work Session

A browser sign-in, which the hosted server uses, must hold an active Work Session before `execute_command`, `execute_file`, or a WebFTP transfer.

1. Look for a usable session with `work_session_list`, or open one with `work_session_create`: `scopes` (`command`, `webftp`, and `sudo` only to elevate from another account), the server UUIDs, `expires_at`, and a `description` that tells the approver which servers, what action, and what will not be touched. To run as another OS account such as `root`, set `target_account_username` here and pass the same account as `username` on each command.
2. If it returns `status="pending_approval"`, tell the user it is waiting for a person, then poll `work_session_get` until `data.status` is `active`. Stop on `rejected`, `cancelled`, `expired`, `revoked`, or `completed`.
3. Pass its id as `work_session_id` on every command and transfer.

Give each non-routine command a `purpose` naming a fact about this host. A `status="purpose_required"` result is not an approval request: answer it with `state_command_purpose` within the deadline. Send a script or heredoc through `execute_file`, not `execute_command`.

## Approvals belong to people

No tool approves a request, and Claude must not try. When any tool returns `status="pending_approval"`, show the user what is waiting and where a person decides it (the Alpacon web console or Slack), then retry or read back once they say it is done.

## A write whose outcome is unknown

An error carrying `outcome_unknown: true` means the request may have reached the server and may have run. Do not resend it. For a command, check `list_commands` for that server, and resubmit only if it is not there. `list_commands` returns the newest 20 by default, so raise `limit` until the oldest entry predates the call; it returns at most 100, so when 100 newer commands fill the page, ask a person to check before resubmitting.
