---
name: vuln-verify
description: Confirm a vulnerability fix actually took effect on Alpacon servers—the fixed version is installed and the running services and kernel loaded it—and list the servers that still need a restart or reboot, without restarting anything. Use after patching ("did the openssh fix take?", "verify CVE-2026-109618 is fixed on web-01 to web-12", "which servers still need a restart after the upgrade?") and as the last step of vuln-patch.
---

# Verify a vulnerability fix

An upgraded package does not patch a process that started before the upgrade: the old code stays loaded until the service restarts. The php2shell fix needed Apache restarted before it applied. So verifying is two checks: the installed version, and whether what runs loaded it. Follow the `using-alpacon` skill for Work Sessions and reading results.

## Inputs

- The servers that were remediated.
- The diagnose check command and the fixed version, as `vuln-diagnose` used them.
- The services that load the patched code (`ssh`, `apache2`, `php8.2-fpm`). Ask if you do not know: a library such as OpenSSL is loaded by many services.
- A Work Session from the caller, if `vuln-patch` handed one over; otherwise open one with the `command` scope for these servers, and close it at the end.

## Steps

1. Rerun the diagnose check, unchanged, with `execute_command_multi_server`. Every server should come back `not_affected`. One that is still `affected` failed to patch; report it and skip the next step for it.
2. Check what is running. Run one read-only line per server, choosing by what the server has:
   - `needrestart -b` (Debian and Ubuntu): lines `NEEDRESTART-SVC: <unit>` name services still running old code, and `NEEDRESTART-KSTA: 2` or `3` means a newer kernel is installed than the one running.
   - `dnf needs-restarting -s` (RHEL family) lists services to restart; `dnf needs-restarting -r` exits 1 when a reboot is needed.
   - Neither installed: compare `systemctl show -p ActiveEnterTimestamp --value <service>` with the upgrade time, from `/var/log/dpkg.log` (`grep " upgrade <pkg>:" /var/log/dpkg.log | tail -1`) or `rpm -q --qf '%{INSTALLTIME:date}\n' <pkg>`. A service that started before the upgrade still runs the old code.
   - Kernel fixes: compare `uname -r` with the fixed kernel, as `vuln-diagnose`'s distribution-package reference describes.
3. Do not restart or reboot anything. For each server that needs it, write down the exact command a person would run (`systemctl restart apache2`, `reboot`), and leave the decision with them: a restart drops connections, and only they know when that is acceptable.

Without root, `needrestart` sees only the session account's processes. If it runs unprivileged, say the result may miss services, or use the `systemctl` comparison, which any account can read.

## Report

A table with one row per server: name, installed version, and one outcome:

- `fixed`: the fixed version is installed and nothing listed runs old code.
- `restart_needed`: installed, but the named services still run old code. Give the command.
- `reboot_needed`: the running kernel predates the fix. Give the command.
- `still_affected`: the diagnose check still says `affected`.
- `unknown`: the check could not run or its output could not be read, with the reason. Never report it as `fixed`.
