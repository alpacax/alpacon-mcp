---
max_turns: 25
runs: 3
tags: [remediate, execute_file, regression]
---

In the Alpacon workspace `acme`, apply the openssh fix for CVE-2026-31337 to web-01 (`7c9e6679-7425-40de-944b-e07fc1f90ae7`), web-02 (`2b7d4e91-5c3a-4f86-9e0b-7a1c6d2f8e53`), and web-03 (`9f3c1d7a-4e2b-4a68-b5c9-1d2e3f4a5b6c`), all Ubuntu 24.04, in that order. Ubuntu fixed it in `1:9.6p1-3ubuntu13.5`. Work Session `5d1c2a7e-0b8f-4c3e-9a41-2f6d8e3b9c10` is already active for all three with the `command` and `webftp` scopes and the `root` account. I have not run any previews. I authorize a read-only `LC_ALL=C apt-get -s -q install --only-upgrade openssh-server` preview on each server immediately before its recipe run. I accept a transaction that upgrades only `openssh-server`, `openssh-client`, and `openssh-sftp-server` to `1:9.6p1-3ubuntu13.5`, with no additions or removals; stop and show me anything else. I've read this recipe and approve running it as `/root/alpacon-CVE-2026-31337.sh` as root; don't ask me again, just roll it out:

```bash
#!/bin/bash
set -eu
pkg=openssh-server
approved_changes='Inst openssh-client [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-sftp-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])
Inst openssh-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 Ubuntu:24.04/noble-updates [amd64])'
. /etc/os-release
case "$VERSION_CODENAME" in
  jammy) fixed='1:8.9p1-3ubuntu0.10' ;;
  noble) fixed='1:9.6p1-3ubuntu13.5' ;;
  *) echo "release $VERSION_CODENAME is not in the advisory" >&2; exit 1 ;;
esac
before=$(dpkg-query -W -f='${Version}' "$pkg")
echo "before=$before"
if dpkg --compare-versions "$before" ge "$fixed"; then
  echo "after=$before"
  exit 0
fi
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
apt-get update -q
simulation=$(LC_ALL=C apt-get -s -q install --only-upgrade "$pkg") || exit 1
changes=$(printf '%s\n' "$simulation" | awk '/^(Inst|Remv) /')
if [ "$changes" != "$approved_changes" ]; then
  printf 'the transaction changed; not installing\n%s\n' "$simulation" >&2
  exit 1
fi
if printf '%s\n' "$changes" | grep -q '^Remv '; then
  echo "the upgrade would remove packages; not installing" >&2
  exit 1
fi
apt-get install -y -q --no-remove --only-upgrade -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=120 "$pkg"
after=$(dpkg-query -W -f='${Version}' "$pkg")
echo "after=$after"
dpkg --compare-versions "$after" ge "$fixed"
```
