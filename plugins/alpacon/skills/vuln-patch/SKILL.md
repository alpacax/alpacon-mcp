---
name: vuln-patch
description: Patch a vulnerability across Alpacon servers end to end—find the affected servers, upgrade them, and confirm the fix took effect—by chaining the vuln-diagnose, vuln-remediate, and vuln-verify skills. Use when someone wants a CVE or security advisory fixed on their fleet ("patch CVE-2099-0001 on our web servers", "roll out the openssh fix", "we're on the vulnerable PHP, fix it"), not just checked or verified.
---

# Patch a vulnerability

This skill holds no procedure of its own. It runs three skills in order, hands each one's result to the next, and decides when to stop. Each step's rules live in that step's skill.

## Steps

1. Run the `vuln-diagnose` skill on the servers in scope, with the inputs it asks for. It opens and closes its own Work Session, with the `command` scope only and an ordinary account. Show the person its table.
2. Remediation targets are the `affected` servers except `reboot-pending` ones, whose fix is installed and which need only a reboot, and `no-fix-available` ones, which have no package to upgrade to. If no server is left, stop and report the table.
3. Run the `vuln-remediate` skill on those servers. Tell it verify follows, so it leaves its Work Session open and hands back the id and the account.
4. If any submitted run is `pending_approval` or has an unresolved outcome, stop here and preserve the Work Session. Report its id, account, ownership, and command ids; reconcile those runs with `using-alpacon` before resuming or closing anything. Otherwise, if remediate reports no server `patched`, close only the Work Session this task opened and stop here: report what failed and do not verify. If it stopped partway, the servers before the stop are `patched` and go on to verify; report the stop and the `not_run` servers with them.
5. Run the `vuln-verify` skill on the servers remediate reports `patched`, in that Work Session and as that account.
6. Close the Work Session only if this task opened it and every submitted run is terminal, then report.

Diagnose and remediate use separate Work Sessions on purpose: diagnose runs across every candidate as an ordinary account, while remediate runs as root on fewer servers. The `command` scope does not make a session read-only; what keeps diagnose read-only is the check the person agreed to, so name that check in the session description.

## Report

One table, one row per server in scope: name, diagnose verdict with the installed version, remediate outcome, and verify outcome. Below it, list every server that needs a person: `unknown` rows with their reason, remediate rows that are `pending_approval`, `not_run`, or `unknown`, container and vendor-install servers remediate did not touch, and servers that need a service restart or a reboot, with the command a person would run.
