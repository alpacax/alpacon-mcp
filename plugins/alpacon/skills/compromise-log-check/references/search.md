# Log search

## Search inputs

Fill only the assignments at the top of [the search](#the-search).

- `logs`: One absolute path per line. The search discovers sibling copies with a numeric suffix (such as `.2`) or a dated suffix (a hyphen followed by 8–10 digits or `YYYY-MM-DD`, starting with 1 or 2), with optional `.gz`, `.xz`, `.bz2` or `.zst`. List copies in an `olddir` or with other naming conventions explicitly, after the log they belong to. Do not list a path twice or list copies already discovered. An `odd_copy` keeps the search incomplete: when the rotation configuration shows it is a copy of this log, list it in `logs` after its log and search again.
- `active`: Only the paths in `logs` that the web server writes now, one per line, read from its configuration (nginx's `access_log`, Apache's `CustomLog`) or named by the person when the configuration does not settle it. Leave empty if none are active. Never a rotated copy or a file listed for one: the script refuses only `<path>.` and a digit, and only when `<path>` is itself listed, and a copy put here could change unnoticed.
- `patterns`: One POSIX extended regular expression per line, applied only to the part matched by `control`. Write each method letter in both cases. For nginx include 499 alongside the advisory status. Use the logged path and escaping. For nginx's default and Apache's escapes, write non-ASCII UTF-8 bytes as literal `\xHH` with both cases for each hex digit that is a letter, such as `[\\]x[Cc]3[\\]x[Aa]9` for the bytes C3 A9. Account for nginx's `\x22` and `\x5C` and Apache's `\"` and `\\`. Where a path expression can span escaped text, read an escaped pair as one character, as in `([^"?\\]|\\.)*` or `([^"?/\\]|\\.)*` for one segment. Allow embedded spaces and escaped controls where the log and server version permit them.
- `control`: Match each request through the status, including empty or malformed requests. Start at a delimiter that the client cannot emit unescaped in another field. The default starts at the request's opening quote. If the format has no trustworthy delimiter, it cannot settle a verdict.
- `line`: Match the entire record, including fields after the status. The default covers nginx and Apache common and combined logs. Adapt it to each other layout, such as by adding one leading `[^ "[]+ ` field for Apache's `vhost_combined`. Leave it empty only if no expression describes the layout. The script still checks for structural anomalies such as a quote or multiple timestamps before the request, a nonprintable byte in it, or a second request-like field. Formats incompatible with those checks cannot support a negative verdict.
- `skip`: Match only confirmed non-request records, at an unspoofable position or marker. A request in another format must never match `skip`. Leave empty if none are known.
- `also`: Fixed strings, one per line, all required. A leading `^` matches a literal line prefix. A leading `[` matches the beginning of the last bracketed time before the request. Otherwise the string is found anywhere through the request and status, with an implicit space at the start of the record. Leave empty on the initial search of a dedicated log. Keep each group of paths in a separate search if their formats or filters differ.
- `show`: A positive integer without leading zeroes. Agree on the cap before running. It limits the excerpts per pattern across all paths.

For a shared log, run the initial search without an application filter and separately once per confirmed application value with the filter. Only use a server-controlled whole field at the start, such as Apache's `%v` or nginx's `$server_name`, with `^` and the trailing space. Confirm what that field meant throughout the dates. A client-set host such as `%V`, `%{Host}i`, or `$host`, or a substring elsewhere in the line, cannot identify the application. When no trustworthy field is present, use the unfiltered run and leave attribution unresolved.

In `patterns`, `control`, `line` and `skip`, avoid single quotes, backslashes before letters, digits, `<`, `>`, a backtick or `]`, `(?`, named bracket classes and brace repetitions. Inside a bracket expression, put a literal `]` first and write a literal backslash as `\\`. Never insert a single quote into any assignment.

## The search

```sh
export LC_ALL=C
logs='/var/log/nginx/access.log'
active='/var/log/nginx/access.log'
patterns='^"[Pp][Oo][Ss][Tt] +(([^"?\\]|\\.)*/api/(/|[.]/|([^"?/\\]|\\.)*/[.][.]/)*session/(/|[.]/|([^"?/\\]|\\.)*/[.][.]/)*|([^"?\\]|\\.)*/[.][.]/([^"?\\]|\\.)*/)reset_password([?#;]([^"\\]|\\.)*)?( +[Hh][Tt][Tt][Pp]/[0-9.]+)? *" (400|499)( |$)'
control='"([^"\\]|\\.)*" [0-9][0-9][0-9]( |$)'
line='^[^ "[]+ [^ "[]+ [^ "[]+ [[][^][]*[]] "([^"\\]|\\.)*" [0-9][0-9][0-9] [0-9-]+( "([^"\\]|\\.)*" "([^"\\]|\\.)*")?$'
skip=''
also=''
show='10'
export patterns control line skip also show
[ -n "$logs" ] && [ -n "$(printf '%s' "$patterns" | tr -d '\n')" ] && [ -n "$control" ] || { echo "search=incomplete reason=empty-input"; exit 0; }
case $show in (''|*[!0-9]*|0*) echo "search=incomplete reason=bad-show"; exit 0 ;; esac
copy='^([.][0-9]+|-[0-9]{8,10}|-[0-9]{4}-[0-9]{2}-[0-9]{2})([.](gz|xz|bz2|zst))?$'
printf '%s\n' "$active" | while IFS= read -r a; do [ -z "$a" ] || printf '%s\n' "$logs" | grep -Fxq -- "$a" || echo x; done | grep -q x && { echo "search=incomplete reason=active-not-in-logs"; exit 0; }
r=$(printf '%s\n' "$logs" | sed '/^$/d' | sort | uniq -d | sed 's/.*/twice/'; printf '%s\n' "$logs" | while IFS= read -r a; do printf '%s\n' "$logs" | while IFS= read -r p; do [ -z "$a" ] || [ -z "$p" ] || [ "$p" = "$a" ] || case $a in ("$p"?*) x=${a#"$p"}
  if printf '%s\n' "$x" | grep -Eq "$copy"; then echo twice; else case $x in (.[0-9]*) printf '%s\n' "$active" | grep -Fxq -- "$a" && echo copy ;; esac; fi ;; esac; done; done)
case $r in (*twice*) echo "search=incomplete reason=listed-twice"; exit 0 ;; (*copy*) echo "search=incomplete reason=active-is-a-copy"; exit 0 ;; esac
case $patterns$control$line$skip in (*\\[A-Za-z0-9]*|*'(?'*|*'[:'*|*{[0-9,]*) echo "search=incomplete reason=unsupported-expression"; exit 0 ;; esac
r=$(printf '%s\n' "$patterns" "$control" "$line" "$skip" | while IFS= read -r x; do [ -n "$x" ] || continue
  printf '%s\n' "$x" | grep -Eq '(^|[^\\])(\\\\)*\\[]<>`]' && echo unsupported
  printf '\n' | grep -E -e "$x" >/dev/null 2>&1; [ "$?" -le 1 ] || echo bad; done)
case $r in (*unsupported*) echo "search=incomplete reason=unsupported-expression"; exit 0 ;; (*bad*) echo "search=incomplete reason=bad-expression"; exit 0 ;; esac
junk() { { printf x | "$1" -c 2>/dev/null; printf JUNKJUNK; } | "$1" -dc; }
strict() { case $(junk "$1" 2>/dev/null; echo ":$?") in (x:0) [ -n "$(junk "$1" 2>&1 >/dev/null)" ] ;; (x:*) : ;; (*) false ;; esac; }
searched() {
  { e=$( { case $1 in (*.gz) strict gzip && gzip -dc < "$1" ;; (*.xz) strict xz && xz -dc < "$1" ;; (*.bz2) strict bzip2 && bzip2 -dc < "$1" ;; (*.zst) strict zstd && zstd -dc < "$1" ;; (*) cat < "$1" ;; esac; } 2>&1 1>&3 ); r=$?; [ -z "$e" ] || r=1
    printf '\nEND-OF-LOG %s\n' "$r"; } 3>&1 | tr '\000' '\001' | f=$1 sz=$sz awk '
    function clean(s) { gsub(/\/\/[^\/" ?#]*@/, "//...@", s); gsub(s ~ /^"/ ? "[?#;]([^\"\\\\]|\\\\.)*" : "[?#;][^ ]*", "?...", s); gsub(/:\/\/[^\/" ?]*[?][.][.][.]/, "://...?...", s); gsub(/[^ -~]/, ".", s); return s }
    function stamp(s,  i, t) { i = 0; while (match(substr(s, i + 1), /\[/)) i += RSTART; if (!i) return s; t = substr(s, i); return index(t, "]") ? substr(t, 1, index(t, "]")) : t }
    function cut(s, n) { return length(s) > n ? substr(s, 1, n - 43) "..." substr(s, length(s) - 39) : s }
    function emit(i, pre, req, whole) {
      pre = whole ? clean(pre) : ""; req = clean(req)
      print "match pattern=" i " file=" f " line=" lines (whole ? "" : " broken") (length(pre) > 200 || length(req) > 300 ? " clipped" : "") " text=" cut(pre, 200) cut(req, 300)
    }
    BEGIN { f = ENVIRON["f"]; c = ENVIRON["control"]; ln = ENVIRON["line"]; sk = ENVIRON["skip"]; show = ENVIRON["show"] + 0; n = split(ENVIRON["patterns"], p, "\n"); a = split(ENVIRON["also"], w, "\n") }
    { rd += length($0) + 1 }
    /^END-OF-LOG [0-9]+$/ { if (pend) lines++; pend = 1; rc = $2; mk = length($0) + 1; next }
    { if (index($0, "\001")) nul = 1; if (/^\001/) sub(/^\001+/, "") }
    /^$/ { next }
    pend { lines++; pend = 0; rc = "" }
    sk != "" && !match($0, c) && $0 ~ sk { next }
    { lines++
      if (!match($0, c)) next; cm++
      pre = substr($0, 1, RSTART - 1); req = substr($0, RSTART, RLENGTH); odd = index(pre req, "\001") || index(pre, "\"") || req ~ /[^ -~]/ || pre ~ /\[[0-3][0-9]\/[A-Z][a-z][a-z]\/[12][0-9][0-9][0-9]:.*\[[0-3][0-9]\/[A-Z][a-z][a-z]\/[12][0-9][0-9][0-9]:/ || match(substr($0, length(pre) + length(req) + 1), c)
      whole = !odd && (ln == "" || $0 ~ ln); if (whole) k++; held = 1
      for (j = 1; j <= a; j++) if (w[j] != "" && !(w[j] ~ /^\^/ ? index(pre req, substr(w[j], 2)) == 1 : w[j] ~ /^\[/ ? index(stamp(pre), w[j]) == 1 : index(" " pre req, w[j]))) held = 0
      if (!held) next
      if (whole) { if (!h++) first = pre; last = pre
        r = pre; while ((x = index(r, "[")) > 0) r = substr(r, x + 1)
        d = r ~ /^[0-3][0-9]\/[A-Z][a-z][a-z]\/[12][0-9][0-9][0-9]:/ ? substr(r, 1, 11) : ""
        if (d != "" && !(d in dy)) { dy[d] = 1; days = days (days == "" ? "" : ",") d } }
      for (i = 1; i <= n; i++) if (p[i] != "" && req ~ p[i] && ++m[i] <= show) emit(i, pre, req, whole)
      if (!whole) { t = substr($0, length(pre) + length(req) + 1); while (match(t, c) && RLENGTH > 0) { q = substr(t, RSTART, RLENGTH); t = substr(t, RSTART + RLENGTH)
        for (i = 1; i <= n; i++) if (p[i] != "" && q ~ p[i] && ++m[i] <= show) emit(i, "", q, 0) } } }
    END { for (i = 1; i <= n; i++) if (p[i] != "") print "count pattern=" i " n=" m[i] + 0
      print "file path=" f " status=" (rc != "0" ? "read_failed" : nul && !lines ? "partial" : !lines ? "empty" : k == lines && !nul ? "ok" : cm ? "partial" : "no_control") " lines=" lines + 0 " control=" cm + 0 " first=[" cut(clean(stamp(first)), 200) "] last=[" cut(clean(stamp(last)), 200) "] days=[" days "]"
      if (ENVIRON["sz"] != "" && rd - mk - 1 < ENVIRON["sz"] + 0) print "file path=" f " status=changed" }' \
    || echo "file path=$1 status=search_failed"
}
written() { case $1 in (*.gz|*.xz|*.bz2|*.zst) return 1 ;; esac; printf '%s\n' "$active" | grep -Fxq -- "$1"; }
copies() {
  l=$1; o=$2; set --
  for g in "$l" "$l".[0-9]* "$l"-[12]*; do
    if [ -e "$g" ] || [ -L "$g" ]; then case $g in (*[!0-9A-Za-z._/:+@~,-]*) [ "$o" = -1dtr ] || echo '!unsafe-name' ;; (*) if [ "$g" = "$l" ] || printf '%s\n' "${g#"$l"}" | grep -Eq "$copy"; then set -- "$@" "$g"; else [ "$o" = -1dtr ] || printf '%s\n' "$logs" | grep -Fxq -- "$g" || echo '!odd-copy'; fi ;; esac; fi
  done
  [ "$#" = 0 ] || ls "$o" -- "$@" 2>/dev/null || echo '!list-failed'
  [ "$o" = -1dtr ] || for g; do if { [ "$g" != "$l" ] || ! written "$g"; } && [ -f "$g" ] && [ -r "$g" ]; then echo "$g $(stat -L -c '%y %z' -- "$g" 2>/dev/null || stat -L -f '%Fm %Fc' -- "$g" 2>/dev/null || date -u -r "$g" +%s) $(wc -c < "$g")"; fi; done
  [ "$o" = -1dtr ] || for g; do if [ -L "$g" ] && [ -e "$g" ]; then echo "$g -> $(ls -1diL -- "$g" 2>/dev/null)"; fi; done
}
snap() { printf '%s\n' "$logs" | while IFS= read -r l; do [ -z "$l" ] || copies "$l" -1di; done; }
report() {
  s0=$(snap)
  printf '%s\n' "$logs" | while IFS= read -r l; do
    [ -n "$l" ] || continue
    d=${l%/*}; [ -r "${d:-/}" ] && [ -x "${d:-/}" ] || echo "file path=$l status=dir_unreadable"
    size=$([ -f "$l" ] && wc -c 2>/dev/null < "$l"); n=${size:-0}; [ "$n" -le 512 ] 2>/dev/null || n=512
    top=$([ -f "$l" ] && head -c "$n" "$l" 2>/dev/null | cksum)
    before=$(copies "$l" -1di); [ -n "$before" ] || { echo "file path=$l status=missing"; echo ran; echo ran; continue; }
    [ -e "$l" ] || ! printf '%s\n' "$active" | grep -Fxq -- "$l" || echo "file path=$l status=missing"
    copies "$l" -1dtr | { while read -r g; do
      case $g in ('!'*) echo "file path=$l status=list_failed"; continue ;; esac
      echo "mtime path=$g utc=$(date -u -r "$g" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
      if [ ! -f "$g" ]; then echo "file path=$g status=not_regular"
      elif [ ! -r "$g" ]; then echo "file path=$g status=unreadable"
      else sz=; [ "$g" != "$l" ] || case $g in (*.gz|*.xz|*.bz2|*.zst) ;; (*) sz=$size ;; esac; searched "$g"; fi
    done; echo ran; }
    [ -z "$size" ] || { [ "$([ -f "$l" ] && wc -c 2>/dev/null < "$l")" -ge "$size" ] 2>/dev/null && [ "$(head -c "$n" "$l" 2>/dev/null | cksum)" = "$top" ]; } || echo "file path=$l status=changed"
    case $before in (*'!unsafe-name'*) echo "file path=$l status=unsafe_name" ;; esac
    case $before in (*'!odd-copy'*) echo "file path=$l status=odd_copy" ;; esac
    case $before in (*'!list-failed'*) echo "file path=$l status=list_failed" ;; ("$(copies "$l" -1di)") ;; (*) echo "file path=$l status=changed" ;; esac
    echo ran
  done
  [ "$s0" = "$(snap)" ] || printf '%s\n' "$logs" | sed '/^$/d; s/.*/file path=& status=changed/'
  echo ran
}
echo "now=$(date +%Y-%m-%dT%H:%M:%S%z)"
report | awk -v show="$show" -v want="$((2 * $(printf '%s\n' "$logs" | grep -c .) + 1))" '
  $1 == "ran" { ran++; next }
  $1 == "match" { if (++s[$2] <= show) print; next }
  $1 == "count" { t[$2] += substr($3, 3); if (!($2 in o)) { o[$2] = 1; q[++n] = $2 } next }
  { print }
  $1 == "file" { files++; if ($3 !~ /^status=(ok|empty)$/) bad++; if ($3 == "status=ok") ok++ }
  END { for (i = 1; i <= n; i++) print "total " q[i] " count=" t[q[i]] + 0 " shown=" (s[q[i]] + 0 < show ? s[q[i]] + 0 : show)
    if (ran != want) bad++
    print "search=" (ok && !bad ? "complete" : "incomplete") " files=" files + 0 " problems=" bad + 0 }'
```

## Output

- `now`: The server's clock and UTC offset at script start.
- `mtime`: Each listed file's UTC modification time. The run visits paths in `logs` order, files by modification time oldest first within each path, and matches in record order within each file.
- `match`: Pattern number, file, `line` (record position after excluding blank and skipped lines), optional `broken` or `clipped` flags, and `text`. A whole record returns its prefix and its request through the status. A broken record returns only its request through the status, possibly from a later request-like part of the same physical line. It has no usable time or address. Fields after the matched status stay on the host unless they themselves contain a request-like part shown as `broken`.
- `file`: Path and status. The read result also reports `lines`, `control`, `first`, `last` and `days`. `first` and `last` come from the first and last whole records that passed `also`, in file order: the text before the request from its last `[` through the `]` that closes it, or the whole of that text when it has no `[`. `days` lists the `dd/Mon/yyyy` days recognized in those records' time fields. Empty time fields or missing days supply no coverage. `lines` counts records after blank and skipped lines are excluded. `control` counts records with an initial `control` match. `ok` means every counted line passed the whole-record checks. `empty` means no counted lines and no NUL corruption. `partial` means unreadable records or NUL corruption with either a recognized request or no counted records. `no_control` means there were records, but no request was recognized. Other statuses report gaps such as `read_failed`, `unreadable`, `dir_unreadable`, `missing`, `list_failed`, `changed`, `not_regular`, `unsafe_name`, `odd_copy`, or `search_failed`. `read_failed` is a corrupt or truncated archive, a decompressor that warned or is absent, or one that fails the script's own check by reporting success on trailing data, as BusyBox's do. `missing` includes an `active` path gone while its copies remain, as when the server still writes a deleted file; those copies are still searched. `not_regular` includes a log linked to stdout. An affected path can have several lines, including a read result followed by `changed`.
- `total`: `count` and `shown` per pattern, including candidates read before a failure and multiple request parts from one broken record. A run without a total for a required pattern cannot show zero candidates.
- `search`: The final `search=complete files=<n> problems=0` requires at least one `ok`, otherwise only `ok` or `empty`, and a completed traversal. `search=incomplete` reports problems or refuses input with `reason=empty-input`, `bad-show`, `active-not-in-logs`, `listed-twice`, `active-is-a-copy`, `unsupported-expression`, or `bad-expression`. Treat missing, truncated, or inconsistent output as a gap. A complete run still needs the skill's coverage checks.

Excerpts mask query strings, path parameters, fragments and recognizable absolute URI user information, and replace nonprintable bytes with dots. A `/`, `"` or space in URI user information can defeat masking, and when `control` does not start at the `"`, a query is masked only up to the next space. The prefix and the `first` and `last` fields over 200 characters, and a request over 300, lose their middle, replaced by `...`. The patterns are applied before that cut, so a `clipped` match is still a match; it shows only that its excerpt lost its middle, and its time, address and status are used when they are visible. In an nginx `escape=json` log, a raw non-ASCII byte in the request makes the record broken.

## Runs by date

When any pattern has `count > shown`, add a time prefix to `also` and rerun for each local log day intersecting the match window defined in [the skill](../SKILL.md#interpreting-time-and-coverage). Convert the window to the log's own time and keep the other filters. For an over-cap day, run each intersecting hour. Split an over-cap hour into ten-minute blocks, an over-cap block into minutes, and an over-cap minute into seconds. Use prefixes such as `[04/Aug/2026:`, `[04/Aug/2026:10:`, `[04/Aug/2026:10:1`, `[04/Aug/2026:10:12:` and `[04/Aug/2026:10:12:01`. If the format lacks a usable time prefix, keep the gap and use the evidence already shown.

An over-cap second leaves undisplayed candidates. Use the matches and anchors that were shown, including those shown before narrowing. For a negative verdict, account for every candidate that could be in range. Treat a missing, failed or still capped slice as a gap. A narrower run can account for previously hidden records only if its time filter selects them reliably, including across offset or format changes. If a record could fall outside the slices because its time is unreadable, or because the logs changed between runs, keep the gap unless the complete output accounts for it. Do not add totals from overlapping runs.

## The pairing run

Search for the advisory's first request as the anchor, regardless of how common it is. For each shown, readable, in-range anchor with an attributable application and a trustworthy client address, search for the second pattern on the same server across every applicable group of paths. Keep each group's `logs`, `active`, `control`, `line`, `skip`, `show` and application filter. Change `patterns` and add the validated address to `also`. Use a separate run per address and confirmed application value. A pair may cross values for the same application. A broken record cannot form either half of a pair.

Use `^<IP> ` for an address at the start of the line, or combine it with the trusted application prefix when the address immediately follows it, as in `^app.example:443 203.0.113.9 `. Else use a space on each side and verify that the address is in the client field. If the filter cannot select every record with that address, the follow-up leaves a gap.

Confirm both advisory statuses, application and address. Both records must fall in the match window and the second must follow the anchor by no more than 24 elapsed hours. For a capped address search, rerun with hour prefixes covering that interval for each applicable anchor, starting at its hour. Narrow any capped hour as in [runs by date](#runs-by-date). Use shown records from every run. Stop pursuing additional candidates for the verdict once a pair is confirmed.

For identical timestamps, run both patterns in one search for the address and exact log second. If the pair spans different application values, omit the application filter in that run and confirm the correct prefix on both records. Use the larger `line` as later only for two shown, whole records in the same file in this run, with completion timestamps and unbuffered, uncompressed logging. Same-second order remains unresolved if the file or its log path reports `changed`, if the records cannot be put in one file in one run, or if that logging format does not preserve completion order. Keep looking for other pairs if this one cannot be established.

## Metabase (CVE-2026-72898, GHSA-vwf4-m7j8-wcjf)

Re-read [Metabase's security update](https://www.metabase.com/blog/security-update). It names a `POST /api/session/reset_password` answered 400 followed by a `GET /api/user/current` answered 200, from the application or ingress log, so when a proxy on another server fronts Metabase, search that server too. It gives neither a correlation window nor a same-address requirement. Use this skill's pairing rules.

Use the supplied anchor for nginx or Apache common or combined logs. Keep its path-prefix and normalization alternatives. For the second request, use the expression below and add the confirmed base path before `/api` when Metabase is served under one.

```text
^"[Gg][Ee][Tt] +(([Hh][Tt][Tt][Pp][Ss]?://[^/"? ]*)?(/|/[.])*/api/(/|[.]/|([^"?/\\]|\\.)*/[.][.]/)*user/(/|[.]/|([^"?/\\]|\\.)*/[.][.]/)*|([^"?\\]|\\.)*/[.][.]/([^"?\\]|\\.)*/)current([?#;]([^"\\]|\\.)*)?( +[Hh][Tt][Tt][Pp]/[0-9.]+)? *" (200|499)( |$)
```
