# Vulnerability remediation

The words the `vuln-*` skills use for checking and patching a vulnerable package across Alpacon servers.

## Language

- **Preview**: What a package transaction would install, upgrade or remove on one server, read before the recipe runs there. _Avoid_: dry run, simulation (as a name for the step).
- **Preflight**: The read-only state of one server that bears on whether it can take the transaction now, read alongside its preview. _Avoid_: precheck, health check, readiness.
- **Preflight anomaly**: A preflight value that is wrong as a matter of fact, with no threshold to choose, and that sends the decision back to a person before that server runs. _Avoid_: preflight failure, blocker.
- **Unreadable preflight**: A preflight value that should have been read and was not, so nothing is known about it; it is not an anomaly, but it also sends the decision back to a person. _Avoid_: unknown, which is reserved for a value the tool never reports.
