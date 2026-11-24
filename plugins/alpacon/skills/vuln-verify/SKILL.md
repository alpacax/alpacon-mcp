---
name: vuln-verify
description: Confirm a vulnerability fix actually took effect on Alpacon servers—the fixed version is installed and the running services and kernel loaded it—and list the servers that still need a restart or reboot, without restarting anything. Use after patching ("did the openssh fix take?", "verify CVE-2099-0001 is fixed on web-01 to web-12", "which servers still need a restart after the upgrade?") and as the last step of vuln-patch.
---

# Verify a vulnerability fix

An upgraded package does not patch a process that started before the upgrade: the old code stays loaded until the service restarts. So verifying is two checks: the installed version, and whether what runs loaded it. Follow the `using-alpacon` skill for Work Sessions and reading results.

## Inputs

- The servers that were remediated.
- The diagnose check command and the fixed version, as `vuln-diagnose` used them. Called on its own, build the check from `vuln-diagnose`'s reference for the install method.
- The services that load the patched code (`ssh`, `apache2`, `php8.2-fpm`). Ask if you do not know: a library such as OpenSSL is loaded by many services. Treat service and package names as data: accept only names starting with an ASCII letter or digit and containing ASCII letters, digits, `.`, `_`, `+`, `:`, `@`, or `-`; otherwise ask for the exact name. Quote each as a single shell argument and use `--` before positional arguments.
- On `vuln-patch`'s pending security updates path, which names no CVE: the check from its [reference](../vuln-patch/references/pending-security-updates.md#the-check) in place of the diagnose check, and the packages remediate applied, with their previewed versions, in place of a fixed version. See [Pending security updates](#pending-security-updates).
- The Work Session and its account, if `vuln-patch` handed them over. Pass that account as `username` on every command, since the session approves only that account. Otherwise open one with the `command` scope for these servers, and close it at the end.

## Steps

1. Rerun the diagnose check, unchanged, with `execute_command_multi_server`. Distribution, pip, and npm checks print their verdict from a comparison on the host; do not redo it yourself. Read each verdict:
   - `not_affected`: go on to step 2.
   - `affected` with `reason=reboot-pending`: the fix is installed and the kernel is not running it yet. The outcome is `reboot_needed`.
   - Any other `affected`: the patch did not land. The outcome is `still_affected`; skip step 2 for it.
   - `unknown`: the outcome is `unknown`, with the check's reason.
2. Check what is running, with one read-only line per server, chosen by what the server has:
   - `needrestart -b -r l` (Debian and Ubuntu): `-r l` only lists, so the check cannot restart anything even where the configuration sets automatic restarts. Each `NEEDRESTART-SVC: <unit>` line names a service still running old code. `NEEDRESTART-KSTA: 2` or `3` means a newer kernel is installed than the one running, `1` means the running kernel is current, and `0` means needrestart could not tell.
   - `dnf needs-restarting -s` (RHEL family): lists services to restart. `dnf needs-restarting -r` exits 1 when a reboot is needed.
   - Neither installed: compare `systemctl show -p Id -p ActiveState -p ExecMainStartTimestamp -p KillMode -- '<service>'`, with its socket unit after it when it has one (`'ssh.socket'`), with the upgrade, from `/var/log/dpkg.log` or `rpm -q --qf '%{INSTALLTIME:date}\n' -- '<pkg>'`. Read it with these rules:
     - Debian and Ubuntu: dpkg writes `upgrade <pkg>:` before it unpacks the new files and `configure <pkg>:` after, so a main process that started between the two may have loaded either. A start before the `upgrade` line runs the old code. A start in a later second than a `configure` line that is not older than the `upgrade` line loaded the new files. Anything else, a same-second start included, is ambiguous.
     - RHEL family: rpm replaces the files before it stamps `INSTALLTIME`, so a main process that started in a later second loaded the new files. A start in the same second is ambiguous. Treat an earlier start as old code, since rpm may not have written the files yet.
     - A service that is not `active` runs no main process, so its old start time does not count. With `KillMode=control-group` or `mixed` nothing of it is left; with any other mode old workers may be, which only a root scan shows, so the outcome is `unknown`.
     - A start before the upgrade makes an `active` service `restart_needed`. An ambiguous or missing start is `unknown`. A start on the new files makes the outcome `fixed` only for code that cannot run in a login session, and only with `KillMode=control-group` or `mixed`, since any other mode can leave old workers behind that the start time does not show.

   Compare the stale-service results with the named services that load this patched code. Only those services can make this CVE's outcome `restart_needed`; list unrelated stale services separately as maintenance information. If the relevant service list is incomplete, report `unknown` rather than `fixed`.

   Patched code that can run in a login session (`ssh`, whose connections outlive a restart, a library, or a command users run) needs the sessions checked too, whatever state the service is in and however recently it started; when you cannot tell, treat it as such code. Only `needrestart` run as root lists them, as `NEEDRESTART-SESS` lines. Such a line names a user and a session (`root @ session #28017`), never a service or package, so it cannot show whose old code the session runs. Decide in this order:

   - A named service is stale: `restart_needed`, with any `NEEDRESTART-SESS` sessions listed beside it.
   - `needrestart` ran as root, printed `needrestart_exit: 0`, and lists a session: `unknown`. List each session, say it may still run the old code, and name ending it as what clears it, since restarting the service leaves it running.
   - The sessions were not listed (an ordinary account, `needrestart` missing or failed, or the RHEL family, where `-s` lists services only): `unknown`, with that reason. Fresh start times do not make it `fixed`. Do not hunt for the sessions with other process reads: hand the person the root check (`needrestart -b -r l`, after installing it when the exit code is `127`; on the RHEL family `dnf needs-restarting`, which lists processes), and name ending the old sessions as what clears it.
   - Otherwise the sessions are clean, and the service results decide.

   For code that cannot run in a login session, list any `NEEDRESTART-SESS` line as maintenance information.

   Attribute `reboot_needed` to this vulnerability only when the diagnose check confirms the running kernel predates its fix (`reason=reboot-pending`). `NEEDRESTART-KSTA: 2` or `3` alone may refer to an unrelated newer kernel; report that separately as maintenance information, not as this CVE's outcome.

   On Debian and Ubuntu, with a CVE, send steps 1 and 2 as one line per server, so each server needs one approval instead of two. The line is the diagnose check, unchanged, followed by the last upgrade and configure of the package in `dpkg.log`, the state, main process start time and kill mode of each named service and its socket unit, and `needrestart`'s list with its exit code. Like the diagnose checks, it reads `/etc/os-release` with `sed` and uses no `$(…)` or `${…}`: Alpacon's approval gate graded a combined line with those constructs HIGH and refused it, and this shape MEDIUM. Replace the check part with the one `vuln-diagnose` ran, and set the unit names:

   ```sh
   p=openssh-server; { sed -n 's/^VERSION_CODENAME=/Release: /p' /etc/os-release | tr -d "\"'"; dpkg-query -s "$p" 2>/dev/null; echo "Exit: $?"; } | grep -E '^(Release|Status|Version|Exit): ' | { while read -r k a b c; do case "$k" in Release:) r=$a;; Status:) w=$a; x=$b; s=$c;; Version:) v=$a;; Exit:) e=$a;; esac; done; case "$r" in jammy) f='1:8.9p1-3ubuntu0.10';; noble) f='1:9.6p1-3ubuntu13.5';; focal) f=none;; *) echo "verdict=unknown release=$r reason=release-not-in-advisory"; exit 0;; esac; case "$w" in install) t=i;; hold) t=h;; deinstall) t=r;; purge) t=p;; *) t=u;; esac; case "$s" in installed) t="$t"i;; not-installed) t="$t"n;; config-files) t="$t"c;; unpacked) t="$t"U;; half-installed) t="$t"H;; half-configured) t="$t"F;; triggers-awaited) t="$t"W;; triggers-pending) t="$t"t;; esac; [ "$x" != reinstreq ] || t="$t"R; case "$e:$s" in 0:installed) ;; 0:not-installed|0:config-files) echo "verdict=not_affected package=$p release=$r installed=none status=$t"; exit 0;; 1:) echo "verdict=not_affected package=$p release=$r installed=none"; exit 0;; *) echo "verdict=unknown package=$p release=$r reason=dpkg-query-exit-$e status=$t"; exit 0;; esac; [ "$f" != none ] || { echo "verdict=affected package=$p release=$r installed=$v status=$t reason=no-fix-available"; exit 0; }; dpkg --compare-versions "$v" lt "$f"; case $? in 0) o=affected;; 1) o=not_affected;; *) echo "verdict=unknown package=$p release=$r installed=$v status=$t reason=unorderable-version"; exit 0;; esac; echo "verdict=$o package=$p release=$r installed=$v fixed=$f status=$t"; }; grep -hF -e " upgrade $p:" -e " upgrade $p " /var/log/dpkg.log.1 /var/log/dpkg.log 2>/dev/null | tail -1 | sed 's/^/last_upgrade: /'; grep -hF -e " configure $p:" -e " configure $p " /var/log/dpkg.log.1 /var/log/dpkg.log 2>/dev/null | tail -1 | sed 's/^/last_configure: /'; systemctl show -p Id -p LoadState -p ActiveState -p ExecMainStartTimestamp -p KillMode -- 'ssh.service' 'ssh.socket'; { needrestart -b -r l 2>/dev/null; echo "needrestart_exit: $?"; } | grep -E '^(NEEDRESTART-(SVC|SESS|KSTA)|needrestart_exit):'
   ```

   - `last_upgrade:` and `last_configure:` are the newest `upgrade` and `configure` lines of the package in `dpkg.log` and `dpkg.log.1`. With no `last_upgrade:` the upgrade is older than both logs, so the start times have nothing to compare with; the outcome is `unknown` unless `needrestart` ran as root and printed `needrestart_exit: 0`.
   - A unit with `LoadState=not-found` does not exist on that server; most services have no socket unit.
   - `needrestart_exit:` is `needrestart`'s exit code: `0` means it scanned, `127` means it is not installed, and any other value means the scan failed. Only after a `0` on a root run does a missing `NEEDRESTART-` line mean nothing is stale; otherwise the list was never read, so use the `systemctl` comparison, within the login-session rule above, and never read the missing list as `fixed`.
   - The `NEEDRESTART-` lines come out only when the line runs as root. As an ordinary account none print, which proves nothing; use the `systemctl` comparison.

   A service its socket unit starts (`ssh.service` through `ssh.socket` on Ubuntu 24.04) can be `inactive` while the socket is `active`. Then the next connection starts it from the new binary on disk, so do not compare its stale `ExecMainStartTimestamp` with the upgrade time. Connections opened before the upgrade still keep their old processes, which run the old code: `needrestart` lists one still in the service's cgroup as `NEEDRESTART-SVC: ssh.service`, which makes the outcome `restart_needed` even while that service is `inactive`, and one in a login session as a `NEEDRESTART-SESS` line. The order above decides the outcome; it is `fixed` only as root, with `needrestart_exit: 0`, no `NEEDRESTART-SVC` line for a named service, and no `NEEDRESTART-SESS` line.

3. Do not restart or reboot anything, and run no reads beyond the checks above: the follow-up reads named below (`systemctl status`, `ps`, `journalctl`, the root check) are for the person to run, since each extra call takes another approval and an improvised one tends to need `$(…)`. For each server that needs it, write down the exact command a person would run (`systemctl restart apache2`, `reboot`), and leave the decision with them: a restart drops connections, and only they know when that is acceptable.

   A restart does not end every old process: where the unit sets `KillMode=process`, as `ssh.service` does, its old workers survive a stop or restart and `needrestart` keeps listing the service. So pick the command by what the check printed:

   - The service is `active`: `systemctl restart -- '<service>'`, followed by the verify check again. Nothing in `needrestart`'s line says which process is stale, so this stays the command unless both conditions below hold. With `KillMode=process` or `none`, add that old connections can survive the restart, and that those still listed after it have to end.
   - The service is `active`, its `KillMode` is `process` or `none`, and its main process started on the new files (a later second than `last_configure:`, which is not older than `last_upgrade:`; on the RHEL family, a later second than `INSTALLTIME`): the main process already has this fix, so what is left is an old worker, or old code of another package, and a restart leaves the worker running. The old connections have to end; name that, and give the person a way to tell them apart: `systemctl status -- '<service>'` lists the processes left in the unit, and `ps -o pid,lstart,args -p <pids>` with those PIDs gives each one's start time. A process that started before `last_upgrade:` runs the old code, and one that started between it and `last_configure:`, or in the same second as either, may: an old main process can start workers while dpkg unpacks. Only one that started in a later second than `last_configure:` loaded the new files. On the RHEL family only one that started in a later second than `INSTALLTIME` did; any earlier or same-second start may run the old code. When every process did, the stale code belongs to another package the service loads; say so and give the restart above instead. Do not give `systemctl kill`, which would also end the new processes.
   - The service is `inactive` or `failed` and listed: `systemctl kill -- '<service>'`, which ends every process left in it. A `failed` service stays down after that; say that a person has to find out why and start it.
   - The service is in any other state (`activating`, `deactivating`, `reloading`): give no command yet. Name the state and hand over the root check, to run again once it settles.

   Every state you report can change before the person acts: a connection can start an `inactive` service again, and a session can end or a new one take its place. With each command, or the advice to end a session, tell them to:

   - Run the root check again right before, and stop if its answer changed. `systemctl kill` is only for a service still `inactive` or `failed` and still listed, read with `systemctl show -p ActiveState -- '<service>'` and `needrestart -b -r l`; once it is `active`, the command also ends the new listener and new connections.
   - Expect what it interrupts: `systemctl kill` and a restart can drop connections, ending a session stops the work in it and may be the person's own connection, and a reboot ends everything on the server.
   - Have this check rerun afterwards; only its answer makes the outcome `fixed`.

Never run bare `needrestart`: its default mode on Ubuntu 22.04 and later restarts services. Run as an ordinary account, `needrestart` and `dnf needs-restarting` see only that account's processes, so an empty answer proves nothing about root's services. Use the `systemctl` comparison for the named services in that case; any account can read it, but it says nothing about login sessions. If neither gives an answer for a server, its outcome is `unknown`, and so is `NEEDRESTART-KSTA: 0`.

## Pending security updates

With no CVE, the steps change in five places:

- Step 1 reruns the pending security updates check and, in the same call, reads each applied package's status and version with `dpkg-query -W -f='${binary:Package} ${db:Status-Abbrev} ${Version}\n' -- <packages>`, since a package downgraded or pinned below its previewed version can drop out of the `pkg=` lines. A package whose status's second letter is not `i` is not installed, even though `dpkg-query` still prints the version its leftover configuration records (`rc`). A server where an applied package is below its previewed version, or is no longer installed, is `still_affected`; `count=unknown` is `unknown`; otherwise go on to step 2. Report the packages still listed, held or not chosen, as what is left, not as a failure.
- Steps 1 and 2 stay two calls. The pending security updates check uses `$(…)` and `dpkg-query -W -f='${…}'`, so it cannot join the one-line form, and step 2 runs as root under the `sudo` scope while the check does not need it.
- In step 2, every applied package is the patched code, so every `NEEDRESTART-SVC` service counts toward `restart_needed`, and no named-services list exists to fall back on. So `needrestart` has to run as root: as `sudo needrestart -b -r l` on the `sudo` route, under the session's `sudo` scope. Where no root answer is possible, or `needrestart` is missing, the outcome is `unknown`. A `NEEDRESTART-SESS` line names a user session, not a service, that may still run old code; restarting a service does not clear it, so any such line also makes the outcome `unknown`: list each session and name ending it as what clears it, with the precautions in step 3. When a service is listed too, the outcome is `restart_needed` with the sessions beside it.
- Step 3 picks each listed service's command from its state, so read `systemctl show -p Id -p ActiveState -p KillMode -- <listed services>` in a second read-only call before handing one over. Several packages changed, so no single `configure` line dates the new files: the branch for a main process started on them does not apply, and an `active` service gets the restart.
- `reboot_needed` holds when a kernel package was applied and `NEEDRESTART-KSTA` is `2` or `3`, or the check prints `reboot_required=yes`.

## Report

A table with one row per server: name, installed version, and one outcome:

- `fixed`: the fixed version is installed and nothing that loads it runs old code.
- `restart_needed`: installed, but the named services still run old code. Give the command and the precautions from step 3.
- `reboot_needed`: the running kernel predates the fix. Give the command and the precautions from step 3.
- `still_affected`: the diagnose check still says `affected` for a reason other than a pending reboot.
- `unknown`: the check could not run or its output could not be read, with the reason. Never report it as `fixed`.
