# API reference

Complete reference for all Alpacon MCP Server tools and capabilities.

## 📌 Conventions

- **`workspace` is always required.** Every tool that talks to the API takes it.
- **`region` is optional.** Leave it out and the server resolves it from the workspace—via `token.json` in local mode, via the JWT claims in hosted mode. Supply it (`ap1`, `us1`) when one token spans several regions. An unresolvable region comes back as a validation error, not a silent default.
- **Server IDs are UUIDs**, never names. Get them from `list_servers`.
- **Work Session gate**: OAuth/browser callers must run command execution and file transfers inside an active Work Session; static API tokens bypass it. Blocked calls return `status="pending_approval"` or a `status="error"` with a `code` and `next_action`—see [Work session tools](#-work-session-tools).

## 📋 Response structure

All MCP tools follow a consistent response structure:

### Successful HTTP request
```json
{
  "status": "success",
  "data": { /* API response data */ },
  "server_id": "server-uuid",
  "region": "ap1",
  "workspace": "production"
}
```

### HTTP request with API error
```json
{
  "status": "success",  // HTTP request succeeded
  "data": {
    "error": "HTTP Error",
    "status_code": 403,  // Actual API error code
    "message": "Client error '403 Forbidden'...",
    "response": "Access denied"
  },
  "server_id": "server-uuid",
  "region": "ap1",
  "workspace": "production"
}
```

> **Note**: `"status": "success"` indicates successful HTTP communication. Check the `data.error` field for API-level errors like ACL permission issues (403/404).

## 🖥️ Server management tools

### `list_servers`
List all servers in a region and workspace.

**Parameters:**
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Array of server objects with ID, name, status, and metadata.

### `get_server`
Get detailed information about a specific server.

**Parameters:**
- `server_id` (string): Server ID to get details for
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Complete server information including hardware specs, status, and configuration.

### `list_server_notes`
List notes for a specific server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `create_server_note`
Create a new note for a server.

**Parameters:**
- `server_id` (string): Server ID
- `content` (string): Note content; capped at 512 characters
- `private` (boolean, optional): Hide the note from other workspace members
- `pinned` (boolean, optional): Pin the note; a server holds at most three pinned notes
- `mentioned_users` (array of strings, optional): User UUIDs to notify; accepted on create only
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_server_note` / `update_server_note` / `delete_server_note`
Read, partially update (`content`, `private`, `pinned`), or permanently delete a note by `note_id`.

### `update_server`
Rename or relabel a server's Alpacon entry. Does not touch the host itself.

**Parameters:**
- `server_id` (string): Server UUID
- `workspace` (string): Workspace name
- `name` (string, optional): New display name
- `description` (string, optional): New description
- `region` (string, optional): Region name

### `unregister_server`
Unregister a host from the workspace. The agent stays installed; bringing the host back needs a registration token.

**Parameters:** `server_id`, `workspace`, `region` (optional)

### `star_server`
Pin or unpin a server for the calling user. A personal preference flag, not a fleet-wide setting.

**Parameters:** `server_id`, `status` (boolean), `workspace`, `region` (optional)

### Agent and host actions

Each takes `server_id`, `workspace`, and an optional `region`.

- `restart_agent`: Restart the Alpacon agent process
- `shutdown_agent`: Stop the agent process
- `upgrade_agent`: Upgrade the agent to the latest version
- `update_information`: Re-collect hardware, OS, network, and package data
- `upgrade_system`: Upgrade all OS packages through the package manager
- `reboot_system`: Reboot the host
- `shutdown_system`: Power the host off

### Registration tokens (Alpamon)

- `list_registration_tokens`: `workspace`, `region` (optional), `page`, `page_size`
- `create_registration_token`: `workspace`, `name`, `description` (optional), `region` (optional)
- `delete_registration_token`: `token_id`, `workspace`, `region` (optional)
- `get_registration_guide`: `token_id`, `workspace`, `platform` (`debian`, `rhel`, `darwin`, `windows`), `server_name` (optional), `region` (optional). Returns the platform-specific install command

---

## 📊 Metrics and monitoring tools

### `get_cpu_usage`
Get CPU usage metrics for a server.

**Parameters:**
- `server_id` (string): Server ID to get metrics for
- `start_date` (string, optional): Start date in ISO format
- `end_date` (string, optional): End date in ISO format
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Example:**
```json
{
  "server_id": "server-123",
  "start_date": "2024-01-01T00:00:00Z",
  "end_date": "2024-01-02T00:00:00Z"
}
```

### `get_memory_usage`
Get memory usage metrics for a server.

**Parameters:** Same as `get_cpu_usage`

### `get_disk_usage`
Get disk usage metrics for a server.

**Parameters:**
- `server_id` (string): Server ID
- `device` (string, optional): Device path (e.g., '/dev/sda1')
- `partition` (string, optional): Partition path (e.g., '/')
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_network_traffic`
Get network traffic metrics for a server.

**Parameters:**
- `server_id` (string): Server ID
- `interface` (string, optional): Network interface (e.g., 'eth0')
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_disk_io`
Get disk I/O performance metrics for a server.

**Parameters:**
- `server_id` (string): Server ID
- `start_date` (string, optional): Start date in ISO format
- `end_date` (string, optional): End date in ISO format
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_top_servers`
Rank the top five servers by resource usage over the last 24 hours.

**Parameters:**
- `workspace` (string): Workspace name
- `metric_types` (string, optional): Comma-separated metrics to rank by (`cpu`, `memory`, `disk_io`, `traffic`); omit for all four
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `get_alert_rules`
Get alert rules for servers.

**Parameters:**
- `server_id` (string, optional): Server ID to filter rules
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_server_metrics_summary`
Get comprehensive metrics summary for a server.

**Parameters:**
- `server_id` (string): Server ID
- `hours` (integer, default: 24): Number of hours back to get metrics
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

---

## 💻 System information tools

### `get_system_info`
Get detailed system information for a server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Hardware specs, CPU details, memory info, and system identifiers.

### `get_os_version`
Get operating system version information.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `list_system_users`
List system users on a server.

**Parameters:**
- `server_id` (string): Server ID
- `username_filter` (string, optional): Username to search for
- `login_enabled_only` (boolean, default: false): Only return users that can login
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `list_system_groups`
List system groups on a server.

**Parameters:**
- `server_id` (string): Server ID
- `groupname_filter` (string, optional): Group name to search for
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `list_system_packages`
List installed system packages on a server.

**Parameters:**
- `server_id` (string): Server ID
- `package_name` (string, optional): Package name to search for
- `architecture` (string, optional): Architecture filter (e.g., 'x86_64')
- `limit` (integer, default: 100): Maximum number of packages to return
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_network_interfaces`
Get network interfaces information for a server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_disk_info`
Get disk and partition information for a server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Both disk and partition information in a single response.

### `get_system_time`
Get system time and uptime information.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_server_overview`
Get comprehensive overview of server system information.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Combined system info, OS version, time, network interfaces, and disk info.

---

## 🗂️ Event management tools

### `list_events`
List server events.

**Parameters:**
- `server_id` (string, optional): Server ID to filter events
- `reporter` (string, optional): Reporter name to filter events
- `limit` (integer, default: 50): Maximum number of events to return
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_event`
Get detailed information about a specific event.

**Parameters:**
- `event_id` (string): Event ID to get details for
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `search_events`
Search events by criteria.

**Parameters:**
- `search_query` (string): Search term to look for in events
- `server_id` (string, optional): Server ID to limit search scope
- `limit` (integer, default: 20): Maximum number of results to return
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

---

## 💻 Command API tools (requires ACL permission)

> ⚠️ **ACL configuration required**: Command API tools require pre-approved commands in your token's Access Control List (ACL). Configure permissions by clicking on your token in the Alpacon web interface → ACL settings.

### `execute_command`
Execute a command on a server and wait for the result.

**Parameters:**
- `server_id` (string): Server ID
- `command` (string): Command to execute. Do not prefix it with `sudo` by default: unless a Work Session sudo policy already covers the command, a sudo invocation either routes to human approval and blocks until a human acts, or is denied outright with no request anyone can approve. Check `sudo_denial.category` before waiting—a `sudo_hint` with no `sudo_denial` is a hard denial that creates no request
- `workspace` (string): Workspace name
- `shell` (string, default: "system"): Shell type
- `username` (string, optional): Username for execution
- `groupname` (string, default: "alpacon"): Group name
- `env` (object, optional): Environment variables
- `run_after` (array, optional): Command IDs to wait for before executing
- `scheduled_at` (string, optional): ISO 8601 datetime for scheduled execution
- `data` (string, optional): Stdin data
- `timeout` (integer, default: 300): Timeout in seconds
- `work_session_id` (string, optional): Work Session to run under; falls back to `ALPACON_WORK_SESSION`
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `list_commands`
List recent command history.

**Parameters:**
- `server_id` (string, optional): Filter by server ID
- `limit` (integer, default: 20): Maximum number of recent commands to return
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `execute_command_multi_server`
Execute a command on multiple servers simultaneously.

**Parameters:**
- `server_ids` (array): List of server IDs
- `command` (string): Command to execute. The same sudo rule as `execute_command` applies, per server: a needless `sudo` prefix stalls that server's command on a human approver, or is denied outright with no request anyone can approve
- `workspace` (string): Workspace name
- `shell` (string, default: "system"): Shell type
- `username` (string, optional): Username for execution
- `groupname` (string, default: "alpacon"): Group name
- `env` (object, optional): Environment variables
- `parallel` (boolean, default: true): Execute in parallel
- `work_session_id` (string, optional): Work Session to run under
- `region` (string, optional): Region name; resolved from the workspace when omitted

---

## 📁 WebFTP tools

### `webftp_session_create`
Create a new WebFTP session for file transfer.

**Parameters:**
- `server_id` (string): Server ID
- `workspace` (string): Workspace name
- `username` (string, optional): Username for FTP access (defaults to the authenticated user)
- `work_session_id` (string, optional): Work Session to attribute the session to
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `webftp_sessions_list`
Get list of WebFTP sessions.

**Parameters:**
- `server_id` (string, optional): Filter by server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `webftp_upload_file`
Upload a local file to a server using S3 presigned URLs.

**Parameters:**
- `server_id` (string): Server ID
- `local_file_path` (string): Absolute path to local file
- `remote_file_path` (string): Absolute path on server
- `workspace` (string): Workspace name
- `username` (string, optional): Username (defaults to authenticated user)
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `allow_overwrite` (boolean, default: true): Allow overwriting existing files

### `webftp_download_file`
Download a file or folder from a server to local storage.

**Parameters:**
- `server_id` (string): Server ID
- `remote_file_path` (string): Absolute path on server
- `local_file_path` (string): Absolute path for local download
- `workspace` (string): Workspace name
- `resource_type` (string, default: "file"): "file" or "folder" (folders download as .zip)
- `username` (string, optional): Username (defaults to authenticated user)
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `webftp_upload_content`
Upload base64-encoded bytes as a file, with no local file on disk. Useful in hosted mode, where the server has no access to your filesystem.

**Parameters:**
- `server_id` (string): Server ID
- `file_content` (string): Base64-encoded content
- `remote_file_path` (string): Absolute path on server
- `workspace` (string): Workspace name
- `file_name` (string, optional): Name to record for the upload
- `username` (string, optional): Username (defaults to authenticated user)
- `work_session_id` (string, optional): Work Session to attribute the transfer to
- `allow_overwrite` (boolean, default: true)
- `region` (string, optional): Region name

### `webftp_bulk_upload`
Upload several local files to one directory in a single operation.

**Parameters:** `server_id`, `local_file_paths` (array), `remote_directory`, `workspace`, `username` (optional), `work_session_id` (optional), `allow_overwrite`, `region` (optional)

### `webftp_bulk_download`
Download several files or folders as one ZIP archive.

**Parameters:** `server_id`, `remote_paths` (array), `local_file_path`, `workspace`, `username` (optional), `work_session_id` (optional), `region` (optional)

### `webftp_check_status`
Check the status of an in-flight transfer.

**Parameters:** `file_id`, `transfer_type` (`upload` or `download`), `workspace`, `region` (optional)

### `webftp_uploads_list`
List uploaded files (upload history).

**Parameters:**
- `workspace` (string): Workspace name
- `server_id` (string, optional): Filter by server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `webftp_downloads_list`
List download requests (download history).

**Parameters:**
- `workspace` (string): Workspace name
- `server_id` (string, optional): Filter by server ID
- `region` (string, optional): Region name; resolved from the workspace when omitted

---

## 🔐 Identity and access management (IAM)

> Manage users and groups with workspace-level isolation.

### User management

#### `list_iam_users`
List all IAM users in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `page` (integer, optional): Page number for pagination
- `page_size` (integer, optional): Users per page

**Example:**
```json
{
  "workspace": "production",
  "page": 1,
  "page_size": 20
}
```

**Returns:** Paginated list of users with metadata, groups, and creation dates.

#### `get_iam_user`
Get detailed information about a specific IAM user.

**Parameters:**
- `user_id` (string): IAM user ID
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Returns:** Complete user profile including permissions and group memberships.

#### `create_iam_user`
Create new IAM user with optional group assignment.

**Parameters:**
- `username` (string): Unique username
- `email` (string): Email address
- `workspace` (string): Workspace name
- `first_name` (string, optional): First name
- `last_name` (string, optional): Last name
- `is_active` (boolean, default: true): Active status
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Example:**
```json
{
  "username": "john.doe",
  "email": "john@company.com",
  "first_name": "John",
  "last_name": "Doe",
  "workspace": "production"
}
```

**Note:** Users have no writable `groups` field. Put a user in a group with `add_iam_member` after creating them.

#### `update_iam_user`
Update an existing user profile.

**Parameters:**
- `user_id` (string): User ID to update
- `workspace` (string): Workspace name
- `email` (string, optional): New email address
- `first_name` (string, optional): New first name
- `last_name` (string, optional): New last name
- `is_active` (boolean, optional): New active status
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Note:** Only provided fields will be updated. Omitted fields remain unchanged. Group membership is changed through `add_iam_member`/`remove_iam_member`, not here.

#### `delete_iam_user`
Delete IAM user from workspace.

**Parameters:**
- `user_id` (string): User ID to delete
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

**⚠️ Warning:** This action is irreversible and will remove all user permissions and group memberships.

### Group management

#### `list_iam_groups`
List all IAM groups in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted
- `page` (integer, optional): Page number
- `page_size` (integer, optional): Groups per page

**Returns:** List of groups with member counts and permission summaries.

#### `create_iam_group`
Create a new IAM group.

**Parameters:**
- `name` (string): Group name (immutable once created)
- `workspace` (string): Workspace name
- `display_name` (string, optional): Human-readable name
- `description` (string, optional): Group description
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Example:**
```json
{
  "name": "senior-developers",
  "workspace": "production",
  "display_name": "Senior Developers",
  "description": "Senior development team with elevated permissions"
}
```

#### `get_iam_group` / `update_iam_group` / `delete_iam_group`
Read a group by `group_id`, update its `display_name`/`description` (the `name` is immutable), or delete it permanently.

### Membership management

#### `list_iam_memberships`
List group memberships. **Parameters:** `workspace`, `group_id` (optional filter), `region` (optional), `page`, `page_size`.

#### `add_iam_member`
Add a user to a group. **Parameters:** `group_id`, `user_id`, `workspace`, `role` (`member`, `manager`, or `owner`), `region` (optional).

#### `remove_iam_member`
Remove a membership. **Parameters:** `membership_id`, `workspace`, `region` (optional).

#### `invite_workspace_user`
Send an email invitation to join the workspace (Auth0-enabled deployments). **Parameters:** `email`, `workspace`, `region` (optional).

### Application management (machine service accounts)

- `list_iam_applications`: `workspace`, `region` (optional), `page`, `page_size`
- `create_iam_application`: `name`, `workspace`, `description` (optional), `service_type` (optional), `region` (optional)
- `get_iam_application` / `update_iam_application` / `delete_iam_application`: by `app_id`
- `assign_application_system_users` / `unassign_application_system_users`: `app_id`, `system_user_ids` (array), `workspace`, `region` (optional)

**Note:** Role and permission endpoints are not implemented in the Alpacon server, so there are no `list_iam_roles`, `assign_iam_user_role`, or permission tools.

---

## 🗂️ Work session tools

A Work Session is the unit of authorized work: a scope, a set of servers, an expiry, and an audit trail. OAuth/browser callers must have one active before executing commands or transferring files; static API tokens and service tokens bypass the gate.

### `work_session_create`
Open a session. **Parameters:** `workspace`, `scopes` (array; agents may request `command`, `webftp`, `tunnel`, and `sudo`—request `sudo` only when the work genuinely requires root, since a sudo invocation no policy covers routes to human approval), `servers` (array of UUIDs), `expires_at` (ISO 8601), `description`, `title` (optional), `region` (optional). Only `title` and `region` may be omitted—a session with no expiry or no stated reason is not a session anyone can approve.

`description` is prose for the human who approves the session. It is not a command list and nothing in it is executed; commands run via `execute_command` once the session is active.

A session that needs human approval comes back with `status="pending_approval"`—surface it to a person and retry after they approve.

### `work_session_get` / `work_session_list`
Read one session (`session_id`) or list them (`status`, `requester_type`, `limit` filters).

### `work_session_update` / `work_session_extend`
Partial update of `title`, `description`, `scopes`, `servers` (and `expires_at` for pending sessions only), or extend `expires_at` on an approved/active session. `description` carries the same prose-only rule as on `work_session_create`. An update that needs approval is queued as a modification request.

### `work_session_timeline`
Chronological record of commands, file transfers, terminal activity, and sudo grants. **Parameters:** `session_id`, `workspace`, `include_records` (boolean, default true), `region` (optional).

### `work_session_close` / `work_session_analyze`
Close a session (triggers AI security analysis) or re-run analysis on a terminal session (`force` to redo).

**Gate error codes:** `work_session_not_active` returns `status="pending_approval"`; `work_session_required`, `work_session_not_usable`, `work_session_expired`, `work_session_scope_not_allowed`, `work_session_server_not_allowed`, and `work_session_assignee_mismatch` return `status="error"` with a `next_action`. Set `ALPACON_WORK_SESSION` to supply a default session id when a tool's `work_session_id` argument is omitted.

---

## ✅ Approval and sudo tools

- `list_approval_requests`: `workspace`, `status` (optional), `region` (optional), `page`, `page_size`
- `get_approval_request`: `request_id`, `workspace`, `region` (optional)
- `explain_approval_decision`: `workspace`, `request_id` (optional), `region` (optional). Explains that deciding is human-only and out of band; performs no mutation
- `list_sudo_policies`: `workspace`, `region` (optional), `page`, `page_size`
- `create_sudo_policy`: `workspace`, `name`, `commands`, `users`, `groups`, `servers`, `run_as`, `no_password`, `description`, `region` (optional)

There is intentionally no `approve_request`/`reject_request` tool: the Alpacon server refuses approve/reject from agent and token channels with HTTP 403. Approval happens in the web console or Slack.

---

## 🔔 Alert tools

- `list_alerts`: `workspace`, `server_id`, `alert_type`, `severity` (`critical`, `warning`, `info`), `server_name`, `acknowledged`, `dismissed`, `region` (optional), `page`, `page_size`
- `get_alert`: `alert_id`, `workspace`, `region` (optional)
- `acknowledge_alert`: `alert_id`, `workspace`, `action_type` (`checked` or `dismissed`), `region` (optional). One acknowledgement per user per alert, and it cannot be changed afterwards
- `create_alert_rule`: `workspace`, `name`, `target`, `threshold`, `is_default`, `region` (optional). `target` is one of `cpu-usage`, `memory-usage`, `disk-usage`, `peak-read-bps`, `peak-write-bps`, `avg-read-bps`, `avg-write-bps`, `peak-input-pps`, `peak-input-bps`, `peak-output-pps`, `peak-output-bps`, `avg-input-pps`, `avg-input-bps`, `avg-output-pps`, `avg-output-bps`
- `update_alert_rule`: `rule_id`, `workspace`, and any of `name`, `target`, `threshold`, `is_default`
- `delete_alert_rule`: by `rule_id`. A rule with `is_default=true` cannot be deleted
- `attach_alert_rule` / `detach_alert_rule`: `server_id`, `rule_id`, `workspace`, `region` (optional). Each is idempotent in the state it aims at: attaching a rule the server already has changes nothing, and so does detaching a rule the server does not have

Creating and updating a rule need a paid plan; reading, attaching and detaching work on any plan.

---

## 🛡️ Security ACL tools

Command ACLs decide which commands a token may run, server ACLs which hosts it may reach, file ACLs which paths it may transfer.

- `list_command_acls`: `workspace`, `api_token_id`/`service_token_id` filters, `region` (optional), `page`, `page_size`
- `create_command_acl`: `workspace`, `command`, `api_token_id` or `service_token_id`, `username`, `groupname`, `region` (optional)
- `update_command_acl` / `delete_command_acl`: by `acl_id`
- `list_server_acls` / `create_server_acl` (`server_id` + token id) / `update_server_acl` / `delete_server_acl`
- `bulk_server_acl`: `workspace`, `action` (add or remove), `server_ids` (array), token id, `region` (optional)
- `list_file_acls` / `create_file_acl` (`path`, `action`) / `update_file_acl` / `delete_file_acl`

---

## 📝 Audit tools

- `list_activity_logs`: `workspace`, `region` (optional), `page`, `page_size`
- `get_activity_log`: `log_id`, `workspace`, `region` (optional)
- `list_server_logs`: command execution history; `workspace`, `server_id` (optional), `page`, `page_size`
- `list_webftp_logs`: file transfer history; same parameters
- `list_session_analyses`: AI security analyses; `workspace`, `server_id`, `status`, `risk_score`, `page`, `page_size`
- `get_session_analysis_detail`: `analysis_id`, `workspace`, `region` (optional). Includes MITRE ATT&CK mapping

---

## 📦 Package tools

- `list_system_package_entries`: `server_id`, `workspace`, `region` (optional), `page`, `page_size`
- `install_system_package`: `server_id`, `package_name`, `workspace`, `version` (optional), `region` (optional)
- `remove_system_package`: `entry_id`, `workspace`, `region` (optional)
- `list_python_packages` / `install_python_package` / `remove_python_package`: same shape, via pip

---

## 📜 Certificate tools

**Authorities:** `list_certificate_authorities`, `create_certificate_authority` (`name`, `domain`, `organization`, `server_id`, `owner`, `root_valid_days`, `default_valid_days`, `max_valid_days`, `key_algorithm`, `key_size`, `install`), `get_certificate_authority`, `update_certificate_authority` (`default_valid_days`, `max_valid_days`, `owner`), `delete_certificate_authority`.

**Signing requests:** `list_sign_requests`, `create_sign_request` (`domain_list`, `ip_list`, `valid_days`), `get_sign_request`, `approve_sign_request`, `deny_sign_request`, `retry_sign_request` (for a CSR stuck in signing), `delete_sign_request` (cancels a pending CSR).

**Certificates:** `list_certificates` (`authority_id` filter), `get_certificate`, `revoke_certificate` (`reason`, `requested_reason`; auto-approved when the caller owns the CA or is an admin, otherwise it waits for approval).

**Revocation requests:** `list_revoke_requests`, `get_revoke_request`, `approve_revoke_request`, `deny_revoke_request`, `retry_revoke_request`, `cancel_revoke_request`.

---

## 🔗 Webhook tools

- `list_webhooks`: `workspace`, `owner` (user UUID), `provider`, `region` (optional), `page`, `page_size`
- `get_webhook` / `delete_webhook`: by `webhook_id`
- `create_webhook`: `workspace`, `name`, `url`, `owner` (user UUID, required), `provider` (optional), `ssl_verify`, `enabled`, `region` (optional). `provider` is one of `slack`, `discord`, `teams`, `telegram`, `custom`, and is detected from the URL when omitted
- `update_webhook`: `webhook_id`, `workspace`, and any of `name`, `url`, `ssl_verify`, `enabled`
- `list_event_subscriptions` / `create_event_subscription` (`channel`, `event_type`, `target_id`) / `delete_event_subscription`

Webhook tools need an admin account, and creating or updating a webhook needs a paid plan.

---

## 🎫 API token tools

- `list_api_tokens`: `workspace`, `region` (optional), `page`, `page_size`, `name`, `enabled`, `remote_ip`, `search`, `ordering`
- `get_api_token`: `token_id`, `workspace`, `region` (optional)
- `create_api_token`: `workspace`, `name`, `scopes`, `presets`, `expires_at`, `enabled`, `region` (optional)
- `update_api_token`: `token_id`, `name`, `enabled`, `expires_at`, `clear_expires_at`, `scopes`
- `delete_api_token` / `duplicate_api_token`: by `token_id`
- `list_api_token_scopes` / `list_api_token_presets`: catalogs for building a token

**Authentication note:** the server rejects these calls when the request is authenticated with a `source='api'` token, so in stdio mode with a `token.json` token they return `403 Forbidden`. Use the hosted server (JWT/OAuth), a browser session, or a login-source token. The scopes and presets catalogs are exempt.

---

## 🏢 Workspace management

### `list_workspaces`
Get list of available workspaces. Takes no `workspace`—it is how you find the name every other tool needs.

**Parameters:**
- `region` (string, optional): Restrict the listing to one region; omit to list every configured region

### `get_current_user`
Get the authenticated user: username, email, role, UID, shell, home directory.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name

### `health_check`
Check MCP server health: version, uptime, authentication mode, connection pool. Takes no parameters.

### `get_workspace_access_control`
Get the workspace access control settings: sudo/root access policy (`allow_sudo_with_mfa`, `allow_direct_root`, `block_local_sudo`, `sudo_timeout`), tunnel/editor defaults, `home_directory_permission`, Work Session TTLs (`work_session_max_ttl`, `work_session_pending_ttl`), command-env audit exposure, and `shared_account_names`.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Note:** On-premise deployments omit the MFA-related fields (`allow_sudo_with_mfa`, `block_local_sudo`, `sudo_timeout`).

### `get_workspace_security`
Get the workspace authentication/security settings: `mfa_required`, `allowed_mfa_methods`, `mfa_timeout`, and which actions require MFA.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Note:** Requires JWT (OAuth/SSO) authentication. The upstream `SecuritySettingsViewSet` has no `APITokenAuthentication`, so a static API token (stdio mode) is rejected before any request is sent; use remote/streamable-http (browser SSO) mode to read these settings.

**Note:** This route is also SaaS-only. On-premise deployments return 404 from the upstream API; this tool reports that the settings are not available on this deployment instead of a generic error.

### `list_workspace_mfa_methods`
List the MFA methods allowed for the workspace (`allowed_mfa_methods`, `passkey_as_mfa`). Useful when guiding a user through the remote/streamable-http MFA re-authentication flow.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

**Note:** Like `get_workspace_security`, this requires JWT (OAuth/SSO) authentication (a static API token is rejected up front) and the route is SaaS-only.

### `get_workspace_preferences`
Get the workspace-wide preferences: timezone, locale, `front_url`, `invite_ttl`, `enabled_extensions`, `websh_session_timeout`, `auto_agent_upgrade`, `package_proxy`, `billing_email`, `allowed_domains`. Workspace-global configuration, not per-user.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, optional): Region name; resolved from the workspace when omitted

### `update_workspace_preferences`
Update workspace-wide preferences. Only the fields you provide are sent (partial update).

**Parameters:**
- `workspace` (string): Workspace name
- `front_url` (string, optional): Workspace front-end URL
- `country` (string, optional): Workspace country code
- `language` (string, optional): Workspace locale/language code
- `timezone` (string, optional): Workspace timezone; also the billing clock
- `invite_ttl` (integer, optional): Invitation link time-to-live, in seconds
- `enabled_extensions` (array, optional): List of enabled extension names. Replaces the whole list (not additive); read via `get_workspace_preferences` and merge before sending. Narrowing it fails with HTTP 402 on non-enterprise plans
- `websh_session_timeout` (integer, optional): Websh idle session timeout, in seconds
- `auto_agent_upgrade` (boolean, optional): Whether agents auto-upgrade
- `package_proxy` (string, optional): Proxy server URL for package installation
- `billing_email` (string, optional): Billing contact email; SaaS-only field
- `allowed_domains` (array, optional): Allowed email domains for invites; SaaS-only field. Replaces the whole list (not additive); read via `get_workspace_preferences` and merge before sending
- `region` (string, optional): Region name; resolved from the workspace when omitted

**⚠️ Warning:** `timezone` is the workspace's billing clock—changing it shifts the daily usage-aggregation boundary. The list fields (`enabled_extensions`, `allowed_domains`) replace the whole list rather than appending—read the current value, merge, then send. `billing_email` and `allowed_domains` are only accepted by the server on SaaS deployments.

### Why access control and security are read-only here

Notifications and preferences have write tools; access control and security settings deliberately do not. On SaaS the server gates those governance-level writes behind a superuser session with fresh MFA, which a static API token cannot satisfy. On-premise the same writes need only an admin token with the `workspaces` scope, so a token could technically perform them—but keeping governance settings human-only, in the web console, is the safer default regardless of deployment. This is a deliberate omission, not a gap to fill.

There are likewise no user-settings or user-profile tools: `/api/user/settings/` and `/api/user/profile/` do not exist on the Alpacon server. The endpoints that do exist for adjacent data are `/api/profiles/preferences/`, `/api/workspaces/preferences/` (exposed above), and `/api/auth0/users/`. Role and permission management endpoints do not exist either, which is why the IAM section has no role or permission tools.

---


## 🔍 Resources and prompts

Most read tools are also exposed as read-only MCP resources under the `alpacon://` scheme, so a client can pull data without a tool call. `search_events`, `get_registration_guide`, `work_session_timeline`, `explain_approval_decision`, `webftp_check_status`, and `health_check` are tool-only. The URI convention is `alpacon://<domain>[/<sub>]/{region}/{workspace}[/{id}]`; optional filters are not part of the URI, so resources use each tool's defaults.

- `alpacon://servers/{region}/{workspace}` — also `/{server_id}`, `/{server_id}/overview`, `/{server_id}/notes`; a single note is `alpacon://server-notes/{region}/{workspace}/{note_id}`
- `alpacon://metrics/{region}/{workspace}/{server_id}/{cpu|memory|disk|disk-io|network|summary}` and `alpacon://metrics/{region}/{workspace}/top`
- `alpacon://system/{region}/{workspace}/{server_id}/{info|os-version|users|groups|packages|network-interfaces|disk-info|time}`
- `alpacon://alerts/{region}/{workspace}`, `alpacon://alerts/active/{region}/{workspace}`, `alpacon://alert-rules/{region}/{workspace}`
- `alpacon://iam/{users|groups|memberships|applications}/{region}/{workspace}`
- `alpacon://work-sessions/...`, `alpacon://approvals/...`, `alpacon://sudo-policies/...`
- `alpacon://audit/{activity|server-logs|webftp-logs|session-analyses}/{region}/{workspace}`
- `alpacon://certs/...`, `alpacon://tokens/...`, `alpacon://webhooks/...`, `alpacon://event-subscriptions/...`, `alpacon://acls/{command|server|file}/...`, `alpacon://webftp/{sessions|uploads|downloads}/...`, `alpacon://packages/{system|python}/...`, `alpacon://events/...`, `alpacon://commands/...`, `alpacon://registration-tokens/...`
- `alpacon://workspaces`, `alpacon://workspaces/{region}`, `alpacon://current-user/{region}/{workspace}`
- `alpacon://workspace-settings/{access-control|security|mfa-methods|preferences}/{region}/{workspace}`

A resource is registered only when its backing tool module is enabled, so a narrow `--toolsets` selection drops the matching resources too.

**Prompts** (workflow guides, defined in `tools/prompts.py`):

- `work_session_workflow(intent, servers)`: how to scope and open a session before acting
- `guarded_execution(work_session_id)`: running commands and transfers inside an approved session
- `incident_response(server_id, workspace)`: read-only triage first, then bounded remediation
- `security_audit(work_session_id, server_id)`: choosing the right audit lens

## ⚠️ Error handling

All tools return a consistent error structure:

```json
{
  "status": "error",
  "message": "Error description",
  "details": "Additional error details (if available)"
}
```

Common error scenarios:
- **401 Unauthorized**: Invalid or missing API token
- **403 Forbidden**: Insufficient permissions
- **404 Not Found**: Server, resource, or session not found
- **500 Internal Error**: Server-side error

## 📝 Response format

Successful responses follow this structure:

```json
{
  "status": "success",
  "data": "Response data",
  "server_id": "server-123",
  "region": "ap1",
  "workspace": "company-main"
}
```

---

For more examples and usage patterns, see the [Examples](examples.md) section.