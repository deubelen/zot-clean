"""Citation keys, step 7 of the cleanup (D143 to D146, D162).

Better BibTeX fills in missing keys, `zc` only does what BBT does not. This
module finds duplicate keys, compared without regard to case unless BBT is
set to tell them apart, and disambiguates them following D144. The oldest
item (by date added) keeps the key, the others get the first free suffix
(a, b… z, then aa), like BBT's `%(a)s` format. A duplicate where two items form
a group of duplicates not judged distinct is sent back to step 2, since the
merge will settle the key.

`make_plan` builds a plan from it (D146), with one group per duplicate key and
one group per item whose Extra still holds a `Citation Key:` line. The line
moves into the native field if it is empty, is removed if it repeats the native
key, and becomes a case to judge in `suivi/cles.toml` if it differs from it. The
rest of Extra is left intact. The plan compares the actual state with the target
state and only plans the difference (D119), the earlier data coming from the API.

Without active BBT, the step is skipped (D146), except for disambiguating the
duplicates. That needs no computation, BBT does not handle it even when it is
there (D162), and a duplicate key hinders every export, Zotero's included. The
Extra lines, leftovers of BBT 7, then wait for BBT.
"""

import re
import tomllib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date

from zot_clean import bbt, privacy
from zot_clean.config import Config
from zot_clean import lang
from zot_clean.lang import L, plural
from zot_clean.api import Client, Refusal
from zot_clean.reader import Library, Item
from zot_clean.plans import Group, Operation, Plan

# `Citation Key: …` line left in Extra by BBT 7 or by an import, which Zotero reads without regard to case.
EXTRA_LINE = re.compile(r'^[ \t]*citation[ \t]*key[ \t]*:[ \t]*(\S+)[ \t]*$', re.I | re.M)


def normalize(key: str, casing: bool = False) -> str:
    return key.strip() if casing else key.strip().lower()


def _seniority(e: Item) -> tuple[str, str]:
    return e.date_added or '', e.key


def doubles(b: Library, casing: bool = False) -> dict[str, list[Item]]:
    """Keys carried by several items, by normalized key, each group sorted from the oldest item to the most
    recent."""
    by = defaultdict(list)
    for e in b.items:
        if key := e.fields.get('citationKey', '').strip():
            by[normalize(key, casing)].append(e)
    return {k: sorted(v, key=_seniority) for k, v in sorted(by.items()) if len(v) > 1}


def letters(n: int) -> str:
    """1 → a, 26 → z, 27 → aa, 28 → ab."""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord('a') + r) + s
    return s


def free_suffix(database: str, taken: Iterable[str], casing: bool = False) -> str:
    """First alphabetic suffix that, added to `base`, gives none of the `taken` keys."""
    taken = {normalize(p, casing) for p in taken}
    n = 1
    while normalize(database + letters(n), casing) in taken:
        n += 1
    return letters(n)


def base_of(key: str) -> str:
    """Key without the suffix BBT adds after the year on a collision (« durand2020a » → « durand2020 »), so that
    the disambiguation continues the series like BBT (« durand2020b ») instead of stacking letters."""
    m = re.fullmatch(r'(.*\d{4})[A-Za-z]{1,2}', key)
    return m.group(1) if m else key


@dataclass
class Change:
    item: Item
    before: str
    after: str


@dataclass
class Double:
    key: str  # normalized key
    keeper: Item  # item that keeps its key
    changes: list[Change] = field(default_factory=list)


@dataclass
class Disambiguation:
    doubles: list[Double] = field(default_factory=list)
    # Duplicates whose items form a group of duplicates not judged distinct, left to step 2.
    deferred: dict[str, list[Item]] = field(default_factory=dict)
    # Duplicates skipped by the user in `suivi/cles.toml`, left as they are.
    skipped: dict[str, list[Item]] = field(default_factory=dict)


def disambiguate(b: Library, casing: bool = False, unjudged_duplicates: Iterable[Iterable[str]] = (),
               keepers: dict[str, str] | None = None, skipped: Iterable[str] = ()) -> Disambiguation:
    """Disambiguation of duplicate keys (D144).

    `unjudged_duplicates` gives the groups of duplicates (item keys) that are not judged distinct.
    `keepers` imposes, per citation key, the key of the item that keeps it (`suivi/cles.toml`). An
    imposed item missing from the group is ignored, the oldest then keeps the key. Suffixes are computed
    against all the keys of the library and against those already assigned. `skipped` gives the citation
    keys of the duplicates to leave as they are."""
    keepers = {normalize(k, casing): v for k, v in (keepers or {}).items()}
    skipped = {normalize(k, casing) for k in skipped}
    duplicate_groups = [set(g) for g in unjudged_duplicates]
    taken = {normalize(e.fields['citationKey'], casing) for e in b.items if e.fields.get('citationKey', '').strip()}
    res = Disambiguation()
    for k, items in doubles(b, casing).items():
        item_keys = {e.key for e in items}
        if any(len(item_keys & g) > 1 for g in duplicate_groups):
            res.deferred[k] = items
            continue
        if k in skipped:
            res.skipped[k] = items
            continue
        keeper = next((e for e in items if e.key == keepers.get(k)), items[0])
        double = Double(k, keeper)
        for e in items:
            if e is keeper:
                continue
            before = e.fields['citationKey']
            # Base taken from the kept key: two keys that differ only by case give the same series
            # (« dreyfus…1992 » and « dreyfus…1992a », not « Dreyfus…1992a »).
            database = base_of(keeper.fields['citationKey'].strip())
            new = database + free_suffix(database, taken, casing)
            taken.add(normalize(new, casing))
            double.changes.append(Change(e, before, new))
        res.doubles.append(double)
    return res


def extra_leftovers(b: Library) -> list[tuple[Item, str]]:
    """Items whose Extra still holds a `Citation Key:` line, with the key it carries."""
    found_list = []
    for e in b.items:
        if m := EXTRA_LINE.search(e.fields.get('extra', '')):
            found_list.append((e, m.group(1)))
    return found_list


# --- Plan for step 7 (D146) -----------------------------------------------------

FILE = 'cles.toml'
STEP = 'cles'
SKIP, NATIVE, EXTRA = 'écarter', 'natif', 'extra'
# Kinds of change, all covered by the first groups of the plan (the trial). Internal codes, `kind_label` shows them.
SUFFIX, TO_NATIVE, REMOVED, REPLACED = ('suffixe', 'Extra vers le champ natif', "ligne d'Extra retirée",
                                           'clé native remplacée')


def kind_label(kind: str) -> str:
    """Kind of change as shown, in the nature of an operation or in the report."""
    return {SUFFIX: L(en='suffix', fr='suffixe'), TO_NATIVE: L(en='Extra to the native field', fr='Extra vers le champ natif'),
            REMOVED: L(en='Extra line removed', fr="ligne d'Extra retirée"),
            REPLACED: L(en='native key replaced', fr='clé native remplacée')}.get(kind, kind)


def kinds_shown(kinds: set[str]) -> str:
    """Kinds of change of a group or an operation, in a stable order."""
    return ', '.join(kind_label(k) for k in sorted(kinds))

def header() -> str:
    return L(en="""\
# Citation keys, cases that need an opinion, written by `zc citation-keys plan` (step 7).
# This file is optional. It can be read and edited by hand or with the agent. `zc citation-keys plan` updates it
# without losing the decisions taken, then prepares the plan from them. A case settled in Zotero disappears from it.
# Decisions are written with `zc citation-keys decide ITEM=keep|skip|native|extra`.
#
# [[double]], a citation key carried by several items. The oldest (date added) keeps the key, the others receive a
#   suffix (a, b…).
#   fiches   : items that share the key, from the oldest to the most recent (filled in by zc).
#   garde    : key of the item that keeps the citation key, instead of the oldest (optional).
#   decision : "" (disambiguate by the rule) or "écarter" (leave as it is, out of the plan).
#   A duplicate whose items form a group of duplicates not judged distinct is sent back to step 2
#   (suivi/doublons.toml), the merge settling the key.
#
# [[extra]], an item whose Extra keeps a "Citation Key:" line that differs from its native key.
#   decision : "" (to judge), "natif" (keep the native key, remove the line), "extra" (the key of the line replaces
#              the native key, line removed) or "écarter" (change nothing, out of the plan).
#
# raison : free note.
""", fr="""\
# Clés de citation, cas qui demandent un avis, écrits par `zc citation-keys plan` (étape 7).
# Ce fichier est facultatif. Il se relit et se modifie à la main ou avec l'agent. `zc citation-keys plan` le met à jour
# sans perdre les décisions prises, puis prépare le plan d'après elles. Un cas réglé dans Zotero en disparaît.
# Les décisions s'écrivent avec `zc citation-keys decide FICHE=keep|skip|native|extra`.
#
# [[double]], une clé de citation portée par plusieurs fiches. La plus ancienne (date d'ajout) garde la clé, les
#   autres reçoivent un suffixe (a, b…).
#   fiches   : fiches qui partagent la clé, de la plus ancienne à la plus récente (renseigné par zc).
#   garde    : clé de la fiche qui garde la clé de citation, à la place de la plus ancienne (facultatif).
#   decision : "" (départager selon la règle) ou "écarter" (laisser tel quel, hors du plan).
#   Un double dont les fiches forment un groupe de doublons non jugé distinct est renvoyé à l'étape 2
#   (suivi/doublons.toml), la fusion réglant la clé.
#
# [[extra]], une fiche dont Extra garde une ligne « Citation Key: » qui diffère de sa clé native.
#   decision : "" (à juger), "natif" (garder la clé native, retirer la ligne), "extra" (la clé de la ligne remplace
#              la clé native, ligne retirée) ou "écarter" (ne rien changer, hors du plan).
#
# raison : note libre.
""")



# `Citation Key:` line of Extra, read line by line so it can be removed without touching the rest.
_LINE = re.compile(r'^[ \t]*citation[ \t]*key[ \t]*:[ \t]*(\S+)[ \t]*\r?$', re.I)


def extra_keys(extra: str) -> list[str]:
    """Keys of the `Citation Key:` lines of Extra, in order."""
    return [m.group(1) for line in (extra or '').split('\n') if (m := _LINE.match(line))]


def without_lines(extra: str) -> str:
    """Extra without its `Citation Key:` lines, the rest intact."""
    return '\n'.join(line for line in (extra or '').split('\n') if not _LINE.match(line))


@dataclass
class DuplicateEntry:
    items: list[str]
    keeper: str = ''
    decision: str = ''
    reason: str = ''


@dataclass
class ExtraEntry:
    item: str
    decision: str = ''
    reason: str = ''


@dataclass
class Tracking:
    doubles: list[DuplicateEntry] = field(default_factory=list)
    extra: list[ExtraEntry] = field(default_factory=list)


def load(cfg: Config) -> Tracking:
    """`suivi/cles.toml`, optional (D146)."""
    path = cfg.tracking / FILE
    if not path.is_file():
        return Tracking()
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start again from scratch.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    s = Tracking()
    for g in raw.get('double', []):
        e = DuplicateEntry([str(k) for k in g.get('fiches', [])], g.get('garde', ''), g.get('decision', ''),
                         g.get('raison', ''))
        if e.decision not in ('', SKIP):
            raise SystemExit(L(en=f'{path}: unknown decision "{e.decision}" for {", ".join(e.items)}.',
                               fr=f'{path} : décision inconnue « {e.decision} » pour {", ".join(e.items)}.'))
        s.doubles.append(e)
    for g in raw.get('extra', []):
        if not g.get('fiche'):
            raise SystemExit(L(en=f'{path}: an [[extra]] entry has no item.',
                               fr=f"{path} : une entrée [[extra]] n'a pas de fiche."))
        e = ExtraEntry(g['fiche'], g.get('decision', ''), g.get('raison', ''))
        if e.decision not in ('', NATIVE, EXTRA, SKIP):
            raise SystemExit(L(en=f'{path}: unknown decision "{e.decision}" for {e.item}.',
                               fr=f'{path} : décision inconnue « {e.decision} » pour {e.item}.'))
        s.extra.append(e)
    return s


KEEP = 'garder'
DECISIONS = {'garder': KEEP, 'garde': KEEP, 'ecarter': SKIP, 'écarter': SKIP, 'natif': NATIVE,
             'extra': EXTRA}


def decide(s: Tracking, decisions: dict[str, str], reason: str = '') -> int:
    """Decisions made by command (D177, modeled on D172), instead of writing the file by hand. Per item key,
    « garder » (the item keeps the citation key of its duplicate), « écarter » (duplicate or Extra case left
    as it is), « natif » or « extra » (Extra cases). Only the cases that are waiting change, that is the duplicates
    with no decision and no imposed item and the Extra cases with no decision. Returns the number of cases decided."""
    extra = {e.item: e for e in s.extra if not e.decision}
    doubles = {k: d for d in s.doubles if not d.decision and not d.keeper for k in d.items}
    known = {e.item for e in s.extra} | {k for d in s.doubles for k in d.items}
    errors, aimed = [], []
    for item, text in decisions.items():
        decision = DECISIONS.get(text.strip().lower())
        if decision is None:
            errors.append(L(en=f'{item}: unknown decision "{text}" (keep, skip, native or extra).',
                            fr=f'{item} : décision inconnue « {text} » (garder, écarter, natif ou extra).'))
        elif item not in known:
            errors.append(L(en=f'{item} is in no case of {FILE}. Check the key, or run `zc citation-keys plan` '
                               'again.',
                            fr=f'{item} ne figure dans aucun cas de {FILE}. Vérifier la clé, ou relancer '
                               '`zc citation-keys plan`.'))
        elif decision in (NATIVE, EXTRA) and item not in extra:
            errors.append(L(en=f'{item} has no Extra line to judge ([[extra]]), "{decision}" does not apply to it, '
                               'or the decision is already taken.',
                            fr=f'{item} n\'a pas de ligne d\'Extra à juger ([[extra]]), « {decision} » ne s\'y '
                               'applique pas, ou la décision est déjà prise.'))
        elif decision == KEEP and item not in doubles:
            errors.append(L(en=f'{item} is in no duplicate key to judge ([[double]]), or the decision is already '
                               'taken.',
                            fr=f'{item} n\'est dans aucune clé en double à juger ([[double]]), ou la décision est '
                               'déjà prise.'))
        elif decision == SKIP and item in extra and item in doubles:
            errors.append(L(en=f'{item} has both a duplicate key and an Extra line to judge. Skip one or the other '
                               'by hand in the file.',
                            fr=f'{item} a à la fois une clé en double et une ligne d\'Extra à juger. Écarter l\'un '
                               'ou l\'autre à la main dans le fichier.'))
        elif decision == SKIP and item not in extra and item not in doubles:
            errors.append(L(en=f'{item}: decision already taken. A decision already taken is changed by hand in '
                               'the file.',
                            fr=f'{item} : décision déjà prise. Une décision prise se change à la main dans le '
                               'fichier.'))
        else:
            aimed.append((item, decision))
    touched = [id(doubles[f]) for f, d in aimed if f in doubles and not (d == SKIP and f in extra)]
    if len(set(touched)) < len(touched):
        errors.append(L(en='A single decision per duplicate key (a single item keeps the key).',
                        fr='Une seule décision par clé en double (une seule fiche garde la clé).'))
    if errors:
        raise SystemExit(' '.join(errors))
    for item, decision in aimed:
        if decision in (NATIVE, EXTRA) or (decision == SKIP and item in extra):
            e = extra[item]
            e.decision, e.reason = decision, reason or e.reason
        else:
            d = doubles[item]
            if decision == KEEP:
                d.keeper = item
            else:
                d.decision = SKIP
            d.reason = reason or d.reason
    return len(aimed)


def refusal(b: Library, cfg: Config, state: bbt.State) -> str:
    """Why the step cannot run, empty if it can."""
    if not cfg.method.use_citation_keys:
        return L(en='The citation keys step is disabled in config.toml (`cles_citation = false`).',
                 fr="L'étape des clés de citation est désactivée dans config.toml (`cles_citation = false`).")
    if 'citationKey' not in b.known_fields:
        return L(en='This version of Zotero has no "Citation Key" field, which appeared with Zotero 7. Update Zotero '
                    'before this step.',
                 fr="Cette version de Zotero n'a pas de champ « Clé de citation », apparu avec Zotero 7. Mettre "
                    'Zotero à jour avant cette étape.')
    if state.present and state.too_old:
        return L(en=f'Better BibTeX {state.version} stores keys in its own database and not in the Zotero field. '
                    f'Upgrade to Better BibTeX {bbt.VERSION_MIN} and Zotero 8 before this step.',
                 fr=f'Better BibTeX {state.version} range les clés dans sa propre base et non dans le champ de '
                    f'Zotero. Passer à Better BibTeX {bbt.VERSION_MIN} et Zotero 8 avant cette étape.')
    return ''


def warnings(b: Library, state: bbt.State) -> list[str]:
    """BBT settings to flag before writing (D146)."""
    res = []
    if state.present and state.regenerates:
        res.append(regenerates())
    without = sum(1 for e in b.items if not e.fields.get('citationKey', '').strip())
    if state.present and state.fill_after == 0 and without:
        count = plural(without, en='item', fr='référence')
        res.append(L(en=f'{count} without a key, and Better BibTeX does not fill in missing keys by itself '
                        '("Automatically fill citation key after" at 0). Fill them with a right click, Better '
                        'BibTeX › Fill, or set a delay.',
                     fr=f"{count} sans clé, et Better BibTeX ne remplit pas seul les clés manquantes "
                        "(« Automatically fill citation key after » à 0). Les remplir par clic droit, Better BibTeX "
                        "› Fill, ou régler un délai."))
    return res


def regenerates() -> str:
    return L(
        en="Better BibTeX regenerates an item's key at every change (“Regenerate citation key when item changes”). "
           "Every item changed by zc would get a new key, and the suffixes of duplicate keys would be recomputed. "
           "Untick this setting in Zotero › Settings › Better BibTeX before applying.",
        fr="Better BibTeX refait la clé d'une fiche à chaque modification (« Regenerate citation key when item "
           "changes »). Chaque fiche modifiée par zc recevrait une nouvelle clé, et les suffixes des clés en double "
           "seraient recalculés. Décocher ce réglage dans Zotero › Réglages › Better BibTeX avant d'appliquer.")


def unjudged_duplicates(b: Library, cfg: Config) -> list[set[str]]:
    """Groups of duplicates found and not judged distinct in `suivi/doublons.toml` (D144)."""
    from zot_clean import duplicates
    distinct_sets = duplicates.distinct_sets(duplicates.load_tracking(cfg))
    return [c for g in duplicates.candidates(b) if not duplicates.already_judged(c := {e.key for e in g}, distinct_sets)]


@dataclass
class ExtraCase:
    item: Item
    native: str
    lines: list[str]  # distinct keys of the Extra lines
    kind: str = ''  # TO_NATIVE, REMOVED, REPLACED, empty for a case to judge or skipped
    target: str = ''  # target native key
    decision: str = ''


def _extra_cases(b: Library, tracking: Tracking) -> list[ExtraCase]:
    decisions = {e.item: e.decision for e in tracking.extra}
    res = []
    for e in b.items:
        lines = list(dict.fromkeys(extra_keys(e.fields.get('extra', ''))))
        if not lines:
            continue
        c = ExtraCase(e, e.fields.get('citationKey', '').strip(), lines, decision=decisions.get(e.key, ''))
        if not c.native and len(lines) == 1:
            c.kind, c.target = TO_NATIVE, lines[0]
        elif c.native and lines == [c.native]:
            c.kind, c.target = REMOVED, c.native
        elif c.decision == NATIVE and c.native:
            c.kind, c.target = REMOVED, c.native
        elif c.decision == EXTRA:
            c.kind, c.target = (REPLACED if c.native else TO_NATIVE), lines[0]
        res.append(c)
    return res


def _simulated(b: Library, targets: dict[str, str]) -> Library:
    """The items with the native key they will have once the Extra lines are tidied, so that the disambiguation
    accounts for the keys leaving Extra."""
    all_items = {}
    for e in b.items:
        key = targets.get(e.key, e.fields.get('citationKey', ''))
        all_items[e.id] = replace(e, fields={'citationKey': key} if key else {})
    return Library(b.schema_version, all_items, {}, {}, {}, [])


def _entry(entries: list[DuplicateEntry], items: set[str]) -> DuplicateEntry | None:
    """Tracking entry of a duplicate, the one that shares the most items with it (two at least)."""
    best, n = None, 1
    for x in entries:
        if (k := len(set(x.items) & items)) > n:
            best, n = x, k
    return best


@dataclass
class Analysis:
    extra: list[ExtraCase]
    disambiguation: Disambiguation
    entries: dict[str, DuplicateEntry]  # tracking entry of each duplicate, by normalized key


def analyze(b: Library, cfg: Config, state: bbt.State, tracking: Tracking, with_extra: bool = True) -> Analysis:
    cases = _extra_cases(b, tracking) if with_extra else []
    sim = _simulated(b, {c.item.key: c.target for c in cases if c.kind})
    entries = {}
    for k, items in doubles(sim, state.casing).items():
        if x := _entry(tracking.doubles, {e.key for e in items}):
            entries[k] = x
    keepers = {k: x.keeper for k, x in entries.items() if x.keeper}
    skipped = [k for k, x in entries.items() if x.decision == SKIP]
    d = disambiguate(sim, state.casing, unjudged_duplicates(b, cfg), keepers, skipped)
    return Analysis(cases, d, entries)


@dataclass
class _Target:
    item: Item  # as the local copy gives it
    key: str | None = None  # new native key, None if it does not change
    extra: bool = False  # remove the `Citation Key:` lines from Extra
    kinds: set[str] = field(default_factory=set)


def _operations(aimed: dict[str, _Target], client: Client) -> tuple[dict[str, Operation], list[str]]:
    """Operations per item, the earlier state re-read from the API. An item that changed since the local copy is left."""
    if not aimed:
        return {}, []
    api = client.items(sorted(aimed))
    ops, problems = {}, []
    for key, v in aimed.items():
        d = api.get(key)
        if d is None or d.get('deleted'):
            problems.append(L(en=f'The item {key} no longer exists in Zotero or is in the trash, left aside.',
                              fr=f"La fiche {key} n'existe plus dans Zotero ou est à la corbeille, laissée de côté."))
            continue
        native, extra = d.get('citationKey') or '', d.get('extra') or ''
        if (native.strip() != v.item.fields.get('citationKey', '').strip()
                or extra_keys(extra) != extra_keys(v.item.fields.get('extra', ''))):
            problems.append(L(en=f'The item {key} changed since the local copy, left aside. Run again after '
                                 "Zotero's sync.",
                              fr=f'La fiche {key} a changé depuis la copie locale, laissée de côté. Relancer après la '
                                 'synchronisation de Zotero.'))
            continue
        before, after = {}, {}
        if v.key is not None and v.key != native:
            before['citationKey'], after['citationKey'] = native, v.key
        if v.extra and (new := without_lines(extra)) != extra:
            before['extra'], after['extra'] = extra, new
        if after:
            # The nature is only shown, never read back: the kinds are in the language of the library.
            ops[key] = Operation(key, before, after, nature=kinds_shown(v.kinds))
    return ops, problems


@dataclass
class _Selected:
    group: Group
    kinds: set[str]
    cache: bool
    double: Double | None = None
    cases: ExtraCase | None = None


def _items(items: Iterable[Item]) -> set[str]:
    return {e.key for e in items}


def make_plan(b: Library, cfg: Config, client: Client, state: bbt.State | None = None,
              day: date | None = None) -> tuple[Plan, str]:
    """Plan for step 7 (D146), one group per duplicate key and one group per item for an Extra line. Also writes
    `suivi/cles.toml` when cases need an opinion."""
    state = state or bbt.detect(cfg.zotero_dir)
    if cause := refusal(b, cfg, state):
        raise Refusal(cause)
    if (server := client.server_version()) > b.version:
        raise Refusal(L(en=f'Zotero has not received the latest changes of the library yet (local version '
                           f'{b.version}, server version {server}). Check that Zotero is open and syncing, then run '
                           'the command again.',
                        fr=f"Zotero n'a pas encore reçu les derniers changements de la bibliothèque (version locale "
                           f'{b.version}, version du serveur {server}). Vérifier que Zotero est ouvert et '
                           'synchronise, puis relancer.'))
    a = analyze(b, cfg, state, load(cfg), with_extra=state.present)
    hidden = privacy.hidden_keys(b, cfg)
    write(cfg, b, a, hidden)

    by_key = b.by_key()
    aimed: dict[str, _Target] = {}
    for c in a.extra:
        if c.kind:
            aimed[c.item.key] = _Target(c.item, c.target if c.target != c.native else None, True, {c.kind})
    for dbl in a.disambiguation.doubles:
        for ch in dbl.changes:
            v = aimed.setdefault(ch.item.key, _Target(by_key[ch.item.key]))
            v.key = ch.after
            v.kinds.add(SUFFIX)
    ops, problems = _operations(aimed, client)

    retained: list[_Selected] = []
    for dbl in a.disambiguation.doubles:
        g_ops = [ops[ch.item.key] for ch in dbl.changes if ch.item.key in ops]
        if g_ops:
            cache = bool(hidden & _items([dbl.keeper, *(ch.item for ch in dbl.changes)]))
            title = privacy.mask() if cache else dbl.keeper.fields['citationKey'].strip()
            kinds = set().union(*(aimed[op.key].kinds for op in g_ops))
            retained.append(_Selected(Group(f'double-{dbl.keeper.key}', title, g_ops), kinds, cache, double=dbl))
    for c in a.extra:
        op = ops.get(c.item.key)
        if c.kind and op and SUFFIX not in aimed[c.item.key].kinds:
            cache = c.item.key in hidden
            retained.append(_Selected(Group(c.item.key, privacy.mask() if cache else _title(c.item), [op]),
                                   {c.kind}, cache, cases=c))
    retained = _order(retained, cfg.writing.trial)
    plan = Plan(STEP, client.user, [r.group for r in retained],
                description=L(en=f'Citation keys, {len(retained)} group(s).',
                              fr=f'Clés de citation, {len(retained)} groupe(s).'))
    return plan, _report(b, a, state, retained, problems, hidden, cfg.writing.trial, day or date.today())


def _title(e: Item) -> str:
    from zot_clean.audit import year
    undated, untitled = L(en='n.d.', fr='s. d.'), L(en='(untitled)', fr='(sans titre)')
    return f"{e.author or '?'}, {year(e) or undated}, {e.title[:60] or untitled}"


def _order(retained: list[_Selected], trial: int) -> list[_Selected]:
    """The first groups, applied by the trial, cover every kind of change present (D146)."""
    remaining = list(retained)
    rest = set().union(*(r.kinds for r in remaining))
    first_groups = []
    while rest and len(first_groups) < trial:
        _, r = max(enumerate(remaining), key=lambda ir: (len(ir[1].kinds & rest), not ir[1].cache, -ir[0]))
        first_groups.append(r)
        remaining.remove(r)
        rest -= r.kinds
    return first_groups + remaining


def write(cfg: Config, b: Library, a: Analysis, hidden: set[str], tracking: Tracking | None = None) -> None:
    """`suivi/cles.toml`, written only when cases need an opinion or the file already exists (D146).
    The citation key of a duplicate that touches a confidential item does not appear in it (D126). `tracking` gives
    the reasons of the Extra cases, those of the default file. A decided Extra case stays there until it is settled
    in Zotero (D177)."""
    from zot_clean.audit import line
    from zot_clean.duplicates import _toml
    d = a.disambiguation
    by_key = b.by_key()  # the disambiguation items carry only their citation key
    new_ones = {ch.item.key: ch.after for dbl in d.doubles for ch in dbl.changes}
    all_entries = ([(dbl.key, [dbl.keeper, *(ch.item for ch in dbl.changes)], '') for dbl in d.doubles]
            + [(k, f, 'écarté') for k, f in d.skipped.items()] + [(k, f, 'renvoyé') for k, f in d.deferred.items()])
    key_word = L(en='key', fr='clé')
    blocks = []
    for k, items, state in sorted(all_entries, key=lambda t: t[0]):
        x = a.entries.get(k) or DuplicateEntry([])
        items = sorted(items, key=_seniority)
        concealed = _items(items) if hidden & _items(items) else set()
        blocks.append('[[double]]')
        if state == 'renvoyé':
            blocks.append(L(en='# sent back to step 2, these items form a group of duplicates not judged distinct '
                               '(suivi/doublons.toml)',
                            fr="# renvoyé à l'étape 2, ces fiches forment un groupe de doublons non jugé distinct "
                               '(suivi/doublons.toml)'))
        shown_key = (privacy.mask() if concealed else
                     L(en=f'"{items[0].fields["citationKey"].strip()}"',
                       fr=f'« {items[0].fields["citationKey"].strip()} »'))
        blocks.append(f'# {key_word} {shown_key}')
        for e in items:
            if e.key in new_ones:
                what = (L(en='gets a suffix', fr='reçoit un suffixe') if concealed else f'→ {new_ones[e.key]}')
            else:
                what = L(en='unchanged', fr='inchangée') if state else L(en='keeps the key', fr='garde la clé')
            who, added = line(by_key[e.key], concealed), (e.date_added or '')[:10]
            blocks.append(L(en=f'# {who}, added on {added}, {what}', fr=f'# {who}, ajoutée le {added}, {what}'))
        blocks += [f'fiches = {_toml([e.key for e in items])}', f'garde = {_toml(x.keeper)}',
                  f'decision = {_toml(x.decision)}', f'raison = {_toml(x.reason)}', '']
    path = cfg.tracking / FILE
    reasons = {e.item: e.reason for e in (tracking or load(cfg)).extra}
    for c in a.extra:
        if c.kind and not c.decision:
            continue
        blocks.append('[[extra]]')
        if c.item.key in hidden:
            blocks.append(f'# {c.item.key} · {privacy.mask()}')
        else:
            lines_text = ('", "' if lang.current() == 'en' else ' », « ').join(c.lines)
            many = len(c.lines) > 1
            blocks += [f'# {line(c.item)}',
                       (L(en=f'# native key "{c.native}", Extra lines "{lines_text}"',
                          fr=f"# clé native « {c.native} », lignes d'Extra « {lines_text} »") if many else
                        L(en=f'# native key "{c.native}", Extra line "{lines_text}"',
                          fr=f"# clé native « {c.native} », ligne d'Extra « {lines_text} »"))]
        if c.decision == NATIVE and not c.native:
            blocks.append(L(en='# "natif" impossible, the item has no native key',
                            fr='# "natif" impossible, la fiche n\'a pas de clé native'))
        blocks += [f'fiche = {_toml(c.item.key)}', f'decision = {_toml(c.decision)}',
                  f"raison = {_toml(reasons.get(c.item.key, ''))}", '']
    if not blocks and not path.is_file():
        return
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    from zot_clean.audit import write_toml
    write_toml(path, [header(), *blocks])


def _report(b: Library, a: Analysis, state: bbt.State, retained: list[_Selected], problems: list[str],
             hidden: set[str], trial: int, day: date) -> str:
    from zot_clean.audit import line
    d = a.disambiguation
    by_key = b.by_key()
    doubles_ = [r for r in retained if r.double]
    extras = [r for r in retained if r.cases]
    suffixes = sum(len(r.group.operations) for r in doubles_)
    several = lambda n: n > 1  # noqa: E731

    groups = plural(len(retained), en='group', fr='groupe')
    keys_count = plural(len(doubles_), en='duplicate key', fr='clé')
    others = plural(suffixes, en='other', fr='autre')
    extras_count = plural(len(extras), en='line', fr='ligne')
    disambiguated = (L(en='disambiguated', fr='départagées') if several(len(doubles_))
                     else L(en='disambiguated', fr='départagée'))
    tidied = L(en='tidied', fr='rangées') if several(len(extras)) else L(en='tidied', fr='rangée')
    lines = [L(en=f'# Citation keys, plan of {day:%d/%m/%Y}', fr=f'# Clés de citation, plan du {day:%d/%m/%Y}'), '',
             bbt.describe(state), '',
             L(en=f'{groups}. {keys_count} {disambiguated}, the oldest item keeping the key and {others} receiving '
                  f'a suffix. {extras_count} "Citation Key:" of Extra {tidied}, the rest of Extra intact. A unique '
                  'key is never touched.',
               fr=f"{groups}. {keys_count} en double {disambiguated}, la plus ancienne fiche gardant la clé et "
                  f"{others} recevant un suffixe. {extras_count} « Citation Key: » d'Extra {tidied}, le reste "
                  "d'Extra intact. Une clé unique n'est jamais touchée.")]
    if doubles_:
        lines += ['', L(en='An item that receives a suffix changes its key. A text that cited it under the old key, '
                           'ambiguous until now, needs updating.',
                        fr="Une fiche qui reçoit un suffixe change de clé. Un texte qui la citait sous l'ancienne "
                           "clé, ambiguë jusqu'ici, est à mettre à jour.")]
    if warn_msg := warnings(b, state):
        lines += ['', L(en='## Warning', fr='## Attention'), ''] + [f'- {x}' for x in warn_msg]
    if not state.present:
        leftovers = len(extra_leftovers(b))
        text = L(en='Better BibTeX is not active. The step is skipped, except for the disambiguation of duplicate '
                    'keys, which needs no computation.',
                 fr="Better BibTeX n'est pas actif. L'étape est sautée, sauf le départage des clés en double, qui "
                    'ne demande aucun calcul.')
        if leftovers:
            count = plural(leftovers, en='item', fr='fiche')
            wait = (L(en='wait', fr='attendent') if several(leftovers) else L(en='waits', fr='attend'))
            text += L(en=f' {count} whose Extra keeps a "Citation Key:" line {wait} for Better BibTeX.',
                      fr=f' {count} dont Extra garde une ligne « Citation Key: » {wait} Better BibTeX.')
        lines += ['', text]
    first_groups = retained[:trial]
    if first_groups and len(retained) > trial:
        lines += ['', L(en='## Trial', fr='## Essai'), '',
                  L(en=f'The first {len(first_groups)} groups, applied by `zc apply <plan> --trial`, cover each '
                       'kind of change. To check with `zc show`:',
                    fr=f'Les {len(first_groups)} premiers groupes, appliqués par `zc apply <plan> --trial`, '
                       'couvrent chaque sorte de changement. À vérifier avec `zc show` :'), '']
        lines += [f"- {r.group.id} · {r.group.title} ({kinds_shown(r.kinds)})" for r in first_groups]
    if doubles_:
        from zot_clean.audit import norm
        lines += ['', L(en='## Duplicate keys', fr='## Clés en double'), '']
        other_title = 0
        for r in doubles_:
            changed_keys = {op.key: op.after.get('citationKey', '') for op in r.group.operations}
            if r.cache:
                keeps = L(en='keeps the key', fr='garde la clé')
                lines.append(f'- {privacy.mask()}, {r.double.keeper.key} {keeps}, '
                             + ', '.join(L(en=f'{k} gets a suffix', fr=f'{k} reçoit un suffixe')
                                         for k in changed_keys))
            else:
                keeper = by_key[r.double.keeper.key]
                lines.append(L(en=f'- "{r.group.title}", {line(keeper)} keeps the key',
                               fr=f'- « {r.group.title} », {line(keeper)} garde la clé'))
                for k, n in changed_keys.items():
                    # The suffixed key repeats the title of the item that keeps the key (D144). When the titles
                    # differ, it is about another text: flag it, without changing the rule.
                    other = state.present and norm(by_key[k].title) != norm(keeper.title)
                    other_title += other
                    lines.append(f'  - {line(by_key[k])} → {n}'
                                 + (L(en=' (key taken from the title of another item)',
                                      fr=" (clé tirée du titre d'une autre fiche)") if other else ''))
        if other_title:
            count = plural(other_title, en='item', fr='fiche')
            verb = L(en='receive', fr='reçoivent') if several(other_title) else L(en='receives', fr='reçoit')
            lines += ['', L(en=f'{count} {verb} a key taken from the title of another item. To give it a key taken '
                               'from its own title, regenerate the key of that item alone in Zotero once the plan is '
                               'applied and synced (right click on the item, Better BibTeX › Refresh). Its key having '
                               'just changed, no text cites it under that name yet.',
                            fr=f"{count} {verb} une clé tirée du titre d'une autre fiche. Pour lui donner une clé "
                               "tirée de son propre titre, régénérer la clé de cette fiche seule dans Zotero une fois "
                               "le plan appliqué et synchronisé (clic droit sur la fiche, Better BibTeX › Refresh). "
                               "Sa clé venant de changer, aucun texte ne la cite encore sous ce nom.")]
    if extras:
        lines += ['', L(en='## "Citation Key:" lines of Extra', fr="## Lignes « Citation Key: » d'Extra"), '']
        for r in extras:
            c = r.cases
            if r.cache:
                lines.append(f'- {c.item.key} · {privacy.mask()}, {kind_label(c.kind)}')
            elif c.kind == TO_NATIVE:
                lines.append(L(en=f'- {line(c.item)}, "{c.target}" moves to the native field',
                               fr=f'- {line(c.item)}, « {c.target} » passe dans le champ natif'))
            elif c.kind == REMOVED:
                lines.append(L(en=f'- {line(c.item)}, line removed, the native key "{c.native}" stays',
                               fr=f'- {line(c.item)}, ligne retirée, la clé native « {c.native} » reste'))
            else:
                lines.append(L(en=f'- {line(c.item)}, native key "{c.native}" replaced by "{c.target}"',
                               fr=f'- {line(c.item)}, clé native « {c.native} » remplacée par « {c.target} »'))
    if d.deferred:
        lines += ['', L(en='## Sent back to step 2', fr="## Renvoyés à l'étape 2"), '',
                  L(en='These items form a group of duplicates not judged distinct in `suivi/doublons.toml`. The '
                       'merge will settle the key. If they are distinct, note it in `suivi/doublons.toml`, then run '
                       'again.',
                    fr='Ces fiches forment un groupe de doublons non jugé distinct dans `suivi/doublons.toml`. La '
                       'fusion réglera la clé. Si elles sont distinctes, le noter dans `suivi/doublons.toml`, puis '
                       'relancer.'), '']
        for items in d.deferred.values():
            cache = hidden & _items(items)
            first = items[0].fields['citationKey'].strip()
            shown = privacy.mask() if cache else L(en=f'"{first}"', fr=f'« {first} »')
            lines.append(f"- {shown}, " + ', '.join(e.key for e in items))
    to_judge = [c for c in a.extra if not c.kind and c.decision != SKIP]
    if to_judge:
        count = plural(len(to_judge), en='item', fr='fiche')
        left = L(en='left', fr='laissées') if several(len(to_judge)) else L(en='left', fr='laissée')
        lines += ['', L(en='## To judge in suivi/cles.toml', fr='## À juger dans suivi/cles.toml'), '',
                  L(en=f'{count} whose "Citation Key:" line of Extra differs from the native key, {left} out of the '
                       'plan.',
                    fr=f"{count} dont la ligne « Citation Key: » d'Extra diffère de la clé native, {left} hors du "
                       "plan."), '']
        for c in to_judge:
            if c.item.key in hidden:
                lines.append(f'- {c.item.key} · {privacy.mask()}')
            else:
                joined = ('", "' if lang.current() == 'en' else ' », « ').join(c.lines)
                lines.append(L(en=f'- {line(c.item)}, native "{c.native}", Extra "{joined}"',
                               fr=f'- {line(c.item)}, native « {c.native} », Extra « {joined} »'))
    skipped = len(d.skipped) + sum(1 for c in a.extra if not c.kind and c.decision == SKIP)
    if skipped:
        count = plural(skipped, en='case', fr='cas')
        lines += ['', (L(en=f'{count} skipped in suivi/cles.toml, left as they are.',
                         fr=f'{count} écartés dans suivi/cles.toml, laissés tels quels.') if several(skipped) else
                       L(en=f'{count} skipped in suivi/cles.toml, left as it is.',
                         fr=f'{count} écarté dans suivi/cles.toml, laissé tel quel.'))]
    without = sum(1 for e in b.items if not e.fields.get('citationKey', '').strip())
    if without:
        count = plural(without, en='item', fr='référence')
        lines += ['', L(en=f'{count} without a citation key. ', fr=f'{count} sans clé de citation. ')
                  + (L(en='Better BibTeX fills them in by itself a few seconds after they arrive, or on request '
                          'with a right click, Better BibTeX › Fill.',
                       fr='Better BibTeX les remplit seul quelques secondes après leur arrivée, ou sur demande par '
                          'clic droit, Better BibTeX › Fill.')
                     if state.present else
                     L(en='Without Better BibTeX, they stay empty.', fr='Sans Better BibTeX, elles restent vides.'))]
    if problems:
        lines += ['', L(en='## To look at', fr='## À regarder'), ''] + [f'- {p}' for p in problems]
    return '\n'.join(lines) + '\n'


# --- Inbox triage (D146) ----------------------------------------------------------

def notify_no_key(b: Library, cfg: Config, state: bbt.State | None = None) -> bool:
    """The triage flags a reference without a key when Better BibTeX, active, should have filled it on arrival."""
    state = state or bbt.detect(cfg.zotero_dir)
    return state.present and not refusal(b, cfg, state)


def disambiguate_inbox(b: Library, cfg: Config, client: Client, triaged: set[str], excluded_items: set[str] = frozenset(),
                    state: bbt.State | None = None) -> tuple[list[tuple[str, Operation]], set[str]]:
    """Disambiguation (D144) of the duplicate keys that touch a triaged reference, for the Inbox triage (D146).

    Each operation, at rank 1, is returned with the triaged reference whose group receives it, its own if it
    receives the suffix. A duplicate that touches an item of `excluded_items` (merged by the same plan) is left.
    Also returns the references whose group touches a confidential item, to show without values (D126)."""
    state = state or bbt.detect(cfg.zotero_dir)
    if refusal(b, cfg, state):
        return [], set()
    a = analyze(b, cfg, state, load(cfg), with_extra=False)
    hidden = privacy.hidden_keys(b, cfg)
    by_key = b.by_key()
    retained = []
    for dbl in a.disambiguation.doubles:
        items = _items([dbl.keeper, *(ch.item for ch in dbl.changes)])
        if items & triaged and not items & excluded_items:
            retained.append((dbl, items, next(k for k in [dbl.keeper.key, *(ch.item.key for ch in dbl.changes)]
                                              if k in triaged)))
    aimed = {ch.item.key: _Target(by_key[ch.item.key], ch.after, False, {SUFFIX})
             for dbl, _, _ in retained for ch in dbl.changes}
    ops, _ = _operations(aimed, client)
    res, concealed = [], set()
    for dbl, items, leading in retained:
        for ch in dbl.changes:
            if op := ops.get(ch.item.key):
                op.rank = 1
                group = ch.item.key if ch.item.key in triaged else leading
                res.append((group, op))
                if hidden & items:
                    concealed.add(group)
    return res, concealed
