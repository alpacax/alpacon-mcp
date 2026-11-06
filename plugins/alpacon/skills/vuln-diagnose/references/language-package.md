# pip and npm packages

A language package lives in an application's environment, not on the system, so the person has to say which application and where it lives. If they do not know, find the interpreter or directory from the running process, read-only: `ps -eo pid,user,args | grep -i '<app>'` shows the Python path of a virtualenv or the directory a Node process started from. A server can run several copies of an application; give each its own row.

Both checks print `installed=<versions>` or `installed=none`, and anything that stops them from looking prints `verdict=unknown` with a reason. A check that could not look must never print `installed=none`.

## pip

Use the application's own interpreter, never the system `python3` unless the application runs on it:

```sh
p=/opt/langflow/.venv/bin/python; n=langflow; [ -x "$p" ] || { echo "verdict=unknown reason=no-interpreter"; exit 0; }; "$p" -c "import importlib.metadata as m, sys; n=sys.argv[1].lower().replace('_', '-'); print('installed=' + next((d.version for d in m.distributions() if (d.metadata['Name'] or '').lower().replace('_', '-') == n), 'none'))" "$n" 2>/dev/null || echo "verdict=unknown reason=check-failed"
```

`importlib.metadata` needs no `pip` in the environment, which many deployed virtualenvs leave out. An interpreter older than Python 3.8 lacks it and the check reports `check-failed`.

## npm

A vulnerable npm package is usually a transitive dependency, and an application can hold several copies at different versions. Read every copy, the top-level one included:

```sh
cd /srv/app 2>/dev/null && [ -d node_modules ] || { echo "verdict=unknown reason=no-node_modules"; exit 0; }; command -v node >/dev/null || { echo "verdict=unknown reason=no-node"; exit 0; }; v=$(find "$PWD/node_modules" -path '*/node_modules/axios/package.json' -exec node -p 'require(process.argv[1]).version' {} \; | sort -u | tr '\n' ' '); echo "installed=${v:-none}"
```

The row is `affected` if any copy is older than the fixed version. An application shipped as a bundle without `node_modules` hides its dependencies from this check, so it is `unknown`.
