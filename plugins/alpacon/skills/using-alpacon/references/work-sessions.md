# Work Sessions

A Work Session is the approved window an agent works inside: which servers, which scopes, which OS account, until when. Personal API tokens, MCP OAuth and browser callers use an active, approved Work Session for command execution and REST file-transfer creation. The Alpacon server enforces this requirement; personal-token enforcement requires a server release that supports it. This MCP server adds no local authorization check. Service tokens retain their endpoint-specific authorization rules; ordinary reads and Work Session requests keep their existing permissions.

## Open one session per task

- Reuse the session that already covers the task. Find it with `work_session_list` and pass its id as `work_session_id` on every command and transfer.
- Never open a second session while one is pending; the result says so in `next_action`, and the second request only waits beside the first.
- Ask `work_session_create` for what the whole task needs: every target server, the `scopes`, an `expires_at` long enough for the work, and a `description` the approver can judge.
- Scopes: `command` runs `execute_command` and `execute_file`, `webftp` moves files, `tunnel` forwards ports, and `sudo` elevates. `execute_file` with `write_file` or `read_from_server` also moves the file, so it needs `webftp` as well as `command`. Request `sudo` only when the task truly needs root. Interactive Websh access is not available to an agent; asking for the `websh` scope is refused with `work_session_scope_not_allowed`.
- To run as another OS account such as `root`, set `target_account_username` at creation. The session approves that one account; pass the same account as `username` on each command. `work_session_update` cannot change the account, so a different account needs a new session, or a person who changes the session for you. The Alpacon server refuses commands and file transfers as `root` with `workspace_direct_root_disabled` unless the workspace's `allow_direct_root` setting is on (off by default; `get_workspace_access_control` reads it), even when the session names `root`.

## Waiting for approval

A new session that needs approval comes back as `status="pending_approval"` with `category="WORK_SESSION_PENDING"`; otherwise it comes back as `success`, and `data.status` says whether it is active yet. For a pending one, tell the person it waits for approval in the Alpacon web console or Slack, then poll `work_session_get` and read `data.status`:

- `active`: proceed.
- `pending` or `approved`: keep waiting; do not run commands yet.
- `rejected`, `cancelled`, `expired`, `revoked`, or `completed` before you closed it: stop and tell the person. A finished session cannot be revived; a new task needs a new session.

The top-level `status` of `work_session_get` is `success` on any good read; the session state is `data.status`.

## Changing a session

- `work_session_update` with `servers` replaces the whole list, and so does `scopes`. Pass every server and scope the session keeps, not only the new one.
- On an approved or active session, widening it may wait for approval (`category="WORK_SESSION_MOD_PENDING"`); narrowing can apply at once. What waits does not apply until it is decided. Poll `work_session_get` until `pending_modification_request` clears, then check the session shows the change.
- `expires_at` changes only while the session is still pending. To get more time on an approved or active session, call `work_session_extend` with a `reason` after the session has started and before `expires_at` passes. It may wait for approval (`category="WORK_SESSION_EXTENSION_PENDING"`); the session keeps its old `expires_at` meanwhile. Do not send the extension again, which files a second request. Once a session has expired, open a new one.

## Servers you cannot see

A session names only the servers and clusters you can reach and counts the rest, with no name or id: `servers_hidden` and `clusters_hidden` beside `servers` and `clusters`, `old_hidden` and `new_hidden` in `adjustments.servers`, and `servers_hidden` in `pending_modification_request.changes` and `account_flag`. When a count is above 0, the result also carries `hidden_targets_note`.

- Never report the named list as the session's whole scope. Say how many more servers it covers that you cannot see.
- Never guess the counted servers. No tool names them for you; the session's assignee, the owner of its token, the direct maintainer of its Application, or a superuser sees them all. A workspace admin who is none of these may see only part of it too.
- A count above 0 means the session is not yours: do not reuse it, and do not try to change, extend or close it. Open your own session for your task.
- `old` and `new` in `adjustments.servers` are cut to the same reach: a server named in `old` and missing from `new` was removed, but a change to a counted server cannot be seen, so the two lists do not show every server added or removed.

## Closing

Call `work_session_close` when the task's commands and transfers are done, on a session you opened for the task. Leave a session you reused open; whoever opened it closes it. Closing ends the window and starts the session's security analysis. It is final, so do it only when the work is finished.

## Gate refusals

A command or transfer the session does not cover fails before it runs with `status="error"`, a `code`, and a `next_action`. Follow `next_action`; none of these waits for a person on its own.

- `work_session_required`: no session attached. Create one and pass its id.
- `work_session_not_usable`: the session is finished. Create a new one.
- `work_session_expired`: the session ran out. Create a new one; its `next_action` may suggest extending, but an expired session cannot be extended.
- `work_session_scope_not_allowed`: the scope is missing. Add it with `work_session_update(scopes=[...])`, keeping the existing scopes; the addition is queued for approval, even for an admin, unless the workspace uses advisory execution control.
- `work_session_server_not_allowed`: the server is not in the session. Add it with `work_session_update(servers=[...])`, keeping the existing servers.
- `work_session_assignee_mismatch`: the session belongs to someone else. Use your own.

`work_session_not_active` is reported as `pending_approval` with `category="WORK_SESSION_PENDING"`: wait for the session as above.

## A paused session

A critical denial or hold can pause the session. The result that paused it carries `work_session_paused: true`; later attempts fail with `error_code="session_paused"`; a queued command the pause closed carries `denial_code="superseded_by_pause"`; and `work_session_get` reports `data.status` `paused`. A command's marker and denial code are historical and remain after Resume: use the result's current `work_session_status`, or check `work_session_get` if it is unavailable, rather than treating that history as a new pause. While the session is paused, stop: do not retry, resubmit, or open another session to get around it. Tell the person that only a person can resume or end the session in the Alpacon web console, then poll `work_session_get`. Continue only once `data.status` is `active` again; resend a superseded command only then, and only if it is still needed. Stop polling and tell the person if it is `completed`, `revoked`, `expired`, `rejected` or `cancelled`; that session cannot resume.

A pending command approval can still be decided during a pause, but recorded approval does not release the command. Delivery needs both approval and Resume. Resume does not approve a held command or replay a refused one.
