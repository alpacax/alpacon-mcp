# Distribution packages

The advisory names a source package (`openssh`) and a fixed version per release. Check the binary packages the server actually installs (`openssh-server`, `openssh-client`); every binary built from that source carries the same version once upgraded, but a server can hold them at different versions. When the advisory does not say which binary carries the vulnerable code, check each installed one, and the server is `affected` if any is older than the fix.

Each check is one shell line and runs as an ordinary account; none of these commands needs root.

## Debian and Ubuntu

`dpkg --compare-versions` orders Debian versions (epochs, `~`, revisions) correctly on the host, so the host decides the verdict. Fill in one `case` arm per release from the advisory:

```sh
. /etc/os-release; case "$VERSION_CODENAME" in jammy) f='1:8.9p1-3ubuntu0.10';; noble) f='1:9.6p1-3ubuntu13.5';; *) echo "verdict=unknown release=$VERSION_CODENAME reason=release-not-in-advisory"; exit 0;; esac; command -v dpkg-query >/dev/null || { echo "verdict=unknown reason=no-dpkg"; exit 0; }; s=$(dpkg-query -W -f='${db:Status-Abbrev}|${Version}' openssh-server 2>/dev/null); case "$s" in ?i*) v=${s#*|};; ?[UFhWt]*) echo "verdict=unknown release=$VERSION_CODENAME reason=partly-installed status=${s%%|*}"; exit 0;; *) echo "verdict=not_affected release=$VERSION_CODENAME installed=none"; exit 0;; esac; if dpkg --compare-versions "$v" lt "$f"; then r=affected; else r=not_affected; fi; echo "verdict=$r release=$VERSION_CODENAME installed=$v fixed=$f"
```

The second letter of the status is what is on disk: `i` is installed, whatever the first letter says. A held package (`hi`) is installed and is exactly the kind that missed an upgrade. A package left half-installed is `unknown`.

## RHEL, Rocky, AlmaLinux, Fedora

The repositories' update metadata already maps a CVE to the advisory that fixes it, so the check asks `dnf` instead of comparing RPM versions by hand. Keep only the advisory lines for the package being checked:

```sh
. /etc/os-release; c=CVE-2026-109618; p=openssh-server; rpm -q "$p" >/dev/null 2>&1 || { echo "verdict=not_affected release=$ID-$VERSION_ID installed=none"; exit 0; }; v=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE} ' "$p"); has(){ dnf -q updateinfo list "$1" --cve "$c" 2>/dev/null | awk '{print $3}' | grep -q "^$p-[0-9]"; }; if has --available; then r=affected; elif has --installed; then r=not_affected; else r=unknown; fi; echo "verdict=$r release=$ID-$VERSION_ID installed=$v"
```

`--available` lists a fixing advisory not yet installed; `--installed` lists one already installed. Do not pass the package name to `dnf updateinfo` itself: with a package argument it also lists that package's unrelated advisories. Neither list naming the package means the repositories carry no update metadata for that CVE (CentOS Stream, a mirror without it, or a repository the server cannot reach), so the verdict is `unknown`, and the report says to compare `installed` with the advisory by hand.

## The kernel

What matters is the running kernel, not the newest one installed. A server running an old kernel with a fixed one installed is `affected` with `reason=reboot-pending`: it needs a reboot, not a patch, and `vuln-verify` reads that reason.

Ubuntu keeps the ABI name (`6.8.0-45-generic`) across some updates, so `uname -r` cannot tell two builds apart. Read the running build from `/proc/version_signature` instead:

```sh
f='6.8.0-45.45'; r=$(awk '{print $2}' /proc/version_signature 2>/dev/null); r=${r%-*}; [ -n "$r" ] || { echo "verdict=unknown reason=no-version-signature"; exit 0; }; if dpkg --compare-versions "$r" ge "$f"; then echo "verdict=not_affected running=$r"; exit 0; fi; for v in $(dpkg-query -W -f='${db:Status-Abbrev}|${Version}\n' 'linux-image-[0-9]*' 2>/dev/null | sed -n 's/^.i.|//p'); do dpkg --compare-versions "$v" ge "$f" && { echo "verdict=affected running=$r reason=reboot-pending"; exit 0; }; done; echo "verdict=affected running=$r"
```

- Debian: the running build is in `uname -v` (`... Debian 6.1.112-1 (2024-09-30)`); read it with `uname -v | sed -n 's/.* Debian \([^ ]*\) .*/\1/p'` and compare the same way.
- RHEL family: `uname -r` (`5.14.0-427.13.1.el9_4.x86_64`) names the build. Kernel release strings are numeric, so `printf '%s\n' "$running" "$fixed" | sort -V | head -1` gives the older one, and `rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core` lists the installed ones for the `reboot-pending` case. `dnf updateinfo` looks at installed packages, not the running kernel, so do not use it here.
