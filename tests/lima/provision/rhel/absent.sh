#!/bin/sh
set -eu

# shellcheck source=/dev/null
. /etc/os-release
test "$ID:${VERSION_ID%%.*}" = rocky:9

if [ -f /run/systemd/system/hardening-clock.service ]; then
    systemctl stop hardening-clock
fi

dnf remove -y --noautoremove autofs bind chrony cronie at net-snmp nfs-utils \
    postfix rpcbind rsh-server telnet-server tftp-server vsftpd
if getent passwd ftp >/dev/null; then
    usermod -s /sbin/nologin ftp
fi
rm -f /etc/hosts.equiv /etc/ssh/sshd_config.d/00-hardening-vm.conf \
    /run/systemd/system/hardening-clock.service /etc/chrony.hardening-clock.conf \
    /etc/systemd/system/rsh.socket.d/00-hardening-vm.conf \
    /etc/systemd/system/telnet.socket.d/00-hardening-vm.conf \
    /etc/systemd/system/tftp.socket.d/00-hardening-vm.conf
systemctl daemon-reload
sshd -t
systemctl reload sshd
