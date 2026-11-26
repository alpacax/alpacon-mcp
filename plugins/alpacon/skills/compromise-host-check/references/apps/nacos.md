# Check Nacos application accounts

Run this separately with an application account that has `console/users` read permission. Nacos's official default-authentication plugin documents `GET /v3/auth/user/list` as the read-only paginated user-list command. It does not document a local command that obtains or safely supplies the required identity without exposing a token to `execute_file`, nor a creation-time response field. Verify credential delivery and the response shape on a real installation before replacing the explicit unknown result below. Never print a password, hash or access token.

Use `execute_file` with a fixed path in that account's home, `write_file: true`, `overwrite: true`, `interpreter: /bin/sh`, and a separate agreement. An `app_account` is an artifact when its name matches an incident indicator or its creation time is on or after `since`; unverified output is unknown.

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
emit unknown kind app_account path nacos reason command-needs-real-install-verification
```
