---
name: vuln-verify
description: Confirm a vulnerability fix actually took effect on Alpacon servers—the fixed version is installed and the running services and kernel loaded it—and list the servers that still need a restart or reboot, without restarting anything. Use after patching ("did the openssh fix take?", "verify CVE-2026-109618 is fixed on web-01 to web-12", "which servers still need a restart after the upgrade?") and as the last step of vuln-patch.
---

# Verify a vulnerability fix

An upgraded package does not patch a process that started before the upgrade: the old code stays loaded until the service restarts. So verifying is two checks: the installed version, and whether what runs loaded it. Follow the `using-alpacon` skill for Work Sessions and reading results.

## Inputs

- The servers that were remediated.
- The diagnose check command and the fixed version, as `vuln-diagnose` used them. Called on its own, build the check from `vuln-diagnose`'s reference for the install method.
- The services that load the patched code (`ssh`, `apache2`, `php8.2-fpm`). Ask if you do not know: a library such as OpenSSL is loaded by many services. Treat service and package names as data: accept only names starting with an ASCII letter or digit and containing ASCII letters, digits, `.`, `_`, `+`, `:`, `@`, or `-`; otherwise ask for the exact name. Quote each as a single shell argument and use `--` before positional arguments.
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
   - Neither installed: compare `systemctl show -p ActiveEnterTimestamp --value -- '<service>'` with the upgrade time, from `/var/log/dpkg.log` (`grep -F ' upgrade <pkg>:' /var/log/dpkg.log | tail -1`) or `rpm -q --qf '%{INSTALLTIME:date}\n' -- '<pkg>'`. A service that started before the upgrade still runs the old code.

   Compare the stale-service results with the named services that load this patched code. Only those services can make this CVE's outcome `restart_needed`; list unrelated stale services separately as maintenance information. If the relevant service list is incomplete, report `unknown` rather than `fixed`.

   Attribute `reboot_needed` to this vulnerability only when the diagnose check confirms the running kernel predates its fix (`reason=reboot-pending`). `NEEDRESTART-KSTA: 2` or `3` alone may refer to an unrelated newer kernel; report that separately as maintenance information, not as this CVE's outcome.

3. Do not restart or reboot anything. For each server that needs it, write down the exact command a person would run (`systemctl restart apache2`, `reboot`), and leave the decision with them: a restart drops connections, and only they know when that is acceptable.

Never run bare `needrestart`: its default mode on Ubuntu 22.04 and later restarts services. Run as an ordinary account, `needrestart` and `dnf needs-restarting` see only that account's processes, so an empty answer proves nothing about root's services. Use the `systemctl` comparison for the named services in that case; any account can read it. If neither gives an answer for a server, its outcome is `unknown`, and so is `NEEDRESTART-KSTA: 0`.

## Report

A table with one row per server: name, installed version, and one outcome:

- `fixed`: the fixed version is installed and nothing that loads it runs old code.
- `restart_needed`: installed, but the named services still run old code. Give the command.
- `reboot_needed`: the running kernel predates the fix. Give the command.
- `still_affected`: the diagnose check still says `affected` for a reason other than a pending reboot.
- `unknown`: the check could not run or its output could not be read, with the reason. Never report it as `fixed`.
