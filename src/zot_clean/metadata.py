"""Metadata, step 3 of the cleanup (D58 to D73). Identifiers and complements.

`identifiers` fixes the form of DOIs, checks that they exist and really designate
the item, and looks for the missing DOI of articles, conference papers, chapters
and preprints. `fill_in` fills empty fields from the confirmed DOI. Certain cases
go straight into the plan. The others are written to `suivi/metadonnees.toml`, and
come back there once judged (`accepter` enters the next plan of the same substep,
`refuser` is not proposed again).

Detection is done on the database copy, the previous values of the plans come
from the API, reread just before the plan is written.
"""

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field

from zot_clean import privacy, plans
from zot_clean.audit import year as item_year, write_toml, line, type_name
from zot_clean.config import Config
from zot_clean.duplicates import _toml
from zot_clean.api import Client
from zot_clean.lang import L
from zot_clean.reader import NON_BASE_DATES, Library, Item, ItemTypes, date_as_entered
from zot_clean.plans import Group, Operation, Plan
from zot_clean.sources import Work, Services, isbns, norm, similarity, titles_match

FILE = 'metadonnees.toml'
# Memory of an ISBN removed by a judged case, refused, with the ISBNs then ruled out as proposals.
REMOVED_ISBN = 'isbn_retire'
IDENTIFIERS, TYPES, FILL_IN = 'identifiants', 'types', 'completer'
ACCEPT, REJECT = 'accepter', 'refuser'
SEARCHED_TYPES = {'journalArticle', 'conferencePaper', 'bookSection', 'preprint'}
VALID_DOI = re.compile(r'^10\.\d{4,9}/\S+$')
CONTAINER = {'journalArticle': 'publicationTitle', 'bookSection': 'bookTitle', 'conferencePaper': 'proceedingsTitle'}
WITH_EDITORS = {'book', 'bookSection'}
# Titles never matched with certainty (D75).
GENERIC_TITLES = {'introduction', 'conclusion', 'conclusions', 'preface', 'avant propos', 'foreword', 'afterword',
              'postface', 'editorial', 'compte rendu', 'review', 'book review', 'prologue', 'epilogue', 'index',
              'bibliography', 'bibliographie', 'introduction generale', 'general introduction'}
STOP_WORDS = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'to', 'for', 'le', 'la', 'les', 'l', 'de', 'des', 'du', 'd',
         'et', 'en', 'un', 'une', 'au', 'aux'}
LANGUAGE_WORDS = {
    'en': {'the', 'of', 'and', 'in', 'a', 'to', 'for', 'on', 'with', 'from', 'an', 'is', 'as', 'by', 'at', 'its',
           'their', 'how', 'what', 'why', 'between', 'toward', 'towards', 'into', 'new'},
    'fr': {'le', 'la', 'les', 'de', 'des', 'du', 'et', 'un', 'une', 'pour', 'sur', 'dans', 'au', 'aux', 'par', 'est',
           'que', 'qui', 'l', 'd', 'entre', 'vers', 'ou', 'son', 'sa', 'ses', 'leur', 'leurs', 'nouvelle'},
}


def generic_title(title: str) -> bool:
    n = norm(title)
    return n in GENERIC_TITLES or len([m for m in n.split() if m not in STOP_WORDS]) < 4


def title_language(title: str) -> str:
    """« en » or « fr » from common words, empty if the title does not decide (D77)."""
    words = norm(title).split()
    scores = {code: sum(m in listing for m in words) for code, listing in LANGUAGE_WORDS.items()}
    (leading, a), (_, b) = sorted(scores.items(), key=lambda x: -x[1])
    return leading if a >= 1 and a > b else ''

def header() -> str:
    """Comment header of `suivi/metadonnees.toml`, in the language of the library. The keys and values it shows
    stay French (D209)."""
    return L(en="""\
# Metadata cases to judge, written by `zc metadata identifiers` and `zc metadata complete`.
# This file can be read again and edited by hand or with the agent. The commands update it without losing the
# decisions, and the next plan of the same substep takes up the accepted cases. Decisions are also written with
# `zc metadata accept` (all the obvious ones with --obvious, or keys) and `zc metadata reject`.
#
# decision : "accepter" (the proposal numbered `choix`, 1 for the first), "refuser" (not to be proposed again)
#            or "" (to judge). A refused « isbn_retire » case keeps track of an ISBN removed by a judged case. The
#            ISBNs it lists are not proposed again, and a new ISBN found for the item stays to judge.
# forcer   : values imposed on the item in addition to the proposal, for example { "date" = "1998" }.
# classe   : sorting done by zc. « évident » when a single proposal matches the item in every respect, its
#            number then being in `choix`, or when an unfindable DOI has no other lead than its removal ;
#            « douteux » otherwise. The opinion on each proposal says what matches or differs
#            (title, author, year, type, journal or book, publisher…).
#
# To impose a value outside any case (wrong journal, ISBN of another book…), add at the end of the
# file a complete case like this one, with the key of the item, then run `zc metadata complete` again.
# An empty value empties the field, for example forcer = { "ISBN" = "" } for a book.
#
#   [[cas]]
#   cle = "ABCD1234"
#   sous_etape = "completer"
#   probleme = "forcer"
#   decision = "accepter"
#   forcer = { "publicationTitle" = "Journal of Experimental Psychology: General" }
""", fr="""\
# Cas de métadonnées à juger, écrits par `zc metadata identifiers` et `zc metadata complete`.
# Ce fichier se relit et se modifie à la main ou avec l'agent. Les commandes le mettent à jour sans perdre
# les décisions, et le plan suivant de la même sous-étape reprend les cas acceptés. Les décisions s'écrivent
# aussi par `zc metadata accept` (tous les évidents avec --obvious, ou des clés) et `zc metadata reject`.
#
# decision : "accepter" (la proposition numéro `choix`, 1 pour la première), "refuser" (à ne plus proposer)
#            ou "" (à juger). Un cas « isbn_retire » refusé garde la trace d'un ISBN retiré par un cas jugé. Les ISBN
#            qu'il liste ne sont plus proposés, et un nouvel ISBN trouvé pour la fiche reste à juger.
# forcer   : valeurs imposées à la fiche en plus de la proposition, par exemple { "date" = "1998" }.
# classe   : tri fait par zc. « évident » quand une seule proposition concorde en tout avec la fiche, son
#            numéro étant alors dans `choix`, ou quand un DOI introuvable n'a pas d'autre piste que son
#            retrait ; « douteux » sinon. L'avis de chaque proposition dit ce qui concorde ou diffère
#            (titre, auteur, année, type, revue ou ouvrage, éditeur…).
#
# Pour imposer une valeur hors de tout cas (revue fausse, ISBN d'un autre livre…), ajouter à la fin du
# fichier un cas complet comme celui-ci, avec la clé de la fiche, puis relancer `zc metadata complete`.
# Une valeur vide vide le champ, par exemple forcer = { "ISBN" = "" } pour un livre.
#
#   [[cas]]
#   cle = "ABCD1234"
#   sous_etape = "completer"
#   probleme = "forcer"
#   decision = "accepter"
#   forcer = { "publicationTitle" = "Journal of Experimental Psychology: General" }
""")


def normalize_doi(v: str) -> str:
    # Resolver address, including behind a library proxy (dx.doi.org.ezproxy.exemple.org/10.…).
    v = re.sub(r'^\s*(https?://)?[^/\s]*doi\.org[^/\s]*/(?=10\.)', '', v.strip(), flags=re.I)
    v = re.sub(r'^doi:\s*', '', v, flags=re.I)
    return v.strip().rstrip('.,;')


@dataclass
class Proposal:
    fields: dict
    source: str = ''
    note: str = ''
    verdict: str = ''  # « concorde » or what differs from the item (D134), empty without a work to compare


@dataclass
class Case:
    key: str
    substep: str
    problem: str
    proposals: list[Proposal] = field(default_factory=list)
    decision: str = ''
    selection: int = 1
    force: dict = field(default_factory=dict)
    grade: str = ''  # « évident » or « douteux » (D134), empty outside identifiers

    @property
    def id(self) -> tuple[str, str, str]:
        return self.key, self.substep, self.problem

    def retained(self) -> dict:
        """Fields to write for an accepted case."""
        fields = dict(self.proposals[self.selection - 1].fields) if self.proposals else {}
        return fields | self.force


# --- Tracking file -------------------------------------------------------------

def load_tracking(cfg: Config) -> list[Case]:
    path = cfg.tracking / FILE
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start over.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    cases = []
    for c in raw.get('cas', []):
        x = Case(c['cle'], c['sous_etape'], c['probleme'],
                [Proposal(dict(p.get('champs', {})), p.get('source', ''), p.get('note', ''), p.get('avis', ''))
                 for p in c.get('propositions', [])],
                c.get('decision', ''), int(c.get('choix', 1)), dict(c.get('forcer', {})), c.get('classe', ''))
        if x.decision not in ('', ACCEPT, REJECT):
            raise SystemExit(L(en=f'{path}: unknown decision “{x.decision}” for {x.key}.',
                               fr=f'{path} : décision inconnue « {x.decision} » pour {x.key}.'))
        if x.decision == ACCEPT and x.proposals and not 1 <= x.selection <= len(x.proposals):
            raise SystemExit(L(en=f'{path}: choice {x.selection} outside the proposals for {x.key}.',
                               fr=f'{path} : choix {x.selection} hors des propositions pour {x.key}.'))
        cases.append(x)
    return cases


def write_tracking(cfg: Config, cases: list[Case], b: Library) -> None:
    by_key = b.by_key()
    hidden = privacy.hidden_keys(b, cfg)
    lines = [header()]
    for c in cases:
        f = by_key.get(c.key)
        cache = c.key in hidden
        container = next((f.fields[k] for k in ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                          if f and f.fields.get(k) and not cache), '')
        doi = f.fields.get('DOI', '') if f and not cache else ''
        in_container = (L(en=f', in “{container[:70]}”', fr=f', dans « {container[:70]} »') if container else '')
        description = (f'# {line(f, hidden)} ({type_name(f.type)}' + in_container
                       + (f', DOI {doi}' if doi else '') + ')') if f else f'# {c.key}'
        lines += ['[[cas]]', description,
                   f'cle = {_toml(c.key)}', f'sous_etape = {_toml(c.substep)}', f'probleme = {_toml(c.problem)}',
                   f'decision = {_toml(c.decision)}', f'choix = {c.selection}', f'forcer = {_toml(c.force)}']
        if c.grade:
            lines.append(f'classe = {_toml(c.grade)}')
        for i, p in enumerate(c.proposals, 1):
            # The note of a source describes the work found, hence the item itself (D126).
            note = privacy.mask() if cache and p.source else p.note
            lines += [f'[[cas.propositions]]  # {i}', f'champs = {_toml(p.fields)}', f'source = {_toml(p.source)}',
                       f'note = {_toml(note)}'] + ([f'avis = {_toml(p.verdict)}'] if p.verdict else [])
        lines.append('')
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    write_toml(cfg.tracking / FILE, lines)


def decide(cases: list[Case], obvious: bool = False, accept: dict[str, int | None] | None = None,
            reject: list[str] = (), except_: set[str] = frozenset()) -> tuple[int, int]:
    """Decisions taken in bulk (D172), instead of writing the file by hand. `obvious` accepts all the obvious cases
    still to judge (except `except_`), with the number zc retained. `accept` gives, by item key, the number of the
    proposal to retain (None for the one zc retained), `reject` the items whose cases are refused.
    A key followed by the problem (« ABCD1234:isbn_manquant ») targets a single case of the item. Only the cases still
    to judge change. Returns the number of cases accepted and refused."""
    accept = accept or {}
    to_judge: dict[str, list[Case]] = {}
    for c in cases:
        if not c.decision:
            to_judge.setdefault(c.key, []).append(c)
            to_judge.setdefault(f'{c.key}:{c.problem}', []).append(c)
    unknowns = [k for k in [*accept, *reject] if k not in to_judge]
    if unknowns:
        names = ', '.join(unknowns)
        raise SystemExit(L(en=f'No case to judge for {names} in {FILE}. Check the key, or run the substep again if '
                              f'the item has just been examined.',
                           fr=f"Aucun cas à juger pour {names} dans {FILE}. Vérifier la clé, ou relancer "
                              f"la sous-étape si la fiche vient d'être examinée."))
    accepted = rejected = 0
    for key, selection in accept.items():
        if selection is not None and len(to_judge[key]) > 1:
            problems = ', '.join(f'{key}:{c.problem}' for c in to_judge[key])
            n_cases = len(to_judge[key])
            raise SystemExit(L(en=f'{key} has {n_cases} cases to judge, a proposal number applies to a single one '
                                  f'only. Target the case by its problem ({problems}).',
                               fr=f'{key} a {n_cases} cas à juger, un numéro de proposition ne vaut que pour '
                                  f'un seul. Viser le cas par son problème ({problems}).'))
        for c in to_judge[key]:
            if selection is not None and not 1 <= selection <= len(c.proposals):
                n_proposals = len(c.proposals)
                raise SystemExit(L(en=f'{key}: proposal {selection} does not exist ({n_proposals} proposal(s)).',
                                   fr=f'{key} : proposition {selection} inexistante ({n_proposals} proposition(s)).'))
            c.decision, c.selection = ACCEPT, selection or c.selection
            accepted += 1
    for key in reject:
        for c in to_judge[key]:
            c.decision = REJECT
            rejected += 1
    if obvious:
        for c in cases:
            if c.grade == 'évident' and not c.decision and c.key not in except_:
                c.decision = ACCEPT
                accepted += 1
    return accepted, rejected


def merge_tracking(previous: list[Case], detected: list[Case], substep: str,
                    scope: set[str] | None = None) -> list[Case]:
    """Keeps the decisions taken. A refused case stays in memory, a resolved case disappears. With `scope`
    (Inbox sorting, D135), only these items were examined, and the cases of the others stay as they are.

    An accepted DOI case that is then resolved leaves the DOIs it ruled out in memory, as a refused
    `doi_manquant` case, so that an item from which a false DOI was removed is not offered the
    discarded candidate again (pilot rehearsal). An accepted case that removes an ISBN leaves an `isbn_retire` case,
    refused, holding the ISBNs then ruled out (pilot bench)."""
    detected_ids = {c.id for c in detected}
    for c in previous:
        skipped = [p for i, p in enumerate(c.proposals, 1) if i != c.selection and p.fields.get('DOI')]
        memory = Case(c.key, IDENTIFIERS, 'doi_manquant', skipped, REJECT)
        if (c.decision == ACCEPT and c.substep == substep == IDENTIFIERS and c.problem.startswith('doi_')
                and c.id not in detected_ids and skipped and (scope is None or c.key in scope)
                and memory.id not in {a.id for a in previous}):
            dois = {p.fields['DOI'].lower() for p in skipped}
            new = next((d for d in detected if d.id == memory.id), None)
            if new:
                new.proposals = [p for p in new.proposals if p.fields.get('DOI', '').lower() not in dois]
                if new.proposals:
                    assign_grade(new)
                    continue
                detected = [d for d in detected if d is not new]
            previous = [*previous, memory]
    for c in previous:
        if (c.decision == ACCEPT and c.substep == substep == IDENTIFIERS
                and c.problem in ('isbn_invalide', 'isbn_discordant') and c.retained().get('ISBN') == ''
                and c.id not in detected_ids and (scope is None or c.key in scope)):
            skipped = [p for i, p in enumerate(c.proposals, 1) if i != c.selection and p.fields.get('ISBN')]
            memory = next((a for a in previous if a.id == (c.key, IDENTIFIERS, REMOVED_ISBN)), None)
            if memory is None:
                previous = [*previous, Case(c.key, IDENTIFIERS, REMOVED_ISBN, skipped, REJECT)]
            else:
                memory.proposals += [p for p in skipped if p.fields not in [q.fields for q in memory.proposals]]
    by_id = {c.id: c for c in previous}
    seen_set, res = set(), []
    for c in detected:
        old = by_id.get(c.id)
        if old and old.decision:
            res.append(old)
        else:
            if old:
                c.force = old.force
            res.append(c)
        seen_set.add(c.id)
    for c in previous:
        if c.id in seen_set:
            continue
        if (c.substep != substep or c.decision == REJECT or c.problem == 'forcer'
                or (scope is not None and c.key not in scope)):
            res.append(c)
    res.sort(key=lambda c: (c.substep, c.decision != '', c.key))
    return res


# --- Identifiers --------------------------------------------------------------

def _first_author(e: Item) -> str:
    return e.author


def _author_ok(e: Item, o: Work) -> bool:
    a, b = norm(_first_author(e)), norm(o.authors[0][0] if o.authors else '')
    return bool(a and b) and (a == b or a in b.split() or b in a.split())


def _year_ok(e: Item, o: Work, gap: int) -> bool:
    a = item_year(e)
    return bool(a and o.year) and abs(int(a) - int(o.year)) <= gap


def _first_page(pages: str) -> str:
    return re.split(r'\s*[-–]\s*', pages.strip(), maxsplit=1)[0] if pages else ''


def same_publication(e: Item, o: Work, threshold: float) -> bool:
    """Is the work found by the item's identifier really the item? (D131)

    Matching titles, or, when the titles differ (translated title, title of the book entered for a
    chapter), same first author, year within one and one more clue (journal, volume, first page)."""
    if titles_match(e.title, o.title, threshold):
        return True
    if not (_author_ok(e, o) and _year_ok(e, o, 1)):
        return False
    container = next((e.fields[k] for k in ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                      if e.fields.get(k)), '')
    page = _first_page(e.fields.get('pages', ''))
    return any((bool(o.volume) and e.fields.get('volume', '').strip() == o.volume,
                bool(page) and page == _first_page(o.pages),
                bool(container and o.container) and similarity(container, o.container) >= threshold,
                bool(o.container) and similarity(e.title, o.container) >= threshold))


def _book_title_ok(e: Item, o: Work, threshold: float) -> bool:
    """For a chapter, the title of the book must match when both are known (D75)."""
    book_title = e.fields.get('bookTitle', '')
    return e.type != 'bookSection' or not book_title or not o.container or similarity(book_title, o.container) >= threshold


def _describe(o: Work, sim: float) -> str:
    """Everything that helps to judge (D79): author, year, type, journal or book, volume, pages, publisher."""
    # A note of a proposal is only shown (tracking file, reports, natures of the plans), never read back: it follows
    # the language of the library.
    author = o.authors[0][0] if o.authors else L(en='n.a.', fr='s. a.')
    container, collection, n_editions, source = o.container[:70], o.collection[:40], o.n_editions, o.source
    details = [x for x in (L(en=f'in “{container}”', fr=f'dans « {container} »') if o.container else '',
                           f'vol. {o.volume}' if o.volume else '',
                           L(en=f'pp. {o.pages}', fr=f'p. {o.pages}') if o.pages else '', o.publisher[:40],
                           o.edition[:30],
                           L(en=f'series {collection}', fr=f'coll. {collection}') if o.collection else '',
                           L(en=f'{n_editions} editions at {source}', fr=f'{n_editions} éditions chez {source}')
                           if o.n_editions > 1 else '') if x]
    title, when = o.title[:90], o.year or L(en='n.d.', fr='s. d.')
    kind = type_name(o.type) if o.type else L(en='unknown type', fr='type inconnu')
    tail = ', ' + ', '.join(details) if details else ''
    return L(en=f'{source}: “{title}”, {author}, {when}, {kind}{tail} (similarity {sim:.2f})',
             fr=f'{source} : « {title} », {author}, {when}, {kind}{tail} (similarité {sim:.2f})')


OBVIOUS_THRESHOLD = 0.9
REVIEWS = ('review', 'compte rendu', 'erratum', 'corrigendum', 'reply', 'comment on')


def work_verdict(e: Item, o: Work, book: bool = False) -> str:
    """What distinguishes the proposed work from the item, or « concorde » (D134, criteria of the `metadata` skill)."""
    problem = []
    if not titles_match(e.title, o.title, OBVIOUS_THRESHOLD):
        problem.append(f'titre {similarity(e.title, o.title):.2f}')
    if not _author_ok(e, o):
        problem.append('auteur')
    if not _year_ok(e, o, 1):
        problem.append('année')
    if o.type and o.type != e.type:
        problem.append('type')
    if book:
        if not _publisher_ok(e, o):
            problem.append('éditeur')
        if o.n_editions > 1:
            problem.append('plusieurs éditions')
    elif not _container_ok(e, o):
        problem.append('revue ou ouvrage')
    if norm(e.title) in GENERIC_TITLES:
        problem.append('titre générique')
    if any(m in norm(o.title) for m in REVIEWS) and not any(m in norm(e.title) for m in REVIEWS):
        problem.append('compte rendu ?')
    return ', '.join(problem) or 'concorde'


def containers_match(a: str, b: str) -> bool:
    """Same journal or same book, give or take a subtitle, a form or an abbreviation (« J. Exp. Psychol. » and
    « Journal of Experimental Psychology »). Two journals differing by one word do not match."""
    if titles_match(a, b, OBVIOUS_THRESHOLD) or same_form('publicationTitle', a, b):
        return True
    x, y = ([m for m in norm(v).split() if m not in STOP_WORDS] for v in (a, b))
    return bool(x) and len(x) == len(y) and all(i.startswith(j) or j.startswith(i) for i, j in zip(x, y))


def _container_ok(e: Item, o: Work) -> bool:
    """Journal, proceedings or book of the item and of the source matching when both are known (D82)."""
    container = next((e.fields[k] for k in ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                      if e.fields.get(k)), '')
    return not container or not o.container or containers_match(container, o.container)


def assign_grade(c: Case) -> Case:
    """Obvious when a single proposal matches in every respect, retained in advance in `selection` (D134), or when an
    unfindable DOI has no other lead than its removal (D169)."""
    if c.problem == 'doi_inconnu' and len(c.proposals) == 1:
        c.grade, c.selection = 'évident', 1
        return c
    good = [i for i, p in enumerate(c.proposals, 1) if p.verdict == 'concorde']
    c.grade = 'évident' if len(good) == 1 else 'douteux'
    if len(good) == 1:
        c.selection = good[0]
    return c


def find_doi(e: Item, services: Services, cfg: Config, exclude: str = '') -> tuple[Proposal | None, list[Proposal]]:
    """Certain candidate (D62), or plausible candidates to judge, for an item without a reliable DOI."""
    m = cfg.metadata
    plausible, seen_set = [], {exclude.lower()}
    for results in services.searches(e.title, _first_author(e), item_year(e)):
        for o in results:
            # Same type required, which rules out the DOI of a book for a chapter (D70).
            if not o.doi or o.doi.lower() in seen_set or o.type != e.type:
                continue
            seen_set.add(o.doi.lower())
            sim = similarity(e.title, o.title)
            prop = Proposal({'DOI': o.doi}, o.source, _describe(o, sim), work_verdict(e, o))
            # A mismatched journal leaves the case to judgment (D82), even if the rest matches.
            if (sim >= m.certain_threshold and _author_ok(e, o) and _year_ok(e, o, m.year_gap)
                    and not generic_title(e.title) and _book_title_ok(e, o, m.mismatch_threshold)
                    and (e.type == 'bookSection' or _container_ok(e, o))):
                return prop, []
            if sim >= m.mismatch_threshold:
                plausible.append(prop)
    return None, plausible[:3]


def _publisher_ok(e: Item, o: Work) -> bool:
    words = [m for m in norm(e.fields.get('publisher', '')).split() if m not in STOP_WORDS | {'editions', 'ed', 'press'}]
    return not words or words[0] in norm(o.publisher).split()


def find_isbn(e: Item, services: Services, cfg: Config) -> tuple[Proposal | None, list[Proposal]]:
    """Certain book (D92, a single suitable edition), or plausible editions to judge (five at most)."""
    m = cfg.metadata
    year = item_year(e)
    retained, plausible, seen_set = [], [], set()
    for results in services.book_searches(e.title, _first_author(e), year):
        for o in results:
            raw = next((x for x in o.isbn for _, ok in isbns(x)[:1] if ok), '')
            if not raw or isbns(raw)[0][0] in seen_set:
                continue
            seen_set.add(isbns(raw)[0][0])
            sim = similarity(e.title, o.title)
            prop = Proposal({'ISBN': raw}, o.source, _describe(o, sim), work_verdict(e, o, book=True))
            if (sim >= m.certain_threshold and _author_ok(e, o) and year and o.year == year and _publisher_ok(e, o)
                    and not generic_title(e.title) and o.n_editions <= 1):
                retained.append(prop)
            elif sim >= m.mismatch_threshold:
                plausible.append(prop)
    if len(retained) == 1:
        return retained[0], []
    return None, (retained + plausible)[:5]


def isbn_forms(isbn: str) -> set[str]:
    """A valid ISBN in digits and its other length (ISBN-13 of an ISBN-10, ISBN-10 of a 978 ISBN-13)."""
    forms = {isbn}
    if len(isbn) == 10 and isbn[:9].isdigit():
        c = '978' + isbn[:9]
        forms.add(c + str((10 - sum(int(x) * (1 if i % 2 == 0 else 3) for i, x in enumerate(c)) % 10) % 10))
    elif len(isbn) == 13 and isbn.startswith('978'):
        body = isbn[3:12]
        check = (11 - sum((10 - i) * int(x) for i, x in enumerate(body)) % 11) % 11
        forms.add(body + ('X' if check == 10 else str(check)))
    return forms


def _isbn_keys(value: str) -> set[str]:
    """Every form of the valid ISBNs of a field, to recognize the same ISBN written in 10 or 13 digits."""
    return {f for i, ok in isbns(value) if ok for f in isbn_forms(i)}


def _edit_distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (x != y))
    return row[-1]


def isbn_gap(current: str, candidate: str) -> int:
    """Characters that separate an invalid ISBN from a candidate, compared at the same length (a typing mistake
    leaves one or two)."""
    gaps = [_edit_distance(current, f) for i, ok in isbns(candidate) if ok for f in isbn_forms(i)
            if len(f) == len(current)]
    return min(gaps, default=99)


def _closest_first(candidates: list[Proposal], wrong: list[str]) -> list[Proposal]:
    """Candidates sorted by their gap to the invalid ISBNs of the field, a gap of one or two characters noted."""
    res = []
    for p in candidates:
        gap = min((isbn_gap(w, p.fields['ISBN']) for w in wrong), default=99)
        note = p.note + (L(en=f', {gap} character(s) away from the current ISBN',
                           fr=f", à {gap} caractère(s) de l'ISBN actuel") if gap <= 2 else '')
        res.append((gap, Proposal(p.fields, p.source, note, p.verdict)))
    return [p for _, p in sorted(res, key=lambda x: x[0])]


def analyze_isbn(e: Item, services: Services, cfg: Config, searchable: bool):
    """ISBN with a wrong checksum, or missing ISBN of a book (D94). An invalid ISBN gives way to a book found with
    certainty by title when the field holds no valid ISBN (as D128 for a DOI), otherwise it is a case to judge whose
    candidates found by title come closest to the current ISBN first."""
    raw = e.fields.get('ISBN', '')
    values = isbns(raw)
    if any(not ok for _, ok in values):
        valid = [i for i, ok in values if ok]
        keep = Proposal({'ISBN': ' '.join(valid)}, '', L(en='keep the valid ISBNs', fr='garder les ISBN valides')
                        if valid else L(en='remove the ISBN', fr="retirer l'ISBN"))
        certain_match, candidates = (find_isbn(e, services, cfg) if searchable and e.type == 'book' and e.title
                                     else (None, []))
        if certain_match and not valid:
            note = certain_match.note
            return Proposal(certain_match.fields, certain_match.source,
                            L(en=f'invalid ISBN ({raw!r}) replaced, {note}', fr=f'ISBN invalide ({raw!r}) remplacé, {note}'))
        kept = _isbn_keys(' '.join(valid))
        candidates = [p for p in ([certain_match] if certain_match else []) + candidates
                      if not _isbn_keys(p.fields['ISBN']) & kept]
        wrong = [i for i, ok in values if not ok]
        return Case(e.key, IDENTIFIERS, 'isbn_invalide', [keep, *_closest_first(candidates, wrong)])
    if values and e.type in ('book', 'bookSection'):
        return mismatched_isbn(e, values[0][0], services, cfg, searchable)
    if not values and e.type == 'book' and searchable and e.title:
        certain_match, candidates = find_isbn(e, services, cfg)
        if certain_match:
            return certain_match
        if candidates:
            return Case(e.key, IDENTIFIERS, 'isbn_manquant', candidates)
    return None


def mismatched_isbn(e: Item, isbn: str, services: Services, cfg: Config, searchable: bool) -> Case | None:
    """Valid ISBN that designates another book (D131, comparison of the titles only). The record read here is the one
    that `fill_in` will read next, the cache serving both, so no extra request, except the search by title
    of a book whose ISBN is wrong."""
    o = services.book(isbn)
    reference = e.title if e.type == 'book' else e.fields.get('bookTitle', '')
    if o is None or not reference or titles_match(reference, o.title, cfg.metadata.mismatch_threshold):
        return None
    drop = Proposal({'ISBN': ''}, '', L(en='remove the ISBN, which designates another book',
                                        fr="retirer l'ISBN, qui désigne un autre livre"))
    described = _describe(o, similarity(reference, o.title))
    keep = Proposal({}, o.source, L(en=f'keep the ISBN, it is right ({described})',
                                    fr=f"garder l'ISBN, il est juste ({described})"),
                    work_verdict(e, o, book=True) if e.type == 'book' else '')
    certain_match, candidates = find_isbn(e, services, cfg) if searchable and e.type == 'book' else (None, [])
    candidates = [p for p in ([certain_match] if certain_match else []) + candidates if isbns(p.fields['ISBN'])[0][0] != isbn]
    return Case(e.key, IDENTIFIERS, 'isbn_discordant', [drop, keep, *candidates])


def isbn_removals(cases: list[Case]) -> tuple[dict[str, set[str]], set[str]]:
    """Items whose ISBN a judged case removed, with every form of the ISBNs then ruled out, and items whose ISBN a
    `forcer` case empties."""
    removed, forced = {}, set()
    for c in cases:
        if c.problem == REMOVED_ISBN:
            ruled_out = c.proposals
        elif (c.substep == IDENTIFIERS and c.problem in ('isbn_invalide', 'isbn_discordant') and c.decision == ACCEPT
              and c.retained().get('ISBN') == ''):
            ruled_out = [p for i, p in enumerate(c.proposals, 1) if i != c.selection]
        else:
            if c.problem == 'forcer' and c.decision == ACCEPT and c.force.get('ISBN') == '':
                forced.add(c.key)
            continue
        removed.setdefault(c.key, set()).update(f for p in ruled_out for f in _isbn_keys(p.fields.get('ISBN', '')))
    return removed, forced


def after_removal(key: str, r, ruled_out: set[str]) -> Case | None:
    """What the book sources find for an item whose ISBN a judged case removed. The ISBNs then ruled out never come
    back, and a new one is a case to judge, never certain, since it would undo the user's decision without asking."""
    if r is None:
        return None
    found = [r] if isinstance(r, Proposal) else r.proposals
    found = [p for p in found if p.fields.get('ISBN') and not _isbn_keys(p.fields['ISBN']) & ruled_out]
    if not found:
        return None
    note = L(en='the ISBN of this item was removed earlier by a judged case',
             fr="l'ISBN de cette fiche a été retiré plus tôt par un cas jugé")
    c = assign_grade(Case(key, IDENTIFIERS, 'isbn_manquant',
                          [Proposal(p.fields, p.source, f'{note}{_SEP()}{p.note}', p.verdict) for p in found]))
    c.grade = 'douteux'
    return c


def _isbn_confirmed(key: str, cases: list[Case]) -> bool:
    """Mismatched ISBN judged right (« garder »). Removing it or choosing another changes it anyway."""
    return any(c.key == key and c.problem == 'isbn_discordant' and c.decision == ACCEPT
               and 'ISBN' not in c.retained() for c in cases)


def analyze_identifiers(e: Item, services: Services, cfg: Config, searchable: bool):
    """Certain proposal, case to judge, or None."""
    raw = e.fields.get('DOI', '')
    drop = Proposal({'DOI': ''}, '', L(en='remove the DOI', fr='retirer le DOI'))
    if raw:
        doi = normalize_doi(raw)
        form = Proposal({'DOI': doi}, '', L(en=f'form fixed ({raw!r})', fr=f'forme corrigée ({raw!r})')) \
            if doi != raw else None
        if not VALID_DOI.match(doi):
            certain_match, candidates = find_doi(e, services, cfg) if searchable else (None, [])
            if certain_match:  # D128: an unusable DOI gives way to a certain candidate
                note = certain_match.note
                return Proposal(certain_match.fields, certain_match.source,
                                L(en=f'malformed DOI ({raw!r}) replaced, {note}',
                                  fr=f'DOI mal formé ({raw!r}) remplacé, {note}'))
            return Case(e.key, IDENTIFIERS, 'doi_malforme', [drop, *candidates])
        o = services.work(doi)
        if o is None:
            if services.exists(doi):
                return form
            certain_match, candidates = find_doi(e, services, cfg, doi) if searchable else (None, [])
            if certain_match:  # D128: a DOI that exists nowhere (JSTOR identifier, typo) gives way
                note = certain_match.note
                return Proposal(certain_match.fields, certain_match.source,
                                L(en=f'nonexistent DOI ({doi}) replaced, {note}',
                                  fr=f'DOI inexistant ({doi}) remplacé, {note}'))
            not_found = Proposal({'DOI': ''}, '', L(en='remove the DOI, which neither doi.org nor the sources know',
                                                    fr='retirer le DOI, que ni doi.org ni les sources ne connaissent'))
            return Case(e.key, IDENTIFIERS, 'doi_inconnu', [not_found, *candidates])
        sim = similarity(e.title, o.title)
        if not same_publication(e, o, cfg.metadata.mismatch_threshold):
            certain_match, candidates = find_doi(e, services, cfg, doi) if searchable else (None, [])
            described = _describe(o, sim)
            keep = Proposal({'DOI': doi} if form else {}, o.source,
                            L(en=f'keep the DOI, it is right ({described})',
                              fr=f'garder le DOI, il est juste ({described})'), work_verdict(e, o))
            return Case(e.key, IDENTIFIERS, 'doi_discordant', [drop, keep, *([certain_match] if certain_match else []), *candidates])
        return form
    if e.type in SEARCHED_TYPES and searchable and e.title:
        certain_match, candidates = find_doi(e, services, cfg)
        if certain_match:
            return certain_match
        if candidates:
            return Case(e.key, IDENTIFIERS, 'doi_manquant', candidates)
    return None


def _SEP() -> str:
    """Separator of the natures of a same item."""
    return L(en='; ', fr=' ; ')


def _judged(what: str) -> str:
    """Nature of a judged case: its problem, or the note of the retained proposal."""
    return L(en=f'judged case ({what})', fr=f'cas jugé ({what})')


def _completed(source: str) -> str:
    """Nature of a completion."""
    return L(en=f'completed from {source}', fr=f'complété depuis {source}')


def _progress(i: int, n: int, show, what: str | None = None) -> None:
    if show and (i % 200 == 0 or i == n):
        if what is None:
            what = L(en='items examined', fr='fiches examinées')
        show(f'{i}/{n} {what}')


def _plan(step: str, proposals: dict[str, tuple[dict, str]], client: Client, description: str,
          hidden: set[str] = frozenset()):
    """Plan of one group per item, with the previous values reread through the API. Also returns the differences."""
    data = client.items(list(proposals))
    groups, skipped = [], []
    for key, (fields, nature) in proposals.items():
        d = data.get(key)
        if d is None or d.get('deleted'):
            skipped.append((key, L(en='item not found or in the trash', fr='fiche introuvable ou à la corbeille')))
            continue
        invalid = [f for f in fields if f not in d]
        if invalid:
            names = ', '.join(invalid)
            skipped.append((key, L(en=f'field(s) missing from this item type ({names})',
                                   fr=f'champ(s) absent(s) de ce type de fiche ({names})')))
            fields = {f: v for f, v in fields.items() if f in d}
        # Already done on the server, the local copy not yet being synchronized, nothing to write.
        fields = {f: v for f, v in fields.items() if d.get(f) != v}
        if not fields:
            continue
        op = Operation(key, {f: plans.raw_value(d, f) for f in fields}, fields, 0, nature)
        groups.append(Group(key, privacy.mask() if key in hidden else d.get('title', '')[:80], [op]))
    return Plan(step, client.user, groups, description=description), skipped


def _within(key: str, keys: set[str] | None) -> bool:
    return keys is None or key in keys


def identifiers(b: Library, cfg: Config, services: Services, client: Client, show=None,
                 keys: set[str] | None = None):
    """`keys` limits the examination to these items (Inbox sorting, D135)."""
    previous = load_tracking(cfg)
    excluded_items = privacy.excluded_items(b, cfg)
    certain, detected, filtered = {}, [], 0
    removed, forced = isbn_removals(previous)
    items = [e for e in b.items if _within(e.key, keys)]
    try:
        for i, e in enumerate(items, 1):
            _progress(i, len(items), show)
            searchable = e.id not in excluded_items
            filtered += not searchable
            isbn_result = None if e.key in forced else analyze_isbn(e, services, cfg, searchable)
            if e.key in removed and not e.fields.get('ISBN'):
                isbn_result = after_removal(e.key, isbn_result, removed[e.key])
            for r in (analyze_identifiers(e, services, cfg, searchable), isbn_result):
                if isinstance(r, Case):
                    detected.append(r if r.grade else assign_grade(r))
                elif r:
                    fields, nature = certain.get(e.key, ({}, ''))
                    source = r.source
                    note = r.note or L(en=f'identifier found, {source}', fr=f'identifiant trouvé, {source}')
                    certain[e.key] = (fields | r.fields, f'{nature}{_SEP()}{note}' if nature else note)
    finally:
        services.persist()
    cases = merge_tracking(previous, detected, IDENTIFIERS, keys)
    write_tracking(cfg, cases, b)
    accepted = {c.key: (c.retained(), _judged(c.problem)) for c in cases
                if c.substep == IDENTIFIERS and c.decision == ACCEPT and c.retained() and _within(c.key, keys)}
    hidden = privacy.hidden_keys(b, cfg)
    # The descriptions and natures of the plans are only shown, never read back: they follow the language of the
    # library.
    plan, skipped = _plan(IDENTIFIERS, certain | accepted, client,
                          L(en='Identifiers (DOI, ISBN) fixed or added.', fr='Identifiants (DOI, ISBN) corrigés ou ajoutés.'),
                          hidden)
    to_judge = [c for c in cases if c.substep == IDENTIFIERS and not c.decision and _within(c.key, keys)]
    return plan, _warn(services, _identifiers_report(plan, to_judge, skipped, filtered, hidden))


def _identifiers_report(plan: Plan, to_judge: list[Case], skipped: list, filtered: int,
                          hidden: set[str] = frozenset()) -> str:
    n_items = len(plan.groups)
    r = [L(en='# Identifiers', fr='# Identifiants'), '',
         L(en=f'{n_items} item(s) modified by this plan (DOI forms fixed, DOIs and ISBNs found with certainty, '
              f'cases judged and accepted).',
           fr=f'{n_items} fiche(s) modifiée(s) par ce plan (formes de DOI corrigées, '
              f'DOI et ISBN trouvés avec certitude, cas jugés et acceptés).'), '']
    if to_judge:
        by_problem = {}
        for c in to_judge:
            by_problem[c.problem] = by_problem.get(c.problem, 0) + 1
        obvious = sum(c.grade == 'évident' for c in to_judge)
        n_cases = len(to_judge)
        listed = ', '.join(f'{n} {p}' for p, n in sorted(by_problem.items()))
        r += [L(en=f'{n_cases} case(s) to judge in suivi/metadonnees.toml: {listed}. Of which {obvious} obvious, where '
                   f'a single proposal matches the item in every respect.',
                fr=f'{n_cases} cas à juger dans suivi/metadonnees.toml : {listed}. Dont {obvious} évident(s), où '
                   f'une seule proposition concorde en tout avec la fiche.'), '']
    if filtered:
        r += [L(en=f'{filtered} item(s) excluded by the privacy filter, never searched by title.',
                fr=f'{filtered} fiche(s) exclue(s) par le filtre de confidentialité, jamais cherchées par titre.'), '']
    if skipped:
        r += [L(en='## Set aside', fr='## Écartées'), ''] + [
            L(en=f'- {c}: {reason}', fr=f'- {c} : {reason}') for c, reason in skipped] + ['']
    r += [L(en='## Detail', fr='## Détail'), '']
    for g in plan.groups:
        op = g.operations[0]
        if g.id in hidden:
            names = ', '.join(op.after)
            r.append(L(en=f'- {g.id} “{g.title}”: {names}', fr=f'- {g.id} « {g.title} » : {names}'))
            continue
        changes = ', '.join(f'{k} {op.before.get(k)!r} → {v!r}' for k, v in op.after.items())
        r.append(L(en=f'- {g.id} “{g.title}”: {changes} ({op.nature})', fr=f'- {g.id} « {g.title} » : {changes} ({op.nature})'))
    return '\n'.join(r) + '\n'


# --- Types ------------------------------------------------------------------------

# Safe transitions when author and year match (D86). « Document » to any recognized type. No
# communication to chapter (D130), since Crossref files proceedings published in a series as chapters (Lecture Notes).
CERTAIN_TRANSITIONS = {('journalArticle', 'bookSection'), ('bookSection', 'journalArticle'),
                     ('journalArticle', 'conferencePaper'), ('bookSection', 'conferencePaper')}
ALWAYS_TO_JUDGE = {'book', 'preprint', 'report', 'thesis', 'encyclopediaArticle'}
META = {'key', 'version', 'itemType', 'dateAdded', 'dateModified', 'collections', 'tags', 'relations', 'creators',
        'deleted', 'parentItem', 'extra'}


def certain_transition(from_: str, to: str) -> bool:
    if from_ in ALWAYS_TO_JUDGE or to in ALWAYS_TO_JUDGE:
        return False
    return (from_, to) in CERTAIN_TRANSITIONS or from_ == 'document'


def conversion(d: dict, to: str, types: ItemTypes) -> tuple[dict, list[str], list[str]]:
    """Fields to write to turn item `d` into type `to` (D85), fields transferred, values copied."""
    from_ = d['itemType']
    after, transfers, copied = {'itemType': to}, [], []
    for f, v in d.items():
        if f in META or not v or f in types.fields.get(to, set()) or f not in types.fields.get(from_, set()):
            continue
        target = types.equivalent(f, from_, to)
        after[f] = ''
        if target and not d.get(target) and target not in after:
            after[target] = v
            transfers.append(f'{f} → {target}')
        else:
            copied.append(f'{f} : {v}')
    if copied:
        after['extra'] = '\n'.join(([d['extra']] if d.get('extra') else []) + copied)
    roles = types.roles.get(to, set())
    creators = d.get('creators') or []
    if any(c.get('creatorType') not in roles for c in creators):
        after['creators'] = [dict(c, creatorType=c['creatorType'] if c.get('creatorType') in roles else 'contributor')
                             for c in creators]
    return after, transfers, copied


def _type_rejected(key: str, cases: list[Case]) -> bool:
    return any(c.key == key and c.substep == TYPES and c.decision == REJECT for c in cases)


def types(b: Library, cfg: Config, services: Services, client: Client, schema: ItemTypes, show=None,
          keys: set[str] | None = None):
    previous = load_tracking(cfg)
    m = cfg.metadata
    hidden = privacy.hidden_keys(b, cfg)
    certain, detected = {}, []
    items = [e for e in b.items if VALID_DOI.match(normalize_doi(e.fields.get('DOI', ''))) and _within(e.key, keys)]
    try:
        for i, e in enumerate(items, 1):
            _progress(i, len(items), show)
            o = services.work(normalize_doi(e.fields['DOI']))
            if not o or not o.type or o.type == e.type or o.type not in schema.fields or _type_rejected(e.key, previous):
                continue
            if not same_publication(e, o, m.mismatch_threshold) and not _confirmed(e.key, previous):
                continue
            local = dict(e.fields, itemType=e.type)
            _, transfers, copied = conversion(local, o.type, schema)
            # The note goes into the plan and the tracking file, where it is only shown: it follows the language of
            # the library. `copied` keeps the « field : value » lines written into Extra, whatever the language.
            change = f'{type_name(e.type)} → {type_name(o.type)}'
            source = o.source
            if e.key in hidden:
                note = L(en=f'{change} according to {source}', fr=f"{change} d'après {source}")
            else:
                described = _describe(o, similarity(e.title, o.title))
                moved = ', '.join(transfers)
                kept = ', '.join(r.split(' : ')[0] for r in copied)
                note = (L(en=f'{change} according to {source} ({described})',
                          fr=f"{change} d'après {source} ({described})")
                        + (L(en=f'. Transferred: {moved}', fr=f'. Transférés : {moved}') if transfers else '')
                        + (L(en=f'. Copied into extra: {kept}', fr=f'. Recopiés dans extra : {kept}') if copied else ''))
            if certain_transition(e.type, o.type) and _author_ok(e, o) and _year_ok(e, o, m.year_gap):
                certain[e.key] = (o.type, note)
            else:
                detected.append(Case(e.key, TYPES, 'type_different', [Proposal({'itemType': o.type}, o.source, note)]))
        # « Document » items without identifier, perhaps books, always to judge (D90).
        excluded_items = privacy.excluded_items(b, cfg)
        documents = []
        for e in b.items:
            if (e.type != 'document' or not _within(e.key, keys) or e.id in excluded_items or not e.title or e.fields.get('DOI')
                    or e.fields.get('ISBN')):
                continue
            certain_match, candidates = find_isbn(e, services, cfg)
            props = [Proposal({'itemType': 'book', 'ISBN': p.fields['ISBN']}, p.source,
                              L(en=f'book: {p.note}', fr=f'livre : {p.note}'))
                     for p in ([certain_match] if certain_match else []) + candidates]
            if props:
                detected.append(Case(e.key, TYPES, 'livre_possible', props))
            else:
                documents.append(e.key)
    finally:
        services.persist()
    detected += duplicate_types(b, cfg, previous, {c.key for c in detected} | set(certain), keys)
    cases = merge_tracking(previous, detected, TYPES, keys)
    write_tracking(cfg, cases, b)
    to = {key: (t, note, {}) for key, (t, note) in certain.items()}
    to |= {c.key: (c.retained()['itemType'], _judged(c.proposals[c.selection - 1].note),
                     {k: v for k, v in c.retained().items() if k != 'itemType'})
             for c in cases if c.substep == TYPES and c.decision == ACCEPT and c.retained().get('itemType')
             and _within(c.key, keys)}
    groups, skipped = [], []
    for k in _conflicting_duplicates(cfg, cases):
        to.pop(k, None)
        skipped.append((k, L(en='another item of the same group of duplicates also changes type, accept only one '
                               'of the two “type_doublon” cases',
                             fr="une autre fiche du même groupe de doublons change aussi de type, n'accepter qu'un "
                                "des deux cas « type_doublon »")))
    data = client.items(list(to))
    for key, (new, note, others) in to.items():
        d = data.get(key)
        if d is None or d.get('deleted'):
            skipped.append((key, L(en='item not found or in the trash', fr='fiche introuvable ou à la corbeille')))
            continue
        if d['itemType'] == new:
            continue
        after, _, _ = conversion(d, new, schema)
        after |= {k: v for k, v in others.items() if k in schema.fields.get(new, set()) and not d.get(k)}
        op = Operation(key, {f: plans.raw_value(d, f) for f in after}, after, 0, note)
        groups.append(Group(key, privacy.mask() if key in hidden else d.get('title', '')[:80], [op]))
    plan = Plan(TYPES, client.user, groups, description=L(en='Item types fixed according to the source of the DOI.',
                                                          fr="Types de fiche corrigés d'après la source du DOI."))
    to_judge = [c for c in cases if c.substep == TYPES and not c.decision and _within(c.key, keys)]
    return plan, _warn(services, _types_report(plan, to_judge, skipped, documents))


def duplicate_types(b: Library, cfg: Config, previous: list[Case], already: set[str],
                       keys: set[str] | None = None) -> list[Case]:
    """Items of a group of duplicates to merge whose types differ, which the merge refuses (D51). Each
    item gets a `type_doublon` case, which proposes the type of the others. Only one is accepted per group, that
    of the item whose type is wrong, which `types` checks. Always to judge, nothing says which type is right."""
    from zot_clean import duplicates
    by_key = b.by_key()
    res = []
    for g in duplicates.load_tracking(cfg):
        items = [by_key[k] for k in g.keys if k in by_key]
        if g.decision != duplicates.MERGE or len(items) != len(g.keys) or len({e.type for e in items}) < 2:
            continue
        for e in items:
            if not _within(e.key, keys) or e.key in already or _type_rejected(e.key, previous):
                continue
            others = [x for x in items if x.key != e.key and x.type != e.type]
            props = []
            for t in dict.fromkeys(x.type for x in others):
                change = f'{type_name(e.type)} → {type_name(t)}'
                of = ', '.join(x.key for x in others if x.type == t)
                props.append(Proposal({'itemType': t}, '', L(
                    en=f'{change}, the type of {of}, duplicate to merge. Accept this case or that of the other item, '
                       f'not both',
                    fr=f"{change}, le type de {of}, doublon à fusionner. Accepter ce cas ou celui de l'autre fiche, "
                       f"pas les deux")))
            res.append(Case(e.key, TYPES, 'type_doublon', props))
    return res


def _conflicting_duplicates(cfg: Config, cases: list[Case]) -> list[str]:
    """Items of the same group of duplicates for which several `type_doublon` cases are accepted, so they would
    swap their types instead of taking just one."""
    from zot_clean import duplicates
    accepted = {c.key for c in cases if c.problem == 'type_doublon' and c.decision == ACCEPT}
    res = []
    for g in duplicates.load_tracking(cfg):
        if g.decision == duplicates.MERGE and len(shared := accepted & set(g.keys)) > 1:
            res += sorted(shared)
    return res


def _types_report(plan: Plan, to_judge: list[Case], skipped: list, documents: list[str] = ()) -> str:
    n_items = len(plan.groups)
    r = [L(en='# Types', fr='# Types'), '',
         L(en=f"{n_items} item(s) change type. The fields that have an equivalent in the new type are transferred "
              f"there, the other values are copied into the extra field, nothing is lost.",
           fr=f"{n_items} fiche(s) changent de type. Les champs qui ont un équivalent dans le "
              f"nouveau type y sont transférés, les autres valeurs sont recopiées dans le champ extra, rien n'est "
              f"perdu."),
         '', L(en='Then run `zc metadata complete`, which will fill the fields of the new type.',
               fr='Lancer ensuite `zc metadata complete`, qui remplira les champs du nouveau type.'), '']
    if to_judge:
        n_cases = len(to_judge)
        r += [L(en=f'{n_cases} type change(s) to judge in suivi/metadonnees.toml.',
                fr=f'{n_cases} changement(s) de type à juger dans suivi/metadonnees.toml.'), '']
    if documents:
        n_documents = len(documents)
        listed = f"{', '.join(documents[:20])}{'…' if len(documents) > 20 else ''}"
        r += [L(en=f'{n_documents} “Document” item(s) with no book found by their title ({listed}). `zc` only '
                   f'proposes a type for items that have a DOI, that look like a known book or that duplicate an '
                   f'item of another type. For the others, the right type is chosen by hand in Zotero, “Item '
                   f'Type” menu of the item.',
                fr=f"{n_documents} fiche(s) « Document » sans livre trouvé par leur titre "
                   f"({listed}). `zc` ne propose un type qu'aux "
                   f"fiches qui ont un DOI, qui ressemblent à un livre connu ou qui doublent une fiche d'un autre "
                   f"type. Pour les autres, le bon type se choisit à la main dans Zotero, menu « Type de document » "
                   f"de la fiche."), '']
    if skipped:
        r += [L(en='## Set aside', fr='## Écartées'), ''] + [
            L(en=f'- {c}: {reason}', fr=f'- {c} : {reason}') for c, reason in skipped] + ['']
    r += [L(en='## Detail', fr='## Détail'), '']
    r += [L(en=f'- {g.id} “{g.title}”: {g.operations[0].nature}', fr=f'- {g.id} « {g.title} » : {g.operations[0].nature}')
          for g in plan.groups]
    return '\n'.join(r) + '\n'


# --- Complements ------------------------------------------------------------------

def _people(listing, role: str) -> list[dict]:
    return [{'creatorType': role, 'lastName': n, 'firstName': p} if p else {'creatorType': role, 'name': n}
            for n, p in listing if n]


def work_fields(o: Work, type_: str, fields: list[str], excluded: dict[str, list[str]] | None = None) -> dict:
    d = {'ISBN': ', '.join(o.isbn), 'ISSN': ', '.join(o.issn), 'date': o.date, 'volume': o.volume, 'issue': o.number,
         'pages': o.pages, 'publisher': o.publisher, 'place': o.place, 'language': o.language,
         'abstractNote': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', o.abstract)).strip(),
         'numPages': o.n_pages, 'edition': o.edition, 'series': o.collection, 'seriesNumber': o.series_number}
    if type_ in CONTAINER:
        d[CONTAINER[type_]] = o.container
    removed = set((excluded or {}).get(type_, []))
    d = {k: v for k, v in d.items() if k in fields and k not in removed and v}
    if 'creators' in fields and 'creators' not in removed:
        creators = _people(o.authors, 'author')
        if type_ in WITH_EDITORS:
            creators += _people(o.editors, 'editor') + _people(o.translators, 'translator')
        if creators:
            d['creators'] = creators
    return d


def _confirmed(key: str, cases: list[Case]) -> bool:
    """Mismatched DOI judged. Removing the DOI or choosing another changes it anyway, stays « garder »."""
    return any(c.key == key and c.problem == 'doi_discordant' and c.decision == ACCEPT for c in cases)


def _to_fill(e: Item, values: dict, o: Work, differences: list) -> dict:
    """Empty fields to fill (D60), language checked on the title (D77). The differences go into `differences`."""
    res = {}
    for f, v in values.items():
        if f == 'language':
            if not e.fields.get(f) and v[:2].lower() == title_language(e.title) != '':
                res[f] = v[:2].lower()
        elif f == 'creators':
            if not e.creators:
                res[f] = v
        elif not e.fields.get(f):
            res[f] = v
        elif not same_form(f, e.fields[f], str(v)):
            # A date of the database copy is shown as entered, without the sortable date before it.
            local = date_as_entered(e.fields[f]) if f in NON_BASE_DATES else e.fields[f]
            differences.append((e.key, f, local, v, o.source))
    return res


def _sortable_date(v: str) -> list[str]:
    """[year, month, day], « 00 » for what is missing. Zotero files « 1991-00-00 1991 »."""
    m = re.match(r'(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?', v.strip())
    return [m.group(1), (m.group(2) or '0').zfill(2), (m.group(3) or '0').zfill(2)] if m else []


def _full_pages(v: str) -> str:
    """« 422-31 » becomes « 422-431 »."""
    start, _, end = re.sub(r'\s*[–—-]+\s*', '-', v.strip()).partition('-')
    if end.isdigit() and start.isdigit() and len(end) < len(start):
        end = start[:len(start) - len(end)] + end
    return f'{start}-{end}' if end else start


def same_form(field_name: str, a: str, b: str) -> bool:
    """Two values that differ only in how they are written (D132): more or less precise date, ISSN or ISBN
    without hyphens or partial, abbreviated pages, initial article of a journal name, accents and case."""
    if field_name == 'date':
        x, y = _sortable_date(a), _sortable_date(b)
        return bool(x and y) and all(i == j or '00' in (i, j) for i, j in zip(x, y))
    if field_name in ('ISSN', 'ISBN'):
        x, y = ({re.sub(r'[^0-9X]', '', s.upper()) for s in re.split(r'[,;\s]+', v) if s} for v in (a, b))
        return bool(x and y) and (x <= y or y <= x)
    if field_name == 'pages':
        x, y = _full_pages(a), _full_pages(b)
        return x == y or ('-' not in x or '-' not in y) and x.split('-')[0] == y.split('-')[0]
    # Long dashes, « & » for « and » or « et », initial article, stop words dropped.
    x, y = ([m for m in norm(re.sub(r'[–—]', '-', v)).split() if m not in STOP_WORDS | {'et'}] for v in (a, b))
    return x == y


def fill_in(b: Library, cfg: Config, services: Services, client: Client, show=None,
              keys: set[str] | None = None):
    cases = load_tracking(cfg)
    m = cfg.metadata
    proposals, differences, mismatches, pending_types, mismatched_isbns = {}, [], [], [], []
    items = [e for e in b.items if VALID_DOI.match(normalize_doi(e.fields.get('DOI', ''))) and _within(e.key, keys)]
    try:
        for i, e in enumerate(items, 1):
            _progress(i, len(items), show)
            o = services.work(normalize_doi(e.fields['DOI']))
            if o is None:
                continue
            if not same_publication(e, o, m.mismatch_threshold) and not _confirmed(e.key, cases):
                mismatches.append((e.key, e.title, o.title, o.source))
                continue
            if o.type and o.type != e.type and not _type_rejected(e.key, cases):
                pending_types.append(e.key)  # D87: the type first
                continue
            values = work_fields(o, e.type, m.fields, m.excluded_by_type)
            if to_fill := _to_fill(e, values, o, differences):
                proposals[e.key] = (to_fill, _completed(o.source))
        # Books and chapters by their ISBN (D90, D93). Values coming from the DOI come first.
        books = [e for e in b.items if e.type in ('book', 'bookSection') and _within(e.key, keys)
                  and any(ok for _, ok in isbns(e.fields.get('ISBN', '')))]
        for n, e in enumerate(books, 1):
            _progress(n, len(books), show, L(en='books and chapters examined by their ISBN',
                                             fr='livres et chapitres examinés par leur ISBN'))
            isbn = next(i for i, ok in isbns(e.fields['ISBN']) if ok)
            o = services.book(isbn)
            if o is None:
                continue
            reference = e.title if e.type == 'book' else e.fields.get('bookTitle', '')
            if (reference and not titles_match(reference, o.title, m.mismatch_threshold)
                    and not _isbn_confirmed(e.key, cases)):
                mismatched_isbns.append((e.key, reference, o.title, o.source))
                continue
            values = work_fields(o, 'book', m.fields, m.excluded_by_type)
            if e.type == 'bookSection':  # record of the book, neither its creators nor its page count
                values = {k: v for k, v in values.items() if k not in ('creators', 'numPages')}
                if 'bookTitle' in m.fields:
                    values['bookTitle'] = o.title
            fields, nature = proposals.get(e.key, ({}, ''))
            values = {k: v for k, v in values.items() if k not in fields}
            if to_fill := _to_fill(e, values, o, differences):
                proposals[e.key] = (fields | to_fill, _SEP().join(filter(None, (nature, _completed(o.source)))))
    finally:
        services.persist()
    imposed = {}
    for c in cases:
        if c.substep == FILL_IN and c.decision == ACCEPT and c.force and _within(c.key, keys):
            fields, _ = proposals.get(c.key, ({}, ''))
            proposals[c.key] = (fields | c.force, L(en='values imposed in suivi/metadonnees.toml',
                                                    fr='valeurs imposées dans suivi/metadonnees.toml'))
            imposed[c.key] = c.force
    # What a `forcer` case settles is no longer reported as skipped nor as different.
    mismatches = [x for x in mismatches if 'DOI' not in imposed.get(x[0], {})]
    mismatched_isbns = [x for x in mismatched_isbns if 'ISBN' not in imposed.get(x[0], {})]
    differences = [x for x in differences if x[1] not in imposed.get(x[0], {})]
    data = client.items(list(proposals))
    # A field filled in Zotero since the database copy is not overwritten.
    for key, (fields, nature) in list(proposals.items()):
        d = data.get(key, {})
        forced = next((c.force for c in cases if c.key == key and c.substep == FILL_IN
                       and c.decision == ACCEPT), {})
        keeper = {f: v for f, v in fields.items() if f in forced or not d.get(f)}
        proposals[key] = (keeper, nature)
    hidden = privacy.hidden_keys(b, cfg)
    plan, skipped = _plan(FILL_IN, {k: v for k, v in proposals.items() if v[0]}, client,
                          L(en='Empty fields completed from the metadata sources.',
                            fr='Champs vides complétés depuis les sources de métadonnées.'), hidden)
    return plan, _warn(services, _complete_report(plan, differences, mismatches, skipped, pending_types,
                                                       mismatched_isbns, hidden, imposed))


def _short(v) -> str:
    return (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))[:70]


def _complete_report(plan: Plan, differences: list, mismatches: list, skipped: list,
                       pending_types: list | None = None, mismatched_isbns: list | None = None,
                       hidden: set[str] = frozenset(), imposed: dict[str, dict] | None = None) -> str:
    """Report of the complements. For a confidential item, the names of the fields without their values (D126).
    Values imposed by a `forcer` case are counted apart from the fields filled from the sources."""
    imposed = imposed or {}
    tallies, forced = {}, {}
    for g in plan.groups:
        for f, v in g.operations[0].after.items():
            if f in imposed.get(g.id, {}):
                what = L(en=f'{f} emptied', fr=f'{f} vidé') if v in ('', [], None) else f
                forced[what] = forced.get(what, 0) + 1
            else:
                tallies[f] = tallies.get(f, 0) + 1
    n_items = len(plan.groups)
    r = [L(en='# Complements', fr='# Compléments'), '',
         L(en=f'{n_items} item(s) completed. Only empty fields are filled, a value already present is never '
              f'replaced, except by a `forcer` case of suivi/metadonnees.toml.',
           fr=f"{n_items} fiche(s) complétée(s). Seuls les champs vides sont remplis, "
              f"une valeur déjà présente n'est jamais remplacée, sauf par un cas `forcer` de suivi/metadonnees.toml."),
         '']
    if tallies:
        listed = ', '.join(f'{f} ({n})' for f, n in sorted(tallies.items()))
        r += [L(en=f'Fields filled: {listed}.', fr=f'Champs remplis : {listed}.'), '']
    if forced:
        listed = ', '.join(f'{f} ({n})' for f, n in sorted(forced.items()))
        r += [L(en=f'Values imposed by a `forcer` case: {listed}.',
                fr=f'Valeurs imposées par un cas `forcer` : {listed}.'), '']
    if mismatches:
        n_skipped = len(mismatches)
        r += [L(en=f'{n_skipped} item(s) skipped, their DOI seems to designate another publication. Judge them '
                   f'first with `zc metadata identifiers`.',
                fr=f"{n_skipped} fiche(s) sautée(s), leur DOI semble désigner une autre publication. Les juger "
                   f"d'abord avec `zc metadata identifiers`."), '']
    if mismatched_isbns:
        n_skipped = len(mismatched_isbns)
        r += [L(en=f'{n_skipped} book(s) or chapter(s) skipped, their ISBN seems to designate another book. Judge '
                   f'them first with `zc metadata identifiers` (`isbn_discordant` case).',
                fr=f"{n_skipped} livre(s) ou chapitre(s) sauté(s), leur ISBN semble désigner un autre livre. "
                   f"Les juger d'abord avec `zc metadata identifiers` (cas `isbn_discordant`)."), '']
    if pending_types:
        n_skipped = len(pending_types)
        r += [L(en=f'{n_skipped} item(s) skipped, their type differs from that of the source. Go through '
                   f'`zc metadata types` first.',
                fr=f"{n_skipped} fiche(s) sautée(s), leur type diffère de celui de la source. Passer d'abord "
                   f"par `zc metadata types`."), '']
    if mismatches or mismatched_isbns:
        r += [L(en='## Skipped, title different from the source', fr='## Sautées, titre différent de la source'), '']
        r += [L(en=f'- {c} ({what}): {privacy.mask()}', fr=f'- {c} ({what}) : {privacy.mask()}') if c in hidden else
              L(en=f'- {c} ({what}): {_short(a)!r} in Zotero, {_short(v)!r} at {s}',
                fr=f'- {c} ({what}) : {_short(a)!r} dans Zotero, {_short(v)!r} chez {s}')
              for what, listing in (('DOI', mismatches), ('ISBN', mismatched_isbns or [])) for c, a, v, s in listing]
        r.append('')
    if skipped:
        r += [L(en='## Set aside', fr='## Écartées'), ''] + [
            L(en=f'- {c}: {reason}', fr=f'- {c} : {reason}') for c, reason in skipped] + ['']
    if differences:
        r += [L(en='## Different values, left as they are', fr='## Valeurs différentes, laissées telles quelles'), '',
              L(en='To impose the value of the source, add a `forcer` case in suivi/metadonnees.toml.',
                fr='Pour imposer la valeur de la source, ajouter un cas `forcer` dans suivi/metadonnees.toml.'), '']
        r += [L(en=f'- {c} {f}: values hidden', fr=f'- {c} {f} : valeurs masquées') if c in hidden else
              L(en=f'- {c} {f}: {_short(a)!r} in Zotero, {_short(v)!r} at {s}',
                fr=f'- {c} {f} : {_short(a)!r} dans Zotero, {_short(v)!r} chez {s}')
              for c, f, a, v, s in differences[:300]]
        if len(differences) > 300:
            more = len(differences) - 300
            r.append(L(en=f'- … and {more} more', fr=f'- … et {more} autres'))
        r.append('')
    r += [L(en='## Detail', fr='## Détail'), '']
    for g in plan.groups:
        op = g.operations[0]
        changes = ', '.join(k if g.id in hidden else f'{k} = {_short(v)!r}' for k, v in op.after.items())
        r.append(L(en=f'- {g.id} “{g.title}”: {changes}', fr=f'- {g.id} « {g.title} » : {changes}'))
    return '\n'.join(r) + '\n'


def _warn(services: Services, report: str) -> str:
    warn_msg = services.warnings()
    if not warn_msg:
        return report
    title, _, rest = report.partition('\n\n')
    return f'{title}\n\n' + ''.join(L(en=f'**Warning.** {a}\n\n', fr=f'**Attention.** {a}\n\n')
                                    for a in warn_msg) + rest


def show_progress(message: str) -> None:
    print(message, file=sys.stderr)
