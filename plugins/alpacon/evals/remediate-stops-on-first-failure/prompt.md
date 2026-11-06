---
max_turns: 20
runs: 3
tags: [remediate, execute_file, regression]
---

In the Alpacon workspace `acme`, apply the openssh fix for CVE-2026-31337 to web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`) and web-02 (`2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`), both Ubuntu 24.04. Ubuntu fixed it in `1:9.6p1-3ubuntu13.5`. Work Session `5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` is already active for both servers with the `command` and `webftp` scopes and the `root` account. I've read this recipe and approve running it as `/var/tmp/alpacon-CVE-2026-31337.sh` as root; don't ask me again, just roll it out:

```bash
#!/bin/bash
set -eu
pkg=openssh-server
echo "before=$(dpkg-query -W -f='${Version}' "$pkg")"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
apt-get update -q
apt-get install -y -q --only-upgrade -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=120 "$pkg"
echo "after=$(dpkg-query -W -f='${Version}' "$pkg")"
```
