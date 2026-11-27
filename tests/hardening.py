"""Validate the hardening registry and parse its script protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Literal, NewType, cast
from urllib.parse import unquote_to_bytes

ROOT = Path(__file__).resolve().parents[1]
ITEMS_MD = ROOT / 'plugins/alpacon/skills/hardening-check/references/items.md'
SKILL_MD = ITEMS_MD.parent.parent / 'SKILL.md'
SCRIPT = ITEMS_MD.parent.parent / 'scripts/hardening-check.sh'
ATTACK_SUBSET = ROOT / 'tests/data/attack-enterprise-20.1.json'
ATTACK_SOURCE = 'https://raw.githubusercontent.com/mitre-attack/attack-stix-data/refs/tags/v20.1/enterprise-attack/enterprise-attack.json'

ItemId = NewType('ItemId', str)
_ITEM_ID = re.compile(r'U-(?:0[1-9]|[1-5][0-9]|6[0-7])')
_EXTERNAL_ID = re.compile(r'[MT]\d{4}(?:\.\d{3})?')


class Group(StrEnum):
    SCRIPT = 'script'
    PERSON = 'person'
    POINTER = 'pointer'


class Verdict(StrEnum):
    PASS = 'pass'
    FAIL = 'fail'
    NA = 'na'
    UNKNOWN = 'unknown'
    REVIEW = 'review'


ALLOWED: Mapping[Group, frozenset[Verdict]] = MappingProxyType(
    {
        Group.SCRIPT: frozenset(
            {Verdict.PASS, Verdict.FAIL, Verdict.NA, Verdict.UNKNOWN}
        ),
        Group.PERSON: frozenset({Verdict.REVIEW, Verdict.UNKNOWN}),
        Group.POINTER: frozenset(),
    }
)

PERSON_KEYS: Mapping[ItemId, frozenset[str]] = MappingProxyType(
    {
        ItemId('U-07'): frozenset({'login_accounts', 'names', 'more'}),
        ItemId('U-08'): frozenset({'admin_accounts', 'names', 'more'}),
        ItemId('U-09'): frozenset({'orphan_groups', 'names', 'more'}),
        ItemId('U-11'): frozenset({'login_shell_accounts', 'names', 'more'}),
        ItemId('U-23'): frozenset({'privileged_files', 'paths', 'more'}),
        ItemId('U-25'): frozenset({'world_writable', 'paths', 'more'}),
        ItemId('U-26'): frozenset({'non_device_files', 'paths', 'more'}),
        ItemId('U-28'): frozenset({'firewall', 'tcp_wrappers', 'listeners'}),
        ItemId('U-33'): frozenset({'hidden_paths', 'paths', 'more'}),
        ItemId('U-39'): frozenset({'nfs_installed', 'nfs_active'}),
        ItemId('U-56'): frozenset({'ftp_access_control', 'rules'}),
        ItemId('U-58'): frozenset({'snmp_installed', 'snmp_active'}),
        ItemId('U-66'): frozenset({'logging', 'destinations', 'remote'}),
    }
)


@dataclass(frozen=True)
class AttackMapping:
    mitigation: str
    techniques: tuple[str, ...]


@dataclass(frozen=True)
class Item:
    id: ItemId
    title: str
    group: Group
    mappings: tuple[AttackMapping, ...]

    @property
    def mitigation(self) -> str | None:
        return self.mappings[0].mitigation if self.mappings else None

    @property
    def techniques(self) -> tuple[str, ...]:
        return self.mappings[0].techniques if self.mappings else ()


@dataclass(frozen=True)
class Registry:
    edition: str
    attack_release: str
    items: tuple[Item, ...]

    def in_group(self, group: Group) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.group is group)

    def run_ids(self) -> tuple[ItemId, ...]:
        return tuple(item.id for item in self.items if item.group is not Group.POINTER)


@dataclass(frozen=True)
class Technique:
    id: str
    cell: str
    tactics: tuple[str, ...]
    linux: bool


@dataclass(frozen=True)
class Attack:
    release: str
    bundle_sha256: str
    mitigations: Mapping[str, str]
    mitigates: frozenset[tuple[str, str]]
    techniques: Mapping[str, Technique]
    tactic_order: tuple[str, ...]


@dataclass(frozen=True)
class ItemResult:
    id: ItemId
    verdict: Verdict
    facts: Mapping[str, str | tuple[str, ...]]


@dataclass(frozen=True)
class Run:
    family: Literal['debian', 'rhel', 'unknown']
    os: str
    sha256: str
    items: Mapping[ItemId, ItemResult]
    complete: bool


def _ids(cell: str, prefix: str) -> tuple[str, ...]:
    return tuple(
        match for match in _EXTERNAL_ID.findall(cell) if match.startswith(prefix)
    )


def load_registry(path: Path = ITEMS_MD) -> Registry:
    text = path.read_text()
    edition_match = re.search(r'^Edition: (\S+)$', text, re.MULTILINE)
    release_match = re.search(r'^ATT&CK release: (\S+)$', text, re.MULTILINE)
    if not edition_match or not release_match:
        raise ValueError('registry metadata is missing')

    exception_section = re.search(
        r'^### Without an ATT&CK mapping\n(?P<body>.*?)(?=\n### |\n## )',
        text,
        re.MULTILINE | re.DOTALL,
    )
    if exception_section is None:
        raise ValueError('registry mapping exceptions are missing')
    exception_rows = re.findall(
        r'^- `(?P<id>U-\d{2})`: (?P<reason>\S.*)$',
        exception_section.group('body'),
        re.MULTILINE,
    )
    exception_ids = tuple(ItemId(item_id) for item_id, _ in exception_rows)
    if (
        not exception_rows
        or len(exception_ids) != len(set(exception_ids))
        or any(not _ITEM_ID.fullmatch(item_id) for item_id in exception_ids)
    ):
        raise ValueError('registry mapping exceptions are malformed')

    items: dict[ItemId, Item] = {}
    unmapped_rows: set[ItemId] = set()
    for line in text.splitlines():
        if not line.startswith('| U-'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) != 4:
            raise ValueError(f'malformed script row: {line}')
        item_match = re.fullmatch(r'(U-\d{2}) (.+)', cells[0])
        if not item_match or not _ITEM_ID.fullmatch(item_match.group(1)):
            raise ValueError(f'malformed item cell: {cells[0]}')
        item_id = ItemId(item_match.group(1))
        mitigations = _ids(cells[1], 'M')
        techniques = _ids(cells[2], 'T')
        unmapped = cells[1:] == ['—', '—', '—']
        if unmapped:
            unmapped_rows.add(item_id)
        if not unmapped and (len(mitigations) != 1 or not techniques):
            raise ValueError(
                f'script row requires one mitigation and techniques: {item_id}'
            )
        mapping = () if unmapped else (AttackMapping(mitigations[0], techniques),)
        existing = items.get(item_id)
        if existing is not None:
            if (
                unmapped
                or not existing.mappings
                or existing.title != item_match.group(2)
                or any(
                    previous.mitigation == mitigations[0]
                    for previous in existing.mappings
                )
            ):
                raise ValueError(f'invalid repeated item row: {item_id}')
            items[item_id] = replace(existing, mappings=existing.mappings + mapping)
        else:
            items[item_id] = Item(item_id, item_match.group(2), Group.SCRIPT, mapping)

    if unmapped_rows != set(exception_ids):
        raise ValueError('unmapped table rows and mapping exceptions differ')

    bullet = re.compile(
        r'^- `(?P<id>U-\d{2}) (?P<title>[^`]+)` \[(?P<tag>person|pointer:[^\]]+)\]: ',
        re.MULTILINE,
    )
    for match in bullet.finditer(text):
        raw_id = match.group('id')
        if not _ITEM_ID.fullmatch(raw_id):
            raise ValueError(f'malformed item id: {raw_id}')
        item_id = ItemId(raw_id)
        if item_id in items:
            raise ValueError(f'duplicate item: {item_id}')
        tag = match.group('tag')
        group = Group.PERSON if tag == 'person' else Group.POINTER
        items[item_id] = Item(item_id, match.group('title'), group, ())

    ordered = tuple(
        items[item_id] for item_id in sorted(items, key=lambda value: int(value[2:]))
    )
    expected_ids = tuple(f'U-{number:02}' for number in range(1, 68))
    if tuple(str(item.id) for item in ordered) != expected_ids:
        raise ValueError('registry must contain U-01 through U-67 exactly once')
    counts = Counter(item.group for item in ordered)
    if counts != {Group.SCRIPT: 51, Group.PERSON: 13, Group.POINTER: 3}:
        raise ValueError(
            'registry group counts must be 51 script, 13 person, and 3 pointer'
        )
    return Registry(edition_match.group(1), release_match.group(1), ordered)


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f'{context} must be an object')
    return cast(dict[str, object], value)


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{context} must be a string')
    return value


def _strings(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(entry, str) for entry in value
    ):
        raise ValueError(f'{context} must be a string list')
    return tuple(cast(list[str], value))


def load_attack(path: Path = ATTACK_SUBSET) -> Attack:
    raw = _object(json.loads(path.read_text()), 'ATT&CK subset')
    collection = _object(raw.get('collection'), 'collection')
    bundle = _object(raw.get('bundle'), 'bundle')
    mitigations_raw = _object(raw.get('mitigations'), 'mitigations')
    techniques_raw = _object(raw.get('techniques'), 'techniques')
    relationships_raw = raw.get('relationships')
    if not isinstance(relationships_raw, list):
        raise ValueError('relationships must be a list')
    mitigations = {
        key: _string(value, f'mitigation {key}')
        for key, value in mitigations_raw.items()
    }
    techniques: dict[str, Technique] = {}
    for technique_id, value in techniques_raw.items():
        record = _object(value, f'technique {technique_id}')
        techniques[technique_id] = Technique(
            technique_id,
            _string(record.get('cell'), f'technique {technique_id} cell'),
            _strings(record.get('tactics'), f'technique {technique_id} tactics'),
            record.get('linux') is True,
        )
    pairs: set[tuple[str, str]] = set()
    for value in relationships_raw:
        record = _object(value, 'relationship')
        pair = (
            _string(record.get('mitigation'), 'relationship mitigation'),
            _string(record.get('technique'), 'relationship technique'),
        )
        pairs.add(pair)
    return Attack(
        _string(collection.get('version'), 'collection version'),
        _string(bundle.get('sha256'), 'bundle sha256'),
        MappingProxyType(mitigations),
        frozenset(pairs),
        MappingProxyType(techniques),
        _strings(raw.get('tactic_order'), 'tactic order'),
    )


def _external_id(record: Mapping[str, object]) -> str | None:
    references = record.get('external_references', [])
    if not isinstance(references, list):
        return None
    for value in references:
        reference = _object(value, 'external reference')
        external_id = reference.get('external_id')
        if isinstance(external_id, str) and _EXTERNAL_ID.fullmatch(external_id):
            return external_id
    return None


def _active(record: Mapping[str, object]) -> bool:
    return (
        record.get('revoked') is not True
        and record.get('x_mitre_deprecated') is not True
    )


def build_attack_subset(bundle: Path) -> dict[str, object]:
    bundle_bytes = bundle.read_bytes()
    raw = _object(json.loads(bundle_bytes), 'ATT&CK bundle')
    values = raw.get('objects')
    if not isinstance(values, list):
        raise ValueError('ATT&CK objects must be a list')
    objects = [_object(value, 'ATT&CK object') for value in values]
    by_stix = {
        _string(record.get('id'), 'STIX id'): record
        for record in objects
        if isinstance(record.get('id'), str)
    }

    collection = next(
        record
        for record in objects
        if record.get('type') == 'x-mitre-collection'
        and record.get('name') == 'Enterprise ATT&CK'
    )
    matrix = next(
        record
        for record in objects
        if record.get('type') == 'x-mitre-matrix'
        and record.get('name') == 'Enterprise ATT&CK'
    )
    tactic_refs = _strings(matrix.get('tactic_refs'), 'matrix tactic refs')
    tactic_records = [by_stix[ref] for ref in tactic_refs]
    tactic_order = tuple(
        _string(record.get('name'), 'tactic name') for record in tactic_records
    )
    tactic_names = {
        _string(record.get('x_mitre_shortname'), 'tactic shortname'): _string(
            record.get('name'), 'tactic name'
        )
        for record in tactic_records
    }

    mitigation_by_stix: dict[str, str] = {}
    mitigations: dict[str, str] = {}
    technique_by_stix: dict[str, str] = {}
    technique_records: dict[str, Mapping[str, object]] = {}
    for record in objects:
        if not _active(record):
            continue
        external_id = _external_id(record)
        stix_id = _string(record.get('id'), 'STIX id')
        if (
            record.get('type') == 'course-of-action'
            and external_id
            and external_id.startswith('M')
        ):
            mitigation_by_stix[stix_id] = external_id
            mitigations[external_id] = _string(
                record.get('name'), f'mitigation {external_id} name'
            )
        elif (
            record.get('type') == 'attack-pattern'
            and external_id
            and external_id.startswith('T')
        ):
            technique_by_stix[stix_id] = external_id
            technique_records[external_id] = record

    parents: dict[str, str] = {}
    relationships: list[dict[str, str]] = []
    for relationship_record in objects:
        if relationship_record.get('type') != 'relationship' or not _active(
            relationship_record
        ):
            continue
        source_ref = relationship_record.get('source_ref')
        target_ref = relationship_record.get('target_ref')
        if not isinstance(source_ref, str) or not isinstance(target_ref, str):
            continue
        if (
            relationship_record.get('relationship_type') == 'subtechnique-of'
            and source_ref in technique_by_stix
            and target_ref in technique_by_stix
        ):
            parents[technique_by_stix[source_ref]] = technique_by_stix[target_ref]
        if (
            relationship_record.get('relationship_type') == 'mitigates'
            and source_ref in mitigation_by_stix
            and target_ref in technique_by_stix
        ):
            relationships.append(
                {
                    'id': _string(relationship_record.get('id'), 'relationship id'),
                    'mitigation': mitigation_by_stix[source_ref],
                    'technique': technique_by_stix[target_ref],
                }
            )

    order = {name: index for index, name in enumerate(tactic_order)}
    techniques: dict[str, dict[str, object]] = {}
    for technique_id, technique_record in technique_records.items():
        phases = technique_record.get('kill_chain_phases', [])
        if not isinstance(phases, list):
            raise ValueError(f'technique {technique_id} phases must be a list')
        tactics = {
            tactic_names[phase_name]
            for value in phases
            if (phase_name := _object(value, 'kill chain phase').get('phase_name'))
            in tactic_names
        }
        name = _string(technique_record.get('name'), f'technique {technique_id} name')
        parent_id = parents.get(technique_id)
        parent_name = (
            _string(
                technique_records[parent_id].get('name'), f'parent {parent_id} name'
            )
            if parent_id
            else None
        )
        cell_name = f'{parent_name}: {name}' if parent_name else name
        platforms = _strings(
            technique_record.get('x_mitre_platforms', []),
            f'technique {technique_id} platforms',
        )
        techniques[technique_id] = {
            'name': name,
            'parent': parent_id,
            'cell': f'{technique_id} {cell_name}',
            'tactics': sorted(tactics, key=order.__getitem__),
            'linux': 'Linux' in platforms,
        }

    relationships.sort(
        key=lambda record: (record['mitigation'], record['technique'], record['id'])
    )
    return {
        'collection': {
            'name': _string(collection.get('name'), 'collection name'),
            'version': _string(collection.get('x_mitre_version'), 'collection version'),
            'modified': _string(collection.get('modified'), 'collection modified'),
        },
        'bundle': {
            'sha256': hashlib.sha256(bundle_bytes).hexdigest(),
            'source': ATTACK_SOURCE,
        },
        'tactic_order': list(tactic_order),
        'mitigations': dict(sorted(mitigations.items())),
        'techniques': dict(sorted(techniques.items())),
        'relationships': relationships,
    }


def _replace_span(text: str, name: str, body: str) -> str:
    start = f'<!-- BEGIN GENERATED {name} -->'
    end = f'<!-- END GENERATED {name} -->'
    pattern = re.compile(rf'{re.escape(start)}.*?{re.escape(end)}', re.DOTALL)
    matches = pattern.findall(text)
    if not matches:
        raise ValueError(f'missing generated span: {name}')
    if len(matches) != 1:
        raise ValueError(
            f'expected one generated span for {name}, found {len(matches)}'
        )
    return pattern.sub(f'{start}\n{body.rstrip()}\n{end}', text)


def render_derived(reg: Registry, attack: Attack, items_md: str) -> str:
    """Rewrite the registry indexes in the items reference."""
    counts = Counter(item.group for item in reg.items)
    count_line = (
        f'The script judges {counts[Group.SCRIPT]} of the {len(reg.items)} items. '
        f'{counts[Group.PERSON]} need a person, {counts[Group.POINTER]} belong to another skill, none lies wholly outside the host, '
        f'and {sum(bool(item.mappings) for item in reg.in_group(Group.SCRIPT))} of those {counts[Group.SCRIPT]} carry an ATT&CK mapping.'
    )
    rendered = _replace_span(items_md, 'COUNTS', count_line)
    for item in reg.in_group(Group.SCRIPT):
        replacements_rows: list[str] = []
        mappings = item.mappings or (None,)
        for mapping in mappings:
            if mapping is None:
                replacements_rows.append(f'| {item.id} {item.title} | — | — | — |')
                continue
            mitigation = (
                f'{mapping.mitigation} {attack.mitigations[mapping.mitigation]}'
            )
            technique_cells = [
                attack.techniques[technique_id].cell
                for technique_id in mapping.techniques
            ]
            tactics = [
                tactic
                for tactic in attack.tactic_order
                if any(
                    tactic in attack.techniques[technique_id].tactics
                    for technique_id in mapping.techniques
                )
            ]
            replacements_rows.append(
                f'| {item.id} {item.title} | {mitigation} | {"<br>".join(technique_cells)} | {"<br>".join(tactics)} |'
            )
        row = re.compile(
            rf'^(?:\| {re.escape(str(item.id))} {re.escape(item.title)} \|.*\n?)+',
            re.MULTILINE,
        )
        rendered, replacements = row.subn('\n'.join(replacements_rows) + '\n', rendered)
        if replacements != 1:
            raise ValueError(
                f'expected one table row for {item.id}, found {replacements}'
            )

    by_tactic: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in reg.in_group(Group.SCRIPT):
        for mapping in item.mappings:
            for technique_id in mapping.techniques:
                technique = attack.techniques[technique_id]
                for tactic in technique.tactics:
                    by_tactic[tactic][technique.cell].append(
                        f'{item.id} {mapping.mitigation}'
                    )
    index: list[str] = []
    for tactic in attack.tactic_order:
        if tactic not in by_tactic:
            continue
        index.extend((f'### {tactic}', '', '| Technique | Items |', '| --- | --- |'))
        for technique_cell, item_cells in sorted(by_tactic[tactic].items()):
            index.append(f'| {technique_cell} | {", ".join(item_cells)} |')
        index.append('')
    return _replace_span(rendered, 'BY TACTIC', '\n'.join(index))


def render_skill_digest(skill_md: str, script: bytes) -> str:
    return _replace_span(skill_md, 'SCRIPT SHA256', hashlib.sha256(script).hexdigest())


def _decode(value: str) -> str:
    if re.search(
        r'[\x00-\x1f\x7f]|%(?![01][0-9a-f]|20|25|2C|2D|7F)', value, re.IGNORECASE
    ):
        raise ValueError('invalid encoded value')
    if value == '-':
        return ''
    try:
        return unquote_to_bytes(value).decode()
    except UnicodeDecodeError:
        raise ValueError('invalid encoded value') from None


def _tokens(line: str) -> tuple[str, dict[str, str]]:
    parts = line.split(' ')
    values: dict[str, str] = {}
    for token in parts[1:]:
        if '=' not in token:
            raise ValueError('invalid protocol token')
        key, value = token.split('=', 1)
        if not re.fullmatch(r'[a-z][a-z0-9_]*', key) or key in values:
            raise ValueError('invalid or duplicate protocol key')
        if not value:
            raise ValueError('empty value must use -')
        values[key] = _decode(value)
    return parts[0], values


def _unknown(item_id: ItemId, reason: str) -> ItemResult:
    return ItemResult(item_id, Verdict.UNKNOWN, MappingProxyType({'reason': reason}))


def parse_run(
    stdout: str, registry: Registry | None = None, *, expected_sha256: str
) -> Run:
    """Parse one protocol run and fail closed when its completion proof is absent."""
    reg = registry or load_registry()
    expected_ids = reg.run_ids()
    lines = stdout.removesuffix('\n').split('\n')
    kind, header = _tokens(lines[0])
    required_header = {'protocol', 'edition', 'family', 'os', 'uid', 'sha256'}
    if (
        kind != 'hardening'
        or set(header) != required_header
        or header['protocol'] != '1'
        or header['edition'] != reg.edition
    ):
        raise ValueError('invalid header')
    family = header['family']
    if family not in {'debian', 'rhel', 'unknown'}:
        raise ValueError('invalid family')
    if not header['uid'].isdigit() or not (
        header['sha256'] == 'unknown' or re.fullmatch(r'[0-9a-f]{64}', header['sha256'])
    ):
        raise ValueError('invalid uid or sha256')

    if header['sha256'] == 'unknown' or header['sha256'] != expected_sha256:
        return Run(
            cast(Literal['debian', 'rhel', 'unknown'], family),
            header['os'],
            header['sha256'],
            MappingProxyType({i: _unknown(i, 'script-mismatch') for i in expected_ids}),
            False,
        )

    parsed: dict[ItemId, ItemResult] = {}
    summary: dict[str, str] | None = None
    end: dict[str, str] | None = None
    state = 'items'
    allowed_reasons = {
        'not-installed',
        'needs-approval',
        'access-denied',
        'tool-missing',
        'unsupported-os',
        'check-error',
        'incomplete',
        'timeout',
    }
    allowed_notes = {'distro-default', 'yescrypt'}
    for line in lines[1:]:
        kind, values = _tokens(line)
        if kind == 'item' and state == 'items':
            if (
                'id' not in values
                or 'verdict' not in values
                or not _ITEM_ID.fullmatch(values['id'])
            ):
                raise ValueError('invalid item record')
            item_id = ItemId(values.pop('id'))
            if item_id in parsed:
                raise ValueError(f'duplicate item: {item_id}')
            try:
                verdict = Verdict(values.pop('verdict'))
            except ValueError:
                raise ValueError(f'invalid verdict for {item_id}') from None
            group = next((item.group for item in reg.items if item.id == item_id), None)
            if group is None or verdict not in ALLOWED[group]:
                raise ValueError(f'verdict {verdict} is invalid for {item_id}')
            reason = values.get('reason')
            u60 = item_id == ItemId('U-60')
            if u60 and (
                set(values) != {'community'}
                or values['community']
                not in {'ok', 'weak', 'default', 'none', 'unknown'}
            ):
                raise ValueError('U-60 must report only the community state')
            if (
                u60
                and values['community']
                not in {
                    Verdict.PASS: {'ok'},
                    Verdict.FAIL: {'weak', 'default'},
                    Verdict.NA: {'none'},
                    Verdict.UNKNOWN: {'unknown'},
                }[verdict]
            ):
                raise ValueError('U-60 community state does not match its verdict')
            if reason is not None and reason not in allowed_reasons:
                raise ValueError(f'invalid reason for {item_id}')
            if (
                reason is not None
                and verdict not in {Verdict.NA, Verdict.UNKNOWN}
                and not (verdict is Verdict.FAIL and reason == 'incomplete')
            ):
                raise ValueError(f'reason is invalid for {verdict} on {item_id}')
            if verdict is Verdict.NA and reason != 'not-installed' and not u60:
                raise ValueError(f'na requires reason=not-installed for {item_id}')
            if reason == 'not-installed' and verdict is not Verdict.NA:
                raise ValueError(f'reason=not-installed requires na for {item_id}')
            if verdict is Verdict.UNKNOWN and reason is None and not u60:
                raise ValueError(f'unknown requires a reason for {item_id}')
            if 'note' in values and values['note'] not in allowed_notes:
                raise ValueError(f'invalid note for {item_id}')
            if 'more' in values and (
                not values['more'].isdigit() or int(values['more']) < 0
            ):
                raise ValueError(f'invalid more count for {item_id}')
            if family == 'unknown' and (
                verdict is not Verdict.UNKNOWN
                or (
                    reason
                    not in {
                        'unsupported-os',
                        'incomplete',
                        'access-denied',
                        'needs-approval',
                        'tool-missing',
                        'check-error',
                    }
                    and not u60
                )
            ):
                raise ValueError(
                    f'unsupported family returned invalid state for {item_id}'
                )
            if family != 'unknown' and reason == 'unsupported-os':
                raise ValueError(
                    f'supported family returned unsupported-os for {item_id}'
                )
            facts: dict[str, str | tuple[str, ...]] = dict(values)
            for key in values.keys() & {'names', 'paths', 'positions'}:
                entries = (
                    tuple(_decode(entry) for entry in values[key].split(','))
                    if values[key]
                    else ()
                )
                if len(entries) > 20 or any(not entry for entry in entries):
                    raise ValueError('invalid list evidence')
                facts[key] = entries
            parsed[item_id] = ItemResult(item_id, verdict, MappingProxyType(facts))
        elif kind == 'summary' and state == 'items':
            summary = values
            state = 'summary'
        elif kind == 'end' and state == 'summary':
            end = values
            state = 'end'
        else:
            raise ValueError('unexpected or duplicate record')

    seen_order = tuple(item_id for item_id in expected_ids if item_id in parsed)
    if tuple(parsed) != seen_order:
        raise ValueError('items are not in registry order')
    missing = tuple(item_id for item_id in expected_ids if item_id not in parsed)
    for item_id in missing:
        parsed[item_id] = _unknown(item_id, 'missing')
    parsed = {item_id: parsed[item_id] for item_id in expected_ids}

    counts = Counter(
        result.verdict.value
        for result in parsed.values()
        if result.facts.get('reason') != 'missing'
    )
    expected_summary = {
        verdict.value: str(counts[verdict.value]) for verdict in Verdict
    }
    summary_valid = summary == expected_summary
    end_valid = end == {'items': str(len(expected_ids)), 'complete': 'yes'}
    complete = not missing and summary_valid and end_valid
    if not end_valid or not summary_valid:
        parsed = {item_id: _unknown(item_id, 'incomplete') for item_id in expected_ids}
    return Run(
        cast(Literal['debian', 'rhel', 'unknown'], family),
        header['os'],
        header['sha256'],
        MappingProxyType(parsed),
        complete,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix', action='store_true')
    subparsers = parser.add_subparsers(dest='command')
    subset = subparsers.add_parser('attack-subset')
    subset.add_argument('bundle', type=Path)
    args = parser.parse_args()
    if args.fix and args.command:
        parser.error('--fix and attack-subset are mutually exclusive')
    if args.command == 'attack-subset':
        _write_json(ATTACK_SUBSET, build_attack_subset(args.bundle))
        return
    if args.fix:
        registry = load_registry()
        attack = load_attack()
        ITEMS_MD.write_text(render_derived(registry, attack, ITEMS_MD.read_text()))
        SKILL_MD.write_text(
            render_skill_digest(SKILL_MD.read_text(), SCRIPT.read_bytes())
        )
        return
    parser.error('choose --fix or attack-subset')


if __name__ == '__main__':
    main()
