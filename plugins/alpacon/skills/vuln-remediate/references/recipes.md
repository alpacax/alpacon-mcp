# Recipes

A recipe is the script `execute_file` runs. Whoever writes it, it must:

- Be idempotent: on a server at or above the fixed version it changes nothing and exits 0. It never downgrades.
- Exit non-zero when anything fails (`set -eu`), so a failed run stops the rollout.
- Print the installed version before and after, so the report and `vuln-verify` can read it.
- Run no restart, reboot, or configuration edit itself. Restarts are a person's decision, and `vuln-verify` lists which ones are needed. A dependency manifest or lockfile the upgrade has to change is part of the upgrade, not configuration: name it when you show the recipe.
- Carry no password or token. `execute_file` refuses inline credentials; read them from a file on the host if the upgrade needs one.

A package's own maintainer scripts may still restart services, and the recipe cannot prevent that: `openssh-server` on Debian and the `openssh-server` RPM both restart `sshd`, and a library upgrade can restart every service that uses it. `dnf upgrade --cve` also upgrades every installed package the CVE's advisories cover, which can install a new kernel. Tell the person both when you show the recipe, and preview the upgrade on the first server before it runs:

- Debian and Ubuntu: `LC_ALL=C apt-get -s -q install --only-upgrade <pkg>`. `-s` only simulates and works as an ordinary account; the `Inst` and `Remv` lines are what the run would change.
- RHEL family: `dnf -q --assumeno upgrade --cve <CVE>`, as root or with `sudo`. It resolves the transaction, prints it, and answers no; the command exits 1 by design.
- pip: `<python> -m pip install --dry-run '<pkg>>=<fixed>'` (pip 22.2 or later) lists what would be installed.
- npm: `npm install --dry-run <pkg>@<fixed>` in the application directory.
- Source build: no preview exists; show the build steps instead, and say what they replace.

Previews do not lock out other package managers: arrange an exclusive maintenance window with the person before upgrading, and stop if another upgrade is active. A package the preview would remove, or a kernel the person did not expect, is a reason to stop before the recipe runs. The recipe refreshes the package lists itself, which can change the transaction after the preview. Before the final recipe review, copy the approved preview's complete `Inst` and `Remv` lines into `approved_changes` below, in their original order; the placeholder deliberately fails closed. After `apt-get update`, the Debian recipe requires a successful simulation with exactly those changes and no removals. Any difference needs a new preview and recipe review before retrying.

## Debian and Ubuntu

```bash
#!/bin/bash
set -eu
pkg=openssh-server
approved_changes='COPY THE APPROVED Inst AND Remv LINES HERE'
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
  awk -v p="$pkg-" 'index($3, p) == 1 && substr($3, length(p)+1, 1) ~ /[0-9]/ {found=1} END {exit !found}' <<<"$list"
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
- npm: use the guard below before `npm install axios@1.7.4 --save-exact` for a direct dependency. It refuses versions outside plain numeric releases instead of ordering prereleases with `sort -V`. Installation edits `package.json` and the lockfile. A transitive copy is not moved by it; it needs an `overrides` entry in `package.json`. Show the manifest change with the recipe.
- Source build: check out and build the fixed tag the way the project's own deploy does. If you do not know how it is built, ask; do not guess a build command.

These upgrades can change the application's behavior beyond the fix. Say so when you show the recipe.

For a direct npm dependency, this complete recipe leaves a fixed install alone and checks the version after installation. A prerelease or another version it cannot order fails before npm runs:

```bash
#!/bin/bash
set -eu
cd /srv/app
fixed=1.7.4
state() {
  node -e 'const [v, f] = process.argv.slice(1); const k = s => { if (!/^[0-9]+(\.[0-9]+)*$/.test(s)) throw Error("unorderable-version"); return s.split(".").map(BigInt); }; const V = k(v), F = k(f); let lower = false; for (let i = 0; i < Math.max(V.length, F.length); i++) { const a = V[i] || 0n, b = F[i] || 0n; if (a !== b) { lower = a < b; break; } } console.log(lower ? "upgrade" : "fixed");' "$1" "$fixed"
}
before=$(node -p "require('axios/package.json').version")
echo "before=$before"
s=$(state "$before") || exit 1
if [ "$s" = fixed ]; then
  echo "after=$before"
  exit 0
fi
npm install "axios@$fixed" --save-exact
after=$(node -p "require('axios/package.json').version")
echo "after=$after"
[ "$(state "$after")" = fixed ]
```
