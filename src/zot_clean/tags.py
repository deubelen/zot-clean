"""Tags, step 6 of the cleanup (D22, D151 to D156).

`inventory` describes the whole set of tags (usages, variants, imported
keywords, statuses from other habits, concepts and tags that duplicate a
theme, protected tags) and prepares `suivi/tags.toml`, which describes rules
by tag name, never by item. The `[automatiques]` section holds the global
rule that removes automatic tags (D152), `[importes]` the same rule for
keywords imported as manual tags (D153), each `[[tag]]` the fate of one tag
(exception to the rule, status, concept, deletion, merge) and each
`[[variantes]]` a group of names brought back to one form. Decisions are kept
from one run to the next, and the file then serves the Inbox triage (D155).

`rules` and `targeted_tags` give, without network, the final list of tags of
an element according to the accepted rules. `make_plan` derives from them a
plan with one operation per element (item, attachment, note or annotation)
that writes its complete list of tags, types kept (D156), without
`DELETE /tags`. It compares the real state with the rules and plans only the
difference (D119).

Protected tags, that is inventoried without proposal and changed only by a
user entry (`source = "utilisateur"`), are the technical tags, the statuses
and marks of the method, the colored tags, those of `[tags] proteges` and
those on which a pending filing proposal rests. The tags of `tags_exclus`
never change. A tag carried only by confidential items appears only under a
stable identifier, and only the global rules apply to it without a user
entry. A tag cited by a saved search escapes the global rules.
"""

import hashlib
import re
import tomllib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

from zot_clean import privacy, subjects as f, filing as r
from zot_clean.audit import year, write_toml, norm
from zot_clean.config import Config
from zot_clean.duplicates import _toml
from zot_clean.lang import L, plural
from zot_clean import lang
from zot_clean.api import Client
from zot_clean.reader import Library, Item
from zot_clean.plans import Group, Operation, Plan, normalize

FILE = 'tags.toml'
STEP = 'tags'
DELETE, KEEP, CONCEPT, STATUS, MERGE = 'supprimer', 'garder', 'concept', 'état', 'fusionner'
ACTIONS = {norm(s): s for s in (DELETE, KEEP, CONCEPT, STATUS, MERGE)}
ACCEPT, REJECT = 'accepter', 'refuser'
ZC, AGENT, USER = 'zc', 'agent', 'utilisateur'
OBVIOUS, DOUBTFUL = 'évident', 'douteux'
MANUAL, AUTOMATIC, BOTH = 'manuel', 'automatique', 'les deux'
MAX_COLORS = 9
TITLES = 3
SHOW_MAX = 50

# Kinds of change in a plan, in report order (the keys are stored in the `nature` of the operations).
def kinds() -> dict[str, str]:
    return {
        'automatique': L(en='automatic tags removed by the global rule', fr='tags automatiques retirés par la règle globale'),
        'importé': L(en='imported keywords removed', fr='mots-clés importés retirés'),
        'variante': L(en='variants brought back to their form', fr='variantes ramenées à leur forme'),
        'état': L(en='tags brought back to a status or mark of the method',
                  fr='tags ramenés à un état ou une marque de la méthode'),
        'concept': L(en='tags converted into concepts', fr='tags convertis en concepts'),
        'fusion': L(en='tags merged into another', fr='tags fusionnés dans un autre'),
        'suppression': L(en='tags deleted', fr='tags supprimés'),
    }


def kind_word(kind: str) -> str:
    """Kind of change in one word, as shown beside a tag or an element."""
    return {'automatique': L(en='automatic', fr='automatique'), 'importé': L(en='imported', fr='importé'),
            'variante': L(en='variant', fr='variante'), 'état': L(en='status', fr='état'),
            'concept': L(en='concept', fr='concept'), 'fusion': L(en='merge', fr='fusion'),
            'suppression': L(en='deletion', fr='suppression')}.get(kind, kind)


def nature_shown(nature: str) -> str:
    """Nature of an operation of the plan (stored kinds, D209) as shown."""
    return ', '.join(kind_word(k) for k in nature.split(', ')) if nature else nature


def type_shown(kind: str) -> str:
    """Type of a tag (stored words, D209: « manuel », « automatique », « les deux », with « , importé ») as shown
    (verification pilot: an English report read « (manuel, 3 item(s)) »)."""
    words = {MANUAL: L(en='manual', fr='manuel'), AUTOMATIC: L(en='automatic', fr='automatique'),
             BOTH: L(en='both', fr='les deux'), 'importé': L(en='imported', fr='importé')}
    return ', '.join(words.get(w, w) for w in kind.split(', ')) if kind else kind


def action_shown(action: str) -> str:
    """Fate of a tag (stored word, D209) as shown, with the English values of `--action` (D219)."""
    return {DELETE: L(en='delete', fr='supprimer'), KEEP: L(en='keep', fr='garder'),
            CONCEPT: L(en='concept', fr='concept'), STATUS: L(en='status', fr='état'),
            MERGE: L(en='merge', fr='fusionner')}.get(action, action)


def grade_shown(grade: str) -> str:
    """Grade of a group of variants (stored word, D209) as shown."""
    return {OBVIOUS: L(en='obvious', fr='évident'), DOUBTFUL: L(en='doubtful', fr='douteux')}.get(grade, grade)


KIND_OF_ACTION = {CONCEPT: 'concept', STATUS: 'état', MERGE: 'fusion'}

# Statuses and marks from other habits (D156), matched by form to those of `[methode]`: index of the
# status in `etats` (0 to read, 1 in progress, 2 read) or of the mark in `autres_tags` (0 essential, 1 paper).
FOREIGN_STATUSES = {
    0: ('to read', 'toread', 'unread', 'à lire', 'non lu', 'pas lu', 'read later', 'à lire plus tard', 'reading list'),
    1: ('reading', 'en cours', 'en cours de lecture', 'en lecture', 'in progress', 'currently reading', 'commencé',
        'reading now', 'now reading', 'started'),
    2: ('read', 'lu', 'déjà lu', 'already read', 'done', 'finished', 'fini', 'terminé', 'lu et annoté'),
}
FOREIGN_MARKS = {
    0: ('important', 'essentiel', 'essential', 'key paper', 'favorite', 'favourite', 'favori', 'must read',
        'incontournable', 'starred', 'étoile'),
    1: ('imprimé', 'printed', 'papier', 'version papier', 'hard copy', 'photocopie', 'copie papier', 'printed copy',
        'print copy', 'copie imprimée', 'paper copy'),
}

def header() -> str:
    return L(en="""\
# Tag rules, prepared by `zc tags inventory` (step 6) and read by `zc tags plan`, then by the Inbox triage.
# This file can be read and edited by hand or with the agent. `zc tags inventory` updates it without losing the
# decisions taken. A rule applies to a tag name, never to an item. Decisions are written with `zc tags accept`,
# `zc tags reject` and `zc tags add` (see `zc tags accept --help`).
#
# [automatiques] removes all the automatic tags (publishers' keywords), except the exceptions below.
# [importes]     likewise removes the keywords imported as manual tags (items that carry many of them, and rare ones).
#
# [[tag]], a tag to judge.
#   sort     : "supprimer" (delete), "garder" (keep), "concept" (renamed to `cible`, which starts with the concept
#              prefix), "état" (renamed to a status or a mark of the method), "fusionner" (renamed to `cible`).
#              A kept automatic tag stays automatic. A renamed tag becomes manual.
#   source   : "zc" (proposed by zc), "agent", "utilisateur". A protected tag (technical, status, mark, colored, list
#              [tags] proteges of config.toml) only changes through an entry whose source is "utilisateur".
#   classe   : "évident" (to approve in bulk) or "douteux" (by bundles).
#   decision : "" (proposed), "accepter" or "refuser". Only accepted entries apply. As long as an entry waits, its
#              tag escapes the global rules.
#   effectif (items that carry it, directly or through a child), dispersion (themes of the subjects where they are),
#   themes, theme (theme it duplicates), recherches (saved searches that cite it): filled in by zc.
#   variantes : other names of the same form, brought back to `nom` before the fate is applied (for instance deleted
#              with it). zc gathers them here rather than in a [[variantes]] when it proposes to delete the tag.
#
# [[variantes]], names that differ only by case, accents, spaces, prefix or plural, brought back to `cible`, set as a
#   manual tag. "évident" when the plural is not involved. A concept is written in lowercase except for proper
#   nouns, in the user's language, spaces allowed ("#cognition incarnée").
#
# A tag carried only by confidential items appears under an identifier ("tag confidentiel 1a2b3c4d"), usable as a
# name in an entry whose source is "utilisateur".
""", fr="""\
# Règles des tags, préparées par `zc tags inventory` (étape 6) et lues par `zc tags plan`, puis par
# le tri de l'Inbox. Ce fichier se relit et se modifie à la main ou avec l'agent. `zc tags inventory` le met à jour
# sans perdre les décisions prises. Une règle porte sur un nom de tag, jamais sur une fiche. Les décisions
# s'écrivent avec `zc tags accept`, `zc tags reject` et `zc tags add` (voir `zc tags accept --help`).
#
# [automatiques] retire tous les tags automatiques (mots-clés des éditeurs), sauf les exceptions ci-dessous.
# [importes]     retire de même les mots-clés importés en tags manuels (fiches qui en portent beaucoup, et rares).
#
# [[tag]], un tag à juger.
#   sort     : "supprimer", "garder", "concept" (renommé en `cible`, qui commence par le préfixe des concepts),
#              "état" (renommé en un état ou une marque de la méthode), "fusionner" (renommé en `cible`).
#              Un tag automatique gardé reste automatique. Un tag renommé devient manuel.
#   source   : "zc" (proposé par zc), "agent", "utilisateur". Un tag protégé (technique, état, marque, coloré, liste
#              [tags] proteges de config.toml) ne change que par une entrée de source "utilisateur".
#   classe   : "évident" (à approuver en bloc) ou "douteux" (par paquets).
#   decision : "" (proposé), "accepter" ou "refuser". Seules les entrées acceptées s'appliquent. Tant qu'une entrée
#              attend, son tag échappe aux règles globales.
#   effectif (fiches qui le portent, directement ou par un enfant), dispersion (thèmes du fonds où elles sont),
#   themes, theme (thème qu'il double), recherches (recherches enregistrées qui le citent) : renseignés par zc.
#   variantes : autres noms de même forme, ramenés à `nom` avant d'appliquer le sort (par exemple supprimés avec
#              lui). zc les réunit ici plutôt que dans un [[variantes]] quand il propose de supprimer le tag.
#
# [[variantes]], des noms qui ne diffèrent que par la casse, les accents, les espaces, le préfixe ou le pluriel,
#   ramenés à `cible`, posée en tag manuel. "évident" quand seul le pluriel n'intervient pas. Un concept s'écrit en
#   minuscules sauf nom propre, dans la langue de l'utilisateur, espaces permis (« #cognition incarnée »).
#
# Un tag porté seulement par des fiches confidentielles apparaît sous un identifiant (« tag confidentiel 1a2b3c4d »),
# utilisable comme nom dans une entrée de source "utilisateur".
""")



# --- Formes -----------------------------------------------------------------------

def _words(name: str, cfg: Config) -> tuple[str, list[str]]:
    m = cfg.method
    head = ''
    if m.technical_prefix and name.startswith(m.technical_prefix):
        head = m.technical_prefix  # « _lu » is not a variant of « lu »
    if m.concept_prefix and name.startswith(m.concept_prefix):
        name = name[len(m.concept_prefix):]
    without = ''.join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c)).casefold()
    return head, re.findall(r'[^\W_]+', without)


def weak_form(name: str, cfg: Config) -> str:
    """Name without case, accents, spaces, hyphens or concept prefix."""
    head, words = _words(name, cfg)
    return head + ''.join(words) if words else name.casefold()


def form(name: str, cfg: Config) -> str:
    """Normalised form that groups variants (D156), simple plural included (`s`, `x`, `-aux`)."""
    head, words = _words(name, cfg)
    return head + ''.join(_singular(x) for x in words) if words else name.casefold()


def _singular(word: str) -> str:
    if len(word) > 3 and word[-1] in 'sx':
        word = word[:-1]
    if len(word) > 3 and word.endswith('al'):
        word = word[:-2] + 'au'  # cheval and chevaux, réseau and réseaux
    return word


def _technical_mark(name: str, cfg: Config) -> bool:
    """Name that starts with neither a letter, nor a digit, nor the concept prefix: a mark left by
    an application (« /unread », « _tablet », « @todo »), never a notion to propose as a concept. The technical
    tags of the method (`_`) are protected before getting here."""
    p = cfg.method.concept_prefix
    return bool(name) and not name[0].isalnum() and not (p and name.startswith(p))


def concept_name(name: str, cfg: Config) -> str:
    """Concept name proposed for a tag, following the skill's convention as far as zc can: concept
    prefix, lowercase (an acronym like « TDAH » stays in capitals), spaces in place of underscores. zc does not
    translate anything, the agent checks the name and puts it in the user's language."""
    p = cfg.method.concept_prefix
    body = name[len(p):] if p and name.startswith(p) else name
    words = body.replace('_', ' ').split()
    return p + ' '.join(m if len(m) > 1 and m.isupper() else m.lower() for m in words)


def identifier(name: str) -> str:
    """Stable name of a tag carried only by confidential items (D156)."""
    return 'tag confidentiel ' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]


# --- Usages -----------------------------------------------------------------------

@dataclass
class Usage:
    name: str
    types: set[int] = field(default_factory=set)
    occurrences: Counter = field(default_factory=Counter)  # type -> number of elements
    all_items: set[int] = field(default_factory=set)
    items: set[int] = field(default_factory=set)  # items that carry it, directly or through a child
    children: int = 0
    annotations: int = 0
    themes: Counter = field(default_factory=Counter)  # theme of the fonds -> items
    searches: list[str] = field(default_factory=list)
    color: str = ''
    color_rank: int = 0
    confidential: bool = False

    @property
    def dispersion(self) -> int:
        return len(self.themes)

    @property
    def readable_type(self) -> str:
        return BOTH if len(self.types) > 1 else (AUTOMATIC if 1 in self.types else MANUAL)


def item_of(b: Library, el: Item) -> int | None:
    """Item of an element, the element itself if it is one, its parent item for a child, None for a standalone note."""
    if el.is_item:
        return el.id
    if el.id in b.attachments:
        return b.attachments[el.id].parent
    if el.id in b.notes:
        return b.notes[el.id]
    attachment = b.annotation_of.get(el.id)
    return b.attachments[attachment].parent if attachment in b.attachments else None


def themes_of_items(b: Library, cfg: Config) -> dict[int, set[str]]:
    """Themes of the fonds for each item, at the level of discipline and theme (a subtheme counts for its theme),
    outside the collections excluded by the filter."""
    e = r._State(b)
    root = e.root(cfg.method.subjects) if cfg.method.subjects else None
    if root is None:
        return {}
    _, covered = f.excluded_collections(b, cfg)
    res: dict[int, set[str]] = defaultdict(set)
    for el in b.items:
        for cid in el.collections:
            k = e.key[cid]
            if cid not in covered and k != root and e.under(k, root):
                res[el.id].add('/'.join(e.path(k).split('/')[1:3]))
    return res


def _cites(operator: str, value: str, name: str) -> bool:
    if operator in ('contains', 'doesNotContain'):
        return bool(value) and value.casefold() in name.casefold()
    return value == name


def usages(b: Library, cfg: Config) -> dict[str, Usage]:
    hidden = privacy.hidden_keys(b, cfg)
    themes = themes_of_items(b, cfg)
    res: dict[str, Usage] = {}
    for el in b.all_items.values():
        item = item_of(b, el)
        for name, typ in el.tags:
            u = res.setdefault(name, Usage(name))
            u.types.add(typ)
            u.occurrences[typ] += 1
            u.all_items.add(el.id)
            if not el.is_item:
                u.children += 1
                u.annotations += el.type == 'annotation'
            if item is not None and item in b.all_items:
                u.items.add(item)
    for u in res.values():
        for item in u.items:
            u.themes.update(themes.get(item, ()))
        u.confidential = all(b.all_items[i].key in hidden for i in u.all_items)
    for rank, (name, color) in enumerate(b.colors, 1):
        if name in res:
            res[name].color, res[name].color_rank = color, rank
    for search, operator, value in b.tag_searches:
        for name, u in res.items():
            if _cites(operator, value, name) and search not in u.searches:
                u.searches.append(search)
    return res


def outline_concepts(cfg: Config) -> list[str]:
    """Concepts defined in the `# Concepts` section of plan.md, one `## #name` heading each (D154)."""
    path = cfg.workspace / f.OUTLINE
    if not path.is_file():
        return []
    res, contained = [], False
    for line in path.read_text(encoding='utf-8').splitlines():
        if m := re.match(r'^#\s+(.*?)\s*$', line):
            contained = norm(m.group(1)) == 'concepts'
        elif contained and (m := re.match(r'^##\s+(.*?)\s*$', line)):
            res.append(m.group(1))
    return res


# --- Tracking file -------------------------------------------------------------

@dataclass
class Entry:
    name: str
    type: str = ''
    count: int = 0
    dispersion: int = 0
    themes: list[str] = field(default_factory=list)
    theme: str = ''  # theme of the plan that the tag duplicates (D154)
    searches: list[str] = field(default_factory=list)
    action: str = ''
    target: str = ''
    source: str = ZC
    grade: str = DOUBTFUL
    decision: str = ''
    note: str = ''
    variants: list[str] = field(default_factory=list)  # names brought back to `name` before the fate


@dataclass
class Variants:
    names: list[str]
    target: str
    grade: str = DOUBTFUL
    source: str = ZC
    decision: str = ''
    note: str = ''


@dataclass
class Tracking:
    automatic: str = ''  # decision of the global rule
    imported: str = ''  # decision for imported keywords
    tags: list[Entry] = field(default_factory=list)
    variants: list[Variants] = field(default_factory=list)
    # Filled in by the inventory, written as a comment or in rangement.toml.
    automatic_summary: str = ''
    imported_summary: str = ''
    pending: list = field(default_factory=list)  # filing proposals (filing.Entry, source « tag »)


def _decision(v: str, where: str, path) -> str:
    if v not in ('', ACCEPT, REJECT):
        raise SystemExit(L(en=f'{path}: unknown decision "{v}" ({where}). Possible decisions: "", "{ACCEPT}", '
                              f'"{REJECT}".',
                           fr=f'{path} : décision inconnue « {v} » ({where}). Décisions possibles : "", "{ACCEPT}", '
                              f'"{REJECT}".'))
    return v


def load(cfg: Config) -> Tracking:
    path = cfg.tracking / FILE
    if not path.is_file():
        return Tracking()
    text = path.read_text(encoding='utf-8')
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start again from scratch.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    m = cfg.method
    s = Tracking()
    for section in ('automatiques', 'importes'):
        d = raw.get(section, {})
        if d.get('sort', DELETE) != DELETE:
            raise SystemExit(L(en=f'{path}: [{section}] only knows sort = "{DELETE}". To keep these tags, '
                                  f'write decision = "{REJECT}".',
                               fr=f'{path} : [{section}] ne connaît que sort = "{DELETE}". Pour garder ces tags, '
                                  f'écrire decision = "{REJECT}".'))
        setattr(s, SECTIONS[section], _decision(d.get('decision', ''), f'[{section}]', path))
        # Summary written by the inventory under the section header, kept when a command rewrites the file.
        if section in raw and (r := re.search(rf'^\[{section}\][ \t]*\r?\n# (.*?)\r?$', text, re.M)):
            setattr(s, f'{SECTIONS[section]}_summary', r.group(1))
    for d in raw.get('tag', []):
        name = d.get('nom', '')
        if not name:
            raise SystemExit(L(en=f'{path}: a [[tag]] entry has no name.',
                               fr=f'{path} : une entrée [[tag]] n\'a pas de nom.'))
        action = d.get('sort', '')
        if action and norm(action) not in ACTIONS:
            raise SystemExit(L(en=f'{path}: unknown sort "{action}" for "{name}". Possible values: '
                                  f'{", ".join(ACTIONS.values())}.',
                               fr=f'{path} : sort inconnu « {action} » pour « {name} ». Sorts possibles : '
                                  f'{", ".join(ACTIONS.values())}.'))
        e = Entry(name, d.get('type', ''), int(d.get('effectif', 0)), int(d.get('dispersion', 0)),
                   list(d.get('themes', [])), d.get('theme', ''), list(d.get('recherches', [])),
                   ACTIONS[norm(action)] if action else '', d.get('cible', ''), _source(d.get('source', ZC), name, path),
                   d.get('classe', DOUBTFUL), _decision(d.get('decision', ''), name, path), d.get('note', ''),
                   list(d.get('variantes', [])))
        _check_target(e.action, e.target, e.decision, name, cfg, path)
        s.tags.append(e)
    for d in raw.get('variantes', []):
        names, target = list(d.get('noms', [])), d.get('cible', '')
        if not names or not target:
            raise SystemExit(L(en=f'{path}: a [[variantes]] group must have `noms` and a `cible` ({names}).',
                               fr=f'{path} : un groupe [[variantes]] doit avoir des `noms` et une `cible` ({names}).'))
        if privacy.excluded_tag(target, cfg):
            raise SystemExit(L(en=f'{path}: "{target}" is used by the privacy filter, it cannot be a target.',
                           fr=f'{path} : « {target} » sert au filtre de confidentialité, il ne peut pas être une '
                              'cible.'))
        s.variants.append(Variants(names, target, d.get('classe', DOUBTFUL), _source(d.get('source', ZC), target, path),
                                     _decision(d.get('decision', ''), target, path), d.get('note', '')))
    return s


def _source(v: str, name: str, path) -> str:
    if v not in (ZC, AGENT, USER):
        raise SystemExit(L(en=f'{path}: unknown source "{v}" for "{name}" ("{ZC}", "{AGENT}" or "{USER}").',
                           fr=f'{path} : source inconnue « {v} » pour « {name} » ("{ZC}", "{AGENT}" ou "{USER}").'))
    return v


def _check_target(action: str, target: str, decision: str, name: str, cfg: Config, path) -> None:
    m = cfg.method
    if action in (CONCEPT, STATUS, MERGE) and decision == ACCEPT and not target:
        raise SystemExit(L(en=f'{path}: "{name}" ({action}) is accepted without a target.',
                           fr=f'{path} : « {name} » ({action}) est accepté sans cible.'))
    if not target:
        return
    if privacy.excluded_tag(target, cfg):
        raise SystemExit(L(en=f'{path}: "{target}" is used by the privacy filter, it cannot be a target.',
                           fr=f'{path} : « {target} » sert au filtre de confidentialité, il ne peut pas être une '
                              'cible.'))
    if action == CONCEPT and m.concept_prefix and not target.startswith(m.concept_prefix):
        raise SystemExit(L(en=f'{path}: the target of the concept "{name}" must start with "{m.concept_prefix}" '
                              f'("{target}").',
                           fr=f'{path} : la cible du concept « {name} » doit commencer par « {m.concept_prefix} » '
                              f'(« {target} »).'))
    if action == STATUS and target not in (*m.statuses, *m.other_tags):
        raise SystemExit(L(en=f'{path}: "{target}", target of "{name}", is neither a status nor a mark of the '
                              f'method ({", ".join((*m.statuses, *m.other_tags))}).',
                           fr=f'{path} : « {target} », cible de « {name} », n\'est ni un état ni une marque de la '
                              f'méthode ({", ".join((*m.statuses, *m.other_tags))}).'))


def _titles(b: Library, u: Usage | None, hidden: set[str]) -> str:
    if u is None:
        return ''
    items = sorted((b.all_items[i] for i in u.items if b.all_items[i].key not in hidden), key=lambda e: norm(e.title))
    undated, untitled = L(en='n.d.', fr='s. d.'), L(en='untitled', fr='sans titre')
    return ' · '.join(L(en=f'{e.author or "?"} {year(e) or undated}, "{e.title[:60] or untitled}"',
                        fr=f'{e.author or "?"} {year(e) or undated}, « {e.title[:60] or untitled} »')
                      for e in items[:TITLES])


def write(cfg: Config, s: Tracking, b: Library) -> None:
    """Write `suivi/tags.toml`, and add to `suivi/rangement.toml` the items to file before deleting a tag
    that duplicates a theme (D154)."""
    u = usages(b, cfg)
    hidden = privacy.hidden_keys(b, cfg)

    def shown(name: str) -> str:
        return identifier(name) if name in u and u[name].confidential else name

    lines = [header(), '[automatiques]']
    if s.automatic_summary:
        lines.append(f'# {s.automatic_summary}')
    lines += [f'sort = "{DELETE}"', f'decision = {_toml(s.automatic)}', '']
    if s.imported_summary or s.imported:
        lines += ['[importes]'] + ([f'# {s.imported_summary}'] if s.imported_summary else [])
        lines += [f'sort = "{DELETE}"', f'decision = {_toml(s.imported)}', '']
    for e in s.tags:
        lines.append('[[tag]]')
        if t := _titles(b, u.get(e.name), hidden):
            lines.append(f'# {t}')
        lines += [f'nom = {_toml(shown(e.name))}', f'type = {_toml(e.type)}', f'effectif = {e.count}',
              f'dispersion = {e.dispersion}', f'themes = {_toml(e.themes)}']
        lines += [f'theme = {_toml(e.theme)}'] if e.theme else []
        lines += [f'recherches = {_toml(e.searches)}'] if e.searches else []
        lines += [f'variantes = {_toml([shown(n) for n in e.variants])}'] if e.variants else []
        lines += [f'sort = {_toml(e.action)}', f'cible = {_toml(e.target)}', f'source = {_toml(e.source)}',
              f'classe = {_toml(e.grade)}', f'decision = {_toml(e.decision)}']
        lines += [f'note = {_toml(e.note)}'] if e.note else []
        lines.append('')
    for g in s.variants:
        lines.append('[[variantes]]')
        lines.append('# ' + ' · '.join(f'{shown(n)} ({len(u[n].items)}, {type_shown(u[n].readable_type)})' if n in u
                                      else L(en=f'{shown(n)} (absent)', fr=f'{shown(n)} (absent)')
                                      for n in g.names))
        lines += [f'noms = {_toml([shown(n) for n in g.names])}', f'cible = {_toml(g.target)}',
              f'classe = {_toml(g.grade)}', f'source = {_toml(g.source)}', f'decision = {_toml(g.decision)}']
        lines += [f'note = {_toml(g.note)}'] if g.note else []
        lines.append('')
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    write_toml(cfg.tracking / FILE, lines)
    if s.pending:
        r.write(cfg, r.load(cfg) + s.pending, b, privacy.excluded_items(b, cfg))


# --- Decisions by command (D177) ------------------------------------------------

def _rule_names() -> dict[str, str]:
    return {'automatiques': L(en='for automatic tags', fr='des tags automatiques'),
            'importes': L(en='for imported keywords', fr='des mots-clés importés')}


def _quoted(names) -> str:
    """Names between quotes, in the style of the current language (« x », « y »)."""
    names = list(names)
    if lang.current() == 'en':
        return '"' + '", "'.join(names) + '"'
    return '«' + '», «'.join(f' {x} ' for x in names) + '»'


# Section of tags.toml -> attribute of `Tracking` (D209).
SECTIONS = {'automatiques': 'automatic', 'importes': 'imported'}


def _nfc(name: str) -> str:
    """Name compared under a single Unicode form, since the one the agent types may differ from the database's."""
    return unicodedata.normalize('NFC', name)


def _forms(names, a=None) -> str:
    """Names that display the same, told apart by their code points (`ascii`), under the identifier of a
    confidential tag when the analysis `a` is given."""
    def one(n: str) -> str:
        if a is not None and _displayed(a, n) != n:
            return _displayed(a, n)
        which = L(en=', composed form NFC', fr=', forme composée NFC') if n == _nfc(n) else (
            L(en=', decomposed form NFD', fr=', forme décomposée NFD') if n == unicodedata.normalize('NFD', n) else '')
        return L(en=f'"{n}" ({ascii(n)}{which})', fr=f'« {n} » ({ascii(n)}{which})')
    return ' ; '.join(one(n) for n in sorted(names, key=ascii))


def _indexer(pairs) -> dict[str, dict[str, list]]:
    """Objects (entries or groups) designated by each name, arranged by NFC form then by exact name."""
    index: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for name, o in pairs:
        listing = index[_nfc(name)][name]
        if all(x is not o for x in listing):
            listing.append(o)
    return index


def _designated(name: str, index, path) -> list:
    """Objects designated by `name`, under its exact form first. Otherwise under its NFC form, since the agent may type
    a different form from the file's, provided it does not designate different objects under several Unicode
    forms, since they display the same and judging one must not judge the other."""
    forms = index.get(_nfc(name), {})
    if name in forms:
        return forms[name]
    objects = {id(o): o for listing in forms.values() for o in listing}
    if len({frozenset(map(id, listing)) for listing in forms.values()}) > 1:
        raise SystemExit(L(en=f'"{name}" designates several names of {path} that differ only by their Unicode form '
                              f'and display the same, {_forms(forms)}. Give the name in its exact form, copied from '
                              'the file.',
                           fr=f'« {name} » désigne plusieurs noms de {path} qui ne diffèrent que par leur forme '
                              f'Unicode et s\'affichent pareil, {_forms(forms)}. Donner le nom sous sa forme exacte, '
                              'copiée depuis le fichier.'))
    return list(objects.values())


def _action(v: str) -> str:
    if norm(v) not in ACTIONS:
        raise SystemExit(L(en=f'Unknown sort "{v}". Possible values: {", ".join(ACTIONS.values())}.',
                           fr=f'Sort inconnu « {v} ». Sorts possibles : {", ".join(ACTIONS.values())}.'))
    return ACTIONS[norm(v)]


def decide(s: Tracking, cfg: Config, decision: str, names=(), variants=(), obvious: bool = False, except_=(),
            rules=(), action: str = '', target: str = '') -> int:
    """Decisions taken by command (D177, modelled on D172), instead of writing the file by hand. `names`
    designates [[tag]] entries by their name, `variants` [[variantes]] groups by their target or one of their
    names, `rules` the [automatiques] and [importes] sections. `obvious` accepts all the entries and all the
    obvious groups still to judge, except the names in `except_`. `action` and `target` change the proposal of the
    given entries (which switch to source « agent »), `target` that of the groups. Only rules still to judge
    change. Returns the number of decisions written."""
    path = cfg.tracking / FILE
    n = 0
    for section in rules:
        what = _rule_names()[section]
        if section == 'importes' and not s.imported_summary and not s.imported:
            raise SystemExit(L(en=f'{path} has no [importes] section: no item carries imported keywords.',
                               fr=f'{path} n\'a pas de section [importes] : aucune fiche ne porte de mots-clés '
                                  'importés.'))
        if getattr(s, SECTIONS[section]):
            current = getattr(s, SECTIONS[section])
            raise SystemExit(L(en=f'The rule {what} is already decided ("{current}") in {path}. To go back on it, '
                                  f'change decision by hand in the [{section}] section.',
                               fr=f'La règle {what} est déjà décidée (« {current} ») dans {path}. Pour revenir '
                                  f'dessus, changer decision à la main dans la section [{section}].'))
        setattr(s, SECTIONS[section], decision)
        n += 1

    all_entries = {_nfc(e.name) for e in s.tags} | {_nfc(x) for g in s.variants for x in (g.target, *g.names)}
    tag_index = _indexer((e.name, e) for e in s.tags)
    group_index = _indexer((x, g) for g in s.variants for x in dict.fromkeys((g.target, *g.names)))

    def to_judge(name: str, index) -> list:
        return [o for o in _designated(name, index, path) if not o.decision]

    def reject_unknown(requested, index, what: str, other=None, elsewhere: str = '') -> None:
        unknowns = [x for x in requested if not to_judge(x, index)]
        if not unknowns:
            return
        chunks = []
        if other is not None and (misplaced := [x for x in unknowns if to_judge(x, other)]):
            quoted = _quoted(misplaced)
            chunks.append(L(en=f'{quoted} designates {elsewhere}.', fr=f'{quoted} désigne {elsewhere}.'))
            unknowns = [x for x in unknowns if x not in misplaced]
        missing = _quoted(x for x in unknowns if _nfc(x) not in all_entries)
        decided_names = _quoted(x for x in unknowns if _nfc(x) in all_entries)
        if any(_nfc(x) not in all_entries for x in unknowns):
            chunks.append(L(en=f'{missing} is not in {path} ({what}). Check the name, in full and between quotes '
                               '(unprotected, a name that starts with # is taken for a comment), or run '
                               '`zc tags inventory` again. A tag with no entry is added by `zc tags add`.',
                            fr=f'{missing} ne figure pas dans {path} ({what}). Vérifier le nom, en entier et entre '
                               'guillemets (non protégé, un nom qui commence par # est pris pour un commentaire), ou '
                               'relancer `zc tags inventory`. Un tag sans entrée s\'ajoute par `zc tags add`.'))
        if any(_nfc(x) in all_entries for x in unknowns):
            chunks.append(L(en=f'{decided_names}: nothing to judge under this name ({what}), the decision is already '
                               'taken. A decision already taken is changed by hand in the file.',
                            fr=f'{decided_names} : rien à juger sous ce nom ({what}), la décision est déjà prise. Une '
                               'décision prise se change à la main dans le fichier.'))
        raise SystemExit(' '.join(chunks))

    reject_unknown(names, tag_index, L(en='[[tag]] entries', fr='entrées [[tag]]'), group_index,
                   L(en='a [[variantes]] group to judge, to give after --variants',
                     fr='un groupe [[variantes]] à juger, à donner après --variants'))
    reject_unknown(variants, group_index, L(en='[[variantes]] groups', fr='groupes [[variantes]]'), tag_index,
                   L(en='a [[tag]] entry to judge, to give without --variants',
                     fr='une entrée [[tag]] à juger, à donner sans --variants'))
    # `except_` excludes under the NFC form, all forms combined, since excluding too much only leaves more to judge.
    reject_unknown([x for x in except_ if _nfc(x) not in all_entries], {},
                   L(en='names of tags and groups', fr='noms de tags et de groupes'))
    action = _action(action) if action else ''

    seen_set: set[int] = set()
    for name in names:
        for e in to_judge(name, tag_index):
            if id(e) in seen_set:
                continue
            seen_set.add(id(e))
            if action or target:
                if action and action != e.action:
                    e.action, e.target = action, ''
                e.target = target or e.target
                e.source = AGENT if e.source == ZC else e.source
            if decision == ACCEPT and not e.action:
                raise SystemExit(L(en=f'"{e.name}" has no proposed sort. Give it with --action.',
                                   fr=f'« {e.name} » n\'a pas de sort proposé. Le donner avec --action.'))
            e.decision = decision
            _check_target(e.action, e.target, e.decision, e.name, cfg, path)
            n += 1
    for name in variants:
        for g in to_judge(name, group_index):
            if id(g) in seen_set:
                continue
            seen_set.add(id(g))
            if target:
                if privacy.excluded_tag(target, cfg):
                    raise SystemExit(L(en=f'"{target}" is used by the privacy filter, it cannot be a target.',
                                       fr=f'« {target} » sert au filtre de confidentialité, il ne peut pas être une '
                                          'cible.'))
                g.target, g.source = target, AGENT if g.source == ZC else g.source
            g.decision = decision
            n += 1
    if obvious:
        skipped = {_nfc(x) for x in except_}
        for e in s.tags:
            if e.grade == OBVIOUS and not e.decision and e.action and _nfc(e.name) not in skipped:
                e.decision = ACCEPT
                _check_target(e.action, e.target, e.decision, e.name, cfg, path)
                n += 1
        for g in s.variants:
            if g.grade == OBVIOUS and not g.decision and not {_nfc(x) for x in (g.target, *g.names)} & skipped:
                g.decision = ACCEPT
                n += 1
    return n


def add(s: Tracking, cfg: Config, b: Library, names, action: str, target: str = '',
            user: bool = False) -> int:
    """New [[tag]] entries, already accepted, for tags the inventory did not propose (tags outside the families
    flagged by the Inbox triage, translations, protected tag at the user's request). Source « agent », or
    « utilisateur », the only source that changes a protected or confidential tag (D151, D156). Returns their number."""
    path = cfg.tracking / FILE
    a = _Analysis(b, cfg)
    action = _action(action)
    already = {e.name for e in s.tags}
    for name in names:
        # Real name carried in the library, which may have another Unicode form than the typed name. Recording the
        # typed name would give an accepted rule that applies to nothing.
        real = _real(a, name)
        tracked_name = _displayed(a, real)  # identifier for a confidential tag, as in the re-read file
        if tracked_name in already:
            raise SystemExit(L(en=f'"{name}" already has a [[tag]] entry in {path}. Judge it with `zc tags accept` '
                                  'or `zc tags reject`.',
                               fr=f'« {name} » a déjà une entrée [[tag]] dans {path}. La juger avec `zc tags accept` '
                                  'ou `zc tags reject`.'))
        e = a.stats(Entry(real), a.u[real])
        e.name, e.action, e.target, e.decision = tracked_name, action, target, ACCEPT
        e.source = USER if user else AGENT
        _check_target(e.action, e.target, e.decision, tracked_name, cfg, path)
        s.tags.append(e)
        already.add(tracked_name)
    s.tags.sort(key=lambda e: norm(e.name))
    return len(names)


def _real(a: '_Analysis', name: str) -> str:
    """Library tag designated by `name` (or by the identifier of a confidential tag), under its exact form
    first, otherwise under its NFC form if only one tag matches."""
    if (n := a.real(name)) in a.u:
        return n
    forms = [n for n in a.u if _nfc(n) == _nfc(name)]
    if not forms:
        raise SystemExit(L(en=f'No tag "{name}" in the library. Check the name, in full and between quotes.',
                           fr=f'Aucun tag « {name} » dans la bibliothèque. Vérifier le nom, en entier et entre '
                              'guillemets.'))
    if len(forms) > 1:
        raise SystemExit(L(en=f'"{name}" designates several tags of the library that differ only by their Unicode '
                              f'form and display the same, {_forms(forms, a)}. Give the name in its exact form, '
                              'copied from the inventory report or from Zotero.',
                           fr=f'« {name} » désigne plusieurs tags de la bibliothèque qui ne diffèrent que par leur '
                              f'forme Unicode et s\'affichent pareil, {_forms(forms, a)}. Donner le nom sous sa '
                              'forme exacte, copiée depuis le rapport de l\'inventaire ou depuis Zotero.'))
    return forms[0]


# --- Analysis ----------------------------------------------------------------------

class _Analysis:
    """Usages and classifications of the library, shared by the inventory, the rules and the plan."""

    def __init__(self, b: Library, cfg: Config):
        self.b, self.cfg = b, cfg
        m = cfg.method
        self.u = usages(b, cfg)
        self.hidden = privacy.hidden_keys(b, cfg)
        self.by_identifier = {identifier(n): n for n, x in self.u.items() if x.confidential}
        self.excluded = privacy.excluded_tags(cfg)
        self.colors = {n for n, _ in b.colors}
        self.statuses = list(m.statuses)
        subjects_toml = cfg.tracking / f.FILE
        self.linked = f.load_tracking(cfg).tags if subjects_toml.is_file() else {}
        plan_path = cfg.workspace / f.OUTLINE
        self.plan = f.read_outline(plan_path.read_text(encoding='utf-8'), cfg) if plan_path.is_file() else None
        self.filing = r.load(cfg) if (cfg.tracking / r.FILE).is_file() else []
        self.waiting = set()  # tags on which a pending filing proposal rests (D156)
        for x in self.filing:
            if x.decision == '' and x.source == r.TAG and (t := re.search(r'tag « (.+?) »', x.note)):
                self.waiting.add(t.group(1))
        # Themes: collections under the root of the fonds and paths of plan.md, by form of the last name.
        e = r._State(b)
        self.state = e
        root = e.root(m.subjects) if m.subjects else None
        self.subjects_root = root
        _, covered = f.excluded_collections(b, cfg)
        concealed_keys = {b.collections[c].key for c in covered}
        paths = {e.path(k).split('/', 1)[1] for k in e.name
                   if root and k != root and e.under(k, root) and k not in concealed_keys}
        if self.plan:
            paths |= set(self.plan.nodes)
        self.themes_by_form = {form(c.rsplit('/', 1)[-1], cfg): c for c in sorted(paths, key=len, reverse=True)}
        self.batch, self.imported = self._batches()
        self.combined_usages: dict[str, Usage] = {}  # target of a variants group -> combined usage
        self.strong = {n for n, u in self.u.items() if 0 in u.types and n not in self.imported}
        self.concepts = {n for n in self.strong if self.is_concept(n)} | set(outline_concepts(cfg))
        self.reference_forms = ({form(n, cfg) for n in self.strong} | {form(c, cfg) for c in self.concepts}
                                 | set(self.themes_by_form))
        self.concept_theme_forms = {form(c, cfg) for c in self.concepts} | set(self.themes_by_form)
        self.foreign_statuses = {}
        for table, names in ((FOREIGN_STATUSES, m.statuses), (FOREIGN_MARKS, m.other_tags)):
            for i, alias in table.items():
                if i < len(names):
                    for a in alias:
                        self.foreign_statuses.setdefault(form(a, cfg), names[i])

    def real(self, name: str) -> str:
        """Real name of a tag designated by its confidential identifier, or the name as it is."""
        return self.by_identifier.get(name, name)

    def is_concept(self, name: str) -> bool:
        p = self.cfg.method.concept_prefix
        return bool(p) and name.startswith(p) and len(name) > len(p)

    def protection(self, name: str) -> str:
        """Reason why a tag is protected (D151), empty otherwise."""
        m = self.cfg.method
        if privacy.form(name) in self.excluded:
            return L(en='privacy filter, never changes', fr='filtre de confidentialité, ne change jamais')
        if m.technical_prefix and name.startswith(m.technical_prefix):
            return L(en='technical tag', fr='tag technique')
        if name in m.statuses:
            return L(en='status of the method', fr='état de la méthode')
        if name in m.other_tags:
            return L(en='mark of the method', fr='marque de la méthode')
        if name in self.colors:
            return L(en='colored tag', fr='tag coloré')
        if name in self.cfg.tags.protected:
            return L(en='list [tags] proteges', fr='liste [tags] proteges')
        if name in self.waiting:
            return L(en='filing proposal pending', fr='proposition de rangement en attente')
        return ''

    def outside_families(self, name: str) -> bool:
        return not self.is_concept(name) and not self.protection(name)

    def _batches(self) -> tuple[set[int], set[str]]:
        """Items that carry more than `seuil_mots_cles` manual tags outside the families, mostly rare, and names whose
        manual occurrences are all on those items (D153). Annotations never enter."""
        t = self.cfg.tags
        batch = set()
        for el in self.b.items:
            if el.key in self.hidden:
                continue
            outside = {n for n, typ in el.tags if typ == 0 and self.outside_families(n)}
            if len(outside) > t.keywords_threshold:
                rare = sum(1 for n in outside if len(self.u[n].items) < t.candidate_threshold)
                if 2 * rare > len(outside):
                    batch.add(el.id)
        imported = set()
        for n, u in self.u.items():
            if 0 not in u.types or u.confidential or not self.outside_families(n):
                continue
            manual_tags = {i for i in u.all_items if (n, 0) in self.b.all_items[i].tags}
            if manual_tags and manual_tags <= batch:
                imported.add(n)
        return batch, imported

    def is_candidate(self, name: str) -> bool:
        """Exception proposed to the global rule (D152): carried enough, or of the same form as a manual tag, a concept
        or a theme."""
        u = self.u[name]
        if len(u.items) >= self.cfg.tags.candidate_threshold:
            return True
        others = {form(n, self.cfg) for n in self.strong if n != name} | self.concept_theme_forms
        return form(name, self.cfg) in others

    def resembles(self, name: str) -> bool:
        """Resemblance to a concept or a theme, which prevents classing a tag to delete as « évident »."""
        fo = form(name, self.cfg)
        for other in self.concept_theme_forms:
            if fo == other or fo in other or other in fo:
                return True
            s = SequenceMatcher(None, fo, other)
            if s.real_quick_ratio() >= 0.8 and s.quick_ratio() >= 0.8 and s.ratio() >= 0.8:
                return True
        return False

    # Variants.

    def groups(self) -> tuple[list[Variants], list[list[str]]]:
        """Proposed variants groups, and groups set aside because they gather several protected tags."""
        by_form: dict[str, list[str]] = defaultdict(list)
        for n, u in self.u.items():
            if not u.confidential and privacy.form(n) not in self.excluded:
                by_form[form(n, self.cfg)].append(n)
        res, skipped = [], []
        for fo, names in sorted(by_form.items()):
            if len(names) < 2:
                continue
            names.sort(key=lambda n: (-len(self.u[n].items), n))
            items = set().union(*(self.u[n].items for n in names))
            if not (any(n in self.strong for n in names) or len(items) >= self.cfg.tags.candidate_threshold
                    or fo in self.concept_theme_forms):
                continue  # automatic or imported only, and rare: the global rule takes care of them
            protected = [n for n in names if self.protection(n)]
            if len(protected) > 1:
                skipped.append(names)
                continue
            target = protected[0] if protected else self._winner(names)
            is_obvious = len({weak_form(n, self.cfg) for n in names}) == 1
            res.append(Variants(names, target, OBVIOUS if is_obvious else DOUBTFUL,
                                 note='' if is_obvious else L(en='plural or a difference other than case and accents',
                                                              fr='pluriel ou autre différence que la casse et les accents')))
        return res, skipped

    def _winner(self, names: list[str]) -> str:
        """The concept, then the most carried manual tag, then the accented lowercase form (D156). As soon as one of the
        names is written in lowercase, the target is too, so that targets follow one casing (« #Mémoire »
        and « #memoire » give « #mémoire »). Capitals stay only if all the names have them (proper noun)."""
        def weight(n):
            return len(self.u[n].items), not n.isascii(), n == n.lower(), n
        concepts = [n for n in names if self.is_concept(n)]
        strong = [n for n in names if n in self.strong]
        if concepts:
            winner = max(concepts, key=weight)
        elif strong:
            winner = max(strong, key=weight)
        else:
            return max(names, key=lambda n: (not n.isascii(), len(self.u[n].items), n)).lower()
        return winner.lower() if any(n == n.lower() for n in names) else winner

    # [[tag]] entries.

    def combined(self, names: list[str]) -> Usage:
        """Combined usage of the names of a variants group, carried by its target once the group is merged."""
        c = Usage(names[-1])
        for n in dict.fromkeys(names):
            x = self.u.get(n)
            if x is None:
                continue
            c.types |= x.types
            c.occurrences.update(x.occurrences)
            c.all_items |= x.all_items
            c.items |= x.items
            c.children += x.children
            c.annotations += x.annotations
            c.searches += [srch for srch in x.searches if srch not in c.searches]
        themes = themes_of_items(self.b, self.cfg) if c.items else {}
        for item in c.items:
            c.themes.update(themes.get(item, ()))
        return c

    def entries(self, groups: list[Variants]) -> list[Entry]:
        in_groups = {n for g in groups for n in g.names if n != g.target}
        self.combined_usages = {g.target: self.combined([*g.names, g.target]) for g in groups}
        res = []
        for n in sorted(set(self.u) | set(self.combined_usages), key=norm):
            u = self.combined_usages.get(n) or self.u[n]
            # A tag protected only by a filing proposal keeps its entry, which awaits that filing.
            if u.confidential or n in in_groups or self.is_concept(n) or (self.protection(n) and n not in self.waiting):
                continue
            state = self.foreign_statuses.get(form(n, self.cfg)) if 0 in u.types else None
            if state and state != n:
                e = self.stats(Entry(n), u)
                e.action, e.target = STATUS, state
                e.note = L(en='status or mark from another habit, to confirm',
                           fr="état ou marque venu d'une autre habitude, à confirmer")
                res.append(e)
                continue
            if n not in self.combined_usages and (u.types == {1} or n in self.imported) and not self.is_candidate(n) \
                    and not u.searches:
                continue  # removed by the global rule, without review
            res.append(self.propose(self.stats(Entry(n), u), u))
        return res

    def stats(self, e: Entry, u: Usage | None = None) -> Entry:
        u = u or self.u.get(e.name)
        if u is None:
            e.count, e.dispersion, e.themes, e.searches = 0, 0, [], []
            return e
        e.type = u.readable_type + (', importé' if e.name in self.imported else '')
        e.count, e.dispersion = len(u.items), u.dispersion
        e.themes = [t for t, _ in u.themes.most_common(3)]
        e.searches = list(u.searches)
        return e

    def propose(self, e: Entry, u: Usage | None = None) -> Entry:
        n, u, cfg = e.name, u or self.u[e.name], self.cfg
        theme_same_name = self.themes_by_form.get(form(n, cfg))
        if n in self.linked:
            e.action, e.theme = DELETE, self.linked[n]
            e.note = L(en=f'linked to the theme "{e.theme}" in suivi/fonds.toml, it duplicates it',
                       fr=f'relié au thème « {e.theme} » dans suivi/fonds.toml, il le double')
        elif theme_same_name:
            e.action, e.theme = DELETE, theme_same_name
            e.note = L(en=f'same name as the theme "{e.theme}", it duplicates it',
                       fr=f'même nom que le thème « {e.theme} », il le double')
        elif _technical_mark(n, cfg):
            e.action, e.grade = DELETE, OBVIOUS
            e.note = L(en='technical mark of an application ("/unread", "_tablet"…), not a notion',
                       fr="marque technique d'une application (« /unread », « _tablet »…), pas une notion")
        elif len(u.all_items) == 1 and 0 in u.types and not u.annotations and not u.searches and not self.resembles(n):
            e.action, e.grade = DELETE, OBVIOUS
            e.note = L(en='carried by a single item, with no resemblance to a concept or a theme',
                       fr='porté par une seule fiche, sans ressemblance avec un concept ou un thème')
        elif u.dispersion >= cfg.tags.concept_dispersion:
            e.action, e.target = CONCEPT, concept_name(n, cfg)
            e.note = L(en=f'spread over {u.dispersion} themes of the subjects, name to check (lowercase except '
                          "proper nouns, in the user's language) and definition to propose",
                       fr=f'réparti sur {u.dispersion} thèmes du fonds, nom à vérifier (minuscules sauf nom propre, '
                          "dans la langue de l'utilisateur) et définition à proposer")
        elif u.dispersion == 1 and (filed := next(iter(u.themes.values()))) >= 2 and 2 * filed >= len(u.items):
            # Concentrated: at least two items filed in the theme, and at least half of those that carry the tag
            # (D241, a single filed item out of three made a mark look like a theme).
            e.action, e.theme = DELETE, next(iter(u.themes))
            e.note = L(en=f'concentrated in the theme "{e.theme}", it duplicates it',
                       fr=f'concentré dans le thème « {e.theme} », il le double')
        elif u.types == {0, 1}:
            e.action, e.target = MERGE, n
            e.note = L(en='also carried as manual, its automatic occurrences would become manual',
                       fr='porté aussi en manuel, ses occurrences automatiques deviendraient manuelles')
        elif u.types == {1} or n in self.imported:
            e.action = DELETE
            e.note = L(en='the global rule would remove it without this exception',
                       fr='la règle globale le retirerait sans cette exception')
        if u.searches:
            e.note = (e.note + '. ' if e.note else '') + L(en='cited by a saved search',
                                                          fr='cité par une recherche enregistrée')
            e.grade = DOUBTFUL
        return e

    def outside_theme(self, name: str, theme: str, others=()) -> set[int]:
        """Items that carry `name` (or one of the `others` names brought back to it) without yet being in `theme` or
        one of its subthemes."""
        items = set()
        for n in (name, *others):
            if (u := self.combined_usages.get(n) or self.u.get(n)) is not None:
                items |= u.items
        if self.subjects_root is None:
            return items
        e = self.state
        res = set()
        for i in items:
            el = self.b.all_items[i]
            paths = [e.path(e.key[c]).split('/', 1)[1] for c in el.collections
                       if e.key[c] != self.subjects_root and e.under(e.key[c], self.subjects_root)]
            if not any(c == theme or c.startswith(theme + '/') for c in paths):
                res.add(i)
        return res

    def filing_proposals(self, s: Tracking) -> list[r.Entry]:
        """Items of a tag that duplicates a theme, absent from that theme, proposed for filing (D154, D116)."""
        if not self.plan or self.subjects_root is None:
            return []
        e = self.state
        already = {x.key for x in self.filing}
        inbox = e.root(self.cfg.method.inbox) if self.cfg.method.inbox else None
        res = []
        for x in s.tags:
            if x.action != DELETE or not x.theme or x.decision == REJECT or x.theme not in self.plan.nodes:
                continue
            u = self.combined_usages.get(x.name) or self.u.get(x.name)
            if u is None or u.confidential:
                continue
            for i in sorted(u.items, key=lambda i: self.b.all_items[i].key):
                el = self.b.all_items[i]
                if el.key in already or el.key in self.hidden:
                    continue
                paths = [e.path(e.key[c]).split('/', 1)[1] for c in el.collections
                           if e.key[c] != self.subjects_root and e.under(e.key[c], self.subjects_root)]
                if any(c == x.theme or c.startswith(x.theme + '/') for c in paths):
                    continue
                origin = next((e.key[c] for c in el.collections if inbox and e.under(e.key[c], inbox)), '')
                res.append(r.Entry(el.key, r.MOVE if origin else r.ADD, x.theme, origin, r.TAG, '',
                                    f'tag « {x.name} »'))
                already.add(el.key)
        return res


def bring_up_to_date(old: Tracking, detected: Tracking, a: _Analysis) -> Tracking:
    """Keeps the decisions and entries of the agent or the user, renews zc proposals still
    pending, removes those whose tags have vanished. A decided rule stays, for the triage of future references."""
    s = Tracking(old.automatic, old.imported)
    kept = {e.name: e for e in old.tags if e.decision or e.source != ZC}
    seen_set = set()
    for e in old.tags:
        if e.name in kept and e.name not in seen_set:
            name = a.real(e.name)
            ref = a.stats(Entry(name), a.combined_usages.get(name))
            e.type = ref.type or e.type
            e.count, e.dispersion, e.themes, e.searches = ref.count, ref.dispersion, ref.themes, ref.searches
            s.tags.append(e)
            seen_set.add(e.name)
    s.tags += [e for e in detected.tags if e.name not in kept]
    s.tags.sort(key=lambda e: norm(e.name))

    settled = [g for g in old.variants if g.decision or g.source != ZC]
    s.variants = list(settled)
    for d in detected.variants:
        covered_names = set()
        target = d.target
        for g in settled:
            members = set(g.names) | {g.target}
            if members & set(d.names):
                covered_names |= members
                target = g.target
        rest = [n for n in d.names if n not in covered_names]
        if not rest:
            continue
        if covered_names:
            d = Variants([*rest, *([target] if target in a.u and target not in rest else [])], target, d.grade,
                          note=L(en='new names for a form already judged', fr='nouveaux noms pour une forme déjà jugée'))
        s.variants.append(d)
    return s


def fold(s: Tracking) -> list[Variants]:
    """Merges into the [[tag]] entry of its target a variants group proposed by zc toward a name that zc proposes to
    delete, so as not to propose both bringing names back to a tag and deleting that tag. The names of the group
    go into `variants` of the entry, deleted with it. Returns the removed groups."""
    by_name = {e.name: e for e in s.tags}
    covered_names = {v for e in s.tags for v in e.variants}
    keepers, folded = [], []
    for g in s.variants:
        if g.source != ZC or g.decision:
            keepers.append(g)
            continue
        others = [n for n in g.names if n != g.target and n not in covered_names]
        e = by_name.get(g.target)
        if not others:
            folded.append(g)  # already merged into a [[tag]] entry
        elif e is not None and e.action == DELETE and not e.decision and e.source == ZC:
            e.variants += [n for n in others if n not in e.variants]
            covered_names |= set(others)
            folded.append(g)
        else:
            if e is not None and e.action == DELETE and e.decision == ACCEPT:
                g.note = (g.note + '. ' if g.note else '') + L(
                    en=f'"{g.target}" is already deleted by an accepted rule, accepting this group deletes these '
                       'names too',
                    fr=f'« {g.target} » est déjà supprimé par une règle acceptée, accepter ce groupe supprime aussi '
                       'ces noms')
            keepers.append(g)
    s.variants = keepers
    return folded


# --- Inventory -------------------------------------------------------------------

def inventory(b: Library, cfg: Config, day: date | None = None) -> tuple[str, Tracking]:
    """Inventory report and updated tracking (to be written by `write`), read-only."""
    a = _Analysis(b, cfg)
    groups, skipped = a.groups()
    detected = Tracking(tags=a.entries(groups), variants=groups)
    tracking = bring_up_to_date(load(cfg), detected, a)
    folded = fold(tracking)
    tracking.pending = a.filing_proposals(tracking)
    a.waiting |= {x.note[len('tag « '):-len(' »')] for x in tracking.pending}

    # What the global rules would remove, once accepted, with the pending exceptions.
    simulated = _rules(a, tracking, simulate=True)
    removed: dict[str, Counter] = {'automatique': Counter(), 'importé': Counter()}
    for el in b.all_items.values():
        for name, kind in _compute_target(el.tags, el.type == 'annotation', simulated, el.id).removed:
            if kind in removed:
                removed[kind][name] += 1
    autos = {n: u for n, u in a.u.items() if 1 in u.types}
    auto_occurrences = sum(u.occurrences[1] for u in autos.values())
    names_count = plural(len(autos), en='automatic name', fr='nom')
    removed_names, removed_occurrences = len(removed['automatique']), sum(removed['automatique'].values())
    tracking.automatic_summary = L(
        en=f"{names_count}, {auto_occurrences} occurrence(s). The rule removes {removed_names} name(s) and "
           f"{removed_occurrences} occurrence(s), the exceptions are in the pending [[tag]] and [[variantes]].",
        fr=f"{names_count} automatique(s), {auto_occurrences} occurrence(s). La règle en retire "
           f"{removed_names} nom(s) et {removed_occurrences} occurrence(s), les "
           'exceptions sont dans les [[tag]] et [[variantes]] en attente.')
    if a.batch:
        items_count = plural(len(a.batch), en='item', fr='fiche')
        imported_names, imported_occurrences = len(removed['importé']), sum(removed['importé'].values())
        tracking.imported_summary = L(
            en=f"{items_count} with more than {cfg.tags.keywords_threshold} manual tags outside the families, "
               f"mostly rare (imported keywords). {imported_names} name(s) and {imported_occurrences} "
               "occurrence(s) removed if the rule is accepted.",
            fr=f"{items_count} porte(nt) plus de {cfg.tags.keywords_threshold} tags manuels hors familles, "
               f"rares pour la plupart (mots-clés importés). {imported_names} nom(s) et "
               f"{imported_occurrences} occurrence(s) retirés si la règle est acceptée.")
    groups = [g for g in groups if not any(g is x for x in folded)]
    return _inventory_report(a, tracking, groups, skipped, removed, day or date.today(), len(folded)), tracking


def _inventory_report(a: _Analysis, s: Tracking, groups: list[Variants], skipped: list[list[str]],
                        removed: dict[str, Counter], day: date, folded: int = 0) -> str:
    b, cfg, u = a.b, a.cfg, a.u
    public = {n: x for n, x in u.items() if not x.confidential}
    occurrences = sum(sum(x.occurrences.values()) for x in u.values())
    manual_tags = sum(1 for x in u.values() if 0 in x.types)
    autos = sum(1 for x in u.values() if 1 in x.types)
    names = plural(len(u), en='tag name', fr='nom')
    lines = [L(en=f'# Tag inventory, {day:%d/%m/%Y}', fr=f'# Inventaire des tags, {day:%d/%m/%Y}'), '',
             L(en="Read-only, nothing was changed. The rules to judge are in `suivi/tags.toml`, which keeps the "
                  "decisions from one run to the next. `zc tags plan` applies the accepted rules.",
               fr="Lecture seule, rien n'a été modifié. Les règles à juger sont dans `suivi/tags.toml`, qui garde les "
                  "décisions d'une fois sur l'autre. `zc tags plan` applique les règles acceptées."), '',
             L(en=f"{names}, {occurrences} occurrence(s) on items, attachments, notes and annotations (trash "
                  f"excluded). {manual_tags} name(s) set as manual, {autos} as automatic (publishers' keywords, "
                  "added by Zotero).",
               fr=f"{names}, {occurrences} occurrence(s) sur les fiches, pièces jointes, notes et "
                  f"annotations (corbeille exclue). {manual_tags} nom(s) posé(s) en manuel, {autos} en automatique "
                  '(mots-clés des éditeurs, ajoutés par Zotero).')]

    current = s.automatic or L(en='to be taken', fr='à prendre')
    lines += ['', L(en='## Global rule on automatic tags', fr='## Règle globale des tags automatiques'), '',
              s.automatic_summary,
              L(en=f'Current decision: "{current}". A single approval is enough. The exceptions are the automatic '
                   f'tags carried by at least {cfg.tags.candidate_threshold} items or of the same form as a manual '
                   'tag, a concept or a theme. Protected tags and those cited by a saved search escape it.',
                fr=f"Décision actuelle : « {current} ». Une seule approbation suffit. Les exceptions sont "
                   f"les tags automatiques portés par au moins {cfg.tags.candidate_threshold} fiches ou de même "
                   "forme qu'un tag manuel, un concept ou un thème. Les tags protégés et ceux cités par une "
                   'recherche enregistrée y échappent.')]
    if removed['automatique']:
        most = ', '.join(f'{_displayed(a, n)} ({k})' for n, k in removed['automatique'].most_common(15))
        lines += ['', L(en=f'The most carried among the removed names: {most}.',
                        fr=f'Les plus portés parmi les noms retirés : {most}.')]

    if a.batch:
        current = s.imported or L(en='to be taken', fr='à prendre')
        lines += ['', L(en='## Keywords imported as manual tags', fr='## Mots-clés importés en tags manuels'), '',
                  s.imported_summary,
                  L(en=f'Current decision: "{current}". Examples of items:',
                    fr=f'Décision actuelle : « {current} ». Exemples de fiches :'), '']
        for i in sorted(a.batch, key=lambda i: norm(b.all_items[i].title))[:10]:
            el = b.all_items[i]
            outside = [n for n, t in el.tags if t == 0 and n in a.imported]
            some = ', '.join(outside[:6])
            lines.append(L(en=f'- {el.key} · {_line(el)} · {len(outside)} tags, including {some}',
                           fr=f'- {el.key} · {_line(el)} · {len(outside)} tags, dont {some}'))

    obvious = [g for g in groups if g.grade == OBVIOUS]
    groups_count = plural(len(groups), en='group', fr='groupe')
    lines += ['', L(en='## Variants', fr='## Variantes'), '',
              L(en=f"{groups_count} of names of the same form, {len(obvious)} of them obvious (case, accents, "
                   "spaces, hyphens or prefix only, to approve in bulk) and the others doubtful (plural, by "
                   "bundles of 10). The target follows the fixed rule (concept, then the most carried manual tag, "
                   "then the accented lowercase form). Translations are not detected, the agent can propose some.",
                fr=f"{groups_count} de noms de même forme, dont {len(obvious)} évident(s) (casse, accents, "
                   "espaces, tirets ou préfixe seulement, à approuver en bloc) et les autres douteux (pluriel, par "
                   "paquets de 10). La cible suit la règle fixe (concept, puis tag manuel le plus porté, puis forme "
                   "en minuscules accentuée). Les traductions ne sont pas repérées, l'agent peut en proposer."), '']
    lines += [L(en=f"- {grade_shown(g.grade)}: {' / '.join(_displayed(a, n) for n in g.names)} → {g.target}",
                fr=f"- {grade_shown(g.grade)} : {' / '.join(_displayed(a, n) for n in g.names)} → {g.target}")
              for g in groups]
    if folded:
        others_count = plural(folded, en='other group', fr='autre groupe')
        lines += ['', L(en=f"{others_count} gathered into the `[[tag]]` entry of their target, which zc proposes to "
                           "delete (`variantes` field). Accepting the entry deletes these names too, keeping it "
                           "brings them back to it.",
                        fr=f"{others_count} réuni(s) à l'entrée `[[tag]]` de sa cible, que zc propose de "
                           "supprimer (champ `variantes`). Accepter l'entrée supprime aussi ces noms, la garder les y "
                           "ramène.")]
    if skipped:
        lines += ['', L(en='Groups that gather several protected tags, left aside (to settle in Zotero, '
                           '"Rename Tag…"):',
                        fr='Groupes qui réunissent plusieurs tags protégés, laissés de côté (à régler dans Zotero, '
                           '« Renommer le tag… ») :'), '']
        lines += [f"- {' / '.join(n)}" for n in skipped]

    def section(title: str, text: str, entries: list[Entry]):
        if entries:
            lines.extend(['', f'## {title}', '', text, ''])
            lines.extend(_entry_line(e) for e in entries)

    waiting = [e for e in s.tags if not e.decision]
    section(L(en='Statuses and marks from other habits', fr="États et marques venus d'autres habitudes"),
            L(en='Matched to the statuses and marks of the method by a small dictionary. Nothing is done '
                 'automatically. An item that would receive two statuses keeps the most advanced.',
              fr="Rapprochés des états et marques de la méthode par un petit dictionnaire. Rien d'office. Une fiche "
                 'qui recevrait deux états garde le plus avancé.'),
            [e for e in waiting if e.action == STATUS])
    section(L(en='Proposed concepts', fr='Concepts proposés'),
            L(en=f'Tags spread over at least {cfg.tags.concept_dispersion} themes of the subjects. The agent '
                 'proposes the name (`cible`) and a short definition for the `# Concepts` section of plan.md.',
              fr=f'Tags répartis sur au moins {cfg.tags.concept_dispersion} thèmes du fonds. '
                 "L'agent propose le nom (`cible`) et une définition courte pour la section `# Concepts` de plan.md."),
            [e for e in waiting if e.action == CONCEPT])
    section(L(en='Tags that duplicate a theme', fr='Tags qui doublent un thème'),
            L(en='Proposed for deletion. The items that carry the tag without being in the theme are first proposed '
                 'in `suivi/rangement.toml` (source "tag"), and the tag stays in place while these proposals wait.',
              fr="Proposés à la suppression. Les fiches qui portent le tag sans être dans le thème sont d'abord "
                 'proposées dans `suivi/rangement.toml` (source « tag »), et le tag reste en place tant que ces '
                 'propositions attendent.'),
            [e for e in waiting if e.action == DELETE and e.theme])
    if s.pending:
        proposals = plural(len(s.pending), en='filing proposal', fr='proposition de rangement')
        lines += ['', L(en=f'{proposals} added to `suivi/rangement.toml`.',
                        fr=f'{proposals} ajoutée(s) à `suivi/rangement.toml`.')]
    unique = [e for e in waiting if e.action == DELETE and e.grade == OBVIOUS]
    section(L(en='Tags carried by a single item', fr='Tags portés par une seule fiche'),
            L(en='With no resemblance to a concept or a theme, obvious to delete, to approve in bulk (complete list).',
              fr='Sans ressemblance avec un concept ou un thème, évidents à supprimer, à approuver en bloc (liste '
                 'complète).'), unique)
    others = [e for e in waiting if e not in unique and e.action not in (STATUS, CONCEPT)
              and not (e.action == DELETE and e.theme)]
    section(L(en='Other tags to judge', fr='Autres tags à juger'),
            L(en='Manual tags outside the families and exceptions to the global rule, by bundles of 20 with their '
                 'count, their dispersion and three titles (in `suivi/tags.toml`). Possible fates, given with '
                 '`zc tags add --action`: delete, keep, concept, merge (written « supprimer », « garder », « concept », '
                 '« fusionner » in the file). Keeping is legitimate.',
              fr='Tags manuels hors familles et exceptions à la règle globale, par paquets de 20 avec leur effectif, '
                 'leur dispersion et trois titres (dans `suivi/tags.toml`). Sorts possibles : supprimer, garder, '
                 'concept, fusionner. Garder est légitime.'), others)
    decided = [e for e in s.tags if e.decision]
    if decided:
        entries_count = plural(len(decided), en='entry', fr='entrée', en_plural='entries')
        accepted = sum(e.decision == ACCEPT for e in decided)
        lines += ['', L(en='## Rules already decided', fr='## Règles déjà décidées'), '',
                  L(en=f'{entries_count} judged, {accepted} of them accepted. They stay in the file and serve to '
                       'sort future items.',
                    fr=f"{entries_count} jugée(s), dont {accepted} acceptée(s). Elles restent dans le fichier et "
                       'servent au tri des références à venir.')]

    protected = sorted(((n, a.protection(n)) for n in public if a.protection(n)), key=lambda x: norm(x[0]))
    lines += ['', L(en='## Protected tags', fr='## Tags protégés'), '',
              L(en='Inventoried without proposal. They only change through an entry whose source is "utilisateur". To '
                   'rename a colored tag, use "Rename Tag…" in Zotero, which carries the color over.',
                fr='Inventoriés sans proposition. Ils ne changent que par une entrée de source « utilisateur ». Pour '
                   'renommer un tag coloré, passer par « Renommer le tag… » dans Zotero, qui reporte la couleur.'), '']
    lines += [L(en=f'- {n} ({reason}, {len(u[n].items)} item(s))', fr=f'- {n} ({reason}, {len(u[n].items)} fiche(s))')
              for n, reason in protected] or [L(en='- none', fr='- aucun')]
    lines += ['', L(en=f'Colored tags: {len(b.colors)} of {MAX_COLORS}, {MAX_COLORS - len(b.colors)} slot(s) free.',
                    fr=f'Tags colorés : {len(b.colors)} sur {MAX_COLORS}, {MAX_COLORS - len(b.colors)} place(s) '
                       'libre(s).')]
    for rank, (n, color) in enumerate(b.colors, 1):
        lines.append(f'- {rank}. {_displayed(a, n)} ({color})'
                     + ('' if n in u else L(en=', carried by no element', fr=', porté par aucun élément')))

    citing = [(srch, op, val) for srch, op, val in b.tag_searches]
    if citing:
        lines += ['', L(en='## Saved searches that cite a tag', fr='## Recherches enregistrées qui citent un tag'), '',
                  L(en="A cited tag escapes the global rules, and is only deleted or renamed by an accepted entry. "
                       "The plan report then reminds you to update the search in Zotero.",
                    fr="Un tag cité échappe aux règles globales, et n'est supprimé ou renommé que par une entrée "
                       'acceptée. Le rapport du plan rappelle alors de mettre la recherche à jour dans Zotero.'), '']
        for srch, op, val in citing:
            names = [_displayed(a, n) for n, x in u.items() if srch in x.searches]
            shown_value = _displayed(a, val) if val in u else val
            matches = (f" ({', '.join(names)})" if names
                       else L(en=', no carried tag matches', fr=', aucun tag porté ne correspond'))
            lines.append(L(en=f'- "{srch}": tag {op} "{shown_value}"{matches}',
                           fr=f'- « {srch} » : tag {op} « {shown_value} »{matches}'))

    confidential_tags = sorted((n for n, x in u.items() if x.confidential), key=identifier)
    if confidential_tags:
        lines += ['', L(en='## Tags of confidential items', fr='## Tags de fiches confidentielles'), '',
                  L(en='Carried only by items excluded by the filter, they appear under an identifier. Only the '
                       'global rules apply to them, the rest through an entry whose source is "utilisateur" named by '
                       'the identifier.',
                    fr="Portés seulement par des fiches exclues par le filtre, ils apparaissent sous un identifiant. "
                       "Seules les règles globales s'y appliquent, le reste par une entrée de source « utilisateur » "
                       "nommée par l'identifiant."), '']
        lines += [L(en=f'- {identifier(n)} ({type_shown(u[n].readable_type)}, {len(u[n].all_items)} element(s))',
                    fr=f'- {identifier(n)} ({type_shown(u[n].readable_type)}, {len(u[n].all_items)} élément(s))')
                  for n in confidential_tags]

    children = sorted(n for n, x in public.items() if x.children == len(x.all_items))
    if children:
        lines += ['', L(en='## Tags carried only by attachments, notes or annotations',
                        fr='## Tags portés seulement par des pièces jointes, notes ou annotations'), '',
                  L(en='The same rules apply to them. Annotation tags, set by hand in the reader, never count among '
                       'the imported keywords.',
                    fr="Les mêmes règles s'y appliquent. Les tags d'annotations, posés à la main dans le lecteur, ne "
                       'comptent jamais parmi les mots-clés importés.'), '']
        lines += [L(en=f'- {n} ({len(u[n].all_items)} element(s), {u[n].annotations} of them annotation(s))',
                    fr=f'- {n} ({len(u[n].all_items)} élément(s), dont {u[n].annotations} annotation(s))')
                  for n in children]
    return '\n'.join(lines) + '\n'


def _line(el: Item) -> str:
    return (f'{el.author or "?"}, {year(el) or L(en="n.d.", fr="s. d.")}, '
            f'{el.title[:80] or L(en="(untitled)", fr="(sans titre)")}')


def _entry_line(e: Entry) -> str:
    chunks = [type_shown(e.type), L(en=f'{e.count} item(s)', fr=f'{e.count} fiche(s)'),
              L(en=f'dispersion {e.dispersion}', fr=f'dispersion {e.dispersion}')]
    if e.themes:
        chunks.append(L(en=f"themes {', '.join(e.themes)}", fr=f"thèmes {', '.join(e.themes)}"))
    proposed = action_shown(e.action) + (f' → {e.target}' if e.target else '') \
        + (L(en=f' (duplicates {e.theme})', fr=f' (double {e.theme})') if e.theme else '')
    if e.variants:
        proposed += L(en=f", with its variants {', '.join(e.variants)}", fr=f", avec ses variantes {', '.join(e.variants)}")
    return f"- {e.name} ({', '.join(chunks)})" \
        + (L(en=f': {proposed}', fr=f' : {proposed}') if e.action else L(en=': fate to propose', fr=' : sort à proposer')) \
        + (f'. {e.note}' if e.note else '')


def _displayed(a: _Analysis, name: str) -> str:
    return identifier(name) if name in a.u and a.u[name].confidential else name


# --- Rules -----------------------------------------------------------------------

@dataclass
class Rules:
    automatic: bool = False
    imported: set[str] = field(default_factory=set)
    excluded: set[str] = field(default_factory=set)
    protected: set[str] = field(default_factory=set)
    exempt: set[str] = field(default_factory=set)  # escape the global rules
    rename: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (target, kind)
    delete: set[str] = field(default_factory=set)
    statuses: list[str] = field(default_factory=list)
    confidential_tags: set[str] = field(default_factory=set)
    citing: dict[str, list[str]] = field(default_factory=dict)  # tag -> saved searches that cite it
    # Tag that duplicates a theme -> items not yet in that theme, where it stays until filing (D154).
    keep_on: dict[str, set[int]] = field(default_factory=dict)
    item_of: dict[int, int] = field(default_factory=dict)  # element -> its item
    problems: list[str] = field(default_factory=list)

    def track(self, name: str) -> tuple[str, set[str]]:
        """Final target of a renaming, following the chains (variant, then concept), and the kinds met on the way."""
        kinds, seen_set = set(), {name}
        while name in self.rename:
            target, kind = self.rename[name]
            kinds.add(kind)
            if target in seen_set or target == name:
                return target, kinds
            seen_set.add(target)
            name = target
        return name, kinds


def rules(tracking: Tracking, cfg: Config, b: Library) -> Rules:
    """Accepted rules of `suivi/tags.toml`. The library serves to recognise protected tags (colored, awaiting
    filing), tags cited by a search or confidential, and imported keywords."""
    return _rules(_Analysis(b, cfg), tracking)


def _rules(a: _Analysis, s: Tracking, simulate: bool = False) -> Rules:
    R = Rules(automatic=simulate or s.automatic == ACCEPT, excluded=set(a.excluded), statuses=list(a.statuses))
    R.item_of = {el.id: f for el in a.b.all_items.values() if (f := item_of(a.b, el)) is not None}
    if simulate or s.imported == ACCEPT:
        R.imported = set(a.imported)
    R.protected = {n for n in a.u if a.protection(n)} | set(a.cfg.tags.protected) | set(a.cfg.method.statuses) \
        | set(a.cfg.method.other_tags) | a.colors | a.waiting
    R.confidential_tags = {n for n, x in a.u.items() if x.confidential}
    R.citing = {n: x.searches for n, x in a.u.items() if x.searches}
    R.exempt = set(R.citing)

    def is_allowed(name: str, source: str) -> bool:
        if name in a.waiting:
            shown = _displayed(a, name)
            R.problems.append(L(en=f'"{shown}" awaits the judgment of filing proposals that rest on it '
                                   '(suivi/rangement.toml). Rule applied once these proposals are judged.',
                                fr=f'« {shown} » attend le jugement de propositions de rangement qui reposent '
                                   'sur lui (suivi/rangement.toml). Règle appliquée une fois ces propositions jugées.'))
            return False
        if name in R.excluded:
            shown = _displayed(a, name)
            R.problems.append(L(en=f'"{shown}" is used by the privacy filter, it never changes.',
                                fr=f'« {shown} » sert au filtre de confidentialité, il ne change jamais.'))
            return False
        if (name in R.protected or name in R.confidential_tags) and source != USER:
            what = (L(en='protected', fr='protégé') if name in R.protected
                    else L(en='carried only by confidential items', fr='porté seulement par des fiches confidentielles'))
            shown = _displayed(a, name)
            R.problems.append(L(en=f'"{shown}" is {what}, only an entry whose source is "utilisateur" changes it. '
                                   'Rule ignored.',
                                fr=f'« {shown} » est {what}, seule une entrée de source « utilisateur » le '
                                   'change. Règle ignorée.'))
            return False
        return True

    for g in s.variants:
        names = [a.real(n) for n in g.names]
        if g.decision == '':
            R.exempt |= set(names)
        elif g.decision == ACCEPT:
            for n in names:
                if is_allowed(n, g.source):
                    R.rename[n] = (g.target, 'variante')
            R.exempt.add(g.target)
    for e in s.tags:
        n = a.real(e.name)
        variants = [a.real(v) for v in e.variants]
        if e.decision == '':
            R.exempt |= {n, *variants}
            continue
        if e.decision == REJECT:
            continue
        if not is_allowed(n, e.source):
            R.exempt |= {n, *variants}
            continue
        for v in variants:  # brought back to the entry name, then subjected to its fate
            if v != n and is_allowed(v, e.source):
                R.rename[v] = (n, 'variante')
        if e.action == DELETE:
            R.delete.add(n)
            folded = [v for v, (c, _) in R.rename.items() if c == n]
            if e.theme and (outside := a.outside_theme(n, e.theme, folded)):
                R.keep_on[n] = outside
                shown = _displayed(a, n)
                count = plural(len(outside), en='item', fr='fiche')
                R.problems.append(
                    L(en=f'"{shown}" duplicates the theme "{e.theme}", but {count} that carry it are not in it yet. '
                         'It stays there until they are filed.',
                      fr=f'« {shown} » double le thème « {e.theme} », mais {count} qui le portent n\'y sont pas '
                         'encore. Il y reste jusqu\'à leur rangement.')
                    if len(outside) > 1 else
                    L(en=f'"{shown}" duplicates the theme "{e.theme}", but {count} that carries it is not in it yet. '
                         'It stays there until it is filed.',
                      fr=f'« {shown} » double le thème « {e.theme} », mais {count} qui le porte n\'y est pas encore. '
                         'Il y reste jusqu\'à son rangement.'))
        elif e.action == KEEP:
            R.exempt.add(n)
        elif e.action in KIND_OF_ACTION:
            R.rename[n] = (e.target, KIND_OF_ACTION[e.action])
        else:
            shown = _displayed(a, n)
            R.problems.append(L(en=f'"{shown}" is accepted without a sort. Rule ignored.',
                                fr=f'« {shown} » est accepté sans sort. Règle ignorée.'))
            R.exempt.add(n)
    return R


@dataclass
class Target:
    tags: list[dict]
    kinds: set[str] = field(default_factory=set)
    removed: list[tuple[str, str]] = field(default_factory=list)  # (name, kind)
    renamed: list[tuple[str, str, str]] = field(default_factory=list)  # (name, target, kind)


def _compute_target(tags: list[tuple[str, int]], annotation: bool, R: Rules, item_id: int | None = None) -> Target:
    """`item_id` (identifier) serves to keep a tag that duplicates a theme on an item not yet filed (D154)."""
    res: dict[str, int] = {}
    item = R.item_of.get(item_id) if item_id is not None else None

    def is_deleted(name: str) -> bool:
        return name in R.delete and item not in R.keep_on.get(name, ())

    v = Target([])
    status_added = False

    def put(name: str, typ: int):
        res[name] = min(res.get(name, typ), typ)

    for name, typ in tags:
        if name in R.excluded:
            put(name, typ)
            continue
        if name in R.rename:
            target, kinds = R.track(name)
            if is_deleted(target):
                v.removed.append((name, 'suppression'))
                v.kinds.add('suppression')
                continue
            put(target, 0)
            if (target, 0) != (name, typ):
                kind = sorted(kinds)[0] if len(kinds) == 1 else ('variante' if 'variante' in kinds else
                                                                    sorted(kinds)[0])
                v.renamed.append((name, target, kind))
                v.kinds |= kinds
                status_added |= target in R.statuses and target != name
            continue
        if is_deleted(name):
            v.removed.append((name, 'suppression'))
            v.kinds.add('suppression')
            continue
        free = name not in R.protected and name not in R.exempt
        if free and typ == 1 and R.automatic:
            v.removed.append((name, 'automatique'))
            v.kinds.add('automatique')
            continue
        if free and typ == 0 and name in R.imported and not annotation:
            v.removed.append((name, 'importé'))
            v.kinds.add('importé')
            continue
        put(name, typ)
    if status_added:
        present_statuses = [e for e in R.statuses if e in res]
        for e in present_statuses[:-1]:  # the most advanced status wins (D156)
            del res[e]
            v.removed.append((e, 'état'))
            v.kinds.add('état')
    v.tags = [{'tag': n} if t == 0 else {'tag': n, 'type': 1} for n, t in res.items()]
    return v


def targeted_tags(item: Item, R: Rules) -> list[dict]:
    """Complete list of the tags of an element after the rules, in API format (`{"tag": …}` for a manual tag,
    `{"tag": …, "type": 1}` for a kept automatic one), without duplicates. Pure function, reused by the triage."""
    return _compute_target(item.tags, item.type == 'annotation', R, item.id).tags


def to_flag(item: Item, R: Rules, cfg: Config) -> list[str]:
    """Manual tags outside the families of an element that no rule covers, to submit to the user (D155)."""
    m = cfg.method
    known = R.protected | R.exempt | set(R.rename) | R.delete | R.imported | R.excluded
    return [n for n, t in item.tags if t == 0 and n not in known
            and not (m.concept_prefix and n.startswith(m.concept_prefix))
            and not (m.technical_prefix and n.startswith(m.technical_prefix))]


# --- Plan -------------------------------------------------------------------------

def _tags_api(data: dict) -> list[tuple[str, int]]:
    return [(t['tag'], int(t.get('type', 0))) for t in data.get('tags') or []]


def make_plan(b: Library, cfg: Config, client: Client, day: date | None = None) -> tuple[Plan, str]:
    """Plan with one operation per element whose tags change, according to the accepted rules (D156)."""
    if (server := client.server_version()) > b.version:
        raise SystemExit(L(en=f'Zotero has not received the latest changes of the library yet (local version '
                              f'{b.version}, server version {server}). Check that Zotero is open and syncing, then '
                              'run the command again.',
                           fr=f'Zotero n\'a pas encore reçu les derniers changements de la bibliothèque (version '
                              f'locale {b.version}, version du serveur {server}). Vérifier que Zotero est ouvert et '
                              'synchronise, puis relancer.'))
    a = _Analysis(b, cfg)
    tracking = load(cfg)
    R = _rules(a, tracking)

    def current(tags):
        return normalize('tags', [{'tag': n, 'type': t} for n, t in tags])

    candidates = [el for el in b.all_items.values()
                 if normalize('tags', _compute_target(el.tags, el.type == 'annotation', R, el.id).tags) != current(el.tags)]
    api = client.items([el.key for el in candidates])
    retained: list[tuple[Item, Operation, Target]] = []
    for el in candidates:
        d = api.get(el.key)
        if d is None:
            R.problems.append(L(en=f'The element {el.key} no longer exists in Zotero, left aside.',
                                fr=f'L\'élément {el.key} n\'existe plus dans Zotero, laissé de côté.'))
            continue
        before = list(d.get('tags') or [])
        v = _compute_target(_tags_api(d), el.type == 'annotation', R, el.id)
        if normalize('tags', v.tags) == normalize('tags', before):
            continue
        op = Operation(el.key, {'tags': before}, {'tags': v.tags}, nature=', '.join(s for s in kinds() if s in v.kinds))
        retained.append((el, op, v))

    colors = _colors(cfg, client.settings([COLORS])[COLORS]['value'])
    trial = cfg.writing.trial - bool(colors)
    retained = _order(retained, trial, a.hidden)
    groups = [Group(el.key, _title(b, el, a.hidden), [op]) for el, op, _ in retained]
    if colors:  # first group, hence in the trial
        groups.insert(0, Group(COLORS, L(en='colors of the method tags', fr='couleurs des tags de la méthode'),
                               [colors]))
    elements = plural(len(retained), en='element', fr='élément')
    plan = Plan(STEP, client.user, groups,
                description=L(en=f'Tags, {elements}', fr=f'Tags, {elements}')
                + (L(en=', and colors of the method tags.', fr=', et couleurs des tags de la méthode.')
                   if colors else '.'))
    return plan, _plan_report(a, R, retained, trial, day or date.today(), colors)


COLORS = 'tagColors'


def _colors(cfg: Config, current) -> Operation | None:
    """Tags of the method colored and placed first, in the order of statuses then of the other tags, to receive the
    keys 1, 2, 3… (D175). A method tag already colored keeps its color. The other colored tags keep
    theirs and follow. Colored even if still unused, to be visible and within reach of a key from the start."""
    m = cfg.method
    current = [c for c in current or [] if isinstance(c, dict) and c.get('name')]
    already = {c['name']: c for c in current}
    method = [{'name': n, 'color': already[n]['color'] if n in already else color}
               for n, color in zip([*m.statuses, *m.other_tags], m.colors)]
    names = {c['name'] for c in method}
    wanted = method + [c for c in current if c['name'] not in names]
    if wanted == current or not method:
        return None
    return Operation(COLORS, {'value': current or None}, {'value': wanted},
                     nature=L(en='colors of the method tags', fr='couleurs des tags de la méthode'), kind='settings')


def _order(retained: list, trial: int, hidden: set[str]) -> list:
    """The first groups, applied by the trial, cover each kind of change present (D156)."""
    def key(x):
        el = x[0]
        return norm(el.title), el.key

    remaining = sorted(retained, key=key)
    rest = set().union(*(x[2].kinds for x in remaining)) if remaining else set()
    first_groups = []
    while rest and len(first_groups) < trial:
        # Most kinds still absent, a visible item rather than a child or a confidential item,
        # then the order of titles.
        _, x = max(enumerate(remaining), key=lambda ix: (len(ix[1][2].kinds & rest), ix[1][0].is_item,
                                                         ix[1][0].key not in hidden, -ix[0]))
        first_groups.append(x)
        remaining.remove(x)
        rest -= x[2].kinds
    return first_groups + remaining


def _title(b: Library, el: Item, hidden: set[str]) -> str:
    if el.key in hidden:
        return privacy.mask()
    if el.is_item:
        return _line(el)
    item = item_of(b, el)
    what = {'attachment': L(en='attachment', fr='pièce jointe'), 'note': L(en='note', fr='note'),
            'annotation': L(en='annotation', fr='annotation')}.get(el.type, el.type)
    if item is None:
        return L(en=f'standalone {what}', fr=f'{what} isolée')
    untitled = L(en='untitled', fr='sans titre')
    return L(en=f'{what} of "{b.all_items[item].title[:60] or untitled}"',
             fr=f'{what} de « {b.all_items[item].title[:60] or untitled} »')


def _to_list(tags: list, a: _Analysis) -> str:
    return ', '.join(f"{_displayed(a, t['tag'])}{' (auto)' if t.get('type') == 1 else ''}"
                     for t in tags) or L(en='none', fr='aucun')


def _colors_report(op: Operation) -> list[str]:
    before = {c['name']: (i, c['color']) for i, c in enumerate(op.before['value'] or [], 1)}
    lines = ['', L(en='## Colors', fr='## Couleurs'), '',
             L(en='The method tags receive a color and the first ranks of the tag selector. In Zotero, the key of '
                  'the rank (1 to 9) sets or removes the tag on the selected items, and a dot of its color marks each '
                  'item that carries it. The first group of the plan, hence in the trial.',
               fr='Les tags de la méthode reçoivent une couleur et les premiers rangs du sélecteur de tags. Dans '
                  'Zotero, la touche du rang (1 à 9) pose ou retire le tag sur les fiches sélectionnées, et une '
                  "pastille de sa couleur marque chaque fiche qui le porte. Le premier groupe du plan, donc dans "
                  "l'essai."), '']
    for i, c in enumerate(op.after['value'], 1):
        if c['name'] not in before:
            what = L(en='new color', fr='nouvelle couleur')
        elif before[c['name']][0] != i:
            old_rank = before[c['name']][0]
            what = L(en=f'had rank {old_rank}, key changed', fr=f'gardait le rang {old_rank}, touche changée')
        else:
            continue
        lines.append(f"- {i}. {c['name']} ({c['color']}), {what}" if i <= 9
                     else L(en=f"- {i}. {c['name']}, {what}, no key", fr=f"- {i}. {c['name']}, {what}, sans touche"))
    if len(op.after['value']) > 9:
        beyond = plural(len(op.after['value']) - 9, en='colored tag', fr='tag coloré')
        lines.append(L(en=f'- Beyond rank 9, {beyond} with no key.', fr=f'- Au-delà du rang 9, {beyond} sans touche.'))
    return lines


def _plan_report(a: _Analysis, R: Rules, retained: list, trial: int, day: date,
                  colors: Operation | None = None) -> str:
    b = a.b
    items = sum(1 for el, _, _ in retained if el.is_item)
    lines = [L(en=f'# Tag plan of {day:%d/%m/%Y}', fr=f'# Plan des tags du {day:%d/%m/%Y}'), '']
    if not retained:
        lines.append(L(en='No tag to change on the elements, only the colors.',
                       fr='Aucun tag à changer sur les éléments, seulement les couleurs.'))
    else:
        elements = plural(len(retained), en='element', fr='élément')
        others = len(retained) - items
        lines.append(L(en=f'{elements} to change, {items} item(s) and {others} attachment(s), note(s) or '
                          'annotation(s). One group per element, which receives its complete list of tags. A kept '
                          'automatic tag keeps its type, a renamed tag becomes manual.',
                       fr=f'{elements} à modifier, dont {items} fiche(s) et {others} pièce(s) jointe(s), note(s) ou '
                          'annotation(s). Un groupe par élément, qui reçoit sa liste complète de tags. Un tag '
                          'automatique conservé garde son type, un tag renommé devient manuel.'))
    if colors:
        lines += _colors_report(colors)
    by_kind = Counter(s for _, _, v in retained for s in v.kinds)
    if by_kind:
        lines += ['', L(en='## By kind of change', fr='## Par sorte de changement'), '']
        names = kinds()
        lines += [L(en=f'- {names[s]}: {by_kind[s]} element(s)', fr=f'- {names[s]} : {by_kind[s]} élément(s)')
                  for s in names if by_kind[s]]

    first_groups = retained[:trial]
    if first_groups and len(retained) > trial:
        # With the colors, the trial applies their group first, then `trial - 1` elements (pilot bench).
        n = len(first_groups) + bool(colors)
        then = L(en=f' (the colors of the method tags, then {len(first_groups)} elements)',
                 fr=f' (les couleurs des tags de la méthode, puis {len(first_groups)} éléments)') if colors else ''
        lines += ['', L(en='## Trial', fr='## Essai'), '',
                  L(en=f'The first {n} groups{then}, applied by `zc apply <plan> --trial`, cover each kind '
                       'of change. To check with `zc show`:',
                    fr=f'Les {n} premiers groupes{then}, appliqués par `zc apply <plan> --trial`, couvrent '
                       'chaque sorte de changement. À vérifier avec `zc show` :'), '']
        for el, op, v in first_groups:
            nature = nature_shown(op.nature)
            if el.key in a.hidden:
                lines.append(f'- {el.key} · {privacy.mask()} ({nature})')
            else:
                before, after = _to_list(op.before["tags"], a), _to_list(op.after["tags"], a)
                lines.append(L(en=f'- {el.key} · {_title(b, el, a.hidden)} ({nature}): before {before} ; '
                                  f'after {after}',
                               fr=f'- {el.key} · {_title(b, el, a.hidden)} ({nature}) : avant {before} ; '
                                  f'après {after}'))

    removed = Counter(n for _, _, v in retained for n, s in v.removed if s != 'automatique')
    reasons = {n: {'importé': L(en='imported keyword', fr='mot-clé importé'),
                   'état': L(en='status less advanced than another of the item',
                             fr="état moins avancé qu'un autre de la fiche")}.get(s, '')
               for _, _, v in retained for n, s in v.removed}
    renamed = Counter((n, c) for _, _, v in retained for n, c, _ in v.renamed)
    autos = Counter(n for _, _, v in retained for n, s in v.removed if s == 'automatique')
    if autos:
        names_count = plural(len(autos), en='name', fr='nom')
        most = ', '.join(f'{_displayed(a, n)} ({k})' for n, k in autos.most_common(20))
        lines += ['', L(en='## Automatic tags removed by the global rule', fr='## Tags automatiques retirés par la règle globale'), '',
                  L(en=f'{names_count}, {sum(autos.values())} occurrence(s). The most carried: {most}.',
                    fr=f'{names_count}, {sum(autos.values())} occurrence(s). Les plus portés : {most}.')]
    if removed:
        lines += ['', L(en='## Tags removed', fr='## Tags retirés'), '']
        lines += [f"- {_displayed(a, n)} ({k}{', ' + reasons[n] if reasons.get(n) else ''})"
                  for n, k in sorted(removed.items(), key=lambda x: norm(x[0]))]
    if renamed:
        lines += ['', L(en='## Tags renamed', fr='## Tags renommés'), '']
        lines += [f'- {_displayed(a, n)} → {c} ({k})' for (n, c), k in sorted(renamed.items(), key=lambda x: norm(x[0][0]))]

    touched = set(removed) | set(autos) | {n for n, _ in renamed}
    up_to_date = sorted((srch, n) for n, srchs in R.citing.items() if n in touched for srch in srchs)
    if up_to_date:
        lines += ['', L(en='## Saved searches to update in Zotero', fr='## Recherches enregistrées à mettre à jour dans Zotero'), '']
        lines += [L(en=f'- "{srch}" cites "{_displayed(a, n)}", removed or renamed by this plan',
                    fr=f'- « {srch} » cite « {_displayed(a, n)} », retiré ou renommé par ce plan')
                  for srch, n in up_to_date]
    vanished_names = {n for n in touched if not any(n == t['tag'] for _, op, _ in retained for t in op.after['tags'])}
    trash = sum(b.trash_tags.get(n, 0) for n in vanished_names)
    if trash:
        lines += ['', L(en=f'{trash} occurrence(s) of these tags stay on elements in the trash, which are not touched. '
                           'They will disappear when the trash is emptied.',
                        fr=f'{trash} occurrence(s) de ces tags restent sur des éléments de la corbeille, qui ne sont '
                           'pas touchés. Elles disparaîtront en vidant la corbeille.')]
    if R.problems:
        lines += ['', L(en='## To look at', fr='## À regarder'), '']
        lines += [f'- {p}' for p in dict.fromkeys(R.problems)]

    lines += ['', L(en='## Groups', fr='## Groupes'), ''] if retained else []
    for el, op, v in retained:
        if el.key in a.hidden:
            nature = nature_shown(op.nature)
            lines.append(L(en=f'- {el.key} · {privacy.mask()}: {nature}', fr=f'- {el.key} · {privacy.mask()} : {nature}'))
            continue
        chunks = [L(en=f'removes {", ".join(_displayed(a, n) for n, _ in v.removed)}',
                    fr=f'retire {", ".join(_displayed(a, n) for n, _ in v.removed)}')] if v.removed else []
        chunks += [f'{_displayed(a, n)} → {c}' for n, c, _ in v.renamed]
        lines.append(L(en=f'- {el.key} · {_title(b, el, a.hidden)}: ', fr=f'- {el.key} · {_title(b, el, a.hidden)} : ')
                     + ' ; '.join(chunks))
    return '\n'.join(lines) + '\n'
