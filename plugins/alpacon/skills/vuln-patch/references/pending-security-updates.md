# Pending security updates

The path for a request that names no CVE or advisory: "any vulnerabilities on this server? fix them if so". It finds the distribution's pending security updates, applies the ones the person chooses, and verifies them. Follow the `using-alpacon` skill for workspaces, server UUIDs, Work Sessions, approvals, and multi-server results.

## What it covers

- Covered: Ubuntu, and Debian 11 and later: packages with a newer version in the distribution's own security suite (`<codename>-security`, Debian's `stable-security` and the like, and Ubuntu Pro's `<codename>-infra-security` and `<codename>-apps-security` where enabled). A third-party repository whose suite merely ends in `-security` does not count; one that reuses the distribution's own suite name is not told apart, since the check reads suite names, not repository origins.
- Not covered: software installed outside the package manager (vendor installs, source builds, container images), pip and npm packages, configuration, a vulnerability the distribution has not fixed yet, RHEL-family servers, distributions derived from Ubuntu or Debian (Linux Mint and the like), and Debian 10 or older, whose security suite (`buster/updates`) or extended-support archive the check does not recognize; those servers are `unknown` (not covered) in this version. Say so when you offer the path and again in the report. A server with nothing pending can still be vulnerable in any of these, so "nothing pending" never means "not vulnerable".

## Steps

1. Offer the path before anything runs: say what it covers and what it does not. If the person would rather name a CVE or advisory, go back to `vuln-diagnose` with it.
2. Call `list_servers` and sort the servers in scope as `vuln-diagnose` step 1 does. A RHEL-family server, a distribution derived from Ubuntu or Debian, or Debian 10 or older, is `unknown` (not covered); the rest are candidates.
3. Show the person [the check](#the-check) exactly as it will run, the servers, and the named non-root account it runs as, and wait for them to agree. In the same message, say that the check reads the package lists as they stand, without refreshing them, because an ordinary account cannot run `apt-get update` (its `lists_updated` line shows how current they are), and that the root preview before any upgrade refreshes them and may show more packages than the check.
4. Reuse a supplied active Work Session whose servers, `command` scope, and ordinary account cover the check, and leave it open afterwards. Otherwise open one for the candidates with the `command` scope only and `target_account_username` set to that account, with a description naming the check ("read pending security updates; changes nothing"), and close it once the results are read. Run the check once with `execute_command_multi_server`, passing that account as `username` and a `purpose` saying it only reads pending security updates, and read each server's result with `check_command_status`.
5. Show each server's result: `count`, then the `pkg=` lines, kernel updates first (every `kind=kernel` line, whatever its state) and the rest by state (upgrades, kept back, held, pinned), then `kernel_running` and `kernel_build`, `reboot_required` with `reboot_required_pkgs`, and `lists_updated`. A server whose check printed `count=unknown` is `unknown` with its reason. `count=0` means nothing was pending as of `lists_updated`.
6. Ask what to apply, as [Scope](#scope) describes. If the person chooses nothing, report and stop.
7. Remediate as `vuln-remediate` does, with the differences in [Remediate](#remediate), and tell it verify follows.
8. Go on as `vuln-patch` steps 4 to 6 do: stop and keep the Work Session while a run is `pending_approval` or unresolved, hand only the servers remediate reports `patched` to `vuln-verify`, as [Verify](#verify) describes, and close the session only if this task opened it.
9. Report as [Report](#report) describes.

## The check

Read-only, one call per server, as an ordinary account; nothing in it needs root:

```sh
export LC_ALL=C
if grep -q '^ID=debian$' /etc/os-release 2>/dev/null && grep -Eq '^VERSION_ID="?([1-9]|10)"?$' /etc/os-release; then echo "count=unknown reason=release-not-covered"; exit 0; fi
grep -Eq '^ID="?(ubuntu|debian)"?$' /etc/os-release 2>/dev/null || { echo "count=unknown reason=distribution-not-covered"; exit 0; }
codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release 2>/dev/null | tr -d '"')
[ -n "$codename" ] || { echo "count=unknown reason=no-codename"; exit 0; }
command -v apt-get >/dev/null 2>&1 || { echo "count=unknown reason=no-apt"; exit 0; }
up=$(apt list --upgradable 2>/dev/null) || { echo "count=unknown reason=apt-list-failed"; exit 0; }
sim=$(apt-get -s -q upgrade 2>/dev/null) || { echo "count=unknown reason=apt-get-simulation-failed"; exit 0; }
holds=$(apt-mark showhold 2>/dev/null) || { echo "count=unknown reason=apt-mark-failed"; exit 0; }
native=$(dpkg --print-architecture 2>/dev/null)
rows=$(printf '%s\n' "$up" | sed -n 's|^\([^/ ]*\)/\([^ ]*\) \([^ ]*\) \([^ ]*\) \[upgradable from: \([^]]*\)\]$|\1 \2 \3 \4 \5|p' | while read -r p suites cand arch cur; do
  case "$arch" in ("$native"|all) ;; (*) p=$p:$arch ;; esac
  case ",$suites," in
    (*,"$codename"-security,*|*,"$codename"-infra-security,*|*,"$codename"-apps-security,*|*,stable-security,*|*,oldstable-security,*|*,oldoldstable-security,*) r=reach ;;
    (*) r=none ;;
  esac
  m=$(apt-cache madison "$p" 2>/dev/null) || { echo "madison_failed=$p"; continue; }
  r=$(printf '%s\n' "$m" | awk -F '|' -v c="$codename" '$3 ~ (" (" c "(-infra|-apps)?|stable|oldstable|oldoldstable)-security/") {gsub(/ /, "", $2); print $2}' | { while read -r v; do if dpkg --compare-versions "$v" gt "$cand"; then r=beyond; elif [ "$r" = none ] && dpkg --compare-versions "$v" gt "$cur"; then r=reach; fi; done; echo "$r"; })
  [ "$r" != none ] || continue
  if printf '%s\n' "$holds" | grep -qxF -- "$p"; then state=held
  elif [ "$r" = beyond ]; then state=pinned
  elif printf '%s\n' "$sim" | awk -v p="$p" '$1 == "Inst" && $2 == p {f = 1} END {exit !f}'; then state=upgrade
  else state=kept_back; fi
  case "$p" in (linux-firmware*|linux-libc-dev*|linux-base|linux-sound-base|linux-doc*|linux-perf*|linux-cpupower*|linux-sysctl-defaults) kind=package ;; (linux-*) kind=kernel ;; (*) kind=package ;; esac
  echo "pkg=$p installed=$cur candidate=$cand state=$state kind=$kind"
done)
case "$rows" in (*madison_failed=*) echo "count=unknown reason=apt-cache-madison-failed"; exit 0 ;; esac
t=$(stat -c %Y /var/lib/apt/lists/*_dists_"$codename"-security_*Release /var/lib/apt/lists/*_dists_"$codename"-infra-security_*Release /var/lib/apt/lists/*_dists_"$codename"-apps-security_*Release /var/lib/apt/lists/*_dists_*stable-security_*Release 2>/dev/null | sort -n | head -n 1)
printf 'lists_updated=%s\n' "$(date -u -d "@${t:-none}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
printf 'kernel_running=%s\n' "$(uname -r)"
printf 'kernel_build=%s\n' "$(cat /proc/version_signature 2>/dev/null || uname -v)"
if [ -e /var/run/reboot-required ]; then echo reboot_required=yes; else echo reboot_required=no; fi
printf 'reboot_required_pkgs=%s\n' "$(sort -u /var/run/reboot-required.pkgs 2>/dev/null | paste -sd, -)"
[ -z "$rows" ] || printf '%s\n' "$rows"
printf '%s\n' "$rows" | awk '
  function val(f) { sub(/^[^=]*=/, "", f); return f }
  function add(k, p) { l[k] = l[k] (l[k] == "" ? "" : ",") p }
  /^pkg=/ { n++; add(val($4), val($1)); if (val($5) == "kernel") add("kernel", val($1)) }
  END { print "count=" n + 0; print "upgrade=" l["upgrade"]; print "kept_back=" l["kept_back"]; print "held=" l["held"]; print "pinned=" l["pinned"]; print "kernel=" l["kernel"] }'
```

It prints these lines, or `count=unknown reason=<why>` alone when a query failed, the server runs neither Ubuntu nor Debian, derived distributions such as Linux Mint included (`reason=distribution-not-covered`), `/etc/os-release` names no codename (`reason=no-codename`), or the server runs Debian 10 or older (`reason=release-not-covered`):

- `lists_updated`: the oldest timestamp among the `Release` files of the distribution's security lists, in UTC, or `unknown`. apt takes it from the archive and keeps it when a refresh finds nothing new, so it says how current the lists are, not when `apt-get update` last ran. Everything below is as of that time.
- `kernel_running` and `kernel_build`: the running kernel, and its build from `/proc/version_signature` on Ubuntu or `uname -v` elsewhere.
- `reboot_required`: `yes` when `/var/run/reboot-required` exists, so an earlier upgrade is already waiting for a reboot, with the packages that asked for it in `reboot_required_pkgs`. Debian writes the file only with `update-notifier-common` installed, so `no` there proves nothing.
- `pkg=`: one line per pending security update, with the installed and candidate versions, a `state`, and a `kind`. A package counts when its candidate comes from the security suite, or when the security suite holds a version newer than the installed one, since the candidate can be a later `-updates` build that carries the fix.
  - `state=upgrade`: `apt-get upgrade` would install it.
  - `state=kept_back`: `apt-get upgrade` keeps it back, because it needs a new package (an Ubuntu kernel update installs a new `linux-image-<abi>` package; a Debian one often keeps the ABI and is a plain `upgrade`), would remove one, or is deferred by phasing. `apt-get -s upgrade` prints no `Inst` line for it, so a check that reads only `Inst` lines reports such a server as having nothing pending.
  - `state=held`: someone marked it with `apt-mark hold`.
  - `state=pinned`: the security suite holds a fix newer than the candidate, which pinning or a priority keeps apt from choosing. Installing the candidate would not apply that fix. A package pinned at its installed version has no newer candidate, so `apt list --upgradable` never shows it and the check cannot list it.
  - `kind=kernel`: any `linux-*` package (images, headers, modules, tools, and every flavour's meta package, such as `linux-generic` or `linux-oem-24.04`) except firmware, `linux-libc-dev`, `linux-base`, `linux-sound-base`, documentation, `perf`, `cpupower`, and `linux-sysctl-defaults`; `kind=package` otherwise.
- A package installed for a foreign architecture is named with it (`libc6:i386`), as apt and dpkg name it.
- `count`: the number of `pkg=` lines, every state included. `upgrade`, `kept_back`, `held`, `pinned`, and `kernel` list the same packages by group, comma-separated.

## Scope

Ask one question for all servers, with each server's groups in front of the person:

- Everything: every `upgrade` and `kept_back` package, kernel included.
- Everything except the kernel: the same without `kind=kernel`.
- A chosen set: the packages the person names.

Held packages are shown and always left out, with the reason: a hold is someone's decision, and this path does not undo it. If the person wants a held package upgraded, they release the hold themselves, and the check runs again. Pinned packages are left out the same way: the fix needs the pin or priority changed, which is the person's decision too. Kernel updates are shown on their own, because they usually install new packages and always take effect only after a reboot, which this path never runs. Neither is applied without an explicit choice: "fix them if so" in the request is not one, so ask even then. A package name goes into a command as data: accept only names shaped `^[a-z0-9][a-z0-9.+-]+(:[a-z0-9]+)?$`, and ask about anything else.

## Remediate

Follow `vuln-remediate`, with these differences:

- Inputs: instead of a CVE and its fixed versions, the agreed packages on each server and the candidate versions its root preview shows. The Work Session description says "apply pending security updates" and names the packages, and that the recipe restarts nothing itself.
- Preview (its step 4): preview every target server before showing any recipe, with two `execute_command` calls per server. Before opening the remediation Work Session, show the person its account, scopes, and servers and the two commands below, and wait for them to agree; that agreement covers the previews, not the recipe. First, refresh the lists and run the check again: the line `apt-get -q update >/dev/null 2>&1 && echo refresh=ok || echo refresh=failed` followed by the check, unchanged. A security package the first check did not list, or a newer candidate, comes from the refreshed lists: show the difference and ask whether to add it to the scope. `refresh=failed` means the lists are still stale; show it and ask. Second, the Debian preflight block from [recipes.md](../../vuln-remediate/references/recipes.md#preflight) with `pkg` set to that server's agreed packages inside its single quotes, separated by spaces (`pkg='openssl libssl3t64'`). On `vuln-remediate`'s `sudo` route, put `sudo` before `apt-get` in the refresh line. A preview that removes a package, or upgrades one the person did not choose, is a reason to stop and show it; the new `linux-image-<abi>` and `linux-modules-<abi>` packages an agreed kernel update pulls in are expected, and are shown with it.
- Recipe: the [multi-package template](../../vuln-remediate/references/recipes.md#several-packages). Fill `targets` with one line per agreed package and the candidate version from that server's preview, and `approved_changes` with that preview's `Inst` and `Remv` lines, in order. Servers whose previews give the same `targets` and the same lines share one recipe; any other server gets its own. Within one recipe, every server runs the same file. A preview line holding a `'` cannot go inside the recipe's quotes: stop and show it.
- Agreement (its step 2): one message shows each server's list once (the agreed packages with their versions, the new packages the preview installs, and its preflight lines), each recipe byte for byte with the servers it runs on, the path (`/root/alpacon-security-updates.sh` as root; on the `sudo` route, an absolute path in the account's home directory, such as `/home/deploy/alpacon-security-updates.sh`, which `execute_file` requires; read the home directory from `getent passwd` when unsure), the account, and the scopes. One agreement covers every server; ask about a single server again only where `vuln-remediate`'s preflight rule says to.
- Run (its steps 5 to 7): one server at a time, each with its own recipe, `overwrite: true` when an earlier run left the file there, and a `purpose` of `pending security updates (<n> packages)` followed by that server's judged preflight keys. Do not preview again before each run: the recipe refreshes the lists, simulates the transaction, and refuses when it differs from what the person saw, which stops the rollout at that server, and later servers are `not_run`.
- Judge (its step 6): a run passes when it exited 0 and every `<pkg> after=` line is at or above that package's previewed version, which the recipe's last line checks.

## Verify

Hand the `patched` servers to `vuln-verify` in the same Work Session and as the same account, with the check above and the applied packages and their previewed versions. Its [Pending security updates](../../vuln-verify/SKILL.md#pending-security-updates) section says how its steps change without a CVE.

## Report

One table, one row per server in scope: name, the number of security updates found (by the refreshed check where the root preview ran, otherwise by the first check), applied, and left, in four groups (held, pinned, kernel updates not chosen, other updates not chosen); then the remediate and verify outcomes. Below it, what a person still has to do: services to restart and servers to reboot, each with the command, held and pinned packages to review, and the `unknown` servers with their reasons. Close with the time the lists were read and what this path does not cover.
