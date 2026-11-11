# Drop-in script

The script that `execute_file` runs writes one file and changes nothing else. It must:

- Write a dedicated drop-in (`99-<cve-id>-mitigation.ini`) and never edit an existing configuration file, so a re-run gives the same result and removal is deleting one file.
- Run the config test after writing, then read the value in effect back, and on either failure put the previous state back and exit non-zero, saying so when the put-back itself fails. A drop-in that fails its test would break the next restart, and a syntax test alone passes when a file loaded later (`zz-custom.ini`) overrides the setting.
- Take the settings and values from the vendor advisory only. The template below holds `REPLACE` placeholders and refuses to run until every one is filled in; the setting shown is never a real mitigation.
- Merge a deny list (`disable_functions`) with the value read in step 2 instead of replacing it: the drop-in loads later and wins, so a replacement silently re-enables whatever the old list blocked. An allow list (`open_basedir`) goes the other way: a union with the old value keeps every path the advisory wants closed, so set the advised value itself. Show the person the merged list, or what the advised allow list removes.
- Restart nothing and print the services that need one.
- Hold each substituted value as data, checked against the rules in the skill's inputs: a `'` in a single-quoted variable ends the quote, and a line equal to `MITIGATION_EOF` in the `want` block ends the heredoc early, so either runs what follows.
- Carry no password or token, since `execute_file` refuses inline credentials.

The config test must load the drop-in. A test that never reads the file passes on a broken drop-in and proves nothing; ask the person which command loads it when you are unsure.

## PHP-FPM on Debian and Ubuntu

```bash
#!/bin/bash
set -eu
cve='REPLACE-CVE-ID'
dropin='/etc/php/8.1/fpm/conf.d/99-REPLACE-CVE-ID-mitigation.ini'
restart='php8.1-fpm'
fpm='php-fpm8.1'
pooldirs='/etc/php/8.1/fpm/pool.d'
settings='REPLACE_SETTING'
expect='REPLACE_SETTING'
baseline='REPLACE_BASELINE'
want=$(cat <<'MITIGATION_EOF'
; Mitigation for REPLACE-CVE-ID. Delete this file once PHP is patched.
REPLACE_SETTING = REPLACE_VALUE
MITIGATION_EOF
)
case "$cve$dropin$settings$expect$baseline$want" in
  *REPLACE*) echo "fill in every REPLACE value from the vendor advisory first" >&2; exit 1 ;;
esac
backup="$dropin.prev"
if [ -e "$backup" ] || [ -L "$backup" ]; then echo "$backup exists from an earlier run; inspect and remove it first" >&2; exit 1; fi
if [ -L "$dropin" ]; then echo "$dropin is a symlink; not writing through it" >&2; exit 1; fi
if [ -e "$dropin" ] && [ ! -f "$dropin" ]; then echo "$dropin is not a regular file; not touching it" >&2; exit 1; fi
if [ -e "$dropin" ] && [ -n "$(find "$dropin" -links +1 -print)" ]; then
  echo "$dropin is hard-linked elsewhere; not writing through it" >&2
  exit 1
fi
has_lines() {
  local line
  while IFS= read -r line; do
    printf '%s\n' "$1" | grep -Fxq -- "$line" || return 1
  done <<<"$2"
}
check() {
  local info
  "$fpm" -t && info=$("$fpm" -i) && has_lines "$info" "$expect"
}
pools_clear() {
  local dir name file files rc
  while IFS= read -r dir; do
    files=$(find -L "$dir" -type f) || return 1
    while IFS= read -r name; do
      while IFS= read -r file; do
        [ -n "$file" ] || continue
        rc=0
        grep -Eq -- "^[[:space:]]*php(_admin)?_(value|flag)[[:space:]]*\[[[:space:]]*[\"']?${name//./\\.}[\"']?[[:space:]]*\]" "$file" || rc=$?
        [ "$rc" -eq 1 ] || return 1
      done <<<"$files"
    done <<<"$settings"
  done <<<"$pooldirs"
}
pools_clear || {
  echo "a pool sets one of the settings, or a directory in pooldirs could not be read; nothing written" >&2
  exit 1
}
if [ -f "$dropin" ] && [ "$(cat -- "$dropin")" = "$want" ]; then
  check
  echo "mitigation=unchanged"
else
  info=$("$fpm" -i) && has_lines "$info" "$baseline" || {
    echo "the value on disk changed since it was reviewed; nothing written" >&2
    exit 1
  }
  if [ -e "$dropin" ]; then cp -p -- "$dropin" "$backup"; fi
  if printf '%s\n' "$want" > "$dropin" && chmod 644 "$dropin" && check && rm -f -- "$backup"; then
    echo "mitigation=applied"
  else
    if { if [ -e "$backup" ]; then mv -- "$backup" "$dropin"; else rm -f -- "$dropin"; fi; }; then
      echo "config test or read-back failed; drop-in rolled back" >&2
    else
      echo "config test or read-back failed and the rollback failed; fix $dropin (backup: $backup) by hand" >&2
    fi
    exit 1
  fi
fi
echo "dropin=$dropin"
echo "restart_required=$restart"
echo "vulnerable=still-present"
```

- The write, the `chmod`, the test, and the backup removal share one condition, so a failure in any of them, a full disk included, rolls the drop-in back instead of leaving a `.prev` that blocks every rerun.
- The backup ends in `.prev`, not `.ini`, so PHP never loads it.
- The unchanged branch still runs the test, so a rerun reports a drop-in that has since stopped passing.
- `expect` holds one whole line per setting, as the read command prints it once the setting is in effect (for example `memory_limit => -1 => -1`). Every line must appear exactly, and the check fails when the read command itself fails.
- On every run, rerun included, the script searches every directory in `pooldirs` (one per line) for an uncommented pool-level `php_admin_value` or `php_admin_flag` of any name in `settings` (one name per line). A hit or a read error stops the run (the search follows symlinked pool files), because `php-fpm8.1 -i` never shows pool overrides and one would make the drop-in useless for that pool. List every directory the FPM configuration includes (`grep -rnE '^[[:space:]]*include' /etc/php/8.1/fpm/php-fpm.conf /etc/php/8.1/fpm/pool.d`, which also finds an include inside a pool file; run it again on every directory it names until no new one appears): one outside the list is not searched. The search reads every file in a listed directory, a `.disabled` or `.dpkg-dist` copy included, so a stale copy there stops the run: that is the safe side, and a person removes the copy.
- `baseline` holds the lines the read command printed for these settings when the person reviewed them. The script refuses to write when the value on disk no longer matches, so a list merged earlier never overwrites a newer one; read again, merge again, and get a new review.
- A `.prev` left by an earlier run is refused rather than reused as this run's rollback copy.
- A drop-in path that is not a regular file (a directory, a FIFO, a device) is refused before anything is copied or read.
- A drop-in path that is a symlink, or a file with more than one hard link, is refused: writing through it would change another file, and the rollback could not restore it. The read-back checks the files on disk, as `php-fpm8.1 -i` does, not the running workers.
- An existing drop-in with different content is replaced whole, and the backup is deleted on success. The file is this skill's own, named for the CVE; step 2 shows its current content so the person sees what the new script drops.
- For another PHP version, edit the variables (`fpm` is the binary the test and the read-back run) and the `want` block; keep the structure. The template covers PHP-FPM only: its config test, read-back, and pool search do not carry over to another service (sshd, sysctl, modprobe), so never adapt it to one.
- Running as an ordinary account, the account must still be able to write the drop-in directory; do not add `sudo` to individual lines. If it cannot, use `root` as the session account instead.

## Reading the value in effect

Ask the process that serves traffic, never the CLI:

- PHP-FPM: `php-fpm8.1 -i | grep -i '^disable_functions'`
- PHP-FPM pool files can override an ini value per pool (`php_admin_value[<setting>]`, `php_admin_flag[<setting>]`), and `php-fpm8.1 -i` never shows them. Also run `grep -RnE 'php(_admin)?_(value|flag)[[:space:]]*\[[[:space:]]*["'"'"']?<setting>["'"'"']?[[:space:]]*\]' /etc/php/8.1/fpm/pool.d`. A hit means the drop-in cannot take effect for that pool: report `unknown` with the line, and ask.
- Apache with mod_php: the CLI cannot show it; read it from a request the person already serves, or ask.

A web server can also pass `PHP_ADMIN_VALUE` per request (nginx `fastcgi_param PHP_ADMIN_VALUE`, Apache `php_admin_value`), which neither check sees and a restart does not clear. Ask the person whether the web server sets the setting, and report `unknown` when it does.

`php-fpm8.1 -i` starts a new process that reads the files on disk. It does not show what the running workers loaded, so a server that shows the advised value may still need the restart: report it `already_set` (on disk) and list the service. An output that does not show the setting is `unknown`, not `already_set`.
