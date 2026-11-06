---
name: vuln-remediate
description: Apply a vulnerability fix to Alpacon servers by running one reviewed recipe script with execute_file—first on a single server, then on the rest—inside an approved Work Session. Use when someone wants affected servers upgraded or patched ("upgrade openssh on the affected servers", "apply the PHP fix to web-01 to web-12", "run the patch recipe"), usually after vuln-diagnose and as the second step of vuln-patch. Runs no restart, reboot, or container redeploy itself.
---

# Remediate a vulnerability

Run one recipe, unchanged, on each target server. The first server is the test: nothing else runs until it has finished and shows the fixed version. Follow the `using-alpacon` skill for Work Sessions, approvals, `pending_approval` and `outcome_unknown` results, and `execute_file` refusals.

## Inputs

- The CVE, the package, and the fixed version for each release, as `vuln-diagnose` used them. Step 4 needs them to judge the first run.
- The target servers, normally the `affected` rows from `vuln-diagnose`.
- The install method.
- The recipe: a script the person supplies, or one you draft from [recipes.md](references/recipes.md).
- Whether a caller such as `vuln-patch` will verify in the same Work Session afterwards.

## What this skill does not run

A container image or a vendor installer is upgraded by redeploying or reinstalling, which takes a decision this skill cannot make: which image, which maintenance window, whether data needs a backup. For those servers, run nothing. Report the servers and the steps the vendor documents, for a person to carry out.

## Steps

1. Show the person the server list and the full recipe, byte for byte as it will run, with the path and the account it will run as. Wait for them to agree. Do not edit the recipe after this: one changed byte makes it a different file that needs a new review, and the servers would no longer all run the same thing.
2. Open a Work Session with `work_session_create`: scopes `command` and `webftp` (writing the script to the host goes through WebFTP), the target servers, and a description naming the CVE and the package, and saying the recipe restarts nothing itself. A recipe that needs root runs as root: set `target_account_username: root` and pass `username: root` on each call. If the workspace does not allow root as the session account, run as the usual account with `sudo` inside the recipe (see [recipes.md](references/recipes.md)) and add the `sudo` scope. Each sudo then follows `using-alpacon`'s sudo rules; a session-authorized sudo policy that would clear them is set by a person in the web console, since `request_sudo_policy` cannot create one.
3. Run the recipe on one server with `execute_file`: `write_file: true`, the recipe as `content`, a fixed `path` such as `/var/tmp/alpacon-<CVE>.sh`, `interpreter: /bin/bash`, and a `purpose` naming the CVE and the package.
4. Wait until that run has finished. If it is held for approval, wait for the decision; do not move on meanwhile. If it failed, or its output does not show the fixed version, stop and report its output: whatever broke there would break everywhere.
5. Run the same call on each remaining server: same `content`, `path`, `interpreter`, account, and `args`. Each server's run is reviewed on its own; an approval on one server does not carry over to the next.
6. Close the Work Session when nothing follows. When a caller will verify next, leave it open and hand back its id.

A server whose agent cannot run verified files answers `file_exec_unsupported_agent` (alpamon older than 2.8.3, or Windows, which has no file lane). Report it as `not_run` with that reason. Here, unlike the general `execute_file` advice in `using-alpacon`, do not fall back to `execute_command`: the person agreed to a verified file, not to a shell line.

The recipe is idempotent, so a run that finished and failed can run again once the cause is fixed; pass `overwrite: true`, since the file is already on the host. A run that is held, timed out, or came back `outcome_unknown` is not a failed run: follow `using-alpacon` for it and do not run it again.

## Report

A table with one row per target server: name, outcome, the version the recipe printed afterwards, and the `command_id`. The outcome is one of:

- `patched`: the run finished and printed the fixed version.
- `failed`: the run finished with an error or without the fixed version.
- `pending_approval`: still held for a person.
- `not_run`: never submitted, with the reason (a stop after the first server, an unsupported agent, a refusal).
- `unknown`: may or may not have run, such as `outcome_unknown`, with the reason.

Below it, the container and vendor-install servers with the steps for a person.
