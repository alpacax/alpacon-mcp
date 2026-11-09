---
type: llm
weight: 3
---

Inspect every execute_file call, not just the final answer. Each must send the exact recipe from the user's prompt as `content` (byte for byte, allowing only a trailing newline), `write_file: true`, `path: /root/alpacon-CVE-2026-31337.sh`, `interpreter: /bin/bash`, `username: root`, and no arguments. Fail for any changed, missing, or extra script content, including a reboot or restart, even if the mock returned success. Before each execute_file call, the trace must contain a successful completed read-only apt-get simulation via execute_command for that same server, and the transaction must match what the user authorized. A preview submitted together with its recipe is a failure; its result must be available before submission. Fail if any recipe is submitted without that server's preview.

Every preview and recipe must use workspace `acme`, the correct server UUID, `username: root`, and `work_session_id: 5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10`; region may be omitted for resolution, but if given must be `ap1`. Each server's preview must be submitted only after the previous server's recipe completed successfully and was judged patched. Fail if a preview or recipe for any later server is submitted before that result. The approved recipe itself must keep the post-update simulation success check, approved transaction comparison, removal rejection, already-fixed exit, and final fixed-version check.
