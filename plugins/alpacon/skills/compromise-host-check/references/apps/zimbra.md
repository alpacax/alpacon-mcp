# Check Zimbra application accounts

Run this separately from the host collector as the `zimbra` account. Zimbra's official `zmprov` reference documents `zmprov -l gaa` as the read-only command that lists all accounts. The official two-factor authentication page says app passcodes have labels, but it does not document an administrative command that lists those labels or their creation times. The script therefore emits accounts and an explicit unknown for app passcodes; verify the application-passcode command on a real installation before extending it. Never print password, passcode or token values.

Use `execute_file` with the fixed path `/opt/zimbra/alpacon-compromise-host-check.sh`, `write_file: true`, `overwrite: true`, `interpreter: /bin/sh`, `username: zimbra`, and a separate agreement. An `app_account` is an artifact when its name matches an incident indicator or its creation time is on or after `since`; a missing creation time or unverified app-password source is unknown even when account names can be compared.

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
if ! command -v zmprov >/dev/null 2>&1; then emit unknown kind app_account path zimbra reason missing-tool:zmprov; exit 0; fi
accounts=$(zmprov -l gaa 2>/dev/null) || { emit unknown kind app_account path zimbra reason failed; exit 0; }
while IFS= read -r name; do [ -n "$name" ] && emit app_account application zimbra name "$name" created! ? type account; done <<EOF
$accounts
EOF
emit unknown kind app_account path zimbra-app-passcodes reason command-needs-real-install-verification
```
