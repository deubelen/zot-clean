"""Plan of the collection (« fonds »), step 4 of the cleanup (D95 to D107). Read-only.

`inventory` writes a report on the existing classification (collection tree,
thematic tags) so that the agent can propose a plan, and prepares
`suivi/fonds.toml`, which gives a fate to each old collection (D99, D100).
`check` checks `plan.md` and `suivi/fonds.toml`, then, on request,
records the fingerprint of their structure (D102). Step 5 will refuse to
plan the filing if that structure has changed since.

`plan.md` describes the fonds under a top-level heading bearing the name of
the root (`# Fonds`), with `##` for a discipline, `###` for a theme and
`####` for a sub-theme (D101). The other top-level sections
(concepts, notes) are ignored here. Paths are relative to the fonds
(`Sociologie/Méthodes`).
"""

import hashlib
import json
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from zot_clean import privacy
from zot_clean.audit import year, write_toml, norm
from zot_clean.config import Config
from zot_clean.duplicates import _toml
from zot_clean.lang import L
from zot_clean.reader import Library, Item

FILE = 'fonds.toml'
VALIDATION = 'fonds-validation.json'
OUTLINE = 'plan.md'
THEME, DISTRIBUTE, PROJECT, ARCHIVES, DISSOLVE, OUTSIDE_OUTLINE = (
    'thème', 'répartir', 'projet', 'archives', 'dissoudre', 'hors plan')
ACTIONS = {norm(s): s for s in (THEME, DISTRIBUTE, PROJECT, ARCHIVES, DISSOLVE, OUTSIDE_OUTLINE)}
SAMPLE = 10
DOMINANT_TAGS = 5
MAX_TAGS = 300
MAX_COOCCURRENCES = 60


def levels() -> dict[int, str]:
    return {1: L(en='discipline', fr='discipline'), 2: L(en='theme', fr='thème'),
            3: L(en='sub-theme', fr='sous-thème')}

def header() -> str:
    return L(en="""\
# Correspondence between the old classification and the subjects outline, prepared by `zc subjects inventory`.
# This file can be read and edited by hand or with the agent. `zc subjects inventory` updates it without losing the
# fates already given, `zc subjects validate` checks it against plan.md.
#
# Each old collection is given a fate (`sort`).
#   "thème"     it becomes the `cible` (target) collection of the outline (path in the subjects, "Sociology/Methods").
#   "répartir"  its items will be distributed one by one in step 5, among the `candidats` (candidates, paths of the
#               outline). Once marked as reviewed (`zc subjects pending --reviewed`), it goes to the trash, the items
#               left in it keeping their other collections. A collection already at a path of the outline stays.
#   "projet"    it goes under a projects root, at the path `cible`, which starts with the name of the root
#               ("Projects/Course 101"). Empty, with a single projects root, it keeps its name there.
#   "archives"  it goes under the archives root, under the name `cible` (by default, its current path).
#   "dissoudre" it goes to the trash, its items keep their other collections.
#   "hors plan" it stays as it is, with its subcollections.
# An empty fate is still to be given. `candidats` only applies to the fate "répartir". `note` is free.
#
# The `racines` table gives the new name of each root, applied by `zc subjects plan --roots`,
# for instance "40 Subjects" = "Subjects". A root missing from the table keeps its name.
#
# The `tags` table, at the end of the file, links a thematic tag to a path of the outline, as a hint to file its items
# in step 5, for instance "visual perception" = "Psychology/Perception".
""", fr="""\
# Correspondance entre l'ancien classement et le plan du fonds, préparée par `zc subjects inventory`.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc subjects inventory` le met à jour sans
# perdre les sorts déjà donnés, `zc subjects validate` le contrôle avec plan.md.
#
# Chaque ancienne collection reçoit un sort :
#   "thème"     elle devient la collection `cible` du plan (chemin dans le fonds, « Sociologie/Méthodes »).
#   "répartir"  ses fiches seront réparties une à une à l'étape 5, entre les `candidats` (chemins du plan). Une fois
#               marquée examinée (`zc subjects pending --reviewed`), elle va à la corbeille, les fiches laissées y
#               gardant leurs autres collections. Une collection déjà à un chemin du plan reste, elle.
#   "projet"    elle va sous une racine de projets, au chemin `cible`, qui commence par le nom de la racine
#               (« Projets/Cours L1 »). Vide, avec une seule racine de projets, elle y garde son nom.
#   "archives"  elle va sous la racine des archives, sous le nom `cible` (par défaut, son chemin actuel).
#   "dissoudre" elle va à la corbeille, ses fiches gardent leurs autres collections.
#   "hors plan" elle reste telle quelle, avec ses sous-collections.
# Un sort vide reste à donner. `candidats` ne sert qu'au sort « répartir ». `note` est libre.
#
# La table `racines` donne le nouveau nom de chaque racine, appliqué par `zc subjects plan --roots`,
# par exemple "40 Fonds" = "Fonds". Une racine absente de la table garde son nom.
#
# La table `tags`, en fin de fichier, relie un tag thématique à un chemin du plan, comme indice pour ranger ses fiches à l'étape 5,
# par exemple "perception visuelle" = "Psychologie/Perception".
""")



# --- Plan ---------------------------------------------------------------------------

@dataclass
class Node:
    path: str
    level: int  # 1 discipline, 2 theme, 3 sub-theme
    line: int
    definition: str = ''
    includes: str = ''
    excludes: str = ''


@dataclass
class Outline:
    nodes: dict[str, Node] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def filing_targets(self) -> list[str]:
        """Paths an item is filed in, in outline order. The themes and sub-themes, and the disciplines that have no
        theme (a discipline with themes only gathers them)."""
        return [p for p, nd in self.nodes.items()
                if nd.level > 1 or not any(q.startswith(p + '/') for q in self.nodes)]


def read_outline(text: str, cfg: Config) -> Outline:
    m = cfg.method
    p = Outline()
    in_subjects, found, code_block = False, False, False
    stack: list[str] = []  # names of the open headings, by level
    cur: Node | None = None
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith(('```', '~~~')):
            code_block = not code_block
            continue
        if code_block:
            continue
        title = re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', raw)
        if title and len(title.group(1)) == 1:
            in_subjects = title.group(2) == m.subjects
            found = found or in_subjects
            cur = None
            continue
        if not in_subjects:
            continue
        if title:
            level, name = len(title.group(1)) - 1, title.group(2)
            cur = None
            if level > m.max_depth:
                p.errors.append(L(en=f'line {n}: "{name}" is deeper than {m.max_depth} levels.',
                                  fr=f'ligne {n} : « {name} » est au-delà de {m.max_depth} niveaux.'))
                continue
            if level > len(stack) + 1:
                p.errors.append(L(en=f'line {n}: "{name}" ({levels()[level]}) has no parent, '
                                     f'a level {"#" * (len(stack) + 2)} heading is missing above it.',
                                  fr=f'ligne {n} : « {name} » ({levels()[level]}) n\'a pas de parent, '
                                     f'il manque un titre de niveau {"#" * (len(stack) + 2)} au-dessus.'))
                continue
            if not name or '/' in name:
                p.errors.append(L(en=f'line {n}: empty name or name containing "/" ("{name}").',
                                  fr=f'ligne {n} : nom vide ou contenant « / » (« {name} »).'))
                continue
            if level == 1 and name in m.roots:
                p.errors.append(L(en=f'line {n}: "{name}" is the name of a root, not to be given to a discipline.',
                                  fr=f'ligne {n} : « {name} » est le nom d\'une racine, à ne pas donner à une '
                                     'discipline.'))
            del stack[level - 1:]
            stack.append(name)
            path = '/'.join(stack)
            if path in p.nodes:
                p.errors.append(L(en=f'line {n}: "{path}" already exists (line {p.nodes[path].line}), '
                                     'two sibling collections cannot have the same name.',
                                  fr=f'ligne {n} : « {path} » existe déjà (ligne {p.nodes[path].line}), '
                                     'deux collections sœurs ne peuvent pas porter le même nom.'))
                continue
            cur = p.nodes[path] = Node(path, level, n)
            continue
        if cur is None or not raw.strip():
            continue
        line_text = raw.strip()
        # « Inclut » and « Exclut », or « Includes » and « Excludes », whatever the language of the library (D228).
        field_name = re.match(r'^[*_]*(Inclut|Exclut|Includes|Excludes)[*_]*\s*[:.]?\s*[*_]*\s*(.*)$', line_text, re.I)
        if field_name:
            attribute = 'includes' if field_name.group(1).lower() in ('inclut', 'includes') else 'excludes'
            setattr(cur, attribute, (getattr(cur, attribute) + ' ' + field_name.group(2)).strip())
        else:
            cur.definition = (cur.definition + ' ' + line_text).strip()
    if not found:
        p.errors.append(L(en=f'no section "# {m.subjects}", under which plan.md describes the subjects.',
                          fr=f'aucune section « # {m.subjects} », sous laquelle plan.md décrit le fonds.'))
    elif not p.nodes:
        p.errors.append(L(en=f'the section "# {m.subjects}" contains no discipline (## heading).',
                          fr=f'la section « # {m.subjects} » ne contient aucune discipline (titre ##).'))
    for nd in p.nodes.values():
        if not nd.definition:
            p.warnings.append(L(en=f'"{nd.path}" ({levels()[nd.level]}) has no definition.',
                                fr=f'« {nd.path} » ({levels()[nd.level]}) n\'a pas de définition.'))
    if p.nodes and not any(nd.level > 1 for nd in p.nodes.values()):
        p.warnings.append(L(
            en=f'no discipline has a theme (### heading). Items will be filed directly in the disciplines, which '
               f'suits a small collection. Beyond {m.subtheme_threshold} items, a discipline is better split into '
               'themes.',
            fr=f'aucune discipline n\'a de thème (titre ###). Les fiches seront rangées directement dans les '
               f'disciplines, ce qui convient à un petit fonds. Au-delà de {m.subtheme_threshold} fiches, une '
               'discipline gagne à être découpée en thèmes.'))
    return p


# --- Tracking --------------------------------------------------------------------------

@dataclass
class OldCollection:
    key: str
    path: str
    count: int = 0
    action: str = ''
    target: str = ''
    candidates: list[str] = field(default_factory=list)
    note: str = ''
    prefilled: str = ''  # reason for the prefilled fate, written as a comment


@dataclass
class Tracking:
    collections: list[OldCollection] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    roots: dict[str, str] = field(default_factory=dict)  # current name -> new name (D112)


def load_tracking(cfg: Config) -> Tracking:
    path = cfg.tracking / FILE
    if not path.is_file():
        return Tracking()
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start again from scratch.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    s = Tracking(tags={str(k): str(v) for k, v in raw.get('tags', {}).items()},
              roots={str(k): str(v) for k, v in raw.get('racines', {}).items()})
    for c in raw.get('collection', []):
        action = c.get('sort', '')
        if action and norm(action) not in ACTIONS:
            raise SystemExit(L(
                en=f'{path}: unknown sort "{action}" for {c.get("chemin", c.get("cle"))}. '
                   f'Possible values: {", ".join(ACTIONS.values())}.',
                fr=f'{path} : sort inconnu « {action} » pour {c.get("chemin", c.get("cle"))}. '
                   f'Sorts possibles : {", ".join(ACTIONS.values())}.'))
        s.collections.append(OldCollection(c['cle'], c.get('chemin', ''), int(c.get('effectif', 0)),
                                      ACTIONS[norm(action)] if action else '', c.get('cible', ''),
                                      list(c.get('candidats', [])), c.get('note', '')))
    return s


def write_tracking(cfg: Config, s: Tracking) -> None:
    lines = [header()]
    for c in s.collections:
        lines += ['[[collection]]']
        if c.prefilled:
            lines.append(f'# {c.prefilled}')
        lines += [f'cle = {_toml(c.key)}', f'chemin = {_toml(c.path)}', f'effectif = {c.count}',
                   f'sort = {_toml(c.action)}', f'cible = {_toml(c.target)}',
                   f'candidats = {_toml(c.candidates if c.action in (DISTRIBUTE, "") else [])}',
                   f'note = {_toml(c.note)}', '']
    lines += ['[racines]'] + [f'{_toml(k)} = {_toml(v)}' for k, v in s.roots.items()] + ['']
    lines += ['[tags]'] + [f'{_toml(k)} = {_toml(v)}' for k, v in s.tags.items()]
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    write_toml(cfg.tracking / FILE, lines + [''])


# --- Inventory ---------------------------------------------------------------------

def refusal(cfg: Config) -> str:
    """Reason for `zc subjects` to refuse, empty if the step can run (D96)."""
    if not cfg.method.subjects:
        return L(en='The subjects root is disabled in config.toml ([methode] fonds = ""). Step 4 builds the '
                    'outline of this root, so it has no reason to run.',
                 fr='La racine du fonds est désactivée dans config.toml ([methode] fonds = ""). '
                    "L'étape 4 construit le plan de cette racine, elle n'a donc pas lieu d'être.")
    return ''


def _roots(b: Library) -> dict[str, int]:
    return {c.name: c.id for c in b.collections.values() if c.parent is None}


def _under(b: Library, cid: int, root: int | None) -> bool:
    return root is not None and cid != root and b.root(cid) == root


def _relative(b: Library, cid: int) -> str:
    """Path without the root."""
    return b.path(cid).split('/', 1)[1]


def excluded_collections(b: Library, cfg: Config) -> tuple[set[int], set[int]]:
    """Collections designated by the filter (D18), and all those they cover, descendants included."""
    names = set(cfg.privacy.excluded_collections)
    designated_cols = {c for c in b.collections if b.collections[c].name in names or b.path(c) in names}
    covered = {c for c in b.collections if privacy._excluded(b, c, names)}
    # A designated collection under another designated one is already covered by its ancestor.
    designated_cols = {c for c in designated_cols if not (b.collections[c].parent in covered)}
    return designated_cols, covered


def _old_collections(b: Library, cfg: Config, excluded_items: set[int]) -> dict[str, OldCollection]:
    """One entry per collection outside the roots of the method, with its prefilled fate (D99).

    Once `plan.md` is written, a collection of the fonds already at a path of the plan (a sub-theme created by a
    filing pass, for example) gets the fate « thème » toward that path."""
    m = cfg.method
    plan_path = cfg.workspace / OUTLINE
    nodes = read_outline(plan_path.read_text(encoding='utf-8'), cfg).nodes if plan_path.is_file() else {}
    roots = _roots(b)
    designated_cols, covered = excluded_collections(b, cfg)
    counts = Counter(c for e in b.items if e.id not in excluded_items for c in e.collections)
    res = {}
    for cid in sorted(b.collections, key=b.path):
        col = b.collections[cid]
        if col.parent is None and col.name in m.roots:
            continue
        if cid in covered and cid not in designated_cols:
            continue
        a = OldCollection(col.key, b.path(cid), counts[cid])
        if cid in designated_cols:
            a.action = OUTSIDE_OUTLINE
            a.prefilled = L(en='excluded by the privacy filter, absent from the inventory',
                            fr="exclue par le filtre de confidentialité, absente de l'inventaire")
        elif any(_under(b, cid, roots.get(r)) for r in m.projects):
            a.action, a.target = PROJECT, b.path(cid)
            a.prefilled = L(en='already under a projects root', fr='déjà sous une racine de projets')
        elif m.archives and _under(b, cid, roots.get(m.archives)):
            a.action, a.target = ARCHIVES, _relative(b, cid)
            a.prefilled = L(en='already under the archives root', fr='déjà sous la racine des archives')
        elif _under(b, cid, roots.get(m.subjects)) and _relative(b, cid) in nodes:
            a.action, a.target = THEME, _relative(b, cid)
            a.prefilled = L(en='already in its place in the outline', fr='déjà à sa place dans le plan')
        elif _under(b, cid, roots.get(m.subjects)):
            a.prefilled = L(en='in the current subjects, to keep, rename or merge',
                            fr='dans le fonds actuel, à garder, renommer ou fusionner')
        res[col.key] = a
    return res


def update_tracking(old: Tracking, detected: dict[str, OldCollection]) -> tuple[Tracking, list[OldCollection], list[OldCollection]]:
    """Keeps the given fates, adds the new collections. Also returns the new and the vanished ones."""
    by_key = {c.key: c for c in old.collections}
    new_ones = [d for key, d in detected.items() if key not in by_key]
    vanished = [c for c in old.collections if c.key not in detected]
    res = []
    for key, d in detected.items():
        a = by_key.get(key)
        if a and (a.action or a.target or a.candidates or a.note):
            a.path, a.count, a.prefilled = d.path, d.count, d.prefilled
            res.append(a)
        else:
            res.append(d)
    return Tracking(res, old.tags, old.roots), new_ones, vanished


def track_roots(cfg: Config) -> int:
    """After the roots are renamed (D112), carries the new names into the paths and targets of
    `fonds.toml` (a project target starts with the name of its root). Returns the number of collections touched."""
    tracking = load_tracking(cfg)
    current = set(cfg.method.roots)
    done = {a: n for a, n in tracking.roots.items() if n in current and a not in current}

    def track(path: str) -> str:
        for old, new in done.items():
            if path == old or path.startswith(old + '/'):
                return new + path[len(old):]
        return path

    n = 0
    for c in tracking.collections:
        path, target = track(c.path), track(c.target)
        if (path, target) != (c.path, c.target):
            c.path, c.target, n = path, target, n + 1
    if n:
        write_tracking(cfg, tracking)
    return n


def proposed_roots(cfg: Config, already: dict[str, str]) -> dict[str, str]:
    """New names of the roots of the method, without the leading number (D112). Choices already made are kept."""
    res = dict(already)
    for name in cfg.method.roots:
        if name not in res and (m := re.fullmatch(r'\d+[\s._-]+(.+)', name)):
            res[name] = m.group(1)
    return res


def _thematic_tag(name: str, typ: int, cfg: Config) -> bool:
    m = cfg.method
    return typ == 0 and not (name.startswith(m.technical_prefix) or name in m.statuses or name in m.other_tags)


def _tags(e: Item, cfg: Config) -> set[str]:
    return {n for n, t in e.tags if _thematic_tag(n, t, cfg)}


def _sample(items: list[Item]) -> list[Item]:
    """Titles spread across the alphabetical order, so as not to show only the start of the list."""
    sorted_items = sorted(items, key=lambda e: norm(e.title))
    if len(sorted_items) <= SAMPLE:
        return sorted_items
    stride = len(sorted_items) / SAMPLE
    return [sorted_items[int(i * stride)] for i in range(SAMPLE)]


def _item_line(e: Item) -> str:
    author = e.author or '?'
    return (f'{author}, {year(e) or L(en="n.d.", fr="s. d.")}, '
            f'{e.title[:100] or L(en="(untitled)", fr="(sans titre)")}')


def inventory(b: Library, cfg: Config, day: date | None = None) -> tuple[str, Tracking, list, list]:
    """Inventory report, updated tracking, collections new and vanished since the last inventory."""
    m = cfg.method
    excluded_items = privacy.excluded_items(b, cfg)
    _, covered = excluded_collections(b, cfg)
    items = [e for e in b.items if e.id not in excluded_items]
    old = load_tracking(cfg)
    tracking, new_ones, vanished = update_tracking(old, _old_collections(b, cfg, excluded_items))
    tracking.roots = proposed_roots(cfg, tracking.roots)
    actions = {c.key: c.action for c in tracking.collections}
    roots = _roots(b)

    by_col: dict[int, list[Item]] = defaultdict(list)
    for e in items:
        for c in e.collections:
            by_col[c].append(e)
    children: dict[int | None, list[int]] = defaultdict(list)
    for cid, c in b.collections.items():
        if cid not in covered:
            children[c.parent].append(cid)

    def total(cid: int) -> set[int]:
        ids = {e.id for e in by_col[cid]}
        for x in children[cid]:
            ids |= total(x)
        return ids

    day = day or date.today()
    without = sum(1 for e in items if not (e.collections - covered))
    excluded_note = (L(en=f' {len(excluded_items)} items and {len(covered)} collections excluded by the privacy '
                          'filter do not appear here.',
                       fr=f' {len(excluded_items)} références et {len(covered)} collections exclues par le filtre '
                          "de confidentialité n'apparaissent pas ici.") if excluded_items or covered else '')
    lines = [L(en=f'# Inventory of the classification for the subjects outline, {day:%d/%m/%Y}',
               fr=f'# Inventaire du classement pour le plan du fonds, {day:%d/%m/%Y}'), '',
             L(en="Read-only, nothing was changed. This inventory is used to propose the subjects outline "
                  "(`plan.md`) and the fate of each old collection (`suivi/fonds.toml`).",
               fr="Lecture seule, rien n'a été modifié. Cet inventaire sert à proposer le plan du fonds (`plan.md`) "
                  "et le sort de chaque ancienne collection (`suivi/fonds.toml`)."), '',
             L(en=f'{len(items)} items, {without} of them in no collection. '
                  f'{len(b.collections) - len(covered)} collections.',
               fr=f'{len(items)} références, dont {without} dans aucune collection. '
                  f'{len(b.collections) - len(covered)} collections.') + excluded_note]
    if roots.get(m.subjects) is not None:
        lines += ['', L(en=f'A root "{m.subjects}" already exists. Its tree is used as a draft of the outline.',
                        fr=f'Une racine « {m.subjects} » existe déjà. Son arbre sert de brouillon au plan.')]

    lines += ['', L(en='## Collection tree', fr='## Arbre des collections'), '',
              L(en='For each collection, the items filed directly in it (and with its subcollections), the depth, '
                   'the collections that share items, the dominant tags and a sample of titles '
                   f'({SAMPLE} at most, all of them for a collection of the subjects with more than '
                   f'{m.subtheme_threshold} items). The fates already given in `suivi/fonds.toml` are recalled.',
                fr='Pour chaque collection, les références rangées directement (et avec les sous-collections), la '
                   'profondeur, les collections qui partagent des références, les tags dominants et un échantillon '
                   f'de titres ({SAMPLE} au plus, tous pour une collection du fonds de plus de '
                   f'{m.subtheme_threshold} références). Les sorts déjà donnés dans `suivi/fonds.toml` sont '
                   'rappelés.')]

    def in_subjects(cid: int) -> bool:
        return _under(b, cid, roots.get(m.subjects))

    def describe(cid: int, level: int):
        col = b.collections[cid]
        direct = by_col[cid]
        everything = total(cid)
        count = (L(en=f'{len(direct)} items', fr=f'{len(direct)} réf.')
                 + (L(en=f', {len(everything)} with subcollections', fr=f', {len(everything)} avec les sous-collections')
                    if children[cid] else ''))
        action = actions.get(col.key, '')
        sort_note = L(en=f', sort "{action}"', fr=f', sort « {action} »') if action else ''
        lines.extend(['', f'{"#" * min(level + 2, 6)} {b.path(cid)}', '',
                      L(en=f'{count}, depth {level}{sort_note}.', fr=f'{count}, profondeur {level}{sort_note}.')])
        method = col.parent is None and col.name in m.roots
        shared_collections = Counter(c for e in direct for c in e.collections if c != cid and c not in covered)
        if shared_collections:
            shared = ', '.join(f'{b.path(c)} ({n})' for c, n in shared_collections.most_common(5))
            lines.append(L(en=f'Items shared with {shared}.', fr=f'Références partagées avec {shared}.'))
        dominant = Counter(t for e in direct for t in _tags(e, cfg)).most_common(DOMINANT_TAGS)
        if dominant:
            tags = ', '.join(f'{t} ({n})' for t, n in dominant)
            lines.append(L(en=f'Most frequent tags, {tags}.', fr=f'Tags les plus portés, {tags}.'))
        if direct and not method and action not in (PROJECT, ARCHIVES):
            is_complete = in_subjects(cid) and len(direct) > m.subtheme_threshold
            if is_complete:
                lines.append(L(en=f'Beyond {m.subtheme_threshold} items, complete list to judge a split into '
                                  'sub-themes.',
                               fr=f'Au-delà de {m.subtheme_threshold} références, liste complète pour juger d\'un '
                                  'découpage en sous-thèmes.'))
            lines.append('')
            chosen = sorted(direct, key=lambda e: norm(e.title)) if is_complete else _sample(direct)
            lines.extend(f'- {_item_line(e)}' for e in chosen)
        for x in sorted(children[cid], key=lambda x: norm(b.collections[x].name)):
            describe(x, level + 1)

    for cid in sorted(children[None], key=lambda x: (b.collections[x].name not in m.roots, norm(b.collections[x].name))):
        describe(cid, 1)

    account = Counter(t for e in items for t in _tags(e, cfg))
    lists = [(t, n) for t, n in account.most_common() if n >= 2]
    unique = sum(1 for n in account.values() if n == 1)
    others = ''.join(f'`{t}`, ' for t in m.other_tags)
    lines += ['', L(en='## Thematic tags', fr='## Tags thématiques'), '',
              L(en=f'Manual tags, without the status tags, {others}nor the technical tags (`{m.technical_prefix}`). '
                   'Automatic tags are ignored.',
                fr=f"Tags manuels, sans les tags d'état, {others}ni les tags techniques (`{m.technical_prefix}`). "
                   'Les tags automatiques sont ignorés.'), '',
              L(en=f'{len(account)} tags, {unique} of them used only once (not listed).',
                fr=f'{len(account)} tags, dont {unique} posés une seule fois (non listés).'), '']
    lines += [f'- {t} ({n})' for t, n in lists[:MAX_TAGS]]
    if len(lists) > MAX_TAGS:
        lines.append(L(en=f'- … and {len(lists) - MAX_TAGS} more', fr=f'- … et {len(lists) - MAX_TAGS} autres'))
    pairs = Counter()
    for e in items:
        ts = sorted(t for t in _tags(e, cfg) if account[t] >= 2)
        for i, a in enumerate(ts):
            for c in ts[i + 1:]:
                pairs[a, c] += 1
    frequent = [(p, n) for p, n in pairs.most_common(MAX_COOCCURRENCES) if n >= 3]
    if frequent:
        lines += ['', L(en='## Tags that come together', fr='## Tags qui reviennent ensemble'), '',
                  L(en='Pairs carried by at least three of the same items.',
                    fr='Paires portées par au moins trois mêmes références.'), '']
        lines += [f'- {a} + {c} ({n})' for (a, c), n in frequent]
    if new_ones and old.collections:
        lines += ['', L(en='## Collections new since the last inventory',
                        fr='## Collections nouvelles depuis le dernier inventaire'), '']
        lines += [f'- {c.path}' for c in new_ones]
    if vanished:
        lines += ['', L(en='## Collections gone since the last inventory',
                        fr='## Collections disparues depuis le dernier inventaire'), '',
                  L(en='Removed from `suivi/fonds.toml`, with the fate they had.',
                    fr="Retirées de `suivi/fonds.toml`, avec le sort qu'elles avaient."), '']
        lines += [f'- {c.path}' + (L(en=f' (sort "{c.action}")', fr=f' (sort « {c.action} »)') if c.action else '')
                  for c in vanished]
    return '\n'.join(lines) + '\n', tracking, new_ones, vanished


# --- Validation ---------------------------------------------------------------------

@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structure: dict = field(default_factory=dict)
    changes: list[str] = field(default_factory=list)
    already_validated: bool = False

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.structure)


def fingerprint(structure: dict) -> str:
    return hashlib.sha256(json.dumps(structure, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def structure(plan: Outline, s: Tracking) -> dict:
    """What the fingerprint covers, namely the paths of the plan, the fates and the targets (D102). Candidates
    count only for a collection to distribute, those of a collection moved to another fate no longer make sense."""
    return {
        'plan': sorted(plan.nodes),
        'collections': {c.key: [c.action, c.target, sorted(c.candidates) if c.action == DISTRIBUTE else []]
                        for c in s.collections},
        'tags': dict(sorted(s.tags.items())),
    }


def _without_useless_candidates(structure: dict) -> dict:
    """Structure recorded before the candidates of an undistributed collection were ignored."""
    res = dict(structure)
    res['collections'] = {key: [v[0], v[1], v[2] if v[0] == DISTRIBUTE else []]
                          for key, v in structure.get('collections', {}).items()}
    return res


def check(cfg: Config) -> Validation:
    m = cfg.method
    k = Validation()
    plan_path = cfg.workspace / OUTLINE
    if not plan_path.is_file():
        k.errors.append(L(en=f'{OUTLINE} missing from the working folder.',
                          fr=f'{OUTLINE} absent du dossier de travail.'))
        return k
    if not (cfg.tracking / FILE).is_file():
        k.errors.append(L(en=f'suivi/{FILE} missing. Run `zc subjects inventory`.',
                          fr=f'suivi/{FILE} absent. Lancer `zc subjects inventory`.'))
        return k
    plan = read_outline(plan_path.read_text(encoding='utf-8'), cfg)
    s = load_tracking(cfg)
    k.errors += [f'{OUTLINE}, {e}' for e in plan.errors]
    k.warnings += [f'{OUTLINE}, {a}' for a in plan.warnings]

    def exists(target: str) -> bool:
        return target in plan.nodes

    for c in s.collections:
        name = L(en=f'"{c.path}" ({c.key})', fr=f'« {c.path} » ({c.key})')
        if not c.action:
            k.errors.append(L(en=f'{name} has no sort.', fr=f'{name} n\'a pas de sort.'))
        elif c.action == THEME:
            if not c.target:
                k.errors.append(L(en=f'{name} becomes a theme, but its target is empty.',
                                  fr=f'{name} devient un thème, mais sa cible est vide.'))
            elif not exists(c.target):
                k.errors.append(L(en=f'{name} becomes "{c.target}", which is not in {OUTLINE}.',
                                  fr=f'{name} devient « {c.target} », qui n\'est pas dans {OUTLINE}.'))
        elif c.action == DISTRIBUTE:
            if not c.candidates:
                k.warnings.append(L(en=f'{name} is to be distributed, with no candidate theme.',
                                    fr=f'{name} est à répartir, sans thème candidat.'))
            for x in c.candidates:
                if not exists(x):
                    k.errors.append(L(en=f'{name} has the candidate "{x}", which is not in {OUTLINE}.',
                                      fr=f'{name} a pour candidat « {x} », qui n\'est pas dans {OUTLINE}.'))
        elif c.action == PROJECT and not m.projects:
            k.errors.append(L(en=f'{name} goes to the projects, but no projects root is declared.',
                              fr=f'{name} va dans les projets, mais aucune racine de projets n\'est déclarée.'))
        elif c.action == PROJECT and c.target and (c.target.split('/')[0] not in m.projects or '/' not in c.target):
            k.errors.append(L(en=f'{name} goes to the projects, but its target "{c.target}" does not start with a '
                                 f'projects root ({", ".join(m.projects)}), followed by the name of the project.',
                              fr=f'{name} va dans les projets, mais sa cible « {c.target} » ne commence pas par une '
                                 f'racine de projets ({", ".join(m.projects)}), suivie du nom du projet.'))
        elif c.action == PROJECT and not c.target and len(m.projects) > 1:
            k.errors.append(L(en=f'{name} goes to the projects, with no target, while there are several projects '
                                 'roots.',
                              fr=f'{name} va dans les projets, sans cible, alors qu\'il y a plusieurs racines de '
                                 'projets.'))
        elif c.action == ARCHIVES and not m.archives:
            k.errors.append(L(en=f'{name} goes to the archives, but the archives root is disabled.',
                              fr=f'{name} va dans les archives, mais la racine des archives est désactivée.'))
        if c.action in (PROJECT, ARCHIVES) and c.target and any(not p.strip() for p in c.target.split('/')):
            k.errors.append(L(en=f'{name} has a malformed target ("{c.target}").',
                              fr=f'{name} a une cible mal formée (« {c.target} »).'))
    # Only two identical explicit targets bring collections together (D118).
    doubles = Counter((c.action, c.target) for c in s.collections if c.action in (PROJECT, ARCHIVES) and c.target
                      and not stays_in_place(c, m))
    for (action, target), n in doubles.items():
        if n > 1:
            k.warnings.append(L(en=f'{n} collections go together into "{target}" ({action}), their items will be '
                                   'merged.',
                                fr=f'{n} collections vont ensemble dans « {target} » ({action}), leurs fiches seront '
                                   'réunies.'))
    for tag, target in s.tags.items():
        if not exists(target):
            k.errors.append(L(en=f'the tag "{tag}" points to "{target}", which is not in {OUTLINE}.',
                              fr=f'le tag « {tag} » renvoie à « {target} », qui n\'est pas dans {OUTLINE}.'))
    k.structure = structure(plan, s)
    former = read_validation(cfg)
    if former:
        before = _without_useless_candidates(former.get('structure', {}))
        k.already_validated = k.fingerprint in (former.get('empreinte'), fingerprint(before))
        if not k.already_validated:
            k.changes = differences(before, k.structure)
    return k


def stays_in_place(c: OldCollection, m) -> bool:
    """Project or archive whose target designates the current location (prefilled target, D99)."""
    if c.action == PROJECT:
        return c.target == c.path
    root, _, rest = c.path.partition('/')
    return c.action == ARCHIVES and root == m.archives and c.target == rest


def read_validation(cfg: Config) -> dict:
    path = cfg.tracking / VALIDATION
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def save(cfg: Config, k: Validation) -> None:
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    data = {'empreinte': k.fingerprint, 'date': datetime.now().isoformat(timespec='seconds'),
               'structure': k.structure}
    (cfg.tracking / VALIDATION).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


def differences(before: dict, after: dict) -> list[str]:
    res = []
    p0, p1 = set(before.get('plan', [])), set(after.get('plan', []))
    res += [L(en=f'added to the outline: {x}', fr=f'ajouté au plan : {x}') for x in sorted(p1 - p0)]
    res += [L(en=f'removed from the outline: {x}', fr=f'retiré du plan : {x}') for x in sorted(p0 - p1)]
    c0, c1 = before.get('collections', {}), after.get('collections', {})
    for key in sorted(set(c0) | set(c1)):
        if c0.get(key) != c1.get(key):
            res.append(L(en=f'collection {key}: {_readable_action(c0.get(key))} → {_readable_action(c1.get(key))}',
                         fr=f'collection {key} : {_readable_action(c0.get(key))} → {_readable_action(c1.get(key))}'))
    t0, t1 = before.get('tags', {}), after.get('tags', {})
    for t in sorted(set(t0) | set(t1)):
        if t0.get(t) != t1.get(t):
            none = L(en='no theme', fr='aucun thème')
            res.append(L(en=f'tag "{t}": {t0.get(t) or none} → {t1.get(t) or none}',
                         fr=f'tag « {t} » : {t0.get(t) or none} → {t1.get(t) or none}'))
    return res


def _readable_action(v) -> str:
    if not v:
        return L(en='absent', fr='absente')
    action, target, candidates = v
    detail = target or ', '.join(candidates)
    no_sort = L(en='no sort', fr='sans sort')
    return L(en=f'"{action or no_sort}"', fr=f'« {action or no_sort} »') + (f' {detail}' if detail else '')


def validation_up_to_date(cfg: Config) -> tuple[bool, list[str]]:
    """For step 5, is the structure the one that was validated (D102)?"""
    k = check(cfg)
    if not read_validation(cfg):
        return False, [L(en='plan never validated (`zc subjects validate`).',
                         fr='plan jamais validé (`zc subjects validate`).')]
    return k.already_validated and not k.errors, k.errors + k.changes
