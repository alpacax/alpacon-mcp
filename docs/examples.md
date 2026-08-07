# Usage examples

Task-shaped examples: what to ask for, which tools answer it, and what to do when the platform says no. Every tool named here exists—see the [API Reference](api-reference.md) for full parameters.

Two things shape almost every example:

- **Server IDs are UUIDs.** Start from `list_servers` and carry the UUID forward. A server name will be rejected.
- **`workspace` is required, `region` is not.** The region is resolved from the workspace unless one token spans several regions.

---

## 🔎 Read-only inspection

Nothing here changes state, and none of it needs a Work Session.

### Survey the fleet

> *"List the servers in the production workspace and tell me which ones are offline."*

1. `list_servers(workspace="production")`
2. Read `status` per server; page with `page`/`page_size` on a large fleet

### One server, everything at once

> *"Give me the full picture of server web-01."*

1. `list_servers` to resolve the name to a UUID
2. `get_server_overview(server_id, workspace)`—hardware, OS, uptime, network interfaces, disk layout in a single call
3. `get_server_metrics_summary(server_id, workspace, hours=24)` for CPU, memory, disk, and network together

Prefer `get_server_overview` over calling `get_system_info`, `get_os_version`, `get_network_interfaces`, and `get_disk_info` separately—it is one round trip instead of four.

### Narrow a performance question

> *"CPU on web-01 spiked last night—show me the window."*

```
get_cpu_usage(
    server_id="7e3984de-49ab-4cc6-bcdf-21fbd35858b8",
    workspace="production",
    start_date="2026-08-05T18:00:00Z",
    end_date="2026-08-06T06:00:00Z",
)
```

Related: `get_memory_usage`, `get_disk_usage` (by `device` or `partition`), `get_disk_io`, `get_network_traffic` (by `interface`).

### Rank the fleet

> *"Which servers are working hardest right now?"*

`get_top_servers(workspace, metric_types="cpu,memory")` ranks the top five by usage over the last 24 hours and takes several metrics in one call.

### Who is on this host

> *"List the accounts on web-01 that can log in, and the groups they belong to."*

1. `list_system_users(server_id, workspace, login_enabled_only=True)`
2. `list_system_groups(server_id, workspace)`

These read the agent's collected inventory—no command execution, no ACL needed. If the data looks stale, `update_information(server_id, workspace)` asks the agent to re-collect it.

---

## 🗂️ Working inside a Work Session

When you reach Alpacon through OAuth (the hosted server at `mcp.alpacon.io`, or any browser-authenticated client), command execution and file transfers must happen inside an active Work Session. Static API tokens bypass this, so in stdio mode you can skip ahead.

### The shape of the flow

> *"I need to restart nginx on web-01."*

```
1. work_session_create(
       workspace="production",
       scopes=["command"],
       servers=["7e3984de-49ab-4cc6-bcdf-21fbd35858b8"],
       expires_at="2026-08-06T05:00:00Z",
       title="Restart nginx on web-01",
       description="Service unresponsive since 03:10 UTC",
   )
2. → status="pending_approval"  → a human approves in the web console or Slack
3. work_session_get(session_id, workspace)  → status="active"
4. execute_command(server_id, command="systemctl restart nginx",
                   workspace="production", work_session_id=session_id)
5. work_session_close(session_id, workspace)
```

Ask for the narrowest scope that does the job: `command`, `webftp`, and `tunnel` are the scopes an agent may request. A session scoped to one server and one purpose is approved faster and audits cleanly.

Setting `ALPACON_WORK_SESSION` supplies a default session id, so tools called without `work_session_id` still land inside it. An explicit argument always wins.

### Reading a denial instead of guessing

The gate answers in a structured way. Each code has one right move:

| Result | Meaning | Next step |
|---|---|---|
| `work_session_not_active` (`status="pending_approval"`) | The session awaits human approval | Surface it to a person; retry after approval |
| `work_session_required` | No session at all | `work_session_create` |
| `work_session_scope_not_allowed` | Session lacks the scope this call needs | `work_session_update` to add it, or open a fitting session |
| `work_session_server_not_allowed` | Server is outside the session | `work_session_update` the server list |
| `work_session_expired` | Window closed | `work_session_extend`, or open a new session |
| `work_session_assignee_mismatch` | Session belongs to someone else | Open your own |

A sudo escalation can also come back as `status="pending_approval"` with `SUDO_APPROVAL_REQUIRED` or `SUDO_INTENT_DEVIATION`. An agent cannot approve its own request—`explain_approval_decision` states this and points at the human channel.

### After the work: the audit trail

> *"What actually happened in that session?"*

1. `work_session_timeline(session_id, workspace)`—commands, transfers, terminal activity, and sudo grants in execution order
2. `work_session_close` triggers AI security analysis; `work_session_analyze(session_id, workspace, force=True)` re-runs it
3. `list_session_analyses(workspace)` and `get_session_analysis_detail(analysis_id, workspace)` for the findings, mapped to MITRE ATT&CK

---

## 💻 Running commands

### One server

```
execute_command(
    server_id="7e3984de-49ab-4cc6-bcdf-21fbd35858b8",
    command="df -h",
    workspace="production",
    timeout=300,
)
```

The call waits for the result—up to `timeout` seconds (default 300). `list_commands(workspace, server_id=...)` shows recent history with status and output.

### Many servers

```
execute_command_multi_server(
    server_ids=["<uuid-1>", "<uuid-2>", "<uuid-3>"],
    command="systemctl is-active nginx",
    workspace="production",
    parallel=True,
)
```

Set `parallel=False` to walk the list one host at a time—useful for a rolling change where you want to stop at the first failure.

### When a command is refused

A command outside the token's ACL comes back as an API error inside a successful HTTP response—`data.status_code` 403 or 404. That is a permission answer, not a bug: add the command to the token's ACL in the web console (`create_command_acl` does the same thing through the API), or ask an administrator to.

---

## 📁 Moving files

### Upload from your machine

```
webftp_upload_file(
    server_id="<uuid>",
    local_file_path="/Users/you/nginx.conf",
    remote_file_path="/etc/nginx/nginx.conf",
    workspace="production",
)
```

Both paths must be absolute. Transfers go through S3 presigned URLs: local file → S3 → server.

### Upload without a local file

From the hosted server, there is no local filesystem to read. Send the bytes instead:

```
webftp_upload_content(
    server_id="<uuid>",
    file_content="<base64>",
    remote_file_path="/etc/nginx/conf.d/rate-limit.conf",
    workspace="production",
)
```

### Download a file or a folder

```
webftp_download_file(
    server_id="<uuid>",
    remote_file_path="/var/log/nginx",
    local_file_path="/Users/you/Downloads/nginx-logs.zip",
    resource_type="folder",
    workspace="production",
)
```

A folder arrives as a ZIP. Large ones take time to stage in S3—raise `ALPACON_MCP_WEBFTP_DOWNLOAD_TIMEOUT` (default 60 seconds) and follow progress with `webftp_check_status(file_id, transfer_type="download", workspace=...)`.

### Several files at once

`webftp_bulk_upload(server_id, local_file_paths=[...], remote_directory="/etc/app/", workspace=...)` and `webftp_bulk_download(server_id, remote_paths=[...], local_file_path="/Users/you/bundle.zip", workspace=...)` do the whole set in one operation.

History lives in `webftp_uploads_list` and `webftp_downloads_list`; the audit view is `list_webftp_logs`.

---

## 🚨 Incident triage

> *"web-01 is slow. Find out why."*

A workable order—read first, act second:

1. `get_server_metrics_summary(server_id, workspace, hours=6)`: is this CPU, memory, disk, or network?
2. `get_disk_io` / `get_network_traffic` on the suspect dimension for the exact window
3. `list_events(workspace, server_id=...)` and `search_events(search_query="oom", workspace=...)`: did the platform already record something?
4. `list_alerts(workspace, server_id=..., acknowledged=False)`: what is already firing
5. Only now, if a live look is needed: open a Work Session scoped to `command` on that one server and run `top -b -n 1`, `iostat -x 1 5`, or `free -h`

The `incident_response` MCP prompt encodes exactly this discipline—read-only triage first, bounded remediation inside a scoped session second.

---

## 🔔 Alerts

> *"Warn us before the disk fills up."*

```
create_alert_rule(
    workspace="production",
    name="web-01 disk above 85%",
    metric_type="disk",
    condition="gt",
    threshold=85,
    servers=["<uuid>"],
    notification_channels=["email"],
    enabled=True,
)
```

`get_alert_rules(workspace)` lists what exists; `update_alert_rule` and `delete_alert_rule` change it. On the firing side: `list_alerts` (filter by `status`, `acknowledged`, `dismissed`), `get_alert` for one, `mute_alert(alert_id, workspace, duration=...)` to silence it for a while.

---

## 🔐 Access management

### Onboard a person

1. `create_iam_user(username, email, workspace, first_name=..., last_name=...)`
2. `list_iam_groups(workspace)` to find the group
3. `add_iam_member(group_id, user_id, workspace, role="member")`

There is no writable `groups` field on a user—membership is its own record, which is why step 3 is separate. `invite_workspace_user(email, workspace)` sends an email invitation instead of creating the account directly.

### A service account for CI

1. `create_iam_application(name="ci-deploy", workspace, service_type=...)`
2. `assign_application_system_users(app_id, system_user_ids=[...], workspace)` to bind the OS-level accounts it runs as

### Scope a token to exactly what it needs

1. `list_api_token_scopes(workspace)` and `list_api_token_presets(workspace)` to see what is available
2. `create_api_token(workspace, name="deploy-bot", scopes=[...], expires_at="2026-12-31T00:00:00Z")`
3. `create_command_acl(workspace, command="systemctl restart nginx", api_token_id=...)` and `create_server_acl(workspace, server_id=..., api_token_id=...)` to bound it further
4. `bulk_server_acl(workspace, action="add", server_ids=[...], api_token_id=...)` when the list is long

Token management needs JWT/OAuth, a browser session, or a login-source token. Called with an API token from `token.json`, these return 403—by the server's design, not a misconfiguration.

---

## 📝 Audit questions

| Question | Tool |
|---|---|
| Who changed what in this workspace? | `list_activity_logs`, then `get_activity_log` for one entry |
| What commands ran on this server? | `list_server_logs(workspace, server_id=...)` |
| What files moved? | `list_webftp_logs(workspace, server_id=...)` |
| What did the platform observe? | `list_events`, `search_events` |
| What did the AI analysis find? | `list_session_analyses`, `get_session_analysis_detail` |
| What happened inside one session? | `work_session_timeline` |

The `security_audit` prompt helps pick between these lenses when the question is vague.

---

## 📦 Keeping hosts current

> *"Which servers still run the vulnerable openssl, and can we patch them?"*

1. `list_system_packages(server_id, workspace, package_name="openssl")` per server—inventory, no command execution
2. `install_system_package(server_id, package_name="openssl", workspace)` to patch one package, or `upgrade_system(server_id, workspace)` for everything
3. `reboot_system(server_id, workspace)` when the update needs it

Python packages have the same trio: `list_python_packages`, `install_python_package`, `remove_python_package`.

---

## 🖥️ Bringing a new host in

1. `create_registration_token(workspace, name="batch-2026-08")`
2. `get_registration_guide(token_id, workspace, platform="debian", server_name="web-04")`—returns the install command to run on the host. Valid platforms: `debian`, `rhel`, `darwin`, `windows`
3. The host appears in `list_servers` once the agent registers
4. `update_server(server_id, workspace, name=..., description=...)` to label it, `star_server` to pin it for yourself
5. `delete_registration_token(token_id, workspace)` once the batch is done

`unregister_server(server_id, workspace)` reverses step 3: the workspace forgets the host, the agent stays installed, and coming back needs a fresh registration token.

---

## 🔗 Related documentation

- **[Getting Started](getting-started.md)**: Setup and first steps
- **[Installation Guide](installation.md)**: Platform-specific setup
- **[API Reference](api-reference.md)**: Every tool and its parameters
- **[Configuration Guide](configuration.md)**: Tokens, transports, environment variables
- **[Troubleshooting](troubleshooting.md)**: When something returns an error

---

## 📞 Support

- **GitHub Issues**: [Report bugs and request features](https://github.com/alpacax/alpacon-mcp/issues)
- **Discussions**: [Ask questions](https://github.com/alpacax/alpacon-mcp/discussions)
