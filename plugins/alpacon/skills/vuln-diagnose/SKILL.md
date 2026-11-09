---
name: vuln-diagnose
description: Find which Alpacon servers are affected by a vulnerability by reading the installed version of the vulnerable software and comparing it with the vendor's fixed version, read-only. Use when someone asks whether servers are affected by a CVE or advisory ("are we hit by CVE-2026-109618?", "which servers still run the vulnerable openssh?", "check our Metabase version against the advisory"), and as the first step of vuln-patch. Changes nothing on the servers.
---

# Diagnose a vulnerability

Answer one question per server: is the installed software older than the fixed version? This skill only reads. Follow the `using-alpacon` skill for workspaces, server UUIDs, Work Sessions, approvals, and multi-server results.

## Inputs

- The CVE or advisory, and its vendor advisory.
- The install method, which picks the reference file below.
- The fixed version for each distribution release or release line in the advisory, or the fixing commit. Vendors often fix several lines at once (`0.53.x` and `0.54.x`), so compare an install with the fix for its own line.
- Optionally, a check command the person wrote.

If the fixed version is missing or comes only from a secondary source, ask for the vendor advisory before running anything: a wrong fixed version turns every verdict wrong at once.

## Steps

1. Call `list_servers`. Every server in scope, the whole workspace or the ones the person named, stays in the report; only which servers get a command narrows. A server with `is_connected: false` is `unknown` (offline). A Windows server is `unknown` (unsupported): the checks below are POSIX shell. A server in an OS family the advisory does not cover (a Debian server under an RHSA) is `unknown` (OS not in advisory). The rest are candidates, including a release the advisory does not list, which the check reports as `unknown`.
2. Read the reference file for the install method and build the check command from it:
   - Distribution package, including the kernel: [distro-package.md](references/distro-package.md)
   - pip or npm package: [language-package.md](references/language-package.md)
   - Container image: [container-image.md](references/container-image.md)
   - Vendor install: [vendor-install.md](references/vendor-install.md)
   - Source build: [source-build.md](references/source-build.md)
   - The person's own check command: [custom-check.md](references/custom-check.md)

   A package name, version, commit, or CVE id goes into the command as data. If one holds shell syntax, a commit is not hexadecimal, or a CVE id is not shaped `CVE-<year>-<number>`, it is not a real value: ask, and do not build the command.
3. Show the person the exact command and the servers it will run on, and wait for them to agree. It runs as written on every server, so they should see it first.
4. Run each check command once across its servers with `execute_command_multi_server`, with a `purpose` that names the CVE and says the command only reads a version, and read each server's result as `using-alpacon`'s fleet reference describes.
5. Turn each server's output into a verdict.

## Verdicts

- `affected`: the installed version is older than the fixed version, or the fixing commit is missing. Keep the check's `reason`: `reboot-pending` means a fixed kernel is installed but not running.
- `not_affected`: the software is not installed, or the installed version is the fixed version or newer.
- `unknown`: anything else, with the reason: offline, unsupported OS, command refused or failed, output that does not parse, a release or OS the advisory does not list, or software inside a container the host cannot see into.

When a check prints `installed=` and leaves the comparison to you, compare release numbers numerically (`1.10.0` is newer than `1.9.3`). A pre-release, a local version (`+cu121`), or anything you cannot order with certainty is `unknown`, with the version in the reason.

Never fold `unknown` into `not_affected`: a server nobody could check is a server nobody knows is safe.

## Report

A table with one row per server in scope: name, UUID, OS and release, installed version, verdict, and the reason for every `unknown` and every `reboot-pending`. When patching follows, hand the `affected` rows to `vuln-remediate`, except `reboot-pending` ones, which need only a reboot by a person.
