#!/bin/sh
set -eu

# shellcheck source=/dev/null
. /etc/os-release
test "$ID:$VERSION_ID" = ubuntu:24.04

if [ -f /run/systemd/system/hardening-clock.service ]; then
    systemctl stop hardening-clock
fi

if systemctl is-active --quiet ypserv; then
    systemctl stop ypserv
fi

export DEBIAN_FRONTEND=noninteractive
apt-get purge -y autofs bind9 chrony cron at fingerd inetutils-inetd inetutils-telnetd \
    nfs-kernel-server nfs-common openbsd-inetd postfix proftpd-core rpcbind rsh-redone-server snmpd \
    systemd-timesyncd talkd tftpd-hpa vsftpd xinetd ypbind-mt ypserv
rm -rf /var/cache/bind /var/lib/snmp
rm -f /etc/defaultdomain /etc/hosts.equiv /etc/inetd.conf /etc/ssh/sshd_config.d/00-hardening-vm.conf \
    /run/systemd/system/hardening-clock.service /etc/chrony.hardening-clock.conf
systemctl daemon-reload
sshd -t
systemctl reload ssh
