#!/bin/sh
set -eu

# shellcheck source=/dev/null
. /etc/os-release
test "$ID:$VERSION_ID" = ubuntu:24.04

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y --no-install-recommends at autofs bind9 chrony cron fingerd \
    inetutils-telnetd nfs-kernel-server openbsd-inetd postfix rsh-redone-server \
    snmpd talkd tftpd-hpa vsftpd ypserv
systemctl stop nfs-server rpc-statd tftpd-hpa named postfix snmpd
systemctl disable --now autofs openbsd-inetd vsftpd ypserv
install -m 600 /dev/null /etc/inetd.conf
install -m 600 /dev/null /etc/hosts.equiv
install -m 644 /dev/null /etc/exports
for banner in /etc/issue /etc/issue.net /etc/motd; do
    printf '%s\n' 'Authorized access only.' > "$banner"
done
cat > /etc/ssh/sshd_config.d/00-hardening-vm.conf <<'EOF'
PermitRootLogin no
Banner /etc/issue.net
EOF
sshd -t
systemctl reload ssh

chown root:root /usr/bin/at
chmod 750 /usr/bin/at /usr/bin/crontab /usr/sbin/postsuper
find /etc/cron* /var/spool/cron -type f -exec chown root {} + -exec chmod 640 {} +
find /etc -maxdepth 1 -name 'at.*' -type f -exec chown root {} + -exec chmod 640 {} +
postconf -e 'inet_interfaces = loopback-only' 'smtpd_relay_restrictions = reject_unauth_destination' \
    'smtpd_recipient_restrictions = reject_unauth_destination' \
    'disable_vrfy_command = yes' 'smtpd_banner = Authorized access only'
cat > /etc/bind/named.conf.options <<'EOF'
options {
    directory "/var/cache/bind";
    listen-on { 127.0.0.1; };
    listen-on-v6 { none; };
    allow-transfer { none; };
    version "Authorized access only";
};
EOF
named-checkconf
cat > /etc/vsftpd.conf <<'EOF'
listen=YES
listen_address=127.0.0.1
anonymous_enable=NO
userlist_enable=YES
userlist_deny=YES
ftpd_banner=Authorized access only
EOF
printf '%s\n' root > /etc/vsftpd.user_list
if ! grep -qxF root /etc/ftpusers; then
    printf '%s\n' root >> /etc/ftpusers
fi
usermod -s /usr/sbin/nologin ftp
cat > /etc/snmp/snmpd.conf <<'EOF'
agentAddress udp:127.0.0.1:161
createUser hardeningVM SHA "FixturePassphrase2026"
rouser hardeningVM auth
EOF

cat > /etc/chrony.hardening-clock.conf <<'EOF'
bindaddress 127.0.0.1
allow 127.0.0.1
local stratum 10
cmdport 0
bindcmdaddress /
pidfile /run/chrony/hardening-clock.pid
EOF
cat > /run/systemd/system/hardening-clock.service <<'EOF'
[Service]
ExecStart=/usr/sbin/chronyd -4 -d -x -f /etc/chrony.hardening-clock.conf
EOF
cat > /etc/chrony/chrony.conf <<'EOF'
port 0
server 127.0.0.1 iburst minpoll 0 maxpoll 0
EOF
systemctl daemon-reload
systemctl restart chrony
systemctl restart hardening-clock
chronyc waitsync 30 0 0 1
