# pip and npm packages

A language package lives in an application's environment, not on the system, so the person has to say which application and where it lives. If they do not know, find the interpreter or directory from the running process, read-only: `ps -eo pid,user,args | grep -i '<app>'` shows the Python path of a virtualenv or the directory a Node process started from. A server can run several copies of an application; give each its own row.

Both checks print `installed=<versions>` or `installed=none`, and anything that stops them from looking prints `verdict=unknown` with a reason. A check that could not look must never print `installed=none`.

## pip

Use the application's own interpreter, never the system `python3` unless the application runs on it:

```sh
p=/opt/langflow/.venv/bin/python; n=langflow; [ -x "$p" ] || { echo "verdict=unknown reason=no-interpreter"; exit 0; }; "$p" -c "import importlib.metadata as m, re, sys; c=lambda s: re.sub(r'[-_.]+', '-', s or '').lower(); n=c(sys.argv[1]); print('installed=' + next((d.version for d in m.distributions() if c(d.metadata['Name']) == n), 'none'))" "$n" 2>/dev/null || echo "verdict=unknown reason=check-failed"
```

`importlib.metadata` needs no `pip` in the environment, which many deployed virtualenvs leave out. Names compare after the normalization Python packaging uses, so `zope.interface` and `zope-interface` are the same package. An interpreter older than Python 3.8 lacks it and the check reports `check-failed`.

## npm

A vulnerable npm package is usually a transitive dependency, and an application can hold several copies at different versions. Read every copy, the top-level one included:

```sh
cd /srv/app 2>/dev/null && [ -d node_modules ] || { echo "verdict=unknown reason=no-node_modules"; exit 0; }; command -v node >/dev/null || { echo "verdict=unknown reason=no-node"; exit 0; }; f=$(find -L "$PWD/node_modules" -path '*/node_modules/axios/package.json' 2>/dev/null) || { echo "verdict=unknown reason=find-failed"; exit 0; }; [ -n "$f" ] || { echo "installed=none"; exit 0; }; v=$(node -p '[...new Set(process.argv.slice(1).map(f=>{const v=require(f).version;if(!v)throw 0;return v}))].join(" ")' $f 2>/dev/null) || { echo "verdict=unknown reason=unreadable-package-json"; exit 0; }; echo "installed=$v"
```

The row is `affected` if any copy is older than the fixed version. An application shipped as a bundle without `node_modules` hides its dependencies from this check, so it is `unknown`.
