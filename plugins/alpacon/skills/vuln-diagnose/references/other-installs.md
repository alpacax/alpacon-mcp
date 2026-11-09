# Other installation checks

## Container images

From the host, the check can read which image a container runs, not what is inside it. A library inside the image (a Python package in a Langflow container, for instance) is `unknown` from the host; say which container and image, so a person can check the image itself. Do not `docker exec` into a container from this skill: it runs a process inside the workload, which is more than a read.

```sh
docker ps --format 'container={{.Names}} image={{.Image}}' 2>&1 || podman ps --format 'container={{.Names}} image={{.Image}}' 2>&1
```

- The image tag carries a version, and the image is the vulnerable software: compare the tag with the fixed version.
- The tag is `latest`, a branch name, or a digest only: `unknown`. A digest says which build runs but not which version it is, unless the vendor publishes digests per version.
- Reading the Docker socket needs root or membership of the `docker` group, which amounts to root. If the command fails with a permission error, the row is `unknown`; do not add `sudo` to get past it without the person deciding the session should carry it.
- Kubernetes workloads are out of reach from a node's shell; report them as `unknown`.

## Vendor installs

Software installed from a vendor's installer or archive (Metabase, PaperCut, Zimbra) is invisible to the package manager. The vendor documents how to read its version: a command, a file, or an HTTP endpoint. Use what the vendor documents, and ask the person when you do not know it. Examples:

- Metabase: `curl -s http://localhost:3000/api/session/properties` and read `version.tag`.
- Zimbra: `/opt/zimbra/bin/zmcontrol -v`, run as `username: zimbra` in a session approved for that account, not through `su`.
- A JAR: the version in its file name, or `Implementation-Version` in its manifest (`unzip -p app.jar META-INF/MANIFEST.MF`).
- A binary: the version in its file name, its package metadata, or a version file the vendor ships beside it.

Rules:

- Do not run the vulnerable binary or JAR to ask its version (`--version`, `java -jar app.jar --version`): that executes the code under suspicion, as whatever account the check uses. Read metadata instead. If the vendor documents no other way, show the person that the check runs the program and wait for them to agree.

- Query only `localhost` or the host's own address. The check is about this server's copy.
- Never put a password or token on the command line. An endpoint that needs credentials is `unknown` unless the person supplies a check that reads them from the host.
- Print `installed=<version>`; a check that could not read the version prints `verdict=unknown` with a reason.

## Source builds

When the advisory names a fixing commit and the software is built from a checkout on the server, ask git whether the commit is in the checkout's history:

```sh
git -C /opt/app merge-base --is-ancestor '3f2a9c1' HEAD; case $? in 0) echo verdict=not_affected;; 1) echo verdict=affected;; *) echo "verdict=unknown reason=git-could-not-answer";; esac
```

- Exit 0: the fix is an ancestor of `HEAD`.
- Exit 1: it is not, so the build predates the fix.
- Anything else, usually 128: git could not answer. The commit may be missing from a shallow clone, the path may not be a checkout, or git may refuse a repository owned by another account. Do not `git fetch` to find out; it changes the repository. Report `unknown`.

A backported fix is cherry-picked under a different commit id, so a release branch can carry the fix and still answer exit 1. When the project backports, ask for the fixing commit on that branch.

A checkout says what runs only if the running binary was built from it. When nobody can confirm the deployed artifact came from this checkout, the verdict is `unknown` whatever git answered, with that in the reason.

## The person's own check command

When none of the install methods fits, the person supplies the command. Before running it:

- It must only read. A command that installs, edits, restarts, or deletes anything belongs in `vuln-remediate`, not here; say so and do not run it.
- It must print one line per server that says the verdict, ideally `verdict=affected`, `verdict=not_affected`, or `verdict=unknown`. If it prints something else, agree with the person how to read its output before running it.

Output that does not match what you agreed is `unknown`, with the output in the reason.
