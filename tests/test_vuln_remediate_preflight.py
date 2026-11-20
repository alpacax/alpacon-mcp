import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.skill_scripts import doc_blocks, install_fakes, run_with_fakes

type Filesystems = dict[str, tuple[str, int, int, int]]

DEB_SIM = 'Inst openssh-server [1:9.6p1-3ubuntu13.4] (1:9.6p1-3ubuntu13.5 noble-updates [amd64])'
DEB_KERNEL_SIM = (
    DEB_SIM + '\nInst linux-image-6.8.0-50-generic (6.8.0-50.51 noble [amd64])'
)
DEB_URIS = """Need to get 2048 kB of archives.
After this operation, 3072 kB of additional disk space will be used.
'http://archive.ubuntu.com/openssh-server.deb' openssh-server.deb 2097152 MD5Sum:00"""
DEB_NEED = 2048 + 3000  # download plus growth, both in KiB
DEB_EMPTY = '0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.'
ONE_FS: Filesystems = {'/': ('/', 10_000_000, 500_000, 400_000)}
WITH_BOOT: Filesystems = {**ONE_FS, '/boot': ('/boot', 50_000, 9, 9)}
PREFLIGHT_FAKES = {
    'df': """[ "$2" != "$DF_MISSING" ] || exit 1
row=$(awk -F '\\t' -v p="$2" '$1 == p' "$DF_TABLE"); [ -n "$row" ] || exit 1
field() { printf '%s\\n' "$row" | cut -f "$1"; }
[ "$(field 3)" != missing ] || exit 1; echo header
if [ "$1" = -Pk ]; then echo "${DF_SOURCE:-$(field 7)} 1 1 $(field 2) 1% $(field 3)"; else echo "${DF_SOURCE:-$(field 7)} $(field 4) 1 $(field 5) 1% $(field 3)"; fi""",
    'apt-get': """case "$1 $2" in
-s*) printf '%s\\n' "$SIMULATION"; exit "${SIM_EXIT:-0}" ;;
*--print-uris*) printf '%s\\n' "$URIS"; exit "${URIS_EXIT:-0}" ;;
esac; exit 2""",
    'dpkg': """case "$1" in
--audit) printf '%s' "$AUDIT"; [ -z "$AUDIT_EXIT" ] || exit "$AUDIT_EXIT"; [ -z "$AUDIT" ] ;;
-L) echo /usr/sbin/sshd; echo /usr/lib/systemd/system/ssh.service ;;
esac""",
    'dnf': """[ "$1" != --version ] || { printf '%s\\n' "${DNF_VERSION-4.14.0}"; exit 0; }
printf '%s\\n' "$DNF_OUT"; exit "${DNF_EXIT:-1}\"""",
    'rpm': 'echo /usr/lib/systemd/system/sshd.service',
    'stat': """[ "$1" = -L ] || { echo 999; exit 0; }  # without -L a symlink reports its own device
[ -z "$STAT_FAILS" ] || exit 1
awk -F '\\t' -v p="$4" '$1 == p {print $6; f = 1} END {exit !f}' "$DF_TABLE\"""",
    'systemctl': 'echo inactive; exit 3',
    'apt-config': """printf "cache='%s'\\n" "${APT_CACHE-/var/cache/apt/archives/}\"""",
}
DNF4 = """Dependencies resolved.
 Package          Arch    Version          Repository  Size
Upgrading:
 openssh-server   x86_64  8.7p1-43.el9     baseos      456 k
Total download size: 5.6 M
Operation aborted."""
DNF4_NEED = '5735+unknown'  # dnf 4 never prints the growth
DNF5 = """Package         Arch   Version       Repository  Size
Upgrading:
 openssh-server x86_64 9.8p1-1.fc41  updates     1.2 MiB
Total size of inbound packages is 685 KiB. Need to download 685 KiB.
After this operation, 2 MiB extra will be used (install 3 MiB, remove 1 MiB).
Operation aborted by the user."""
DNF5_NEED = 685 + 2048
DNF5_VERSION = 'dnf5 version 5.2.17.0'
PATHS = [
    '/',
    '/usr',
    '/var',
    '/var/cache/apt/archives',
    '/var/cache/dnf',
    '/var/cache/libdnf5',
    '/srv/cache',
    '/boot',
]


def _root(free: int) -> Filesystems:
    """One filesystem holding every path, with `free` KiB."""
    return {'/': ('/', free, 9, 9)}


def _listed(keys: dict[str, str], key: str) -> list[str]:
    """The comma-separated values of an `anomaly` or `unreadable` line."""
    return keys[key].split(',')


def _preflight(
    tmp_path: Path,
    distro: str,
    shell: str = 'sh',
    filesystems: Filesystems = ONE_FS,
    options: dict[str, str] | None = None,
    devices: dict[str, str] | None = None,
    sources: dict[str, str] | None = None,
    **env: str,
) -> tuple[dict[str, str], subprocess.CompletedProcess[str]]:
    """
    Run the documented preflight block; filesystems maps a path to (mount, free KiB, inodes, free inodes).
    devices and sources map a path to the mount whose device number or df source it shares.
    """
    block = doc_blocks('vuln-remediate/references/recipes.md', 'sh')[distro == 'rpm']

    def nearest(
        p: str,
    ) -> str:  # a path not listed shares its closest listed ancestor's filesystem
        return max(
            (k for k in filesystems if p == k or p.startswith(k.rstrip('/') + '/')),
            key=len,
        )

    table = [(p, *filesystems[nearest(p)]) for p in PATHS]
    ids = {m: str(n) for n, m in enumerate(sorted({t[1] for t in table}))}
    (tmp_path / 'df-table').write_text(
        ''.join(
            f'{p}\t{free}\t{mount}\t{inodes}\t{ifree}\t{ids[(devices or {}).get(nearest(p), mount)]}'
            f'\t/dev/disk{ids[(sources or devices or {}).get(nearest(p), mount)]}\n'
            for p, mount, free, inodes, ifree in table
        )
    )
    if not env.pop(
        'NO_MOUNTS', ''
    ):  # leave the mount table missing, as in a chroot without /proc
        (tmp_path / 'mounts').write_text(
            ''.join(
                f'dev {m.replace(" ", chr(92) + "040")} ext4 {(options or {}).get(m, "rw,relatime")} 0 0\n'
                for m in {mount for _, mount, *_ in table}
            )
        )
    (tmp_path / 'meminfo').write_text(
        'MemTotal: 4000000 kB\nMemAvailable: 1234567 kB\n'
    )
    (tmp_path / 'dnf.conf').write_text(env.pop('DNF_CONF', '[main]\n'))
    block = block.replace('/proc/mounts', str(tmp_path / 'mounts'))
    block = block.replace('/proc/meminfo', str(tmp_path / 'meminfo'))
    block = block.replace('/etc/dnf/dnf.conf', str(tmp_path / 'dnf.conf'))
    install_fakes(tmp_path / 'bin', PREFLIGHT_FAKES)
    result = run_with_fakes(
        [shutil.which(shell) or shell, '-c', block],
        tmp_path / 'bin',
        **{
            'DF_TABLE': str(tmp_path / 'df-table'),
            'SIMULATION': DEB_SIM,
            'URIS': DEB_URIS,
            'AUDIT': '',
            'DNF_OUT': '',
            **env,
        },
    )
    keys = dict(re.findall(r'^([a-z0-9_]+)=(.*)$', result.stdout, re.M))
    return keys, result


class TestDebianPreflight:
    # happy path
    @pytest.mark.parametrize('shell', ['sh', 'bash'])
    def test_reports_the_facts_and_the_preview_of_a_healthy_server(
        self, tmp_path: Path, shell: str
    ):
        keys, result = _preflight(tmp_path, 'deb', shell)

        assert result.returncode == 0, result.stderr
        assert keys['transaction'] == 'changes'
        assert keys['disk_free_root'] == '10000000'
        assert keys['disk_need_root'] == str(DEB_NEED)
        assert keys['inode_free_root'] == '400000'
        assert keys['mount_root'] == 'rw'
        assert keys['units'] == 'ssh.service'
        assert keys['kubelet'] == 'inactive'
        assert keys['mem_available'] == '1234567'
        assert keys['anomaly'] == 'none'
        assert keys['unreadable'] == 'none'
        assert result.stdout.rstrip().endswith(DEB_SIM)

    def test_needs_nothing_on_an_already_fixed_server(self, tmp_path: Path):
        keys, result = _preflight(tmp_path, 'deb', SIMULATION=DEB_EMPTY, URIS=DEB_EMPTY)

        assert result.returncode == 0
        assert keys['transaction'] == 'empty'
        assert keys['disk_need_root'] == '0'
        assert keys['anomaly'] == 'none'

    # unhappy paths
    @pytest.mark.parametrize(
        ('filesystems', 'options', 'audit', 'anomaly'),
        [
            (_root(4000), None, '', 'disk_root'),
            ({'/': ('/', 10_000_000, 500, 0)}, None, '', 'inode_root'),
            (ONE_FS, {'/': 'ro,relatime'}, '', 'ro_root'),
            (ONE_FS, None, 'openssh-server  half-configured\n', 'dpkg_audit'),
        ],
    )
    def test_names_each_factual_anomaly(
        self,
        tmp_path: Path,
        filesystems: Filesystems,
        options: dict[str, str] | None,
        audit: str,
        anomaly: str,
    ):
        keys, result = _preflight(
            tmp_path, 'deb', filesystems=filesystems, options=options, AUDIT=audit
        )

        assert result.returncode == 0, result.stderr
        assert keys['anomaly'] == anomaly
        assert keys['unreadable'] == 'none'

    def test_names_every_anomaly_it_finds_on_one_line(self, tmp_path: Path):
        keys, _ = _preflight(
            tmp_path,
            'deb',
            filesystems={'/': ('/', 10_000_000, 500, 0)},
            options={'/': 'ro,relatime'},
            AUDIT='openssh-server  half-configured\n',
        )

        assert keys['anomaly'] == 'dpkg_audit,inode_root,ro_root'

    def test_marks_a_failed_preview_unreadable_and_keeps_its_status(
        self, tmp_path: Path
    ):
        keys, result = _preflight(
            tmp_path, 'deb', SIM_EXIT='100', SIMULATION='E: broken'
        )

        assert result.returncode == 100
        assert keys['transaction'] == 'unreadable'
        assert 'transaction' in _listed(keys, 'unreadable')

    @pytest.mark.parametrize(
        ('env', 'filesystems', 'unreadable'),
        [
            ({'URIS_EXIT': '100'}, ONE_FS, 'disk_need_root'),
            ({'URIS': 'Need to get 2048 kB of archives.'}, ONE_FS, 'disk_need_root'),
            (
                {
                    'URIS': 'After this operation, 3 parsecs of additional disk space will be used.'
                },
                ONE_FS,
                'disk_need_root',
            ),
            (
                {},
                {'/': ('/', 10_000_000, 9, 9), '/var': ('missing', 0, 0, 0)},
                'disk_var',
            ),
            ({'AUDIT_EXIT': '2'}, ONE_FS, 'dpkg_audit'),
        ],
    )
    def test_reports_a_value_it_could_not_read_as_unreadable(
        self,
        tmp_path: Path,
        env: dict[str, str],
        filesystems: Filesystems,
        unreadable: str,
    ):
        keys, _ = _preflight(
            tmp_path, 'deb', 'sh', filesystems, None, None, None, **env
        )

        assert unreadable in _listed(keys, 'unreadable')
        assert keys['anomaly'] == 'none'

    def test_a_device_number_that_cannot_be_read_off_dev_is_unreadable(
        self, tmp_path: Path
    ):
        keys, _ = _preflight(tmp_path, 'deb', DF_SOURCE='tmpfs', STAT_FAILS='1')

        assert 'disk_var' in _listed(keys, 'unreadable')

    def test_a_missing_mount_table_leaves_every_mount_unreadable(self, tmp_path: Path):
        keys, _ = _preflight(tmp_path, 'deb', NO_MOUNTS='1')

        assert keys['mount_root'] == 'unreadable'
        assert keys['unreadable'] == 'mount_root'
        assert keys['anomaly'] == 'none'

    # edge cases
    @pytest.mark.parametrize(
        ('free', 'anomaly'), [(DEB_NEED, 'none'), (DEB_NEED - 1, 'disk_root')]
    )
    def test_free_space_equal_to_the_need_is_enough(
        self, tmp_path: Path, free: int, anomaly: str
    ):
        keys, _ = _preflight(tmp_path, 'deb', filesystems=_root(free))

        assert keys['anomaly'] == anomaly

    def test_judges_each_filesystem_against_its_own_share(self, tmp_path: Path):
        filesystems = {'/': ('/', 10_000_000, 9, 9), '/var': ('/var', 2000, 9, 9)}

        keys, _ = _preflight(tmp_path, 'deb', filesystems=filesystems)

        assert keys['disk_need_var'] == '2048'
        assert keys['disk_need_root'] == '3000'
        assert keys['anomaly'] == 'disk_var'

    def test_judges_the_download_on_the_package_cache_filesystem(self, tmp_path: Path):
        filesystems = {**ONE_FS, '/var/cache/apt/archives': ('/var/cache', 1000, 9, 9)}

        keys, _ = _preflight(tmp_path, 'deb', filesystems=filesystems)

        assert keys['disk_need_var_cache'] == '2048'
        assert keys['disk_need_root'] == '3000'
        assert keys['anomaly'] == 'disk_var_cache'

    @pytest.mark.parametrize(
        ('apt_cache', 'label'), [('/srv/cache/', 'srv_cache'), ('', 'var_cache')]
    )
    def test_reads_the_package_cache_apt_is_configured_with(
        self, tmp_path: Path, apt_cache: str, label: str
    ):
        filesystems = {
            **ONE_FS,
            '/var/cache/apt/archives': ('/var/cache', 10_000_000, 9, 9),
            '/srv/cache': ('/srv/cache', 10_000_000, 9, 9),
        }

        keys, _ = _preflight(
            tmp_path, 'deb', filesystems=filesystems, APT_CACHE=apt_cache
        )

        assert keys[f'disk_need_{label}'] == '2048'

    def test_a_bind_mount_of_one_filesystem_is_judged_as_one_space(
        self, tmp_path: Path
    ):
        filesystems = {'/': ('/', 4000, 9, 9), '/var': ('/var', 4000, 9, 9)}

        keys, _ = _preflight(
            tmp_path, 'deb', filesystems=filesystems, devices={'/var': '/'}
        )

        assert keys['disk_need_root'] == str(DEB_NEED)
        assert 'disk_need_var' not in keys
        assert keys['anomaly'] == 'disk_root'

    def test_btrfs_subvolumes_of_one_pool_are_judged_as_one_space(self, tmp_path: Path):
        filesystems = {'/': ('/', 4000, 0, 0), '/var': ('/var', 4000, 0, 0)}

        keys, _ = _preflight(
            tmp_path, 'deb', filesystems=filesystems, sources={'/var': '/'}
        )

        assert keys['disk_need_root'] == str(DEB_NEED)
        assert keys['anomaly'] == 'disk_root'

    @pytest.mark.parametrize(
        ('devices', 'need_root', 'anomaly'),
        [({'/var': '/'}, str(DEB_NEED), 'disk_root'), (None, '3000', 'none')],
    )
    def test_groups_a_filesystem_outside_dev_by_its_device_number(
        self,
        tmp_path: Path,
        devices: dict[str, str] | None,
        need_root: str,
        anomaly: str,
    ):
        filesystems = {'/': ('/', 4000, 9, 9), '/var': ('/var', 4000, 9, 9)}

        keys, _ = _preflight(
            tmp_path, 'deb', filesystems=filesystems, devices=devices, DF_SOURCE='tmpfs'
        )

        assert keys['disk_need_root'] == need_root
        assert keys['anomaly'] == anomaly
        assert keys['unreadable'] == 'none'

    @pytest.mark.parametrize(
        ('after', 'need'),
        [
            ('After this operation, 1024 kB disk space will be freed.', 2048),
            (
                'After this operation, 3 MB of additional disk space will be used.',
                2048 + 2930,
            ),
        ],
    )
    def test_reads_a_shrinking_upgrade_and_larger_units(
        self, tmp_path: Path, after: str, need: int
    ):
        uris = DEB_URIS.replace(DEB_URIS.splitlines()[1], after)

        keys, _ = _preflight(tmp_path, 'deb', URIS=uris)

        assert keys['disk_need_root'] == str(need)
        assert keys['unreadable'] == 'none'

    def test_a_full_filesystem_is_an_anomaly_even_when_its_need_is_unknown(
        self, tmp_path: Path
    ):
        filesystems = {**ONE_FS, '/boot': ('/boot', 0, 9, 9)}

        keys, _ = _preflight(
            tmp_path, 'deb', filesystems=filesystems, SIMULATION=DEB_KERNEL_SIM
        )

        assert keys['disk_need_boot'] == 'unknown'
        assert keys['anomaly'] == 'disk_boot'

    def test_a_mount_point_with_a_space_is_read_whole(self, tmp_path: Path):
        filesystems = {**ONE_FS, '/var': ('/srv/package cache', 10_000_000, 9, 9)}

        keys, _ = _preflight(tmp_path, 'deb', filesystems=filesystems)

        assert keys['mount_srv_package_cache'] == 'rw'
        assert keys['unreadable'] == 'none'

    def test_checks_boot_only_when_a_kernel_is_in_the_transaction(self, tmp_path: Path):
        (tmp_path / 'kernel').mkdir()
        (tmp_path / 'plain').mkdir()

        keys, _ = _preflight(
            tmp_path / 'kernel', 'deb', filesystems=WITH_BOOT, SIMULATION=DEB_KERNEL_SIM
        )
        plain, _ = _preflight(tmp_path / 'plain', 'deb', filesystems=WITH_BOOT)

        assert keys['mount_boot'] == 'rw'
        assert keys['disk_need_boot'] == 'unknown'
        assert keys['anomaly'] == 'none'
        assert 'mount_boot' not in plain

    @pytest.mark.parametrize(
        'line',
        [
            'Conf linux-image-6.8.0-50-generic (6.8.0-50.51 noble [amd64])',
            'Inst linux-modules-6.8.0-50-generic (6.8.0-50.51 noble [amd64])',
        ],
    )
    def test_every_kernel_package_line_brings_boot_in(self, tmp_path: Path, line: str):
        keys, _ = _preflight(
            tmp_path, 'deb', filesystems=WITH_BOOT, SIMULATION=f'{DEB_SIM}\n{line}'
        )

        assert keys['mount_boot'] == 'rw'

    @pytest.mark.parametrize(
        'simulation',
        [
            'Conf openssh-server (1:9.6p1-3ubuntu13.5 noble-updates [amd64])',
            'Remv openssh-server [1:9.6p1-3ubuntu13.4]',
        ],
    )
    def test_counts_a_pending_configure_or_a_removal_as_a_change(
        self, tmp_path: Path, simulation: str
    ):
        keys, _ = _preflight(tmp_path, 'deb', SIMULATION=simulation)

        assert keys['transaction'] == 'changes'


class TestRpmPreflight:
    # happy path
    @pytest.mark.parametrize(
        ('output', 'need'), [(DNF4, DNF4_NEED), (DNF5, str(DNF5_NEED))]
    )
    def test_reports_the_sizes_dnf_prints_for_a_healthy_server(
        self, tmp_path: Path, output: str, need: str
    ):
        keys, result = _preflight(tmp_path, 'rpm', DNF_OUT=output)

        assert result.returncode == 1  # dnf --assumeno answers no by design
        assert keys['transaction'] == 'changes'
        assert keys['disk_need_root'] == need
        assert keys['units'] == 'sshd.service'
        assert keys['anomaly'] == 'none'
        assert keys['unreadable'] == 'none'

    def test_needs_nothing_when_dnf_has_nothing_to_do(self, tmp_path: Path):
        keys, _ = _preflight(
            tmp_path,
            'rpm',
            DNF_OUT='Dependencies resolved.\nNothing to do.\nComplete!',
            DNF_EXIT='0',
        )

        assert keys['transaction'] == 'empty'
        assert keys['unreadable'] == 'none'

    # unhappy paths
    @pytest.mark.parametrize(('output', 'free'), [(DNF4, 5000), (DNF5, 2000)])
    def test_names_a_filesystem_too_small_for_the_sizes_dnf_prints(
        self, tmp_path: Path, output: str, free: int
    ):
        keys, _ = _preflight(tmp_path, 'rpm', filesystems=_root(free), DNF_OUT=output)

        assert keys['anomaly'] == 'disk_root'

    def test_marks_a_failed_preview_unreadable(self, tmp_path: Path):
        keys, _ = _preflight(
            tmp_path, 'rpm', DNF_OUT='Error: Failed to download metadata for repo'
        )

        assert keys['transaction'] == 'unreadable'
        assert 'transaction' in _listed(keys, 'unreadable')

    @pytest.mark.parametrize(
        'output',
        [
            DNF4.replace('Total download size: 5.6 M\n', ''),
            DNF4.replace('5.6 M', '5.6 X'),
        ],
    )
    def test_leaves_a_size_it_cannot_read_unreadable(self, tmp_path: Path, output: str):
        keys, _ = _preflight(tmp_path, 'rpm', DNF_OUT=output)

        assert keys['disk_need_root'] == 'unreadable'
        assert 'disk_need_root' in _listed(keys, 'unreadable')
        assert keys['anomaly'] == 'none'

    @pytest.mark.parametrize(
        ('conf', 'version'),
        [('[main]\ncachedir = cache\n', '4.14.0'), ('[main]\n', '')],
    )
    def test_leaves_a_cache_it_cannot_place_unreadable(
        self, tmp_path: Path, conf: str, version: str
    ):
        keys, _ = _preflight(
            tmp_path, 'rpm', DNF_OUT=DNF4, DNF_CONF=conf, DNF_VERSION=version
        )

        assert 'package_cache' in _listed(keys, 'unreadable')

    # edge cases
    def test_needs_no_download_when_dnf4_has_every_package_cached(self, tmp_path: Path):
        output = DNF4.replace('Total download size: 5.6 M', 'Total size: 600 M')

        keys, _ = _preflight(
            tmp_path, 'rpm', filesystems=_root(500 * 1024), DNF_OUT=output
        )

        assert keys['disk_need_root'] == '0+unknown'
        assert keys['anomaly'] == 'none'

    @pytest.mark.parametrize(
        ('output', 'need'),
        [
            (
                DNF5.replace('After this operation, ', 'After this operation '),
                DNF5_NEED,
            ),
            (
                DNF5.replace('2 MiB extra will be used', '2 MiB will be freed'),
                685,
            ),
            (
                DNF5.replace('685 KiB', '1 GiB').replace('2 MiB extra', '2 GiB extra'),
                1024**2 + 2 * 1024**2,
            ),
        ],
    )
    def test_reads_every_way_dnf5_writes_the_growth(
        self, tmp_path: Path, output: str, need: int
    ):
        keys, _ = _preflight(tmp_path, 'rpm', DNF_OUT=output)

        assert keys['disk_need_root'] == str(need)
        assert keys['unreadable'] == 'none'

    @pytest.mark.parametrize(
        ('version', 'conf', 'cache'),
        [
            ('4.14.0', '[main]\n', '/var/cache/dnf'),
            (DNF5_VERSION, '[main]\n', '/var/cache/libdnf5'),
            ('4.14.0', '[main]\ncachedir = /srv/cache\n', '/srv/cache'),
        ],
    )
    def test_judges_the_download_on_the_cache_dnf_uses(
        self, tmp_path: Path, version: str, conf: str, cache: str
    ):
        filesystems = {
            **ONE_FS,
            '/var/cache/dnf': ('/var/cache/dnf', 10_000_000, 9, 9),
            '/var/cache/libdnf5': ('/var/cache/libdnf5', 10_000_000, 9, 9),
            '/srv/cache': ('/srv/cache', 10_000_000, 9, 9),
            cache: (cache, 1000, 9, 9),
        }

        keys, _ = _preflight(
            tmp_path,
            'rpm',
            filesystems=filesystems,
            DNF_OUT=DNF4,
            DNF_VERSION=version,
            DNF_CONF=conf,
        )

        label = cache.strip('/').replace('/', '_')
        assert keys[f'disk_need_{label}'] == '5735'
        assert keys['anomaly'] == f'disk_{label}'

    def test_falls_back_to_the_nearest_existing_cache_parent(self, tmp_path: Path):
        keys, _ = _preflight(
            tmp_path,
            'rpm',
            DNF_OUT=DNF5,
            DNF_VERSION=DNF5_VERSION,
            DF_MISSING='/var/cache/libdnf5',
        )

        assert keys['disk_need_root'] == str(DNF5_NEED)
        assert keys['unreadable'] == 'none'

    @pytest.mark.parametrize(
        'kernel', ['kernel-core', 'kernel-rt-core', 'kernel-debug-core', 'kernel']
    )
    def test_reads_boot_for_every_kernel_flavor(self, tmp_path: Path, kernel: str):
        output = DNF4.replace(
            'Total download',
            f' {kernel}  x86_64  5.14.0-503.el9   baseos      18 M\nTotal download',
        )

        keys, _ = _preflight(tmp_path, 'rpm', filesystems=WITH_BOOT, DNF_OUT=output)

        assert keys['mount_boot'] == 'rw'

    def test_never_runs_dpkg_audit(self, tmp_path: Path):
        keys, _ = _preflight(tmp_path, 'rpm', DNF_OUT=DNF4, AUDIT='half-configured\n')

        assert 'dpkg_audit' not in _listed(keys, 'anomaly')
