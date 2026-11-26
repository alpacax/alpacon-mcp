# Check MySQL accounts

Run this separately with the operating-system account that has read-only administrative socket access. MySQL's official grant-table reference documents `User`, `Host` and `password_last_changed` in `mysql.user`; the last field is a password-change proxy rather than an account creation time and can be null for external authentication. The script selects only those fields through the local socket and never selects authentication strings, password hashes or tokens. Verify the socket account and supported columns on the installed MySQL release before approval. The [official client options](https://dev.mysql.com/doc/refman/8.4/en/mysql-command-options.html) document the explicit socket protocol and option-file isolation used below.

Use `execute_file` with a fixed path in that account's home, `write_file: true`, `overwrite: true`, `interpreter: /bin/sh`, and a separate agreement. An `app_account` is an artifact when its name matches an incident indicator or its creation time is on or after `since`; a missing creation time is unknown for creation-time checks even when the names can be compared.

```sh
export LC_ALL=C TZ=UTC
LIB='
function init(  i) { for (i = 1; i < 256; i++) ord[sprintf("%c", i)] = i }
function esc(s,  o, i, c, n) {
  o = ""
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c ~ /^[A-Za-z0-9._~\/:@+,-]$/) o = o c
    else { n = ord[c]; if (n == "") n = 0; o = o sprintf("%%%02X", n) }
  }
  return o
}
function iso(t,  z, days, sod, era, doe, yoe, y, doy, mp, d, m) {
  z = int(t); days = int(z / 86400); sod = z - days * 86400
  if (sod < 0) { days--; sod += 86400 }
  z = days + 719468; era = int((z >= 0 ? z : z - 146096) / 146097)
  doe = z - era * 146097; yoe = int((doe - int(doe / 1460) + int(doe / 36524) - int(doe / 146096)) / 365)
  y = yoe + era * 400; doy = doe - (365 * yoe + int(yoe / 4) - int(yoe / 100)); mp = int((5 * doy + 2) / 153)
  d = doy - int((153 * mp + 2) / 5) + 1; m = mp + (mp < 10 ? 3 : -9); y += (m <= 2)
  return sprintf("%04d-%02d-%02dT%02d:%02d:%02dZ", y, m, d, int(sod / 3600), int((sod % 3600) / 60), sod % 60)
}
function val(k, v) { return k ~ /!$/ ? "?" : (k ~ /^(mtime|ctime|atime|now|start|end|begins)$/ && v ~ /^[0-9]+$/ ? iso(v) : esc(v)) }
'
emit() { awk "$LIB"'BEGIN { init(); l = ARGV[1]; for (i = 2; i < ARGC; i += 2) { k = ARGV[i]; sub(/!$/, "", k); l = l " " k "=" val(ARGV[i], ARGV[i + 1]) } print l; exit }' "$@"; }
if ! command -v mysql >/dev/null 2>&1; then emit unknown kind app_account path mysql reason missing-tool:mysql; exit 0; fi
rows=$(mysql --no-defaults --protocol=SOCKET --host=localhost --batch --skip-column-names --execute='SELECT User, Host, UNIX_TIMESTAMP(password_last_changed) FROM mysql.user' 2>/dev/null) || { emit unknown kind app_account path mysql reason failed; exit 0; }
tab=$(printf '\t')
while IFS="$tab" read -r user host changed; do [ -n "$user$host" ] || continue; emit app_account application mysql name "$user@$host" created! "${changed:-?}" type account; done <<EOF
$rows
EOF
emit unknown kind app_account path mysql reason creation-time-unavailable
```
