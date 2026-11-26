#!/bin/sh
# Globbing disabled;fields split deliberately.
# shellcheck disable=SC2086
R=''
# Formats are literal.
# shellcheck disable=SC2059
p(){ printf "$@";}
ep(){ e pass "$@";}
ef(){ e fail "$@";}
er(){ e review "$@";}
eu(){ e unknown "$@";}
E=$R/etc;V=$R/var;B=$R/usr
S=$E/shadow;L=$E/login.defs;F=$E/security/faillock.conf;M=$E/mail/sendmail.cf;C=$E/vsftpd/vsftpd.conf;D=$E/proftpd/proftpd.conf;H=$E/hosts.equiv;X=$E/exports;
set -f
IFS=$(p ' \t\n_')
IFS=${IFS%_}
LC_ALL=C
export LC_ALL
ur(){ eu reason=incomplete;}
ENCODE_AWK='
function encode(value, out, i, c){
    for(i=1;i<=length(value);i++){
        c=substr(value,i,1)
        out=out ((c in escape)?escape[c]:c)
    }
    return out
}
BEGIN{
    for(i=0;i<32;i++)escape[sprintf("%c",i)]=sprintf("%%%02X",i)
    escape[sprintf("%c",127)]="%7F"
    escape[" "]="%20";escape[","]="%2C";escape["%"]="%25"
}'
enc(){
    case $1 in
        '') p '%s' '-';;
        -) p '%s' '%2D';;
        *[[:cntrl:][:space:],%]*)
            p '%s.' "$1" | awk "$ENCODE_AWK"'
            NR>1{value=value "\n"}{value=value $0}
            END{printf "%s",encode(substr(value,1,length(value)-1))}';;
        *) p '%s' "$1";;
    esac
}
e(){
p 'item id=%s verdict=%s' "$ITEM" "$1"
shift
for fact do
p ' %s=' "${fact%%=*}"
enc "${fact#*=}"
done
p '\n'
}
wn(){
case $1 in ''|*[!0-7]*) return 1;;esac
[ ${#1} -le 4 ]||return 1
[ $((0$1&~0$2)) = 0 ]
}
td(){
if command -v timeout >/dev/null 2>&1;then timeout 15 "$@";else "$@";fi
}
ce(){
case $1 in *'Permission denied'*|*'Operation not permitted'*|*'!access-denied'*) if [ "$Z" = 0 ];then p access-denied;else p needs-approval;fi;;
*'!tool-missing'*) p tool-missing;;*'!timeout'*) p timeout;;
*) case $2 in 127) p tool-missing;;124) p timeout;;*) p incomplete;;esac;;esac
}
pe(){ case $(ce "$1" "$2") in access-denied) return 13;;tool-missing) return 127;;*) return 2;;esac;}
ht(){ [ "$2" = 0 ]||p '!%s\n' "$(ce "$1" "$2")";return 0;}
exists(){ [ -e "$1" ]||[ -L "$1" ]; }
rd(){ [ -r "$1" ]&&return 0;[ ! -e "$1" ]||p '!access-denied\n' >&2;return 1;}
q(){ "$@"||{ qr=$?;[ "$qr" != 127 ]||p '!tool-missing\n' >&2;return "$qr";};}
pq(){
case $PKG in
dpkg-query)
ps=$(dpkg-query -W -f='${Status}' "$1" 2>&1);pr=$?
if [ "$pr" = 0 ];then case $ps in 'install ok installed') return 0;;*' not-installed'|*' config-files') return 1;;esac;fi
[ "$pr" != 1 ]||[ "$ps" != "dpkg-query: no packages found matching $1" ]||return 1
;;
rpm)
ps=$(rpm -q "$1" 2>&1);pr=$?;[ "$pr" != 0 ]||return 0
[ "$pr" != 1 ]||[ "$ps" != "package $1 is not installed" ]||return 1
;;
esac
pe "$ps" "$pr"
}
active_state(){
    case $1 in active|reloading|activating|deactivating) return 0;;*) return 1;;esac
}
sq(){
    case $1 in *.socket|*.target) set -- "$1" "${1%.*}" "${1##*.}";;*) set -- "$1.service" "$1" service;;esac
    us_rc=0
    us=$(systemctl show -p LoadState -p ActiveState "$1" 2>&1)||us_rc=$?
    load='';state=''
    for property in $us;do
        case $property in LoadState=*) load=${property#*=};;ActiveState=*) state=${property#*=};;esac
    done
    if [ "$us_rc" = 0 ]&&active_state "$state";then return 0;fi
    found=0
    for unit_state in $UNIT_ROWS;do
        unit=${unit_state%:*}
        case $unit in
            "$2"@*."$3") :;;
            "$2.socket"|"$2"@*.socket)
                [ "$3" = service ]||continue
                case " $UNIT_SELECTORS " in *" $2.socket "*) continue;;esac;;
            *) continue;;
        esac
        active_state "${unit_state##*:}"&&return 0
        found=1
    done
    [ "$us_rc" = 0 ]||{ pe "$us" "$us_rc";return $?;}
    [ "$UNIT_RC" = 0 ]||{ pe "$UNIT_OUTPUT" "$UNIT_RC";return $?;}
    case $load:$state in
        loaded:inactive|loaded:failed|masked:inactive|masked:failed) return 3;;
        not-found:inactive) [ "$found" = 0 ]&&return 1;return 3;;
    esac
    return 2
}
OE=unsupported-os
if [ ! -r "$E/os-release" ];then OE=incomplete;[ ! -e "$E/os-release" ]||OE=access-denied;fi
OI='';OL='';OV=''
while IFS='=' read -r k v||[ -n "$k" ];do
v=${v#\"};v=${v%\"};v=${v#\'};v=${v%\'}
case $k in ID) OI=$v;;ID_LIKE) OL=$v;;VERSION_ID) OV=$v;;esac
done 2>/dev/null < "$E/os-release"
[ -n "$OI" ]||[ "$OE" != unsupported-os ]||OE=incomplete
FAM=unknown
for os in "$OI" $OL;do
case $os in
debian|ubuntu) FAM=debian;break;;
rhel|rocky|centos|almalinux) FAM=rhel;break;;
esac
done
case $FAM in
debian) PKG=dpkg-query;SSH=openssh-server;TELNET='telnetd inetutils-telnetd';RSH='rsh-server rsh-redone-server';SB='640 root shadow'
FINGER='fingerd';FTP='vsftpd proftpd-core';INET='openbsd-inetd xinetd';MAIL='postfix sendmail-bin exim4-daemon-light'
DNS='bind9';NFS='nfs-kernel-server';AUTO='autofs';NIS='nis ypserv ypbind-mt';TALK='talkd';TFTP='tftpd-hpa';QL='tftpd-hpa tftp.socket tftp'
SNMP='snmpd';TIME='chrony ntpsec systemd-timesyncd';SAMBA='samba';RPC='rpcbind'
PP=/etc/pam.d/common-password;AA=/etc/pam.d/common-auth;AP=/etc/pam.d/common-account
CRON='cron at';DC=/etc/bind/named.conf
;;
rhel) PKG=rpm;SSH=openssh-server;TELNET='telnet-server';RSH='rsh-server';SB=''
FINGER='finger-server';FTP='vsftpd proftpd';INET='xinetd';MAIL='postfix sendmail exim'
DNS='bind';NFS='nfs-utils';AUTO='autofs';NIS='ypserv ypbind';TALK='talk-server';TFTP='tftp-server';QL='tftp.socket tftp'
SNMP='net-snmp';TIME='chrony ntp';SAMBA='samba';RPC='rpcbind'
PP=/etc/pam.d/system-auth;AA=/etc/pam.d/system-auth;AP=/etc/pam.d/system-auth
CRON='cronie at';DC=/etc/named.conf
;;
esac
QF='finger.socket finger';QG='vsftpd proftpd ftp.socket';QI='inetd openbsd-inetd xinetd'
QM='postfix sendmail exim4 exim';DS='named bind9';QN='nfs-server nfs-kernel-server'
QH='autofs';QJ='ypserv ypbind ypxfrd';QK='talk.socket talk ntalk.socket ntalk'
QO='snmpd';QT='chronyd chrony ntpd ntp systemd-timesyncd'
QQ='rsh.socket rsh rlogin.socket rlogin rexec.socket rexec'
RSH_SERVICES='(^|[ /])(rsh|rlogin|rexec|shell|login|in[.](rshd|rlogind|rexecd))([ /{]|$)'
QP='rpc-cmsd rpc-ttdbserverd sadmind rusersd walld sprayd rstatd rexd
rpc-pcnfsd rpc-statd rpc-ypupdated rpc-rquotad kcms-server cachefsd'
QD='echo.socket discard.socket daytime.socket chargen.socket'
LSV='telnet.socket telnet rsh.socket rsh rlogin.socket rlogin'
Z=$(id -u 2>/dev/null)
case $Z in ''|*[!0-9]*) Z=65534;;esac
SHA=$(sha256sum "$0" 2>/dev/null)
SHA=${SHA%% *}
case $SHA in ''|*[!0-9a-f]*) SHA=unknown;;esac
[ ${#SHA} = 64 ]||SHA=unknown
p 'hardening protocol=1 edition=kisa-2026 family=%s os=%s uid=%s sha256=%s\n' "$FAM" "$(enc "$OI-$OV")" "$Z" "$SHA"
TO='';TR=127;LO='';LR=127
if [ "$FAM" != unknown ]&&[ "$Z" = 0 ];then
TO='';TR=127
if command -v chronyc >/dev/null 2>&1;then TO=$(td chronyc sources 2>&1);TR=$?
elif command -v ntpq >/dev/null 2>&1;then TO=$(td ntpq -pn 2>&1);TR=$?;fi
LO=$(ss -lntu 2>&1);LR=$?
fi
WALK='';WRC=0;DEV='';DRC=0
if [ "$FAM" != unknown ]&&[ "$Z" = 0 ];then
set -- "$R/";WALK_U=0
for wr in "$V/log" "$V/spool" "$V/spool/cron" "$V/spool/at";do [ ! -d "$wr" ]||set -- "$@" "$wr";done
if [ -z "$R" ]&&[ -r "$R/proc/self/mountinfo" ];then
while IFS= read -r wr;do [ -n "$wr" ]||continue;case $wr in *\\*) WALK_U=1;;*) set -- "$@" "$wr";;esac;done <<EOF
$(awk '$5=="/var/log"||$5~/^\/var\/log\//||$5=="/var/spool"||$5~/^\/var\/spool\/(cron|at)(\/|$)/{print $5}' "$R/proc/self/mountinfo")
EOF
fi
WALK=$(td find "$@" -xdev -printf '%y\t%m\t%u\t%g\t%U\t%G\t%p\n' 2>&1)
WRC=$?
[ "$WALK_U" = 0 ]||WRC=1
if [ "$WRC" = 0 ];then WALK=$(p '%s\n' "$WALK" | awk -F '\t' 'NF!=7{print;next}!sn[$7]++')||WRC=1;fi
DEV=$(td find "$R/dev" -xdev -printf '%y\t%m\t%u\t%g\t%U\t%G\t%p\n' 2>&1)
DRC=$?
fi
J='';SR=0
if [ "$FAM" != unknown ]&&[ "$Z" = 0 ];then
J=$(td sshd -T 2>&1);SR=$?
fi
cr(){
case $1 in *"|$3:"*) cd=${1#*"|$3:"};rc=${cd%%|*};case $rc in 13) p '!access-denied\n' >&2;;127) p '!tool-missing\n' >&2;;esac;return "$rc";;esac
"$2" "$3"
}
package(){ cr "$PC" pq "$1";}
service(){ cr "$SC" sq "$1";}
cs(){
ca='|'
for tg in $1;do
case $ca in *"|$tg:"*) continue;;esac
rc=0;"$2" "$tg"||rc=$?
ca="$ca$tg:$rc|"
done
p '%s' "$ca"
}
UNIT_SELECTORS="sshd ssh $LSV $QF $QG $QI $QM $DS $QN $QH $QJ $QK $QL $QO $QT $QQ $QD $QP smb smbd nmbd"
PC='';SC='';UNIT_OUTPUT='';UNIT_ROWS='';UNIT_RC=0
if [ "$FAM" != unknown ];then
    UNIT_OUTPUT=$(systemctl list-units --all --no-legend --plain --no-pager '*.service' '*.socket' '*.target' 2>&1)||UNIT_RC=$?
    if [ "$UNIT_RC" = 0 ];then
        UNIT_ROWS=$(p '%s\n' "$UNIT_OUTPUT" | awk 'NF>=4 && $2!="not-found"{print $1 ":" $3}')||UNIT_RC=$?
    fi
fi
if [ "$FAM" != unknown ]&&[ "$Z" = 0 ];then
PC=$(cs "$SSH $TELNET $RSH $FINGER $FTP $INET $MAIL $DNS $NFS $AUTO $NIS \
$TALK $TFTP $SNMP $TIME $SAMBA $RPC cron cronie at" pq)
SC=$(cs "$UNIT_SELECTORS" sq)
fi
BT='';BR=127
if [ "$FAM" != unknown ]&&[ "$Z" = 0 ]&&command -v named-checkconf >/dev/null 2>&1;then BT=$(td named-checkconf -p -x "$R$DC" 2>&1);BR=$?;fi
legacy(){
inetd '(^|[ /])(telnet|in[.]telnetd|rsh|in[.]rshd|rlogin|in[.]rlogind|shell|login)([ /{]|$)'
[ "$IA" = 0 ]&&[ "$IU" = 0 ]
}
U01(){
pkgs "$SSH $TELNET $RSH";unsure=$PU;ins=$PI;bad=0;permit='';la=0;pt='';ic=0
if [ "$SR" = 0 ];then
ins=1
permit=$(p '%s\n' "$J" | awk '$1=="permitrootlogin"{print $2}')
case $permit in no) :;;'') unsure=1;;*) bad=1;;esac
else
rc=0;package "$SSH"||rc=$?
[ "$rc" = 1 ]&&[ "$SR" = 127 ]||unsure=1
if [ "$rc" = 1 ];then
for unit in sshd ssh;do urc=0;service "$unit"||urc=$?
case $urc in 0|3) ins=1;unsure=1;;1) :;;*) unsure=1;;esac
done
fi
fi
if [ "$ins" -gt 0 ]||[ -e "$E/ssh/sshd_config" ];then
ssh_text=$(expand_config ssh /etc/ssh/sshd_config)
case $ssh_text in *'!INCOMPLETE'*) unsure=1;;esac
if p '%s\n' "$ssh_text" | awk '
tolower($1)=="match"{m=1;next}
m&&tolower($1)=="permitrootlogin"&&tolower($2)!="no"{bad=1}
END{exit !bad}';then bad=1;fi
fi
legacy||{ unsure=1;ic=1;}
ht "$UNIT_OUTPUT" "$UNIT_RC"
[ "$UNIT_RC" = 0 ]||unsure=1
for unit_state in $UNIT_ROWS;do
    case $unit_state in
        telnet@*|rsh@*|rlogin@*) active_state "${unit_state##*:}"&&{ unsure=1;ic=1;};;
    esac
done
for unit in $LSV;do
rc=0;service "$unit"||rc=$?
case $rc in
0) ins=1;la=$((la+1))
case $unit in telnet*) pt="$pt login";;rsh*) pt="$pt rsh";;*) pt="$pt rlogin";;esac;;
3) ins=1;;
1) :;;
*) unsure=1;;
esac
done
for tg in $pt;do
if [ ! -r "$E/pam.d/$tg" ]||[ ! -r "$E/securetty" ];then unsure=1;continue;fi
if ! awk '$1=="auth"&&$2=="required"&&$3~/(^|\/)pam_securetty[.]so$/{ok=1}END{exit!ok}' "$E/pam.d/$tg";then bad=1;fi
if ! awk '!/^[ \t]*#/&&/pts\//{bad=1}END{exit bad}' "$E/securetty";then bad=1;fi
done
if [ "$bad" = 1 ];then ef "permitrootlogin=$permit" "legacy_active=$la"
elif [ "$unsure" = 1 ];then
if [ "$SR" = 124 ];then eu reason=timeout
elif [ "$ic" = 1 ];then eu reason=incomplete
else ur;fi
elif [ "$ins" = 0 ];then e na reason=not-installed
else ep "permitrootlogin=$permit" "legacy_active=$la";fi
}
U13(){
if ! rd "$S"||! rd "$L";then ur;return;fi
c=$(awk -F: 'NF!=9||$1==""{bad=1;next}$2==""{e++;next}$2~/^[!*]/{l++;sub(/^[!]+/,"",$2);if($2==""||$2~/^[*]/)next}
$2~/^\$6\$/{a++;next}$2~/^\$5\$/{b++;next}$2~/^\$y\$/{y++;next}$2~/^\$1\$/{m++;next}{o++}
END{if(bad||NR==0)exit 1;print a+0,b+0,y+0,m+0,l+0,e+0,o+0}' "$S" )||{ ur;return;}
method=$(awk '$1=="ENCRYPT_METHOD"{v=toupper($2)}END{print v}' "$L")||return 1
set -- $c;verdict=pass;[ "$4" = 0 ]&&[ "$6" = 0 ]&&[ "$7" = 0 ]||verdict=fail
case $method in SHA256|SHA512|YESCRYPT) :;;'') [ "$verdict" = fail ]||{ ur;return;};;*) verdict=fail;;esac
e "$verdict" "sha512=$1" "sha256=$2" "yescrypt=$3" "md5=$4" "locked=$5" "empty=$6" "other=$7" "encrypt_method=$method"
}
U18(){
meta=$(fm "$S")||{ ur;return;};set -- $meta
[ "$#" = 3 ]||return 1
vm "$meta"||{ ur;return;}
verdict=fail;[ "$2" != root ]||! wn "$1" 400||verdict=pass
note='';[ "$meta" != "$SB" ]||note=note=distro-default
e "$verdict" "mode=$1" "owner=$2" "group=$3" $note
}
U07(){ login_accounts login_accounts;}
timed_out(){ eu reason=timeout;}
part(){ eu reason=incomplete;}
P=$E/passwd;G=$E/group
awk(){ q command awk "$@";}
wv(){
[ "$1" = 0 ]||{ ef "$4=$1";return;}
[ "$WRC" != 124 ]||{ timed_out;return;}
[ "$WRC" = 0 ]&&[ "$2" = 0 ]||{ part;return;}
ep "$5=$3"
}
need(){ rd "$1"||{ ur;return 1;};}
pw(){ need "$P"||return;awk -F: 'NF!=7||$1==""||$3!~/^[0-9]+$/{bad=1}END{exit bad||(NR==0)}' "$P"||{ ur;return 1;};}
gp(){ need "$G"||return;awk -F: 'NF!=4||$1==""{bad=1}END{exit bad||(NR==0)}' "$G"||{ ur;return 1;};}
fm(){
q stat -L -c '%a %U %G' "$1" 
}
vm(){ set -- $1;[ "$#" = 3 ]&&wn "$1" 7777;}
om(){
path=$1;os=$2;mx=$3
need "$path"||return 0
m=$(fm "$path")||{ ur;return;}
set -- $m
[ "$#" = 3 ]||{ ur;return;}
al=0
for ao in $os;do [ "$2" != "$ao" ]||al=1;done
if [ "$al" = 0 ];then vd=fail
elif ! wn "$1" 7777;then ur;return
elif wn "$1" "$mx";then vd=pass;else vd=fail;fi
e "$vd" "mode=$1" "owner=$2" "group=$3"
}
rl(){
ck=$1;lk=$2;vs=$3
ls=$(p '%s\n' "$vs" | awk "$ENCODE_AWK"'
length($0){n++;if (n<=20)names=names (n>1?",":"") ($0=="-"?"%2D":encode($0))}
END{print n+0;print names;print (n>20?n-20:0)}
')||{ eu reason=check-error;return;}
ct=${ls%%'
'*};tail=${ls#*'
'};names=${tail%'
'*};more=${ls##*'
'}
e "${4:-review}" "$ck=$ct" "$lk=$names" "more=$more" ${5:+"$5"}
}
U02(){
need "$L"||return 0
need "$R$PP"||return 0
policy=$(awk '
/^[ \t]*#/{next}
$1=="PASS_MIN_DAYS"{a=$2}
$1=="PASS_MAX_DAYS"{b=$2}
END{print a+0,b+0}
' "$L")||{ ur;return;}
set -- $policy;md=$1;xd=$2
c=''
for pf in "$E/security/pwquality.conf" "$E/security/pwhistory.conf";do
[ ! -e "$pf" ]||rd "$pf"||{ ur;return;}
[ ! -r "$pf" ]||c="$c
$(awk '{sub(/#.*/,"")}NF{print}' "$pf")"||return 1
done
c="$c
!PAM
$(awk '{sub(/#.*/,"")}NF{print}' "$R$PP")"||return 1
facts=$(p '%s\n' "$c" | awk '
$0=="!PAM"{pam=1;next}
pam{
    if($1!="password")next
    mod=""
    for(aidx=3;aidx<=NF;aidx++)if($aidx~/[.]so$/){mod=$aidx;sub(/^.*\//,"",mod);break}
    if(mod=="pam_pwquality.so"){i=1;if(!u)j=1}
    else if(mod=="pam_pwhistory.so"){k=1;if(!u)l=1}
    else if(mod=="pam_unix.so"){u=1;next}
    else next
}
function v(k,r){r=$0;sub(".*"k"[ \\t]*=[ \\t]*","",r);sub(/[ \\t].*/,"",r);return r}
(!pam||mod=="pam_pwquality.so"){
    if(/minlen[ \t]*=/){x=v("minlen");a=(x~/^[0-9]+$/&&x>=8)}
    if(/dcredit[ \t]*=/)b=(v("dcredit")=="-1")
    if(/ucredit[ \t]*=/)d=(v("ucredit")=="-1")
    if(/lcredit[ \t]*=/)e=(v("lcredit")=="-1")
    if(/ocredit[ \t]*=/)f=(v("ocredit")=="-1")
}
(!pam||mod=="pam_pwhistory.so")&&/remember[ \t]*=/{x=v("remember");g=(x~/^[0-9]+$/&&x>=4)}
/enforce_for_root/{h=1}
END{printf "%d%d%d%d%d%d%d%d%d%d%d%d",a,b,d,e,f,g,h,i,k,j,l,u}
')||return 1
vd=fail
[ "$md" -ge 1 ]&&[ "$xd" -ge 1 ]&&[ "$xd" -le 90 ]&&[ "$facts" = 111111111111 ]&&vd=pass
e "$vd" "min_days=$md" "max_days=$xd" "policy=$facts"
}
U03(){
af="$R$AA";cf="$R$AP";need "$af"||return 0
c=''
if [ -e "$F" ];then
need "$F"||return 0
c=$(awk '{sub(/#.*/,"")}NF{print}' "$F")||return 1
fi
c="$c
!PAM
$(awk '{sub(/#.*/,"")}NF{print}' "$af")"||{ ur;return;}
stt=$(p '%s\n' "$c" | awk '
$0=="!PAM"{pam=1;next}
pam{
    if($1!="auth"||$0!~/(^|[ \t\/])pam_(faillock|tally2?)[.]so([ \t]|$)/)next
    module=1
}
match($0,/(^|[ \t])deny[ \t]*=[ \t]*/){
    candidate=substr($0,RSTART+RLENGTH)
    sub(/[ \t].*/,"",candidate)
    deny=(candidate~/^[0-9]+$/?candidate+0:0)
}
END{print module+0,(deny>=1 && deny<=10)}
')||return 1
set -- $stt
a=0;need "$cf"||return 0
awk '{sub(/#.*/,"")}$1=="account"&&/(^|[ \t\/])pam_(faillock|tally2?)[.]so([ \t]|$)/{ok=1}END{exit!ok}' "$cf"&&a=1
if [ "$1$2$a" = 111 ];then ep "module=$1" "threshold=$2";else ef "module=$1" "threshold=$2";fi
}
U04(){
pw||return 0
if [ ! -e "$S" ];then
stt=$(awk -F: 'NF!=7||$1==""{b=1;next}$2~/^[!*]$/||$2~/^[!*]*[$][^$]+[$]/{s++;next}{p++}END{if(b||NR==0)exit 1;print s+0,p+0}' "$P")||{ ur;return;}
set -- $stt
if [ "$2" = 0 ];then ep shadow=0 "encrypted=$1";else ef "plain=$2" x=0;fi
return
fi
need "$S"||return 0
ps=$(awk -F: '
FILENAME==ARGV[1]{if (NF!=9 || $1=="")bad=1;shadow_name[$1]=1;next}
NF!=7 || $1==""{bad=1;next}
$2=="x"{shadow++;if (!($1 in shadow_name))mi++;next}
$2~/^[!*]$/ || $2~/^[!*]*[$][^$]+[$]/{protected++;next}
{plain++}
END{if (bad || NR==0)exit 1;print shadow+0,protected+0,plain+0,mi+0}
' "$S" "$P")||{ ur;return;}
set -- $ps
if [ "$3" -gt 0 ]||[ "$4" -gt 0 ];then ef "plain=$3" "missing=$4"
else ep "shadow=$1" "encrypted=$2";fi
}
U05(){
pw||return 0
stt=$(awk -F: 'NF!=7||$3!~/^[0-9]+$/{bad=1}$3~/^[0-9]+$/&&$3+0==0&&$1!="root"{n++}END{if(bad||NR==0)exit 1;print n+0}' "$P")||{
ur;return;
}
if [ "$stt" = 0 ];then ep "extra_uid0=0";else ef "extra_uid0=$stt";fi
}
U06(){
pw&&gp||return 0
o=0
while IFS=: read -r account _ _ _ _ _ shell||[ -n "$account" ];do
[ "$account" = root ]||! login_shell "$shell"||o=$((o+1))
done < "$P"
[ "$o" != 0 ]||{ ep accounts=root-only;return;}
need "$E/pam.d/su"||return 0
pg=$(awk '
{sub(/#.*/,"")}
$1=="auth"&&$2=="sufficient"&&$3!~/(^|\/)pam_rootok[.]so$/&&!wheel{bypass=1}
$1=="auth"&&$2=="required"&&$3~/(^|\/)pam_wheel[.]so$/{wheel=1;
group="wheel";for (i=1;i<=NF;i++)if ($i~/^group=/){sub(/^group=/,"",$i);group=$i};print group;exit
}
END{if(bypass)print "!BYPASS"}
' "$E/pam.d/su")||return 1
case $pg in *'!BYPASS'*) ef group=wheel method=pam;return;;esac
if [ -n "$pg" ]&&awk -F: -v g="$pg" '$1==g{fd=1}END{exit!fd}' "$G";then
ep "group=$pg" method=pam;return
fi
m=$(fm "$B/bin/su")||{ ur;return;}
vm "$m"||{ ur;return;}
set -- $m
if [ "$#" = 3 ]&&[ "$2" = root ]&&[ "$3" != root ]&&wn "$1" 4750;then
ep "mode=$1" "group=$3" method=mode
else ef "mode=${1-}" "group=${3-}";fi
}
U08(){
pw&&gp||return 0
names=$(awk -F: '
FILENAME==ARGV[1]{if ($3==0 && $1!="root")out[$1]=1;next}
NF!=4{bad=1}$3==0{n=split($4,a,",");for (i=1;i<=n;i++)if (a[i]!="" && a[i]!="root")out[a[i]]=1}
END{if(bad||FNR==0)exit 1;for (name in out)print name}
' "$P" "$G")||{ ur;return;}
rl admin_accounts names "$names"
}
U09(){
pw&&gp||return 0
names=$(awk -F: '
FILENAME==ARGV[1]{users[$1]=1;gids[$4]=1;next}
NF!=4{bad=1}{used=($3 in gids);n=split($4,a,",");for (i=1;i<=n;i++)if (a[i] in users)used=1;if (!used)print $1}
END{if(bad||FNR==0)exit 1}
' "$P" "$G")||{ ur;return;}
rl orphan_groups names "$names"
}
U10(){
pw||return 0
du=$(awk -F: 'NF!=7||$3!~/^[0-9]+$/{bad=1}$3~/^[0-9]+$/{sn[$3+0]++}END{if(bad||NR==0)exit 1;for(u in sn)if(sn[u]>1)n++;print n+0}' "$P")||{
ur;return;
}
if [ "$du" = 0 ];then ep duplicate_uids=0;else ef "duplicate_uids=$du";fi
}
shells_ok=0
if [ "$FAM" != unknown ]&&[ -f "$E/shells" ]&&[ -r "$E/shells" ]&&
   login_shells=$(awk '{sub(/#.*/, "");if (NF)print $1}' "$E/shells" 2>/dev/null);then
    shells_ok=1
fi
login_shell(){
if [ "$shells_ok" = 0 ];then
    case ${1##*/} in nologin|false) return 1;;esac
    return 0
fi
[ -n "$1" ]||return 1
case "
$login_shells
" in *"
$1
"*) return 0;;*) return 1;;esac
}
login_accounts(){
pw||return 0
names=''
while IFS=: read -r account _ _ _ _ _ shell||[ -n "$account" ];do
login_shell "$shell"||continue
names="${names:+$names
}$account"
done < "$P"
if [ "$shells_ok" = 1 ];then rl "$1" names "$names"
else rl "$1" names "$names" unknown reason=incomplete;fi
}
U11(){ login_accounts login_shell_accounts;}
lc(){
case " $LS " in *" $1 "*) return 0;;esac
LS="$LS $1";lp=$R$1
if [ ! -e "$lp" ]||! rd "$lp";then p '!INCOMPLETE\n';return;fi
text=$(awk '{sub(/#.*/,"");print}' "$lp")||{ p '!INCOMPLETE\n';return;}
p '%s\n' "$text"
incs=$(p '%s\n' "$text" | awk '
$1=="."||$1=="source"{
p=$2;gsub(/^"|"$/, "", p)
if(!index(p,"$")&&!index(p,"`")&&p~/^\//)print p
}')||{ p '!INCOMPLETE\n';return;}
while IFS= read -r inc;do
    if [ -n "$inc" ];then lc "$inc";fi
done <<EOF
$incs
EOF
}
login_configs(){
LS='';set +f
set -- "$E/profile" "$E/profile.d/"* "$E/bashrc" "$E/bash.bashrc" "$E/environment" "$E/csh.cshrc" "$E/csh.login" "$E/cshrc"
set -f
for lf;do if exists "$lf";then lc "${lf#"$R"}";fi;done
return 0
}
U12(){
text=$(login_configs)||{ ur;return;}
ts=$(p '%s\n' "$text" | command awk '
function trim(s){sub(/^[ \t]+/,"",s);sub(/[ \t]+$/,"",s);return s}
/^!INCOMPLETE$/{u=1;next}
{
parts=split($0,a,";")
for(i=1;i<=parts;i++){
s=trim(a[i])
if(s~/^unset[ \t]+TMOUT([ \t]|$)/){bad++;continue}
if(s~/^export[ \t]+TMOUT([ \t]|$)/){exported=1;if(s!~/=/)continue}
if(s~/^(export[ \t]+|readonly[ \t]+)?TMOUT[ \t]*=/){
if(s~/^export[ \t]+/)exported=1
sub(/^(export[ \t]+|readonly[ \t]+)?TMOUT[ \t]*=/,"",s);s=trim(s)
q=substr(s,1,1);if((q=="\""||q==sprintf("%c",39))&&substr(s,length(s),1)==q)s=substr(s,2,length(s)-2)
if(s~/^[0-9]+$/){v=s+0;n++;if(v<1||v>600)bad++}else u=1
}
}
}
END{print v+0,exported+0,bad+0,u+0,n+0}
')||{ ur;return;}
set -- $ts
if [ "$3" -gt 0 ];then ef "timeout=$1"
elif [ "$4" -gt 0 ];then ur
elif [ "$5" -gt 0 ]&&[ "$1" -ge 1 ]&&[ "$1" -le 600 ]&&[ "$2" = 1 ];then ep "timeout=$1"
else ef "timeout=$1";fi
}
U14(){
command -v su >/dev/null 2>&1||{ eu reason=tool-missing;return;}
# shellcheck disable=SC2016
set -- su -l root -c 'printf "\n__HC_PATH_BEGIN__%s__HC_PATH_END__\n" "$PATH"'
if command -v timeout >/dev/null 2>&1;then set -- timeout 10 "$@";fi
login_output=$("$@" </dev/null 2>/dev/null)||{
    case $1:$? in timeout:124) eu reason=timeout;;*) eu reason=check-error;;esac
    return
}
case $login_output in *__HC_PATH_BEGIN__*__HC_PATH_END__*) :;;*) eu reason=check-error;return;;esac
login_path=${login_output#*__HC_PATH_BEGIN__};login_path=${login_path%%__HC_PATH_END__*}
case $login_path in ''|.) ef entries=1 positions=1;return;;esac
entries=1;bad=0;positions=''
while [ "$login_path" != "${login_path#*:}" ];do
    case ${login_path%%:*} in
        ''|.)
            bad=$((bad+1))
            if [ "$bad" -le 20 ];then positions="${positions:+$positions,}$entries";fi;;
    esac
    entries=$((entries+1))
    login_path=${login_path#*:}
done
if [ "$bad" = 0 ];then ep "entries=$entries"
elif [ "$bad" -le 20 ];then ef "entries=$entries" "positions=$positions"
else ef "entries=$entries" "positions=$positions" "more=$((bad-20))";fi
}
U15(){
stt=$(p '%s\n' "$WALK" | awk -F '\t' 'NF==0{next}NF!=7{bk=1;next}$3==$5 || $4==$6{bad++}END{print bad+0,bk+0}')||return 1
set -- $stt
wv "$1" "$2" 0 unowned unowned
}
U16(){ om "$P" root 644;}
U17(){
sp=$(p '%s\n' "$WALK" | awk -F '\t' -v r="$R" '
NF==0{next}NF!=7{bk=1;next}{p=$7;q=p;if (r!="" && index(q,r)==1)q=substr(q,length(r)+1)}
(q~"^/etc/systemd/system/" || q~"^/etc/rc[0-9S]*[.]d/" || q~"^/etc/rc[.]d/[^/]+/")&&($1=="f" || $1=="l"){print p}
END{if (bk)print "!INCOMPLETE"}
')||return 1
b=0;u=0;ic=0
enabled_rc=0
enabled=$(systemctl list-unit-files --state=enabled,enabled-runtime --no-legend --no-pager 2>&1)||enabled_rc=$?
ht "$enabled" "$enabled_rc"
if [ "$enabled_rc" = 0 ];then
    while read -r unit state _;do
        case $state in enabled|enabled-runtime) :;;*) continue;;esac
        case $unit in ''|*/*) ic=1;continue;;esac
        for dir in "$B/lib/systemd/system" "$R/lib/systemd/system";do
            sf=$dir/$unit
            if exists "$sf"&&[ ! -d "$sf" ];then sp="$sp
$sf";fi
        done
    done <<EOF
$enabled
EOF
else ic=1;fi
while IFS= read -r sf;do
[ -n "$sf" ]||continue
[ "$sf" != '!INCOMPLETE' ]||{ ic=1;continue;}
m=$(fm "$sf")||{ u=1;continue;}
vm "$m"||{ u=1;continue;}
set -- $m
[ "$2" = root ]&&wn "$1" 7755||b=$((b+1))
done <<EOF
$sp
EOF
if [ "$b" -gt 0 ];then ef "startup_files=$b"
elif [ "$WRC" = 124 ];then timed_out
elif [ "$WRC" != 0 ]||[ "$u" -gt 0 ]||[ "$ic" -gt 0 ];then part
else ep startup_files=ok;fi
}
U19(){ om "$E/hosts" root 644;}
U21(){
f=0;b=0;u=0
for cf in "$E/syslog.conf" "$E/rsyslog.conf";do
exists "$cf"||continue;f=$((f+1))
m=$(fm "$cf")||{ u=1;continue;}
vm "$m"||{ u=1;continue;}
set -- $m
case $2 in root|bin|sys) :;;*) b=1;;esac
wn "$1" 640||b=1
done
if [ "$b" = 1 ];then ef files="$f"
elif [ "$u" = 1 ]||[ "$f" = 0 ];then ur
else ep files="$f";fi
}
U22(){ om "$E/services" 'root bin sys' 644;}
wr(){
src=$WALK;sr=$WRC
[ "$1" != device ]||{ src=$DEV;sr=$DRC;}
case $sr in 0) :;;124) timed_out;return;;*) part;return;;esac
paths=$(p '%s\n' "$src" | awk -F '\t' -v r="$R" -v kind="$1" '
NF==0{next}NF!=7{bk=1;next}
{p=$7;if (r!="" && index(p,r)==1)p=substr(p,length(r)+1);n=split(p,a,"/")}
kind=="privileged" && $1=="f" && $2~/^[1-7][0-7][0-7][0-7]$/{print p}
kind=="world" && $1=="f" && substr($2,length($2),1)~/[2367]/{print p}
kind=="device" && $1=="f" && p!~"^/dev/(mqueue|shm)(/|$)"{print p}
kind=="hidden" && a[n]~/^[.]/ && a[n]!="." && a[n]!=".."{print p}
END{if (bk)exit 2}
')||{ part;return;}
rl "$2" "$3" "$paths"
}
U23(){ wr privileged privileged_files paths;}
U24(){
pw||return 0
b=0;u=0;n=0
set +f
while IFS=: read -r account _ _ _ _ h _;do
for ef in "$R$h"/.profile "$R$h"/.kshrc "$R$h"/.cshrc "$R$h"/.bashrc \
"$R$h"/.bash_profile "$R$h"/.bash_login "$R$h"/.login "$R$h"/.exrc "$R$h"/.netrc;do
exists "$ef"||continue;n=$((n+1))
m=$(fm "$ef")||{ u=1;continue;}
vm "$m"||{ u=1;continue;}
set -- $m
[ "$2" = root ]||[ "$2" = "$account" ]||b=1
wn "$1" 755||b=1
done
done < "$P"
set -f
if [ "$b" = 1 ];then ef "files=$n"
elif [ "$u" = 1 ];then ur
else ep "files=$n";fi
}
U25(){ wr world world_writable paths;}
U26(){ wr device non_device_files paths;}
U29(){
exists "$E/hosts.lpd"||{ ep present=no;return;}
om "$E/hosts.lpd" root 600
}
U30(){
f=0;s=0;u=0
login_text=$(login_configs)||u=1
if rd "$L";then
login_text="$login_text
$(awk '{sub(/#.*/,"");print}' "$L")"||u=1
else u=1;fi
p '%s\n' "$login_text" | awk '/^!INCOMPLETE$/{exit 1}'||u=1
vs=$(p '%s\n' "$login_text" | awk '
{
    n=split($0,commands,";")
    for(i=1;i<=n;i++){
        $0=commands[i]
        if(tolower($1)!="umask")continue
        v=$2;sub(/^=/,"",v)
        q=substr(v,1,1);if((q=="\""||q==sprintf("%c",39))&&substr(v,length(v),1)==q)v=substr(v,2,length(v)-2)
        print (v==""?"!":v)
    }
}
')||u=1
for mask in $vs;do
case $mask in ''|*[!0-7]*) u=1;continue;;esac
f=$((f+1));[ $((0$mask&~0777)) = 0 ]&&[ $((0$mask&0022)) = 18 ]&&s=$((s+1))
done
if [ "$f" -gt 0 ]&&[ "$f" -eq "$s" ]&&[ "$u" = 0 ];then ep "umasks=$f"
elif [ "$f" -gt "$s" ];then ef "unsafe=$((f-s))"
elif [ "$u" = 1 ];then ur
else ef umasks=0;fi
}
U31(){
pw||return 0
b=0;u=0;n=0;skipped=0;bad_homes=''
nl='
'
while IFS=: read -r account _ _ _ _ h shell||[ -n "$account" ];do
    login_shell "$shell"||{ skipped=$((skipped+1));continue;}
    if [ -z "$h" ]||{ [ ! -d "$R$h" ]&&[ ! -L "$R$h" ]; };then continue;fi
    n=$((n+1))
    m=$(fm "$R$h")||{ u=1;continue;}
    vm "$m"||{ u=1;continue;}
    set -- $m
    if [ "$2" != "$account" ]||! wn "$1" 755;then
        case $bad_homes in
            *"$nl$h$nl"*) ;;
            *) b=$((b+1));bad_homes="$bad_homes$nl$h$nl";;
        esac
    fi
done < "$P"
if [ "$b" -gt 0 ];then ef "bad_homes=$b" "skipped=$skipped"
elif [ "$u" = 1 ]||[ "$shells_ok" = 0 ];then eu "skipped=$skipped" reason=incomplete
else ep "homes=$n" "skipped=$skipped";fi
}
U32(){
pw||return 0
x=0;n=0;skipped=0;u=0
while IFS=: read -r account _ _ _ _ h shell||[ -n "$account" ];do
    login_shell "$shell"||{ skipped=$((skipped+1));continue;}
    n=$((n+1))
    if [ -n "$h" ]&&[ -d "$R$h" ];then continue;fi
    if [ -n "$h" ]&&[ -L "$R$h" ]&&[ ! -e "$R$h" ];then u=1;else x=$((x+1));fi
done < "$P"
if [ "$x" -gt 0 ];then ef "missing=$x" "skipped=$skipped"
elif [ "$shells_ok" = 0 ]||[ "$u" = 1 ];then eu "skipped=$skipped" reason=incomplete
else ep "homes=$n" "skipped=$skipped";fi
}
U33(){ wr hidden hidden_paths paths;}
walk_modes(){
    max_mode=$2
    files=$(p '%s\n' "$WALK" | awk -F '\t' -v r="$R" -v pattern="$1" '
    NF==0{next}
    NF!=7{print "!";next}
    {path=$7;if(r!="" && index(path,r)==1)path=substr(path,length(r)+1)}
    path~pattern && $1=="f"{print $2,$3}
    path~pattern && $1=="l"{print "link " $7}
    ')||return 1
    bad=0;incomplete=0;count=0
    while IFS= read -r record;do
        case $record in
            '') continue;;
            '!') incomplete=1;continue;;
            'link '*)
                link=${record#link }
                [ ! -d "$link" ]||continue
                if ! meta=$(fm "$link")||! vm "$meta";then incomplete=1;continue;fi
                record=${meta% *};;
        esac
        set -- $record
        if [ "$#" != 2 ]||! wn "$1" 7777;then incomplete=1;continue;fi
        count=$((count+1))
        [ "$2" = root ]&&wn "$1" "$max_mode"||bad=$((bad+1))
    done <<EOF
$files
EOF
    p '%s %s %s\n' "$bad" "$incomplete" "$count"
}
U37(){
pi=0;pu=0;ci=0;ai=0
for p in $CRON;do rc=0;package "$p"||rc=$?;case $rc in 0) pi=1;case $p in at) ai=1;;*) ci=1;;esac;;1) :;;*) pu=1;;esac;done
if [ "$pi" = 0 ];then
if [ "$pu" = 1 ];then ur;else e na reason=not-installed;fi
return
fi
b=0;u=0;n=0
for spec in "$ci:$B/bin/crontab" "$ai:$B/bin/at";do
[ "${spec%%:*}" = 1 ]||continue;cf=${spec#*:};n=$((n+1))
[ -e "$cf" ]||{ u=1;continue;}
m=$(fm "$cf")||{ u=1;continue;}
vm "$m"||{ u=1;continue;}
set -- $m
[ "$2" = root ]&&wn "$1" 750||b=$((b+1))
done
stt=$(walk_modes '^/etc/(crontab$|cron([.]|/|$)|at[.](allow|deny)$)|^/var/spool/(cron|at)(/|$)' 640)||{
eu reason=check-error;return;
}
set -- $stt;b=$((b+$1));n=$((n+$3))
if [ "$b" -gt 0 ];then ef "bad=$b"
elif [ "$WRC" = 124 ];then timed_out
elif [ "$WRC" != 0 ]||[ "$u" = 1 ]||[ "$pu" = 1 ]||[ "$2" -gt 0 ];then part
else ep "files=$n";fi
}
U63(){ om "$E/sudoers" root 640;}
U67(){
stt=$(walk_modes '^/var/log/' 644)||return 1
set -- $stt
wv "$1" "$2" "$3" bad_logs log_files
}
impl(){ case $1 in vsftpd*)t=1;;proftpd*)t=2;;samba*|smb*|nmb*)t=4;;postfix*)t=8;;sendmail*)t=16;;exim*)t=32;;nfs*)t=64;;*)t=0;;esac;}
FL='function f(s,n,i,j,c,q,k,v){i=1;while(i<=length(s)){while(substr(s,i,1)~/[ \t]/)i++;if(i>length(s))break;c=substr(s,i,1);
if(c=="#")break
if(c=="\""||c=="\047"){q=c;j=i+1;while(j<=length(s)&&substr(s,j,1)!=q)j++;if(j>length(s))return "\001";v=substr(s,i+1,j-i-1);
i=j+1}
else{j=i;while(j<=length(s)&&substr(s,j,1)!~/[ \t]/)j++;v=substr(s,i,j-i);i=j}k++;if(k==n)return v}return ""}'
pkgs(){
PI=0;PU=0;PM=0
for ps_pkg in $1;do ps_rc=0;package "$ps_pkg"||ps_rc=$?
case $ps_rc in 0) PI=$((PI+1));impl "$ps_pkg";PM=$((PM|t));;1) :;;*) PU=1;;esac
done
}
units(){
UA=0;UI=0;UU=0
for us_unit in $1;do us_rc=0;service "$us_unit"||us_rc=$?
case $us_rc in 0) UA=$((UA+1));;1) continue;;3) :;;*) UU=1;continue;;esac
UI=$((UI+1));impl "$us_unit";PM=$((PM|t))
done
}
so(){
pkgs "$1";units "$2"
SU=0;[ "$PU" = 0 ]&&[ "$UU" = 0 ]||SU=1
if [ "$UI" -gt 0 ]||[ "$PI" -gt 0 ];then SO=i
elif [ "$PU" -gt 0 ]||[ "$UU" -gt 0 ];then SO=u;else SO=a;fi
}
ready(){
case $SO in i) return 0;;a) e na reason=not-installed;;*) ur;;esac
return 1
}
want(){ [ "$PM" = 0 ]||[ $((PM&$1)) -gt 0 ];}
mark(){ sn=$((sn|$1));}
cv(){ [ $((sn&PM)) -eq "$PM" ];}
cfg(){  awk '!/^[ \t]*(#|$)/{print}' "$1";}
expand_config(){ (
ek=$1;ep=$2;ed=${3:-0}
[ "$ed" -lt 12 ]||{ p '!INCOMPLETE\n';return;}
case $ep in *'`'*|*'$'*|*'{'*|*'}'*|*'%'*|*' '*|*'	'*) p '!INCOMPLETE\n';return;;esac
case $ep in "$R"/*) pattern=$ep;;/*) pattern=$R$ep;;*) pattern=$ep;;esac
parent=${pattern%/*}
case $parent in
    *'*'*|*'?'*|*'['*) :;;
    *)
        if [ -d "$parent" ]&&{ [ ! -x "$parent" ]||[ ! -r "$parent" ]; };then
            p '!access-denied\n' >&2
            p '!INCOMPLETE\n'
            return
        fi;;
esac
set +f;set -- $pattern;set -f
[ "$#" -gt 1 ]||exists "$1"||{
case $ep in *'*'*|*'?'*|*'['*) return 0;;*) p '!INCOMPLETE\n';return;;esac
}
for ef do
rd "$ef"||{ p '!INCOMPLETE\n';continue;}
if [ -d "$ef" ];then
if [ ! -x "$ef" ];then p '!access-denied\n' >&2;p '!INCOMPLETE\n';continue;fi
set +f
case $ek in xinetd|snmp) set -- "$ef"/*;;*) set -- "$ef"/*.conf;;esac
set -f
[ "$#" -gt 1 ]||exists "$1"||continue
for child do case $ek:$child in xinetd:*~|snmp:*~) continue;;esac;expand_config "$ek" "$child" "$((ed+1))";done
continue
fi
et=$(cfg "$ef")||{ p '!INCOMPLETE\n';continue;}
while IFS= read -r el||[ -n "$el" ];do
p '%s\n' "$el"
case $el in *[iI][nN][cC][lL][uU][dD][eE]*) :;;*) continue;;esac
ei=$(p '%s\n' "$el" | awk -v k="$ek" '
{line=$0;sub(/[ \t]*#.*/,"",line)}
k=="ssh"&&tolower($1)=="include"{for(i=2;i<=NF;i++)print $i}
k=="samba"&&tolower(line)~/^[ \t]*include[ \t]*=/{sub(/^[^=]*=[ \t]*/,"",line);print line}
k=="snmp"&&tolower($1)~/^include(file|dir)$/{print $2}
k=="xinetd"&&tolower($1)~/^include(dir)?$/{print $2}
k=="exim"&&$1==".include"{print $2}
k=="exim"&&$1~/^[.]include/&&$1!=".include"{print "%"}
k=="rsyslog"&&tolower($1)=="$includeconfig"{print $2}
k=="rsyslog"&&tolower(line)~/^[ \t]*include[ \t]*\(/&&match(line,/file[ \t]*=[ \t]*"[^"]*"/){v=substr(line,RSTART,RLENGTH);sub(/^[^"]*"/,"",v);sub(/"$/,"",v);print v}
')||{ p '!INCOMPLETE\n';continue;}
oldifs=$IFS;IFS='
'
for ip in $ei;do
IFS=$oldifs
case $ip in \"*\") ip=${ip#\"};ip=${ip%\"};;\'*) ip=${ip#\'};ip=${ip%\'};;esac
case $ip in /*) :;;*) case $ek in ssh) ip=/etc/ssh/$ip;;*) base=${ef%/*};ip=$base/$ip;;esac;;esac
expand_config "$ek" "$ip" "$((ed+1))"
IFS='
'
done
IFS=$oldifs
done <<EOF
$et
EOF
done
);}
effective_cfg(){
ec=$1
case $ec in
*/exim/*.conf|*/exim4/*.conf) expand_config exim "$ec";;
*/postfix/main.cf)
cfg "$ec"||return
p '!POSTFIX_MASTER\n'
if [ -e "$E/postfix/master.cf" ];then cfg "$E/postfix/master.cf"||p '!INCOMPLETE\n';else p '!INCOMPLETE\n';fi
;;
*vsftpd.conf)
et=$(cfg "$ec")||return;p '%s\n' "$et"
banner=$(p '%s\n' "$et" | awk -F= 'tolower($1)~/^[ \t]*banner_file[ \t]*$/{v=$2;sub(/[ \t]*#.*/,"",v);gsub(/^[ \t]+|[ \t]+$/,"",v)}END{print v}')
case $banner in
'') :;;
/*) if rd "$R$banner";then awk 'NF{print "ftpd_banner=" $0}' "$R$banner"||p '!INCOMPLETE\n';else p '!INCOMPLETE\n';fi;;
*) p '!INCOMPLETE\n';;
esac
;;
*) cfg "$ec";;
esac
}
records(){ awk '{sub(/#.*/,"");if($0~/^[ \t]*$/)next;if($0~/^[ \t]/)s=s " " $0;else{if(s!="")print s;s=$0}}END{print s}';}
postfix_va(){
p '%s\n' "$2" | awk -F= -v mode="$1" '
function trim(v){sub(/^[ \t]+/,"",v);sub(/[ \t]+$/,"",v);return v}
function safe(v){return v~/(reject|defer)_unauth_destination/&&v!~/(^|[, \t])permit([, \t]|$)/}
function judge(rec, a,n,r,l,d,net,s,end,pair,eq,name,value){
n=split(rec,a,/[ \t]+/)
if(a[2]!="inet"||a[8]!~/(^|\/)smtpd$/)return 3
r=recipient;l=relay;d=vrfy;net=networks;greeting=banner;s=rec
while(match(s,/-o[ \t]+/)){
s=substr(s,RSTART+RLENGTH)
if(substr(s,1,1)=="{"){end=index(s,"}");if(!end)return 2;pair=substr(s,2,end-2);s=substr(s,end+1)}
else{pair=s;sub(/[ \t].*/,"",pair);s=substr(s,length(pair)+1)}
eq=index(pair,"=");if(!eq)return 2
name=tolower(trim(substr(pair,1,eq-1)));value=tolower(trim(substr(pair,eq+1)))
if(index(value,"$")||index(value,sprintf("%c",96)))return 2
if(name=="smtpd_recipient_restrictions")r=value
else if(name=="smtpd_relay_restrictions")l=value
else if(name=="disable_vrfy_command")d=value
else if(name=="mynetworks")net=value
else if(name=="smtpd_banner")greeting=value
}
return policy(r,l,d,net,greeting)
}
function policy(r,l,d,net,greeting){
    if(mode=="mail")return d!="yes"
    if(mode=="banner")return greeting==""
    if(net~/\/0([, \t]|$)|(^|[, \t])[*]([, \t]|$)/)return 1
    return !safe(l!=""?l:r)
}
$0=="!POSTFIX_MASTER"{master=1;next}
$0=="!INCOMPLETE"{unknown=1;next}
!master{
key=tolower($1);gsub(/[ \t]/,"",key);value=tolower($2)
if(key=="smtpd_recipient_restrictions")recipient=value
else if(key=="smtpd_relay_restrictions")relay=value
else if(key=="disable_vrfy_command")vrfy=trim(value)
else if(key=="mynetworks")networks=value
else if(key=="smtpd_banner")banner=trim(value)
next
}
{master_records[++count]=$0}
END{
for(i=1;i<=count;i++){
    result=judge(master_records[i])
    if(result==3)continue
    observed=1
    if(result==1)bad=1;else if(result==2)unknown=1
}
if(!observed&&!unknown)bad=policy(recipient,relay,vrfy,networks,banner)
if(bad)exit 1;if(unknown)exit 2
}'
}
va(){
mode=$1;path=$2;text=$3
case $mode:$path in relay:*postfix*|relay:*exim*|mail:*postfix*|mail:*exim*) text=$(p '%s\n' "$text"|records)||return 2;;esac
case $mode:$path in
anon:*/exports) p '%s\n' "$text" | awk '/anon(uid|gid)[ \t]*=/{exit 1}';;
anon:*vsftpd*) p '%s\n' "$text" | awk -F= 'tolower($1)~/^[ \t]*anonymous_enable[ \t]*$/{v=tolower($2);sub(/[ \t]*#.*/,"",v);gsub(/[ \t]/,"",v)}END{exit(v!="no")}';;
anon:*proftpd*) p '%s\n' "$text" | awk 'tolower($0)~/<anonymous[ \t]/{exit 1}';;
anon:*) p '%s\n' "$text" | awk -F= 'tolower($1)~/guest ok/&&tolower($2)~/yes|true/{exit 1}';;
relay:*sendmail*) p '%s\n' "$text" | awk 'tolower($0)~/promiscuous_relay/{exit 1}';;
relay:*postfix*) postfix_va relay "$text";;
relay:*) p '%s\n' "$text"|awk -F= '{k=tolower($1);v=tolower($2);if(k~/relay_from_hosts/){ok=1;if(v~/[$]/)u=1}
if(k~/accept[ \t]+hosts/){a=1;if(v~/[+$]/&&v!~/[+]relay_from_hosts/)u=1}
if(k~/relay_from_hosts|accept[ \t]+hosts/&&v~/\/0([:; \t]|$)|(^|[:; \t])[*]([:; \t]|$)/)bad=1}END{if(bad)exit 1;if(u)exit 2;
exit!(ok&&a)}';;
mail:*sendmail*) p '%s\n' "$text" | awk 'tolower($0)~/privacyoptions/&&(tolower($0)~/goaway/||(tolower($0)~/noexpn/&&tolower($0)~/novrfy/)){ok=1}END{exit!ok}';;
mail:*postfix*) postfix_va mail "$text";;
mail:*) p '%s\n' "$text" | awk 'tolower($0)~/acl_smtp_(vrfy|expn)[ \t]*=[ \t]*accept/{exit 1}';;
banner:*vsftpd*) p '%s\n' "$text" | awk -F= 'tolower($1)~/^[ \t]*ftpd_banner[ \t]*$/{ok=(tolower($2)!~/(vsftpd|ftp|version|[0-9]+[.][0-9]+)/)}END{exit!ok}';;
banner:*) p '%s\n' "$text" | awk 'tolower($1)=="serverident"&&(tolower($2)=="off"||tolower($0)!~/(proftp|ftp|[0-9]+[.][0-9]+)/){ok=1}END{exit!ok}';;
esac
}
scan(){
mode=$1;shift;obs=0;bad=0;ur=$SU;sn=0;[ "$PM" -gt 0 ]||ur=1
for spec;do t=${spec%%:*};conf=${spec#*:};want "$t"||continue
[ -e "$conf" ]||continue;obs=$((obs+1))
case $conf in */samba/*) text=$(expand_config samba "$conf");;*) text=$(effective_cfg "$conf")||{ ur=1;continue;};;esac
case $text in *'!INCOMPLETE'*) ur=1;text=$(p '%s\n' "$text"|awk '$0!="!INCOMPLETE"');;esac
mark "$t"
rc=0;va "$mode" "$conf" "$text"||rc=$?;case $rc in 0);;1)bad=$((bad+1));;*)ur=1;;esac;done
cv||ur=1;finish "$bad" "$ur" "$obs"
}
root_list(){
RL=0
for conf in $1;do [ -e "$conf" ]||continue;text=$(cfg "$conf")||{ ur=1;continue;}
rc=0;p '%s\n' "$text" | awk '$1=="root"{ok=1}END{exit!ok}'||rc=$?
case $rc in 0) RL=1;;1) :;;*) ur=1;;esac;done
}
finish(){
if [ "$1" -gt 0 ];then ef "targets=$3" "violations=$1"
elif [ "$2" -gt 0 ]||[ "${SU-0}" -gt 0 ];then ur
else ep "targets=$3" "violations=$1";fi
}
inetd(){
    IA=0;IU=0;IS=0
    [ "$INETD_RC" = 0 ]||{ ht "$INETD_CONF" "$INETD_RC";IU=1;}
    case $XINETD_CONF in *'!INCOMPLETE'*) IU=1;;esac
    case $XINETD_CONF in *'!access-denied'*) p '!access-denied\n' >&2;IU=1;;esac
    case $XINETD_CONF in *'!tool-missing'*) p '!tool-missing\n' >&2;IU=1;;esac
    if [ "$INETD_RC" = 0 ];then
        c=$(p '%s\n' "$INETD_CONF" | awk -v p="$1" '{sub(/#.*/,"");if(NF&&tolower($0)~p)n++}END{print n+0}')||{ IU=1;c=0;}
        IA=$c;IS=$c
    fi
    c=$(p '%s\n' "$XINETD_CONF" | awk -v p="$1" '
    {sub(/#.*/,"");s=s " " tolower($0)}
    END{
        disabled="disable[ \t]*=[ \t]*yes([ \t;}]|$)"
        enabled="disable[ \t]*=[ \t]*no([ \t;}]|$)"
        if(match(s,/defaults[ \t]*[{][^}]*[}]/))off=substr(s,RSTART,RLENGTH)~disabled
        while(match(s,/service[ \t]+[^{}]*[{][^}]*[}]/)){
            block=substr(s,RSTART,RLENGTH)
            if(block~p){seen++;if(block!~disabled&&(!off||block~enabled))active++}
            s=substr(s,RSTART+RLENGTH)
        }
        if(s~/service[ \t]+/ && s~p)unknown=1
        print active+0,seen+0,unknown+0
    }')||{ IU=1;return;}
    set -- $c
    IA=$((IA+$1));IS=$((IS+$2));IU=$((IU+$3))
}
inetd_installation(){
    inetd "$1"
    if [ "$IA" -gt 0 ];then SO=i
    elif [ "$IU" -gt 0 ]&&[ "$SO" = a ];then SO=u;fi
    [ "$IU" = 0 ]||SU=1
}
disabled(){
so "$1" "$2";inetd "$3"
if [ "$UA" -gt 0 ]||[ "$IA" -gt 0 ];then ef "active=$((UA+IA))"
elif [ "$SU" -gt 0 ]||[ "$IU" -gt 0 ];then ur
elif [ "$PI" = 0 ]&&[ "$UI" = 0 ]&&[ "$IS" = 0 ];then e na reason=not-installed
else ep "active=$((UA+IA))";fi
}
U20(){
sn=0;bad=0;ur=0
for tg in "$E/inetd.conf" "$E/xinetd.conf";do exists "$tg"||continue;sn=$((sn+1))
meta=$(fm "$tg")||{ ur=1;continue;};vm "$meta"||{ ur=1;continue;};set -- $meta
[ "$#" = 3 ]||{ ur=1;continue;};[ "$2" = root ]&&wn "$1" 600||bad=1
done
if [ "$bad" = 1 ];then ef "files=$sn" "violations=$bad" "metadata=$meta";elif [ "$ur" = 1 ];then ur
elif [ "$sn" -gt 0 ];then ep "files=$sn" "violations=$bad" "metadata=$meta";else
so "$INET" "$QI";if [ "$SO" = a ];then e na reason=not-installed;else ur;fi
fi
}
U27(){
so "$RSH" "$QQ"
inetd_installation "$RSH_SERVICES"
ready||return 0
ur=$((SU+IU))
if [ "$((UA+IA))" = 0 ];then if [ "$ur" = 0 ];then ep active=0;else ur;fi;return;fi
rd "$P"||{ ur;return;}
bad=0;ck=0;homes=$(awk -F: 'NF==7{print $1 ":" $6}' "$P")||{ ur;return;}
oldifs=$IFS;IFS='
'
for row in $homes;do account=${row%%:*};home=${row#*:};exists "$R$home/.rhosts"||continue;ck=$((ck+1))
meta='';meta=$(fm "$R$home/.rhosts")||ur=1
if [ -n "$meta" ];then IFS=$oldifs;if vm "$meta";then set -- $meta;{ [ "$2" = root ]||[ "$2" = "$account" ];}&&wn "$1" 600||bad=1;else ur=1;fi;IFS='
';fi
if text=$(cfg "$R$home/.rhosts");then p '%s\n' "$text" | awk '{for(i=1;i<=NF;i++)if($i=="+")exit 1}'||bad=1;else ur=1;fi
done
IFS=$oldifs
if exists "$H";then ck=$((ck+1));meta='';meta=$(fm "$H")||ur=1
if [ -n "${meta-}" ];then if vm "$meta";then set -- $meta;[ "$2" = root ]&&wn "$1" 600||bad=1;else ur=1;fi;fi
if text=$(cfg "$H");then p '%s\n' "$text" | awk '{for(i=1;i<=NF;i++)if($i=="+")exit 1}'||bad=1;else ur=1;fi
fi
finish "$bad" "$ur" "$ck"
}
U34(){ disabled "$FINGER" "$QF" '(^|[ /])(finger|in[.]fingerd)([ /{]|$)';}
U35(){
so "$FTP $SAMBA $NFS" "$QG $QN smb smbd nmbd";inetd_installation "$FTP_SERVICES";ready||return 0
scan anon 1:"$E/vsftpd.conf" 1:"$C" 2:"$D" 4:"$E/samba/smb.conf" 64:"$X"
}
U36(){ disabled "$RSH" "$QQ" "$RSH_SERVICES";}
U38(){ disabled "$INET" "$QI $QD" '(^|[ /])(echo|discard|daytime|chargen)([ /{]|$)';}
U40(){
so "$NFS" "$QN";ready||return 0
ct=0;broad=0;bad=0;incomplete=$SU;metadata=''
if exists "$E/exports.d";then
    if [ ! -d "$E/exports.d" ];then incomplete=1
    elif [ ! -r "$E/exports.d" ]||[ ! -x "$E/exports.d" ];then
        p '!access-denied\n' >&2
        incomplete=1
    fi
fi
set +f
set -- "$X" "$E"/exports.d/*.exports
set -f
for conf do
    [ "$conf" = "$X" ]||exists "$conf"||continue
    rd "$conf"||{ incomplete=1;continue;}
    if meta=$(fm "$conf")&&vm "$meta";then
        set -- $meta
        [ -n "$metadata" ]||metadata=$meta
        if ! wn "$1" 644||[ "$2" != root ];then bad=1;metadata=$meta;fi
    else
        incomplete=1
    fi
    counts=$(awk '
    {sub(/#.*/, ""); if(sub(/\\[ \t]*$/, "")){record=record $0 " ";next}
     $0=record $0;record=""}
    NF{n++;for(i=2;i<=NF;i++)if($i~/^(\*|0[.]0[.]0[.]0\/(0|0[.]0[.]0[.]0)|::\/0)($|\()/)b++}
    END{if(record!="")exit 1;print n+0,b+0}
    ' "$conf")||{ incomplete=1;continue;}
    set -- $counts
    ct=$((ct+$1));broad=$((broad+$2))
done
if [ "$bad" = 1 ]||[ "$broad" -gt 0 ];then ef "exports=$ct" "unrestricted=$broad" "metadata=$metadata"
elif [ "$incomplete" -gt 0 ];then ur
else ep "exports=$ct" "unrestricted=$broad" "metadata=$metadata";fi
}
U41(){ disabled "$AUTO" "$QH" '(^|[ /])automountd?([ /{]|$)';}
U42(){
disabled "$RPC $INET" "$QP" \
'rpc[.](cmsd|ttdbserverd|nisd|pcnfsd|statd|ypupdated|rquotad)|(^|[ /])(sadmind|rusersd|walld|sprayd|rstatd|rexd|kcms_server|cachefsd)([ /{]|$)'
}
U43(){ disabled "$NIS" "$QJ" '(^|[ /])(ypserv|ypbind|ypxfrd)([ /{]|$)';}
U44(){ disabled "$TFTP $TALK" "$QL $QK" '(^|[ /])(tftp|talk|ntalk|in[.](tftpd|talkd|ntalkd))([ /{]|$)';}
mail(){ so "$MAIL" "$QM";}
U46(){
mail;ready||return 0
sn=0;obs=0;bad=0;ur=$SU;[ "$PM" -gt 0 ]||ur=1
if want 16&&[ -e "$M" ];then obs=$((obs+1));if text=$(cfg "$M");then mark 16
p '%s\n' "$text" | awk 'tolower($0)~/privacyoptions/&&tolower($0)~/restrictqrun/{ok=1}END{exit!ok}'||bad=1;else ur=1;fi
fi
for spec in 8:"$B/sbin/postsuper" 32:"$B/sbin/exiqgrep";do t=${spec%%:*};tg=${spec#*:};want "$t"||continue
exists "$tg"||continue;obs=$((obs+1));meta=$(fm "$tg")||{ ur=1;continue;}
vm "$meta"||{ ur=1;continue;};mark "$t";set -- $meta;[ $((0$1&1)) = 0 ]||bad=1
done
cv||ur=1
finish "$bad" "$ur" "$obs"
}
U47(){
mail;ready||return 0
scan relay 16:"$M" 8:"$E/postfix/main.cf" 32:"$E/exim/exim.conf" 32:"$E/exim4/exim4.conf"
}
U48(){
mail;ready||return 0
scan mail 16:"$M" 8:"$E/postfix/main.cf" 32:"$E/exim/exim.conf" 32:"$E/exim4/exim4.conf"
}
dns(){ so "$DNS" "$DS";}
dout(){ v=$1;c=$2;shift 2;[ "$v" != unknown ]||[ "$#" -gt 0 ]||set -- reason=incomplete;e "$v" "rules=$r" "coverage=$c" "$@";}
dr(){
dns;ready||return 0
case $BR in 0);;124) r=unknown;dout unknown unknown reason=timeout;return;;*) r=unknown;dout unknown unknown reason=incomplete;return;;esac
s=$(p '%s\n' "$BT"|awk -v k="$k" '
function ip(a){return a~/^[0-9a-f:.]+(\/[0-9]+)?$/&&a~/[.:]/}
function unquote(line,txt,a,n,v){while(match(line,/"([^"\\]|\\.)*"/)){a=RSTART;n=RLENGTH;v=substr(line,a+1,n-2);
txt=txt substr(line,1,a-1) (v=="any"||v=="none"?v:"@");line=substr(line,a+n)}q+=(line~/"/);return txt line}
{o=o " " unquote($0)}END{gsub(/^[ \t\r\n]+/,"",o);gsub(/[{};]/," & ",o);n=split(tolower(o),t,/[ \t\r\n]+/);
d=0;st[0]=1
for(i=1;i<=n;i++)if(t[i]=="{"){h=t[st[d]];if(h==k){r++;g=op[d];j=i;l=1;u=v=0;while(l&&j<n){j++;if(t[j]=="{")l++;else if(t[j]=="}")l--;else{a=t[j];
sub(/^!/,"",a);if(a~/^(any|0[.]0[.]0[.]0\/(0|0[.]0[.]0[.]0)|::\/0)$/)u=1;else if(a!~/^[;!]$/&&a!="none"&&!ip(a))v=1}}if(l)x++;
b+=u;x+=v;gl+=g&&!u&&!v}
op[++d]=h=="options";st[d]=i+1}else if(t[i]==";")st[d]=i+1;else if(t[i]=="}"){d--;st[d]=i+1}print r+0,b+0,x+q+(d!=0),gl+0}' )||{ eu rules=unknown coverage=unknown reason=check-error;return;}
set -- $s;r=$1
[ "$2" -gt 0 ]&&{ dout fail unsafe;return;}
[ "$3" = 0 ]&&[ "$SU" = 0 ]||{ dout unknown unknown;return;}
if [ "$k" = allow-transfer ]&&[ "$4" = 0 ];then dout unknown partial
elif [ "$r" = 0 ];then dout pass default-disabled
else dout pass complete;fi
}
U50(){ k=allow-transfer;dr;}
U51(){ k=allow-update;dr;}
U52(){ disabled "$TELNET" 'telnet.socket telnet' '(^|[ /])(telnet|in[.]telnetd)([ /{]|$)';}
FTP_SERVICES='(^|[ /])(ftp|in[.]ftpd|vsftpd|proftpd)([ /{]|$)'
ftp(){ so "$FTP" "$QG";inetd_installation "$FTP_SERVICES";}
U53(){
ftp;ready||return 0
scan banner 1:"$E/vsftpd.conf" 1:"$C" 2:"$D"
}
U54(){ disabled "$FTP" "$QG" "$FTP_SERVICES";}
U55(){
ftp;ready||return 0
rd "$P"||{ ur;return;};shell=$(awk -F: '$1=="ftp"{print ($7==""?"login":$7)}' "$P")||{ ur;return;}
if [ -z "$shell" ];then if [ "$SU" = 0 ];then ep "shell=$shell";else ur;fi
else case $shell in /bin/false|/sbin/nologin|/usr/sbin/nologin) if [ "$SU" = 0 ];then ep "shell=$shell";else ur;fi;;*) ef "shell=$shell";;esac;fi
}
U57(){
ftp;ready||return 0
fd=0;bad=0;ur=$SU;sn=0;[ "$PM" -gt 0 ]||ur=1
root_list "$E/ftpusers $E/ftpd/ftpusers";ftpusers=$RL
root_list "$E/vsftpd/ftpusers $E/vsftpd.ftpusers";vsusers=$RL
root_list "$E/vsftpd/user_list $E/vsftpd.user_list";userlist=$RL
if want 1;then for conf in "$E/vsftpd.conf" "$C";do [ -e "$conf" ]||continue;fd=$((fd+1));text=$(cfg "$conf")||{ ur=1;continue;};mark 1
stt=$(p '%s\n' "$text" | awk -F= '{k=tolower($1);v=tolower($2);gsub(/[ \t]/,"",k);gsub(/[ \t]/,"",v);if(k=="userlist_enable")e=v;if(k=="userlist_deny")d=v}END{print e,d}')
ul=$(p '%s\n' "$text" | awk -F= 'tolower($1)~/^[ \t]*userlist_file[ \t]*$/{v=$2;sub(/[ \t]*#.*/,"",v);gsub(/^[ \t]+|[ \t]+$/,"",v)}END{print v}')
set -- $stt;if [ "${1-no}" = no ];then [ "$ftpusers" = 1 ]||[ "$vsusers" = 1 ]||bad=1
elif [ "$1" = yes ]&&[ "${2-yes}" = yes ];then
    selected=$userlist
    case $ul in
        '') :;;
        /*) if rd "$R$ul";then root_list "$R$ul";selected=$RL;else ur=1;continue;fi;;
        *) ur=1;continue;;
    esac
    [ "$selected" = 1 ]||bad=1
else bad=1;fi
done;fi
if want 2;then for conf in "$E/proftpd.conf" "$D";do [ -e "$conf" ]||continue;fd=$((fd+1));text=$(cfg "$conf")||{ ur=1;continue;};mark 2
stt=$(p '%s\n' "$text" | awk 'tolower($1)=="useftpusers"{u=tolower($2)}tolower($1)=="rootlogin"{r=tolower($2)}END{print u,r}')
set -- $stt;if [ "${1-on}" = off ];then [ "$2" = off ]||bad=1;else [ "$ftpusers" = 1 ]||bad=1;fi
done;fi
cv||ur=1
finish "$bad" "$ur" "$fd"
}
snmp(){ so "$SNMP" "$QO";}
snmp_cfg(){ expand_config snmp /etc/snmp/snmpd.conf;}
U59(){
snmp;ready||return 0
text=$(snmp_cfg)||{ ur;return;}
ur=$SU;case $text in *'!INCOMPLETE'*) ur=1;text=$(p '%s\n' "$text"|awk '$0!="!INCOMPLETE"');;esac
stt=$(p '%s\n' "$text" | awk 'tolower($1)~/^(rouser|rwuser)$/{v3++}tolower($1)~/^(rocommunity6?|rwcommunity6?|com2sec6?)$/{old++}END{print v3+0,old+0}')||{ ur;return;}
set -- $stt
if [ "$2" -gt 0 ];then ef version=legacy-or-mi
elif [ "$1" -gt 0 ]&&[ "$ur" = 0 ];then ep version=3
elif [ "$ur" -gt 0 ];then ur
else ef version=legacy-or-mi;fi
}
U60(){
[ "$Z" = 0 ]||{ eu community=unknown;return;};snmp
case $SO in a) e na community=none;return;;u) eu community=unknown;return;;esac
all=$(snmp_cfg)||{ eu community=unknown;return;};ur=$SU
case $all in *'!INCOMPLETE'*) ur=1;all=$(p '%s\n' "$all"|awk '$0!="!INCOMPLETE"');;esac
for conf in "$V/lib/snmp/snmpd.conf" "$V/lib/net-snmp/snmpd.conf";do [ ! -e "$conf" ]||rd "$conf"||ur=1
[ ! -r "$conf" ]||all="$all
$(cfg "$conf")"||ur=1;done
result=$(p '%s\n' "$all" | awk "$FL"'
{d=tolower(f($0,1));if(d~/^com2sec6?$/)n=(f($0,2)=="-Cn"?6:4);else n=(d=="createuser"?4:2);if(d~/^(rocommunity6?|rwcommunity6?|com2sec6?|createuser)$/){v=f($0,n);
sn=1
if(v=="\001"||v=="")bad=1;else if(tolower(v)~/^(public|private)$/)r="default";else if(r!="default"&&(v!~/[[:alpha:]]/||v!~/[[:digit:]]/||(length(v)<10&&(length(v)<8||v!~/[^[:alnum:]]/))))r="weak"}}
END{if(r!="")print r;else if(bad||!sn)print "unknown";else print "ok"}')||result=unknown
case $result in default|weak) ef "community=$result";;ok) if [ "$ur" = 0 ];then ep community=ok;else eu community=unknown;fi;;*) eu community=unknown;;esac
}
U61(){
snmp;ready||return 0
text=$(snmp_cfg)||{ ur;return;}
inc=0;case $text in *'!INCOMPLETE'*) inc=1;text=$(p '%s\n' "$text"|awk '$0!="!INCOMPLETE"');;esac
stt=$(p '%s\n' "$text" | awk "$FL"'
{d=tolower(f($0,1));if(d~/^(rocommunity6?|rwcommunity6?|com2sec6?)$/){sn++;n=(d~/^com2sec6?$/&&f($0,2)=="-Cn"?5:3);v=tolower(f($0,n));if(v=="\001")bk=1
else if(v==""||v~/^(default|[*]|0[.]0[.]0[.]0\/(0|0[.]0[.]0[.]0)|::\/0)$/)bad++}else if(d~/^(rouser|rwuser)$/)sn++}
END{print sn+0,bad+0,bk+0}')||{ ur;return;}
set -- $stt;[ "$1" -gt 0 ]||set -- 0 1 "$3"
if [ "$1" = 0 ]&&[ "$((SU+$3+inc))" -gt 0 ];then finish 0 1 0
else finish "$2" "$((SU+$3+inc))" "$1";fi
}
timesyncd(){
set +f
set -- "$E/systemd/timesyncd.conf" "$E"/systemd/timesyncd.conf.d/*.conf
set -f
incomplete=$SU;config=''
for conf do
    [ -e "$conf" ]||continue
    if ! rd "$conf";then incomplete=1;continue;fi
    if ! text=$(awk '{print}' "$conf");then incomplete=1;continue;fi
    config="$config
[]
$text"
done
sv=$(p '%s\n' "$config" | awk '
    /^[ \t]*\[/ {in_time=($0~/^[ \t]*\[Time\][ \t]*$/)}
    in_time && /^[ \t]*(NTP|FallbackNTP)[ \t]*=/ {
        key=$0;sub(/=.*/, "", key);gsub(/[ \t]/, "", key)
        sub(/^[^=]*=[ \t]*/, "");sub(/[ \t]+$/, "")
        if ($0=="") count[key]=0;else count[key]+=NF
    }
    END {print count["NTP"]+count["FallbackNTP"]}
')||{ ur;return;}
timedata=$(td timedatectl show-timesync 2>&1)||{ eu "reason=$(ce "$timedata" "$?")";return; }
clock=$(td timedatectl show 2>&1)||{ eu "reason=$(ce "$clock" "$?")";return; }
if [ "$sv" = 0 ];then
    sv=$(p '%s\n' "$timedata" | awk '
        /^(Link|System|Runtime|Fallback)NTPServers=/ {sub(/^[^=]*=/, "");n+=NF}
        END {print n+0}
    ')||{ ur;return;}
fi
sync=$(p '%s\n' "$clock" | awk -F= '$1=="NTPSynchronized"{print $2}')||{ ur;return;}
sy=$(p '%s\n' "$timedata" | awk '
    /^ServerName=./ && $0 !~ /^ServerName=(n\/a|\(null\))$/ {selected=1}
    END {print selected+0}
')||{ ur;return;}
case $sync in
    no) sy=0;verdict=fail;;
    yes) if [ "$sv" = 0 ]||[ "$sy" = 0 ];then verdict=fail;else verdict=pass;fi;;
    *) ur;return;;
esac
if [ "$incomplete" -gt 0 ]&&[ "$sync" != no ];then ur;return;fi
e "$verdict" "servers=$sv" "selected=$sy" "active=$UA"
}
U65(){
so "$TIME" "$QT";ready||return 0
if service systemd-timesyncd;then timesyncd;return;fi
ht "$TO" "$TR"
fd=0;sv=0;ur=$SU
for conf in "$E/ntp.conf" "$E/chrony.conf" "$E/chrony/chrony.conf";do [ -e "$conf" ]||continue;fd=$((fd+1))
text=$(cfg "$conf")||{ ur=1;continue;};ct=$(p '%s\n' "$text" | awk 'tolower($1)~/^(server|pool)$/{n++}END{print n+0}')
sv=$((sv+ct))
done
sy=0;[ "$TR" = 0 ]&&sy=$(p '%s\n' "$TO" | awk '/^[*]|^\^\*/{n++}END{print n+0}')
if [ "$UA" = 0 ]||{ [ "$fd" -gt 0 ]&&[ "$sv" = 0 ];};then ef "servers=$sv" "selected=$sy" "active=$UA"
elif [ "$ur" -gt 0 ]||[ "$fd" = 0 ]||[ "$TR" != 0 ];then ur
elif [ "$sy" = 0 ];then ef "servers=$sv" "selected=$sy" "active=$UA";else ep "servers=$sv" "selected=$sy" "active=$UA";fi
}
U28(){
firewall=unknown;tcp_wrappers=none;listeners=unknown
for conf in "$E/nftables.conf" "$E/firewalld/firewalld.conf" "$E/ufw/ufw.conf";do rd "$conf"&&firewall=configured;done
{ rd "$E/hosts.allow"||rd "$E/hosts.deny";}&&tcp_wrappers=configured
[ "$LR" = 0 ]||{ ur;return;}
listeners=$(p '%s\n' "$LO" | awk 'NR>1{n++}END{print n+0}')
er "firewall=$firewall" "tcp_wrappers=$tcp_wrappers" "listeners=$listeners"
}
person(){
so "$1" "$2"
case $SO in a) er "$3_installed=no" "$3_active=no";;u) ur;;
i) [ "$SU" = 0 ]||{ ur;return;};[ "$UA" -gt 0 ]&&active=yes||active=no
er "$3_installed=yes" "$3_active=$active";;esac
}
U39(){ person "$NFS" "$QN" nfs;}
U56(){
ftp;case $SO in a) er ftp_access_control=not-installed rules=0;return;;u) ur;return;;esac
[ "$SU" = 0 ]||{ ur;return;}
rules=0;unreadable=0
rule_files="$E/hosts.allow $E/hosts.deny $E/vsftpd/user_list"
if want 1;then
for vs_conf in "$E/vsftpd.conf" "$C";do
exists "$vs_conf"||continue
if ! rd "$vs_conf";then unreadable=1;continue;fi
custom_list=$(cfg "$vs_conf" | awk -F= 'tolower($1)~/^[ \t]*userlist_file[ \t]*$/{v=$2;sub(/[ \t]*#.*/,"",v);gsub(/^[ \t]+|[ \t]+$/,"",v)}END{print v}')||{ unreadable=1;continue;}
case $custom_list in
'') :;;
/*)
    if ! exists "$R$custom_list";then unreadable=1
    else case " $rule_files " in *" $R$custom_list "*) :;;*) rule_files="$rule_files $R$custom_list";;esac;fi;;
*) unreadable=1;;
esac
done
fi
for conf in $rule_files;do
exists "$conf"||continue
rd "$conf"||{ unreadable=1;continue;}
ct=$(cfg "$conf" | awk 'NF{n++}END{print n+0}')||{ unreadable=1;continue;};rules=$((rules+ct))
done
[ "$unreadable" = 0 ]||{ ur;return;}
[ "$rules" -gt 0 ]&&stt=configured||stt=none;er "ftp_access_control=$stt" "rules=$rules"
}
U58(){ person "$SNMP" "$QO" snmp;}
U66(){
logging=none;destinations=0;remote=no;incomplete=0
for conf in "$E/rsyslog.conf" "$E/syslog.conf";do [ -e "$conf" ]||continue
text=$(expand_config rsyslog "$conf")||{ incomplete=1;continue;}
case $text in *'!INCOMPLETE'*) incomplete=1;text=$(p '%s\n' "$text"|awk '$0!="!INCOMPLETE"');;esac
logging=configured
ct=$(p '%s\n' "$text" | awk '
$1~/^[*a-zA-Z0-9,!;]+[.]/{legacy++}
{all=all " " tolower($0)}
END{while(match(all,/action[ \t]*\([^)]*type[ \t]*=[ \t]*"omfwd"/)){modern++;all=substr(all,RSTART+RLENGTH)}
print legacy+modern,modern+0}')||{ incomplete=1;continue;}
set -- $ct;destinations=$((destinations+$1));[ "$2" -eq 0 ]||remote=yes
p '%s\n' "$text" | awk '$0~/(^|[ \t])@@?[^; \t]+/{ok=1}END{exit!ok}'&&remote=yes
done
[ "$incomplete" = 0 ]||{ ur;return;}
er "logging=$logging" "destinations=$destinations" "remote=$remote"
}
bf(){
ck=$((ck+1))
[ -e "$1" ]||{ mi=1;return;}
rd "$1"||{ ur=1;return;}
if [ "$2" = product ];then awk 'NF{fd=1}tolower($0)~/(vsftpd|ftp|version|[0-9]+[.][0-9]+)/{bad=1}END{exit(!fd||bad)}' "$1"||mi=1
else awk 'NF{fd=1}END{exit!fd}' "$1"||mi=1;fi
}
bc(){
ck=$((ck+1));conf=''
if [ "$2" = ftpd_banner ];then
found=0
for candidate in $1;do
[ -e "$R$candidate" ]||continue;found=1
if ! rd "$R$candidate";then ur=1;continue;fi
text=$(cfg "$R$candidate")||{ ur=1;continue;}
banner_file=$(p '%s\n' "$text" | awk -F= 'tolower($1)~/^[ \t]*banner_file[ \t]*$/{v=$2;sub(/[ \t]*#.*/,"",v);gsub(/^[ \t]+|[ \t]+$/,"",v)}END{print v}')
if [ -n "$banner_file" ];then
case $banner_file in /*) saved_ck=$ck;bf "$R$banner_file" product;ck=$saved_ck;;*) ur=1;;esac
continue
fi
v=$(p '%s\n' "$text" | awk -F= 'tolower($1)~/^[ \t]*ftpd_banner[ \t]*$/{v=$2}END{gsub(/^[ \t]+|[ \t]+$/,"",v);print v}')
if [ -z "$v" ];then mi=1
elif p '%s\n' "$v" | awk 'tolower($0)~/(vsftpd|ftp|version|[0-9]+[.][0-9]+)/{bad=1}END{exit!bad}';then mi=1;fi
done
[ "$found" = 1 ]||ur=1
return
fi
if [ "$2" = version ];then [ "$BR" = 0 ]||{ ur=1;return;};text=$BT
else
for candidate in $1;do [ ! -e "$R$candidate" ]||{ conf="$R$candidate";break;};done
if [ -z "$conf" ]||! rd "$conf";then ur=1;return;fi
case $2 in
    smtpd_banner)
        text=$(effective_cfg "$conf")||{ ur=1;return;}
        text=$(p '%s\n' "$text" | records)||{ ur=1;return;}
        rc=0;postfix_va banner "$text"||rc=$?
        case $rc in 0) :;;1) mi=1;;*) ur=1;;esac
        case $text in *'!INCOMPLETE'*) ur=1;;esac
        return;;
    smtp_banner) text=$(expand_config exim "$conf")||{ ur=1;return;};;
    *) text=$(cfg "$conf")||{ ur=1;return;};;
esac
fi
partial=0
case $text in *'!INCOMPLETE'*) partial=1;ur=1;;esac
v=$(p '%s\n' "$text" | awk -v k="$2" '
{line=$0;sub(/^[ \t]*/,"",line)}
tolower(line)~"^" k "[ \t=]"{sub(/^[^ \t=]+[ \t=]*/,"",line);v=line}
END{gsub(/[";]/,"",v);print v}
')||{ ur=1;return;}
[ -n "$v" ]||{ [ "$partial" != 0 ]||mi=1;return;}
if [ "$2" = displaylogin ];then
case $v in /*) bf "$R$v";;*) ur=1;;esac
fi
}
U62(){
mi=0;ur=0;ck=0
bf "$E/motd";bf "$E/issue"
so "$SSH" 'sshd ssh'
if [ "$SO" = i ];then
if [ "$SR" != 0 ];then ur=1
else
banner=$(p '%s\n' "$J" | awk '$1=="banner"{print $2}')
case $banner in /*) bf "$R$banner";;*) mi=1;;esac
fi
ssh_text=$(expand_config ssh /etc/ssh/sshd_config)
case $ssh_text in *'!INCOMPLETE'*) ur=1;ssh_text=$(p '%s\n' "$ssh_text"|awk '$0!="!INCOMPLETE"');;esac
match_banners=$(p '%s\n' "$ssh_text" | awk '
tolower($1)=="match"{m=1;next}
m&&tolower($1)=="banner"{print $2}
')||ur=1
oldifs=$IFS;IFS='
'
for match_banner in $match_banners;do
IFS=$oldifs
case $match_banner in none) ck=$((ck+1));mi=1;;/*) bf "$R$match_banner";;*) ck=$((ck+1));ur=1;;esac
IFS='
'
done
IFS=$oldifs
elif [ "$SO" = u ];then ur=1;fi
for pkg in $TELNET $FTP $MAIL $DNS;do
rc=0;package "$pkg"||rc=$?
case $rc in 1) continue;;0) :;;*) ur=1;continue;;esac
case $pkg in
telnet*|inetutils-telnetd) bf "$E/issue.net";;
vsftpd) bc '/etc/vsftpd.conf /etc/vsftpd/vsftpd.conf' ftpd_banner;;
proftpd*) bc '/etc/proftpd/proftpd.conf /etc/proftpd.conf' displaylogin;;
postfix) bc '/etc/postfix/main.cf' smtpd_banner;;
sendmail*) bc '/etc/mail/sendmail.cf' smtpgreetingmessage;;
exim*) bc '/etc/exim4/exim4.conf /etc/exim4/exim4.conf.template /etc/exim/exim.conf' smtp_banner;;
bind*) bc '/etc/named.conf /etc/bind/named.conf.options' version;;
esac
done
finish "$mi" "$ur" "$ck"
}
INETD_CONF='';INETD_RC=0;XINETD_CONF=''
if [ "$FAM" != unknown ];then
    if exists "$E/inetd.conf";then INETD_CONF=$(cfg "$E/inetd.conf" 2>&1)||INETD_RC=$?;fi
    if exists "$E/xinetd.conf";then XINETD_CONF=$(expand_config xinetd "$E/xinetd.conf" 2>&1);fi
fi
ITEMS='U-01 U-02 U-03 U-04 U-05 U-06 U-07 U-08 U-09 U-10 U-11 U-12 U-13 U-14 U-15 U-16 U-17 U-18 U-19 U-20
U-21 U-22 U-23 U-24 U-25 U-26 U-27 U-28 U-29 U-30 U-31 U-32 U-33 U-34 U-35 U-36 U-37 U-38 U-39 U-40
U-41 U-42 U-43 U-44 U-46 U-47 U-48 U-50 U-51 U-52 U-53 U-54 U-55 U-56 U-57 U-58 U-59 U-60 U-61 U-62
U-63 U-65 U-66 U-67'
pass=0;fail=0;na=0;unknown=0;review=0;n=0
[ "$OE" != access-denied ]||[ "$Z" = 0 ]||OE=needs-approval
for ITEM in $ITEMS;do
if [ "$FAM" = unknown ];then
[ "$ITEM" != U-60 ]&&row=$(eu reason=$OE)||row=$(eu community=unknown)
else
fn=U${ITEM#U-};row=$({
set -e;
if [ "$Z" != 0 ];then case $ITEM in (U-0[1-46]|U-1[2-9]|U-2[0-9]|U-3[0-37]|U-50|U-51|U-59|U-6[12357]) eu reason=needs-approval;exit 0;;esac;fi;
case $ITEM in (U-01|U-62) ht "$J" "$SR";;esac
case $ITEM in (U-15|U-17|U-23|U-25|U-33|U-37|U-67) ht "$WALK" "$WRC";;(U-26) ht "$DEV" "$DRC";;(U-28) ht "$LO" "$LR";;esac
case $ITEM in (U-50|U-51|U-62) ht "$BT" "$BR";;esac
"$fn"
} 2>&1)
rc=$?
ec=$(ce "$row" "$rc")
row=${row##*'
'}
if [ "$ec" != incomplete ];then case $row in (*' verdict=unknown '*reason=*) row=${row%reason=*}reason=$ec;;esac;fi
if [ "$rc" != 0 ]||[ -z "$row" ];then
[ "$ec" != incomplete ]||ec=check-error
[ "$ITEM" != U-60 ]&&row=$(eu reason=${ec:-check-error})||row=$(eu community=unknown)
fi
fi
p '%s\n' "$row"
case $row in
*' verdict=pass'*) pass=$((pass+1));;*' verdict=fail'*) fail=$((fail+1));;
*' verdict=na'*) na=$((na+1));;*' verdict=review'*) review=$((review+1));;*) unknown=$((unknown+1));;
esac
n=$((n+1))
done
p 'summary pass=%s fail=%s na=%s unknown=%s review=%s\n' "$pass" "$fail" "$na" "$unknown" "$review"
p 'end items=%s complete=yes\n' "$n"
