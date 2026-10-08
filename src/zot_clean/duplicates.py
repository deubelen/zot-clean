"""Duplicates, step 2 of the cleanup (D27, D49 to D51).

`chercher` finds the candidate groups on the copy of the database (DOI, ISBN,
title, first author and year), sorts them into « sûrs » and « à juger » and
writes them to `suivi/doublons.toml`, keeping the decisions already taken. A
group judged distinct is no longer proposed, nor reported by the audit, nor is
a group whose pairs of items all lie in groups judged distinct. A group that
strictly contains a group to merge is not proposed again either, only what it
holds besides (see `find`). `zc duplicates accept <key> --except <key>` takes
items out of a group to merge and judges each of them distinct from the rest
(see `decide`), so that the next search proposes neither the whole group again
nor an excluded item with a merged one.

`planifier` builds, for each group to merge, a plan that does what Zotero's
merge does. The children of the absorbed items are attached to the kept item
(rank 0), the kept item is completed and the items related to the absorbed
ones point to it (rank 1), the absorbed items go to the trash (rank 2). The
data comes from the API, the fingerprints of the attachments from the local
files, since the API's `md5` is empty when files are synced through WebDAV.

The relations follow Zotero's `moveRelations` (`chrome/content/zotero/
mergeItems.mjs`). Those of an absorbed item move to the kept item, except a
link to an item of the group, the absorbed item loses its `dc:replaces`, the
kept item gains a `dc:replaces` to it, and a related item that pointed to the
absorbed item points to the kept item. The groups of one plan are chained
like successive merges, each starting from the relations left by the
previous ones.
"""

import json
import tomllib
from collections import defaultdict
from itertools import combinations
from dataclasses import dataclass, field

from zot_clean import privacy, plans
from zot_clean.citation_keys import base_of
from zot_clean.audit import _doi, _isbns, year, write_toml, line, md5, type_name, norm
from zot_clean.config import Config
from zot_clean.api import Client
from zot_clean.lang import L
from zot_clean.reader import Library, Item, nonempty_note
from zot_clean.plans import Group, Operation, Plan
from zot_clean.sources import titles_match

FILE = 'doublons.toml'
MERGE, DISTINCT = 'fusionner', 'distinct'
CERTAIN, TO_JUDGE = 'sûr', 'à juger'
# A same DOI makes a « sûr » group only with matching titles, at the threshold of the obvious matches of
# step 3 (`metadata.OBVIOUS_THRESHOLD`). At 0.8, an erratum (« Erratum to: <title> ») would still pass.
TITLES_THRESHOLD = 0.9
REPLACES = 'dc:replaces'  # Zotero predicate that keeps the trace of a merge
DO_NOT_COPY = {'key', 'version', 'itemType', 'dateAdded', 'dateModified', 'collections', 'tags', 'relations',
                 'creators', 'deleted', 'parentItem'}


# The natures of the operations of a merge plan are only shown (reports of the plan and of the Inbox sorting),
# never read back from a file: they follow the language of the library.
def fill_in() -> str:
    """Nature of the operation that completes the kept item. `warning` compares it on the plan it has just built."""
    return L(en='complete the kept item', fr='compléter la fiche conservée')


def _move_child(item_type: str) -> str:
    """Nature of a child moved to the kept item."""
    if item_type == 'attachment':
        return L(en='move the attachment', fr='rattacher la pièce jointe')
    if item_type == 'note':
        return L(en='move the note', fr='rattacher la note')
    return L(en=f'move {item_type}', fr=f'rattacher {item_type}')

def header() -> str:
    """Comment header of `suivi/doublons.toml`, in the language of the library. The keys and values it shows stay
    French (D209)."""
    return L(en="""\
# Duplicates found by `zc duplicates find`, with the decisions made.
# This file can be read again and edited by hand or with the agent. `zc duplicates find` updates it
# without losing the decisions, `zc duplicates plan` prepares the merge of the groups to merge.
# Decisions are written with `zc duplicates accept` (merge, --keep) and `zc duplicates reject` (distinct).
#
# decision  : "fusionner", "distinct" (different editions or texts, not to be reported any more) or "" (to judge).
# conserver : key of the item to keep (optional, otherwise the one with the most attachments, then the oldest).
# forcer    : values imposed on the kept item, for example { "date" = "1938" } (optional).
# raison    : free note, useful for the groups judged distinct.
#
# A group that `zc duplicates find` did not spot is added at the end of the file, for example
#   [[groupe]]
#   cles = ["ABCD1234", "EFGH5678"]
#   decision = "fusionner"
# It is kept as long as its items exist.
""", fr="""\
# Doublons repérés par `zc duplicates find`, avec les décisions prises.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc duplicates find` le met à jour
# sans perdre les décisions, `zc duplicates plan` prépare la fusion des groupes à fusionner.
# Les décisions s'écrivent avec `zc duplicates accept` (fusionner, --keep) et `zc duplicates reject` (distinct).
#
# decision  : "fusionner", "distinct" (éditions ou textes différents, à ne plus signaler) ou "" (à juger).
# conserver : clé de la fiche à garder (facultatif, sinon celle qui a le plus de pièces jointes, puis la plus ancienne).
# forcer    : valeurs imposées à la fiche gardée, par exemple { "date" = "1938" } (facultatif).
# raison    : note libre, utile pour les groupes jugés distincts.
#
# Un groupe que `zc duplicates find` n'a pas repéré s'ajoute à la fin du fichier, par exemple
#   [[groupe]]
#   cles = ["ABCD1234", "EFGH5678"]
#   decision = "fusionner"
# Il est gardé tant que ses fiches existent.
""")


def candidates(b: Library, among: list[Item] | None = None) -> list[list[Item]]:
    """Groups of items that share a DOI, an ISBN, a signature (title, year, first author, type) or a PDF. With
    `among`, only these items are grouped, the links through other items being ignored (`find`)."""
    pool = b.items if among is None else among
    parent = {e.id: e.id for e in pool}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    index = defaultdict(list)
    for e in pool:
        # Chapters often carry the DOI or ISBN of the book, which does not distinguish them.
        if e.fields.get('DOI') and e.type != 'bookSection':
            index['doi', _doi(e.fields['DOI'])].append(e.id)
        if e.type == 'book':
            for i in _isbns(e.fields.get('ISBN', '')):
                index['isbn', i].append(e.id)
        title = norm(e.title)
        if len(title) >= 10:
            author = norm(e.author)
            index['sig', title[:60], year(e), author, e.type].append(e.id)
    # Items that carry the same PDF are often duplicates, or one received the PDF of the other (D125).
    from zot_clean.attachments import identical_groups
    attachments = {att.key: att.parent for att in b.attachments.values()}
    items = {e.id for e in pool}
    for copies in identical_groups(b):
        index['pdf', copies[0]] = list(dict.fromkeys(attachments[k] for k in copies if attachments.get(k) in items))
    for ids in index.values():
        for x in ids[1:]:
            parent[root(x)] = root(ids[0])
    groups = defaultdict(list)
    for e in pool:
        groups[root(e.id)].append(e)
    return sorted((g for g in groups.values() if len(g) > 1), key=lambda g: norm(g[0].title))


def assign_grade(g: list[Item]) -> str:
    """« sûr », a group of the same type that shares the DOI and has matching titles, or the title, creators and
    year (D49). A chapter imported with the DOI of the book, or an erratum entered with that of the article,
    shares the DOI without being a duplicate: without matching titles, the group is « à juger »."""
    if len({e.type for e in g}) > 1:
        return TO_JUDGE
    dois = {_doi(e.fields.get('DOI', '')) for e in g}
    if (len(dois) == 1 and '' not in dois and g[0].type != 'bookSection'
            and all(titles_match(g[0].title, e.title, TITLES_THRESHOLD) for e in g[1:])):
        return CERTAIN
    signatures = {(norm(e.title), tuple(norm(n) for n, _ in e.creators), year(e)) for e in g}
    return CERTAIN if len(signatures) == 1 and next(iter(signatures))[0] else TO_JUDGE


@dataclass
class Entry:
    keys: list[str]
    grade: str
    decision: str = ''
    keep: str = ''
    reason: str = ''
    force: dict = field(default_factory=dict)


def load_tracking(cfg: Config) -> list[Entry]:
    path = cfg.tracking / FILE
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start over.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    entries = []
    for g in raw.get('groupe', []):
        e = Entry(list(g['cles']), g.get('classe', TO_JUDGE), g.get('decision', ''), g.get('conserver', ''),
                   g.get('raison', ''), dict(g.get('forcer', {})))
        if e.decision not in ('', MERGE, DISTINCT):
            names = ', '.join(e.keys)
            raise SystemExit(L(en=f'{path}: unknown decision “{e.decision}” for {names}.',
                               fr=f'{path} : décision inconnue « {e.decision} » pour {names}.'))
        entries.append(e)
    return entries


def distinct_sets(entries: list[Entry]) -> list[set[str]]:
    return [set(e.keys) for e in entries if e.decision == DISTINCT]


def already_judged(keys: set[str], distinct_sets_: list[set[str]]) -> bool:
    """A group is already judged when it lies in a group judged distinct, or when each of its pairs of items does,
    as after `zc duplicates accept --except`, which judges each excluded item distinct from each merged one."""
    if any(keys <= d for d in distinct_sets_):
        return True
    return len(keys) > 1 and all(any({u, v} <= d for d in distinct_sets_) for u, v in combinations(sorted(keys), 2))


def _toml(v) -> str:
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return '[' + ', '.join(_toml(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{json.dumps(k, ensure_ascii=False)} = {_toml(x)}' for k, x in v.items()) + ' }'
    return json.dumps(v)


def write_tracking(cfg: Config, entries: list[Entry], b: Library) -> None:
    by_key = b.by_key()
    hidden = privacy.hidden_keys(b, cfg)
    n_atts = defaultdict(int)
    for p in b.attachments.values():
        n_atts[p.parent] += 1
    lines = [header()]
    for e in entries:
        lines += ['[[groupe]]']
        # The items of a group look alike: a single confidential item hides the whole group (D126).
        cache = set(e.keys) if hidden & set(e.keys) else set()
        for key in e.keys:
            f = by_key.get(key)
            lines.append(L(en=f'# {line(f, cache)} ({type_name(f.type)}, {n_atts[f.id]} attachment(s))',
                           fr=f'# {line(f, cache)} ({type_name(f.type)}, {n_atts[f.id]} pièce(s) jointe(s))') if f
                         else L(en=f'# {key} (not in the library)', fr=f'# {key} (absente de la bibliothèque)'))
        lines += [f'cles = {_toml(e.keys)}', f'classe = {_toml(e.grade)}', f'decision = {_toml(e.decision)}',
                   f'conserver = {_toml(e.keep)}', f'raison = {_toml(e.reason)}', f'forcer = {_toml(e.force)}',
                   '']
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    write_toml(cfg.tracking / FILE, lines)


def decide(entries: list[Entry], certain: bool = False, to_merge=(), distinct=(), keep=(), except_=(),
            reason: str = '') -> tuple[int, int, int]:
    """Decisions taken by command (D177, modelled on D172), instead of writing the file by hand. Each
    group is designated by the key of one of its items. `to_merge` and `keep` (the item to keep) give the
    groups to merge, `distinct` those that are not duplicates, with `reason`. `certain` merges all the « sûrs »
    groups still « à juger », except those that contain an item of `except_`. Only the groups still « à juger »
    change.

    An item of `except_` that belongs to a group designated by `to_merge` or `keep` is taken out of that group
    instead: three items share a wrong DOI, two are duplicates, the third is another article. The group is
    merged without it, and each excluded item is judged distinct from each item that stays, one `[[groupe]]`
    `decision = "distinct"` per pair, the structure of the files of 0.3.2 (D209). The next `find` then proposes
    neither the whole group nor, once merged, the excluded item with the kept one (`already_judged`). Two excluded
    items are not judged between them, and `find` proposes them together if they look alike. Without
    `certain`, an `except_` key outside the designated groups is refused, as is a group left with fewer than two
    items.

    Returns the number of groups to merge, of distinct groups and of items taken out of a group."""
    to_judge: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        if not e.decision:
            for k in e.keys:
                to_judge[k].append(e)
    known = {k for e in entries for k in e.keys}
    requested = [*to_merge, *keep, *distinct]
    unknowns = [k for k in requested if k not in to_judge]
    if unknowns:
        missing_keys = [k for k in unknowns if k not in known]
        decided = [k for k in unknowns if k in known]
        chunks = []
        if missing_keys:
            names = ', '.join(missing_keys)
            chunks.append(L(en=f'No group of {FILE} contains {names}. Check the key, or run `zc duplicates find` '
                               f'again. Two items that zc has not brought together are added by hand at the end '
                               f'of the file, as its header shows.',
                            fr=f"Aucun groupe de {FILE} ne contient {names}. Vérifier la clé, ou "
                               f"relancer `zc duplicates find`. Deux fiches que zc n'a pas réunies s'ajoutent à la "
                               f"main en fin de fichier, comme le montre son en-tête."))
        if decided:
            names = ', '.join(decided)
            chunks.append(L(en=f'The group of {names} is already decided. A decision that was made is changed by '
                               f'hand in the file.',
                            fr=f'Le groupe de {names} est déjà décidé. Une décision prise se change à la '
                               f'main dans le fichier.'))
        raise SystemExit(' '.join(chunks))
    if (ambiguous := [k for k in requested if len(to_judge[k]) > 1]):
        names = ', '.join(ambiguous)
        raise SystemExit(L(en=f'{names} appears in several groups to judge. Separate them by hand in {FILE}.',
                           fr=f'{names} figure dans plusieurs groupes à juger. Les départager à la main '
                              f'dans {FILE}.'))
    if (outside := [k for k in except_ if k not in known]):
        names = ', '.join(outside)
        raise SystemExit(L(en=f'No group of {FILE} contains {names}.', fr=f'Aucun groupe de {FILE} ne contient {names}.'))
    kept = [to_judge[k][0] for k in keep]
    if len({id(e) for e in kept}) < len(kept):
        raise SystemExit(L(en='Only one item kept per group.', fr='Une seule fiche conservée par groupe.'))
    merge = {id(to_judge[k][0]): to_judge[k][0] for k in [*to_merge, *keep]}
    distinct_sets_ = {id(to_judge[k][0]): to_judge[k][0] for k in distinct}
    if merge.keys() & distinct_sets_.keys():
        raise SystemExit(L(en='A same group cannot be both merged and distinct.',
                           fr='Un même groupe ne peut pas être à la fois fusionné et distinct.'))
    taken_out, skipped = _taken_out(merge, except_, [*to_merge, *keep], certain)
    for k in keep:
        to_judge[k][0].keep = k
    for e in merge.values():
        e.decision = MERGE
    for e, out in taken_out:
        _take_out(entries, e, out)
    for e in distinct_sets_.values():
        e.decision, e.reason = DISTINCT, reason or e.reason
    n = len(merge)
    if certain:
        for e in entries:
            if e.grade == CERTAIN and not e.decision and not skipped & set(e.keys):
                e.decision = MERGE
                n += 1
    return n, len(distinct_sets_), sum(len(out) for _, out in taken_out)


def _taken_out(merge: dict[int, Entry], except_, designators: list[str],
               certain: bool) -> tuple[list[tuple[Entry, list[str]]], set[str]]:
    """Items of `except_` to take out of a group designated to merge (`decide`), and the other keys of `except_`,
    which designate the groups that `certain` leaves aside. Refuses a designating key, a key outside the designated
    groups without `certain`, and a group that would keep fewer than two items."""
    by_group: dict[int, list[str]] = defaultdict(list)
    skipped = set()
    for k in dict.fromkeys(except_):
        e = next((e for e in merge.values() if k in e.keys), None)
        if e is None:
            skipped.add(k)
        else:
            by_group[id(e)].append(k)
    if (both := [k for k in designators if k in except_]):
        names = ', '.join(dict.fromkeys(both))
        raise SystemExit(L(en=f'{names} designates the group to merge and cannot be taken out of it with --except. '
                              f'Designate the group by an item that stays in it.',
                           fr=f'{names} désigne le groupe à fusionner et ne peut pas en être retiré par --except. '
                              f'Désigner le groupe par une fiche qui y reste.'))
    if skipped and not certain:
        names, groups = ', '.join(sorted(skipped)), ', '.join(dict.fromkeys(designators))
        raise SystemExit(L(en=f'{names} is not in the group of {groups}. --except takes items out of the group to '
                              f'merge (or, with --certain, leaves aside the certain groups that contain them). Check '
                              f'the keys in {FILE}.',
                           fr=f"{names} n'est pas dans le groupe de {groups}. --except retire des fiches du groupe à "
                              f"fusionner (ou, avec --certain, écarte les groupes sûrs qui les contiennent). Vérifier "
                              f"les clés dans {FILE}."))
    res = []
    for e in merge.values():
        if not (out := by_group.get(id(e))):
            continue
        if len(e.keys) - len(out) < 2:
            names = ', '.join(e.keys)
            raise SystemExit(L(en=f'The group {names} would keep fewer than two items without {", ".join(out)}. '
                                  f'If none of its items are duplicates, judge it distinct with '
                                  f'`zc duplicates reject`.',
                               fr=f'Le groupe {names} garderait moins de deux fiches sans {", ".join(out)}. Si '
                                  f'aucune de ses fiches ne fait doublon, le juger distinct avec '
                                  f'`zc duplicates reject`.'))
        res.append((e, out))
    return res, skipped


def _take_out(entries: list[Entry], e: Entry, out: list[str]) -> None:
    """Removes `out` from the group `e` and judges each of its items distinct from each item that stays, by a pair
    written just after the group (`decide`). A pair already in the file keeps its decision, or is judged distinct
    if it was still to judge."""
    e.keys = [k for k in e.keys if k not in out]
    if e.keep in out:
        e.keep = ''
    stays = ', '.join(e.keys)
    by_keys = {frozenset(x.keys): x for x in entries}
    pairs = []
    for x in out:
        # Free note of the pair (`raison`), in the language of the library like the header of the file.
        reason = L(en=f'{x} taken out of the group to merge {stays} (zc duplicates accept --except)',
                   fr=f'{x} retirée du groupe à fusionner {stays} (zc duplicates accept --except)')
        for k in e.keys:
            if (known := by_keys.get(frozenset({k, x}))) is not None:
                if not known.decision:
                    known.decision, known.reason = DISTINCT, known.reason or reason
                continue
            pairs.append(Entry([k, x], TO_JUDGE, DISTINCT, reason=reason))
    i = next(i for i, x in enumerate(entries) if x is e) + 1
    entries[i:i] = pairs


def find(b: Library, cfg: Config) -> list[Entry]:
    """Groups found in the library, written to `suivi/doublons.toml` with the decisions already taken.

    A group found that strictly contains a group to merge of the file (three items sharing a wrong DOI, of
    which the user merges two, by `zc duplicates accept --except` or by editing `cles` by hand) is not proposed
    again. Only what it holds besides is, the items outside the groups to merge, grouped among themselves
    (`candidates` restricted to them) and proposed if at least two of them look alike. A single item left over
    is not proposed while the merge waits. Once the merge is applied, the absorbed items are in the trash and
    the kept one, if it still looks like the item left over, forms a new group with it, unless `--except` has
    judged them distinct. A group judged distinct is never cut this way, since it stays in the file for good: a
    group found that contains it is still proposed whole when one of its pairs of items is not judged distinct
    (a new duplicate of one of two editions), and skipped otherwise (`already_judged`)."""
    old_ones = load_tracking(cfg)
    by_keys = {frozenset(e.keys): e for e in old_ones}
    dist = distinct_sets(old_ones)
    present_keys = {e.key for e in b.items}
    to_merge = [frozenset(e.keys) for e in old_ones
                if e.decision == MERGE and len(e.keys) > 1 and set(e.keys) <= present_keys]
    current, visited = [], set()
    for found in candidates(b):
        for g in _beside_merges(b, found, to_merge, by_keys):
            keys = frozenset(e.key for e in g)
            if keys in visited or already_judged(set(keys), dist):
                continue
            e = by_keys.get(keys) or Entry(sorted(keys), '')
            e.grade = assign_grade(g)
            current.append(e)
            visited.add(keys)
    # Groups judged distinct stay in memory, even when they are no longer found. A group to merge
    # that zc does not find (added by hand, DOI removed in the meantime, or cut out of a bigger group found)
    # stays as long as its items exist.
    kept = [e for e in old_ones if frozenset(e.keys) not in visited and
               (e.decision == DISTINCT or e.decision == MERGE and len(e.keys) > 1 and set(e.keys) <= present_keys)]
    current.sort(key=lambda e: (e.decision != '', e.grade != CERTAIN))
    entries = current + kept
    write_tracking(cfg, entries, b)
    return entries


def _beside_merges(b: Library, found: list[Item], to_merge: list[frozenset[str]],
                   by_keys: dict[frozenset[str], Entry]) -> list[list[Item]]:
    """The group found, or, when it strictly contains groups to merge of the file, the groups that its other
    items form among themselves (`find`). A group found that the file already holds with a decision is kept
    as it is."""
    keys = frozenset(e.key for e in found)
    if (known := by_keys.get(keys)) is not None and known.decision:
        return [found]
    inside = [m for m in to_merge if m < keys]
    if not inside:
        return [found]
    # The group to merge was cut out of this one: proposing the whole group again would undo the cut, and
    # its decided items are already settled. Only the rest can still hold duplicates.
    rest = [e for e in found if not any(e.key in m for m in inside)]
    return candidates(b, rest) if len(rest) > 1 else []


# --- Merge plan -------------------------------------------------------------

class _Files:
    """Fingerprints and attachments of the attached files, from the local database."""

    def __init__(self, b: Library):
        self.b = b
        self.by_key = b.by_key()
        self.note_parents = {p for p in b.notes.values() if p}

    def fingerprint(self, key: str) -> str:
        e = self.by_key.get(key)
        p = self.b.attachments.get(e.id) if e else None
        return md5(p.file) if p and p.file and p.file.is_file() else ''

    def annotated(self, key: str) -> bool:
        e = self.by_key.get(key)
        return bool(e and (self.b.annotations.get(e.id) or e.id in self.note_parents
                           or (e.id in self.b.attachments and self.b.attachments[e.id].note)))  # the attachment's own note (D206)


def _att_count(children: list[dict]) -> int:
    return sum(1 for k in children if k['itemType'] == 'attachment')


def _choose(items: list[dict], children: dict[str, list[dict]], keep: str) -> dict:
    if keep:
        return next(d for d in items if d['key'] == keep)
    return sorted(items, key=lambda d: (-_att_count(children[d['key']]), d.get('dateAdded', '')))[0]


def _to_list(v) -> list[str]:
    return [v] if isinstance(v, str) else list(v or [])


def _relations(d: dict) -> dict[str, list[str]]:
    """Relations of an item, a list of addresses per predicate (the API gives a string for a single one)."""
    return {p: _to_list(v) for p, v in (d.get('relations') or {}).items() if _to_list(v)}


def _add(relations: dict, p: str, o: str) -> None:
    if o not in relations.setdefault(p, []):
        relations[p].append(o)


class _Links:
    """Relations planned by the groups already planned, so that each group starts from the state left by the
    previous ones, like successive merges in Zotero, and so that `before` matches what the base will reread."""

    def __init__(self, client: Client, hidden: set[str]):
        self.client, self.hidden = client, hidden
        self.planned: dict[str, dict] = {}
        self.absorbed_keys: set[str] = set()
        self.fetched: dict[str, dict | None] = {}
        self.prefix = client.uri('')  # address of the items of this library, up to the key

    def of(self, d: dict) -> dict[str, list[str]]:
        return json.loads(json.dumps(self.planned.get(d['key'], _relations(d))))

    def kept_item(self, m: dict, others: list[dict]) -> dict:
        """Relations of the kept item. Those of the absorbed items move to it, except a link to an item of the group
        (Zotero drops the link to the kept item, zc also drops one to another absorbed item, also headed for the
        trash), then a `dc:replaces` to each absorbed item. The links it already had stay."""
        relations, group = self.of(m), {self.client.uri(d['key']) for d in [m, *others]}
        for d in others:
            for p, objects in self.of(d).items():
                for o in objects:
                    if o not in group:
                        _add(relations, p, o)
            _add(relations, REPLACES, self.client.uri(d['key']))
        return relations

    def related(self, m: dict, others: list[dict]) -> list[Operation]:
        """Items outside the group that point to an absorbed item: their link moves to the kept item (rank 1).
        They are found through the links of the absorbed item, which Zotero sets on both sides (« Connexe »), and
        among the relations already planned by the plan. An item absorbed by a previous group is not touched."""
        group_keys = {d['key'] for d in [m, *others]}
        uris = {self.client.uri(d['key']): d['key'] for d in others}
        candidate_keys = {o[len(self.prefix):] for d in others for p, objects in self.of(d).items() if p != REPLACES
                      for o in objects if o.startswith(self.prefix)}
        candidate_keys |= {k for k, r in self.planned.items()
                       if any(o in uris for p, objects in r.items() if p != REPLACES for o in objects)}
        candidate_keys -= group_keys | self.absorbed_keys
        if (to_read := sorted(k for k in candidate_keys if k not in self.fetched)):
            fetched = self.client.items(to_read)
            self.fetched.update({k: fetched.get(k) for k in to_read})
        ops, to = [], self.client.uri(m['key'])
        for k in sorted(candidate_keys):
            if self.fetched.get(k) is None:  # deleted for good, or address of another library
                continue
            before = self.of(self.fetched[k])
            after, sources = json.loads(json.dumps(before)), []
            for p, objects in after.items():
                if p == REPLACES:
                    continue
                for o in [o for o in objects if o in uris]:
                    objects.remove(o)
                    if to not in objects:
                        objects.append(to)
                    sources.append(uris[o])
            if not sources:
                continue
            self.planned[k] = after
            mask = f' {privacy.mask()}' if k in self.hidden else ''
            linked, kept = ', '.join(dict.fromkeys(sources)), m['key']
            ops.append(Operation(k, {'relations': before}, {'relations': after}, 1,
                                 L(en=f'linked item {k}{mask}: its link to {linked} moves to {kept}',
                                   fr=f'fiche liée {k}{mask} : son lien vers {linked} passe à {kept}')))
        return ops

    def trash(self, d: dict) -> tuple[dict, dict]:
        """Before and after of trashing an absorbed item, which loses its `dc:replaces`, moved to the kept item,
        so that a replaced item does not have two replacers (Zotero)."""
        self.absorbed_keys.add(d['key'])
        relations = self.of(d)
        if REPLACES not in relations:
            return {'deleted': False}, {'deleted': True}
        without = {p: o for p, o in relations.items() if p != REPLACES}
        self.planned[d['key']] = without
        return {'deleted': False, 'relations': relations}, {'deleted': True, 'relations': without}


def _merge(m: dict, others: list[dict], children: dict[str, list[dict]], force: dict, links: _Links,
            files: _Files, cache: bool = False):
    """Merge operations and differing values. With `cache`, the natures cite no title (D126)."""
    valid = set(m) - DO_NOT_COPY
    update = {}
    for d in others:
        for f in sorted(valid):
            if not m.get(f) and d.get(f) and f not in update:
                update[f] = d[f]
    if not m.get('creators'):
        update['creators'] = next((d['creators'] for d in others if d.get('creators')), [])
        if not update['creators']:
            del update['creators']
    differences = [(f, m[f], d[f]) for d in others for f in sorted(valid)
                   if m.get(f) and d.get(f) and d[f] != m[f] and f not in force]
    # The kept item carries the key suffixed by Better BibTeX (« ozgen2002a ») and an absorbed item the base key
    # (« ozgen2002 »), the oldest and most cited: the kept item takes this one (pilot rehearsal).
    keeper = str(m.get('citationKey') or '').strip()
    database = next((k for d in others if (k := str(d.get('citationKey') or '').strip())
                 and k != keeper and base_of(keeper).lower() == k.lower()), None)
    if keeper and database and 'citationKey' not in force:
        update['citationKey'] = database
    update.update(force)

    collections = list(dict.fromkeys(m.get('collections', []) + [c for d in others for c in d.get('collections', [])]))
    if collections != m.get('collections', []):
        update['collections'] = collections
    tags, seen_set = list(m.get('tags', [])), {(t['tag'], t.get('type', 0)) for t in m.get('tags', [])}
    for d in others:
        for t in d.get('tags', []):
            if (t['tag'], t.get('type', 0)) not in seen_set:
                seen_set.add((t['tag'], t.get('type', 0)))
                tags.append(t)
    if len(tags) != len(m.get('tags', [])):
        update['tags'] = tags
    update['relations'] = links.kept_item(m, others)

    ops = []
    fingerprints = {files.fingerprint(k['key']) for k in children[m['key']] if k['itemType'] == 'attachment'} - {''}
    for d in others:
        for k in children[d['key']]:
            h = files.fingerprint(k['key']) if k['itemType'] == 'attachment' else ''
            annotated = files.annotated(k['key'])
            # Note of the attachment itself (`note` field of the item), which Zotero carries over when merging.
            has_note = k['itemType'] == 'attachment' and nonempty_note(k.get('note'))  # empty, Zotero wraps it
            if h and h in fingerprints and not k.get('tags') and not annotated and not has_note:
                title = '' if cache else k.get('title', '')
                ops.append(Operation(k['key'], {'deleted': False}, {'deleted': True}, 0,
                                     L(en='identical attachment to the trash', fr='pièce jointe identique à la corbeille')
                                     + ('' if cache else L(en=f': {title}', fr=f' : {title}')), children=[]))
            else:
                # An identical copy that is annotated, noted or tagged is never trashed (D51, D125).
                keeper = (L(en='its attachment note', fr='sa note de pièce jointe') if has_note
                          else L(en='its annotations or notes', fr='ses annotations ou notes') if annotated
                          else L(en='its tags', fr='ses tags'))
                why = (L(en=f' (identical to a copy already there, kept for {keeper})',
                         fr=f' (identique à une copie déjà présente, gardée pour {keeper})')
                       if h and h in fingerprints else '')

                # The text of a note never leaves the journal (D191).
                title = '' if cache else k.get('title') or ''
                ops.append(Operation(k['key'], {'parentItem': d['key']}, {'parentItem': m['key']}, 0,
                                     _move_child(k['itemType'])
                                     + (L(en=f': {title}', fr=f' : {title}') if title else '') + why))
                if h:
                    fingerprints.add(h)
    before = {f: plans.raw_value(m, f) for f in update} | {'relations': links.of(m)}
    ops.append(Operation(m['key'], before, update, 1, fill_in()))
    links.planned[m['key']] = update['relations']
    ops += links.related(m, others)
    for d in others:
        before, after = links.trash(d)
        ops.append(Operation(d['key'], before, after, 2, L(en='absorbed item to the trash',
                                                            fr='fiche absorbée à la corbeille'),
                             children=[k['key'] for k in children[d['key']]]))
    return ops, differences


def _short(v) -> str:
    return repr(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))[:70]


def make_plan(cfg: Config, client: Client, b: Library) -> tuple[Plan, str]:
    """Merge plan for the groups decided « fusionner » only. A « sûr » group without a decision does not enter it,
    it is accepted first with `zc duplicates accept --certain` (D49)."""
    entries = load_tracking(cfg)
    chosen = [e for e in entries if e.decision == MERGE]
    data = client.items([k for e in chosen for k in e.keys])
    files = _Files(b)
    hidden = privacy.hidden_keys(b, cfg)
    links = _Links(client, hidden)
    groups, refusal, details = [], [], []
    for e in chosen:
        items = [data.get(k) for k in e.keys]
        missing = [k for k, d in zip(e.keys, items) if d is None]
        if missing:
            names = ', '.join(missing)
            refusal.append((e, L(en=f'not found: {names}', fr=f'introuvable(s) : {names}')))
            continue
        if any(d.get('deleted') for d in items):
            refusal.append((e, L(en='an item is already in the trash', fr='une fiche est déjà à la corbeille')))
            continue
        types = sorted({d['itemType'] for d in items})
        if len(types) > 1:
            names = ', '.join(type_name(t) for t in types)
            refusal.append((e, L(en=f'different types ({names}), change the type first (step 3)',
                                 fr=f"types différents ({names}), changer d'abord le type (étape 3)")))
            continue
        if e.keep and e.keep not in e.keys:
            refusal.append((e, L(en=f'conserver = “{e.keep}” is not part of the group',
                                 fr=f'conserver = « {e.keep} » ne fait pas partie du groupe')))
            continue
        children = {d['key']: [k for k in client.children(d['key']) if not k.get('deleted')] for d in items}
        m = _choose(items, children, e.keep)
        others = [d for d in items if d['key'] != m['key']]
        cache = any(k in hidden for k in e.keys)
        ops, differences = _merge(m, others, children, e.force, links, files, cache)
        gid = str(len(groups) + 1)
        groups.append(Group(gid, privacy.mask() if cache else m.get('title', '')[:80], ops))
        details.append(_detail(gid, m, others, children, ops, differences, cache))
    # The description is only shown (`zc apply`), never read back: it follows the language of the library.
    plan = Plan('doublons', client.user, groups,
                description=L(en=f'Merge of {len(groups)} group(s) of duplicates.',
                              fr=f'Fusion de {len(groups)} groupe(s) de doublons.'))
    to_judge = sum(1 for e in entries if not e.decision)
    return plan, _report(plan, refusal, details, to_judge, warning(b, cfg, plan))


def warning(b: Library, cfg: Config, plan: Plan) -> str:
    """PDFs of the plan's items missing from disk (D168). Without the file, zc cannot recognize an identical copy,
    which is then attached to the kept item instead of going to the trash."""
    from zot_clean import bbt
    from zot_clean.audit import missing_reminder
    items = {op.key for g in plan.groups for op in g.operations if op.rank == 2 or op.nature == fill_in()}
    follow_up = L(en='. An identical copy is then attached to the kept item instead of going to the trash, and '
                     'the item keeps the same file twice',
                  fr=". Une copie identique est alors rattachée à la fiche conservée au lieu d'aller à la corbeille, "
                     "et la fiche garde deux fois le même fichier")
    return missing_reminder(b, bbt.file_storage(cfg.zotero_dir), follow_up, items,
                            bbt.downloads_at_sync(cfg.zotero_dir)) if items else ''


def _detail(gid, m, others, children, ops, differences, cache: bool = False) -> list[str]:
    """Detail of a group. With `cache`, no title or value, only the keys and the field names (D126)."""
    title = privacy.mask() if cache else m.get('title', '')[:90]
    r = [L(en=f'### Group {gid}. {title}', fr=f'### Groupe {gid}. {title}'), '']

    def described(d: dict, verb: str) -> str:
        date = d.get('date', '') or L(en='n.d.', fr='s. d.')
        n = _att_count(children[d['key']])
        added = d.get('dateAdded', '')[:10]
        kind = type_name(d['itemType'])
        key = d['key']
        return L(en=f"- {verb} {key} ({kind}, {date}, {n} attachment(s), added on {added})",
                 fr=f"- {verb} {key} ({kind}, {date}, {n} pièce(s) jointe(s), ajoutée le {added})")

    r.append(described(m, L(en='keep', fr='conserver')))
    r += [described(d, L(en='absorb', fr='absorber')) for d in others]
    op_m = next(op for op in ops if op.key == m['key'])
    update = op_m.after
    fields = {k: v for k, v in update.items() if k not in ('relations', 'collections', 'tags')}
    if fields:
        listed = ', '.join(k if cache else f'{k} = {_short(v)}' for k, v in fields.items())
        r.append(L(en=f'- fields completed: {listed}', fr=f'- champs complétés : {listed}'))
    if 'collections' in update:
        before, after = len(m.get('collections', [])), len(update['collections'])
        r.append(L(en=f'- collections: {before} → {after}', fr=f'- collections : {before} → {after}'))
    if 'tags' in update:
        before, after = len(m.get('tags', [])), len(update['tags'])
        r.append(L(en=f'- tags: {before} → {after}', fr=f'- tags : {before} → {after}'))
    taken_over = sum(len(set(o) - set(op_m.before['relations'].get(p, []))) for p, o in update['relations'].items()
                 if p != REPLACES)
    if taken_over:
        r.append(L(en=f'- “Related” links or other relations taken over from the absorbed items: {taken_over}',
                   fr=f'- liens « Connexe » ou autres relations repris des fiches absorbées : {taken_over}'))
    r += [f'- {op.nature}' for op in ops if op.rank == 0 or op.rank == 1 and op.key != m['key']]
    # Citation key of an absorbed item that disappears with it (D146), reported apart from the other differences.
    kept_item = str(update.get('citationKey') or m.get('citationKey') or '').strip()
    if (former := str(m.get('citationKey') or '').strip()) and former != kept_item:
        mk = m['key']
        r.append(L(en=f"- citation key of {mk} replaced by that, without suffix, of an absorbed item",
                   fr=f"- clé de citation de {mk} remplacée par celle, sans suffixe, d'une fiche absorbée") if cache
                 else L(en=f"- citation key “{former}” of {mk} replaced by “{kept_item}”, without suffix, of an "
                           f"absorbed item. A text that cites the old one must be updated",
                        fr=f"- clé de citation « {former} » de {mk} remplacée par « {kept_item} », sans suffixe, "
                           f"d'une fiche absorbée. Un texte qui cite l'ancienne est à mettre à jour"))
    for d in others:
        if (key := str(d.get('citationKey') or '').strip()) and key != kept_item:
            dk = d['key']
            r.append(L(en=f"- citation key of {dk} that disappears, the kept item keeping its own",
                       fr=f"- clé de citation de {dk} qui disparaît, la fiche conservée gardant la sienne")
                     if cache else L(en=f"- citation key “{key}” of {dk} that disappears, the kept item keeping "
                                        f"“{kept_item}”. A text that cites it must be updated",
                                     fr=f"- clé de citation « {key} » de {dk} qui disparaît, la fiche conservée "
                                        f"gardant « {kept_item} ». Un texte qui la cite est à mettre à jour"))
    differences = [x for x in differences if x[0] != 'citationKey']
    if differences:
        r.append(L(en='- different values, that of the kept item is kept (impose a value with `forcer`):',
                   fr='- valeurs différentes, celle de la fiche conservée est gardée (imposer une valeur avec '
                      '`forcer`) :'))
        r += [f'  - {f}' if cache else L(en=f'  - {f}: {_short(a)} kept, {_short(b)} set aside',
                                         fr=f'  - {f} : {_short(a)} gardé, {_short(b)} écarté')
              for f, a, b in differences]
    return r + ['']


def _report(plan: Plan, refusal: list, details: list[list[str]], to_judge: int, warn_msg: str = '') -> str:
    n_groups, n_operations = len(plan.groups), plan.n_operations
    r = [L(en='# Merge of duplicates', fr='# Fusion de doublons'), '',
         *([L(en=f'**Warning.** {warn_msg}', fr=f'**Attention.** {warn_msg}'), ''] if warn_msg else []),
         L(en=f'{n_groups} group(s) to merge, {n_operations} operation(s). As in Zotero, notes and attachments move '
              f'to the kept item, empty fields are completed, collections and tags are combined, the “Related” '
              f'links of the absorbed items move to the kept item, on their side as on that of the linked items, '
              f'and the absorbed items go to the trash with a link to the kept item.',
           fr=f"{n_groups} groupe(s) à fusionner, {n_operations} opération(s). Comme dans Zotero, les "
              f"notes et pièces jointes passent sur la fiche conservée, les champs vides sont complétés, collections "
              f"et tags réunis, les liens « Connexe » des fiches absorbées passent à la fiche conservée, de leur côté "
              f"comme de celui des fiches liées, et les fiches absorbées vont à la corbeille avec un lien vers la "
              f"fiche conservée."), '',
         L(en="Zotero empties the trash automatically (after 30 days by default). After that, a merge can no "
              "longer be undone by `zc undo`.",
           fr="Zotero vide la corbeille automatiquement (après 30 jours par défaut). Passé ce délai, une fusion "
              "n'est plus annulable par `zc undo`."), '']
    if to_judge:
        r += [L(en=f'{to_judge} group(s) remain to be judged in suivi/doublons.toml.',
                fr=f'{to_judge} groupe(s) restent à juger dans suivi/doublons.toml.'), '']
    if refusal:
        r += [L(en='## Groups set aside', fr='## Groupes écartés'), '']
        r += [L(en=f"- {', '.join(e.keys)}: {reason}", fr=f"- {', '.join(e.keys)} : {reason}")
              for e, reason in refusal] + ['']
    r += [L(en='## Detail', fr='## Détail'), '']
    for d in details:
        r += d
    return '\n'.join(r)
