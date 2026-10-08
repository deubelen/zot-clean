"""Synthetic, messy Zotero library for the pilot bench (D237).

`generate(language, seed, type_fields)` returns the library as the Zotero web API would hold it (items,
collections, settings, saved searches, files stored online), the files to put on the disk (`storage/<KEY>/…`),
and what the fake metadata services know (Crossref, OpenAlex, doi.org, BnF, Sudoc, Open Library). Everything is
invented: titles, people, journals and publishers. DOIs use the Crossref test prefix 10.5555.

The library is messy on purpose, so that every cleanup step has something to do: certain and doubtful duplicates,
identical PDFs, missing or malformed DOIs, wrong item types, empty fields the sources can fill, a chaotic
collection tree, automatic and imported tags, status tags from other habits, citation keys duplicated or left in
Extra, PDFs with names that do not follow Zotero's template, recent items outside any collection, one confidential
item. The conventions of the method (roots, statuses) are not created: the cleanup creates them.
"""

import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'
USER = 4242
DOI_PREFIX = '10.5555'
PRIVATE_TAG = {'fr': '_privé', 'en': '_private'}

# --- Vocabulary -------------------------------------------------------------------------------------------------

FIRST_FR = ['Marie', 'Claire', 'Julien', 'Sophie', 'Antoine', 'Camille', 'Nicolas', 'Élise', 'Thomas', 'Hélène',
            'Mathieu', 'Agnès', 'Pierre', 'Lucie', 'Samir', 'Inès', 'Benoît', 'Nadia', 'François', 'Aurélie']
LAST_FR = ['Lefèvre', 'Morel', 'Garnier', 'Rousseau', 'Mercier', 'Blanchard', 'Faure', 'Chevalier', 'Perrin',
           'Lemaire', 'Gauthier', 'Roussel', 'Marchand', 'Barbier', 'Colin', 'Arnaud', 'Giraud', 'Benali',
           'Haddad', 'Ferrand', 'Vasseur', 'Delorme', 'Texier', 'Aubert', 'Lacombe', 'Pélissier']
FIRST_EN = ['Emily', 'James', 'Hannah', 'Daniel', 'Grace', 'Oliver', 'Ruth', 'Samuel', 'Alice', 'Henry', 'Maya',
            'Thomas', 'Clara', 'Isaac', 'Leah', 'Patrick', 'Nora', 'Victor', 'Amira', 'Lucas']
LAST_EN = ['Whitfield', 'Harlow', 'Okafor', 'Brennan', 'Castellanos', 'Lindqvist', 'Mehta', 'Pemberton',
           'Ashworth', 'Galloway', 'Thornbury', 'Kessler', 'Delaney', 'Marsh', 'Fairbanks', 'Holloway', 'Quinlan',
           'Rowntree', 'Sandoval', 'Tremaine', 'Underhill', 'Vance', 'Winslow', 'Yardley', 'Abernethy', 'Coulter']

# Each theme: collection names (old tree), topics (noun, article) or plain English nouns, publics, journals,
# automatic tags from databases, concept tags.
THEMES = {
    'fr': [
        dict(id='educ', topics=[('école', "l'"), ('orientation scolaire', "l'"), ('inégalités scolaires', 'les'),
                                ('enseignement supérieur', "l'"), ('classes préparatoires', 'les'),
                                ('décrochage scolaire', 'le'), ('travail enseignant', 'le')],
             publics=['familles populaires', 'enseignants débutants', 'lycéens professionnels', 'étudiants boursiers'],
             journals=[("Cahiers de sociologie de l'éducation", '1765-4410'), ('Revue des savoirs scolaires', '2109-3352')],
             auto=['Education', 'Sociology', 'France', 'Schools', 'Students'], concepts=['capital culturel', 'habitus']),
        dict(id='hist', topics=[('ouvriers du textile', 'les'), ('grève de 1936', 'la'), ('mutuelles', 'les'),
                                ('immigration italienne', "l'"), ('logement ouvrier', 'le'), ('syndicalisme', 'le')],
             publics=['ouvrières lyonnaises', 'mineurs du Nord', 'cheminots', 'petits commerçants'],
             journals=[('Histoire et société', '1953-6118'), ('Revue d’histoire sociale contemporaine', '2271-8890')],
             auto=['History', 'France', 'Labor', 'Social Conditions'], concepts=['domination', 'classe ouvrière']),
        dict(id='sci', topics=[('statistique publique', 'la'), ('hygiénisme', "l'"), ('psychologie expérimentale', 'la'),
                               ('laboratoires', 'les'), ('médecine sociale', 'la')],
             publics=['savants', 'médecins de province', 'ingénieurs des mines'],
             journals=[('Revue d’histoire des savoirs', '2427-0261')],
             auto=['History', 'Science', 'Medicine'], concepts=['expertise']),
        dict(id='meth', topics=[('entretien', "l'"), ('observation participante', "l'"), ('archives orales', 'les'),
                                ('questionnaire', 'le'), ('analyse de réseaux', "l'")],
             publics=['enquêteurs', 'doctorants', 'chercheurs en sciences sociales'],
             journals=[('Enquêtes et méthodes', '2490-8177')],
             auto=['Qualitative Research', 'Interviews as Topic', 'Methods'], concepts=['réflexivité']),
        dict(id='philo', topics=[('reconnaissance', 'la'), ('soin', 'le'), ('justice sociale', 'la'),
                                 ('expérience', "l'"), ('vulnérabilité', 'la')],
             publics=['philosophes', 'soignants'],
             journals=[('Revue de philosophie sociale', '2552-1490')],
             auto=['Philosophy', 'Ethics'], concepts=['reconnaissance', 'domination']),
        dict(id='ling', topics=[('plurilinguisme', 'le'), ('accents', 'les'), ('norme linguistique', 'la'),
                                ('langues régionales', 'les')],
             publics=['élèves allophones', 'locuteurs bilingues'],
             journals=[('Langages et sociétés contemporaines', '2117-6024')],
             auto=['Language', 'Linguistics', 'France'], concepts=['habitus']),
    ],
    'en': [
        dict(id='educ', topics=['schooling', 'vocational tracking', 'educational inequality', 'higher education',
                                'elite schools', 'school dropout', "teachers' work"],
             publics=['working-class families', 'novice teachers', 'vocational students', 'first-generation students'],
             journals=[('Education and Society Review', '1765-4410'), ('Journal of School Knowledge', '2109-3352')],
             auto=['Education', 'Sociology', 'United Kingdom', 'Schools', 'Students'],
             concepts=['cultural capital', 'habitus']),
        dict(id='hist', topics=['textile workers', 'the general strike', 'friendly societies', 'Irish immigration',
                                'working-class housing', 'trade unionism'],
             publics=['mill girls', 'coal miners', 'railwaymen', 'shopkeepers'],
             journals=[('Social History Quarterly', '1953-6118'), ('Review of Labour History', '2271-8890')],
             auto=['History', 'United Kingdom', 'Labor', 'Social Conditions'], concepts=['domination', 'working class']),
        dict(id='sci', topics=['official statistics', 'public hygiene', 'experimental psychology', 'laboratories',
                               'social medicine'],
             publics=['savants', 'country doctors', 'mining engineers'],
             journals=[('History of Knowledge Review', '2427-0261')],
             auto=['History', 'Science', 'Medicine'], concepts=['expertise']),
        dict(id='meth', topics=['the interview', 'participant observation', 'oral archives', 'the questionnaire',
                                'network analysis'],
             publics=['fieldworkers', 'doctoral students', 'social scientists'],
             journals=[('Methods in Qualitative Inquiry', '2490-8177')],
             auto=['Qualitative Research', 'Interviews as Topic', 'Methods'], concepts=['reflexivity']),
        dict(id='philo', topics=['recognition', 'care', 'social justice', 'experience', 'vulnerability'],
             publics=['philosophers', 'caregivers'],
             journals=[('Review of Social Philosophy', '2552-1490')],
             auto=['Philosophy', 'Ethics'], concepts=['recognition', 'domination']),
        dict(id='ling', topics=['multilingualism', 'accents', 'linguistic norms', 'minority languages'],
             publics=['newly arrived pupils', 'bilingual speakers'],
             journals=[('Language in Context', '2117-6024')],
             auto=['Language', 'Linguistics', 'United Kingdom'], concepts=['habitus']),
    ],
}

TITLES = {
    'fr': ['{T} en France (1880-1940)', 'Sociologie {de}', '{T} : enquête auprès des {p}', 'Penser {t} : enjeux '
           'théoriques et méthodologiques', 'Les transformations {de} depuis les années 1980', 'Retour sur {t}',
           '{T} au prisme du genre', 'Une histoire sociale {de}', '{T} et ses publics', 'Les usages sociaux {de}',
           '{T} : le point de vue des {p}', '{T}, un objet pour les sciences sociales', 'Les frontières {de}',
           '{T} en question : regards croisés', 'Les mondes {de}', 'Gouverner {t}'],
    'en': ['{T} in Britain, 1880-1940', 'The sociology of {t}', '{T}: an ethnography of {p}', 'Rethinking {t}: '
           'theoretical and methodological issues', 'The transformation of {t} since the 1980s', '{T} revisited',
           '{T} through the lens of gender', 'A social history of {t}', '{T} and its publics',
           'The social uses of {t}', '{T}: the view from {p}', '{T} as an object for the social sciences',
           'The boundaries of {t}', '{T} in question: crossed perspectives', 'The worlds of {t}', 'Governing {t}'],
}
ABSTRACT = {
    'fr': "Cet article examine {t} à partir d'une enquête menée auprès des {p}. Il montre comment les "
          "transformations récentes {de} recomposent les pratiques et les représentations, et propose de "
          "reconsidérer les catégories habituelles de l'analyse.",
    'en': 'This article examines {t} on the basis of fieldwork among {p}. It shows how recent changes in {t} '
          'reshape practices and representations, and argues for a reconsideration of the usual categories of '
          'analysis.',
}
PUBLISHERS = {
    'fr': [('Éditions Lirac', 'Paris'), ('Presses universitaires de Vallon', 'Rennes'),
           ('Éditions de la Licorne', 'Lyon'), ('Belval', 'Paris')],
    'en': [('Harrow University Press', 'Oxford'), ('Northgate Press', 'London'), ('Linden & Moss', 'Chicago')],
}
VOLUMES = {
    'fr': ['{T} : état des savoirs', 'Dictionnaire critique {de}', 'Nouvelles approches {de}'],
    'en': ['{T}: the state of the art', 'A critical companion to {t}', 'New approaches to {t}'],
}

# Old tree of collections, with numbered prefixes, a catch-all, variants and project leftovers. (name, parent, themes)
TREE = {
    'fr': [('00 À lire', None, ()), ('01 Thèse', None, ()), ('Chapitre 1 - cadrage', '01 Thèse', ('educ', 'meth')),
           ('Chapitre 2 - terrain', '01 Thèse', ('educ',)), ('Chapitre 3', '01 Thèse', ()),
           ('02 Cours', None, ()), ("L2 Sociologie de l'éducation", '02 Cours', ('educ',)),
           ('M1 Méthodes', '02 Cours', ('meth',)), ('03 Article RFS 2022', None, ('hist',)),
           ('Divers', None, ()), ('Sociologie', None, ()), ('Éducation', 'Sociologie', ('educ',)),
           ('Inégalités', 'Éducation', ('educ',)), ('Méthodes qualitatives', 'Sociologie', ('meth',)),
           ('Histoire', None, ()), ('Histoire sociale', 'Histoire', ('hist',)),
           ('histoire des sciences', 'Histoire', ('sci',)), ('XIXe siècle', 'histoire des sciences', ('sci',)),
           ('Philosophie', None, ('philo',)), ('philo', None, ('philo',)), ('Linguistique', None, ('ling',)),
           ('Colloque Lyon 2021', None, ('ling', 'educ')), ('Vieux trucs', None, ()),
           ('Import Mendeley', None, ())],
    'en': [('00 To read', None, ()), ('01 Dissertation', None, ()),
           ('Chapter 1 - framing', '01 Dissertation', ('educ', 'meth')),
           ('Chapter 2 - fieldwork', '01 Dissertation', ('educ',)), ('Chapter 3', '01 Dissertation', ()),
           ('02 Teaching', None, ()), ('SOC201 Sociology of education', '02 Teaching', ('educ',)),
           ('Methods seminar', '02 Teaching', ('meth',)), ('03 Paper draft 2022', None, ('hist',)),
           ('Misc', None, ()), ('Sociology', None, ()), ('Education', 'Sociology', ('educ',)),
           ('Inequality', 'Education', ('educ',)), ('Qualitative methods', 'Sociology', ('meth',)),
           ('History', None, ()), ('Social history', 'History', ('hist',)),
           ('history of science', 'History', ('sci',)), ('Nineteenth century', 'history of science', ('sci',)),
           ('Philosophy', None, ('philo',)), ('philosophy', None, ('philo',)), ('Linguistics', None, ('ling',)),
           ('Leeds conference 2021', None, ('ling', 'educ')), ('Old stuff', None, ()),
           ('Mendeley import', None, ())],
}
# Status and mark tags from other habits, then variants of a same tag, then keywords imported with a record.
HABITS = {
    'fr': dict(to_read=['à lire', 'A lire', 'toread'], read=['lu', 'Lu'], reading=['en cours'],
               marks=['important', 'imprimé'], variants=[['méthodologie', 'Méthodologie', 'methodologie'],
                                                        ['inégalités', 'inegalites']],
               keywords=['scolarisation', 'parcours', 'lycée', 'trajectoires', 'mobilité', 'réussite', 'famille',
                         'territoire', 'genre', 'politique éducative', 'ségrégation', 'quartiers']),
    'en': dict(to_read=['to read', 'To Read', 'toread'], read=['read', 'Read'], reading=['reading now'],
               marks=['important', 'printed copy'], variants=[['methodology', 'Methodology', 'methodolgy'],
                                                             ['inequality', 'inequalities']],
               keywords=['schooling', 'pathways', 'secondary school', 'trajectories', 'mobility', 'attainment',
                         'family', 'territory', 'gender', 'education policy', 'segregation', 'neighbourhoods']),
}
CONJUNCTION = {'fr': 'et', 'en': 'and'}
MESSY_NAMES = ['article.pdf', 'fulltext.pdf', 'download.pdf', 'scan0012.pdf', '1-s2.0-S0000000000-main.pdf',
               'document(3).pdf', 'pdf.pdf', 'texte_integral.pdf']

# --- Small helpers ----------------------------------------------------------------------------------------------


def ascii_fold(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def isbn13(rng: random.Random, prefix: str) -> str:
    body = prefix + ''.join(rng.choice('0123456789') for _ in range(12 - len(prefix)))
    check = (10 - sum(int(x) * (1 if i % 2 == 0 else 3) for i, x in enumerate(body)) % 10) % 10
    return body + str(check)


def hyphenate(isbn: str) -> str:
    return f'{isbn[:3]}-{isbn[3]}-{isbn[4:8]}-{isbn[8:12]}-{isbn[12]}'


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def phrases(language: str, topic) -> dict:
    """Forms of a topic for the title templates: {t} with its article, {T} capitalized, {de} « de » + topic."""
    if language == 'en':
        return {'t': topic, 'T': cap(topic), 'de': f'of {topic}'}
    noun, article = topic
    t = f'{article}{noun}' if article.endswith("'") else f'{article} {noun}'
    de = {'le': f'du {noun}', 'les': f'des {noun}'}.get(article, f'de {t}')
    return {'t': t, 'T': cap(t), 'de': de}


def pdf_bytes(lines: list[str], text: bool = True, ident: str = '') -> bytes:
    """Small valid one-page PDF, with a text layer in Helvetica (WinAnsi), readable by pypdf. `text=False`: a page
    without text, like a scan without character recognition."""
    def esc(s: str) -> bytes:
        return s.encode('cp1252', 'replace').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
    wrapped = []
    for line in lines:
        while len(line) > 88:
            cut = line.rfind(' ', 0, 88)
            cut = cut if cut > 0 else 88
            wrapped.append(line[:cut])
            line = line[cut:].lstrip()
        wrapped.append(line)
    if text:
        content = b'BT /F1 11 Tf 14 TL 56 780 Td ' + b''.join(b'(' + esc(w) + b') Tj T* ' for w in wrapped) + b'ET'
    else:
        content = b'0.6 g 56 300 480 460 re f'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R '
               b'/Resources << /Font << /F1 5 0 R >> >> >>',
               b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    out, offsets = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n' + (f'% {ident}\n'.encode() if ident else b''), []
    for i, o in enumerate(objects, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return out


# --- Works (what the sources know) and the library built from them --------------------------------------------


@dataclass
class Work:
    kind: str  # journalArticle, book, bookSection, thesis, report
    title: str
    authors: list[tuple[str, str]]
    year: int
    theme: str
    abstract: str = ''
    journal: str = ''
    issn: str = ''
    volume: str = ''
    issue: str = ''
    pages: str = ''
    doi: str = ''
    isbn: str = ''
    publisher: str = ''
    place: str = ''
    book_title: str = ''
    editors: list[tuple[str, str]] = field(default_factory=list)
    n_pages: str = ''
    university: str = ''


class World:
    def __init__(self, language: str, seed: int, type_fields: dict[str, list[str]], today: date | None = None):
        self.lang, self.rng, self.type_fields = language, random.Random(seed), type_fields
        self.today = today or date.today()
        self.version = 0
        self.items: dict[str, dict] = {}
        self.collections: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
        self.searches: dict[str, dict] = {}
        self.files: set[str] = set()  # attachments whose file is stored on zotero.org
        self.disk: dict[str, tuple[str, bytes | None]] = {}  # attachment key -> (file name, content or None)
        self.online_only: dict[str, bytes] = {}  # attachment key -> content of a file only on zotero.org
        self.used_keys: set[str] = set()
        self.titles: set[str] = set()
        self.works: list[Work] = []
        self.sources = dict(crossref={}, openalex={}, handles=[], bnf={}, sudoc={}, openlibrary={})
        self.notes: list[str] = []  # what was planted, for the bench's own summary

    # Keys, versions, dates

    def key(self) -> str:
        while (k := ''.join(self.rng.choice(ALPHABET) for _ in range(8))) in self.used_keys:
            pass
        self.used_keys.add(k)
        return k

    def bump(self) -> int:
        self.version += 1
        return self.version

    def added(self, recent: bool = False) -> str:
        if recent:
            d = datetime.combine(self.today - timedelta(days=self.rng.randint(1, 6)), datetime.min.time())
        else:
            d = datetime(2016, 1, 1) + timedelta(days=self.rng.randint(0, 3600))
        d += timedelta(seconds=self.rng.randint(8 * 3600, 20 * 3600))
        return d.strftime('%Y-%m-%dT%H:%M:%SZ')

    # People and titles

    def person(self) -> tuple[str, str]:
        last = LAST_FR if self.lang == 'fr' else LAST_EN
        first = FIRST_FR if self.lang == 'fr' else FIRST_EN
        return self.rng.choice(last), self.rng.choice(first)

    def people(self) -> list[tuple[str, str]]:
        n = self.rng.choices([1, 2, 3], weights=[6, 3, 1])[0]
        res = []
        while len(res) < n:
            p = self.person()
            if p[0] not in {r[0] for r in res}:
                res.append(p)
        return res

    def title(self, theme: dict) -> tuple[str, dict]:
        for _ in range(200):
            topic = self.rng.choice(theme['topics'])
            f = phrases(self.lang, topic) | {'p': self.rng.choice(theme['publics'])}
            t = self.rng.choice(TITLES[self.lang]).format(**f)
            if t not in self.titles:
                self.titles.add(t)
                return t, f
        raise RuntimeError('not enough title combinations')

    def doi(self, theme: dict, year: int) -> str:
        return f'{DOI_PREFIX}/{theme["id"]}.{year}.{self.rng.randint(100, 9999):04d}'

    # Works

    def make_works(self) -> None:
        pattern = ['journalArticle'] * 7 + ['book'] * 3 + ['bookSection'] * 2
        for theme in THEMES[self.lang]:
            vol_f = phrases(self.lang, self.rng.choice(theme['topics']))
            volume_title = self.rng.choice(VOLUMES[self.lang]).format(**vol_f)
            volume_editors = self.people()[:2]
            volume_year = self.rng.randint(2005, 2020)
            volume_publisher = self.rng.choice(PUBLISHERS[self.lang])
            for kind in pattern:
                t, f = self.title(theme)
                w = Work(kind, t, self.people(), self.rng.randint(1995, 2024), theme['id'],
                         ABSTRACT[self.lang].format(**f))
                if kind == 'journalArticle':
                    w.journal, w.issn = self.rng.choice(theme['journals'])
                    w.volume, w.issue = str(self.rng.randint(12, 64)), str(self.rng.randint(1, 4))
                    first = self.rng.randint(5, 300)
                    w.pages = f'{first}-{first + self.rng.randint(12, 30)}'
                    w.doi = self.doi(theme, w.year)
                elif kind == 'book':
                    w.year = self.rng.randint(1964, 2022)
                    w.publisher, w.place = self.rng.choice(PUBLISHERS[self.lang])
                    w.isbn = isbn13(self.rng, '9782' if self.lang == 'fr' else '9781')
                    w.n_pages = str(self.rng.randint(180, 520))
                else:
                    w.book_title, w.editors, w.year = volume_title, volume_editors, volume_year
                    w.publisher, w.place = volume_publisher
                    first = self.rng.randint(9, 300)
                    w.pages = f'{first}-{first + self.rng.randint(15, 25)}'
                    w.doi = self.doi(theme, w.year)
                self.works.append(w)
        self.theme_of = {t['id']: t for t in THEMES[self.lang]}

    def publish(self, w: Work, crossref: bool = True, openalex: bool = False) -> None:
        """Record of the work in the sources: Crossref (or OpenAlex alone) for an article or a chapter with a DOI,
        the BnF and the Sudoc (French ISBN) or Open Library for a book."""
        if w.doi and crossref:
            m = {'DOI': w.doi, 'type': {'journalArticle': 'journal-article', 'bookSection': 'book-chapter'}.get(
                    w.kind, 'book'), 'title': [w.title], 'issued': {'date-parts': [[w.year]]},
                 'author': [{'family': a, 'given': b} for a, b in w.authors],
                 'container-title': [w.journal or w.book_title] if (w.journal or w.book_title) else [],
                 'language': self.lang, 'abstract': f'<jats:p>{w.abstract}</jats:p>'}
            for k, v in (('volume', w.volume), ('issue', w.issue), ('page', w.pages), ('publisher', w.publisher),
                         ('publisher-location', w.place)):
                if v:
                    m[k] = v
            if w.issn:
                m['ISSN'] = [w.issn]
            if w.editors:
                m['editor'] = [{'family': a, 'given': b} for a, b in w.editors]
            self.sources['crossref'][w.doi.lower()] = m
        elif w.doi and openalex:
            first, _, last = w.pages.partition('-')
            self.sources['openalex'][w.doi.lower()] = {
                'doi': f'https://doi.org/{w.doi}', 'title': w.title, 'display_name': w.title,
                'type': 'article', 'publication_year': w.year, 'publication_date': f'{w.year}-01-01',
                'authorships': [{'author': {'display_name': f'{b} {a}'}} for a, b in w.authors],
                'primary_location': {'source': {'display_name': w.journal, 'issn': [w.issn] if w.issn else []}},
                'biblio': {'volume': w.volume, 'issue': w.issue, 'first_page': first, 'last_page': last},
                'language': self.lang}
        if w.isbn and w.kind == 'book':
            if self.lang == 'fr':
                from fake_sources import unimarc_record
                a = w.authors[0]
                rec = unimarc_record(w.title, author=(a[0], a[1]), year=str(w.year), publisher=w.publisher,
                                     place=w.place, isbn=hyphenate(w.isbn), pages=f'{w.n_pages} p.',
                                     collection='', language='fre')
                self.sources['bnf'][w.isbn] = rec
                self.sources['sudoc'][w.isbn] = unimarc_record(
                    w.title, author=(a[0], a[1]), year=str(w.year), publisher=w.publisher, place=w.place,
                    isbn=hyphenate(w.isbn), pages=f'{w.n_pages} p.', collection='', language='fre', xml_prefix='')
            else:
                self.sources['openlibrary'][w.isbn] = {
                    'title': w.title, 'publish_date': str(w.year), 'publishers': [w.publisher],
                    'publish_places': [w.place], 'isbn_13': [w.isbn], 'number_of_pages': int(w.n_pages or 0),
                    'authors': [{'key': f'/authors/{b} {a}'} for a, b in w.authors]}

    # Library objects

    def collection(self, name: str, parent: str | None = None) -> str:
        k = self.key()
        self.collections[k] = {'key': k, 'version': self.bump(), 'name': name, 'parentCollection': parent or False,
                               'relations': {}}
        return k

    def item(self, type_: str, fields: dict, creators: list[dict], tags=(), collections=(), recent=False,
             **extra) -> str:
        k = extra.pop('key', None) or self.key()
        d = {'key': k, 'version': self.bump(), 'itemType': type_}
        d.update({f: '' for f in self.type_fields.get(type_, [])})
        d.update({f: v for f, v in fields.items() if f in d or f in ('dateAdded',)})
        d['creators'] = creators
        d['tags'] = [{'tag': t} if isinstance(t, str) else {'tag': t[0], 'type': t[1]} for t in tags]
        d['collections'] = list(collections)
        d['relations'] = {}
        d.setdefault('dateAdded', self.added(recent))
        d['dateModified'] = d['dateAdded']
        d.update(extra)
        self.items[k] = d
        return k

    def attachment(self, parent: str, name: str, content: bytes | None, mode: str = 'imported_file',
                   online: bool = True, title: str = 'PDF', tags=(), path: str = '', url: str = '',
                   content_type: str = 'application/pdf', note: str = '', on_disk: bool = True) -> str:
        """`on_disk=False`: a file stored on zotero.org only, not yet downloaded by Zotero."""
        k = self.key()
        d = {'key': k, 'version': self.bump(), 'itemType': 'attachment', 'parentItem': parent, 'linkMode': mode,
             'title': title, 'accessDate': '', 'url': url, 'note': note, 'contentType': content_type,
             'charset': '', 'tags': [{'tag': t} for t in tags], 'relations': {},
             'dateAdded': self.items[parent]['dateAdded'], 'dateModified': self.items[parent]['dateAdded']}
        if mode in ('imported_file', 'imported_url'):
            d.update(filename=name, md5='', mtime=0)
            if on_disk:
                self.disk[k] = (name, content)
            elif content is not None:
                self.online_only[k] = content
            if online:
                self.files.add(k)
        elif mode == 'linked_file':
            d['path'] = path
        self.items[k] = d
        return k

    def note(self, html: str, parent: str | None = None, collections=(), tags=()) -> str:
        k = self.key()
        d = {'key': k, 'version': self.bump(), 'itemType': 'note', 'note': html, 'tags': [{'tag': t} for t in tags],
             'relations': {}, 'dateAdded': self.added(), 'dateModified': self.added()}
        if parent:
            d['parentItem'] = parent
        else:
            d['collections'] = list(collections)
        self.items[k] = d
        return k

    def annotation(self, attachment: str, text: str) -> str:
        k = self.key()
        self.items[k] = {'key': k, 'version': self.bump(), 'itemType': 'annotation', 'parentItem': attachment,
                         'annotationType': 'highlight', 'annotationText': text, 'annotationComment': '',
                         'annotationColor': '#ffd400', 'annotationPageLabel': '1',
                         'annotationSortIndex': '00000|000100|00200', 'annotationPosition': '{}', 'tags': [],
                         'relations': {}, 'dateAdded': self.added(), 'dateModified': self.added()}
        return k


def creators_of(w: Work, first_name: bool = True) -> list[dict]:
    res = [{'creatorType': 'editor', 'firstName': b, 'lastName': a} for a, b in w.editors] if w.kind == 'bookSection' else []
    res += [{'creatorType': 'author', 'firstName': b if first_name else '', 'lastName': a} for a, b in w.authors]
    return res


def first_creator(w: Work, language: str) -> str:
    names = [a for a, _ in w.authors]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f'{names[0]} {CONJUNCTION[language]} {names[1]}'
    return f'{names[0]} et al.'


def template_name(w: Work, language: str, title: str | None = None) -> str:
    """Name given by Zotero's default template, for a simple title (no characters Zotero would remove)."""
    t = (title or w.title)[:100]
    t = re.sub(r'[\\/?*:|"<>]', '', t).strip()  # Zotero removes these characters without closing up the spaces
    return f'{first_creator(w, language)} - {w.year} - {t}.pdf'


def citation_key(w: Work, year: int | None = None) -> str:
    """Approximation of Better BibTeX's `auth.lower + shorttitle(3,3) + year`."""
    stop = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'to', 'for', 'le', 'la', 'les', 'l', 'de', 'des', 'du', 'd',
            'et', 'en', 'un', 'une', 'au', 'aux', 'ce', 'que', 'its', 'as', 'what', 'through', 'since'}
    words = [x for x in re.findall(r"[^\W\d_]+", ascii_fold(w.title)) if x.lower() not in stop]
    author = re.sub(r'[^a-z]', '', ascii_fold(w.authors[0][0]).lower()) if w.authors else ''
    return author + ''.join(x[:1].upper() + x[1:].lower() for x in words[:3]) + str(year or w.year)


def pdf_for(w: Work, language: str) -> bytes:
    by = ', '.join(f'{b} {a}' for a, b in w.authors)
    where = (f'{w.journal}, {w.volume}({w.issue}), {w.year}, p. {w.pages}' if w.journal else
             f'{w.book_title}, {w.year}' if w.book_title else f'{w.publisher}, {w.place}, {w.year}')
    head = 'Résumé' if language == 'fr' else 'Abstract'
    return pdf_bytes([w.title, by, where, '', head, w.abstract] + ([f'DOI {w.doi}'] if w.doi else []))


def item_fields(w: Work, language: str) -> dict:
    f = {'title': w.title, 'date': str(w.year), 'abstractNote': w.abstract if w.abstract else '',
         'language': language}
    if w.kind == 'journalArticle':
        f.update(publicationTitle=w.journal, volume=w.volume, issue=w.issue, pages=w.pages, DOI=w.doi, ISSN=w.issn)
    elif w.kind == 'book':
        f.update(publisher=w.publisher, place=w.place, ISBN=hyphenate(w.isbn) if w.isbn else '', numPages=w.n_pages)
    elif w.kind == 'bookSection':
        f.update(bookTitle=w.book_title, publisher=w.publisher, place=w.place, pages=w.pages, DOI=w.doi)
    elif w.kind == 'thesis':
        f.update(university=w.university, thesisType='Thèse de doctorat' if language == 'fr' else 'PhD Thesis',
                 numPages=w.n_pages)
    elif w.kind == 'report':
        f.update(institution=w.publisher, place=w.place)
    return f


def generate(language: str, seed: int, type_fields: dict[str, list[str]], today: date | None = None) -> World:
    W = World(language, seed, type_fields, today)
    rng = W.rng
    W.make_works()
    fr = language == 'fr'
    habits = HABITS[language]

    # Old collection tree.
    col = {}
    for name, parent, _ in TREE[language]:
        col[name] = W.collection(name, col[parent] if parent else None)
    by_theme: dict[str, list[str]] = {}
    for name, _, themes in TREE[language]:
        for t in themes:
            by_theme.setdefault(t, []).append(name)
    catch_all, to_read_col = TREE[language][9][0], TREE[language][0][0]
    projects = [n for n, p, _ in TREE[language] if p in (TREE[language][1][0], TREE[language][5][0])]

    articles = [w for w in W.works if w.kind == 'journalArticle']
    books = [w for w in W.works if w.kind == 'book']
    chapters = [w for w in W.works if w.kind == 'bookSection']
    rng.shuffle(articles)
    rng.shuffle(books)
    rng.shuffle(chapters)

    # Scenarios of step 3, on distinct works.
    sc: dict[int, str] = {}
    take = iter(articles)
    for name, n in (('doi_missing', 4), ('openalex_only', 1), ('doi_url', 1), ('doi_prefix', 1), ('doi_trailing', 1),
                    ('doi_in_url_field', 1), ('doi_unknown', 1), ('doi_wrong', 1), ('fields_missing', 6),
                    ('type_document', 2), ('type_webpage', 1), ('no_language', 3)):
        for _ in range(n):
            sc[id(next(take))] = name
    take_b = iter(books)
    for name, n in (('book_fields_missing', 4), ('isbn_invalid', 1), ('no_isbn', 2)):
        for _ in range(n):
            sc[id(next(take_b))] = name
    sc[id(chapters[0])] = 'chapter_as_book'
    sc[id(chapters[1])] = 'booktitle_missing'

    # Sources: every work with a DOI is known, except the unknown DOI and the OpenAlex-only article.
    for w in W.works:
        s = sc.get(id(w), '')
        W.publish(w, crossref=s != 'openalex_only', openalex=s == 'openalex_only')
    W.sources['handles'] = [f'{DOI_PREFIX}/datacite.2019.0042']  # registered elsewhere, no metadata

    # Citation keys: most items carry one, some are missing (Better BibTeX fills them), some collide.
    key_of: dict[int, str] = {}
    for w in W.works:
        if rng.random() < 0.75:
            key_of[id(w)] = citation_key(w)
    # Two distinct works by the same author the same year with an old author-year key, and a case variant.
    a1, a2 = articles[-1], articles[-2]
    a2.authors[0], a2.year = a1.authors[0], a1.year
    legacy = re.sub(r'[^a-z]', '', ascii_fold(a1.authors[0][0]).lower()) + str(a1.year)
    key_of[id(a1)] = key_of[id(a2)] = legacy
    b1, b2 = articles[-3], articles[-4]
    b2.authors[0], b2.year = b1.authors[0], b1.year
    base = re.sub(r'[^A-Za-z]', '', ascii_fold(b1.authors[0][0])) + str(b1.year)
    key_of[id(b1)], key_of[id(b2)] = base, base.lower()
    for w in (a1, a2, b1, b2):  # their DOI date follows the new year
        if w.doi:
            old = w.doi
            w.doi = f'{DOI_PREFIX}/{w.theme}.{w.year}.{old.rsplit(".", 1)[1]}'
            m = W.sources['crossref'].pop(old.lower(), None)
            if m:
                m['DOI'], m['issued'], m['author'] = w.doi, {'date-parts': [[w.year]]}, \
                    [{'family': a, 'given': b} for a, b in w.authors]
                W.sources['crossref'][w.doi.lower()] = m
    extra_lines = {}  # Extra lines « Citation Key: » left by Better BibTeX 7
    with_key = [w for w in W.works if id(w) in key_of and w not in (a1, a2, b1, b2)]
    for i, w in enumerate(with_key[:5]):
        if i < 2:
            extra_lines[id(w)] = key_of.pop(id(w))  # native field empty, key only in Extra
        elif i < 4:
            extra_lines[id(w)] = key_of[id(w)]  # repeats the native key
        else:
            extra_lines[id(w)] = key_of[id(w)] + 'Old'  # differs from the native key

    # Tags.
    def tags_for(w: Work, i: int) -> list:
        theme = W.theme_of[w.theme]
        res: list = []
        if rng.random() < 0.4:
            res += [(t, 1) for t in rng.sample(theme['auto'], k=min(len(theme['auto']), rng.randint(2, 4)))]
        r = rng.random()
        if r < 0.15:
            res.append(rng.choice(habits['to_read']))
        elif r < 0.25:
            res.append(rng.choice(habits['read']))
        elif r < 0.28:
            res.append(habits['reading'][0])
        if rng.random() < 0.08:
            res.append(rng.choice(habits['marks']))
        if theme['id'] == 'meth' and rng.random() < 0.6:
            res.append(rng.choice(habits['variants'][0]))
        if theme['id'] == 'educ' and rng.random() < 0.4:
            res.append(rng.choice(habits['variants'][1]))
        if rng.random() < 0.18:
            res.append(rng.choice(theme['concepts']))
        return res

    def place(w: Work) -> list[str]:
        r = rng.random()
        if r < 0.1:
            return []
        names = by_theme.get(w.theme, [])
        res = [col[rng.choice(names)]] if names else []
        if rng.random() < 0.15:
            res.append(col[catch_all])
        if rng.random() < 0.12:
            res.append(col[to_read_col])
        if w.theme in ('educ', 'meth') and rng.random() < 0.2:
            res.append(col[rng.choice(projects)])
        return list(dict.fromkeys(res))

    item_of: dict[int, str] = {}
    pdf_of: dict[int, str] = {}
    for i, w in enumerate(W.works):
        s = sc.get(id(w), '')
        f = item_fields(w, language)
        type_ = w.kind
        if s == 'doi_missing' or s == 'openalex_only':
            f['DOI'] = ''
        elif s == 'doi_url':
            f['DOI'] = f'https://doi.org/{w.doi}'
        elif s == 'doi_prefix':
            f['DOI'] = f'doi:{w.doi}'
        elif s == 'doi_trailing':
            f['DOI'] = f'{w.doi}.'
        elif s == 'doi_in_url_field':
            f['DOI'], f['url'] = '', f'https://doi.org/{w.doi}'
        elif s == 'doi_unknown':
            f['DOI'] = w.doi + '9'  # typo: this DOI exists nowhere
        elif s == 'doi_wrong':
            other = next(x for x in articles if x is not w and sc.get(id(x), '') == '')
            f['DOI'] = other.doi
        elif s == 'fields_missing':
            for k in rng.sample(['volume', 'issue', 'pages', 'publicationTitle', 'ISSN'], k=3):
                f[k] = ''
        elif s == 'type_document':
            type_ = 'document'
            f['publisher'] = w.journal
        elif s == 'type_webpage':
            type_ = 'webpage'
            f['websiteTitle'], f['url'] = w.journal, f'https://revues.example.org/{w.doi.split("/")[1]}'
        elif s == 'no_language':
            f['language'] = ''
        elif s == 'book_fields_missing':
            f['publisher'] = f['place'] = ''
            f['date'] = ''
        elif s == 'isbn_invalid':
            f['ISBN'] = f['ISBN'][:-1] + str((int(f['ISBN'][-1]) + 3) % 10)
        elif s == 'no_isbn':
            f['ISBN'] = ''
        elif s == 'chapter_as_book':
            type_ = 'book'
            f.pop('bookTitle', None)
            f['publisher'] = w.publisher
        elif s == 'booktitle_missing':
            f['bookTitle'] = ''
        if rng.random() < 0.3 and type_ == 'journalArticle':
            f['abstractNote'] = ''
        extra = []
        if id(w) in extra_lines:
            extra.append(f'Citation Key: {extra_lines[id(w)]}')
        if rng.random() < 0.06:
            extra.append('Lu en 2019' if fr else 'Read in 2019')
        f['extra'] = '\n'.join(extra)
        f['citationKey'] = key_of.get(id(w), '')
        cr = creators_of(w)
        if type_ == 'book' and w.kind == 'bookSection':
            cr = [c for c in cr if c['creatorType'] == 'author']
        k = W.item(type_, f, cr, tags_for(w, i), place(w))
        item_of[id(w)] = k
        # Attached file: most items have a PDF, some only a link, a few nothing.
        r = rng.random()
        if r < 0.72:
            name = template_name(w, language) if rng.random() < 0.45 else rng.choice(MESSY_NAMES)
            pdf_of[id(w)] = W.attachment(k, name, pdf_for(w, language), title='PDF' if fr else 'Full Text PDF')
        elif r < 0.8 and w.kind == 'journalArticle':
            W.attachment(k, '', None, mode='linked_url', title='Snapshot' if not fr else 'Version en ligne',
                         url=f'https://revues.example.org/{(w.doi or "x/y").split("/")[1]}', content_type='')
    W.notes.append(f'{len(W.works)} works, scenarios: {sorted(set(sc.values()))}')

    # Keywords imported with two records: many rare manual tags.
    for w in rng.sample([w for w in W.works if w.theme == 'educ'], 2):
        W.items[item_of[id(w)]]['tags'] += [{'tag': t} for t in rng.sample(habits['keywords'], 9)]

    # --- Duplicates ---------------------------------------------------------------------------------------------
    plain = [w for w in articles if sc.get(id(w), '') == '' and w not in (a1, a2, b1, b2)]
    used = set()

    def pick(pool):
        w = next(x for x in pool if id(x) not in used)
        used.add(id(w))
        return w

    def copy_of(w: Work, f_changes: dict | None = None, creators=None, type_=None, pdf=False, tags=(), cols=None,
                name=None):
        d = W.items[item_of[id(w)]]
        f = {k: v for k, v in d.items() if k not in ('key', 'version', 'itemType', 'creators', 'tags', 'collections',
                                                      'relations', 'dateAdded', 'dateModified')}
        f.update(f_changes or {})
        k = W.item(type_ or d['itemType'], f, creators if creators is not None else d['creators'], tags,
                   cols if cols is not None else place(w))
        if pdf:
            W.attachment(k, name or rng.choice(MESSY_NAMES), pdf_for(w, language), title='PDF')
        return k

    # Certain: same DOI and same title, imported twice (one without PDF, other collections).
    for _ in range(2):
        w = pick(plain)
        copy_of(w, {'abstractNote': '', 'citationKey': W.items[item_of[id(w)]]['citationKey']},
                tags=[(t, 1) for t in W.theme_of[w.theme]['auto'][:2]])
    # Certain: same DOI, both with the same PDF (identical files across the two records).
    w = pick(plain)
    if id(w) not in pdf_of:
        pdf_of[id(w)] = W.attachment(item_of[id(w)], template_name(w, language), pdf_for(w, language), title='PDF')
    copy_of(w, pdf=True, name='fulltext.pdf')
    # Certain: identical title, creators and year, no DOI, three copies (report imported three times).
    rep = Work('report', 'Rapport final du programme Territoires et réussite éducative' if fr else
               'Final report of the Territories and Educational Attainment programme',
               [W.person()], 2017, 'educ', publisher='Observatoire régional' if fr else 'Regional Observatory',
               place='Lille' if fr else 'Leeds')
    rf = item_fields(rep, language)
    first_rep = W.item('report', rf, creators_of(rep), (), [col[by_theme['educ'][0]]])
    W.attachment(first_rep, template_name(rep, language), pdf_for(rep, language), title='PDF')
    for _ in range(2):
        W.item('report', dict(rf), creators_of(rep), (), [])
    # Certain: same ISBN, the copy lacks the publisher.
    bk = next(b for b in books if sc.get(id(b), '') == '')
    used.add(id(bk))
    copy_of(bk, {'publisher': '', 'place': ''}, cols=[col[catch_all]])
    # Doubtful: same DOI, title of the copy without its subtitle.
    w = next(x for x in plain if id(x) not in used and ':' in x.title)
    used.add(id(w))
    copy_of(w, {'title': w.title.split(':')[0].strip()})
    # Doubtful: same long title and year, the copy has an extra author and no first names.
    w = pick(plain)
    copy_of(w, {'DOI': ''}, creators=[{'creatorType': 'author', 'firstName': '', 'lastName': a} for a, _ in w.authors]
            + [{'creatorType': 'author', 'firstName': '', 'lastName': W.person()[0]}])
    # Doubtful: same ISBN, other year (reprint).
    bk2 = next(b for b in books if sc.get(id(b), '') == '' and id(b) not in used)
    used.add(id(bk2))
    reprint = bk2.year + 12 if bk2.year + 12 <= 2025 else bk2.year - 9  # the copy is the other edition
    copy_of(bk2, {'date': str(reprint), 'extra': 'Réédition' if fr else 'Reprint'})
    # Lookalikes, distinct: two parts of a same study, same author and year, long common start of title.
    th = W.theme_of['educ']
    long_base = ("Les transformations de l'enseignement supérieur depuis les années 1980 dans les villes moyennes"
                 if fr else 'The transformation of higher education since the 1980s in medium-sized towns of the '
                            'North')
    author = [W.person()]
    for n, part in enumerate(('première partie', 'seconde partie') if fr else ('part one', 'part two')):
        lw = Work('journalArticle', f'{long_base} : {part}' if fr else f'{long_base}: {part}', author, 2011, 'educ',
                  ABSTRACT[language].format(**phrases(language, th['topics'][3]), p=th['publics'][3]),
                  th['journals'][0][0], th['journals'][0][1], '33', str(2 + n), '41-63')
        lw.doi = W.doi(th, 2011)
        W.works.append(lw)
        W.publish(lw)
        k = W.item('journalArticle', item_fields(lw, language) | {'citationKey': citation_key(lw)}, creators_of(lw),
                   (), [col[by_theme['educ'][1]]])
        W.attachment(k, template_name(lw, language), pdf_for(lw, language), title='PDF')
    # A PDF attached to the wrong record: the file of one article also sits on another one.
    with_pdf = [w for w in plain if id(w) in pdf_of and id(w) not in used]
    src, dst = with_pdf[0], with_pdf[1]
    used.update({id(src), id(dst)})
    W.attachment(item_of[id(dst)], 'article(1).pdf', pdf_for(src, language), title='PDF')
    # Two identical copies of the same PDF on one record.
    w = with_pdf[2]
    used.add(id(w))
    W.attachment(item_of[id(w)], 'copie.pdf' if fr else 'copy.pdf', pdf_for(w, language), title='PDF')

    # --- Theses, files, notes, trash, private item, new items ---------------------------------------------------
    for i in range(2):
        tw = Work('thesis', W.title(W.theme_of['hist' if i else 'educ'])[0], [W.person()], 2009 + 5 * i,
                  'hist' if i else 'educ', university='Université de Vallon' if fr else 'University of Harrow',
                  n_pages=str(rng.randint(380, 620)))
        k = W.item('thesis', item_fields(tw, language) | {'citationKey': citation_key(tw)}, creators_of(tw),
                   [rng.choice(habits['to_read'])], [col[by_theme[tw.theme][0]]])
        W.attachment(k, 'these.pdf' if fr else 'thesis.pdf', pdf_bytes([], text=False, ident=k), title='PDF')  # scan, no text
    # Missing files: one only on zotero.org, one lost everywhere, one linked file that moved.
    missing = [w for w in W.works if id(w) in item_of and id(w) not in pdf_of and w.kind == 'journalArticle'][:2]
    W.attachment(item_of[id(missing[0])], template_name(missing[0], language), pdf_for(missing[0], language),
                 online=True, title='PDF', on_disk=False)
    W.attachment(item_of[id(missing[1])], 'article.pdf', None, online=False, title='PDF')
    linked_to = next(w for w in books if id(w) in item_of)
    W.attachment(item_of[id(linked_to)], '', None, mode='linked_file', title='Scan',
                 path='/Users/ancien-poste/Documents/Scans/livre.pdf')
    # Notes: child notes, one standalone note in the dissertation folder, annotations on one PDF.
    for w in rng.sample([w for w in W.works if id(w) in item_of], 4):
        W.note('<p>' + ('Relire la partie méthodologique, comparer avec mon terrain.' if fr else
                        'Reread the methods section, compare with my fieldwork.') + '</p>', parent=item_of[id(w)])
    W.note('<h1>' + ('Plan du chapitre 2' if fr else 'Outline of chapter 2') + '</h1><p>1. ' +
           ('Terrain' if fr else 'Fieldwork') + '</p>', collections=[col[TREE[language][1][0]]])
    annotated = next(iter(pdf_of.values()))
    for text in (('Premier passage surligné.', 'Second passage surligné.') if fr else
                 ('First highlighted passage.', 'Second highlighted passage.')):
        W.annotation(annotated, text)
    # Trash: a record deleted but not emptied, which still carries a status tag.
    tw = Work('journalArticle', W.title(W.theme_of['philo'])[0], [W.person()], 2003, 'philo')
    k = W.item('journalArticle', item_fields(tw, language), creators_of(tw), [habits['to_read'][0]], [])
    W.items[k]['deleted'] = True
    # Confidential item: an evaluation report carrying the privacy tag of the library's profile.
    pw = Work('report', "Rapport d'évaluation du dossier de candidature de M. X" if fr else
              "Evaluation report on Mr X's application file", [W.person()], 2024, 'educ',
              publisher='Comité de sélection' if fr else 'Selection committee', place='')
    k = W.item('report', item_fields(pw, language), creators_of(pw), [PRIVATE_TAG[language]],
               [col[TREE[language][1][0]]])
    W.attachment(k, 'evaluation_confidentielle.pdf' if fr else 'confidential_evaluation.pdf',
                 pdf_bytes(['CONFIDENTIEL' if fr else 'CONFIDENTIAL', pw.title, 'Avis défavorable.' if fr else
                            'Unfavourable opinion.']), title='PDF')
    W.note('<p>' + ('Ne pas diffuser.' if fr else 'Do not circulate.') + '</p>', parent=k)
    # New items saved in the last days with the connector, outside any collection, with automatic tags and a file
    # already named by Zotero. One of them is a duplicate of an existing record (same DOI).
    for i in range(4):
        theme = W.theme_of[rng.choice(list(W.theme_of))]
        t, ff = W.title(theme)
        nw = Work('journalArticle', t, W.people(), rng.randint(2023, 2026), theme['id'],
                  ABSTRACT[language].format(**ff), theme['journals'][0][0], theme['journals'][0][1],
                  str(rng.randint(40, 70)), '1', f'{i + 1}-{i + 25}')
        nw.doi = W.doi(theme, nw.year)
        W.works.append(nw)
        W.publish(nw)
        k = W.item('journalArticle', item_fields(nw, language) | {'abstractNote': ''}, creators_of(nw),
                   [(a, 1) for a in theme['auto'][:3]], [], recent=True)
        W.attachment(k, template_name(nw, language), pdf_for(nw, language), title='Full Text PDF')
    dup_new = next(w for w in plain if id(w) not in used)
    used.add(id(dup_new))
    d = W.items[item_of[id(dup_new)]]
    k = W.item(d['itemType'], {f: d[f] for f in ('title', 'date', 'DOI', 'publicationTitle', 'volume', 'issue',
                                                 'pages', 'ISSN', 'language')},
               d['creators'], [(t, 1) for t in W.theme_of[dup_new.theme]['auto'][:2]], [], recent=True)
    W.attachment(k, template_name(dup_new, language), pdf_for(dup_new, language), title='Full Text PDF')

    # Library settings: a colored tag from another habit, a saved search on a status tag.
    W.settings['tagColors'] = {'value': [{'name': 'important', 'color': '#FF6666'}], 'version': W.bump()}
    sk = W.key()
    W.searches[sk] = {'key': sk, 'version': W.bump(), 'name': 'À lire' if fr else 'To read',
                      'conditions': [{'condition': 'tag', 'operator': 'is', 'value': habits['to_read'][0]}]}
    return W
