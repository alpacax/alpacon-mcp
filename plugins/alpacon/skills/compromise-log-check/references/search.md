# Log search

The script the `compromise-log-check` skill runs with `execute_file`, as an ordinary account. It only reads, though `execute_file` writes the script itself to the server first; fill the values in its first lines and leave the rest unchanged.

- `logs`: one absolute log path per line. Each is searched with its rotated copies (`<path>.*` and `<path>-*`), gzip, xz, bzip2 and zstd included. A rotation that names files another way (`access-20260803.log`) needs each file listed.
- `patterns`: one extended regular expression per line, numbered from 1, tried only inside the part of a line that `control` matches.
- `control`: an expression that matches the request part of every ordinary line in this log format, from where it starts through its status. The value below also matches a malformed or empty request, so a line it misses is in another format. It shows that the search can read the format, not that a pattern is right, and keeps a request written into a user agent or referer from counting. Start it at something a client cannot write, as the `"` of the nginx and Apache formats, which both escape in client text.
- `skip`: an expression for the lines in this log that are known not to be requests, such as an error record, tried only on a line `control` misses; empty when there are none. A line it matches is left out of `lines` and not searched, so start it at text a client cannot write, as the start of the line, and never let it match a request in any format. Every other line that `control` misses makes its file `partial`.
- `also`: fixed strings, one per line, that a line must all hold up to the end of its request part; one that starts with `^` must be at the start of the line, as `^10.0.0.1 ` (with its last space) for an address that comes first, so neither `110.0.0.1` nor a user name counts. Elsewhere in the line, write the address with a space on both sides. When the log serves more than one application, such as an ingress or a proxy with several virtual hosts, every run on it, the first included, holds one line with this application's host or upstream, the lines below added beside it. Only a whole field at the start of the line that the server writes from its own configuration can be used, such as Apache's `%v` or nginx's `$server_name`, never the client's `Host` (`%V`, `%{Host}i`, `$host`), which a scanner sets to anything. Write it with `^` and its last space, as `^metabase.example.com:443 ` for Apache's `vhost_combined` format. All `also` lines must hold, so when the application is written with more than one value, such as two ports or two server names, each value gets its own run; the address that follows it goes in the same line, as `^metabase.example.com:443 203.0.113.9 `. Anywhere else the text can sit inside a longer name or in a field the client writes, such as the user name. When the format starts no line with that field, leave the line out: the search can still show that no line matches, but any match it finds cannot be tied to this application. One `also` value applies to every path in `logs`, so a shared log and a log that serves only this application are searched in separate runs. Otherwise empty on the first run; the pairing run fills it.

In `patterns`, `control` and `skip`, use no `'`, no `\` before a letter or digit, no `(?`, no `[:class:]` and no `{n}`: some `awk` builds read them as something else and find nothing. The search refuses all but `'`, which ends the quoted value, so check for that before filling it.

## The search

```sh
export LC_ALL=C
logs='/var/log/nginx/access.log'
patterns='^"POST [^"?]*/api/session/reset_password(\?([^"\\]|\\.)*)? +HTTP/[0-9.]+" 400( |$)'
control='"([^"\\]|\\.)*" [0-9][0-9][0-9]( |$)'
skip=''
also=''
show=10
export patterns control skip also show
[ -n "$logs" ] && [ -n "$patterns" ] && [ -n "$control" ] || { echo "search=incomplete reason=empty-input"; exit 0; }
case $patterns$control$skip in (*\\[A-Za-z0-9]*|*'(?'*|*'[:'*|*{[0-9]*) echo "search=incomplete reason=unsupported-expression"; exit 0 ;; esac
searched() {
  { case $1 in (*.gz) gzip -dc < "$1" ;; (*.xz) xz -dc < "$1" ;; (*.bz2) bzip2 -dc < "$1" ;; (*.zst) zstd -dc < "$1" ;; (*) cat < "$1" ;; esac 2>/dev/null
    printf '\nEND-OF-LOG %s\n' "$?"; } | tr '\000' '\001' | f=$1 awk '
    function clean(s) { gsub(s ~ /^"/ ? "[?]([^\"\\\\]|\\\\.)*" : "[?][^ ]*", "?...", s); gsub(/[^ -~]/, ".", s); return s }
    function cut(s, n) { return length(s) > n ? substr(s, 1, n - 43) "..." substr(s, length(s) - 39) : s }
    BEGIN { f = ENVIRON["f"]; c = ENVIRON["control"]; sk = ENVIRON["skip"]; show = ENVIRON["show"] + 0; n = split(ENVIRON["patterns"], p, "\n"); a = split(ENVIRON["also"], w, "\n") }
    /^END-OF-LOG [0-9]+$/ { rc = $2; next }
    { if (/^\001/) sub(/^\001+/, "") }
    /^$/ { next }
    sk != "" && !match($0, c) && $0 ~ sk { next }
    { lines++
      if (!match($0, c)) next
      pre = substr($0, 1, RSTART - 1); req = substr($0, RSTART, RLENGTH); if (!k++) first = pre; last = pre
      for (i = 1; i <= n; i++) if (p[i] != "" && req ~ p[i]) {
        hit = 1
        for (j = 1; j <= a; j++) if (w[j] != "" && !(w[j] ~ /^\^/ ? index(pre req, substr(w[j], 2)) == 1 : index(" " pre req, w[j]))) hit = 0
        if (hit && ++m[i] <= show) print "match pattern=" i " file=" f " line=" lines " text=" cut(clean(pre), 200) cut(clean(req), 300)
      } }
    END { for (i = 1; i <= n; i++) if (p[i] != "") print "count pattern=" i " n=" m[i] + 0
      print "file path=" f " status=" (rc != "0" ? "read_failed" : !lines ? "empty" : k == lines ? "ok" : k ? "partial" : "no_control") " lines=" lines + 0 " control=" k + 0 " first=[" cut(clean(first), 200) "] last=[" cut(clean(last), 200) "]" }' \
    || echo "file path=$1 status=search_failed"
}
copies() {
  l=$1; o=$2; set --
  for g in "$l" "$l".* "$l"-*; do
    if [ -e "$g" ] || [ -L "$g" ]; then case $g in (*[!0-9A-Za-z._/:+@~,-]*) [ "$o" = -1dtr ] || echo unsafe-name ;; (*) set -- "$@" "$g" ;; esac; fi
  done
  [ "$#" = 0 ] || ls "$o" -- "$@" 2>/dev/null || echo "$l list-failed"
  [ "$o" = -1dtr ] || for g; do if [ "$g" != "$l" ] && [ -f "$g" ] && [ -r "$g" ]; then echo "$g $(stat -c '%y %z' -- "$g" 2>/dev/null || stat -f '%Fm %Fc' -- "$g" 2>/dev/null || date -u -r "$g" +%s) $(wc -c < "$g")"; fi; done
}
report() {
  printf '%s\n' "$logs" | while read -r l; do
    [ -n "$l" ] || continue
    d=${l%/*}; [ -r "${d:-/}" ] && [ -x "${d:-/}" ] || echo "file path=$l status=dir_unreadable"
    before=$(copies "$l" -1di); [ -n "$before" ] || { echo "file path=$l status=missing"; continue; }
    copies "$l" -1dtr | while read -r g; do
      echo "mtime path=$g utc=$(date -u -r "$g" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
      if [ ! -f "$g" ]; then echo "file path=$g status=not_regular"
      elif [ ! -r "$g" ]; then echo "file path=$g status=unreadable"
      else searched "$g"; fi
    done
    case $before in (*unsafe-name*) echo "file path=$l status=unsafe_name" ;; esac
    case $before in (*list-failed*) echo "file path=$l status=list_failed" ;; ("$(copies "$l" -1di)") ;; (*) echo "file path=$l status=changed" ;; esac
  done
}
echo "now=$(date +%Y-%m-%dT%H:%M:%S%z)"
report | awk -v show="$show" '
  $1 == "match" { if (++s[$2] <= show) print; next }
  $1 == "count" { t[$2] += substr($3, 3); if (!($2 in o)) { o[$2] = 1; q[++n] = $2 } next }
  { print }
  $1 == "file" { files++; if ($3 !~ /^status=(ok|empty)$/) bad++; if ($3 == "status=ok") ok++ }
  END { for (i = 1; i <= n; i++) print "total " q[i] " count=" t[q[i]] + 0 " shown=" (s[q[i]] + 0 < show ? s[q[i]] + 0 : show)
    print "search=" (ok && !bad ? "complete" : "incomplete") " files=" files + 0 " problems=" bad + 0 }'
```

It prints these lines, or `search=incomplete reason=<why>` alone when a value is empty or an expression is refused:

- `now`: the server's clock and UTC offset. A log's own offset wins when it prints one.
- `mtime`: when each file last changed, in UTC, oldest first within each path in `logs`.
- `match`: the line's place among its file's non-empty lines that `skip` left in (`line`), then what precedes the request and the request part of a matching line, so referer, user agent and anything else after the status stay on the host. Any query string, with what follows it up to the closing quote (the next space in an unquoted format, whatever it holds), is `?...`, any byte outside printable ASCII is `.`, and a part over 200 (before the request) or 300 characters loses its middle. At most `show` per pattern, over all files.
- `file`: one per file. `first` and `last` hold what precedes the request on the first and last control line, cleaned the same way, which is where the time usually is. `lines` leaves out empty lines and those `skip` matched; `control` is how many of them `control` matched. `status` is `ok` (every line matched `control`); `empty` (no line left); `partial` (some lines matched neither `control` nor `skip`, so a request in another format may not have been searched); `no_control` (lines, none in the format `control` describes); `read_failed` (a corrupt or truncated archive, or no decompressor); `unreadable` (no permission); `dir_unreadable` (one more line for that path: rotated copies may exist that the search cannot list); `missing`; `list_failed` (`ls` could not list every copy); `changed` (one more line for that path: its files rotated during the search, so one may have been skipped; search again only if the person agrees); `not_regular` (a directory, pipe, device or broken link, such as a container log linked to stdout); `unsafe_name` (a rotated copy whose name holds a space or another unexpected character, reported under its path in `logs`); or `search_failed` (a bad expression).
- `total`: the count for each pattern, including what could be read of a `read_failed` file, and how many `match` lines were shown.
- `search`: `complete` when at least one file was `ok` and every other was `ok` or `empty`; `incomplete` otherwise. It says nothing about dates, which the skill judges.

## The pairing run

For a pattern of two requests, the first run searches only the rarer one, the anchor. The second run takes the other request as `patterns` and one client address, copied from the anchor's `match` line, as `also`, with `^` and a last space when the line starts with it; run it once per address. A value holding a `'` is not used. The address ties the two requests to one client, not to one application, so in a shared log both runs keep the application's line.

When `count` is above `shown`, the later requests were not seen: add an `also` line with the log's own time text for the anchor's hour (`[04/Aug/2026:10:`), then for each following hour, worked out from the anchor, for the first 24 hours, then each following day, until a pair is found or the end date is reached. If one hour still exceeds `show`, narrow it to ten minutes.

The anchor run has the same limit: when its `count` is above `shown`, anchors inside the dates may not have been seen, whatever the dates of the shown ones. Run it again with the log's own time text added to `also` for each day from the start date to the end date (`[04/Aug/2026:`), and for each hour of a day that still exceeds `show`. An hour that exceeds it is narrowed to ten minutes.

Two runs cannot be compared by file or `line`, because the logs may rotate between them. When an anchor and a second request carry the same time, run the search once more with both expressions in `patterns`, one per line, and the address and that time text added to `also`. In that one run, the match with the larger `line` in the same file came later. When the two are in different files, the order is unknown: the files are listed by when they last changed, which recompressing or restoring an archive also changes. It is unknown too when the run is `changed` or not every match was shown.

## Metabase (CVE-2026-72898, GHSA-vwf4-m7j8-wcjf)

[Metabase's security update](https://www.metabase.com/blog/security-update) names a `POST /api/session/reset_password` answered 400, followed by a `GET /api/user/current` answered 200. Re-read it before searching. It says to look in the application log or the ingress log, so when a proxy on another server fronts Metabase, search that server too. It gives no time window and does not say the two come from one address.

The anchor is the `patterns` value above, for the nginx and Apache common and combined formats. The second request, for the pairing run:

```text
^"GET [^"?]*/api/user/current(\?([^"\\]|\\.)*)? +HTTP/[0-9.]+" 200( |$)
```

Another format, plain or JSON, needs its own `patterns` and `control`, with `control` starting at text a client cannot write. Everything before the request part comes back, so a format that writes a credential, cookie or token there cannot be searched with this script. Where the format has no such text, report `unknown`.
