---
name: vuln-remediate
description: Apply a vulnerability fix to Alpacon servers by running one reviewed recipe script with execute_file—first on a single server, then on the rest—inside an approved Work Session. Use when someone wants affected servers upgraded or patched ("upgrade openssh on the affected servers", "apply the PHP fix to web-01 to web-12", "run the patch recipe"), usually after vuln-diagnose and as the second step of vuln-patch. Does not restart services, reboot, or redeploy containers.
---

# Remediate a vulnerability

Run one recipe, unchanged, on each target server, and stop at the first failure. Follow the `using-alpacon` skill for Work Sessions, approvals, `pending_approval` results, and `execute_file` refusals; this skill does not repeat those rules.

## Inputs

- The target servers, normally the `affected` rows from `vuln-diagnose`.
- The install method.
- The recipe: a script the person supplies, or one you draft from [recipes.md](references/recipes.md).
- A Work Session from the caller, if `vuln-patch` handed one over.

## What this skill does not run

A container image or a vendor installer is upgraded by redeploying or reinstalling, which takes a decision this skill cannot make: which image, which maintenance window, whether data needs a backup. For those servers, run nothing. Report the servers and the steps the vendor documents, for a person to carry out.

## Steps

1. Show the person the server list and the full recipe, byte for byte as it will run, with the path and the account it will run as. Wait for them to agree. Do not edit the recipe after this: changing one byte makes it a different file that needs a new review, and the servers would no longer all run the same thing.
2. Use the caller's Work Session if there is one. Otherwise open one with `work_session_create`: scopes `command` and `webftp` (writing the script to the host goes through WebFTP), the target servers, and a description naming the CVE, the package, and that nothing is restarted. A recipe that needs root runs as root: set `target_account_username: root` on the session and pass `username: root` on each call. If the workspace does not allow logging in as root, run as the usual account with `sudo` inside the recipe, add the `sudo` scope, and with more than a few servers file one `request_sudo_policy` for the recipe's commands up front, so the approver decides once instead of once per server.
3. Run the recipe on one server with `execute_file`: `write_file: true`, the recipe as `content`, a fixed `path` such as `/var/tmp/alpacon-<CVE>.sh`, `interpreter: /bin/bash`, a `purpose` naming the CVE and the package, and `reuse_days: 1` so the approver can let the same bytes run on the other servers without paging again. Pass `overwrite: true` when rerunning after a failure, since the file is already there.
4. If the first server's run fails, or its output does not show the fixed version, stop. Report its output and do not touch the other servers: whatever broke there would break everywhere.
5. Run the same call on each remaining server: same `content`, `path`, `interpreter`, account, and `args`. Anything different starts a new review.
6. Close the Work Session if you opened it. Leave a session the caller handed over open; the caller closes it.

A server whose agent cannot run verified files answers `file_exec_unsupported_agent` (alpamon older than 2.8.3, or Windows, which has no file lane). List it in the report as not patched with that reason. Do not fall back to pasting the recipe into `execute_command`: the approver agreed to a verified file, not to a shell line.

The recipe is idempotent, so a server that waited on approval, timed out, or failed partway can run it again once the cause is fixed. A held run is not rerun; read its result with `check_command_status` when it is approved.

## Report

A table with one row per target server: name, outcome (`patched`, `failed`, `not_run` with the reason, or `pending_approval`), the version the recipe printed afterwards, and the `command_id`. Below it, the container and vendor-install servers with the steps for a person, and every server whose first run stopped the rest.
