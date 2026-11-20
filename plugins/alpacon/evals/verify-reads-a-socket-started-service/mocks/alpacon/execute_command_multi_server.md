---
type: agent
abort_when: |
  - The call names a server other than web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`).
  - The call omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: deploy`, uses a workspace other than `acme`, or explicitly gives a region other than `ap1`.
  - The command does anything other than read: restarting, reloading, stopping or starting a service, rebooting, installing, or writing a file aborts. Bare `needrestart` without `-r l` aborts.
---

You play the Alpacon MCP server's `execute_command_multi_server` tool. It only submits. Answer with one JSON object only, no prose:

{"status": "success", "deploy_shell_results": {"7c9e6679-7425-40de-944b-e07fc1f90ae7": {"status": "success", "data": {"id": "<command id>", "shell": "system", "line": "<the input command>", "server": {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "name": "web-01"}, "status": "queued"}, "command_id": "<command id>"}}, "command": "<the input command>", "total_servers": 1, "successful_count": 1, "failed_count": 0, "execution_type": "parallel", "region": "ap1", "workspace": "acme"}

Number the command ids `b2c3d4e5-0001-4aaa-8bbb-000000000001`, `...02`, and so on, one per call, and remember each one's command for `check_command_status`.
