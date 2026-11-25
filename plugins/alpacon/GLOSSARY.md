# Vulnerability remediation

The words the `vuln-*` skills use for checking and patching a vulnerable package across Alpacon servers.

## Language

- **Preview**: What a package transaction would install, upgrade or remove on one server, read before the recipe runs there. _Avoid_: dry run, simulation (as a name for the step).
- **Preflight**: The read-only state of one server that bears on whether it can take the transaction now, read alongside its preview. _Avoid_: precheck, health check, readiness.
- **Preflight anomaly**: A preflight value that is wrong as a matter of fact, with no threshold to choose, and that sends the decision back to a person before that server runs. _Avoid_: preflight failure, blocker.
- **Unreadable preflight**: A preflight value that should have been read and was not, so nothing is known about it; it is not an anomaly, but it also sends the decision back to a person. _Avoid_: unknown, which is reserved for a value the tool never reports.
- **Pending security update**: A Debian or Ubuntu package with a newer version in the distribution's security pocket than the one installed, as the pending security updates check lists it. _Avoid_: vulnerability, which the path cannot rule out.
- **Kept back**: A pending update that `apt-get upgrade` leaves alone because it needs a new package, would remove one, or is deferred by phasing; an Ubuntu kernel update always is one. _Avoid_: skipped, blocked.
- **Held package**: A package someone marked with `apt-mark hold`; the skills show it and never upgrade it. _Avoid_: pinned, which is an apt preferences setting.
