import json
import os
import re
from inspect import Parameter, signature
from pathlib import Path

import pytest

from tests.hardening import (
    ATTACK_SUBSET,
    ITEMS_MD,
    SCRIPT,
    SKILL_MD,
    Group,
    ItemId,
    Verdict,
    build_attack_subset,
    load_attack,
    load_registry,
    parse_run,
    render_derived,
)

PERSON = {7, 8, 9, 11, 23, 25, 26, 28, 33, 39, 56, 58, 66}
POINTER = {45, 49, 64}
UNMAPPED = {'U-32', 'U-41', 'U-50', 'U-53', 'U-59', 'U-62', 'U-65'}
DIGEST = 'a' * 64
BUNDLE_SHA256 = '539a843a7b53ed9749740b2123dddae3726b1a4831841c32aca740b011b910b5'


def output(*, omit: int | None = None) -> str:
    rows = [
        (
            'hardening protocol=1 edition=kisa-2026 family=debian '
            f'os=ubuntu-24.04 uid=0 sha256={DIGEST}'
        )
    ]
    for n in range(1, 68):
        if n in POINTER or n == omit:
            continue
        verdict = 'review' if n in PERSON else 'pass'
        fact = ' community=ok' if n == 60 else ''
        rows.append(f'item id=U-{n:02} verdict={verdict}{fact}')
    rows.extend(
        [
            f'summary pass={51 - (omit is not None and omit not in PERSON)} fail=0 na=0 unknown=0 review={13 - (omit in PERSON)}',
            f'end items={64 - (omit is not None)} complete=yes',
        ]
    )
    return '\n'.join(rows) + '\n'


def test_registry_has_every_kisa_item_once_in_number_order():
    registry = load_registry()

    assert [item.id for item in registry.items] == [f'U-{n:02}' for n in range(1, 68)]
    assert registry.edition == 'kisa-2026'
    assert registry.attack_release == '20.1'


def test_registry_uses_the_agreed_groups():
    registry = load_registry()

    assert len(registry.in_group(Group.SCRIPT)) == 51
    assert {item.id for item in registry.in_group(Group.PERSON)} == {
        f'U-{n:02}' for n in PERSON
    }
    assert {item.id for item in registry.in_group(Group.POINTER)} == {
        f'U-{n:02}' for n in POINTER
    }
    assert len(registry.run_ids()) == 64


def test_every_mapping_is_a_live_linux_mitigation_relationship():
    registry = load_registry()
    attack = load_attack()

    unmapped = {
        item.id for item in registry.in_group(Group.SCRIPT) if item.mitigation is None
    }
    assert unmapped == UNMAPPED
    for item in registry.in_group(Group.SCRIPT):
        if not item.mappings:
            assert not item.techniques
            continue
        for mapping in item.mappings:
            assert mapping.mitigation in attack.mitigations
            assert mapping.techniques
            for technique in mapping.techniques:
                assert (mapping.mitigation, technique) in attack.mitigates
                assert attack.techniques[technique].linux
    assert attack.release == '20.1'
    assert len(attack.mitigations) == 44
    assert attack.bundle_sha256 == BUNDLE_SHA256


def test_fixed_mapping_choices_are_preserved():
    registry = load_registry()
    items = {item.id: item for item in registry.items}

    assert (items['U-18'].mitigation, items['U-18'].techniques) == (
        'M1026',
        ('T1003.008',),
    )
    assert (items['U-14'].mitigation, items['U-14'].techniques) == (
        'M1022',
        ('T1574.007',),
    )
    assert (items['U-03'].mitigation, items['U-03'].techniques) == (
        'M1036',
        ('T1110.001', 'T1110.003'),
    )


def test_derived_spans_match_the_registry_and_attack_data():
    registry = load_registry()
    attack = load_attack()
    source = ITEMS_MD.read_text()

    rendered = render_derived(registry, attack, source)

    assert rendered == source
    assert 'and 44 of those 51 carry an ATT&CK mapping.' in source


def test_each_script_item_has_one_guide_page_cited_criterion():
    source = ITEMS_MD.read_text()
    criteria = source.split('### Pass criteria\n', 1)[1].split('\n### ', 1)[0]
    rows = [line for line in criteria.splitlines() if line.startswith('- `U-')]

    assert len(rows) == 51
    assert re.findall(r'^- `(U-\d{2})`:', criteria, re.M) == [
        item.id for item in load_registry().in_group(Group.SCRIPT)
    ]
    assert all(re.search(r'PDF pp?\. \d+', row) for row in rows)


def test_script_run_ids_match_the_registry():
    source = SCRIPT.read_text()

    match = re.search(r"^ITEMS='([^']+)'", source, re.M)

    assert match is not None
    assert tuple(match[1].split()) == load_registry().run_ids()


def test_skill_digest_matches_the_script_when_the_skill_is_delivered():
    if not SKILL_MD.exists():
        pytest.skip('SKILL.md belongs to delivery unit 5')

    assert SCRIPT.exists(), 'A delivered skill must include its host script'
    registry = load_registry()
    attack = load_attack()
    skill_source = SKILL_MD.read_text()

    _, rendered = render_derived(
        registry,
        attack,
        ITEMS_MD.read_text(),
        skill_source,
        SCRIPT.read_bytes(),
    )

    assert rendered == skill_source


def test_subset_matches_the_bundle():
    bundle = os.environ.get('ATTACK_BUNDLE')
    if not bundle:
        pytest.skip('Set ATTACK_BUNDLE to the Enterprise ATT&CK v20.1 bundle')

    generated = build_attack_subset(Path(bundle))

    assert generated == json.loads(ATTACK_SUBSET.read_text())


def test_complete_run_preserves_all_verdicts():
    stdout = output()

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert run.complete
    assert len(run.items) == 64
    assert run.items[ItemId('U-01')].verdict == Verdict.PASS
    assert run.items[ItemId('U-07')].verdict == Verdict.REVIEW
    assert run.sha256 == DIGEST


def test_run_without_end_is_incomplete():
    stdout = output().rsplit('end ', 1)[0]

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert not run.complete


def test_duplicate_item_is_rejected():
    stdout = output().replace(
        'item id=U-02 verdict=pass',
        'item id=U-01 verdict=pass',
    )

    with pytest.raises(ValueError):
        parse_run(stdout, expected_sha256=DIGEST)


def test_missing_item_is_unknown_even_when_counts_agree():
    stdout = output(omit=2)

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert not run.complete
    assert run.items[ItemId('U-02')].verdict == Verdict.UNKNOWN


def test_inconsistent_summary_is_incomplete():
    stdout = output().replace('summary pass=51', 'summary pass=50')

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert not run.complete


@pytest.mark.parametrize(
    'replacement',
    [
        'protocol=2',
        'protocol=',
        'protocol=-1',
    ],
)
def test_unsupported_protocol_is_rejected(replacement):
    stdout = output().replace('protocol=1', replacement)

    with pytest.raises(ValueError):
        parse_run(stdout, expected_sha256=DIGEST)


def test_output_facts_are_percent_decoded_once():
    stdout = output().replace(
        'item id=U-01 verdict=pass',
        'item id=U-01 verdict=pass path=/a%20b%2Cc%25d%0Ae%09%1B%7F empty=-',
    )

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert run.items[ItemId('U-01')].facts == {
        'path': '/a b,c%d\ne\t\x1b\x7f',
        'empty': '',
    }


@pytest.mark.parametrize(
    'row',
    [
        'item id=U-01 verdict=pass reason=incomplete',
        'item id=U-01 verdict=pass reason=bogus',
        'item id=U-01 verdict=pass path=bad%XX',
        'item id=U-01 verdict=pass path=bad%2Fvalue',
        'item id=U-01 verdict=pass path=a path=b',
        'item id=U-01 verdict=unknown reason=not-installed',
        'item id=U-01 verdict=unknown',
        'item id=U-01 verdict=unknown reason=unsupported-os',
        'item id=U-01 verdict=na',
        'item id=U-01 verdict=review',
        'item id=U-45 verdict=pass',
    ],
)
def test_invalid_item_records_are_rejected(row):
    stdout = output().replace('item id=U-01 verdict=pass', row)

    with pytest.raises(ValueError):
        parse_run(stdout, expected_sha256=DIGEST)


@pytest.mark.parametrize(
    'row',
    [
        'item id=U-60 verdict=pass community=ok secret=marker',
        'item id=U-60 verdict=pass community=marker',
        'item id=U-60 verdict=pass community=weak',
        'item id=U-60 verdict=unknown community=ok',
        'item id=U-60 verdict=pass reason=incomplete community=unknown',
        'item id=U-60 verdict=pass',
    ],
)
def test_u60_rejects_every_fact_except_the_bounded_community_state(row):
    stdout = output().replace('item id=U-60 verdict=pass community=ok', row)

    with pytest.raises(ValueError) as raised:
        parse_run(stdout, expected_sha256=DIGEST)

    assert 'marker' not in str(raised.value)


def test_malformed_registry_row_is_rejected(tmp_path):
    source = ITEMS_MD.read_text().replace('| U-01 ', '| U-00 ', 1)
    path = tmp_path / 'items.md'
    path.write_text(source)

    with pytest.raises(ValueError):
        load_registry(path)


def test_unmapped_rows_must_have_an_explanation(tmp_path):
    source = ITEMS_MD.read_text().replace('- `U-62`:', '- `U-61`:', 1)
    path = tmp_path / 'items.md'
    path.write_text(source)

    with pytest.raises(ValueError):
        load_registry(path)


def test_generated_spans_must_exist_once():
    registry = load_registry()
    attack = load_attack()
    source = ITEMS_MD.read_text()
    marker = '<!-- BEGIN GENERATED COUNTS -->'

    with pytest.raises(ValueError):
        render_derived(registry, attack, source.replace(marker, '', 1))
    with pytest.raises(ValueError):
        render_derived(registry, attack, source + source)


def test_one_item_can_have_multiple_mitigation_rows(tmp_path):
    source = ITEMS_MD.read_text()
    first = next(line for line in source.splitlines() if line.startswith('| U-18 '))
    item_cell = first.split('|')[1]
    second = f'|{item_cell}| M1027 | T1003.008 | Credential Access |'
    path = tmp_path / 'items.md'
    path.write_text(source.replace(first, f'{first}\n{second}', 1))

    registry = load_registry(path)
    item = next(item for item in registry.items if item.id == 'U-18')

    assert [(mapping.mitigation, mapping.techniques) for mapping in item.mappings] == [
        ('M1026', ('T1003.008',)),
        ('M1027', ('T1003.008',)),
    ]


def test_duplicate_mitigation_row_is_rejected(tmp_path):
    source = ITEMS_MD.read_text()
    row = next(line for line in source.splitlines() if line.startswith('| U-18 '))
    path = tmp_path / 'items.md'
    path.write_text(source.replace(row, f'{row}\n{row}', 1))

    with pytest.raises(ValueError):
        load_registry(path)


def test_run_parser_requires_a_pinned_digest():
    assert signature(parse_run).parameters['expected_sha256'].default is Parameter.empty


def test_a_script_digest_mismatch_makes_the_whole_run_unknown():
    stdout = output().rsplit('end ', 1)[0]

    run = parse_run(stdout, expected_sha256='b' * 64)

    assert not run.complete
    assert {item.verdict for item in run.items.values()} == {Verdict.UNKNOWN}
    assert {item.facts['reason'] for item in run.items.values()} == {'script-mismatch'}


def test_a_truncated_run_does_not_leave_pass_verdicts():
    stdout = output().rsplit('end ', 1)[0]

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert {item.verdict for item in run.items.values()} == {Verdict.UNKNOWN}


def test_the_renderer_repairs_names_without_changing_criteria():
    registry = load_registry()
    attack = load_attack()
    source = ITEMS_MD.read_text()
    damaged = source.replace('Privileged Account Management', 'stale name')

    rendered = render_derived(registry, attack, damaged)

    assert rendered == source
    assert (
        rendered.split('### Pass criteria', 1)[1].split('## By tactic', 1)[0]
        == source.split('### Pass criteria', 1)[1].split('## By tactic', 1)[0]
    )


def test_a_list_preserves_encoded_commas_inside_entries():
    stdout = output().replace(
        'item id=U-07 verdict=review',
        'item id=U-07 verdict=review names=alice%2Cbob%252Cjunior%2525 more=2',
    )

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert run.complete
    assert run.items[ItemId('U-07')].facts == {
        'names': ('alice', 'bob,junior%'),
        'more': '2',
    }


def test_an_unavailable_digest_makes_the_whole_run_unknown():
    stdout = output().replace(f'sha256={DIGEST}', 'sha256=unknown')

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert not run.complete
    assert {item.verdict for item in run.items.values()} == {Verdict.UNKNOWN}


@pytest.mark.parametrize(
    'tail',
    [
        ' more=-1',
        ' more=abc',
        ' note=bogus',
        ' path=',
        ' names=' + '%2C'.join(str(n) for n in range(21)),
    ],
)
def test_malformed_facts_are_rejected(tail):
    stdout = output().replace(
        'item id=U-01 verdict=pass', 'item id=U-01 verdict=pass' + tail
    )

    with pytest.raises(ValueError):
        parse_run(stdout, expected_sha256=DIGEST)


def test_a_known_violation_stays_failed_when_collection_is_incomplete():
    stdout = (
        output()
        .replace(
            'item id=U-01 verdict=pass',
            'item id=U-01 verdict=fail reason=incomplete',
        )
        .replace('summary pass=51 fail=0', 'summary pass=50 fail=1')
    )

    run = parse_run(stdout, expected_sha256=DIGEST)

    assert run.complete
    assert run.items[ItemId('U-01')].verdict == Verdict.FAIL
    assert run.items[ItemId('U-01')].facts == {'reason': 'incomplete'}


@pytest.mark.parametrize(
    'fact',
    [
        'path=secret-marker%XX',
        'secret-marker',
        'secret-marker=value',
        'verdict=secret-marker',
    ],
)
def test_malformed_output_errors_do_not_expose_host_data(fact):
    stdout = output().replace(
        'item id=U-01 verdict=pass',
        'item id=U-01 verdict=pass ' + fact,
    )

    with pytest.raises(ValueError) as raised:
        parse_run(stdout, expected_sha256=DIGEST)

    assert 'secret-marker' not in str(raised.value)
    assert raised.value.__cause__ is None


def test_an_unknown_record_does_not_expose_host_data():
    stdout = output() + 'secret-marker\n'

    with pytest.raises(ValueError) as raised:
        parse_run(stdout, expected_sha256=DIGEST)

    assert 'secret-marker' not in str(raised.value)
