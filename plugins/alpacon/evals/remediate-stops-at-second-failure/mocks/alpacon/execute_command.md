---
type: agent
abort_when: |
  - Any call targets web-03 (`9f3c1d7a-4e2b-4a68-b5c9-1d2e3f4a5b6c`).
  - A web-02 preview is submitted before web-01's execute_file call completed successfully.
  - The call omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: root`, uses a workspace other than `acme`, or explicitly gives a region other than `ap1`.
  - The command does anything other than a read-only apt-get simulation of the openssh-server upgrade.
---

Return one JSON object with the completed simulation for the requested server. Copy `server_id` from the call and map web-01 to `7c9e6679-7425-40de-944b-e07fc1f90ae7`, web-02 to `2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`, and web-03 to `9f3c1d7a-4e2b-4a68-b5c9-1d2e3f4a5b6c`. Use workspace `acme`, region `ap1`, and Work Session `5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10`.

Use `status: success`, `data.status: success`, `data.success: true`, and `data.exit_code: 0`. Include `data.server` with the requested server's id and name, `data.line` with the input command, and `data.result` with these exact lines:

```text
Inst openssh-client [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-sftp-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
```
