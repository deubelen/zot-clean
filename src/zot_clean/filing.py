"""Filing, step 5 of the cleanup (D112 to D122).

`make_plan` compares the real state of the library to the state aimed at by
the validated plan (`plan.md`, `suivi/fonds.toml`) and by the accepted
decisions of `suivi/rangement.toml`, and plans only the difference (D119). It
can therefore be rerun safely, after an interrupted pass, a manual touch-up in
Zotero or an undo.

The subject tree is transformed in place (D113). Each path of the plan is
embodied by a collection. It is the old collection destined for it (fate
« thème »), the one already there, or a collection created under a key drawn
here (D114). Several old collections with the same target are merged into
one of them, the others go to the trash once emptied (D117). Projects and
archives are moved, dissolved collections go to the trash. The old
collections are designated by their key (D118).

The plan has one group per target collection, in tree order (D120), with its
collection change at rank 0 and the items entering it at rank 1. An item that
enters several collections goes in the group of the first one, or in that of
the last one created by the plan if it comes later, so that its write never
precedes a creation. Then come projects and archives, the collections to
trash, the items to trash, then the roots (D112), which are renamed only on
request.
"""

import json
import re
import secrets
import tomllib
from dataclasses import dataclass, field
from datetime import date

from zot_clean import privacy, subjects as f, plans
from zot_clean.apply import stale_copy
from zot_clean.audit import year, write_toml, type_name, norm
from zot_clean.config import Config
from zot_clean.duplicates import _toml
from zot_clean.lang import L, plural
from zot_clean.api import Client
from zot_clean.reader import VALID_KEY, Library, Item
from zot_clean.plans import Group, Operation, Plan

FILE = 'rangement.toml'
MOVE, ADD, TRASH = 'déplacer', 'ajouter', 'corbeille'
ACTIONS = {norm(a): a for a in (MOVE, ADD, TRASH)}
ACCEPT, REJECT = 'accepter', 'refuser'
AGENT, TAG, INSTRUCTION = 'agent', 'tag', 'consigne'
ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'
BUNDLE = 50

def header() -> str:
    return L(en="""\
# Item-by-item filing decisions, read by `zc subjects plan` and `zc inbox plan`.
# This file can be read and edited by hand or with the agent. `zc subjects pending` adds to it the proposals drawn
# from the tags linked to a theme, without touching the existing entries.
#
# One [[fiche]] table per decision, usually a single one per item (a second one to "ajouter" another place).
# cle      : key of the item, given by the reports (`zc subjects pending`, `zc inbox prepare`).
# action   : "déplacer" (to `cible`, leaving `depuis`), "ajouter" (into `cible`, leaving nothing),
#            "corbeille" (the item goes to the Zotero trash).
# cible    : path in the outline, without the subjects root ("Philosophy/Philosophy of science").
# depuis   : key of the collection left, the one the report gives for the bundle. Empty, the item leaves the themes
#            of the subjects that contain the target. For an item in no collection, `depuis` stays empty, and
#            "déplacer" or "ajouter" come to the same. An item of a project gets "ajouter" and stays there.
# source   : "agent", "tag" or "consigne" (request from the user).
# decision : "" (proposed), "accepter" or "refuser". Only accepted entries enter the plan.
# note     : free, one sentence that justifies the proposal.
#
# Example, to copy without the hash signs:
# [[fiche]]
# cle = "ABCD2345"
# action = "déplacer"
# cible = "Psychology/Perception"
# depuis = "WXYZ6789"
# source = "agent"
# decision = ""
# note = "Colour psychophysics, in the Includes of Perception."
""", fr="""\
# Décisions de rangement fiche par fiche, lues par `zc subjects plan` et `zc inbox plan`.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc subjects pending` y ajoute les propositions
# tirées des tags reliés à un thème, sans toucher aux entrées existantes.
#
# Une table [[fiche]] par décision, une seule par fiche en général (une seconde pour « ajouter » une autre place).
# cle      : clé de la fiche, donnée par les rapports (`zc subjects pending`, `zc inbox prepare`).
# action   : "déplacer" (vers `cible`, en quittant `depuis`), "ajouter" (dans `cible`, sans rien quitter),
#            "corbeille" (la fiche va à la corbeille de Zotero).
# cible    : chemin du plan, sans la racine du fonds (« Philosophie/Philosophie des sciences »).
# depuis   : clé de la collection quittée, celle que le rapport donne pour le paquet. Vide, la fiche quitte les
#            thèmes du fonds qui contiennent la cible. Pour une fiche hors de toute collection, `depuis` reste vide,
#            et « déplacer » ou « ajouter » reviennent au même. Une fiche d'un projet reçoit « ajouter » et y reste.
# source   : "agent", "tag" ou "consigne" (demande de l'utilisateur).
# decision : "" (proposé), "accepter" ou "refuser". Seules les entrées acceptées entrent dans le plan.
# note     : libre, une phrase qui justifie la proposition.
#
# Exemple, à recopier sans les dièses :
# [[fiche]]
# cle = "ABCD2345"
# action = "déplacer"
# cible = "Psychologie/Perception"
# depuis = "WXYZ6789"
# source = "agent"
# decision = ""
# note = "Psychophysique des couleurs, dans les « Inclut » de Perception."
""")



# --- Tracking file -------------------------------------------------------------

@dataclass
class Entry:
    key: str
    action: str
    target: str = ''
    origin: str = ''
    source: str = AGENT
    decision: str = ''
    note: str = ''


def load(cfg: Config) -> list[Entry]:
    path = cfg.tracking / FILE
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start again from scratch.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    res = []
    for d in raw.get('fiche', []):
        action = ACTIONS.get(norm(d.get('action', '')))
        if not action:
            raise SystemExit(L(en=f'{path}: unknown action "{d.get("action")}" for {d.get("cle")}. '
                                  f'Possible actions: {", ".join(ACTIONS.values())}.',
                               fr=f'{path} : action inconnue « {d.get("action")} » pour {d.get("cle")}. '
                                  f'Actions possibles : {", ".join(ACTIONS.values())}.'))
        decision = d.get('decision', '')
        if decision not in ('', ACCEPT, REJECT):
            raise SystemExit(L(en=f'{path}: unknown decision "{decision}" for {d.get("cle")}.',
                               fr=f'{path} : décision inconnue « {decision} » pour {d.get("cle")}.'))
        if action != TRASH and not d.get('cible'):
            raise SystemExit(L(en=f'{path}: {d.get("cle")} ({action}) has no target.',
                               fr=f'{path} : {d.get("cle")} ({action}) sans cible.'))
        res.append(Entry(d['cle'], action, d.get('cible', ''), d.get('depuis', ''), d.get('source', AGENT),
                          decision, d.get('note', '')))
    return res


def write(cfg: Config, entries: list[Entry], b: Library, excluded_items: set[int]) -> None:
    by_key = b.by_key()
    lines = [header()]
    for e in entries:
        item = by_key.get(e.key)
        lines.append('[[fiche]]')
        if item and item.id not in excluded_items:
            lines.append(f'# {_line(item)} · ' + ', '.join(sorted(b.path(c) for c in item.collections)))
        lines += [f'cle = {_toml(e.key)}', f'action = {_toml(e.action)}', f'cible = {_toml(e.target)}',
                   f'depuis = {_toml(e.origin)}', f'source = {_toml(e.source)}', f'decision = {_toml(e.decision)}',
                   f'note = {_toml(e.note)}', '']
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    write_toml(cfg.tracking / FILE, lines)


def create_if_missing(cfg: Config) -> bool:
    """Writes the file, with only its header and its example, if it does not exist yet. Returns True if created."""
    if (cfg.tracking / FILE).is_file():
        return False
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    (cfg.tracking / FILE).write_text(header(), encoding='utf-8')
    return True


def _line(e: Item) -> str:
    author = e.author or '?'
    return (f'{author}, {year(e) or L(en="n.d.", fr="s. d.")}, '
            f'{e.title[:100] or L(en="(untitled)", fr="(sans titre)")}')


# --- Target state --------------------------------------------------------------------

@dataclass
class TargetCollection:
    key: str
    name: str
    parent: str | None  # None at the root
    create: bool = False
    category: str = 'fonds'  # subjects, project, archives, intermediate, root (stored French values)
    order: tuple = ()


@dataclass
class Target:
    subjects_root: str = ''
    nodes: dict[str, str] = field(default_factory=dict)  # plan path -> key
    collections: dict[str, TargetCollection] = field(default_factory=dict)  # key -> target state, for those that change
    trash_collections: list[str] = field(default_factory=list)
    merges: dict[str, str] = field(default_factory=dict)  # merged key -> kept key
    items: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)  # key -> (removed, added)
    trash_items: list[str] = field(default_factory=list)
    roots: dict[str, str] = field(default_factory=dict)  # key -> new name
    problems: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)  # items without a place in the subject tree after filing
    distributed: dict[str, int] = field(default_factory=dict)  # distributed, examined collection -> items left (D167)
    left_out: list[str] = field(default_factory=list)  # without a place, left outside the subject tree by decision (D176)


class _State:
    """Current collections of the local copy, by key."""

    def __init__(self, b: Library):
        self.b = b
        self.key = {cid: c.key for cid, c in b.collections.items()}
        self.name = {c.key: c.name for c in b.collections.values()}
        self.parent = {c.key: (self.key[c.parent] if c.parent else None) for c in b.collections.values()}
        self.children: dict[str | None, list[str]] = {}
        for k, p in self.parent.items():
            self.children.setdefault(p, []).append(k)
        self.taken_keys = set(self.name) | {e.key for e in b.all_items.values()}

    def root(self, name: str) -> str | None:
        return next((k for k in self.children.get(None, []) if self.name[k] == name), None)

    def child(self, parent: str | None, name: str) -> str | None:
        return next((k for k in self.children.get(parent, []) if self.name[k] == name), None)

    def path(self, k: str) -> str:
        p = self.parent[k]
        return (self.path(p) + '/' if p else '') + self.name[k]

    def under(self, k: str, root: str) -> bool:
        while k is not None:
            if k == root:
                return True
            k = self.parent.get(k)
        return False

    def new_key(self) -> str:
        while True:
            k = ''.join(secrets.choice(ALPHABET) for _ in range(8))
            if k not in self.taken_keys and VALID_KEY.match(k):
                self.taken_keys.add(k)
                return k


def compute_target(b: Library, cfg: Config, plan: f.Outline, tracking: f.Tracking, entries: list[Entry],
          with_roots: bool = False, reviewed: dict[str, set[str]] | None = None,
          left_out: set[str] = frozenset()) -> Target:
    m = cfg.method
    e = _State(b)
    v = Target()
    counts: dict[str, int] = {}
    items_of: dict[str, set[str]] = {}
    for el in b.all_items.values():
        for cid in el.collections:
            counts[e.key[cid]] = counts.get(e.key[cid], 0) + 1
            items_of.setdefault(e.key[cid], set()).add(el.key)
    old_ones = {a.key: a for a in tracking.collections if a.key in e.name}

    # Root of the subject tree.
    F = e.root(m.subjects)
    if F is None:
        F = e.new_key()
        v.collections[F] = TargetCollection(F, m.subjects, None, create=True, category='racine', order=(0, m.subjects))
    v.subjects_root = F

    def relative(k: str) -> str | None:
        return e.path(k).split('/', 1)[1] if F in e.name and e.under(k, F) and k != F else None

    # 1. Plan paths embodied by the old collections destined for this theme.
    destined: dict[str, list[str]] = {}
    for a in old_ones.values():
        if a.action == f.THEME and a.target in plan.nodes:
            destined.setdefault(a.target, []).append(a.key)
    for path, keys in destined.items():
        keeper = sorted(keys, key=lambda k: (relative(k) != path, -counts.get(k, 0), k))[0]
        v.nodes[path] = keeper
        for k in keys:
            if k != keeper:
                v.merges[k] = keeper
    # A collection to distribute that already sits at a plan path embodies it (its items stay there, D115).
    for a in old_ones.values():
        if a.action == f.DISTRIBUTE and (r := relative(a.key)) in plan.nodes and r not in v.nodes:
            v.nodes[r] = a.key
    # 2. Paths embodied by a collection already in place (created by a previous pass), otherwise created.
    sent_elsewhere = {k for k, a in old_ones.items() if a.action not in (f.OUTSIDE_OUTLINE, '')} - set(v.nodes.values())
    taken = set(v.nodes.values())
    for path, nd in plan.nodes.items():
        if path in v.nodes:
            continue
        outline_parent = path.rpartition('/')[0]
        parent = v.nodes.get(outline_parent) if outline_parent else F
        existing = e.child(parent, path.rpartition('/')[2]) if parent in e.name else None
        if existing and existing not in sent_elsewhere and existing not in taken:
            v.nodes[path] = existing
            taken.add(existing)
        else:
            v.nodes[path] = e.new_key()
    v.nodes = {path: v.nodes[path] for path in plan.nodes}  # tree order (D120)
    outline_order = {path: i for i, path in enumerate(plan.nodes)}
    for path, k in v.nodes.items():
        outline_parent = path.rpartition('/')[0]
        target_coll = TargetCollection(k, path.rpartition('/')[2], v.nodes[outline_parent] if outline_parent else F,
                          create=k not in e.name, order=(1, outline_order[path]))
        if target_coll.create or e.name[k] != target_coll.name or e.parent[k] != target_coll.parent:
            v.collections[k] = target_coll

    # 3. Projects and archives, moved under their root (parents before children).
    intended_paths: dict[str, str] = {}  # full target path -> key, for the intermediate parents

    def root_of(name: str) -> str:
        k = e.root(name)
        if k is None:
            k = intended_paths.get(name) or e.new_key()
            if k not in v.collections:
                v.collections[k] = TargetCollection(k, name, None, create=True, category='racine', order=(0, name))
            intended_paths[name] = k
        return k

    def parent_of(path: str, category: str) -> str:
        head, _, rest = path.partition('/')
        k = root_of(head)
        seen = head
        for name in rest.split('/')[:-1] if rest else []:
            seen += '/' + name
            if seen in intended_paths:
                k = intended_paths[seen]
                continue
            child = e.child(k, name) if k in e.name else None
            if child is None:
                child = e.new_key()
                v.collections[child] = TargetCollection(child, name, k, create=True, category='intermédiaire',
                                                  order=(2, seen))
            intended_paths[seen] = k = child
        return k

    archives = e.root(m.archives) if m.archives else None
    for a in sorted(old_ones.values(), key=lambda a: e.path(a.key).count('/')):
        if a.action not in (f.PROJECT, f.ARCHIVES) or f.stays_in_place(a, m):
            continue
        if a.action == f.ARCHIVES and not a.target and archives and e.under(a.key, archives):
            # Without a target, an archive goes to its former path. Already under the archives (previous pass), it is
            # in place: its current path is no longer a target, otherwise « Archives/Archives/… » (pilot rehearsal).
            continue
        if a.action == f.PROJECT:
            if not m.projects:
                v.problems.append(L(en=f'{a.path} goes to the projects, with no projects root declared.',
                                    fr=f'{a.path} va dans les projets, sans racine de projets déclarée.'))
                continue
            target = a.target or f'{m.projects[0]}/{e.name[a.key]}'
        else:
            target = f'{m.archives}/{a.target or e.path(a.key)}'
        old_parent = old_ones.get(e.parent[a.key] or '')
        if not a.target and old_parent and old_parent.action == a.action and not old_parent.target:
            parent = e.parent[a.key]  # follows its mother, itself moved with its name (D118)
        else:
            parent = parent_of(target, a.action)
        intended_paths.setdefault(target, a.key)
        target_coll = TargetCollection(a.key, target.rpartition('/')[2], parent, category=a.action,
                          order=(3 if a.action == f.PROJECT else 4, target))
        if e.name[a.key] != target_coll.name or e.parent[a.key] != target_coll.parent:
            v.collections[a.key] = target_coll

    # 4. Items: merges, then accepted decisions of rangement.toml.
    def change(key: str, drop: set[str], add: set[str]):
        r, a = v.items.setdefault(key, (set(), set()))
        a -= drop
        r |= drop
        a |= add
        r -= add

    for k, keeper in v.merges.items():
        for key in items_of.get(k, ()):
            change(key, {k}, {keeper})
    all_items = b.by_key()
    ancestors = {path: {v.nodes[path[:i]] for i in [m_.start() for m_ in re.finditer('/', path)]}
                for path in plan.nodes}
    # Chained decisions on the same item (A to B, then B to C): the item goes straight to C. Otherwise B, which it
    # does not contain yet or any more, would be added to it by the first (found on the real library).
    next_nodes = {(ent.key, v.merges.get(ent.origin, ent.origin)): v.nodes[ent.target] for ent in entries
              if ent.decision == ACCEPT and ent.action == MOVE and ent.origin and ent.target in v.nodes}
    for ent in entries:
        if ent.decision != ACCEPT:
            continue
        if ent.key not in all_items:
            v.problems.append(L(en=f'rangement.toml: the item {ent.key} no longer exists, entry ignored.',
                                fr=f'rangement.toml : la fiche {ent.key} n\'existe plus, entrée ignorée.'))
            continue
        if ent.action == TRASH:
            v.trash_items.append(ent.key)
            continue
        if ent.target not in v.nodes:
            v.problems.append(L(en=f'rangement.toml: {ent.key} aims at "{ent.target}", which is not in plan.md, '
                                   'entry ignored.',
                                fr=f'rangement.toml : {ent.key} vise « {ent.target} », qui n\'est pas dans plan.md, '
                                   'entrée ignorée.'))
            continue
        target, visited = v.nodes[ent.target], set()
        while (follow_up := next_nodes.get((ent.key, target))) and target not in visited:
            visited.add(target)
            target = follow_up
        if ent.action == ADD:
            change(ent.key, set(), {target})
            continue
        current = {e.key[c] for c in all_items[ent.key].collections}
        if ent.origin:
            to_leave = {v.merges.get(ent.origin, ent.origin)}
        else:
            to_leave = ancestors[ent.target] | ({k for k in current if v.merges.get(k) in ancestors[ent.target]})
        change(ent.key, to_leave & (current | set(v.merges.values())), {target})

    # 5. Collections to trash: merged, dissolved, or to distribute outside the plan and emptied. A collection to
    #    distribute is emptied when only items judged and left there remain in it (D124, D167). The items keep their
    #    other collections, those with no other one in the subject tree are presented as without a place.
    reviewed = reviewed or {}
    staying = {}  # collection -> items that stay in it after filing
    for k in e.name:
        contained = {c for c in items_of.get(k, ()) if k not in v.items.get(c, (set(), set()))[0]}
        contained |= {c for c, (_, a) in v.items.items() if k in a}
        staying[k] = contained
    target_parent = {k: (v.collections[k].parent if k in v.collections else e.parent[k]) for k in e.name}
    distributed = {k for k, a in old_ones.items() if a.action == f.DISTRIBUTE and k not in v.nodes.values() and (
        not staying[k] or (k in reviewed and staying[k] <= reviewed[k]))}
    dropped = {k for k, a in old_ones.items() if k in v.merges or a.action == f.DISSOLVE or k in distributed}
    # A collection that keeps a subcollection stays. A subcollection trashed in the same pass does not hold it
    # back (distributed with its subcollections, pilot rehearsal).
    while kept := {k for k in dropped if any(target_parent[x] == k and x not in dropped for x in e.name)}:
        dropped -= kept
    for k, a in old_ones.items():
        if k in v.merges or a.action == f.DISSOLVE or k in distributed:
            if k not in dropped:
                v.problems.append(L(en=f'{a.path} keeps subcollections, it is not sent to the trash.',
                                    fr=f'{a.path} garde des sous-collections, elle n\'est pas mise à la corbeille.'))
                continue
            v.trash_collections.append(k)
            if k in distributed and staying[k]:
                v.distributed[k] = len(staying[k])

    # 6. Roots renamed on request (D112).
    if with_roots:
        for old, new in tracking.roots.items():
            k = e.root(old)
            if k is None or old == new:
                continue
            if e.root(new) is not None:
                v.problems.append(L(en=f'The root "{old}" cannot become "{new}", which already exists.',
                                    fr=f'La racine « {old} » ne peut pas devenir « {new} », qui existe déjà.'))
                continue
            v.roots[k] = new

    # 7. Items that will have no place in the subject tree (D20), outside the Inbox and outside the filter.
    excluded_items = privacy.excluded_items(b, cfg)
    target_subjects = set(v.nodes.values()) | {F}
    inbox = e.root(m.inbox) if m.inbox else None
    trash = set(v.trash_collections)
    for el in b.items:
        if el.id in excluded_items or el.key in v.trash_items:
            continue
        removed_cols, added_keys = v.items.get(el.key, (set(), set()))
        after = ({e.key[c] for c in el.collections} - removed_cols | added_keys) - trash
        if inbox and any(e.under(k, inbox) for k in after):
            continue
        if not after & target_subjects and not any(e.under(k, F) for k in after if k in e.name and F in e.name):
            # An item left outside the subject tree by decision (D176) no longer is if the plan changes its collections.
            is_left_out = el.key in left_out and not any(v.items.get(el.key, (set(), set()))) \
                and not {e.key[c] for c in el.collections} & trash
            (v.left_out if is_left_out else v.unplaced).append(el.key)
    return v


# --- Plan ---------------------------------------------------------------------------

def make_plan(b: Library, cfg: Config, client: Client, with_roots: bool = False,
              show=None) -> tuple[Plan, str]:
    up_to_date, reasons = f.validation_up_to_date(cfg)
    if not up_to_date:
        listing = '\n  '.join(reasons)
        raise SystemExit(L(en=f'The subjects outline is not validated in its current state:\n  {listing}\n'
                              'Run `zc subjects validate` again, then `--save` once agreed.',
                           fr=f"Le plan du fonds n'est pas validé dans son état actuel :\n  {listing}\n"
                              'Relancer `zc subjects validate`, puis `--save` après accord.'))
    concordance(b, cfg)
    # The real state is read from the local copy (D119). If Zotero has not yet received the latest changes (those
    # of a previous pass, for example), the collections already created are not there and would be created again.
    if (server := client.server_version()) > b.version:
        raise SystemExit(stale_copy(b.version, server))
    outline = f.read_outline((cfg.workspace / f.OUTLINE).read_text(encoding='utf-8'), cfg)
    v = compute_target(b, cfg, outline, f.load_tracking(cfg), load(cfg), with_roots, load_reviewed(cfg),
              load_left_out(b, cfg))
    e = _State(b)
    excluded_items = privacy.excluded_items(b, cfg)
    by_key = b.by_key()

    coll_keys = [k for k in (*v.collections, *v.trash_collections, *v.roots) if k in e.name]
    if show:
        n_collections = plural(len(coll_keys), en='collection', fr='collection')
        n_items = plural(len(v.items) + len(v.trash_items), en='item', fr='fiche')
        show(L(en=f'Target state computed. Reading from zotero.org {n_collections} and {n_items} touched by the '
                  'plan.',
               fr=f'État visé calculé. Lecture sur zotero.org de {n_collections} et {n_items} touchées par le '
                  'plan.'))
    api_coll = client.collections(coll_keys)
    api_items = client.items([*v.items, *v.trash_items])

    groups: dict[tuple, Group] = {}
    titles: dict[tuple, str] = {}

    def group(order: tuple, title: str) -> Group:
        if order not in groups:
            groups[order] = Group('', title, [])
        return groups[order]

    def intended_path(k: str) -> str:
        """Path of a collection once the plan applied, from the root of the library like every path of the report.
        A collection left in place follows its parent: under an old collection moved into the subjects, it is
        shown under the subjects root too (pilot rehearsal, « Psychologie/Perception » beside
        « Fonds/Psychologie »)."""
        c = v.collections.get(k)
        if c:
            return (intended_path(c.parent) + '/' if c.parent else '') + c.name
        if k not in e.name:
            return k
        return (intended_path(e.parent[k]) + '/' if e.parent[k] else '') + e.name[k]

    order_of: dict[str, tuple] = {}
    for k, c in v.collections.items():
        order_of[k] = c.order
    for path, k in v.nodes.items():
        order_of.setdefault(k, (1, list(v.nodes).index(path)))

    for k, c in sorted(v.collections.items(), key=lambda x: x[1].order):
        g = group(c.order, intended_path(k))
        if c.create:
            g.operations.append(Operation(k, {}, {'name': c.name, 'parentCollection': c.parent or False},
                                          nature='création', kind='collections', create=True))
            continue
        d = api_coll.get(k)
        if d is None:
            v.problems.append(L(en=f'The collection {e.path(k)} ({k}) no longer exists in Zotero, left aside.',
                                fr=f'La collection {e.path(k)} ({k}) n\'existe plus dans Zotero, laissée de côté.'))
            continue
        before = {'name': d.get('name', ''), 'parentCollection': d.get('parentCollection') or False}
        after = {'name': c.name, 'parentCollection': c.parent or False}
        changed = {x: after[x] for x in after if before[x] != after[x]}
        if changed:
            g.operations.append(Operation(k, {x: before[x] for x in changed}, changed,
                                          nature='renommage' if 'name' in changed else 'déplacement',
                                          kind='collections'))

    for key, (removed_cols, added_keys) in sorted(v.items.items()):
        d = api_items.get(key)
        if d is None:
            v.problems.append(L(en=f'The item {key} no longer exists in Zotero, left aside.',
                                fr=f'La fiche {key} n\'existe plus dans Zotero, laissée de côté.'))
            continue
        before = list(d.get('collections') or [])
        after = [k for k in before if k not in removed_cols] + [k for k in sorted(added_keys) if k not in before]
        if sorted(after) == sorted(before):
            continue
        entries = [k for k in after if k not in before]
        # Group of the first collection the item enters, unless it also enters a collection created by a later
        # group: it then goes in the group of that creation, the last one, so as never to be written (in the trial
        # or in an earlier bundle) to a collection that does not exist yet.
        ordered_keys = sorted(entries, key=lambda k: _sort_key(order_of.get(k, (5, k))))
        newly_created = [k for k in ordered_keys if k in v.collections and v.collections[k].create]
        if newly_created and _sort_key(order_of[newly_created[-1]]) > _sort_key(order_of.get(ordered_keys[0], (5, ordered_keys[0]))):
            ordered_keys.insert(0, newly_created[-1])
        order = order_of.get(ordered_keys[0], (5, ordered_keys[0])) if ordered_keys else (5, 'fiches')
        g = group(order, intended_path(ordered_keys[0]) if ordered_keys
                  else L(en='items removed from collections', fr='fiches retirées de collections'))
        g.operations.append(Operation(key, {'collections': before}, {'collections': after}, rank=1,
                                      nature='rangement'))

    for k in v.trash_collections:
        if k in api_coll or k in e.name:
            title = L(en=f'trash: {e.path(k)}', fr=f'corbeille : {e.path(k)}')
            if k in v.distributed:
                title += L(en=' (distributed and reviewed)', fr=' (répartie et examinée)')
            g = group((6, e.path(k)), title)
            g.operations.append(Operation(k, {'deleted': False}, {'deleted': True}, nature='corbeille',
                                          kind='collections'))
    children = b.children()
    for i in range(0, len(v.trash_items), BUNDLE):
        g = group((7, i), L(en='items to the trash', fr='fiches à la corbeille'))
        for key in v.trash_items[i:i + BUNDLE]:
            if key in api_items and not api_items[key].get('deleted'):
                g.operations.append(Operation(key, {'deleted': False}, {'deleted': True}, nature='corbeille',
                                              children=children.get(key, [])))
    for k, name in v.roots.items():
        d = api_coll.get(k)
        if d:
            g = group((8, name), L(en=f'root: {e.name[k]} → {name}', fr=f'racine : {e.name[k]} → {name}'))
            g.operations.append(Operation(k, {'name': d['name']}, {'name': name}, nature='racine',
                                          kind='collections'))

    listing = []
    for order in sorted(groups, key=_sort_key):
        g = groups[order]
        if g.operations:
            g.id = str(len(listing) + 1)
            listing.append(g)
    plan = Plan('fonds', client.user, listing,
                description=L(en=f'Filing of the subjects, {len(listing)} group(s).',
                              fr=f'Rangement du fonds, {len(listing)} groupe(s).'))
    return plan, report(plan, v, b, e, excluded_items, by_key, intended_path)


def _sort_key(order: tuple):
    return tuple((0, x) if isinstance(x, int) else (1, str(x)) for x in order)


def concordance(b: Library, cfg: Config) -> None:
    """The roots of config.toml must exist, otherwise a rename was not carried over there (D112)."""
    m = cfg.method
    present_keys = {c.name for c in b.collections.values() if c.parent is None}
    missing = [n for n in (m.subjects, *m.projects, m.archives) if n and n not in present_keys]
    if missing:
        tracking = f.load_tracking(cfg)
        renamed_roots = {a: n for a, n in tracking.roots.items() if a in missing and n in present_keys}
        if renamed_roots:
            names = ', '.join(L(en=f'“{a}” → “{n}”', fr=f'« {a} » → « {n} »') for a, n in renamed_roots.items())
            raise SystemExit(L(en=f'Roots renamed in Zotero, to carry over into config.toml ([methode]) and into the '
                                  f'title of plan.md: {names}.',
                               fr=f'Racines renommées dans Zotero, à reporter dans config.toml ([methode]) et dans '
                                  f'le titre de plan.md : {names}.'))


def _describe_collection(op: Operation, e: _State, intended_path) -> str:
    def place(k):
        return intended_path(k) if k else L(en='the root', fr='la racine')
    if op.create:
        return L(en=f'creation of "{op.after["name"]}" under {place(op.after["parentCollection"])}',
                 fr=f'création de « {op.after["name"]} » sous {place(op.after["parentCollection"])}')
    if op.nature == 'corbeille':
        return L(en=f'{e.path(op.key)} to the trash', fr=f'{e.path(op.key)} à la corbeille')
    chunks = []
    if 'name' in op.after:
        chunks.append(L(en=f'"{op.before.get("name", "")}" renamed "{op.after["name"]}"',
                        fr=f'« {op.before.get("name", "")} » renommée « {op.after["name"]} »'))
    if 'parentCollection' in op.after:
        # Where it is now (current path of its parent), where it goes (path of its parent once the plan applied).
        before = op.before.get('parentCollection')
        origin = e.path(before) if before in e.name else place(before)
        chunks.append(L(en=f'moved from {origin} to {place(op.after["parentCollection"])}',
                        fr=f'déplacée de {origin} vers {place(op.after["parentCollection"])}'))
    return ', '.join(chunks)


def report(plan: Plan, v: Target, b: Library, e: _State, excluded_items: set[int], by_key: dict, intended_path,
            day: date | None = None) -> str:
    day = day or date.today()
    ops = [op for g in plan.groups for op in g.operations]
    account = {n: sum(1 for op in ops if op.nature == n) for n in
              ('création', 'renommage', 'déplacement', 'rangement', 'corbeille', 'racine')}
    lines = [L(en=f'# Filing plan of {day:%d/%m/%Y}', fr=f'# Plan de rangement du {day:%d/%m/%Y}'), '',
             L(en=f'{len(plan.groups)} group(s), {len(ops)} operation(s). Collections created {account["création"]}, '
                  f'renamed {account["renommage"]}, moved {account["déplacement"]}. Items filed '
                  f'{account["rangement"]}. Sent to the trash {account["corbeille"]}. Roots renamed '
                  f'{account["racine"]}.',
               fr=f'{len(plan.groups)} groupe(s), {len(ops)} opération(s). Collections créées {account["création"]}, '
                  f'renommées {account["renommage"]}, déplacées {account["déplacement"]}. Fiches rangées '
                  f'{account["rangement"]}. Mises à la corbeille {account["corbeille"]}. Racines renommées '
                  f'{account["racine"]}.'), '',
             L(en='A group matches a collection of the subjects, with the items that enter it. The trial applies the '
                  'first groups, to check with `zc show`.',
               fr="Un groupe correspond à une collection du fonds, avec les fiches qui y entrent. L'essai applique "
                  'les premiers groupes, à vérifier avec `zc show`.')]
    if v.subjects_root:
        root = intended_path(v.subjects_root)
        lines[-1] += L(en=f' Paths start at the root of the library, as in Zotero, the themes being under “{root}”, '
                          f'which plan.md and suivi/rangement.toml leave out. A collection moved or created is shown '
                          f'at its place once the plan applied.',
                       fr=f' Les chemins partent de la racine de la bibliothèque, comme dans Zotero, les thèmes étant '
                          f'sous « {root} », que plan.md et suivi/rangement.toml omettent. Une collection déplacée ou '
                          f'créée figure à sa place une fois le plan appliqué.')
    if v.merges:
        lines += ['', L(en='## Merges', fr='## Fusions'), '']
        lines += [L(en=f'- {e.path(k)} into {intended_path(g)}', fr=f'- {e.path(k)} dans {intended_path(g)}')
                  for k, g in v.merges.items()]
    if v.distributed:
        lines += ['', L(en='## Distributed collections', fr='## Collections réparties'), '',
                  L(en='Entirely judged (`zc subjects pending --reviewed`), they go to the trash. The items left in '
                       'place keep their other collections there, and those that have none in the subjects are '
                       'counted below among the items with no place.',
                    fr='Entièrement jugées (`zc subjects pending --reviewed`), elles vont à la corbeille. Les fiches '
                       "laissées en place y gardent leurs autres collections, et celles qui n'en ont aucune dans le "
                       'fonds sont comptées ci-dessous parmi les fiches sans place.'), '']
        for k, n in v.distributed.items():
            left = plural(n, en='item left', fr='fiche laissée', en_plural='items left')
            lines.append(f'- {e.path(k)}, {left}')
    if v.problems:
        lines += ['', L(en='## To look at', fr='## À regarder'), '']
        lines += [f'- {p}' for p in v.problems]
    if v.unplaced or v.left_out:
        text = []
        if v.unplaced:
            # What the number covers, since `zc subjects pending` counts differently (pilot bench).
            n = len(v.unplaced)
            count = plural(n, en='item', fr='fiche')
            pending_note = L(en='`zc subjects pending` presents them in bundles, together with the other items of the '
                                'collections to distribute and without those already in `suivi/rangement.toml`, to '
                                'propose a theme for them.',
                             fr='`zc subjects pending` les présente par paquets, avec les autres fiches des '
                                'collections à répartir et sans celles déjà dans `suivi/rangement.toml`, pour leur '
                                'proposer un thème.')
            text.append(L(en=f'{count} will be in no theme of the subjects after this plan, the Inbox aside, even '
                             f'if it stays in a collection to distribute. {pending_note}',
                          fr=f'{count} ne sera dans aucun thème du fonds après ce plan, hors Inbox, même si elle '
                             f'reste dans une collection à répartir. {pending_note}')
                        if n == 1 else
                        L(en=f'{count} will be in no theme of the subjects after this plan, the Inbox aside, those '
                             f'that stay only in a collection to distribute included. {pending_note}',
                          fr=f'{count} ne seront dans aucun thème du fonds après ce plan, hors Inbox, y compris '
                             f'celles qui ne restent que dans une collection à répartir. {pending_note}'))
        if v.left_out:
            n = len(v.left_out)
            count = plural(n, en=('other ' if v.unplaced else '') + 'item left out of the subjects',
                           fr=('autre ' if v.unplaced else '') + 'fiche laissée',
                           en_plural=('other ' if v.unplaced else '') + 'items left out of the subjects')
            text.append(L(en=f'{count} by decision (`zc subjects pending --leave-out`), not presented.',
                          fr=f'{count} hors du fonds par décision (`zc subjects pending --leave-out`), non présentée.')
                        if n == 1 else
                        L(en=f'{count} by decision (`zc subjects pending --leave-out`), not presented.',
                          fr=f'{count} hors du fonds par décision (`zc subjects pending --leave-out`), '
                             'non présentées.'))
        lines += ['', L(en='## Items with no place in the subjects', fr='## Fiches sans place dans le fonds'), '',
                  ' '.join(text)]
    lines += ['', L(en='## Groups', fr='## Groupes')]
    for g in plan.groups:
        lines += ['', f'### {g.id}. {g.title}', '']
        for op in g.operations:
            if op.kind == 'collections':
                lines.append(L(en=f'- collection {op.key}: ', fr=f'- collection {op.key} : ')
                             + _describe_collection(op, e, intended_path))
            else:
                el = by_key.get(op.key)
                who = _line(el) if el and el.id not in excluded_items else privacy.mask()
                if op.nature == 'corbeille':
                    lines.append(L(en=f'- {op.key} · {who}: to the trash', fr=f'- {op.key} · {who} : à la corbeille'))
                else:
                    new_ones = [intended_path(k) for k in op.after['collections'] if k not in op.before['collections']]
                    left = [intended_path(k) for k in op.before['collections'] if k not in op.after['collections']]
                    lines.append(f'- {op.key} · {who}'
                                 + (L(en=f': enters {", ".join(new_ones)}', fr=f' : entre dans {", ".join(new_ones)}')
                                    if new_ones else '')
                                 + (L(en=f', leaves {", ".join(left)}', fr=f', quitte {", ".join(left)}')
                                    if left else ''))
    return '\n'.join(lines) + '\n'


# --- Items to judge ------------------------------------------------------------------

REVIEWED = 'rangement-examinees.json'


def load_reviewed(cfg: Config) -> dict[str, set[str]]:
    """Items left in place in each collection to distribute that has been entirely judged (D124)."""
    try:
        raw = json.loads((cfg.tracking / REVIEWED).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    return {k: set(d['fiches']) for k, d in raw.items()}


def mark_reviewed(b: Library, cfg: Config, keys: list[str]) -> dict[str, int]:
    """Records the items a collection to distribute still contains once judged. `a-ranger` no longer presents
    them, only those that arrive there afterwards (D124). Refuses while a proposal from this collection is pending."""
    tracking = f.load_tracking(cfg)
    to_distribute = {a.key for a in tracking.collections if a.action == f.DISTRIBUTE}
    e = _State(b)
    for k in keys:
        if k not in to_distribute or k not in e.name:
            raise SystemExit(L(en=f'{k} is not a collection to distribute in suivi/fonds.toml.',
                               fr=f'{k} n\'est pas une collection à répartir de suivi/fonds.toml.'))
    content = {k: {el.key for el in b.all_items.values() if el.is_item and any(e.key[c] == k for c in el.collections)}
               for k in keys}
    proposed_keys = {x.key for x in load(cfg) if x.decision == ''}
    waiting = [k for k in keys if content[k] & proposed_keys]
    if waiting:
        names = ', '.join(e.path(k) for k in waiting)
        raise SystemExit(L(en=f'Proposals still pending on items of {names}. Have them judged before marking the '
                              'collection as reviewed.',
                           fr=f'Propositions encore en attente sur des fiches de {names}. Les faire juger avant de '
                              'marquer la collection comme examinée.'))
    try:
        raw = json.loads((cfg.tracking / REVIEWED).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raw = {}
    res = {}
    for k in keys:
        contained = content[k] | set(raw.get(k, {}).get('fiches', []))
        raw[k] = {'chemin': e.path(k), 'date': date.today().isoformat(), 'fiches': sorted(contained)}
        res[e.path(k)] = len(contained)
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    (cfg.tracking / REVIEWED).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding='utf-8')
    return res


LEFT_OUT = 'rangement-laissees.json'


def _collections_of(b: Library, el: Item) -> list[str]:
    key = {cid: c.key for cid, c in b.collections.items()}
    return sorted(key[c] for c in el.collections)


def load_left_out(b: Library, cfg: Config) -> set[str]:
    """Items seen and left outside the subject tree by decision (D176), while their collections are unchanged."""
    try:
        raw = json.loads((cfg.tracking / LEFT_OUT).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return set()
    by_key = b.by_key()
    return {k for k, d in raw.items() if k in by_key and _collections_of(b, by_key[k]) == d['collections']}


def leave_out(b: Library, cfg: Config, keys: list[str]) -> list[str]:
    """Records items without a place in the subject tree as seen and left outside it (D176). `a-ranger`, the Inbox
    triage and the audit no longer present them, as long as they stay in the same collections. Refuses an Inbox
    item, an item that already has its place in the subject tree, and an item with a pending or accepted decision."""
    m = cfg.method
    e = _State(b)
    by_key = b.by_key()
    subjects = e.root(m.subjects) if m.subjects else None
    inbox = e.root(m.inbox) if m.inbox else None
    decided = {x.key for x in load(cfg) if x.decision != REJECT}
    for k in keys:
        el = by_key.get(k)
        if el is None or not el.is_item:
            raise SystemExit(L(en=f'No item with key {k}.', fr=f'Aucune fiche de clé {k}.'))
        inside = [e.key[c] for c in el.collections]
        if inbox and any(e.under(c, inbox) for c in inside):
            raise SystemExit(L(en=f'{k} is in the Inbox. An Inbox item is sorted (`zc inbox prepare`), it is not '
                                  'left out of the subjects.',
                               fr=f'{k} est dans l\'Inbox. Une fiche de l\'Inbox se trie (`zc inbox prepare`), elle '
                                  'ne se laisse pas hors du fonds.'))
        if subjects and any(e.under(c, subjects) for c in inside):
            raise SystemExit(L(en=f'{k} already has its place in the subjects.',
                               fr=f'{k} a déjà sa place dans le fonds.'))
        if k in decided:
            raise SystemExit(L(en=f'{k} has a pending or accepted decision in suivi/{FILE}. Set it to "refuser" '
                                  'before leaving the item out of the subjects.',
                               fr=f'{k} a une décision en attente ou acceptée dans suivi/{FILE}. La passer à '
                                  '« refuser » avant de laisser la fiche hors du fonds.'))
    try:
        raw = json.loads((cfg.tracking / LEFT_OUT).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raw = {}
    for k in keys:
        raw[k] = {'date': date.today().isoformat(), 'collections': _collections_of(b, by_key[k])}
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    (cfg.tracking / LEFT_OUT).write_text(json.dumps(raw, ensure_ascii=False, indent=1, sort_keys=True),
                                      encoding='utf-8')
    return sorted(keys)


@dataclass
class Bundle:
    source: str  # path of the original collection, or « no place in the subjects » (no place in the tree)
    origin: str  # key of the collection left, empty for an item without a place
    candidates: list[str]
    items: list[Item]


def pending(b: Library, cfg: Config) -> tuple[str, list[Bundle], int]:
    """Report of the items to distribute or to place (D121), bundles, and number of proposals added by the tags."""
    outline = f.read_outline((cfg.workspace / f.OUTLINE).read_text(encoding='utf-8'), cfg)
    tracking = f.load_tracking(cfg)
    entries = load(cfg)
    reviewed = load_reviewed(cfg)
    v = compute_target(b, cfg, outline, tracking, entries, reviewed=reviewed, left_out=load_left_out(b, cfg))
    excluded_items = privacy.excluded_items(b, cfg)
    e = _State(b)
    decided = {x.key for x in entries}
    by_key = b.by_key()

    def to_judge(el: Item) -> bool:
        return el.is_item and el.id not in excluded_items and el.key not in decided and el.key not in v.trash_items

    # An item appears in a single bundle, the first that applies: that of its first collection to distribute in the
    # order of suivi/fonds.toml, otherwise the bundle of the items without a place (pilot bench, an item of two
    # catch-alls was presented twice and got two proposals from its tags).
    bundles: list[Bundle] = []
    shown: set[str] = set()
    for a in tracking.collections:
        if a.action != f.DISTRIBUTE or a.key not in e.name:
            continue
        items = sorted((el for el in b.all_items.values() if to_judge(el) and el.key not in shown
                         and any(e.key[c] == a.key for c in el.collections)
                         and a.key not in v.items.get(el.key, (set(), set()))[0]
                         and el.key not in reviewed.get(a.key, ())), key=lambda el: norm(el.title))
        shown |= {el.key for el in items}
        for i in range(0, len(items), BUNDLE):
            bundles.append(Bundle(e.path(a.key), a.key, a.candidates, items[i:i + BUNDLE]))
    without = sorted((by_key[c] for c in v.unplaced if to_judge(by_key[c]) and c not in shown),
                  key=lambda el: norm(el.title))
    for i in range(0, len(without), BUNDLE):
        bundles.append(Bundle(L(en='no place in the subjects', fr='sans place dans le fonds'), '',
                              outline.filing_targets(), without[i:i + BUNDLE]))

    # Proposals drawn from the tags linked to a theme (D100, D116), for the items to judge only. None for an item
    # already filed, once the plan applied, in one of the themes its tags designate or in one of their sub-themes.
    path_of = {k: path for path, k in v.nodes.items()}

    def filed_in(el: Item) -> set[str]:
        removed, added = v.items.get(el.key, (set(), set()))
        return {path_of[k] for k in ({e.key[c] for c in el.collections} - removed) | added if k in path_of}

    additions = []
    for p in bundles:
        for el in p.items:
            linked = [(n, tracking.tags[n]) for n, _ in el.tags if tracking.tags.get(n) in outline.nodes]
            if not linked:
                continue
            paths = filed_in(el)
            if any(x == t or x.startswith(t + '/') for _, t in linked for x in paths):
                continue
            name, target = linked[0]
            additions.append(Entry(el.key, MOVE, target, p.origin, TAG, '', f'tag « {name} »'))
    if additions:
        write(cfg, entries + additions, b, excluded_items)
    create_if_missing(cfg)
    return _pending_report(bundles, outline, additions, e, len(v.left_out)), bundles, len(additions)


def _pending_report(bundles: list[Bundle], outline: f.Outline, additions: list[Entry], e: _State, left_out: int = 0,
                      day: date | None = None) -> str:
    day = day or date.today()
    total = sum(len(p.items) for p in bundles)
    # What the number covers, since the filing plan counts only the items in no theme (pilot bench).
    distributed = sum(len(p.items) for p in bundles if p.origin)
    n_total = plural(total, en='item', fr='fiche')
    n_bundles = plural(len(bundles), en='bundle', fr='paquet')
    n_distributed = plural(distributed, en='item', fr='fiche')
    n_without = plural(total - distributed, en='item', fr='fiche')
    lines = [L(en=f'# Items to file, {day:%d/%m/%Y}', fr=f'# Fiches à ranger, {day:%d/%m/%Y}'), '',
             L(en=f'{n_total} in {n_bundles} of {BUNDLE} at most, that is {n_distributed} of the collections to '
                  f'distribute, whether or not they already have a place in the subjects, and {n_without} in no '
                  'theme of the subjects, without those already decided in `suivi/rangement.toml` or those excluded '
                  'by the privacy filter. For each item, propose a target among the candidates, or leave it in '
                  'place. Write the proposals in `suivi/rangement.toml` (one `[[fiche]]` table per item, as in the '
                  'example of the header, with `depuis` = the key given for the bundle), then have them approved '
                  'bundle by bundle. An item appears in a single bundle only, that of its first collection to '
                  'distribute in the order of `suivi/fonds.toml`, its other collections being given on its line.',
               fr=f'{n_total} en {n_bundles} de {BUNDLE} au plus, à savoir {n_distributed} des collections à '
                  f'répartir, qu\'elles aient déjà ou non une place dans le fonds, et {n_without} dans aucun thème '
                  'du fonds, sans celles déjà décidées dans `suivi/rangement.toml` ni celles exclues par le filtre '
                  'de confidentialité. Pour chaque fiche, proposer une cible parmi les candidats, ou la laisser en '
                  'place. Écrire les propositions dans `suivi/rangement.toml` (une table `[[fiche]]` par fiche, '
                  "comme dans l'exemple de l'en-tête, avec `depuis` = la clé donnée pour le paquet), puis les faire "
                  "approuver paquet par paquet. Une fiche n'apparaît que dans un seul paquet, celui de sa première "
                  'collection à répartir dans l\'ordre de `suivi/fonds.toml`, ses autres collections étant données '
                  'sur sa ligne.')]
    if left_out:
        lines += ['', L(en='Items left out of the subjects by decision (`zc subjects pending --leave-out`), not '
                           f'presented as long as their collections do not change, {left_out}.',
                        fr='Fiches laissées hors du fonds par décision (`zc subjects pending --leave-out`), non '
                           f'présentées tant que leurs collections ne changent pas, {left_out}.')]
    if additions:
        lines += ['', L(en=f'{len(additions)} proposal(s) drawn from the tags linked to a theme were added to '
                           '`suivi/rangement.toml`, to approve like the others (items marked "tag" below).',
                        fr=f'{len(additions)} proposition(s) tirée(s) des tags reliés à un thème ont été ajoutées à '
                           '`suivi/rangement.toml`, à approuver comme les autres (fiches marquées « tag » '
                           'ci-dessous).')]
    proposed_keys = {x.key: x.target for x in additions}
    for n, p in enumerate(bundles, 1):
        lines += ['', L(en=f'## Bundle {n} · {p.source}', fr=f'## Paquet {n} · {p.source}')
                  + (f' (depuis = "{p.origin}")' if p.origin else ' (depuis = "")'), '']
        if not p.origin:
            lines += [L(en='`depuis` stays empty. For an item in no collection, "déplacer" or "ajouter" come to the '
                           'same. An item filed outside the subjects (project, archives) gets "ajouter" and stays '
                           'there.',
                        fr='`depuis` reste vide. Pour une fiche hors de toute collection, « déplacer » ou « ajouter » '
                           'reviennent au même. Une fiche rangée hors du fonds (projet, archives) reçoit « ajouter » '
                           'et y reste.'), '']
        lines += [L(en='Candidates:', fr='Candidats :'), '']
        for c in p.candidates:
            nd = outline.nodes.get(c)
            if nd:
                line = f'- **{c}**. {nd.definition}'
                line += L(en=f' Includes: {nd.includes}', fr=f' Inclut : {nd.includes}') if nd.includes else ''
                line += L(en=f' Excludes: {nd.excludes}', fr=f' Exclut : {nd.excludes}') if nd.excludes else ''
                lines.append(line)
        lines += ['', L(en='Items:', fr='Fiches :'), '']
        for el in p.items:
            tags = ', '.join(n for n, t in el.tags if t == 0)
            others = ', '.join(sorted(e.path(e.key[c]) for c in el.collections if e.key[c] != p.origin))
            lines.append(f'- {el.key} · {_line(el)} · {type_name(el.type)}'
                         + (L(en=f' · tags {tags}', fr=f' · tags {tags}') if tags else '')
                         + (L(en=f' · also in {others}', fr=f' · aussi dans {others}') if others
                            else L(en=' · in no collection', fr=' · hors de toute collection') if not p.origin else '')
                         + (L(en=f' · tag → {proposed_keys[el.key]}', fr=f' · tag → {proposed_keys[el.key]}')
                            if el.key in proposed_keys else ''))
    return '\n'.join(lines) + '\n'


def abstract(b: Library, cfg: Config, key: str) -> str:
    """Abstract of a doubtful item (D121), never for an item excluded by the filter."""
    el = b.by_key().get(key)
    if el is None:
        raise SystemExit(L(en=f'No item with key {key}.', fr=f'Aucune fiche de clé {key}.'))
    if el.id in privacy.excluded_items(b, cfg):
        raise SystemExit(L(en=f'The item {key} is excluded by the privacy filter, its abstract is not given.',
                           fr=f'La fiche {key} est exclue par le filtre de confidentialité, son résumé n\'est pas '
                              'donné.'))
    return f"{_line(el)}\n\n{el.fields.get('abstractNote') or L(en='(no abstract)', fr='(pas de résumé)')}"
