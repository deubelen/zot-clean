"""Journal of the writes (D16, D37, D38).

One JSON Lines file per plan run, `journal/<date>_<step>.jsonl`.
An `en-tete` line, an `intention` line per item just before its batch is sent
(complete earlier object reread from the API, fields to write), an `element`
line per item written (the same, and the new version), added as soon as its
batch is confirmed, a `groupe` line per group handled, a `fin` line. A journal
without an end line is that of an interrupted run.

An intention with no item confirming it, in the same journal or a later journal
of the same plan, is a write that may or may not have been done by Zotero
(lost reply, interruption, D178). Resuming the plan confirms it if it finds the
written values, and undoing it is safe, since it only touches a field still at
the written value.

Keys and line types are spelled out literally, never taken from the Python
parameter names, so that renaming code does not change the format of journals
already written (D209).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from zot_clean import __version__

DONE = ('fait', 'partiel')  # group statuses that a resumed run does not redo


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


class Journal:
    def __init__(self, folder: Path, step: str):
        folder.mkdir(parents=True, exist_ok=True)
        database = f'{datetime.now():%Y-%m-%d_%H%M%S}_{step}'
        self.path = folder / f'{database}.jsonl'
        n = 1
        while self.path.exists():
            n += 1
            self.path = folder / f'{database}_{n}.jsonl'
        self._f = self.path.open('a', encoding='utf-8')

    def _line(self, d: dict):
        self._f.write(json.dumps(d, ensure_ascii=False) + '\n')
        self._f.flush()

    def header(self, plan: str, fingerprint: str, step: str, mode: str, library: int, resumed: bool,
                undoes: list[str]):
        self._line({'type': 'en-tete', 'debut': now(), 'zc': __version__, 'plan': plan, 'empreinte': fingerprint,
                     'etape': step, 'mode': mode, 'bibliotheque': library, 'reprise': resumed, 'annule': undoes})

    def intention(self, group: str, rank: int, before: dict, written: dict, kind: str = 'items',
                  created: bool = False) -> dict:
        """Write about to be sent, recorded before sending (D178)."""
        d = _describe('intention', group, rank, before, written, kind, created)
        self._line(d)
        return d

    def item(self, group: str, rank: int, before: dict, written: dict, version: int, kind: str = 'items',
                created: bool = False):
        """`before` is the object reread before the write, reduced to its key for a created collection."""
        self._line(_describe('element', group, rank, before, written, kind, created) | {'version': version})

    def group(self, id_: str, status: str, detail: str = ''):
        self._line({'type': 'groupe', 'id': id_, 'statut': status, 'detail': detail})

    def end(self, done: int, partials: int, conflicts: int, errors: int, all_items: int):
        self._line({'type': 'fin', 'fin': now(), 'faits': done, 'partiels': partials, 'conflits': conflicts,
                     'erreurs': errors, 'elements': all_items})
        self.close()

    def close(self):
        if not self._f.closed:
            self._f.close()


def _describe(type_: str, group: str, rank: int, before: dict, written: dict, kind: str, created: bool) -> dict:
    extra = ({'genre': kind} if kind != 'items' else {}) | ({'cree': True} if created else {})
    return {'type': type_, 'groupe': group, 'rang': rank, 'cle': before['key'], 'avant': before, 'ecrit': written} | extra


def read(path: Path) -> list[dict]:
    lines = []
    for l in path.read_text(encoding='utf-8').splitlines():
        try:
            lines.append(json.loads(l))
        except json.JSONDecodeError:
            break  # last line truncated by an interruption
    return lines


@dataclass
class Summary:
    path: Path
    header: dict
    groups: dict[str, str] = field(default_factory=dict)  # id -> status
    all_items: int = 0
    finished: bool = False


def summarize(path: Path) -> Summary:
    lines = read(path)
    r = Summary(path, lines[0] if lines and lines[0].get('type') == 'en-tete' else {})
    for l in lines:
        if l['type'] == 'groupe':
            r.groups[l['id']] = l['statut']
        elif l['type'] == 'element':
            r.all_items += 1
        elif l['type'] == 'fin':
            r.finished = True
    return r


REGISTRY = 'commandes.jsonl'  # duration of each command (D173), not a journal of writes


def all_entries(folder: Path) -> list[Summary]:
    return [summarize(p) for p in sorted(folder.glob('*.jsonl')) if p.name != REGISTRY] if folder.is_dir() else []


def for_plan(folder: Path, fingerprint: str) -> list[Summary]:
    return [r for r in all_entries(folder) if r.header.get('empreinte') == fingerprint]


def _done(folder: Path, fingerprint: str) -> list[tuple[Summary, set[str]]]:
    """Groups done by each journal of the plan, minus those that an undo of that journal reversed. A plan
    recomputed identically after its undo has the same fingerprint, and must be re-appliable. An
    undo can only target a journal already written, so the order of the names need not be consulted."""
    journals = all_entries(folder)
    res = []
    for r in journals:
        if r.header.get('empreinte') != fingerprint:
            continue
        done = {g for g, s in r.groups.items() if s in DONE}
        for a in journals:
            if r.path.name in a.header.get('annule', []):
                done -= {g for g, s in a.groups.items() if s in DONE}
        res.append((r, done))
    return res


def pending(paths: list[Path]) -> dict[tuple[str, str], dict]:
    """Intentions that nothing confirms, by (group, key), reading the journals in order (D178)."""
    res: dict[tuple[str, str], dict] = {}
    for path in sorted(paths):
        for l in read(path):
            if l['type'] == 'intention':
                res[l['groupe'], l['cle']] = l
            elif l['type'] == 'element':
                res.pop((l['groupe'], l['cle']), None)
    return res


def done_groups(folder: Path, fingerprint: str) -> set[str]:
    return {g for _, done in _done(folder, fingerprint) for g in done}


def trial_done(folder: Path, fingerprint: str) -> bool:
    return any(r.header.get('mode') == 'essai' and done for r, done in _done(folder, fingerprint))
