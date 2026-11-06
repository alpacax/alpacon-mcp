# pip and npm packages

A language package lives in an application's environment, not on the system, so the person has to say which application and where it lives. If they do not know, find the interpreter or directory from the running process, read-only: `ps -eo pid,user,args | grep -i '<app>'` shows the Python path of a virtualenv or the directory a Node process started from. A server can run several copies of an application; give each its own row.

The check prints the installed version, and the agent compares it with the fixed version. Compare release numbers numerically (`1.10.0` is newer than `1.9.3`). A pre-release, a local version (`+cu121`), or anything you cannot order with certainty makes the row `unknown`, with the version in the reason.

## pip

Use the application's own interpreter, never the system `python3` unless the application runs on it:

```sh
/opt/langflow/.venv/bin/python -c "import importlib.metadata as m; print('installed=' + m.version('langflow'))" 2>/dev/null || echo "installed=none"
```

`importlib.metadata` needs no `pip` in the environment, which many deployed virtualenvs leave out.

## npm

A vulnerable npm package is usually a transitive dependency, and an application can hold several copies at different versions. Read every copy:

```sh
cd /srv/app && find node_modules -path '*/node_modules/mcp-atlassian/package.json' -exec grep -m1 '"version"' {} + 2>/dev/null || echo "installed=none"
```

The row is `affected` if any copy is older than the fixed version. An application shipped as a bundle without `node_modules` hides its dependencies from this check, so it is `unknown`.
