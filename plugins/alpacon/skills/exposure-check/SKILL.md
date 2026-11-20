---
name: exposure-check
description: Check Alpacon servers for services left reachable—listening ports bound beyond loopback, a Docker API over TCP or a world-writable Docker socket, endpoints that answer without authentication, and factory default credentials still accepted—read-only. Use when someone asks whether a server exposes something an attacker could walk into rather than whether a version is vulnerable ("is the Docker API open on our hosts?", "is MinIO still on minioadmin?", "what is listening on web-01?", "does /terminal/ws answer without a login?"). Changes nothing on the servers.
---

# Check servers for exposed services

Answer one question per server: does it expose a listed port, a Docker API, or an endpoint or login that lets anyone in? This skill only reads; closing a port, changing a credential or editing a daemon is a person's change, because each can cut a service off. Follow the `using-alpacon` skill for workspaces, server UUIDs, Work Sessions, approvals, and multi-server results.

## Inputs

- What to check: ports, endpoints, and default credentials, a preset from [checks.md](references/checks.md#presets) (Docker API, MinIO), or both.
- Each value goes into the command as data. A port is `^[1-9][0-9]{0,4}$` and at most 65535, a path is `^/[A-Za-z0-9._~/-]*$`, an endpoint method is `GET` or `WS`, a scheme is `http` or `https`. Ask about anything else and do not build the command.
- A credential is only a publicly documented factory default (`minioadmin:minioadmin`). The command text, credential included, is recorded in Alpacon's command history, so never put a real password in it. A credential holding a `'` or a newline cannot go inside the command's quotes: ask.

## Steps

1. Call `list_servers`. Every server in scope stays in the report. A server with `is_connected: false` is `unknown` (offline), and a Windows server is `unknown` (unsupported); the rest are candidates.
2. Fill [the check](references/checks.md#the-check) with the ports and endpoints, and show it exactly as it will run, with the servers and the named non-root account it runs as. Say that each endpoint gets one request per address its port listens on, which the service may log. Wait for the person to agree.
3. Reuse a supplied active Work Session whose servers, `command` scope and ordinary account cover the check, and leave it open afterwards. Otherwise open one with the `command` scope only and `target_account_username` set to that account, described as "read listening sockets and Docker settings, probe the listed endpoints; changes nothing", and close it once the results are read.
4. Run the check once with `execute_command_multi_server`, passing that account as `username` and a `purpose` that says it only reads sockets and settings and probes the listed endpoints, and read each server's result with `check_command_status`.
5. Show each server's `verdict`, `findings` and `unknowns`, then its `listen` lines. A server whose command failed or whose output does not parse is `unknown`.
6. Default credentials, only when the input or preset names one: run [the login check](references/checks.md#default-credential-login) on the servers whose check shows that port listening beyond loopback. Before it runs, show the filled login command exactly as it will run, with those servers and the account, ask separately, and say that it is a real login attempt, one per address the port listens on, that it lands in the service's access log and may count toward a lockout, and that its command text with the credential is recorded in Alpacon's command history. Skip it if the person declines; never treat their agreement to the first check as agreement to this one. An `accepted` result makes the server `exposed`.

## Verdicts

- `exposed`: the check printed at least one finding, or a default credential was `accepted`.
- `not_exposed`: every check ran and found nothing.
- `unknown`: offline, unsupported, failed, or an item the check could not read or judge, listed in `unknowns`, with no finding.

Never fold `unknown` into `not_exposed`.

## Report

One table, one row per server in scope: name, verdict, findings, unknowns with their reasons, and the login result where it ran. Below it, each server's `listen` lines.

Say that a socket bound to `0.0.0.0`, `::` or an interface address shows what the host listens on, not what the internet can reach: firewalls and security groups decide that, and the person checks them. When `processes=own-only`, say that other accounts' process names were not visible. Say what the check does not cover: UDP, ports and paths nobody listed, a site served only under a host name (name-based virtual hosts), since each probe goes to an IP address, containers that mount the Docker socket, and scanning from outside the host. Close with the change a person would make for each finding; this skill makes none.
