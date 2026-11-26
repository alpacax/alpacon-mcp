# ATT&CK mapping

ATT&CK Enterprise v20.1 (2026-10-13)

An ID says what a record is consistent with, not that the technique was used. Decode every `%XX` byte for comparison and show the encoded value in the report. The host-kind rows match the field catalog in [collect.md](collect.md#record-kinds); `app_account` extends that catalog only for the separately approved application references. The first four columns follow the layout shared with `hardening-check`: ATT&CK mitigation is `—` because this file maps artifacts, not mitigations, and Tactic uses the v20.1 tactic names of every technique in the row.

Before applying the table, treat a numeric UID of zero as root regardless of leading zeroes, and treat an empty passwd password field as `password=none` regardless of shadow state. A `system-nologin` account is context unless another `account` condition makes it an artifact. Socket addresses are already normalized so IPv4-mapped peers compare as IPv4, and socket process evidence uses the final `pid=N,fd=` entry rather than attacker-controlled process-name text.

Secret exclusions compare logical paths, `readlink -f` targets and device and inode numbers before any file content is opened, hashed or searched. Absolute-secret metadata is captured before any other host file is read; home-relative secret metadata follows the minimum passwd and login.defs reads needed to expand it.

| Item | ATT&CK mitigation | ATT&CK technique | Tactic | Artifact when | Unknown when |
|---|---|---|---|---|---|
| `run` | — | none | — | never | never |
| `secret` | — | T1552.001 Unsecured Credentials: Credentials In Files | Credential Access | `exists=yes`, `atime_mode` is `strictatime` or `relatime`, and `atime` is on or after `since` | `exists=yes` and `atime_mode` is `noatime`, `readonly` or `?`; or `exists=yes`, `atime_mode` is `relatime`, `atime` is within the 24 hours before `since`, and later than both `mtime` and `ctime` |
| `account` | — | T1136.001 Create Account: Local Account | Persistence | `class=root` with a name other than `root`; a name the person gave; or `password=none` | `password=?` |
| `sudoers` | — | T1548.003 Abuse Elevation Control Mechanism: Sudo and Sudo Caching | Privilege Escalation | `mtime` or `ctime` is on or after `since`; or a comma-separated name in `principal` is a name the person gave or an artifact account | never |
| `authkey` | — | T1098.004 Account Manipulation: SSH Authorized Keys | Persistence; Privilege Escalation | `mtime` or `ctime` is on or after `since`; its account is an artifact; or `fp` is a fingerprint the person gave | `fp=?` |
| `cron` | — | T1053.003 Scheduled Task/Job: Cron | Execution; Persistence; Privilege Escalation | `hits` is neither empty nor `?`; or `mtime` or `ctime` is on or after `since` and either `packaged` is not `yes` or a `pkg_modified` record names the same path | `hits` is `?` |
| `systemd_unit` | — | T1543.002 Create or Modify System Process: Systemd Service; a `.timer` path also has T1053.006 Scheduled Task/Job: Systemd Timers | Execution; Persistence; Privilege Escalation | the same conditions as `cron` | the same conditions as `cron` |
| `rc_local` | — | T1037.004 Boot or Logon Initialization Scripts: RC Scripts | Persistence; Privilege Escalation | the same conditions as `cron` | the same conditions as `cron` |
| `listen` | — | none; report it as context without an ID | — | never | never |
| `connection` | — | T1071 Application Layer Protocol when `listening=no`; T1571 Non-Standard Port when `listening=no` and `rport` is outside the standard ports below | Command and Control | `raddr` is an address the person gave; or `exe` is under `/tmp`, `/var/tmp` or `/dev/shm` | never |
| `pkg_modified` | — | T1554 Compromise Host Software Binary; a path matching `*/security/pam_*.so` also has T1556.003 Modify Authentication Process: Pluggable Authentication Modules | Persistence; Defense Impairment; Credential Access | `conf=no` and `flags` shows a content change: `S`, `5` or `L` for `manager=rpm`, or `5` in the digest column for `manager=dpkg`, and `mtime` or `ctime` is on or after `since` | `manager=dpkg` and the digest column in `flags` is `?`; or `manager=rpm` and the digest-test (`5`) position in `flags` is `?`; or the flags show a content change and `mtime` or `ctime` is `?` |
| `webroot_file` | — | T1505.003 Server Software Component: Web Shell | Persistence | always, because the collector lists only script files changed since `since` | never |
| `login` | — | T1078 Valid Accounts; a `pts/*` tty with a `from` address also has T1021.004 Remote Services: SSH | Stealth; Persistence; Privilege Escalation; Initial Access; Lateral Movement | `user` is a name the person gave or an artifact account; or `from` is an address the person gave | never |
| `wtmp` | — | none | — | never | `begins` is after `since` |
| `unknown` | — | none | — | never | always |
| `check` | — | none | — | never | `status` is `partial` or `unknown`, or a requested check is `not_requested` |
| `cap` | — | none | — | never | no shown record of that `kind` is an artifact |
| `end` | — | none | — | never | `status` is not `complete` |
| `app_account` | — | T1136 Create Account; T1098 Account Manipulation | Persistence; Privilege Escalation | the application reference's condition | the application reference's condition |

A `pkg_modified` record whose flags show only a mode, owner, group, device, time or capability change (`M`, `U`, `G`, `D`, `T`, `P`) is context, because routine package scripts and administrators change those without altering content.

A `connection` with `deleted=yes` and an executable outside the temporary directories is context: a service that was upgraded but not restarted looks the same. A content change to a package file whose times are all before `since` is context, because it predates the intrusion.

An `account.pwchanged` date on or after `since`, or a `pwchanged=?`, is context only. It does not make the account an artifact or unknown by itself.

Package ownership is `yes`, `no` or `?` on every `cron`, `systemd_unit` and `rc_local` record. Routine package installation timestamps do not make a packaged scheduled file an artifact unless package verification also lists that path; a pattern hit remains an artifact regardless of package ownership. Systemd records cover `/run/systemd/transient` and every account's `~/.config/systemd/user` and `~/.local/share/systemd/user` trees.

## Standard ports

The standard set is 22, 25, 53, 80, 123, 443, 465, 587, 853, 993 and 995, plus ports the person identifies as known services. T1571 is context and never makes a record an artifact by itself; on a connection that is already an artifact, report it beside T1071.

## Not covered

A point-in-time host check covers only part of the Linux techniques that leave artifacts. The issue's ATT&CK Enterprise v20.1 analysis estimates that about 29 of 155 Linux techniques leave an artifact visible now and about 56 can be visible when logs still exist, a process or connection is active, or an effect is self-evident. Those counts are judgments from the STIX data rather than published ATT&CK totals.

Discovery, lateral movement, most collection and exfiltration, memory-only behavior and most initial access leave no reliable point-in-time artifact. Techniques visible only in logs belong elsewhere: exploitation of a public-facing application (T1190) to `compromise-log-check` (#465), which reads web logs for an advisory's request pattern; valid accounts, remote services, brute force, external remote services, shutdown and indicator removal including log clearing (T1078, T1021, T1110, T1133, T1529, T1070, T1685.006) to `auth-log-check` (#517). T1059, T1072, T1569 and T1068 need auditd or process accounting, and no skill covers them. This check also misses unspecified web roots, new files outside package ownership, evidence removed before collection, anything hidden by a rootkit, and secret reads that do not update atime.
