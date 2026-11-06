# Recipes

A recipe is the script `execute_file` runs. Whoever writes it, it must:

- Be idempotent: on a server already at the fixed version it changes nothing and exits 0. A run that stopped partway can then simply run again.
- Exit non-zero when anything fails (`set -eu`), so the first server's failure stops the rollout.
- Print the installed version before and after, so the report and `vuln-verify` can read it.
- Not restart services, reboot, or edit configuration. Restarts are a person's decision, and `vuln-verify` lists which ones are needed.
- Carry no password or token. `execute_file` refuses inline credentials; read them from a file on the host if the upgrade needs one.

## Debian and Ubuntu

```bash
#!/bin/bash
set -eu
pkg=openssh-server
echo "before=$(dpkg-query -W -f='${Version}' "$pkg")"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
apt-get update -q
apt-get install -y -q --only-upgrade -o Dpkg::Options::=--force-confold "$pkg"
echo "after=$(dpkg-query -W -f='${Version}' "$pkg")"
```

- `--only-upgrade` never installs the package on a server that lacks it.
- `NEEDRESTART_MODE=l` keeps `needrestart` (default on Ubuntu 22.04 and later) to listing services instead of restarting them.
- `--force-confold` keeps the server's edited configuration files instead of stopping to ask.
- A package's own maintainer script may still restart its service on upgrade (`openssh-server` restarts `ssh`). That is the package's behavior; mention it to the person when you show the recipe.

## RHEL, Rocky, AlmaLinux, Fedora

```bash
#!/bin/bash
set -eu
pkg=openssh-server
echo "before=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$pkg")"
dnf -y -q upgrade --cve CVE-2026-109618 "$pkg"
echo "after=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$pkg")"
```

`--cve` limits the upgrade to the advisory that fixes this CVE, so the run does not pull in unrelated updates.

## The kernel

Install the fixed kernel the same way (`linux-image-<flavour>` or `kernel`). It takes effect only after a reboot, which this skill does not do; `vuln-verify` reports the server as needing one.

## pip, npm, and source builds

Pin the fixed version, run as the account that owns the application, and leave the restart out:

- pip: `/opt/app/.venv/bin/python -m pip install 'langflow==1.3.0'`
- npm: for a direct dependency, `cd /srv/app && npm install mcp-atlassian@0.11.10 --save-exact`. A transitive copy is not moved by that; it needs an `overrides` entry in `package.json` that the person agrees to, then `npm install`.
- Source build: check out and build the fixed tag the way the project's own deploy does. If you do not know how it is built, ask; do not guess a build command.

These upgrades can change the application's behavior beyond the fix. Say so when you show the recipe.
