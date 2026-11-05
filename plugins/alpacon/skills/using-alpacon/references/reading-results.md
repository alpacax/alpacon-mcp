# Reading list results and metrics

## Three ways lists page

Check which shape a list returned before you conclude you have seen everything.

- `page` and `page_size`, with `count` and `next` in the result: `list_servers`, `list_alerts`, `list_approval_requests`, `list_iam_users`, `list_latest_metrics`, and most other lists. When `count` is larger than what you have, call again with the `next` page number.
- A walked cursor with a `pagination` object: `list_activity_logs`, `list_server_logs`, `list_webftp_logs`, and `work_session_timeline`. Read `pagination.stopped_because`: on `page_bound`, pass `pagination.next_cursor` back for the rest; on `upstream_error` the walk failed partway, so say the list is incomplete and retry as the message says; `end_of_list` or `unpaginated_server` means you have it all. `complete: false` alone does not tell you which.
- `limit` only, newest first: `list_commands` (default 20, at most 100), `list_events`, `search_events`, and `work_session_list`. There is no next page; raise `limit` or narrow the filter.

`work_session_records` returns one page at a time: pass `data.next` back as `cursor` until it is null.

Never describe a whole history from the first page.

## Empty metrics

An empty metric is not by itself an outage.

- When the metrics feature is unavailable, the result says so with `error_code="workspace_extension_not_enabled"` (an admin has not turned it on) or `workspace_extension_plan_required` (the plan does not include it).
- `available: false` with a message such as "No CPU data available" means the feature answered but has no points for that window. Call `get_collection_profile` for the server: it reports whether metrics collection is enabled and which metrics are not collected and why.
- Realtime metrics cover at most the last 12 hours.
