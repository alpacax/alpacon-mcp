---
name: vuln-patch
description: Patch a vulnerability across Alpacon servers end to end—find the affected servers, upgrade them, and confirm the fix took effect—by chaining the vuln-diagnose, vuln-remediate, and vuln-verify skills. Use when someone wants a CVE or security advisory fixed on their fleet ("patch CVE-2026-109618 on our web servers", "roll out the openssh fix", "we're on the vulnerable PHP, fix it"), not just checked or verified.
---

# Patch a vulnerability

This skill holds no procedure of its own. It runs three skills in order and decides when to stop; each step's rules live in that step's skill, so read them there. The `using-alpacon` skill covers Work Sessions, approvals, and reading results throughout.

## Inputs

Collect these before the first step, and ask for what the request does not give:

- The CVE or advisory, and the vendor advisory it comes from. Fixed versions come from the vendor advisory, not from a blog post or news story that quotes it.
- What is vulnerable and how it is installed (distribution package, pip or npm package, container image, vendor install, source build, or a check command the person supplies).
- The fixed version per distribution release, or the fixing commit.
- Which servers to consider, if not the whole workspace.

## Steps

1. Run the `vuln-diagnose` skill on the candidate servers. Show the person its table.
2. If no server is `affected`, stop here and report the table. Servers that are `unknown` stay listed as unknown with their reason; they are not counted as safe.
3. Run the `vuln-remediate` skill on the `affected` servers only. Hand it the Work Session you open for this step and keep the session open afterwards, because verify runs in it.
4. If remediate stopped on its first server, stop here: report what failed and do not run the rest or verify.
5. Run the `vuln-verify` skill on the servers remediate patched, in the same Work Session.
6. Close the Work Session you opened for steps 3 to 5, then report.

Diagnose needs only read access, and remediate needs write or root access on fewer servers. Keep them in separate Work Sessions: one for diagnose across the candidates, one for remediate and verify across the affected servers. The approver sees exactly what each step can touch, and nobody is asked twice for the second half.

## Report

One table, one row per candidate server: name, diagnose verdict with the installed version, remediate outcome, and verify outcome. Below it, list the servers that need a person: `unknown` servers with their reason, servers remediate reported but did not touch (container images, vendor installs), and servers that need a service restart or a reboot, with the command a person would run.
