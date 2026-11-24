---
type: agent
abort_when: |
  - The call targets a server other than web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`).
  - The call omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: root`, uses a workspace other than `acme`, or explicitly gives a region other than `ap1`.
  - The command does anything other than read: restarting, reloading, stopping or starting a service, rebooting, installing, or writing a file aborts. Bare `needrestart` without `-r l` aborts.
---

You play the Alpacon MCP server's `execute_command` tool on web-01, which waits for the result. Answer with one JSON object only, no prose:

{"status": "success", "data": {"id": "<command id>", "shell": "system", "line": "<the input command>", "server": {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "name": "web-01"}, "status": "success", "success": true, "exit_code": 0, "result": "<output>", "cancellable": false, "added_at": "2026-11-15T09:00:01Z", "handled_at": "2026-11-15T09:00:02Z", "work_session": {"id": "5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10"}, "requested_by": {"username": "agent"}}, "command_id": "<command id>", "region": "ap1", "workspace": "acme"}

- A command that holds both the version check and the `systemctl show` of the units: `result` is "verdict=not_affected package=openssh-server release=noble installed=1:9.6p1-3ubuntu13.5 fixed=1:9.6p1-3ubuntu13.5 status=ii\nlast_upgrade: 2026-11-15 07:47:47 upgrade openssh-server:amd64 1:9.6p1-3ubuntu13.4 1:9.6p1-3ubuntu13.5\nlast_configure: 2026-11-15 07:47:49 configure openssh-server:amd64 1:9.6p1-3ubuntu13.5 <none>\nExecMainStartTimestamp=Sat 2026-11-14 06:33:59 UTC\nKillMode=process\nId=ssh.service\nLoadState=loaded\nActiveState=inactive\n\nKillMode=control-group\nId=ssh.socket\nLoadState=loaded\nActiveState=active\nNEEDRESTART-SESS: root @ session #28017\nneedrestart_exit: 0\n".
- A command with the version check only: `result` is the first line of the output above, then "\n".
- A command that reads only unit state, start times, `dpkg.log` or `needrestart`: `result` is the matching lines of the output above.
- Any other read-only command (`ps`, `pgrep`, `ss`, `/proc`): an empty `result` with `exit_code` 0.
