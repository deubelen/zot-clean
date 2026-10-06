"""Sources de métadonnées, Crossref et OpenAlex pour commencer (D17, D59, D63, D64, D67).

Chaque source rend des `Oeuvre`, forme commune tirée de sa réponse. Les
réponses sont mises en cache dans `cache/<source>.json` du dossier de travail,
déjà réduites à des `Oeuvre` (les réponses brutes contiennent les références
bibliographiques et pèsent lourd). Débit limité par source, nouveaux essais
après un 429, un 5xx ou une coupure. L'adresse de contact, si elle est réglée,
ne part qu'à Crossref et OpenAlex, comme `zc init` l'annonce (D189).
"""

import html
import json
import re
import time
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import httpx2

from zot_clean import __version__
from zot_clean.config import Config, lire_env

ESSAIS = 4
LENTE = 20  # secondes, au-delà une réponse compte comme lente
LENTES_MAX = 3  # au troisième signe de lenteur d'affilée, la source est mise de côté
SAUVEGARDE = 30  # secondes entre deux écritures du cache


class SourceIndisponible(Exception):
    """La source refuse de répondre (limite de débit, panne, clé exigée). Rien n'est mis en cache."""


class RechercheImpossible(Exception):
    """La source ne fait pas de recherche pour le moment (pas de clé, plafond du jour atteint), la lecture par DOI reste."""

# Type Zotero d'un type Crossref ou OpenAlex (prototype, fiches.TYPE_CR).
TYPES = {
    'journal-article': 'journalArticle', 'article': 'journalArticle',
    'book': 'book', 'monograph': 'book', 'edited-book': 'book', 'reference-book': 'book',
    'book-chapter': 'bookSection', 'book-section': 'bookSection', 'book-part': 'bookSection',
    'proceedings-article': 'conferencePaper', 'reference-entry': 'encyclopediaArticle',
    'dissertation': 'thesis', 'report': 'report', 'posted-content': 'preprint', 'preprint': 'preprint',
}


@dataclass
class Oeuvre:
    source: str
    doi: str = ''
    type: str = ''  # type Zotero, vide si inconnu
    titre: str = ''
    date: str = ''
    auteurs: list[list[str]] = field(default_factory=list)  # [nom, prénom], prénom vide pour une institution
    editeurs_scientifiques: list[list[str]] = field(default_factory=list)
    conteneur: str = ''  # revue, ouvrage ou actes
    volume: str = ''
    numero: str = ''
    pages: str = ''
    editeur: str = ''
    lieu: str = ''
    issn: list[str] = field(default_factory=list)
    isbn: list[str] = field(default_factory=list)
    langue: str = ''
    resume: str = ''
    # Livres (D93).
    traducteurs: list[list[str]] = field(default_factory=list)
    nb_pages: str = ''
    edition: str = ''
    collection: str = ''
    numero_collection: str = ''
    nb_editions: int = 0  # Open Library : éditions de l'œuvre, 0 si inconnu

    @property
    def annee(self) -> str:
        return self.date[:4] if re.match(r'\d{4}', self.date) else ''


def norm(s: str) -> str:
    s = html.unescape(html.unescape(s or ''))  # entités parfois doublées chez Crossref (« &amp;amp; »)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def similarite(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Un titre sans sous-titre doit pouvoir correspondre au titre complet.
    if len(a) >= 25 and (b.startswith(a) or a.startswith(b)):
        return 0.97
    return SequenceMatcher(None, a, b).ratio()


ARTICLES = {'the', 'a', 'an', 'le', 'la', 'les', 'l', 'un', 'une', 'der', 'die', 'das'}


def titre_principal(titre: str) -> str:
    """Titre sans sous-titre, sans collection entre parenthèses ni article initial (D131)."""
    t = re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', titre or '')
    t = re.sub(r"['’‘ʼ]", '', t)  # « Mind's » et « Minds », « d’une » et « d'une »
    t = re.split(r'\s*[:?!;]\s*|\.\s+|\s+[-–—]\s+', t.strip(), maxsplit=1)[0]
    mots = norm(t).split()
    return ' '.join(mots[1:] if len(mots) > 1 and mots[0] in ARTICLES else mots)


def titres_concordants(a: str, b: str, seuil: float) -> bool:
    """Même titre, à un sous-titre, une collection entre parenthèses ou un article initial près (D131).

    Sert à vérifier qu'un identifiant déjà posé désigne bien la fiche, et non à choisir un candidat."""
    if similarite(a, b) >= seuil:
        return True
    pa, pb = titre_principal(a), titre_principal(b)
    return bool(pa) and pa == pb


class Source:
    nom = ''
    base = ''

    def __init__(self, dossier_cache: Path, contact: str = '', debit: float = 3.0,
                 client_http: httpx2.Client | None = None, attendre=time.sleep, horloge=time.monotonic):
        self.fichier = dossier_cache / f'{self.nom}.json'
        self.contact = contact
        self.intervalle = 1 / debit if debit > 0 else 0
        self.http = client_http or httpx2.Client(timeout=httpx2.Timeout(15, connect=10), follow_redirects=True)
        self._attendre, self._horloge = attendre, horloge
        self._dernier = -1e9
        self._cache = json.loads(self.fichier.read_text(encoding='utf-8')) if self.fichier.is_file() else {}
        self._modifs = 0
        self._lentes = 0
        self._sauve = self._horloge()

    def entetes(self) -> dict[str, str]:
        suffixe = f'; mailto:{self.contact}' if self.contact else ''
        return {'User-Agent': f'zot-clean/{__version__} (https://github.com/deubelen/zot-clean{suffixe})'}

    def _get(self, url: str, params: dict | None = None, texte: bool = False):
        """Réponse JSON, ou None si la ressource n'existe pas (404) ou si la source refuse la requête (400)."""
        motif = ''
        for essai in range(ESSAIS):
            pause = self._dernier + self.intervalle - self._horloge()
            if pause > 0:
                self._attendre(pause)
            self._dernier = debut = self._horloge()
            try:
                r = self.http.get(url, params=params, headers=self.entetes())
            except httpx2.TransportError as e:
                motif = f'injoignable ({e.__class__.__name__})'
                self._signaler_lenteur(motif)
                self._attendre(5 * (essai + 1))
                continue
            if self._horloge() - debut > LENTE:
                self._signaler_lenteur(f'réponses de plus de {LENTE} secondes')
            else:
                self._lentes = 0  # seules les lenteurs d'affilée comptent
            if r.status_code in (400, 404):
                return None
            if r.status_code < 300:
                if texte:
                    return r.text
                try:
                    return r.json()
                except ValueError:
                    raise SourceIndisponible(f'{self.nom} : réponse illisible') from None
            motif = f'réponse {r.status_code}' + (f', {r.json().get("message", "")}' if 'json' in
                                                   r.headers.get('content-type', '') else '')
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            self._attendre(min(int(r.headers.get('Retry-After', 5 * (essai + 1))), 60))
        raise SourceIndisponible(f'{self.nom} : {motif}'.strip())

    def _signaler_lenteur(self, motif: str):
        self._lentes += 1
        if self._lentes >= LENTES_MAX:
            raise SourceIndisponible(f'{self.nom} : trop lent en ce moment ({motif})')

    def http_texte(self, url: str, params: dict | None = None) -> str | None:
        """Comme `_get`, pour une réponse XML ou texte."""
        return self._get(url, params, texte=True)

    def _memo(self, cle: str, calcul):
        if cle not in self._cache:
            self._cache[cle] = calcul()
            self._modifs += 1
            if self._horloge() - self._sauve > SAUVEGARDE:
                self.sauver()
        return self._cache[cle]

    def sauver(self):
        if self._modifs:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            self.fichier.write_text(json.dumps(self._cache, ensure_ascii=False), encoding='utf-8')
        self._sauve = self._horloge()

    def oeuvre(self, doi: str) -> Oeuvre | None:
        d = self._memo(f'doi:{doi.lower()}', lambda: self._oeuvre(doi))
        return Oeuvre(**d) if d else None

    def chercher(self, titre: str, auteur: str = '', annee: str = '') -> list[Oeuvre]:
        cle = f'q:{norm(titre)}|{norm(auteur)}|{annee}'
        return [Oeuvre(**d) for d in self._memo(cle, lambda: self._chercher(titre, auteur, annee))]

    def livre(self, isbn: str) -> Oeuvre | None:
        """Notice d'un livre par son ISBN (chiffres seuls). Seules les sources de livres en ont."""
        d = self._memo(f'isbn:{isbn}', lambda: self._livre(isbn))
        return Oeuvre(**d) if d else None

    def _livre(self, isbn: str) -> dict | None:
        return None

    def _oeuvre(self, doi: str) -> dict | None:
        raise NotImplementedError

    def _chercher(self, titre: str, auteur: str, annee: str) -> list[dict]:
        raise NotImplementedError


def _date_parts(d: dict | None) -> str:
    parts = ((d or {}).get('date-parts') or [[None]])[0]
    if not parts or not parts[0]:
        return ''
    return '-'.join(f'{x:02d}' if i else str(x) for i, x in enumerate(parts) if x)


def _personnes(liste) -> list[list[str]]:
    return [[p.get('family', ''), p.get('given', '')] if p.get('family') else [p.get('name', ''), '']
            for p in liste or [] if p.get('family') or p.get('name')]


class Crossref(Source):
    nom = 'crossref'
    base = 'https://api.crossref.org'

    def _params(self, **p) -> dict:
        return dict(p, mailto=self.contact) if self.contact else p

    def _oeuvre(self, doi: str) -> dict | None:
        d = self._get(f'{self.base}/works/{urllib.parse.quote(doi, safe="/")}', self._params())
        return asdict(self.lire(d['message'])) if d else None

    def _chercher(self, titre: str, auteur: str, annee: str) -> list[dict]:
        q = ' '.join(x for x in (titre, auteur, annee) if x)
        d = self._get(f'{self.base}/works', self._params(**{'query.bibliographic': q, 'rows': 5}))
        return [asdict(self.lire(m)) for m in (d or {}).get('message', {}).get('items', [])]

    @staticmethod
    def lire(m: dict) -> Oeuvre:
        titre = (m.get('title') or [''])[0]
        sous = (m.get('subtitle') or [''])[0]
        if sous and sous.lower() not in titre.lower():
            titre = f'{titre}: {sous}'
        date = ''
        for k in ('published-print', 'published-online', 'issued'):
            if date := _date_parts(m.get(k)):
                break
        conteneurs = m.get('container-title') or ['']
        return Oeuvre('crossref', m.get('DOI', ''), TYPES.get(m.get('type', ''), ''), titre, date,
                      _personnes(m.get('author')), _personnes(m.get('editor')), conteneurs[-1],
                      m.get('volume', ''), m.get('issue', ''), m.get('page', ''), m.get('publisher', ''),
                      m.get('publisher-location', ''), list(m.get('ISSN') or []), list(m.get('ISBN') or []),
                      m.get('language', ''), m.get('abstract', ''))


class OpenAlex(Source):
    """Lecture par DOI gratuite, recherches seulement avec une clé et sous un plafond quotidien (D74)."""
    nom = 'openalex'
    base = 'https://api.openalex.org'

    def __init__(self, dossier_cache: Path, cle: str = '', plafond: int = 900, aujourdhui=None, **kw):
        super().__init__(dossier_cache, **kw)
        self.cle, self.plafond = cle, plafond
        self._aujourdhui = aujourdhui or (lambda: date.today().isoformat())
        self.fichier_budget = dossier_cache / 'openalex_budget.json'
        self._budget = (json.loads(self.fichier_budget.read_text(encoding='utf-8'))
                        if self.fichier_budget.is_file() else {'jour': '', 'recherches': 0})

    def _params(self, **p) -> dict:
        if self.contact:
            p['mailto'] = self.contact
        if self.cle:
            p['api_key'] = self.cle
        return p

    def _compter_recherche(self):
        if not self.cle:
            raise RechercheImpossible('openalex : recherches sautées, aucune clé OPENALEX_API_KEY dans .env '
                                      '(gratuite sur openalex.org)')
        jour = self._aujourdhui()
        if self._budget['jour'] != jour:
            self._budget = {'jour': jour, 'recherches': 0}
        if self._budget['recherches'] >= self.plafond:
            raise RechercheImpossible(f'openalex : plafond de {self.plafond} recherches atteint pour aujourd\'hui, '
                                      'relancer demain pour continuer')
        self._budget['recherches'] += 1
        self._modifs += 1

    def sauver(self):
        super().sauver()
        if self._budget['jour']:
            self.fichier_budget.parent.mkdir(parents=True, exist_ok=True)
            self.fichier_budget.write_text(json.dumps(self._budget), encoding='utf-8')

    def _oeuvre(self, doi: str) -> dict | None:
        d = self._get(f'{self.base}/works/doi:{urllib.parse.quote(doi, safe="/")}', self._params())
        return asdict(self.lire(d)) if d else None

    def _chercher(self, titre: str, auteur: str, annee: str) -> list[dict]:
        self._compter_recherche()
        # La recherche d'OpenAlex refuse certains signes (points de suspension, points d'interrogation…).
        q = re.sub(r'\s+', ' ', re.sub(r'[^\w\s-]', ' ', titre)).strip()
        d = self._get(f'{self.base}/works', self._params(search=q, **{'per-page': 5}))
        return [asdict(self.lire(w)) for w in (d or {}).get('results', [])]

    @staticmethod
    def lire(w: dict) -> Oeuvre:
        auteurs = []
        for a in w.get('authorships') or []:
            nom = (a.get('author') or {}).get('display_name') or a.get('raw_author_name') or ''
            prenom, _, famille = nom.rpartition(' ')
            auteurs.append([famille, prenom] if famille else [nom, ''])
        source = ((w.get('primary_location') or {}).get('source') or {})
        biblio = w.get('biblio') or {}
        pages = '-'.join(p for p in (biblio.get('first_page'), biblio.get('last_page')) if p)
        doi = re.sub(r'^https?://doi\.org/', '', w.get('doi') or '')
        return Oeuvre('openalex', doi, TYPES.get(w.get('type', ''), ''), w.get('title') or w.get('display_name') or '',
                      w.get('publication_date') or str(w.get('publication_year') or ''), auteurs, [],
                      source.get('display_name') or '', biblio.get('volume') or '', biblio.get('issue') or '', pages,
                      source.get('host_organization_name') or '', '', list(source.get('issn') or []), [],
                      w.get('language') or '', '')


# --- Sources de livres (D90 à D93) ----------------------------------------------------

ROLES_UNIMARC = {'070': 'auteurs', '340': 'editeurs_scientifiques', '730': 'traducteurs'}
LANGUES = {'fre': 'fr', 'eng': 'en', 'ger': 'de', 'spa': 'es', 'ita': 'it', 'por': 'pt', 'lat': 'la'}


def _nettoyer(v: str) -> str:
    v = v.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
    return re.sub(r'\s+', ' ', re.sub(r'[\[\]]', '', v)).strip(' ,;:/.')


def lire_unimarc(notice: str, source: str) -> Oeuvre | None:
    """Notice UNIMARC en XML (BnF, Sudoc), lue comme dans le prototype."""
    champs = [(tag, [(c, _nettoyer(v)) for c, v in re.findall(r'code="(.)">([^<]*)', corps)])
              for tag, corps in re.findall(r'<(?:\w+:)?datafield tag="(\d+)"[^>]*>(.*?)</(?:\w+:)?datafield>',
                                           notice, re.S)]
    prem = lambda tag: next((f for t, f in champs if t == tag), [])
    sous = lambda f, code: [v for c, v in f if c == code]
    f200 = prem('200')
    if not f200:
        return None
    titre = (sous(f200, 'a') or [''])[0]
    titre = re.split(r'\.\s+(?:Chronologie|Traduction|Trad\.|Présentation|Préface|Introduction|Texte)\b', titre)[0]
    # Notices anciennes : mention de responsabilité et d'édition recopiées dans le titre.
    titre = re.split(r'\s*,\s*(?:par|by|publié|trad)\b', titre)[0].strip(' ,')
    if complement := sous(f200, 'e'):
        titre += ' : ' + ' : '.join(complement)
    o = Oeuvre(source, type='book', titre=titre)
    for tag in ('700', '701', '702'):
        for f in (f for t, f in champs if t == tag):
            code = (sous(f, '4') or ['070' if tag != '702' else ''])[0]
            liste = ROLES_UNIMARC.get(code)
            personne = [' '.join(sous(f, 'a')), ' '.join(sous(f, 'b'))]
            if liste and personne[0] and personne not in getattr(o, liste):
                getattr(o, liste).append(personne)
    pub = prem('210') or prem('214')
    o.lieu = (sous(pub, 'a') or [''])[0]
    o.editeur = re.sub(r'\s*\([^)]*impr[^)]*\)', '', (sous(pub, 'c') or [''])[0])
    # Notices anciennes : « Paris, Presses universitaires de France » dans un seul sous-champ.
    if not o.lieu and ', ' in o.editeur:
        o.lieu, o.editeur = o.editeur.split(', ', 1)
    elif not o.editeur and ', ' in o.lieu:
        o.lieu, o.editeur = o.lieu.split(', ', 1)
    if date := re.search(r'\d{4}', ' '.join(sous(pub, 'd'))):
        o.date = date.group(0)
    if pages := re.search(r'(\d+)\s*p\b', ' '.join(sous(prem('215'), 'a'))):
        o.nb_pages = pages.group(1)
    o.edition = (sous(prem('205'), 'a') or [''])[0]
    o.collection = (sous(prem('225'), 'a') or [''])[0]
    o.numero_collection = (sous(prem('225'), 'v') or [''])[0]
    o.isbn = [x for t, f in champs if t == '010' for x in sous(f, 'a')]
    code = (sous(prem('101'), 'a') or [''])[0]
    o.langue = LANGUES.get(code, '')
    return o


class BnF(Source):
    nom = 'bnf'
    base = 'https://catalogue.bnf.fr/api/SRU'

    def _sru(self, requete: str, n: int) -> list[Oeuvre]:
        xml = self.http_texte(self.base, {'version': '1.2', 'operation': 'searchRetrieve',
                                          'recordSchema': 'unimarcxchange', 'maximumRecords': n, 'query': requete})
        return [o for o in (lire_unimarc(r, self.nom) for r in re.findall(r'<mxc:record.*?</mxc:record>', xml or '',
                                                                           re.S)) if o]

    def _livre(self, isbn: str) -> dict | None:
        res = self._sru(f'bib.isbn adj "{isbn}"', 3)
        return asdict(res[0]) if res else None

    def _chercher(self, titre: str, auteur: str, annee: str) -> list[dict]:
        t, a = (re.sub(r'["\\]', ' ', x) for x in (titre, auteur))
        requete = f'bib.title all "{t}"' + (f' and bib.author all "{a}"' if a else '')
        return [asdict(o) for o in self._sru(requete, 10)]


class Sudoc(Source):
    """Par ISBN seulement, le Sudoc n'a pas d'API publique de recherche par titre."""
    nom = 'sudoc'
    base = 'https://www.sudoc.fr'

    def _livre(self, isbn: str) -> dict | None:
        # Le format se passe dans le chemin, comme le fait le prototype.
        d = self._get(f'{self.base}/services/isbn2ppn/{isbn}&format=text/json') or {}
        res = d.get('sudoc', {}).get('query', {}).get('result', [])
        for r in res if isinstance(res, list) else [res]:
            if o := lire_unimarc(self.http_texte(f"{self.base}/{r['ppn']}.xml") or '', self.nom):
                return asdict(o)
        return None

    def _chercher(self, titre: str, auteur: str, annee: str) -> list[dict]:
        return []


class OpenLibrary(Source):
    nom = 'openlibrary'
    base = 'https://openlibrary.org'

    def _auteur(self, cle: str) -> str:
        return self._memo(f'auteur:{cle}', lambda: (self._get(f'{self.base}{cle}.json') or {}).get('name', ''))

    @staticmethod
    def _personne(nom: str) -> list[str]:
        prenom, _, famille = nom.rpartition(' ')
        return [famille, prenom] if famille else [nom, '']

    def _livre(self, isbn: str) -> dict | None:
        d = self._get(f'{self.base}/isbn/{isbn}.json')
        if not d or not d.get('title'):
            return None
        date = re.search(r'\d{4}', d.get('publish_date', ''))
        return asdict(Oeuvre(
            self.nom, type='book', titre=d['title'] + (f" : {d['subtitle']}" if d.get('subtitle') else ''),
            date=date.group(0) if date else '', auteurs=[self._personne(n) for a in d.get('authors', [])
                                                         if (n := self._auteur(a['key']))],
            editeur=(d.get('publishers') or [''])[0], lieu=(d.get('publish_places') or [''])[0],
            isbn=list(d.get('isbn_13', []) + d.get('isbn_10', [])), nb_pages=str(d.get('number_of_pages') or '')))

    def _chercher(self, titre: str, auteur: str, annee: str) -> list[dict]:
        champs = 'key,title,author_name,editions,editions.title,editions.publish_date,editions.isbn,editions.publisher'
        d = self._get(f'{self.base}/search.json', {'title': titre, 'author': auteur, 'limit': 5, 'fields': champs}) or {}
        res = []
        for w in d.get('docs', []):
            editions = w.get('editions') or {}
            for e in editions.get('docs', [])[:1]:
                date = re.search(r'\d{4}', ' '.join(e.get('publish_date', [])))
                res.append(asdict(Oeuvre(self.nom, type='book', titre=e.get('title') or w.get('title', ''),
                                         date=date.group(0) if date else '',
                                         auteurs=[self._personne(n) for n in w.get('author_name', [])],
                                         editeur=(e.get('publisher') or [''])[0], isbn=list(e.get('isbn', [])),
                                         nb_editions=int(editions.get('numFound') or 0))))
        return res


def morceaux_isbn(valeur: str) -> list[str]:
    """Chiffres de chaque ISBN d'un champ. Plusieurs ISBN se séparent par une virgule, un point-virgule ou une
    espace, mais un ISBN peut lui-même s'écrire avec des espaces (« 978 90 272 5202 9 ») : un groupe qui fait à
    lui seul 10 ou 13 chiffres est un seul ISBN."""
    res = []
    for groupe in re.split(r'[,;]+', valeur or ''):
        compact = re.sub(r'[^\dX]', '', groupe.upper())
        res += [compact] if len(compact) in (10, 13) else \
            [re.sub(r'[^\dX]', '', brut.upper()) for brut in groupe.split()]
    return res


def isbns(valeur: str) -> list[tuple[str, bool]]:
    """ISBN d'un champ, en chiffres, avec la validité de leur somme de contrôle."""
    res = []
    for c in morceaux_isbn(valeur):
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


class Resolveur(Source):
    """Existence d'un DOI, quelle que soit l'agence qui l'a attribué."""
    nom = 'doi'
    base = 'https://doi.org/api/handles'

    def existe(self, doi: str) -> bool:
        return self._memo(f'doi:{doi.lower()}', lambda: bool(
            (d := self._get(f'{self.base}/{urllib.parse.quote(doi, safe="/")}')) and d.get('responseCode') == 1))


@dataclass
class Services:
    """Sources actives, dans l'ordre de D67. Une source indisponible est mise de côté pour le reste de l'exécution."""
    sources: list[Source]
    resolveur: Resolveur
    livres: list[Source] = field(default_factory=list)  # BnF, Sudoc, Open Library
    indisponibles: dict[str, str] = field(default_factory=dict)
    sans_recherche: dict[str, str] = field(default_factory=dict)

    def _actives(self):
        return [s for s in self.sources if s.nom not in self.indisponibles]

    def oeuvre(self, doi: str) -> Oeuvre | None:
        for s in self._actives():
            try:
                if o := s.oeuvre(doi):
                    return o
            except SourceIndisponible as e:
                self.indisponibles[s.nom] = str(e)
        return None

    def recherches(self, titre: str, auteur: str = '', annee: str = ''):
        """Résultats de chaque source active, source par source."""
        for s in self._actives():
            if s.nom in self.sans_recherche:
                continue
            try:
                resultats = s.chercher(titre, auteur, annee)
            except RechercheImpossible as e:
                self.sans_recherche[s.nom] = str(e)
                continue
            except SourceIndisponible as e:
                self.indisponibles[s.nom] = str(e)
                continue
            yield resultats

    def existe(self, doi: str) -> bool:
        """Faute de pouvoir le vérifier, un DOI est présumé exister, pour ne rien déclarer inconnu à tort."""
        if self.resolveur.nom in self.indisponibles:
            return True
        try:
            return self.resolveur.existe(doi)
        except SourceIndisponible as e:
            self.indisponibles[self.resolveur.nom] = str(e)
            return True

    def livre(self, isbn: str) -> Oeuvre | None:
        """Notice d'un livre, sources dans l'ordre de D91 selon la langue de l'ISBN."""
        ordre = ['bnf', 'sudoc', 'openlibrary'] if francophone(isbn) else ['openlibrary', 'sudoc', 'bnf']
        for s in sorted(self.livres, key=lambda s: ordre.index(s.nom) if s.nom in ordre else 9):
            if s.nom in self.indisponibles:
                continue
            try:
                if o := s.livre(isbn):
                    return o
            except SourceIndisponible as e:
                self.indisponibles[s.nom] = str(e)
        return None

    def recherches_livre(self, titre: str, auteur: str = '', annee: str = ''):
        """Résultats de la BnF puis d'Open Library (D91)."""
        for s in self.livres:
            if s.nom in self.indisponibles or s.nom == 'sudoc':
                continue
            try:
                yield s.chercher(titre, auteur, annee)
            except SourceIndisponible as e:
                self.indisponibles[s.nom] = str(e)

    def avertissements(self) -> list[str]:
        return [f'Source mise de côté pendant cette exécution, {motif}. Relancer plus tard pour la consulter '
                '(le cache garde tout ce qui a déjà été obtenu).' for motif in self.indisponibles.values()] + \
               [f'{motif[0].upper()}{motif[1:]}.' for motif in self.sans_recherche.values()]

    def sauver(self):
        for s in (*self.sources, *self.livres, self.resolveur):
            s.sauver()


def depuis_config(cfg: Config, rafraichir: bool = False, client_http: httpx2.Client | None = None, **kw) -> Services:
    if rafraichir:
        for f in cfg.cache.glob('*.json'):
            f.unlink()
    commun = dict(contact=cfg.sources.contact, debit=cfg.sources.debit, client_http=client_http, **kw)
    sources: list[Source] = []
    if cfg.sources.crossref:
        sources.append(Crossref(cfg.cache, **commun))
    if cfg.sources.openalex:
        sources.append(OpenAlex(cfg.cache, cle=lire_env(cfg.dossier_travail).get('OPENALEX_API_KEY', ''),
                                plafond=cfg.sources.plafond_openalex, **commun))
    anonyme = commun | {'contact': ''}
    livres: list[Source] = []
    for classe, actif in ((BnF, cfg.sources.bnf), (Sudoc, cfg.sources.sudoc), (OpenLibrary, cfg.sources.openlibrary)):
        if actif:
            # Open Library demande de rester sous une requête par seconde.
            livres.append(classe(cfg.cache, **(anonyme | ({'debit': min(1.0, cfg.sources.debit)}
                                                         if classe is OpenLibrary else {}))))
    return Services(sources, Resolveur(cfg.cache, **anonyme), livres)
