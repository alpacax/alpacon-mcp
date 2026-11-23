# Exposure checks

The commands the `exposure-check` skill runs. Both are read-only and need no root; fill the values in their first lines and leave the rest unchanged.

## The check

`ports` lists the ports whose listeners count as findings, separated by spaces; with `ports=''` the listeners are shown and none is a finding. `endpoints` holds one `<method> <scheme> <port> <path>` line per endpoint; leave it empty to probe none.

```sh
export LC_ALL=C
ports='2375 2376 2377'
endpoints='GET http 2375 /version
GET https 2376 /version'
command -v ss >/dev/null 2>&1 || { echo "verdict=unknown reason=no-ss"; exit 0; }
sockets=$(ss -ltnp 2>/dev/null) || { echo "verdict=unknown reason=ss-failed"; exit 0; }
listeners=$(printf '%s\n' "$sockets" | awk '{a = $4; p = a; sub(/.*:/, "", p); if (p !~ /^[0-9]+$/) next
  sub(/:[0-9]+$/, "", a); gsub(/[][]/, "", a); z = ""; if (i = index(a, "%")) {z = substr(a, i + 1); a = substr(a, 1, i - 1)}
  s = (a ~ /^127\./ || a == "::1" || a ~ /^::ffff:127\./) ? "loopback" : (a == "0.0.0.0" || a == "::" || a == "*") ? "all" : "interface"
  t = s == "loopback" ? "-" : a == "*" ? "*" : a == "::" ? "[::1]" : s == "all" ? "127.0.0.1" : a ~ /:/ ? "[" a (z == "" ? "" : "%25" z) "]" : a
  n = ""; if (match($0, /users:\(\("[^"]*"/)) n = substr($0, RSTART + 9, RLENGTH - 10)
  print a, p, s, t, n}' | sort -u)
target() { printf '%s\n' "$listeners" | awk -v p="$1" 'function out(x) {if (!(x in seen)) {seen[x] = 1; k = 1; print x}}
  $2 == p {if ($3 == "loopback") l = 1; else if ($4 == "*") {out("127.0.0.1"); out("[::1]")} else out($4)}
  END {if (!k && l) print "loopback"}'; }
scope_of() { h=${1#tcp://}; case $h in (\[*) h=${h#?}; h=${h%%]*} ;; (*) h=${h%:*} ;; esac
  case $h in (127.*|::1|::ffff:127.*|localhost) echo loopback ;; (''|0.0.0.0|::|'*') echo all ;; (*) echo interface ;; esac; }
hidden() { d=$1; while [ "${d%/*}" != "$d" ]; do d=${d%/*}; [ ! -e "${d:-/}" ] || break; done; [ -d "${d:-/}" ] && [ ! -x "${d:-/}" ]; }
host_flags() { grep -oE '(^|[[:space:]])(-H(=|[[:space:]]*)|--host(=|[[:space:]]+))[^-[:space:];][^[:space:];]*' | sed -E 's/^[[:space:]]*(-H|--host)[=[:space:]]*//'; }
docker_hosts() {
  dj=/etc/docker/daemon.json
  if [ -r "$dj" ] && grep -q '\\u' "$dj"; then echo "daemon.json -"
  elif [ -r "$dj" ]; then tr -d '[:space:]' < "$dj" | sed 's#\\/#/#g' | grep -oE '"hosts":\[("[^"]*",?)*\]' | sed 's/^"hosts"://' | grep -oE '"[^"]*"' | tr -d '"' | sed 's/^/daemon.json /'
  elif [ -e "$dj" ] || hidden "$dj"; then echo "daemon.json -"; fi
  if command -v systemctl >/dev/null 2>&1; then
    if u=$(systemctl show -p ExecStart docker.service 2>/dev/null); then printf '%s\n' "$u" | host_flags | sed 's/^/unit /'; else echo "unit -"; fi
  fi
  if p=$(ps -eo args= 2>/dev/null); then printf '%s\n' "$p" | awk '$1 ~ /(^|\/)dockerd$/' | host_flags | sed 's/^/process /'; else echo "process -"; fi
}
report() {
  if [ "$(id -u)" = 0 ]; then echo processes=all; else echo processes=own-only; fi
  printf '%s\n' "$listeners" | awk -v w=" $ports " 'NF && $3 != "loopback" {print "listen addr=" $1 " port=" $2 " scope=" $3 " watched=" (index(w, " " $2 " ") ? "yes" : "no") " process=" $5}'
  hosts=$(docker_hosts)
  printf '%s\n' "$hosts" | while read -r src h; do
    case $h in ('-') echo "docker_host source=$src host=unreadable scope=unknown"; continue ;; (tcp://*) ;; (*://*|/*|'') continue ;; (*) h=tcp://$h ;; esac
    echo "docker_host source=$src host=$h scope=$(scope_of "$h")"
  done
  { for s in /run/docker.sock /var/run/docker.sock; do if [ -S "$s" ]; then echo "$s"; break; fi; done
    printf '%s\n' "$hosts" | sed -n 's#^[^ ]* unix://##p'; } | awk 'NF && !seen[$0]++' | while read -r s; do
    if [ -S "$s" ]; then stat -L -c "docker_sock path=$s mode=%a owner=%U group=%G" "$s" 2>/dev/null || echo "docker_sock path=$s mode=unknown"
    elif hidden "$s"; then echo "docker_sock path=$s mode=unknown"; fi
  done
  printf '%s\n' "$endpoints" | while read -r m sc port path; do
    [ -n "$path" ] || continue
    t=$(target "$port")
    case $t in
      ('') echo "endpoint method=$m port=$port path=$path url=- code=none result=not_listening"; continue ;;
      (loopback) echo "endpoint method=$m port=$port path=$path url=- code=none result=loopback_only"; continue ;;
    esac
    printf '%s\n' "$t" | while read -r a; do
      u="$sc://$a:$port$path"
      set -- -q --noproxy '*' -sk -o /dev/null -m 5 -w '%{http_code}'
      [ "$m" != WS ] || set -- "$@" -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=='
      if command -v curl >/dev/null 2>&1; then c=$(curl "$@" "$u"); else c=none; fi
      case $m$c in (GET2??|WS101) r=open ;; (*401|*403) r=auth_required ;; (*404) r=not_found ;; (*000) r=no_answer ;; (*) r=unclear ;; esac
      echo "endpoint method=$m port=$port path=$path url=$u code=$c result=$r"
    done
  done
}
out=$(report)
printf '%s\n' "$out"
printf '%s\n' "$out" | awk '
  function val(k,  i) { for (i = 2; i <= NF; i++) if (index($i, k "=") == 1) return substr($i, length(k) + 2); return "" }
  function add(v, x) { return index("," v ",", "," x ",") ? v : v (v == "" ? "" : ",") x }
  $1 == "listen" && val("watched") == "yes" { f = add(f, "port:" val("port") "@" val("addr")) }
  $1 == "docker_host" && val("scope") ~ /^(all|interface)$/ { f = add(f, "docker_host:" val("source")) }
  $1 == "docker_host" && val("scope") == "unknown" { u = add(u, "docker_host:" val("source")) }
  $1 == "docker_sock" && val("mode") ~ /^[0-7]*[2367]$/ { f = add(f, "docker_sock:world_writable") }
  $1 == "docker_sock" && val("mode") == "unknown" { u = add(u, "docker_sock:unreadable") }
  $1 == "endpoint" && val("result") == "open" { f = add(f, "endpoint:" val("port") val("path")) }
  $1 == "endpoint" && val("result") ~ /^(unclear|no_answer)$/ { u = add(u, "endpoint:" val("port") val("path")) }
  END { print "verdict=" (f != "" ? "exposed" : u != "" ? "unknown" : "not_exposed"); print "findings=" f; print "unknowns=" u }'
```

It prints these lines, or `verdict=unknown reason=<why>` alone when `ss` is missing or fails:

- `processes`: `all` as root, `own-only` otherwise. An ordinary account sees the process name only on its own sockets, so `process=` is empty on the others.
- `listen`: one line per TCP listener not bound to loopback (`127.0.0.0/8`, `::1`, `::ffff:127.*`). `scope=all` is a wildcard bind (`0.0.0.0`, `::`, `*`), `scope=interface` one address. `watched=yes` when its port is in `ports`, which makes it a finding.
- `docker_host`: a TCP host the Docker daemon is set to listen on, written with `tcp://` or, as dockerd also accepts, as a bare `host:port`, from `daemon.json`'s `hosts`, the `-H`/`--host` flags of `docker.service`'s effective `ExecStart` with its drop-ins applied (`unit`), or those of the running `dockerd` (`process`), which also catch hosts set in `/etc/default/docker`. A non-loopback host is a finding whether or not it is listening now, because the next daemon restart opens it. A source that could not be read is an unknown: an unreadable `daemon.json`, one behind a directory the account cannot search, which looks the same as no file at all, one holding `\u` escapes, which the check does not decode, a failing `systemctl` or a failing `ps`. A host without `systemctl` has no unit to read and is not an unknown for it.
- `docker_sock`: the mode, owner and group of the default Docker socket and of every `unix://` socket the daemon is configured with. A world-writable socket (`666`, `777`) is a finding: any local account can then drive the daemon, which is root on the host. A socket whose mode `stat` cannot read, or a configured one behind a directory the account cannot search, is `mode=unknown` and an unknown.
- `endpoint`: one line per address the endpoint's port listens on, each probed there: `127.0.0.1` for an IPv4 wildcard, `[::1]` for an IPv6 one, and both for a dual-stack socket that `ss` shows as `*`, so a dual-stack listener gets two requests, otherwise the bound interface address, with its zone for a link-local one. A port with no listener is `not_listening` and one bound only to loopback is `loopback_only`; neither gets a request. `result=open` (a 2xx to `GET`, `101` to a `WS` upgrade) is a finding; `auth_required` (401, 403) and `not_found` (404) are not; `no_answer` (nothing answered, a timeout or a failed TLS handshake included) and any other code, a redirect included, which is `unclear`, are unknowns.
- `verdict`: `exposed` when there is a finding, `unknown` when there is none but something is unknown, `not_exposed` otherwise; `findings` and `unknowns` name them, comma-separated.

`https` is probed without certificate verification, because the question is whether the service answers, not whether its certificate is valid. curl runs with `-q` and `--noproxy '*'`, so neither the account's `~/.curlrc` nor a proxy setting changes what is sent or who answers. A Docker daemon on 2376 that requires client certificates refuses the handshake, which reads as `no_answer`; the listener on 2376 is a finding on its own.

## Presets

| Preset | `ports` | `endpoints` | Default credential |
| --- | --- | --- | --- |
| Docker API | `2375 2376 2377` | `GET http 2375 /version`, `GET https 2376 /version` | None |
| MinIO | `9000 9001` | None | Console login, below |

The Docker daemon has no login: anyone who reaches 2375, or 2376 without client certificates, controls it. 2377 is the swarm management port, which `docker swarm init` binds to every interface unless `--listen-addr` names one. The `docker_host` and `docker_sock` lines are read on every run, preset or not.

A MinIO console started with `--console-address` on another port takes that port in `ports` and in the login check instead.

An endpoint of the person's own takes the same shape, such as `WS http 2718 /terminal/ws` for a marimo terminal.

## Default credential login

Run it only after the separate agreement in the skill's step 6. `port`, `scheme` and `path` name the login endpoint, `accepted` the status codes that mean the login worked, and `expect` a response header, lowercased, that only the expected service sends on success, so another service answering the same code is `unclear` instead of `accepted`; leave it empty only when the service sends no such header. The credential never goes in the command text: pass it in the `env` argument of `execute_command_multi_server`, as `EXPOSURE_BASIC` (`user:password` for HTTP basic auth) or `EXPOSURE_BODY` (a JSON body to `POST`). The values below are MinIO's console login, which answers `204` with a `token` session cookie to its factory default; its `env` is `{"EXPOSURE_BODY": "{\"accessKey\":\"minioadmin\",\"secretKey\":\"minioadmin\"}"}`.

```sh
export LC_ALL=C
port=9001
scheme=http
path=/api/v1/login
accepted='204'
expect='set-cookie: token='
command -v ss >/dev/null 2>&1 && command -v curl >/dev/null 2>&1 || { echo "login result=unknown reason=no-ss-or-curl"; exit 0; }
sockets=$(ss -ltn 2>/dev/null) || { echo "login port=$port result=unknown reason=ss-failed"; exit 0; }
t=$(printf '%s\n' "$sockets" | awk -v p="$port" 'function out(x) {if (!(x in seen)) {seen[x] = 1; k = 1; print x}}
  {a = $4; q = a; sub(/.*:/, "", q); if (q != p) next
  sub(/:[0-9]+$/, "", a); gsub(/[][]/, "", a); z = ""; if (i = index(a, "%")) {z = substr(a, i + 1); a = substr(a, 1, i - 1)}
  if (a ~ /^127\./ || a == "::1" || a ~ /^::ffff:127\./) {l = 1; next}
  if (a == "*") {out("127.0.0.1"); out("[::1]")} else out(a == "::" ? "[::1]" : a == "0.0.0.0" ? "127.0.0.1" : a ~ /:/ ? "[" a (z == "" ? "" : "%25" z) "]" : a)}
  END {if (!k && l) print "loopback"}')
case $t in ('') echo "login port=$port result=not_listening"; exit 0 ;; (loopback) echo "login port=$port result=loopback_only"; exit 0 ;; esac
set -- -q --noproxy '*' -sk -o /dev/null -D - -m 10 -w '\n%{http_code}'
[ -z "${EXPOSURE_BASIC-}" ] || set -- "$@" -u "$EXPOSURE_BASIC"
[ -z "${EXPOSURE_BODY-}" ] || set -- "$@" -H 'Content-Type: application/json' --data-binary "$EXPOSURE_BODY"
printf '%s\n' "$t" | while read -r a; do
  u="$scheme://$a:$port$path"
  out=$(curl "$@" "$u"); c=$(printf '%s\n' "$out" | tail -n 1)
  case " $accepted " in
    (*" $c "*) if [ -z "$expect" ] || printf '%s\n' "$out" | tr '[:upper:]' '[:lower:]' | grep -qF "$expect"; then r=accepted; else r=unclear; fi ;;
    (*) case $c in (401|403) r=rejected ;; (000) r=no_answer ;; (*) r=unclear ;; esac ;;
  esac
  echo "login url=$u code=$c result=$r"
done
```

It prints one `login` line per address the port listens on, chosen as for `endpoint`, so a console bound to two interfaces, or to both IP families, gets two attempts. `result=accepted` means the expected code came with the `expect` header: the default credential still works and the server is `exposed`; `rejected` is not a finding; `no_answer`, `unclear` (any other code) and `unknown` (`ss` or `curl` missing, or `ss` failed) are unknowns. A port with no listener, or one bound only to loopback, gets no login attempt.
