# API reference

Complete reference for all Alpacon MCP Server tools and capabilities.

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
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Array of server objects with ID, name, status, and metadata.

### `get_server`
Get detailed information about a specific server.

**Parameters:**
- `server_id` (string): Server ID to get details for
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Complete server information including hardware specs, status, and configuration.

### `list_server_notes`
List notes for a specific server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `create_server_note`
Create a new note for a server.

**Parameters:**
- `server_id` (string): Server ID
- `title` (string): Note title
- `content` (string): Note content
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---

## 📊 Metrics and monitoring tools

### `get_cpu_usage`
Get CPU usage metrics for a server.

**Parameters:**
- `server_id` (string): Server ID to get metrics for
- `start_date` (string, optional): Start date in ISO format
- `end_date` (string, optional): End date in ISO format
- `region` (string, default: "ap1"): Region name
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
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_network_traffic`
Get network traffic metrics for a server.

**Parameters:**
- `server_id` (string): Server ID
- `interface` (string, optional): Network interface (e.g., 'eth0')
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_disk_io`
Get disk I/O performance metrics for a server.

**Parameters:**
- `server_id` (string): Server ID
- `start_date` (string, optional): Start date in ISO format
- `end_date` (string, optional): End date in ISO format
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_top_servers`
Get top servers by metric type(s).

**Parameters:**
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_alert_rules`
Get alert rules for servers.

**Parameters:**
- `server_id` (string, optional): Server ID to filter rules
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_server_metrics_summary`
Get comprehensive metrics summary for a server.

**Parameters:**
- `server_id` (string): Server ID
- `hours` (integer, default: 24): Number of hours back to get metrics
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---

## 💻 System information tools

### `get_system_info`
Get detailed system information for a server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Hardware specs, CPU details, memory info, and system identifiers.

### `get_os_version`
Get operating system version information.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `list_system_users`
List system users on a server.

**Parameters:**
- `server_id` (string): Server ID
- `username_filter` (string, optional): Username to search for
- `login_enabled_only` (boolean, default: false): Only return users that can login
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `list_system_groups`
List system groups on a server.

**Parameters:**
- `server_id` (string): Server ID
- `groupname_filter` (string, optional): Group name to search for
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `list_system_packages`
List installed system packages on a server.

**Parameters:**
- `server_id` (string): Server ID
- `package_name` (string, optional): Package name to search for
- `architecture` (string, optional): Architecture filter (e.g., 'x86_64')
- `limit` (integer, default: 100): Maximum number of packages to return
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_network_interfaces`
Get network interfaces information for a server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_disk_info`
Get disk and partition information for a server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Both disk and partition information in a single response.

### `get_system_time`
Get system time and uptime information.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_server_overview`
Get comprehensive overview of server system information.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
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
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_event`
Get detailed information about a specific event.

**Parameters:**
- `event_id` (string): Event ID to get details for
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `search_events`
Search events by criteria.

**Parameters:**
- `search_query` (string): Search term to look for in events
- `server_id` (string, optional): Server ID to limit search scope
- `limit` (integer, default: 20): Maximum number of results to return
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---

## 💻 Command API tools (requires ACL permission)

> ⚠️ **ACL configuration required**: Command API tools require pre-approved commands in your token's Access Control List (ACL). Configure permissions by clicking on your token in the Alpacon web interface → ACL settings.

### `execute_command`
Execute a command on a server and wait for the result.

**Parameters:**
- `server_id` (string): Server ID
- `command` (string): Command to execute
- `workspace` (string): Workspace name
- `shell` (string, default: "system"): Shell type
- `username` (string, optional): Username for execution
- `groupname` (string, default: "alpacon"): Group name
- `env` (object, optional): Environment variables
- `run_after` (array, optional): Command IDs to wait for before executing
- `scheduled_at` (string, optional): ISO 8601 datetime for scheduled execution
- `data` (string, optional): Stdin data
- `timeout` (integer, default: 300): Timeout in seconds
- `region` (string, default: "ap1"): Region name

### `list_commands`
List recent command history.

**Parameters:**
- `server_id` (string, optional): Filter by server ID
- `limit` (integer, default: 20): Maximum number of recent commands to return
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

### `execute_command_multi_server`
Execute a command on multiple servers simultaneously.

**Parameters:**
- `server_ids` (array): List of server IDs
- `command` (string): Command to execute
- `workspace` (string): Workspace name
- `shell` (string, default: "internal"): Shell type
- `username` (string, optional): Username for execution
- `groupname` (string, default: "alpacon"): Group name
- `env` (object, optional): Environment variables
- `parallel` (boolean, default: true): Execute in parallel
- `region` (string, default: "ap1"): Region name

---

## 📁 WebFTP tools

### `webftp_session_create`
Create a new WebFTP session for file transfer.

**Parameters:**
- `server_id` (string): Server ID
- `username` (string): Username for FTP access
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `webftp_sessions_list`
Get list of WebFTP sessions.

**Parameters:**
- `server_id` (string, optional): Filter by server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `webftp_upload_file`
Upload a local file to a server using S3 presigned URLs.

**Parameters:**
- `server_id` (string): Server ID
- `local_file_path` (string): Absolute path to local file
- `remote_file_path` (string): Absolute path on server
- `workspace` (string): Workspace name
- `username` (string, optional): Username (defaults to authenticated user)
- `region` (string, default: "ap1"): Region name
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
- `region` (string, default: "ap1"): Region name

### `webftp_uploads_list`
List uploaded files (upload history).

**Parameters:**
- `workspace` (string): Workspace name
- `server_id` (string, optional): Filter by server ID
- `region` (string, default: "ap1"): Region name

### `webftp_downloads_list`
List download requests (download history).

**Parameters:**
- `workspace` (string): Workspace name
- `server_id` (string, optional): Filter by server ID
- `region` (string, default: "ap1"): Region name

---

## 🔐 Identity and access management (IAM)

> Manage users and groups with workspace-level isolation.

### User management

#### `list_iam_users`
List all IAM users in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name
- `page` (number, optional): Page number for pagination
- `page_size` (number, optional): Users per page

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
- `region` (string, default: "ap1"): Region name

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
- `groups` (array, optional): List of group IDs to assign
- `region` (string, default: "ap1"): Region name

**Example:**
```json
{
  "username": "john.doe",
  "email": "john@company.com",
  "first_name": "John",
  "last_name": "Doe",
  "workspace": "production",
  "groups": ["developers", "team-leads"]
}
```

#### `update_iam_user`
Update existing user information and group memberships.

**Parameters:**
- `user_id` (string): User ID to update
- `workspace` (string): Workspace name
- `email` (string, optional): New email address
- `first_name` (string, optional): New first name
- `last_name` (string, optional): New last name
- `is_active` (boolean, optional): New active status
- `groups` (array, optional): New list of group IDs
- `region` (string, default: "ap1"): Region name

**Note:** Only provided fields will be updated. Omitted fields remain unchanged.

#### `delete_iam_user`
Delete IAM user from workspace.

**Parameters:**
- `user_id` (string): User ID to delete
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**⚠️ Warning:** This action is irreversible and will remove all user permissions and group memberships.

### Group management

#### `list_iam_groups`
List all IAM groups in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name
- `page` (number, optional): Page number
- `page_size` (number, optional): Groups per page

**Returns:** List of groups with member counts and permission summaries.

#### `create_iam_group`
Create new IAM group with permission assignments.

**Parameters:**
- `name` (string): Group name
- `workspace` (string): Workspace name
- `description` (string, optional): Group description
- `permissions` (array, optional): List of permission IDs
- `region` (string, default: "ap1"): Region name

**Example:**
```json
{
  "name": "senior-developers",
  "workspace": "production",
  "description": "Senior development team with elevated permissions",
  "permissions": ["deploy-staging", "read-prod-logs", "manage-users"]
}
```

---

## 🏢 Workspace management

### `list_workspaces`
Get list of available workspaces.

**Parameters:**
- `region` (string, default: "ap1"): Region name

### `get_workspace_access_control`
Get the workspace access control settings: sudo/root access policy (`allow_sudo_with_mfa`, `allow_direct_root`, `block_local_sudo`, `sudo_timeout`), tunnel/editor defaults, `home_directory_permission`, Work Session TTLs (`work_session_max_ttl`, `work_session_pending_ttl`), command-env audit exposure, and `shared_account_names`.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**Note:** On-premise deployments omit the MFA-related fields (`allow_sudo_with_mfa`, `block_local_sudo`, `sudo_timeout`).

### `get_workspace_security`
Get the workspace authentication/security settings: `mfa_required`, `allowed_mfa_methods`, `mfa_timeout`, and which actions require MFA.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**Note:** Requires JWT (OAuth/SSO) authentication. The upstream `SecuritySettingsViewSet` has no `APITokenAuthentication`, so a static API token (stdio mode) is rejected before any request is sent; use remote/streamable-http (browser SSO) mode to read these settings.

**Note:** This route is also SaaS-only. On-premise deployments return 404 from the upstream API; this tool reports that the settings are not available on this deployment instead of a generic error.

### `list_workspace_mfa_methods`
List the MFA methods allowed for the workspace (`allowed_mfa_methods`, `passkey_as_mfa`). Useful when guiding a user through the remote/streamable-http MFA re-authentication flow.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**Note:** Like `get_workspace_security`, this requires JWT (OAuth/SSO) authentication (a static API token is rejected up front) and the route is SaaS-only.

### `get_workspace_notifications`
Get the workspace notification settings: `disconnection_notification` and `notification_channels`.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

### `get_workspace_preferences`
Get the workspace-wide preferences: timezone, locale, `front_url`, `invite_ttl`, `enabled_extensions`, `websh_session_timeout`, `auto_agent_upgrade`, `package_proxy`, `billing_email`, `allowed_domains`. Workspace-global configuration, not per-user.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

### `update_workspace_notifications`
Update workspace notification settings. Only the fields you provide are sent (partial update).

**Parameters:**
- `workspace` (string): Workspace name
- `disconnection_notification` (boolean, optional): Notify when a server disconnects/goes offline
- `notification_channels` (array, optional): Channel types to notify through (`email`, `webhook`, `push`). Replaces the whole list (not additive); read via `get_workspace_notifications` and merge before sending
- `region` (string, default: "ap1"): Region name

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
- `region` (string, default: "ap1"): Region name

**⚠️ Warning:** `timezone` is the workspace's billing clock—changing it shifts the daily usage-aggregation boundary. The list fields (`enabled_extensions`, `allowed_domains`) replace the whole list rather than appending—read the current value, merge, then send. `billing_email` and `allowed_domains` are only accepted by the server on SaaS deployments.

---


## 🔍 Resources

The server also provides authentication resources for checking status and configuration:

- **`auth://status`**: Check authentication status
- **`auth://config`**: Check configuration directory information
- **`auth://tokens/{env}/{workspace}`**: Query specific token

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