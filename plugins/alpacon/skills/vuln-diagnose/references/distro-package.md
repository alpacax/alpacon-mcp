# Distribution packages

The advisory names a source package (`openssh`) and a fixed version per release. Check the binary packages the server actually installs (`openssh-server`, `openssh-client`); every binary built from that source carries the same version once upgraded, but a server can hold them at different versions. When the advisory does not say which binary carries the vulnerable code, run the check once per binary, setting `p` in the commands below. A server's verdict is the worst of its checks: `affected` over `unknown` over `not_affected`.

Each check is one shell line and runs as an ordinary account; none of these commands needs root.

## Debian and Ubuntu

`dpkg --compare-versions` orders Debian versions (epochs, `~`, revisions) correctly on the host, so the host decides the verdict. Set `p` to the binary package and fill in one `case` arm per release from the distribution's tracker. A release the tracker lists as vulnerable with no fixed package yet gets `f=none` (`focal` below is such an arm), so an installed copy reports `reason=no-fix-available` instead of a version comparison:

```sh
. /etc/os-release; p=openssh-server; case "$VERSION_CODENAME" in jammy) f='1:8.9p1-3ubuntu0.10';; noble) f='1:9.6p1-3ubuntu13.5';; focal) f=none;; *) echo "verdict=unknown release=$VERSION_CODENAME reason=release-not-in-advisory"; exit 0;; esac; s=$(dpkg-query -W -f='${db:Status-Abbrev}|${Version}' "$p" 2>/dev/null); e=$?; case "$e:$s" in 0:?i*) v=${s#*|};; 0:?[nc]*|1:) echo "verdict=not_affected package=$p release=$VERSION_CODENAME installed=none"; exit 0;; *) echo "verdict=unknown package=$p release=$VERSION_CODENAME reason=dpkg-query-exit-$e status=${s%%|*}"; exit 0;; esac; [ "$f" != none ] || { echo "verdict=affected package=$p release=$VERSION_CODENAME installed=$v reason=no-fix-available"; exit 0; }; if dpkg --compare-versions "$v" lt "$f"; then r=affected; else r=not_affected; fi; echo "verdict=$r package=$p release=$VERSION_CODENAME installed=$v fixed=$f"
```

The second letter of the status is what is on disk: `i` is installed, whatever the first letter says, so a held package (`hi`) counts, and it is exactly the kind that missed an upgrade. `n` and `c`, or exit 1 with no output, mean not installed. Anything else, a half-installed package or a package database `dpkg-query` cannot read, is `unknown`.

## RHEL, Rocky, AlmaLinux, Fedora

The repositories' update metadata already maps a CVE to the advisory that fixes it, so the check asks `dnf` instead of comparing RPM versions by hand. Keep only the advisory lines for the package being checked:

```sh
. /etc/os-release; c='CVE-2099-0001'; p=openssh-server; rpm -q rpm >/dev/null 2>&1 || { echo "verdict=unknown package=$p release=$ID-$VERSION_ID reason=rpm-database-unreadable"; exit 0; }; o=$(LC_ALL=C rpm -q "$p" 2>/dev/null); e=$?; case "$e:$o" in 0:*) ;; *"is not installed"*) echo "verdict=not_affected package=$p release=$ID-$VERSION_ID installed=none"; exit 0;; *) echo "verdict=unknown package=$p release=$ID-$VERSION_ID reason=rpm-exit-$e"; exit 0;; esac; v=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE} ' "$p"); has(){ a=$(dnf -q updateinfo list "$1" --cve "$c" 2>/dev/null) || return 2; printf '%s\n' "$a" | awk -v p="$p-" 'index($3, p) == 1 && substr($3, length(p)+1, 1) ~ /[0-9]/ {found=1} END {exit !found}'; }; if has --available; then r=affected; else e=$?; if [ "$e" -ne 1 ]; then r=unknown; elif has --installed; then r=not_affected; else r=unknown; fi; fi; echo "verdict=$r package=$p release=$ID-$VERSION_ID installed=$v"
```

An unreadable RPM database answers "not installed" for every package, so the check first asks for `rpm` itself. `--available` lists a fixing advisory not yet installed; `--installed` lists one already installed. Do not pass the package name to `dnf updateinfo` itself: with a package argument it also lists that package's unrelated advisories. A failed query is `unknown`, even when the other query could name an installed advisory. Neither list naming the package means the repositories carry no update metadata for that CVE (CentOS Stream, a mirror without it, or a repository the server cannot reach), so the verdict is `unknown`, and the report says to compare `installed` with the advisory by hand.

## The kernel

What matters is the running kernel, not the newest one installed. A server running an old kernel with a fixed one installed is `affected` with `reason=reboot-pending`: it needs a reboot, not a patch, and `vuln-verify` reads that reason.

Ubuntu keeps the ABI name (`6.8.0-45-generic`) across some updates, so `uname -r` cannot tell two builds apart. Read the running build from `/proc/version_signature` (`Ubuntu 6.8.0-45.45-generic 6.8.12`) instead.

Ubuntu builds each kernel flavour (`generic`, `lowlatency`, `aws`, `azure`, `gcp`, `oracle`) from its own source package with its own version numbers: the fixed `aws` build `6.8.0-1015.16` is not comparable with the fixed `generic` build `6.8.0-45.45`. Each kernel series is tracked separately as well: a release ships its own series and, through hardware enablement (HWE), later ones (`6.8.0-45.45~22.04.1` on jammy; `6.11` and `6.14` on noble), and a fix in one series says nothing about another. So the check reads the running flavour and series (`6.8.0`), and takes the fixed version for that combination from the USN; a combination the USN does not list is `unknown`, never compared against another flavour's or series' version. Fill in one `case` arm per release, flavour, and series the USN lists, and `f=none` for one it lists as still vulnerable:

```sh
. /etc/os-release; r=$(awk '{print $2}' /proc/version_signature 2>/dev/null); b=$(printf '%s' "$r" | sed -n 's/^\([0-9.]*-[0-9.]*\(~[0-9.]*\)\{0,1\}\)-[a-z].*$/\1/p'); k=${r#"$b"-}; [ -n "$b" ] || { echo "verdict=unknown reason=no-version-signature"; exit 0; }; t=${b%%-*}; case "$VERSION_CODENAME:$k:$t" in noble:generic:6.8.0) f='6.8.0-45.45';; noble:aws:6.8.0) f='6.8.0-1015.16';; jammy:generic:6.8.0) f='6.8.0-45.45~22.04.1';; noble:generic:6.14.0) f=none;; *) echo "verdict=unknown running=$b flavour=$k series=$t reason=flavour-not-in-advisory"; exit 0;; esac; [ "$f" != none ] || { echo "verdict=affected running=$b flavour=$k series=$t reason=no-fix-available"; exit 0; }; if dpkg --compare-versions "$b" ge "$f"; then echo "verdict=not_affected running=$b flavour=$k fixed=$f"; exit 0; fi; for v in $(dpkg-query -W -f='${db:Status-Abbrev}|${Version}\n' "linux-image-$t-[0-9]*-$k" 2>/dev/null | sed -n 's/^.i.|//p'); do dpkg --compare-versions "$v" ge "$f" && { echo "verdict=affected running=$b flavour=$k fixed=$f reason=reboot-pending"; exit 0; }; done; echo "verdict=affected running=$b flavour=$k fixed=$f"
```

`reboot-pending` counts only an installed image of the running series and flavour (`linux-image-<series>-<abi>-<flavour>`), so a fixed `generic` image installed beside a running `aws` kernel does not make the `aws` server look fixed after a reboot.

- Debian: every flavour (`amd64`, `cloud-amd64`, `rt-amd64`) is built from the one `linux` source package, so one fixed version per release covers them. The running build is in `uname -v` (`... Debian 6.1.112-1 (2024-09-30)`); read it with `uname -v | sed -n 's/.* Debian \([^ ]*\) .*/\1/p'` and compare the same way.
- RHEL family: `uname -r` (`5.14.0-427.13.1.el9_4.x86_64`) names the build. Kernel release strings are numeric, so `printf '%s\n' "$running" "$fixed" | sort -V | head -1` gives the older one, and `rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core` lists the installed ones for the `reboot-pending` case. A real-time kernel (`+rt` in `uname -r`, package `kernel-rt-core`) has its own fixed version in the RHSA; without one it is `unknown`. `dnf updateinfo` looks at installed packages, not the running kernel, so do not use it here.
