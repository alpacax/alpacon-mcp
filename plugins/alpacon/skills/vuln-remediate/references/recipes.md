# Recipes

A recipe is the script `execute_file` runs. Whoever writes it, it must:

- Be idempotent: on a server at or above the fixed version it changes nothing and exits 0. It never downgrades.
- Exit non-zero when anything fails (`set -eu`), so the first server's failure stops the rollout.
- Print the installed version before and after, so the report and `vuln-verify` can read it.
- Run no restart, reboot, or configuration edit itself. Restarts are a person's decision, and `vuln-verify` lists which ones are needed. A dependency manifest or lockfile the upgrade has to change is part of the upgrade, not configuration: name it when you show the recipe.
- Carry no password or token. `execute_file` refuses inline credentials; read them from a file on the host if the upgrade needs one.

A package's own upgrade script may still restart its service (`openssh-server` on Debian and the `openssh-server` RPM both restart `sshd`). The recipe cannot prevent that; tell the person when you show it.

## Debian and Ubuntu

```bash
#!/bin/bash
set -eu
pkg=openssh-server
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
apt-get install -y -q --only-upgrade -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=120 "$pkg"
after=$(dpkg-query -W -f='${Version}' "$pkg")
echo "after=$after"
dpkg --compare-versions "$after" ge "$fixed"
```

- The early exit keeps a rerun from touching a server that is already fixed: `apt-get` alone would move it to any newer candidate.
- The last line fails the run when the upgrade did not reach the fix, such as a mirror that lacks it: `apt-get` exits 0 with nothing to upgrade.
- `--only-upgrade` never installs the package on a server that lacks it.
- `NEEDRESTART_MODE=l` keeps `needrestart` (default on Ubuntu 22.04 and later) to listing services instead of restarting them.
- `--force-confold` keeps the server's edited configuration files instead of stopping to ask.
- `DPkg::Lock::Timeout` waits for an unattended upgrade that holds the lock instead of failing at once.

Running as an ordinary account with `sudo`, put the environment on the `sudo` line, because `sudo` resets it: `sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install ...`, and `sudo apt-get update -q`.

## RHEL, Rocky, AlmaLinux, Fedora

```bash
#!/bin/bash
set -eu
cve='CVE-2026-109618'
pkg=openssh-server
pending() {
  local list
  list=$(dnf -q updateinfo list --available --cve "$cve") || exit 1
  awk '{print $3}' <<<"$list" | grep -q "^$pkg-[0-9]"
}
before=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$pkg")
echo "before=$before"
if ! pending; then
  echo "after=$before"
  exit 0
fi
dnf -y -q upgrade --cve "$cve"
echo "after=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$pkg")"
! pending
```

- The early exit leaves a server alone when no fixing advisory is pending for the package, so a rerun does not move it to a newer build. A repository without update metadata also takes this exit, so check that `after` shows the fixed version.
- The last line fails the run when the advisory is still pending after the upgrade.

`--cve` upgrades the installed packages that the advisories fixing this CVE cover, every binary from the source included, and nothing unrelated. They go to the newest version in the repositories, which can be later than the advisory's. A package name on that line narrows the upgrade to that one package and leaves its sibling binaries behind, so leave it off. With `sudo`, prefix `dnf` with it.

## The kernel

Install the fixed kernel the same way (`linux-image-<flavour>` or `kernel`). It takes effect only after a reboot, which this skill does not do; `vuln-verify` reports the server as needing one.

## pip, npm, and source builds

Ask for the fixed version as a floor, never an exact pin that could downgrade a newer install, run as the account that owns the application, and leave the restart out:

- pip: `/opt/app/.venv/bin/python -m pip install 'langflow>=1.3.0'`. pip leaves an install that already satisfies the floor untouched; below it, pip takes the newest release, so add a ceiling (`'langflow>=1.3.0,<1.4'`) when the person wants only the fix line.
- npm: check first and stop when the installed version is at or above the fix, `cd /srv/app && v=$(node -p "require('axios/package.json').version") && [ "$(printf '%s\n' 1.7.4 "$v" | sort -V | head -1)" = 1.7.4 ] && exit 0`, then `npm install axios@1.7.4 --save-exact` for a direct dependency. That edits `package.json` and the lockfile. A transitive copy is not moved by it; it needs an `overrides` entry in `package.json`. Show the manifest change with the recipe.
- Source build: check out and build the fixed tag the way the project's own deploy does. If you do not know how it is built, ask; do not guess a build command.

These upgrades can change the application's behavior beyond the fix. Say so when you show the recipe.
