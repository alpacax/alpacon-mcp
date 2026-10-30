# Changelog

All notable changes to the Alpacon MCP Server project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- An `alpacon` agent plugin in `plugins/alpacon/`, installed with `/plugin marketplace add alpacax/alpacon-mcp` and `/plugin install alpacon@alpacon-mcp` (#222). It connects to the hosted server `https://mcp.alpacon.io/mcp`, adds a `using-alpacon` skill carrying the server UUID, Work Session, approval, and `outcome_unknown` rules, and a Bash hook that refuses the `alpacon` CLI. The tool surface and every response are unchanged; the same directory also installs in Codex, Copilot CLI, and Cursor.
- The command pre-approval ledger tools can be served in remote mode (streamable-http) when the operator sets
  `ALPACON_MCP_REMOTE_LEDGER=true` (#362). A ledger call without a usable ledger token asks the MCP client to sign
  in again through a 403 `insufficient_scope` challenge naming `ledger:<workspace>`; the OAuth proxy then obtains a
  ledger token for that person and carries it, encrypted, in the access token it hands that one client. The
  returned access token can therefore be an opaque `amcpl1.` value rather than an Auth0 JWT, and when the client
  cannot step up the tool returns `authorization_required` without a `verification_uri`. SSE still never serves
  these tools.
- A coded refusal's `gate`, `missing`, `next` and `hint` now ride the error result as sent, and a server `hint` replaces the local hints, `recovery_hints` included; without one, a known `gate` or `missing` class picks a local hint that says whom to ask (#242). A rejected command on `execute_command`, `execute_file` and `list_commands` carries `rejection_cause`, `rejection_gate` and a new `rejection_hint`, and a rejected `command` item on `work_session_timeline` carries `rejection_hint`. A client parsing `message` sees two changes: a rejected command's message ends with its hint, an older server's rejected command included, and a refusal whose `gate` or `missing` this client recognizes no longer carries `recovery_hints` or `related_tools`. An older server's other errors are unchanged, and a current server's feature-lock 402 now also carries the `gate: "plan"` it sends.
- `list_latest_metrics` accepts `metric_severity` and `-metric_severity` ordering and preserves
  row `metric_severity`, cell `threshold` and `operator`, and envelope `summary` fields (#397).
  Clients parsing responses see these new keys, including permission-dependent nulls; no
  existing fields are removed. Severity ordering and these fields require a server deployment
  that supports them; earlier deployments ignore that ordering (the default order applies) and omit the fields, as does a caller without `alert:read` for the ordering.
- Command pre-approval ledger tools (#362): `get_ledger_capability`, `list_ledger_entries`,
  `issue_ledger_entries`, `revoke_ledger_entry`, `revoke_ledger_entries`, `disable_ledger_entry`,
  `enable_ledger_entry`, `list_ledger_admins`, `grant_ledger_admin` and `revoke_ledger_admin`, in a new
  `ledger` toolset. They manage Pre-approved commands and Command ACL admins on a workspace whose
  `command_acl_surface` is `ai`. They are served over stdio, and in remote mode as the entry above
  describes; SSE does not register them, and a call that reaches one where they are not served is refused before any
  sign-in is read. Over stdio the first call returns a new `status` value, `authorization_required`, carrying a
  sign-in link a person must open before the call is retried, so a client branching on `status` has to handle it. `issue_ledger_entries` takes
  `service_token` entries only: a personal API token has no command list on the ledger, and
  `api_token` stays a `list_ledger_entries` filter so entries such a token already has can still be
  listed and revoked.

### Fixed
- On a deployment with `ALPACON_MCP_ENV` set to `staging` or `dev`, every tool's `region` parameter also accepts `dev`, the region `list_workspaces` reports there (#434). Since #404 the SDK refused `region: "dev"`, so a client that passed back the region it had just been given failed with `Input should be 'ap1' or 'us1'`. Production publishes `ap1` and `us1` only, as before; a client has nothing new to handle.
- The `enabled_extensions` description on `update_workspace_preferences` no longer claims that narrowing the list fails with HTTP 402, and now states which additions Alpacon server 2.44.0 and later refuse, including the `ip` that `dns` and `proxy` require (#350). The two 400s it names, `workspace_extension_requires_extension` and `extension_not_available`, now append a hint to `message` saying what to change, and `get_workspace_preferences` documents the `extensions` field (`id`, `available`, `allowed`). Responses are unchanged, so a client needs no new handling.
- `acknowledge_alert` now answers a repeat acknowledgement by the same user with `status: "success"` and `already_acknowledged: true` instead of an error, when alpacon-server (2.35.0 or later) refuses it with `alert_already_acknowledged` (#191). That call records nothing and its response omits the existing `action_type`, so a client branching on `status` should read `already_acknowledged` and call `get_alert` for the recorded `action_type`; every other `400` is still an error, and the tool's `idempotentHint` is now `true`.
- `get_disk_io` and its `alpacon://metrics/{region}/{workspace}/{server_id}/disk-io` resource no longer fail with HTTP 400 `api_insufficient_data` when no `device` is given: they read the alphabetically first device with data in the last day, or return an error when there is none (#413). The response gains `devices`, the sorted device list when `device` was omitted or blank and null otherwise, so a client on a multi-disk server should read it and call again per device. `get_disk_usage` now picks its discovered device the same way, where it used to take whichever the server listed first.
- Every `alpacon://` resource now publishes its tool's description, the text `tools/list` shows, instead of the tool function's docstring, so every resource description changes (#407). The descriptions of `get_server`, `get_collection_profile`, `get_top_servers`, `get_server_metrics_summary`, `list_latest_metrics`, `get_alert_rule_recipients`, `list_rule_overrides`, `list_alerts`, `get_alert` and `list_workspaces` gain the response-reading notes their docstrings alone carried. The field is free text, so a client has nothing new to parse.
- `webftp_download_file` now waits for the host to transfer the file before answering, in both modes (#393). Both modes now wait up to `ALPACON_MCP_WEBFTP_DOWNLOAD_TIMEOUT` and can return `download_failed` or `download_timeout` where they used to return success, so a client has to handle both; a create response with no download URL, which used to be polled in remote mode and reported as a created request in local mode, now fails at once with `download_failed`. Remote mode no longer hands out a URL before the file is behind it, except on `download_timeout`, which carries `download_url` for use once `webftp_check_status` reports the download completed; local mode no longer replaces an existing file at `local_file_path` unless the transfer is confirmed, and `execute_file` with `read_from_server` no longer reports `file_read_timeout` for a read that finished in time. A scoped token without `command:read`, such as one from the `file_download` or `file_transfer` preset, is no longer refused: both tools then wait on the transfer status alone and fetch the file only once it reports success.
- A `POST` or `PATCH` is no longer resent after its request may have reached the server: a read or write timeout, a broken connection, a 5xx, or an unexpected error such as a 2xx whose body cannot be read now returns at once, and only a request that never reached the server is retried—no connection opened or came free from the pool, the proxy refused the tunnel, the URL scheme cannot be sent, or the server answered 503 `auth_verification_unavailable`, which it sends before any view runs (#392). A timed-out `execute_command`, `execute_file`, or `execute_command_multi_server` submission used to post the command again, so the host could run it twice. Every POST or PATCH tool error that may have acted now carries `outcome_unknown: true` and no `recovery_hints`, and a command error also tells the caller to check `list_commands` before resubmitting; a client that retried any write on error has to check first.
- In remote mode, the MFA pre-check now reads a workspace whose `mfa_timeout` is null as the server does, as 3600 seconds. It used to fail the comparison and treat every completed MFA as stale, so a call needing MFA kept asking for re-authentication. Responses are unchanged.
- When Auth0 returns an error to `/oauth/callback` without an `error_description` and no client `redirect_uri` is known, the JSON error now carries `error_description: ""` instead of `null`. RFC 6749 allows the field to be absent or a string, never null; a client that read the field as nullable needs no change (#372).
- `create_command_acl`, `update_command_acl` and `delete_command_acl` now explain the 405
  `command_acl_moved` that a server managing command pre-approvals on the command pre-approval
  ledger answers on every command-ACL write: the error says a Command ACL admin must issue or revoke
  the entry under Pre-approved commands on the service token's page in the web console, that a
  personal API token has no command list on the ledger, and that the call should not be retried, instead of a bare 405. The
  three tool descriptions, `docs/api-reference.md` and `docs/examples.md` say the same; a server
  without the ledger still accepts these writes.

### Removed
- BREAKING: `update_workspace_preferences` no longer accepts `allowed_domains`, which the server already ignored (#377). The SDK drops this argument before the request: a call that sends only it returns `No update data provided`, while other fields in the same call are still sent. The response shape is unchanged.
- BREAKING: `update_workspace_preferences` no longer accepts the deprecated `auto_agent_upgrade` boolean; use the existing `agent_rollout_policy` object instead (`{"mode": "manual"}` replaces the old `false`) (#376). Responses no longer include the alias-specific `deprecation_note`; the preferences response shape is otherwise unchanged. The SDK drops the alias before the request: a call that sends only it returns `No update data provided`, while other fields in the same call are still sent.

### Changed
- Every remaining rule that binds one argument now sits on that argument's schema description instead of the tool description (#175): the shared `workspace`, `servers`, `server_ids` and `session_id` arguments carry one description each, and every other argument that had such a rule (for example `expires_at`, `cursor`, `force`, `purpose` and the `update_workspace_preferences` fields) carries the sentences that used to open or close its tool's description. Tool descriptions keep the behavior, cost and routing guidance. Arguments and responses are unchanged, so a client has nothing new to handle.
- Every `server_id`, `region` and `work_session_id` argument now carries its rule as a parameter description (#175): `server_id` is a UUID, never a server name; `region` names what an omitted value resolves to; `work_session_id` states the audit link, which callers the server requires it from, and the `ALPACON_WORK_SESSION` fallback. The `work_session_id` sentences are removed from the descriptions of `execute_command`, `execute_command_multi_server`, `execute_file`, `webftp_session_create`, `webftp_upload_file`, `webftp_download_file`, `webftp_bulk_upload` and `webftp_bulk_download`. Arguments and responses are unchanged, so a client has nothing new to handle.
- The rules that bind one argument now sit on that argument's schema description instead of the tool description (#175): `description` and `scopes` on `work_session_create` and `work_session_update`, and `command` on `execute_command` and `execute_command_multi_server`. The four tool descriptions drop those sentences and keep the cost and routing guidance; the parameter descriptions also add rules the tool descriptions never stated: `command` must not be empty or whitespace-only, `sudo` scope is requested only when the work requires root, `work_session_update`'s `description` asks for the same specific statement as create's, and its `scopes` replaces the whole scope list. Arguments and responses are unchanged, so a client has nothing new to handle.
- Sudo tool descriptions, denial hints, and next actions now describe the policy as session-authorized sudo and name the `session_authorized` field a human sets on the Work Session's sudo policy in the Alpacon web console. `request_sudo_policy` still cannot carry that field; tool names, parameters, error codes, and response shapes are unchanged, so clients parsing responses have nothing new to handle.
- Auth0 settings now use `AUTH0_ALPACON_DOMAIN`, `AUTH0_ALPACON_LOGIN_CLIENT_ID`, `AUTH0_ALPACON_LOGIN_CLIENT_SECRET`, `AUTH0_ALPACON_USER_AUDIENCE`, `AUTH0_ALPACON_MFA_AUDIENCE`, and `AUTH0_ALPACON_NAMESPACE`, with the legacy names accepted as fallbacks and a deprecation warning once per process per variable. The legacy names will be removed in a later release; defaults, seal-key derivation, and response shapes are unchanged, so clients parsing responses have nothing new to handle.
- The `command_acl_moved` hint, the command ACL tool descriptions and the 403 command recovery hint
  keep pointing to the web console and, on a stdio server only, also name the ledger tools.
- Remote mode reads the JWT and the workspace security settings more strictly, only for values the Alpacon API server and Auth0 do not send. A token whose `sub` or `scope` is not a string, or whose `exp` is not an integer, is refused, where a string `exp` used to be accepted. A malformed security setting takes its strictest reading: an `mfa_required_actions` that is not a list of strings requires MFA for every action, an `allowed_mfa_methods` that is not a list of strings lets no method satisfy MFA, and a non-numeric or boolean `mfa_timeout` counts no MFA as fresh. `list_workspaces` reports a non-string `auth0_id` from the workspaces claim as an empty string. In local mode, a top-level `token.json` value that is not an object, such as a `_comment` key, is no longer counted as a region or reported by `list_workspaces`, where it used to appear as a workspace named after its key, and saving a token keeps it in the file.
- A plan-limit error (a 402 with `gate: "plan"`, or with no `gate` and a legacy `*_limit_exceeded` code from an older or self-hosted server) now reports `next` as null when the server body carries a non-string `next`, where the value used to be passed through unchanged. The Alpacon API server sends a string path or null, so a client that already reads `next` as a string or null has nothing new to handle.
- The WebFTP and command tools now check the type of each response field they read, and the metrics tools check each metric row field they read (`timestamp`, `usage`, the disk `device`, `mount_point` and byte counts, the traffic `interface` and rates). A body of the wrong shape returns an error whose message contains `Unexpected upstream response shape:` followed by each bad field's path, where several of these reads used to say `Expected a JSON object from upstream, got <type>`; a WebFTP transfer answer without an `id` is now such an error before any bytes are uploaded. `webftp_bulk_download` and the device lookup in `get_disk_usage` now return this error for a non-object body instead of answering as if no URL or no device came back, and `execute_file` reports it as `file_read_failed` or `file_write_failed`. `get_server_metrics_summary` now marks a metric whose `results` is not a list as unavailable instead of failing the whole summary. The error response shape is unchanged; a client matching the old message text has to match the new one.
- The `get_workspace_preferences` description now marks the `auto_agent_upgrade` response boolean as deprecated and due for removal from the server response (#292). Clients should read `agent_rollout_policy`; the current response shape is unchanged.
- Every tool's `region` parameter now publishes its accepted values, `ap1` and `us1`, and defaults to null instead of an empty string; leaving it out still resolves the region from the workspace, and `list_workspaces` still lists every region. A client that sends `region: ""` must omit the field or send null instead, since the SDK now refuses an empty string, like any other value outside the two, with a tool error before the call runs, where it used to resolve the region or return a `validation` error response.
- The `file_exec_unsupported_agent` hint and the `execute_file` description now name alpamon 2.8.3,
  the first release that reports its capabilities, instead of 2.6.0, and separate two cases: an agent
  older than 2.8.3 reports no capabilities (upgrade it), while one already on 2.8.3 or newer has no
  file lane on that platform, such as Windows (upgrading does not help; use `execute_command`). The
  `error_code` is unchanged, so a client parsing the response has nothing new to handle.
- `execute_file` and its `file_exec_reuse_exceeds_max` hint now state that standing approvals
  always expire: the workspace ceiling is 1 to 366 days (default 90), a requester may propose a
  shorter `reuse_days` but never a longer one, omitting it proposes no duration (the approver may
  still grant reuse up to the ceiling), and a proposal above the ceiling is refused. The previous
  wording said an omitted `reuse_days` could run with no expiry when the workspace had no ceiling.

### Added
- `execute_command`, `state_command_purpose` and `list_commands` now recognize a command the server refused because its line carries a script body, which can happen when the workspace approval policy blocks script bodies (`rejection_cause: "use_file_execution"` on the command row, read after verification rather than from a submit-time 4xx) and return `error_code: "use_file_execution"` with a `next_action` to rerun the script through `execute_file` with `write_file: true` on the same server and account (#358). A client parsing the response sees the new `error_code` on the `execute_command` error and on refused `list_commands` entries; for `execute_command_multi_server`, only the refused servers should be resubmitted.
- `execute_file` gained an optional `write_file` (boolean, default `false`) that writes `content`
  to `path` on the host through WebFTP, then submits the same bytes once the host reports the file
  written, and an `overwrite` that lets it replace an existing file (#360). A client parsing errors
  sees two new `error_code` values, `file_write_failed` and `file_write_timeout`, neither of which
  has submitted anything; the API reference has the ownership and refusal rules. With this and
  `read_from_server`, `commands` alone reaches WebFTP, so leaving `webftp` out of `--toolsets` no
  longer keeps file transfers from the agent.
- `execute_file` gained an optional `read_from_server` (boolean, default `false`) that reads the
  script already at `path` on the host and submits its exact bytes, so `content` is no longer
  required (#360). A client parsing errors sees three new `error_code` values,
  `file_exec_invalid_options`, `file_read_failed` and `file_read_timeout`, none of which has
  submitted anything. A held `execute_command` response may now carry an `execute_file_suggestion`
  object, whose `arguments.interpreter` is `null` with an added `interpreter_name` and `instruction`
  when the held line names a bare interpreter.
- `install_pam` (`server_id`, `workspace`, `region`): install the `alpamon-pam` package as root
  through the host's package manager on a host provisioned with alpamon alone, a no-op when the host
  is already current; it wraps the new `install_pam` value of
  `POST /api/servers/servers/{id}/actions/` (alpacax/alpacon-server#4239), **requires an
  alpacon-server release carrying that action**, takes no `force` because it is not disruptive, and
  needs the workspace's "Use sudo with MFA" setting on. A client parsing these errors sees three new
  `error_code` values, each a plain `status: "error"` to act on: `server_pam_install_unsupported`
  (400: the host has no package path—macOS, Windows, or a package manager Alpacon does not drive),
  `server_pam_install_requires_sudo_with_mfa` (400: sudo with MFA is off—turn the setting on; or
  this deployment cannot complete its step-up—the workspace cannot fix this, report it to the
  operator) and `server_pam_install_in_progress` (409: an install is already pending on that
  server; try again after it finishes).
- Over stdio, when the client sends no `clientInfo` name, the agent is declared to the server from
  the same environment markers the Alpacon CLI reads (`AI_AGENT`, `CLAUDE_CODE_CHILD_SESSION`,
  `CODEX_THREAD_ID` and the rest of the CLI's table). A `clientInfo` name always wins, and the SSE
  and streamable-HTTP transports never read the environment. Tool responses are unchanged.
- `work_session_create` gained an optional `target_account_username` (string), sent to the server
  as `target_account_username` only when given, so an agent can have an account such as `root`
  approved with the session (#343). An existing caller's request is unchanged.
- A finished command whose `error_phase` starts with `file_` now carries an `error_phase_hint`
  in `execute_command`, `execute_file` and `list_commands`: one sentence on what happened and what
  to do next, for `file_hash_mismatch`, `file_payload_invalid`, `file_open_failed`,
  `file_exec_unsupported` and `file_too_large`. An unrecognized `file_*` phase gets a generic
  file-lane hint; every other phase is unchanged.
- `work_session_records` (`session_id`, `websh_session_id`, `workspace`, `cursor`, `page_size`,
  `region`): read one page of a websh terminal recording captured inside a Work Session, as
  `{added_at, record}` chunks oldest first (#347). Wraps
  `GET /api/work-sessions/sessions/{id}/records/?session=<websh session id>`
  (alpacax/alpacon-server#4142) and **requires alpacon-server 2.42.0 or later**. It closes the gap
  `work_session_timeline` left when it stopped carrying recordings: the timeline names the sessions
  that have one, as `websh_session` items whose `id` this tool reads. Unlike the timeline and the
  audit lists it does not walk the cursor—one call is one request, and `data` is the server's page
  as it stands (`count`, `next`, `previous`, `results`) with no `pagination` object, because one
  page is already bounded at roughly 2 MiB of rendered chunks and merging ten would put tens of
  MiB in one response. Pass `data.next` back as `cursor` and stop when it is null; a page holding
  fewer items than `page_size` is not the end, since a byte budget cuts pages too. `page_size` is
  1 to 16 (default 8), and a value outside that range is refused locally with
  `error_code: "validation"` before any request. A 400 carries `error_code: invalid_input` for a
  missing or malformed `session`, a 404 means the websh session is not in this Work Session, is a
  tunnel, or is outside what the caller may see, and a 402 (`workspace_plan_update_required`)
  means the workspace is on the Free plan, which cannot read a recording whole, or that the
  session is older than the plan's audit window.
- `execute_file` gained an optional `reuse_days` (integer, 1 to 366): a proposed number of days
  for which the approver should let the same unchanged file be rerun without a new review
  (#323). It is sent as `file.reuse_days` only when given, so an existing caller's request is
  unchanged and a server that predates the field ignores it. A client parsing errors sees two
  new `error_code` values, `file_exec_invalid_reuse_days`
  (outside 1 to 366, also refused locally) and `file_exec_reuse_exceeds_max` (past the workspace
  ceiling; the server refuses rather than shortens), each a plain `status: "error"` to act on.
- `initialize` and `server/discover` now report the package version in `serverInfo.version`, which was previously an empty string (#144). A client that parsed the empty value as "unknown" will now see a real version string.
- `preview_alert_rule` (`workspace`, `rule_id`, `servers`, `window_s`, and the `create_alert_rule`
  fields minus `name` and `is_default`, `region`): replay an alert rule, saved or not, over up to
  seven days of stored samples and report the episodes it would have raised, how many would have
  interrupted someone, and who would receive them, without storing anything (#288). Wraps
  `POST /api/metrics/alert-rules/preview/`; a server without that endpoint refuses the request. The
  preview's four limit codes (`metrics_alert_rule_preview_window_too_long`, `_too_many_servers`,
  `_too_many_samples`, `_servers_required`) surface as `error_code` with a hint naming what to
  narrow, and `server_not_found` surfaces as `error_code` as elsewhere.
- `list_latest_metrics` (`workspace`, `region`, `search`, `groups`, `tag`, `is_connected`, `state`,
  `ordering`, `page`, `page_size`): the latest CPU, memory, disk usage, disk I/O and network reading
  for many servers in one request, one row per server. Wraps `GET /api/metrics/latest/`
  (alpacax/alpacon-server#3654) and **requires alpacon-server 2.37.0 or later**. It is the servers
  list with five metric cells added — filters, search, and pagination are `list_servers`'s own, plus
  `state` (`stale`, which includes `no_data`, or `no_data` alone) and `ordering` (any of `name`,
  `starred`, `sampled_at`, or a metric family by its hyphenated wire name or underscore spelling,
  `-`-prefixed for descending; both `state` and `ordering` are validated client-side before the
  request is built). Each metric cell carries `value`, `unit`, `sampled_at`, `device`, `collected`,
  `reason`, and `interval_s`, with `value`/`sampled_at`/`device` null when nothing is stored for
  that family. `get_server_metrics_summary`'s description now says explicitly that it answers for
  one server; use the new tool for many servers at once. Two new resources proxy it:
  `alpacon://metrics/{region}/{workspace}/latest` and
  `alpacon://metrics/{region}/{workspace}/latest/stale` (pinned to `state=stale`).
- `create_alert_rule` and `update_alert_rule` gained `notify_email` (`all`, `admins`,
  `group_members`, or `none`; validated against those four choices before the request is built)
  and `notify_slack_channel` (boolean), matching the alert-rule notification-destinations feature
  in alpacon-server (alpacax/alpacon-server#3594, deployed in server 2.35.3). Both are optional and
  sent only when given, so an existing caller's request is unchanged; omitted on create, the server
  default (`all`, `notify_slack_channel: true`) applies, and omitted on update the rule's current
  value is left alone. Only a human caller may set either field—the server refuses a service-token
  or agent write naming one with a 400 (`metrics_alert_rule_destination_not_allowed`), and
  `severity: "info"` suppresses the mail and the channel post regardless of what these two say.
- `get_alert_rule_recipients` (`rule_id`, `workspace`, `region`): preview who an alert rule would
  notify, as counts only—never names. Wraps `GET /api/metrics/alert-rules/{id}/recipients/`, added
  in alpacon-server (alpacax/alpacon-server#3618) and **requires alpacon-server 2.36.0 or later**.
  Returns `email` (`mode`, `count`, `reasons` with `admins`/`group_members`/`owner`—these overlap,
  so they need not sum to `count`), `slack_channel` (`enabled`, `connected`—both stay as configured
  for an info-severity rule even though info posts nothing), and `event_subscriptions`. A 404 while
  the rule itself reads fine through `get_alert_rules` means every server the rule is attached to
  is outside what the caller can see, not that the rule is gone; a rule attached to no server
  answers zeros instead.
  A new `alpacon://alert-rules/{region}/{workspace}/{rule_id}/recipients` resource proxies it.
- `list_rule_overrides`, `get_rule_override`, `create_rule_override`, `update_rule_override`, and
  `delete_rule_override` tools against `/api/metrics/rule-overrides/` (#244): a per-server departure
  from a workspace alert rule, keyed on `server` and `rule`, with `threshold`, `recovery_threshold`,
  `duration_s`, and `enabled` as nullable per-field overrides—a field left unset keeps the rule's
  own value, and `enabled=false` exempts the server from the rule entirely. At most one override per
  `(server, rule)` pair; the server refuses a second. `get_collection_profile`: what a server
  collects and at what cadence, wrapping `GET /api/servers/servers/{id}/collection-profile/`.
  Read-only and not gated behind the metrics extension, so it answers on every plan; `core[]` and
  `metrics[]` entries carry `interval_s`, `last_sample_at`, `collected`, `scope`, and `reason` when
  not collected, `metrics[]` entries also carry `retention_days`, the core disk-usage entry alone
  carries `latest[]` per-volume readings, and `not_collected[]` entries carry `reason` and
  `unlocked_by`. `update_server` gained `offline_alert_enabled` (boolean), a server's own
  offline-alert toggle independent of any workspace rule; the server refuses it from the host's own
  agent credential. `get_server` and `list_servers` responses can now also carry
  `offline_alert_enabled`—no new handling required for a client that already reads fields it
  recognizes by name. Three new `alpacon://` resources proxy the read-only tools above:
  `alpacon://rule-overrides/{region}/{workspace}`, `alpacon://rule-overrides/{region}/{workspace}/{override_id}`,
  and `alpacon://servers/{region}/{workspace}/{server_id}/collection-profile`.
- `create_alert_rule` and `update_alert_rule` gained `operator`, `duration_s`, `recovery_threshold`,
  `no_data_after_s`, `device`, and `severity`, matching the alpacon-server metrics-extension rule
  shape (#243). All six are optional and sent only when given, so an existing caller's request is
  unchanged; `device` is accepted only for device-scoped targets (disk usage, disk I/O, network),
  and `duration_s=0` (the server default) still fires on a single breaching sample.
- `list_alerts` gained a `resolved` filter (#243): omitted, it returns open alerts only as before;
  `true` returns the resolved history. `list_alerts` and `get_alert` responses can now also carry
  `resolved_at`, `device`, and `severity` from the rule that raised the alert — no new handling
  required for a client that already reads fields it recognizes by name.
- `list_event_subscriptions` and `create_event_subscription` now document two more event types,
  `metric_threshold_crossed` and `metric_threshold_resolved` (#243), which the server already
  accepted once a workspace's metrics extension was enabled. Both carry an `alert_id` pairing the
  crossing to its resolution; subscribing to every server (an omitted `target_id`) needs an admin
  account.
- Actionable hints for two error codes the workspace extension gates return:
  `workspace_extension_plan_required` (402, the workspace's plan excludes the extension that
  owns the endpoint) and `workspace_extension_not_enabled` (403, the plan allows it but a
  workspace admin has not enabled it yet). The metrics, DNS, proxy, and Private SSL extensions
  share these codes (alpacax/alpacon-server#3559) and the body does not name the extension, so
  the hints stay generic. A client already reading `error_code` from an error response needs no
  new handling; the hint text is appended to `message`.
- `execute_file`: run a script that already exists on a server as a verified file (#207, the
  client half of ADR 0053). It submits `POST /api/events/commands/` with a `file` object—`path`,
  `interpreter`, `args`, and the script's `content` byte-for-byte—instead of `line`, so the
  reviewer judges the exact bytes and the agent executes only an on-disk file that hashes to them;
  an approver can then make an unchanged re-run standing, which a `bash /path` line never is. The
  response is the `execute_command` shape plus a `file` object echoing `path`, `interpreter`, and
  `args`, and no `command` or `shell` echo. A client parsing errors sees six new `error_code`
  values (`file_exec_unsupported_agent`, `file_exec_assessor_disabled`, `file_exec_invalid_path`,
  `file_exec_content_too_large`, `file_exec_empty_content`, `file_exec_line_too_long`), each a
  plain `status: "error"` to act on, never a pending approval.
  `execute_command`'s description now points scripts and heredocs at the new tool.
- `state_command_purpose`, and a `purpose` argument on `execute_command` and
  `execute_command_multi_server` (#186). When the verification gate holds an agent's command
  and asks what it is for (ADR 0052), `execute_command` now reports it as
  `status: "purpose_required"` instead of a result, and `state_command_purpose` answers it.
  A client parsing command responses has to handle that status: it is not a pending approval,
  and no approver has been notified. Three response fields are new: `purpose_truncated` on a
  success whose purpose was cut to the 2000-character ceiling, and `purpose_guidance` plus an
  optional `deadline_seconds` on `purpose_required` — the last is absent when the server
  reports no expiry, so a parser must tolerate it missing.
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
- `force` on the two disruptive server actions: `restart_agent` and `upgrade_agent` (#140). The
  server has refused these while a host is busy with an open Websh/WebFTP session or an in-flight
  command since alpacax/alpacon-server#2553, and `force=true` is the only way through. It defaults to
  `false`, so an existing caller sends the same effective request as before; `update_information`
  is not disruptive and gains nothing.
- `request_sudo_policy`: ask for a sudo policy through `/api/sudo/policy-requests/`, which mints an
  approval request an admin has to approve before the policy exists (#140). The tool returns
  `status="pending_approval"` with category `SUDO_POLICY_REQUEST_PENDING`, so a client that already
  branches on the pending-approval shape needs no new handling. Omitting `users` scopes the
  approved policy to the requester alone rather than to the whole workspace, which is how the
  server narrows an approved request. `session_authorized` (formerly `allow_bypass_mfa`) is
  deliberately not a parameter: the server refuses it on this endpoint.
- `--toolsets` CLI argument (and `ALPACON_MCP_TOOLSETS` env var) for local
  stdio/SSE mode: selectively register toolsets; default remains `all`
  (#34). Remote mode is unaffected and always registers every tool.
- Workspace settings management tools under `/api/workspaces/`
  - Read tools: `get_workspace_access_control`, `get_workspace_security`, `list_workspace_mfa_methods`, `get_workspace_notifications`, `get_workspace_preferences`
  - Partial-update tools: `update_workspace_notifications`, `update_workspace_preferences`
  - Exposed the five read tools as `alpacon://workspace-settings/{access-control|security|mfa-methods|notifications|preferences}/{region}/{workspace}` resources
  - Security and access-control writes are intentionally omitted from the tool surface; on SaaS the server gates them behind a superuser session with fresh MFA (unsatisfiable by a static API token), and even where an on-premise admin token could write them, keeping governance-level settings human-only via the web console is the safer default
  - `get_workspace_security` and `list_workspace_mfa_methods` require JWT (OAuth/SSO) authentication and short-circuit a static API token before any request, and are SaaS-only (a clear not-available message on on-premise 404)
  - The list fields on the update tools (`notification_channels`, `enabled_extensions`) replace the whole array rather than appending; documented the read-merge-write pattern
- `suse` (openSUSE / SLES) as a `platform` value on `get_registration_guide`, matching
  the platform choices the server offers for token-based installs (#182). The guide
  response keeps its existing shape—the zypper commands arrive in the same
  `install_commands` list every other platform uses.

### Changed
- `list_activity_logs`, `list_server_logs`, and `list_webftp_logs` now take `cursor` instead of
  `page`, which alpacon-server's cursor paginator ignored, so page two used to return page one
  again (#325). Each call follows the cursor for up to 10 requests and merges the pages; `data`
  drops `next` and `previous`, and a new top-level `pagination` object reports the walk, so check
  `pagination.complete` before treating a result as the whole list. A `page` argument is now
  dropped without an error; see `docs/api-reference.md` for the `pagination` fields and resume.
- `work_session_timeline` now asks the server for a paged timeline, follows the cursor for up
  to 10 requests, and reports the walk under a top-level `pagination` object as the audit tools
  do (#325): check `pagination.complete` before treating a result as the whole session, since a
  result stopped at the bound holds the start of the session and not its end. `data` is now the
  walk's `{count, results}` envelope with `count` null, and a server that predates the paged
  timeline is reported `stopped_because: unpaginated_server` with `complete: true`.
  `include_records` is retired and any value is refused with `error_code: "validation"` rather
  than dropped; the refusal and the tool description now point at `work_session_records`, which
  reads a recording one page at a time (#347).
- `delete_certificate_authority`'s description now matches alpacon-server after alpacax/alpacon-server#4057 (#333): a CA that has received a certificate sign request can no longer be deleted, and the call surfaces `error_code` `cert_authority_cannot_be_deleted` with the CA and its records kept. The description points to `unregister_server` on the CA's server for retiring such a CA. A client that treated the delete as always succeeding must handle the new 400.
- The CPU, memory, disk, and network usage tools, the interface lookup behind `get_server_metrics_summary`, and `webftp_check_status` now return an error when upstream answers with a bare JSON scalar (#236), and all but `webftp_check_status` also when a paginated body's `results` is not a list; they used to report "no data", or a transfer still in progress. The WebFTP upload, download, and bulk tools already failed on such a body with a generic error and now name the unexpected body type instead. Object and list bodies behave as before; a client parsing these responses may now see an `error` status where it used to see an empty result.
- `list_servers` error responses now carry the upstream `code` the way every other server tool does (#237): an ordinary coded 4xx adds `error_code`, a WorkSession gate code adds `code` and `next_action`, a code with a known hint appends that hint to `message`, and a 402 plan-limit response returns the plan-limit shape (`error_code`, `gate`, `axis`, `next`, `requires_human_approval`, `next_action`). The success response is unchanged; a client parsing `list_servers` errors may now see those fields.
- Tool descriptions now match what the tools do. `work_session_create` names `work_session_id`, the parameter `execute_command` takes, and says a session that needs approval returns `pending_approval` until a human approves it; `webftp_upload_file`, `webftp_bulk_upload`, and `webftp_bulk_download` say they return `remote_mode_unsupported` in remote mode, where the MCP server cannot reach your local filesystem; `duplicate_api_token` says the copy drops scopes that can no longer be granted and caps expiry at the workspace maximum; and the pending-approval guidance lists `completed` among the states that mean stop polling. The `remote_mode_unsupported` error message now names the tools that work in remote mode; the codes are unchanged, so a client parsing responses needs no change.
- `work_session_timeline` now defaults `include_records` to false, so websh terminal records are omitted unless requested (#286). A client that relied on the previous default must now pass `include_records=True` to keep seeing those records. Superseded by #325: `include_records` is now refused, and a recording is read with `work_session_records`.
- `webftp_upload_content` now rejects file content over 3 MiB decoded with a tool
  error naming the limit and the size sent, instead of relying on the transport
  to reject it (#144). The check only applies on streamable-http and SSE, the
  transports the SDK's request-body cap actually constrains; stdio is unaffected.
  MCP SDK 2.x added a 4 MiB request-body cap on streamable-http/SSE that didn't
  exist under SDK 1.x; the ASGI limit is now raised to 5 MiB so a too-large
  request reaches this check rather than failing as a bare HTTP 413 with no
  JSON-RPC body. A request far larger than 3 MiB (roughly 3.75 MiB of file bytes
  and up, once base64 envelope overhead is included) still gets that plain-text
  413 before reaching the tool at all; use `webftp_upload_file` in local mode
  for such files. The upload path's design is being reconsidered in #275.
- MCP SDK 2.x also changed two error shapes clients should account for (#144): a
  `resources/read` on an unknown URI now returns JSON-RPC code `-32602`
  (invalid params) with `error.data.uri` set, instead of `0`; and an unknown
  method now returns `-32601` (method not found) instead of `-32602`.
- The auth error middleware now streams the response instead of buffering it in
  full, so a long-lived tool call is no longer held back from the client until it
  finishes (#144). Nothing else about the response changes: on a second upstream
  401 within the cooldown window the app's own response still passes through.
- `create_alert_rule` and `update_alert_rule` no longer validate `target` against a
  client-side copy of the server's metric list before sending the request; an unrecognized
  `target` now reaches the server and comes back as its own `400` with an `error_code`
  instead of a local validation error. The client-side list drifted from the server's, so a
  metric the server had added was rejected locally until the tool caught up.
- BREAKING: `create_alert_rule` and `update_alert_rule` now take a `target` metric (one of
  a fixed set mirroring the server's `AlertRule.TARGET_METRICS`) and a `threshold`, instead
  of the invented `metric_type` and `condition`, which the serializer never read. A call
  still passing the old names now fails outright instead of being accepted and dropped.
- BREAKING: `create_webhook` now requires `owner`, a user UUID, because `WebhookSerializer`
  requires it. A call without it is a TypeError, and a username in its place is rejected
  before the request goes out.
- Values a closed server-side set defines are now checked in the tool rather than at the
  API: `action_type`, `provider`, the webhook `owner` UUID, and the 512-character
  cap on note `content`. Each returns a validation error naming the accepted values, in
  place of an opaque 400.
- The validation error an update tool returns when it receives no writable field now reports
  `field: "payload"` and names the accepted fields in the `suggestion` sentence, rather than
  packing the whole list into `field`. Affects `update_alert_rule`, `update_server`,
  `update_server_note`, and `update_webhook`.
- Arguments that are supplied but blank are now rejected in the tool instead of being
  forwarded to the API (#199). `limit` and `page_size` must be positive integers on every
  tool that takes one, and the `command` on `execute_command` and `execute_command_multi_server`
  and the `command`/`path` match patterns on the ACL tools must not be empty or
  whitespace-only. A client that sent any of these gets a `status: "error"` naming the field
  instead of an opaque 400 or an ACL rule built on a blank pattern.
- `list_session_analyses`'s `status` and `risk_score`, and `list_approval_requests`'s
  `status`, now forward an empty string to the API instead of silently dropping it (#200).
  A client that passed `status=""` meaning "no filter" now gets whatever the server does
  with a blank filter value, not the unfiltered list it got before.
- List filters that are supplied but blank are now forwarded to the API instead of being
  silently dropped (#226), matching the rule #200 established. Affects `reporter` on
  `list_events`; `status` and `requester_type` on `work_session_list`; `username_filter`
  on `list_system_users`; `groupname_filter` on `list_system_groups`; `package_name` and
  `architecture` on `list_system_packages`; and `partition`, `interface`, and `end_date`
  on the metrics window tools, plus `device` on `get_disk_usage` when a `partition` is
  also given, and unconditionally on `get_disk_io`. A client that passed one of these as
  `""` meaning "no filter" now gets whatever the server does with a blank filter value.
  `server_id`, `limit`, and `page_size` are unaffected: a blank one was already rejected
  before the request was built.
- `restart_agent`, `upgrade_agent`, and `update_information` now state in their description and
  docstring that the server's action endpoint accepts only these three actions (#290).
- BREAKING: `work_session_extend` now requires `reason` (#294): a short justification the
  human approver judges the request by, sent on every request, including one an auto-approve
  lane extends directly. A call that omitted `reason` before now fails with a `TypeError`
  at the tool boundary instead of extending the session. Whether the extension applies
  immediately or waits for approval follows the workspace's approval policy, the same rule
  `work_session_create` uses—an auto-approve lane still returns a normal success, but any
  other lane now queues an extension request and the tool returns `status="pending_approval"`
  instead of applying it; the session's `expires_at` stays at its prior value until a human
  decides out-of-band. Poll `work_session_get` until `expires_at` changes to see the outcome.
  A blank `reason` now surfaces as `error_code: work_session_extension_reason_required` with
  an actionable hint instead of an opaque `400`. Matches alpacon-server's extension-approval
  change (alpacax/alpacon-server#3805); this must ship in the same MCP release as, or
  before, the server release that enforces it.
- `get_workspace_preferences` and `update_workspace_preferences` now read and write
  `agent_rollout_policy` (#292), the workspace's agent-upgrade rollout policy:
  `{"mode": "latest"|"n_minus_1"|"manual", "window": {"days": [0-6, Monday is 0],
  "start_hour": 0-23, "length_hours": 1-24, "timezone": "<IANA>"}}`. A write may name
  only part of the object; whatever it leaves out keeps its current value, and the
  shape is validated locally—naming an unknown key, an out-of-range hour, a duplicate
  day, or an unrecognized timezone fails before any request is sent. `update_workspace_preferences`
  no longer sends `auto_agent_upgrade` to the server. Choosing `n_minus_1` while this
  deployment has no pinned agent-upgrade targets enabled comes back as a readable
  `error_code: preferences_agent_rollout_mode_unavailable` instead of an opaque `400`;
  the window validation codes (`preferences_agent_rollout_{policy,mode,window_days,
  window_start_hour,window_length,window_timezone}_invalid`) surface the same way.
- A plan-limit 402 (`gate: "plan"` with an `axis`, or, from an older or self-hosted
  alpacon-server, a gate-less `server_limit_exceeded`, `user_limit_exceeded`,
  `application_limit_exceeded`, `websh_limit_exceeded`, `webftp_limit_exceeded`, or
  `websh_share_limit_exceeded`) now comes back as a structured result—`error_code`, `gate`,
  `axis`, `next` (passed through unmodified), `requires_human_approval: false`, and a
  `next_action` telling the agent not to retry and what to tell the user, with a console
  billing link when the workspace host resolves to one (#296). A client parsing error
  responses should check for `axis` before falling back to generic error handling. A feature
  lock (`gate: "plan"` with no `axis`) is unaffected and keeps its existing generic-error
  handling.

### Removed
- BREAKING: the `owner` filter on `list_webhooks` (alpacax/alpacon-server#3647). A server
  carrying alpacax/alpacon-server#3925 ignores `?owner=`, so the filter would have answered an
  unfiltered list; a client still sending `owner` now has it dropped and gets every webhook. Those
  servers return no `owner` on a webhook either, so `list_webhooks` and `get_webhook` results
  carry none.
- BREAKING: `shutdown_agent`, `upgrade_system`, `reboot_system`, and `shutdown_system` (#290,
  #291). Privileged power operations on a host or its agent—a shutdown, a reboot, an OS-level
  package upgrade—now go through a Work Session with sudo, MFA, policy, or approval, and
  recording, rather than a one-click action. The four action verbs were removed from the
  server's action endpoint, which answers a removed action with `400`; a caller still naming
  one of these tools gets a `Tool not found` error instead of the action it used to perform.
  `restart_agent`, `upgrade_agent`, and `update_information` are unaffected; for the host
  upgrade/reboot flow, see "Keeping hosts current" in [examples.md](docs/examples.md).
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
- In remote mode, a tool call that needs MFA now answers 403 with `WWW-Authenticate: Bearer error="insufficient_scope", scope="... mfa"` instead of 401. MCP clients answer a 401 by refreshing the token first and drop its scope while the refresh succeeds, so the browser MFA flow never started and the refreshed token was refused again ("Server returned 401 after re-authentication"); on `insufficient_scope` they skip the refresh and authorize with `mfa`. This covers both the existing `auth_mfa_required` step-up and the new `auth_token_mfa_missing` from alpacon-server (the token was issued without the workspace's sign-in MFA), which is now recognized as an MFA signal too. A client without step-up support sees a 403 where it saw a 401. In stdio and SSE mode, which have no browser re-authentication, the tool answers `auth_token_mfa_missing` with `message: "MFA verification required"` instead of the raw HTTP error; the response keeps its `status: "error"` shape.
- An `AI_AGENT` version now reaches the server in the case it was given: `my-agent/1.0.0-Beta.1`
  is declared as version `1.0.0-Beta.1`, not `1.0.0-beta.1`. Only the agent name is lowercased.
- In JWT mode, a `workspace` argument that is a renamed URL slug is now resolved to the workspace's fixed `schema_name` through the account service lookup before it is matched against the token claims. An argument that already equals a claim's `schema_name` makes no network call; the lookup is skipped when `ALPACON_ACCOUNT_URL` is unset, and any lookup failure keeps the previous rejection. Tool responses keep their shape, so a client parsing them needs no change. `list_workspaces` still reports each domain from `schema_name`, since the token claims carry no slug.
- A 503 with `auth_verification_unavailable` from alpacon-server (it could not check the credential during an identity provider, cache or database outage) now reaches the agent as `error_code` with a hint to retry shortly and not to re-authenticate. The call was already retried; only the code was dropped once retries ran out. A 5xx result now carries `error_code` when the server sent one, never the raw response body, and `get_server_metrics_summary` reports it per section with the same hint.
- The tool entry log no longer writes the command a call runs (#311). It writes an argument's value
  only for a reviewed set of identifiers, names, paths, enums, filters and timestamps
  (`_LOGGED_VERBATIM_KEYS`); every other argument, `command`, `commands`, `search` and
  `search_query` among them, keeps its key and is recorded as `<str len=N>`, `<list items=N>` or
  `<dict items=N>`, so a credential typed inline on a command line never reaches the log. At DEBUG
  the HTTP client records request and response bodies and query parameters by field name and size,
  and headers by name; an upstream 4xx or 5xx error body is logged by field name, not text. httpx
  and httpcore now log warnings and errors only, the MCP SDK nothing below INFO, and the uvicorn
  access log drops query strings, since those write request URLs with their query, each client
  message, and the OAuth callback's authorization code. Nothing changes for a client, but an
  existing `logs/alpacon-mcp.log` can hold commands as they were typed.
- A client-supplied value can no longer start a second log record (#310). The stderr and file sinks,
  uvicorn's own records included, escape every control character in a message and indent each line
  of a traceback, and the OAuth
  callback `error` and `error_description`, a mismatched `client_id`, a JWT `kid`, and JWT claim
  values are escaped and bounded where they are logged. Nothing changes for a client.
- `get_server_metrics_summary` now reads disk usage and network traffic for the root partition (a non-virtual one when several exist) and the first active interface (a non-virtual name such as `eth0` before `docker0` or `br-…`), and reports a failed or empty lookup in `metrics.disk.error` or `metrics.network.error` (#298). `get_network_traffic` now requires `interface`, an interface ID, so its resource URI is now `alpacon://metrics/{region}/{workspace}/{server_id}/network/{interface}`. The CPU, memory, disk, and network metrics now report the newest sample as `current` and a `time_range` running oldest to newest, so a client reading `current` sees different values, and because the realtime endpoints keep only 12 hours, the CPU, memory, disk usage, disk I/O, and network tools now default to the last 12 hours, with `hours` defaulting to 12 and capped at 12 (it was 24 and 168).
- `webftp_check_status` now returns a `message` naming the transfer state—still in progress, completed, or failed with the server's own message when it gives one (#247). The top-level `status: "success"` only means the status call itself succeeded, and a running transfer used to come back as `{"success": null, "message": null}` with no words at all. `data` is unchanged, so a client already branching on `data.success` needs nothing new.
- `webftp_upload_content` no longer writes the uploaded file into the log (#233). `with_logging`
  logged every argument value in full, and `file_content` carries the base64 payload, so the whole
  uploaded file landed in one INFO line, measured at 1.4 MB of log for a 1 MB upload. The entry
  log now records the payload by its length, replaces a kept string over 256 characters with
  `<str len=N>` and a list or dict over ten entries with `<list items=N>` or `<dict items=N>`, and
  builds the summary only when INFO is enabled. Nothing changes for a client, but an
  existing `logs/alpacon-mcp.log` can hold uploaded file contents and should be treated
  accordingly.
- The entry log no longer records the free text, personal data, environment maps, and config lists
  a tool receives (#233). The payload and free text a person wrote, the webhook and proxy URLs
  that are themselves a credential, personal data, the `env` map that could carry a secret under
  any key, and bulk config lists are recorded by type and size alone; the identifiers, paths,
  filters, and the `scopes` and `presets` a credential was granted are kept. Nothing changes for a
  client.
- The published input schema of every tool behind `@mcp_tool_handler` no longer carries
  `kwargs`, the catch-all the decorator injects the token through (#211). FastMCP did not read
  it as a catch-all and published it as a required string, so a client that sent only the
  documented arguments was rejected with a `Field required` validation error naming `kwargs`,
  and reached the tool only by adding a meaningless `kwargs: ""`. A client that has been
  sending that keeps working, since an unknown property is not rejected, but every client reads
  a different schema now: `kwargs` is gone from `properties` and from `required`, and on
  `list_workspaces`, whose only required field it was, the `required` key is gone entirely.
- `get_server_overview` no longer writes the caller's credential into the log (#211). It used
  to forward its own `**kwargs` into the five tools it fans out to, and by then that catch-all
  held the resolved API token in stdio mode or the raw JWT in remote mode. Each sub-tool bound
  it as `arguments['kwargs']`, a key `_UNLOGGED_KEYS` did not cover, so the entry log wrote
  the credential in cleartext at INFO five times per call, and `utils/logger.py` applies no
  redaction. Nothing changes for a client, but `logs/alpacon-mcp.log` from any earlier
  `get_server_overview` call can hold a live token and should be treated accordingly.
- `list_workspaces` is now registered through `@mcp_tool_handler` like every other tool, so a
  failure comes back as the standard `error_response` envelope instead of an uncaught traceback
  (#201). A malformed `token.json` was the way to hit it. Two things change for a client: an
  unknown `region` value is now rejected with a `validation` error naming the field, where it
  previously returned an empty workspace list; and a failure carries `status: "error"` with a
  `Failed in list_workspaces:` message. `health_check` keeps its raw registration, because it
  has to answer before any workspace or JWT exists, but it now returns the same error envelope
  on failure.
- `list_workspaces` now reports `data.unusable_entries`, the number of JWT workspace claim
  entries dropped for naming no workspace or no region (#201). The Auth0 Action that mints the
  claim writes `region: org.metadata?.region || null` when an organization has no region in its
  metadata, and such an entry authorizes nothing, so it is left out of `data.workspaces`. Without
  the count the workspace simply vanished from the tool whose job is enumeration. A client that
  reads the count can tell a short list from a complete one; it is 0 in local mode and a `region`
  filter does not narrow it.
- `TokenManager` now rejects a `token.json` whose top level is not a JSON object (#201). An
  array or a bare string parsed cleanly and was handed to callers that walk it as a map of
  regions, so the first `.items()` raised an `AttributeError` far from the real problem. Such a
  file is now logged as an error and read as no tokens at all, the same as an unparseable one.
- A JWT `workspaces` claim entry that does not name both a workspace and a region as
  non-blank strings is now dropped instead of being passed on, and the warning names the
  offending fields rather than dumping the entry (#201).
  `list_workspaces` used to report such an entry as a workspace with an empty name and the
  domain `..alpacon.io`, and an entry that was not an object at all crashed the region
  auto-detection with an `AttributeError` that no tool error handler covers, so it reached
  the client as a traceback. A client in remote mode may now see fewer entries than the
  claim carries.
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