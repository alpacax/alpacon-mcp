---
type: agent
abort_when: |
  - The call targets anything other than web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`), omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: ubuntu`, or uses a workspace other than `acme`.
  - The command is not the compromise-log-check skill's search script (it holds `END-OF-LOG` and `gzip -dc`), filled with `logs='/var/log/nginx/access.log'`.
  - A pairing run's `also` value is not the address with `^` before it and a space after it.
  - The command writes, copies or deletes a file, or uses sudo.
---

You play the Alpacon MCP server's `execute_command_multi_server` tool. Answer with one JSON object only, no prose. Pick the command id from the `patterns` and `also` values at the top of the command:

- `patterns` holds `reset_password` and `also` is empty: `4b7d9e21-3c5a-4f68-9d0e-8a1b2c3d4e5f`
- `patterns` holds `user/current` and `also` holds `198.51.100.44`: `5c8e0f32-4d6b-4a79-8e1f-9b2c3d4e5f60`
- `patterns` holds `user/current` and `also` holds `203.0.113.9`: `6d9f1a43-5e7c-4b8a-9f20-ac3d4e5f6071`

{"status": "success", "deploy_shell_results": {"7c9e6679-7425-40de-944b-e07fc1f90ae7": {"status": "success", "data": {"id": "<command id>"}, "command_id": "<command id>"}}, "total_servers": 1, "successful_count": 1, "failed_count": 0, "execution_type": "parallel", "region": "ap1", "workspace": "acme"}
