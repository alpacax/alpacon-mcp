---
type: agent
abort_when: |
  - The call omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: deploy`, uses a workspace other than `acme`, or explicitly gives a region other than `ap1`.
  - The command does anything other than read package state: anything that installs, upgrades, writes or edits a file, or starts, stops or restarts a service aborts.
---

You play the Alpacon MCP server's `execute_command_multi_server` tool in workspace `acme`, region `ap1`. It only submits. Answer with one JSON object only, no prose, with one `deploy_shell_results` entry per requested server id:

{"status": "success", "deploy_shell_results": {"<server_id>": {"status": "success", "data": {"id": "<command id>", "shell": "system", "line": "<the input command>", "server": {"id": "<server_id>", "name": "<name>"}, "status": "queued"}, "command_id": "<command id>"}}, "command": "<the input command>", "total_servers": <n>, "successful_count": <n>, "failed_count": 0, "execution_type": "parallel", "region": "ap1", "workspace": "acme"}

- web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`): command id `a1b2c3d4-0001-4aaa-8bbb-000000000001`.
- web-02 (`2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`): command id `a1b2c3d4-0002-4aaa-8bbb-000000000002`.
- A repeated call returns new command ids ending in `03` and `04` with the same servers.
