# Changelog

All notable changes to the Alpacon MCP Server project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `acknowledge_alert`, `attach_alert_rule`, and `detach_alert_rule` tools.
- `list_alerts` gained the `alert_type`, `severity`, and `server_name` filters that
  `AlertFilter` defines.
- `list_webhooks` gained the `owner` and `provider` filters that
  `WebhookViewSet.filterset_fields` already exposed.
- `create_server_note` and `update_server_note` gained `private` and `pinned`, and
  `create_server_note` alone gained `mentioned_users`, which only the create serializer
  reads.
- `rotate_api_token`: regenerate an API token's secret in place through
  `POST /api/auth/tokens/{id}/rotate/` (#140). Unlike `duplicate_api_token`, which mints a second
  token and leaves the original live, rotation overwrites the secret on the same row, so the old
  one stops authenticating immediately with no grace period. The response carries the new secret;
  the token id, name, scopes and ACLs are unchanged. An expiry the token already had survives too,
  but a token with no expiry comes back carrying the workspace maximum, and a token already past
  its expiry is refused with `400 API_TOKEN_ALREADY_EXPIRED`. Paid plans only. The tool is annotated
  destructive rather than idempotent, so a client that auto-retries on idempotent hints will not
  silently invalidate a secret the first call already issued.
- `force` on the six disruptive server actions: `restart_agent`, `shutdown_agent`, `upgrade_agent`,
  `upgrade_system`, `reboot_system` and `shutdown_system` (#140). The server has refused these while
  a host is busy with an open Websh/WebFTP session or an in-flight command since alpacon-server
  #2553, and `force=true` is the only way through. It defaults to `false`, so an existing caller
  sends the same effective request as before; `update_information` is not disruptive and gains
  nothing.
- `request_sudo_policy`: ask for a sudo policy through `/api/sudo/policy-requests/`, which mints an
  approval request an admin has to approve before the policy exists (#140). The tool returns
  `status="pending_approval"` with category `SUDO_POLICY_REQUEST_PENDING`, so a client that already
  branches on the pending-approval shape needs no new handling. Omitting `users` scopes the
  approved policy to the requester alone rather than to the whole workspace, which is how the
  server narrows an approved request. `allow_bypass_mfa` is deliberately not a parameter: the
  server refuses it on this endpoint.
- `--toolsets` CLI argument (and `ALPACON_MCP_TOOLSETS` env var) for local
  stdio/SSE mode: selectively register toolsets; default remains `all`
  (#34). Remote mode is unaffected and always registers every tool.
- Workspace settings management tools under `/api/workspaces/`
  - Read tools: `get_workspace_access_control`, `get_workspace_security`, `list_workspace_mfa_methods`, `get_workspace_notifications`, `get_workspace_preferences`
  - Partial-update tools: `update_workspace_notifications`, `update_workspace_preferences`
  - Exposed the five read tools as `alpacon://workspace-settings/{access-control|security|mfa-methods|notifications|preferences}/{region}/{workspace}` resources
  - Security and access-control writes are intentionally omitted from the tool surface; on SaaS the server gates them behind a superuser session with fresh MFA (unsatisfiable by a static API token), and even where an on-premise admin token could write them, keeping governance-level settings human-only via the web console is the safer default
  - `get_workspace_security` and `list_workspace_mfa_methods` require JWT (OAuth/SSO) authentication and short-circuit a static API token before any request, and are SaaS-only (a clear not-available message on on-premise 404)
  - The list fields on the update tools (`notification_channels`, `enabled_extensions`, `allowed_domains`) replace the whole array rather than appending; documented the read-merge-write pattern
- `suse` (openSUSE / SLES) as a `platform` value on `get_registration_guide`, matching
  the platform choices the server offers for token-based installs (#182). The guide
  response keeps its existing shape—the zypper commands arrive in the same
  `install_commands` list every other platform uses.

### Changed
- BREAKING: `create_alert_rule` and `update_alert_rule` now take a `target` metric (one of
  a fixed set mirroring the server's `AlertRule.TARGET_METRICS`) and a `threshold`, instead
  of the invented `metric_type` and `condition`, which the serializer never read. A call
  still passing the old names now fails outright instead of being accepted and dropped.
- BREAKING: `create_webhook` now requires `owner`, a user UUID, because `WebhookSerializer`
  requires it. A call without it is a TypeError, and a username in its place is rejected
  before the request goes out.
- Values a closed server-side set defines are now checked in the tool rather than at the
  API: `target`, `action_type`, `provider`, the webhook `owner` UUID, and the 512-character
  cap on note `content`. Each returns a validation error naming the accepted values, in
  place of an opaque 400.
- The validation error an update tool returns when it receives no writable field now reports
  `field: "payload"` and names the accepted fields in the `suggestion` sentence, rather than
  packing the whole list into `field`. Affects `update_alert_rule`, `update_server`,
  `update_server_note`, and `update_webhook`.

### Removed
- BREAKING: the invented `title` on `create_server_note` and `update_server_note`. The note
  serializer has no such field, so the server discarded whatever was sent.
- BREAKING: `mentioned_users` on `update_server_note`. Only the `create` action routes to
  `NoteCreateSerializer`, so the update path never read it.
- BREAKING: the `status` filter on `list_alerts`, which `AlertFilter` does not define.
  `acknowledged` and `dismissed` are the filters that work.
- `mute_alert`. The server has no endpoint behind it, and no way at all to silence an alert
  for a while. `acknowledge_alert` is the closest thing and is not a substitute: it records
  one permanent acknowledgement per user per alert—`action_type='checked'` for seen,
  `'dismissed'` for not worth acting on—and that choice cannot be changed afterwards.
- The GET response cache, and the `cache_size` field it contributed to the health payload.
  It had never actually cached anything, since the whitelisted path prefixes were compared
  against whole URLs, and every read it covered—the server list, process info, IAM users
  and groups—comes back filtered by the calling token's permissions. Nothing in the process
  sees a grant revoked in the web console, in Slack, or by another MCP process, so a hit
  would have kept answering with access the caller had already lost. Reads now always go to
  the server, the only place that decision is current.
- The `remote_ip` parameter on `list_api_tokens`. The server narrowed the viewset's filters to
  `name` and `enabled` because `remote_ip` and `user_agent` are only ever populated for
  `source='login'` tokens, and this endpoint lists `source='api'` ones (#140). django-filter
  discarded the parameter silently, so a caller passing it got an unnarrowed result set that looked
  filtered. The `search` and `ordering` documentation now matches the server as well: search covers
  `name` alone, and the orderable fields are `added_at`, `updated_at` and `last_used_at`.
- `create_sudo_policy`. It posted five fields (`name`, `groups`, `run_as`, `no_password`,
  `description`) that no longer exist on the server's serializer, to a path that had been 404 for
  four months. Its replacement is `request_sudo_policy`, which routes through human approval instead
  of writing a live policy; the direct-write endpoint `/api/sudo/policies/` demands owner or manager
  rights on every target server and stays off the MCP tool surface on purpose (#140).
- `get_workspace_notifications` and `update_workspace_notifications`, along with the
  `alpacon://workspace-settings/notifications/{region}/{workspace}` resource. The upstream
  `/api/workspaces/notifications/-/` endpoint no longer exists—the `NotificationSettings`
  model, serializer, viewset and route were deleted server-side (alpacax/alpacon-server#2832)
  because the two fields had no runtime consumer, so both tools returned 404. Server
  disconnection still raises an alert in the notification bell; that path is unaffected,
  as is the unrelated metrics `AlertRule` behind the alert rule tools, whose own payload
  correction is the first entry under Changed.

### Fixed
- `unregister_server` now sends the `auto` and `purge_provisioned_accounts` query parameters the
  server's delete endpoint reads (#140). Both default to `false`, matching the server, so an
  existing caller sends the same effective request as before and a still-connected host is still
  refused with `400 SERVER_CANNOT_BE_DELETED`. Pass `auto=true` to tear the agent off a host that
  is still running. A client parsing the response sees no new fields.
- `list_sudo_policies` now calls `/api/sudo/policies/`. The server moved sudo policies out of the
  `approvals` app and renamed the URL prefix, so the old `/api/approvals/sudo-policies/` path had
  been returning 404 unconditionally (#140). The tool also accepts the `user` and `server_id` UUID
  filters the server's `SudoPolicyFilter` exposes, which its description already claimed;
  `server_id` carries the repo's usual name so a server name is rejected by the input validator
  rather than by the API. The response shape is unchanged.
- Arguments whose name ends in `_id` are now validated before any request is built: the value must
  be a string matching `[A-Za-z0-9._~-]+` and must not be `.` or `..` (#204). Most of them are
  interpolated into an endpoint path, where `urljoin` resolves `..` as a path climb and carries
  percent-encoded climbs such as `%2e%2e%2f` to the wire still encoded. The rest only reach a query
  parameter or a request body, and are held to the same rule because it picks arguments by the name
  rather than by where the value ends up. A client sending anything else—a separator, a `?` or `#`,
  a trailing newline, or a value that is not a string at all, such as a list—receives the usual
  validation error envelope naming the field instead of a response from another resource.
  `server_id` and `session_id` keep their stricter UUID check, and `work_session_id` is exempt,
  keeping its documented whitespace tolerance.
- Dropped the root `__init__.py` that 0.4.1 added, together with its wheel include. It made the
  checkout directory a package, so under pytest `sys.modules['main']` was pre-registered with that
  package and `import main` no longer reached `main.py` in a clone directory named `main` (#189).
  The console scripts and the Dockerfile load `main.py` as a top-level module and are unaffected.
- `eu1` is no longer accepted as a `region`. Only `ap1` and `us1` are served, so `eu1` now fails
  validation before any HTTP call instead of dying at DNS on `{workspace}.eu1.alpacon.io`, and every
  docstring that advertised it as a choice now lists only `ap1` and `us1` (#165). A client that
  sends `eu1` gets an error response with `field: "region"` rather than a connection error; nothing
  else about the response shape changed. A workspace that pinned its host explicitly—the `token.json`
  object form or `ALPACON_MCP_<REGION>_<WORKSPACE>_URL`—loses access too, even though that host never
  resolved `*.eu1.alpacon.io`: the region check runs before the override is read. Re-register such an
  entry under `ap1` or `us1` and keep its `url` as it is.
- The setup wizard checks the region it prompts for instead of writing whatever is typed into
  `token.json`. A typo such as `eu1` or `ap` is now reported at the prompt rather than surfacing as a
  validation error on the first tool call (#165).

### Documentation
- Documented the hosted remote MCP server (`https://mcp.alpacon.io/mcp`, streamable-http transport)
  - Added a "Remote MCP server (hosted, no install)" section to `README.md` with per-client setup for Claude Code, Claude Desktop, Cursor, and VS Code
  - Explained browser-based OAuth authentication (no API token, no `token.json`) and prompt-driven workspace selection
  - Added a streamable-http transport mode entry to `docs/configuration.md`

## [0.4.3] - 2025-10-24

### Improved
- **Session Management**: Optimized Websh session creation by removing unnecessary 0.5s sleep
  - Session reuse logic now properly identifies MCP sessions via user_agent filtering
  - Faster session creation without compromising user_agent recording
- **Version Management**: Implemented dynamic version reading from `pyproject.toml`
  - Removed hardcoded version in `utils/common.py`
  - Version now automatically synchronized via `importlib.metadata`
  - Development fallback version for non-installed environments

### Technical details
- `websh_session_create`: Removed `asyncio.sleep(0.5)` after WebSocket connection
- `get_or_create_channel`: Already properly filters sessions by user_agent='alpacon-mcp'
- `MCP_VERSION`: Now reads from package metadata instead of hardcoded value

## [0.4.2] - 2025-10-24

### Fixed
- Removed missing `security_audit_tools` import that was causing import errors
- Cleaned up unused imports and references to non-existent modules

## [0.4.1] - 2025-10-24

### Fixed
- Added `__init__.py` to make alpacon-mcp a proper Python package
- Fixed package structure for proper installation and distribution

## [0.4.0] - 2025-10-24

### Added
- **Interactive Setup Wizard**: Simplified installation with guided configuration
  - Region selection with defaults
  - Workspace and API token input with validation
  - Automatic token file creation
  - Connection testing and verification
  - Claude Desktop configuration guidance

### Improved
- **MCP Tools Consolidation**: Cleaned up and reorganized MCP tool structure
  - Removed redundant tool definitions
  - Improved tool naming consistency
  - Better organization of tool modules

### Changed
- Streamlined installation process with `uvx alpacon-mcp setup` command
- Enhanced user experience with interactive prompts and validation

## [0.3.1] - 2025-10-01

### Documentation
- Updated CLAUDE.md with new `@mcp_tool_handler` decorator pattern examples
- Updated CONTRIBUTING.md with unified tool creation guide
- Added comprehensive CHANGELOG for v0.3.0 changes
- Fixed documentation examples to reflect current implementation

## [0.3.0] - 2025-10-01

### Changed
- **BREAKING**: Refactored all MCP tools to use unified `@mcp_tool_handler` decorator pattern
- Removed manual token management from tool implementations
- Replaced manual error handling with automatic decorator-based handling
- Updated all tools to use `success_response()` and `error_response()` helpers
- Standardized token injection via `**kwargs` pattern across all tools

### Improved
- Reduced code duplication by ~60% per tool function
- Centralized error handling and logging in decorator
- Consistent response formatting across all MCP tools
- Better maintainability and testability of tool implementations

### Fixed
- Enhanced error handling in `execute_command` for ACL permission errors
- Improved metric tools with human-readable formatting (GB/MB, Mbps/Kbps)
- Added statistical summaries for metric data (current, average, min, max)
- Fixed `get_server_metrics_summary` to return summary only (reduced from 75K to 2K tokens)

### Removed
- Removed non-existent IAM role and permission management endpoints
  - `list_iam_roles`
  - `assign_iam_user_role`
  - `list_iam_permissions`
  - `get_iam_user_permissions`
- Removed `websh_command_execute` (HTTP POST endpoint does not exist on server)

### Documentation
- Updated CLAUDE.md with new decorator pattern examples
- Updated CONTRIBUTING.md with unified tool creation guide
- Added decorator benefits and technical details to documentation

### Technical details
- All 22+ tool functions refactored across 8 tool modules:
  - command_tools.py
  - events_tools.py
  - iam_tools.py
  - metrics_tools.py
  - system_info_tools.py
  - webftp_tools.py
  - server_tools.py
  - workspace_tools.py

## [0.1.0] - 2024-09-25

### Added
- Initial release of Alpacon MCP Server
- Authentication tools for login/logout functionality
- Server management tools (list, get details, notes)
- Websh tools for secure shell session management
- WebFTP tools for file transfer operations
- System information tools for hardware and OS details
- Metrics tools for performance monitoring (CPU, memory, disk, network)
- Events tools for system event management
- Workspace management tools
- Comprehensive documentation structure
- Support for both stdio and SSE transport modes
- Multi-region and multi-workspace support
- Token management with environment variable configuration
- Command-line interface with entry points

### Features
- **Server Management**: List and monitor servers across regions
- **Real-Time Monitoring**: CPU, memory, disk, and network metrics
- **System Administration**: User management, package inventory, system information
- **Remote Operations**: Websh sessions and file transfers
- **Event Management**: Command tracking and execution history
- **Authentication**: Secure token-based authentication with multi-workspace support

### Documentation
- Complete installation guide with platform-specific instructions
- Configuration guide for authentication and MCP client setup
- API reference with detailed tool documentation
- Usage examples for common scenarios
- Troubleshooting guide for common issues
- Getting started guide for quick setup

### Technical
- Built on FastMCP framework
- Supports Python 3.12+
- MCP protocol compatible with Claude Desktop, Cursor, VS Code
- Environment variable-based configuration
- Comprehensive error handling and logging

## [0.2.0] - 2024-09-26

### Added
- **Comprehensive IAM Management System**: Complete identity and access management tools
  - User management (list, get, create, update, delete)
  - Group management with permission inheritance
  - Role-based access control (RBAC) system
  - Permission management and user effective permissions
  - Workspace-level isolation for multi-tenant environments
- **Comprehensive Test Suite**: 246+ test cases covering all MCP tools and scenarios
  - Unit tests for all tools and utilities
  - Integration tests for API workflows
  - Error handling and edge case validation
  - Mock server testing infrastructure
- **Enhanced Logging System**: Comprehensive logging and monitoring capabilities
  - Structured logging with configurable levels
  - Request/response tracking for debugging
  - Performance metrics and monitoring
  - Error tracking and reporting

### Fixed
- Corrected environment variable names and paths in README for better clarity
- Fixed Cursor IDE MCP configuration file name to use correct `mcp.json` format
- Updated URL patterns and documentation to reflect current architecture

### Documentation
- Improved token configuration guide with clearer examples and file paths
- Enhanced documentation structure with current architecture patterns
- Added comprehensive testing documentation
- Updated language guidelines for better consistency
- Improved API reference with detailed examples

### Technical
- Enhanced error handling across all tools
- Improved code organization and maintainability
- Added comprehensive type checking and validation
- Enhanced security practices and token management

## [0.1.1] - 2024-09-25

### Fixed
- Updated MCP client configuration to use config file instead of direct token exposure for improved security
- Enhanced token management documentation for better security practices

### Documentation
- Added comprehensive uvx support across all documentation
- Improved token configuration examples with security best practices
- Enhanced installation instructions with uvx integration

## [Unreleased]

### Planned
- Enhanced metrics visualization
- Additional monitoring capabilities
- Performance optimizations
- Extended API coverage
- More authentication methods