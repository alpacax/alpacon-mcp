# pip and npm packages

A language package lives in an application's environment, not on the system, so the person has to say which application and where it lives. If they do not know, list process names with `ps -eo pid,user,comm`, then read only `/proc/<pid>/exe` and `/proc/<pid>/cwd` for a confirmed numeric PID. Do not read `args`, `cmdline`, or `environ`: they can contain credentials. These paths may identify only the base interpreter or working directory, not a virtualenv; ask for the application environment when they are insufficient or inaccessible. A server can run several copies of an application; give each its own row.

Both checks compare on the host and print the verdict with `installed=`. The fixed versions go in `x` as `<line>=<fixed>` pairs, one per release line the advisory fixes (`0.28=0.28.1 1.7=1.7.4`); an install takes the first pair whose line its version starts with. An empty line (`=1.3.0`) matches every version: use it, last, when the advisory says every release below the fix is affected. An install on no listed line is `unknown`, even if it is newer than every fix: the advisory says nothing about that line. A version that is not plain dot-separated numbers (a pre-release `1.3.0rc1`, a local `+cu121`) is `unknown`: the check orders only what it can order with certainty. Anything that stops a check from looking prints `verdict=unknown` with a reason; a check that could not look never prints `installed=none`.

## pip

Use the application's own interpreter, never the system `python3` unless the application runs on it:

```sh
p=/opt/langflow/.venv/bin/python; n=langflow; x='1.3=1.3.0'; [ -x "$p" ] || { echo "verdict=unknown reason=no-interpreter"; exit 0; }; "$p" -c "import importlib.metadata as m, re, sys; a=sys.argv; c=lambda s: re.sub(r'[-_.]+', '-', s or '').lower(); k=lambda s: [int(i) for i in s.split('.')] if re.fullmatch(r'[0-9]+(\.[0-9]+)*', s) else None; lt=lambda x, y: x + [0]*(len(y)-len(x)) < y + [0]*(len(x)-len(y)); fx=[(k(l) if l else [], k(f), f) for l, f in (e.split('=', 1) for e in a[2].split())]; assert fx and all(l is not None and F for l, F, f in fx); v=next((d.version for d in m.distributions() if c(d.metadata['Name']) == c(a[1])), None); K=k(v) if v else None; L=[(F, f) for l, F, f in fx if K and K[:len(l)] == l]; print('verdict=not_affected installed=none' if v is None else f'verdict=unknown installed={v} reason=unorderable-version' if K is None else (f'verdict=affected installed={v} fixed={L[0][1]}' if lt(K, L[0][0]) else f'verdict=not_affected installed={v} fixed={L[0][1]}') if L else f'verdict=unknown installed={v} reason=line-not-in-advisory')" "$n" "$x" 2>/dev/null || echo "verdict=unknown reason=check-failed"
```

`importlib.metadata` needs no `pip` in the environment, which many deployed virtualenvs leave out. Names compare after the normalization Python packaging uses, so `zope.interface` and `zope-interface` are the same package. An interpreter older than Python 3.8 lacks it, and a malformed `x` fails the `assert`; both report `check-failed`.

## npm

A vulnerable npm package is usually a transitive dependency, and an application can hold several copies at different versions. Read every copy, the top-level one included; the row takes the worst copy's verdict, `affected` over `unknown` over `not_affected`:

```sh
x='0.28=0.28.1 1.7=1.7.4'; cd /srv/app 2>/dev/null && [ -d node_modules ] || { echo "verdict=unknown reason=no-node_modules"; exit 0; }; command -v node >/dev/null || { echo "verdict=unknown reason=no-node"; exit 0; }; f=$(find -L "$PWD/node_modules" -path '*/node_modules/axios/package.json' 2>/dev/null) || { echo "verdict=unknown reason=find-failed"; exit 0; }; [ -n "$f" ] || { echo "verdict=not_affected installed=none"; exit 0; }; node -e 'const [x, ...fs] = process.argv.slice(1); const k = s => /^[0-9]+(\.[0-9]+)*$/.test(s) ? s.split(".").map(Number) : null; const lt = (a, b) => { for (let i = 0; i < Math.max(a.length, b.length); i++) { const d = (a[i] || 0) - (b[i] || 0); if (d) return d < 0; } return false; }; const fx = x.split(" ").map(e => e.split("=").map((s, i) => i || s ? k(s) : [])); if (fx.some(([l, F]) => !l || !F)) throw 0; const vs = [...new Set(fs.map(f => { const v = require(f).version; if (!v) throw 0; return v; }))]; const one = v => { const K = k(v); if (!K) return "unknown"; const L = fx.find(([l]) => l.every((n, i) => K[i] === n)); if (L) return lt(K, L[1]) ? "affected" : "not_affected"; return "unknown"; }; const r = vs.map(one); console.log("verdict=" + (r.includes("affected") ? "affected" : r.includes("unknown") ? "unknown" : "not_affected") + " installed=" + vs.join(","));' "$x" $f 2>/dev/null || echo "verdict=unknown reason=check-failed"
```

A `package.json` without a version, or a malformed `x`, reports `check-failed`. An application shipped as a bundle without `node_modules` hides its dependencies from this check, so it is `unknown`.
