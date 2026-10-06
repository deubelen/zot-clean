"""Fausses réponses de Crossref, OpenAlex et doi.org, sans réseau (D45)."""

import urllib.parse

import httpx2


def crossref_work(doi, titre, auteurs=(('Özgen', 'Emre'),), annee=2002, type_='journal-article', **autres):
    m = {'DOI': doi, 'type': type_, 'title': [titre], 'issued': {'date-parts': [[annee, 8, 1]]},
         'author': [{'family': f, 'given': g} for f, g in auteurs]}
    m.update(autres)
    return m


def notice_unimarc(titre, auteur=('Bourdieu', 'Pierre'), annee='1979', editeur='Éditions de Minuit', lieu='Paris',
                   isbn='2-7073-0275-9', pages='670 p.', collection='Le Sens commun', langue='fre',
                   traducteur=None, balise='mxc:'):
    """Notice UNIMARC en XML, au format de la BnF (préfixe mxc:) ou du Sudoc (sans préfixe)."""
    def champ(tag, *sous):
        return (f'<{balise}datafield tag="{tag}" ind1=" " ind2=" ">'
                + ''.join(f'<{balise}subfield code="{c}">{v}</{balise}subfield>' for c, v in sous if v)
                + f'</{balise}datafield>')
    corps = [champ('010', ('a', isbn)), champ('101', ('a', langue)), champ('200', ('a', titre)),
             champ('210', ('a', lieu), ('c', editeur), ('d', annee)), champ('215', ('a', pages)),
             champ('225', ('a', collection)), champ('700', ('a', auteur[0]), ('b', auteur[1]), ('4', '070'))]
    if traducteur:
        corps.append(champ('702', ('a', traducteur[0]), ('b', traducteur[1]), ('4', '730')))
    return f'<{balise}record>' + ''.join(corps) + f'</{balise}record>'


def reponse_sru(notices):
    return ('<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/"><srw:records>'
            + ''.join(f'<srw:record><srw:recordData>{n}</srw:recordData></srw:record>' for n in notices)
            + '</srw:records></srw:searchRetrieveResponse>')


class FauxServices:
    def __init__(self):
        self.crossref: dict[str, dict] = {}  # doi en minuscules -> message
        self.crossref_recherche: list[dict] = []  # résultats renvoyés à toute recherche
        self.openalex: dict[str, dict] = {}
        self.openalex_recherche: list[dict] = []
        self.handles: set[str] = set()  # DOI connus de doi.org hors Crossref et OpenAlex
        self.bnf: dict[str, str] = {}  # ISBN en chiffres -> notice
        self.bnf_recherche: list[str] = []
        self.sudoc: dict[str, str] = {}
        self.openlibrary: dict[str, dict] = {}
        self.openlibrary_recherche: list[dict] = []
        self.requetes: list[str] = []

    def ajouter(self, **kw):
        m = crossref_work(**kw)
        self.crossref[m['DOI'].lower()] = m
        return m

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self.traiter))

    def traiter(self, req: httpx2.Request) -> httpx2.Response:
        hote, chemin = req.url.host, urllib.parse.unquote(req.url.path)
        self.requetes.append(f'{hote}{chemin}')
        if hote == 'api.crossref.org':
            if chemin == '/works':
                return httpx2.Response(200, json={'message': {'items': self.crossref_recherche}})
            doi = chemin.removeprefix('/works/').lower()
            if doi in self.crossref:
                return httpx2.Response(200, json={'message': self.crossref[doi]})
            return httpx2.Response(404)
        if hote == 'api.openalex.org':
            if chemin == '/works':
                if any(c in req.url.params.get('search', '') for c in '?.:'):
                    return httpx2.Response(400, json={'error': 'Invalid query parameters'})
                return httpx2.Response(200, json={'results': self.openalex_recherche})
            doi = chemin.removeprefix('/works/doi:').lower()
            if doi in self.openalex:
                return httpx2.Response(200, json=self.openalex[doi])
            return httpx2.Response(404)
        if hote == 'catalogue.bnf.fr':
            q = req.url.params.get('query', '')
            if q.startswith('bib.isbn adj'):
                isbn = q.split('"')[1]
                return httpx2.Response(200, text=reponse_sru([self.bnf[isbn]] if isbn in self.bnf else []))
            return httpx2.Response(200, text=reponse_sru(self.bnf_recherche))
        if hote == 'www.sudoc.fr':
            if chemin.startswith('/services/isbn2ppn/'):
                isbn = chemin.removeprefix('/services/isbn2ppn/').split('&')[0]
                if isbn in self.sudoc:
                    return httpx2.Response(200, json={'sudoc': {'query': {'result': {'ppn': f'P{isbn}'}}}})
                return httpx2.Response(200, json={'sudoc': {'error': 'Aucune notice'}})
            return httpx2.Response(200, text=self.sudoc.get(chemin.strip('/').removesuffix('.xml')[1:], ''))
        if hote == 'openlibrary.org':
            if chemin == '/search.json':
                return httpx2.Response(200, json={'docs': self.openlibrary_recherche})
            if chemin.startswith('/isbn/'):
                d = self.openlibrary.get(chemin.removeprefix('/isbn/').removesuffix('.json'))
                return httpx2.Response(200, json=d) if d else httpx2.Response(404)
            if chemin.startswith('/authors/'):
                return httpx2.Response(200, json={'name': chemin.removeprefix('/authors/').removesuffix('.json')})
            return httpx2.Response(404)
        if hote == 'doi.org':
            doi = chemin.removeprefix('/api/handles/').lower()
            connu = doi in self.handles or doi in self.crossref or doi in self.openalex
            return httpx2.Response(200 if connu else 404, json={'responseCode': 1 if connu else 100})
        return httpx2.Response(404)
