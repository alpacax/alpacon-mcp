# API Reference

Complete reference for all Alpacon MCP Server tools and capabilities.

## 📋 Response Structure

All MCP tools follow a consistent response structure:

### Successful HTTP Request
```json
{
  "status": "success",
  "data": { /* API response data */ },
  "server_id": "server-uuid",
  "region": "ap1",
  "workspace": "production"
}
```

### HTTP Request with API Error
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

## 🔐 Authentication Tools

### `auth_set_token`
Set or update API tokens for specific region and workspace.

**Parameters:**
- `region` (string): Region name (currently supports 'ap1')
- `workspace` (string): Workspace name
- `token` (string): API token

**Example:**
```json
{
  "region": "ap1",
  "workspace": "company-main",
  "token": "your-api-token-here"
}
```

### `auth_remove_token`
Remove stored API token for a region and workspace.

**Parameters:**
- `region` (string): Region name
- `workspace` (string): Workspace name

---

## 🖥️ Server Management Tools

### `servers_list`
List all servers in a region and workspace.

**Parameters:**
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Array of server objects with ID, name, status, and metadata.

### `server_get`
Get detailed information about a specific server.

**Parameters:**
- `server_id` (string): Server ID to get details for
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Complete server information including hardware specs, status, and configuration.

### `server_notes_list`
List notes for a specific server.

**Parameters:**
- `server_id` (string): Server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `server_note_create`
Create a new note for a server.

**Parameters:**
- `server_id` (string): Server ID
- `title` (string): Note title
- `content` (string): Note content
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---

## 📊 Metrics and Monitoring Tools

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

### `get_cpu_top_servers`
Get top 5 servers by CPU usage in the last 24 hours.

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

## 💻 System Information Tools

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

## 🗂️ Event Management Tools

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

### `acknowledge_command`
Acknowledge that a command has been received and started.

**Parameters:**
- `command_id` (string): Command ID to acknowledge
- `success` (boolean, default: true): Whether command started successfully
- `result` (string, optional): Optional result message
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `finish_command`
Mark a command as finished with results.

**Parameters:**
- `command_id` (string): Command ID to mark as finished
- `success` (boolean, default: true): Whether command completed successfully
- `result` (string, optional): Optional result output or error message
- `elapsed_time` (float, optional): Optional execution time in seconds
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `get_command_status`
Get detailed status and execution information for a command.

**Parameters:**
- `command_id` (string): Command ID to get status for
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `delete_command`
Delete a scheduled command that hasn't been delivered yet.

**Parameters:**
- `command_id` (string): Command ID to delete
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---

## 🖥️ Websh and Command Execution Tools

> ⚠️ **ACL Configuration Required**: All command execution tools require pre-approved commands in your token's Access Control List (ACL). Configure permissions by clicking on your token in the Alpacon web interface → ACL settings.

### `websh_session_create`
Create a new Websh session for remote shell access.

**Parameters:**
- `server_id` (string): Server ID to create session for
- `username` (string, optional): Username for the session
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

**Returns:** Session ID and connection details.

### `websh_sessions_list`
Get list of active Websh sessions.

**Parameters:**
- `server_id` (string, optional): Filter by server ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `websh_command_execute`
Execute a command in a Websh session.

**Parameters:**
- `session_id` (string): Websh session ID
- `command` (string): Command to execute
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `websh_session_reconnect`
Create a new user channel for an existing Websh session.

**Parameters:**
- `session_id` (string): Session ID to reconnect
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `websh_session_terminate`
Terminate a Websh session.

**Parameters:**
- `session_id` (string): Session ID to terminate
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `websh_websocket_execute`
Execute commands in Websh session via WebSocket.

**Parameters:**
- `websocket_url` (string): WebSocket URL
- `command` (string): Command to execute
- `timeout` (integer, default: 10): Timeout in seconds

### `websh_channel_connect`
Connect to Websh user channel and maintain persistent connection.

**Parameters:**
- `channel_id` (string): User channel ID
- `websocket_url` (string): WebSocket URL from user channel creation
- `session_id` (string): Session ID for reference

**Returns:** Connection status and channel information.

### `websh_channel_execute`
Execute command using existing WebSocket connection from pool.

**Parameters:**
- `channel_id` (string): User channel ID
- `command` (string): Command to execute
- `timeout` (integer, default: 10): Timeout in seconds

**Returns:** Command execution result with output.

### `websh_channels_list`
List all active WebSocket connections in the pool.

**Returns:** List of active channels with connection status.

### `websh_channel_disconnect`
Disconnect and remove WebSocket connection from pool.

**Parameters:**
- `channel_id` (string): User channel ID to disconnect

**Returns:** Disconnection status.

---

## 📁 WebFTP Tools

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
Upload a file through WebFTP session.

**Parameters:**
- `session_id` (string): WebFTP session ID
- `file_path` (string): Target file path on server
- `file_data` (string): File content (base64 encoded for binary files)
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `webftp_downloads_list`
Get list of downloadable files from WebFTP session.

**Parameters:**
- `session_id` (string): WebFTP session ID
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---

## 🔐 Identity and Access Management (IAM)

> **Comprehensive IAM System** - Manage users, groups, roles, and permissions with workspace-level isolation and RBAC support.

### User Management

#### `iam_users_list`
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

#### `iam_user_get`
Get detailed information about a specific IAM user.

**Parameters:**
- `user_id` (string): IAM user ID
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**Returns:** Complete user profile including permissions and group memberships.

#### `iam_user_create`
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

#### `iam_user_update`
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

#### `iam_user_delete`
Delete IAM user from workspace.

**Parameters:**
- `user_id` (string): User ID to delete
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**⚠️ Warning:** This action is irreversible and will remove all user permissions and group memberships.

### Group Management

#### `iam_groups_list`
List all IAM groups in workspace with pagination support.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name
- `page` (number, optional): Page number
- `page_size` (number, optional): Groups per page

**Returns:** List of groups with member counts and permission summaries.

#### `iam_group_create`
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

### Role and Permission Management

#### `iam_roles_list`
List all IAM roles in workspace.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name
- `page` (number, optional): Page number
- `page_size` (number, optional): Roles per page

**Returns:** Available roles with descriptions and associated permissions.

#### `iam_permissions_list`
List all available permissions in workspace.

**Parameters:**
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name
- `page` (number, optional): Page number
- `page_size` (number, optional): Permissions per page

**Returns:** Complete permission catalog with descriptions and scopes.

#### `iam_user_assign_role`
Assign a role to a user.

**Parameters:**
- `user_id` (string): IAM user ID
- `role_id` (string): Role ID to assign
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**Example:**
```json
{
  "user_id": "user-123",
  "role_id": "admin-role",
  "workspace": "production"
}
```

#### `iam_user_permissions_get`
Get user's effective permissions (direct + inherited from groups).

**Parameters:**
- `user_id` (string): IAM user ID
- `workspace` (string): Workspace name
- `region` (string, default: "ap1"): Region name

**Returns:**
```json
{
  "status": "success",
  "data": {
    "direct_permissions": [
      {
        "id": "perm-read-servers",
        "name": "Read Servers",
        "description": "Can view server information"
      }
    ],
    "group_permissions": [
      {
        "group": "developers",
        "permissions": [
          {
            "id": "perm-deploy-staging",
            "name": "Deploy to Staging"
          }
        ]
      }
    ],
    "effective_permissions": ["perm-read-servers", "perm-deploy-staging"]
  }
}
```

### IAM Best Practices

**Security Guidelines:**
1. **Least Privilege**: Grant minimum required permissions
2. **Group-Based Management**: Use groups for permission inheritance
3. **Regular Audits**: Review user permissions periodically
4. **Workspace Isolation**: Separate environments with different workspaces

**Performance Tips:**
1. **Pagination**: Use page_size for large user/group lists
2. **Caching**: Cache permission lookups for better performance
3. **Bulk Operations**: Group multiple user operations when possible

---

## 🏢 Workspace and User Management

### `workspace_list`
Get list of available workspaces.

**Parameters:**
- `region` (string, default: "ap1"): Region name

### `user_settings_get`
Get user settings.

**Parameters:**
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `user_settings_update`
Update user settings.

**Parameters:**
- `settings` (object): Settings object to update
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

### `user_profile_get`
Get user profile information.

**Parameters:**
- `region` (string, default: "ap1"): Region name
- `workspace` (string): Workspace name

---


## 🔍 Resources

The server also provides authentication resources for checking status and configuration:

- **`auth://status`** - Check authentication status
- **`auth://config`** - Check configuration directory information
- **`auth://tokens/{env}/{workspace}`** - Query specific token

## ⚠️ Error Handling

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

## 📝 Response Format

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