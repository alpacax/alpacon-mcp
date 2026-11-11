---
name: vuln-diagnose
description: Find which Alpacon servers are affected by a vulnerability by reading the installed version of the vulnerable software and comparing it with the vendor's fixed version, read-only. Use when someone asks whether servers are affected by a CVE or advisory ("are we hit by CVE-2099-0001?", "which servers still run the vulnerable openssh?", "check our Metabase version against the advisory"), and as the first step of vuln-patch. Changes nothing on the servers.
---

# Diagnose a vulnerability

Answer one question per server: is the installed software older than the fixed version? This skill only reads. Follow the `using-alpacon` skill for workspaces, server UUIDs, Work Sessions, approvals, and multi-server results.

## Inputs

- The CVE or advisory, and its vendor advisory.
- The install method, which picks the reference file below.
- The fixed version for each distribution release or release line in the advisory, or the fixing commit. Vendors often fix several lines at once (`0.53.x` and `0.54.x`), so compare an install with the fix for its own line.
- Optionally, a check command the person wrote.

If the fixed version is missing or comes only from a secondary source, ask for the vendor advisory before running anything: a wrong fixed version turns every verdict wrong at once.

For a distribution package, including the kernel, take each fixed version from the distribution's tracker or errata—the Ubuntu USN or CVE page, Debian security tracker, or RHSA—never upstream. Distributions backport fixes without changing the upstream version; for example, Ubuntu's `1:8.9p1-3ubuntu0.10` includes a fix upstream released later. If the tracker still marks a release vulnerable and has no fixed package, give its check a `none` arm: installed rows are `affected` with `reason=no-fix-available`, and no recipe follows.

## Steps

1. Call `list_servers`. Every server in scope, the whole workspace or the ones the person named, stays in the report; only which servers get a command narrows. A server with `is_connected: false` is `unknown` (offline). A Windows server is `unknown` (unsupported): the checks below are POSIX shell. A server in an OS family the advisory does not cover (a Debian server under an RHSA) is `unknown` (OS not in advisory). The rest are candidates, including a release the advisory does not list, which the check reports as `unknown`.
2. Read the reference file for the install method and build the check command from it:
   - Distribution package, including the kernel: [distro-package.md](references/distro-package.md)
   - pip or npm package: [language-package.md](references/language-package.md)
   - Container image: [other-installs.md](references/other-installs.md#container-images)
   - Vendor install: [other-installs.md](references/other-installs.md#vendor-installs)
   - Source build: [other-installs.md](references/other-installs.md#source-builds)
   - The person's own check command: [other-installs.md](references/other-installs.md#the-persons-own-check-command)

   A package name, version, commit, or CVE id goes into the command as data. If one holds shell syntax, a commit is not hexadecimal, or a CVE id is not shaped `CVE-<year>-<number>`, it is not a real value: ask, and do not build the command.
3. Show the person the exact command, the servers it will run on, and the account it runs as, and wait for them to agree. It runs as written on every server, so they should see it first.
4. Open a Work Session for those servers with the `command` scope only, no `sudo` or `webftp`, and `target_account_username` set to a named non-root account; the checks need neither root nor file transfer. Name the check in the description: the `command` scope alone does not make a session read-only, so the description is where the approver sees what it is for.
5. Run each check command once across its servers with `execute_command_multi_server`, passing that account as `username`, with a `purpose` that names the CVE and says the command only reads a version, and read each server's result as `using-alpacon`'s fleet reference describes.
6. Turn each server's output into a verdict, and close the Work Session you opened.

## Verdicts

- `affected`: the installed version is older than the fixed version, or the fixing commit is missing. Keep the check's `reason`: `reboot-pending` means a fixed kernel is installed but not running, and `no-fix-available` means the distribution has not shipped a fix for that release yet.
- `not_affected`: the software is not installed, or the installed version is the fixed version or newer.
- `unknown`: anything else, with the reason: offline, unsupported OS, command refused or failed, output that does not parse, a release or OS the advisory does not list, or software inside a container the host cannot see into.

Distribution, pip, and npm checks decide on the host and print the verdict. When a check prints only `installed=` and leaves the comparison to you, as vendor-install and container checks do, compare release numbers numerically (`1.10.0` is newer than `1.9.3`). A pre-release, a local version (`+cu121`), or anything you cannot order with certainty is `unknown`, with the version in the reason.

Never fold `unknown` into `not_affected`: a server nobody could check is a server nobody knows is safe.

## Report

A table with one row per server in scope: name, UUID, OS and release, installed version, verdict, and the reason for every `unknown` and every `affected` row, including `reboot-pending` and `no-fix-available`. When patching follows, hand the `affected` rows to `vuln-remediate`, except `reboot-pending` ones, which need only a reboot by a person, and `no-fix-available` ones, which wait for the distribution's fix.
