#!/bin/sh
set -eu

# shellcheck source=/dev/null
. /etc/os-release
test "$ID:${VERSION_ID%%.*}" = rocky:9

printf '%s\n' 'PermitRootLogin prohibit-password' > /etc/ssh/sshd_config.d/00-hardening-vm.conf
sshd -t
systemctl reload sshd
chmod 755 /usr/bin/crontab /usr/sbin/postsuper

postconf -e 'smtpd_relay_restrictions = permit' 'smtpd_recipient_restrictions = permit' 'disable_vrfy_command = no'
cat > /etc/named.conf <<'EOF'
options {
    directory "/var/named";
    listen-on { 127.0.0.1; };
    listen-on-v6 { none; };
    allow-transfer { any; };
};
zone "hardening.test" {
    type primary;
    file "/var/named/hardening.test";
    allow-update { any; };
};
EOF
named-checkconf
sed -i -e 's/^anonymous_enable=.*/anonymous_enable=YES/' -e '/^ftpd_banner=/d' /etc/vsftpd/vsftpd.conf
printf '%s\n' nobody > /etc/vsftpd/user_list
sed -i '/^root$/d' /etc/vsftpd/ftpusers
usermod -s /bin/sh ftp
cat > /etc/snmp/snmpd.conf <<'EOF'
agentAddress udp:127.0.0.1:161
rocommunity public
EOF
chmod 666 /etc/exports
install -m 644 /dev/null /etc/hosts.equiv
for unit in rsh telnet tftp; do
    case "$unit" in
        rsh) listen=ListenStream; port=514 ;;
        telnet) listen=ListenStream; port=23 ;;
        tftp) listen=ListenDatagram; port=69 ;;
    esac
    directory="/etc/systemd/system/$unit.socket.d"
    install -d "$directory"
    printf '[Socket]\n%s=\n%s=127.0.0.1:%s\n' "$listen" "$listen" "$port" \
        > "$directory/00-hardening-vm.conf"
done
systemctl daemon-reload
systemctl restart rsh.socket telnet.socket tftp.socket vsftpd
systemctl start autofs rpc-statd
systemctl stop chronyd hardening-clock
