# Distribution packages

The advisory names a source package (`openssh`) and a fixed version per release. Check the binary packages the server actually installs (`openssh-server`, `openssh-client`); every binary built from that source carries the same version once upgraded, but a server can hold them at different versions. When the advisory does not say which binary carries the vulnerable code, check each installed one, and the server is `affected` if any is older than the fix. The fixed version differs per release, so the check reads the release first and picks the fixed version for it. A release the advisory does not list is `unknown`, never compared against another release's fixed version.

Each check is one shell line, so it goes through `execute_command_multi_server`. It runs as an ordinary account; none of these commands needs root.

## Debian and Ubuntu

`dpkg --compare-versions` orders Debian versions (epochs, `~`, revisions) correctly on the host, so the host decides the verdict. Fill in one `case` arm per release from the advisory:

```sh
. /etc/os-release; case "$VERSION_CODENAME" in jammy) f='1:8.9p1-3ubuntu0.10';; noble) f='1:9.6p1-3ubuntu13.5';; *) echo "verdict=unknown release=$VERSION_CODENAME reason=release-not-in-advisory"; exit 0;; esac; s=$(dpkg-query -W -f='${db:Status-Abbrev}|${Version}' openssh-server 2>/dev/null); case "$s" in ii*) v=${s#*|};; *) echo "verdict=not_affected release=$VERSION_CODENAME installed=none"; exit 0;; esac; if dpkg --compare-versions "$v" lt "$f"; then r=affected; else r=not_affected; fi; echo "verdict=$r release=$VERSION_CODENAME installed=$v fixed=$f"
```

`dpkg-query` alone also reports packages that were removed but left their configuration behind; the `ii` status prefix is what means installed.

## RHEL, Rocky, AlmaLinux, Fedora

The repositories' update metadata already maps a CVE to the advisory that fixes it, so the check asks `dnf` instead of comparing RPM versions by hand:

```sh
. /etc/os-release; rpm -q openssh-server >/dev/null 2>&1 || { echo "verdict=not_affected release=$ID-$VERSION_ID installed=none"; exit 0; }; v=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE} ' openssh-server); if [ -n "$(dnf -q updateinfo list --available --cve CVE-2026-109618 2>/dev/null)" ]; then r=affected; elif [ -n "$(dnf -q updateinfo list --installed --cve CVE-2026-109618 2>/dev/null)" ]; then r=not_affected; else r=unknown; fi; echo "verdict=$r release=$ID-$VERSION_ID installed=$v"
```

`--available` lists a fixing advisory not yet installed; `--installed` lists one already installed. Neither means the repositories carry no update metadata for that CVE (CentOS Stream, a mirror without it, or a repository the server cannot reach), so the verdict is `unknown`, and the report says to compare `installed` with the advisory by hand.

## The kernel

What matters is the running kernel, not the newest one installed: a fixed kernel waiting for a reboot still leaves the server `affected`. Read the version of the package that provides the running kernel:

- Debian and Ubuntu: `dpkg-query -W -f='${Version}' "linux-image-$(uname -r)"`, compared with `dpkg --compare-versions` as above.
- RHEL family: `uname -r` (`5.14.0-427.13.1.el9_4.x86_64`) against the fixed kernel release. Kernel release strings are numeric, so `printf '%s\n' "$running" "$fixed" | sort -V | head -1` gives the older one. `dnf updateinfo` looks at installed packages, not the running kernel, so do not use it here.

When a fixed kernel is installed but not running, say so in the reason: the server needs a reboot, not a patch.
