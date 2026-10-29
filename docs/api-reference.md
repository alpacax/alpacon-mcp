# API reference

Complete reference for all Alpacon MCP Server tools and capabilities.

## 📌 Conventions

- **`workspace` is always required.** Every tool that talks to the API takes it, as the name `list_workspaces` returns.
- **`region` is optional.** Leave it out and the server resolves it from the workspace—via `token.json` in local mode, via the JWT claims in hosted mode. Supply it (`ap1` or `us1`; the schema refuses any other value, including an empty string) when one token spans several regions. An unresolvable region comes back as a validation error, not a silent default.
- **Server IDs are UUIDs**, never names. Get them from `list_servers`. The same holds for each entry of `servers` and `server_ids`, and `session_id` on the Work Session tools is a Work Session UUID.
- **Every other `*_id` is checked before the request is built.** A value must be a string of letters, digits, `.`, `_`, `~`, or `-`, and must not be `.` or `..`. Most of these identifiers are interpolated into the endpoint path, where a `/` or a `..` retargets the request; the ones that only reach a query parameter or a request body are held to the same rule, because the check goes by the argument name rather than by where the value ends up. Anything else—a `/`, a `?`, a `#`, a percent-encoded spelling of one, or a value that is not a string at all—comes back as a validation error naming the field, and no request is sent. `work_session_id` is the one exception: its surrounding whitespace is stripped on purpose, so the rule would reject values the `ALPACON_WORK_SESSION` route accepts.
- **`limit` and `page_size` must be positive integers.** Both name a page size and reach the API as `page_size`, where a zero or a negative asks for a page that cannot exist. Either one comes back as a validation error naming the field, and no request is sent. Omitting the argument still gets the tool's own default.
- **Work Session gate**: OAuth/browser callers must run command execution and file transfers inside an active Work Session; static API and service tokens bypass it. Blocked calls return `status="pending_approval"` or a `status="error"` with a `code` and `next_action`—see [Work session tools](#-work-session-tools).

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

A request is retried with backoff after a 5xx, a timeout, or a network error, with one exception: a `POST` or `PATCH` is retried only when it never reached the server—no connection opened or came free from the pool, the proxy refused the tunnel, the URL scheme cannot be sent, or the server answered 503 `auth_verification_unavailable`, which it sends before any view runs. Once it may have reached the server (a read or write timeout, a broken connection, any other 5xx, or an unexpected error such as a 2xx whose body cannot be read), the tool's error comes back at once with `outcome_unknown: true` and no `recovery_hints`, because sending it again could repeat what it did. Check whether the write took effect before calling the tool again. An error without the field was not acted on, or came from a method that is safe to resend (#392).

## 🖥️ Server management tools

### `list_servers`
List all servers in a region and workspace.

**Parameters:**
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name
- `page` (integer, optional): Page number
- `page_size` (integer, optional): Servers per page, up to 100; the server defaults to 15

**Returns:** Array of server objects with ID, name, status, and metadata.

### `get_server`
Get detailed information about a specific server.

**Parameters:**
- `server_id` (string): Server UUID to get details for
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Complete server information including hardware specs, status, and configuration.

### `list_server_notes`
List notes for a specific server.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `create_server_note`
Create a new note for a server.

**Parameters:**
- `server_id` (string): Server UUID
- `content` (string): Note content; capped at 512 characters
- `private` (boolean, optional): Hide the note from other workspace members
- `pinned` (boolean, optional): Pin the note; a server holds at most three pinned notes
- `mentioned_users` (array of strings, optional): User UUIDs to notify; accepted on create only
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_server_note` / `update_server_note` / `delete_server_note`
Read, partially update (`content`, `private`, `pinned`), or permanently delete a note by `note_id`.

### `update_server`
Rename or relabel a server's Alpacon entry, or toggle its own offline-alert delivery. Does not touch the host itself.

**Parameters:**
- `server_id` (string): Server UUID
- `workspace` (string): Workspace name
- `name` (string, optional): New display name
- `description` (string, optional): New description
- `offline_alert_enabled` (boolean, optional): This server's own offline-alert toggle, independent of any workspace rule; defaults to `true` on the server. Refused when the caller is the server's own agent credential
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `get_collection_profile`
What a server collects and at what cadence, and what it does not collect. Not gated behind the metrics extension, so it answers on every plan.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** `enabled` (whether the metrics extension is on for this workspace), `core[]` and `metrics[]`—each entry carrying `name`, `interval_s`, `last_sample_at`, `collected`, `scope`, and `reason` when not collected; `metrics[]` entries also carry `retention_days`, and the core disk-usage entry alone carries `latest[]` (per-volume readings)—and `not_collected[]`, each entry carrying `name`, `reason`, and `unlocked_by`.

### `unregister_server`
Unregister a host from the workspace. The agent stays installed; bringing the host back needs a registration token.

**Parameters:** `server_id`, `workspace`, `auto` (boolean, default `false`: refuses a still-connected host with 400 `SERVER_CANNOT_BE_DELETED`; `true` tears the agent off a host that is still running), `purge_provisioned_accounts` (boolean, default `false`: also deletes the OS accounts Alpacon provisioned on the host, skipped when the host is unreachable), `region` (`ap1` or `us1`, optional)

### `star_server`
Pin or unpin a server for the calling user. A personal preference flag, not a fleet-wide setting.

**Parameters:** `server_id`, `status` (boolean: `true` pins the server, `false` unpins it), `workspace`, `region` (`ap1` or `us1`, optional)

### Agent actions

Each takes `server_id`, `workspace`, and an optional `region` (`ap1` or `us1`). This is the complete set of actions
this endpoint accepts; an action outside this set returns 400. The two disruptive ones also take
`force` (boolean, default `false`), which runs the action even while the host is busy with an open
Websh or WebFTP session or an in-flight command, tearing that work down. `install_pam` and
`update_information` are not disruptive and take no `force`.

- `restart_agent`: Restart the Alpacon agent process
- `upgrade_agent`: Upgrade the agent to the latest version
- `install_pam`: Install the `alpamon-pam` package as root through the host's package manager; a
  host already current is a no-op. Needs the workspace's "Use sudo with MFA" setting on. Refused
  with `error_code` `server_pam_install_requires_sudo_with_mfa` (400: that setting is off, or the
  deployment cannot complete its step-up), `server_pam_install_unsupported` (400: the host has no
  package path—macOS, Windows, or a package manager Alpacon does not drive) or
  `server_pam_install_in_progress` (409: an install is already pending). Requires an
  alpacon-server release carrying alpacax/alpacon-server#4239
- `update_information`: Re-collect hardware, OS, network, and package data

Host-level power operations (an OS package upgrade, a reboot, a shutdown) are not one-click tools.
They run through a Work Session and `execute_command`—see "Keeping hosts current" in
[examples.md](examples.md)—so they carry sudo, MFA or approval, and recording.

### Registration tokens (Alpamon)

- `list_registration_tokens`: `workspace`, `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `create_registration_token`: `workspace`, `name`, `description` (optional), `region` (`ap1` or `us1`, optional)
- `delete_registration_token`: `token_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `get_registration_guide`: `token_id`, `workspace`, `platform` (`debian`, `rhel`, `suse`, `darwin`, `windows`), `server_name` (optional), `region` (`ap1` or `us1`, optional). Returns the platform-specific install command

---

## 📊 Metrics and monitoring tools

### `get_cpu_usage`
Get CPU usage metrics for a server.

**Parameters:**
- `server_id` (string): Server UUID to get metrics for
- `start_date` (string, optional, default: 12 hours ago): Start date in ISO format; the server returns at most the last 12 hours
- `end_date` (string, optional): End date in ISO format
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
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
- `server_id` (string): Server UUID
- `device` (string, optional): Device path (e.g., '/dev/sda1'); with neither `device` nor `partition`, the tool reads the alphabetically first device with data in the last day
- `partition` (string, optional): Partition ID (UUID) from `/api/proc/partitions/`
- `start_date` (string, optional, default: 12 hours ago): Start date; the server returns at most the last 12 hours
- `end_date` (string, optional): End date
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_network_traffic`
Get network traffic metrics for a server.

**Parameters:**
- `server_id` (string): Server UUID
- `interface` (string): Interface ID (UUID) from `/api/proc/interfaces/`, required; the endpoint returns HTTP 400 when it is missing or is an interface name such as `eth0`
- `start_date` (string, optional, default: 12 hours ago): Start date; the server returns at most the last 12 hours
- `end_date` (string, optional): End date
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_disk_io`
Get disk I/O performance metrics for a server.

**Parameters:**
- `server_id` (string): Server UUID
- `device` (string, optional): Disk device name (e.g., 'sda', 'nvme0n1'); when omitted or blank, the tool reads `/api/metrics/realtime/disk-io/device/` and uses the alphabetically first device with data in the last day, and returns an error without querying metrics when there is none
- `start_date` (string, optional, default: 12 hours ago): Start date in ISO format; the server returns at most the last 12 hours
- `end_date` (string, optional): End date in ISO format
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Response:** `data` is the unpaginated list of rows the Alpacon API server returns, newest first, one per device and sample: `id`, `device`, `disk`, `timestamp`, and that sample's `peak_read_bps`, `peak_write_bps`, `avg_read_bps` and `avg_write_bps` in bytes per second. The top-level `device` is the device read, and `devices` is the sorted list of discovered devices when `device` was omitted or blank, null otherwise; call again with another entry to read that device. A device listed for the last day can have no rows in the 12-hour window, which returns an empty `data`.

### `get_top_servers`
Rank the top five servers by resource usage over the last 24 hours.

**Parameters:**
- `workspace` (string): Workspace name
- `metric_types` (string, optional): Comma-separated metrics to rank by (`cpu`, `memory`, `disk_io`, `traffic`); omit for all four
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `list_latest_metrics`
Get the latest CPU, memory, disk usage, disk I/O and network reading for many servers in one
request, one row per server. It is the servers list with five metric cells added: filters, search,
and pagination are `list_servers`'s own, plus `state` and `ordering`. Each cell says whether its
value is missing, stale, or not collected — use `get_cpu_usage` etc. for one server's time series,
or `get_server_metrics_summary` for one server's detail. **Requires alpacon-server 2.37.0 or
later.**

The `metric_severity`, `threshold`, `operator`, and `summary` fields require a server
deployment that supports them; earlier deployments omit them.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `search` (string, optional): Free-text search across server name, version, owner, and group name
- `groups` (string, optional): Filter by group ID(s)
- `tag` (string, optional): Filter by tag(s) in `key:value` form
- `is_connected` (boolean, optional): Filter by live agent connection state
- `state` (string, optional): `stale` (some family overdue, including a server storing nothing) or
  `no_data` (nothing stored at all); `stale` includes every `no_data` server
- `ordering` (string, optional): `name`, `starred`, `sampled_at`, `cpu`, `memory`, `disk_usage` (or
  `disk-usage`), `disk_io` (or `disk-io`), `net`, `metric_severity`, optionally prefixed with `-`
  for descending; a server with no value for the field sorts last. `-metric_severity` puts
  critical first; ties keep the default order. Severity ordering needs a server that supports it
  and `alert:read`; otherwise it is ignored and the default order applies
- `page` (integer, optional): Page number for pagination
- `page_size` (integer, optional): Number of results per page, up to 100

**Response:** `count`, `current`, `next`, `previous`, `last`, `summary`, and `results`—each result an
`{id, name, is_connected, metric_severity, cpu, memory, "disk-usage", "disk-io", net}` row, every
metric cell an object with `value`, `unit` (`percent` or `bytes_per_sec`), `sampled_at`, `device`, `collected`,
`reason`, `interval_s`, `threshold`, and `operator` (`value`, `sampled_at`, and `device` are null
when no sample is stored for that family).

`metric_severity` is `critical`, `warning`, `info`, or null without `alert:read`. Each cell's
`threshold` is a number or null and `operator` is `gte`, `lte`, or null; both are always null
for `disk-io` and `net`, and null when the caller cannot read rule overrides.

`summary` contains server counts `{critical, warning, stale, no_data}` over the filtered set
before pagination. `critical` and `warning` are null without `alert:read`; `warning` excludes
servers counted as critical.

### `get_alert_rules`
Get alert rules for servers.

**Parameters:**
- `server_id` (string, optional): Server UUID to filter rules
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_server_metrics_summary`
Comprehensive health overview for one server; for many servers at once, use `list_latest_metrics`.

**Parameters:**
- `server_id` (string): Server UUID
- `hours` (integer, default: 12, max: 12): Number of hours back to get metrics; the realtime endpoints keep only the last 12 hours, so a larger value is clamped to 12
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** `metrics.cpu`, `metrics.memory`, `metrics.disk`, and `metrics.network`, each with `available` and either `data_points` or `error`. Disk usage is read for the partition mounted at `/`, preferring one that is not virtual, using its ID from `/api/proc/partitions/`. Network traffic is read for the first active non-loopback interface whose name does not look virtual (`docker`, `br-`, `veth`, `virbr`, `cni`, `flannel`, `cali`, `vxlan`, `tun`, `tap`, `lxc`, `kube` prefixes), falling back to the first active non-loopback interface, using its ID from `/api/proc/interfaces/` (up to 20 pages of 100 interfaces are read, so an interface missing from the summary does not prove none exists beyond the first 2000). If the partition lookup fails or returns no root partition, `metrics.disk.error` describes the problem and the disk-usage endpoint is not called. If the interface lookup fails or finds no active non-loopback interface, `metrics.network.error` describes the problem and the traffic endpoint is not called.

---

## 💻 System information tools

### `get_system_info`
Get detailed system information for a server.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Hardware specs, CPU details, memory info, and system identifiers.

### `get_os_version`
Get operating system version information.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `list_system_users`
List system users on a server.

**Parameters:**
- `server_id` (string): Server UUID
- `username_filter` (string, optional): Username to search for
- `login_enabled_only` (boolean, default: false): Only return users that can login
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `list_system_groups`
List system groups on a server.

**Parameters:**
- `server_id` (string): Server UUID
- `groupname_filter` (string, optional): Group name to search for
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `list_system_packages`
List installed system packages on a server.

**Parameters:**
- `server_id` (string): Server UUID
- `package_name` (string, optional): Package name to search for
- `architecture` (string, optional): Architecture filter (e.g., 'x86_64')
- `limit` (integer, default: 100): Maximum number of packages to return
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_network_interfaces`
Get network interfaces information for a server.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_disk_info`
Get disk and partition information for a server.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Both disk and partition information in a single response.

### `get_system_time`
Get system time and uptime information.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_server_overview`
Get comprehensive overview of server system information.

**Parameters:**
- `server_id` (string): Server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

**Returns:** Combined system info, OS version, time, network interfaces, and disk info.

---

## 🗂️ Event management tools

### `list_events`
List server events.

**Parameters:**
- `server_id` (string, optional): Server UUID to filter events
- `reporter` (string, optional): Reporter name to filter events
- `limit` (integer, default: 50): Maximum number of events to return
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `get_event`
Get detailed information about a specific event.

**Parameters:**
- `event_id` (string): Event ID to get details for
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `search_events`
Search events by criteria.

**Parameters:**
- `search_query` (string): Search term to look for in events
- `server_id` (string, optional): Server UUID to limit search scope
- `limit` (integer, default: 20): Maximum number of results to return
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

---

## 💻 Command API tools (requires ACL permission)

> ⚠️ **ACL configuration required**: Command API tools require pre-approved commands in your token's Access Control List (ACL). Configure permissions by clicking on your token in the Alpacon web interface → ACL settings.

### `execute_command`
Execute a command on a server and wait for the result.

**Parameters:**
- `server_id` (string): Server UUID
- `command` (string): Command to execute; must not be empty or whitespace-only. Do not prefix it with `sudo` by default; use `sudo` only when the command genuinely requires root and the Work Session carries the `sudo` scope. Unless a Work Session sudo policy already covers the command, a sudo invocation either routes to human approval and blocks until a human acts, or is denied outright with no request anyone can approve. Check `sudo_denial.category` before waiting—a `sudo_hint` with no `sudo_denial` is a hard denial that creates no request
- `workspace` (string): Workspace name
- `shell` (string, default: "system"): Shell type
- `username` (string, optional): Username for execution
- `groupname` (string, default: "alpacon"): Group name
- `env` (object, optional): Environment variables
- `run_after` (array, optional): Command IDs to wait for before executing
- `scheduled_at` (string, optional): ISO 8601 datetime for scheduled execution
- `data` (string, optional): Stdin data
- `timeout` (integer, default: 300): Timeout in seconds
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `purpose` (string, optional): What this particular command is for (ADR 0052). The assessor judges the command with it in hand, so one that would otherwise queue for a human may clear on its own. State a fact local to this host that the Work Session description does not already imply; general knowledge adds nothing the assessor lacks, and a purpose cannot lower a command's intrinsic risk. Trimmed to 2000 characters rather than refused, and the response then carries `purpose_truncated: true`
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Held for its purpose:** when no `purpose` was stated and the gate holds the command, the response is
`status: "purpose_required"` rather than a result. It carries `command_id`, `requires_human_approval: false`,
`answerable_by_agent: true`, `purpose_guidance`, and—when the server reports the demand's expiry—
`deadline_seconds`, the number of seconds left. No approval request exists at that point, so a client must not treat it as a pending
approval: answer it with `state_command_purpose`.

**Held for approval:** a `status: "pending_approval"` response with `category:
"COMMAND_AWAITING_APPROVAL"` says in its `message` that a script already on the host can move to
`execute_file` with `read_from_server: true`. When the server names the script the held line runs, the
response also carries `execute_file_suggestion`: `{"tool": "execute_file", "arguments": {...}}` with
`server_id`, `path`, `interpreter`, `args`, `read_from_server: true`, `workspace`, and `region`, plus
the held command's `username`, `groupname` and `work_session_id` (from the held call, else from the
polled command row, so a run answered through `state_command_purpose` keeps them too), ready to pass
as they are on the next run. A held command that was fed `data` gets no suggestion, only the hint in
`message`: `execute_file` takes no stdin. When the held line names a bare interpreter such as `bash`, the server
does not resolve it and neither does this one: `arguments.interpreter` is `null`, and the suggestion
adds `interpreter_name` (the bare name) and an `instruction` to set `interpreter` to that name's
absolute path on the host, for example from `command -v bash` there, before calling. A suggestion
with a malformed field is dropped, never patched, so the field is either absent or complete apart
from that one interpreter path. The held command stays queued and runs if approved, and the
`message` says so: to switch to `execute_file` now, have a human cancel the held command in the
Alpacon console (Commands) first, or the script waits on two approval requests. No MCP tool cancels
it.

**Refused as a script body:** a line that carries a script body (a heredoc, a multi-line `-c` or `-e`
body, or a decoded payload piped into a shell or interpreter) can be refused when the workspace
approval policy blocks script bodies. It is never refused at submit time. The command is created as
usual, and the verdict lands on the command row after verification: `status`
and `verification_status` are `rejected`, `rejection_cause` is `use_file_execution`, and `result`
carries the server's guidance sentence. The response is then `status: "error"` with `error_code:
"use_file_execution"`, a `message` that leads with that sentence, the command row in `details`, and a
`next_action` telling the agent to call `execute_file` with the script as `content` and
`write_file: true` on the same server and account (`server_id`, `username`, a non-default
`groupname` and `work_session_id` are named when the command row carries them), with `interpreter`
set to the absolute path of the interpreter the refused line invoked, since it defaults to
`/bin/bash`. A command that was fed stdin `data` is told to move that data into the script, because
`execute_file` takes no stdin.
The refused command did not run, so nothing needs cancelling. The server attaches no
`execute_file_suggestion` here: the script body is on the command line, so there is no path to read.
`state_command_purpose` returns the same refusal when the re-judged command lands on it.

**Rejected by a gate:** a command a gate refused before it ran ends in `status: "rejected"`, and the response is `status: "error"` with the command row in `details` plus three fields read from it (#242). `rejection_cause` is why the platform refused it (`command_acl_denied`, `command_acl_unavailable`, `risk_denied`, `risk_unavailable`, `approval_policy_denied`, `approval_rejected`, `approval_expired`, `approval_cancelled`, `work_session_terminated`, `account_bound_to_other_person`, `unsigned_file`, `signature_invalid`, `use_file_execution`). `rejection_gate` is the gate that refused it, `null` for the causes the agent's signature check or the account binding decided. `rejection_hint` says whom to ask or where to wait, and is also appended to `message`, except on a `use_file_execution` refusal, whose `message` and `next_action` already name the `execute_file` call. Resubmitting the same command gets the same answer, so no hint says to. A cause this server does not know takes the hint for its gate, and a gate it does not know takes a generic one. A rejected command whose `rejection_cause` is `null` or absent, from an older server or an older row, gets a hint saying the cause was not recorded; it is not an error of its own. A `denied` command carries no cause and keeps its plain error.

**Lost submission:** the command is submitted once and never resent after its request may have reached the server (#392). The response is then `status: "error"` with `outcome_unknown: true`, as described under Response structure, and the command may have been created and may have run. Do not resubmit it until `list_commands` for that server shows it is not there, since a resubmission may run the command twice. Read back past the time of the call: `list_commands` returns the newest commands first, 20 by default, so raise `limit` until the oldest entry predates the call. A page holding only newer commands does not show the command is missing. The server returns at most 100 commands whatever `limit` asks for, so when 100 newer commands fill the page, ask a human to check before resubmitting.

### `execute_file`
Run a script on a server as a verified file, and wait for the result. With `write_file`,
the same call writes the script to the host first; with `read_from_server`, it reads the script
already on the host and submits those bytes.

The reviewer and the assessor judge the exact bytes submitted as `content`; the agent hashes the file at
`path` on the target host's disk and executes it only if those bytes match. Approving it authorizes
exactly these bytes, on this server, as this account, with these arguments—not "this file is safe".
One changed byte re-queues review. Environment, libraries, interpreter version, and anything the
script fetches at runtime stay the executor's responsibility; only this first entrypoint is verified.
Once an approver marks a verified file standing, an unchanged re-run is admitted without paging a
human, which a `bash /path` line on `execute_command` never is.

**Parameters:**
- `server_id` (string): Server UUID
- `path` (string): Absolute path of the file on the target host. Without `write_file` it must already exist there; the agent reads it from disk, and `content` is never shipped to the host
- `workspace` (string): Workspace name
- `content` (string, optional): The file's contents, byte-for-byte as they are on disk. Never stripped, trimmed, or normalized—the agent hashes the on-disk file with no normalization, so a dropped trailing newline fails closed. Non-empty, at most 64 KB (65536 UTF-8 bytes). Required unless `read_from_server` is true, and refused alongside it
- `interpreter` (string, default: "/bin/bash"): Absolute path of the interpreter; a bare `bash` is refused
- `args` (array, optional): Arguments appended after the path, default `[]`; may contain empty strings
- `reuse_days` (integer, optional): Proposed number of days, 1 to 366, for which the approver should let this exact file be rerun without a new review. Standing approvals always expire: the workspace ceiling is 1 to 366 days (default 90), and a requester may propose a shorter period, never a longer one. A proposal, not a grant: the approver may decline reuse, and a workspace ceiling lowered after submission can shorten it; the approver cannot choose another period. A proposal above the ceiling is refused with `file_exec_reuse_exceeds_max` rather than shortened. Give it when the same unchanged script will be rerun within that window. Sent as `file.reuse_days` only when given, so an omitted value leaves the request unchanged and a server that predates the field never sees it. Omitting it proposes no duration; an approver who opts in may still grant reuse up to the workspace ceiling
- `write_file` (boolean, default: false): Write `content` to `path` on the host through WebFTP before submitting, in the same call. See "Writing the file" below
- `overwrite` (boolean, default: false): With `write_file`, replace a file already at `path`. Refused with `file_exec_invalid_options` without `write_file`
- `read_from_server` (boolean, default: false): Read the file at `path` from the host through WebFTP and submit those bytes as `content`. Excludes `write_file` and `content`. See "Reading the file" below
- `username` (string, optional): Username for execution; with `write_file`, also the account the file is written as, and with `read_from_server`, the account it is read as
- `groupname` (string, default: "alpacon"): Group name; with `write_file`, a value other than the default is also the group a new file is written with
- `run_after` (array, optional): Command IDs to wait for before executing
- `scheduled_at` (string, optional): ISO 8601 datetime for scheduled execution
- `timeout` (integer, default: 300): Timeout in seconds
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins. With `write_file` or `read_from_server`, the transfer is linked to it too
- `purpose` (string, optional): Same semantics as on `execute_command`
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Writing the file:** with `write_file: true`, the call uploads `content`, encoded as UTF-8 with no
normalization, to `path`, waits until the host reports the file written, and only then submits the
same bytes for review. The guarantee is unchanged: the agent hashes the on-disk file at execution and
refuses a mismatch, so a file changed between the write and the run fails closed.
- Overwrite: an existing file at `path` is refused, as the CLI's upload refuses it, unless
  `overwrite: true` is passed. The refusal is `file_write_failed`, and its message says the file
  already exists. To re-run a script already on the host, use `read_from_server` instead of writing
  it again.
- Ownership: the file is written as `username`. A new file is owned by that account and its own
  group, or by `groupname` when one other than the default `alpacon` is passed, and the account
  needs write access to the directory. An existing file replaced with `overwrite` keeps its owner
  and mode, and must be writable by `username`. Pass `username` whenever ownership matters: an
  omitted one leaves the writing account to the server's WebFTP default. No execute bit is needed;
  the interpreter runs the file.
- Timing: the write happens before the run is reviewed, exactly as a `webftp_upload_content` call
  would, so a run that is later denied leaves the new file in place. The wait for the write, up to
  about 60 seconds, comes before and on top of `timeout`.
- Failure: nothing is submitted. `error_code` is `file_write_failed` when the upload is refused or
  the host reports the write failed (a server refusal that names its own code, such as a Work
  Session gate, keeps that code), and
  `file_write_timeout`, with `upload_id`, when the host does not report the file written within
  about 60 seconds.
- The local path, size, and `reuse_days` checks run before the write, so a run refused locally
  never touches the host.

**Reading the file:** for a script that already exists on the host, such as the one a held
`bash /opt/deploy.sh` line runs, pass `read_from_server: true` and omit `content`. The call downloads
the file at `path` as `username` through WebFTP and submits its exact bytes, so the requester never
copies the script by hand. The trust model does not change: the requester still submits the content
the reviewer judges, and the agent still hashes the on-disk file at execution and refuses a mismatch,
so a file changed after the read fails closed.
- Exclusive: `read_from_server` with `write_file` or with a non-empty `content` is refused locally
  with `file_exec_invalid_options`, before anything reaches the host.
- Unusable file: nothing is submitted. An empty file is refused with `file_exec_empty_content` and one
  over 64 KB with `file_exec_content_too_large`, each naming `path`. A file that is not UTF-8 text
  cannot travel as `content` unchanged and is refused with `file_read_failed`.
- Failure: nothing is submitted. `error_code` is `file_read_failed` when the download is refused, the
  host reports the read failed (a missing file, or an account that cannot read it), or the transfer
  breaks (a server refusal that names its own code, such as a Work Session gate, keeps that code),
  and `file_read_timeout`, with `download_id`, when the host does not hand the file over within about
  60 seconds. That wait comes before and on top of `timeout`.
- A call with neither `content` nor `read_from_server` is refused with `file_exec_empty_content`, and
  the message names `read_from_server` as the way to run a file already on the host.

There is no `env`, `data`, or `shell`: composition (pipes, redirection, `&&`, variables) goes inside the
script, where it is reviewed with it. A one-off composition around a file belongs on `execute_command`.

**Response:** the same shape as `execute_command`—`awaiting_approval`, `purpose_required`, sudo
denials, and the result all follow the same rules—plus a `file` object echoing `path`, `interpreter`,
and `args` (never `content`). `command` and `shell` are not echoed; the polled command row carries the
server-rendered line.

**Lost submission:** the command submission follows the `execute_command` rule: with `outcome_unknown: true` the command may exist and may have run, so check `list_commands` for that server, read back past the time of the call, before resubmitting, and ask a human once 100 newer commands fill the page. The `write_file` upload and the `read_from_server` download are POSTs too, and a failed one carries the same field, but there the call can be repeated: the upload's bytes go up and the host writes them only in later steps that never ran, and a download only reads, so no file was written and nothing was submitted.

**Refusals** come back as `status: "error"` with `error_code` set, and a message stating the fix. None
has a request waiting behind it, so a client acts on them rather than waiting or retrying as-is:
`file_exec_unsupported_agent` (the agent on that server did not report support for this lane: an
alpamon older than 2.8.3 reports no capabilities, so upgrade it to 2.8.3 or newer or run the work
through `execute_command`; an alpamon already on 2.8.3 or newer has no file lane on that platform,
such as Windows, so upgrading does not help and the work runs through `execute_command` there),
`file_exec_assessor_disabled` (the deployment has the command assessor off), `file_exec_invalid_path`,
`file_exec_content_too_large`, `file_exec_empty_content`,
`file_exec_line_too_long`, `file_exec_invalid_options` (local only: `read_from_server` combined with
`write_file` or `content`, or `overwrite` without `write_file`), `file_exec_invalid_reuse_days` (`reuse_days` is outside 1 to 366; fix it or
omit it), and `file_exec_reuse_exceeds_max` (`reuse_days` is above the workspace's ceiling; resubmit
with a shorter duration or none). The path, size, and `reuse_days` range rules are also checked
locally before any request is made, with the same `error_code` and wording; only the server knows the
workspace ceiling.

**File-lane refusals after submit:** when the agent refuses a verified file at run time, the result
carries `error_phase` and the response adds `error_phase_hint` (what happened and what to do next).
Phases: `file_hash_mismatch` (the file changed after it was verified; re-run `execute_file`),
`file_payload_invalid`, `file_open_failed`, `file_exec_unsupported`, and `file_too_large`. Any other
`file_*` phase gets a generic file-lane hint. The same field is attached to `list_commands` entries
and to `execute_command` results; other phases carry no hint.

### `list_commands`
List recent command history.

**Parameters:**
- `server_id` (string, optional): Filter by server UUID
- `limit` (integer, default: 20): Maximum number of recent commands to return
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

An entry whose `error_phase` starts with `file_` gains `error_phase_hint`, as on `execute_file`.
An entry whose `rejection_cause` is `use_file_execution` gains `error_code: "use_file_execution"` and
the same `next_action` as on `execute_command`, naming that entry's server and account, plus a
reminder to rerun only that server rather than the original target set.
A rejected entry gains `rejection_hint` beside the row's own `rejection_cause` and `rejection_gate`, as described under `execute_command` (#242).

### `execute_command_multi_server`
Execute a command on multiple servers simultaneously.

**Parameters:**
- `server_ids` (array): List of server IDs
- `command` (string): Command to execute; must not be empty or whitespace-only. The same sudo rule as `execute_command` applies, per server: a needless `sudo` prefix stalls that server's command on a human approver, or is denied outright with no request anyone can approve
- `workspace` (string): Workspace name
- `shell` (string, default: "system"): Shell type
- `username` (string, optional): Username for execution
- `groupname` (string, default: "alpacon"): Group name
- `env` (object, optional): Environment variables
- `parallel` (boolean, default: true): Execute in parallel; `false` runs the servers one after another
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `purpose` (string, optional): What this particular command is for (ADR 0052). The assessor judges the command with it in hand, so one that would otherwise queue for a human may clear on its own. State a fact local to this host that the Work Session description does not already imply; general knowledge adds nothing the assessor lacks, and a purpose cannot lower a command's intrinsic risk. Trimmed to 2000 characters rather than refused, and the response then carries `purpose_truncated: true`. This tool never waits, so it is never asked for a purpose after the fact—stating it up front is the only chance
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Refused as a script body:** the `use_file_execution` refusal described under `execute_command`, which
applies when the workspace approval policy blocks script bodies, is decided per server command after verification, so this tool's submit result never shows it and only
some targets may be refused. Read it from `list_commands`, where each refused entry carries
`error_code: "use_file_execution"` and a `next_action`. Rerun the script with `execute_file` on the
refused servers only, with the same account: the file lane needs every target server to support it,
so resubmitting the original target set can fail with `file_exec_unsupported_agent` on a server that
was never refused.

**Lost submission:** a server whose entry in `deploy_shell_results` carries `outcome_unknown: true` follows the `execute_command` rule: its command may exist and may have run, so check `list_commands` for that server, read back past the time of the call, before resubmitting to it, and ask a human once 100 newer commands fill the page.

### `state_command_purpose`
Answer the purpose demand on a command the verification gate is holding, then wait for the outcome.

Use it when `execute_command` returned `status: "purpose_required"`; the `command_id` is in that response.
The command re-enters judgment once with the purpose attached, and this call returns whatever that second
verdict produces—the command output when it clears, a `pending_approval` result when a human is still
needed, or an error when it is denied.

There is exactly one demand per command and it expires shortly, so a late or second answer is refused.
Only the principal that submitted the command may answer. A settled command and an answer from the wrong
principal share one server error, so a refusal cannot say which happened: read the command's state with
`list_commands` rather than re-submitting it.

**Parameters:**
- `command_id` (string): The held command, from the `purpose_required` response
- `purpose` (string): What the command is for. Trimmed to 2000 characters rather than refused, and the response then carries `purpose_truncated: true`
- `workspace` (string): Workspace name
- `timeout` (integer, default: 300): Timeout in seconds for the wait after the answer
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

---

## 📁 WebFTP tools

### `webftp_session_create`
Create a new WebFTP session for file transfer.

**Parameters:**
- `server_id` (string): Server UUID
- `workspace` (string): Workspace name
- `username` (string, optional): Username for FTP access (defaults to the authenticated user)
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `webftp_sessions_list`
Get list of WebFTP sessions.

**Parameters:**
- `server_id` (string, optional): Filter by server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `workspace` (string): Workspace name

### `webftp_upload_file`
Upload a local file to a server using S3 presigned URLs.

**Parameters:**
- `server_id` (string): Server UUID
- `local_file_path` (string): Absolute path to local file
- `remote_file_path` (string): Absolute path on server
- `workspace` (string): Workspace name
- `username` (string, optional): Username (defaults to authenticated user)
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `allow_overwrite` (boolean, default: true): Allow overwriting existing files

### `webftp_download_file`
Download a file or folder from a server. The call waits until the host has run the transfer command and the server reports the transfer succeeded, up to `ALPACON_MCP_WEBFTP_DOWNLOAD_TIMEOUT` seconds (default 60), checking the transfer once more at the deadline.

- Local mode: once the transfer is confirmed, streams the file to a temporary name beside `local_file_path` and moves it into place. A failed download leaves any file already at `local_file_path` untouched.
- Remote mode (streamable-http): returns `download_url`, a presigned URL valid for 24 hours, with a `curl` command in `tip`. The URL is returned only once the file is in place, so it can be fetched at once.

A transfer the host or server reports as failed returns `code: "download_failed"` with the server's message, and so does a create response with no download URL, which most likely means the token lacks the WebFTP download scope. A transfer still running when the wait ends returns `code: "download_timeout"` with `file_id`; follow it with `webftp_check_status`. In remote mode that error also carries `download_url`, which works once `webftp_check_status` reports the download completed.

A scoped API or service token without `command:read` (the `file_download` and `file_transfer` presets) cannot read the host's transfer command. The call then waits on the transfer status alone and fetches the file only after it reports success, so a command the host never runs ends in `download_timeout` rather than an early `download_failed`. `execute_file` with `read_from_server` behaves the same way.

**Parameters:**
- `server_id` (string): Server UUID
- `remote_file_path` (string): Absolute path on server
- `local_file_path` (string): Absolute path for local download
- `workspace` (string): Workspace name
- `resource_type` (string, default: "file"): "file" or "folder" (folders download as .zip)
- `username` (string, optional): Username (defaults to authenticated user)
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `webftp_upload_content`
Upload base64-encoded bytes as a file, with no local file on disk. Useful in hosted mode, where the server has no access to your filesystem.

On streamable-http and SSE, `file_content` is capped at 3 MiB of decoded (original) file bytes—base64 inflates bytes 4/3x, so the encoded string is larger. A file over this limit gets a tool error naming the limit and the size sent; use `webftp_upload_file` in local mode instead. A request far larger than that never reaches the tool at all—MCP SDK 2.x caps the streamable-http/SSE request body itself, and an oversized request fails as a plain-text HTTP 413 before any MCP error is produced. This limit is a stopgap around that SDK change; the upload path's design is being reconsidered in #275. Under stdio, no such request-body cap exists, so this tool imposes none either.

**Parameters:**
- `server_id` (string): Server UUID
- `file_content` (string): Base64-encoded content
- `remote_file_path` (string): Absolute path on server
- `workspace` (string): Workspace name
- `file_name` (string, optional): Name to record for the upload
- `username` (string, optional): Username (defaults to authenticated user)
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `allow_overwrite` (boolean, default: true)
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `webftp_bulk_upload`
Upload several local files to one directory in a single operation.

**Parameters:**
- `server_id` (string): Server UUID
- `local_file_paths` (array): Absolute paths to local files; must not be empty
- `remote_directory` (string): Absolute directory on server that receives every file
- `workspace` (string): Workspace name
- `username` (string, optional): Username (defaults to authenticated user)
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `allow_overwrite` (boolean, default: true): Allow overwriting existing files
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `webftp_bulk_download`
Download several files or folders as one ZIP archive.

**Parameters:**
- `server_id` (string): Server UUID
- `remote_paths` (array): Absolute paths on server sharing one parent directory; must not be empty
- `local_file_path` (string): Absolute path for the local ZIP archive
- `workspace` (string): Workspace name
- `username` (string, optional): Username (defaults to authenticated user)
- `work_session_id` (string, optional): Work Session to link the call to for audit; required for MCP OAuth and browser-login callers, optional for static API and service tokens; falls back to `ALPACON_WORK_SESSION` in the MCP server's environment when omitted, and an explicit value wins
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `webftp_check_status`
Check the status of an in-flight transfer.

**Parameters:** `file_id`, `transfer_type` (`upload` or `download`), `workspace`, `region` (`ap1` or `us1`, optional)

### `webftp_uploads_list`
List uploaded files (upload history).

**Parameters:**
- `workspace` (string): Workspace name
- `server_id` (string, optional): Filter by server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `webftp_downloads_list`
List download requests (download history).

**Parameters:**
- `workspace` (string): Workspace name
- `server_id` (string, optional): Filter by server UUID
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

---

## 🔐 Identity and access management (IAM)

> Manage users and groups with workspace-level isolation.

### User management

#### `list_iam_users`
List all IAM users in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
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
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

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
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

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
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Note:** Only provided fields will be updated. Omitted fields remain unchanged. Group membership is changed through `add_iam_member`/`remove_iam_member`, not here.

#### `delete_iam_user`
Delete IAM user from workspace.

**Parameters:**
- `user_id` (string): User ID to delete
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**⚠️ Warning:** This action is irreversible and will remove all user permissions and group memberships.

### Group management

#### `list_iam_groups`
List all IAM groups in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted
- `page` (integer, optional): Page number
- `page_size` (integer, optional): Groups per page

**Returns:** List of groups with member counts and permission summaries.

#### `create_iam_group`
Create a new IAM group.

**Parameters:**
- `name` (string): Group name: lowercase letters, digits, hyphens, and underscores only (immutable once created)
- `workspace` (string): Workspace name
- `display_name` (string, optional): Human-readable name
- `description` (string, optional): Group description
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

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
List group memberships. **Parameters:** `workspace`, `group_id` (optional filter: lists the members of one group), `region` (`ap1` or `us1`, optional), `page`, `page_size`.

#### `add_iam_member`
Add a user to a group. **Parameters:** `group_id`, `user_id`, `workspace`, `role` (`member`, `manager`, or `owner`; default `member`), `region` (`ap1` or `us1`, optional).

#### `remove_iam_member`
Remove a membership. **Parameters:** `membership_id`, `workspace`, `region` (`ap1` or `us1`, optional).

#### `invite_workspace_user`
Send an email invitation to join the workspace (Auth0-enabled deployments). **Parameters:** `email`, `workspace`, `region` (`ap1` or `us1`, optional).

### Application management (machine service accounts)

- `list_iam_applications`: `workspace`, `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `create_iam_application`: `name`, `workspace`, `description` (optional), `service_type` (optional: `ci_cd`, `monitoring`, `automation` or `integration`; default `integration`), `region` (`ap1` or `us1`, optional)
- `get_iam_application` / `update_iam_application` / `delete_iam_application`: by `app_id`
- `assign_application_system_users` / `unassign_application_system_users`: `app_id`, `system_user_ids` (array), `workspace`, `region` (`ap1` or `us1`, optional)

**Note:** Role and permission endpoints are not implemented in the Alpacon server, so there are no `list_iam_roles`, `assign_iam_user_role`, or permission tools.

---

## 🗂️ Work session tools

A Work Session is the unit of authorized work: a scope, a set of servers, an expiry, and an audit trail. OAuth/browser callers must have one active before executing commands or transferring files; static API tokens and service tokens bypass the gate.

### `work_session_create`
Open a session. **Parameters:** `workspace`, `scopes` (array; agents may request `command` for `execute_command` and `execute_file`, `webftp` for file transfers, `tunnel` for port forwarding, and `sudo` for privilege elevation—request `sudo` only when the work genuinely requires root, since a sudo invocation no policy covers routes to human approval), `servers` (array of UUIDs), `expires_at` (ISO 8601), `description`, `title` (optional), `target_account_username` (optional; the OS account commands will run as, such as `root`—set it when you intend to run as another account so it is approved with the session, then pass the same account as `username` to `execute_command` and `execute_file`; running directly as `root` is declared here, while the `sudo` scope is for elevation from another account; sent only when given), `region` (`ap1` or `us1`, optional). Only `title`, `target_account_username` and `region` may be omitted—a session with no expiry or no stated reason is not a session anyone can approve.

`description` is prose for the human who approves the session. It is not a command list and nothing in it is executed; commands run via `execute_command` once the session is active. Be specific: name the targets, the action, and what will not be touched, since a bare word like "maintenance" gives the approver nothing to decide on. Markdown is supported.

A session that needs human approval comes back with `status="pending_approval"`, and no command or file transfer runs in it until a human approves it out-of-band (Alpacon web console or Slack). Surface it to a person, then call `work_session_get` and proceed once `data.status` is `active`; stop if it is `rejected`, `cancelled`, `expired`, `revoked`, or `completed`, since those never become active.

### `work_session_get` / `work_session_list`
Read one session (`session_id`) or list them (`status`, `requester_type`, `limit` filters).

### `work_session_update` / `work_session_extend`
Partial update of `title`, `description`, `scopes`, `servers` (and `expires_at` for pending sessions only), or extend `expires_at` on an approved/active session. `description` carries the same prose-only rule as on `work_session_create`. `scopes` replaces the whole scope list, so list every scope the session keeps. An update that needs approval is queued as a modification request.

`work_session_extend` **parameters:** `session_id`, `workspace`, `expires_at` (ISO 8601, must be later than the current expiry), `reason` (required—a short justification the human approver judges the request by), `region` (`ap1` or `us1`, optional). Whether the extension applies immediately or waits for approval follows the workspace's approval policy, the same rule `work_session_create` uses: an auto-approve lane extends directly and the tool returns a normal success; any other lane queues an extension request instead, and the tool returns `status="pending_approval"`—the session's `expires_at` stays at its prior value until a human decides out-of-band. Poll `work_session_get` until `expires_at` changes to see the outcome; the session's `pending_extension_request` field names the open request until then. A blank `reason` is rejected with `error_code: work_session_extension_reason_required`.

### `work_session_timeline`
Chronological record of commands, file transfers, websh activity, and sudo grants, oldest first. **Parameters:** `session_id`, `workspace`, `region` (`ap1` or `us1`, optional), `cursor`, `page_size` (1 to 500; the server defaults to 100, and a larger value is refused locally with a `validation` error), and `include_records`, which is retired and refused. The endpoint pages only when a request names `cursor`, so the tool names it on every request, empty on the first, and walks the cursor the same way the audit tools do—see **Audit tools** for the `pagination` object and how to resume. Three things differ from those lists. The walk reads forward, so a result stopped at the bound holds the start of the session and omits its most recent activity. The paged timeline carries no websh terminal recordings; it names the sessions that have one, and `work_session_records` below reads them. `include_records` is still declared only so that passing it can be refused, since the SDK discards an argument the published schema does not name before the call. Any value, `true` or `false`, is answered with `status: "error"`, `error_code: "validation"` and `field: "include_records"` before any request is made. And an alpacon-server that predates the paged timeline ignores `cursor` and answers with the whole session and no `next`; that first answer is read as the whole list, reported `stopped_because: unpaginated_server` with `complete: true`, a value only this tool can return. If the call sent a `cursor` the server ignored, the `note` says so, because the records then start at the beginning of the session. A later page without `next` is an error, as it is for every list. A `command` item with a non-null `rejection_cause` gains `rejection_hint`, worded as on `execute_command` (#242); the timeline carries no `status`, so an item without a cause gets none.

### `work_session_records`
One page of one websh terminal recording captured inside the session: the output in chunks, oldest first, as `{added_at, record}` items. **Parameters:** `session_id` (the work session), `websh_session_id`, `workspace`, `region` (`ap1` or `us1`, optional), `cursor` (optional), `page_size` (1 to 16, default 8; a value outside that range is refused locally with a `validation` error before any request). Wraps `GET /api/work-sessions/sessions/{id}/records/?session=<websh session id>` and **requires alpacon-server 2.42.0 or later**.

`websh_session_id` is the `id` of a `websh_session` item on `work_session_timeline`, which is how you learn which sessions a work session recorded. The websh session must belong to this work session and must not be a tunnel, which records no terminal; one that does not, or that is outside what the caller may see, answers `404`. A missing or malformed `session` answers `400` with `error_code: invalid_input`. Reading a recording whole is a paid-plan feature, as it is on the websh route, so a Free workspace answers `402` (`error_code: workspace_plan_update_required`), and so does a session older than the plan's audit window.

Unlike `work_session_timeline` and the audit lists, this tool does not walk the cursor: one call is one request, and the response carries the server's page as it stands—`count`, `next`, `previous`, `results`—with no `pagination` object. Pass `data.next` back as `cursor` to read the page after it, and stop when it is null. A page is cut by a byte budget as well as by `page_size`, because a chunk dense in control sequences costs several times its raw size once JSON-escaped, so **a page holding fewer items than `page_size` is not the end of the recording**—only `next: null` is. A cursor is bound to the websh session it was minted for: keep sending the same `websh_session_id` while paging one recording, and start a new walk rather than carrying a cursor across recordings.

### `work_session_close` / `work_session_analyze`
Close a session (triggers AI security analysis) or re-run analysis on a terminal session (`force` to redo).

**Gate error codes:** `work_session_not_active` returns `status="pending_approval"`; `work_session_required`, `work_session_not_usable`, `work_session_expired`, `work_session_scope_not_allowed`, `work_session_server_not_allowed`, and `work_session_assignee_mismatch` return `status="error"` with a `next_action`. Set `ALPACON_WORK_SESSION` to supply a default session id when a tool's `work_session_id` argument is omitted.

---

## ✅ Approval and sudo tools

- `list_approval_requests`: `workspace`, `status` (optional), `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `get_approval_request`: `request_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `explain_approval_decision`: `workspace`, `request_id` (optional), `region` (`ap1` or `us1`, optional). Explains that deciding is human-only and out of band; performs no mutation
- `list_sudo_policies`: `workspace`, `region` (`ap1` or `us1`, optional), `page`, `page_size`, `user` (UUID), `server_id` (UUID)
- `request_sudo_policy`: `workspace`, `servers` (UUID list), `commands`, `reason`, `users` (optional UUID list), `valid_from`, `valid_until`, `region` (`ap1` or `us1`, optional). Creates an approval request, not a policy; returns `status="pending_approval"`. Omitting `users` scopes the approved policy to the requester alone, not to the whole workspace. `session_authorized` is not accepted: the server refuses it on this endpoint. For session-authorized sudo, a human must set `session_authorized` on the Work Session's sudo policy in the Alpacon web console; this needs an enterprise plan and a usable Work Session

There is intentionally no `approve_request`/`reject_request` tool: the Alpacon server refuses approve/reject from agent and token channels with HTTP 403. Approval happens in the web console or Slack.

---

## 🔔 Alert tools

- `list_alerts`: `workspace`, `server_id`, `alert_type`, `severity` (`critical`, `warning`, `info`), `server_name`, `acknowledged`, `dismissed`, `resolved`, `region` (`ap1` or `us1`, optional), `page`, `page_size`. `acknowledged=false` selects the active, unacknowledged alerts. `resolved` omitted returns open alerts only; `true` returns the resolved history instead; `false` is the explicit spelling of the default
- `get_alert`: `alert_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `acknowledge_alert`: `alert_id`, `workspace`, `action_type` (`checked` marks the alert as seen, `dismissed` as not worth acting on), `region` (`ap1` or `us1`, optional). One acknowledgement per user per alert, and it cannot be changed afterwards. A repeat call by the same user (alpacon-server 2.35.0 or later) returns `status: "success"` with `already_acknowledged: true`, a `message`, and no `data`. That call records nothing whatever `action_type` it sends; the existing acknowledgement's `action_type` is not in the response, and `get_alert` returns it as `action_type`. An older server refuses the repeat with `error_code` `invalid`, and any other `400` stays an error
- `create_alert_rule`: `workspace`, `name`, `target`, `threshold`, `is_default`, `operator` (`gte` or `lte`, default `gte`), `duration_s` (seconds the condition must hold; `0`, the default, fires on a single sample), `recovery_threshold`, `no_data_after_s` (floored at the target's collection interval), `device` (disk/interface name; device-scoped targets only), `severity` (`critical`, `warning`, `info`; default `warning`), `notify_email` (`all`, `admins`, `group_members`, or `none`; default `all`), `notify_slack_channel` (boolean; default `true`), `region` (`ap1` or `us1`, optional). `target` is a metric the workspace exposes, e.g. `cpu-usage`, `memory-usage`, `disk-usage`, or one of the peak/avg bps or pps network and disk rates; the server holds the authoritative list and rejects an unrecognized value with `400`. `device` is accepted only for a device-scoped target—`cpu-usage` and `memory-usage` are host-wide. `notify_email` and `notify_slack_channel` decide who hears about alerts this rule raises; only a human caller may set them—a service-token or agent write naming either is refused with `400` (`metrics_alert_rule_destination_not_allowed`), and an `info`-severity rule sends no mail and posts to no channel regardless of either setting
- `update_alert_rule`: `rule_id`, `workspace`, and any of `name`, `target`, `threshold`, `is_default`, `operator`, `duration_s`, `recovery_threshold`, `no_data_after_s`, `device`, `severity`, `notify_email`, `notify_slack_channel`—sent only for the fields given. `target`, when given, is subject to the same rule as `create_alert_rule`: the server holds the authoritative list and rejects an unrecognized value with `400`. `notify_email`, when given, is one of the same four choices as on `create_alert_rule` (`all`, `admins`, `group_members`, `none`); `notify_slack_channel` is a boolean. Both carry the same human-only restriction and `info`-severity behavior as on `create_alert_rule`; omitted, each keeps the rule's current value
- `delete_alert_rule`: by `rule_id`. A rule with `is_default=true` cannot be deleted
- `attach_alert_rule` / `detach_alert_rule`: `server_id`, `rule_id`, `workspace`, `region` (`ap1` or `us1`, optional). Each is idempotent in the state it aims at: attaching a rule the server already has changes nothing, and so does detaching a rule the server does not have
- `get_alert_rule_recipients`: `rule_id`, `workspace`, `region` (`ap1` or `us1`, optional). Preview who the rule would notify, as counts only—never names. Requires alpacon-server 2.36.0 or later. Returns `email` (`mode`, `count`, `reasons` with `admins`/`group_members`/`owner`—these overlap each other and need not sum to `count`), `slack_channel` (`enabled`, `connected`—both stay as configured for an `info`-severity rule even though `info` posts nothing), and `event_subscriptions` (machine listeners, unaffected by either destination). Counted over the servers the rule is attached to that the caller can see and that the rule can actually fire on; a `404` while the rule itself reads fine through `get_alert_rules` means every one of its servers is outside what the caller can see, not that the rule is gone, while a rule attached to no server answers zeros
- `preview_alert_rule`: `workspace`, `rule_id` (optional), `servers` (optional UUID list, up to 20), `window_s` (optional; `60` to `604800`, default `86400`), any of `target`, `threshold`, `operator`, `duration_s`, `recovery_threshold`, `no_data_after_s`, `device`, `severity`, `notify_email`, `notify_slack_channel` (the `create_alert_rule` fields minus `name` and `is_default`, sent only when given), `region` (`ap1` or `us1`, optional). Replays the rule over the window's realtime samples with the live evaluator's own logic, one tick every 60 seconds, and stores nothing. Without `rule_id` the fields describe a new rule and `servers` is required; with `rule_id` they override that rule's values (give none to preview it unchanged), its server overrides apply, and `servers` defaults to its attached servers. Returns `window` (`start`, `end`), `sample_interval_s`, `summary` (`episodes`, `would_interrupt`, `open_at_end`, `longest_s`), `servers` (one row per server and device: `server`, `device`, `samples`, `episodes` with `condition`, `raised_at`, `resolved_at`, `peak`, `outlived_hold`, `would_interrupt`), `recipients` (the `get_alert_rule_recipients` shape, over the replayed servers), and `not_reproduced`. Refused with `400` and an `error_code`: `metrics_alert_rule_preview_window_too_long` (`window_s` over seven days), `metrics_alert_rule_preview_too_many_servers` (over 20 servers, or servers × `window_s` over 5 × 604800), `metrics_alert_rule_preview_too_many_samples` (over 300,000 samples), `metrics_alert_rule_preview_servers_required` (neither `rule_id` nor `servers`), and `server_not_found` (an entry in `servers` is unknown or out of reach). A `404` means no rule with `rule_id`, or every server it is attached to is outside what the caller can see. `notify_email` and `notify_slack_channel` carry the same human-only restriction as on `create_alert_rule`

Creating and updating a rule need a paid plan; reading, attaching and detaching work on any plan. A
listed or fetched alert can carry `device` and `severity` from the rule that raised it, and
`resolved_at` once the condition clears.

#### Rule overrides

A per-server departure from a workspace alert rule, against `/api/metrics/rule-overrides/`. `server` and `rule` identify the override; `threshold`, `recovery_threshold`, `duration_s`, and `enabled` are nullable per-field overrides—a field left unset keeps the rule's own value for that server, and `enabled=false` exempts the server from the rule entirely regardless of the other fields. At most one override per `(server, rule)` pair; a second create for the same pair is refused.

- `list_rule_overrides`: `workspace`, `server_id` (optional), `rule_id` (optional), `enabled` (optional), `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `get_rule_override`: `override_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `create_rule_override`: `server_id`, `rule_id`, `workspace`, `threshold`, `recovery_threshold`, `duration_s`, `enabled` (all four optional), `region` (`ap1` or `us1`, optional)
- `update_rule_override`: `override_id`, `workspace`, and any of `server_id`, `rule_id`, `threshold`, `recovery_threshold`, `duration_s`, `enabled`—sent only for the fields given
- `delete_rule_override`: by `override_id`

---

## 🛡️ Security ACL tools

Command ACLs decide which commands a token may run, server ACLs which hosts it may reach, file ACLs which paths it may transfer.

The `command` and `path` a rule matches on must not be empty or whitespace-only. Both are patterns the server matches against, so a blank one is a pattern of its own rather than a missing value, and `create_command_acl`, `update_command_acl`, `create_file_acl`, and `update_file_acl` reject it before the request is built. The catch-all is `*`.

- `list_command_acls`: `workspace`, `api_token_id`/`service_token_id` filters, `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `create_command_acl`: `workspace`, `command`, `api_token_id` or `service_token_id`, `username`, `groupname`, `region` (`ap1` or `us1`, optional)
- `update_command_acl` / `delete_command_acl`: by `acl_id`
- `list_server_acls` / `create_server_acl` (`server_id` + token id) / `update_server_acl` / `delete_server_acl`
- `bulk_server_acl`: `workspace`, `action` (add or remove), `server_ids` (array), token id, `region` (`ap1` or `us1`, optional)
- `list_file_acls` / `create_file_acl` (`path`, `action`) / `update_file_acl` / `delete_file_acl`

On a server that manages command ACLs on the command pre-approval ledger, `create_command_acl`, `update_command_acl`, and `delete_command_acl` are refused with 405 and `error_code` `command_acl_moved`; retrying the call does not help. A Command ACL admin then issues or revokes the entry under Pre-approved commands on the service token's page in the web console, or, on a server that registers them, with the [command pre-approval ledger tools](#-command-pre-approval-ledger-tools). The error hint, the tool descriptions and the 403 recovery hint name those tools only there: on stdio, and on streamable-http with `ALPACON_MCP_REMOTE_LEDGER=true`. A personal API token has no command list on the ledger. `list_command_acls` still answers there, but those rules no longer decide anything; a server without the ledger keeps accepting all four.

---

## 📜 Command pre-approval ledger tools

On a workspace whose `command_acl_surface` is `ai`, the pre-approvals that let a token run a command without a human approval live on the command pre-approval ledger—the Pre-approved commands card in the web console—instead of in the command ACL tools above. Every tool here first reads `GET /api/auth/env/` on the workspace server. A workspace reporting `upstream` (or a server too old to report the field) is refused with `command_acl_surface: "upstream"` and pointed to the command ACL tools; `get_ledger_capability` answers it as a success instead.

The ledger accepts only a person's token issued for its own audience, never an API or service token, and only a Command ACL admin of the workspace may read or change it. Over stdio, the first ledger call in a process returns `status: "authorization_required"` with `verification_uri_complete`, `verification_uri`, `user_code`, `expires_in` and `requires_human_action: true`. Show the link to the user; once they open it, confirm the code and sign in, call the same tool again. The agent cannot complete this step itself. The token covers one workspace, lives in memory only, carries no refresh token, and expires after the period the sign-in service sets; a restarted process or an expired token asks again. A declined or failed sign-in returns `status: "error"` with the sign-in service's `error_code`, and the next call starts over.

In remote mode (streamable-http), the tools are registered only when the operator sets `ALPACON_MCP_REMOTE_LEDGER=true`, and there is no link to show. A call without a usable ledger token answers the transport request with 403 `insufficient_scope` and `ledger:<workspace>` in the challenge's scope, which tells the MCP client to open a new sign-in; the person completes it, and the same tool is called again. When the client cannot act on that (for example within the 60-second re-auth cooldown), the tool returns `status: "authorization_required"` with `requires_human_action: true` and a message naming the workspace, but no `verification_uri`. The ledger token is kept in that client's own credential, never in the process, so it reaches no other connection or person and any replica can use it. It covers one workspace at a time, the one most recently asked for, and has no refresh: once it expires, or for another workspace, the next call asks for the sign-in again, and a 401 from the ledger does the same with the ledger's body in `detail`. A ledger sign-in that finished in the last 10 minutes without a token the ledger accepts (Auth0 refused that leg, or the ledger answered 401 to the token it just issued) is not asked for again: the call returns `status: "error"` saying the server is likely not allowed the ledger audience, with the ledger's 401 body in `detail` when there is one, so a misconfiguration cannot send the person around sign-ins in a loop. The process cache above is never read in remote mode. See `docs/configuration.md` for the Auth0 settings this needs.

SSE never registers these tools, and neither does streamable-http without `ALPACON_MCP_REMOTE_LEDGER`; a call that reaches one anyway returns an error pointing to the web console before any sign-in is read. The ledger host defaults to `https://alpacon.ai`; `ALPACON_MCP_LEDGER_URL` and `ALPACON_MCP_LEDGER_AUDIENCE` override the host and the audience.

A refusal from the ledger keeps its body in `detail`, which names the field and the reason, for example `{"workspace_id": ["This account does not administer that workspace."]}` for a person who is not a Command ACL admin of it, or `{"entries": ["Row 0 is a grant the ledger already holds: ..."]}` for a duplicate.

A 401 from the ledger also keeps its body in `detail`. Over stdio, when the refused token was cached by an earlier call, it was revoked or expired early, so the call returns `authorization_required` with a new link. When the token was issued during the same call, another sign-in would be refused the same way, so the call returns an error instead, usually pointing at a mismatched `ALPACON_MCP_LEDGER_URL` or `ALPACON_MCP_LEDGER_AUDIENCE`. The next call starts a new sign-in.

The list and issue tools, and `grant_ledger_admin`, name the workspace's id to the ledger. The tools that take an `entry_id`, `entry_ids` or `admin_id` do not: the ledger resolves an id only among the workspaces the signed-in person administers, and answers an id outside them as not found. Their `workspace` argument selects whose sign-in to use, not which workspace the id belongs to.

- `get_ledger_capability`: `workspace`, `region` (`ap1` or `us1`, optional). Returns `command_acl_surface`; on the ledger also `is_ledger_admin`, `administers_workspace` (this workspace), `workspace_id` and `workspace_ids`
- `list_ledger_entries`: `workspace`, `principal_type` (`service_token` or `api_token`; `api_token` finds entries a personal API token kept from before, which the revoke and disable tools still reach), `principal_id`, `page`, `page_size` (at most 200), `region` (`ap1` or `us1`, optional). Active entries only; the page carries `count`, `current`, `next`, `previous`, `last`, `results`
- `issue_ledger_entries`: `workspace`, `entries` (1 to 200), `region` (`ap1` or `us1`, optional). Each entry takes `principal_type` (`service_token` only: a personal API token has no command list on the ledger, and a batch naming `api_token` is refused before anything is sent), `principal_id` (the service token's UUID), `command_pattern`, `username` (`*` for any user), and optionally `groupname`, `server_ids` (omit to apply on every server, which the ledger flags in `warnings`), `expires_at`, `enabled`. All or nothing. An entry is never edited: revoke it and issue a new one
- `revoke_ledger_entry`: `workspace`, `entry_id`. The entry stops matching and stays readable for audit
- `revoke_ledger_entries`: `workspace`, `entry_ids` (1 to 200). All or nothing; returns `revoked`
- `disable_ledger_entry` / `enable_ledger_entry`: `workspace`, `entry_id`. Reversible, unlike a revocation
- `list_ledger_admins`: `workspace`, `page`, `page_size`, `region` (`ap1` or `us1`, optional)
- `grant_ledger_admin`: `workspace`, `subject` (the person's Auth0 user id), `email` (optional), `region` (`ap1` or `us1`, optional). A machine principal is refused
- `revoke_ledger_admin`: `workspace`, `admin_id`. The last admin of a workspace cannot be removed

---

## 📝 Audit tools

`list_activity_logs`, `list_server_logs`, and `list_webftp_logs` read Elasticsearch-backed endpoints that alpacon-server paginates by cursor, not by page number; they take no `page`, and one passed anyway is dropped without an error. Each call follows the cursor for up to 10 requests and merges the pages, so `data.results` spans all of them and `data.count` stays the server's total match count. A top-level `pagination` object reports the walk: `complete`, `stopped_because` (`end_of_list`, `page_bound`, `upstream_error`), `started_from_cursor`, `pages_read`, `max_pages`, `records_returned`, `next_cursor`, and, when there is something to explain, a `note`. Check `pagination.complete` before treating the result as the whole list, and pass `pagination.next_cursor` back as `cursor` to continue; an empty `cursor` starts from the beginning. A call resumed from `cursor` holds only the records after it, so it is never `complete` on its own: when it reads to the end it reports `stopped_because: end_of_list` with `complete: false`, and the whole list is its records together with those of the calls before it. A request that fails partway through, or a page that is not a well-formed cursor page (no `results` list, no `next`, a `next` that is neither null nor a cursor string, or a `next` repeating the cursor just sent), returns an error carrying the same object with `records_discarded`; the partial list is not handed back as a success, and `next_cursor` is where the walk started, so a retry reads the discarded records again. When the server refuses the cursor (`error_code` `api_cursor_expired` or `api_invalid_cursor`), `next_cursor` is null: retry from the start.

- `list_activity_logs`: `workspace`, `region` (`ap1` or `us1`, optional), `cursor`, `page_size`
- `get_activity_log`: `log_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `list_server_logs`: command execution history; `workspace`, `server_id` (optional), `cursor`, `page_size`
- `list_webftp_logs`: file transfer history; same parameters
- `list_session_analyses`: AI security analyses; a plain page-numbered list, so `page` applies here; `workspace`, `server_id`, `status`, `risk_score`, `page`, `page_size`
- `get_session_analysis_detail`: `analysis_id`, `workspace`, `region` (`ap1` or `us1`, optional). Includes MITRE ATT&CK mapping

---

## 📦 Package tools

- `list_system_package_entries`: `server_id`, `workspace`, `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `install_system_package`: `server_id`, `package_name`, `workspace`, `version` (optional), `region` (`ap1` or `us1`, optional)
- `remove_system_package`: `entry_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `list_python_packages` / `install_python_package` / `remove_python_package`: same shape, via pip

---

## 📜 Certificate tools

**Authorities:** `list_certificate_authorities`, `create_certificate_authority` (`name`, `domain`, `organization`, `server_id`, `owner`, `root_valid_days`, `default_valid_days`, `max_valid_days`, `key_algorithm` (`rsa` or `ecdsa`), `key_size` (2048 or 4096 for RSA, 256 or 384 for ECDSA), `install`), `get_certificate_authority`, `update_certificate_authority` (`default_valid_days`, `max_valid_days`, `owner`), `delete_certificate_authority` (only a CA that has never received a sign request; otherwise the server answers 400 with `cert_authority_cannot_be_deleted` and keeps the CA and its sign requests, certificates, and revoke requests. Retiring such a CA means removing its whole host with `unregister_server`, which takes the host out of the workspace, so do it only when the host itself is to be retired; a still-connected host needs `auto=True`, which also removes its Alpamon agent. Once the host is gone the CA leaves the list and takes no new sign requests; requests already pending are not cancelled).

**Signing requests:** `list_sign_requests`, `create_sign_request` (`domain_list` for DNS names, `ip_list` for IP addresses, `valid_days`), `get_sign_request`, `approve_sign_request`, `deny_sign_request`, `retry_sign_request` (for a CSR stuck in signing), `delete_sign_request` (cancels a pending CSR).

**Certificates:** `list_certificates` (`authority_id` filter), `get_certificate`, `revoke_certificate` (`reason`, an RFC 5280 code: 0 unspecified, 1 key compromise, 2 CA compromise, 3 affiliation changed, 4 superseded, 5 cessation of operation, 6 certificate hold, 9 privilege withdrawn, 10 AA compromise; `requested_reason`, free text; auto-approved when the caller owns the CA or is an admin, otherwise it waits for approval).

**Revocation requests:** `list_revoke_requests`, `get_revoke_request`, `approve_revoke_request`, `deny_revoke_request`, `retry_revoke_request`, `cancel_revoke_request`.

---

## 🔗 Webhook tools

- `list_webhooks`: `workspace`, `provider` (one of `slack`, `discord`, `teams`, `telegram`, `custom`), `region` (`ap1` or `us1`, optional), `page`, `page_size`
- `get_webhook` / `delete_webhook`: by `webhook_id`
- `create_webhook`: `workspace`, `name`, `url`, `owner` (user UUID, required), `provider` (optional), `ssl_verify`, `enabled`, `region` (`ap1` or `us1`, optional). `provider` is one of `slack`, `discord`, `teams`, `telegram`, `custom`, and is detected from the URL when omitted
- `update_webhook`: `webhook_id`, `workspace`, and any of `name`, `url`, `ssl_verify`, `enabled`
- `list_event_subscriptions` / `create_event_subscription` (`channel`, `event_type`, `target_id`) / `delete_event_subscription`. `event_type` includes `command_fin`, `servers_commit`, `sudo`, and (with the workspace's metrics extension enabled) `metric_threshold_crossed` / `metric_threshold_resolved`, which pair through the `alert_id` they carry; subscribing to every server (an omitted `target_id`) needs an admin account

Webhook tools need an admin account, and creating or updating a webhook needs a paid plan.

---

## 🎫 API token tools

- `list_api_tokens`: `workspace`, `region` (`ap1` or `us1`, optional), `page`, `page_size`, `name`, `enabled`, `search` (name only), `ordering` (`added_at`, `updated_at`, `last_used_at`)
- `get_api_token`: `token_id`, `workspace`, `region` (`ap1` or `us1`, optional)
- `create_api_token`: `workspace`, `name`, `scopes`, `presets`, `expires_at`, `enabled`, `region` (`ap1` or `us1`, optional). An omitted `expires_at` is issued at the workspace maximum lifetime
- `update_api_token`: `token_id`, `workspace`, `name`, `enabled`, `expires_at`, `clear_expires_at`, `scopes`, `region` (`ap1` or `us1`, optional). `clear_expires_at` sends a null expiry, which the server resets to the workspace maximum lifetime; no token can be made non-expiring
- `delete_api_token` / `duplicate_api_token`: by `token_id`
- `rotate_api_token`: `token_id`, `workspace`, `region` (`ap1` or `us1`, optional). Regenerates the secret in place; the old secret dies immediately, and the id, name, scopes and ACLs survive. A token that had no expiry comes back with the workspace maximum expiry, and one already past its expiry is refused with 400 `API_TOKEN_ALREADY_EXPIRED`. Paid plans only
- `list_api_token_scopes` / `list_api_token_presets`: catalogs for building a token

**Authentication note:** the server rejects these calls when the request is authenticated with a `source='api'` token, so in stdio mode with a `token.json` token they return `403 Forbidden`. Use the hosted server (JWT/OAuth), a browser session, or a login-source token. The scopes and presets catalogs are exempt.

---

## 🏢 Workspace management

### `list_workspaces`
Get list of available workspaces. Takes no `workspace`—it is how you find the name every other tool needs.

**Parameters:**
- `region` (`ap1` or `us1`, optional): Restrict the listing to one region; omit to list every configured region; an unknown region is rejected as a validation error, not answered with an empty list

**Note:** `data.unusable_entries` counts the JWT workspace claim entries that named no workspace or no region and were therefore left out of `data.workspaces`. A non-zero count means the Auth0 organization metadata is missing a `region`, not that access was denied: such an entry authorizes nothing either way. A `region` filter does not narrow the count, since a dropped entry belongs to no region, and the count is always 0 in local mode, which reads `token.json` instead of a JWT.

### `get_current_user`
Get the authenticated user: username, email, role, UID, shell, home directory.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

### `health_check`
Check MCP server health: version, uptime, authentication mode, connection pool. Takes no parameters.

### `get_workspace_access_control`
Get the workspace access control settings: sudo/root access policy (`allow_sudo_with_mfa`, `allow_direct_root`, `block_local_sudo`, `sudo_timeout`), tunnel/editor defaults, `home_directory_permission`, Work Session TTLs (`work_session_max_ttl`, `work_session_pending_ttl`), command-env audit exposure, and `shared_account_names`.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Note:** On-premise deployments omit the MFA-related fields (`allow_sudo_with_mfa`, `block_local_sudo`, `sudo_timeout`).

### `get_workspace_security`
Get the workspace authentication/security settings: `mfa_required`, `allowed_mfa_methods`, `mfa_timeout`, and which actions require MFA.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Note:** Requires JWT (OAuth/SSO) authentication. The upstream `SecuritySettingsViewSet` has no `APITokenAuthentication`, so a static API token (stdio mode) is rejected before any request is sent; use remote/streamable-http (browser SSO) mode to read these settings.

**Note:** This route is also SaaS-only. On-premise deployments return 404 from the upstream API; this tool reports that the settings are not available on this deployment instead of a generic error.

### `list_workspace_mfa_methods`
List the MFA methods allowed for the workspace (`allowed_mfa_methods`, `passkey_as_mfa`). Useful when guiding a user through the remote/streamable-http MFA re-authentication flow.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Note:** Like `get_workspace_security`, this requires JWT (OAuth/SSO) authentication (a static API token is rejected up front) and the route is SaaS-only.

### `get_workspace_preferences`
Get the workspace-wide preferences: timezone, locale, `front_url`, `invite_ttl`, `enabled_extensions`, `websh_session_timeout`, `agent_rollout_policy`, `package_proxy`, `billing_email`. Workspace-global configuration, not per-user.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**Note:** The response also includes `auto_agent_upgrade`, a deprecated boolean derived from `agent_rollout_policy` (`true` unless `mode` is `manual`) that will be removed from the server response. Read `agent_rollout_policy`.

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
- `agent_rollout_policy` (object, optional): The agent-upgrade rollout policy: `{"mode": "latest"|"n_minus_1"|"manual", "window": {"days": [0-6, Monday is 0], "start_hour": 0-23, "length_hours": 1-24, "timezone": "<IANA>"}}`. A write may name only part of the object (just `mode`, or just one `window` key); whatever it leaves out keeps its current value. `manual` runs no automatic upgrade; `latest` and `n_minus_1` (one release behind) run the scheduled upgrade inside the window. The shape is validated locally before the request is sent
- `package_proxy` (string, optional): Proxy server URL for package installation
- `billing_email` (string, optional): Billing contact email; SaaS-only field
- `region` (`ap1` or `us1`, optional): Region name; resolved from the workspace when omitted

**⚠️ Warning:** `timezone` is the workspace's billing clock—changing it shifts the daily usage-aggregation boundary. `enabled_extensions` replaces the whole list rather than appending—read the current value, merge, then send. `billing_email` is only accepted by the server on SaaS deployments.

**Note:** Choosing `n_minus_1` can be refused with a `400` (`error_code: preferences_agent_rollout_mode_unavailable`) until this deployment has pinned agent-upgrade targets enabled—use `latest` or `manual` instead. A malformed `agent_rollout_policy` object is rejected locally with a field-specific message before any request is sent; a shape-valid object the server still refuses comes back with the coded `error_code` (`preferences_agent_rollout_policy_invalid`, `_mode_invalid`, `_window_days_invalid`, `_window_start_hour_invalid`, `_window_length_invalid`, `_window_timezone_invalid`) and an actionable message.

### Why access control and security are read-only here

Notifications and preferences have write tools; access control and security settings deliberately do not. On SaaS the server gates those governance-level writes behind a superuser session with fresh MFA, which a static API token cannot satisfy. On-premise the same writes need only an admin token with the `workspaces` scope, so a token could technically perform them—but keeping governance settings human-only, in the web console, is the safer default regardless of deployment. This is a deliberate omission, not a gap to fill.

There are likewise no user-settings or user-profile tools: `/api/user/settings/` and `/api/user/profile/` do not exist on the Alpacon server. The endpoints that do exist for adjacent data are `/api/profiles/preferences/` and `/api/workspaces/preferences/` (exposed above). Role and permission management endpoints do not exist either, which is why the IAM section has no role or permission tools.

---


## 🔍 Resources and prompts

Most read tools are also exposed as read-only MCP resources under the `alpacon://` scheme, so a client can pull data without a tool call. `search_events`, `get_registration_guide`, `work_session_timeline`, `work_session_records`, `explain_approval_decision`, `webftp_check_status`, and `health_check` are tool-only. The URI convention is `alpacon://<domain>[/<sub>]/{region}/{workspace}[/{id}]`; optional filters are not part of the URI, so resources use each tool's defaults.

- `alpacon://servers/{region}/{workspace}` — also `/{server_id}`, `/{server_id}/overview`, `/{server_id}/notes`; a single note is `alpacon://server-notes/{region}/{workspace}/{note_id}`
- `alpacon://metrics/{region}/{workspace}/{server_id}/{cpu|memory|disk|disk-io|summary}`, `alpacon://metrics/{region}/{workspace}/{server_id}/network/{interface}` and `alpacon://metrics/{region}/{workspace}/top`—also `alpacon://metrics/{region}/{workspace}/latest` and `alpacon://metrics/{region}/{workspace}/latest/stale` (pinned to `state=stale`), each returning only the first page at the API's default page size; read the rest with `list_latest_metrics` and `page`, adding `state="stale"` for the stale one
- `alpacon://system/{region}/{workspace}/{server_id}/{info|os-version|users|groups|packages|network-interfaces|disk-info|time}`
- `alpacon://alerts/{region}/{workspace}`, `alpacon://alerts/active/{region}/{workspace}`, `alpacon://alert-rules/{region}/{workspace}`, `alpacon://alert-rules/{region}/{workspace}/{rule_id}/recipients`, `alpacon://rule-overrides/{region}/{workspace}` (also `/{override_id}`)
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

### Refusal fields

A coded refusal from a current alpacon-server can carry up to four more fields, and each one rides the error result as sent when present (#242). `gate` is the class of control that refused (`work_session`, `role`, `token_scope`, `server_reach`, `command_acl`, `file_acl`, `approval`, `presence`, `risk`, `sudo`, `plan`, `rate`). `missing` is the class of prerequisite that is absent, or a `scope:<scope>` literal a token lacked, as a string or a list of strings. `next` is a self-relative status path or documentation reference: read it as where to look or wait, never as a call to make. `hint` is the server's guidance sentence.

```json
{
  "status": "error",
  "status_code": 403,
  "error_code": "auth_token_scope_insufficient",
  "gate": "token_scope",
  "missing": "scope:command:execute",
  "message": "HTTP 403 The credential lacks the command:execute scope. Ask a workspace admin for a token that carries it; you cannot add a scope yourself."
}
```

A server `hint` is appended to `message` and replaces every local hint: the per-code hint, the gate hint, and `recovery_hints`/`related_tools`. Without one, a code with its own hint keeps it. Otherwise a known `missing` class, then a known `gate`, picks a local hint that names whom to ask or where to wait and never a tool that creates the missing thing; a recognized `gate` or `missing` also drops the status-based `recovery_hints`. `plan` and `rate` have no gate hint here, so the 402 and 429 recovery hints still apply to them. A gate or class this server does not know rides through with no local hint. An older server sends none of these fields, and its errors come back exactly as before; any other unknown field is ignored. A Work Session gate result and a plan-limit result carry the same fields beside their own, but keep their own `message` and `next_action`: a server `hint` rides there as a field only.

### Plan-limit refusals (402)

A 402 whose body carries `gate: "plan"` and an `axis`—or, from an older or
self-hosted alpacon-server, a gate-less `server_limit_exceeded`,
`user_limit_exceeded`, `application_limit_exceeded`, `websh_limit_exceeded`,
`webftp_limit_exceeded`, or `websh_share_limit_exceeded`—is a **plan-limit**
refusal: the workspace hit a plan limit on that axis, not a permissions or
input problem. It comes back structured instead of a generic error:

```json
{
  "status": "error",
  "error_code": "server_limit_exceeded",
  "gate": "plan",
  "axis": "server",
  "next": "/api/workspaces/workspaces/<id>/entitlements/",
  "requires_human_approval": false,
  "next_action": "Do not retry. Tell the user the servers plan limit was reached; remove one no longer used or upgrade; if this host was registered before, delete the old server entry first, then retry; upgrade at https://alpacon.io/<workspace>/settings/billing; or talk to us: https://www.alpacax.com/alpacon/pricing"
}
```

`next` is the server's self-relative entitlements-read pointer on a count-cap
axis (`server`, `user`, `application`, `workspace`); it is `null` on a
monthly axis (`websh`, `webftp`, `websh-share`), where `next_action` instead
says the allowance resets at the end of the month. The billing link in
`next_action` resolves from the workspace this call was made against—an
Alpacon Cloud workspace (`<label>.<region>.alpacon.io`) gets a direct
`https://alpacon.io/<label>/settings/billing` link; a self-hosted deployment
gets the words "Settings → Billing in your Alpacon console" instead. Retrying
does not change the answer; `requires_human_approval` is `false` because the
caller (an admin, or whoever can free up or upgrade the plan) can usually
resolve it directly, without an out-of-band approval.

A 402 with `gate: "plan"` and **no** `axis` is a feature lock, not a plan
limit (the plan itself excludes the action, on any usage). It stays a plain
error with `error_code` set and, for a curated few codes, an actionable hint
appended to `message`—the same handling any other 4xx `code` gets.

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