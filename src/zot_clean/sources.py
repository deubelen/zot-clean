"""Metadata sources, Crossref and OpenAlex to begin with (D17, D59, D63, D64, D67).

Each source returns `Work` objects, a common form drawn from its response. The
responses are cached in `cache/<source>.json` of the working folder, already
reduced to `Work` objects (the raw responses contain the bibliographic
references and are heavy). Rate limited per source, new attempts after a 429,
a 5xx or a network drop. The contact address, if set, is sent only to
Crossref and OpenAlex, as `zc init` announces (D189).
"""

import copy
import html
import json
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import httpx2

from zot_clean import __version__
from zot_clean.config import Config, read_env
from zot_clean.lang import L

ATTEMPTS = 4
SLOW = 20  # seconds, beyond this a response counts as slow
SLOW_MAX = 3  # at the third sign of slowness in a row, the source is set aside
SAVE_INTERVAL = 30  # seconds between two writes of the cache


class SourceUnavailable(Exception):
    """The source refuses to answer (rate limit, outage, key required). Nothing is cached."""


class SearchImpossible(Exception):
    """The source does not search for the moment (no key, daily ceiling reached), reading by DOI remains."""

# Zotero type of a Crossref or OpenAlex type (prototype, fiches.TYPE_CR).
TYPES = {
    'journal-article': 'journalArticle', 'article': 'journalArticle',
    'book': 'book', 'monograph': 'book', 'edited-book': 'book', 'reference-book': 'book',
    'book-chapter': 'bookSection', 'book-section': 'bookSection', 'book-part': 'bookSection',
    'proceedings-article': 'conferencePaper', 'reference-entry': 'encyclopediaArticle',
    'dissertation': 'thesis', 'report': 'report', 'posted-content': 'preprint', 'preprint': 'preprint',
}


@dataclass
class Work:
    source: str
    doi: str = ''
    type: str = ''  # Zotero type, empty if unknown
    title: str = ''
    date: str = ''
    authors: list[list[str]] = field(default_factory=list)  # [last, first], first empty for an institution
    editors: list[list[str]] = field(default_factory=list)
    container: str = ''  # journal, book or proceedings
    volume: str = ''
    number: str = ''
    pages: str = ''
    publisher: str = ''
    place: str = ''
    issn: list[str] = field(default_factory=list)
    isbn: list[str] = field(default_factory=list)
    language: str = ''
    abstract: str = ''
    # Books (D93).
    translators: list[list[str]] = field(default_factory=list)
    n_pages: str = ''
    edition: str = ''
    collection: str = ''
    series_number: str = ''
    n_editions: int = 0  # Open Library: editions of the work, 0 if unknown

    @property
    def year(self) -> str:
        return self.date[:4] if re.match(r'\d{4}', self.date) else ''


# Cache key (`cache/<source>.json`) -> attribute of `Work`. The cache keeps these keys whatever the names in the
# code, so that a cache written by a previous version can be reread (D209).
WORK_FIELDS = {
    'source': 'source', 'doi': 'doi', 'type': 'type', 'titre': 'title', 'date': 'date', 'auteurs': 'authors',
    'editeurs_scientifiques': 'editors', 'conteneur': 'container', 'volume': 'volume',
    'numero': 'number', 'pages': 'pages', 'editeur': 'publisher', 'lieu': 'place', 'issn': 'issn', 'isbn': 'isbn',
    'langue': 'language', 'resume': 'abstract', 'traducteurs': 'translators', 'nb_pages': 'n_pages',
    'edition': 'edition', 'collection': 'collection', 'numero_collection': 'series_number',
    'nb_editions': 'n_editions'}


def work_to_stored(o: Work) -> dict:
    """The work as it is written in the cache."""
    return {key: copy.deepcopy(getattr(o, attribute)) for key, attribute in WORK_FIELDS.items()}


def read_work(d: dict) -> Work:
    return Work(**{WORK_FIELDS[k]: copy.deepcopy(v) for k, v in d.items()})


def norm(s: str) -> str:
    s = html.unescape(html.unescape(s or ''))  # entities sometimes doubled at Crossref (« &amp;amp; »)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # A title without subtitle must be able to match the full title.
    if len(a) >= 25 and (b.startswith(a) or a.startswith(b)):
        return 0.97
    return SequenceMatcher(None, a, b).ratio()


ARTICLES = {'the', 'a', 'an', 'le', 'la', 'les', 'l', 'un', 'une', 'der', 'die', 'das'}


def main_title(title: str) -> str:
    """Title without subtitle, without collection in parentheses nor initial article (D131)."""
    t = re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', title or '')
    t = re.sub(r"['’‘ʼ]", '', t)  # « Mind's » and « Minds », « d’une » and « d'une »
    t = re.split(r'\s*[:?!;]\s*|\.\s+|\s+[-–—]\s+', t.strip(), maxsplit=1)[0]
    words = norm(t).split()
    return ' '.join(words[1:] if len(words) > 1 and words[0] in ARTICLES else words)


def titles_match(a: str, b: str, threshold: float) -> bool:
    """Same title, give or take a subtitle, a collection in parentheses or an initial article (D131).

    Used to check that an identifier already set designates the item, not to choose a candidate."""
    if similarity(a, b) >= threshold:
        return True
    pa, problem = main_title(a), main_title(b)
    return bool(pa) and pa == problem


class Source:
    name = ''
    database = ''

    def __init__(self, cache_folder: Path, contact: str = '', rate: float = 3.0,
                 client_http: httpx2.Client | None = None, wait=time.sleep, clock=time.monotonic):
        self.file = cache_folder / f'{self.name}.json'
        self.contact = contact
        self.interval = 1 / rate if rate > 0 else 0
        self.http = client_http or httpx2.Client(timeout=httpx2.Timeout(15, connect=10), follow_redirects=True)
        self._wait, self._clock = wait, clock
        self._last = -1e9
        self._cache = json.loads(self.file.read_text(encoding='utf-8')) if self.file.is_file() else {}
        self._edits = 0
        self._slow = 0
        self._saved = self._clock()
        self.queried = False  # a request went out during this run, the cache not sufficing

    def headers(self) -> dict[str, str]:
        suffix = f'; mailto:{self.contact}' if self.contact else ''
        return {'User-Agent': f'zot-clean/{__version__} (https://github.com/deubelen/zot-clean{suffix})'}

    def _get(self, url: str, params: dict | None = None, text: bool = False):
        """JSON response, or None if the resource does not exist (404) or if the source refuses the request (400)."""
        cause = ''
        for trial in range(ATTEMPTS):
            pause = self._last + self.interval - self._clock()
            if pause > 0:
                self._wait(pause)
            self._last = start = self._clock()
            self.queried = True
            try:
                r = self.http.get(url, params=params, headers=self.headers())
            except httpx2.TransportError as e:
                kind = e.__class__.__name__
                cause = L(en=f'unreachable ({kind})', fr=f'injoignable ({kind})')
                self._flag_slowness(cause)
                self._wait(5 * (trial + 1))
                continue
            if self._clock() - start > SLOW:
                self._flag_slowness(L(en=f'responses of more than {SLOW} seconds', fr=f'réponses de plus de {SLOW} secondes'))
            else:
                self._slow = 0  # only slowness in a row counts
            if r.status_code in (400, 404):
                return None
            if r.status_code < 300:
                if text:
                    return r.text
                try:
                    return r.json()
                except ValueError:
                    raise SourceUnavailable(L(en=f'{self.name}: unreadable response',
                                              fr=f'{self.name} : réponse illisible')) from None
            detail = f', {r.json().get("message", "")}' if 'json' in r.headers.get('content-type', '') else ''
            cause = L(en=f'response {r.status_code}{detail}', fr=f'réponse {r.status_code}{detail}')
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            self._wait(min(int(r.headers.get('Retry-After', 5 * (trial + 1))), 60))
        raise SourceUnavailable(L(en=f'{self.name}: {cause}', fr=f'{self.name} : {cause}').strip())

    def _flag_slowness(self, cause: str):
        self._slow += 1
        if self._slow >= SLOW_MAX:
            raise SourceUnavailable(L(en=f'{self.name}: too slow at the moment ({cause})',
                                      fr=f'{self.name} : trop lent en ce moment ({cause})'))

    def http_text(self, url: str, params: dict | None = None) -> str | None:
        """Like `_get`, for an XML or text response."""
        return self._get(url, params, text=True)

    def _memo(self, key: str, computation):
        if key not in self._cache:
            self._cache[key] = computation()
            self._edits += 1
            if self._clock() - self._saved > SAVE_INTERVAL:
                self.persist()
        return self._cache[key]

    def persist(self):
        if self._edits:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self._cache, ensure_ascii=False), encoding='utf-8')
        self._saved = self._clock()

    def work(self, doi: str) -> Work | None:
        d = self._memo(f'doi:{doi.lower()}', lambda: self._work(doi))
        return read_work(d) if d else None

    def find(self, title: str, author: str = '', year: str = '') -> list[Work]:
        key = f'q:{norm(title)}|{norm(author)}|{year}'
        return [read_work(d) for d in self._memo(key, lambda: self._find(title, author, year))]

    def book(self, isbn: str) -> Work | None:
        """Record of a book by its ISBN (digits only). Only the book sources have one."""
        d = self._memo(f'isbn:{isbn}', lambda: self._book(isbn))
        return read_work(d) if d else None

    def _book(self, isbn: str) -> dict | None:
        return None

    def _work(self, doi: str) -> dict | None:
        raise NotImplementedError

    def _find(self, title: str, author: str, year: str) -> list[dict]:
        raise NotImplementedError


def _date_parts(d: dict | None) -> str:
    parts = ((d or {}).get('date-parts') or [[None]])[0]
    if not parts or not parts[0]:
        return ''
    return '-'.join(f'{x:02d}' if i else str(x) for i, x in enumerate(parts) if x)


def _people(listing) -> list[list[str]]:
    return [[p.get('family', ''), p.get('given', '')] if p.get('family') else [p.get('name', ''), '']
            for p in listing or [] if p.get('family') or p.get('name')]


class Crossref(Source):
    name = 'crossref'
    database = 'https://api.crossref.org'

    def _params(self, **p) -> dict:
        return dict(p, mailto=self.contact) if self.contact else p

    def _work(self, doi: str) -> dict | None:
        d = self._get(f'{self.database}/works/{urllib.parse.quote(doi, safe="/")}', self._params())
        return work_to_stored(self.read(d['message'])) if d else None

    def _find(self, title: str, author: str, year: str) -> list[dict]:
        q = ' '.join(x for x in (title, author, year) if x)
        d = self._get(f'{self.database}/works', self._params(**{'query.bibliographic': q, 'rows': 5}))
        return [work_to_stored(self.read(m)) for m in (d or {}).get('message', {}).get('items', [])]

    @staticmethod
    def read(m: dict) -> Work:
        title = (m.get('title') or [''])[0]
        under = (m.get('subtitle') or [''])[0]
        if under and under.lower() not in title.lower():
            title = f'{title}: {under}'
        date = ''
        for k in ('published-print', 'published-online', 'issued'):
            if date := _date_parts(m.get(k)):
                break
        containers = m.get('container-title') or ['']
        return Work('crossref', m.get('DOI', ''), TYPES.get(m.get('type', ''), ''), title, date,
                      _people(m.get('author')), _people(m.get('editor')), containers[-1],
                      m.get('volume', ''), m.get('issue', ''), m.get('page', ''), m.get('publisher', ''),
                      m.get('publisher-location', ''), list(m.get('ISSN') or []), list(m.get('ISBN') or []),
                      m.get('language', ''), m.get('abstract', ''))


BUDGET_OPENALEX = 'openalex_budget.json'  # searches of the day, kept when the cache is emptied


class OpenAlex(Source):
    """Reading by DOI is free, searches only with a key and under a daily ceiling (D74)."""
    name = 'openalex'
    database = 'https://api.openalex.org'

    def __init__(self, cache_folder: Path, key: str = '', cap: int = 900, today=None, **kw):
        super().__init__(cache_folder, **kw)
        self.key, self.cap = key, cap
        self._today = today or (lambda: date.today().isoformat())
        self.budget_file = cache_folder / BUDGET_OPENALEX
        self._budget = (json.loads(self.budget_file.read_text(encoding='utf-8'))
                        if self.budget_file.is_file() else {'jour': '', 'recherches': 0})

    def _params(self, **p) -> dict:
        if self.contact:
            p['mailto'] = self.contact
        if self.key:
            p['api_key'] = self.key
        return p

    def _count_search(self):
        if not self.key:
            raise SearchImpossible(L(en='openalex: searches skipped, no OPENALEX_API_KEY key in .env (free at '
                                        'openalex.org)',
                                     fr='openalex : recherches sautées, aucune clé OPENALEX_API_KEY dans .env '
                                        '(gratuite sur openalex.org)'))
        day = self._today()
        if self._budget['jour'] != day:
            self._budget = {'jour': day, 'recherches': 0}
        if self._budget['recherches'] >= self.cap:
            raise SearchImpossible(L(en=f'openalex: ceiling of {self.cap} searches reached for today, run again '
                                        f'tomorrow to continue',
                                     fr=f"openalex : plafond de {self.cap} recherches atteint pour aujourd'hui, "
                                        f"relancer demain pour continuer"))
        self._budget['recherches'] += 1
        self._edits += 1

    def persist(self):
        super().persist()
        if self._budget['jour']:
            self.budget_file.parent.mkdir(parents=True, exist_ok=True)
            self.budget_file.write_text(json.dumps(self._budget), encoding='utf-8')

    def _work(self, doi: str) -> dict | None:
        d = self._get(f'{self.database}/works/doi:{urllib.parse.quote(doi, safe="/")}', self._params())
        return work_to_stored(self.read(d)) if d else None

    def _find(self, title: str, author: str, year: str) -> list[dict]:
        self._count_search()
        # The OpenAlex search refuses certain characters (ellipsis, question marks...).
        q = re.sub(r'\s+', ' ', re.sub(r'[^\w\s-]', ' ', title)).strip()
        d = self._get(f'{self.database}/works', self._params(search=q, **{'per-page': 5}))
        return [work_to_stored(self.read(w)) for w in (d or {}).get('results', [])]

    @staticmethod
    def read(w: dict) -> Work:
        authors = []
        for a in w.get('authorships') or []:
            name = (a.get('author') or {}).get('display_name') or a.get('raw_author_name') or ''
            first_name, _, surname = name.rpartition(' ')
            authors.append([surname, first_name] if surname else [name, ''])
        source = ((w.get('primary_location') or {}).get('source') or {})
        biblio = w.get('biblio') or {}
        pages = '-'.join(p for p in (biblio.get('first_page'), biblio.get('last_page')) if p)
        doi = re.sub(r'^https?://doi\.org/', '', w.get('doi') or '')
        return Work('openalex', doi, TYPES.get(w.get('type', ''), ''), w.get('title') or w.get('display_name') or '',
                      w.get('publication_date') or str(w.get('publication_year') or ''), authors, [],
                      source.get('display_name') or '', biblio.get('volume') or '', biblio.get('issue') or '', pages,
                      source.get('host_organization_name') or '', '', list(source.get('issn') or []), [],
                      w.get('language') or '', '')


# --- Book sources (D90 to D93) ----------------------------------------------------

UNIMARC_ROLES = {'070': 'authors', '340': 'editors', '730': 'translators'}
LANGUAGES = {'fre': 'fr', 'eng': 'en', 'ger': 'de', 'spa': 'es', 'ita': 'it', 'por': 'pt', 'lat': 'la'}


def _clean(v: str) -> str:
    v = v.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
    return re.sub(r'\s+', ' ', re.sub(r'[\[\]]', '', v)).strip(' ,;:/.')


def read_unimarc(record: str, source: str) -> Work | None:
    """UNIMARC record in XML (BnF, Sudoc), read as in the prototype."""
    fields = [(tag, [(c, _clean(v)) for c, v in re.findall(r'code="(.)">([^<]*)', body)])
              for tag, body in re.findall(r'<(?:\w+:)?datafield tag="(\d+)"[^>]*>(.*?)</(?:\w+:)?datafield>',
                                           record, re.S)]
    first_field = lambda tag: next((f for t, f in fields if t == tag), [])
    under = lambda f, code: [v for c, v in f if c == code]
    f200 = first_field('200')
    if not f200:
        return None
    title = (under(f200, 'a') or [''])[0]
    title = re.split(r'\.\s+(?:Chronologie|Traduction|Trad\.|Présentation|Préface|Introduction|Texte)\b', title)[0]
    # Old records, with the statement of responsibility and edition copied into the title.
    title = re.split(r'\s*,\s*(?:par|by|publié|trad)\b', title)[0].strip(' ,')
    if complement := under(f200, 'e'):
        title += ' : ' + ' : '.join(complement)
    o = Work(source, type='book', title=title)
    for tag in ('700', '701', '702'):
        for f in (f for t, f in fields if t == tag):
            code = (under(f, '4') or ['070' if tag != '702' else ''])[0]
            listing = UNIMARC_ROLES.get(code)
            person = [' '.join(under(f, 'a')), ' '.join(under(f, 'b'))]
            if listing and person[0] and person not in getattr(o, listing):
                getattr(o, listing).append(person)
    pub = first_field('210') or first_field('214')
    o.place = (under(pub, 'a') or [''])[0]
    o.publisher = re.sub(r'\s*\([^)]*impr[^)]*\)', '', (under(pub, 'c') or [''])[0])
    # Old records, with « Paris, Presses universitaires de France » in a single subfield.
    if not o.place and ', ' in o.publisher:
        o.place, o.publisher = o.publisher.split(', ', 1)
    elif not o.publisher and ', ' in o.place:
        o.place, o.publisher = o.place.split(', ', 1)
    if date := re.search(r'\d{4}', ' '.join(under(pub, 'd'))):
        o.date = date.group(0)
    if pages := re.search(r'(\d+)\s*p\b', ' '.join(under(first_field('215'), 'a'))):
        o.n_pages = pages.group(1)
    o.edition = (under(first_field('205'), 'a') or [''])[0]
    o.collection = (under(first_field('225'), 'a') or [''])[0]
    o.series_number = (under(first_field('225'), 'v') or [''])[0]
    o.isbn = [x for t, f in fields if t == '010' for x in under(f, 'a')]
    code = (under(first_field('101'), 'a') or [''])[0]
    o.language = LANGUAGES.get(code, '')
    return o


class BnF(Source):
    name = 'bnf'
    database = 'https://catalogue.bnf.fr/api/SRU'

    def _sru(self, request: str, n: int) -> list[Work]:
        xml = self.http_text(self.database, {'version': '1.2', 'operation': 'searchRetrieve',
                                          'recordSchema': 'unimarcxchange', 'maximumRecords': n, 'query': request})
        return [o for o in (read_unimarc(r, self.name) for r in re.findall(r'<mxc:record.*?</mxc:record>', xml or '',
                                                                           re.S)) if o]

    def _book(self, isbn: str) -> dict | None:
        res = self._sru(f'bib.isbn adj "{isbn}"', 3)
        return work_to_stored(res[0]) if res else None

    def _find(self, title: str, author: str, year: str) -> list[dict]:
        t, a = (re.sub(r'["\\]', ' ', x) for x in (title, author))
        request = f'bib.title all "{t}"' + (f' and bib.author all "{a}"' if a else '')
        return [work_to_stored(o) for o in self._sru(request, 10)]


class Sudoc(Source):
    """By ISBN only, Sudoc has no public API for searching by title."""
    name = 'sudoc'
    database = 'https://www.sudoc.fr'

    def _book(self, isbn: str) -> dict | None:
        # The format goes in the path, as the prototype does.
        d = self._get(f'{self.database}/services/isbn2ppn/{isbn}&format=text/json') or {}
        res = d.get('sudoc', {}).get('query', {}).get('result', [])
        for r in res if isinstance(res, list) else [res]:
            if o := read_unimarc(self.http_text(f"{self.database}/{r['ppn']}.xml") or '', self.name):
                return work_to_stored(o)
        return None

    def _find(self, title: str, author: str, year: str) -> list[dict]:
        return []


class OpenLibrary(Source):
    name = 'openlibrary'
    database = 'https://openlibrary.org'

    def _author(self, key: str) -> str:
        return self._memo(f'auteur:{key}', lambda: (self._get(f'{self.database}{key}.json') or {}).get('name', ''))

    @staticmethod
    def _person(name: str) -> list[str]:
        first_name, _, surname = name.rpartition(' ')
        return [surname, first_name] if surname else [name, '']

    def _book(self, isbn: str) -> dict | None:
        d = self._get(f'{self.database}/isbn/{isbn}.json')
        if not d or not d.get('title'):
            return None
        date = re.search(r'\d{4}', d.get('publish_date', ''))
        return work_to_stored(Work(
            self.name, type='book', title=d['title'] + (f" : {d['subtitle']}" if d.get('subtitle') else ''),
            date=date.group(0) if date else '', authors=[self._person(n) for a in d.get('authors', [])
                                                         if (n := self._author(a['key']))],
            publisher=(d.get('publishers') or [''])[0], place=(d.get('publish_places') or [''])[0],
            isbn=list(d.get('isbn_13', []) + d.get('isbn_10', [])), n_pages=str(d.get('number_of_pages') or '')))

    def _find(self, title: str, author: str, year: str) -> list[dict]:
        fields = 'key,title,author_name,editions,editions.title,editions.publish_date,editions.isbn,editions.publisher'
        d = self._get(f'{self.database}/search.json', {'title': title, 'author': author, 'limit': 5, 'fields': fields}) or {}
        res = []
        for w in d.get('docs', []):
            editions = w.get('editions') or {}
            for e in editions.get('docs', [])[:1]:
                date = re.search(r'\d{4}', ' '.join(e.get('publish_date', [])))
                res.append(work_to_stored(Work(self.name, type='book', title=e.get('title') or w.get('title', ''),
                                         date=date.group(0) if date else '',
                                         authors=[self._person(n) for n in w.get('author_name', [])],
                                         publisher=(e.get('publisher') or [''])[0], isbn=list(e.get('isbn', [])),
                                         n_editions=int(editions.get('numFound') or 0))))
        return res


def isbn_chunks(value: str) -> list[str]:
    """Digits of each ISBN of a field. Several ISBNs are separated by a comma, a semicolon or a space,
    but an ISBN can itself be written with spaces (« 978 90 272 5202 9 »): a group that makes up
    10 or 13 digits by itself is a single ISBN."""
    res = []
    for group in re.split(r'[,;]+', value or ''):
        compact = re.sub(r'[^\dX]', '', group.upper())
        res += [compact] if len(compact) in (10, 13) else \
            [re.sub(r'[^\dX]', '', raw.upper()) for raw in group.split()]
    return res


def isbns(value: str) -> list[tuple[str, bool]]:
    """ISBNs of a field, in digits, with the validity of their checksum."""
    res = []
    for c in isbn_chunks(value):
        if len(c) == 10:
            ok = c[:9].isdigit() and sum((10 - i) * (10 if x == 'X' else int(x)) for i, x in enumerate(c)) % 11 == 0
        elif len(c) == 13 and c.isdigit():
            ok = sum(int(x) * (1 if i % 2 == 0 else 3) for i, x in enumerate(c)) % 10 == 0
        else:
            continue
        res.append((c, ok))
    return res


def francophone(isbn: str) -> bool:
    return isbn.startswith(('9782', '97910')) or (len(isbn) == 10 and isbn.startswith('2'))


class Resolver(Source):
    """Existence of a DOI, whichever agency assigned it."""
    name = 'doi'
    database = 'https://doi.org/api/handles'

    def exists(self, doi: str) -> bool:
        return self._memo(f'doi:{doi.lower()}', lambda: bool(
            (d := self._get(f'{self.database}/{urllib.parse.quote(doi, safe="/")}')) and d.get('responseCode') == 1))


@dataclass
class Services:
    """Active sources, in the order of D67. An unavailable source is set aside for the rest of the run."""
    sources: list[Source]
    resolver: Resolver
    books: list[Source] = field(default_factory=list)  # BnF, Sudoc, Open Library
    unavailable: dict[str, str] = field(default_factory=dict)
    no_search: dict[str, str] = field(default_factory=dict)

    def _active(self):
        return [s for s in self.sources if s.name not in self.unavailable]

    def work(self, doi: str) -> Work | None:
        for s in self._active():
            try:
                if o := s.work(doi):
                    return o
            except SourceUnavailable as e:
                self.unavailable[s.name] = str(e)
        return None

    def searches(self, title: str, author: str = '', year: str = ''):
        """Results of each active source, source by source."""
        for s in self._active():
            if s.name in self.no_search:
                continue
            try:
                results = s.find(title, author, year)
            except SearchImpossible as e:
                self.no_search[s.name] = str(e)
                continue
            except SourceUnavailable as e:
                self.unavailable[s.name] = str(e)
                continue
            yield results

    def exists(self, doi: str) -> bool:
        """Unable to check it, a DOI is presumed to exist, so as not to declare anything unknown wrongly."""
        if self.resolver.name in self.unavailable:
            return True
        try:
            return self.resolver.exists(doi)
        except SourceUnavailable as e:
            self.unavailable[self.resolver.name] = str(e)
            return True

    def book(self, isbn: str) -> Work | None:
        """Record of a book, sources in the order of D91 according to the language of the ISBN."""
        order = ['bnf', 'sudoc', 'openlibrary'] if francophone(isbn) else ['openlibrary', 'sudoc', 'bnf']
        for s in sorted(self.books, key=lambda s: order.index(s.name) if s.name in order else 9):
            if s.name in self.unavailable:
                continue
            try:
                if o := s.book(isbn):
                    return o
            except SourceUnavailable as e:
                self.unavailable[s.name] = str(e)
        return None

    def book_searches(self, title: str, author: str = '', year: str = ''):
        """Results of the BnF then Open Library (D91)."""
        for s in self.books:
            if s.name in self.unavailable or s.name == 'sudoc':
                continue
            try:
                yield s.find(title, author, year)
            except SourceUnavailable as e:
                self.unavailable[s.name] = str(e)

    def warnings(self) -> list[str]:
        return [L(en=f'Source set aside during this run, {cause}. Run again later to query it (the cache keeps '
                     f'everything already obtained).',
                  fr=f'Source mise de côté pendant cette exécution, {cause}. Relancer plus tard pour la consulter '
                     f'(le cache garde tout ce qui a déjà été obtenu).') for cause in self.unavailable.values()] + \
               [f'{cause[0].upper()}{cause[1:]}.' for cause in self.no_search.values()]

    def contact_note(self) -> str:
        """Short note when Crossref or OpenAlex were queried during this run without a contact address, which is
        optional (D189). Empty otherwise."""
        if not any(s.queried and not s.contact for s in self.sources):
            return ''
        return L(en='No contact address in config.toml ([sources] contact), so Crossref and OpenAlex answered more '
                    'slowly. It is optional.',
                 fr="Pas d'adresse de contact dans config.toml ([sources] contact), Crossref et OpenAlex ont donc "
                    "répondu plus lentement. Elle est facultative.")

    def persist(self):
        for s in (*self.sources, *self.books, self.resolver):
            s.persist()


def from_config(cfg: Config, refresh: bool = False, client_http: httpx2.Client | None = None, **kw) -> Services:
    if refresh:
        # Responses only. The count of the day's searches stays, otherwise the OpenAlex ceiling would restart from 0.
        for f in cfg.cache.glob('*.json'):
            if f.name != BUDGET_OPENALEX:
                f.unlink()
    common = dict(contact=cfg.sources.contact, rate=cfg.sources.rate, client_http=client_http, **kw)
    sources: list[Source] = []
    if cfg.sources.crossref:
        sources.append(Crossref(cfg.cache, **common))
    if cfg.sources.openalex:
        sources.append(OpenAlex(cfg.cache, key=read_env(cfg.workspace).get('OPENALEX_API_KEY', ''),
                                cap=cfg.sources.openalex_cap, **common))
    anonymous = common | {'contact': ''}
    books: list[Source] = []
    for cls, active in ((BnF, cfg.sources.bnf), (Sudoc, cfg.sources.sudoc), (OpenLibrary, cfg.sources.openlibrary)):
        if active:
            # Open Library asks to stay under one request per second.
            books.append(cls(cfg.cache, **(anonymous | ({'rate': min(1.0, cfg.sources.rate)}
                                                         if cls is OpenLibrary else {}))))
    return Services(sources, Resolver(cfg.cache, **anonymous), books)
