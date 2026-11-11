# Scripts and files

## Run a script with `execute_file`

Send any script, heredoc, or `bash /path/to/file` line through `execute_file`, not `execute_command`. The reviewer judges the exact bytes, and the host runs the file only if its bytes still hash the same. An approver can mark a verified file as standing, so an unchanged rerun (same bytes, server, account, and args) clears without paging a person; a shell line never can.

- You have the script's text: pass `write_file=true` with the full text as `content`. One call writes it to `path` and submits it. An existing file is refused with `file_write_failed` unless you also pass `overwrite=true`.
- The script is already on the host: pass `read_from_server=true` and no `content`. The call reads the file's bytes as `username` and submits those.
- `write_file` and `read_from_server` move the file through WebFTP, so the Work Session needs both the `command` and `webftp` scopes for personal API tokens and OAuth/browser callers. Personal-token enforcement requires an Alpacon server release that supports it, as described in [Work Sessions](work-sessions.md). With `command` alone the transfer is refused with `code="work_session_scope_not_allowed"` and nothing runs.
- Both off: the file must already be at `path`, and `content` is only what the reviewer reads.
- Pass `content` byte for byte. Do not strip a trailing newline or change line endings; a mismatch fails at run time.
- `path` and `interpreter` are absolute (`/bin/bash`, not `bash`). Put pipes, redirection, and environment setup inside the script; nothing can be composed around the file.
- `reuse_days` (1 to 366) proposes how long the approver may let this exact file rerun without a new review. It is a proposal the approver may decline. A value above the workspace ceiling is refused with `file_exec_reuse_exceeds_max`.
- The write happens before review, so a run that is later denied leaves the new file on the host.
- `execute_file` always waits for the result; it has no `wait` option. Otherwise it follows the same rules as `execute_command`: a held run returns `pending_approval`, a purpose demand returns `purpose_required`, neither is resubmitted, and sudo inside the script is approved or denied the same way.

### Refusals that do not wait for anyone

These come back as `error_code`. Nothing waits behind them, so fix the call or switch lanes; do not wait or resend unchanged.

- `file_exec_unsupported_agent`: the server's agent cannot run verified files. Upgrade the agent if the message says so; otherwise use `execute_command`.
- `file_exec_assessor_disabled`: verified file runs are unavailable on this Alpacon deployment. Use `execute_command`.
- `file_exec_invalid_path`, `file_exec_invalid_options`, `file_exec_empty_content`, `file_exec_content_too_large` (over 64 KB), `file_exec_line_too_long`, `file_exec_invalid_reuse_days`, `file_exec_reuse_exceeds_max`: fix the argument the message names.
- `file_write_failed` or `file_read_failed`: nothing was submitted. Fix the cause (path, permissions, a file that already exists) and rerun. A Work Session refusal on the transfer keeps its own `code` instead.
- `file_write_timeout` or `file_read_timeout`: the host did not answer within about a minute, and nothing was submitted. A write may still land late, so once the host is reachable, rerun with `overwrite=true`, or with `read_from_server=true` if the file is there as intended.

### Secrets

A command line that carries a credential is refused with `command_inline_credential`. On `execute_command`, move the secret into the `env` argument. On `execute_file`, have the script read it at run time from a file or the host's environment, as the message says.

## Move files with WebFTP

For personal API tokens and OAuth/browser callers, REST file-transfer creation needs the `webftp` scope on an active, approved Work Session and its id as `work_session_id`. The Alpacon server enforces this requirement; personal-token enforcement requires a server release that supports it. Service tokens retain their endpoint-specific authorization rules.

- `webftp_upload_content` writes `file_content` to a path on the server. `file_content` must be base64-encoded; plain text is refused with `code="invalid_content"`. On the hosted server it accepts up to 3 MiB of decoded content; larger content is refused with `code="content_too_large"`.
- `webftp_download_file` fetches a file or folder. On the hosted server it waits for the host to send the file, then returns a `download_url` valid for 24 hours instead of writing to your disk; hand the person the link or fetch it before it expires. A failed transfer returns `code="download_failed"`. `code="download_timeout"` means the host had not finished in time; check it later with `webftp_check_status`.
- `webftp_upload_file`, `webftp_bulk_upload`, and `webftp_bulk_download` read or write a path on the machine running the MCP server. The hosted server cannot reach your disk, so they return `code="remote_mode_unsupported"`; use `webftp_upload_content` and `webftp_download_file` there.
