# Source builds

When the advisory names a fixing commit and the software is built from a checkout on the server, ask git whether the commit is in the checkout's history:

```sh
git -C /opt/app merge-base --is-ancestor 3f2a9c1 HEAD; case $? in 0) echo verdict=not_affected;; 1) echo verdict=affected;; *) echo "verdict=unknown reason=git-could-not-answer";; esac
```

- Exit 0: the fix is an ancestor of `HEAD`.
- Exit 1: it is not, so the build predates the fix.
- Anything else, usually 128: git could not answer. The commit may be missing from a shallow clone, the path may not be a checkout, or git may refuse a repository owned by another account. Do not `git fetch` to find out; it changes the repository. Report `unknown`.

A backported fix is cherry-picked under a different commit id, so a release branch can carry the fix and still answer exit 1. When the project backports, ask for the fixing commit on that branch.

A checkout says what runs only if the running binary was built from it. When nobody can confirm the deployed artifact came from this checkout, the verdict is `unknown` whatever git answered, with that in the reason.
