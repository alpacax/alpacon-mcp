# Recipes

A recipe is the script `execute_file` runs. Whoever writes it, it must:

- Be idempotent: on a server at or above the fixed version it changes nothing and exits 0. It never downgrades.
- Exit non-zero when anything fails (`set -eu`), so a failed run stops the rollout.
- Print the installed version before and after, so the report and `vuln-verify` can read it.
- Run no restart, reboot, or configuration edit itself. Restarts are a person's decision, and `vuln-verify` lists which ones are needed. A dependency manifest or lockfile the upgrade has to change is part of the upgrade, not configuration: name it when you show the recipe.
- Carry no password or token. `execute_file` refuses inline credentials; read them from a file on the host if the upgrade needs one.

A package's own maintainer scripts may still restart services, and the recipe cannot prevent that: `openssh-server` on Debian and the `openssh-server` RPM both restart `sshd`, and a library upgrade can restart every service that uses it. `dnf upgrade --cve` also upgrades every installed package the CVE's advisories cover, which can install a new kernel. Tell the person both when you show the recipe, and preview the upgrade on the first server before it runs:

- Debian and Ubuntu: `LC_ALL=C apt-get -s -q install --only-upgrade <pkg>`. `-s` only simulates and works as an ordinary account; the `Inst` and `Remv` lines are what the run would change. Send it inside the preflight block below.
- RHEL family: `dnf --assumeno upgrade --cve <CVE>`, as root or with `sudo`. It resolves the transaction, prints it, and answers no; the command exits 1 by design. Send it inside the preflight block below, which leaves out `-q` because `-q` hides the size lines.
- pip: `<python> -m pip install --dry-run '<pkg>>=<fixed>'` (pip 22.2 or later) lists what would be installed.
- npm: `npm install --dry-run <pkg>@<fixed>` in the application directory.
- Source build: no preview exists; show the build steps instead, and say what they replace.

Previews do not lock out other package managers: arrange an exclusive maintenance window with the person before upgrading, and stop if another upgrade is active. A package the preview would remove, or a kernel the person did not expect, is a reason to stop before the recipe runs. The recipe refreshes the package lists itself, which can change the transaction after the preview. Before the final recipe review, copy the approved preview's complete `Inst` and `Remv` lines into `approved_changes` below, in their original order; the placeholder deliberately fails closed. After `apt-get update`, the Debian recipe requires a successful simulation with exactly those changes and no removals. Any difference needs a new preview and recipe review before retrying.

## Preflight

For a Debian or RHEL-family package, read each server's state in the same `execute_command` call as its preview: send the block for the distribution below, unchanged except for `pkg` or `cve` (and `sudo` before `dnf` on the `sudo` route), as the preview's account. It prints one `key=value` line per fact, then the preview's own output, and exits with the preview's status. Every value is read-only.

- `transaction`: `changes` (on Debian, any `Inst`, `Conf` or `Remv` line, so a package left unconfigured counts), `empty` when the preview would change nothing, or `unreadable` when the preview failed.
- `disk_free_<fs>` and `disk_need_<fs>`: KiB free on each filesystem holding `/`, `/usr`, `/var` and the package cache (`Dir::Cache::archives` for apt, `/var/cache/libdnf5` or `/var/cache/dnf` for dnf), and `/boot` when a kernel is in the transaction,, named by the mount point of the first path on it (`root`, `usr`, `var`, `boot`); paths on one filesystem share one set of keys: those whose `df` source is the same `/dev` device (Btrfs subvolumes of one pool included), or, for a source outside `/dev` such as `tmpfs`, the same device number (bind mounts included), and the KiB the transaction adds there. The download lands on the one holding the package cache and the installed-size growth on the one holding `/usr`; when they are one filesystem, the two add up. The growth includes what a kernel puts on `/boot`, so on a server with a separate `/boot` the need shown for `/usr` is an upper bound, and a shortfall there can be a false alarm the person clears. `unknown` marks a size the package manager never reports, such as the growth under dnf 4 (RHEL 8 to 10), which prints only the download size, and nothing is judged on it. dnf 4 prints only `Total size`, with no download line, when every package is already cached, and the download is then 0.
- `inode_free_<fs>`: free inodes, or `n/a` on a filesystem without a fixed count, such as btrfs.
- `mount_<fs>`: `rw` or `ro`, or `unreadable` when `/proc/mounts` cannot be read.
- `units`, `kubelet` and `mem_available`: the systemd services the transaction's packages ship in their installed version, whether `kubelet` runs, and `MemAvailable` in KiB. They are shown to the person and never judged. `units` lists what the packages ship now, not what the new version adds or what their scripts will restart, which no preview can tell; a package the transaction newly installs contributes nothing.
- `anomaly`: `none`, or what is wrong as a matter of fact: `dpkg_audit` (`dpkg --audit` reports an interrupted run), `ro_<fs>`, `inode_<fs>` (no free inode) or `disk_<fs>` (less free space than the transaction adds there, or none at all, which counts even where the size is `unknown`).
- `unreadable`: `none`, or a judged value that should have been read and was not, such as `disk_need_<fs>` when the size line is missing or `transaction` when the preview failed.

No anomaly needs a floor or a percentage; each is a fact about this server and this transaction. The package manager's lock is not read: the Debian recipe waits for it (`DPkg::Lock::Timeout`), and a lock held now may be gone when the recipe runs. dnf has no cheap check for an interrupted transaction, so the RPM block has no counterpart to `dpkg_audit`. Whether the server is a database primary or one half of an HA pair needs credentials or knowledge the block does not have: ask the person.

Debian and Ubuntu, as an ordinary account or root:

```sh
pkg=openssh-server
sim=$(LC_ALL=C apt-get -s -q install --only-upgrade "$pkg"); rc=$?
uris=$(LC_ALL=C apt-get -q --print-uris -y install --only-upgrade "$pkg") || uris=failed
inst=$(printf '%s\n' "$sim" | awk '/^(Inst|Conf|Remv) / {print $2}' | sort -u)
eval "$(apt-config shell cache Dir::Cache::archives/d 2>/dev/null)"; cache=${cache%/}; [ -n "$cache" ] || cache=/var/cache/apt/archives
transaction=empty anomaly= unreadable= paths="/ /usr /var $cache"
if [ "$rc" -ne 0 ]; then transaction=unreadable unreadable=transaction; elif printf '%s\n' "$sim" | grep -Eq '^(Inst|Conf|Remv) '; then transaction=changes; fi
audit=$(dpkg --audit 2>/dev/null) || [ -n "$audit" ] || unreadable="$unreadable dpkg_audit"
[ -z "$audit" ] || anomaly=dpkg_audit
if printf '%s\n' "$inst" | grep -Eq '^linux-(image|modules)-'; then paths="$paths /boot"; fi
sizes=$(printf '%s\n' "$uris" | awk -v t="$transaction" -v q="'" '
  $0 == "failed" { bad = 1 }
  index($0, q) == 1 { dl += $3 }
  /^After this operation,? / { n = split("B kB MB GB TB", u, " "); for (i = 1; i <= n; i++) if (u[i] == $5) m = 1000 ^ (i - 1); delta = (/freed/ ? 0 : (m ? $4 * m : "?")) }
  END { if (bad) { print "? ?"; exit } if (delta == "") delta = (t == "changes" ? "?" : 0)
        printf "%d %s\n", (dl + 1023) / 1024, (delta == "?" ? "?" : int((delta + 1023) / 1024)) }')
printf 'transaction=%s\n' "$transaction"
printf 'units=%s\n' "$(for p in $inst; do dpkg -L "$p" 2>/dev/null; done | sed -n 's|.*/systemd/system/\([^/]*\.service\)$|\1|p' | sort -u | paste -sd, -)"
printf 'kubelet=%s\n' "$(systemctl is-active kubelet 2>/dev/null)"
printf 'mem_available=%s\n' "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null)"
for p in $paths; do
  d=$(stat -L -c %d "$p" 2>/dev/null); i=$(df -Pi "$p" 2>/dev/null | awk 'NR == 2 {print $2, $4}')
  printf '%s %s %s %s\n' "$p" "${d:-?}" "${i:-? ?}" "$(df -Pk "$p" 2>/dev/null | awk 'NR == 2 {m = $6; for (f = 7; f <= NF; f++) m = m " " $f; print $1, $4, m}')"
done | awk -v sizes="$sizes" -v a="$anomaly" -v u="$unreadable" -v mf=/proc/mounts -v cache="$cache" '
  function label(m) { m = substr(m, 2); gsub(/[^A-Za-z0-9]/, "_", m); return (m == "" ? "root" : m) }
  function need(m, v) { if (v == "unknown") unk[m] = 1; else if (v !~ /^[0-9]+$/) bad[m] = 1; else { sum[m] += v; known[m] = 1 } }
  BEGIN { split(sizes, s, " "); while ((getline line < mf) > 0) { split(line, w, " "); gsub(/\\040/, " ", w[2]); opt[w[2]] = w[4] } }
  seen[$1]++ { next }
  NF < 7 || $6 !~ /^[0-9]+$/ { u = u " disk_" label($1); next }
  { k = $7; for (f = 8; f <= NF; f++) k = k " " $f
    if ($5 ~ /^\/dev\//) m = $5; else if ($2 != "?") m = $2; else { m = "mount " k; u = u " disk_" label($1) }
    if (!(m in free)) { order[++n] = m; name[m] = k; free[m] = $6 + 0; inodes[m] = $3; ifree[m] = $4 }
    if (!(k in opt)) mbad[m] = 1; else if (("," opt[k] ",") ~ /,ro,/) mro[m] = 1
    if ($1 == cache) need(m, s[1]); if ($1 == "/usr") need(m, s[2]) }
  END {
    for (i = 1; i <= n; i++) {
      m = order[i]; l = label(name[m]); v = known[m] ? sum[m] : ""
      if (bad[m]) { v = v (v == "" ? "" : "+") "unreadable"; u = u " disk_need_" l } else if (unk[m] || !known[m]) v = v (v == "" ? "" : "+") "unknown"
      print "disk_free_" l "=" free[m]; print "disk_need_" l "=" v
      if ((known[m] && free[m] < sum[m]) || free[m] == 0) a = a " disk_" l
      if (inodes[m] == "?") { print "inode_free_" l "=unreadable"; u = u " inode_" l } else if (inodes[m] ~ /^[1-9][0-9]*$/) { print "inode_free_" l "=" ifree[m]; if (ifree[m] == 0) a = a " inode_" l } else print "inode_free_" l "=n/a"
      if (mbad[m]) { print "mount_" l "=unreadable"; u = u " mount_" l } else if (mro[m]) { print "mount_" l "=ro"; a = a " ro_" l } else print "mount_" l "=rw"
    }
    $0 = a; $1 = $1; gsub(" ", ","); print "anomaly=" ($0 == "" ? "none" : $0)
    $0 = u; $1 = $1; gsub(" ", ","); print "unreadable=" ($0 == "" ? "none" : $0)
  }'
printf '%s\n' "$sim"
exit "$rc"
```

RHEL, Rocky, AlmaLinux and Fedora, as root (prefix `dnf` with `sudo` on the `sudo` route):

```sh
cve=CVE-2099-0001
sim=$(LC_ALL=C dnf --assumeno upgrade --cve "$cve" 2>&1); rc=$?
inst=$(printf '%s\n' "$sim" | awk '$2 ~ /^(x86_64|aarch64|noarch|i686|ppc64le|s390x)$/ {print $1}')
cache=/var; for c in /var/cache/libdnf5 /var/cache/dnf; do if [ -d "$c" ]; then cache=$c; break; fi; done
transaction=unreadable anomaly= unreadable=transaction paths="/ /usr /var $cache"
if [ -n "$inst" ]; then transaction=changes unreadable=; elif printf '%s\n' "$sim" | grep -q '^Nothing to do'; then transaction=empty unreadable=; fi
if printf '%s\n' "$inst" | grep -Eq '^kernel(-|$)'; then paths="$paths /boot"; fi
sizes=$(printf '%s\n' "$sim" | awk -v t="$transaction" '
  function kib(n, unit, i, k, u) { k = split("B KiB MiB GiB TiB", u, " "); for (i = 1; i <= k; i++) if (u[i] == unit) return int((n * 1024 ^ (i - 1) + 1023) / 1024)
    k = split("k M G T", u, " "); for (i = 1; i <= k; i++) if (u[i] == unit) return int(n * 1024 ^ (i - 1) + 0.999); return (unit == "" ? int((n + 1023) / 1024) : "?") }
  /^Total download size: / { dl = kib($4, $5) } /^Total size: / { total = 1 }
  /^Total size of inbound packages is / { five = 1; u = $13; sub(/\.$/, "", u); dl = kib($12, u) }
  /^After this operation,? / { delta = (/freed/ ? 0 : kib($4, $5)) }
  END { if (t != "changes") { print "0 0"; exit } if (dl == "") dl = (total ? 0 : "?"); if (delta == "") delta = (five ? "?" : "unknown"); print dl, delta }')
printf 'transaction=%s\n' "$transaction"
printf 'units=%s\n' "$(for p in $inst; do rpm -ql "$p" 2>/dev/null; done | sed -n 's|.*/systemd/system/\([^/]*\.service\)$|\1|p' | sort -u | paste -sd, -)"
printf 'kubelet=%s\n' "$(systemctl is-active kubelet 2>/dev/null)"
printf 'mem_available=%s\n' "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null)"
for p in $paths; do
  d=$(stat -L -c %d "$p" 2>/dev/null); i=$(df -Pi "$p" 2>/dev/null | awk 'NR == 2 {print $2, $4}')
  printf '%s %s %s %s\n' "$p" "${d:-?}" "${i:-? ?}" "$(df -Pk "$p" 2>/dev/null | awk 'NR == 2 {m = $6; for (f = 7; f <= NF; f++) m = m " " $f; print $1, $4, m}')"
done | awk -v sizes="$sizes" -v a="$anomaly" -v u="$unreadable" -v mf=/proc/mounts -v cache="$cache" '
  function label(m) { m = substr(m, 2); gsub(/[^A-Za-z0-9]/, "_", m); return (m == "" ? "root" : m) }
  function need(m, v) { if (v == "unknown") unk[m] = 1; else if (v !~ /^[0-9]+$/) bad[m] = 1; else { sum[m] += v; known[m] = 1 } }
  BEGIN { split(sizes, s, " "); while ((getline line < mf) > 0) { split(line, w, " "); gsub(/\\040/, " ", w[2]); opt[w[2]] = w[4] } }
  seen[$1]++ { next }
  NF < 7 || $6 !~ /^[0-9]+$/ { u = u " disk_" label($1); next }
  { k = $7; for (f = 8; f <= NF; f++) k = k " " $f
    if ($5 ~ /^\/dev\//) m = $5; else if ($2 != "?") m = $2; else { m = "mount " k; u = u " disk_" label($1) }
    if (!(m in free)) { order[++n] = m; name[m] = k; free[m] = $6 + 0; inodes[m] = $3; ifree[m] = $4 }
    if (!(k in opt)) mbad[m] = 1; else if (("," opt[k] ",") ~ /,ro,/) mro[m] = 1
    if ($1 == cache) need(m, s[1]); if ($1 == "/usr") need(m, s[2]) }
  END {
    for (i = 1; i <= n; i++) {
      m = order[i]; l = label(name[m]); v = known[m] ? sum[m] : ""
      if (bad[m]) { v = v (v == "" ? "" : "+") "unreadable"; u = u " disk_need_" l } else if (unk[m] || !known[m]) v = v (v == "" ? "" : "+") "unknown"
      print "disk_free_" l "=" free[m]; print "disk_need_" l "=" v
      if ((known[m] && free[m] < sum[m]) || free[m] == 0) a = a " disk_" l
      if (inodes[m] == "?") { print "inode_free_" l "=unreadable"; u = u " inode_" l } else if (inodes[m] ~ /^[1-9][0-9]*$/) { print "inode_free_" l "=" ifree[m]; if (ifree[m] == 0) a = a " inode_" l } else print "inode_free_" l "=n/a"
      if (mbad[m]) { print "mount_" l "=unreadable"; u = u " mount_" l } else if (mro[m]) { print "mount_" l "=ro"; a = a " ro_" l } else print "mount_" l "=rw"
    }
    $0 = a; $1 = $1; gsub(" ", ","); print "anomaly=" ($0 == "" ? "none" : $0)
    $0 = u; $1 = $1; gsub(" ", ","); print "unreadable=" ($0 == "" ? "none" : $0)
  }'
printf '%s\n' "$sim"
exit "$rc"
```

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
cve='CVE-2099-0001'
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
