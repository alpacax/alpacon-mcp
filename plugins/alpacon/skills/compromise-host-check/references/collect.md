# Host artifact collection

The collector reads host metadata and selected persistence sources. It prints records only. It never changes host configuration or removes evidence.

## Arguments

Pass every input as one `key=value` argument, in this order: one `since`, sorted `webroot` values, sorted `protect` values, `pattern` values in the person's order, then sorted `inspect` values. A `protect` value names a secret path; Alpacon refuses an argument spelled `secret=` as an inline credential, so the key is `protect` while its records keep the kind `secret`.

| Key | Count | Value |
|---|---:|---|
| `since` | 1 | A real UTC date in `YYYY-MM-DD` form. |
| `webroot` | 0 or more | An absolute path without control bytes, at most 1024 bytes. |
| `protect` | 0 or more | An absolute path or a `~/` path, optionally with shell glob characters, without control bytes, at most 1024 bytes. |
| `pattern` | 0 or more | A nonempty fixed string without control bytes, at most 200 bytes. A leading dash is data. |
| `inspect` | 0 or more | An absolute file path, or `/proc/<pid>`, without control bytes, at most 1024 bytes. Any `inspect` value switches the run to inspect mode, which looks only at the named items. |

## Records

Each line is a kind followed by space-separated `key=value` fields. Values percent-encode every byte outside `[A-Za-z0-9._~/:@+,-]` as uppercase `%XX`. A lone `?` means unreadable; a literal question mark is `%3F`.

This table is the canonical kind and field catalog. The script, ATT&CK mapping, and tests must match it exactly.

| Kind | Fields | Source |
|---|---|---|
| `run` | `v uid now since sha256` | Collector identity and invocation. |
| `secret` | `path account exists type atime mtime ctime mount atime_mode` | Metadata only; content is never opened. |
| `account` | `name uid gid home shell class password pwchanged` | `getent passwd` (or passwd), login.defs, and shadow. Password hashes are never printed. |
| `sudoers` | `path line principal nopasswd all mtime ctime` | sudoers rules without command text. |
| `authkey` | `account path line type fp options mtime ctime` | Authorized key type, fingerprint, and option names. Key comments and option values are never printed. |
| `cron` | `path owner mode size mtime ctime sha256 hits packaged` | System and per-account cron files. |
| `systemd_unit` | `path account owner mode size mtime ctime sha256 target hits packaged` | System and user units. |
| `rc_local` | `path owner mode size mtime ctime sha256 hits packaged` | rc.local files. |
| `listen` | `proto addr port pid process exe deleted` | TCP and UDP listeners. |
| `connection` | `laddr lport raddr rport pid process exe deleted listening count` | Established TCP connections, including connections whose local port also listens. |
| `pkg_modified` | `manager path flags conf mtime ctime` | Package verification mismatches. |
| `webroot_file` | `root path owner mode size mtime ctime sha256 target hits` | Script-like files changed since the requested date. |
| `login` | `user tty from start end` | Numeric-address login history. |
| `wtmp` | `path begins` | Beginning of the available login history. |
| `file` | `path owner group mode links size atime mtime ctime sha256 package verify` | Inspect mode: one named file, its owning package and that file's package verification result (`ok`, `none` when no package owns it, or the verifier's flags). |
| `exec` | `source line key program sha256 package mtime ctime` | Inspect mode: the first word of a unit `Exec*=` line or a cron command, and every other absolute path in it that is an executable file, with that program's hash, package and times. Other arguments are never printed. |
| `journal` | `path start end comm unit count` | Inspect mode: journal entries per process and unit in the five minutes either side of a file's ctime. Messages are never printed. |
| `key_login` | `path fp start user from` | Inspect mode: sshd public-key logins since `since` with a key from a named `authorized_keys` file. |
| `process` | `pid comm exe deleted sha256 package start chain` | Inspect mode: one process, its executable and its parent chain as `pid:comm` pairs. |
| `app_account` | `application name created type` | Application-specific reference scripts. |
| `unknown` | `kind path reason` | A source or item that could not be judged. |
| `check` | `kind status` | Collector coverage: `complete`, `partial`, `unknown`, or `not_requested`. |
| `cap` | `kind total shown` | A record kind exceeded the output limit. |
| `end` | `status records unknowns` or `status arg reason` | Complete, incomplete, or refused collection. |

`check status=partial` means a collector emitted at least one data record and at least one `unknown`. `unknown` means it emitted no data record and at least one `unknown`. Only `secret` and `webroot_file` may be `not_requested`.

Before package verification, the collector uses `dpkg --search` or `rpm -qf` to ask whether each expanded secret file and its `readlink -f` target belong to a package without reading them. A secret directory is not queried, because a verifier hashes only package files, and those inside the directory are caught by the inventory check below. An owned path or an ownership-query error makes `pkg_modified` unknown with `reason=secret-overlap`; only an explicit not-owned result permits the verifier to run. It also inventories installed package paths (`dpkg --get-selections` plus `--listfiles`, or `rpm -qal`) on every run and checks them and their `readlink -f` targets before verification; an overlapping alias or an inventory failure skips verification with `reason=secret-overlap`, and a packaged FIFO skips it with `reason=not-a-file`.

## The script

Run this exact block with `execute_file`, `/bin/sh`, and arguments from the table. The block holds no tab and no quoted line break, so it survives being copied into a tool argument. The block is 923 lines, 53,463 bytes, with sha256 `cf08c4b806a642911b63069ccff84611fd0094e6f8d1b9b0c93a1e125c2f096a`; the `run` record repeats the sha256 of the bytes that ran. Alpamon runs a verified file from a sealed copy at `/proc/self/fd/N`, so the collector hashes that path directly instead of putting it through the secret checks. The `R=` line is empty on a host; tests replace only that line to point at a fixture tree.

```sh
# compromise-host-check collector v1
export LC_ALL=C TZ=UTC
NL=$(printf '\nx'); NL=${NL%x}
TAB=$(printf '\t')
R=
LIMIT=200
MAX_HASH=16777216

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

emit() {
  printf '%s\000' "$#"
  printf '%s\000' "$@"
}

refuse() { emit end status refused arg "$1" reason "$2" | finish; exit 2; }
append() {
  case "$1" in
    ACCTS) ACCTS=${ACCTS}${ACCTS:+$NL}$2;;
    WEBROOTS) WEBROOTS=${WEBROOTS}${WEBROOTS:+$NL}$2;;
    SECRETS) SECRETS=${SECRETS}${SECRETS:+$NL}$2;;
    PATTERNS) PATTERNS=${PATTERNS}${PATTERNS:+$NL}$2;;
    INSPECTS) INSPECTS=${INSPECTS}${INSPECTS:+$NL}$2;;
    EXPANDED_SECRETS) EXPANDED_SECRETS=${EXPANDED_SECRETS}${EXPANDED_SECRETS:+$NL}$2;;
    LISTEN_PORTS) LISTEN_PORTS=${LISTEN_PORTS}${LISTEN_PORTS:+$NL}$2;;
  esac
}

valid_date() {
  awk -v d="$1" 'BEGIN { if (d !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) exit 1; split(d,a,"-"); y=a[1]+0; m=a[2]+0; x=a[3]+0; md=31; if (m==4||m==6||m==9||m==11) md=30; if (m==2) md=28+((y%4==0&&y%100!=0)||y%400==0); exit !(m>=1&&m<=12&&x>=1&&x<=md) }'
}

parse_args() {
  SINCE= WEBROOTS= SECRETS= PATTERNS= INSPECTS= since_seen=0 argn=0
  for arg do
    argn=$((argn + 1))
    case "$arg" in *=*) key=${arg%%=*}; value=${arg#*=};; *) refuse "$argn" malformed;; esac
    bytes=$(printf %s "$value" | wc -c | tr -d ' ')
    printf '%s' "$value" | grep -q '[[:cntrl:]]' && refuse "$argn" control-byte
    case "$value" in *"$NL"*|*"$TAB"*) refuse "$argn" control-byte;; esac
    case "$key" in
      since) [ "$since_seen" -eq 0 ] || refuse "$argn" duplicate-since; valid_date "$value" || refuse "$argn" invalid-date; SINCE=$value; since_seen=1;;
      webroot) case "$value" in /*) :;; *) refuse "$argn" relative-webroot;; esac; [ "$bytes" -le 1024 ] || refuse "$argn" too-long; append WEBROOTS "$value";;
      protect) case "$value" in /*|\~/*) :;; *) refuse "$argn" relative-path;; esac; [ "$bytes" -le 1024 ] || refuse "$argn" too-long; append SECRETS "$value";;
      inspect) case "$value" in /*) :;; *) refuse "$argn" relative-path;; esac; [ "$bytes" -le 1024 ] || refuse "$argn" too-long; append INSPECTS "$value";;
      pattern) [ "$bytes" -gt 0 ] && [ "$bytes" -le 200 ] || refuse "$argn" invalid-pattern; append PATTERNS "$value";;
      *) refuse "$argn" unknown-key;;
    esac
  done
  [ "$since_seen" -eq 1 ] || refuse 0 no-since
  SINCE_EPOCH=$(awk -v d="$SINCE" 'BEGIN{split(d,a,"-");y=a[1]+0;m=a[2]+0;x=a[3]+0;y-=m<=2;e=int((y>=0?y:y-399)/400);q=y-e*400;z=int((153*(m+(m>2?-3:9))+2)/5)+x-1;print (e*146097+q*365+int(q/4)-int(q/100)+z-719468)*86400}')
}

begin_kind() { CURRENT_KIND=$1; KIND_RECORDS=0; KIND_UNKNOWNS=0; }
record() { emit "$@"; KIND_RECORDS=$((KIND_RECORDS + 1)); }
unknown() { emit unknown kind "$1" path "$2" reason "$3"; KIND_UNKNOWNS=$((KIND_UNKNOWNS + 1)); }
end_kind() {
  if [ "$KIND_UNKNOWNS" -eq 0 ]; then status=complete
  elif [ "$KIND_RECORDS" -gt 0 ]; then status=partial
  else status=unknown
  fi
  emit check kind "$CURRENT_KIND" status "$status"
}
not_requested() { emit check kind "$1" status not_requested; }
dir_unsearchable() { [ -d "$1" ] && { [ ! -r "$1" ] || [ ! -x "$1" ]; }; }
maybe_key() { MKEY=$1; [ "$2" = '?' ] && MKEY=$1!; }
change_times() {
  CT=$(stat -c '%Y:%Z' -- "$1" 2>/dev/null) || return 1
  [ -L "$1" ] || return 0
  ct_target=$(stat -L -c '%Y:%Z' -- "$1" 2>/dev/null) || return 1
  [ "${ct_target%:*}" -le "${CT%:*}" ] || CT=${ct_target%:*}:${CT#*:}
  [ "${ct_target#*:}" -le "${CT#*:}" ] || CT=${CT%:*}:${ct_target#*:}
}
target_packaged() {
  [ "${PACKAGE_KNOWN:-no}" = yes ] || return 1
  tp=$(readlink -f -- "$1" 2>/dev/null) || return 1; tp=${tp#"$R"}; tp_alt=$(alt_path "$tp")
  while IFS= read -r owned; do [ "$owned" != "$tp" ] && [ "$owned" != "${tp_alt:-/}" ] || return 0; done <<EOF
$PACKAGE_OWNED
EOF
  return 1
}
alt_path() { case "$1" in /usr/lib/*) printf '%s\n' "${1#/usr}";; /lib/*) printf '%s\n' "/usr$1";; esac; }
same_id() { case "$1" in *:*) [ "$1" = "$2" ];; *) [ "$1" = "${2#*:}" ];; esac; }
secret_fd() {
  fd_id=${1%:*}; fd_links=${1##*:}
  [ -n "$EXPANDED_SECRETS" ] || return 1
  for fd_snapshot in $SECRET_IDS; do ! same_id "$fd_id" "$fd_snapshot" || return 0; done
  while IFS='|' read -r fd_ctime fd_dir; do
    [ -n "$fd_dir" ] || continue
    [ "$(stat -L -c %z -- "$fd_dir" 2>/dev/null)" = "$fd_ctime" ] || return 0
  done <<EOF
$SECRET_DIRS
EOF
  if [ -d /proc/self/fd ]; then
    fd_path=$(readlink /proc/self/fd/3 2>/dev/null) || return 0
    case "$fd_path" in *' (deleted)') return 0;; esac
    secret_overlap "${fd_path#"$R"}" && return 0
  fi
  while IFS=: read -r fd_account fd_spec; do
    saved_ifs=$IFS; IFS=$NL; set -- "$R"$fd_spec; IFS=$saved_ifs
    for fd_secret do
      fd_secret_id=$(stat -L -c '%d:%i' -- "$fd_secret" 2>/dev/null) || continue
      ! same_id "$fd_id" "$fd_secret_id" || return 0
      [ ! -d "$fd_secret" ] || [ "$fd_links" -le 1 ] || return 0
    done
  done <<EOF
$EXPANDED_SECRETS
EOF
  return 1
}
read_file() {
  rf_file=$1; shift
  [ -f "$rf_file" ] && [ -r "$rf_file" ] || return 125
  if [ -d /proc/self/fd ]; then rf_fd=/proc/self/fd/3 rf_format='%d:%i:%h'; else rf_fd=/dev/fd/3 rf_format='%i:%h'; fi
  { if rf_meta=$(stat -L -c "$rf_format" "$rf_fd" 2>/dev/null) && [ -f "$rf_fd" ] && { [ -z "${RF_EXPECT:-}" ] || same_id "${rf_meta%:*}" "$RF_EXPECT"; } && ! secret_fd "$rf_meta"; then "$@" <&3; else return 125; fi; } 3< "$rf_file"
}
no_accounts() { reason=unreadable; secret_overlap /etc/passwd && reason=secret-overlap; unknown "$1" /etc/passwd "$reason"; }

load_accounts() {
  UID_MIN=1000 UID_MAX=60000
  if ! secret_overlap /etc/login.defs && [ -r "$R/etc/login.defs" ]; then
    defs=$(read_file "$R/etc/login.defs" awk '$1=="UID_MIN"&&min==""{min=$2} $1=="UID_MAX"&&max==""{max=$2} END{print min ":" max}') || defs=:
    value=${defs%%:*}; case "$value" in ''|*[!0-9]*) :;; *) UID_MIN=$value;; esac
    value=${defs#*:}; case "$value" in ''|*[!0-9]*) :;; *) UID_MAX=$value;; esac
  fi
  ACCTS=
  secret_overlap /etc/passwd && return
  if command -v getent >/dev/null 2>&1 && passwd_rows=$(getent passwd 2>/dev/null); then :
  elif passwd_rows=$(read_file "$R/etc/passwd" awk 1); then :
  else return
  fi
  while IFS=: read -r name x uid gid gecos home shell; do
    [ -n "$name" ] || continue
    class=
    if [ "$uid" -eq 0 ] 2>/dev/null; then class=root
    elif [ "$uid" -ge "$UID_MIN" ] 2>/dev/null && [ "$uid" -le "$UID_MAX" ] 2>/dev/null && [ "$uid" != 65534 ]; then class=human
    else case "$shell" in */nologin|*/false|'') class=system-nologin;; *) class=system-login;; esac
    fi
    append ACCTS "$name:$uid:$gid:$home:$shell:$class:$x"
  done <<EOF
$passwd_rows
EOF
}

expand_secrets() {
  EXPANDED_SECRETS=
  [ -n "$SECRETS" ] || return
  while IFS= read -r spec; do
    case "$spec" in
      \~/*) while IFS=: read -r name uid gid home shell class passwd_password; do [ -n "$name" ] || continue; append EXPANDED_SECRETS "$name:${home}${spec#\~}"; done <<EOF
$ACCTS
EOF
      ;;
      *) append EXPANDED_SECRETS ":$spec";;
    esac
  done <<EOF
$SECRETS
EOF
}

secret_overlap() {
  overlap_logical=$1
  [ -n "$EXPANDED_SECRETS" ] || return 1
  overlap_target=$(readlink -f -- "$R$overlap_logical" 2>/dev/null) || { [ ! -e "$R$overlap_logical" ] && [ ! -L "$R$overlap_logical" ] && return 1; return 0; }
  overlap_id=$(stat -L -c '%d:%i' -- "$R$overlap_logical" 2>/dev/null)
  while IFS=: read -r secret_account secret_spec; do
    case "$overlap_logical" in $secret_spec) return 0;; esac
    case "${overlap_target#"$R"}" in $secret_spec) return 0;; esac
    saved_ifs=$IFS; IFS=$NL; set -- "$R"$secret_spec; IFS=$saved_ifs
    for secret_file do
      secret_target=$(readlink -f -- "$secret_file" 2>/dev/null) || continue
      [ "$overlap_target" != "$secret_target" ] || return 0
      if [ -d "$secret_file" ]; then case "$overlap_target" in "${secret_target%/}"/*) return 0;; esac; fi
      [ -z "$overlap_id" ] || [ "$overlap_id" != "$(stat -L -c '%d:%i' -- "$secret_file" 2>/dev/null)" ] || return 0
    done
  done <<EOF
$EXPANDED_SECRETS
EOF
  return 1
}

mount_mode() {
  logical=$1
  secret_overlap /proc/self/mountinfo && { printf '%s\n%s\n' '?' '?'; return; }
  [ -r "$R/proc/self/mountinfo" ] || { printf '%s\n%s\n' '?' '?'; return; }
  mm=$(export LOGICAL="$logical"; read_file "$R/proc/self/mountinfo" awk '
    function decode(s,out,i,x) { out=""; for(i=1;i<=length(s);){x=substr(s,i,4);if(x=="\\040"){out=out " ";i+=4}else if(x=="\\011"){out=out sprintf("%c",9);i+=4}else if(x=="\\012"){out=out sprintf("%c",10);i+=4}else if(x=="\\134"){out=out sprintf("%c",92);i+=4}else{out=out substr(s,i,1);i++}} return out }
    BEGIN { logical=ENVIRON["LOGICAL"] }
    { mount=decode($5); opts=$6; if((mount=="/"||logical==mount||index(logical,mount "/")==1)&&length(mount)>=length(best)){best=mount;bestopts=opts} }
    END { if(best==""){print "?";print "?";exit} mode="strictatime";if(("," bestopts ",")~/,ro,/)mode="readonly";else if(("," bestopts ",")~/,noatime,/)mode="noatime";else if(("," bestopts ",")~/,relatime,/)mode="relatime";print best;print mode }
  ') || mm="?$NL?"
  printf '%s\n' "$mm"
}

glob_blocked() {
  gb_rest=${1#/} gb_dirs=/
  while :; do
    while IFS= read -r gb_dir; do [ -z "$gb_dir" ] || [ -x "$R$gb_dir" ] || return 0; done <<EOF
$gb_dirs
EOF
    gb_part=${gb_rest%%/*}
    case "$gb_part" in *[*?[]*) while IFS= read -r gb_dir; do [ -z "$gb_dir" ] || [ -r "$R$gb_dir" ] || return 0; done <<EOF
$gb_dirs
EOF
    ;; esac
    case "$gb_rest" in */*) gb_rest=${gb_rest#*/};; *) return 1;; esac
    gb_next=
    while IFS= read -r gb_dir; do
      [ -n "$gb_dir" ] || continue
      saved_ifs=$IFS; IFS=$NL; set -- "$R${gb_dir%/}/"$gb_part; IFS=$saved_ifs
      for gb_match do [ -d "$gb_match" ] && gb_next=${gb_next}${gb_next:+$NL}${gb_match#"$R"}; done
    done <<EOF
$gb_dirs
EOF
    gb_dirs=$gb_next
    [ -n "$gb_dirs" ] || return 1
  done
}

snapshot_secrets() {
  while IFS=: read -r account spec; do
    [ -n "$spec" ] || continue
    matched=0; saved_ifs=$IFS; IFS=$NL; set -- "$R"$spec; IFS=$saved_ifs
    for physical do
      logical=${physical#"$R"}; [ -e "$physical" ] || [ -L "$physical" ] || continue
      matched=1; meta=$(stat -L -c '%X:%Y:%Z' -- "$physical" 2>/dev/null) || meta='?:?:?'
      id=$(stat -L -c '%d:%i' -- "$physical" 2>/dev/null) && SECRET_IDS="$SECRET_IDS $id"
      if [ -d "$physical" ]; then dir_ctime=$(stat -L -c %z -- "$physical" 2>/dev/null) || dir_ctime=?; SECRET_DIRS=${SECRET_DIRS}${SECRET_DIRS:+$NL}"$dir_ctime|$physical"; fi
      SECRET_SNAPSHOTS=${SECRET_SNAPSHOTS}${SECRET_SNAPSHOTS:+$NL}$account:yes:$meta:$logical
    done
    state=no; [ "$matched" -eq 0 ] || state=
    if glob_blocked "$spec"; then state='?'; fi
    [ -z "$state" ] || SECRET_SNAPSHOTS=${SECRET_SNAPSHOTS}${SECRET_SNAPSHOTS:+$NL}$account:$state:?:?:?:$spec
  done <<EOF
$EXPANDED_SECRETS
EOF
}

collect_secrets() {
  [ -n "$SECRETS" ] || { not_requested secret; return; }
  begin_kind secret
  case "$SECRETS" in '~/'*|*"$NL~/"*) [ -n "$ACCTS" ] || no_accounts secret;; esac
  while IFS=: read -r account exists atime mtime ctime logical; do
    if [ "$exists" = '?' ]; then unknown secret "$logical" unsearchable; continue; fi
    if [ "$exists" = no ]; then record secret path "$logical" account "$account" exists no type! '' atime! '' mtime! '''' ctime! '' mount! '' atime_mode! ''; continue; fi
    if [ "$atime" = '?' ]; then unknown secret "$logical" unreadable; continue; fi
    mount_path=$(readlink -f -- "$R$logical" 2>/dev/null) && mount_path=${mount_path#"$R"} || mount_path=$logical
    mm=$(mount_mode "$mount_path"); mount=${mm%
*}; mode=${mm##*
}
    maybe_key mount "$mount"; mount_key=$MKEY; maybe_key atime_mode "$mode"; mode_key=$MKEY
    type=other; if [ -d "$R$logical" ]; then type=directory; elif [ -f "$R$logical" ]; then type=file; fi
    record secret path "$logical" account "$account" exists yes type "$type" atime "$atime" mtime "$mtime" ctime "$ctime" "$mount_key" "$mount" "$mode_key" "$mode"
  done <<EOF
$SECRET_SNAPSHOTS
EOF
  end_kind
}

collect_accounts() {
  begin_kind account
  [ -n "$ACCTS" ] || { no_accounts account; end_kind; return; }
  shadow_ok=1; shadow_reason=unreadable
  if secret_overlap /etc/shadow; then shadow_ok=0; shadow_reason=secret-overlap; elif [ ! -f "$R/etc/shadow" ] && [ -e "$R/etc/shadow" ]; then shadow_ok=0; shadow_reason=not-a-file; elif [ ! -r "$R/etc/shadow" ]; then shadow_ok=0
  elif ! shadow_rows=$(read_file "$R/etc/shadow" awk -F: '{c="set";if($2=="")c="none";else if($2~/^[!*]/)c="locked";print $1 ":" c ":" $3}'); then shadow_ok=0; shadow_reason=changed-during-read
  fi
  while IFS=: read -r name uid gid home shell class passwd_password; do
    password=? pwchanged=?
    if [ "$shadow_ok" -eq 1 ]; then
      row=$(printf '%s\n' "$shadow_rows" | awk -F: -v n="$name" '$1==n{print $2 ":" $3; exit}')
      state=${row%%:*}; changed=${row#*:}
      if [ -n "$row" ]; then password=$state; [ -n "$changed" ] && pwchanged=$(awk "$LIB"'BEGIN{print substr(iso(ARGV[1]*86400),1,10);exit}' "$changed"); fi
    fi
    [ -n "$passwd_password" ] || password=none
    maybe_key password "$password"; password_key=$MKEY; maybe_key pwchanged "$pwchanged"; changed_key=$MKEY
    record account name "$name" uid "$uid" gid "$gid" home "$home" shell "$shell" class "$class" "$password_key" "$password" "$changed_key" "$pwchanged"
  done <<EOF
$ACCTS
EOF
  [ "$shadow_ok" -eq 1 ] || unknown account /etc/shadow "$shadow_reason"
  end_kind
}

collect_sudoers() {
  begin_kind sudoers
  if dir_unsearchable "$R/etc/sudoers.d"; then unknown sudoers /etc/sudoers.d unsearchable; fi
  for file in "$R"/etc/sudoers.d/* "$R/etc/sudoers"; do
    [ -e "$file" ] || continue; logical=${file#"$R"}
    case "${logical##*/}" in *.*|*~) continue;; esac
    if secret_overlap "$logical"; then unknown sudoers "$logical" secret-overlap; continue; fi
    [ -f "$file" ] || { unknown sudoers "$logical" not-a-file; continue; }
    [ -r "$file" ] || { unknown sudoers "$logical" unreadable; continue; }
    change_times "$file" || { unknown sudoers "$logical" unreadable; continue; }; mtime=${CT%:*}; ctime=${CT#*:}
    rows=$(read_file "$file" awk 'function rule(s,n, p,np,al){sub(/^[ \t]+/,"",s);if(s~/^(@|#)include(dir)?[ \t]+/){split(s,a,/[ \t]+/);print n "\t@include\t" a[2];return}if(s==""||s~/^#/||s~/^Defaults([ \t:@!>]|$)/||s~/^[A-Za-z_]+_Alias([ \t]|$)/)return;split(s,a,/[ \t]+/);p=a[1];np=(s~/NOPASSWD:/?"yes":"no");al=(s~/ALL[ \t]*=[ \t]*\(ALL(:ALL)?\)[ \t]*(NOPASSWD:[ \t]*)?ALL/?"yes":"no");print n "\t" p "\t" np "\t" al} {if(buf=="")start=NR;line=$0;if(line~/\\[ \t]*$/){sub(/\\[ \t]*$/, "", line);buf=buf line " ";next}rule(buf line,start);buf=""} END{if(buf!="")rule(buf,start)}') || { unknown sudoers "$logical" changed-during-read; continue; }
    [ -n "$rows" ] || continue
    while IFS=$TAB read -r line principal nopasswd all; do
      if [ "$principal" = @include ]; then case "$nopasswd" in /etc/sudoers.d) :;; *) unknown sudoers "$logical" include-outside-default;; esac; continue; fi
      record sudoers path "$logical" line "$line" principal "$principal" nopasswd "$nopasswd" all "$all" mtime "$mtime" ctime "$ctime"
    done <<EOF
$rows
EOF
  done
  end_kind
}

collect_authkeys() {
  begin_kind authkey
  [ -n "$ACCTS" ] || no_accounts authkey
  if dir_unsearchable "$R/etc/ssh/sshd_config.d"; then unknown authkey /etc/ssh/sshd_config.d unsearchable; fi
  for cfg in "$R/etc/ssh/sshd_config" "$R"/etc/ssh/sshd_config.d/*; do
    [ -e "$cfg" ] || continue
    if secret_overlap "${cfg#"$R"}"; then unknown authkey "${cfg#"$R"}" secret-overlap; continue; fi
    [ -f "$cfg" ] || { unknown authkey "${cfg#"$R"}" not-a-file; continue; }
    [ -r "$cfg" ] || { unknown authkey "${cfg#"$R"}" unreadable; continue; }
    flags=$(read_file "$cfg" awk 'match($0,/^[ \t]*[A-Za-z]+[ \t]*=/){$0=substr($0,1,RLENGTH-1) " " substr($0,RLENGTH+1)} function norm(p, n,a,i,o,k){n=split(p,a,"/");k=0;for(i=1;i<=n;i++){if(a[i]==""||a[i]==".")continue;if(a[i]==".."){if(k)k--;continue}o[++k]=a[i]}p="";for(i=1;i<=k;i++)p=p "/" o[i];return p} tolower($1)=="include"{for(i=2;i<=NF;i++){p=$i;gsub(/"/,"",p);if(p!~/^\//)p="/etc/ssh/" p;if(index(norm(p),"/etc/ssh/sshd_config.d/")!=1)inc=1}} tolower($1)=="authorizedkeyscommand"&&$2!="none"{cmd=1} tolower($1)=="authorizedkeysfile"{for(i=2;i<=NF;i++)if($i!=".ssh/authorized_keys"&&$i!=".ssh/authorized_keys2")file=1} END{print (inc?"i":"") (cmd?"c":"") (file?"f":"")}') || { unknown authkey "${cfg#"$R"}" changed-during-read; continue; }
    case "$flags" in *i*) unknown authkey "${cfg#"$R"}" include-outside-default;; esac
    case "$flags" in *c*) unknown authkey "${cfg#"$R"}" authorized-keys-command;; *f*) unknown authkey "${cfg#"$R"}" non-default-authorized-keys-file;; esac
  done
  while IFS=: read -r account uid gid home shell class passwd_password; do
    if [ -d "$R$home" ] && [ ! -x "$R$home" ]; then unknown authkey "$home" unsearchable; continue; fi
    if dir_unsearchable "$R$home/.ssh"; then unknown authkey "$home/.ssh" unsearchable; continue; fi
    for logical in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
      file=$R$logical; [ -e "$file" ] || continue
      if secret_overlap "$logical"; then unknown authkey "$logical" secret-overlap; continue; fi
      [ -f "$file" ] || { unknown authkey "$logical" not-a-file; continue; }
      [ -r "$file" ] || { unknown authkey "$logical" unreadable; continue; }
      change_times "$file" || { unknown authkey "$logical" unreadable; continue; }; mtime=${CT%:*}; ctime=${CT#*:}
      rows=$(read_file "$file" awk 'function keytype(s){return s~/^(ssh-(dss|rsa|ed25519)(-cert-v01@openssh.com)?|ecdsa-sha2-nistp(256|384|521)(-cert-v01@openssh.com)?|sk-(ssh-ed25519|ecdsa-sha2-nistp256)(-cert-v01)?@openssh.com)$/} function optnames(s, names,count,i,c,quoted,escaped,start,item,j,name,out,x){start=1;for(i=1;i<=length(s)+1;i++){c=substr(s,i,1);if(escaped){escaped=0;continue}if(c=="\\"){escaped=1;continue}if(c=="\""){quoted=!quoted;continue}if((c==","&&!quoted)||i>length(s)){item=substr(s,start,i-start);quoted=escaped=0;name="";for(j=1;j<=length(item);j++){c=substr(item,j,1);if(escaped){escaped=0;continue}if(c=="\\"){escaped=1;continue}if(c=="\""){quoted=!quoted;continue}if(c=="="&&!quoted){name=substr(item,1,j-1);break}}if(name=="")name=item;gsub(/^[ \t]+|[ \t]+$/, "", name);if(name!="")names[++count]=name;start=i+1}}for(i=1;i<=count;i++)for(j=i+1;j<=count;j++)if(names[j]<names[i]){x=names[i];names[i]=names[j];names[j]=x}for(i=1;i<=count;i++)out=out (out?",":"") names[i];return out} function parse(line,n,i,c,quoted,escaped,start,token,count){n=length(line);start=1;for(i=1;i<=n+1;i++){c=substr(line,i,1);if(escaped){escaped=0;continue}if(c=="\\"){escaped=1;continue}if(c=="\""){quoted=!quoted;continue}if(((c==" "||c=="\t")&&!quoted)||i>n){if(i>start){token=substr(line,start,i-start);if(keytype(token)){rest=substr(line,i+1);sub(/^[ \t]+/,"",rest);split(rest,a,/[ \t]+/);print NR "\t" token "\t" a[1] "\t" optnames(substr(line,1,start-1));return}}start=i+1}}print NR "\t?"} /^[ \t]*($|#)/{next} {parse($0)}') || { unknown authkey "$logical" changed-during-read; continue; }
      [ -n "$rows" ] || continue
      while IFS=$TAB read -r line type blob options; do
        [ "$type" != '?' ] || { unknown authkey "$logical" unparsed; continue; }
        fp=?
        if command -v ssh-keygen >/dev/null 2>&1; then out=$(printf '%s %s\n' "$type" "$blob" | ssh-keygen -lf - 2>/dev/null); set -- $out; [ -n "${2:-}" ] && fp=$2; fi
        maybe_key fp "$fp"; record authkey account "$account" path "$logical" line "$line" type "$type" "$MKEY" "$fp" options "$options" mtime "$mtime" ctime "$ctime"
      done <<EOF
$rows
EOF
    done
  done <<EOF
$ACCTS
EOF
  end_kind
}

pattern_hits() {
  file=$1; secret_overlap "${file#"$R"}" && { printf %s '?'; return; }; [ -n "$PATTERNS" ] || { printf %s ''; return; }
  set --; while IFS= read -r p; do set -- "$@" -e "$p"; done <<EOF
$PATTERNS
EOF
  rows=$(read_file "$file" grep -a -n -o -F "$@" 2>/dev/null); [ "$?" -le 1 ] || { printf %s '?'; return; }; hits=
  while IFS= read -r row; do [ -n "$row" ] || continue; line=${row%%:*}; match=${row#*:}; n=0; i=0
    while IFS= read -r p; do i=$((i + 1)); [ "$p" = "$match" ] && { n=$i; break; }; done <<EOF
$PATTERNS
EOF
    [ "$n" -gt 0 ] && hits=${hits}${hits:+,}$n@$line
  done <<EOF
$rows
EOF
  printf %s "$hits"
}

file_record() {
  kind=$1 logical=$2 account=$3 root=$4; file=$R$logical
  if secret_overlap "$logical"; then unknown "$kind" "$logical" secret-overlap; return; fi
  if [ "${PACKAGE_SCAN:-no}" = yes ]; then PACKAGE_PATHS=${PACKAGE_PATHS}${PACKAGE_PATHS:+$NL}$logical; return; fi
  [ -L "$file" ] || [ -r "$file" ] || { unknown "$kind" "$logical" unreadable; return; }
  pre_id=$(stat -L -c '%d:%i' -- "$file" 2>/dev/null)
  meta=$(stat -c '%Y:%Z:%s:%U:%a' -- "$file" 2>/dev/null) || { unknown "$kind" "$logical" unreadable; return; }
  IFS=: read -r mtime ctime size owner mode <<EOF
$meta
EOF
  target= sha=? hits= hits_key=hits
  if [ -L "$file" ]; then
    target=$(readlink -- "$file" 2>/dev/null || printf %s '?')
    if ! target_packaged "$file" && change_times "$file"; then mtime=${CT%:*}; ctime=${CT#*:}; fi
  fi
  if [ -f "$file" ]; then
    [ ! -L "$file" ] || size=$(stat -L -c %s -- "$file" 2>/dev/null) || size=?
    RF_EXPECT=$pre_id
    if [ ! -r "$file" ]; then RF_EXPECT=; hits_key=hits!; unknown "$kind" "$logical" unreadable
    elif [ "$size" -le "$MAX_HASH" ] 2>/dev/null; then
      sum=$(read_file "$file" sha256sum 2>/dev/null); rc=$?
      [ "$rc" -ne 125 ] || { RF_EXPECT=; unknown "$kind" "$logical" changed-during-read; return; }
      sha=${sum%% *}; [ "$rc" -eq 0 ] && [ -n "$sha" ] || { sha=?; unknown "$kind" "$logical" unreadable; }
    fi
    if [ "$hits_key" = hits ]; then
      hits=$(pattern_hits "$file")
      [ "$hits" != '?' ] || { hits_key=hits!; unknown "$kind" "$logical" search-failed; }
    fi
    RF_EXPECT=
    post_id=$(stat -L -c '%d:%i' -- "$file" 2>/dev/null)
    if [ "$post_id" != "$pre_id" ] || secret_overlap "$logical"; then unknown "$kind" "$logical" changed-during-read; return; fi
  fi
  packaged=?
  if [ "${PACKAGE_KNOWN:-no}" = yes ]; then
    packaged=no
    alt=$(alt_path "$logical")
    while IFS= read -r owned; do [ "$owned" != "$logical" ] && [ "$owned" != "${alt:-/}" ] || packaged=yes; done <<EOF
$PACKAGE_OWNED
EOF
  fi
  maybe_key packaged "$packaged"; packaged_key=$MKEY
  case "$kind" in
    cron|rc_local) maybe_key sha256 "$sha"; record "$kind" path "$logical" owner "$owner" mode "$mode" size "$size" mtime "$mtime" ctime "$ctime" "$MKEY" "$sha" "$hits_key" "$hits" "$packaged_key" "$packaged";;
    systemd_unit) maybe_key sha256 "$sha"; record systemd_unit path "$logical" account "$account" owner "$owner" mode "$mode" size "$size" mtime "$mtime" ctime "$ctime" "$MKEY" "$sha" target "$target" "$hits_key" "$hits" "$packaged_key" "$packaged";;
    webroot_file) maybe_key sha256 "$sha"; record webroot_file root "$root" path "$logical" owner "$owner" mode "$mode" size "$size" mtime "$mtime" ctime "$ctime" "$MKEY" "$sha" target "$target" "$hits_key" "$hits";;
  esac
}

collect_persistence() {
  persistence=$1 PACKAGE_PATHS= PACKAGE_SCAN=yes
  walk_"$persistence" >/dev/null
  PACKAGE_SCAN=no PACKAGE_KNOWN=no PACKAGE_OWNED=
  set --
  while IFS= read -r path; do
    [ -n "$path" ] || continue; set -- "$@" "$path" $(alt_path "$path")
    if [ -L "$R$path" ] && link_target=$(readlink -f -- "$R$path" 2>/dev/null); then set -- "$@" "${link_target#"$R"}" $(alt_path "${link_target#"$R"}"); fi
  done <<EOF
$PACKAGE_PATHS
EOF
  if [ "$#" -gt 0 ]; then
    if command -v dpkg >/dev/null 2>&1; then
      owned=$(dpkg --search "$@" 2>/dev/null); rc=$?
      if [ "$rc" -le 1 ]; then PACKAGE_KNOWN=yes; PACKAGE_OWNED=$(printf '%s\n' "$owned" | awk '/^(local )?diversion /{next}{sub(/^[^\/]*: \//,"/");if($0~/^\//)print}'); fi
    elif command -v rpm >/dev/null 2>&1; then
      owned=$(rpm -qf --queryformat '[%{FILENAMES}\n]' -- "$@" 2>/dev/null); rc=$?
      if [ "$rc" -le 1 ] || printf '%s\n' "$owned" | awk 'NF&&!/^\//&&!/ is not owned by any package$/{bad=1} END{exit bad}'; then PACKAGE_KNOWN=yes; PACKAGE_OWNED=$(printf '%s\n' "$owned" | awk '/^\//'); fi
    fi
  fi
  walk_"$persistence"
}

walk_cron() {
  begin_kind cron
  for dir in /etc/cron.d /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /etc/cron.monthly /etc/cron.yearly /var/spool/cron /var/spool/cron/crontabs; do
    if dir_unsearchable "$R$dir"; then unknown cron "$dir" unsearchable; fi
  done
  for file in "$R/etc/crontab" "$R/etc/anacrontab" "$R"/etc/cron.d/* "$R"/etc/cron.d/.[!.]* "$R"/etc/cron.d/..?* "$R"/etc/cron.hourly/* "$R"/etc/cron.hourly/.[!.]* "$R"/etc/cron.daily/* "$R"/etc/cron.daily/.[!.]* "$R"/etc/cron.weekly/* "$R"/etc/cron.weekly/.[!.]* "$R"/etc/cron.monthly/* "$R"/etc/cron.monthly/.[!.]* "$R"/etc/cron.yearly/* "$R"/etc/cron.yearly/.[!.]* "$R"/var/spool/cron/* "$R"/var/spool/cron/.[!.]* "$R"/var/spool/cron/crontabs/* "$R"/var/spool/cron/crontabs/.[!.]*; do [ -f "$file" ] || [ -L "$file" ] || continue; file_record cron "${file#"$R"}" '' ''; done
  end_kind
}

walk_systemd() {
  begin_kind systemd_unit
  [ -n "$ACCTS" ] || no_accounts systemd_unit
  for dir in /etc/systemd/system /etc/systemd/system.control /etc/systemd/user /run/systemd/system /run/systemd/system.control /run/systemd/transient /run/systemd/user /usr/local/lib/systemd/system /usr/local/lib/systemd/user /etc/systemd/system-generators /etc/systemd/user-generators /usr/local/lib/systemd/system-generators /usr/local/lib/systemd/user-generators; do
    [ -d "$R$dir" ] || continue
    unit_walk '' "$R$dir" all
  done
  for dir in /lib/systemd/system /lib/systemd/user /lib/systemd/system-generators /lib/systemd/user-generators /usr/lib/systemd/system /usr/lib/systemd/user /usr/lib/systemd/system-generators /usr/lib/systemd/user-generators; do
    [ -d "$R$dir" ] || continue
    case "$dir" in /lib/*) [ ! -L "$R/lib" ] || continue;; esac
    unit_walk '' "$R$dir" changed
  done
  while IFS=: read -r account uid gid home shell class passwd_password; do
    if [ -d "$R$home" ] && [ ! -x "$R$home" ]; then unknown systemd_unit "$home" unsearchable; continue; fi
    for dir in "$home/.config/systemd/user" "$home/.local/share/systemd/user"; do
      [ -d "$R$dir" ] || continue
      unit_walk "$account" "$R$dir" all
    done
  done <<EOF
$ACCTS
EOF
  end_kind
}

unit_walk() {
  unit_account=$1; unit_dir=$2; unit_filter=$3
  if secret_overlap "${unit_dir#"$R"}"; then unknown systemd_unit "${unit_dir#"$R"}" secret-overlap; return; fi
  if dir_unsearchable "$unit_dir"; then unknown systemd_unit "${unit_dir#"$R"}" unsearchable; return; fi
  for file in "$unit_dir"/* "$unit_dir"/.[!.]* "$unit_dir"/..?*; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    case "${file##*/}" in *.scope|*.slice|*.scope.d|*.slice.d) continue;; esac
    if [ -d "$file" ] && [ ! -L "$file" ]; then unit_walk "$unit_account" "$file" "$unit_filter"; continue; fi
    if [ "$unit_filter" = changed ]; then
      times=$(stat -c '%Y:%Z' -- "$file" 2>/dev/null) || { unknown systemd_unit "${file#"$R"}" unreadable; continue; }
      mtime=${times%:*}; ctime=${times#*:}
      if [ "$mtime" -lt "$SINCE_EPOCH" ] 2>/dev/null && [ "$ctime" -lt "$SINCE_EPOCH" ] 2>/dev/null; then continue; fi
    fi
    file_record systemd_unit "${file#"$R"}" "$unit_account" ''
  done
}

walk_rc_local() {
  begin_kind rc_local
  for logical in /etc/rc.local /etc/rc.d/rc.local; do [ -e "$R$logical" ] || [ -L "$R$logical" ] || continue; file_record rc_local "$logical" '' ''; done
  end_kind
}

split_endpoint() { EP_ADDR=${1%:*}; EP_PORT=${1##*:}; EP_ADDR=${EP_ADDR#[}; EP_ADDR=${EP_ADDR%]}; case "$EP_ADDR" in ::[fF][fF][fF][fF]:*.*) EP_ADDR=${EP_ADDR##*:};; esac; }
proc_fields() {
  pid=$1 process=? exe=? deleted=no PROCESS_UNKNOWN=yes EXE_UNKNOWN=yes
  if [ "$pid" = '?' ]; then unknown "$CURRENT_KIND" '' no-process; return; fi
  [ -e "$R/proc/$pid" ] || { unknown "$CURRENT_KIND" "/proc/$pid" exited; return; }
  if secret_overlap "/proc/$pid/comm"; then unknown "$CURRENT_KIND" "/proc/$pid/comm" secret-overlap
  elif [ -r "$R/proc/$pid/comm" ]; then IFS= read -r process < "$R/proc/$pid/comm" && PROCESS_UNKNOWN=no || { process=?; unknown "$CURRENT_KIND" "/proc/$pid/comm" unreadable; }
  else unknown "$CURRENT_KIND" "/proc/$pid/comm" unreadable
  fi
  if [ -L "$R/proc/$pid/exe" ]; then
    if exe=$(readlink -- "$R/proc/$pid/exe" 2>/dev/null); then EXE_UNKNOWN=no; case "$exe" in *' (deleted)') exe=${exe%' (deleted)'}; deleted=yes;; esac
    else exe=?; unknown "$CURRENT_KIND" "/proc/$pid/exe" unreadable
    fi
  else unknown "$CURRENT_KIND" "/proc/$pid/exe" unreadable
  fi
}

socket_pid() {
  printf '%s\n' "$1" | awk 'function pid(s, p){p="?";sub(/^.*users:\(\(/,"",s);while(match(s,/pid=[0-9]+,fd=/)){p=substr(s,RSTART+4,RLENGTH-8);s=substr(s,RSTART+RLENGTH)}return p} {print pid($0)}'
}

collect_sockets() {
  begin_kind listen; LISTEN_PORTS=
  if ! command -v ss >/dev/null 2>&1; then unknown listen '' missing-tool:ss; end_kind; begin_kind connection; unknown connection '' missing-tool:ss; end_kind; return; fi
  for proto in tcp udp; do if [ "$proto" = tcp ]; then data=$(ss -H -ltnp 2>/dev/null); rc=$?; else data=$(ss -H -lunp 2>/dev/null); rc=$?; fi
    if [ "$rc" -ne 0 ]; then unknown listen '' failed; continue; fi
    while IFS= read -r row; do [ -n "$row" ] || continue; set -f; set -- $row; set +f; local_ep=${4:-}; split_endpoint "$local_ep"; pid=$(socket_pid "$row"); proc_fields "$pid"
      maybe_key pid "$pid"; pid_key=$MKEY; process_key=process; [ "$PROCESS_UNKNOWN" = yes ] && process_key=process!; exe_key=exe; [ "$EXE_UNKNOWN" = yes ] && exe_key=exe!
      record listen proto "$proto" addr "$EP_ADDR" port "$EP_PORT" "$pid_key" "$pid" "$process_key" "$process" "$exe_key" "$exe" deleted "$deleted"; [ "$proto" != tcp ] || append LISTEN_PORTS "$EP_PORT"
    done <<EOF
$data
EOF
  done
  end_kind
  begin_kind connection
  data=$(ss -H -tnp state established 2>/dev/null); rc=$?
  if [ "$rc" -ne 0 ]; then unknown connection '' failed; end_kind; return; fi
  rows=$(printf '%s\n' "$data" | awk 'NF{if($1~/^[0-9]+$/){l=$3;r=$4}else{l=$4;r=$5}p="?";s=$0;sub(/^.*users:\(\(/,"",s);while(match(s,/pid=[0-9]+,fd=/)){p=substr(s,RSTART+4,RLENGTH-8);s=substr(s,RSTART+RLENGTH)};k=r SUBSEP p;c[k]++;if(!(k in local)||l<local[k])local[k]=l}END{for(k in c){split(k,a,SUBSEP);print local[k] "\t" a[1] "\t" a[2] "\t" c[k]}}' | sort)
  while IFS=$TAB read -r lep rep pid count; do [ -n "$lep" ] || continue; split_endpoint "$lep"; laddr=$EP_ADDR; lport=$EP_PORT; split_endpoint "$rep"; raddr=$EP_ADDR; rport=$EP_PORT; listening=no
    while IFS= read -r p; do [ "$p" = "$lport" ] && listening=yes; done <<EOF
$LISTEN_PORTS
EOF
    proc_fields "$pid"; maybe_key pid "$pid"; pid_key=$MKEY; process_key=process; [ "$PROCESS_UNKNOWN" = yes ] && process_key=process!; exe_key=exe; [ "$EXE_UNKNOWN" = yes ] && exe_key=exe!
    record connection laddr "$laddr" lport "$lport" raddr "$raddr" rport "$rport" "$pid_key" "$pid" "$process_key" "$process" "$exe_key" "$exe" deleted "$deleted" listening "$listening" count "$count"
  done <<EOF
$rows
EOF
  end_kind
}

package_paths_safe() {
  command -v xargs >/dev/null 2>&1 || return 1
  if [ "$manager" = dpkg ]; then
    selections=$(dpkg --get-selections 2>/dev/null) || return 1
    packages=$(printf '%s\n' "$selections" | awk 'NF{print $1}')
    set --
    while IFS= read -r package; do [ -z "$package" ] || set -- "$@" "$package"; done <<EOF
$packages
EOF
    [ "$#" -gt 0 ] || return 0
    paths=$(dpkg --listfiles "$@" 2>/dev/null) || return 1
  else
    paths=$(rpm -qal 2>/dev/null) || return 1
  fi
  ids=$SECRET_IDS dirs=
  while IFS=: read -r secret_account secret_spec; do
    [ -n "$secret_spec" ] || continue
    saved_ifs=$IFS; IFS=$NL; set -- "$R"$secret_spec; IFS=$saved_ifs
    for secret_file do
      id=$(stat -L -c '%d:%i' -- "$secret_file" 2>/dev/null) || continue
      ids="$ids $id"
      [ -d "$secret_file" ] || continue
      dir=$(readlink -f -- "$secret_file" 2>/dev/null) || return 1
      devs="${devs:-} ${id%%:*}"; dirs=${dirs}${dirs:+$NL}${dir%/}
    done
  done <<EOF
$EXPANDED_SECRETS
EOF
  physical=$(printf '%s\n' "$paths" | awk -v r="$R" '/^\//{print r $0}')
  if [ -n "$dirs" ]; then
    sentinel=$(readlink -f -- "$R/" 2>/dev/null) || return 1
    { printf '%s/\n' "$R"; printf '%s\n' "$physical"; printf '%s/\n' "$R"; } | tr '\n' '\000' | xargs -0 readlink -f -- 2>/dev/null | DIRS=$dirs awk -v sentinel="$sentinel" -v r="$R" 'function inside(x, i){for(i=1;i<=n;i++)if(index(x,d[i] "/")==1)return 1;return 0} BEGIN{n=split(ENVIRON["DIRS"],d,"\n")} NR==1{first=$0;next} {if(have&&inside(prev))bad=1;prev=$0;have=1} END{exit bad||first!=sentinel||prev!=sentinel}' || return 1
  fi
  sentinel=$(stat -L -c '%d:%i %h %F' -- "$R/" 2>/dev/null) || return 1
  { printf '%s/\n' "$R"; printf '%s\n' "$physical"; printf '%s/\n' "$R"; } | tr '\n' '\000' | xargs -0 stat -L -c '%d:%i %h %F' -- 2>/dev/null | awk -v ids="$ids" -v devs="${devs:-}" -v sentinel="$sentinel" 'BEGIN{n=split(ids,a," ");for(i=1;i<=n;i++)s[a[i]]=1;n=split(devs,b," ");for(i=1;i<=n;i++)v[b[i]]=1} NR==1{first=$0} {last=$0} ($1 in s)&&$3!="directory"{bad=1} {split($1,p,":")} ($2>1&&$3=="regular"&&(p[1] in v)){listed[$1]++;links[$1]=$2} $3=="fifo"{fifo=1} END{for(k in listed)if(links[k]>listed[k])bad=1;if(bad||first!=sentinel||last!=sentinel)exit 1;if(fifo)exit 2}' || return
  kind_sentinel=$(stat -c %F -- "$R/" 2>/dev/null) || return 1
  { printf '%s/\n' "$R"; printf '%s\n' "$physical"; printf '%s/\n' "$R"; } | tr '\n' '\000' | xargs -0 stat -c %F -- 2>/dev/null | awk -v sentinel="$kind_sentinel" 'NR==1{first=$0} {last=$0} /^(fifo|socket|character special file|block special file)$/{special=1} END{if(first!=sentinel||last!=sentinel)exit 1;if(special)exit 2}'
}

collect_packages() {
  begin_kind pkg_modified
  if command -v dpkg >/dev/null 2>&1; then
    manager=dpkg
    if [ -n "$EXPANDED_SECRETS" ]; then
      while IFS=: read -r secret_account secret_spec; do
        saved_ifs=$IFS; IFS=$NL; set -- "$R"$secret_spec; IFS=$saved_ifs
        for physical do
          [ -e "$physical" ] || [ -L "$physical" ] || continue; [ ! -d "$physical" ] || continue; logical=${physical#"$R"}
          target=$(readlink -f -- "$physical" 2>/dev/null) || { unknown pkg_modified "$logical" secret-overlap; end_kind; return; }
          for query in "$logical" "${target#"$R"}"; do
            dpkg --search "$query" >/dev/null 2>&1; rc=$?
            [ "$rc" -eq 1 ] || { unknown pkg_modified "$logical" secret-overlap; end_kind; return; }
          done
        done
      done <<EOF
$EXPANDED_SECRETS
EOF
    fi
    devs=; package_paths_safe; rc=$?
    [ "$rc" -eq 0 ] || { reason=secret-overlap; [ "$rc" -ne 2 ] || reason=not-a-file; unknown pkg_modified '' "$reason"; end_kind; return; }
    data=$(dpkg --verify 2>/dev/null); rc=$?; [ "$rc" -le 1 ] || { unknown pkg_modified '' failed; end_kind; return; }
  elif command -v rpm >/dev/null 2>&1; then
    manager=rpm
    if [ -n "$EXPANDED_SECRETS" ]; then
      while IFS=: read -r secret_account secret_spec; do
        saved_ifs=$IFS; IFS=$NL; set -- "$R"$secret_spec; IFS=$saved_ifs
        for physical do
          [ -e "$physical" ] || [ -L "$physical" ] || continue; [ ! -d "$physical" ] || continue; logical=${physical#"$R"}
          target=$(readlink -f -- "$physical" 2>/dev/null) || { unknown pkg_modified "$logical" secret-overlap; end_kind; return; }
          for query in "$logical" "${target#"$R"}"; do
            rpm -qf "$query" >/dev/null 2>&1; rc=$?
            [ "$rc" -eq 1 ] || { unknown pkg_modified "$logical" secret-overlap; end_kind; return; }
          done
        done
      done <<EOF
$EXPANDED_SECRETS
EOF
    fi
    devs=; package_paths_safe; rc=$?
    [ "$rc" -eq 0 ] || { reason=secret-overlap; [ "$rc" -ne 2 ] || reason=not-a-file; unknown pkg_modified '' "$reason"; end_kind; return; }
    data=$(rpm -Va --nodeps --noscripts 2>/dev/null); rc=$?; [ "$rc" -le 1 ] || { unknown pkg_modified '' failed; end_kind; return; }
  else unknown pkg_modified '' no-package-manager; end_kind; return
  fi
  while IFS= read -r row; do
    case "$row" in missing*' ('*')') unknown pkg_modified "$(printf '%s\n' "$row" | awk '{sub(/^missing[ \t]+/,"");sub(/^[cdglr][ \t]+/,"");sub(/ \([^()]*\)$/,"");print}')" unreadable; continue;; esac
    parsed=$(printf '%s\n' "$row" | awk 'substr($0,1,9)~/^[.SM5DLUGTP?]+$/ {flags=substr($0,1,9);rest=substr($0,10);sub(/^[ \t]+/,"",rest);conf="no";if(rest~/^[cdglr][ \t]+/){if(substr(rest,1,1)=="c")conf="yes";sub(/^[cdglr][ \t]+/,"",rest)}if(rest~/^\//)print flags "\t" conf "\t" rest}')
    [ -n "$parsed" ] || continue
    IFS=$TAB read -r flags conf path <<EOF
$parsed
EOF
    times=$(stat -c '%Y:%Z' -- "$R$path" 2>/dev/null) || times='?:?'
    maybe_key mtime "${times%:*}"; mtime_key=$MKEY; maybe_key ctime "${times#*:}"
    record pkg_modified manager "$manager" path "$path" flags "$flags" conf "$conf" "$mtime_key" "${times%:*}" "$MKEY" "${times#*:}"
  done <<EOF
$data
EOF
  end_kind
}

collect_webroots() {
  [ -n "$WEBROOTS" ] || { not_requested webroot_file; return; }
  begin_kind webroot_file; PACKAGE_KNOWN=no WEB_SEEN=$NL
  while IFS= read -r root; do
    [ -d "$R$root" ] || { unknown webroot_file "$root" not-a-directory; continue; }
    WEB_ROOT_REAL=$(readlink -f -- "$R$root" 2>/dev/null) || { unknown webroot_file "$root" unreadable; continue; }
    web_walk "$root" "$R$root"
  done <<EOF
$WEBROOTS
EOF
  end_kind
}

web_walk() {
  web_root=$1; web_dir=$2
  if secret_overlap "${web_dir#"$R"}"; then unknown webroot_file "${web_dir#"$R"}" secret-overlap; return; fi
  if dir_unsearchable "$web_dir"; then unknown webroot_file "${web_dir#"$R"}" unsearchable; return; fi
  web_real=$(readlink -f -- "$web_dir" 2>/dev/null) || { unknown webroot_file "${web_dir#"$R"}" unreadable; return; }
  case "$web_real/" in "$WEB_ROOT_REAL"/*) :;; *) unknown webroot_file "${web_dir#"$R"}" outside-webroot; return;; esac
  case "$WEB_SEEN" in *"$NL$web_real$NL"*) return;; esac
  WEB_SEEN="$WEB_SEEN$web_real$NL"
  for file in "$web_dir"/* "$web_dir"/.[!.]* "$web_dir"/..?*; do
    [ -e "$file" ] || [ -L "$file" ] || continue
    if [ -d "$file" ]; then web_walk "$web_root" "$file"; continue; fi
    base=${file##*/}
    case "$base" in .htaccess|.user.ini|*.php|*.php[34578]|*.phtml|*.phar|*.pht|*.jsp|*.jspx|*.jspf|*.asp|*.aspx|*.ashx|*.cfm|*.cgi|*.pl|*.py|*.rb|*.sh|*.war) :;; *) continue;; esac
    change_times "$file" || { [ -L "$file" ] && [ -n "$CT" ]; } || { unknown webroot_file "${file#"$R"}" unreadable; continue; }
    mtime=${CT%:*}; ctime=${CT#*:}
    if [ "$mtime" -ge "$SINCE_EPOCH" ] 2>/dev/null || [ "$ctime" -ge "$SINCE_EPOCH" ] 2>/dev/null; then file_record webroot_file "${file#"$R"}" '' "$web_root"; fi
  done
}

collect_logins() {
  begin_kind login
  if ! command -v last >/dev/null 2>&1; then unknown login '' missing-tool:last-iso; end_kind; begin_kind wtmp; unknown wtmp '' missing-tool:last-iso; end_kind; return; fi
  wtmp=/var/log/wtmp; last_bin=$(command -v last); case "$(readlink -f -- "$last_bin" 2>/dev/null)" in */wtmpdb) wtmp=/var/log/wtmp.db;; esac
  reason=
  if secret_overlap "$wtmp"; then reason=secret-overlap
  elif [ ! -e "$R$wtmp" ]; then reason=absent
  elif [ ! -f "$R$wtmp" ]; then reason=not-a-file
  elif [ "$wtmp" = /var/log/wtmp.db ]; then data=$(last -i -w --time-format iso -s "$SINCE" 2>/dev/null) || reason=missing-tool:last-iso
  else
    data=$(read_file "$R$wtmp" last -f /dev/stdin -i -w --time-format iso -s "$SINCE" 2>/dev/null); rc=$?
    if [ "$rc" -eq 125 ]; then reason=changed-during-read
    elif [ "$rc" -ne 0 ] || ! printf '%s\n' "$data" | awk '$2=="begins"{f=1} END{exit !f}'; then reason=missing-tool:last-iso
    fi
  fi
  if [ -n "$reason" ]; then unknown login "$wtmp" "$reason"; end_kind; begin_kind wtmp; unknown wtmp "$wtmp" "$reason"; end_kind; return; fi
  login_rows=$(printf '%s\n' "$data" | awk '$1!=""&&$1!="reboot"&&$2!="begins"{f=$3;s=$4;k=5;if(f~/^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T/){s=f;f="";k=4}if(f=="0.0.0.0"||f=="::")f="";sub(/\+00:00$/,"Z",s);e="?";for(i=k;i<=NF;i++)if($i~/^[0-9][0-9][0-9][0-9]-/){e=$i;sub(/\+00:00$/,"Z",e);break}print $1 "\t" $2 "\t" s "\t" e "\t" f}')
  while IFS=$TAB read -r user tty start end from; do if [ -n "$user" ]; then maybe_key end "$end"; record login user "$user" tty "$tty" from "$from" start "$start" "$MKEY" "$end"; fi; done <<EOF
$login_rows
EOF
  end_kind
  begin_kind wtmp
  begins=$(printf '%s\n' "$data" | awk '$2=="begins"{$1=$2="";sub(/^  */,"");sub(/\+00:00$/,"Z");print;exit}')
  if [ -n "$begins" ]; then record wtmp path "$wtmp" begins "$begins"; else unknown wtmp "$wtmp" missing-tool:last-iso; fi
  end_kind
}

package_of() {
  PKG=?
  if command -v dpkg >/dev/null 2>&1; then
    owners=$(dpkg --search "$1" 2>/dev/null); rc=$?
    if [ "$rc" -eq 1 ]; then PKG=-; elif [ "$rc" -eq 0 ]; then PKG=$(printf '%s\n' "$owners" | awk '/^(local )?diversion /{next} {sub(/: \/.*$/,""); print; exit}'); [ -n "$PKG" ] || PKG=-; fi
  elif command -v rpm >/dev/null 2>&1; then
    owners=$(rpm -qf --queryformat '%{NAME}\n' -- "$1" 2>/dev/null); rc=$?
    if [ "$rc" -eq 0 ]; then PKG=${owners%%"$NL"*}; elif printf '%s\n' "$owners" | grep -q ' is not owned by any package$'; then PKG=-; fi
  fi
}

verify_of() {
  VERIFY=?
  case "$2" in -) VERIFY=none; return;; '?') return;; esac
  [ "$PATHS_SAFE" = yes ] || return
  if [ "$manager" = dpkg ]; then checked=$(dpkg --verify "${2%%,*}" 2>/dev/null); else checked=$(rpm -V --nodeps --noscripts "${2%%,*}" 2>/dev/null); fi
  [ "$?" -le 1 ] || return
  VERIFY=$(printf '%s\n' "$checked" | awk -v p="$1" '{f=$1; r=$0; sub(/^[^ \t]+[ \t]+/,"",r); sub(/^[cdglr][ \t]+/,"",r); sub(/ \([^()]*\)$/,"",r); if(r==p){print f; found=1; exit}} END{if(!found)print "ok"}')
}

program_info() {
  P_SHA=? P_PKG=? P_MTIME=? P_CTIME=?
  case "$1" in /*) :;; *) return;; esac
  secret_overlap "$1" && return
  pmeta=$(stat -L -c '%Y:%Z:%s:%d:%i' -- "$R$1" 2>/dev/null) || return
  IFS=: read -r P_MTIME P_CTIME psize pdev pino <<EOF
$pmeta
EOF
  if [ "$psize" -le "$MAX_HASH" ] 2>/dev/null; then RF_EXPECT=$pdev:$pino; psum=$(read_file "$R$1" sha256sum 2>/dev/null) && P_SHA=${psum%% *}; RF_EXPECT=; fi
  package_of "$1"; P_PKG=$PKG
}

exec_record() {
  program_info "$4"
  maybe_key sha256 "$P_SHA"; k_sha=$MKEY; maybe_key package "$P_PKG"; k_pkg=$MKEY; maybe_key mtime "$P_MTIME"; k_mtime=$MKEY; maybe_key ctime "$P_CTIME"
  record exec source "$1" line "$2" key "$3" program "$4" "$k_sha" "$P_SHA" "$k_pkg" "$P_PKG" "$k_mtime" "$P_MTIME" "$MKEY" "$P_CTIME"
}

inspect_programs() {
  case "$1" in
    *.service|*.socket|*.timer|*.path|*.mount|*.conf) program_awk='function out(k,from, i,t){for(i=from;i<=NF;i++){t=$i;gsub(/^["\047(]+|["\047);&|]+$/,"",t);if(i==from||t~/^\//)print NR "\t" k "\t" (i==from) "\t" t}} {sub(/^[ \t]+/,"")} /^Exec[A-Za-z]*=/{k=$0; sub(/=.*/,"",k); sub(/^[^=]*=[ \t]*/,""); sub(/^[-@:+!|]+/,""); if(NF)out(k,1)}';;
    /etc/crontab|/etc/cron.d/*) program_awk='function out(k,from, i,t){for(i=from;i<=NF;i++){t=$i;gsub(/^["\047(]+|["\047);&|]+$/,"",t);if(i==from||t~/^\//)print NR "\t" k "\t" (i==from) "\t" t}} /^[ \t]*(#|$)/{next} /^[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]*=/{next} {out("cron",($1~/^@/)?3:7)}';;
    /var/spool/cron/*) program_awk='function out(k,from, i,t){for(i=from;i<=NF;i++){t=$i;gsub(/^["\047(]+|["\047);&|]+$/,"",t);if(i==from||t~/^\//)print NR "\t" k "\t" (i==from) "\t" t}} /^[ \t]*(#|$)/{next} /^[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]*=/{next} {out("cron",($1~/^@/)?2:6)}';;
    /etc/anacrontab) program_awk='function out(k,from, i,t){for(i=from;i<=NF;i++){t=$i;gsub(/^["\047(]+|["\047);&|]+$/,"",t);if(i==from||t~/^\//)print NR "\t" k "\t" (i==from) "\t" t}} /^[ \t]*(#|$)/{next} /^[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]*=/{next} {out("cron",4)}';;
    *) return;;
  esac
  rows=$(read_file "$R$1" awk "$program_awk") || { unknown inspect "$1" changed-during-read; return; }
  while IFS=$TAB read -r line key first program; do
    [ -n "$line" ] || continue
    [ "$first" = 1 ] || { [ -f "$R$program" ] && [ -x "$R$program" ]; } || continue
    exec_record "$1" "$line" "$key" "$program"
  done <<EOF
$rows
EOF
}

inspect_journal() {
  command -v journalctl >/dev/null 2>&1 || { unknown inspect "$1" missing-tool:journalctl; return; }
  from=$(($2 - 300)) to=$(($2 + 300))
  entries=$(journalctl -q --since "@$from" --until "@$to" -o json --output-fields=_COMM,_SYSTEMD_UNIT 2>/dev/null) || { unknown inspect "$1" failed; return; }
  rows=$(printf '%s\n' "$entries" | awk 'function f(k){if(match($0,"\"" k "\":\"[^\"]*\""))return substr($0,RSTART+length(k)+4,RLENGTH-length(k)-5);return "-"} NF{c[f("_COMM") "\t" f("_SYSTEMD_UNIT")]++} END{for(k in c)print c[k] "\t" k}' | sort -rn | awk 'NR<=20')
  while IFS=$TAB read -r count comm unit; do
    [ -n "$count" ] && record journal path "$1" start "$from" end "$to" comm "$comm" unit "$unit" count "$count"
  done <<EOF
$rows
EOF
}

inspect_keys() {
  command -v ssh-keygen >/dev/null 2>&1 || { unknown inspect "$1" missing-tool:ssh-keygen; return; }
  command -v journalctl >/dev/null 2>&1 || { unknown inspect "$1" missing-tool:journalctl; return; }
  fps=$(read_file "$R$1" ssh-keygen -lf - 2>/dev/null | awk '$2~/^SHA256:/{print $2}') || { unknown inspect "$1" unparsed; return; }
  logins=$(journalctl -q _COMM=sshd --since "@$SINCE_EPOCH" -o short-unix 2>/dev/null) || { unknown inspect "$1" failed; return; }
  for fp in $fps; do
    rows=$(printf '%s\n' "$logins" | awk -v fp="$fp" 'index($0," " fp)&&/Accepted publickey for /{u=$0; sub(/.*Accepted publickey for /,"",u); split(u,a," "); print int($1) "\t" a[1] "\t" a[3]}' | sort -u)
    while IFS=$TAB read -r when user from; do
      [ -n "$when" ] && record key_login path "$1" fp "$fp" start "$when" user "$user" from "$from"
    done <<EOF
$rows
EOF
  done
}

inspect_file() {
  logical=$1 file=$R$1
  if secret_overlap "$logical"; then unknown inspect "$logical" secret-overlap; return; fi
  [ -e "$file" ] || [ -L "$file" ] || { unknown inspect "$logical" absent; return; }
  [ -f "$file" ] || { unknown inspect "$logical" not-a-file; return; }
  fmeta=$(stat -L -c '%U:%G:%a:%h:%s:%X:%Y:%Z:%d:%i' -- "$file" 2>/dev/null) || { unknown inspect "$logical" unreadable; return; }
  IFS=: read -r owner group mode links size atime mtime ctime fdev fino <<EOF
$fmeta
EOF
  sha=?
  if [ "$size" -le "$MAX_HASH" ] 2>/dev/null; then
    RF_EXPECT=$fdev:$fino; fsum=$(read_file "$file" sha256sum 2>/dev/null); rc=$?; RF_EXPECT=
    [ "$rc" -ne 125 ] || { unknown inspect "$logical" changed-during-read; return; }
    [ "$rc" -ne 0 ] || sha=${fsum%% *}
  fi
  package_of "$logical"; verify_of "$logical" "$PKG"
  maybe_key sha256 "$sha"; k_sha=$MKEY; maybe_key package "$PKG"; k_pkg=$MKEY; maybe_key verify "$VERIFY"
  record file path "$logical" owner "$owner" group "$group" mode "$mode" links "$links" size "$size" atime "$atime" mtime "$mtime" ctime "$ctime" "$k_sha" "$sha" "$k_pkg" "$PKG" "$MKEY" "$VERIFY"
  inspect_programs "$logical"
  case "$logical" in */authorized_keys|*/authorized_keys2) inspect_keys "$logical";; esac
  inspect_journal "$logical" "$ctime"
}

inspect_process() {
  pid=$1 proc=$R/proc/$1
  [ -d "$proc" ] || { unknown inspect "/proc/$pid" exited; return; }
  comm=?; IFS= read -r comm 2>/dev/null < "$proc/comm" || comm=?
  exe=$(readlink -- "$proc/exe" 2>/dev/null) || exe=?
  deleted=no; case "$exe" in *' (deleted)') exe=${exe%' (deleted)'}; deleted=yes;; esac
  sha=?; xsum=$(read_file "$proc/exe" sha256sum 2>/dev/null) && sha=${xsum%% *}
  PKG=?; [ "$exe" = '?' ] || [ "$deleted" = yes ] || package_of "$exe"
  start=$(stat -c %Y -- "$proc" 2>/dev/null) || start=?
  chain= parent=$pid hops=0
  while [ "$hops" -lt 16 ]; do
    parent=$(awk '{sub(/^.*\) /,""); print $2}' "$R/proc/$parent/stat" 2>/dev/null)
    case "$parent" in ''|0|*[!0-9]*) break;; esac
    name=?; IFS= read -r name 2>/dev/null < "$R/proc/$parent/comm" || name=?
    chain=${chain}${chain:+,}$parent:$name; hops=$((hops + 1))
    [ "$parent" != 1 ] || break
  done
  maybe_key comm "$comm"; k_comm=$MKEY; maybe_key exe "$exe"; k_exe=$MKEY; maybe_key sha256 "$sha"; k_sha=$MKEY; maybe_key package "$PKG"; k_pkg=$MKEY; maybe_key start "$start"
  record process pid "$pid" "$k_comm" "$comm" "$k_exe" "$exe" deleted "$deleted" "$k_sha" "$sha" "$k_pkg" "$PKG" "$MKEY" "$start" chain "$chain"
}

inspect_all() {
  begin_kind inspect; PATHS_SAFE=no manager=
  if command -v dpkg >/dev/null 2>&1; then manager=dpkg; elif command -v rpm >/dev/null 2>&1; then manager=rpm; fi
  if [ -n "$manager" ]; then devs=; package_paths_safe && PATHS_SAFE=yes; fi
  while IFS= read -r target; do
    case "$target" in
      /proc/*) target=${target#/proc/}; case "$target" in ''|*[!0-9]*) unknown inspect "/proc/$target" malformed;; *) inspect_process "$target";; esac;;
      *) inspect_file "$target";;
    esac
  done <<EOF
$INSPECTS
EOF
  end_kind
}

finish() {
  od -An -v -tx1 | awk -v limit="$LIMIT" "$LIB"'
    function number(h,  d){d="0123456789abcdef";return (index(d,substr(h,1,1))-1)*16+index(d,substr(h,2,1))-1}
    function safe(n){return (n>=48&&n<=57)||(n>=65&&n<=90)||(n>=97&&n<=122)||n==46||n==95||n==126||n==47||n==58||n==64||n==43||n==44||n==45}
    function token_done(  i){
      if(parts==0){parts=rawtoken+0;seen=0}
      else{part[++seen]=rawtoken;encoded[seen]=enctoken;if(seen==parts){flush();delete part;delete encoded;parts=0}}
      rawtoken="";enctoken=""
    }
    function flush(  kind,line,i,key,value,capped) {
      kind=part[1]
      if(kind=="__done"){done=1;return}
      line=kind
      for(i=2;i<=parts;i+=2){key=part[i];value=part[i+1];sub(/!$/, "", key);shown=(part[i]~/!$/?"?":(part[i]~/^(mtime|ctime|atime|now|start|end|begins)$/&&value~/^[0-9]+$/?val(part[i],value):encoded[i+1]));line=line " " key "=" shown;raw[key]=value}
      if(kind=="end"&&raw["status"]=="refused"){print line;refused=1;return}
      if(kind=="check"){fflush();if(sort_open&&close(sortcmd)!=0)sort_failed=1;sort_open=0;checks[raw["kind"]]++;print line;fflush();records++;delete raw;return}
      if(kind=="unknown")unknowns++
      capped=(kind=="connection"||kind=="pkg_modified"||kind=="webroot_file"||kind=="login")
      if(capped){total[kind]++;if(total[kind]>limit){delete raw;return}}
      if(kind in need){fflush();print line | sortcmd;sort_open=1;records++;delete raw;return}
      print line;records++;delete raw
    }
    BEGIN { init(); sortcmd="sort"; records=0; unknowns=0; split("secret account sudoers authkey cron systemd_unit rc_local listen connection pkg_modified webroot_file login wtmp",a," "); for(i in a)need[a[i]]=1 }
    { for(j=1;j<=NF;j++){h=tolower($j);if(h=="00")token_done();else{n=number(h);rawtoken=rawtoken sprintf("%c",n);enctoken=enctoken (safe(n)?sprintf("%c",n):"%" toupper(h))}} }
    END { if(sort_open&&close(sortcmd)!=0)sort_failed=1;if(refused)exit; split("connection pkg_modified webroot_file login",order," "); for(i=1;i<=4;i++){k=order[i];if(total[k]>limit){print "cap kind=" k " total=" total[k] " shown=" limit;records++}} ok=done&&!sort_failed; if("inspect" in checks){if(checks["inspect"]!=1||checks["secret"]!=1)ok=0}else for(k in need)if(checks[k]!=1)ok=0; print "end status=" (ok?"complete":"incomplete") " records=" records " unknowns=" unknowns }
  '
}

main() {
  ACCTS= SECRET_SNAPSHOTS= SECRET_IDS= SECRET_DIRS=
  expand_secrets
  snapshot_secrets
  load_accounts
  expand_secrets
  all_secrets=$EXPANDED_SECRETS
  EXPANDED_SECRETS=
  while IFS= read -r entry; do
    case "$entry" in :*) :;; *) append EXPANDED_SECRETS "$entry";; esac
  done <<EOF
$all_secrets
EOF
  snapshot_secrets
  EXPANDED_SECRETS=$all_secrets
  collect_secrets
  self_sum=
  case "$0" in /proc/self/fd/*) self_sum=$(sha256sum < "$0" 2>/dev/null);; *) if ! secret_overlap "$0"; then self_sum=$(read_file "$0" sha256sum 2>/dev/null); fi;; esac; self_hash=${self_sum%% *}; [ -n "$self_hash" ] || self_hash=?
  maybe_key sha256 "$self_hash"; emit run v 1 uid "$(id -u)" now "$(date -u +%s)" since "$SINCE" "$MKEY" "$self_hash"
  if [ -n "$INSPECTS" ]; then inspect_all; emit __done; return; fi
  collect_accounts
  collect_sudoers
  collect_authkeys
  collect_persistence cron
  collect_persistence systemd
  collect_persistence rc_local
  collect_sockets
  collect_packages
  collect_webroots
  collect_logins
  emit __done
}

parse_args "$@"
main | finish
exit 0
```

The collector requires Linux `/dev/fd` and `/proc/self/fd`, POSIX `sh`, `awk`, `grep`, `od`, `stat`, `sha256sum`, `readlink`, `sort`, `tr`, `wc`, `xargs`, `id`, and `date`, with GNU `stat` formatting. It treats `getent`, `ss`, `ssh-keygen`, `dpkg`, `rpm`, and `last` as optional and reports coverage it cannot obtain. Persistence records include `packaged=yes|no|?` from one batched ownership lookup per collector. A missing package manager or an ownership-query error yields `?`.

Absolute secrets are stat’ed before account files or any other file is read. Home-relative secrets are stat’ed immediately after reading only passwd and login.defs. Secret overlap checks logical paths, targets resolved with `readlink -f`, and device and inode numbers, so a hard link is also an overlap, before opening, hashing, or grepping; an unresolved candidate is skipped conservatively. Account records include every passwd entry, classify numeric UID zero as `root`, and classify non-login system accounts as `system-nologin`. An empty passwd password field overrides shadow with `password=none`. When passwd is not read, the `secret` check for `~/` paths and the `authkey` and `systemd_unit` checks emit `unknown` for `/etc/passwd`. An `authorized_keys` line that is neither blank, a comment, nor parsed as a key emits `reason=unparsed`. A symlink is recorded even when its target is gone, so a dangling link is a record rather than `unreadable`; a regular-file target is hashed and searched through the link, and the record reports the later of the link's and the target's times. Runtime `.scope` and `.slice` units and their drop-in directories are skipped. When `/lib` is a symlink, the `/lib` unit directories are not walked a second time, and package ownership accepts either the `/lib` or the `/usr/lib` spelling. A secret pattern that passes through a directory the collector cannot search or list is `unknown` with `reason=unsearchable`, even when other matches exist. A read-only mount reports `atime_mode=readonly`, and the last mount on a mount point decides the mode. `pkg_modified` records carry the file's `mtime` and `ctime`. The alias check stats every package path in one batched `xargs` call and compares device and inode numbers with the secrets', including those recorded when the secrets were first stat’ed; the batch is bracketed by the root directory, so a `stat` that never ran skips verification. When a secret is a directory, a package path that resolves inside it skips verification too, while a package that owns the directory itself does not, since a verifier hashes no directory, and so does a regular package file on its filesystem with more hard links than the inventory lists for that inode, since the unlisted link may sit inside the secret. The verifier then opens package paths itself, so a path swapped between this check and the verifier is outside what the collector can guard.

Socket records use the last `pid=N,fd=` occurrence in the `users:((...))` field and normalize IPv4-mapped addresses before encoding. Systemd discovery also includes `/run/systemd/transient`, both `system.control` directories, and every account’s `~/.local/share/systemd/user`. A secret whose nearest existing parent directory is unsearchable is `unknown` with `reason=unsearchable`. A failed pattern search prints `hits=?` and an `unknown` record for the file. A symlinked sudoers or `authorized_keys` file reports the later of the link’s and the target’s times. Only TCP listeners set `listening=yes` on a TCP connection. Sshd keywords written as `Keyword=value` are read like `Keyword value`, and `dpkg` diversion lines never count as package ownership. Every file, `wtmp` included, is read through a descriptor opened once and checked first: it must be a regular file, keep the inode it had when its metadata was read, resolve through `/proc/self/fd` to a path outside every secret, and match no secret's device and inode, then or at the first stat, nor be a hard-linked file while a secret is a directory. A directory secret whose ctime changed since its first stat refuses every read for the rest of the run, and the cron, systemd and web-root walks never list a directory inside a secret. A FIFO swapped in between the regular-file check and the open blocks that open; the run then ends without an `end` record. A refused or changed file is dropped as `reason=changed-during-read`, and a sudoers, sshd, `authorized_keys`, `/etc/shadow` or `wtmp` path that is not a regular file is `reason=not-a-file`. A missing `wtmp` is `reason=absent`. When `last` is wtmpdb, it reads `/var/log/wtmp.db` itself after the same path checks; util-linux `last` reads the checked descriptor, and its output counts only with a `begins` line. An sshd `Include` outside `/etc/ssh/sshd_config.d` is `reason=include-outside-default`. Sudoers files that sudo skips, those with a dot or a trailing `~`, are not read. An RPM `missing` line with an error is `unknown` with `reason=unreadable`. A login without a remote address has an empty `from`. Cron coverage includes `/etc/cron.yearly`; systemd coverage includes `/run/systemd/user` and the system and user generator directories. Package verification preserves spaced paths, accepts RPM attribute markers `c`, `d`, `g`, `l`, `r`, and ignores non-file diagnostics. Unknown digest evidence means position 3 for dpkg or position 3 (the `5` test) for RPM, rather than any `?` elsewhere.

RPM verification passes [`--nodeps --noscripts`](https://rpm.org/docs/latest/man/rpm.8) so package verification scriptlets do not execute on the host.
