---
name: vuln-mitigate
description: Reduce exposure to a vulnerability on Alpacon servers that cannot be patched yet, by writing one dedicated configuration drop-in from the vendor advisory with execute_file—one server at a time, config-tested, inside an approved Work Session—and flagging the services that must restart for it to apply. Use when a fix is not released or a server cannot take it now ("no PHP 8.1 fix yet, apply the php.net mitigation", "mitigate CVE-2026-109618 on web-01 to web-12 until we can patch"), usually after vuln-diagnose marks servers affected. The vulnerability stays present and nothing is restarted.
---

# Mitigate a vulnerability

A mitigation lowers exposure; it does not fix anything. Write one drop-in file with the vendor's settings, test the configuration, and leave the restart to a person. Servers run one at a time. Follow the `using-alpacon` skill for Work Sessions, approvals, `pending_approval` and `outcome_unknown` results, and `execute_file` refusals.

## Inputs

- The CVE and its vendor advisory, with the mitigation it documents. A blog post that quotes the advisory is not a source: if the person has only that, ask for the advisory before running anything.
- The target servers, normally the `affected` rows from `vuln-diagnose` that cannot be patched yet.
- Each setting and its value, the drop-in path, the config test command, and the services that must restart for the setting to apply. Treat all of these as data, and check each before it goes into a command: a CVE id not shaped `CVE-<year>-<number>`, a setting name outside ASCII letters, digits, `.`, `_`, and `-`, a value or path holding shell syntax or a newline, a path that is not absolute, or a service name that breaks the `vuln-verify` naming rule is not a real value, so ask and do not build the script.
- The command that reads the value in effect, run against the process that serves traffic. For PHP that is `php-fpm8.1 -i`, not `php -i`: the CLI reads its own configuration, which differs from the one the web server loads.
- An existing Work Session and its account, if supplied, and whether this task opened it. Reuse it only if its approved servers, account, and scopes cover this script.

## Steps

1. Call `list_servers`. A server with `is_connected: false` is `unknown` (offline), and a Windows server is `unknown` (unsupported): `execute_file` has no file lane there. Every server in scope stays in the report.
2. Read the current value on each candidate. Show the person the read command, the servers, and the account, and wait for them to agree. Open a Work Session with the `command` scope only, no `sudo` or `webftp`, a named non-root `target_account_username`, and a description that names this read command: the `command` scope alone does not make a session read-only, so the description is where the approver sees what it is for. Run it once with `execute_command_multi_server`, passing that account as `username` and a `purpose` that names the CVE and says it only reads a setting. The call returns command ids, not output: read each server's result with `check_command_status` until it is terminal, then close that session. The read shows the configuration on disk, not what the running workers loaded. A server already at the advised value is `already_set` (on disk): it leaves steps 3 to 7, since the script would write a new drop-in beside whatever file sets the value now, and its service is still listed for restart; one whose output you cannot read is `unknown`. Also print the drop-in if it already exists (`cat -- '<path>'`): the script replaces it whole, so show the person any line in it the new script drops. Keep each server's current value: a deny list is merged with it and an allow list is set to the advised value, never a union, and servers whose current values differ form separate groups.
3. Build the script from [dropin.md](references/dropin.md), filling every `REPLACE` placeholder from the vendor advisory (`baseline` is what step 2 read) and merging a deny list with the value read in step 2 (an allow list takes the advised value alone). Show the person the server list, the full script byte for byte, the drop-in path, the account, and the session scopes, and say that the vulnerability stays present and no service restarts. Wait for them to agree. Servers whose current deny list differs need their own merged script, shown and agreed separately, so a script built from one server never overwrites another's list. Once agreed, one changed byte needs a new review; every server in a group runs the same file.
4. Reuse a supplied Work Session that covers the agreed script. Otherwise open a second one, apart from the read session, with `work_session_create`: scopes `command` and `webftp` (WebFTP writes the script), `target_account_username` set to the account that can write the drop-in directory (usually `root`), the target servers, and a description naming the CVE, saying the script writes one configuration file and restarts nothing. Never add a scope or change the account the person has not seen.
5. Run the script on the first server with `execute_file`: `write_file: true`, the script as `content`, a `path` in a directory only the run account can write (`/root/alpacon-<CVE>-mitigate.sh` as root; never `/tmp` or `/var/tmp`), `interpreter: /bin/bash`, `username` set to that same account, and a `purpose` naming the CVE and saying it writes one drop-in and restarts nothing.
6. Judge the run before anything else is submitted. It passes only when it finished, exited 0, and printed `mitigation=applied` or `mitigation=unchanged`, which the script prints only after the config test and the read-back both passed. Anything else stops the rollout: a failure, a failed config test (the script rolled the drop-in back and exited 1), a value that changed since step 2 (the script refuses to write; read again and review again), a refusal, a timeout, `outcome_unknown`, or a run held for approval. A stop goes to step 8, which closes the session when no run is unresolved.
7. For each remaining server, run the same `execute_file` call with identical `content`, `path`, `interpreter`, account, and `args` (the content of its own group), one server at a time, applying step 6 before the next. Later servers are `not_run`. Never batch or parallelize. Approval for one server does not cover another.
8. Close only a Work Session this task opened, when every submitted run has a known terminal result. Keep it open while a run is held, timed out, or unresolved, and hand back its id, account, and command ids for reconciliation with `using-alpacon`. Never close a session supplied by someone else.

A server whose agent cannot run verified files answers `file_exec_unsupported_agent` (alpamon older than 2.8.3, or Windows). Report it `not_run` with that reason, and do not fall back to `execute_command`: the person agreed to a verified file, not to a shell line.

The script is idempotent, so a run that finished and failed can run again once the cause is fixed; pass `overwrite: true`, since the file is already on the host. A run that is held, timed out, or `outcome_unknown` is not a failed run: follow `using-alpacon` and do not run it again. The exception is `file_write_timeout`: nothing was submitted, so once the host is reachable run it again with `overwrite: true`, since the write may have landed late.

## What this skill does not do

- It restarts nothing. A setting applies only after the services restart; list each one with the command a person would run (`systemctl restart php8.1-fpm`), and say a restart drops connections.
- It does not remove the drop-in once the patch lands. A person deletes it, and the report below names the path.
- It does not approve anything. A `pending_approval` result goes to a person to decide in the web console or Slack.

## Report

Say in the first line, and again for every server, that the vulnerability is still present and this is a mitigation only. A table with one row per server in scope: name, the value before, and one outcome:

- `mitigated`: the script finished, and the config test and the read-back of the value on disk both passed. The setting takes effect after the restart below.
- `already_set`: the advised value was already on disk at step 2, so the server never reached the script and nothing was written. Its service may still need the restart.
- `failed`: the run finished with an error, a failed config test, or a read-back that did not show the advised value; the stderr line says whether the drop-in was rolled back. If it says the rollback failed, report the file and its backup path as needing manual repair, and never call the server restored.
- `pending_approval`: still held for a person.
- `not_run`: never submitted, with the reason (the rollout stopped at an earlier server, an unsupported agent, a refusal).
- `unknown`: offline, unsupported OS, an unreadable value, or `outcome_unknown`, with the reason.

Below it, every service that needs a restart for the setting to apply, with the command, and the drop-in path a person removes once the patch lands.
