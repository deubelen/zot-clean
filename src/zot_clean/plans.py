"""Write plans (D34, D46).

A cleanup step never touches Zotero, it produces a plan. A plan is a list of
groups, and each group a sequence of operations on elements (key, before and
after values of the touched fields, rank in the group). Attaching to an item,
moving to the trash or restoring from it are field changes like any other
(`parentItem`, `deleted`). `zc apply` runs the plan as it is, and its
fingerprint links the plan to its journals.

An operation targets an item (`kind = "items"`, stored as `genre`) or a
collection (`kind = "collections"`, D114), whose name, parent and trash state
change the same way (`name`, `parentCollection`, `deleted`). A creation
operation (`create`, stored as `creation`) brings a collection into being
under the key drawn by the plan, so that items of the same plan can already
refer to it.

The fingerprint covers everything that acts at execution or in the journal
registry, namely the groups and, for an undo plan, the journals it undoes
(format 2, D180). The description and the creation date are left out, so that
a plan recomputed identically keeps its fingerprint (D47). A format 1 plan
keeps the fingerprint computed without the journals.

The keys of the file form a frozen protocol, independent of the Python names
(D209). The `*_FIELDS` tables give, for each written key, the attribute that
carries it. The file and the fingerprint are computed on this stored
representation, so renaming an attribute changes neither.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from zot_clean.lang import L

FORMAT = 2
FORMATS = (1, 2)  # formats still read

# Value of a field missing from the data returned by the API.
DEFAULTS = {'deleted': False, 'parentItem': False, 'parentCollection': False, 'collections': [], 'tags': [], 'relations': {}, 'creators': []}


def normalize(field_name: str, v):
    """Comparable form of a value, independent of the order the API returns."""
    if field_name == 'deleted':
        return bool(v)
    if field_name in ('parentItem', 'parentCollection'):
        return v or False
    if field_name == 'collections':
        return sorted(v or [])
    if field_name == 'tags':
        return sorted([t['tag'], int(t.get('type', 0))] for t in v or [])
    if field_name == 'relations':
        return {k: sorted([x] if isinstance(x, str) else x) for k, x in (v or {}).items() if x}
    return v


def value(data: dict, field_name: str):
    return normalize(field_name, data.get(field_name, DEFAULTS.get(field_name, '')))


def raw_value(data: dict, field_name: str):
    """Value as the API expects it when writing, default included."""
    return data.get(field_name, DEFAULTS.get(field_name, ''))


@dataclass
class Operation:
    key: str
    before: dict
    after: dict
    rank: int = 0  # the ranks of a group run in order, a failed rank stops the group
    nature: str = ''
    kind: str = 'items'  # or 'collections', or 'settings' (synced setting, `value`, D175)
    create: bool = False  # collection to create under the key `key`, with the fields of `after`
    # Moving to the trash: children (attachments, notes, annotations) of an item, or items and subcollections
    # of a collection, known to the plan. Another one found at write time stops the group (D182, D183).
    children: list[str] | None = None
    requires: dict | None = None  # fields that must still have these values, even in a partial plan (D183)


@dataclass
class Group:
    id: str
    title: str
    operations: list[Operation]


@dataclass
class Plan:
    step: str
    library: int
    groups: list[Group]
    description: str = ''
    # Undo (D39): a conflicting field is left as it is, the others are written.
    partial: bool = False
    undoes: list[str] = field(default_factory=list)
    created: str = ''
    format: int = FORMAT

    @property
    def fingerprint(self) -> str:
        content = {'etape': self.step, 'bibliotheque': self.library, 'partiel': self.partial,
                   'groupes': [_without_defaults(_stored_group(g)) for g in self.groups]}
        if self.undoes and self.format >= 2:  # absent otherwise, so that the fingerprint of other plans does not change
            content['annule'] = self.undoes
        return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]

    @property
    def n_operations(self) -> int:
        return sum(len(g.operations) for g in self.groups)


# File key -> attribute, in writing order (D209). Groups and operations are written in their place.
PLAN_FIELDS = {'etape': 'step', 'bibliotheque': 'library', 'groupes': 'groups', 'description': 'description',
               'partiel': 'partial', 'annule': 'undoes', 'cree': 'created'}
GROUP_FIELDS = {'id': 'id', 'titre': 'title', 'operations': 'operations'}
OPERATION_FIELDS = {'cle': 'key', 'avant': 'before', 'apres': 'after', 'rang': 'rank', 'nature': 'nature',
                    'genre': 'kind', 'creation': 'create', 'enfants': 'children', 'exige': 'requires'}


def _stored_operation(op: Operation) -> dict:
    return {key: getattr(op, attribute) for key, attribute in OPERATION_FIELDS.items()}


def _stored_group(g: Group) -> dict:
    return {key: [_stored_operation(o) for o in g.operations] if key == 'operations' else getattr(g, attribute)
            for key, attribute in GROUP_FIELDS.items()}


def to_stored(plan: Plan) -> dict:
    """The plan as it is written in its file."""
    d = {key: [_stored_group(g) for g in plan.groups] if key == 'groupes' else getattr(plan, attribute)
         for key, attribute in PLAN_FIELDS.items()}
    return {'format': plan.format, 'empreinte': plan.fingerprint, **d}


def _without_defaults(group: dict) -> dict:
    """Group without the operation fields added for collections when they have their default value,
    so that the fingerprint of plans written before them does not change."""
    ops = [{k: v for k, v in o.items() if not (k == 'genre' and v == 'items' or k == 'creation' and not v
                                                or k in ('enfants', 'exige') and v is None)}
           for o in group['operations']]
    return dict(group, operations=ops)


def write(plan: Plan, folder: Path, report: str) -> Path:
    """Write the plan and its readable report in `folder` (plans/ of the working folder)."""
    folder.mkdir(parents=True, exist_ok=True)
    plan.created = plan.created or datetime.now().astimezone().isoformat(timespec='seconds')
    path = folder / f'{datetime.now():%Y-%m-%d_%H%M%S}_{plan.step}_{plan.fingerprint}.json'
    path.write_text(json.dumps(to_stored(plan), ensure_ascii=False, indent=1), encoding='utf-8')
    path.with_suffix('.md').write_text(report, encoding='utf-8')
    return path


def load(path: Path) -> Plan:
    d = json.loads(path.read_text(encoding='utf-8'))
    if d.get('format') not in FORMATS:
        raise SystemExit(L(en=f'{path}: unknown plan format ({d.get("format")}). Update zot-clean.',
                           fr=f'{path} : format de plan inconnu ({d.get("format")}). Mettre zot-clean à jour.'))
    groups = [Group(**{GROUP_FIELDS[k]: [_operation(o) for o in v] if k == 'operations' else v
                         for k, v in g.items()}) for g in d['groupes']]
    plan = Plan(**{PLAN_FIELDS[k]: groups if k == 'groupes' else v for k, v in d.items() if k in PLAN_FIELDS},
                format=d['format'])
    if plan.fingerprint != d.get('empreinte'):
        raise SystemExit(L(en=f'{path}: the plan was modified after it was created. Regenerate it.',
                           fr=f'{path} : le plan a été modifié depuis sa création. Le régénérer.'))
    return plan


def _operation(o: dict) -> Operation:
    """Operation read from a file, where keys introduced since format 1 may be missing."""
    return Operation(**{OPERATION_FIELDS[k]: v for k, v in o.items()})


def newer_plans(path: Path, plan: Plan) -> list[Path]:
    """Plans of the same step prepared after `path`, in the same folder. A regenerated plan does not replace the
    file of the old one, which stays beside it: `zc apply` flags it. Undo plans are not compared."""
    if plan.step == 'annulation':
        return []
    timestamp = path.name[:17]  # YYYY-MM-DD_HHMMSS
    return sorted(p for p in path.parent.glob(f'*_{plan.step}_*.json')
                  if p.name[:17] > timestamp and p.name.split('_')[2] == plan.step)
