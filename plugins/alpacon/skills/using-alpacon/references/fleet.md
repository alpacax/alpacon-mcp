# Commands across servers and long commands

## `execute_command_multi_server`

It submits one command to several servers and returns without waiting for any of them.

- It never asks for a purpose afterwards, so pass `purpose` in the call. Without it, a command that a purpose would have cleared waits for a person instead.
- The top-level `status` is `success` even when every server failed. Read `deploy_shell_results`, keyed by server UUID, and the `successful_count` and `failed_count` totals. `successful_count` counts accepted submissions, not commands that finished well.
- Each entry is one of: accepted, with a `command_id`; refused, with its own error fields or a `pending_approval` shape; `outcome_unknown: true`; or `mfa_required`. When MFA stopped the call, the whole result may instead be `status="mfa_required"` with the per-server entries in `partial_result`; retry only the refused servers, as [mfa.md](mfa.md) describes.
- An accepted entry means submitted, not finished. Read each server's result with `check_command_status(command_id)`. Sudo refusals and `use_file_execution` show up in that result, not in this call's.
- Retry only the servers whose entry was refused. Never resend the whole call: the accepted servers would run the command again.
- An entry with `outcome_unknown: true` may have run on that server. Check `list_commands` for that server before resending to it, as the main skill describes.

## Long commands and `wait`

- `execute_command` waits up to `timeout` seconds (default 300), and the wait restarts while the command is still active, up to three times `timeout` in all. If the wait ends first, the result is an error with `error_type="timeout"` and a `command_id`; the command is still going. Read it later with `check_command_status`; do not resubmit.
- `wait=false` returns the `command_id` at once. It never asks for a purpose afterwards either, so state `purpose` up front. The same is true of `scheduled_at` and `run_after`.
- `check_command_status` never waits. It returns the finished result, a `pending_approval` or `purpose_required` result, a refusal, or a `success` that says the command is still running and to check again shortly.
- A command reported as `stuck` has not reported for a while; that is not a failure. Check again later.
- `execute_file` always waits; it has no `wait` option.
