from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.hardening import SCRIPT, Group, ItemId, Verdict, load_registry, parse_run

if TYPE_CHECKING:
    from tests.lima.conftest import LimaVM

STATES = ('absent', 'secured', 'weakened')
PROVISION = Path(__file__).with_name('provision')
P, F, N = Verdict.PASS, Verdict.FAIL, Verdict.NA

# Columns follow STATES. Service-independent observations use the image defaults.
COMMON = {
    'U-01': (F, P, F),
    'U-02': (F, F, F),
    'U-03': (F, F, F),
    'U-04': (P, P, P),
    'U-05': (P, P, P),
    'U-06': (F, F, F),
    'U-10': (P, P, P),
    'U-12': (F, F, F),
    'U-13': (P, P, P),
    'U-14': (P, P, P),
    'U-15': (P, P, P),
    'U-16': (P, P, P),
    'U-17': (P, P, P),
    'U-18': (P, P, P),
    'U-19': (P, P, P),
    'U-20': (N, P, F),
    'U-21': (F, F, F),
    'U-22': (P, P, P),
    'U-24': (P, P, P),
    'U-27': (N, P, F),
    'U-29': (P, P, P),
    'U-30': (P, P, P),
    'U-31': (P, P, F),  # The FTP account gains a login shell with a root-owned home.
    'U-32': (P, P, P),
    'U-34': (N, P, F),
    'U-35': (N, P, F),
    'U-36': (N, P, F),
    'U-37': (N, P, F),
    'U-38': (N, P, F),
    'U-40': (N, P, F),
    'U-41': (N, P, F),
    'U-42': (N, P, F),
    'U-43': (N, P, F),
    'U-44': (N, P, F),
    'U-46': (N, P, F),
    'U-47': (N, P, F),
    'U-48': (N, P, F),
    'U-50': (N, P, F),
    'U-51': (N, P, F),
    'U-52': (N, P, F),
    'U-53': (N, P, F),
    'U-54': (N, P, F),
    'U-55': (N, P, F),
    'U-57': (N, P, F),
    'U-59': (N, P, F),
    'U-60': (N, P, F),
    'U-61': (N, P, F),
    'U-62': (F, P, F),
    'U-63': (P, P, P),
    'U-65': (N, P, F),
    'U-67': (F, F, F),
}
FAMILY_OVERRIDES = {
    'debian': {
        'U-18': (F, F, F),
    },
    'rhel': {
        'U-20': (N, N, N),
        'U-34': (N, N, N),
        'U-38': (N, N, N),
        'U-43': (N, N, N),
    },
}
EXPECTED = {
    family: {
        state: {
            ItemId(item): verdicts[index]
            for item, verdicts in (COMMON | overrides).items()
        }
        for index, state in enumerate(STATES)
    }
    for family, overrides in FAMILY_OVERRIDES.items()
}

PERSON_KEYS = {
    ItemId('U-07'): {'login_accounts', 'names', 'more'},
    ItemId('U-08'): {'admin_accounts', 'names', 'more'},
    ItemId('U-09'): {'orphan_groups', 'names', 'more'},
    ItemId('U-11'): {'login_shell_accounts', 'names', 'more'},
    ItemId('U-23'): {'privileged_files', 'paths', 'more'},
    ItemId('U-25'): {'world_writable', 'paths', 'more'},
    ItemId('U-26'): {'non_device_files', 'paths', 'more'},
    ItemId('U-28'): {'firewall', 'tcp_wrappers', 'listeners'},
    ItemId('U-33'): {'hidden_paths', 'paths', 'more'},
    ItemId('U-39'): {'nfs_installed', 'nfs_active'},
    ItemId('U-56'): {'ftp_access_control', 'rules'},
    ItemId('U-58'): {'snmp_installed', 'snmp_active'},
    ItemId('U-66'): {'logging', 'destinations', 'remote'},
}


@pytest.mark.lima
@pytest.mark.parametrize('family', ['debian', 'rhel'])
def test_published_script_reports_each_provisioned_state(
    family: str, vm: LimaVM
) -> None:
    registry = load_registry()
    sha256 = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert PERSON_KEYS.keys() == {item.id for item in registry.in_group(Group.PERSON)}
    script_ids = {item.id for item in registry.in_group(Group.SCRIPT)}
    mismatches = []

    with vm.staging_directory() as directory:
        for state in STATES:
            expected = EXPECTED[family][state]
            assert expected.keys() == script_ids, state
            provision = PROVISION / family / f'{state}.sh'
            vm.copy(provision, f'{directory}/{provision.name}')
            vm.shell('sudo', '/bin/sh', f'{directory}/{provision.name}')
            vm.copy(SCRIPT, f'{directory}/{SCRIPT.name}')
            stdout = vm.shell('sudo', '/bin/sh', f'{directory}/{SCRIPT.name}')

            run = parse_run(stdout, registry, expected_sha256=sha256)
            assert run.sha256 == sha256, state
            assert run.complete, state
            assert run.family == family, state
            for item_id, verdict in expected.items():
                result = run.items[item_id]
                if result.verdict != verdict:
                    mismatches.append(
                        f'{state} {item_id}: expected {verdict}, got {result.verdict} '
                        f'{dict(result.facts)}'
                    )
            for item_id, keys in PERSON_KEYS.items():
                result = run.items[item_id]
                if result.verdict != Verdict.REVIEW or not keys <= result.facts.keys():
                    mismatches.append(
                        f'{state} {item_id}: expected review with {sorted(keys)}, '
                        f'got {result.verdict} {dict(result.facts)}'
                    )

    assert not mismatches, '\n'.join(mismatches)
