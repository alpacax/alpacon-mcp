#!/bin/sh
set -eu

# shellcheck source=/dev/null
. /etc/os-release
test "$ID:$VERSION_ID" = ubuntu:24.04

printf '%s\n' 'PermitRootLogin prohibit-password' > /etc/ssh/sshd_config.d/00-hardening-vm.conf
sshd -t
systemctl reload ssh
chmod 755 /usr/bin/crontab /usr/sbin/postsuper

postconf -e 'smtpd_relay_restrictions = permit' 'smtpd_recipient_restrictions = permit' 'disable_vrfy_command = no'
cat > /etc/bind/named.conf.options <<'EOF'
options {
    directory "/var/cache/bind";
    listen-on { 127.0.0.1; };
    listen-on-v6 { none; };
    allow-transfer { any; };
};
zone "hardening.test" {
    type primary;
    file "/var/cache/bind/hardening.test";
    allow-update { any; };
};
EOF
named-checkconf
sed -i -e 's/^anonymous_enable=.*/anonymous_enable=YES/' -e '/^ftpd_banner=/d' /etc/vsftpd.conf
printf '%s\n' nobody > /etc/vsftpd.user_list
sed -i '/^root$/d' /etc/ftpusers
usermod -s /bin/sh ftp
cat > /etc/snmp/snmpd.conf <<'EOF'
agentAddress udp:127.0.0.1:161
rocommunity public
EOF
chmod 666 /etc/exports
cat > /etc/inetd.conf <<'EOF'
127.0.0.1:
finger stream tcp nowait nobody /usr/sbin/in.fingerd in.fingerd
echo stream tcp nowait root internal
telnet stream tcp nowait root /usr/sbin/telnetd telnetd
shell stream tcp nowait root /usr/sbin/in.rshd in.rshd
ntalk dgram udp wait nobody /usr/sbin/in.ntalkd in.ntalkd
EOF
chmod 644 /etc/inetd.conf /etc/hosts.equiv
systemctl restart openbsd-inetd vsftpd
printf '%s\n' hardening.test > /etc/defaultdomain
printf '%s\n' '255.0.0.0 127.0.0.0' 'host ::1' > /var/yp/securenets
systemctl start autofs rpc-statd ypserv
systemctl stop chrony hardening-clock
