# Work Sessions

A Work Session is the approved window an agent works inside: which servers, which scopes, which OS account, until when. A browser sign-in, which the hosted server uses, must attach one to every command and file transfer. Static API tokens are not gated, so a flow that works with a token can be refused after a browser sign-in.

## Open one session per task

- Reuse the session that already covers the task. Find it with `work_session_list` and pass its id as `work_session_id` on every command and transfer.
- Never open a second session while one is pending; the result says so in `next_action`, and the second request only waits beside the first.
- Ask `work_session_create` for what the whole task needs: every target server, the `scopes`, an `expires_at` long enough for the work, and a `description` the approver can judge.
- Scopes: `command` runs `execute_command` and `execute_file`, `webftp` moves files, `tunnel` forwards ports, and `sudo` elevates. `execute_file` with `write_file` or `read_from_server` also moves the file, so it needs `webftp` as well as `command`. Request `sudo` only when the task truly needs root. Interactive Websh access is not available to an agent; asking for the `websh` scope is refused with `work_session_scope_not_allowed`.
- To run as another OS account such as `root`, set `target_account_username` at creation. The session approves that one account; pass the same account as `username` on each command. `work_session_update` cannot change the account, so a different account needs a new session, or a person who changes the session for you.

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

## Closing

Call `work_session_close` when the task's commands and transfers are done, on a session you opened for the task. Leave a session you reused open; whoever opened it closes it. Closing ends the window and starts the session's security analysis. It is final, so do it only when the work is finished.

## Gate refusals

A command or transfer the session does not cover fails before it runs with `status="error"`, a `code`, and a `next_action`. Follow `next_action`; none of these waits for a person on its own.

- `work_session_required`: no session attached. Create one and pass its id.
- `work_session_not_usable`: the session is finished. Create a new one.
- `work_session_expired`: the session ran out. Create a new one; its `next_action` may suggest extending, but an expired session cannot be extended.
- `work_session_scope_not_allowed`: the scope is missing. Add it with `work_session_update(scopes=[...])`, keeping the existing scopes; the change may wait for approval.
- `work_session_server_not_allowed`: the server is not in the session. Add it with `work_session_update(servers=[...])`, keeping the existing servers.
- `work_session_assignee_mismatch`: the session belongs to someone else. Use your own.

`work_session_not_active` is reported as `pending_approval` with `category="WORK_SESSION_PENDING"`: wait for the session as above.
