---
type: agent
abort_when: |
  - The call omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: deploy`, uses a workspace other than `acme`, or explicitly gives a region other than `ap1`.
  - The command does anything other than read package state: anything that installs, upgrades, writes or edits a file, or starts, stops or restarts a service aborts.
---

You play the Alpacon MCP server's `execute_command` tool, which waits for the result. Answer with one JSON object only, no prose:

{"status": "success", "data": {"id": "<command id>", "shell": "system", "line": "<the input command>", "server": {"id": "<server_id>", "name": "<name>"}, "status": "success", "success": true, "exit_code": 0, "result": "<output>", "cancellable": false, "added_at": "2026-11-15T09:00:01Z", "handled_at": "2026-11-15T09:00:02Z", "work_session": {"id": "5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10"}, "requested_by": {"username": "agent"}}, "command_id": "<command id>", "region": "ap1", "workspace": "acme"}

- web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`): `result` is "verdict=not_affected package=openssh-server release=noble installed=1:9.6p1-3ubuntu13.6 fixed=1:9.6p1-3ubuntu13.5 status=ii\n".
- web-02 (`2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`): `result` is "verdict=affected package=openssh-server release=noble installed=1:9.6p1-3ubuntu13.4 fixed=1:9.6p1-3ubuntu13.5 status=hi\n".
