import dataclasses
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.hardening import (
    PERSON_KEYS,
    SCRIPT,
    Group,
    ItemId,
    Run,
    Verdict,
    load_registry,
    parse_run,
)

FAKE_HOST_SHELL = 'dash' if shutil.which('dash') else 'sh'

SCRIPT_IDS = {
    'U-01',
    'U-02',
    'U-03',
    'U-04',
    'U-05',
    'U-06',
    'U-10',
    'U-12',
    'U-13',
    'U-14',
    'U-15',
    'U-16',
    'U-17',
    'U-18',
    'U-19',
    'U-20',
    'U-21',
    'U-22',
    'U-24',
    'U-27',
    'U-29',
    'U-30',
    'U-31',
    'U-32',
    'U-34',
    'U-35',
    'U-36',
    'U-37',
    'U-38',
    'U-40',
    'U-41',
    'U-42',
    'U-43',
    'U-44',
    'U-46',
    'U-47',
    'U-48',
    'U-50',
    'U-51',
    'U-52',
    'U-53',
    'U-54',
    'U-55',
    'U-57',
    'U-59',
    'U-60',
    'U-61',
    'U-62',
    'U-63',
    'U-65',
    'U-67',
}
SERVICE_IDS = {
    'U-01',
    'U-20',
    'U-27',
    'U-34',
    'U-35',
    'U-36',
    'U-37',
    'U-38',
    'U-40',
    'U-41',
    'U-42',
    'U-43',
    'U-44',
    'U-46',
    'U-47',
    'U-48',
    'U-50',
    'U-51',
    'U-52',
    'U-53',
    'U-54',
    'U-55',
    'U-57',
    'U-59',
    'U-60',
    'U-61',
    'U-65',
}
KNOWN_PACKAGES = ' '.join(
    """openssh-server telnetd inetutils-telnetd telnet-server rsh-server rsh-redone-server fingerd finger-server
    vsftpd proftpd-basic proftpd-core proftpd openbsd-inetd xinetd postfix sendmail-bin
    sendmail exim4-daemon-light exim4-daemon-heavy exim bind9 bind nfs-kernel-server nfs-utils
    autofs nis ypserv ypbind ypbind-mt talkd talk-server tftpd-hpa tftp-server snmpd
    net-snmp chrony ntpsec ntp systemd-timesyncd samba rpcbind cron cronie at""".split()
)
KNOWN_UNITS = ' '.join(
    """sshd.service ssh.service telnet.socket telnet.service rsh.socket
    rsh.service rlogin.socket rlogin.service rexec.socket rexec.service
    finger.socket finger.service vsftpd.service proftpd.service ftp.socket
    inetd.service openbsd-inetd.service xinetd.service postfix.service
    sendmail.service exim4.service exim.service named.service bind9.service
    nfs-server.service nfs-kernel-server.service autofs.service ypserv.service
    ypbind.service ypxfrd.service talk.socket talk.service ntalk.socket
    ntalk.service tftp.socket tftp.service tftpd-hpa.service snmpd.service chronyd.service
    chrony.service ntpd.service ntp.service ntpsec.service smb.service smbd.service
    nmb.service nmbd.service echo.socket discard.socket daytime.socket
    chargen.socket rpc-statd.service rpc-rquotad.service rusersd.service
    rstatd.service rpcbind.service cron.service crond.service atd.service
    systemd-timesyncd.service rpc-cmsd.service rpc-ttdbserverd.service
    sadmind.service walld.service sprayd.service rexd.service rpc-pcnfsd.service
    rpc-ypupdated.service kcms-server.service cachefsd.service""".split()
)


@dataclass(frozen=True)
class Host:
    os_release: str
    passwd: str
    shadow: str | None
    login_defs: str
    os_mode: int = 0o644
    uid: int = 0
    shadow_stat: str = '400 root root'
    installed: str = 'openssh-server'
    active_units: str = 'sshd.service'
    loaded_units: str = ''
    unit_states: str = ''
    enabled_units: str = ''
    links: tuple[tuple[str, str], ...] = ()
    unreadable_dirs: tuple[str, ...] = ()
    bind_config: str | None = None
    failure_message: str = ''
    bind_exit: int = 0
    sshd: str = 'permitrootlogin no\nbanner /etc/issue.net\n'
    sshd_exit: int = 0
    login_path: str | None = '/usr/sbin:/usr/bin:/sbin:/bin'
    login_output: str = ''
    path_markers: bool = True
    su_exit: int = 0
    has_timeout: bool = True
    walk_exit: int = 0
    stat_exit: int = 0
    query_exit: int = 2
    securetty: str = 'tty1\ntty2\n'
    package_error: str = ''
    inetd_conf: str | None = None
    group: str = 'root:x:0:\nwheel:x:10:root\nalice:x:1000:alice\n'
    files: tuple[tuple[str, str | None], ...] = ()
    stats: tuple[tuple[str, str], ...] = ()
    walk: str = ''
    dev_walk: str = ''
    systemctl_error: str = ''
    time_source: str = '^* time.example.test\n'
    timesync: str = ''
    timedate: str = ''
    unreadable: tuple[str, ...] = ()
    held: str = ''
    fifos: tuple[str, ...] = ()


PASSWD = (
    'root:x:0:0:root:/root:/bin/bash\n'
    'alice:x:1000:1000:Alice:/home/alice:/bin/sh\n'
    'daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n'
)
SHADOW = 'root:$y$root-secret:20000:0:99999:7:::\nalice:$6$alice-secret:20000:0:99999:7:::\ndaemon:!:20000:0:99999:7:::\n'
DEBIAN_INSTALLED = (
    'openssh-server telnetd rsh-server fingerd vsftpd openbsd-inetd postfix '
    'bind9 nfs-kernel-server autofs nis ypserv ypbind-mt talkd tftpd-hpa snmpd chrony samba '
    'rpcbind cron at'
)
RHEL_INSTALLED = (
    'openssh-server telnet-server rsh-server finger-server vsftpd xinetd '
    'postfix bind nfs-utils autofs ypserv ypbind talk-server tftp-server '
    'net-snmp chrony samba rpcbind cronie at'
)
LOADED = 'ssh.service sshd.service telnet.service rsh.service rlogin.service finger.service vsftpd.service postfix.service nfs-server.service autofs.service ypserv.service talk.service tftp.service snmpd.service chronyd.service smbd.service rpc-statd.service'
BASE_DEBIAN = Host(
    'ID=debian\nVERSION_ID="12"\n',
    PASSWD,
    SHADOW,
    'ENCRYPT_METHOD YESCRYPT\nPASS_MIN_DAYS 1\nPASS_MAX_DAYS 90\nUMASK 022\n',
    installed=DEBIAN_INSTALLED,
    active_units='sshd.service chronyd.service',
    loaded_units=LOADED,
)
BASE_RHEL = Host(
    'ID=rocky\nID_LIKE="rhel centos fedora"\nVERSION_ID="9.5"\n',
    PASSWD,
    SHADOW.replace('$y$root-secret', '$6$root-secret'),
    'ENCRYPT_METHOD SHA512\nPASS_MIN_DAYS 1\nPASS_MAX_DAYS 90\nUMASK 022\n',
    shadow_stat='400 root root',
    installed=RHEL_INSTALLED,
    active_units='sshd.service chronyd.service',
    loaded_units=LOADED,
)


def _weakened(host: Host) -> Host:
    files = (
        ('/etc/security/pwquality.conf', 'minlen=7\ndcredit=0\n'),
        ('/etc/security/pwhistory.conf', 'remember=0\n'),
        ('/etc/pam.d/common-password', 'password required pam_unix.so\n'),
        (
            '/etc/pam.d/system-auth',
            'auth required pam_faillock.so deny=11\npassword required pam_unix.so\n',
        ),
        ('/etc/pam.d/common-auth', 'auth required pam_faillock.so deny=11\n'),
        ('/etc/pam.d/su', 'auth sufficient pam_rootok.so\n'),
        ('/etc/profile', 'TMOUT=900\nexport TMOUT\numask 000\n'),
        ('/etc/hosts.lpd', '+\n'),
        ('/etc/hosts.equiv', '+ +\n'),
        ('/home/alice/.profile', 'PATH=.:/usr/bin\n'),
        ('/etc/systemd/system/weak.service', '[Service]\nExecStart=/bin/false\n'),
        ('/etc/vsftpd.conf', 'anonymous_enable=YES\nftpd_banner=vsftpd 3.0\n'),
        ('/etc/xinetd.conf', 'service echo { disable = no }\n'),
        ('/etc/exports', '/* *(rw)\n'),
        (
            '/etc/mail/sendmail.cf',
            'O PrivacyOptions=authwarnings\nO Promiscuous_Relay=True\n',
        ),
        ('/etc/postfix/main.cf', 'disable_vrfy_command = no\n'),
        (
            '/etc/named.conf',
            'options { allow-transfer { any; }; allow-update { any; }; };\n',
        ),
        (
            '/etc/bind/named.conf.options',
            'options { allow-transfer { any; }; allow-update { any; }; };\n',
        ),
        ('/etc/ftpusers', 'daemon\n'),
        ('/etc/snmp/snmpd.conf', 'rocommunity public default\n'),
        ('/var/lib/snmp/snmpd.conf', None),
        ('/etc/chrony/chrony.conf', '# no source\n'),
        ('/etc/motd', ''),
        ('/etc/issue', ''),
        ('/etc/issue.net', ''),
    )
    stats = (
        ('/etc/passwd', '666 daemon daemon'),
        ('/etc/hosts', '666 daemon daemon'),
        ('/etc/hosts.lpd', '666 daemon daemon'),
        ('/etc/hosts.equiv', '666 daemon daemon'),
        ('/etc/rsyslog.conf', '666 daemon daemon'),
        ('/etc/services', '666 daemon daemon'),
        ('/etc/sudoers', '660 daemon daemon'),
        ('/etc/xinetd.conf', '666 daemon daemon'),
        ('/etc/exports', '666 daemon daemon'),
        ('/usr/bin/su', '4777 root root'),
        ('/usr/bin/crontab', '777 daemon daemon'),
        ('/usr/bin/at', '777 daemon daemon'),
        ('/usr/sbin/postsuper', '751 root root'),
        ('/root', '777 daemon daemon'),
        ('/home/alice', '777 root root'),
        ('/home/alice/.profile', '666 daemon daemon'),
        ('/etc/systemd/system/weak.service', '666 daemon daemon'),
    )
    passwd = (
        'root:plain:0:0:root:/root:/bin/bash\n'
        'toor:x:0:0:Toor:/missing:/bin/bash\n'
        'alice:x:1000:1000:Alice:/home/alice:/bin/sh\n'
        'bob:x:1000:1000:Bob:/missing-bob:/bin/sh\n'
        'ftp:x:14:50:FTP:/srv/ftp:/bin/bash\n'
    )
    active = ' '.join(
        unit for unit in KNOWN_UNITS.split() if unit != 'systemd-timesyncd.service'
    )
    walk = (
        'f\t6777\t9999\t9999\t9999\t9999\t{R}/unowned\n'
        'f\t666\troot\troot\t0\t0\t{R}/etc/systemd/system/weak.service\n'
        'f\t666\troot\troot\t0\t0\t{R}/.hidden\n'
        'f\t666\troot\troot\t0\t0\t{R}/var/log/weak.log\n'
        'f\t666\troot\troot\t0\t0\t{R}/etc/cron.d/weak\n'
    )
    return dataclasses.replace(
        host,
        passwd=passwd,
        shadow='root:$1$weak:1::::::\ntoor:$1$weak:1::::::\nalice::1::::::\nbob:$1$weak:1::::::\nftp:$1$weak:1::::::\n',
        login_defs='ENCRYPT_METHOD MD5\nPASS_MIN_DAYS 0\nPASS_MAX_DAYS 999\nUMASK 000\n',
        group='root:x:0:alice\nwheel:x:10:\n',
        login_path='.:/usr/bin',
        files=files,
        stats=stats,
        active_units=active,
        sshd='permitrootlogin yes\nbanner none\n',
        shadow_stat='777 daemon daemon',
        securetty='pts/0\n',
        walk=walk,
        dev_walk='f\t666\troot\troot\t0\t0\t{R}/dev/plain-file\n',
        time_source='',
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text('#!/bin/sh\n' + body + '\n')
    path.chmod(0o755)


def _install_fakes(bin_dir: Path, host: Host) -> None:
    bin_dir.mkdir()
    awk = shutil.which('awk')
    sed = shutil.which('sed')
    tr = shutil.which('tr')
    assert awk is not None and sed is not None and tr is not None
    awk_guard = """program=0; option_value=0
for argument do
    if [ "$option_value" = 1 ]; then option_value=0; continue; fi
    if [ "$program" = 0 ]; then
        case $argument in -F|-v) option_value=1 ;; -F*|-v*) : ;; *) program=1 ;; esac
        continue
    fi
    case $argument in "$FAKE_ROOT"/*) ;; /*) exit 91 ;; esac
done"""
    _write_executable(bin_dir / 'awk', awk_guard + f'\nexec {awk} "$@"')
    _write_executable(
        bin_dir / 'sed',
        f'for argument do case $argument in /*) exit 91 ;; esac; done\nexec {sed} "$@"',
    )
    _write_executable(
        bin_dir / 'tr',
        f'for argument do case $argument in /*) exit 91 ;; esac; done\nexec {tr} "$@"',
    )
    _write_executable(
        bin_dir / 'id',
        '[ "$#" = 1 ] && [ "$1" = -u ] || exit 91\nprintf \'%s\\n\' "$FAKE_UID"',
    )
    _write_executable(
        bin_dir / 'sha256sum',
        '[ "$#" = 1 ] && [ "$1" = "$FAKE_SCRIPT" ] || exit 91\nprintf \'%064d  %s\\n\' 0 "$1"',
    )
    _write_executable(
        bin_dir / 'sshd',
        '[ "$#" = 1 ] && [ "$1" = -T ] || exit 91\nprintf \'%s\' "$FAKE_SSHD"\nexit "$FAKE_SSHD_EXIT"',
    )
    if host.login_path is not None:
        _write_executable(
            bin_dir / 'su',
            r"""[ "$#" = 4 ] && [ "$1" = -l ] && [ "$2" = root ] && [ "$3" = -c ] && [ "$4" = 'printf "\n__HC_PATH_BEGIN__%s__HC_PATH_END__\n" "$PATH"' ] || exit 91
if IFS= read -r input; then exit 91; fi
printf '%s' "$FAKE_LOGIN_OUTPUT"
if [ "$FAKE_PATH_MARKERS" = 1 ]; then printf '\n__HC_PATH_BEGIN__%s__HC_PATH_END__\n' "$FAKE_LOGIN_PATH"; else printf '%s' "$FAKE_LOGIN_PATH"; fi
[ "$FAKE_SU_EXIT" = 0 ] || printf '%s\n' "$FAKE_FAILURE_MESSAGE" >&2
exit "$FAKE_SU_EXIT"
""",
        )
    _write_executable(
        bin_dir / 'find',
        r"""if [ "$1" = "$FAKE_ROOT/dev" ]; then
[ "$#" = 4 ] && [ "$2" = -xdev ] && [ "$3" = -printf ] && [ "$4" = '%y\t%m\t%u\t%g\t%U\t%G\t%p\n' ] || exit 91
printf 'find\n' >> "$FAKE_CALL_LOG"
printf '%s' "$FAKE_DEV_WALK"
else
[ "$#" = 8 ] && [ "$1" = "$FAKE_ROOT/" ] && [ "$2" = "$FAKE_ROOT/var/log" ] && [ "$3" = "$FAKE_ROOT/var/spool" ] && [ "$4" = "$FAKE_ROOT/var/spool/cron" ] && [ "$5" = "$FAKE_ROOT/var/spool/at" ] || exit 91
shift 5
[ "$1" = -xdev ] && [ "$2" = -printf ] && [ "$3" = '%y\t%m\t%u\t%g\t%U\t%G\t%p\n' ] || exit 91
printf 'find\n' >> "$FAKE_CALL_LOG"
printf '%s' "$FAKE_WALK"
tab=$(printf '\t')
while IFS= read -r row; do path=${row##*"$tab"}; case $path in "$FAKE_ROOT/var/log/"*|"$FAKE_ROOT/var/spool/"*) printf '%s\n' "$row" ;; esac; done <<EOF
$FAKE_WALK
EOF
fi
[ "$FAKE_WALK_EXIT" = 0 ] || printf '%s\n' "$FAKE_FAILURE_MESSAGE" >&2
exit "$FAKE_WALK_EXIT"
""",
    )
    if host.has_timeout:
        _write_executable(
            bin_dir / 'timeout',
            r"""[ "$#" -ge 2 ] || exit 91
case "$1:$2" in 10:su|15:sshd|15:find|15:named-checkconf|15:timedatectl|15:chronyc) ;; *) exit 91 ;; esac
shift
case "$1" in
    sshd) [ "$#" = 2 ] && [ "$2" = -T ] || exit 91; printf 'sshd\n' >> "$FAKE_CALL_LOG"; [ "$FAKE_SSHD_EXIT" = 124 ] && exit 124; printf '%s' "$FAKE_SSHD"; exit "$FAKE_SSHD_EXIT" ;;
    su) [ "$FAKE_SU_EXIT" != 124 ] || exit 124; exec "$@" ;;
    find|named-checkconf|timedatectl) command=$1; shift; exec "$command" "$@" ;;
    chronyc) [ "$#" = 2 ] && [ "$2" = sources ] || exit 91; printf '%s' "$FAKE_TIME_SOURCE" ;;
    *) exit 91 ;;
esac""",
        )
    _write_executable(
        bin_dir / 'chronyc',
        '[ "$#" = 1 ] && [ "$1" = sources ] || exit 91\nprintf \'%s\' "$FAKE_TIME_SOURCE"',
    )
    _write_executable(
        bin_dir / 'timedatectl',
        """[ "$#" = 1 ] || exit 91
case "$1" in
    show-timesync) printf '%s' "$FAKE_TIMESYNC" ;;
    show) printf '%s' "$FAKE_TIMEDATE" ;;
    *) exit 91 ;;
esac""",
    )
    _write_executable(
        bin_dir / 'ss',
        '[ "$#" = 1 ] && [ "$1" = -lntu ] || exit 91\n'
        "printf 'Netid State Local Address:Port\\ntcp LISTEN 0.0.0.0:22\\n'",
    )
    _write_executable(
        bin_dir / 'named-checkconf',
        r"""[ "$#" = 3 ] && [ "$1" = -p ] && [ "$2" = -x ] || exit 91
case "$3" in "$FAKE_ROOT/etc/named.conf"|"$FAKE_ROOT/etc/bind/named.conf") ;; *) exit 91 ;; esac
printf 'named-checkconf\n' >> "$FAKE_CALL_LOG"
printf '%s' "$FAKE_BIND_CONFIG"
[ "$FAKE_BIND_EXIT" = 0 ] || printf '%s\n' "$FAKE_FAILURE_MESSAGE" >&2
exit "$FAKE_BIND_EXIT"
""",
    )
    _write_executable(
        bin_dir / 'dpkg-query',
        """[ "$#" = 3 ] && [ "$1" = -W ] && [ "$2" = '-f=${Status}' ] || exit 91
case " $FAKE_KNOWN_PACKAGES " in *" $3 "*) ;; *) exit 91 ;; esac
case " $FAKE_PACKAGE_ERROR " in *" $3 "*) printf '%s\\n' "$FAKE_FAILURE_MESSAGE" >&2; exit "$FAKE_QUERY_EXIT" ;; esac
case " $FAKE_HELD " in *" $3 "*) printf 'hold ok installed'; exit 0 ;; esac
case " $FAKE_INSTALLED " in *" $3 "*) printf 'install ok installed'; exit 0 ;; *) printf 'dpkg-query: no packages found matching %s\n' "$3" >&2; exit 1 ;; esac""",
    )
    _write_executable(
        bin_dir / 'rpm',
        """[ "$#" = 2 ] && [ "$1" = -q ] || exit 91
case " $FAKE_KNOWN_PACKAGES " in *" $2 "*) ;; *) exit 91 ;; esac
case " $FAKE_PACKAGE_ERROR " in *" $2 "*) printf '%s\\n' "$FAKE_FAILURE_MESSAGE" >&2; exit "$FAKE_QUERY_EXIT" ;; esac
case " $FAKE_INSTALLED " in *" $2 "*) printf '%s-1.0\n' "$2"; exit 0 ;; *) printf 'package %s is not installed\n' "$2"; exit 1 ;; esac""",
    )
    _write_executable(
        bin_dir / 'systemctl',
        """if [ "$1" = list-unit-files ]; then
    [ "$*" = 'list-unit-files --state=enabled,enabled-runtime --no-legend --no-pager' ] || exit 91
    for unit in $FAKE_ENABLED_UNITS; do printf '%s enabled enabled\\n' "$unit"; done
    exit 0
fi
if [ "$1" = list-units ]; then
    [ "$*" = 'list-units --all --no-legend --plain --no-pager *.service *.socket *.target' ] || exit 91
    for unit in $FAKE_ACTIVE_UNITS; do printf '%s loaded active running -\\n' "$unit"; done
    for pair in $FAKE_UNIT_STATES; do printf '%s loaded %s running -\\n' "${pair%:*}" "${pair#*:}"; done
    exit 0
fi
[ "$#" = 6 ] && [ "$1" = show ] && [ "$2" = -p ] && [ "$3" = LoadState ] && [ "$4" = -p ] && [ "$5" = ActiveState ] || exit 91
case " $FAKE_KNOWN_UNITS " in *" $6 "*) ;; *) exit 91 ;; esac
case " $FAKE_SYSTEMCTL_ERROR " in *" $6 "*) exit "$FAKE_QUERY_EXIT" ;; esac
for pair in $FAKE_UNIT_STATES; do
    if [ "${pair%:*}" = "$6" ]; then printf 'LoadState=loaded\\nActiveState=%s\\n' "${pair#*:}"; exit; fi
done
case " $FAKE_ACTIVE_UNITS " in *" $6 "*) printf 'LoadState=loaded\\nActiveState=active\\n' ;; *) case " $FAKE_LOADED_UNITS " in *" $6 "*) printf 'LoadState=loaded\\nActiveState=inactive\\n' ;; *) printf 'LoadState=not-found\\nActiveState=inactive\\n' ;; esac ;; esac""",
    )
    _write_executable(
        bin_dir / 'stat',
        """follow=no
if [ "$#" = 4 ] && [ "$1" = -L ]; then follow=yes; shift; fi
[ "$#" = 3 ] && [ "$1" = -c ] && [ "$2" = '%a %U %G' ] || exit 91
case "$3" in "$FAKE_ROOT"/*) key=${3#"$FAKE_ROOT"} ;; *) exit 91 ;; esac
if [ -L "$3" ]; then
    if [ "$follow" = no ]; then printf '777 root root\n'; exit; fi
    [ -e "$3" ] || exit 2
    while IFS='|' read -r link target; do
        [ "$key" != "$link" ] || { key=$target; break; }
    done < "$FAKE_LINK_FILE"
fi
[ "$key" != /etc/shadow ] || { [ "$FAKE_STAT_EXIT" = 0 ] || { printf '%s\\n' "$FAKE_FAILURE_MESSAGE" >&2; exit "$FAKE_STAT_EXIT"; }; printf '%s\n' "$FAKE_SHADOW_STAT"; exit; }
while IFS='|' read -r path value; do [ "$key" != "$path" ] || { printf '%s\n' "$value"; exit; }; done < "$FAKE_STAT_FILE"
exit 91""",
    )


def _run(
    tmp_path: Path, host: Host, shell: str = FAKE_HOST_SHELL
) -> subprocess.CompletedProcess[str]:
    root = tmp_path / 'host'
    etc = root / 'etc'
    etc.mkdir(parents=True)
    for directory in ('var/log', 'var/spool/cron', 'var/spool/at'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (etc / 'os-release').write_text(host.os_release)
    (etc / 'os-release').chmod(host.os_mode)
    (etc / 'passwd').write_text(host.passwd)
    (etc / 'login.defs').write_text(host.login_defs)
    (etc / 'group').write_text(host.group)
    pam_dir = etc / 'pam.d'
    pam_dir.mkdir()
    (pam_dir / 'login').write_text('auth required pam_securetty.so\n')
    defaults: dict[str, str | None] = {
        '/etc/security/pwquality.conf': 'minlen=8\ndcredit=-1\nucredit=-1\nlcredit=-1\nocredit=-1\nenforce_for_root\n',
        '/etc/security/pwhistory.conf': 'remember=4\nenforce_for_root\n',
        '/etc/pam.d/common-password': 'password requisite pam_pwquality.so enforce_for_root\npassword required pam_pwhistory.so remember=4\npassword required pam_unix.so\n',
        '/etc/pam.d/common-auth': 'auth required pam_faillock.so preauth deny=10\nauth [default=die] pam_faillock.so authfail deny=10\n',
        '/etc/pam.d/common-account': 'account required pam_faillock.so\n',
        '/etc/pam.d/system-auth': 'auth required pam_faillock.so preauth deny=10\nauth [default=die] pam_faillock.so authfail deny=10\naccount required pam_faillock.so\npassword requisite pam_pwquality.so enforce_for_root\npassword required pam_pwhistory.so remember=4\npassword required pam_unix.so\n',
        '/etc/pam.d/su': 'auth required pam_wheel.so use_uid\n',
        '/etc/pam.d/vsftpd': 'auth required pam_listfile.so item=user sense=deny file=/etc/ftpusers onerr=succeed\n',
        '/etc/profile': 'TMOUT=600\nexport TMOUT\numask 022\n',
        '/etc/shells': '/bin/bash\n/bin/sh\n',
        '/etc/hosts': '127.0.0.1 localhost\n',
        '/etc/services': 'ssh 22/tcp\n',
        '/etc/sudoers': 'root ALL=(ALL) ALL\n',
        '/etc/rsyslog.conf': '*.info /var/log/messages\n*.* @@logs.example.test\n',
        '/etc/ssh/sshd_config': 'PermitRootLogin no\nBanner /etc/issue.net\n',
        '/etc/vsftpd.conf': 'anonymous_enable=NO\nftpd_banner=Authorized use only\nuserlist_enable=NO\n',
        '/etc/samba/smb.conf': 'guest ok = no\n',
        '/etc/xinetd.conf': 'defaults { }\n',
        '/etc/exports': '/srv/share 192.0.2.0/24(ro)\n',
        '/etc/ftpusers': 'root\n',
        '/etc/postfix/main.cf': 'smtpd_recipient_restrictions = reject_unauth_destination\ndisable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
        '/etc/postfix/master.cf': 'smtp inet n - y - - smtpd\n',
        '/etc/mail/sendmail.cf': 'O PrivacyOptions=goaway,restrictqrun,noexpn,novrfy\nO SmtpGreetingMessage=Authorized use only\n',
        '/etc/bind/named.conf': 'include "/etc/bind/named.conf.options";\n',
        '/etc/named.conf': 'version "Authorized use only";\nallow-transfer { none; };\nallow-update { none; };\n',
        '/etc/bind/named.conf.options': 'version "Authorized use only";\nallow-transfer { none; };\nallow-update { none; };\n',
        '/etc/snmp/snmpd.conf': 'rouser monitor authPriv\n',
        '/var/lib/snmp/snmpd.conf': 'createUser monitor SHA "Abcdef12!" AES\n',
        '/etc/chrony/chrony.conf': 'server time.example.test iburst\n',
        '/etc/motd': 'Authorized use only\n',
        '/etc/issue': 'Authorized use only\n',
        '/etc/issue.net': 'Authorized use only\n',
        '/etc/systemd/system/example.service': '[Service]\nExecStart=/bin/true\n',
        '/var/log/auth.log': 'ok\n',
    }
    defaults.update(dict(host.files))
    for name in ('/etc/named.conf', '/etc/bind/named.conf.options'):
        value = defaults.get(name)
        if value and not value.lstrip().startswith(
            ('options ', 'view ', 'zone ', 'include ')
        ):
            defaults[name] = 'options {\n' + value + '\n};\n'
    for relative, content in defaults.items():
        path = root / relative.removeprefix('/')
        if content is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for relative in host.unreadable:
        (root / relative.removeprefix('/')).chmod(0)
    for home in ('/root', '/home/alice', '/usr/sbin'):
        (root / home.removeprefix('/')).mkdir(parents=True, exist_ok=True)
    for command in (
        '/usr/bin/su',
        '/usr/bin/crontab',
        '/usr/bin/at',
        '/usr/sbin/postsuper',
    ):
        path = root / command.removeprefix('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (etc / 'securetty').write_text(host.securetty)
    if host.inetd_conf is not None:
        (etc / 'inetd.conf').write_text(host.inetd_conf)
    if host.shadow is not None:
        (etc / 'shadow').write_text(host.shadow)
    for name, target in host.links:
        link = root / name.removeprefix('/')
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to(root / target.removeprefix('/'))
    for name in host.fifos:
        os.mkfifo(root / name.removeprefix('/'))
    for name in host.unreadable_dirs:
        locked = root / name.removeprefix('/')
        locked.mkdir(parents=True, exist_ok=True)
        locked.chmod(0)
    link_file = tmp_path / 'links'
    link_file.write_text(''.join(f'{name}|{target}\n' for name, target in host.links))
    script = tmp_path / 'hardening-check.sh'
    bin_dir = tmp_path / 'bin'
    _install_fakes(bin_dir, host)
    # Source the hot-path fakes in subshells to avoid re-launching the shell for each query.
    fake_functions = '\n'.join(
        f"{function}() ( . '{bin_dir / command}' )"
        for function, command in (
            ('rpm', 'rpm'),
            ('systemctl', 'systemctl'),
            ('stat', 'stat'),
            ('fake_dpkg_query', 'dpkg-query'),
            ('fake_awk', 'awk'),
        )
    )
    original = SCRIPT.read_text()
    assert all(seam in original for seam in ("R=''", 'dpkg-query -W', 'command awk'))
    source = (
        original.replace("R=''", f"R='{root}'\n{fake_functions}", 1)
        .replace('dpkg-query -W', 'fake_dpkg_query -W')
        .replace('command awk', 'fake_awk')
    )
    script.write_text(source)
    script.chmod(0o755)
    call_log = tmp_path / 'calls.log'
    stat_file = tmp_path / 'stats'
    default_stats = {
        '/etc/passwd': '644 root root',
        '/etc/group': '644 root root',
        '/etc/login.defs': '644 root root',
        '/etc/securetty': '600 root root',
        '/root': '700 root root',
        '/home/alice': '700 alice alice',
        '/usr/sbin': '755 daemon daemon',
        '/usr/bin/su': '4750 root wheel',
        '/usr/bin/crontab': '750 root root',
        '/usr/bin/at': '750 root root',
        '/usr/sbin/postsuper': '750 root root',
    }
    for relative, content in defaults.items():
        if content is not None:
            default_stats.setdefault(relative, '600 root root')
    default_stats.update(dict(host.stats))
    stat_file.write_text(
        ''.join(f'{path}|{value}\n' for path, value in default_stats.items())
    )
    walk = (
        host.walk.replace('{R}', str(root))
        if host.walk
        else (
            f'f\t600\troot\troot\t0\t0\t{root}/var/log/auth.log\n'
            f'f\t600\troot\troot\t0\t0\t{root}/etc/systemd/system/example.service\n'
        )
    )
    bind_path = (
        '/etc/bind/named.conf.options'
        if 'ID=debian' in host.os_release
        else '/etc/named.conf'
    )
    bind_body = defaults.get(bind_path)
    bind_config = host.bind_config if host.bind_config is not None else bind_body or ''
    bind_exit = host.bind_exit or (
        2 if bind_body is None and host.bind_config is None else 0
    )
    return subprocess.run(  # noqa: S603  # published script against isolated fakes
        [shutil.which(shell) or shell, str(script)],
        env={
            'PATH': str(bin_dir),
            'LC_ALL': 'C',
            'FAKE_ROOT': str(root),
            'FAKE_SCRIPT': str(script),
            'FAKE_UID': str(host.uid),
            'FAKE_SHADOW_STAT': host.shadow_stat,
            'FAKE_INSTALLED': host.installed,
            'FAKE_HELD': host.held,
            'FAKE_ACTIVE_UNITS': host.active_units,
            'FAKE_LOADED_UNITS': host.loaded_units,
            'FAKE_BIND_CONFIG': bind_config,
            'FAKE_BIND_EXIT': str(bind_exit),
            'FAKE_FAILURE_MESSAGE': host.failure_message,
            'FAKE_SSHD': host.sshd,
            'FAKE_SSHD_EXIT': str(host.sshd_exit),
            'FAKE_LOGIN_PATH': host.login_path or '',
            'FAKE_LOGIN_OUTPUT': host.login_output,
            'FAKE_PATH_MARKERS': str(int(host.path_markers)),
            'FAKE_SU_EXIT': str(host.su_exit),
            'FAKE_WALK_EXIT': str(host.walk_exit),
            'FAKE_WALK': walk,
            'FAKE_DEV_WALK': host.dev_walk.replace('{R}', str(root)),
            'FAKE_STAT_EXIT': str(host.stat_exit),
            'FAKE_QUERY_EXIT': str(host.query_exit),
            'FAKE_PACKAGE_ERROR': host.package_error,
            'FAKE_CALL_LOG': str(call_log),
            'FAKE_STAT_FILE': str(stat_file),
            'FAKE_LINK_FILE': str(link_file),
            'FAKE_UNIT_STATES': host.unit_states,
            'FAKE_ENABLED_UNITS': host.enabled_units,
            'FAKE_KNOWN_PACKAGES': KNOWN_PACKAGES,
            'FAKE_KNOWN_UNITS': KNOWN_UNITS,
            'FAKE_SYSTEMCTL_ERROR': host.systemctl_error,
            'FAKE_TIME_SOURCE': host.time_source,
            'FAKE_TIMESYNC': host.timesync,
            'FAKE_TIMEDATE': host.timedate,
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def _parsed(tmp_path: Path, host: Host, shell: str = FAKE_HOST_SHELL):
    result = _run(tmp_path, host, shell)

    assert result.returncode == 0, result.stderr
    return parse_run(result.stdout, expected_sha256='0' * 64), result


def _parse_batch[Case](
    paths: dict[Case, Path], hosts: dict[Case, Host]
) -> dict[Case, tuple[Run, subprocess.CompletedProcess[str]]]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = pool.map(_parsed, (paths[case] for case in hosts), hosts.values())
        return dict(zip(hosts, runs, strict=True))


def _parsed_cases(
    tmp_path_factory: pytest.TempPathFactory, hosts: dict[str, Host]
) -> dict[str, tuple[Run, subprocess.CompletedProcess[str]]]:
    return _parse_batch({name: tmp_path_factory.mktemp(name) for name in hosts}, hosts)


def _absent(base: Host) -> Host:
    return dataclasses.replace(
        base,
        installed='',
        active_units='',
        loaded_units='',
        sshd_exit=127,
        files=(('/etc/xinetd.conf', None),),
    )


@pytest.fixture(scope='module')
def base_runs(tmp_path_factory):
    hosts = {}
    for base in (BASE_DEBIAN, BASE_RHEL):
        hosts['secured', base] = base
        hosts['weakened', base] = _weakened(base)
        hosts['absent', base] = _absent(base)

    paths = {case: tmp_path_factory.mktemp(case[0]) for case in hosts}
    return {
        case: (*result, paths[case])
        for case, result in _parse_batch(paths, hosts).items()
    }


@pytest.fixture(scope='module')
def edge_runs(tmp_path_factory):
    hash_shadow = (
        'yescrypt:$y$yescrypt-secret:1::::::\n'
        'sha512:$6$sha512-secret:1::::::\n'
        'sha256:$5$sha256-secret:1::::::\n'
        'md5:$1$md5-secret:1::::::\n'
        'locked1:!:1::::::\nlocked2:*:1::::::\nempty::1::::::\nother:plain-secret:1::::::\n'
    )
    hosts = {
        'non_root': dataclasses.replace(BASE_DEBIAN, uid=1000),
        'legacy_hashes_metadata': dataclasses.replace(
            BASE_DEBIAN,
            installed='openssh-server telnetd',
            active_units='sshd.service telnet.socket',
            securetty='tty1\npts/0\n',
            shadow=hash_shadow,
            stat_exit=2,
        ),
        'malformed_passwd_root_ssh': dataclasses.replace(
            BASE_DEBIAN,
            passwd='missing-fields:x:1000\n',
            sshd='permitrootlogin prohibit-password\n',
        ),
        'timeout_missing_shadow': dataclasses.replace(
            BASE_DEBIAN, sshd_exit=124, shadow=None
        ),
        'locked_default_shadow': dataclasses.replace(
            BASE_DEBIAN,
            sshd='port 22\n',
            shadow='root:!$1$locked-md5-secret:1::::::\n',
            shadow_stat='640 root shadow',
        ),
        'yescrypt_special_mode': dataclasses.replace(
            BASE_DEBIAN,
            shadow='root:$y$root-secret:1::::::\n',
            login_defs='ENCRYPT_METHOD YESCRYPT\n',
            shadow_stat='4400 root root',
            inetd_conf='telnet stream tcp nowait root /usr/sbin/in.telnetd in.telnetd\n',
        ),
        'many_accounts_zero_mode': dataclasses.replace(
            BASE_DEBIAN,
            passwd=''.join(
                f'user{number}:x:{1000 + number}:100:User:/home/user{number}:/bin/sh\n'
                for number in range(23)
            ),
            shadow_stat='000 root root',
            active_units='telnet@pts0.service',
        ),
    }
    return _parsed_cases(tmp_path_factory, hosts)


@pytest.mark.parametrize('host', [BASE_DEBIAN, BASE_RHEL])
def test_every_script_item_passes_on_a_secured_supported_host(base_runs, host: Host):
    run, result, _ = base_runs['secured', host]

    assert {
        str(item_id)
        for item_id, result in run.items.items()
        if result.verdict is Verdict.PASS
    } == SCRIPT_IDS
    assert all(run.items[ItemId(item_id)].facts for item_id in SCRIPT_IDS)
    assert run.items[ItemId('U-20')].facts['metadata'] == '600 root root'
    assert run.items[ItemId('U-67')].facts['log_files'] == '1'
    assert run.items[ItemId('U-62')].facts['targets'] == '7'
    for item_id, keys in PERSON_KEYS.items():
        item = run.items[item_id]
        assert item.verdict is Verdict.REVIEW
        assert item.facts.keys() == keys
    assert 'Abcdef12!' not in result.stdout + result.stderr


@pytest.mark.parametrize('host', [BASE_DEBIAN, BASE_RHEL])
def test_every_script_item_fails_on_a_weakened_host(base_runs, host: Host):
    run, result, _ = base_runs['weakened', host]

    assert {
        str(item_id)
        for item_id, item in run.items.items()
        if item.verdict is Verdict.FAIL
    } == SCRIPT_IDS
    assert 'Abcdef12!' not in result.stdout + result.stderr


@pytest.mark.parametrize('base', [BASE_DEBIAN, BASE_RHEL])
def test_every_service_item_is_na_when_its_packages_are_confirmed_absent(
    base_runs, base: Host
):
    run, _, _ = base_runs['absent', base]

    assert {
        str(item_id)
        for item_id, item in run.items.items()
        if item.verdict is Verdict.NA
    } == SERVICE_IDS


def test_case_catalog_covers_the_registry_and_service_contract():
    registry = load_registry()
    script_ids = {str(item.id) for item in registry.in_group(Group.SCRIPT)}

    assert SCRIPT_IDS == script_ids
    assert SERVICE_IDS <= script_ids


def test_highest_lockout_value_counts_and_password_modules_must_precede_unix(
    tmp_path: Path,
):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/pam.d/common-password',
                'password required pam_unix.so\npassword requisite pam_pwquality.so enforce_for_root\npassword required pam_pwhistory.so remember=4\n',
            ),
            (
                '/etc/pam.d/common-auth',
                'auth required pam_faillock.so preauth deny=3\nauth required pam_faillock.so authfail deny=10\n',
            ),
        ),
    )
    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-02')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-03')].verdict is Verdict.PASS


@pytest.fixture(scope='module')
def local_check_runs(tmp_path_factory):
    hosts = {
        'pam-options': dataclasses.replace(
            BASE_DEBIAN,
            files=(
                (
                    '/etc/pam.d/common-password',
                    (
                        'password requisite pam_pwquality.so minlen=6 # minlen=8 dcredit=-1 ucredit=-1 lcredit=-1 ocredit=-1\n'
                        'password required pam_pwhistory.so remember=4 enforce_for_root\n'
                        'password required pam_unix.so\n'
                    ),
                ),
                ('/etc/pam.d/common-auth', 'auth required pam_faillock.so deny=20\n'),
                ('/etc/security/faillock.conf', 'deny=5\n'),
            ),
        ),
        'su-bypass': dataclasses.replace(
            BASE_DEBIAN,
            files=(
                (
                    '/etc/pam.d/su',
                    'auth sufficient pam_unix.so\nauth required pam_wheel.so group=wheel\n',
                ),
            ),
        ),
        'su-command-shell-accounts': dataclasses.replace(
            BASE_DEBIAN,
            passwd=(
                'root:x:0:0:root:/root:/bin/bash\n'
                'sync:x:4:65534:sync:/bin:/bin/sync\n'
                'daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n'
            ),
            files=(('/etc/pam.d/su', 'auth sufficient pam_rootok.so\n'),),
        ),
        'duplicate-uid': dataclasses.replace(
            BASE_DEBIAN,
            passwd=PASSWD + 'bob:x:01000:1000:Bob:/home/bob:/bin/sh\n',
        ),
        'malformed-uid': dataclasses.replace(
            BASE_DEBIAN,
            passwd=PASSWD.replace('alice:x:1000:', 'alice:x:not-a-number:'),
        ),
        'weak-login-policy': dataclasses.replace(
            BASE_DEBIAN,
            files=(
                (
                    '/etc/profile',
                    'TMOUT=600\nexport TMOUT\numask 022\n. /etc/login-extra\n',
                ),
                ('/etc/login-extra', 'safe=yes; TMOUT=0\numask 000\n'),
                ('/etc/profile.d/weaker.sh', 'export TMOUT="0"\n'),
                ('/etc/csh.login', 'TMOUT=900\n'),
            ),
        ),
        'incomplete-login-policy': dataclasses.replace(
            BASE_DEBIAN,
            files=(
                (
                    '/etc/profile',
                    'TMOUT=600\nexport TMOUT\numask u=rwx,g=rx,o=rx\nsource /etc/missing-login-policy\n',
                ),
            ),
        ),
        'bash-login': dataclasses.replace(
            BASE_DEBIAN,
            files=(('/home/alice/.bash_login', 'umask 022\n'),),
            stats=(('/home/alice/.bash_login', '666 alice alice'),),
        ),
    }
    return _parsed_cases(tmp_path_factory, hosts)


def test_pam_inline_comments_and_module_arguments_control_the_policy(local_check_runs):
    run, _ = local_check_runs['pam-options']

    assert run.items[ItemId('U-02')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-03')].verdict is Verdict.FAIL


def test_u06_fails_when_sufficient_auth_bypasses_pam_wheel(local_check_runs):
    run, _ = local_check_runs['su-bypass']

    assert run.items[ItemId('U-06')].verdict is Verdict.FAIL


def test_u06_counts_only_accounts_with_a_shell_from_etc_shells(local_check_runs):
    run, _ = local_check_runs['su-command-shell-accounts']

    assert run.items[ItemId('U-06')].verdict is Verdict.PASS
    assert run.items[ItemId('U-06')].facts == {'accounts': 'root-only'}


def test_a_supported_host_writes_nothing_to_stderr(base_runs, edge_runs):
    results = {key: result for key, (_, result, _) in base_runs.items()}
    results['non_root'] = edge_runs['non_root'][1]

    noisy = {key: result.stderr for key, result in results.items() if result.stderr}

    assert noisy == {}


def test_uid_checks_compare_numeric_values_and_reject_malformed_uids(local_check_runs):
    duplicate_run, _ = local_check_runs['duplicate-uid']
    malformed_run, _ = local_check_runs['malformed-uid']

    assert duplicate_run.items[ItemId('U-10')].verdict is Verdict.FAIL
    assert malformed_run.items[ItemId('U-05')].verdict is Verdict.UNKNOWN
    assert malformed_run.items[ItemId('U-10')].verdict is Verdict.UNKNOWN


def test_login_policy_checks_follow_literal_sources_and_profile_directory(
    local_check_runs,
):
    run, _ = local_check_runs['weak-login-policy']

    assert run.items[ItemId('U-12')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-30')].verdict is Verdict.FAIL


def test_login_policy_reports_unfollowed_sources_and_symbolic_umask(local_check_runs):
    run, _ = local_check_runs['incomplete-login-policy']

    assert run.items[ItemId('U-12')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-30')].verdict is Verdict.UNKNOWN


def test_u24_checks_bash_login(local_check_runs):
    run, _ = local_check_runs['bash-login']

    assert run.items[ItemId('U-24')].verdict is Verdict.FAIL


def test_a_known_mode_violation_beats_malformed_sibling_metadata(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            ('/etc/inetd.conf', '# disabled\n'),
            ('/etc/syslog.conf', '*.info /var/log/messages\n'),
        ),
        stats=(
            ('/etc/xinetd.conf', '666 daemon daemon'),
            ('/etc/inetd.conf', 'malformed'),
            ('/etc/syslog.conf', 'malformed'),
        ),
    )
    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-20')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-21')].verdict is Verdict.UNKNOWN


def test_u01_fails_when_ssh_permits_root_login(edge_runs):
    run, _ = edge_runs['malformed_passwd_root_ssh']

    assert run.items[ItemId('U-01')].verdict is Verdict.FAIL


def test_u01_fails_when_a_legacy_remote_login_service_is_active(edge_runs):
    run, _ = edge_runs['legacy_hashes_metadata']

    assert run.items[ItemId('U-01')].verdict is Verdict.FAIL


def test_u01_is_not_applicable_when_remote_login_packages_are_absent(base_runs):
    run, _, _ = base_runs['absent', BASE_DEBIAN]

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.NA
    assert item.facts['reason'] == 'not-installed'


def test_u01_is_unknown_when_effective_sshd_configuration_times_out(edge_runs):
    run, _ = edge_runs['timeout_missing_shadow']

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'timeout'


def test_u01_is_unknown_when_a_package_query_fails(tmp_path: Path):
    host = dataclasses.replace(
        BASE_RHEL, package_error='telnet-server', failure_message='query: not found'
    )

    run, _ = _parsed(tmp_path, host)

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_u30_is_unknown_when_login_defs_sets_an_invalid_umask(tmp_path: Path):
    host = dataclasses.replace(
        BASE_RHEL, login_defs=BASE_RHEL.login_defs + 'UMASK invalid\n'
    )

    run, _ = _parsed(tmp_path, host)

    item = run.items[ItemId('U-30')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_dns_items_are_unknown_when_named_checkconf_fails(tmp_path: Path):
    host = dataclasses.replace(BASE_RHEL, bind_exit=2)

    run, _ = _parsed(tmp_path, host)

    for item_id in ('U-50', 'U-51'):
        assert run.items[ItemId(item_id)].verdict is Verdict.UNKNOWN
        assert run.items[ItemId(item_id)].facts['reason'] == 'incomplete'


def test_u01_is_unknown_when_sshd_omits_permit_root_login(edge_runs):
    run, _ = edge_runs['locked_default_shadow']

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_u01_is_unknown_when_inetd_declares_a_legacy_service(edge_runs):
    run, _ = edge_runs['yescrypt_special_mode']

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_u13_reports_hash_classes_without_reporting_hashes(edge_runs):
    run, result = edge_runs['legacy_hashes_metadata']

    item = run.items[ItemId('U-13')]
    assert item.verdict is Verdict.FAIL
    assert {
        'yescrypt': '1',
        'sha512': '1',
        'sha256': '1',
        'md5': '1',
        'locked': '2',
        'empty': '1',
        'other': '1',
    }.items() <= item.facts.items()
    assert '$y$yescrypt-secret' not in result.stdout + result.stderr
    assert '$6$sha512-secret' not in result.stdout + result.stderr


def test_u13_passes_yescrypt_and_reports_the_login_default(edge_runs):
    run, _ = edge_runs['yescrypt_special_mode']

    item = run.items[ItemId('U-13')]
    assert item.verdict is Verdict.PASS
    assert item.facts['encrypt_method'] == 'YESCRYPT'


def test_u13_is_unknown_when_shadow_cannot_be_read(edge_runs):
    run, _ = edge_runs['timeout_missing_shadow']

    item = run.items[ItemId('U-13')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_u13_counts_a_locked_weak_hash_without_printing_it(edge_runs):
    secret = '!$1$locked-md5-secret'
    run, result = edge_runs['locked_default_shadow']

    item = run.items[ItemId('U-13')]
    assert item.verdict is Verdict.FAIL
    assert item.facts['locked'] == '1'
    assert item.facts['md5'] == '1'
    assert secret not in result.stdout + result.stderr


def test_u18_fails_and_marks_the_debian_default(edge_runs):
    run, _ = edge_runs['locked_default_shadow']

    item = run.items[ItemId('U-18')]
    assert item.verdict is Verdict.FAIL
    assert item.facts['note'] == 'distro-default'


def test_u18_is_unknown_when_shadow_metadata_cannot_be_read(edge_runs):
    run, _ = edge_runs['legacy_hashes_metadata']

    item = run.items[ItemId('U-18')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_u18_rejects_special_permission_bits(edge_runs):
    run, _ = edge_runs['yescrypt_special_mode']

    assert run.items[ItemId('U-18')].verdict is Verdict.FAIL


def test_u18_accepts_no_permission_bits(edge_runs):
    run, _ = edge_runs['many_accounts_zero_mode']

    assert run.items[ItemId('U-18')].verdict is Verdict.PASS


def test_u07_reports_at_most_twenty_login_capable_accounts(edge_runs):
    run, _ = edge_runs['many_accounts_zero_mode']

    item = run.items[ItemId('U-07')]
    assert item.verdict is Verdict.REVIEW
    assert item.facts['login_accounts'] == '23'
    assert len(item.facts['names']) == 20
    assert item.facts['more'] == '3'


def test_u07_is_unknown_when_the_passwd_record_is_malformed(edge_runs):
    run, _ = edge_runs['malformed_passwd_root_ssh']

    item = run.items[ItemId('U-07')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_root_items_are_unknown_when_the_script_is_not_root(edge_runs):
    run, _ = edge_runs['non_root']

    for item_id in (
        'U-01',
        'U-13',
        'U-14',
        'U-15',
        'U-17',
        'U-18',
        'U-23',
        'U-25',
        'U-26',
        'U-33',
        'U-37',
        'U-50',
        'U-51',
        'U-62',
        'U-65',
        'U-67',
    ):
        item = run.items[ItemId(item_id)]
        assert item.verdict is Verdict.UNKNOWN
        assert item.facts['reason'] == 'needs-approval'


def test_u28_requires_approval_to_collect_listeners_when_not_root(edge_runs):
    run, _ = edge_runs['non_root']

    item = run.items[ItemId('U-28')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'needs-approval'


def test_every_item_is_unknown_on_an_unsupported_operating_system(tmp_path: Path):
    host = dataclasses.replace(BASE_DEBIAN, os_release='ID=freebsd\nVERSION_ID=14\n')
    run, _ = _parsed(tmp_path, host)

    assert {item.verdict for item in run.items.values()} == {Verdict.UNKNOWN}
    ordinary = [item for item in run.items.values() if item.id != ItemId('U-60')]
    assert {item.facts['reason'] for item in ordinary} == {'unsupported-os'}
    assert run.items[ItemId('U-60')].facts == {'community': 'unknown'}


def test_postfix_smtp_service_overrides_cannot_bypass_mail_controls(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        installed='postfix',
        active_units='postfix.service',
        files=(
            (
                '/etc/postfix/master.cf',
                (
                    'custom-smtp inet n - y - - smtpd\n'
                    '  -o { smtpd_recipient_restrictions = permit }\n'
                    '  -o { smtpd_relay_restrictions = permit }\n'
                    '  -o { disable_vrfy_command = no }\n'
                ),
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-47')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-48')].verdict is Verdict.FAIL


def test_exim_include_cannot_hide_an_enabled_vrfy_acl(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        installed='exim4-daemon-light',
        active_units='exim4.service',
        files=(
            ('/etc/exim4/exim4.conf', '.include /etc/exim4/unsafe.conf\n'),
            ('/etc/exim4/unsafe.conf', 'acl_smtp_vrfy = accept\n'),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-48')].verdict is Verdict.FAIL


def test_vsftpd_uses_configured_banner_and_user_list_files(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        installed='vsftpd',
        active_units='vsftpd.service',
        files=(
            (
                '/etc/vsftpd.conf',
                (
                    'anonymous_enable=NO\nftpd_banner=Authorized use only\n'
                    'banner_file=/etc/vsftpd/banner\nuserlist_enable=YES\n'
                    'userlist_deny=YES\nuserlist_file=/etc/vsftpd/custom-users\n'
                ),
            ),
            ('/etc/vsftpd/banner', 'vsftpd 3.0\n'),
            ('/etc/vsftpd/custom-users', 'alice\n'),
            ('/etc/vsftpd/user_list', 'root\n'),
            ('/etc/ftpusers', 'nobody\n'),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-53')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-57')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-62')].verdict is Verdict.FAIL


def test_installed_ftp_with_an_unreadable_rule_file_is_unknown(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        installed='vsftpd',
        active_units='vsftpd.service',
        files=(
            (
                '/etc/vsftpd.conf',
                'anonymous_enable=NO\nuserlist_file=/etc/vsftpd/custom-users\n',
            ),
            ('/etc/vsftpd/custom-users', 'root\n'),
        ),
        unreadable=('/etc/vsftpd/custom-users',),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-56')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-56')].facts['reason'] == 'access-denied'


def test_rsyslog_include_counts_omfwd_without_printing_its_target(tmp_path: Path):
    secret_target = 'private.logs.example.test'
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            ('/etc/rsyslog.conf', '$IncludeConfig /etc/rsyslog-extra.conf\n'),
            (
                '/etc/rsyslog-extra.conf',
                f'action(\n target="{secret_target}"\n type="omfwd"\n)\n',
            ),
        ),
    )

    run, result = _parsed(tmp_path, host)

    item = run.items[ItemId('U-66')]
    assert item.facts == {'logging': 'configured', 'destinations': '1', 'remote': 'yes'}
    assert secret_target not in result.stdout


@pytest.mark.parametrize(
    ('files', 'expected'),
    [
        (
            (
                ('/etc/rsyslog.d/remote.conf', '*.* @@logs.example.test\n'),
                ('/etc/rsyslog.d/local.conf', '*.info /var/log/messages\n'),
            ),
            {'logging': 'configured', 'destinations': '3', 'remote': 'yes'},
        ),
        ((), {'logging': 'configured', 'destinations': '1', 'remote': 'no'}),
    ],
    ids=['matching-files', 'empty-glob'],
)
def test_rsyslog_rainerscript_include_with_a_mode_reads_the_globbed_files(
    tmp_path: Path, files: tuple[tuple[str, str], ...], expected: dict[str, str]
):
    rocky_main = (
        '*.info /var/log/messages\n'
        'include(file="/etc/rsyslog.d/*.conf" mode="optional")\n'
    )
    host = dataclasses.replace(
        BASE_RHEL, files=(('/etc/rsyslog.conf', rocky_main), *files)
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-66')].verdict is Verdict.REVIEW
    assert run.items[ItemId('U-66')].facts == expected


@pytest.mark.parametrize(
    ('master_cf', 'unreadable'),
    [
        (
            (
                'custom inet n - y - - smtpd '
                '-o smtpd_relay_restrictions=$unsafe '
                '-o disable_vrfy_command=$unsafe\n'
            ),
            (),
        ),
        ('custom inet n - y - - smtpd\n', ('/etc/postfix/master.cf',)),
    ],
)
def test_unobservable_postfix_service_overrides_are_unknown(
    tmp_path: Path, master_cf: str, unreadable: tuple[str, ...]
):
    host = dataclasses.replace(
        BASE_DEBIAN,
        installed='postfix',
        active_units='postfix.service',
        files=(('/etc/postfix/master.cf', master_cf),),
        unreadable=unreadable,
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-47')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-48')].verdict is Verdict.UNKNOWN


def test_a_failed_pilot_check_does_not_stop_later_items(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        shadow_stat='400 root',
        bind_config='zone "a" { type primary; file "/tmp/a.zone"; allow-transfer { none; }; };',
    )
    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-13')].verdict is Verdict.PASS
    assert run.items[ItemId('U-18')].facts['reason'] == 'check-error'
    assert run.items[ItemId('U-67')].verdict is Verdict.PASS
    assert run.items[ItemId('U-50')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-50')].facts['coverage'] == 'partial'


def test_output_is_complete_and_parses_as_the_protocol(base_runs):
    run, result, _ = base_runs['secured', BASE_DEBIAN]

    assert run.complete
    assert run.os == 'debian-12'
    assert len(run.items) == len(load_registry().run_ids()) == 64
    assert result.stderr == ''


def test_expensive_host_reads_run_once_before_the_item_loop(base_runs):
    _, _, tmp_path = base_runs['secured', BASE_DEBIAN]

    assert (tmp_path / 'calls.log').read_text().splitlines() == [
        'find',
        'find',
        'sshd',
        'named-checkconf',
    ]


@pytest.fixture(scope='module')
def interpretation_runs(tmp_path_factory):
    timesyncd = dataclasses.replace(
        BASE_DEBIAN,
        installed=BASE_DEBIAN.installed.replace('chrony', 'systemd-timesyncd'),
        active_units='sshd.service systemd-timesyncd.service',
        timesync='ServerName=time.example.test\n',
        timedate='NTPSynchronized=yes\n',
    )
    time_files = (
        ('/etc/chrony/chrony.conf', None),
        ('/etc/systemd/timesyncd.conf', '[Time]\nNTP=old.example.test\n'),
        (
            '/etc/systemd/timesyncd.conf.d/local.conf',
            '[Time]\nNTP=\nNTP=time.example.test\n',
        ),
    )
    hosts = {
        'defaults': dataclasses.replace(
            timesyncd,
            passwd=(
                PASSWD
                + 'service:x:2:2:Service:/nonexistent:/bin/false\n'
                + 'sync:x:4:65534:sync:/usr/sbin:/bin/sync\n'
            ),
            stats=(('/usr/sbin', '777 root root'), ('/etc/exports', '644 root root')),
            files=(
                ('/etc/shells', '# /bin/sync\n\n/bin/bash\n  /bin/sh # login\n'),
                ('/etc/exports', '# No shares\n'),
                ('/etc/exports.d/local.exports', '# No shares\n'),
                (
                    '/etc/systemd/timesyncd.conf',
                    '[Time]\n#FallbackNTP=time.example.test\n',
                ),
            ),
            timesync='FallbackNTPServers=time.example.test\nServerName=time.example.test\n',
        ),
        'violations': dataclasses.replace(
            timesyncd,
            passwd=PASSWD + 'bob:x:1001:1001:Bob:/nonexistent:/bin/zsh\n',
            stats=(('/home/alice', '777 root root'), ('/etc/exports', '666 root root')),
            files=(
                ('/etc/shells', '/bin/bash\n/bin/sh\n/bin/zsh\n'),
                ('/etc/exports', '# No shares\n'),
                *time_files,
            ),
            timedate='NTPSynchronized=no\n',
        ),
        'explicit': dataclasses.replace(
            timesyncd,
            files=(
                ('/etc/exports', '# No shares\n'),
                ('/etc/exports.d/local.exports', '/srv/share *(rw)\n'),
                *time_files,
            ),
        ),
    }
    return {
        name: run for name, (run, _) in _parsed_cases(tmp_path_factory, hosts).items()
    }


@pytest.fixture(scope='module')
def account_check_host() -> Host:
    return dataclasses.replace(
        BASE_DEBIAN, installed='', active_units='', loaded_units=''
    )


@pytest.fixture(scope='module')
def root_login_runs(tmp_path_factory, account_check_host: Host):
    cases = {
        'login-path': {'login_path': '/usr/local/sbin:/usr/sbin:/snap/bin'},
        'middle-dot': {'login_path': '/usr/sbin:.:/bin'},
        'leading-empty': {'login_path': ':/bin'},
        'single-dot': {'login_path': '.'},
        'single-empty': {'login_path': ''},
        'trailing-dot-without-timeout': {
            'login_path': '/usr/sbin:/bin:.',
            'has_timeout': False,
        },
        'missing-su': {'login_path': None},
        'failed-su': {'su_exit': 1, 'failure_message': 'su: Permission denied'},
        'timed-out-su': {'su_exit': 124},
        'mixed-startup-output': {
            'login_path': '.:/bin',
            'login_output': 'private-startup-message',
        },
        'missing-markers': {'login_path': '/usr/sbin:/bin', 'path_markers': False},
    }
    hosts = {
        name: dataclasses.replace(account_check_host, **overrides)  # type: ignore[arg-type]
        for name, overrides in cases.items()
    }
    return _parsed_cases(tmp_path_factory, hosts)


@pytest.mark.parametrize(
    ('case', 'verdict', 'facts'),
    [
        ('login-path', Verdict.PASS, {'entries': '3'}),
        ('middle-dot', Verdict.FAIL, {'entries': '3', 'positions': ('2',)}),
        ('leading-empty', Verdict.FAIL, {'entries': '2', 'positions': ('1',)}),
        ('single-dot', Verdict.FAIL, {'entries': '1', 'positions': ('1',)}),
        ('single-empty', Verdict.FAIL, {'entries': '1', 'positions': ('1',)}),
        ('trailing-dot-without-timeout', Verdict.PASS, {'entries': '3'}),
        ('mixed-startup-output', Verdict.FAIL, {'entries': '2', 'positions': ('1',)}),
    ],
)
def test_u14_judges_entries_in_roots_login_path(root_login_runs, case, verdict, facts):
    run, result = root_login_runs[case]

    item = run.items[ItemId('U-14')]
    assert item.verdict is verdict
    assert item.facts == facts
    assert '/snap/bin' not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ('case', 'reason'),
    [
        ('missing-su', 'tool-missing'),
        ('failed-su', 'check-error'),
        ('timed-out-su', 'timeout'),
        ('missing-markers', 'check-error'),
    ],
)
def test_u14_reports_why_the_root_login_path_could_not_be_read(
    root_login_runs, case, reason
):
    run, result = root_login_runs[case]

    item = run.items[ItemId('U-14')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts == {'reason': reason}
    assert 'su: Permission denied' not in result.stdout + result.stderr
    assert 'private-startup-message' not in result.stdout + result.stderr


def test_account_and_home_checks_skip_shells_unlisted_in_etc_shells(
    interpretation_runs,
):
    run = interpretation_runs['defaults']

    for item_id, count in (
        ('U-07', 'login_accounts'),
        ('U-11', 'login_shell_accounts'),
    ):
        item = run.items[ItemId(item_id)]
        assert item.verdict is Verdict.REVIEW
        assert item.facts == {count: '2', 'names': ('root', 'alice'), 'more': '0'}
    for item_id in ('U-31', 'U-32'):
        item = run.items[ItemId(item_id)]
        assert item.verdict is Verdict.PASS
        assert item.facts == {'homes': '2', 'skipped': '3'}


@pytest.mark.parametrize(
    'missing_home', [False, True], ids=['no-violation', 'violation']
)
def test_account_and_home_checks_use_fallback_when_etc_shells_cannot_be_read(
    tmp_path: Path, account_check_host: Host, missing_home
):
    host = dataclasses.replace(
        account_check_host,
        passwd=PASSWD
        + (
            'sync:x:4:65534:sync:/usr/sbin:/bin/sync\n'
            'bob:x:1001:1001:Bob:/nonexistent:/bin/zsh\n'
            if missing_home
            else ''
        ),
        files=(('/etc/shells', None),),
        stats=(('/usr/sbin', '777 root root'),),
    )

    run, _ = _parsed(tmp_path, host)

    for item_id, count in (
        ('U-07', 'login_accounts'),
        ('U-11', 'login_shell_accounts'),
    ):
        item = run.items[ItemId(item_id)]
        assert item.verdict is Verdict.UNKNOWN
        assert item.facts == {
            count: '4' if missing_home else '2',
            'names': ('root', 'alice', 'sync', 'bob')
            if missing_home
            else ('root', 'alice'),
            'more': '0',
            'reason': 'incomplete',
        }
    permissions = run.items[ItemId('U-31')]
    existence = run.items[ItemId('U-32')]
    if missing_home:
        assert permissions.verdict is existence.verdict is Verdict.FAIL
        assert permissions.facts == {'bad_homes': '1', 'skipped': '1'}
        assert existence.facts == {'missing': '1', 'skipped': '1'}
    else:
        assert permissions.verdict is existence.verdict is Verdict.UNKNOWN
        assert (
            permissions.facts
            == existence.facts
            == {
                'skipped': '1',
                'reason': 'incomplete',
            }
        )


def test_home_checks_count_a_double_fault_once_and_report_missing_login_homes(
    interpretation_runs,
):
    run = interpretation_runs['violations']

    assert run.items[ItemId('U-11')].facts['names'] == ('root', 'alice', 'bob')
    permissions = run.items[ItemId('U-31')]
    assert permissions.verdict is Verdict.FAIL
    assert permissions.facts == {'bad_homes': '1', 'skipped': '1'}
    existence = run.items[ItemId('U-32')]
    assert existence.verdict is Verdict.FAIL
    assert existence.facts == {'missing': '1', 'skipped': '1'}


@pytest.mark.parametrize(
    ('case', 'verdict', 'exports', 'unrestricted'),
    [
        ('defaults', Verdict.PASS, '0', '0'),
        ('violations', Verdict.FAIL, '0', '0'),
        ('explicit', Verdict.FAIL, '1', '1'),
    ],
)
def test_u40_checks_export_metadata_even_without_shares(
    interpretation_runs, case, verdict, exports, unrestricted
):
    run = interpretation_runs[case]
    item = run.items[ItemId('U-40')]

    assert item.verdict is verdict
    assert item.facts['exports'] == exports
    assert item.facts['unrestricted'] == unrestricted


@pytest.mark.parametrize(
    ('case', 'verdict', 'selected'),
    [
        ('explicit', Verdict.PASS, '1'),
        ('violations', Verdict.FAIL, '0'),
        ('defaults', Verdict.PASS, '1'),
    ],
)
def test_u65_requires_timesyncd_to_synchronize_with_a_configured_server(
    interpretation_runs, case, verdict, selected
):
    run = interpretation_runs[case]
    item = run.items[ItemId('U-65')]

    assert item.verdict is verdict
    assert item.facts == {'servers': '1', 'selected': selected, 'active': '1'}


def test_script_fits_the_delivery_size_and_line_limits():
    source = SCRIPT.read_bytes()

    assert len(source) <= 63 * 1024  # execute_file takes 64 KB; the rest is headroom
    assert max(map(len, source.splitlines())) <= 200


def test_script_parses_as_posix_shell():
    result = subprocess.run(  # noqa: S603  # repository script syntax check
        ['/bin/sh', '-n', str(SCRIPT)], text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    'shell',
    ['sh', 'bash'] + (['dash'] if shutil.which('dash') else []),
)
def test_script_runs_under_supported_shells(tmp_path: Path, shell: str, base_runs):
    if shell == FAKE_HOST_SHELL:
        run, _, _ = base_runs['secured', BASE_RHEL]
    else:
        run, _ = _parsed(tmp_path, BASE_RHEL, shell)

    assert run.complete
    assert run.os == 'rocky-9.5'


def test_u01_is_unknown_when_a_template_remote_login_service_is_active(edge_runs):
    run, _ = edge_runs['many_accounts_zero_mode']

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'incomplete'


def test_u01_does_not_claim_absence_while_an_ssh_service_is_active(tmp_path: Path):
    host = dataclasses.replace(_absent(BASE_DEBIAN), active_units='sshd.service')

    run, _ = _parsed(tmp_path, host)

    item = run.items[ItemId('U-01')]
    assert item.verdict is Verdict.UNKNOWN
    assert item.facts['reason'] == 'tool-missing'


def test_service_items_do_not_claim_absence_while_their_units_are_loaded(
    tmp_path: Path,
):
    host = dataclasses.replace(_absent(BASE_DEBIAN), loaded_units=LOADED)

    run, _ = _parsed(tmp_path, host)

    for item_id in ('U-34', 'U-35', 'U-48'):
        assert run.items[ItemId(item_id)].verdict is Verdict.PASS
    assert run.items[ItemId('U-65')].verdict is Verdict.FAIL


def test_exim_mail_items_follow_the_live_config_over_its_template(tmp_path: Path):
    host = dataclasses.replace(
        _absent(BASE_DEBIAN),
        loaded_units='exim4.service',
        files=(
            (
                '/etc/exim4/exim4.conf.template',
                'hostlist relay_from_hosts = 127.0.0.1\naccept hosts = +relay_from_hosts\n',
            ),
            (
                '/etc/exim4/exim4.conf',
                'hostlist relay_from_hosts = *\naccept hosts = +relay_from_hosts\nacl_smtp_vrfy = deny\nacl_smtp_expn = deny\n',
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-47')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-48')].verdict is Verdict.PASS


def test_invalid_service_metadata_is_unknown_and_timeout_accepts_inline_comments(
    tmp_path: Path,
):
    host = dataclasses.replace(
        BASE_DEBIAN,
        shadow_stat='invalid root root',
        active_units='sshd.service chronyd.service rsh.service',
        walk='f\t600\troot\troot\t0\t0\t{R}/var/log/auth.log\nf\t666\troot\troot\t0\t0\t{R}/etc/rc.d/init.d/unsafe\n',
        files=(
            ('/etc/rc.d/init.d/unsafe', '#!/bin/sh\n'),
            (
                '/etc/profile',
                'TMOUT=600 # policy\nexport TMOUT\numask 022\nPATH=/usr/bin:/bin\n',
            ),
            ('/etc/hosts.equiv', 'trusted alice\n'),
            ('/etc/exports', '/srv/data 192.0.2.10(rw,anonuid=1000)\n'),
        ),
        stats=(
            ('/etc/rc.d/init.d/unsafe', '666 root root'),
            ('/etc/xinetd.conf', 'invalid root root'),
            ('/etc/hosts.equiv', 'invalid root root'),
            ('/etc/exports', 'invalid root root'),
        ),
    )

    run, result = _parsed(tmp_path, host)

    assert run.items[ItemId('U-17')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-12')].verdict is Verdict.PASS
    assert run.items[ItemId('U-35')].verdict is Verdict.FAIL
    for item_id in ('U-18', 'U-20', 'U-27', 'U-40'):
        assert run.items[ItemId(item_id)].verdict is Verdict.UNKNOWN
        assert run.items[ItemId(item_id)].facts['reason'] == 'incomplete'
    assert result.stderr == ''


def _network_rules_host(
    *,
    echo_socket: bool,
    postfix: str | None,
    export_client: str,
    snmpd: str,
    bind_config: str | None,
) -> Host:
    acl = 'version "Authorized use only";\nallow-transfer { 192.0.2.1; any; };\nallow-update {\n192.0.2.1;\nany;\n};\n'
    return dataclasses.replace(
        BASE_DEBIAN,
        active_units='sshd.service chronyd.service'
        + (' echo.socket' if echo_socket else ''),
        passwd=BASE_DEBIAN.passwd + 'ftp:x:50:50:FTP:/srv/ftp:\n',
        installed=BASE_DEBIAN.installed + ' proftpd-core sendmail-bin',
        shadow_stat='400 daemon root',
        files=(
            ('/etc/xinetd.conf', 'defaults { }\nincludedir /etc/xinetd.d\n'),
            (
                '/etc/xinetd.d/custom-services',
                'service echo\n{\ndisable = '
                + ('yes' if echo_socket else 'no')
                + '\n}\nservice discard { disable = yes }\n',
            ),
            (
                '/etc/vsftpd/vsftpd.conf',
                'anonymous_enable=NO\nftpd_banner=Authorized use only\nuserlist_enable=NO\n',
            ),
            ('/etc/postfix/main.cf', postfix),
            ('/etc/exports', f'/srv/share {export_client}(ro)\n'),
            (
                '/etc/mail/sendmail.cf',
                'O PrivacyOptions=restrictqrun,noexpn,novrfy\nO SmtpGreetingMessage=Authorized use only\n',
            ),
            ('/etc/exim4/exim4.conf.template', 'relay_from_hosts = 127.0.0.1\n'),
            ('/etc/exim4/exim4.conf', 'acl_smtp_vrfy = deny\nacl_smtp_expn = deny\n'),
            ('/etc/named.conf', acl),
            ('/etc/bind/named.conf.options', acl),
            ('/etc/snmp/snmpd.conf', snmpd),
        ),
        bind_config=bind_config,
        stats=(('/usr/sbin/postsuper', 'invalid root root'),),
    )


def _bind_acl_host(acl: str) -> Host:
    return dataclasses.replace(
        BASE_DEBIAN, bind_config=f'options {{ allow-transfer {{ "{acl}"; }}; }};'
    )


@pytest.fixture(scope='module')
def network_runs(tmp_path_factory):
    return _parsed_cases(
        tmp_path_factory,
        {
            'xinetd-echo': _network_rules_host(
                echo_socket=False,
                postfix=None,
                export_client='192.0.2.0/24',
                snmpd='rouser monitor authPriv\nrocommunity6 public default\n',
                bind_config='options { allow-transfer { none; }; allow-update { none; }; };\nzone "safe" { type master; file "safe.db"; allow-transfer { none; }; };\nzone "open" { type master; file "open.db"; allow-transfer { any; }; allow-update { any; }; };\n',
            ),
            'socket-echo': _network_rules_host(
                echo_socket=True,
                postfix='mynetworks = 0.0.0.0/0\nsmtpd_recipient_restrictions = permit_mynetworks,\n reject_unauth_destination\ndisable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
                export_client='0.0.0.0/0',
                snmpd='rocommunity "Abc def12!" 0.0.0.0/0.0.0.0\n',
                bind_config=None,
            ),
            'bind-acl-none': _bind_acl_host('none'),
            'bind-acl-any': _bind_acl_host('any'),
        },
    )


@pytest.mark.parametrize('case', ['xinetd-echo', 'socket-echo'])
def test_global_network_rules_and_hidden_services_cannot_pass(network_runs, case: str):
    run, result = network_runs[case]

    for item_id in ('U-18', 'U-38', 'U-50', 'U-51', 'U-55', 'U-59', 'U-61'):
        assert run.items[ItemId(item_id)].verdict is Verdict.FAIL
    for item_id in ('U-35', 'U-53', 'U-57'):
        assert run.items[ItemId(item_id)].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-46')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-46')].facts['reason'] == 'incomplete'
    assert 'Abc def12!' not in result.stdout + result.stderr
    assert result.stderr == ''


@pytest.mark.parametrize(
    ('case', 'verdict'),
    [('xinetd-echo', Verdict.PASS), ('socket-echo', Verdict.FAIL)],
)
def test_u40_fails_only_an_export_open_to_every_host(
    network_runs, case: str, verdict: Verdict
):
    run, _ = network_runs[case]

    assert run.items[ItemId('U-40')].verdict is verdict


def test_postfix_mail_items_are_unknown_without_its_main_config(network_runs):
    run, _ = network_runs['xinetd-echo']

    assert run.items[ItemId('U-47')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-48')].verdict is Verdict.UNKNOWN


def test_postfix_open_mynetworks_fails_relay_while_disabled_vrfy_passes(
    network_runs,
):
    run, _ = network_runs['socket-echo']

    assert run.items[ItemId('U-47')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-48')].verdict is Verdict.PASS


@pytest.mark.parametrize(
    ('case', 'verdict'),
    [('socket-echo', Verdict.PASS), ('xinetd-echo', Verdict.FAIL)],
)
def test_u60_passes_a_strong_community_and_fails_public(
    network_runs, case: str, verdict: Verdict
):
    run, _ = network_runs[case]

    assert run.items[ItemId('U-60')].verdict is verdict


FAILURE_SECRET = 'failure-secret-marker'


def _read_failure_host(reason: str) -> Host:
    message = (
        ('Permission denied' if reason == 'access-denied' else 'query: not found')
        + ' '
        + FAILURE_SECRET
    )
    return dataclasses.replace(
        BASE_RHEL,
        failure_message=message,
        package_error='telnet-server',
        stat_exit=2 if reason == 'access-denied' else 127,
        walk_exit=2 if reason == 'access-denied' else 127,
        bind_exit=2 if reason == 'access-denied' else 127,
        query_exit=2 if reason == 'access-denied' else 127,
    )


def _mail_relay_host(implementation: str) -> Host:
    path = (
        '/etc/postfix/main.cf' if implementation == 'postfix' else '/etc/exim/exim.conf'
    )
    config = (
        'smtpd_relay_restrictions = permit\nsmtpd_recipient_restrictions = permit, reject_unauth_destination\n'
        if implementation == 'postfix'
        else 'hostlist relay_from_hosts = 127.0.0.1\n'
    )
    return dataclasses.replace(
        BASE_RHEL,
        installed=BASE_RHEL.installed + (' exim' if implementation == 'exim' else ''),
        files=((path, config),),
    )


@pytest.fixture(scope='module')
def mail_and_read_runs(tmp_path_factory):
    return _parsed_cases(
        tmp_path_factory,
        {
            'access-denied': _read_failure_host('access-denied'),
            'tool-missing': _read_failure_host('tool-missing'),
            'postfix': _mail_relay_host('postfix'),
            'exim': _mail_relay_host('exim'),
        },
    )


@pytest.mark.parametrize('reason', ['access-denied', 'tool-missing'])
def test_read_failures_report_the_observed_cause_without_leaking_errors(
    mail_and_read_runs, reason: str
):
    run, result = mail_and_read_runs[reason]

    for item_id in ('U-01', 'U-15', 'U-17', 'U-18', 'U-50', 'U-51'):
        assert run.items[ItemId(item_id)].verdict is Verdict.UNKNOWN
        assert run.items[ItemId(item_id)].facts['reason'] == reason
    assert result.stderr == ''
    assert FAILURE_SECRET not in result.stdout + result.stderr


@pytest.mark.parametrize('implementation', ['postfix', 'exim'])
def test_mail_relay_requires_an_effective_restriction(
    mail_and_read_runs, implementation: str
):
    run, _ = mail_and_read_runs[implementation]

    assert run.items[ItemId('U-47')].verdict is Verdict.FAIL


@pytest.mark.skipif(os.geteuid() == 0, reason='A real root process can bypass mode 000')
@pytest.mark.parametrize(
    ('uid', 'reason'), [(0, 'access-denied'), (1000, 'needs-approval')]
)
def test_unreadable_os_identity_reports_the_read_failure(
    tmp_path: Path, uid: int, reason: str
):
    host = dataclasses.replace(BASE_DEBIAN, os_mode=0, uid=uid)

    run, result = _parsed(tmp_path, host)

    assert run.family == 'unknown'
    for item_id, item in run.items.items():
        assert item.verdict is Verdict.UNKNOWN
        assert item.facts == (
            {'community': 'unknown'}
            if item_id == ItemId('U-60')
            else {'reason': reason}
        )
    assert result.stderr == ''
    assert not (tmp_path / 'calls.log').exists()


def _ubuntu_rsh_host(inetd_conf: str) -> Host:
    return dataclasses.replace(
        BASE_DEBIAN,
        installed='openssh-server openbsd-inetd rsh-redone-server',
        active_units='sshd.service openbsd-inetd.service',
        loaded_units='',
        inetd_conf=inetd_conf,
        files=(('/etc/hosts.equiv', ''),),
        stats=(('/etc/hosts.equiv', '644 root root'),),
    )


@pytest.fixture(scope='module')
def ubuntu_service_runs(tmp_path_factory):
    return _parsed_cases(
        tmp_path_factory,
        {
            'telnet-disabled': dataclasses.replace(
                BASE_DEBIAN,
                installed='openssh-server inetutils-telnetd',
                loaded_units='',
            ),
            'tftp-active': dataclasses.replace(
                BASE_DEBIAN,
                installed='openssh-server tftpd-hpa',
                active_units='tftpd-hpa.service',
            ),
            'disabled': _ubuntu_rsh_host(''),
            'inetd-active': _ubuntu_rsh_host(
                'shell stream tcp nowait root /usr/sbin/in.rshd in.rshd\n'
            ),
        },
    )


def test_ubuntu_reports_installed_but_disabled_telnet(ubuntu_service_runs):
    run, _ = ubuntu_service_runs['telnet-disabled']

    assert run.items[ItemId('U-52')].verdict is Verdict.PASS
    assert run.items[ItemId('U-27')].verdict is Verdict.NA
    assert run.items[ItemId('U-36')].verdict is Verdict.NA


def test_ubuntu_reports_the_active_tftpd_hpa_service(ubuntu_service_runs):
    run, _ = ubuntu_service_runs['tftp-active']

    assert run.items[ItemId('U-44')].verdict is Verdict.FAIL


@pytest.mark.parametrize(
    ('acl', 'verdict'), [('none', Verdict.PASS), ('any', Verdict.FAIL)]
)
def test_bind_checks_quoted_builtin_acl_names(network_runs, acl: str, verdict: Verdict):
    run, _ = network_runs[f'bind-acl-{acl}']

    assert run.items[ItemId('U-50')].verdict is verdict


def test_ftp_deny_list_without_root_is_a_violation_under_dash(tmp_path: Path):
    if shutil.which('dash') is None:
        pytest.skip('dash is required to exercise POSIX errexit')
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            ('/etc/vsftpd.conf', 'userlist_enable=YES\nuserlist_deny=YES\n'),
            ('/etc/vsftpd.user_list', 'nobody\n'),
            ('/etc/ftpusers', 'nobody\n'),
        ),
    )
    run, _ = _parsed(tmp_path, host, 'dash')

    assert run.items[ItemId('U-57')].verdict is Verdict.FAIL


@pytest.mark.parametrize(
    ('case', 'verdict'),
    [
        pytest.param('disabled', Verdict.PASS, id='disabled'),
        pytest.param('inetd-active', Verdict.FAIL, id='inetd-active'),
    ],
)
def test_ubuntu_judges_rsh_redone_and_its_inetd_configuration(
    ubuntu_service_runs, case: str, verdict: Verdict
):
    run, _ = ubuntu_service_runs[case]

    assert run.items[ItemId('U-27')].verdict is verdict
    assert run.items[ItemId('U-36')].verdict is verdict


def test_ssh_match_overrides_in_included_files_are_violations(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        sshd_exit=2,
        files=(
            (
                '/etc/ssh/sshd_config',
                'PermitRootLogin no\nBanner /etc/issue.net\nInclude /etc/ssh/sshd_config.d/*.conf\n',
            ),
            (
                '/etc/ssh/sshd_config.d/restricted.conf',
                'Match Address 192.0.2.0/24\nPermitRootLogin yes\nBanner none\n',
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-01')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-62')].verdict is Verdict.FAIL


def test_samba_include_cannot_hide_an_anonymous_share(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/samba/smb.conf',
                'guest ok = no\ninclude = /etc/samba/shares.conf\n',
            ),
            ('/etc/samba/shares.conf', '[public]\nguest ok = yes\n'),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-35')].verdict is Verdict.FAIL


def test_snmp_includes_and_com2sec_context_options_are_judged(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/snmp/snmpd.conf',
                'rouser monitor authPriv\nincludeDir /etc/snmp/snmpd.conf.d\n',
            ),
            (
                '/etc/snmp/snmpd.conf.d/community.conf',
                'com2sec -Cn ctx local default public\n',
            ),
        ),
    )

    run, result = _parsed(tmp_path, host)

    for item_id in ('U-59', 'U-60', 'U-61'):
        assert run.items[ItemId(item_id)].verdict is Verdict.FAIL
    assert 'public' not in result.stdout + result.stderr


def test_unfollowable_service_includes_make_clean_results_unknown(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/ssh/sshd_config',
                'PermitRootLogin no\nBanner /etc/issue.net\nInclude /etc/ssh/missing.conf\n',
            ),
            (
                '/etc/samba/smb.conf',
                'guest ok = no\ninclude = /etc/samba/missing.conf\n',
            ),
            (
                '/etc/snmp/snmpd.conf',
                'includeFile /etc/snmp/missing.conf\n',
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    for item_id in ('U-01', 'U-35', 'U-59', 'U-61', 'U-62'):
        assert run.items[ItemId(item_id)].verdict is Verdict.UNKNOWN
        assert run.items[ItemId(item_id)].facts['reason'] == 'incomplete'
    assert run.items[ItemId('U-60')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-60')].facts == {'community': 'unknown'}


def test_known_service_violations_beat_unfollowable_includes(tmp_path: Path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/ssh/sshd_config',
                'Include /etc/ssh/missing.conf\nMatch User root\nPermitRootLogin yes\nBanner none\n',
            ),
            (
                '/etc/samba/smb.conf',
                'include = /etc/samba/missing.conf\nguest ok = yes\n',
            ),
            (
                '/etc/snmp/snmpd.conf',
                'includeFile /etc/snmp/missing.conf\ncom2sec local default public\n',
            ),
        ),
    )

    run, result = _parsed(tmp_path, host)

    for item_id in ('U-01', 'U-35', 'U-59', 'U-60', 'U-61', 'U-62'):
        assert run.items[ItemId(item_id)].verdict is Verdict.FAIL
    assert 'public' not in result.stdout + result.stderr


@pytest.fixture(scope='module')
def mixed_service_run(tmp_path_factory):
    local = '/etc/systemd/system/example.service'
    vendor_units = (
        '/usr/lib/systemd/system/vendor.service',
        '/lib/systemd/system/legacy.service',
    )
    host = dataclasses.replace(
        BASE_DEBIAN,
        installed='openssh-server',
        loaded_units='',
        unit_states='autofs.service:reloading telnet@pts-0.service:deactivating tftp@entry.socket:activating',
        enabled_units='vendor.service legacy.service',
        inetd_conf='shell stream tcp nowait root /usr/sbin/in.rshd in.rshd\n',
        files=(
            ('/etc/hosts.equiv', '+\n'),
            ('/etc/xinetd.conf', 'defaults { }\nincludedir /etc/custom-inetd\n'),
            ('/etc/custom-inetd/finger', 'service finger { disable = no }\n'),
            *((path, '[Service]\nExecStart=/bin/true\n') for path in vendor_units),
        ),
        stats=tuple((path, '664 root staff') for path in (local, *vendor_units)),
    )
    return _parsed(tmp_path_factory.mktemp('mixed-services'), host)[0]


def test_running_service_states_and_template_sockets_are_active(mixed_service_run):
    assert [
        mixed_service_run.items[ItemId(item)].verdict
        for item in ('U-41', 'U-44', 'U-52')
    ] == [
        Verdict.FAIL,
        Verdict.FAIL,
        Verdict.FAIL,
    ]


def test_local_and_enabled_vendor_startup_units_reject_group_write(mixed_service_run):
    item = mixed_service_run.items[ItemId('U-17')]

    assert item.verdict is Verdict.FAIL
    assert item.facts == {'startup_files': '3'}


def test_enabled_inetd_entry_prevents_not_installed_and_checks_trust_files(
    mixed_service_run,
):
    assert mixed_service_run.items[ItemId('U-27')].verdict is Verdict.FAIL


def test_xinetd_follows_includedir_outside_the_default_location(mixed_service_run):
    assert mixed_service_run.items[ItemId('U-34')].verdict is Verdict.FAIL


@pytest.fixture(scope='module')
def filesystem_run(tmp_path_factory):
    passwd = (
        PASSWD
        + 'a,b%z\x1b:x:1001:1000:Test:/home/alice:/bin/sh\nftp:x:1002:1000:FTP:/home/ftp:/bin/\tsh\x7f\n'
    )
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            ('/real/passwd', passwd),
            ('/real/job', 'job\n'),
            ('/real/log', 'log\n'),
            ('/etc/crontab', '# Cron jobs\n'),
        ),
        links=(
            ('/etc/passwd', '/real/passwd'),
            ('/etc/shadow', '/absent'),
            ('/etc/hosts.lpd', '/etc/hosts.lpd'),
            ('/etc/cron.d/job', '/real/job'),
            ('/var/log/app.log', '/real/log'),
        ),
        stats=(
            ('/real/passwd', '644 root root'),
            ('/real/job', '666 root root'),
            ('/real/log', '666 root root'),
        ),
        walk=(
            'l\t777\troot\troot\t0\t0\t{R}/etc/cron.d/job\n'
            'l\t777\troot\troot\t0\t0\t{R}/var/log/app.log\n'
            'f\t666\troot\troot\t0\t0\t{R}/etc/crontab\n'
        ),
        unreadable_dirs=('/etc/exports.d',),
    )
    directory = tmp_path_factory.mktemp('file-observations')
    try:
        return _parsed(directory, host)
    finally:
        (directory / 'host/etc/exports.d').chmod(0o700)


def test_cron_checks_both_crontab_and_linked_job_permissions(filesystem_run):
    run, _ = filesystem_run

    assert run.items[ItemId('U-37')].verdict is Verdict.FAIL
    assert run.items[ItemId('U-37')].facts == {'bad': '2'}


def test_file_checks_judge_symlink_targets_and_report_broken_links(filesystem_run):
    run, _ = filesystem_run

    assert {
        item: run.items[ItemId(item)].verdict
        for item in ('U-16', 'U-18', 'U-29', 'U-67')
    } == {
        'U-16': Verdict.PASS,
        'U-18': Verdict.UNKNOWN,
        'U-29': Verdict.UNKNOWN,
        'U-67': Verdict.FAIL,
    }


def test_unlistable_export_directory_makes_the_result_unknown(filesystem_run):
    run, _ = filesystem_run

    assert run.items[ItemId('U-40')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-40')].facts['reason'] == 'access-denied'


def test_evidence_encodes_control_bytes_and_preserves_list_elements(filesystem_run):
    run, result = filesystem_run

    assert run.items[ItemId('U-07')].facts['names'] == ('root', 'alice', 'a,b%z\x1b')
    assert 'names=root%2Calice%2Ca%252Cb%2525z%251B ' in result.stdout
    assert 'shell=/bin/%09sh%7F' in result.stdout


def test_login_policy_handles_repeated_and_dynamic_sources_and_weak_umask(tmp_path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/profile',
                '. /opt/login.sh\n. /opt/login.sh\n. "$i"\numask 000; export X=1\n',
            ),
            ('/opt/login.sh', 'export TMOUT=600\n'),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert (run.items[ItemId('U-12')].verdict, run.items[ItemId('U-30')].verdict) == (
        Verdict.PASS,
        Verdict.FAIL,
    )


def test_unrelated_pam_module_arguments_do_not_override_password_checks(tmp_path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/pam.d/common-password',
                (
                    'password requisite pam_pwquality.so minlen=6 enforce_for_root\n'
                    'password required pam_pwhistory.so remember=4\n'
                    'password required pam_unix.so minlen=8\n'
                ),
            ),
            ('/etc/security/faillock.conf', 'deny=20\n'),
            (
                '/etc/pam.d/common-auth',
                'auth required pam_faillock.so\nauth required pam_exec.so deny=5\n',
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert (run.items[ItemId('U-02')].verdict, run.items[ItemId('U-03')].verdict) == (
        Verdict.FAIL,
        Verdict.FAIL,
    )


def test_unreadable_include_globs_and_dangling_rules_are_unknown(tmp_path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        unreadable_dirs=('/etc/ssh/blocked',),
        links=(
            ('/home/alice/.bash_login', '/missing'),
            ('/etc/hosts.allow', '/missing'),
        ),
        files=(
            (
                '/etc/ssh/sshd_config',
                'Include /etc/ssh/blocked/*.conf\nPermitRootLogin no\n',
            ),
            (
                '/etc/ssh/blocked/settings.conf',
                'Match User root\nPermitRootLogin yes\nBanner none\n',
            ),
        ),
    )

    try:
        run, _ = _parsed(tmp_path, host)
    finally:
        (tmp_path / 'host/etc/ssh/blocked').chmod(0o700)

    assert [
        run.items[ItemId(item)].verdict for item in ('U-01', 'U-24', 'U-56', 'U-62')
    ] == [
        Verdict.UNKNOWN,
        Verdict.UNKNOWN,
        Verdict.UNKNOWN,
        Verdict.UNKNOWN,
    ]
    assert run.items[ItemId('U-01')].facts == {'reason': 'access-denied'}
    assert run.items[ItemId('U-62')].facts == {'reason': 'access-denied'}


def test_mail_settings_overridden_by_every_smtp_service_use_effective_values(tmp_path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/postfix/main.cf',
                'disable_vrfy_command = no\nsmtpd_relay_restrictions = permit\n',
            ),
            (
                '/etc/postfix/master.cf',
                (
                    'submission inet n - y - - smtpd\n'
                    '  -o disable_vrfy_command=yes\n'
                    '  -o smtpd_relay_restrictions=reject_unauth_destination\n'
                ),
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert (run.items[ItemId('U-47')].verdict, run.items[ItemId('U-48')].verdict) == (
        Verdict.PASS,
        Verdict.PASS,
    )


def test_missing_configured_vsftpd_user_list_is_unknown(tmp_path):
    host = dataclasses.replace(
        BASE_DEBIAN,
        files=(
            (
                '/etc/vsftpd.conf',
                'userlist_enable=YES\nuserlist_deny=YES\nuserlist_file=/etc/vsftpd/missing\n',
            ),
        ),
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-56')].verdict is Verdict.UNKNOWN
    assert run.items[ItemId('U-57')].verdict is Verdict.UNKNOWN


@pytest.mark.parametrize(
    ('implementation', 'files', 'expected'),
    [
        (
            'postfix',
            (
                (
                    '/etc/postfix/master.cf',
                    'smtp inet n - y - - smtpd -o smtpd_banner=\n',
                ),
            ),
            Verdict.FAIL,
        ),
        (
            'exim4-daemon-light',
            (
                ('/etc/exim4/exim4.conf', '.include /etc/exim4/banner.conf\n'),
                ('/etc/exim4/banner.conf', 'smtp_banner = Authorized use only\n'),
            ),
            Verdict.PASS,
        ),
    ],
)
def test_smtp_login_banners_use_effective_postfix_and_exim_settings(
    tmp_path, implementation, files, expected
):
    host = dataclasses.replace(
        BASE_DEBIAN, installed=f'openssh-server {implementation}', files=files
    )

    run, _ = _parsed(tmp_path, host)

    assert run.items[ItemId('U-62')].verdict is expected


def _debian(**overrides) -> Host:
    return dataclasses.replace(BASE_DEBIAN, **overrides)


PROFTPD_INSTALLED = DEBIAN_INSTALLED + ' proftpd-core'
VSFTPD_BASE = 'anonymous_enable=NO\nftpd_banner=Authorized use only\n'


@pytest.fixture(scope='module')
def config_semantics_runs(tmp_path_factory):
    hosts = {
        'nfs-world-options': _debian(files=(('/etc/exports', '/srv (rw)\n'),)),
        'nfs-no-client': _debian(files=(('/etc/exports', '/srv\n'),)),
        'proftpd-default-ident': _debian(
            installed=PROFTPD_INSTALLED,
            files=(('/etc/proftpd/proftpd.conf', 'ServerIdent on\n'),),
        ),
        'proftpd-included': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                (
                    '/etc/proftpd/proftpd.conf',
                    'ServerIdent on "Authorized use only"\nRootLogin off\nInclude /etc/proftpd/conf.d/\n',
                ),
                ('/etc/proftpd/conf.d/anonymous', '<Anonymous ~ftp>\n</Anonymous>\n'),
            ),
        ),
        'proftpd-without-ftpusers': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                ('/etc/proftpd/proftpd.conf', 'ServerIdent off\nUseFtpUsers off\n'),
            ),
        ),
        'sendmail': _debian(installed=DEBIAN_INSTALLED + ' sendmail-bin'),
        'sendmail-default-greeting': _debian(
            installed=DEBIAN_INSTALLED + ' sendmail-bin',
            files=(
                (
                    '/etc/mail/sendmail.cf',
                    'O PrivacyOptions=goaway,restrictqrun\nO SmtpGreetingMessage=$j Sendmail $v/$Z; $b\n',
                ),
            ),
        ),
        'held-telnetd': _debian(
            installed=DEBIAN_INSTALLED.replace('telnetd ', ''), held='telnetd'
        ),
        'vsftpd-deny-only': _debian(
            files=(('/etc/vsftpd.conf', VSFTPD_BASE + 'userlist_deny=YES\n'),)
        ),
        'vsftpd-allowlist': _debian(
            files=(
                (
                    '/etc/vsftpd.conf',
                    VSFTPD_BASE + 'userlist_enable=YES\nuserlist_deny=NO\n',
                ),
                ('/etc/vsftpd.user_list', 'alice\n'),
            )
        ),
        'samba-commented-guest': _debian(
            files=(('/etc/samba/smb.conf', '[share]\n;   guest ok = yes\n'),)
        ),
        'samba-public': _debian(
            files=(('/etc/samba/smb.conf', '[share]\npublic = yes\n'),)
        ),
        'chrony-sourcedir': _debian(
            files=(
                ('/etc/chrony/chrony.conf', 'sourcedir /etc/chrony/sources.d\n'),
                (
                    '/etc/chrony/sources.d/pool.sources',
                    'pool pool.example.test iburst\n',
                ),
            )
        ),
        'ntpsec': _debian(
            installed=DEBIAN_INSTALLED.replace('chrony', 'ntpsec'),
            active_units='sshd.service ntpsec.service',
            files=(
                ('/etc/chrony/chrony.conf', None),
                ('/etc/ntpsec/ntp.conf', 'server time.example.test iburst\n'),
            ),
        ),
        'time-unit-error': _debian(
            active_units='sshd.service', systemctl_error='chronyd.service'
        ),
        'postfix-default-relay': _debian(
            files=(
                (
                    '/etc/postfix/main.cf',
                    'disable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
                ),
            )
        ),
        'faillock-default-deny': dataclasses.replace(
            BASE_RHEL,
            files=(
                (
                    '/etc/pam.d/system-auth',
                    'auth required pam_faillock.so preauth\nauth [default=die] pam_faillock.so authfail\naccount required pam_faillock.so\npassword requisite pam_pwquality.so enforce_for_root\npassword required pam_pwhistory.so remember=4\npassword required pam_unix.so\n',
                ),
            ),
        ),
        'pam-tab-arguments': _debian(
            files=(
                ('/etc/security/pwquality.conf', None),
                (
                    '/etc/pam.d/common-password',
                    'password requisite pam_pwquality.so minlen=8\tdcredit=-1\tucredit=-1\tlcredit=-1\tocredit=-1\tenforce_for_root\npassword required pam_pwhistory.so remember=4\npassword required pam_unix.so\n',
                ),
            )
        ),
        'pwquality-drop-in': _debian(
            files=(
                (
                    '/etc/security/pwquality.conf',
                    'minlen=8\nucredit=-1\nlcredit=-1\nocredit=-1\nenforce_for_root\n',
                ),
                (
                    '/etc/security/pwquality.conf.d/50-local.conf',
                    'minlen=7\ndcredit=-1\n',
                ),
            )
        ),
        'rhosts-fifo': _debian(
            active_units='sshd.service chronyd.service rsh.socket',
            fifos=('/home/alice/.rhosts',),
        ),
        'forged-walk-record': _debian(
            walk=(
                'd\t755\talice\talice\t1000\t1000\t{R}/tmp/x\n'
                'f\t600\troot\troot\t0\t0\t{R}/var/log/auth.log\n'
                'f\t666\troot\troot\t0\t0\t{R}/var/log/auth.log\n'
            )
        ),
        'nfs-default-options-only': _debian(files=(('/etc/exports', '/srv -rw\n'),)),
        'nfs-quoted-path-no-client': _debian(
            files=(('/etc/exports', '"/srv/my share"\n'),)
        ),
        'proftpd-boolean-no': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                (
                    '/etc/proftpd/proftpd.conf',
                    'ServerIdent off\nUseFtpUsers no\nRootLogin on\n',
                ),
            ),
        ),
        'proftpd-included-root-login': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                (
                    '/etc/proftpd/proftpd.conf',
                    'ServerIdent off\nInclude /etc/proftpd/conf.d/\n',
                ),
                ('/etc/proftpd/conf.d/root', 'RootLogin on\n'),
            ),
        ),
        'proftpd-virtual-host-root-login': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                (
                    '/etc/proftpd/proftpd.conf',
                    'ServerIdent off\n<VirtualHost 192.0.2.1>\nRootLogin on\n</VirtualHost>\nRootLogin off\n',
                ),
            ),
        ),
        'proftpd-missing-include': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                (
                    '/etc/proftpd/proftpd.conf',
                    'ServerIdent off\nInclude /etc/proftpd/absent.conf\n',
                ),
            ),
        ),
        'proftpd-ident-variable': _debian(
            installed=PROFTPD_INSTALLED,
            files=(('/etc/proftpd/proftpd.conf', 'ServerIdent on "%L ready"\n'),),
        ),
        'proftpd-ident-reenabled': _debian(
            installed=PROFTPD_INSTALLED,
            files=(('/etc/proftpd/proftpd.conf', 'ServerIdent off\nServerIdent on\n'),),
        ),
        'proftpd-included-login-banner': _debian(
            installed=PROFTPD_INSTALLED,
            files=(
                (
                    '/etc/proftpd/proftpd.conf',
                    'ServerIdent off\nInclude /etc/proftpd/conf.d/\n',
                ),
                (
                    '/etc/proftpd/conf.d/banner',
                    'DisplayLogin /etc/proftpd/welcome.msg\n',
                ),
                ('/etc/proftpd/welcome.msg', 'Authorized use only\n'),
            ),
        ),
        'samba-guest-on': _debian(
            files=(('/etc/samba/smb.conf', '[share]\nguest ok = on\n'),)
        ),
        'samba-public-one': _debian(
            files=(('/etc/samba/smb.conf', '[share]\npublic = 1\n'),)
        ),
        'sendmail-version-macro': _debian(
            installed=DEBIAN_INSTALLED + ' sendmail-bin',
            files=(
                (
                    '/etc/mail/sendmail.cf',
                    'O PrivacyOptions=goaway,restrictqrun\nO SmtpGreetingMessage=$j $Z ready\n',
                ),
            ),
        ),
        'postfix-relay-gate-closes-open-recipient': _debian(
            files=(
                (
                    '/etc/postfix/main.cf',
                    'smtpd_relay_restrictions = permit\nsmtpd_recipient_restrictions = reject_unauth_destination\ndisable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
                ),
            )
        ),
        'postfix-submission-rejects-the-rest': _debian(
            files=(
                (
                    '/etc/postfix/main.cf',
                    'disable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
                ),
                (
                    '/etc/postfix/master.cf',
                    'submission inet n - y - - smtpd\n  -o smtpd_relay_restrictions=permit_sasl_authenticated,reject\n',
                ),
            )
        ),
        'chrony-unreadable-source': _debian(
            files=(
                ('/etc/chrony/chrony.conf', 'sourcedir /etc/chrony/sources.d\n'),
                (
                    '/etc/chrony/sources.d/pool.sources',
                    'pool pool.example.test iburst\n',
                ),
            ),
            unreadable=('/etc/chrony/sources.d/pool.sources',),
        ),
        'chrony-second-confdir': _debian(
            files=(
                ('/etc/chrony/chrony.conf', 'confdir /etc/chrony/a /etc/chrony/b\n'),
                ('/etc/chrony/b/pool.conf', 'pool pool.example.test iburst\n'),
            )
        ),
        'vsftpd-boolean-words': _debian(
            files=(
                (
                    '/etc/vsftpd.conf',
                    VSFTPD_BASE + 'userlist_enable=TRUE\nuserlist_deny=0\n',
                ),
                ('/etc/vsftpd.user_list', 'alice\n'),
            )
        ),
        'hosts-equiv-fifo': _debian(
            active_units='sshd.service chronyd.service rsh.socket',
            fifos=('/etc/hosts.equiv',),
        ),
        'rhosts-symlink': _debian(
            active_units='sshd.service chronyd.service rsh.socket',
            files=(('/real/rhosts', 'trusted.example.test\n'),),
            links=(('/home/alice/.rhosts', '/real/rhosts'),),
            stats=(('/real/rhosts', '600 alice alice'),),
        ),
        'postfix-warn-only-relay': _debian(
            files=(
                (
                    '/etc/postfix/main.cf',
                    'smtpd_relay_restrictions = warn_if_reject reject_unauth_destination\nsmtpd_recipient_restrictions = permit_mynetworks\ndisable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
                ),
            )
        ),
        'postfix-reject-then-permit': _debian(
            files=(
                (
                    '/etc/postfix/main.cf',
                    'smtpd_relay_restrictions = reject_unauth_destination, permit\ndisable_vrfy_command = yes\nsmtpd_banner = Authorized use only\n',
                ),
            )
        ),
        'postfix-stock-banner': _debian(
            files=(
                (
                    '/etc/postfix/main.cf',
                    'disable_vrfy_command = yes\nsmtpd_banner = $myhostname ESMTP $mail_name (Ubuntu)\n',
                ),
            )
        ),
        'nfs-expanded-ipv6-world': _debian(
            files=(('/etc/exports', '/srv 0:0:0:0:0:0:0:0/0(ro)\n'),)
        ),
        'nfs-commented-anonuid': _debian(
            files=(('/etc/exports', '/srv 192.0.2.0/24(ro) # anonuid=65534\n'),)
        ),
        'pwhistory-only-root': _debian(
            files=(
                (
                    '/etc/security/pwquality.conf',
                    'minlen=8\ndcredit=-1\nucredit=-1\nlcredit=-1\nocredit=-1\n',
                ),
                ('/etc/security/pwhistory.conf', 'remember=4\n'),
                (
                    '/etc/pam.d/common-password',
                    'password requisite pam_pwquality.so\npassword required pam_pwhistory.so remember=4 enforce_for_root\npassword required pam_unix.so\n',
                ),
            )
        ),
        'faillock-without-authfail': _debian(
            files=(
                ('/etc/pam.d/common-auth', 'auth required pam_faillock.so deny=3\n'),
            )
        ),
        'faillock-split-deny': _debian(
            files=(
                ('/etc/security/faillock.conf', 'deny = 20\n'),
                (
                    '/etc/pam.d/common-auth',
                    'auth required pam_faillock.so preauth\nauth [default=die] pam_faillock.so authfail deny=5\n',
                ),
            )
        ),
        'su-empty-shell-account': _debian(
            passwd='root:x:0:0:root:/root:/bin/bash\nbob:x:1001:1001::/home/bob:\n',
            files=(('/etc/pam.d/su', 'auth sufficient pam_rootok.so\n'),),
            stats=(('/usr/bin/su', '4755 root root'),),
        ),
        'su-requisite-wheel': _debian(
            files=(('/etc/pam.d/su', 'auth requisite pam_wheel.so group=wheel\n'),),
            stats=(('/usr/bin/su', '4755 root root'),),
        ),
        'vsftpd-anonymous-default-debian': _debian(
            files=(('/etc/vsftpd.conf', 'ftpd_banner=Authorized use only\n'),)
        ),
        'vsftpd-anonymous-default-rhel': dataclasses.replace(
            BASE_RHEL,
            files=(('/etc/vsftpd.conf', 'ftpd_banner=Authorized use only\n'),),
        ),
        'vsftpd-user-list-without-root': _debian(
            files=(
                ('/etc/vsftpd.conf', VSFTPD_BASE + 'userlist_enable=YES\n'),
                ('/etc/vsftpd.user_list', 'alice\n'),
            )
        ),
        'xinetd-running-without-small-services': _debian(
            active_units='sshd.service chronyd.service xinetd.service'
        ),
        'bind-negated-any': _debian(
            files=(
                (
                    '/etc/bind/named.conf.options',
                    'version "Authorized use only";\nallow-transfer { !any; };\nallow-update { ! any; };\n',
                ),
            )
        ),
        'proftpd-rhel-path': dataclasses.replace(
            BASE_RHEL,
            installed=RHEL_INSTALLED + ' proftpd',
            files=(('/etc/proftpd.conf', 'ServerIdent off\n'),),
        ),
        'snmp-vacm': _debian(
            files=(
                (
                    '/etc/snmp/snmpd.conf',
                    'group admins usm monitor\nview all included .1\naccess admins "" usm auth exact all none none\n',
                ),
            )
        ),
        'chrony-nested-include': _debian(
            files=(
                ('/etc/chrony/chrony.conf', 'include /etc/chrony/a.conf\n'),
                ('/etc/chrony/a.conf', 'include /etc/chrony/b.conf\n'),
                ('/etc/chrony/b.conf', 'server time.example.test iburst\n'),
            )
        ),
        'ssh-match-equals': _debian(
            files=(
                (
                    '/etc/ssh/sshd_config',
                    'PermitRootLogin no\nMatch User root\n  PermitRootLogin=yes\n',
                ),
            )
        ),
        'ssh-match-banner-equals': _debian(
            files=(
                (
                    '/etc/ssh/sshd_config',
                    'PermitRootLogin no\nBanner /etc/issue.net\nMatch User alice\n  Banner=none\n',
                ),
            )
        ),
        'faillock-custom-conf': _debian(
            files=(
                ('/etc/security/site-faillock.conf', 'deny = 20\n'),
                (
                    '/etc/pam.d/common-auth',
                    'auth required pam_faillock.so preauth conf=/etc/security/site-faillock.conf\nauth [default=die] pam_faillock.so authfail conf=/etc/security/site-faillock.conf\n',
                ),
            )
        ),
        'faillock-authsucc': _debian(
            files=(
                (
                    '/etc/pam.d/common-auth',
                    'auth required pam_faillock.so preauth deny=5\nauth [default=die] pam_faillock.so authfail deny=5\nauth sufficient pam_faillock.so authsucc deny=5\n',
                ),
                ('/etc/pam.d/common-account', 'account required pam_unix.so\n'),
            )
        ),
        'su-wheel-deny': _debian(
            files=(('/etc/pam.d/su', 'auth required pam_wheel.so deny group=wheel\n'),),
            stats=(('/usr/bin/su', '4755 root root'),),
        ),
        'vsftpd-pam-without-listfile': _debian(
            files=(('/etc/pam.d/vsftpd', 'auth required pam_unix.so\n'),)
        ),
        'home-setgid': _debian(stats=(('/home/alice', '2755 alice alice'),)),
        'nfs-ipv6-colon-mask': _debian(files=(('/etc/exports', '/srv ::/::(rw)\n'),)),
        'bind-negated-any-first': _debian(
            files=(
                (
                    '/etc/bind/named.conf.options',
                    'version "Authorized use only";\nallow-transfer { !any; any; };\nallow-update { none; };\n',
                ),
            )
        ),
        'snmp-authcommunity': _debian(
            files=(
                (
                    '/etc/snmp/snmpd.conf',
                    'rouser monitor authPriv\nauthcommunity read Strong12345!\n',
                ),
            )
        ),
        'snmp-createuser-engine': _debian(
            files=(
                (
                    '/var/lib/snmp/snmpd.conf',
                    'createUser -e 0x80001f88 monitor SHA "Abcdef12!" AES\n',
                ),
            )
        ),
        'ntpsec-includefile': _debian(
            installed=DEBIAN_INSTALLED.replace('chrony', 'ntpsec'),
            active_units='sshd.service ntpsec.service',
            files=(
                ('/etc/chrony/chrony.conf', None),
                ('/etc/ntpsec/ntp.conf', 'includefile /etc/ntpsec/servers.conf\n'),
                ('/etc/ntpsec/servers.conf', 'server time.example.test iburst\n'),
            ),
        ),
        'chrony-peer-selected': _debian(time_source='=* peer.example.test\n'),
        'ssh-include-equals': _debian(
            files=(
                (
                    '/etc/ssh/sshd_config',
                    'PermitRootLogin no\nInclude=/etc/ssh/root.conf\n',
                ),
                ('/etc/ssh/root.conf', 'Match User root\n  PermitRootLogin yes\n'),
            )
        ),
        'faillock-deny-zero': _debian(
            files=(
                ('/etc/security/faillock.conf', 'deny = 5\n'),
                (
                    '/etc/pam.d/common-auth',
                    'auth required pam_faillock.so preauth deny=0\nauth [default=die] pam_faillock.so authfail deny=0\n',
                ),
            )
        ),
        'xinetd-backup-file': _debian(
            active_units='sshd.service chronyd.service xinetd.service',
            files=(
                ('/etc/xinetd.conf', 'defaults { }\nincludedir /etc/xinetd.d\n'),
                ('/etc/xinetd.d/echo.dpkg-old', 'service echo\n{\ndisable = no\n}\n'),
            ),
        ),
        'exim-heavy': _debian(
            installed='openssh-server exim4-daemon-heavy',
            active_units='sshd.service',
            loaded_units='sshd.service',
            files=(('/etc/exim4/exim4.conf', 'acl_smtp_vrfy = deny\n'),),
        ),
        'nfs-quoted-world': _debian(files=(('/etc/exports', '/srv "*"(ro)\n'),)),
        'nfs-hash-in-quoted-path': _debian(
            files=(('/etc/exports', '"/srv/a#b" 10.0.0.0/8(ro)\n'),)
        ),
        'chrony-second-sourcedir': _debian(
            files=(
                (
                    '/etc/chrony/chrony.conf',
                    'sourcedir /etc/chrony/empty /etc/chrony/sources.d\n',
                ),
                (
                    '/etc/chrony/sources.d/pool.sources',
                    'pool pool.example.test iburst\n',
                ),
            )
        ),
        'pwquality-not-enforcing': _debian(
            files=(
                (
                    '/etc/security/pwquality.conf',
                    'minlen=8\ndcredit=-1\nucredit=-1\nlcredit=-1\nocredit=-1\nenforce_for_root\nenforcing=0\n',
                ),
            )
        ),
        'crontab-user-group': _debian(stats=(('/usr/bin/crontab', '750 root alice'),)),
        'crontab-memberless-group': _debian(
            group=BASE_DEBIAN.group + 'crontab:x:107:\n',
            stats=(('/usr/bin/crontab', '750 root crontab'),),
        ),
    }
    return _parsed_cases(tmp_path_factory, hosts)


@pytest.mark.parametrize(
    ('case', 'item_id'),
    [
        ('nfs-world-options', 'U-40'),
        ('nfs-no-client', 'U-40'),
        ('nfs-default-options-only', 'U-40'),
        ('nfs-quoted-path-no-client', 'U-40'),
        ('proftpd-default-ident', 'U-53'),
        ('proftpd-ident-variable', 'U-53'),
        ('proftpd-ident-reenabled', 'U-53'),
        ('proftpd-included', 'U-35'),
        ('proftpd-boolean-no', 'U-57'),
        ('proftpd-included-root-login', 'U-57'),
        ('proftpd-virtual-host-root-login', 'U-57'),
        ('samba-public', 'U-35'),
        ('samba-guest-on', 'U-35'),
        ('samba-public-one', 'U-35'),
        ('sendmail-default-greeting', 'U-62'),
        ('sendmail-version-macro', 'U-62'),
        ('forged-walk-record', 'U-67'),
        ('postfix-warn-only-relay', 'U-47'),
        ('postfix-stock-banner', 'U-62'),
        ('nfs-expanded-ipv6-world', 'U-40'),
        ('pwhistory-only-root', 'U-02'),
        ('faillock-without-authfail', 'U-03'),
        ('faillock-split-deny', 'U-03'),
        ('su-empty-shell-account', 'U-06'),
        ('vsftpd-anonymous-default-rhel', 'U-35'),
        ('ssh-match-equals', 'U-01'),
        ('ssh-match-banner-equals', 'U-62'),
        ('su-wheel-deny', 'U-06'),
        ('vsftpd-pam-without-listfile', 'U-57'),
        ('nfs-ipv6-colon-mask', 'U-40'),
        ('snmp-authcommunity', 'U-59'),
        ('snmp-authcommunity', 'U-61'),
        ('ssh-include-equals', 'U-01'),
        ('faillock-deny-zero', 'U-03'),
        ('nfs-quoted-world', 'U-40'),
        ('pwquality-not-enforcing', 'U-02'),
        ('crontab-user-group', 'U-37'),
        ('exim-heavy', 'U-62'),
    ],
)
def test_settings_that_expose_a_service_are_violations(
    config_semantics_runs, case, item_id
):
    run, _ = config_semantics_runs[case]

    assert run.items[ItemId(item_id)].verdict is Verdict.FAIL


@pytest.mark.parametrize(
    ('case', 'item_id'),
    [
        ('proftpd-included', 'U-53'),
        ('proftpd-included', 'U-57'),
        ('proftpd-without-ftpusers', 'U-57'),
        ('proftpd-included-login-banner', 'U-62'),
        ('vsftpd-deny-only', 'U-57'),
        ('vsftpd-allowlist', 'U-57'),
        ('vsftpd-boolean-words', 'U-57'),
        ('samba-commented-guest', 'U-35'),
        ('sendmail', 'U-62'),
        ('held-telnetd', 'U-52'),
        ('chrony-sourcedir', 'U-65'),
        ('chrony-second-confdir', 'U-65'),
        ('ntpsec', 'U-65'),
        ('postfix-default-relay', 'U-47'),
        ('postfix-relay-gate-closes-open-recipient', 'U-47'),
        ('postfix-submission-rejects-the-rest', 'U-47'),
        ('faillock-default-deny', 'U-03'),
        ('pam-tab-arguments', 'U-02'),
        ('pwquality-drop-in', 'U-02'),
        ('postfix-reject-then-permit', 'U-47'),
        ('nfs-commented-anonuid', 'U-35'),
        ('su-requisite-wheel', 'U-06'),
        ('vsftpd-anonymous-default-debian', 'U-35'),
        ('vsftpd-user-list-without-root', 'U-57'),
        ('xinetd-running-without-small-services', 'U-38'),
        ('bind-negated-any', 'U-50'),
        ('bind-negated-any', 'U-51'),
        ('proftpd-rhel-path', 'U-53'),
        ('snmp-vacm', 'U-59'),
        ('snmp-vacm', 'U-61'),
        ('chrony-nested-include', 'U-65'),
        ('faillock-authsucc', 'U-03'),
        ('home-setgid', 'U-31'),
        ('bind-negated-any-first', 'U-50'),
        ('snmp-createuser-engine', 'U-60'),
        ('ntpsec-includefile', 'U-65'),
        ('chrony-peer-selected', 'U-65'),
        ('xinetd-backup-file', 'U-38'),
        ('nfs-hash-in-quoted-path', 'U-40'),
        ('chrony-second-sourcedir', 'U-65'),
        ('crontab-memberless-group', 'U-37'),
    ],
)
def test_documented_defaults_and_alternate_syntax_pass_a_secured_setting(
    config_semantics_runs, case, item_id
):
    run, _ = config_semantics_runs[case]

    assert run.items[ItemId(item_id)].verdict is Verdict.PASS


@pytest.mark.parametrize(
    ('case', 'item_id', 'reason'),
    [
        ('time-unit-error', 'U-65', 'incomplete'),
        ('chrony-unreadable-source', 'U-65', 'access-denied'),
        ('proftpd-missing-include', 'U-57', 'incomplete'),
        ('rhosts-fifo', 'U-27', 'incomplete'),
        ('hosts-equiv-fifo', 'U-27', 'incomplete'),
        ('rhosts-symlink', 'U-27', 'incomplete'),
        ('faillock-custom-conf', 'U-03', 'incomplete'),
    ],
)
def test_unobservable_state_is_unknown_rather_than_judged(
    config_semantics_runs, case, item_id, reason
):
    run, _ = config_semantics_runs[case]

    item = run.items[ItemId(item_id)]
    assert (item.verdict, item.facts['reason']) == (Verdict.UNKNOWN, reason)
