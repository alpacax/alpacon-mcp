import re
from pathlib import Path

import pytest

from tests.skill_scripts import doc_blocks, install_fakes, run_with_fakes

CHECK = 'vuln-patch/references/pending-security-updates.md'
RECIPES = 'vuln-remediate/references/recipes.md'
COMPARE = """[ "$1" != --print-architecture ] || { echo amd64; exit 0; }
[ "$1" = --compare-versions ] || exit 2
[ "$2" != "$4" ] || case "$3" in ge|le|eq) exit 0 ;; *) exit 1 ;; esac
newer=$(printf '%s\\n%s\\n' "$2" "$4" | sort -V | tail -n 1)
case "$3" in gt|ge) [ "$newer" = "$2" ] ;; lt|le) [ "$newer" = "$4" ] ;; *) exit 2 ;; esac"""
CHECK_FAKES = {
    'apt': 'echo Listing...; printf \'%s\\n\' "$APT_LIST"; exit "${APT_EXIT:-0}"',
    'apt-get': 'printf \'%s\\n\' "$SIMULATION"; exit "${SIM_EXIT:-0}"',
    'apt-mark': 'printf \'%s\\n\' "$HOLDS"; exit "${HOLDS_EXIT:-0}"',
    'apt-cache': 'printf \'%s\\n\' "$MADISON" | awk -F \' [|] \' -v p="$2" \'{k = $1; sub(/^ +/, "", k)} k == p\'; exit "${MADISON_EXIT:-0}"',
    'dpkg': COMPARE,
    'uname': 'echo 6.8.0-45-generic',
}
KERNEL_META = (
    'linux-generic/noble-updates,noble-security 6.8.0-49.49 amd64 [upgradable from: 6.8.0-45.45]\n'
    'linux-image-generic/noble-updates,noble-security 6.8.0-49.49 amd64 [upgradable from: 6.8.0-45.45]'
)
KEPT_BACK = 'The following packages have been kept back:\n  linux-generic linux-image-generic\n0 upgraded, 0 newly installed, 0 to remove and 2 not upgraded.'
TARGETS = 'openssl 3.0.13-0ubuntu3.5\nvim 2:9.1.0016-1ubuntu7.9'
APPROVED = (
    'Inst openssl [3.0.13-0ubuntu3.4] (3.0.13-0ubuntu3.5 noble-security [amd64])\n'
    'Inst vim [2:9.1.0016-1ubuntu7.8] (2:9.1.0016-1ubuntu7.9 noble-security [amd64])'
)
BEFORE = 'openssl 3.0.13-0ubuntu3.4\nvim 2:9.1.0016-1ubuntu7.8'
FIXED = 'openssl 3.0.13-0ubuntu3.5\nvim 2:9.1.0016-1ubuntu7.9'
RECIPE_FAKES = {
    'dpkg-query': """f=$BEFORE_FILE; [ ! -f "$INSTALL_MARKER" ] || f=$AFTER_FILE
awk -v p="$3" '$1 == p {print $2; found = 1} END {exit !found}' "$f\"""",
    'dpkg': COMPARE,
    'apt-get': """case "$1" in
update) echo UPDATE_REACHED ;;
-s) printf '%s\\n' "$SIMULATION"; exit "${SIM_EXIT:-0}" ;;
install) printf '%s\\n' "$@" > "$INSTALL_ARGV"; echo "$DEBIAN_FRONTEND $NEEDRESTART_MODE" > "$INSTALL_ENV"; touch "$INSTALL_MARKER"; echo INSTALL_REACHED ;;
esac""",
}


def _check(
    tmp_path: Path, shell: str, apt_list: str, simulation: str = '', **env: str
) -> tuple[dict[str, str], list[str], str]:
    """Run the documented check; returns its key=value lines, its pkg= lines, and stdout."""
    script = doc_blocks(CHECK, 'sh')[0]
    assert 'apt-mark showhold' in script, 'the first sh block is no longer the check'
    for path in (
        '/var/run/reboot-required',
        '/proc/version_signature',
        '/var/lib/apt/lists',
        '/etc/os-release',
    ):
        script = script.replace(path, str(tmp_path / Path(path).name))
    if not (tmp_path / 'os-release').exists():
        (tmp_path / 'os-release').write_text('ID=ubuntu\nVERSION_CODENAME=noble\n')
    install_fakes(tmp_path, CHECK_FAKES)
    result = run_with_fakes(
        [shell, '-c', script],
        tmp_path,
        **{'APT_LIST': apt_list, 'SIMULATION': simulation, 'HOLDS': '', 'MADISON': ''}
        | env,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    keys = dict(line.split('=', 1) for line in lines if not line.startswith('pkg='))
    return keys, [line for line in lines if line.startswith('pkg=')], result.stdout


def _recipe(
    tmp_path: Path,
    simulation: str = APPROVED,
    before: str = BEFORE,
    after: str = FIXED,
    targets: str | None = TARGETS,
    exit_code: int = 0,
    approved: str = APPROVED,
):
    """Run the documented multi-package recipe, filled with `targets` and `approved`, against a fake apt."""
    script = doc_blocks(RECIPES, 'bash')[1]
    assert 'targets=' in script, (
        'the second bash block is no longer the multi-package recipe'
    )
    if targets is not None:
        script = re.sub(r"targets='[^']*'", f"targets='{targets}'", script)
        script = re.sub(
            r"approved_changes='[^']*'", f"approved_changes='{approved}'", script
        )
    (tmp_path / 'before').write_text(before + '\n')
    (tmp_path / 'after').write_text(after + '\n')
    install_fakes(tmp_path / 'bin', RECIPE_FAKES)
    return run_with_fakes(
        ['/bin/bash', '-c', script],
        tmp_path / 'bin',
        SIMULATION=simulation,
        SIM_EXIT=str(exit_code),
        BEFORE_FILE=str(tmp_path / 'before'),
        AFTER_FILE=str(tmp_path / 'after'),
        INSTALL_MARKER=str(tmp_path / 'installed'),
        INSTALL_ARGV=str(tmp_path / 'install-argv'),
        INSTALL_ENV=str(tmp_path / 'install-env'),
    )


@pytest.mark.parametrize('shell', ['bash', 'sh'])
class TestPendingSecurityUpdatesCheck:
    def test_counts_kernel_updates_that_apt_get_upgrade_keeps_back(
        self, tmp_path: Path, shell: str
    ):
        keys, rows, _ = _check(tmp_path, shell, KERNEL_META, KEPT_BACK)

        assert keys['count'] == '2'
        assert keys['kept_back'] == 'linux-generic,linux-image-generic'
        assert keys['kernel'] == 'linux-generic,linux-image-generic'
        assert keys['upgrade'] == ''
        assert rows[0] == (
            'pkg=linux-generic installed=6.8.0-45.45 candidate=6.8.0-49.49 '
            'state=kept_back kind=kernel'
        )

    def test_lists_held_packages_apart_from_upgrades_and_kept_back_ones(
        self, tmp_path: Path, shell: str
    ):
        apt_list = (
            KERNEL_META
            + '\nvim/noble-security 2:9.1.0016-1ubuntu7.9 amd64 [upgradable from: 2:9.1.0016-1ubuntu7.8]'
            '\nsudo/noble-security 1.9.15p5-3ubuntu5.2 amd64 [upgradable from: 1.9.15p5-3ubuntu5.1]'
        )
        simulation = 'Inst vim [2:9.1.0016-1ubuntu7.8] (2:9.1.0016-1ubuntu7.9 noble-security [amd64])'

        keys, _, _ = _check(tmp_path, shell, apt_list, simulation, HOLDS='sudo')

        assert keys['count'] == '4'
        assert keys['upgrade'] == 'vim'
        assert keys['held'] == 'sudo'
        assert keys['kept_back'] == 'linux-generic,linux-image-generic'

    def test_prints_the_running_kernel_build_and_a_pending_reboot(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'version_signature').write_text(
            'Ubuntu 6.8.0-45.45-generic 6.8.12\n'
        )
        (tmp_path / 'reboot-required').write_text('*** System restart required ***\n')
        (tmp_path / 'reboot-required.pkgs').write_text(
            'linux-base\nlibc6\nlinux-base\n'
        )

        keys, _, _ = _check(tmp_path, shell, '')

        assert keys['kernel_running'] == '6.8.0-45-generic'
        assert keys['kernel_build'] == 'Ubuntu 6.8.0-45.45-generic 6.8.12'
        assert keys['reboot_required'] == 'yes'
        assert keys['reboot_required_pkgs'] == 'libc6,linux-base'

    def test_a_server_with_no_pending_reboot_or_readable_lists_says_so(
        self, tmp_path: Path, shell: str
    ):
        keys, _, _ = _check(tmp_path, shell, '')

        assert keys['reboot_required'] == 'no'
        assert keys['reboot_required_pkgs'] == ''
        assert keys['lists_updated'] == 'unknown'
        assert keys['count'] == '0'

    def test_counts_every_kernel_flavour_and_no_firmware_as_a_kernel_update(
        self, tmp_path: Path, shell: str
    ):
        apt_list = (
            'linux-oem-24.04/noble-security 6.11.0-1011.11 amd64 [upgradable from: 6.11.0-1009.9]\n'
            'linux-firmware/noble-security 20240318.git3b128b60-0ubuntu2.6 amd64 [upgradable from: 20240318.git3b128b60-0ubuntu2.5]'
        )

        keys, _, _ = _check(tmp_path, shell, apt_list)

        assert keys['kernel'] == 'linux-oem-24.04'
        assert keys['count'] == '2'

    @pytest.mark.parametrize('version', ['10', '"9"'])
    def test_debian_10_or_older_is_unknown_and_never_nothing_pending(
        self, tmp_path: Path, shell: str, version: str
    ):
        (tmp_path / 'os-release').write_text(f'ID=debian\nVERSION_ID={version}\n')

        _, _, stdout = _check(tmp_path, shell, KERNEL_META)

        assert stdout == 'count=unknown reason=release-not-covered\n'

    def test_debian_11_is_checked(self, tmp_path: Path, shell: str):
        (tmp_path / 'os-release').write_text(
            'ID=debian\nVERSION_ID="11"\nVERSION_CODENAME=bullseye\n'
        )
        apt_list = 'openssl/bullseye-security 1.1.1w-0+deb11u2 amd64 [upgradable from: 1.1.1w-0+deb11u1]'

        keys, _, _ = _check(tmp_path, shell, apt_list)

        assert keys['count'] == '1'

    @pytest.mark.parametrize(
        ('codename', 'suites'),
        [
            ('noble', 'noble-updates,noble-infra-security'),
            ('bookworm', 'bookworm-security'),
            ('bookworm', 'stable-security'),
        ],
    )
    def test_counts_every_security_suite_the_reference_covers(
        self, tmp_path: Path, shell: str, codename: str, suites: str
    ):
        distribution = 'ubuntu' if codename == 'noble' else 'debian'
        (tmp_path / 'os-release').write_text(
            f'ID={distribution}\nVERSION_CODENAME={codename}\n'
        )
        apt_list = f'openssl/{suites} 3.0.13-0ubuntu3.5 amd64 [upgradable from: 3.0.13-0ubuntu3.4]'

        keys, _, _ = _check(tmp_path, shell, apt_list)

        assert keys['count'] == '1'

    def test_leaves_out_a_third_party_suite_named_like_a_security_pocket(
        self, tmp_path: Path, shell: str
    ):
        apt_list = 'vendor-agent/vendor-security 2.0 amd64 [upgradable from: 1.0]'
        madison = ' vendor-agent | 2.0 | https://repo.vendor.example vendor-security/main amd64 Packages'

        keys, rows, _ = _check(tmp_path, shell, apt_list, MADISON=madison)

        assert keys['count'] == '0'
        assert rows == []

    def test_leaves_out_a_vendor_suite_shaped_like_an_ubuntu_pro_pocket(
        self, tmp_path: Path, shell: str
    ):
        apt_list = 'vendor-agent/noble-vendor-security 2.0 amd64 [upgradable from: 1.0]'

        keys, _, _ = _check(tmp_path, shell, apt_list)

        assert keys['count'] == '0'

    def test_a_derived_distribution_is_unknown_and_never_nothing_pending(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'os-release').write_text(
            'ID=linuxmint\nID_LIKE="ubuntu debian"\nVERSION_CODENAME=wilma\n'
        )

        _, _, stdout = _check(tmp_path, shell, KERNEL_META)

        assert stdout == 'count=unknown reason=distribution-not-covered\n'

    def test_marks_a_security_candidate_with_a_newer_pinned_fix_as_pinned(
        self, tmp_path: Path, shell: str
    ):
        apt_list = 'openssl/noble-security 3.0.13-0ubuntu3.5 amd64 [upgradable from: 3.0.13-0ubuntu3.4]'
        madison = (
            ' openssl | 3.0.13-0ubuntu3.6 | http://security.ubuntu.com/ubuntu noble-security/main amd64 Packages\n'
            ' openssl | 3.0.13-0ubuntu3.5 | http://security.ubuntu.com/ubuntu noble-security/main amd64 Packages'
        )

        keys, _, _ = _check(tmp_path, shell, apt_list, MADISON=madison)

        assert keys['pinned'] == 'openssl'
        assert keys['upgrade'] == ''

    def test_a_server_whose_release_has_no_codename_is_unknown(
        self, tmp_path: Path, shell: str
    ):
        (tmp_path / 'os-release').write_text('ID=ubuntu\n')

        _, _, stdout = _check(tmp_path, shell, KERNEL_META)

        assert stdout == 'count=unknown reason=no-codename\n'

    def test_marks_a_candidate_pinned_below_the_security_fix_as_pinned(
        self, tmp_path: Path, shell: str
    ):
        apt_list = 'openssl/noble-updates 3.0.13-0ubuntu3.5 amd64 [upgradable from: 3.0.13-0ubuntu3.4]'
        madison = (
            ' openssl | 3.0.13-0ubuntu3.6 | http://security.ubuntu.com/ubuntu noble-security/main amd64 Packages\n'
            ' openssl | 3.0.13-0ubuntu3.5 | http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages'
        )

        keys, rows, _ = _check(tmp_path, shell, apt_list, MADISON=madison)

        assert keys['count'] == '1'
        assert keys['pinned'] == 'openssl'
        assert keys['upgrade'] == ''
        assert keys['kept_back'] == ''
        assert rows == [
            (
                'pkg=openssl installed=3.0.13-0ubuntu3.4 candidate=3.0.13-0ubuntu3.5 '
                'state=pinned kind=package'
            )
        ]

    def test_names_a_foreign_architecture_package_with_its_architecture(
        self, tmp_path: Path, shell: str
    ):
        apt_list = (
            'libc6/noble-security 2.39-0ubuntu8.4 amd64 [upgradable from: 2.39-0ubuntu8.3]\n'
            'libc6/noble-security 2.39-0ubuntu8.4 i386 [upgradable from: 2.39-0ubuntu8.3]\n'
            'tzdata/noble-security 2024a-3ubuntu1.2 all [upgradable from: 2024a-3ubuntu1.1]'
        )
        simulation = (
            'Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 noble-security [amd64])\n'
            'Inst libc6:i386 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 noble-security [i386])\n'
            'Inst tzdata [2024a-3ubuntu1.1] (2024a-3ubuntu1.2 noble-security [all])'
        )

        keys, _, _ = _check(tmp_path, shell, apt_list, simulation)

        assert keys['count'] == '3'
        assert keys['upgrade'] == 'libc6,libc6:i386,tzdata'

    def test_counts_an_update_whose_security_build_is_superseded_in_updates(
        self, tmp_path: Path, shell: str
    ):
        apt_list = 'openssl/noble-updates 3.0.13-0ubuntu3.6 amd64 [upgradable from: 3.0.13-0ubuntu3.4]'
        madison = (
            ' openssl | 3.0.13-0ubuntu3.6 | http://archive.ubuntu.com/ubuntu noble-updates/main amd64 Packages\n'
            ' openssl | 3.0.13-0ubuntu3.5 | http://security.ubuntu.com/ubuntu noble-security/main amd64 Packages'
        )

        keys, rows, _ = _check(tmp_path, shell, apt_list, MADISON=madison)

        assert keys['count'] == '1'
        assert rows == [
            (
                'pkg=openssl installed=3.0.13-0ubuntu3.4 candidate=3.0.13-0ubuntu3.6 '
                'state=kept_back kind=package'
            )
        ]

    def test_leaves_out_an_update_with_no_newer_security_version(
        self, tmp_path: Path, shell: str
    ):
        apt_list = 'curl/noble-updates 8.5.0-2ubuntu10.7 amd64 [upgradable from: 8.5.0-2ubuntu10.6]'
        madison = ' curl | 8.5.0-2ubuntu10.6 | http://security.ubuntu.com/ubuntu noble-security/main amd64 Packages'

        keys, rows, _ = _check(tmp_path, shell, apt_list, MADISON=madison)

        assert keys['count'] == '0'
        assert rows == []

    @pytest.mark.parametrize(
        ('failing', 'reason'),
        [
            ('APT_EXIT', 'apt-list-failed'),
            ('SIM_EXIT', 'apt-get-simulation-failed'),
            ('HOLDS_EXIT', 'apt-mark-failed'),
            ('MADISON_EXIT', 'apt-cache-madison-failed'),
        ],
    )
    def test_a_failed_query_is_unknown_and_never_a_count_of_zero(
        self, tmp_path: Path, shell: str, failing: str, reason: str
    ):
        apt_list = (
            KERNEL_META
            + '\nopenssl/noble-updates 3.0.13-0ubuntu3.6 amd64 [upgradable from: 3.0.13-0ubuntu3.4]'
        )

        _, _, stdout = _check(tmp_path, shell, apt_list, **{failing: '100'})

        assert stdout == f'count=unknown reason={reason}\n'


class TestMultiPackageRecipe:
    def test_installs_the_approved_transaction_without_removals_or_prompts(
        self, tmp_path: Path
    ):
        result = _recipe(tmp_path)

        assert result.returncode == 0, result.stderr
        assert 'INSTALL_REACHED' in result.stdout
        assert 'vim after=2:9.1.0016-1ubuntu7.9' in result.stdout
        argv = (tmp_path / 'install-argv').read_text().splitlines()
        assert argv[-2:] == ['openssl', 'vim']
        assert '--no-remove' in argv
        assert '--only-upgrade' in argv
        options = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '-o']
        assert 'Dpkg::Options::=--force-confold' in options
        assert 'DPkg::Lock::Timeout=120' in options
        assert (tmp_path / 'install-env').read_text() == 'noninteractive l\n'

    def test_installs_the_new_kernel_packages_an_agreed_meta_package_pulls_in(
        self, tmp_path: Path
    ):
        approved = (
            'Inst linux-image-6.8.0-49-generic (6.8.0-49.49 noble-security [amd64])\n'
            'Inst linux-modules-6.8.0-49-generic (6.8.0-49.49 noble-security [amd64])\n'
            'Inst linux-generic [6.8.0-45.45] (6.8.0-49.49 noble-security [amd64])'
        )

        result = _recipe(
            tmp_path,
            simulation=approved,
            before='linux-generic 6.8.0-45.45',
            after='linux-generic 6.8.0-49.49',
            targets='linux-generic 6.8.0-49.49',
            approved=approved,
        )

        assert result.returncode == 0, result.stderr
        assert 'linux-generic after=6.8.0-49.49' in result.stdout
        argv = (tmp_path / 'install-argv').read_text().splitlines()
        assert argv[-1] == 'linux-generic'

    def test_refuses_an_approved_transaction_that_removes_a_package(
        self, tmp_path: Path
    ):
        approved = APPROVED + '\nRemv ubuntu-pro-client [32.3]'

        result = _recipe(tmp_path, simulation=approved, approved=approved)

        assert result.returncode != 0
        assert 'would remove packages' in result.stderr
        assert 'INSTALL_REACHED' not in result.stdout

    def test_refuses_a_rerun_after_part_of_the_transaction_was_installed(
        self, tmp_path: Path
    ):
        result = _recipe(
            tmp_path,
            simulation=APPROVED.splitlines()[1],
            before='openssl 3.0.13-0ubuntu3.5\nvim 2:9.1.0016-1ubuntu7.8',
        )

        assert result.returncode != 0
        assert 'the transaction changed' in result.stderr
        assert 'INSTALL_REACHED' not in result.stdout

    def test_fails_before_refreshing_when_an_agreed_package_is_not_installed(
        self, tmp_path: Path
    ):
        result = _recipe(tmp_path, before='openssl 3.0.13-0ubuntu3.4')

        assert result.returncode != 0
        assert 'vim is not installed' in result.stderr
        assert 'UPDATE_REACHED' not in result.stdout

    @pytest.mark.parametrize(
        ('simulation', 'exit_code'),
        [
            (
                APPROVED
                + '\nInst linux-image-6.8.0-49-generic (6.8.0-49.49 noble-security [amd64])',
                0,
            ),
            (APPROVED.splitlines()[0], 0),
            (APPROVED + '\nRemv ubuntu-pro-client [32.3]', 0),
            (APPROVED, 100),
        ],
    )
    def test_refuses_a_transaction_other_than_the_previewed_one(
        self, tmp_path: Path, simulation: str, exit_code: int
    ):
        result = _recipe(tmp_path, simulation, exit_code=exit_code)

        assert result.returncode != 0
        assert 'INSTALL_REACHED' not in result.stdout

    def test_fails_when_a_package_stays_below_its_previewed_version(
        self, tmp_path: Path
    ):
        result = _recipe(
            tmp_path, after='openssl 3.0.13-0ubuntu3.5\nvim 2:9.1.0016-1ubuntu7.8'
        )

        assert result.returncode != 0
        assert 'INSTALL_REACHED' in result.stdout

    @pytest.mark.parametrize(
        'targets',
        [
            'openssl;id 1.0',
            'open* 1.0',
            'OpenSSL 1.0',
            'openssl',
            'openssl 1.0$(id)',
            '-oAPT::Get::AllowUnauthenticated=1 1.0',
        ],
    )
    def test_refuses_a_target_that_is_not_a_package_and_a_version(
        self, tmp_path: Path, targets: str
    ):
        result = _recipe(tmp_path, targets=targets)

        assert result.returncode != 0
        assert 'UPDATE_REACHED' not in result.stdout

    def test_the_unfilled_template_fails_before_touching_the_server(
        self, tmp_path: Path
    ):
        result = _recipe(tmp_path, targets=None)

        assert result.returncode != 0
        assert 'UPDATE_REACHED' not in result.stdout

    @pytest.mark.parametrize(
        'before', [FIXED, 'openssl 3.0.13-0ubuntu3.6\nvim 2:9.1.0016-1ubuntu7.9']
    )
    def test_leaves_a_server_at_or_past_every_previewed_version_untouched(
        self, tmp_path: Path, before: str
    ):
        result = _recipe(tmp_path, before=before)

        assert result.returncode == 0, result.stderr
        assert 'UPDATE_REACHED' not in result.stdout
        after = [line for line in result.stdout.splitlines() if ' after=' in line]
        assert after == [
            f'{p} after={v}' for p, v in (row.split() for row in before.splitlines())
        ]


def test_the_debian_preflight_previews_every_agreed_package(tmp_path: Path):
    block = doc_blocks(RECIPES, 'sh')[0].replace(
        "pkg='openssh-server'", "pkg='openssl vim'"
    )
    assert "pkg='openssl vim'" in block, (
        'the first sh block is no longer the Debian preflight'
    )
    install_fakes(
        tmp_path,
        {
            'apt-get': 'printf \'%s\\n\' "$*" >> "$APT_ARGV"; echo "Inst openssl [1] (2 noble-security [amd64])"'
        },
    )

    run_with_fakes(['/bin/sh', '-c', block], tmp_path, APT_ARGV=str(tmp_path / 'argv'))

    calls = (tmp_path / 'argv').read_text().splitlines()
    assert calls == [
        '-s -q install --only-upgrade openssl vim',
        '-q --print-uris -y install --only-upgrade openssl vim',
    ]


def test_the_debian_preflight_passes_a_pattern_shaped_name_literally(tmp_path: Path):
    (tmp_path / 'openssl').write_text('')
    pattern = str(tmp_path / 'open*')
    block = doc_blocks(RECIPES, 'sh')[0].replace(
        "pkg='openssh-server'", f"pkg='{pattern}'"
    )
    install_fakes(
        tmp_path / 'bin',
        {'apt-get': 'printf \'%s\\n\' "$*" >> "$APT_ARGV"'},
    )

    run_with_fakes(
        ['/bin/sh', '-c', block], tmp_path / 'bin', APT_ARGV=str(tmp_path / 'argv')
    )

    calls = (tmp_path / 'argv').read_text().splitlines()
    assert calls[0] == f'-s -q install --only-upgrade {pattern}'
