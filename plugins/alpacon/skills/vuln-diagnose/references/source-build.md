# Source builds

When the advisory names a fixing commit and the software is built from a checkout on the server, ask git whether the commit is in the checkout's history:

```sh
git -C /opt/app merge-base --is-ancestor 3f2a9c1 HEAD; case $? in 0) echo verdict=not_affected;; 1) echo verdict=affected;; *) echo "verdict=unknown reason=commit-not-in-clone";; esac
```

- Exit 0: the fix is an ancestor of `HEAD`.
- Exit 1: it is not, so the build predates the fix.
- Anything else, usually 128: the commit is not in the local clone (a shallow clone, or not fetched). Do not `git fetch` to find out; it changes the repository. Report `unknown`.

A checkout says what was built only if the running binary was built from it. When the deployed artifact may come from elsewhere, add that to the reason even when the verdict is `not_affected`.
