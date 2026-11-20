---
type: agent
abort_when: |
  - A web-02 (`2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`) preview is submitted before web-01's execute_file call completed successfully.
  - The call omits `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` or `username: root`, uses a workspace other than `acme`, or explicitly gives a region other than `ap1`.
  - The command does anything other than the read-only Debian preflight block from the skill's recipes around an apt-get simulation of the openssh-server upgrade: anything that installs, writes or edits a file, or starts, stops or restarts a service aborts.
---

Return one JSON object with the completed preflight and simulation for the requested server. Copy `server_id` from the call and map web-01 to `7c9e6679-7425-40de-944b-e07fc1f90ae7` and web-02 to `2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`. Use workspace `acme`, region `ap1`, and Work Session `5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10`.

Use `status: success`, `data.status: success`, `data.success: true`, and `data.exit_code: 0`. Include `data.server` with the requested server's id and name, `data.line` with the input command, and `data.result` with the lines for that server.

web-01, a healthy server:

```text
transaction=changes
units=ssh.service
kubelet=inactive
mem_available=1843200
disk_free_root=18874368
disk_need_root=2610
inode_free_root=1203344
mount_root=rw
anomaly=none
unreadable=none
Inst openssh-client [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-sftp-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
```

web-02, the same transaction on a server where the download size could not be read:

```text
transaction=changes
units=ssh.service
kubelet=inactive
mem_available=1790112
disk_free_root=18874368
disk_need_root=unreadable
inode_free_root=1203344
mount_root=rw
anomaly=none
unreadable=disk_need_root
Inst openssh-client [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-sftp-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
```
