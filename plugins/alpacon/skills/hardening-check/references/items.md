# KISA 2026 Unix hardening items

Edition: kisa-2026

Published: 2025-12-24

ATT&CK release: 20.1

This registry follows the Unix server items in KISA's *2026 Detailed Guide for Technical Vulnerability Analysis and Evaluation of Critical Information Infrastructure*, posted on 2025-12-24. The pass criteria below are translated from that guide; ATT&CK mappings describe the techniques blocked by each individual setting, not every technique covered by the mitigation.

<!-- BEGIN GENERATED COUNTS -->
The script judges 51 of the 67 items. 13 need a person, 3 belong to another skill, none lies wholly outside the host, and 44 of those 51 carry an ATT&CK mapping.
<!-- END GENERATED COUNTS -->

## Judged by the script

| Item | ATT&CK mitigation | ATT&CK technique | Tactic |
| --- | --- | --- | --- |
| U-01 Restrict remote root login | M1042 Disable or Remove Feature or Program | T1021.004 Remote Services: SSH | Lateral Movement |
| U-02 Configure password management policy | M1027 Password Policies | T1110.001 Brute Force: Password Guessing<br>T1110.002 Brute Force: Password Cracking<br>T1110.003 Brute Force: Password Spraying | Credential Access |
| U-03 Configure account lockout threshold | M1036 Account Use Policies | T1110.001 Brute Force: Password Guessing<br>T1110.003 Brute Force: Password Spraying | Credential Access |
| U-04 Protect the password file | M1026 Privileged Account Management | T1003.008 OS Credential Dumping: /etc/passwd and /etc/shadow | Credential Access |
| U-05 Prohibit UID 0 for non-root accounts | M1026 Privileged Account Management | T1078.003 Valid Accounts: Local Accounts | Initial Access<br>Persistence<br>Privilege Escalation<br>Stealth |
| U-06 Restrict use of su | M1026 Privileged Account Management | T1548 Abuse Elevation Control Mechanism | Privilege Escalation |
| U-10 Prohibit duplicate UIDs | M1018 User Account Management | T1078.003 Valid Accounts: Local Accounts | Initial Access<br>Persistence<br>Privilege Escalation<br>Stealth |
| U-12 Configure session timeout | M1026 Privileged Account Management | T1563 Remote Service Session Hijacking | Lateral Movement |
| U-13 Use a secure password hashing algorithm | M1027 Password Policies | T1110.002 Brute Force: Password Cracking | Credential Access |
| U-14 Secure root home and PATH settings | M1022 Restrict File and Directory Permissions | T1574.007 Hijack Execution Flow: Path Interception by PATH Environment Variable | Execution<br>Stealth |
| U-15 Assign owners to files and directories | M1022 Restrict File and Directory Permissions | T1222.002 File and Directory Permissions Modification: Linux and Mac Permissions | Defense Impairment |
| U-16 Secure /etc/passwd ownership and permissions | M1022 Restrict File and Directory Permissions | T1098 Account Manipulation | Persistence<br>Privilege Escalation |
| U-17 Secure system startup script permissions | M1022 Restrict File and Directory Permissions | T1037.004 Boot or Logon Initialization Scripts: RC Scripts<br>T1543.002 Create or Modify System Process: Systemd Service | Persistence<br>Privilege Escalation |
| U-18 Secure /etc/shadow ownership and permissions | M1026 Privileged Account Management | T1003.008 OS Credential Dumping: /etc/passwd and /etc/shadow | Credential Access |
| U-19 Secure /etc/hosts ownership and permissions | M1022 Restrict File and Directory Permissions | T1565.001 Data Manipulation: Stored Data Manipulation | Impact |
| U-20 Secure /etc/(x)inetd.conf ownership and permissions | M1022 Restrict File and Directory Permissions | T1543 Create or Modify System Process | Persistence<br>Privilege Escalation |
| U-21 Secure /etc/(r)syslog.conf ownership and permissions | M1022 Restrict File and Directory Permissions | T1685 Disable or Modify Tools | Defense Impairment |
| U-22 Secure /etc/services ownership and permissions | M1022 Restrict File and Directory Permissions | T1565.001 Data Manipulation: Stored Data Manipulation | Impact |
| U-24 Secure user and system environment files | M1022 Restrict File and Directory Permissions | T1546.004 Event Triggered Execution: Unix Shell Configuration Modification | Persistence<br>Privilege Escalation |
| U-27 Prohibit unsafe .rhosts and hosts.equiv use | M1035 Limit Access to Resource Over Network | T1021 Remote Services | Lateral Movement |
| U-29 Secure hosts.lpd ownership and permissions | M1022 Restrict File and Directory Permissions | T1565.001 Data Manipulation: Stored Data Manipulation | Impact |
| U-30 Manage the system umask | M1022 Restrict File and Directory Permissions | T1565.001 Data Manipulation: Stored Data Manipulation | Impact |
| U-31 Secure home directory ownership and permissions | M1022 Restrict File and Directory Permissions | T1546.004 Event Triggered Execution: Unix Shell Configuration Modification | Persistence<br>Privilege Escalation |
| U-32 Ensure configured home directories exist | — | — | — |
| U-34 Disable the Finger service | M1028 Operating System Configuration | T1087.001 Account Discovery: Local Account | Discovery |
| U-35 Restrict anonymous access to sharing services | M1035 Limit Access to Resource Over Network | T1133 External Remote Services | Initial Access<br>Persistence |
| U-36 Disable r-command services | M1042 Disable or Remove Feature or Program | T1021 Remote Services | Lateral Movement |
| U-37 Secure crontab and at files | M1022 Restrict File and Directory Permissions | T1053 Scheduled Task/Job | Execution<br>Persistence<br>Privilege Escalation |
| U-38 Disable services vulnerable to denial of service | M1042 Disable or Remove Feature or Program | T1210 Exploitation of Remote Services | Lateral Movement |
| U-40 Control NFS access | M1035 Limit Access to Resource Over Network | T1021 Remote Services | Lateral Movement |
| U-41 Disable automountd | — | — | — |
| U-42 Disable unnecessary RPC services | M1042 Disable or Remove Feature or Program | T1210 Exploitation of Remote Services | Lateral Movement |
| U-43 Disable NIS or use NIS+ | M1042 Disable or Remove Feature or Program | T1557 Adversary-in-the-Middle | Credential Access<br>Collection |
| U-44 Disable tftp, talk, and ntalk | M1042 Disable or Remove Feature or Program | T1210 Exploitation of Remote Services | Lateral Movement |
| U-46 Prevent ordinary users from running the mail service | M1026 Privileged Account Management | T1569 System Services | Execution |
| U-47 Restrict mail relay | M1054 Software Configuration | T1667 Email Bombing | Impact |
| U-48 Disable SMTP expn and vrfy commands | M1028 Operating System Configuration | T1087.001 Account Discovery: Local Account | Discovery |
| U-50 Restrict DNS zone transfers | — | — | — |
| U-51 Prohibit unsafe DNS dynamic updates | M1035 Limit Access to Resource Over Network | T1190 Exploit Public-Facing Application | Initial Access |
| U-52 Disable Telnet | M1042 Disable or Remove Feature or Program | T1021 Remote Services | Lateral Movement |
| U-53 Limit FTP service information disclosure | — | — | — |
| U-54 Disable unencrypted FTP | M1041 Encrypt Sensitive Information | T1040 Network Sniffing | Credential Access<br>Discovery |
| U-55 Restrict the FTP account shell | M1036 Account Use Policies | T1078 Valid Accounts | Initial Access<br>Persistence<br>Privilege Escalation<br>Stealth |
| U-57 Configure ftpusers | M1026 Privileged Account Management | T1078.003 Valid Accounts: Local Accounts | Initial Access<br>Persistence<br>Privilege Escalation<br>Stealth |
| U-59 Use a secure SNMP version | — | — | — |
| U-60 Configure a complex SNMP community string | M1027 Password Policies | T1110.001 Brute Force: Password Guessing<br>T1110.003 Brute Force: Password Spraying | Credential Access |
| U-61 Configure SNMP access control | M1035 Limit Access to Resource Over Network | T1190 Exploit Public-Facing Application | Initial Access |
| U-62 Configure login warning messages | — | — | — |
| U-63 Secure sudo access configuration | M1022 Restrict File and Directory Permissions | T1548.003 Abuse Elevation Control Mechanism: Sudo and Sudo Caching | Privilege Escalation |
| U-65 Configure NTP and time synchronization | — | — | — |
| U-67 Secure log directory ownership and permissions | M1022 Restrict File and Directory Permissions | T1685.006 Disable or Modify Tools: Clear Linux or Mac System Logs | Defense Impairment |

### Without an ATT&CK mapping

- `U-32`: Ensuring a configured home directory exists prevents a login from defaulting to the root directory, but does not block a technique in a live v20.1 mitigation relationship.
- `U-41`: Disabling automountd removes automatic mounting, but its direct threat effect has no matching live v20.1 mitigation relationship.
- `U-50`: Restricting DNS zone transfers protects reconnaissance data, but no live Enterprise mitigation relationship covers the relevant pre-compromise collection behavior.
- `U-53`: Suppressing an FTP banner reduces disclosed service information, but no live v20.1 mitigation relationship covers that disclosure setting.
- `U-59`: SNMPv3 can run without privacy encryption, so the guide's version-only pass criterion does not always block network sniffing.
- `U-62`: A login warning communicates policy but does not block a technique covered by a live Enterprise ATT&CK v20.1 `mitigates` relationship.
- `U-65`: Time synchronization supports reliable timestamps but does not itself block a technique covered by a live Enterprise ATT&CK v20.1 `mitigates` relationship.

### Pass criteria

- `U-01`: Remote terminal services are unused, or direct remote login as root is blocked. PDF p. 12.
- `U-02`: Passwords contain at least 8 characters including letters, digits, and special characters; minimum age is at least 1 day, maximum age is 90 days or less, and the last 4 passwords cannot be reused. PDF pp. 15–20.
- `U-03`: The account lockout threshold is configured at 10 failed logins or fewer. PDF p. 21.
- `U-04`: Shadow passwords are used, or passwords are stored encrypted. PDF p. 25.
- `U-05`: No account other than root has UID 0. PDF p. 27.
- `U-06`: Use of `su` is restricted to an authorized group; no restriction is required when root is the only user account. PDF p. 29.
- `U-10`: No two user accounts have the same UID. PDF p. 34.
- `U-12`: The session timeout is configured at 600 seconds or fewer. PDF p. 36.
- `U-13`: Every stored password uses SHA-2 or a stronger secure hashing algorithm. PDF p. 37.
- `U-14`: Root's `PATH` does not contain `.` or an empty entry at the beginning or in the middle. PDF p. 39.
- `U-15`: No file or directory has an owner that does not exist. PDF p. 40.
- `U-16`: `/etc/passwd` is owned by root and has no permission bit beyond 644. PDF p. 41.
- `U-17`: System startup scripts are owned by root and are not writable by ordinary users. PDF p. 42.
- `U-18`: `/etc/shadow` is owned by root and has no permission bit beyond 400. PDF p. 44.
- `U-19`: `/etc/hosts` is owned by root and has no permission bit beyond 644. PDF p. 45.
- `U-20`: `/etc/inetd.conf` and `/etc/xinetd.conf`, when present, are owned by root and have no permission bit beyond 600. PDF p. 46.
- `U-21`: `/etc/syslog.conf` and `/etc/rsyslog.conf`, when present, are owned by root, bin, or sys and have no permission bit beyond 640. PDF p. 48.
- `U-22`: `/etc/services` is owned by root, bin, or sys and has no permission bit beyond 644. PDF p. 49.
- `U-24`: Each home environment file is owned by root or its account and is writable only by root and the owner. PDF p. 51.
- `U-27`: The r-command services are unused, or every `.rhosts` and `hosts.equiv` file is owned by root or the applicable account, has no permission bit beyond 600, and contains no `+` entry. PDF p. 54.
- `U-29`: `/etc/hosts.lpd` is absent, or it is owned by root and has no permission bit beyond 600. PDF p. 61.
- `U-30`: The system umask is 022 or more restrictive. PDF p. 62.
- `U-31`: Each login-capable account's existing home directory is owned by that account and is not writable by other users. PDF p. 65.
- `U-32`: Each login-capable account's configured home directory exists. PDF p. 66.
- `U-34`: The Finger service is disabled. PDF p. 68.
- `U-35`: Anonymous access to sharing services is restricted. PDF p. 70.
- `U-36`: Unnecessary r-command services are disabled. PDF p. 77.
- `U-37`: Ordinary users cannot execute `crontab` or `at`, and cron and at files have no permission bit beyond 640. PDF p. 80.
- `U-38`: Services vulnerable to denial of service are disabled. PDF p. 83.
- `U-40`: Every NFS export restricts access, and the export configuration files are root-owned with no permission bit beyond 644. PDF p. 89.
- `U-41`: The automountd service is disabled. PDF p. 93.
- `U-42`: Unnecessary RPC services are disabled. PDF p. 96.
- `U-43`: NIS is disabled, or NIS+ is used when the service is necessary. PDF p. 99.
- `U-44`: The tftp, talk, and ntalk services are disabled. PDF p. 102.
- `U-46`: Ordinary users are prevented from running the mail service. PDF p. 111.
- `U-47`: SMTP relay is restricted. PDF p. 113.
- `U-48`: SMTP is configured with the `noexpn` and `novrfy` options. PDF p. 116.
- `U-50`: DNS zone transfers are allowed only to authorized users or secondary name servers. PDF p. 121.
- `U-51`: DNS dynamic updates are disabled or protected by appropriate access controls. PDF p. 122.
- `U-52`: Telnet is disabled for remote access. PDF p. 124.
- `U-53`: The FTP login banner discloses no service information. PDF p. 127.
- `U-54`: Unencrypted FTP is disabled. PDF p. 131.
- `U-55`: The FTP account uses `/bin/false` or `/sbin/nologin`. PDF p. 134.
- `U-57`: FTP blocks root login. PDF p. 139.
- `U-59`: SNMP uses version 3 or later. PDF p. 143.
- `U-60`: The SNMP community is not `public` or `private` and is at least 10 characters with letters and digits, or at least 8 characters with letters, digits, and special characters; an SNMPv3 authentication password meets the same complexity. PDF p. 145.
- `U-61`: SNMP access control is configured. PDF p. 148.
- `U-62`: Warning messages are configured for server, Telnet, FTP, SMTP, and DNS logins. PDF p. 150.
- `U-63`: `/etc/sudoers` is owned by root and has no permission bit beyond 640. PDF p. 159.
- `U-65`: NTP has a configured server and synchronizes with a selected source using chrony, ntp, or systemd-timesyncd. PDF pp. 164–165.
- `U-67`: Log files are owned by root and have no permission bit beyond 644. PDF p. 171.

### Interpretations

- `U-01`: Only `PermitRootLogin no` satisfies the SSH part of the criterion. Any value that still permits direct root authentication fails.
- `U-13`: yescrypt (`$y$`) passes because the guide requires SHA-2 or stronger and lists yescrypt as an accepted Debian `ENCRYPT_METHOD` value on PDF p. 38.
- `U-14`: The check runs root's login shell, which executes root's startup files exactly as a root login does.
- `U-18`: Debian and Ubuntu's `640 root:shadow` default fails the guide's `root` and 400-or-less requirement. The report marks it `note=distro-default` because tightening it may affect programs that authenticate through `unix_chkpwd`.
- `U-31`: The guide refers to each user's home directory (PDF p. 65). The check includes only accounts with a shell listed in `/etc/shells`, since system account homes such as `/bin` are root-owned by design.
- `U-32`: The guide refers to each user's home directory (PDF p. 66). The check includes only accounts with a shell listed in `/etc/shells`, since system account homes such as `/nonexistent` are absent by design.
- `U-40`: With zero exports in `/etc/exports` and `/etc/exports.d/*.exports`, no share lacks access control (PDF p. 89). The export configuration files must still be root-owned with no permission bit beyond 644.
- `U-63`: The guide's pass line names mode 640 and its fail line says beyond 640, so a stricter mode such as the 440 that Ubuntu and Rocky Linux ship passes.

## Needs a person

- `U-07 Remove unnecessary accounts` [person]: Decide which login-capable accounts have no operational owner or purpose; the script reports `login_accounts`, `names`, and `more`. PDF p. 31.
- `U-08 Minimize membership of the administrator group` [person]: Decide which non-root administrator-group members lack an approved administrative role; the script reports `admin_accounts`, `names`, and `more`. PDF p. 32.
- `U-09 Remove GIDs without accounts` [person]: Decide which groups serve no system-management or operational purpose; the script reports `orphan_groups`, `names`, and `more`. PDF p. 33.
- `U-11 Check user shells` [person]: Decide which accounts do not require login; the script reports `login_shell_accounts`, `names`, and `more`. PDF p. 35.
- `U-23 Review SUID, SGID, and sticky-bit files` [person]: Decide which privileged files are unnecessary or suspicious because the guide supplies no fixed executable list; the script reports `privileged_files`, `paths`, and `more`. PDF p. 50.
- `U-25 Review world-writable files` [person]: Decide whether every world-writable file has a known operational reason; the script reports `world_writable`, `paths`, and `more`. PDF p. 52.
- `U-26 Review non-device files under /dev` [person]: Decide whether each ordinary file under `/dev` is legitimate; the script reports `non_device_files`, `paths`, and `more`. PDF p. 53.
- `U-28 Review connection IP and port restrictions` [person]: Decide which source addresses and ports the server's purpose requires; the script reports `firewall`, `tcp_wrappers`, and `listeners`. PDF p. 56.
- `U-33 Review hidden files and directories` [person]: Decide which hidden paths are unnecessary or suspicious; the script reports `hidden_paths`, `paths`, and `more`. PDF p. 67.
- `U-39 Disable unnecessary NFS` [person]: Decide whether the server's role requires NFS; the script reports `nfs_installed` and `nfs_active`. PDF p. 86.
- `U-56 Configure FTP access control` [person]: Decide which source addresses or hosts require FTP access; the script reports `ftp_access_control` and `rules`. PDF p. 135.
- `U-58 Disable unnecessary SNMP` [person]: Decide whether the server's monitoring role requires SNMP; the script reports `snmp_installed` and `snmp_active`. PDF p. 141.
- `U-66 Configure system logging according to policy` [person]: Decide which events the internal security policy requires and whether the configuration implements them; the script reports `logging`, `destinations`, and `remote`. PDF p. 166.

## Checked elsewhere

- `U-45 Check the mail service version` [pointer:vuln-diagnose]: Check a named mail-server advisory with `vuln-diagnose`; version currency depends on current vendor security information. PDF p. 105.
- `U-49 Apply DNS security patches` [pointer:vuln-diagnose]: Check a named BIND advisory with `vuln-diagnose`; patch currency depends on current vendor security information. PDF p. 118.
- `U-64 Apply periodic security patches and vendor recommendations` [pointer:vuln-patch]: Use `vuln-patch` and `references/pending-security-updates.md` for pending security updates; whether the organization has a periodic patch policy remains outside the host. PDF p. 160.

Listening ports and default credentials are checked by `exposure-check`. The policy half of U-66 remains outside the host.

## By tactic

<!-- BEGIN GENERATED BY TACTIC -->
### Initial Access

| Technique | Items |
| --- | --- |
| T1078 Valid Accounts | U-55 M1036 |
| T1078.003 Valid Accounts: Local Accounts | U-05 M1026, U-10 M1018, U-57 M1026 |
| T1133 External Remote Services | U-35 M1035 |
| T1190 Exploit Public-Facing Application | U-51 M1035, U-61 M1035 |

### Execution

| Technique | Items |
| --- | --- |
| T1053 Scheduled Task/Job | U-37 M1022 |
| T1569 System Services | U-46 M1026 |
| T1574.007 Hijack Execution Flow: Path Interception by PATH Environment Variable | U-14 M1022 |

### Persistence

| Technique | Items |
| --- | --- |
| T1037.004 Boot or Logon Initialization Scripts: RC Scripts | U-17 M1022 |
| T1053 Scheduled Task/Job | U-37 M1022 |
| T1078 Valid Accounts | U-55 M1036 |
| T1078.003 Valid Accounts: Local Accounts | U-05 M1026, U-10 M1018, U-57 M1026 |
| T1098 Account Manipulation | U-16 M1022 |
| T1133 External Remote Services | U-35 M1035 |
| T1543 Create or Modify System Process | U-20 M1022 |
| T1543.002 Create or Modify System Process: Systemd Service | U-17 M1022 |
| T1546.004 Event Triggered Execution: Unix Shell Configuration Modification | U-24 M1022, U-31 M1022 |

### Privilege Escalation

| Technique | Items |
| --- | --- |
| T1037.004 Boot or Logon Initialization Scripts: RC Scripts | U-17 M1022 |
| T1053 Scheduled Task/Job | U-37 M1022 |
| T1078 Valid Accounts | U-55 M1036 |
| T1078.003 Valid Accounts: Local Accounts | U-05 M1026, U-10 M1018, U-57 M1026 |
| T1098 Account Manipulation | U-16 M1022 |
| T1543 Create or Modify System Process | U-20 M1022 |
| T1543.002 Create or Modify System Process: Systemd Service | U-17 M1022 |
| T1546.004 Event Triggered Execution: Unix Shell Configuration Modification | U-24 M1022, U-31 M1022 |
| T1548 Abuse Elevation Control Mechanism | U-06 M1026 |
| T1548.003 Abuse Elevation Control Mechanism: Sudo and Sudo Caching | U-63 M1022 |

### Stealth

| Technique | Items |
| --- | --- |
| T1078 Valid Accounts | U-55 M1036 |
| T1078.003 Valid Accounts: Local Accounts | U-05 M1026, U-10 M1018, U-57 M1026 |
| T1574.007 Hijack Execution Flow: Path Interception by PATH Environment Variable | U-14 M1022 |

### Defense Impairment

| Technique | Items |
| --- | --- |
| T1222.002 File and Directory Permissions Modification: Linux and Mac Permissions | U-15 M1022 |
| T1685 Disable or Modify Tools | U-21 M1022 |
| T1685.006 Disable or Modify Tools: Clear Linux or Mac System Logs | U-67 M1022 |

### Credential Access

| Technique | Items |
| --- | --- |
| T1003.008 OS Credential Dumping: /etc/passwd and /etc/shadow | U-04 M1026, U-18 M1026 |
| T1040 Network Sniffing | U-54 M1041 |
| T1110.001 Brute Force: Password Guessing | U-02 M1027, U-03 M1036, U-60 M1027 |
| T1110.002 Brute Force: Password Cracking | U-02 M1027, U-13 M1027 |
| T1110.003 Brute Force: Password Spraying | U-02 M1027, U-03 M1036, U-60 M1027 |
| T1557 Adversary-in-the-Middle | U-43 M1042 |

### Discovery

| Technique | Items |
| --- | --- |
| T1040 Network Sniffing | U-54 M1041 |
| T1087.001 Account Discovery: Local Account | U-34 M1028, U-48 M1028 |

### Lateral Movement

| Technique | Items |
| --- | --- |
| T1021 Remote Services | U-27 M1035, U-36 M1042, U-40 M1035, U-52 M1042 |
| T1021.004 Remote Services: SSH | U-01 M1042 |
| T1210 Exploitation of Remote Services | U-38 M1042, U-42 M1042, U-44 M1042 |
| T1563 Remote Service Session Hijacking | U-12 M1026 |

### Collection

| Technique | Items |
| --- | --- |
| T1557 Adversary-in-the-Middle | U-43 M1042 |

### Impact

| Technique | Items |
| --- | --- |
| T1565.001 Data Manipulation: Stored Data Manipulation | U-19 M1022, U-22 M1022, U-29 M1022, U-30 M1022 |
| T1667 Email Bombing | U-47 M1054 |
<!-- END GENERATED BY TACTIC -->
