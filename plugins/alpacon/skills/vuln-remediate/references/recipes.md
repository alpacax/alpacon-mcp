# Recipes

A recipe is the script `execute_file` runs. Whoever writes it, it must:

- Be idempotent: on a server already at the fixed version it changes nothing and exits 0.
- Exit non-zero when anything fails (`set -eu`), so the first server's failure stops the rollout.
- Print the installed version before and after, so the report and `vuln-verify` can read it.
- Run no restart, reboot, or configuration edit itself. Restarts are a person's decision, and `vuln-verify` lists which ones are needed.
- Carry no password or token. `execute_file` refuses inline credentials; read them from a file on the host if the upgrade needs one.

A package's own upgrade script may still restart its service (`openssh-server` on Debian and the `openssh-server` RPM both restart `sshd`). The recipe cannot prevent that; tell the person when you show it.

## Debian and Ubuntu

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

- `--only-upgrade` never installs the package on a server that lacks it.
- `NEEDRESTART_MODE=l` keeps `needrestart` (default on Ubuntu 22.04 and later) to listing services instead of restarting them.
- `--force-confold` keeps the server's edited configuration files instead of stopping to ask.
- `DPkg::Lock::Timeout` waits for an unattended upgrade that holds the lock instead of failing at once.

Running as an ordinary account with `sudo`, put the environment on the `sudo` line, because `sudo` resets it: `sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install ...`, and `sudo apt-get update -q`.

## RHEL, Rocky, AlmaLinux, Fedora

```bash
#!/bin/bash
set -eu
pkg=openssh-server
echo "before=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$pkg")"
dnf -y -q upgrade --cve CVE-2026-109618
echo "after=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$pkg")"
```

`--cve` upgrades the installed packages that the advisories fixing this CVE cover, every binary from the source included, and nothing unrelated. They go to the newest version in the repositories, which can be later than the advisory's. A package name on that line narrows the upgrade to that one package and leaves its sibling binaries behind, so leave it off. With `sudo`, prefix `dnf` with it.

## The kernel

Install the fixed kernel the same way (`linux-image-<flavour>` or `kernel`). It takes effect only after a reboot, which this skill does not do; `vuln-verify` reports the server as needing one.

## pip, npm, and source builds

Pin the fixed version, run as the account that owns the application, and leave the restart out:

- pip: `/opt/app/.venv/bin/python -m pip install 'langflow==1.3.0'`
- npm: for a direct dependency, `cd /srv/app && npm install axios@1.7.4 --save-exact`. A transitive copy is not moved by that; it needs an `overrides` entry in `package.json` that the person agrees to, then `npm install`.
- Source build: check out and build the fixed tag the way the project's own deploy does. If you do not know how it is built, ask; do not guess a build command.

These upgrades can change the application's behavior beyond the fix. Say so when you show the recipe.
