---
name: vuln-diagnose
description: Find which Alpacon servers are affected by a vulnerability by reading the installed version of the vulnerable software and comparing it with the vendor's fixed version, read-only. Use when someone asks whether servers are affected by a CVE or advisory ("are we hit by CVE-2026-109618?", "which servers still run the vulnerable openssh?", "check our Metabase version against the advisory"), and as the first step of vuln-patch. Changes nothing on the servers.
---

# Diagnose a vulnerability

Answer one question per server: is the installed software older than the fixed version? This skill only reads. Follow the `using-alpacon` skill for workspaces, server UUIDs, Work Sessions, and approvals.

## Inputs

- The CVE or advisory, and its vendor advisory.
- The install method, which picks the reference file below.
- The fixed version for each distribution release or release line in the advisory, or the fixing commit. Vendors often fix several lines at once (`0.53.x` and `0.54.x`), so compare an install with the fix for its own line. A release or line the advisory does not list has no fixed version to compare with.
- Optionally, a check command the person wrote.

If the fixed version is missing or comes only from a secondary source, ask for the vendor advisory before running anything: a wrong fixed version turns every verdict wrong at once.

## Steps

1. Call `list_servers` and keep the candidates whose `os_name` and `os_version` the advisory covers. A server with `is_connected: false` is `unknown` (offline) and gets no command. A Windows server is `unknown` (unsupported): the checks below are POSIX shell.
2. Read the reference file for the install method and build the check command from it:
   - Distribution package, including the kernel: [distro-package.md](references/distro-package.md)
   - pip or npm package: [language-package.md](references/language-package.md)
   - Container image: [container-image.md](references/container-image.md)
   - Vendor install: [vendor-install.md](references/vendor-install.md)
   - Source build: [source-build.md](references/source-build.md)
   - The person's own check command: [custom-check.md](references/custom-check.md)
3. Show the person the exact command and the servers it will run on, and wait for them to agree. It runs as written on every server, so they should see it first.
4. Run it once with `execute_command_multi_server`, passing a `purpose` that names the CVE and says the command only reads a version. Read every server's entry: an accepted one carries a `command_id`; read its output with `check_command_status`. A refused or `pending_approval` entry is handled as `using-alpacon` describes, never by resending the whole call.
5. Turn each server's output into a verdict, as the reference file says.

## Verdicts

- `affected`: the installed version is older than the fixed version, or the fixing commit is missing.
- `not_affected`: the software is not installed, or the installed version is the fixed version or newer.
- `unknown`: anything else. Say why: offline, unsupported OS, command refused or failed, output that does not parse, a release the advisory does not list, or the software running inside a container that the host cannot see into.

Never fold `unknown` into `not_affected`. A server nobody could check is a server nobody knows is safe, and the report is the only place the person learns that.

## Report

A table with one row per candidate server: name, UUID, OS and release, installed version, verdict, and the reason for every `unknown`. Hand the `affected` rows to `vuln-remediate` when patching follows.
