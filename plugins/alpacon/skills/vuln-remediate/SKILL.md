---
name: vuln-remediate
description: Apply a vulnerability fix to Alpacon servers by running one reviewed recipe script with execute_file—one server at a time, stopping at the first run that does not reach the fixed version—inside an approved Work Session. Use when someone wants affected servers upgraded or patched ("upgrade openssh on the affected servers", "apply the PHP fix to web-01 to web-12", "run the patch recipe"), usually after vuln-diagnose and as the second step of vuln-patch. Runs no restart, reboot, or container redeploy itself.
---

# Remediate a vulnerability

Run one recipe, unchanged, on each target server. Servers run one at a time, and each run must finish and show the fixed version before the next is submitted. Follow the `using-alpacon` skill for Work Sessions, approvals, `pending_approval` and `outcome_unknown` results, and `execute_file` refusals.

## Inputs

- The CVE, the package, and the fixed version for each release, as `vuln-diagnose` used them. Step 6 needs them to judge each run.
- The target servers, normally the `affected` rows from `vuln-diagnose`.
- The install method.
- The recipe: a script the person supplies, or one you draft from [recipes.md](references/recipes.md).
- An existing Work Session and its account, if supplied, and whether this task opened it. Reuse it only if its approved servers, account, and scopes cover this recipe.
- Whether a caller such as `vuln-patch` will verify in the same Work Session afterwards.

## What this skill does not run

A container image or a vendor installer is upgraded by redeploying or reinstalling, which takes a decision this skill cannot make: which image, which maintenance window, whether data needs a backup. For those servers, run nothing. Report the servers and the steps the vendor documents, for a person to carry out.

## Steps

1. Decide the account before showing anything. A recipe needing root uses `target_account_username: root`, scopes `command` and `webftp` (WebFTP writes the script), and `username: root` on every call. If the workspace disallows root as the session account, run it as a named ordinary account with `sudo` inside the recipe (see [recipes.md](references/recipes.md)) and add the `sudo` scope.
2. Show the person the server list, the full recipe byte for byte as it will run, its path, the account, and the session scopes. Say what the package's own scripts may do, as [recipes.md](references/recipes.md) describes. Wait for them to agree. For the Debian template, fill `approved_changes` after the preview in step 4 and show the complete final recipe for agreement before executing it. Once agreed, one changed byte needs a new review; every server runs the same file.
3. Reuse a supplied active Work Session that covers the agreed recipe. Otherwise open one with `work_session_create`, remembering that this task owns it, exactly as shown: those scopes, that account, the target servers, and a description naming the CVE and the package, and saying the recipe restarts nothing itself. If the workspace refuses root as the session account, go back to step 1 with the `sudo` route and show it again; never add a scope or change the account the person has not seen. Each sudo then follows `using-alpacon`'s sudo rules; a session-authorized sudo policy that would clear them is set by a person in the web console, since `request_sudo_policy` cannot create one.
4. Preview the upgrade on the first server with `execute_command`. For a Debian or RHEL-family package, send the preflight block from [recipes.md](references/recipes.md), which reads the server's state and runs the preview in one call; for another install method, send its preview line. Show what it would install, upgrade, or remove, a kernel included, with the preflight lines, and wait for the person to confirm. A preview that would remove a package, or install one the person did not expect, is a reason to stop. When the person already ran this preview and shows its output, use that instead of running it again, unless it lacks the preflight lines.
5. Run the recipe on the first server with `execute_file`: `write_file: true`, the recipe as `content`, a `path` in a directory only the run account can write (`/root/alpacon-<CVE>.sh` as root, the account's home directory on the `sudo` route; never `/tmp` or `/var/tmp`, where any local user can place a file first), `interpreter: /bin/bash`, and a `purpose` naming the CVE and the package, followed by that server's preflight lines except `units`, which can be long, on one line (`CVE-2099-0001 openssh-server; transaction=changes disk_free_root=... anomaly=none unreadable=none`), so an approver of a held run sees this server's own state.
6. Judge the run before anything else is submitted. It passes only when it finished, exited 0, and its output shows the fixed version. Anything else stops the rollout: a failure, a missing or older `after=` version, a refusal, a timeout, `outcome_unknown`, or a run held for approval. Wait for a held run's decision and judge the result; if it is still held when you have to stop waiting, report it `pending_approval` and submit nothing else.
7. For each remaining server, preview it first. A different mirror or dependency can change the transaction; if the preview would install, upgrade, or remove anything the person did not see in the first server's preview, stop and show it. Otherwise run the same `execute_file` call, one server at a time, with identical `content`, `path`, `interpreter`, account, and `args`; only `purpose` changes, to carry that server's preflight. Apply step 6 before submitting another, stopping at the first non-pass; later servers are `not_run`. Never batch or parallelize calls: failure on the second must keep the third from running. Review each run separately; approval for one server does not cover another.
8. Close only a Work Session this task opened, when nothing follows and every submitted run has a known terminal result. Keep it open while a run is held, timed out, or has an unresolved outcome; hand back its id, account, ownership, and unresolved command ids for reconciliation with `using-alpacon`. When a caller will verify next, also leave it open and pass that ownership onward. Never close a session supplied by someone else.

For a server previewed with the preflight block, read its preflight before its `execute_file` call. When `anomaly` or `unreadable` is not `none`, as when the preview itself failed (`transaction=unreadable`), or when the output lacks either line, do not run that server: show its preflight lines and ask the person whether to run it anyway, even if they said not to ask again, since that permission covered the recipe, not a server in this state. Run it only on a yes for that server. On a no, or with no answer, report it `not_run` with the anomaly or unreadable values as the reason and stop the rollout as after a failed run, so later servers are `not_run` too. The one exception is a server already fixed: when its transaction is `empty`, its installed version is at or above the fixed version, and no `ro_`, `disk_` or `inode_` anomaly is listed, the recipe changes nothing, so its preflight is reported, not asked about. Those three still stop it, because step 5 writes the script to that server's disk. An empty preview on a server below the fixed version means stale package lists or a mirror without the fix; the recipe refreshes the lists and may still install, so ask about its preflight like any other. `units`, `kubelet` and `mem_available` are never a reason to stop: show them, and when `kubelet` is `active` or the person has said the servers form an HA pair or a database cluster, say that patching the next server right after this one is their call. If the server holds the preflight block with `script_body_suggestion`, follow `using-alpacon`: do not resubmit it or fall back to the bare preview line, and stop the rollout.

A server whose agent cannot run verified files answers `file_exec_unsupported_agent` (alpamon older than 2.8.3, or Windows, which has no file lane). Report it as `not_run` with that reason. Here, unlike the general `execute_file` advice in `using-alpacon`, do not fall back to `execute_command`: the person agreed to a verified file, not to a shell line.

The recipe is idempotent, so a run that finished and failed can run again once the cause is fixed; pass `overwrite: true`, since the file is already on the host. A run that is held, timed out, or came back `outcome_unknown` is not a failed run: follow `using-alpacon` for it and do not run it again.

## Report

A table with one row per target server: name, outcome, the version the recipe printed afterwards, the `command_id`, and `preflight`: `clean`, the `anomaly` and `unreadable` values, or `not read`. The outcome is one of:

- `patched`: the run finished and printed the fixed version.
- `failed`: the run finished with an error or without the fixed version.
- `pending_approval`: still held for a person.
- `not_run`: never submitted, with the reason (the rollout stopped at an earlier server, a preflight the person did not clear, an unsupported agent, a refusal).
- `unknown`: may or may not have run, such as `outcome_unknown`, with the reason.

Below it, each server's preflight lines as read, then the container and vendor-install servers with the steps for a person.
