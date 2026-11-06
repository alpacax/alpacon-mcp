# Vendor installs

Software installed from a vendor's installer or archive (Metabase, PaperCut, Zimbra) is invisible to the package manager. The vendor documents how to read its version: a command, a file, or an HTTP endpoint. Use what the vendor documents, and ask the person when you do not know it. Examples:

- Metabase: `curl -s http://localhost:3000/api/session/properties` and read `version.tag`.
- Zimbra: `/opt/zimbra/bin/zmcontrol -v`, run as `username: zimbra` in a session approved for that account, not through `su`.
- A JAR or binary: the version in its file name, or its `--version` output.

Rules:

- Query only `localhost` or the host's own address. The check is about this server's copy.
- Never put a password or token on the command line. An endpoint that needs credentials is `unknown` unless the person supplies a check that reads them from the host.
- Print `installed=<version>`; a check that could not read the version prints `verdict=unknown` with a reason.
